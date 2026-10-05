from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class Candle:
    time: int
    low: float
    high: float
    open: float
    close: float
    volume: float

    def __post_init__(self):
        if not all(math.isfinite(x) for x in asdict(self).values()):
            raise ValueError('Non-finite candle')
        if self.time < 0 or self.low <= 0 or self.volume < 0 or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError('Invalid OHLCV candle')


@dataclass(frozen=True)
class Liquidity:
    bid: float
    ask: float
    volume_usd: float
    # Optional only for historical replay/test providers. Live Coinbase supplies all.
    quote_time: float | None = None
    observed_at: float | None = None
    request_started_at: float | None = None

    def validate_freshness(self, now, max_age):
        stamps = (self.quote_time, self.observed_at, self.request_started_at)
        if all(stamp is None for stamp in stamps):
            return  # Historical spread assumptions have no live timestamp.
        if any(stamp is None or not math.isfinite(stamp) for stamp in stamps):
            raise ValueError('Missing or invalid quote timestamp')
        if any(stamp > now + 2 for stamp in stamps):
            raise ValueError('Quote timestamp is in the future; check clock')
        if self.request_started_at > self.observed_at or self.quote_time > self.observed_at + 2:
            raise ValueError('Inconsistent quote/request timestamps')
        if any(now - stamp > max_age for stamp in stamps):
            raise ValueError('Coinbase quote stale or request delayed; new entry blocked')

    @property
    def spread_bps(self):
        if not all(math.isfinite(x) for x in (self.bid, self.ask, self.volume_usd)) or self.bid <= 0 or self.ask < self.bid or self.volume_usd < 0:
            raise ValueError('Invalid liquidity snapshot')
        return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 10000
