import unittest
from unittest.mock import patch, MagicMock
from scanner.notifications.telegram import Telegram, format_signal
from scanner.config import Config
from scanner.models import Candle, Liquidity
from scanner.strategy.signal_engine import evaluate


class NotificationTests(unittest.TestCase):
    def test_format_and_safe_failure(self):
        candles = [Candle(n * 900, 99, 101, 100, 100, 10) for n in range(300)]
        s = evaluate('ETH-USD', candles, 'NEUTRAL', Liquidity(99.99, 100.01, 2e6), Config(), 300 * 900)
        s['classification'] = 'WATCH'
        text = format_signal(s)
        self.assertIn('WATCH SIGNAL', text)
        self.assertNotIn('BUY SIGNAL', text)
        self.assertIn('+00:00', text)
        with patch('scanner.notifications.telegram.urlopen', side_effect=RuntimeError('secret-token-url')):
            with self.assertRaisesRegex(RuntimeError, 'ambiguous') as result:
                Telegram('secret', '123').send(s)
            self.assertNotIn('secret', str(result.exception))

    def test_successful_transport_without_real_delivery(self):
        candles = [Candle(n * 900, 99, 101, 100, 100, 10) for n in range(300)]
        s = evaluate('ETH-USD', candles, 'NEUTRAL', Liquidity(99.99, 100.01, 2e6), Config(), 300 * 900)
        transport = MagicMock()
        transport.__enter__.return_value.read.return_value = b'{"ok":true,"result":{"message_id":123}}'
        with patch('scanner.notifications.telegram.urlopen', return_value=transport) as call:
            Telegram('test-token', '123').send(s)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[0].method, 'POST')
