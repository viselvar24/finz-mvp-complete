import os
import requests
from datetime import datetime, timedelta



def fetch_price_df(ticker, period="6mo"):
    """Fetch historical prices for `ticker` using Tiingo.

    Returns a list of dicts with keys: date, open, high, low, close, volume
    """
    key = os.getenv("TIINGO_API_KEY")
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    headers = {"Authorization": f"Token {key}"} if key else {}

    # Compute a startDate based on 'period' (support simple forms like '6mo' and '1y')
    start_date = None
    try:
        now = datetime.utcnow().date()
        if isinstance(period, str) and period.endswith('mo'):
            months = int(period[:-2]) if period[:-2].isdigit() else 6
            start_date = now - timedelta(days=30 * months)
        elif isinstance(period, str) and period.endswith('y'):
            years = int(period[:-1]) if period[:-1].isdigit() else 1
            start_date = now - timedelta(days=365 * years)
    except Exception:
        start_date = None

    params = {}
    if start_date:
        params['startDate'] = start_date.isoformat()

    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        # Normalize to list of dicts
        out = []
        for item in data:
            out.append({
                'date': item.get('date'),
                'open': item.get('open'),
                'high': item.get('high'),
                'low': item.get('low'),
                'close': item.get('close'),
                'volume': item.get('volume')
            })
        return out
    except Exception:
        return None


def fetch_latest_price(ticker):
    """Fetch latest close price from Tiingo for `ticker`."""
    key = os.getenv("TIINGO_API_KEY")
    url = f"https://api.tiingo.com/tiingo/daily/{ticker}/prices"
    headers = {"Authorization": f"Token {key}"} if key else {}
    params = {"resampleFreq": "daily"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return None
        last = data[-1]
        return float(last.get('close')) if last.get('close') is not None else None
    except Exception:
        return None


def fetch_company_profile(ticker):
    """Return a minimal company profile using Tiingo search results."""
    try:
        ti = fetch_tiingo_search(ticker)
        match = ti.get('match') if ti else None
        if not match:
            return {}
        return {
            'shortName': match.get('name'),
            'assetType': match.get('assetType'),
            'ticker': match.get('ticker'),
            'exchange': match.get('exchange'),
        }
    except Exception:
        return {}

def fetch_tiingo_search(ticker, limit=10):
    """Query Tiingo utilities/search for metadata about `ticker`.

    Returns a dict: {"raw": <response list> , "match": <best match dict or None>, "is_etf": bool, "error": <str>}
    """
    key = os.getenv("TIINGO_API_KEY")
    url = "https://api.tiingo.com/tiingo/utilities/search"
    params = {"query": ticker}
    headers = {}
    if key:
        headers["Authorization"] = f"Token {key}"
    try:
        r = requests.get(url, headers=headers, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            data = []
        upper = (ticker or "").upper()
        best = None
        # prefer exact ticker match
        for item in data:
            if (item.get("ticker") or "").upper() == upper:
                best = item
                break
        # fallback: pick first with 'ETF' in name
        if not best:
            for item in data:
                name = (item.get("name") or "").lower()
                if "etf" in name or "exchange traded fund" in name:
                    best = item
                    break
        is_etf = False
        if best:
            name = (best.get("name") or "").lower()
            asset_type = (best.get("assetType") or "").lower()
            # Mark ETF if name contains 'etf' or Tiingo explicitly marks assetType as ETF
            if "etf" in name or "exchange traded fund" in name or asset_type == "etf":
                is_etf = True
        return {"raw": data, "match": best, "is_etf": is_etf}
    except Exception as e:
        return {"raw": None, "match": None, "is_etf": False, "error": str(e)}


from functools import lru_cache

@lru_cache(maxsize=2048)
def detect_ticker_type(ticker):
    """Detect type of ticker: returns {"type": "ETF"|"STOCK"|"UNKNOWN", "source": <str>}.

    Strategy:
    - Fast local checks (known ETFs and suffix heuristics)
    - Tiingo utilities/search (preferred if available)
    - yfinance profile fallback
    - Default to UNKNOWN
    """
    if not ticker:
        return {"type": "UNKNOWN", "source": "none"}
    t = (ticker or "").upper()

    # Fast known ETF list and suffix
    known_etfs = {"SPY", "QQQ", "IVV", "VOO", "IWM", "EEM", "VTI", "GLD", "TLT", "XLF", "XLE"}
    if t in known_etfs or t.endswith("ETF"):
        return {"type": "ETF", "source": "symbol_heuristic"}

    # Tiingo search (authoritative)
    try:
        info = fetch_tiingo_search(t)
        if info and info.get("match"):
            if info.get("is_etf"):
                return {"type": "ETF", "source": "tiingo"}
            # If match exists and not ETF, assume STOCK
            return {"type": "STOCK", "source": "tiingo"}
    except Exception:
        pass

    # No profile-based fallback anymore (yfinance removed). If we couldn't detect above, return UNKNOWN
    return {"type": "UNKNOWN", "source": "fallback"}
