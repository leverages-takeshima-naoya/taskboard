#!/usr/bin/env python3
"""
Slack リストの JSON エクスポートを taskboard の tasks.json に変換する。

    python import_slack_list.py <export.json> [-o tasks.json] [--merge]

対応づけ（2026-09-03 に決めたもの）:
    領域(select)        -> プロジェクト
    ステータス(select)  -> セクション。タスクの status にも同じ値を入れる
    名前(text)          -> タイトル
    完了済み(checkbox)  -> サブタスクの done。親は status で表す
    期限日(date)        -> 期日（親・子とも）
    アウトプット(text)  -> URL なら参照リンク、そうでなければメモ
    子レコード          -> サブタスク（期日つき）

除外するもの:
    - 「▼」で始まる見出し行（タスクではなく区切り）
    - タイトルが空のレコード
"""
import argparse, json, pathlib, sys, unicodedata

# ステータスのラベル -> taskboard の status 値
STATUS_VALUE = {
    '未着手': 'todo',
    'タスク化': 'ticketed',
    '進行中': 'doing',
    'リリース待ち': 'release',
    '完了': 'done',
}
FALLBACK_PROJECT = 'その他'
# 画面側が扱える色名（index.html の COLORS と揃える）
COLORS = {'gray', 'brown', 'orange', 'yellow', 'green', 'cyan',
          'blue', 'indigo', 'purple', 'pink', 'red'}


def slug(text, used):
    """日本語をそのまま id に使えないので、安定した英数 id を作る。"""
    base = ''.join(
        c if c.isascii() and (c.isalnum() or c == '_') else '%02x' % (ord(c) % 256)
        for c in unicodedata.normalize('NFKC', text)
    )[:24] or 'x'
    out, n = base, 2
    while out in used:
        out, n = f'{base}{n}', n + 1
    used.add(out)
    return out


def color_map(export):
    """選択肢のラベル -> Slack が付けている色名。画面の見出しの色に使う。"""
    out = {}
    for c in export['columns']:
        if c['type'] != 'select':
            continue
        for ch in c.get('options', {}).get('choices', []):
            if ch.get('color') in COLORS:
                out[ch['label']] = ch['color']
    return out


def build_reader(export):
    """列定義から、レコードを素直な dict に開くための関数を作る。"""
    cols = {c['id']: c for c in export['columns']}
    opts = {
        ch['value']: ch['label']
        for c in export['columns'] if c['type'] == 'select'
        for ch in c['options']['choices']
    }

    def read(record):
        out = {}
        for f in record['fields']:
            col = cols.get(f['column_id'])
            if not col:
                continue
            name, kind = col['name'], col['type']
            if kind == 'text':
                out[name] = (f.get('text') or '').strip()
                urls = [
                    el['url']
                    for blk in (f.get('rich_text') or [])
                    for sec in blk.get('elements', [])
                    for el in sec.get('elements', [])
                    if el.get('type') == 'link'
                ]
                if urls:
                    out[name + '::url'] = urls[0]
            elif kind == 'select':
                labels = [opts.get(v, '') for v in (f.get('select') or [])]
                out[name] = next((x for x in labels if x), '')
            elif kind == 'todo_completed':
                out[name] = bool(f.get('checkbox'))
            elif kind == 'todo_due_date':
                dates = f.get('date') or []
                out[name] = dates[0] if dates else ''
        return out

    return read


def is_divider(title):
    return title.lstrip().startswith(('▼', '▽', '■', '□', '---'))


def convert(export, existing=None):
    read = build_reader(export)
    tint = color_map(export)
    state = existing or {'version': 1, 'projects': [], 'tasks': []}
    projects = {p['name']: p for p in state['projects']}
    used_ids = {p['id'] for p in state['projects']}
    used_ids |= {s['id'] for p in state['projects'] for s in p['sections']}
    used_ids |= {t['id'] for t in state['tasks']}

    skipped, order = [], {}

    # Slack の並び順を保つ
    records = sorted(export['records'], key=lambda n: float(n['record'].get('position') or 0))

    for node in records:
        rec = node['record']
        F = read(rec)
        title = F.get('名前', '')

        if not title:
            skipped.append(('タイトルが空', rec['id']))
            continue
        if is_divider(title):
            skipped.append(('見出し行', title))
            continue

        pname = F.get('領域') or FALLBACK_PROJECT
        proj = projects.get(pname)
        if proj is None:
            proj = {'id': 'p_' + slug(pname, used_ids), 'name': pname,
                    'color': tint.get(pname, ''), 'sections': []}
            projects[pname] = proj
            state['projects'].append(proj)
        elif not proj.get('color') and tint.get(pname):
            proj['color'] = tint[pname]

        # セクションは Slack のステータス選択肢の順に並べる
        sname = F.get('ステータス') or '未着手'
        sec = next((s for s in proj['sections'] if s['name'] == sname), None)
        if sec is None:
            sec = {'id': 's_' + slug(f'{pname}_{sname}', used_ids), 'name': sname,
                   'color': tint.get(sname, '')}
            proj['sections'].append(sec)
            proj['sections'].sort(
                key=lambda s: list(STATUS_VALUE).index(s['name'])
                if s['name'] in STATUS_VALUE else 99
            )

        out_text = F.get('アウトプット', '')
        out_url = F.get('アウトプット::url', '')
        # 貼っただけの URL は rich_text のリンク要素にならないことがある
        if not out_url and out_text.startswith(('http://', 'https://')) and ' ' not in out_text:
            out_url = out_text

        subtasks = []
        for child in node.get('children') or []:
            cf = read(child['record'])
            ctitle = cf.get('名前', '')
            if not ctitle:
                skipped.append(('サブタスクのタイトルが空', child['record']['id']))
                continue
            subtasks.append({
                'id': 'k_' + slug(ctitle, used_ids),
                'title': ctitle,
                'done': bool(cf.get('完了済み')),
                'due': cf.get('期限日', ''),
            })

        # Slack は子レコードを、意図した工程順とは逆に返してくることが多い
        # （2026-09-04 に実データで確認し、本人の指示で逆順に揃えた）
        subtasks.reverse()

        key = (proj['id'], sec['id'])
        order[key] = order.get(key, 0) + 1000
        status = STATUS_VALUE.get(sname, 'todo')

        state['tasks'].append({
            'id': 't_' + slug(title, used_ids),
            'projectId': proj['id'],
            'sectionId': sec['id'],
            'title': title,
            # URL でないアウトプット（Slack のファイル ID や資料名）はメモに残す
            'notes': '' if (out_url or not out_text) else f'アウトプット: {out_text}',
            'status': status,
            'priority': '',                      # Slack リストに優先度列はない
            'due': F.get('期限日', ''),
            'url': out_url,
            'subtasks': subtasks,
            'createdAt': __import__('datetime').datetime.fromtimestamp(
                rec['date_created'], __import__('datetime').timezone.utc
            ).isoformat().replace('+00:00', 'Z'),
            'completedAt': None,
            'order': order[key],
        })

    return state, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source', type=pathlib.Path)
    ap.add_argument('-o', '--out', type=pathlib.Path,
                    default=pathlib.Path(__file__).with_name('tasks.json'))
    ap.add_argument('--merge', action='store_true',
                    help='既存の tasks.json に追記する（既定は置き換え）')
    a = ap.parse_args()

    export = json.loads(a.source.read_text(encoding='utf-8'))
    meta = export.get('meta', {})
    for flag, label in [('records_truncated', 'レコード'),
                        ('max_subtask_depth_exceeded', 'サブタスクの深さ')]:
        if meta.get(flag):
            print(f'警告: {label}が切り詰められたエクスポートです', file=sys.stderr)

    existing = None
    if a.merge and a.out.exists():
        existing = json.loads(a.out.read_text(encoding='utf-8'))

    state, skipped = convert(export, existing)
    state['version'] = 1
    # ブラウザ側と同じ UTC の 'Z' 形式にそろえる（比較が狂わないように）
    state['updatedAt'] = __import__('datetime').datetime.now(
        __import__('datetime').timezone.utc).isoformat().replace('+00:00', 'Z')
    a.out.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

    subs = sum(len(t['subtasks']) for t in state['tasks'])
    print(f'{a.out} に書き出しました')
    print(f'  プロジェクト {len(state["projects"])} / タスク {len(state["tasks"])} / サブタスク {subs}')
    for p in state['projects']:
        n = sum(1 for t in state['tasks'] if t['projectId'] == p['id'])
        print(f'    {p["name"]:<8} {n:>3} 件   セクション: ' +
              ' / '.join(f'{s["name"]}' for s in p['sections']))
    if skipped:
        print('  除外:')
        for why, what in skipped:
            print(f'    [{why}] {what}')


if __name__ == '__main__':
    main()
