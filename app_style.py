#!/usr/bin/env python3
"""
Style partage pour toutes les applications PySide6 du pipeline.

Contient les tokens de design (couleurs, polices) et la feuille de style Qt
(QSS) commune, de maniere a ce que chaque application ait le meme look sans
dupliquer le CSS. Une application l'utilise ainsi :

    from app_style import C, STYLESHEET, font
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    ...
    label.setFont(font(12, 600))

Ou, plus court :

    from app_style import apply_style
    app = QApplication(sys.argv)
    apply_style(app)
"""

import sys

from PySide6.QtGui import QFont, QFontDatabase

# ==========================================================================
# Design tokens (maquette Claude Design)
# ==========================================================================

C = {
    "app_bg":        "#101214",
    "void":          "#0d0f11",
    "window":        "#1a1c1e",
    "chrome":        "#202326",
    "topbar":        "#212427",
    "well":          "#141618",
    "detail_bg":     "#17191b",
    "border":        "#2c3034",
    "border_soft":   "#303539",
    "line":          "#3a3f44",
    "sel_idle":      "#2e3338",
    "row_idle":      "#0d0f11",
    "hover":         "#232729",
    "accent":        "#3f6f9f",
    "accent_text":   "#eef2f5",
    "btn":           "#282c30",
    "btn_border":    "#383d42",
    "btn_hover":     "#31363b",
    "btn_hover_bd":  "#454b50",
    "text":          "#d6d9dc",
    "text_file":     "#b3babf",
    "text_mono":     "#b9bfc4",
    "header":        "#9aa1a7",
    "label":         "#7d858b",
    "dim":           "#5f666b",
    "count":         "#5c6368",
    "mark_dir_bd":   "#6c757b",
    "mark_dir_fill": "#3b4045",
    "mark_file_bd":  "#454b50",
    "scroll":        "#35393d",
    "scroll_hover":  "#464b50",
    # Utilisees uniquement par les tableaux "fermes" de la fenetre de
    # parametres (Polices/Entetes/Geometrie — voir settings_window._sync_dynamic_M) :
    # l'appli principale n'a encore aucun tableau standard a ce jour (voir
    # set_table_radius plus bas), mais ces 2 couleurs suivent deja le meme
    # mecanisme reglable que le reste de C, pretes pour le jour ou elle en
    # aura un.
    "table_head":    "#1b1e21",
    "table_row":     "#181b1d",
}

# ==========================================================================
# Polices
# ==========================================================================

_SANS = None
_MONO = None
_NAME = None
_CODE = None


def sans_family() -> str:
    global _SANS
    if _SANS is None:
        families = set(QFontDatabase.families())
        for candidate in ("Nunito", "IBM Plex Sans", "Inter", "Segoe UI", "Noto Sans"):
            if candidate in families:
                _SANS = candidate
                break
        else:
            _SANS = "Sans Serif"
    return _SANS


def mono_family() -> str:
    global _MONO
    if _MONO is None:
        families = set(QFontDatabase.families())
        for candidate in ("IBM Plex Mono", "Consolas", "DejaVu Sans Mono", "Courier New"):
            if candidate in families:
                _MONO = candidate
                break
        else:
            _MONO = "Monospace"
    return _MONO


def name_family() -> str:
    """Police dediee aux noms de dossiers/fichiers dans les navigateurs du
    pipeline (distincte de la police generale de l'interface : boutons,
    en-tetes, etc. restent sur sans_family())."""
    global _NAME
    if _NAME is None:
        families = set(QFontDatabase.families())
        for candidate in ("Rubik", "Nunito", "IBM Plex Sans", "Inter", "Segoe UI", "Noto Sans"):
            if candidate in families:
                _NAME = candidate
                break
        else:
            _NAME = "Sans Serif"
    return _NAME


def code_family() -> str:
    """Police dediee au role "Code" (voir ROLE_BASE_KIND) — Consolas
    explicitement demandee par l'utilisateur (pas une detection parmi
    plusieurs candidates comme mono_family : ce role doit rester CETTE
    police precise), avec un repli neutre si elle n'est pas installee sur
    la machine."""
    global _CODE
    if _CODE is None:
        _CODE = "Consolas" if "Consolas" in set(QFontDatabase.families()) else mono_family()
    return _CODE


_ALL_FAMILIES: list[str] | None = None


def installed_font_families() -> list[str]:
    """Polices reellement installees sur la machine (voir QFontDatabase),
    triees alphabetiquement — calcule une seule fois (le jeu de polices
    installees ne change pas en cours de session). Utilise par la fenetre
    de parametres pour proposer un choix qui correspond a ce qui est
    vraiment disponible, plutot qu'une liste figee de polices qui
    pourraient ne pas etre installees du tout chez l'utilisateur."""
    global _ALL_FAMILIES
    if _ALL_FAMILIES is None:
        _ALL_FAMILIES = sorted(QFontDatabase.families())
    return _ALL_FAMILIES


SMOOTHING_CHOICES = ("current", "previous", "none")
# Intitules demandes par l'utilisateur pour le selecteur par police de la
# fenetre de parametres (voir settings_window._SimpleFontTable) : "current"
# (sans hinting, lissage complet) / "previous" (hinting natif Windows,
# intermediaire) / "none" (anti-aliasing desactive) — voir font() pour le
# detail technique de chaque niveau.
SMOOTHING_LABELS = {
    "current": "Tres lissee",
    "previous": "Un peu",
    "none": "Pas du tout",
}
# Intitules courts (retenus pour la colonne "Lissage", plus etroite qu'un
# _Row classique) — memes cles que SMOOTHING_CHOICES.
SMOOTHING_LABELS_SHORT = SMOOTHING_LABELS

# ==========================================================================
# Echelle generale de l'interface (fenetre de parametres > General > Scale) :
# multiplie la taille de TOUTES les polices (voir font() ci-dessous) ET
# toutes les metriques de mise en page qui passent par scaled() ci-dessous
# (largeurs/hauteurs de colonnes, entetes, boutons de la barre de titre...)
# — point de passage unique pour toute l'interface, pas seulement le texte.
# ==========================================================================

_UI_SCALE_PERCENT = 100


def set_ui_scale(percent: int) -> None:
    global _UI_SCALE_PERCENT
    _UI_SCALE_PERCENT = max(10, int(percent))


def ui_scale() -> int:
    return _UI_SCALE_PERCENT


def scaled(px: float, minimum: int = 1) -> int:
    """Convertit une metrique de mise en page (largeur, hauteur, padding...)
    exprimee dans ses unites "logiques" (100%) vers sa taille reelle a
    l'echelle courante — meme principe que font() pour la typographie, mais
    pour toute autre grandeur en pixels. `px` reste la valeur stockee dans
    les reglages (colonnes, entetes...), inchangee ; seul son usage a
    l'affichage passe par ici. `minimum` vaut 1 par defaut (une largeur/
    hauteur ne doit jamais s'ecraser a 0 px), mais DOIT etre mis a 0 par
    l'appelant pour un padding/rayon/espacement, ou 0 est une valeur reglee
    valide et distincte de "1px" (sinon un padding regle a 0 remontait quand
    meme a 1px apres arrondi — l'image d'une vignette semblait alors rognee/
    decalee alors que le reglage affichait bien 0)."""
    return max(minimum, round(px * _UI_SCALE_PERCENT / 100))


def font(size: int, weight: int = 400, mono: bool = False,
         tracking: float = 0.0, caps: bool = False, family: str | None = None,
         smoothing: str = "current") -> QFont:
    if family is None:
        family = mono_family() if mono else sans_family()
    f = QFont(family)
    size = max(1, round(size * _UI_SCALE_PERCENT / 100))
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    # En dessous d'environ 18-20px, le moteur de rendu de police de Windows
    # bascule sur un anti-aliasing tres grossier (quelques niveaux de gris
    # seulement) des que le hinting est actif, donnant un texte crenele —
    # visible sur toute l'interface puisque la plupart du texte de l'appli
    # est en 10-12px. "current" desactive le hinting pour forcer un lissage
    # complet et coherent quelle que soit la taille (le comportement par
    # defaut de l'appli) ; "previous" restaure le hinting natif de Qt/Windows
    # (comportement d'avant ce correctif, plus crenele en petite taille) ;
    # "none" desactive completement l'anti-aliasing (texte brut, sans lissage).
    if smoothing == "previous":
        f.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    elif smoothing == "none":
        f.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
    else:
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    if caps:
        f.setCapitalization(QFont.AllUppercase)
    return f


# ==========================================================================
# Polices par role, personnalisables par l'utilisateur (fenetre Parametres) :
# fichiers, dossiers, informations diverses (compteurs, chemins...), boutons,
# et une police "ensemble de l'appli" qui sert de repli pour les roles non
# surcharges individuellement. Une surcharge vide (family="") revient au
# comportement automatique (name_family/mono_family/sans_family).
# ==========================================================================

ROLE_BASE_KIND = {
    "files": "name",
    "folders": "name",
    "info": "mono",
    "info2": "mono",
    "buttons": "sans",
    "titles": "sans",
    "colhead": "sans",
    "code": "code",
}

_ROLE_DEFAULTS = {
    "family": "", "size": 12, "bold": False, "smoothing": "current", "color": "", "custom": False,
}

# "app"      -> Police principale (repli de tous les autres roles)
# "titles"   -> Police principale titres
# "folders"  -> Dossiers
# "files"    -> Fichiers
# "buttons"  -> Boutons
# "colhead"  -> Entete de colonnes
# "info"     -> Informations diverses / invites
# "info2"    -> Informations diverses / invites (2)
# "code"     -> Police "Code" (voir code_family) — pas encore consommee
#               ailleurs dans l'appli, ajoutee sur demande de l'utilisateur
#               (meme principe que "table_head"/"table_row" en leur temps :
#               reglage prepare avant son premier usage reel).
_ROLE_OVERRIDES: dict[str, dict] = {
    role: dict(_ROLE_DEFAULTS)
    for role in ("app", "titles", "files", "folders", "info", "info2", "buttons", "colhead", "code")
}

# Colonnes > Type > Texte > Police (voir settings_window._section_items) :
# "polices du soft" — les 5 roles DEJA regles dans Polices principales,
# proposees comme raccourcis dans le meme selecteur que les polices
# SYSTEME (voir installed_font_families) — voir la remarque de
# l'utilisateur, "je veux avoir le choix entre les polices du soft et les
# polices systeme" (clarifiee : "les polices qui se trouvent dans la
# section polices principales"). Cle = role (voir role_font), valeur =
# libelle AFFICHE dans le selecteur ET valeur STOCKEE telle quelle dans
# item_font_family (pas de prefixe "@" : ces libellles ne risquent pas de
# collisionner avec un vrai nom de police systeme) — pipeline_browser.py
# fait la RESOLUTION inverse (libelle -> role -> role_font(...).family())
# au moment de peindre le texte.
ITEM_FONT_ROLE_LABELS = {
    "app": "Police principale",
    "info": "Police informations",
    "titles": "Police principale titres",
    "files": "Police fichiers",
    "code": "Police code",
}


def set_role_font(role: str, family: str, size: int, bold: bool,
                   smoothing: str = "current", color: str = "", custom: bool = True) -> None:
    """Enregistre la surcharge typographique d'un role : 'app', 'titles',
    'files', 'folders', 'buttons', 'colhead', 'info', 'info2' ou 'code'.
    `custom` (True par defaut : un appel explicite vaut personnalisation)
    distingue "jamais touche dans la fenetre de parametres" (taille/gras
    ignores, chaque appelant garde sa propre taille/graisse par defaut —
    voir role_font) de "personnalise, meme en laissant la police sur
    Automatique" (la famille reste auto-detectee, mais taille/gras suivent
    desormais l'utilisateur). `smoothing` et `color` s'appliquent eux
    toujours independamment, meme sans personnalisation."""
    _ROLE_OVERRIDES[role] = {
        "family": family, "size": size, "bold": bold,
        "smoothing": smoothing if smoothing in SMOOTHING_CHOICES else "current",
        "color": color, "custom": custom,
    }


def _base_family_for(role: str) -> str:
    kind = ROLE_BASE_KIND.get(role, "sans")
    if kind == "mono":
        return mono_family()
    if kind == "code":
        return code_family()
    if kind == "name":
        return name_family()
    return sans_family()


def auto_family_for_role(role: str) -> str:
    """Police reellement utilisee quand un role reste sur "Systeme" (aucune
    surcharge) — expose _base_family_for a l'UI pour que la fenetre de
    parametres puisse afficher ce vrai nom de police plutot que le mot
    generique "Systeme" dans ses selecteurs."""
    return _base_family_for(role)


def role_font(role: str, default_size: int, default_weight: int = 400,
              tracking: float = 0.0, caps: bool = False) -> QFont:
    """Police pour un `role` donne, en tenant compte d'une eventuelle
    surcharge utilisateur pour ce role, puis de la surcharge globale 'app',
    puis de l'auto-detection habituelle si rien n'est personnalise. Le
    lissage suit la surcharge du role (ou 'current' par defaut)."""
    role_ov = _ROLE_OVERRIDES.get(role) or {}
    app_ov = _ROLE_OVERRIDES.get("app") or {}
    source = role_ov if role_ov.get("custom") else (app_ov if app_ov.get("custom") else None)
    smoothing = role_ov.get("smoothing") or "current"
    if source:
        family = source["family"] or _base_family_for(role)
        return font(
            source["size"], 700 if source["bold"] else 400,
            tracking=tracking, caps=caps, family=family, smoothing=smoothing,
        )
    return font(default_size, default_weight, tracking=tracking, caps=caps,
                family=_base_family_for(role), smoothing=smoothing)


def role_color(role: str, default_hex: str) -> str:
    """Couleur de texte pour un `role` donne : surcharge du role, puis
    surcharge globale 'app', puis `default_hex` si rien n'est personnalise."""
    role_ov = _ROLE_OVERRIDES.get(role) or {}
    app_ov = _ROLE_OVERRIDES.get("app") or {}
    return role_ov.get("color") or app_ov.get("color") or default_hex


# ==========================================================================
# Couleurs de l'interface, modifiables en direct depuis la fenetre de
# parametres (page "Couleurs de l'interface"). COLOR_FIELDS liste, dans
# l'ordre d'affichage, chaque cle de C avec un intitule et une note en
# francais — c'est cette liste que la fenetre de parametres parcourt pour
# generer une pastille par couleur, sans avoir a connaitre les cles de C.
# ==========================================================================

COLOR_FIELDS: list[tuple[str, str, str]] = [
    ("app_bg", "Fond application", "Derriere la fenetre, barre de titre"),
    ("void", "Fond de vide", "Au-dela de la derniere colonne, apercus vides"),
    ("window", "Fond fenetre", "Base des colonnes et du chrome general"),
    ("chrome", "Fond entete de colonne", "Bandeau haut de chaque colonne"),
    ("topbar", "Fond barre d'outils", "Bandeau du haut (racine, boutons)"),
    ("well", "Fond des champs enfonces", "Champs de saisie, vignettes vides"),
    ("detail_bg", "Fond inspecteur", "Panneau de droite"),
    ("border", "Bordures et separateurs", "Traits 1px entre les zones"),
    ("border_soft", "Bordure des champs", "Contour des champs de saisie"),
    ("line", "Ligne", "Filets separateurs internes aux colonnes"),
    ("sel_idle", "Selection (colonne inactive)", "Ligne selectionnee hors focus"),
    ("row_idle", "Ligne non selectionnee", "Fond des lignes Type/Projets/Sous-projet au repos"),
    ("hover", "Survol de ligne", "Retour au survol de la souris"),
    ("accent", "Couleur d'accent", "Selection active, boutons principaux"),
    ("accent_text", "Texte sur accent", "Texte au-dessus de la couleur d'accent"),
    ("btn", "Fond des boutons", "Etat normal"),
    ("btn_border", "Bordure des boutons", "Etat normal"),
    ("btn_hover", "Fond des boutons (survol)", ""),
    ("btn_hover_bd", "Bordure des boutons (survol)", ""),
    ("text", "Texte principal", "Dossiers, titres"),
    ("text_file", "Texte des fichiers", ""),
    ("text_mono", "Texte monospace", "Champs de saisie"),
    ("header", "Texte d'entete de colonne", ""),
    ("label", "Texte des libelles", "Labels de la barre d'outils"),
    ("dim", "Texte attenue", "Informations secondaires"),
    ("count", "Texte des compteurs", "Nombre d'elements par colonne"),
    ("mark_dir_bd", "Marqueur dossier (contour)", ""),
    ("mark_dir_fill", "Marqueur dossier (fond)", ""),
    ("mark_file_bd", "Marqueur fichier (contour)", ""),
    ("scroll", "Ascenseur", ""),
    ("scroll_hover", "Ascenseur (survol)", ""),
    ("table_head", "Fond entete de tableau", "Bandeau titre des tableaux (fenetre de parametres)"),
    ("table_row", "Fond de tableau", "Lignes des tableaux (fenetre de parametres) — toutes les lignes, sans variation"),
]


def _hex_to_rgb(hexval: str) -> tuple[int, int, int]:
    """Composantes (R, G, B) 0-255 d'un "#rrggbb" OU "#aarrggbb" (alpha en
    tete, voir _hex_to_alpha ci-dessous/la remarque de l'utilisateur, "un
    parametre de transparence des couleurs dans le selecteur") — retombe
    sur noir pour une entree absente/mal formee, jamais une exception
    (source de donnees parfois EXTERNE, voir C/settings.json). Source
    UNIQUE (auparavant dupliquee independamment dans pipeline_browser.py
    ET settings_window.py, avec une garde differente entre les 2 copies —
    voir la remarque de l'utilisateur, "clean le code")."""
    h = (hexval or "#000000").lstrip("#")
    if len(h) == 8:
        h = h[2:]   # AARRGGBB -> RRGGBB (alpha gere a part, voir _hex_to_alpha)
    if len(h) != 6:
        h = "000000"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hex_to_alpha(hexval: str) -> int:
    """Canal alpha 0-255 d'un "#aarrggbb" (255 = opaque, PAR DEFAUT pour
    tout "#rrggbb" a 6 chiffres — retro-compatible, aucune couleur
    existante n'est transparente tant qu'elle n'est pas explicitement
    reglee) — voir _hex_to_rgb, MEME convention."""
    h = (hexval or "").lstrip("#")
    if len(h) == 8:
        try:
            return max(0, min(255, int(h[0:2], 16)))
        except ValueError:
            return 255
    return 255


def set_color(key: str, hex_value: str) -> None:
    """Modifie une couleur de l'interface (cle de C) en direct. N'affecte
    par elle-meme que les widgets construits APRES l'appel — voir
    refresh_style() pour re-appliquer la feuille de style Qt globale, et
    le cote appelant (pipeline_browser.refresh_colors) pour les widgets
    permanents dont le style est fixe une fois pour toutes a la construction."""
    if key in C:
        C[key] = hex_value


_BUTTON_RADIUS = 0
_BUTTON_FRAME = True
_INPUT_RADIUS = 0
_INPUT_FRAME = True
_TABLE_RADIUS = 0


def set_button_radius(px: int) -> None:
    global _BUTTON_RADIUS
    _BUTTON_RADIUS = max(0, int(px))


def get_button_radius() -> int:
    """Rayon BOUTON actuellement applique a l'appli principale (voir
    set_button_radius) — sert a la fenetre de parametres pour que ses
    propres boutons peints a la main (popup couleur, voir _Btn) restent
    visuellement coherents avec les vrais boutons de l'appli plutot que
    de rester a angle droit par defaut (voir la remarque de
    l'utilisateur, capture annotee a l'appui)."""
    return _BUTTON_RADIUS


def get_input_radius() -> int:
    """Meme chose que get_button_radius, pour le rayon ZONE DE SAISIE
    (QLineEdit)."""
    return _INPUT_RADIUS


def set_button_frame(on: bool) -> None:
    """Cadre (bordure 1px) des boutons standard (QPushButton, style global
    — pas les boutons peints a la main de la fenetre de parametres, voir sa
    palette M propre). Fenetre de parametres > Geometrie > Boutons."""
    global _BUTTON_FRAME
    _BUTTON_FRAME = bool(on)


def set_input_radius(px: int) -> None:
    global _INPUT_RADIUS
    _INPUT_RADIUS = max(0, int(px))


def set_input_frame(on: bool) -> None:
    """Cadre (bordure 1px) des champs de saisie standard (QLineEdit, style
    global). Fenetre de parametres > Geometrie > Zones de saisie."""
    global _INPUT_FRAME
    _INPUT_FRAME = bool(on)


def set_table_radius(px: int) -> None:
    """Rayon des coins des tableaux standard (QTableWidget/QTableView, style
    global — pas les tableaux peints a la main de la fenetre de parametres,
    qui suivent la meme valeur mais via leur propre palette M, voir
    settings_window._TableFrame). Fenetre de parametres > Geometrie >
    Tableaux. L'appli principale n'a encore aucun tableau standard a ce
    jour : ce reglage est prepare pour le jour ou elle en aura un, voir la
    remarque de l'utilisateur."""
    global _TABLE_RADIUS
    _TABLE_RADIUS = max(0, int(px))


_COLUMN_GAP = 0


def set_column_gap(px: int) -> None:
    """Distance (px) entre 2 colonnes adjacentes du navigateur principal
    (voir pipeline_browser.PipelineBrowser.columns_layout.setSpacing) —
    Fenetre de parametres > Colonnes > Distance entre colonnes. 0 par
    defaut (comportement inchange : colonnes deja collees jusqu'ici).

    PAS de plancher a 0 (max(0, ...) ici avant) : -1 doit rester possible
    (voir settings_window, slider borne a -1) — chaque colonne a deja son
    propre filet de separation de 1px, un espacement de -1 les superpose
    au lieu de les cumuler en un filet de 2px visible — voir la remarque
    de l'utilisateur, "de maniere a ce que les bordures ne se cumulent
    pas"."""
    global _COLUMN_GAP
    _COLUMN_GAP = max(-1, int(px))


def column_gap() -> int:
    return _COLUMN_GAP


_COLUMNS_RESIZABLE = True


def set_columns_resizable(on: bool) -> None:
    """Colonnes agrandissables a la main (glisser la bordure droite, voir
    pipeline_browser._Column._in_resize_zone) — Fenetre de parametres >
    Tableaux > Colonnes dimensionnables. True par defaut (comportement
    inchange : ce glisser existait deja, ce reglage permet juste de le
    desactiver)."""
    global _COLUMNS_RESIZABLE
    _COLUMNS_RESIZABLE = bool(on)


def columns_resizable() -> bool:
    return _COLUMNS_RESIZABLE


# ==========================================================================
# Palette semantique (11 cles), utilisee par la fenetre de parametres (page
# "Couleurs", 2 colonnes) et par la resolution de la couleur d'entete
# ci-dessous : chaque "slot" semantique renvoie vers UNE cle reelle de C.
# "skinAccent" et "selCur" pointent tous deux vers "accent" — le reste de
# l'appli n'a qu'une seule couleur d'accent, a la fois pour la selection
# active ET les boutons principaux (voir la note de "accent" dans
# COLOR_FIELDS ci-dessus) : les deux pastilles de la fenetre de parametres
# restent donc volontairement synchronisees plutot que d'introduire une
# distinction qui n'existe nulle part ailleurs dans l'appli. Pastille
# "Bouton" supprimee (remarque de l'utilisateur, capture annotee a
# l'appui, "supprimer bouton ... sera : skin-accent") : "skinAccent"
# reprend seule ce role, "accent" gardant une seule couleur d'accent pour
# toute l'appli comme avant.
# ==========================================================================

SEMANTIC_COLOR_SLOTS: list[tuple[str, str, str]] = [
    # Mapping zone-par-zone, fixe suite a la remarque de l'utilisateur
    # (nouvelle capture annotee de l'APPLI, chaque zone pointee par une
    # fleche) — remplace le mapping precedent, qui melangeait plusieurs de
    # ces zones a tort :
    #   - "Fond" = C["window"], SEULEMENT l'espace realement vide au-dela de
    #     la derniere colonne (#ColumnsHost) — plus le fond des colonnes
    #     elles-memes (voir "Skin principale niveau 2" plus bas) ;
    #   - "Barre de navigation" = C["app_bg"], la barre de titre maison tout
    #     en haut (#TitleBar) qui sert aussi a deplacer la fenetre (voir
    #     TitleBar.mousePressEvent) — jusqu'ici fixee, sans reglage expose ;
    #   - "Skin principale niveau 1" = C["topbar"], la barre ROOT/Parcourir
    #     juste en dessous (#TopBar) SEULE : le panneau d'apercu
    #     (PreviewColumn) ne la partage plus, voir "niveau 2" ;
    #   - "Skin principale niveau 2" = C["void"], le fond propre de CHAQUE
    #     colonne (liste QListWidget, voir build_stylesheet) ET du panneau
    #     d'apercu (PreviewColumn, sous ses vignettes) ET de l'inspecteur
    #     (DetailPanel, sous ses champs) — un seul ton de "vide" partage par
    #     tout ce qui affiche du contenu, quelle que soit sa nature ;
    #   - "Zone de saisie" = C["well"], le fond des champs de texte (ex :
    #     le champ ROOT) ;
    #   - "Ligne" (nouveau reglage, voir C["line"]) = le filet separateur
    #     optionnel entre les lignes d'une colonne (voir item_row_border_*/
    #     pipeline_browser._paint_row_border), qui utilisait C["border"]
    #     jusqu'ici (pas de reglage dedie) ;
    #   - "Item non selectionne" (nouveau reglage, voir C["row_idle"]) = le
    #     fond de CHAQUE ligne Type/Projets/Sous-projet au repos (ni
    #     selectionnee ni survolee, voir pipeline_browser._paint_unified_row)
    #     — jusqu'ici transparente (aucun fond peint), valeur par defaut
    #     identique a "Skin principale niveau 2" pour ne rien changer tant
    #     que l'utilisateur ne la personnalise pas.
    #
    # Ordre fixe suite a une remarque de l'utilisateur (capture annotee de
    # CETTE grille) : le "sens de lecture" qui compte pour cette liste est
    # celui de l'AFFICHAGE (grille 2 colonnes remplie ligne par ligne, voir
    # _ColorGrid.__init__/divmod(i, 2)) lu de HAUT EN BAS dans la colonne de
    # GAUCHE d'abord, puis de haut en bas dans la colonne de DROITE — pas
    # ligne par ligne de gauche a droite (erreur du premier essai, corrigee
    # ici suite a la remarque de l'utilisateur). Les tuples ci-dessous sont
    # donc ecrits dans l'ordre de la grille (2 par 2, une ligne a la fois),
    # mais leur PROGRESSION logique (voir "skin - accent" plus bas) suit ce
    # sens colonne-par-colonne : colonne de gauche = skinAccent, skinN1,
    # skinN2, fond, saisie, ligne, border2 (7) ; colonne de droite = navbar,
    # selCur, selDone, hover, itemIdle, tableHead, tableRow (7 autres).
    #
    # "skin - accent" ajoutee EN PREMIER de ce sens de lecture (remarque de
    # l'utilisateur, capture annotee a l'appui : "ajouter une couleur
    # skin-accent en premier item, tous les autres seront decales en
    # fonction du sens de lecture") — tout le reste decale d'un cran dans CE
    # sens colonne-par-colonne, ce qui fait deborder l'ancien dernier de la
    # colonne de gauche ("navbar") en tete de la colonne de droite. Meme cle
    # reelle "accent" que "Item - sélectionné-focus" (selCur) : voir la
    # remarque de tete de liste.
    ("skinAccent", "accent", "skin - accent"),
    ("navbar", "app_bg", "Barre de navigation"),
    ("skinN1", "topbar", "skin - niveau1"),
    ("selCur", "accent", "Item - sélectionné-focus"),
    ("skinN2", "void", "skin - niveau2"),
    ("selDone", "sel_idle", "Item - sélectionné"),
    ("fond", "window", "skin - fond"),
    ("hover", "hover", "Item - survol"),
    ("saisie", "well", "Zone de saisie"),
    ("itemIdle", "row_idle", "Item - non sélectionné"),
    ("ligne", "line", "Bordures niveau 1"),
    ("tableHead", "table_head", "Tableau - entête"),
    # Nouvelle pastille demandee par l'utilisateur ("Bordures niveau 2, a
    # creer") : expose C["border"] (deja une cle reelle existante — les
    # "Bordures et separateurs" generaux, voir COLOR_FIELDS plus haut, deja
    # persistee mais jusqu'ici absente de CETTE grille) plutot que d'ajouter
    # une cle entierement nouvelle a C — meme role que "Bordures niveau 1"
    # (C["line"]) juste au-dessus, mais l'AUTRE tier de bordure deja
    # distinct dans l'appli.
    ("border2", "border", "Bordures niveau 2"),
    # Derniere pastille : concerne UNIQUEMENT la fenetre de parametres
    # elle-meme (ses propres tableaux "fermes" Polices/Entetes/Geometrie,
    # voir settings_window._sync_dynamic_M) — l'appli principale n'a pas
    # encore de tableau standard a proprement parler (voir set_table_radius),
    # donc elle n'a aucun effet visible ailleurs, y compris si choisie
    # (improbable mais sans consequence) comme source de la couleur d'entete
    # de colonne.
    ("tableRow", "table_row", "Tableau - fond"),
]
_SEMANTIC_TO_REAL = {slot: real for slot, real, _ in SEMANTIC_COLOR_SLOTS}

_HEADER_COLOR_SLOT = "skinN1"
_HEADER_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
_HEADER_RADIUS = {k: 0 for k in _HEADER_CORNERS}
_HEADER_BORDER_ENABLED = {"top": False, "right": False, "bottom": True, "left": False}
_HEADER_BORDER = {"top": "", "right": "", "bottom": "", "left": ""}   # "" = pas encore personnalise, retombe sur C['border']
_HEADER_BORDER_THICKNESS = 1


def _coerce_header_radius(value) -> dict:
    """Meme convention que settings_window._coerce_corner_radius (int
    unique, retro-compatible, OU dict {"top_left": int, ...} — un rayon PAR
    COIN, voir settings_window._CornerRadiusField/la remarque de
    l'utilisateur, "dans tous les parametres de coins arrondis, je veux
    exactement le meme fonctionnement que les padding")."""
    if isinstance(value, dict):
        return {k: max(0, int(value.get(k, 0))) for k in _HEADER_CORNERS}
    v = max(0, int(value)) if value is not None else 0
    return {k: v for k in _HEADER_CORNERS}


def set_header_style(color_slot: str, radius, border_enabled: dict, border_colors: dict | None = None,
                      border_thickness: int = 1) -> None:
    """Reglages de l'entete de colonne (et de l'inspecteur, voir header_qss)
    pilotes par la fenetre de parametres > Colonnes > Entetes : quelle
    pastille semantique alimente le fond (OU une couleur PERSONNALISEE, un
    hex direct "#rrggbb" — voir settings_window._HeaderColorField, "je veux
    pouvoir personnaliser la couleur"), un rayon PAR COIN (voir
    _coerce_header_radius), et la bordure — un interrupteur PAR COTE
    (border_enabled) + une couleur INDEPENDANTE par cote (border_colors) +
    une epaisseur partagee (border_thickness) — voir settings_window.
    _ToggleSideColorsField, MEME reglage que Colonnes > Bordure (voir la
    remarque de l'utilisateur, "je veux exactement les memes parametre de
    controle que celui des colonnes")."""
    global _HEADER_COLOR_SLOT, _HEADER_RADIUS, _HEADER_BORDER_ENABLED, _HEADER_BORDER, _HEADER_BORDER_THICKNESS
    is_custom_hex = isinstance(color_slot, str) and color_slot.startswith("#")
    _HEADER_COLOR_SLOT = color_slot if (is_custom_hex or color_slot in _SEMANTIC_TO_REAL) else "skinN1"
    _HEADER_RADIUS = _coerce_header_radius(radius)
    _HEADER_BORDER_ENABLED = {k: bool(border_enabled.get(k, False)) for k in ("top", "right", "bottom", "left")}
    border_colors = border_colors or {}
    _HEADER_BORDER = {k: str(border_colors.get(k) or "") for k in ("top", "right", "bottom", "left")}
    _HEADER_BORDER_THICKNESS = max(0, int(border_thickness))


def header_bg_hex() -> str:
    if _HEADER_COLOR_SLOT.startswith("#"):
        return _HEADER_COLOR_SLOT
    return C.get(_SEMANTIC_TO_REAL.get(_HEADER_COLOR_SLOT, "chrome"), C["chrome"])


def header_border_color(side: str) -> str:
    return _HEADER_BORDER.get(side) or C["border"]


def header_qss(object_name: str) -> str:
    """Regle QSS complete (scopee a #object_name, voir la remarque sur les
    selecteurs nus dans pipeline_browser.py) pour le FOND configurable d'une
    barre d'entete — Column.header_fill ET DetailPanel.header_fill
    partagent cette meme resolution. Le filet de separation structurel de
    l'inspecteur (frontiere avec la derniere colonne) est gere a part, sur
    le widget exterieur non inset (voir DetailPanel.__init__/refresh_colors
    — HEADER_PADDING ne doit inset que ce fond configurable, jamais cette
    limite de panneau)."""
    def edge(name: str) -> str:
        # "0px solid transparent", PAS le mot-cle "none" (voir column_frame_
        # qss, MEME raison — le moteur QSS de Qt peut alors carrement
        # ignorer border-radius pour le FOND, le laissant deborder carre au-
        # dela du coin arrondi sur un cote sans bordure).
        if _HEADER_BORDER_THICKNESS <= 0 or not _HEADER_BORDER_ENABLED.get(name):
            return "0px solid transparent"
        return f"{_HEADER_BORDER_THICKNESS}px solid {header_border_color(name)}"
    # PAS le raccourci CSS "border-radius: TL TR BR BL" (4 valeurs) : Qt ne
    # le supporte PAS (contrairement a un navigateur) — verifie directement
    # (2 boites identiques sauf ceci, l'une au raccourci 4-valeurs reste
    # CARREE, l'autre aux 4 proprietes separees arrondit bien SEULEMENT le
    # coin voulu) — voir la remarque de l'utilisateur, capture a l'appui,
    # "quand on bouge un slider, il affecte plusieurs cotes" : Qt ignore
    # silencieusement la regle entiere des qu'elle porte plus d'une valeur,
    # ne laissant plus par defaut QUE le rayon du DERNIER "border-radius"
    # a une seule valeur encore valide ailleurs dans la feuille de style —
    # d'ou l'impression qu'UN seul cran de slider deplacait TOUS les
    # coins a la fois. Les 4 proprietes PAR COIN, elles, sont individuellement
    # bien supportees.
    radius_qss = (
        f"border-top-left-radius: {_HEADER_RADIUS['top_left']}px; "
        f"border-top-right-radius: {_HEADER_RADIUS['top_right']}px; "
        f"border-bottom-right-radius: {_HEADER_RADIUS['bottom_right']}px; "
        f"border-bottom-left-radius: {_HEADER_RADIUS['bottom_left']}px;"
    )
    return (
        f"#{object_name} {{ background: {header_bg_hex()}; {radius_qss} "
        f"border-top: {edge('top')}; border-right: {edge('right')}; "
        f"border-bottom: {edge('bottom')}; border-left: {edge('left')}; }}"
    )


# Cles de reglage "Colonnes/Entetes/Texte/Image/Selection" resolvables PAR
# TITRE de colonne (voir set_column_style/column_style_for ci-dessous,
# pipeline_browser.apply_all_settings, settings_window._build_column_
# override_page) — SOURCE UNIQUE partagee par pipeline_browser.py ET
# settings_window.py (auparavant maintenue independamment dans chacun des
# 2 fichiers, avec un risque de divergence a chaque nouvelle cle — voir la
# remarque de l'utilisateur, "clean le code"). COLUMN_FRAME_KEYS seul reste
# utile a part (voir pipeline_browser.COLUMN_SETTINGS, remarque de tete) :
# cadre/entete, applique a TOUTE colonne, alors que le reste de
# COLUMN_TYPE_OVERRIDE_KEYS (texte/selection/image des LIGNES) ne concerne
# que les 3 colonnes surchargeables (Type/Projets/Sous-projet).
COLUMN_FRAME_KEYS = [
    "header_visible", "header_height", "header_padding", "header_color", "header_radius",
    "header_border_enabled", "header_border", "header_border_thickness",
    "column_padding", "column_border_enabled", "column_border", "column_border_thickness", "column_border_radius",
    "column_bg_color",
]

# Titre "virtuel" de la colonne fantome de l'apercu image empile (voir
# pipeline_browser.PreviewColumn/PipelineBrowser.image_preview_column) —
# le gros apercu qui apparait une fois une selection faite dans Projets/
# Sous-projet, PAS ces 2 colonnes elles-memes — voir la remarque de
# l'utilisateur, "je ne sais pas comment les appeler quand je te demande
# de les modifier", d'ou ce nom/cette cle — "Focus" (renomme depuis
# "Aperçu", voir la remarque de l'utilisateur, "change la tab APERCU pour
# FOCUS stp, ca parle plus" — a changer ici SEUL si un autre nom est
# prefere, tout le reste — onglet, en-tete affiche ET resolution de style
# dans les 2 fichiers — en depend). Definie ici (pas dans pipeline_
# browser.py) : settings_window.py en a besoin aussi, pour son propre
# onglet de surcharge (voir SettingsWindow._build_columns_page).
PREVIEW_STACK_TITLE = "Focus"

COLUMN_TYPE_OVERRIDE_KEYS = COLUMN_FRAME_KEYS + [
    "item_font_family", "item_font_size", "item_font_bold", "item_color",
    "item_antialias_override_enabled", "item_antialias_override",
    "item_icon_enabled", "item_row_height", "item_row_spacing", "item_column_width", "item_header_gap",
    "item_text_padding", "item_selection_focus_color", "item_selection_unfocus_color", "item_hover_color",
    "item_idle_color",
    "item_selection_padding", "item_selection_border_enabled", "item_selection_border",
    "item_selection_radius", "item_selection_edge_border",
    "item_row_border_enabled", "item_row_border_color", "item_row_border_thickness",
    "item_image_padding", "item_image_border_enabled", "item_image_border",
    "item_image_border_thickness", "item_image_radius", "item_image_ratio",
    # Colonnes > Apercu (voir pipeline_browser.PreviewColumn/_PreviewBlock/
    # PREVIEW_STACK_TITLE) — SPECIFIQUES a cette colonne, jamais exposees
    # ni partagees ailleurs (contrairement aux cles item_* ci-dessus,
    # communes a Type/Projets/Sous-projet/Logiciels/Contenu) : incluses
    # ici quand meme pour que column_style_for(PREVIEW_STACK_TITLE) les
    # resolve par le MEME mecanisme general/surcharge, sans code separe —
    # voir la remarque de l'utilisateur, "je veux une section image ...
    # zone titre ... bouton repliement". "preview_padding"/"preview_radius"
    # (dicts, 4 cotes/4 coins INDEPENDANTS — voir la remarque de
    # l'utilisateur, "controle des paddings sur les 4 cotes comme partout
    # ailleurs ... pareil pour les coins arrondis") remplacent les
    # anciennes cles "preview_pad"/"preview_radius" (int uniforme).
    "preview_padding", "preview_radius",
    "preview_title_zone_height",
    "preview_title_font_size", "preview_title_font_color",
    "preview_title_font_family", "preview_title_font_smoothing_enabled", "preview_title_font_smoothing",
    "preview_title_padding",
    "preview_status_font_size", "preview_status_font_color", "preview_status_font_color_idle",
    "preview_status_font_family", "preview_status_font_smoothing_enabled", "preview_status_font_smoothing",
    "preview_status_padding",
    "preview_toggle_width", "preview_toggle_height", "preview_toggle_bg_color",
    "preview_toggle_border_enabled", "preview_toggle_border", "preview_toggle_border_thickness",
    "preview_toggle_radius", "preview_toggle_x", "preview_toggle_y",
]


# ==========================================================================
# Style de colonne — settings_window._section_headers ("Colonnes" dans
# l'onglet General) APPLIQUE pour de vrai a TOUTES les colonnes (voir
# pipeline_browser.Column/RowDelegate) — contrairement a une 1ere version,
# qui ne le cablait QUE sur la colonne "Type" (voir la remarque de
# l'utilisateur, "je veux que tu en fasse de meme pour toute les colonnes
# de l'appli. les settings doivent refletter a 100% ce qui se passe dans
# l'appli"). Colonnes > Type peut en outre SURCHARGER individuellement
# chaque parametre pour elle-meme (toggle par ligne, voir settings_window.
# _build_column_type_page) : `style_for(title)` renvoie deja la valeur
# EFFECTIVE (surchargee si activee pour "Type", sinon la generale) —
# resolue une seule fois par pipeline_browser.apply_all_settings, pas ici.
# ==========================================================================

_GENERAL_COLUMN_STYLE: dict = {}
# Style EFFECTIF PAR titre reel de colonne (voir COLUMN_OVERRIDABLE_TITLES) —
# generalise de l'ancien _TYPE_COLUMN_STYLE (un seul dict, "Type"
# uniquement) pour couvrir aussi "Projets"/"Sous-projet" (voir la remarque
# de l'utilisateur, "place ensuite cette meme section dans les onglets
# projets et sous projets pour y controler les colonnes respectives").
_COLUMN_STYLES: dict[str, dict] = {}


def set_general_column_style(style: dict) -> None:
    """Style EFFECTIF (general, sans aucune surcharge) applique a TOUTE
    colonne SANS surcharge active — voir set_column_style ci-dessous pour
    les colonnes qui en ont une."""
    global _GENERAL_COLUMN_STYLE
    _GENERAL_COLUMN_STYLE = dict(style)


def set_column_style(title: str, style: dict) -> None:
    """Style EFFECTIF (general ou surcharge par ligne, voir
    pipeline_browser.apply_all_settings) d'UNE colonne precise ("Type",
    "Projets" ou "Sous-projet")."""
    _COLUMN_STYLES[title] = dict(style)


def column_style_for(title: str) -> dict:
    """Style EFFECTIF d'UNE colonne precise, quel que soit son titre — voir
    Column.refresh_colors/refresh_header/_column_padding, qui l'appellent
    tous avec le titre de LEUR colonne plutot que de choisir eux-memes
    entre general/Type."""
    return _COLUMN_STYLES.get(title) or _GENERAL_COLUMN_STYLE


def resolve_color_ref(value, fallback: str = "") -> str:
    """Meme convention que settings_window._resolve_color_value ("#rrggbb"
    direct OU reference "@<slot>" a une pastille semantique) mais resolue
    ici contre la palette REELLE de l'appli (`C`, deja tenue a jour par
    set_color) — pas de dict "colors" separe a faire suivre, contrairement
    a la fenetre de parametres (qui doit aussi suivre une palette LIVE
    pendant un glisser, voir _apply_column_preview)."""
    if isinstance(value, str) and value.startswith("@"):
        return C.get(_SEMANTIC_TO_REAL.get(value[1:], "chrome"), C["chrome"])
    return value or fallback or C["border"]


def _column_header_bg_hex(style: dict) -> str:
    slot = style.get("header_color", "skinN1")
    if isinstance(slot, str) and slot.startswith("#"):
        return slot
    return C.get(_SEMANTIC_TO_REAL.get(slot, "chrome"), C["chrome"])


def column_header_qss(object_name: str, title: str) -> str:
    """Meme construction que header_qss ci-dessus, mais a partir du style
    EFFECTIF de CETTE colonne (voir column_style_for) plutot que des
    globals _HEADER_* partages a l'ancienne — voir Column.refresh_colors,
    appele pour TOUTE colonne desormais (general ou surcharge Type).

    Rayon propre de l'entete UNIQUEMENT (header_radius) — plus de
    "nibbling" (agrandissement des coins hauts au rayon de la colonne) :
    ancien palliatif, ecrit AVANT que pipeline_browser.Column.card ne
    decoupe REELEMENT (voir _RoundedCornersEffect) tout son contenu
    (entete ET liste compris) a la silhouette exacte du rayon de la
    colonne. Le rognage visuel est donc deja garanti par ce decoupage —
    forcer EN PLUS le rayon PROPRE de l'entete a suivre celui de la
    colonne ne faisait plus que gonfler artificiellement sa courbure,
    meme quand header_radius est explicitement regle a 0 — voir la
    remarque de l'utilisateur, capture a l'appui, "quand je regle le
    padding de l'entete a 0, je me retrouve avec des bordures radius
    monstrueux alors qu'il est a 0 dans les settings".

    Un nibbling avait ete brievement reintroduit (voir git blame) pour
    contourner un cas ou le decoupage ci-dessus ne recoupait pas
    fiablement l'entete — REVENU EN ARRIERE sur demande explicite de
    l'utilisateur : "je ne veux pas que le fait de mettre un arrondi sur
    les colonnes affecte les arrondis des entetes (j'ai deja un
    parametre pour ca)". Le rayon de l'entete suit donc a nouveau
    UNIQUEMENT header_radius, jamais column_border_radius."""
    s = column_style_for(title)
    radius = dict(_coerce_header_radius(s.get("header_radius", 0)))
    enabled = s.get("header_border_enabled") or {}
    colors = s.get("header_border") or {}
    thickness = max(0, int(s.get("header_border_thickness", 1)))

    def edge(name: str) -> str:
        # "0px solid transparent", PAS "none" — voir column_frame_qss, meme
        # raison (le fond deborde carre du coin arrondi sinon).
        if thickness <= 0 or not enabled.get(name):
            return "0px solid transparent"
        return f"{thickness}px solid {resolve_color_ref(colors.get(name))}"

    # PAS le raccourci CSS "border-radius: TL TR BR BL" — voir header_qss,
    # MEME correctif/MEME raison (Qt ne le supporte pas, contrairement a un
    # navigateur — verifie directement) : ces 4 proprietes SEPAREES le
    # remplacent.
    radius_qss = (
        f"border-top-left-radius: {radius['top_left']}px; "
        f"border-top-right-radius: {radius['top_right']}px; "
        f"border-bottom-right-radius: {radius['bottom_right']}px; "
        f"border-bottom-left-radius: {radius['bottom_left']}px;"
    )
    return (
        f"#{object_name} {{ background: {_column_header_bg_hex(s)}; {radius_qss} "
        f"border-top: {edge('top')}; border-right: {edge('right')}; "
        f"border-bottom: {edge('bottom')}; border-left: {edge('left')}; }}"
    )


def column_frame_style(title: str, suppress_left: bool = False) -> dict:
    """Cadre de la colonne elle-meme (Colonnes > Bordure/Rayon des angles
    de bordure) — remplace, pour TOUTE colonne, le simple "border-right:
    1px solid" code en dur jusqu'ici (voir Column.__init__/refresh_colors,
    la remarque de l'utilisateur au sujet de cette decouverte : ce reglage
    general n'etait jusqu'ici JAMAIS applique a l'appli reelle, seulement a
    l'apercu de la fenetre de parametres).

    Renvoie les valeurs BRUTES (radius/enabled/colors DEJA resolues/
    thickness), PAS une chaine QSS : voir pipeline_browser._ColumnCard,
    peinte a la main (QPainter, _paint_bordered_rect) — PAS de border-
    radius QSS ici — pour que le masque de decoupe des enfants (voir
    Column._update_card_mask) utilise EXACTEMENT la meme geometrie que ce
    qui est reellement peint, plutot que de tenter de faire correspondre
    2 moteurs de rendu differents (le style QSS de Qt, puis un chemin
    arrondi maison pour le masque) — voir la remarque de l'utilisateur,
    capture a l'appui, "le cadre n'enveloppe pas les bordures radius".

    `suppress_left` (voir Column.refresh_colors, colonne PAS la premiere ET
    "Distance entre colonnes" <= 0) — MEME regle que settings_window.
    _ColumnPreview (has_left_neighbor) : quand 2 colonnes se touchent, un
    SEUL filet reste visible a leur frontiere (celui de DROITE de la
    colonne de GAUCHE) plutot que 2 cumules."""
    s = column_style_for(title)
    radius = _coerce_header_radius(s.get("column_border_radius", 0))
    enabled = dict(s.get("column_border_enabled") or {})
    if suppress_left:
        enabled["left"] = False
    thickness = max(0, int(s.get("column_border_thickness", 1)))
    colors = {k: resolve_color_ref(v) for k, v in (s.get("column_border") or {}).items()}
    # "@skinN2" (= C["void"]) par defaut : comportement INCHANGE tant que
    # l'utilisateur ne personnalise rien — voir la remarque de
    # l'utilisateur, "dans la section general/colonne/colonne je veux un
    # parametre couleur de fond".
    bg = resolve_color_ref(s.get("column_bg_color", "@skinN2"))
    return {"radius": radius, "enabled": enabled, "colors": colors, "thickness": thickness, "bg": bg}


def column_padding_for(title: str) -> dict:
    """Padding EFFECTIF (voir settings_window._ColumnPreview.setPadding,
    MEME comportement "carte flottante" — le fond+la bordure de la colonne
    RETRECISSENT, revelant le fond de la fenetre tout autour, plutot qu'un
    simple retrait de son contenu) de CETTE colonne — voir Column.card/
    _refresh_card_margins."""
    s = column_style_for(title)
    pad = s.get("column_padding") or {}
    return {side: max(0, int(pad.get(side, 0))) for side in ("top", "right", "bottom", "left")}


# ==========================================================================
# Feuille de style Qt (QSS) commune
# ==========================================================================

def build_stylesheet() -> str:
    """Regenere le QSS global a partir des valeurs courantes de C et du
    rayon de bordure des boutons — appelee a chaque changement de couleur
    (voir refresh_style) plutot qu'une seule fois au demarrage, pour que la
    previsualisation en direct de la fenetre de parametres fonctionne."""
    input_border = f"1px solid {C['border_soft']}" if _INPUT_FRAME else "none"
    button_border = f"1px solid {C['btn_border']}" if _BUTTON_FRAME else "none"
    # QListWidget (Skin principale niveau 2 / void), PAS Fond (window) : le
    # vide propre a chaque colonne de l'appli principale (QListWidget, seul
    # usage de cette classe hors fenetre de parametres, voir Column) suit
    # desormais sa propre couleur, distincte du fond genere au-dela de la
    # derniere colonne (#ColumnsHost, voir PipelineBrowser) — voir la
    # remarque de l'utilisateur, nouvelle capture annotee a l'appui.
    return f"""
QWidget {{ background: {C['window']}; color: {C['text']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {C['window']}; }}
QListWidget {{ background: {C['void']}; border: none; outline: none; }}

QLineEdit {{
    background: {C['well']};
    border: {input_border};
    border-radius: {_INPUT_RADIUS}px;
    color: {C['text_mono']};
    padding: 0 8px;
    selection-background-color: {C['accent']};
}}

QPushButton {{
    background: {C['btn']};
    border: {button_border};
    border-radius: {_BUTTON_RADIUS}px;
    color: #c4cacf;
    padding: 0 12px;
}}
QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}
QPushButton:pressed {{
    background: {C['accent']};
    border-color: {C['accent']};
    color: {C['accent_text']};
}}

QTableWidget, QTableView {{
    border: 1px solid {C['border']};
    border-radius: {_TABLE_RADIUS}px;
}}

QScrollBar:vertical, QScrollBar:horizontal {{ background: transparent; width: 9px; height: 9px; margin: 0; }}
QScrollBar::handle {{ background: {C['scroll']}; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {C['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {C['chrome']}; border: 1px solid {C['border']}; padding: 4px 0; }}
QMenu::item {{ padding: 5px 18px; color: {C['text']}; }}
QMenu::item:selected {{ background: {C['accent']}; color: {C['accent_text']}; }}
"""


STYLESHEET = build_stylesheet()

# Cles de C reellement lues par build_stylesheet ci-dessus (a tenir a jour
# avec elle) — sert a PipelineBrowser._apply_settings pour ne rebatir le
# QSS global (app.setStyleSheet, ~100ms mesures sur une appli de taille
# normale : le poste de loin le plus cher de tout le rafraichissement live
# de la fenetre de parametres) que si une couleur qui compte VRAIMENT pour
# lui a change — pas a chaque pixel du glisser d'une pastille QUELCONQUE
# de la page Couleurs (la moitie des ~30 couleurs reglables, ex.
# table_head/table_row/sel_idle/hover, n'apparaissent nulle part dans ce
# QSS et n'ont donc aucune raison d'en forcer la reconstruction) — voir la
# remarque de l'utilisateur sur la latence au glisser.
STYLESHEET_COLOR_KEYS = (
    "window", "text", "void", "well", "text_mono", "accent", "accent_text",
    "btn", "btn_border", "btn_hover", "btn_hover_bd", "border", "border_soft",
    "scroll", "scroll_hover", "chrome",
)


def apply_style(app) -> None:
    """Applique le style commun (style Fusion + QSS) a une QApplication."""
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())


# ==========================================================================
# Cadre DWM des fenetres sans decoration (frameless) — commun a toutes les
# fenetres de premier niveau de l'appli (navigateur, parametres...).
# ==========================================================================

# Rayon utilise quand le toggle "coins arrondis" (fenetre de parametres,
# General) est active — plus de slider en pixels : Windows ne propose de
# toute facon que rond/pas-rond cote DWM (voir apply_dwm_frame), un choix
# fin en pixels n'avait donc de sens que sur le radius peint cote QSS, pas
# sur le rendu natif qui l'accompagne forcement en pratique.
WINDOW_ROUNDED_RADIUS = 12

def apply_dwm_frame(widget, radius: int, border_hex: str, resizable: bool = False) -> None:
    """Sur Windows 11, le compositeur (DWM) arrondit et colore DEJA de
    lui-meme toute fenetre de premier niveau sans decoration (voir
    Qt.FramelessWindowHint), qu'on le lui demande ou non — avec sa propre
    couleur d'accent systeme (souvent bleu vif) et surtout un arrondi
    FIXE, impose meme quand l'appli demande un "border radius" nul cote
    QSS. C'etait la cause du reglage "Border radius de la fenetre
    principale" sans effet visible : quelle que soit la valeur choisie,
    DWM imposait son propre preset par-dessus.

    On lui redemande donc explicitement ce meme filet, mais dans la
    couleur de bordure de l'appli, ET SURTOUT sans arrondi (DONOTROUND) des
    que radius<=0 — Windows n'offre de toute facon aucun controle fin du
    rayon cote DWM (juste round/round-petit/aucun), le rayon EXACT choisi
    par l'utilisateur reste peint cote QSS (voir central/#Panel) ; ceci
    n'a qu'a s'assurer que DWM ne vient plus contredire ce choix.

    A appeler pour CHAQUE fenetre frameless de l'appli (navigateur,
    parametres...) — pas seulement la principale — sans quoi les autres
    restent soumises au comportement par defaut de DWM decrit ci-dessus.

    resizable=True pose en plus WS_THICKFRAME/WS_MAXIMIZEBOX/WS_MINIMIZEBOX
    (necessaires a l'accrochage aux bords/Aero Snap) — reserve a une
    fenetre vraiment redimensionnable par l'utilisateur (le navigateur),
    pas a une boite de dialogue de taille fixe.

    Sans effet (silencieusement) hors Windows, ou sur Windows 10 et
    anterieur ou ces attributs DWM n'existent pas.

    Les 2 DwmSetWindowAttribute plus bas (coin/couleur) forcent le
    compositeur a recalculer tout le cadre de la fenetre — ~20ms mesures,
    negligeable pour un appel isole mais couteux rejoue a chaque frame :
    SettingsWindow rappelle cette fonction a CHAQUE glisser d'un slider de
    couleur (voir _refresh_dynamic_colors), la plupart du temps avec un
    radius/border_hex IDENTIQUES au dernier appel (seul un sous-ensemble
    des couleurs reglables affecte reellement panel_border). D'ou ce
    cache par widget (radius, border_hex) qui saute les deux appels natifs
    quand rien n'a change depuis la derniere fois — voir la remarque de
    l'utilisateur sur la latence au glisser."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        if resizable:
            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            WS_MAXIMIZEBOX = 0x00010000
            WS_MINIMIZEBOX = 0x00020000
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            wanted = style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX
            if wanted != style:
                user32.SetWindowLongW(hwnd, GWL_STYLE, wanted)
                # SANS CA : Windows garde en cache l'ancien frame tant qu'on
                # ne le lui redemande pas explicitement — le bit WS_THICKFRAME
                # ne devient reellement effectif (WM_NCHITTEST/curseur/
                # glisser de redimensionnement) qu'apres un SetWindowPos avec
                # SWP_FRAMECHANGED. Sans lui, le redimensionnement par les
                # bords pouvait rester silencieusement mort au survol (voir
                # la remarque de l'utilisateur : rien ne se passait du tout).
                SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x0002, 0x0001, 0x0004, 0x0020
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
                )
        hexcolor = (border_hex or "").lstrip("#")
        cache_key = (radius <= 0, hexcolor)
        if getattr(widget, "_dwm_frame_cache", None) == cache_key:
            return
        widget._dwm_frame_cache = cache_key
        dwmapi = ctypes.windll.dwmapi
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        DWMWCP_ROUND = 2
        DWMWA_BORDER_COLOR = 34
        pref = ctypes.c_int(DWMWCP_DONOTROUND if radius <= 0 else DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref)
        )
        if len(hexcolor) == 6:
            r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
            colorref = ctypes.c_uint32((b << 16) | (g << 8) | r)
            dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR, ctypes.byref(colorref), ctypes.sizeof(colorref)
            )
    except Exception:
        pass


def start_native_move(widget) -> None:
    """Demarre le glisser natif d'une fenetre de premier niveau sans
    decoration (barre de titre maison, voir mousePressEvent des TitleBar de
    l'appli). Sur Windows, pilote directement DefWindowProc (ReleaseCapture
    + SendMessage SC_MOVE) plutot que QWindow.startSystemMove() : ce
    dernier POSTE son message SC_MOVE (traite plus tard, de facon
    asynchrone), alors que SendMessage est synchrone — DefWindowProc entre
    dans sa boucle de glisser modale immediatement, dans le meme appel.
    Avec le message poste, si d'autres evenements souris arrivent avant que
    Windows ne traite ce message en file, la fenetre "rate" le debut du
    glisser et ne raccroche qu'au premier mouvement capte par la boucle
    modale — souvent bien apres que le curseur s'est deja eloigne (symptome
    signale par l'utilisateur : la fenetre ne suit pas tout de suite le
    clic, puis "s'accroche" longtemps plus tard).

    Retombe sur QWindow.startSystemMove() hors Windows (ou si l'appel bas
    niveau echoue), avec le meme defaut potentiel mais toujours fonctionnel."""
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = int(widget.winId())
            user32 = ctypes.windll.user32
            user32.ReleaseCapture()
            WM_SYSCOMMAND = 0x0112
            SC_MOVE = 0xF010
            # +2 : variante "mouse-initiated" de SC_MOVE — indique a
            # DefWindowProc de suivre le curseur depuis sa position
            # courante plutot que d'attendre des fleches clavier.
            user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_MOVE + 2, 0)
            return
        except Exception:
            pass
    handle = widget.windowHandle()
    if handle is not None:
        handle.startSystemMove()


def resize_hit_test(widget, message, border: int = 6):
    """Reponse a un WM_NCHITTEST pour une fenetre frameless redimensionnable
    par les bords (voir apply_dwm_frame(..., resizable=True)) : sans cadre
    natif, Windows ne sait plus quel bord/coin est survole pour proposer le
    curseur et le glisser de redimensionnement habituels — on repond
    nous-memes, Windows/Qt gerent ensuite le reste (curseur, aimantation,
    contraintes de taille) normalement, comme pour une fenetre a cadre
    classique. Factorise ici (identique jusque-la a la fenetre principale)
    pour que toute fenetre frameless redimensionnable de l'appli (voir
    PipelineBrowser.nativeEvent, SettingsWindow.nativeEvent) partage le
    meme calcul plutot que de le dupliquer.

    Retourne None si l'evenement n'est pas un WM_NCHITTEST exploitable —
    l'appelant doit alors retomber sur super().nativeEvent() — ou (True,
    hit) sinon, directement renvoyable tel quel depuis nativeEvent()."""
    if sys.platform != "win32" or widget.isMaximized():
        return None
    try:
        from ctypes import wintypes
        msg = wintypes.MSG.from_address(int(message))
        if msg.message != 0x0084:  # WM_NCHITTEST
            return None
        import ctypes
        x = ctypes.c_short(msg.lParam & 0xFFFF).value - widget.frameGeometry().x()
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value - widget.frameGeometry().y()
        w, h, b = widget.width(), widget.height(), border
        left, right = x < b, x > w - b
        top, bottom = y < b, y > h - b
        hit = None
        if top and left: hit = 13       # HTTOPLEFT
        elif top and right: hit = 14    # HTTOPRIGHT
        elif bottom and left: hit = 16  # HTBOTTOMLEFT
        elif bottom and right: hit = 17 # HTBOTTOMRIGHT
        elif left: hit = 10             # HTLEFT
        elif right: hit = 11            # HTRIGHT
        elif top: hit = 12              # HTTOP
        elif bottom: hit = 15           # HTBOTTOM
        if hit is not None:
            return True, hit
    except Exception:
        pass
    return None


def refresh_style(app) -> None:
    """Reapplique le QSS global apres un changement de couleur/rayon de
    bouton (voir set_color/set_button_radius) : a appeler en plus de
    apply_style, qui n'est utile qu'une fois au demarrage."""
    app.setStyleSheet(build_stylesheet())
