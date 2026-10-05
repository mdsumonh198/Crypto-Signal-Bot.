import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from scanner.strategy.scoring import MAXIMA


def format_signal(s):
    risk, i = s['risk'], s['indicators']
    label = '🟢 BUY SIGNAL' if s['classification'] == 'BUY' else '🟡 WATCH SIGNAL'
    lines = [label, '', f"🪙 Pair: {s['symbol']}", f"⏱ Timeframe: {s['timeframe'] // 60}M",
             f"📊 Score: {s['score']:.2f}/100", '', f"💵 Entry: ${risk['entry']:.8g}",
             f"🛑 Stop Loss: ${risk['stop_loss']:.8g}", f"🎯 Take Profit: ${risk['take_profit']:.8g}",
             f"⚖️ Risk/Reward: {risk['risk_reward']:.2f}", '']
    lines += [f"🕯 Confirmed candle close: ${risk.get('confirmed_close', i['price']):.8g}",
              '📍 Entry source: Coinbase ask observed during evaluation; fill price may differ.']
    quote = s.get('quote', {})
    if quote.get('observed_at') is not None:
        lines += [f"💱 Coinbase spot bid / ask: ${quote['bid']:.8g} / ${quote['ask']:.8g}",
                  '🕒 Quote observed at: ' + datetime.fromtimestamp(quote['observed_at'], timezone.utc).isoformat(),
                  '🕒 Price snapshot at: ' + datetime.fromtimestamp(quote.get('book_time', quote.get('last_trade_time')), timezone.utc).isoformat()]
    lines += [f'{k}: {v:.2f}/{MAXIMA[k]}' for k, v in s['components'].items()]
    lines += ['Score measures indicator alignment, not win probability.']
    lines += ['', f"RSI: {i['rsi']:.2f}", f"EMA50: {i['ema50']:.8g}", f"EMA200: {i['ema200']:.8g}",
              f"MACD: {i['macd']:.8g}", f"Volume Ratio: {i['volume_ratio']:.2f}",
              f"BTC Regime: {s['btc_regime']}", '', '📝 Reason: ' + s['reason'],
              '🕒 Time: ' + datetime.fromtimestamp(s['time'], timezone.utc).isoformat(),
              'ℹ️ Signal only. No order placed.']
    return '\n'.join(lines)


class Telegram:
    def __init__(self, token, chat_id):
        if not token or not chat_id:
            raise ValueError('TELEGRAM_TOKEN and TELEGRAM_CHAT_ID required')
        self.token, self.chat_id = token, chat_id

    def send(self, s):
        return self.send_text(format_signal(s))

    def cycle_summary(self, candle_close, selected, evaluated, buys, errors, reason=''):
        review = datetime.fromtimestamp(candle_close, timezone.utc)
        upcoming = datetime.fromtimestamp(candle_close + 900, timezone.utc)
        lines = ['📊 MARKET UPDATE', '🕒 Review: ' + review.strftime('%d %b, %H:%M UTC'), '',
                 '🪙 Monitoring the Top 10 eligible Coinbase coins.']
        if not evaluated:
            lines += ['', '⚠️ Market data could not be verified this round.',
                      '⏸ No new BUY recommendation is available.']
        elif buys:
            lines += ['', f'✅ {buys} BUY setup(s) passed our confirmation checks.']
        else:
            lines += ['', '⏳ No confirmed BUY opportunity among the coins reviewed.',
                      '🔎 Waiting for a setup that meets our entry requirements.']
        if evaluated and (errors or reason or evaluated < selected):
            lines += ['', '⚠️ Some coins were skipped because up-to-date market data could not be verified.']
        lines += ['', '⏰ Next scheduled review: ' + upcoming.strftime('%H:%M UTC')]
        return self.send_text('\n'.join(lines))

    def trade_update(self, trade, stats):
        label = '🎯 TP HIT — WIN' if trade['outcome'] == 'TP' else '🛑 SL HIT — LOSS'
        change = (trade['hit_price'] / trade['entry'] - 1) * 100
        text = '\n'.join([label, '', '📤 Action: SELL / EXIT — tracked long signal; no order placed.', f"🪙 Pair: {trade['symbol']}",
                          f"💵 Signal entry: ${trade['entry']:.8g}",
                          f"🛑 Stop Loss: ${trade['stop']:.8g}", f"🎯 Take Profit: ${trade['target']:.8g}",
                          f"📤 Tracked exit level: ${trade['hit_price']:.8g}",
                          f"📈 Indicative gross move: {change:+.2f}%", '',
                          f"📊 Total tracked signals: {stats['total']}",
                          f"📋 Closed: {stats['closed']} | Open: {stats['open']}",
                          f"🏁 Wins (TP): {stats['wins']} | Losses (SL): {stats['losses']}",
                          f"📊 Win rate (closed): {stats['win_rate']:.1f}%", '',
                          '🕒 Candle confirmed at: ' + datetime.fromtimestamp(trade['hit_time'], timezone.utc).isoformat(),
                          'Signal tracking only; assumes entry at the signal price. Gross move excludes fees/slippage. No actual trade executed or closed.'])
        return self.send_text(text, reply_to_message_id=trade['message_id'])

    def lifecycle(self, event, config, reason=''):
        if event not in ('started', 'stopped'):
            raise ValueError('Invalid lifecycle event')
        label = '🟢 SCANNER STARTED' if event == 'started' else '🔴 SCANNER STOPPED'
        markets = ('CMC-ranked Top 10 tradable Coinbase USD assets' if config.timeframe == 900 else
                   (f'Top {config.top_markets} CMC-ranked USD markets' if config.top_markets else config.pairs))
        lines = [label, f'🪙 Markets: {markets}', f'⏱ Timeframe: {config.timeframe // 60}M',
                 f'🔄 Scan interval: {config.scan_interval} seconds',
                 f'📝 Paper trading: {"enabled" if config.paper else "disabled"}',
                 'ℹ️ Signal only. Real execution disabled.']
        if reason:
            lines.append('📝 Reason: ' + reason)
        lines.append('🕒 Time: ' + datetime.now(timezone.utc).isoformat())
        self.send_text('\n'.join(lines))

    def send_text(self, text, reply_to_message_id=None):
        payload = {'chat_id': self.chat_id, 'text': text}
        if reply_to_message_id is not None:
            payload['reply_parameters'] = {'message_id': reply_to_message_id, 'allow_sending_without_reply': False}
        body = json.dumps(payload).encode()
        request = Request(f'https://api.telegram.org/bot{self.token}/sendMessage', data=body,
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=20) as response:
                result = json.load(response)
            if not result.get('ok'):
                raise ValueError('Telegram rejected message')
            message_id = result.get('result', {}).get('message_id')
            if type(message_id) is not int or message_id <= 0:
                raise ValueError('Telegram response missing valid message ID')
            return message_id
        except Exception:
            # Never log exception URLs containing the bot secret. No automatic retry
            # because a timed-out send may already have delivered the message.
            raise RuntimeError('Telegram delivery failed or is ambiguous; reservation retained') from None
