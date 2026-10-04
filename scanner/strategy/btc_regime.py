def detect(i, config):
    if i['change_pct'] <= config.btc_breakdown_pct or (i['price'] < i['ema200'] and i['change_pct'] < config.btc_bearish_pct and i['atr_pct'] > config.max_atr_pct):
        return 'BREAKDOWN'
    if i['price'] < i['ema200'] and (i['ema50'] < i['ema200'] or i['histogram'] < 0):
        return 'BEARISH'
    if i['price'] > i['ema50'] > i['ema200'] and i['macd'] > 0 and i['histogram'] >= 0:
        return 'BULLISH'
    return 'NEUTRAL'
