"""Bibliothèque commune de FM Audio et FM Music (sans Qt).

Identité de ressource (id stable) ≠ révision (immuable, numérotée) ≠ contenu (fichier, vérifié par
sha256) ≠ emplacement. Une composition ÉPINGLE une révision (Clip.resource + Clip.revision).

Stockage portable, adapté à un dossier synchronisé : un MANIFESTE JSON par ressource
(`resources/<id>/manifest.json`, écrit de façon atomique) et les fichiers de révision à côté
(`r<N><ext>`, copiés à la publication, jamais déplacés ni réécrits). L'index est reconstruit à la
demande depuis les manifestes (aucune base active copiée entre postes). Les cas du cloud sont
traités explicitement : manifeste illisible ou incomplet (diagnostic, ignoré), fichier de
révision pas encore arrivé (révision « en attente », non adoptable), copies de conflit du
synchroniseur (signalées ; révisions de même numéro et de contenu différent = conflit, jamais
fusionnées en silence).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import time
import uuid
from pathlib import Path

from . import media
from .project import Clip, Project, save_json_atomic

LIB_VERSION = 1


def _sha256(path: Path) -> str:
    return media.content_hash(str(path))


class LibraryError(RuntimeError):
    pass


class Library:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        self.res_dir = self.root / "resources"
        self.res_dir.mkdir(parents=True, exist_ok=True)
        self.index: dict[str, dict] = {}
        self.diagnostics: list[str] = []
        self.rebuild()

    # ---------------------------------------------------------------- index
    def rebuild(self) -> None:
        """Relit les manifestes (dossier de la bibliothèque seulement)."""
        self.index, self.diagnostics = {}, []
        for d in sorted(p for p in self.res_dir.iterdir() if p.is_dir()):
            man = d / "manifest.json"
            conflicts = [p for p in d.glob("manifest*.json") if p.name != "manifest.json"]
            for c in conflicts:
                self.diagnostics.append(f"{d.name} : copie de conflit du synchroniseur « {c.name} » (à résoudre, non fusionnée)")
            if not man.exists():
                self.diagnostics.append(f"{d.name} : manifeste absent (arrivée incomplète ?)")
                continue
            try:
                m = json.loads(man.read_text("utf-8"))
                if int(m.get("version", 1)) > LIB_VERSION:
                    self.diagnostics.append(f"{d.name} : manifeste d'une version plus récente, ignoré")
                    continue
                if m.get("id") != d.name or not isinstance(m.get("revisions"), list):
                    raise ValueError("structure invalide")
            except (OSError, ValueError, TypeError) as e:
                self.diagnostics.append(f"{d.name} : manifeste illisible ({e}), ignoré")
                continue
            for c in conflicts:
                try:
                    other = json.loads(c.read_text("utf-8"))
                except (OSError, ValueError):
                    continue
                mine = {r["n"]: r.get("sha256") for r in m["revisions"]}
                for r in other.get("revisions", []):
                    if r["n"] in mine and mine[r["n"]] != r.get("sha256"):
                        self.diagnostics.append(f"{d.name} : révision r{r['n']} en CONFLIT (contenus différents)")
            self.index[m["id"]] = m

    def resources(self) -> list[dict]:
        return sorted(self.index.values(), key=lambda m: m.get("created", 0))

    def manifest(self, rid: str) -> dict:
        if rid not in self.index:
            raise LibraryError(f"ressource inconnue : {rid}")
        return self.index[rid]

    def _write(self, m: dict) -> None:
        d = self.res_dir / m["id"]
        d.mkdir(exist_ok=True)
        save_json_atomic(d / "manifest.json", m)
        bak = d / "manifest.json.bak"
        if bak.exists():
            bak.unlink()
        self.index[m["id"]] = m

    # ---------------------------------------------------------------- publication
    def publish(self, src, name: str = "", kind: str = "son", resource: str | None = None, recipe: dict | None = None,
                source: tuple | None = None, note: str = "") -> tuple[str, int]:
        """Publie `src` comme NOUVELLE révision (copie ; l'original reste où il est). Retourne (id, n)."""
        src = Path(src)
        if not src.is_file():
            raise LibraryError(f"fichier à publier introuvable : {src}")
        info = media.probe(src)
        if resource is None:
            resource = uuid.uuid4().hex[:12]
            m = {"version": LIB_VERSION, "id": resource, "name": name or src.stem, "kind": kind, "created": time.time(),
                 "tags": [], "projects": [], "revisions": []}
        else:
            m = copy.deepcopy(self.manifest(resource))
        n = max((r["n"] for r in m["revisions"]), default=0) + 1
        dest = self.res_dir / resource / f"r{n}{src.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise LibraryError(f"révision r{n} déjà présente sur disque (conflit) : {dest}")
        tmp = dest.with_name(dest.name + ".part")
        shutil.copy2(src, tmp)
        digest = _sha256(tmp)
        if digest != _sha256(src):
            tmp.unlink()
            raise LibraryError("copie altérée pendant la publication")
        os.replace(tmp, dest)
        m["revisions"].append({"n": n, "file": dest.name, "sha256": digest, "sample_rate": info.sample_rate,
                               "channels": info.channels, "frames": info.frames, "created": time.time(),
                               "recipe": recipe or {}, "source": list(source) if source else None,
                               "origin": str(src), "note": note})
        self._write(m)
        return resource, n

    def latest(self, rid: str, ready_only: bool = True) -> int:
        revs = [r["n"] for r in self.manifest(rid)["revisions"] if not ready_only or self.revision_path(rid, r["n"])]
        return max(revs, default=0)

    def revision(self, rid: str, n: int) -> dict:
        r = next((r for r in self.manifest(rid)["revisions"] if r["n"] == n), None)
        if r is None:
            raise LibraryError(f"{rid} : révision r{n} inconnue")
        return r

    def revision_path(self, rid: str, n: int, verify: bool = False) -> Path | None:
        """Fichier de la révision ; None tant qu'il n'est pas arrivé (synchronisation en cours)."""
        try:
            r = self.revision(rid, n)
        except LibraryError:
            return None
        p = self.res_dir / rid / r["file"]
        if not p.is_file():
            return None
        if verify and _sha256(p) != r["sha256"]:
            raise LibraryError(f"{rid} r{n} : contenu altéré (empreinte différente)")
        return p

    def lineage(self, rid: str) -> list[tuple]:
        """Filiation : [(id, n, recette)] en remontant les sources."""
        out = []
        seen = set()
        cur = (rid, self.latest(rid, ready_only=False))
        while cur and cur not in seen:
            seen.add(cur)
            r = self.revision(*cur)
            out.append((cur[0], cur[1], r.get("recipe") or {}))
            src = r.get("source")
            cur = tuple(src) if src else None
            if cur and cur[0] not in self.index:
                break
        return out

    def link_project(self, rid: str, project_id: str) -> None:
        m = copy.deepcopy(self.manifest(rid))
        if project_id not in m["projects"]:
            m["projects"].append(project_id)
            self._write(m)


# ---------------------------------------------------------------- projets ↔ bibliothèque
def insert(project: Project, lib: Library, rid: str, track_id: str, start: int, n: int | None = None) -> Clip:
    """Insère une révision (la plus récente prête par défaut) dans une piste ; épinglée."""
    n = n or lib.latest(rid)
    path = lib.revision_path(rid, n)
    if path is None:
        raise LibraryError(f"{rid} r{n} : fichier pas encore disponible")
    r = lib.revision(rid, n)
    length = int(round(r["frames"] * project.sample_rate / max(1, r["sample_rate"])))
    c = Clip(path=str(path), resource=rid, revision=n, name=lib.manifest(rid)["name"], start=int(start), length=length)
    with project.edit("Insérer depuis la bibliothèque", track_id):
        project.track(track_id).clips.append(c)
        project.track(track_id).clips.sort(key=lambda x: x.start)
    lib.link_project(rid, project.id)
    return c


def pending_updates(project: Project, lib: Library) -> list[dict]:
    """Propositions : clips épinglés sur une révision plus ancienne que la dernière PRÊTE, sauf refus
    explicite de cette révision."""
    refused = project.extensions.get("library_refused", {})
    out = []
    for t in project.tracks:
        for c in t.clips:
            if not c.resource or c.resource not in lib.index:
                continue
            new = lib.latest(c.resource)
            if new > c.revision and refused.get(c.resource, 0) < new:
                out.append({"track": t.id, "clip": c.id, "resource": c.resource, "current": c.revision, "proposed": new})
    return out


def adopt(project: Project, lib: Library, track_id: str, clip_id: str, n: int | None = None) -> dict:
    """Adopte une révision (annulable : une étape d'historique). Si la durée change, la position, le
    décalage et les fondus sont conservés ; la longueur est seulement réduite à ce qui existe."""
    t = project.track(track_id)
    c = next(x for x in t.clips if x.id == clip_id)
    n = n or lib.latest(c.resource)
    path = lib.revision_path(c.resource, n)
    if path is None:
        raise LibraryError(f"{c.resource} r{n} : fichier pas encore disponible")
    r = lib.revision(c.resource, n)
    avail = int(round(r["frames"] * project.sample_rate / max(1, r["sample_rate"])))
    report = {"from": c.revision, "to": n, "adjusted": []}
    with project.edit(f"Adopter r{n}", track_id):
        c.path, c.revision = str(path), n
        if c.offset + c.length * c.rate > avail:
            new_len = max(1, int((avail - c.offset) / c.rate))
            report["adjusted"].append(f"longueur {c.length} -> {new_len} (révision plus courte)")
            c.length = new_len
        if c.fade_in + c.fade_out > c.length:
            c.fade_in = min(c.fade_in, c.length // 2)
            c.fade_out = min(c.fade_out, c.length - c.fade_in)
            report["adjusted"].append("fondus réduits à la nouvelle longueur")
        refused = project.extensions.get("library_refused", {})
        refused.pop(c.resource, None)
    return report


def refuse(project: Project, lib: Library, resource: str, n: int) -> None:
    """Refus EXPLICITE d'une révision : plus proposée (annulable)."""
    with project.edit(f"Refuser r{n}", structure=True):
        project.extensions.setdefault("library_refused", {})[resource] = int(n)


# ---------------------------------------------------------------- médias absents, collecte
def missing_media(project: Project) -> list[dict]:
    out = []
    for t in project.tracks:
        for c in list(t.clips) + [c for k in t.takes for c in k["clips"]]:
            if c.path and not os.path.exists(c.path):
                out.append({"track": t.id, "clip": c.id, "path": c.path})
    return out


def find_candidates(path: str, search_dirs) -> list[Path]:
    """Mêmes noms dans les dossiers indiqués par l'utilisateur (aucun balayage global)."""
    name = Path(path).name
    return [Path(d) / name for d in search_dirs if (Path(d) / name).is_file()]


def relink(project: Project, old_path: str, new_path: str, verify_hash: str | None = None) -> int:
    """Reliaison contrôlée de toutes les références à `old_path` (une étape annulable).
    `verify_hash` : refuse un fichier dont le contenu diffère."""
    if verify_hash and _sha256(Path(new_path)) != verify_hash:
        raise LibraryError("le fichier proposé n'a pas le contenu attendu")
    tids = [t.id for t in project.tracks if any(c.path == old_path for c in list(t.clips) + [c for k in t.takes for c in k["clips"]])]
    n = 0
    with project.edit("Relier un média", *tids):
        for t in project.tracks:
            for c in list(t.clips) + [c for k in t.takes for c in k["clips"]]:
                if c.path == old_path:
                    c.path = str(new_path)
                    n += 1
    return n


def collect(project: Project, dest_dir) -> Path:
    """Export portable SUR DEMANDE : copie du projet + médias référencés dans `dest_dir` (le projet
    d'origine n'est pas modifié). Les médias absents restent référencés et sont listés."""
    dest = Path(dest_dir)
    (dest / "media").mkdir(parents=True, exist_ok=True)
    data = project.to_dict()
    copied: dict[str, str] = {}
    missing = []
    for t in data["tracks"]:
        clips = list(t["clips"]) + [c for k in t["takes"] for c in k["clips"]]
        for c in clips:
            src = c.get("path")
            if not src:
                continue
            if src not in copied:
                if not os.path.exists(src):
                    missing.append(src)
                    continue
                h = hashlib.sha1(os.path.abspath(src).encode()).hexdigest()[:6]
                target = dest / "media" / f"{Path(src).stem}_{h}{Path(src).suffix}"
                shutil.copy2(src, target)
                copied[src] = str(target)
            c["path"] = copied[src]
    data["extensions"] = dict(data.get("extensions", {}), collected_missing=missing)
    ext = ".fmmusic" if project.kind == "music" else ".fmaudio"
    out = dest / f"{project.name or 'projet'}{ext}"
    save_json_atomic(out, data)
    return out
