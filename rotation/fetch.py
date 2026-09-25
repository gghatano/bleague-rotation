import time
import urllib.request
from pathlib import Path

BASE = 'https://sports.yahoo.co.jp/basket/widget/ds/pc/premier'
USER_AGENT = 'bleague-rotation (+https://github.com/gghatano/bleague-rotation)'
REQUEST_INTERVAL_SEC = 3


class Fetcher:
    def __init__(self, raw_dir: Path):
        self.raw_dir = raw_dir
        self._last = 0.0

    def _get(self, url: str, cache_name: str) -> str:
        wait = self._last + REQUEST_INTERVAL_SEC - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read().decode('utf-8')
        self._last = time.monotonic()
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        (self.raw_dir / cache_name).write_text(body, encoding='utf-8')
        return body

    def schedule(self, ymd: str) -> str:
        return self._get(f'{BASE}/daily/schedule_{ymd}.html', f'schedule_{ymd}.html')

    def play_by_play(self, game_id: str) -> str:
        return self._get(f'{BASE}/games/{game_id}/text_live.html', f'text_live_{game_id}.html')
