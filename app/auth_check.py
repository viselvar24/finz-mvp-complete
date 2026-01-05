# app/auth_check.py
"""
Centralized authentication checking for Streamlit app.
Import and call require_authentication() at the start of each page.
"""

import os
import streamlit as st
import requests
import logging

logger = logging.getLogger(__name__)

# Configuration
AUTH_API_BASE = "https://perfient-auth-611410191564.europe-west1.run.app"
LANDING_PAGE_URL = "https://perfient.com"

def check_authentication():
    """
    Verify user authentication by checking session cookie with auth service.
    Returns True if authenticated, False otherwise.
    """
    try:
        # Try to get cookies from Streamlit's request context
        cookie_header = ""
        
        # Method 1: Try modern st.context.headers (Streamlit >= 1.29)
        try:
            if hasattr(st, 'context') and hasattr(st.context, 'headers'):
                headers = st.context.headers
                if headers:
                    cookie_header = headers.get("Cookie", "")
        except Exception:
            pass
        
        # Method 2: Fallback to script run context for older versions
        if not cookie_header:
            try:
                from streamlit.runtime.scriptrunner import get_script_run_ctx
                ctx = get_script_run_ctx()
                if ctx and hasattr(ctx, 'session_info'):
                    if hasattr(ctx.session_info, 'ws'):
                        cookie_header = ctx.session_info.ws.request.headers.get("Cookie", "")
            except Exception:
                pass
        
        # If no cookies found, authentication fails
        if not cookie_header:
            logger.warning("No cookie header found - user likely not authenticated")
            return False
        
        # Verify with auth service
        response = requests.get(
            f"{AUTH_API_BASE}/auth/verify",
            headers={"Cookie": cookie_header},
            timeout=5
        )
        
        return response.status_code == 200
    except Exception as e:
        logger.warning(f"Authentication check failed: {e}")
        return False

def require_authentication():
    """
    Check authentication and show login prompt if not authenticated.
    Call this at the start of your Streamlit pages.
    """
    # Skip auth check in development mode (local testing)
    if os.getenv("STREAMLIT_DEV_MODE") == "true":
        st.session_state.authenticated = True
        return True
    
    # Check if already verified in session
    if st.session_state.get("authenticated", False):
        return True
    
    # Check for auth token in query parameters (fallback method)
    query_params = st.query_params
    auth_token = query_params.get("auth_token", None)
    if auth_token:
        # Verify token with auth service
        try:
            response = requests.post(
                f"{AUTH_API_BASE}/auth/verify-token",
                json={"token": auth_token},
                timeout=5
            )
            if response.status_code == 200:
                # Extract user data from response
                data = response.json()
                if data.get('valid') and data.get('user'):
                    user = data['user']
                    # Store user info in session state for profile auto-loading
                    st.session_state.authenticated = True
                    st.session_state.current_user_username = user.get('username')
                    st.session_state.current_user_email = user.get('email')  # May be None
                    st.session_state.current_user_id = user.get('id')
                    logger.info(f"User authenticated: {user.get('username')}")
                    # Clear token from URL for security
                    st.query_params.clear()
                    return True
        except Exception as e:
            logger.warning(f"Token verification failed: {e}")
    
    # Verify authentication via cookies
    if check_authentication():
        st.session_state.authenticated = True
        return True
    
    # Not authenticated - show login prompt
    st.title("🔒 Authentication Required")
    st.warning("You need to log in to access Perfient.")
    
    st.markdown(f"""
    ### Please log in to continue
    
    You'll be redirected to our secure login page in 3 seconds...
    
    [Go to Login Page Now →]({LANDING_PAGE_URL})
    """)
    
    # Auto-redirect using meta refresh (more reliable than JavaScript in Streamlit)
    st.markdown(f"""
    <meta http-equiv="refresh" content="3;url={LANDING_PAGE_URL}">
    <p style="text-align:center;color:#888;margin-top:2rem;">
        <em>Not redirecting automatically? <a href="{LANDING_PAGE_URL}" style="color:#17a673;font-weight:600;">Click here to login</a></em>
    </p>
    """, unsafe_allow_html=True)
    
    st.stop()

def logout():
    """
    Clear authentication session and redirect to landing page.
    """
    # Clear all authentication-related session state
    if "authenticated" in st.session_state:
        del st.session_state.authenticated
    if "current_user_email" in st.session_state:
        del st.session_state.current_user_email
    if "current_user_id" in st.session_state:
        del st.session_state.current_user_id
    
    # Clear all other session state for fresh start
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    
    # Show logout message and redirect
    st.success("✅ Logged out successfully!")
    st.markdown(f"""
    <meta http-equiv="refresh" content="1;url={LANDING_PAGE_URL}">
    <p style="text-align:center;color:#888;margin-top:1rem;">
        <em>Redirecting to login page... <a href="{LANDING_PAGE_URL}" style="color:#17a673;font-weight:600;">Click here if not redirected</a></em>
    </p>
    """, unsafe_allow_html=True)
    st.stop()
