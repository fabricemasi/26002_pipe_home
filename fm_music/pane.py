"""Pane FM Music : arrangement (pistes instrument et audio, clips MIDI, patterns, sections),
piano roll, instruments internes (synthé, sampler, boîte à rythmes), tempo / signatures,
quantification et groove réversibles, MIDI standard, enregistrement direct (même moteur),
mixer et export. Contrat fenêtre : voir fm_sound_ui/editor_base.py."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QSplitter

from fm_audio_engine import media, midi
from fm_audio_engine.project import PPQ, Clip, MidiClip, Note, Project, Track, new_id
from fm_sound_ui.editor_base import EditorPane
from fm_sound_ui.ui_kit import ask_value, menu

from . import MIDI_EXTENSIONS
from .pianoroll import PianoRoll
from .presets import INSTRUMENT_PRESETS

HOOKS: dict = {}
AUDIO_EXT = (".wav", ".mp3", ".flac", ".ogg", ".aif", ".aiff", ".m4a")


def default_project(settings: dict | None = None) -> Project:
    """Morceau neuf (réglages « Nouveaux morceaux » de FM Music) : tempo, signature, fréquence ; batterie + basse
    de départ, ou une piste synthé vide."""
    from fm_sound_ui.editor_base import new_sample_rate
    s = settings or {}
    p = Project("music", "Sans titre", sample_rate=new_sample_rate(s))
    try:
        p.tempo = [{"tick": 0, "bpm": max(20.0, min(400.0, float(s.get("music_new_tempo", 120.0))))}]
    except (TypeError, ValueError):
        pass
    num, _, den = str(s.get("music_new_signature", "4/4")).partition("/")
    if num.isdigit() and den.isdigit() and int(num) > 0 and int(den) in (2, 4, 8, 16):
        p.signatures = [{"tick": 0, "num": int(num), "den": int(den)}]
    if not s.get("music_new_demo", True):
        p.tracks.append(Track(name="Synthé", kind="instrument", instrument=dict(INSTRUMENT_PRESETS["Basse ronde"])))
        p.history.mark_saved()
        return p
    drums = Track(name="Batterie", kind="instrument", instrument={"type": "drums"})
    pid = new_id("pat")
    p.patterns[pid] = {"name": "Rythme 1", "length_tick": 4 * PPQ, "notes": [
        Note(0, PPQ // 4, 36, 110), Note(PPQ, PPQ // 4, 38, 100), Note(2 * PPQ, PPQ // 4, 36, 110), Note(3 * PPQ, PPQ // 4, 38, 100)]
        + [Note(k * PPQ // 2, PPQ // 8, 42, 70) for k in range(8)]}
    drums.midi_clips.append(MidiClip(name="Rythme 1", start_tick=0, length_tick=8 * PPQ, pattern=pid))
    synth = Track(name="Synthé", kind="instrument", instrument=dict(INSTRUMENT_PRESETS["Basse ronde"]))
    synth.midi_clips.append(MidiClip(name="Basse", start_tick=0, length_tick=8 * PPQ, notes=[
        Note(0, PPQ, 36, 100), Note(2 * PPQ, PPQ, 43, 100), Note(4 * PPQ, PPQ, 41, 100), Note(6 * PPQ, PPQ, 43, 100)]))
    p.tracks += [drums, synth]
    p.loop = {"on": False, "start": 0, "end": p.tempo_map().tick_to_sample(8 * PPQ)}
    p.history.mark_saved()
    return p


def grid_of(settings: dict | None) -> int:
    try:
        g = int((settings or {}).get("music_grid", PPQ // 4))
    except (TypeError, ValueError):
        return PPQ // 4
    return g if g in (PPQ, PPQ // 2, PPQ // 3, PPQ // 4, PPQ // 8) else PPQ // 4


class MusicPane(EditorPane):
    KIND = "music"
    TITLE = "FM Music"
    PROJECT_EXT = ".fmmusic"
    HOOKS = HOOKS

    def __init__(self, parent=None, hooks: dict | None = None):
        super().__init__(parent, hooks)
        self.roll = PianoRoll(self.session)
        self.roll.grid = grid_of(self._settings())
        self.inner = QSplitter(Qt.Vertical)
        lay = self.center.layout()
        lay.removeWidget(self.view)
        self.inner.addWidget(self.view)
        self.inner.addWidget(self.roll)
        self.inner.setStretchFactor(0, 1)
        self.inner.setStretchFactor(1, 1)
        lay.insertWidget(0, self.inner)          # au-dessus des couloirs de prises
        self.view.clipActivated.connect(self.edit_clip)
        first = next((t for t in self.project.tracks if t.midi_clips), None)
        if first is not None:
            self.roll.set_clip(first.id, first.midi_clips[0].id)

    def build_bars(self) -> None:
        b = self.bar2
        v = self.view
        self.add(b, "Instrument +", "Ajouter une piste instrument (préréglage)", self.add_instrument_track)
        self.add(b, "Audio +", "Ajouter une piste audio (enregistrement direct possible)", self.add_audio_track)
        self.add(b, "Clip +", "Nouveau clip MIDI de 4 mesures au curseur, sur la piste courante", self.add_clip)
        self.add(b, "Pattern", "Transformer le clip choisi en pattern réutilisable, ou en poser une copie", self.pattern_menu)
        self.add(b, "Quantifier", "Quantifier les notes du clip (Q ; Maj+Q annule)", lambda: self.quantize(False))
        self.add(b, "Déquantifier", "Rétablir les positions d'origine", lambda: self.quantize(True))
        self.add(b, "Swing…", "Quantifier avec swing", self.swing)
        self.add(b, "Instrument…", "Préréglage de l'instrument de la piste courante", self.instrument_menu)
        self.add(b, "Tempo…", "Tempo au curseur (crée un changement de tempo)", self.set_tempo)
        self.add(b, "Mesure…", "Signature rythmique", self.set_signature)
        self.add(b, "Section", "Poser un repère de section au curseur", self.add_section)
        self.add(b, "Importer MIDI…", "Importer un fichier MIDI standard", self.import_midi_dialog)
        self.add(b, "Exporter MIDI…", "Exporter les pistes en fichier MIDI standard", self.export_midi)
        self.add(b, "Exporter…", "Exporter le morceau en audio", self.export_dialog)
        self.add(b, "Stems…", "Exporter une piste par fichier", lambda: self.export_dialog(stems=True))
        self.add(b, "MIDI…", "Clavier MIDI : entrée, sortie, piste jouée, MIDI thru", self.midi_menu)
        self.add(b, "Panique", "Coupe toutes les notes (notes bloquées)", self.panic)
        self.add(b, "Zoom +", "Zoom avant", lambda: v.zoom(0.5))
        self.add(b, "Zoom −", "Zoom arrière", lambda: v.zoom(2.0))

    # ---------------------------------------------------------------- fichiers
    def file_filter(self) -> str:
        return "Projet FM Music (*.fmmusic);;MIDI (*.mid *.midi);;Tous les fichiers (*.*)"

    def new_project(self) -> None:
        if not self.confirm_leave():
            return
        self.session.set_project(default_project())
        self.after_load()

    def after_load(self) -> None:
        super().after_load()
        first = next((t for t in self.project.tracks if t.midi_clips), None)
        if first is not None and hasattr(self, "roll"):
            self.roll.set_clip(first.id, first.midi_clips[0].id)

    def open_other(self, path: Path) -> bool:
        if path.suffix.lower() in MIDI_EXTENSIONS:
            if not self.confirm_leave():
                return False
            try:
                p = project_from_midi(path)
            except (OSError, ValueError) as e:
                self.set_status(f"MIDI illisible : {e}")
                return False
            self.session.set_project(p)
            self.after_load()
            self.set_status(f"{path.name} : {len(p.tracks)} piste(s) importée(s)")
            return True
        if path.suffix.lower() in AUDIO_EXT:
            self.import_audio([str(path)])
            return True
        return super().open_other(path)

    def import_midi_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importer un fichier MIDI", "", "MIDI (*.mid *.midi)")
        if not path:
            return
        r = midi.read_smf(path)
        at = int(self.project.tempo_map().sample_to_tick(self.session.cursor))
        with self.project.edit("Importer MIDI", structure=True):
            for tr in r["tracks"]:
                t = Track(name=tr["name"] or Path(path).stem, kind="instrument",
                          instrument={"type": "drums"} if tr["channel"] == 9 else dict(INSTRUMENT_PRESETS["Piano électrique"]))
                end = max((n.tick + n.length for n in tr["notes"]), default=PPQ)
                t.midi_clips.append(MidiClip(name=t.name, start_tick=at, length_tick=-(-end // PPQ) * PPQ, notes=tr["notes"],
                                             controllers={str(k): v for k, v in tr["controllers"].items()}))
                self.project.tracks.append(t)
        self.set_status(f"{len(r['tracks'])} piste(s) MIDI importée(s)" + (f" ; {len(r['warnings'])} avertissement(s)" if r["warnings"] else ""))

    def export_midi(self) -> None:
        start = str(Path(self.project.path).with_suffix(".mid")) if self.project.path else self.project.name + ".mid"
        out, _ = QFileDialog.getSaveFileName(self, "Exporter en MIDI", start, "MIDI (*.mid)")
        if not out:
            return
        from fm_audio_engine.project import pattern_notes
        tracks = []
        for i, t in enumerate(self.project.tracks):
            if not t.midi_clips:
                continue
            notes = []
            for m in t.midi_clips:
                for n in pattern_notes(self.project, m):
                    if n.tick < m.length_tick:
                        notes.append(Note(m.start_tick + n.tick, min(n.length, m.length_tick - n.tick), max(0, min(127, n.pitch + m.transpose)), n.vel, n.mute))
            ch = 9 if (t.instrument or {}).get("type") == "drums" else i % 9
            tracks.append({"name": t.name, "channel": ch, "notes": notes})
        if Path(out).exists() and not self.confirm_overwrite(out):
            return
        midi.write_smf(out, tracks, self.project.tempo, self.project.signatures)
        self.set_status(f"MIDI exporté : {Path(out).name} ({len(tracks)} piste(s))")

    def confirm_overwrite(self, path) -> bool:
        from fm_sound_ui.ui_kit import confirm
        return confirm(self, "Remplacer le fichier", f"{Path(path).name} existe déjà. Le remplacer ?", "Remplacer")

    def import_audio(self, paths) -> None:
        with self.project.edit("Importer des sons", structure=True):
            t = Track(name=Path(paths[0]).stem)
            pos = self.session.cursor
            for path in paths:
                info = media.probe(path)
                c = Clip(path=str(path), name=Path(path).stem, start=pos,
                         length=max(1, int(round(info.frames * self.project.sample_rate / max(1, info.sample_rate)))))
                t.clips.append(c)
                pos = c.end
            self.project.tracks.append(t)

    # ---------------------------------------------------------------- pistes et clips
    def current(self) -> Track | None:
        return self.project.track(self.view.current_track) if self.view.current_track else None

    def add_instrument_track(self) -> None:
        m = menu(self)
        acts = {m.addAction(name): name for name in INSTRUMENT_PRESETS}
        chosen = m.exec(self.mapToGlobal(self.view.geometry().center()))
        if chosen not in acts:
            return
        name = acts[chosen]
        t = self.project.add_track(Track(name=name, kind="instrument", instrument=dict(INSTRUMENT_PRESETS[name])))
        self.view.current_track = t.id

    def add_audio_track(self) -> None:
        t = self.project.add_track(Track(name=f"Audio {len(self.project.tracks) + 1}", input=0, input_channels=1))
        self.view.current_track = t.id
        self.set_status(f"{t.name} : armer (R) puis Enreg. pour enregistrer directement dans FM Music")

    def add_clip(self) -> None:
        t = self.current()
        if t is None or t.kind != "instrument":
            self.set_status("Choisir une piste instrument (clic dans son en-tête)")
            return
        tm = self.project.tempo_map()
        tick = int(tm.sample_to_tick(self.session.cursor))
        bar = tm.bar_ticks(tick)
        tick = tick // bar * bar
        with self.project.edit("Nouveau clip MIDI", t.id):
            m = MidiClip(name=f"Clip {len(t.midi_clips) + 1}", start_tick=tick, length_tick=4 * bar)
            t.midi_clips.append(m)
        self.roll.set_clip(t.id, m.id)

    def edit_clip(self, track_id: str, clip_id: str) -> None:
        t = self.project.track(track_id)
        if t is not None and any(m.id == clip_id for m in t.midi_clips):
            self.roll.set_clip(track_id, clip_id)
            self.roll.setFocus()

    def pattern_menu(self) -> None:
        t, m = self.roll.clip()
        if m is None:
            self.set_status("Ouvrir d'abord un clip MIDI (double-clic)")
            return
        mm = menu(self)
        a_make = mm.addAction("Faire de ce clip un pattern") if not m.pattern else None
        a_copy = mm.addAction("Poser une instance du pattern après le clip") if m.pattern else None
        a_free = mm.addAction("Détacher (notes propres au clip)") if m.pattern else None
        chosen = mm.exec(self.mapToGlobal(self.view.geometry().center()))
        if chosen is None:
            return
        with self.project.edit("Pattern", structure=True):
            if chosen is a_make:
                pid = new_id("pat")
                self.project.patterns[pid] = {"name": m.name or "Pattern", "length_tick": m.length_tick, "notes": m.notes}
                m.notes, m.pattern = [], pid
            elif chosen is a_copy:
                n = MidiClip(name=m.name, start_tick=m.end_tick, length_tick=m.length_tick, pattern=m.pattern)
                t.midi_clips.append(n)
            elif chosen is a_free:
                from fm_audio_engine.project import pattern_notes
                m.notes = [Note.from_dict(x.to_dict()) for x in pattern_notes(self.project, m)]
                m.pattern = ""
        self.roll.update()

    def make_new_project(self) -> Project:
        return default_project(self._settings())

    def apply_settings(self, settings: dict) -> None:
        super().apply_settings(settings)
        roll = getattr(self, "roll", None)
        if roll is not None:
            roll.grid = grid_of(settings)
            roll.update()

    def quantize(self, undo: bool) -> None:
        notes = self.roll.notes()
        if not notes:
            return
        targets = [notes[i] for i in sorted(self.roll.sel)] or notes
        with self.roll.edit("Annuler la quantification" if undo else "Quantifier"):
            (midi.unquantize if undo else midi.quantize)(targets, *(() if undo else (self.roll.grid,)))

    def swing(self) -> None:
        v = ask_value(self, "Swing", "Swing en % (0 = droit, 100 = ternaire)",
                      str(self._settings().get("music_swing_default", 50)))
        if v:
            s = max(0.0, min(1.0, float(v.replace(",", ".")) / 100))
            notes = self.roll.notes()
            targets = [notes[i] for i in sorted(self.roll.sel)] or notes
            with self.roll.edit("Swing"):
                midi.quantize(targets, self.roll.grid, swing=s)

    def instrument_menu(self) -> None:
        t = self.current()
        if t is None or t.kind != "instrument":
            self.set_status("Choisir une piste instrument")
            return
        from fm_audio_engine import presets
        insts = presets.instruments()
        m = menu(self)
        acts = {m.addAction(name): name for name in insts}
        from fm_sound_ui import plugins_ui
        pacts = plugins_ui.add_library_menu(m, "instruments", self._settings())
        m.addSeparator()
        a_sample = m.addAction("Sampler : charger un son…")
        a_save = m.addAction("Enregistrer l'instrument comme préréglage…")
        eacts = plugins_ui.add_slot_actions(m, self.session)
        chosen = m.exec(self.mapToGlobal(self.view.geometry().center()))
        if chosen in eacts:
            plugins_ui.open_editor(self, *eacts[chosen][1])
            return
        if chosen in pacts:
            item = plugins_ui.handle_library_choice(self, pacts[chosen])
            if item:
                from fm_audio_engine import plugins
                with self.project.edit("Instrument plugin", t.id):
                    t.instrument = plugins.instrument_for(item)
                    t.name = item["name"] if t.name.startswith(("Synthé", "Piste", "Instrument")) else t.name
                self.set_status(f"{t.name} : {item['name']}")
            return
        if chosen is a_save and t.instrument:
            name = ask_value(self, "Préréglage", "Nom de l'instrument", t.name)
            if name:
                presets.save_instrument(name, t.instrument)
            return
        if chosen is a_sample:
            path, _ = QFileDialog.getOpenFileName(self, "Son du sampler", "", "WAV (*.wav)")
            if path:
                with self.project.edit("Sampler", t.id):
                    t.instrument = {"type": "sampler", "zones": [{"path": path, "root": 60, "lo": 0, "hi": 127}],
                                    "params": {"attack": 0.002, "release": 0.3}}
        elif chosen in acts:
            with self.project.edit("Instrument", t.id):
                t.instrument = dict(insts[acts[chosen]])
                t.name = acts[chosen] if t.name.startswith(("Synthé", "Piste", "Instrument")) else t.name
        self.set_status(f"{t.name} : {(t.instrument or {}).get('type', 'aucun')}")

    def set_tempo(self) -> None:
        tm = self.project.tempo_map()
        tick = int(tm.sample_to_tick(self.session.cursor)) // tm.bar_ticks(0) * tm.bar_ticks(0)
        v = ask_value(self, "Tempo", f"BPM à partir de la mesure {tm.bar_beat(tick)[0]}", f"{tm.bpm_at(tick):g}")
        if not v:
            return
        bpm = max(20.0, min(400.0, float(v.replace(",", "."))))
        with self.project.edit("Tempo", structure=True):
            pts = [p for p in self.project.tempo if int(p["tick"]) != tick]
            pts.append({"tick": tick, "bpm": bpm})
            self.project.tempo = sorted(pts, key=lambda p: p["tick"])
        self.set_status(f"Tempo {bpm:g} BPM à la mesure {tm.bar_beat(tick)[0]}")

    def set_signature(self) -> None:
        v = ask_value(self, "Signature", "Mesure, ex. 3/4 ou 7/8 (à partir du début)", "4/4")
        if not v or "/" not in v:
            return
        num, den = (int(x) for x in v.split("/"))
        with self.project.edit("Signature", structure=True):
            self.project.signatures = [{"tick": 0, "num": num, "den": den}]

    def add_section(self) -> None:
        tm = self.project.tempo_map()
        tick = int(tm.sample_to_tick(self.session.cursor))
        with self.project.edit("Section", structure=True):
            self.project.sections.append({"tick": tick, "name": f"Section {len(self.project.sections) + 1}"})
            self.project.sections.sort(key=lambda s: s["tick"])

    def midi_menu(self) -> None:
        if not self.session.ensure_device():
            return
        eng = self.session.engine
        try:
            devs = eng.request("midi_devices", timeout=30.0)
        except Exception as e:
            self.set_status(f"MIDI : {e}")
            return
        m = menu(self)
        acts = {}
        sub = m.addMenu("Entrée MIDI")
        for d in devs.get("inputs", []):
            acts[sub.addAction(d["name"])] = ("in", d["index"])
        if not devs.get("inputs"):
            sub.addAction("Aucun clavier MIDI détecté").setEnabled(False)
        sub = m.addMenu("Sortie MIDI (synthé externe)")
        for d in devs.get("outputs", []):
            acts[sub.addAction(d["name"])] = ("out", d["index"])
        t = self.current()
        if t is not None:
            acts[m.addAction(f"Jouer « {t.name} » au clavier")] = ("target", t.id)
            a = m.addAction("Notes de la piste vers la sortie MIDI")
            a.setCheckable(True)
            a.setChecked(bool(getattr(t, "midi_out", False) or (t.instrument or {}).get("midi_out")))
            acts[a] = ("track_out", t.id)
        acts[m.addAction("Fermer les ports MIDI")] = ("close",)
        what = acts.get(m.exec(self.mapToGlobal(self.view.geometry().center())))
        if not what:
            return
        ids = [x.id for x in self.project.tracks]
        try:
            if what[0] == "in":
                tgt = ids.index(self.view.current_track) if self.view.current_track in ids else 0
                eng.request("midi_open", inputs=[what[1]], target=tgt, timeout=10.0)
                self.set_status("Clavier MIDI ouvert")
            elif what[0] == "out":
                eng.request("midi_open", inputs=[], output=what[1], timeout=10.0)
            elif what[0] == "target":
                eng.request("midi_target", node=ids.index(what[1]))
            elif what[0] == "track_out":
                tr = self.project.track(what[1])
                with self.project.edit("Sortie MIDI de la piste", tr.id):
                    ins = dict(tr.instrument or {})
                    ins["midi_out"] = not ins.get("midi_out", False)
                    tr.instrument = ins
            elif what[0] == "close":
                eng.request("midi_close")
        except Exception as e:
            self.set_status(f"MIDI : {e}")

    def panic(self) -> None:
        if self.session.engine is not None and self.session.engine.alive():
            self.session.engine.request("panic")
        self.set_status("Toutes les notes coupées")


def project_from_midi(path) -> Project:
    r = midi.read_smf(path)
    p = Project("music", Path(path).stem)
    p.tempo, p.signatures = r["tempo"], r["signatures"]
    for tr in r["tracks"]:
        drums = tr["channel"] == 9
        t = Track(name=tr["name"] or ("Batterie" if drums else f"Piste {len(p.tracks) + 1}"), kind="instrument",
                  instrument={"type": "drums"} if drums else dict(INSTRUMENT_PRESETS["Piano électrique"]))
        end = max((n.tick + n.length for n in tr["notes"]), default=PPQ)
        t.midi_clips.append(MidiClip(name=t.name, start_tick=0, length_tick=-(-end // PPQ) * PPQ, notes=tr["notes"],
                                     controllers={str(k): v for k, v in tr["controllers"].items()}))
        p.tracks.append(t)
    p.history.mark_saved()
    return p
