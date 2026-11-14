"""Plugins VST3 dans les éditeurs FM Audio / FM Music (Qt, partagé).

- `add_library_menu(menu, kind, settings)` : sous-menu « Plugins VST3 » tiré du CACHE de scan (aucun
  processus lancé pendant l'ouverture du menu : fluidité) + « Rechercher les plugins… » (scan isolé EN
  FOND, `Rescan`) + modules en quarantaine (« Réessayer »).
- `add_slot_actions(menu, session)` : « Éditeur : <plugin> » pour chaque plugin du projet.
- `open_editor(pane, nid, slot)` : fenêtre de l'éditeur, portée par le MOTEUR (processus à part : un
  éditeur qui plante n'emporte pas PIPE FMZ).
"""
from __future__ import annotations

import ctypes
import threading

from PySide6.QtCore import QObject, Signal

from fm_audio_engine import client, plugins


def add_library_menu(m, kind: str, settings: dict | None) -> dict:
    """kind = "effects" | "instruments". Renvoie {action: (quoi, valeur)} : ("plugin", item), ("rescan", None),
    ("retry", chemin)."""
    acts = {}
    sub = m.addMenu("Plugins VST3")
    lib = plugins.library(plugins.dirs_from_settings(settings), scan_new=False)
    items = lib[kind]
    for it in items:
        label = it["name"] + (f"  ({it['vendor']})" if it.get("vendor") else "")
        acts[sub.addAction(label)] = ("plugin", it)
    if not items:
        a = sub.addAction("Aucun plugin connu" + (" : lancer la recherche" if lib["unscanned"] else ""))
        a.setEnabled(False)
    sub.addSeparator()
    n = lib["unscanned"]
    acts[sub.addAction("Rechercher les plugins…" + (f" ({n} module(s) à lire)" if n else ""))] = ("rescan", None)
    q = plugins.quarantined()
    if q:
        qm = sub.addMenu(f"En quarantaine ({len(q)})")
        for mod in q:
            acts[qm.addAction("Réessayer : " + mod["path"].rsplit("\\", 1)[-1])] = ("retry", mod["path"])
    return acts


class Rescan(QObject):
    """Scan isolé de tous les modules EN FOND ; `finished` porte le résumé (fil principal via signal)."""
    finished = Signal(dict)
    _running = False

    def start(self, settings: dict | None) -> bool:
        if Rescan._running:
            return False
        Rescan._running = True
        dirs = plugins.dirs_from_settings(settings)
        try:
            timeout = max(5.0, float((settings or {}).get("audio_plugin_scan_timeout", plugins.SCAN_TIMEOUT_S)))
        except (TypeError, ValueError):
            timeout = plugins.SCAN_TIMEOUT_S

        def work():
            try:
                res = plugins.library(dirs, timeout=timeout)
            except Exception as e:                       # noqa: BLE001 : le résumé dit ce qui a échoué
                res = {"effects": [], "instruments": [], "problems": [str(e)], "unscanned": 0}
            Rescan._running = False
            try:
                self.finished.emit(res)
            except RuntimeError:                         # éditeur fermé entre-temps
                pass
        threading.Thread(target=work, daemon=True, name="fmz-vst3-scan").start()
        return True


def summary(res: dict) -> str:
    s = f"Plugins : {len(res['effects'])} effet(s), {len(res['instruments'])} instrument(s)"
    if res["problems"]:
        s += f" ; {len(res['problems'])} problème(s) : " + " ; ".join(res["problems"][:3])
    return s


def handle_library_choice(pane, what) -> dict | None:
    """Actions communes : recherche en fond, réessai d'un module ; renvoie l'item choisi pour ("plugin", item)."""
    kind, value = what
    if kind == "plugin":
        return value
    if kind == "retry":
        plugins.release_quarantine(value)
        kind = "rescan"
    if kind == "rescan":
        job = Rescan(pane)
        job.finished.connect(lambda res: pane.set_status(summary(res)))
        if job.start(pane._settings()):
            pane.set_status("Recherche des plugins VST3 (scan isolé, en fond)…")
        else:
            pane.set_status("Recherche des plugins déjà en cours")
    return None


def add_slot_actions(m, session) -> dict:
    acts = {}
    slots = session.plugin_slots()
    if slots:
        m.addSeparator()
    for obj, nid, slot in slots:
        name = (obj.name if slot != "inst" else (obj.instrument or {}).get("name")) or "plugin"
        acts[m.addAction(f"Éditeur : {name}")] = ("editor", (nid, slot))
    return acts


def open_editor(pane, nid: str, slot: str) -> None:
    s = pane.session
    if not s.ensure_engine():
        return
    eng = s.engine
    pid = getattr(getattr(eng, "_proc", None), "pid", None)
    if pid:
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(int(pid))   # la fenêtre du moteur passe devant
        except (AttributeError, OSError):
            pass
    for attempt in range(2):
        try:
            r = eng.request("vst3_editor", node=nid, slot=slot, open=True, timeout=15.0)
            pane.set_status(f"Éditeur ouvert : {r.get('name', '')}")
            return
        except client.EngineError as e:
            if attempt == 0 and "aucun plugin chargé" in str(e):
                s._push_spec()                           # graphe pas encore envoyé : on l'envoie, puis on réessaie
                continue
            pane.set_status(f"Éditeur : {e}")
            return
