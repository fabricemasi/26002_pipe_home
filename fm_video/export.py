"""Export du module vidéo, en fond (l'appli reste réactive), annulable, fichiers temporaires nettoyés.

- Vidéo (MP4, MOV, MKV, WEBM) : les images sont lues par la source du module (images EXACTES de la plage IN / OUT),
  traitées comme à l'écran si demandé (corrections + LUT + affichage OCIO, `color.process_np`), puis envoyées en
  16 bits par canal à FFmpeg par un tube ; FFmpeg encode (H.264, H.265, ProRes, DNxHR, AV1, VP9) et reprend
  l'audio de la plage depuis le fichier source. Écrit dans « <nom>.part.<ext> », renommé à la fin.
- Séquence (EXR, TIFF, PNG, DPX) : OpenImageIO, précision choisie (EXR half / float, TIFF 8 / 16 / 32 flottant,
  PNG 8 / 16). Trois contenus : « données » (pixels de la source, tels quels — EXR : valeurs linéaires gardées),
  « linéaire corrigé » (espace de travail + corrections, sans transformation d'affichage) ou « tel qu'affiché ».

Changement de cadence (cadences RATIONNELLES, aucun arrondi cumulé) :
- « reinterpret » : mêmes images, nouvelle cadence (la durée change ; audio non repris) ;
- « resample » : durée gardée, images dupliquées / retirées : l'image de sortie k montre l'image source
  floor(k × fps_source / fps_sortie) ;
- « interpolate » : durée gardée, images intermédiaires CALCULÉES aux bons instants : FFmpeg `minterpolate`
  (flux optique par blocs, détection des changements de plan : pas d'interpolation entre deux plans) ou
  `blend` (fondu), ou RIFE (rife-ncnn-vulkan, optionnel, Vulkan) quand il est installé."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from fm_video import color as vcolor
from fm_video.media import Frame, MediaSource

VIDEO_CONTAINERS = {"mp4": ".mp4", "mov": ".mov", "mkv": ".mkv", "webm": ".webm"}
SEQUENCE_FORMATS = {"exr": ".exr", "tiff": ".tif", "png": ".png", "dpx": ".dpx"}

# codec -> (encodeur FFmpeg, conteneurs permis)
CODECS = {
    "h264": ("libx264", ("mp4", "mov", "mkv")),
    "h265": ("libx265", ("mp4", "mov", "mkv")),
    "prores": ("prores_ks", ("mov", "mkv")),
    "dnxhr": ("dnxhd", ("mov", "mkv")),
    "av1": ("libsvtav1", ("mp4", "mkv", "webm")),
    "vp9": ("libvpx-vp9", ("webm", "mkv")),
}
PRORES_PROFILES = (("0", "Proxy"), ("1", "LT"), ("2", "422"), ("3", "422 HQ"), ("4", "4444"), ("5", "4444 XQ"))
DNXHR_PROFILES = (("dnxhr_lb", "LB"), ("dnxhr_sq", "SQ"), ("dnxhr_hq", "HQ"), ("dnxhr_hqx", "HQX 10 bits"),
                  ("dnxhr_444", "444"))
X26X_PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")


def ffmpeg_path() -> str | None:
    return os.environ.get("FFMPEG_EXECUTABLE") or shutil.which("ffmpeg")


_ENCODERS: set[str] | None = None


def available_encoders() -> set[str]:
    """Encodeurs vidéo du FFmpeg installé (lu une fois)."""
    global _ENCODERS
    if _ENCODERS is not None:
        return _ENCODERS
    exe = ffmpeg_path()
    found = set()
    if exe:
        try:
            out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10,
                                 creationflags=_NO_WINDOW).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith("V"):
                    found.add(parts[1])
        except (OSError, subprocess.SubprocessError):
            pass
    _ENCODERS = found
    return found


def available_codecs() -> list[str]:
    encoders = available_encoders()
    return [name for name, (enc, _c) in CODECS.items() if enc in encoders]


def rife_path(configured: str = "") -> str | None:
    """rife-ncnn-vulkan : chemin réglé, sinon $RIFE_NCNN_VULKAN, sinon le PATH, sinon celui livré dans
    `tools/rife/` (téléchargé à part, ignoré par git). None = RIFE indisponible."""
    for candidate in (configured, os.environ.get("RIFE_NCNN_VULKAN", "")):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    found = shutil.which("rife-ncnn-vulkan")
    if found:
        return found
    bundled = sorted((Path(__file__).resolve().parent.parent / "tools" / "rife").glob("*/rife-ncnn-vulkan.exe"))
    return str(bundled[-1]) if bundled else None


def rife_model(exe: str) -> str | None:
    """Modèle RIFE v4 le plus récent livré avec l'exécutable (chemin ABSOLU : sinon cherché dans le dossier
    courant). Seuls les modèles v4 acceptent un nombre d'images quelconque (`-n`) : les autres ne font que doubler."""
    models = sorted((p for p in Path(exe).parent.glob("rife-v4*") if (p / "flownet.param").is_file()),
                    key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name[6:].split(".")])
    return str(models[-1]) if models else None


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class ExportSettings:
    output: Path                              # fichier (vidéo) ou fichier modèle de la 1re image (séquence)
    fmt: str = "mp4"                          # mp4, mov, mkv, webm, exr, tiff, png, dpx
    codec: str = "h264"
    crf: int = 18
    preset: str = "medium"
    bitrate_kbps: int = 0
    profile: str = ""
    width: int = 0
    height: int = 0
    fps: Fraction | None = None               # None = cadence de la source
    fps_mode: str = "resample"                # reinterpret, resample, interpolate
    interp: str = "minterpolate"              # minterpolate, blend, rife
    content: str = "display"                  # data, working, display
    depth: str = "half"                       # séquences : half, float, 8, 16, 32f
    alpha: bool = False
    audio: bool = True
    range: tuple[int, int] = (0, 0)           # rangs INCLUS
    numbering: str = "source"                 # source, 1, 1001
    all_layers: bool = False                  # EXR -> EXR : TOUS les calques / parties et métadonnées, tels quels
    overwrite: bool = False
    rife_exe: str = ""
    view: vcolor.ViewState | None = None
    pipeline: vcolor.ColorPipeline | None = None
    missing: str = "black"                    # black, hold

    @property
    def is_video(self) -> bool:
        return self.fmt in VIDEO_CONTAINERS


def output_frame_plan(lo: int, hi: int, fps_in: Fraction, fps_out: Fraction | None, mode: str) -> list[int]:
    """Rangs source montrés par chaque image de sortie (resample : durée gardée ; sinon une par une)."""
    frames = list(range(lo, hi + 1))
    if not fps_out or fps_out == fps_in or mode != "resample":
        return frames
    count = len(frames)
    out_count = max(1, int((Fraction(count) * fps_out / fps_in)))
    return [lo + min(count - 1, int(Fraction(k) * fps_in / fps_out)) for k in range(out_count)]


class ExportJob(QObject):
    """Une tâche d'export. Signaux : progress(fait, total, images/s, secondes restantes ou -1, état),
    finished(ok, message, chemin)."""

    progress = Signal(int, int, float, float, str)
    finished = Signal(bool, str, str)

    PAD = 4

    def __init__(self, source: MediaSource, settings: ExportSettings, parent=None):
        super().__init__(parent)
        self._target_frames = 0
        self.source = source
        self.s = settings
        self._cancel = threading.Event()
        self._thread = None
        self._proc = None
        self.started_at = 0.0

    def start(self):
        self.started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="video-export", daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancel.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    def wait(self, timeout: float = 30.0):
        if self._thread is not None:
            self._thread.join(timeout)

    def thread_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- commun --

    def _emit_progress(self, done: int, total: int, state: str):
        elapsed = max(1e-6, time.monotonic() - self.started_at)
        speed = done / elapsed
        eta = (total - done) / speed if speed > 0 and done else -1.0
        try:
            self.progress.emit(done, total, speed, eta, state)
        except RuntimeError:
            pass

    def _finish(self, ok: bool, message: str, path: str = ""):
        try:
            self.finished.emit(ok, message, path)
        except RuntimeError:
            pass

    def _pixels(self, frame: Frame, previous):
        """Pixels d'une image à écrire selon le contenu choisi : (float32 H x W x C, alpha ou None)."""
        if frame.pixels is None:                              # image manquante
            if self.s.missing == "hold" and previous is not None:
                return previous
            h, w = self.source.height, self.source.width
            return np.zeros((h, w, 3), np.float32), None
        if self.s.content == "data":
            rgb, alpha = vcolor.to_rgb_alpha(frame.pixels)
            return rgb, alpha
        view = self.s.view or vcolor.ViewState(dict(vcolor.DEFAULT_GRADE))
        return vcolor.process_np(frame.pixels, self.s.pipeline, view,
                                 stage="working" if self.s.content == "working" else "display")

    def _run(self):
        try:
            if self.s.is_video:
                self._run_video()
            else:
                self._run_sequence()
        except Exception as exc:                              # noqa: BLE001 - message, jamais de plantage
            self._finish(False, f"Échec de l'export : {type(exc).__name__}: {exc}")
        finally:
            try:
                self.source.close()
            except Exception:                                 # noqa: BLE001
                pass

    # -- séquences d'images --

    def _sequence_path(self, k: int, number: int) -> Path:
        out = Path(self.s.output)
        stem = out.stem
        # « nom.1001.exr » / « nom.####.exr » donnés comme modèle : la tête seule est gardée.
        head = stem.rstrip("#").rstrip("0123456789").rstrip(".") or stem
        start = {"1": 1, "1001": 1001}.get(self.s.numbering)
        n = (start + k) if start is not None else number
        return out.with_name(f"{head}.{n:04d}{SEQUENCE_FORMATS[self.s.fmt]}")

    def _run_sequence(self):
        import OpenImageIO as oiio
        lo, hi = self.s.range
        plan = output_frame_plan(lo, hi, self.source.fps, self.s.fps, self.s.fps_mode)
        total = len(plan)
        paths = [self._sequence_path(k, self.source.number_of(i)) for k, i in enumerate(plan)]
        if not self.s.overwrite:
            existing = [p for p in paths if p.exists()]
            if existing:
                self._finish(False, f"{len(existing)} fichier(s) existent déjà (ex. {existing[0].name}). "
                                    "Cochez « Écraser » ou changez le nom.")
                return
        Path(self.s.output).parent.mkdir(parents=True, exist_ok=True)
        if self.s.all_layers:
            self._copy_all_layers(plan, paths)
            return
        fmt = self.s.fmt
        depth = self.s.depth
        type_desc = {"half": oiio.HALF, "float": oiio.FLOAT, "32f": oiio.FLOAT, "16": oiio.UINT16,
                     "8": oiio.UINT8, "10": oiio.UINT16}.get(depth, oiio.HALF)
        if fmt == "png" and type_desc not in (oiio.UINT8, oiio.UINT16):
            type_desc = oiio.UINT16
        if fmt == "exr" and type_desc not in (oiio.HALF, oiio.FLOAT):
            type_desc = oiio.HALF
        written = []
        previous = None
        last_index, last_pixels = None, None
        for k, index in enumerate(plan):
            if self._cancel.is_set():
                self._finish(False, f"Export annulé ({k} / {total} images écrites, gardées).")
                return
            if index == last_index:
                rgb, alpha = last_pixels
            else:
                frame = self.source.read(index)
                rgb, alpha = self._pixels(frame, previous)
                last_index, last_pixels = index, (rgb, alpha)
            previous = (rgb, alpha)
            data = rgb
            if self.s.alpha and alpha is not None:
                data = np.concatenate([rgb, alpha[..., None]], axis=2)
            data = self._resize(data)
            if type_desc in (oiio.UINT8, oiio.UINT16):
                data = np.clip(data, 0.0, 1.0)
            h, w, c = data.shape
            spec = oiio.ImageSpec(w, h, c, type_desc)
            if c == 4:
                spec.alpha_channel = 3
            if fmt == "exr":
                spec.attribute("compression", "zip")
            elif fmt == "tiff":
                spec.attribute("compression", "zip")
            fps = self.s.fps or self.source.fps
            try:
                spec.attribute("FramesPerSecond", oiio.TypeDesc("rational"), (fps.numerator, fps.denominator))
            except Exception:                                 # noqa: BLE001 - métadonnée facultative
                pass
            if self.s.content != "data" and self.s.pipeline is not None:
                space = self.s.pipeline.working if self.s.content == "working" else self.s.pipeline.display
                spec.attribute("oiio:ColorSpace", space)
            path = paths[k]
            out = oiio.ImageOutput.create(str(path))
            if out is None or not out.open(str(path), spec):
                self._finish(False, f"Écriture impossible : {path.name} ({oiio.geterror()})")
                return
            ok = out.write_image(np.ascontiguousarray(data, dtype=np.float32))
            out.close()
            if not ok:
                self._finish(False, f"Écriture impossible : {path.name} ({oiio.geterror()} — disque plein ?)")
                return
            written.append(path)
            self._emit_progress(k + 1, total, "écriture")
        self._finish(True, f"{total} images écrites.", str(paths[0]) if paths else "")

    def _copy_all_layers(self, plan: list[int], paths: list[Path]):
        """Export « tous les calques » (EXR -> EXR) : chaque image recopiée avec TOUTES ses parties (multipart),
        tous ses canaux / AOV dans leur type d'origine (half, float, uint) et toutes ses métadonnées (caméra,
        rendu, timecode…). Aucune transformation (contenu « données ») ; renumérotation et cadence suivent les
        réglages ; image manquante = la précédente recopiée (ou sautée s'il n'y en a pas)."""
        import OpenImageIO as oiio
        total = len(plan)
        previous = None
        for k, index in enumerate(plan):
            if self._cancel.is_set():
                self._finish(False, f"Export annulé ({k} / {total} images écrites, gardées).")
                return
            src = self.source.path_of(index) if hasattr(self.source, "path_of") else None
            src = src or previous
            if src is None:
                continue
            previous = src
            inp = oiio.ImageInput.open(str(src))
            if inp is None:
                self._finish(False, f"Lecture impossible : {Path(src).name} ({oiio.geterror()})")
                return
            try:
                specs = []
                while inp.seek_subimage(len(specs), 0):
                    specs.append(inp.spec())
                fps = self.s.fps or self.source.fps
                for spec in specs:
                    try:
                        spec.attribute("FramesPerSecond", oiio.TypeDesc("rational"),
                                       (fps.numerator, fps.denominator))
                    except Exception:                         # noqa: BLE001 - métadonnée facultative
                        pass
                path = paths[k]
                part = path.with_name(path.stem + ".part" + path.suffix)
                out = oiio.ImageOutput.create(str(part))
                if out is None or not out.open(str(part), specs):
                    self._finish(False, f"Écriture impossible : {path.name} ({oiio.geterror()})")
                    return
                ok = True
                for i, spec in enumerate(specs):
                    if i and not out.open(str(part), spec, "AppendSubimage"):
                        ok = False
                        break
                    inp.seek_subimage(i, 0)
                    data = inp.read_image(i, 0, 0, spec.nchannels, spec.format)
                    ok = ok and data is not None and out.write_image(data)
                out.close()
            finally:
                inp.close()
            if not ok:
                _remove(part)
                self._finish(False, f"Écriture impossible : {path.name} ({oiio.geterror()} — disque plein ?)")
                return
            os.replace(part, path)
            self._emit_progress(k + 1, total, "copie des calques")
        self._finish(True, f"{total} images écrites (tous les calques et métadonnées).",
                     str(paths[0]) if paths else "")

    def _resize(self, data: np.ndarray) -> np.ndarray:
        w, h = self.s.width, self.s.height
        if not w and not h:
            return data
        src_h, src_w = data.shape[:2]
        if not w:
            w = max(1, round(src_w * h / src_h))
        if not h:
            h = max(1, round(src_h * w / src_w))
        if (w, h) == (src_w, src_h):
            return data
        import OpenImageIO as oiio
        buf = oiio.ImageBuf(np.ascontiguousarray(data, dtype=np.float32))
        roi = oiio.ROI(0, w, 0, h, 0, 1, 0, data.shape[2])
        resized = oiio.ImageBufAlgo.resize(buf, roi=roi)
        return resized.get_pixels(oiio.FLOAT)

    # -- vidéos (FFmpeg) --

    def _video_command(self, width: int, height: int, in_fps: Fraction, out_path: Path, alpha: bool) -> list[str]:
        s = self.s
        exe = ffmpeg_path()
        pix_in = "rgba64le" if alpha else "rgb48le"
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", pix_in,
               "-s", f"{width}x{height}", "-framerate", f"{in_fps.numerator}/{in_fps.denominator}", "-i", "pipe:0"]
        audio = s.audio and self.source.kind == "video" and getattr(self.source, "has_audio", False) \
            and s.fps_mode != "reinterpret"
        if audio:
            lo, hi = s.range
            t0 = float(Fraction(lo) / self.source.fps)
            dur = float(Fraction(hi - lo + 1) / self.source.fps)
            cmd += ["-ss", f"{t0:.6f}", "-t", f"{dur:.6f}", "-i", str(self.source.path)]
        filters = []
        out_fps = s.fps if s.fps else in_fps
        if s.fps and s.fps_mode == "interpolate" and s.interp in ("minterpolate", "blend") and out_fps != in_fps:
            rate = f"{out_fps.numerator}/{out_fps.denominator}"
            if s.interp == "blend":
                filters.append(f"minterpolate=fps={rate}:mi_mode=blend")
            else:
                filters.append(f"minterpolate=fps={rate}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1:scd=fdiff")
        tw, th = s.width, s.height
        if tw or th:
            filters.append(f"scale={tw or -2}:{th or -2}:flags=lanczos")
        encoder, _containers = CODECS[s.codec]
        pix_out, extra = self._codec_args(alpha)
        filters.append(f"scale=out_color_matrix=bt709:out_range=tv,format={pix_out}" if not pix_out.startswith(
            ("rgb", "gbr")) else f"format={pix_out}")
        cmd += ["-vf", ",".join(filters), "-map", "0:v:0"]
        if audio:
            cmd += ["-map", "1:a:0?"]
        cmd += ["-c:v", encoder, *extra, "-colorspace", "bt709", "-color_primaries", "bt709",
                "-color_trc", "bt709", "-color_range", "tv"]
        if out_fps != in_fps and not (s.fps_mode == "interpolate" and s.interp in ("minterpolate", "blend")):
            cmd += ["-r", f"{out_fps.numerator}/{out_fps.denominator}"]
        if self._target_frames:
            cmd += ["-frames:v", str(self._target_frames)]
        if audio:
            cmd += ["-c:a", "aac" if s.fmt in ("mp4", "mov", "mkv") else "libopus", "-b:a", "192k", "-shortest"]
        if s.fmt in ("mp4", "mov"):
            cmd += ["-movflags", "+faststart"]
            if s.codec == "h265":
                cmd += ["-tag:v", "hvc1"]
        cmd += ["-f", {"mkv": "matroska"}.get(s.fmt, s.fmt), str(out_path)]
        return cmd

    def _codec_args(self, alpha: bool):
        s = self.s
        if s.codec == "h264":
            args = ["-preset", s.preset or "medium"]
            args += ["-b:v", f"{s.bitrate_kbps}k"] if s.bitrate_kbps else ["-crf", str(s.crf)]
            return "yuv420p", args
        if s.codec == "h265":
            args = ["-preset", s.preset or "medium", "-x265-params", "log-level=error"]
            args += ["-b:v", f"{s.bitrate_kbps}k"] if s.bitrate_kbps else ["-crf", str(s.crf)]
            return "yuv420p10le", args
        if s.codec == "prores":
            profile = s.profile if s.profile in dict(PRORES_PROFILES) else "3"
            four = profile in ("4", "5")
            pix = ("yuva444p10le" if alpha else "yuv444p10le") if four else "yuv422p10le"
            return pix, ["-profile:v", profile, "-vendor", "apl0"]
        if s.codec == "dnxhr":
            profile = s.profile if s.profile in dict(DNXHR_PROFILES) else "dnxhr_hq"
            pix = {"dnxhr_hqx": "yuv422p10le", "dnxhr_444": "yuv444p10le"}.get(profile, "yuv422p")
            return pix, ["-profile:v", profile]
        if s.codec == "av1":
            preset = s.preset if s.preset.isdigit() else "8"
            args = ["-preset", preset]
            args += ["-b:v", f"{s.bitrate_kbps}k"] if s.bitrate_kbps else ["-crf", str(min(63, s.crf + 10))]
            return "yuv420p10le", args
        if s.codec == "vp9":
            args = ["-b:v", f"{s.bitrate_kbps}k"] if s.bitrate_kbps else ["-crf", str(min(63, s.crf + 13)), "-b:v", "0"]
            return ("yuva420p" if alpha else "yuv420p"), args + ["-row-mt", "1"]
        raise ValueError(f"codec inconnu : {s.codec}")

    def _run_video(self):
        s = self.s
        if not ffmpeg_path():
            self._finish(False, "FFmpeg introuvable (installez-le ou réglez FFMPEG_EXECUTABLE).")
            return
        encoder = CODECS[s.codec][0]
        if encoder not in available_encoders():
            self._finish(False, f"Encodeur {encoder} absent de ce FFmpeg.")
            return
        out = Path(s.output).with_suffix(VIDEO_CONTAINERS[s.fmt])
        if out.exists() and not s.overwrite:
            self._finish(False, f"{out.name} existe déjà. Cochez « Écraser » ou changez le nom.")
            return
        out.parent.mkdir(parents=True, exist_ok=True)
        lo, hi = s.range
        in_fps = self.source.fps
        if s.fps and s.fps_mode == "reinterpret":
            in_fps = s.fps
        plan = output_frame_plan(lo, hi, self.source.fps, s.fps, s.fps_mode)
        if s.fps and s.fps_mode == "resample":
            in_fps = s.fps                               # images déjà à la cadence de sortie
        if s.fps and s.fps_mode == "interpolate" and s.interp == "rife":
            self._run_rife(out, plan)
            return
        # Interpolation FFmpeg : durée gardée EXACTEMENT (n × sortie / entrée images) ; minterpolate perd les
        # dernières images : la dernière est répétée (PAD) puis la sortie est coupée au bon nombre.
        self._target_frames = 0
        if s.fps and s.fps_mode == "interpolate" and s.fps != self.source.fps:
            self._target_frames = max(1, round(Fraction(len(plan)) * s.fps / self.source.fps))
            plan = plan + [plan[-1]] * self.PAD
        first = self.source.read(plan[0])
        rgb, alpha = self._pixels(first, None)
        height, width = rgb.shape[:2]
        width -= width % 2
        height -= height % 2
        use_alpha = bool(s.alpha and alpha is not None and (s.codec in ("prores", "vp9")))
        part = out.with_name(out.stem + ".part" + out.suffix)
        cmd = self._video_command(width, height, in_fps, part, use_alpha)
        log = tempfile.TemporaryFile()
        self._proc = proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log, creationflags=_NO_WINDOW)
        total = len(plan)
        ok = True
        previous = (rgb, alpha)
        cached_index, cached = plan[0], (rgb, alpha)
        try:
            for k, index in enumerate(plan):
                if self._cancel.is_set():
                    ok = False
                    break
                if index != cached_index:
                    frame = self.source.read(index)
                    cached = self._pixels(frame, previous)
                    cached_index = index
                previous = cached
                rgb, alpha = cached
                data = rgb[:height, :width]
                if use_alpha:
                    a = alpha[:height, :width, None] if alpha is not None else np.ones((height, width, 1), np.float32)
                    data = np.concatenate([data, a], axis=2)
                buf = (np.clip(data, 0.0, 1.0) * 65535.0 + 0.5).astype("<u2")
                try:
                    proc.stdin.write(buf.tobytes())
                except (BrokenPipeError, OSError):
                    ok = False
                    break
                self._emit_progress(k + 1, total, "encodage")
            try:
                proc.stdin.close()
            except OSError:
                pass
            code = proc.wait()
        finally:
            self._proc = None
        if self._cancel.is_set():
            _remove(part)
            log.close()
            self._finish(False, "Export annulé (fichier temporaire supprimé).")
            return
        if not ok or code != 0:
            log.seek(0)
            tail = log.read().decode("utf-8", "replace").strip().splitlines()[-6:]
            log.close()
            _remove(part)
            self._finish(False, "FFmpeg a échoué : " + (" | ".join(tail) or f"code {code}"))
            return
        log.close()
        os.replace(part, out)
        count = self._target_frames or total
        self._finish(True, f"{count} images encodées ({s.codec}).", str(out))

    def _run_rife(self, out: Path, plan: list[int]):
        """RIFE (rife-ncnn-vulkan) : images de la plage écrites en PNG 16 bits dans un dossier temporaire, RIFE
        calcule le nombre d'images voulu (durée gardée), FFmpeg encode. Dossier temporaire supprimé à la fin."""
        s = self.s
        exe = rife_path(s.rife_exe)
        if not exe:
            self._finish(False, "RIFE (rife-ncnn-vulkan) n'est pas installé : choisissez l'interpolation FFmpeg.")
            return
        tmp = Path(tempfile.mkdtemp(prefix="pipe_rife_"))
        try:
            import OpenImageIO as oiio
            src_dir, dst_dir = tmp / "in", tmp / "out"
            src_dir.mkdir()
            dst_dir.mkdir()
            total = len(plan)
            for k, index in enumerate(plan):
                if self._cancel.is_set():
                    self._finish(False, "Export annulé.")
                    return
                rgb, _alpha = self._pixels(self.source.read(index), None)
                buf = oiio.ImageBuf(np.ascontiguousarray(np.clip(rgb, 0, 1), np.float32))
                buf.write(str(src_dir / f"{k + 1:08d}.png"), oiio.UINT8)
                self._emit_progress(k + 1, total * 2, "préparation RIFE")
            target = int(Fraction(total) * s.fps / self.source.fps)
            model = rife_model(exe)
            if model is None:
                self._finish(False, "RIFE : aucun modèle v4 trouvé à côté de rife-ncnn-vulkan (dossier rife-v4…).")
                return
            cmd = [exe, "-i", str(src_dir), "-o", str(dst_dir), "-n", str(target), "-m", model, "-f", "%08d.png"]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                          creationflags=_NO_WINDOW, cwd=str(Path(exe).parent))
            _out, err = self._proc.communicate()
            code = self._proc.returncode
            self._proc = None
            if self._cancel.is_set():
                self._finish(False, "Export annulé.")
                return
            if code != 0:
                self._finish(False, "RIFE a échoué : " + err.decode("utf-8", "replace")[-300:])
                return
            self._emit_progress(total * 2 - 1, total * 2, "encodage")
            rate = f"{s.fps.numerator}/{s.fps.denominator}"
            encoder, _c = CODECS[s.codec]
            pix, extra = self._codec_args(False)
            part = out.with_name(out.stem + ".part" + out.suffix)
            cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-framerate", rate,
                   "-i", str(dst_dir / "%08d.png"), "-vf", f"scale=out_color_matrix=bt709:out_range=tv,format={pix}",
                   "-c:v", encoder, *extra, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc",
                   "bt709", str(part)]
            result = subprocess.run(cmd, capture_output=True, creationflags=_NO_WINDOW)
            if result.returncode != 0:
                _remove(part)
                self._finish(False, "FFmpeg a échoué : " + result.stderr.decode("utf-8", "replace")[-300:])
                return
            os.replace(part, out)
            self._emit_progress(total * 2, total * 2, "terminé")
            self._finish(True, f"{target} images (RIFE) encodées.", str(out))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _remove(path: Path):
    try:
        Path(path).unlink()
    except OSError:
        pass
