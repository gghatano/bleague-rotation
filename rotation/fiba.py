"""FIBA national-team games, read from a game page on www.fiba.basketball.

The page is a Next.js app whose server payload (self.__next_f.push chunks)
carries the FIBA LiveStats play-by-play, both rosters and the official box
score. The play-by-play is turned into the same Event list the B.LEAGUE
parser produces, so analyze() rebuilds it unchanged; the box score's minutes
and +/- per player then serve as an independent check of the rebuild.
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .parse import OVERTIME_SEC, REGULAR_PERIOD_SEC, REGULAR_PERIODS, Event, StructureError

URL_RE = re.compile(r'https://www\.fiba\.basketball/(?:[a-z]{2}/)?events/([a-z0-9-]+)/games/(\d+)-([A-Za-z0-9-]+)/?(?:[#?].*)?$')
SHOT_KIND = {'P2': '2Pシュート', 'P3': '3Pシュート', 'FT': 'フリースロー'}
JST = timezone(timedelta(hours=9))
# Japanese names for the teams Japan meets in Asian competitions; others keep FIBA's short name.
TEAM_JA = {
    'JPN': '日本', 'LBN': 'レバノン', 'CHN': '中国', 'KOR': '韓国', 'TPE': 'チャイニーズ・タイペイ', 'PHI': 'フィリピン',
    'AUS': 'オーストラリア', 'NZL': 'ニュージーランド', 'IRI': 'イラン', 'JOR': 'ヨルダン', 'KSA': 'サウジアラビア',
    'QAT': 'カタール', 'BRN': 'バーレーン', 'SYR': 'シリア', 'IRQ': 'イラク', 'KAZ': 'カザフスタン', 'GUM': 'グアム',
    'IND': 'インド', 'INA': 'インドネシア', 'THA': 'タイ', 'MGL': 'モンゴル', 'HKG': '香港', 'UAE': 'UAE',
}
COMPETITION_JA = {
    'fiba-basketball-world-cup-2027-asian-qualifiers': 'FIBAワールドカップ2027 アジア地区予選',
}


@dataclass(frozen=True)
class FibaGame:
    game_id: str
    url: str
    competition: str
    date: str
    tipoff: str
    home: str
    away: str
    home_score: int
    away_score: int
    final: bool
    events: list
    num_periods: int
    official: dict  # team -> {"#jersey name": (seconds played, plus-minus)}


def parse_url(url: str) -> tuple[str, str]:
    """Returns (event slug, FIBA game id) for a game page URL."""
    m = URL_RE.match(url.strip())
    if not m:
        raise ValueError(f'FIBAの試合ページのURLではない: {url}')
    return m.group(1), m.group(2)


def _payload(src: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', src, re.S)
    if not chunks:
        raise StructureError('FIBAの試合ページにサーバーデータ（__next_f）が見つからない')
    return ''.join(json.loads(f'"{c}"') for c in chunks)


def _value_after(payload: str, marker: str, start_with: str):
    """Decodes the JSON value that follows marker, at the first place it starts with start_with."""
    dec = json.JSONDecoder()
    for m in re.finditer(re.escape(marker), payload):
        at = m.end()
        if payload.startswith(start_with, at):
            return dec.raw_decode(payload, at)[0]
    raise StructureError(f'FIBAの試合ページに {marker}{start_with}… が見つからない')


def _period_length(label: str) -> int:
    if re.fullmatch(r'Q[1-4]', label):
        return REGULAR_PERIOD_SEC
    if re.fullmatch(r'OT\d+', label):
        return OVERTIME_SEC
    raise StructureError(f'FIBAのプレイバイプレイに未知のピリオド {label}')


def _clock(text: str) -> int:
    m = re.fullmatch(r'(\d+):(\d{1,2})', text)  # the box score writes 17:05 as "17:5"
    if not m:
        raise StructureError(f'FIBAのプレイバイプレイの時刻 {text} を読めない')
    return int(m.group(1)) * 60 + int(m.group(2))


def parse_game(src: str, url: str) -> FibaGame:
    slug, game_id = parse_url(url)
    payload = _payload(src)
    game = _value_after(payload, '"game":', '{"gameId":' + game_id)
    pbp = _value_after(payload, '"playByPlay":', '{"items"')['items']
    roster = {p['personId']: p for key in ('"playersTeamA":', '"playersTeamB":') for p in _value_after(payload, key, '[')}
    box = _value_after(payload, '"gameDetails":', '{"c"')['c']

    side = {game['teamA']['organisationId']: 'A', game['teamB']['organisationId']: 'B'}
    names = {s: TEAM_JA.get(game[f'team{s}']['code'], game[f'team{s}']['shortName']) for s in 'AB'}
    team_of = {org: names[s] for org, s in side.items()}

    def who(pid) -> str:
        if pid not in roster:
            raise StructureError(f'FIBAのロスターにない選手 personId {pid}')
        p = roster[pid]
        return f"#{p['uniformNumber']} {p['lastName']}"

    events, official = [], {}
    for team in box:
        org = int(team['Id'].removeprefix('T_'))
        if org not in team_of:
            raise StructureError(f'FIBAのボックススコアに未知のチーム {team["Id"]}')
        official[team_of[org]] = {}
        starters = 0
        for child in team['Children']:
            pid, stats = int(child['Id'].removeprefix('P_')), child['Stats']
            played = _clock(stats['TP'])
            if played:
                official[team_of[org]][who(pid)] = (played, stats['PM'])
            if stats['Starter']:
                starters += 1
                events.append(Event(0, team_of[org], f'{who(pid)} プレイヤーイン'))
        if starters != 5:
            raise StructureError(f'FIBAのボックススコアで {team_of[org]} の先発が{starters}人')

    start, num_periods = 0, 0
    for label, period in pbp.items():
        length = _period_length(label)
        for e in sorted(period['items'], key=lambda e: e['order']):
            sec = start + length - _clock(e['Time'])
            if e['ac'] == 'SUBST':
                inout = {'Sub-In': 'イン', 'Sub-Out': 'アウト'}.get(e['txt'])
                if inout is None:
                    raise StructureError(f'FIBAの交代記録の種類 {e["txt"]} を読めない')
                events.append(Event(sec, team_of[e['oId']], f'{who(e["pId"])} プレイヤー{inout}'))
            elif e['ac'] in SHOT_KIND:
                mark = '○' if e.get('made') else '×'
                events.append(Event(sec, team_of[e['oId']], f'{who(e["pId"])} {SHOT_KIND[e["ac"]]} {mark}'))
        start += length
        num_periods += 1
    if any(a.sec > b.sec for a, b in zip(events, events[1:])):
        raise StructureError('FIBAのプレイバイプレイで、記録の順序と時刻が食い違っている')
    if num_periods < REGULAR_PERIODS and not game['isLive']:
        raise StructureError(f'試合終了なのにピリオドが{num_periods}個しかない')

    utc = datetime.fromisoformat(game['gameDateTimeUTC']).replace(tzinfo=timezone.utc).astimezone(JST)
    return FibaGame(
        game_id=f'fiba-{game_id}',
        url=url.split('#')[0],
        competition=COMPETITION_JA.get(slug, slug),
        date=utc.strftime('%Y-%m-%d'),
        tipoff=utc.strftime('%H:%M'),
        home=names['A'],
        away=names['B'],
        home_score=game['teamAScore'],
        away_score=game['teamBScore'],
        final=not game['isLive'],
        events=events,
        num_periods=num_periods,
        official=official,
    )


def check_against_box_score(result: dict, official: dict, tolerance_sec: int = 1) -> list[str]:
    """Differences between the rebuilt minutes and +/- and FIBA's box score.
    Minutes are allowed a second of slack: the box score counts tenths."""
    problems = []
    for team in result['teams']:
        rebuilt = {f"#{p['jersey']} {p['name']}": (p['totalSec'], p['plusMinus']) for p in team['players']}
        expected = official.get(team['name'], {})
        for key in sorted(set(rebuilt) | set(expected)):
            got, want = rebuilt.get(key, (0, 0)), expected.get(key, (0, 0))
            if abs(got[0] - want[0]) > tolerance_sec:
                problems.append(f'{team["name"]} {key}: 出場 {got[0]}秒（公式 {want[0]}秒）')
            if got[1] != want[1]:
                problems.append(f'{team["name"]} {key}: +/- {got[1]}（公式 {want[1]}）')
    return problems
