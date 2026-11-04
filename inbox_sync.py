#!/usr/bin/env python3
"""
Slack の自分宛てDMから、taskboard の inbox に入れるタスクを拾う。Slack は叩かない。
読むのは Claude（Slack MCP の slack_read_channel）で、このスクリプトはその出力を
解釈して inbox.json に足すだけ。

    python inbox_sync.py since
        前回どこまで読んだか（Slack の ts）を出す。slack_read_channel の oldest に渡す
    python inbox_sync.py ingest <slack_read_channel の出力ファイル ...>
        「タスク」で始まるメッセージの2行目以降を、1行1件で inbox.json に足す
    python inbox_sync.py pending
        振り分け先の提案がまだ無い inbox の項目と、振り分け先の候補（プロジェクトと未完了の親タスク）を出す
    python inbox_sync.py suggest <提案の JSON ファイル>
        Claude が決めた振り分け先を inbox.json の各項目に書く。画面はそれを「AIの提案」として出す
        JSON は [{"id", "projectId", "parentId", "newParent", "breakdown", "ref", "reason"}, ...]。
        合う親タスクが無いときは parentId を空にして、newParent に新しく作る親タスク名を入れる。
        項目そのものが親タスク級なら、breakdown にサブタスク案 [{"title", "estimate"}] を入れ、
        ref に参考にした過去のタスク名を入れる（このとき parentId・newParent は使わない）

書き込むのは inbox.json だけ。tasks.json への取り込みは画面（index.html）がやる。
"""
import argparse
import datetime
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
INBOX = ROOT / 'inbox.json'
TASKS = ROOT / 'tasks.json'
KEEP = 500
HISTORY = 40      # 分解の参考に渡す、サブタスクを持つ過去の親タスクの数
MAX_SUBS = 12
HEADS = {'タスク', 'たすく', 'task'}
BULLET = re.compile(r'^\s*(?:[-*・•●]|\d+[.)．])\s*')
MSG = re.compile(r'^=== Message from .*? ===\s*$', re.M)
TS = re.compile(r'^Message TS:\s*([0-9.]+)\s*$', re.M)


def load():
    if not INBOX.exists():
        return {'lastTs': '', 'items': []}
    with open(INBOX, encoding='utf-8') as fh:
        doc = json.load(fh)
    doc.setdefault('lastTs', '')
    doc.setdefault('items', [])
    return doc


def save(doc):
    tmp = INBOX.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, INBOX)


def read_text(path):
    """ツール結果の保存ファイル（{"messages": "..."}）でも、本文そのままでも読む"""
    raw = pathlib.Path(path).read_text(encoding='utf-8')
    try:
        doc = json.loads(raw)
        if isinstance(doc, dict) and isinstance(doc.get('messages'), str):
            return doc['messages']
    except json.JSONDecodeError:
        pass
    return raw


def messages(text):
    """slack_read_channel（detailed）の出力を (ts, 本文) に分ける"""
    parts = MSG.split(text)
    for body in parts[1:]:
        m = TS.search(body)
        if not m:
            continue
        rest = body[m.end():]
        # 添付やリアクションの行は本文ではない
        lines = [ln for ln in rest.split('\n')
                 if not re.match(r'^(Files|Reactions|Thread|Replies):', ln)]
        yield m.group(1), '\n'.join(lines).strip()


def tasks_in(text):
    lines = [ln.strip() for ln in text.split('\n')]
    lines = [ln for ln in lines if ln]
    if not lines:
        return []
    head = lines[0].rstrip(':：').strip().lower()
    if head not in HEADS:
        return []
    out = []
    for ln in lines[1:]:
        t = BULLET.sub('', ln).strip()
        if t:
            out.append(t)
    return out


def cmd_since(_a):
    print(load()['lastTs'] or '')


def cmd_ingest(a):
    doc = load()
    have = {x['id'] for x in doc['items']}
    added = []
    for f in a.files:
        for ts, body in messages(read_text(f)):
            for i, title in enumerate(tasks_in(body)):
                iid = f'slack-{ts}-{i}'
                if iid in have:
                    continue
                when = datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc)
                doc['items'].append({'id': iid, 'title': title, 'src': 'slack',
                                     'receivedAt': when.isoformat().replace('+00:00', 'Z')})
                have.add(iid)
                added.append(title)
            if float(ts) > float(doc['lastTs'] or 0):
                doc['lastTs'] = ts
    doc['items'] = sorted(doc['items'], key=lambda x: x['id'])[-KEEP:]
    save(doc)
    json.dump({'added': added, 'lastTs': doc['lastTs']}, sys.stdout, ensure_ascii=False)
    print()


def load_board():
    """tasks.json は画面のもの。読むだけで書かない"""
    if not TASKS.exists():
        return {'projects': [], 'tasks': [], 'inbox': [], 'inboxSeen': []}
    with open(TASKS, encoding='utf-8') as fh:
        return json.load(fh)


def cmd_pending(_a):
    doc, board = load(), load_board()
    # 画面の inbox に残っているもの、またはまだ画面に取り込まれていないものだけ。振り分け済みには要らない
    left = {x.get('id') for x in board.get('inbox', [])}
    seen = set(board.get('inboxSeen', []))
    items = [{'id': x['id'], 'title': x['title']} for x in doc['items']
             if not x.get('suggest') and (x['id'] in left or x['id'] not in seen)]
    projects = []
    for p in board.get('projects', []):
        tasks = [{'id': t['id'], 'title': t.get('title', ''), 'status': t.get('status', ''),
                  'subtasks': [k.get('title', '') for k in t.get('subtasks', [])][-5:]}
                 for t in board.get('tasks', [])
                 if t.get('projectId') == p['id'] and t.get('status') != 'done']
        projects.append({'id': p['id'], 'name': p.get('name', ''), 'tasks': tasks})
    # 分解の参考。完了したものも含め、サブタスクを2件以上持つ親タスクを新しい順に
    names = {p['id']: p.get('name', '') for p in board.get('projects', [])}
    past = sorted((t for t in board.get('tasks', []) if len(t.get('subtasks', [])) >= 2),
                  key=lambda t: t.get('createdAt') or '', reverse=True)[:HISTORY]
    history = [{'title': t.get('title', ''), 'project': names.get(t.get('projectId'), ''),
                'subtasks': [{'title': k.get('title', ''), 'estimate': k.get('estimate')} for k in t['subtasks']]}
               for t in past]
    json.dump({'items': items, 'projects': projects, 'history': history}, sys.stdout, ensure_ascii=False, indent=1)
    print()


def hours(v):
    try:
        h = float(v)
    except (TypeError, ValueError):
        return None
    return h if 0 < h <= 100 else None


def cmd_suggest(a):
    doc, board = load(), load_board()
    projects = {p['id'] for p in board.get('projects', [])}
    parents = {t['id']: t.get('projectId') for t in board.get('tasks', []) if t.get('status') != 'done'}
    with open(a.file, encoding='utf-8') as fh:
        picks = {x.get('id'): x for x in json.load(fh) if isinstance(x, dict)}
    done, skipped = [], []
    for it in doc['items']:
        s = picks.pop(it['id'], None)
        if s is None:
            continue
        pid = s.get('projectId') or ''
        if pid not in projects:
            skipped.append(f"{it['title']}（プロジェクトが無い）")
            continue
        subs = [{'title': str(k.get('title', '')).strip(), 'estimate': hours(k.get('estimate'))}
                for k in (s.get('breakdown') or []) if isinstance(k, dict) and str(k.get('title', '')).strip()][:MAX_SUBS]
        parent = '' if subs else (s.get('parentId') or '')
        if parents.get(parent) != pid:
            parent = ''
        it['suggest'] = {'pid': pid, 'parent': parent,
                         'newParent': '' if parent or subs else (s.get('newParent') or '').strip(),
                         'breakdown': subs, 'ref': (s.get('ref') or '').strip() if subs else '',
                         'reason': (s.get('reason') or '').strip(),
                         'at': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')}
        done.append(it['title'])
    skipped += [f"{k}（inbox に無い）" for k in picks]
    save(doc)
    json.dump({'suggested': done, 'skipped': skipped}, sys.stdout, ensure_ascii=False)
    print()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('since')
    p = sub.add_parser('ingest')
    p.add_argument('files', nargs='+')
    sub.add_parser('pending')
    p = sub.add_parser('suggest')
    p.add_argument('file')
    a = ap.parse_args()
    {'since': cmd_since, 'ingest': cmd_ingest, 'pending': cmd_pending, 'suggest': cmd_suggest}[a.cmd](a)


if __name__ == '__main__':
    main()
