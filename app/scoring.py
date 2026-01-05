# app/scoring.py
# Add the Perfient Fit Score implementation
from typing import Optional, Dict, Any
import math

def simple_score(fundamentals, recent_returns, sentiment_score):
    """
    Rule-based score 0-100 combining several signals. Keep interpretable for MVP.
    fundamentals: dict with marketCap, previousClose
    recent_returns: dict like {'7d':0.02}
    sentiment_score: -1..1
    """
    score = 50.0
    mc = fundamentals.get('marketCap') or 0
    if mc > 50_000_000_000:
        score += 12
    elif mc > 5_000_000_000:
        score += 8
    elif mc > 500_000_000:
        score += 4
    # momentum
    r7 = recent_returns.get('7d', 0)
    if r7 > 0.05:
        score += 10
    elif r7 > 0.02:
        score += 5
    elif r7 < -0.05:
        score -= 8
    # sentiment
    score += sentiment_score * 10
    return max(0.0, min(100.0, score))

    
def _exposure_penalty(pfs, ticker):
    """
    Simple heuristic penalty: if user's cash->investments ratio is low,
    or if user has stated conservative risk and score is high, reduce fit.
    This is intentionally simple for MVP and easy to expand.
    """
    if not pfs:
        return 0.0
    # penalty by risk mismatch
    rt = (pfs.risk_tolerance or "").lower()
    if rt.startswith("conserv"):
        return 0.15
    if rt.startswith("aggress"):
        return -0.05
    return 0.0

def fit_score(profile_obj, ticker, ticker_score, price=None):
    """
    Returns fit score in 0..1 combining ticker_score (0..100) with
    user profile heuristics. Lower if mismatch with risk tolerance or
    when buying would exceed a typical single-position budget.
    """
    base = max(0.0, min(100.0, float(ticker_score or 50.0)))
    # normalize to 0..1
    base_norm = base / 100.0

    # penalty from PFS & exposures
    penalty = 0.0
    try:
        penalty += _exposure_penalty(profile_obj, ticker)
        # if profile exists, estimate position dollar size limit
        if profile_obj:
            # assume max single position = 5% of investments by default
            max_pct = 0.05
            # if conservative, shrink to 2%
            if (profile_obj.risk_tolerance or "").lower().startswith("conserv"):
                max_pct = 0.02
            # if price known, compute implied shares for 1-share buy and scale penalty if price too high
            if price and price > 0:
                # if price would require > max dollar (very expensive single share), slightly penalize
                if price > (profile_obj.investments * max_pct):
                    penalty += 0.1
    except Exception:
        penalty += 0.0

    fit = base_norm - penalty
    # clamp 0..1
    if fit < 0.0:
        fit = 0.0
    if fit > 1.0:
        fit = 1.0
    return fit

# Helper normalizers
def _norm_clip(x, lo=0.0, hi=1.0):
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return 0.0

def _safe_div(a, b, default=0.0):
    try:
        return a / b if b != 0 else default
    except Exception:
        return default

def _to_01_by_rank(value, low, high):
    """
    Simple linear normalization: maps value in [low, high] -> [0,1].
    Values below low -> 0, above high -> 1.
    """
    if value is None:
        return 0.0
    if low == high:
        return 0.0
    return _norm_clip((value - low) / (high - low), 0.0, 1.0)


def perfient_fit_score(
    profile_obj: Optional[Any],
    ticker: str,
    ticker_profile: Optional[Dict[str, Any]] = None,
    price: Optional[float] = None,
    recent_returns: Optional[Dict[str, float]] = None,
    volatility: Optional[float] = None,
    sector_exposure: Optional[float] = None,
    perfient_intrinsic: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
    debug: bool = False,
) -> Dict[str, Any]:
    """
    Compute Perfient Fit Score for (user profile, ticker).
    Returns dict: {
      'fit': 0..1,
      'components': {'F':..., 'V':..., 'M':..., 'Vol':..., 'Q':..., 'P':..., 'U':...},
      'weights': {...},
      'explain': "human readable summary"
    }
    Inputs:
      - profile_obj: PFSOut or None (see app/pfs_service.py). Use its fields risk_tolerance, investment_horizon_years, investments, cash_and_equivalents, net_worth.
      - ticker_profile: dict from fetch_company_profile() (may contain marketCap, previousClose, sector)
      - price: latest price (float)
      - recent_returns: dict like {'7d':0.02, '30d':0.05}
      - volatility: e.g., 30-day stddev (annualized) or None
      - sector_exposure: if user holdings contain percent in same sector -> 0..1 (None if unknown)
      - perfient_intrinsic: Perfient intrinsic value (median of valuation models with 20% margin of safety)
    """

    # --- default weights ---
    default_weights = {
        'F': 0.20,  # fundamentals
        'V': 0.15,  # valuation
        'M': 0.15,  # momentum
        'Vol': 0.15, # volatility (inverse)
        'Q': 0.10,  # quality / balance-sheet proxy
        'P': 0.10,  # portfolio compatibility
        'U': 0.15,  # user profile fit
    }
    w = weights or default_weights

    # --- gather raw signals with safe defaults ---
    # 1) Fundamentals (use marketCap as proxy + call simple_score baseline scaled)
    market_cap = None
    if ticker_profile:
        market_cap = ticker_profile.get('marketCap') or ticker_profile.get('market_cap') or None

    # base_score: reuse simple_score if available (0..100)
    try:
        base_score = simple_score(ticker_profile or {}, recent_returns or {}, 0.0)
        base_norm = _norm_clip(base_score / 100.0)
    except Exception:
        base_norm = 0.0

    # Fundamental strength: map market cap tiers and base_norm
    if market_cap is None:
        F = base_norm
    else:
        # map very small -> 0, mid -> 0.5, mega -> 1.0
        if market_cap > 50_000_000_000:
            mc_score = 1.0
        elif market_cap > 5_000_000_000:
            mc_score = 0.7
        elif market_cap > 500_000_000:
            mc_score = 0.5
        else:
            mc_score = 0.3
        # combine with base_norm
        F = _norm_clip(0.6 * base_norm + 0.4 * mc_score)

    # 2) Valuation V: based on Perfient intrinsic value vs current price
    # If price < intrinsic -> undervalued (high V), if price > intrinsic -> overvalued (low V)
    if perfient_intrinsic is None or perfient_intrinsic <= 0 or price is None or price <= 0:
        # Fallback to neutral if no intrinsic value available
        V = 0.5
    else:
        # Calculate discount/premium percentage
        discount = (perfient_intrinsic - price) / perfient_intrinsic
        # discount > 0 means undervalued (good), discount < 0 means overvalued (bad)
        # Map: +50% discount -> V=1.0, 0% -> V=0.5, -50% premium -> V=0.0
        if discount >= 0.5:
            V = 1.0
        elif discount <= -0.5:
            V = 0.0
        else:
            # Linear mapping: discount in [-0.5, 0.5] maps to V in [0.0, 1.0]
            V = 0.5 + discount  # discount=0.5->1.0, discount=0->0.5, discount=-0.5->0.0
        V = _norm_clip(V)

    # 3) Momentum M: map 7d and 30d into 0..1
    m7 = (recent_returns or {}).get('7d')
    m30 = (recent_returns or {}).get('30d')
    if m7 is None and m30 is None:
        M = 0.0
    else:
        # simple combination
        m7s = _to_01_by_rank((m7 or 0.0), -0.1, 0.2)
        m30s = _to_01_by_rank((m30 or 0.0), -0.2, 0.6)
        M = _norm_clip(0.6 * m30s + 0.4 * m7s)

    # 4) Volatility: lower vol -> higher score
    if volatility is None:
        Vol = 0.0
    else:
        # Suppose volatility in pct (0.2 = 20% annualized). define 0..1 mapping: 0.0->1.0, 0.6->0.0
        Vol = 1.0 - _to_01_by_rank(volatility, 0.0, 0.6)

    # 5) Quality Q: small proxy: if market_cap large -> more quality, else neutral
    if market_cap is None:
        Q = 0.0
    else:
        if market_cap > 100_000_000_000:
            Q = 0.9
        elif market_cap > 10_000_000_000:
            Q = 0.7
        elif market_cap > 1_000_000_000:
            Q = 0.5
        else:
            Q = 0.35

    # 6) Portfolio compatibility P: if sector_exposure known, penalize high existing exposure
    if sector_exposure is None:
        P = 0.0
    else:
        # if >40% in sector => penalty
        P = 1.0 - _to_01_by_rank(sector_exposure, 0.0, 0.6)  # exposure 0->1 ; 60%->0
        P = _norm_clip(P)

    # 7) User profile fit U: risk tolerance & horizon
    U = 0.0
    try:
        if profile_obj:
            rt = (profile_obj.risk_tolerance or "").lower() if getattr(profile_obj, "risk_tolerance", None) is not None else ""
            horizon = getattr(profile_obj, "investment_horizon_years", None)
            # if high volatility & user conservative -> lower
            if rt.startswith("conserv"):
                # penalize if volatility > 0.25
                if volatility and volatility > 0.25:
                    U = 0.25
                else:
                    U = 0.6
            elif rt.startswith("aggress"):
                U = 0.8
            else:
                U = 0.6
            # horizon adjustment: short horizon (<3y) should reduce fit for risky assets (high vol)
            if horizon is not None and horizon < 3:
                if volatility and volatility > 0.20:
                    U = min(U, 0.4)
    except Exception:
        U = 0.0

    # --- compute weighted sum ---
    components = {'F': _norm_clip(F), 'V': _norm_clip(V), 'M': _norm_clip(M),
                  'Vol': _norm_clip(Vol), 'Q': _norm_clip(Q), 'P': _norm_clip(P), 'U': _norm_clip(U)}
    total_weight = sum(w.values()) or 1.0
    fit_raw = 0.0
    for k, val in components.items():
        fit_raw += w.get(k, 0.0) * val

    fit = _norm_clip(fit_raw / total_weight)

    # build explanation
    explain = (
        f"Fit={fit:.2f} = "
        f"{w['F']*100:.0f}%*F({components['F']:.2f}) + "
        f"{w['V']*100:.0f}%*V({components['V']:.2f}) + "
        f"{w['M']*100:.0f}%*M({components['M']:.2f}) + "
        f"{w['Vol']*100:.0f}%*Vol({components['Vol']:.2f}) + "
        f"{w['Q']*100:.0f}%*Q({components['Q']:.2f}) + "
        f"{w['P']*100:.0f}%*P({components['P']:.2f}) + "
        f"{w['U']*100:.0f}%*U({components['U']:.2f})"
    )

    out = {
        'fit': fit,
        'components': components,
        'weights': w,
        'fit_raw': fit_raw,
        'explain': explain
    }
    if debug:
        out['debug_inputs'] = {
            'market_cap': market_cap,
            'price': price,
            'recent_returns': recent_returns,
            'volatility': volatility,
            'sector_exposure': sector_exposure,
            'profile': {
                'risk_tolerance': getattr(profile_obj, "risk_tolerance", None) if profile_obj else None,
                'investment_horizon_years': getattr(profile_obj, "investment_horizon_years", None) if profile_obj else None,
                'investments': getattr(profile_obj, "investments", None) if profile_obj else None,
            }
        }
    return out

