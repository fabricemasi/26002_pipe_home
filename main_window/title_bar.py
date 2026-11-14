"""Barre de titre / barre de navigation (TitleBar), cheminement (puces), cadre « Visionneuse ».

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from app_style import C, resolve_color_ref, role_color, role_font, font, scaled, start_native_move
from previews import UI_ICON_APP_LOGO, custom_ui_icon_pixmap
from settings_store import DEFAULT_SETTINGS, navbar_effective
from browser_core import TITLEBAR_HEIGHT, _resolve_font_family
from preview_column import IconButton
import ui_state
import previews as _previews

from .helpers import _set_qss

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pipeline_browser import PipelineBrowser      # annotations seulement (pipeline_browser importe ce module)


_CRUMB_LOOK_CACHE: list = [None, None]       # [reglages appliques, habillage] : un calcul par jeu de reglages


def _sides_px(value) -> dict:
    """Marge / padding de fm_browser (`navtool_margin`, `navtool_padding`) en px a l'echelle courante."""
    value = value if isinstance(value, dict) else {}
    out = {}
    for side in ("left", "top", "right", "bottom"):
        try:
            out[side] = scaled(max(0, int(value.get(side, 0) or 0)), 0)
        except (TypeError, ValueError):
            out[side] = 0
    return out


def nav_tool_metrics(settings: dict, row: int, prefix: str = "navtool", size_key: str = "navtool_icon_size",
                     default: int = 24) -> tuple[int, dict, dict]:
    """Icones de la barre de navigation (fm_browser > Barre de navigation) : (cote du carre, marge, padding). Le
    cote = « Taille des icones », jamais plus que la 1re ligne moins la marge du haut et du bas ; le champ racine et
    le menu des presets prennent la meme hauteur et la meme position en Y. Boutons de la fenetre : prefixe
    `navbar_winbtn` (fm_theme > Barre de navigation > Boutons fenetre)."""
    margin = _sides_px(settings.get(f"{prefix}_margin"))
    padding = _sides_px(settings.get(f"{prefix}_padding"))
    try:
        size = scaled(max(8, int(settings.get(size_key, default) or default)), 0)
    except (TypeError, ValueError):
        size = scaled(default, 0)
    side = max(scaled(8, 0), min(size, row - margin["top"] - margin["bottom"]))
    return side, margin, padding


def _crumb_look() -> dict:
    """Habillage du cheminement (Reglages > Barre de navigation > Cheminement, cles `crumb_*`). Calcule une fois par
    jeu de reglages appliques (il est relu a chaque redimensionnement et a chaque cran d'un curseur)."""
    applied = ui_state.APPLIED_SETTINGS
    if _CRUMB_LOOK_CACHE[0] is applied and _CRUMB_LOOK_CACHE[1] is not None:
        return _CRUMB_LOOK_CACHE[1]
    look = _build_crumb_look()
    _CRUMB_LOOK_CACHE[0], _CRUMB_LOOK_CACHE[1] = applied, look
    return look


# Espace entre le cadre d'un onglet et son texte : fixe (refonte du 2026-11-08 : plus de reglage de padding).
_CRUMB_PADDING = {"left": 10, "top": 6, "right": 10, "bottom": 5}


def _build_crumb_look() -> dict:
    """Habillage des onglets du cheminement (refonte demandee par l'utilisateur, 2026-11-08) : espacement a gauche et
    entre les onglets, bordure de la barre coupee sous l'onglet actif / sous les autres, fond, bordures, border
    radius, fond de l'onglet actif, du survol, des onglets apres l'actif, police, police apres l'onglet actif. Un fond
    d'onglet actif / apres l'actif / de survol transparent = le fond commun."""
    from settings_store import _coerce_corner_radius, _coerce_side_enabled
    values = dict(DEFAULT_SETTINGS)
    values.update(navbar_effective(ui_state.APPLIED_SETTINGS or {}))     # bordure basse : override de fm_browser
    sides = ("top", "right", "bottom", "left")

    def number(key, default, low=0, high=999):
        try:
            return max(low, min(high, int(values.get(key, default))))
        except (TypeError, ValueError):
            return default

    def fill(key):
        color = QColor(resolve_color_ref(values.get(key), "#00000000"))
        return color if color.alpha() else None

    def text_font(pre):
        size = number(f"{pre}_font_size", 10, 4, 80)
        weight = 700 if values.get(f"{pre}_font_bold") else 500
        family = (values.get(f"{pre}_font_family") or "").strip()
        if family and family != "Systeme":
            result = font(size, weight, family=_resolve_font_family(family, size, weight),
                          italic=bool(values.get(f"{pre}_font_italic")))
        else:
            result = role_font("info", size, weight)
            result.setItalic(bool(values.get(f"{pre}_font_italic")))
        return result, QColor(resolve_color_ref(values.get(f"{pre}_font_color"), role_color("info", C["text_mono"])))

    raw = values.get("crumb_border")
    enabled = _coerce_side_enabled(values.get("crumb_border_enabled"), False)
    base_font, base_color = text_font("crumb")
    after_font, after_color = text_font("crumb_after_active")
    return {
        "spacing": number("crumb_spacing", 5, 0, 80),
        "left": number("crumb_left_spacing", 10, 0, 400),            # avant le 1er onglet
        "bg": fill("crumb_bg_color"), "active_bg": fill("crumb_active_bg_color"),
        "after_bg": fill("crumb_after_active_bg_color"), "hover_bg": fill("crumb_hover_bg_color"),
        "border_on": enabled,
        "border_colors": {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, "#303539")
                          for s in sides},
        "thickness": number("crumb_border_thickness", 1, 0, 20) if any(enabled.values()) else 0,
        "radius": _coerce_corner_radius(values.get("crumb_corner_radius", 0)),
        "font": base_font, "color": base_color, "after_font": after_font, "after_color": after_color,
        "padding": {s: scaled(v, 0) for s, v in _CRUMB_PADDING.items()},
        # « Couper la bordure » : sous l'onglet, ni sa bordure basse ni le filet de la barre ; l'onglet descend sur
        # l'epaisseur du filet (`band`) et rejoint ce qui est dessous. Un reglage pour l'onglet actif, un pour les autres.
        "cut_active": bool(values.get("crumb_cut_border_active")),
        "cut_others": bool(values.get("crumb_cut_border_others")),
        "band": (number("navbar_bottom_thickness", 1, 0, 40) if values.get("navbar_bottom_enabled", True) else 0),
        "signature": (repr({k: v for k, v in values.items() if k.startswith("crumb_")}) + repr(values.get("colors"))
                      + repr((values.get("navbar_bottom_enabled"), values.get("navbar_bottom_thickness")))),
    }


def _crumb_state(kind: str) -> tuple:
    """Genre d'un onglet -> (etat, actif) : « set », « after », « after_focus » (apres l'onglet actif) ; suffixe
    « ! » = l'onglet actif (celui qui a le focus)."""
    return kind.rstrip("!"), kind.endswith("!")


class _CrumbChip(QWidget):
    """Un onglet du cheminement : fond (commun, actif, apres l'actif, survol par-dessus), bordures, border radius,
    texte (police commune, ou celle d'apres l'onglet actif) ; cliquer = focus sur l'element de sa colonne."""

    clicked = Signal()

    def __init__(self, text: str, kind: str, look: dict, parent=None):
        super().__init__(parent)
        self._kind, self._look = kind, look
        self._full_text = text                    # aucune info-bulle au survol (demande de l'utilisateur)
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.set_look(look, kind)

    def set_look(self, look: dict, kind: str):
        """(Re)pose l'habillage, la taille et le texte : mise a jour SUR PLACE, sans recreer l'onglet."""
        self._kind, self._look = kind, look
        state, self._focus = _crumb_state(kind)
        self._after = after = state == "after_focus"
        self._font, self._color = (look["after_font"], look["after_color"]) if after else (look["font"], look["color"])
        own = look["active_bg"] if self._focus else look["after_bg"] if after else None
        self._bg = own if own is not None else look["bg"]
        metrics = QFontMetrics(self._font)
        self._text = metrics.elidedText(self._full_text, Qt.ElideMiddle, scaled(220, 0))
        pad, t, on = look["padding"], look["thickness"], look["border_on"]
        self._cut = cut = look["cut_active"] if self._focus else look["cut_others"]
        band = look["band"]
        self._edge = {"left": pad["left"] + (t if on["left"] else 0), "right": pad["right"] + (t if on["right"] else 0),
                      "top": pad["top"] + (t if on["top"] else 0),
                      "bottom": pad["bottom"] + (t if on["bottom"] and not cut else 0) + (band if cut else 0)}
        # Rangee descendue sur le filet (un onglet coupe) : un onglet NON coupe reste au-dessus du filet.
        self._below = band if not cut and (look["cut_active"] or look["cut_others"]) else 0
        radius = dict(look["radius"]) if isinstance(look["radius"], dict) else {
            k: int(look["radius"] or 0) for k in ("top_left", "top_right", "bottom_right", "bottom_left")}
        radius["bottom_left"] = radius["bottom_right"] = 0      # aucun arrondi contre la bordure
        self._radius = radius
        width = metrics.horizontalAdvance(self._text) + self._edge["left"] + self._edge["right"]
        height = metrics.height() + self._edge["top"] + self._edge["bottom"]
        self.setFixedSize(width, height + self._below)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def box_rect(self) -> QRect:
        """L'onglet peint (sans l'espace laisse sous lui au-dessus du filet)."""
        return self.rect().adjusted(0, 0, 0, -self._below)

    def paintEvent(self, event):
        from settings_widgets import _paint_bordered_vector
        look = self._look
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        fill = look["hover_bg"] if self._hover and look["hover_bg"] is not None else self._bg
        border_on = dict(look["border_on"], bottom=False) if self._cut else look["border_on"]
        thickness = look["thickness"]
        if fill is not None or thickness:
            _paint_bordered_vector(painter, self.box_rect(), self._radius, border_on, thickness,
                                   look["border_colors"], fill.name(QColor.NameFormat.HexArgb) if fill else None)
        painter.setFont(self._font)
        painter.setPen(self._color)
        inner = self.box_rect().adjusted(self._edge["left"], self._edge["top"], -self._edge["right"],
                                         -self._edge["bottom"])
        painter.drawText(inner, Qt.AlignVCenter | Qt.AlignLeft, self._text)
        painter.end()

    def mousePressEvent(self, event):
        # Garder le clic : sinon il remonte a la barre de titre, qui lance le deplacement natif de la fenetre
        # (boucle modale) et le relachement n'arrive jamais ici.
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        event.accept()


class _ViewerGroup(QWidget):
    """Cadre « Visionneuse » de la barre de navigation (demande de l'utilisateur) : les boutons de la visionneuse /
    planche y sont regroupes, visionneuse ouverte. Habillage : Reglages > Visionneuse > Regroupement (fond, police
    du libelle, bordures, border radius, padding, margin ; cles `viewer_group_*`). Les boutons sont ses enfants,
    poses par `PipelineBrowser._layout_viewer_buttons` a partir de `content_origin()`."""

    LABEL = "Visionneuse"

    def __init__(self, parent=None, label: str | None = None):
        super().__init__(parent)
        if label is not None:
            self.LABEL = label                    # cadre « Editeur de texte » : meme habillage, autre libelle
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.restyle()

    def restyle(self):
        from settings_store import _coerce_corner_radius, _coerce_side_enabled
        values = dict(DEFAULT_SETTINGS)
        values.update(ui_state.APPLIED_SETTINGS or {})

        def box(key):
            raw = values.get(key)
            raw = raw if isinstance(raw, dict) else {}
            return {s: max(0, int(raw.get(s, 0) or 0)) for s in ("left", "top", "right", "bottom")}

        size = max(4, int(values.get("viewer_group_label_font_size", 9) or 9))
        weight = 700 if values.get("viewer_group_label_font_bold") else 500
        family = (values.get("viewer_group_label_font_family") or "").strip()
        if family and family != "Systeme":
            label_font = font(size, weight, family=_resolve_font_family(family, size, weight),
                              italic=bool(values.get("viewer_group_label_font_italic")))
        else:
            label_font = role_font("info", size, weight)
            label_font.setItalic(bool(values.get("viewer_group_label_font_italic")))
        raw = values.get("viewer_group_border")
        sides = ("top", "right", "bottom", "left")
        enabled = _coerce_side_enabled(values.get("viewer_group_border_enabled"), True)
        thickness = max(0, int(values.get("viewer_group_border_thickness", 1) or 0)) if any(enabled.values()) else 0
        bg = QColor(resolve_color_ref(values.get("viewer_group_bg_color"), "#00000000"))
        self.look = {
            "label": bool(values.get("viewer_group_label_enabled", True)),    # nom du module affiche ou non
            "font": label_font,
            "color": QColor(resolve_color_ref(values.get("viewer_group_label_font_color"), C["dim"])),
            "bg": bg if bg.alpha() else None,
            "border_on": enabled, "thickness": thickness,
            "border_colors": {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, "#303539")
                              for s in sides},
            "radius": _coerce_corner_radius(values.get("viewer_group_corner_radius", 4)),
            "padding": box("viewer_group_padding"), "margin": box("viewer_group_margin"),
        }
        self.update()

    def _edges(self) -> dict:
        look, t = self.look, self.look["thickness"]
        return {s: look["padding"][s] + (t if look["border_on"].get(s) else 0)
                for s in ("left", "top", "right", "bottom")}

    def label_width(self) -> int:
        if not self.look["label"]:
            return 0
        return QFontMetrics(self.look["font"]).horizontalAdvance(self.LABEL)

    def content_origin(self) -> QPoint:
        """Ou commence le premier bouton (apres le libelle, s'il est affiche)."""
        gap = scaled(8, 0) if self.look["label"] else 0
        return QPoint(self._edges()["left"] + self.label_width() + gap, self._edges()["top"])

    def fit(self, content_right: int, content_height: int):
        """Taille du cadre pour des boutons qui finissent a `content_right` (coordonnees du cadre)."""
        edges = self._edges()
        label_h = QFontMetrics(self.look["font"]).height() if self.look["label"] else 0
        height = max(content_height, label_h) + edges["top"] + edges["bottom"]
        self.setFixedSize(content_right + edges["right"], height)

    def paintEvent(self, event):
        from settings_widgets import _paint_bordered_vector
        look = self.look
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if look["bg"] is not None or look["thickness"]:
            _paint_bordered_vector(painter, self.rect(), look["radius"], look["border_on"], look["thickness"],
                                   look["border_colors"],
                                   look["bg"].name(QColor.NameFormat.HexArgb) if look["bg"] else None)
        if look["label"]:
            edges = self._edges()
            painter.setFont(look["font"])
            painter.setPen(look["color"])
            painter.drawText(QRect(edges["left"], 0, self.label_width() + 2, self.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, self.LABEL)
        painter.end()


class TitleBar(QWidget):

    def __init__(self, window: "PipelineBrowser", parent=None):
        super().__init__(parent)
        self._window = window
        self.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        # objectName + selecteur ID (voir la meme remarque pour #CentralFrame
        # et #DetailPanel) : sans ce ciblage strict, le "border-bottom" nu se
        # propageait au title_label (le seul enfant sans bordure propre),
        # qui se retrouvait souligne sur sa seule largeur de texte au lieu du
        # filet visant a courir sur toute la largeur de la barre.
        self.setObjectName("TitleBar")
        # Indispensable pour qu'une sous-classe de QWidget (comme celle-ci)
        # peigne effectivement son propre style — sans lui, le fond et la
        # bordure ci-dessus sont ignores au rendu (seul un QWidget "nu",
        # sans sous-classe, les applique automatiquement) : voir Column, qui
        # pose deja cet attribut pour la meme raison.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#TitleBar {{ background: {C['app_bg']}; border-bottom: 1px solid {C['border']}; }}")
        self.setMouseTracking(True)

        icon = QLabel()
        self._icon = icon
        icon_size = scaled(9)
        icon.setFixedSize(icon_size, icon_size)
        # Icone perso (voir Settings > ICONES > General, UI_ICON_APP_LOGO)
        # si l'utilisateur en a choisi une, sinon le carre neutre d'origine.
        custom_logo = custom_ui_icon_pixmap(UI_ICON_APP_LOGO, icon_size)
        if custom_logo is not None:
            icon.setPixmap(custom_logo)
            icon.setStyleSheet("background: transparent;")
        else:
            icon.setStyleSheet(f"border: 1px solid {C['mark_dir_bd']}; background: transparent;")
        # Transparent aux clics : sans ca, cliquer PILE sur l'icone ou le
        # texte du titre (plutot qu'a cote, sur le fond nu de la barre) ne
        # declenche jamais TitleBar.mousePressEvent ci-dessous — un widget
        # enfant sous le curseur capte l'evenement souris meme s'il n'en
        # fait rien, Qt ne le remonte pas tout seul au parent. C'etait la
        # cause du "des fois le clic ne deplace pas la fenetre".
        icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.title_label = QLabel(window.windowTitle())
        self.title_label.setFont(role_font("app", 11, 400, tracking=0.01))
        self.title_label.setStyleSheet(f"color: {role_color('app', C['label'])}; background: transparent;")
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(9)
        # Logo et titre : en haut de la barre (comme les boutons : barre haute = tout reste en haut), centres sur
        # la hauteur d'un bouton (TITLEBAR_HEIGHT) pour s'aligner avec les outils de la barre.
        self._icon_holder = QWidget()
        holder_layout = QHBoxLayout(self._icon_holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(icon, alignment=Qt.AlignVCenter)
        self._icon_holder.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        self._icon_holder.setObjectName("NavHolder")
        self._icon_holder.setStyleSheet("#NavHolder { background: transparent; }")   # sinon « QWidget » de l'appli : gris
        self.title_label.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        layout.addWidget(self._icon_holder, alignment=Qt.AlignTop)
        layout.addWidget(self.title_label, alignment=Qt.AlignTop)
        layout.addStretch(1)

        # Choix de chaque colonne, SOUS le titre, colles a gauche (a la hauteur d'un bouton : la rangee des outils
        # reste en haut). Enfant libre de la barre : placee par `_place_crumbs`.
        self._crumb_names: list = []
        self.crumbs = QWidget(self)
        self.crumbs.setStyleSheet("background: transparent;")
        self._crumb_layout = QHBoxLayout(self.crumbs)
        self._crumb_layout.setContentsMargins(0, 0, 0, 0)
        self._crumb_layout.setSpacing(scaled(5, 0))
        self.btn_min = self._make_button("min", window.showMinimized)
        self.btn_max = self._make_button("max", self._toggle_max)
        self.btn_close = self._make_button("close", window.close)
        # Punaise : 4e bouton de la fenetre, TOUJOURS visible (demande de l'utilisateur, 2026-11-07) ; un clic met la
        # fenetre au premier plan tout le temps, un autre la libere (aussi : clic droit sur la barre).
        self.btn_pin = self._make_button("pin", self._toggle_always_on_top)
        self._sync_pin()
        # Rangee SANS espacement : seule leur marge (`navbar_winbtn_margin`) les ecarte — a 0 ils se touchent
        # (demande de l'utilisateur, 2026-11-08 ; avant : l'espacement de la barre, 9 px).
        winbtns = QWidget()
        winbtns.setObjectName("NavHolder")
        winbtns.setStyleSheet("#NavHolder { background: transparent; }")
        winbtn_row = QHBoxLayout(winbtns)
        winbtn_row.setContentsMargins(0, 0, 0, 0)
        winbtn_row.setSpacing(0)
        for btn in (self.btn_pin, self.btn_min, self.btn_max, self.btn_close):
            winbtn_row.addWidget(btn, alignment=Qt.AlignTop)
        layout.addWidget(winbtns, alignment=Qt.AlignTop)

    def _crumb_row_height(self) -> int:
        """Hauteur de la rangee du cheminement : l'onglet le plus haut (police commune ou d'apres l'onglet actif,
        padding fixe, bordures haut / bas)."""
        look = _crumb_look()
        pad, t, on = look["padding"], look["thickness"], look["border_on"]
        text = max(QFontMetrics(look["font"]).height(), QFontMetrics(look["after_font"]).height())
        height = text + pad["top"] + pad["bottom"] + (t if on["top"] else 0) + (t if on["bottom"] else 0)
        return max(scaled(14, 0), height)

    def set_crumbs(self, items: list, force: bool = False):
        """Un repere par colonne ayant un choix, a gauche sous le titre. `items` = [(genre, nom, rappel)] : genre
        « set » (colonnes du set) ou « after » (apres le set, ou projet sans set) ; `rappel` = ce que fait un clic
        (= cliquer l'element de sa colonne). Mise en forme : Reglages > Barre de navigation > Cheminement."""
        look = _crumb_look()
        names = [str(name) for _kind, name, _cb in items]
        key = (names, [kind for kind, _n, _c in items], look["signature"])
        if not force and key == getattr(self, "_crumb_key", None) and self._crumb_layout.count():
            self._crumb_items = items
            return
        structure = (names, [kind for kind, _n, _c in items])
        previous = getattr(self, "_crumb_structure", None)
        self._crumb_key = key
        self._crumb_items = items
        self._crumb_names = names
        if not force and structure == previous and self._crumb_layout.count():
            self._restyle_crumbs(look)                       # memes reperes : seulement l'habillage change
            return
        kinds = [kind for kind, _n, _c in items]
        if (not force and previous is not None and self._crumb_layout.count()
                and len(previous[1]) == len(kinds)):
            # Autant de reperes, autres noms ou etats (visionneuse : image suivante ; focus deplace) : textes et
            # habillages changes SUR PLACE, aucun widget recree (sinon chaque image refaisait toute la rangee).
            self._crumb_structure = structure
            chips = iter(zip(names, kinds))
            for index in range(self._crumb_layout.count()):
                widget = self._crumb_layout.itemAt(index).widget()
                if isinstance(widget, _CrumbChip):
                    widget._full_text, kind = next(chips)
                    widget.set_look(look, kind)
            return
        self._crumb_structure = structure
        while self._crumb_layout.count():
            item = self._crumb_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._crumb_layout.setSpacing(look["spacing"])
        self._crumb_layout.setContentsMargins(scaled(look["left"], 0), 0, 0, 0)
        for index, (kind, name, callback) in enumerate(items):
            chip = _CrumbChip(name, kind, look)
            # Le rappel est relu au clic dans `_crumb_items` : les reperes sont gardes d'un rafraichissement a
            # l'autre (mise a jour sur place) alors que les colonnes, elles, sont recreees.
            chip.clicked.connect(lambda i=index: self._crumb_click(i))
            self._crumb_layout.addWidget(chip, 0, Qt.AlignBottom)     # contre la bordure du bas
        self._crumb_layout.addStretch(1)
        self.refresh_sizes()

    def _crumb_click(self, index: int):
        items = getattr(self, "_crumb_items", None) or []
        if 0 <= index < len(items):
            items[index][2]()

    def _restyle_crumbs(self, look: dict):
        """Habillage change, reperes inchanges : puces mises a jour sur place (aucun widget recree)."""
        self._crumb_layout.setSpacing(look["spacing"])
        self._crumb_layout.setContentsMargins(scaled(look["left"], 0), 0, 0, 0)
        self.crumbs.update()
        kinds = iter([kind for kind, _n, _c in self._crumb_items])
        for index in range(self._crumb_layout.count()):
            widget = self._crumb_layout.itemAt(index).widget()
            if isinstance(widget, _CrumbChip):
                widget.set_look(look, next(kinds))
        self.refresh_sizes()

    def refresh_crumbs(self):
        """Reglages changes : repose les reperes seulement si leur habillage a change."""
        if getattr(self, "_crumb_items", None) is not None:
            self.set_crumbs(self._crumb_items)

    def _place_crumbs(self):
        reserved = sum(b.width() for b in self._window_buttons() if not b.isHidden())   # boutons de la fenetre
        # En BAS de la barre, juste au-dessus de sa bordure (demande de l'utilisateur, 2026-11-07 ; avant : sous le
        # titre), jamais au-dessus de la rangee des outils. L'espacement a gauche est la marge du layout
        # (« Espacement a gauche », `crumb_left_spacing`). Bordure coupee : la rangee descend sur le filet.
        band = getattr(self, "_bottom_border_px", 0)
        look = _crumb_look()
        cut = look["cut_active"] or look["cut_others"]
        floor = self.height() - (0 if cut else band)
        row = min(self._crumb_row_height() + (band if cut else 0), max(0, floor - self._row_height()))
        self.crumbs.setGeometry(0, floor - row, max(0, self.width() - reserved), row)
        self.crumbs.raise_()
        self.update()                                     # filet coupe sous les reperes (paintEvent)

    def _crumb_ranges(self) -> list:
        """Etendue en X (coordonnees de la barre) de chaque onglet coupe visible : ou le filet du bas est coupe."""
        ranges = []
        layout = self._crumb_layout
        for index in range(layout.count()):
            chip = layout.itemAt(index).widget()
            if isinstance(chip, _CrumbChip) and not chip.isHidden() and chip._cut:
                box = chip.box_rect().translated(chip.pos() + self.crumbs.pos())
                ranges.append((box.left(), box.right() + 1))
        return sorted(ranges)

    def paintEvent(self, event):
        # Filet du bas peint ici quand il est coupe sous les reperes (« Couper la bordure ») : la feuille de style
        # garde alors une bordure TRANSPARENTE de meme epaisseur (le fond de la barre en dessous).
        line = getattr(self, "_cut_line", None)
        if not line:
            return
        width, color = line
        painter = QPainter(self)
        y, x = self.height() - width, 0
        for start, end in self._crumb_ranges():
            if start > x:
                painter.fillRect(x, y, start - x, width, color)
            x = max(x, end)
        if x < self.width():
            painter.fillRect(x, y, self.width() - x, width, color)
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_crumbs()
        self.place_viewer_group()
        self._place_load_bar()
        self.place_bottom_badge()

    def set_bottom_badge(self, widget):
        """Encart accroche en BAS de la barre, a droite (mode de rendu du board : OPEN GL / CLASSIQUE) ; None =
        aucun."""
        old = getattr(self, "_bottom_badge", None)
        if old is not None and old is not widget:
            old.hide()
        self._bottom_badge = widget
        self.place_bottom_badge()

    def place_bottom_badge(self):
        """Colle en bas, a droite (sous les boutons de la fenetre) ; a leur gauche s'il en recouvrait plus que le
        bord."""
        badge = getattr(self, "_bottom_badge", None)
        if badge is None:
            return
        gap = scaled(8, 0)
        x = self.width() - badge.width() - gap
        y = self.height() - badge.height()
        first = QRect(self.btn_min.mapTo(self, QPoint(0, 0)), self.btn_min.size())   # dans sa rangee
        if first.bottom() - y > scaled(4, 0) and x + badge.width() > first.left() - gap:
            x = first.left() - gap - badge.width()
        badge.move(x, y)
        badge.raise_()

    def set_load_progress(self, percent: int | None):
        """Barre « Réglages n % » en bas a droite de la barre (chargement des reglages sur inactivite) ; None =
        masquee. Meme habillage que la barre de mise en cache des apercus."""
        status = getattr(self, '_background_status', None)
        if status is not None:
            status.settings_progress(percent)
            return
        bar = getattr(self, "_load_bar", None)
        if percent is None:
            if bar is not None:
                bar.setFormat("Réglages en mémoire  %p %")
                bar.setStyleSheet(f"QProgressBar {{ background: transparent; border: none; color: {C['label']}; }} "
                                 "QProgressBar::chunk { background: transparent; }")
                bar.show()
            return
        if bar is None:
            bar = self._load_bar = QProgressBar(self)
            bar.setFixedSize(scaled(150), scaled(15))
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setAlignment(Qt.AlignCenter)
            bar.setFormat("Réglages  %p %")
            bar.setFont(role_font("app", 8, 400))
            bar.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            bar.setStyleSheet(
                f"QProgressBar {{ background: {C['chrome']}; border: 1px solid {C['border']}; border-radius: 3px; "
                f"color: {role_color('app', C['label'])}; }} "
                f"QProgressBar::chunk {{ background: {C['accent']}; border-radius: 2px; }}")
        bar.setValue(max(0, min(100, int(percent))))
        bar.setFormat("Réglages  %p %")
        bar.setStyleSheet(f"QProgressBar {{ background: {C['chrome']}; border: 1px solid {C['border']}; "
                         f"color: {C['label']}; }} QProgressBar::chunk {{ background: {C['accent']}; }}")
        self._place_load_bar()
        bar.show()
        bar.raise_()

    def _place_load_bar(self):
        bar = getattr(self, "_load_bar", None)
        if bar is not None:
            gap = scaled(6, 0)
            bar.move(self.width() - bar.width() - gap, self.height() - bar.height() - gap)

    def viewer_group(self) -> "_ViewerGroup":
        group = getattr(self, "_viewer_group", None)
        if group is None:
            group = self._viewer_group = _ViewerGroup(self)
            group.hide()
        return group

    def editor_group(self) -> "_ViewerGroup":
        """Cadre « Éditeur » (module Markdown / code, paquet mdeditor/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_editor_group", None)
        if group is None:
            group = self._editor_group = _ViewerGroup(self, "Éditeur")
            group.hide()
        return group

    def board_group(self) -> "_ViewerGroup":
        """Cadre « Board » (mode board, paquet board/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_board_group", None)
        if group is None:
            group = self._board_group = _ViewerGroup(self, "Board")
            group.hide()
        return group

    def video_group(self) -> "_ViewerGroup":
        """Cadre « Vidéo » (module fm_video/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_video_group", None)
        if group is None:
            group = self._video_group = _ViewerGroup(self, "Vidéo")
            group.hide()
        return group

    def font_group(self) -> "_ViewerGroup":
        """Cadre « Typographie » (module fm_font/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_font_group", None)
        if group is None:
            group = self._font_group = _ViewerGroup(self, "Typographie")
            group.hide()
        return group

    def pdf_group(self) -> "_ViewerGroup":
        """Cadre « PDF » (module fm_pdf/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_pdf_group", None)
        if group is None:
            group = self._pdf_group = _ViewerGroup(self, "PDF")
            group.hide()
        return group

    def agenda_group(self) -> "_ViewerGroup":
        """Cadre « Agenda » (module fm_agenda/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_agenda_group", None)
        if group is None:
            group = self._agenda_group = _ViewerGroup(self, "Agenda")
            group.hide()
        return group

    def taches_group(self) -> "_ViewerGroup":
        """Cadre « Tâches » (module fm_taches/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_taches_group", None)
        if group is None:
            group = self._taches_group = _ViewerGroup(self, "Tâches")
            group.hide()
        return group

    def audio_group(self) -> "_ViewerGroup":
        """Cadre « FM Audio » (module fm_audio/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_audio_group", None)
        if group is None:
            group = self._audio_group = _ViewerGroup(self, "FM Audio")
            group.hide()
        return group

    def music_group(self) -> "_ViewerGroup":
        """Cadre « FM Music » (module fm_music/) : memes habillage et place que « Visionneuse »."""
        group = getattr(self, "_music_group", None)
        if group is None:
            group = self._music_group = _ViewerGroup(self, "FM Music")
            group.hide()
        return group

    def place_viewer_group(self):
        """Cadres « Visionneuse » / « Éditeur » / « Board » / « Vidéo » / « Typographie » / « PDF » / « Agenda » :
        a la suite des outils (apres le dernier bouton de la barre), centres dans la hauteur de la rangee des outils,
        decales de leur margin."""
        for group in (getattr(self, "_viewer_group", None), getattr(self, "_editor_group", None),
                      getattr(self, "_board_group", None), getattr(self, "_video_group", None),
                      getattr(self, "_font_group", None), getattr(self, "_pdf_group", None),
                      getattr(self, "_agenda_group", None), getattr(self, "_taches_group", None),
                      getattr(self, "_audio_group", None), getattr(self, "_music_group", None)):
            if group is not None and not group.isHidden():
                self._place_group(group)

    def _place_group(self, group):
        tools = getattr(self, "_tool_buttons", None)
        anchor = tools[-1] if tools else self.title_label
        margin = group.look["margin"]
        row = self._row_height()
        x = anchor.mapTo(self, QPoint(anchor.width(), 0)).x() + margin["left"]   # bouton dans la rangee des icones
        y = (row - group.height()) // 2 + margin["top"] - margin["bottom"]
        if group.pos() != QPoint(x, y):
            group.move(x, y)
        group.raise_()

    def add_tools(self, *widgets):
        """Racine, parcourir, presets, reglages... poses juste apres le titre. Les IconButton ont tous la MEME
        taille (celle des boutons reduire / agrandir / fermer)."""
        root_field, browse, picker, presets, settings, collapse, *modes = widgets
        # modes : boutons visionneuse et editeur de texte, a la suite du repli des colonnes.
        self._tool_buttons = [browse, presets, settings, collapse, *modes]
        layout = self.layout()
        # Disposition de BASE (capture de l'utilisateur) : tout sur la meme ligne, centre dans la hauteur de la
        # barre ; racine a 32 px du titre, Parcourir colle a la racine (3 px), 14 px avant le menu des presets,
        # puis 9 px entre les boutons ; repli des colonnes a la suite de l'engrenage.
        box = QWidget()
        self._tool_boxes = [box, picker]
        # PAS de feuille de style ici (`background: transparent` sans selecteur se propageait au champ racine et
        # ecrasait la feuille de style de l'appli : champ NOIR, indifferent a Reglages > Zone de saisie).
        row = QHBoxLayout(box)
        row.setContentsMargins(scaled(23, 0), 0, 0, 0)       # + l'espacement de la barre (9) = 32
        row.setSpacing(scaled(3, 0))
        # Champ racine dans un support aux marges haut / bas des icones : meme hauteur ET meme Y que leur cadre,
        # meme si la marge du haut differe de celle du bas (refresh_sizes).
        field_box = QWidget()
        self._field_box_layout = QVBoxLayout(field_box)
        self._field_box_layout.setContentsMargins(0, 0, 0, 0)
        self._field_box_layout.addWidget(root_field, alignment=Qt.AlignVCenter)
        select = getattr(picker, "select", None)
        self._nav_fields = tuple(w for w in (root_field, select) if w is not None)
        self._picker = picker
        if select is not None:
            select._keep_height = True                   # Zone de saisie > Hauteur ne s'y applique plus
        row.addWidget(field_box, alignment=Qt.AlignVCenter)
        row.addWidget(browse, alignment=Qt.AlignVCenter)
        picker.layout().setContentsMargins(scaled(5, 0), 0, 0, 0)   # + 9 = 14 apres Parcourir
        self._tool_boxes.append(field_box)
        for holder in self._tool_boxes:                  # meme hauteur qu'un bouton : champs centres dessus
            holder.setFixedHeight(scaled(TITLEBAR_HEIGHT))
            holder.setObjectName("NavHolder")            # fond de la barre, pas le gris du « QWidget » de l'appli
            holder.setStyleSheet("#NavHolder { background: transparent; }")
        # Icones a la suite : une rangee SANS espacement, seule leur marge (`navtool_margin`) les ecarte — a 0 elles
        # se touchent (demande de l'utilisateur, 2026-11-07).
        icons = QWidget()
        icons.setObjectName("NavHolder")
        icons.setStyleSheet("#NavHolder { background: transparent; }")
        icons_row = QHBoxLayout(icons)
        icons_row.setContentsMargins(0, 0, 0, 0)
        icons_row.setSpacing(0)
        for button in (presets, settings, collapse, *modes):
            icons_row.addWidget(button, alignment=Qt.AlignVCenter)
        self._tool_boxes.append(icons)
        position = 2                                     # apres l'icone et le titre
        for widget in (box, picker, icons):
            layout.insertWidget(position, widget, alignment=Qt.AlignTop)
            position += 1

    def refresh_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) a la
        hauteur de la barre et a ses boutons — construits une seule fois
        (contrairement aux colonnes, jamais reconstruits), donc sans cela le
        slider d'echelle ne les affecterait qu'au prochain lancement."""
        settings = ui_state.APPLIED_SETTINGS or {}
        # Deux etages (demande de l'utilisateur, 2026-11-07) : la 1re LIGNE (titre, outils, reduire / agrandir /
        # fermer) a la hauteur de fm_theme (`navbar_height`, celle d'une barre standard), tous ses elements centres
        # dessus ; la barre l'augmente de la hauteur additionnelle de fm_browser (`navtool_extra_height`), ou se pose
        # le cheminement (jamais moins que sa rangee).
        row = self._row_height()
        try:
            extra = scaled(max(0, int(settings.get("navtool_extra_height", 70) or 0)), 0)
        except (TypeError, ValueError):
            extra = 0
        border = getattr(self, "_bottom_border_px", 0)
        height = row + max(extra, self._crumb_row_height() + border)
        self.setFixedHeight(height)
        self.layout().setContentsMargins(10, 0, 0, height - row)     # le layout = la 1re ligne seule
        self._place_crumbs()
        self._icon.setFixedSize(scaled(9), scaled(9))
        self._icon_holder.setFixedHeight(row)
        self.title_label.setFixedHeight(row)
        for holder in getattr(self, "_tool_boxes", ()):
            holder.setFixedHeight(row)
        # Boutons de la fenetre (fm_theme > Barre de navigation > Boutons fenetre) : CARRES, colles en haut (layout
        # AlignTop, aucune marge haute), marge autour, padding entre cadre et dessin.
        side, margin, padding = nav_tool_metrics(settings, row, "navbar_winbtn", "navbar_winbtn_size", 30)
        for btn in self._window_buttons():
            btn.setFixedSize(margin["left"] + side + margin["right"], margin["top"] + side + margin["bottom"])
            btn.set_margins(margin["left"], margin["top"], margin["right"], margin["bottom"])
            btn.set_padding(padding["left"], padding["top"], padding["right"], padding["bottom"])
        # Icones d'outils (reglages de fm_browser) : CARREES (« Taille des icones »), la marge autour (peinte en
        # dehors du cadre, `IconButton.set_margins`), le padding entre le cadre et le dessin.
        side, margin, padding = nav_tool_metrics(settings, row)
        for btn in getattr(self, "_tool_buttons", ()):
            btn.setFixedSize(margin["left"] + side + margin["right"], margin["top"] + side + margin["bottom"])
            if hasattr(btn, "set_margins"):
                btn.set_margins(margin["left"], margin["top"], margin["right"], margin["bottom"])
                btn.set_padding(padding["left"], padding["top"], padding["right"], padding["bottom"])
        # Champ racine et menu des presets : hauteur et Y du cadre des icones (memes marges haut / bas).
        if getattr(self, "_nav_fields", None):
            self._field_box_layout.setContentsMargins(0, margin["top"], 0, margin["bottom"])
            picker_layout = self._picker.layout()
            picker_layout.setContentsMargins(picker_layout.contentsMargins().left(), margin["top"], 0,
                                             margin["bottom"])
            for field in self._nav_fields:
                if field.height() != side or field.minimumHeight() != side:
                    field.setFixedHeight(side)
        self.place_viewer_group()

    def _row_height(self) -> int:
        """Hauteur de la 1re ligne de la barre : fm_theme > Barre de navigation > Hauteur barre."""
        try:
            height = navbar_effective(ui_state.APPLIED_SETTINGS or {}).get("navbar_height", 30)   # override fm_browser
            return max(scaled(16, 0), scaled(int(height), 0))
        except (TypeError, ValueError):
            return scaled(30, 0)

    def refresh_look(self):
        # Bordure basse et police du titre : celles de fm_theme, ou l'override de fm_browser (`navtool_ovr_*`).
        settings = navbar_effective(ui_state.APPLIED_SETTINGS or {})
        enabled = bool(settings.get("navbar_bottom_enabled", True))
        width = max(0, int(settings.get("navbar_bottom_thickness", 1))) if enabled else 0
        color = resolve_color_ref(settings.get("navbar_bottom_color"), C["border"])
        owner = self.window()
        toolbar_margin = settings.get("md_toolbar_margin") or {}
        margins_are_zero = (not any(int(toolbar_margin.get(side, 0) or 0)
                                    for side in ("top", "right", "bottom", "left"))
                            if isinstance(toolbar_margin, dict) else int(toolbar_margin or 0) == 0)
        toolbar_borders = settings.get("md_toolbar_border_enabled") or {}
        toolbar_top_enabled = (toolbar_borders.get("top", False) if isinstance(toolbar_borders, dict)
                              else bool(toolbar_borders))
        toolbar_visible = (getattr(owner, "_md_open", False) and settings.get("md_toolbar_enabled", True))
        if toolbar_visible:
            import fm_markdown.pane as md_pane
            pane = md_pane.instance(create=False)
            toolbar_visible = pane is not None and pane.kind == "markdown" and pane.mode == "edit"
        if toolbar_visible and margins_are_zero and toolbar_top_enabled:
            width = max(0, int(settings.get("md_toolbar_border_thickness", 1)))
            toolbar_colors = settings.get("md_toolbar_border") or {}
            toolbar_color = (toolbar_colors.get("top") if isinstance(toolbar_colors, dict) else toolbar_colors)
            color = resolve_color_ref(toolbar_color, C["border"])
        # _set_qss : rien si la feuille est identique (la barre porte tout le cheminement : repolir tous ses
        # descendants coutait ~6 ms, et refresh_look est rejouee plusieurs fois par cran de curseur).
        background = resolve_color_ref(settings.get("navbar_bg_color"), C["app_bg"])
        cut = (bool(settings.get("crumb_cut_border_active")) or bool(settings.get("crumb_cut_border_others"))) \
            and width > 0
        self._cut_line = (width, QColor(color)) if cut else None      # peint par paintEvent, coupe sous les reperes
        _set_qss(self, f"#TitleBar {{ background: {background}; "
                       f"border-bottom: {width}px solid {'transparent' if cut else color}; }}")
        if width != getattr(self, "_bottom_border_px", 0):    # le cheminement est pose juste au-dessus du filet
            self._bottom_border_px = width
            self.refresh_sizes()                               # hauteur (filet compris) puis place du cheminement
        size = max(6, int(settings.get("navbar_title_font_size", 11)))
        family = settings.get("navbar_title_font_family") or ""
        # « Niveau de lissage » de la ligne Police titre : n'etait jamais lu (2026-11-07).
        smoothing = (settings.get("navbar_title_font_smoothing") or "current"
                     if settings.get("navbar_title_font_smoothing_enabled") else "current")
        if family and family != "Systeme":
            weight = 700 if settings.get("navbar_title_font_bold") else 400
            title_font = font(size, weight, family=_resolve_font_family(family, size, weight),
                              italic=bool(settings.get("navbar_title_font_italic", False)), smoothing=smoothing)
        elif smoothing != "current":
            weight = 700 if settings.get("navbar_title_font_bold") else 400
            title_font = font(size, weight, family=role_font("titles", size, weight).family(), tracking=0.01,
                              italic=bool(settings.get("navbar_title_font_italic", False)), smoothing=smoothing)
        else:
            title_font = role_font("titles", size, 700 if settings.get("navbar_title_font_bold") else 400,
                                   tracking=0.01)
            title_font.setItalic(bool(settings.get("navbar_title_font_italic", False)))
        self.title_label.setFont(title_font)
        _set_qss(
            self.title_label,
            f"color: {resolve_color_ref(settings.get('navbar_title_font_color'), role_color('titles', C['label']))}; "
            "background: transparent;")
        custom_logo = custom_ui_icon_pixmap(UI_ICON_APP_LOGO, self._icon.width())
        self._icon.setPixmap(custom_logo or QPixmap())
        _set_qss(self._icon, "background: transparent;" if custom_logo is not None else
                 f"border: 1px solid {C['mark_dir_bd']}; background: transparent;")
        for btn in (self.btn_pin, self.btn_min, self.btn_max, self.btn_close):
            btn.update()
        self._apply_tool_look(settings)
        self.refresh_crumbs()

    def _apply_tool_look(self, settings: dict):
        """Boutons d'outils (reglages de fm_browser > Barre de navigation, cles `navtool_*`) : fond, bordure, border
        radius, fond au survol — cadre peint par IconButton (remplace leur feuille transparente / survol)."""
        from settings_store import _coerce_corner_radius, _coerce_side_enabled
        bg = resolve_color_ref(settings.get("navtool_bg_color"), "#00000000")
        hover = resolve_color_ref(settings.get("navtool_hover_bg_color") or "@hover", C["hover"])
        enabled = _coerce_side_enabled(settings.get("navtool_border_enabled"), False)
        raw = settings.get("navtool_border")
        colors = {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, C["border"])
                  for s in ("top", "right", "bottom", "left")}
        try:
            thickness = max(0, int(settings.get("navtool_border_thickness", 1))) if any(enabled.values()) else 0
        except (TypeError, ValueError):
            thickness = 0
        radius = {k: scaled(v, 0) for k, v in _coerce_corner_radius(settings.get("navtool_corner_radius", 0)).items()}
        for btn in getattr(self, "_tool_buttons", ()):
            if hasattr(btn, "set_frame_style"):
                btn.set_frame_style(bg, enabled, colors, thickness, radius)
                btn.set_hover_bg(hover)
        # Boutons de la fenetre : meme habillage, cles de fm_theme `navbar_winbtn_*`.
        frame = self._frame_look(settings, "navbar_winbtn")
        # Fermer : son propre fond au survol (fm_theme > Barre de navigation > Boutons fenetre, 2026-11-08).
        close_hover = resolve_color_ref(settings.get("navbar_winbtn_close_hover_bg_color") or "#c42b1c", "#c42b1c")
        for btn in self._window_buttons():
            btn.set_frame_style(*frame[:5])
            btn.set_hover_bg(close_hover if btn is self.btn_close else frame[5])

    def _window_buttons(self) -> tuple:
        """Punaise, reduire, agrandir, fermer (fm_theme > Barre de navigation > Boutons fenetre)."""
        return tuple(b for b in (getattr(self, n, None) for n in ("btn_pin", "btn_min", "btn_max", "btn_close"))
                     if b is not None)

    def style_group_button(self, button):
        """Bouton d'un cadre de module (Visionneuse, Board, Vidéo...) : MEME taille et meme padding que les icones de
        la barre (`navtool_icon_size`, `navtool_padding`), habillage de Reglages > Barre de navigation > Cadre des
        modules (cles `viewer_group_btn_*` : fond, couleur de base des icones, bordures, border radius ; demande de
        l'utilisateur, 2026-11-08). Un bouton rendu a la colonne Focus reprend son habillage : `release_group_button`."""
        settings = ui_state.APPLIED_SETTINGS or {}
        side, _margin, padding = nav_tool_metrics(settings, self._row_height())
        if not hasattr(button, "_group_home_colors"):
            button._group_home_colors = (button._color, button._hover_color)
        button.setFixedSize(side, side)
        button.set_margins(0, 0, 0, 0)
        button.set_padding(padding["left"], padding["top"], padding["right"], padding["bottom"])
        frame = self._frame_look(settings, "viewer_group_btn")
        button.set_frame_style(*frame[:5])
        if getattr(button, "_kind", None) == "close":       # fermer le module : survol rouge (2026-11-08)
            hover = resolve_color_ref(settings.get("viewer_group_btn_close_hover_bg_color"), "#c42b1c")
        else:
            hover = resolve_color_ref(settings.get("navtool_hover_bg_color") or "@hover", C["hover"])
        button.set_hover_bg(hover)
        button.set_colors(resolve_color_ref(settings.get("viewer_group_btn_icon_color"), "#c4cacf"),
                          button._group_home_colors[1])

    @staticmethod
    def release_group_button(button):
        """Bouton sorti d'un cadre de module (colonne Focus) : couleurs, padding et survol d'avant (la taille et le
        cadre sont reposes par `style_focus_button`)."""
        colors = getattr(button, "_group_home_colors", None)
        if colors is None:
            return
        del button._group_home_colors
        button.set_colors(*colors)
        button.set_padding(0, 0, 0, 0)
        button.set_hover_bg(None)

    def restyle_module_groups(self):
        """Reglages > Barre de navigation > Cadre des modules, ou taille des icones : cadres visibles rhabilles et
        reposes (quelques boutons, seulement a un changement de reglage)."""
        owner = self._window
        for attr, layout in (("_viewer_group", "_layout_viewer_buttons"), ("_editor_group", "_layout_md_buttons"),
                             ("_board_group", "_layout_board_buttons"), ("_video_group", "_layout_video_buttons"),
                             ("_font_group", "_layout_font_buttons"), ("_pdf_group", "_layout_pdf_buttons"),
                             ("_agenda_group", "_layout_agenda_buttons"),
                             ("_taches_group", "_layout_taches_buttons"),
                             ("_audio_group", "_layout_sound_buttons"), ("_music_group", "_layout_sound_buttons")):
            group = getattr(self, attr, None)
            if group is None:
                continue
            group.restyle()
            if not group.isHidden() and hasattr(owner, layout):
                getattr(owner, layout)()

    @staticmethod
    def _frame_look(settings: dict, prefix: str) -> tuple:
        """(fond, cotes, couleurs, epaisseur, rayons, fond au survol) d'un cadre peint `<prefix>_*`."""
        from settings_store import _coerce_corner_radius, _coerce_side_enabled
        enabled = _coerce_side_enabled(settings.get(f"{prefix}_border_enabled"), False)
        raw = settings.get(f"{prefix}_border")
        colors = {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, C["border"])
                  for s in ("top", "right", "bottom", "left")}
        try:
            thickness = max(0, int(settings.get(f"{prefix}_border_thickness", 1))) if any(enabled.values()) else 0
        except (TypeError, ValueError):
            thickness = 0
        radius = {k: scaled(v, 0) for k, v in _coerce_corner_radius(settings.get(f"{prefix}_corner_radius", 0)).items()}
        return (resolve_color_ref(settings.get(f"{prefix}_bg_color"), "#00000000"), enabled, colors, thickness, radius,
                resolve_color_ref(settings.get(f"{prefix}_hover_bg_color") or "@hover", C["hover"]))

    def _make_button(self, kind: str, slot) -> IconButton:
        btn = IconButton(kind, C["label"], C["text"])
        btn.setFixedSize(scaled(26), scaled(TITLEBAR_HEIGHT))
        btn.setCursor(Qt.ArrowCursor)
        btn.setFlat(True)
        btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent; border: none;"
            "}"
            "QPushButton:hover {"
            f"  background: {C['hover']};"
            "}"
        )
        btn.clicked.connect(slot)
        return btn

    def contextMenuEvent(self, event):
        """Clic droit sur la barre : « Toujours au-dessus » (demande de l'utilisateur : plus d'espaces ici)."""
        from settings_widgets import Menu
        from fm_theme.style import always_on_top
        menu = Menu(self)
        action = menu.addAction("Toujours au-dessus")
        action.setCheckable(True)
        action.setChecked(always_on_top(self))
        action.triggered.connect(lambda checked: self.set_always_on_top(checked))
        menu.exec(event.globalPos())
        event.accept()

    def _toggle_always_on_top(self):
        from fm_theme.style import always_on_top
        self.set_always_on_top(not always_on_top(self))

    def _sync_pin(self, on: bool = False):
        """Punaise allumee (couleur d'accent) quand la fenetre reste au premier plan, attenuee sinon."""
        color = C["accent"] if on else C["label"]
        self.btn_pin.set_colors(color, color if on else C["text"])
        self.btn_pin.set_icon_tint(C["accent"] if on else None)
        self.btn_pin.setToolTip("Toujours au premier plan : cliquer pour libérer" if on
                                else "Garder la fenêtre au premier plan")

    def set_always_on_top(self, on: bool, save: bool = True):
        from fm_theme.style import set_always_on_top
        set_always_on_top(self, on)
        self._sync_pin(bool(on))
        if save:
            from settings_store import save_live_state
            save_live_state("window_always_on_top", bool(on))
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS["window_always_on_top"] = bool(on)

    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_max()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Voir app_style.start_native_move : SendMessage synchrone
            # plutot que QWindow.startSystemMove() (qui POSTE son SC_MOVE,
            # asynchrone) — evite que la fenetre "rate" le debut du glisser
            # si d'autres evenements souris arrivent avant que Windows ne
            # traite ce message en file.
            start_native_move(self._window)
            event.accept()
        else:
            super().mousePressEvent(event)

# ==========================================================================
# Deplacement temporaire des elements de l'interface
