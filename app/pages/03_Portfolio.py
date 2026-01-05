# app/pages/Portfolio.py

import os
import streamlit as st
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.utils import fetch_latest_price, fetch_company_profile, fetch_tiingo_search, detect_ticker_type
from google.cloud import firestore
import time
import openai
from app.auth_check import require_authentication

# Check if encryption is available
try:
    from app.encryption import encrypt_portfolio, decrypt_portfolio
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

# ============================================
# Firestore Client
# ============================================
@st.cache_resource
def get_firestore_client():
    """Cached Firestore client connection."""
    return firestore.Client()

# ============================================
# Portfolio File Parsing
# ============================================
def load_portfolio_file(file) -> Optional[pd.DataFrame]:
    """
    Parse uploaded portfolio file (CSV or Excel).
    
    Expected columns:
    - ticker (required)
    - quantity (required)
    - avg_price (optional but recommended)
    - currency (optional, defaults to USD)
    """
    try:
        if file.name.endswith(".csv"):
            df = pd.read_csv(file)
        elif file.name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(file)
        else:
            return None
        
        # Normalize column names
        df.columns = df.columns.str.lower().str.strip()
        
        return df
    except Exception as e:
        st.error(f"Error loading file: {e}")
        return None

def validate_portfolio_df(df: pd.DataFrame) -> tuple[bool, str]:
    """
    Validate portfolio dataframe has required columns.
    
    Returns:
        (is_valid, error_message)
    """
    required_cols = {"ticker", "quantity"}
    actual_cols = set(df.columns.str.lower())
    missing = required_cols - actual_cols
    
    if missing:
        return False, f"Missing required columns: {', '.join(missing)}"
    
    # Check for empty tickers
    if df["ticker"].isna().any() or (df["ticker"] == "").any():
        return False, "Some rows have empty ticker symbols"
    
    # Check for non-positive quantities
    if (df["quantity"] <= 0).any():
        return False, "All quantities must be positive numbers"
    
    return True, ""

# ============================================
# Market Data Fetching
# ============================================
@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_current_prices(tickers: List[str]) -> Dict[str, float]:
    """
    Fetch current prices for list of tickers using Tiingo-backed helper.

    Returns:
        Dictionary mapping ticker -> current price
    """
    prices = {}

    for ticker in tickers:
        try:
            p = fetch_latest_price(ticker.upper())
            prices[ticker.upper()] = p
        except Exception as e:
            print(f"Error fetching price for {ticker}: {e}")
            prices[ticker.upper()] = None

    return prices

def is_etf(ticker: str) -> bool:
    """
    Detect if a ticker is an ETF using Tiingo/heuristics.
    """
    try:
        det = detect_ticker_type(ticker)
        return det.get('type') == 'ETF'
    except Exception:
        return False

@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_stock_info(ticker: str) -> Optional[Dict[str, Any]]:
    """
    Fetch stock or ETF metadata using Tiingo search results.
    """
    try:
        ti = fetch_tiingo_search(ticker)
        match = ti.get('match') if ti else None
        if not match:
            return {
                "name": ticker,
                "sector": "Unknown",
                "industry": "Unknown",
                "currency": "USD",
                "asset_type": "Unknown",
                "etf_category": None,
            }
        asset_type = match.get('assetType', '')
        is_etf_flag = str(asset_type).upper() == 'ETF'
        if is_etf_flag:
            return {
                "name": match.get('name', ticker),
                "sector": "ETF",
                "industry": match.get('assetType', "ETF"),
                "currency": match.get('exchangeCountry', "USD") or "USD",
                "asset_type": "ETF",
                "etf_category": match.get('fundCategory') or None,
            }
        else:
            return {
                "name": match.get('name', ticker),
                "sector": match.get('sector', "Unknown"),
                "industry": match.get('industry', "Unknown"),
                "currency": match.get('exchangeCountry', "USD") or "USD",
                "asset_type": "Stock",
                "etf_category": None,
            }
    except Exception as e:
        print(f"Error fetching info for {ticker}: {e}")
        return {
            "name": ticker,
            "sector": "Unknown",
            "industry": "Unknown",
            "currency": "USD",
            "asset_type": "Unknown",
            "etf_category": None,
        }

# ============================================
# Portfolio Analytics
# ============================================
def enrich_portfolio_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add market data and analytics to portfolio dataframe.
    
    Adds columns:
    - current_price: Latest market price
    - market_value: quantity * current_price
    - cost_basis: quantity * avg_price (if avg_price provided)
    - gain_loss: market_value - cost_basis
    - gain_loss_pct: (market_value - cost_basis) / cost_basis
    - name: Company name
    - sector: Company sector
    """
    enriched = df.copy()
    
    # Fetch current prices
    tickers = enriched["ticker"].str.upper().unique().tolist()
    prices = fetch_current_prices(tickers)
    
    # Add price data
    enriched["ticker"] = enriched["ticker"].str.upper()
    enriched["current_price"] = enriched["ticker"].map(prices)
    
    # Calculate market value
    enriched["market_value"] = enriched["quantity"] * enriched["current_price"]
    
    # Add cost basis and gains if avg_price provided
    if "avg_price" in enriched.columns:
        enriched["cost_basis"] = enriched["quantity"] * enriched["avg_price"]
        enriched["gain_loss"] = enriched["market_value"] - enriched["cost_basis"]
        enriched["gain_loss_pct"] = (enriched["gain_loss"] / enriched["cost_basis"]) * 100
    else:
        enriched["cost_basis"] = None
        enriched["gain_loss"] = None
        enriched["gain_loss_pct"] = None
    
    # Add company metadata (cached)
    info_list = []
    for ticker in enriched["ticker"]:
        info = fetch_stock_info(ticker)
        info_list.append(info)
    
    enriched["name"] = [info["name"] for info in info_list]
    enriched["sector"] = [info["sector"] for info in info_list]
    enriched["industry"] = [info["industry"] for info in info_list]
    enriched["asset_type"] = [info["asset_type"] for info in info_list]
    enriched["etf_category"] = [info["etf_category"] for info in info_list]
    
    return enriched

def calculate_portfolio_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate overall portfolio metrics.
    
    Returns:
        Dictionary with metrics like total value, allocation, risk concentration
    """
    total_value = df["market_value"].sum()
    
    # Allocation by position
    df_sorted = df.sort_values("market_value", ascending=False)
    df_sorted["weight_pct"] = (df_sorted["market_value"] / total_value) * 100
    
    # Sector allocation
    sector_alloc = df.groupby("sector")["market_value"].sum()
    sector_alloc_pct = (sector_alloc / total_value) * 100
    
    # Asset type allocation (Stocks vs ETFs)
    if "asset_type" in df.columns:
        asset_type_alloc = df.groupby("asset_type")["market_value"].sum()
        asset_type_alloc_pct = (asset_type_alloc / total_value) * 100
    else:
        asset_type_alloc_pct = pd.Series()
    
    # ETF category breakdown
    etfs_df = df[df["sector"] == "ETF"] if "sector" in df.columns else pd.DataFrame()
    if not etfs_df.empty and "etf_category" in etfs_df.columns:
        etf_category_alloc = etfs_df.groupby("etf_category")["market_value"].sum()
        etf_category_alloc_pct = (etf_category_alloc / total_value) * 100
    else:
        etf_category_alloc_pct = pd.Series()
    
    # Gains/losses (if avg_price provided)
    total_cost = df["cost_basis"].sum() if "cost_basis" in df.columns and df["cost_basis"].notna().any() else None
    total_gain = df["gain_loss"].sum() if "gain_loss" in df.columns and df["gain_loss"].notna().any() else None
    total_gain_pct = ((total_value - total_cost) / total_cost * 100) if total_cost and total_cost > 0 else None
    
    # Risk concentration (top 5 holdings)
    top_5_weight = df_sorted.head(5)["weight_pct"].sum()
    
    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "total_gain": total_gain,
        "total_gain_pct": total_gain_pct,
        "num_holdings": len(df),
        "num_stocks": len(df[df["sector"] != "ETF"]) if "sector" in df.columns else len(df),
        "num_etfs": len(etfs_df),
        "top_5_concentration": top_5_weight,
        "sector_allocation": sector_alloc_pct.to_dict(),
        "asset_type_allocation": asset_type_alloc_pct.to_dict(),
        "etf_category_allocation": etf_category_alloc_pct.to_dict(),
        "top_holdings": df_sorted.head(10),
    }

# ============================================
# Portfolio Persistence (Firestore)
# ============================================
def save_portfolio_to_firestore(user_id: str, portfolio_df: pd.DataFrame):
    """Save portfolio to Firestore for the given user (encrypted)."""
    try:
        db = get_firestore_client()
        
        # Convert dataframe to list of dicts
        portfolio_data = portfolio_df.to_dict(orient="records")
        
        # Prepare document
        doc_data = {
            "user_id": user_id,
            "holdings": portfolio_data,
            "last_updated": datetime.utcnow(),
        }
        
        # Encrypt sensitive portfolio data before storing
        if ENCRYPTION_AVAILABLE:
            try:
                doc_data = encrypt_portfolio(doc_data)
                import logging
                logging.info(f"Portfolio encrypted for user {user_id}")
            except Exception as e:
                import logging
                logging.error(f"Portfolio encryption failed, storing unencrypted: {e}")
        
        # Save to Firestore
        doc_ref = db.collection("portfolios").document(user_id)
        doc_ref.set(doc_data)
        
        return True
    except Exception as e:
        st.error(f"Error saving portfolio: {e}")
        return False

def load_portfolio_from_firestore(user_id: str) -> Optional[pd.DataFrame]:
    """Load saved portfolio from Firestore (decrypted if encrypted)."""
    try:
        db = get_firestore_client()
        doc_ref = db.collection("portfolios").document(user_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return None
        
        data = doc.to_dict()
        
        # Decrypt portfolio data if encrypted
        if ENCRYPTION_AVAILABLE and data.get("_encrypted", False):
            try:
                data = decrypt_portfolio(data)
            except Exception as e:
                import logging
                logging.error(f"Failed to decrypt portfolio for user {user_id}: {e}")
                st.error("Unable to decrypt portfolio data. Please contact support.")
                return None
        
        holdings = data.get("holdings", [])
        
        if not holdings:
            return None
        
        df = pd.DataFrame(holdings)
        return df
    except Exception as e:
        st.error(f"Error loading portfolio: {e}")
        return None

# ============================================
# UI Components
# ============================================
def render_portfolio_summary(metrics: Dict[str, Any]):
    """Display portfolio summary metrics in cards."""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Value", f"${metrics['total_value']:,.2f}")
    
    with col2:
        if metrics["total_cost"]:
            st.metric("Total Cost", f"${metrics['total_cost']:,.2f}")
        else:
            st.metric("Total Cost", "N/A")
    
    with col3:
        if metrics["total_gain"] is not None:
            delta_color = "normal" if metrics["total_gain"] >= 0 else "inverse"
            st.metric(
                "Total Gain/Loss",
                f"${metrics['total_gain']:,.2f}",
                f"{metrics['total_gain_pct']:.2f}%"
            )
        else:
            st.metric("Total Gain/Loss", "N/A")
    
    with col4:
        num_stocks = metrics.get("num_stocks", metrics["num_holdings"])
        num_etfs = metrics.get("num_etfs", 0)
        st.metric("Holdings", f"{metrics['num_holdings']} total")
        if num_etfs > 0:
            st.caption(f"📊 {num_stocks} stocks + {num_etfs} ETFs")

def render_asset_type_allocation(metrics: Dict[str, Any]):
    """Display asset type allocation (Stocks vs ETFs)."""
    asset_type_alloc = metrics.get("asset_type_allocation", {})
    
    if asset_type_alloc:
        st.subheader("📈 Asset Type Breakdown")
        
        asset_df = pd.DataFrame({
            "Asset Type": list(asset_type_alloc.keys()),
            "Weight (%)" : list(asset_type_alloc.values())
        }).sort_values("Weight (%)", ascending=False)
        
        st.bar_chart(asset_df.set_index("Asset Type"))
        
        # Display table with values
        total_value = metrics.get("total_value", 0)
        asset_df["Value"] = asset_df["Weight (%)"].apply(lambda x: f"${(x/100 * total_value):,.2f}")
        asset_df["Weight (%)"] = asset_df["Weight (%)"].apply(lambda x: f"{x:.2f}%")
        
        st.dataframe(
            asset_df,
            use_container_width=True,
            hide_index=True
        )
        
        # Show ETF category breakdown if available
        etf_category_alloc = metrics.get("etf_category_allocation", {})
        if etf_category_alloc:
            with st.expander("🔍 ETF Category Breakdown"):
                etf_cat_df = pd.DataFrame({
                    "ETF Category": list(etf_category_alloc.keys()),
                    "Weight (%)" : list(etf_category_alloc.values())
                }).sort_values("Weight (%)", ascending=False)
                
                etf_cat_df["Value"] = etf_cat_df["Weight (%)"].apply(lambda x: f"${(x/100 * total_value):,.2f}")
                etf_cat_df["Weight (%)"] = etf_cat_df["Weight (%)"].apply(lambda x: f"{x:.2f}%")
                
                st.dataframe(
                    etf_cat_df,
                    use_container_width=True,
                    hide_index=True
                )

def render_sector_allocation(metrics: Dict[str, Any]):
    """Display sector allocation chart (excluding ETFs from sector analysis)."""
    st.subheader("📊 Sector Allocation (Stocks)")
    
    sector_df = pd.DataFrame({
        "Sector": list(metrics["sector_allocation"].keys()),
        "Weight (%)": list(metrics["sector_allocation"].values())
    }).sort_values("Weight (%)", ascending=False)
    
    st.bar_chart(sector_df.set_index("Sector"))
    
    # Display table
    st.dataframe(
        sector_df.style.format({"Weight (%)": "{:.2f}%"}),
        use_container_width=True,
        hide_index=True
    )

def render_risk_analysis(metrics: Dict[str, Any]):
    """Display portfolio risk metrics."""
    st.subheader("⚠️ Risk Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("Top 5 Concentration", f"{metrics['top_5_concentration']:.1f}%")
        if metrics['top_5_concentration'] > 60:
            st.warning("⚠️ High concentration in top 5 holdings. Consider diversifying.")
        elif metrics['top_5_concentration'] > 40:
            st.info("ℹ️ Moderate concentration. Monitor top holdings.")
        else:
            st.success("✅ Well-diversified across holdings.")
    
    with col2:
        num_sectors = len(metrics["sector_allocation"])
        st.metric("Sector Diversity", f"{num_sectors} sectors")
        if num_sectors < 3:
            st.warning("⚠️ Limited sector diversity. Consider adding different sectors.")
        elif num_sectors < 5:
            st.info("ℹ️ Moderate sector diversity.")
        else:
            st.success("✅ Good sector diversification.")

def create_sample_csv() -> str:
    """Create sample portfolio CSV content with both stocks and ETFs."""
    sample_data = """ticker,quantity,avg_price
AAPL,10,145.50
MSFT,5,320.00
NVDA,3,450.25
GOOGL,8,125.75
VOO,15,400.00
QQQ,10,350.00
VTI,20,220.00"""
    return sample_data

def calculate_rebalancing_targets(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate rebalancing targets based on sector allocation drift.
    
    Returns:
        Dict with sector drift analysis and overweight/underweight recommendations
    """
    sector_allocation = metrics.get("sector_allocation", {})
    total_value = metrics.get("total_value", 0)
    
    if not sector_allocation or total_value == 0:
        return None
    
    # Define ideal target allocations (moderate risk profile)
    # These can be customized based on user's risk tolerance
    ideal_targets = {
        "Technology": 25.0,
        "Financial Services": 15.0,
        "Healthcare": 15.0,
        "Consumer Cyclical": 12.0,
        "Communication Services": 10.0,
        "Industrials": 10.0,
        "Consumer Defensive": 8.0,
        "Energy": 5.0,
        "Other": 0.0,  # Catch-all
    }
    
    # Calculate drift for each sector
    drifts = {}
    recommendations = []
    
    for sector, current_pct in sector_allocation.items():
        target_pct = ideal_targets.get(sector, 8.0)  # Default 8% for unspecified sectors
        drift = current_pct - target_pct
        current_value = (current_pct / 100) * total_value
        target_value = (target_pct / 100) * total_value
        diff_value = current_value - target_value
        
        drifts[sector] = {
            "current_pct": current_pct,
            "target_pct": target_pct,
            "drift_pct": drift,
            "current_value": current_value,
            "target_value": target_value,
            "diff_value": diff_value,
        }
        
        # Generate recommendations for significant drifts (>5% difference)
        if abs(drift) > 5.0:
            if drift > 0:
                recommendations.append({
                    "type": "reduce",
                    "sector": sector,
                    "message": f"**Overweight in {sector}**: Current {current_pct:.1f}% vs target {target_pct:.1f}%. Consider reducing by ${abs(diff_value):,.0f}.",
                    "severity": "high" if abs(drift) > 10 else "medium",
                })
            else:
                recommendations.append({
                    "type": "increase",
                    "sector": sector,
                    "message": f"**Underweight in {sector}**: Current {current_pct:.1f}% vs target {target_pct:.1f}%. Consider adding ${abs(diff_value):,.0f}.",
                    "severity": "high" if abs(drift) > 10 else "medium",
                })
    
    return {
        "drifts": drifts,
        "recommendations": recommendations,
        "total_value": total_value,
        "needs_rebalancing": len(recommendations) > 0,
    }

@st.cache_data(ttl=600)  # Cache for 10 minutes
def generate_ai_portfolio_recommendations(portfolio_df: pd.DataFrame, metrics: Dict[str, Any], user_id: str = None) -> Optional[str]:
    """
    Generate AI-powered portfolio recommendations using OpenAI.
    
    Returns:
        Markdown-formatted recommendation text
    """
    try:
        # Get user's PFS data if available
        pfs_context = ""
        if user_id:
            try:
                # Import PFS functions
                import sys
                sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from utils import get_pfs_functions
                
                pfs_funcs = get_pfs_functions()
                latest_pfs = pfs_funcs['get_latest_pfs_for_user'](user_id)
                
                if latest_pfs:
                    pfs_context = f"""
**User's Financial Profile:**
- Net Worth: ${latest_pfs.net_worth or 0:,.0f}
- Risk Tolerance: {latest_pfs.risk_tolerance or 'Moderate'}
- Investment Horizon: {latest_pfs.investment_horizon_years or 10} years
- Primary Goal: {latest_pfs.goal_type or 'Wealth Growth'}
"""
            except Exception:
                pass
        
        # Build portfolio context
        total_value = metrics.get("total_value", 0)
        sector_allocation = metrics.get("sector_allocation", {})
        top_5_concentration = metrics.get("top_5_concentration", 0)
        
        # Get top holdings
        top_holdings = portfolio_df.nlargest(5, "market_value")[["ticker", "market_value", "sector"]]
        holdings_text = "\n".join([
            f"  - {row['ticker']}: ${row['market_value']:,.0f} ({row['sector']})"
            for _, row in top_holdings.iterrows()
        ])
        
        sector_text = "\n".join([
            f"  - {sector}: {pct:.1f}%"
            for sector, pct in sorted(sector_allocation.items(), key=lambda x: x[1], reverse=True)
        ])
        
        portfolio_context = f"""
**Portfolio Summary:**
- Total Value: ${total_value:,.2f}
- Number of Holdings: {len(portfolio_df)}
- Top 5 Concentration: {top_5_concentration:.1f}%

**Top 5 Holdings:**
{holdings_text}

**Sector Allocation:**
{sector_text}
"""
        
        # Create prompt for AI
        system_prompt = f"""You are an expert portfolio advisor. Analyze the user's portfolio and provide specific, actionable recommendations.

{portfolio_context}
{pfs_context}

Provide recommendations in the following areas:
1. **Rebalancing**: Specific sectors or positions to adjust
2. **Diversification**: Areas where portfolio is overconcentrated
3. **Risk Management**: Concerns about volatility or sector exposure
4. **Opportunities**: Underweight sectors or themes to consider
5. **Specific Actions**: 2-3 concrete next steps (e.g., "Consider selling 20% of NVDA position")

FORMATTING REQUIREMENTS:
- Use proper spacing between all words and numbers
- Format numbers with commas: $10,000 not $10000
- Always include spaces before and after numbers in sentences
- Use markdown formatting consistently (bold with **, lists with -, etc.)
- Break content into readable paragraphs

Be specific with dollar amounts and percentages. Keep response under 400 words. Use markdown formatting with bullet points."""
        
        # Call OpenAI
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Provide detailed portfolio recommendations based on the data above."}
            ],
            temperature=0.7,
            max_tokens=600
        )
        
        return response.choices[0].message.content.strip()
    
    except Exception as e:
        st.error(f"Error generating AI recommendations: {e}")
        return None

def render_portfolio_recommendations(portfolio_df: pd.DataFrame, metrics: Dict[str, Any], user_id: str = None):
    """
    Render portfolio recommendations section with rebalancing suggestions.
    """
    st.subheader("💡 Portfolio Recommendations")
    
    # Calculate rebalancing targets
    rebalancing = calculate_rebalancing_targets(metrics)
    
    if rebalancing and rebalancing["needs_rebalancing"]:
        st.markdown("### 🎯 Rebalancing Suggestions")
        st.caption("Based on drift from target allocations for a moderate risk profile")
        
        # Show recommendations
        recommendations = rebalancing["recommendations"]
        
        # Separate by severity
        high_priority = [r for r in recommendations if r["severity"] == "high"]
        medium_priority = [r for r in recommendations if r["severity"] == "medium"]
        
        if high_priority:
            st.markdown("**🔴 High Priority Adjustments:**")
            for rec in high_priority:
                if rec["type"] == "reduce":
                    st.warning(rec["message"])
                else:
                    st.info(rec["message"])
        
        if medium_priority:
            st.markdown("**🟡 Medium Priority Adjustments:**")
            for rec in medium_priority:
                if rec["type"] == "reduce":
                    st.warning(rec["message"])
                else:
                    st.info(rec["message"])
        
        # Show drift table
        with st.expander("📊 View Detailed Drift Analysis"):
            drift_data = []
            for sector, data in rebalancing["drifts"].items():
                drift_data.append({
                    "Sector": sector,
                    "Current %": f"{data['current_pct']:.1f}%",
                    "Target %": f"{data['target_pct']:.1f}%",
                    "Drift": f"{data['drift_pct']:+.1f}%",
                    "Current Value": f"${data['current_value']:,.0f}",
                    "Target Value": f"${data['target_value']:,.0f}",
                    "Adjustment Needed": f"${data['diff_value']:+,.0f}",
                })
            
            drift_df = pd.DataFrame(drift_data)
            st.dataframe(drift_df, use_container_width=True, hide_index=True)
    else:
        st.success("✅ **Portfolio is well-balanced!** No significant rebalancing needed at this time.")
        st.caption("Your sector allocation is within 5% of recommended targets.")
    
    st.markdown("---")
    
    # AI-Powered Recommendations
    st.markdown("### 🤖 AI-Powered Analysis")
    
    with st.spinner("Generating personalized recommendations..."):
        ai_recommendations = generate_ai_portfolio_recommendations(portfolio_df, metrics, user_id)
    
    if ai_recommendations:
        st.markdown(ai_recommendations)
    else:
        st.info("💡 AI recommendations unavailable. Check your OpenAI API key configuration.")

# ============================================
# Main Page Logic
# ============================================
st.set_page_config(page_title="Portfolio", layout="wide")
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

st.title("📁 Portfolio")
st.caption("Upload and manage your investment portfolio")

# Session state initialization
if "current_user_id" not in st.session_state:
    st.session_state.current_user_id = None
if "portfolio" not in st.session_state:
    st.session_state.portfolio = None

# Check if user is logged in
user_id = st.session_state.get("current_user_id")

# ============================================
# Upload Section
# ============================================
st.markdown("---")
st.subheader("📤 Upload Portfolio")

col_upload, col_template = st.columns([3, 1])

with col_template:
    # Download template button
    sample_csv = create_sample_csv()
    st.download_button(
        label="📥 Download Template",
        data=sample_csv,
        file_name="portfolio_template.csv",
        mime="text/csv",
        help="Download a sample CSV file to use as a template"
    )

with col_upload:
    uploaded_file = st.file_uploader(
        "Upload your portfolio (CSV or Excel)",
        type=["csv", "xlsx", "xls"],
        help="Required columns: ticker, quantity | Optional: avg_price, currency"
    )

if uploaded_file:
    with st.spinner("Loading portfolio..."):
        df = load_portfolio_file(uploaded_file)
        
        if df is not None:
            is_valid, error_msg = validate_portfolio_df(df)
            
            if is_valid:
                st.success("✅ Portfolio uploaded successfully!")
                
                # Enrich with market data
                with st.spinner("Fetching current prices..."):
                    enriched_df = enrich_portfolio_df(df)
                    st.session_state.portfolio = enriched_df
                
                # Save to Firestore if user is logged in
                if user_id:
                    if save_portfolio_to_firestore(user_id, enriched_df):
                        st.success("💾 Portfolio saved to your account")
            else:
                st.error(f"❌ {error_msg}")

# ============================================
# Load Existing Portfolio
# ============================================
if user_id and st.session_state.portfolio is None:
    with st.spinner("Loading saved portfolio..."):
        saved_portfolio = load_portfolio_from_firestore(user_id)
        if saved_portfolio is not None:
            enriched_df = enrich_portfolio_df(saved_portfolio)
            st.session_state.portfolio = enriched_df
            st.info("📂 Loaded your saved portfolio")

# ============================================
# Display Portfolio
# ============================================
if st.session_state.portfolio is not None:
    st.markdown("---")
    st.subheader("📊 Your Portfolio")
    
    portfolio_df = st.session_state.portfolio
    
    # Calculate metrics
    metrics = calculate_portfolio_metrics(portfolio_df)
    
    # Summary cards
    render_portfolio_summary(metrics)
    
    st.markdown("---")
    
    # Holdings table
    st.subheader("📋 Holdings")
    
    # Prepare display dataframe
    display_cols = ["ticker", "name", "asset_type", "quantity", "current_price", "market_value"]
    if "avg_price" in portfolio_df.columns and portfolio_df["avg_price"].notna().any():
        display_cols.extend(["avg_price", "cost_basis", "gain_loss", "gain_loss_pct"])
    display_cols.extend(["sector"])
    
    # Add ETF category for ETFs
    if "etf_category" in portfolio_df.columns:
        display_cols.append("etf_category")
    
    display_df = portfolio_df[display_cols].copy()
    display_df["weight_pct"] = (display_df["market_value"] / metrics["total_value"]) * 100
    
    # Format for display
    format_dict = {
        "current_price": "${:.2f}",
        "market_value": "${:,.2f}",
        "weight_pct": "{:.2f}%",
    }
    if "avg_price" in display_df.columns:
        format_dict.update({
            "avg_price": "${:.2f}",
            "cost_basis": "${:,.2f}",
            "gain_loss": "${:,.2f}",
            "gain_loss_pct": "{:.2f}%",
        })
    
    st.dataframe(
        display_df.style.format(format_dict),
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("---")
    
    # Analytics - Asset Type Breakdown
    if metrics.get("num_etfs", 0) > 0:
        render_asset_type_allocation(metrics)
        st.markdown("---")
    
    # Analytics - Sector & Risk
    col_sector, col_risk = st.columns(2)
    
    with col_sector:
        render_sector_allocation(metrics)
    
    with col_risk:
        render_risk_analysis(metrics)
    
    st.markdown("---")
    
    # Portfolio Recommendations
    render_portfolio_recommendations(portfolio_df, metrics, user_id)
    
    st.markdown("---")
    
    # Action buttons
    col_chat, col_clear = st.columns([3, 1])
    
    with col_chat:
        if st.button("💬 Ask AI about this portfolio", type="primary", use_container_width=True):
            # Store portfolio summary in session for Chat to access
            st.session_state.portfolio_summary = {
                "total_value": metrics["total_value"],
                "holdings": portfolio_df[["ticker", "quantity", "market_value", "sector"]].to_dict(orient="records"),
                "sector_allocation": metrics["sector_allocation"],
            }
            st.success("✅ Portfolio context saved! Go to Chat to ask questions.")
            st.info("💡 Try asking: 'Analyze my portfolio' or 'What should I rebalance?'")
    
    with col_clear:
        if st.button("🗑️ Clear portfolio", use_container_width=True):
            st.session_state.portfolio = None
            st.rerun()

else:
    st.info("📂 Upload a portfolio file to get started, or log in to load your saved portfolio.")
    
    # Show example
    with st.expander("💡 See example portfolio format"):
        st.code(create_sample_csv(), language="csv")
        st.caption("**Required columns:** ticker, quantity")
        st.caption("**Optional columns:** avg_price (for gain/loss tracking), currency")
