"""Garde-fous AUTOMATIQUES des sessions Claude Code de ce projet (hook PreToolUse de `.claude/settings.json`, outils
Bash et PowerShell ; demande de l'utilisateur 2026-11-06 : « que ce soit acté pour toujours », une note se contourne
par inattention, pas un hook).

Refuse (code de sortie 2, la raison est rendue à l'agent) :
- une recherche RÉCURSIVE sur tout le projet (`grep -r` sur `.`, sans chemin, `*` ou la racine ; `Get-ChildItem` /
  `Select-String` avec `-Recurse` sans chemin précis ; `find` à la racine sans `-maxdepth`) : `data/` et les caches
  la font expirer (120 s perdues, deux fois déjà) ;
- les suites de tests longues, que l'UTILISATEUR lance à temps perdu (`fluidite.bat`) : `tests/run.py`, `unittest
  discover` sans `-p`, `--lent`, `PIPELINE_TESTS_LENTS`, et un fichier de test ENTIER s'il est lourd
  (`tools/hooks/tests_lourds.txt`, mis à jour par `tools/fluidite.py`) — ses tests se lancent par leur nom.

Contournement : préfixer la commande de `GARDE_FOUS_OK=1` SEULEMENT si l'utilisateur l'a demandé en toutes lettres.
Léger exprès (json, re, shlex) : il tourne avant chaque commande. Une erreur interne laisse passer la commande."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

ROOT = os.path.normcase(os.path.normpath(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
HEAVY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests_lourds.txt")
BYPASS = "GARDE_FOUS_OK=1"
SEPARATORS = {"|", "||", "&&", ";", "&", "(", ")"}


def _heavy_tests() -> set[str]:
    try:
        with open(HEAVY_FILE, encoding="utf-8") as handle:
            return {line.split("#")[0].strip() for line in handle if line.split("#")[0].strip()}
    except OSError:
        return set()


def _msys_to_windows(path: str) -> str:
    match = re.match(r"^/([a-zA-Z])(/.*)?$", path)          # /f/SYNC/... (Git Bash) -> F:/SYNC/...
    return f"{match.group(1)}:{match.group(2) or '/'}" if match else path


def _is_root(path: str, cwd_is_root: bool) -> bool:
    path = path.strip().strip('"').strip("'")
    if path in ("", ".", "./", ".\\", "*", "./*"):
        return cwd_is_root
    if "$CLAUDE_PROJECT_DIR" in path or "%CLAUDE_PROJECT_DIR%" in path:
        path = path.replace("$CLAUDE_PROJECT_DIR", ROOT).replace("${CLAUDE_PROJECT_DIR}", ROOT)
    path = _msys_to_windows(path)
    if not os.path.isabs(path):
        return False
    return os.path.normcase(os.path.normpath(path)) == ROOT


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments, current = [], []
    for token in lexer:
        if token in SEPARATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _grep_targets(args: list[str]):
    """(récursif ?, chemins) d'un appel de grep."""
    recursive, pattern_given, positional = False, False, []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            positional += args[i + 1:]
            break
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            if name in ("--recursive", "--dereference-recursive"):
                recursive = True
            if name in ("--regexp", "--file"):
                pattern_given = True
            if "=" not in token and name in ("--regexp", "--file", "--include", "--exclude", "--exclude-dir",
                                             "--max-count", "--context", "--after-context", "--before-context"):
                i += 1
        elif token.startswith("-") and len(token) > 1:
            flags = token[1:]
            for j, flag in enumerate(flags):
                if flag in "rR":
                    recursive = True
                if flag in "efmABCdD":
                    pattern_given = pattern_given or flag in "ef"
                    if j == len(flags) - 1:
                        i += 1                              # l'argument est le jeton suivant
                    break                                   # sinon le reste du jeton est l'argument
        else:
            positional.append(token)
        i += 1
    return recursive, (positional if pattern_given else positional[1:])


def _search_problem(command: str) -> str | None:
    try:
        segments = _segments(command)
    except ValueError:                                      # guillemets de PowerShell que shlex ne lit pas
        segments = []
    cwd_is_root = True
    for seg in segments:
        while seg and re.match(r"^\w+=", seg[0]):            # VAR=valeur commande
            seg = seg[1:]
        if not seg:
            continue
        name = os.path.basename(seg[0]).lower()
        if name in ("cd", "set-location", "pushd") and len(seg) > 1:
            cwd_is_root = _is_root(seg[-1], True)
        elif name in ("grep", "egrep", "fgrep"):
            recursive, paths = _grep_targets(seg[1:])
            if recursive and (not paths and cwd_is_root or any(_is_root(p, cwd_is_root) for p in paths)):
                return ("recherche récursive (grep -r) sur TOUT le projet : data/ et les caches la font expirer. "
                        "Utiliser l'outil Grep avec `glob`/`path`, ou grep -r sur un dossier précis (fm_board, tests...).")
        elif name == "find" and len(seg) > 1 and _is_root(seg[1], cwd_is_root) and "-maxdepth" not in seg:
            return "find sur tout le projet : utiliser l'outil Glob (ou find sur un dossier précis, ou -maxdepth)."
    low = command.lower()
    if re.search(r"(get-childitem|\bgci\b|\bls\b|\bdir\b|select-string|\bsls\b)[^|;]*-recurse", low):
        match = re.search(r"-path\s+(\"[^\"]*\"|'[^']*'|\S+)", command, re.IGNORECASE)
        if match is None or _is_root(match.group(1), True):
            return ("-Recurse sur TOUT le projet (PowerShell) : utiliser les outils Glob / Grep, ou un -Path "
                    "précis (fm_board, tests...).")
    return None


def _tests_problem(command: str) -> str | None:
    later = "les suites longues sont lancées par l'utilisateur à temps perdu (fluidite.bat)."
    run = r"python[\w.]*[\"']?\s+[^|;&\n]*?"          # lancé par Python (lire le fichier, le chercher : permis)
    if re.search(run + r"tests[/\\]run\.py", command):
        return f"tests/run.py lance un module entier : lancer les tests concernés PAR NOM ; {later}"
    if re.search(run + r"--lent\b", command) or re.search(r"PIPELINE_TESTS_LENTS\s*=\s*[\"']?1", command):
        return f"tests lents demandés : {later}"
    heavy = _heavy_tests()
    files = []
    discover = re.search(r"unittest\s+discover\b", command)
    if discover:
        pattern = re.search(r"\s-p\s+[\"']?([\w*.]+)", command)
        if pattern is None or "*" in pattern.group(1):
            return f"unittest discover lance toute la suite : lancer les tests concernés PAR NOM ; {later}"
        files.append(pattern.group(1).removesuffix(".py"))
    for match in re.finditer(r"unittest((?:\s+-\w+)*)((?:\s+[\"']?[\w.]+[\"']?)+)", command):
        for target in match.group(2).split():
            target = target.strip("\"'")
            parts = target.split(".")
            if parts and parts[0] == "tests":
                parts = parts[1:]
            if len(parts) == 1 and parts[0].startswith("test_"):
                files.append(parts[0])                      # module seul : le fichier entier
    files += re.findall(r"python[\w.]*\"?\s+[^|;&\n]*?tests[/\\](test_\w+)\.py", command)
    for name in files:
        if name in heavy:
            return (f"{name} entier est un fichier de test LOURD (tools/hooks/tests_lourds.txt) : lancer ses tests "
                    f"PAR NOM (tests.{name}.Classe ou .test_x), ceux qui couvrent la fonction modifiée ; {later}")
    return None


def main() -> int:
    try:                                    # UTF-8 quel que soit l'encodage de la console Windows
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except (ValueError, OSError):
        return 0
    command = (data.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str) or not command or BYPASS in command:
        return 0
    problem = _search_problem(command) or _tests_problem(command)
    if problem is None:
        return 0
    message = f"Refusé par les garde-fous du projet (tools/hooks/garde_fous.py, AGENTS.md) : {problem}\n"
    sys.stderr.buffer.write(message.encode("utf-8"))
    sys.stderr.flush()
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:                                       # noqa: BLE001 - un garde-fou ne bloque jamais par erreur
        sys.exit(0)
