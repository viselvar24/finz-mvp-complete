# app/pfs_service.py

from datetime import datetime
from typing import Optional, List, Dict, Any
import logging
import os

from pydantic import BaseModel, Field

# Check if we're in mock mode (for local development)
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"

if not MOCK_MODE:
    from google.cloud import firestore
    db_fs = firestore.Client()
else:
    db_fs = None
    logging.info("Running in MOCK_MODE - Firestore client not initialized")

# Import encryption utilities
try:
    from app.encryption import encrypt_pfs, decrypt_pfs
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    logging.warning("Encryption module not available - data will be stored unencrypted")

logger = logging.getLogger(__name__)

USERS_COLLECTION = "users"


# -----------------------------------------------------
# PFS Schemas
# -----------------------------------------------------

class PFSBase(BaseModel):
    currency: str = "USD"

    # Income & expenses (per month)
    gross_income: float = 0.0
    net_income: float = 0.0
    fixed_expenses: float = 0.0
    variable_expenses: float = 0.0

    # Assets
    cash_and_equivalents: float = 0.0
    investments: float = 0.0
    real_estate: float = 0.0
    other_assets: float = 0.0

    # Liabilities
    short_term_debt: float = 0.0
    long_term_debt: float = 0.0
    other_liabilities: float = 0.0

    # Investor profile
    risk_tolerance: Optional[str] = Field(
        default=None,
        description="conservative | moderate | aggressive | etc.",
    )
    investment_horizon_years: Optional[int] = None
    goal_type: Optional[str] = None  # retirement | house | education | etc.


class PFSCreate(PFSBase):
    pass


class PFSUpdate(BaseModel):
    # All fields optional for PATCH-like update
    currency: Optional[str] = None

    gross_income: Optional[float] = None
    net_income: Optional[float] = None
    fixed_expenses: Optional[float] = None
    variable_expenses: Optional[float] = None

    cash_and_equivalents: Optional[float] = None
    investments: Optional[float] = None
    real_estate: Optional[float] = None
    other_assets: Optional[float] = None

    short_term_debt: Optional[float] = None
    long_term_debt: Optional[float] = None
    other_liabilities: Optional[float] = None

    risk_tolerance: Optional[str] = None
    investment_horizon_years: Optional[int] = None
    goal_type: Optional[str] = None


class PFSOut(PFSBase):
    id: str
    net_worth: float
    monthly_savings: float
    savings_rate: float
    created_at: datetime
    updated_at: datetime


# -----------------------------------------------------
# Internal helpers
# -----------------------------------------------------

def _statements_collection_for_user(user_id: str):
    return (
        db_fs.collection(USERS_COLLECTION)
        .document(user_id)
        .collection("financial_statements")
    )


def _compute_derived(data: Dict[str, Any]) -> Dict[str, Any]:
    total_assets = (
        data.get("cash_and_equivalents", 0.0)
        + data.get("investments", 0.0)
        + data.get("real_estate", 0.0)
        + data.get("other_assets", 0.0)
    )
    total_liabilities = (
        data.get("short_term_debt", 0.0)
        + data.get("long_term_debt", 0.0)
        + data.get("other_liabilities", 0.0)
    )

    net_worth = total_assets - total_liabilities
    net_income = data.get("net_income", 0.0)
    expenses = data.get("fixed_expenses", 0.0) + data.get("variable_expenses", 0.0)
    monthly_savings = max(net_income - expenses, 0.0)
    savings_rate = (monthly_savings / net_income * 100.0) if net_income > 0 else 0.0

    data["net_worth"] = float(net_worth)
    data["monthly_savings"] = float(monthly_savings)
    data["savings_rate"] = float(savings_rate)
    return data


def _doc_to_pfs_out(doc) -> PFSOut:
    d = doc.to_dict()
    
    # Decrypt if encryption is available and document is encrypted
    if ENCRYPTION_AVAILABLE and d.get("_encrypted", False):
        try:
            d = decrypt_pfs(d)
        except Exception as e:
            logger.error(f"Failed to decrypt PFS document {doc.id}: {e}")
            # Continue with encrypted data (will likely fail validation)
    
    d["id"] = doc.id
    return PFSOut(**d)


# -----------------------------------------------------
# CRUD functions (used by FastAPI & Streamlit)
# -----------------------------------------------------

def create_pfs_for_user(user_id: str, payload: PFSCreate) -> PFSOut:
    col = _statements_collection_for_user(user_id)
    now = datetime.utcnow()
    data = payload.dict()
    data = _compute_derived(data)
    data["created_at"] = now
    data["updated_at"] = now

    # Encrypt sensitive financial data before storing
    if ENCRYPTION_AVAILABLE:
        try:
            encrypted_data = encrypt_pfs(data.copy())
            doc_ref = col.document()
            doc_ref.set(encrypted_data)
            data["id"] = doc_ref.id
            logger.info(f"Created encrypted PFS for user {user_id}")
            return PFSOut(**data)
        except Exception as e:
            logger.error(f"Encryption failed, storing unencrypted: {e}")
            doc_ref = col.document()
            doc_ref.set(data)
            data["id"] = doc_ref.id
            return PFSOut(**data)
    else:
        doc_ref = col.document()
        doc_ref.set(data)
        data["id"] = doc_ref.id
        return PFSOut(**data)


def update_pfs_for_user(user_id: str, statement_id: str, payload: PFSUpdate) -> PFSOut:
    col = _statements_collection_for_user(user_id)
    doc_ref = col.document(statement_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise ValueError("PFS document not found")

    existing = snapshot.to_dict()
    
    # Decrypt existing data if encrypted
    if ENCRYPTION_AVAILABLE and existing.get("_encrypted", False):
        try:
            existing = decrypt_pfs(existing)
        except Exception as e:
            logger.error(f"Failed to decrypt existing PFS: {e}")
            raise ValueError("Cannot update encrypted document - decryption failed")
    
    update_data = {k: v for k, v in payload.dict().items() if v is not None}
    existing.update(update_data)
    existing = _compute_derived(existing)
    existing["updated_at"] = datetime.utcnow()

    # Re-encrypt before saving
    if ENCRYPTION_AVAILABLE:
        try:
            encrypted_data = encrypt_pfs(existing.copy())
            doc_ref.set(encrypted_data)
            logger.info(f"Updated encrypted PFS for user {user_id}")
        except Exception as e:
            logger.error(f"Encryption failed during update, storing unencrypted: {e}")
            doc_ref.set(existing)
    else:
        doc_ref.set(existing)
    
    existing["id"] = statement_id
    return PFSOut(**existing)


def get_latest_pfs_for_user(user_id: str) -> Optional[PFSOut]:
    # Mock mode: return dummy data
    if MOCK_MODE:
        from app.mock_data import get_mock_pfs_for_user
        mock_pfs = get_mock_pfs_for_user(user_id or "mock_user_001")
        # Convert MockPFS to PFSOut
        return PFSOut(
            id=mock_pfs.id,
            currency=mock_pfs.currency,
            gross_income=mock_pfs.gross_income,
            net_income=mock_pfs.net_income,
            fixed_expenses=mock_pfs.fixed_expenses,
            variable_expenses=mock_pfs.variable_expenses,
            cash_and_equivalents=mock_pfs.cash_and_equivalents,
            investments=mock_pfs.investments,
            real_estate=mock_pfs.real_estate,
            other_assets=mock_pfs.other_assets,
            short_term_debt=mock_pfs.short_term_debt,
            long_term_debt=mock_pfs.long_term_debt,
            other_liabilities=mock_pfs.other_liabilities,
            risk_tolerance=mock_pfs.risk_tolerance,
            investment_horizon_years=mock_pfs.investment_horizon_years,
            goal_type=mock_pfs.goal_type,
            net_worth=mock_pfs.net_worth,
            monthly_savings=mock_pfs.monthly_savings,
            savings_rate=mock_pfs.savings_rate,
            created_at=mock_pfs.created_at,
            updated_at=mock_pfs.updated_at,
        )
    
    # Production mode: use Firestore
    col = _statements_collection_for_user(user_id)
    query = (
        col.order_by("created_at", direction=firestore.Query.DESCENDING).limit(1)
    )
    docs = list(query.stream())
    if not docs:
        return None
    return _doc_to_pfs_out(docs[0])


def get_pfs_history_for_user(user_id: str, limit: int = 100) -> List[PFSOut]:
    # Mock mode: return dummy history
    if MOCK_MODE:
        from app.mock_data import get_mock_pfs_history
        mock_history = get_mock_pfs_history(user_id or "mock_user_001", months=min(limit, 12))
        # Convert MockPFS list to PFSOut list
        return [
            PFSOut(
                id=mock_pfs.id,
                currency=mock_pfs.currency,
                gross_income=mock_pfs.gross_income,
                net_income=mock_pfs.net_income,
                fixed_expenses=mock_pfs.fixed_expenses,
                variable_expenses=mock_pfs.variable_expenses,
                cash_and_equivalents=mock_pfs.cash_and_equivalents,
                investments=mock_pfs.investments,
                real_estate=mock_pfs.real_estate,
                other_assets=mock_pfs.other_assets,
                short_term_debt=mock_pfs.short_term_debt,
                long_term_debt=mock_pfs.long_term_debt,
                other_liabilities=mock_pfs.other_liabilities,
                risk_tolerance=mock_pfs.risk_tolerance,
                investment_horizon_years=mock_pfs.investment_horizon_years,
                goal_type=mock_pfs.goal_type,
                net_worth=mock_pfs.net_worth,
                monthly_savings=mock_pfs.monthly_savings,
                savings_rate=mock_pfs.savings_rate,
                created_at=mock_pfs.created_at,
                updated_at=mock_pfs.updated_at,
            )
            for mock_pfs in mock_history
        ]
    
    # Production mode: use Firestore
    col = _statements_collection_for_user(user_id)
    query = col.order_by("created_at", direction=firestore.Query.ASCENDING).limit(limit)
    return [_doc_to_pfs_out(d) for d in query.stream()]


# -----------------------------------------------------
# LLM prompt helper
# -----------------------------------------------------

def build_pfs_prompt_fragment(pfs: Optional[PFSOut]) -> str:
    if not pfs:
        return "User financial profile is not available."

    total_expenses = pfs.fixed_expenses + pfs.variable_expenses

    return (
        "User financial profile:\n"
        f"- Currency: {pfs.currency}\n"
        f"- Net worth: {pfs.net_worth:,.2f}\n"
        f"- Monthly net income: {pfs.net_income:,.2f}\n"
        f"- Monthly expenses: {total_expenses:,.2f}\n"
        f"- Monthly savings: {pfs.monthly_savings:,.2f} "
        f"({pfs.savings_rate:.1f}% of net income)\n"
        f"- Cash & equivalents: {pfs.cash_and_equivalents:,.2f}\n"
        f"- Investments: {pfs.investments:,.2f}\n"
        f"- Real estate: {pfs.real_estate:,.2f}\n"
        f"- Short-term debt: {pfs.short_term_debt:,.2f}\n"
        f"- Long-term debt: {pfs.long_term_debt:,.2f}\n"
        f"- Risk tolerance: {pfs.risk_tolerance or 'not specified'}\n"
        f"- Investment horizon (years): {pfs.investment_horizon_years or 'not specified'}\n"
        f"- Primary goal: {pfs.goal_type or 'not specified'}\n"
    )


def get_net_worth_series_for_user(user_id: str, limit: int = 100):
    """
    Returns a list of (created_at, net_worth, savings_rate) ordered by created_at asc.
    Useful for plotting a 'financial twin' trajectory.
    """
    history = get_pfs_history_for_user(user_id, limit=limit)
    return [
        {"created_at": p.created_at.isoformat(), "net_worth": p.net_worth, "savings_rate": p.savings_rate}
        for p in history
    ] if history else []

