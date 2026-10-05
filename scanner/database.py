import json
import sqlite3
from pathlib import Path


class Repository:
    def __init__(self, path):
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY, time INTEGER, symbol TEXT, candle_time INTEGER, classification TEXT, score REAL, payload TEXT);
            CREATE TABLE IF NOT EXISTS notifications (symbol TEXT PRIMARY KEY, time INTEGER, candle_time INTEGER, classification TEXT, score REAL, status TEXT);
            CREATE TABLE IF NOT EXISTS errors (id INTEGER PRIMARY KEY, time INTEGER, symbol TEXT, message TEXT);
            CREATE TABLE IF NOT EXISTS cycle_notifications (chat_id TEXT, candle_close INTEGER,
                status TEXT, PRIMARY KEY(chat_id, candle_close));
            CREATE TABLE IF NOT EXISTS paper (id INTEGER PRIMARY KEY, symbol TEXT, entry_time INTEGER, entry REAL, stop REAL, target REAL, quantity REAL, score REAL, exit_time INTEGER, exit REAL, pnl REAL, return_pct REAL, reason TEXT);
            CREATE TABLE IF NOT EXISTS signal_tracking (
                id INTEGER PRIMARY KEY, symbol TEXT, chat_id TEXT, message_id INTEGER,
                timeframe INTEGER, started_at INTEGER, entry REAL, stop REAL, target REAL,
                checked_until INTEGER, outcome TEXT, hit_time INTEGER, hit_price REAL,
                reply_status TEXT DEFAULT 'pending', UNIQUE(chat_id, message_id));
        ''')

    def save_scan(self, s):
        with self.db:
            self.db.execute('INSERT INTO scans(time,symbol,candle_time,classification,score,payload) VALUES(?,?,?,?,?,?)',
                            (s['time'], s['symbol'], s['candle_time'], s['classification'], s['score'], json.dumps(s, allow_nan=False)))

    def error(self, now, symbol, message):
        with self.db:
            self.db.execute('INSERT INTO errors(time,symbol,message) VALUES(?,?,?)', (now, symbol, message))

    def claim(self, s, config):
        with self.db:
            row = self.db.execute('SELECT * FROM notifications WHERE symbol=?', (s['symbol'],)).fetchone()
            if row:
                if s['candle_time'] <= row['candle_time']:
                    return False
                upgrade = config.watch_to_buy and row['classification'] == 'WATCH' and s['classification'] == 'BUY'
                if not upgrade and s['time'] - row['time'] < config.cooldown:
                    return False
            self.db.execute('INSERT OR REPLACE INTO notifications VALUES(?,?,?,?,?,?)',
                            (s['symbol'], s['time'], s['candle_time'], s['classification'], s['score'], 'reserved'))
        return True

    def claim_cycle(self, chat_id, candle_close):
        with self.db:
            cursor = self.db.execute('INSERT OR IGNORE INTO cycle_notifications VALUES(?,?,?)',
                                     (str(chat_id), candle_close, 'reserved'))
        return cursor.rowcount == 1

    def delivered_cycle(self, chat_id, candle_close, status):
        with self.db:
            self.db.execute('UPDATE cycle_notifications SET status=? WHERE chat_id=? AND candle_close=?',
                            (status, str(chat_id), candle_close))

    def delivered(self, symbol, status):
        with self.db:
            self.db.execute('UPDATE notifications SET status=? WHERE symbol=?', (status, symbol))

    def close(self):
        self.db.close()
