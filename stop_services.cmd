@echo off
chcp 65001 >nul
cd /d "%~dp0"
docker compose down
echo 完整服务栈已停止，MySQL 数据卷默认保留。
pause
