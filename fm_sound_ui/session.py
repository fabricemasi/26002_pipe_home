"""Session audio Qt : projet + moteur partagé + transport + travaux de fond (décodage, pics).

Règles de fluidité : rien de bloquant dans le fil de l'interface. Le moteur est chargé en
différé (premier besoin) ; décodage et pics tournent dans des fils de travail ; la position et
les vu-mètres viennent de la dernière télémétrie (lecture d'un dict, jamais une requête).
"""
from __future__ import annotations

import os
import queue
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from fm_audio_engine import client, media, peaks
from fm_audio_engine.project import Clip, Project, compile_spec

TELEMETRY_MS = 33


def takes_dir() -> Path:
    """Prises écrites en local, hors synchronisation, puis publiées à côté du projet."""
    base = os.environ.get("FMZ_AUDIO_TAKES") or os.path.join(os.environ.get("LOCALAPPDATA") or str(Path.home()),
                                                            "PIPE_FMZ", "audio_takes")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def device_pair(settings: dict) -> tuple:
    """(sortie, entrée) à ouvrir : un pilote ASIO est duplex, ses entrées sont celles du MÊME pilote ; une entrée
    WASAPI avec une sortie ASIO (horloges différentes) est ignorée."""
    output = settings.get("audio_output_device") or "default"
    inp = settings.get("audio_input_device") or ""
    if output.startswith("asio:"):
        return output, (output if inp else "")
    if inp.startswith("asio:"):
        return inp, inp
    return output, inp

class AudioSession(QObject):
    changed = Signal()                 # le projet a changé (édition, undo…)
    status = Signal(str)               # message pour l'utilisateur
    tick = Signal(dict)                # télémétrie (position, vu-mètres) à ~30 Hz
    mediaReady = Signal(str)           # pics / PCM d'un média prêts
    jobProgress = Signal(int, float)
    jobDone = Signal(int, dict)

    def __init__(self, project: Project | None = None, settings=None, parent=None):
        super().__init__(parent)
        self.project = project or Project()
        self.settings = settings or (lambda: {})
        self.engine: client.EngineClient | None = None
        self.engine_error = ""
        self.playing = False
        self.recording = False
        self.position = 0
        self.cursor = 0
        self.peaks: dict[str, peaks.Peaks] = {}
        self.pcm: dict[str, str] = {}
        self.media_errors: dict[str, str] = {}
        self._queued: set[str] = set()
        self._jobs = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stopping = False
        self._reload = QTimer(self)
        self._reload.setSingleShot(True)
        self._reload.setInterval(30)
        self._reload.timeout.connect(self._push_spec)
        self._poll = QTimer(self)
        self._poll.setInterval(TELEMETRY_MS)
        self._poll.timeout.connect(self._read_telemetry)
        self._render_jobs: dict[int, dict] = {}
        self.project.history.listeners.append(self._on_history)
        self.warnings: list[str] = []
        self.request_media()

    @property
    def device(self) -> dict | None:
        """Périphérique ouvert sur le moteur PARTAGÉ (un seul pour tous les éditeurs et le Board)."""
        return getattr(self.engine, "device_info", None) if self.engine is not None else None

    # ---------------------------------------------------------------- projet
    def set_project(self, project: Project) -> None:
        self.stop()
        try:
            self.project.history.listeners.remove(self._on_history)
        except ValueError:
            pass
        self.project = project
        project.history.listeners.append(self._on_history)
        self.request_media()
        self.schedule_reload()
        self.changed.emit()

    def _on_history(self) -> None:
        self.request_media()
        self.schedule_reload()
        self.changed.emit()

    # ---------------------------------------------------------------- médias (fond)
    def media_paths(self) -> list[str]:
        out = []
        for t in self.project.tracks:
            for c in list(t.clips) + [c for k in t.takes for c in k["clips"]]:
                if c.path and c.path not in out:
                    out.append(c.path)
        return out

    def request_media(self) -> None:
        for p in self.media_paths():
            if p in self.peaks or p in self._queued or p in self.media_errors:
                continue
            self._queued.add(p)
            self._jobs.put(p)
        if not self._jobs.empty() and (self._worker is None or not self._worker.is_alive()):
            self._worker = threading.Thread(target=self._work, daemon=True, name="fmz-audio-media")
            self._worker.start()

    def _work(self) -> None:
        while not self._stopping:
            try:
                path = self._jobs.get(timeout=0.5)
            except queue.Empty:
                return
            try:
                pcm = media.ensure_pcm(path, cancel=lambda: self._stopping)
                pk = peaks.compute(pcm, cancel=lambda: self._stopping)
                self.pcm[path] = pcm
                self.peaks[path] = pk
            except Exception as e:  # média absent ou illisible : signalé, jamais remplacé
                self.media_errors[path] = str(e)
            finally:
                self._queued.discard(path)
            try:
                self.mediaReady.emit(path)
            except RuntimeError:              # session détruite pendant le calcul : résultat ignoré
                return

    def resolve(self, clip: Clip) -> str | None:
        return self.pcm.get(clip.path) or media.cached_pcm(clip.path) or clip.path

    # ---------------------------------------------------------------- moteur
    def ensure_engine(self) -> bool:
        if self.engine is not None and self.engine.alive():
            return True
        ok, why = client.available()
        if not ok:
            self.engine_error = why
            self.status.emit(why)
            return False
        try:
            self.engine = client.shared_engine()
        except client.EngineError as e:
            self.engine_error = str(e)
            self.status.emit(f"Moteur audio indisponible : {e}")
            return False
        self.engine.listeners.append(self._engine_event)
        self.schedule_reload(0)
        return True

    def ensure_device(self) -> bool:
        if not self.ensure_engine():
            return False
        dev = self.device
        if dev is not None and (dev.get("sample_rate") == self.project.sample_rate or self.recording
                                or self.engine.telemetry.get("recording") or dev.get("backend") == "asio"):
            return True                         # ASIO : le pilote garde sa fréquence (pas de réouverture en boucle)
        s = self.settings() or {}
        output, inp = device_pair(s)
        try:
            if dev is not None:                 # autre fréquence : réouverture (WASAPI partagé convertit)
                self.engine.request("close_device", timeout=5.0)
                self.engine.device_info = None
            self.engine.device_info = self.engine.request(
                "open_device", timeout=20.0, output=output, sample_rate=self.project.sample_rate,
                input=inp, buffer=int(s.get("audio_buffer", 0) or 0),
                exclusive=bool(s.get("audio_exclusive", False)))
        except client.EngineError as e:
            self.status.emit(f"Périphérique audio : {e}")
            return False
        self._poll.start()
        if self.device.get("sample_rate") != self.project.sample_rate:
            self.status.emit(f"Périphérique à {self.device.get('sample_rate')} Hz, projet à {self.project.sample_rate} Hz")
        if output.startswith("asio:"):
            self.engine.device_info["backend"] = "asio"
            if (s.get("audio_input_device") or "") not in ("", output):
                self.status.emit("ASIO : entrées du même pilote seulement (pas d'agrégation de cartes non synchronisées)")
        return True

    def schedule_reload(self, ms: int | None = None) -> None:
        if ms is not None:
            self._reload.setInterval(ms)
        self._reload.start()

    def spec(self) -> dict:
        return compile_spec(self.project, self.resolve)

    def _push_spec(self) -> None:
        self._reload.setInterval(30)
        if self.engine is None or not self.engine.alive():
            return
        try:
            res = self.engine.request("load", spec=self.spec())
            self.warnings = res.get("warnings", [])
        except client.EngineError as e:
            self.status.emit(f"Graphe refusé : {e}")

    def _engine_event(self, msg: dict) -> None:   # fil de lecture du moteur
        ev = msg.get("event")
        if ev == "progress":
            self.jobProgress.emit(int(msg["job"]), float(msg.get("progress", 0)))
        elif ev == "done":
            self.jobDone.emit(int(msg["job"]), msg)

    def _read_telemetry(self) -> None:
        if self.engine is None:
            return
        t = self.engine.telemetry
        if not t:
            return
        self.position = int(t.get("pos", self.position))
        self.playing = bool(t.get("playing", False))
        self.tick.emit(t)

    # ---------------------------------------------------------------- transport
    def play(self, from_pos: int | None = None) -> bool:
        if not self.ensure_device():
            return False
        self._push_spec()
        pos = self.cursor if from_pos is None else from_pos
        loop = self.project.loop
        self.engine.request("loop", on=bool(loop.get("on")), start=int(loop.get("start", 0)), end=int(loop.get("end", 0)))
        self.engine.request("play", **{"from": int(pos)})
        self.playing = True
        return True

    def stop(self) -> None:
        if self.recording:
            self.stop_recording()
        if self.engine is not None and self.engine.alive():
            try:
                self.engine.request("stop")
            except client.EngineError:
                pass
        self.playing = False

    def toggle_play(self) -> None:
        self.stop() if self.playing else self.play()

    def seek(self, pos: int) -> None:
        self.cursor = max(0, int(pos))
        if self.playing and self.engine is not None:
            try:
                self.engine.request("seek", pos=self.cursor)
            except client.EngineError:
                pass

    def plugin_slots(self) -> list:
        """[(objet du projet, nœud, emplacement)] des plugins VST3 du projet : (Fx, id, "fx<N>") ou (piste, id, "inst")."""
        out = []
        for n in list(self.project.tracks) + list(self.project.buses) + [self.project.master]:
            nid = "master" if n is self.project.master else n.id
            for i, f in enumerate(n.fx):
                if f.type.startswith("vst3:"):
                    out.append((f, nid, f"fx{i}"))
            inst = getattr(n, "instrument", None) or {}
            if str(inst.get("type", "")).startswith("vst3:"):
                out.append((n, nid, "inst"))
        return out

    def capture_plugin_states(self) -> int:
        """Avant l'enregistrement : l'état COURANT de chaque plugin (réglé dans son éditeur ou par automation)
        est recopié dans le projet (paramètre \"state\", base64). Hors étape d'annulation : l'état d'un plugin
        n'est pas une édition du document. Renvoie le nombre d'états mis à jour."""
        if self.engine is None or not self.engine.alive():
            return 0
        n = 0
        for obj, nid, slot in self.plugin_slots():
            try:
                st = self.engine.request("vst3_state", node=nid, slot=slot, timeout=5.0).get("state", "")
            except client.EngineError:
                continue
            if not st:
                continue
            target = obj.params if slot != "inst" else obj.instrument
            if target.get("state") != st:
                target["state"] = st
                n += 1
        return n

    def plugin_params(self, nid: str, slot: str) -> list:
        if self.engine is None or not self.engine.alive():
            return []
        try:
            return self.engine.request("vst3_params", node=nid, slot=slot, timeout=5.0).get("params", [])
        except client.EngineError:
            return []

    def set_node(self, node_id: str, key: str, value: float) -> None:
        """Changement continu (fader, pan) : envoyé au moteur sans reconstruire le graphe."""
        if self.engine is None or not self.engine.alive():
            return
        spec_ids = [t.id for t in self.project.tracks] + [b.id for b in self.project.buses] + ["master"]
        if node_id in spec_ids:
            try:
                self.engine.request("node", node=spec_ids.index(node_id), key=key, value=float(value))
            except client.EngineError:
                pass

    def metronome(self, on: bool, level: float = 0.5) -> None:
        if self.ensure_engine():
            self.engine.request("metronome", on=bool(on), level=float(level))

    # ---------------------------------------------------------------- enregistrement
    def start_recording(self, precount_bars: int = 0) -> bool:
        armed = [t for t in self.project.tracks if t.armed]
        if not armed:
            self.status.emit("Aucune piste armée")
            return False
        if not self.ensure_device():
            return False
        if not self.device.get("in_channels"):
            self.status.emit("Aucune entrée ouverte : choisir un périphérique d'entrée dans les réglages audio")
            return False
        self._push_spec()
        tracks = [{"id": t.id, "inputs": [max(0, t.input) + k for k in range(max(1, min(2, t.input_channels)))]} for t in armed]
        loop = self.project.loop
        try:
            self.engine.request("record_start", dir=str(takes_dir()), name=self.project.name or "prise", tracks=tracks)
            self.engine.request("loop", on=bool(loop.get("on")), start=int(loop.get("start", 0)), end=int(loop.get("end", 0)))
            start = self.cursor
            kw = {"from": int(start)}
            if precount_bars > 0:
                tm = self.project.tempo_map()
                tick = tm.sample_to_tick(start)
                kw["from"] = int(start - (tm.tick_to_sample(int(tick)) - tm.tick_to_sample(int(tick) - precount_bars * tm.bar_ticks(int(tick)))))
                kw["precount_until"] = int(start)
            self.engine.request("play", **kw)
        except client.EngineError as e:
            self.status.emit(f"Enregistrement impossible : {e}")
            return False
        self.recording = True
        self.playing = True
        return True

    def stop_recording(self) -> list:
        if not self.recording or self.engine is None:
            return []
        self.recording = False
        try:
            self.engine.request("stop")
            res = self.engine.request("record_stop", timeout=30.0)
        except client.EngineError as e:
            self.status.emit(f"Arrêt de la prise : {e}")
            return []
        if res.get("error"):
            self.status.emit(f"Prise : {res['error']}")
        if res.get("overflow"):
            self.status.emit(f"Prise : {res['overflow']} échantillons perdus (débordement du tampon)")
        return self.adopt_takes(res.get("takes", []), int(res.get("declared_latency_samples", 0)))

    def adopt_takes(self, takes: list, latency: int = 0) -> list:
        """Les prises deviennent des sources indépendantes : une prise par passe, rangée dans
        les `takes` de la piste ; la plus récente est jouée. Publication à côté du projet."""
        made = []
        dest = self.media_folder()
        by_track: dict[str, list] = {}
        for k in takes:
            by_track.setdefault(k["track"], []).append(k)
        with self.project.edit("Prise", *by_track.keys()):
            for tid, ks in by_track.items():
                t = self.project.track(tid)
                if t is None:
                    continue
                for k in ks:
                    path = Path(k["path"])
                    if dest is not None and path.exists():
                        target = dest / path.name
                        n = 1
                        while target.exists():
                            target = dest / f"{path.stem}_{n}{path.suffix}"
                            n += 1
                        shutil.copy2(path, target)       # publication APRÈS finalisation ; l'original local reste
                        path = target
                    start = max(0, int(k["start"]) - latency)
                    c = Clip(path=str(path), name=path.stem, start=start, length=int(k["frames"]), take=f"pass{k.get('pass', 0)}")
                    t.takes.append({"id": c.take + "_" + c.id, "name": f"Prise {len(t.takes) + 1}", "clips": [c]})
                    made.append(c)
                if ks:
                    last = t.takes[-1]["clips"][0]
                    t.clips = [x for x in t.clips if not (x.start < last.end and x.end > last.start)] + [Clip.from_dict(last.to_dict())]
                    t.clips.sort(key=lambda x: x.start)
        return made

    def media_folder(self) -> Path | None:
        if not self.project.path:
            return None
        p = Path(self.project.path)
        d = p.with_name(p.stem + "_media")
        d.mkdir(exist_ok=True)
        return d

    # ---------------------------------------------------------------- export
    def export(self, out: str, stems_dir: str | None = None, fmt: str = "pcm24", end: int = -1) -> int | None:
        if not self.ensure_engine():
            return None
        kw = {"format": fmt, "end": int(end if end >= 0 else self.project.length_samples())}
        if stems_dir:
            kw["stems"] = str(stems_dir)
        try:
            return self.engine.render(self.spec(), out, **kw)
        except client.EngineError as e:
            self.status.emit(f"Export : {e}")
            return None

    def cancel_job(self, job: int) -> None:
        if self.engine is not None:
            try:
                self.engine.request("cancel", job=job)
            except client.EngineError:
                pass

    def shutdown(self) -> None:
        """Le pane se ferme : transport arrêté. Le moteur partagé reste (Board, autre éditeur)."""
        self._poll.stop()
        self._reload.stop()
        self._stopping = True                 # travaux de fond arrêtés proprement (aucun fichier partiel)
        if self._worker is not None:
            self._worker.join(5.0)
        if not self.recording:
            self.stop()
        if self.engine is not None:
            try:
                self.engine.listeners.remove(self._engine_event)
            except ValueError:
                pass
