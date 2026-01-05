# pages/Decisions_Admin.py
import streamlit as st
from google.cloud import firestore
import pandas as pd
from datetime import datetime
from app.auth_check import require_authentication

st.set_page_config(page_title="Analysis History", layout="wide")

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

st.title("Analysis History")

_db = firestore.Client()

def list_recent_decisions(user_id: str, limit=50):
    """List recent decisions for a specific user."""
    if not user_id:
        return pd.DataFrame()
    
    rows = []
    user_ref = _db.collection("users").document(user_id)
    decs = user_ref.collection("decisions").order_by("created_at_ms", direction=firestore.Query.DESCENDING).limit(limit).stream()
    for d in decs:
        doc = d.to_dict()
        rows.append({
            "user_id": user_id,
            "decision_id": doc.get("_id") or d.id,
            "query": doc.get("query"),
            "created_at_ms": doc.get("created_at_ms"),
            "proposal_action": (doc.get("proposal") or {}).get("action"),
            "proposal_dollar": (doc.get("proposal") or {}).get("dollar"),
            "fit": (doc.get("fit_output") or {}).get("fit"),
            "feedback": (doc.get("feedback") or {}),
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at_ms"], unit='ms')
    df = df.sort_values("created_at", ascending=False)
    return df

# Get logged-in user's ID
current_user_id = st.session_state.get("current_user_id")
if not current_user_id:
    st.warning("No user logged in. Please log in to view your analysis history.")
    st.stop()

df = list_recent_decisions(current_user_id, limit=50)
if df.empty:
    st.write("No analysis history found yet. Start by asking investment questions in the Chat page!")
else:
    st.dataframe(df[["created_at","decision_id","query","proposal_action","proposal_dollar","fit","feedback"]], height=600)

    # allow selection of a decision to inspect trace
    sel = st.text_input("Enter Decision ID to inspect")
    if sel:
        # try to find doc for current user only
        try:
            doc_ref = _db.collection("users").document(current_user_id).collection("decisions").document(sel)
            doc = doc_ref.get()
            if not doc.exists:
                st.warning("Decision not found in your history.")
            else:
                st.subheader("Decision doc")
                st.json(doc.to_dict())
        except Exception as e:
            st.error(f"Error loading decision: {e}")
