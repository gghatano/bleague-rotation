import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .fetch import Fetcher
from .notify import notify
from .ratings import load_games, player_ratings, team_ratings, write
from .site import build
from .store import Report, Store, process_date

ROOT = Path(__file__).resolve().parent.parent
RECHECK_DAYS = 3


def ymd(value: str) -> str:
    if not re.fullmatch(r'20\d{6}', value):
        raise argparse.ArgumentTypeError('YYYYMMDD 形式で指定してください')
    return value


def jst_date(days_ago: int) -> str:
    return (datetime.now(ZoneInfo('Asia/Tokyo')) - timedelta(days=days_ago)).strftime('%Y%m%d')


def cmd_update(args) -> int:
    store = Store(ROOT / 'data')
    fetcher = Fetcher(ROOT / 'raw')
    report = Report()
    season = store.index.get('seasonDates')
    if args.live:
        today = jst_date(0)
        default = max((d for d in season or [] if d <= today), default=today)
        recheck = []
    else:
        default = jst_date(1)
        recheck = [] if args.date else store.dates_to_recheck(jst_date(RECHECK_DAYS), jst_date(2))
    dates = sorted(set(args.date or [default]) | set(store.dates_to_retry()) | set(recheck))
    for day in dates:
        if season and day not in season and not args.date:
            print(f'{day}: 試合なし')
            continue
        entries = process_date(store, fetcher, day, report, live=args.live)
        store.save_index()
        if not entries:
            print(f'{day}: 対象の試合なし')
        for e in entries:
            line = f"{day} {e['gameId']} {e['home']['name']} {e['home']['score']}-{e['away']['score']} {e['away']['name']}: {e['status']}"
            line += f" [{e['clock']}]" if 'clock' in e else ''
            print(line + (f" ({e['message']})" if 'message' in e else ''))
    report.write(Path(args.report))
    print(f'問題 {len(report.problems)} 件、解消 {len(report.resolved)} 件 → {args.report}')
    return 0


def cmd_build(args) -> int:
    count = build(ROOT / 'data', Path(args.out))
    print(f'{count} 試合のページを {args.out} に生成')
    return 0


def cmd_ratings(args) -> int:
    games = load_games(ROOT / 'data')
    rows = team_ratings(games) if args.teams else player_ratings(games, args.min_minutes)
    if args.out:
        write(rows, Path(args.out))
        print(f'{len(games)} 試合から {len(rows)} 行を {args.out} に出力')
        return 0
    if args.teams:
        for r in rows:
            print(f"{r['team']:6} pace {r['pace']:5.1f}  ORtg {r['ortg']:6.1f}  DRtg {r['drtg']:6.1f}  Net {r['net']:+6.1f}")
        return 0
    for r in rows[:args.top] + ([None] + rows[-args.top:] if len(rows) > 2 * args.top else rows[args.top:]):
        if r is None:
            print('...')
            continue
        v = lambda k, spec: format(r[k], spec) if r[k] is not None else '–'
        print(f"{r['team']:6}#{r['jersey']:>3} {r['name']:10} {r['onMin']:5.0f}分 | "
              f"on {v('onORtg', '6.1f')}/{v('onDRtg', '6.1f')} ({v('onNet', '+6.1f')}) | "
              f"off {v('offORtg', '6.1f')}/{v('offDRtg', '6.1f')} ({v('offNet', '+6.1f')}) | "
              f"差 O {v('diffORtg', '+5.1f')} D {v('diffDRtg', '+5.1f')} Net {v('diffNet', '+5.1f')}")
    return 0


def cmd_notify(args) -> int:
    if not args.repo:
        raise SystemExit('--repo か環境変数 GITHUB_REPOSITORY でリポジトリを指定してください')
    notify(Path(args.report), args.repo, args.dry_run)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog='python -m rotation')
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser('update', help='指定日（既定: 前日JST）の終了済みの試合を取得・集計する。不整合・試合中だった試合と、2〜3日前の公開済みの試合も取り直す')
    p.add_argument('--date', action='append', type=ymd, help='YYYYMMDD。複数指定可')
    p.add_argument('--report', default=str(ROOT / 'report.json'), help='見つかった問題の出力先')
    p.add_argument('--live', action='store_true', help='試合中の試合も取り込む（日付の既定は当日。当日が開催日でなければ直近の開催日）')
    p.set_defaults(func=cmd_update)
    p = sub.add_parser('build', help='data/ から静的サイトを生成する')
    p.add_argument('--out', default=str(ROOT / '_site'))
    p.set_defaults(func=cmd_build)
    p = sub.add_parser('ratings', help='シーズンの on/off レーティング（100ポゼッションあたりの ORtg/DRtg）を集計する')
    p.add_argument('--min-minutes', type=float, default=150, help='対象にする出場分数の下限（既定 150）')
    p.add_argument('--teams', action='store_true', help='選手ではなくチーム単位で出す')
    p.add_argument('--top', type=int, default=15, help='画面表示で上下に出す人数')
    p.add_argument('--out', help='.json か .csv に全行を書き出す')
    p.set_defaults(func=cmd_ratings)
    p = sub.add_parser('notify', help='update のレポートをもとに GitHub issue を作成・クローズする')
    p.add_argument('report')
    p.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    p.add_argument('--dry-run', action='store_true', help='issue を作成・変更せず、実行内容だけ表示する')
    p.set_defaults(func=cmd_notify)
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
