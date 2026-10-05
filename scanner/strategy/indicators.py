def ema(values, period):
    if period < 1 or len(values) < period:
        raise ValueError('Insufficient EMA history')
    result = [None] * (period - 1)
    current = sum(values[:period]) / period
    result.append(current)
    alpha = 2 / (period + 1)
    for value in values[period:]:
        current += alpha * (value - current)
        result.append(current)
    return result


def wilder(values, period):
    if len(values) < period:
        raise ValueError('Insufficient Wilder history')
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = (current * (period - 1) + value) / period
    return current


def rsi(values, period=14):
    changes = [b - a for a, b in zip(values, values[1:])]
    gain = wilder([max(x, 0) for x in changes], period)
    loss = wilder([max(-x, 0) for x in changes], period)
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100 - 100 / (1 + gain / loss)


def macd(values):
    fast, slow = ema(values, 12), ema(values, 26)
    line = [a - b for a, b in zip(fast, slow) if b is not None]
    signal = ema(line, 9)
    return line[-1], signal[-1], line[-1] - signal[-1], line[-2] - signal[-2]


def indicators(candles):
    if len(candles) < 250:
        raise ValueError('250 completed candles required for warmup')
    close = [c.close for c in candles]
    ema50 = ema(close, 50)
    ema200 = ema(close, 200)
    m, s, h, previous = macd(close)
    tr = [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(candles, candles[1:])]
    atr = wilder(tr, 14)
    average = sum(c.volume for c in candles[-21:-1]) / 20
    return dict(price=close[-1], ema50=ema50[-1], ema200=ema200[-1],
                prior_trend_confirmed=close[-2] > ema50[-2] > ema200[-2],
                ema50_rising=ema50[-1] > ema50[-2] > ema50[-3],
                rsi=rsi(close), macd=m, macd_signal=s, histogram=h, previous_histogram=previous,
                volume=candles[-1].volume, average_volume=average,
                volume_ratio=candles[-1].volume / average if average else 0,
                atr=atr, atr_pct=atr / close[-1] * 100,
                change_pct=(close[-1] / close[-2] - 1) * 100,
                swing_low=min(c.low for c in candles[-10:]))
