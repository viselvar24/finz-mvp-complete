# app/pages/01_Profile.py

import os
from datetime import datetime
from typing import Optional, Dict, Any, List

import pandas as pd
import streamlit as st
from google.cloud import firestore

from app.pfs_service import (
    PFSCreate,
    get_latest_pfs_for_user,
    create_pfs_for_user,
)
from app.auth_check import require_authentication

# Import encryption utilities
try:
    from app.encryption import encrypt_user_profile, decrypt_user_profile
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    import logging
    logging.warning("Encryption module not available - profile data will be stored unencrypted")

# Firestore config
db_fs = firestore.Client()
USERS_COLLECTION = "users"


def get_user_by_email_fs(email: str) -> Optional[Dict[str, Any]]:
    """Lookup user in Firestore by email."""
    email = email.strip().lower()
    docs = (
        db_fs.collection(USERS_COLLECTION)
        .where("email", "==", email)
        .limit(1)
        .stream()
    )
    for d in docs:
        data = d.to_dict()
        data["id"] = d.id
        return data
    return None


def save_profile_data_to_user(user_id: str, profile_data: Dict[str, Any]) -> None:
    """Save profile data to user document in Firestore (encrypted)."""
    try:
        # Encrypt sensitive profile fields
        encrypted_profile = profile_data.copy()
        if ENCRYPTION_AVAILABLE:
            try:
                encrypted_profile = encrypt_user_profile(encrypted_profile)
                import logging
                logging.info(f"Profile data encrypted for user {user_id}")
            except Exception as e:
                import logging
                logging.error(f"Profile encryption failed, storing unencrypted: {e}")
        
        user_ref = db_fs.collection(USERS_COLLECTION).document(user_id)
        user_ref.update({
            "profile_data": encrypted_profile,
            "profile_updated_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        st.error(f"Error saving profile data: {str(e)}")


def get_profile_data_from_user(user_id: str) -> Dict[str, Any]:
    """Load profile data from user document in Firestore (decrypted if encrypted)."""
    try:
        user_ref = db_fs.collection(USERS_COLLECTION).document(user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            data = user_doc.to_dict()
            profile_data = data.get("profile_data", {})
            
            # Decrypt if encrypted
            if ENCRYPTION_AVAILABLE and profile_data.get("_encrypted", False):
                try:
                    profile_data = decrypt_user_profile(profile_data)
                except Exception as e:
                    import logging
                    logging.error(f"Failed to decrypt profile for user {user_id}: {e}")
                    st.warning("Unable to decrypt some profile data. Please update your profile.")
                    return {}
            
            return profile_data
    except Exception as e:
        st.warning(f"Could not load profile data: {str(e)}")
    return {}


# Page config
st.set_page_config(page_title="Perfient — Build Your Profile", layout="wide", initial_sidebar_state="expanded")

# Check authentication
#require_authentication()

# Sidebar - User info and logout
with st.sidebar:
    st.markdown("---")
    if "current_user_username" in st.session_state and st.session_state.current_user_username:
        st.markdown(f"### 👤 @{st.session_state.current_user_username}")
        if st.session_state.get("current_user_email"):
            st.caption(f"📧 {st.session_state.current_user_email}")
        
        st.markdown("---")
        
        if st.button("🚪 Logout", type="primary", use_container_width=True):
            # Clear all session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.success("✅ Logged out successfully!")
            st.info("Please refresh the page to log in again.")
            st.stop()

st.title("👤 Your Financial Profile")

# Custom CSS for better UX
st.markdown("""
<style>
    .step-header {
        font-size: 1.8rem;
        font-weight: 600;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .step-description {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 1.5rem;
        line-height: 1.6;
    }
    .help-text {
        background-color: #f0f8ff;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #1f77b4;
        margin: 1rem 0;
        color: #1a1a1a;
    }
    .progress-container {
        margin-bottom: 2rem;
    }
    .example-text {
        color: #888;
        font-style: italic;
        font-size: 0.9rem;
    }
    .validation-tip {
        background-color: #fff3cd;
        padding: 0.75rem;
        border-radius: 0.5rem;
        border-left: 4px solid #ffc107;
        margin-top: 1rem;
        color: #1a1a1a;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "current_user_id" not in st.session_state:
    st.session_state.current_user_id = None
if "current_user_email" not in st.session_state:
    st.session_state.current_user_email = ""
if "profile_step" not in st.session_state:
    st.session_state.profile_step = 0
if "profile_data" not in st.session_state:
    st.session_state.profile_data = {}
if "profile_mode" not in st.session_state:
    st.session_state.profile_mode = "wizard"  # wizard or edit
if "pause_personalization" not in st.session_state:
    st.session_state.pause_personalization = False
if "pft_model" not in st.session_state:
    st.session_state.pft_model = None  # None, "lite", or "full"
if "show_success_message" not in st.session_state:
    st.session_state.show_success_message = False


# Header
st.title("🎯 Build Your Financial Twin")
st.caption("Answer a few questions to get personalized investment recommendations tailored to your unique situation.")

# 1) User identification
st.markdown("### 👤 First, let's identify you")
# 
# Auto-load profile if email is already known from login
if st.session_state.current_user_email and not st.session_state.current_user_id:
    user = get_user_by_email_fs(st.session_state.current_user_email)
    if user:
        st.session_state.current_user_id = user["id"]
        st.session_state.current_user_email = user["email"]

email_input = st.text_input(
    "Your Perfient email",
    value=st.session_state.current_user_email or "",
    placeholder="you@example.com",
    disabled=bool(st.session_state.current_user_id),  # Disable if already loaded
)
# 
col_load, col_status = st.columns([1, 3])
# 
with col_load:
    if not st.session_state.current_user_id:
        if st.button("Load profile"):
            if not email_input.strip():
                st.error("Please enter your email.")
            else:
                user = get_user_by_email_fs(email_input)
                if not user:
                    st.error("User not found in Firestore. Please make sure you've signed up.")
                else:
                    st.session_state.current_user_id = user["id"]
                    st.session_state.current_user_email = user["email"]
                    st.success(f"Loaded user: {user['email']}")
                    st.rerun()
    else:
         if st.button("Change user"):
            st.session_state.current_user_id = None
            st.session_state.current_user_email = ""
            st.session_state.profile_data = {}
            st.rerun()
# 
with col_status:
    if st.session_state.current_user_id:
        st.success(f"✅ Logged in as: `{st.session_state.current_user_email}`")
    else:
        st.warning("No user loaded yet. Enter your email and click **Load profile**.")


user_id = st.session_state.current_user_id
if not user_id:
    st.stop()

# Email Management Section
st.markdown("---")

# Import encryption at top level
try:
    from app.encryption import encrypt_value, decrypt_value
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    import logging
    logging.warning("Encryption not available - email will be stored unencrypted")

with st.expander("📧 Email Settings (Optional)", expanded=False):
    st.markdown("**Add or update your email address for account recovery**")
    
    current_email = st.session_state.get("current_user_email")
    
    if current_email:
        st.info(f"✅ Current email: **{current_email}**")
        st.caption("Your email is encrypted and stored securely.")
        
        if st.checkbox("Update email address"):
            new_email = st.text_input(
                "New email address",
                placeholder="your@email.com",
                help="Enter a new email address to update your account"
            )
            
            if st.button("💾 Update Email", type="primary"):
                if not new_email or "@" not in new_email:
                    st.error("Please enter a valid email address.")
                else:
                    try:
                        email_to_store = new_email.strip().lower()
                        
                        # Encrypt email if encryption is available
                        if ENCRYPTION_AVAILABLE:
                            encrypted_email = encrypt_value(email_to_store)
                            st.caption("🔒 Email will be encrypted before storage")
                        else:
                            encrypted_email = email_to_store
                            st.warning("⚠️ Encryption unavailable - email stored as plaintext")
                        
                        # Update in Firestore
                        db_fs.collection(USERS_COLLECTION).document(user_id).update({
                            "email": encrypted_email
                        })
                        
                        # Update session state with plaintext for display
                        st.session_state.current_user_email = email_to_store
                        
                        st.success("✅ Email updated successfully!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to update email: {e}")
                        import traceback
                        st.error(f"Details: {traceback.format_exc()}")
    else:
        st.warning("⚠️ **No email address on file**")
        st.markdown("""
        **Why add an email?**
        - Enable account recovery if you forget your password
        - Receive important security notifications
        - Get updates about new features
        
        ⚠️ **Important:** Without an email, you must keep your username and password safe. Account recovery will not be possible.
        """)
        
        add_email = st.text_input(
            "Email address",
            placeholder="your@email.com",
            help="This will be encrypted and stored securely"
        )
        
        if st.button("💾 Add Email", type="primary"):
            if not add_email or "@" not in add_email:
                st.error("Please enter a valid email address.")
            else:
                try:
                    email_to_store = add_email.strip().lower()
                    
                    # Encrypt email if encryption is available
                    if ENCRYPTION_AVAILABLE:
                        encrypted_email = encrypt_value(email_to_store)
                        st.caption("🔒 Email will be encrypted before storage")
                    else:
                        encrypted_email = email_to_store
                        st.warning("⚠️ Encryption unavailable - email stored as plaintext")
                    
                    # Update in Firestore
                    db_fs.collection(USERS_COLLECTION).document(user_id).update({
                        "email": encrypted_email
                    })
                    
                    # Update session state with plaintext for display
                    st.session_state.current_user_email = email_to_store
                    
                    st.success("✅ Email added successfully! Your account now has recovery options.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add email: {e}")

st.markdown("---")

# Data Import Section (for returning users)
with st.expander("📥 Import Previous Data (Returning Users)", expanded=False):
    st.markdown("### 🔄 Restore Your Perfient Data")
    st.caption("If you previously exported your data and want to return, upload your JSON file here.")
    
    st.info("💡 **This will restore:** Profile data, PFS snapshots, portfolio holdings, and analysis history.")
    
    uploaded_file = st.file_uploader(
        "Upload your exported data (JSON file)",
        type=["json"],
        help="Select the JSON file you downloaded when you quit Perfient"
    )
    
    if uploaded_file is not None:
        try:
            import json
            from datetime import datetime
            
            # Read and parse JSON
            file_contents = uploaded_file.read()
            import_data = json.loads(file_contents)
            
            # Validate structure
            required_keys = ["export_date", "user_id", "profile_data"]
            missing_keys = [key for key in required_keys if key not in import_data]
            
            if missing_keys:
                st.error(f"❌ Invalid file format. Missing keys: {', '.join(missing_keys)}")
            else:
                # Show preview
                st.success("✅ File validated successfully!")
                
                with st.expander("📋 Preview Import Data", expanded=True):
                    st.markdown(f"**Export Date:** {import_data.get('export_date', 'Unknown')}")
                    st.markdown(f"**Original User ID:** {import_data.get('user_id', 'Unknown')}")
                    st.markdown(f"**Email:** {import_data.get('user_email', 'Not specified')}")
                    
                    pfs_count = len(import_data.get('pfs_snapshots', []))
                    decision_count = len(import_data.get('decisions', []))
                    has_portfolio = bool(import_data.get('portfolio'))
                    
                    st.markdown(f"**PFS Snapshots:** {pfs_count}")
                    st.markdown(f"**Decision History:** {decision_count} records")
                    st.markdown(f"**Portfolio Data:** {'Yes' if has_portfolio else 'No'}")
                
                st.warning("⚠️ **Important:** This will overwrite your current profile data. Make sure to export your current data first if needed.")
                
                col_cancel, col_import = st.columns(2)
                
                with col_cancel:
                    if st.button("← Cancel", use_container_width=True):
                        st.rerun()
                
                with col_import:
                    if st.button("📥 Import Data", type="primary", use_container_width=True):
                        try:
                            progress_bar = st.progress(0, text="Starting import...")
                            
                            # 1. Update user profile data
                            progress_bar.progress(0.2, text="Restoring profile...")
                            if import_data.get('profile_data'):
                                profile_to_restore = import_data['profile_data'].copy()
                                # Remove fields that shouldn't be overwritten
                                fields_to_skip = ['id', 'created_at', 'password']
                                for field in fields_to_skip:
                                    profile_to_restore.pop(field, None)
                                
                                # Add current timestamp
                                profile_to_restore['restored_at'] = datetime.now().isoformat()
                                profile_to_restore['restored_from_export'] = import_data.get('export_date')
                                
                                db_fs.collection("users").document(user_id).update(profile_to_restore)
                            
                            # 2. Restore PFS snapshots
                            progress_bar.progress(0.4, text="Restoring financial snapshots...")
                            pfs_funcs = get_pfs_functions()
                            for pfs_snapshot in import_data.get('pfs_snapshots', []):
                                # Create new PFS with imported data
                                pfs_data = pfs_snapshot.copy()
                                pfs_data.pop('id', None)  # Remove old ID
                                pfs_data['user_id'] = user_id  # Use current user ID
                                pfs_data['restored_at'] = datetime.now().isoformat()
                                
                                # Create PFS payload
                                try:
                                    pfs_payload = PFSCreate(
                                        currency=pfs_data.get('currency', 'USD'),
                                        gross_income=pfs_data.get('gross_income', 0.0),
                                        net_income=pfs_data.get('net_income', 0.0),
                                        fixed_expenses=pfs_data.get('fixed_expenses', 0.0),
                                        variable_expenses=pfs_data.get('variable_expenses', 0.0),
                                        cash_and_equivalents=pfs_data.get('cash_and_equivalents', 0.0),
                                        investments=pfs_data.get('investments', 0.0),
                                        real_estate=pfs_data.get('real_estate', 0.0),
                                        other_assets=pfs_data.get('other_assets', 0.0),
                                        short_term_debt=pfs_data.get('short_term_debt', 0.0),
                                        long_term_debt=pfs_data.get('long_term_debt', 0.0),
                                        other_liabilities=pfs_data.get('other_liabilities', 0.0),
                                        risk_tolerance=pfs_data.get('risk_tolerance'),
                                        investment_horizon_years=pfs_data.get('investment_horizon_years'),
                                        goal_type=pfs_data.get('goal_type'),
                                    )
                                    create_pfs_for_user(user_id, pfs_payload)
                                except Exception as e:
                                    st.warning(f"⚠️ Skipped one PFS snapshot: {e}")
                            
                            # 3. Restore portfolio data
                            progress_bar.progress(0.6, text="Restoring portfolio...")
                            if import_data.get('portfolio'):
                                portfolio_data = import_data['portfolio'].copy()
                                portfolio_data.pop('id', None)  # Remove old ID
                                portfolio_data['user_id'] = user_id
                                portfolio_data['restored_at'] = datetime.now().isoformat()
                                
                                # Upsert portfolio
                                db_fs.collection("portfolios").document(user_id).set(portfolio_data, merge=True)
                            
                            # 4. Restore decision history
                            progress_bar.progress(0.8, text="Restoring analysis history...")
                            for decision in import_data.get('decisions', [])[:100]:  # Limit to 100 most recent
                                decision_data = decision.copy()
                                decision_data.pop('id', None)
                                decision_data['restored_at'] = datetime.now().isoformat()
                                
                                # Add to decisions subcollection
                                db_fs.collection("users").document(user_id).collection("decisions").add(decision_data)
                            
                            # 5. Complete
                            progress_bar.progress(1.0, text="Import complete!")
                            
                            st.success("✅ **Data imported successfully!**")
                            st.balloons()
                            st.info("🔄 Refreshing page to load your restored data...")
                            
                            # Clear session state to reload
                            st.session_state.profile_data = {}
                            
                            import time
                            time.sleep(2)
                            st.rerun()
                            
                        except json.JSONDecodeError:
                            st.error("❌ Invalid JSON file. Please upload a valid Perfient export file.")
                        except Exception as e:
                            st.error(f"❌ Import failed: {e}")
                            st.warning("Your original data has not been modified.")
        
        except Exception as e:
            st.error(f"❌ Error reading file: {e}")

st.markdown("---")

# Load existing profile data
latest_pfs = get_latest_pfs_for_user(user_id)

# Load saved profile data from user document (if not already in session)
if not st.session_state.profile_data:
    saved_profile = get_profile_data_from_user(user_id)
    if saved_profile:
        st.session_state.profile_data = saved_profile


# Show success screen if profile was just saved
if st.session_state.show_success_message:
    st.markdown('<div class="step-header">🎉 Profile Successfully Saved!</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-description">Your Financial Twin is ready to provide personalized recommendations.</div>', unsafe_allow_html=True)
    
    st.balloons()
    
    st.success(f"✅ **Profile saved successfully!**")
    st.info(f"💰 **Net Worth:** {st.session_state.get('saved_net_worth', 'Calculated')}")
    
    st.markdown("---")
    st.markdown("### 🚀 What's Next?")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        #### 💬 Chat with Your Twin
        Get personalized investment recommendations based on your profile.
        
        Ask questions like:
        - "What should I invest in?"
        - "How can I reach my goals?"
        - "What's my risk capacity?"
        """)
        if st.button("💬 Go to Chat", use_container_width=True, type="primary"):
            st.session_state.show_success_message = False
            st.switch_page("Chat.py")
    
    with col2:
        st.markdown("""
        #### 📊 View Dashboard
        Track your financial progress and see portfolio insights.
        
        Explore:
        - Net worth trends
        - Goal progress
        - Portfolio allocation
        """)
        if st.button("📊 View Dashboard", use_container_width=True):
            st.session_state.show_success_message = False
            st.switch_page("pages/02_Dashboard.py")
    
    st.markdown("---")
    if st.button("🔄 Update My Profile", use_container_width=False):
        st.session_state.show_success_message = False
        st.rerun()
    
    st.stop()


# Define functions before calling them
def render_wizard_interface(user_id: str, latest_pfs):
    """Guided Q&A wizard for building profile step by step."""
    
    # Define wizard steps - streamlined without manual goal selection
    # Step -1: Model selection (lite vs full)
    # Step 0: PFT Intro
    # Step 1: Life Context (age, location, employment, currency)
    # Step 2: Risk Comfort
    # Step 3: Financial Snapshot (Assets/Liabilities)
    # Step 4: Income & Expenses
    # Step 5: Additional Details (Risk tolerance, investment horizon)
    # Step 6: Review & Submit
    # Note: Goals/roadmap are now auto-generated based on financial data
    
    TOTAL_STEPS = 7 if st.session_state.pft_model else 6
    current_step = st.session_state.profile_step
    
    # Progress bar (only show if past model selection)
    if current_step >= 0:
        progress = current_step / TOTAL_STEPS
        st.markdown('<div class="progress-container">', unsafe_allow_html=True)
        st.progress(progress)
        st.caption(f"Step {current_step + 1} of {TOTAL_STEPS}")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Navigation helpers
    def next_step():
        if st.session_state.profile_step < TOTAL_STEPS - 1:
            st.session_state.profile_step += 1
    
    def prev_step():
        if st.session_state.profile_step > 0:
            st.session_state.profile_step -= 1
    
    def get_default(field: str, default=0.0):
        # Check session first, then latest_pfs
        if field in st.session_state.profile_data:
            return st.session_state.profile_data[field]
        return getattr(latest_pfs, field, default) if latest_pfs else default
    
    def skip_step():
        """Skip current step and move to next"""
        if st.session_state.profile_step < TOTAL_STEPS - 1:
            st.session_state.profile_step += 1
    
    # Step -1: Model Selection (only shown if model not selected)
    if current_step == -1 or st.session_state.pft_model is None:
        st.markdown('<div class="step-header">🎯 Choose Your Financial Twin Model</div>', unsafe_allow_html=True)
        st.markdown('<div class="step-description">We offer two approaches to building your financial profile. Choose the one that fits your comfort level.</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🌟 PFT Lite")
            st.markdown("""<div class="help-text">
            <b>Perfect for getting started quickly</b><br><br>
            ✅ No sensitive data required<br>
            ✅ Takes ~2 minutes<br>
            ✅ Works with estimates<br>
            ✅ Skip any question<br><br>
            <b>What you get:</b><br>
            • Risk capacity estimate<br>
            • Goal feasibility check<br>
            • Personalized insights<br><br>
            <i>You can upgrade to Full anytime</i>
            </div>""", unsafe_allow_html=True)
            
            if st.button("✨ Build Lite Twin (2 min)", use_container_width=True, type="primary"):
                st.session_state.pft_model = "lite"
                st.session_state.profile_step = 0
                st.rerun()
        
        with col2:
            st.markdown("### 💎 PFT Full")
            st.markdown("""<div class="help-text">
            <b>For detailed, precise analysis</b><br><br>
            📊 Comprehensive financial picture<br>
            📊 Exact numbers<br>
            📊 Full asset & liability tracking<br>
            📊 Advanced stress testing<br><br>
            <b>What you get:</b><br>
            • Precise goal probabilities<br>
            • Scenario analysis<br>
            • Detailed action plans<br>
            • Monte Carlo simulations<br><br>
            <i>Takes 5-10 minutes</i>
            </div>""", unsafe_allow_html=True)
            
            if st.button("🚀 Build Full Twin (10 min)", use_container_width=True):
                st.session_state.pft_model = "full"
                st.session_state.profile_step = 0
                st.rerun()
        
        st.markdown("---")
        with st.expander("🔒 What data do we store?"):
            st.markdown("""
            **PFT Lite:**
            - Age range (not exact birthday)
            - Country/region
            - Employment type
            - Income/expense ranges
            - Goals (no amounts)
            
            **PFT Full:**
            - All Lite data plus:
            - Specific income amounts
            - Asset values
            - Liability details
            - Investment holdings
            
            **We NEVER:**
            - Connect to your bank
            - Store passwords
            - Share your data
            - Require social security numbers
            """)
        
        return  # Don't show navigation buttons on model selection
    
    # Step 0: PFT Lite Intro (Trust Gate)
    if current_step == 0:
        model = st.session_state.pft_model or "lite"
        st.markdown(f'<div class="step-header">👋 Welcome to PFT {model.title()}!</div>', unsafe_allow_html=True)
        st.markdown('<div class="step-description">Let\'s start by understanding your life context. This helps us personalize recommendations.</div>', unsafe_allow_html=True)
        
        st.markdown(f'<div class="help-text">💡 <b>You selected: PFT {model.title()}</b><br>', unsafe_allow_html=True)
        if model == "lite":
            st.markdown("""
            • No sensitive data required<br>
            • All questions are optional<br>
            • Estimates are perfectly fine<br>
            • You can upgrade to Full later
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            • Detailed financial picture<br>
            • Precise recommendations<br>
            • Advanced scenario analysis<br>
            • You can simplify to Lite later
            </div>""", unsafe_allow_html=True)
        
        if st.button("🔄 Change Model", use_container_width=False):
            st.session_state.pft_model = None
            st.session_state.profile_step = -1
            st.rerun()
    
    # Step 1: Life Context (Non-Financial)
    elif current_step == 1:
        st.markdown('<div class="step-header">🌍 Life Context</div>', unsafe_allow_html=True)
        st.markdown('<div class="step-description">First, tell us about your currency and income situation. This helps us understand your financial baseline.</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="help-text">💡 <b>Why we ask:</b> Age affects time horizon, location affects market access, and employment type affects income stability.</div>', unsafe_allow_html=True)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 📅 Age Range")
            st.markdown('<p class="example-text">We use ranges for privacy</p>', unsafe_allow_html=True)
            age_ranges = ["", "18-25", "26-35", "36-45", "46-60", "60+"]
            age_range = st.selectbox(
                "Your age range",
                age_ranges,
                index=age_ranges.index(get_default("age_range", "")) if get_default("age_range", "") in age_ranges else 0,
                help="Used to model time horizon and life stage"
            )
            if age_range:
                st.session_state.profile_data["age_range"] = age_range
            
            st.markdown("#### 🌎 Location")
            countries = ["", "United States", "United Kingdom", "Canada", "Germany", "India", "Australia", "Other"]
            country = st.selectbox(
                "Country/Region",
                countries,
                index=countries.index(get_default("country", "")) if get_default("country", "") in countries else 0,
                help="Helps us understand market access and regulatory environment"
            )
            if country:
                st.session_state.profile_data["country"] = country
        
        with col2:
            st.markdown("#### 💼 Employment Type")
            st.markdown('<p class="example-text">Affects income stability modeling</p>', unsafe_allow_html=True)
            employment_types = ["", "Salaried", "Self-employed", "Retired", "Mixed", "Student", "Other"]
            employment = st.selectbox(
                "Your employment situation",
                employment_types,
                index=employment_types.index(get_default("employment_type", "")) if get_default("employment_type", "") in employment_types else 0,
                help="Used to model income volatility and risk capacity"
            )
            if employment:
                st.session_state.profile_data["employment_type"] = employment
            
            st.markdown("#### 💰 Currency")
            currencies = ["USD", "EUR", "GBP", "INR", "CAD", "AUD"]
            currency = st.selectbox(
                "Primary currency",
                currencies,
                index=currencies.index(get_default("currency", "USD")) if get_default("currency", "USD") in currencies else 0,
                help="All financial amounts will be in this currency"
            )
            st.session_state.profile_data["currency"] = currency
        
        st.markdown("---")
        st.markdown('<div class="validation-tip">💡 <b>Note:</b> All fields are optional. You can skip any question and still get useful recommendations.</div>', unsafe_allow_html=True)
    
    # Step 2: Risk Comfort (Subjective First) - Goals are now auto-generated as roadmap
    elif current_step == 2:
        st.markdown('<div class="step-header">🎲 Risk Comfort Level</div>', unsafe_allow_html=True)
        st.markdown('<div class="step-description">How comfortable are you with investment volatility? This is about feelings, not knowledge.</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="help-text">💡 <b>Why we ask:</b> This maps to risk tolerance before we calculate risk capacity.</div>', unsafe_allow_html=True)
        
        st.markdown("#### 📉 Scenario: Market Drop")
        st.markdown("Imagine your investment portfolio dropped 20% in value. How would you react?")
        
        risk_reaction = st.select_slider(
            "Your reaction",
            options=[
                "Very uncomfortable - I'd sell immediately",
                "Uncomfortable - I'd be very worried",
                "Neutral - I'd wait and see",
                "Comfortable - I'd hold my positions",
                "Very comfortable - I'd buy more"
            ],
            value=get_default("risk_reaction", "Neutral - I'd wait and see")
        )
        st.session_state.profile_data["risk_reaction"] = risk_reaction
        
        st.markdown("---")
        st.markdown("#### ⚖️ Investment Philosophy")
        
        investment_priority = st.radio(
            "What matters more to you?",
            options=[
                "Protecting what I have (Capital preservation)",
                "Balance of growth and safety (Balanced)",
                "Growing my wealth (Growth focused)"
            ],
            index=1 if not get_default("investment_priority") else 
                  ["Protecting what I have (Capital preservation)", 
                   "Balance of growth and safety (Balanced)", 
                   "Growing my wealth (Growth focused)"].index(get_default("investment_priority"))
        )
        st.session_state.profile_data["investment_priority"] = investment_priority
    
    # Step 3: Financial Snapshot (Lite: ranges, Full: Detailed Assets/Liabilities)
    elif current_step == 3:
        model = st.session_state.pft_model or "lite"
        
        if model == "lite":
            # Helper functions to convert numeric PFS values to range strings
            def get_cash_range_from_value(value: float) -> str:
                """Convert numeric cash value to range string"""
                if value == 0:
                    return ""
                elif value < 10000:
                    return "< $10k"
                elif value < 50000:
                    return "$10k - $50k"
                elif value < 200000:
                    return "$50k - $200k"
                else:
                    return "$200k+"
            
            def get_investment_range_from_value(value: float) -> str:
                """Convert numeric investment value to range string"""
                if value == 0:
                    return "None"
                elif value < 10000:
                    return "< $10k"
                elif value < 50000:
                    return "$10k - $50k"
                elif value < 200000:
                    return "$50k - $200k"
                else:
                    return "$200k+"
            
            def get_property_status_from_value(value: float) -> str:
                """Convert numeric real estate value to property status"""
                if value == 0:
                    return "None"
                else:
                    return "Primary residence (owned)"
            
            def get_debt_level_from_value(short_debt: float, long_debt: float) -> str:
                """Convert numeric debt values to debt level"""
                total_debt = short_debt + long_debt
                if total_debt == 0:
                    return "None"
                elif total_debt < 10000:
                    return "Low (manageable)"
                elif total_debt < 50000:
                    return "Medium (watching it)"
                else:
                    return "High (concerned)"
            
            st.markdown('<div class="step-header">💵 Financial Snapshot (Lite)</div>', unsafe_allow_html=True)
            st.markdown('<div class="step-description">Give us rough ranges. Estimates are perfectly fine - we don\'t need exact numbers.</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="help-text">💡 <b>Why ranges work:</b> Even approximate numbers help us model your capacity and give useful recommendations.</div>', unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 💰 Savings & Cash")
                cash_ranges = ["", "< $10k", "$10k - $50k", "$50k - $200k", "$200k+"]
                
                # Get default: check for range first, then convert from numeric PFS value
                default_cash_range = get_default("cash_range", "")
                if not default_cash_range and latest_pfs:
                    cash_value = getattr(latest_pfs, "cash_and_equivalents", 0.0)
                    default_cash_range = get_cash_range_from_value(cash_value)
                
                cash_range = st.selectbox(
                    "Approximate savings",
                    cash_ranges,
                    index=cash_ranges.index(default_cash_range) if default_cash_range in cash_ranges else 0
                )
                if cash_range:
                    st.session_state.profile_data["cash_range"] = cash_range
                
                st.markdown("#### 📈 Investments")
                inv_ranges = ["", "None", "< $10k", "$10k - $50k", "$50k - $200k", "$200k+"]
                
                # Get default: check for range first, then convert from numeric PFS value
                default_inv_range = get_default("investment_range", "")
                if not default_inv_range and latest_pfs:
                    inv_value = getattr(latest_pfs, "investments", 0.0)
                    default_inv_range = get_investment_range_from_value(inv_value)
                
                inv_range = st.selectbox(
                    "Stocks, bonds, retirement accounts",
                    inv_ranges,
                    index=inv_ranges.index(default_inv_range) if default_inv_range in inv_ranges else 0
                )
                if inv_range:
                    st.session_state.profile_data["investment_range"] = inv_range
            
            with col2:
                st.markdown("#### 🏡 Property")
                property_opts = ["", "None", "Primary residence (owned)", "Investment property", "Both"]
                
                # Get default: check for status first, then convert from numeric PFS value
                default_property = get_default("property_status", "")
                if not default_property and latest_pfs:
                    re_value = getattr(latest_pfs, "real_estate", 0.0)
                    default_property = get_property_status_from_value(re_value)
                
                property_status = st.selectbox(
                    "Real estate ownership",
                    property_opts,
                    index=property_opts.index(default_property) if default_property in property_opts else 0
                )
                if property_status:
                    st.session_state.profile_data["property_status"] = property_status
                
                st.markdown("#### 💳 Debt Level")
                debt_opts = ["", "None", "Low (manageable)", "Medium (watching it)", "High (concerned)"]
                
                # Get default: check for level first, then convert from numeric PFS value
                default_debt = get_default("debt_level", "")
                if not default_debt and latest_pfs:
                    short_debt_val = getattr(latest_pfs, "short_term_debt", 0.0)
                    long_debt_val = getattr(latest_pfs, "long_term_debt", 0.0)
                    default_debt = get_debt_level_from_value(short_debt_val, long_debt_val)
                
                debt_level = st.selectbox(
                    "Overall debt situation",
                    debt_opts,
                    index=debt_opts.index(default_debt) if default_debt in debt_opts else 0
                )
                if debt_level:
                    st.session_state.profile_data["debt_level"] = debt_level
        
        else:  # Full model
            st.markdown('<div class="step-header">� Your Assets (What You Own)</div>', unsafe_allow_html=True)
            st.markdown('<div class="step-description">Let\'s start with what you own. Be as accurate as possible for better recommendations.</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="help-text">💡 <b>Why we ask:</b> Your assets form the foundation of your financial picture. This helps us calculate your net worth and investment capacity roughly.</div>', unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 💵 Liquid Assets")
                st.markdown('<p class="example-text">Money you can access quickly</p>', unsafe_allow_html=True)
                
                cash_eq = st.number_input(
                    f"Cash & bank accounts ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("cash_and_equivalents", 0.0)),
                    min_value=0.0,
                    step=500.0,
                    help="Checking, savings, money market accounts"
                )
                st.session_state.profile_data["cash_and_equivalents"] = cash_eq
                
                investments = st.number_input(
                    f"Investments ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("investments", 0.0)),
                    min_value=0.0,
                    step=500.0,
                    help="Stocks, bonds, ETFs, mutual funds, retirement accounts"
                )
                st.session_state.profile_data["investments"] = investments
            
            with col2:
                st.markdown("#### 🏡 Other Assets")
                st.markdown('<p class="example-text">Valuable property and possessions</p>', unsafe_allow_html=True)
                
                real_estate = st.number_input(
                    f"Real estate value ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("real_estate", 0.0)),
                    min_value=0.0,
                    step=1000.0,
                    help="Market value of properties you own"
                )
                st.session_state.profile_data["real_estate"] = real_estate
                
                other_assets = st.number_input(
                    f"Other assets ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("other_assets", 0.0)),
                    min_value=0.0,
                    step=500.0,
                    help="Vehicles, collectibles, business ownership, etc."
                )
                st.session_state.profile_data["other_assets"] = other_assets
            
            total_assets = cash_eq + investments + real_estate + other_assets
            st.markdown("---")
            st.metric("💰 Total Assets", f"{st.session_state.profile_data.get('currency', 'USD')} {total_assets:,.0f}")
            
            st.markdown("---")
            st.markdown('<div class="step-header">📊 Your Liabilities (What You Owe)</div>', unsafe_allow_html=True)
            st.markdown('<div class="step-description">Now let\'s account for any debts or obligations.</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="help-text">💡 <b>Why we ask:</b> Your debts affect your net worth and risk capacity. High-interest debt should often be paid down before investing.</div>', unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### ⚡ Short-term Debt")
                st.markdown('<p class="example-text">Debts due within a year</p>', unsafe_allow_html=True)
                
                short_debt = st.number_input(
                    f"Short-term debt ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("short_term_debt", 0.0)),
                    min_value=0.0,
                    step=100.0,
                    help="Credit cards, personal loans, upcoming bills"
                )
                st.session_state.profile_data["short_term_debt"] = short_debt
                
                with st.expander("📝 What counts as short-term debt?"):
                    st.markdown("""
                    - Credit card balances
                    - Personal loans (< 1 year)
                    - Medical bills
                    - Payday loans
                    - Any debt due within 12 months
                    """)
            
            with col2:
                st.markdown("#### 🏦 Long-term Debt")
                st.markdown('<p class="example-text">Debts with longer repayment periods</p>', unsafe_allow_html=True)
                
                long_debt = st.number_input(
                    f"Long-term debt ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("long_term_debt", 0.0)),
                    min_value=0.0,
                    step=500.0,
                    help="Mortgages, student loans, car loans, business loans"
                )
                st.session_state.profile_data["long_term_debt"] = long_debt
                
                with st.expander("📝 What counts as long-term debt?"):
                    st.markdown("""
                    - Mortgage (home loan)
                    - Student loans
                    - Auto loans
                    - Business loans
                    - Any debt with > 1 year repayment
                    """)
            
            st.markdown("#### 📝 Other Liabilities")
            other_liab = st.number_input(
                f"Other obligations ({st.session_state.profile_data.get('currency', 'USD')})",
                value=float(get_default("other_liabilities", 0.0)),
                min_value=0.0,
                step=100.0,
                help="Any other financial obligations not captured above"
            )
            st.session_state.profile_data["other_liabilities"] = other_liab
            
            total_liabilities = short_debt + long_debt + other_liab
            total_assets = (st.session_state.profile_data.get("cash_and_equivalents", 0) +
                           st.session_state.profile_data.get("investments", 0) +
                           st.session_state.profile_data.get("real_estate", 0) +
                           st.session_state.profile_data.get("other_assets", 0))
            net_worth = total_assets - total_liabilities
            
            st.markdown("---")
            col_sum1, col_sum2, col_sum3 = st.columns(3)
            with col_sum1:
                st.metric("Total Liabilities", f"{st.session_state.profile_data.get('currency', 'USD')} {total_liabilities:,.0f}")
            with col_sum2:
                st.metric("Total Assets", f"{st.session_state.profile_data.get('currency', 'USD')} {total_assets:,.0f}")
            with col_sum3:
                st.metric("Net Worth", f"{st.session_state.profile_data.get('currency', 'USD')} {net_worth:,.0f}", 
                         delta="Positive" if net_worth > 0 else "Focus on debt reduction")
            
            if total_liabilities > total_assets and total_assets > 0:
                st.markdown('<div class="validation-tip">💡 <b>Tip:</b> Your liabilities exceed assets. Focus on debt reduction alongside investing for long-term wealth building.</div>', unsafe_allow_html=True)
    
    # Step 4: Income & Expenses
    elif current_step == 4:
        model = st.session_state.pft_model or "lite"
        
        st.markdown('<div class="step-header">💵 Income & Expenses</div>', unsafe_allow_html=True)
        st.markdown('<div class="step-description">Help us understand your cash flow to calculate your savings capacity and investment potential.</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="help-text">💡 <b>Why we ask:</b> Your income minus expenses equals your savings capacity. This is crucial for investment planning and goal feasibility.</div>', unsafe_allow_html=True)
        
        if model == "lite":
            # Lite mode: Simple ranges
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### 💰 Monthly Income")
                st.markdown('<p class="example-text">After-tax income (take-home pay)</p>', unsafe_allow_html=True)
                
                income_ranges = ["", "< $2k", "$2k - $5k", "$5k - $10k", "$10k - $20k", "$20k+"]
                income_range = st.selectbox(
                    "Approximate monthly income",
                    income_ranges,
                    index=income_ranges.index(get_default("income_range", "")) if get_default("income_range", "") in income_ranges else 0,
                    help="Your take-home pay after taxes"
                )
                if income_range:
                    st.session_state.profile_data["income_range"] = income_range
            
            with col2:
                st.markdown("#### 💳 Monthly Expenses")
                st.markdown('<p class="example-text">All spending (housing, food, bills, etc.)</p>', unsafe_allow_html=True)
                
                expense_ranges = ["", "< $2k", "$2k - $5k", "$5k - $10k", "$10k - $20k", "$20k+"]
                expense_range = st.selectbox(
                    "Approximate monthly expenses",
                    expense_ranges,
                    index=expense_ranges.index(get_default("expense_range", "")) if get_default("expense_range", "") in expense_ranges else 0,
                    help="Total monthly spending"
                )
                if expense_range:
                    st.session_state.profile_data["expense_range"] = expense_range
        
        else:  # Full mode: Detailed breakdown
            st.markdown("### 💰 Income (Monthly)")
            col1, col2 = st.columns(2)
            
            with col1:
                gross_income = st.number_input(
                    f"Gross income ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("gross_income", 0.0)),
                    min_value=0.0,
                    step=100.0,
                    help="Total income before taxes and deductions"
                )
                st.session_state.profile_data["gross_income"] = gross_income
            
            with col2:
                net_income = st.number_input(
                    f"Net income ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("net_income", 0.0)),
                    min_value=0.0,
                    step=100.0,
                    help="Take-home pay after taxes"
                )
                st.session_state.profile_data["net_income"] = net_income
            
            st.markdown("---")
            st.markdown("### 💳 Expenses (Monthly)")
            
            col1, col2 = st.columns(2)
            
            with col1:
                fixed_expenses = st.number_input(
                    f"Fixed expenses ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("fixed_expenses", 0.0)),
                    min_value=0.0,
                    step=50.0,
                    help="Rent/mortgage, insurance, loan payments, subscriptions"
                )
                st.session_state.profile_data["fixed_expenses"] = fixed_expenses
                
                with st.expander("📝 What are fixed expenses?"):
                    st.markdown("""
                    - Rent or mortgage payment
                    - Insurance (health, car, home)
                    - Loan payments
                    - Utilities (average)
                    - Subscriptions (Netflix, gym, etc.)
                    """)
            
            with col2:
                variable_expenses = st.number_input(
                    f"Variable expenses ({st.session_state.profile_data.get('currency', 'USD')})",
                    value=float(get_default("variable_expenses", 0.0)),
                    min_value=0.0,
                    step=50.0,
                    help="Food, entertainment, shopping, travel"
                )
                st.session_state.profile_data["variable_expenses"] = variable_expenses
                
                with st.expander("📝 What are variable expenses?"):
                    st.markdown("""
                    - Groceries and dining out
                    - Entertainment and hobbies
                    - Shopping (clothes, etc.)
                    - Travel and vacations
                    - Miscellaneous spending
                    """)
            
            # Calculate and display savings
            total_expenses = fixed_expenses + variable_expenses
            monthly_savings = max(net_income - total_expenses, 0)
            savings_rate = (monthly_savings / net_income * 100) if net_income > 0 else 0
            
            st.markdown("---")
            col_exp, col_sav, col_rate = st.columns(3)
            
            currency = st.session_state.profile_data.get('currency', 'USD')
            with col_exp:
                st.metric("Total Monthly Expenses", f"{currency} {total_expenses:,.0f}")
            with col_sav:
                st.metric("Monthly Savings", f"{currency} {monthly_savings:,.0f}")
            with col_rate:
                st.metric("Savings Rate", f"{savings_rate:.1f}%")
            
            if savings_rate < 10 and net_income > 0:
                st.warning("⚠️ Your savings rate is below 10%. Consider reviewing expenses or increasing income to improve investment capacity.")
            elif savings_rate >= 20:
                st.success("✅ Excellent savings rate! You have strong investment capacity.")
            elif savings_rate >= 10:
                st.info("💡 Good savings rate. You're building wealth steadily.")
    
    # Step 5: Additional Details (Risk tolerance and investment horizon)
    elif current_step == 5:
        model = st.session_state.pft_model or "lite"
        
        if model == "full":
            st.markdown('<div class="step-header">🎯 Your Investment Personality</div>', unsafe_allow_html=True)
        st.markdown('<div class="step-description">Let\'s understand your comfort with risk and your financial goals. This is crucial for personalized recommendations.</div>', unsafe_allow_html=True)
        
        st.markdown('<div class="help-text">💡 <b>Why we ask:</b> Your risk tolerance and time horizon determine what investments are appropriate for you. There\'s no one-size-fits-all answer!</div>', unsafe_allow_html=True)
        
        st.markdown("#### 🎲 Risk Tolerance")
        st.markdown("How comfortable are you with investment volatility?")
        
        risk_options = ["", "conservative", "moderate", "aggressive"]
        risk_labels = {
            "": "Select your risk tolerance...",
            "conservative": "Conservative - I prefer stability over high returns",
            "moderate": "Moderate - I can handle some ups and downs",
            "aggressive": "Aggressive - I'm comfortable with significant volatility for higher potential returns"
        }
        
        risk_default = 0
        current_risk = get_default("risk_tolerance", "")
        if current_risk in risk_options:
            risk_default = risk_options.index(current_risk)
        
        risk_tolerance = st.selectbox(
            "Your risk tolerance",
            risk_options,
            index=risk_default,
            format_func=lambda x: risk_labels.get(x, x)
        )
        st.session_state.profile_data["risk_tolerance"] = risk_tolerance if risk_tolerance else None
        
        if risk_tolerance:
            if risk_tolerance == "conservative":
                st.info("🛡️ **Conservative:** You prefer capital preservation. We'll focus on lower-volatility investments.")
            elif risk_tolerance == "moderate":
                st.info("⚖️ **Moderate:** You seek balanced growth. We'll mix stability with growth opportunities.")
            elif risk_tolerance == "aggressive":
                st.info("🚀 **Aggressive:** You're growth-focused. We'll consider higher-risk, higher-reward investments.")
        
        st.markdown("---")
        st.markdown("#### ⏰ Investment Horizon")
        st.markdown("How long do you plan to invest before needing this money?")
        
        investment_horizon_years = st.slider(
            "Time horizon (years)",
            min_value=0,
            max_value=40,
            value=int(get_default("investment_horizon_years", 5)),
            step=1,
            help="Longer horizons allow for more aggressive strategies"
        )
        st.session_state.profile_data["investment_horizon_years"] = investment_horizon_years if investment_horizon_years > 0 else None
        
        if investment_horizon_years > 0:
            if investment_horizon_years < 3:
                st.info("⏱️ **Short-term (< 3 years):** Consider lower-risk investments for near-term goals.")
            elif investment_horizon_years < 10:
                st.info("📅 **Medium-term (3-10 years):** A balanced approach works well for mid-range goals.")
            else:
                st.info("🗓️ **Long-term (10+ years):** Time is your friend! You can ride out market volatility.")
        
        # Risk/horizon alignment check
        if risk_tolerance and investment_horizon_years:
            if risk_tolerance == "aggressive" and investment_horizon_years < 5:
                st.markdown('<div class="validation-tip">⚠️ <b>Note:</b> Aggressive investing with a short horizon can be risky. Make sure you\'re comfortable with potential losses.</div>', unsafe_allow_html=True)
            elif risk_tolerance == "conservative" and investment_horizon_years > 15:
                st.markdown('<div class="validation-tip">💡 <b>Tip:</b> With a long horizon, you might consider a slightly higher risk tolerance to maximize growth potential.</div>', unsafe_allow_html=True)
    
    # Step 6: Review & Submit
    elif current_step == 6:
        st.markdown('<div class="step-header">✅ Review Your Profile</div>', unsafe_allow_html=True)
        st.markdown('<div class="step-description">Take a moment to review everything before saving. You can always edit later!</div>', unsafe_allow_html=True)
        
        currency = st.session_state.profile_data.get("currency", "USD")
        
        # Check if profile is essentially empty (all financial values are 0)
        total_assets = (st.session_state.profile_data.get("cash_and_equivalents", 0) +
                       st.session_state.profile_data.get("investments", 0) +
                       st.session_state.profile_data.get("real_estate", 0) +
                       st.session_state.profile_data.get("other_assets", 0))
        total_liabilities = (st.session_state.profile_data.get("short_term_debt", 0) +
                           st.session_state.profile_data.get("long_term_debt", 0) +
                           st.session_state.profile_data.get("other_liabilities", 0))
        net_income = st.session_state.profile_data.get("net_income", 0)
        
        is_empty_profile = (total_assets == 0 and total_liabilities == 0 and net_income == 0)
        
        if is_empty_profile:
            st.warning("⚠️ **Your profile appears to be incomplete.** All financial values are zero. For personalized portfolio recommendations, please go back and fill in your actual financial data.")
            st.markdown("""
            <div class="validation-tip">
            💡 <b>Why this matters:</b> Without real financial data, we can only provide generic investment advice. 
            Fill in your assets, income, and goals to get:
            <ul>
                <li>Personalized asset allocation</li>
                <li>Risk capacity analysis</li>
                <li>Goal-based recommendations</li>
                <li>Realistic portfolio suggestions</li>
            </ul>
            </div>
            """, unsafe_allow_html=True)
        
        # Summary cards
        col1, col2 = st.columns(2)
        
        model = st.session_state.pft_model or "lite"
        
        with col1:
            st.markdown("### 💰 Financial Summary")
            
            if model == "lite":
                # Display ranges for Lite mode
                st.markdown("#### 💵 Assets")
                cash_range = st.session_state.profile_data.get("cash_range", "Not specified")
                st.info(f"**Savings & Cash:** {cash_range}")
                
                investment_range = st.session_state.profile_data.get("investment_range", "Not specified")
                st.info(f"**Investments:** {investment_range}")
                
                property_status = st.session_state.profile_data.get("property_status", "Not specified")
                st.info(f"**Property:** {property_status}")
                
                st.markdown("#### 💳 Liabilities")
                debt_level = st.session_state.profile_data.get("debt_level", "Not specified")
                st.info(f"**Debt Level:** {debt_level}")
                
                st.markdown("#### 💰 Cash Flow")
                income_range = st.session_state.profile_data.get("income_range", "Not specified")
                st.info(f"**Monthly Income:** {income_range}")
                
                expense_range = st.session_state.profile_data.get("expense_range", "Not specified")
                st.info(f"**Monthly Expenses:** {expense_range}")
            else:
                # Display exact values for Full mode
                total_assets = (st.session_state.profile_data.get("cash_and_equivalents", 0) +
                               st.session_state.profile_data.get("investments", 0) +
                               st.session_state.profile_data.get("real_estate", 0) +
                               st.session_state.profile_data.get("other_assets", 0))
                
                total_liabilities = (st.session_state.profile_data.get("short_term_debt", 0) +
                                   st.session_state.profile_data.get("long_term_debt", 0) +
                                   st.session_state.profile_data.get("other_liabilities", 0))
                
                net_worth = total_assets - total_liabilities
                
                st.metric("Net Worth", f"{currency} {net_worth:,.0f}")
                st.metric("Total Assets", f"{currency} {total_assets:,.0f}")
                st.metric("Total Liabilities", f"{currency} {total_liabilities:,.0f}")
                
                net_income = st.session_state.profile_data.get("net_income", 0)
                total_expenses = (st.session_state.profile_data.get("fixed_expenses", 0) +
                                st.session_state.profile_data.get("variable_expenses", 0))
                monthly_savings = max(net_income - total_expenses, 0)
                savings_rate = (monthly_savings / net_income * 100) if net_income > 0 else 0
                
                st.metric("Monthly Savings", f"{currency} {monthly_savings:,.0f}")
                st.metric("Savings Rate", f"{savings_rate:.1f}%")
        
        with col2:
            st.markdown("### 🎯 Investment Profile")
            
            risk = st.session_state.profile_data.get("risk_tolerance", "Not specified")
            horizon = st.session_state.profile_data.get("investment_horizon_years", "Not specified")
            
            st.info(f"**Risk Tolerance:** {risk}")
            st.info(f"**Time Horizon:** {horizon} years" if isinstance(horizon, (int, float)) and horizon > 0 else f"**Time Horizon:** {horizon}")
            
            st.markdown("---")
            st.markdown("#### 🗺️ Your Financial Roadmap")
            st.caption("After saving, we'll automatically create a personalized roadmap with progressive milestones based on your financial data.")
            st.info("**Roadmap will include:**\n- Emergency fund goals\n- Debt reduction targets\n- Portfolio growth milestones\n- Path to financial independence (25x annual expenses)")
            
            # Emergency fund analysis (only for Full mode with exact expenses)
            if model == "full":
                monthly_expenses = (st.session_state.profile_data.get("fixed_expenses", 0) +
                                  st.session_state.profile_data.get("variable_expenses", 0))
                if monthly_expenses > 0:
                    cash = st.session_state.profile_data.get("cash_and_equivalents", 0)
                    emergency_months = cash / monthly_expenses
                    st.markdown("---")
                    st.markdown("#### 🏥 Emergency Fund")
                    st.metric("Months of Coverage", f"{emergency_months:.1f} months")
                    
                    if emergency_months < 3:
                        st.warning("Consider building 3-6 months of emergency savings")
                    elif emergency_months >= 6:
                        st.success("Excellent emergency fund!")
                    else:
                        st.info("Good progress on emergency fund")
        
        st.markdown("---")
        
        # Expandable detailed view
        with st.expander("📋 View Complete Details"):
            st.json(st.session_state.profile_data)
        
        st.markdown("---")
        
        col_back, col_save = st.columns([1, 2])
        with col_back:
            if st.button("← Back to Edit", use_container_width=True):
                prev_step()
                st.rerun()
        
        with col_save:
            if st.button("💾 Save Profile & Get Recommendations", type="primary", use_container_width=True):
                # Save all profile data to user document first
                save_profile_data_to_user(user_id, st.session_state.profile_data)
                
                # Create PFS
                payload = PFSCreate(
                    currency=st.session_state.profile_data.get("currency", "USD"),
                    gross_income=st.session_state.profile_data.get("gross_income", 0.0),
                    net_income=st.session_state.profile_data.get("net_income", 0.0),
                    fixed_expenses=st.session_state.profile_data.get("fixed_expenses", 0.0),
                    variable_expenses=st.session_state.profile_data.get("variable_expenses", 0.0),
                    cash_and_equivalents=st.session_state.profile_data.get("cash_and_equivalents", 0.0),
                    investments=st.session_state.profile_data.get("investments", 0.0),
                    real_estate=st.session_state.profile_data.get("real_estate", 0.0),
                    other_assets=st.session_state.profile_data.get("other_assets", 0.0),
                    short_term_debt=st.session_state.profile_data.get("short_term_debt", 0.0),
                    long_term_debt=st.session_state.profile_data.get("long_term_debt", 0.0),
                    other_liabilities=st.session_state.profile_data.get("other_liabilities", 0.0),
                    risk_tolerance=st.session_state.profile_data.get("risk_tolerance"),
                    investment_horizon_years=st.session_state.profile_data.get("investment_horizon_years"),
                    goal_type=st.session_state.profile_data.get("goal_type"),
                )
                new_pfs = create_pfs_for_user(user_id, payload)
                
                # Store success info and trigger success screen
                st.session_state.saved_net_worth = f"{new_pfs.currency} {new_pfs.net_worth:,.0f}"
                st.session_state.show_success_message = True
                st.session_state.profile_step = 0
                st.session_state.profile_data = {}
                st.rerun()
    
    # Navigation buttons
    st.markdown("---")
    col1, col2, col3, col4 = st.columns([1, 1, 2, 1])
    
    with col1:
        if current_step > 0:
            if st.button("← Previous", use_container_width=True):
                prev_step()
                st.rerun()
    
    with col2:
        if current_step < TOTAL_STEPS - 1:
            if st.button("⏭️ Skip", use_container_width=True, help="Skip this step"):
                skip_step()
                st.rerun()
    
    with col4:
        if current_step < TOTAL_STEPS - 1:
            if st.button("Next →", type="primary", use_container_width=True):
                next_step()
                st.rerun()


def render_quick_edit_interface(user_id: str, latest_pfs):
    """Original quick edit interface for advanced users."""
    st.markdown("### ⚡ Quick Edit Mode")
    st.caption("For advanced users who want direct access to all fields.")
    
    def _field(name: str, default: float = 0.0) -> float:
        return getattr(latest_pfs, name) if latest_pfs else default

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Income & Expenses (per month)")
        
        gross_income = st.number_input(
            "Gross income",
            value=float(_field("gross_income", 0.0)),
            min_value=0.0,
            step=100.0,
        )
        net_income = st.number_input(
            "Net income",
            value=float(_field("net_income", 0.0)),
            min_value=0.0,
            step=100.0,
        )
        fixed_expenses = st.number_input(
            "Fixed expenses",
            value=float(_field("fixed_expenses", 0.0)),
            min_value=0.0,
            step=50.0,
        )
        variable_expenses = st.number_input(
            "Variable expenses",
            value=float(_field("variable_expenses", 0.0)),
            min_value=0.0,
            step=50.0,
        )

        st.subheader("Assets")
        cash_eq = st.number_input(
            "Cash & equivalents",
            value=float(_field("cash_and_equivalents", 0.0)),
            min_value=0.0,
            step=500.0,
        )
        investments = st.number_input(
            "Investments",
            value=float(_field("investments", 0.0)),
            min_value=0.0,
            step=500.0,
        )
        real_estate = st.number_input(
            "Real estate",
            value=float(_field("real_estate", 0.0)),
            min_value=0.0,
            step=1000.0,
        )
        other_assets = st.number_input(
            "Other assets",
            value=float(_field("other_assets", 0.0)),
            min_value=0.0,
            step=500.0,
        )

    with col_right:
        st.subheader("Liabilities")
        short_debt = st.number_input(
            "Short-term debt",
            value=float(_field("short_term_debt", 0.0)),
            min_value=0.0,
            step=100.0,
        )
        long_debt = st.number_input(
            "Long-term debt",
            value=float(_field("long_term_debt", 0.0)),
            min_value=0.0,
            step=500.0,
        )
        other_liab = st.number_input(
            "Other liabilities",
            value=float(_field("other_liabilities", 0.0)),
            min_value=0.0,
            step=100.0,
        )

        st.subheader("Profile & Goals")
        
        # Load profile data from user document for additional fields
        profile_data = get_profile_data_from_user(user_id)
        
        currency = st.text_input(
            "Currency",
            value=(latest_pfs.currency if latest_pfs else "USD"),
        )
        
        # Life Context
        age_ranges = ["", "18-25", "26-35", "36-45", "46-60", "60+"]
        age_range = st.selectbox(
            "Age range",
            age_ranges,
            index=age_ranges.index(profile_data.get("age_range", "")) if profile_data.get("age_range", "") in age_ranges else 0,
            help="Used to model time horizon and life stage"
        )
        
        countries = ["", "United States", "United Kingdom", "Canada", "Germany", "India", "Australia", "Other"]
        country = st.selectbox(
            "Country/Region",
            countries,
            index=countries.index(profile_data.get("country", "")) if profile_data.get("country", "") in countries else 0,
            help="Helps us understand market access"
        )
        
        employment_types = ["", "Salaried", "Self-employed", "Retired", "Mixed", "Student", "Other"]
        employment_type = st.selectbox(
            "Employment type",
            employment_types,
            index=employment_types.index(profile_data.get("employment_type", "")) if profile_data.get("employment_type", "") in employment_types else 0,
            help="Used to model income volatility"
        )

        risk_options = ["", "conservative", "moderate", "aggressive"]
        risk_default = 0
        if latest_pfs and latest_pfs.risk_tolerance in risk_options:
            risk_default = risk_options.index(latest_pfs.risk_tolerance)

        risk_tolerance = st.selectbox(
            "Risk tolerance",
            risk_options,
            index=risk_default,
        )

        horizon_val = (
            int(latest_pfs.investment_horizon_years)
            if latest_pfs and latest_pfs.investment_horizon_years
            else 0
        )
        investment_horizon_years = st.number_input(
            "Investment horizon (years)",
            value=horizon_val,
            min_value=0,
            step=1,
        )

        goal_type = st.text_input(
            "Primary goal (e.g. retirement, house)",
            value=(latest_pfs.goal_type or "") if latest_pfs else "",
        )

    # Derived metrics preview
    total_assets = cash_eq + investments + real_estate + other_assets
    total_liab = short_debt + long_debt + other_liab
    net_worth_preview = total_assets - total_liab
    monthly_savings_preview = max(net_income - (fixed_expenses + variable_expenses), 0.0)

    # Gentle validation hints (friendly coach style)
    total_expenses_preview = fixed_expenses + variable_expenses

    if net_income > 0 and total_expenses_preview >= net_income:
        st.warning(
            "Your monthly expenses are as high as, or higher than, your net income. "
            "That makes it hard to build savings. Even a small gap between income and expenses "
            "can make a big difference over time."
        )

    if net_worth_preview < 0:
        st.warning(
            "Your preview net worth is negative. That's not unusual, especially early on, "
            "but it does mean that focusing on reducing debt or increasing savings may be helpful."
        )

    if net_income > 0 and monthly_savings_preview / net_income * 100 < 5:
        st.info(
            "Your savings rate is quite low right now. If it feels manageable, you might aim to "
            "slowly nudge it up over time."
        )

    # Risk tolerance vs horizon quick hint
    if risk_tolerance and investment_horizon_years is not None:
        rt = (risk_tolerance or "").lower()
        if rt.startswith("aggress") and investment_horizon_years < 3:
            st.info(
                "You've selected an **aggressive** risk tolerance with a relatively short horizon. "
                "That can work, but it may also mean larger swings along the way. Make sure that "
                "feels comfortable for you."
            )
        if rt.startswith("conserv") and investment_horizon_years > 15:
            st.info(
                "You've selected a **conservative** risk tolerance with a long horizon. "
                "That's perfectly fine, but you may want to check whether this still aligns with "
                "your long-term growth goals."
            )


    st.markdown("### Preview summary")
    st.write(f"- **Net worth (preview):** {net_worth_preview:,.2f} {currency}")
    st.write(f"- **Monthly savings (preview):** {monthly_savings_preview:,.2f} {currency}")
    if net_income > 0:
        st.write(f"- **Savings rate (preview):** {monthly_savings_preview / net_income * 100:,.1f}%")

    if st.button("Save new snapshot", type="primary"):
        # Save PFS snapshot
        payload = PFSCreate(
            currency=currency or "USD",
            gross_income=gross_income,
            net_income=net_income,
            fixed_expenses=fixed_expenses,
            variable_expenses=variable_expenses,
            cash_and_equivalents=cash_eq,
            investments=investments,
            real_estate=real_estate,
            other_assets=other_assets,
            short_term_debt=short_debt,
            long_term_debt=long_debt,
            other_liabilities=other_liab,
            risk_tolerance=risk_tolerance or None,
            investment_horizon_years=investment_horizon_years or None,
            goal_type=goal_type or None,
        )
        new_pfs = create_pfs_for_user(user_id, payload)
        
        # Save additional profile data (life context)
        additional_profile_data = {
            "age_range": age_range if age_range else None,
            "country": country if country else None,
            "employment_type": employment_type if employment_type else None,
            "currency": currency or "USD",
        }
        
        # Merge with existing profile data to preserve other fields
        existing_profile = get_profile_data_from_user(user_id)
        existing_profile.update(additional_profile_data)
        save_profile_data_to_user(user_id, existing_profile)
        
        st.success(f"Snapshot saved. Net worth: {new_pfs.net_worth:,.2f} {new_pfs.currency}. View your progress on the [Dashboard page](/Dashboard).")
        st.rerun()


# Privacy Controls
st.markdown("---")
st.markdown("### 🔒 Privacy & Data Controls")
st.caption("Manage how your financial data is used for personalized recommendations.")

col_privacy1, col_privacy2, col_privacy3 = st.columns(3)

with col_privacy1:
    # Pause Personalization button
    pause_label = "▶️ Resume Personalization" if st.session_state.pause_personalization else "⏸️ Pause Personalization"
    pause_help = "Resume using your financial data for personalized recommendations" if st.session_state.pause_personalization else "Temporarily stop using your financial data for personalized recommendations"
    
    if st.button(pause_label, use_container_width=True, help=pause_help):
        st.session_state.pause_personalization = not st.session_state.pause_personalization
        
        if st.session_state.pause_personalization:
            st.success("✅ Personalization paused. You'll receive generic investment advice without using your financial profile.")
        else:
            st.success("✅ Personalization resumed. Your financial profile will be used for tailored recommendations.")
        
        st.rerun()
    
    if st.session_state.pause_personalization:
        st.info("🔕 **Personalization is currently paused.** Generic advice will be provided.")

with col_privacy2:
    # Delete My Twin button with confirmation
    if "confirm_delete_twin" not in st.session_state:
        st.session_state.confirm_delete_twin = False
    
    if not st.session_state.confirm_delete_twin:
        if st.button("🗑️ Delete My Twin", use_container_width=True, help="Permanently delete all your financial profile data"):
            st.session_state.confirm_delete_twin = True
            st.rerun()
    else:
        st.warning("⚠️ **Are you sure?** This will permanently delete all your financial snapshots and profile data. This action cannot be undone.")
        
        col_confirm1, col_confirm2 = st.columns(2)
        with col_confirm1:
            if st.button("❌ Cancel", use_container_width=True):
                st.session_state.confirm_delete_twin = False
                st.rerun()
        with col_confirm2:
            if st.button("✔️ Yes, Delete", type="primary", use_container_width=True):
                try:
                    # Delete all PFS records for this user
                    pfs_collection = db_fs.collection("personal_financial_statement")
                    user_pfs_docs = pfs_collection.where("user_id", "==", user_id).stream()
                    
                    deleted_count = 0
                    for doc in user_pfs_docs:
                        doc.reference.delete()
                        deleted_count += 1
                    
                    # Reset session state
                    st.session_state.profile_data = {}
                    st.session_state.profile_step = 0
                    st.session_state.pause_personalization = False
                    st.session_state.confirm_delete_twin = False
                    
                    st.success(f"✅ Successfully deleted {deleted_count} financial snapshot(s). Your Financial Twin has been removed.")
                    st.info("You can create a new profile anytime by filling out the form below.")
                    st.balloons()
                    
                except Exception as e:
                    st.error(f"❌ Error deleting Financial Twin: {str(e)}")
                    st.session_state.confirm_delete_twin = False
                
                st.rerun()

with col_privacy3:
    # Delete Entire Profile (Quit Perfient) - multi-step confirmation
    if "delete_profile_step" not in st.session_state:
        st.session_state.delete_profile_step = 0
    
    if st.session_state.delete_profile_step == 0:
        if st.button("🚨 Quit Perfient", use_container_width=True, help="Permanently delete all data and close your account", type="secondary"):
            st.session_state.delete_profile_step = 1
            st.rerun()
    elif st.session_state.delete_profile_step == 1:
        st.error("⚠️ **WARNING: This will permanently delete ALL your data:**")
        st.markdown("""
        - ❌ Financial profile (all PFS snapshots)
        - ❌ Financial Twin model
        - ❌ Portfolio data
        - ❌ Analysis history  
        - ❌ All chat conversations
        - ❌ User account
        """)
        st.caption("**⚠️ This action CANNOT be undone!**")
        
        col_next, col_back = st.columns(2)
        with col_back:
            if st.button("← Go Back", use_container_width=True):
                st.session_state.delete_profile_step = 0
                st.rerun()
        with col_next:
            if st.button("Continue →", type="primary", use_container_width=True):
                st.session_state.delete_profile_step = 2
                st.rerun()
    elif st.session_state.delete_profile_step == 2:
        st.error("### 🔐 FINAL CONFIRMATION")
        
        # Determine what to use for confirmation: email or user ID
        user_email = st.session_state.get("current_user_email", "")
        use_email_confirmation = bool(user_email and user_email.strip())
        
        if use_email_confirmation:
            st.markdown("**Type your email address to confirm deletion:**")
            st.caption(f"Expected: {user_email}")
            
            confirmation_text = st.text_input(
                "Email address",
                placeholder="your.email@example.com",
                key="delete_confirmation_email"
            )
            expected_value = user_email.lower().strip()
            entered_value = confirmation_text.lower().strip()
        else:
            # Fallback to user ID confirmation if no email
            st.markdown("**Type your user ID to confirm deletion:**")
            st.caption(f"Expected: {user_id}")
            st.info("💡 Your account doesn't have an email address, so we'll use your user ID for confirmation.")
            
            confirmation_text = st.text_input(
                "User ID",
                placeholder="Enter your user ID",
                key="delete_confirmation_userid"
            )
            expected_value = user_id.strip()
            entered_value = confirmation_text.strip()
        
        col_delete, col_cancel = st.columns(2)
        with col_cancel:
            if st.button("← Cancel", use_container_width=True):
                st.session_state.delete_profile_step = 0
                st.rerun()
        with col_delete:
            confirmation_match = (entered_value == expected_value)
            if st.button("🗑️ DELETE ALL DATA", type="primary", use_container_width=True, disabled=not confirmation_match):
                if confirmation_match:
                    try:
                        # Show progress
                        progress_bar = st.progress(0, text="Starting deletion...")
                        
                        # 1. Delete all PFS snapshots
                        progress_bar.progress(0.15, text="Deleting financial snapshots...")
                        pfs_collection = db_fs.collection("personal_financial_statement")
                        user_pfs_docs = pfs_collection.where("user_id", "==", user_id).stream()
                        for doc in user_pfs_docs:
                            doc.reference.delete()
                        
                        # 2. Delete twin snapshots from users subcollection
                        progress_bar.progress(0.30, text="Deleting Financial Twin...")
                        try:
                            twin_docs = db_fs.collection("users").document(user_id).collection("twins").stream()
                            for doc in twin_docs:
                                doc.reference.delete()
                        except:
                            pass
                        
                        # 3. Delete decision history
                        progress_bar.progress(0.45, text="Deleting analysis history...")
                        try:
                            decision_docs = db_fs.collection("users").document(user_id).collection("decisions").stream()
                            for doc in decision_docs:
                                doc.reference.delete()
                        except:
                            pass
                        
                        # 4. Delete PFS subcollection from users
                        progress_bar.progress(0.60, text="Deleting profile data...")
                        try:
                            pfs_docs = db_fs.collection("users").document(user_id).collection("pfs").stream()
                            for doc in pfs_docs:
                                doc.reference.delete()
                        except:
                            pass
                        
                        # 5. Delete portfolio data
                        progress_bar.progress(0.75, text="Deleting portfolio...")
                        try:
                            portfolio_ref = db_fs.collection("portfolios").document(user_id)
                            portfolio_ref.delete()
                        except:
                            pass
                        
                        # 6. Delete user document
                        progress_bar.progress(0.90, text="Deleting user account...")
                        user_ref = db_fs.collection("users").document(user_id)
                        user_ref.delete()
                        
                        # 7. Clear session state
                        progress_bar.progress(1.0, text="Clearing session...")
                        for key in list(st.session_state.keys()):
                            del st.session_state[key]
                        
                        st.success("✅ **All data has been permanently deleted.**")
                        st.info("👋 Thank you for using Perfient. You'll be redirected in 3 seconds...")
                        
                        # Redirect to landing page
                        import time
                        time.sleep(3)
                        st.markdown("""
                        <meta http-equiv="refresh" content="0;url=https://perfient.com">
                        <p style="text-align:center;margin-top:2rem;">
                            <a href="https://perfient.com" style="color:#17a673;font-weight:600;">Click here if not redirected</a>
                        </p>
                        """, unsafe_allow_html=True)
                        st.stop()
                        
                    except Exception as e:
                        st.error(f"❌ Error during deletion: {e}")
                        st.warning("Some data may have been deleted. Please contact support@perfient.com for assistance.")
                        st.session_state.delete_profile_step = 0
                else:
                    if use_email_confirmation:
                        st.error("❌ Email does not match. Deletion cancelled.")
                    else:
                        st.error("❌ User ID does not match. Deletion cancelled.")

# Data Export (GDPR Compliance)
st.markdown("---")
st.markdown("### 📥 Export Your Data")
st.caption("Download a copy of all your financial data (GDPR compliance)")
st.info("💡 **Tip:** Export your data before deleting your account. You can import it later if you return to Perfient!")

if st.button("📄 Export All Data as JSON", use_container_width=False):
    try:
        from datetime import datetime
        import json
        
        export_data = {
            "export_date": datetime.now().isoformat(),
            "user_id": user_id,
            "user_email": st.session_state.current_user_email,
            "profile_data": {},
            "pfs_snapshots": [],
            "portfolio": {},
            "decisions": []
        }
        
        # Get user profile data
        user_doc = db_fs.collection("users").document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            # Remove sensitive fields if any
            if "password" in user_data:
                del user_data["password"]
            export_data["profile_data"] = user_data
        
        # Get all PFS snapshots
        pfs_collection = db_fs.collection("personal_financial_statement")
        user_pfs_docs = pfs_collection.where("user_id", "==", user_id).stream()
        for doc in user_pfs_docs:
            pfs_data = doc.to_dict()
            pfs_data["id"] = doc.id
            export_data["pfs_snapshots"].append(pfs_data)
        
        # Get portfolio
        try:
            portfolio_doc = db_fs.collection("portfolios").document(user_id).get()
            if portfolio_doc.exists:
                export_data["portfolio"] = portfolio_doc.to_dict()
        except:
            pass
        
        # Get decision history (last 100)
        try:
            decision_docs = db_fs.collection("users").document(user_id).collection("decisions").limit(100).stream()
            for doc in decision_docs:
                decision_data = doc.to_dict()
                decision_data["id"] = doc.id
                export_data["decisions"].append(decision_data)
        except:
            pass
        
        # Convert to JSON
        json_data = json.dumps(export_data, indent=2, default=str)
        
        # Provide download button
        st.download_button(
            label="⬇️ Download perfient_data.json",
            data=json_data,
            file_name=f"perfient_data_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=False
        )
        st.success("✅ Data export ready! Click the button above to download.")
        st.info("💡 This file contains all your financial data in JSON format. Keep it secure!")
        
    except Exception as e:
        st.error(f"Error exporting data: {e}")

# Mode toggle and routing
st.markdown("---")
col_mode1, col_mode2 = st.columns(2)
with col_mode1:
    if st.button("📝 Guided Setup (Recommended)", use_container_width=True, type="primary" if st.session_state.profile_mode == "wizard" else "secondary"):
        st.session_state.profile_mode = "wizard"
        st.rerun()
with col_mode2:
    if st.button("⚡ Quick Edit (Advanced)", use_container_width=True, type="primary" if st.session_state.profile_mode == "edit" else "secondary"):
        st.session_state.profile_mode = "edit"
        st.rerun()

st.markdown("---")

# Route to appropriate interface
if st.session_state.profile_mode == "wizard":
    render_wizard_interface(user_id, latest_pfs)
else:
    render_quick_edit_interface(user_id, latest_pfs)
