"""Vérification À TEMPS PERDU (demande de l'utilisateur 2026-11-06 : lancer les tests et les mesures de fluidité quand
il n'attend rien, plutôt que de les faire pendant ses requêtes) : `fluidite.bat`, ou
`python tools/fluidite.py [--lent] [--sans-tests] [--sans-bancs] [--sans-file] [--filtre texte]`.

1. TESTS : chaque fichier `tests/test_*.py`, un par un et chronométré (tests rapides ; `--lent` : lents compris ;
   `--filtre` : seulement les fichiers dont le nom contient le texte). Met à jour `tools/hooks/tests_lourds.txt`
   (fichiers de plus de `LOURD` secondes : le hook `tools/hooks/garde_fous.py` refuse à l'agent de les lancer
   en entier pendant une requête).
2. BANCS de fluidité (offscreen) : `BANCS` ci-dessous.
3. FILE D'ATTENTE `docs/agents/a_mesurer.md` : chaque ligne « - [ ] description — `commande` » y est lancée
   (l'agent y note ce qu'il n'a pas mesuré pendant la requête).
Rapport : `docs/agents/rapport_fluidite.md`. À la requête suivante, l'agent le lit et corrige en priorité ce qui
échoue ou dépasse."""
from __future__ import annotations

import datetime
import glob
import os
import re
import shlex
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
LOURD = 15.0                                        # secondes : au-delà, un fichier de test est « lourd »
HEAVY_FILE = os.path.join(ROOT, "tools", "hooks", "tests_lourds.txt")
QUEUE_FILE = os.path.join(ROOT, "docs", "agents", "a_mesurer.md")
REPORT_FILE = os.path.join(ROOT, "docs", "agents", "rapport_fluidite.md")
BANCS = [
    ("Illustrator, 2 000 tracés", ["tools/bench_illustrator.py"]),
    ("Photoshop, calcul / chargement / mémoire", ["tools/bench_photoshop.py"]),
    ("Photoshop, latence visible", ["tools/probe_photoshop_latency.py"]),
]
TIMEOUT_TEST = 20 * 60
TIMEOUT_BANC = 30 * 60


def _env(slow: bool) -> dict:
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONIOENCODING"] = "utf-8"
    if slow:
        env["PIPELINE_TESTS_LENTS"] = "1"
    return env


def _run(args: list[str], timeout: float, env: dict) -> tuple[int, float, str]:
    start = time.perf_counter()
    try:
        done = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, timeout=timeout)
        out = (done.stdout + done.stderr).decode("utf-8", "replace")
        code = done.returncode
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"") + (exc.stderr or b"")).decode("utf-8", "replace") + f"\n[EXPIRÉ après {timeout:.0f} s]"
        code = -1
    return code, time.perf_counter() - start, out


def _tail(text: str, lines: int = 60) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def run_tests(slow: bool, needle: str | None) -> list[dict]:
    env = _env(slow)
    files = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "tests", "test_*.py")))
    if needle:
        files = [f for f in files if needle in f]
    results = []
    for index, name in enumerate(files, 1):
        code, seconds, out = _run([PY, "-m", "unittest", f"tests.{name}"], TIMEOUT_TEST, env)
        ran = re.findall(r"^Ran (\d+) tests?", out, re.M)
        status = re.findall(r"^(OK|FAILED)\b(.*)$", out, re.M)
        failed = [f"{kind} {test} ({where})" for kind, test, where in
                  re.findall(r"^(FAIL|ERROR): (\S+) \((\S+)\)", out, re.M)]
        ok = code == 0
        result = {"name": name, "seconds": seconds, "tests": int(ran[-1]) if ran else 0, "ok": ok,
                  "status": "".join(status[-1]).strip() if status else ("EXPIRÉ" if code == -1 else f"code {code}"),
                  "failed": failed, "tail": "" if ok else _tail(out, 40)}
        results.append(result)
        print(f"[{index}/{len(files)}] {name:<45} {seconds:7.1f} s  {result['status']}", flush=True)
    return results


def update_heavy(results: list[dict]) -> list[tuple[str, float, int]]:
    """Réécrit la liste des fichiers lourds : ceux mesurés ici remplacent leur ancienne mesure, les autres restent."""
    kept = {}
    try:
        with open(HEAVY_FILE, encoding="utf-8") as handle:
            for line in handle:
                name, _sep, note = line.partition("#")
                if name.strip():
                    kept[name.strip()] = note.strip()
    except OSError:
        pass
    for r in results:
        kept.pop(r["name"], None)
        if r["seconds"] > LOURD:
            kept[r["name"]] = f"{r['seconds']:.0f} s ({r['tests']} tests), mesuré le {datetime.date.today():%Y-%m-%d}"
    lines = ["# Fichiers de test LOURDS : jamais lancés en entier par l'agent pendant une requête (tools/hooks/garde_fous.py) ;",
             f"# leurs tests se lancent par leur nom. Réécrit par `tools/fluidite.py` (fichiers de plus de {LOURD:.0f} s)."]
    lines += [f"{name:<40} # {note}" for name, note in sorted(kept.items())]
    with open(HEAVY_FILE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return sorted(kept.items())


def run_benches() -> list[dict]:
    env = _env(False)
    out = []
    for title, args in BANCS:
        if not os.path.exists(os.path.join(ROOT, args[0])):
            continue
        print(f"Banc : {title}...", flush=True)
        code, seconds, text = _run([PY, *args], TIMEOUT_BANC, env)
        out.append({"title": title, "command": " ".join(args), "code": code, "seconds": seconds, "tail": _tail(text)})
    return out


def queue_items() -> list[tuple[str, str]]:
    try:
        with open(QUEUE_FILE, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return []
    return [(m.group(1).strip(" —-"), m.group(2)) for m in re.finditer(r"^- \[ \] (.*)`([^`]+)`\s*$", text, re.M)]


def run_queue() -> list[dict]:
    env = _env(False)
    out = []
    for description, command in queue_items():
        args = shlex.split(command)
        if args and args[0] in ("python", "python3", "py"):
            args[0] = PY
        print(f"File : {description}...", flush=True)
        code, seconds, text = _run(args, TIMEOUT_BANC, env)
        out.append({"title": description, "command": command, "code": code, "seconds": seconds, "tail": _tail(text)})
    return out


def write_report(started, tests, heavy, benches, queue, options) -> None:
    lines = [f"# Rapport de fluidité ({started:%Y-%m-%d %H:%M})", "",
             f"Généré par `tools/fluidite.py` ({options or 'options par défaut'}) en "
             f"{(datetime.datetime.now() - started).total_seconds() / 60:.0f} min. L'agent le lit à la requête "
             "suivante : échecs et dépassements d'abord.", ""]
    if tests is not None:
        failed = [r for r in tests if not r["ok"]]
        total = sum(r["tests"] for r in tests)
        lines += ["## Tests", "", f"{len(tests)} fichiers, {total} tests, {len(failed)} fichier(s) en échec, "
                  f"{sum(r['seconds'] for r in tests) / 60:.0f} min.", ""]
        for r in failed:
            lines += [f"### ÉCHEC : {r['name']} ({r['status']})", ""] + [f"- {f}" for f in r["failed"]] + \
                     ["", "```", r["tail"], "```", ""]
        lines += ["### Durées (les plus longs d'abord)", "", "| Fichier | Tests | Durée | Résultat |", "|---|---|---|---|"]
        lines += [f"| {r['name']} | {r['tests']} | {r['seconds']:.1f} s | {r['status']} |"
                  for r in sorted(tests, key=lambda r: -r["seconds"])]
        lines += ["", f"Fichiers lourds (> {LOURD:.0f} s, `tools/hooks/tests_lourds.txt`) : "
                  + (", ".join(name for name, _note in heavy) or "aucun"), ""]
    for title, items in (("Bancs de fluidité", benches), ("File d'attente (docs/agents/a_mesurer.md)", queue)):
        if items is None:
            continue
        lines += [f"## {title}", ""]
        if not items:
            lines += ["(rien)", ""]
        for item in items:
            state = "OK" if item["code"] == 0 else f"code {item['code']}"
            lines += [f"### {item['title']} ({state}, {item['seconds']:.0f} s)", "", f"`{item['command']}`", "",
                      "```", item["tail"], "```", ""]
    with open(REPORT_FILE, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    needle = None
    if "--filtre" in argv:
        at = argv.index("--filtre")
        needle = argv[at + 1] if at + 1 < len(argv) else None
    started = datetime.datetime.now()
    tests = heavy = benches = queue = None
    if "--sans-tests" not in argv:
        tests = run_tests("--lent" in argv, needle)
        heavy = update_heavy(tests)
    if "--sans-bancs" not in argv:
        benches = run_benches()
    if "--sans-file" not in argv:
        queue = run_queue()
    write_report(started, tests, heavy, benches, queue, " ".join(argv))
    print(f"\nRapport : {REPORT_FILE}")
    return 0 if not tests or all(r["ok"] for r in tests) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
