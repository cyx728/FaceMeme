@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
where py >nul 2>nul
if not errorlevel 1 (
    py -3.11 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        py -3.11 run_all.py %*
        goto finished
    )
    py -3.12 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        py -3.12 run_all.py %*
        goto finished
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python run_all.py %*
    goto finished
)
echo Please install Python 3.11 or 3.12 from https://www.python.org/downloads/
set "RUN_EXIT=1"
goto wait_exit
:finished
set "RUN_EXIT=%ERRORLEVEL%"
:wait_exit
if "%~1"=="" pause
exit /b %RUN_EXIT%
