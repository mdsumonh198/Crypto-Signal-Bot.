# Top-20 / 15-minute research profile — 2026-10-05

The default universe is dynamically selected from active Coinbase USD markets using turnover, spread quality and recent three-candle price activity. The highest-turnover 40 candidates plus qualifying majors receive lightweight screening; only the final 20 receive full signal analysis. Stablecoins and poor-quality markets are excluded. Majors receive a small preference, not automatic admission. The 15-minute strategy caps full analysis at 20 even with old TOP_MARKETS=64/250 settings. See README for ranking weights. Strong confirmation, high-score rejection gates and Telegram behavior remain unchanged in this market-selection update.

A score of 94.6/100 expresses indicator alignment, not win odds. Price can reverse despite passing all filters. The stronger profile keeps 15-minute completed candles and 60-second checks, and defaults to:

- Prior completed close > EMA50 > EMA200, with EMA50 rising across three values, in addition to current bullish trend gates.
- Current positive/rising histogram, with a positive previous histogram.
- Volume at least 1.2 times the previous 20-candle average.
- Close above the prior 20-candle high plus 0.05 ATR. The current candle is excluded from the reference range; no future candles are used.
- A bullish candle closing in the top 30% of its range, with an upper wick no larger than 25% of its range.
- Price no more than 2.5 ATR above EMA50, and observed ask no more than 0.5 ATR away from the signal close.
- BTC BEARISH blocks BUY; BREAKDOWN continues blocking all alerts.
- Estimated reward/risk after configured two-sided fees and adverse entry/exit slippage of at least 1.2. Gross reward/risk remains reported separately. Cost inputs are assumptions, not live account-specific fees.

Parameters are all in `.env.example`. `STRONG_CONFIRMATION=false` disables the added candle/entry/cost filters for explicit comparisons; ordinary BUY trend/momentum/volume and quality gates still apply. Do not loosen live filters just to force more alerts. These filters may omit profitable setups, especially trend continuation/pullbacks; they have not been demonstrated to improve expected returns.

Validation: 49 automated tests passed, including a high 94.6 score rejected after a wick-based reversal warning, a valid breakout qualifying BUY, timestamp-safe prior-range calculations, cost rejection and a top-20 universe fixture. A real ETH replay for 2026-10-01 through 2026-10-03 evaluated 191 decisions and produced zero simulated entries under this profile. Zero entries provide no win-rate evidence and do not prove robustness. Broader walk-forward and paper validation remains necessary.

## Apply to the VPS

These changes are local; the remote running service has not been changed. Upload the updated `scanner` source directory (including new `strategy/confirmation.py`), then update settings in the VPS's existing private `.env`. Preserve the VPS's `data` directory/database and credentials. Do not replace them with local state.

```dotenv
TOP_MARKETS=20
TIMEFRAME=900
SCAN_INTERVAL=60
VOLUME_BUY_RATIO=1.2
STRONG_CONFIRMATION=true
BREAKOUT_LOOKBACK=20
BREAKOUT_BUFFER_ATR=0.05
MIN_CLOSE_LOCATION=0.7
MAX_UPPER_WICK=0.25
MAX_EXTENSION_ATR=2.5
MAX_ENTRY_DRIFT_ATR=0.5
MIN_NET_REWARD_RISK=1.2
EXCLUDED_PAIRS=USDT-USD,USDC-USD,DAI-USD,PYUSD-USD,USD1-USD
```

Stop the service before replacing source, run tests using the VPS virtual environment, and restart it after verification. The existing Telegram startup message should show Top 20 markets. Existing tracked BUY plans and paper positions keep their original stored stop/target. TP/SL replies continue to use those plans, including coins outside the new top-20 universe.

The provided `apply_top20_profile.py` updates only the listed settings in your existing `.env`, preserving credentials, database location and paper mode. From the project directory, after uploading this source update:

```bash
sudo systemctl stop crypto-scanner
# Replace/upload source and tests, keeping the existing .env and data directory.
.venv/bin/python apply_top20_profile.py
.venv/bin/python -m unittest discover -q
sudo systemctl start crypto-scanner
sudo journalctl -u crypto-scanner -n 30 --no-pager
```

A safe live scan with the new profile evaluated all 20 selected markets in 25.1 seconds with no data errors: BUY=0, WATCH=1, NO TRADE=19. No real Telegram messages or paper trades were produced by this validation. This is one operational snapshot, not evidence of improved strategy performance.

SELL semantics require clarification: exiting an existing long and proposing a new short are different strategies. This update does not issue an ambiguous SELL or place an order. TP/SL outcome replies remain implemented.

Latest market-selection validation: 54 automated tests passed, including full-engine call counts capped at 20 with the old 64-market setting, the old 250-market configuration, changing momentum rankings, stablecoin/spread exclusions, and lightweight three-candle screening.

Live market-selection check: selected=20 and evaluated=20 in 51.7 seconds using public Coinbase data, an in-memory database, no notifier and paper trading disabled for validation. No Telegram messages or trades were sent.
