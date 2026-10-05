import unittest
from unittest.mock import patch
from dataclasses import replace
from scanner.config import Config
from scanner.models import Candle, Liquidity
from scanner.strategy.confirmation import confirm
from scanner.strategy.signal_engine import evaluate
from scanner.risk.engine import plan
from scanner.database import Repository
from tests.test_integration import FixtureProvider, Scanner


def setup():
    bars = [Candle(n * 900, 108, 109.8, 108.5, 109, 100) for n in range(299)]
    bars += [Candle(299 * 900, 108, 110.1, 109, 110, 140)]
    i = dict(price=110, ema50=108, ema200=100, atr=2, atr_pct=1.8,
             rsi=60, macd=1, histogram=.3, previous_histogram=.2,
             volume_ratio=1.4, swing_low=107, prior_trend_confirmed=True, ema50_rising=True)
    return bars, i, Liquidity(109.99, 110.01, 2e6)


class ConfirmationTests(unittest.TestCase):
    def test_qualified_breakout(self):
        bars, i, liquidity = setup()
        self.assertEqual(confirm(bars, i, liquidity, 'BULLISH', Config()), [])
        with patch('scanner.strategy.signal_engine.indicators', return_value=i), patch('scanner.strategy.signal_engine.score', return_value=(94.6, {}, {})):
            self.assertEqual(evaluate('ETH-USD', bars, 'BULLISH', liquidity, Config(), 300 * 900)['classification'], 'BUY')

    def test_high_score_cannot_bypass_reversal_filter(self):
        bars, i, liquidity = setup()
        bars[-1] = Candle(299 * 900, 108, 114, 109, 110, 140)
        with patch('scanner.strategy.signal_engine.indicators', return_value=i), patch('scanner.strategy.signal_engine.score', return_value=(94.6, {}, {})):
            s = evaluate('ETH-USD', bars, 'BULLISH', liquidity, Config(), 300 * 900)
        self.assertEqual(s['classification'], 'WATCH')
        self.assertIn('Upper wick indicates rejection', s['invalidation_reasons'])

    def test_confirmation_failures_are_explained(self):
        bars, i, liquidity = setup()
        for key, value, fragment in [('prior_trend_confirmed', False, 'Two-candle'),
                                     ('ema50_rising', False, 'Two-candle'),
                                     ('previous_histogram', -.1, 'Previous completed'),
                                     ('ema50', 100, 'overextended')]:
            with self.subTest(key=key):
                result = confirm(bars, dict(i, **{key: value}), liquidity, 'BULLISH', Config())
                self.assertTrue(any(fragment in reason for reason in result))
        self.assertTrue(any('entry stale' in r for r in confirm(bars, i, Liquidity(112, 112.01, 2e6), 'BULLISH', Config())))
        self.assertTrue(any('BTC bearish' in r for r in confirm(bars, i, liquidity, 'BEARISH', Config())))

    def test_breakout_does_not_include_current_high(self):
        bars, i, liquidity = setup()
        self.assertEqual(confirm(bars, i, liquidity, 'BULLISH', Config()), [])
        bars[-2] = Candle(298 * 900, 108, 111, 108.5, 109, 100)
        self.assertTrue(any('prior-range' in r for r in confirm(bars, i, liquidity, 'BULLISH', Config())))

    def test_costs_can_invalidate_gross_two_r_plan(self):
        _, i, liquidity = setup()
        self.assertFalse(plan(i, liquidity, Config(fee_bps=500))['approved'])
        self.assertTrue(plan(i, liquidity, Config(fee_bps=0, slippage_bps=0))['approved'])

    def test_dynamic_top_twenty_excludes_inactive_and_stable_pairs(self):
        class Markets(FixtureProvider):
            def products(self):
                return ['BTC-USD', 'USDT-USD'] + [f'COIN{n}-USD' for n in range(25)]
            def turnovers(self):
                return dict({p: 2e6 + n for n, p in enumerate(self.products())}, **{'INACTIVE-USD': 1e12, 'USDT-USD': 1e12})
        repo = Repository(':memory:')
        try:
            with self.assertLogs('scanner.service', level='INFO'):
                result = Scanner(Config(), Markets(), repo).run_once(400 * 900)
            self.assertEqual(len(result), 10)
            self.assertNotIn('USDT-USD', {s['symbol'] for s in result})
            self.assertNotIn('INACTIVE-USD', {s['symbol'] for s in result})
        finally:
            repo.close()
