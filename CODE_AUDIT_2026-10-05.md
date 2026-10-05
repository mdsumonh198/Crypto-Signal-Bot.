# Crypto Signal Bot audit — 2026-10-05

Scope: local deployed-source candidate, code inspection, 67 existing automated tests, deterministic defect reproductions and one read-only public-data scan. No access to current VPS filesystem/database was used. No source, strategy settings, Telegram messages or trading state were changed during this audit.

## Findings

1. **High: valid repeat BUY notifications can be blocked indefinitely.** `scanner/database.py:41` requires both cooldown expiry and score improvement relative to the last reserved notification. With SCORE_IMPROVEMENT=5, a previous BUY score of 96 requires a new score of at least 101. Since scores cap at 100, subsequent qualifying signals for that symbol cannot pass, even the next day. Reproduced: initial 96 claim succeeds; next-day 99 and 100 claims fail. WATCH alerts are disabled, so the WATCH-to-BUY exception normally does not rescue this case. Recommended correction: retain same-candle deduplication and cooldown, but scope score improvement to a bounded repeat-alert policy rather than lifetime eligibility. Preserve mandatory confirmation gates.

2. **High: paginated candle ownership is not restricted to each request window.** `scanner/market_data/coinbase.py:68` filters each response against the overall request start/end, rather than that page's cursor/stop. Boundary rows returned by adjacent requests can enter twice and cause `Conflicting duplicate candle` when revised between responses. Reproduced with two mocked pages of a 300-bar request. This is a plausible contributor to the observed BCH/AVAX errors; current VPS raw API responses were not available to establish their exact cause. Do not ignore genuine conflicting duplicates. Recommended correction: enforce nonoverlapping page ownership and retain conflict detection within a page, with bounded refetch for transient data conflicts. Service currently marks generic data failures done for the bucket, so these errors can omit that asset's valid setup.

3. **Configuration: cost and breakout gates suppress current setups.** Local settings are FEE_BPS=60 (0.60% per side), SLIPPAGE_BPS=5 (0.05% per side), gross REWARD_RISK=2 and MIN_NET_REWARD_RISK=1.2. In the read-only live scan, all 20 selected assets failed the cost-adjusted risk/reward gate and all 20 failed the required prior-range breakout. Volume confirmation failed on 17 and MACD confirmation on 13. These are mandatory filters working as configured, not a Telegram transport failure. Cost assumptions must be compared with actual execution costs before changing them; do not disable filters just to create alerts.

4. **Latency risk:** `Scanner.run_once` calls sequential tracked-trade updates before starting universe refresh and entry analysis. Many pending tracked trades or slow requests can delay boundary analysis. Actual VPS open-trade counts and timings are needed to measure the impact. The scheduler's quarter-hour target alone does not guarantee that entry analysis starts within five seconds.

## Verification results

- Existing test suite: **67 passed**. These tests do not cover the lifetime score-lockout or paginated revision scenario above; passing the suite is not proof of defect absence.
- Live public CMC/Coinbase snapshot: **selected=20, evaluated=20, 23.9 seconds, BUY=0, WATCH=0, NO TRADE=20**.
- Universe restrictions and completed-candle checks are present; high scores cannot bypass confirmation rules.
- Notification delivery is gated by classification and repository claim. WATCH alerts are disabled. `Telegram errors=0` with no alerts does not demonstrate delivery attempts succeeded.
- TP/SL, win/loss, persistence and notification-format regressions passed using offline fixtures/mocks. No live Telegram send was performed.

## Conclusion

No BUY in the latest local snapshot is explained by unmet strategy filters. Nevertheless, two reproduced code defects can cause missed evaluations/notifications and should be corrected before calling the system fully reliable. The current VPS version, stored notification rows and recent logs must be compared before attributing the whole historical no-signal period to one cause.
