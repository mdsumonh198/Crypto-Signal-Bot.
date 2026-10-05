import unittest
from unittest.mock import patch
from scanner.config import Config
from scanner.database import Repository
from scanner.market_data.selection import select_markets
from scanner.models import Candle, Liquidity
from scanner.service import Scanner
from tests.test_integration import FixtureProvider


class ActivityProvider(FixtureProvider):
    def products(self):
        return ['BTC-USD', 'USDT-USD', 'USDE-USD', 'BAD-USD'] + [f'COIN{n:02d}-USD' for n in range(64)]
    def turnovers(self):
        return {s: 10e6 for s in self.products()}
    def liquidity(self, symbol):
        return Liquidity(99, 101, 10e6) if symbol == 'BAD-USD' else Liquidity(99.99, 100.01, 10e6)


class SelectionTests(unittest.TestCase):
    def test_old_64_setting_caps_full_analysis_at_20(self):
        provider = ActivityProvider()
        repo = Repository(':memory:')
        from scanner.service import evaluate
        try:
            with patch('scanner.service.evaluate', wraps=evaluate) as engine:
                with self.assertLogs('scanner.service', level='INFO'):
                    result = Scanner(Config(top_markets=64), provider, repo).run_once(400 * 900)
            self.assertEqual(len(result), 20)
            self.assertEqual(engine.call_count, 20)
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0], 20)
        finally:
            repo.close()

    def test_stable_and_poor_spread_excluded_major_preference(self):
        with self.assertLogs('scanner.market_data.selection', level='INFO') as logs:
            selected = select_markets(ActivityProvider(), ActivityProvider().products(), Config(), 400 * 900, 20)
        self.assertEqual(len(selected), 20)
        self.assertIn('BTC-USD', selected)
        self.assertTrue({'USDT-USD', 'USDE-USD', 'BAD-USD'}.isdisjoint(selected))
        self.assertTrue(any('Selected Top 20 active markets' in line for line in logs.output))

    def test_momentum_affects_ranking_and_selection_refreshes(self):
        class Provider(ActivityProvider):
            strong = 'COIN36-USD'
            def candles(self, symbol, start, end, timeframe):
                if end - start == 3 * timeframe and symbol == self.strong:
                    return [Candle(t, 99, 102, 100, 102, 1) for t in range(start, end, timeframe)]
                return super().candles(symbol, start, end, timeframe)
        provider = Provider()
        with self.assertLogs('scanner.market_data.selection', level='INFO'):
            first = select_markets(provider, provider.products(), Config(), 400 * 900, 20)
            provider.strong = 'COIN35-USD'
            second = select_markets(provider, provider.products(), Config(), 401 * 900, 20)
        self.assertIn('COIN36-USD', first)
        self.assertIn('COIN35-USD', second)
        self.assertNotIn('COIN36-USD', second)

    def test_selection_fetches_only_lightweight_three_bar_histories(self):
        provider = ActivityProvider()
        with patch.object(provider, 'candles', wraps=provider.candles) as candles:
            with self.assertLogs('scanner.market_data.selection', level='INFO'):
                select_markets(provider, provider.products(), Config(), 400 * 900, 20)
        self.assertTrue(all(call.args[2] - call.args[1] == 3 * 900 for call in candles.call_args_list))
        self.assertLessEqual(candles.call_count, 48)
