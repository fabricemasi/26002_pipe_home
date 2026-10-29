"""Styles de la fenetre de reglages, en UN SEUL endroit.

Chaque texte de la fenetre porte un ROLE (libelle de ligne, texte colle a
un controle, note...) plutot qu'une police et une couleur posees a la main :
changer l'apparence d'un role ici la change PARTOUT ou il est utilise.
Pour un nouveau texte, choisir le role existant qui correspond a son usage
(voir TEXT_ROLES) ; n'en creer un nouveau que pour un usage reellement
nouveau.

Vient juste apres settings_store dans l'ordre de dependance (avant
settings_widgets, qui reexporte _qfont)."""
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

from fm_theme.style import get_button_radius, get_input_radius
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
    "tag_accent": (9, 600, "toggle_on_fg", False, 0.7),
    "width_badge": (9, 600, "accent_fg", True, 0.0),      # encart « N px » pendant un redimensionnement   # etiquette en capitales mise en avant
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
    (cas dynamique, ex. libelle grise quand son toggle est coupe). Dans une cellule / un tableau
    qui a sa propre police (« Override settings », `_text_look`), celle-ci passe par-dessus."""
    font, text_color = _text_font(role), color or _text_color(role)
    look = text_look_of(label)
    if look:
        font = text_look_font(font, look)
        if color is None and look.get("color"):
            text_color = look["color"]
    label.setFont(font)
    label.setStyleSheet(f"color: {text_color}; background: transparent;")
    label.setProperty("textRole", role)
    return label


def text_look_of(widget: QWidget) -> dict | None:
    """Police propre la plus proche (`_text_look` d'une cellule ou d'un tableau, voir
    settings_layout.apply_part_looks) au-dessus de `widget`."""
    node = widget.parentWidget()
    while node is not None:
        look = getattr(node, "_text_look", None)
        if look:
            return look
        if getattr(node, "_text_look_barrier", False):    # entete d'un tableau : pas la police du tableau
            return None
        node = node.parentWidget()
    return None


def text_look_font(font: QFont, look: dict) -> QFont:
    """`font` avec seulement ce que `look` change (police, gras, italique, hauteur en px, lissage)."""
    out = QFont(font)
    if look.get("family"):
        out.setFamily(look["family"])
    if "bold" in look:
        out.setWeight(QFont.DemiBold if look["bold"] else QFont.Normal)
    if "italic" in look:
        out.setItalic(bool(look["italic"]))
    if look.get("size"):
        out.setPixelSize(max(4, int(look["size"])))
    if look.get("smoothing") == "none":
        out.setStyleStrategy(QFont.NoAntialias)
    elif look.get("smoothing") == "previous":
        out.setHintingPreference(QFont.PreferDefaultHinting)
    return out


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


def apply_input_look(values: dict) -> None:
    """Reglages > Zone de saisie : rayon, hauteur, couleur, bordures de TOUTES les zones de saisie inscrites (menus
    deroulants, champs texte, boites de valeur des curseurs...) — rejoue leur habillage."""
    import settings_store as store
    store.set_input_look(values)
    radius = values.get("input_corner_radius")
    if radius is not None:
        top_left = radius.get("top_left", 0) if isinstance(radius, dict) else radius
        try:
            _RADII["input"] = max(0, int(top_left))
        except (TypeError, ValueError):
            pass
    # Rien n'a change pour les zones de saisie (ce qui est le cas de presque tout apercu en direct : curseur d'une
    # autre section...) : ne rien repeindre. Rejouer l'habillage de ~1000 zones de saisie coutait ~1 s PAR cran
    # d'un curseur, sur n'importe quel reglage.
    global _LAST_INPUT_SIG
    signature = repr((sorted((k, repr(v)) for k, v in store.INPUT_LOOK.items() if k != "colors"),
                      sorted((store.INPUT_LOOK.get("colors") or {}).items()), _RADII["input"]))
    if signature == _LAST_INPUT_SIG:
        return
    _LAST_INPUT_SIG = signature
    visible = []
    hidden = []
    for widget in list(_REGISTERED["input"]):
        try:
            (visible if widget.isVisible() else hidden).append(widget)
        except RuntimeError:                              # objet Qt deja detruit (fenetre fermee)
            _REGISTERED["input"].discard(widget)
    for widget in visible:                                # ce qu'on voit : tout de suite
        _restyle_input(widget)
    _PENDING_INPUTS[:] = hidden                           # le reste : par petits paquets, sans figer l'interface
    if hidden and not _PENDING_TIMER:
        _PENDING_TIMER.append(True)
        QTimer.singleShot(20, _restyle_pending_inputs)


_LAST_INPUT_SIG = None
_PENDING_INPUTS: list = []
_PENDING_TIMER: list = []


def _restyle_input(widget) -> None:
    import settings_store as store
    try:
        base = getattr(widget, "_default_height", None)
        if base is None:
            # Hauteur NATURELLE, jamais celle du moment : une section preparee en fond (cachee, mise en page tassee)
            # donnait ~17 px a un curseur dont la case de valeur en fait 25 — case coupee en bas (signale).
            if 0 < widget.minimumHeight() == widget.maximumHeight():
                base = widget.minimumHeight()            # hauteur fixee par son createur : gardee
            else:
                base = widget.sizeHint().height()
                if widget.isVisible():
                    base = max(base, widget.height())
            widget._default_height = base
        widget.setRadius(_RADII["input"])                 # rejoue aussi son habillage
        height = store.input_height() or base
        box = getattr(widget, "box", None)                # curseur : jamais plus bas que sa case de valeur
        if box is not None:
            height = max(height, box.height())
        widget.setFixedHeight(height)
    except RuntimeError:
        _REGISTERED["input"].discard(widget)


def _restyle_pending_inputs() -> None:
    import time
    # Paquet borne en TEMPS (6 ms), pas en nombre : 40 zones de saisie prenaient ~40 ms d'un coup, toutes les
    # 20 ms, pendant plus d'une seconde — l'interface (curseur tire, toggle) hachait.
    end = time.perf_counter() + 0.006
    while _PENDING_INPUTS and time.perf_counter() < end:
        _restyle_input(_PENDING_INPUTS.pop())
    if _PENDING_INPUTS:
        QTimer.singleShot(20, _restyle_pending_inputs)
    else:
        _PENDING_TIMER.clear()


def _register_input(widget: QWidget) -> int:
    return _register_radius(widget, "input")


def _set_input_radius(radius: int) -> None:
    _set_radius_of("input", radius)


def _set_button_radius(radius: int) -> None:
    _set_radius_of("button", radius)
