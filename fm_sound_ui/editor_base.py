"""Base des panes FM Audio / FM Music : recouvre les colonnes de la fenêtre (suit la taille de son
parent), barre d'outils (briques fm_theme), transport, mixer, fichier (ouvrir, enregistrer, fermer
prudemment), statut. Contrat attendu par la fenêtre (comme fm_pdf) : HOOKS, closeRequested,
stateChanged, open_path, confirm_leave, request_close, shutdown, apply_settings, view.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from fm_audio_engine.project import Project, ProjectError

from .mixer import MixerPanel
from .session import AudioSession
from .timeline import TimelineView
from .ui_kit import button, choose, fmt_time, label, menu, tok


def new_sample_rate(settings: dict | None) -> int:
    try:
        sr = int((settings or {}).get("audio_new_sample_rate", 48000))
    except (TypeError, ValueError):
        return 48000
    return sr if sr in (44100, 48000, 88200, 96000) else 48000


class EditorPane(QWidget):
    closeRequested = Signal()
    stateChanged = Signal()
    transportChanged = Signal()      # lecture / prise / boucle / métronome / mixer : émis au CHANGEMENT seulement
    KIND = "audio"
    TITLE = "FM Audio"
    PROJECT_EXT = ".fmaudio"
    HOOKS: dict = {}

    def __init__(self, parent=None, hooks: dict | None = None):
        super().__init__(parent)
        self.hooks = hooks if hooks is not None else self.HOOKS
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), tok("panel_bg", "#202226"))
        self.setPalette(pal)
        self.session = AudioSession(self.make_new_project(), settings=self._settings, parent=self)
        self.session.status.connect(self.set_status)
        self.session.changed.connect(self._on_changed)
        self.session.tick.connect(self._on_tick)
        self.session.jobProgress.connect(self._job_progress)
        self.session.jobDone.connect(self._job_done)
        self._jobs: dict[int, str] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)
        self.bar1 = QHBoxLayout()
        self.bar2 = QHBoxLayout()
        root.addLayout(self.bar1)
        root.addLayout(self.bar2)
        self.view = TimelineView(self.session, music=self.KIND == "music")
        self.view.selectionChanged.connect(self.stateChanged)
        self.mixer = MixerPanel(self.session)
        self.split = QSplitter(Qt.Vertical)
        self.center = QWidget()
        cl = QVBoxLayout(self.center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.view)
        from .takes import TakesPanel
        self.takes = TakesPanel(self.view)
        cl.addWidget(self.takes)
        self.takes.hide()
        self.split.addWidget(self.center)
        self.split.addWidget(self.mixer)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        root.addWidget(self.split, 1)
        foot = QHBoxLayout()
        self.status = label("", "row_note")
        self.clock = label("00:00.000", "value_mono")
        foot.addWidget(self.status, 1)
        foot.addWidget(self.clock)
        root.addLayout(foot)
        self._build_common_bar()
        self.build_bars()
        self.bar1.addStretch(1)
        self.bar2.addStretch(1)
        self.mixer.setVisible(bool(self._settings().get("audio_mixer_visible", True)))
        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())
        QTimer.singleShot(0, self.view, self.view.zoom_fit)   # annulé si la vue est détruite

    # ---------------------------------------------------------------- hooks / réglages
    def _settings(self) -> dict:
        fn = self.hooks.get("settings")
        try:
            return dict(fn() or {}) if fn else {}
        except Exception:
            return {}

    def apply_settings(self, settings: dict) -> None:
        self.view.snap_on = bool(settings.get("music_snap", True)) if self.KIND == "music" else False
        self.view.update()

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        fn = self.hooks.get("status")
        if fn:
            try:
                fn(f"{self.TITLE} : {text}")
            except Exception:
                pass

    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    # ---------------------------------------------------------------- barre commune
    def add(self, bar, text: str, tip: str, slot, checkable: bool = False):
        b = button(text, tip, slot, checkable=checkable)
        bar.addWidget(b)
        return b

    def _build_common_bar(self) -> None:
        b = self.bar1
        self.add(b, "Nouveau", "Nouveau projet", self.new_project)
        self.add(b, "Ouvrir…", "Ouvrir un projet ou un son (Ctrl+O)", self.open_dialog)
        self.btn_save = self.add(b, "Enregistrer", "Enregistrer le projet (Ctrl+S)", self.save)
        self.add(b, "Enregistrer sous…", "Enregistrer le projet sous…", lambda: self.save(ask=True))
        self.btn_undo = self.add(b, "Annuler", "Annuler (Ctrl+Z)", lambda: self.session.project.history.undo())
        self.btn_redo = self.add(b, "Rétablir", "Rétablir (Ctrl+Y)", lambda: self.session.project.history.redo())
        self.btn_play = self.add(b, "Lecture", "Lecture / arrêt (Espace)", self.session.toggle_play)
        self.btn_rec = self.add(b, "Enreg.", "Enregistrer les pistes armées (R dans l'en-tête de piste)", self.toggle_record, checkable=True)
        self.btn_loop = self.add(b, "Boucle", "Boucle (L ; Maj + glisser dans la règle pour la placer)", self.toggle_loop, checkable=True)
        self.btn_metro = self.add(b, "Métronome", "Métronome", self.toggle_metronome, checkable=True)
        self.btn_mixer = self.add(b, "Mixer", "Afficher / masquer le mixer", self.toggle_mixer)
        self.add(b, "Prises", "Couloirs de prises de la piste courante (comping, looper)", lambda: self.takes.setVisible(not self.takes.isVisible()))
        self.add(b, "Automation…", "Couloir d'automation de la piste courante (A : volume)", self.automation_menu)
        self.add(b, "Bibliothèque…", "Bibliothèque commune : insérer, nouvelles révisions, médias absents", self.library_menu)
        self.add(b, "Publier", "Publier le son des clips choisis dans la bibliothèque (nouvelle révision)", self.publish_selected)
        self.add(b, "Audio…", "Périphériques audio", self.device_menu)
        self.btn_settings = self.add(b, "Réglages", "Réglages : Audio (périphérique, export, enregistrement)", self.open_settings)
        self.btn_close = self.add(b, "Fermer", f"Fermer {self.TITLE}", self.request_close)
        if self.hooks.get("navbar_frame"):
            # Cadre du module dans la barre de navigation (main_window/audio_module.py) : ses outils n'ont pas de
            # doublon ici.
            for w in (self.btn_undo, self.btn_redo, self.btn_play, self.btn_rec, self.btn_loop, self.btn_metro,
                      self.btn_mixer, self.btn_settings, self.btn_close):
                w.hide()
        self._transport = None

    def build_bars(self) -> None:
        """Barres propres à l'éditeur (surchargé)."""

    # ---------------------------------------------------------------- fichier
    @property
    def project(self) -> Project:
        return self.session.project

    def new_project(self) -> None:
        if not self.confirm_leave():
            return
        self.session.set_project(self.make_new_project())
        self.after_load()

    def make_new_project(self) -> Project:
        """Projet neuf : fréquence du réglage « audio_new_sample_rate » (FM Music : morceau de départ)."""
        return Project(self.KIND, "Sans titre", sample_rate=new_sample_rate(self._settings()))

    def open_dialog(self) -> None:
        start = str(Path(self.project.path).parent) if self.project.path else ""
        path, _ = QFileDialog.getOpenFileName(self, f"Ouvrir dans {self.TITLE}", start, self.file_filter())
        if path:
            self.open_path(path)

    def file_filter(self) -> str:
        return f"Projet {self.TITLE} (*{self.PROJECT_EXT});;Tous les fichiers (*.*)"

    def open_path(self, path) -> bool:
        path = Path(path)
        if path.suffix.lower() == self.PROJECT_EXT:
            if not self.confirm_leave():
                return False
            try:
                p = Project.load(path)
            except ProjectError as e:
                self.set_status(str(e))
                return False
            self.session.set_project(p)
            self.after_load()
            self.set_status(f"Projet ouvert : {path.name}")
            return True
        return self.open_other(path)

    def open_other(self, path: Path) -> bool:
        self.set_status(f"Type non pris en charge : {path.suffix}")
        return False

    def after_load(self) -> None:
        self.view.sel = None
        self.view.sel_clips.clear()
        QTimer.singleShot(0, self.view, self.view.zoom_fit)   # annulé si la vue est détruite
        self.stateChanged.emit()

    def save(self, ask: bool = False) -> bool:
        p = self.project
        target = p.path
        if ask or not target:
            start = target or self.suggest_path()
            target, _ = QFileDialog.getSaveFileName(self, "Enregistrer le projet", start, f"Projet (*{self.PROJECT_EXT})")
            if not target:
                return False
            if not target.lower().endswith(self.PROJECT_EXT):
                target += self.PROJECT_EXT
            p.name = Path(target).stem
        self.session.capture_plugin_states()            # états des plugins VST3 (éditeurs, automation)
        try:
            p.save(target)
        except (OSError, ProjectError) as e:
            self.set_status(f"Enregistrement impossible : {e}")
            return False
        self.set_status(f"Enregistré : {Path(target).name}")
        self.stateChanged.emit()
        return True

    def suggest_path(self) -> str:
        return (self.project.name or "Sans titre") + self.PROJECT_EXT

    def confirm_leave(self) -> bool:
        if not self.project.history.dirty:
            return True
        r = choose(self, "Projet modifié", f"« {self.project.name} » a été modifié.",
                   [("save", "Enregistrer"), ("discard", "Ne pas enregistrer"), ("cancel", "Annuler")])
        if r == "save":
            return self.save()
        return r == "discard"

    def request_close(self) -> None:
        if self.confirm_leave():
            self.closeRequested.emit()

    def shutdown(self) -> None:
        self.session.shutdown()

    @property
    def recording(self) -> bool:
        return self.session.recording

    # ---------------------------------------------------------------- transport
    def toggle_record(self) -> None:
        if self.session.recording:
            made = self.session.stop_recording()
            self.set_status(f"{len(made)} prise(s) ajoutée(s)")
        else:
            bars = int(self._settings().get("audio_precount_bars", 1))
            if not self.session.start_recording(bars):
                self.btn_rec.setChecked(False)
        self.btn_rec.setChecked(self.session.recording)
        self._emit_transport()

    def toggle_loop(self) -> None:
        lp = self.project.loop
        if self.view.sel:
            self.project.loop = {"on": True, "start": self.view.sel[0], "end": self.view.sel[1]}
        else:
            lp["on"] = not lp.get("on")
        self.btn_loop.setChecked(bool(self.project.loop.get("on")))
        self._emit_transport()
        if self.session.playing and self.session.engine is not None:
            lp = self.project.loop
            self.session.engine.request("loop", on=bool(lp.get("on")), start=int(lp.get("start", 0)), end=int(lp.get("end", 0)))
        self.view.update()

    def toggle_metronome(self) -> None:
        self.session.metronome(self.btn_metro.isChecked(), float(self._settings().get("audio_metronome_level", 0.5)))
        self._emit_transport()

    def flip_metronome(self) -> None:
        """Bouton du cadre (sans case cochée à lui) : bascule puis applique."""
        self.btn_metro.setChecked(not self.btn_metro.isChecked())
        self.toggle_metronome()

    def toggle_mixer(self) -> None:
        on = not self.mixer.isVisible()
        self.mixer.setVisible(on)
        fn = self.hooks.get("save_live_state")
        if fn:
            fn("audio_mixer_visible", on)
        self._emit_transport()

    def open_settings(self) -> None:
        fn = self.hooks.get("open_settings")
        if fn:
            fn()

    def transport_state(self) -> dict:
        h = self.project.history
        return {"playing": bool(self.session.playing), "recording": bool(self.session.recording),
                "loop": bool(self.project.loop.get("on")), "metronome": self.btn_metro.isChecked(),
                "mixer": not self.mixer.isHidden(), "can_undo": h.can_undo(), "can_redo": h.can_redo()}

    def _emit_transport(self) -> None:
        st = self.transport_state()
        if st != self._transport:
            self._transport = st
            self.transportChanged.emit()

    def device_menu(self) -> None:
        if not self.session.ensure_engine():
            return
        try:
            devs = self.session.engine.request("devices", timeout=5.0).get("devices", [])
        except Exception as e:
            self.set_status(f"Périphériques : {e}")
            return
        s = self._settings()
        m = menu(self)
        acts = {}
        for flow, title, key in (("output", "Sortie", "audio_output_device"), ("input", "Entrée", "audio_input_device")):
            m.addSection(title) if hasattr(m, "addSection") else None
            if flow == "input":
                a = m.addAction("Aucune entrée")
                a.setCheckable(True)
                a.setChecked(not s.get(key))
                acts[a] = (key, "")
            for d in devs:
                if d.get("flow") not in (flow, "duplex"):        # pilote ASIO : sortie ET entrée
                    continue
                info = "ASIO" if d.get("backend") == "asio" else f"{d.get('sample_rate', '?')} Hz"
                a = m.addAction(f"{d.get('name', '?')}  ({info}{', défaut' if d.get('default') else ''})")
                a.setCheckable(True)
                cur = s.get(key) or ("default" if flow == "output" else "")
                a.setChecked(cur == d["id"] or (cur == "default" and d.get("default") and flow == "output"))
                acts[a] = (key, d["id"])
        chosen = m.exec(self.mapToGlobal(self.rect().center()))
        if chosen in acts:
            key, value = acts[chosen]
            fn = self.hooks.get("save_live_state")
            if fn:
                fn(key, value)
            # le périphérique sera rouvert au prochain besoin
            eng = self.session.engine
            if eng is not None and not self.session.recording:
                try:
                    eng.request("close_device", timeout=5.0)
                except Exception:
                    pass
                eng.device_info = None
            self.set_status("Périphérique choisi : " + chosen.text())

    # ---------------------------------------------------------------- mise à jour
    def _on_changed(self) -> None:
        h = self.project.history
        self.btn_undo.setEnabled(h.can_undo())
        self.btn_redo.setEnabled(h.can_redo())
        self.stateChanged.emit()
        self._emit_transport()

    def _on_tick(self, t: dict) -> None:
        self.clock.setText(fmt_time(int(t.get("pos", 0)), self.project.sample_rate))
        self.btn_play.setText("Stop" if t.get("playing") else "Lecture")
        if self._transport is None or bool(t.get("playing")) != self._transport["playing"] \
                or self.session.recording != self._transport["recording"]:
            self._emit_transport()                       # quelques booléens comparés : rien de refait sinon
        if t.get("device_lost"):
            self.set_status("Périphérique audio perdu (débranché ?) : choisir un autre périphérique")

    # ---------------------------------------------------------------- export
    def export_dialog(self, stems: bool = False) -> None:
        start = str(Path(self.project.path).with_suffix("")) if self.project.path else self.project.name
        fmt = self._settings().get("audio_export_format", "pcm24")
        if stems:
            d = QFileDialog.getExistingDirectory(self, "Dossier des stems", str(Path(start).parent))
            if not d:
                return
            job = self.session.export(str(Path(d) / "_mix.wav"), stems_dir=d, fmt=fmt)
            label_ = f"stems dans {d}"
        else:
            out, _ = QFileDialog.getSaveFileName(self, "Exporter le mix", start + "_mix.wav", "WAV (*.wav)")
            if not out:
                return
            job = self.session.export(out, fmt=fmt)
            label_ = Path(out).name
        if job is not None:
            self._jobs[job] = label_
            self.set_status(f"Export en cours : {label_} (Échap n'annule pas un export ; bouton Annuler l'export)")

    def _job_progress(self, job: int, p: float) -> None:
        if job in self._jobs:
            self.set_status(f"Export {self._jobs[job]} : {p * 100:.0f} %")

    def _job_done(self, job: int, msg: dict) -> None:
        name = self._jobs.pop(job, None)
        if name is None:
            return
        if not msg.get("ok"):
            self.set_status(f"Export échoué : {msg.get('error')}")
        elif (msg.get("result") or {}).get("cancelled"):
            self.set_status("Export annulé (aucun fichier écrit)")
        else:
            r = msg.get("result") or {}
            n = len(r.get("stems", [])) if "stems" in r else 1
            self.set_status(f"Export terminé : {name} ({n} fichier(s) vérifié(s))")

    def cancel_exports(self) -> None:
        for job in list(self._jobs):
            self.session.cancel_job(job)

    # ---------------------------------------------------------------- bibliothèque commune
    def library(self):
        import os
        from fm_audio_engine import library
        root = self._settings().get("audio_library_root") or os.path.join(
            os.environ.get("LOCALAPPDATA") or str(Path.home()), "PIPE_FMZ", "bibliotheque_audio")
        if getattr(self, "_lib", None) is None or str(self._lib.root) != str(root):
            self._lib = library.Library(root)
        return self._lib

    def publish_selected(self) -> None:
        """Publie le son des clips choisis comme nouvelle révision (même ressource si déjà publiée)."""
        from fm_audio_engine import library
        items = list(self.view.sel_clips)
        if not items:
            self.set_status("Choisir un clip à publier")
            return
        lib = self.library()
        done = []
        with self.project.edit("Publier", *{tid for tid, _ in items}):
            for tid, cid in items:
                c = next((x for x in self.project.track(tid).clips if x.id == cid), None)
                if c is None or not c.path:
                    continue
                try:
                    rid, n = lib.publish(c.path, c.name or Path(c.path).stem, "son", resource=c.resource or None,
                                         recipe={"from_project": self.project.id}, source=(c.resource, c.revision) if c.resource else None)
                except library.LibraryError as e:
                    self.set_status(str(e))
                    continue
                c.resource, c.revision, c.path = rid, n, str(lib.revision_path(rid, n))
                done.append(f"{c.name or rid} r{n}")
        if done:
            self.set_status("Publié : " + ", ".join(done))

    def library_menu(self) -> None:
        """Insérer une ressource au curseur ; propositions de nouvelles révisions (adopter / refuser)."""
        from fm_audio_engine import library
        lib = self.library()
        lib.rebuild()
        m = menu(self)
        acts = {}
        ups = library.pending_updates(self.project, lib)
        for u in ups:
            a = m.addAction(f"Nouvelle révision : {lib.manifest(u['resource'])['name']} r{u['current']} → r{u['proposed']}")
            acts[a] = ("update", u)
        if ups:
            m.addSeparator()
        sub = m.addMenu("Insérer depuis la bibliothèque")
        for r in lib.resources():
            n = lib.latest(r["id"])
            if n:
                acts[sub.addAction(f"{r['name']} (r{n}, {r.get('kind', 'son')})")] = ("insert", r["id"])
        for d in lib.diagnostics[:5]:
            a = m.addAction("⚠ " + d)
            a.setEnabled(False)
        miss = library.missing_media(self.project)
        if miss:
            acts[m.addAction(f"Relier {len(miss)} média(s) absent(s)…")] = ("relink", miss)
        chosen = m.exec(self.mapToGlobal(self.view.geometry().center()))
        what = acts.get(chosen)
        if not what:
            return
        if what[0] == "insert":
            tid = self.view.current_track or (self.project.tracks[0].id if self.project.tracks else None)
            if tid is None:
                tid = self.project.add_track(name="Bibliothèque").id
            library.insert(self.project, lib, what[1], tid, self.session.cursor)
        elif what[0] == "update":
            u = what[1]
            r = choose(self, "Nouvelle révision", f"Adopter r{u['proposed']} à la place de r{u['current']} ?",
                       [("adopt", "Adopter"), ("refuse", "Refuser cette révision"), ("cancel", "Plus tard")])
            if r == "adopt":
                rep = library.adopt(self.project, lib, u["track"], u["clip"], u["proposed"])
                self.set_status(f"r{rep['to']} adoptée" + (" ; " + " ; ".join(rep["adjusted"]) if rep["adjusted"] else "")
                                + " (Ctrl+Z annule)")
            elif r == "refuse":
                library.refuse(self.project, lib, u["resource"], u["proposed"])
        elif what[0] == "relink":
            for mm in what[1]:
                new, _ = QFileDialog.getOpenFileName(self, f"Relier {Path(mm['path']).name}", str(Path(mm["path"]).parent))
                if new:
                    library.relink(self.project, mm["path"], new)
    def automation_menu(self) -> None:
        from . import automation
        t = self.project.track(self.view.current_track) if self.view.current_track else None
        if t is None:
            self.set_status("Choisir une piste (clic dans son en-tête)")
            return
        m = menu(self)
        acts = {}
        for target, label_ in automation.targets(t):
            a = m.addAction(label_)
            a.setCheckable(True)
            a.setChecked(self.view.auto_target == target)
            acts[a] = target
        m.addSeparator()
        acts[m.addAction("Masquer l'automation")] = None
        chosen = m.exec(self.mapToGlobal(self.view.geometry().center()))
        if chosen in acts:
            self.view.auto_target = acts[chosen]
            self.view.update()