def propose_trade_advanced(ticker,
                           fit_score,
                           price,
                           portfolio_value,
                           pfs=None,
                           profile=None,
                           twin=None):
    """
    Twin-aware advanced trade proposer.

    Parameters
    - ticker: string
    - fit_score: float 0..1
    - price: float
    - portfolio_value: float (dollars)
    - pfs: user's PFS object (optional)
    - profile: ticker profile (optional)
    - twin: PersonalFinancialTwin object (optional) -- if provided, will enforce twin.risk_capacity caps

    Returns dict with keys:
      action, qty, dollar, confidence, explain, adjusted_for_twin_cap (optional boolean)
    """
    # safety checks
    if price is None or price == 0:
        return {'action': 'No suggestion', 'reason': 'no-price', 'confidence': 0.0, 'qty': 0, 'dollar': 0.0}

    # Determine basic action thresholds (calibrated)
    if fit_score >= 0.75:
        action = 'BUY'
        # Confidence increases with distance from threshold
        # 0.75->0.75, 0.85->0.85, 1.0->0.95
        threshold_distance = fit_score - 0.75
        confidence = 0.65 + min(0.30, threshold_distance * 1.2)
    elif 0.0 < fit_score <= 0.30:
        action = 'SELL'
        # Confidence increases with distance below threshold
        # 0.30->0.70, 0.15->0.80, 0.0->0.90
        threshold_distance = 0.30 - fit_score
        confidence = 0.60 + min(0.30, threshold_distance * 1.0)
    elif 0.30 < fit_score < 0.75:
        action = 'HOLD'
        # Confidence highest near center, lower near edges
        center = 0.525  # midpoint of HOLD range (0.30 to 0.75)
        distance_from_center = abs(fit_score - center)
        
        if distance_from_center <= 0.10:  # Near center (0.425-0.625)
            confidence = 0.75  # High confidence - clearly HOLD
        elif distance_from_center <= 0.15:  # Mid-range (0.375-0.675)
            confidence = 0.65
        else:  # Near edges (close to BUY/SELL boundary)
            confidence = 0.50  # Lower confidence - borderline case
    else:
        action = 'Not available'
        confidence = 0.00

    # Adjust confidence based on data quality/completeness
    data_quality_penalty = 0.0
    if not price or price <= 0:
        data_quality_penalty += 0.15
    if not profile:
        data_quality_penalty += 0.08
    if not pfs:
        data_quality_penalty += 0.07
    
    confidence = max(0.30, min(0.95, confidence - data_quality_penalty))

    qty = 0
    dollar = 0.0
    explanation = ""

    if action == 'BUY':
        # base allocation percent
        base_pct = 0.05
        if pfs:
            rt = (pfs.risk_tolerance or "").lower()
            if rt.startswith("conserv"):
                base_pct = 0.02
            elif rt.startswith("aggress"):
                base_pct = 0.08
        # scale by fit score (stronger fit -> larger allocation)
        alloc_pct = base_pct * (0.0 + fit_score)  # approx range 0.5*base .. 1.5*base
        dollar = portfolio_value * alloc_pct
        # convert to integer shares
        qty = 0 if price <= 0 else int(dollar // price)
        # ensure sensible lower bound
        if qty < 1 and dollar >= price:
            qty = 1
        explanation = f"Proposes ~${dollar:,.0f} ({alloc_pct*100:.2f}% of portfolio) based on fit {fit_score:.2f}."

    elif action == 'SELL':
        # conservative default - suggest trimming or selling all (without holdings info)
        qty = 'ALL'
        explanation = "Suggest reducing exposure (low personal fit)."

    else:
        explanation = "No trade recommended — fit is moderate."

    result = {
        'action': action,
        'qty': qty,
        'dollar': float(dollar),
        'confidence': float(confidence),
        'explain': explanation
    }

    # -------- Twin-based cap enforcement (if twin supplied) ----------
    try:
        if twin and getattr(twin, "risk_capacity", None):
            rc = twin.risk_capacity
            max_single = rc.get("max_single_dollars")
            if max_single is not None and result.get("dollar", 0.0) and action == 'BUY':
                # If proposal dollar allocation exceeds twin's max single position, cap it.
                if result["dollar"] > max_single:
                    # compute allowed qty
                    if price and price > 0:
                        allowed_qty = int(max_single // price)
                        # do not force min 1 if max_single is too small
                        allowed_qty = max(0, allowed_qty)
                    else:
                        allowed_qty = 0
                    old_dollar = result["dollar"]
                    new_dollar = float(allowed_qty * price) if price else 0.0
                    result["dollar"] = new_dollar
                    result["qty"] = allowed_qty
                    result["adjusted_for_twin_cap"] = True
                    # add human-readable explanation append
                    result["explain"] = (result.get("explain","") +
                                         f" NOTE: adjusted to comply with your risk capacity (max ${max_single:,.0f}) — reduced allocation from ${old_dollar:,.0f} to ${new_dollar:,.0f}.")
    except Exception as e:
        # Do not crash the proposer on twin errors; log minimally (if logger present), and continue returning the unadjusted proposal
        try:
            print("propose_trade_advanced:twin_cap_error", repr(e))
        except Exception:
            pass

    return result

