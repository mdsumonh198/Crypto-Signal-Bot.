import unittest
from unittest.mock import patch
from scanner.config import Config
from scanner.database import Repository
from scanner.market_data.coinbase import Coinbase
from scanner.models import Liquidity
from tests.test_integration import FixtureProvider, Scanner


class LargeProvider(FixtureProvider):
    def products(self):
        return ['BTC-USD'] + [f'COIN{n}-USD' for n in range(259)]

    def turnovers(self):
        return dict({s: float(n) for n, s in enumerate(self.products())}, **{'NOT-ACTIVE-USD': 1e15})

    def liquidity(self, symbol):
        # Below the BUY quality floor: still selected, never promoted to BUY.
        return Liquidity(99.99, 100.01, 2e6)


class UniverseTests(unittest.TestCase):
    def test_old_top_250_setting_cannot_expand_fifteen_minute_universe(self):
        repo = Repository(':memory:')
        try:
            provider = LargeProvider()
            with self.assertLogs('scanner.service', level='INFO'):
                signals = Scanner(Config(top_markets=250, min_volume_usd=1), provider, repo).run_once(400 * 900)
            self.assertEqual(len(signals), 10)
            self.assertTrue(all(s['classification'] != 'BUY' for s in signals))
        finally:
            repo.close()

    def test_bulk_turnover_parsing(self):
        with patch.object(Coinbase, 'get', return_value={
            'BTC-USD': {'stats_24hour': {'volume': '2', 'last': '100'}},
            'INVALID-USD': {'stats_24hour': {'volume': 'NaN', 'last': '1'}},
            'MISSING-USD': {},
        }):
            self.assertEqual(Coinbase().turnovers(), {'BTC-USD': 200})
