class PaperEngine:
    def __init__(self, repository, config):
        self.repo, self.config = repository, config

    def equity(self):
        return self.config.paper_equity + self.repo.db.execute('SELECT COALESCE(SUM(pnl),0) FROM paper WHERE exit_time IS NOT NULL').fetchone()[0]

    def open(self, signal, entry_time=None, entry_price=None):
        if signal['classification'] != 'BUY' or not signal['risk']['approved']:
            return False
        c, db = self.config, self.repo.db
        when = signal['time'] if entry_time is None else entry_time
        active = db.execute('SELECT * FROM paper WHERE exit_time IS NULL').fetchall()
        if len(active) >= c.max_positions or any(r['symbol'] == signal['symbol'] for r in active):
            return False
        # One simulated entry per signal candle, including after a position closes.
        if db.execute('SELECT 1 FROM paper WHERE symbol=? AND entry_time>=?',
                      (signal['symbol'], signal['candle_time'] + c.timeframe)).fetchone():
            return False
        equity = self.equity()
        day = when // 86400 * 86400
        daily_pnl = db.execute('SELECT COALESCE(SUM(pnl),0) FROM paper WHERE exit_time>=? AND exit_time<?', (day, day + 86400)).fetchone()[0]
        if equity <= 0 or daily_pnl <= -c.daily_loss_limit * c.paper_equity:
            return False
        entry = (signal['risk']['entry'] if entry_price is None else entry_price) * (1 + c.slippage_bps / 10000)
        stop, target = signal['risk']['stop_loss'], signal['risk']['take_profit']
        if not 0 < stop < entry < target:
            return False
        fee = c.fee_bps / 10000
        available = min(equity, equity * c.max_exposure) - sum(r['entry'] * r['quantity'] * (1 + fee) for r in active)
        quantity = min(equity * c.risk_per_trade / (entry - stop + fee * (entry + stop)), available / (entry * (1 + fee)))
        if quantity <= 0:
            return False
        with db:
            db.execute('INSERT INTO paper(symbol,entry_time,entry,stop,target,quantity,score) VALUES(?,?,?,?,?,?,?)',
                       (signal['symbol'], when, entry, stop, target, quantity, signal['score']))
        return True

    def update(self, symbol, candles):
        db, c = self.repo.db, self.config
        for position in db.execute('SELECT * FROM paper WHERE symbol=? AND exit_time IS NULL', (symbol,)).fetchall():
            for candle in candles:
                if candle.time < position['entry_time']:
                    continue
                exit_price, reason = None, None
                if candle.open <= position['stop']:
                    exit_price, reason = candle.open, 'gap_stop'
                elif candle.low <= position['stop']:
                    exit_price, reason = position['stop'], 'stop'
                elif candle.open >= position['target'] or candle.high >= position['target']:
                    exit_price, reason = position['target'], 'target'
                if exit_price is not None:
                    exit_price *= 1 - c.slippage_bps / 10000
                    fee = c.fee_bps / 10000
                    pnl = position['quantity'] * (exit_price - position['entry'] - fee * (exit_price + position['entry']))
                    with db:
                        db.execute('UPDATE paper SET exit_time=?,exit=?,pnl=?,return_pct=?,reason=? WHERE id=?',
                                   (candle.time + c.timeframe, exit_price, pnl,
                                    pnl / (position['entry'] * position['quantity']) * 100, reason, position['id']))
                    break

    def stats(self):
        rows = self.repo.db.execute('SELECT * FROM paper WHERE exit_time IS NOT NULL').fetchall()
        wins = sum(r['pnl'] > 0 for r in rows)
        losses = sum(r['pnl'] < 0 for r in rows)
        gains = sum(max(r['pnl'], 0) for r in rows)
        lost = -sum(min(r['pnl'], 0) for r in rows)
        return dict(total_paper_trades=len(rows), open_positions=self.repo.db.execute('SELECT COUNT(*) FROM paper WHERE exit_time IS NULL').fetchone()[0],
                    wins=wins, losses=losses, breakeven=len(rows) - wins - losses,
                    win_rate=wins / len(rows) if rows else None,
                    average_return_pct=sum(r['return_pct'] for r in rows) / len(rows) if rows else None,
                    profit_factor=gains / lost if lost and len(rows) >= 2 else None,
                    average_duration_seconds=sum(r['exit_time'] - r['entry_time'] for r in rows) / len(rows) if rows else None,
                    realized_pnl=sum(r['pnl'] for r in rows), realized_equity=self.equity())
