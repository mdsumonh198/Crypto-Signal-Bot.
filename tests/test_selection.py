import unittest
from unittest.mock import MagicMock, patch
from scanner.config import Config
from scanner.database import Repository
from scanner.market_data.selection import select_markets
from scanner.service import Scanner
from scanner.strategy.signal_engine import evaluate
from tests.test_integration import FixtureProvider, FixtureRanking


class RankedProvider(FixtureProvider):
    def products(self):
        return ['BTC-USD', 'AKT-USD', 'USDT-USD', 'NEWSTABLE-USD'] + [f'COIN{n:02d}-USD' for n in range(30)]


def ranking():
    result = FixtureRanking(['BTC-USD', 'USDT-USD', 'NEWSTABLE-USD', 'UNAVAILABLE-USD'] +
                            [f'COIN{n:02d}-USD' for n in range(30)] + ['AKT-USD'])
    result.rows[2]['stable'] = True
    return result


class SelectionTests(unittest.TestCase):
    def test_exact_twenty_by_cmc_rank_not_activity(self):
        provider = RankedProvider()
        with self.assertLogs('scanner.market_data.selection', level='INFO') as logs:
            selected = select_markets(ranking(), provider.products(), Config())
        self.assertEqual(selected, ['BTC-USD'] + [f'COIN{n:02d}-USD' for n in range(9)])
        self.assertTrue(any('Selected Top 10 symbols' in line for line in logs.output))
        self.assertTrue({'AKT-USD', 'USDT-USD', 'NEWSTABLE-USD', 'UNAVAILABLE-USD'}.isdisjoint(selected))

    def test_outside_universe_never_evaluated_or_notified_even_with_high_buy_score(self):
        for old_limit in (0, 64, 250):
            with self.subTest(top_markets=old_limit):
                provider = RankedProvider()
                repo = Repository(':memory:')
                notifier = MagicMock(chat_id='fixture')
                notifier.send.return_value = 42
                def qualified(*args):
                    value = evaluate(*args)
                    value['classification'], value['score'] = 'BUY', 99
                    return value
                try:
                    with patch('scanner.service.evaluate', side_effect=qualified) as engine:
                        signals = Scanner(Config(top_markets=old_limit, pairs='AKT-USD,USDT-USD'), provider, repo,
                                          notifier, market_caps=ranking()).run_once(400 * 900)
                    self.assertEqual(len(signals), 10)
                    self.assertEqual(engine.call_count, 10)
                    symbols = {call.args[0] for call in engine.call_args_list}
                    sent = {call.args[0]['symbol'] for call in notifier.send.call_args_list}
                    self.assertTrue({'AKT-USD', 'USDT-USD', 'NEWSTABLE-USD'}.isdisjoint(symbols | sent))
                finally:
                    repo.close()

    def test_refresh_changes_membership_when_rank_changes(self):
        provider = RankedProvider()
        source = ranking()
        first = select_markets(source, provider.products(), Config())
        source.rows[-1]['rank'] = 1
        source.rows[0]['rank'] = 1000
        second = select_markets(source, provider.products(), Config())
        self.assertNotIn('AKT-USD', first)
        self.assertIn('AKT-USD', second)  # Eligible only if its real rank enters the Top 20.
        self.assertNotIn('BTC-USD', second)

    def test_pagination_continues_until_twenty_exchange_available_assets(self):
        source = FixtureRanking([f'NO{n}-USD' for n in range(100)] + ['BTC-USD'] + [f'COIN{n:02d}-USD' for n in range(25)])
        with patch.object(source, 'page', wraps=source.page) as page:
            selected = select_markets(source, RankedProvider().products(), Config())
        self.assertEqual(len(selected), 10)
        self.assertEqual([call.kwargs['start'] for call in page.call_args_list], [1, 101])

    def test_selection_never_downloads_candles_or_ranks_by_turnover(self):
        provider = RankedProvider()
        with patch.object(provider, 'candles') as candles, patch.object(provider, 'liquidity') as liquidity:
            select_markets(ranking(), provider.products(), Config())
        candles.assert_not_called()
        liquidity.assert_not_called()

    def test_ranking_failure_blocks_new_signals(self):
        repo = Repository(':memory:')
        notifier = MagicMock()
        source = MagicMock()
        source.page.side_effect = RuntimeError('Ranking unavailable')
        scanner = Scanner(Config(), RankedProvider(), repo, notifier, market_caps=source)
        try:
            with self.assertRaises(RuntimeError):
                scanner.run_once(400 * 900)
            self.assertEqual(scanner.allowed, set())
            notifier.send.assert_not_called()
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0], 0)
        finally:
            repo.close()

    def test_ranking_failure_revokes_old_universe_and_backs_off(self):
        repo = Repository(':memory:')
        source = ranking()
        scanner = Scanner(Config(), RankedProvider(), repo, market_caps=source)
        try:
            scanner.run_once(360005)
            with patch.object(source, 'page', side_effect=RuntimeError('Ranking unavailable')) as fetch:
                with self.assertRaises(RuntimeError):
                    scanner.run_once(360905)
                self.assertEqual(scanner.allowed, set())
                self.assertEqual(scanner.run_once(360910), [])
                self.assertEqual(fetch.call_count, 1)
            self.assertEqual(repo.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0], 10)
        finally:
            repo.close()
