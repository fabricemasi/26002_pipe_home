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
    "sel_idle":      "#2e3338",
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
}

# ==========================================================================
# Polices
# ==========================================================================

_SANS = None
_MONO = None
_NAME = None


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
SMOOTHING_LABELS = {
    "current": "Lissage actuel",
    "previous": "Lissage precedent",
    "none": "Pas de lissage",
}
# Intitules courts (3 positions) demandes pour la fenetre de parametres :
# memes cles que SMOOTHING_CHOICES, juste un libelle plus compact.
SMOOTHING_LABELS_SHORT = {"current": "Haut", "previous": "Moyen", "none": "Sans"}

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
_ROLE_OVERRIDES: dict[str, dict] = {
    role: dict(_ROLE_DEFAULTS)
    for role in ("app", "titles", "files", "folders", "info", "info2", "buttons", "colhead")
}


def set_role_font(role: str, family: str, size: int, bold: bool,
                   smoothing: str = "current", color: str = "", custom: bool = True) -> None:
    """Enregistre la surcharge typographique d'un role : 'app', 'titles',
    'files', 'folders', 'buttons', 'colhead', 'info' ou 'info2'. `custom`
    (True par defaut : un appel explicite vaut personnalisation) distingue
    "jamais touche dans la fenetre de parametres" (taille/gras ignores,
    chaque appelant garde sa propre taille/graisse par defaut — voir
    role_font) de "personnalise, meme en laissant la police sur
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
    ("sel_idle", "Selection (colonne inactive)", "Ligne selectionnee hors focus"),
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
]


def set_color(key: str, hex_value: str) -> None:
    """Modifie une couleur de l'interface (cle de C) en direct. N'affecte
    par elle-meme que les widgets construits APRES l'appel — voir
    refresh_style() pour re-appliquer la feuille de style Qt globale, et
    le cote appelant (pipeline_browser.refresh_colors) pour les widgets
    permanents dont le style est fixe une fois pour toutes a la construction."""
    if key in C:
        C[key] = hex_value


_BUTTON_RADIUS = 0


def set_button_radius(px: int) -> None:
    global _BUTTON_RADIUS
    _BUTTON_RADIUS = max(0, int(px))


# ==========================================================================
# Feuille de style Qt (QSS) commune
# ==========================================================================

def build_stylesheet() -> str:
    """Regenere le QSS global a partir des valeurs courantes de C et du
    rayon de bordure des boutons — appelee a chaque changement de couleur
    (voir refresh_style) plutot qu'une seule fois au demarrage, pour que la
    previsualisation en direct de la fenetre de parametres fonctionne."""
    return f"""
QWidget {{ background: {C['window']}; color: {C['text']}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {C['window']}; }}
QListWidget {{ background: {C['window']}; border: none; outline: none; }}

QLineEdit {{
    background: {C['well']};
    border: 1px solid {C['border_soft']};
    color: {C['text_mono']};
    padding: 0 8px;
    selection-background-color: {C['accent']};
}}

QPushButton {{
    background: {C['btn']};
    border: 1px solid {C['btn_border']};
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
    anterieur ou ces attributs DWM n'existent pas."""
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
        dwmapi = ctypes.windll.dwmapi
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        DWMWCP_ROUND = 2
        DWMWA_BORDER_COLOR = 34
        pref = ctypes.c_int(DWMWCP_DONOTROUND if radius <= 0 else DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref)
        )
        hexcolor = (border_hex or "").lstrip("#")
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


def refresh_style(app) -> None:
    """Reapplique le QSS global apres un changement de couleur/rayon de
    bouton (voir set_color/set_button_radius) : a appeler en plus de
    apply_style, qui n'est utile qu'une fois au demarrage."""
    app.setStyleSheet(build_stylesheet())
