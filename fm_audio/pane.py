"""Pane FM Audio : montage non destructif multipiste, waveforms, édition, effets, mixer,
enregistrement, export. Contrat fenêtre : voir fm_sound_ui/editor_base.py."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from fm_audio_engine import edits, media
from fm_audio_engine.project import Bus, Clip, Fx, Project, Track
from fm_sound_ui.editor_base import EditorPane
from fm_sound_ui.ui_kit import menu

from . import AUDIO_EXTENSIONS

HOOKS: dict = {}

EFFECTS = (("eq", "EQ paramétrique"), ("compressor", "Compresseur"), ("limiter", "Limiteur"), ("gate", "Noise gate"),
           ("deesser", "De-esser"), ("filter", "Filtre"), ("reverb", "Réverbération"), ("delay", "Delay"),
           ("chorus", "Chorus"), ("distortion", "Saturation / distorsion"), ("overdrive", "Overdrive (pédale)"),
           ("amp", "Simulation d'ampli"), ("cabinet", "Cabinet (IR)"), ("gain", "Gain / polarité"))


class AudioPane(EditorPane):
    KIND = "audio"
    TITLE = "FM Audio"
    PROJECT_EXT = ".fmaudio"
    HOOKS = HOOKS

    def build_bars(self) -> None:
        b = self.bar2
        v = self.view
        self.add(b, "Importer…", "Importer des sons sur la piste courante, au curseur", self.import_dialog)
        self.add(b, "Piste +", "Ajouter une piste audio", self.add_track)
        self.add(b, "Bus +", "Ajouter un bus (retour d'effets)", self.add_bus)
        self.add(b, "Couper", "Couper (Ctrl+X)", lambda: v.cmd_copy(cut=True))
        self.add(b, "Copier", "Copier (Ctrl+C)", v.cmd_copy)
        self.add(b, "Coller", "Coller au curseur (Ctrl+V)", v.cmd_paste)
        self.add(b, "Supprimer", "Supprimer la sélection (Suppr ; Maj+Suppr : refermer le trou)", v.cmd_delete)
        self.add(b, "Scinder", "Scinder au curseur (S)", v.cmd_split)
        self.add(b, "Rogner", "Ne garder que la sélection", v.cmd_crop)
        self.add(b, "Normaliser", "Normaliser les clips choisis à -1 dBFS (gain du clip, non destructif)", self.normalize)
        self.add(b, "Fondus", "Fondus de 10 ms aux bords des clips choisis", self.default_fades)
        self.add(b, "Polarité", "Inverser la polarité des clips choisis", self.polarity)
        self.add(b, "Inverser", "Lire les clips choisis à l'envers", self.reverse)
        self.add(b, "Effets…", "Ajouter un effet à la piste courante", self.effects_menu)
        self.add(b, "Traitements…", "Traitements en nouvelle révision (l'original est conservé)", self.process_menu)
        self.add(b, "Spectre", "Spectrogramme du clip choisi (glisser : zone temps × fréquence)", self.toggle_spectrogram)
        self.btn_tuner = self.add(b, "Accordeur", "Accordeur en direct sur l'entrée de la piste courante", self.toggle_tuner, checkable=True)
        self.add(b, "Exporter…", "Exporter le mix (fichier vérifié, jamais écrasé sans accord)", self.export_dialog)
        self.add(b, "Stems…", "Exporter une piste par fichier (effets de bus inclus)", lambda: self.export_dialog(stems=True))
        self.add(b, "Zoom +", "Zoom avant (+ ; Ctrl+molette)", lambda: v.zoom(0.5))
        self.add(b, "Zoom −", "Zoom arrière (−)", lambda: v.zoom(2.0))
        self.add(b, "Ajuster", "Tout voir", v.zoom_fit)

    # ---------------------------------------------------------------- ouverture
    def file_filter(self) -> str:
        exts = " ".join("*" + e for e in AUDIO_EXTENSIONS)
        return f"Projet FM Audio (*.fmaudio);;Sons ({exts});;Tous les fichiers (*.*)"

    def open_other(self, path: Path) -> bool:
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            return super().open_other(path)
        if not self.confirm_leave():
            return False
        p = Project("audio", path.stem)
        t = Track(name=path.stem)
        p.tracks.append(t)
        try:
            info = media.probe(path)
        except media.MediaError as e:
            self.set_status(str(e))
            return False
        t.channels = 1 if info.channels == 1 else 2
        t.clips.append(Clip(path=str(path), name=path.stem, start=0, length=max(1, info.frames)))
        p.sample_rate = info.sample_rate or p.sample_rate
        self.session.set_project(p)
        self.after_load()
        self.set_status(f"{path.name} : {info.channels} canal(aux), {info.sample_rate} Hz, {info.duration:.2f} s, {info.codec}")
        return True

    def suggest_path(self) -> str:
        for t in self.project.tracks:
            for c in t.clips:
                if c.path:
                    return str(Path(c.path).with_suffix(".fmaudio"))
        return super().suggest_path()

    def import_dialog(self) -> None:
        exts = " ".join("*" + e for e in AUDIO_EXTENSIONS)
        paths, _ = QFileDialog.getOpenFileNames(self, "Importer des sons", "", f"Sons ({exts})")
        if paths:
            self.import_files(paths)

    def import_files(self, paths, at: int | None = None) -> list:
        p = self.project
        tid = self.view.current_track
        made = []
        with p.edit("Importer", structure=True):
            t = p.track(tid) if tid else None
            if t is None:
                t = Track(name=Path(paths[0]).stem)
                p.tracks.append(t)
            pos = self.session.cursor if at is None else at
            for path in paths:
                try:
                    info = media.probe(path)
                except media.MediaError as e:
                    self.set_status(str(e))
                    continue
                c = Clip(path=str(path), name=Path(path).stem, start=pos, length=max(1, int(round(info.frames * p.sample_rate / max(1, info.sample_rate)))))
                t.clips.append(c)
                made.append(c.id)
                pos = c.end
            t.clips.sort(key=lambda c: c.start)
        self.view.current_track = t.id
        return made

    # ---------------------------------------------------------------- pistes
    def add_track(self) -> None:
        t = self.project.add_track(name=f"Piste {len(self.project.tracks) + 1}")
        self.view.current_track = t.id

    def add_bus(self) -> None:
        p = self.project
        with p.edit("Ajouter un bus", structure=True):
            b = Bus(name=f"Bus {len(p.buses) + 1}", fx=[Fx("reverb", {"mix": 1.0})])
            p.buses.append(b)
            t = p.track(self.view.current_track) if self.view.current_track else None
            if t is not None:
                t.sends.append({"target": b.id, "gain_db": -12.0, "pre": False})
        self.set_status(f"{b.name} ajouté (réverbe 100 % mouillée)" + (f", envoi depuis {t.name}" if t else ""))

    # ---------------------------------------------------------------- édition
    def _selected(self) -> dict:
        out: dict[str, set] = {}
        for tid, cid in self.view.sel_clips:
            out.setdefault(tid, set()).add(cid)
        return out

    def normalize(self) -> None:
        sel = self._selected()
        if not sel:
            self.set_status("Choisir un ou plusieurs clips")
            return
        n = 0
        with self.project.edit("Normaliser", *sel.keys()):
            for tid, ids in sel.items():
                n += len(edits.normalize(self.project, tid, ids, -1.0, resolve=self.session.resolve))
        self.set_status(f"{n} clip(s) normalisé(s) à -1 dBFS")

    def default_fades(self) -> None:
        sr = self.project.sample_rate
        with self.project.edit("Fondus", *self._selected().keys()):
            for tid, ids in self._selected().items():
                for cid in ids:
                    edits.set_fades(self.project, tid, cid, fade_in=sr // 100, fade_out=sr // 100)

    def polarity(self) -> None:
        with self.project.edit("Polarité", *self._selected().keys()):
            for tid, ids in self._selected().items():
                edits.invert_polarity(self.project, tid, ids)

    def reverse(self) -> None:
        sel = self._selected()
        with self.project.edit("Inverser", *sel.keys()):
            for tid, ids in sel.items():
                for c in self.project.track(tid).clips:
                    if c.id in ids:
                        c.reverse = not c.reverse

    def effects_menu(self) -> None:
        t = self.project.track(self.view.current_track) if self.view.current_track else None
        if t is None:
            self.set_status("Choisir une piste (clic dans son en-tête)")
            return
        from fm_audio_engine import presets
        m = menu(self)
        acts = {m.addAction(name): kind for kind, name in EFFECTS}
        chains = presets.chains()
        sub = m.addMenu("Chaînes (préréglages)")
        for name in chains:
            acts[sub.addAction(name)] = ("chain", name)
        from fm_sound_ui import plugins_ui
        pacts = plugins_ui.add_library_menu(m, "effects", self._settings())
        if t.fx:
            acts[m.addAction("Enregistrer la chaîne comme préréglage…")] = ("save_chain", 0)
            m.addSeparator()
            for i, f in enumerate(t.fx):
                a = m.addAction(f"Retirer : {f.name or f.type}")
                acts[a] = ("remove", i)
        eacts = plugins_ui.add_slot_actions(m, self.session)
        chosen = m.exec(self.mapToGlobal(self.view.geometry().center()))
        if chosen in eacts:
            plugins_ui.open_editor(self, *eacts[chosen][1])
            return
        if chosen in pacts:
            item = plugins_ui.handle_library_choice(self, pacts[chosen])
            if item:
                from fm_audio_engine import plugins
                with self.project.edit("Plugin", t.id):
                    t.fx.append(plugins.fx_for(item))
                self.set_status(f"{t.name} : {item['name']} ajouté" + (f" (latence {item['latency']} éch., compensée)" if item.get("latency") else ""))
            return
        if chosen not in acts:
            return
        what = acts[chosen]
        if isinstance(what, tuple) and what[0] == "save_chain":
            from fm_sound_ui.ui_kit import ask_value
            name = ask_value(self, "Préréglage", "Nom de la chaîne d'effets", t.name)
            if name:
                presets.save_chain(name, t.fx)
                self.set_status(f"Chaîne « {name} » enregistrée")
            return
        with self.project.edit("Effets", t.id):
            if isinstance(what, tuple) and what[0] == "chain":
                t.fx = [Fx.from_dict(f) for f in chains[what[1]]]
            elif isinstance(what, tuple):
                del t.fx[what[1]]
            else:
                t.fx.append(Fx(what, {}))
        self.set_status(f"{t.name} : {', '.join(f.name or f.type for f in t.fx) or 'aucun effet'}")

    def process_menu(self) -> None:
        from . import processing
        processing.menu_for(self)

    # ---------------------------------------------------------------- accordeur en direct
    def toggle_tuner(self) -> None:
        on = self.btn_tuner.isChecked()
        if on and not self.session.ensure_device():
            self.btn_tuner.setChecked(False)
            return
        if on and not (self.session.device or {}).get("in_channels"):
            self.set_status("Accordeur : aucune entrée ouverte (choisir une entrée dans « Audio… »)")
            self.btn_tuner.setChecked(False)
            return
        t = self.project.track(self.view.current_track) if self.view.current_track else None
        ch = max(0, t.input) if t is not None else 0
        try:
            self.session.engine.request("tuner", input=ch if on else -1)
        except Exception as e:
            self.set_status(f"Accordeur : {e}")

    def _on_tick(self, t: dict) -> None:
        super()._on_tick(t)
        hz = t.get("tuner_hz")
        if hz:
            from fm_audio_engine import analysis
            ref = float(self._settings().get("audio_tuner_reference", 440.0))
            n = analysis.tuner(hz, ref)
            self.clock.setText(f"{n['note']}{n['octave']} {n['cents']:+.0f} c  ({hz:.1f} Hz)")
    # ---------------------------------------------------------------- spectrogramme
    def toggle_spectrogram(self) -> None:
        if getattr(self, "spectro", None) is None:
            from .spectrogram import SpectrogramView
            self.spectro = SpectrogramView(self.view)
            self.center.layout().insertWidget(1, self.spectro)
            self.spectro.hide()
        self.spectro.setVisible(not self.spectro.isVisible())
