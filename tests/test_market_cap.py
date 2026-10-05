import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from scanner.market_data.market_cap import CoinMarketCap


def payload(now=10000):
    return dict(status=dict(error_code=0, timestamp=datetime.fromtimestamp(now, timezone.utc).isoformat()),
                data=[dict(id=1, cmc_rank=1, symbol='BTC', tags=['pow'], quote=[dict(symbol='USD', market_cap=1e12)]),
                      dict(id=2, cmc_rank=2, symbol='NEWSTABLE', tags=['usd-stablecoin'], quote=[dict(symbol='USD', market_cap=1e11)])])


class MarketCapTests(unittest.TestCase):
    def test_v3_rank_and_dynamic_stablecoin_tag_parsing(self):
        value = payload()
        value['status']['error_code'] = '0'
        with patch('scanner.market_data.market_cap.time.time', return_value=10000):
            result = CoinMarketCap.parse(value)
        self.assertEqual([r['rank'] for r in result], [1, 2])
        self.assertFalse(result[0]['stable'])
        self.assertTrue(result[1]['stable'])

    def test_stale_missing_metadata_and_error_snapshots_fail_closed(self):
        for change in ('stale', 'missing_tags', 'error', 'nan'):
            value = payload()
            if change == 'stale':
                value['status']['timestamp'] = datetime.fromtimestamp(1, timezone.utc).isoformat()
            elif change == 'missing_tags':
                value['data'][0]['tags'] = None
            elif change == 'error':
                value['status']['error_code'] = 1001
            else:
                value['data'][0]['quote'][0]['market_cap'] = float('nan')
            with self.subTest(change=change), patch('scanner.market_data.market_cap.time.time', return_value=10000):
                with self.assertRaises((ValueError, RuntimeError)):
                    CoinMarketCap.parse(value)

    def test_keyless_market_cap_query_and_optional_key_header(self):
        for key in ('', 'fixture-key'):
            with patch('scanner.market_data.market_cap.urlopen') as open_url, patch('scanner.market_data.market_cap.json.load', return_value=payload()), patch('scanner.market_data.market_cap.time.time', return_value=10000):
                CoinMarketCap(key).page()
            request = open_url.call_args.args[0]
            self.assertIn('sort=market_cap', request.full_url)
            self.assertEqual('/public-api/' in request.full_url, not bool(key))
            self.assertEqual(request.get_header('X-cmc_pro_api_key'), key or None)

    def test_rate_limit_retries_without_activity_fallback(self):
        error = HTTPError('https://fixture', 429, 'Rate limited', None, None)
        with patch('scanner.market_data.market_cap.urlopen', side_effect=error) as request, patch('scanner.market_data.market_cap.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'new signals blocked'):
                CoinMarketCap().page()
        self.assertEqual(request.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
