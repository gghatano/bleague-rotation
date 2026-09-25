import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .fetch import Fetcher
from .site import build
from .store import Store, process_date

ROOT = Path(__file__).resolve().parent.parent


def ymd(value: str) -> str:
    if not re.fullmatch(r'20\d{6}', value):
        raise argparse.ArgumentTypeError('YYYYMMDD 形式で指定してください')
    return value


def yesterday_jst() -> str:
    return (datetime.now(ZoneInfo('Asia/Tokyo')) - timedelta(days=1)).strftime('%Y%m%d')


def cmd_update(args) -> int:
    store = Store(ROOT / 'data')
    fetcher = Fetcher(ROOT / 'raw')
    dates = sorted(set(args.date or [yesterday_jst()]) | set(store.games_to_retry()))
    season = store.index.get('seasonDates')
    for day in dates:
        if season and day not in season and not args.date:
            print(f'{day}: 試合なし')
            continue
        entries = process_date(store, fetcher, day)
        store.save_index()
        if not entries:
            print(f'{day}: 終了済みの試合なし')
        for e in entries:
            line = f"{day} {e['gameId']} {e['home']['name']} {e['home']['score']}-{e['away']['score']} {e['away']['name']}: {e['status']}"
            print(line + (f" ({e['message']})" if 'message' in e else ''))
    return 0


def cmd_build(args) -> int:
    count = build(ROOT / 'data', Path(args.out))
    print(f'{count} 試合のページを {args.out} に生成')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog='python -m rotation')
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser('update', help='指定日（既定: 前日JST）の試合を取得・集計する。未解決の試合も再試行する')
    p.add_argument('--date', action='append', type=ymd, help='YYYYMMDD。複数指定可')
    p.set_defaults(func=cmd_update)
    p = sub.add_parser('build', help='data/ から静的サイトを生成する')
    p.add_argument('--out', default=str(ROOT / '_site'))
    p.set_defaults(func=cmd_build)
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
