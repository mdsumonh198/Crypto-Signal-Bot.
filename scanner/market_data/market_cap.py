"""CoinMarketCap ranking only; Coinbase remains the candle/quote source."""
import json
import math
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class CoinMarketCap:
    def __init__(self, api_key=''):
        self.api_key = api_key
        self.has_more = False

    def page(self, start=1, limit=100):
        root = 'https://pro-api.coinmarketcap.com'
        if not self.api_key:
            root += '/public-api'
        params = dict(start=start, limit=limit, convert='USD', sort='market_cap', sort_dir='desc')
        headers = {'Accept': 'application/json', 'User-Agent': 'SignalScanner/1.0'}
        if self.api_key:
            headers['X-CMC_PRO_API_KEY'] = self.api_key
        url = root + '/v3/cryptocurrency/listings/latest?' + urlencode(params)
        for attempt in range(3):
            try:
                with urlopen(Request(url, headers=headers), timeout=10) as response:
                    payload = json.load(response)
                result = self.parse(payload)
                self.has_more = len(payload['data']) == limit
                return result
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f'CoinMarketCap HTTP {exc.code}; new signals blocked') from None
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise RuntimeError('CoinMarketCap unavailable; new signals blocked') from None
            time.sleep(2 ** attempt)

    @staticmethod
    def parse(payload):
        status = payload.get('status', {})
        if str(status.get('error_code', 0)) != '0':
            raise RuntimeError('CoinMarketCap rejected ranking request; new signals blocked')
        timestamp = status.get('timestamp')
        if not timestamp:
            raise ValueError('Market-cap ranking timestamp missing')
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if parsed.tzinfo is None or not -120 <= time.time() - parsed.timestamp() <= 180:
            raise ValueError('Market-cap ranking snapshot stale or clock invalid')
        rows = payload.get('data')
        if not isinstance(rows, list):
            raise ValueError('Unexpected CoinMarketCap listings schema')
        result = []
        for row in rows:
            rank, symbol, identity = row['cmc_rank'], row['symbol'], row['id']
            if rank in (None, 0):
                continue
            if not isinstance(rank, int) or rank < 1 or not isinstance(symbol, str):
                raise ValueError('Invalid market-cap identity/rank')
            tags = row['tags']
            if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                raise ValueError('Missing stablecoin classification metadata')
            quotes = row['quote']
            usd = quotes.get('USD') if isinstance(quotes, dict) else next((q for q in quotes if q.get('symbol') == 'USD'), None)
            cap = float(usd['market_cap']) if usd else float('nan')
            if not math.isfinite(cap) or cap <= 0:
                raise ValueError('Invalid ranked market-cap value')
            result.append(dict(id=identity, symbol=symbol.upper(), rank=rank, market_cap=cap,
                               stable=any('stablecoin' in tag.lower() for tag in tags)))
        return sorted(result, key=lambda row: row['rank'])
