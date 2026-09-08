@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\enable_semantic_search.ps1"
if errorlevel 1 (
  echo.
  echo 开启失败，请根据上方提示检查 API Key 或网络。
) else (
  echo.
  echo 已开启 Qwen Embedding 混合检索。重启后端即可生效。
)
pause
