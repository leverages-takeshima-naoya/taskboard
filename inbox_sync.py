#!/usr/bin/env python3
"""
Slack の自分宛てDMから、taskboard の inbox に入れるタスクを拾う。Slack は叩かない。
読むのは Claude（Slack MCP の slack_read_channel）で、このスクリプトはその出力を
解釈して inbox.json に足すだけ。

    python inbox_sync.py since
        前回どこまで読んだか（Slack の ts）を出す。slack_read_channel の oldest に渡す
    python inbox_sync.py ingest <slack_read_channel の出力ファイル ...>
        「タスク」で始まるメッセージの2行目以降を、1行1件で inbox.json に足す

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
KEEP = 500
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


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('since')
    p = sub.add_parser('ingest')
    p.add_argument('files', nargs='+')
    a = ap.parse_args()
    {'since': cmd_since, 'ingest': cmd_ingest}[a.cmd](a)


if __name__ == '__main__':
    main()
