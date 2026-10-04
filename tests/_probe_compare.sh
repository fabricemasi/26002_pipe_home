#!/bin/bash
# usage : tests/_probe_compare.sh  (capture avant = HEAD des fichiers settings_*, apres = copie de travail)
cd "$(dirname "$0")/.."
P=/tmp/claude-1000/-mnt-f-SYNC-Sync-PROG-26002-pipe-home/60bc46ff-654b-44ba-b170-edfdac1c617f/scratchpad/compare
rm -rf "$P" tests/_shots_before tests/_shots_after; mkdir -p "$P"
cp settings_*.py "$P"/
git stash push -q settings_window.py settings_sections.py settings_layout.py settings_widgets.py settings_store.py settings_colorpicker.py
mv settings_theme.py "$P/theme.bak" 2>/dev/null
powershell.exe -NoProfile -Command "cd F:\SYNC\Sync\PROG\26002_pipe_home; .venv\Scripts\python.exe tests\_probe_render.py tests\_shots_before 2>&1 | Select-Object -Last 3"
mv "$P/theme.bak" settings_theme.py 2>/dev/null
git stash pop -q
powershell.exe -NoProfile -Command "cd F:\SYNC\Sync\PROG\26002_pipe_home; .venv\Scripts\python.exe tests\_probe_render.py tests\_shots_after 2>&1 | Select-Object -Last 3"
same=0; diff=0
for f in tests/_shots_before/*.png; do b=$(basename "$f"); if cmp -s "$f" "tests/_shots_after/$b"; then same=$((same+1)); else diff=$((diff+1)); echo "DIFF $b"; fi; done
echo "identiques=$same differentes=$diff"
