@echo off
rem Tests et mesures de fluidite A TEMPS PERDU (tools/fluidite.py) : rapport dans docs\agents\rapport_fluidite.md.
rem Options : --lent (tests lents compris), --sans-tests, --sans-bancs, --sans-file, --filtre <texte>.
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
"%PY%" tools\fluidite.py %*
echo.
pause
