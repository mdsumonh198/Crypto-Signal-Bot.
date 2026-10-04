import unittest
from unittest.mock import patch
from scanner.config import Config
from scanner.database import Repository
from scanner.market_data.coinbase import Coinbase
from scanner.models import Liquidity
from scanner.service import Scanner
from tests.test_integration import FixtureProvider


class LargeProvider(FixtureProvider):
    def products(self):
        return ['BTC-USD'] + [f'COIN{n}-USD' for n in range(259)]

    def turnovers(self):
        return dict({s: float(n) for n, s in enumerate(self.products())}, **{'NOT-ACTIVE-USD': 1e15})

    def liquidity(self, symbol):
        # Below the BUY quality floor: still selected, never promoted to BUY.
        return Liquidity(99.99, 100.01, 10)


class UniverseTests(unittest.TestCase):
    def test_top_250_ranked_active_pairs_keep_quality_filters(self):
        repo = Repository(':memory:')
        try:
            provider = LargeProvider()
            with self.assertLogs('scanner.service', level='INFO'):
                signals = Scanner(Config(), provider, repo).run_once(400 * 900)
            self.assertEqual(len(signals), 250)
            expected = set(provider.products()[10:])
            self.assertEqual({s['symbol'] for s in signals}, expected)
            self.assertTrue(all(s['classification'] == 'NO TRADE' for s in signals))
        finally:
            repo.close()

    def test_bulk_turnover_parsing(self):
        with patch.object(Coinbase, 'get', return_value={
            'BTC-USD': {'stats_24hour': {'volume': '2', 'last': '100'}},
            'INVALID-USD': {'stats_24hour': {'volume': 'NaN', 'last': '1'}},
            'MISSING-USD': {},
        }):
            self.assertEqual(Coinbase().turnovers(), {'BTC-USD': 200})
