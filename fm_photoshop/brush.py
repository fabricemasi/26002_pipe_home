"""Moteur de brosse (SANS Qt) : coups de pinceau, gomme et peinture de masque par TAMPONS (« dabs »).

Principe (mesuré, voir la doc) : le trait n'est jamais recomposé en entier. Les pixels sont lus / écrits par TUILES de
64 × 64 ; la couverture du trait (flottant) est gardée par tuile ; chaque tampon n'écrit que les pixels qu'il touche.
Débit (flow) : les tampons s'ACCUMULENT (cov += (1 - cov)·tampon·débit) ; opacité : plafond du trait entier
(min(cov, opacité)) ; sélection : multiplie la couverture (bords progressifs respectés). Au `end`, l'étape
d'annulation ne garde que la zone touchée (avant / après)."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace

import numpy as np

try:    # le ufunc `clip` direct : `np.clip` passe par trois enveloppes Python (≈ 5 µs par appel, ~9 appels par tampon)
    from numpy._core.umath import clip as _uclip
except ImportError:                                  # NumPy 1.x
    from numpy.core.umath import clip as _uclip

from . import compose as C, filters
from .history import TilesCommand
from .pen_input import OneEuro, Rope, Weighted
from .planes import rect_intersect

TILE = 64
DOTTED_SPACING = 0.35       # fraction du diamètre : pointillé voulu au-delà ; distance de non-contact qui fait d'un retour un NOUVEAU passage


@dataclass
class Tuning:
    """Réglages d'ESSAI du moteur de trait (panneau « Réglages d'essai » de la brosse) : valeurs trouvées à l'usage,
    destinées à être figées dans le code puis retirées. Un seul exemplaire (`TUNING`), lu à chaque point du geste."""
    # pression (signal indépendant de la trajectoire)
    pressure_filter: float = 1.0        # poids du nouvel échantillon de pression (1 = brute, bas = lissée, donc en retard)
    size_gamma: float = 1.0             # courbe de la taille : f(p) = p ^ gamma (1 = linéaire)
    opacity_gamma: float = 1.0          # courbe de l'opacité (si « Pression : opacité »)
    flow_gamma: float = 1.0             # courbe du débit (si « Pression : débit »)
    min_diameter: float = 0.0           # m : fraction de la taille à pression nulle, D = Dmax (m + (1 - m) f(p))
    # lissage adaptatif (One Euro)
    oe_cutoff_max: float = 30.0         # Hz : fréquence de coupure à l'arrêt pour un lissage faible (diminue avec le lissage)
    oe_beta: float = 0.05               # sensibilité à la vitesse : plus haut = moins de retard au mouvement rapide
    # lissage pondéré
    weighted_px: float = 24.0           # fenêtre à 100 % (px d'écran)
    # stabilisateur (corde tirée)
    rope_px: float = 100.0              # lissage 100 % = corde de cette longueur (px d'écran)
    catch_up_end: bool = False          # « Rattrapage en fin de trait » : le trait finit sous le curseur
    catch_up_pause: bool = False        # « Rattrapage du trait » : la pointe continue vers le curseur pendant une pause
    catch_up_speed: float = 0.25        # fraction de l'écart parcourue à chaque tour de minuterie (16 ms)
    pressure_at_tip: bool = True        # la pointe en retard garde la pression qu'avait le curseur à cet endroit
    # aérographe (voir `Stroke.air_tick`)
    air_rate: float = 1.0               # à pression immobile, « débit » = part de la peinture restante déposée PAR SECONDE
    air_dt_max: float = 0.1             # s : durée maximale comptée entre deux mises à jour (un blocage de l'interface ne dépose pas d'un coup)
    air_first: float = 1.0 / 60.0       # s : dépôt initial à l'appui (un simple tap laisse un point)
    # fusion des pointes douces (voir `Stroke._apply_tile`)
    soft_union: float = 0.25            # espacement de référence (fraction du diamètre) de l'union « sur » des pointes douces ; 0 = maximum seul
    # contour des pointes
    feather: float = 1.5                # px : douceur ajoutée à la transition d'une pointe NON dure (voir `_tip`)
    hard_feather: float = 0.0           # px : adoucissement OPTIONNEL du bord d'une pointe dure (0 = bord net, anticrénelage seul)
    # commun
    zoom_adjust: bool = True            # les longueurs en pixels d'écran suivent le zoom d'affichage
    continuous_spacing: float = 0.08    # trait continu : tampons au plus tous les 8 % du diamètre
    curve_chord: float = 1.5            # pixels : pas de la courbe aplatie du stabilisateur

    def reset(self):
        for key, value in Tuning().__dict__.items():
            setattr(self, key, value)

    def as_text(self) -> str:
        return ", ".join(f"{k}={v:g}" if not isinstance(v, bool) else f"{k}={v}" for k, v in self.__dict__.items())


TUNING = Tuning()
# Modes d'un trait : « paint » (pinceau), « erase » (gomme) et les outils de retouche. Clone / correcteur / flou /
# netteté lisent une COPIE du plan prise au début du trait (une seule fois par trait, jamais à chaque point).
MODES = ("paint", "erase", "clone", "heal", "blur", "sharpen", "smudge", "dodge", "burn")
MODE_LABELS = {"paint": "Pinceau", "erase": "Gomme", "clone": "Tampon de duplication",
               "heal": "Correcteur (texture de la source, tons de la destination)", "blur": "Goutte d'eau (flou)",
               "sharpen": "Netteté", "smudge": "Doigt", "dodge": "Densité - (éclaircir)", "burn": "Densité + (assombrir)"}
SNAPSHOT_MODES = ("clone", "heal", "blur", "sharpen")
SMOOTHING_MODES = ("none", "adaptive", "weighted", "stabilizer")
SMOOTHING_LABELS = {"none": "Aucun", "adaptive": "Adaptatif", "weighted": "Pondéré", "stabilizer": "Stabilisateur"}
PAINT_MODES = ("wash", "buildup")
PAINT_LABELS = {"wash": "Plafond", "buildup": "Accumulation"}


@dataclass
class Brush:
    name: str = "Rond"
    size: float = 24.0                  # diamètre (pixels du document)
    hardness: float = 0.8               # 0 (très doux) .. 1 (dur)
    opacity: float = 1.0                # plafond du trait (mode « plafond ») ou dose de départ (mode « accumulation »)
    flow: float = 1.0                   # débit : part de l'opacité déposée par PASSAGE (voir `Stroke._apply_tile`)
    paint_mode: str = "wash"            # "wash" (plafond) | "buildup" (accumulation naturelle), voir `paint_kind`
    spacing: float = 0.2                # fraction du diamètre entre deux tampons
    smoothing: float = 0.0              # 0 .. 0.95 : intensité du lissage du geste (selon `smoothing_mode`)
    smoothing_mode: str = ""            # "none" | "adaptive" | "weighted" | "stabilizer" ; "" = automatique (voir `smoothing_kind`)
    pressure_size: bool = False
    pressure_flow: bool = False
    pressure_opacity: bool = False
    airbrush: bool = False              # aérographe : le dépôt dépend du TEMPS (même immobile), voir `Stroke.air_tick`
    color: tuple = (0, 0, 0)
    eraser: bool = False
    mode: str = "paint"                 # voir MODES
    sigma: float = 2.0                  # flou / netteté / correcteur : écart-type (pixels)

    def copy(self, **kw) -> "Brush":
        return replace(self, **kw)

    def smoothing_kind(self) -> str:
        """Mode de lissage effectif. Une brosse ancienne (lissage > 0 sans mode) garde le stabilisateur qu'elle avait ;
        sans lissage, le mode est « aucun » : la trajectoire est celle du périphérique."""
        if self.smoothing <= 0.0 and self.smoothing_mode != "stabilizer":
            return "none"
        if self.smoothing_mode in SMOOTHING_MODES:
            return self.smoothing_mode
        return "stabilizer"

    def paint_kind(self) -> str:
        """Comportement de dépôt. « wash » (Plafond) : l'opacité est une limite, repasser dans le trait n'ajoute rien au-delà
        (le débit règle la vitesse pour l'atteindre). « buildup » (Accumulation naturelle) : un passage dépose son opacité
        de façon homogène, chaque RETOUR sur une zone déjà peinte s'y ajoute (1 − (1 − a)(1 − b)). La pression et le mode
        sont indépendants. Une présélection sans mode (ou inconnu) = plafond, son comportement d'avant l'accumulation."""
        return self.paint_mode if self.paint_mode in PAINT_MODES else "wash"

    def to_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, raw: dict) -> "Brush":
        base = cls()
        for key, value in (raw or {}).items():
            if key in base.__dict__ and key != "color":
                try:
                    setattr(base, key, type(getattr(base, key))(value))
                except (TypeError, ValueError):
                    pass
        if isinstance((raw or {}).get("color"), (list, tuple)) and len(raw["color"]) >= 3:
            base.color = tuple(max(0, min(255, int(c))) for c in raw["color"][:3])
        base.hardness = min(1.0, max(0.0, base.hardness))
        base.opacity = min(1.0, max(0.0, base.opacity))
        base.flow = min(1.0, max(0.0, base.flow))
        base.smoothing = min(0.95, max(0.0, base.smoothing))
        if base.smoothing_mode not in SMOOTHING_MODES:
            base.smoothing_mode = ""
        if base.paint_mode not in PAINT_MODES:
            base.paint_mode = "wash"                    # migration explicite : une présélection ancienne garde le plafond
        base.size = min(5000.0, max(0.5, base.size))
        base.spacing = min(2.0, max(0.02, base.spacing))
        base.sigma = min(50.0, max(0.3, base.sigma))
        if base.mode not in MODES:
            base.mode = "paint"
        return base


def _tip(radius: float, hardness: float):
    """(r0, largeur) du profil radial d'une pointe : plein jusqu'à `r0`, puis descente smoothstep sur `largeur` pixels.
    Dureté = `r0 / R`. Douceur supplémentaire (`TUNING.feather`, « pixel feather ») : la transition s'élargit AUTOUR de son
    milieu (le diamètre apparent à 50 % de densité ne bouge pas) de `hypot(largeur, feather)`, et seulement :
      - pour une pointe non dure (le poids tombe à 0 quand la dureté tend vers 100 % : un disque franc reste net),
      - pour une pointe assez grande (le poids monte de 0 à 1 entre 1,5 et 6 px de rayon : les petites pointes ne
        deviennent jamais molles ni ne disparaissent).
    Ce n'est PAS l'anticrénelage (moyenne sur l'aire du pixel, calculée ensuite) : les deux sont indépendants."""
    h = min(1.0, max(0.0, hardness))
    r0 = radius * h
    width = radius - r0
    if width < 5e-3 * radius:
        hard = TUNING.hard_feather * min(1.0, radius / 3.0)       # (nul par défaut ; plus faible sur les très petites pointes)
        if hard > 1e-6:
            w = min(hard, 1.2 * radius)
            return max(0.0, radius - w / 2.0), min(w, radius + w / 2.0)      # 50 % de densité exactement au rayon nominal
        return radius, 0.0
    feather = TUNING.feather * min(1.0, max(0.0, (radius - 1.5) / 4.5)) * min(1.0, (1.0 - h) / 0.1)
    if feather > 1e-6:
        mid = radius - width / 2.0
        wide = math.hypot(width, feather)
        inner = mid - wide / 2.0
        if inner <= 0.0:                               # dégradé déjà aussi large que la pointe : rien à ajouter
            return 0.0, radius
        return inner, wide
    return r0, width


def _soft_range(hardness: float, size: float) -> float:
    """Degré de « pointe douce » (0..1) : 1 pour une pointe douce (dureté <= 50 %), 0 à partir de 80 %, continu entre les
    deux (aucun saut de 1 % à 0 %) ; nul sous 6 px de diamètre, plein à 12 px (les petites pointes gardent la méthode exacte).
    Seules les pointes douces ont le balayage continu du segment et, selon `TUNING.soft_union`, l'union « sur »."""
    u = min(1.0, max(0.0, (0.8 - hardness) / 0.3))
    v = min(1.0, max(0.0, (size - 6.0) / 6.0))
    return u * u * (3.0 - 2.0 * u) * v * v * (3.0 - 2.0 * v)


def _soft_weight(hardness: float, size: float) -> float:
    """Part de l'union « sur » (fusion naturelle des pointes douces, voir `Stroke._apply_tile`) dans la forme du passage ;
    0 si `TUNING.soft_union` = 0 (balayage continu seul)."""
    return _soft_range(hardness, size) if TUNING.soft_union > 0.0 else 0.0


def _profile(dist, r0: float, width: float):
    """Profil radial DE LA POINTE (douceur artistique) : densité 1 jusqu'à `r0`, puis descente lissée (smoothstep) sur
    `width` pixels jusqu'à 0. `width` = 0 : disque franc."""
    if width <= 1e-9:
        return (dist <= r0).astype(np.float64)
    t = np.clip((dist - r0) / width, 0.0, 1.0)
    return 1.0 - t * t * (3.0 - 2.0 * t)


def _smooth_q2(x, r0: float, width: float):
    """Deuxième primitive de la répartition Φ du profil (Φ = 0 sous r0, smoothstep de r0 à r0 + width, 1 au-delà) :
    Q2'' = Φ. Avec t = (x − r0)/width borné à [0, 1] : Q2 = width²·(t⁴/4 − t⁵/10) + (x − r1)₊·width/2 + (x − r1)₊²/2."""
    t = _uclip((x - r0) / width, 0.0, 1.0)
    over = np.maximum(x - (r0 + width), 0.0)
    return width * width * (t ** 4 / 4.0 - t ** 5 / 10.0) + over * (0.5 * width) + 0.5 * over * over


def dab_alpha(cx: float, cy: float, diameter: float, hardness: float, rect, to=None) -> np.ndarray:
    """Couverture (float32 h × l, 0..1) d'un tampon rond centré en (cx, cy) sur la zone `rect`. `to` = (x, y) : couverture du
    BALAYAGE continu de la pointe du centre (cx, cy) à `to` (union exacte de tous les tampons du segment : la distance au
    centre devient la distance au segment, la normale du bord la direction du point le plus proche) ; grande pointe seulement.

    TROIS notions séparées : la dureté (rayon `r0 = R·h` de pleine densité), la douceur (profil smoothstep de r0 à R) et
    l'anticrénelage = valeur MOYENNE du profil sur l'aire de chaque pixel (jamais la valeur au centre du pixel, jamais un
    élargissement artificiel du dégradé). Grande pointe : pour un bord localement droit de normale n, le pixel carré se
    projette sur n selon la loi trapèze (a = max|n|, b = min|n|), d'où une formule fermée exacte,
        moyenne(Φ)(d) = [Q2(d + (a+b)/2) − Q2(d + (a−b)/2) − Q2(d − (a−b)/2) + Q2(d − (a+b)/2)] / (a·b),
    valable pour le disque franc comme pour tout profil lissé. Petite pointe (rayon < SUPER_RADIUS : la courbure n'est plus
    négligeable devant le pixel) : suréchantillonnage local 8 × 8 (16 × 16 pour un disque franc ou sous 1,5 px de rayon)."""
    radius = max(0.02, diameter / 2.0)
    r0, width = _tip(radius, hardness)
    outer = r0 + width                                     # (>= R : la douceur peut dépasser R d'au plus feather / 2)
    if radius < SUPER_RADIUS:
        return _dab_super(cx, cy, r0, width, rect, 16 if (radius < 1.5 or width < 1.0) else 8)
    xs = (np.arange(rect[0], rect[2], dtype=np.float32) + np.float32(0.5 - cx))[None, :]
    ys = (np.arange(rect[1], rect[3], dtype=np.float32) + np.float32(0.5 - cy))[:, None]
    seg = None
    if to is not None:
        sx, sy = to[0] - cx, to[1] - cy
        length2 = sx * sx + sy * sy
        if length2 > 1e-6:
            seg = (sx, sy, length2)
            t = np.clip((xs * np.float32(sx) + ys * np.float32(sy)) / np.float32(length2), 0.0, 1.0)
            xs, ys = xs - t * np.float32(sx), ys - t * np.float32(sy)        # vecteur du point le plus proche du segment au pixel
    dist = np.sqrt(xs * xs + ys * ys)
    alpha = np.zeros(dist.shape, np.float32)
    reach = 0.75                                           # demi-largeur maximale de l'empreinte d'un pixel sur une normale
    alpha[dist <= r0 - reach] = 1.0                        # plein cœur : 1
    band = (dist > r0 - reach) & (dist < outer + reach)    # le reste vaut 0 ; seule la bande de transition se calcule
    exact = band
    if width >= 6.0:
        # Dégradé large : loin des deux jonctions (r0 et R) le profil est lisse sur l'empreinte d'un pixel ; sa moyenne vaut
        # f(d) + f''(d)·σ²/2 avec σ² = (a² + b²)/12 = 1/12 (a² + b² = nx² + ny² = 1, quelle que soit la normale). Formule
        # fermée seulement près des jonctions : 3 à 10 fois plus rapide pour une grande pointe douce.
        exact = band & ((np.abs(dist - r0) < reach) | (np.abs(dist - outer) < reach))
        far = band & ~exact
        t = np.clip((dist - np.float32(r0)) / np.float32(width), 0.0, 1.0)         # (calcul dense : plus rapide que l'indexation)
        alpha = np.where(far, 1.0 - t * t * (3.0 - 2.0 * t) - (1.0 - 2.0 * t) / np.float32(4.0 * width * width), alpha)
    iy, ix = np.nonzero(exact)
    if iy.size:
        px = ix + (rect[0] + 0.5) - cx                     # (coordonnées en double précision pour les différences de Q2 ; entier + k,5
        py = iy + (rect[1] + 0.5) - cy                     # est exact : même valeur que (rect + ix) + 0,5, une opération de moins)
        if seg is not None:
            t = np.clip((px * seg[0] + py * seg[1]) / seg[2], 0.0, 1.0)
            px, py = px - t * seg[0], py - t * seg[1]
        d = np.hypot(px, py)
        inv = 1.0 / np.maximum(d, 1e-9)
        on_axis = d < 1e-6                                 # (sur le segment balayé : normale quelconque, le profil y est plat)
        nx, ny = np.abs(px) * inv, np.abs(py) * inv
        if np.count_nonzero(on_axis):
            nx, ny = np.where(on_axis, 1.0, nx), np.where(on_axis, 0.0, ny)
        a, b = np.maximum(nx, ny), np.maximum(np.minimum(nx, ny), 0.02)
        w = max(width, 1e-4)                               # disque franc : marche quasi verticale, même formule
        s1, s2 = 0.5 * (a + b), 0.5 * (a - b)
        # Les quatre évaluations de Q2 en UN SEUL passage (4, N) : mêmes opérations par élément, dans le même ordre
        # (q0 − q1 − q2 + q3), mais quatre fois moins d'appels NumPy (le coût d'un tampon moyen est l'appel, pas la donnée).
        x4 = np.empty((4, d.size))
        np.add(d, s1, out=x4[0])
        np.add(d, s2, out=x4[1])
        np.subtract(d, s2, out=x4[2])
        np.subtract(d, s1, out=x4[3])
        q = _smooth_q2(x4, r0, w)
        alpha[iy, ix] = 1.0 - (q[0] - q[1] - q[2] + q[3]) / (a * b)
    return _uclip(alpha, 0.0, 1.0)


def _point_profile(cx, cy, diameter, hardness, rect) -> np.ndarray:
    """Profil de la pointe au CENTRE des pixels (sans moyenne d'aire, sans bord exact) : sert aux sommes de l'union douce."""
    r0, width = _tip(max(0.02, diameter / 2.0), hardness)
    xs = (np.arange(rect[0], rect[2], dtype=np.float32) + np.float32(0.5 - cx))[None, :]
    ys = (np.arange(rect[1], rect[3], dtype=np.float32) + np.float32(0.5 - cy))[:, None]
    t = np.clip((np.sqrt(xs * xs + ys * ys) - np.float32(r0)) / np.float32(max(width, 1e-3)), 0.0, 1.0)
    return 1.0 - t * t * (3.0 - 2.0 * t)


SUPER_RADIUS = 6.0          # px : sous ce rayon, couverture par suréchantillonnage local (mesuré : erreur max <= 1,6 % ; voir la doc)


def _dab_super(cx, cy, r0, width, rect, ss) -> np.ndarray:
    """Valeur moyenne du profil sur ss × ss sous-pixels de chaque pixel de `rect` (pointes de petit rayon)."""
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    offsets = (np.arange(ss, dtype=np.float64) + 0.5) / ss
    xs = (rect[0] + np.arange(w, dtype=np.float64)[:, None] + offsets[None, :]).reshape(-1) - cx
    ys = (rect[1] + np.arange(h, dtype=np.float64)[:, None] + offsets[None, :]).reshape(-1) - cy
    dist = np.sqrt(xs[None, :] ** 2 + ys[:, None] ** 2)
    sample = _profile(dist, r0, width)
    return sample.reshape(h, ss, w, ss).mean(axis=(1, 3)).astype(np.float32)


SUB = 64                    # échantillons par pixel de l'état d'un trait à petite pointe
# Motif d'échantillons FIXE, identique dans tous les pixels : suite de Kronecker R2 (faible discrépance). Une grille 8 × 8
# n'offre que 8 niveaux sur un bord horizontal ; ce motif en donne ~64 quelle que soit l'orientation du bord.
_SUB_X = (0.5 + np.arange(SUB) * 0.7548776662466927) % 1.0
_SUB_Y = (0.5 + np.arange(SUB) * 0.5698402909980532) % 1.0


def _dab_samples(cx, cy, diameter, hardness, rect) -> np.ndarray:
    """Profil du tampon ÉCHANTILLONNÉ (non moyenné) aux SUB points fixes de chaque pixel de `rect` : forme (h, l, SUB)."""
    r0, width = _tip(max(0.02, diameter / 2.0), hardness)
    xs = np.arange(rect[0], rect[2], dtype=np.float64)[None, :, None] + _SUB_X[None, None, :] - cx
    ys = np.arange(rect[1], rect[3], dtype=np.float64)[:, None, None] + _SUB_Y[None, None, :] - cy
    return _profile(np.sqrt(xs * xs + ys * ys), r0, width).astype(np.float32)


def _flushed(method):
    """Les pixels du trait sont recomposés UNE fois par appel public (évènement), pas à chaque tampon : voir `Stroke._flush_pixels`."""
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        finally:
            if self._pend:
                self._flush_pixels()
    wrapper.__name__, wrapper.__doc__ = method.__name__, method.__doc__
    return wrapper


class Stroke:
    """Un trait sur le plan `pixels` ou `mask` d'un calque. `begin` / `move`* / `end` (-> étape d'annulation)."""

    def __init__(self, layer, target: str, brush: Brush, doc_rect, selection=None, retouch: dict | None = None):
        if target == "mask" and layer.mask is None:
            raise ValueError("Ce calque n'a pas de masque.")
        if (layer.is_group() or layer.pix is None) and target == "pixels":
            raise ValueError("Un groupe n'a pas de pixels : peignez dans un calque.")
        if layer.locked:
            raise ValueError("Le calque est verrouillé.")
        if layer.source and target == "pixels":
            raise ValueError("Calque de texte ou de forme : convertissez-le d'abord en pixels (menu Calque).")
        self.layer, self.target, self.brush = layer, target, brush
        self.mode = "erase" if brush.eraser else brush.mode
        if target == "mask" and self.mode not in ("paint", "erase"):
            raise ValueError("Cet outil agit sur les pixels, pas sur un masque.")
        self.retouch = dict(retouch or {})              # clone / correcteur : {"offset": (dx, dy)} = source - destination
        if self.mode in ("clone", "heal") and not self.retouch.get("offset"):
            raise ValueError("Choisissez d'abord la source (Alt + clic).")
        self.plane = layer.pix if target == "pixels" else layer.mask.plane
        self.doc_rect = tuple(doc_rect)
        self.selection = selection
        self._snap = self.plane.read(self.doc_rect) if self.mode in SNAPSHOT_MODES else None
        self._carry = None                  # doigt : couleurs emportées par le trait
        self._orig: dict = {}               # (tx, ty) -> pixels d'origine de la tuile (uint8)
        self._cov: dict = {}                # (tx, ty) -> couverture du trait (float32, jamais décroissante)
        self._geo: dict = {}                # (tx, ty) -> enveloppe géométrique : max des formes (borne, jamais décroissante)
        self._base: dict = {}               # (tx, ty) -> densité des passages TERMINÉS (par pixel)
        self._seen: dict = {}               # (tx, ty) -> abscisse curviligne du dernier tampon qui a touché le pixel
        self._way: dict = {}                # (tx, ty) -> sens du geste au début du passage du pixel (x, y)
        self._lam: dict = {}                # (tx, ty) -> « hasard » cumulé de l'union douce du passage courant (pointes douces)
        self._soft = _soft_range(brush.hardness, brush.size) > 0.0
        # Recomposition différée (peinture / gomme seulement : les outils de retouche relisent le plan) : chaque tampon met à jour
        # l'ÉTAT du trait et son alpha par pixel (`_alpha`), mais les pixels ne sont recomposés qu'à la fin de l'évènement
        # (`_flush_pixels`). Un évènement rapide pose des dizaines de tampons sur les mêmes tuiles : la recomposition, qui
        # ne dépend que de l'alpha FINAL du pixel, n'est plus refaite pour chacun d'eux (résultat identique octet pour octet).
        self._defer = self.target == "mask" or self.mode in ("paint", "erase")
        self._alpha: dict = {}              # (tx, ty) -> dernier alpha calculé de chaque pixel (float32 ; 0 = jamais touché = pixel d'origine)
        self._pend: dict = {}               # (tx, ty) -> zone du document à recomposer au prochain `_flush_pixels`
        self._prev_dab = None               # (x, y, abscisse) du tampon précédent : segment balayé et pas réel
        # Aérographe : dépôt TEMPOREL, canal séparé du dépôt spatial (celui-ci n'est pas utilisé pendant un trait d'aérographe).
        self._air = bool(brush.airbrush) and self.mode in ("paint", "erase")
        self._air_cov: dict = {}            # (tx, ty) -> densité déposée par le temps (0..1, jamais décroissante)
        self._air_queue: list = []          # tampons posés pendant ce mouvement, en attente de leur durée
        self._air_owed = 0.0                # secondes écoulées depuis le dernier dépôt, pas encore déposées
        self._air_last = None               # dernière date comptée (horloge `air_now`)
        self.air_seconds = 0.0              # temps total déposé (diagnostic, tests)
        if self._air:
            self._ss = 1
        self.paint_kind = brush.paint_kind()
        # Pointe de petit diamètre : l'ÉTAT du trait (couverture, union) vit sur une grille SUB × SUB par pixel, la seule
        # façon exacte de réunir des tampons rapprochés (un maximum par pixel retirait 32 % d'aire à d = 1, 7 % à d = 2).
        self._ss = SUB if brush.size < 2.0 * SUPER_RADIUS else 1      # (1 = état au pixel, aire exacte du tampon)
        self._pos = None                    # position lissée
        self._last = None                   # (x, y, pression) du dernier tampon posé
        self._finished = False
        self._trail = []                    # chemin du curseur (voir `begin`)
        self._next = 0.0
        self.dirty = None
        self.dabs = 0
        self.zoom = 1.0                     # zoom d'affichage (réglé par l'établi) : longueur de la corde de lissage
        self.trace = None                   # diagnostic : {"raw": [...], "used": [...], "dabs": [...]} rempli si l'établi le demande

    # -- geste --
    # Chaîne d'entrée, étapes SÉPARÉES : (1) trajectoire brute -> (2) trajectoire filtrée par le mode de lissage choisi
    # (aucun = rien) -> (3) pression brute -> pression filtrée (facultative) -> (4) courbes de réponse par paramètre
    # (taille, opacité, débit) -> (5) rééchantillonnage spatial (tampons à pas constant, distance résiduelle conservée)
    # -> (6) rendu des tampons. Hors stabilisateur, la trajectoire est une polyligne EXACTE entre les points filtrés :
    # aucune courbe n'est ajoutée pour masquer l'acquisition.
    @_flushed
    def begin(self, x, y, pressure=1.0, air_now=None):
        x, y, p = float(x), float(y), float(pressure)
        self._mode = self.brush.smoothing_kind()
        self._pos = (x, y)                          # dernière position utilisée par le tracé
        self._raw = (x, y)                          # dernier point brut reçu
        self._cursor = self._pos                    # dernier point filtré (stabilisateur : curseur que la corde suit)
        self._pp = self._pm = self._ptip = p        # pression filtrée ; à l'extrémité de la courbe ; de la pointe
        self._pmax = p
        self._clock_t = None
        self._oe, self._wt, self._rope_f = OneEuro(), Weighted(), Rope(self._pos)
        self._ctrl = self._mid = self._pos          # stabilisateur : contrôle / extrémité de la courbe en cours
        self._trail = [(0.0, p)]                    # chemin du curseur : (longueur d'arc, pression)
        self._trail_xy = self._pos
        self._finished = False
        self._last = (x, y, p)
        self._next = 0.0
        self._arc = 0.0                             # abscisse curviligne du dernier point
        self._heading = (0.0, 0.0)                  # sens moyen récent du geste (voir `_note_heading`)
        self._stamped = False
        self._dab_at = None                         # position du dernier tampon posé
        self.info = {}
        if self.trace is not None:
            self.trace["raw"].append((x, y))
            self.trace["used"].append((x, y))
        if self._air:
            self._air_last = air_now if air_now is not None else 0.0
            self._stamped = True
            self._next = self._step(p)
            self._stamp(x, y, p)                                # point de départ : dépôt initial d'une image (un tap laisse un point)
            self._air_owed = TUNING.air_first
            return self._air_flush()
        dynamic = self.brush.pressure_size or self.brush.pressure_flow or self.brush.pressure_opacity
        return None if dynamic else self._first_stamp()      # (avec pression : au premier déplacement, voir `_segment`)

    def _first_stamp(self):
        """Premier tampon, posé au point de départ avec la pression qu'il porte AU MOMENT du premier mouvement (le premier
        échantillon d'un stylet arrive souvent avec une pression quasi nulle)."""
        x, y, p = self._last
        self._stamped = True
        self._next = self._step(p)
        return self._stamp(x, y, p)

    @_flushed
    def move(self, x, y, pressure=1.0, t=None, air_now=None):
        """Point suivant du geste (`t` : horodatage en secondes, sinon 120 Hz supposés) ; rend la zone modifiée. `air_now` :
        horloge monotone de l'aérographe (secondes ; par défaut `t`)."""
        start = time.perf_counter()
        x, y, p = float(x), float(y), float(pressure)
        now = self._now(t)
        self._raw = (x, y)
        self._pmax = max(self._pmax, p)
        cursor = self._filter(x, y, now)
        if self.trace is not None and len(self.trace["raw"]) < 20000:
            self.trace["raw"].append((x, y))
            self.trace["used"].append(cursor)
        pp = self._pressure(p)
        self._trail_add(cursor, pp)
        if self._mode == "stabilizer":
            self._cursor = cursor
            target = self._rope(cursor)
            dirty = None if target is None else self._advance(target, self._tip_pressure(target, cursor, pp))
        else:
            self._pos = cursor
            dirty = self._segment(cursor[0], cursor[1], pp)
        if self._air:
            self._air_advance(air_now if air_now is not None else now)
            dirty = self._air_flush()
        self.info = {"p_raw": p, "p_filtered": pp, "size": self._size(pp), "opacity": self._opacity_factor(pp),
                     "flow": self._flow_factor(pp), "raw": (x, y), "used": cursor, "t": now,
                     "seconds": time.perf_counter() - start}
        return dirty

    def _now(self, t):
        prev = self._clock_t
        if t is None or (prev is not None and float(t) <= prev):      # horodatage absent ou non croissant : 120 Hz supposés
            t = 0.0 if prev is None else prev + 1.0 / 120.0
        self._clock_t = float(t)
        return self._clock_t

    def _zoom(self) -> float:
        return max(self.zoom, 0.02) if TUNING.zoom_adjust else 1.0

    def _filter(self, x, y, now):
        """Trajectoire filtrée selon le mode. Les réglages sont en pixels d'ÉCRAN : on filtre en espace écran."""
        mode, s = self._mode, self.brush.smoothing
        if mode in ("none", "stabilizer") or s <= 0.0:
            return (x, y)
        z = self._zoom()
        if mode == "adaptive":
            cutoff = TUNING.oe_cutoff_max * (1.0 - s) ** 3 + 0.3
            ox, oy = self._oe.apply(x * z, y * z, now, cutoff, TUNING.oe_beta)
        else:
            ox, oy = self._wt.apply(x * z, y * z, now, s * TUNING.weighted_px)
        return (ox / z, oy / z)

    def _pressure(self, p):
        """Pression filtrée (facultative : `pressure_filter` = 1 laisse la pression brute)."""
        self._pp += (p - self._pp) * min(1.0, max(0.01, TUNING.pressure_filter))
        return self._pp

    # -- stabilisateur « corde tirée » (entièrement séparé du lissage normal) --
    def _rope(self, cursor):
        rope = self.brush.smoothing * TUNING.rope_px / self._zoom()
        tip = self._rope_f.apply(cursor[0], cursor[1], rope)
        if tip is not None:
            self._pos = tip
        return tip

    def _advance(self, target, pressure):
        """La pointe passe à `target` : courbe de l'extrémité précédente au milieu (contrôle = dernier point de la corde)."""
        end = ((self._ctrl[0] + target[0]) / 2.0, (self._ctrl[1] + target[1]) / 2.0)
        end_pressure = (self._ptip + pressure) / 2.0
        dirty = self._curve(end, end_pressure)
        self._ctrl, self._ptip = target, pressure
        return dirty

    # -- pression de la pointe en retard : elle garde la pression qu'avait le curseur à cet endroit du chemin --
    def _trail_add(self, cursor, pressure):
        trail = self._trail
        s = trail[-1][0] + math.hypot(cursor[0] - self._trail_xy[0], cursor[1] - self._trail_xy[1]) if trail else 0.0
        self._trail_xy = cursor
        trail.append((s, pressure))
        if self._mode != "stabilizer" and len(trail) > 3:
            del trail[:-3]                              # seul le stabilisateur relit le chemin

    def _tip_pressure(self, tip, cursor, fallback):
        """Pression au point du chemin du curseur où se trouve la pointe (à `distance(pointe, curseur)` derrière lui)."""
        trail = self._trail
        if not TUNING.pressure_at_tip or len(trail) < 2:
            return fallback
        s_tip = trail[-1][0] - math.hypot(cursor[0] - tip[0], cursor[1] - tip[1])
        while len(trail) > 2 and trail[1][0] <= s_tip:      # le début du chemin, derrière la pointe, ne sert plus
            trail.pop(0)
        (s0, p0), (s1, p1) = trail[0], trail[1]
        if s1 <= s0:
            return p1
        return p0 + (p1 - p0) * min(1.0, max(0.0, (s_tip - s0) / (s1 - s0)))

    @_flushed
    def idle(self):
        """Rattrapage PENDANT une pause (« Stroke Catch-up ») : la pointe avance vers le curseur d'une fraction de l'écart
        à chaque appel (minuterie de l'établi) ; rend la zone modifiée (ou None). Stabilisateur seulement."""
        if self._finished or self._mode != "stabilizer" or self.brush.smoothing <= 0 or not self._trail:
            return None
        (px, py), (cx, cy) = self._pos, self._cursor
        gap = math.hypot(cx - px, cy - py)
        if gap < 0.05:
            return None
        k = min(1.0, max(0.02, TUNING.catch_up_speed))
        f = 1.0 if gap < 0.5 / self._zoom() else k
        self._pos = (px + (cx - px) * f, py + (cy - py) * f)
        self._rope_f.tip = self._pos
        return self._advance(self._pos, self._trail[-1][1])

    def _curve(self, end, end_pressure):
        """Courbe de `_mid` à `end` avec `_ctrl` pour contrôle : posée en petits segments (tampons à pas constant)."""
        (x0, y0), (cx, cy), (x1, y1) = self._mid, self._ctrl, end
        p0 = self._pm
        length = math.hypot(cx - x0, cy - y0) + math.hypot(x1 - cx, y1 - cy)
        n = max(1, int(math.ceil(length / max(0.25, TUNING.curve_chord))))
        dirty = None
        for i in range(1, n + 1):
            t = i / n
            u = 1.0 - t
            px = u * u * x0 + 2 * u * t * cx + t * t * x1
            py = u * u * y0 + 2 * u * t * cy + t * t * y1
            dirty = self._union(dirty, self._segment(px, py, p0 + (end_pressure - p0) * t))
        self._mid, self._pm = (x1, y1), end_pressure
        return dirty

    # -- réponse à la pression : une courbe PAR paramètre, D = Dmax · (m + (1 − m) · f(p)) --
    @staticmethod
    def _shaped(pressure, gamma) -> float:
        return max(0.0, min(1.0, pressure)) ** gamma

    def _spacing(self) -> float:
        """Espacement réellement posé : un trait continu (réglage <= 35 %) est tamponné serré (débit < 100 % ou brosse
        douce : sans perles) ; au-delà, c'est un pointillé voulu."""
        spacing = self.brush.spacing
        return min(spacing, TUNING.continuous_spacing) if spacing <= 0.35 else spacing

    def _size(self, pressure) -> float:
        if not self.brush.pressure_size:
            return self.brush.size
        low = max(0.0, min(1.0, TUNING.min_diameter))
        return self.brush.size * (low + (1.0 - low) * self._shaped(pressure, TUNING.size_gamma))

    def _opacity_factor(self, pressure) -> float:
        return self._shaped(pressure, TUNING.opacity_gamma) if self.brush.pressure_opacity else 1.0

    def _flow_factor(self, pressure) -> float:
        return self._shaped(pressure, TUNING.flow_gamma) if self.brush.pressure_flow else 1.0

    def _step(self, pressure) -> float:
        size = self._size(pressure)
        # Pas minimal : la dentelure entre deux tampons (R − √(R² − (pas/2)²)) reste sous ~0,03 px, soit pas = 0,49·√R pour une
        # pointe fine (état au sous-pixel) ; 0,75 px au-delà. (Plus fin = plus de tampons pour rien : le coût est par tampon.)
        floor = max(0.3, 0.49 * math.sqrt(size / 2.0)) if self._ss > 1 else 0.75
        spacing = self._spacing()
        if self._soft and self._ss == 1 and size / 2.0 >= SUPER_RADIUS and self.brush.spacing <= DOTTED_SPACING:
            # Pointe douce : le balayage continu (union exacte du segment) et la somme de Riemann au point milieu sont stables
            # jusqu'à 16 % d'espacement (mesuré) : deux fois moins de tampons qu'à 8 %, pour un rendu identique.
            spacing = min(self.brush.spacing, 2.0 * TUNING.continuous_spacing)
        return max(floor, spacing * max(1.0, size))

    def _segment(self, x, y, pressure):
        """Pose les tampons le long du segment (dernier point -> (x, y)) : pas constant, reste conservé d'un segment au
        suivant, pression interpolée avec la position."""
        x0, y0, p0 = self._last
        dx, dy = x - x0, y - y0
        dist = math.hypot(dx, dy)
        if dist <= 1e-9:
            if not self._stamped:
                self._last = (x0, y0, pressure)         # immobile : la pression du départ suit
            return None
        dirty = None
        if not self._stamped:
            dirty = self._first_stamp()
            p0 = self._last[2]
        self._note_heading(dx / dist, dy / dist, dist, self._size(pressure))
        d = self._next
        while d <= dist:
            t = d / dist
            p = p0 + (pressure - p0) * t
            dirty = self._union(dirty, self._stamp(x0 + dx * t, y0 + dy * t, p, arc=self._arc + d))
            d += self._step(p)
        self._next = d - dist
        self._arc += dist
        self._last = (x, y, pressure)
        return dirty

    def _note_heading(self, ux, uy, dist, size):
        """Sens moyen RÉCENT du geste (moyenne exponentielle sur une demi-largeur de pointe) : le tremblement d'une main
        lente (petits reculs) s'y noie, un vrai demi-tour le retourne après ~0,35 diamètre de course."""
        k = min(1.0, dist / max(0.5 * size, 1.0))
        vx, vy = self._heading
        self._heading = (vx * (1.0 - k) + ux * k, vy * (1.0 - k) + uy * k)

    @staticmethod
    def _union(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

    # -- un tampon --
    def _stamp(self, x, y, pressure, arc=None):
        """Un tampon posé en (x, y), à l'abscisse curviligne `arc` (distance parcourue depuis le début du trait ; par
        défaut celle du dernier point)."""
        brush = self.brush
        size = self._size(pressure)
        if self.mode == "smudge":
            flow = brush.flow * self._flow_factor(pressure)
            if flow < 1.0:                             # le débit réglé vaut pour l'espacement réglé : on le répartit
                flow = 1.0 - (1.0 - flow) ** (self._spacing() / max(brush.spacing, 1e-6))
            return self._stamp_smudge_at(x, y, size, flow)
        if size < 0.05:
            return None                                # diamètre nul (pression nulle sans diamètre minimum) : rien à poser
        self._dab_at = (x, y)
        if self.trace is not None and len(self.trace["dabs"]) < 60000:
            self.trace["dabs"].append((x, y, size))
        if self._air:                                  # aérographe : la durée de ce tampon n'est connue qu'en fin de mouvement
            arc = self._arc if arc is None else arc
            prev = self._air_queue[-1][4] if self._air_queue else (self._prev_dab[2] if self._prev_dab else arc - self._step(pressure))
            self._air_queue.append((x, y, size, pressure, arc, max(arc - prev, 1e-3)))
            self._prev_dab = (x, y, arc, size)
            return None
        reach = size / 2.0 + 1.0
        box = rect_intersect((int(math.floor(x - reach)), int(math.floor(y - reach)),
                              int(math.ceil(x + reach)), int(math.ceil(y + reach))), self.doc_rect)
        if box is None:
            return None
        arc = self._arc if arc is None else arc
        sweep, step, prev = None, self._step(pressure), self._prev_dab
        if prev is not None and arc - prev[2] <= 3.0 * step + 1e-6:
            step = max(arc - prev[2], 1e-6)                                              # pas RÉEL depuis le tampon précédent
            if self._ss == 1 and size / 2.0 >= SUPER_RADIUS and self._soft:               # pointe douce (dureté < 60 %) : balayage continu
                sweep = (prev[0], prev[1])
                reach = max(size, prev[3]) / 2.0 + 1.0
                box = rect_intersect((int(math.floor(min(x, prev[0]) - reach)), int(math.floor(min(y, prev[1]) - reach)),
                                      int(math.ceil(max(x, prev[0]) + reach)), int(math.ceil(max(y, prev[1]) + reach))), self.doc_rect)
                if box is None:
                    return None
        self._prev_dab = (x, y, arc, size)
        # (diamètre variable : le balayage prend le diamètre MOYEN du segment ; celui du seul tampon courant déborderait de
        # la moitié de la variation sur tout le segment quand la pression monte)
        shape = (dab_alpha(x, y, 0.5 * (size + prev[3]) if sweep else size, brush.hardness, box, to=sweep) if self._ss == 1 else   # FORME : dureté, douceur, anticrénelage
                 _dab_samples(x, y, size, brush.hardness, box))                          # (jamais la quantité de peinture)
        flow = brush.flow * self._flow_factor(pressure)
        ceiling = self._opacity_factor(pressure)                                         # niveau du tampon par la pression
        if self.paint_kind == "buildup":
            amount, envelope = brush.opacity * ceiling * flow, 1.0                      # dose en valeur absolue, sans plafond
        else:
            amount, envelope = ceiling * flow, ceiling                                   # dose relative au plafond (= opacité)
        self.dabs += 1
        soft = _soft_weight(brush.hardness, size)
        weight = min(1.0, step / max(TUNING.soft_union * size, 1e-6)) * (1.0 if prev is not None else 0.5) if soft > 0.0 else 0.0   # (règle du trapèze : le 1er tampon ne vaut qu'un demi-pas)
        haz = None
        if soft > 0.0:                              # somme de Riemann de l'union douce : tampon au MILIEU du segment (règle du point
            cx, cy = (x, y) if sweep is None else (0.5 * (x + sweep[0]), 0.5 * (y + sweep[1]))     # milieu, erreur en pas²)
            mid = shape if (sweep is None and self._ss > 1) else _point_profile(cx, cy, size, brush.hardness, box)
            haz = weight * (-np.log1p(-np.minimum(mid, 0.98)))
        for ty in range(box[1] // TILE, (box[3] - 1) // TILE + 1):
            for tx in range(box[0] // TILE, (box[2] - 1) // TILE + 1):
                self._apply_tile(tx, ty, box, shape, amount, envelope, arc, DOTTED_SPACING * size, self._heading, soft, haz, prev is None)
        self.dirty = self._union(self.dirty, box)
        return box

    def _tile(self, tx, ty):
        key = (tx, ty)
        if key not in self._orig:
            rect = rect_intersect((tx * TILE, ty * TILE, tx * TILE + TILE, ty * TILE + TILE), self.doc_rect)
            self._orig[key] = (rect, self.plane.read(rect))
            pixels = (rect[3] - rect[1], rect[2] - rect[0])
            if self._air:
                self._air_cov[key] = np.zeros(pixels, np.float32)
                return self._orig[key], self._air_cov[key]
            state = pixels + ((self._ss,) if self._ss > 1 else ())
            self._cov[key] = np.zeros(state, np.float32)
            self._geo[key] = np.zeros(state, np.float32)
            self._base[key] = np.zeros(pixels, np.float32)
            self._seen[key] = np.full(pixels, -1e9, np.float32)
            self._way[key] = (np.zeros(pixels, np.float32), np.zeros(pixels, np.float32))
            if self._soft:
                self._lam[key] = np.zeros(state, np.float32)
        return self._orig[key], (self._air_cov[key] if self._air else self._cov[key])

    def _apply_tile(self, tx, ty, box, shape, amount, envelope, arc, gap, heading, soft=0.0, haz=None, first=False):
        """Met à jour l'état du trait sur la part de `box` dans cette tuile, puis recompose les pixels depuis la COPIE
        D'ORIGINE de la tuile (idempotent : rien n'est appliqué deux fois). Trois quantités SÉPARÉES par pixel :

        - FORME `s` (couverture géométrique × douceur du tampon) : ne dépend jamais de la quantité de peinture ;
        - PASSAGE courant `cur = max(montant · s)` sur les tampons VOISINS qui forment un même passage : le maximum ne
          compte pas deux fois une même peinture (un rééchantillonnage plus dense ne change rien) et ne recule jamais ;
        - DENSITÉ des passages terminés `base`. Un pixel que le pinceau retrouve après l'avoir quitté de plus de `gap`
          (abscisse curviligne : 35 % du diamètre), ou qu'un geste de SENS INVERSE retrouve (demi-tour), est un VRAI retour : le passage courant est versé dans `base`
          (`base ← base + (1 − base)·cur`, alpha_final = ancien + apport·(1 − ancien)) et un nouveau passage commence.

        Alpha final = min(base ⊕ cur, enveloppe) · échelle, `base ⊕ cur = 1 − (1 − base)(1 − cur)`. L'enveloppe (max des
        formes) borne les pixels de bord (leur forme partielle ne tend jamais vers 1 par les retours). Premier passage :
        `cur = montant · s`, plateau homogène, bord = transition de la forme, aucune atténuation liée à la distance
        parcourue (plus d'« effet de tube »). Plafond : montant relatif à l'opacité (échelle finale = opacité)."""
        (trect, orig), cov = self._tile(tx, ty)
        sub = rect_intersect(box, trect)
        if sub is None:
            return
        key = (tx, ty)
        ly0, ly1, lx0, lx1 = sub[1] - trect[1], sub[3] - trect[1], sub[0] - trect[0], sub[2] - trect[0]
        part = shape[sub[1] - box[1]:sub[3] - box[1], sub[0] - box[0]:sub[2] - box[0]]
        if self._defer and not np.count_nonzero(part) and (soft <= 0.0 or key not in self._lam or not (
                np.count_nonzero(haz[sub[1] - box[1]:sub[3] - box[1], sub[0] - box[0]:sub[2] - box[0]])
                or np.count_nonzero(self._lam[key][ly0:ly1, lx0:lx1]))):
            return      # rien sous ce tampon dans cette tuile : état et pixels inchangés (peinture / gomme / masque : la recomposition est idempotente ;
                        # pas les outils de retouche, dont le flou et l'arrondi du prémultiplié dépendent de la zone écrite)
        cur = cov[ly0:ly1, lx0:lx1]
        geo = self._geo[key][ly0:ly1, lx0:lx1]
        base = self._base[key][ly0:ly1, lx0:lx1]
        seen = self._seen[key][ly0:ly1, lx0:lx1]
        wx, wy = self._way[key][0][ly0:ly1, lx0:lx1], self._way[key][1][ly0:ly1, lx0:lx1]
        sampled = self._ss > 1
        touched = (part.max(axis=-1) if sampled else part) > 1e-4
        # retour = pixel quitté depuis plus de `gap`, OU retrouvé par un geste de sens inverse (demi-tour : le bout du trait)
        fresh = touched & (((arc - seen) > gap) | (wx * heading[0] + wy * heading[1] < -0.25))
        if np.count_nonzero(fresh):
            done = cur.mean(axis=-1) if sampled else cur
            np.copyto(base, base + (1.0 - base) * done, where=fresh)
            np.copyto(cur, 0.0, where=fresh[..., None] if sampled else fresh)
            np.copyto(wx, heading[0], where=fresh)
            np.copyto(wy, heading[1], where=fresh)    # sens du geste au DÉBUT du passage de ce pixel (pas à chaque contact)

        np.putmask(seen, touched, arc)
        if soft > 0.0 and key in self._lam:
            # Union « sur » normalisée des pointes douces (comme les pinceaux de Photoshop : le recouvrement de deux zones
            # molles se fond au lieu de laisser une rainure ; une trajectoire qui ondule est moyennée sur ~un rayon). Hasard
            # cumulé Λ += (pas / (k·D)) · (−ln(1 − s)), S = 1 − e^(−Λ) : sans pas (limite continue), indépendant de la
            # densité des tampons. La forme du passage est un MÉLANGE de la pointe balayée seule et de cette union, pondéré par la
            # douceur (dureté <= 50 % : union seule, comme Photoshop ; >= 80 % : aucun changement) ; ne touche ni le montant ni
            # les retours. (Un maximum avec la pointe seule gardait les lobes de la trajectoire dans la frange faible.)
            lam = self._lam[key][ly0:ly1, lx0:lx1]
            lam += haz[sub[1] - box[1]:sub[3] - box[1], sub[0] - box[0]:sub[2] - box[0]]
            if not first:                              # (le tout premier tampon reste entier : un simple appui garde son cœur plein)
                part = (1.0 - soft) * part + soft * (1.0 - np.exp(-lam))
        np.maximum(cur, part * amount, out=cur)
        np.maximum(geo, part * envelope, out=geo)
        now = cur.mean(axis=-1) if sampled else cur
        if np.count_nonzero(base):                      # (premier passage : `cur` <= forme <= enveloppe, la borne est sans effet)
            bound = geo.mean(axis=-1) if sampled else geo
            alpha = np.minimum(1.0 - (1.0 - base) * (1.0 - now), bound)
        else:
            alpha = now
        if self.paint_kind != "buildup":
            alpha = alpha * self.brush.opacity
        if self.selection is not None:
            alpha = alpha * self.selection.coverage(sub)
        if self._defer:
            buf = self._alpha.get(key)
            if buf is None:
                buf = self._alpha[key] = np.zeros((trect[3] - trect[1], trect[2] - trect[0]), np.float32)
            buf[ly0:ly1, lx0:lx1] = alpha
            known = self._pend.get(key)
            self._pend[key] = sub if known is None else (min(known[0], sub[0]), min(known[1], sub[1]),
                                                         max(known[2], sub[2]), max(known[3], sub[3]))
            return
        before = orig[ly0:ly1, lx0:lx1]
        self.plane.write(sub, self._result(before, alpha, sub))

    def _flush_pixels(self):
        """Recompose, UNE fois par tuile, la zone touchée depuis la copie d'origine et l'alpha courant de chaque pixel (les
        pixels de la zone non touchés par l'évènement gardent leur dernier alpha : même valeur qu'avant, la recomposition est
        idempotente ; un pixel jamais touché a l'alpha 0 et reste le pixel d'origine)."""
        pending, self._pend = self._pend, {}
        for key, rect in pending.items():
            trect, orig = self._orig[key]
            ly0, ly1, lx0, lx1 = rect[1] - trect[1], rect[3] - trect[1], rect[0] - trect[0], rect[2] - trect[0]
            self.plane.write(rect, self._result(orig[ly0:ly1, lx0:lx1], self._alpha[key][ly0:ly1, lx0:lx1], rect))

    # -- aérographe : dépôt TEMPOREL --
    # Canal `air` par pixel, SÉPARÉ du dépôt spatial (base / cur / enveloppe, intact) : chaque tampon porte la durée `dt` qu'il a
    # « exposée » et dépose  air ← 1 − (1 − air)·e^(−K·s·dt)  (s = forme du tampon, K = intensité par seconde). Deux mises à jour
    # de durées dt1 et dt2 valent exactement une seule de dt1 + dt2 : le résultat ne dépend pas de la fréquence des mises à jour.
    # Immobile : la peinture continue de s'ajouter au même endroit ; en mouvement : la durée d'un déplacement est répartie sur
    # les tampons posés (lent = exposition longue, rapide = courte). Plafond : l'air monte vers 1 (échelle finale = opacité, jamais
    # dépassée) avec une vitesse réglée par le débit ; Accumulation : vitesse réglée par opacité × débit, sans plafond.
    def _air_advance(self, now):
        """Compte le temps écoulé jusqu'à `now` (horloge monotone), borné par `air_dt_max`."""
        if self._air_last is None:
            self._air_last = now
        dt = max(0.0, min(now - self._air_last, TUNING.air_dt_max))
        self._air_last = now
        self._air_owed += dt

    @_flushed
    def air_tick(self, now):
        """Mise à jour de la minuterie (stylet immobile ou non) : dépose, à la dernière position et avec la dernière pression
        valide, le temps écoulé depuis le dernier dépôt. Rend la zone modifiée (ou None). Sans effet après le relâchement."""
        if not self._air or self._finished or self._last is None:
            return None
        self._air_advance(now)
        if not self._air_queue:
            x, y, _p = self._last
            self._stamp(x, y, self._pp)
        return self._air_flush()

    def _air_flush(self):
        """Dépose les tampons en attente en leur répartissant le temps dû (proportionnellement à leur pas)."""
        queue, owed = self._air_queue, self._air_owed
        if not queue or owed <= 0.0:
            return None
        self._air_queue, self._air_owed = [], 0.0
        total = sum(q[5] for q in queue)
        dirty = None
        for x, y, size, pressure, _arc, step in queue:
            dirty = self._union(dirty, self._air_dab(x, y, size, pressure, owed * step / total))
        self.air_seconds += owed
        return dirty

    def _air_dab(self, x, y, size, pressure, dt):
        brush = self.brush
        flow = brush.flow * self._flow_factor(pressure)
        level = self._opacity_factor(pressure)
        a = flow * level if self.paint_kind != "buildup" else brush.opacity * level * flow
        a = min(0.99, max(0.0, a))
        if a <= 0.0 or dt <= 0.0:
            return None
        rate = -math.log(1.0 - a) * TUNING.air_rate                   # intensité K (1/s) : « a par seconde » à forme pleine
        reach = size / 2.0 + 1.0
        box = rect_intersect((int(math.floor(x - reach)), int(math.floor(y - reach)),
                              int(math.ceil(x + reach)), int(math.ceil(y + reach))), self.doc_rect)
        if box is None:
            return None
        shape = dab_alpha(x, y, size, brush.hardness, box)
        self.dabs += 1
        for ty in range(box[1] // TILE, (box[3] - 1) // TILE + 1):
            for tx in range(box[0] // TILE, (box[2] - 1) // TILE + 1):
                self._air_tile(tx, ty, box, shape, rate * dt)
        self.dirty = self._union(self.dirty, box)
        return box

    def _air_tile(self, tx, ty, box, shape, exposure):
        (trect, orig), air = self._tile(tx, ty)
        sub = rect_intersect(box, trect)
        if sub is None:
            return
        ly0, ly1, lx0, lx1 = sub[1] - trect[1], sub[3] - trect[1], sub[0] - trect[0], sub[2] - trect[0]
        part = shape[sub[1] - box[1]:sub[3] - box[1], sub[0] - box[0]:sub[2] - box[0]]
        cell = air[ly0:ly1, lx0:lx1]
        cell[...] = 1.0 - (1.0 - cell) * np.exp(-exposure * part)      # alpha_nouveau = 1 − (1 − alpha_ancien)·e^(−K·dt)
        alpha = cell if self.paint_kind == "buildup" else cell * self.brush.opacity
        if self.selection is not None:
            alpha = alpha * self.selection.coverage(sub)
        self.plane.write(sub, self._result(orig[ly0:ly1, lx0:lx1], alpha, sub))

    # -- lecture de la copie du début du trait --
    def _snap_read(self, rect) -> np.ndarray:
        """Pixels de la copie (transparents hors du document)."""
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        out = np.zeros((h, w, 4), np.uint8)
        common = rect_intersect(rect, self.doc_rect)
        if common is not None:
            out[common[1] - rect[1]:common[3] - rect[1], common[0] - rect[0]:common[2] - rect[0]] = \
                self._snap[common[1] - self.doc_rect[1]:common[3] - self.doc_rect[1],
                           common[0] - self.doc_rect[0]:common[2] - self.doc_rect[0]]
        return out

    @staticmethod
    def _lerp_straight(dest: np.ndarray, src: np.ndarray, alpha: np.ndarray) -> np.ndarray:
        """Mélange (1 − α)·destination + α·source en couleurs prémultipliées, rendu en couleurs droites."""
        a = alpha[..., None]
        pd, ps = C.premultiplied(dest), C.premultiplied(src)
        return C.to_straight_u8(pd * (1.0 - a) + ps * a)

    def _result(self, before: np.ndarray, alpha: np.ndarray, rect=None) -> np.ndarray:
        brush = self.brush
        mode = self.mode
        if self.target != "mask" and mode not in ("paint", "erase"):
            return self._retouch(mode, before, alpha, rect)
        if self.target == "mask":
            value = 0.299 * brush.color[0] + 0.587 * brush.color[1] + 0.114 * brush.color[2]
            if brush.eraser:
                value = 255.0               # gomme dans un masque : révèle
            m = before[..., 0].astype(np.float32)
            return _uclip(m + (value - m) * alpha + 0.5, 0, 255).astype(np.uint8)[..., None]
        old_a = before[..., 3].astype(np.float32) * (1.0 / 255.0)
        if mode == "erase":
            out = before.copy()
            out[..., 3] = _uclip(old_a * (1.0 - alpha) * 255.0 + 0.5, 0, 255)
            return out
        new_a = alpha + old_a * (1.0 - alpha)
        weight = np.where(new_a > 1e-6, alpha / np.maximum(new_a, 1e-6), 0.0)
        # Couleur CANAL D'ABORD (3, h, l) : la diffusion d'un poids (h, l, 1) sur 3 canaux entrelacés boucle sur une dimension
        # de 3 éléments (sans SIMD) ; mêmes opérations, mêmes arrondis, 1,4 à 2,4 fois plus vite (identique octet pour octet).
        color = np.array(brush.color, np.float32)
        rgb = before[..., :3].transpose(2, 0, 1).astype(np.float32, order="C") * (1.0 - weight)[None] + color[:, None, None] * weight[None]
        out = np.empty_like(before)
        out[..., :3] = _uclip(rgb + 0.5, 0, 255).transpose(1, 2, 0)
        out[..., 3] = _uclip(new_a * 255.0 + 0.5, 0, 255)
        return out

    def _retouch(self, mode, before, alpha, rect):
        brush = self.brush
        if mode == "clone":
            dx, dy = self.retouch["offset"]
            src = self._snap_read((rect[0] + dx, rect[1] + dy, rect[2] + dx, rect[3] + dy))
            return self._lerp_straight(before, src, alpha)
        if mode in ("blur", "sharpen"):
            m = filters.margin(brush.sigma)
            ctx = self._snap_read((rect[0] - m, rect[1] - m, rect[2] + m, rect[3] + m))
            premult = C.premultiplied(ctx)
            done = (filters.gaussian_blur(premult, brush.sigma) if mode == "blur" else
                    filters.unsharp(premult, 1.5, brush.sigma))
            return self._lerp_straight(before, C.to_straight_u8(done)[m:-m, m:-m], alpha)
        if mode == "heal":
            return self._heal(before, alpha, rect)
        rgb = before[..., :3].astype(np.float32)
        a = alpha[..., None]
        out = before.copy()
        if mode == "dodge":
            out[..., :3] = np.clip(rgb + (255.0 - rgb) * a + 0.5, 0, 255)
        else:                                                 # burn
            out[..., :3] = np.clip(rgb * (1.0 - a) + 0.5, 0, 255)
        return out

    def _heal(self, before, alpha, rect):
        """Correcteur : basses fréquences (tons) de la DESTINATION + hautes fréquences (texture) de la SOURCE, sur des
        couleurs pondérées par l'alpha (convolution normalisée). Ce n'est ni un collage ni un simple flou ; ce n'est pas
        une reconstruction de Poisson (limite documentée)."""
        sigma = max(0.5, self.brush.sigma)
        m = filters.margin(sigma)
        dx, dy = self.retouch["offset"]
        dest = self._snap_read((rect[0] - m, rect[1] - m, rect[2] + m, rect[3] + m))
        src = self._snap_read((rect[0] + dx - m, rect[1] + dy - m, rect[2] + dx + m, rect[3] + dy + m))

        def low(ctx):
            p = C.premultiplied(ctx)
            blurred = filters.gaussian_blur(p, sigma)
            a = blurred[..., 3:4]
            return np.where(a > 1e-4, blurred[..., :3] / np.maximum(a, 1e-4), 0.0)
        src_rgb = src[..., :3].astype(np.float32) / 255.0
        healed = low(dest) + (src_rgb - low(src))
        healed = np.clip(healed[m:-m, m:-m] * 255.0 + 0.5, 0, 255)
        out = before.copy()
        a = (alpha * (before[..., 3] > 0))[..., None]
        out[..., :3] = np.clip(before[..., :3] * (1.0 - a) + healed * a + 0.5, 0, 255)
        return out

    def _stamp_smudge_at(self, x, y, size, flow):
        """Doigt : la boîte du tampon a une taille CONSTANTE (centrée sur le pixel entier le plus proche, de côté fixé par
        le diamètre maximal), même au bord du document : la couleur emportée est alors conservée d'un tampon au suivant
        (une boîte dont la taille varie d'un pixel d'un tampon à l'autre la réinitialisait et ne traînait rien)."""
        half = int(math.ceil(self.brush.size / 2.0)) + 1
        fx, fy = int(math.floor(x)), int(math.floor(y))
        full = (fx - half, fy - half, fx + half + 1, fy + half + 1)
        dab = dab_alpha(x, y, size, self.brush.hardness, full) * flow
        self.dabs += 1
        common = rect_intersect(full, self.doc_rect)
        if common is None:
            return None
        self._stamp_smudge(full, common, dab)
        self.dirty = self._union(self.dirty, common)
        return common

    def _stamp_smudge(self, full, common, dab):
        """Emporte les couleurs du tampon précédent et les dépose sous le nouveau (effet de traînée)."""
        for ty in range(common[1] // TILE, (common[3] - 1) // TILE + 1):
            for tx in range(common[0] // TILE, (common[2] - 1) // TILE + 1):
                self._tile(tx, ty)                           # copie d'origine de la tuile (annulation)
        w, h = full[2] - full[0], full[3] - full[1]
        ys, xs = slice(common[1] - full[1], common[3] - full[1]), slice(common[0] - full[0], common[2] - full[0])
        cur = np.zeros((h, w, 4), np.float32)
        cur[ys, xs] = C.premultiplied(self.plane.read(common))
        strength = np.minimum(dab, 1.0) * self.brush.opacity
        if self.selection is not None:
            cover = np.zeros((h, w), np.float32)
            cover[ys, xs] = self.selection.coverage(common)
            strength = strength * cover
        carry = self._carry
        if carry is None:
            self._carry = cur
            return
        s = strength[..., None]
        out = cur * (1.0 - s) + carry * s
        self.plane.write(common, C.to_straight_u8(out[ys, xs]))
        self._carry = out

    # -- fin --
    @_flushed
    def finish_to(self, x, y, pressure=1.0):
        """Termine la courbe au dernier point (la pression du relâchement, souvent nulle, est ignorée)."""
        if self._pos is None or self._finished:
            return None
        self._finished = True
        if self._air:                                   # relâchement : le dépôt s'arrête, AUCUN tampon supplémentaire
            self._air_queue.clear()
            return None
        x, y = float(x), float(y)
        if self._mode == "stabilizer":
            end_pressure = self._ptip
            if not TUNING.catch_up_end:                 # le trait finit où la pointe est (pas de rattrapage)
                x, y = self._pos
            else:                                       # rattrapage : la pression glisse vers la dernière pression du curseur
                end_pressure = self._pp                 # (pas d'épaisseur figée de la pointe en retard sur tout le segment)
            dirty = self._curve((x, y), end_pressure)
        else:
            # Tracé direct : il finit sur le dernier point reçu, avec la dernière pression FILTRÉE (celle du relâchement,
            # souvent nulle, n'est jamais utilisée) ; aucun segment artificiel si le point est déjà atteint.
            dirty = self._segment(x, y, self._pp)
        if not self._stamped:                           # simple appui sans déplacement : un point, à la pression maximale
            self._last = (self._last[0], self._last[1], self._pmax)
            dirty = self._union(dirty, self._first_stamp())
        elif self._dab_at is not None and math.hypot(self._last[0] - self._dab_at[0], self._last[1] - self._dab_at[1]) > 0.05:
            dirty = self._union(dirty, self._stamp(*self._last))     # le trait finit EXACTEMENT au dernier point (bout rond complet)
        return dirty

    def end(self, label: str = "Pinceau"):
        """Étape d'annulation (zone touchée seulement), ou None si rien n'a changé."""
        if self._pos is not None and not self._finished:
            self.finish_to(*self._raw)                       # (appelant sans `finish_to` : on rejoint le dernier point)
        if self._pend:
            self._flush_pixels()
        if not self._orig:
            return None
        pieces = []
        for rect, before in self._orig.values():
            after = self.plane.read(rect)
            if not np.array_equal(before, after):
                pieces.append((rect, before, after))
        if not pieces:
            return None
        return TilesCommand(label, self.layer, self.target, pieces)
