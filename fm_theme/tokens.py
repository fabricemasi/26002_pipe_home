"""Jetons d'aspect des briques : palette `M` de la fenêtre de réglages, habillage des curseurs, styles des
titres par niveau, zones de saisie, couleurs « @slot », normalisation bordures / coins. Sortis de
settings_store (qui les réexporte) à l'étape 2 de fm_theme. Les dicts (`M`, `_SLIDER_STYLE`,
`_TITLE_LEVEL_STYLE`, `INPUT_LOOK`) sont modifiés EN PLACE : jamais réaffectés.
N'importe rien de l'appli (voir fm_theme/hooks.py)."""
from pathlib import Path

from PySide6.QtGui import QFont

from fm_theme.style import C, SEMANTIC_COLOR_SLOTS

_ROOT_DIR = Path(__file__).resolve().parent.parent
_ICONS_DIR = _ROOT_DIR / "icons"
_TOGGLE_ICONS_DIR = _ROOT_DIR / "data" / "toggle_icons"

# ==========================================================================
# Palette et metriques FIXES de cette fenetre (voir la remarque de tete de
# fichier) — recopiees de la maquette html.
# ==========================================================================

M = {
    "accent": "#3f6f9f",
    "accent_border": "#4c80b3",
    "accent_hover": "#487bad",
    "accent_fg": "#f2f6f9",
    "panel_bg": "#16181a",
    "panel_border": "#2a2e32",
    "titlebar_bg": "#101214",
    "title_fg": "#8d949a",
    "dirty_fg": "#c2914a",
    "clean_fg": "#5d656b",
    "dirty_border": "#5c4f2a",
    "dirty_frame": "#c62828",      # bordure de la fenetre de reglages v2 tant qu'un changement n'est pas enregistre
    "dirty_dot": "#c2914a",
    "clean_dot": "#3f8f6b",
    "close_hover_bg": "#232a30",
    "close_fg": "#7d858b",
    "close_hover_fg": "#d6d9dc",
    "dot_border": "#4d565c",
    "toolbar_bg": "#1b1e21",
    "field_bg": "#101214",
    "field_border": "#2e343a",
    "field_border_hover": "#3f6f9f",
    "label_dim": "#6e767c",
    "value_fg": "#d6d9dc",
    "value_muted": "#8d949a",
    "chevron": "#6e767c",
    "btn_bg": "#262b30",
    "btn_border": "#353b41",
    "btn_fg": "#c4cacf",
    "btn_hover": "#2f353b",
    "placeholder": "#5d656b",
    "section_title": "#5f9bd0",
    "group_title": "#d6d9dc",
    "group_note": "#5d656b",
    "row_label": "#cdd2d6",
    "row_label_off": "#7a828a",
    "row_note": "#5d656b",
    "value_text": "#e0e4e7",
    "value_text_off": "#6a7278",
    "unit": "#5d656b",
    "track_bg": "#25292d",
    "knob_off": "#5d656b",
    "toggle_on_fg": "#9dc0e0",
    "toggle_off_fg": "#5d656b",
    "swatch_border": "#3a4045",
    "swatch_border_hover": "#5f9bd0",
    "table_head_bg": "#1b1e21",
    "table_row_a": "#181b1d",
    "table_row_b": "#181b1d",
    "table_head_fg": "#8d949a",
    "bold_mark_fg": "#0f1114",
    "preview_bg": "#131517",
    "preview_border": "#23282c",
    "reset_fg": "#9aa2a9",
    "reset_hover_fg": "#c8ced3",
    "edge_off": "#262a2e",
    "edge_hint": "#4c545a",
    "dash": "#454d53",
}

def _sync_dynamic_M(colors: dict) -> None:
    """Aligne les entrees de M qui suivent desormais les couleurs REGLABLES
    de l'appli (voir app_style.SEMANTIC_COLOR_SLOTS/COLOR_FIELDS) au lieu de
    rester fixes — "Zone de saisie" (well), "Skin principale niveau 1"
    (topbar), et les 2 couleurs de tableau "Fond entete de tableau"/"Fond de
    tableau" (table_head/table_row) — voir la remarque de l'utilisateur,
    capture annotee de cette fenetre a l'appui (chaque zone visait un role
    deja existant ailleurs dans l'appli, plus 2 nouvelles couleurs pour ses
    propres tableaux). table_row_a ET table_row_b (ligne impaire/paire)
    valent tous deux exactement "table_row", SANS variation automatique
    entre les deux — une version precedente assombrissait legerement la
    ligne paire (voir _shade_hex, retire), mais l'utilisateur veut que
    TOUTES les lignes restent exactement la couleur choisie (capture a
    l'appui : l'alternance elle-meme etait le probleme signale, pas juste
    son absence de reglage).

    `colors` : dict de cles REELLES de C (pas de slots semantiques) —
    typiquement self.settings["colors"] fusionne avec les edits en cours du
    color grid (voir SettingsWindow._on_colors_changed/_refresh_dynamic_colors),
    JAMAIS C directement : le C global n'est mis a jour qu'au bout du
    round-trip vers la fenetre principale (settingsChanged, debounce de
    30ms) — beaucoup trop lent pour un apercu en direct pendant le glisser
    d'une pastille de couleur. `C[key]` sert seulement de repli si `colors`
    ne contient pas encore la cle (tout premier appel, preset incomplet...)."""
    well = colors.get("well", C["well"])
    topbar = colors.get("topbar", C["topbar"])
    table_head = colors.get("table_head", C["table_head"])
    table_row = colors.get("table_row", C["table_row"])
    M["field_bg"] = well
    M["toolbar_bg"] = topbar
    M["panel_bg"] = topbar
    M["table_head_bg"] = table_head
    M["table_row_a"] = table_row
    M["table_row_b"] = table_row

# Habillage des sliders peints a la main de cette fenetre (voir _MiniSlider) —
# reglable depuis Geometrie > Slider (voir SettingsWindow._section_geometry),
# sur le meme principe que _sync_dynamic_M ci-dessus : un dict a part (pas
# M directement, ce ne sont pas que des couleurs) que chaque _MiniSlider lit
# en direct a chaque peinture, mis a jour ici a l'ouverture de la fenetre et
# a chaque changement de l'un de ces reglages (voir SettingsWindow.
# _apply_slider_style, qui rappelle aussi .apply_style() sur chaque instance
# deja construite — necessaire pour thumb_h/track_h, qui influent sur la
# hauteur meme du widget, pas juste sa peinture).
_SLIDER_STYLE = {
    "thumb_w": 3,
    "thumb_h": 14,
    "thumb_color": "#8fb4d5",
    "thumb_border_top": "#8fb4d5",
    "thumb_border_right": "#8fb4d5",
    "thumb_border_bottom": "#8fb4d5",
    "thumb_border_left": "#8fb4d5",
    # dict {cote: bool}, pas un bool unique (voir _coerce_side_enabled/la
    # remarque de l'utilisateur, "un toggle par cote") — reecrase de toute
    # facon par _sync_slider_style avant le 1er rendu.
    "thumb_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "thumb_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "track_h": 3,
    "track_fill": "#3f6f9f",
    "track_empty": "#25292d",
    "track_border_top": "#25292d",
    "track_border_right": "#25292d",
    "track_border_bottom": "#25292d",
    "track_border_left": "#25292d",
    "track_border_enabled": {"top": True, "right": True, "bottom": True, "left": True},
    "track_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
}

def _sync_slider_style(settings: dict) -> None:
    _SLIDER_STYLE["thumb_w"] = max(1, int(settings.get("slider_thumb_width", 3)))
    _SLIDER_STYLE["thumb_h"] = max(1, int(settings.get("slider_thumb_height", 14)))
    # _resolve_color_value : voir _sync_toggle_shape_style, meme raison
    # (toutes les couleurs peuvent contenir un hex direct OU une
    # reference "@<slot>", voir _AppOrCustomColorField).
    colors = settings.get("colors") or {}
    thumb_color = _resolve_color_value(settings.get("slider_thumb_color", "#8fb4d5"), colors)
    _SLIDER_STYLE["thumb_color"] = thumb_color
    thumb_border = settings.get("slider_thumb_border") or {}
    for side in ("top", "right", "bottom", "left"):
        _SLIDER_STYLE[f"thumb_border_{side}"] = _resolve_color_value(
            thumb_border.get(side, thumb_color), colors)
    _SLIDER_STYLE["thumb_border_enabled"] = _coerce_side_enabled(settings.get("slider_thumb_border_enabled", True))
    _SLIDER_STYLE["thumb_radius"] = _coerce_corner_radius(settings.get("slider_thumb_radius", 0))
    _SLIDER_STYLE["track_h"] = max(1, int(settings.get("slider_track_height", 3)))
    track_empty = _resolve_color_value(settings.get("slider_track_empty_color", "#25292d"), colors)
    _SLIDER_STYLE["track_fill"] = _resolve_color_value(settings.get("slider_track_fill_color", "#3f6f9f"), colors)
    _SLIDER_STYLE["track_empty"] = track_empty
    track_border = settings.get("slider_track_border") or {}
    for side in ("top", "right", "bottom", "left"):
        _SLIDER_STYLE[f"track_border_{side}"] = _resolve_color_value(
            track_border.get(side, track_empty), colors)
    _SLIDER_STYLE["track_border_enabled"] = _coerce_side_enabled(settings.get("slider_track_border_enabled", True))
    _SLIDER_STYLE["track_radius"] = _coerce_corner_radius(settings.get("slider_track_radius", 0))

# ==========================================================================
# Section "TITRE" (voir SettingsWindow._section_titre) : police + retrait
# (indentation) des titres de _Section/_SubSection de CETTE fenetre, par
# niveau d'imbrication (1 = _Section, 2..5 = _SubSection a une profondeur
# croissante) — voir la remarque de l'utilisateur, "je veux homogeneiser
# les textes des sections et sous sections". Defauts = apparence INCHANGEE
# (voir _Section/_SubSection avant ce reglage : 14/600 couleur section_title
# niveau 1, 10/600 couleur group_title/group_note + 20px/40px de retrait
# niveaux 2/3) ; niveaux 4/5 n'ont encore AUCUN site d'utilisation reel
# (aucune sous-section n'est imbriquee aussi profond aujourd'hui) — reserves
# pour une imbrication future, memes defauts que le niveau 3 mais un retrait
# plus profond (60/80px).
# ==========================================================================
_TITLE_LEVEL_DEFAULTS: dict[int, dict] = {
    1: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 14,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5f9bd0", "indent": 0, "gap_collapsed": 2, "gap_expanded": 34, "gap_next": 4},
    2: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 20, "gap_collapsed": 0, "gap_expanded": 32, "gap_next": 6},
    3: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 40, "gap_collapsed": 0, "gap_expanded": 32, "gap_next": 6},
    4: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 60, "gap_collapsed": 0, "gap_expanded": 32, "gap_next": 6},
    5: {"font_family": "", "font_bold": True, "font_italic": False, "font_size": 10,
        "font_smoothing_enabled": False, "font_smoothing": "current", "font_color": "#5d656b", "indent": 80, "gap_collapsed": 0, "gap_expanded": 32, "gap_next": 6},
}

# Fenetre v2 : chaque titre est un PARAGRAPHE (titre + tout son contenu jusqu'au titre suivant).
# `text_padding` = padding du texte seul (remplace les espacements gap_* en v2) ; `bg_*` = fond du
# paragraphe (couleur, margin, padding, bordures, border radius). Voir _BodyMixin.apply_box (settings_layout).
def _title_box_defaults(level: int) -> dict:
    vertical = 6 if level == 1 else 4
    return {
        "text_padding": {"left": 0, "top": vertical, "right": 0, "bottom": vertical},
        "text_padding_linked": False,
        "space_before": 0, "space_after": 0,   # padding avant le 1er / apres le dernier titre d'une pile de niveau N
        "bg_enabled": False, "bg_color": "@skinN2",
        "bg_margin": {"left": 0, "top": 0, "right": 0, "bottom": 0}, "bg_margin_linked": True,
        "bg_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0}, "bg_padding_linked": True,
        # Padding (paragraphe) : autour de TOUT ce que contient le titre (sous la ligne du titre).
        "body_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0}, "body_padding_linked": True,
        "bg_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
        "bg_border": {"top": "#2e343a", "right": "#2e343a", "bottom": "#2e343a", "left": "#2e343a"},
        "bg_border_thickness": 1, "bg_border_enabled_linked": True,
        "bg_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
        "bg_radius_linked": True,
    }

for _level, _vals in _TITLE_LEVEL_DEFAULTS.items():
    _vals.update(_title_box_defaults(_level))
del _level, _vals

_TITLE_LEVEL_STYLE: dict[int, dict] = {level: dict(vals) for level, vals in _TITLE_LEVEL_DEFAULTS.items()}

def _sync_title_level_style(settings: dict) -> None:
    colors = settings.get("colors") or {}
    for level, defaults in _TITLE_LEVEL_DEFAULTS.items():
        prefix = f"title_level{level}"
        style = _TITLE_LEVEL_STYLE[level]
        for key, default in defaults.items():
            style[key] = settings.get(f"{prefix}_{key}", default)
        style["bg_color_hex"] = _resolve_color_value(style["bg_color"], colors)
        border = style["bg_border"] if isinstance(style["bg_border"], dict) else {}
        style["bg_border_hex"] = {side: _resolve_color_value(border.get(side, "#2e343a"), colors)
                                  for side in ("top", "right", "bottom", "left")}
        # Resolu tout de suite en hex REEL (voir _resolve_color_value) —
        # PAS conserve tel quel ("@<slot>") : _title_color n'a lui-meme
        # aucun acces a la palette (fonction MODULE, pas methode), le
        # laisser resoudre plus tard avec un dict VIDE retombait toujours
        # sur le noir de repli — voir la remarque de l'utilisateur, "quand
        # je selectionne une couleur app, elle apparait noire".
        style["font_color"] = _resolve_color_value(style["font_color"], colors)

def _title_font(level: int) -> QFont:
    """Police EFFECTIVE d'un titre de _Section (niveau 1) / _SubSection
    (niveau 2-5) — voir _TITLE_LEVEL_STYLE. Import de pipeline_browser
    LOCAL (voir _SettingsTitleBar.__init__, meme raison) : evite un import
    circulaire au chargement du module (pipeline_browser importe deja
    settings_window)."""
    from fm_theme.style import _resolve_font_family, font as pb_font
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_DEFAULTS[3]
    size = int(style.get("font_size", 10))
    weight = 600 if style.get("font_bold", True) else 400
    smoothing = style.get("font_smoothing", "current") if style.get("font_smoothing_enabled") else "current"
    family = _resolve_font_family((style.get("font_family") or "").strip(), size, weight)
    return pb_font(
        size, weight, family=family, italic=bool(style.get("font_italic", False)),
        smoothing=smoothing, tracking=(0.6 if level >= 2 else 0.0))

def _title_color(level: int) -> str:
    """Couleur DEJA resolue en hex (voir _sync_title_level_style, appelee
    avant toute utilisation de cette fonction) — jamais un "@<slot>" brut
    ici."""
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_DEFAULTS[3]
    return style.get("font_color", "#d6d9dc")

def _title_indent(level: int) -> int:
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_DEFAULTS[3]
    return max(0, int(style.get("indent", 0)))


def _title_gap_next(level: int) -> int:
    """Espace entre un titre deplie de `level` et son contenu (le titre du
    niveau suivant, le cas echeant)."""
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_DEFAULTS[3]
    return max(0, int(style.get("gap_next", 6)))

def _title_box(level: int) -> dict:
    """Habillage « paragraphe » d'un titre de `level` (v2) : margin et paddings en tuples (G, H, D, B), bordure
    (cotes actifs, couleurs hex, epaisseur), rayons par coin, couleur de fond hex ou None."""
    style = _TITLE_LEVEL_STYLE.get(level) or _TITLE_LEVEL_STYLE[3]

    def pad(value) -> tuple:
        value = value if isinstance(value, dict) else {}
        return tuple(max(0, int(value.get(side, 0))) for side in ("left", "top", "right", "bottom"))

    return {
        "text_padding": pad(style.get("text_padding")),
        "margin": pad(style.get("bg_margin")),
        "space_before": max(0, int(style.get("space_before", 0))),
        "space_after": max(0, int(style.get("space_after", 0))),
        "padding": pad(style.get("bg_padding")),
        "body_padding": pad(style.get("body_padding")),
        "fill": style.get("bg_color_hex") if style.get("bg_enabled") else None,
        "border_on": _coerce_side_enabled(style.get("bg_border_enabled", False), False),
        "border_colors": dict(style.get("bg_border_hex") or {}),
        "thickness": max(0, int(style.get("bg_border_thickness", 1))),
        "radius": _coerce_corner_radius(style.get("bg_radius", 0)),
    }

def _subsection_left_margin(level: int) -> int:
    """Marge GAUCHE reelle du bandeau d'une _SubSection de `level` — voir la
    remarque de l'utilisateur, "pour les titres, une indentation a 0
    correspond a etre au meme niveau que le titre 1" : un retrait de 0px
    (General > TITRE > "Retrait titre niveau N") doit aligner le TEXTE de
    cette sous-section sur le TEXTE du titre de _Section (niveau 1), pas sur
    x=0 brut — or _Section et _SubSection n'ont pas le meme chevron/
    espacement (16+10 vs 11+6), d'ou l'ecart fixe "9" ci-dessous pour
    compenser cette difference AVANT d'ajouter le retrait configure."""
    return _title_indent(1) + 9 + _title_indent(level)


def toggle_style_list(settings: dict) -> list[dict]:
    """Styles de toggle, dans l'ordre : `toggle_styles`, plus ceux de l'ancienne liste
    `toggle_custom_styles` (styles ajoutes avant qu'on puisse renommer/supprimer) absents de la
    premiere. Jamais vide (repli sur Toggle 1)."""
    styles, seen = [], set()
    for entry in list(settings.get("toggle_styles") or []) + list(settings.get("toggle_custom_styles") or []):
        key = (entry or {}).get("key")
        if key and key not in seen:
            seen.add(key)
            styles.append({"key": key, "name": entry.get("name") or key})
    return styles or [{"key": "toggle1", "name": "Toggle 1"}]


_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")

_SLOT_REAL = {slot: real for slot, real, _label in SEMANTIC_COLOR_SLOTS}

def _resolve_color_value(value: str, colors: dict) -> str:
    """Resout une valeur de couleur qui peut etre soit un hex direct
    ("#rrggbb"), soit une reference "@<slot>" a une pastille semantique
    (voir _AppOrCustomColorField, bordures de Toggles/Sliders) — utilise
    partout ou une telle valeur doit finir en hex REEL (ex: la peinture
    d'un toggle, voir _sync_toggle_shape_style) plutot que le marqueur
    "@..." lui-meme, que QColor() ne saurait pas interpreter."""
    if isinstance(value, str) and value.startswith("@"):
        from fm_theme.style import split_color_ref, with_alpha     # « @slot/75 » : opacite propre
        ref, alpha = split_color_ref(value)
        return with_alpha(colors.get(_SLOT_REAL.get(ref[1:], "chrome"), "#000000"), alpha)
    return value

# -- Zone de saisie (Reglages > Zone de saisie) : valeurs LUES par toutes les zones de saisie de la fenetre de
# reglages au moment de leur habillage (la feuille de style de l'appli couvre, elle, les QLineEdit de l'appli).
INPUT_LOOK: dict = {}


def set_input_look(values: dict) -> None:
    INPUT_LOOK.clear()
    INPUT_LOOK.update({k: v for k, v in values.items() if k.startswith("input_")})
    INPUT_LOOK["colors"] = values.get("colors") or {}


def input_bg() -> str:
    value = INPUT_LOOK.get("input_bg_color")
    return _resolve_color_value(value, INPUT_LOOK.get("colors") or {}) if value else M["field_bg"]


def input_border_decl() -> str:
    """Bordures de la zone de saisie : une declaration par cote (couleur, epaisseur, cotes allumes)."""
    colors = INPUT_LOOK.get("colors") or {}
    enabled = INPUT_LOOK.get("input_border_enabled", True)
    if not isinstance(enabled, dict):
        enabled = dict.fromkeys(("top", "right", "bottom", "left"), bool(enabled))
    raw = INPUT_LOOK.get("input_border")
    if not isinstance(raw, dict):
        raw = dict.fromkeys(("top", "right", "bottom", "left"), raw or M["field_border"])
    try:
        width = max(0, int(INPUT_LOOK.get("input_border_thickness", 1)))
    except (TypeError, ValueError):
        width = 1
    return " ".join(
        f"border-{side}: {width}px solid {_resolve_color_value(raw.get(side) or M['field_border'], colors)};"
        if enabled.get(side) and width else f"border-{side}: none;"
        for side in ("top", "right", "bottom", "left"))


def input_height() -> int:
    """Hauteur imposee aux zones de saisie (0 : chacune garde la sienne)."""
    try:
        return max(0, int(INPUT_LOOK.get("input_height") or 0))
    except (TypeError, ValueError):
        return 0


def _coerce_side_enabled(value, default: bool = True) -> dict[str, bool]:
    """Normalise un reglage de bordure "activee" en dict {cote: bool} —
    accepte soit l'ancien format (un seul bool, pour tous les cotes a la
    fois — retro-compatibilite avec les presets/pipeline_settings.json
    existants), soit deja un dict {"top": bool, ...} (nouveau format, voir
    _SideColorsField/_ToggleSideColorsField et la remarque de l'utilisateur,
    "au lieu d'avoir un seul toggle pour activer les bordures, je veux un
    toggle par cote")."""
    if isinstance(value, dict):
        return {k: bool(value.get(k, default)) for k in ("top", "right", "bottom", "left")}
    v = default if value is None else bool(value)
    return {k: v for k in ("top", "right", "bottom", "left")}

def _coerce_corner_radius(value, default: int = 0) -> dict[str, int]:
    """Normalise un reglage de rayon en dict {coin: int} — accepte soit
    l'ancien format (un seul int, meme rayon pour les 4 coins — retro-
    compatibilite avec les presets/pipeline_settings.json existants), soit
    deja un dict {"top_left": int, ...} — voir _CornerRadiusField et la
    remarque de l'utilisateur, "dans tous les parametres de coins arrondis,
    je veux exactement le meme fonctionnement que les padding (un par
    coin)"."""
    if isinstance(value, dict):
        return {k: max(0, int(value.get(k, default))) for k in _CORNERS}
    v = max(0, int(value)) if value is not None else default
    return {k: v for k in _CORNERS}
