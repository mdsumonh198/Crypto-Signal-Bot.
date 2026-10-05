import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from scanner.market_data.coinbase import validate_history
from scanner.strategy.indicators import indicators
from scanner.strategy.btc_regime import detect
from scanner.strategy.signal_engine import evaluate
from scanner.paper_trading.engine import PaperEngine
from scanner.tracking import SignalTracker
from scanner.market_data.selection import select_markets

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, config, provider, repository, notifier=None):
        self.config, self.provider, self.repo, self.notifier = config, provider, repository, notifier
        self.paper = PaperEngine(repository, config) if config.paper else None
        self.last_end = None
        self.tracker = SignalTracker(repository, provider, notifier)

    def run_once(self, now=None):
        live_clock = now is None
        now = int(time.time()) if now is None else now
        c = self.config
        self.tracker.update(now)
        end = now // c.timeframe * c.timeframe
        if end == self.last_end:
            log.info('No new completed candle yet; scanner remains running')
            return []
        log.info('Scan starting: fetching active Coinbase USD markets')
        available = self.provider.products()
        log.info('Coinbase discovery: %d active USD markets available', len(available))
        requested = [p.strip() for p in c.pairs.split(',') if p.strip()]
        missing = set(requested) - set(available)
        if missing and not c.top_markets:
            raise ValueError('Unsupported/inactive USD products: ' + ', '.join(sorted(missing)))
        if 'BTC-USD' not in available:
            raise ValueError('BTC-USD unavailable; no market safety context')
        start = end - c.history * c.timeframe
        log.info('Loading completed BTC candles for market safety filter')
        btc = self.provider.candles('BTC-USD', start, end, c.timeframe)
        validate_history(btc, c.timeframe, end)
        regime = detect(indicators(btc), c)
        if c.top_markets:
            limit = min(20, c.top_markets) if c.timeframe == 900 else c.top_markets
            if limit != c.top_markets:
                log.warning('15-minute strategy caps full analysis at 20; TOP_MARKETS=%d cannot expand it', c.top_markets)
            requested = select_markets(self.provider, available, c, end, limit)
        if not requested:
            raise ValueError('No eligible markets selected')
        requested = list(dict.fromkeys(requested))
        if c.timeframe == 900:
            requested = requested[:20]
        log.info('Selected %d markets: %s | BTC regime=%s', len(requested), ', '.join(requested), regime)
        selected = set(requested)
        if self.paper:
            held = [r[0] for r in self.repo.db.execute('SELECT DISTINCT symbol FROM paper WHERE exit_time IS NULL')]
            extras = [symbol for symbol in held if symbol not in selected]
            if extras:
                log.info('Also monitoring %d existing paper positions outside the selected universe', len(extras))
                requested += extras
        def fetch(symbol):
            candles = btc if symbol == 'BTC-USD' else self.provider.candles(symbol, start, end, c.timeframe)
            validate_history(candles, c.timeframe, end)
            return candles, self.provider.liquidity(symbol)

        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='market-data')
        futures = {pool.submit(fetch, symbol): symbol for symbol in requested}
        try:
            return self._process(futures, regime, now, end, live_clock, selected)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)

    def _process(self, futures, regime, now, end, live_clock, selected):
        c = self.config
        signals = []
        failures = 0
        alerts_sent = 0
        notification_failures = 0
        for index, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                if symbol in selected:
                    log.info('Analysis market %s (universe capped at %d)', symbol, len(selected))
                else:
                    log.info('Paper-position exit monitoring only: %s', symbol)
                candles, liquidity = future.result()
                if live_clock and int(time.time()) // c.timeframe * c.timeframe > end:
                    # A long market discovery cycle must not deliver old signals.
                    raise ValueError('Scan exceeded candle freshness window')
                if self.paper:
                    oldest = self.repo.db.execute('SELECT MIN(entry_time) FROM paper WHERE symbol=? AND exit_time IS NULL', (symbol,)).fetchone()[0]
                    updates = candles
                    if oldest is not None and oldest < candles[0].time:
                        updates = self.provider.candles(symbol, oldest // c.timeframe * c.timeframe, end, c.timeframe)
                        validate_history(updates, c.timeframe, end, 1)
                    self.paper.update(symbol, updates)
                if symbol not in selected:
                    continue
                evaluated_at = int(time.time()) if live_clock else now
                if evaluated_at // c.timeframe * c.timeframe > end:
                    raise ValueError('Signal became stale during paper history catch-up')
                signal = evaluate(symbol, candles, regime, liquidity, c, evaluated_at)
                self.repo.save_scan(signal)
                signals.append(signal)
                if self.paper:
                    self.paper.open(signal, entry_price=liquidity.ask)
                if self.notifier and (signal['classification'] == 'BUY' or (c.watch_alerts and signal['classification'] == 'WATCH')) and self.repo.claim(signal, c):
                    try:
                        message_id = self.notifier.send(signal)
                        self.repo.delivered(symbol, 'sent')
                        if signal['classification'] == 'BUY':
                            started_at = int(time.time()) if live_clock else evaluated_at
                            self.tracker.register(signal, message_id, self.notifier.chat_id, started_at)
                        alerts_sent += 1
                        log.info('Telegram %s alert sent for %s', signal['classification'], symbol)
                    except RuntimeError as exc:
                        self.repo.delivered(symbol, 'ambiguous_or_failed')
                        notification_failures += 1
                        self.repo.error(evaluated_at, symbol, str(exc))
                        log.error('%s Telegram delivery: %s', symbol, exc)
                log.info('%s %s %.2f BTC=%s', symbol, signal['classification'], signal['score'], regime)
                if signal['classification'] != 'BUY':
                    log.info('%s qualification: %s', symbol, signal['reason'])
            except Exception as exc:
                failures += 1
                self.repo.error(now, symbol, str(exc))
                log.error('%s: %s', symbol, exc)
        counts = {label: sum(s['classification'] == label for s in signals) for label in ('BUY', 'WATCH', 'NO TRADE')}
        log.info('Scan summary: selected=%d evaluated=%d | BUY=%d WATCH=%d NO TRADE=%d | data/analysis errors=%d Telegram alerts=%d Telegram errors=%d',
                 len(selected), len(signals), counts['BUY'], counts['WATCH'], counts['NO TRADE'], failures, alerts_sent, notification_failures)
        if not signals and failures:
            raise RuntimeError('All markets failed; inspect errors table/logs')
        self.last_end = end
        return signals
