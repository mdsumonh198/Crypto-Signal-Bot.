"""Apply research settings without replacing Telegram credentials or live state."""
import argparse
import os
import re
import tempfile
from pathlib import Path

SETTINGS = {
    'TOP_MARKETS': '20', 'TIMEFRAME': '900', 'SCAN_INTERVAL': '60',
    'VOLUME_BUY_RATIO': '1.2', 'STRONG_CONFIRMATION': 'true',
    'BREAKOUT_LOOKBACK': '20', 'BREAKOUT_BUFFER_ATR': '0.05',
    'MIN_CLOSE_LOCATION': '0.7', 'MAX_UPPER_WICK': '0.25',
    'MAX_EXTENSION_ATR': '2.5', 'MAX_ENTRY_DRIFT_ATR': '0.5',
    'MIN_NET_REWARD_RISK': '1.2',
    'EXCLUDED_PAIRS': 'USDT-USD,USDC-USD,DAI-USD,PYUSD-USD,USD1-USD',
}


def update(path):
    path = Path(path)
    source = path.read_text(encoding='utf-8')
    for key, value in SETTINGS.items():
        source, count = re.subn(r'^' + key + r'\s*=.*$', key + '=' + value, source, flags=re.MULTILINE)
        if not count:
            source += '\n' + key + '=' + value + '\n'
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.env-update-', delete=False) as temporary:
            temporary.write(source)
            temporary.flush()
            os.fsync(temporary.fileno())
            temp_path = Path(temporary.name)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env', default='.env')
    args = parser.parse_args()
    update(args.env)
    print('Top-20 research profile applied. Credentials, paper mode and database setting preserved. Restart the scanner service to load it.')
