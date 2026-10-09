#!/usr/bin/env python3
"""
task backlog のローカルサーバー。

画面を配るだけでなく、保存も引き受ける。ブラウザのファイル書き込み許可
（File System Access API）が要らなくなるのはこのため。ページは fetch で
POST するだけで、実際に tasks.json へ書くのはこちらの仕事になる。

    python server.py [--port 8777] [--no-browser]

127.0.0.1 にだけ待ち受ける。外部からは触れない。
書き込むのはこのフォルダの tasks.json と backups/ の中だけ。
"""
import argparse
import datetime
import http.server
import json
import os
import pathlib
import shutil
import socketserver
import subprocess
import sys
import threading
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


class Sync:
    """画面の「同期」ボタンから、Claude Code（コマンド版）に taskboard-sync を頼む。
       同時に1本だけ。結果の文章は sync.log に残し、画面には先頭だけ返す。
       Claude に許すのは、同期に要るツールだけ（カレンダー・Slack の読み取り・2つのスクリプト）。"""
    lock = threading.Lock()
    state = {'state': 'idle', 'startedAt': None, 'finishedAt': None, 'summary': ''}
    LOG = ROOT / 'sync.log'
    TMP = ROOT / 'sync_tmp'
    PROMPT = (
        'taskboard-sync スキルの手順どおりに、カレンダー同期と inbox の取り込みをして。\n'
        '- 作業フォルダは今いる場所（taskboard）。cd や PYTHONIOENCODING は付けず、'
        '`python calendar_sync.py ...` / `python inbox_sync.py ...` の形でそのまま実行する\n'
        '- Slack の取得結果をファイルに保存するときは sync_tmp/ フォルダの中に書く\n'
        '- 最後の報告は、スキルの「報告」にある決まった形式の7行だけを出す。前置き・まとめ・太字は付けない\n'
    )
    TOOLS = [
        'Skill', 'ToolSearch', 'Read',
        'Write(./sync_tmp/**)', 'Edit(./sync_tmp/**)',
        'Bash(python calendar_sync.py:*)', 'Bash(python inbox_sync.py:*)',
        'mcp__claude_ai_Google_Calendar__list_events', 'mcp__claude_ai_Google_Calendar__get_event',
        'mcp__claude_ai_Google_Calendar__create_event', 'mcp__claude_ai_Google_Calendar__update_event',
        'mcp__claude_ai_Google_Calendar__delete_event',
        'mcp__claude_ai_Slack__slack_read_channel',
    ]

    @classmethod
    def status(cls):
        with cls.lock:
            return dict(cls.state)

    @classmethod
    def start(cls, extra=None):
        with cls.lock:
            if cls.state['state'] == 'running':
                return {**cls.state, 'ok': False, 'error': 'already running'}
            exe = shutil.which('claude')
            if not exe:
                return {'ok': False, 'state': 'error', 'error': 'claude コマンドが見つかりません'}
            cls.state = {'state': 'running', 'startedAt': utc_now(), 'finishedAt': None, 'summary': ''}
        threading.Thread(target=cls._run, args=(exe, extra), daemon=True).start()
        return {**cls.status(), 'ok': True}

    @classmethod
    def _run(cls, exe, extra=None):
        cls.TMP.mkdir(exist_ok=True)
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        args = [exe, '-p', '--output-format', 'text', '--allowedTools', *cls.TOOLS]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # 裏で動かしているときに黒い窓を出さない
        try:
            prompt = cls.PROMPT
            if extra:
                prompt += (f'- 今週・来週に加えて、{extra[0]}〜{extra[1]} の週も取り込む。list_events をその範囲でも呼び、'
                           f'ingest には --range 今週日曜:来週土曜 --range {extra[0]}:{extra[1]} の形で両方の範囲を渡す\n')
            p = subprocess.run(args, input=prompt, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', cwd=str(ROOT), env=env,
                               timeout=15 * 60, creationflags=flags)
            out = (p.stdout or '').strip()
            lines = [ln for ln in out.splitlines() if 'andbox' not in ln]   # 警告行は捨てる
            summary = '\n'.join(lines).strip()
            ok = p.returncode == 0
            if not ok:
                summary = (summary + '\n' + (p.stderr or '')).strip()
        except subprocess.TimeoutExpired:
            ok, summary = False, '15分で終わらなかったので止めました'
        except OSError as e:
            ok, summary = False, f'起動できませんでした: {e}'
        try:
            cls.LOG.write_text(f'[{utc_now()}] ok={ok}\n{summary}\n', encoding='utf-8')
        except OSError:
            pass
        with cls.lock:
            cls.state = {**cls.state, 'state': 'done' if ok else 'error',
                         'finishedAt': utc_now(), 'summary': summary[:1500]}


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
            self._json(200, Sync.status())
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split('?')[0] == '/api/sync':
            # 本文に {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"} があれば、その週も取り込む（画面で見ている週）
            extra = None
            try:
                n = int(self.headers.get('Content-Length') or 0)
                if 0 < n < 10000:
                    body = json.loads(self.rfile.read(n).decode('utf-8'))
                    f, t = str(body.get('from', '')), str(body.get('to', ''))
                    if len(f) == 10 and len(t) == 10 and f[4] == '-' and t[4] == '-':
                        extra = (f, t)
            except (ValueError, json.JSONDecodeError):
                extra = None
            self._json(200, Sync.start(extra))
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
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('停止しました。')


if __name__ == '__main__':
    main()
