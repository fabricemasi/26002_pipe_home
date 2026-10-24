"""Menus contextuels : habillage commun (Reglages > Menu contextuel, cles `ctx_menu_*`), lignes
alignees en colonnes, personnalisation a la volee retenue par menu.

- Tout menu contextuel est un `Menu` (ou passe par `hook_menu`). Juste avant son affichage
  (`aboutToShow` : Qt n'a pas encore calcule sa taille) il recoit l'habillage des reglages, la
  disposition retenue pour CE menu (ordre, separateurs, libelles, icones) et ses lignes a controles
  (`menu_row` : texte + curseur, liste, champ...) sont alignees en colonnes : icone | texte |
  controle, le texte au meme x que celui des lignes simples, les controles a la meme largeur.
  Ses sous-menus sont accroches au passage. Aucun filtre d'evenements global (rien ne coute aux
  animations) : seuls les menus ouverts ont un filtre, pour la personnalisation.
- Personnalisation (Reglages > Menu contextuel > Menu > « Personnalisation ») : TIRER un element le
  deplace (il suit le curseur, son ancienne place reste a 25 %, les emplacements s'allument a
  l'approche, le plus proche en surbrillance : `settings_layout._ReorderOverlay`, comme les lignes des
  tableaux) ; CLIC DROIT sur un element = separateur au-dessus / en dessous, libelle (titre de
  section, renomme sur place), icone, supprimer, reinitialiser le menu.
- Disposition retenue PAR MENU (`menu_key` : le widget qui l'ouvre, + titre pour un sous-menu),
  fusionnee d'une variante a l'autre du meme menu (un element absent garde sa place) ; un separateur
  ou un libelle n'apparait que si un element qui le suit (jusqu'au suivant) est present.
- Couche reglages : aucune dependance au code propre a l'appli. L'appli fournit (`install`) les
  reglages appliques, la lecture / l'ecriture des dispositions, le traducteur de polices et les
  dossiers d'icones.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QFontMetrics, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMenu, QProxyStyle, QStyle, QWidget,
    QWidgetAction,
)

from app_style import font as app_font, resolve_color_ref
from settings_store import DEFAULT_SETTINGS

_SIDES = ("top", "right", "bottom", "left")
_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
ICON_EXTENSIONS = (".png", ".svg", ".jpg", ".jpeg", ".ico", ".bmp", ".webp")
# Decalage du texte des lignes simples par Qt (feuille de style) : taille des icones + 4 px des qu'une
# ligne a une icone, 14 px fixes quand le menu n'a que des cases a cocher, le plus grand des deux sinon.
# Mesure au pixel, verifie par tests/test_context_menu.py.
_ICON_TEXT_GAP = 4
_CHECK_COLUMN = 14
_DRAG_START = 6          # px avant qu'un appui devienne un deplacement

_STATE: dict = {
    "values": None,          # () -> reglages appliques (dict)
    "load": None,            # () -> {cle de menu: disposition}
    "save": None,            # (dispositions) -> None
    "family": None,          # (libelle, taille, graisse) -> famille reelle (roles de police de l'appli)
    "icon_dir": None,        # dossier ou copier les icones choisies hors des dossiers proposes
    "icon_sources": (),      # dossiers dont les images sont proposees dans le sous-menu « Icone »
}
_LAYOUTS_CACHE: dict = {}


def install(values=None, load_layouts=None, save_layouts=None, font_family=None, icon_dir=None,
            icon_sources=()) -> None:
    """Branche les menus sur l'appli (voir le texte du module). Sans appel : valeurs par defaut,
    dispositions gardees en memoire seulement."""
    _STATE.update(values=values, load=load_layouts, save=save_layouts, family=font_family,
                  icon_dir=Path(icon_dir) if icon_dir else None, icon_sources=tuple(Path(p) for p in icon_sources))


def _values() -> dict:
    merged = dict(DEFAULT_SETTINGS)
    provider = _STATE["values"]
    if provider is not None:
        merged.update(provider() or {})
    return merged


def _layouts() -> dict:
    loader = _STATE["load"]
    data = loader() if loader is not None else _LAYOUTS_CACHE
    return data if isinstance(data, dict) else {}


def _save_layouts(layouts: dict) -> None:
    saver = _STATE["save"]
    if saver is not None:
        saver(layouts)
    else:
        _LAYOUTS_CACHE.clear()
        _LAYOUTS_CACHE.update(layouts)


# ==========================================================================
# Habillage (lu dans les reglages appliques)
# ==========================================================================

def _int(value, default=0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _sides(value, default=0) -> dict:
    if isinstance(value, dict):
        return {s: _int(value.get(s, default), default) for s in _SIDES}
    return {s: _int(value, default) for s in _SIDES}


def _corners(value) -> dict:
    if isinstance(value, dict):
        return {c: _int(value.get(c, 0)) for c in _CORNERS}
    return {c: _int(value) for c in _CORNERS}


def _font(v: dict, pre: str, default_size: int):
    size = _int(v.get(f"{pre}_font_size"), default_size) or default_size
    weight = 700 if v.get(f"{pre}_font_bold") else 400
    smooth = v.get(f"{pre}_font_smoothing", "current") if v.get(f"{pre}_font_smoothing_enabled") else "current"
    label = (v.get(f"{pre}_font_family") or "").strip()
    family = None
    if label and label != "Systeme":
        resolver = _STATE["family"]
        family = resolver(label, size, weight) if resolver is not None else label
    return app_font(size, weight, family=family, smoothing=smooth, italic=bool(v.get(f"{pre}_font_italic")))


# Portees d'habillage (ex. « board » : Reglages > MRO > Menus contextuels) : un menu dont la cle commence par
# « <portee>: » prend, pour chaque cle dont l'interrupteur d'override est allume, la valeur propre a la portee.
SCOPES: dict[str, tuple[str, dict]] = {}


def register_scope(scope: str, value_prefix: str, toggles: dict) -> None:
    """`toggles` : {cle des menus (ctx_menu_*): cle de l'interrupteur d'override}."""
    SCOPES[scope] = (value_prefix, dict(toggles))


def menu_scope(menu) -> str | None:
    key = menu_key(menu)
    scope = key.split(":", 1)[0] if ":" in key else None
    return scope if scope in SCOPES else None


def scoped_values(values: dict, scope: str | None) -> dict:
    if scope not in SCOPES:
        return values
    prefix, toggles = SCOPES[scope]
    merged = dict(values)
    for key, toggle in toggles.items():
        if values.get(toggle):
            merged[key] = values.get(prefix + key, values.get(key))
    return merged


def menu_look(scope: str | None = None) -> dict:
    """Habillage des menus : Reglages > Menu contextuel (cles `ctx_menu_*`), et les overrides d'une portee."""
    v = scoped_values(_values(), scope)

    def color(key, fallback):
        return resolve_color_ref(v.get(key), fallback)

    border, border_colors = _border(v, "ctx_menu_border", "#2c3034")
    if _single_border_color(v, scope):
        one = color("ctx_menu_border_color", "#2c3034")
        border_colors = {s: one for s in _SIDES}
    hover_border, hover_border_colors = _border(v, "ctx_menu_hover_border", "#5f9bd0")
    return {
        "bg": color("ctx_menu_bg", "#202326"),
        "border": border,
        "border_colors": border_colors,
        "radius": _corners(v.get("ctx_menu_border_radius")),
        "padding": _sides(v.get("ctx_menu_padding"), 4),
        "font": _font(v, "ctx_menu", 11),
        "text": color("ctx_menu_font_color", "#d6d9dc"),
        "item_padding": _sides(v.get("ctx_menu_item_padding"), 5),
        "hover": color("ctx_menu_hover_color", "#3f6f9f"),
        "hover_text": color("ctx_menu_hover_text_color", "#eef2f5"),
        "hover_radius": _corners(v.get("ctx_menu_hover_radius")),
        "hover_border": hover_border,
        "hover_border_colors": hover_border_colors,
        "hover_margin": _sides(v.get("ctx_menu_hover_margin"), 0),
        "disabled": color("ctx_menu_disabled_color", "#7d858b"),
        "icon_size": max(8, _int(v.get("ctx_menu_icon_size"), 16)),
        "gap": _int(v.get("ctx_menu_control_gap"), 16),
        "slider_width": max(40, _int(v.get("ctx_menu_slider_width"), 140)),
        "label_font": _font(v, "ctx_menu_label", 10),
        "label_text": color("ctx_menu_label_font_color", "#7d858b"),
        "label_bg": color("ctx_menu_label_bg", "#00000000"),
        "label_padding": _sides(v.get("ctx_menu_label_padding"), 4),
        "label_caps": bool(v.get("ctx_menu_label_uppercase", True)),
        "sep_color": color("ctx_menu_sep_color", "#2c3034"),
        "sep_thickness": _int(v.get("ctx_menu_sep_thickness"), 1),
        "sep_padding": _sides(v.get("ctx_menu_sep_padding"), 4),
        "editable": bool(v.get("ctx_menu_editable", True)),
        "shadow": _shadow(v),
    }


def _single_border_color(values: dict, scope: str | None) -> bool:
    """Portee dont SEULE la « Couleur des bordures » est en override (pas la ligne Bordures) : cette couleur
    vaut pour les 4 cotes (dans l'appli, elle est deja recopiee sur chaque cote par la fenetre de reglages)."""
    if scope not in SCOPES:
        return False
    toggles = SCOPES[scope][1]
    return bool(values.get(toggles.get("ctx_menu_border_color", ""))) and         not values.get(toggles.get("ctx_menu_border", ""))


def _border(v: dict, prefix: str, default_color: str) -> tuple:
    """Ligne « Bordures » (`<prefix>_enabled` par cote, `<prefix>` couleurs, `<prefix>_thickness`) :
    ({cote: epaisseur, 0 si eteint}, {cote: couleur})."""
    raw, on = v.get(prefix), v.get(f"{prefix}_enabled")
    on = {s: bool(on.get(s)) if isinstance(on, dict) else bool(on) for s in _SIDES}
    thick = _int(v.get(f"{prefix}_thickness"), 1)
    colors = {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, default_color) for s in _SIDES}
    return {s: thick if on[s] else 0 for s in _SIDES}, colors


def _line_box(lk: dict) -> dict:
    """Retrait du TEXTE d'une ligne simple par rapport a sa place dans le menu, par cote : marge du survol
    + bordure du survol (toujours reservee, transparente hors survol : le texte ne bouge pas au survol)
    + padding des lignes. Les lignes a controles et les libelles prennent les memes retraits."""
    m, b, ip = lk["hover_margin"], lk["hover_border"], lk["item_padding"]
    return {s: m[s] + b[s] + ip[s] for s in _SIDES}


def _shadow(v: dict):
    """Ombre des menus (ligne « Ombres », settings_widgets.shadow_look ; None = aucune)."""
    from settings_widgets import shadow_look      # differe : settings_widgets importe ce module
    return shadow_look(v, "ctx_menu_shadow", lambda value: resolve_color_ref(value, "#8c000000"))


def shadow_margin(lk: dict) -> int:
    """Marge transparente autour du menu, ou son ombre est peinte (0 sans ombre)."""
    return lk["shadow"]["size"] if lk["shadow"] else 0


def _qss(lk: dict) -> str:
    b, bc, r, p, ip, sp = (lk["border"], lk["border_colors"], lk["radius"], lk["padding"], lk["item_padding"],
                           lk["sep_padding"])
    borders = " ".join(f"border-{s}: {b[s]}px solid {bc[s]};" for s in _SIDES)
    radius = " ".join(f"border-{c.replace('_', '-')}-radius: {r[c]}px;" for c in _CORNERS)
    hm, hb, hc, hr = lk["hover_margin"], lk["hover_border"], lk["hover_border_colors"], lk["hover_radius"]
    # Survol : bordure TOUJOURS reservee (transparente hors survol) pour que le texte ne bouge pas.
    item_border = " ".join(f"border-{s}: {hb[s]}px solid transparent;" for s in _SIDES)
    hover_border = " ".join(f"border-{s}-color: {hc[s]};" for s in _SIDES if hb[s])
    hover_radius = " ".join(f"border-{c.replace('_', '-')}-radius: {hr[c]}px;" for c in _CORNERS)
    return (
        f"QMenu {{ margin: {shadow_margin(lk)}px; background: {lk['bg']}; {borders} {radius} "
        f"padding: {p['top']}px {p['right']}px {p['bottom']}px {p['left']}px; }}"
        f"QMenu::item {{ padding: {ip['top']}px {ip['right']}px {ip['bottom']}px {ip['left']}px; "
        f"margin: {hm['top']}px {hm['right']}px {hm['bottom']}px {hm['left']}px; "
        f"color: {lk['text']}; background: transparent; {item_border} {hover_radius} }}"
        f"QMenu::item:selected {{ background: {lk['hover']}; color: {lk['hover_text']}; {hover_border} }}"
        f"QMenu::item:disabled {{ color: {lk['disabled']}; background: transparent; }}"
        f"QMenu::separator {{ height: {lk['sep_thickness']}px; background: {lk['sep_color']}; "
        f"margin: {sp['top']}px {sp['right']}px {sp['bottom']}px {sp['left']}px; }}"
    )


class _MenuPainter(QObject):
    """Ombre du menu (peinte dans sa marge transparente, avant son fond) ; a l'affichage, le menu est
    decale de cette marge pour que son PANNEAU arrive la ou Qt l'a place (au curseur, contre le menu
    parent)."""

    def __init__(self, menu: QMenu):
        super().__init__(menu)
        self.menu = menu

    def eventFilter(self, obj, event):
        kind = event.type()
        lk = getattr(self.menu, "_ctx_look", None)
        if lk is None:
            return False
        margin = shadow_margin(lk)
        if kind == QEvent.Paint and margin:
            from settings_widgets import paint_shadow
            from PySide6.QtGui import QPainter
            painter = QPainter(self.menu)
            panel = self.menu.rect().adjusted(margin, margin, -margin, -margin)
            paint_shadow(painter, panel, dict(lk["radius"]), lk["shadow"])
            painter.end()
        elif kind == QEvent.Show and margin:
            self.menu.move(self.menu.pos() - QPoint(margin, margin))
        return False


class _MenuStyle(QProxyStyle):
    """Taille des icones des menus (Reglages > Menu contextuel > « Taille des icones ») : la feuille
    de style de Qt ne la regle pas pour un QMenu."""

    def __init__(self, icon_size: int):
        super().__init__()
        self.icon_size = icon_size

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PM_SmallIconSize:
            return self.icon_size
        return super().pixelMetric(metric, option, widget)


# ==========================================================================
# Lignes a controles et libelles
# ==========================================================================

class _MenuRow(QWidget):
    """Ligne de menu : [case d'icone] texte [controle]. Alignee par `_align` : texte au meme x que
    celui des lignes simples, controles en colonne, tous a la meme largeur."""

    def __init__(self, text: str, control: QWidget | None):
        super().__init__()
        self.text = text
        self.control = control
        self.setAttribute(Qt.WA_StyledBackground, False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)
        self.label = QLabel(text, self)      # enfant avant la case d'icone : 1er QLabel de la ligne
        self.icon = QLabel(self)
        self.icon._no_object = True          # objets libres (Ctrl+Maj) : ni la case d'icone ni l'ecart
        self.icon.setFixedWidth(0)
        self.icon.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.icon)
        layout.addWidget(self.label)
        self.gap = QWidget()
        self.gap._no_object = True
        self.gap.setFixedWidth(10)
        layout.addWidget(self.gap)
        if control is not None:
            layout.addWidget(control)
        layout.addStretch(1)
        self._icon_path = None

    def set_icon(self, path: str | None):
        self._icon_path = path or None


class _SectionRow(QWidget):
    """Libelle de section (titre pose a la volee dans un menu) : renomme sur place (`start_edit`)."""

    def __init__(self, text: str):
        super().__init__()
        self.text = text
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("CtxMenuSection")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.label = QLabel(text)
        layout.addWidget(self.label, 1)
        self.edit: QLineEdit | None = None
        self.on_commit = None

    def start_edit(self, on_commit):
        """Zone de saisie posee sur le libelle : Entree / clic ailleurs = valide, Echap = annule."""
        self.on_commit = on_commit
        edit = QLineEdit(self.text, self)
        edit.setFont(self.label.font())
        edit.setFrame(False)
        edit.setStyleSheet(self.label.styleSheet() + "background: rgba(255,255,255,0.08);")
        edit.setGeometry(self.label.geometry())
        edit.selectAll()
        edit.installEventFilter(self)
        edit.editingFinished.connect(lambda: self._finish(True))
        self.edit = edit
        edit.show()
        edit.setFocus(Qt.OtherFocusReason)

    def _finish(self, keep: bool):
        edit, self.edit = self.edit, None
        if edit is None:
            return
        text = edit.text().strip()
        edit.hide()
        edit.deleteLater()
        if keep and self.on_commit is not None:
            self.on_commit(text)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._finish(False)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._finish(True)
                return True
        return False


def menu_row(menu: QMenu, text: str, control: QWidget | None = None) -> QWidgetAction:
    """Ajoute a `menu` une ligne « texte + controle » (curseur, liste, champ...) : ce que les menus
    contextuels doivent utiliser pour tout ce qui n'est pas une ligne simple (alignement en colonnes)."""
    action = QWidgetAction(menu)
    action.setDefaultWidget(_MenuRow(text, control))
    menu.addAction(action)
    return action


def _section_action(menu: QMenu, text: str) -> QWidgetAction:
    action = QWidgetAction(menu)
    action.setDefaultWidget(_SectionRow(text))
    action._ctx_section = text
    return action


# ==========================================================================
# Identite des menus et de leurs elements
# ==========================================================================

def _strip(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&").strip()


def item_id(action) -> str | None:
    """Identifiant d'un element (stable d'une ouverture a l'autre) : son texte (« row: » + texte pour
    une ligne a controle, « menu: » + titre pour un sous-menu). None : separateur, libelle, inconnu."""
    if isinstance(action, QWidgetAction):
        widget = action.defaultWidget()
        if isinstance(widget, _MenuRow):
            return "row:" + widget.text
        return None
    if action.isSeparator():
        return None
    text = _strip(action.text())
    if not text:
        return None
    return ("menu:" + text) if action.menu() is not None else text


def menu_key(menu: QMenu) -> str:
    """Cle de la disposition d'un menu : posee a l'accroche (`hook_menu`)."""
    key = menu.property("ctxMenuKey")
    return key if isinstance(key, str) and key else "menu"


def _derive_key(menu: QMenu) -> str:
    parent = menu.parent()
    if isinstance(parent, QMenu):
        return f"{menu_key(parent)}>{_strip(menu.title())}"
    return type(parent).__name__ if parent is not None else "menu"


def _entries(menu: QMenu) -> list:
    """Elements affiches, dans l'ordre : ("item", id, action) | ("sep", None, action) |
    ("label", texte, action) | ("other", None, action)."""
    out = []
    for action in menu.actions():
        if not action.isVisible():
            continue
        section = getattr(action, "_ctx_section", None)
        if section is not None:
            out.append(("label", section, action))
        elif action.isSeparator():
            out.append(("sep", None, action))
        else:
            iid = item_id(action)
            out.append(("item", iid, action) if iid else ("other", None, action))
    return out


def _snapshot(entries: list) -> list:
    order = []
    for kind, value, _action in entries:
        if kind == "item":
            order.append({"item": value})
        elif kind == "sep":
            order.append({"sep": True})
        elif kind == "label":
            order.append({"label": value})
    return order


def _merge(new: list, old: list) -> list:
    """Disposition `new` (ce qui est affiche) + les elements de `old` absents de cet affichage, chacun
    replace juste apres l'element qui le precedait (une variante du menu ne perd pas les autres)."""
    out = list(new)
    shown = {e["item"] for e in new if "item" in e}
    anchor = -1
    for entry in old:
        if "item" not in entry:
            continue
        if entry["item"] in shown:
            anchor = next(i for i, e in enumerate(out) if e.get("item") == entry["item"])
        else:
            anchor += 1
            out.insert(anchor, dict(entry))
            shown.add(entry["item"])
    return out


def _plan(entries: list, order: list) -> list:
    """Sequence a afficher : ("action", QAction) | ("sep",) | ("label", texte) d'apres la disposition
    retenue ; les elements nouveaux (absents de `order`) restent apres leur predecesseur d'origine."""
    present = {}
    for kind, value, action in entries:
        if kind == "item" and value not in present:
            present[value] = action
    seq, used = [], set()
    # Un separateur / libelle n'est garde que si un element present le suit avant le suivant.
    for k, entry in enumerate(order):
        if "item" in entry:
            action = present.get(entry["item"])
            if action is not None and entry["item"] not in used:
                seq.append(("action", action))
                used.add(entry["item"])
            continue
        follow = []
        for nxt in order[k + 1:]:
            if "item" not in nxt:
                break
            follow.append(nxt["item"])
        if not any(i in present for i in follow):
            continue
        seq.append(("sep",) if "sep" in entry else ("label", entry["label"]))
    # Nouveaux elements (et lignes inconnues) : apres leur predecesseur d'origine deja place.
    placed = {id(s[1]) for s in seq if s[0] == "action"}
    for index, (kind, value, action) in enumerate(entries):
        if kind not in ("item", "other") or id(action) in placed:
            continue
        position = 0
        for prev_kind, _v, prev in reversed(entries[:index]):
            if id(prev) in placed:
                position = next(i for i, s in enumerate(seq) if s[0] == "action" and s[1] is prev) + 1
                break
        seq.insert(position, ("action", action))
        placed.add(id(action))
    # Pas de separateur au debut / a la fin ni deux a la suite ; pas de libelle en dernier.
    cleaned = []
    for step in seq:
        if step[0] == "sep" and (not cleaned or cleaned[-1][0] in ("sep", "label")):
            continue
        cleaned.append(step)
    while cleaned and cleaned[-1][0] in ("sep", "label"):
        cleaned.pop()
    return cleaned


# ==========================================================================
# Preparation d'un menu (avant chaque affichage)
# ==========================================================================

def _make_translucent(menu: QMenu) -> None:
    """Fenetre transparente sans l'ombre de Windows (un rectangle a angles droits qui debordait des coins
    arrondis) : fond, coins et ombre sont peints par le menu. A poser AVANT que Qt cree la fenetre (elle
    existe deja a `aboutToShow` : posee alors, la transparence ne prenait pas et le fond sortait NOIR,
    « cadre noir » signale) -> des l'accroche. setWindowFlags : setWindowFlag est sans effet sur
    NoDropShadowWindowHint en PySide."""
    if not menu.testAttribute(Qt.WA_TranslucentBackground):
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
    wanted = Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
    if (menu.windowFlags() & wanted) != wanted:
        menu.setWindowFlags(menu.windowFlags() | wanted)


def hook_menu(menu: QMenu, key: str | None = None) -> QMenu:
    """Accroche `menu` : habillage, alignement et disposition retenue a chaque affichage."""
    if getattr(menu, "_ctx_hooked", False):
        return menu
    menu._ctx_hooked = True
    _make_translucent(menu)
    menu.setProperty("ctxMenuKey", key or _derive_key(menu))
    menu.aboutToShow.connect(lambda m=menu: prepare_menu(m))
    return menu


class Menu(QMenu):
    """QMenu des menus contextuels de l'appli (voir le texte du module)."""

    def __init__(self, *args, key: str | None = None, editable: bool = True):
        super().__init__(*args)
        self.setProperty("ctxNoEdit", not editable)
        hook_menu(self, key)


def prepare_menu(menu: QMenu) -> None:
    lk = menu_look(menu_scope(menu))
    layout = _layouts().get(menu_key(menu)) or {}
    if layout.get("order") and not menu.property("ctxNoEdit"):
        _apply_order(menu, layout["order"])
    _apply_icons(menu, layout.get("icons") or {}, lk["icon_size"])
    _apply_look(menu, lk)
    for action in menu.actions():
        sub = action.menu()
        if isinstance(sub, QMenu):
            if sub.parent() is None:
                sub.setParent(menu, sub.windowFlags())
            if sub.property("ctxNoEdit") is None and menu.property("ctxNoEdit"):
                sub.setProperty("ctxNoEdit", True)
            hook_menu(sub)
    if lk["editable"] and not menu.property("ctxNoEdit"):
        _editor(menu)
    _apply_objects(menu, layout)


# ==========================================================================
# Objets des lignes a controle (demande de l'utilisateur) : comme dans les tableaux (settings_cells) —
# Ctrl+Maj + glisser = deplacer dans sa ligne (+ Q : vertical, + Z : horizontal), Ctrl+Maj+X + glisser
# un bord = redimensionner (aimante aux objets de la ligne sous le curseur), Ctrl+Z ; et style des toggles
# au clic droit. Retenu dans la disposition du menu : `objects` {« row:<texte>|<chemin> »: [x, y, l, h]},
# `toggles` {« row:<texte>|<chemin> »: style}.
# ==========================================================================

class _MenuObjects:
    """Magasin des objets libres d'un menu (protocole de settings_cells : objects, set_object, commit,
    owner_window, snap_rows)."""

    def __init__(self, menu: QMenu):
        self.menu = menu
        self.objects: dict = {}

    def rows(self) -> list:
        return [a.defaultWidget() for a in self.menu.actions()
                if isinstance(a, QWidgetAction) and isinstance(a.defaultWidget(), _MenuRow)]

    def row(self, row_key: str):
        return next((r for r in self.rows() if "row:" + r.text == row_key), None)

    def set_object(self, key: str, rec) -> None:
        import settings_cells
        row_key, _sep, path = key.partition("|")
        settings_cells.set_host_object(self, self.row(row_key), key, path, rec)

    def owner_window(self):
        return self.menu

    def snap_rows(self) -> list:
        return [r for r in self.rows() if r.isVisible()]

    def commit(self) -> None:
        layouts = dict(_layouts())
        key = menu_key(self.menu)
        layout = dict(layouts.get(key) or {})
        objects = {k: list(v) for k, v in self.objects.items() if any(v)}
        if objects:
            layout["objects"] = objects
        else:
            layout.pop("objects", None)
        layouts[key] = layout
        _save_layouts(layouts)


def _apply_objects(menu: QMenu, layout: dict) -> None:
    """Branche les gestes sur les lignes a controle et rejoue places / tailles / styles de toggle retenus."""
    import settings_cells
    _install_toggle_listener()
    store = getattr(menu, "_ctx_objects", None)
    if store is None:
        store = menu._ctx_objects = _MenuObjects(menu)
    rows = store.rows()
    for row in rows:
        row._objects_host = lambda r=row, s=store: (s, "row:" + r.text)
        settings_cells.watch_object_gestures(row)
    # Styles des toggles AVANT les places : un objet detache garde la taille qu'il a a ce moment.
    for key, style in (layout.get("toggles") or {}).items():
        row_key, _sep, path = key.partition("|")
        row = store.row(row_key)
        toggle = settings_cells._resolve_object(row, path) if row is not None and path else None
        if toggle is not None and hasattr(toggle, "setStyleKey"):
            toggle.setStyleKey(style)
    saved = layout.get("objects") or {}
    for key in [k for k in store.objects if k not in saved]:
        store.set_object(key, None)
    for key, rec in saved.items():
        if isinstance(rec, list):
            store.set_object(key, rec)


def _toggle_at(gpos: QPoint):
    """Toggle (style changeable : `setStyleKey`) sous le point global `gpos`, dans une ligne de menu."""
    widget = QApplication.widgetAt(gpos)
    while widget is not None and not isinstance(widget, (_MenuRow, QMenu)):
        if hasattr(widget, "setStyleKey") and hasattr(widget, "chosenStyle"):
            return widget
        widget = widget.parentWidget()
    return None


def _row_and_menu(widget):
    row = widget
    while row is not None and not isinstance(row, _MenuRow):
        row = row.parentWidget()
    menu = row.parentWidget() if row is not None else None
    while menu is not None and not isinstance(menu, QMenu):
        menu = menu.parentWidget()
    return row, menu


def _menu_toggle_listener(toggle, style) -> None:
    """Style choisi au clic droit sur un toggle d'une ligne de menu : retenu dans la disposition du menu."""
    import settings_cells
    row, menu = _row_and_menu(toggle)
    if row is None or menu is None:
        return
    path = settings_cells._object_path(row, toggle)
    if path is None:
        return
    layouts = dict(_layouts())
    key = menu_key(menu)
    layout = dict(layouts.get(key) or {})
    toggles = dict(layout.get("toggles") or {})
    name = f"row:{row.text}|{path}"
    if style:
        toggles[name] = style
    else:
        toggles.pop(name, None)
    if toggles:
        layout["toggles"] = toggles
    else:
        layout.pop("toggles", None)
    layouts[key] = layout
    _save_layouts(layouts)


def _install_toggle_listener() -> None:
    from settings_widgets import TOGGLE_STYLE_LISTENERS
    if _menu_toggle_listener not in TOGGLE_STYLE_LISTENERS:
        TOGGLE_STYLE_LISTENERS.append(_menu_toggle_listener)


def _apply_order(menu: QMenu, order: list) -> None:
    seq = _plan(_entries(menu), order)
    hidden = [a for a in menu.actions() if not a.isVisible()]
    for action in list(menu.actions()):
        menu.removeAction(action)
    for action in hidden:
        menu.addAction(action)
    for step in seq:
        if step[0] == "action":
            menu.addAction(step[1])
        elif step[0] == "sep":
            menu.addSeparator()
        else:
            menu.addAction(_section_action(menu, step[1]))


def _apply_icons(menu: QMenu, icons: dict, icon_size: int) -> None:
    row_icon, plain = False, []
    for action in menu.actions():
        iid = item_id(action)
        if iid is None:
            continue
        path = icons.get(iid)
        path = path if path and Path(path).is_file() else None
        if isinstance(action, QWidgetAction):
            action.defaultWidget().set_icon(path)
            row_icon |= path is not None
            continue
        if not hasattr(action, "_ctx_base_icon"):
            action._ctx_base_icon = action.icon()
        action.setIcon(QIcon(path) if path else action._ctx_base_icon)
        plain.append(action)
    # Une ligne a controle a une icone : Qt doit reserver la case d'icone des lignes simples aussi
    # (sinon leur texte ne serait plus aligne) -> icone transparente sur l'une d'elles.
    shown = [a for a in plain if a.isVisible()]
    if row_icon and shown and all(a.icon().isNull() for a in shown):
        shown[0].setIcon(_blank_icon(icon_size))


def _icon_column(menu: QMenu, lk: dict) -> int:
    """Decalage du texte des lignes simples (case d'icone / de coche ; 0 si le menu n'en a aucune)."""
    icons = checks = False
    for action in menu.actions():
        if not action.isVisible() or isinstance(action, QWidgetAction) or action.isSeparator():
            continue
        icons |= not action.icon().isNull()
        checks |= action.isCheckable()
    return max(lk["icon_size"] + _ICON_TEXT_GAP if icons else 0, _CHECK_COLUMN if checks else 0)


def _blank_icon(size: int) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    return QIcon(pix)


def _apply_look(menu: QMenu, lk: dict) -> None:
    _make_translucent(menu)
    if getattr(menu, "_ctx_painter", None) is None:
        menu._ctx_painter = _MenuPainter(menu)
        menu.installEventFilter(menu._ctx_painter)
    menu._ctx_look = lk
    style = getattr(menu, "_ctx_style", None)
    if style is None or style.icon_size != lk["icon_size"]:
        style = _MenuStyle(lk["icon_size"])
        menu._ctx_style = style
        menu.setStyle(style)
    menu.setStyleSheet(_qss(lk))
    menu.setFont(lk["font"])
    _align(menu, lk)


def _align(menu: QMenu, lk: dict) -> None:
    """Lignes a controles et libelles : texte au x du texte des lignes simples, controles en colonne
    (apres le plus long texte + l'ecart reglé), tous a la meme largeur."""
    ip = _line_box(lk)           # marge + bordure du survol + padding : comme les lignes simples
    icon_col = _icon_column(menu, lk)
    rows, sections = [], []
    for action in menu.actions():
        if not isinstance(action, QWidgetAction):
            continue
        widget = action.defaultWidget()
        if isinstance(widget, _MenuRow):
            rows.append(widget)
        elif isinstance(widget, _SectionRow):
            sections.append(widget)
    metrics = QFontMetrics(lk["font"])
    text_w = max((metrics.horizontalAdvance(r.text) for r in rows), default=0)
    # Controles : meme largeur pour tous (curseurs : rail a la largeur reglee, boite de valeur commune).
    box_w = max((r.control.box.width() for r in rows if hasattr(r.control, "box")), default=0)
    for row in rows:
        control = row.control
        if hasattr(control, "slider") and hasattr(control, "box"):
            control.slider._width = lk["slider_width"]
            control.slider._apply_size()
            control.box.setFixedWidth(box_w)
    widths = [r.control.sizeHint().width() for r in rows if r.control is not None]
    control_w = max(widths, default=0)
    color = f"color: {lk['text']}; background: transparent;"
    for row in rows:
        row.layout().setContentsMargins(ip["left"], ip["top"], ip["right"], ip["bottom"])
        row.icon.setFixedWidth(icon_col)
        if row._icon_path and icon_col:
            row.icon.setPixmap(QIcon(row._icon_path).pixmap(lk["icon_size"], lk["icon_size"]))
        else:
            row.icon.clear()
        row.label.setFont(lk["font"])
        row.label.setStyleSheet(color)
        row.label.setFixedWidth(text_w)
        row.gap.setFixedWidth(lk["gap"] if row.control is not None else 0)
        if row.control is not None and control_w and not hasattr(row.control, "slider"):
            row.control.setFixedWidth(control_w)
    lp = lk["label_padding"]
    for section in sections:
        section.label.setText(section.text.upper() if lk["label_caps"] else section.text)
        section.label.setFont(lk["label_font"])
        section.label.setStyleSheet(f"color: {lk['label_text']}; background: transparent;")
        section.setStyleSheet(f"#CtxMenuSection {{ background: {lk['label_bg']}; }}")
        section.layout().setContentsMargins(ip["left"] + icon_col + lp["left"], lp["top"], lp["right"], lp["bottom"])


# ==========================================================================
# Personnalisation : deplacer, separateurs, libelles, icones
# ==========================================================================

def _store(menu: QMenu, order: list | None = None, icons: dict | None = None, reset: bool = False) -> None:
    layouts = dict(_layouts())
    key = menu_key(menu)
    if reset:
        layouts.pop(key, None)
    else:
        layout = dict(layouts.get(key) or {})
        if order is not None:
            layout["order"] = _merge(order, list(layout.get("order") or []))
        if icons is not None:
            layout["icons"] = {k: v for k, v in icons.items() if v}
        layouts[key] = layout
    _save_layouts(layouts)


def _refresh_open_menu(menu: QMenu) -> None:
    """Rejoue la disposition retenue sur le menu ouvert (Qt le redimensionne)."""
    prepare_menu(menu)
    menu.adjustSize()
    menu.update()


class _Spans:
    """Adaptateur pour `_ReorderOverlay` (axe y) : positions des elements du menu."""

    def __init__(self, menu: QMenu, actions: list):
        rects = [menu.actionGeometry(a) for a in actions]
        self._spans = [(r.top(), r.bottom() + 1) for r in rects]
        self._order = list(range(len(actions)))

    def _column_spans(self):
        return self._spans


class _MenuEditor(QObject):
    """Filtre pose sur un menu ouvert (personnalisation permise) : glisser = deplacer ; clic droit =
    menu d'edition (separateurs, libelles, icone, reinitialiser)."""

    def __init__(self, menu: QMenu):
        super().__init__(menu)
        self.menu = menu
        self._press: QPoint | None = None
        self._source = None
        self._overlay = None
        self._actions: list = []

    def _visible(self) -> list:
        return [a for a in self.menu.actions() if a.isVisible()]

    def _at(self, pos: QPoint):
        for action in self._visible():
            if self.menu.actionGeometry(action).contains(pos):
                return action
        return None

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            pos = self.menu.mapFromGlobal(event.globalPosition().toPoint())
            if event.button() == Qt.RightButton:
                return self._at(pos) is not None
            if event.button() == Qt.LeftButton:
                self._press, self._source = pos, self._at(pos)
            return False
        if kind == QEvent.MouseMove and self._press is not None and event.buttons() & Qt.LeftButton:
            pos = self.menu.mapFromGlobal(event.globalPosition().toPoint())
            if self._overlay is None:
                # Deplacer = Ctrl + glisser (demande de l'utilisateur, pour tout deplacement de l'appli).
                if (self._source is None or not (QApplication.keyboardModifiers() & Qt.ControlModifier)
                        or (pos - self._press).manhattanLength() < _DRAG_START):
                    return False
                self._begin_drag()
            self._overlay.follow(pos.y())
            return True
        if kind == QEvent.MouseButtonRelease:
            pos = self.menu.mapFromGlobal(event.globalPosition().toPoint())
            if event.button() == Qt.RightButton:
                action = self._at(pos)
                if action is None:
                    return False
                gpos = event.globalPosition().toPoint()
                toggle = _toggle_at(gpos)
                if toggle is not None:
                    toggle._ctx_menu_handled = True     # son propre menu ne s'ouvre pas en plus
                QTimer.singleShot(0, lambda a=action, g=gpos, t=toggle: self._edit_menu(a, g, t))
                return True
            self._press = None
            if self._overlay is not None:
                self._end_drag()
                return True
        return False

    # -- deplacement --

    def _begin_drag(self):
        from settings_layout import _ReorderOverlay
        self._actions = self._visible()
        source = self._actions.index(self._source)
        rect = self.menu.actionGeometry(self._source)
        ghost = self.menu.grab(rect)
        spans = _Spans(self.menu, self._actions)
        overlay = _ReorderOverlay(self.menu, spans, source, ghost, 0, self._press.y() - rect.top(), axis="y")
        overlay.veil_color = menu_look(menu_scope(self.menu))["bg"]
        overlay.setGeometry(QRect(rect.left(), 0, rect.width(), self.menu.height()))
        overlay.offset = 0
        self._overlay = overlay
        self.menu.setActiveAction(None)

    def _end_drag(self):
        overlay, self._overlay = self._overlay, None
        target = overlay.target
        source = overlay.source
        overlay.hide()
        overlay.deleteLater()
        if target is None:
            return
        entries = [e for e in _entries(self.menu) if e[2] in self._actions]
        moved = entries.pop(source)
        entries.insert(target - (1 if target > source else 0), moved)
        _store(self.menu, order=_snapshot(entries))
        _refresh_open_menu(self.menu)

    # -- clic droit --

    def _edit_menu(self, action, global_pos: QPoint, toggle=None):
        menu = self.menu
        entries = _entries(menu)
        index = next((i for i, e in enumerate(entries) if e[2] is action), None)
        if index is None:
            return
        kind, value, _a = entries[index]
        edit = Menu(menu, editable=False)
        if toggle is not None:
            # Clic droit sur un toggle d'une ligne : son style d'abord (demande de l'utilisateur).
            from settings_widgets import add_toggle_style_menu
            try:
                add_toggle_style_menu(toggle, edit)
                edit.addSeparator()
            except RuntimeError:
                pass
        add_above = edit.addAction("Ajouter un séparateur au-dessus")
        add_below = edit.addAction("Ajouter un séparateur en dessous")
        remove_sep = edit.addAction("Supprimer le séparateur") if kind == "sep" else None
        edit.addSeparator()
        add_label = edit.addAction("Ajouter un libellé au-dessus…")
        rename_label = edit.addAction("Renommer le libellé…") if kind == "label" else None
        remove_label = edit.addAction("Supprimer le libellé") if kind == "label" else None
        icon_actions = {}
        if kind == "item":
            edit.addSeparator()
            icons = dict((_layouts().get(menu_key(menu)) or {}).get("icons") or {})
            sub = Menu("Icône", edit, editable=False)
            edit.addMenu(sub)
            for path in _icon_choices():
                choice = sub.addAction(QIcon(str(path)), path.stem)
                icon_actions[choice] = str(path)
            if icon_actions:
                sub.addSeparator()
            pick = sub.addAction("Choisir un fichier…")
            icon_actions[pick] = "<pick>"
            if icons.get(value):
                drop = sub.addAction("Retirer l'icône")
                icon_actions[drop] = ""
        edit.addSeparator()
        reset = edit.addAction("Réinitialiser ce menu")
        reset.setEnabled(bool(_layouts().get(menu_key(menu))))
        chosen = edit.exec(global_pos)
        if chosen is None:
            return
        snap = _snapshot(entries)
        if chosen in (add_above, add_below):
            snap.insert(index + (chosen is add_below), {"sep": True})
            _store(menu, order=snap)
        elif chosen is remove_sep:
            snap.pop(index)
            _store(menu, order=snap)
        elif chosen is add_label:
            snap.insert(index, {"label": "Section"})
            _store(menu, order=snap)
            _refresh_open_menu(menu)
            self._rename_label(index)
            return
        elif chosen is rename_label:
            self._rename_label(index)
            return
        elif chosen is remove_label:
            snap.pop(index)
            _store(menu, order=snap)
        elif chosen is reset:
            _store(menu, reset=True)
            menu.close()
            return
        elif chosen in icon_actions:
            path = icon_actions[chosen]
            if path == "<pick>":
                root = _root_menu(menu)
                root.close()
                QTimer.singleShot(150, lambda k=menu_key(menu), i=value: _pick_icon_file(k, i))
                return
            icons = dict((_layouts().get(menu_key(menu)) or {}).get("icons") or {})
            icons[value] = path
            _store(menu, icons=icons)
        _refresh_open_menu(menu)

    def _rename_label(self, index: int):
        menu = self.menu
        entries = _entries(menu)
        if index >= len(entries) or entries[index][0] != "label":
            return
        section = entries[index][2].defaultWidget()

        def commit(text: str, i=index):
            snap = _snapshot(_entries(menu))
            if i < len(snap) and "label" in snap[i]:
                if text:
                    snap[i] = {"label": text}
                else:
                    snap.pop(i)
                _store(menu, order=snap)
            _refresh_open_menu(menu)

        section.start_edit(commit)


def _editor(menu: QMenu) -> None:
    if getattr(menu, "_ctx_editor", None) is None:
        menu._ctx_editor = _MenuEditor(menu)
        menu.installEventFilter(menu._ctx_editor)


def _root_menu(menu: QMenu) -> QMenu:
    while isinstance(menu.parent(), QMenu):
        menu = menu.parent()
    return menu


def _icon_choices() -> list:
    seen, out = set(), []
    folders = list(_STATE["icon_sources"])
    if _STATE["icon_dir"] is not None:
        folders.insert(0, _STATE["icon_dir"])
    for folder in folders:
        try:
            files = sorted(p for p in folder.iterdir() if p.suffix.lower() in ICON_EXTENSIONS)
        except OSError:
            continue
        for path in files:
            if path.name not in seen:
                seen.add(path.name)
                out.append(path)
    return out


def _pick_icon_file(key: str, iid: str) -> None:
    """« Choisir un fichier… » : le menu s'est ferme ; l'image choisie est copiee dans le dossier
    d'icones (proposee ensuite dans tous les menus) et posee sur l'element."""
    path, _filter = QFileDialog.getOpenFileName(
        None, "Icône de l'élément", "", "Images (" + " ".join(f"*{e}" for e in ICON_EXTENSIONS) + ")")
    if not path:
        return
    source = Path(path)
    target = source
    folder = _STATE["icon_dir"]
    if folder is not None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / source.name
            if target.resolve() != source.resolve():
                shutil.copyfile(source, target)
        except OSError:
            target = source
    layouts = dict(_layouts())
    layout = dict(layouts.get(key) or {})
    icons = dict(layout.get("icons") or {})
    icons[iid] = str(target)
    layout["icons"] = icons
    layouts[key] = layout
    _save_layouts(layouts)
