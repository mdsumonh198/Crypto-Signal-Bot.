import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from scanner.market_data.coinbase import validate_history, CandleNotReady
from scanner.market_data.market_cap import CoinMarketCap
from scanner.strategy.indicators import indicators
from scanner.strategy.btc_regime import detect
from scanner.strategy.signal_engine import evaluate
from scanner.paper_trading.engine import PaperEngine
from scanner.tracking import SignalTracker
from scanner.market_data.selection import select_markets

log = logging.getLogger(__name__)


class Scanner:
    def __init__(self, config, provider, repository, notifier=None, market_caps=None):
        self.config, self.provider, self.repo, self.notifier = config, provider, repository, notifier
        self.paper = PaperEngine(repository, config) if config.paper else None
        self.last_end = None
        self.market_caps = market_caps if market_caps is not None else CoinMarketCap(config.cmc_api_key)
        self.allowed = None
        self.universe_end = None
        self.cycle_done = set()
        self.retry_pending = False
        self.refresh_retry_at = 0
        self.candle_cache = {}
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
        if live_clock and c.timeframe == 900 and now - end < c.candle_publish_delay:
            log.info('Waiting for completed 15m candle publication until close + %ds', c.candle_publish_delay)
            return []
        if self.universe_end != end:
            if now < self.refresh_retry_at:
                log.info('Market-cap source backoff active; new signals remain blocked')
                return []
            # Revoke the previous universe before any refresh can fail.
            self.allowed = set()
            self.retry_pending = False
            self.cycle_done = set()
            log.info('Universe refresh for candle close %d UTC: fetching CMC market-cap ranking', end)
            available = self.provider.products()
            if 'BTC-USD' not in available:
                raise ValueError('BTC-USD unavailable; no market safety context')
            if c.timeframe == 900 or c.top_markets:
                if c.timeframe == 900 and c.top_markets != 20:
                    log.warning('15-minute strategy requires CMC Top 20; TOP_MARKETS=%d and PAIRS cannot bypass it', c.top_markets)
                try:
                    requested = select_markets(self.market_caps, available, c, 20 if c.timeframe == 900 else c.top_markets)
                except Exception:
                    self.refresh_retry_at = now + 60
                    raise
            else:
                requested = list(dict.fromkeys(p.strip() for p in c.pairs.split(',') if p.strip()))
                if not requested or set(requested) - set(available):
                    raise ValueError('Unsupported/inactive USD products')
            self.allowed = set(requested)
            self.refresh_retry_at = 0
            self.universe_end = end
        selected = set(self.allowed)
        start = end - c.history * c.timeframe

        def history(symbol):
            cached = self.candle_cache.get(symbol, [])
            if cached and cached[-1].time < end:
                fetch_start = max(start, cached[-1].time + c.timeframe)
                fresh = self.provider.candles(symbol, fetch_start, end, c.timeframe) if fetch_start < end else []
                candles = [bar for bar in cached if start <= bar.time < end] + fresh
            else:
                candles = self.provider.candles(symbol, start, end, c.timeframe)
            validate_history(candles, c.timeframe, end)
            self.candle_cache[symbol] = candles
            return candles

        log.info('Loading completed BTC candles for market safety filter')
        try:
            btc = history('BTC-USD')
        except CandleNotReady:
            self.retry_pending = now < end + c.candle_retry_window
            if not self.retry_pending:
                self.last_end = end
            raise
        regime = detect(indicators(btc), c)
        requested = sorted(selected)
        if self.paper:
            held = [r[0] for r in self.repo.db.execute('SELECT DISTINCT symbol FROM paper WHERE exit_time IS NULL')]
            extras = [symbol for symbol in held if symbol not in selected]
            if extras:
                log.info('Also monitoring %d existing paper positions outside the selected universe', len(extras))
                requested += extras
        requested = [symbol for symbol in requested if symbol not in self.cycle_done]
        # Drop unused history, except BTC context and existing paper positions.
        self.candle_cache = {symbol: bars for symbol, bars in self.candle_cache.items()
                             if symbol == 'BTC-USD' or symbol in selected or symbol in requested}
        self.retry_pending = False
        def fetch(symbol):
            candles = btc if symbol == 'BTC-USD' else history(symbol)
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
                validate_history(candles, c.timeframe, end)
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
                    self.cycle_done.add(symbol)
                    continue
                if self.allowed is not None and symbol not in self.allowed:
                    raise ValueError('Symbol outside current market-cap universe; new signal blocked')
                evaluated_at = int(time.time()) if live_clock else now
                if evaluated_at // c.timeframe * c.timeframe > end:
                    raise ValueError('Signal became stale during paper history catch-up')
                signal = evaluate(symbol, candles, regime, liquidity, c, evaluated_at)
                if signal['symbol'] != symbol:
                    raise ValueError('Signal symbol differs from allowed market identity')
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
                self.cycle_done.add(symbol)
            except CandleNotReady as exc:
                if (int(time.time()) if live_clock else now) < end + c.candle_retry_window:
                    self.retry_pending = True
                    log.info('%s: completed candle not published; retry in %ds', symbol, c.candle_retry_interval)
                else:
                    self.cycle_done.add(symbol)
                    failures += 1
                    self.repo.error(now, symbol, str(exc))
                    log.warning('%s: publication retry window expired; skipped this candle', symbol)
            except Exception as exc:
                self.cycle_done.add(symbol)
                failures += 1
                self.repo.error(now, symbol, str(exc))
                log.error('%s: %s', symbol, exc)
        counts = {label: sum(s['classification'] == label for s in signals) for label in ('BUY', 'WATCH', 'NO TRADE')}
        log.info('Scan summary: selected=%d evaluated=%d | BUY=%d WATCH=%d NO TRADE=%d | data/analysis errors=%d Telegram alerts=%d Telegram errors=%d',
                 len(selected), len(signals), counts['BUY'], counts['WATCH'], counts['NO TRADE'], failures, alerts_sent, notification_failures)
        if not self.retry_pending:
            self.last_end = end
        if not signals and failures:
            raise RuntimeError('All markets failed; inspect errors table/logs')
        return signals
