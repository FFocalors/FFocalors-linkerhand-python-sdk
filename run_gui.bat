@echo off
chcp 65001 >nul
setlocal
set "PROJECT_ROOT=%~dp0"
set "PYTHONPATH=%PROJECT_ROOT%"
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
    echo [ERROR] Python not found. Please install Python 3.9+ and add it to PATH.
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
