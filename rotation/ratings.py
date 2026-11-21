"""Season on/off ratings per player, per 100 possessions.

Each stint stores the box counts both teams produced while that five was on
court (FGA, FTA, OREB, TOV). Possessions are estimated from them per stint and
summed, so a player's on-court ORtg is points scored per 100 of his team's
possessions while he played, and DRtg points allowed per 100 of the
opponent's. "Off" is the team's season total minus the on-court part.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

from .analyze import BOX_KEYS, possessions

PER = 100
GAME_SEC = 2400


def _blank():
    return {'sec': 0, 'for': 0, 'against': 0, 'off': dict.fromkeys(BOX_KEYS, 0), 'def': dict.fromkeys(BOX_KEYS, 0)}


def _add(acc: dict, st: dict):
    acc['sec'] += st['end'] - st['start']
    acc['for'] += st['for']
    acc['against'] += st['against']
    for side in ('off', 'def'):
        for k in BOX_KEYS:
            acc[side][k] += st[side][k]


def _minus(a: dict, b: dict) -> dict:
    return {'sec': a['sec'] - b['sec'], 'for': a['for'] - b['for'], 'against': a['against'] - b['against'],
            **{side: {k: a[side][k] - b[side][k] for k in BOX_KEYS} for side in ('off', 'def')}}


def _rates(acc: dict) -> dict:
    op, dp = possessions(acc['off']), possessions(acc['def'])
    ortg = PER * acc['for'] / op if op > 0 else None
    drtg = PER * acc['against'] / dp if dp > 0 else None
    return {
        'min': round(acc['sec'] / 60, 1),
        'poss': round(op, 1),
        'pace': round((op + dp) / 2 / acc['sec'] * GAME_SEC, 1) if acc['sec'] else None,
        'ortg': ortg, 'drtg': drtg,
        'net': ortg - drtg if ortg is not None and drtg is not None else None,
    }


def collect(games: list[dict]) -> tuple[dict, dict, dict]:
    """Returns season accumulators per team, per (team, jersey, name), and games played."""
    teams, players, played = defaultdict(_blank), defaultdict(_blank), defaultdict(int)
    for game in games:
        if not game.get('final', True) or game.get('truncated'):
            continue
        for team in game['teams']:
            seen = set()
            for st in team['stints']:
                if 'off' not in st:
                    raise ValueError(f"gameId {game.get('gameId')} のステイントにボックス集計がない（再取得が必要）")
                _add(teams[team['name']], st)
                for p in st['lineup']:
                    key = (team['name'], p['jersey'], p['name'])
                    _add(players[key], st)
                    seen.add(key)
            for key in seen:
                played[key] += 1
    return teams, players, played


def _r(x):
    return round(x, 1) if x is not None else None


def player_ratings(games: list[dict], min_minutes: float = 0) -> list[dict]:
    teams, players, played = collect(games)
    rows = []
    for key, on in players.items():
        team, jersey, name = key
        off = _minus(teams[team], on)
        a, b = _rates(on), _rates(off)
        if a['min'] < min_minutes:
            continue
        diff = lambda k: _r(a[k] - b[k]) if a[k] is not None and b[k] is not None else None
        rows.append({
            'team': team, 'jersey': jersey, 'name': name, 'games': played[key],
            'onMin': a['min'], 'offMin': b['min'], 'onPoss': a['poss'], 'onPace': a['pace'],
            'onORtg': _r(a['ortg']), 'onDRtg': _r(a['drtg']), 'onNet': _r(a['net']),
            'offORtg': _r(b['ortg']), 'offDRtg': _r(b['drtg']), 'offNet': _r(b['net']),
            'diffORtg': diff('ortg'), 'diffDRtg': diff('drtg'), 'diffNet': diff('net'),
        })
    return sorted(rows, key=lambda r: (r['diffNet'] is None, -(r['diffNet'] or 0)))


def team_ratings(games: list[dict]) -> list[dict]:
    teams, _, _ = collect(games)
    rows = []
    for name, acc in teams.items():
        r = _rates(acc)
        rows.append({'team': name, 'min': r['min'], 'pace': r['pace'],
                     'ortg': _r(r['ortg']), 'drtg': _r(r['drtg']), 'net': _r(r['net'])})
    return sorted(rows, key=lambda r: -(r['net'] or 0))


def load_games(data_dir: Path) -> list[dict]:
    index = json.loads((data_dir / 'games.json').read_text(encoding='utf-8'))
    return [json.loads((data_dir / 'games' / f'{gid}.json').read_text(encoding='utf-8'))
            for gid, e in index['games'].items() if e['status'] == 'ok']


def write(rows: list[dict], path: Path):
    if path.suffix == '.csv':
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    else:
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
