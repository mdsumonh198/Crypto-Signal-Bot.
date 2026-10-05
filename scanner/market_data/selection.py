"""First twenty eligible assets in CMC market-cap rank order; no activity bias."""
import logging
from collections import Counter

log = logging.getLogger(__name__)
STABLE_BASES = frozenset(('USDT', 'USDC', 'DAI', 'PYUSD', 'USD1', 'USDE', 'USDS', 'EURC',
                         'TUSD', 'FDUSD', 'USDP', 'GUSD', 'RLUSD', 'USDD', 'FRAX', 'LUSD'))


def select_markets(ranking, available, config, limit=20):
    excluded = {s.strip().upper() for s in config.excluded_pairs.split(',') if s.strip()}
    available = set(available)
    rows = []
    selected = []
    for start in range(1, 10001, 100):
        page = ranking.page(start=start, limit=100)
        rows.extend(page)
        counts = Counter(row['symbol'] for row in rows)
        selected = []
        for row in sorted(rows, key=lambda row: row['rank']):
            symbol = row['symbol'] + '-USD'
            if (row['stable'] or row['symbol'] in STABLE_BASES or counts[row['symbol']] != 1
                    or symbol not in available or symbol in excluded):
                continue
            selected.append(symbol)
            if len(selected) == limit:
                break
        if len(selected) == limit or not getattr(ranking, 'has_more', len(page) == 100):
            break
    if len(selected) < limit:
        log.warning('Only %d/%d eligible CMC-ranked Coinbase USD assets available', len(selected), limit)
    log.info('Selected Top 20 symbols by CoinMarketCap market-cap rank (%d selected): %s', len(selected), ', '.join(selected))
    if not selected:
        raise ValueError('No eligible market-cap-ranked markets; new signals blocked')
    return selected
