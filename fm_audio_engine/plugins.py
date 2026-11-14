"""Plugins (sans Qt) : INVENTAIRE et SCAN ISOLÉ des modules VST3.

- `scan(dirs)` : inventaire SANS charger les modules (métadonnées `Contents/Resources/moduleinfo.json`
  quand le fabricant les fournit), dans les dossiers standard et ceux que l'utilisateur ajoute, jamais un
  balayage du disque entier ; délai borné.
- `scan_module(path)` : SCAN ISOLÉ d'un module par le moteur dans un processus à part
  (`fmz_audio_engine.exe --scan-vst3`), avec délai : chaque classe est instanciée pour lire bus,
  paramètres et latence. Plantage ou blocage = module mis en QUARANTAINE (jamais rechargé tant que le
  fichier ne change pas) ; l'appli et le moteur de lecture continuent. Résultats en CACHE (empreinte :
  chemin, taille, date du module, version du moteur).
- `library(dirs)` : classes utilisables (effets / instruments) de tous les modules trouvés.
- Politique « plugin absent » : un effet `vst3:<UID>` introuvable est SIGNALÉ par le moteur et laissé de
  côté (son inchangé) ; un instrument absent laisse sa piste muette ; jamais un autre son à la place.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

SCAN_TIMEOUT_S = 20.0


def standard_dirs() -> list[Path]:
    out = []
    common = os.environ.get("CommonProgramFiles") or r"C:\Program Files\Common Files"
    out.append(Path(common) / "VST3")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(Path(local) / "Programs" / "Common" / "VST3")
    return out


def _read_moduleinfo(bundle: Path) -> dict:
    mi = bundle / "Contents" / "Resources" / "moduleinfo.json"
    if not mi.is_file():
        return {}
    try:
        # moduleinfo.json tolère des virgules finales (JSON5 léger) : retrait prudent
        text = mi.read_text("utf-8", errors="replace").replace(",\n}", "\n}").replace(",\n]", "\n]")
        return json.loads(text)
    except (OSError, ValueError):
        return {"_error": "moduleinfo.json illisible"}


def scan(dirs=None, deadline_s: float = 5.0, max_depth: int = 3) -> dict:
    """{"plugins": [...], "errors": [...], "dirs": [...]} ; s'arrête proprement au-delà du délai."""
    dirs = [Path(d) for d in (dirs if dirs is not None else standard_dirs())]
    t0 = time.monotonic()
    plugins, errors = [], []
    for root in dirs:
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            if time.monotonic() - t0 > deadline_s:
                errors.append(f"inventaire interrompu après {deadline_s:g} s (dossiers restants non lus)")
                return {"plugins": plugins, "errors": errors, "dirs": [str(d) for d in dirs]}
            d, depth = stack.pop()
            try:
                entries = list(d.iterdir())
            except OSError as e:
                errors.append(f"{d} : {e}")
                continue
            for p in entries:
                if p.suffix.lower() == ".vst3":
                    info = _read_moduleinfo(p) if p.is_dir() else {}
                    classes = [{"id": c.get("CID", ""), "name": c.get("Name", ""), "category": c.get("Category", ""),
                                "sub": c.get("Sub Categories", [])} for c in info.get("Classes", [])]
                    plugins.append({"path": str(p), "name": info.get("Name") or p.stem,
                                    "vendor": (info.get("Factory Info") or {}).get("Vendor", ""),
                                    "version": info.get("Version", ""), "classes": classes,
                                    "metadata": bool(info) and "_error" not in info,
                                    "error": info.get("_error", "")})
                elif p.is_dir() and depth < max_depth:
                    stack.append((p, depth + 1))
    return {"plugins": sorted(plugins, key=lambda x: x["name"].lower()), "errors": errors, "dirs": [str(d) for d in dirs]}


# ---------------------------------------------------------------- scan isolé, cache, quarantaine
def _store_path() -> Path:
    from .media import cache_dir
    return cache_dir() / "plugins_vst3.json"


def _load_store() -> dict:
    try:
        return json.loads(_store_path().read_text("utf-8"))
    except (OSError, ValueError):
        return {"modules": {}}


def _save_store(store: dict) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".part")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, p)


def _fingerprint(path: Path) -> str:
    from . import client
    target = path / "Contents" / "x86_64-win" / (path.stem + ".vst3") if path.is_dir() else path
    try:
        st = target.stat()
        eng = client.engine_path().stat().st_mtime_ns
    except OSError:
        return ""
    return f"{st.st_size}:{st.st_mtime_ns}:{eng}"


def scan_module(path, timeout: float = SCAN_TIMEOUT_S, refresh: bool = False) -> dict:
    """Scan isolé d'un module (cache ; quarantaine si plantage / blocage). Renvoie
    {"path", "classes": [...], "status": "ok"|"quarantine"|"error", "error": str, "cached": bool}."""
    from . import client
    path = Path(path)
    key = str(path.resolve()) if path.exists() else str(path)
    fp = _fingerprint(path)
    store = _load_store()
    entry = store["modules"].get(key)
    if entry and entry.get("fingerprint") == fp and fp and not refresh:
        return dict(entry, cached=True)
    if not fp:
        return {"path": key, "classes": [], "status": "error", "error": "module introuvable", "cached": False}
    ok, why = client.available()
    if not ok:
        return {"path": key, "classes": [], "status": "error", "error": why, "cached": False}
    try:
        r = subprocess.run([str(client.engine_path()), "--scan-vst3", key], capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = r.stdout.decode("utf-8", "replace").strip().splitlines()
        if r.returncode != 0 or not out:
            entry = {"path": key, "classes": [], "status": "quarantine",
                     "error": f"le scan a planté (code {r.returncode & 0xFFFFFFFF:#x}) : module mis en quarantaine"}
        else:
            data = json.loads(out[-1])
            entry = {"path": key, "classes": data.get("classes", []), "vendor": data.get("vendor", ""),
                     "status": "error" if data.get("error") else "ok", "error": data.get("error", "")}
    except subprocess.TimeoutExpired:
        entry = {"path": key, "classes": [], "status": "quarantine",
                 "error": f"le scan ne répond plus après {timeout:g} s : module mis en quarantaine"}
    except (OSError, ValueError) as e:
        entry = {"path": key, "classes": [], "status": "error", "error": str(e)}
    entry["fingerprint"] = fp
    entry["scanned_at"] = time.time()
    store["modules"][key] = entry
    _save_store(store)
    return dict(entry, cached=False)


def quarantined() -> list[dict]:
    return [m for m in _load_store()["modules"].values() if m.get("status") == "quarantine"]


def release_quarantine(path) -> None:
    """« Réessayer » : oublie le verdict ; le prochain scan relance le module (toujours isolé)."""
    store = _load_store()
    store["modules"].pop(str(Path(path).resolve()), None)
    _save_store(store)


def library(dirs=None, timeout: float = SCAN_TIMEOUT_S, scan_new: bool = True) -> dict:
    """{"effects": [...], "instruments": [...], "problems": [...], "unscanned": n} : classes utilisables de tous
    les modules. Chaque classe : {"type": "vst3:<UID>", "uid", "name", "vendor", "path", "latency", "params"}.
    scan_new=False : cache seulement (aucun processus lancé : menus), `unscanned` = modules jamais scannés."""
    inv = scan(dirs, deadline_s=5.0 if scan_new else 0.5)
    effects, instruments, problems = [], [], list(inv["errors"])
    store = _load_store()["modules"] if not scan_new else {}
    unscanned = 0
    for mod in inv["plugins"]:
        if scan_new:
            res = scan_module(mod["path"], timeout=timeout)
        else:
            path = Path(mod["path"])
            res = store.get(str(path.resolve()))
            if not res or res.get("fingerprint") != _fingerprint(path):
                unscanned += 1
                continue
        if res["status"] != "ok":
            problems.append(f"{Path(mod['path']).name} : {res['error']}")
            continue
        for c in res["classes"]:
            if c.get("error"):
                problems.append(f"{c.get('name')} : {c['error']}")
                continue
            item = {"type": effect_ref(c["uid"]), "uid": c["uid"], "name": c.get("name", ""), "vendor": c.get("vendor", ""),
                    "path": res["path"], "latency": c.get("latency", 0), "params": c.get("params", 0)}
            (instruments if c.get("instrument") else effects).append(item)
    key = lambda x: (x["vendor"].lower(), x["name"].lower())
    return {"effects": sorted(effects, key=key), "instruments": sorted(instruments, key=key), "problems": problems,
            "unscanned": unscanned}


def dirs_from_settings(settings: dict | None) -> list[Path]:
    """Dossiers standard + dossiers ajoutés par l'utilisateur (réglage « audio_plugin_dirs », séparés par ;)."""
    extra = [Path(p.strip()) for p in str((settings or {}).get("audio_plugin_dirs", "") or "").split(";") if p.strip()]
    return standard_dirs() + extra


def effect_ref(plugin_class_id: str) -> str:
    """Type d'effet (ou d'instrument) du projet qui référence une classe de plugin."""
    return f"vst3:{plugin_class_id}"


def fx_for(item: dict):
    """Effet du projet pour une classe de `library()`."""
    from .project import Fx
    return Fx(type=item["type"], params={"path": item["path"]}, name=item["name"])


def instrument_for(item: dict) -> dict:
    return {"type": item["type"], "path": item["path"], "name": item["name"]}


def missing_plugins(project) -> list[dict]:
    """Plugins référencés par le projet dont le module est introuvable (effets et instruments)."""
    out = []
    for t in list(project.tracks) + list(project.buses) + [project.master]:
        for i, f in enumerate(t.fx):
            if f.type.startswith("vst3:"):
                path = f.params.get("path", "")
                if not path or not Path(path).exists():
                    out.append({"node": t.id, "index": i, "type": f.type, "name": f.name or f.type, "path": path})
        inst = getattr(t, "instrument", None) or {}
        if str(inst.get("type", "")).startswith("vst3:"):
            path = inst.get("path", "")
            if not path or not Path(path).exists():
                out.append({"node": t.id, "index": -1, "type": inst["type"], "name": inst.get("name") or inst["type"], "path": path})
    return out
