# Crypto Market Scanner + Signal Engine + Telegram Bot

The latest top-20 / 15-minute research profile and VPS update steps are in [STRATEGY_UPDATE.md](STRATEGY_UPDATE.md).

For client acceptance and deployment status, see [CLIENT_HANDOVER.md](CLIENT_HANDOVER.md).

A Python 3.11+ signal-only service using real Coinbase Exchange public market data. It evaluates completed OHLCV candles, explains a 0–100 score, applies independent BUY qualification and quality checks, stores every successful analysis in SQLite, and optionally sends Telegram BUY/WATCH alerts. It can simulate trades and replay historical data. No order API, exchange secret, or switch enabling real execution exists.

## Architecture

`Coinbase public GET data → validation → indicators/BTC regime → scoring → qualification/risk plan → SQLite → optional Telegram/paper simulation`

- `scanner/config.py`: validated environment configuration.
- `scanner/market_data/`: provider protocol and Coinbase client; add exchanges behind this interface.
- `scanner/strategy/`: indicators, BTC detection, scoring and decisions.
- `scanner/risk/`: ATR/structure stop and quality approval.
- `scanner/database.py`, `models.py`: SQLite repository and typed market records.
- `scanner/notifications/`: Telegram formatting and delivery.
- `scanner/paper_trading/`, `backtesting/`: simulation and historical replay.
- `scanner/execution/`: future Coinbase/Robinhood boundaries that always raise `ExecutionDisabled`.
- `scanner/service.py`, `__main__.py`: orchestration and command-line entry point.

## Install and run

Install Python 3.11 or later and open a terminal in this repository. On Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m scanner scan --once --no-paper
```

On macOS/Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m scanner scan --once --no-paper
```

The application and tests use only Python's standard library; `requirements.txt` intentionally has no external dependencies. In commands below, use your environment's Python executable in place of `python`.

On this Windows workspace, `python` is not on PATH. You can run `powershell -ExecutionPolicy Bypass -File .\run.ps1` immediately: the launcher chooses the project virtual environment, a registered Python launcher, or the available bundled Codex runtime. With no arguments it performs one safe scan with notifications and paper trading disabled. `powershell -ExecutionPolicy Bypass -File .\run.ps1 stats` shows local simulated account statistics. Create a normal virtual environment for independent deployment.

```bash
python -m scanner scan                         # continuous local scans; no Telegram
python -m scanner scan --once --no-paper       # safe real-data inspection, JSON output
python -m scanner scan --notify                # continuous scanning and Telegram alerts
python -m scanner --env custom.env scan --once
python -m unittest discover -v
```

Stop with Ctrl+C. For deployment, run one process per database under a supervisor with restart and log rotation. Logs go to stderr; scans, failures, notification reservations and simulated positions persist in SQLite. Do not run multiple scanners sharing one database: notification reservation assumes a single writer. Keep `.env`, SQLite files and logs private. SQLite is suitable for one scanner process; a multi-worker deployment needs transactional claims and a server database. Back up the database while stopped or use SQLite's backup API.

The terminal prints startup status, Coinbase's active USD market count, selected pairs, analysis progress, qualification reasons and a scan summary (BUY/WATCH/NO TRADE/errors/Telegram alert counts). Between scans it prints `BOT RUNNING` every 60 seconds with the time remaining until the next scan. This heartbeat confirms the waiting process is alive; it does not change candle timing or create extra Telegram messages.

The safe inspection command was verified against live BTC-USD and ETH-USD data. Telegram is not required for local scanning. API errors return nonzero for `--once`; continuous mode records errors and retries on the next interval. HTTP GET requests use timeouts, rate pacing and bounded retries for network errors, 429 and transient server errors. Candle data is fetched at most once per completed bucket per process. A failed whole-market cycle is visible in logs and the errors table; no synthetic prices or fallback random signals are generated.

## Configuration

Every setting is listed in `.env.example`; environment variables override the file. `TOP_MARKETS=20` dynamically selects up to 20 active Coinbase USD pairs before each new completed-candle analysis cycle. The selector first shortlists the highest-turnover 40 markets plus qualifying majors (BTC, ETH, SOL, XRP, DOGE, ZEC, NEAR, HYPE). It screens these using fresh quotes and just three completed candles, rejecting stablecoins, configured exclusions, inadequate turnover, excessive spreads and incomplete recent data. Ranking combines normalized turnover (50%), spread quality as a liquidity proxy (25%), recent price change/range activity (25%), and a small 0.03 preference for qualifying majors. This is exchange activity ranking, not global market capitalization or measured order-book depth. Only the final 20 receive full strategy evaluation. Fewer may be selected if quality data is unavailable. Logs print `Selected Top 20 active markets` and the symbols. For 15-minute scans, old values such as 64 or 250 are capped at 20; `TOP_MARKETS=0` retains manual `PAIRS` mode, also capped at 20. Existing paper positions and notified trade plans outside the list continue exit monitoring separately. Four workers share the existing rate limiter. BTC history remains available for market safety even when BTC is outside the selected list.

`TIMEFRAME` is seconds, default 900 (15 minutes), and accepts Coinbase's 60, 300, 900, 3600, 21600, 86400 values. `SCAN_INTERVAL` defaults to 60 seconds. This checks for a newly completed candle every minute; an unchanged candle is skipped before market API calls. It does not turn the strategy into a one-minute strategy. A signal arrives after candle completion plus polling delay and data-fetch/analysis time; slow discovery or unavailable data can delay or prevent it. `HISTORY` defaults to 300 and must be at least 250. Historical requests are split into windows below the 300-candle request limit, sorted and deduplicated. Only candles ending at or before the current UTC bucket boundary are included. Missing intervals, a missing latest completed candle, invalid OHLCV or conflicting duplicates block evaluation. Coinbase omits intervals without trades; this service deliberately does not invent fills. Increasing history improves EMA200 warmup but increases API load.

`MIN_VOLUME_USD`, `MAX_SPREAD_BPS`, `MIN_ATR_PCT`, `MAX_ATR_PCT` control quality. One basis point is 0.01%. Volume turnover is an estimate, not a precise quote-volume aggregate. Quotes are fetched during each scan and validated for finite values and a non-crossed spread; they are not synchronized with candle close. The public ticker has no separate book-age guarantee. Signals are suppressed if the scan extends into another candle bucket.

## Indicators and scoring

EMA50/200 use an initial SMA seed and alpha `2/(period+1)`. RSI14 and ATR14 use Wilder smoothing. A flat RSI series returns 50; an all-gain series 100; all-loss 0. MACD is EMA12 minus EMA26, with EMA9 signal and current/prior histogram. Volume average excludes the current candle and uses the preceding 20 candles. All calculations use completed candles only.

With `clip(x)=max(0,min(1,x))`, the component formulas are:

| Component | Maximum | Formula |
| --- | ---: | --- |
| Trend | 30 | 15 × clip(0.5 + (close−EMA200)/(4ATR)) + 15 × clip(0.5 + (EMA50−EMA200)/(4ATR)) |
| Momentum | 20 | 8 × clip(1−abs(RSI−band midpoint)/25) + 6 × clip(0.5+MACD/ATR) + 6 × clip(0.5+histogram/(0.2ATR)) |
| Volume | 15 | 15 × clip(volume ratio / 2) |
| BTC regime | 15 | BULLISH 15; NEUTRAL 9; BEARISH 3; BREAKDOWN 0 |
| Volatility | 10 | 10 × min(clip(ATR% / minimum), clip((maximum−ATR%)/(maximum/2))) |
| Liquidity | 10 | 5 × clip(1−spread/max spread) + 5 × clip(turnover/(2 × minimum turnover)) |

Scoring formulas are centralized in `strategy/scoring.py`; thresholds live in configuration. Components are recorded to four decimals and totalled without integer rounding. Defaults: score ≥75 raw BUY, 60–<75 WATCH, below 60 NO TRADE. Final classification applies quality gates: high raw scores may become WATCH or NO TRADE. A WATCH is always labeled WATCH.

BUY additionally requires close > EMA200, EMA50 > EMA200, RSI in the configured 52–68 band, MACD >0, histogram >0 and non-decreasing, volume ratio ≥1.2, non-breakdown BTC and risk approval. Failed trend/momentum/volume/confirmation gates demote raw BUY to WATCH. Failed quality gates or BTC breakdown produce NO TRADE. Explainable scores and invalidation reasons are stored separately from final classification.

BTC state precedence:

1. BREAKDOWN: latest completed close-to-close return ≤ `BTC_BREAKDOWN_PCT` (default −3%), or BTC below EMA200 with return < `BTC_BEARISH_PCT` (−1%) and ATR% above the configured maximum.
2. BEARISH: below EMA200 with bearish EMA structure or negative histogram.
3. BULLISH: close > EMA50 > EMA200, positive MACD and nonnegative histogram.
4. NEUTRAL: remaining conditions.

BREAKDOWN blocks BUY and WATCH notifications for all markets, including BTC itself. With strong confirmation enabled, BEARISH prevents BUY (a qualifying raw score is demoted to WATCH).

## Risk plans

Suggested entry is the most recent completed close. Stop is the lower of `entry − STOP_ATR×ATR` and the lowest low of the last ten candles minus 0.25 ATR. Target is `entry + REWARD_RISK×(entry−stop)`, default 2R. Stop must be positive and within `MAX_STOP_PCT` of entry. ATR%, spread and turnover must meet configured limits. Plans are indicative, not guaranteed executable prices; displayed reward/risk is gross of trading costs.

## Telegram setup and duplicate protection

1. In Telegram, use **@BotFather**, send `/newbot`, and follow its instructions.
2. Put the token in `TELEGRAM_TOKEN` in your private `.env`.
3. Start a conversation with your bot, or add it to your target group and send a message. Obtain the appropriate chat ID via Telegram's Bot API `getUpdates` or a trusted chat-ID tool; save it as `TELEGRAM_CHAT_ID`. Do not share the token or paste it into public logs.
4. Run `python -m scanner scan --notify` to explicitly enable delivery.

With `--notify`, Telegram also receives `SCANNER STARTED` when the scanner begins and `SCANNER STOPPED` on a graceful exit (Ctrl+C, a completed single scan, or a failed single scan). These messages include the configured markets, timeframe, paper mode and UTC time; a startup message means the process has started, not that its first market scan has succeeded. Delivery failures are logged without stopping scanning and are not retried automatically. Closing the terminal forcibly, killing the process, a power outage or an unavailable network can prevent the shutdown message. Without `--notify`, no lifecycle messages are sent.

BUY alerts include score breakdown, entry/stop/target, gross reward/risk, indicators, BTC state, explanation and UTC time. Set `WATCH_ALERTS=true` to send WATCH alerts. NO TRADE is never sent. Default cooldown is 3600 seconds; another alert ordinarily needs a new candle, elapsed cooldown and at least five points of improvement relative to the last reserved alert. `WATCH_TO_BUY=true` permits an upgrade on a new candle before the cooldown or score-improvement threshold. This only applies when a prior WATCH alert was actually reserved.

SQLite stores per-symbol last notified class/score/candle/time. A delivery reservation is saved before contacting Telegram, preventing restart spam. Sending has no automatic retries: a timed-out request might already have delivered. Failed/ambiguous reservations remain visible in the `notifications.status` column and suppress the same candle. This favors avoiding duplicates over guaranteed delivery. The `signals` are stored as rows in the `scans` table with full JSON indicator/score payloads; there is no separate redundant signals table.

## Paper trading

Set `PAPER=true`, then run `python -m scanner scan` (or add `--notify`). Simulated positions are clearly confined to the `paper` table. BUY can create one position per symbol; entry uses the observed ask plus `SLIPPAGE_BPS`. Stop/target stay tied to the signal plan; gap entries outside those bounds are rejected. `RISK_PER_TRADE` budgets equity against stop distance plus estimated fees; `MAX_EXPOSURE`, `MAX_POSITIONS` and `DAILY_LOSS_LIMIT` constrain simulations. These are also reserved configuration inputs for future execution, but no real execution is implemented.

Completed candles beginning after entry time settle positions. A partial entry candle is skipped because its pre-entry high/low are ambiguous; this can miss an exit in that candle. Stops take priority if a bar touches both stop and target. A gap below stop fills at bar open, while targets conservatively fill at target. Fees apply on both sides and exit slippage reduces proceeds. On restart, older missing candles for existing positions are fetched before settlement. Gaps fail safely; they are not interpolated. Entries are limited to one per signal candle.

```bash
python -m scanner stats
```

Reports closed trade count, wins/losses/breakeven, win rate, average net return, profit factor when at least two closed trades and a loss exist, mean duration, realized P/L, realized equity and open count. Open positions are excluded from realized statistics. Equity is not marked to market. Daily loss uses realized P/L against initial equity, UTC day boundaries; it is not a full portfolio risk system. Configuration should remain consistent while positions are open. A fresh database starts a fresh paper account.

## Backtesting

```bash
python -m scanner backtest --symbol ETH-USD --start 2026-10-01T00:00:00Z --end 2026-10-03T00:00:00Z --assumed-spread-bps 10 --output reports/eth.json
```

Start/end must be past, timeframe-aligned UTC timestamps. Public Coinbase history is downloaded with warmup. Each signal uses only the asset prefix and aligned BTC prefix available at that candle close. Simulated entry uses the next candle's open plus slippage; the decision does not access that future open. Settlement starts on the entry candle and uses stop-first OHLC rules. Replay starts with 249 warmup candles before the requested start and includes no earlier positions. Backtests use a separate in-memory database and export every simulated trade to JSON; they do not notify Telegram or modify the live paper account.

Historical bid/ask is unavailable from candles, so `--assumed-spread-bps` is mandatory and explicitly recorded. Liquidity uses trailing OHLCV-derived USD turnover, not present-day ticker data. This approximation is especially weak for six-hour/day candles. Data gaps stop replay rather than fabricating candles. Open trades remain open at the end and are excluded from realized results. Backtest results are model-dependent estimates, not demonstrated future performance. Single-symbol backtests are supported; correlated portfolio replay and walk-forward parameter optimization are not implemented.

## Limits and risks

This is a runnable Phase 1 foundation, not a claim of independently audited production reliability or profitability. Public APIs can be unavailable, rate-limited or incomplete. Candles cannot establish intrabar order, queue position or precise slippage. This version uses public REST polling rather than WebSockets, approximate liquidity without order-book depth, SQLite single-process storage, and at-most-once notification reservations. CoinMarketCap context is optional in the requested architecture and is not implemented; market eligibility comes entirely from Coinbase. Public history can have survivorship bias. These thresholds have not been optimized or validated as a profitable strategy. Crypto markets can move sharply; research signals and simulations can lose money and do not constitute personalized investment advice.

API reference: [Coinbase candle schema, granularities and pagination limits](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles), [Coinbase ticker](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-ticker).
