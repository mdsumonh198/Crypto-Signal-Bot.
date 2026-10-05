import unittest
from unittest.mock import patch
from scanner.market_data.coinbase import Coinbase, validate_history
from scanner.models import Candle


class MarketTests(unittest.TestCase):
    def test_parsing_order_completion_and_duplicates(self):
        api = Coinbase()
        with patch.object(api, 'get', return_value=[[1800, 1, 3, 2, 2, 10], [900, 1, 3, 2, 2, 10], [0, 1, 3, 2, 2, 10], [900, 1, 3, 2, 2, 10]]):
            result = api.candles('BTC-USD', 0, 1800, 900)
        self.assertEqual([c.time for c in result], [0, 900])
        validate_history(result, 900, 1800, 2)
        with self.assertRaises(ValueError):
            validate_history(result, 900, 2700, 2)

    def test_gap(self):
        with self.assertRaises(ValueError):
            validate_history([Candle(t, 1, 2, 1, 2, 1) for t in (0, 1800)], 900, 2700, 2)

    def test_validation(self):
        with self.assertRaises(ValueError):
            Candle(0, 3, 2, 1, 2, 1)
