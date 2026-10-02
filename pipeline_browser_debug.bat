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

echo --- Installation / verification des dependances de l'application ---
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install PySide6 ezdxf matplotlib
echo.

echo Les apercus DWG necessitent aussi ODA File Converter.
echo Installez-le depuis https://www.opendesign.com/guestfiles/oda_file_converter
echo ou definissez ODA_FILE_CONVERTER vers ODAFileConverter.exe.
echo.

echo --- Lancement de l'application ---
"%VENV%\Scripts\python.exe" "%~dp0pipeline_browser.py"
echo.
echo --- Termine (code de sortie %errorlevel%) ---
pause
