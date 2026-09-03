@echo off
setlocal
cd /d "%~dp0"

echo Dossier courant : %CD%
echo.
echo --- Contenu du dossier ---
dir /b
echo.

echo --- Python detecte ---
py -3 --version
if errorlevel 1 (
    echo ERREUR : le lanceur "py" est introuvable. Python n'est pas installe correctement.
    pause
    exit /b 1
)
echo.

set "VENV=%~dp0.venv"

if not exist "%VENV%\Scripts\python.exe" (
    echo --- Creation de l'environnement virtuel ---
    py -3 -m venv "%VENV%"
    if errorlevel 1 (
        echo ERREUR : creation du venv impossible.
        pause
        exit /b 1
    )
)

echo --- Installation / verification de PySide6 ---
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install PySide6
echo.

echo --- Lancement de l'application ---
"%VENV%\Scripts\python.exe" "%~dp0pipeline_browser.py"
echo.
echo --- Termine (code de sortie %errorlevel%) ---
pause
