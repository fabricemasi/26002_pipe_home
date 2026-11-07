"""Habillage de l'analyse colorimétrique (maquette « Analyse — Image 4207 », demande de l'utilisateur, 2026-10-31).

Valeurs de la maquette = défauts (`ANALYSIS_LOOK_DEFAULTS`, fusionnés dans `VIDEO_DEFAULTS`) ; chaque valeur visuelle
est réglable dans Réglages : Vidéo > Moodboard > Analyse colorimétrique (`fm_video/settings.py`). `analysis_look`
lit les réglages UNE fois et rend un dict figé + sa clé : l'interface ne refait rien si la clé n'a pas changé.
Aucun widget ici (lu par les tests sans fenêtre)."""
from __future__ import annotations

import sys

PREFIX = "video_analysis_"

# (suffixe, défaut) : couleurs de la maquette.
COLORS = (
    ("bg_color", "#101112"),            # fond de la page
    ("panel_color", "#161719"),         # barre du haut, palette, inspecteur
    ("footer_color", "#131415"),        # barre d'état
    ("line_color", "#26282b"),          # filets entre les zones
    ("control_border", "#2c2e31"),      # contour des boutons, séparateur de la barre d'outils
    ("well_color", "#0d0e0f"),          # fond des sélecteurs segmentés et des champs
    ("active_color", "#2c2e31"),        # segment choisi
    ("card_color", "#1e1f22"),          # cartes des statistiques de luminance
    ("scope_bg", "#0b0c0d"),            # fond des scopes
    ("text_color", "#e8e6e1"),
    ("strong_color", "#f2f0eb"),        # titre, HEX, segment choisi
    ("label_color", "#c9c6bf"),         # titres des sections, boutons
    ("muted_color", "#9a978f"),         # légendes
    ("axis_color", "#8a877f"),          # graduations des scopes
    ("accent_color", "#e0b062"),        # bouton principal, moyenne, anneau du fond choisi, cases cochées
    ("accent_ink", "#1a1408"),          # texte du bouton principal
    ("chip_on_bg", "#232528"), ("chip_on_border", "#3a3c40"), ("chip_off_dot", "#4a4c50"),
    ("hist_r", "#ff6a5e"), ("hist_g", "#5ad884"), ("hist_b", "#6a9fff"), ("hist_y", "#e8e6e1"),
    ("wave_color", "#c4bca6"),          # densité du waveform
    ("skin_color", "#f0a890"),          # ligne des teintes chair du vectorscope
    ("viewer_bg_1", "#000000"), ("viewer_bg_2", "#1c1d1f"), ("viewer_bg_3", "#767676"),
    # Onglet Matching / LUT (seconde maquette)
    ("accent_light", "#f0c98a"),        # « Choisir une référence… », « Après · n % »
    ("disabled_bg", "#2a2b2e"), ("disabled_fg", "#77746d"),   # bouton d'export tant que rien n'est calculé
    ("arrow_color", "#6f6c66"),         # flèche source -> référence
    ("todo_ring", "#3a3c40"),           # étape à venir
    # Palette, 2e version de la maquette (localiser sur l'image)
    ("swatch_frame", "#d8d8d8"),        # filet clair entre les pastilles jointives
    ("toggle_on_border", "#4a4c50"),    # contour de « Localiser sur l'image » allumé
)

# (suffixe, défaut, min, max) : tailles de la maquette (pixels logiques).
SIZES = (
    ("font_size", 13, 9, 20),
    ("inspector_width", 340, 240, 600),
    ("section_padding", 16, 4, 40),
    ("radius", 8, 0, 20),               # boutons, champs, cartes
    ("button_height", 36, 24, 56),
    ("swatch_height", 76, 24, 160),
    ("swatch_gap", 3, 0, 12),           # entre les colonnes des barres de couverture
    ("coverage_height", 16, 2, 32),
    ("bars_height", 56, 20, 160),
    ("tone_height", 14, 4, 32),
    ("image_max_height", 560, 200, 2000),
    ("hist_height", 150, 80, 400),
    ("wave_height", 180, 80, 400),
    ("vec_size", 220, 120, 400),
    ("match_image_max_height", 540, 200, 2000),
    ("thumb_width", 96, 48, 200),
)

ANALYSIS_LOOK_DEFAULTS = {
    **{PREFIX + k: v for k, v in COLORS},
    **{PREFIX + k: v for k, v, _lo, _hi in SIZES},
    PREFIX + "font_family": "", PREFIX + "mono_family": "",     # vide = Inter / JetBrains Mono (maquette)
    PREFIX + "vec_zoom": 16,            # zoom du vectorscope en dixièmes (maquette : ×1,6)
    # Ordre de la palette (choix de la maquette) et états temps réel de la vue.
    PREFIX + "order": "L", PREFIX + "viewer_bg": 1, PREFIX + "scope": "hist", PREFIX + "log": True,
    PREFIX + "channels": "rgb", PREFIX + "tool": "P",
    # Localiser sur l'image (2e version) : sélection d'origine / aplat, autres couleurs ajustées (luminosité,
    # saturation en %) / unies (couleur). Allumé / rendu de l'image : non enregistrés (`analysis_ui.SESSION`).
    PREFIX + "pick_mode": "orig", PREFIX + "rest": "adj", PREFIX + "rest_light": 30,
    PREFIX + "rest_sat": 0, PREFIX + "rest_color": "#000000",
}


def _resolve(value: str, default: str) -> str:
    """Couleur des réglages (peut être une référence « @… » : résolue par l'appli si le module vidéo est chargé)."""
    value = str(value or default)
    if value.startswith("@"):
        pane = sys.modules.get("fm_video.pane")
        resolve = getattr(pane, "HOOKS", {}).get("resolve_color") if pane is not None else None
        try:
            return resolve(value) if resolve is not None else default
        except Exception:                                    # noqa: BLE001 - référence cassée : le défaut
            return default
    return value


def _int(settings: dict, key: str, low: int, high: int) -> int:
    default = ANALYSIS_LOOK_DEFAULTS[PREFIX + key]
    try:
        return max(low, min(high, int(settings.get(PREFIX + key, default))))
    except (TypeError, ValueError):
        return default


def analysis_look(settings: dict | None) -> dict:
    """Valeurs visuelles prêtes à l'emploi (couleurs résolues, tailles bornées) + `key` pour comparer."""
    s = settings or {}
    look = {k: _resolve(s.get(PREFIX + k), v) for k, v in COLORS}
    look.update({k: _int(s, k, lo, hi) for k, _v, lo, hi in SIZES})
    look["font_family"] = str(s.get(PREFIX + "font_family") or "Inter")
    look["mono_family"] = str(s.get(PREFIX + "mono_family") or "JetBrains Mono")
    look["vec_zoom"] = _int(s, "vec_zoom", 5, 40) / 10.0
    look["key"] = repr(sorted(look.items()))
    return look


LOOK = analysis_look({})
