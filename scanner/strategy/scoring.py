import math

MAXIMA = {'Trend': 30, 'Momentum': 20, 'Volume': 15, 'BTC Regime': 15, 'Volatility': 10, 'Liquidity': 10}


def clamp(x):
    return max(0.0, min(1.0, x))


def classify(score, config):
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError('Score must be finite and in [0,100]')
    return 'BUY' if score >= config.buy_score else 'WATCH' if score >= config.watch_score else 'NO TRADE'


def score(i, regime, liquidity, config):
    # Distances are normalized by ATR so partial credit adapts to each market.
    atr = max(i['atr'], i['price'] * 1e-8)
    trend = 15 * clamp(0.5 + (i['price'] - i['ema200']) / (4 * atr)) + 15 * clamp(0.5 + (i['ema50'] - i['ema200']) / (4 * atr))
    midpoint = (config.rsi_low + config.rsi_high) / 2
    rsi_strength = clamp(1 - abs(i['rsi'] - midpoint) / 25)
    momentum = 8 * rsi_strength + 6 * clamp(0.5 + i['macd'] / atr) + 6 * clamp(0.5 + i['histogram'] / (atr * 0.2))
    volume = 15 * clamp(i['volume_ratio'] / 2)
    btc = {'BULLISH': 15, 'NEUTRAL': 9, 'BEARISH': 3, 'BREAKDOWN': 0}[regime]
    volatility = 10 * min(clamp(i['atr_pct'] / max(config.min_atr_pct, 1e-8)), clamp((config.max_atr_pct - i['atr_pct']) / (config.max_atr_pct * 0.5)))
    liquid = 5 * clamp(1 - liquidity.spread_bps / config.max_spread_bps) + 5 * clamp(liquidity.volume_usd / (2 * config.min_volume_usd))
    parts = dict(zip(MAXIMA, (trend, momentum, volume, btc, volatility, liquid)))
    parts = {k: round(v, 4) for k, v in parts.items()}
    explanation = {
        'Trend': 'Price and EMA50 distance above EMA200, normalized by ATR',
        'Momentum': 'RSI proximity to configured band midpoint plus normalized MACD and histogram',
        'Volume': f"Completed candle volume / prior 20-candle mean: {i['volume_ratio']:.2f}",
        'BTC Regime': f'BTC state: {regime}',
        'Volatility': f"ATR / close: {i['atr_pct']:.3f}%",
        'Liquidity': f'Spread {liquidity.spread_bps:.2f} bps; 24h estimated USD turnover {liquidity.volume_usd:.0f}',
    }
    return min(100.0, sum(parts.values())), parts, explanation
