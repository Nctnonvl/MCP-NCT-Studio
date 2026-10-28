@echo off
chcp 65001 >nul
setlocal
set "NCT_PROJECT_DIR=%~dp0"
if not exist "%NCT_PROJECT_DIR%reset_facebook_login.py" set "NCT_PROJECT_DIR=D:\MCP\NCT_Group_Manager\"
if not exist "%NCT_PROJECT_DIR%.venv\Scripts\python.exe" (
  echo Khong tim thay Python cua NCT Group Manager.
  pause
  exit /b 1
)
"%NCT_PROJECT_DIR%.venv\Scripts\python.exe" "%NCT_PROJECT_DIR%reset_facebook_login.py"
if errorlevel 1 pause
endlocal
