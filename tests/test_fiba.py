import json
import tempfile
import unittest
from pathlib import Path

from rotation import fiba
from rotation.analyze import analyze
from rotation.parse import StructureError
from rotation.store import Report, Store, process_fiba_game

URL = 'https://www.fiba.basketball/en/events/fiba-basketball-world-cup-2027-asian-qualifiers/games/900-LBN-JPN#playByPlay'
A, B = 93, 85  # organisation ids: A is home (Lebanon), B away (Japan)


def player(pid, n):
    return {'personId': pid, 'firstName': 'F', 'lastName': f'P{n}', 'uniformNumber': str(n)}


def box_player(pid, tp, pm, starter):
    return {'Id': f'P_{pid}', 'Stats': {'TP': tp, 'PM': pm, 'Starter': starter, 'HasPlayed': tp != '0:0'}}


def ev(order, clock, ac, org=None, pid=None, txt='', **extra):
    return {'act': '', 'Time': clock, 'ac': ac, 'txt': txt, 'oId': org, 'pId': pid, 'order': order, **extra}


def page(q1, box_a, box_b, home_score=2, away_score=0):
    """A game page whose only plays are q1; Q2-Q4 are empty."""
    payload = ''.join([
        '"game":{"gameId":900,"teamA":{"organisationId":93,"code":"LBN","shortName":"Lebanon"},'
        '"teamB":{"organisationId":85,"code":"JPN","shortName":"Japan"},'
        f'"teamAScore":{home_score},"teamBScore":{away_score},"isLive":false,"gameDateTimeUTC":"2026-11-26T19:00:00"}},',
        '"playByPlay":"Play by play",',  # the page's label strings use the same key
        '"playByPlay":' + json.dumps({'items': {'Q1': {'items': q1}, 'Q2': {'items': []}, 'Q3': {'items': []}, 'Q4': {'items': []}}}) + ',',
        '"playersTeamA":' + json.dumps([player(100 + n, n) for n in range(1, 7)]) + ',',
        '"playersTeamB":' + json.dumps([player(200 + n, n + 10) for n in range(1, 6)]) + ',',
        '"gameDetails":' + json.dumps({'c': [{'Id': 'T_93', 'Children': box_a}, {'Id': 'T_85', 'Children': box_b}]}),
    ])
    return f'<script>self.__next_f.push([1,{json.dumps(payload)}])</script>'


# A1 scores at Q1 5:00, then A5 is replaced by A6 at the same 5:00: the basket is the old five's.
Q1 = [
    ev(1, '5:00', 'P2', A, 101, '2pt layup made', made=True, pts=2),
    ev(2, '5:00', 'SUBST', A, 105, 'Sub-Out'),
    ev(3, '5:00', 'SUBST', A, 106, 'Sub-In'),
]
BOX_A = [box_player(100 + n, '40:0', 2, True) for n in range(1, 5)] + [
    box_player(105, '5:0', 2, True), box_player(106, '35:0', 0, False)]
BOX_B = [box_player(200 + n, '40:0', -2, True) for n in range(1, 6)]


class FakeFetcher:
    def __init__(self, src):
        self.src = src

    def fiba_game(self, url, game_id):
        return self.src


class FibaParseTest(unittest.TestCase):
    def test_reads_game_metadata_in_jst(self):
        g = fiba.parse_game(page(Q1, BOX_A, BOX_B), URL)
        self.assertEqual((g.game_id, g.home, g.away, g.date, g.tipoff), ('fiba-900', 'レバノン', '日本', '2026-11-27', '04:00'))
        self.assertEqual((g.home_score, g.away_score, g.num_periods, g.final), (2, 0, 4, True))

    def test_starters_come_from_box_score(self):
        g = fiba.parse_game(page(Q1, BOX_A, BOX_B), URL)
        ins = [e.desc for e in g.events if e.sec == 0]
        self.assertEqual(len(ins), 10)
        self.assertIn('#5 P5 プレイヤーイン', ins)

    def test_rejects_non_game_url(self):
        with self.assertRaises(ValueError):
            fiba.parse_url('https://www.fiba.basketball/en/events/fiba-basketball-world-cup-2027-asian-qualifiers')

    def test_rejects_page_without_payload(self):
        with self.assertRaises(StructureError):
            fiba.parse_game('<html></html>', URL)


class ExactOrderTest(unittest.TestCase):
    def setUp(self):
        self.game = fiba.parse_game(page(Q1, BOX_A, BOX_B), URL)

    def pm(self, **kw):
        r = analyze(self.game.events, 4, 'レバノン', '日本', **kw)
        return {p['name']: p['plusMinus'] for p in r['teams'][0]['players']}, r

    def test_same_second_basket_goes_to_the_lineup_before_the_substitution(self):
        pm, r = self.pm(exact_order=True)
        self.assertEqual((pm['P5'], pm['P6']), (2, 0))
        self.assertEqual(fiba.check_against_box_score(r, self.game.official), [])

    def test_clock_only_attribution_credits_the_new_lineup(self):
        pm, r = self.pm()
        self.assertEqual((pm['P5'], pm['P6']), (0, 2))
        self.assertTrue(fiba.check_against_box_score(r, self.game.official))


class ProcessFibaGameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_game_matching_box_score_is_published(self):
        report = Report()
        entry = process_fiba_game(self.store, FakeFetcher(page(Q1, BOX_A, BOX_B)), URL, report)
        self.assertEqual((entry['status'], entry['league'], entry['date']), ('ok', 'fiba', '2026-11-27'))
        self.assertTrue(self.store.game_path('fiba-900').exists())
        self.assertEqual(report.problems, [])

    def test_game_disagreeing_with_box_score_is_held_back(self):
        box_a = BOX_A[:5] + [box_player(106, '35:0', 1, False)]
        report = Report()
        entry = process_fiba_game(self.store, FakeFetcher(page(Q1, box_a, BOX_B)), URL, report)
        self.assertEqual((entry['status'], entry['errorKind']), ('error', 'data'))
        self.assertIn('#6 P6: +/- 0（公式 1）', entry['message'])
        self.assertFalse(self.store.game_path('fiba-900').exists())
        self.assertEqual(len(report.problems), 1)

    def test_fiba_games_are_not_retried_through_the_bleague_schedule(self):
        box_a = BOX_A[:5] + [box_player(106, '35:0', 1, False)]
        process_fiba_game(self.store, FakeFetcher(page(Q1, box_a, BOX_B)), URL, Report())
        self.assertEqual(self.store.dates_to_retry(), [])


if __name__ == '__main__':
    unittest.main()
