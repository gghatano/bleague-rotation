import json
from datetime import datetime, timezone
from pathlib import Path

from . import corrections
from .analyze import DataError, UnsupportedGame, analyze, clock_label
from .fetch import Fetcher
from .parse import ScheduledGame, StructureError, parse_play_by_play, parse_schedule

FINISHED = '試合終了'
TEXT_URL = 'https://sports.yahoo.co.jp/basket/bleague/premier/game/{}/text'
SCHEDULE_URL = 'https://sports.yahoo.co.jp/basket/bleague/premier/schedule/reg/?date={}'


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.corrections_dir = data_dir.parent / 'corrections'
        self.index_path = data_dir / 'games.json'
        self.index = json.loads(self.index_path.read_text(encoding='utf-8')) if self.index_path.exists() else {'games': {}}

    def game_path(self, game_id: str) -> Path:
        return self.data_dir / 'games' / f'{game_id}.json'

    def save_index(self):
        self.index['games'] = dict(sorted(self.index['games'].items()))
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')

    def dates_to_recheck(self, first: str, last: str) -> list[str]:
        """Dates (YYYYMMDD) in [first, last] with a published game, to pick up
        corrections the source makes in the days after a game."""
        return sorted({g['date'].replace('-', '') for g in self.index['games'].values()
                       if g['status'] == 'ok' and first <= g['date'].replace('-', '') <= last})

    def dates_to_retry(self) -> list[str]:
        return sorted({g['date'].replace('-', '') for g in self.index['games'].values() if g['status'] in ('error', 'live')})


class Report:
    """Problems found in one run, and previously failing games that now pass.

    Each problem carries a stable key so the notifier can find an issue it
    opened on an earlier run instead of opening a duplicate.
    """

    def __init__(self):
        self.problems = []
        self.resolved = []

    def problem(self, kind: str, key: str, title: str, body: str):
        self.problems.append({'kind': kind, 'key': key, 'title': title, 'body': body})

    def write(self, path: Path):
        path.write_text(json.dumps({'problems': self.problems, 'resolved': self.resolved}, ensure_ascii=False, indent=1) + '\n',
                        encoding='utf-8')


def _entry(game: ScheduledGame, ymd: str) -> dict:
    return {
        'gameId': game.game_id,
        'date': f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}',
        'tipoff': game.tipoff,
        'home': {'name': game.home.name, 'teamId': game.home.team_id, 'score': game.home_score},
        'away': {'name': game.away.name, 'teamId': game.away.team_id, 'score': game.away_score},
    }


def game_key(game_id: str) -> str:
    return f'gameId {game_id}'


def _report_game_problem(report: Report, entry: dict, kind: str, message: str):
    gid = entry['gameId']
    label = f"{entry['date']} {entry['home']['name']}-{entry['away']['name']}（{game_key(gid)}）"
    if kind == 'structure':
        title = f'出典の構造変化の疑い: {label}'
        lead = 'テキスト速報を想定どおりに読み取れませんでした。出典のページ構造が変わった可能性があります。'
    else:
        title = f'データ不整合: {label}'
        lead = '交代記録からコート上の5人を復元できませんでした。この試合のページは公開を保留し、毎朝の実行で再取得します。'
    body = (f'{lead}\n\n- 内容: {message}\n- 出典: {TEXT_URL.format(gid)}\n\n'
            '再取得で解消した場合は、自動でこのissueを閉じます。')
    report.problem(kind, game_key(gid), title, body)


def in_progress(game: ScheduledGame) -> bool:
    return game.status != FINISHED and game.home_score is not None and game.away_score is not None


def _attempt(events, num_periods, game: ScheduledGame, final: bool):
    """Returns (result, problem). A live result cut short by an inconsistency is
    still usable, so it comes back together with the problem that cut it."""
    try:
        result = analyze(events, num_periods, game.home.name, game.away.name, final=final)
    except DataError as e:
        return None, e
    computed = [t['score'] for t in result['teams']]
    if final and computed != [game.home_score, game.away_score]:
        return None, DataError(f'再計算した得点 {computed[0]}-{computed[1]} が公式スコア {game.home_score}-{game.away_score} と一致しない')
    if result['truncated']:
        return result, DataError(result['truncated']['reason'])
    return result, None


def _report_stale_correction(report: Report, entry: dict):
    gid = entry['gameId']
    report.problem('correction', f'correction {gid}',
                   f"補正が不要になった可能性: {entry['date']} {entry['home']['name']}-{entry['away']['name']}（correction {gid}）",
                   f'出典の記録が補正なしで検証を通るようになりました。出典側で修正された可能性があります。\n\n'
                   f'`corrections/{gid}.json` を削除してください（現在は適用していません）。\n- 出典: {TEXT_URL.format(gid)}')


def process_game(store: Store, fetcher: Fetcher, game: ScheduledGame, ymd: str, report: Report) -> dict:
    """A finished game must reproduce the official score exactly. A game in
    progress is only checked for five on court: its schedule score is fetched a
    moment before the play-by-play and can already be a basket behind.

    A hand-written correction is applied only when the raw record fails, so a
    fix the source has since made itself is never overridden."""
    final = game.status == FINISHED
    entry = _entry(game, ymd)
    previous = store.index['games'].get(game.game_id, {})
    path = store.game_path(game.game_id)
    correction = corrections.load(store.corrections_dir, game.game_id)
    applied = []
    try:
        events, num_periods = parse_play_by_play(fetcher.play_by_play(game.game_id), **({} if final else {'min_events': 0}))
        result, problem = _attempt(events, num_periods, game, final)
        if problem is None and correction:
            _report_stale_correction(report, entry)
        elif problem is not None and correction:
            try:
                fixed, fixed_problem = _attempt(corrections.apply(events, correction), num_periods, game, final)
            except DataError as e:
                fixed, fixed_problem = None, e
            if fixed is not None and fixed_problem is None:
                result, problem, applied = fixed, None, corrections.describe(correction)
            else:
                problem = DataError(f'{problem}（補正 corrections/{game.game_id}.json を適用しても解消しない: {fixed_problem}）')
        if result is None:
            raise problem
        computed = [t['score'] for t in result['teams']]
        if not final:
            entry['clock'] = game.status
            if result['truncated']:
                entry['truncatedAt'] = clock_label(result['truncated']['sec'])
            else:
                entry['home']['score'], entry['away']['score'] = computed
    except UnsupportedGame as e:
        entry.update(status='unsupported', message=str(e))
        path.unlink(missing_ok=True)
    except (DataError, StructureError) as e:
        kind = 'structure' if isinstance(e, StructureError) else 'data'
        entry.update(status='error', errorKind=kind, message=str(e))
        path.unlink(missing_ok=True)
        _report_game_problem(report, entry, kind, str(e))
    else:
        entry.update(status='ok' if final else 'live', anomalies=len(result['anomalies']))
        if applied:
            entry['corrected'] = len(applied)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**entry, **result, 'corrections': applied}
        stored = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        if stored is None or {k: v for k, v in stored.items() if k != 'generatedAt'} != payload:
            payload['generatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        if final and previous.get('status') == 'error':
            note = (f'補正ファイル `corrections/{game.game_id}.json` を適用して検証を通過したため、試合ページを公開しました。'
                    if applied else '再取得したデータで検証を通過したため、試合ページを公開しました。')
            report.resolved.append({'key': game_key(game.game_id), 'gameId': game.game_id, 'note': note})
    store.index['games'][game.game_id] = entry
    return entry


def process_date(store: Store, fetcher: Fetcher, ymd: str, report: Report, live: bool = False) -> list[dict]:
    try:
        games, season_dates = parse_schedule(fetcher.schedule(ymd))
        if not season_dates:
            raise StructureError('日程からシーズンの開催日一覧を読めない')
        if ymd in season_dates and not games:
            raise StructureError('開催日なのに日程から試合を1件も読めない')
    except StructureError as e:
        report.problem('structure', f'schedule {ymd}', f'出典の構造変化の疑い: {ymd} の日程（schedule {ymd}）',
                       f'日程を想定どおりに読み取れませんでした。出典のページ構造が変わった可能性があります。\n\n'
                       f'- 内容: {e}\n- 出典: {SCHEDULE_URL.format(ymd)}')
        return []
    store.index['seasonDates'] = season_dates
    return [process_game(store, fetcher, g, ymd, report) for g in games
            if g.status == FINISHED or (live and in_progress(g))]
