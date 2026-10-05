# CMC market-cap Top 20 and candle scheduling update

The existing project is modified. Confirmation, Telegram formatting/transport, TP/SL reply tracking, win/loss statistics and the paper engine are preserved.

## Files changed

Production: `scanner/market_data/market_cap.py` (new), `scanner/market_data/selection.py`, `scanner/market_data/coinbase.py`, `scanner/service.py`, `scanner/scheduling.py` (new), `scanner/__main__.py`, `scanner/config.py`.

Settings/documentation: `.env`, `.env.example`, `README.md`, `STRATEGY_UPDATE.md`, this file. Private `.env` is excluded from the ZIP.

Tests: `test_selection.py`, new `test_market_cap.py`, new `test_scheduling.py`, and offline fixture updates in `test_integration.py`, `test_confirmation.py`, `test_universe.py`, `test_tracking.py`, `test_lifecycle.py`.

## Exact selection

Fetch CMC `/v3/cryptocurrency/listings/latest` with `sort=market_cap`, `sort_dir=desc`, `convert=USD`, paging 100 listings at a time. Walk ascending `cmc_rank`, using CMC's own methodology rather than exchange turnover or momentum.

Exclude CMC-tagged stablecoins, known stablecoin tickers, configured `EXCLUDED_PAIRS`, tickers without an active Coinbase USD pair, and duplicate tickers observed in fetched pages. Continue down the ranking until 20 distinct eligible assets are selected. Lookup stops when listings run out or at the safety ceiling of 10,000 listings.

This is the Top 20 **eligible tradable non-stablecoin assets** by global CMC rank. Global rank numbers may exceed 20 because stablecoins and unavailable assets are skipped. Failing a signal's liquidity/confirmation checks does not admit a lower-ranked replacement. AKT is blocked while outside this universe; it can qualify only if its real market-cap rank enters it.

For 15m, old `TOP_MARKETS=0/64/250` and manual `PAIRS` cannot override the universe. Every completed-candle cycle refreshes membership and logs `Selected Top 20 symbols by CoinMarketCap market-cap rank` with all selected symbols. New signal identity must match an allowed requested pair. Existing outcome replies for previously tracked coins outside the list continue.

## Exact timing

Default analysis start targets: **:00:05, :15:05, :30:05, :45:05 UTC**. `CANDLE_PUBLISH_DELAY=5` allows publication time. Startup midway through a candle promptly evaluates the latest completed bucket. Network/data retrieval adds to this target; alerts are not guaranteed five seconds after close.

Only candles with `open_time + 900 <= requested_close` are accepted. Validated history must end at `requested_close - 900`, with no gaps. The live bucket is discarded by Coinbase parsing and rejected by service validation.

Missing publication retries only pending assets every five seconds (`CANDLE_RETRY_INTERVAL=5`) through close + 90 seconds (`CANDLE_RETRY_WINDOW=90`). Already evaluated assets are skipped on retries. Missing data after that window is skipped for the bucket. BTC must be ready for safety analysis. No synthetic candles are created.

`SCAN_INTERVAL=60` remains the trade-tracking/heartbeat cadence; waits shorten to reach the quarter-hour deadline. Ranking failures back off for 60 seconds, blocking new signals. Scans crossing into a newer candle bucket suppress stale entries. The unchanged 300-bar warmup is reused in a rolling completed-history cache; subsequent scans download only newly completed buckets. New universe entrants receive full history. Other supported timeframes retain interval scheduling.

## Preserved behavior

EMA, RSI, MACD, volume, BTC regime, breakout, rejection wick, extension/chasing, stale entry, spread/liquidity and fees/slippage-adjusted risk/reward remain unchanged. A high score cannot bypass them. No new SELL strategy or real execution is introduced.

Telegram signal text, TP/SL parent replies, persisted tracking, notification reservations and total/open/closed/win/loss statistics are unchanged. Preserve the VPS database on deployment.

## Validation

**All 67 automated tests passed.** A subsequent live CMC/Coinbase scan selected and evaluated exactly **20 assets in 24.5 seconds**, with no pending publication retries. Byte hashes confirm the confirmation module, signal engine, Telegram module, TP/SL tracker and paper engine are unchanged.

Tests cover exact 20 membership; AKT/stablecoin exclusion even with mocked 99-point BUY signals; old configuration bypass attempts; dynamic rank refresh; pagination; stablecoin metadata; invalid/stale ranking rejection; optional key headers and 429 retries; quarter-hour scheduling; publication grace/retry/deduplication/timeout; incremental history; and live-candle rejection. Existing confirmation, Telegram, TP/SL, win/loss, persistence, paper and backtest regressions also run.

Live CMC ranking selected BTC, ETH, BNB, XRP, SOL, HYPE, ZEC, DOGE, LINK, ADA, XLM, NEAR, BCH, UNI, LTC, SUI, AVAX, HBAR, SHIB and TAO in one snapshot. This is dynamic membership, not a hardcoded list. A live scan started near the next boundary evaluated 17 of 20 in 23.9 seconds and skipped three after the bucket changed, confirming stale-entry protection. Keyless CMC also returned HTTP 429 during validation. No Telegram sends or paper trades were made by these checks.

## API limitations

CMC is the ranking dependency; Coinbase still provides candles and quotes. Blank `CMC_API_KEY` uses the official keyless endpoint and its shared IP quota. An optional private key uses the keyed endpoint and dedicated quota. A snapshot older than three minutes, malformed response or unavailable source blocks new signals. There is no activity-ranking fallback. CMC controls ranking publication timing.

Exact uppercase ticker matching is used; observed duplicates are skipped and automatic aliases are not guessed. Coinbase must offer an active USD pair. No-trade candle intervals can be omitted, and candle publication latency has no guarantee; these data checks remain strict.

Sources: [CMC listings specification](https://coinmarketcap.com/api/documentation/pro-api-reference/cryptocurrency), [official keyless API and rate limits](https://pro.coinmarketcap.com/api/documentation/pro-api-reference/keyless-public-api/).

## VPS deployment

The VPS has not been modified. Stop its service, upload updated `scanner/` and `tests/`, and preserve private `.env` and `data/`. New settings have defaults, so existing confirmation parameters do not need resetting. Do not use the older research-profile helper to overwrite custom confirmations for this update.

From the VPS project folder:

```bash
sudo systemctl stop crypto-scanner
# Upload source and tests now, keeping .env and data intact.
.venv/bin/python -m unittest discover -q
sudo systemctl start crypto-scanner
sudo systemctl status crypto-scanner --no-pager -l
sudo journalctl -u crypto-scanner -n 60 --no-pager
```

Keep `TIMEFRAME=900`, `TOP_MARKETS=20`. Optional timing settings: `CANDLE_PUBLISH_DELAY=5`, `CANDLE_RETRY_INTERVAL=5`, `CANDLE_RETRY_WINDOW=90`. Add a private `CMC_API_KEY` to the VPS `.env` if persistent rate limits require it. Restart after settings changes. The existing Telegram startup message is preserved.
