import unittest
from contextlib import ExitStack
from unittest.mock import patch, MagicMock
from scanner.config import Config
from scanner.__main__ import main, wait_for_next_scan
from scanner.notifications.telegram import Telegram


class LifecycleTests(unittest.TestCase):
    def run_app(self, arguments, interrupted=False, failed=False):
        with ExitStack() as stack:
            stack.enter_context(patch('sys.argv', ['scanner', 'scan'] + arguments))
            stack.enter_context(patch('scanner.__main__.Config.load', return_value=Config(database=':memory:')))
            notifier = stack.enter_context(patch('scanner.__main__.Telegram')).return_value
            scanner = stack.enter_context(patch('scanner.__main__.Scanner')).return_value
            scanner.last_end = None
            scanner.retry_pending = False
            scanner.refresh_retry_at = 0
            scanner.run_once.return_value = []
            if failed:
                scanner.run_once.side_effect = RuntimeError('Fixture scan failure')
            if interrupted:
                stack.enter_context(patch('scanner.__main__.time.sleep', side_effect=KeyboardInterrupt))
            stack.enter_context(patch('builtins.print'))
            if failed:
                with self.assertRaises(SystemExit):
                    main()
            else:
                main()
            return notifier.lifecycle.call_args_list

    def test_ctrl_c_start_and_stop(self):
        calls = self.run_app(['--notify'], interrupted=True)
        self.assertEqual([c.args[0] for c in calls], ['started', 'stopped'])
        self.assertIn('Ctrl+C', calls[-1].args[2])

    def test_once_completion_and_failure(self):
        calls = self.run_app(['--once', '--notify'])
        self.assertIn('completed', calls[-1].args[2])
        calls = self.run_app(['--once', '--notify'], failed=True)
        self.assertIn('failed', calls[-1].args[2])

    def test_without_notify(self):
        self.assertEqual(self.run_app(['--once']), [])

    def test_message_content(self):
        telegram = Telegram('fixture-secret', '123')
        with patch.object(telegram, 'send_text') as send:
            telegram.lifecycle('started', Config())
            self.assertIn('SCANNER STARTED', send.call_args.args[0])
            self.assertNotIn('fixture-secret', send.call_args.args[0])
            telegram.lifecycle('stopped', Config(), 'Stopped by user (Ctrl+C)')
            self.assertIn('SCANNER STOPPED', send.call_args.args[0])

    def test_wait_shows_heartbeat_without_changing_interval(self):
        with patch('scanner.__main__.time.sleep') as sleep:
            with self.assertLogs(level='INFO') as logs:
                wait_for_next_scan(125)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [60, 60, 5])
        self.assertTrue(any('BOT RUNNING' in line for line in logs.output))
        self.assertTrue(any('next scan in 1m 5s' in line for line in logs.output))
