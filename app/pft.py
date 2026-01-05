# app/pft.py
"""
Personal Financial Twin (PFT) module.

===============================================================================
TWO MODES: LITE vs FULL
===============================================================================

**PFT Lite** (Default for real-time queries)
- Uses: Single latest PFS snapshot
- Speed: ~50-100ms
- Metrics: Essential only (stress_index, risk_capacity, emergency_fund_coverage)
- Use Cases:
  * Real-time chat query responses
  * Quick risk capacity lookups
  * Users with limited history (< 2 snapshots)
  * Mobile/responsive interfaces

**PFT Full** (For comprehensive analysis)
- Uses: Complete PFS history time-series
- Speed: ~500-1000ms (depends on history size)
- Metrics: All metrics including trends, CAGR, behavioral patterns, projections
- Use Cases:
  * Detailed financial analysis reports
  * Goal planning and forecasting
  * Trend analysis and behavioral profiling
  * Dashboard analytics

===============================================================================
CORE FUNCTIONALITY
===============================================================================

Builds a user's financial twin from PFS data and provides:
 - Time-series analysis (net worth, savings rate over time)
 - Growth metrics (CAGR, trends, momentum)
 - Risk metrics (stress index, debt ratios, runway)
 - Behavioral classification (saver types, patterns)
 - Risk capacity calculation (position sizing, budget)
 - Financial health composite score (0-100)
 - Monte Carlo goal attainment simulation
 - Persistence (Firestore caching with smart refresh)

===============================================================================
USAGE EXAMPLES
===============================================================================

# Quick query (lite mode - fast)
twin = get_or_build_twin(user_id, mode='lite')
max_position = twin.risk_capacity['max_single_dollars']

# Detailed analysis (full mode - comprehensive)
twin = get_or_build_twin(user_id, mode='full')
health_score = twin.financial_health_score
trend = twin.savings_rate_trend_pct_per_year

# Force rebuild with specific mode
twin = build_and_save_twin(user_id, mode='full')
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import math
import statistics
import random
import numpy as np  # sentence-transformers already depends on numpy; reuse
from copy import deepcopy
import os

# Check if we're in mock mode (for local development)
MOCK_MODE = os.getenv("MOCK_MODE", "true").lower() == "true"

# reuse your pfs_service helpers (already in repo)
from app.pfs_service import get_pfs_history_for_user, get_latest_pfs_for_user

if not MOCK_MODE:
    from google.cloud import firestore
    db_fs = firestore.Client()
else:
    db_fs = None

# Import encryption utilities
try:
    from app.encryption import encrypt_twin, decrypt_twin
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False
    import logging
    logging.warning("Encryption module not available - twin data will be stored unencrypted")

USERS_COLLECTION = "users"


@dataclass
class TwinSeriesPoint:
    created_at: datetime
    net_worth: float
    savings_rate: float
    monthly_savings: float


@dataclass
class PersonalFinancialTwin:
    user_id: str
    created_at: datetime
    # time series ordered ascending by date
    series: List[TwinSeriesPoint]
    # mode: 'lite' or 'full'
    mode: str = 'full'
    # summary metrics (computed)
    net_worth_cagr: Optional[float] = None
    net_worth_change_pct: Optional[float] = None
    avg_savings_rate: Optional[float] = None
    savings_rate_trend_pct_per_year: Optional[float] = None
    cash_runway_months: Optional[float] = None
    stress_index: Optional[float] = None
    behavioral_profile: Optional[str] = None
    risk_capacity: Optional[Dict[str, Any]] = None
    # Enhanced metrics for Full mode
    debt_to_income_ratio: Optional[float] = None
    emergency_fund_coverage: Optional[float] = None
    investment_allocation_quality: Optional[Dict[str, float]] = None
    financial_health_score: Optional[float] = None
    last_updated: Optional[datetime] = None

    def to_dict(self):
        d = asdict(self)
        # convert datetimes to iso strings for storing
        d["created_at"] = self.created_at.isoformat()
        d["last_updated"] = self.last_updated.isoformat() if self.last_updated else None
        d["mode"] = self.mode
        series_serial = []
        for s in self.series:
            series_serial.append({
                "created_at": s.created_at.isoformat(),
                "net_worth": s.net_worth,
                "savings_rate": s.savings_rate,
                "monthly_savings": s.monthly_savings,
            })
        d["series"] = series_serial
        return d

    @classmethod
    def from_dict(cls, d):
        series = []
        for s in d.get("series", []):
            series.append(TwinSeriesPoint(
                created_at = datetime.fromisoformat(s["created_at"]),
                net_worth = float(s["net_worth"]),
                savings_rate = float(s["savings_rate"]),
                monthly_savings = float(s.get("monthly_savings", 0.0)),
            ))
        obj = cls(
            user_id=d["user_id"],
            created_at=datetime.fromisoformat(d["created_at"]),
            series=series,
            mode=d.get("mode", "full"),
            net_worth_cagr=d.get("net_worth_cagr"),
            net_worth_change_pct=d.get("net_worth_change_pct"),
            avg_savings_rate=d.get("avg_savings_rate"),
            savings_rate_trend_pct_per_year=d.get("savings_rate_trend_pct_per_year"),
            cash_runway_months=d.get("cash_runway_months"),
            stress_index=d.get("stress_index"),
            behavioral_profile=d.get("behavioral_profile"),
            risk_capacity=d.get("risk_capacity"),
            debt_to_income_ratio=d.get("debt_to_income_ratio"),
            emergency_fund_coverage=d.get("emergency_fund_coverage"),
            investment_allocation_quality=d.get("investment_allocation_quality"),
            financial_health_score=d.get("financial_health_score"),
            last_updated=datetime.fromisoformat(d["last_updated"]) if d.get("last_updated") else None,
        )
        return obj


# -------------------------
# Builders & Metrics
# -------------------------
def build_twin_lite(user_id: str) -> Optional[PersonalFinancialTwin]:
    """
    PFT Lite: Fast twin creation using only the latest PFS snapshot.
    Computes essential metrics without time-series analysis.
    Uses middle values of ranges for internal processing.
    
    Use when:
    - Real-time query responsiveness is critical
    - User has limited PFS history (< 2 snapshots)
    - Doing quick risk capacity or stress index lookups
    """
    latest_pfs = get_latest_pfs_for_user(user_id)
    if not latest_pfs:
        return None
    
    # Create minimal series with single point - use middle values for ranges
    series = [TwinSeriesPoint(
        created_at=latest_pfs.created_at,
        net_worth=_parse_range_to_middle(latest_pfs.net_worth),
        savings_rate=_parse_range_to_middle(latest_pfs.savings_rate),
        monthly_savings=_parse_range_to_middle(latest_pfs.monthly_savings),
    )]
    
    twin = PersonalFinancialTwin(
        user_id=user_id,
        created_at=datetime.utcnow(),
        series=series,
        mode='lite',
        last_updated=datetime.utcnow(),
    )
    
    # Compute only essential metrics (fast path)
    _compute_lite_metrics(twin, latest_pfs)
    
    return twin


def _parse_range_to_middle(value) -> float:
    """
    Parse a range string to its middle value for Twin Lite processing.
    
    Examples:
        "10000-20000" -> 15000.0
        "50000-100000" -> 75000.0
        "5000" -> 5000.0 (if not a range)
        50000 -> 50000.0 (if already numeric)
        None -> 0.0
    
    Args:
        value: Can be string (range or numeric), float, int, or None
    
    Returns:
        float: Middle value of range or the value itself
    """
    if value is None:
        return 0.0
    
    # If already numeric, return it
    if isinstance(value, (int, float)):
        return float(value)
    
    # If string, check if it's a range
    if isinstance(value, str):
        value = value.strip()
        if '-' in value and not value.startswith('-'):
            # It's a range like "10000-20000"
            try:
                parts = value.split('-')
                if len(parts) == 2:
                    low = float(parts[0].strip())
                    high = float(parts[1].strip())
                    return (low + high) / 2.0
            except (ValueError, IndexError):
                pass
        
        # Try to parse as single number
        try:
            return float(value)
        except ValueError:
            return 0.0
    
    return 0.0


def _compute_lite_metrics(twin: PersonalFinancialTwin, latest_pfs):
    """
    Fast metric computation for PFT Lite mode using single snapshot.
    Uses middle values of ranges for internal processing.
    """
    # Basic savings rate - parse range to middle value
    twin.avg_savings_rate = _parse_range_to_middle(latest_pfs.savings_rate)
    
    # Simple stress index based on debt-to-income
    try:
        debt = _parse_range_to_middle(latest_pfs.mortgage) + _parse_range_to_middle(latest_pfs.other_liabilities)
        income = _parse_range_to_middle(latest_pfs.net_income)
        if income == 0.0:
            income = 1.0  # Avoid division by zero
        dti = debt / (income * 12.0) if income > 0 else 0.0
        # Normalize to 0-1: 0% debt = 0.1 stress, 100%+ debt = 0.9 stress
        twin.stress_index = min(0.9, 0.1 + (dti * 0.8))
        twin.debt_to_income_ratio = dti
    except Exception:
        twin.stress_index = 0.3
        twin.debt_to_income_ratio = None
    
    # Emergency fund coverage
    try:
        cash = _parse_range_to_middle(latest_pfs.cash_and_equivalents)
        monthly_expenses = _parse_range_to_middle(latest_pfs.fixed_expenses) + _parse_range_to_middle(latest_pfs.variable_expenses)
        twin.emergency_fund_coverage = (cash / monthly_expenses) if monthly_expenses > 0 else 0.0
        twin.cash_runway_months = twin.emergency_fund_coverage
    except Exception:
        twin.emergency_fund_coverage = None
        twin.cash_runway_months = None
    
    # Behavioral profile (simplified)
    if twin.avg_savings_rate >= 20:
        twin.behavioral_profile = "consistent_saver"
    elif twin.avg_savings_rate >= 10:
        twin.behavioral_profile = "moderate_saver"
    else:
        twin.behavioral_profile = "low_saver"
    
    # Risk capacity (simplified calculation)
    try:
        cash = _parse_range_to_middle(latest_pfs.cash_and_equivalents)
        investments = _parse_range_to_middle(latest_pfs.investments)
        monthly_expenses = _parse_range_to_middle(latest_pfs.fixed_expenses) + _parse_range_to_middle(latest_pfs.variable_expenses)
        monthly_savings = _parse_range_to_middle(latest_pfs.monthly_savings)
        
        rt = (latest_pfs.risk_tolerance or "").lower()
        rt_factor = 0.6 if rt.startswith("aggress") else (0.3 if rt.startswith("conserv") else 0.45)
        
        risk_budget_pct = max(0.01, min(0.3, (twin.avg_savings_rate / 100.0) * rt_factor + 0.02))
        max_single_pct = 0.05 if rt.startswith("aggress") else (0.02 if rt.startswith("conserv") else 0.035)
        max_single_dollars = (investments + cash) * max_single_pct
        
        twin.risk_capacity = {
            "cash": cash,
            "investments": investments,
            "monthly_expenses": monthly_expenses,
            "monthly_savings": monthly_savings,
            "runway_months": twin.cash_runway_months,
            "risk_budget_pct": risk_budget_pct,
            "max_single_pct": max_single_pct,
            "max_single_dollars": max_single_dollars,
        }
    except Exception:
        twin.risk_capacity = None


def build_twin_from_history(user_id: str, limit: int = 100, mode: str = 'full') -> Optional[PersonalFinancialTwin]:
    """
    Read PFS snapshots for user (ascending), build a PersonalFinancialTwin and compute metrics.
    """
    pfs_list = get_pfs_history_for_user(user_id, limit=limit)
    if not pfs_list:
        return None

    # build series
    series = []
    for p in pfs_list:
        series.append(TwinSeriesPoint(
            created_at = p.created_at,
            net_worth = p.net_worth,
            savings_rate = p.savings_rate,
            monthly_savings = p.monthly_savings,
        ))

    twin = PersonalFinancialTwin(
        user_id=user_id,
        created_at=datetime.utcnow(),
        series=series,
        last_updated=datetime.utcnow(),
    )

    # compute metrics
    compute_twin_metrics(twin)

    return twin


def compute_twin_metrics(twin: PersonalFinancialTwin):
    """
    Fill metrics on twin in-place:
    - net_worth_cagr (annualized)
    - net_worth_change_pct (recent)
    - avg_savings_rate, savings_rate_trend_pct_per_year
    - cash_runway_months
    - stress_index
    - behavioral_profile
    - risk_capacity (dict)
    """
    series = twin.series
    if not series:
        return twin

    # ensure sorted ascending
    series = sorted(series, key=lambda s: s.created_at)
    twin.series = series

    # net worth change & CAGR
    start = series[0]
    end = series[-1]
    months = max(1, (end.created_at.year - start.created_at.year) * 12 + (end.created_at.month - start.created_at.month))
    try:
        change = (end.net_worth - start.net_worth) / abs(start.net_worth) if start.net_worth != 0 else None
    except Exception:
        change = None
    twin.net_worth_change_pct = change if change is not None else None

    # annualized CAGR (approx)
    if start.net_worth and start.net_worth > 0 and months >= 1:
        years = months / 12.0
        try:
            cagr = (end.net_worth / start.net_worth) ** (1.0 / years) - 1.0 if end.net_worth > 0 else -1.0
        except Exception:
            cagr = None
        twin.net_worth_cagr = float(cagr) if cagr is not None else None
    else:
        twin.net_worth_cagr = None

    # savings rate statistics
    srates = [s.savings_rate for s in series if s.savings_rate is not None]
    twin.avg_savings_rate = float(statistics.mean(srates)) if srates else None

    # trend of savings rate (simple linear slope per year, using first and last)
    if len(srates) >= 2:
        first_sr = srates[0]
        last_sr = srates[-1]
        try:
            years = months / 12.0
            twin.savings_rate_trend_pct_per_year = ((last_sr - first_sr) / max(1e-6, abs(first_sr))) / years if first_sr != 0 else (last_sr - first_sr) / years
        except Exception:
            twin.savings_rate_trend_pct_per_year = None
    else:
        twin.savings_rate_trend_pct_per_year = None

    # cash runway: average monthly expenses computed from last snapshot
    last = series[-1]
    # monthly expenses = fixed + variable if available in original PFS — approximate from savings/net income
    # monthly_savings = net_income - expenses -> expenses = net_income - monthly_savings
    # we don't have raw fields here; attempt best-effort:
    if last.savings_rate is not None and last.savings_rate >= 0 and getattr(last, "monthly_savings", None) is not None:
        # If monthly_savings is present (we stored it), we need net_income -> but not in twin; fallback to estimate runway on (cash + investments) / avg_monthly_expenses
        # Use last.monthly_savings available in TwinSeriesPoint
        try:
            monthly_savings = last.monthly_savings
            # If monthly_savings is 0 or small, runway is cash / small number but cap at large value
            # Pull cash and investments from user's latest PFS via get_latest_pfs_for_user when needed in runtime
            twin.cash_runway_months = None  # computed later if caller supplies latest PFS
        except Exception:
            twin.cash_runway_months = None
    else:
        twin.cash_runway_months = None

    # stress_index: volatility of monthly savings rate and net_worth drawdowns
    try:
        # compute month-to-month net_worth returns
        nw_values = [s.net_worth for s in series if s.net_worth is not None]
        if len(nw_values) >= 2:
            returns = []
            for i in range(1, len(nw_values)):
                prev = nw_values[i-1]
                curr = nw_values[i]
                if prev != 0:
                    returns.append((curr - prev) / prev)
            # stress = stddev of returns normalized to expected range
            vol = float(statistics.pstdev(returns)) if returns else 0.0
            # also consider savings volatility
            sr_vals = [s.monthly_savings for s in series if s.monthly_savings is not None]
            sv = float(statistics.pstdev(sr_vals)) if len(sr_vals) >= 2 else 0.0
            # combine scaled
            twin.stress_index = float(_sigmoid( (vol * 2.0) + (sv / (max(1.0, max(1.0, abs(max(sr_vals) if sr_vals else 0.0))))) ))
        else:
            twin.stress_index = 0.2
    except Exception:
        twin.stress_index = None

    # behavioral_profile: simple heuristics
    try:
        # use volatility of savings rate to classify
        sr_std = float(statistics.pstdev(srates)) if len(srates) >= 2 else 0.0
        if sr_std < 5.0:
            twin.behavioral_profile = "consistent_saver"
        elif sr_std < 15.0:
            twin.behavioral_profile = "variable_saver"
        else:
            twin.behavioral_profile = "volatile_spender"
    except Exception:
        twin.behavioral_profile = "unknown"

    # risk_capacity: compute simple metrics
    try:
        latest_pfs = get_latest_pfs_for_user(twin.user_id)
        cash = getattr(latest_pfs, "cash_and_equivalents", 0.0) if latest_pfs else 0.0
        investments = getattr(latest_pfs, "investments", 0.0) if latest_pfs else 0.0
        net_income = getattr(latest_pfs, "net_income", 0.0) if latest_pfs else 0.0
        fixed = getattr(latest_pfs, "fixed_expenses", 0.0) if latest_pfs else 0.0
        variable = getattr(latest_pfs, "variable_expenses", 0.0) if latest_pfs else 0.0
        monthly_expenses = fixed + variable
        monthly_savings = max(net_income - monthly_expenses, 0.0)
        # runway months on cash only
        runway = (cash / monthly_expenses) if monthly_expenses > 0 else None
        # conservative risk capacity: how much of investments could be exposed to risk (percent)
        # heuristic: risk_budget_pct = savings_rate_norm * risk_tolerance_factor
        savings_rate = twin.avg_savings_rate or 0.0
        rt = getattr(latest_pfs, "risk_tolerance", "") if latest_pfs else ""
        rt_factor = 0.6 if (rt and rt.lower().startswith("aggress")) else (0.3 if rt and rt.lower().startswith("conserv") else 0.45)
        risk_budget_pct = max(0.01, min(0.3, (savings_rate / 100.0) * rt_factor + 0.02))
        # max single position size (dollars)
        max_single_pct = 0.05 if rt and rt.lower().startswith("aggress") else (0.02 if rt and rt.lower().startswith("conserv") else 0.035)
        max_single_dollars = (investments + cash) * max_single_pct
        
        # Financial health score (composite 0-100)
        try:
            health_components = []
            # 1. Savings rate component (0-25 points)
            sr_score = min(25, (twin.avg_savings_rate or 0) / 20.0 * 25)
            health_components.append(sr_score)
            # 2. Debt-to-income component (0-25 points)
            debt = (getattr(latest_pfs, "mortgage", 0.0) or 0.0) + (getattr(latest_pfs, "other_liabilities", 0.0) or 0.0)
            annual_income = net_income * 12 if net_income else 0.0
            dti = (debt / annual_income) if annual_income > 0 else None
            if dti is not None:
                dti_score = max(0, 25 - (dti * 25))
                health_components.append(dti_score)
                twin.debt_to_income_ratio = dti
            # 3. Emergency fund component (0-25 points)
            if runway:
                ef_score = min(25, (runway / 6.0) * 25)  # 6 months = full score
                health_components.append(ef_score)
                twin.emergency_fund_coverage = runway
            # 4. Growth trajectory component (0-25 points)
            if twin.net_worth_cagr:
                growth_score = min(25, max(0, (twin.net_worth_cagr + 0.05) / 0.15 * 25))
                health_components.append(growth_score)
            
            twin.financial_health_score = sum(health_components) if health_components else None
        except Exception:
            twin.financial_health_score = None
        
        # Investment allocation quality (placeholder for future enhancement)
        twin.investment_allocation_quality = None
        
        twin.risk_capacity = {
            "cash": cash,
            "investments": investments,
            "monthly_expenses": monthly_expenses,
            "monthly_savings": monthly_savings,
            "runway_months": runway,
            "risk_budget_pct": risk_budget_pct,
            "max_single_pct": max_single_pct,
            "max_single_dollars": max_single_dollars,
        }
    except Exception:
        twin.risk_capacity = None

    twin.last_updated = datetime.utcnow()
    return twin


def _sigmoid(x):
    """bounded 0..1 mapping for stress combining"""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except Exception:
        return 0.0


# -------------------------
# Goal attainment simulation
# -------------------------
def simulate_goal_probability(
        twin: PersonalFinancialTwin,
        goal_amount: float,
        years: int = 5,
        n_sims: int = 2000,
        annual_return_mean: float = 0.06,
        annual_return_std: float = 0.12,
        annual_savings: Optional[float] = None,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
    """
    Monte-Carlo simulation to estimate probability of reaching `goal_amount` in `years`.
    - annual_return_mean / std are model assumptions
    - annual_savings: if None, infer from twin.risk_capacity['monthly_savings'] * 12
    Returns dict: {probability, sims_summary, params}
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)

    # start value = last net worth (use investments + cash ideally)
    if not twin.series:
        return {"probability": 0.0, "sims": []}
    start_val = twin.series[-1].net_worth
    if annual_savings is None:
        try:
            annual_savings = (twin.risk_capacity.get("monthly_savings", 0.0) * 12.0) if twin.risk_capacity else 0.0
        except Exception:
            annual_savings = 0.0

    dt = 1.0  # yearly step
    results = []
    # Geometric Brownian Motion yearly step (simple)
    mu = annual_return_mean
    sigma = annual_return_std

    for i in range(n_sims):
        val = start_val
        for y in range(years):
            # sample annual return
            r = np.random.normal(mu, sigma)
            val = val * (1.0 + r) + annual_savings
            # optional floor at -50% to avoid negative explosion
            if val < -abs(start_val) * 0.5:
                val = -abs(start_val) * 0.5
        results.append(val)

    results = np.array(results)
    prob = float((results >= goal_amount).sum()) / float(len(results))
    median = float(np.median(results))
    pct10 = float(np.percentile(results, 10))
    pct90 = float(np.percentile(results, 90))

    out = {
        "probability": prob,
        "median_end_value": median,
        "pct10": pct10,
        "pct90": pct90,
        "params": {
            "start_val": float(start_val),
            "annual_savings": float(annual_savings),
            "years": years,
            "n_sims": n_sims,
            "mean": mu,
            "std": sigma
        }
    }
    return out


# -------------------------
# Persistence helpers
# -------------------------
def _twin_doc_ref(user_id: str):
    return db_fs.collection(USERS_COLLECTION).document(user_id).collection("twin").document("latest")


def save_twin_snapshot(twin: PersonalFinancialTwin):
    doc_ref = _twin_doc_ref(twin.user_id)
    data = twin.to_dict()
    data["saved_at"] = datetime.utcnow()
    
    # Encrypt sensitive twin data before storing
    if ENCRYPTION_AVAILABLE:
        try:
            data = encrypt_twin(data)
            import logging
            logging.info(f"Twin data encrypted for user {twin.user_id}")
        except Exception as e:
            import logging
            logging.error(f"Twin encryption failed, storing unencrypted: {e}")
    
    doc_ref.set(data)
    return True


def load_twin_snapshot(user_id: str) -> Optional[PersonalFinancialTwin]:
    # Mock mode: return dummy twin
    if MOCK_MODE:
        from app.mock_data import get_mock_twin
        mock_twin_obj = get_mock_twin(user_id or "mock_user_001", mode="lite")
        
        # Convert MockTwin to PersonalFinancialTwin
        # Create series from latest_pfs
        series = []
        if mock_twin_obj.latest_pfs:
            series.append(TwinSeriesPoint(
                created_at=mock_twin_obj.latest_pfs.created_at,
                net_worth=mock_twin_obj.latest_pfs.net_worth,
                savings_rate=mock_twin_obj.latest_pfs.savings_rate,
                monthly_savings=mock_twin_obj.latest_pfs.monthly_savings,
            ))
        
        return PersonalFinancialTwin(
            user_id=user_id,
            created_at=mock_twin_obj.created_at,
            series=series,
            mode=mock_twin_obj.mode,
            stress_index=mock_twin_obj.stress_index,
            financial_health_score=mock_twin_obj.financial_health_score,
            risk_capacity=mock_twin_obj.risk_capacity,
            emergency_fund_coverage=mock_twin_obj.emergency_fund_coverage,
            net_worth_cagr=mock_twin_obj.net_worth_cagr,
            avg_savings_rate=mock_twin_obj.avg_savings_rate,
            savings_rate_trend_pct_per_year=mock_twin_obj.savings_rate_trend_pct_per_year,
            last_updated=mock_twin_obj.created_at,
        )
    
    # Production mode: use Firestore
    doc = _twin_doc_ref(user_id).get()
    if not doc.exists:
        return None
    
    data = doc.to_dict()
    
    # Decrypt twin data if encrypted
    if ENCRYPTION_AVAILABLE and data.get("_encrypted", False):
        try:
            data = decrypt_twin(data)
        except Exception as e:
            import logging
            logging.error(f"Failed to decrypt twin for user {user_id}: {e}")
            return None
    
    return PersonalFinancialTwin.from_dict(data)


# -------------------------
# Convenience wrapper: build, compute, persist
# -------------------------
def build_and_save_twin(user_id: str, limit: int = 100, mode: str = 'full') -> Optional[PersonalFinancialTwin]:
    """
    Build and save twin with specified mode.
    
    Args:
        user_id: User identifier
        limit: Max PFS history records to fetch (only for full mode)
        mode: 'lite' for fast snapshot-based twin, 'full' for comprehensive analysis
    """
    if mode == 'lite':
        twin = build_twin_lite(user_id)
    else:
        twin = build_twin_from_history(user_id, limit=limit, mode=mode)
    
    if twin:
        save_twin_snapshot(twin)
    return twin


def get_or_build_twin(user_id: str, mode: str = 'lite', max_age_hours: int = 24) -> Optional[PersonalFinancialTwin]:
    """
    Smart twin loader: returns cached twin if fresh enough, otherwise rebuilds.
    
    Args:
        user_id: User identifier
        mode: 'lite' or 'full'
        max_age_hours: Maximum age of cached twin before rebuilding
    
    Returns:
        PersonalFinancialTwin or None
    """
    # Try loading existing twin
    twin = load_twin_snapshot(user_id)
    
    # Check if we need to rebuild
    rebuild = False
    if not twin:
        rebuild = True
    elif twin.mode != mode:
        rebuild = True  # Mode mismatch
    elif twin.last_updated:
        age = datetime.utcnow() - twin.last_updated
        if age.total_seconds() / 3600 > max_age_hours:
            rebuild = True  # Too old
    
    if rebuild:
        twin = build_and_save_twin(user_id, mode=mode)
    
    return twin
