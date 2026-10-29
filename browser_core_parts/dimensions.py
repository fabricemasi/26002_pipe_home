"""Dimensions et configuration des colonnes. Carte : docs/agents/colonnes.md."""

from app_style import scaled

# ==========================================================================
# Design tokens : voir app_style.py (C, STYLESHEET, font()) partage entre
# toutes les applications du pipeline.
# ==========================================================================

COLUMN_MIN_WIDTH = 120

COLUMN_MAX_WIDTH = 640

COLUMN_RESIZE_MARGIN = 5   # zone (px) autour de la bordure ou le curseur change

# Hauteur des colonnes du groupe IN/OVER/OUT/LOGICIELS (voir Column.
# __init__ group_kind/fill_height, height_resize_begin/update/end) :
# CHACUNE a sa PROPRE hauteur, independante des 3 autres, redimensionnable a
# la main comme n'importe quel bord — SAUF la DERNIERE colonne de l'ordre
# courant (voir PipelineBrowser._group_column_order), qui reste TOUJOURS
# etiree jusqu'en bas de la page (comme une colonne normale, pas de poignee
# de redimensionnement) — voir la remarque de l'utilisateur, "je ne veux
# pas qu'elles aient toute la meme hauteur, mais chacune leur hauteur ...
# il est important que la derniere colonne aille bien jusqu'en bas de la
# page".
GROUP_COLUMN_DEFAULT_HEIGHT = 220

GROUP_COLUMN_MIN_HEIGHT = 80

GROUP_COLUMN_MAX_HEIGHT = 900

# Repli local (voir _WIDGET_SIZE_MAX) : valeur historique de
# QWIDGETSIZE_MAX (2**24-1, absente de certains bindings PySide6) utilisee
# pour LIBERER la hauteur maximale d'une colonne du groupe qui redevient la
# DERNIERE (voir Column.set_group_fill_height) — memes raison/valeur que
# l'ancienne constante module-level du meme nom, retiree avec la refonte du
# detail "Fichiers pour X".
_WIDGET_SIZE_MAX = 16777215

# Redimensionnement des lignes a la souris (Ctrl + clic entre 2 lignes +
# glisser, voir Column.row_resize_begin/_in_row_resize_zone, disponible sur
# TOUTE colonne) — memes bornes que le slider "Hauteur de la ligne" de la
# fenetre de parametres (voir settings_window._ITEM_TEXT_FIELD_SPECS) pour
# qu'une valeur posee ici ne soit jamais silencieusement recadree en
# rouvrant les parametres.
ROW_RESIZE_MIN_HEIGHT = 14

ROW_RESIZE_MAX_HEIGHT = 80

STATUS_HEIGHT = 24

TITLEBAR_HEIGHT = 28

DETAIL_PANEL_MIN_WIDTH = 220

DETAIL_PANEL_MAX_WIDTH = 520

# INSPECTOR_TITLE (titre "virtuel" pour resoudre le style EFFECTIF de
# l'inspecteur, voir app_style.column_style_for/DetailPanel.refresh_header/
# refresh_colors) est desormais importe depuis app_style.py, MEME raison
# que PREVIEW_STACK_TITLE ci-dessous : possede maintenant son propre onglet
# de surcharge (voir SettingsWindow._build_columns_page) — voir la remarque
# de l'utilisateur, "ajoute ... la colonne inspecteur" (dans les settings).
# PREVIEW_STACK_TITLE (la colonne fantome de l'apercu image empile, une
# fois une selection faite dans Projets/Sous-projet) est desormais
# importee depuis app_style.py — settings_window.py en a aussi besoin
# depuis qu'elle a son propre onglet de surcharge (voir
# SettingsWindow._build_columns_page), d'ou son deplacement la-bas (MEME
# raison que COLUMN_TYPE_OVERRIDE_KEYS : source UNIQUE partagee entre les
# 2 fichiers plutot que dupliquee).


# ==========================================================================
# Reglages par colonne (fenetre de parametres > pages "Colonne ...") :
# largeur / hauteur de ligne / espacement, et pour les colonnes a vignettes,
# padding/rayon des images qu'elles affichent (vignettes de projet pour
# Projets/Sous-projet, apercus fichier-image pour Logiciels/Contenu). Cle =
# COLUMN_LABELS (ou "Contenu" pour toute colonne au-dela de Logiciels).
# COLUMN_LABELS n'est definie que plus bas dans le fichier ; les reglages par
# defaut ci-dessous sont donc indexes a la main sur les memes intitules.
# ==========================================================================

COLUMN_SETTINGS: dict[str, dict[str, int]] = {
    "Type":        {"width": 140, "height": 25, "spacing": 0, "img_pad": 0, "img_radius": 0},
    "Projets":     {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0},
    "Sous-projet": {"width": 208, "height": 58, "spacing": 1, "img_pad": 0, "img_radius": 0},
    "Logiciels":   {"width": 186, "height": 30, "plain_height": 22, "spacing": 0, "img_pad": 3, "img_radius": 2},
    "Contenu":     {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
    # IN/OVER/OUT (colonnes du groupe fantome, voir update_preview_stack) :
    # memes valeurs de depart que "Contenu" — c'est le bucket qu'elles
    # partageaient AVANT d'obtenir leur propre onglet de surcharge dedie
    # (voir SettingsWindow._build_columns_page, la remarque de
    # l'utilisateur, "ajoute la colonne logiciels dans les settings, ainsi
    # que in over et out") : aucun changement visuel tant qu'aucune
    # surcharge n'est activee pour l'une d'elles.
    "IN":          {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
    "OVER":        {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
    "OUT":         {"width": 186, "height": 25, "plain_height": 20, "spacing": 0, "img_pad": 3, "img_radius": 0},
}

# Style de Colonnes/Entetes/Items par titre reel (voir settings_window.
# _section_headers, "Colonnes" dans l'onglet General, et
# _build_column_override_page pour les surcharges par titre) — cles
# EFFECTIVEMENT resolues (general OU surcharge, voir apply_all_settings
# ci-dessous) dans app_style.set_column_style/column_style_for, lues par
# Column/RowDelegate (voir Column.refresh_colors/refresh_header,
# _paint_unified_row). "column_gap" est volontairement absent : un
# espacement ENTRE colonnes n'a pas de sens pour une seule colonne.
# Colonne/entete (fond/bordure/rayon/padding — voir app_style.column_frame_
# qss/column_header_qss/column_padding_for) et cles "item_*" (texte/
# selection des LIGNES, voir _paint_unified_row) sont TOUTES deux
# APPLIQUEES a TOUTE colonne depuis l'unification du rendu — voir la
# remarque de l'utilisateur, "je veux que tu reformate toutes les autres
# colonnes exactement de la meme maniere que la colonne type". Listes
# elles-memes definies dans app_style.py (COLUMN_FRAME_KEYS/
# COLUMN_TYPE_OVERRIDE_KEYS, importees ci-dessus) — SOURCE UNIQUE partagee
# avec settings_window.py, qui ne peut pas importer CE fichier (sens
# d'import inverse) mais peut importer app_style.py comme ici.


# Colonnes > Texte > Police : libelle "police du soft" (voir
# app_style.ITEM_FONT_ROLE_LABELS) -> role (voir role_font) — sens
# INVERSE de la table de settings_window (qui, elle, va du role vers le
# libelle affiche dans le selecteur) — utilise par Column.refresh_fonts
# pour resoudre la famille REELLEMENT choisie pour ce role.
from app_style import _ITEM_FONT_LABEL_TO_ROLE  # noqa: E402  (source unique : fm_theme.style)

def _col_key(title: str) -> str:
    return title if title in COLUMN_SETTINGS else "Contenu"

# Chaque accesseur passe par scaled() (voir app_style.py) : les valeurs
# stockees dans COLUMN_SETTINGS restent les grandeurs "logiques" (100%,
# telles que reglees dans la fenetre de parametres), la mise a l'echelle ne
# s'applique qu'ici, a l'usage — meme principe que role_font() pour le
# texte. Ainsi le slider "Scale general de l'interface" affecte aussi les
# colonnes/lignes/vignettes, pas seulement les polices.

def col_width(title: str) -> int:
    return scaled(COLUMN_SETTINGS[_col_key(title)]["width"])

def col_row_height(title: str) -> int:
    return scaled(COLUMN_SETTINGS[_col_key(title)]["height"])

def col_plain_height(title: str) -> int:
    """Hauteur des lignes SANS apercu (fichier ordinaire, pas une image/
    .obj/.psd/.exr/video) dans une colonne qui melange les deux (voir
    RowDelegate.sizeHint) — plus basse que col_row_height, inutile de
    reserver la place d'une vignette carree la ou aucune n'est dessinee.
    Repli sur "height" si la colonne n'a pas de reglage distinct (colonnes
    a vignettes systematiques comme Projets/Sous-projet, ou Type qui n'a
    jamais d'image du tout : une seule hauteur y suffit)."""
    settings = COLUMN_SETTINGS[_col_key(title)]
    return scaled(settings.get("plain_height", settings["height"]))

def col_spacing(title: str) -> int:
    # minimum=0 : un espacement regle a 0 doit rester 0 apres mise a
    # l'echelle (voir scaled()), sinon deux lignes contigues se
    # retrouveraient quand meme separees par 1px.
    return scaled(COLUMN_SETTINGS[_col_key(title)]["spacing"], minimum=0)

def col_img_pad(title: str) -> int:
    # minimum=0, meme raison que col_spacing : un padding regle a 0 ne doit
    # jamais remonter a 1px (voir scaled()), sans quoi l'image d'une
    # vignette parait rognee/decalee d'un cote alors que le reglage
    # affiche bien 0.
    return scaled(COLUMN_SETTINGS[_col_key(title)]["img_pad"], minimum=0)
