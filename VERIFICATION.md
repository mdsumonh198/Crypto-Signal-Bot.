# Verification performed

Verified in the supplied Windows workspace on 2026-10-04 (Asia/Dhaka) using the bundled Python runtime. The default `python` executable was not available on PATH; normal deployment requires Python 3.11+ as described in README.

- Automated suite: configuration/schema, Coinbase response parsing, candle ordering/completion/gaps, EMA/RSI/MACD, score boundaries and partial points, BTC breakdown gate, ATR stop/target, disabled execution, duplicate state across restart, notification formatting/transport sanitization, paper stop/gap/cost handling, backtest prefix timing and next-open entry, service persistence.
- Real end-to-end command: `python -m scanner scan --once --no-paper`. Completed successfully using public Coinbase BTC-USD and ETH-USD candles and tickers. Both final classifications were WATCH despite raw scores above 75 because BUY confirmation gates failed. Stored two scans in SQLite; no Telegram messages and no simulated or real orders were created.
- Real historical replay: `python -m scanner backtest --symbol ETH-USD --start 2026-10-01T00:00:00Z --end 2026-10-03T00:00:00Z --assumed-spread-bps 10 --output reports/eth.json`. Completed 191 evaluations and three closed simulated trades, all losses. Realized net P/L was approximately −$211.71 on $10,000 initial simulated equity, with default 60-bps fees per side and 5-bps slippage. This small sample is verification of behavior, not evidence of expected strategy performance.
- Telegram HTTP is tested using an explicitly mocked test transport. Delivery to a real chat was not tested because no credentials or destination were provided.

The local replay report is intentionally ignored by Git (`reports/eth.json`), and live SQLite state is ignored (`data/scanner.sqlite`). No exchange account credentials are needed or used. Execution modules always raise and do not contain authenticated exchange order endpoints.

## Top-250 universe update

Default configuration and the local `.env` now use `TOP_MARKETS=250` and `SCAN_INTERVAL=60`. Bulk Coinbase `/products/stats` data ranks active USD pairs by estimated 24h turnover. Four workers fetch candles and fresh tickers under a shared request limiter; persistence and notifications stay on the main thread. The volume floor remains a signal-quality gate rather than reducing the selected universe.

All 29 automated tests passed, including an exact 250-pair selection fixture, exclusion of inactive markets, bulk statistics parsing and preservation of the low-volume BUY block. A real top-250 scan completed using an in-memory database with Telegram and paper mode disabled: 250 selected, 79 successfully evaluated (3 BUY, 43 WATCH, 33 NO TRADE), and 171 rejected for unavailable/insufficient/gapped history or other data errors. No Telegram alerts were sent. Selected universe size does not guarantee usable historical data for every pair. Detailed local output is in the ignored `universe-verification.log`.
