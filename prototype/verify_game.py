import re, sys
from collections import defaultdict

def parse_clock(t):
    m = re.match(r'残り(\d+)分(\d+)秒', t)
    return int(m.group(1))*60+int(m.group(2))

def parse_item(li):
    time_m = re.search(r'ba-liveText__time">([^<]*)<', li)
    team_m = re.search(r'ba-liveText__name">([^<]*)<', li)
    desc_m = re.search(r'ba-liveText__desc">([^<]*)<', li)
    return (time_m.group(1) if time_m else None,
            team_m.group(1) if team_m else None,
            desc_m.group(1) if desc_m else None)

def load_events(html_path, period_len=600):
    with open(html_path, encoding='utf-8') as f:
        html = f.read()
    blocks = re.split(r'<span class="ba-accordion__title">([^<]*)</span>', html)
    events = []
    period_titles = []
    for qi in range(1, len(blocks), 2):
        title = blocks[qi]
        period_titles.append(title)
        period_idx = (qi-1)//2
        for li in re.findall(r'<li>(.*?)</li>', blocks[qi+1], re.S):
            t, team, desc = parse_item(li)
            if not (t and team and desc):
                continue
            remain = parse_clock(t)
            g = period_idx*period_len + (period_len - remain)
            events.append((g, t, team, desc, title))
    return events, period_titles

def shot_points(desc):
    m = re.search(r'(2Pシュート|3Pシュート|フリースロー).*?(○|×)', desc)
    if m and m.group(2) == '○':
        return {'2Pシュート':2, '3Pシュート':3, 'フリースロー':1}[m.group(1)]
    return 0

def parse_final_score(scoreboard_path):
    with open(scoreboard_path, encoding='utf-8') as f:
        html = f.read()
    names = re.findall(r'ba-scoreBoard__teamName">\s*([^\s<][^<]*?)\s*<', html)
    home = re.search(r'ba-scoreBoard__data ba-scoreBoard__data--totalHome"[^>]*>(\d+)', html)
    away = re.search(r'ba-scoreBoard__data ba-scoreBoard__data--totalAway"[^>]*>(\d+)', html)
    return names, (int(home.group(1)) if home else None), (int(away.group(1)) if away else None)

def verify(game_id, text_path, scoreboard_path, period_len=600):
    print(f"\n{'='*60}\ngameId={game_id}\n{'='*60}")
    events, period_titles = load_events(text_path, period_len)
    print("ピリオド:", period_titles)
    teams = sorted(set(e[2] for e in events))
    print("チーム:", teams)

    # 得点再計算
    totals = defaultdict(int)
    for g, t, team, desc, _ in events:
        totals[team] += shot_points(desc)
    print("再計算スコア:", dict(totals))
    try:
        names, home, away = parse_final_score(scoreboard_path)
        print("scoreboard.htmlのチーム名候補:", names[:4], "home=", home, "away=", away)
    except Exception as ex:
        print("scoreboard解析失敗:", ex)

    # 冪等な状態機械で復元 + 異常検知
    open_start = defaultdict(dict)
    anomalies = []
    game_end = period_len * len(period_titles)
    for g, t, team, desc, _ in events:
        m = re.match(r'#(\d+)\s+(\S+)\s+プレイヤー(イン|アウト)', desc)
        if not m:
            continue
        jersey, name, inout = m.groups()
        key = (jersey, name)
        if inout == 'イン':
            if key in open_start[team]:
                anomalies.append((g, t, team, key, '重複IN'))
            else:
                open_start[team][key] = g
        else:
            if key in open_start[team]:
                open_start[team].pop(key)
            else:
                anomalies.append((g, t, team, key, '重複OUT'))

    print(f"異常イベント(重複IN/OUT): {len(anomalies)}件")
    for a in anomalies:
        print("  ", a)

    # 合計出場時間チェック(簡易: 冪等ロジックでのintervalsから)
    open_start2 = defaultdict(dict)
    intervals = []
    for g, t, team, desc, _ in events:
        m = re.match(r'#(\d+)\s+(\S+)\s+プレイヤー(イン|アウト)', desc)
        if not m:
            continue
        jersey, name, inout = m.groups()
        key = (jersey, name)
        if inout == 'イン':
            if key not in open_start2[team]:
                open_start2[team][key] = g
        else:
            if key in open_start2[team]:
                s = open_start2[team].pop(key)
                intervals.append((team, key, s, g))
    for team, d in open_start2.items():
        for key, s in d.items():
            intervals.append((team, key, s, game_end))
    by_team_total = defaultdict(int)
    for team, key, s, e in intervals:
        by_team_total[team] += e - s
    expected = 5 * game_end
    for team in teams:
        total = by_team_total[team]
        status = 'OK' if total == expected else f'NG(差分{total-expected:+d}秒)'
        print(f"{team}: 合計出場時間 {total}秒 (期待値{expected}秒) {status}")

if __name__ == '__main__':
    gid = sys.argv[1]
    verify(gid, f"text_live_{gid}.html", f"scoreboard_{gid}.html")
