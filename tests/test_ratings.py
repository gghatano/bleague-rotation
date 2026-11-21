import unittest

from rotation.ratings import player_ratings, team_ratings


def stint(start, end, pf, pa, lineup, off, deff):
    keys = ('fga', 'fta', 'oreb', 'tov')
    return {'start': start, 'end': end, 'for': pf, 'against': pa, 'margin': pf - pa,
            'lineup': [{'jersey': j, 'name': f'P{j}'} for j in lineup],
            'off': dict(zip(keys, off)), 'def': dict(zip(keys, deff))}


ON = ['1', '2', '3', '4', '5']
OFF = ['6', '2', '3', '4', '5']
GAME = {'gameId': '1', 'final': True, 'teams': [
    {'name': 'H', 'stints': [
        stint(0, 1200, 30, 20, ON, (20, 0, 0, 5), (22, 0, 2, 5)),    # H 25 poss / A 25 poss
        stint(1200, 2400, 20, 30, OFF, (18, 0, 3, 5), (20, 0, 0, 0)),  # H 20 poss / A 20 poss
    ]},
    {'name': 'A', 'stints': []},
]}


class RatingsTest(unittest.TestCase):
    def test_on_off_per_100(self):
        rows = {r['jersey']: r for r in player_ratings([GAME])}
        p1 = rows['1']
        self.assertEqual((p1['onORtg'], p1['onDRtg'], p1['onNet']), (120.0, 80.0, 40.0))
        self.assertEqual((p1['offORtg'], p1['offDRtg'], p1['offNet']), (100.0, 150.0, -50.0))
        self.assertEqual(p1['diffNet'], 90.0)
        self.assertIsNone(rows['2']['offORtg'])  # 全時間出場: off がない

    def test_team(self):
        (h,) = [r for r in team_ratings([GAME]) if r['team'] == 'H']
        self.assertEqual((h['ortg'], h['drtg']), (round(5000 / 45, 1), round(5000 / 45, 1)))

    def test_missing_box_counts_are_reported(self):
        legacy = {'gameId': '9', 'teams': [{'name': 'H', 'stints': [{'start': 0, 'end': 1, 'for': 0, 'against': 0, 'lineup': []}]}]}
        with self.assertRaisesRegex(ValueError, '再取得'):
            player_ratings([legacy])
