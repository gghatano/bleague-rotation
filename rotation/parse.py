import html
import re
from dataclasses import dataclass

REGULAR_PERIOD_SEC = 600
MIN_EVENTS_PER_GAME = 100


class StructureError(Exception):
    """The source markup no longer matches what the parser expects."""


@dataclass(frozen=True)
class Event:
    sec: int
    team: str
    desc: str


@dataclass(frozen=True)
class Team:
    name: str
    team_id: str


@dataclass(frozen=True)
class ScheduledGame:
    game_id: str
    tipoff: str
    home: Team
    away: Team
    home_score: int | None
    away_score: int | None
    status: str


def _period_rows(block: str) -> list[tuple[int, str, str]]:
    rows = []
    for li in re.findall(r'<li>(.*?)</li>', block, re.S):
        clock = re.search(r'ba-liveText__time">残り(\d+)分(\d+)秒<', li)
        team = re.search(r'ba-liveText__name">([^<]*)<', li)
        desc = re.search(r'ba-liveText__desc">([^<]*)<', li)
        if clock and team and desc:
            remain = int(clock.group(1)) * 60 + int(clock.group(2))
            rows.append((remain, html.unescape(team.group(1)).strip(), html.unescape(desc.group(1)).strip()))
    return rows


def _is_newest_first(titles: list[str], periods: list[list[tuple[int, str, str]]]) -> bool:
    numbers = [int(m.group(1)) for t in titles if (m := re.fullmatch(r'第(\d+)クォーター', t.strip()))]
    if len(numbers) >= 2 and numbers[0] != numbers[-1]:
        return numbers[0] > numbers[-1]
    rows = periods[0] if periods else []
    return bool(rows) and rows[0][0] < rows[-1][0]


def parse_play_by_play(src: str, min_events: int = MIN_EVENTS_PER_GAME) -> tuple[list[Event], int]:
    """Returns events with game-clock seconds elapsed since tip-off, and the number of periods.

    A game in progress is rendered newest first (last quarter on top, latest play
    first); a finished game oldest first. Both are normalised to chronological order.
    """
    parts = re.split(r'<span class="ba-accordion__title">([^<]*)</span>', src)
    titles, periods = parts[1::2], [_period_rows(b) for b in parts[2::2]]
    if not titles:
        raise StructureError('テキスト速報にピリオドの見出しが見つからない')
    if _is_newest_first(titles, periods):
        titles.reverse()
        periods = [rows[::-1] for rows in reversed(periods)]
    events = []
    for period_idx, (title, rows) in enumerate(zip(titles, periods)):
        remains = [r for r, _, _ in rows]
        if remains != sorted(remains, reverse=True):
            raise StructureError(f'{title.strip()} のイベントが残り時間の順に並んでいない')
        for remain, team, desc in rows:
            events.append(Event(period_idx * REGULAR_PERIOD_SEC + REGULAR_PERIOD_SEC - remain, team, desc))
    if len(events) < min_events:
        raise StructureError(f'テキスト速報から読めたイベントが{len(events)}件しかない')
    return events, len(titles)


def _team(cell: str) -> Team:
    m = re.search(r'teams/(\d+)/info.*?<span>([^<]+)</span>', cell, re.S)
    if not m:
        raise StructureError('日程表からチーム名・チームIDを読めない')
    return Team(html.unescape(m.group(2)).strip(), m.group(1))


def parse_schedule(src: str) -> tuple[list[ScheduledGame], list[str]]:
    """Returns the day's games and the season's game dates (YYYYMMDD)."""
    season_dates = re.findall(r'\b(20\d{6})\b', src[:src.find('<table')] if '<table' in src else src)
    games = []
    tbody = src[src.find('<tbody>'):src.find('</tbody>')]
    for row in re.findall(r'<tr>(.*?)</tr>', tbody, re.S):
        game = re.search(r'/game/(\d+)/', row)
        if not game:
            continue
        cells = re.findall(r'<td class="ba-table__data ba-table__data--(\w+)">(.*?)</td>', row, re.S)
        teams = [_team(c) for kind, c in cells if kind == 'team']
        if len(teams) != 2:
            raise StructureError(f'日程表の1行からチームが{len(teams)}件しか読めない（gameId {game.group(1)}）')
        tipoff = re.search(r'<time[^>]*>([^<]*)</time>', row)
        detail = re.search(r'ba-table__scoreDetail">(.*?)</span>\s*<', row, re.S)
        scores = [int(n) for n in re.findall(r'\d+', re.sub(r'&nbsp;', ' ', detail.group(1)))] if detail else []
        status = re.search(r'ba-table__status">([^<]*)<', row)
        games.append(ScheduledGame(
            game_id=game.group(1),
            tipoff=tipoff.group(1).strip() if tipoff else '',
            home=teams[0],
            away=teams[1],
            home_score=scores[0] if len(scores) == 2 else None,
            away_score=scores[1] if len(scores) == 2 else None,
            status=status.group(1).strip() if status else '',
        ))
    return games, sorted(set(season_dates))
