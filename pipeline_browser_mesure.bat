@echo off
rem Lance l'appli avec le journal des blocages de l'interface (data\stalls.log) : diagnostic de fluidite.
cd /d "%~dp0"
set PIPELINE_STALL_LOG=1
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" pipeline_browser.py
) else (
    py -3 pipeline_browser.py
)
echo.
echo Journal : %~dp0data\stalls.log
pause
