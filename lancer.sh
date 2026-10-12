#!/bin/bash
# Lance l'appli (fenetre Windows) depuis WSL avec le Python du .venv Windows.
cd "$(dirname "$0")"
exec .venv/Scripts/python.exe pipeline_browser.py "$@"
