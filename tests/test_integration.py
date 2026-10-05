import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from concurrent.futures import Future
from scanner.config import Config
from scanner.database import Repository
from scanner.models import Candle, Liquidity
from scanner.service import Scanner as ProductionScanner
from scanner.strategy.signal_engine import evaluate


class FixtureProvider:
    # Explicit deterministic test fixtures; never used by production entry point.
    def products(self):
        return ['BTC-USD', 'ETH-USD']

    def candles(self, symbol, start, end, timeframe):
        return [Candle(t, 99, 101, 100, 100, 1000) for t in range(start, end, timeframe)]

    def liquidity(self, symbol):
        return Liquidity(99.99, 100.01, 2e6)


class FixtureRanking:
    def __init__(self, symbols):
        self.rows = [dict(id=n, rank=n, symbol=s.removesuffix('-USD'), market_cap=1e12 / n,
                          stable=s in ('USDT-USD', 'USDC-USD')) for n, s in enumerate(symbols, 1)]

    def page(self, start=1, limit=100):
        return self.rows[start - 1:start - 1 + limit]


def Scanner(config, provider, repo, notifier=None, market_caps=None):
    # Explicit offline CMC fixtures. Manual-list cases supply a small ranking
    # fixture to isolate notification/position behavior, not a production bypass.
    symbols = config.pairs.split(',') if config.top_markets == 0 else provider.products()
    return ProductionScanner(config, provider, repo, notifier,
                             market_caps=market_caps or FixtureRanking(symbols))


class IntegrationTests(unittest.TestCase):
    def test_expired_live_scan_cannot_persist_or_notify_signal(self):
        repo = Repository(':memory:')
        end = 400 * 900
        provider = FixtureProvider()
        notifier = MagicMock()
        future = Future()
        future.set_result((provider.candles('BTC-USD', end - 300 * 900, end, 900), provider.liquidity('BTC-USD')))
        try:
            with patch('scanner.service.time.time', return_value=end + 900):
                with self.assertLogs('scanner.service', level='INFO'):
                    with self.assertRaises(RuntimeError):
                        Scanner(Config(), provider, repo, notifier)._process({future: 'BTC-USD'}, 'NEUTRAL', end, end, True, {'BTC-USD'})
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0], 0)
            notifier.send.assert_not_called()
        finally:
            repo.close()

    def test_telegram_failure_preserves_successful_analysis(self):
        repo = Repository(':memory:')
        notifier = MagicMock()
        notifier.send.side_effect = RuntimeError('Fixture delivery failure')
        config = Config(top_markets=0, pairs='BTC-USD')
        def qualified(*args):
            signal = evaluate(*args)
            signal['classification'] = 'BUY'
            return signal
        try:
            with patch('scanner.service.evaluate', side_effect=qualified):
                with self.assertLogs('scanner.service', level='INFO') as logs:
                    signals = Scanner(config, FixtureProvider(), repo, notifier).run_once(400 * 900)
            self.assertEqual(len(signals), 1)
            self.assertTrue(any('Telegram errors=1' in s and 'data/analysis errors=0' in s for s in logs.output))
            self.assertEqual(repo.db.execute('SELECT status FROM notifications').fetchone()[0], 'ambiguous_or_failed')
        finally:
            repo.close()

    def test_live_timestamp_is_analysis_time(self):
        repo = Repository(':memory:')
        config = Config(top_markets=0)
        end = 400 * 900
        provider = FixtureProvider()
        future = Future()
        future.set_result((provider.candles('BTC-USD', end - 300 * 900, end, 900), provider.liquidity('BTC-USD')))
        try:
            with patch('scanner.service.time.time', return_value=end + 120):
                result = Scanner(config, provider, repo)._process({future: 'BTC-USD'}, 'NEUTRAL', end + 1, end, True, {'BTC-USD'})
            self.assertEqual(result[0]['time'], end + 120)
        finally:
            repo.close()

    def test_open_paper_position_remains_monitored_after_leaving_universe(self):
        repo = Repository(':memory:')
        end = 400 * 900
        with repo.db:
            repo.db.execute('INSERT INTO paper(symbol,entry_time,entry,stop,target,quantity,score) VALUES(?,?,?,?,?,?,?)',
                            ('ETH-USD', end - 900, 100, 99.5, 104, 1, 80))
        try:
            result = Scanner(Config(top_markets=0, pairs='BTC-USD', paper=True), FixtureProvider(), repo).run_once(end)
            self.assertEqual([s['symbol'] for s in result], ['BTC-USD'])
            self.assertIsNotNone(repo.db.execute('SELECT exit_time FROM paper WHERE symbol=?', ('ETH-USD',)).fetchone()[0])
        finally:
            repo.close()

    def test_minute_checks_detect_next_candle_without_repolling_same_history(self):
        self.assertEqual(Config().scan_interval, 60)
        repo = Repository(':memory:')
        provider = FixtureProvider()
        scanner = Scanner(Config(), provider, repo)
        try:
            with patch.object(provider, 'products', wraps=provider.products) as products:
                scanner.run_once(900 * 400 + 880)
                self.assertEqual(scanner.run_once(900 * 400 + 890), [])
                self.assertEqual(products.call_count, 1)
                result = scanner.run_once(900 * 400 + 940)
                self.assertEqual(len(result), 2)
                self.assertEqual(products.call_count, 2)
                self.assertEqual(result[0]['candle_time'], 900 * 400)
        finally:
            repo.close()

    def test_scan_persists_and_skips_same_candle(self):
        repo = Repository(':memory:')
        scanner = Scanner(Config(), FixtureProvider(), repo)
        self.assertEqual(len(scanner.run_once(900 * 400)), 2)
        self.assertEqual(scanner.run_once(900 * 400 + 100), [])
        self.assertEqual(repo.db.execute('SELECT count(*) FROM scans').fetchone()[0], 2)
        self.assertEqual(repo.db.execute('SELECT count(*) FROM paper').fetchone()[0], 0)
        repo.close()

    def test_breakdown_blocks_even_high_score(self):
        data = FixtureProvider().candles('ETH-USD', 0, 300 * 900, 900)
        with patch('scanner.strategy.signal_engine.score', return_value=(100, {}, {})):
            s = evaluate('ETH-USD', data, 'BREAKDOWN', Liquidity(99.99, 100.01, 2e6), Config(), 300 * 900)
        self.assertEqual(s['classification'], 'NO TRADE')
        self.assertIn('BTC market breakdown', s['invalidation_reasons'])

    def test_restart_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'db.sqlite')
            s = dict(symbol='ETH-USD', time=10000, candle_time=9000, score=90, classification='BUY')
            repo = Repository(path)
            self.assertTrue(repo.claim(s, Config()))
            repo.close()
            repo = Repository(path)
            self.assertFalse(repo.claim(s, Config()))
            repo.close()
