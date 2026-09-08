@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先创建虚拟环境并安装依赖后再使用此备用入口。
  pause
  exit /b 1
)
set PERSISTENCE_BACKEND=json
set RATE_LIMIT_BACKEND=memory
set AGENT_MODEL_PROVIDER=deterministic
start "" http://127.0.0.1:8000/
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
