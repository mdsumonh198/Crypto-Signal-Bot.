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

    @property
    def spread_bps(self):
        if not all(math.isfinite(x) for x in (self.bid, self.ask, self.volume_usd)) or self.bid <= 0 or self.ask < self.bid or self.volume_usd < 0:
            raise ValueError('Invalid liquidity snapshot')
        return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 10000
