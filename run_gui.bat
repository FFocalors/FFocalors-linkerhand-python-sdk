@echo off
chcp 65001 >nul
setlocal
set "PROJECT_ROOT=%~dp0"
set "PYTHONPATH=%PROJECT_ROOT%"

if not exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    echo [ERROR] Workspace Python not found: "%PROJECT_ROOT%.venv\Scripts\python.exe"
    pause
    exit /b 1
)

pushd "%PROJECT_ROOT%example\gui_control"
"%PROJECT_ROOT%.venv\Scripts\python.exe" "%PROJECT_ROOT%example\gui_control\main.py"
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" echo [ERROR] GUI exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
