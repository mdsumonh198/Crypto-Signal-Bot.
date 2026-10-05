import tempfile
import unittest
from pathlib import Path
from apply_top20_profile import update


class ProfileTests(unittest.TestCase):
    def test_update_is_idempotent_and_preserves_credentials_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('TOP_MARKETS=250\nTELEGRAM_TOKEN=fixture-secret\nDATABASE=data/live.sqlite\nPAPER=true\n', encoding='utf-8')
            update(path)
            first = path.read_text(encoding='utf-8')
            update(path)
            self.assertEqual(first, path.read_text(encoding='utf-8'))
            self.assertIn('TOP_MARKETS=10', first)
            self.assertIn('TELEGRAM_TOKEN=fixture-secret', first)
            self.assertIn('DATABASE=data/live.sqlite', first)
            self.assertIn('PAPER=true', first)
