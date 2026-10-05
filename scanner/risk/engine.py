def plan(i, liquidity, config):
    entry = i['price']
    stop = min(entry - config.stop_atr * i['atr'], i['swing_low'] - 0.25 * i['atr'])
    distance = entry - stop
    target = entry + config.reward_risk * distance
    fee = config.fee_bps / 10000
    slip = config.slippage_bps / 10000
    assumed_entry = entry * (1 + slip)
    assumed_target = target * (1 - slip)
    assumed_stop = stop * (1 - slip)
    net_gain = assumed_target - assumed_entry - fee * (assumed_target + assumed_entry)
    net_loss = assumed_entry - assumed_stop + fee * (assumed_entry + assumed_stop)
    net_rr = net_gain / net_loss if net_loss > 0 else 0
    reasons = []
    if i['atr'] <= 0 or not config.min_atr_pct <= i['atr_pct'] <= config.max_atr_pct:
        reasons.append('Volatility outside configured band')
    if liquidity.spread_bps > config.max_spread_bps:
        reasons.append('Spread too wide')
    if liquidity.volume_usd < config.min_volume_usd:
        reasons.append('24h USD turnover too low')
    if stop <= 0 or distance <= 0 or distance / entry * 100 > config.max_stop_pct:
        reasons.append('Invalid or excessive stop distance')
    if config.strong_confirmation and net_rr < config.min_net_reward_risk:
        reasons.append('Reward/risk after configured fees and slippage too low')
    return dict(entry=entry, stop_loss=stop, take_profit=target,
                risk_reward=config.reward_risk, estimated_net_risk_reward=net_rr, approved=not reasons, reasons=reasons)
