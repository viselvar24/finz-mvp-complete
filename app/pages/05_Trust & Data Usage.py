import streamlit as st
from app.auth_check import require_authentication

st.set_page_config(page_title="Trust & Data Usage", layout="centered")

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

st.title("Trust & Data Usage at Perfient")

st.markdown("""
### 🛡️ Trust is Our Foundation

We take trust seriously. Building a Financial Twin requires sharing sensitive information, and we understand the responsibility that comes with it.

**📖 For complete transparency on our security practices, data handling, and privacy commitments:**  
👉 **[Visit our Trust Center](https://perfient.com/trust-center.html)** for detailed information on encryption, compliance, audits, and more.

---
""")

st.markdown("""
### Your data belongs to you
Perfient does **not** sell personal data, show ads, or monetize user information.
Your data is used only to help you make better investment decisions.
""")

st.markdown("""
### Personal Financial Twin (PFT)
Your PFT is a private analytical model — not a copy of your accounts.
It estimates risk capacity, stress, and goal feasibility using the data you choose to share.
""")

st.markdown("""
### PFT Lite vs Full
**Lite:** No sensitive data, directional insights  
**Full:** Optional precision using income, expenses, and assets
""")

st.markdown("""
### What we never do
- selling data  
- advertising  
- training AI on raw financial data  
- autonomous trades  
""")

st.markdown("""
### Your controls
- Inspect reasoning (Developer Mode)
- Pause personalization
- Delete your twin anytime
""")

st.info("Trust is not a claim — it’s a design choice.")
