#!/usr/bin/env python3
"""
taskboard と Google カレンダーの同期を手伝う。カレンダー API は叩かない。
叩くのは Claude（カレンダー MCP）で、このスクリプトは「何をすべきか」を出すのと、
結果を calendar.json に記録するだけ。

    python calendar_sync.py plan
        tasks.json と calendar.json を突き合わせ、カレンダーへの操作を JSON で出す
    python calendar_sync.py link <taskId> <eventId> <date> <start> <end> [<title>]
        予定を作った・動かした結果を記録する（title は ops の title をそのまま）
        ※ op が move_event（ボードで動かした自分だけの予定）のときは記録は要らない。次の ingest で反映される
    python calendar_sync.py unlink <taskId>
        予定を消した結果を記録する
    python calendar_sync.py ingest <list_events の出力.json ...> --from YYYY-MM-DD --to YYYY-MM-DD
        カレンダーの予定を取り込む。会議は events に入れ、タスクの予定が
        カレンダー側で動いた・消えたことを links に写す

書き込むのは calendar.json だけ。tasks.json は画面（index.html）が書き手なので、
ここからは読むだけにする（開いている画面と上書きし合わないため）。
"""
import argparse
import datetime
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
TASKS = ROOT / 'tasks.json'
CAL = ROOT / 'calendar.json'
JST = datetime.timezone(datetime.timedelta(hours=9))
MARK = 'taskboard:'
DEFAULT_H = 0.5   # 工数が空のときの長さ。画面の WK_DEFAULT_H と同じ


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def load(path, default):
    if not path.exists():
        return default
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def save_cal(cal):
    tmp = CAL.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        json.dump(cal, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CAL)


def load_cal():
    cal = load(CAL, {})
    cal.setdefault('links', {})
    cal.setdefault('events', [])
    return cal


def ts(s):
    if not s:
        return 0.0
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def task_hours(t):
    """index.html の taskHours と同じ。サブタスクがあればその合計。未設定なら 30分"""
    subs = t.get('subtasks') or []
    if subs:
        h = sum(s.get('estimate') or 0 for s in subs)
    else:
        h = t.get('estimate') or 0
    return h if h > 0 else DEFAULT_H


def end_at(start, hours):
    h, m = map(int, start.split(':'))
    e = min(h * 60 + m + round(hours * 60), 24 * 60 - 1)
    return f'{e // 60:02d}:{e % 60:02d}'


def units(data):
    """カレンダーに置く単位。タスクとサブタスクの両方（画面の allUnits と同じ）。
       返すのは (id, 予定名, schedule, 工数h, 完了か, 親タスク)"""
    for t in data.get('tasks', []):
        done = t.get('status') == 'done'
        yield t['id'], t.get('title', ''), t.get('schedule'), task_hours(t), done, t
        for k in t.get('subtasks') or []:
            # サブタスクは名前だけだと何の作業か分からないので、親の名前を前に付ける
            title = f"{t.get('title', '')}_{k.get('title', '')}"
            yield (k['id'], title, k.get('schedule'), k.get('estimate') or DEFAULT_H,
                   done or bool(k.get('done')), t)


def iso_jst(date, hm):
    return f'{date}T{hm}:00+09:00'


def cmd_plan(_a):
    data = load(TASKS, {'tasks': [], 'projects': []})
    cal = load_cal()
    links = cal['links']
    projects = {p['id']: p.get('name', '') for p in data.get('projects', [])}
    ops = []
    ids = set()
    for uid, title, s, hours, done, t in units(data):
        ids.add(uid)
        L = links.get(uid)
        live = L and not L.get('gone')
        if not s:
            if live:
                ops.append({'op': 'delete', 'taskId': uid, 'eventId': L['eventId'], 'title': title})
            continue
        want = {'date': s['date'], 'start': s['start'], 'end': end_at(s['start'], hours)}
        common = {'taskId': uid, 'title': title, **want,
                  'startTime': iso_jst(want['date'], want['start']),
                  'endTime': iso_jst(want['date'], want['end']),
                  'description': f"{MARK}{uid}\n{projects.get(t.get('projectId'), '')}"}
        if not live:
            # 完了済みで一度もカレンダーに載っていないものは、いまさら作らない
            if not done:
                ops.append({'op': 'create', **common})
            continue
        # 名前が変わった（タスク名の変更、または予定名の付け方の変更）
        renamed = L.get('title') is not None and L.get('title') != title
        if ts(s.get('setAt')) > ts(L.get('syncedAt')):
            # 画面で動かした方が新しい → 画面の時刻で上書き
            if renamed or (L.get('date'), L.get('start'), L.get('end')) != (want['date'], want['start'], want['end']):
                ops.append({'op': 'update', 'eventId': L['eventId'], **common})
            continue
        # カレンダー側の方が新しい（画面がまだ取り込んでいない）。日時はカレンダーに従い、
        # 長さだけ工数に合わせる
        end2 = end_at(L['start'], hours)
        if renamed or L.get('end') != end2:
            ops.append({'op': 'update', 'eventId': L['eventId'], **common,
                        'date': L['date'], 'start': L['start'], 'end': end2,
                        'startTime': iso_jst(L['date'], L['start']),
                        'endTime': iso_jst(L['date'], end2)})
    for tid, L in links.items():
        if tid not in ids and not L.get('gone'):
            ops.append({'op': 'delete', 'taskId': tid, 'eventId': L['eventId'], 'title': '（削除済みタスク）'})
    # ボードで動かした「自分だけの予定」。calendar.json の時刻と違えば動かす
    evs = {e.get('id'): e for e in cal.get('events', []) if e.get('id')}
    for eid, mv in (data.get('eventMoves') or {}).items():
        e = evs.get(eid)
        if not e or not e.get('movable'):
            continue
        want_s, want_e = iso_jst(mv['date'], mv['start']), iso_jst(mv['date'], mv['end'])
        cur_s = datetime.datetime.fromisoformat(e['start']).astimezone(JST).strftime('%Y-%m-%dT%H:%M')
        if cur_s != f"{mv['date']}T{mv['start']}":
            ops.append({'op': 'move_event', 'eventId': eid, 'title': e.get('title', ''),
                        'startTime': want_s, 'endTime': want_e})
    json.dump({'ops': ops}, sys.stdout, ensure_ascii=False, indent=2)
    print()


def cmd_link(a):
    cal = load_cal()
    cal['links'][a.taskId] = {'eventId': a.eventId, 'date': a.date, 'start': a.start,
                              'end': a.end, 'syncedAt': now_iso()}
    if a.title is not None:
        cal['links'][a.taskId]['title'] = a.title
    save_cal(cal)
    print('linked', a.taskId)


def cmd_unlink(a):
    cal = load_cal()
    cal['links'].pop(a.taskId, None)
    save_cal(cal)
    print('unlinked', a.taskId)


def parse_when(w):
    """list_events の start/end を (datetime JST, 終日か) にする"""
    if 'dateTime' in w:
        return datetime.datetime.fromisoformat(w['dateTime']).astimezone(JST), False
    d = w.get('date', '')[:10]
    return datetime.datetime.fromisoformat(d).replace(tzinfo=JST), True


def movable(e):
    """ボードから動かしてよい予定か。自分が作り、参加者が自分しかいないものだけ。
       参加者がいる会議を動かすと相手のカレンダーも変わり、通知も飛ぶため対象外にする"""
    if not (e.get('organizer') or {}).get('self'):
        return False
    others = [a for a in e.get('attendees') or [] if not a.get('self') and not a.get('resource')]
    return not others


def my_response(e):
    for at in e.get('attendees') or []:
        if at.get('self'):
            return at.get('responseStatus')
    return 'organizer'


def in_ranges(date, ranges):
    return any(r['from'] <= date <= r['to'] for r in ranges)


def cmd_ingest(a):
    # 取り込む範囲。--from/--to（1つ）か --range FROM:TO（いくつでも）
    ranges = [{'from': a.date_from, 'to': a.date_to}] if a.date_from and a.date_to else []
    for r in a.ranges or []:
        f, t = r.split(':')
        ranges.append({'from': f, 'to': t})
    if not ranges:
        sys.exit('取り込む範囲がありません（--from/--to か --range）')
    raw = []
    for f in a.files:
        with open(f, encoding='utf-8') as fh:
            doc = json.load(fh)
        raw.extend(doc.get('events', []) if isinstance(doc, dict) else doc)
    cal = load_cal()
    links = cal['links']
    by_event = {L['eventId']: tid for tid, L in links.items() if not L.get('gone')}
    seen = set()
    events = []
    for e in raw:
        if e.get('status') == 'cancelled' or 'start' not in e:
            continue
        tid = by_event.get(e.get('id'))
        if tid is None and MARK in (e.get('description') or ''):
            # リンクを失った taskboard の予定。会議として出すと二重になるので捨てる
            continue
        s, all_day = parse_when(e['start'])
        en, _ = parse_when(e['end'])
        if tid is not None:
            seen.add(e['id'])
            L = links[tid]
            date, start, end = s.strftime('%Y-%m-%d'), s.strftime('%H:%M'), en.strftime('%H:%M')
            if (L['date'], L['start'], L['end']) != (date, start, end):
                L.update({'date': date, 'start': start, 'end': end, 'syncedAt': now_iso()})
            continue
        if my_response(e) == 'declined' or e.get('transparency') == 'transparent':
            continue
        if all_day:
            events.append({'title': e.get('summary', '（無題）'), 'allDay': True,
                           'start': s.strftime('%Y-%m-%d'), 'end': en.strftime('%Y-%m-%d')})
        else:
            events.append({'id': e.get('id'), 'title': e.get('summary', '（無題）'), 'allDay': False,
                           'start': s.isoformat(), 'end': en.isoformat(), 'movable': movable(e),
                           'colorId': e.get('colorId')})   # Google カレンダーで付けた色（無ければカレンダーの既定色）
    # 取り込んだ範囲に居るはずなのに見つからない予定は、カレンダー側で消されたもの。
    # 報告するのは今回新たに消えたものだけ（前回までに報告済みのものは繰り返さない）
    gone = []
    for tid, L in links.items():
        if L.get('gone') or L['eventId'] in seen:
            continue
        if in_ranges(L['date'], ranges):
            L.update({'gone': True, 'syncedAt': now_iso()})
            gone.append(tid)
    # 今回の範囲の外にある前回までの予定は残す（見ている週を足していくため）。
    # ただし4週間より前のものは捨てる
    old_limit = (datetime.datetime.now(JST) - datetime.timedelta(days=28)).strftime('%Y-%m-%d')
    keep = [e for e in cal.get('events', []) if e['start'][:10] >= old_limit and not in_ranges(e['start'][:10], ranges)]
    events = sorted(keep + events, key=lambda x: x['start'])
    cal['events'] = events
    prev = cal.get('ranges') or ([cal['range']] if cal.get('range') else [])
    merged = [r for r in prev if r['to'] >= old_limit] + ranges
    cal['ranges'] = merged
    cal['range'] = ranges[0]   # 古い画面向けに残す
    cal['syncedAt'] = now_iso()
    save_cal(cal)
    print(json.dumps({'events': len(events), 'raw': len(raw), 'gone': gone}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('plan')
    p = sub.add_parser('link')
    for k in ('taskId', 'eventId', 'date', 'start', 'end'):
        p.add_argument(k)
    p.add_argument('title', nargs='?', default=None)   # 予定名。次に名前が変わったら update を出すため
    p = sub.add_parser('unlink')
    p.add_argument('taskId')
    p = sub.add_parser('ingest')
    p.add_argument('files', nargs='+')
    p.add_argument('--from', dest='date_from')
    p.add_argument('--to', dest='date_to')
    p.add_argument('--range', dest='ranges', action='append', help='FROM:TO（YYYY-MM-DD:YYYY-MM-DD）。複数可')
    a = ap.parse_args()
    {'plan': cmd_plan, 'link': cmd_link, 'unlink': cmd_unlink, 'ingest': cmd_ingest}[a.cmd](a)


if __name__ == '__main__':
    main()
