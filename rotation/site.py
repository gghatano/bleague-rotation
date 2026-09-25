import html
import json
import shutil
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'
LINEUP_ROWS = 6


def _json_for_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace('</', '<\\/')


def _mmss(sec: int) -> str:
    return f'{sec // 60}:{sec % 60:02d}'


def _signed(n: int) -> str:
    return f'+{n}' if n > 0 else str(n)


def _sign_class(n: int) -> str:
    return 'lu-pos' if n > 0 else 'lu-neg' if n < 0 else 'lu-zero'


def _lineup_table(lineups: list[dict]) -> str:
    rows = []
    for g in lineups[:LINEUP_ROWS]:
        names = ' '.join(f"#{p['jersey']} {html.escape(p['name'])}" for p in g['lineup'])
        rows.append(
            f'<tr><td class="lu-time">{_mmss(g["sec"])}</td>'
            f'<td class="lu-margin {_sign_class(g["margin"])}">{_signed(g["margin"])}</td>'
            f'<td class="lu-fa">{g["for"]}-{g["against"]}</td><td class="lu-cnt">{g["stints"]}</td>'
            f'<td class="lu-names">{names}</td></tr>')
    rest = lineups[LINEUP_ROWS:]
    if rest:
        sec, margin = sum(g['sec'] for g in rest), sum(g['margin'] for g in rest)
        rows.append(
            f'<tr class="lu-rest"><td class="lu-time">{_mmss(sec)}</td>'
            f'<td class="lu-margin {_sign_class(margin)}">{_signed(margin)}</td>'
            f'<td class="lu-fa">–</td><td class="lu-cnt">–</td><td class="lu-names">他 {len(rest)} 組み合わせ</td></tr>')
    return ('<div class="lu-scroll"><table class="lu-table"><thead><tr><th>出場</th><th>+/-</th>'
            '<th>得点-失点</th><th>回数</th><th>5人</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def render_game(game: dict) -> str:
    home, away = game['teams']
    t1, t2 = html.escape(home['name']), html.escape(away['name'])
    y, m, d = (int(x) for x in game['date'].split('-'))
    lineups = ('<div class="lineups"><h3 class="lu-heading">出場選手の集合別 +/-</h3>'
               '<p class="lu-sub">同じ５人の組み合わせを、連続しない出場も合わせて集計（出場時間順）</p>')
    for slot, team in (('t1', home), ('t2', away)):
        lineups += f'<p class="lu-team" style="color:var(--{slot}-ink)">{html.escape(team["name"])}</p>' + _lineup_table(team['lineups'])
    lineups += '</div>'
    chart = {
        'periodLength': game['periodLength'],
        'numPeriods': game['numPeriods'],
        'teams': [{'name': t['name'], 'color': f'var(--{slot})', 'players': t['players'], 'stints': t['stints']}
                  for slot, t in (('t1', home), ('t2', away))],
    }
    note = f'ソースの重複した交代記録{len(game["anomalies"])}件は無視して集計しています。' if game['anomalies'] else ''
    values = {
        'TITLE': f'{t1}-{t2} ローテーション',
        'DATE': game['date'],
        'T1': t1, 'T2': t2,
        'S1': str(home['score']), 'S2': str(away['score']),
        'META': f'{y}年{m}月{d}日 {html.escape(game["tipoff"])}・B.LEAGUE PREMIER（ホーム {t1}）',
        'NOTE': note,
        'LINEUPS': lineups,
        'DATA': _json_for_script(chart),
    }
    page = (TEMPLATES / 'game.html').read_text(encoding='utf-8')
    for key, value in values.items():
        page = page.replace('{{' + key + '}}', value)
    return page


def build(data_dir: Path, out_dir: Path) -> int:
    index = json.loads((data_dir / 'games.json').read_text(encoding='utf-8'))
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / 'games').mkdir(parents=True)
    built = 0
    for game_id, entry in index['games'].items():
        if entry['status'] != 'ok':
            continue
        game = json.loads((data_dir / 'games' / f'{game_id}.json').read_text(encoding='utf-8'))
        (out_dir / 'games' / f'{game_id}.html').write_text(render_game(game), encoding='utf-8')
        built += 1
    page = (TEMPLATES / 'index.html').read_text(encoding='utf-8')
    page = page.replace('{{INDEX}}', _json_for_script(index))
    (out_dir / 'index.html').write_text(page, encoding='utf-8')
    (out_dir / '.nojekyll').write_text('', encoding='utf-8')
    return built
