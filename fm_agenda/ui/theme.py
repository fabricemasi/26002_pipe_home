"""Thème de l'agenda : jetons du design Claude Design (`Agenda — sombre`, Main.dc.html), SOURCE UNIQUE des valeurs
graphiques du module (couleurs, polices, métriques). Changer l'apparence = changer ce fichier (ou les réglages
`agenda_theme`, `agenda_accent`, `agenda_today_color`), jamais le moteur.

Thème sombre : le design le dérive de la palette `M` de fm_theme (fond, barres, filets, champs, boutons, accent) ;
ces jetons sont relus dans `M` à chaque construction du thème : l'agenda suit le thème de l'appli. Thème clair :
valeurs du design.

Couleurs d'événements : familles nommées (fond / barre / texte par thème, celles du design pour bleu, violet,
orange, vert, rouge) ; une couleur libre « #rrggbb » (calendrier Google) donne des teintes dérivées de la même
façon que le design (fond = barre mêlée au fond de la page, texte = barre éclaircie / assombrie)."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QColor, QFont, QFontMetrics

# -- jetons du design (CSS --xxx) --------------------------------------------------------------------------------
TOKENS = {
    "sombre": {
        "bg": "#16181a", "side": "#121416", "bar": "#1b1e21", "line": "#2a2e32", "grid": "#262a2e",
        "grid_half": "#1d2023", "field": "#101214", "field_line": "#2e343a", "text": "#d6d9dc", "strong": "#eef0f2",
        "muted": "#a3aab0", "dim": "#8a9197", "off": "#5d656b", "btn": "#262b30", "btn_line": "#353b41",
        "btn_fg": "#c4cacf", "seg": "#101214", "week": "#23282d", "hover": "#1d2125",
        "weekend": "rgba(255,255,255,0.02)", "todaycol": "rgba(95,155,208,0.05)", "today_text": "#f0716a",
        "section": "#5f9bd0", "link": "#5f9bd0", "on_accent": "#f2f6f9",
    },
    "clair": {
        "bg": "#f7f8f9", "side": "#eef0f2", "bar": "#e7eaec", "line": "#d3d8dc", "grid": "#e1e4e7",
        "grid_half": "#eef0f2", "field": "#ffffff", "field_line": "#c5cbd0", "text": "#23292d", "strong": "#101315",
        "muted": "#4b545b", "dim": "#5c656c", "off": "#7d868d", "btn": "#ffffff", "btn_line": "#c5cbd0",
        "btn_fg": "#2b3236", "seg": "#dadee2", "week": "#dde3e9", "hover": "#eceff2",
        "weekend": "rgba(20,35,50,0.035)", "todaycol": "rgba(63,111,159,0.06)", "today_text": "#b8322a",
        "section": "#2f6aa3", "link": "#2f6aa3", "on_accent": "#f2f6f9",
    },
}
# Jetons du thème sombre relus dans la palette M de fm_theme (même valeur par défaut que le design).
_FROM_M = {"bg": "panel_bg", "bar": "toolbar_bg", "line": "panel_border", "field": "field_bg",
           "field_line": "field_border", "btn": "btn_bg", "btn_line": "btn_border", "btn_fg": "btn_fg",
           "section": "section_title", "seg": "field_bg"}

EVENT_COLORS = {
    "sombre": {
        "bleu": ("#1f3550", "#4c8ed1", "#d4e6f8"), "violet": ("#2e2a4a", "#8b7fd6", "#e2defb"),
        "orange": ("#42321a", "#d39a45", "#f6e4c6"), "vert": ("#1d3a2d", "#3fa274", "#cfeedd"),
        "rouge": ("#45221f", "#d9574c", "#f8d4cf"), "cyan": ("#173a42", "#3aa6b9", "#cdeef3"),
        "rose": ("#43213a", "#d0609e", "#f7d3e8"), "gris": ("#2a2f34", "#8a9197", "#dde1e4"),
    },
    "clair": {
        "bleu": ("#dbe8f6", "#2f6eae", "#163a5e"), "violet": ("#e6e2f8", "#6a5cc4", "#31296b"),
        "orange": ("#f7e6cb", "#b77a22", "#573808"), "vert": ("#d8eee2", "#2a8159", "#14442f"),
        "rouge": ("#f8dcd8", "#c23f35", "#6a1c16"), "cyan": ("#d4eef2", "#23899b", "#0f3e47"),
        "rose": ("#f6dcea", "#b4407f", "#5c1a3f"), "gris": ("#e3e6e9", "#6b747b", "#262c30"),
    },
}

DEFAULT_ACCENT = "#3f6f9f"
DEFAULT_TODAY = "#cc3d35"
ACCENT_CHOICES = ("#3f6f9f", "#3f8f6b", "#8b7fd6", "#c2914a")
TODAY_CHOICES = ("#cc3d35", "#3f6f9f", "#c2914a")

# -- métriques du design (px logiques) ---------------------------------------------------------------------------
METRICS = {
    "font_base": 13, "header_pad_v": 10, "header_pad_h": 16, "header_gap": 10, "btn_h": 32, "btn_radius": 6,
    "seg_h": 26, "seg_pad": 2, "seg_radius": 7, "seg_item_radius": 5, "seg_item_pad": 14, "search_w": 220,
    "sidebar_w": 272, "side_pad_top": 12, "side_pad_h": 16, "side_pad_bottom": 14, "mini_week_col": 22,
    "mini_head_h": 20, "mini_row_h": 31, "mini_num": 22, "mini_nav": 28, "gutter": 56, "hour_h": 52,
    "allday_min_h": 32, "day_head_h": 51, "ev_radius": 4, "ev_bar": 3, "ev_min_h": 22, "month_week_col": 40,
    "month_head_h": 32, "month_row_min": 112, "chip_h": 18, "details_w": 300, "details_min": 260,
    "details_max": 340,
}

FONT_FAMILIES = ("Segoe UI", "Inter", "Arial")
MONO_FAMILIES = ("Consolas", "Cascadia Mono", "Courier New")

_WEIGHTS = {300: QFont.Weight.Light, 400: QFont.Weight.Normal, 500: QFont.Weight.Medium,
            600: QFont.Weight.DemiBold, 700: QFont.Weight.Bold}


def parse_color(text: str) -> QColor:
    text = (text or "").strip()
    if text.startswith("rgba(") and text.endswith(")"):
        parts = [p.strip() for p in text[5:-1].split(",")]
        r, g, b = (int(float(x)) for x in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return QColor(r, g, b, round(a * 255))
    return QColor(text)


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def with_alpha(c: QColor, alpha: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, alpha)))
    return out


@lru_cache(maxsize=256)
def font(px: int, weight: int = 400, mono: bool = False, italic: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(list(MONO_FAMILIES if mono else FONT_FAMILIES))
    f.setPixelSize(max(6, int(px)))
    f.setWeight(_WEIGHTS.get(weight, QFont.Weight.Normal))
    f.setItalic(italic)
    f.setHintingPreference(QFont.PreferNoHinting)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


@lru_cache(maxsize=256)
def metrics(px: int, weight: int = 400, mono: bool = False) -> QFontMetrics:
    return QFontMetrics(font(px, weight, mono))


class AgendaTheme:
    """Jetons résolus en QColor pour un thème, un accent et une couleur « aujourd'hui »."""

    def __init__(self, name: str = "sombre", accent: str | None = None, today: str | None = None,
                 density: str = "normal"):
        self.name = name if name in TOKENS else "sombre"
        raw = dict(TOKENS[self.name])
        m_accent = None
        if self.name == "sombre":
            try:
                from fm_theme.tokens import M
                for key, mkey in _FROM_M.items():
                    if M.get(mkey):
                        raw[key] = M[mkey]
                m_accent = M.get("accent")
            except Exception:                            # noqa: BLE001 - fm_theme absent : valeurs du design
                pass
        self._c = {k: parse_color(v) for k, v in raw.items()}
        self._c["accent"] = QColor(accent or m_accent or DEFAULT_ACCENT)
        self._c["today"] = QColor(today or DEFAULT_TODAY)
        self._events: dict[str, tuple[QColor, QColor, QColor]] = {}
        self.dark = self.name == "sombre"
        self.density = density
        scale = {"compacte": 0.85, "normal": 1.0, "confortable": 1.15}.get(density, 1.0)
        self.m = dict(METRICS)
        for key in ("mini_row_h", "allday_min_h", "month_row_min"):
            self.m[key] = round(METRICS[key] * scale)

    def c(self, key: str) -> QColor:
        return self._c[key]

    def hexc(self, key: str) -> str:
        return self._c[key].name()

    def event(self, color: str | None) -> tuple[QColor, QColor, QColor]:
        """(fond, barre, texte) d'une couleur d'événement (famille nommée ou « #rrggbb »)."""
        key = color or "bleu"
        cached = self._events.get(key)
        if cached is not None:
            return cached
        family = EVENT_COLORS[self.name].get(key)
        if family is not None:
            out = tuple(QColor(x) for x in family)
        else:
            bar = QColor(key)
            if not bar.isValid():
                out = tuple(QColor(x) for x in EVENT_COLORS[self.name]["bleu"])
            elif self.dark:
                out = (mix(self._c["bg"], bar, 0.24), bar, mix(bar, QColor("#ffffff"), 0.78))
            else:
                out = (mix(QColor("#ffffff"), bar, 0.17), bar, mix(bar, QColor("#000000"), 0.5))
        self._events[key] = out
        return out

    def heat(self, level: int) -> QColor:
        """Fond d'un jour de la vue Année (accent à 22 / 40 / 62 %)."""
        return with_alpha(self._c["accent"], {1: 0.22, 2: 0.40, 3: 0.62}.get(level, 0.0))


def from_settings(settings: dict) -> AgendaTheme:
    return AgendaTheme(settings.get("agenda_theme") or "sombre", settings.get("agenda_accent") or None,
                       settings.get("agenda_today_color") or None, settings.get("agenda_density") or "normal")
