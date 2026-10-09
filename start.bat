@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PORT=8777"

rem ログイン時の自動起動でサーバーが裏で動いていれば、ボードを開くだけにする
curl -s -m 2 http://127.0.0.1:%PORT%/api/ping >nul 2>nul
if not errorlevel 1 (
  start "" "http://127.0.0.1:%PORT%/index.html"
  exit /b
)

where python >nul 2>nul
if errorlevel 1 goto nopython

python server.py --port %PORT%
exit /b

:nopython
echo Python が見つかりませんでした。index.html を直接開きます。
echo （この場合 tasks.json への自動保存は使えません）
start "" "%~dp0index.html"
pause
