import json
from datetime import datetime, timezone
from pathlib import Path

from .analyze import DataError, UnsupportedGame, analyze
from .fetch import Fetcher
from .parse import ScheduledGame, parse_play_by_play, parse_schedule

FINISHED = '試合終了'


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.index_path = data_dir / 'games.json'
        self.index = json.loads(self.index_path.read_text(encoding='utf-8')) if self.index_path.exists() else {'games': {}}

    def game_path(self, game_id: str) -> Path:
        return self.data_dir / 'games' / f'{game_id}.json'

    def save_index(self):
        self.index['games'] = dict(sorted(self.index['games'].items()))
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    def games_to_retry(self) -> list[str]:
        return sorted({g['date'].replace('-', '') for g in self.index['games'].values() if g['status'] != 'ok'})


def _entry(game: ScheduledGame, ymd: str) -> dict:
    return {
        'gameId': game.game_id,
        'date': f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}',
        'tipoff': game.tipoff,
        'home': {'name': game.home.name, 'teamId': game.home.team_id, 'score': game.home_score},
        'away': {'name': game.away.name, 'teamId': game.away.team_id, 'score': game.away_score},
    }


def process_game(store: Store, fetcher: Fetcher, game: ScheduledGame, ymd: str) -> dict:
    entry = _entry(game, ymd)
    path = store.game_path(game.game_id)
    try:
        events, num_periods = parse_play_by_play(fetcher.play_by_play(game.game_id))
        result = analyze(events, num_periods, game.home.name, game.away.name)
        computed = [t['score'] for t in result['teams']]
        if computed != [game.home_score, game.away_score]:
            raise DataError(f'再計算した得点 {computed[0]}-{computed[1]} が公式スコア {game.home_score}-{game.away_score} と一致しない')
    except (DataError, UnsupportedGame) as e:
        entry.update(status='unsupported' if isinstance(e, UnsupportedGame) else 'error', message=str(e))
        path.unlink(missing_ok=True)
    else:
        entry.update(status='ok', anomalies=len(result['anomalies']))
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**entry, **result, 'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    store.index['games'][game.game_id] = entry
    return entry


def process_date(store: Store, fetcher: Fetcher, ymd: str) -> list[dict]:
    games, season_dates = parse_schedule(fetcher.schedule(ymd))
    if season_dates:
        store.index['seasonDates'] = season_dates
    return [process_game(store, fetcher, g, ymd) for g in games if g.status == FINISHED]
