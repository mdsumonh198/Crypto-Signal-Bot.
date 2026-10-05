"""Quarter-hour candle evaluation; frequent wakes still service trade tracking."""
def next_scan_delay(config, now, last_end, retry_pending=False, refresh_retry_at=0):
    if config.timeframe != 900:
        return config.scan_interval
    end = int(now) // 900 * 900
    due = end + config.candle_publish_delay
    if refresh_retry_at > now:
        return min(config.scan_interval, refresh_retry_at - now)
    if now < due and last_end != end:
        return due - now
    if last_end != end:
        return min(config.candle_retry_interval, end + 900 + config.candle_publish_delay - now)
    # Keep the original trade-monitor cadence, without drifting past a close.
    return min(config.scan_interval, end + 900 + config.candle_publish_delay - now)
