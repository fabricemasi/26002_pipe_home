"""Réglages d'image et filtres (SANS Qt) : un registre `EFFECTS` (nom -> libellé, paramètres, fonction) utilisé tel quel
par la fenêtre d'aperçu et par les tests.

CONVENTIONS : les réglages travaillent sur les couleurs DROITES (RGB uint8, encodées sRGB) et laissent l'alpha
inchangé ; les filtres travaillent en float32 PRÉMULTIPLIÉ (pas de halo). Résultat toujours calculé depuis l'ORIGINAL
(`run` relit le calque) : aucune erreur ne s'accumule quand un curseur bouge. Ils sont DESTRUCTIFS (le calque est
modifié), annulables ; la sélection (couverture partielle comprise) mélange l'original et le résultat.

Formules (documentées, testées) :
- luminosité / contraste : y = (x − ½)·tan((c + 1)·π/4) + ½ + b/2, c et b dans [−1, 1] ;
- niveaux : y = ((x − noir)/(blanc − noir))^(1/gamma), puis remis entre sortie noire et blanche ;
- courbes : interpolation monotone (Fritsch–Carlson) des points, table de 256 valeurs ;
- exposition : en lumière linéaire, y = x·2^EV + décalage, puis gamma, puis retour sRGB ;
- teinte / saturation / luminosité : en HSL ; N&B : somme pondérée des canaux ; balance des couleurs : décalages pondérés
  par les tons (ombres / moyens / hautes lumières) avec option « conserver la luminosité »."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import compose as C, filters
from .planes import rect_intersect, rect_union


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    low: float
    high: float
    default: float
    unit: str = ""
    decimals: int = 0           # 0 = entier ; 1, 2 = décimales du curseur (valeur affichée = entier / 10**decimals)


# -- outils de table --
def _apply_lut(rgb: np.ndarray, luts) -> np.ndarray:
    """luts : 3 tables de 256 uint8 (une par canal) ou une seule pour les trois."""
    out = np.empty_like(rgb)
    for c in range(3):
        out[..., c] = np.take(luts[c] if isinstance(luts, (list, tuple)) else luts, rgb[..., c])
    return out


def _to_u8(y: np.ndarray) -> np.ndarray:
    return np.clip(y * 255.0 + 0.5, 0, 255).astype(np.uint8)


_X = np.linspace(0.0, 1.0, 256, dtype=np.float64)


def srgb_to_linear(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(y):
    y = np.clip(y, 0.0, None)
    return np.where(y <= 0.0031308, y * 12.92, 1.055 * np.power(y, 1 / 2.4) - 0.055)


# -- réglages en table --
def brightness_contrast(rgb, brightness=0.0, contrast=0.0):
    slope = math.tan((float(np.clip(contrast, -0.999, 0.999)) + 1.0) * math.pi / 4.0)
    return _apply_lut(rgb, _to_u8((_X - 0.5) * slope + 0.5 + brightness / 2.0))


def levels(rgb, in_black=0, in_white=255, gamma=1.0, out_black=0, out_white=255):
    span = max(1.0, float(in_white) - float(in_black))
    t = np.clip((_X * 255.0 - in_black) / span, 0.0, 1.0) ** (1.0 / max(0.01, gamma))
    return _apply_lut(rgb, _to_u8((out_black + t * (out_white - out_black)) / 255.0))


def curve_lut(points) -> np.ndarray:
    """Table de 256 valeurs d'une courbe à points de contrôle [(x, y)] en 0..255 (interpolation monotone)."""
    pts = sorted((float(x), float(y)) for x, y in points)
    if not pts or pts[0][0] > 0:
        pts.insert(0, (0.0, pts[0][1] if pts else 0.0))
    if pts[-1][0] < 255:
        pts.append((255.0, pts[-1][1]))
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    h = np.diff(xs)
    h = np.where(h == 0, 1e-9, h)
    delta = np.diff(ys) / h
    m = np.zeros(len(xs))
    m[0], m[-1] = delta[0], delta[-1]
    for k in range(1, len(xs) - 1):
        m[k] = 0.0 if delta[k - 1] * delta[k] <= 0 else (delta[k - 1] + delta[k]) / 2.0
    for k in range(len(delta)):                                 # Fritsch–Carlson : monotonie
        if delta[k] == 0:
            m[k] = m[k + 1] = 0.0
        else:
            a, b = m[k] / delta[k], m[k + 1] / delta[k]
            s = a * a + b * b
            if s > 9:
                tau = 3.0 / math.sqrt(s)
                m[k], m[k + 1] = tau * a * delta[k], tau * b * delta[k]
    x = np.arange(256, dtype=np.float64)
    idx = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, len(xs) - 2)
    t = (x - xs[idx]) / h[idx]
    t2, t3 = t * t, t * t * t
    y = (2 * t3 - 3 * t2 + 1) * ys[idx] + (t3 - 2 * t2 + t) * h[idx] * m[idx] + (-2 * t3 + 3 * t2) * ys[idx + 1] \
        + (t3 - t2) * h[idx] * m[idx + 1]
    return np.clip(y + 0.5, 0, 255).astype(np.uint8)


def curves(rgb, points=((0, 0), (255, 255)), red=None, green=None, blue=None):
    master = curve_lut(points)
    luts = [master, master, master]
    for i, extra in enumerate((red, green, blue)):
        if extra:
            luts[i] = np.take(curve_lut(extra), master)
    return _apply_lut(rgb, luts)


def exposure(rgb, ev=0.0, offset=0.0, gamma=1.0):
    lin = srgb_to_linear(_X) * (2.0 ** ev) + offset
    lin = np.sign(lin) * np.abs(lin) ** (1.0 / max(0.01, gamma))
    return _apply_lut(rgb, _to_u8(linear_to_srgb(lin)))


def invert(rgb):
    return 255 - rgb


def black_white(rgb, red=0.299, green=0.587, blue=0.114):
    gray = rgb[..., 0] * red + rgb[..., 1] * green + rgb[..., 2] * blue
    out = np.empty_like(rgb)
    out[...] = np.clip(gray + 0.5, 0, 255).astype(np.uint8)[..., None]
    return out


# -- réglages en HSL --
def _rgb_to_hsl(rgb):
    f = rgb.astype(np.float32) / 255.0
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    mx, mn = f.max(axis=2), f.min(axis=2)
    l = (mx + mn) / 2.0
    d = mx - mn
    s = np.where(d == 0, 0.0, d / np.maximum(1e-9, 1.0 - np.abs(2.0 * l - 1.0)))
    h = np.zeros_like(l)
    nz = d > 0
    rr = nz & (mx == r)
    gg = nz & (mx == g) & ~rr
    bb = nz & ~rr & ~gg
    h[rr] = (((g - b)[rr] / d[rr]) % 6.0)
    h[gg] = ((b - r)[gg] / d[gg]) + 2.0
    h[bb] = ((r - g)[bb] / d[bb]) + 4.0
    return h * 60.0, s, l


def _hsl_to_rgb(h, s, l):
    c = (1.0 - np.abs(2.0 * l - 1.0)) * s
    hp = (h % 360.0) / 60.0
    x = c * (1.0 - np.abs(hp % 2.0 - 1.0))
    z = np.zeros_like(c)
    sector = hp.astype(np.int32) % 6
    table = [(c, x, z), (x, c, z), (z, c, x), (z, x, c), (x, z, c), (c, z, x)]
    r = np.select([sector == i for i in range(6)], [t[0] for t in table])
    g = np.select([sector == i for i in range(6)], [t[1] for t in table])
    b = np.select([sector == i for i in range(6)], [t[2] for t in table])
    m = l - c / 2.0
    return np.clip(np.stack([r + m, g + m, b + m], axis=2) * 255.0 + 0.5, 0, 255).astype(np.uint8)


def hue_saturation(rgb, hue=0.0, saturation=0.0, lightness=0.0):
    h, s, l = _rgb_to_hsl(rgb)
    s = np.clip(s * (1.0 + saturation), 0.0, 1.0) if saturation >= 0 else s * (1.0 + saturation)
    l = l + (1.0 - l) * lightness if lightness >= 0 else l * (1.0 + lightness)
    return _hsl_to_rgb(h + hue, s, np.clip(l, 0.0, 1.0))


def color_balance(rgb, shadows=(0, 0, 0), midtones=(0, 0, 0), highlights=(0, 0, 0), preserve_luminosity=True):
    """Décalages (cyan–rouge, magenta–vert, jaune–bleu) en −1..1 par plage de tons."""
    f = rgb.astype(np.float32) / 255.0
    lum = (f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114)
    w_sh = np.clip(1.0 - 2.0 * lum, 0.0, 1.0)
    w_hi = np.clip(2.0 * lum - 1.0, 0.0, 1.0)
    w_mid = 1.0 - w_sh - w_hi
    out = f.copy()
    for weight, shift in ((w_sh, shadows), (w_mid, midtones), (w_hi, highlights)):
        for c in range(3):
            out[..., c] += weight * float(shift[c]) * 0.5
    out = np.clip(out, 0.0, 1.0)
    if preserve_luminosity:
        new_lum = out[..., 0] * 0.299 + out[..., 1] * 0.587 + out[..., 2] * 0.114
        out = np.clip(out * (np.maximum(lum, 1e-4) / np.maximum(new_lum, 1e-4))[..., None], 0.0, 1.0)
    return _to_u8(out)


# -- filtres (float32 prémultiplié) --
def f_gaussian(premult, radius=4.0):
    return filters.gaussian_blur(premult, radius)


def f_unsharp(premult, amount=1.0, radius=1.5, threshold=0.0):
    return filters.unsharp(premult, amount, radius, threshold)


def f_noise(premult, amount=0.1, seed=0, mono=True):
    return filters.add_noise(premult, amount, seed, mono)


def _P(key, label, low, high, default, unit="", decimals=0):
    return Param(key, label, low, high, default, unit, decimals)


# nom -> (libellé, genre « rgb » / « filter », paramètres, fonction, marge(params))
EFFECTS = {
    "brightness_contrast": ("Luminosité / contraste", "rgb", [_P("brightness", "Luminosité", -1.0, 1.0, 0.0, "", 2),
                                                               _P("contrast", "Contraste", -1.0, 1.0, 0.0, "", 2)],
                            brightness_contrast, None),
    "levels": ("Niveaux", "rgb", [_P("in_black", "Noir entrée", 0, 254, 0), _P("in_white", "Blanc entrée", 1, 255, 255),
                                  _P("gamma", "Gamma", 0.1, 9.9, 1.0, "", 2),
                                  _P("out_black", "Noir sortie", 0, 255, 0), _P("out_white", "Blanc sortie", 0, 255, 255)],
               levels, None),
    "curves": ("Courbes", "rgb", [], curves, None),
    "exposure": ("Exposition", "rgb", [_P("ev", "Exposition (IL)", -5.0, 5.0, 0.0, "", 2),
                                       _P("offset", "Décalage", -0.5, 0.5, 0.0, "", 3),
                                       _P("gamma", "Correction gamma", 0.1, 9.9, 1.0, "", 2)], exposure, None),
    "hue_saturation": ("Teinte / saturation", "rgb", [_P("hue", "Teinte", -180, 180, 0, "°"),
                                                        _P("saturation", "Saturation", -1.0, 1.0, 0.0, "", 2),
                                                        _P("lightness", "Luminosité", -1.0, 1.0, 0.0, "", 2)],
                       hue_saturation, None),
    "color_balance": ("Balance des couleurs", "rgb", [], color_balance, None),
    "black_white": ("Noir et blanc", "rgb", [_P("red", "Rouges", 0.0, 1.0, 0.299, "", 3),
                                             _P("green", "Verts", 0.0, 1.0, 0.587, "", 3),
                                             _P("blue", "Bleus", 0.0, 1.0, 0.114, "", 3)], black_white, None),
    "invert": ("Négatif", "rgb", [], invert, None),
    "gaussian_blur": ("Flou gaussien", "filter", [_P("radius", "Rayon", 0.1, 250.0, 4.0, "px", 1)], f_gaussian,
                      lambda p: filters.margin(p.get("radius", 4.0))),
    "unsharp": ("Accentuation", "filter", [_P("amount", "Quantité", 0.0, 5.0, 1.0, "", 2),
                                           _P("radius", "Rayon", 0.1, 100.0, 1.5, "px", 1),
                                           _P("threshold", "Seuil", 0.0, 0.5, 0.0, "", 3)], f_unsharp,
                lambda p: filters.margin(p.get("radius", 1.5))),
    "noise": ("Ajouter du bruit", "filter", [_P("amount", "Quantité", 0.0, 0.5, 0.1, "", 3)], f_noise, None),
}


def defaults(name: str) -> dict:
    return {p.key: p.default for p in EFFECTS[name][2]}


def clean_params(name: str, params: dict | None) -> dict:
    """Paramètres validés (inconnus ignorés, bornes respectées) : un fichier ou un réglage invalide ne plante rien."""
    out = defaults(name)
    for p in EFFECTS[name][2]:
        if params and p.key in params:
            try:
                out[p.key] = min(p.high, max(p.low, float(params[p.key])))
            except (TypeError, ValueError):
                pass
    if name in ("curves", "color_balance") and params:
        out.update({k: v for k, v in params.items() if k not in out})
    return out


def run(layer, name: str, params: dict | None, selection, doc_rect, seed: int = 0):
    """Calcule l'effet sur le calque SANS rien modifier. Rend (rect, avant, après) ou None si rien à faire.
    Région = pixels du calque (élargis de la marge du filtre, dans le document) ∩ sélection."""
    label, kind, specs, function, margin_of = EFFECTS[name]
    params = clean_params(name, params)
    mine = layer.pix.rect()
    if mine is None and kind == "rgb":
        return None
    mine = mine or doc_rect
    margin = margin_of(params) if margin_of else 0
    region = mine
    if kind == "filter" and margin:
        grown = rect_intersect((mine[0] - margin, mine[1] - margin, mine[2] + margin, mine[3] + margin), doc_rect)
        region = rect_union(mine, grown) if grown else mine
    if kind == "filter" and name == "noise":
        region = rect_intersect(region, doc_rect) or region
    if selection is not None:
        bounds = selection.bounds()
        if bounds is None:
            return None
        region = rect_intersect(region, bounds)
        if region is None:
            return None
    before = layer.pix.read(region)
    if kind == "rgb":
        out = before.copy()
        out[..., :3] = function(before[..., :3], **params)
    else:
        ctx = (region[0] - margin, region[1] - margin, region[2] + margin, region[3] + margin)
        premult = C.premultiplied(layer.pix.read(ctx))
        kwargs = dict(params)
        if name == "noise":
            kwargs["seed"] = seed
        result = function(premult, **kwargs)[margin:margin + before.shape[0], margin:margin + before.shape[1]]
        out = C.to_straight_u8(result)
    if selection is not None:
        cover = selection.coverage(region)[..., None]
        out = np.clip(before.astype(np.float32) + (out.astype(np.float32) - before) * cover + 0.5, 0, 255) \
            .astype(np.uint8)
    if np.array_equal(out, before):
        return None
    return region, before, out
