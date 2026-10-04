import unittest
from scanner.strategy.indicators import ema, rsi, macd


class IndicatorTests(unittest.TestCase):
    def test_ema_seed_and_update(self):
        self.assertEqual(ema([1, 2, 3, 4], 3), [None, None, 2, 3])

    def test_rsi(self):
        self.assertEqual(rsi(list(range(1, 40))), 100)
        self.assertEqual(rsi(list(range(40, 1, -1))), 0)
        self.assertEqual(rsi([10] * 40), 50)
        # Published Wilder worked example: initial 14-period RSI approximately 70.46.
        reference = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10,
                     45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        self.assertAlmostEqual(rsi(reference), 70.464135, places=5)

    def test_macd(self):
        self.assertEqual(macd([10] * 100), (0, 0, 0, 0))
        self.assertGreater(macd(list(range(1, 101)))[0], 0)
