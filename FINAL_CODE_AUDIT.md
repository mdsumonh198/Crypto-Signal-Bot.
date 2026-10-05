# Final code audit — 5 October 2026

## Outcome

Reviewed the existing scanner, CMC universe selection, Coinbase adapter, scheduling,
strategy/indicators/scoring/confirmation, risk plan, notification reservations,
Telegram transport, TP/SL tracker, paper accounting, backtest and disabled execution
boundaries. This is an update to the existing project. Confirmation thresholds and
existing stored trades have not been reset or loosened. No live orders are supported.

## Fixes from this audit

1. **Quote age was unchecked.** Coinbase ticker requests now capture last-trade time,
   request start and response observation time. MAX_QUOTE_AGE defaults to 15 seconds.
   Stale last-trade snapshots, slow requests, invalid/missing timestamps and future or
   inconsistent clocks block new entries. Checks run before evaluation, after
   evaluation and immediately before Telegram delivery. A blocked delivery is marked
   explicitly; it cannot create a notified tracking entry.
2. **Price differences were difficult to diagnose.** Signal payloads and logs retain
   Coinbase spot bid/ask and timestamps. BUY/WATCH messages add bid/ask, quote-observed
   time and last-trade time. Entry remains the observed ask; the completed candle
   close is separate. An observed quote is not a guaranteed execution price.
3. **Tracking catch-up delayed fresh scans.** New-entry analysis now runs before old
   notified-trade catch-up. Tracking still runs afterward, even on scan failure or
   an unchanged candle. Redundant quotes collected before the processing queue were
   removed; quotes are fetched immediately before each market's evaluation.
4. **Invalid direct risk inputs.** Nonfinite, zero or negative entry prices now raise
   instead of producing invalid plans. Stop remains the existing confirmed ATR/swing
   stop; target is entry + 2 * (entry - stop) under default configuration. Net costs,
   max stop distance and all existing risk gates remain.
5. **Misleading lifecycle text.** A 15M start/stop message always describes the actual
   CMC-ranked Top 10 eligible Coinbase USD universe, even with legacy TOP_MARKETS=250.
6. **Credentials in the public template.** Telegram token/chat ID were cleared from
   .env.example. The private .env is excluded from Git. A token previously uploaded
   to GitHub must be rotated through BotFather; removing it here cannot revoke the
   previously exposed token or erase GitHub history. Source/template/docs checks now
   find no Telegram token patterns. Private credentials are not included in this report.
7. **Paper configuration.** The local private environment and public example now use
   PAPER=true, TOP_MARKETS=10, TIMEFRAME=900 and MAX_QUOTE_AGE=15. Existing private
   credentials and stored database/trade histories are preserved.

The earlier Top 10 update also fixed lifetime high-score notification lockout and
cross-page candle-boundary duplicate conflicts. Those regression tests remain.

## Universe and timing

Walk current CMC market-cap ranks in ascending order. Exclude stablecoin metadata,
known stablecoin symbols, configured exclusions, ambiguous duplicate symbols and
unavailable/inactive Coinbase USD products. Continue down the ranks until ten assets
qualify. An asset outside this refreshed universe cannot receive a new trade signal;
old open positions remain tracked even if they leave the universe.

Evaluate completed 15M candles after :00, :15, :30, :45 UTC, normally close +5 seconds.
Retry unpublished completed candles every 5 seconds, up to close +90 seconds. This
is publication-aware scheduling, not a guarantee of a BUY every quarter hour.
Mandatory confirmations, same-candle deduplication and the existing same-coin
notification cooldown still apply. Each completed cycle has a persisted Telegram
status reservation, reporting confirmed setups or no valid setup/data unavailability.

## Validation

**88 automated tests passed.** New regressions cover ticker timestamp parsing, stale
and delayed quotes, missing/future timestamps, expired quotes during evaluation and
before delivery, no stale paper entry or Telegram BUY, entry-first tracking ordering,
price/timestamp formatting, invalid risk inputs and accurate lifecycle wording.
Existing universe, schedule, completed-candle, mandatory confirmation, deduplication,
Telegram, TP/SL reply, win/loss, paper and backtest tests also pass. Telegram sends in
tests are mocked. All 50 Python source/test/helper files passed syntax parsing.

A read-only live check selected **10** CMC-ranked Coinbase markets in **16.69 seconds**:
BTC, ETH, BNB, XRP, SOL, HYPE, ZEC, DOGE, LINK and ADA. Eight passed quote freshness
and were evaluated; BNB and HYPE were blocked by the quote-age/request-delay guard.
The eight retained entries exactly matched the observed Coinbase asks. Zero BUYs
passed the unchanged confirmation system. This check used an in-memory database,
no notifier and no paper positions, so it sent no messages or orders.

## Practical limits

- Coinbase ticker `time` is **last trade time**, not an order-book update timestamp.
  The guard is deliberately conservative: an old last trade can block a new entry
  even when a currently quoted bid/ask is available. A dedicated timestamped book/
  WebSocket feed would be a separate integration, not something this code claims.
- The feed is fresh REST snapshots during evaluation, not continuous streaming.
  Network/API delays and Telegram delivery can still create differences between
  the observed ask and a later client fill. CMC supplies ranking, not entry prices.
- Stops/targets for already-notified trades remain their original stored levels.
  Updating the bot does not rewrite historical entries or reported outcomes.
- TP/SL replies are retrospective completed-candle tracking, not exchange orders.
  The partial candle containing a mid-candle entry is skipped to avoid using
  pre-entry highs/lows. A same-candle move can therefore be missed by this tracker.
  Both-level candles use conservative SL precedence. Gross tracked wins/losses
  exclude fees/slippage; paper accounting includes configured costs.
- A high score is indicator alignment, not win probability. Mandatory filters
  can prevent all BUYs. Tests do not establish profitability or guaranteed fills.
- The client's original BUY-time Coinbase quote was not supplied. The SL-fill
  screenshot alone cannot prove the historical entry-price mismatch's cause.
- Multiple externally launched scanner processes can duplicate work. Run the
  existing crypto-scanner service only; this local audit cannot confirm VPS state.

## Files changed in this audit

scanner/models.py; scanner/config.py; scanner/market_data/coinbase.py;
scanner/market_data/selection.py; scanner/strategy/signal_engine.py;
scanner/risk/engine.py; scanner/service.py; scanner/notifications/telegram.py;
scanner/tracking.py (comment only); tests/test_price_audit.py;
tests/test_top10_update.py; .env.example; private .env; README.md;
TOP10_UPDATE.md; FINAL_CODE_AUDIT.md.

## Deployment

Upload the updated source, tests and docs to GitHub, excluding .env, data/, reports/
and caches. Preserve the VPS private .env and database before pulling. Keep its
TOP_MARKETS=10, TIMEFRAME=900, PAPER=true and MAX_QUOTE_AGE=15. Run
`.venv/bin/python -m unittest discover -q`, then restart the existing crypto-scanner
service with its --notify argument. Inspect logs for Top 10 selection, Coinbase spot
quote timestamps and scan summaries. A VPS reboot is not required. The VPS has not
been modified or verified by this local update.
