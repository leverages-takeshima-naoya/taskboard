#!/usr/bin/env python3
"""
ミッション管理シート（【MK管理】FY26下期_個人ミッション入力シート の missions タブ）を読み書きする。
認証は gcloud の ADC（Sheets API を直接叩く）。

    python mission_sync.py pull
        自分のミッションと、メンバーのミッションを読んで missions.json に書く。画面はこれを読むだけ
    python mission_sync.py write <ミッション名の一部> --actual 50% --forecast 100% --comment "..." [--week 2026/10/27] [--dry-run]
        自分のミッションの、その週の「実績・着地見込・進捗コメント」を、管理シートと全社シートの両方に書く。
        --week が無ければ今週。2枚は行も週の列もずれているので、ミッション名と1行目の日付でそれぞれ探す。
        --dry-run で書かずに before / after を出す。--only kanri / zensha で片方だけ書く

週の列は、1行目の日付（進捗コメントの列の上にある）で探す。今日以前でいちばん新しい日付が「今週」。
ライターマネジメントの実績は、メンバー全員のミッションの ウェイト×実績 の加重平均（未入力は 0% として数え、件数を出す）。
書き込むのは missions.json とシートだけ。tasks.json には触らない。
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / 'missions.json'
SHEET_ID = '1R6eHu7LOm6KmI9bwIAhAf6N3MefjIx4rXtGllncGboM'
# 自分のミッションのウェイトは全社版（【MK】FY26下期_個人ミッション入力シート）を正とする。管理シートは空欄や古い値がある
WEIGHT_SHEET_ID = '1O-wPtLHuLyGId78Iwc867n9RrcYptO2_wFOevyy8Soo'
TAB = 'missions'
ME = '竹島'
MEMBERS = ['櫻井', '杉江', '森澤']
# 列（0始まり）。シートの見出しに合わせてある
C_NO, C_NAME, C_MISSION, C_CRITERIA, C_WEIGHT = 0, 2, 5, 6, 7
WEEK_FIRST = 46            # ここから「実績・着地見込・進捗コメント」が3列ずつ並ぶ。日付は進捗コメントの列の1行目


def token():
    env = dict(os.environ, CLOUDSDK_PYTHON=sys.executable)   # gcloud が Python を見つけられないことがあるため
    exe = shutil.which('gcloud') or 'gcloud'
    p = subprocess.run([exe, 'auth', 'application-default', 'print-access-token'],
                       capture_output=True, text=True, env=env)
    tok = (p.stdout or '').strip().splitlines()[-1:] or ['']
    if p.returncode != 0 or len(tok[0]) < 50:
        sys.exit('gcloud のトークンが取れません。`gcloud auth application-default login` が要るかもしれません\n' + (p.stderr or ''))
    return tok[0]


def api(tok, path, body=None, method='GET', sheet=SHEET_ID):
    req = urllib.request.Request('https://sheets.googleapis.com/v4/spreadsheets/' + sheet + path,
                                 data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def col_name(i):
    s = ''
    i += 1
    while i:
        i, m = divmod(i - 1, 26)
        s = chr(65 + m) + s
    return s


def pct(v):
    m = re.match(r'^\s*(-?\d+(?:\.\d+)?)\s*%?\s*$', v or '')
    return float(m.group(1)) if m else None


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def read(tok, sheet=SHEET_ID, last=400):
    rng = urllib.parse.quote(f'{TAB}!A1:CZ{last}')
    rows = api(tok, '/values/' + rng, sheet=sheet).get('values', [])
    width = max(len(r) for r in rows)
    return [r + [''] * (width - len(r)) for r in rows]


def weeks(rows):
    """[(日付, 実績の列)] を古い順に"""
    out = []
    for c in range(WEEK_FIRST + 2, len(rows[0]), 3):
        try:
            d = datetime.datetime.strptime(rows[0][c].strip(), '%Y/%m/%d').date()
        except ValueError:
            continue
        out.append((d, c - 2))
    return out


def this_week(ws, today=None):
    today = today or datetime.date.today()
    past = [w for w in ws if w[0] <= today]
    return past[-1] if past else ws[0]


def mission(rows, i, ws):
    r = rows[i]
    hist = [{'week': d.isoformat(), 'actual': pct(r[c]), 'forecast': pct(r[c + 1]), 'comment': r[c + 2]}
            for d, c in ws]
    return {'row': i + 1, 'no': r[C_NO], 'name': r[C_MISSION], 'criteria': r[C_CRITERIA], 'weight': num(r[C_WEIGHT]),
            'history': hist}


def cmd_pull(_a):
    tok = token()
    rows = read(tok)
    ws = weeks(rows)
    wk, _ = this_week(ws)
    at = [d for d, _ in ws].index(wk)
    mine = [mission(rows, i, ws) for i in range(2, len(rows)) if ME in rows[i][C_NAME] and rows[i][C_MISSION]]
    official = {r[C_MISSION]: num(r[C_WEIGHT]) for r in read(tok, WEIGHT_SHEET_ID, 3000)
                if ME in r[C_NAME] and r[C_MISSION]}
    for m in mine:
        if official.get(m['name']) is not None:
            m['weight'] = official[m['name']]
    members = []
    for n in MEMBERS:
        ms = [mission(rows, i, ws) for i in range(2, len(rows)) if n in rows[i][C_NAME] and rows[i][C_MISSION]]
        if not ms:
            continue
        full = next(rows[m['row'] - 1][C_NAME] for m in ms)
        members.append({'name': full, 'missions': ms})
    # ライターマネジメントの実績（今週）。未入力は 0% で数える
    tw = sum(m['weight'] or 0 for p in members for m in p['missions'])
    tv = sum((m['weight'] or 0) * (m['history'][at]['actual'] or 0) for p in members for m in p['missions'])
    missing = sum(1 for p in members for m in p['missions'] if m['history'][at]['actual'] is None)
    for p in members:
        w = sum(m['weight'] or 0 for m in p['missions'])
        v = sum((m['weight'] or 0) * (m['history'][at]['actual'] or 0) for m in p['missions'])
        p['weighted'] = round(v / w, 1) if w else None
        p['missing'] = sum(1 for m in p['missions'] if m['history'][at]['actual'] is None)
    doc = {'sheetId': SHEET_ID, 'week': wk.isoformat(), 'weeks': [d.isoformat() for d, _ in ws],
           'mine': mine, 'team': {'members': members, 'weighted': round(tv / tw, 1) if tw else None, 'missing': missing},
           'pulledAt': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')}
    tmp = OUT.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    json.dump({'week': doc['week'],
               'mine': [{'row': m['row'], 'name': m['name'], 'weight': m['weight'], 'actual': m['history'][at]['actual'],
                         'forecast': m['history'][at]['forecast']} for m in mine],
               'team': {'weighted': doc['team']['weighted'], 'missing': missing,
                        'members': [{'name': p['name'], 'weighted': p['weighted'], 'missing': p['missing']} for p in members]}},
              sys.stdout, ensure_ascii=False, indent=1)
    print()


SHEETS = {'kanri': SHEET_ID, 'zensha': WEIGHT_SHEET_ID}   # 書き込み先。管理シートと全社シート
SHEET_NAMES = {'kanri': '管理シート', 'zensha': '全社シート'}


def find_week(ws, week):
    if not week:
        return this_week(ws)
    hit = [w for w in ws if w[0].strftime('%Y/%m/%d') == week or w[0].isoformat() == week]
    if not hit:
        sys.exit(f'{week} の週の列が見つかりません')
    return hit[0]


def cmd_write(a):
    """ミッション名で自分の行を探し、その週の3列を書く。2枚のシートは行も週の列の位置も違うので、それぞれで探す"""
    tok = token()
    out = []
    for key in (a.only.split(',') if a.only else ['kanri', 'zensha']):
        rows = read(tok, SHEETS[key], 3000)
        mine = [i for i in range(2, len(rows)) if ME in rows[i][C_NAME] and a.mission in rows[i][C_MISSION]]
        if len(mine) != 1:
            sys.exit(f'{SHEET_NAMES[key]}で「{a.mission}」に当たる自分の行が {len(mine)} 件あります（1件に絞れる名前にしてください）')
        i = mine[0]
        wk, c = find_week(weeks(rows), a.week)
        before = rows[i][c:c + 3]
        after = [a.actual if a.actual is not None else before[0],
                 a.forecast if a.forecast is not None else before[1],
                 a.comment if a.comment is not None else before[2]]
        rng = f'{col_name(c)}{i + 1}:{col_name(c + 2)}{i + 1}'
        if not a.dry_run:
            api(tok, '/values/' + urllib.parse.quote(f'{TAB}!{rng}') + '?valueInputOption=USER_ENTERED',
                {'values': [after]}, 'PUT', sheet=SHEETS[key])
        out.append({'sheet': SHEET_NAMES[key], 'mission': rows[i][C_MISSION], 'week': wk.isoformat(), 'range': rng,
                    'before': before, 'after': after, 'written': not a.dry_run})
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('pull')
    p = sub.add_parser('write')
    p.add_argument('mission', help='ミッション名（一部でよい。例：新規アプリ）')
    p.add_argument('--only', help='kanri / zensha のどちらかだけ書くとき')
    p.add_argument('--dry-run', action='store_true', help='書かずに before / after だけ出す')
    p.add_argument('--actual')
    p.add_argument('--forecast')
    p.add_argument('--comment')
    p.add_argument('--week')
    a = ap.parse_args()
    {'pull': cmd_pull, 'write': cmd_write}[a.cmd](a)


if __name__ == '__main__':
    main()
