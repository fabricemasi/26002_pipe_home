"""FM Audio / FM Music dans l'appli : cibles d'ouverture, réglages déclarés, panes construits
(Qt offscreen), ouverture d'un son, édition depuis la timeline, sauvegarde / réouverture,
piano roll, Échap qui n'en sort jamais, isolation des modules (aucun import croisé)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import ast
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from _window_cleanup import WindowTestCase, track  # noqa: E402
from _lent import lent  # noqa: E402

app = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parent.parent
SR = 48000


def key(widget, k, mods=Qt.NoModifier):
    widget.keyPressEvent(QKeyEvent(QEvent.KeyPress, k, mods))


def click(widget, x, y, mods=Qt.NoModifier):
    p = QPointF(x, y)
    widget.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p, p, Qt.LeftButton, Qt.LeftButton, mods))
    widget.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, p, p, Qt.LeftButton, Qt.NoButton, mods))


class ModuleWiringTest(unittest.TestCase):
    def test_targets_and_defaults(self):
        import settings_store
        from fm_audio.settings_defaults import AUDIO_DEFAULTS
        from main_window.module_targets import MODULES, OPENERS, module_targets
        for k, v in AUDIO_DEFAULTS.items():
            self.assertEqual(settings_store.DEFAULT_SETTINGS[k], v)
        self.assertIn("audio", module_targets(Path("x/prise.wav"), False))
        self.assertIn("audio", module_targets(Path("x/a.FLAC"), False))
        self.assertIn("audio", module_targets(Path("x/p.fmaudio"), False))
        self.assertIn("music", module_targets(Path("x/m.fmmusic"), False))
        self.assertIn("music", module_targets(Path("x/m.mid"), False))
        self.assertEqual(module_targets(Path("x/dossier.wav"), True), [])
        self.assertEqual(OPENERS["audio"], "_open_audio")
        self.assertEqual(MODULES["music"][0], "Ouvrir dans FM Music")

    def test_editors_never_import_each_other(self):
        for pkg, other in (("fm_audio", "fm_music"), ("fm_music", "fm_audio")):
            for f in (ROOT / pkg).glob("*.py"):
                tree = ast.parse(f.read_text("utf-8"))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    for n in names:
                        self.assertFalse(n == other or n.startswith(other + "."), f"{f.name} importe {n}")
        for f in list((ROOT / "fm_audio_engine").glob("*.py")):
            text = f.read_text("utf-8")
            self.assertNotIn("PySide6", text, f"{f.name} : le moteur et son modèle sont sans Qt")

    def test_main_window_mixin_present(self):
        import pipeline_browser
        cls = pipeline_browser.PipelineBrowser
        for name in ("_open_audio", "_open_music", "_leave_audio", "_sound_claims", "_close_sound_panes_for_exit"):
            self.assertTrue(hasattr(cls, name), name)


class PanesTest(WindowTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        os.environ["FMZ_AUDIO_CACHE"] = str(self.dir / "cache")
        from fm_audio_engine import wavio
        t = np.arange(SR) / SR
        self.wav = wavio.write(self.dir / "voix.wav", (0.3 * np.sin(2 * np.pi * 220 * t))[None, :].astype(np.float32), SR)

    def tearDown(self):
        os.environ.pop("FMZ_AUDIO_CACHE", None)
        self.tmp.cleanup()

    def test_audio_pane_open_edit_save_reopen(self):
        from fm_audio.pane import AudioPane
        pane = track(AudioPane(None, hooks={}))
        pane.resize(1200, 700)
        self.assertTrue(pane.open_path(self.wav))
        p = pane.project
        self.assertEqual(len(p.tracks), 1)
        self.assertEqual(p.tracks[0].clips[0].length, SR)
        v = pane.view
        v.resize(1000, 400)
        v.spp = SR / 800
        v.x0 = 0
        # sélection d'un clip (clic) puis scinder au curseur
        click(v, v.x_of(SR // 2), 60)
        self.assertEqual(len(v.sel_clips), 1)
        pane.session.seek(SR // 2)
        key(v, Qt.Key_S)
        self.assertEqual(len(p.tracks[0].clips), 2)
        key(v, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(len(p.tracks[0].clips), 1)
        # Échap : annule la sélection, le pane reste ouvert
        closed = []
        pane.closeRequested.connect(lambda: closed.append(1))
        key(v, Qt.Key_Escape)
        key(v, Qt.Key_Escape)
        self.assertEqual(closed, [])
        self.assertFalse(v.sel_clips)
        # sans Ctrl, glisser un clip ne le déplace pas (sélection temporelle à la place)
        start = p.tracks[0].clips[0].start
        pt0, pt1 = QPointF(v.x_of(SR // 4), 60), QPointF(v.x_of(SR // 4) + 100, 60)
        v.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pt0, pt0, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        v.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, pt1, pt1, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        v.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, pt1, pt1, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        self.assertEqual(p.tracks[0].clips[0].start, start)
        self.assertIsNotNone(v.sel)
        # enregistrer / rouvrir fidèlement
        out = pane.project.save(self.dir / "essai.fmaudio")
        pane2 = track(AudioPane(None, hooks={}))
        self.assertTrue(pane2.open_path(out))
        self.assertEqual(pane2.project.to_dict()["tracks"], p.to_dict()["tracks"])
        pane.shutdown()
        pane2.shutdown()

    def test_waveform_peaks_arrive_in_background(self):
        from fm_audio.pane import AudioPane
        pane = track(AudioPane(None, hooks={}))
        pane.open_path(self.wav)
        w = pane.session._worker
        if w is not None:
            w.join(10)
        app.processEvents()
        self.assertIn(str(self.wav), pane.session.peaks)
        pane.view.resize(900, 300)
        pane.view.grab()           # peinture complète sans erreur
        pane.shutdown()

    def test_music_pane_piano_roll(self):
        from fm_music.pane import MusicPane
        pane = track(MusicPane(None, hooks={}))
        pane.resize(1200, 800)
        p = pane.project
        self.assertEqual(p.kind, "music")
        self.assertTrue(any(t.instrument and t.instrument["type"] == "drums" for t in p.tracks))
        roll = pane.roll
        synth = next(t for t in p.tracks if t.instrument["type"] == "synth")
        roll.set_clip(synth.id, synth.midi_clips[0].id)
        roll.resize(900, 400)
        n0 = len(roll.notes())
        roll.top_pitch = 72
        roll.t0 = 0
        click(roll, roll.x_of(250) + 1, roll.y_of(60) + 2)      # case de grille [240, 480), do3
        self.assertEqual(len(roll.notes()), n0 + 1)
        new = roll.notes()[-1]
        self.assertEqual((new.tick, new.pitch), (240, 60))
        key(roll, Qt.Key_Q)
        self.assertEqual(new.tick, 240)
        key(roll, Qt.Key_Up)
        self.assertEqual(new.pitch, 61)
        key(roll, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(roll.notes()[-1].pitch, 60)
        key(roll, Qt.Key_Escape)
        self.assertFalse(roll.sel)
        roll.grab()
        pane.view.resize(900, 300)
        pane.view.grab()
        pane.shutdown()

    def test_mixer_fader_and_meters(self):
        from fm_audio.pane import AudioPane
        from fm_sound_ui.mixer import db_to_slider
        pane = track(AudioPane(None, hooks={}))
        pane.open_path(self.wav)
        tid = pane.project.tracks[0].id
        strip = pane.mixer.strips[tid]
        strip.fader.setValue(db_to_slider(-6.0))         # hors glisser : une étape d'annulation
        self.assertAlmostEqual(pane.project.track(tid).gain_db, -6.0, places=3)
        pane.project.history.undo()
        self.assertAlmostEqual(pane.project.track(tid).gain_db, 0.0, places=3)
        self.assertAlmostEqual(strip.fader.value(), db_to_slider(0.0))
        strip.mute.setChecked(True)
        self.assertTrue(pane.project.track(tid).mute)
        pane.show()
        pane.mixer.show()
        pane.mixer._meters({"meters": {tid: [0.5, 0.25, -3.0]}})
        self.assertAlmostEqual(strip.meter.level[0], 0.5)
        self.assertAlmostEqual(strip.meter.gr, -3.0)
        strip.meter.grab()
        pane.shutdown()

    def test_publish_from_editor_into_library(self):
        from fm_audio.pane import AudioPane
        from fm_audio_engine import library
        root = self.dir / "biblio"
        pane = track(AudioPane(None, hooks={"settings": lambda: {"audio_library_root": str(root)}}))
        pane.open_path(self.wav)
        t = pane.project.tracks[0]
        pane.view.sel_clips = {(t.id, t.clips[0].id)}
        pane.publish_selected()
        c = pane.project.tracks[0].clips[0]
        self.assertTrue(c.resource)
        self.assertEqual(c.revision, 1)
        self.assertTrue(c.path.startswith(str(root)))
        self.assertTrue(self.wav.exists())
        pane.publish_selected()                                   # republier = r2 de la même ressource
        self.assertEqual(pane.project.tracks[0].clips[0].revision, 2)
        self.assertEqual(library.Library(root).latest(c.resource), 2)
        pane.project.history.undo()
        self.assertEqual(pane.project.tracks[0].clips[0].revision, 1)
        pane.shutdown()

    def test_automation_lane_gestures(self):
        from fm_audio.pane import AudioPane
        from fm_audio_engine.project import compile_spec
        from fm_sound_ui import automation
        pane = track(AudioPane(None, hooks={}))
        pane.open_path(self.wav)
        v = pane.view
        v.resize(1000, 400)
        v.spp, v.x0 = SR / 800, 0
        t = pane.project.tracks[0]
        v.current_track = t.id
        key(v, Qt.Key_A)
        self.assertEqual(v.auto_target, "gain_db")
        r = v._lane_rect(v.track_y(0))
        click(v, v.x_of(SR // 4), r.top() + 2)                      # haut du couloir : +6 dB
        click(v, v.x_of(SR // 2), r.bottom() - 1)                   # bas : -60 dB
        pts = t.automation["gain_db"]["points"]
        self.assertEqual(len(pts), 2)
        self.assertGreater(pts[0][1], 3.0)                           # près du haut (+6 dB)
        self.assertLess(pts[1][1], -55.0)
        # Ctrl + glisser : déplace le point (sans Ctrl : un nouveau point serait ajouté ailleurs)
        x0, y0 = v.x_of(pts[1][0]), r.bottom() - 1
        p0, p1 = QPointF(x0, y0), QPointF(x0 + 80, r.center().y())
        QApplication.keyboardModifiers  # Ctrl lu au départ du geste
        v._g = None
        v._auto_press(t, x0, y0, QMouseEvent(QEvent.MouseButtonPress, p0, p0, Qt.LeftButton, Qt.LeftButton, Qt.ControlModifier), True)
        v.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p1, p1, Qt.NoButton, Qt.LeftButton, Qt.ControlModifier))
        v.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, p1, p1, Qt.LeftButton, Qt.NoButton, Qt.ControlModifier))
        pts = t.automation["gain_db"]["points"]
        self.assertEqual(len(pts), 2)
        self.assertGreater(pts[1][0], SR // 2)
        self.assertAlmostEqual(automation.value_at(pts, pts[1][0]), pts[1][1])
        # Alt + clic : supprime
        pa = QPointF(v.x_of(pts[0][0]), r.top() + 2)
        v._auto_press(t, pa.x(), pa.y(), QMouseEvent(QEvent.MouseButtonPress, pa, pa, Qt.LeftButton, Qt.LeftButton, Qt.AltModifier), False)
        self.assertEqual(len(t.automation["gain_db"]["points"]), 1)
        spec = compile_spec(pane.project)
        self.assertEqual(len(spec["tracks"][0]["automation"]["gain_db"]), 1)
        pane.project.history.undo()
        self.assertEqual(len(pane.project.tracks[0].automation["gain_db"]["points"]), 2)
        v.grab()
        pane.shutdown()

    def test_mixer_routing(self):
        from fm_audio_engine.project import Bus, Fx, Track, compile_spec
        from fm_sound_ui.mixer import route
        from fm_music.pane import MusicPane
        pane = track(MusicPane(None, hooks={}))
        p = pane.project
        with p.edit("bus", structure=True):
            p.buses += [Bus(id="b1", name="Rev"), Bus(id="b2", name="Grp", output="b1")]
        a, b = p.tracks[0], p.tracks[1]
        route(p, b.id, "output", "b2")
        route(p, b.id, "send", "b1", True)
        route(p, "b1", "output", "b2")                                  # b2 -> b1 -> b2 : cycle refusé
        with p.edit("fx", b.id):
            b.fx.append(Fx("compressor", {"ratio": 4}))
        route(p, b.id, "sidechain", 0, a.id)
        spec = compile_spec(p)
        tb = next(t for t in spec["tracks"] if t["id"] == b.id)
        self.assertEqual(tb["output"], "b2")
        self.assertEqual(tb["sends"], [{"target": "b1", "gain_db": -6.0, "pre": True}])
        self.assertEqual(tb["fx"][0]["sidechain"], a.id)
        self.assertEqual(p.bus("b1").output, "master")
        if __import__("fm_audio_engine.client", fromlist=["x"]).available()[0]:
            from fm_audio_engine import client
            client.render_offline(spec, self.dir / "route.wav", end=SR // 4, tail=0)   # graphe accepté par le moteur
        route(p, b.id, "unsend", 0)
        self.assertEqual(p.track(b.id).sends, [])
        p.history.undo()
        self.assertEqual(len(p.track(b.id).sends), 1)
        pane.shutdown()

    def test_midi_menu_targets(self):
        from fm_audio_engine import client
        from fm_audio_engine.project import compile_spec
        from fm_music.pane import MusicPane
        if not client.available()[0]:
            self.skipTest("moteur absent")
        pane = track(MusicPane(None, hooks={"settings": lambda: {"audio_output_device": "test"}}))
        t = pane.project.tracks[1]
        with pane.project.edit("x", t.id):
            t.instrument = dict(t.instrument, midi_out=True, midi_channel=3)
        tr = next(x for x in compile_spec(pane.project)["tracks"] if x["id"] == t.id)
        self.assertTrue(tr["midi_out"])
        self.assertEqual(tr["midi_channel"], 3)
        self.assertTrue(pane.session.ensure_device())                # périphérique de test (réglage)
        self.assertEqual(pane.session.engine.request("status")["backend"], "test")
        pane.session.engine.request("midi_target", node=1)
        pane.session.engine.request("midi_inject", status=0x90, d1=60, d2=100)
        pane.shutdown()
        client.shutdown_shared()

    def test_take_lanes_comp_by_drag(self):
        from fm_audio.pane import AudioPane
        from fm_audio_engine.project import Clip
        pane = track(AudioPane(None, hooks={}))
        pane.open_path(self.wav)
        t = pane.project.tracks[0]
        with pane.project.edit("prises", t.id):
            t.takes = [{"id": "k1", "name": "Prise 1", "clips": [Clip(path=str(self.wav), start=0, length=SR, take="k1")]},
                       {"id": "k2", "name": "Prise 2", "clips": [Clip(path=str(self.wav), start=0, length=SR, take="k2")]}]
        v = pane.view
        v.resize(1000, 300)
        v.spp, v.x0 = SR / 800, 0
        v.current_track = t.id
        pane.takes.show()
        lanes = pane.takes.lanes
        lanes._refresh()
        lanes.resize(1000, lanes.height())
        y = 44 + 20                                                     # deuxième couloir
        p0, p1 = QPointF(v.x_of(SR // 4), y), QPointF(v.x_of(SR // 2), y)
        lanes.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p0, p0, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        lanes.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p1, p1, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        lanes.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, p1, p1, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        comp = pane.project.track(t.id).comp
        self.assertEqual(len(comp), 1)
        self.assertEqual(comp[0]["take"], "k2")
        self.assertAlmostEqual(comp[0]["start"], SR // 4, delta=v.spp)
        lanes.grab()
        pane.takes.stack()
        self.assertEqual(len(pane.project.track(t.id).clips), 2)
        pane.shutdown()

    def test_spectrogram_view_tiles_and_selection(self):
        from fm_audio.pane import AudioPane
        pane = track(AudioPane(None, hooks={}))
        pane.open_path(self.wav)
        pane.session._worker and pane.session._worker.join(10)
        app.processEvents()
        v = pane.view
        v.resize(1000, 300)
        v.spp, v.x0 = SR / 800, 0
        v.current_track = pane.project.tracks[0].id
        pane.toggle_spectrogram()
        sp = pane.spectro
        sp.resize(1000, 200)
        sp.grab()                                                       # demande les tuiles visibles
        sp.wait_idle()
        app.processEvents()
        self.assertTrue(any(img is not None for img in sp.tiles.values()))
        sp.grab()
        p0, p1 = QPointF(v.x_of(SR // 4), sp.y_of(400)), QPointF(v.x_of(SR // 2), sp.y_of(100))
        sp.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p0, p0, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        sp.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p1, p1, Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
        t0, t1, f0, f1 = sp.sel
        self.assertAlmostEqual(f0, 100, delta=5)
        self.assertAlmostEqual(f1, 400, delta=15)
        self.assertLess(t0, t1)
        key(sp, Qt.Key_Escape)
        self.assertIsNone(sp.sel)
        pane.shutdown()

    def test_editors_work_without_engine(self):
        from pathlib import Path as P
        from unittest import mock
        from fm_audio.pane import AudioPane
        from fm_audio_engine import client
        with mock.patch.object(client, "ENGINE_EXE", P(self.dir) / "absent.exe"):
            ok, why = client.available()
            self.assertFalse(ok)
            self.assertIn("build.py", why)
            pane = track(AudioPane(None, hooks={}))
            self.assertTrue(pane.open_path(self.wav))                 # ouverture, waveform, édition : sans moteur
            pane.view.sel_clips = {(pane.project.tracks[0].id, pane.project.tracks[0].clips[0].id)}
            pane.session.seek(SR // 2)
            pane.view.cmd_split()
            self.assertEqual(len(pane.project.tracks[0].clips), 2)
            self.assertFalse(pane.session.play())                       # lecture : diagnostic clair, aucune erreur
            self.assertIn("build.py", pane.status.text())
            pane.shutdown()

    def test_midi_file_opens_in_music(self):
        from fm_audio_engine import midi
        from fm_audio_engine.project import Note
        from fm_music.pane import MusicPane
        mid = midi.write_smf(self.dir / "m.mid", [{"name": "Piano", "channel": 0, "notes": [Note(0, 480, 60, 100)]},
                                                 {"name": "Batt", "channel": 9, "notes": [Note(0, 120, 36, 100)]}])
        pane = track(MusicPane(None, hooks={}))
        self.assertTrue(pane.open_path(mid))
        kinds = [t.instrument["type"] for t in pane.project.tracks]
        self.assertEqual(kinds, ["synth", "drums"])
        pane.shutdown()


class ColumnCreateProjectTest(WindowTestCase):
    """Clic droit dans une colonne : « Créer un projet FM Audio / FM Music »."""

    def test_column_menu_creates_sound_projects(self):
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        from browser_core import ROLE_PATH
        from column_parts.file_operations import ColumnFileOperationsMixin
        from fm_audio_engine.project import Project
        import fm_audio
        import fm_music
        from main_window.module_targets import module_targets

        class _Column(ColumnFileOperationsMixin):
            pass
        with tempfile.TemporaryDirectory() as d:
            column = _Column()
            column.directory = Path(d)
            column.list = track(QListWidget())

            def refresh():
                column.list.clear()
                for p in sorted(Path(d).iterdir()):
                    item = QListWidgetItem(p.name)
                    item.setData(ROLE_PATH, str(p))
                    column.list.addItem(item)
            column.refresh = refresh
            a = column._create_sound_project("audio", "Prise voix")
            self.assertEqual(a, Path(d) / "Prise voix.fmaudio")
            self.assertEqual(column.list.currentItem().data(ROLE_PATH), str(a))
            pa = Project.load(a)
            self.assertEqual((pa.kind, pa.name, pa.tracks), ("audio", "Prise voix", []))
            m = column._create_sound_project("music", "Morceau.fmmusic")     # extension tapée : pas doublée
            self.assertEqual(m, Path(d) / "Morceau.fmmusic")
            pm = Project.load(m)
            self.assertEqual((pm.kind, pm.name, len(pm.tracks)), ("music", "Morceau", 2))
            self.assertTrue(fm_audio.opens(a) and fm_music.opens(m))
            self.assertIn("audio", module_targets(a, False))
            self.assertIn("music", module_targets(m, False))
            self.assertIsNone(column._create_sound_project("audio", "  "))       # nom vide : rien


class NavFrameTest(WindowTestCase):
    """Bouton de la barre et cadre d'outils : icônes du catalogue (bibliothèque hors dépôt) résolues et peintes,
    couleur de module déclarée, réglages des projets neufs, doublons de l'éditeur masqués quand le cadre de la
    barre porte les outils, état du transport signalé au CHANGEMENT seulement."""

    def test_catalog_icons_resolve_and_paint(self):
        from config import ICON_LIBRARY_ROOT
        from fm_theme import icon_library
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QImage, QPainter
        from browser_core_parts.settings import MODULE_ICON_COLOR_KEYS
        from preview_column import NAV_LIBRARY_ICONS
        import settings_store
        if not Path(ICON_LIBRARY_ROOT).exists():
            self.skipTest("bibliothèque d'icônes absente de ce poste")
        icon_library.configure(ICON_LIBRARY_ROOT)
        kinds = ("audio", "music", "sound_play", "sound_record", "sound_loop", "sound_metronome", "sound_mixer")
        for kind in kinds:
            ident = NAV_LIBRARY_ICONS[kind]
            for style in (icon_library.COULEUR, icon_library.MONOCHROME):
                self.assertTrue(icon_library.chemin(ident, style), (ident, style))
                img = QImage(32, 32, QImage.Format_ARGB32_Premultiplied)
                img.fill(0)
                p = QPainter(img)
                ok = icon_library.peindre(p, QRectF(0, 0, 32, 32), ident, style=style)
                p.end()
                self.assertTrue(ok, (ident, style))
                self.assertTrue(any(img.pixelColor(x, y).alpha() for x in range(32) for y in range(32)), ident)
        for module in ("audio", "music"):
            self.assertIn(MODULE_ICON_COLOR_KEYS[module], settings_store.DEFAULT_SETTINGS)

    def test_new_project_settings(self):
        from fm_music.pane import default_project, grid_of
        from fm_sound_ui.editor_base import new_sample_rate
        p = default_project({"music_new_tempo": 90, "music_new_signature": "6/8", "music_new_demo": False,
                             "audio_new_sample_rate": 44100})
        self.assertEqual((p.sample_rate, p.tempo[0]["bpm"], p.signatures[0]["num"], p.signatures[0]["den"]), (44100, 90.0, 6, 8))
        self.assertEqual([t.kind for t in p.tracks], ["instrument"])
        self.assertEqual(len(default_project({}).tracks), 2)                       # batterie + basse de départ
        self.assertEqual((grid_of({"music_grid": 480}), grid_of({"music_grid": 7})), (480, 240))
        self.assertEqual((new_sample_rate({"audio_new_sample_rate": 96000}), new_sample_rate({"audio_new_sample_rate": 12})), (96000, 48000))

    def test_navbar_frame_hides_duplicates_and_reports_transport(self):
        from fm_audio.pane import AudioPane
        pane = track(AudioPane(None, hooks={"navbar_frame": True, "settings": lambda: {"audio_new_sample_rate": 44100}}))
        self.assertEqual(pane.project.sample_rate, 44100)
        for b in (pane.btn_undo, pane.btn_redo, pane.btn_play, pane.btn_rec, pane.btn_loop, pane.btn_metro,
                  pane.btn_mixer, pane.btn_settings, pane.btn_close):
            self.assertTrue(b.isHidden())
        seen = []
        pane.transportChanged.connect(lambda: seen.append(pane.transport_state()))
        pane.toggle_loop()
        self.assertTrue(seen[-1]["loop"])
        n = len(seen)
        pane._emit_transport()                                                     # rien n'a changé : silence
        self.assertEqual(len(seen), n)
        pane.flip_metronome()
        self.assertTrue(seen[-1]["metronome"])
        plain = track(AudioPane(None, hooks={}))
        self.assertFalse(plain.btn_play.isHidden())                                # sans cadre : la barre garde ses outils


@lent
class NavbarAppTest(unittest.TestCase):
    """PIPE FMZ COMPLET (lent) : boutons FM Audio / FM Music de la barre, cadre de chaque module, bascule entre les
    deux, fermeture par le bouton."""

    def test_buttons_and_frames(self):
        import time
        from settings_store import load_settings
        import pipeline_browser as pb
        pb.apply_all_settings(load_settings())

        def pump(s):
            end = time.perf_counter() + s
            while time.perf_counter() < end:
                app.processEvents()
                time.sleep(0.005)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "racine"
            (root / "26001_Essai").mkdir(parents=True)
            win = pb.PipelineBrowser(root)
            win.resize(1700, 900)
            win.show()
            pump(0.4)
            try:
                self.assertTrue(win.btn_audio.isEnabled() and win.btn_music.isEnabled())
                win.btn_audio.click()
                pump(0.3)
                self.assertTrue(win._audio_pane.isVisible())
                self.assertFalse(win.titlebar.audio_group().isHidden())
                self.assertEqual(len(win._audio_frame_buttons), 9)
                win.btn_music.click()
                pump(0.3)
                self.assertTrue(win._music_pane.isVisible())
                self.assertTrue(win.titlebar.audio_group().isHidden())
                self.assertFalse(win.titlebar.music_group().isHidden())
                win._music_pane.project.history.mark_saved()
                win.btn_music.click()
                pump(0.3)
                self.assertTrue(win.titlebar.music_group().isHidden())
            finally:
                win.close()
                pump(0.2)


if __name__ == "__main__":
    unittest.main()
