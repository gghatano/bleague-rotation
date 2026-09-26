import re
from collections import defaultdict
from itertools import groupby

from .parse import REGULAR_PERIOD_SEC, Event, StructureError

SUB_RE = re.compile(r'#(\d+)\s+(.+?)\s+プレイヤー(イン|アウト)$')
SHOT_RE = re.compile(r'(2Pシュート|3Pシュート|フリースロー).*?(○|×)')
SHOT_POINTS = {'2Pシュート': 2, '3Pシュート': 3, 'フリースロー': 1}
SHOT_KIND = {'2Pシュート': '2P', '3Pシュート': '3P', 'フリースロー': 'FT'}
PLAYER_RE = re.compile(r'#(\d+)\s+(.+?)\s+(?:2Pシュート|3Pシュート|フリースロー)')


class DataError(Exception):
    def __init__(self, message: str, sec: int | None = None):
        super().__init__(message)
        self.sec = sec


class UnsupportedGame(Exception):
    pass


def clock_label(sec: int) -> str:
    period = min(sec // REGULAR_PERIOD_SEC, 3) + 1
    remain = period * REGULAR_PERIOD_SEC - sec
    return f'Q{period} 残り{remain // 60}:{remain % 60:02d}'


def points_of(desc: str) -> int:
    m = SHOT_RE.search(desc)
    return SHOT_POINTS[m.group(1)] if m and m.group(2) == '○' else 0


def reconstruct(events: list[Event], teams: list[str], game_end: int):
    """Replays substitutions into per-player on-court intervals.

    A duplicate IN for a player already on court, or an OUT for one already off,
    is recorded as an anomaly and ignored; the 5-on-court check runs only after a
    whole timestamp has been applied, since a batch of swaps passes through 3 or 7.
    """
    on_court = {t: {} for t in teams}
    intervals = {t: [] for t in teams}
    anomalies = []
    for sec, batch in groupby(events, key=lambda e: e.sec):
        for e in batch:
            m = SUB_RE.match(e.desc)
            if not m:
                continue
            key = (m.group(1), m.group(2))
            court = on_court[e.team]
            if m.group(3) == 'イン':
                if key in court:
                    anomalies.append({'sec': sec, 'team': e.team, 'jersey': key[0], 'name': key[1], 'kind': 'duplicate_in'})
                else:
                    court[key] = sec
            elif key in court:
                intervals[e.team].append((key, court.pop(key), sec))
            else:
                anomalies.append({'sec': sec, 'team': e.team, 'jersey': key[0], 'name': key[1], 'kind': 'duplicate_out'})
        for team, court in on_court.items():
            if len(court) != 5:
                names = '、'.join(f'#{j} {n}' for j, n in court)
                raise DataError(f'{team}: {clock_label(sec)} 時点でコート上が{len(court)}人（{names}）', sec)
    for team, court in on_court.items():
        for key, start in court.items():
            intervals[team].append((key, start, game_end))
    return intervals, anomalies


def _stints(team, opp, events, intervals, game_end):
    bounds = sorted({0, game_end} | {e.sec for e in events if e.team == team and SUB_RE.match(e.desc)})
    scoring = [(e.sec, e.team, p) for e in events if (p := points_of(e.desc))]
    stints = []
    for start, end in zip(bounds, bounds[1:]):
        lineup = [{'jersey': j, 'name': n} for (j, n), a, b in intervals if a <= start and end <= b]
        pf = sum(p for s, t, p in scoring if t == team and start <= s < end)
        pa = sum(p for s, t, p in scoring if t == opp and start <= s < end)
        stints.append({'start': start, 'end': end, 'for': pf, 'against': pa, 'margin': pf - pa, 'lineup': lineup})
    return stints


def _players(intervals, stints):
    spans = defaultdict(list)
    for key, start, end in intervals:
        spans[key].append([start, end])
    players = []
    for (jersey, name), ivs in sorted(spans.items(), key=lambda kv: min(s for s, _ in kv[1])):
        me = {'jersey': jersey, 'name': name}
        players.append({
            'jersey': jersey,
            'name': name,
            'totalSec': sum(e - s for s, e in ivs),
            'intervals': sorted(ivs),
            'plusMinus': sum(st['margin'] for st in stints if me in st['lineup']),
        })
    return players


def _lineups(stints):
    groups = {}
    for st in stints:
        key = frozenset(p['jersey'] for p in st['lineup'])
        g = groups.setdefault(key, {'lineup': st['lineup'], 'sec': 0, 'for': 0, 'against': 0, 'margin': 0, 'stints': 0})
        g['sec'] += st['end'] - st['start']
        g['for'] += st['for']
        g['against'] += st['against']
        g['margin'] += st['margin']
        g['stints'] += 1
    return sorted(groups.values(), key=lambda g: -g['sec'])


def analyze(events: list[Event], num_periods: int, home: str, away: str, final: bool = True) -> dict:
    """Rebuilds a game. With final=False the game is still in progress: it may
    have fewer than four periods, and every open stint ends at the latest play."""
    regular = 4
    if num_periods > regular or (final and num_periods != regular):
        raise UnsupportedGame(f'ピリオド数{num_periods}（延長戦）は未対応')
    game_end = regular * REGULAR_PERIOD_SEC if final else max(e.sec for e in events)
    teams = [home, away]
    if not any(SUB_RE.match(e.desc) for e in events):
        raise StructureError('交代（プレイヤーイン/アウト）の記録を1件も読めない')
    if not any(points_of(e.desc) for e in events):
        raise StructureError('得点の記録を1件も読めない')
    unknown = {e.team for e in events} - set(teams)
    if unknown:
        raise DataError(f'日程にないチーム名がテキストに出現: {sorted(unknown)}')
    truncated = None
    try:
        intervals, anomalies = reconstruct(events, teams, game_end)
    except DataError as e:
        # A live feed is often corrected within minutes; until then show the part before the break.
        if final or not e.sec:
            raise
        truncated = {'sec': e.sec, 'reason': str(e)}
        events = [ev for ev in events if ev.sec < e.sec]
        game_end = e.sec
        intervals, anomalies = reconstruct(events, teams, game_end)
    result = []
    for team, opp in ((home, away), (away, home)):
        stints = _stints(team, opp, events, intervals[team], game_end)
        result.append({
            'name': team,
            'score': sum(points_of(e.desc) for e in events if e.team == team),
            'players': _players(intervals[team], stints),
            'stints': stints,
            'lineups': _lineups(stints),
        })
    side = {home: 0, away: 1}
    scoring = []
    for e in events:
        if not (p := points_of(e.desc)):
            continue
        player = PLAYER_RE.match(e.desc)
        scoring.append([e.sec, side[e.team], p, player.group(1) if player else '', player.group(2) if player else '',
                        SHOT_KIND[SHOT_RE.search(e.desc).group(1)]])
    return {'periodLength': REGULAR_PERIOD_SEC, 'numPeriods': regular, 'final': final, 'elapsedSec': game_end,
            'truncated': truncated, 'teams': result, 'scoring': scoring, 'anomalies': anomalies}
