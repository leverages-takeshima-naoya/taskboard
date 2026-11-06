#!/usr/bin/env python3
"""
Slack の自分宛てDMから、taskboard の inbox に入れるタスクを拾う。Slack は叩かない。
読むのは Claude（Slack MCP の slack_read_channel）で、このスクリプトはその出力を
解釈して inbox.json に足すだけ。

    python inbox_sync.py since
        前回どこまで読んだか（Slack の ts）を出す。slack_read_channel の oldest に渡す
    python inbox_sync.py ingest <slack_read_channel の出力ファイル ...>
        「タスク」で始まるメッセージの2行目以降を、1行1件で inbox.json に足す。
        リンクだけの行は直前のタスクのリンクにする。転送したメッセージ（Forwarded message from 〜）より後は読まない
    python inbox_sync.py pending
        振り分け先の提案がまだ無い inbox の項目と、振り分け先の候補（プロジェクトと未完了の親タスク）を出す
    python inbox_sync.py suggest <提案の JSON ファイル>
        Claude が決めた振り分け先を inbox.json の各項目に書く。画面はそれを「AIの提案」として出す
        JSON は [{"id", "projectId", "parentId", "newParent", "breakdown", "ref", "reason"}, ...]。
        合う親タスクが無いときは parentId を空にして、newParent に新しく作る親タスク名を入れる。
        項目そのものが親タスク級なら、breakdown にサブタスク案 [{"title", "estimate"}] を入れ、
        ref に参考にした過去のタスク名を入れる（このとき parentId・newParent は使わない）

Slack で自分に来た依頼（DM・メンション）も拾う。読むのは Claude（slack_search_public_and_private）:

    python inbox_sync.py intake-since
        前回どこまで見たか（UNIX 秒）を出す。検索の after に渡す。空なら今日の 0:00 JST
    python inbox_sync.py intake-parse <検索結果のファイル ...>
        自分の発言・自分宛てDM・見たことのあるものを除いて、判定する候補を出す。
        渡した検索結果の中の自分の発言（from:自分 の検索）と突き合わせ、依頼のあとに自分が返信していれば
        その文を myReply に入れる。返信で済んだかは Claude が判定する。
        inbox に入ったあとで返信した依頼も、返信の文と一緒に later に出す
    python inbox_sync.py intake-add <判定の JSON ファイル>
        JSON は {"add": [{"id", "title", "due"}, ...], "done": [id, ...]}。
        add は対応が要ると判定した候補。title は依頼の要約、due は依頼文から読んだ期日（YYYY-MM-DD、無ければ空）。
        done は later のうち、返信で済んだと判定したもの。画面に「返信済み」と出る。
        候補に出したものは入れなかった分も「見た」ことにして、次から出さない。
        add には summary（依頼の中身を2〜3文で）と context（スレッドの前後の発言
        [{"from", "when", "text", "me"}]）も入れられる。詳細の「概要」に出す

依頼の詳細で「方針を出して」を押したときや、コメントを書いたときに Claude が使う（taskboard-plan スキル）:

    python inbox_sync.py plan-get <id>
        依頼の中身・スレッドの前後・これまでの方針・竹島のコメントを出す。
        コメントは画面から server.py 経由で sync_tmp/plan-<id>.json に置かれたものを読む
    python inbox_sync.py plan-set <方針の JSON ファイル>
        JSON は {"id", "plan", "questions": [...], "reply"}。項目の plans に1件足す。画面は最新を方針・返信案として出す

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
LINK_ONLY = re.compile(r'^<?(https?://[^\s|>]+)(?:\|[^>]*)?>?$')
FORWARD = re.compile(r'^Forwarded message from ')
MSG = re.compile(r'^=== Message from .*? ===\s*$', re.M)
TS = re.compile(r'^Message TS:\s*([0-9.]+)\s*$', re.M)

ME = 'U068JL21GMP'
SELF_DM = 'D06861H4RNW'   # 自分宛てDM。ここは「タスク」メモの ingest が見る
CAND = ROOT / 'sync_tmp' / 'intake_candidates.json'
SEEN_KEEP = 2000
QUOTE = 300               # カードに残す元メッセージの長さ
CONTEXT_KEEP, CONTEXT_LEN = 12, 600   # 概要に残すスレッドの前後の件数と、1件の長さ
PLANS_KEEP = 20           # 1件の依頼に残す方針の数（すり合わせのたびに増える）
JST = datetime.timezone(datetime.timedelta(hours=9))
RESULT = re.compile(r'^### Result \d+ of \d+\s*$', re.M)
FIELD = {
    'channel': re.compile(r'^Channel:\s*(.*?)\s*\(ID:\s*(\w+)\)', re.M),
    'from': re.compile(r'^From:\s*(.*?)\s*(?:<[^>]*>\s*)?\(ID:\s*(\w+)\)', re.M),
    'ts': re.compile(r'^Message_ts:\s*([0-9.]+)', re.M),
    'url': re.compile(r'^Permalink:\s*\[[^\]]*\]\((\S+?)\)', re.M),
}
MENTION = re.compile(r'<@\w+\|([^>]+)>')
THREAD = re.compile(r'[?&]thread_ts=([0-9.]+)')


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
    """ツール結果の保存ファイル（{"messages": "..."} や {"results": "..."}）でも、本文そのままでも読む"""
    raw = pathlib.Path(path).read_text(encoding='utf-8')
    try:
        doc = json.loads(raw)
        for k in ('messages', 'results'):
            if isinstance(doc, dict) and isinstance(doc.get(k), str):
                return doc[k]
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
        if FORWARD.match(ln):
            break
        t = BULLET.sub('', ln).strip()
        m = LINK_ONLY.match(t)
        if m:
            if out and not out[-1]['url']:
                out[-1]['url'] = m.group(1)
            continue
        if t:
            out.append({'title': t, 'url': ''})
    return out


def cmd_since(_a):
    print(load()['lastTs'] or '')


def cmd_ingest(a):
    doc = load()
    have = {x['id'] for x in doc['items']}
    added = []
    for f in a.files:
        for ts, body in messages(read_text(f)):
            for i, task in enumerate(tasks_in(body)):
                title = task['title']
                iid = f'slack-{ts}-{i}'
                if iid in have:
                    continue
                when = datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc)
                item = {'id': iid, 'title': title, 'src': 'slack',
                        'receivedAt': when.isoformat().replace('+00:00', 'Z')}
                if task['url']:
                    item['url'] = task['url']
                doc['items'].append(item)
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


def search_hits(text):
    """slack_search_public_and_private（detailed）の出力を1件ずつの dict に分ける"""
    for body in RESULT.split(text)[1:]:
        body = body.rsplit('\n---', 1)[0]
        got = {k: rx.search(body) for k, rx in FIELD.items()}
        if not (got['channel'] and got['from'] and got['ts']):
            continue
        _, _, msg = body.partition('\nText:')
        from_line = body[got['from'].start():].split('\n', 1)[0]
        yield {'ts': got['ts'].group(1), 'bot': '[BOT]' in from_line or got['from'].group(2) == 'USLACK',
               'chName': got['channel'].group(1), 'ch': got['channel'].group(2),
               'from': got['from'].group(1), 'fromId': got['from'].group(2),
               'url': got['url'].group(1) if got['url'] else '',
               'text': MENTION.sub(r'@\1', msg).strip()}


def cmd_intake_since(_a):
    ts = load().get('intakeTs', '')
    if not ts:
        today = datetime.datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
        ts = str(int(today.timestamp()))
    print(ts)


def thread_of(ts, url):
    """スレッドの親の ts。スレッドの外の発言なら空"""
    m = THREAD.search(url or '')
    return m.group(1) if m else ''


def replied(ch, ts, url, dm, mine):
    """依頼より後に、同じスレッド（スレッドの外の DM なら同じ会話）で自分が発言していれば、その最後の文"""
    root = thread_of(ts, url) or ts
    last = ''
    for m in sorted(mine, key=lambda m: float(m['ts'])):
        if m['ch'] != ch or float(m['ts']) <= float(ts):
            continue
        t = thread_of(m['ts'], m['url'])
        if t == root or (dm and not thread_of(ts, url) and not t):
            last = m['text'] or '（スタンプ・添付のみ）'
    return last


def cmd_intake_parse(a):
    doc = load()
    skip = set(doc.get('intakeSeen', [])) | {x['id'] for x in doc['items']}
    hits = [h for f in a.files for h in search_hits(read_text(f))]
    mine = [h for h in hits if h['fromId'] == ME]
    out, have = [], set()
    for h in hits:
        iid = f"intake-{h['ch']}-{h['ts']}"
        # bot は include_bots=false でも DM の検索に混ざる。本文が空のもの（Slack 本体の通知など）も読めない
        if (h['fromId'] == ME or h['ch'] == SELF_DM or h['bot'] or not h['text']
                or iid in skip or iid in have):
            continue
        have.add(iid)
        when = datetime.datetime.fromtimestamp(float(h['ts']), JST)
        out.append({'id': iid, 'when': when.strftime('%m/%d %H:%M'), **h,
                    'myReply': replied(h['ch'], h['ts'], h['url'], not h['chName'].startswith('#'), mine)})
    out.sort(key=lambda x: float(x['ts']))
    # inbox に入れたあとで返信したもの。画面が「返信済み」と出す
    later = []
    for x in doc['items']:
        if x.get('src') != 'intake' or x.get('replied'):
            continue
        r = replied(x['id'].split('-')[1], x['id'].split('-')[2], x.get('url'),
                    not x.get('chName', '').startswith('#'), mine)
        if r:
            later.append({'id': x['id'], 'title': x['title'], 'text': x.get('quote', ''), 'myReply': r})
    CAND.parent.mkdir(exist_ok=True)
    with open(CAND, 'w', encoding='utf-8') as fh:
        json.dump({'cands': out, 'later': later}, fh, ensure_ascii=False, indent=2)
    json.dump({'cands': [{k: x[k] for k in ('id', 'when', 'chName', 'from', 'url', 'text', 'myReply')} for x in out],
               'later': later}, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_intake_add(a):
    if not CAND.exists():
        sys.exit('候補がありません。先に intake-parse を実行してください')
    with open(CAND, encoding='utf-8') as fh:
        got = json.load(fh)
    cand = {x['id']: x for x in got['cands']}
    with open(a.file, encoding='utf-8') as fh:
        picks = json.load(fh)
    done = set()
    if isinstance(picks, dict):
        done = set(picks.get('done', [])) & {x['id'] for x in got['later']}
        picks = picks.get('add', [])
    doc = load()
    have = {x['id'] for x in doc['items']}
    added, unknown = [], []
    for p in picks:
        c = cand.get(p.get('id'))
        if not c:
            unknown.append(p.get('id'))
            continue
        if c['id'] in have or not str(p.get('title', '')).strip():
            continue
        due = p.get('due') or ''
        if due and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', due):
            due = ''
        when = datetime.datetime.fromtimestamp(float(c['ts']), datetime.timezone.utc)
        doc['items'].append({'id': c['id'], 'title': p['title'].strip(), 'src': 'intake',
                             'receivedAt': when.isoformat().replace('+00:00', 'Z'), 'due': due,
                             'from': c['from'], 'chName': c['chName'], 'url': c['url'],
                             'quote': c['text'][:QUOTE],
                             'summary': str(p.get('summary') or '').strip()[:400],
                             'context': context_of(p.get('context'))})
        have.add(c['id'])
        added.append(p['title'].strip())
    for x in doc['items']:
        if x['id'] in done:
            x['replied'] = True
    # 入れなかった候補も見たことにする。検索の after は指定時刻を含むので、id で二重を防ぐ
    seen = list(cand)
    doc['intakeSeen'] = (doc.get('intakeSeen', []) + seen)[-SEEN_KEEP:]
    if seen:
        top = max(float(x['ts']) for x in cand.values())
        doc['intakeTs'] = str(max(int(top), int(doc.get('intakeTs') or 0)))
    doc['items'] = sorted(doc['items'], key=lambda x: x.get('receivedAt', ''))[-KEEP:]
    save(doc)
    CAND.unlink()
    json.dump({'added': added, 'seen': len(seen), 'replied': len(done), 'unknown': unknown, 'intakeTs': doc.get('intakeTs', '')},
              sys.stdout, ensure_ascii=False)
    print()


def context_of(v):
    """スレッドの前後の発言を、決まった形に揃えて短くする"""
    out = []
    for m in (v if isinstance(v, list) else [])[-CONTEXT_KEEP:]:
        if isinstance(m, dict) and str(m.get('text', '')).strip():
            out.append({'from': str(m.get('from', ''))[:40], 'when': str(m.get('when', ''))[:20],
                        'text': str(m['text']).strip()[:CONTEXT_LEN], 'me': bool(m.get('me'))})
    return out


def plan_req(iid):
    """画面のコメント。server.py が sync_tmp/plan-<id>.json に置く"""
    path = ROOT / 'sync_tmp' / ('plan-' + re.sub(r'[^\w.-]', '_', iid) + '.json')
    try:
        with open(path, encoding='utf-8') as fh:
            got = json.load(fh)
        return got.get('talk') if isinstance(got.get('talk'), list) else []
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def cmd_plan_get(a):
    x = next((x for x in load()['items'] if x['id'] == a.id), None)
    if not x:
        sys.exit(f'inbox.json に {a.id} がありません')
    keys = ('id', 'title', 'summary', 'from', 'chName', 'url', 'receivedAt', 'due', 'quote', 'context', 'plans')
    out = {k: x.get(k, [] if k in ('context', 'plans') else '') for k in keys}
    json.dump({**out, 'talk': plan_req(a.id)}, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_plan_set(a):
    with open(a.file, encoding='utf-8') as fh:
        p = json.load(fh)
    doc = load()
    x = next((x for x in doc['items'] if x['id'] == p.get('id')), None)
    if not x:
        sys.exit(f'inbox.json に {p.get("id")} がありません')
    if not str(p.get('plan', '')).strip():
        sys.exit('plan が空です')
    qs = [str(q).strip() for q in (p.get('questions') or []) if str(q).strip()]
    entry = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
             'plan': str(p['plan']).strip(), 'questions': qs[:5], 'reply': str(p.get('reply') or '').strip()}
    x['plans'] = (x.get('plans', []) + [entry])[-PLANS_KEEP:]
    save(doc)
    json.dump({'id': x['id'], 'plans': len(x['plans']), 'questions': len(qs[:5]), 'reply': bool(entry['reply'])},
              sys.stdout, ensure_ascii=False)
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
    sub.add_parser('intake-since')
    p = sub.add_parser('intake-parse')
    p.add_argument('files', nargs='+')
    p = sub.add_parser('intake-add')
    p.add_argument('file')
    p = sub.add_parser('plan-get')
    p.add_argument('id')
    p = sub.add_parser('plan-set')
    p.add_argument('file')
    a = ap.parse_args()
    {'since': cmd_since, 'ingest': cmd_ingest, 'pending': cmd_pending, 'suggest': cmd_suggest,
     'intake-since': cmd_intake_since, 'intake-parse': cmd_intake_parse,
     'intake-add': cmd_intake_add, 'plan-get': cmd_plan_get, 'plan-set': cmd_plan_set}[a.cmd](a)


if __name__ == '__main__':
    main()
