"""Hand-written fixes for play-by-play records the source got wrong.

A file corrections/{gameId}.json looks like:

    {
      "issue": 11,
      "reason": "why the record is believed wrong",
      "replace": [
        {"at": "Q1 残り5:05", "team": "仙台",
         "from": "#10 レイマン プレイヤーアウト", "to": "#9 エル ダーウィッチ プレイヤーアウト"}
      ]
    }

"at" uses the same clock label the pages show. A rule must match exactly one
event; otherwise the source has changed underneath it and the file is stale.
"""
import json
from dataclasses import replace as dc_replace
from pathlib import Path

from .analyze import DataError, clock_label
from .parse import Event


def load(corrections_dir: Path, game_id: str) -> dict | None:
    path = corrections_dir / f'{game_id}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def apply(events: list[Event], correction: dict, num_periods: int = 4) -> list[Event]:
    events = list(events)
    for rule in correction['replace']:
        hits = [i for i, e in enumerate(events)
                if clock_label(e.sec, num_periods) == rule['at'] and e.team == rule['team'] and e.desc == rule['from']]
        if len(hits) != 1:
            raise DataError(f"補正「{rule['at']} {rule['team']} {rule['from']}」に当たる記録が{len(hits)}件（出典が変わった可能性）")
        events[hits[0]] = dc_replace(events[hits[0]], desc=rule['to'])
    return events


def describe(correction: dict) -> list[str]:
    return [f"{r['at']} {r['team']}: 「{r['from']}」→「{r['to']}」" for r in correction['replace']]
