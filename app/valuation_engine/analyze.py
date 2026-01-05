# --- ETF Analysis ---
from .data.tiingo import tiingo_get
def analyze_etf(ticker, country='US'):
    """
    Analyze an ETF using Tiingo API: show key metrics, expense ratio, performance, and fees.
    """
    try:
        # Fund overview
        overview = tiingo_get(f'funds/{ticker}')
        if isinstance(overview, list):
            overview = overview[0] if overview else {}
        # Fund metrics (historical/current fee data)
        metrics = tiingo_get(f'funds/{ticker}/metrics')
        if isinstance(metrics, list) and metrics:
            metrics = metrics[-1]  # Most recent
        else:
            metrics = {}

        # Parse fields
        name = overview.get('name', ticker)
        description = overview.get('description', '')
        share_class = overview.get('shareClass', '')
        net_expense = overview.get('netExpense')
        other_share_classes = overview.get('otherShareClasses', [])

        # Fee/Performance fields from metrics
        perf = {
            'prospectusDate': metrics.get('prospectusDate'),
            'netExpense': metrics.get('netExpense'),
            'grossExpense': metrics.get('grossExpense'),
            'managementFee': metrics.get('managementFee'),
            '12b1': metrics.get('12b1'),
            'non12b1': metrics.get('non12b1'),
            'otherExpenses': metrics.get('otherExpenses'),
            'acquiredFundFees': metrics.get('acquiredFundFees'),
            'feeWaiver': metrics.get('feeWaiver'),
            'exchangeFeeUSD': metrics.get('exchangeFeeUSD'),
            'exchangeFeePercent': metrics.get('exchangeFeePercent'),
            'frontLoad': metrics.get('frontLoad'),
            'backLoad': metrics.get('backLoad'),
            'dividendLoad': metrics.get('dividendLoad'),
            'shareholderFee': metrics.get('shareholderFee'),
            'accountFeeUSD': metrics.get('accountFeeUSD'),
            'accountFeePercent': metrics.get('accountFeePercent'),
            'redemptionFeeUSD': metrics.get('redemptionFeeUSD'),
            'redemptionFeePercent': metrics.get('redemptionFeePercent'),
            'portfolioTurnover': metrics.get('portfolioTurnover'),
            'miscFees': metrics.get('miscFees'),
            'customFees': metrics.get('customFees'),
        }

        return {
            'ticker': ticker,
            'name': name,
            'description': description,
            'shareClass': share_class,
            'netExpense': net_expense,
            'otherShareClasses': other_share_classes,
            'performanceAndFees': perf,
        }
    except Exception as e:
        return {'ticker': ticker, 'error': str(e)}
import statistics
from .data.tiingo import get_company_metadata,get_fundamentals_daily,get_fcf_from_cashflow,get_eps,get_shares_outstanding
from .data.prices import get_price_history,compute_returns
from .models.giv import calculate_giv
from .models.dcf import calculate_dcf
from .models.ddm import calculate_ddm
from .models.mvm import calculate_mvm
from .data.peers import (
    search_tickers_by_industry,
    fetch_peer_fundamentals,
    select_top_peers
)

def _run_valuation_for_ticker(t, country='US', top_peers=None):
    """Helper function to run valuation logic for a single ticker"""
    try:
        f=get_fundamentals_daily(t)
    except Exception:
        f={}
    
    eps=f.get('eps') or f.get('earningsPerShare')
    if not eps:
        try:
            eps=get_eps(t)
        except Exception:
            eps=0
    
    try:
        fcf=get_fcf_from_cashflow(t) or 0
    except Exception:
        fcf=0
    
    # Get shares outstanding for per-share calculations
    try:
        shares_outstanding = get_shares_outstanding(t)
    except Exception:
        shares_outstanding = None
    
    wacc=f.get('wacc') or 0.10  # Default WACC of 10%
    
    try:
        prices=get_price_history(t)
        stats=compute_returns(prices)
        current_price=stats.get('current_price', 0)
    except Exception:
        current_price=0
        stats={}
    
    long_g=0.03; div_g=0.03

    try:
        giv=calculate_giv(eps or 0,long_g,country) if eps else 0
    except Exception:
        giv=0
    
    try:
        if fcf and shares_outstanding and shares_outstanding > 0:
            # DCF returns total enterprise value, convert to per-share
            dcf_enterprise_value = calculate_dcf(fcf,long_g,wacc)
            dcf = dcf_enterprise_value / shares_outstanding
        else:
            dcf = 0
    except Exception:
        dcf=0
    
    try:
        ddm=calculate_ddm([1],div_g,wacc)
    except Exception:
        ddm=0
    
    try:
        mvm_value = calculate_mvm(eps, top_peers) if top_peers else 0
    except Exception:
        mvm_value=0

    # Calculate Perfient intrinsic value: median of valuations with 20% margin of safety
    valuations = [giv, dcf, ddm, mvm_value]
    # Filter out zero values for more accurate median
    non_zero_valuations = [v for v in valuations if v > 0]
    if non_zero_valuations:
        median_value = statistics.median(non_zero_valuations)
        perfient_intrinsic = median_value * 0.8  # 20% margin of safety
    else:
        perfient_intrinsic = 0

    return {
        'ticker': t,
        'GIV': giv,
        'DCF': dcf,
        'DDM': ddm,
        'MVM': mvm_value,
        'perfientIntrinsic': perfient_intrinsic,
        'currentPrice': current_price,
        '52wHigh': stats.get('52w_high', 'N/A'),
        '52wLow': stats.get('52w_low', 'N/A')
    }


def analyze_ticker(t,country='US'):
    try:
        meta=get_company_metadata(t)
    except Exception:
        meta={'name': t, 'industry': ''}

    industry = meta.get("industry", "")
    
    # Peer detection - try search API first, fallback to curated lists
    industry_peers = {
        'Consumer Electronics': ['AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN', 'NVDA', 'AMD', 'INTC', 'QCOM', 'AVGO'],
        'Software': ['MSFT', 'ORCL', 'SAP', 'ADBE', 'CRM', 'INTU', 'WDAY', 'SNOW', 'PANW', 'CRWD'],
        'Semiconductors': ['NVDA', 'AMD', 'INTC', 'TSM', 'QCOM', 'AVGO', 'MU', 'MRVL', 'TXN', 'AMAT'],
        'Automotive': ['TSLA', 'F', 'GM', 'TM', 'HMC', 'STLA', 'RIVN', 'LCID', 'NIO', 'XPEV'],
        'E-Commerce': ['AMZN', 'WMT', 'TGT', 'EBAY', 'ETSY', 'SHOP', 'MELI', 'JD', 'BABA', 'PDD'],
        'Streaming': ['NFLX', 'DIS', 'PARA', 'WBD', 'SPOT', 'ROKU', 'GOOGL', 'AMZN', 'AAPL', 'META']
    }
    
    try:
        # First try search API with industry
        peer_tickers = search_tickers_by_industry(industry) if industry else []
        peer_tickers = [p for p in peer_tickers if p != t]
        peers = fetch_peer_fundamentals(peer_tickers)
        top_peers = select_top_peers(peers, n=10)
        
        # If we got less than 10 peers, supplement with curated list
        if len(top_peers) < 10:
            curated_list = industry_peers.get(industry, [])
            if curated_list:
                # Get tickers not already in top_peers
                existing_tickers = {p.get('ticker') for p in top_peers}
                additional_tickers = [p for p in curated_list if p != t and p not in existing_tickers]
                if additional_tickers:
                    additional_peers = fetch_peer_fundamentals(additional_tickers)
                    all_peers = peers + additional_peers
                    top_peers = select_top_peers(all_peers, n=10)
    except Exception:
        # If peer detection fails, use empty list
        top_peers = []
    
    # Run valuation for main ticker
    main_valuation = _run_valuation_for_ticker(t, country, top_peers)
    
    # Run valuation for all peer tickers
    peer_valuations = []
    for peer_dict in top_peers:
        peer_ticker = peer_dict.get('ticker')
        if not peer_ticker:
            continue
        try:
            peer_val = _run_valuation_for_ticker(peer_ticker, country, top_peers)
            peer_val['company'] = peer_ticker  # Add company name, can be enriched later
            peer_valuations.append(peer_val)
        except Exception:
            # Skip peer if valuation fails
            continue

    return {
        'ticker': t,
        'company': meta.get('name', t),
        'GIV': main_valuation['GIV'],
        'DCF': main_valuation['DCF'],
        'DDM': main_valuation['DDM'],
        'MVM': main_valuation['MVM'],
        'perfientIntrinsic': main_valuation['perfientIntrinsic'],
        'currentPrice': main_valuation['currentPrice'],
        '52wHigh': main_valuation['52wHigh'],
        '52wLow': main_valuation['52wLow'],
        'peerValuations': peer_valuations,
        'peerCount': len(peer_valuations)
    }
