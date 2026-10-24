"""Médias du module vidéo : détection des séquences d'images, sources d'images (vidéo PyAV, séquence / image
OpenImageIO), informations techniques.

Une SOURCE donne des images par RANG (0 … frame_count - 1) : `read(rang)` -> `Frame` (tableau numpy H x W x C,
type d'origine : uint8, uint16, float16, float32 — jamais converti en 8 bits). Elle n'est pas partagée entre fils :
le chargeur (`cache.FrameLoader`) en ouvre une par fil (`clone()`).

Vidéo : rang -> horodatage RÉEL de l'image (index des paquets, construit en fond par `build_index` : cadence
variable comprise) ; aller à une image = saut à l'image clé d'avant puis décodage jusqu'à elle (jamais une
approximation en secondes). Lecture vers l'avant : le décodage continue sans saut."""
from __future__ import annotations

import bisect
import math
import os
import re
import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np

from video import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

# Nombre d'images que la lecture vers l'avant décode sans saut (au-delà : saut à l'image clé d'avant).
FORWARD_DECODE_LIMIT = 150

_FRAME_RE = re.compile(r"^(?P<head>.*?)(?P<num>-?\d+)(?P<tail>\.[^.]+)$")


# ==========================================================================
# Séquences
# ==========================================================================

@dataclass
class Sequence:
    """Séquence d'images : `head` + numéro (sur `padding` chiffres, 0 = sans remplissage) + `tail`."""
    directory: Path
    head: str
    tail: str
    padding: int
    numbers: list[int]                       # numéros PRÉSENTS, triés

    @property
    def first(self) -> int:
        return self.numbers[0]

    @property
    def last(self) -> int:
        return self.numbers[-1]

    @property
    def length(self) -> int:
        """Images de la PLAGE (manquantes comprises) : c'est la timeline."""
        return self.last - self.first + 1

    def missing(self) -> list[int]:
        present = set(self.numbers)
        return [n for n in range(self.first, self.last + 1) if n not in present]

    def path_for(self, number: int) -> Path:
        text = f"{abs(number):0{self.padding}d}" if self.padding else str(abs(number))
        return self.directory / f"{self.head}{'-' if number < 0 else ''}{text}{self.tail}"

    def has(self, number: int) -> bool:
        index = bisect.bisect_left(self.numbers, number)
        return index < len(self.numbers) and self.numbers[index] == number

    @property
    def pattern(self) -> str:
        hashes = "#" * (self.padding or len(str(abs(self.first))))
        return f"{self.head}{hashes}{self.tail}"


def split_frame_name(name: str):
    """(tête, numéro en texte, extension) d'un nom de fichier numéroté, sinon None. Le numéro est le DERNIER
    groupe de chiffres juste avant l'extension (« smoke_v003.1001.tif » -> 1001, la version reste dans la tête)."""
    match = _FRAME_RE.match(name)
    if match is None:
        return None
    num = match.group("num")
    head = match.group("head")
    if num.startswith("-") and head and head[-1].isalnum():     # « shot-12 » : le tiret est un séparateur
        head, num = head + "-", num[1:]
    return head, num, match.group("tail")


def find_sequence(path, min_length: int = 2) -> Sequence | None:
    """Séquence à laquelle appartient `path` (fichier d'images numéroté), en UNE lecture du dossier ; None si le
    fichier est seul (ou si moins de `min_length` images). Plusieurs séquences dans un dossier : seules celles de
    même tête, même extension et même remplissage que `path` sont réunies."""
    path = Path(path)
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    parts = split_frame_name(path.name)
    if parts is None:
        return None
    head, num, tail = parts
    padded = len(num.lstrip("-")) > 1 and num.lstrip("-").startswith("0")
    width = len(num.lstrip("-"))
    numbers = []
    tail_low = tail.lower()
    try:
        with os.scandir(path.parent) as entries:
            for entry in entries:
                name = entry.name
                if not name.startswith(head) or not name.lower().endswith(tail_low):
                    continue
                middle = name[len(head):len(name) - len(tail)]
                digits = middle[1:] if middle.startswith("-") else middle
                if not digits.isdigit():
                    continue
                # Remplissage : un numéro rempli de zéros n'appartient qu'aux numéros de même largeur ; les numéros
                # plus longs (1000 après 0999) sont acceptés.
                if padded and len(digits) < width:
                    continue
                if not padded and digits.startswith("0") and len(digits) > 1:
                    continue
                numbers.append(-int(digits) if middle.startswith("-") else int(digits))
    except OSError:
        return None
    if len(numbers) < max(1, min_length):
        return None
    numbers.sort()
    return Sequence(path.parent, head, tail, width if padded else 0, numbers)


def list_sequences(directory) -> list[Sequence]:
    """Toutes les séquences d'un dossier (au moins 2 images), dans l'ordre des noms."""
    groups: dict[tuple, list[int]] = {}
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if Path(entry.name).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                parts = split_frame_name(entry.name)
                if parts is None:
                    continue
                head, num, tail = parts
                digits = num.lstrip("-")
                padding = len(digits) if len(digits) > 1 and digits.startswith("0") else 0
                groups.setdefault((head, tail, padding), []).append(int(num))
    except OSError:
        return []
    out = []
    for (head, tail, padding), numbers in sorted(groups.items()):
        if len(numbers) >= 2:
            numbers.sort()
            out.append(Sequence(Path(directory), head, tail, padding, numbers))
    return out


# ==========================================================================
# Images
# ==========================================================================

class YuvImage:
    """Image YUV planaire telle que décodée (aucune conversion sur le CPU) : la conversion en RVB se fait dans le
    shader (`viewer`), avec la matrice et la plage du fichier. `planes` : Y, U, V (tableaux 2D, lignes éventuellement
    plus larges que l'image : `row_lengths`). `bits` : profondeur (8, 10, 12) ; entiers 8 bits = uint8, sinon uint16.
    `chroma_shift` : décalage horizontal des chromas (en fraction de leur texel) quand ils sont alignés à gauche
    (H.264 / HEVC en 4:2:0 et 4:2:2), au lieu d'être centrés."""
    __slots__ = ("planes", "width", "height", "sx", "sy", "bits", "kr", "kb", "full_range", "chroma_shift", "keep")

    def __init__(self, planes, width, height, sx, sy, bits, kr, kb, full_range, chroma_shift=0.0, keep=None):
        self.planes = planes
        self.width, self.height = int(width), int(height)
        self.sx, self.sy = int(sx), int(sy)
        self.bits = int(bits)
        self.kr, self.kb = float(kr), float(kb)
        self.full_range = bool(full_range)
        self.chroma_shift = float(chroma_shift)
        self.keep = keep                     # objet qui possède la mémoire (image PyAV), gardé en vie

    @property
    def nbytes(self) -> int:
        return int(sum(p.nbytes for p in self.planes))

    def plane_size(self, i: int) -> tuple[int, int]:
        if i == 0:
            return self.width, self.height
        return -(-self.width // self.sx), -(-self.height // self.sy)

    def levels(self):
        """(code max, Y : décalage, échelle, chroma : décalage, échelle) en VALEURS DE CODE (8 bits : 0-255)."""
        n = self.bits
        top = float((1 << n) - 1)
        if self.full_range:
            return top, 0.0, top, float(1 << (n - 1)), top
        m = float(1 << (n - 8))
        return top, 16.0 * m, 219.0 * m, 128.0 * m, 224.0 * m

    def _rgb_float(self, y, u, v):
        _top, ya, yb, ca, cb = self.levels()
        y = (y - ya) / yb
        u = (u - ca) / cb
        v = (v - ca) / cb
        kr, kb = self.kr, self.kb
        kg = 1.0 - kr - kb
        r = y + 2.0 * (1.0 - kr) * v
        b = y + 2.0 * (1.0 - kb) * u
        g = (y - kr * r - kb * b) / kg
        return r, g, b

    def to_rgb(self) -> np.ndarray:
        """RVB (H x W x 3) uint8 ou uint16, pour ce qui lit des pixels sur le CPU (repli CPU, analyse)."""
        w, h = self.width, self.height
        y = self.planes[0][:h, :w].astype(np.float32)
        cw, ch = self.plane_size(1)
        u = self.planes[1][:ch, :cw].astype(np.float32)
        v = self.planes[2][:ch, :cw].astype(np.float32)
        if self.sx > 1 or self.sy > 1:
            u = np.repeat(np.repeat(u, self.sy, 0), self.sx, 1)[:h, :w]
            v = np.repeat(np.repeat(v, self.sy, 0), self.sx, 1)[:h, :w]
        r, g, b = self._rgb_float(y, u, v)
        rgb = np.clip(np.stack((r, g, b), -1), 0.0, 1.0)
        if self.bits <= 8:
            return (rgb * 255.0 + 0.5).astype(np.uint8)
        return (rgb * 65535.0 + 0.5).astype(np.uint16)

    def value_at(self, x: int, y: int):
        """RVB d'UN pixel (même échelle que `to_rgb`), sans convertir toute l'image."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        yy = float(self.planes[0][y, x])
        u = float(self.planes[1][y // self.sy, x // self.sx])
        v = float(self.planes[2][y // self.sy, x // self.sx])
        rgb = [min(1.0, max(0.0, c)) for c in self._rgb_float(yy, u, v)]
        scale = 255.0 if self.bits <= 8 else 65535.0
        return np.array([int(c * scale + 0.5) for c in rgb], np.uint8 if self.bits <= 8 else np.uint16)


class Frame:
    """Une image décodée. `pixels` : H x W x C (C = 1 à 4), type d'origine ; une image vidéo affichée arrive en
    `yuv` (`YuvImage`) et `pixels` n'est alors calculé qu'à la demande. `number` : numéro affiché (rang pour une
    vidéo, numéro de fichier pour une séquence). `missing` : image absente de la séquence (pixels = None)."""

    def __init__(self, index: int, pixels: np.ndarray | None = None, number: int = 0, missing: bool = False,
                 pts: int | None = None, yuv: YuvImage | None = None):
        self.index = index
        self._pixels = pixels
        self.number = number
        self.missing = missing
        self.pts = pts
        self.yuv = yuv

    @property
    def pixels(self) -> np.ndarray | None:
        if self._pixels is None and self.yuv is not None:
            self._pixels = self.yuv.to_rgb()
        return self._pixels

    @pixels.setter
    def pixels(self, value):
        self._pixels = value

    @property
    def has_image(self) -> bool:
        return self._pixels is not None or self.yuv is not None

    def value_at(self, x: int, y: int):
        if self.yuv is not None and self._pixels is None:
            return self.yuv.value_at(x, y)
        px = self._pixels
        if px is None or not (0 <= y < px.shape[0] and 0 <= x < px.shape[1]):
            return None
        return px[y, x]

    @property
    def nbytes(self) -> int:
        if self.yuv is not None:
            return self.yuv.nbytes + (0 if self._pixels is None else int(self._pixels.nbytes))
        return 0 if self._pixels is None else int(self._pixels.nbytes)

    @property
    def size(self) -> tuple[int, int]:
        if self.yuv is not None:
            return self.yuv.width, self.yuv.height
        if self._pixels is None:
            return (0, 0)
        return int(self._pixels.shape[1]), int(self._pixels.shape[0])

    @property
    def channels(self) -> int:
        if self.yuv is not None:
            return 3
        if self._pixels is None:
            return 0
        return 1 if self._pixels.ndim == 2 else int(self._pixels.shape[2])


def yuv_coefficients(colorspace: int | None, height: int) -> tuple[float, float]:
    """(Kr, Kb) de la matrice YUV (codes FFmpeg) ; non précisée = BT.709 en HD, BT.601 en SD (comme VLC / FFmpeg)."""
    space = colorspace or 2
    if space in (2, 0):
        space = 1 if height >= 720 else 5
    return {1: (0.2126, 0.0722), 5: (0.299, 0.114), 6: (0.299, 0.114), 7: (0.212, 0.087),
            9: (0.2627, 0.0593), 10: (0.2627, 0.0593), 4: (0.30, 0.11)}.get(space, (0.2126, 0.0722))


# Formats planaires envoyés tels quels au GPU : nom -> (sous-échantillonnage x, y, bits, plage pleine forcée).
YUV_FORMATS = {"yuv420p": (2, 2, 8, False), "yuvj420p": (2, 2, 8, True), "yuv422p": (2, 1, 8, False),
               "yuvj422p": (2, 1, 8, True), "yuv444p": (1, 1, 8, False), "yuvj444p": (1, 1, 8, True),
               "yuv420p10le": (2, 2, 10, False), "yuv422p10le": (2, 1, 10, False), "yuv444p10le": (1, 1, 10, False),
               "yuv420p12le": (2, 2, 12, False), "yuv422p12le": (2, 1, 12, False), "yuv444p12le": (1, 1, 12, False)}


def normalized(pixels: np.ndarray) -> np.ndarray:
    """Pixels en float32 0-1 (entiers) ou tels quels (flottants) : base des calculs CPU (export, analyse)."""
    if pixels.dtype == np.uint8:
        return pixels.astype(np.float32) / 255.0
    if pixels.dtype == np.uint16:
        return pixels.astype(np.float32) / 65535.0
    return pixels.astype(np.float32, copy=False)


def format_timecode(index: int, fps: Fraction, start: int = 0) -> str:
    """Timecode HH:MM:SS:FF (sans drop-frame : cadence arrondie, comme les lecteurs pour 23,976 / 29,97)."""
    rate = max(1, round(float(fps))) if fps else 24
    total = max(0, int(index) + int(start))
    frames = total % rate
    seconds = total // rate
    return f"{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}:{frames:02d}"


def parse_timecode(text: str, fps: Fraction) -> int | None:
    """Rang d'un timecode « HH:MM:SS:FF » (ou « ;FF »), None si illisible."""
    parts = re.split(r"[:;]", (text or "").strip())
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    rate = max(1, round(float(fps))) if fps else 24
    h, m, s, f = (int(p) for p in parts)
    return ((h * 60 + m) * 60 + s) * rate + f


def _fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if value < 1024 or unit == "To":
            return f"{value:.0f} {unit}" if unit == "o" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} o"


def _ratio_text(width: int, height: int) -> str:
    if not width or not height:
        return ""
    ratio = Fraction(width, height).limit_denominator(100)
    return f"{width / height:.3f} ({ratio.numerator}:{ratio.denominator})"


def fps_text(fps: Fraction | None) -> str:
    if not fps:
        return ""
    value = float(fps)
    return f"{value:.3f}".rstrip("0").rstrip(".") + (f" ({fps.numerator}/{fps.denominator})"
                                                     if fps.denominator != 1 else "")


# ==========================================================================
# Sources
# ==========================================================================

class MediaError(Exception):
    """Média illisible : message clair pour l'utilisateur."""


class MediaSource:
    """Interface commune des sources. Attributs : `kind` (« video » / « sequence » / « image »), `path`,
    `frame_count`, `fps` (Fraction, cadence de LECTURE), `first_number` (numéro de la 1re image),
    `info` ({catégorie: [(libellé, valeur)]}, seulement ce qui est connu), `layers` (calques / AOV),
    `has_audio`, `width`, `height`."""
    kind = "image"
    has_audio = False
    first_number = 0
    timecode_start = 0

    def __init__(self):
        self.layers: list[str] = [""]
        self.layer = ""
        self.info: dict[str, list[tuple[str, str]]] = {}
        self.width = self.height = 0
        self.fps = Fraction(24)
        self.frame_count = 1

    def read(self, index: int, on_extra=None, yuv: bool = False) -> Frame:
        raise NotImplementedError

    def time_of(self, index: float) -> float:
        """Temps (s) de l'image `index` (cadence de lecture ; les vidéos lisent leurs horodatages réels)."""
        return float(index) / float(self.fps or 24)

    def index_at_time(self, seconds: float) -> float:
        return float(seconds) * float(self.fps or 24)

    def clone(self) -> "MediaSource":
        raise NotImplementedError

    def number_of(self, index: int) -> int:
        return self.first_number + int(index)

    def close(self):
        pass


class VideoSource(MediaSource):
    kind = "video"
    extra_window = 1 << 30          # images converties avant la cible quand on recule (le chargeur la borne)

    def __init__(self, path, fps_override: Fraction | None = None, _index=None):
        super().__init__()
        import av
        self.path = Path(path)
        try:
            self._container = av.open(str(self.path))
        except Exception as exc:                            # noqa: BLE001
            raise MediaError(f"Vidéo illisible : {exc}") from exc
        if not self._container.streams.video:
            self._container.close()
            raise MediaError("Aucune piste vidéo dans ce fichier.")
        self._stream = stream = self._container.streams.video[0]
        stream.thread_type = "AUTO"
        ctx = stream.codec_context
        self.time_base = stream.time_base or Fraction(1, 90000)
        self.source_fps = stream.average_rate or stream.guessed_rate or stream.base_rate or Fraction(24)
        self.fps = Fraction(fps_override) if fps_override else Fraction(self.source_fps)
        self.width, self.height = int(ctx.width or 0), int(ctx.height or 0)
        self.has_audio = bool(self._container.streams.audio)
        self._start = stream.start_time if stream.start_time is not None else 0
        self.pix_fmt = ctx.pix_fmt or ""
        self._index = _index if _index is not None else _SharedIndex()
        duration = None
        if stream.duration:
            duration = float(stream.duration * self.time_base)
        elif self._container.duration:
            duration = self._container.duration / 1_000_000
        count = int(stream.frames or 0)
        if not count and duration:
            count = int(round(duration * float(self.source_fps)))
        self.frame_count = max(1, self._index.count or count)
        self.duration = duration
        tc = stream.metadata.get("timecode") or self._container.metadata.get("timecode")
        self.timecode_text = tc or ""
        if tc:
            start = parse_timecode(tc, self.source_fps)
            self.timecode_start = start or 0
        self._gen = None
        self._pushed = None
        self._last_index = None
        self._last_pts = None
        # Emplacement des chromas : seul MJPEG / MPEG-1 les centre ; tout le reste (H.264, HEVC, ProRes…) à gauche.
        self._chroma_left = ctx.name not in ("mjpeg", "mpeg1video", "jpeg2000")
        self.index_gate = threading.Event()              # fermé : la construction de l'index attend (lecture VLC)
        self.index_gate.set()
        self._build_info()

    # -- index des images (horodatages réels) --

    def build_index(self, cancel: threading.Event | None = None) -> bool:
        """Lit les paquets (sans décoder) : horodatages de TOUTES les images, triés = ordre d'affichage. Partagé
        par les clones. Quelques dixièmes de seconde pour plusieurs minutes de vidéo."""
        if self._index.ready:
            return True
        import av
        try:
            container = av.open(str(self.path))
        except Exception:                                    # noqa: BLE001
            return False
        try:
            stream = container.streams.video[0]
            pts, keys = [], []
            for packet in container.demux(stream):
                if cancel is not None and cancel.is_set():
                    return False
                if not self.index_gate.is_set():
                    # Lecture en cours (VLC) : on n'ajoute aucune lecture du fichier (réseau, gros MKV).
                    while not self.index_gate.wait(0.25):
                        if cancel is not None and cancel.is_set():
                            return False
                if packet.pts is None or packet.size == 0:
                    continue
                pts.append(packet.pts)
                if packet.is_keyframe:
                    keys.append(packet.pts)
            pts.sort()
            keys.sort()
            self._index.set(pts, keys)
            if pts:
                self.frame_count = len(pts)
            return True
        except Exception:                                    # noqa: BLE001
            return False
        finally:
            container.close()

    @property
    def index_ready(self) -> bool:
        return self._index.ready

    def pts_of(self, index: int) -> int:
        if self._index.ready and self._index.pts:
            index = max(0, min(index, len(self._index.pts) - 1))
            return self._index.pts[index]
        return int(self._start + round(index / float(self.source_fps) / float(self.time_base)))

    def time_of(self, index: float) -> float:
        """Temps (s) de l'image `index` depuis le début du flux : horodatage réel (cadence variable comprise) ;
        un rang fractionnaire est interpolé entre ses deux voisins (graduations de la timeline)."""
        lo = int(math.floor(index))
        t0 = float((self.pts_of(lo) - self._start) * self.time_base)
        frac = index - lo
        if frac <= 1e-9:
            return t0
        t1 = float((self.pts_of(lo + 1) - self._start) * self.time_base) if lo + 1 < self.frame_count             else t0 + 1.0 / float(self.source_fps)
        return t0 + (t1 - t0) * frac

    def index_at_time(self, seconds: float) -> float:
        """Rang (fractionnaire) au temps `seconds` : inverse de `time_of`."""
        if self._index.ready and self._index.pts:
            pts = self._start + seconds / float(self.time_base)
            values = self._index.pts
            i = bisect.bisect_right(values, pts) - 1
            if i < 0:
                return 0.0
            if i >= len(values) - 1:
                return float(len(values) - 1)
            span = values[i + 1] - values[i]
            return i + ((pts - values[i]) / span if span else 0.0)
        return seconds * float(self.source_fps)

    def index_of(self, pts: int) -> int:
        if self._index.ready and self._index.pts:
            values = self._index.pts
            i = bisect.bisect_left(values, pts)
            if i >= len(values):
                return len(values) - 1
            if i > 0 and abs(values[i - 1] - pts) < abs(values[i] - pts):
                return i - 1
            return i
        return max(0, int(round((pts - self._start) * float(self.time_base) * float(self.source_fps))))

    # -- décodage --

    def _yuv(self, frame) -> YuvImage | None:
        """Planes YUV de l'image (vues sur la mémoire de PyAV, aucune copie) si son format s'affiche tel quel."""
        spec = YUV_FORMATS.get(frame.format.name)
        if spec is None:
            return None
        sx, sy, bits, full = spec
        dtype = np.uint8 if bits == 8 else np.dtype("<u2")
        planes = []
        for plane in frame.planes:
            item = 1 if bits == 8 else 2
            arr = np.frombuffer(plane, dtype)
            rows = plane.height
            arr = arr[:rows * (plane.line_size // item)].reshape(rows, plane.line_size // item)
            planes.append(arr)
        if len(planes) < 3:
            return None
        kr, kb = yuv_coefficients(getattr(frame, "colorspace", 2), self.height)
        full = full or (getattr(frame, "color_range", 0) or 0) == 2
        # Chromas alignés à gauche (MPEG-2 / H.264 / HEVC, valeur par défaut) en 4:2:0 / 4:2:2.
        shift = 0.0
        if sx == 2 and self._chroma_left:
            shift = 0.25 / max(1, -(-frame.width // 2))
        return YuvImage(planes, frame.width, frame.height, sx, sy, bits, kr, kb, full, shift, keep=frame)

    def _convert(self, frame) -> np.ndarray:
        fmt = frame.format
        try:
            depth = max(c.bits for c in fmt.components)
        except Exception:                                    # noqa: BLE001
            depth = 8
        alpha = fmt.has_alpha if hasattr(fmt, "has_alpha") else ("a" in fmt.name.replace("gray", ""))
        if depth > 8:
            target = "rgba64le" if alpha else "rgb48le"
        else:
            target = "rgba" if alpha else "rgb24"
        kwargs = {"format": target}
        if not fmt.name.startswith(("rgb", "bgr", "gbr", "argb", "abgr", "rgba", "bgra", "gray")):
            # Matrice YUV -> RVB : celle du fichier (BT.709 par défaut en HD, BT.601 en SD), plage d'origine
            # (« vidéo » 16-235 ou « pleine ») ramenée à la pleine plage.
            space = getattr(frame, "colorspace", 2) or 2
            if space in (2, 0):                               # non précisé
                space = 1 if self.height >= 720 else 5
            kwargs["src_colorspace"] = {1: "ITU709", 5: "ITU601", 6: "ITU601", 7: "SMPTE240M", 9: "BT2020",
                                        10: "BT2020"}.get(space, "ITU709")
            rng = getattr(frame, "color_range", 0) or 0
            kwargs["src_color_range"] = "JPEG" if rng == 2 else "MPEG"
            kwargs["dst_color_range"] = "JPEG"
        try:
            return frame.to_ndarray(**kwargs)
        except Exception:                                    # noqa: BLE001 - option refusée : conversion simple
            return frame.to_ndarray(format=target)

    def _seek(self, index: int):
        """Saut AVANT l'image `index`, vérifié : certains conteneurs (AVI, MPEG-PS…) sautent sur l'horodatage de
        DÉCODAGE, et avec des B-frames ils atterrissent APRÈS l'image voulue. Si la 1re image décodée dépasse la
        cible, on ressaute plus tôt (écart doublé à chaque essai), jusqu'au début du fichier : jamais d'image
        approchée. La 1re image décodée est gardée (`_pushed`) pour la boucle de lecture."""
        target = self.pts_of(index)
        seek_to = target
        step = max(1, int(round(1 / float(self.source_fps) / float(self.time_base))))
        for _attempt in range(12):
            if seek_to <= self._start:
                self._container.seek(int(self._start), backward=True, any_frame=False, stream=self._stream)
            else:
                self._container.seek(int(seek_to), backward=True, any_frame=False, stream=self._stream)
            self._gen = self._container.decode(self._stream)
            self._last_index = None
            first = self._next_decoded()
            self._pushed = first
            if first is None or seek_to <= self._start:
                return
            pts = first.pts if first.pts is not None else getattr(first, "dts", None)
            if pts is None or pts <= target:
                return
            step *= 2
            seek_to = target - step * 4
        return

    def _next_decoded(self):
        """Image décodée suivante (paquets corrompus sautés, 50 au plus), None en fin de fichier."""
        errors = 0
        while True:
            try:
                return next(self._gen)
            except StopIteration:
                return None
            except Exception:                                # noqa: BLE001 - paquet corrompu : on continue
                errors += 1
                if errors > 50:
                    raise

    def _make(self, index, frame, pts, yuv: bool) -> Frame:
        if yuv:
            planes = self._yuv(frame)
            if planes is not None:
                return Frame(index, None, number=index, pts=pts, yuv=planes)
        return Frame(index, self._convert(frame), number=index, pts=pts)

    def read(self, index: int, on_extra=None, yuv: bool = False) -> Frame:
        """Image de rang `index`, EXACTE. `on_extra(Frame)` reçoit les images décodées avant elle (depuis l'image
        clé) : le chargeur les garde quand on recule image par image. `yuv` : planes YUV telles que décodées
        (affichage : converties par le shader) au lieu d'un RVB calculé sur le CPU."""
        index = max(0, min(int(index), self.frame_count - 1))
        last = self._last_index
        if self._gen is None or last is None or index <= last or index - last > FORWARD_DECODE_LIMIT:
            self._seek(index)
        target_pts = self.pts_of(index)
        fallback = None
        while True:
            frame = self._pushed if self._pushed is not None else None
            self._pushed = None
            if frame is None:
                try:
                    frame = self._next_decoded()
                except Exception as exc:                     # noqa: BLE001
                    raise MediaError(f"Décodage impossible : {exc}") from exc
            if frame is None:
                self._gen = None
                if fallback is not None:
                    return fallback
                raise MediaError(f"Image {index} introuvable (fin du fichier).")
            pts = frame.pts if frame.pts is not None else getattr(frame, "dts", None)
            if pts is None:
                pts = target_pts
            got = self.index_of(pts)
            self._last_index, self._last_pts = got, pts
            if got < index and pts < target_pts:
                if on_extra is not None and index - got <= self.extra_window:
                    on_extra(self._make(got, frame, pts, yuv))
                continue
            result = self._make(got, frame, pts, yuv)
            if got == index or pts >= target_pts:
                result.index = index
                result.number = index
                return result
            fallback = result

    def thumbnail(self, index: int, height: int) -> np.ndarray:
        """Décode une miniature exacte en réutilisant le flux courant pour les rangs croissants."""
        index = max(0, min(int(index), self.frame_count - 1))
        last = self._last_index
        if self._gen is None or last is None or index <= last or index - last > FORWARD_DECODE_LIMIT:
            self._seek(index)
        target_pts = self.pts_of(index)
        previous = previous_pts = None
        while True:
            frame = self._pushed
            self._pushed = None
            if frame is None:
                try:
                    frame = self._next_decoded()
                except Exception as exc:                     # noqa: BLE001
                    raise MediaError(f"Décodage impossible : {exc}") from exc
            if frame is None:
                frame = previous
                if frame is None:
                    raise MediaError(f"Image {index} introuvable (fin du fichier).")
                break
            pts = frame.pts if frame.pts is not None else getattr(frame, "dts", None)
            if pts is None:
                pts = target_pts
            self._last_index, self._last_pts = self.index_of(pts), pts
            if pts >= target_pts:
                if previous is not None and target_pts - previous_pts <= pts - target_pts:
                    frame = previous
                    pts = previous_pts
                break
            previous, previous_pts = frame, pts
        height = min(max(16, int(height)), int(frame.height))
        width = max(2, int(round(frame.width * height / max(1, frame.height))) // 2 * 2)
        return frame.reformat(width=width, height=height, format="rgb24").to_ndarray()

    def clone(self) -> "VideoSource":
        copy = VideoSource(self.path, fps_override=self.fps if self.fps != self.source_fps else None,
                           _index=self._index)
        copy.frame_count = self.frame_count
        return copy

    def close(self):
        try:
            self._container.close()
        except Exception:                                    # noqa: BLE001
            pass

    def _build_info(self):
        ctx = self._stream.codec_context
        size = self.path.stat().st_size if self.path.exists() else 0
        media = [("Nom", self.path.name), ("Chemin", str(self.path.parent)),
                 ("Format", self._container.format.long_name or self._container.format.name),
                 ("Codec", (ctx.codec.long_name or ctx.name) if ctx.codec else str(ctx.name)),
                 ("Taille", _fmt_size(size))]
        profile = getattr(ctx, "profile", None)
        if profile:
            media.append(("Profil", str(profile)))
        if self.duration:
            media.append(("Durée", f"{self.duration:.3f} s"))
        if ctx.bit_rate:
            media.append(("Débit", f"{ctx.bit_rate / 1e6:.1f} Mb/s"))
        if self.timecode_text:
            media.append(("Timecode de départ", self.timecode_text))
        image = [("Résolution", f"{self.width} × {self.height}"), ("Ratio", _ratio_text(self.width, self.height))]
        sar = self._stream.sample_aspect_ratio or getattr(ctx, "sample_aspect_ratio", None)
        if sar and sar != 1:
            image.append(("Pixel aspect ratio", f"{float(sar):.4f}"))
        if self.pix_fmt:
            image.append(("Format pixel", self.pix_fmt))
            try:
                import av
                fmt = av.VideoFormat(self.pix_fmt)
                image.append(("Profondeur", f"{max(c.bits for c in fmt.components)} bits"))
                image.append(("Canaux", str(len(fmt.components))))
                image.append(("Alpha", "oui" if getattr(fmt, "has_alpha", False) else "non"))
            except Exception:                                # noqa: BLE001
                pass
        for label, attr in (("Espace (matrice)", "colorspace"), ("Primaires", "color_primaries"),
                            ("Transfert", "color_trc"), ("Plage", "color_range")):
            value = getattr(ctx, attr, None)
            if value not in (None, 0, 2) or (attr == "color_range" and value):
                image.append((label, _COLOR_NAMES.get((attr, int(value)), str(value))))
        play = [("FPS source", fps_text(self.source_fps))]
        audio = self._container.streams.audio
        if audio:
            a = audio[0].codec_context
            play.append(("Audio", f"{a.name}, {a.sample_rate} Hz, {getattr(a.layout, 'name', '')}"))
        self.info = {"Média": media, "Image": image, "Lecture": play}


_COLOR_NAMES = {("colorspace", 1): "BT.709", ("colorspace", 5): "BT.601 (PAL)", ("colorspace", 6): "BT.601 (NTSC)",
                ("colorspace", 9): "BT.2020", ("color_primaries", 1): "BT.709", ("color_primaries", 9): "BT.2020",
                ("color_primaries", 12): "P3-D65", ("color_trc", 1): "BT.709", ("color_trc", 13): "sRGB",
                ("color_trc", 16): "PQ (ST 2084)", ("color_trc", 18): "HLG", ("color_trc", 8): "Linéaire",
                ("color_range", 1): "vidéo (16-235)", ("color_range", 2): "pleine (0-255)"}


class _SharedIndex:
    """Index des horodatages partagé entre une source et ses clones (construit une fois, en fond)."""

    def __init__(self):
        self.pts: list[int] = []
        self.keys: list[int] = []
        self.ready = False
        self.count = 0

    def set(self, pts, keys):
        self.pts, self.keys, self.count = pts, keys, len(pts)
        self.ready = True


class ImageSource(MediaSource):
    """Séquence d'images (ou image seule) lue par OpenImageIO ; précision d'origine gardée (half, float, 16 bits).
    Calques / AOV des EXR (et parties des EXR multipart) : `layers`, choisi par `set_layer`."""

    def __init__(self, path, sequence: Sequence | None = None, fps: Fraction | None = None):
        super().__init__()
        import OpenImageIO as oiio      # noqa: F401 - absent : erreur claire plus haut
        self.path = Path(path)
        self.sequence = sequence
        self.kind = "sequence" if sequence is not None else "image"
        self.fps = Fraction(fps) if fps else Fraction(24)
        if sequence is not None:
            self.first_number = sequence.first
            self.frame_count = sequence.length
        else:
            self.first_number = 0
            self.frame_count = 1
        self._channels: dict[str, tuple[int, list[int]]] = {}
        self._probe()

    def _probe(self):
        import OpenImageIO as oiio
        probe = self.path if self.path.exists() else (self.sequence.path_for(self.sequence.first)
                                                      if self.sequence else self.path)
        inp = oiio.ImageInput.open(str(probe))
        if inp is None:
            raise MediaError(f"Image illisible : {oiio.geterror() or probe.name}")
        try:
            specs = []
            sub = 0
            while inp.seek_subimage(sub, 0):
                specs.append(inp.spec())
                sub += 1
            spec = specs[0]
            self.width, self.height = spec.width, spec.height
            self.spec = spec
            for sub, s in enumerate(specs):
                part = s.getattribute("name") or (f"partie {sub}" if len(specs) > 1 else "")
                groups: dict[str, list[tuple[str, int]]] = {}
                for i, name in enumerate(s.channelnames):
                    layer, _dot, chan = name.rpartition(".")
                    groups.setdefault(layer, []).append((chan, i))
                for layer, chans in groups.items():
                    key = "/".join(x for x in (part if len(specs) > 1 else "", layer) if x)
                    self._channels[key] = (sub, _pick_channels(chans))
            names = list(self._channels)
            names.sort(key=lambda n: (n != "", n.lower()))
            self.layers = names or [""]
            self.layer = "" if "" in self._channels else self.layers[0]
            self._build_info(specs, probe)
        finally:
            inp.close()

    def set_layer(self, layer: str):
        if layer in self._channels:
            self.layer = layer

    def path_of(self, index: int) -> Path | None:
        if self.sequence is None:
            return self.path
        number = self.sequence.first + int(index)
        return self.sequence.path_for(number) if self.sequence.has(number) else None

    def number_of(self, index: int) -> int:
        return (self.sequence.first if self.sequence else 0) + int(index)

    def read(self, index: int, on_extra=None, yuv: bool = False) -> Frame:
        import OpenImageIO as oiio
        index = max(0, min(int(index), self.frame_count - 1))
        number = self.number_of(index)
        path = self.path_of(index)
        if path is None:
            return Frame(index, None, number=number, missing=True)
        sub, chans = self._channels.get(self.layer, (0, [0, 1, 2]))
        inp = oiio.ImageInput.open(str(path))
        if inp is None:
            raise MediaError(f"{path.name} : {oiio.geterror()}")
        try:
            if sub:
                inp.seek_subimage(sub, 0)
            spec = inp.spec()
            if chans and chans == list(range(chans[0], chans[-1] + 1)):
                data = inp.read_image(sub, 0, chans[0], chans[-1] + 1, oiio.UNKNOWN)
            else:
                data = inp.read_image(sub, 0, 0, spec.nchannels, oiio.UNKNOWN)
                if data is not None:
                    data = np.ascontiguousarray(data[..., chans])
        finally:
            inp.close()
        if data is None:
            raise MediaError(f"{path.name} : {oiio.geterror() or 'lecture impossible'}")
        if data.ndim == 2:
            data = data[..., None]
        if data.dtype not in (np.uint8, np.uint16, np.float16, np.float32):
            data = data.astype(np.float32)
        return Frame(index, np.ascontiguousarray(data), number=number)

    def clone(self) -> "ImageSource":
        copy = ImageSource.__new__(ImageSource)
        copy.__dict__.update(self.__dict__)
        return copy

    def _build_info(self, specs, probe: Path):
        import OpenImageIO as oiio
        spec = specs[0]
        try:
            size = probe.stat().st_size
        except OSError:
            size = 0
        media = [("Nom", self.sequence.pattern if self.sequence else self.path.name),
                 ("Chemin", str(self.path.parent)), ("Format", spec.getattribute("oiio:Format")
                                                       or probe.suffix.lstrip(".").upper())]
        compression = spec.getattribute("compression")
        if compression:
            media.append(("Compression", str(compression)))
        media.append(("Taille (image)", _fmt_size(size)))
        if self.sequence:
            missing = self.sequence.missing()
            media.append(("Images", f"{len(self.sequence.numbers)} ({self.sequence.first}-{self.sequence.last})"))
            if missing:
                media.append(("Images manquantes", str(len(missing))))
        types = {oiio.UINT8: "8 bits entiers", oiio.UINT16: "16 bits entiers", oiio.HALF: "16 bits flottants (half)",
                 oiio.FLOAT: "32 bits flottants", oiio.UINT32: "32 bits entiers", oiio.DOUBLE: "64 bits flottants"}
        image = [("Résolution", f"{spec.width} × {spec.height}"), ("Ratio", _ratio_text(spec.width, spec.height))]
        par = spec.getattribute("PixelAspectRatio")
        if par and abs(float(par) - 1.0) > 1e-4:
            image.append(("Pixel aspect ratio", f"{float(par):.4f}"))
        image.append(("Profondeur", types.get(spec.format.basetype, str(spec.format))))
        image.append(("Canaux", f"{spec.nchannels} ({', '.join(spec.channelnames[:8])}"
                                f"{'…' if spec.nchannels > 8 else ''})"))
        image.append(("Alpha", "oui" if spec.alpha_channel >= 0 else "non"))
        space = spec.getattribute("oiio:ColorSpace")
        if space:
            image.append(("Espace (métadonnées)", str(space)))
        if spec.getattribute("ICCProfile") is not None:
            image.append(("Profil ICC", "présent"))
        if len(specs) > 1:
            image.append(("Parties (multipart)", str(len(specs))))
        if len(self.layers) > 1:
            image.append(("Calques / AOV", str(len(self.layers))))
        play = []
        meta_fps = spec.getattribute("FramesPerSecond")
        if meta_fps:
            play.append(("FPS (métadonnées)", str(meta_fps)))
        self.info = {"Média": media, "Image": image, "Lecture": play}


def _pick_channels(chans: list[tuple[str, int]]) -> list[int]:
    """Canaux affichés d'un calque : R, G, B (A) dans cet ordre, sinon X, Y, Z, sinon les 4 premiers."""
    by_name = {name.upper(): i for name, i in chans}
    for wanted in (("R", "G", "B", "A"), ("R", "G", "B"), ("X", "Y", "Z"), ("Y", "A"), ("Y",), ("Z",)):
        if all(w in by_name for w in wanted):
            return [by_name[w] for w in wanted]
    return [i for _n, i in chans[:4]]


def open_media(path, settings: dict | None = None) -> MediaSource:
    """Source d'un fichier : vidéo, séquence (le fichier ouvert en fait partie), image seule. MediaError si
    illisible ou si la bibliothèque nécessaire manque."""
    settings = settings or {}
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        try:
            import av  # noqa: F401
        except Exception as exc:                              # noqa: BLE001
            raise MediaError("PyAV n'est pas installé : vidéos illisibles (pip install av).") from exc
        return VideoSource(path)
    if suffix in IMAGE_EXTENSIONS:
        try:
            import OpenImageIO  # noqa: F401
        except Exception as exc:                              # noqa: BLE001
            raise MediaError("OpenImageIO n'est pas installé (pip install OpenImageIO).") from exc
        fps = _parse_fps(settings.get("video_sequence_fps", "24"))
        sequence = find_sequence(path) if settings.get("video_detect_sequences", True) else None
        return ImageSource(path, sequence, fps)
    raise MediaError(f"Format non pris en charge : {suffix or path.name}")


FPS_CHOICES = (("23.976", "23,976"), ("24", "24"), ("25", "25"), ("29.97", "29,97"), ("30", "30"),
               ("48", "48"), ("50", "50"), ("59.94", "59,94"), ("60", "60"), ("120", "120"))


def _parse_fps(value) -> Fraction:
    """Cadence : « 23.976 » / « 29.97 » / « 59.94 » -> 24000/1001… ; autre nombre -> fraction exacte."""
    text = str(value or "24").replace(",", ".").strip()
    exact = {"23.976": Fraction(24000, 1001), "23.98": Fraction(24000, 1001), "29.97": Fraction(30000, 1001),
             "47.952": Fraction(48000, 1001), "59.94": Fraction(60000, 1001), "119.88": Fraction(120000, 1001)}
    if text in exact:
        return exact[text]
    try:
        value = Fraction(text).limit_denominator(1001)
        return value if value > 0 else Fraction(24)
    except (ValueError, ZeroDivisionError):
        return Fraction(24)


parse_fps = _parse_fps
