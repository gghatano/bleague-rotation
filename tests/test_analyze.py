import unittest

from rotation.analyze import DataError, UnsupportedGame, analyze
from rotation.parse import parse_play_by_play, parse_schedule


def li(clock, team, desc):
    return (f'<li><div class="ba-liveText__time">{clock}</div>'
            f'<span class="ba-liveText__name">{team}</span>'
            f'<div class="ba-liveText__desc">{desc}</div></li>')


def page(*periods):
    return ''.join(f'<span class="ba-accordion__title">第{i}クォーター</span><ul>{"".join(rows)}</ul>'
                   for i, rows in enumerate(periods, 1))


def starters(team, jerseys):
    return [li('残り10分00秒', team, f'#{j} P{j} プレイヤーイン') for j in jerseys]


HOME, AWAY = 'H', 'A'
H5, A5 = [1, 2, 3, 4, 5], [11, 12, 13, 14, 15]


def game(q1_extra=(), q2=(), q3=(), q4=()):
    return page(starters(HOME, H5) + starters(AWAY, A5) + list(q1_extra), list(q2), list(q3), list(q4))


def run(src):
    events, periods = parse_play_by_play(src)
    return analyze(events, periods, HOME, AWAY)


def team(result, name):
    return next(t for t in result['teams'] if t['name'] == name)


class AnalyzeTest(unittest.TestCase):
    def test_substitution_batch_passes_through_other_counts(self):
        swap = [
            li('残り5分00秒', HOME, '#1 P1 プレイヤーアウト'),
            li('残り5分00秒', HOME, '#2 P2 プレイヤーアウト'),
            li('残り5分00秒', HOME, '#6 P6 プレイヤーイン'),
            li('残り5分00秒', HOME, '#7 P7 プレイヤーイン'),
        ]
        home = team(run(game(swap)), HOME)
        p1 = next(p for p in home['players'] if p['jersey'] == '1')
        self.assertEqual(p1['intervals'], [[0, 300]])
        self.assertEqual(sum(p['totalSec'] for p in home['players']), 5 * 2400)

    def test_lineup_carries_over_quarter_break(self):
        q2 = [li('残り10分00秒', HOME, '#1 P1 プレイヤーアウト'), li('残り10分00秒', HOME, '#6 P6 プレイヤーイン')]
        home = team(run(game(q2=q2)), HOME)
        p2 = next(p for p in home['players'] if p['jersey'] == '2')
        self.assertEqual(p2['intervals'], [[0, 2400]])

    def test_duplicate_in_and_out_are_ignored_as_anomalies(self):
        dup = [
            li('残り3分33秒', HOME, '#9 P9 プレイヤーアウト'),
            li('残り3分33秒', HOME, '#1 P1 プレイヤーイン'),
        ]
        result = run(game(dup))
        self.assertEqual([a['kind'] for a in result['anomalies']], ['duplicate_out', 'duplicate_in'])
        p1 = next(p for p in team(result, HOME)['players'] if p['jersey'] == '1')
        self.assertEqual(p1['intervals'], [[0, 2400]])

    def test_unpaired_entry_is_rejected(self):
        bad = [li('残り7分00秒', HOME, '#9 P9 プレイヤーアウト'), li('残り7分00秒', HOME, '#6 P6 プレイヤーイン')]
        with self.assertRaisesRegex(DataError, r'H: Q1 残り7:00 時点でコート上が6人'):
            run(game(bad))

    def test_points_and_plus_minus(self):
        plays = [
            li('残り9分00秒', HOME, '#1 P1 3Pシュート○(3点) ジャンプショット'),
            li('残り8分00秒', AWAY, '#11 P11 2Pシュート インサイドペイント○(2点) レイアップ'),
            li('残り8分00秒', AWAY, '#11 P11 フリースロー× 1/2'),
            li('残り8分00秒', AWAY, '#11 P11 フリースロー○(3点) 2/2'),
            li('残り7分00秒', HOME, '#2 P2 2Pシュート インサイドペイント× レイアップ'),
        ]
        result = run(game(plays))
        self.assertEqual([t['score'] for t in result['teams']], [3, 3])
        self.assertTrue(all(p['plusMinus'] == 0 for p in team(result, HOME)['players']))

    def test_overtime_is_unsupported(self):
        src = game() + '<span class="ba-accordion__title">延長</span><ul></ul>'
        with self.assertRaises(UnsupportedGame):
            run(src)


class ScheduleTest(unittest.TestCase):
    def test_parse_row(self):
        src = ('<div>20260922, 20260923</div><table><tbody><tr>'
               '<td class="ba-table__data ba-table__data--date"><time class="ba-table__time" datetime="9/23 14:05">14:05</time></td>'
               '<td class="ba-table__data ba-table__data--team"><a href="https://x/teams/706/info"> <span class="ba-teamLogo ba-teamLogo--706"></span> <span>A東京</span> </a></td>'
               '<td class="ba-table__data ba-table__data--score"><div class="ba-table__score">'
               '<a href="https://x/premier/game/506389/boxscore"> <span class="ba-table__scoreDetail"> 74 &nbsp;-&nbsp; <span class="ba-table__win">85</span> </span>\n'
               '<p class="ba-table__status">試合終了</p> </a></div></td>'
               '<td class="ba-table__data ba-table__data--team"><a href="https://x/teams/701/info"> <span class="ba-teamLogo ba-teamLogo--701"></span> <span>琉球</span> </a></td>'
               '</tr></tbody></table>')
        games, dates = parse_schedule(src)
        self.assertEqual(dates, ['20260922', '20260923'])
        g = games[0]
        self.assertEqual((g.game_id, g.tipoff, g.home.name, g.home.team_id, g.away.name), ('506389', '14:05', 'A東京', '706', '琉球'))
        self.assertEqual((g.home_score, g.away_score, g.status), (74, 85, '試合終了'))


if __name__ == '__main__':
    unittest.main()
