"""Colorimétrie du module vidéo : pipeline explicite, non destructif, MÊME calcul sur le GPU (shader de
l'affichage) et sur le CPU (export, analyse, repli sans OpenGL).

Ordre des opérations (documenté, une seule fois ici) :
 1. Décodage des pixels source (précision d'origine ; entiers ramenés à 0-1, flottants tels quels, HDR gardé).
 2. LUT « technique » (position « source ») : sur les valeurs encodées du fichier (ex. LUT Log -> Rec.709 d'un
    appareil photo). L'espace d'entrée doit alors être celui de la SORTIE de la LUT.
 3. Interprétation : espace d'entrée (OpenColorIO, choisi — jamais deviné) -> espace de travail = rôle
    `scene_linear` de la configuration (ACEScg pour les configurations ACES intégrées).
 4. Corrections, en linéaire scène : balance des blancs (température / teinte, gains de canaux), exposition (stops),
    offset, lift / gamma / gain par canal (formule ASC CDL : (x × gain + lift) ^ (1 / gamma)), contraste autour d'un
    pivot (en log2 : pivot × (x / pivot) ^ contraste), ombres / hautes lumières / blancs / noirs (gains en stops
    pondérés par la luminance en log2), saturation, vibrance, teinte (rotation autour de l'axe des gris).
 5. Transformation d'affichage : OpenColorIO display / view (ex. « sRGB - Display » / « ACES 2.0 - SDR »).
 6. LUT « créative » (position « affichage ») : sur l'image affichée (LUT écrites pour du Rec.709 / sRGB).
 7. Niveaux d'entrée / sortie et luminosité (espace affiché), vue d'un canal, écrêtage signalé.
 8. Affichage (fond damier / couleur derrière l'alpha), jamais écrit dans les données.

« Avant » (comparaison) = étapes 1, 3, 5, 8 seules : même interprétation et même affichage, sans corrections ni LUT.
Rien ne modifie les fichiers : les réglages vivent à part (réglages de l'appli, presets)."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# ==========================================================================
# Corrections
# ==========================================================================

DEFAULT_GRADE = {
    "exposure": 0.0, "temperature": 0.0, "tint": 0.0,
    "offset": 0.0, "offset_r": 0.0, "offset_g": 0.0, "offset_b": 0.0,
    "lift": 0.0, "lift_r": 0.0, "lift_g": 0.0, "lift_b": 0.0,
    "gamma": 1.0, "gamma_r": 1.0, "gamma_g": 1.0, "gamma_b": 1.0,
    "gain": 1.0, "gain_r": 1.0, "gain_g": 1.0, "gain_b": 1.0,
    "contrast": 1.0, "pivot": 0.18,
    "shadows": 0.0, "highlights": 0.0, "whites": 0.0, "blacks": 0.0,
    "saturation": 1.0, "vibrance": 0.0, "hue": 0.0,
    "brightness": 0.0, "in_black": 0.0, "in_white": 1.0, "out_black": 0.0, "out_white": 1.0,
}

# Poids de luminance de l'espace de travail (AP1 / ACEScg ; Rec.709 proches, écart négligeable pour l'usage).
LUMA_AP1 = (0.2722287, 0.6740818, 0.0536895)
LUMA_709 = (0.2126, 0.7152, 0.0722)


def grade_active(grade: dict) -> bool:
    return any(abs(float(grade.get(k, v)) - v) > 1e-6 for k, v in DEFAULT_GRADE.items())


def _hue_matrix(degrees: float) -> np.ndarray:
    """Rotation de `degrees` autour de l'axe des gris (1, 1, 1) : la luminance des gris ne change pas."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    k = 1.0 / 3.0
    sq = math.sqrt(k)
    return np.array([
        [c + (1 - c) * k, k * (1 - c) - sq * s, k * (1 - c) + sq * s],
        [k * (1 - c) + sq * s, c + k * (1 - c), k * (1 - c) - sq * s],
        [k * (1 - c) - sq * s, k * (1 - c) + sq * s, c + k * (1 - c)],
    ], dtype=np.float32)


def derived(grade: dict, luma=LUMA_AP1) -> dict:
    """Valeurs calculées une fois (partagées par le shader et numpy)."""
    g = {**DEFAULT_GRADE, **{k: float(v) for k, v in (grade or {}).items() if k in DEFAULT_GRADE}}
    # Balance des blancs (approximation linéaire, pas une courbe de corps noir) : température = bleu <-> jaune,
    # teinte = vert <-> magenta ; luminance gardée.
    t, n = g["temperature"] / 100.0, g["tint"] / 100.0
    wb = np.array([1 + 0.3 * t + 0.1 * n, 1 - 0.2 * n, 1 - 0.3 * t + 0.1 * n], dtype=np.float32)
    wb /= float(np.dot(wb, luma))
    gain = np.array([g["gain_r"], g["gain_g"], g["gain_b"]], dtype=np.float32) * g["gain"]
    lift = np.array([g["lift_r"], g["lift_g"], g["lift_b"]], dtype=np.float32) + g["lift"]
    gam = np.array([g["gamma_r"], g["gamma_g"], g["gamma_b"]], dtype=np.float32) * g["gamma"]
    power = 1.0 / np.maximum(gam, 1e-3)
    offset = np.array([g["offset_r"], g["offset_g"], g["offset_b"]], dtype=np.float32) + g["offset"]
    return {"wb": wb * (2.0 ** g["exposure"]), "offset": offset, "slope": gain, "lift": lift, "power": power,
            "contrast": g["contrast"], "pivot": max(1e-4, g["pivot"]),
            "tone": np.array([g["shadows"], g["highlights"], g["whites"], g["blacks"]], dtype=np.float32),
            "sat": g["saturation"], "vib": g["vibrance"], "hue": _hue_matrix(g["hue"]),
            "luma": np.array(luma, dtype=np.float32),
            "levels": np.array([g["in_black"], g["in_white"], g["out_black"], g["out_white"]], dtype=np.float32),
            "bright": g["brightness"]}


def _spow(x, p):
    return np.sign(x) * np.power(np.abs(x), p)


def apply_grade_np(rgb: np.ndarray, d: dict) -> np.ndarray:
    """Étape 4 sur un tableau H x W x 3 float32 (linéaire scène)."""
    x = rgb * d["wb"] + d["offset"]
    x = _spow(x * d["slope"] + d["lift"], d["power"])
    if abs(d["contrast"] - 1.0) > 1e-6:
        p = d["pivot"]
        x = np.where(x > 0, p * np.power(np.maximum(x, 1e-10) / p, d["contrast"]), x)
    tone = d["tone"]
    if np.any(np.abs(tone) > 1e-6):
        lum = np.maximum(np.tensordot(x, d["luma"], axes=([-1], [0])), 1e-6)
        stops = np.log2(lum / 0.18)
        ms = np.clip(-stops / 4.0, 0, 1)
        mh = np.clip(stops / 3.0, 0, 1)
        mb = np.clip((-stops - 3.0) / 3.0, 0, 1)
        mw = np.clip((stops - 1.5) / 2.0, 0, 1)
        gain = np.exp2(tone[0] * ms + tone[1] * mh + tone[2] * mw + tone[3] * mb)
        x = x * gain[..., None]
    lum = np.tensordot(x, d["luma"], axes=([-1], [0]))[..., None]
    sat = d["sat"]
    if abs(d["vib"]) > 1e-6:
        mx = np.max(x, axis=-1, keepdims=True)
        mn = np.min(x, axis=-1, keepdims=True)
        cur = np.clip((mx - mn) / np.maximum(np.abs(mx), 1e-6), 0, 1)
        sat = sat * (1 + d["vib"] * (1 - cur))
    x = lum + (x - lum) * sat
    if not np.allclose(d["hue"], np.eye(3), atol=1e-6):
        x = x @ d["hue"].T
    return x.astype(np.float32, copy=False)


def apply_levels_np(rgb: np.ndarray, d: dict) -> np.ndarray:
    ib, iw, ob, ow = (float(v) for v in d["levels"])
    x = (rgb - ib) / max(1e-6, iw - ib)
    return (x * (ow - ob) + ob + d["bright"]).astype(np.float32, copy=False)


# ==========================================================================
# LUT .cube (1D et 3D)
# ==========================================================================

class LutError(Exception):
    pass


@dataclass
class Lut:
    path: Path
    kind: int                    # 1 ou 3
    size: int
    table: np.ndarray            # 1D : (N, 3) ; 3D : (N, N, N, 3) indexé [b, g, r] (rouge le plus rapide)
    domain_min: np.ndarray
    domain_max: np.ndarray
    title: str = ""

    def apply_np(self, rgb: np.ndarray) -> np.ndarray:
        x = (rgb - self.domain_min) / np.maximum(self.domain_max - self.domain_min, 1e-9)
        x = np.clip(x, 0.0, 1.0) * (self.size - 1)
        if self.kind == 1:
            out = np.empty_like(x)
            grid = np.arange(self.size, dtype=np.float32)
            for c in range(3):
                out[..., c] = np.interp(x[..., c], grid, self.table[:, c])
            return out
        i0 = np.floor(x).astype(np.int32)
        i0 = np.minimum(i0, self.size - 2)
        f = x - i0
        r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
        fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
        t = self.table

        def at(db, dg, dr):
            return t[b0 + db, g0 + dg, r0 + dr]
        c00 = at(0, 0, 0) * (1 - fr) + at(0, 0, 1) * fr
        c01 = at(0, 1, 0) * (1 - fr) + at(0, 1, 1) * fr
        c10 = at(1, 0, 0) * (1 - fr) + at(1, 0, 1) * fr
        c11 = at(1, 1, 0) * (1 - fr) + at(1, 1, 1) * fr
        c0 = c00 * (1 - fg) + c01 * fg
        c1 = c10 * (1 - fg) + c11 * fg
        return (c0 * (1 - fb) + c1 * fb).astype(np.float32)


_LUT_CACHE: dict = {}


def load_cube(path) -> Lut:
    """Lit un .cube (Adobe / Resolve) : LUT_1D_SIZE ou LUT_3D_SIZE, DOMAIN_MIN / MAX, TITLE. LutError si invalide.
    Gardée en mémoire tant que le fichier ne change pas."""
    path = Path(path)
    try:
        stamp = path.stat().st_mtime_ns
    except OSError as exc:
        raise LutError(f"LUT introuvable : {path}") from exc
    cached = _LUT_CACHE.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    kind = size = 0
    title = ""
    dmin, dmax = np.zeros(3, np.float32), np.ones(3, np.float32)
    values: list[list[float]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                word = line.split()[0].upper()
                if word == "TITLE":
                    title = line[5:].strip().strip('"')
                elif word == "LUT_1D_SIZE":
                    kind, size = 1, int(line.split()[1])
                elif word == "LUT_3D_SIZE":
                    kind, size = 3, int(line.split()[1])
                elif word == "DOMAIN_MIN":
                    dmin = np.array([float(v) for v in line.split()[1:4]], np.float32)
                elif word == "DOMAIN_MAX":
                    dmax = np.array([float(v) for v in line.split()[1:4]], np.float32)
                elif word in ("LUT_1D_INPUT_RANGE", "LUT_3D_INPUT_RANGE"):
                    lo, hi = (float(v) for v in line.split()[1:3])
                    dmin, dmax = np.full(3, lo, np.float32), np.full(3, hi, np.float32)
                elif word[0].isdigit() or word[0] in "-+.":
                    values.append([float(v) for v in line.split()[:3]])
    except (OSError, ValueError, IndexError) as exc:
        raise LutError(f"LUT illisible ({path.name}) : {exc}") from exc
    expected = size if kind == 1 else size ** 3
    if kind == 0 or size < 2 or len(values) != expected:
        raise LutError(f"LUT invalide ({path.name}) : {len(values)} valeurs pour une taille {size}"
                       f"{' (3D)' if kind == 3 else ''}.")
    table = np.asarray(values, np.float32)
    table = table.reshape(size, size, size, 3) if kind == 3 else table.reshape(size, 3)
    lut = Lut(path, kind, size, np.ascontiguousarray(table), dmin, dmax, title)
    _LUT_CACHE[str(path)] = (stamp, lut)
    return lut


def list_luts(directory) -> list[Path]:
    """.cube d'une bibliothèque (sous-dossiers compris), triés par nom."""
    if not directory:
        return []
    out = []
    for root, _dirs, files in os.walk(directory):
        for name in files:
            if name.lower().endswith(".cube"):
                out.append(Path(root) / name)
        if len(out) > 2000:
            break
    return sorted(out, key=lambda p: p.name.lower())


# ==========================================================================
# OpenColorIO
# ==========================================================================

BUILTIN_CONFIG = "ocio://cg-config-latest"


def ocio_available() -> bool:
    try:
        import PyOpenColorIO  # noqa: F401
        return True
    except Exception:                                        # noqa: BLE001
        return False


_CONFIGS: dict = {}


def load_config(path: str = ""):
    """Configuration OCIO : fichier choisi, sinon $OCIO, sinon la configuration CG intégrée (ACES)."""
    import PyOpenColorIO as ocio
    source = (path or "").strip() or os.environ.get("OCIO", "") or BUILTIN_CONFIG
    if source in _CONFIGS:
        return _CONFIGS[source]
    try:
        config = ocio.Config.CreateFromFile(source)
    except Exception:                                        # noqa: BLE001 - configuration absente / invalide
        source = BUILTIN_CONFIG
        config = _CONFIGS.get(source) or ocio.Config.CreateFromFile(source)
    _CONFIGS[source] = config
    return config


def colorspace_names(config) -> list[str]:
    return [cs.getName() for cs in config.getColorSpaces()]


def working_space(config) -> str:
    import PyOpenColorIO as ocio
    return config.getRoleColorSpace(ocio.ROLE_SCENE_LINEAR) or colorspace_names(config)[0]


@dataclass
class OcioSetup:
    config_path: str
    input_space: str
    display: str
    view: str


class ColorPipeline:
    """Processeurs OCIO (entrée -> travail, travail -> affichage), gardés tant que la configuration ne change pas."""

    def __init__(self, setup: OcioSetup):
        import PyOpenColorIO as ocio
        self.setup = setup
        self.config = load_config(setup.config_path)
        self.working = working_space(self.config)
        names = colorspace_names(self.config)
        self.input_space = setup.input_space if setup.input_space in names else self.working
        displays = list(self.config.getDisplays())
        self.display = setup.display if setup.display in displays else self.config.getDefaultDisplay()
        views = list(self.config.getViews(self.display))
        self.view = setup.view if setup.view in views else self.config.getDefaultView(self.display)
        self.proc_in = self.config.getProcessor(self.input_space, self.working)
        transform = ocio.DisplayViewTransform(src=self.working, display=self.display, view=self.view)
        self.proc_out = self.config.getProcessor(transform)
        self._cpu_in = self.proc_in.getDefaultCPUProcessor()
        self._cpu_out = self.proc_out.getDefaultCPUProcessor()
        self.identity_in = self.proc_in.isNoOp()
        try:
            luma = self.config.getDefaultLumaCoefs()
            self.luma = tuple(float(v) for v in luma)
        except Exception:                                    # noqa: BLE001
            self.luma = LUMA_AP1

    def key(self):
        return (self.setup.config_path, self.input_space, self.display, self.view)

    def cpu_in(self, rgb: np.ndarray) -> np.ndarray:
        if self.identity_in:
            return rgb
        out = np.ascontiguousarray(rgb, dtype=np.float32).copy()
        self._cpu_in.applyRGB(out)
        return out

    def cpu_out(self, rgb: np.ndarray) -> np.ndarray:
        out = np.ascontiguousarray(rgb, dtype=np.float32).copy()
        self._cpu_out.applyRGB(out)
        return out

    def gpu_shader(self, which: str):
        """(texte GLSL d'une fonction `vec4 <nom>(vec4)`, textures [(nom du sampler, dimensions, largeur, hauteur,
        profondeur, canaux, valeurs float32, linéaire)]). `which` : « in » ou « out »."""
        import PyOpenColorIO as ocio
        proc = self.proc_in if which == "in" else self.proc_out
        desc = ocio.GpuShaderDesc.CreateShaderDesc(language=ocio.GPU_LANGUAGE_GLSL_1_3)
        name = "OCIOIn" if which == "in" else "OCIOOut"
        desc.setFunctionName(name)
        desc.setResourcePrefix(f"ocio_{which}_")
        try:
            desc.setAllowTexture1D(False)
        except Exception:                                    # noqa: BLE001 - OCIO < 2.3
            pass
        proc.getDefaultGPUProcessor().extractGpuShaderInfo(desc)
        textures = []
        for tex in desc.getTextures():
            values = np.asarray(tex.getValues(), dtype=np.float32)
            channels = 3 if tex.channel == ocio.GpuShaderDesc.TEXTURE_RGB_CHANNEL else 1
            textures.append((tex.samplerName, 2, tex.width, max(1, tex.height), 1, channels, values,
                             tex.interpolation != ocio.INTERP_NEAREST))
        for tex in desc.get3DTextures():
            values = np.asarray(tex.getValues(), dtype=np.float32)
            edge = int(getattr(tex, "edgeLen", 0) or getattr(tex, "width", 0))
            textures.append((tex.samplerName, 3, edge, edge, edge, 3, values,
                             tex.interpolation != ocio.INTERP_NEAREST))
        uniforms = []
        for uname, data in desc.getUniforms():
            uniforms.append((uname, data))
        return desc.getShaderText(), textures, uniforms


# ==========================================================================
# Traitement CPU complet (export, analyse, repli sans OpenGL)
# ==========================================================================

@dataclass
class ViewState:
    """Ce qui transforme l'image affichée (et exportée « telle qu'affichée »)."""
    grade: dict
    grade_on: bool = True
    lut: Lut | None = None
    lut_position: str = "display"         # « source » ou « display »
    lut_mix: float = 1.0
    channel: str = "rgb"                  # rgb, r, g, b, a, luma
    clipping: bool = False
    alpha_mode: str = "auto"              # auto, premult, straight, ignore


def to_rgb_alpha(pixels: np.ndarray):
    """(RVB float32 H x W x 3, alpha H x W ou None) depuis 1 à 4 canaux, 0-1 pour les entiers."""
    from video.media import normalized
    x = normalized(pixels)
    if x.ndim == 2:
        x = x[..., None]
    c = x.shape[2]
    if c == 1:
        return np.repeat(x, 3, axis=2), None
    if c == 2:
        return np.repeat(x[..., :1], 3, axis=2), x[..., 1]
    return x[..., :3].copy(), (x[..., 3] if c >= 4 else None)


def process_np(pixels: np.ndarray, pipe: ColorPipeline | None, state: ViewState, stage: str = "display"):
    """Image traitée sur le CPU. `stage` : « working » (linéaire scène corrigé, avant affichage : export EXR « avec
    corrections ») ou « display » (telle qu'affichée, avant niveaux de canal / damier). Rend (RVB, alpha)."""
    rgb, alpha = to_rgb_alpha(pixels)
    graded = state.grade_on
    d = derived(state.grade, pipe.luma if pipe else LUMA_AP1)
    if graded and state.lut is not None and state.lut_position == "source":
        rgb = _mix(rgb, state.lut.apply_np(rgb), state.lut_mix)
    if pipe is not None:
        rgb = pipe.cpu_in(rgb)
    if graded:
        rgb = apply_grade_np(rgb, d)
    if stage == "working":
        return rgb, alpha
    if pipe is not None:
        rgb = pipe.cpu_out(rgb)
    if graded and state.lut is not None and state.lut_position == "display":
        rgb = _mix(rgb, state.lut.apply_np(rgb), state.lut_mix)
    if graded:
        rgb = apply_levels_np(rgb, d)
    return rgb, alpha


def _mix(a, b, t):
    t = float(t)
    if t >= 0.999:
        return b
    return a + (b - a) * t
