# app/pages/02_Dashboard.py

import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

import pandas as pd
import streamlit as st
from google.cloud import firestore
import plotly.graph_objects as go
import plotly.express as px

from app.pfs_service import (
    get_latest_pfs_for_user,
    get_pfs_history_for_user,
)
from app.auth_check import require_authentication

from app.pft import load_twin_snapshot, build_and_save_twin, simulate_goal_probability
from app.portfolio_recommender import calculate_recommended_portfolio, get_allocation_explanation

# Import encryption utilities
try:
    from app.encryption import decrypt_user_profile
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

# Import professional UI components
try:
    from app.ui_components import (
        load_custom_css,
        show_professional_header,
        show_skeleton_screen,
        LoadingContext,
        lazy_load_component
    )
    load_custom_css()
except ImportError:
    def show_professional_header(title, subtitle=None): st.title(title)
    def show_skeleton_screen(*args): pass
    class LoadingContext:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def lazy_load_component(func, *args, **kwargs): return func()

# Firestore config
db_fs = firestore.Client()
USERS_COLLECTION = "users"


def calculate_financial_health_score(pfs) -> Dict[str, Any]:
    """
    Calculate comprehensive financial health score (0-100) based on multiple factors.
    Similar to FICO but for overall financial wellness.
    
    Returns:
        Dictionary with score, breakdown, and category
    """
    if not pfs:
        return None
    
    score_components = {}
    
    # 1. Savings Rate (0-25 points)
    # Excellent: 20%+, Good: 15-20%, Fair: 10-15%, Poor: <10%
    savings_rate = pfs.savings_rate if pfs.savings_rate else 0
    if savings_rate >= 20:
        score_components['savings_rate'] = 25
    elif savings_rate >= 15:
        score_components['savings_rate'] = 20
    elif savings_rate >= 10:
        score_components['savings_rate'] = 15
    elif savings_rate >= 5:
        score_components['savings_rate'] = 10
    else:
        score_components['savings_rate'] = 5
    
    # 2. Debt-to-Income Ratio (0-25 points)
    # Excellent: <20%, Good: 20-35%, Fair: 35-50%, Poor: >50%
    net_income = pfs.net_income if pfs.net_income else 0
    total_debt = (pfs.short_term_debt or 0) + (pfs.long_term_debt or 0) + (pfs.other_liabilities or 0)
    
    # Calculate monthly debt payment (assume 5% of total debt as monthly payment)
    monthly_debt_payment = total_debt * 0.05 / 12
    debt_to_income = (monthly_debt_payment / net_income * 100) if net_income > 0 else 100
    
    if debt_to_income < 20:
        score_components['debt_management'] = 25
    elif debt_to_income < 35:
        score_components['debt_management'] = 20
    elif debt_to_income < 50:
        score_components['debt_management'] = 10
    else:
        score_components['debt_management'] = 5
    
    # 3. Emergency Fund Coverage (0-20 points)
    # Excellent: 6+ months, Good: 3-6 months, Fair: 1-3 months, Poor: <1 month
    cash = pfs.cash_and_equivalents if pfs.cash_and_equivalents else 0
    monthly_expenses = (pfs.fixed_expenses or 0) + (pfs.variable_expenses or 0)
    emergency_months = (cash / monthly_expenses) if monthly_expenses > 0 else 0
    
    if emergency_months >= 6:
        score_components['emergency_fund'] = 20
    elif emergency_months >= 3:
        score_components['emergency_fund'] = 15
    elif emergency_months >= 1:
        score_components['emergency_fund'] = 10
    else:
        score_components['emergency_fund'] = 5
    
    # 4. Net Worth Progress (0-15 points)
    # Positive net worth gets points, negative loses points
    net_worth = pfs.net_worth if pfs.net_worth else 0
    
    if net_worth > 500000:
        score_components['net_worth'] = 15
    elif net_worth > 100000:
        score_components['net_worth'] = 12
    elif net_worth > 50000:
        score_components['net_worth'] = 10
    elif net_worth > 0:
        score_components['net_worth'] = 8
    elif net_worth > -50000:
        score_components['net_worth'] = 5
    else:
        score_components['net_worth'] = 2
    
    # 5. Investment Diversification (0-15 points)
    investments = pfs.investments if pfs.investments else 0
    total_assets = (pfs.cash_and_equivalents or 0) + investments + (pfs.real_estate or 0) + (pfs.other_assets or 0)
    investment_ratio = (investments / total_assets * 100) if total_assets > 0 else 0
    
    # Ideal investment ratio: 40-70% of total assets
    if 40 <= investment_ratio <= 70:
        score_components['investments'] = 15
    elif 20 <= investment_ratio < 40 or 70 < investment_ratio <= 85:
        score_components['investments'] = 10
    elif investment_ratio > 0:
        score_components['investments'] = 5
    else:
        score_components['investments'] = 0
    
    # Calculate total score
    total_score = sum(score_components.values())
    
    # Determine grade
    if total_score >= 85:
        grade = "A+"
        status = "Excellent"
        color = "🟢"
    elif total_score >= 75:
        grade = "A"
        status = "Very Good"
        color = "🟢"
    elif total_score >= 65:
        grade = "B"
        status = "Good"
        color = "🔵"
    elif total_score >= 55:
        grade = "C"
        status = "Fair"
        color = "🟡"
    elif total_score >= 45:
        grade = "D"
        status = "Needs Improvement"
        color = "🟠"
    else:
        grade = "F"
        status = "Critical"
        color = "🔴"
    
    return {
        "total_score": total_score,
        "grade": grade,
        "status": status,
        "color": color,
        "components": score_components,
        "metrics": {
            "savings_rate": savings_rate,
            "debt_to_income": debt_to_income,
            "emergency_months": emergency_months,
            "net_worth": net_worth,
            "investment_ratio": investment_ratio
        }
    }


def project_net_worth(
    current_pfs,
    years: int = 10,
    monthly_savings_growth_rate: float = 0.02,
    investment_return_rate: float = 0.07,
    cash_return_rate: float = 0.02,
    real_estate_appreciation: float = 0.03,
    debt_paydown_rate: float = 0.05,
    inflation_rate: float = 0.03,
) -> pd.DataFrame:
    """
    Project future net worth based on current financial position, savings rate, and asset growth.
    Includes both nominal and real (inflation-adjusted) values.
    
    Args:
        current_pfs: Current PFS snapshot
        years: Number of years to project forward
        monthly_savings_growth_rate: Annual rate at which monthly savings increases (e.g., 2% for raises)
        investment_return_rate: Expected annual return on investments (default 7%)
        cash_return_rate: Expected annual return on cash/savings (default 2%)
        real_estate_appreciation: Annual real estate appreciation rate (default 3%)
        debt_paydown_rate: Annual debt reduction rate (default 5% of principal)
        inflation_rate: Annual inflation rate for calculating real values (default 3%)
    
    Returns:
        DataFrame with projected values by year (both nominal and real)
    """
    # Current state
    cash = current_pfs.cash_and_equivalents or 0
    investments = current_pfs.investments or 0
    real_estate = current_pfs.real_estate or 0
    other_assets = current_pfs.other_assets or 0
    short_term_debt = current_pfs.short_term_debt or 0
    long_term_debt = current_pfs.long_term_debt or 0
    other_liabilities = current_pfs.other_liabilities or 0
    monthly_savings = current_pfs.monthly_savings or 0
    
    # Project year by year
    projections = []
    
    for year in range(years + 1):
        # Current year values (nominal)
        total_assets = cash + investments + real_estate + other_assets
        total_liabilities = short_term_debt + long_term_debt + other_liabilities
        net_worth = total_assets - total_liabilities
        
        # Calculate inflation adjustment factor (compound)
        inflation_factor = (1 + inflation_rate) ** year
        
        # Calculate real (inflation-adjusted) values
        real_net_worth = net_worth / inflation_factor
        real_total_assets = total_assets / inflation_factor
        real_total_liabilities = total_liabilities / inflation_factor
        
        projections.append({
            "year": year,
            "cash": cash,
            "investments": investments,
            "real_estate": real_estate,
            "other_assets": other_assets,
            "total_assets": total_assets,
            "short_term_debt": short_term_debt,
            "long_term_debt": long_term_debt,
            "other_liabilities": other_liabilities,
            "total_liabilities": total_liabilities,
            "net_worth": net_worth,
            "monthly_savings": monthly_savings,
            "real_net_worth": real_net_worth,
            "real_total_assets": real_total_assets,
            "real_total_liabilities": real_total_liabilities,
            "inflation_factor": inflation_factor,
        })
        
        if year < years:
            # Apply growth for next year
            
            # 1. Add annual savings to investments (assume savings go to investments)
            annual_savings = monthly_savings * 12
            investments += annual_savings
            
            # 2. Grow each asset class by expected return
            cash *= (1 + cash_return_rate)
            investments *= (1 + investment_return_rate)
            real_estate *= (1 + real_estate_appreciation)
            other_assets *= (1 + cash_return_rate)  # Conservative growth for other assets
            
            # 3. Pay down debt
            total_debt = short_term_debt + long_term_debt + other_liabilities
            annual_debt_payment = total_debt * debt_paydown_rate
            
            # Prioritize short-term debt paydown
            if short_term_debt > 0:
                payment_to_st = min(short_term_debt, annual_debt_payment)
                short_term_debt -= payment_to_st
                annual_debt_payment -= payment_to_st
            
            # Then long-term debt
            if annual_debt_payment > 0 and long_term_debt > 0:
                payment_to_lt = min(long_term_debt, annual_debt_payment)
                long_term_debt -= payment_to_lt
                annual_debt_payment -= payment_to_lt
            
            # Then other liabilities
            if annual_debt_payment > 0 and other_liabilities > 0:
                payment_to_other = min(other_liabilities, annual_debt_payment)
                other_liabilities -= payment_to_other
            
            # 4. Increase monthly savings by growth rate (raises, promotions)
            monthly_savings *= (1 + monthly_savings_growth_rate)
    
    return pd.DataFrame(projections)


def categorize_wealth_stage(net_worth: float) -> Dict[str, str]:
    """
    Categorize user based on net worth into wealth stages.
    
    Returns:
        Dictionary with stage, description, and next milestone
    """
    if net_worth < 0:
        return {
            "stage": "🌱 Foundation Builder",
            "description": "Focus on eliminating debt and building positive net worth",
            "next_milestone": "Reach $0 net worth",
            "advice": "Prioritize debt reduction and emergency fund creation"
        }
    elif net_worth < 10000:
        return {
            "stage": "🌱 Beginner",
            "description": "Early stages of wealth building",
            "next_milestone": "Reach $10,000 net worth",
            "advice": "Build emergency fund and start investing consistently"
        }
    elif net_worth < 50000:
        return {
            "stage": "📈 Accumulator (Early)",
            "description": "Making steady progress toward financial goals",
            "next_milestone": "Reach $50,000 net worth",
            "advice": "Increase savings rate and optimize investment strategy"
        }
    elif net_worth < 100000:
        return {
            "stage": "📈 Accumulator",
            "description": "Building substantial wealth through consistent savings",
            "next_milestone": "Reach $100,000 net worth",
            "advice": "Maximize retirement contributions and tax-advantaged accounts"
        }
    elif net_worth < 500000:
        return {
            "stage": "💼 Advanced Accumulator",
            "description": "Significant wealth accumulated, approaching financial independence",
            "next_milestone": "Reach $500,000 net worth",
            "advice": "Diversify investments and consider tax optimization strategies"
        }
    elif net_worth < 1000000:
        return {
            "stage": "💎 High Net Worth Individual",
            "description": "Substantial assets with strong financial security",
            "next_milestone": "Reach $1,000,000 net worth",
            "advice": "Focus on wealth preservation and estate planning"
        }
    else:
        return {
            "stage": "👑 Ultra High Net Worth",
            "description": "Top tier wealth with multiple income streams and assets",
            "next_milestone": "Maintain and grow wealth",
            "advice": "Advanced tax strategies, philanthropy, and legacy planning"
        }


def calculate_financial_roadmap(pfs) -> Dict[str, Any]:
    """
    Calculate personalized financial roadmap with progressive levels.
    Auto-generates goals based on user's current financial situation.
    
    Returns:
        Dictionary with current level, progress, and next milestones
    """
    if not pfs:
        return None
    
    # Calculate key metrics
    annual_expenses = (pfs.fixed_expenses + pfs.variable_expenses) * 12
    cash = pfs.cash_and_equivalents or 0
    investments = pfs.investments or 0
    portfolio_value = cash + investments
    total_debt = (pfs.short_term_debt or 0) + (pfs.long_term_debt or 0) + (pfs.other_liabilities or 0)
    monthly_expenses = (pfs.fixed_expenses or 0) + (pfs.variable_expenses or 0)
    emergency_months = (cash / monthly_expenses) if monthly_expenses > 0 else 0
    
    # High-interest debt threshold (simplified - assume short-term debt is high interest)
    high_interest_debt = pfs.short_term_debt or 0
    
    # Define progressive levels
    levels = [
        {
            "id": 1,
            "name": "🎯 Debt Freedom",
            "target": "Close high-interest debt",
            "condition": high_interest_debt == 0,
            "value": high_interest_debt,
            "target_value": 0,
            "description": "Eliminate high-interest debt (credit cards, personal loans)",
            "priority": "Critical"
        },
        {
            "id": 2,
            "name": "🛡️ Emergency Fund",
            "target": "6 months of expenses in cash",
            "condition": emergency_months >= 6,
            "value": emergency_months,
            "target_value": 6,
            "description": f"Build {6 * monthly_expenses:,.0f} emergency fund",
            "priority": "High"
        },
        {
            "id": 3,
            "name": "📊 Portfolio Starter",
            "target": "5,000 investment portfolio",
            "condition": portfolio_value >= 5000,
            "value": portfolio_value,
            "target_value": 5000,
            "description": "Build initial investment portfolio of 5,000",
            "priority": "Medium"
        },
        {
            "id": 4,
            "name": "📈 Growing Investor",
            "target": "10,000 investment portfolio",
            "condition": portfolio_value >= 10000,
            "value": portfolio_value,
            "target_value": 10000,
            "description": "Grow portfolio to 10,000",
            "priority": "Medium"
        },
        {
            "id": 5,
            "name": "💪 Serious Accumulator",
            "target": "25,000 investment portfolio",
            "condition": portfolio_value >= 25000,
            "value": portfolio_value,
            "target_value": 25000,
            "description": "Build significant portfolio of 25,000",
            "priority": "Medium"
        },
        {
            "id": 6,
            "name": "🚀 Advanced Builder",
            "target": "50,000 investment portfolio",
            "condition": portfolio_value >= 50000,
            "value": portfolio_value,
            "target_value": 50000,
            "description": "Achieve substantial portfolio of 50,000",
            "priority": "Medium"
        },
        {
            "id": 7,
            "name": "💎 Wealth Creator",
            "target": "100,000 investment portfolio",
            "condition": portfolio_value >= 100000,
            "value": portfolio_value,
            "target_value": 100000,
            "description": "Reach six-figure portfolio milestone",
            "priority": "Low"
        },
        {
            "id": 8,
            "name": "🌟 Financial Independence",
            "target": "25x annual expenses",
            "condition": portfolio_value >= (annual_expenses * 25),
            "value": portfolio_value,
            "target_value": annual_expenses * 25,
            "description": f"Achieve FI with {annual_expenses * 25:,.0f} (4% rule)",
            "priority": "Ultimate"
        }
    ]
    
    # Find current level and next milestone
    current_level = 0
    for level in levels:
        if level["condition"]:
            current_level = level["id"]
        else:
            break
    
    # Calculate progress on current level
    next_level = None
    progress_pct = 0
    if current_level < len(levels):
        next_level = levels[current_level]  # Next incomplete level
        if next_level["target_value"] > 0:
            progress_pct = min((next_level["value"] / next_level["target_value"]) * 100, 100)
    
    # Get completed and upcoming levels
    completed_levels = [l for l in levels if l["id"] <= current_level]
    upcoming_levels = [l for l in levels if l["id"] > current_level]
    
    return {
        "current_level": current_level,
        "total_levels": len(levels),
        "next_level": next_level,
        "progress_pct": progress_pct,
        "completed_levels": completed_levels,
        "upcoming_levels": upcoming_levels,
        "all_levels": levels
    }


def get_peer_comparisons(pfs, country: str = "United States") -> Dict[str, Any]:
    """
    Compare user's financial metrics to national averages/benchmarks.
    
    Returns:
        Dictionary with percentile rankings and comparison text
    """
    comparisons = {}
    
    net_income = (pfs.net_income * 12) if pfs.net_income else 0  # Annual income
    net_worth = pfs.net_worth if pfs.net_worth else 0
    savings_rate = pfs.savings_rate if pfs.savings_rate else 0
    
    # Income percentiles (US benchmarks - simplified)
    if net_income >= 200000:
        comparisons['income'] = "Top 10% of earners"
    elif net_income >= 100000:
        comparisons['income'] = "Top 25% of earners"
    elif net_income >= 60000:
        comparisons['income'] = "Above median income"
    elif net_income >= 35000:
        comparisons['income'] = "Near median income"
    else:
        comparisons['income'] = "Below median income"
    
    # Net worth percentiles by age (simplified - assume age 35-44)
    if net_worth >= 500000:
        comparisons['net_worth'] = "Top 20% for net worth"
    elif net_worth >= 100000:
        comparisons['net_worth'] = "Above average net worth"
    elif net_worth >= 50000:
        comparisons['net_worth'] = "Near median net worth"
    elif net_worth >= 0:
        comparisons['net_worth'] = "Building net worth"
    else:
        comparisons['net_worth'] = "Negative net worth (focus on debt reduction)"
    
    # Savings rate comparison
    if savings_rate >= 20:
        comparisons['savings'] = "Top 10% savings rate (excellent!)"
    elif savings_rate >= 15:
        comparisons['savings'] = "Above average savings rate"
    elif savings_rate >= 10:
        comparisons['savings'] = "Average savings rate"
    else:
        comparisons['savings'] = "Below average savings rate"
    
    # Debt comparison
    total_debt = (pfs.short_term_debt or 0) + (pfs.long_term_debt or 0) + (pfs.other_liabilities or 0)
    
    if total_debt == 0:
        comparisons['debt'] = "Debt-free (top 25%)"
    elif total_debt < 10000:
        comparisons['debt'] = "Low debt burden"
    elif total_debt < 50000:
        comparisons['debt'] = "Moderate debt (average range)"
    elif total_debt < 100000:
        comparisons['debt'] = "Above average debt"
    else:
        comparisons['debt'] = "High debt burden (consider debt reduction strategy)"
    
    return comparisons


def get_user_by_email_fs(email: str) -> Optional[Dict[str, Any]]:
    """Lookup user in Firestore by email."""
    if not email:
        return None
    
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


def get_user_by_id_fs(user_id: str) -> Optional[Dict[str, Any]]:
    """Lookup user in Firestore by user ID."""
    if not user_id:
        return None
    
    try:
        doc = db_fs.collection(USERS_COLLECTION).document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            data["id"] = doc.id
            return data
    except Exception as e:
        print(f"Error fetching user by ID: {e}")
    return None


def get_actual_portfolio_allocation(user_id: str, latest_pfs=None) -> Optional[Dict[str, float]]:
    """
    Get user's actual portfolio allocation from saved portfolio data.
    Includes cash from PFS if available.
    
    Returns:
        Dictionary with actual asset class allocations (percentages) or None
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection("portfolios").document(user_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            print(f"No portfolio document found for user {user_id}")
            return None
        
        data = doc.to_dict()
        holdings = data.get("holdings", [])
        
        if not holdings:
            print(f"No holdings found in portfolio for user {user_id}")
            return None
        
        # Categorize holdings into asset classes
        allocation = {
            "Cash": 0.0,
            "Bonds": 0.0,
            "Commodities": 0.0,
            "Real Estate": 0.0,
            "ETFs": 0.0,
            "Stocks": 0.0,
        }
        
        # Include cash from PFS if available
        cash_value = 0.0
        if latest_pfs:
            cash_value = latest_pfs.cash_and_equivalents or 0
            allocation["Cash"] = cash_value
        
        total_value = cash_value
        
        for holding in holdings:
            market_value = holding.get("market_value", 0)
            if market_value is None or pd.isna(market_value):
                continue
                
            total_value += market_value
            
            # Categorize by asset_type and sector
            asset_type = holding.get("asset_type", "Stock")
            sector = holding.get("sector", "Unknown")
            etf_category = holding.get("etf_category", "")
            
            if asset_type == "ETF":
                # Categorize ETFs by their underlying assets
                if etf_category and isinstance(etf_category, str):
                    etf_cat_lower = etf_category.lower()
                    if "bond" in etf_cat_lower or "fixed" in etf_cat_lower:
                        allocation["Bonds"] += market_value
                    elif "real estate" in etf_cat_lower or "reit" in etf_cat_lower:
                        allocation["Real Estate"] += market_value
                    elif "commodity" in etf_cat_lower or "gold" in etf_cat_lower or "silver" in etf_cat_lower:
                        allocation["Commodities"] += market_value
                    else:
                        allocation["ETFs"] += market_value
                else:
                    allocation["ETFs"] += market_value
            elif sector == "Real Estate" or "REIT" in sector:
                allocation["Real Estate"] += market_value
            else:
                allocation["Stocks"] += market_value
        
        # Convert to percentages
        if total_value > 0:
            for key in allocation:
                allocation[key] = (allocation[key] / total_value) * 100
        
        return allocation
        
    except Exception as e:
        print(f"Error getting actual portfolio allocation: {e}")
        return None


@st.cache_resource
def get_firestore_client():
    """Cached Firestore client for portfolio queries."""
    return firestore.Client()


def get_synthetic_portfolio_from_pfs(latest_pfs) -> Optional[Dict[str, float]]:
    """
    Generate synthetic portfolio allocation from PFS data when no portfolio is uploaded.
    Uses the actual asset values from the user's financial profile.
    
    Returns:
        Dictionary with asset class allocations (percentages) or None
    """
    try:
        if not latest_pfs:
            return None
        
        # Get asset values from PFS
        cash = latest_pfs.cash_and_equivalents or 0
        investments = latest_pfs.investments or 0
        real_estate = latest_pfs.real_estate or 0
        other_assets = latest_pfs.other_assets or 0
        
        # Calculate total assets
        total_assets = cash + investments + real_estate + other_assets
        
        if total_assets == 0:
            return None
        
        # Create allocation based on PFS data
        # Assume investments are split between stocks, bonds, and ETFs based on risk tolerance
        risk_tolerance = latest_pfs.risk_tolerance.lower() if latest_pfs.risk_tolerance else "moderate"
        
        if risk_tolerance == "conservative":
            # Conservative: More bonds, less stocks
            stocks_pct = 0.20  # 20% of investments
            bonds_pct = 0.50   # 50% of investments
            etfs_pct = 0.25    # 25% of investments
            commodities_pct = 0.05  # 5% of investments
        elif risk_tolerance == "aggressive":
            # Aggressive: More stocks, less bonds
            stocks_pct = 0.50  # 50% of investments
            bonds_pct = 0.10   # 10% of investments
            etfs_pct = 0.35    # 35% of investments
            commodities_pct = 0.05  # 5% of investments
        else:  # moderate
            # Moderate: Balanced
            stocks_pct = 0.30  # 30% of investments
            bonds_pct = 0.30   # 30% of investments
            etfs_pct = 0.35    # 35% of investments
            commodities_pct = 0.05  # 5% of investments
        
        allocation = {
            "Cash": (cash / total_assets) * 100,
            "Bonds": ((investments * bonds_pct) / total_assets) * 100,
            "Commodities": ((investments * commodities_pct) / total_assets) * 100,
            "Real Estate": (real_estate / total_assets) * 100,
            "ETFs": ((investments * etfs_pct) / total_assets) * 100,
            "Stocks": ((investments * stocks_pct + other_assets) / total_assets) * 100,
        }
        
        return allocation
        
    except Exception as e:
        print(f"Error generating synthetic portfolio: {e}")
        return None


def render_portfolio_comparison(recommended: Dict[str, float], actual: Optional[Dict[str, float]]):
    """
    Render side-by-side comparison of recommended vs actual portfolio allocation.
    """
    st.subheader("📊 Portfolio Allocation Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🎯 Recommended Allocation")
        st.caption("Based on your risk profile, financial health, and current market conditions")
        
        # Create pie chart for recommended allocation
        # Filter out zero values for cleaner display, but always keep Cash
        rec_filtered = {k: v for k, v in recommended.items() if v > 0.5 or k == "Cash"}
        
        fig_rec = go.Figure(data=[go.Pie(
            labels=list(rec_filtered.keys()),
            values=list(rec_filtered.values()),
            hole=0.3,
            marker=dict(colors=px.colors.qualitative.Set3)
        )])
        
        fig_rec.update_layout(
            showlegend=True,
            height=400,
            margin=dict(l=20, r=20, t=30, b=20)
        )
        
        st.plotly_chart(fig_rec, use_container_width=True)
        
        # Show percentage table
        rec_df = pd.DataFrame({
            "Asset Class": list(rec_filtered.keys()),
            "Target %": [f"{v:.1f}%" for v in rec_filtered.values()]
        }).sort_values("Asset Class")
        
        st.dataframe(rec_df, use_container_width=True, hide_index=True)
    
    with col2:
        if actual:
            # Check if this is synthetic or real portfolio
            is_synthetic = actual.get("_is_synthetic", False)
            
            if is_synthetic:
                st.markdown("#### 💼 Your Current Allocation (Estimated)")
                st.caption("Based on your financial profile data. Upload portfolio for actual holdings.")
            else:
                st.markdown("#### 💼 Your Current Allocation")
                st.caption("Based on your uploaded portfolio")
            
            # Filter out zero values and metadata flags
            actual_filtered = {k: v for k, v in actual.items() if k != "_is_synthetic" and v > 0.5}
            
            fig_actual = go.Figure(data=[go.Pie(
                labels=list(actual_filtered.keys()),
                values=list(actual_filtered.values()),
                hole=0.3,
                marker=dict(colors=px.colors.qualitative.Pastel)
            )])
            
            fig_actual.update_layout(
                showlegend=True,
                height=400,
                margin=dict(l=20, r=20, t=30, b=20)
            )
            
            st.plotly_chart(fig_actual, use_container_width=True)
            
            # Show percentage table
            actual_df = pd.DataFrame({
                "Asset Class": list(actual_filtered.keys()),
                "Current %": [f"{v:.1f}%" for v in actual_filtered.values()]
            }).sort_values("Asset Class")
            
            st.dataframe(actual_df, use_container_width=True, hide_index=True)
            
            # Show warning after table for synthetic portfolios
            if is_synthetic:
                st.warning("⚠️ This is an estimated allocation based on your PFS data. Upload your actual portfolio on the [Portfolio page](/Portfolio) for precise analysis.")
        else:
            st.markdown("#### 💼 Your Current Allocation")
            st.info("📂 **No portfolio or financial data available**\n\nTo see your current allocation:\n\n1. Go to the [Profile page](/Profile) and save your financial snapshot, OR\n2. Go to the [Portfolio page](/Portfolio) and upload your holdings\n\nOnce you provide data, we'll show your actual allocation here.")
    
    # Show allocation drift analysis if actual portfolio exists
    if actual:
        st.markdown("---")
        st.markdown("#### 📈 Allocation Drift Analysis")
        
        # Calculate drift
        drift_data = []
        for asset_class in recommended.keys():
            rec_pct = recommended.get(asset_class, 0)
            actual_pct = actual.get(asset_class, 0)
            drift = actual_pct - rec_pct
            
            if abs(drift) > 0.1:  # Only show if drift is meaningful
                drift_data.append({
                    "Asset Class": asset_class,
                    "Target %": f"{rec_pct:.1f}%",
                    "Current %": f"{actual_pct:.1f}%",
                    "Drift": f"{drift:+.1f}%",
                    "Status": "⚠️ Overweight" if drift > 5 else ("⚠️ Underweight" if drift < -5 else "✅ Aligned")
                })
        
        if drift_data:
            drift_df = pd.DataFrame(drift_data)
            st.dataframe(drift_df, use_container_width=True, hide_index=True)
            
            # Recommendations
            st.markdown("**💡 Rebalancing Recommendations:**")
            
            overweight = [d for d in drift_data if "Overweight" in d["Status"]]
            underweight = [d for d in drift_data if "Underweight" in d["Status"]]
            
            if overweight:
                st.warning(f"**Reduce exposure:** {', '.join([d['Asset Class'] for d in overweight])}")
            if underweight:
                st.info(f"**Increase exposure:** {', '.join([d['Asset Class'] for d in underweight])}")
            
            if not overweight and not underweight:
                st.success("✅ **Portfolio is well-aligned with recommendations!** No major rebalancing needed.")
        else:
            st.success("✅ **Portfolio is well-aligned with recommendations!** All asset classes are within target ranges.")


# Page config
st.set_page_config(page_title="Perfient — Dashboard", layout="wide")

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

st.title("📊 Financial Dashboard")
st.caption("Track your financial progress over time.")

# Shared session state with main chat page
if "current_user_id" not in st.session_state:
    st.session_state.current_user_id = None
if "current_user_email" not in st.session_state:
    st.session_state.current_user_email = ""


# User identification
user_id = st.session_state.current_user_id

if not user_id:
    st.warning("⚠️ Not logged in — Please go to the [Profile page](/Profile) to load your account.")
    st.info("👉 Enter your email on the Profile page and click 'Load profile' to view your dashboard.")
    st.stop()


# Display current user
st.success(f"👤 Viewing dashboard for: **@{st.session_state.current_user_username}**")

# Auto-refresh indicator
st.caption("🔄 Dashboard auto-updates based on your profile changes and market conditions")

# Get latest PFS for summary
latest_pfs = get_latest_pfs_for_user(user_id)

if latest_pfs:
    # ============================================
    # Financial Roadmap (Auto-generated levels)
    # ============================================
    roadmap = calculate_financial_roadmap(latest_pfs)
    
    if roadmap and roadmap["next_level"]:
        st.markdown("## 🗺️ Your Financial Roadmap")
        st.caption("Progressive milestones automatically generated based on your financial profile")
        
        # Progress bar for current level
        next_level = roadmap["next_level"]
        progress_pct = roadmap["progress_pct"]
        
        col_progress, col_level = st.columns([3, 1])
        
        with col_progress:
            st.markdown(f"### Current Goal: {next_level['name']}")
            st.caption(next_level['description'])
            st.progress(progress_pct / 100)
            st.caption(f"Progress: {progress_pct:.1f}%")
        
        with col_level:
            st.metric(
                "Level",
                f"{roadmap['current_level']}/{roadmap['total_levels']}",
                f"+{roadmap['current_level']} completed"
            )
        
        # Show next 3 upcoming milestones
        if roadmap["upcoming_levels"]:
            st.markdown("#### 🎯 Upcoming Milestones")
            upcoming = roadmap["upcoming_levels"][:3]
            cols = st.columns(len(upcoming))
            for idx, level in enumerate(upcoming):
                with cols[idx]:
                    icon = "🔒" if level["id"] > roadmap["current_level"] + 1 else "⏭️"
                    st.markdown(f"**{icon} Level {level['id']}**")
                    st.caption(level['name'])
                    st.caption(f"Target: {level['target']}")
        
        st.markdown("---")
    
    # ============================================
    # Financial Health Score & Categorization
    # ============================================
    st.markdown("## 🎯 Financial Health Overview")
    
    # Calculate health score
    health_score = calculate_financial_health_score(latest_pfs)
    wealth_stage = categorize_wealth_stage(latest_pfs.net_worth)
    
    # Get user's country from profile data (default to US)
    user_data = get_user_by_id_fs(user_id)
    profile_data = user_data.get("profile_data", {}) if user_data else {}
    
    # Decrypt profile data if encrypted
    if ENCRYPTION_AVAILABLE and profile_data and profile_data.get("_encrypted", False):
        try:
            profile_data = decrypt_user_profile(profile_data)
        except Exception as e:
            print(f"Failed to decrypt profile data: {e}")
            profile_data = {}
    
    country = profile_data.get("country", "United States")
    
    peer_comparisons = get_peer_comparisons(latest_pfs, country)
    
    # Main score display
    col_score, col_stage, col_peers = st.columns([1, 1, 1])
    
    with col_score:
        st.markdown("### Financial Health Score")
        st.markdown(f"# {health_score['color']} {health_score['total_score']}/100")
        st.markdown(f"**Grade: {health_score['grade']}** - {health_score['status']}")
        
        # Score breakdown in expander
        with st.expander("📊 Score Breakdown"):
            components = health_score['components']
            st.write(f"💰 Savings Rate: {components['savings_rate']}/25 ({health_score['metrics']['savings_rate']:.1f}%)")
            st.write(f"💳 Debt Management: {components['debt_management']}/25 (DTI: {health_score['metrics']['debt_to_income']:.1f}%)")
            st.write(f"🏥 Emergency Fund: {components['emergency_fund']}/20 ({health_score['metrics']['emergency_months']:.1f} months)")
            st.write(f"📈 Net Worth: {components['net_worth']}/15 (${health_score['metrics']['net_worth']:,.0f})")
            st.write(f"📊 Investments: {components['investments']}/15 ({health_score['metrics']['investment_ratio']:.1f}% of assets)")
    
    with col_stage:
        st.markdown("### Wealth Stage")
        st.markdown(f"# {wealth_stage['stage']}")
        st.info(wealth_stage['description'])
        st.markdown(f"**Next Milestone:** {wealth_stage['next_milestone']}")
        
        with st.expander("💡 Recommended Actions"):
            st.write(wealth_stage['advice'])
    
    with col_peers:
        st.markdown("### Peer Comparison")
        st.markdown("**Your Position:**")
        
        for category, comparison in peer_comparisons.items():
            if category == 'income':
                st.write(f"💵 Income: {comparison}")
            elif category == 'net_worth':
                st.write(f"💰 Net Worth: {comparison}")
            elif category == 'savings':
                st.write(f"🏦 Savings: {comparison}")
            elif category == 'debt':
                st.write(f"💳 Debt: {comparison}")
        
        st.caption(f"*Benchmarks based on {country} data")
    
    # Store categorization in session for use in portfolio recommendations
    st.session_state.wealth_stage = wealth_stage['stage']
    st.session_state.financial_health_score = health_score['total_score']
    
    st.markdown("---")
    
    # ============================================
    # Recommended Portfolio Allocation
    # ============================================
    st.markdown("## 📊 Recommended Portfolio Allocation")
    st.caption("Dynamic allocation based on your financial twin, risk profile, and market conditions")
    
    # Load twin for recommendations
    twin = load_twin_snapshot(user_id)
    if not twin:
        try:
            twin = build_and_save_twin(user_id)
        except Exception:
            twin = None
    
    if twin:
        # Calculate recommended allocation using centralized function
        recommended_allocation = calculate_recommended_portfolio(
            latest_pfs=latest_pfs,
            twin=twin,
            health_score=health_score['total_score'],
            wealth_stage=wealth_stage['stage']
        )
        
        # Get actual portfolio allocation (from uploaded portfolio)
        actual_allocation = get_actual_portfolio_allocation(user_id, latest_pfs)
        
        # If no uploaded portfolio, generate synthetic from PFS data
        if not actual_allocation:
            actual_allocation = get_synthetic_portfolio_from_pfs(latest_pfs)
            if actual_allocation:
                # Mark as synthetic so we can display it differently
                actual_allocation["_is_synthetic"] = True
        
        # Render comparison
        render_portfolio_comparison(recommended_allocation, actual_allocation)
        
        # Show factors influencing recommendation
        with st.expander("🔍 Factors Influencing This Recommendation"):
            st.markdown("**Your Profile:**")
            st.write(f"• Risk Tolerance: {latest_pfs.risk_tolerance or 'Moderate'}")
            st.write(f"• Investment Horizon: {latest_pfs.investment_horizon_years or 10} years")
            st.write(f"• Financial Health Score: {health_score['total_score']}/100 ({health_score['grade']})")
            st.write(f"• Wealth Stage: {wealth_stage['stage']}")
            if twin and hasattr(twin, 'stress_index'):
                stress_level = "High" if twin.stress_index > 0.7 else ("Low" if twin.stress_index < 0.3 else "Moderate")
                st.write(f"• Financial Stress Level: {stress_level}")
            
            st.markdown("\n**Market Considerations:**")
            st.write("• Current macro environment: Moderate")
            st.write("• Inflation outlook: Normal")
            st.write("• Interest rate environment: Stable")
            
            st.caption("*Recommendations update automatically based on changes to your profile and market conditions*")
    else:
        st.info("💡 **Save your financial profile** to see personalized portfolio recommendations. Go to the [Profile page](/Profile) to get started.")
    
    st.markdown("---")
    
    # Display current financial snapshot
    st.markdown("### Current Financial Snapshot")
    
    # Check if user is using Twin Lite mode (has range fields instead of exact values)
    user_data = get_user_by_id_fs(user_id)
    profile_data = user_data.get("profile_data", {}) if user_data else {}
    
    # Decrypt profile data if encrypted
    if ENCRYPTION_AVAILABLE and profile_data and profile_data.get("_encrypted", False):
        try:
            profile_data = decrypt_user_profile(profile_data)
        except Exception as e:
            print(f"Failed to decrypt profile data: {e}")
            profile_data = {}
    
    is_lite_mode = profile_data.get("model") == "lite" or (
        profile_data.get("income_range") and not latest_pfs.net_income
    )
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if is_lite_mode:
            # For Twin Lite users, show ranges if available
            net_worth_range = profile_data.get("net_worth_range", "Not specified")
            st.metric("Net Worth (Range)", net_worth_range)
        else:
            st.metric("Net Worth", f"${latest_pfs.net_worth:,.2f}")
    
    with col2:
        if is_lite_mode:
            income_range = profile_data.get("income_range", "Not specified")
            expense_range = profile_data.get("expense_range", "Not specified")
            st.metric("Monthly Income", income_range)
            st.caption(f"Expenses: {expense_range}")
        else:
            st.metric("Monthly Savings", f"${latest_pfs.monthly_savings:,.2f}")
    
    with col3:
        if is_lite_mode:
            st.metric("Mode", "Twin Lite")
            st.caption("[Upgrade to Twin Full](/Profile) for detailed tracking")
        else:
            savings_rate_pct = latest_pfs.savings_rate if latest_pfs.savings_rate else 0
            st.metric("Savings Rate", f"{savings_rate_pct:.1f}%")
    
    with col4:
        if latest_pfs.risk_tolerance:
            st.metric("Risk Tolerance", latest_pfs.risk_tolerance.capitalize())
        else:
            st.metric("Risk Tolerance", "Not set")


# History & progress chart
st.markdown("---")
st.markdown("### Progress Over Time")

history = get_pfs_history_for_user(user_id, limit=200)
if history:
    # Build comprehensive historical dataframe
    hist_df = pd.DataFrame(
        [
            {
                "created_at": p.created_at,
                "net_worth": p.net_worth,
                "monthly_savings": p.monthly_savings,
                "total_debt": p.short_term_debt + p.long_term_debt + p.other_liabilities,
                "cash_pct": (p.cash_and_equivalents / (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) * 100) if (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) > 0 else 0,
                "investments_pct": (p.investments / (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) * 100) if (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) > 0 else 0,
                "real_estate_pct": (p.real_estate / (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) * 100) if (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) > 0 else 0,
                "other_assets_pct": (p.other_assets / (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) * 100) if (p.cash_and_equivalents + p.investments + p.real_estate + p.other_assets) > 0 else 0,
            }
            for p in history
        ]
    ).sort_values("created_at")

    # Helper function to calculate percentage change for different time periods
    def calculate_period_changes(df, column_name, current_time):
        """Calculate percentage changes for 1D, 1W, 1M, 1Y, and Max periods."""
        changes = {}
        current_value = df.iloc[-1][column_name]
        
        periods = {
            "1D": timedelta(days=1),
            "1W": timedelta(weeks=1),
            "1M": timedelta(days=30),
            "1Y": timedelta(days=365),
            "Max": None
        }
        
        for period_name, period_delta in periods.items():
            if period_name == "Max":
                # Compare with first value
                if len(df) > 1:
                    old_value = df.iloc[0][column_name]
                    if old_value != 0:
                        pct_change = ((current_value - old_value) / abs(old_value)) * 100
                        changes[period_name] = pct_change
                    else:
                        changes[period_name] = None
                else:
                    changes[period_name] = None
            else:
                # Find closest snapshot to the target date
                target_date = current_time - period_delta
                past_df = df[df["created_at"] <= target_date]
                
                if len(past_df) > 0:
                    old_value = past_df.iloc[-1][column_name]
                    if old_value != 0:
                        pct_change = ((current_value - old_value) / abs(old_value)) * 100
                        changes[period_name] = pct_change
                    else:
                        changes[period_name] = None
                else:
                    changes[period_name] = None
        
        return changes

    # Get current time for calculations
    current_time = hist_df.iloc[-1]["created_at"]

    tab1, tab2, tab3, tab4 = st.tabs(["Net Worth", "Monthly Savings", "Debt Reduction", "Asset Allocation"])

    with tab1:
        # Calculate percentage changes for Net Worth
        nw_changes = calculate_period_changes(hist_df, "net_worth", current_time)
        
        # Display period performance metrics
        st.markdown("**Performance**")
        col1, col2, col3, col4, col5 = st.columns(5)
        
        for col, (period, pct_change) in zip([col1, col2, col3, col4, col5], nw_changes.items()):
            with col:
                if pct_change is not None:
                    st.metric(period, f"{pct_change:+.2f}%")
                else:
                    st.metric(period, "N/A")
        
        # Show note for N/A values
        if any(v is None for v in nw_changes.values()):
            st.info("💡 **Note:** Progress tracking requires actual data entries. [Switch to Twin Full](/Profile) to track your net worth over time with precise values.")
        
        st.line_chart(hist_df.set_index("created_at")["net_worth"])

    with tab2:
        # Calculate percentage changes for Monthly Savings
        savings_changes = calculate_period_changes(hist_df, "monthly_savings", current_time)
        
        # Display period performance metrics
        st.markdown("**Performance**")
        col1, col2, col3, col4, col5 = st.columns(5)
        
        for col, (period, pct_change) in zip([col1, col2, col3, col4, col5], savings_changes.items()):
            with col:
                if pct_change is not None:
                    st.metric(period, f"{pct_change:+.2f}%")
                else:
                    st.metric(period, "N/A")
        
        # Show note for N/A values
        if any(v is None for v in savings_changes.values()):
            st.info("💡 **Note:** Progress tracking requires actual data entries. [Switch to Twin Full](/Profile) to track your savings over time with precise values.")
        
        st.line_chart(hist_df.set_index("created_at")["monthly_savings"])
    
    with tab3:
        # Calculate percentage changes for Total Debt (inverse display - negative is good)
        debt_changes = calculate_period_changes(hist_df, "total_debt", current_time)
        
        # Display period performance metrics
        st.markdown("**Performance (Debt Reduction)**")
        col1, col2, col3, col4, col5 = st.columns(5)
        
        for col, (period, pct_change) in zip([col1, col2, col3, col4, col5], debt_changes.items()):
            with col:
                if pct_change is not None:
                    # For debt, negative change is good (reduction)
                    st.metric(period, f"{pct_change:+.2f}%", delta_color="inverse")
                else:
                    st.metric(period, "N/A")
        
        # Show note for N/A values
        if any(v is None for v in debt_changes.values()):
            st.info("💡 **Note:** Debt tracking requires actual data entries. [Switch to Twin Full](/Profile) to monitor your debt reduction over time.")
        
        st.markdown("**Total Debt Over Time**")
        st.line_chart(hist_df.set_index("created_at")["total_debt"])
        
        # Show debt reduction summary
        if len(hist_df) > 1:
            first_debt = hist_df.iloc[0]["total_debt"]
            latest_debt = hist_df.iloc[-1]["total_debt"]
            debt_change = latest_debt - first_debt
            debt_change_pct = ((debt_change / first_debt) * 100) if first_debt > 0 else 0
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Initial Debt", f"${first_debt:,.2f}")
            with col2:
                st.metric("Current Debt", f"${latest_debt:,.2f}", 
                         delta=f"${debt_change:,.2f}" if debt_change != 0 else "No change",
                         delta_color="inverse")  # Red is good for debt reduction
            with col3:
                st.metric("Change", f"{debt_change_pct:+.1f}%")
    
    with tab4:
        st.markdown("**Asset Allocation Drift Over Time**")
        
        # Calculate percentage point changes for each asset class
        st.markdown("**Cash & Equivalents Allocation Change**")
        cash_changes = calculate_period_changes(hist_df, "cash_pct", current_time)
        col1, col2, col3, col4, col5 = st.columns(5)
        for col, (period, pct_change) in zip([col1, col2, col3, col4, col5], cash_changes.items()):
            with col:
                if pct_change is not None:
                    st.metric(f"💵 {period}", f"{pct_change:+.2f}%")
                else:
                    st.metric(f"💵 {period}", "N/A")
        
        st.markdown("**Investments Allocation Change**")
        inv_changes = calculate_period_changes(hist_df, "investments_pct", current_time)
        col1, col2, col3, col4, col5 = st.columns(5)
        for col, (period, pct_change) in zip([col1, col2, col3, col4, col5], inv_changes.items()):
            with col:
                if pct_change is not None:
                    st.metric(f"📈 {period}", f"{pct_change:+.2f}%")
                else:
                    st.metric(f"📈 {period}", "N/A")
        
        # Create allocation dataframe for stacked area chart
        allocation_df = hist_df.set_index("created_at")[["cash_pct", "investments_pct", "real_estate_pct", "other_assets_pct"]]
        allocation_df.columns = ["Cash & Equivalents", "Investments", "Real Estate", "Other Assets"]
        
        st.area_chart(allocation_df)
        
        # Show current vs initial allocation comparison
        if len(hist_df) > 1:
            st.markdown("**Allocation Comparison**")
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("##### Initial Allocation")
                initial = hist_df.iloc[0]
                st.write(f"💵 Cash: {initial['cash_pct']:.1f}%")
                st.write(f"📈 Investments: {initial['investments_pct']:.1f}%")
                st.write(f"🏠 Real Estate: {initial['real_estate_pct']:.1f}%")
                st.write(f"📦 Other: {initial['other_assets_pct']:.1f}%")
            
            with col2:
                st.markdown("##### Current Allocation")
                current = hist_df.iloc[-1]
                st.write(f"💵 Cash: {current['cash_pct']:.1f}%")
                st.write(f"📈 Investments: {current['investments_pct']:.1f}%")
                st.write(f"🏠 Real Estate: {current['real_estate_pct']:.1f}%")
                st.write(f"📦 Other: {current['other_assets_pct']:.1f}%")
else:
    st.info("No historical snapshots yet. Save at least one snapshot on the Profile page to start tracking your progress.")


# Net Worth Projection
st.markdown("---")
st.markdown("### 🔮 Net Worth Projection")
st.caption("Forward-looking projection based on your current assets, savings rate, and expected growth rates")

if latest_pfs:
    # Projection controls
    with st.expander("⚙️ Projection Settings", expanded=False):
        col_settings1, col_settings2, col_settings3 = st.columns(3)
        
        with col_settings1:
            projection_years = st.slider(
                "Years to project", 
                min_value=1, 
                max_value=30, 
                value=10,
                help="How many years into the future to project your net worth"
            )
            
            investment_return = st.slider(
                "Expected investment return (%/year)",
                min_value=0.0,
                max_value=15.0,
                value=7.0,
                step=0.5,
                help="Historical S&P 500 average: ~10%. Conservative: 5-7%. Aggressive: 8-12%"
            ) / 100
            
            cash_return = st.slider(
                "Cash/savings return (%/year)",
                min_value=0.0,
                max_value=6.0,
                value=2.0,
                step=0.5,
                help="Expected return on cash and savings accounts. Typical range: 0.5-4%"
            ) / 100
        
        with col_settings2:
            real_estate_appreciation = st.slider(
                "Real estate appreciation (%/year)",
                min_value=0.0,
                max_value=10.0,
                value=3.0,
                step=0.5,
                help="Historical average: ~3-4% per year"
            ) / 100
            
            debt_paydown = st.slider(
                "Annual debt paydown (% of principal)",
                min_value=0.0,
                max_value=20.0,
                value=5.0,
                step=1.0,
                help="What percentage of total debt you'll pay down each year"
            ) / 100
            
            savings_growth = st.slider(
                "Annual savings increase (%/year)",
                min_value=0.0,
                max_value=10.0,
                value=2.0,
                step=0.5,
                help="Expected annual increase in your monthly savings (raises, promotions). Average: 2-3%"
            ) / 100
        
        with col_settings3:
            inflation_rate = st.slider(
                "Expected inflation rate (%/year)",
                min_value=0.0,
                max_value=10.0,
                value=3.0,
                step=0.1,
                help="Annual inflation rate for calculating purchasing power. US average: ~3%"
            ) / 100
            
            st.markdown("---")
            st.caption("💡 **Real vs Nominal:**")
            st.caption("• **Nominal**: Actual dollar amount")
            st.caption("• **Real**: Inflation-adjusted purchasing power")
    
    # Calculate projection
    projection_df = project_net_worth(
        latest_pfs,
        years=projection_years,
        monthly_savings_growth_rate=savings_growth,
        investment_return_rate=investment_return,
        cash_return_rate=cash_return,
        real_estate_appreciation=real_estate_appreciation,
        debt_paydown_rate=debt_paydown,
        inflation_rate=inflation_rate,
    )
    
    # Display key metrics
    current_nw = projection_df.iloc[0]["net_worth"]
    projected_nw = projection_df.iloc[-1]["net_worth"]
    real_projected_nw = projection_df.iloc[-1]["real_net_worth"]
    nw_growth = projected_nw - current_nw
    nw_growth_pct = (nw_growth / abs(current_nw) * 100) if current_nw != 0 else 0
    real_growth = real_projected_nw - current_nw
    real_growth_pct = (real_growth / abs(current_nw) * 100) if current_nw != 0 else 0
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Current Net Worth", f"${current_nw:,.0f}")
        st.caption("Today's dollars")
    with col2:
        st.metric(
            f"Projected ({projection_years}Y)",
            f"${projected_nw:,.0f}",
            delta=f"+${nw_growth:,.0f} ({nw_growth_pct:+.1f}%)"
        )
        st.caption("Nominal (future dollars)")
    with col3:
        st.metric(
            f"Real Value ({projection_years}Y)",
            f"${real_projected_nw:,.0f}",
            delta=f"+${real_growth:,.0f} ({real_growth_pct:+.1f}%)"
        )
        st.caption("Inflation-adjusted")
    with col4:
        final_debt = projection_df.iloc[-1]["total_liabilities"]
        debt_reduction = projection_df.iloc[0]["total_liabilities"] - final_debt
        st.metric(
            "Projected Debt",
            f"${final_debt:,.0f}",
            delta=f"-${debt_reduction:,.0f}" if debt_reduction > 0 else "No change",
            delta_color="inverse"
        )
    
    # Main projection chart
    st.markdown("#### Net Worth Trajectory")
    
    # Create multi-line chart showing net worth, assets, and liabilities
    chart_data = pd.DataFrame({
        "Year": projection_df["year"],
        "Net Worth (Nominal)": projection_df["net_worth"],
        "Net Worth (Real)": projection_df["real_net_worth"],
        "Total Assets": projection_df["total_assets"],
        "Total Liabilities": -projection_df["total_liabilities"],  # Negative for visual clarity
    })
    
    fig = go.Figure()
    
    # Nominal net worth line (bold)
    fig.add_trace(go.Scatter(
        x=chart_data["Year"],
        y=chart_data["Net Worth (Nominal)"],
        mode='lines+markers',
        name='Net Worth (Nominal)',
        line=dict(color='rgb(0, 176, 80)', width=3),
        marker=dict(size=8),
        hovertemplate='Year %{x}<br>Nominal: $%{y:,.0f}<extra></extra>'
    ))
    
    # Real net worth line (bold, dashed)
    fig.add_trace(go.Scatter(
        x=chart_data["Year"],
        y=chart_data["Net Worth (Real)"],
        mode='lines+markers',
        name='Net Worth (Real)',
        line=dict(color='rgb(0, 120, 215)', width=3, dash='dash'),
        marker=dict(size=8, symbol='diamond'),
        hovertemplate='Year %{x}<br>Real (Inflation-Adjusted): $%{y:,.0f}<extra></extra>'
    ))
    
    # Assets line
    fig.add_trace(go.Scatter(
        x=chart_data["Year"],
        y=chart_data["Total Assets"],
        mode='lines',
        name='Total Assets',
        line=dict(color='rgb(68, 114, 196)', width=2, dash='dot'),
        hovertemplate='Year %{x}<br>Assets: $%{y:,.0f}<extra></extra>'
    ))
    
    # Liabilities line (negative values)
    fig.add_trace(go.Scatter(
        x=chart_data["Year"],
        y=chart_data["Total Liabilities"],
        mode='lines',
        name='Total Liabilities',
        line=dict(color='rgb(237, 125, 49)', width=2, dash='dot'),
        hovertemplate='Year %{x}<br>Liabilities: $%{y:,.0f}<extra></extra>'
    ))
    
    fig.update_layout(
        title=f"Net Worth Projection Over Time (Inflation: {inflation_rate*100:.1f}%)",
        xaxis_title="Years from Now",
        yaxis_title="Amount ($)",
        hovermode='x unified',
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        ),
        height=500
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Explain inflation impact
    inflation_impact = projected_nw - real_projected_nw
    st.info(f"💡 **Inflation Impact:** Over {projection_years} years, inflation at {inflation_rate*100:.1f}% reduces the purchasing power of your projected ${projected_nw:,.0f} to ${real_projected_nw:,.0f} in today's dollars. That's a ${inflation_impact:,.0f} difference in real value.")
    
    # Show projection table
    with st.expander("📊 View Detailed Projection Table"):
        display_df = projection_df[["year", "net_worth", "real_net_worth", "total_assets", "total_liabilities", "monthly_savings"]].copy()
        display_df.columns = ["Year", "Net Worth (Nominal)", "Net Worth (Real)", "Total Assets", "Total Liabilities", "Monthly Savings"]
        
        # Format currency columns
        for col in ["Net Worth (Nominal)", "Net Worth (Real)", "Total Assets", "Total Liabilities", "Monthly Savings"]:
            display_df[col] = display_df[col].apply(lambda x: f"${x:,.0f}")
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        st.caption("💡 **Nominal** = Future dollar amounts | **Real** = Today's purchasing power (inflation-adjusted)")
    
    # Asset breakdown over time
    st.markdown("#### Asset Growth Breakdown")
    
    asset_breakdown_data = pd.DataFrame({
        "Year": projection_df["year"],
        "Cash": projection_df["cash"],
        "Investments": projection_df["investments"],
        "Real Estate": projection_df["real_estate"],
        "Other Assets": projection_df["other_assets"],
    })
    
    fig_assets = go.Figure()
    
    asset_colors = {
        "Cash": "rgb(144, 238, 144)",
        "Investments": "rgb(68, 114, 196)",
        "Real Estate": "rgb(255, 192, 0)",
        "Other Assets": "rgb(165, 165, 165)"
    }
    
    for asset_class in ["Cash", "Investments", "Real Estate", "Other Assets"]:
        fig_assets.add_trace(go.Scatter(
            x=asset_breakdown_data["Year"],
            y=asset_breakdown_data[asset_class],
            mode='lines',
            name=asset_class,
            stackgroup='one',
            line=dict(width=0.5),
            fillcolor=asset_colors[asset_class]
        ))
    
    fig_assets.update_layout(
        title="Asset Composition Over Time",
        xaxis_title="Years from Now",
        yaxis_title="Amount ($)",
        hovermode='x unified',
        showlegend=True,
        height=400
    )
    
    st.plotly_chart(fig_assets, use_container_width=True)
    
    # Show detailed year-by-year breakdown
    with st.expander("📊 Year-by-Year Breakdown"):
        # Format the dataframe for display
        display_df = projection_df[[
            "year", "net_worth", "total_assets", "total_liabilities",
            "investments", "cash", "real_estate", "monthly_savings"
        ]].copy()
        
        display_df.columns = [
            "Year", "Net Worth", "Total Assets", "Total Debt",
            "Investments", "Cash", "Real Estate", "Monthly Savings"
        ]
        
        # Format currency columns
        for col in display_df.columns[1:]:
            display_df[col] = display_df[col].apply(lambda x: f"${x:,.0f}")
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    
    st.info("""
    💡 **Note:** This projection assumes:
    - Your monthly savings continue and grow at the specified rate
    - All new savings are invested in your investment portfolio
    - Asset growth rates remain constant (actual returns will vary)
    - Debt paydown continues at the specified rate
    - No major life changes (job loss, inheritance, large purchases)
    
    Adjust the settings above to see how different scenarios affect your projected net worth.
    """)
else:
    st.info("Save your financial profile to see net worth projections. Go to the [Profile page](/Profile) to get started.")


# Goal Simulator Widget
st.markdown("---")
st.markdown("### 🎯 Goal Attainment Simulator")
st.markdown("""
This simulator uses **Monte Carlo analysis** to project your financial future based on your current financial profile. 
It runs thousands of simulations with varying market returns to estimate your probability of reaching a specific financial goal.

**How it works:** The simulator uses your current net worth, expected savings patterns, and market assumptions to forecast 
your wealth growth over time. Higher return assumptions and lower volatility increase your success probability.
""")

# Load or build the Personal Financial Twin
twin = load_twin_snapshot(user_id)
if not twin:
    try:
        twin = build_and_save_twin(user_id)
    except Exception:
        twin = None

if not twin or not twin.series:
    st.info("No Personal Financial Twin found. Save at least one financial snapshot on the Profile page to enable goal simulation.")
else:
    # Get default values from twin
    default_start = twin.series[-1].net_worth if twin.series else 0

    col_left, col_right = st.columns([1, 1])
    
    with col_left:
        st.markdown("**Goal Parameters**")
        goal_amount = st.number_input(
            "Goal amount (target)", 
            min_value=0.0, 
            value=float(max(50000.0, default_start * 2)), 
            step=1000.0, 
            format="%.2f",
            help="The target amount you want to reach (e.g., $100,000 for emergency fund, $500,000 for down payment, $1,000,000 for retirement)"
        )
        years = st.slider(
            "Years until goal", 
            min_value=1, 
            max_value=30, 
            value=5,
            help="Time horizon for reaching your goal. Longer timeframes generally increase success probability due to compound growth."
        )
    
    with col_right:
        st.markdown("**Simulation Settings**")
        n_sims = st.selectbox(
            "Number of simulations", 
            [500, 1000, 2000, 5000], 
            index=1,
            help="More simulations = more accurate results but slower computation. 1000 is recommended for most cases."
        )
        mean = st.number_input(
            "Expected annual return (%)", 
            value=6.0, 
            min_value=-10.0,
            max_value=20.0,
            step=0.5,
            format="%.1f",
            help="Average expected return per year. Conservative: 4-6% (bonds/balanced), Moderate: 7-8% (diversified stocks), Aggressive: 9-10% (growth stocks). Historical S&P 500: ~10%"
        ) / 100
        std = st.number_input(
            "Annual volatility (%)", 
            value=12.0, 
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            format="%.1f",
            help="Measures how much returns fluctuate year-to-year. Low risk: 5-10% (bonds), Medium: 12-15% (diversified), High: 18-25% (aggressive stocks). Historical S&P 500: ~15%"
        ) / 100
    
    run_sim = st.button("Run Simulation", type="primary")

    if run_sim:
        with st.spinner("Running Monte Carlo simulation..."):
            try:
                res = simulate_goal_probability(
                    twin,
                    goal_amount=float(goal_amount),
                    years=int(years),
                    n_sims=int(n_sims),
                    annual_return_mean=mean,
                    annual_return_std=std,
                )
                
                st.markdown("---")
                st.markdown("#### Simulation Results")
                st.caption(f"Based on {n_sims:,} simulations over {years} years")
                
                # Main result
                prob_pct = res['probability'] * 100
                if prob_pct >= 75:
                    st.success(f"🎉 **{prob_pct:.1f}%** chance to reach your goal of ${goal_amount:,.0f}")
                    st.info("**Excellent probability!** Your current savings trajectory and expected returns make this goal highly achievable.")
                elif prob_pct >= 50:
                    st.warning(f"⚠️ **{prob_pct:.1f}%** chance to reach your goal of ${goal_amount:,.0f}")
                    st.info("**Moderate probability.** Consider increasing savings rate, extending timeline, or adjusting goal amount for better odds.")
                else:
                    st.error(f"📉 **{prob_pct:.1f}%** chance to reach your goal of ${goal_amount:,.0f}")
                    st.info("**Low probability.** This goal may be challenging with current parameters. Consider: reducing goal amount, extending timeline, increasing savings, or improving expected returns through better asset allocation.")
                
                # Additional metrics
                st.markdown("**Projected Outcomes**")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Median End Value", f"${res['median_end_value']:,.0f}")
                    st.caption("50% of simulations ended above this value")
                with col2:
                    st.metric("10th Percentile", f"${res['pct10']:,.0f}")
                    st.caption("Worst-case scenario (10% of outcomes)")
                with col3:
                    st.metric("90th Percentile", f"${res['pct90']:,.0f}")
                    st.caption("Best-case scenario (10% of outcomes)")
                
                # Show simulation parameters
                with st.expander("📊 View Simulation Parameters"):
                    st.json(res["params"])
                    
            except Exception as e:
                st.error(f"Simulation failed: {e}")

