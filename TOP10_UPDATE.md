# Top 10 / Coinbase entry update

Latest audit: see [FINAL_CODE_AUDIT.md](FINAL_CODE_AUDIT.md). The current suite has
88 passing tests, quote-age guards, visible quote timestamps, entry-first tracking
ordering and paper-mode local configuration. Validation below records the earlier
Top 10 update snapshot.

The existing project now selects the first ten CMC market-cap-ranked, non-stablecoin assets that have active Coinbase USD pairs. Stablecoin metadata, configured exclusions and ambiguous ticker checks remain. Old 0/20/64/250 settings cannot enlarge the 15M signal universe. Existing open trade outcomes outside that universe are still monitored.

Completed 15M analysis targets :00:05, :15:05, :30:05, :45:05 UTC. Publication retries and rolling history remain. API delays can defer or prevent analysis; no synthetic candles or forced BUY signals are generated. Trade tracking checks remain at the configured heartbeat cadence; this is not tick-by-tick execution.

Each completed analysis cycle has one persistent Telegram status reservation per chat and candle close. Valid BUY messages retain their format, with added confirmed-close and Coinbase entry-source information. A cycle with no valid entry reports **No valid setup**. Data failures are explicitly reported when the scanner can reach Telegram. Network outages cannot guarantee message delivery. Restarting within a bucket does not resend the cycle status. Existing same-coin BUY cooldown remains in force.

Entry now uses a refreshed Coinbase ask immediately before evaluation; the last completed candle close is reported separately. Stop retains the confirmed candle's ATR/swing structure. Target, stop-distance limits and fee/slippage-adjusted reward/risk are recomputed against that entry. Existing price-drift, wick, EMA, RSI, MACD, volume, breakout, BTC and market-quality gates are preserved. Quotes are indicative and do not guarantee fills. CMC supplies ranking only; Coinbase supplies candles and executable-side quotes.

## Audit fixes

- Coinbase candle pages now own separate half-open windows, eliminating cross-page boundary conflicts while retaining genuine same-page conflicting-duplicate detection.
- A previous high score no longer blocks repeat BUYs forever. Same-candle deduplication, cooldown and WATCH-to-BUY behavior remain. The legacy SCORE_IMPROVEMENT setting is retained for configuration compatibility but no longer controls lifetime repeat notification eligibility.

TP/SL outcome replies, wins/losses and paper execution accounting remain. Exit messages are the existing TP/SL replies to the original BUY; no independent short-entry strategy or indicator-based early exit has been added.

## Validation

76 automated tests pass, including Top 10 restrictions, stablecoin/nonmember exclusion, completed candles, quarter-hour timing, quote-based entry/target and persisted tracking entry, stale-price rejection, duplicate pagination, high-score repeat eligibility, persisted cycle-status deduplication, ambiguous-send reservations and the existing Telegram/TP/SL/win-loss/paper/backtest tests. Confirmation thresholds were not loosened. Tests mock Telegram; no real Telegram test messages are sent.

A read-only live CMC/Coinbase check selected and evaluated exactly 10 assets in 17.5 seconds. No BUY passed the unchanged confirmations in that snapshot. The check used an in-memory database, disabled paper trading and no notifier.

## Deploy

Upload this project's updated source/tests to GitHub. Do not upload private `.env`, databases, logs, test reports or ZIPs. On the VPS preserve `.env` and `data/`, pull the updated source, run tests with the virtual environment, then restart `crypto-scanner` with its existing `--notify` command. Keep `TIMEFRAME=900`; set `TOP_MARKETS=10` in the VPS `.env` so lifecycle wording matches actual selection. No CMC key is required for keyless ranking, but its rate limits can require an optional private key.

The new cycle-status SQLite table is created automatically; no data reset is needed. Existing notified trades retain their stored entry/TP/SL. Only new signals use refreshed ask entry. The running VPS has not been changed by the local update.
