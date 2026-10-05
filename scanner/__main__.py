import argparse
import json
import logging
import time
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
from scanner.config import Config
from scanner.database import Repository
from scanner.market_data.coinbase import Coinbase
from scanner.notifications.telegram import Telegram
from scanner.service import Scanner
from scanner.backtesting.engine import backtest
from scanner.paper_trading.engine import PaperEngine
from scanner.tracking import SignalTracker
from scanner.scheduling import next_scan_delay


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError('Timestamp must include timezone, e.g. 2026-09-01T00:00:00Z')
    return int(parsed.timestamp())


def notify_lifecycle(notifier, event, config, reason=''):
    try:
        notifier.lifecycle(event, config, reason)
    except RuntimeError as exc:
        logging.warning('Telegram %s notification: %s', event, exc)
    else:
        logging.info('Telegram %s notification sent', event)


def wait_for_next_scan(seconds):
    next_scan = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    logging.info('Waiting for next scan at %s UTC; Ctrl+C to stop', next_scan.strftime('%H:%M:%S'))
    remaining = seconds
    while remaining > 0:
        step = min(60, remaining)
        time.sleep(step)
        remaining -= step
        if remaining:
            logging.info('BOT RUNNING | next scan in %dm %ds', remaining // 60, remaining % 60)


def main():
    parser = argparse.ArgumentParser(description='Crypto scanner: signal only, never places orders')
    parser.add_argument('--env', default='.env')
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan')
    scan.add_argument('--once', action='store_true')
    scan.add_argument('--notify', action='store_true', help='Explicitly enable configured Telegram alerts')
    scan.add_argument('--no-paper', action='store_true')
    sub.add_parser('stats')
    bt = sub.add_parser('backtest')
    bt.add_argument('--symbol', default='ETH-USD')
    bt.add_argument('--start', type=timestamp, required=True)
    bt.add_argument('--end', type=timestamp, required=True)
    bt.add_argument('--assumed-spread-bps', type=float, required=True)
    bt.add_argument('--output', default='reports/backtest.json')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    config = Config.load(args.env)
    if args.command == 'backtest':
        if not 0 <= args.assumed_spread_bps < 10000 or args.end <= args.start or args.end > int(time.time()) or args.start % config.timeframe or args.end % config.timeframe:
            parser.error('Backtest requires past, aligned start/end and valid spread')
        provider = Coinbase()
        if args.symbol not in provider.products():
            parser.error('Symbol is not an active USD market')
        candles = provider.candles(args.symbol, args.start - config.history * config.timeframe, args.end, config.timeframe)
        btc = candles if args.symbol == 'BTC-USD' else provider.candles('BTC-USD', args.start - config.history * config.timeframe, args.end, config.timeframe)
        from scanner.market_data.coinbase import validate_history
        validate_history(candles, config.timeframe, args.end)
        validate_history(btc, config.timeframe, args.end)
        # Exactly 249 warm-up candles before requested start; no earlier trades.
        candles = [c for c in candles if c.time >= args.start - 249 * config.timeframe]
        btc = [c for c in btc if c.time >= args.start - 249 * config.timeframe]
        repo = Repository(':memory:')
        try:
            result = backtest(args.symbol, candles, btc, config, repo, args.assumed_spread_bps)
            result['trades'] = [dict(r) for r in repo.db.execute('SELECT * FROM paper')]
            result['symbol'] = args.symbol
            result['start'], result['end'] = args.start, args.end
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding='utf-8')
            print(json.dumps({k: v for k, v in result.items() if k != 'trades'}, indent=2))
        finally:
            repo.close()
        return
    repo = Repository(config.database)
    notifier = None
    scanner_started = False
    shutdown_reason = 'Unexpected application exit'
    try:
        if args.command == 'stats':
            result = PaperEngine(repo, config).stats()
            result['telegram_signal_tracking'] = SignalTracker(repo, None).stats(config.telegram_chat_id)
            print(json.dumps(result, indent=2))
            return
        if args.no_paper:
            config = replace(config, paper=False)
        notifier = Telegram(config.telegram_token, config.telegram_chat_id) if args.notify else None
        scanner = Scanner(config, Coinbase(), repo, notifier)
        scanner_started = True
        logging.info('SCANNER STARTED | signal only | timeframe=%dm | Telegram=%s | WATCH alerts=%s',
                     config.timeframe // 60, 'enabled' if notifier else 'disabled', config.watch_alerts)
        if notifier:
            notify_lifecycle(notifier, 'started', config)
        while True:
            try:
                signals = scanner.run_once()
                if args.once:
                    print(json.dumps(signals, indent=2, allow_nan=False))
                    shutdown_reason = 'Single scan completed'
                    break
            except Exception as exc:
                logging.error('Scan failed: %s', exc)
                repo.error(int(time.time()), '*', str(exc))
                if args.once:
                    shutdown_reason = 'Single scan failed; check local logs'
                    raise SystemExit(1) from None
            wait_for_next_scan(next_scan_delay(config, time.time(), scanner.last_end, scanner.retry_pending, scanner.refresh_retry_at))
    except KeyboardInterrupt:
        shutdown_reason = 'Stopped by user (Ctrl+C)'
        logging.info('Scanner stopped')
    finally:
        try:
            if notifier and scanner_started:
                notify_lifecycle(notifier, 'stopped', config, shutdown_reason)
        finally:
            repo.close()


if __name__ == '__main__':
    main()
