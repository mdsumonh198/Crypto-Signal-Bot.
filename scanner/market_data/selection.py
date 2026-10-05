"""Cheap universe screening before full strategy analysis."""
import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from scanner.market_data.coinbase import validate_history

log = logging.getLogger(__name__)
MAJORS = frozenset(('BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'DOGE-USD', 'ZEC-USD', 'NEAR-USD', 'HYPE-USD'))
STABLE_BASES = frozenset(('USDT', 'USDC', 'DAI', 'PYUSD', 'USD1', 'USDE', 'USDS', 'EURC', 'TUSD', 'FDUSD', 'USDP', 'GUSD', 'RLUSD', 'USDD'))


def clip(value):
    return max(0.0, min(1.0, value))


def select_markets(provider, available, config, end, limit):
    excluded = {s.strip() for s in config.excluded_pairs.split(',') if s.strip()}
    turnovers = provider.turnovers() if hasattr(provider, 'turnovers') else {s: provider.liquidity(s).volume_usd for s in available}
    eligible = [s for s in set(available) if s.endswith('-USD') and s.split('-')[0] not in STABLE_BASES
                and s not in excluded and math.isfinite(turnovers.get(s, float('nan')))
                and turnovers[s] >= config.min_volume_usd]
    ranked = sorted(eligible, key=lambda s: (-turnovers[s], s))
    # Screen up to twice the limit plus qualifying majors; no full indicators here.
    candidates = list(dict.fromkeys(ranked[:limit * 2] + sorted(MAJORS.intersection(eligible))))
    log.info('Universe screening: %d eligible; checking %d candidates for spread and recent activity', len(eligible), len(candidates))
    def screen(symbol):
        quote = provider.liquidity(symbol)
        if (not math.isfinite(quote.spread_bps) or not math.isfinite(quote.volume_usd)
                or quote.spread_bps < 0 or quote.spread_bps > config.max_spread_bps
                or quote.volume_usd < config.min_volume_usd):
            raise ValueError('Liquidity/spread below selection quality threshold')
        candles = provider.candles(symbol, end - 3 * config.timeframe, end, config.timeframe)
        validate_history(candles, config.timeframe, end, 3)
        if candles[0].time != end - 3 * config.timeframe:
            raise ValueError('Incomplete recent selection history')
        change_pct = (candles[-1].close / candles[0].open - 1) * 100
        range_pct = sum((c.high - c.low) / c.close * 100 for c in candles) / len(candles)
        turnover = min(turnovers[symbol], quote.volume_usd)
        volume_strength = clip(math.log10(max(1, turnover / config.min_volume_usd)) / 3)
        liquidity_strength = clip(1 - quote.spread_bps / config.max_spread_bps)
        activity_strength = 0.7 * clip(0.5 + change_pct / (2 * config.max_atr_pct)) + 0.3 * clip(range_pct / config.max_atr_pct)
        # A small preference cannot bypass any eligibility or quality gate.
        rank_score = .5 * volume_strength + .25 * liquidity_strength + .25 * activity_strength + (.03 if symbol in MAJORS else 0)
        return symbol, rank_score
    results = []
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='universe') as pool:
        jobs = {pool.submit(screen, symbol): symbol for symbol in candidates}
        for job in as_completed(jobs):
            try:
                results.append(job.result())
            except Exception as exc:
                log.warning('Universe screening skipped %s: %s', jobs[job], exc)
    selected = [s for s, value in sorted(results, key=lambda item: (-item[1], item[0]))[:limit]]
    if len(selected) < limit:
        log.warning('Only %d/%d candidates meet current activity/liquidity data requirements', len(selected), limit)
    log.info('Selected Top %d active markets (%d selected): %s', limit, len(selected), ', '.join(selected))
    return selected
