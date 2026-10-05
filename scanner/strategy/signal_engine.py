from scanner.strategy.indicators import indicators
from scanner.strategy.scoring import score, classify
from scanner.risk.engine import plan
from scanner.strategy.confirmation import confirm


def evaluate(symbol, candles, regime, liquidity, config, now):
    liquidity.validate_freshness(now, config.max_quote_age)
    i = indicators(candles)
    total, parts, explanations = score(i, regime, liquidity, config)
    risk = plan(i, liquidity, config, entry_price=liquidity.ask)
    reasons = list(risk['reasons'])
    if regime == 'BREAKDOWN':
        reasons.append('BTC market breakdown')
    if not i['price'] > i['ema200'] or not i['ema50'] > i['ema200']:
        reasons.append('Bullish EMA structure absent')
    if not config.rsi_low <= i['rsi'] <= config.rsi_high:
        reasons.append('RSI outside BUY band')
    if not (i['macd'] > 0 and i['histogram'] > 0 and i['histogram'] >= i['previous_histogram']):
        reasons.append('MACD does not confirm rising positive momentum')
    if i['volume_ratio'] < config.volume_buy_ratio:
        reasons.append('Volume confirmation absent')
    reasons.extend(confirm(candles, i, liquidity, regime, config))
    classification = classify(total, config)
    if regime == 'BREAKDOWN' or not risk['approved']:
        classification = 'NO TRADE'
    elif classification == 'BUY' and reasons:
        classification = 'WATCH'
    return dict(time=now, candle_time=candles[-1].time, symbol=symbol,
                timeframe=config.timeframe, score=total, raw_classification=classify(total, config),
                classification=classification, components=parts, explanations=explanations,
                indicators=i, btc_regime=regime, risk=risk,
                quote=dict(source='Coinbase Exchange spot ticker', bid=liquidity.bid, ask=liquidity.ask,
                           last_trade_time=liquidity.quote_time, observed_at=liquidity.observed_at,
                           request_started_at=liquidity.request_started_at),
                invalidation_reasons=reasons,
                reason='; '.join(reasons) if reasons else 'Bullish trend, rising momentum, volume, candle breakout and market quality confirmed')
