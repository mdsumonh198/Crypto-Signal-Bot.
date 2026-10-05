import unittest
from dataclasses import replace
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


class PriceAuditTests(unittest.TestCase):
    def test_coinbase_captures_book_time_and_request_window(self):
        row = dict(bids=[['99.99', '1', 1]], asks=[['100.01', '1', 1]],
                   time='1970-01-01T00:16:39Z')
        with patch.object(Coinbase, 'get', side_effect=[dict(volume='20000',last='100'),row]), patch('scanner.market_data.coinbase.time.time', side_effect=[998, 1000]):
            quote = Coinbase().liquidity('ETH-USD')
        self.assertEqual((quote.quote_time, quote.observed_at, quote.request_started_at), (999, 1000, 998))
        quote.validate_freshness(1001, 15)

    def test_missing_or_naive_book_time_is_rejected(self):
        row = dict(bids=[['99','1',1]], asks=[['100','1',1]])
        for stamp in (None, '2026-10-05T12:00:00'):
            with self.subTest(stamp=stamp), patch.object(Coinbase, 'get', side_effect=[dict(volume='20000',last='100'),dict(row, time=stamp)]):
                with self.assertRaises((ValueError, AttributeError)):
                    Coinbase().liquidity('ETH-USD')

    def test_stale_delayed_future_and_partial_quotes_fail_closed(self):
        for stamps in ((980, 1000, 999), (999, 1000, 980), (1010, 1000, 999),
                       (999, None, 999), (float('nan'), 1000, 999)):
            with self.subTest(stamps=stamps), self.assertRaises(ValueError):
                Liquidity(99, 100, 2e6, *stamps).validate_freshness(1000, 15)

    def test_fresh_quote_expires_even_without_price_drift(self):
        bars, i, quote = setup()
        quote = replace(quote, quote_time=999, observed_at=1000, request_started_at=999)
        with patch('scanner.strategy.signal_engine.indicators', return_value=i), patch('scanner.strategy.signal_engine.score', return_value=(100, {}, {})):
            with self.assertRaisesRegex(ValueError, 'stale'):
                evaluate('ETH-USD', bars, 'BULLISH', quote, Config(), 1020)

    def test_stale_service_quote_never_opens_paper_or_sends_buy(self):
        provider = FixtureProvider()
        provider.liquidity = MagicMock(return_value=Liquidity(99.99, 100.01, 2e6, 359970, 360005, 360004))
        repo = Repository(':memory:')
        notifier = MagicMock(chat_id='fixture')
        try:
            scanner = Scanner(Config(paper=True), provider, repo, notifier, FixtureRanking(['BTC-USD']))
            with self.assertRaisesRegex(RuntimeError, 'All markets failed'):
                scanner.run_once(360005)
            notifier.send.assert_not_called()
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM paper').fetchone()[0], 0)
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM signal_tracking').fetchone()[0], 0)
            self.assertEqual(notifier.cycle_summary.call_args.args[4], 1)
        finally:
            repo.close()

    def test_entries_precede_tracking_and_tracking_runs_even_on_failure(self):
        repo = Repository(':memory:')
        scanner = Scanner(Config(), FixtureProvider(), repo)
        events = []
        try:
            with (patch.object(scanner, '_run_entries', side_effect=lambda now: events.append('entries')),
                  patch.object(scanner.tracker, 'update', side_effect=lambda now: events.append('tracking'))):
                scanner.run_once(360005)
            self.assertEqual(events, ['entries', 'tracking'])
            with (patch.object(scanner, '_run_entries', side_effect=RuntimeError('API unavailable')),
                  patch.object(scanner.tracker, 'update') as update):
                with self.assertRaises(RuntimeError):
                    scanner.run_once(360005)
                update.assert_called_once_with(360005)
        finally:
            repo.close()

    def test_quote_prices_and_timestamp_visible_in_signal(self):
        bars, i, quote = setup()
        quote = replace(quote, quote_time=999, observed_at=1000, request_started_at=999)
        with patch('scanner.strategy.signal_engine.indicators', return_value=i):
            s = evaluate('ETH-USD', bars, 'BULLISH', quote, Config(), 1001)
        text = format_signal(s)
        self.assertIn('Coinbase spot bid / ask:', text)
        self.assertIn('Quote observed at: 1970-01-01T00:16:40+00:00', text)
        self.assertEqual(s['quote']['ask'], s['risk']['entry'])

    def test_invalid_entry_cannot_create_invalid_risk_plan(self):
        _, i, quote = setup()
        for entry in (0, -1, float('nan'), float('inf')):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                plan(i, quote, Config(), entry_price=entry)
        risk = plan(i, quote, Config(), entry_price=1)
        self.assertFalse(risk['approved'])

    def test_lifecycle_uses_effective_ten_even_with_legacy_config(self):
        with patch.object(Telegram, 'send_text') as send:
            Telegram('fixture', '1').lifecycle('started', Config(top_markets=250))
        self.assertIn('Top 10', send.call_args.args[0])
        self.assertNotIn('Top 250', send.call_args.args[0])

    def test_quote_age_setting_cannot_disable_validation(self):
        for value in (0, -1, float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Config(max_quote_age=value)

    def test_quote_expiring_during_evaluation_cannot_create_paper_position(self):
        repo = Repository(':memory:')
        provider = FixtureProvider()
        provider.liquidity = MagicMock(return_value=Liquidity(99.99, 100.01, 2e6, 360004, 360005, 360004))
        notifier = MagicMock(chat_id='fixture')
        scanner = Scanner(Config(paper=True), provider, repo, notifier, FixtureRanking(['BTC-USD']))
        try:
            with patch('scanner.service.time.time', return_value=360005) as clock:
                def delayed(*args):
                    s = evaluate(*args)
                    s['classification'] = 'BUY'
                    s['risk']['approved'] = True
                    clock.return_value = 360025
                    return s
                with patch('scanner.service.evaluate', side_effect=delayed):
                    with self.assertRaises(RuntimeError):
                        scanner.run_once()
            notifier.send.assert_not_called()
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0], 0)
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM paper').fetchone()[0], 0)
        finally:
            repo.close()

    def test_quote_expiring_before_send_marks_reservation_blocked(self):
        repo = Repository(':memory:')
        provider = FixtureProvider()
        provider.liquidity = MagicMock(return_value=Liquidity(99.99, 100.01, 2e6, 360004, 360005, 360004))
        notifier = MagicMock(chat_id='fixture')
        scanner = Scanner(Config(), provider, repo, notifier, FixtureRanking(['BTC-USD']))
        claim = repo.claim
        try:
            with patch('scanner.service.time.time', return_value=360005) as clock:
                def buy(*args):
                    s = evaluate(*args)
                    s['classification'] = 'BUY'
                    return s
                def delayed_claim(*args):
                    result = claim(*args)
                    clock.return_value = 360025
                    return result
                with patch('scanner.service.evaluate', side_effect=buy), patch.object(repo, 'claim', side_effect=delayed_claim):
                    scanner.run_once()
            notifier.send.assert_not_called()
            self.assertEqual(repo.db.execute('SELECT status FROM notifications').fetchone()[0], 'blocked_stale_quote')
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM signal_tracking').fetchone()[0], 0)
        finally:
            repo.close()
