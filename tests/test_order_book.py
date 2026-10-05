import unittest
from unittest.mock import patch
from scanner.market_data.coinbase import Coinbase


def book(**changes):
    return dict(dict(bids=[['100', '2', 1]], asks=[['100.01', '3', 1]],
                     time='1970-01-01T00:16:39Z', auction_mode=False), **changes)


class OrderBookTests(unittest.TestCase):
    def fetch(self, snapshot, stats=None):
        with patch.object(Coinbase, 'get', side_effect=[stats or dict(volume='20000', last='90'), snapshot]) as get:
            with patch('scanner.market_data.coinbase.time.time', side_effect=[998,1000]):
                quote = Coinbase().liquidity('BNB-USD')
        self.assertEqual(get.call_args_list[-1].args, ('/products/BNB-USD/book', {'level':1}))
        return quote

    def test_entry_comes_from_fresh_book_despite_old_last_price(self):
        quote = self.fetch(book())
        quote.validate_freshness(1001, 15)
        self.assertEqual(quote.ask, 100.01)
        self.assertEqual(quote.bid, 100)
        self.assertEqual(quote.volume_usd, 1800000)
        self.assertEqual(quote.quote_time, 999)

    def test_old_book_snapshot_remains_blocked(self):
        quote = self.fetch(book(time='1970-01-01T00:16:00Z'))
        with self.assertRaisesRegex(ValueError, 'stale'):
            quote.validate_freshness(1001, 15)

    def test_empty_auction_or_invalid_book_is_rejected(self):
        for changes in (dict(bids=[]), dict(asks=[]), dict(auction_mode=True),
                        dict(asks=[['100.01','0',1]]), dict(asks=[['99','1',1]]),
                        dict(bids=[['nan','1',1]])):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.fetch(book(**changes))

    def test_book_failure_never_falls_back_to_ticker(self):
        with patch.object(Coinbase, 'get', side_effect=[dict(volume='20000',last='90'),RuntimeError('book unavailable')]) as get:
            with self.assertRaises(RuntimeError):
                Coinbase().liquidity('BNB-USD')
        self.assertEqual(get.call_count, 2)
        self.assertFalse(any('/ticker' in str(c) for c in get.call_args_list))

    def test_slow_book_request_remains_blocked(self):
        with patch.object(Coinbase,'get', side_effect=[dict(volume='20000',last='90'),book()]), patch('scanner.market_data.coinbase.time.time',side_effect=[980,1000]):
            quote=Coinbase().liquidity('BNB-USD')
        with self.assertRaises(ValueError):
            quote.validate_freshness(1001,15)
