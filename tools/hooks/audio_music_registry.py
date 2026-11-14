"""Registre de la mission FM Audio / FM Music (`docs/agents/audio_music_state.json`) : lecture, VÉRIFICATEUR
déterministe et verdict de poursuite. Bibliothèque standard SEULEMENT (lancé par les hooks avec `python -S`).

Le registre est la SEULE source de vérité de l'avancement (les tâches natives de Claude Code n'en sont qu'une vue,
par leur identifiant `[T-…]` dans le sujet). Schéma (version 1) :
- `requirements` : exigences STABLES (`id` R-…, `title`, `phase`, `validations` : drapeaux requis parmi
  automatic / performance / hardware / human, `na` : motif d'une validation non applicable) ;
- `tasks` : `id` T-…, `requirement`, `phase`, `title`, `kind` (code, doc, decision, perf, hardware, human),
  `status` (todo, in_progress, implemented, blocked), `depends_on`, `criteria`, `paths` (fichiers utiles, servent au
  progrès et aux preuves), `blocker` (obligatoire si blocked), `next_action` ;
- `evidence` : preuves PRODUITES PAR LE RUNNER (`audio_music_guard.py run`), jamais écrites à la main : commande,
  code retour, tests lancés, durée, environnement, empreintes (taille, mtime, sha256) des seuls fichiers concernés ;
- `blockers`, `decisions` (liens vers la doc), `next_action`.

`baseline_requirements` : identifiants du périmètre INITIAL ; en retirer un du registre est un problème (on divise
une exigence, on ne la supprime pas).

États calculés (jamais stockés) : une exigence est VALIDÉE quand chacune de ses validations requises l'est :
automatic = toutes ses tâches non manuelles `implemented` avec une preuve réussie et fraîche, dont au moins une
tâche `code` ou `perf` (des tâches doc / decision seules ne valident pas un comportement, sauf `doc_only`) ; performance /
hardware / human = une confirmation de l'UTILISATEUR (phrase « VALIDE R-… <type> » tapée dans la conversation,
enregistrée par le hook UserPromptSubmit hors du registre, voir `audio_music_guard.py`).

Fraîcheur : le hook Stop compare seulement taille + mtime (rapide) ; un écart rend la preuve « à vérifier »,
`check --refresh` recalcule le sha256 (même contenu = preuve rafraîchie, sinon périmée)."""
from __future__ import annotations

import hashlib
import json
import os

SCHEMA_VERSION = 1
TASK_STATES = ("todo", "in_progress", "implemented", "blocked")
TASK_KINDS = ("code", "doc", "decision", "perf", "hardware", "human")
MANUAL_KINDS = ("hardware", "human")            # validées par l'utilisateur, jamais par une preuve automatique
VALIDATION_KINDS = ("automatic", "performance", "hardware", "human")
CONFIRMABLE = ("performance", "hardware", "human")


class RegistryError(Exception):
    """Registre illisible ou de structure invalide (le diagnostic est le message)."""


# --- Lecture / écriture ---------------------------------------------------------------------------------------------

def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise RegistryError(f"registre absent : {path}") from None
    except (OSError, ValueError) as error:
        raise RegistryError(f"registre illisible ou tronqué ({path}) : {error}") from None
    if not isinstance(data, dict):
        raise RegistryError("le registre n'est pas un objet JSON")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError(f"schema_version {data.get('schema_version')!r} inconnue (attendue {SCHEMA_VERSION})")
    for key in ("requirements", "tasks", "evidence"):
        if not isinstance(data.get(key), list):
            raise RegistryError(f"clé « {key} » absente ou non liste")
    return data


def save(path: str, data: dict) -> None:
    """Écriture atomique (fichier temporaire puis remplacement) : jamais de registre à moitié écrit."""
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(tmp, path)


# --- Empreintes de fichiers -----------------------------------------------------------------------------------------

def _abs(root: str, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(root, rel)


def stat_of(root: str, rel: str) -> dict | None:
    try:
        st = os.stat(_abs(root, rel))
    except OSError:
        return None
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def sha256_of(root: str, rel: str) -> str | None:
    digest = hashlib.sha256()
    try:
        with open(_abs(root, rel), "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def fingerprint_files(root: str, paths) -> dict:
    out = {}
    for rel in sorted(set(paths)):
        st = stat_of(root, rel)
        out[rel] = dict(st, sha256=sha256_of(root, rel)) if st else {"missing": True}
    return out


def evidence_freshness(root: str, ev: dict, deep: bool = False) -> str:
    """'fresh', 'suspect' (taille / date changées, contenu non relu) ou 'stale' (contenu changé ou fichier perdu)."""
    state = "fresh"
    for rel, fp in (ev.get("files") or {}).items():
        if fp.get("missing"):
            if stat_of(root, rel) is not None:
                return "stale"                              # apparu depuis la preuve
            continue
        st = stat_of(root, rel)
        if st is None:
            return "stale"
        if st["size"] != fp.get("size"):
            return "stale"
        if st["mtime_ns"] != fp.get("mtime_ns"):
            if not deep:
                state = "suspect"
            elif sha256_of(root, rel) != fp.get("sha256"):
                return "stale"
    return state


def refresh_evidence(root: str, data: dict) -> int:
    """`check --refresh` : preuve « suspecte » au contenu inchangé -> dates mises à jour. Renvoie le nombre."""
    count = 0
    for ev in data["evidence"]:
        for rel, fp in (ev.get("files") or {}).items():
            st = stat_of(root, rel)
            if st and not fp.get("missing") and st["size"] == fp.get("size") and st["mtime_ns"] != fp.get("mtime_ns") \
                    and sha256_of(root, rel) == fp.get("sha256"):
                fp["mtime_ns"] = st["mtime_ns"]
                count += 1
    return count


# --- Vérificateur ---------------------------------------------------------------------------------------------------

def _cycles(tasks: dict) -> list[str]:
    seen, stack, out = set(), set(), []

    def visit(tid):
        if tid in stack:
            out.append(tid)
            return
        if tid in seen or tid not in tasks:
            return
        stack.add(tid)
        for dep in tasks[tid].get("depends_on") or ():
            visit(dep)
        stack.discard(tid)
        seen.add(tid)
    for tid in tasks:
        visit(tid)
    return sorted(set(out))


def best_evidence(data: dict, task_id: str) -> dict | None:
    """Dernière preuve RÉUSSIE de la tâche (code retour 0)."""
    ok = [ev for ev in data["evidence"] if ev.get("task") == task_id and ev.get("returncode") == 0]
    return ok[-1] if ok else None


def analyse(data: dict, root: str, confirmations=(), deep: bool = False, stalled=()) -> dict:
    """Vérifie le registre et calcule le verdict. Ne lance rien, ne lit que le registre et l'état des fichiers.

    Renvoie {"verdict": continue | complete | blocked | invalid, "problems", "actionable" [(id, action)],
    "requirements": {id: {...}}, "counts", "blockers", "pending_manual"}."""
    problems: list[str] = []
    reqs = {}
    for r in data["requirements"]:
        rid = r.get("id")
        if not rid or rid in reqs:
            problems.append(f"exigence sans id ou en double : {rid!r}")
            continue
        reqs[rid] = r
    tasks = {}
    for t in data["tasks"]:
        tid = t.get("id")
        if not tid or tid in tasks:
            problems.append(f"tâche sans id ou en double : {tid!r}")
            continue
        tasks[tid] = t
        if t.get("requirement") not in reqs:
            problems.append(f"{tid} : exigence inconnue {t.get('requirement')!r}")
        if t.get("status") not in TASK_STATES:
            problems.append(f"{tid} : statut invalide {t.get('status')!r}")
        if t.get("kind", "code") not in TASK_KINDS:
            problems.append(f"{tid} : type invalide {t.get('kind')!r}")
        for dep in t.get("depends_on") or ():
            if dep not in {x.get("id") for x in data["tasks"]}:
                problems.append(f"{tid} : dépendance inconnue {dep}")
        if t.get("status") == "blocked" and not t.get("blocker"):
            problems.append(f"{tid} : bloquée sans motif (`blocker`)")
    for cyc in _cycles(tasks):
        problems.append(f"dépendance cyclique autour de {cyc}")
    by_req: dict[str, list] = {rid: [] for rid in reqs}
    for t in tasks.values():
        by_req.setdefault(t.get("requirement"), []).append(t)
    for rid in reqs:
        if not by_req.get(rid):
            problems.append(f"{rid} : exigence sans tâche")
    for rid in data.get("baseline_requirements") or ():
        if rid not in reqs:
            problems.append(f"{rid} : exigence du périmètre initial RETIRÉE (interdit ; la diviser, pas la supprimer)")
    ev_ids = set()
    for ev in data["evidence"]:
        if not ev.get("runner"):
            problems.append(f"preuve {ev.get('id')!r} non produite par le runner (écrite à la main ?)")
        if ev.get("task") not in tasks:
            problems.append(f"preuve {ev.get('id')!r} : tâche inconnue {ev.get('task')!r}")
        if ev.get("id") in ev_ids:
            problems.append(f"preuve en double {ev.get('id')!r}")
        ev_ids.add(ev.get("id"))

    # Fraîcheur des preuves des tâches « implemented » (faux statut si aucune preuve réussie).
    proof: dict[str, str] = {}
    for tid, t in tasks.items():
        if t.get("status") != "implemented" or t.get("kind") in MANUAL_KINDS:
            continue
        ev = best_evidence(data, tid)
        if ev is None:
            problems.append(f"{tid} : « implemented » sans preuve réussie du runner (faux statut)")
            proof[tid] = "missing"
        else:
            proof[tid] = evidence_freshness(root, ev, deep)

    confirmed = {(c.get("requirement"), c.get("kind")) for c in confirmations}
    req_state = {}
    pending_manual = []
    for rid, r in reqs.items():
        need = r.get("validations") or {"automatic": True}
        st = {}
        for kind in VALIDATION_KINDS:
            if not need.get(kind):
                continue
            if kind == "automatic":
                auto = [t for t in by_req.get(rid, []) if t.get("kind", "code") not in MANUAL_KINDS]
                real = r.get("doc_only") or any(t.get("kind", "code") in ("code", "perf") for t in auto)
                st[kind] = "passed" if auto and real and all(proof.get(t["id"]) == "fresh" for t in auto) \
                    else "pending"
            else:
                st[kind] = "passed" if (rid, kind) in confirmed else "pending"
                if st[kind] == "pending":
                    pending_manual.append(f"{rid} {kind}")
        req_state[rid] = {"validations": st, "validated": bool(st) and all(v == "passed" for v in st.values())}

    def done(tid):
        return tasks.get(tid, {}).get("status") == "implemented"

    actionable = []
    for tid, t in tasks.items():
        if tid in stalled:
            continue
        status, kind = t.get("status"), t.get("kind", "code")
        if status == "implemented" and proof.get(tid) in ("stale", "missing"):
            actionable.append((tid, f"re-prouver {tid} (preuve {proof[tid]}) avec `audio_music_guard.py run`"))
        elif status == "implemented" and proof.get(tid) == "suspect":
            actionable.append((tid, f"{tid} : fichiers modifiés depuis la preuve : `check --refresh` ou re-prouver"))
        elif status in ("todo", "in_progress") and kind not in MANUAL_KINDS \
                and all(done(d) for d in t.get("depends_on") or ()):
            actionable.append((tid, t.get("next_action") or f"{tid} : {t.get('title', '')}"))
    actionable.sort(key=lambda a: (tasks[a[0]].get("status") != "in_progress", tasks[a[0]].get("phase", ""), a[0]))

    counts = {s: sum(1 for t in tasks.values() if t.get("status") == s) for s in TASK_STATES}
    validated = sum(1 for s in req_state.values() if s["validated"])
    blockers = [f"{tid} : {t.get('blocker')}" for tid, t in tasks.items() if t.get("status") == "blocked"]
    if problems:
        verdict = "invalid"
    elif actionable:
        verdict = "continue"
    elif reqs and validated == len(reqs):
        verdict = "complete"
    else:
        verdict = "blocked"
    return {"verdict": verdict, "problems": problems, "actionable": actionable, "requirements": req_state,
            "counts": dict(counts, requirements=len(reqs), validated=validated), "blockers": blockers,
            "pending_manual": pending_manual}


def progress_key(data: dict) -> str:
    """Empreinte du PROGRÈS UTILE : statuts, motifs de blocage, dépendances et preuves (identifiants, codes
    retour). Les dates, `next_action` et les reformulations n'en font pas partie."""
    core = {
        "req": sorted(r.get("id", "") for r in data.get("requirements", [])),
        "tasks": sorted((t.get("id", ""), t.get("status", ""), str(t.get("blocker") or ""),
                         tuple(t.get("depends_on") or ())) for t in data.get("tasks", [])),
        "ev": sorted((e.get("id", ""), e.get("returncode")) for e in data.get("evidence", [])),
    }
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def summary(result: dict, limit: int = 3) -> str:
    """État compact pour la conversation (l'évaluateur de /goal ne lit pas les fichiers)."""
    c = result["counts"]
    parts = [f"verdict={result['verdict']}", f"exigences validées {c['validated']}/{c['requirements']}",
             f"tâches implémentées {c['implemented']}, en cours {c['in_progress']}, à faire {c['todo']}, "
             f"bloquées {c['blocked']}", f"réalisables {len(result['actionable'])}"]
    if result["pending_manual"]:
        parts.append(f"validations utilisateur en attente {len(result['pending_manual'])}")
    if result["problems"]:
        parts.append("problèmes : " + " ; ".join(result["problems"][:limit]))
    if result["actionable"]:
        parts.append("prochaine : " + result["actionable"][0][1])
    if result["blockers"]:
        parts.append("blocages : " + " ; ".join(result["blockers"][:limit]))
    return " | ".join(parts)
