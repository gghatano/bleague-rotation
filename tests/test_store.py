import tempfile
import unittest
from pathlib import Path

from rotation.notify import _find
from rotation.parse import ScheduledGame, Team
from rotation.store import Report, Store, game_key, process_date, process_game
from tests.test_analyze import AWAY, HOME, game, li

FILLER = [li('残り9分00秒', HOME, '#1 P1 ターンオーバー(1本)')] * 100
GOOD = game(FILLER)
BAD = game(FILLER + [li('残り7分00秒', HOME, '#9 P9 プレイヤーアウト'), li('残り7分00秒', HOME, '#6 P6 プレイヤーイン')])
FINISHED = ScheduledGame('900001', '19:05', Team(HOME, '1'), Team(AWAY, '2'), 2, 2, '試合終了')


class FakeFetcher:
    def __init__(self, pbp='', schedule=''):
        self.pbp = pbp
        self.schedule_src = schedule

    def play_by_play(self, game_id):
        return self.pbp

    def schedule(self, ymd):
        return self.schedule_src


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_inconsistent_game_is_held_back_and_reported(self):
        report = Report()
        entry = process_game(self.store, FakeFetcher(BAD), FINISHED, '20260924', report)
        self.assertEqual((entry['status'], entry['errorKind']), ('error', 'data'))
        self.assertFalse(self.store.game_path('900001').exists())
        self.assertEqual([p['key'] for p in report.problems], [game_key('900001')])
        self.assertIn('（gameId 900001）', report.problems[0]['title'])
        self.assertEqual(self.store.dates_to_retry(), ['20260924'])

    def test_recovered_game_is_published_and_marked_resolved(self):
        process_game(self.store, FakeFetcher(BAD), FINISHED, '20260924', Report())
        report = Report()
        entry = process_game(self.store, FakeFetcher(GOOD), FINISHED, '20260924', report)
        self.assertEqual(entry['status'], 'ok')
        self.assertTrue(self.store.game_path('900001').exists())
        self.assertEqual(report.problems, [])
        self.assertEqual([r['key'] for r in report.resolved], [game_key('900001')])

    def test_unreadable_play_by_play_is_a_structure_problem(self):
        report = Report()
        entry = process_game(self.store, FakeFetcher('<html>maintenance</html>'), FINISHED, '20260924', report)
        self.assertEqual(entry['errorKind'], 'structure')
        self.assertEqual(report.problems[0]['kind'], 'structure')

    def test_game_day_without_games_is_a_structure_problem(self):
        report = Report()
        entries = process_date(self.store, FakeFetcher(schedule='<div>20260924</div><table></table>'), '20260924', report)
        self.assertEqual(entries, [])
        self.assertEqual([p['key'] for p in report.problems], ['schedule 20260924'])


class NotifyTest(unittest.TestCase):
    def test_find_matches_whole_key_only(self):
        issues = [{'number': 1, 'title': 'データ不整合: 2026-09-24 A-B（gameId 5063800）'},
                  {'number': 2, 'title': 'データ不整合: 2026-09-24 A-B（gameId 506380）'}]
        self.assertEqual(_find(issues, 'gameId 506380')['number'], 2)
        self.assertIsNone(_find(issues, 'gameId 50638'))


if __name__ == '__main__':
    unittest.main()
