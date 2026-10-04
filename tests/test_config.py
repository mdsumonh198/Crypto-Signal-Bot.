import unittest
from scanner.config import Config
from scanner.database import Repository


class ConfigTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        self.assertEqual(Config().timeframe, 900)
        with self.assertRaises(ValueError):
            Config(timeframe=42)
        with self.assertRaises(ValueError):
            Config(buy_score=60)

    def test_schema(self):
        r = Repository(':memory:')
        self.assertEqual(r.db.execute('SELECT count(*) FROM paper').fetchone()[0], 0)
        r.close()
