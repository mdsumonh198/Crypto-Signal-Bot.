import unittest
from unittest.mock import MagicMock, patch
from scanner.config import Config
from scanner.database import Repository
from scanner.market_data.coinbase import Coinbase
from scanner.models import Liquidity
from scanner.notifications.telegram import Telegram, format_signal
from scanner.risk.engine import plan
from scanner.service import Scanner
from scanner.strategy.signal_engine import evaluate
from tests.test_confirmation import setup
from tests.test_integration import FixtureProvider, FixtureRanking


class UpdateTests(unittest.TestCase):
    def test_service_refreshed_entry_is_used_in_signal_and_tracking(self):
        class Quotes(FixtureProvider):
            calls = 0
            def liquidity(self, symbol):
                self.calls += 1
                return Liquidity(99.79,99.81,2e6)
        repo = Repository(':memory:')
        provider = Quotes()
        notifier = MagicMock(chat_id='fixture')
        notifier.send.return_value = 42
        def qualified(*args):
            s = evaluate(*args)
            s['classification'] = 'BUY'
            return s
        try:
            with patch('scanner.service.evaluate', side_effect=qualified):
                result = Scanner(Config(),provider,repo,notifier,market_caps=FixtureRanking(['BTC-USD'])).run_once(360005)
            self.assertEqual(result[0]['risk']['entry'],99.81)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(notifier.send.call_args.args[0]['risk']['entry'],99.81)
            self.assertEqual(repo.db.execute('SELECT entry FROM signal_tracking').fetchone()[0],99.81)
            self.assertEqual(notifier.cycle_summary.call_count,1)
        finally:
            repo.close()
    def test_high_score_does_not_lock_out_future_qualified_buy(self):
        r = Repository(':memory:')
        try:
            signal = dict(symbol='BTC-USD', time=10000, candle_time=9000, classification='BUY', score=96)
            self.assertTrue(r.claim(signal, Config()))
            self.assertFalse(r.claim(dict(signal, time=10900, candle_time=9900, score=100), Config()))
            self.assertTrue(r.claim(dict(signal, time=100000, candle_time=99900, score=99), Config()))
            self.assertFalse(r.claim(dict(signal, time=100001, candle_time=99900, score=100), Config()))
        finally:
            r.close()

    def test_pagination_owns_each_completed_bucket_exactly_once(self):
        first = [[t, 1, 3, 2, 2, 10] for t in range(0, 300 * 900, 900)]
        second = [[299 * 900, 1, 3, 2, 2.1, 11], [300 * 900, 1, 3, 2, 2, 20]]
        with patch.object(Coinbase, 'get', side_effect=[first, second]):
            bars = Coinbase().candles('BTC-USD', 0, 300 * 900, 900)
        self.assertEqual(len(bars), 300)
        self.assertEqual(bars[-1].close, 2.1)
        self.assertEqual(bars[-1].volume, 11)
        self.assertTrue(all(b.time + 900 <= 300 * 900 for b in bars))

    def test_genuine_same_page_conflict_is_still_rejected(self):
        with patch.object(Coinbase, 'get', return_value=[[0,1,3,2,2,10], [0,1,3,2,2.1,11]]):
            with self.assertRaisesRegex(ValueError, 'Conflicting duplicate'):
                Coinbase().candles('BTC-USD', 0, 900, 900)

    def test_entry_and_target_use_current_ask_not_historical_close(self):
        bars, indicators, _ = setup()
        quote = Liquidity(109.59, 109.61, 2e6)
        risk = plan(indicators, quote, Config(), entry_price=quote.ask)
        self.assertEqual(risk['entry'], 109.61)
        self.assertEqual(risk['confirmed_close'], 110)
        self.assertAlmostEqual(risk['take_profit'], 109.61 + 2 * (109.61 - risk['stop_loss']))
        with patch('scanner.strategy.signal_engine.indicators', return_value=indicators):
            s = evaluate('ETH-USD', bars, 'BULLISH', quote, Config(), 300 * 900)
        self.assertEqual(s['risk']['entry'], quote.ask)
        self.assertIn('Confirmed candle close: $110', format_signal(s))
        self.assertIn('Coinbase ask', format_signal(s))

    def test_fresh_entry_does_not_bypass_stale_quote_confirmation(self):
        bars, indicators, _ = setup()
        with patch('scanner.strategy.signal_engine.indicators', return_value=indicators), patch('scanner.strategy.signal_engine.score', return_value=(99,{},{})):
            s = evaluate('ETH-USD', bars, 'BULLISH', Liquidity(112,112.01,2e6), Config(), 300 * 900)
        self.assertNotEqual(s['classification'], 'BUY')
        self.assertIn('Quote moved too far from confirmed close; entry stale', s['invalidation_reasons'])

    def test_no_setup_status_once_per_bucket_and_across_restart(self):
        repo = Repository(':memory:')
        notifier = MagicMock(chat_id='fixture')
        provider = FixtureProvider()
        source = FixtureRanking(provider.products())
        try:
            scanner = Scanner(Config(), provider, repo, notifier, market_caps=source)
            scanner.run_once(360005)
            scanner.run_once(360065)
            Scanner(Config(), provider, repo, notifier, market_caps=source).run_once(360120)
            notifier.send.assert_not_called()
            self.assertEqual(notifier.cycle_summary.call_count, 1)
            scanner.run_once(360905)
            self.assertEqual(notifier.cycle_summary.call_count, 2)
            self.assertEqual(notifier.cycle_summary.call_args.args[3], 0)
        finally:
            repo.close()

    def test_cycle_transport_failure_is_not_retried_ambiguously(self):
        repo = Repository(':memory:')
        notifier = MagicMock(chat_id='fixture')
        notifier.cycle_summary.side_effect = RuntimeError('Ambiguous delivery')
        try:
            scanner = Scanner(Config(), FixtureProvider(), repo, notifier)
            scanner.report_cycle(360000)
            scanner.report_cycle(360000)
            self.assertEqual(notifier.cycle_summary.call_count, 1)
            self.assertEqual(repo.db.execute('SELECT status FROM cycle_notifications').fetchone()[0], 'ambiguous_or_failed')
        finally:
            repo.close()

    def test_status_wording_does_not_fabricate_trade_signal(self):
        telegram = Telegram('fixture', '1')
        with patch.object(telegram, 'send_text') as send:
            telegram.cycle_summary(360000,10,10,0,0)
        self.assertIn('No confirmed BUY opportunity', send.call_args.args[0])
        self.assertNotIn('BUY SIGNAL', send.call_args.args[0])
