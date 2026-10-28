"""Barre de titre / barre de navigation (TitleBar), cheminement (puces), cadre « Visionneuse ».

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

from app_style import C, resolve_color_ref, role_color, role_font, font, scaled, start_native_move
from previews import UI_ICON_APP_LOGO, custom_ui_icon_pixmap
from settings_store import DEFAULT_SETTINGS
from settings_widgets import shadow_look
from browser_core import TITLEBAR_HEIGHT, _resolve_font_family
from preview_column import IconButton
import ui_state
import previews as _previews

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pipeline_browser import PipelineBrowser      # annotations seulement (pipeline_browser importe ce module)


_CRUMB_LOOK_CACHE: list = [None, None]       # [reglages appliques, habillage] : un calcul par jeu de reglages


def _crumb_look() -> dict:
    """Habillage du cheminement (Reglages > Barre de navigation > Cheminement, cles `crumb_*`) : police, espacement,
    separateur, fonds (set / apres set), bordures, rayon, padding, ombre. Calcule une fois par jeu de reglages
    appliques (il est relu a chaque redimensionnement et a chaque cran d'un curseur)."""
    applied = ui_state.APPLIED_SETTINGS
    if _CRUMB_LOOK_CACHE[0] is applied and _CRUMB_LOOK_CACHE[1] is not None:
        return _CRUMB_LOOK_CACHE[1]
    look = _build_crumb_look()
    _CRUMB_LOOK_CACHE[0], _CRUMB_LOOK_CACHE[1] = applied, look
    return look


def _build_crumb_look() -> dict:
    """Habillage du cheminement. Un habillage par ETAT de repere (`look["states"]`) : « set » (cles `crumb_*`),
    « after » (`crumb_after_*`), « after_focus » (`crumb_afterfocus_*`) ; dans les deux derniers, une ligne dont le
    toggle d'override (`<prefixe>_ovr_<ligne>`) est eteint reprend celle du Set. Survol / focus : fond et bordures
    par-dessus (`look["hover"]`, `look["focus"]`)."""
    from settings_store import _coerce_corner_radius, _coerce_side_enabled
    values = dict(DEFAULT_SETTINGS)
    values.update(ui_state.APPLIED_SETTINGS or {})
    sides = ("top", "right", "bottom", "left")

    def number(key, default, low=0, high=999):
        try:
            return max(low, min(high, int(values.get(key, default))))
        except (TypeError, ValueError):
            return default

    def fill(key):
        color = QColor(resolve_color_ref(values.get(key), "#00000000"))
        return color if color.alpha() else None

    def border(pre):
        raw = values.get(f"{pre}_border")
        colors = {s: resolve_color_ref(raw.get(s) if isinstance(raw, dict) else raw, "#303539") for s in sides}
        enabled = _coerce_side_enabled(values.get(f"{pre}_border_enabled"), False)
        thickness = number(f"{pre}_border_thickness", 1, 0, 20) if any(enabled.values()) else 0
        return enabled, colors, thickness

    def box(key):
        raw = values.get(key)
        raw = raw if isinstance(raw, dict) else {}
        return {s: max(0, int(raw.get(s, 0) or 0)) for s in ("left", "top", "right", "bottom")}

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
        color = QColor(resolve_color_ref(values.get(f"{pre}_font_color"), role_color("info", C["text_mono"])))
        return result, color, family, size

    def state(pre, bg_key):
        crumb_font, color, _family, _size = text_font(pre)
        enabled, colors, thickness = border(pre)
        return {"font": crumb_font, "color": color, "bg": fill(bg_key),
                "border_on": enabled, "border_colors": colors, "thickness": thickness,
                "radius": _coerce_corner_radius(values.get(f"{pre}_corner_radius", 0)),
                "padding": box(f"{pre}_padding"), "margin": box(f"{pre}_margin"),
                "shadow": shadow_look(values, f"{pre}_shadow", resolve_color_ref)}

    base = state("crumb", "crumb_set_bg_color")
    rows = {"font": ("font", "color"), "bg": ("bg",), "border": ("border_on", "border_colors", "thickness"),
            "radius": ("radius",), "padding": ("padding",), "margin": ("margin",), "shadow": ("shadow",)}
    states = {"set": base}
    for name, pre, bg_key in (("after", "crumb_after", "crumb_after_bg_color"),
                              ("after_focus", "crumb_afterfocus", "crumb_afterfocus_bg_color")):
        own = state(pre, bg_key)
        merged = dict(base)
        for row, fields in rows.items():
            if values.get(f"{pre}_ovr_{row}"):
                merged.update({f: own[f] for f in fields})
        states[name] = merged

    def overlay(pre):
        enabled, colors, thickness = border(pre)
        return {"bg": fill(f"{pre}_bg_color"), "border_on": enabled, "border_colors": colors,
                "thickness": thickness}

    _crumb_font, _color, family, size = text_font("crumb")
    # Separateur : sa propre police ; famille vide = celle des textes, taille 0 = celle des textes.
    sep_size = number("crumb_sep_font_size", 0, 0, 80) or size
    sep_weight = 700 if values.get("crumb_sep_font_bold") else 500
    sep_family = (values.get("crumb_sep_font_family") or "").strip()
    if not sep_family or sep_family == "Systeme":
        sep_family = family if family and family != "Systeme" else ""
    if sep_family:
        sep_font = font(sep_size, sep_weight, family=_resolve_font_family(sep_family, sep_size, sep_weight),
                        italic=bool(values.get("crumb_sep_font_italic")))
    else:
        sep_font = role_font("info", sep_size, sep_weight)
        sep_font.setItalic(bool(values.get("crumb_sep_font_italic")))
    return {
        **base,                                           # habillage du Set (anciens appels)
        "states": states, "hover": overlay("crumb_hover"), "focus": overlay("crumb_focus"),
        "set_bg": base["bg"], "after_bg": states["after"]["bg"],
        "sep_font": sep_font,
        "sep_color": QColor(resolve_color_ref(values.get("crumb_sep_font_color"), C["dim"])),
        "spacing": number("crumb_spacing", 5, 0, 80),
        "separators": bool(values.get("crumb_separator_enabled", True)),
        "separator_icon": values.get("crumb_separator_kind") == "icon",
        "separator_char": str(values.get("crumb_separator_char") or "›"),
        "signature": repr({k: v for k, v in values.items() if k.startswith("crumb_")}) + repr(values.get("colors")),
    }


def _crumb_state(kind: str) -> tuple:
    """Genre d'un repere -> (etat, focus) : « set », « after », « after_focus » ; suffixe « ! » = le repere qui a
    le focus."""
    return kind.rstrip("!"), kind.endswith("!")


class _CrumbChip(QWidget):
    """Un repere du cheminement : habillage de son etat (Set / Apres set / Apres focus), fond et bordures du focus
    et du survol par-dessus (border radius de l'etat), ombre, texte ; cliquer = focus sur l'element de sa colonne."""

    clicked = Signal()

    def __init__(self, text: str, kind: str, look: dict, parent=None):
        super().__init__(parent)
        self._kind, self._look = kind, look
        self._full_text = text                    # aucune info-bulle au survol (demande de l'utilisateur)
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.set_look(look, kind)

    def set_look(self, look: dict, kind: str):
        """(Re)pose l'habillage, la taille et le texte : mise a jour SUR PLACE, sans recreer la puce."""
        self._kind, self._look = kind, look
        state, self._focus = _crumb_state(kind)
        self._st = st = (look.get("states") or {}).get(state) or look
        metrics = QFontMetrics(st["font"])
        self._text = metrics.elidedText(self._full_text, Qt.ElideMiddle, scaled(220, 0))
        pad, t = st["padding"], st["thickness"]
        on = st["border_on"]
        self._edge = {"left": pad["left"] + (t if on["left"] else 0), "right": pad["right"] + (t if on["right"] else 0),
                      "top": pad["top"] + (t if on["top"] else 0), "bottom": pad["bottom"] + (t if on["bottom"] else 0)}
        self._margin = st["shadow"]["size"] if st["shadow"] else 0
        out = {s: self._margin + st["margin"][s] for s in ("left", "top", "right", "bottom")}   # ombre + margin
        self._out = out
        width = metrics.horizontalAdvance(self._text) + self._edge["left"] + self._edge["right"]
        height = metrics.height() + self._edge["top"] + self._edge["bottom"]
        self.setFixedSize(width + out["left"] + out["right"], height + out["top"] + out["bottom"])
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        from settings_widgets import _paint_bordered_vector, paint_shadow
        st = self._st
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        o = self._out
        box = self.rect().adjusted(o["left"], o["top"], -o["right"], -o["bottom"])
        if st["shadow"] is not None:
            paint_shadow(painter, QRectF(box), st["radius"], st["shadow"])
        fill, border_on, colors, thickness = st["bg"], st["border_on"], st["border_colors"], st["thickness"]
        for active, extra in ((self._focus, self._look.get("focus")), (self._hover, self._look.get("hover"))):
            if active and extra:                       # focus puis survol, par-dessus l'etat du repere
                if extra["bg"] is not None:
                    fill = extra["bg"]
                if extra["thickness"]:
                    border_on, colors, thickness = extra["border_on"], extra["border_colors"], extra["thickness"]
        if fill is not None or thickness:
            _paint_bordered_vector(painter, box, st["radius"], border_on, thickness,
                                   colors, fill.name(QColor.NameFormat.HexArgb) if fill else None)
        painter.setFont(st["font"])
        painter.setPen(st["color"])
        inner = box.adjusted(self._edge["left"], self._edge["top"], -self._edge["right"], -self._edge["bottom"])
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
        return QFontMetrics(self.look["font"]).horizontalAdvance(self.LABEL)

    def content_origin(self) -> QPoint:
        """Ou commence le premier bouton (apres le libelle)."""
        return QPoint(self._edges()["left"] + self.label_width() + scaled(8, 0), self._edges()["top"])

    def fit(self, content_right: int, content_height: int):
        """Taille du cadre pour des boutons qui finissent a `content_right` (coordonnees du cadre)."""
        edges = self._edges()
        height = max(content_height, QFontMetrics(self.look["font"]).height()) + edges["top"] + edges["bottom"]
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
        layout.addWidget(self.btn_min, alignment=Qt.AlignTop)
        layout.addWidget(self.btn_max, alignment=Qt.AlignTop)
        layout.addWidget(self.btn_close, alignment=Qt.AlignTop)

    def _crumb_row_height(self) -> int:
        """Hauteur de la rangee du cheminement : un repere (police + padding + bordures + marge de l'ombre)."""
        look = _crumb_look()
        height = 0
        for st in (look.get("states") or {"set": look}).values():     # le plus haut des etats (Set, Apres...)
            pad, t, on = st["padding"], st["thickness"], st["border_on"]
            margin = st["shadow"]["size"] if st["shadow"] else 0
            height = max(height, QFontMetrics(st["font"]).height() + pad["top"] + pad["bottom"]
                         + (t if on["top"] else 0) + (t if on["bottom"] else 0) + 2 * margin
                         + st["margin"]["top"] + st["margin"]["bottom"])
        return max(scaled(14, 0), height, QFontMetrics(look["sep_font"]).height())

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
        separators = (look.get("separators", True), look["separator_icon"])
        structure = (names, [kind for kind, _n, _c in items], separators)
        previous = getattr(self, "_crumb_structure", None)
        self._crumb_key = key
        self._crumb_items = items
        self._crumb_names = names
        if not force and structure == previous and self._crumb_layout.count():
            self._restyle_crumbs(look)                       # memes reperes : seulement l'habillage change
            return
        kinds = [kind for kind, _n, _c in items]
        if (not force and previous is not None and self._crumb_layout.count()
                and len(previous[1]) == len(kinds) and previous[2] == separators):
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
        separator_icon = None
        if look["separator_icon"]:
            import previews as _previews
            separator_icon = custom_ui_icon_pixmap(_previews.UI_ICON_NAVBAR_CRUMB_SEPARATOR,
                                                   QFontMetrics(look["sep_font"]).height())
        for index, (kind, name, callback) in enumerate(items):
            if index and separators[0]:                    # separateurs coupes : aucun (colonne « Activer »)
                sep = QLabel()
                sep.setAlignment(Qt.AlignCenter)
                if separator_icon is not None:
                    sep.setPixmap(separator_icon)
                else:
                    sep.setText(look["separator_char"])
                    sep.setFont(look["sep_font"])         # sa police (par defaut celle des textes)
                sep.setStyleSheet(f"color: {look['sep_color'].name(QColor.NameFormat.HexArgb)}; "
                                  "background: transparent;")
                self._crumb_layout.addWidget(sep)
            chip = _CrumbChip(name, kind, look)
            # Le rappel est relu au clic dans `_crumb_items` : les reperes sont gardes d'un rafraichissement a
            # l'autre (mise a jour sur place) alors que les colonnes, elles, sont recreees.
            chip.clicked.connect(lambda i=index: self._crumb_click(i))
            self._crumb_layout.addWidget(chip)
        self._crumb_layout.addStretch(1)
        self.refresh_sizes()

    def _crumb_click(self, index: int):
        items = getattr(self, "_crumb_items", None) or []
        if 0 <= index < len(items):
            items[index][2]()

    def _restyle_crumbs(self, look: dict):
        """Habillage change, reperes inchanges : puces et separateurs mis a jour sur place (aucun widget recree)."""
        self._crumb_layout.setSpacing(look["spacing"])
        kinds = iter([kind for kind, _n, _c in self._crumb_items])
        separator_icon = None
        if look["separator_icon"]:
            import previews as _previews
            separator_icon = custom_ui_icon_pixmap(_previews.UI_ICON_NAVBAR_CRUMB_SEPARATOR,
                                                   QFontMetrics(look["sep_font"]).height())
        for index in range(self._crumb_layout.count()):
            widget = self._crumb_layout.itemAt(index).widget()
            if isinstance(widget, _CrumbChip):
                widget.set_look(look, next(kinds))
            elif isinstance(widget, QLabel):
                if separator_icon is not None:
                    widget.setPixmap(separator_icon)
                else:
                    widget.setText(look["separator_char"])
                    widget.setFont(look["sep_font"])
                widget.setStyleSheet(f"color: {look['sep_color'].name(QColor.NameFormat.HexArgb)}; "
                                     "background: transparent;")
        self.refresh_sizes()

    def refresh_crumbs(self):
        """Reglages changes : repose les reperes seulement si leur habillage a change."""
        if getattr(self, "_crumb_items", None) is not None:
            self.set_crumbs(self._crumb_items)

    def _place_crumbs(self):
        left = scaled(10, 0)
        top = scaled(TITLEBAR_HEIGHT, 0)
        reserved = scaled(26 * 3, 0)                      # reduire / agrandir / fermer restent libres
        self.crumbs.setGeometry(left, top, max(0, self.width() - left - reserved),
                                min(self._crumb_row_height(), max(0, self.height() - top)))
        self.crumbs.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_crumbs()
        self.place_viewer_group()
        self._place_load_bar()

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

    def place_viewer_group(self):
        """Cadres « Visionneuse » / « Éditeur » / « Board » / « Vidéo » : a la suite des outils (apres
        le dernier bouton de la barre), centres dans la hauteur de la rangee des outils, decales de leur margin."""
        for group in (getattr(self, "_viewer_group", None), getattr(self, "_editor_group", None),
                      getattr(self, "_board_group", None), getattr(self, "_video_group", None)):
            if group is not None and not group.isHidden():
                self._place_group(group)

    def _place_group(self, group):
        tools = getattr(self, "_tool_buttons", None)
        anchor = tools[-1] if tools else self.title_label
        margin = group.look["margin"]
        row = scaled(TITLEBAR_HEIGHT, 0)
        x = anchor.geometry().right() + 1 + margin["left"]
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
        row.addWidget(root_field, alignment=Qt.AlignVCenter)
        row.addWidget(browse, alignment=Qt.AlignVCenter)
        picker.layout().setContentsMargins(scaled(5, 0), 0, 0, 0)   # + 9 = 14 apres Parcourir
        for holder in self._tool_boxes:                  # meme hauteur qu'un bouton : champs centres dessus
            holder.setFixedHeight(scaled(TITLEBAR_HEIGHT))
            holder.setObjectName("NavHolder")            # fond de la barre, pas le gris du « QWidget » de l'appli
            holder.setStyleSheet("#NavHolder { background: transparent; }")
        position = 2                                     # apres l'icone et le titre
        for widget in (box, picker, presets, settings, collapse, *modes):
            layout.insertWidget(position, widget, alignment=Qt.AlignTop)
            position += 1

    def refresh_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) a la
        hauteur de la barre et a ses boutons — construits une seule fois
        (contrairement aux colonnes, jamais reconstruits), donc sans cela le
        slider d'echelle ne les affecterait qu'au prochain lancement."""
        settings = ui_state.APPLIED_SETTINGS or {}
        self.setFixedHeight(max(scaled(TITLEBAR_HEIGHT, 0) + self._crumb_row_height(),
                                scaled(int(settings.get("navbar_height", TITLEBAR_HEIGHT)))))
        self._place_crumbs()
        self._icon.setFixedSize(scaled(9), scaled(9))
        self._icon_holder.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        self.title_label.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        for holder in getattr(self, "_tool_boxes", ()):
            holder.setFixedHeight(scaled(TITLEBAR_HEIGHT))
        for btn in (self.btn_min, self.btn_max, self.btn_close, *getattr(self, "_tool_buttons", ())):
            btn.setFixedSize(scaled(26), scaled(TITLEBAR_HEIGHT))

    def refresh_look(self):
        settings = ui_state.APPLIED_SETTINGS or {}
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
        self.setStyleSheet(f"#TitleBar {{ background: {C['app_bg']}; "
                           f"border-bottom: {width}px solid {color}; }}")
        size = max(6, int(settings.get("navbar_title_font_size", 11)))
        family = settings.get("navbar_title_font_family") or ""
        if family:
            weight = 700 if settings.get("navbar_title_font_bold") else 400
            title_font = font(size, weight, family=_resolve_font_family(family, size, weight),
                              italic=bool(settings.get("navbar_title_font_italic", False)))
        else:
            title_font = role_font("titles", size, 700 if settings.get("navbar_title_font_bold") else 400,
                                   tracking=0.01)
            title_font.setItalic(bool(settings.get("navbar_title_font_italic", False)))
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(
            f"color: {resolve_color_ref(settings.get('navbar_title_font_color'), role_color('titles', C['label']))}; "
            "background: transparent;")
        custom_logo = custom_ui_icon_pixmap(UI_ICON_APP_LOGO, self._icon.width())
        self._icon.setPixmap(custom_logo or QPixmap())
        self._icon.setStyleSheet("background: transparent;" if custom_logo is not None else
                                 f"border: 1px solid {C['mark_dir_bd']}; background: transparent;")
        for btn in (self.btn_min, self.btn_max, self.btn_close):
            btn.update()
        self.refresh_crumbs()

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
