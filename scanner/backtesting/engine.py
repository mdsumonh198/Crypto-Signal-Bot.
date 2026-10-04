from scanner.models import Liquidity
from scanner.strategy.indicators import indicators
from scanner.strategy.btc_regime import detect
from scanner.strategy.signal_engine import evaluate
from scanner.paper_trading.engine import PaperEngine


def backtest(symbol, candles, btc_candles, config, repository, assumed_spread_bps):
    """Prefix-only signals; next candle open entry. No live liquidity in replay."""
    for sequence in (candles, btc_candles):
        if any(b.time - a.time != config.timeframe for a, b in zip(sequence, sequence[1:])):
            raise ValueError('Backtest requires contiguous, sorted candles')
    btc_index = {c.time: n for n, c in enumerate(btc_candles)}
    paper = PaperEngine(repository, config)
    decisions = 0
    for n in range(249, len(candles) - 1):
        candle, next_candle = candles[n], candles[n + 1]
        # Settle prior positions before computing this close's new signal.
        paper.update(symbol, [candle])
        btc_n = btc_index.get(candle.time)
        if btc_n is None or btc_n < 249:
            continue
        history = candles[max(0, n + 1 - config.history):n + 1]
        btc = btc_candles[max(0, btc_n + 1 - config.history):btc_n + 1]
        regime = detect(indicators(btc), config)
        # Observed trailing candle turnover; spread explicitly supplied by user.
        lookback = max(1, 86400 // config.timeframe)
        turnover = sum(c.close * c.volume for c in candles[max(0, n + 1 - lookback):n + 1])
        half = assumed_spread_bps / 20000
        liquidity = Liquidity(candle.close * (1 - half), candle.close * (1 + half), turnover)
        signal = evaluate(symbol, history, regime, liquidity, config, candle.time + config.timeframe)
        signal['liquidity_source'] = 'historical candle turnover; user-assumed spread'
        repository.save_scan(signal)
        decisions += 1
        paper.open(signal, next_candle.time, next_candle.open)
    if candles:
        paper.update(symbol, [candles[-1]])
    return dict(paper.stats(), signals_evaluated=decisions, assumed_spread_bps=assumed_spread_bps,
                limitations='Historical spread is assumed; candle fills approximate; open trades excluded from realized statistics')
