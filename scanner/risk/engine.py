def plan(i, liquidity, config):
    entry = i['price']
    stop = min(entry - config.stop_atr * i['atr'], i['swing_low'] - 0.25 * i['atr'])
    distance = entry - stop
    target = entry + config.reward_risk * distance
    reasons = []
    if i['atr'] <= 0 or not config.min_atr_pct <= i['atr_pct'] <= config.max_atr_pct:
        reasons.append('Volatility outside configured band')
    if liquidity.spread_bps > config.max_spread_bps:
        reasons.append('Spread too wide')
    if liquidity.volume_usd < config.min_volume_usd:
        reasons.append('24h USD turnover too low')
    if stop <= 0 or distance <= 0 or distance / entry * 100 > config.max_stop_pct:
        reasons.append('Invalid or excessive stop distance')
    return dict(entry=entry, stop_loss=stop, take_profit=target,
                risk_reward=config.reward_risk, approved=not reasons, reasons=reasons)
