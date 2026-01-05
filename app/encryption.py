"""
Data encryption utilities for protecting sensitive user and portfolio data in Firestore.
Uses Fernet symmetric encryption with keys managed via Google Cloud KMS or environment variables.
"""

import os
import json
import base64
import importlib as _importlib
logging = _importlib.import_module("logging")
from typing import Any, Dict, Optional, Union
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from functools import lru_cache
import hashlib


# Defer STREAMLIT key SHA256 print until runtime when cipher is available
key = None

try:
    logger = logging.getLogger(__name__)
except Exception:
    class _DummyLogger:
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
        def warning(self, *a, **k): print(*a, **k)
        def error(self, *a, **k): print(*a, **k)
    logger = _DummyLogger()

# Encryption key source priority: 1) GCP KMS, 2) Environment variable, 3) Generated (dev only)
ENCRYPTION_KEY_ENV = "PERFIENT_ENCRYPTION_KEY"
KMS_KEY_NAME = os.getenv("PERFIENT_KMS_KEY_NAME")  # Format: projects/PROJECT/locations/LOCATION/keyRings/RING/cryptoKeys/KEY

# Fields to encrypt in user documents
# NOTE: username is NOT encrypted (used for authentication), but email IS encrypted
ENCRYPTED_USER_FIELDS = [
    "email",  # Encrypted in user document (auth uses username)
    "full_name",
    "phone",
    "address",
    "ssn",
    "tax_id",
    "bank_account",
    "emergency_contact",
    "selected_goals",
    "risk_reaction",
    "investment_priority",
]

# Fields to encrypt in user profile_data (stored in user document)
ENCRYPTED_PROFILE_DATA_FIELDS = [
    "age_range",
    "country",
    "employment_type",
    "currency",
    "gross_income",
    "net_income",
    "fixed_expenses",
    "variable_expenses",
    "cash_and_equivalents",
    "investments",
    "real_estate",
    "other_assets",
    "short_term_debt",
    "long_term_debt",
    "other_liabilities",
    "goal_retirement",
    "goal_house",
    "goal_education",
    "goal_other",
    "risk_tolerance",
    "investment_horizon_years",
    # Range fields (for Twin Lite mode)
    "cash_range",
    "income_range",
    "expense_range",
    "investment_range",
    "property_status",
    "debt_level",
    # Goal-specific fields
    "goal_buy_home",
    "goal_buy_home_horizon",
    "goal_buy_home_importance",
    "goal_retire",
    "goal_retire_horizon",
    "goal_retire_importance",
    "goal_education",
    "goal_education_horizon",
    "goal_education_importance",
    "goal_other",
    "goal_other_horizon",
    "goal_other_importance",
    # User preferences and behavioral data
    "selected_goals",
    "risk_reaction",
    "investment_priority",
]

# Fields to encrypt in PFS documents (financial data)
ENCRYPTED_PFS_FIELDS = [
    "monthly_income",
    "monthly_expenses",
    "gross_income",
    "net_income",
    "fixed_expenses",
    "variable_expenses",
    "cash_and_equivalents",
    "investments",
    "retirement_accounts",
    "real_estate",
    "other_assets",
    "total_assets",
    "credit_card_debt",
    "student_loans",
    "mortgage",
    "short_term_debt",
    "long_term_debt",
    "other_liabilities",
    "total_liabilities",
    "net_worth",
    "monthly_savings",
    "savings_rate",
    "risk_tolerance",
    "investment_horizon_years",
    "goal_type",
    "investment_priority",
]

# Fields to encrypt in portfolio documents
ENCRYPTED_PORTFOLIO_FIELDS = [
    "holdings",  # Entire holdings array
    "total_value",
    "cash_balance",
    "invested_value",
]

# Fields to encrypt in twin documents
ENCRYPTED_TWIN_FIELDS = [
    "latest_pfs",
    "pfs_history",
    "series",  # Time series data (net worth, savings over time)
    "stress_index",
    "financial_health_score",
    "risk_capacity",
    "net_worth_trajectory",
    "monthly_savings",
    "burn_rate",
    "debt_to_income",
    "debt_to_income_ratio",
    "savings_rate",
    "risk_reaction",
    "investment_priority",
    "behavioral_profile",
    "cash_runway_months",
    "emergency_fund_coverage",
    "avg_savings_rate",
    "mode",
    "net_worth_cagr",
    "net_worth_change_pct",
    "savings_rate_trend_pct_per_year",
    "investment_allocation_quality",
]


@lru_cache(maxsize=1)
def get_encryption_key() -> bytes:
    """
    Get or generate encryption key from KMS, environment, or generate new (dev only).
    Cached for performance.
    
    Returns:
        32-byte encryption key for Fernet
    """
    try:
        # Priority 1: Try Google Cloud KMS
        if KMS_KEY_NAME:
            try:
                from google.cloud import kms
                client = kms.KeyManagementServiceClient()
                
                # For simplicity, we'll use a data encryption key (DEK) encrypted by KMS
                # In production, implement proper key rotation and DEK management
                dek = os.getenv("PERFIENT_DEK")  # Data Encryption Key (encrypted by KMS)
                if dek:
                    # Decrypt DEK using KMS
                    response = client.decrypt(
                        request={"name": KMS_KEY_NAME, "ciphertext": base64.b64decode(dek)}
                    )
                    logger.info("Encryption key loaded from KMS")
                    return response.plaintext[:32]  # Use first 32 bytes for Fernet
            except Exception as e:
                logger.warning(f"KMS key retrieval failed: {e}, falling back to env variable")
        
        # Priority 2: Environment variable
        env_key = os.getenv(ENCRYPTION_KEY_ENV)
        if env_key:
            # Derive 32-byte key from environment variable using PBKDF2HMAC
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"perfient_salt_v1",  # Static salt for deterministic key derivation
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(env_key.encode()))
            logger.info("Encryption key derived from environment variable")
            return key
        
        # Priority 3: Generate new key (DEVELOPMENT ONLY - data will be lost on restart)
        if os.getenv("STREAMLIT_DEV_MODE") == "true":
            logger.warning("DEVELOPMENT MODE: Generating temporary encryption key - DO NOT USE IN PRODUCTION")
            return Fernet.generate_key()
        
        raise ValueError(
            "No encryption key configured. Set PERFIENT_ENCRYPTION_KEY environment variable "
            "or configure PERFIENT_KMS_KEY_NAME for production use."
        )
    
    except Exception as e:
        logger.error(f"Failed to get encryption key: {e}")
        raise


@lru_cache(maxsize=1)
def get_cipher() -> Fernet:
    """Get Fernet cipher instance (cached for performance)."""
    key = get_encryption_key()
    return Fernet(key)


def encrypt_value(value: Any) -> str:
    """
    Encrypt a single value (string, number, dict, list) to encrypted string.
    
    Args:
        value: Value to encrypt (will be JSON-serialized first)
    
    Returns:
        Base64-encoded encrypted string with 'enc:' prefix
    """
    if value is None:
        return None
    
    try:
        cipher = get_cipher()
        # Serialize value to JSON, then encrypt
        json_str = json.dumps(value, default=str)
        encrypted_bytes = cipher.encrypt(json_str.encode('utf-8'))
        # Prefix with 'enc:' to identify encrypted values
        return f"enc:{base64.urlsafe_b64encode(encrypted_bytes).decode('utf-8')}"
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise


def decrypt_value(encrypted_value: str) -> Any:
    """
    Decrypt an encrypted value back to original type.
    
    Args:
        encrypted_value: Encrypted string (with 'enc:' prefix)
    
    Returns:
        Decrypted original value (deserialized from JSON)
    """
    if encrypted_value is None:
        return None
    
    # Handle unencrypted values (backward compatibility)
    if not isinstance(encrypted_value, str) or not encrypted_value.startswith("enc:"):
        logger.warning("Attempted to decrypt unencrypted value - returning as-is for backward compatibility")
        return encrypted_value
    
    try:
        cipher = get_cipher()
        # Remove 'enc:' prefix and decode
        encrypted_str = encrypted_value[4:]  # Remove 'enc:' prefix
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_str.encode('utf-8'))
        decrypted_bytes = cipher.decrypt(encrypted_bytes)
        json_str = decrypted_bytes.decode('utf-8')
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        # Return None instead of raising to handle corrupted data gracefully
        return None


def encrypt_document(doc: Dict[str, Any], field_list: list) -> Dict[str, Any]:
    """
    Encrypt specified fields in a document (in-place modification).
    
    Args:
        doc: Document dictionary to encrypt
        field_list: List of field names to encrypt
    
    Returns:
        Modified document with encrypted fields
    """
    if not doc:
        return doc
    
    encrypted_doc = doc.copy()
    
    for field in field_list:
        if field in encrypted_doc and encrypted_doc[field] is not None:
            try:
                # Skip if already encrypted
                if isinstance(encrypted_doc[field], str) and encrypted_doc[field].startswith("enc:"):
                    continue
                
                encrypted_doc[field] = encrypt_value(encrypted_doc[field])
                logger.debug(f"Encrypted field: {field}")
            except Exception as e:
                logger.error(f"Failed to encrypt field {field}: {e}")
                # Keep original value on encryption failure
    
    # Mark document as encrypted
    encrypted_doc["_encrypted"] = True
    encrypted_doc["_encryption_version"] = "v1"
    
    return encrypted_doc


def decrypt_document(doc: Dict[str, Any], field_list: list) -> Dict[str, Any]:
    """
    Decrypt specified fields in a document (in-place modification).
    
    Args:
        doc: Document dictionary with encrypted fields
        field_list: List of field names to decrypt
    
    Returns:
        Modified document with decrypted fields
    """
    if not doc:
        return doc
    
    # Check if document is encrypted
    if not doc.get("_encrypted", False):
        logger.debug("Document not marked as encrypted - returning as-is")
        return doc
    
    decrypted_doc = doc.copy()
    
    for field in field_list:
        if field in decrypted_doc and decrypted_doc[field] is not None:
            try:
                # Only decrypt if it's an encrypted value
                if isinstance(decrypted_doc[field], str) and decrypted_doc[field].startswith("enc:"):
                    decrypted_doc[field] = decrypt_value(decrypted_doc[field])
                    logger.debug(f"Decrypted field: {field}")
            except Exception as e:
                logger.error(f"Failed to decrypt field {field}: {e}")
                # Set to None on decryption failure
                decrypted_doc[field] = None
    
    return decrypted_doc


def encrypt_pfs(pfs_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Encrypt a Personal Financial Statement document.
    
    Args:
        pfs_doc: PFS document to encrypt
    
    Returns:
        Encrypted PFS document
    """
    return encrypt_document(pfs_doc, ENCRYPTED_PFS_FIELDS)


def decrypt_pfs(pfs_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decrypt a Personal Financial Statement document.
    
    Args:
        pfs_doc: Encrypted PFS document
    
    Returns:
        Decrypted PFS document
    """
    return decrypt_document(pfs_doc, ENCRYPTED_PFS_FIELDS)


def encrypt_user_profile(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Encrypt a user profile_data document.
    
    Args:
        user_doc: Profile data dictionary to encrypt
    
    Returns:
        Encrypted profile data
    """
    return encrypt_document(user_doc, ENCRYPTED_PROFILE_DATA_FIELDS)


def decrypt_user_profile(user_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decrypt a user profile_data document.
    
    Args:
        user_doc: Encrypted profile data dictionary
    
    Returns:
        Decrypted profile data
    """
    return decrypt_document(user_doc, ENCRYPTED_PROFILE_DATA_FIELDS)


def encrypt_portfolio(portfolio_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Encrypt a portfolio document.
    
    Args:
        portfolio_doc: Portfolio document to encrypt
    
    Returns:
        Encrypted portfolio document
    """


def encrypt_twin(twin_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Encrypt a Personal Financial Twin document.
    
    Args:
        twin_doc: Twin document to encrypt
    
    Returns:
        Encrypted twin document
    """
    return encrypt_document(twin_doc, ENCRYPTED_TWIN_FIELDS)


def decrypt_twin(twin_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decrypt a Personal Financial Twin document.
    
    Args:
        twin_doc: Encrypted twin document
    
    Returns:
        Decrypted twin document
    """
    return decrypt_document(twin_doc, ENCRYPTED_TWIN_FIELDS)
    return encrypt_document(portfolio_doc, ENCRYPTED_PORTFOLIO_FIELDS)


def decrypt_portfolio(portfolio_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decrypt a portfolio document.
    
    Args:
        portfolio_doc: Encrypted portfolio document
    
    Returns:
        Decrypted portfolio document
    """
    return decrypt_document(portfolio_doc, ENCRYPTED_PORTFOLIO_FIELDS)


def migrate_document_to_encrypted(collection: str, doc_id: str, field_list: list, db=None) -> bool:
    """
    Migrate an existing unencrypted document to encrypted format.
    
    Args:
        collection: Firestore collection name
        doc_id: Document ID
        field_list: List of fields to encrypt
        db: Firestore client (optional, will create if None)
    
    Returns:
        True if migration successful, False otherwise
    """
    try:
        if db is None:
            from google.cloud import firestore
            db = firestore.Client()
        
        doc_ref = db.collection(collection).document(doc_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            logger.warning(f"Document {collection}/{doc_id} does not exist")
            return False
        
        doc_data = doc.to_dict()
        
        # Skip if already encrypted
        if doc_data.get("_encrypted", False):
            logger.info(f"Document {collection}/{doc_id} already encrypted")
            return True
        
        # Encrypt document
        encrypted_doc = encrypt_document(doc_data, field_list)
        
        # Update Firestore
        doc_ref.set(encrypted_doc, merge=True)
        logger.info(f"Successfully migrated {collection}/{doc_id} to encrypted format")
        return True
    
    except Exception as e:
        logger.error(f"Failed to migrate document {collection}/{doc_id}: {e}")
        return False


def setup_encryption_key():
    """
    Helper function to generate and display encryption key for first-time setup.
    Run this once during deployment to generate a secure key.
    """
    key = Fernet.generate_key()
    print("=" * 60)
    print("PERFIENT ENCRYPTION KEY SETUP")
    print("=" * 60)
    print("\n⚠️  IMPORTANT: Store this key securely! Loss of this key means")
    print("   loss of all encrypted data. Never commit to version control.\n")
    print("Add this to your environment variables:")
    print(f"\nPERFIENT_ENCRYPTION_KEY={key.decode('utf-8')}\n")
    print("Or use Google Cloud Secret Manager:")
    print(f"gcloud secrets create perfient-encryption-key --data-file=- <<< '{key.decode('utf-8')}'")
    print("\n" + "=" * 60)
    return key


if __name__ == "__main__":
    # Run key generation helper
    setup_encryption_key()
    try:
        #cipher = get_cipher()
        #key = cipher._signing_key + cipher._encryption_key
        #print("🔥 STREAMLIT KEY SHA256:", hashlib.sha256(key).hexdigest())
        cipher = get_cipher()

        # This reconstructs the actual Fernet key
        key_bytes = cipher._signing_key + cipher._encryption_key
        real_key = base64.urlsafe_b64encode(key_bytes).decode()

        print("REAL_FERNET_KEY =", real_key)
    except Exception as e:
        print("Could not compute STREAMLIT key SHA256:", e)
