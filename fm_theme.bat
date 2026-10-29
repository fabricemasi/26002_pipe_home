@echo off
rem Lance fm_theme : pour l'instant, la fenetre de reglages seule (l'editeur fm_theme viendra a l'etape 5).
rem Premiere installation (.venv, dependances) : pipeline_browser_debug.bat.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PY%" (
    echo Environnement .venv introuvable : lancer d'abord pipeline_browser_debug.bat.
    pause
    exit /b 1
)
start "" "%PY%" -m fm_theme
