import unittest
from unittest.mock import patch
from scanner.config import Config
from scanner.database import Repository
from scanner.service import Scanner
from scanner.scheduling import next_scan_delay
from tests.test_integration import FixtureProvider, FixtureRanking


class TimingTests(unittest.TestCase):
    def test_exact_quarter_hour_close_plus_five_seconds(self):
        c = Config()
        for end in (360000, 360900, 361800, 362700):
            self.assertEqual(next_scan_delay(c, end - 1, end - 900), 6)
            self.assertEqual(next_scan_delay(c, end + 1, end - 900), 4)
            self.assertEqual(next_scan_delay(c, end + 5, end - 900, True), 5)
            self.assertEqual(next_scan_delay(c, end + 870, end), 35)
            self.assertEqual(next_scan_delay(c, end + 20, end), 60)
        self.assertEqual(next_scan_delay(c, 360010, None, refresh_retry_at=360060), 50)

    def test_no_analysis_during_publication_grace(self):
        repo = Repository(':memory:')
        provider = FixtureProvider()
        scanner = Scanner(Config(), provider, repo, market_caps=FixtureRanking(provider.products()))
        try:
            with patch('scanner.service.time.time', return_value=360001), patch.object(provider, 'products') as products:
                self.assertEqual(scanner.run_once(), [])
            products.assert_not_called()
        finally:
            repo.close()

    def test_missing_publication_retries_only_pending_symbol_without_duplicates(self):
        class Delayed(FixtureProvider):
            published = False
            def candles(self, symbol, start, end, timeframe):
                bars = super().candles(symbol, start, end, timeframe)
                return bars[:-1] if symbol == 'ETH-USD' and not self.published else bars
        repo = Repository(':memory:')
        provider = Delayed()
        source = FixtureRanking(provider.products())
        scanner = Scanner(Config(), provider, repo, market_caps=source)
        try:
            with patch.object(source, 'page', wraps=source.page) as refresh:
                first = scanner.run_once(360005)
                self.assertEqual([s['symbol'] for s in first], ['BTC-USD'])
                self.assertTrue(scanner.retry_pending)
                provider.published = True
                second = scanner.run_once(360010)
                self.assertEqual([s['symbol'] for s in second], ['ETH-USD'])
                self.assertFalse(scanner.retry_pending)
                self.assertEqual(refresh.call_count, 1)
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0], 2)
            self.assertEqual(scanner.last_end, 360000)
        finally:
            repo.close()

    def test_publication_timeout_skips_candle_without_fabricating_data(self):
        class Missing(FixtureProvider):
            def candles(self, symbol, start, end, timeframe):
                return super().candles(symbol, start, end, timeframe)[:-1]
        repo = Repository(':memory:')
        scanner = Scanner(Config(), Missing(), repo, market_caps=FixtureRanking(['BTC-USD']))
        try:
            with self.assertRaises(ValueError):
                scanner.run_once(360095)
            self.assertFalse(scanner.retry_pending)
            self.assertEqual(scanner.last_end, 360000)
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0], 0)
        finally:
            repo.close()

    def test_warm_scan_fetches_only_new_completed_bucket(self):
        repo = Repository(':memory:')
        provider = FixtureProvider()
        scanner = Scanner(Config(), provider, repo, market_caps=FixtureRanking(provider.products()))
        try:
            scanner.run_once(360005)
            with patch.object(provider, 'candles', wraps=provider.candles) as fetch:
                result = scanner.run_once(360905)
            self.assertEqual(len(result), 2)
            self.assertTrue(all(call.args[1:4] == (360000, 360900, 900) for call in fetch.call_args_list))
            self.assertTrue(all(s['candle_time'] == 360000 for s in result))
        finally:
            repo.close()

    def test_incomplete_live_candle_is_rejected_before_signal_analysis(self):
        class LiveCandle(FixtureProvider):
            def candles(self, symbol, start, end, timeframe):
                # Faulty upstream returns the live candle as well.
                return super().candles(symbol, start, end + timeframe, timeframe)
        repo = Repository(':memory:')
        scanner = Scanner(Config(), LiveCandle(), repo, market_caps=FixtureRanking(['BTC-USD']))
        try:
            with patch('scanner.service.evaluate') as evaluate:
                with self.assertRaises(ValueError):
                    scanner.run_once(360005)
            evaluate.assert_not_called()
        finally:
            repo.close()
