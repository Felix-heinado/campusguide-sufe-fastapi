@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo 首次运行需要先安装依赖：
  echo uv sync --extra dev --extra mysql --no-install-project
  pause
  exit /b 1
)

set PERSISTENCE_BACKEND=json
echo 正在启动财问 SUFE Guide 完整网站...
echo 启动后访问 http://127.0.0.1:8000/
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
