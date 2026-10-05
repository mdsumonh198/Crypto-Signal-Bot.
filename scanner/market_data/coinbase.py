import json
import time
import math
import threading
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError
from scanner.models import Candle, Liquidity


class Coinbase:
    """Public Exchange API; this client exposes GET market data only."""
    def __init__(self):
        self.last_request = 0.0
        self.request_lock = threading.Lock()

    def get(self, path, params=None):
        url = 'https://api.exchange.coinbase.com' + path
        if params:
            url += '?' + urlencode(params)
        for attempt in range(4):
            # Shared pacing across workers; network IO does not hold the lock.
            with self.request_lock:
                time.sleep(max(0, 0.35 - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
            try:
                with urlopen(Request(url, headers={'User-Agent': 'SignalScanner/1.0', 'Accept': 'application/json'}), timeout=20) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise RuntimeError(f'Coinbase HTTP {exc.code} for {path}') from None
            except (URLError, TimeoutError):
                if attempt == 3:
                    raise RuntimeError(f'Coinbase unavailable for {path}') from None
            time.sleep(2 ** attempt)

    def products(self):
        return sorted(p['id'] for p in self.get('/products')
                      if p.get('quote_currency') == 'USD' and p.get('status') == 'online'
                      and not any(p.get(k, False) for k in ('trading_disabled', 'cancel_only', 'post_only', 'limit_only')))

    def turnovers(self):
        """Bulk observed 24-hour base volume times last price for ranking."""
        result = {}
        for symbol, row in self.get('/products/stats').items():
            try:
                stats = row['stats_24hour']
                value = float(stats['volume']) * float(stats['last'])
                if math.isfinite(value) and value >= 0:
                    result[symbol] = value
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def candles(self, symbol, start, end, timeframe):
        rows = {}
        cursor = start
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
        while cursor < end:
            stop = min(end, cursor + 299 * timeframe)
            result = self.get(f'/products/{quote(symbol, safe="")}/candles',
                              {'start': iso(cursor), 'end': iso(stop), 'granularity': timeframe})
            for raw in result:
                if len(raw) != 6:
                    raise ValueError('Unexpected candle schema')
                c = Candle(int(raw[0]), *(float(v) for v in raw[1:]))
                # Each page owns only its half-open window. Coinbase can return
                # boundary rows belonging to the next page; do not mix snapshots.
                if cursor <= c.time and c.time + timeframe <= stop:
                    if c.time in rows and rows[c.time] != c:
                        raise ValueError('Conflicting duplicate candle')
                    rows[c.time] = c
            cursor = stop
        return [rows[t] for t in sorted(rows)]

    def liquidity(self, symbol):
        started = time.time()
        row = self.get(f'/products/{quote(symbol, safe="")}/ticker')
        observed = time.time()
        # Ticker time is the last trade's timestamp, not a book-update timestamp.
        # Reject stale activity conservatively instead of asserting a live fill.
        timestamp = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('Coinbase ticker timestamp lacks timezone')
        result = Liquidity(float(row['bid']), float(row['ask']), float(row['volume']) * float(row['price']),
                           timestamp.timestamp(), observed, started)
        result.spread_bps
        return result


class CandleNotReady(ValueError):
    """Requested completed bucket has not been published yet."""


def validate_history(candles, timeframe, end, minimum=250):
    if not candles or candles[-1].time < end - timeframe:
        raise CandleNotReady('Latest completed candle missing/stale')
    if len(candles) < minimum:
        raise ValueError(f'Insufficient completed candles: {len(candles)} < {minimum}')
    if candles[-1].time != end - timeframe:
        raise ValueError('Latest completed candle missing/stale')
    if any(c.time % timeframe for c in candles):
        raise ValueError('Unaligned candle timestamp')
    if any(b.time - a.time != timeframe for a, b in zip(candles, candles[1:])):
        raise ValueError('Candle gap or duplicate; no fabricated fills allowed')
