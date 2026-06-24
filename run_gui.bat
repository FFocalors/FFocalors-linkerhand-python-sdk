@echo off
chcp 65001 >nul
setlocal
set "PROJECT_ROOT=%~dp0"
set "PYTHONPATH=%PROJECT_ROOT%"
set "PYTHON_EXE=D:\develop_tools\mini\envs\linkerhand_py39\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Required Python not found: "%PYTHON_EXE%"
    pause
    exit /b 1
)

pushd "%PROJECT_ROOT%example\gui_control"
"%PYTHON_EXE%" "%PROJECT_ROOT%example\gui_control\main.py"
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" echo [ERROR] GUI exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
