#!/usr/bin/env python3
"""
評価シート（評価シート_竹島尚哉 の template タブ）と、評価エピソードの候補を扱う。

    python eval_sync.py sheet [--if-older 7]
        評価項目（領域・項目・レベル2/3の着眼点と行動事例）と、過去の評点・エピソードを evaluation.json に書く。
        --if-older N なら、前回の読み込みから N 日たっていないときは何もしない
    python eval_sync.py since
        前回エピソード候補を集めた日（YYYY-MM-DD）を出す。空なら初回
    python eval_sync.py context --date YYYY-MM-DD
        その日の材料を出す：完了したタスク（tasks.json）、会議（calendar.json）、評価項目とレベル3の着眼点
        Slack は Claude が MCP で読む
    python eval_sync.py add <候補の JSON ファイル> --date YYYY-MM-DD
        候補を episodes.json に足し、集めた日を進める。
        JSON は [{"item", "level", "note", "source": {"type", "ref", "url"}}, ...]
        item は評価項目名、note は何があったかの1行メモ（例：竹原さんに ASA の切り分け方法をヒアリングできた）。
        評価シートの書き方（［経緯・目的］［行動・結果］）にするのは期末にまとめてやる

書き込むのは evaluation.json と episodes.json だけ。採用・却下は画面が tasks.json に持つ。
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import sys
import urllib.parse

from mission_sync import api, token

ROOT = pathlib.Path(__file__).resolve().parent
EVAL = ROOT / 'evaluation.json'
EPIS = ROOT / 'episodes.json'
TASKS = ROOT / 'tasks.json'
CAL = ROOT / 'calendar.json'
SHEET_ID = '14LBS3OSb8U-FReiF5xLrYVNOGyF2OsDQVbLI3JmZf1g'
TAB = 'template'
HEAD_ROW = 30          # 期の名前が並ぶ行（0始まり）。評点の列の上にある
FIRST_ITEM_ROW = 32    # ここから「項目×レベル」の行が続く
C_AREA, C_ITEM, C_LEVEL, C_FOCUS, C_EXAMPLE = 0, 1, 2, 3, 4
KEEP = 1000


def load(path, empty):
    if not path.exists():
        return empty
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def save(path, doc):
    tmp = path.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def cmd_sheet(a):
    if a.if_older and EVAL.exists():
        at = load(EVAL, {}).get('pulledAt', '')
        try:
            age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(at.replace('Z', '+00:00'))
            if age.days < a.if_older:
                print(json.dumps({'skipped': True, 'pulledAt': at}))
                return
        except ValueError:
            pass
    tok = token()
    rows = api(tok, '/values/' + urllib.parse.quote(TAB + '!A1:AZ80'), sheet=SHEET_ID).get('values', [])
    width = max(len(r) for r in rows)
    rows = [r + [''] * (width - len(r)) for r in rows]
    head = rows[HEAD_ROW]
    # 期は「評点の列」。次の列が次の期の評点でなければ、そこがエピソード
    cols = [c for c, v in enumerate(head) if v.strip()]
    periods = [{'name': head[c].strip(), 'score': c, 'ep': c + 1 if c + 1 not in cols else None} for c in cols]
    items = {}
    for r in rows[FIRST_ITEM_ROW:]:
        name, lv = r[C_ITEM].strip(), r[C_LEVEL].strip()
        if not name or lv not in ('2', '3'):
            continue
        it = items.setdefault(name, {'name': name, 'area': r[C_AREA].strip(), 'levels': {}, 'history': {}})
        it['levels'][lv] = {'focus': r[C_FOCUS].strip(), 'examples': r[C_EXAMPLE].strip()}
        for p in periods:
            h = it['history'].setdefault(p['name'], {'period': p['name']})
            if lv == '2' and r[p['score']].strip():
                h['score'] = r[p['score']].strip()
            if p['ep'] is not None and r[p['ep']].strip():
                h['ep' + lv] = r[p['ep']].strip()
    out = {'sheetId': SHEET_ID, 'periods': [p['name'] for p in periods],
           'items': [dict(it, history=[it['history'][p['name']] for p in periods]) for it in items.values()],
           'pulledAt': now()}
    save(EVAL, out)
    print(json.dumps({'items': len(out['items']), 'periods': out['periods']}, ensure_ascii=False))


def cmd_since(_a):
    print(load(EPIS, {}).get('lastDate', ''))


def cmd_context(a):
    day = a.date
    board = load(TASKS, {'tasks': []})
    done = []
    for t in board.get('tasks', []):
        if (t.get('completedAt') or '')[:10] == day:
            done.append({'title': t.get('title', ''), 'notes': (t.get('notes') or '')[:300]})
        for k in t.get('subtasks', []):
            sch = k.get('schedule') or {}
            if k.get('done') and sch.get('date') == day:
                done.append({'title': t.get('title', '') + '_' + k.get('title', '')})
    cal = load(CAL, {'events': []})
    events = [{'title': e.get('title') or e.get('summary', ''), 'start': e.get('start', ''), 'end': e.get('end', '')}
              for e in cal.get('events', []) if str(e.get('date') or e.get('start', ''))[:10] == day]
    ev = load(EVAL, {'items': []})
    items = [{'name': it['name'], 'area': it['area'],
              'lv2': it['levels'].get('2', {}).get('focus', ''), 'lv3': it['levels'].get('3', {}).get('focus', '')}
             for it in ev.get('items', [])]
    json.dump({'date': day, 'doneTasks': done, 'meetings': events, 'items': items}, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_add(a):
    names = {it['name'] for it in load(EVAL, {'items': []}).get('items', [])}
    doc = load(EPIS, {'lastDate': '', 'items': []})
    have = {x['id'] for x in doc['items']}
    with open(a.file, encoding='utf-8') as fh:
        picks = json.load(fh)
    added, skipped = [], []
    for p in picks if isinstance(picks, list) else []:
        item = str(p.get('item', '')).strip()
        if names and item not in names:
            skipped.append(f'{item}（評価項目に無い）')
            continue
        src = p.get('source') or {}
        key = f"{item}|{src.get('url') or src.get('ref') or p.get('note', '')}"
        iid = 'ep-' + hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]
        if iid in have:
            continue
        doc['items'].append({'id': iid, 'date': p.get('date') or a.date, 'item': item,
                             'level': str(p.get('level') or '3'), 'note': str(p.get('note', '')).strip(),
                             'source': {'type': src.get('type', ''), 'ref': src.get('ref', ''), 'url': src.get('url', '')},
                             'createdAt': now()})
        have.add(iid)
        added.append(item)
    if a.date > (doc.get('lastDate') or ''):
        doc['lastDate'] = a.date
    doc['items'] = doc['items'][-KEEP:]
    save(EPIS, doc)
    json.dump({'added': added, 'skipped': skipped, 'lastDate': doc['lastDate']}, sys.stdout, ensure_ascii=False)
    print()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('sheet')
    p.add_argument('--if-older', type=int, default=0)
    sub.add_parser('since')
    p = sub.add_parser('context')
    p.add_argument('--date', required=True)
    p = sub.add_parser('add')
    p.add_argument('file')
    p.add_argument('--date', required=True)
    a = ap.parse_args()
    {'sheet': cmd_sheet, 'since': cmd_since, 'context': cmd_context, 'add': cmd_add}[a.cmd](a)


if __name__ == '__main__':
    main()
