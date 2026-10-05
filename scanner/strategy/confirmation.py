def confirm(candles, i, liquidity, regime, config):
    """Research filters, not a probability model or a guarantee against reversals."""
    if not config.strong_confirmation:
        return []
    reasons = []
    c = candles[-1]
    width = c.high - c.low
    if not i['prior_trend_confirmed'] or not i['ema50_rising']:
        reasons.append('Two-candle rising trend confirmation absent')
    if i['previous_histogram'] <= 0:
        reasons.append('Previous completed candle lacks positive MACD histogram')
    previous_high = max(bar.high for bar in candles[-config.breakout_lookback - 1:-1])
    if c.close < previous_high + config.breakout_buffer_atr * i['atr']:
        reasons.append('Close has not confirmed the prior-range breakout')
    if width <= 0 or c.close <= c.open or (c.close - c.low) / width < config.min_close_location:
        reasons.append('Breakout candle lacks a strong bullish close')
    if width > 0 and (c.high - max(c.open, c.close)) / width > config.max_upper_wick:
        reasons.append('Upper wick indicates rejection')
    if i['price'] - i['ema50'] > config.max_extension_atr * i['atr']:
        reasons.append('Price overextended above EMA50; avoid chasing')
    if abs(liquidity.ask - i['price']) > config.max_entry_drift_atr * i['atr']:
        reasons.append('Quote moved too far from confirmed close; entry stale')
    if regime == 'BEARISH':
        reasons.append('BTC bearish: new BUY blocked by strong confirmation')
    return reasons
