# app/mock_data.py
"""
Mock data module for local MVP development without Firestore dependency.
Provides dummy user data, PFS snapshots, and portfolio data.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Environment flag to enable mock mode
MOCK_MODE = True  # Set to False to use real Firestore

# -----------------------------------------------------
# Mock PFS Data (Personal Financial Snapshot)
# -----------------------------------------------------

@dataclass
class MockPFS:
    """Mock Personal Financial Snapshot"""
    id: str
    user_id: str = "mock_user_001"
    currency: str = "USD"
    
    # Income & expenses (per month)
    gross_income: float = 12000.0
    net_income: float = 9000.0
    fixed_expenses: float = 3500.0
    variable_expenses: float = 1500.0
    
    # Assets
    cash_and_equivalents: float = 50000.0
    investments: float = 150000.0
    real_estate: float = 400000.0
    other_assets: float = 25000.0
    
    # Liabilities
    short_term_debt: float = 5000.0
    long_term_debt: float = 300000.0
    other_liabilities: float = 0.0
    
    # Investor profile
    risk_tolerance: str = "moderate"
    investment_horizon_years: int = 15
    goal_type: str = "retirement"
    
    # Computed fields
    net_worth: float = 320000.0  # (50k+150k+400k+25k) - (5k+300k)
    monthly_savings: float = 4000.0  # net_income - expenses
    savings_rate: float = 44.4  # (4000/9000) * 100
    
    created_at: datetime = None
    updated_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now() - timedelta(days=180)
        if self.updated_at is None:
            self.updated_at = datetime.now()


# Pre-defined mock users with different profiles
MOCK_USERS = {
    "mock_user_001": {
        "conservative": MockPFS(
            id="pfs_conservative_001",
            user_id="mock_user_001",
            risk_tolerance="conservative",
            investment_horizon_years=5,
            net_income=6000.0,
            investments=80000.0,
            net_worth=150000.0,
            monthly_savings=2000.0,
            savings_rate=33.3,
        ),
        "moderate": MockPFS(
            id="pfs_moderate_001",
            user_id="mock_user_001",
            risk_tolerance="moderate",
            investment_horizon_years=15,
            net_income=9000.0,
            investments=150000.0,
            net_worth=320000.0,
            monthly_savings=4000.0,
            savings_rate=44.4,
        ),
        "aggressive": MockPFS(
            id="pfs_aggressive_001",
            user_id="mock_user_001",
            risk_tolerance="aggressive",
            investment_horizon_years=25,
            net_income=15000.0,
            investments=300000.0,
            net_worth=600000.0,
            monthly_savings=8000.0,
            savings_rate=53.3,
        ),
    },
    "anonymous": {
        "moderate": MockPFS(
            id="pfs_anonymous_001",
            user_id="anonymous",
            risk_tolerance="moderate",
            investment_horizon_years=10,
            net_income=7000.0,
            investments=100000.0,
            net_worth=200000.0,
            monthly_savings=3000.0,
            savings_rate=42.9,
        ),
    }
}


# Default mock PFS to use when no user profile exists
DEFAULT_MOCK_PFS = MOCK_USERS["mock_user_001"]["moderate"]


def get_mock_pfs_for_user(user_id: str = "mock_user_001", risk_profile: str = "moderate") -> MockPFS:
    """
    Get mock PFS data for a user.
    
    Args:
        user_id: User identifier (default: mock_user_001)
        risk_profile: Risk tolerance level (conservative/moderate/aggressive)
    
    Returns:
        MockPFS object with dummy financial data
    """
    if user_id in MOCK_USERS:
        if risk_profile in MOCK_USERS[user_id]:
            return MOCK_USERS[user_id][risk_profile]
        # Default to moderate if profile not found
        return MOCK_USERS[user_id].get("moderate", DEFAULT_MOCK_PFS)
    
    # Return anonymous user data for unknown users
    return MOCK_USERS["anonymous"]["moderate"]


def get_mock_pfs_history(user_id: str = "mock_user_001", months: int = 12) -> List[MockPFS]:
    """
    Generate mock PFS history for time-series analysis.
    Creates historical snapshots with gradual growth over time.
    
    Args:
        user_id: User identifier
        months: Number of months of history to generate
    
    Returns:
        List of MockPFS objects representing historical snapshots
    """
    base_pfs = get_mock_pfs_for_user(user_id)
    history = []
    
    for i in range(months, 0, -1):
        # Create historical snapshot with gradual growth
        growth_factor = 1.0 - (i * 0.01)  # 1% growth per month backwards
        
        historical_pfs = MockPFS(
            id=f"pfs_{user_id}_{i}",
            user_id=user_id,
            currency=base_pfs.currency,
            gross_income=base_pfs.gross_income * growth_factor,
            net_income=base_pfs.net_income * growth_factor,
            fixed_expenses=base_pfs.fixed_expenses * growth_factor,
            variable_expenses=base_pfs.variable_expenses * growth_factor,
            cash_and_equivalents=base_pfs.cash_and_equivalents * growth_factor,
            investments=base_pfs.investments * growth_factor,
            real_estate=base_pfs.real_estate,  # Real estate stays constant
            other_assets=base_pfs.other_assets * growth_factor,
            short_term_debt=base_pfs.short_term_debt * (1.0 + (i * 0.005)),  # Debt decreases
            long_term_debt=base_pfs.long_term_debt * (1.0 + (i * 0.002)),
            other_liabilities=base_pfs.other_liabilities,
            risk_tolerance=base_pfs.risk_tolerance,
            investment_horizon_years=base_pfs.investment_horizon_years,
            goal_type=base_pfs.goal_type,
            net_worth=base_pfs.net_worth * growth_factor,
            monthly_savings=base_pfs.monthly_savings * growth_factor,
            savings_rate=base_pfs.savings_rate,
            created_at=datetime.now() - timedelta(days=30 * i),
            updated_at=datetime.now() - timedelta(days=30 * i),
        )
        history.append(historical_pfs)
    
    # Add current snapshot
    history.append(base_pfs)
    return history


# -----------------------------------------------------
# Mock Portfolio Data
# -----------------------------------------------------

MOCK_PORTFOLIO = {
    "mock_user_001": {
        "holdings": [
            {"ticker": "AAPL", "quantity": 50, "market_value": 8500, "sector": "Technology"},
            {"ticker": "MSFT", "quantity": 30, "market_value": 12000, "sector": "Technology"},
            {"ticker": "JPM", "quantity": 40, "market_value": 6800, "sector": "Financials"},
            {"ticker": "JNJ", "quantity": 35, "market_value": 5600, "sector": "Healthcare"},
            {"ticker": "XOM", "quantity": 60, "market_value": 6300, "sector": "Energy"},
        ],
        "total_value": 39200,
        "sector_allocation": {
            "Technology": 52.3,
            "Financials": 17.3,
            "Healthcare": 14.3,
            "Energy": 16.1,
        }
    },
    "anonymous": {
        "holdings": [],
        "total_value": 0,
        "sector_allocation": {}
    }
}


def get_mock_portfolio(user_id: str = "mock_user_001") -> Dict[str, Any]:
    """Get mock portfolio data for a user."""
    return MOCK_PORTFOLIO.get(user_id, MOCK_PORTFOLIO["anonymous"])


# -----------------------------------------------------
# Mock Twin Data (Personal Financial Twin)
# -----------------------------------------------------

@dataclass
class MockTwin:
    """Mock Personal Financial Twin with computed metrics"""
    user_id: str
    mode: str = "lite"  # lite or full
    created_at: datetime = None
    
    # Core metrics (available in both modes)
    latest_pfs: MockPFS = None
    stress_index: float = 0.15  # 0-1 scale (0.15 = low stress)
    financial_health_score: float = 75.0  # 0-100 scale
    
    # Risk capacity
    risk_capacity: Dict[str, Any] = None
    emergency_fund_coverage: float = 6.0  # months
    
    # Growth metrics (full mode only)
    net_worth_cagr: Optional[float] = None  # Compound annual growth rate
    avg_savings_rate: Optional[float] = None
    savings_rate_trend_pct_per_year: Optional[float] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        
        if self.risk_capacity is None:
            # Calculate risk capacity based on PFS
            portfolio_value = 0.0
            if self.latest_pfs:
                portfolio_value = (self.latest_pfs.investments or 0.0) + (self.latest_pfs.cash_and_equivalents or 0.0)
            
            self.risk_capacity = {
                "max_single_percent": 5.0,  # 5% of portfolio
                "max_single_dollars": portfolio_value * 0.05,
                "max_sector_percent": 25.0,
                "suggested_position_size": portfolio_value * 0.03,  # 3% suggested
            }
        
        # Full mode metrics
        if self.mode == "full":
            self.net_worth_cagr = 0.12  # 12% annual growth
            self.avg_savings_rate = self.latest_pfs.savings_rate if self.latest_pfs else 40.0
            self.savings_rate_trend_pct_per_year = 2.5  # 2.5% improvement per year
    
    def to_dict(self):
        """Convert to dictionary for compatibility"""
        return {
            "user_id": self.user_id,
            "mode": self.mode,
            "stress_index": self.stress_index,
            "financial_health_score": self.financial_health_score,
            "risk_capacity": self.risk_capacity,
            "emergency_fund_coverage": self.emergency_fund_coverage,
            "net_worth_cagr": self.net_worth_cagr,
            "avg_savings_rate": self.avg_savings_rate,
            "savings_rate_trend_pct_per_year": self.savings_rate_trend_pct_per_year,
        }


def get_mock_twin(user_id: str = "mock_user_001", mode: str = "lite") -> MockTwin:
    """
    Get mock twin data for a user.
    
    Args:
        user_id: User identifier
        mode: 'lite' for fast queries, 'full' for comprehensive analysis
    
    Returns:
        MockTwin object with financial twin metrics
    """
    latest_pfs = get_mock_pfs_for_user(user_id)
    
    return MockTwin(
        user_id=user_id,
        mode=mode,
        latest_pfs=latest_pfs,
        stress_index=0.15 if latest_pfs.risk_tolerance == "conservative" else 0.25,
        financial_health_score=85.0 if latest_pfs.net_worth > 300000 else 70.0,
    )


# -----------------------------------------------------
# Mock Stock Metrics (Firestore replacement)
# -----------------------------------------------------

MOCK_STOCK_METRICS = {
    "AAPL": {
        "derived_metrics": {
            "piotroski_f_score": 8,
            "altman_z_score": 3.5,
            "roic": 0.28,
            "croic": 0.25,
            "market_cap": 2800000000000,
        },
        "latest_financials": {
            "date": "2023-12-31",
            "revenue": 383285000000,
            "net_income": 96995000000,
            "total_assets": 352755000000,
        }
    },
    "MSFT": {
        "derived_metrics": {
            "piotroski_f_score": 7,
            "altman_z_score": 4.2,
            "roic": 0.32,
            "croic": 0.29,
            "market_cap": 2900000000000,
        },
        "latest_financials": {
            "date": "2023-12-31",
            "revenue": 211915000000,
            "net_income": 72361000000,
            "total_assets": 411976000000,
        }
    },
}


def get_mock_stock_metrics(ticker: str) -> Optional[Dict[str, Any]]:
    """Get mock stock metrics from predefined data."""
    return MOCK_STOCK_METRICS.get(ticker.upper())


# -----------------------------------------------------
# Helper function to check if mock mode is enabled
# -----------------------------------------------------

def is_mock_mode() -> bool:
    """Check if the app is running in mock data mode."""
    return MOCK_MODE


def set_mock_mode(enabled: bool):
    """Enable or disable mock data mode."""
    global MOCK_MODE
    MOCK_MODE = enabled
    logger.info(f"Mock data mode {'enabled' if enabled else 'disabled'}")


# -----------------------------------------------------
# Logging for debugging
# -----------------------------------------------------

logger.info(f"Mock data module initialized. Mock mode: {MOCK_MODE}")
