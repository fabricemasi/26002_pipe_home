"""Module vidéo, lecture et ergonomie : moteur LibVLC (images exactes à la pause, lectures répétées sans perte du
son, volume), lecture automatique, zoom initial intelligent, YUV -> RVB du shader, timeline en secondes, curseurs
« modifiés » (contour orange, double-clic = valeur d'origine), dossier d'export, RIFE.

Vidéos générées par FFmpeg : l'image n est un gris connu (4 n). Rien n'est écrit dans les vrais réglages."""
import _isolate  # noqa: F401
from _lent import lent  # noqa: E402

import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication(sys.argv)

try:
    import av  # noqa: F401
    HAS_AV = True
except Exception:                          # noqa: BLE001
    HAS_AV = False
FFMPEG = shutil.which("ffmpeg")
try:
    from fm_video import vlc_engine
    HAS_VLC = vlc_engine.available()
except Exception:                          # noqa: BLE001
    HAS_VLC = False

W, H, N = 160, 96, 60


def make_video(path: Path, fps: int = 24, count: int = N, size=(W, H), audio=True):
    w, h = size
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r",
           str(fps), "-i", "-"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={count / fps + 0.2}"]
    cmd += ["-c:v", "libx264", "-bf", "3", "-g", "30", "-pix_fmt", "yuv420p"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    proc = subprocess.Popen(cmd + [str(path)], stdin=subprocess.PIPE)
    for i in range(count):
        proc.stdin.write(np.full((h, w), (i * 4) % 240, np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()


def pump(seconds: float):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        APP.processEvents()
        time.sleep(0.002)


def wait(cond, timeout=10.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.003)
    return False


def gray_of(frame) -> float:
    return float(frame.pixels.mean()) / 4.0


class _PaneCase(unittest.TestCase):
    video = None

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="vplay_"))
        cls.video = cls.dir / "clip.mp4"
        make_video(cls.video)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def make_pane(self, **settings):
        from settings_store import DEFAULT_SETTINGS
        from fm_video.pane import VideoPane
        self.host = QWidget()
        self.host.resize(900, 600)
        values = dict(DEFAULT_SETTINGS, video_backend="cpu", video_volume=0)
        values.update(settings)
        self.pane = VideoPane(self.host, values)
        self.host.show()
        return self.pane

    def tearDown(self):
        pane = getattr(self, "pane", None)
        if pane is not None:
            pane.shutdown()
            pane.deleteLater()
            self.host.deleteLater()
            APP.processEvents()


@unittest.skipUnless(HAS_AV and FFMPEG and HAS_VLC, "PyAV / FFmpeg / VLC absents")
class VlcEngineTest(_PaneCase):
    def test_autoplay_uses_vlc_and_pause_shows_the_exact_frame(self):
        pane = self.make_pane(video_autoplay=True, video_loop=False)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertEqual(pane._engine, "vlc")
        self.assertTrue(wait(lambda: pane._playing and pane._vlc.displayed > 5, 8), "lecture automatique")
        self.assertTrue(wait(lambda: pane.index >= 10, 5))
        pane.pause()
        self.assertTrue(wait(lambda: pane._shown == pane.index and pane.viewer.frame.yuv is not None
                             and pane.viewer.frame.index == pane.index, 5))
        self.assertAlmostEqual(gray_of(pane.viewer.frame), pane.index, delta=0.6)
        # Pas à pas depuis la pause : exact, dans les deux sens.
        for delta in (1, 1, -1, -1, -1):
            target = pane.index + delta
            pane.step(delta)
            self.assertTrue(wait(lambda t=target: pane._shown == t, 5))
            self.assertAlmostEqual(gray_of(pane.viewer.frame), target, delta=0.6)

    def test_loop_started_near_the_end_restarts_at_the_beginning(self):
        # `:input-repeat` de VLC rejoue depuis le point de départ : lancé à la fin, il tournait sans rien montrer.
        pane = self.make_pane(video_autoplay=False, video_loop=True)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        last = pane.source.frame_count - 1
        pane.go(last - 6)
        self.assertTrue(wait(lambda: pane._shown == last - 6, 5))
        pane.play()
        self.assertTrue(wait(lambda: pane._playing and 0 <= pane.index < last // 2, 8), pane.index)
        seen = pane._vlc.displayed
        pump(0.5)
        self.assertGreater(pane._vlc.displayed, seen)                   # elle continue
        pane.pause()
        pane.go(last)
        self.assertTrue(wait(lambda: pane._shown == last, 5))
        pane.play()                                                      # depuis la dernière image : repart au début
        self.assertTrue(wait(lambda: pane._playing and pane._vlc.displayed > seen + 5 and pane.index < last // 2, 8))

    def test_no_autoplay_opens_paused_on_the_first_frame(self):
        pane = self.make_pane(video_autoplay=False)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        pump(0.5)
        self.assertFalse(pane._playing)
        self.assertEqual(pane._vlc.displayed, 0)

    @lent
    def test_twenty_plays_keep_the_sound(self):
        """Cause du bug « plus de son à partir de la 3e lecture » : après la fin du média, LibVLC refuse play() ;
        chaque lecture repart d'un lecteur arrêté, volume / muet reposés quand la sortie audio est créée."""
        pane = self.make_pane(video_autoplay=False, video_loop=False, video_volume=35)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        checked = 0
        for n in range(20):
            pane.go(N - 12 if n % 2 else 0)
            pane.play()
            if n % 2:                                       # jusqu'à la fin du média
                self.assertTrue(wait(lambda: not pane._playing, 8), f"fin de la lecture {n + 1}")
            else:
                self.assertTrue(wait(lambda: pane._vlc.displayed and pane.index > 3, 8), f"lecture {n + 1}")
            player = pane._vlc.player
            if pane._playing:                               # sortie audio vivante : piste, volume, pas muet
                self.assertTrue(wait(lambda: player.audio_get_track() > 0, 3), f"piste audio, lecture {n + 1}")
                self.assertTrue(wait(lambda: player.audio_get_volume() == 35, 3), f"volume, lecture {n + 1}")
                self.assertEqual(player.audio_get_mute(), 0)
                checked += 1
            pane.pause()
        self.assertGreaterEqual(checked, 10)
        self.assertTrue(wait(lambda: pane._shown == pane.index, 5))

    def test_volume_label_and_mute_follow_one_value(self):
        pane = self.make_pane(video_autoplay=False, video_volume=80)
        self.assertTrue(pane.open(self.video))
        self.assertEqual(pane.volume_label.text(), "80 %")
        pane.volume.setValue(25)
        self.assertEqual(pane.volume_label.text(), "25 %")
        self.assertEqual(pane._vlc.volume, 25)
        pane._toggle_mute()
        self.assertTrue(pane._vlc.muted)
        self.assertEqual(pane.volume_label.text(), "25 %")
        pane._toggle_mute()
        self.assertFalse(pane._vlc.muted)
        self.assertEqual(pane._vlc.volume, 25)
        # Autre fichier : même volume.
        self.assertTrue(pane.open(self.video))
        self.assertEqual(pane._vlc.volume, 25)
        self.assertEqual(pane.volume_label.text(), "25 %")


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class ZoomAndColorTest(_PaneCase):
    def test_smart_zoom_keeps_small_images_at_100_and_fits_large_ones(self):
        from fm_video.viewer import CPUViewer
        viewer = CPUViewer()
        viewer.resize(800, 500)
        viewer.smart()
        viewer.set_image_size(320, 240)
        self.assertEqual(viewer.zoom(), 1.0)
        viewer.set_image_size(3840, 2160)
        dpr = viewer.devicePixelRatioF() or 1.0
        self.assertAlmostEqual(viewer.zoom(), min(800 * dpr / 3840, 500 * dpr / 2160), places=4)
        viewer.fit()
        viewer.set_image_size(320, 240)
        self.assertGreater(viewer.zoom(), 1.0)              # « toujours ajuster » agrandit
        viewer.deleteLater()

    def test_image_rect_is_snapped_to_physical_pixels(self):
        from fm_video.viewer import CPUViewer
        viewer = CPUViewer()
        viewer.resize(801, 501)
        viewer.set_image_size(320, 241)
        viewer.one_to_one()
        rect = viewer.image_rect()
        dpr = viewer.devicePixelRatioF() or 1.0
        self.assertAlmostEqual(rect.left() * dpr, round(rect.left() * dpr), places=6)
        self.assertAlmostEqual(rect.top() * dpr, round(rect.top() * dpr), places=6)
        viewer.deleteLater()

    def test_yuv_conversion_matches_ffmpeg(self):
        """Conversion YUV -> RVB du module (celle du shader) = celle de FFmpeg (matrice BT.709 / 601, plage)."""
        from fm_video import media as vmedia
        for size, matrix in (((1280, 720), "bt709"), ((640, 480), "bt470bg")):
            path = self.dir / f"bars_{size[0]}.mp4"
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"testsrc2=size={size[0]}x{size[1]}:rate=24:duration=0.2", "-vf",
                            f"scale=out_color_matrix={matrix}:out_range=tv", "-colorspace", matrix,
                            "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", str(path)], check=True)
            src = vmedia.open_media(path)
            ours = src.read(2, yuv=True).yuv.to_rgb().astype(np.float32)
            ref = src.read(2, yuv=False).pixels.astype(np.float32)
            self.assertLess(float(np.abs(ours - ref).mean()), 1.5, size)
            src.close()

    def test_initial_zoom_setting(self):
        pane = self.make_pane(video_autoplay=False, video_default_zoom="smart", video_engine="pyav")
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        self.assertEqual(pane.viewer.zoom_mode(), "smart")
        self.assertEqual(pane.viewer.zoom(), 1.0)          # 160 x 96 dans 900 x 600 : 100 %, pas agrandie


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class TimelineSecondsTest(_PaneCase):
    def test_seconds_unit_changes_only_the_display(self):
        pane = self.make_pane(video_autoplay=False, video_engine="pyav")
        self.assertTrue(pane.open(self.video))
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        pane.go(30)
        self.assertTrue(wait(lambda: pane._shown == 30, 5))
        self.assertEqual(pane.timeline.label(30), "30")
        pane.unit_select.setValue("Secondes")
        pane._unit_chosen("Secondes")
        self.assertEqual(pane.timeline.label(30), "00:01.250")             # 30 / 24
        self.assertEqual(pane.index, 30)
        self.assertEqual(pane.timeline.current, 30)
        pane.timeline.repaint()                                            # graduations en secondes : pas d'erreur

    def test_fractional_rate_has_no_drift(self):
        from fm_video.timeline import Timeline
        timeline = Timeline()
        timeline.set_media(100000, 0, Fraction(24000, 1001))
        fps = Fraction(24000, 1001)
        timeline.set_time_mapping(lambda i: float(i / fps), lambda t: float(t) * float(fps))
        timeline.set_look({"seconds": True})
        self.assertEqual(timeline.label(86314), "1:00:00.013")            # 86314 × 1001 / 24000 = 3600,0131 s
        self.assertEqual(timeline.label(1), "00:00.042")                  # 1001 / 24000 = 0,0417 s


class SliderResetTest(unittest.TestCase):
    def test_modified_value_is_marked_and_double_click_on_the_knob_resets(self):
        from settings_store import M
        from settings_widgets import _SliderField
        field = _SliderField(20, 500, 100, unit="", scale=100)
        field.set_reset_value(100)
        field.resize(300, 30)
        field.show()
        APP.processEvents()
        self.assertNotIn(M["dirty_fg"], field.box.styleSheet())
        field.setValue(130)
        self.assertIn(M["dirty_fg"], field.box.styleSheet())
        slider = field.slider
        x = round(slider._pct() * slider.width())
        pos = QPointF(x, slider.height() / 2)
        event = QMouseEvent(QEvent.MouseButtonDblClick, pos, slider.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton,
                            Qt.NoModifier)
        QApplication.sendEvent(slider, event)
        self.assertEqual(field.value(), 100)
        self.assertNotIn(M["dirty_fg"], field.box.styleSheet())
        field.value_label.setText("1,30")                  # saisie numérique : même contour
        field._on_text_edited()
        self.assertEqual(field.value(), 130)
        self.assertIn(M["dirty_fg"], field.box.styleSheet())
        field.deleteLater()


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class ExportFolderTest(_PaneCase):
    def test_missing_folder_is_refused_and_the_last_folder_is_remembered(self):
        from fm_video import pane as vpane
        saved = {}
        old = vpane.HOOKS.get("save_state")
        vpane.HOOKS["save_state"] = lambda k, v: saved.__setitem__(k, v)
        try:
            pane = self.make_pane(video_autoplay=False, video_engine="pyav")
            self.assertTrue(pane.open(self.video))
            window = pane.open_export_window()
            window.dir_field.setText(str(self.dir / "absent"))
            self.assertIsNone(window.build_settings())
            self.assertIn("introuvable", window.progress.text())
            window.dir_field.setText(str(self.dir))
            window._remember({"x_dir": str(self.dir)})
            self.assertIsNotNone(window.build_settings())
            self.assertEqual(saved["video_export_last"]["x_dir"], str(self.dir))
            window.close()
        finally:
            vpane.HOOKS["save_state"] = old


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class RifeTest(unittest.TestCase):
    def test_rife_doubles_the_rate_keeping_the_duration(self):
        from fm_video import export as vexport
        from fm_video import media as vmedia
        exe = vexport.rife_path("")
        if not exe:
            self.skipTest("rife-ncnn-vulkan absent")
        folder = Path(tempfile.mkdtemp(prefix="rife_"))
        try:
            clip = folder / "clip.mp4"
            make_video(clip, fps=12, count=12, size=(128, 96), audio=False)
            out = folder / "rife.mp4"
            job = vexport.ExportJob(vmedia.open_media(clip), vexport.ExportSettings(
                output=out, fmt="mp4", codec="h264", fps=Fraction(24), fps_mode="interpolate", interp="rife",
                range=(0, 11), overwrite=True, content="data"))
            result = {}
            job.finished.connect(lambda ok, msg, path: result.update(ok=ok, msg=msg))
            job.start()
            self.assertTrue(wait(lambda: bool(result), 120), "RIFE trop long")
            self.assertTrue(result["ok"], result.get("msg"))
            done = vmedia.open_media(out)
            done.build_index()
            self.assertEqual(done.frame_count, 24)
            # Image intermédiaire entre les rangs 2 et 3 de la source (gris 8 et 12) : un gris entre les deux.
            middle = gray_of(done.read(5)) * 4
            self.assertTrue(8 <= middle <= 12, middle)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class ScopesTest(unittest.TestCase):
    def test_histogram_waveform_and_vectorscope(self):
        from fm_video import scopes
        rgb = np.zeros((20, 40, 3), np.float32)
        rgb[:, :20] = (1.0, 0.0, 0.0)                     # moitié rouge pur, moitié gris moyen
        rgb[:, 20:] = 0.5
        r = scopes.compute(rgb)
        self.assertEqual(int(r["hist"][0][255]), 400)
        self.assertEqual(int(r["hist"][3][128]), 400)          # luma du gris
        self.assertEqual(int(r["wave"].sum()), 800)
        self.assertEqual(int(r["wave"][:, 30].sum()), 20)
        self.assertGreater(int(r["vec"][127:130, 127:130].sum()), 0)   # gris : au centre
        self.assertEqual(int(r["vec"].sum()), 800)

    @unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
    def test_small_rgb_of_a_yuv_frame(self):
        from fm_video import media as vmedia
        from fm_video import scopes
        folder = Path(tempfile.mkdtemp(prefix="scopes_"))
        try:
            clip = folder / "c.mp4"
            make_video(clip, count=5, size=(1280, 720), audio=False)
            frame = vmedia.open_media(clip).read(3, yuv=True)
            rgb, _alpha = scopes.small_rgb(frame)
            self.assertLessEqual(rgb.shape[1], scopes.MAX_W)
            self.assertAlmostEqual(float(rgb.mean()) * 255, 12, delta=1.5)   # gris de l'image 3
        finally:
            shutil.rmtree(folder, ignore_errors=True)


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class ViewerInteractionTest(_PaneCase):
    def _press_move_release(self, viewer, start, end=None, button=Qt.LeftButton):
        from PySide6.QtTest import QTest
        QTest.mousePress(viewer, button, Qt.NoModifier, start)
        if end is not None:
            for k in range(1, 11):
                QTest.mouseMove(viewer, start + (end - start) * k / 10)
        QTest.mouseRelease(viewer, button, Qt.NoModifier, end or start)
        APP.processEvents()

    def test_pan_works_on_a_smaller_image_and_recenter_keeps_the_zoom(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        pane = self.make_pane(video_autoplay=False, video_default_zoom="smart")
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        viewer = pane.viewer
        viewer.set_zoom(0.25)                                   # image bien plus petite que la zone
        pump(0.1)
        before = viewer.image_rect()
        self.assertLess(before.width(), viewer.width())
        centre = before.center().toPoint()
        self._press_move_release(viewer, centre, centre + QPoint(120, -60))
        moved = viewer.image_rect()
        self.assertAlmostEqual(moved.left() - before.left(), 120, delta=2)
        self.assertAlmostEqual(moved.top() - before.top(), -60, delta=2)
        self.assertFalse(pane._playing)                          # un déplacement n'est pas un clic
        self.assertEqual(pane.index, 0)
        # Redimensionnement : le déplacement choisi reste.
        self.host.resize(950, 620); pump(0.2)
        self.assertNotAlmostEqual(viewer.image_rect().center().x(), viewer.width() / 2, delta=20)
        # Jamais hors de la zone.
        self._press_move_release(viewer, viewer.image_rect().center().toPoint(), QPoint(-5000, -5000))
        rect = viewer.image_rect()
        self.assertGreaterEqual(rect.right(), min(viewer.KEEP_VISIBLE, rect.width()) - 2)
        self.assertGreaterEqual(rect.bottom(), min(viewer.KEEP_VISIBLE, rect.height()) - 2)
        # Recentrer : centre de la zone, zoom inchangé, image inchangée.
        zoom = viewer.zoom()
        pane.buttons["center"].clicked.emit()
        pump(0.05)
        rect = viewer.image_rect()
        self.assertAlmostEqual(rect.center().x(), viewer.width() / 2, delta=1)
        self.assertAlmostEqual(rect.center().y(), viewer.height() / 2, delta=1)
        self.assertEqual(viewer.zoom(), zoom)
        self.assertEqual(pane.index, 0)
        viewer._pan = QPointF(90, -40)
        viewer._changed()
        QTest.mouseClick(viewer, Qt.MiddleButton, Qt.NoModifier, viewer.rect().center())
        self.assertAlmostEqual(viewer.image_rect().center().x(), viewer.width() / 2 + 90, delta=1)
        self.assertEqual(viewer.zoom(), zoom)
        viewer._pan = QPointF(-70, 35)
        viewer._changed()
        QTest.mouseClick(viewer, Qt.MiddleButton, Qt.ShiftModifier, viewer.rect().center())
        self.assertAlmostEqual(viewer.image_rect().center().x(), viewer.width() / 2, delta=1)
        self.assertAlmostEqual(viewer.image_rect().center().y(), viewer.height() / 2, delta=1)
        self.assertEqual(viewer.zoom(), 1.0)
        # Image agrandie : déplacement aussi, au-delà des extrémités.
        viewer.set_zoom(3.0); pump(0.05)
        c = QPoint(viewer.width() // 2, viewer.height() // 2)
        before = viewer.image_rect()
        self._press_move_release(viewer, c, c + QPoint(80, 40))
        self.assertAlmostEqual(viewer.image_rect().left() - before.left(), 80, delta=2)
        viewer.set_image_size(1920, 1080)
        viewer.set_zoom(2.0)
        pan = QPointF(1920, 1080)
        viewer._pan = QPointF(pan)
        viewer._clamp_pan()
        self.assertEqual(viewer._pan, pan)                       # plus de blocage pour couvrir la zone

    def test_click_on_the_image_toggles_playback_double_click_stays_fullscreen(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        pane = self.make_pane(video_autoplay=False, video_loop=True)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        viewer = pane.viewer
        viewer.set_zoom(0.3); pump(0.05)
        on_image = viewer.image_rect().center().toPoint()
        self._press_move_release(viewer, on_image)
        self.assertTrue(pane._playing)
        pump(0.3)
        self._press_move_release(viewer, on_image)
        self.assertFalse(pane._playing)
        # À côté de l'image : rien.
        self._press_move_release(viewer, QPoint(3, 3))
        self.assertFalse(pane._playing)
        # Double-clic : plein écran, l'état de lecture ne change pas au bout du compte.
        self._press_move_release(viewer, on_image)
        QTest.mouseDClick(viewer, Qt.LeftButton, Qt.NoModifier, on_image)
        pump(0.3)
        self.assertTrue(pane.is_fullscreen())
        self.assertFalse(pane._playing)
        pane.toggle_fullscreen(); pump(0.3)


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class SnapshotTest(_PaneCase):
    def test_full_frame_and_zone_captures_are_numbered_in_the_film_folder(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QImage
        from PySide6.QtTest import QTest
        pane = self.make_pane(video_autoplay=False)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        pane.go(12)
        self.assertTrue(wait(lambda: pane._shown == 12, 5))
        folder = self.video.parent / self.video.stem
        shutil.rmtree(folder, ignore_errors=True)
        # Image entière, deux fois : _001 puis _002, pleine définition, gris de l'image 12.
        for _ in range(2):
            done = pane.last_snapshot
            pane.buttons["shot"].clicked.emit()
            self.assertTrue(wait(lambda: pane.last_snapshot != done, 10))
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["clip_001.png", "clip_002.png"])
        image = QImage(str(folder / "clip_001.png"))
        self.assertEqual((image.width(), image.height()), (pane.source.width, pane.source.height))
        # Couleurs TELLES QU'AFFICHÉES : même calcul que l'afficheur (OCIO, corrections).
        from fm_video import color as vcolor
        cy, cx = image.height() // 2, image.width() // 2
        shown, _a = vcolor.process_np(pane.viewer.frame.pixels[cy:cy + 1, cx:cx + 1], pane._pipeline,
                                      pane.view_state())
        self.assertAlmostEqual(QColor(image.pixel(cx, cy)).red(), float(shown[0, 0, 0]) * 255, delta=2)
        # Zone : bouton, rectangle tracé sur l'image (pas de lecture), fichier z_crop_clip_001.png à la taille tracée.
        viewer = pane.viewer
        pane.buttons["zone"].clicked.emit()
        self.assertTrue(viewer.region_mode())
        rect = viewer.image_rect()
        a = QPoint(int(rect.left() + rect.width() * 0.25), int(rect.top() + rect.height() * 0.25))
        b = QPoint(int(rect.left() + rect.width() * 0.75), int(rect.top() + rect.height() * 0.75))
        QTest.mousePress(viewer, Qt.LeftButton, Qt.NoModifier, a)
        QTest.mouseMove(viewer, b)
        QTest.mouseRelease(viewer, Qt.LeftButton, Qt.NoModifier, b)
        self.assertFalse(viewer.region_mode())
        self.assertFalse(pane._playing)
        self.assertTrue(wait(lambda: (folder / "z_crop_clip_001.png").exists(), 10))
        zone = QImage(str(folder / "z_crop_clip_001.png"))
        self.assertAlmostEqual(zone.width(), pane.source.width / 2, delta=3)
        self.assertAlmostEqual(zone.height(), pane.source.height / 2, delta=3)
        # Échap annule le tracé.
        pane.buttons["zone"].clicked.emit()
        QTest.keyClick(viewer, Qt.Key_Escape)
        self.assertFalse(viewer.region_mode())
        self.assertFalse(pane.buttons["zone"].checked)
        shutil.rmtree(folder, ignore_errors=True)

    def test_moodboard_capture_saves_the_entire_grid_with_prefix(self):
        from unittest.mock import patch
        from PySide6.QtGui import QImage
        pane = self.make_pane(video_autoplay=False)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        pane.toggle_moodboard()
        self.assertTrue(wait(lambda: bool(pane.moodboard.pixmaps), 10))
        pane.moodboard.set_zoom(2.0)
        folder = Path(tempfile.mkdtemp(prefix="moodshot_"))
        try:
            from fm_video import snapshot as vsnap
            with patch.object(vsnap, "snapshot_dir", return_value=folder):
                pane.take_snapshot()
            path = folder / "z_mood_clip_001.png"
            self.assertTrue(wait(lambda: path.exists(), 30), (list(folder.iterdir()), pane.last_snapshot,
                                                              pane._message))
            image = QImage(str(path))
            self.assertFalse(image.isNull())
            self.assertEqual((image.width(), image.height()),
                             (pane.moodboard.board_size().width() * 2,
                              pane.moodboard.board_size().height() * 2))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_sequence_folder_is_named_after_the_sequence(self):
        from fm_video import snapshot as vsnap
        from fm_video import media as vmedia
        seq = vmedia.Sequence(Path("D:/shot"), "beauty.", ".exr", 4, [1001, 1002])
        source = type("S", (), {"sequence": seq, "path": Path("D:/shot/beauty.1001.exr")})()
        self.assertEqual(vsnap.media_name(source), "beauty")
        self.assertEqual(vsnap.snapshot_dir(source), Path("D:/shot/beauty"))


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class BeforeAfterTest(_PaneCase):
    def test_each_grade_window_bypasses_only_its_own_corrections(self):
        from fm_video import color as vcolor
        pane = self.make_pane(video_autoplay=False)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        self.assertTrue(wait(lambda: pane._shown == 0, 5))
        pane.set_grade({**vcolor.DEFAULT_GRADE, "exposure": 1.0, "saturation": 0.5, "gain_r": 1.4,
                        "in_white": 0.8}, save=False)
        main = pane.open_grade_window("grade_main")
        channels = pane.open_grade_window("grade_channels")
        pump(0.2)
        b_main, b_chan = pane._bypass_buttons["grade_main"], pane._bypass_buttons["grade_channels"]
        self.assertIs(b_main.parentWidget(), main.titlebar)
        sliders_before = {spec.key: field.value() for spec, field in main._fields if spec.key.startswith("vg_")}
        # Avant des corrections générales : exposition / saturation à l'origine, canaux et niveaux gardés.
        b_main.mouseReleaseEvent(_left_release(b_main))
        state = pane.viewer.state
        self.assertTrue(b_main.checked)
        self.assertEqual(state.grade["exposure"], 0.0)
        self.assertEqual(state.grade["saturation"], 1.0)
        self.assertEqual(state.grade["gain_r"], 1.4)
        self.assertEqual(state.grade["in_white"], 0.8)
        self.assertEqual(pane._grade["exposure"], 1.0)                         # réglage gardé
        self.assertEqual({spec.key: field.value() for spec, field in main._fields if spec.key.startswith("vg_")},
                         sliders_before)
        self.assertEqual(pane.view_state(display=False).grade["exposure"], 1.0)   # export : vraies valeurs
        # Avant des canaux en plus, puis après des générales seulement.
        b_chan.mouseReleaseEvent(_left_release(b_chan))
        self.assertEqual(pane.viewer.state.grade["gain_r"], 1.0)
        self.assertEqual(pane.viewer.state.grade["in_white"], 1.0)
        b_main.mouseReleaseEvent(_left_release(b_main))
        self.assertEqual(pane.viewer.state.grade["exposure"], 1.0)
        self.assertEqual(pane.viewer.state.grade["gain_r"], 1.0)
        # Index et zoom inchangés.
        self.assertEqual(pane.index, 0)
        # Fenêtre fermée en « avant » : ses corrections reviennent.
        channels.close(); pump(0.2)
        self.assertEqual(pane.viewer.state.grade["gain_r"], 1.4)
        self.assertFalse(pane._bypass)
        main.close(); pump(0.1)


def _left_release(widget):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    c = QPointF(widget.width() / 2, widget.height() / 2)
    return QMouseEvent(QEvent.MouseButtonRelease, c, widget.mapToGlobal(c), Qt.LeftButton, Qt.NoButton,
                       Qt.NoModifier)


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class TimelineThumbsTest(_PaneCase):
    def test_thumbnails_only_on_button_click_never_on_zoom(self):
        pane = self.make_pane(video_autoplay=True, video_loop=True, video_timeline_thumbs=True)
        self.assertTrue(pane.open(self.video))
        pane.fade_in()
        tl = pane.timeline
        pump(1.0)
        self.assertEqual(tl.thumbs, {})                                  # rien sans le bouton
        # Bouton : la partie visible se remplit (lecture en cours).
        pane.buttons["thumbs"].clicked.emit()
        self.assertTrue(wait(lambda: set(tl.thumb_indices()) <= set(tl.thumbs), 10),
                        (tl.thumb_indices(), sorted(tl.thumbs)))
        self.assertTrue(pane._playing or pane._engine != "vlc")
        # Zoom / défilement : aucune nouvelle demande.
        asked = []
        tl.thumbsWanted.connect(asked.append)
        tl.zoom(3.0, tl.width() / 2)
        tl.scroll(5)
        pump(0.5)
        self.assertEqual(asked, [])
        pane.buttons["thumbs"].clicked.emit()                            # reclic : la vue zoomée
        self.assertEqual(len(asked), 1)
        self.assertTrue(wait(lambda: set(tl.thumb_indices()) <= set(tl.thumbs), 10))

    def test_dragging_the_band_top_resizes_thumbnails_and_keeps_the_view(self):
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        saved = []
        from fm_video import pane as vpane
        vpane.HOOKS["save_state"] = lambda k, v: saved.append((k, v))
        try:
            pane = self.make_pane(video_autoplay=False, video_timeline_thumbs=True, video_timeline_thumb_height=40)
            self.assertTrue(pane.open(self.video))
            pane.fade_in()
            pump(0.3)
            tl = pane.timeline
            tl.zoom(2.0, tl.width() / 2)
            pane.go(20)
            tl.set_range(10, 30)
            view, height = tl.view(), tl.height()
            top = tl._thumb_band()[0]

            def send(kind, local_y, global_y, buttons):
                event = QMouseEvent(kind, QPointF(50, local_y), QPointF(500, global_y), Qt.LeftButton, buttons,
                                    Qt.NoModifier)
                {QEvent.MouseButtonPress: tl.mousePressEvent, QEvent.MouseMove: tl.mouseMoveEvent,
                 QEvent.MouseButtonRelease: tl.mouseReleaseEvent}[kind](event)

            tl.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(50, top + 1), QPointF(500, 400),
                                          Qt.NoButton, Qt.NoButton, Qt.NoModifier))
            self.assertEqual(tl.cursor().shape(), Qt.SizeVerCursor)
            send(QEvent.MouseButtonPress, top, 400, Qt.LeftButton)
            for dy in range(1, 31):
                send(QEvent.MouseMove, top, 400 - dy, Qt.LeftButton)       # vers le haut = plus grandes
            send(QEvent.MouseButtonRelease, top, 370, Qt.NoButton)
            self.assertEqual(tl.thumb_h, 70)
            self.assertEqual(tl.height(), height + 30)
            self.assertEqual(tl.view(), view)                                # zoom horizontal gardé
            self.assertEqual((tl.in_point, tl.out_point, tl.current), (10, 30, 20))
            self.assertEqual(saved[-1], ("video_timeline_thumb_height", 70))
            pane.buttons["thumbs"].clicked.emit()
            # Les miniatures arrivent à la nouvelle taille, sans déformation (case = hauteur × rapport).
            self.assertTrue(wait(lambda: any(i in tl.thumbs and tl.thumbs[i].height() >= 70
                                             for i in tl.thumb_indices()), 10))
            slots, _q = tl._thumb_slots()
            self.assertAlmostEqual(slots[0][1], 70 * tl.thumb_aspect, delta=0.01)
            # Bornes.
            send(QEvent.MouseButtonPress, tl._thumb_band()[0], 400, Qt.LeftButton)
            send(QEvent.MouseMove, 0, 2000, Qt.LeftButton)
            send(QEvent.MouseButtonRelease, 0, 2000, Qt.NoButton)
            self.assertEqual(tl.thumb_h, tl.THUMB_MIN)
        finally:
            vpane.HOOKS.pop("save_state", None)


class ThumbnailsTest(unittest.TestCase):
    def test_loader_reads_thumbnails_while_playing_and_resends_known_ones(self):
        from fm_video import thumbs as vthumbs
        from fm_video.thumbs import ThumbnailLoader
        folder = Path(tempfile.mkdtemp(prefix="thumbs_"))
        try:
            clip = folder / "c.mp4"
            make_video(clip, audio=False)
            got = {}
            loader = ThumbnailLoader(clip)
            loader.ready.connect(lambda i, img: got.__setitem__(i, img))
            loader.set_playing(True)                           # lecture en cours : au ralenti, mais elles arrivent
            start = time.perf_counter()
            loader.request([0, 30, 59])
            self.assertTrue(wait(lambda: len(got) == 3, 10))
            self.assertGreaterEqual(time.perf_counter() - start, 3 * vthumbs.PLAY_GAP_S * 0.9)
            self.assertEqual(got[0].height(), 48)
            # La timeline les a oubliées (index prêt) : une nouvelle demande les RENVOIE aussitôt.
            got.clear()
            loader.request([0, 30, 59])
            self.assertEqual(sorted(got), [0, 30, 59])
            # Bande agrandie : refaites à la nouvelle hauteur.
            loader.set_playing(False)
            got.clear()
            loader.set_height(96)
            loader.request([30])
            self.assertTrue(wait(lambda: 30 in got, 10))
            self.assertEqual(got[30].height(), 96)
            loader.stop()
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class AllLayersExportTest(unittest.TestCase):
    def test_every_part_channel_type_and_metadata_are_kept(self):
        try:
            import OpenImageIO as oiio
        except Exception:                                      # noqa: BLE001
            self.skipTest("OpenImageIO absent")
        from fm_video import export as vexport
        from fm_video import media as vmedia
        folder = Path(tempfile.mkdtemp(prefix="aov_"))
        try:
            for n in (1001, 1002, 1003):
                path = folder / f"shot.{n}.exr"
                specs = []
                for name, chans, fmt in (("rgba", ("R", "G", "B", "A"), oiio.HALF),
                                         ("diffuse", ("diffuse.R", "diffuse.G", "diffuse.B"), oiio.HALF),
                                         ("depth", ("Z",), oiio.FLOAT)):
                    spec = oiio.ImageSpec(32, 16, len(chans), fmt)
                    spec.channelnames = chans
                    spec.attribute("name", name)
                    spec.attribute("cameraName", "camA")
                    specs.append(spec)
                out = oiio.ImageOutput.create(str(path))
                out.open(str(path), specs)
                for i, spec in enumerate(specs):
                    if i:
                        out.open(str(path), spec, "AppendSubimage")
                    out.write_image(np.full((16, 32, spec.nchannels), n / 1000.0 + i, np.float32))
                out.close()
            source = vmedia.open_media(folder / "shot.1001.exr")
            target = folder / "out" / "copie.exr"
            target.parent.mkdir()
            job = vexport.ExportJob(source, vexport.ExportSettings(
                output=target, fmt="exr", content="data", range=(0, 2), numbering="1", all_layers=True))
            result = {}
            job.finished.connect(lambda ok, msg, path: result.update(ok=ok, msg=msg))
            job.start()
            self.assertTrue(wait(lambda: bool(result), 20))
            self.assertTrue(result["ok"], result["msg"])
            done = folder / "out" / "copie.0002.exr"
            inp = oiio.ImageInput.open(str(done))
            parts = []
            while inp.seek_subimage(len(parts), 0):
                spec = inp.spec()
                parts.append((spec.getattribute("name"), tuple(spec.channelnames), str(spec.format),
                              spec.getattribute("cameraName")))
            z = inp.read_image(2, 0, 0, 1, oiio.FLOAT)
            inp.close()
            self.assertEqual(parts, [("rgba", ("R", "G", "B", "A"), "half", "camA"),
                                     ("diffuse", ("diffuse.R", "diffuse.G", "diffuse.B"), "half", "camA"),
                                     ("depth", ("Z",), "float", "camA")])
            self.assertAlmostEqual(float(z.mean()), 1.002 + 2, places=4)
            self.assertFalse(list((folder / "out").glob("*.part.*")))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
