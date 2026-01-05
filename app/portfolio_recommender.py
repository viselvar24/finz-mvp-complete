# app/portfolio_recommender.py
"""
Centralized portfolio recommendation logic.
Used consistently across Dashboard and Chat to provide the same recommendations.
"""

from typing import Dict, Optional, Any


def calculate_recommended_portfolio(
    latest_pfs,
    twin=None,
    health_score: Optional[int] = None,
    wealth_stage: Optional[str] = None
) -> Dict[str, float]:
    """
    Calculate recommended portfolio allocation based on user's financial profile,
    risk tolerance, life stage, financial health, and market conditions.
    
    This is the SINGLE SOURCE OF TRUTH for portfolio recommendations across the entire system.
    Both Dashboard and Chat use this function to ensure consistency.
    
    Args:
        latest_pfs: PFS object with user's financial data
        twin: Optional financial twin object (for stress index)
        health_score: Optional financial health score (0-100)
        wealth_stage: Optional wealth stage string
    
    Returns:
        Dictionary with asset class allocations (percentages)
    """
    if not latest_pfs:
        # Return default moderate allocation if no PFS
        return {
            "Cash": 10.0,
            "Bonds": 25.0,
            "Commodities": 5.0,
            "Real Estate": 15.0,
            "ETFs": 25.0,
            "Stocks": 20.0,
        }
    
    # Base allocations by risk tolerance
    risk_tolerance = latest_pfs.risk_tolerance.lower() if latest_pfs.risk_tolerance else "moderate"
    
    # Get age-based factor (if investment horizon is available)
    investment_horizon = latest_pfs.investment_horizon_years if latest_pfs.investment_horizon_years else 10
    age_factor = min(investment_horizon / 30.0, 1.0)  # Normalize to 0-1
    
    # Get twin metrics for behavior-based adjustments
    stress_index = twin.stress_index if twin and hasattr(twin, 'stress_index') else 0.5
    financial_health_factor = (health_score / 100.0) if health_score else 0.5
    
    # Macro factor adjustment (simplified - can be enhanced with real economic data)
    macro_equity_bias = 0.0  # -0.1 to +0.1 adjustment based on market conditions
    
    # Base allocations by risk profile
    if risk_tolerance == "conservative":
        base_allocation = {
            "Cash": 15.0,
            "Bonds": 40.0,
            "Commodities": 5.0,
            "Real Estate": 15.0,
            "ETFs": 15.0,
            "Stocks": 10.0,
        }
    elif risk_tolerance == "aggressive":
        base_allocation = {
            "Cash": 5.0,
            "Bonds": 10.0,
            "Commodities": 5.0,
            "Real Estate": 10.0,
            "ETFs": 30.0,
            "Stocks": 40.0,
        }
    else:  # moderate (default)
        base_allocation = {
            "Cash": 10.0,
            "Bonds": 25.0,
            "Commodities": 5.0,
            "Real Estate": 15.0,
            "ETFs": 25.0,
            "Stocks": 20.0,
        }
    
    # Adjust based on age/investment horizon (younger = more equities)
    if age_factor > 0.7:  # Long horizon (young investor)
        base_allocation["Stocks"] += 5
        base_allocation["ETFs"] += 5
        base_allocation["Bonds"] -= 10
    elif age_factor < 0.3:  # Short horizon (near retirement)
        base_allocation["Bonds"] += 10
        base_allocation["Cash"] += 5
        base_allocation["Stocks"] -= 10
        base_allocation["ETFs"] -= 5
    
    # Adjust based on financial stress (high stress = more conservative)
    if stress_index > 0.7:  # High stress
        base_allocation["Cash"] += 5
        base_allocation["Bonds"] += 5
        base_allocation["Stocks"] -= 5
        base_allocation["ETFs"] -= 5
    elif stress_index < 0.3:  # Low stress
        base_allocation["Stocks"] += 3
        base_allocation["ETFs"] += 3
        base_allocation["Cash"] -= 6
    
    # Adjust based on financial health (better health = can take more risk)
    if financial_health_factor > 0.8:  # Excellent health
        base_allocation["Stocks"] += 5
        base_allocation["Real Estate"] += 5
        base_allocation["Cash"] -= 5
        base_allocation["Bonds"] -= 5
    elif financial_health_factor < 0.5:  # Poor health
        base_allocation["Cash"] += 10
        base_allocation["Stocks"] -= 5
        base_allocation["ETFs"] -= 5
    
    # Adjust based on wealth stage (accumulation vs preservation)
    if wealth_stage:
        if "Foundation" in wealth_stage or "Beginner" in wealth_stage:
            # Early stage: focus on cash reserves and diversified ETFs
            base_allocation["Cash"] += 5
            base_allocation["ETFs"] += 5
            base_allocation["Stocks"] -= 5
            base_allocation["Real Estate"] -= 5
        elif "Ultra High" in wealth_stage or "High Net Worth" in wealth_stage:
            # Wealth preservation: more real estate and bonds
            base_allocation["Real Estate"] += 10
            base_allocation["Bonds"] += 5
            base_allocation["Stocks"] -= 10
            base_allocation["ETFs"] -= 5
    
    # Apply macro factor adjustment (shift between equities and bonds)
    if macro_equity_bias != 0:
        equity_shift = macro_equity_bias * 10  # -10% to +10%
        base_allocation["Stocks"] += equity_shift / 2
        base_allocation["ETFs"] += equity_shift / 2
        base_allocation["Bonds"] -= equity_shift
    
    # Ensure all values are non-negative
    for key in base_allocation:
        base_allocation[key] = max(0, base_allocation[key])
    
    # Ensure minimum cash allocation (at least 3% for emergency liquidity)
    if base_allocation["Cash"] < 3.0:
        base_allocation["Cash"] = 3.0
    
    # Normalize to 100%
    total = sum(base_allocation.values())
    if total > 0:
        for key in base_allocation:
            base_allocation[key] = (base_allocation[key] / total) * 100
    
    return base_allocation


def get_allocation_explanation(
    allocation: Dict[str, float],
    latest_pfs,
    wealth_stage: Optional[str] = None,
    health_score: Optional[int] = None
) -> str:
    """
    Generate human-readable explanation for why this allocation was recommended.
    
    Args:
        allocation: The recommended allocation percentages
        latest_pfs: User's PFS data
        wealth_stage: User's wealth stage
        health_score: Financial health score
    
    Returns:
        Markdown-formatted explanation text
    """
    risk_tolerance = latest_pfs.risk_tolerance if latest_pfs and latest_pfs.risk_tolerance else "moderate"
    investment_horizon = latest_pfs.investment_horizon_years if latest_pfs and latest_pfs.investment_horizon_years else 10
    
    # Find dominant asset class
    sorted_alloc = sorted(allocation.items(), key=lambda x: x[1], reverse=True)
    top_asset = sorted_alloc[0][0] if sorted_alloc else "Balanced"
    
    explanation = f"""
### Why this allocation fits YOUR situation

**Risk Profile:** {risk_tolerance.capitalize()}
- Your {risk_tolerance} risk tolerance shapes the core allocation
- Investment horizon of {investment_horizon} years allows for {"long-term growth focus" if investment_horizon > 15 else "balanced approach"}

**Key Factors:**
"""
    
    if wealth_stage:
        explanation += f"- **Wealth Stage:** {wealth_stage} - Strategy aligned with your financial maturity\n"
    
    if health_score:
        health_status = "Excellent" if health_score >= 75 else ("Good" if health_score >= 55 else "Needs improvement")
        explanation += f"- **Financial Health:** {health_score}/100 ({health_status}) - Influences risk capacity\n"
    
    if latest_pfs:
        if latest_pfs.monthly_savings:
            explanation += f"- **Savings Capacity:** ${latest_pfs.monthly_savings:,.0f}/month supports systematic investing\n"
        
        if latest_pfs.net_worth:
            explanation += f"- **Net Worth:** ${latest_pfs.net_worth:,.0f} provides foundation for growth\n"
    
    explanation += f"""
**Allocation Strategy:**
- Primary focus: **{top_asset}** ({allocation[top_asset]:.1f}%) for {"stability and income" if top_asset == "Bonds" else ("liquidity" if top_asset == "Cash" else "growth potential")}
- Diversification across {len([v for v in allocation.values() if v > 0])} asset classes
- Balanced exposure to minimize concentration risk

**What makes this personalized:**
This isn't a generic allocation - it's customized based on YOUR complete financial profile, including risk tolerance, time horizon, financial health, and wealth stage. As your situation evolves, so will these recommendations.
"""
    
    return explanation
