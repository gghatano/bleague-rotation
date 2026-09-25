import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .fetch import Fetcher
from .notify import notify
from .site import build
from .store import Report, Store, process_date

ROOT = Path(__file__).resolve().parent.parent


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
    default = jst_date(0) if args.live else jst_date(1)
    dates = sorted(set(args.date or [default]) | set(store.dates_to_retry()))
    season = store.index.get('seasonDates')
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


def cmd_notify(args) -> int:
    if not args.repo:
        raise SystemExit('--repo か環境変数 GITHUB_REPOSITORY でリポジトリを指定してください')
    notify(Path(args.report), args.repo, args.dry_run)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog='python -m rotation')
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser('update', help='指定日（既定: 前日JST）の終了済みの試合を取得・集計する。不整合・試合中だった試合も再試行する')
    p.add_argument('--date', action='append', type=ymd, help='YYYYMMDD。複数指定可')
    p.add_argument('--report', default=str(ROOT / 'report.json'), help='見つかった問題の出力先')
    p.add_argument('--live', action='store_true', help='試合中の試合も取り込む（日付の既定は当日JST）')
    p.set_defaults(func=cmd_update)
    p = sub.add_parser('build', help='data/ から静的サイトを生成する')
    p.add_argument('--out', default=str(ROOT / '_site'))
    p.set_defaults(func=cmd_build)
    p = sub.add_parser('notify', help='update のレポートをもとに GitHub issue を作成・クローズする')
    p.add_argument('report')
    p.add_argument('--repo', default=os.environ.get('GITHUB_REPOSITORY'))
    p.add_argument('--dry-run', action='store_true', help='issue を作成・変更せず、実行内容だけ表示する')
    p.set_defaults(func=cmd_notify)
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
