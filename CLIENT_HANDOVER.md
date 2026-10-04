# Client handover status — 2026-10-05

Suitable for a Phase 1 signal-only pilot/demo, with the limitations below disclosed. This review does not certify zero bugs, continuous uptime or strategy profitability. A sustained production soak test has not been performed.

## Verified

- Standard-library Python application; run instructions in README.
- 33 automated tests pass for indicators, scoring, classification, risk gates, data validation, persistent deduplication, paper accounting, replay timing, lifecycle messages, a 250-pair selection fixture and stale-signal suppression.
- Previous real Coinbase scan selected 250 active USD markets: 79 evaluated and 171 rejected for inadequate or otherwise invalid data. A selected pair is not guaranteed to have enough contiguous completed history for this strategy.
- Real Telegram delivery is confirmed by the project owner, not independently re-tested by this audit. Automated transport checks use mocks and do not contact the owner's chat.
- Real execution remains disabled. Paper/backtest results are simulations; the small historical test had three losing trades and does not establish profitability.

## Issues fixed in this review

- Telegram delivery failures now have a separate summary count and cannot turn a successful market analysis into an all-markets-failed exception. Ambiguous delivery reservations remain intact to prevent duplicate sends.
- Live signal and simulated entry timestamps use the time of analysis instead of batch-start time. Freshness is checked again after historical paper-position catch-up.
- Existing simulated positions continue to be monitored after their symbol drops out of the top-250 universe; no new signals are issued for those extra symbols.

## Client setup and acceptance

Give the client the source, README, `.env.example`, this document and VERIFICATION.md. Exclude your `.env`, database, reports, logs and virtual environment. The previously screenshot-exposed bot token should be revoked and replaced; use the client's own bot/chat configuration for handover.

On the target machine, install Python 3.11+, copy `.env.example` to a private `.env`, set credentials and run the test suite. Perform a safe `scan --once --no-paper`, then verify startup/shutdown delivery and at least one complete market cycle with `--notify`. Before unattended production use, run a 24–48-hour pilot and inspect data coverage, scan duration, error counts, alerts and restart behavior. This pilot is an acceptance recommendation and has not already been performed.

For continuous hosting use one scanner process per database under a supervisor with restart and persistent disk/backups. The application uses REST polling, one-process SQLite storage and notification reservations that favor avoiding duplicates over guaranteed delivery. A forced kill, power/network outage or abrupt shutdown can prevent a shutdown notification. API data gaps block affected signals. No promised signal frequency or win rate is part of this handover.
