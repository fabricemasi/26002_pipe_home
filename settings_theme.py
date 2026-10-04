"""Styles de la fenetre de reglages, en UN SEUL endroit.

Chaque texte de la fenetre porte un ROLE (libelle de ligne, texte colle a
un controle, note...) plutot qu'une police et une couleur posees a la main :
changer l'apparence d'un role ici la change PARTOUT ou il est utilise.
Pour un nouveau texte, choisir le role existant qui correspond a son usage
(voir TEXT_ROLES) ; n'en creer un nouveau que pour un usage reellement
nouveau.

Vient juste apres settings_store dans l'ordre de dependance (avant
settings_widgets, qui reexporte _qfont)."""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

from app_style import get_button_radius, get_input_radius
from settings_store import M


def _qfont(size: int, weight: int = 400, mono: bool = False, tracking: float = 0.0) -> QFont:
    f = QFont("Consolas" if mono else "Segoe UI")
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    if tracking:
        f.setLetterSpacing(QFont.AbsoluteSpacing, tracking)
    return f


# role -> (taille px, graisse, cle de couleur dans M, police mono, espacement des lettres)
TEXT_ROLES: dict[str, tuple[int, int, str, bool, float]] = {
    # --- Lignes de reglage ---
    "row_label": (12, 400, "row_label", False, 0.0),      # libelle d'une ligne (colonne de gauche)
    "inline_label": (11, 400, "row_label", False, 0.0),   # texte colle a un controle : « gras », « Hauteur », « lier les 4 »...
    "choice_label": (10, 400, "row_label", False, 0.0),   # « Couleur application » / « Couleur systeme »
    "mini_label": (9, 400, "row_label", False, 0.0),      # « app » / « sys », « niveau de lissage »
    "row_note": (10, 400, "row_note", False, 0.0),        # note sous le libelle d'une ligne
    # --- Notes et textes d'information ---
    "note": (10, 400, "group_note", False, 0.0),          # note d'une section, sous-libelle
    "note_mono": (10, 400, "group_note", True, 0.0),      # chemin de fichier
    "note_mono_bold": (10, 600, "group_note", True, 0.0), # numero d'etat
    "placeholder": (12, 400, "group_note", False, 0.0),   # page vide (« Aucun reglage... »)
    # --- Valeurs ---
    "value": (11, 400, "value_fg", False, 0.0),           # nom d'icone, de logiciel, de preset
    "card_title": (11, 600, "value_fg", False, 0.0),      # titre d'une carte (style de toggle, position...)
    "value_muted": (11, 400, "value_muted", False, 0.0),  # valeur secondaire, apercu de police
    "value_muted_mono": (11, 400, "value_muted", True, 0.0),
    "value_mono": (11, 400, "value_text", True, 0.0),     # valeur numerique du selecteur de couleur
    "unit": (9, 400, "unit", True, 0.0),                  # unite apres une valeur (px, %...)
    "unit_large": (11, 400, "unit", True, 0.0),           # « 1/ » du slider de ratio
    "dash": (10, 400, "dash", True, 0.0),                 # tiret de cellule vide
    # --- Etiquettes ---
    "tag": (9, 600, "label_dim", False, 0.7),             # etiquette en capitales (« PRESET »...)
    "tag_accent": (9, 600, "toggle_on_fg", False, 0.7),   # etiquette en capitales mise en avant
    "side_letter": (9, 600, "label_dim", False, 0.5),     # lettre d'un cote ou d'un coin (H, B, G, D...)
    "hex_tag": (9, 400, "label_dim", True, 0.0),          # « HEX »
    "edge_hint": (9, 400, "edge_hint", True, 0.0),        # libelle au centre du schema des bordures
    "table_head_mono": (10, 400, "table_head_fg", True, 0.0),
    # --- Fenetre ---
    "window_title": (11, 400, "title_fg", False, 0.0),
}


def _text_font(role: str) -> QFont:
    size, weight, _color, mono, tracking = TEXT_ROLES[role]
    return _qfont(size, weight, mono=mono, tracking=tracking)


def _text_color(role: str) -> str:
    return M[TEXT_ROLES[role][2]]


def _set_text_role(label: QWidget, role: str, color: str | None = None) -> QWidget:
    """Applique police + couleur du role. `color` remplace la couleur du role
    (cas dynamique, ex. libelle grise quand son toggle est coupe)."""
    label.setFont(_text_font(role))
    label.setStyleSheet(f"color: {color or _text_color(role)}; background: transparent;")
    label.setProperty("textRole", role)
    return label


def _text_label(text: str, role: str, parent: QWidget | None = None) -> QLabel:
    return _set_text_role(QLabel(text, parent), role)


def _refresh_text_roles(root: QWidget) -> None:
    """Reapplique les roles a tous les textes de `root` (apres un changement
    de M ou de TEXT_ROLES)."""
    for label in root.findChildren(QLabel):
        role = label.property("textRole")
        if role in TEXT_ROLES:
            _set_text_role(label, role)


# ==========================================================================
# Arrondis communs : zones de saisie (Geometrie > Zones de saisie > Coins
# arrondis) et boutons (Geometrie > Boutons > Coins arrondis). Chaque widget
# concerne (boite de valeur de slider, menu deroulant, boite hex, bouton...)
# s'INSCRIT ici a sa creation, avec son genre, puis suit le reglage tout
# seul : plus aucune liste de champs a tenir a jour a la main.
# ==========================================================================
import weakref

# Valeurs de depart : celles de l'appli (app_style) ; la fenetre de reglages
# les repose a son ouverture puis en direct (voir SettingsWindow).
_RADII = {"input": get_input_radius(), "button": get_button_radius()}
_REGISTERED: dict[str, "weakref.WeakSet[QWidget]"] = {kind: weakref.WeakSet() for kind in _RADII}


def _radius_of(kind: str) -> int:
    return _RADII[kind]


def _register_radius(widget: QWidget, kind: str) -> int:
    """Inscrit `widget` (qui doit avoir une methode setRadius) et rend le rayon
    courant de son genre, a utiliser comme rayon initial."""
    _REGISTERED[kind].add(widget)
    return _RADII[kind]


def _set_radius_of(kind: str, radius: int) -> None:
    radius = max(0, int(radius))
    if radius == _RADII[kind]:
        # Chaque widget inscrit a deja ce rayon (pris a sa creation) : le
        # reappliquer re-stylerait des centaines de champs pour rien.
        return
    _RADII[kind] = radius
    for widget in list(_REGISTERED[kind]):
        try:
            widget.setRadius(radius)
        except RuntimeError:   # objet Qt deja detruit (fenetre fermee)
            _REGISTERED[kind].discard(widget)


def _input_radius() -> int:
    return _radius_of("input")


def _register_input(widget: QWidget) -> int:
    return _register_radius(widget, "input")


def _set_input_radius(radius: int) -> None:
    _set_radius_of("input", radius)


def _set_button_radius(radius: int) -> None:
    _set_radius_of("button", radius)
