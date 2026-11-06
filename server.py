#!/usr/bin/env python3
"""
task backlog のローカルサーバー。

画面を配るだけでなく、保存も引き受ける。ブラウザのファイル書き込み許可
（File System Access API）が要らなくなるのはこのため。ページは fetch で
POST するだけで、実際に tasks.json へ書くのはこちらの仕事になる。

    python server.py [--port 8777] [--no-browser]

127.0.0.1 にだけ待ち受ける。外部からは触れない。
書き込むのはこのフォルダの tasks.json と backups/ の中だけ。
ほかに、Claude に渡すもの（依頼の詳細に書いたコメント）を sync_tmp/ に置く。
"""
import argparse
import datetime
import http.server
import json
import os
import pathlib
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import time
import webbrowser

# ログイン時の自動起動は pythonw（ウィンドウなし）で動かす。そのとき標準出力が無く、
# アクセスのたびに出るログで落ちてしまうので、捨て先をつないでおく。
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / 'tasks.json'
BACKUPS = ROOT / 'backups'
BACKUP_EVERY = datetime.timedelta(hours=1)   # これより短い間隔では控えを増やさない
BACKUP_KEEP = 40
MAX_BODY = 32 * 1024 * 1024


def utc_now():
    """ブラウザ側と同じ UTC の 'Z' 形式で書く。
       ローカル時刻の '+09:00' 形式と混ざると、更新時刻の比較が狂う。"""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z')


def newest_backup():
    if not BACKUPS.is_dir():
        return None
    files = sorted(BACKUPS.glob('tasks-*.json'))
    return files[-1] if files else None


def rotate_backup():
    """保存のたびではなく、間隔を空けて控えを取る。古いものは捨てる。"""
    if not DATA.exists():
        return
    BACKUPS.mkdir(exist_ok=True)
    last = newest_backup()
    if last is not None:
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(last.stat().st_mtime)
        if age < BACKUP_EVERY:
            return
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    # copy2 は元ファイルの更新時刻まで複製するので、間隔の判定が常に成立して
    # 保存のたびに控えが増えてしまう。copyfile なら控え側は「今」になる。
    shutil.copyfile(DATA, BACKUPS / f'tasks-{stamp}.json')
    old = sorted(BACKUPS.glob('tasks-*.json'))[:-BACKUP_KEEP]
    for f in old:
        try:
            f.unlink()
        except OSError:
            pass


def write_atomic(payload):
    """一時ファイルに書いてから差し替える。
       途中で落ちても tasks.json が半端な状態にならないようにするため。"""
    tmp = DATA.with_suffix('.json.tmp')
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, DATA)


SKILLS = pathlib.Path.home() / '.claude' / 'skills'
COMMON_TOOLS = ['Skill', 'ToolSearch', 'Read', 'Write(./sync_tmp/**)', 'Edit(./sync_tmp/**)']


class Sync:
    """Claude Code（コマンド版）に taskboard の同期スキルを頼む。
       仕事（job）は3つ。auto はカレンダーと Slack で、タイマー（平日 10:00〜19:00 の30分ごと）と
       週ビューの「Claude で同期」ボタンから動く。mission と eval は各ページのボタンから動く。
       plan は inbox の依頼の詳細（「方針を出して」とコメント）から、依頼1件ずつ動く。
       同時に動くのは1本だけ。plan だけは、ほかが動いていれば順番待ちに並べて、終わったあとに回す。スキルごとに別の Claude を起動し、モデルはスキルの model: に従う。
       結果の文章は sync-<job>.log に残し、画面には先頭だけ返す。
       Claude に許すのは、そのスキルに要るツールだけ。"""
    lock = threading.Lock()
    TMP = ROOT / 'sync_tmp'
    JOBS = {'auto': ['calendar', 'slack'], 'mission': ['mission'], 'eval': ['eval'], 'plan': ['plan']}
    PARTS = {
        'calendar': {
            'skill': 'taskboard-calendar', 'ask': 'カレンダー同期をして。',
            'tools': ['Bash(python calendar_sync.py:*)',
                      'mcp__claude_ai_Google_Calendar__list_events', 'mcp__claude_ai_Google_Calendar__get_event',
                      'mcp__claude_ai_Google_Calendar__create_event', 'mcp__claude_ai_Google_Calendar__update_event',
                      'mcp__claude_ai_Google_Calendar__delete_event']},
        'slack': {
            'skill': 'taskboard-slack', 'ask': '「タスク」メモと Slack の依頼を inbox に拾い、振り分け先を提案して。',
            'tools': ['Bash(python inbox_sync.py:*)',
                      'mcp__claude_ai_Slack__slack_read_channel', 'mcp__claude_ai_Slack__slack_search_public_and_private',
                      'mcp__claude_ai_Slack__slack_read_thread']},
        'mission': {
            'skill': 'taskboard-mission', 'ask': 'ミッションを読み込んで。シートには書かない。',
            'tools': ['Bash(python mission_sync.py pull)']},
        'eval': {
            'skill': 'taskboard-eval', 'ask': '評価エピソードの候補を集めて。',
            'tools': ['Bash(python eval_sync.py:*)', 'mcp__claude_ai_Slack__slack_search_public_and_private']},
        # inbox の依頼の方針と返信案。調べるのは読むだけの範囲。Slack への送信・下書きは許さない
        'plan': {
            'skill': 'taskboard-plan', 'ask': 'inbox の依頼の方針と返信案を出して。',
            'tools': ['Bash(python inbox_sync.py plan-get:*)', 'Bash(python inbox_sync.py plan-set:*)',
                      'mcp__claude_ai_Slack__slack_read_thread', 'mcp__claude_ai_Slack__slack_read_channel',
                      'mcp__claude_ai_Slack__slack_search_public_and_private', 'mcp__claude_ai_Slack__slack_read_canvas',
                      'mcp__claude_ai_Slack__slack_read_user_profile', 'mcp__claude_ai_Slack__slack_search_users',
                      'mcp__claude_ai_Google_Drive__search_files', 'mcp__claude_ai_Google_Drive__read_file_content',
                      'mcp__claude_ai_Google_Drive__get_file_metadata',
                      'mcp__claude_ai_Google_Sheets__get_values', 'mcp__claude_ai_Google_Sheets__get_spreadsheet']},
    }
    PROMPT = (
        '{skill} スキルの手順どおりに、{ask}\n'
        '- 作業フォルダは今いる場所（taskboard）。cd や PYTHONIOENCODING は付けず、'
        '`python calendar_sync.py ...` のようにそのまま実行する\n'
        '- Slack・カレンダーの取得結果をファイルに保存するときは sync_tmp/ フォルダの中に書く\n'
        '- 最後の報告は、スキルの「報告」にある決まった形式の行だけを出す。前置き・まとめ・太字は付けない\n'
    )
    AUTO_DAYS = range(0, 5)                 # 月〜金
    AUTO_FROM, AUTO_TO = (10, 0), (19, 0)   # この間の毎時 0分・30分（19:00 も含む）
    busy = ''
    states = {j: {'state': 'idle', 'startedAt': None, 'finishedAt': None, 'summary': '', 'trigger': ''}
              for j in JOBS}
    # 方針は依頼ごと。ほかの仕事が動いている間に頼まれたら waiting に並べ、終わったら順に回す
    waiting = []      # [(job, extra, trigger)]
    plans = {}        # {依頼の id: {'state': queued / running / done / error, 'at', 'error'}}

    @classmethod
    def status(cls, job='auto'):
        with cls.lock:
            return {**cls.states.get(job, cls.states['auto']), 'job': job, 'busy': cls.busy}

    @classmethod
    def start(cls, job='auto', extra=None, trigger='manual'):
        if job not in cls.JOBS:
            return {'ok': False, 'state': 'error', 'error': f'知らない仕事です: {job}'}
        with cls.lock:
            if cls.busy:
                if job == 'plan':
                    if all(w[1] != extra for w in cls.waiting):
                        cls.waiting.append((job, extra, trigger))
                    cls.plans[extra] = {'state': 'queued', 'at': utc_now(), 'error': ''}
                    return {'ok': True, 'state': 'queued', 'job': job, 'busy': cls.busy}
                return {**cls.states[job], 'job': job, 'busy': cls.busy, 'ok': False, 'error': 'already running'}
            exe = shutil.which('claude')
            if not exe:
                return {'ok': False, 'state': 'error', 'error': 'claude コマンドが見つかりません'}
            cls.busy = job
            cls.states[job] = {'state': 'running', 'startedAt': utc_now(), 'finishedAt': None,
                               'summary': '', 'trigger': trigger}
            if job == 'plan':
                cls.plans[extra] = {'state': 'running', 'at': utc_now(), 'error': ''}
        threading.Thread(target=cls._run, args=(job, exe, extra), daemon=True).start()
        return {**cls.status(job), 'ok': True}

    @staticmethod
    def model_of(skill):
        """スキルの SKILL.md の model: を読む。無ければ空（既定のモデル）"""
        try:
            head = (SKILLS / skill / 'SKILL.md').read_text(encoding='utf-8').split('---')[1]
        except (OSError, IndexError):
            return ''
        for ln in head.splitlines():
            if ln.startswith('model:'):
                return ln.split(':', 1)[1].strip()
        return ''

    @classmethod
    def _part(cls, exe, name, extra):
        part = cls.PARTS[name]
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        args = [exe, '-p', '--output-format', 'text', '--allowedTools', *COMMON_TOOLS, *part['tools']]
        model = cls.model_of(part['skill'])
        if model:
            args[1:1] = ['--model', model]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # 裏で動かしているときに黒い窓を出さない
        prompt = cls.PROMPT.format(**part)
        if name == 'calendar' and extra:
            prompt += (f'- 今週・来週に加えて、{extra[0]}〜{extra[1]} の週も取り込む。list_events をその範囲でも呼び、'
                       f'ingest には --range 今週日曜:来週土曜 --range {extra[0]}:{extra[1]} の形で両方の範囲を渡す\n')
        if name == 'plan':
            prompt += f'- 対象の依頼の id は {extra}。`python inbox_sync.py plan-get {extra}` から始める\n'
        try:
            p = subprocess.run(args, input=prompt, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', cwd=str(ROOT), env=env,
                               timeout=15 * 60, creationflags=flags)
            out = (p.stdout or '').strip()
            lines = [ln for ln in out.splitlines() if 'andbox' not in ln]   # 警告行は捨てる
            summary = '\n'.join(lines).strip()
            if p.returncode != 0:
                summary = (summary + '\n' + (p.stderr or '')).strip()
                return False, summary + f'\nエラー：{part["skill"]} が異常終了しました'
            return True, summary
        except subprocess.TimeoutExpired:
            return False, f'エラー：{part["skill"]} が15分で終わらなかったので止めました'
        except OSError as e:
            return False, f'エラー：{part["skill"]} を起動できませんでした: {e}'

    @classmethod
    def _run(cls, job, exe, extra=None):
        cls.TMP.mkdir(exist_ok=True)
        ok, texts = True, []
        for name in cls.JOBS[job]:
            # カレンダーが失敗しても Slack は回す。別の仕事なので
            o, text = cls._part(exe, name, extra)
            ok = ok and o
            texts.append(text)
        summary = '\n'.join(texts)
        try:
            (ROOT / f'sync-{job}.log').write_text(f'[{utc_now()}] ok={ok}\n{summary}\n', encoding='utf-8')
        except OSError:
            pass
        with cls.lock:
            cls.busy = ''
            cls.states[job] = {**cls.states[job], 'state': 'done' if ok else 'error',
                               'finishedAt': utc_now(), 'summary': summary[:3000]}
            if job == 'plan':
                cls.plans[extra] = {'state': 'done' if ok else 'error', 'at': utc_now(),
                                    'error': '' if ok else summary[-500:]}
            nxt = cls.waiting.pop(0) if cls.waiting else None
        if nxt:
            cls.start(*nxt)

    @classmethod
    def plan(cls, iid, talk):
        """依頼の詳細から方針を頼む。竹島のコメント（talk）は sync_tmp/plan-<id>.json に置き、
           Claude が inbox_sync.py plan-get で読む"""
        if not re.fullmatch(r'[\w.-]{1,120}', iid or ''):
            return {'ok': False, 'state': 'error', 'error': '依頼の id が正しくありません'}
        cls.TMP.mkdir(exist_ok=True)
        talk = [{'at': str(t.get('at', ''))[:30], 'text': str(t.get('text', ''))[:4000]}
                for t in (talk if isinstance(talk, list) else []) if isinstance(t, dict) and t.get('text')][-50:]
        (cls.TMP / f'plan-{iid}.json').write_text(json.dumps({'id': iid, 'talk': talk}, ensure_ascii=False),
                                                  encoding='utf-8')
        return cls.start('plan', iid)

    @classmethod
    def timer(cls):
        """平日 10:00〜19:00 の毎時 0分・30分に auto を回す。何かが動いていたらその回は飛ばす"""
        last = ''
        while True:
            now = datetime.datetime.now()
            slot = now.strftime('%Y-%m-%d %H:%M')
            if (now.weekday() in cls.AUTO_DAYS and now.minute in (0, 30)
                    and cls.AUTO_FROM <= (now.hour, now.minute) <= cls.AUTO_TO and slot != last):
                last = slot
                cls.start('auto', trigger='timer')
            time.sleep(20)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):
        if self.path.startswith('/api/'):
            return
        super().log_message(fmt, *args)

    def end_headers(self):
        # 編集した index.html が古いまま出続けるのを防ぐ
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split('?')[0] == '/api/ping':
            self._json(200, {'ok': True, 'mode': 'server', 'file': DATA.name})
            return
        if self.path.split('?')[0] == '/api/sync':
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self._json(200, Sync.status((q.get('job') or ['auto'])[0]))
            return
        if self.path.split('?')[0] == '/api/plan':
            with Sync.lock:
                self._json(200, {'plans': dict(Sync.plans), 'busy': Sync.busy})
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split('?')[0] == '/api/sync':
            # 本文の job で仕事を選ぶ（auto / mission / eval。無ければ auto）。
            # {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"} があれば、その週もカレンダーに取り込む（画面で見ている週）
            extra, job = None, 'auto'
            try:
                n = int(self.headers.get('Content-Length') or 0)
                if 0 < n < 10000:
                    body = json.loads(self.rfile.read(n).decode('utf-8'))
                    job = str(body.get('job') or 'auto')
                    f, t = str(body.get('from', '')), str(body.get('to', ''))
                    if len(f) == 10 and len(t) == 10 and f[4] == '-' and t[4] == '-':
                        extra = (f, t)
            except (ValueError, json.JSONDecodeError, AttributeError):
                extra = None
            self._json(200, Sync.start(job, extra))
            return
        if self.path.split('?')[0] == '/api/plan':
            # 本文は {"id": 依頼の id, "talk": [{"at", "text"}, ...]}。talk は詳細に書いたコメント（古い順）
            try:
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n).decode('utf-8')) if 0 < n < 512 * 1024 else {}
            except (ValueError, json.JSONDecodeError):
                body = {}
            if not isinstance(body, dict):
                body = {}
            self._json(200, Sync.plan(str(body.get('id') or ''), body.get('talk')))
            return
        if self.path.split('?')[0] != '/api/save':
            self._json(404, {'ok': False, 'error': 'not found'})
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            self._json(400, {'ok': False, 'error': 'bad length'})
            return
        if length <= 0 or length > MAX_BODY:
            self._json(400, {'ok': False, 'error': 'bad length'})
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._json(400, {'ok': False, 'error': f'invalid json: {e}'})
            return
        # taskboard のデータ以外は書かせない（誤って別物で上書きしないため）
        if not isinstance(payload, dict) \
                or not isinstance(payload.get('projects'), list) \
                or not isinstance(payload.get('tasks'), list):
            self._json(400, {'ok': False, 'error': 'not a taskboard document'})
            return
        try:
            rotate_backup()
            write_atomic(payload)
        except OSError as e:
            self._json(500, {'ok': False, 'error': str(e)})
            return
        self._json(200, {'ok': True,
                         'tasks': len(payload['tasks']),
                         'savedAt': datetime.datetime.now().astimezone().isoformat()})


class Server(socketserver.ThreadingTCPServer):
    # Windows ではこれを True にすると、同じポートに2つ目のサーバーが立ててしまう。
    # 裏で動いているのに start.bat を押したときに二重起動しないよう、Windows では切る。
    allow_reuse_address = os.name != 'nt'
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8777)
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()

    if not DATA.exists():
        write_atomic({'version': 1,
                      'updatedAt': utc_now(),
                      'projects': [], 'tasks': []})

    url = f'http://127.0.0.1:{a.port}/index.html'
    with Server(('127.0.0.1', a.port), Handler) as srv:
        print()
        print(f'  task backlog   {url}')
        print(f'  保存先          {DATA}')
        print(f'  控え            {BACKUPS}')
        print()
        print('  このウィンドウを閉じると止まります。')
        print()
        if not a.no_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        threading.Thread(target=Sync.timer, daemon=True).start()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('停止しました。')


if __name__ == '__main__':
    main()
