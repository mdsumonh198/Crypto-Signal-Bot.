import unittest
from unittest.mock import patch
from dataclasses import replace
from scanner.config import Config
from scanner.database import Repository
from scanner.models import Candle
from scanner.paper_trading.engine import PaperEngine
from scanner.backtesting.engine import backtest


def signal(when=250 * 900):
    return dict(symbol='ETH-USD', classification='BUY', time=when, candle_time=when - 900,
                score=90, risk=dict(approved=True, entry=100, stop_loss=95, take_profit=110))


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(':memory:')
        self.config = Config(fee_bps=0, slippage_bps=0)
        self.paper = PaperEngine(self.repo, self.config)

    def tearDown(self):
        self.repo.close()

    def test_entry_excludes_past_and_stop_first(self):
        s = signal()
        self.assertTrue(self.paper.open(s))
        self.assertFalse(self.paper.open(s))
        self.paper.update('ETH-USD', [Candle(s['time'] - 900, 90, 120, 100, 100, 1)])
        self.assertEqual(self.paper.stats()['open_positions'], 1)
        self.paper.update('ETH-USD', [Candle(s['time'], 90, 120, 100, 100, 1)])
        self.assertEqual(self.paper.stats()['losses'], 1)
        row = self.repo.db.execute('SELECT * FROM paper').fetchone()
        self.assertEqual(row['exit'], 95)

    def test_gap_and_costs(self):
        paper = PaperEngine(self.repo, replace(self.config, fee_bps=60, slippage_bps=5))
        paper.open(signal())
        paper.update('ETH-USD', [Candle(250 * 900, 89, 92, 90, 91, 1)])
        row = self.repo.db.execute('SELECT * FROM paper').fetchone()
        self.assertLess(row['exit'], 90)
        self.assertLess(row['pnl'], 0)

    def test_backtest_prefix_and_next_open(self):
        candles = [Candle(n * 900, 99, 103, 102, 100, 100000) for n in range(255)]
        seen = []
        def evaluate(symbol, history, regime, liquidity, config, now):
            self.assertEqual(history[-1].time + 900, now)
            self.assertTrue(all(c.time < now for c in history))
            seen.append(now)
            return dict(signal(now), components={}, indicators={})
        with patch('scanner.backtesting.engine.evaluate', side_effect=evaluate):
            result = backtest('ETH-USD', candles, candles, self.config, self.repo, 10)
        row = self.repo.db.execute('SELECT * FROM paper').fetchone()
        self.assertEqual(row['entry'], 102)
        self.assertEqual(row['entry_time'], candles[250].time)
        self.assertEqual(result['signals_evaluated'], 5)
        self.assertEqual(len(seen), 5)
