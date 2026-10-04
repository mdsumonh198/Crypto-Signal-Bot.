import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from scanner.database import Repository
from scanner.models import Candle
from scanner.tracking import SignalTracker
from scanner.notifications.telegram import Telegram
from scanner.service import Scanner
from scanner.config import Config
from tests.test_integration import FixtureProvider


def signal():
    return dict(symbol='ETH-USD', classification='BUY', timeframe=900,
                risk=dict(entry=100, stop_loss=95, take_profit=110))


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(':memory:')
        self.provider = MagicMock()
        self.notifier = MagicMock(chat_id='123')
        self.tracker = SignalTracker(self.repo, self.provider, self.notifier)

    def tearDown(self):
        self.repo.close()

    def test_tp_reply_stats_and_duplicate_protection(self):
        self.tracker.register(signal(), 42, '123', 900)
        self.provider.candles.return_value = [Candle(900, 99, 112, 100, 111, 1)]
        self.tracker.update(1800)
        self.tracker.update(1801)
        self.notifier.trade_update.assert_called_once()
        trade, stats = self.notifier.trade_update.call_args.args
        self.assertEqual(trade['message_id'], 42)
        self.assertEqual(trade['outcome'], 'TP')
        self.assertEqual(stats, dict(total=1, closed=1, open=0, wins=1, losses=0, win_rate=100))

    def test_sl_first_and_gap(self):
        self.tracker.register(signal(), 42, '123', 900)
        self.provider.candles.return_value = [Candle(900, 90, 112, 100, 111, 1)]
        self.tracker.update(1800)
        self.assertEqual(self.tracker.stats('123')['losses'], 1)
        self.tracker.register(signal(), 43, '123', 1800)
        self.provider.candles.return_value = [Candle(1800, 88, 92, 90, 91, 1)]
        self.tracker.update(2700)
        row = self.repo.db.execute('SELECT hit_price FROM signal_tracking WHERE message_id=43').fetchone()
        self.assertEqual(row[0], 90)

    def test_partial_entry_candle_is_excluded(self):
        self.tracker.register(signal(), 42, '123', 901)
        self.tracker.update(1800)
        self.provider.candles.assert_not_called()
        self.notifier.trade_update.assert_not_called()
        self.assertEqual(self.tracker.stats('123')['open'], 1)

    def test_history_gap_does_not_invent_outcome(self):
        self.tracker.register(signal(), 42, '123', 900)
        self.provider.candles.return_value = [Candle(1800, 99, 112, 100, 111, 1)]
        with self.assertLogs('scanner.tracking', level='ERROR'):
            self.tracker.update(2700)
        self.assertEqual(self.tracker.stats('123')['closed'], 0)

    def test_ambiguous_reply_not_retried(self):
        self.tracker.register(signal(), 42, '123', 900)
        self.provider.candles.return_value = [Candle(900, 99, 112, 100, 111, 1)]
        self.notifier.trade_update.side_effect = RuntimeError('Fixture timeout')
        with self.assertLogs('scanner.tracking', level='ERROR'):
            self.tracker.update(1800)
        self.tracker.update(2700)
        self.notifier.trade_update.assert_called_once()
        self.assertEqual(self.repo.db.execute('SELECT reply_status FROM signal_tracking').fetchone()[0], 'ambiguous_or_failed')

    def test_restart_preserves_parent_and_open_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'db.sqlite')
            repo = Repository(path)
            SignalTracker(repo, self.provider).register(signal(), 42, '123', 900)
            repo.close()
            repo = Repository(path)
            try:
                self.provider.candles.return_value = [Candle(900, 99, 112, 100, 111, 1)]
                SignalTracker(repo, self.provider, self.notifier).update(1800)
                self.assertEqual(self.notifier.trade_update.call_args.args[0]['message_id'], 42)
            finally:
                repo.close()

    def test_no_replies_to_another_chat(self):
        self.tracker.register(signal(), 42, 'other-chat', 900)
        self.provider.candles.return_value = [Candle(900, 99, 112, 100, 111, 1)]
        self.tracker.update(1800)
        self.notifier.trade_update.assert_not_called()
        self.assertEqual(self.tracker.stats('123')['total'], 0)

    def test_watch_is_not_tracked(self):
        self.tracker.register(dict(signal(), classification='WATCH'), 42, '123', 900)
        self.assertEqual(self.tracker.stats('123')['total'], 0)

    def test_reply_transport_and_human_readable_statistics(self):
        transport = MagicMock()
        transport.__enter__.return_value.read.return_value = b'{"ok":true,"result":{"message_id":99}}'
        trade = dict(symbol='ETH-USD', message_id=42, outcome='TP', entry=100,
                     stop=95, target=110, hit_price=110, hit_time=1800)
        stats = dict(total=5, closed=3, open=2, wins=2, losses=1, win_rate=2 / 3 * 100)
        with patch('scanner.notifications.telegram.urlopen', return_value=transport) as send:
            message_id = Telegram('fixture', '123').trade_update(trade, stats)
        payload = json.loads(send.call_args.args[0].data)
        self.assertEqual(message_id, 99)
        self.assertEqual(payload['reply_parameters']['message_id'], 42)
        self.assertFalse(payload['reply_parameters']['allow_sending_without_reply'])
        self.assertIn('TP HIT — WIN', payload['text'])
        self.assertIn('Wins (TP): 2 | Losses (SL): 1', payload['text'])
        self.assertIn('66.7%', payload['text'])

    def test_service_tracks_buy_without_paper_mode(self):
        notifier = MagicMock(chat_id='123')
        notifier.send.return_value = 42
        config = Config(top_markets=0, pairs='BTC-USD', paper=False)
        from scanner.strategy.signal_engine import evaluate
        def buy(*args):
            s = evaluate(*args)
            s['classification'] = 'BUY'
            return s
        with patch('scanner.service.evaluate', side_effect=buy):
            Scanner(config, FixtureProvider(), self.repo, notifier).run_once(400 * 900)
        self.assertEqual(self.repo.db.execute('SELECT message_id FROM signal_tracking').fetchone()[0], 42)
        self.assertEqual(self.repo.db.execute('SELECT COUNT(*) FROM paper').fetchone()[0], 0)
