"""Couleurs dérivées des icônes Flat Couleur à partir de la couleur d'un module (OKLCH, sans Qt, sans état).

La couleur d'un module (réglages de l'appli) devient la DOMINANTE de ses icônes ; deux tons dérivés l'accompagnent :
- `module`        : la dominante. Gardée TELLE QUELLE si elle est déjà lisible sur le fond sombre des icônes
                    (clarté OKLCH dans [L_MIN, L_MAX], chroma <= C_MAX) ; sinon ramenée dans cette plage à teinte
                    constante (une couleur très sombre, très claire ou fluo reste reconnaissable).
- `module_clair`  : reflets, surfaces secondaires claires (plus clair, moins saturé).
- `module_sombre` : ombres, pièces structurelles (plus sombre, chroma plafonnée).
Les calculs se font en OKLCH (perception uniforme) ; le retour en sRGB réduit la chroma à clarté et teinte constantes
quand la couleur sort du gamut (jamais d'écrêtage canal par canal, qui fausse la teinte).
Les couleurs neutres (neutre, encre) et sémantiques (erreur, avertissement) ne dépendent jamais d'un module.

Même fonction pour les SVG maîtres (tons de référence) et pour l'affichage : `derive(référence)` rend la référence
elle-même pour `module`, donc une icône affichée avec la couleur de référence est identique à son fichier.
Docs : docs/agents/fm_theme.md, « Icônes de la bibliothèque : couleurs des modules »."""
import functools
import math

ROLES = ("module", "module_clair", "module_sombre")
FOND = "#202630"          # fond de référence des chartes (icônes sur fond sombre)
ENCRE = "#263444"         # signes internes sur les aplats
L_MIN, L_MAX, C_MAX = 0.63, 0.88, 0.20     # 0.63 : contraste >= 3,5 sur le fond ET sous l'encre
CLAIR_DL, CLAIR_L_MAX, CLAIR_C = 0.09, 0.94, 0.65
SOMBRE_DL, SOMBRE_L_MIN, SOMBRE_C_MAX = 0.17, 0.46, 0.16


def normaliser(value) -> str | None:
    """« #RGB », « #RRGGBB », « #AARRGGBB » (Qt) -> « #RRGGBB » en majuscules ; None si ce n'est pas une couleur."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("#"):
        return None
    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    elif len(digits) == 8:
        digits = digits[2:]
    if len(digits) != 6:
        return None
    try:
        int(digits, 16)
    except ValueError:
        return None
    return "#" + digits.upper()


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = normaliser(hex_color)
    if h is None:
        raise ValueError(f"couleur invalide : {hex_color!r}")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def oklch(hex_color: str) -> tuple[float, float, float]:
    """(L 0..1, C, h en degrés) d'une couleur sRGB."""
    r, g, b = (_lin(c) for c in _rgb(hex_color))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _lineaire(L: float, C: float, h: float) -> tuple[float, float, float]:
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def _dans_gamut(rgb) -> bool:
    return all(-1e-6 <= c <= 1 + 1e-6 for c in rgb)


def depuis_oklch(L: float, C: float, h: float) -> str:
    """Couleur sRGB « #RRGGBB » ; hors gamut : chroma réduite par dichotomie (clarté et teinte gardées)."""
    L = min(max(L, 0.0), 1.0)
    rgb = _lineaire(L, C, h)
    if not _dans_gamut(rgb):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            if _dans_gamut(_lineaire(L, mid, h)):
                lo = mid
            else:
                hi = mid
        rgb = _lineaire(L, lo, h)
    return "#" + "".join(f"{round(min(max(_gam(min(max(c, 0.0), 1.0)), 0.0), 1.0) * 255):02X}" for c in rgb)


def luminance(hex_color: str) -> float:
    r, g, b = (_lin(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs."""
    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


def derive(dominante: str) -> dict[str, str]:
    """Rôles `module`, `module_clair`, `module_sombre` dérivés de la couleur d'un module (voir l'en-tête)."""
    source = normaliser(dominante)
    if source is None:
        raise ValueError(f"couleur invalide : {dominante!r}")
    return dict(zip(ROLES, _derive(source)))


@functools.lru_cache(maxsize=512)
def _derive(source: str) -> tuple[str, str, str]:
    L, C, h = oklch(source)
    if L_MIN <= L <= L_MAX and C <= C_MAX:
        module = source                                   # déjà lisible : la couleur choisie, au chiffre près
    else:
        L = min(max(L, L_MIN), L_MAX)
        C = min(C, C_MAX)
        module = depuis_oklch(L, C, h)
        L, C, _ = oklch(module)                           # chroma réellement atteinte (gamut)
    clair = depuis_oklch(min(L + CLAIR_DL, CLAIR_L_MAX), C * CLAIR_C, h)
    sombre = depuis_oklch(max(L - SOMBRE_DL, SOMBRE_L_MIN), min(C, SOMBRE_C_MAX), h)
    return module, clair, sombre
