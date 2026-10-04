import os
import math
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    pairs: str = 'BTC-USD,ETH-USD'
    top_markets: int = 250
    timeframe: int = 900
    scan_interval: int = 60
    history: int = 300
    min_volume_usd: float = 1_000_000
    max_spread_bps: float = 20
    max_atr_pct: float = 5
    min_atr_pct: float = 0.05
    buy_score: float = 75
    watch_score: float = 60
    rsi_low: float = 52
    rsi_high: float = 68
    volume_buy_ratio: float = 1.05
    btc_breakdown_pct: float = -3
    btc_bearish_pct: float = -1
    stop_atr: float = 2
    reward_risk: float = 2
    max_stop_pct: float = 10
    cooldown: int = 3600
    score_improvement: float = 5
    watch_alerts: bool = False
    watch_to_buy: bool = True
    telegram_token: str = ''
    telegram_chat_id: str = ''
    paper: bool = False
    risk_per_trade: float = 0.01
    max_exposure: float = 0.3
    max_positions: int = 5
    daily_loss_limit: float = 0.03
    paper_equity: float = 10000
    fee_bps: float = 60
    slippage_bps: float = 5
    database: str = 'data/scanner.sqlite'

    def __post_init__(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, (float, int)) and not math.isfinite(value):
                raise ValueError(f'{f.name} must be finite')
        if self.timeframe not in (60, 300, 900, 3600, 21600, 86400):
            raise ValueError('Unsupported Coinbase candle timeframe')
        if not 250 <= self.history <= 10000 or self.scan_interval < 10:
            raise ValueError('history >= 250 and scan_interval >= 10 required')
        if not 0 <= self.watch_score < self.buy_score <= 100:
            raise ValueError('Invalid score thresholds')
        if not 0 < self.rsi_low < self.rsi_high < 100:
            raise ValueError('Invalid RSI band')
        for name in ('min_volume_usd', 'max_spread_bps', 'max_atr_pct', 'stop_atr',
                     'reward_risk', 'max_stop_pct', 'paper_equity', 'max_positions'):
            if getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive')
        if not 0 <= self.min_atr_pct < self.max_atr_pct:
            raise ValueError('Invalid ATR band')
        if any(not 0 < getattr(self, n) <= 1 for n in ('risk_per_trade', 'max_exposure', 'daily_loss_limit')):
            raise ValueError('Risk controls must be fractions in (0, 1]')
        if min(self.cooldown, self.score_improvement, self.top_markets, self.fee_bps, self.slippage_bps) < 0:
            raise ValueError('Negative configuration value')
        if not self.btc_breakdown_pct < self.btc_bearish_pct < 0 or self.volume_buy_ratio <= 1:
            raise ValueError('Invalid BTC thresholds or volume confirmation ratio')
        if self.fee_bps >= 10000 or self.slippage_bps >= 10000:
            raise ValueError('Fees and slippage must be below 10000 basis points')

    @classmethod
    def load(cls, path='.env'):
        values = {}
        if Path(path).exists():
            for line in Path(path).read_text(encoding='utf-8').splitlines():
                if line.strip() and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    values[key.strip()] = value.strip().strip('\"').strip("'")
        values.update(os.environ)
        kwargs = {}
        for f in fields(cls):
            key = f.name.upper()
            if key in values:
                if f.type is bool:
                    if values[key].lower() not in ('true', 'false'):
                        raise ValueError(f'{key} must be true or false')
                    kwargs[f.name] = values[key].lower() == 'true'
                else:
                    kwargs[f.name] = f.type(values[key])
        return cls(**kwargs)
