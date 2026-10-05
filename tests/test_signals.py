import unittest
from dataclasses import replace
from scanner.config import Config
from scanner.models import Liquidity
from scanner.strategy.scoring import classify, score, MAXIMA
from scanner.strategy.btc_regime import detect
from scanner.risk.engine import plan
from scanner.database import Repository
from scanner.execution.coinbase import CoinbaseExecution
from scanner.execution.base import ExecutionDisabled


def sample():
    return dict(price=110, ema50=105, ema200=100, atr=2, atr_pct=1.82, rsi=60,
                macd=1, histogram=.3, previous_histogram=.2, volume_ratio=1.5,
                change_pct=.1, swing_low=107)


class SignalTests(unittest.TestCase):
    def test_boundaries(self):
        for value, expected in [(59, 'NO TRADE'), (60, 'WATCH'), (74, 'WATCH'), (75, 'BUY'), (100, 'BUY')]:
            self.assertEqual(classify(value, Config()), expected)

    def test_partial_score(self):
        total, parts, reasons = score(sample(), 'BULLISH', Liquidity(109.99, 110.01, 2e6), Config())
        self.assertAlmostEqual(total, sum(parts.values()))
        self.assertGreater(parts['Volume'], 0)
        self.assertLess(parts['Volume'], 15)
        self.assertEqual(set(reasons), set(MAXIMA))
        for k, value in parts.items():
            self.assertTrue(0 <= value <= MAXIMA[k])

    def test_breakdown_and_risk(self):
        i = sample()
        i['change_pct'] = -4
        self.assertEqual(detect(i, Config()), 'BREAKDOWN')
        r = plan(i, Liquidity(109.99, 110.01, 2e6), Config())
        self.assertEqual(r['stop_loss'], 106)
        self.assertEqual(r['take_profit'], 118)
        self.assertTrue(r['approved'])
        self.assertFalse(plan(i, Liquidity(100, 110, 1), Config())['approved'])

    def test_duplicates(self):
        r = Repository(':memory:')
        s = dict(symbol='ETH-USD', time=10000, candle_time=9000, score=80, classification='WATCH')
        self.assertTrue(r.claim(s, Config()))
        self.assertFalse(r.claim(s, Config()))
        self.assertTrue(r.claim(dict(s, time=10900, candle_time=9900, classification='BUY'), Config()))
        self.assertTrue(r.claim(dict(s, time=14500, candle_time=13500, score=82), Config()))
        self.assertFalse(r.claim(dict(s, time=14500, candle_time=13500, score=86), Config()))
        r.close()

    def test_execution_disabled(self):
        with self.assertRaises(ExecutionDisabled):
            CoinbaseExecution().submit('BUY')
