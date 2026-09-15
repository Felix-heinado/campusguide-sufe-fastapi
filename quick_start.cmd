@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ================================================
echo SUFE Guide - full stack quick start
echo FastAPI + MySQL + Redis + Agent Runtime
echo ================================================

where docker >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Docker Desktop was not found. Install and start it first.
  pause
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is not ready. Trying to start it...
  docker desktop start --detach >nul 2>nul
  set ENGINE_READY=0
  for /l %%i in (1,1,30) do (
    docker info >nul 2>nul
    if not errorlevel 1 (
      set "ENGINE_READY=1"
      goto :engine_ready
    )
    timeout /t 2 /nobreak >nul
  )
  :engine_ready
  if "%ENGINE_READY%"=="0" (
    echo [ERROR] Docker Desktop is not running.
    echo Please open Docker Desktop and wait until the Linux Engine is ready.
    pause
    exit /b 1
  )
)
echo [1/3] Validating Docker Compose configuration...
docker compose config -q
if errorlevel 1 (
  echo [ERROR] docker-compose.yml validation failed.
  pause
  exit /b 1
)
echo [2/3] Building and starting MySQL, Redis and FastAPI...
docker compose up --build -d
if errorlevel 1 goto :failed
echo [3/3] Waiting for API readiness...
set READY=0
for /l %%i in (1,1,45) do (
  powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/ready -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } } catch {} ; exit 1" >nul 2>nul
  if not errorlevel 1 (
    set "READY=1"
    goto :ready
  )
  timeout /t 2 /nobreak >nul
)
:ready
if "%READY%"=="0" goto :failed
echo Full stack is ready: http://127.0.0.1:8000/
echo Swagger: http://127.0.0.1:8000/docs
echo Run stop_services.cmd to stop the stack.
start "" http://127.0.0.1:8000/
pause
exit /b 0

:failed
echo.
echo [ERROR] Startup failed. Run "docker compose logs" for details.
pause
exit /b 1
