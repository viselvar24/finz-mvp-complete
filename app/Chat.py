# app/Chat.py
import os
import sys

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not required if env vars are set another way

# Add parent directory to path for imports to work when running directly
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

import streamlit as st
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple
from functools import lru_cache
import pandas as pd
import time
import traceback
import re
import requests 
import random 
from dataclasses import dataclass
import uuid
import logging

# Module logger (ensure defined for all call sites)
logger = logging.getLogger(__name__)
if not logging.getLogger().hasHandlers():
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO))

# MUST be first Streamlit command - configure page
st.set_page_config(
    page_title="Perfient — Chat",
    layout="wide",
    page_icon="💰",
    initial_sidebar_state="expanded"
)

# Load professional UI components and styling
try:
    from app.ui_components import (
        load_custom_css,
        show_loading_spinner,
        show_skeleton_screen,
        show_trust_signals,
        show_professional_header,
        show_professional_footer,
        LoadingContext,
        lazy_load_component
    )
    load_custom_css()
except ImportError:
    # Fallback if ui_components not available
    def load_custom_css(): pass
    def show_trust_signals(): pass
    def show_professional_header(title, subtitle=None): st.title(title)
    def show_professional_footer(): pass
    class LoadingContext:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def lazy_load_component(func, *args, **kwargs): return func()

# Authentication configuration
AUTH_API_BASE = "https://perfient-auth-611410191564.europe-west1.run.app"
LANDING_PAGE_URL = "https://perfient.com"

# Import portfolio recommender for consistent allocation recommendations
from app.portfolio_recommender import calculate_recommended_portfolio, get_allocation_explanation

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
            import streamlit as st
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
            return False
        
        # Verify with auth service
        response = requests.get(
            f"{AUTH_API_BASE}/auth/verify",
            headers={"Cookie": cookie_header},
            timeout=5
        )
        
        return response.status_code == 200
    except Exception as e:
        # Use print for now since logger might not be initialized yet
        print(f"Authentication check failed: {e}")
        return False

def require_authentication():
    """
    Check authentication and show login prompt if not authenticated.
    Call this at the start of your app.
    """
    # Skip auth check in development mode (local testing)
    if os.getenv("STREAMLIT_DEV_MODE") == "true":
        st.session_state.authenticated = True
        return True
    
    # Check if already verified in session
    if st.session_state.get("authenticated", False):
        return True
    
    # Check for auth token in query parameters (primary authentication method)
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
                    st.session_state.current_user_email = user.get('email')
                    st.session_state.current_user_id = user.get('id')
                    print(f"User authenticated: {user.get('username')} ({user.get('email')})")
                    # Clear token from URL for security
                    st.query_params.clear()
                    return True
        except Exception as e:
            print(f"Token verification failed: {e}")
    
    # Fallback: Verify authentication via cookies
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
    if "current_user_username" in st.session_state:
        del st.session_state.current_user_username
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

# Import valuation engine with fallback
try:
    from app.valuation_engine.analyze import analyze_ticker

    # --- ETF Analysis Import ---
    from app.valuation_engine.analyze import analyze_etf
    VALUATION_AVAILABLE = True
except Exception as e:
    print(f"Warning: Valuation engine not available: {e}")
    analyze_ticker = None
    analyze_etf = None


# Lazy-load heavy imports to speed up initial page load
def get_pfs_functions():
    """Lazy-load PFS service functions."""
    from app.pfs_service import (
        get_latest_pfs_for_user,
        build_pfs_prompt_fragment,
        get_pfs_history_for_user,
        get_net_worth_series_for_user,
        create_pfs_for_user,
    )
    return {
        'get_latest_pfs_for_user': get_latest_pfs_for_user,
        'build_pfs_prompt_fragment': build_pfs_prompt_fragment,
        'get_pfs_history_for_user': get_pfs_history_for_user,
        'get_net_worth_series_for_user': get_net_worth_series_for_user,
        'create_pfs_for_user': create_pfs_for_user,
    }


def get_pft_functions():
    """Lazy-load PFT functions."""
    from app.pft import load_twin_snapshot, build_and_save_twin, get_or_build_twin, build_twin_lite
    return {
        'load_twin_snapshot': load_twin_snapshot,
        'build_and_save_twin': build_and_save_twin,
        'get_or_build_twin': get_or_build_twin,
        'build_twin_lite': build_twin_lite,
    }


def get_logging_function():
    """Lazy-load logging function."""
    from app.logging import persist_decision_trace_safe
    return persist_decision_trace_safe


def get_utils_functions():
    """Lazy-load utils functions."""
    from app.utils import fetch_company_profile, fetch_latest_price, fetch_news_finnhub, fetch_tiingo_search
    return {
        'fetch_company_profile': fetch_company_profile,
        'fetch_latest_price': fetch_latest_price,
        'fetch_news_finnhub': fetch_news_finnhub,
        'fetch_tiingo_search': fetch_tiingo_search,
    }


def get_rag_functions():
    """Lazy-load RAG functions."""
    from app.rag import summarize_with_evidence, summarize_with_evidence_and_pfs, normalize_passages
    return {
        'summarize_with_evidence': summarize_with_evidence,
        'summarize_with_evidence_and_pfs': summarize_with_evidence_and_pfs,
        'normalize_passages': normalize_passages,
    }


def get_rag_retrieval_functions():
    """Lazy-load RAG document retrieval functions."""
    try:
        import sys
        import os
        # Add db_service to path if not already there
        db_service_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'db_service')
        if os.path.exists(db_service_path) and db_service_path not in sys.path:
            sys.path.insert(0, db_service_path)
        
        from rag_pipeline.vector_storage import RAGDocumentStore
        return {
            'RAGDocumentStore': RAGDocumentStore,
        }
    except Exception as e:
        logger.warning(f"RAG document retrieval not available: {e}")
        return {}



def get_vector_functions():
    """Lazy-load vector store functions."""
    from app.vector_store import retrieve, upsert
    return {
        'retrieve': retrieve,
        'upsert': upsert,
    }


def get_scoring_function():
    """Lazy-load scoring function."""
    from app.scoring import simple_score
    return simple_score


def get_trade_functions():
    """Lazy-load trade functions. Only the advanced proposer is supported now."""
    from app.trades import propose_trade_advanced
    return {
        'propose_trade_advanced': propose_trade_advanced,
    }


def get_alpaca_functions():
    """Lazy-load Alpaca execution functions."""
    from app.alpaca_exec import place_order_buy, place_order_sell
    return {
        'place_order_buy': place_order_buy,
        'place_order_sell': place_order_sell,
    }


def get_scoring_functions():
    """Lazy-load scoring functions."""
    from app.scoring import perfient_fit_score, fit_score
    return {
        'perfient_fit_score': perfient_fit_score,
        'fit_score': fit_score,
    }


INTENT_KEYWORDS = {
    "analyze", "analysis", "review", "check", "look", "opinion",
    "stock", "stocks", "share", "shares",
    "buy", "sell", "hold",
    "invest", "investment", "portfolio", "position", "ticker", "price",
    "compare", "versus", "vs",
}

STOPWORDS = {
    "COULD", "WOULD", "SHOULD", "HELP", "PLEASE", "YOU", "YOUR", "ME",
    "MY", "THE", "A", "AN", "IN", "ON", "AT", "IS", "IT", "IF", "AND",
    "OR", "TO", "OF", "FOR", "WITH", "ABOUT", "REVIEW", "ANALYZE",
    "CHECK", "LOOK", "STOCK", "STOCKS", "INVEST", "INVESTMENT", "PRICE",
    "COMPARE", "VERSUS", "VS",
    # Common conversational words that shouldn't be treated as tickers
    "YES", "NO", "OK", "OKAY", "SURE", "THANKS", "THANK", "HI", "HELLO",
    "BYE", "GOODBYE", "HOW", "WHAT", "WHY", "WHEN", "WHERE", "WHO",
    "CAN", "WILL", "DO", "DOES", "DID", "HAVE", "HAS", "HAD", "BE",
    "AM", "ARE", "WAS", "WERE", "BEEN", "BEING", "NOT", "BUT", "SO",
    "THEN", "NOW", "JUST", "LIKE", "MORE", "MOST", "SOME", "ANY", "ALL",
    "VERY", "GOOD", "BAD", "BEST", "WORST", "NEW", "OLD", "HIGH", "LOW",
    "BIG", "SMALL", "UP", "DOWN", "OUT", "OVER", "UNDER", "BOTH",
    "EACH", "FEW", "MANY", "MUCH", "OTHER", "SAME", "SUCH", "TOO", "WELL",
}

USERS_COLLECTION = "users"

# Simple in-memory caches (reset on app restart)
_PROFILE_CACHE: Dict[str, Dict[str, Any]] = {}
_SYMBOL_SEARCH_CACHE: Dict[str, Dict[str, Any]] = {}
_FIRESTORE_CLIENT = None

# Mock mode for local development
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"


@st.cache_resource
def get_firestore_client():
    """Lazy-load and cache Firestore client to speed up initial page load."""
    if MOCK_MODE:
        return None  # No Firestore client in mock mode
    from google.cloud import firestore
    return firestore.Client()


def get_stock_metrics_from_firestore(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve detailed stock metrics from Firestore including Piotroski F-score, 
    Altman Z-score, ROIC, CROIC, and financial statements.
    
    Args:
        ticker: Stock ticker symbol (e.g., 'AAPL')
    
    Returns:
        Dictionary containing derived metrics, financials, and data quality info,
        or None if not found
    """
    # Mock mode: return dummy metrics
    if MOCK_MODE:
        from app.mock_data import get_mock_stock_metrics
        return get_mock_stock_metrics(ticker)
    
    # Production mode: use Firestore
    try:
        db_fs = get_firestore_client()
        if not db_fs:
            return None
        ticker_upper = ticker.upper()
        doc_ref = db_fs.collection("stocks").document(ticker_upper)
        doc = doc_ref.get()
        
        if not doc.exists:
            return None
        
        data = doc.to_dict()
        
        # Extract key metrics
        derived_metrics = data.get("derived_metrics", {})
        financials = data.get("financials", {})
        analytics_quality = data.get("analytics_quality", {})
        profile = data.get("profile", {})
        
        # Get latest annual financials
        income_annual = financials.get("incomeStatement", {}).get("annual", [])
        balance_annual = financials.get("balanceSheet", {}).get("annual", [])
        
        latest_income = income_annual[0] if income_annual else {}
        latest_balance = balance_annual[0] if balance_annual else {}
        
        return {
            "ticker": ticker_upper,
            "profile": profile,
            "derived_metrics": {
                "piotroski_f_score": derived_metrics.get("piotroski_f"),
                "altman_z_score": derived_metrics.get("altman_z"),
                "roic": derived_metrics.get("roic"),
                "croic": derived_metrics.get("croic"),
                "invested_capital": derived_metrics.get("invested_capital"),
                "market_cap": derived_metrics.get("market_cap"),
            },
            "latest_financials": {
                "revenue": latest_income.get("totalRevenue"),
                "net_income": latest_income.get("netIncome"),
                "total_assets": latest_balance.get("totalAssets"),
                "total_liabilities": latest_balance.get("totalLiabilities"),
                "date": latest_income.get("date") or latest_balance.get("date"),
            },
            "data_quality": analytics_quality,
        }
    except Exception as e:
        logger.error(f"Error retrieving metrics for {ticker}: {e}")
        return None


def get_currency_symbol(currency_code: str) -> str:
    """Get currency symbol from currency code."""
    currency_symbols = {
        "USD": "$",
        "EUR": "€",
        "GBP": "£",
        "INR": "₹",
        "CAD": "$",
        "AUD": "$"
    }
    return currency_symbols.get(currency_code, "$")


def format_currency(value, currency_code: str = "USD", decimals: int = 2) -> str:
    """Format a value with the appropriate currency symbol."""
    if value is None:
        return "N/A"
    try:
        symbol = get_currency_symbol(currency_code)
        return f"{symbol}{float(value):,.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def format_metric_value(value: Any, metric_type: str = "default", currency_code: str = "USD") -> str:
    """
    Format metric values for display with appropriate formatting.
    
    Args:
        value: The metric value to format
        metric_type: Type of metric (default, percentage, currency, score)
        currency_code: Currency code for currency formatting (USD, EUR, GBP, etc.)
    
    Returns:
        Formatted string representation
    """
    if value is None:
        return "N/A"
    
    try:
        if metric_type == "percentage":
            return f"{float(value) * 100:.2f}%"
        elif metric_type == "currency":
            return format_currency(value, currency_code, decimals=0)
        elif metric_type == "score":
            return f"{float(value):.2f}"
        else:
            return f"{float(value):.4f}" if abs(float(value)) < 1 else f"{float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value)


def log_feedback(user_id: str, decision_id: str, helpful: bool, comment: str = None):
    """
    Append feedback to the decision doc.
    """
    from google.api_core.exceptions import GoogleAPIError
    try:
        db_fs = get_firestore_client()
        doc_ref = db_fs.collection("users").document(user_id).collection("decisions").document(decision_id)
        payload = {
            "feedback": {
                "helpful": bool(helpful),
                "comment": comment,
                "ts_ms": int(time.time() * 1000)
            }
        }
        doc_ref.set(payload, merge=True)
        return True
    except GoogleAPIError as e:
        print("log_feedback error:", e)
        return False


def generate_followup_question(intent: str, ticker: Optional[str] = None, action: Optional[str] = None, 
                                has_pfs: bool = False, proposal: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Generate a contextual follow-up question based on the user's intent and response context.
    This helps maintain conversation flow and engagement.
    
    Args:
        intent: The classified intent (ticker_analysis, ticker_comparison, portfolio_request, general)
        ticker: The primary ticker discussed (if any)
        action: The suggested action (BUY, SELL, HOLD)
        has_pfs: Whether the user has a financial profile set up
        proposal: The trade proposal dict (if any)
    
    Returns:
        Dict with 'question' (display text) and 'context' (structured data for handling affirmative response)
    """
    import random
    
    followup = ""
    context = {}
    
    if intent == "ticker_analysis" and ticker:
        if action == "BUY":
            options = [
                {"question": f"Would you like me to compare {ticker} with similar stocks in the same sector?", 
                 "action": "compare_peers", "ticker": ticker},
                {"question": f"Would you like to see how {ticker} fits into a diversified portfolio?", 
                 "action": "portfolio_fit", "ticker": ticker},
                {"question": f"Should I help you determine the right position size for {ticker} based on your profile?", 
                 "action": "position_size", "ticker": ticker},
                {"question": f"Would you like to explore the risks and potential downsides of investing in {ticker}?", 
                 "action": "risk_analysis", "ticker": ticker},
            ]
        elif action == "SELL":
            options = [
                {"question": f"Would you like suggestions for alternative investments to replace {ticker}?", 
                 "action": "find_alternatives", "ticker": ticker},
                {"question": f"Should I analyze when might be the optimal time to exit your {ticker} position?", 
                 "action": "exit_timing", "ticker": ticker},
                {"question": f"Would you like to see other stocks that might better align with your goals?", 
                 "action": "better_matches", "ticker": ticker},
            ]
        else:  # HOLD or other
            options = [
                {"question": f"Would you like me to set up alerts for key price levels or news about {ticker}?", 
                 "action": "setup_alerts", "ticker": ticker},
                {"question": f"Should I show you how {ticker} compares to its industry peers?", 
                 "action": "compare_peers", "ticker": ticker},
                {"question": f"Would you like to explore what conditions might change this recommendation?", 
                 "action": "scenario_analysis", "ticker": ticker},
            ]
        
        if not has_pfs:
            options.append({"question": "Would you like to set up your financial profile so I can give more personalized advice?", 
                          "action": "setup_profile", "ticker": ticker})
        
        selected = random.choice(options)
        followup = selected["question"]
        context = {"action": selected["action"], "ticker": selected.get("ticker"), "intent": "ticker_analysis"}
    
    elif intent == "ticker_comparison":
        options = [
            {"question": "Would you like me to suggest an allocation strategy between these stocks?", 
             "action": "allocation_strategy"},
            {"question": "Should I analyze which one fits better with your risk tolerance and time horizon?", 
             "action": "fit_analysis"},
            {"question": "Would you like to see how these compare to relevant ETFs in the same sectors?", 
             "action": "compare_etfs"},
            {"question": "Should I help you understand the key risk factors for each option?", 
             "action": "risk_factors"},
        ]
        selected = random.choice(options)
        followup = selected["question"]
        context = {"action": selected["action"], "ticker": ticker, "intent": "ticker_comparison"}
    
    elif intent == "portfolio_request":
        if not has_pfs:
            options = [
                {"question": "Would you like to set up your financial profile so I can personalize this portfolio further?", 
                 "action": "setup_profile"},
                {"question": "Should I show you how to adjust this portfolio based on different risk tolerance levels?", 
                 "action": "risk_adjustment"},
            ]
        else:
            options = [
                {"question": "Would you like me to suggest specific ETFs or stocks to implement this allocation?", 
                 "action": "suggest_instruments"},
                {"question": "Should I help you create a rebalancing schedule to maintain these targets?", 
                 "action": "rebalancing_schedule"},
                {"question": "Would you like to see how this portfolio has performed historically?", 
                 "action": "historical_performance"},
                {"question": "Should I analyze how this allocation aligns with your specific financial goals?", 
                 "action": "goal_alignment"},
            ]
        selected = random.choice(options)
        followup = selected["question"]
        context = {"action": selected["action"], "intent": "portfolio_request"}
    
    elif intent == "general":
        if not has_pfs:
            followup = "Would you like to set up your financial profile so I can provide personalized investment recommendations?"
            context = {"action": "setup_profile", "intent": "general"}
        else:
            options = [
                {"question": "Would you like me to analyze a specific stock or create a portfolio strategy for you?", 
                 "action": "analyze_or_strategy"},
                {"question": "Should I review your financial profile and suggest investment opportunities?", 
                 "action": "review_profile"},
                {"question": "Would you like to compare a few stocks to see which fits your goals best?", 
                 "action": "compare_stocks"},
            ]
            selected = random.choice(options)
            followup = selected["question"]
            context = {"action": selected["action"], "intent": "general"}
    
    # Add personalization hints if profile exists but is incomplete
    if has_pfs and proposal and proposal.get("action") != "Not Available":
        enhancement_options = [
            {"question": "Would you like me to explain the reasoning behind this recommendation in more detail?", 
             "action": "explain_reasoning"},
            {"question": "Should I show you what would happen if market conditions change?", 
             "action": "scenario_analysis"},
        ]
        if random.random() > 0.7:  # 30% chance to add enhancement question
            selected = random.choice(enhancement_options)
            followup = selected["question"]
            context = {"action": selected["action"], "ticker": ticker, "intent": intent}
    
    return {"question": followup, "context": context}


def orchestrate_query(user_text: str, user_id: str = None, prefer_llm: bool = False, debug: bool = False) -> dict:
    """
    Orchestrator with PFT (Personal Financial Twin) wiring:
      - loads twin (cached snapshot or builds if missing)
      - uses twin.stress_index -> volatility proxy for perfient_fit_score
      - uses twin.risk_capacity to cap proposal dollar size (max_single_dollars)
    """
    start = time.time()
    print('orchestrate_query START')
    trace = {"steps": [], "timings": {}}
    out = {
        "ok": False,
        "response_text": "",
        "proposal": None,
        "fit_output": None,
        "evidence": [],         # normalized evidence list
        "trace": trace,
        "error": None,
        "valuation_result": None,  # valuation engine results
    }

    # --- Handle single-word follow-up responses (e.g., "No", "Yes") ---
    last_followup_context = st.session_state.get("last_followup_context")
    user_text_stripped = user_text.strip().lower()
    non_ticker_responses = {"no", "yes", "none", "n/a", "ok", "okay", "cancel", "skip"}
    # If last_followup_context exists and user response is a single word and not a likely ticker
    if last_followup_context and user_text_stripped in non_ticker_responses:
        # Frame a new query based on the context/action
        action = last_followup_context.get("action")
        ticker = last_followup_context.get("ticker")
        intent = last_followup_context.get("intent")
        # You can expand this logic for more actions as needed
        if action == "compare_peers" and ticker:
            user_text = f"Compare {ticker} with its industry peers."
        elif action == "portfolio_fit" and ticker:
            user_text = f"Show how {ticker} fits into a diversified portfolio."
        elif action == "position_size" and ticker:
            user_text = f"Suggest position size for {ticker} based on my profile."
        elif action == "risk_analysis" and ticker:
            user_text = f"Show risks and downsides of investing in {ticker}."
        elif action == "find_alternatives" and ticker:
            user_text = f"Suggest alternatives to {ticker}."
        elif action == "exit_timing" and ticker:
            user_text = f"Analyze optimal exit timing for {ticker}."
        elif action == "better_matches" and ticker:
            user_text = f"Show stocks that better align with my goals than {ticker}."
        elif action == "setup_alerts" and ticker:
            user_text = f"Set up alerts for {ticker}."
        elif action == "compare_peers" and ticker:
            user_text = f"Compare {ticker} to its industry peers."
        elif action == "scenario_analysis" and ticker:
            user_text = f"Show scenarios that could change the recommendation for {ticker}."
        elif action == "setup_profile":
            user_text = "Help me set up my financial profile."
        elif action == "allocation_strategy":
            user_text = "Suggest an allocation strategy between these stocks."
        elif action == "fit_analysis":
            user_text = "Analyze which stock fits better with my risk tolerance and time horizon."
        elif action == "compare_etfs":
            user_text = "Compare these stocks to relevant ETFs in the same sectors."
        elif action == "risk_factors":
            user_text = "Show key risk factors for each stock option."
        elif action == "suggest_instruments":
            user_text = "Suggest specific ETFs or stocks to implement this allocation."
        elif action == "rebalancing_schedule":
            user_text = "Help me create a rebalancing schedule for my portfolio."
        elif action == "historical_performance":
            user_text = "Show how this portfolio has performed historically."
        elif action == "goal_alignment":
            user_text = "Analyze how this allocation aligns with my financial goals."
        elif action == "analyze_or_strategy":
            user_text = "Analyze a specific stock or create a portfolio strategy for me."
        elif action == "review_profile":
            user_text = "Review my financial profile and suggest investment opportunities."
        elif action == "compare_stocks":
            user_text = "Compare a few stocks to see which fits my goals best."
        elif action == "explain_reasoning" and ticker:
            user_text = f"Explain the reasoning behind the recommendation for {ticker}."
        # else: fallback to a generic clarification
        else:
            user_text = "Please clarify or provide more details."
        # Remove the last_followup_context so this doesn't loop
        st.session_state.last_followup_context = None
        # Continue with the new user_text

    try:
        # -----------------------
        # 0) Load Personal Financial Twin (PFT)
        # PFT Lite: Fast mode for real-time queries (uses latest snapshot)
        # PFT Full: Comprehensive mode for detailed analysis (uses history)
        # -----------------------
        t0 = time.time()
        twin = None
        pft_mode = 'lite'  # Default to lite for query responsiveness
        try:
            if user_id:
                pft_funcs = get_pft_functions()
                # Use smart loader: gets cached twin if fresh, rebuilds if needed
                twin = pft_funcs['get_or_build_twin'](user_id, mode=pft_mode, max_age_hours=24)
                trace["steps"].append({
                    "name": "load_twin", 
                    "present": bool(twin),
                    "mode": twin.mode if twin else None,
                    "metrics": {
                        "stress_index": twin.stress_index if twin else None,
                        "financial_health_score": twin.financial_health_score if twin else None,
                    } if twin else None
                })
        except Exception as e:
            trace["steps"].append({"name": "load_twin_error", "err": repr(e)})
            twin = None
        trace["timings"]["pft_load"] = time.time() - t0
        print('orchestrate: pft_load done')

        # -----------------------
        # 1) Build PFS fragment for transparency & AI context
        # -----------------------
        pfs_fragment = None
        latest_pfs = None
        
        # Check if personalization is paused
        pause_personalization = st.session_state.get("pause_personalization", False)
        
        if not pause_personalization:
            # Try to get PFS from twin first, fallback to direct PFS load
            if twin and hasattr(twin, 'latest_pfs') and twin.latest_pfs:
                latest_pfs = twin.latest_pfs
                trace["steps"].append({"name": "pfs_from_twin", "success": True})
            elif user_id:
                # Fallback: Load PFS directly if twin doesn't have it
                try:
                    pfs_funcs = get_pfs_functions()
                    latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
                    if latest_pfs:
                        trace["steps"].append({"name": "pfs_direct_load", "success": True})
                except Exception as e:
                    trace["steps"].append({"name": "pfs_direct_load_error", "err": repr(e)})
            
            # Build PFS fragment for AI context if we have PFS data
            if latest_pfs:
                try:
                    pfs_funcs = get_pfs_functions()
                    pfs_fragment = pfs_funcs['build_pfs_prompt_fragment'](latest_pfs)
                    trace["pfs_fragment"] = pfs_fragment
                    trace["steps"].append({"name": "pfs_fragment_built", "success": True, "length": len(pfs_fragment) if pfs_fragment else 0})
                except Exception as e:
                    trace["steps"].append({"name": "pfs_fragment_error", "err": repr(e)})
        else:
            trace["steps"].append({"name": "personalization_paused", "note": "User has paused personalization - generic advice only"})
        
        # -----------------------
        # 1b) Load portfolio context if available
        # -----------------------
        portfolio_context = None
        portfolio_summary = st.session_state.get("portfolio_summary")
        if portfolio_summary and not pause_personalization:
            try:
                # Build portfolio context fragment for AI
                holdings_list = portfolio_summary.get("holdings", [])
                total_value = portfolio_summary.get("total_value", 0)
                sector_alloc = portfolio_summary.get("sector_allocation", {})
                
                # Get user's currency
                user_currency = "USD"
                if latest_pfs and hasattr(latest_pfs, 'currency') and latest_pfs.currency:
                    user_currency = latest_pfs.currency
                
                portfolio_lines = [
                    "\n--- USER'S CURRENT PORTFOLIO ---",
                    f"Total Portfolio Value: {format_currency(total_value, user_currency)}",
                    "",
                    "Holdings:",
                ]
                for h in holdings_list[:15]:  # Limit to top 15
                    ticker = h.get("ticker", "")
                    qty = h.get("quantity", 0)
                    value = h.get("market_value", 0)
                    sector = h.get("sector", "Unknown")
                    weight = (value / total_value * 100) if total_value > 0 else 0
                    portfolio_lines.append(f"  • {ticker}: {qty} shares | {format_currency(value, user_currency)} ({weight:.1f}%) | {sector}")
                
                portfolio_lines.append("")
                portfolio_lines.append("Sector Allocation:")
                for sector, pct in sorted(sector_alloc.items(), key=lambda x: x[1], reverse=True):
                    portfolio_lines.append(f"  • {sector}: {pct:.1f}%")
                
                portfolio_lines.append("--- END PORTFOLIO ---\n")
                portfolio_context = "\n".join(portfolio_lines)
                trace["portfolio_context"] = portfolio_context
                trace["steps"].append({"name": "portfolio_context_loaded", "success": True})
            except Exception as e:
                trace["steps"].append({"name": "portfolio_context_error", "err": repr(e)})
        
        # -----------------------
        # 2) Intent parsing with conversation context
        # -----------------------
        t1 = time.time()
        parsed = None
        # Get conversation history for context
        conversation_history = st.session_state.get("history", [])
        try:
            parsed = process_user_input(user_text, conversation_history=conversation_history)
            trace["steps"].append({"name": "local_intent", "out": parsed})
        except Exception as e:
            parsed = None
            trace["steps"].append({"name": "local_intent_error", "err": repr(e)})
        trace["timings"]["intent_local"] = time.time() - t1
        print('orchestrate: intent parsing done')

        # Optionally call LLM-based parser if available and appropriate
        if (not parsed) or getattr(parsed, "follow_up", None) or prefer_llm:
            t1b = time.time()
            try:
                if "process_user_input_via_llm" in globals():
                    llm_parsed = process_user_input_via_llm(user_text)
                    if llm_parsed:
                        parsed = parsed or llm_parsed
                        trace["steps"].append({"name": "llm_intent", "out": llm_parsed})
            except Exception as e:
                trace["steps"].append({"name": "llm_intent_error", "err": repr(e)})
            trace["timings"]["intent_llm"] = time.time() - t1b

        if not parsed:
            parsed = type("P", (), {"intent":"general", "tickers": [], "primary_ticker": None, "follow_up": None, "can_handle": True})

        # Handle out-of-scope queries early (now with general LLM response)
        if not getattr(parsed, "can_handle", True):
            out_of_scope_msg = getattr(parsed, "out_of_scope_message", None)
            if out_of_scope_msg:
                out["ok"] = True
                out["response_text"] = out_of_scope_msg
                out["proposal"] = {"action": "Not Available", "confidence": 0.0}
                trace["steps"].append({"name": "out_of_scope_with_general_response", "handled": True})
                trace["timings"]["total"] = time.time() - start
                return out

        if getattr(parsed, "follow_up", None):
            out["ok"] = True
            out["response_text"] = parsed.follow_up
            trace["timings"]["total"] = time.time() - start
            return out
        # -------------------------
        # Short-circuit for portfolio requests: if intent requests a portfolio, generate portfolio suggestion and return early.
        # Uses parsed.intent produced by process_user_input or LLM parser.
        # -------------------------
        try:
            parsed_intent = None
            if parsed:
                if isinstance(parsed, dict):
                    parsed_intent = parsed.get("intent")
                else:
                    parsed_intent = getattr(parsed, "intent", None)
            else:
                parsed_intent = locals().get("intent")
        except Exception:
            parsed_intent = locals().get("intent")

        if parsed_intent == "portfolio_request":
            try:
                if 'generate_portfolio_suggestion' in globals() and callable(generate_portfolio_suggestion):
                    portfolio_suggestion = generate_portfolio_suggestion(user_text)
                    
                    # Handle case when no PFS exists
                    if portfolio_suggestion is None:
                        md_parts = []
                        md_parts.append("### Portfolio suggestion ###\n")
                        
                        # Check if user is logged in
                        user_id_check = st.session_state.get("current_user_id")
                        if not user_id_check:
                            md_parts.append("⚠️ **You need to load your profile first!**\n\n")
                            md_parts.append("📋 **Steps to get started:**\n")
                            md_parts.append("1. Go to the **Profile** page (in the sidebar)\n")
                            md_parts.append("2. Enter your email and click **Load profile**\n")
                            md_parts.append("3. Enter your financial information\n")
                            md_parts.append("4. Come back here and ask again!\n")
                        else:
                            md_parts.append("I'd love to help build a portfolio for you — but I don't see financial data for your account yet.\n\n")
                            md_parts.append("📊 **To get a personalized portfolio:**\n")
                            md_parts.append("1. Go to the **Profile** page (in the sidebar)\n")
                            md_parts.append("2. Enter your financial information (income, assets, liabilities, etc.)\n")
                            md_parts.append("3. Save your profile\n")
                            md_parts.append("4. Come back and ask again!\n")
                        
                        out["response_text"] = "\n".join(md_parts)
                        out["ok"] = True
                        trace["steps"].append({"step": "portfolio_no_pfs"})
                        return out
                else:
                    # Use centralized portfolio recommendation function
                    # Get twin data if available for more accurate recommendations
                    twin = None
                    health_score = None
                    wealth_stage = None
                    
                    try:
                        from app.pft import load_twin_snapshot
                        from app.scoring import calculate_financial_health_score, determine_wealth_stage
                        
                        if latest_pfs:
                            # Try to load twin
                            try:
                                twin = load_twin_snapshot(user_id)
                            except Exception:
                                pass
                            
                            # Calculate health score
                            try:
                                health_data = calculate_financial_health_score(latest_pfs)
                                health_score = health_data.get('total_score')
                            except Exception:
                                pass
                            
                            # Determine wealth stage
                            try:
                                wealth_data = determine_wealth_stage(latest_pfs)
                                wealth_stage = wealth_data.get('stage')
                            except Exception:
                                pass
                    except Exception:
                        pass
                    
                    # Get recommended allocation from centralized function
                    recommended_allocation = calculate_recommended_portfolio(
                        latest_pfs=latest_pfs,
                        twin=twin,
                        health_score=health_score,
                        wealth_stage=wealth_stage
                    )
                    
                    # Calculate portfolio value for dollar targets
                    pv = None
                    if latest_pfs:
                        try:
                            pv = (latest_pfs.investments or 0.0) + (latest_pfs.cash_and_equivalents or 0.0)
                        except Exception:
                            pv = None
                    if pv is None or pv == 0:
                        pv = 100000.0  # Default for illustration
                    
                    # Format allocation for Chat display
                    alloc = {}
                    for asset_class, percentage in recommended_allocation.items():
                        target_pct = percentage / 100.0  # Convert to decimal
                        dollar_target = round(target_pct * pv, 2)
                        alloc[asset_class] = {
                            "target_pct": target_pct,
                            "dollar_target": dollar_target,
                            "notes": f"Personalized based on your profile"
                        }
                    
                    # Get explanation from centralized function
                    explanation = get_allocation_explanation(
                        recommended_allocation,
                        latest_pfs,
                        wealth_stage=wealth_stage,
                        health_score=health_score
                    )
                    
                    portfolio_suggestion = {
                        "explain": explanation,
                        "allocation": alloc
                    }

                # Get user's currency
                user_currency = "USD"
                if latest_pfs and hasattr(latest_pfs, 'currency') and latest_pfs.currency:
                    user_currency = latest_pfs.currency

                md_parts = []
                md_parts.append("### Portfolio suggestion ###\n")
                if isinstance(portfolio_suggestion, dict) and portfolio_suggestion.get("explain"):
                    md_parts.append(portfolio_suggestion.get("explain") + "\n")
                if isinstance(portfolio_suggestion, dict) and portfolio_suggestion.get("allocation"):
                    md_parts.append("\n**Allocation**\n")
                    for k, v in portfolio_suggestion.get("allocation").items():
                        pct = v.get("target_pct", 0)
                        dollar = v.get("dollar_target", 0)
                        notes = v.get("notes", "")
                        md_parts.append(f"- {k}: {pct*100:.1f}% ({format_currency(dollar, user_currency, decimals=0)}) — {notes}\n")
                
                # Add follow-up question for portfolio requests
                try:
                    followup_data = generate_followup_question(
                        intent="portfolio_request",
                        has_pfs=bool(latest_pfs)
                    )
                    if followup_data and followup_data.get("question"):
                        # Store context for handling affirmative responses
                        st.session_state.last_followup_context = followup_data.get("context")
                        md_parts.append(f"\n\n---\n\n💡 **{followup_data['question']}**")
                except Exception:
                    pass
                
                out["response_text"] = "\n".join(md_parts)
                out["proposal"] = {
                    "type": "portfolio",
                    "risk_profile": "conservative",
                    "allocation": portfolio_suggestion.get("allocation", {}),
                    "explanation": portfolio_suggestion.get("explain"),
                }
                out["evidence"] = []
                out["ok"] = True
                trace["steps"].append({"step": "portfolio_short_circuit", "handled": True})
                trace["timings"]["portfolio_short_circuit"] = 0.0
                # Persist decision trace
                try:
                    decision_trace = {
                        "user_id": user_id,
                        "query": user_text,
                        "parsed": getattr(parsed, "__dict__", None) or parsed,
                        "comparison_results": results,
                        "response_text": md,
                        "trace": trace,
                    }
                    persist_fn = get_logging_function()
                    decision_id = persist_fn(user_id or "anonymous", decision_trace)
                    out["decision_id"] = decision_id
                    out["trace"]["decision_id"] = decision_id
                except Exception:
                    pass
                return out
            except Exception as pf_err:
                logger.exception("portfolio short-circuit failed: %s", pf_err)
                # continue normal flow

        # -------------------------
        # Portfolio Analysis Intent (analyze existing uploaded portfolio)
        # -------------------------
        if parsed_intent == "portfolio_analysis":
            try:
                # Check if generate_portfolio_analysis function exists
                if 'generate_portfolio_analysis' in globals() and callable(generate_portfolio_analysis):
                    analysis_result = generate_portfolio_analysis(user_text)
                    
                    if analysis_result:
                        # Portfolio exists and was analyzed
                        md_parts = []
                        md_parts.append("## 📊 Portfolio Analysis\n")
                        md_parts.append(analysis_result.get("analysis", ""))
                        
                        # Add metadata footer
                        portfolio_value = analysis_result.get("portfolio_value", 0)
                        num_holdings = analysis_result.get("num_holdings", 0)
                        # Get user's currency
                        user_currency = "USD"
                        if latest_pfs and hasattr(latest_pfs, 'currency') and latest_pfs.currency:
                            user_currency = latest_pfs.currency
                        md_parts.append(f"\n\n---\n\n📈 **Portfolio Summary**: {num_holdings} holdings | Total value: {format_currency(portfolio_value, user_currency)}")
                        
                        # Add follow-up question
                        try:
                            followup_data = generate_followup_question(
                                intent="portfolio_analysis",
                                has_pfs=bool(latest_pfs)
                            )
                            if followup_data and followup_data.get("question"):
                                st.session_state.last_followup_context = followup_data.get("context")
                                md_parts.append(f"\n\n💡 **{followup_data['question']}**")
                        except Exception:
                            pass
                        
                        out["response_text"] = "\n".join(md_parts)
                        out["ok"] = True
                        out["evidence"] = []
                        trace["steps"].append({"step": "portfolio_analysis_completed", "num_holdings": num_holdings})
                        return out
                    else:
                        # No portfolio loaded
                        md_parts = []
                        md_parts.append("## 📂 Portfolio Not Found\n")
                        md_parts.append("I'd love to analyze your portfolio, but I don't see one uploaded yet.\n\n")
                        md_parts.append("**To upload your portfolio:**\n")
                        md_parts.append("1. Go to the **Portfolio** page in the sidebar\n")
                        md_parts.append("2. Upload a CSV or Excel file with your holdings\n")
                        md_parts.append("3. Review and save your portfolio\n")
                        md_parts.append("4. Come back and ask me to analyze it!\n\n")
                        md_parts.append("💡 *Tip: You can download a sample template on the Portfolio page*")
                        
                        out["response_text"] = "\n".join(md_parts)
                        out["ok"] = True
                        trace["steps"].append({"step": "portfolio_analysis_no_portfolio"})
                        return out
                else:
                    # Function not available (shouldn't happen)
                    logger.warning("generate_portfolio_analysis function not found")
            except Exception as pa_err:
                logger.exception("portfolio analysis failed: %s", pa_err)
                # Continue to normal flow

        # -------------------------
        # Short-circuit for general queries that require PFS (financial health, wealth building pace, etc.)
        # -------------------------
        requires_pfs = False
        if parsed:
            if isinstance(parsed, dict):
                requires_pfs = parsed.get("requires_pfs", False)
            else:
                # Check extras dict for requires_pfs flag from LLM
                extras = getattr(parsed, "extras", {})
                requires_pfs = extras.get("requires_pfs", False) if isinstance(extras, dict) else False
        
        if parsed_intent == "general" and requires_pfs:
            try:
                # Generate PFS-aware response
                pfs_response = get_pfs_aware_response(user_text, user_id, conversation_history)
                
                # Add follow-up question
                try:
                    followup_data = generate_followup_question(
                        intent="general",
                        has_pfs=bool(latest_pfs)
                    )
                    if followup_data and followup_data.get("question"):
                        st.session_state.last_followup_context = followup_data.get("context")
                        pfs_response += f"\n\n---\n\n💡 **{followup_data['question']}**"
                except Exception:
                    pass
                
                out["ok"] = True
                out["response_text"] = pfs_response
                out["proposal"] = {"action": "Not Available", "confidence": 0.0}
                trace["steps"].append({"step": "pfs_general_query", "handled": True})
                trace["timings"]["pfs_general"] = time.time() - start
                trace["timings"]["total"] = time.time() - start
                return out
            except Exception as e:
                trace["steps"].append({"step": "pfs_general_error", "err": repr(e)})
                # Fall through to regular handling

        # -------------------------
        # Short-circuit for ticker comparison: if intent is ticker_comparison and we have 2+ tickers, run comparison flow
        # -------------------------
        if parsed_intent == "ticker_comparison" and parsed and getattr(parsed, "tickers", None) and len(parsed.tickers) >= 2:
            try:
                # Validate tickers first
                valid_tickers, invalid_tickers = validate_tickers(parsed.tickers)
                if len(valid_tickers) >= 2:
                    # Load PFS for comparison context
                    latest_pfs = None
                    if user_id:
                        try:
                            pfs_funcs = get_pfs_functions()
                            latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
                        except Exception:
                            pass

                    # Run analysis for each ticker using latest analyze_ticker
                    analysis_results = []
                    for t in valid_tickers[:3]:  # Limit to 3 tickers for performance
                        try:
                            result = analyze_ticker(t, country="US")
                        except Exception:
                            result = None
                        analysis_results.append({"ticker": t, **(result or {})})

                    # Build markdown table for comparison
                    headers = ["Ticker", "GIV", "DCF", "DDM", "MVM", "Perfient Intrinsic", "Current Price", "52w High", "52w Low"]
                    md = ""
                    if latest_pfs:
                        md += "🎯 **Personalized comparison** based on your financial profile\n\n"
                        horizon = latest_pfs.investment_horizon_years if hasattr(latest_pfs, 'investment_horizon_years') else 'N/A'
                        user_currency = latest_pfs.currency if hasattr(latest_pfs, 'currency') and latest_pfs.currency else "USD"
                        md += f"*Your profile: Net Worth {format_currency(getattr(latest_pfs, 'net_worth', 0), user_currency, decimals=0)} | Risk Tolerance: {getattr(latest_pfs, 'risk_tolerance', 'N/A')} | Horizon: {horizon}y*\n\n"
                    else:
                        md += "ℹ️ *General comparison* — [Create your profile](/Profile) for personalized fit scores\n\n"

                    md += "| " + " | ".join(headers) + " |\n"
                    md += "|" + "---|" * len(headers) + "\n"
                    for r in analysis_results:
                        md += f"| {r.get('ticker','')} | {r.get('GIV','N/A'):.2f} | {r.get('DCF','N/A'):.2f} | {r.get('DDM','N/A'):.2f} | {r.get('MVM','N/A'):.2f} | {r.get('perfientIntrinsic','N/A'):.2f} | {r.get('currentPrice','N/A'):.2f} | {r.get('52wHigh','N/A')} | {r.get('52wLow','N/A')} |\n"

                    # Highlight best fit (by perfientIntrinsic if available)
                    best = max(analysis_results, key=lambda r: r.get('perfientIntrinsic', 0) or 0)
                    md += f"\n### 🏆 Best fit for your profile: **{best.get('ticker','')}** (Perfient Intrinsic: {best.get('perfientIntrinsic','N/A'):.2f})\n"

                    # Add follow-up question for comparison
                    try:
                        followup_data = generate_followup_question(
                            intent="ticker_comparison",
                            ticker=best.get('ticker',''),
                            has_pfs=bool(latest_pfs)
                        )
                        if followup_data and followup_data.get("question"):
                            st.session_state.last_followup_context = followup_data.get("context")
                            md += f"\n\n---\n\n💡 **{followup_data['question']}**"
                    except Exception:
                        pass

                    out["response_text"] = md
                    out["proposal"] = {"action": "Compare", "confidence": 0.0}
                    out["evidence"] = []
                    out["ok"] = True
                    trace["steps"].append({"step": "ticker_comparison_short_circuit", "tickers": valid_tickers, "results": analysis_results})
                    trace["timings"]["ticker_comparison"] = time.time() - start
                    # Persist decision trace
                    try:
                        decision_trace = {
                            "user_id": user_id,
                            "query": user_text,
                            "parsed": getattr(parsed, "__dict__", None) or parsed,
                            "comparison_results": analysis_results,
                            "response_text": md,
                            "trace": trace,
                        }
                        persist_fn = get_logging_function()
                        decision_id = persist_fn(user_id or "anonymous", decision_trace)
                        out["decision_id"] = decision_id
                        out["trace"]["decision_id"] = decision_id
                    except Exception:
                        pass
                    return out
                else:
                    trace["steps"].append({"step": "ticker_comparison_insufficient_valid", "valid": len(valid_tickers)})
            except Exception as comp_err:
                trace["steps"].append({"step": "ticker_comparison_error", "err": repr(comp_err)})
                # continue normal flow on error

        # -----------------------
        # 2) Memory agent: PFS already loaded in section 1
        # -----------------------
        t2 = time.time()
        # Note: latest_pfs and pfs_fragment are already loaded in section 1 above
        # This ensures consistent PFS context throughout the query processing
        trace["timings"]["memory"] = time.time() - t2

        # -----------------------
        # 3) Retriever: local RAG passages + enhanced RAG documents
        # -----------------------
        t3 = time.time()
        raw_passages = []
        rag_documents = []  # New: RAG research documents
        primary_ticker = None
        if getattr(parsed, "tickers", None):
            try:
                primary_ticker = parsed.tickers[0].upper() if len(parsed.tickers) > 0 else None
                if primary_ticker:
                    # retrieve raw hits from vector store (existing function)
                    try:
                        vec_funcs = get_vector_functions()
                        rag_funcs = get_rag_functions()
                        raw_passages = vec_funcs['retrieve'](primary_ticker, k=20) or []
                        normalized_passages = rag_funcs['normalize_passages'](
                            raw_passages,
                            query=primary_ticker,
                            ticker=primary_ticker,
                            k=6
                        )
                    except Exception as e:
                        trace["steps"].append({"name": "normalize_passages_error", "err": repr(e)})
                        normalized_passages = []
                    trace["steps"].append({"name": "retrieve_passages", "count_raw": len(raw_passages), "count_normalized": len(normalized_passages)})
                    
                    # NEW: Retrieve enhanced RAG documents (SEC, news, analyst, industry)
                    # Note: Will fetch industry context later after profile is loaded
                    try:
                        rag_retrieval_funcs = get_rag_retrieval_functions()
                        if rag_retrieval_funcs and 'RAGDocumentStore' in rag_retrieval_funcs:
                            rag_store = rag_retrieval_funcs['RAGDocumentStore']()
                            
                            # Retrieve multiple document types
                            rag_documents = rag_store.retrieve_by_ticker(
                                ticker=primary_ticker,
                                k=10,  # Get top 10 research documents
                                document_types=["sec_filing", "news_summary", "analyst_report"]  # Exclude industry for now
                            )
                            
                            trace["steps"].append({
                                "name": "retrieve_rag_documents",
                                "count": len(rag_documents),
                                "types": [d.get("meta", {}).get("document_type") for d in rag_documents]
                            })
                        else:
                            trace["steps"].append({"name": "rag_documents_unavailable"})
                    except Exception as e:
                        trace["steps"].append({"name": "retrieve_rag_documents_error", "err": repr(e)})
                else:
                    normalized_passages = []
            except Exception as e:
                trace["steps"].append({"name": "retrieve_error", "err": repr(e)})
                normalized_passages = []
        else:
            normalized_passages = []
        trace["timings"]["retrieve"] = time.time() - t3
        print('orchestrate: retrieve done')

        # Save normalized evidence into out early so other steps can use them for diagnostics / persistence
        out["evidence"] = normalized_passages

        # -----------------------
        # 4) Data Agent: fetch profile (price from valuation engine via Tiingo)
        # -----------------------
        t4 = time.time()
        prof = None
        price = None
        try:
            if primary_ticker:
                prof = get_profile_cached(primary_ticker)
            trace["steps"].append({"name": "market_data", "out": {"profile_present": bool(prof)}})
        except Exception as e:
            trace["steps"].append({"name": "market_data_error", "err": repr(e)})
        trace["timings"]["market_data"] = time.time() - t4
        
        # -----------------------
        # 4a) Enhance RAG documents with industry context (now that profile is loaded)
        # -----------------------
        if rag_documents and prof and prof.get("sector"):
            try:
                rag_retrieval_funcs = get_rag_retrieval_functions()
                if rag_retrieval_funcs and 'RAGDocumentStore' in rag_retrieval_funcs:
                    rag_store = rag_retrieval_funcs['RAGDocumentStore']()
                    sector = prof.get("sector", "")
                    industry_docs = rag_store.retrieve_industry_context(sector, k=2)
                    if industry_docs:
                        rag_documents.extend(industry_docs)
                        trace["steps"].append({
                            "name": "retrieve_industry_context",
                            "sector": sector,
                            "count": len(industry_docs)
                        })
            except Exception as e:
                trace["steps"].append({"name": "retrieve_industry_error", "err": repr(e)})

        # -----------------------
        # 4b) Valuation Engine: calculate intrinsic values
        # -----------------------
        t4b = time.time()
        valuation_result = None
        
        if not VALUATION_AVAILABLE or analyze_ticker is None:
            trace["steps"].append({"name": "valuation_unavailable"})
            out["valuation_result"] = None
        elif primary_ticker:
            try:
                # Ensure TIINGO_API_KEY is set
                if not os.getenv("TIINGO_API_KEY"):
                    os.environ["TIINGO_API_KEY"] = "12a4b6199b51d43953b990b9ec734b451e05d8e1"

                # --- Instrument Type Detection ---
                utils_funcs = get_utils_functions()

                detected = {"type": "UNKNOWN", "source": "none"}
                try:
                    detected = utils_funcs.get('detect_ticker_type')(primary_ticker) or detected
                except Exception:
                    try:
                        # Fallback to Tiingo search if detect_ticker_type not available
                        ti = utils_funcs.get('fetch_tiingo_search')(primary_ticker)
                        if ti and ti.get('is_etf'):
                            detected = {"type": "ETF", "source": "tiingo"}
                    except Exception:
                        pass

                is_etf = (detected.get("type") == "ETF")
                # Record how we detected it for debugging
                trace["steps"].append({"name": "instrument_detection", "ticker": primary_ticker, "detected": detected})

                if is_etf:
                    # Prefer analyze_etf for ETFs, but fallback if unavailable
                    if VALUATION_AVAILABLE and analyze_etf is not None:
                        try:
                            valuation_result = analyze_etf(primary_ticker, country="US")
                            trace["steps"].append({"name": "etf_analysis", "success": True, "ticker": primary_ticker})
                        except Exception as e:
                            trace["steps"].append({"name": "etf_analysis_error", "err": repr(e)})
                            valuation_result = None
                    else:
                        trace["steps"].append({"name": "etf_analysis_unavailable", "ticker": primary_ticker})
                        # Fallback to analyze_ticker if available
                        if VALUATION_AVAILABLE and analyze_ticker is not None:
                            try:
                                valuation_result = analyze_ticker(primary_ticker, country="US")
                                trace["steps"].append({"name": "fallback_to_stock_analysis", "ticker": primary_ticker})
                            except Exception as e:
                                trace["steps"].append({"name": "fallback_stock_error", "err": repr(e)})
                                valuation_result = None
                        else:
                            valuation_result = None

                    # Format ETF output for UI when ETF analyzer returned structured info
                    if valuation_result and isinstance(valuation_result, dict) and not valuation_result.get('error') and valuation_result.get('assetType', '').lower() == 'etf' or (valuation_result and isinstance(valuation_result, dict) and valuation_result.get('performanceAndFees')):
                        etf_info = valuation_result
                        perf = etf_info.get('performanceAndFees', {})
                        etf_summary = f"ETF: {etf_info.get('name', primary_ticker)}\n"
                        etf_summary += f"Description: {etf_info.get('description', '')}\n" if etf_info.get('description') else ''
                        etf_summary += f"Share Class: {etf_info.get('shareClass', '')}\n" if etf_info.get('shareClass') else ''
                        etf_summary += f"Net Expense Ratio: {etf_info.get('netExpense', 'N/A')}\n"
                        if perf:
                            etf_summary += "--- Performance & Fees ---\n"
                            for k, v in perf.items():
                                if v is not None:
                                    etf_summary += f"{k}: {v}\n"
                        if etf_info.get('otherShareClasses'):
                            etf_summary += f"Other Share Classes: {etf_info['otherShareClasses']}\n"
                        out["valuation_result"] = {"summary": etf_summary, **etf_info}
                    else:
                        out["valuation_result"] = valuation_result
                else:
                    # Non-ETF path: use analyze_ticker
                    try:
                        valuation_result = analyze_ticker(primary_ticker, country="US")
                        trace["steps"].append({"name": "valuation_analysis", "success": True, "ticker": primary_ticker})
                    except Exception as e:
                        trace["steps"].append({"name": "valuation_error", "err": repr(e)})
                        valuation_result = None
                    out["valuation_result"] = valuation_result
                    # Get price directly from valuation engine (Tiingo API)
                    if valuation_result and valuation_result.get('currentPrice'):
                        price = valuation_result.get('currentPrice')
                        trace["steps"].append({"name": "price_from_tiingo", "price": price, "source": "valuation_engine"})

                # For debugging: record is_etf flag
                trace["steps"].append({"name": "is_etf_flag", "ticker": primary_ticker, "is_etf": is_etf})
            except Exception as val_err:
                trace["steps"].append({"name": "valuation_error", "err": str(val_err)})
                valuation_result = None
                out["valuation_result"] = None
        else:
            out["valuation_result"] = None
        
        trace["timings"]["valuation_analysis"] = time.time() - t4b
        print('orchestrate: valuation done')

        # -----------------------
        # 5) Reasoner (LLM RAG summary) - ALWAYS with PFS context (USP of product)
        # -----------------------
        t5 = time.time()
        summary_text = None
        rag_context = None  # New: Structured RAG context
        try:
            rag_funcs = get_rag_functions()
            
            # CRITICAL: Always use PFS-aware summarization - this is our USP
            # If no PFS exists, prompt user to create one for personalized recommendations
            if not pfs_fragment and latest_pfs:
                # Build PFS fragment on the fly if missing
                pfs_funcs = get_pfs_functions()
                pfs_fragment = pfs_funcs['build_pfs_prompt_fragment'](latest_pfs)
            
            # NEW: Build RAG context from retrieved research documents
            if rag_documents:
                rag_context_parts = []
                rag_context_parts.append("\n--- RECENT RESEARCH INSIGHTS ---")
                
                for doc in rag_documents[:8]:  # Limit to top 8 documents
                    meta = doc.get("meta", {})
                    doc_type = meta.get("document_type", "unknown")
                    source = meta.get("source", "unknown")
                    summary_preview = meta.get("summary_preview", "")
                    ingestion_date = meta.get("ingestion_date", "")[:10]
                    
                    if doc_type == "sec_filing":
                        try:
                            full_meta = meta.get("full_metadata", {})
                            filing_type = full_meta.get("filing_type", "Unknown")
                            rag_context_parts.append(f"\n[SEC Filing: {filing_type} - {ingestion_date}]")
                            rag_context_parts.append(summary_preview)
                        except:
                            pass
                    
                    elif doc_type == "news_summary":
                        try:
                            full_meta = meta.get("full_metadata", {})
                            sentiment = full_meta.get("sentiment", {}).get("overall", "neutral")
                            rag_context_parts.append(f"\n[News Summary - {ingestion_date} | Sentiment: {sentiment}]")
                            rag_context_parts.append(summary_preview)
                        except:
                            pass
                    
                    elif doc_type == "analyst_report":
                        try:
                            full_meta = meta.get("full_metadata", {})
                            rating = full_meta.get("rating", "N/A")
                            rag_context_parts.append(f"\n[Analyst Report - {ingestion_date} | Rating: {rating}]")
                            rag_context_parts.append(summary_preview)
                        except:
                            pass
                    
                    elif doc_type == "industry_analysis":
                        try:
                            full_meta = meta.get("full_metadata", {})
                            industry = full_meta.get("industry", "N/A")
                            rag_context_parts.append(f"\n[Industry Analysis: {industry}]")
                            rag_context_parts.append(summary_preview[:300])  # Shorter for industry
                        except:
                            pass
                
                rag_context_parts.append("\n--- END RESEARCH INSIGHTS ---\n")
                rag_context = "\n".join(rag_context_parts)
                trace["steps"].append({"name": "rag_context_built", "length": len(rag_context)})
            
            # Combine normalized passages with RAG context for enriched analysis
            enriched_passages = normalized_passages.copy() if normalized_passages else []
            if rag_context:
                # Add RAG context as a special passage at the beginning
                enriched_passages.insert(0, {
                    "passage_text": rag_context,
                    "source": "RAG_Research_Documents",
                    "ticker": primary_ticker,
                    "snippet": rag_context[:500]
                })
            
            if pfs_fragment:
                # Primary path: Use PFS-personalized analysis (our USP)
                summary_text = rag_funcs['summarize_with_evidence_and_pfs'](primary_ticker or "GENERAL", enriched_passages, pfs_fragment)
                trace["steps"].append({"name": "reasoner_with_pfs_and_rag", "out_summary_len": len(summary_text) if isinstance(summary_text, str) else None})
            else:
                # No PFS available - still analyze but encourage profile creation
                summary_text = rag_funcs['summarize_with_evidence_and_pfs'](primary_ticker or "GENERAL", enriched_passages, None)
                pfs_reminder = "\n\n💡 **Tip:** Create your financial profile to get personalized recommendations based on your net worth, savings rate, risk tolerance, and goals!"
                if isinstance(summary_text, str):
                    summary_text += pfs_reminder
                trace["steps"].append({"name": "reasoner_no_pfs_with_rag", "out_summary_len": len(summary_text) if isinstance(summary_text, str) else None})
        except Exception as e:
            summary_text = "Sorry — I couldn't produce a summary at the moment."
            trace["steps"].append({"name": "reasoner_error", "err": repr(e)})
        trace["timings"]["reasoner"] = time.time() - t5
        print('orchestrate: reasoner done')

        # -----------------------
        # 6) Scoring Agent (perfient_fit_score wiring with twin)
        # -----------------------
        t6 = time.time()
        fit_out = None
        try:
            # Use twin.stress_index as a proxy for volatility (map 0..1 -> 0..0.5 annual vol)
            volatility_proxy = None
            if twin and getattr(twin, "stress_index", None) is not None:
                # map stress_index(0..1) -> volatility (0..0.5)
                volatility_proxy = float(twin.stress_index) * 0.5

            # Extract perfient_intrinsic from valuation_result
            perfient_intrinsic_value = None
            if valuation_result and isinstance(valuation_result, dict):
                perfient_intrinsic_value = valuation_result.get('perfientIntrinsic')

            # Lazy-load scoring functions
            scoring_funcs = get_scoring_functions()
            perfient_fit_score_fn = scoring_funcs.get('perfient_fit_score')
            fit_score_fn = scoring_funcs.get('fit_score')

            # call richer scorer if available
            if perfient_fit_score_fn is not None:
                fit_out = perfient_fit_score_fn(
                    profile_obj = latest_pfs,
                    ticker = primary_ticker,
                    ticker_profile = prof,
                    price = price,
                    recent_returns = {},  # if you compute recent returns earlier, pass them
                    volatility = volatility_proxy,
                    sector_exposure = None,
                    perfient_intrinsic = perfient_intrinsic_value,
                )
                fit_scalar = fit_out.get("fit", 0.0)
                trace["steps"].append({"name": "scoring_perfient", "fit": fit_scalar, "has_explain": bool(fit_out.get("explain"))})
            elif fit_score_fn is not None:
                score_fn = get_scoring_function()
                fit_scalar = fit_score_fn(latest_pfs, primary_ticker, ticker_score=(score_fn(prof or {}, {}, 0.0)), price=price)
                fit_out = {"fit": fit_scalar, "explain": "Using simple fit_score (legacy)", "components": {}}
                trace["steps"].append({"name": "scoring_legacy", "fit": fit_scalar})
            else:
                fit_scalar = 0.0
                fit_out = {"fit": fit_scalar, "explain": "Scoring functions not available - check imports", "components": {}}
                trace["steps"].append({"name": "scoring_unavailable"})

        except Exception as e:
            fit_out = {"fit": 0.0, "explain": f"Scoring error: {str(e)}"}
            trace["steps"].append({"name": "scoring_error", "err": repr(e)})
        trace["timings"]["scoring"] = time.time() - t6

        # -----------------------
        # 7) Trade Proposer -> propose_trade_advanced + twin-based cap enforcement
        # -----------------------
        t7 = time.time()
        proposal = None
        try:
            portfolio_value = None
            if latest_pfs:
                portfolio_value = (latest_pfs.investments or 0.0) + (latest_pfs.cash_and_equivalents or 0.0)
            if portfolio_value is None:
                portfolio_value = 10000  # fallback

            trade_funcs = get_trade_functions()
            if 'propose_trade_advanced' in trade_funcs and callable(trade_funcs['propose_trade_advanced']):
                proposal = trade_funcs['propose_trade_advanced'](
                    ticker = primary_ticker,
                    fit_score = (fit_out.get("fit") if fit_out else 0.0),
                    price = price,
                    portfolio_value = portfolio_value,
                    pfs = latest_pfs,
                    profile = prof,
                    twin = twin,
                )
            else:
                # Advanced proposer unavailable - do not fallback to deprecated simple proposer
                trace["steps"].append({"name": "trade_proposal_unavailable", "note": "propose_trade_advanced not found"})
                proposal = None

            # APPLY TWIN RISK CAP: if twin.risk_capacity.max_single_dollars exists, cap proposal dollar allocation
            try:
                if twin and twin.risk_capacity and proposal and proposal.get("dollar", 0):
                    max_single = twin.risk_capacity.get("max_single_dollars")
                    if max_single is not None and proposal.get("dollar", 0.0) > max_single:
                        # adjust qty priced to max_single (integer shares)
                        if price and price > 0:
                            allowed_qty = int(max_single // price)
                            allowed_qty = max(1, allowed_qty) if allowed_qty > 0 else 0
                        else:
                            allowed_qty = 0
                        old_dollar = proposal.get("dollar", 0.0)
                        # Get user's currency
                        user_currency = "USD"
                        if latest_pfs and hasattr(latest_pfs, 'currency') and latest_pfs.currency:
                            user_currency = latest_pfs.currency
                        proposal["explain"] = (proposal.get("explain","") 
                                               + f" NOTE: adjusted to comply with your risk capacity (max {format_currency(max_single, user_currency, decimals=0)}) — reduced allocation from {format_currency(old_dollar, user_currency, decimals=0)} to {format_currency(allowed_qty*price if price else 0, user_currency, decimals=0)}.")
                        proposal["dollar"] = allowed_qty * price if price else 0.0
                        proposal["qty"] = allowed_qty
                        proposal["adjusted_for_twin_cap"] = True
                        trace["steps"].append({"name": "twin_cap_applied", "max_single": max_single, "old_dollar": old_dollar, "new_dollar": proposal["dollar"]})
            except Exception as e:
                trace["steps"].append({"name": "twin_cap_error", "err": repr(e)})

            trace["steps"].append({"name": "trade_proposal", "out": proposal})
        except Exception as e:
            # Set default when proposer throws an error
            proposal = {
                "action": "Not Available",
                "confidence": 0.0,
                "qty": None,
                "dollar": 0.0,
                "explain": "Proposal generation failed due to an internal error."
            }
            trace["steps"].append({"name": "trade_proposal_error", "err": repr(e)})

        # Ensure we always have a normalized proposal dict (if no proposer produced one)
        if proposal is None:
            proposal = {
                "action": "Not Available",
                "confidence": 0.0,
                "qty": None,
                "dollar": 0.0,
                "explain": "No recommendation available."
            }

        # Optional: normalize common fields from different proposer shapes
        # e.g., some proposers return 'explain' vs 'rationale'; normalize to use 'rationale' in UI
        if isinstance(proposal, dict):
            if "rationale" not in proposal:
                proposal["rationale"] = proposal.get("explain") or proposal.get("reason") or ""
            # ensure confidence is numeric and in 0..1
            try:
                proposal["confidence"] = float(proposal.get("confidence", 0.0)) if proposal.get("confidence") is not None else 0.0
            except Exception:
                proposal["confidence"] = 0.0

        trace["timings"]["trade_proposal"] = time.time() - t7

        # -----------------------
        # 8) Compose final response text - Always highlight PFS personalization (USP)
        # -----------------------
        t8 = time.time()
        try:
            md_lines = []
            
            # ALWAYS show personalization status at the top (our USP)
            if latest_pfs:
                md_lines.append("🎯 **Personalized for you** based on your financial profile\n")
            else:
                md_lines.append("ℹ️ *General analysis* — [Create your profile](/Profile) for personalized recommendations\n")
            md_lines.append("\n")
            
            if summary_text:
                md_lines.append("**Analysis**\n")
                md_lines.append(summary_text)
                md_lines.append("\n")
            
            # NEW: Display RAG research sources if available
            if rag_documents:
                md_lines.append("\n**📚 Research Sources**\n")
                
                # Group by document type
                sec_docs = [d for d in rag_documents if d.get("meta", {}).get("document_type") == "sec_filing"]
                news_docs = [d for d in rag_documents if d.get("meta", {}).get("document_type") == "news_summary"]
                analyst_docs = [d for d in rag_documents if d.get("meta", {}).get("document_type") == "analyst_report"]
                industry_docs = [d for d in rag_documents if d.get("meta", {}).get("document_type") == "industry_analysis"]
                
                if sec_docs:
                    md_lines.append(f"- **SEC Filings**: {len(sec_docs)} recent filing(s) analyzed\n")
                if news_docs:
                    md_lines.append(f"- **News Analysis**: {len(news_docs)} news summary report(s)\n")
                if analyst_docs:
                    md_lines.append(f"- **Analyst Reports**: {len(analyst_docs)} AI-generated report(s)\n")
                if industry_docs:
                    md_lines.append(f"- **Industry Context**: {len(industry_docs)} sector analysis document(s)\n")
                
                md_lines.append("\n*Analysis enriched with preprocessed research insights from multiple sources*\n\n")

            # Add valuation analysis results
            display_valuation = out.get("valuation_result")
            
            if display_valuation and isinstance(display_valuation, dict):
                try:
                    valuation_text = format_valuation_response(display_valuation, proposal)
                    if valuation_text:
                        md_lines.append("---\n\n")  # Add separator
                        md_lines.append(valuation_text)
                        md_lines.append("\n")
                        trace["steps"].append({"name": "valuation_displayed", "success": True})
                except Exception as e:
                    trace["steps"].append({"name": "valuation_display_error", "err": repr(e)})
                    md_lines.append("⚠️ *Valuation analysis temporarily unavailable*\n\n")
            
            # # Add supplementary Firestore metrics (Piotroski, Altman, ROIC, CROIC) only if valuation didn't show them
            # if primary_ticker:
            #     try:
            #         metrics_data = get_stock_metrics_from_firestore(primary_ticker)
            #         if metrics_data and metrics_data.get("derived_metrics"):
            #             dm = metrics_data["derived_metrics"]
            #             
            #             # Only show if we have at least one valid metric
            #             has_metrics = any([
            #                 dm.get("piotroski_f_score") is not None,
            #                 dm.get("altman_z_score") is not None,
            #                 dm.get("roic") is not None,
            #                 dm.get("croic") is not None
            #             ])
            #             
            #             if has_metrics:
            #                 md_lines.append("**📊 Additional Financial Health Metrics**\n")
            #                 
            #                 if dm.get("piotroski_f_score") is not None:
            #                     score = dm["piotroski_f_score"]
            #                     interpretation = "Strong" if score >= 7 else "Moderate" if score >= 5 else "Weak"
            #                     md_lines.append(f"- **Piotroski F-Score:** {score}/9 ({interpretation} financial strength)\n")
            #                 
            #                 if dm.get("altman_z_score") is not None:
            #                     z_score = dm["altman_z_score"]
            #                     interpretation = "Safe Zone" if z_score > 2.99 else "Grey Zone" if z_score > 1.81 else "Distress Zone"
            #                     md_lines.append(f"- **Altman Z-Score:** {format_metric_value(z_score, 'score')} ({interpretation})\n")
            #                 
            #                 if dm.get("roic") is not None:
            #                     md_lines.append(f"- **ROIC (Return on Invested Capital):** {format_metric_value(dm['roic'], 'percentage')}\n")
            #                 
            #                 if dm.get("croic") is not None:
            #                     md_lines.append(f"- **CROIC (Cash Return on Invested Capital):** {format_metric_value(dm['croic'], 'percentage')}\n")
            #                 
            #                 if dm.get("market_cap") is not None:
            #                     md_lines.append(f"- **Market Cap:** {format_metric_value(dm['market_cap'], 'currency')}\n")
            #                 
            #                 md_lines.append("\n")
            #                 
            #                 # Add latest financials summary
            #                 latest_fin = metrics_data.get("latest_financials", {})
            #                 if latest_fin.get("revenue") or latest_fin.get("net_income"):
            #                     md_lines.append("**Latest Financials**\n")
            #                     if latest_fin.get("date"):
            #                         md_lines.append(f"*As of {latest_fin['date'][:10]}*\n")
            #                     if latest_fin.get("revenue"):
            #                         md_lines.append(f"- Revenue: {format_metric_value(latest_fin['revenue'], 'currency')}\n")
            #                     if latest_fin.get("net_income"):
            #                         md_lines.append(f"- Net Income: {format_metric_value(latest_fin['net_income'], 'currency')}\n")
            #                     if latest_fin.get("total_assets"):
            #                         md_lines.append(f"- Total Assets: {format_metric_value(latest_fin['total_assets'], 'currency')}\n")
            #                     md_lines.append("\n")
            #     except Exception as e:
            #         # Silently fail - don't break the response if metrics retrieval fails
            #         trace["steps"].append({"name": "metrics_display_error", "err": repr(e)})

            
            if fit_out:
                fit_val = fit_out.get("fit", 0.0)
                md_lines.append(f"**Perfient Fit Score (tells how well the stock fits your profile):** **{fit_val:.2f}**\n")
                if fit_out.get("explain"):
                    md_lines.append(f"*Why:* {fit_out.get('explain')}\n")

            # Proposal block (unchanged)
            if proposal:
                action = proposal.get("action", "-")
                confidence = proposal.get("confidence", 0.0)
                qty = proposal.get("qty", "")
                rationale = proposal.get("rationale", "")  # Use normalized field instead of 'explain'
                md_lines.append(f"\n---\n**Suggested action:** **{action}**  \nConfidence score (“Confidence level of Perfient copilot about the correctness of the answer”): {confidence*100:.0f}%\n")
                md_lines.append(f"- Qty: {qty}\n- Rationale: {rationale}\n")

            # # Evidence block: Filter out stale evidence with too many "None" values and reconstruct from Firestore
            # if normalized_passages:
            #     # Filter and enrich evidence
            #     valid_evidence = []
            #     for e in (normalized_passages or [])[:4]:
            #         text = e.get("snippet") or e.get("passage_text") or ""
            #         
            #         # Count "None" occurrences - if too many, this is stale data
            #         none_count = text.count(": None")
            #         total_fields = text.count("===") + text.count(":")
            #         
            #         # Skip if more than 50% of fields are None
            #         if total_fields > 0 and none_count / total_fields > 0.5:
            #             # Try to reconstruct from fresh Firestore data
            #             doc_id = e.get("doc_id") or e.get("source") or ""
            #             if ":" in doc_id:
            #                 ticker_from_doc = doc_id.split(":")[1].split("_")[0]
            #                 try:
            #                     fresh_metrics = get_stock_metrics_from_firestore(ticker_from_doc)
            #                     if fresh_metrics:
            #                         # Rebuild evidence text from fresh data
            #                         dm = fresh_metrics["derived_metrics"]
            #                         lf = fresh_metrics["latest_financials"]
            #                         
            #                         fresh_text = f"Ticker: {ticker_from_doc}\n"
            #                         fresh_text += f"=== Financials (Latest Annual) ===\n"
            #                         fresh_text += f"Revenue: {format_metric_value(lf.get('revenue'), 'currency') if lf.get('revenue') else 'N/A'}\n"
            #                         fresh_text += f"Net Income: {format_metric_value(lf.get('net_income'), 'currency') if lf.get('net_income') else 'N/A'}\n"
            #                         fresh_text += f"Total Assets: {format_metric_value(lf.get('total_assets'), 'currency') if lf.get('total_assets') else 'N/A'}\n"
            #                         fresh_text += f"=== Derived Metrics ===\n"
            #                         fresh_text += f"ROIC: {format_metric_value(dm.get('roic'), 'percentage') if dm.get('roic') else 'N/A'}\n"
            #                         fresh_text += f"CROIC: {format_metric_value(dm.get('croic'), 'percentage') if dm.get('croic') else 'N/A'}\n"
            #                         fresh_text += f"Piotroski F-Score: {dm.get('piotroski_f_score') if dm.get('piotroski_f_score') is not None else 'N/A'}\n"
            #                         fresh_text += f"Altman Z-Score: {format_metric_value(dm.get('altman_z_score'), 'score') if dm.get('altman_z_score') else 'N/A'}\n"
            #                         
            #                         # Use fresh data
            #                         e['snippet'] = fresh_text[:300]
            #                         e['passage_text'] = fresh_text
            #                         valid_evidence.append(e)
            #                         continue
            #                 except Exception as ex:
            #                     trace["steps"].append({"name": "evidence_reconstruct_error", "err": repr(ex)})
            #             # If reconstruction failed, skip this evidence
            #             continue
            #         
            #         # Evidence is good, keep it
            #         valid_evidence.append(e)
            #     
            #     # Display valid evidence
            #     if valid_evidence:
            #         md_lines.append("\n---\n**Evidence**\n")
            #         for e in valid_evidence:
            #             src = e.get("source") or e.get("doc_id") or e.get("source_url") or ""
            #             pid = e.get("passage_id") or ""
            #             snippet = e.get("snippet") or (e.get("passage_text") or "")[:300]
            #             score_pct = (int((e.get("sentence_score") or e.get("retrieval_score") or 0.0) * 100))
            #             md_lines.append(f"- [{pid}] {snippet}  \n  _source_: {src}  _score_: {score_pct}%\n")
            #     elif normalized_passages:
            #         # All evidence was stale - note that corpus may need rebuilding
            #         md_lines.append("\n---\n**Evidence**\n")
            #         md_lines.append("_Note: Evidence data is being refreshed. See Key Financial Metrics above for current data._\n")
            # # PFS Summary - Always show when available (our USP)
            # if latest_pfs:
            #     try:
            #         md_lines.append("\n---\n**📊 Your Financial Profile**\n")
            #         md_lines.append(f"- Net Worth: ${latest_pfs.net_worth:,.2f}\n")
            #         md_lines.append(f"- Monthly Savings: ${latest_pfs.monthly_savings:,.2f} ({latest_pfs.savings_rate:.1f}% savings rate)\n")
            #         md_lines.append(f"- Risk Tolerance: {latest_pfs.risk_tolerance or 'Not specified'}\n")
            #         if latest_pfs.investment_horizon_years:
            #             md_lines.append(f"- Investment Horizon: {latest_pfs.investment_horizon_years} years\n")
            #         md_lines.append("\n")
            #     except Exception:
            #         pass
            # 
            # # twin summary - additional insights if available
            # if twin:
            #     try:
            #         twin_caps = twin.risk_capacity or {}
            #         md_lines.append("\n**📈 Your Growth Metrics**\n")
            #         if twin.net_worth_cagr is not None:
            #             md_lines.append(f"- Net Worth Growth (CAGR): {twin.net_worth_cagr:.2%}\n")
            #         if twin.avg_savings_rate is not None:
            #             md_lines.append(f"- Average Savings Rate: {twin.avg_savings_rate:.1f}%\n")
            #         if twin.risk_capacity:
            #             md_lines.append(f"- Recommended Max Position: ${twin.risk_capacity.get('max_single_dollars', 0):,.0f}\n")
            #         md_lines.append("\n")
            #     except Exception:
            #         pass

            md = "\n".join(md_lines)
            
            # Generate and append follow-up question to maintain conversation flow
            try:
                parsed_intent = getattr(parsed, "intent", "general") if parsed else "general"
                action = proposal.get("action") if proposal else None
                followup_data = generate_followup_question(
                    intent=parsed_intent,
                    ticker=primary_ticker,
                    action=action,
                    has_pfs=bool(latest_pfs),
                    proposal=proposal
                )
                if followup_data and followup_data.get("question"):
                    # Store context for handling affirmative responses
                    st.session_state.last_followup_context = followup_data.get("context")
                    md += f"\n\n---\n\n💡 **{followup_data['question']}**"
            except Exception as e:
                trace["steps"].append({"name": "followup_question_error", "err": repr(e)})
            
            out["response_text"] = md
            if out["response_text"] is None:
                out["response_text"] = summary_text or "No analysis available."
            out["proposal"] = out.get("proposal") or {}
            out["diagnostics"] = {"evidence_count": len(normalized_passages)}
            out["fit_output"] = fit_out
            trace["steps"].append({"name": "compose", "out_len": len(md)})
        except Exception as e:
            trace["steps"].append({"name": "compose_error", "err": repr(e)})
        trace["timings"]["compose"] = time.time() - t8
        print('orchestrate: compose done')

        # persist decision trace (unchanged)
        try:
            decision_trace = {
                "user_id": user_id,
                "query": user_text,
                "parsed": getattr(parsed, "__dict__", None) or parsed,
                "twin": (twin.to_dict() if twin else None),
                "passages": normalized_passages,
                "ticker_profile": prof,
                "fit_output": fit_out,
                "proposal": proposal,
                "response_text": (summary_text[:1000] if summary_text else ""),
                "trace": trace,
            }
            persist_fn = get_logging_function()
            decision_id = persist_fn(user_id or "anonymous", decision_trace)
            out["decision_id"] = decision_id
            out["trace"]["decision_id"] = decision_id
        except Exception as e:
            print("decision persist error:", e)

        out["ok"] = True
        trace["timings"]["total"] = time.time() - start
        return out

    except Exception as e:
        err = traceback.format_exc()
        out["error"] = str(e)
        out["ok"] = False
        trace["steps"].append({"name": "fatal", "err": err})
        trace["timings"]["total"] = time.time() - start
        return out



def detect_ticker_tokens(text: str) -> List[str]:
    """
    Detect one or more ticker-like tokens from the user text.

    Strategy:
    1) Prefer explicit tickers:
       - ALL CAPS in original (AAPL, TSLA)
       - $-prefixed ($AAPL)
    2) Only if none are found, fall back to short alphabetic tokens
       that aren't in STOPWORDS.
    """
    # prevent ticker parsing if portfolio terms are present
    t = text.lower()
    portfolio_keywords = [
        "portfolio", "asset allocation", "balanced", "diversified",
        "allocation", "target mix"
    ]
    if any(k in t for k in portfolio_keywords):
        return []

    raw_tokens = text.split()
    original_tokens = [
        t.strip(".,?!:;()[]{}\"'")
        for t in raw_tokens
        if t.strip(".,?!:;()[]{}\"'")
    ]
    upper_tokens = [t.upper() for t in original_tokens]

    found: List[str] = []

    def add_candidate(sym: str):
        s = sym.upper()
        if (
            s.isalpha()
            and 1 <= len(s) <= 5
            and s not in STOPWORDS
            and s not in found
        ):
            found.append(s)

    # --- STEP 1: explicit tickers in original text (ALL CAPS) ---
    for orig in original_tokens:
        if orig.isalpha() and orig == orig.upper() and 1 <= len(orig) <= 5:
            add_candidate(orig)

    # --- STEP 2: $-prefixed tickers like $AAPL ---
    for orig in original_tokens:
        if orig.startswith("$"):
            sym = orig[1:].strip(".,?!:;()[]{}\"'")
            add_candidate(sym)

    # If we found any explicit tickers, prefer those and STOP.
    if found:
        return found

    # --- STEP 3: fallback (only if nothing explicit was found) ---
    # This supports things like "analyze tsla" or "compare aapl and msft"
    # BUT: Be more conservative - require stock-related context words
    stock_context_words = [
        "buy", "sell", "hold", "analyze", "analyse", "analysis", "compare", "comparison",
        "stock", "stocks", "equity", "share", "shares", "ticker", "symbol",
        "price", "valuation", "invest", "investment", "performance", "earnings",
        "dividend", "market", "trading", "trade", "company", "companies"
    ]
    has_stock_context = any(word in t for word in stock_context_words)
    
    # Only apply fallback if there's clear stock-related context
    if has_stock_context:
        for upper in upper_tokens:
            add_candidate(upper)

    return found

def search_symbol_finnhub_cached(query: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a company name or free-text query to a ticker using Finnhub search.
    Uses a simple in-memory cache.
    """
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return None

    q_key = query.strip().lower()
    if q_key in _SYMBOL_SEARCH_CACHE:
        return _SYMBOL_SEARCH_CACHE[q_key]

    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/search",
            params={"q": query, "token": api_key},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("result") or []
        if not results:
            _SYMBOL_SEARCH_CACHE[q_key] = None
            return None

        # Prefer common stocks
        chosen = None
        for r in results:
            if r.get("type") == "Common Stock":
                chosen = r
                break
        if not chosen:
            chosen = results[0]

        _SYMBOL_SEARCH_CACHE[q_key] = chosen
        return chosen
    except Exception as e:
        print("symbol search error:", repr(e))
        _SYMBOL_SEARCH_CACHE[q_key] = None
        return None

def generate_portfolio_suggestion(user_text: str):
    """
    Build a simple, balanced, personalized portfolio suggestion using the user's PFS.
    Returns a dict with 'explain' and 'allocation' keys, or None if no PFS.
    """
    user_id = st.session_state.get("current_user_id")
    
    # Debug logging
    print(f"DEBUG: Portfolio suggestion - user_id: {user_id}")
    
    if not user_id:
        print("DEBUG: No user_id in session state")
        return None
    
    try:
        pfs_funcs = get_pfs_functions()
        latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
        
        print(f"DEBUG: PFS fetch result: {latest_pfs is not None}")
        if latest_pfs:
            print(f"DEBUG: PFS net_worth: {latest_pfs.net_worth}")
        
        if not latest_pfs:
            # Return None to signal no PFS - caller will handle the message
            return None
    except Exception as e:
        print(f"DEBUG: Error fetching PFS: {e}")
        import traceback
        traceback.print_exc()
        return None

    # Pull relevant PFS fields
    inc = latest_pfs.net_income or 0
    nw = latest_pfs.net_worth or 0
    save_rate = latest_pfs.savings_rate or 0
    rt = (latest_pfs.risk_tolerance or "moderate").lower()
    
    # Get total assets and liabilities to check if profile is empty
    total_assets = ((latest_pfs.cash_and_equivalents or 0) + 
                   (latest_pfs.investments or 0) + 
                   (latest_pfs.real_estate or 0) + 
                   (latest_pfs.other_assets or 0))
    total_liabilities = ((latest_pfs.short_term_debt or 0) + 
                        (latest_pfs.long_term_debt or 0) + 
                        (latest_pfs.other_liabilities or 0))
    
    # Check if profile is essentially empty (all zeros)
    is_empty_profile = (total_assets == 0 and total_liabilities == 0 and inc == 0)
    
    if is_empty_profile:
        # Return a message prompting user to fill in their profile
        empty_message = """
⚠️ **Profile Incomplete - Unable to Provide Personalized Portfolio**

Your financial profile currently has no data filled in (all values are zero). To receive a personalized portfolio recommendation tailored to your situation, please:

1. 🎯 **[Update Your Profile](/Profile)** - Add your financial information
2. 📊 Include your assets, income, and liabilities
3. 🎯 Set your financial goals and risk tolerance

**What you'll get with a complete profile:**
- Personalized asset allocation based on YOUR risk capacity
- Goal-based investment recommendations
- Realistic portfolio suggestions aligned with your financial situation
- Monthly investment plan tailored to your savings rate

**For now,** I can only provide generic investment advice. Would you like to:
- Go to the Profile page to fill in your details?
- Learn about general investing principles?
- Ask specific questions about investment concepts?
"""
        return {
            "explain": empty_message,
            "allocation": {}
        }

    # Simple risk-based allocation
    if rt.startswith("conserv"):
        stocks, bonds, cash = 40, 50, 10
        label = "Conservative"
    elif rt.startswith("aggress"):
        stocks, bonds, cash = 75, 20, 5
        label = "Aggressive"
    else:
        stocks, bonds, cash = 60, 30, 10
        label = "Moderate"

    # Calculate savings rate percentage for display (already in latest_pfs.savings_rate)
    savings_rate_pct = latest_pfs.savings_rate if latest_pfs.savings_rate else 0
    
    # Get user's currency
    user_currency = latest_pfs.currency if hasattr(latest_pfs, 'currency') and latest_pfs.currency else "USD"
    
    answer = f"""
🎯 **Personalized Portfolio** based on your complete financial profile

**Your Financial Snapshot:**
• Net Worth: {format_currency(nw, user_currency)}
• Net Income: {format_currency(inc, user_currency)}/year
• Monthly Savings: {format_currency(latest_pfs.monthly_savings, user_currency)} (Rate: {savings_rate_pct:.1f}%)
• Risk Tolerance: {latest_pfs.risk_tolerance or 'Not specified'}
• Investment Horizon: {latest_pfs.investment_horizon_years or 'Not specified'} years
• Primary Goal: {latest_pfs.goal_type or 'Not specified'}

---

### 📊 Recommended {label} Allocation

- **{stocks}% Stocks** (broad US + global ETFs like VTI, VXUS)
- **{bonds}% Bonds** (intermediate-term, or a total bond market ETF like BND)
- **{cash}% Cash** (emergency buffer or short-term goals)

### Why this fits YOUR situation
- Aligns with your **{label.lower()}** risk tolerance and **{latest_pfs.investment_horizon_years or 'medium-term'}-year** horizon
- Your {format_currency(latest_pfs.monthly_savings, user_currency)} monthly savings supports systematic investing
- Balances growth potential with your {format_currency(nw, user_currency, decimals=0)} net worth base
- Provides stability for your stated goal: *{latest_pfs.goal_type or 'wealth building'}*

**Next steps**: I can help you compare specific ETFs, create a monthly investing plan, or analyze how this fits with your current holdings.
"""

    # Return dict for caller to format - don't use append_history here
    return {
        "explain": answer,
        "allocation": {}  # The markdown answer already includes allocation details
    }


def generate_portfolio_analysis(user_text: str):
    """
    Analyze user's current portfolio and provide personalized recommendations.
    Requires portfolio to be loaded in session state.
    """
    import openai
    
    # Check if portfolio exists
    portfolio_summary = st.session_state.get("portfolio_summary")
    if not portfolio_summary:
        return None
    
    # Get user PFS for personalization
    user_id = st.session_state.get("current_user_id")
    pfs_funcs = get_pfs_functions()
    latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id) if user_id else None
    
    # Build portfolio context
    total_value = portfolio_summary.get("total_value", 0)
    holdings = portfolio_summary.get("holdings", [])
    sector_alloc = portfolio_summary.get("sector_allocation", {})
    
    portfolio_text = f"**Current Portfolio** (Total Value: ${total_value:,.2f}):\n\n"
    portfolio_text += "**Holdings:**\n"
    for h in holdings[:15]:
        ticker = h.get("ticker", "")
        qty = h.get("quantity", 0)
        value = h.get("market_value", 0)
        weight = (value / total_value * 100) if total_value > 0 else 0
        portfolio_text += f"  - {ticker}: {qty} shares | ${value:,.2f} ({weight:.1f}%)\n"
    
    portfolio_text += "\n**Sector Allocation:**\n"
    for sector, pct in sorted(sector_alloc.items(), key=lambda x: x[1], reverse=True):
        portfolio_text += f"  - {sector}: {pct:.1f}%\n"
    
    # Build PFS context
    pfs_text = ""
    if latest_pfs:
        pfs_text = f"""

**Your Financial Profile:**
- Net Worth: ${latest_pfs.net_worth or 0:,.2f}
- Risk Tolerance: {latest_pfs.risk_tolerance or 'Not specified'}
- Investment Horizon: {latest_pfs.investment_horizon_years or 'Not specified'} years
- Primary Goal: {latest_pfs.goal_type or 'Not specified'}
"""
    
    # Generate analysis via LLM
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        system_prompt = f"""You are an expert portfolio analyst. Analyze the user's portfolio and provide personalized recommendations.

{portfolio_text}
{pfs_text}

Provide:
1. **Portfolio Health Assessment**: Overall quality, diversification, risk level
2. **Strengths**: What's working well
3. **Concerns**: Any red flags (high concentration, sector imbalance, risky holdings)
4. **Recommendations**: 3-5 specific actionable suggestions for improvement
5. **Alignment with Goals**: How well the portfolio matches their stated goals and risk profile

FORMATTING REQUIREMENTS:
- Use proper spacing between all words and numbers
- Format numbers with commas: $10,000 not $10000
- Always include spaces before and after numbers in sentences
- Use markdown formatting consistently (bold with **, lists with -, etc.)
- Break content into readable paragraphs

Be specific, reference their actual holdings, and provide concrete next steps. Keep response under 400 words."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text or "Analyze my portfolio"}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=600
        )
        
        analysis = response.choices[0].message.content.strip()
        
        return {
            "analysis": analysis,
            "portfolio_value": total_value,
            "num_holdings": len(holdings),
        }
        
    except Exception as e:
        print(f"Portfolio analysis error: {e}")
        import traceback
        traceback.print_exc()
        return None


# replace existing run_comparison_flow in app/Chat.py
def run_comparison_flow(valid_tickers: List[str]):
    """
    Compare 2–3 tickers side-by-side using RAG summaries and PFS conditioning.
    """
    user_id = st.session_state.get("current_user_id")
    pfs_funcs = get_pfs_functions()
    latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id) if user_id else None
    pfs_fragment = pfs_funcs['build_pfs_prompt_fragment'](latest_pfs) if latest_pfs else None

    results = []
    
    # Lazy-load required functions
    vec_funcs = get_vector_functions()
    rag_funcs = get_rag_functions()
    utils_funcs = get_utils_functions()
    score_fn = get_scoring_function()

    for t in valid_tickers:
        raw = vec_funcs['retrieve'](t, k=20)
        passages = rag_funcs['normalize_passages'](raw, query=t, ticker=t, k=6)
        summary = rag_funcs['summarize_with_evidence_and_pfs'](t, passages, pfs_fragment)


        # Extract suggested action and compute scores
        prof = get_profile_cached(t)
        price = None
        try:
            price = utils_funcs['fetch_latest_price'](t)
        except Exception:
            price = None

        base = score_fn(prof or {}, {'7d': 0.0}, 0.0)
        from app.scoring import fit_score
        f = fit_score(latest_pfs, t, base, price)

        action = "Not Available"
        if "buy" in summary.lower():
            action = "BUY"
        elif "sell" in summary.lower():
            action = "SELL"

        results.append({
            "ticker": t,
            "summary": summary,
            "action": action,
            "confidence": 0.0,
            "base_score": base,
            "fit_score": f,
            "price": price,
        })

    # Determine winner by fit_score
    best = max(results, key=lambda r: r["fit_score"])

    # Build markdown block
    md = "### 🔍 Ticker comparison\n\n"
    for r in results:
        md += f"#### **{r['ticker']}**\n{r['summary']}\n\n**Suggested:** {r['action']}  \n**Base score:** {r['base_score']:.1f}  **Fit:** {r['fit_score']:.2f}\n\n---\n"

    md += f"\n### 🏆 Best fit for you: **{best['ticker']}** (fit {best['fit_score']:.2f})\n"

    append_history("assistant", md, meta={"tickers": valid_tickers, "results": results})


def interpret_stock_query_multi(user_input: str) -> Dict[str, Any]:
    """
    Multi-ticker-aware interpretation of user input.

    Returns:
    {
      "is_stock_query": bool,
      "tickers": List[str],            # resolved tickers
      "primary_ticker": Optional[str], # first one to focus on
      "companies": Dict[str, str],     # ticker -> company name
      "profiles": Dict[str, dict],     # ticker -> profile dict
      "errors": List[str],             # any user-facing warnings
    }
    """
    text = user_input.strip()
    if not text:
        return {
            "is_stock_query": False,
            "tickers": [],
            "primary_ticker": None,
            "companies": {},
            "profiles": {},
            "errors": [],
        }

    lower = text.lower()
    has_intent_keyword = any(kw in lower for kw in INTENT_KEYWORDS)

    detected_tickers = detect_ticker_tokens(text)
    is_stock_query = bool(detected_tickers or has_intent_keyword)
    if not is_stock_query:
        return {
            "is_stock_query": False,
            "tickers": [],
            "primary_ticker": None,
            "companies": {},
            "profiles": {},
            "errors": [],
        }

    companies: Dict[str, str] = {}
    profiles: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    valid_tickers: List[str] = []

    # 1) Validate any explicit tickers
    for t in detected_tickers:
        profile = get_profile_cached(t)
        if not profile:
            errors.append(f"I couldn't find a company for ticker `{t}`. I'll ignore it for now.")
            continue
        valid_tickers.append(t)
        profiles[t] = profile
        companies[t] = profile.get("name") or profile.get("ticker") or t

    # 2) If no valid tickers yet, try to infer from company name
    if not valid_tickers:
        search_result = search_symbol_finnhub_cached(text)
        if search_result:
            resolved_t = search_result.get("symbol")
            desc = search_result.get("description") or search_result.get("name") or resolved_t
            profile = get_profile_cached(resolved_t)
            if profile:
                valid_tickers.append(resolved_t)
                profiles[resolved_t] = profile
                companies[resolved_t] = profile.get("name") or desc or resolved_t
            else:
                errors.append(
                    f"I found ticker `{resolved_t}` for '{desc}', but couldn't load its profile."
                )
        else:
            errors.append(
                "This sounds like a stock/company question, "
                "but I couldn't match it to a known ticker. "
                "Try including the ticker symbol (e.g., AAPL, TSLA)."
            )

    # De-duplicate while preserving order
    seen = set()
    tickers_ordered: List[str] = []
    for t in valid_tickers:
        if t not in seen:
            tickers_ordered.append(t)
            seen.add(t)

    return {
        "is_stock_query": True,
        "tickers": tickers_ordered,
        "primary_ticker": tickers_ordered[0] if tickers_ordered else None,
        "companies": companies,
        "profiles": profiles,
        "errors": errors,
    }




def get_user_by_email_fs(email: str) -> Optional[Dict[str, Any]]:
    # Mock mode: return mock user
    if MOCK_MODE:
        email_normalized = email.strip().lower()
        return {
            "email": email_normalized,
            "uid": "mock_user_001",
            "displayName": "Mock User",
            "created_at": datetime.now().isoformat(),
        }
    
    # Production mode: use Firestore
    email = email.strip().lower()
    db_fs = get_firestore_client()
    if not db_fs:
        return None
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

def is_pfs_progress_request(text: str) -> bool:
    t = text.lower()
    return ("pfs" in t or "personal financial" in t or "net worth" in t) and (
        "history" in t or "progress" in t or "chart" in t or "graph" in t
    )

def render_quick_prompts():
    """
    Show up to six quick prompts horizontally.
    """
    import random

    try:
        prompts = QUICK_PROMPTS
    except NameError:
        prompts = [
            "Could you help me review AAPL based on my financial profile and see if it fits my goals?",
            "How does TSLA look right now, and is it a good match for my savings rate and risk tolerance?",
            "Look at NVDA for me — do you think it’s aligned with my time horizon and overall plan?",
            "Check out MSFT with the latest news. Would it be a healthy addition for someone like me?",
            "Given my current debt, savings, and goals, should I prioritize investing or paying things down first?",
            "Am I building wealth at a healthy pace based on my net worth and monthly savings?",
            "With my income and expenses, how much should I comfortably invest each month?",
            "Based on my risk tolerance, what type of investment mix could help me stay steady and confident?",
            "Using my financial profile, could you suggest a simple, balanced portfolio that fits where I’m headed?",
            "I’d love your help shaping a long-term investment plan based on my savings rate and goals.",
            "Can you recommend what share of my money might go toward stocks vs safer options, given my situation?",
            "Could you show me how my net worth has changed over time? I’m curious to see my progress.",
            "Let’s look at a chart of my PFS history so I can see how far I’ve come.",
            "Would you graph my monthly savings across the snapshots I’ve saved?",
            "How is my financial profile trending overall? Am I moving in a positive direction?",
            "Can you check whether adding more to VOO makes sense for me financially right now?",
            "If I want to retire in around 15 years, how do ETFs like VTI or QQQ fit into that picture?",
            "Given my net worth and goals, is increasing my position in TSLA too aggressive or just right?",
            "Could you look at my monthly savings and tell me if I’m setting myself up for long-term success?",
            "Could you look at my net worth and monthly savings and highlight any opportunities to improve?",
            "Suggest a simple, balanced portfolio based on my financial profile.",
            "Compare AAPL and MSFT for me.",
            "Recommend ETFs for a conservative investor.",
        ]

    # Flatten if dict-of-lists
    flat = []
    if isinstance(prompts, dict):
        for v in prompts.values():
            if isinstance(v, list):
                flat.extend(v)
            else:
                flat.append(str(v))
    else:
        flat = list(map(str, prompts))

    # Store chosen prompts in session state to keep them consistent across reruns
    # Only reset if not initialized yet (not based on history length)
    if "quick_prompts_chosen" not in st.session_state:
        count = min(6, len(flat))
        st.session_state.quick_prompts_chosen = random.sample(flat, count)
    
    chosen = st.session_state.quick_prompts_chosen
    count = len(chosen)

    # Add CSS for uniform button sizing with more specific selectors
    st.markdown("""
        <style>
        /* Target all buttons in quick prompts section */
        div[data-testid="column"] > div > div > button[kind="secondary"] {
            height: 85px !important;
            min-height: 85px !important;
            max-height: 85px !important;
            white-space: normal !important;
            word-wrap: break-word !important;
            overflow-wrap: break-word !important;
            padding: 10px 8px !important;
            font-size: 12px !important;
            line-height: 1.3 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            text-align: center !important;
            width: 100% !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # Display prompts in two rows
    # Split chosen prompts into two rows
    mid_point = (count + 1) // 2  # Ceiling division for first row
    first_row = chosen[:mid_point]
    second_row = chosen[mid_point:]
    
    # First row
    cols = st.columns(len(first_row))
    for col, q in zip(cols, first_row):
        with col:
            key = f"qp_{abs(hash(q)) % (10**7)}"
            if st.button(q, key=key, use_container_width=True):
                st.session_state.pending_quick_prompt = q
                st.rerun()
    
    # Second row
    if second_row:
        cols = st.columns(len(second_row))
        for col, q in zip(cols, second_row):
            with col:
                key = f"qp_{abs(hash(q)) % (10**7)}"
                if st.button(q, key=key, use_container_width=True):
                    st.session_state.pending_quick_prompt = q
                    st.rerun()




def validate_tickers(tickers: List[str]) -> Tuple[List[str], List[str]]:
    """
    Validate list of ticker symbols by checking if each resolves to
    a company profile via get_profile_cached().

    Returns:
        valid:   list of confirmed tickers
        invalid: list of unrecognized tokens
    """
    valid = []
    invalid = []

    for t in tickers:
        profile = get_profile_cached(t)
        if profile:
            valid.append(t)
        else:
            invalid.append(t)

    return valid, invalid


def get_profile_cached(ticker: str) -> Optional[Dict[str, Any]]:
    """Get company profile, cached in memory."""
    t = ticker.upper()
    if t in _PROFILE_CACHE:
        return _PROFILE_CACHE[t]

    utils_funcs = get_utils_functions()
    profile = utils_funcs['fetch_company_profile'](t)
    if profile:
        _PROFILE_CACHE[t] = profile
    return profile

def render_profile_status():
    """Show a small badge indicating whether the financial profile is set up."""
    user_id = st.session_state.get("current_user_id")
    if not user_id:
        st.caption("Profile status: ❓ No user selected yet.")
        return

    pfs_funcs = get_pfs_functions()
    latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
    if not latest_pfs:
        st.caption("Profile status: ⚪ Not set up yet.")
        st.info("Go to the **Profile** page to create your financial profile.")
        return

    # Heuristic: consider profile 'better' if some key fields are non-zero
    filled_keys = [
        latest_pfs.net_income,
        latest_pfs.cash_and_equivalents,
        latest_pfs.investments,
    ]
    if any(v > 0 for v in filled_keys):
        st.caption("Profile status: ✅ Connected and in use.")
    else:
        st.caption("Profile status: 🟡 Partial — fill in more details on the Profile page.")





# Check authentication before allowing access
#require_authentication()

# Step 0: Trust Center Acknowledgment (First-time users)
if "trust_center_acknowledged" not in st.session_state:
    st.session_state.trust_center_acknowledged = False

if not st.session_state.trust_center_acknowledged:
    st.title("🛡️ Welcome to Perfient")
    
    st.markdown("""
    ### Before You Begin
    
    Perfient helps you make better investment decisions using your personal financial data. 
    We take this responsibility seriously.

    You’re using an early version of Perfient designed to test usefulness, clarity, and trust — not perfection. 

    Some features are experimental and may change. Outputs can be wrong — challenge them. Your feedback directly shapes the product.
    
    **Please take a moment to understand how we protect your data and earn your trust:**
    """)
    
    st.info("""
    📖 **[Read our Trust Center](https://perfient.com/trust-center.html)** to learn about:
    - How we secure your data with bank-grade encryption
    - What data we collect and how we use it
    - Your privacy rights and controls
    - Our commitment to transparency
    - GDPR compliance and data protection
    """)
    
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        By proceeding, you acknowledge that you have read or will read our Trust Center 
        and agree to our data handling practices; that Perfient is not providing financial advice;  that you remain responsible for your decisions.
        """)
        
        if st.button("✅ I Understand, Let's Get Started", type="primary", use_container_width=True):
            st.session_state.trust_center_acknowledged = True
            st.rerun()
    
    st.markdown("---")
    st.caption("🔒 Your data belongs to you. We never sell it, show ads, or monetize your information.")
    
    st.stop()

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

st.title("Perfient — Your investment copilot ")
st.caption("Ask about any ticker, portfolio, or investment idea. Example: 'Analyze TSLA' or 'What should I do with AAPL?'")

# Show mock mode banner if running in local development mode
if MOCK_MODE:
    st.info(
        "🔧 **Development Mode**: Running with mock user data (no Firestore connection). "
        f"Mock User: **mock_user_001** | Net Worth: **$320K** | Risk: **Moderate**. "
        "Set `MOCK_MODE=false` in `.env` to connect to production backend."
    )

# Session state
if "current_user_id" not in st.session_state:
    # In mock mode, default to mock_user_001 for testing
    st.session_state.current_user_id = "mock_user_001" if MOCK_MODE else None
if "current_user_email" not in st.session_state:
    st.session_state.current_user_email = "mock@example.com" if MOCK_MODE else None
if "history" not in st.session_state:
    st.session_state.history = []   # list of (role, text, meta)
if "last_proposal" not in st.session_state:
    st.session_state.last_proposal = {}

if "show_pfs_page" not in st.session_state:
    st.session_state.show_pfs_page = False

if "pfs_warning_flag" not in st.session_state:
    st.session_state.pfs_warning_flag = False

if "pfs_notice_shown" not in st.session_state:
    st.session_state.pfs_notice_shown = False

if "dev_mode" not in st.session_state:
    st.session_state.dev_mode = False

if "pending_input" not in st.session_state:
    st.session_state["pending_input"] = None
if "submit_quick_prompt" not in st.session_state:
    st.session_state["submit_quick_prompt"] = False
if "center_input" not in st.session_state:
    st.session_state["center_input"] = ""
if "pending_quick_prompt" not in st.session_state:
    st.session_state["pending_quick_prompt"] = None




def append_history(role, text, meta=None):
    st.session_state.history.append({"role": role, "text": text, "meta": meta or {}})


def check_profile_complete(user_id: str) -> bool:
    """Check if user has completed their financial profile by checking PFS data."""
    try:
        # Get latest PFS (Personal Financial Statement)
        pfs_funcs = get_pfs_functions()
        latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
        
        if not latest_pfs:
            return False
        
        # Check if PFS has actual data (not all zeros)
        total_assets = ((latest_pfs.cash_and_equivalents or 0) + 
                       (latest_pfs.investments or 0) + 
                       (latest_pfs.real_estate or 0) + 
                       (latest_pfs.other_assets or 0))
        total_liabilities = ((latest_pfs.short_term_debt or 0) + 
                            (latest_pfs.long_term_debt or 0) + 
                            (latest_pfs.other_liabilities or 0))
        net_income = latest_pfs.net_income or 0
        
        # Profile is complete if user has entered financial data
        has_financial_data = (total_assets > 0 or total_liabilities > 0 or net_income > 0)
        
        # Also check essential fields are present
        has_essential_fields = bool(
            latest_pfs.risk_tolerance and
            (latest_pfs.investment_horizon_years is not None)
        )
        
        return has_financial_data and has_essential_fields
        
    except Exception as e:
        logger.error(f"Error checking profile completion: {e}")
        return False


def check_portfolio_uploaded(user_id: str) -> bool:
    """Check if user has uploaded a portfolio."""
    try:
        # First check session state (fast path)
        portfolio_summary = st.session_state.get("portfolio_summary")
        if portfolio_summary and portfolio_summary.get("holdings"):
            return True
        
        # Mock mode: return mock portfolio status
        if MOCK_MODE:
            from app.mock_data import get_mock_portfolio
            mock_portfolio = get_mock_portfolio(user_id or "mock_user_001")
            return len(mock_portfolio.get("holdings", [])) > 0
        
        # If not in session, check Firestore for saved portfolio
        db_fs = get_firestore_client()
        if not db_fs:
            return False
        doc_ref = db_fs.collection("portfolios").document(user_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            holdings = data.get("holdings", [])
            return len(holdings) > 0
        
        return False
    except Exception as e:
        logger.error(f"Error checking portfolio upload: {e}")
        return False


def get_personalized_recommendations(user_id: str) -> Dict[str, Any]:
    """
    Get personalized next steps and recommendations for users with complete profiles.
    Returns wealth stage info, financial health insights, and actionable next steps.
    """
    try:
        # Get latest PFS
        pfs_funcs = get_pfs_functions()
        latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
        
        if not latest_pfs:
            return None
        
        # Import Dashboard functions
        from app.pages import Dashboard as dash_module
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dashboard",
            os.path.join(os.path.dirname(__file__), "pages", "02_Dashboard.py")
        )
        dashboard = importlib.util.module_from_spec(spec)
        
        # Calculate financial health score
        try:
            spec.loader.exec_module(dashboard)
            health_score = dashboard.calculate_financial_health_score(latest_pfs)
            wealth_stage = dashboard.categorize_wealth_stage(latest_pfs.net_worth)
        except Exception:
            # Fallback to simple calculations
            health_score = None
            wealth_stage = None
        
        # Get twin for additional insights
        try:
            pft_funcs = get_pft_functions()
            twin = pft_funcs['get_or_build_twin'](user_id, mode='lite', max_age_hours=24)
        except Exception:
            twin = None
        
        return {
            "health_score": health_score,
            "wealth_stage": wealth_stage,
            "twin": twin,
            "pfs": latest_pfs,
        }
    except Exception as e:
        logger.error(f"Error getting personalized recommendations: {e}")
        return None


# Initialize onboarding session state
if "onboarding_dismissed" not in st.session_state:
    st.session_state.onboarding_dismissed = False

# Show onboarding checklist for new users OR personalized recommendations for complete users
if st.session_state.get("current_user_id") and not st.session_state.onboarding_dismissed:
    profile_complete = check_profile_complete(st.session_state.current_user_id)
    portfolio_uploaded = check_portfolio_uploaded(st.session_state.current_user_id)
    
    # If both profile and portfolio are complete, show personalized recommendations
    if profile_complete and portfolio_uploaded:
        recommendations = get_personalized_recommendations(st.session_state.current_user_id)
        
        if recommendations:
            # Get user's name for personalized greeting
            user_display_name = st.session_state.get("current_user_id", "there")
            try:
                pfs = recommendations.get("pfs")
                if pfs and hasattr(pfs, 'user_id'):
                    user_display_name = pfs.user_id
            except Exception:
                pass
            
            with st.expander("🎯 **Your Personalized Dashboard**", expanded=not st.session_state.get("dashboard_collapsed", False)):
                # Welcome message for returning users with complete profiles
                st.markdown(f"### Welcome back, {user_display_name}! 👋")
                st.caption("Your profile and portfolio are set up. Here's your personalized financial overview.")
                st.markdown("---")
                
                # Financial Roadmap Section
                pfs = recommendations.get("pfs")
                if pfs:
                    # Import Dashboard roadmap function
                    try:
                        import importlib.util
                        spec = importlib.util.spec_from_file_location(
                            "dashboard",
                            os.path.join(os.path.dirname(__file__), "pages", "02_Dashboard.py")
                        )
                        dashboard = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(dashboard)
                        
                        roadmap = dashboard.calculate_financial_roadmap(pfs)
                        if roadmap and roadmap["next_level"]:
                            st.markdown("### 🗺️ Your Financial Journey")
                            
                            next_level = roadmap["next_level"]
                            progress_pct = roadmap["progress_pct"]
                            
                            st.markdown(f"**Current Goal:** {next_level['name']}")
                            st.caption(next_level['description'])
                            st.progress(progress_pct / 100)
                            st.caption(f"Level {roadmap['current_level']}/{roadmap['total_levels']} • {progress_pct:.0f}% complete")
                            
                            st.markdown("---")
                    except Exception as e:
                        logger.error(f"Error loading roadmap: {e}")
                
                st.markdown("### Financial Health Overview 📊")
                
                col_health, col_wealth = st.columns(2)
                
                # Health Score
                with col_health:
                    health_score = recommendations.get("health_score")
                    if health_score:
                        st.markdown(f"#### {health_score['color']} Financial Health: {health_score['total_score']}/100")
                        st.caption(f"Grade: **{health_score['grade']}** - {health_score['status']}")
                        
                        # Key metrics
                        metrics = health_score['metrics']
                        st.write(f"💰 Savings Rate: {metrics['savings_rate']:.1f}%")
                        st.write(f"🏦 Emergency Fund: {metrics['emergency_months']:.1f} months")
                
                # Wealth Stage
                with col_wealth:
                    wealth_stage = recommendations.get("wealth_stage")
                    if wealth_stage:
                        st.markdown(f"#### {wealth_stage['stage']}")
                        st.caption(wealth_stage['description'])
                        st.info(f"🎯 **Next Milestone:** {wealth_stage['next_milestone']}")
                
                st.markdown("---")
                
                # Actionable Next Steps
                st.markdown("### 🚀 Recommended Actions")
                
                wealth_stage = recommendations.get("wealth_stage")
                if wealth_stage:
                    st.markdown(f"💡 **{wealth_stage['advice']}**")
                
                # Quick action buttons
                st.markdown("")
                col_action1, col_action2, col_action3 = st.columns(3)
                
                with col_action1:
                    if st.button("📈 View Full Dashboard", use_container_width=True):
                        st.switch_page("pages/02_Dashboard.py")
                
                with col_action2:
                    if st.button("💼 Review Portfolio", use_container_width=True):
                        st.switch_page("pages/03_Portfolio.py")
                
                with col_action3:
                    if st.button("⚙️ Update Profile", use_container_width=True):
                        st.switch_page("pages/01_Profile.py")
                
                # Collapse button
                st.markdown("")
                if st.button("✖ Collapse this panel", key="collapse_dashboard"):
                    st.session_state.dashboard_collapsed = True
                    st.rerun()
    else:
        # Original onboarding flow for incomplete profiles
        with st.expander("🎯 **Get Started - Complete Your Setup**", expanded=not st.session_state.get("onboarding_collapsed", False)):
            st.markdown("### Welcome to Perfient! 👋")
            st.markdown("To get personalized investment advice, please complete the following steps:")
            
            col_steps, col_dismiss = st.columns([5, 1])
            
            with col_steps:
                # Step 1: Profile
                if not profile_complete:
                    st.markdown("#### ⬜ Step 1: Complete Your Financial Profile")
                    st.caption("Tell us about your financial situation, goals, and risk tolerance to get personalized recommendations.")
                    if st.button("📝 Go to Profile →", key="onboarding_profile", type="primary"):
                        st.switch_page("pages/01_Profile.py")
                else:
                    st.markdown("#### ✅ Step 1: Profile Complete!")
                
                st.markdown("---")
                
                # Step 2: Portfolio (optional)
                if not portfolio_uploaded:
                    st.markdown("#### ⬜ Step 2: Upload Your Portfolio *(Optional)*")
                    st.caption("Upload your existing holdings to get portfolio-specific advice and analysis.")
                    if st.button("📊 Go to Portfolio →", key="onboarding_portfolio"):
                        st.switch_page("pages/03_Portfolio.py")
                else:
                    st.markdown("#### ✅ Step 2: Portfolio Uploaded!")
                
                if profile_complete and portfolio_uploaded:
                    st.success("🎉 **Setup Complete!** You're all set to get personalized investment advice.")
                    if st.button("Dismiss this guide", key="dismiss_onboarding"):
                        st.session_state.onboarding_dismissed = True
                        st.rerun()
            
            with col_dismiss:
                if st.button("✕", key="collapse_onboarding", help="Collapse this guide"):
                    st.session_state.onboarding_collapsed = True
                    st.rerun()

st.markdown("---")

# Ensure onboarding flags are initialized to avoid NameError in environments where earlier branches didn't set them
if 'profile_complete' not in globals():
    profile_complete = False
if 'portfolio_uploaded' not in globals():
    portfolio_uploaded = False

dev_col, _ = st.columns([0.2, 0.8])
with dev_col:
    st.session_state.dev_mode = st.checkbox("Developer mode", value=st.session_state.dev_mode, help="Show orchestration trace and function calls for last decision")

# Chat UI (left) + context / quick actions (right)
col1, _ = st.columns([3,1])

with col1:
    # Create a container for chat messages
    chat_container = st.container()
    
    with chat_container:
        # Show welcome message for users with complete profiles (no chat history yet)
        if not st.session_state.get("history") and profile_complete:
            # Get user's name from profile
            user_name = "there"
            try:
                if latest_pfs and hasattr(latest_pfs, 'user_id'):
                    user_name = latest_pfs.user_id
                elif st.session_state.get("current_user_id"):
                    user_name = st.session_state.get("current_user_id")
            except Exception:
                pass
            
            welcome_msg = f"""### Welcome back, {user_name}! 👋

I'm your personal investment copilot. You have successfully built your financial Twin. With it, I can now provide personalized recommendations.

**What would you like to know?**
- 💰 Ask about specific stocks or ETFs (e.g., "What do you think about AAPL?")
- 📊 Request portfolio analysis or suggestions
- 🎯 Get advice aligned with your financial goals
- 📈 Review investment opportunities that match your risk tolerance

Feel free to ask me anything about investments, and I'll provide personalized advice based on your profile."""
            
            st.chat_message("assistant").markdown(welcome_msg)
        
        # render chat history
        for i, msg in enumerate(st.session_state.history):
            if msg["role"] == "user":
                st.chat_message("user").markdown(msg["text"])
            else:
                st.chat_message("assistant").markdown(msg["text"])

                # try to find the decision_id related to this message (we store it in meta when appending)
                decision_id = None
                pfs_fragment = None
                if isinstance(msg, dict) and msg.get("meta"):
                    meta = msg.get("meta", {})
                    decision_id = meta.get("decision_id") or (meta.get("trace", {}) or {}).get("decision_id")
                    pfs_fragment = meta.get("pfs_fragment")
                
                # Show "What the AI sees" transparency panel
                with st.expander("🔍 What the AI sees", expanded=False):
                    if pfs_fragment:
                        st.caption("**Your Financial Profile (Summarized & Anonymized)**")
                        st.caption("This is the exact financial context we provide to the AI to personalize recommendations for you. Your data never leaves our secure system.")
                        st.code(pfs_fragment, language="text")
                    else:
                        st.caption("**No financial profile loaded**")
                        st.info("💡 This response used general market analysis only. Create your financial profile to get personalized recommendations based on your specific situation.")
                        if st.button("📝 Create Profile", key=f"create_profile_{i}"):
                            st.switch_page("pages/01_Profile.py")

                # Render feedback buttons inline under this assistant message
                cols = st.columns([0.1, 0.1, 1.0])
                with cols[0]:
                    if st.button("👍", key=f"fb_up_{i}"):
                        uid = st.session_state.get("current_user_id") or "anonymous"
                        if decision_id:
                            log_feedback(uid, decision_id, helpful=True)
                            # show a small ephemeral message (this triggers a rerun)
                            st.rerun()
                        else:
                            st.info("No decision id saved for this message.")
                with cols[1]:
                    if st.button("👎", key=f"fb_down_{i}"):
                        # mark that comment box should be shown for this message
                        st.session_state[f"fb_comment_visible_{i}"] = True

                # Show comment box when user clicked 👎
                if st.session_state.get(f"fb_comment_visible_{i}"):
                    comment = st.text_area("Tell us why (optional):", key=f"fb_comment_{i}", height=80)
                    if st.button("Submit feedback", key=f"fb_submit_{i}"):
                        uid = st.session_state.get("current_user_id") or "anonymous"
                        if decision_id:
                            log_feedback(uid, decision_id, helpful=False, comment=comment)
                            # hide the comment box and rerun to reflect change
                            st.session_state[f"fb_comment_visible_{i}"] = False
                            st.rerun()
                        else:
                            st.info("No decision id saved for this message.")

    # Auto-scroll anchor - this helps browsers scroll to the latest message
    if st.session_state.history:
        st.markdown('<div id="chat-end-anchor"></div>', unsafe_allow_html=True)
        
        # Use st.rerun() tracking to scroll only on new messages
        if "last_scroll_count" not in st.session_state:
            st.session_state.last_scroll_count = 0
        
        current_count = len(st.session_state.history)
        should_scroll = current_count > st.session_state.last_scroll_count
        st.session_state.last_scroll_count = current_count
        
        if should_scroll:
            import streamlit.components.v1 as components
            # Force scroll with multiple strategies and longer delays
            components.html(
                f"""
                <script>
                    function forceScrollToBottom() {{
                        try {{
                            // Strategy 1: Scroll main section
                            const mainSection = window.parent.document.querySelector('section.main');
                            if (mainSection) {{
                                mainSection.scrollTo({{
                                    top: mainSection.scrollHeight,
                                    behavior: 'smooth'
                                }});
                            }}
                            
                            // Strategy 2: Scroll to bottom element
                            const anchor = window.parent.document.getElementById('chat-end-anchor');
                            if (anchor) {{
                                anchor.scrollIntoView({{ behavior: 'smooth', block: 'end' }});
                            }}
                            
                            // Strategy 3: Direct scroll manipulation
                            if (mainSection) {{
                                mainSection.scrollTop = mainSection.scrollHeight + 1000;
                            }}
                        }} catch (e) {{
                            console.log('Scroll error:', e);
                        }}
                    }}
                    
                    // Execute immediately
                    forceScrollToBottom();
                    
                    // Execute with increasing delays to catch dynamic content
                    [100, 200, 400, 800, 1200].forEach(delay => {{
                        setTimeout(forceScrollToBottom, delay);
                    }});
                </script>
                <div style="display:none;">{current_count}</div>
                """,
                height=0,
            )
    
    
    

# ---------- Improved intent + continuation helpers ----------
import re
from typing import Dict, Any, List, Optional, Tuple

# Dialog-state keys used in st.session_state:
# - dialog_state: { 'last_intent': str, 'last_tickers': List[str], 'pending_question': Optional[str], 'context': dict }
if "dialog_state" not in st.session_state:
    st.session_state.dialog_state = {
        "last_intent": None,
        "last_tickers": [],
        "pending_question": None,
        "context": {},
    }

def classify_intent_enhanced(text: str) -> str:
    t = (text or "").lower().strip()

    # Portfolio / allocation requests (strong)
    portfolio_kw = [
        "portfolio", "asset allocation", "balanced", "diversified",
        "allocation", "retirement mix", "build me a portfolio",
        "investment mix", "how should i allocate", "target allocation",
        "investment plan", "investing plan", "investment strategy",
        "help me invest", "where should i invest", "invest suggestions",
        "investment suggestions", "what should i invest", "how to invest",
        "given my situation", "based on my situation", "for my situation",
        "share of my money", "stocks vs", "safer options"
    ]
    if any(kw in t for kw in portfolio_kw):
        return "portfolio_request"
    
    # Check for investment queries with dollar amounts (e.g., "I have $X, help me invest")
    if re.search(r"(i have|i've got|with)\s*\$?\d+.*\b(invest|put|allocate)", t):
        return "portfolio_request"

    # Comparison patterns (explicit "vs", "compare", "which is better")
    if re.search(r"\b(compare|which (is|one) (is )?better|versus| vs | v\. )\b", t):
        return "ticker_comparison"

    # If user explicitly asks about "my holdings" or "my portfolio" -> portfolio
    if any(kw in t for kw in ["my holdings", "my portfolio", "my investments as a whole"]):
        return "portfolio_request"

    # If user mentions typical trade verbs and an uppercase token in original text, it's likely ticker analysis
    if re.search(r"\b(buy|sell|hold|review|analy(z|s)e|valuation)\b", t) and re.search(r"[A-Z]{2,5}\b", text):
        return "ticker_analysis"

    # Suppress ticker detection when portfolio-related language present
    portfolio_blockers = ["portfolio", "allocation", "allocate", "diversify"]
    if not any(b in t for b in portfolio_blockers):
        detected = detect_ticker_tokens(text)
        # Only treat as ticker_analysis if we actually found valid tickers
        # AND the query isn't just a single common word
        if detected and len(detected) > 0:
            # Check if it's just a single common word that might not be a ticker
            if len(detected) == 1 and len(text.strip().split()) == 1:
                # Single word input - check if it looks like actual stock context
                single_word = text.strip().lower()
                common_words = [
                    "yes", "no", "ok", "okay", "sure", "thanks", "hello", "hi",
                    "help", "start", "begin", "what", "how", "why", "when", "where",
                    "good", "bad", "maybe", "analysis"
                ]
                if single_word in common_words:
                    return "general"
            return "ticker_analysis"

    # Heuristic: if text is question about general finance / definitions -> general
    if re.search(r"\b(what is|how do i|explain|should i|advice|suggest)\b", t):
        return "general"

    # fallback
    return "general"

def update_dialog_state(last_intent: Optional[str]=None, last_tickers: Optional[List[str]]=None, pending_question: Optional[str]=None, extra_context: Optional[Dict]=None):
    ds = st.session_state.dialog_state
    if last_intent is not None:
        ds["last_intent"] = last_intent
    if last_tickers is not None:
        ds["last_tickers"] = last_tickers
    ds["pending_question"] = pending_question
    if extra_context:
        ds["context"].update(extra_context)

def clear_dialog_state():
    st.session_state.dialog_state = {"last_intent": None, "last_tickers": [], "pending_question": None, "context": {}}

def resolve_tickers_with_feedback(tickers: List[str]) -> Tuple[List[str], List[str]]:
    """
    Returns (valid, invalid) and will append a helpful assistant message if invalids exist.
    """
    if not tickers:
        return [], []
    valid, invalid = validate_tickers(tickers)
    if invalid and not valid:
        append_history("assistant", f"I couldn't recognize those symbols: {', '.join(invalid)}. Could you double-check the tickers or provide company names?")
        update_dialog_state(pending_question="clarify_tickers")
        return [], invalid
    if invalid and valid:
        append_history("assistant", f"I couldn't recognize these tickers: {', '.join(invalid)}. I'll continue using: {', '.join(valid)}.")
    return valid, invalid

def display_processing_status(text: str, user_id: str = None):
    """
    Display real-time processing status to show users what's happening behind the scenes.
    Returns the orchestrate_query result.
    """
    with st.status("🤔 Understanding your request...", expanded=True) as status:
        # Step 1: Parse intent with LLM and conversation context
        st.write("🔍 **Analyzing your input with AI...**")
        # Get conversation history for context
        conversation_history = st.session_state.get("history", [])
        reframed_text = text  # Default to original text
        
        try:
            parsed = process_user_input(text, conversation_history=conversation_history)
            intent = getattr(parsed, "intent", "general")
            tickers = getattr(parsed, "tickers", [])
            can_handle = getattr(parsed, "can_handle", True)
            extras = getattr(parsed, "extras", {})
            
            # IMPORTANT: Get the potentially reframed text from parsed input
            # If "yes" was reframed to "Compare AAPL with...", we need to use that
            reframed_text = getattr(parsed, "raw", text)
            
            # Show analysis method
            if extras.get("method") == "keyword_fallback":
                st.write("ℹ️ Using keyword-based analysis")
            elif extras.get("llm_confidence"):
                st.write(f"✓ AI analysis complete (confidence: {extras['llm_confidence']:.0%})")
            else:
                st.write("✓ Analysis complete")
            
            # Handle out-of-scope
            if not can_handle or intent == "out_of_scope":
                st.write("⚠️ This query is outside my capabilities")
                status.update(label="ℹ️ Request outside scope", state="complete", expanded=False)
                # Return early with out-of-scope response (use reframed text)
                result = orchestrate_query(reframed_text, user_id=user_id)
                return result
            
            # Show detected intent
            if intent == "ticker_analysis" and tickers:
                st.write(f"✓ Detected: Analyzing **{', '.join(tickers)}**")
            elif intent == "ticker_comparison" and len(tickers) >= 2:
                st.write(f"✓ Detected: Comparing **{' vs '.join(tickers[:3])}**")
            elif intent == "portfolio_request":
                st.write("✓ Detected: Portfolio strategy request")
            else:
                st.write("✓ Understanding your question...")
        except Exception as e:
            st.write(f"⚠️ Analysis issue: {str(e)}")
            st.write("✓ Processing with fallback method...")
        
        # Step 2: Loading profile
        st.write("👤 **Loading your financial profile...**")
        if user_id:
            try:
                pfs_funcs = get_pfs_functions()
                latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
                if latest_pfs:
                    st.write("✓ Profile loaded - personalizing recommendations")
                else:
                    st.write("ℹ️ No profile found - using general analysis")
            except Exception:
                st.write("ℹ️ Using general analysis")
        else:
            st.write("ℹ️ Using general analysis")
        
        # Step 3: Retrieving data
        if tickers and intent in ("ticker_analysis", "ticker_comparison"):
            st.write(f"📊 **Retrieving data for {', '.join(tickers[:3])}...**")
            st.write("✓ Fetching market data and research")
        
        # Step 4: Analyzing
        st.write("🧠 **Analyzing with AI...**")
        st.write("✓ Generating insights and recommendations")
        
        # Execute the actual query with reframed text (if yes/no was reframed)
        result = orchestrate_query(reframed_text, user_id=user_id)
        
        # Update status based on result
        if result.get("ok"):
            status.update(label="✅ Analysis complete!", state="complete", expanded=False)
        else:
            status.update(label="⚠️ Analysis completed with issues", state="error", expanded=False)
    
    return result


def handle_user_message(text):
    """Handle user message with special handling for simple conversational responses."""
    text_lower = text.lower().strip().rstrip('!.,?')
    
    # First check if this is a follow-up response to a previous question
    # Check conversation history for pending questions
    conversation_history = st.session_state.get("history", [])
    is_follow_up = False
    
    if conversation_history and len(conversation_history) > 0:
        last_msg = conversation_history[-1]
        if last_msg.get("role") == "assistant":
            last_text = last_msg.get("text", "")
            # If last assistant message was a question, treat simple responses as follow-ups
            if "?" in last_text:
                is_follow_up = True
    
    # List of simple conversational responses that don't need full analysis
    # BUT only if they're NOT follow-ups to a question
    simple_greetings = {
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "bye", "goodbye", "see you", "later",
    }
    
    simple_thanks = {
        "thanks", "thank you", "thx", "ty",
    }
    
    # Only intercept greetings and thanks if they're NOT follow-ups
    if not is_follow_up and text_lower in simple_greetings:
        responses = {
            "hi": "Hello! How can I assist with your investments today?",
            "hello": "Hi there! Ready to help you with your investment decisions.",
            "hey": "Hey! What can I help you with?",
            "good morning": "Good morning! How can I assist you today?",
            "good afternoon": "Good afternoon! What can I help you with?",
            "good evening": "Good evening! How can I help with your investments?",
            "bye": "Goodbye! Feel free to return anytime you have questions.",
            "goodbye": "Take care! I'm here whenever you need investment guidance.",
            "see you": "See you! Come back anytime you need help.",
            "later": "See you later! Happy investing!",
        }
        response = responses.get(text_lower, "Hello! How can I help you today?")
        append_history("assistant", response)
        return
    
    if not is_follow_up and text_lower in simple_thanks:
        responses = {
            "thanks": "You're welcome! Happy to help anytime.",
            "thank you": "My pleasure! Let me know if you need anything else.",
            "thx": "Anytime! I'm here to help.",
            "ty": "You're welcome! Feel free to ask more questions.",
        }
        response = responses.get(text_lower, "You're welcome!")
        append_history("assistant", response)
        return
    
    # For all other cases (including yes/no follow-ups), proceed with full processing
    user_id = st.session_state.get("current_user_id")
    
    # In mock mode, ensure we always have a user_id
    if MOCK_MODE and not user_id:
        user_id = "mock_user_001"
        st.session_state.current_user_id = user_id

    # Display processing status and get result
    result = display_processing_status(text, user_id=user_id)
    
    # Render answer (chat bubble) with PFS fragment for transparency
    meta = {
        "trace": result.get("trace"),
        "decision_id": result.get("decision_id"),
        "pfs_fragment": result.get("trace", {}).get("pfs_fragment") if result.get("trace") else None
    }
    append_history("assistant", result["response_text"], meta=meta)

    # Store last proposal for the right-hand sidebar
    st.session_state.last_proposal = {
        "proposal": result.get("proposal"),
        "fit_output": result.get("fit_output"),
        "raw": result.get("response_text"),
        "decision_id": result.get("decision_id"),
    }


# ======= Improved NLP input processing (fuzzy matching, NER, normalization) =======


# Optional third-party libs: rapidfuzz, spaCy. Code will gracefully fall back if unavailable.
try:
    from rapidfuzz import process as rf_process, fuzz as rf_fuzz
except Exception:
    rf_process = None
    rf_fuzz = None

try:
    import spacy
    _SPACY = spacy.load("en_core_web_sm", disable=["parser", "tagger"])
except Exception:
    _SPACY = None

# ---------- Firestore-backed stock index ----------

@lru_cache(maxsize=1)
def load_stock_index_firestore() -> Dict[str, Dict[str, str]]:
    """
    Loads all stock metadata from Firestore collection `stocks/{TICKER}`.
    Expected document format:
    {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "sector": "...",
        "industry": "...",
        ...
    }
    """
    index = {}
    try:
        db_fs = get_firestore_client()
        collection_ref = db_fs.collection("stocks")
        docs = collection_ref.stream()
        for doc in docs:
            data = doc.to_dict() or {}
            t = (data.get("ticker") or doc.id).upper().strip()
            name = data.get("name") or ""
            index[t] = {"ticker": t, "name": name, **data}
    except Exception as e:
        print("Warning: failed to load stock index from Firestore:", e)

    # Fallback minimal set (only if Firestore is empty)
    if not index:
        index = {
            "AAPL": {"ticker": "AAPL", "name": "Apple Inc."},
            "MSFT": {"ticker": "MSFT", "name": "Microsoft Corporation"},
            "TSLA": {"ticker": "TSLA", "name": "Tesla, Inc."},
            "NVDA": {"ticker": "NVDA", "name": "NVIDIA Corporation"},
        }

    return index


def get_stock_index():
    """Lazy-load stock index to avoid Firestore connection at module import time."""
    global STOCK_INDEX, _TICKER_TO_NAME, _NAME_CHOICES, _TICKER_CHOICES
    if 'STOCK_INDEX' not in globals() or STOCK_INDEX is None:
        STOCK_INDEX = load_stock_index_firestore()
        _TICKER_TO_NAME = {t: v.get("name") or t for t, v in STOCK_INDEX.items()}
        _NAME_CHOICES = list(_TICKER_TO_NAME.values())
        _TICKER_CHOICES = list(_TICKER_TO_NAME.keys())
    return STOCK_INDEX


# Initialize these as None - they'll be lazy-loaded when needed
STOCK_INDEX = None
_TICKER_TO_NAME = {}
_NAME_CHOICES = []
_TICKER_CHOICES = []


@dataclass
class ParsedInput:
    raw: str
    normalized: str
    intent: str
    tickers: List[str]
    companies: List[str]
    ticker_confidences: Dict[str, float]
    follow_up: Optional[str]
    extras: Dict[str, Any]
    can_handle: bool = True  # Whether the system can handle this query
    out_of_scope_message: Optional[str] = None  # Message for out-of-scope queries


def get_pfs_aware_response(text: str, user_id: str, conversation_history: Optional[List[Dict]] = None) -> str:
    """
    Generate a response that incorporates the user's PFS data for personalized financial guidance.
    
    Args:
        text: User's query
        user_id: User identifier to fetch PFS
        conversation_history: Previous conversation for context
        
    Returns:
        Personalized response with PFS insights
    """
    import openai
    
    try:
        # Fetch user's PFS data
        pfs_funcs = get_pfs_functions()
        latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id) if user_id else None
        
        # Fetch historical data for trend analysis
        net_worth_series = pfs_funcs.get('get_net_worth_series_for_user', lambda x, limit=10: [])(user_id, limit=10) if user_id else []
        
        # Build PFS context
        pfs_context = ""
        if latest_pfs:
            # Calculate totals (not stored as attributes)
            total_assets = (latest_pfs.cash_and_equivalents + latest_pfs.investments + 
                          latest_pfs.real_estate + latest_pfs.other_assets)
            total_liabilities = (latest_pfs.short_term_debt + latest_pfs.long_term_debt + 
                               latest_pfs.other_liabilities)
            monthly_expenses = latest_pfs.fixed_expenses + latest_pfs.variable_expenses
            
            # Get user's currency preference
            user_currency = latest_pfs.currency if hasattr(latest_pfs, 'currency') and latest_pfs.currency else "USD"
            
            pfs_context = f"""
USER'S FINANCIAL PROFILE (CURRENT):
- Net Worth: {format_currency(latest_pfs.net_worth, user_currency)} (Assets: {format_currency(total_assets, user_currency)}, Liabilities: {format_currency(total_liabilities, user_currency)})
- Monthly Income: {format_currency(latest_pfs.net_income, user_currency)}
- Monthly Expenses: {format_currency(monthly_expenses, user_currency)}
- Monthly Savings: {format_currency(latest_pfs.monthly_savings, user_currency)} ({latest_pfs.savings_rate:.1f}% savings rate)
- Investments: {format_currency(latest_pfs.investments, user_currency)}
- Cash & Equivalents: {format_currency(latest_pfs.cash_and_equivalents, user_currency)}
- Total Debt: {format_currency(total_liabilities, user_currency)}
- Risk Tolerance: {latest_pfs.risk_tolerance or 'Not specified'}
- Investment Horizon: {latest_pfs.investment_horizon_years or 'Not specified'} years
- Goal: {latest_pfs.goal_type or 'Not specified'}

"""
            
            # Add historical trend data if available
            if net_worth_series and len(net_worth_series) > 1:
                pfs_context += f"""
HISTORICAL TREND DATA ({len(net_worth_series)} data points):
"""
                for idx, point in enumerate(net_worth_series):
                    pfs_context += f"- {point['created_at'][:10]}: Net Worth {format_currency(point['net_worth'], user_currency)}, Savings Rate {point['savings_rate']:.1f}%\n"
                
                # Calculate growth if we have at least 2 points
                first_nw = net_worth_series[0]['net_worth']
                last_nw = net_worth_series[-1]['net_worth']
                if first_nw > 0:
                    growth_pct = ((last_nw - first_nw) / first_nw) * 100
                    pfs_context += f"\nOverall Change: {format_currency(last_nw - first_nw, user_currency)} ({growth_pct:+.1f}%)\n"
            elif net_worth_series and len(net_worth_series) == 1:
                pfs_context += "\nNote: Only one financial snapshot available. Track over time by updating your profile regularly.\n"
            
            pfs_context += "\nUse this data to provide PERSONALIZED insights specific to the user's situation and trends."
        else:
            # No PFS found - return a clear message instead of asking LLM to generate one
            return """I'd love to provide personalized insights about your financial profile, but I don't see any financial data saved yet.

📊 **To get personalized analysis:**
1. Go to the **Profile** page (in the sidebar)
2. Enter your financial information (income, expenses, assets, liabilities)
3. Save your profile
4. Come back and ask again!

Once I have your data, I can tell you exactly how you're trending and provide tailored recommendations."""
        
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Include portfolio context if available
        portfolio_info = st.session_state.get("portfolio_summary")
        portfolio_text = ""
        if portfolio_info:
            total_val = portfolio_info.get("total_value", 0)
            holdings = portfolio_info.get("holdings", [])
            # Get user's currency from PFS
            user_currency = latest_pfs.currency if latest_pfs and hasattr(latest_pfs, 'currency') and latest_pfs.currency else "USD"
            portfolio_text = f"\n\nUSER'S PORTFOLIO (Total Value: {format_currency(total_val, user_currency)}):\n"
            for h in holdings[:10]:
                ticker = h.get("ticker", "")
                value = h.get("market_value", 0)
                portfolio_text += f"  - {ticker}: {format_currency(value, user_currency)}\n"
        
        system_prompt = f"""You are a knowledgeable investment copilot. Answer the user's question using their actual financial data.

{pfs_context}
{portfolio_text}

FORMATTING REQUIREMENTS:
- Use proper spacing between all words and numbers
- Format numbers with commas: $10,000 not $10000
- Always include spaces before and after numbers in sentences
- Use markdown formatting consistently (bold with **, lists with -, etc.)
- Break content into readable paragraphs

Provide actionable, personalized insights based on their specific numbers. Be encouraging but realistic. Keep response under 300 words."""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history for context
        if conversation_history:
            for msg in conversation_history[-4:]:
                role = "assistant" if msg.get("role") == "assistant" else "user"
                messages.append({"role": role, "content": msg.get("text", "")})
        
        messages.append({"role": "user", "content": text})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=400
        )
        
        personalized_answer = response.choices[0].message.content.strip()
        
        return personalized_answer
        
    except Exception as e:
        import traceback
        print(f"PFS-aware response error: {e}")
        print(traceback.format_exc())
        
        # More specific error message
        if "user_id" in str(e).lower() or not user_id:
            return "I need you to be logged in to access your financial profile. Please sign in first."
        else:
            return f"I encountered an issue while analyzing your financial data. Error: {str(e)}\n\nPlease try again, or ask me a general investment question."


def get_general_llm_response(text: str, conversation_history: Optional[List[Dict]] = None) -> str:
    """
    Get a general LLM response for out-of-scope queries with a disclaimer.
    
    Args:
        text: User's query
        conversation_history: Previous conversation for context
        
    Returns:
        Response string with disclaimer
    """
    import openai
    
    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        system_prompt = """You are a helpful AI assistant. The user has asked a question that is outside the scope of an investment copilot system, but you can still provide a helpful general response.

FORMATTING REQUIREMENTS:
- Use proper spacing between all words and numbers
- Format numbers with commas where appropriate
- Use markdown formatting consistently (bold with **, lists with -, etc.)
- Break content into readable paragraphs

Be concise, informative, and helpful. Keep responses under 200 words unless more detail is specifically requested."""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history for context
        if conversation_history:
            for msg in conversation_history[-4:]:
                role = "assistant" if msg.get("role") == "assistant" else "user"
                messages.append({"role": role, "content": msg.get("text", "")})
        
        messages.append({"role": "user", "content": text})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=300
        )
        
        general_answer = response.choices[0].message.content.strip()
        
        # Add disclaimer
        return f"ℹ️ **Note:** This question is outside my investment analysis expertise, but here's a general response:\n\n{general_answer}\n\n---\n💡 I specialize in stock analysis, portfolio strategy, and investment guidance. Would you like help with any of these?"
        
    except Exception as e:
        print(f"General LLM response error: {e}")
        return "I apologize, but this question is outside my investment analysis capabilities. I specialize in:\n• Stock analysis and recommendations\n• Portfolio strategy\n• Comparing investment options\n• General investment guidance\n\nWould you like help with any of these?"


def analyze_user_intent_with_llm(text: str, conversation_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """
    Use OpenAI LLM to deeply understand user intent and extract relevant entities.
    This provides better context understanding than keyword matching.
    
    Args:
        text: Current user input
        conversation_history: Previous conversation messages for context
    
    Returns:
        Dict with keys: intent, tickers, companies, can_handle, explanation, follow_up
    """
    import openai
    
    system_prompt = """You are an intelligent intent classifier for an investment copilot assistant.

Your capabilities include:
1. Analyzing individual stocks (ticker analysis)
2. Comparing multiple stocks (ticker comparison)
3. Creating portfolio strategies (portfolio_request)
4. Analyzing existing portfolios (portfolio_analysis)
5. Answering general investment questions (general)
6. Analyzing user's financial health using their Personal Financial Statement (PFS) data

CRITICAL: Distinguish between creating NEW portfolios vs analyzing EXISTING portfolios:

portfolio_request (creating new portfolio):
- "Help me with an investment plan" (portfolio_request)
- "Create a portfolio for me" (portfolio_request)
- "What should my asset allocation be?" (portfolio_request)
- "Suggest a balanced portfolio" (portfolio_request)
- "I have $1000. Help me invest..." (portfolio_request)
- "Where should I invest my money?" (portfolio_request)
- "Recommend allocation based on my situation" (portfolio_request)
- "How should I split my money between stocks and bonds?" (portfolio_request)

portfolio_analysis (analyzing existing portfolio):
- "Analyze my portfolio" (portfolio_analysis)
- "Review my holdings" (portfolio_analysis)
- "What do you think of my portfolio?" (portfolio_analysis)
- "Should I rebalance?" (portfolio_analysis)
- "Am I too concentrated in tech?" (portfolio_analysis)
- "Is my portfolio diversified enough?" (portfolio_analysis)
- "What should I sell from my portfolio?" (portfolio_analysis)
- "Rate my portfolio" (portfolio_analysis)

CRITICAL: Queries about the user's own finances ARE IN-SCOPE and require PFS, classify as general with requires_pfs=true:
- "Am I building wealth at a healthy pace?" (general - use PFS)
- "How is my financial profile trending?" (general - use PFS)
- "Am I moving in a positive direction financially?" (general - use PFS)
- "Look at my monthly savings..." (general - use PFS)
- "Am I setting myself up for long-term success?" (general - use PFS)
- "Check my savings rate" (general - use PFS)
- "Review my financial situation" (general - use PFS)
- "Based on my net worth/savings/income..." (general - use PFS)
- "Should I invest more or pay down debt?" (general - use PFS)
- "How am I doing financially?" (general - use PFS)
- "Can I afford to invest in X?" (general - use PFS)
- "What's my financial health?" (general - use PFS)
- "Am I on track for retirement?" (general - use PFS)

IMPORTANT: Consider conversation history. If the user's message is a follow-up (e.g., "what about its dividend?", "compare it with", "how much should I invest?"), treat it as continuing the previous topic and maintain context from earlier messages.

CRITICAL: Handle short affirmative/negative responses to follow-up questions:
- If the previous assistant message ended with a question mark AND the user responds with a short answer (Yes, No, Sure, OK, Please, etc.), interpret it as answering that question
- "Yes" / "Sure" / "OK" / "Please" / "Go ahead" → user is affirmatively responding to the last question
- "No" / "Not now" / "Skip" → user is declining the follow-up
- Extract the intent from the previous question and reformulate the user's response accordingly

Analyze the user's query and respond with a JSON object:
{
    "intent": "ticker_analysis|ticker_comparison|portfolio_request|portfolio_analysis|general|out_of_scope",
    "tickers": ["AAPL", "MSFT"],  // Empty array if none
    "companies": ["Apple Inc.", "Microsoft"],  // Company names mentioned
    "can_handle": true|false,  // false if query is outside capabilities
    "requires_pfs": true|false,  // true if query needs user's financial profile data
    "explanation": "Brief explanation of what user wants",
    "confidence": 0.0-1.0,  // Confidence in classification
    "follow_up": "Clarifying question if needed (null if not needed)"
}

Out-of-scope queries include:
- Cryptocurrency/forex trading
- Real estate investment (unless asking about REITs)
- Legal/tax advice (specific regulatory questions)
- Technical issues with platforms
- General knowledge completely unrelated to investments/finance

For out-of-scope queries, set can_handle=false and provide a polite explanation."""

    try:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Build messages with conversation history for context
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add recent conversation history (last 4 messages for context)
        if conversation_history:
            for msg in conversation_history[-4:]:
                role = "assistant" if msg.get("role") == "assistant" else "user"
                messages.append({"role": role, "content": msg.get("text", "")})
        
        # Add current user input
        messages.append({"role": "user", "content": text})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        result = response.choices[0].message.content
        import json
        parsed = json.loads(result)
        
        # Normalize tickers to uppercase
        parsed["tickers"] = [t.upper() for t in parsed.get("tickers", [])]
        
        return parsed
        
    except Exception as e:
        print(f"LLM intent analysis error: {e}")
        # Fallback to simple classification
        return {
            "intent": "general",
            "tickers": [],
            "companies": [],
            "can_handle": True,
            "explanation": "Processing query with basic analysis",
            "confidence": 0.5,
            "follow_up": None
        }

def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    s = re.sub(r"[^\w\s\$\.\&%\'-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

_TICKER_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
_UPPER_RE = re.compile(r"\b([A-Z]{2,5})\b")

def extract_explicit_tickers(text: str) -> List[str]:
    out = []
    for m in _TICKER_RE.finditer(text):
        out.append(m.group(1).upper())
    for m in _UPPER_RE.finditer(text):
        tok = m.group(1).upper()
        out.append(tok)
    seen = set(); res = []
    for t in out:
        if t not in seen:
            seen.add(t); res.append(t)
    return res

def extract_company_names(text: str) -> List[str]:
    if _SPACY:
        try:
            doc = _SPACY(text)
            names = [ent.text for ent in doc.ents if ent.label_ in ("ORG","PRODUCT","PERSON")]
            if names:
                return names
        except Exception:
            pass
    matches = re.findall(r"\b([A-Z][a-z]{1,}\s(?:[A-Z][a-z]{1,}\s?){0,3})", text)
    return [m.strip() for m in matches]

def fuzzy_match_company_to_ticker(name: str, top_n: int = 3) -> List[Tuple[str, float]]:
    name = (name or "").strip()
    if not name:
        return []
    # Lazy-load stock index
    get_stock_index()
    for t, n in _TICKER_TO_NAME.items():
        if name.lower() == n.lower():
            return [(t, 100.0)]
    if rf_process:
        try:
            name_map = {v: k for k,v in _TICKER_TO_NAME.items()}
            results = rf_process.extract(name, list(name_map.keys()), scorer=rf_fuzz.token_sort_ratio, limit=top_n)
            out = []
            for match_name, score, _ in results:
                out.append((name_map[match_name], float(score)))
            return out
        except Exception:
            pass
    out = []
    lname = name.lower()
    for t, n in _TICKER_TO_NAME.items():
        ln = n.lower()
        score = 0.0
        if lname in ln or ln in lname:
            score = 80.0
        else:
            sset = set(lname.split()); nset = set(ln.split())
            common = sset & nset
            if common:
                score = 50.0 + 10.0 * len(common)
        if score > 0:
            out.append((t, score))
    out.sort(key=lambda x: -x[1])
    return out[:top_n]

def detect_intent_from_text(text: str) -> str:
    t = (text or "").lower()
    if any(kw in t for kw in ["portfolio","asset allocation","balanced","allocation"]):
        return "portfolio_request"
    if re.search(r"\b(compare| versus | vs | which is better)\b", t):
        return "ticker_comparison"
    if re.search(r"\b(analyz|analy|review|buy|sell|valuation|hold)\b", t):
        return "candidate_ticker_analysis"
    return "general"

def process_user_input(text: str, use_llm: bool = True, conversation_history: Optional[List[Dict]] = None) -> ParsedInput:
    """
    Enhanced user input processing with LLM-based intent understanding.
    Falls back to keyword-based approach if LLM fails.
    
    Args:
        text: User's input text
        use_llm: Whether to use LLM for intent analysis (default: True)
        conversation_history: Previous conversation messages for context
    
    Returns:
        ParsedInput object with intent, tickers, and scope information
    """
    raw = text or ""
    norm = normalize_text(raw)
    
    # Handle short affirmative/negative responses to follow-up questions using stored context
    short_response_patterns = r"^\s*(yes|yeah|yep|sure|ok|okay|please|go ahead|absolutely|definitely|no|nope|not now|skip|maybe later)\s*[.!?]?\s*$"
    if re.match(short_response_patterns, norm, re.IGNORECASE):
        is_affirmative = re.match(r"^\s*(yes|yeah|yep|sure|ok|okay|please|go ahead|absolutely|definitely)\s*[.!?]?\s*$", norm, re.IGNORECASE)
        
        # Check if we have stored follow-up context in session state
        followup_context = st.session_state.get("last_followup_context")
        
        if is_affirmative and followup_context:
            # User said yes - reformulate based on stored context
            action = followup_context.get("action")
            ticker = followup_context.get("ticker", "")
            
            # Map actions to clear user queries
            action_queries = {
                "compare_peers": f"Compare {ticker} with similar stocks in the same sector",
                "portfolio_fit": f"Show me how {ticker} fits into a diversified portfolio",
                "position_size": f"Help me determine the right position size for {ticker}",
                "risk_analysis": f"Analyze the risks and potential downsides of investing in {ticker}",
                "find_alternatives": f"Suggest alternative investments to replace {ticker}",
                "exit_timing": f"Analyze the optimal time to exit my {ticker} position",
                "better_matches": f"Find stocks that might better align with my goals than {ticker}",
                "setup_alerts": f"Set up alerts for key price levels and news about {ticker}",
                "scenario_analysis": f"Show what would happen to {ticker} if market conditions change",
                "allocation_strategy": "Suggest an allocation strategy between these stocks",
                "fit_analysis": "Analyze which stock fits better with my risk tolerance and time horizon",
                "compare_etfs": "Compare these stocks to relevant ETFs in the same sectors",
                "risk_factors": "Explain the key risk factors for each option",
                "suggest_instruments": "Suggest specific ETFs or stocks to implement this allocation",
                "rebalancing_schedule": "Help me create a rebalancing schedule",
                "historical_performance": "Show how this portfolio has performed historically",
                "goal_alignment": "Analyze how this allocation aligns with my financial goals",
                "setup_profile": "Help me set up my financial profile",
                "review_profile": "Review my financial profile and suggest investment opportunities",
                "explain_reasoning": f"Explain the reasoning behind the recommendation for {ticker} in more detail",
                "analyze_or_strategy": "Help me choose - should I analyze a specific stock or create a portfolio strategy?",
                "compare_stocks": "Help me compare a few stocks to see which fits my goals best",
            }
            
            if action in action_queries:
                raw = action_queries[action]
                norm = normalize_text(raw)
                # Clear the context after using it
                st.session_state.last_followup_context = None
        elif not is_affirmative and followup_context:
            # User declined - clear context and treat as general conversation
            st.session_state.last_followup_context = None
    
    # Try LLM-based analysis first
    llm_result = None
    if use_llm and os.getenv("OPENAI_API_KEY"):
        try:
            llm_result = analyze_user_intent_with_llm(raw)
        except Exception as e:
            print(f"LLM analysis failed, falling back to keyword matching: {e}")
    
    # Use LLM results if available and confident
    if llm_result and llm_result.get("confidence", 0) > 0.6:
        intent = llm_result.get("intent", "general")
        tickers = llm_result.get("tickers", [])
        companies = llm_result.get("companies", [])
        can_handle = llm_result.get("can_handle", True)
        follow_up = llm_result.get("follow_up")
        requires_pfs = llm_result.get("requires_pfs", False)
        
        # Lazy-load stock index
        get_stock_index()
        
        # Validate tickers exist
        validated_tickers = []
        ticker_confidences = {}
        for t in tickers:
            if t.upper() in _TICKER_TO_NAME or get_profile_cached(t):
                validated_tickers.append(t.upper())
                ticker_confidences[t.upper()] = 0.9
        
        # Handle out-of-scope queries - pass to general LLM for helpful response
        if not can_handle or intent == "out_of_scope":
            explanation = llm_result.get("explanation", "I'm unable to help with this request.")
            general_response = get_general_llm_response(raw, conversation_history)
            
            return ParsedInput(
                raw=raw,
                normalized=norm,
                intent="out_of_scope",
                tickers=[],
                companies=companies,
                ticker_confidences={},
                follow_up=None,
                extras={"llm_explanation": explanation, "general_response": general_response},
                can_handle=False,
                out_of_scope_message=general_response
            )
        
        return ParsedInput(
            raw=raw,
            normalized=norm,
            intent=intent,
            tickers=validated_tickers,
            companies=companies,
            ticker_confidences=ticker_confidences,
            follow_up=follow_up,
            extras={
                "llm_confidence": llm_result.get("confidence"), 
                "llm_explanation": llm_result.get("explanation"),
                "requires_pfs": requires_pfs
            },
            can_handle=True
        )
    
    # Fallback to keyword-based approach
    intent_guess = detect_intent_from_text(norm)
    explicit = extract_explicit_tickers(raw)
    companies = extract_company_names(raw)
    ticker_candidates = {}
    
    for comp in companies:
        matches = fuzzy_match_company_to_ticker(comp, top_n=3)
        for t, score in matches:
            prev = ticker_candidates.get(t, 0.0)
            ticker_candidates[t] = max(prev, score)
    
    for t in explicit:
        ticker_candidates[t] = max(ticker_candidates.get(t, 0.0), 95.0)
    
    tickers_sorted = sorted(ticker_candidates.items(), key=lambda x: -x[1])
    tickers = [t for t, s in tickers_sorted]
    confidences = {t: s/100.0 for t, s in ticker_candidates.items()}
    
    if intent_guess in ("candidate_ticker_analysis",) and tickers:
        intent_final = "ticker_analysis"
    elif intent_guess == "ticker_comparison" and len(tickers) >= 2:
        intent_final = "ticker_comparison"
    else:
        intent_final = intent_guess
    
    follow_up = None
    if intent_final == "ticker_analysis" and not tickers:
        follow_up = "Which ticker would you like me to analyze?"
    if intent_final == "ticker_comparison" and len(tickers) < 2:
        follow_up = "Which two or more tickers should I compare?"
    
    return ParsedInput(
        raw=raw,
        normalized=norm,
        intent=intent_final,
        tickers=tickers,
        companies=companies,
        ticker_confidences=confidences,
        follow_up=follow_up,
        extras={"method": "keyword_fallback"},
        can_handle=True
    )
# ======= end NLP block =======

def format_valuation_response(result, proposal=None):
    current_price = result.get('currentPrice', 0)
    giv = result.get('GIV', 0)
    dcf = result.get('DCF', 0)
    ddm = result.get('DDM', 0)
    mvm = result.get('MVM', 0)
    perfient_intrinsic = result.get('perfientIntrinsic', 0)
    
    # Start building the response
    response_parts = []
    
    response_parts.append(f"""📊 **Stock Valuation Report for {result.get('ticker', 'N/A')}**

**Company:** {result.get('company', 'N/A')}  
**Current Price:** ${current_price:.2f}

**Intrinsic Value Models:**
- **GIV (Graham Intrinsic Value):** ${giv:.2f}
- **DCF (Discounted Cash Flow):** ${dcf:.2f}
- **DDM (Dividend Discount Model):** ${ddm:.2f}
- **MVM (Multiple Valuation Model):** ${mvm:.2f}

**Perfient Intrinsic Value:** ${perfient_intrinsic:.2f}
*Median of all models with 20% margin of safety*

**Price Levels:**
- **52 Week High:** {result.get('52wHigh', 'N/A')}
- **52 Week Low:** {result.get('52wLow', 'N/A')}
""")
    
    # Add peers section if action is HOLD or SELL
    if proposal:
        action = proposal.get('action', '').upper()
        if action in ['HOLD', 'SELL']:
            peer_valuations = result.get('peerValuations', [])
            if peer_valuations and len(peer_valuations) > 0:
                # Filter peers to only show BUY recommendations (undervalued: perfient_intrinsic > current_price)
                buy_peers = []
                for peer in peer_valuations:
                    peer_perfient = peer.get('perfientIntrinsic', 0)
                    peer_price = peer.get('currentPrice', 0)
                    if peer_perfient > 0 and peer_price > 0 and peer_perfient > peer_price:
                        buy_peers.append(peer)
                
                if buy_peers:
                    response_parts.append("\n**Peers to Consider:**")
                    # Show top 5 BUY-worthy peers with their tickers and Perfient intrinsic values
                    for peer in buy_peers[:5]:
                        peer_ticker = peer.get('ticker', 'N/A')
                        peer_company = peer.get('company', peer_ticker)
                        peer_perfient = peer.get('perfientIntrinsic', 0)
                        peer_price = peer.get('currentPrice', 0)
                        
                        # Calculate discount/premium
                        discount_pct = ((peer_perfient - peer_price) / peer_perfient) * 100
                        discount_text = f"{discount_pct:+.1f}% vs intrinsic"
                        response_parts.append(f"- **{peer_ticker}** ({peer_company}): ${peer_price:.2f} - Perfient Intrinsic: ${peer_perfient:.2f} ({discount_text})")
                    
                    response_parts.append("")
                else:
                    # No undervalued peers found
                    response_parts.append("\n**Peers to Consider:**")
                    response_parts.append("*Industry peers appear overvalued as well and are not considerable at the moment.*\n")
    
    return "\n".join(response_parts)



# Handle pending quick prompt click
if st.session_state.get("pending_quick_prompt"):
    prompt_text = st.session_state.pending_quick_prompt
    st.session_state.pending_quick_prompt = None
    append_history("user", prompt_text)
    handle_user_message(prompt_text)
    st.rerun()

# If new user message was added, process last message
if st.session_state.history and st.session_state.history[-1]["role"] == "user":
    last = st.session_state.history[-1]["text"]
    # Use enhanced handler which manages dialog continuation and intent routing
    handle_user_message(last)
    st.rerun()

if st.session_state.dev_mode and st.session_state.get("last_proposal"):
    last_decision_id = st.session_state.last_proposal.get("decision_id")
    if last_decision_id:
        db_fs = get_firestore_client()
        doc = db_fs.collection("users").document(st.session_state.get("current_user_id") or "anonymous").collection("decisions").document(last_decision_id).get()
        if doc.exists:
            decision_doc = doc.to_dict()
            st.subheader("Developer Trace")
            st.json(decision_doc.get("trace", {}))
        else:
            st.write("No trace doc found for last decision.")
    else:
        st.write("No last decision id available.")

# Right column: quick controls & confirm trade
#with col2:        
#    if st.session_state.get("pfs_warning_flag"):
#        st.subheader("Your profile")
#        # This shows a clickable link to the Profile page
#        st.page_link("pages/01_Profile.py", label="View / edit financial profile", icon="👤")
#        render_profile_status()
#        # Small warning badge if user asked for PFS-aware advice but no profile exists
#        st.markdown(
#            """
#            <div style="
#                margin-top: 6px;
#                padding: 6px 10px;
#                border-radius: 999px;
#                border: 1px solid rgba(245,158,11,0.9);
#                background: rgba(251,191,36,0.10);
#                font-size: 12px;
#            ">
#                ⚠️ You asked for advice based on your financial profile,<br/>
#                but no profile is set up yet. Open the <b>Profile</b> page<br/>
#                to create one so I can personalize suggestions.
#            </div>
#            """,
#            unsafe_allow_html=True,
#        )
#    if st.session_state.get("history"):
#        st.markdown("---")
#        st.subheader("Last proposal")
#        if st.session_state.last_proposal:
#            lp = st.session_state.last_proposal            
#            st.metric("Fit score", f"{lp.get('fit_score',0):.2f}")
#            st.write("Base score:", f"{lp.get('base_score',0):.1f}/100")
#            if lp and isinstance(lp, dict):
#                lp = lp or {}
#                st.write(lp.get("proposal", {}).get("explain", ""))                
#            else:
#                st.write("")  # or debug message
#            st.write(lp)
#            out = lp.get('fit_output')  # store perfient_fit_score output in last_proposal
#            if out:
#                st.metric("Fit", f"{out['fit']:.2f}")
#                with st.expander("Why this fit?"):
#                    st.write(out['explain'])
#                    st.json(out['components'])
#            if lp["proposal"]["action"] == "BUY":
#                if st.button("Confirm BUY (paper)"):
#                    res = place_order_buy(lp["ticker"], lp["proposal"]["qty"])
#                    st.success(f"Order submitted: {res}")
#            elif lp["proposal"]["action"] == "SELL":
#                if st.button("Confirm SELL (paper)"):
#                    res = place_order_sell(lp["ticker"], (lp["proposal"]["qty"] if isinstance(lp["proposal"]["qty"], int) else 0))
#                    st.success(f"Order submitted: {res}")
#        else:
#            st.info("No trade proposals yet.")

#        st.markdown("---")
#        st.write("Session logs")
#        if st.button("Clear chat"):
#            st.session_state.history = []
#            st.session_state.last_proposal = None
#            st.rerun()



# ------------------ INPUT AREA (Centered before first message; bottom afterwards) ------------------

# If the user has NOT started a conversation:
if not st.session_state.get("history"): 
    # Center wrapper
    st.markdown(
        "<div style='display:flex;justify-content:center;margin-top:40px;'>",
        unsafe_allow_html=True
    )
    cols_center = st.columns([1, 2, 1])

    with cols_center[1]:
        # Centered input box
        prompt = st.chat_input(
            "Type a ticker or question (e.g., 'Analyze TSLA' or 'What should I do with my AAPL?')",
            key="center_input"
        )

        if prompt:
            append_history("user", prompt)
            st.rerun()

        # Quick prompts shown ONLY before first message
        st.markdown(
            "<div style='display:flex;justify-content:center;margin-top:12px;'>",
            unsafe_allow_html=True
        )
        render_quick_prompts()   # horizontally placed quick prompts
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)



# Once conversation has begun:
else:
    prompt = st.chat_input(
        "Type a ticker or question (e.g., 'Analyze TSLA' or 'What should I do with my AAPL?')",
        key="bottom_input"
    )
    if prompt:
        append_history("user", prompt)
        st.rerun()

st.markdown(
    "[🔒 Trust & Data Usage](Trust_&_Data_Usage)"
)