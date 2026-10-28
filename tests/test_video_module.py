"""Module vidéo (paquet fm_video/) : séquences, lecture EXACTE image par image (avant / arrière), précision des
EXR / TIFF / PNG, colorimétrie (corrections, LUT .cube, OCIO, même calcul GPU / CPU vérifié par la sonde native),
export (plage IN / OUT exacte, cadences, séquences, annulation, originaux intacts), module (centrage gardé par les
informations, réglages en direct), onglet « Module vidéo » des réglages."""
import _isolate  # noqa: F401

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])

from fm_video import color as vcolor          # noqa: E402
from fm_video import media as vmedia          # noqa: E402

try:
    import av  # noqa: F401
    HAS_AV = True
except Exception:                          # noqa: BLE001
    HAS_AV = False
try:
    import OpenImageIO as oiio
except Exception:                          # noqa: BLE001
    oiio = None
FFMPEG = shutil.which("ffmpeg")

W, H, N = 160, 96, 60


def _gray(i: int) -> int:
    return (i * 4) % 240


CODEC_ARGS = {
    "h264": ["-c:v", "libx264", "-bf", "3", "-pix_fmt", "yuv420p"],
    "hevc": ["-c:v", "libx265", "-x265-params", "log-level=error:bframes=4", "-pix_fmt", "yuv420p10le"],
    "prores": ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"],
    "vp9": ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-pix_fmt", "yuv420p"],
    "mpeg4": ["-c:v", "mpeg4", "-q:v", "2", "-bf", "2", "-pix_fmt", "yuv420p"],
}


def make_video(path: Path, fps: int = 24, count: int = N, gop: int = 30, codec: str = "h264", vfr: bool = False):
    """Vidéo dont l'image n est un gris connu (_gray(n)) ; GOP long et B-frames quand le codec en a. `vfr` :
    horodatages IRRÉGULIERS (cadence variable : écarts de 1 à 3 « images »)."""
    extra = ["-g", str(gop)] if codec in ("h264", "hevc", "vp9", "mpeg4") else []
    timing = ["-vf", "setpts=(N+floor(N/3)+floor(N/5))/TB/24", "-fps_mode", "vfr"] if vfr else []
    proc = subprocess.Popen([FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s",
                             f"{W}x{H}", "-r", str(fps), "-i", "-", *timing, *CODEC_ARGS[codec], *extra, str(path)],
                            stdin=subprocess.PIPE)
    for i in range(count):
        proc.stdin.write(np.full((H, W), _gray(i), np.uint8).tobytes())
    proc.stdin.close()
    proc.wait()


def write_image(path: Path, pixels: np.ndarray, type_desc):
    h, w, c = pixels.shape
    out = oiio.ImageOutput.create(str(path))
    spec = oiio.ImageSpec(w, h, c, type_desc)
    out.open(str(path), spec)
    out.write_image(np.ascontiguousarray(pixels, np.float32))
    out.close()


def wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        APP.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


def digest(path: Path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


class SequenceDetectionTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="seq_"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def touch(self, *names):
        for name in names:
            (self.dir / name).write_bytes(b"x")

    def test_padding_versions_missing_and_several_sequences(self):
        self.touch(*[f"smoke_v003.{n:04d}.tif" for n in (1001, 1002, 1004, 1005)],
                   *[f"smoke_v004.{n:04d}.tif" for n in (1001, 1002)], "smoke_v003.tif", "other.0001.exr")
        seq = vmedia.find_sequence(self.dir / "smoke_v003.1002.tif")
        self.assertEqual(seq.numbers, [1001, 1002, 1004, 1005])
        self.assertEqual(seq.missing(), [1003])
        self.assertEqual(seq.length, 5)
        self.assertEqual(seq.path_for(1003).name, "smoke_v003.1003.tif")
        self.assertIsNone(vmedia.find_sequence(self.dir / "smoke_v003.tif"))
        self.assertIsNone(vmedia.find_sequence(self.dir / "other.0001.exr"))        # image seule
        names = {s.pattern for s in vmedia.list_sequences(self.dir)}
        self.assertEqual(names, {"smoke_v003.####.tif", "smoke_v004.####.tif"})

    def test_padded_and_unpadded_numbers_stay_apart(self):
        self.touch("a.0001.png", "a.0002.png", "a.1.png", "a.2.png", "a.3.png")
        self.assertEqual(vmedia.find_sequence(self.dir / "a.0001.png").numbers, [1, 2])
        self.assertEqual(vmedia.find_sequence(self.dir / "a.3.png").numbers, [1, 2, 3])

    def test_timecode_round_trip(self):
        fps = Fraction(25)
        self.assertEqual(vmedia.format_timecode(25 * 61 + 3, fps), "00:01:01:03")
        self.assertEqual(vmedia.parse_timecode("00:01:01:03", fps), 25 * 61 + 3)
        self.assertEqual(vmedia.parse_fps("23.976"), Fraction(24000, 1001))


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class VideoFrameAccuracyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="vid_"))
        cls.video = cls.dir / "clip.mp4"
        make_video(cls.video)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_every_frame_forward_backward_and_random(self):
        src = vmedia.open_media(self.video)
        self.assertTrue(src.build_index())
        self.assertEqual(src.frame_count, N)
        order = list(range(N)) + list(range(N - 1, -1, -1)) + [17, 3, 59, 31, 30, 29, 0]
        for i in order:
            frame = src.read(i)
            self.assertEqual(frame.index, i)
            self.assertLess(abs(float(frame.pixels.mean()) - _gray(i)), 3.0, f"image {i}")
        src.close()

    def test_every_container_and_codec_steps_exactly_both_ways(self):
        """MP4, MOV, MKV, WEBM, AVI ; H.264 / HEVC à B-frames, ProRes, VP9, MPEG-4 ; cadence variable."""
        cases = [("h264.mov", "h264", False), ("prores.mov", "prores", False), ("hevc.mkv", "hevc", False),
                 ("vp9.webm", "vp9", False), ("mpeg4.avi", "mpeg4", False), ("vfr.mkv", "h264", True),
                 ("vfr.mp4", "h264", True)]
        for name, codec, vfr in cases:
            with self.subTest(name):
                path = self.dir / name
                make_video(path, codec=codec, vfr=vfr, count=40)
                src = vmedia.open_media(path)
                self.assertTrue(src.build_index())
                self.assertEqual(src.frame_count, 40)
                order = [0, 1, 2, 3] + list(range(39, -1, -1)) + list(range(0, 40)) + [25, 7, 33, 32, 31]
                for i in order:
                    frame = src.read(i)
                    level = float(vmedia.normalized(frame.pixels)[..., 0].mean()) * 255
                    self.assertLess(abs(level - _gray(i)), 3.0, f"{name} image {i}")
                src.close()

    def test_backward_steps_keep_decoded_frames(self):
        src = vmedia.open_media(self.video)
        src.build_index()
        extra = []
        src.read(45, on_extra=extra.append)
        self.assertTrue(extra and all(f.index < 45 for f in extra))
        for f in extra:
            self.assertLess(abs(float(f.pixels.mean()) - _gray(f.index)), 3.0)
        src.close()


@unittest.skipUnless(oiio is not None, "OpenImageIO absent")
class ImagePrecisionTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="img_"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_exr_half_and_float_tiff_16_png_alpha_keep_their_precision(self):
        hdr = np.zeros((8, 8, 4), np.float32)
        hdr[..., 0] = 7.25                     # HDR > 1 gardé
        hdr[..., 3] = 0.5
        write_image(self.dir / "r.0001.exr", hdr, oiio.HALF)
        write_image(self.dir / "r.0002.exr", hdr, oiio.HALF)
        write_image(self.dir / "f.tif", np.full((4, 4, 3), 0.123456, np.float32), oiio.FLOAT)
        write_image(self.dir / "s.tif", np.full((4, 4, 3), 40000 / 65535, np.float32), oiio.UINT16)
        write_image(self.dir / "p.png", np.full((4, 4, 4), 0.5, np.float32), oiio.UINT8)
        exr = vmedia.open_media(self.dir / "r.0002.exr")
        self.assertEqual(exr.kind, "sequence")
        frame = exr.read(0)
        self.assertEqual(frame.pixels.dtype, np.float16)
        self.assertAlmostEqual(float(frame.pixels[0, 0, 0]), 7.25, places=2)
        self.assertEqual(frame.channels, 4)
        f32 = vmedia.open_media(self.dir / "f.tif").read(0)
        self.assertEqual(f32.pixels.dtype, np.float32)
        self.assertAlmostEqual(float(f32.pixels[0, 0, 0]), 0.123456, places=6)
        u16 = vmedia.open_media(self.dir / "s.tif").read(0)
        self.assertEqual(u16.pixels.dtype, np.uint16)
        self.assertEqual(int(u16.pixels[0, 0, 0]), 40000)
        png = vmedia.open_media(self.dir / "p.png").read(0)
        self.assertEqual((png.pixels.dtype, png.channels), (np.uint8, 4))

    def test_exr_layers_are_listed_and_selectable(self):
        out = oiio.ImageOutput.create("x.exr")
        spec = oiio.ImageSpec(4, 4, 6, oiio.HALF)
        spec.channelnames = ("R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B")
        path = self.dir / "aov.exr"
        out.open(str(path), spec)
        data = np.zeros((4, 4, 6), np.float32)
        data[..., 3] = 0.75
        out.write_image(data)
        out.close()
        src = vmedia.open_media(path)
        self.assertIn("diffuse", src.layers)
        src.set_layer("diffuse")
        self.assertAlmostEqual(float(src.read(0).pixels[0, 0, 0]), 0.75, places=3)

    def test_exr_sequence_steps_exactly_both_ways_in_the_pane(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QWidget
        from settings_store import DEFAULT_SETTINGS
        from fm_video.pane import VideoPane
        for n in range(1001, 1021):
            write_image(self.dir / f"beauty.{n}.exr", np.full((8, 8, 3), n / 1000, np.float32), oiio.HALF)
        host = QWidget()
        host.resize(600, 400)
        pane = VideoPane(host, dict(DEFAULT_SETTINGS, video_backend="cpu"))
        try:
            self.assertTrue(pane.open(self.dir / "beauty.1005.exr"))
            pane.fade_in()
            host.show()
            self.assertTrue(wait(lambda: pane._shown == 4))
            expected = 4
            for key in [Qt.Key_Right] * 10 + [Qt.Key_Left] * 14:
                QTest.keyClick(pane.viewer, key)
                expected += 1 if key == Qt.Key_Right else -1
                self.assertTrue(wait(lambda: pane._shown == expected, 5), expected)
                self.assertAlmostEqual(float(pane.viewer.frame.pixels[0, 0, 0]), (1001 + expected) / 1000, places=2)
                self.assertEqual(pane.frame_field.text(), str(1001 + expected))
        finally:
            pane.shutdown()
            pane.deleteLater()
            host.deleteLater()

    def test_missing_frame_is_reported_not_invented(self):
        img = np.full((4, 4, 3), 0.5, np.float32)
        for n in (1, 2, 4):
            write_image(self.dir / f"m.{n:04d}.exr", img, oiio.HALF)
        src = vmedia.open_media(self.dir / "m.0001.exr")
        self.assertEqual(src.frame_count, 4)
        self.assertTrue(src.read(2).missing)
        self.assertIsNone(src.read(2).pixels)


class ColorTest(unittest.TestCase):
    def test_neutral_grade_is_identity_and_exposure_is_in_stops(self):
        rgb = np.random.default_rng(1).random((6, 6, 3)).astype(np.float32) * 3
        d = vcolor.derived(vcolor.DEFAULT_GRADE)
        np.testing.assert_allclose(vcolor.apply_grade_np(rgb, d), rgb, atol=1e-5)
        d = vcolor.derived({"exposure": 1.0})
        np.testing.assert_allclose(vcolor.apply_grade_np(rgb, d), rgb * 2, atol=1e-5)
        d = vcolor.derived({"saturation": 0.0})
        out = vcolor.apply_grade_np(rgb, d)
        np.testing.assert_allclose(out[..., 0], out[..., 1], atol=1e-5)
        d = vcolor.derived({"contrast": 1.8, "pivot": 0.18})
        pivot = np.full((1, 1, 3), 0.18, np.float32)
        np.testing.assert_allclose(vcolor.apply_grade_np(pivot, d), pivot, atol=1e-5)   # le pivot ne bouge pas
        self.assertFalse(vcolor.grade_active(vcolor.DEFAULT_GRADE))
        self.assertTrue(vcolor.grade_active({**vcolor.DEFAULT_GRADE, "gamma": 1.1}))

    def test_cube_lut_identity_invalid_and_1d(self):
        tmp = Path(tempfile.mkdtemp(prefix="lut_"))
        try:
            n = 5
            lines = ["TITLE \"id\"", f"LUT_3D_SIZE {n}"]
            for b in range(n):
                for g in range(n):
                    for r in range(n):
                        lines.append(f"{r / (n - 1)} {g / (n - 1)} {b / (n - 1)}")
            (tmp / "id.cube").write_text("\n".join(lines))
            lut = vcolor.load_cube(tmp / "id.cube")
            rgb = np.random.default_rng(2).random((5, 5, 3)).astype(np.float32)
            np.testing.assert_allclose(lut.apply_np(rgb), rgb, atol=1e-5)
            (tmp / "inv.cube").write_text("LUT_1D_SIZE 2\n1 1 1\n0 0 0\n")
            inv = vcolor.load_cube(tmp / "inv.cube")
            np.testing.assert_allclose(inv.apply_np(rgb), 1 - rgb, atol=1e-5)
            (tmp / "bad.cube").write_text("LUT_3D_SIZE 4\n0 0 0\n")
            with self.assertRaises(vcolor.LutError):
                vcolor.load_cube(tmp / "bad.cube")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(vcolor.ocio_available(), "OpenColorIO absent")
    def test_ocio_srgb_round_trip_and_pipeline_order(self):
        pipe = vcolor.ColorPipeline(vcolor.OcioSetup("", "sRGB Encoded Rec.709 (sRGB)", "sRGB - Display",
                                                     "Un-tone-mapped"))
        rgb = np.random.default_rng(3).random((4, 4, 3)).astype(np.float32)
        state = vcolor.ViewState(dict(vcolor.DEFAULT_GRADE))
        out, _a = vcolor.process_np(rgb, pipe, state)
        np.testing.assert_allclose(out, rgb, atol=2e-3)          # vidéo affichée telle quelle (comme VLC)
        lin, _a = vcolor.process_np(rgb, pipe, state, stage="working")
        self.assertEqual(pipe.working, "ACEScg")
        self.assertFalse(np.allclose(lin, rgb, atol=1e-2))       # interprétée en linéaire scène
        exposed, _a = vcolor.process_np(rgb, pipe, vcolor.ViewState({**vcolor.DEFAULT_GRADE, "exposure": 1}))
        self.assertGreater(float(exposed.mean()), float(out.mean()))


@unittest.skipUnless(HAS_AV and FFMPEG and oiio is not None, "PyAV / FFmpeg / OpenImageIO absents")
class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="exp_"))
        cls.video = cls.dir / "clip.mp4"
        make_video(cls.video, fps=24, count=48)
        cls.hash = digest(cls.video)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def run_job(self, source, **kw):
        from fm_video import export as vexport
        job = vexport.ExportJob(source, vexport.ExportSettings(overwrite=True, **kw))
        result = {}
        job.finished.connect(lambda ok, msg, path: result.update(ok=ok, msg=msg, path=path))
        job.start()
        self.assertTrue(wait(lambda: bool(result), 120), "export trop long")
        return result

    def source(self):
        src = vmedia.open_media(self.video)
        src.build_index()
        return src

    def test_selection_exports_exactly_its_frames(self):
        r = self.run_job(self.source(), output=self.dir / "sel.mp4", fmt="mp4", codec="h264", range=(10, 33))
        self.assertTrue(r["ok"], r["msg"])
        out = vmedia.open_media(r["path"])
        out.build_index()
        self.assertEqual(out.frame_count, 24)
        for k in range(24):
            self.assertLess(abs(float(out.read(k).pixels.mean()) - _gray(10 + k)), 4.0, f"image {k}")
        self.assertEqual(digest(self.video), self.hash)          # original jamais modifié

    def test_video_export_applies_the_lut_when_asked(self):
        lut_path = self.dir / "invert.cube"
        lut_path.write_text("LUT_1D_SIZE 2\n1 1 1\n0 0 0\n")
        view = vcolor.ViewState(dict(vcolor.DEFAULT_GRADE), lut=vcolor.load_cube(lut_path), lut_position="display")
        r = self.run_job(self.source(), output=self.dir / "lut.mp4", fmt="mp4", codec="h264", range=(5, 9),
                         view=view, pipeline=None, content="display")
        self.assertTrue(r["ok"], r["msg"])
        out = vmedia.open_media(r["path"])
        out.build_index()
        self.assertLess(abs(float(out.read(0).pixels.mean()) - (255 - _gray(5))), 4.0)
        r = self.run_job(self.source(), output=self.dir / "nolut.mp4", fmt="mp4", codec="h264", range=(5, 9),
                         view=view, pipeline=None, content="data")
        out = vmedia.open_media(r["path"])
        self.assertLess(abs(float(out.read(0).pixels.mean()) - _gray(5)), 4.0)       # sans corrections

    def test_frame_rate_conversions_keep_or_change_duration_as_asked(self):
        for fps, mode, expected in ((Fraction(25), "resample", 25), (Fraction(30), "resample", 30),
                                    (Fraction(30), "interpolate", 30), (Fraction(30), "reinterpret", 24)):
            r = self.run_job(self.source(), output=self.dir / f"r_{mode}_{fps}.mp4", fmt="mp4", codec="h264",
                             range=(0, 23), fps=fps, fps_mode=mode, interp="minterpolate")
            self.assertTrue(r["ok"], r["msg"])
            out = vmedia.open_media(r["path"])
            out.build_index()
            self.assertEqual((out.frame_count, out.fps), (expected, fps), f"{mode} {fps}")

    def test_resample_plan_is_rational(self):
        from fm_video.export import output_frame_plan
        plan = output_frame_plan(0, 23, Fraction(24), Fraction(30), "resample")
        self.assertEqual(len(plan), 30)
        self.assertEqual(plan[:6], [0, 0, 1, 2, 3, 4])
        self.assertEqual(len(output_frame_plan(0, 23, Fraction(24), Fraction(25), "resample")), 25)

    def test_exr_data_export_keeps_hdr_values_and_numbering(self):
        img = np.zeros((8, 8, 3), np.float32)
        img[..., 1] = 5.5
        for n in (1001, 1002, 1003):
            write_image(self.dir / f"hdr.{n}.exr", img, oiio.HALF)
        src = vmedia.open_media(self.dir / "hdr.1001.exr")
        r = self.run_job(src, output=self.dir / "out" / "copy.exr", fmt="exr", depth="float", content="data",
                         range=(0, 2))
        self.assertTrue(r["ok"], r["msg"])
        self.assertEqual(Path(r["path"]).name, "copy.1001.exr")
        out = vmedia.open_media(r["path"])
        self.assertAlmostEqual(float(out.read(0).pixels[0, 0, 1]), 5.5, places=3)
        self.assertEqual(out.read(0).pixels.dtype, np.float32)

    def test_cancel_removes_the_temporary_file(self):
        from fm_video import export as vexport
        out = self.dir / "cancel.mp4"
        job = vexport.ExportJob(self.source(), vexport.ExportSettings(output=out, fmt="mp4", codec="h264",
                                                                       preset="veryslow", range=(0, 47),
                                                                       overwrite=True))
        result = {}
        job.finished.connect(lambda ok, msg, path: result.update(ok=ok, msg=msg))
        job.start()
        time.sleep(0.2)
        job.cancel()
        self.assertTrue(wait(lambda: bool(result), 30))
        self.assertFalse(result["ok"])
        self.assertFalse(out.exists())
        self.assertFalse((self.dir / "cancel.part.mp4").exists())


@unittest.skipUnless(HAS_AV and FFMPEG, "PyAV / FFmpeg absents")
class PaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="pane_"))
        cls.video = cls.dir / "clip.mp4"
        make_video(cls.video)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        from PySide6.QtWidgets import QWidget
        from settings_store import DEFAULT_SETTINGS
        from fm_video.pane import VideoPane
        self.host = QWidget()
        self.host.resize(900, 600)
        # Pas de lecture automatique : ces tests naviguent image par image depuis la pause.
        settings = dict(DEFAULT_SETTINGS, video_backend="cpu", video_autoplay=False)
        self.pane = VideoPane(self.host, settings)
        self.assertTrue(self.pane.open(self.video))
        self.pane.fade_in()
        self.host.show()
        APP.processEvents()

    def tearDown(self):
        self.pane.shutdown()
        self.pane.deleteLater()
        self.host.deleteLater()
        APP.processEvents()

    def shown_gray(self):
        return float(self.pane.viewer.frame.pixels.mean())

    def test_step_forward_and_backward_shows_the_exact_frame(self):
        pane = self.pane
        self.assertTrue(wait(lambda: pane._shown == 0))
        for target in (1, 2, 3, 2, 1, 0, 25, 24, 23):
            pane.go(target)
            self.assertTrue(wait(lambda: pane._shown == target), f"image {target}")
            self.assertLess(abs(self.shown_gray() - _gray(target)), 3.0, f"image {target}")

    def test_arrow_keys_step_exactly_and_keep_frame_field_and_timeline_in_sync(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        pane = self.pane
        self.assertTrue(wait(lambda: pane._shown == 0))
        keys = [Qt.Key_Right] * 35 + [Qt.Key_Left] * 35 + [Qt.Key_End] + [Qt.Key_Left] * 3 + [Qt.Key_Home]
        expected = 0
        for key in keys:
            QTest.keyClick(pane.viewer, key)
            expected = {Qt.Key_Right: expected + 1, Qt.Key_Left: expected - 1, Qt.Key_End: N - 1,
                        Qt.Key_Home: 0}[key]
            self.assertTrue(wait(lambda: pane._shown == expected, 5), f"image {expected}")
            self.assertLess(abs(self.shown_gray() - _gray(expected)), 3.0, f"image {expected}")
            self.assertEqual(pane.timeline.current, expected)
            self.assertEqual(pane.frame_field.text(), str(expected))

    def test_info_overlay_never_moves_the_image_and_follows_its_settings(self):
        pane = self.pane
        self.assertTrue(wait(lambda: pane._shown == 0))
        before = pane.viewer.image_rect()
        center = pane.viewer.rect().center()
        self.assertAlmostEqual(before.center().x(), center.x(), delta=1)
        pane.toggle_info()
        APP.processEvents()
        self.assertTrue(pane.overlay.isVisible())
        self.assertEqual(pane.viewer.image_rect(), before)
        sections = dict(pane.info_sections())
        self.assertIn("Média", sections)
        self.assertIn(("Résolution", f"{W} × {H}"), sections["Image"])
        settings = dict(pane._settings, video_info_opacity=15, video_info_corner="bottom_left")
        pane.apply_settings(settings)
        self.assertEqual(pane.overlay.look["opacity"], 15)
        self.assertLess(pane.overlay.x(), pane.viewer.width() / 2)
        margin = pane.overlay.look["margin_y"]
        self.assertEqual(pane.overlay.geometry().bottom() + 1, pane.viewer.height() - margin)   # collé en bas
        pane.toggle_info()
        self.assertEqual(pane.viewer.image_rect(), before)

    def test_in_out_range_and_timeline_zoom(self):
        pane = self.pane
        pane.go(10)
        pane.set_in()
        pane.go(20)
        pane.set_out()
        self.assertEqual(pane.timeline.range(), (10, 20))
        pane._toggle_loop_range()
        self.assertEqual(pane._bounds(), (10, 20))
        span = pane.timeline.view()[1] - pane.timeline.view()[0]
        pane.timeline.zoom(3, 100)
        self.assertLess(pane.timeline.view()[1] - pane.timeline.view()[0], span)
        pane.clear_range()
        self.assertEqual(pane.timeline.range(), (0, N - 1))

    def test_playback_advances_and_pause_lands_on_a_frame(self):
        pane = self.pane
        pane.play()
        self.assertTrue(wait(lambda: pane._shown >= 5, 5))
        pane.pause()
        self.assertEqual(pane.index, pane._shown)
        self.assertLess(abs(self.shown_gray() - _gray(pane._shown)), 3.0)

    def test_moodboard_receives_real_video_thumbnails(self):
        pane = self.pane
        pane.toggle_moodboard()
        self.assertTrue(wait(lambda: len(pane.moodboard.pixmaps) == len(set(pane._moodboard_paths)), 15))

    def test_grade_window_applies_corrections_live(self):
        pane = self.pane
        window = pane.open_grade_window("grade_main")
        fields = {spec.key: field for spec, field in window._fields}
        self.assertIn("vg_exposure", fields)
        fields["vg_exposure"].setValue(150)                    # 1,50 stop
        fields["vg_saturation"].setValue(50)                   # 0,50
        self.assertTrue(wait(lambda: abs(pane._grade["exposure"] - 1.5) < 1e-9
                             and abs(pane._grade["saturation"] - 0.5) < 1e-9, 3))
        self.assertEqual(pane.viewer.state.grade["exposure"], 1.5)
        window.close()

    def test_grade_changes_view_state_not_the_frame(self):
        pane = self.pane
        self.assertTrue(wait(lambda: pane._shown == 0))
        raw = pane.viewer.frame.pixels.copy()
        pane.set_grade({**vcolor.DEFAULT_GRADE, "exposure": 1.5}, save=False)
        self.assertEqual(pane.viewer.state.grade["exposure"], 1.5)
        np.testing.assert_array_equal(pane.viewer.frame.pixels, raw)


class MoodboardUiTest(unittest.TestCase):
    def test_mode_pauses_and_replaces_view_with_resizable_video_samples(self):
        from PySide6.QtWidgets import QWidget
        from settings_store import DEFAULT_SETTINGS
        from fm_video.pane import VideoPane

        class Source:
            frame_count = 1200
            kind = 'video'
            index_ready = True
            fps = Fraction(24, 1)
            width = 1920
            height = 1080
            def time_of(self,index):
                return index/24
            def number_of(self, index):
                return index + 1001

        class Thumbs:
            def __init__(self):
                self.height = 0
                self.requested = []
                self.ready = type("Signal", (), {"disconnect": lambda self, _slot: None})()
            def set_height(self, height):
                self.height = height
            def set_moodboard(self, indices, layout=()):
                pass
            def request(self, indices):
                self.requested = list(indices)
            def set_playing(self, _playing):
                pass
            def stop(self):
                pass

        host = QWidget()
        pane = VideoPane(host, dict(DEFAULT_SETTINGS, video_backend="cpu"))
        try:
            host.resize(900, 600)
            pane.setGeometry(0, 0, 900, 600)
            host.show()
            APP.processEvents()
            pane.source = Source()
            pane._thumbs = Thumbs()
            pane._mood_thumbs = Thumbs()
            pane._playing = True
            pane.toggle_moodboard()
            APP.processEvents()
            self.assertFalse(pane._playing)
            self.assertIs(pane.content_layout.currentWidget(), pane.moodboard)
            self.assertEqual(pane.moodboard.count(), pane.moodboard_grid[0] * pane.moodboard_grid[1])
            self.assertEqual(pane._moodboard_paths[0], 0)
            if len(pane._moodboard_paths) > 1:
                self.assertEqual(pane._moodboard_paths[-1], pane.source.frame_count - 1)
            self.assertAlmostEqual(pane._moodboard_cell.width() / pane._moodboard_cell.height(), 16 / 9, delta=0.02)
            self.assertEqual(pane._mood_thumbs.requested, pane._moodboard_paths)
            pane.mood_size_slider.setValue(260)
            self.assertLessEqual(pane._moodboard_cell.width(), 260)
            self.assertAlmostEqual(pane._moodboard_cell.width() / pane._moodboard_cell.height(), 16 / 9,
                                   delta=0.02)
            pane.toggle_moodboard()
            self.assertIs(pane.content_layout.currentWidget(), pane.viewer)
            self.assertFalse(pane._playing)
        finally:
            pane.shutdown()
            pane.deleteLater()
            host.deleteLater()
            APP.processEvents()


class SettingsTabTest(unittest.TestCase):
    def test_every_video_row_is_declared_and_builds(self):
        import settings_window_v2 as v2
        from settings_store import DEFAULT_SETTINGS
        values = dict(DEFAULT_SETTINGS)
        scope = v2.ScopeValues(values, None, v2.VIDEO_TAB)
        self.assertIn((v2.VIDEO_TAB, None), v2.SCOPES)
        for node in v2.VIDEO_TREE:
            for spec in v2.CATALOG[node.group]:
                self.assertIn(spec.key, DEFAULT_SETTINGS, spec.key)
                for key in spec.extra_keys:
                    self.assertIn(key, DEFAULT_SETTINGS, key)
                widget = v2.make_field(spec, scope, values["colors"])
                read = v2.read_spec(spec, widget)
                self.assertEqual(read[spec.key], DEFAULT_SETTINGS[spec.key], spec.key)

    def test_decimal_slider_reads_integers_and_shows_decimals(self):
        from settings_widgets import _SliderField
        field = _SliderField(-1000, 1000, 125, "stops", scale=100)
        self.assertEqual(field.value_label.text(), "1.25")
        field.value_label.setText("-2,5")
        field._on_text_edited()
        self.assertEqual(field.value(), -250)


if __name__ == "__main__":
    unittest.main()
