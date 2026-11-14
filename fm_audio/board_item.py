"""Carte audio du Board (`audio_doc`) : nom, rôle, durée, miniature waveform (pyramide de pics
calculée EN FOND, jamais pendant la peinture), métadonnées, révision, état (fichier introuvable),
préécoute par le moteur PARTAGÉ (bouton lecture de la carte), double-clic = bonne cible
d'ouverture (FM Audio ou FM Music). Le Board organise et référence : il n'édite pas le son.

Ouverture dans un module : `HOOKS["open"](clé, chemin)` posé par la fenêtre ; à défaut,
la méthode `open_in_module` de la fenêtre hôte (même contrat que les menus « Ouvrir dans … »).
"""
from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QPen

from fm_miro.items import ITEM_CLASSES, BoardItem

from . import board_model as bm

HOOKS: dict = {}
PLAY_W = 26


class _Relay(QObject):
    ready = Signal(str)


_relay = None
_jobs: queue.Queue = queue.Queue()
_peaks: dict = {}          # chemin -> Peaks | None (None = échec, signalé sur la carte)
_errors: dict = {}
_queued: set = set()
_worker = None


def _get_relay() -> _Relay:
    global _relay
    if _relay is None:
        _relay = _Relay()
    return _relay


def request_peaks(path: str) -> None:
    """Miniature : pyramide calculée par un fil de travail unique (décodage compris)."""
    global _worker
    if path in _peaks or path in _queued:
        return
    _queued.add(path)
    _jobs.put(path)
    _get_relay()
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, daemon=True, name="fmz-board-audio")
        _worker.start()


def _work() -> None:
    from fm_audio_engine import media, peaks
    while True:
        try:
            path = _jobs.get(timeout=2.0)
        except queue.Empty:
            return
        try:
            _peaks[path] = peaks.compute(media.ensure_pcm(path))
        except Exception as e:
            _peaks[path] = None
            _errors[path] = str(e)
        _queued.discard(path)
        try:
            _relay.ready.emit(path)
        except RuntimeError:
            return


def wait_idle(timeout: float = 10.0) -> None:
    """Tests : attend la fin des calculs de miniatures."""
    end = time.monotonic() + timeout
    while (_queued or not _jobs.empty()) and time.monotonic() < end:
        time.sleep(0.01)


class AudioItem(BoardItem):
    MODULE = "miro"          # carte du Board de base (organise et référence ; pas un module d'édition)
    CONNECTABLE = True
    RESIZABLE = True
    KEEP_RATIO = False

    def __init__(self, data: dict):
        self._path_cache = None
        self._tip = None
        super().__init__(data)
        _get_relay().ready.connect(self._peaks_ready)

    # -- liens --
    def board_pane(self):
        scene = self.scene()
        parent = scene.parent() if scene is not None else None
        return parent if hasattr(parent, "save") else None

    def board_path(self):
        pane = self.board_pane()
        return getattr(pane, "path", None) if pane is not None else None

    def file_path(self) -> Path | None:
        """Fichier lié (relatif au board d'abord) ; gardé 2 s (la peinture le demande à chaque image)."""
        now = time.monotonic()
        key = (self.data.get("path"), self.data.get("rel"), self.board_path())
        c = self._path_cache
        if c is not None and c[0] == key and now - c[2] < 2.0:
            return c[1]
        path = bm.resolve(self.data, key[2])
        self._path_cache = (key, path, now)
        return path

    def _peaks_ready(self, path: str) -> None:
        try:
            p = self.file_path()
        except RuntimeError:
            return
        if p is not None and str(p) == path:
            info = _peaks.get(path)
            if info is not None and not self.data.get("duration"):
                self.data["duration"] = round(info.frames / max(1, info.sample_rate), 3)
                self.data["sample_rate"] = info.sample_rate
                self.data["channels"] = info.channels
            self.update()

    # -- peinture (aucun calcul : pics demandés en fond) --
    def paint(self, painter: QPainter, option, widget=None):
        from fm_sound_ui.ui_kit import tok
        w, h = self.size()
        body = QRectF(0, 0, w, h)
        path = self.file_path()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(tok("panel_border", "#3a3d42"), 1))
        painter.setBrush(tok("panel_bg", "#202226"))
        painter.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        font = QFont("Segoe UI")
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(tok("row_label", "#ddd"))
        title = self.data.get("title") or (path.stem if path else "son")
        painter.drawText(QRectF(PLAY_W + 8, 4, w - PLAY_W - 14, 18), Qt.AlignLeft | Qt.AlignVCenter, title)
        font.setBold(False)
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(tok("label_dim", "#999"))
        painter.drawText(QRectF(PLAY_W + 8, 21, w - PLAY_W - 14, 14), Qt.AlignLeft | Qt.AlignVCenter, bm.describe(self.data))
        # bouton de préécoute (triangle)
        play = QRectF(6, 8, PLAY_W - 8, PLAY_W - 8)
        playing = Preview.current() == str(path) if path else False
        painter.setPen(Qt.NoPen)
        painter.setBrush(tok("accent", "#3d8bfd"))
        if playing:
            painter.drawRect(play.adjusted(3, 3, -3, -3))
        else:
            from PySide6.QtGui import QPolygonF
            painter.drawPolygon(QPolygonF([QPointF(play.left() + 3, play.top() + 2), QPointF(play.right() - 2, play.center().y()),
                                           QPointF(play.left() + 3, play.bottom() - 2)]))
        wave = QRectF(8, 40, w - 16, h - 48)
        if path is None:
            painter.setPen(tok("dirty_dot", "#e05050"))
            painter.drawText(wave, Qt.AlignCenter | Qt.TextWordWrap,
                             "Fichier introuvable :\n%s\n(clic droit : relier)" % (self.data.get("rel") or self.data.get("path")))
        elif path.suffix.lower() in bm.SOUND_EXT:
            pk = _peaks.get(str(path))
            if pk is None:
                if str(path) in _errors:
                    painter.setPen(tok("dirty_dot", "#e05050"))
                    painter.drawText(wave, Qt.AlignCenter, "illisible")
                else:
                    request_peaks(str(path))
                    painter.setPen(tok("label_dim", "#999"))
                    painter.drawText(wave, Qt.AlignCenter, "…")
            else:
                width = max(1, int(wave.width()))
                mins, maxs = pk.view(0, pk.frames / width, width)
                mid, amp = wave.center().y(), wave.height() / 2
                painter.setPen(QPen(tok("accent", "#3d8bfd"), 1))
                lines = []
                for k in range(width):
                    lo, hi = float(mins[:, k].min()), float(maxs[:, k].max())
                    if lo != lo:
                        continue
                    x = wave.left() + k
                    lines += [QPointF(x, mid - hi * amp), QPointF(x, mid - lo * amp)]
                if lines:
                    painter.drawLines(lines)
        else:
            painter.setPen(tok("label_dim", "#999"))
            painter.drawText(wave, Qt.AlignCenter, "Projet FM Music" if self.data.get("module") == "music" else "Projet FM Audio")
        painter.restore()
        self._sync_tip(path)
        self.paint_selection(painter)

    def _sync_tip(self, path) -> None:
        tip = f"{self.data.get('role', 'son').capitalize()} : {self.data.get('title') or (path.name if path else '')}"
        if path is not None:
            tip += f"\n{path}"
        if self.data.get("note"):
            tip += f"\n{self.data['note']}"
        if tip != self._tip:
            self._tip = tip
            self.setToolTip(tip)

    # -- gestes --
    def mousePressEvent(self, event):
        p = event.pos()
        if event.button() == Qt.LeftButton and p.x() < PLAY_W and p.y() < PLAY_W + 4 and not event.modifiers():
            path = self.file_path()
            if path is not None and path.suffix.lower() in bm.SOUND_EXT:
                Preview.toggle(str(path))
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        """Menu de la carte : préécoute, ouverture dans le bon module, rôle, révisions, reliaison."""
        from fm_theme.menu import Menu
        path = self.file_path()
        menu = Menu(None)
        acts = {}
        if path is not None and path.suffix.lower() in bm.SOUND_EXT:
            acts[menu.addAction("Arrêter la préécoute" if Preview.current() == str(path) else "Préécouter")] = ("preview",)
        if path is not None:
            label = "Ouvrir dans FM Music" if self.data.get("module") == "music" else "Ouvrir dans FM Audio"
            acts[menu.addAction(label)] = ("open",)
        roles = menu.addMenu("Rôle")
        for r in bm.ROLES:
            a = roles.addAction(r)
            a.setCheckable(True)
            a.setChecked(self.data.get("role") == r)
            acts[a] = ("role", r)
        revs = revisions(self.data, self.board_path())
        if len(revs) > 1:
            sub = menu.addMenu("Révisions")
            for rev, p in revs:
                a = sub.addAction(f"r{rev} : {p.name}")
                a.setCheckable(True)
                a.setChecked(path is not None and p == path)
                acts[a] = ("revision", rev, p)
        acts[menu.addAction("Relier le fichier…" if path is None else "Changer de fichier…")] = ("relink",)
        chosen = menu.exec(event.screenPos())
        what = acts.get(chosen)
        if not what:
            event.accept()
            return
        if what[0] == "preview":
            Preview.toggle(str(path))
        elif what[0] == "open":
            open_in_module(self, self.data.get("module", "audio"), path)
        elif what[0] == "role":
            self._change({"role": what[1]}, "Rôle de la carte")
        elif what[0] == "revision":
            values = bm.relink(self.data, what[2], self.board_path())
            values["revision"] = what[1]
            self._change(values, "Révision de la carte")
        elif what[0] == "relink":
            from PySide6.QtWidgets import QFileDialog
            start = str(Path(self.data.get("path") or "").parent)
            exts = " ".join("*" + e for e in bm.SOUND_EXT + tuple(bm.PROJECT_EXT))
            new, _ = QFileDialog.getOpenFileName(None, "Relier la carte à un fichier", start, f"Sons et projets ({exts})")
            if new:
                self._change(bm.relink(self.data, new, self.board_path()), "Relier la carte")
        self.update()
        event.accept()

    def _change(self, values: dict, label: str) -> None:
        """Modification annulable par l'historique du Board (`change_items`)."""
        scene = self.scene()
        change = getattr(scene, "change_items", None) if scene is not None else None
        if change is not None:                    # une étape d'annulation du Board
            change([self], lambda item: item.data.update(values), label)
        else:
            self.apply(dict(self.data, **values))
        self._path_cache = None
    def mouseDoubleClickEvent(self, event):
        path = self.file_path()
        if path is None:
            return super().mouseDoubleClickEvent(event)
        open_in_module(self, self.data.get("module", "audio"), path)
        event.accept()


def open_in_module(item, key: str, path) -> bool:
    Preview.stop()
    fn = HOOKS.get("open")
    if fn is not None:
        fn(key, Path(path))
        return True
    scene = item.scene()
    for view in (scene.views() if scene is not None else []):
        win = view.window()
        if hasattr(win, "open_in_module"):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: win.open_in_module(key, Path(path)))   # après l'événement du Board
            return True
    return False


class Preview:
    """Préécoute par le moteur PARTAGÉ : jamais un second moteur ni un second périphérique ;
    refusée pendant une prise (la capture a priorité)."""
    _path: str | None = None

    @classmethod
    def current(cls) -> str | None:
        return cls._path

    @classmethod
    def toggle(cls, path: str) -> str:
        if cls._path == path:
            cls.stop()
            return "arrêt"
        return cls.play(path)

    @classmethod
    def play(cls, path: str) -> str:
        from fm_audio_engine import client, media, wavio
        from fm_audio_engine.preview import preview_spec
        try:
            eng = client.shared_engine()
        except client.EngineError as e:
            return f"moteur indisponible : {e}"
        if eng.telemetry.get("recording"):
            return "prise en cours : préécoute refusée"
        pcm = media.cached_pcm(path)
        if pcm is None:
            request_peaks(path)                  # décode en fond ; la préécoute marchera au prochain clic
            return "décodage en cours"
        try:
            sr = wavio.probe(pcm).sample_rate
            dev = getattr(eng, "device_info", None)
            if dev is None or dev.get("sample_rate") != sr:      # fréquence du son (WASAPI partagé convertit)
                if dev is not None:
                    eng.request("close_device", timeout=5.0)
                eng.device_info = None
                eng.device_info = eng.request("open_device", timeout=8.0, output=HOOKS.get("output", "default"), sample_rate=sr)
            eng.request("load", spec=preview_spec(pcm))
            eng.request("play", **{"from": 0})
        except client.EngineError as e:
            return f"préécoute impossible : {e}"
        cls._path = path
        return "lecture"

    @classmethod
    def stop(cls) -> None:
        if cls._path is None:
            return
        cls._path = None
        try:
            from fm_audio_engine import client
            eng = client.shared_engine(start=False)
            if eng is not None:
                eng.request("stop")
        except Exception:
            pass


def drop_files(board, paths, at) -> list:
    """Dépôt de fichiers sur le Board : une carte par son / projet. Retourne les fichiers pris."""
    from fm_board import model
    taken = [Path(p) for p in paths if bm.accepts(p) and Path(p).is_file()]
    for i, p in enumerate(taken):
        values = bm.link_values(p, getattr(board, "board_path", None))
        try:
            from fm_audio_engine import media
            if p.suffix.lower() in bm.SOUND_EXT:
                info = media.probe(p)
                values.update(duration=round(info.duration, 3), sample_rate=info.sample_rate, channels=info.channels, codec=info.codec)
        except Exception:
            pass
        w, h = bm.DEFAULTS[bm.AUDIO_DOC]["w"], bm.DEFAULTS[bm.AUDIO_DOC]["h"]
        data = model.new_item(bm.AUDIO_DOC, x=at.x() - w / 2 + 24 * i, y=at.y() - h / 2 + (h + 12) * i, **values)
        board.add_new(data, "Ajouter un son" if len(taken) == 1 else "Ajouter des sons")
    return taken


def revisions(data: dict, board_path=None) -> list:
    """Révisions d'un même son à côté du fichier lié : `<nom>__r<N>.wav` (traitements de FM Audio,
    original = r0). Aucun balayage global : seulement le dossier du fichier."""
    path = bm.resolve(data, board_path)
    if path is None:
        return []
    stem = path.stem.split("__r")[0]
    out = []
    for p in path.parent.glob(f"{stem}*{path.suffix}"):
        if p.stem == stem:
            out.append((0, p))
        elif p.stem.startswith(stem + "__r") and p.stem[len(stem) + 3:].isdigit():
            out.append((int(p.stem[len(stem) + 3:]), p))
    return sorted(out)


ITEM_CLASSES[bm.AUDIO_DOC] = AudioItem
