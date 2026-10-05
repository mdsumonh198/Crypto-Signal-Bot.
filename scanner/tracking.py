"""Persisted TP/SL monitoring of notified BUY plans, independent of paper mode."""
import logging
from scanner.market_data.coinbase import validate_history

log = logging.getLogger(__name__)


class SignalTracker:
    def __init__(self, repository, provider, notifier=None):
        self.repo, self.provider, self.notifier = repository, provider, notifier

    def register(self, signal, message_id, chat_id, started_at):
        if signal['classification'] != 'BUY':
            return
        if type(message_id) is not int or message_id <= 0:
            raise ValueError('Missing Telegram message ID')
        tf, risk = signal['timeframe'], signal['risk']
        first_full = (started_at + tf - 1) // tf * tf
        with self.repo.db:
            self.repo.db.execute('''INSERT OR IGNORE INTO signal_tracking
                (symbol,chat_id,message_id,timeframe,started_at,entry,stop,target,checked_until)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (signal['symbol'], str(chat_id), message_id, tf, started_at,
                 risk['entry'], risk['stop_loss'], risk['take_profit'], first_full))
        log.info('Tracking BUY %s: message %d', signal['symbol'], message_id)

    def stats(self, chat_id):
        rows = self.repo.db.execute('SELECT outcome FROM signal_tracking WHERE chat_id=?', (str(chat_id),)).fetchall()
        wins = sum(r['outcome'] == 'TP' for r in rows)
        losses = sum(r['outcome'] == 'SL' for r in rows)
        closed = wins + losses
        return dict(total=len(rows), closed=closed, open=len(rows) - closed,
                    wins=wins, losses=losses, win_rate=wins / closed * 100 if closed else 0)

    def update(self, now):
        # Exits remain active even if BTC breaks down or a coin leaves the universe.
        rows = self.repo.db.execute('SELECT * FROM signal_tracking WHERE outcome IS NULL ORDER BY started_at').fetchall()
        for trade in rows:
            end = now // trade['timeframe'] * trade['timeframe']
            if end <= trade['checked_until']:
                continue
            try:
                candles = self.provider.candles(trade['symbol'], trade['checked_until'], end, trade['timeframe'])
                validate_history(candles, trade['timeframe'], end, 1)
                if candles[0].time != trade['checked_until']:
                    raise ValueError('Missing initial tracking interval')
                for candle in candles:
                    outcome, price = None, None
                    if candle.open <= trade['stop']:
                        outcome, price = 'SL', candle.open
                    elif candle.low <= trade['stop']:
                        outcome, price = 'SL', trade['stop']
                    elif candle.high >= trade['target']:
                        outcome, price = 'TP', trade['target']
                    if outcome:
                        with self.repo.db:
                            self.repo.db.execute('''UPDATE signal_tracking SET outcome=?,hit_time=?,hit_price=?,checked_until=?
                                WHERE id=? AND outcome IS NULL''',
                                (outcome, candle.time + trade['timeframe'], price, candle.time + trade['timeframe'], trade['id']))
                        log.info('%s %s HIT for message %s', trade['symbol'], outcome, trade['message_id'])
                        break
                else:
                    with self.repo.db:
                        self.repo.db.execute('UPDATE signal_tracking SET checked_until=? WHERE id=?', (end, trade['id']))
            except Exception as exc:
                self.repo.error(now, trade['symbol'], 'Signal tracking: ' + str(exc))
                log.error('Signal tracking %s: %s', trade['symbol'], exc)
        self.send_pending(now)

    def send_pending(self, now):
        if not self.notifier:
            return
        rows = self.repo.db.execute('''SELECT * FROM signal_tracking
            WHERE outcome IS NOT NULL AND reply_status='pending' AND chat_id=?''',
            (str(self.notifier.chat_id),)).fetchall()
        for trade in rows:
            with self.repo.db:
                cursor = self.repo.db.execute("UPDATE signal_tracking SET reply_status='reserved' WHERE id=? AND reply_status='pending'", (trade['id'],))
            if cursor.rowcount != 1:
                continue
            try:
                self.notifier.trade_update(trade, self.stats(trade['chat_id']))
                status = 'sent'
            except RuntimeError as exc:
                status = 'ambiguous_or_failed'
                self.repo.error(now, trade['symbol'], str(exc))
                log.error('TP/SL reply %s: %s', trade['symbol'], exc)
            with self.repo.db:
                self.repo.db.execute('UPDATE signal_tracking SET reply_status=? WHERE id=?', (status, trade['id']))
