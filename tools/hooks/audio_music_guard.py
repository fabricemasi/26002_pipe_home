"""Contrôleur de POURSUITE de la mission FM Audio / FM Music (`docs/agents/mission_audio_music.md`, § 11).
Bibliothèque standard seulement, lancé avec `python -S`. Le registre et son vérificateur : `audio_music_registry.py`.

HOOKS (déclarés dans `.claude/settings.local.json`, en PLUS du garde-fou `garde_fous.py` de `.claude/settings.json`,
qui reste actif : les hooks des fichiers de réglages s'additionnent) :
- `context` (SessionStart) : contexte court (mission, verdict, prochaine action, blocages) ;
- `stop` (Stop) : bloque l'arrêt tant qu'une tâche réalisable reste (`{"decision":"block","reason":…}`) ;
- `task` (TaskCompleted) : refuse (sortie 2) de clore une tâche native `[T-…]` sans preuve fraîche du runner ;
- `prompt` (UserPromptSubmit) : phrases de l'UTILISATEUR seulement : « STOP MISSION » (arrêt demandé),
  « VALIDE R-… humain|matériel|performance » (confirmation, jamais écrite par l'agent).

TOUT EST INERTE hors d'un run ARMÉ et LIÉ à la session : une autre conversation du projet n'est jamais retenue
(sortie immédiate, sans lire le registre). Liaison : variable `PIPE_AUDIO_MUSIC_RUN` du terminal (liée au premier
`session_id` vu), ou `bind --run-id ID` lancé depuis la session (appli de bureau : `CLAUDE_CODE_SESSION_ID`). Un
second écrivain sur le même run est refusé (sauf `bind --force`, reprise volontaire dans une nouvelle conversation).

Progrès : empreinte du registre (`progress_key`) + taille / date des fichiers `paths` des tâches en cours. Un
horodatage, une reformulation ou un test relancé à l'identique n'en est pas. 3 arrêts sans progrès sur la même
tâche -> tâche « calée » (écartée, l'agent doit documenter son blocage) ; 3 sans progrès ni autre tâche, ou 6 sans
progrès du tout -> arrêt diagnostiqué autorisé (`limit_reached`). Compteurs gardés dans le fichier du run
(`.claude/audio_music_runs/<run>.json`) à travers les reprises. `stop_hook_active` n'est PAS une permission de
quitter. Le hook ne lance ni test, ni build, ni réseau, ni git : il lit le registre et l'état des fichiers.

CLI : `arm|disarm|bind|status --run-id ID`, `check [--refresh] [--deep]`, `run --task T [--file F]… -- commande`
(le RUNNER : seule façon d'écrire une preuve ; il refuse ce que `garde_fous.py` refuse)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import audio_music_registry as reg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
RUN_ENV = "PIPE_AUDIO_MUSIC_RUN"
STALL_TASK = 3          # arrêts sans progrès sur la même tâche avant de la déclarer calée
STALL_STOP = 3          # arrêts consécutifs sans progrès NI alternative avant l'arrêt diagnostiqué
HARD_STOP = 6           # arrêts consécutifs sans progrès du tout : arrêt diagnostiqué quoi qu'il reste
INVALID_TRIES = 3       # tentatives de réparation d'un registre invalide
HISTORY = 40
STOP_WORDS = re.compile(r"^\s*(stop\s+mission|arr[eê]te\s+la\s+mission)\b", re.I)
CONFIRM_RE = re.compile(r"^\s*VALIDE\s+(R-[\w.-]+)\s+(performance|mat[eé]riel|hardware|humain|human)\b", re.I | re.M)
CONFIRM_KIND = {"performance": "performance", "materiel": "hardware", "matériel": "hardware",
                "hardware": "hardware", "humain": "human", "human": "human"}
TASK_REF = re.compile(r"\[(T-[\w.-]+)\]")


PATH_KEYS = ("state_path", "root", "confirm_path")   # chemins propres à un run (essais sur registre fictif)
_RUN_PATHS: dict = {}


def use_run(run: dict | None) -> None:
    """Le run retenu impose ses chemins (`arm --state/--root/--confirm`), sinon variables d'environnement, sinon
    le vrai registre de la mission."""
    _RUN_PATHS.clear()
    _RUN_PATHS.update({k: run[k] for k in PATH_KEYS if run and run.get(k)})


def project_root() -> str:
    return _RUN_PATHS.get("root") or os.environ.get("PIPE_AUDIO_MUSIC_ROOT") or ROOT


def state_path() -> str:
    return _RUN_PATHS.get("state_path") or os.environ.get("PIPE_AUDIO_MUSIC_STATE") or os.path.join(
        ROOT, "docs", "agents", "audio_music_state.json")


def runs_dir() -> str:
    return os.environ.get("PIPE_AUDIO_MUSIC_RUNS_DIR") or os.path.join(ROOT, ".claude", "audio_music_runs")


def confirm_path() -> str:
    return _RUN_PATHS.get("confirm_path") or os.environ.get("PIPE_AUDIO_MUSIC_CONFIRM") or os.path.join(
        ROOT, "docs", "agents", "audio_music_confirmations.json")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _out(text: str, stream=None) -> None:
    (stream or sys.stdout).buffer.write((text + "\n").encode("utf-8"))
    (stream or sys.stdout).flush()


# --- Fichiers de run ------------------------------------------------------------------------------------------------

def _run_file(run_id: str) -> str:
    if not re.fullmatch(r"[\w.-]{1,64}", run_id or ""):
        raise SystemExit(f"identifiant de run invalide : {run_id!r}")
    return os.path.join(runs_dir(), f"{run_id}.json")


def load_run(run_id: str) -> dict | None:
    try:
        with open(_run_file(run_id), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def save_run(run: dict) -> None:
    os.makedirs(runs_dir(), exist_ok=True)
    run["history"] = run.get("history", [])[-HISTORY:]
    path = _run_file(run["run_id"])
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(run, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def new_run(run_id: str) -> dict:
    return {"run_id": run_id, "armed": False, "session_id": None, "stop_requested": False, "created": _now(),
            "counters": {"stops": 0, "blocks": 0, "no_progress": 0, "invalid": 0, "attempts": {}},
            "stalled": [], "last_progress": None, "history": []}


def _event(run: dict, kind: str, **info) -> None:
    run.setdefault("history", []).append(dict(at=_now(), event=kind, **info))


def concerned_run(session_id: str | None) -> tuple[dict | None, str]:
    """Run armé de cette session : (run, 'bound') ; run d'un autre écrivain : (run, 'foreign') ; sinon (None, '').
    Le run retenu impose ses chemins (`use_run`)."""
    run, how = _find_run(session_id)
    use_run(run)
    return run, how


def _find_run(session_id: str | None) -> tuple[dict | None, str]:
    env_run = os.environ.get(RUN_ENV, "").strip()
    try:
        names = [n[:-5] for n in os.listdir(runs_dir()) if n.endswith(".json")]
    except OSError:
        names = []
    for name in names:
        run = load_run(name)
        if run and run.get("armed") and session_id and run.get("session_id") == session_id:
            return run, "bound"
    if env_run:
        run = load_run(env_run)
        if run and run.get("armed"):
            if not run.get("session_id") and session_id:
                run["session_id"] = session_id
                _event(run, "bind", session=session_id, via=RUN_ENV)
                save_run(run)
                return run, "bound"
            if run.get("session_id") != session_id:
                return run, "foreign"
    return None, ""


def load_confirmations() -> list:
    try:
        with open(confirm_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def analyse_now(stalled=(), deep=False) -> tuple[dict | None, dict]:
    try:
        data = reg.load(state_path())
    except reg.RegistryError as error:
        return None, {"verdict": "invalid", "problems": [str(error)], "actionable": [], "blockers": [],
                      "pending_manual": [], "counts": {s: 0 for s in reg.TASK_STATES} | {"requirements": 0,
                                                                                          "validated": 0}}
    return data, reg.analyse(data, project_root(), load_confirmations(), deep=deep, stalled=stalled)


def _paths_key(data: dict | None) -> str:
    if not data:
        return ""
    root = project_root()
    parts = []
    for t in data["tasks"]:
        if t.get("status") == "in_progress":
            for rel in t.get("paths") or ():
                st = reg.stat_of(root, rel)
                parts.append(f"{rel}:{st['size']}:{st['mtime_ns']}" if st else f"{rel}:-")
    return hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()[:12] if parts else ""


# --- Hooks ----------------------------------------------------------------------------------------------------------

def _stdin() -> dict:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def hook_context(event: dict) -> int:
    run, how = concerned_run(event.get("session_id"))
    if run is None:
        return 0
    if how == "foreign":
        _out(f"[Mission audio] Le run {run['run_id']} est déjà lié à une autre session : cette conversation N'ÉCRIT "
             f"PAS le registre (un seul écrivain). Reprise volontaire : `audio_music_guard.py bind --run-id "
             f"{run['run_id']} --force`.")
        return 0
    _data, result = analyse_now(run.get("stalled", ()))
    lines = [f"[Mission audio, run {run['run_id']}] Mission : docs/agents/mission_audio_music.md ; registre : "
             f"docs/agents/audio_music_state.json (seule source de vérité). État : {reg.summary(result)}.",
             "Protocole : tâche suivante -> lire seulement son contexte -> incrément -> tests ciblés PAR NOM via "
             "`python -S tools/hooks/audio_music_guard.py run --task T -- <commande>` -> statut dans le registre -> "
             "publier `status` dans la conversation -> tâche suivante. Ne rien certifier sans preuve du runner."]
    if run.get("stop_requested"):
        lines.append("ARRÊT DEMANDÉ par l'utilisateur : termine proprement (PASSATION, registre) puis arrête-toi.")
    _out("\n".join(lines))
    return 0


def _allow(message: str | None = None) -> int:
    if message:
        _out(json.dumps({"systemMessage": message}, ensure_ascii=False))
    return 0


def hook_stop(event: dict) -> int:
    run, how = concerned_run(event.get("session_id"))
    if run is None or how != "bound":
        return 0
    counters = run.setdefault("counters", new_run("x")["counters"])
    counters["stops"] = counters.get("stops", 0) + 1
    if run.get("stop_requested"):
        _event(run, "stop_allowed", why="arrêt demandé par l'utilisateur")
        save_run(run)
        return _allow("Mission audio : arrêt demandé par l'utilisateur, mission INACHEVÉE (registre conservé).")
    stalled = list(run.get("stalled", []))
    data, result = analyse_now(stalled)
    key = (reg.progress_key(data) if data else "invalid") + "/" + _paths_key(data)
    progress = key != run.get("last_progress")
    run["last_progress"] = key
    if progress:
        counters["no_progress"] = 0
        counters["attempts"] = {}
        if stalled:
            run["stalled"] = stalled = []
            data, result = analyse_now(())
    else:
        counters["no_progress"] = counters.get("no_progress", 0) + 1
    verdict = result["verdict"]
    if verdict == "invalid":
        counters["invalid"] = counters.get("invalid", 0) + 1 if not progress else 1
        if counters["invalid"] > INVALID_TRIES:
            _event(run, "stop_allowed", why="registre invalide après réparations", problems=result["problems"][:3])
            save_run(run)
            return _allow("Mission audio : registre INVALIDE malgré " f"{INVALID_TRIES} tentatives, arrêt diagnostiqué "
                          "(mission inachevée) : " + " ; ".join(result["problems"][:3]))
        return _block(run, "Registre de mission invalide, à RÉPARER sans retirer d'exigence (tentative "
                      f"{counters['invalid']}/{INVALID_TRIES}) : " + " ; ".join(result["problems"][:4]))
    counters["invalid"] = 0
    if not progress and counters["no_progress"] >= HARD_STOP:
        return _limit(run, result)
    if verdict == "continue" and not progress:
        tid = result["actionable"][0][0]
        attempts = counters.setdefault("attempts", {})
        attempts[tid] = attempts.get(tid, 0) + 1
        if attempts[tid] >= STALL_TASK:
            stalled.append(tid)
            run["stalled"] = stalled
            _event(run, "stalled", task=tid)
            _data, result = analyse_now(stalled)
            if result["verdict"] == "continue":
                return _block(run, f"{tid} : {STALL_TASK} arrêts sans progrès. Documente son blocage dans le "
                              f"registre (status blocked + blocker précis), puis passe à : {result['actionable'][0][1]}")
            return _block(run, f"{tid} : {STALL_TASK} arrêts sans progrès et aucune autre tâche réalisable. "
                          "Documente son blocage dans le registre (status blocked + blocker précis, ce qu'il faut à "
                          "l'utilisateur), mets la PASSATION à jour, puis arrête-toi.")
    elif not progress and stalled and counters["no_progress"] >= STALL_STOP:
        return _limit(run, result)                          # calée, non documentée, rien d'autre : arrêt diagnostiqué
    if verdict == "continue":
        return _block(run, f"Tâche réalisable ({len(result['actionable'])} au total) : {result['actionable'][0][1]}. "
                      "Ensuite : preuve via le runner, registre à jour, `status` publié. "
                      + ("" if progress else f"[{counters['no_progress']} arrêt(s) sans progrès]"))
    _event(run, "stop_allowed", verdict=verdict)
    save_run(run)
    if verdict == "complete":
        return _allow("Mission audio : toutes les exigences et validations requises sont satisfaites.")
    return _allow("Mission audio INACHEVÉE : aucune tâche réalisable sans intervention. " + reg.summary(result))


def _block(run: dict, reason: str) -> int:
    run["counters"]["blocks"] = run["counters"].get("blocks", 0) + 1
    _event(run, "block", reason=reason[:300])
    save_run(run)
    _out(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def _limit(run: dict, result: dict) -> int:
    _event(run, "limit_reached", no_progress=run["counters"]["no_progress"], stalled=run.get("stalled"))
    save_run(run)
    return _allow(f"Mission audio : limit_reached ({run['counters']['no_progress']} arrêts sans progrès utile), "
                  f"arrêt diagnostiqué, mission INACHEVÉE. Tâches calées : {', '.join(run.get('stalled') or []) or '-'}"
                  f". {reg.summary(result)}")


def hook_task(event: dict) -> int:
    run, how = concerned_run(event.get("session_id"))
    if run is None or how != "bound":
        return 0
    match = TASK_REF.search(str(event.get("task_subject") or "") + " " + str(event.get("task_description") or ""))
    if not match:
        return 0                                            # tâche native sans lien avec le registre
    tid = match.group(1)
    try:
        data = reg.load(state_path())
    except reg.RegistryError as error:
        return _refuse(f"registre invalide, clôture de {tid} refusée : {error}")
    task = next((t for t in data["tasks"] if t.get("id") == tid), None)
    if task is None:
        return _refuse(f"{tid} absente du registre : ajoute-la (avec son exigence) avant de la clore")
    if task.get("kind") in reg.MANUAL_KINDS:
        return _refuse(f"{tid} est une validation {task.get('kind')} : seule la confirmation de l'utilisateur la clôt")
    if task.get("status") != "implemented":
        return _refuse(f"{tid} a le statut {task.get('status')!r} dans le registre (attendu « implemented »)")
    ev = reg.best_evidence(data, tid)
    if ev is None:
        return _refuse(f"{tid} : aucune preuve réussie du runner (`audio_music_guard.py run --task {tid} -- …`)")
    fresh = reg.evidence_freshness(project_root(), ev)
    if fresh != "fresh":
        return _refuse(f"{tid} : preuve {fresh} (fichiers modifiés depuis) : re-prouver ou `check --refresh`")
    return 0


def _refuse(message: str) -> int:
    _out(f"Clôture refusée par le contrôleur de mission (audio_music_guard.py) : {message}", sys.stderr)
    return 2


def hook_prompt(event: dict) -> int:
    prompt = str(event.get("prompt") or "")
    notes = []
    if STOP_WORDS.search(prompt):
        run, how = concerned_run(event.get("session_id"))
        if run is not None and how == "bound":
            run["stop_requested"] = True
            _event(run, "stop_requested", via="user_prompt")
            save_run(run)
            notes.append("Arrêt de la mission demandé par l'utilisateur : finis l'action en cours proprement "
                         "(registre, PASSATION si tâche inachevée), puis arrête-toi. Réarmement : `arm`.")
    found = CONFIRM_RE.findall(prompt)
    if found:
        try:
            ids = {r.get("id") for r in reg.load(state_path())["requirements"]}
        except reg.RegistryError:
            ids = set()
        items = load_confirmations()
        for rid, kind in found:
            kind = CONFIRM_KIND[kind.lower()]
            if rid not in ids:
                notes.append(f"Confirmation ignorée : {rid} n'est pas une exigence du registre.")
                continue
            items.append({"requirement": rid, "kind": kind, "at": _now(), "via": "user_prompt",
                          "session_id": event.get("session_id"), "text": prompt.strip()[:200]})
            notes.append(f"Validation {kind} de {rid} confirmée par l'utilisateur (enregistrée).")
        tmp = confirm_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(items, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, confirm_path())
    if notes:
        _out("[Mission audio] " + " ".join(notes))
    return 0


# --- Commandes ------------------------------------------------------------------------------------------------------

def _arg(args: list, name: str, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def cmd_arm(run_id: str, paths: dict) -> int:
    run = load_run(run_id) or new_run(run_id)
    run.update({k: os.path.abspath(v) for k, v in paths.items() if v})
    use_run(run)
    data, result = analyse_now()
    if result["verdict"] == "invalid":
        _out("Armement REFUSÉ : registre invalide : " + " ; ".join(result["problems"][:5]), sys.stderr)
        return 1
    run.update(armed=True, stop_requested=False)
    _event(run, "arm")
    save_run(run)
    _out(f"Run {run_id} ARMÉ (session liée : {run.get('session_id') or 'aucune, liée au premier hook avec ' + RUN_ENV + ' ou par bind'}). "
         f"Compteurs conservés : {run['counters']}.\n{reg.summary(result)}")
    return 0


def cmd_disarm(run_id: str) -> int:
    run = load_run(run_id)
    if run is None:
        _out(f"Run {run_id} inconnu.", sys.stderr)
        return 1
    run["armed"] = False
    _event(run, "disarm")
    save_run(run)
    _out(f"Run {run_id} DÉSARMÉ : plus aucune poursuite forcée (réarmement explicite : arm).")
    return 0


def cmd_bind(run_id: str, session: str | None, force: bool) -> int:
    run = load_run(run_id)
    session = session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if run is None or not run.get("armed"):
        _out(f"Run {run_id} absent ou désarmé : `arm --run-id {run_id}` d'abord.", sys.stderr)
        return 1
    if not session:
        _out("Identifiant de session introuvable (ni --session, ni CLAUDE_CODE_SESSION_ID).", sys.stderr)
        return 1
    if run.get("session_id") not in (None, session) and not force:
        _out(f"Run {run_id} déjà lié à la session {run['session_id']} : second écrivain refusé "
             "(reprise volontaire dans une nouvelle conversation : --force).", sys.stderr)
        return 1
    previous = run.get("session_id")
    run["session_id"] = session
    _event(run, "bind", session=session, previous=previous, forced=force)
    save_run(run)
    _out(f"Run {run_id} lié à la session {session}.")
    return 0


def cmd_status(run_id: str | None) -> int:
    run = load_run(run_id) if run_id else None
    _data, result = analyse_now(run.get("stalled", ()) if run else ())
    _out(reg.summary(result, limit=5))
    if run is not None:
        c = run["counters"]
        _out(f"run {run_id} : armé={run.get('armed')} session={run.get('session_id')} arrêt_demandé="
             f"{run.get('stop_requested')} | arrêts={c.get('stops')} blocages={c.get('blocks')} sans_progrès="
             f"{c.get('no_progress')} calées={run.get('stalled') or '-'}")
    elif run_id:
        _out(f"run {run_id} : inconnu")
    return 0


def cmd_check(refresh: bool, deep: bool) -> int:
    try:
        data = reg.load(state_path())
    except reg.RegistryError as error:
        _out(f"verdict=invalid | {error}")
        return 1
    if refresh:
        count = reg.refresh_evidence(project_root(), data)
        if count:
            reg.save(state_path(), data)
        _out(f"{count} empreinte(s) rafraîchie(s) (contenu identique).")
    result = reg.analyse(data, project_root(), load_confirmations(), deep=deep or refresh)
    _out(reg.summary(result, limit=20))
    return 1 if result["verdict"] == "invalid" else 0


def _garde_fous_problem(command: str) -> str | None:
    try:
        import garde_fous
        return garde_fous._search_problem(command) or garde_fous._tests_problem(command)
    except Exception:                                       # noqa: BLE001
        return None


def cmd_run(args: list) -> int:
    """Le RUNNER : lance la commande, enregistre la preuve (jamais écrite à la main)."""
    import subprocess                                       # paresseux : les hooks n'en ont pas besoin
    if "--" not in args:
        _out("usage : run --task T [--file F]… [--timeout S] -- commande…", sys.stderr)
        return 2
    head, command = args[:args.index("--")], args[args.index("--") + 1:]
    tid = _arg(head, "--task")
    files = [head[i + 1] for i, a in enumerate(head) if a == "--file" and i + 1 < len(head)]
    timeout = float(_arg(head, "--timeout", 900))
    if not tid or not command:
        _out("--task et une commande sont obligatoires", sys.stderr)
        return 2
    if not os.path.isabs(command[0]):                       # Windows ne résout pas un exécutable relatif à `cwd` :
        for base in (project_root(), ROOT):                 # dossier du run d'abord, puis le dépôt (`.venv/…`)
            if os.path.exists(os.path.join(base, command[0])):
                command = [os.path.join(base, command[0])] + command[1:]
                break
    line = subprocess.list2cmdline(command)
    problem = _garde_fous_problem(line)
    if problem:
        _out(f"Refusé (garde_fous.py) : {problem}", sys.stderr)
        return 2
    try:
        data = reg.load(state_path())
    except reg.RegistryError as error:
        _out(f"registre invalide : {error}", sys.stderr)
        return 2
    task = next((t for t in data["tasks"] if t.get("id") == tid), None)
    if task is None:
        _out(f"{tid} absente du registre", sys.stderr)
        return 2
    run_id = _arg(head, "--run-id") or os.environ.get(RUN_ENV)
    session = os.environ.get("CLAUDE_CODE_SESSION_ID")
    target = os.path.normcase(os.path.abspath(state_path()))
    for name in (n[:-5] for n in _listdir(runs_dir()) if n.endswith(".json")):
        r = load_run(name)                                  # seul compte un run qui écrit CE registre
        own = (r or {}).get("state_path") or os.environ.get("PIPE_AUDIO_MUSIC_STATE") or os.path.join(
            ROOT, "docs", "agents", "audio_music_state.json")
        same = bool(r) and os.path.normcase(os.path.abspath(own)) == target
        if r and same and r.get("armed") and r.get("session_id") and session and r["session_id"] != session:
            _out(f"Run {name} armé et lié à une autre session : second écrivain refusé.", sys.stderr)
            return 2
    start = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=project_root(), capture_output=True, timeout=timeout)
        code, output = proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        code, output = 124, f"délai dépassé ({timeout:.0f} s)"
    except OSError as error:
        code, output = 127, str(error)
    duration = round(time.monotonic() - start, 2)
    ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
    data = reg.load(state_path())                           # relu : la commande a pu durer
    task = next(t for t in data["tasks"] if t.get("id") == tid)
    paths = list(task.get("paths") or ()) + files
    ev = {"id": f"E-{len(data['evidence']) + 1:04d}-{int(time.time())}", "task": tid, "runner": True,
          "command": line, "returncode": code, "tests_run": int(ran[-1]) if ran else None,
          "summary": "\n".join(output.strip().splitlines()[-3:])[-400:], "duration_s": duration, "at": _now(),
          "env": {"python": sys.version.split()[0], "platform": sys.platform, "run": run_id, "session": session},
          "files": reg.fingerprint_files(project_root(), paths)}
    data["evidence"].append(ev)
    reg.save(state_path(), data)
    _out(output[-3000:])
    _out(f"[runner] preuve {ev['id']} : code {code}, {ev['tests_run']} test(s), {duration} s, "
         f"{len(ev['files'])} fichier(s) empreint(s).")
    return code


def _listdir(path: str) -> list:
    try:
        return os.listdir(path)
    except OSError:
        return []


def main(argv: list) -> int:
    if not argv:
        _out(__doc__)
        return 2
    command, args = argv[0], argv[1:]
    hooks = {"context": hook_context, "stop": hook_stop, "task": hook_task, "prompt": hook_prompt}
    if command in hooks:
        return hooks[command](_stdin())
    head = args[:args.index("--")] if "--" in args else args
    run_id = _arg(head, "--run-id")
    if command in ("arm", "disarm", "bind") and not run_id:
        _out(f"{command} exige --run-id ID", sys.stderr)
        return 2
    if command == "arm":
        return cmd_arm(run_id, {"state_path": _arg(head, "--state"), "root": _arg(head, "--root"),
                                "confirm_path": _arg(head, "--confirm")})
    use_run(load_run(run_id or os.environ.get(RUN_ENV, "")) if (run_id or os.environ.get(RUN_ENV)) else None)
    if command == "disarm":
        return cmd_disarm(run_id)
    if command == "bind":
        return cmd_bind(run_id, _arg(args, "--session"), "--force" in args)
    if command == "status":
        return cmd_status(run_id or os.environ.get(RUN_ENV))
    if command == "check":
        return cmd_check("--refresh" in args, "--deep" in args)
    if command == "run":
        return cmd_run(args)
    _out(f"commande inconnue : {command}", sys.stderr)
    return 2


if __name__ == "__main__":
    hook = len(sys.argv) > 1 and sys.argv[1] in ("context", "stop", "task", "prompt")
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as error:                              # noqa: BLE001
        if not hook:
            raise
        _out(f"audio_music_guard : erreur interne ({error!r}), hook ignoré.", sys.stderr)
        sys.exit(0)                                         # un hook en panne ne bloque jamais une session
