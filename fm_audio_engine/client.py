"""Client du moteur audio natif (sans Qt).

Un seul processus moteur par application (`shared_engine()`), partagé par FM Audio,
FM Music et la préécoute du Board. Protocole IPC v1 : voir docs/agents/fm_audio.md.
Les blocs audio ne passent jamais par ici : seulement des commandes et la télémétrie.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PROTOCOL = 1
_HERE = Path(__file__).resolve().parent
ENGINE_EXE = _HERE / "bin" / "fmz_audio_engine.exe"


class EngineError(RuntimeError):
    """Erreur explicite du moteur (jamais un succès implicite)."""


def engine_path() -> Path:
    return ENGINE_EXE


def available() -> tuple[bool, str]:
    """(disponible, diagnostic). Ne compile rien : l'appli démarre sans moteur."""
    if os.name != "nt":
        return False, "moteur audio : Windows uniquement pour l'instant"
    if not ENGINE_EXE.exists():
        return False, "moteur audio non compilé : lancer `python fm_audio_engine/build.py`"
    return True, str(ENGINE_EXE)


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def render_offline(spec: dict, out: str | os.PathLike, *, start: int = 0, end: int = -1,
                   tail: float | str = "auto", fmt: str = "f32", dither: bool = False,
                   overwrite: bool = False, stems: str | None = None, block: int = 512,
                   timeout: float = 600.0) -> dict:
    """Rendu offline par le moteur (même graphe qu'en temps réel). Lève EngineError."""
    ok, why = available()
    if not ok:
        raise EngineError(why)
    fd, spec_path = tempfile.mkstemp(suffix=".json", prefix="fmz_spec_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f)
        args = [str(ENGINE_EXE), "--render", spec_path, str(out), "--start", str(int(start)),
                "--end", str(int(end)), "--tail", str(tail), "--format", fmt, "--block", str(int(block))]
        if dither:
            args.append("--dither")
        if overwrite:
            args.append("--overwrite")
        if stems:
            args += ["--stems", str(stems)]
        r = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=_no_window())
        text = r.stdout.decode("utf-8", "replace").strip().splitlines()
        try:
            res = json.loads(text[-1]) if text else {}
        except ValueError:
            res = {}
        if r.returncode != 0 or not res.get("ok"):
            raise EngineError(res.get("error") or r.stderr.decode("utf-8", "replace") or f"code {r.returncode}")
        return res
    finally:
        try:
            os.unlink(spec_path)
        except OSError:
            pass


class EngineClient:
    """Processus moteur en mode --serve. Thread de lecture : réponses et événements."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._next = 1
        self._waiting: dict[int, dict] = {}
        self._cv = threading.Condition()
        self.telemetry: dict = {}           # dernière télémétrie (lue sans attente par l'interface)
        self.jobs: dict[int, dict] = {}     # travaux longs : progression / résultat
        self.listeners: list = []           # callbacks(event) appelés dans le thread de lecture
        self.info: dict = {}
        self.dead_reason = ""

    # ---- cycle de vie
    def start(self, timeout: float = 5.0) -> dict:
        ok, why = available()
        if not ok:
            raise EngineError(why)
        self._proc = subprocess.Popen([str(ENGINE_EXE), "--serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, creationflags=_no_window(), bufsize=0)
        threading.Thread(target=self._reader, daemon=True, name="fmz-engine-reader").start()
        self.info = self.request("hello", timeout=timeout)
        if int(self.info.get("protocol", -1)) != PROTOCOL:
            self.close()
            raise EngineError(f"protocole moteur {self.info.get('protocol')} incompatible (attendu {PROTOCOL})")
        return self.info

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self, timeout: float = 5.0) -> None:
        """Ferme stdin : le moteur s'arrête proprement (prises finalisées)."""
        p = self._proc
        if p is None:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.close()
                except OSError:
                    pass
                try:
                    p.wait(timeout)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(2)
        finally:
            for s in (p.stdout, p.stdin):
                try:
                    s.close()
                except (OSError, AttributeError):
                    pass
            self._proc = None
            with self._cv:
                self._cv.notify_all()

    # ---- requêtes
    def request(self, cmd: str, timeout: float = 2.0, **kw) -> dict:
        if not self.alive():
            raise EngineError("moteur arrêté" + (f" : {self.dead_reason}" if self.dead_reason else ""))
        with self._lock:
            rid = self._next
            self._next += 1
            msg = dict(kw, id=rid, cmd=cmd)
            data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except OSError as e:
                raise EngineError(f"moteur injoignable : {e}")
        deadline = time.monotonic() + timeout
        with self._cv:
            while rid not in self._waiting:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise EngineError(f"délai dépassé pour « {cmd} » ({timeout:.1f} s)")
                if not self.alive():
                    raise EngineError("moteur arrêté pendant « %s »" % cmd)
                self._cv.wait(min(left, 0.1))
            res = self._waiting.pop(rid)
        if not res.get("ok"):
            raise EngineError(res.get("error") or f"échec de « {cmd} »")
        return res

    def render(self, spec: dict, out: str, **kw) -> int:
        """Lance un rendu (travail annulable). Retourne l'identifiant du travail."""
        job = int(self.request("render", spec=spec, out=str(out), **kw)["job"])
        self.jobs.setdefault(job, {"progress": 0.0})
        return job

    def wait_job(self, job: int, timeout: float = 600.0) -> dict:
        deadline = time.monotonic() + timeout
        with self._cv:
            while "done" not in self.jobs.get(job, {}):
                left = deadline - time.monotonic()
                if left <= 0:
                    raise EngineError(f"rendu {job} : délai dépassé")
                self._cv.wait(min(left, 0.2))
        ev = self.jobs[job]["done"]
        if not ev.get("ok"):
            raise EngineError(ev.get("error") or "rendu échoué")
        return ev.get("result", {})

    # ---- lecture
    def _reader(self) -> None:
        p = self._proc
        try:
            for raw in p.stdout:
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                ev = msg.get("event")
                if ev == "telemetry":
                    self.telemetry = msg
                elif ev in ("progress", "done"):
                    j = self.jobs.setdefault(int(msg.get("job", -1)), {})
                    if ev == "progress":
                        j["progress"] = float(msg.get("progress", 0))
                    else:
                        j["done"] = msg
                        with self._cv:
                            self._cv.notify_all()
                elif "id" in msg:
                    with self._cv:
                        self._waiting[int(msg["id"])] = msg
                        self._cv.notify_all()
                for cb in list(self.listeners):
                    try:
                        cb(msg)
                    except Exception:
                        pass
        finally:
            code = p.poll()
            if code not in (None, 0):
                self.dead_reason = f"processus terminé (code {code})"
            with self._cv:
                self._cv.notify_all()


_shared: EngineClient | None = None
_shared_lock = threading.Lock()


def shared_engine(start: bool = True) -> EngineClient | None:
    """Le moteur unique de l'application (créé à la première demande)."""
    global _shared
    with _shared_lock:
        if _shared is not None and _shared.alive():
            return _shared
        if not start:
            return None
        c = EngineClient()
        c.start()
        _shared = c
        return c


def shutdown_shared() -> None:
    global _shared
    with _shared_lock:
        if _shared is not None:
            _shared.close()
            _shared = None
