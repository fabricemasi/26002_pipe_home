import json
import os
import sys
from pathlib import Path
import threading
import time
from PySide6.QtCore import (
    QByteArray, QCoreApplication, QEasingCurve, QEvent, QEventLoop, QObject, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, QSizeF, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QCursor,
    QFontMetrics,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QToolButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    resolve_color_ref,
    PREVIEW_STACK_TITLE,
    STYLESHEET_COLOR_KEYS,
    apply_dwm_frame,
    apply_style,
    auto_collapse_set_columns,
    column_gap,
    build_stylesheet,
    resize_hit_test,
    role_color,
    role_font,
    font,
    scaled,
    start_native_move,
    column_style_for,
)
import config as _config
import ui_state
from config import (
    COLUMN_LABELS,
    RAW_EXTENSIONS,
    PREVIEWABLE_EXTENSIONS,
    RENDERABLE_3D_EXTENSIONS,
    SOFTWARE_COLUMN_LABEL,
)
from previews import (
    UI_ICON_APP_LOGO,
    _IdlePreviewScheduler,
    custom_ui_icon_pixmap,
)
from config import (
    GLOBAL_OMIT_DIR_NAMES,
    GLOBAL_OMIT_FILE_EXTENSIONS,
    GLOBAL_OMIT_FILE_NAMES,
)
from settings_store import (
    DEFAULT_SETTINGS,
    load_settings,
    save_live_state,
    save_settings,
)
from settings_widgets import (
    Menu, shadow_look, TOGGLE_STYLE_LISTENERS, _Toggle, make_space_actions, set_space_above, set_space_below,
    space_target, widget_at_path, widget_path,
)
from browser_core import (
    COLUMN_SETTINGS,
    DEFAULT_WORK_DIR_TYPE,
    GROUP_COLUMN_DEFAULT_HEIGHT,
    GROUP_COLUMN_MAX_HEIGHT,
    GROUP_COLUMN_MIN_HEIGHT,
    ROLE_ISDIR,
    ROLE_MEDIA_COUNTS,
    ROLE_PATH,
    ROLE_SOURCE_LABEL,
    STATUS_FOLDERS,
    STATUS_HEIGHT,
    TITLEBAR_HEIGHT,
    WORK_DIR_TYPES,
    _WIDGET_SIZE_MAX,
    _hide_resize_width,
    _is_globally_omitted_path,
    _named_subdir,
    _show_resize_width,
    _update_layout_setting,
    apply_all_settings,
    _resolve_font_family,
    col_width,
    load_layout_settings,
    load_project_columns,
    open_in_file_manager,
    open_path,
    project_thumbnail_pixmap,
    status_folder_state,
)
from column import (
    Column,
    _FOCUS_LEVEL_LABEL,
)
from detail_panel import (
    DetailPanel,
    load_window_state,
    save_window_state,
)
from preview_column import (
    PureRefImagesTask,
    _PUR_EXPORT_POOL,
    pur_image_files,
    IconButton,
    style_focus_button,
    PreviewColumn,
)
from previews import (
    migrate_cache_names,
)
from browser_core import (
    _FadeOverlay,
)
from focus import (
    FilterChips, FocusFilmstrip, FocusGallery, FocusImageLoader, FocusInfoPanel, FocusOverlay, filter_window, fit_rect,
    placeholder_pixmap,
)
import file_attributes
import file_filters
from focus import thumbnail as focus_thumbnail
import focus as _focus
from config import (
    PUR_PREVIEW_EXTENSIONS,
)
import previews as _previews
import software_launch
import shiboken6
from interface_edit_targets import PaintedTarget


def _anim_running(overlay) -> bool:
    """Overlay d'animation (fondu, glissement) reellement en cours. Un overlay
    detruit sans etre alle au bout (objet Qt supprime) ne compte pas : sinon
    son drapeau `running` reste vrai et bloque toutes les animations suivantes."""
    return overlay is not None and overlay.running and shiboken6.isValid(overlay)
from browser_core import (
    _SlideOverlay,
    DETAIL_PANEL_MIN_WIDTH,
)
from browser_core import (
    _HoverPrime,
    entry_is_dir,
)
from previews import (
    sweep_preview_cache_if_due,
)


# ==========================================================================
# Barre de titre intrinseque : la fenetre principale est sans decoration
# systeme (voir PipelineBrowser.__init__), donc cette barre en tient lieu —
# deplacement, reduction/agrandissement/fermeture — avec le meme habillage
# sombre que le reste de l'appli plutot que le chrome blanc/bleu de Windows.
# ==========================================================================

def _set_qss(widget, qss: str) -> None:
    """setStyleSheet seulement si la feuille change : sur un conteneur qui
    porte toute la fenetre, Qt repolit tous les descendants meme pour un
    texte identique (~7 ms par appel, rejoue a chaque cran de slider)."""
    if widget.styleSheet() != qss:
        widget.setStyleSheet(qss)


class _MouseBackFilter(QObject):
    """Bouton « precedent » : de l'image en focus vers les diapositives, puis vers les colonnes."""

    def __init__(self, browser: "PipelineBrowser"):
        super().__init__(browser)
        self._browser = browser

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            return False
        if event.button() != Qt.BackButton or not self._browser._project_columns_hidden:
            return False
        if not (watched.isWidgetType() and watched.window() is self._browser):
            return False
        if kind == QEvent.MouseButtonPress:
            if self._browser._viewer_active():
                self._browser._open_focus_gallery()
            elif self._browser._focus_gallery is not None:
                self._browser._set_columns_hidden(False)
        return True                       # avale aussi le relachement (rien d'autre ne le voit)


class _AppInputWatch(QObject):
    """Filtre d'application pose SEULEMENT pendant le chargement des reglages sur inactivite : le premier geste
    reel (evenement spontane : clavier, souris, molette) sur l'appli l'arrete aussitot."""

    def __init__(self, kinds, on_input):
        super().__init__()
        self._kinds, self._on_input = kinds, on_input

    def eventFilter(self, watched, event):
        if event.type() in self._kinds and event.spontaneous():
            self._on_input()
        return False



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
            import mdeditor.pane as md_pane
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

class _InterfaceMoveFrame(QFrame):
    """Cadre visuel d'un widget retenu par le mode de déplacement global."""

    def __init__(self, parent, mode=None, debug=False):
        super().__init__(parent)
        self.mode = mode
        self.debug = debug
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, event):
        if self.mode is None:
            return
        mode = self.mode
        prefix = "debug" if self.debug else "selection"
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        background = mode.debug_background if self.debug else mode.selection_background
        radius = max(0, getattr(mode, f"{prefix}_radius"))
        sides = getattr(mode, f"{prefix}_border_enabled")
        colors = getattr(mode, f"{prefix}_border_colors")
        thickness = max(0, int(getattr(mode, f"{prefix}_border_width")))
        bounds = QRectF(self.rect()).adjusted(thickness / 2, thickness / 2,
                                               -thickness / 2, -thickness / 2)
        path = QPainterPath()
        path.addRoundedRect(bounds, radius, radius)
        painter.fillPath(path, background)
        if thickness:
            edge_colors = {side: QColor(resolve_color_ref(colors.get(side, ""),
                                                           mode._color_css(getattr(mode, f"{prefix}_border"))))
                           for side in ("top", "right", "bottom", "left")}
            active_colors = [edge_colors[side].rgba() for side in edge_colors if sides.get(side)]
            if (all(sides.get(side) for side in edge_colors) and active_colors
                    and len(set(active_colors)) == 1):
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(edge_colors["top"], thickness))
                painter.drawPath(path)
                painter.end()
                return
            left, top, right, bottom = bounds.left(), bounds.top(), bounds.right(), bounds.bottom()
            horizontal_start = min(right, left + radius)
            horizontal_end = max(left, right - radius)
            vertical_start = min(bottom, top + radius)
            vertical_end = max(top, bottom - radius)
            edges = (
                ("top", QPointF(horizontal_start, top), QPointF(horizontal_end, top)),
                ("right", QPointF(right, vertical_start), QPointF(right, vertical_end)),
                ("bottom", QPointF(horizontal_end, bottom), QPointF(horizontal_start, bottom)),
                ("left", QPointF(left, vertical_end), QPointF(left, vertical_start)),
            )
            for side, start, end in edges:
                if not sides.get(side):
                    continue
                pen = QPen(edge_colors[side], thickness)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawLine(start, end)
        painter.end()


class _InterfaceObjectStore:
    """Magasin d'objets libres pour les mises en page hors tableaux de réglages."""

    def __init__(self, mode, window):
        self.mode = mode
        self.window = window
        self.objects = {}
        self.hosts = {}

    def set_object(self, key, rec):
        from settings_cells import set_host_object
        host_key, _sep, path = key.partition("|")
        host = self.hosts.get(host_key)
        if host is None or not path:
            self.objects.pop(key, None)
            return
        set_host_object(self, host, key, path, rec)
        persist_key = f"@free|{self.mode._window_key(self.window)}|{host_key}|{path}"
        if rec and any(rec):
            self.mode.position_overrides[persist_key] = {"object": list(self.objects.get(key, rec))}
        else:
            self.mode.position_overrides.pop(persist_key, None)

    def commit(self):
        self.mode._flush_positions()

    def owner_window(self):
        return self.window

    def snap_rows(self):
        return []


class _InterfaceMoveMode(QObject):
    """Déplacement temporaire des tableaux de l'interface."""

    _ACTIVATE_MODIFIERS = Qt.ControlModifier
    _EDIT_BORDER_THICKNESS = 5

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.active = False
        self.selected: list[QWidget] = []
        self.frames: dict[QWidget, _InterfaceMoveFrame] = {}
        self.debug_frames: dict[QWidget, _InterfaceMoveFrame] = {}
        self.undo_stack: list[dict[QWidget, QPoint]] = []
        self.original_positions: dict[QWidget, QPoint] = {}
        self.modified: set[QWidget] = set()
        self.text_modified: set[QWidget] = set()
        initial_settings = load_settings()
        saved_positions = initial_settings.get("interface_move_positions") or {}
        self.position_overrides = dict(saved_positions) if isinstance(saved_positions, dict) else {}
        self.selection_border = QColor(255, 0, 0, 128)
        self.selection_border_enabled = {side: True for side in ("top", "right", "bottom", "left")}
        self.selection_border_colors = {side: "#80ff0000" for side in ("top", "right", "bottom", "left")}
        self.selection_background = QColor(255, 0, 0, 31)
        self.debug_border = QColor(255, 190, 0, 180)
        self.debug_border_enabled = {side: True for side in ("top", "right", "bottom", "left")}
        self.debug_border_colors = {side: "#b4ffbe00" for side in ("top", "right", "bottom", "left")}
        self.debug_background = QColor(255, 190, 0, 40)
        self.selection_border_width = 2
        self.debug_border_width = 2
        self.selection_radius = 0
        self.debug_radius = 0
        self.editable_windows: set[QWidget] = set()
        self._load_edit_appearance(initial_settings.get("interface_edit_appearance") or {})
        self.debug_enabled = False
        self.window_frames = {}
        self.painted_targets = {}
        self.object_stores = {}
        self.pending_refinement = None
        self.last_click_pos = None
        self.selection_depth = 0
        self.press_global = None
        self.press_positions: dict[QWidget, QPoint] = {}
        self.press_widget_positions: dict[QWidget, QPoint] = {}
        self.press_widget_states: dict[QWidget, dict] = {}
        self.dragging = False
        self.drag_mode = "move"
        self.drag_axis = None
        self.drag_resize = None
        self.toolbar_press = None
        self.toolbar_start_x = 0
        self.toolbar_dragged = False
        self.window_frame = QFrame(browser)
        self.window_frame.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.window_frame.setStyleSheet(
            "QFrame { background: transparent; border: 5px solid rgba(255, 0, 0, 128); }"
        )
        self.window_frame.hide()
        self.edit_toolbar = self._build_toolbar()
        QApplication.instance().installEventFilter(self)
        self._edit_sync = QTimer(self)
        self._edit_sync.setInterval(150)
        self._edit_sync.timeout.connect(self._sync_windows)
        self._edit_sync.start()
        self._position_save_timer = QTimer(self)
        self._position_save_timer.setSingleShot(True)
        self._position_save_timer.setInterval(250)
        self._position_save_timer.timeout.connect(self._flush_positions)
        QApplication.instance().aboutToQuit.connect(self._flush_positions)

    def _eligible_window(self, window):
        if (not isinstance(window, QWidget) or not window.isWindow()
                or window.windowType() in (Qt.Popup, Qt.ToolTip, Qt.SplashScreen)
                or window is getattr(self, "settings_window", None)):
            return False
        return True

    def _editable_window(self, window):
        return self._eligible_window(window) and window in self.editable_windows

    def _visible_target(self, widget):
        return (shiboken6.isValid(widget) and widget.isVisible()
                and not widget.window().isMinimized() and not widget.visibleRegion().isEmpty())

    def _sync_windows(self):
        self.selected[:] = [widget for widget in self.selected if shiboken6.isValid(widget)]
        for widget in list(self.original_positions):
            if not shiboken6.isValid(widget):
                self.original_positions.pop(widget, None)
                self.modified.discard(widget)
        self._restore_visible_positions()
        for target_key, target in list(self.painted_targets.items()):
            if not shiboken6.isValid(target):
                self.painted_targets.pop(target_key, None)
                continue
            rect = getattr(target.view, "_edit_geometry", {}).get(target.key, {}).get(target.part)
            if rect is not None:
                if target in self.original_positions:
                    self.original_positions[target] += rect.topLeft() - target.base.topLeft()
                target.sync(rect)
        for window, frame in list(self.window_frames.items()):
            if not shiboken6.isValid(window):
                self.window_frames.pop(window, None)
            elif shiboken6.isValid(frame):
                frame.setVisible(self.active and window.isVisible() and self._editable_window(window))
        if self.active:
            for window in QApplication.topLevelWidgets():
                if not self._editable_window(window) or not window.isVisible() or window is self.browser:
                    continue
                frame = self.window_frames.get(window)
                if frame is None:
                    frame = QFrame(window)
                    frame.setAttribute(Qt.WA_TransparentForMouseEvents)
                    frame.setStyleSheet(self.window_frame.styleSheet())
                    self.window_frames[window] = frame
                frame.setGeometry(window.rect())
                frame.show()
                frame.raise_()
        if hasattr(self, "secondary_windows_button"):
            self.secondary_windows_button.setEnabled(self.active)
        self._refresh_frames()

    def _restore_visible_positions(self):
        if not self.position_overrides:
            return
        import settings_cells as cells
        for window in QApplication.topLevelWidgets():
            # Toute fenetre eligible, PAS seulement celles du mode edition : `editable_windows` est vide tant qu'on
            # n'est pas entre dans le mode edition, donc les positions enregistrees n'etaient reappliquees qu'a
            # son activation (signale : « au redemarrage la position n'est pas celle modifiee »).
            if not self._eligible_window(window) or not window.isVisible():
                continue
            prefix = self._window_key(window) + "|"
            for key, saved in list(self.position_overrides.items()):
                if key.startswith("@free|"):
                    _tag, owner, host_path, object_path = (key.split("|", 3) + [""])[:4]
                    if owner != self._window_key(window) or not isinstance(saved, dict):
                        continue
                    host = widget_at_path(window, host_path) if host_path else window
                    rec = saved.get("object")
                    if host is None or not isinstance(rec, list) or len(rec) != 4:
                        continue
                    store = self.object_stores.get(window)
                    if store is None:
                        store = self.object_stores[window] = _InterfaceObjectStore(self, window)
                    store.hosts[host_path] = host
                    if getattr(host, "_objects_host", None) is None:
                        host._objects_host = lambda s=store, k=host_path: (s, k)
                    store.set_object(f"{host_path}|{object_path}", rec)
                    target = cells._resolve_object(host, object_path)
                    if target is not None and self._visible_target(target):
                        slot = getattr(target, "_float_slot", None)
                        if slot is not None:
                            self.original_positions.setdefault(target, slot.mapTo(host, QPoint(0, 0)))
                            self.modified.add(target)
                    continue
                if not key.startswith(prefix) or not isinstance(saved, dict):
                    continue
                parts = key[len(prefix):].split("|")
                widget = widget_at_path(window, parts[0])
                if widget is None or not self._visible_target(widget):
                    continue
                if len(parts) == 3:
                    view, item_key, part = widget, parts[1], parts[2]
                    rect = getattr(view, "_edit_geometry", {}).get(item_key, {}).get(part)
                    if rect is None:
                        continue
                    target_key = (view, item_key, part)
                    widget = self.painted_targets.get(target_key)
                    if widget is None or not shiboken6.isValid(widget):
                        widget = self.painted_targets[target_key] = PaintedTarget(view, item_key, part, rect)
                if widget in self.original_positions:
                    continue
                delta = saved.get("offset", [0, 0])
                if isinstance(delta, list) and len(delta) == 2 and all(isinstance(n, int) for n in delta):
                    if isinstance(widget, PaintedTarget):
                        # Decalage ABSOLU depuis la place peinte (`base`), jamais depuis sa position du moment :
                        # rejoue toutes les 150 ms, il s'ajoutait a chaque tour et les compteurs IMG / VID
                        # glissaient vers la gauche jusqu'au bord de la ligne (signale).
                        self.original_positions.setdefault(widget, widget.base.topLeft())
                        widget.move(self._bounded_position(widget, widget.base.topLeft() + QPoint(*delta)))
                        self.modified.add(widget)
                    else:
                        context = self._object_context(widget)
                        if context is not None:
                            state, object_key, host = context
                            state.set_object(object_key, [delta[0], delta[1], 0, 0])
                            state.commit()
                            slot = getattr(widget, "_float_slot", None)
                            if slot is not None:
                                self.original_positions.setdefault(widget, slot.mapTo(host, QPoint(0, 0)))
                                self.modified.add(widget)
                        else:
                            self.original_positions.setdefault(widget, widget.pos())
                            widget.move(self._bounded_position(widget, widget.pos() + QPoint(*delta)))
                            self.modified.add(widget)

    @staticmethod
    def _color_css(color: QColor) -> str:
        return color.name(QColor.HexArgb)

    def _load_edit_appearance(self, saved: dict):
        if not isinstance(saved, dict):
            return
        for prefix, attr in (("selection", "selection"), ("debug", "debug")):
            color = QColor(saved.get(f"{prefix}_background", ""))
            if color.isValid():
                setattr(self, f"{attr}_background", color)
            enabled = saved.get(f"{prefix}_border_enabled")
            if isinstance(enabled, dict):
                setattr(self, f"{attr}_border_enabled", {s: bool(enabled.get(s, False))
                                                          for s in ("top", "right", "bottom", "left")})
            colors = saved.get(f"{prefix}_border_colors")
            if isinstance(colors, dict):
                setattr(self, f"{attr}_border_colors", dict(colors))
            border = QColor(saved.get(f"{prefix}_border", ""))
            if border.isValid():
                setattr(self, f"{attr}_border", border)
            for key, field in (("border_width", "width"), ("radius", "radius")):
                value = saved.get(f"{prefix}_{key}")
                if value is not None:
                    setattr(self, f"{attr}_{field}", max(0, int(value)))

    def _save_edit_appearance(self):
        appearance = {}
        for prefix in ("selection", "debug"):
            appearance.update({
                f"{prefix}_background": self._color_css(getattr(self, f"{prefix}_background")),
                f"{prefix}_border": self._color_css(getattr(self, f"{prefix}_border")),
                f"{prefix}_border_enabled": dict(getattr(self, f"{prefix}_border_enabled")),
                f"{prefix}_border_colors": dict(getattr(self, f"{prefix}_border_colors")),
                f"{prefix}_border_width": int(getattr(self, f"{prefix}_border_width")),
                f"{prefix}_radius": int(getattr(self, f"{prefix}_radius")),
            })
        save_live_state("interface_edit_appearance", appearance)

    def _button(self, text: str, background: str, radius: int = 2) -> QPushButton:
        button = QPushButton(text, self.edit_toolbar)
        button.setFont(role_font("code", 9, 500))
        button.setCursor(Qt.ArrowCursor)
        button.setFixedHeight(scaled(22))
        button.setFixedWidth(scaled(220))
        button.setStyleSheet(
            f"QPushButton {{ color: black; background: {background}; border: none; "
            f"border-radius: {scaled(radius)}px; padding: 0 {scaled(5)}px; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,45); }}"
        )
        return button

    def _build_toolbar(self):
        toolbar = QWidget(self.browser)
        self.edit_toolbar = toolbar
        toolbar.setAttribute(Qt.WA_StyledBackground, True)
        toolbar.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scaled(3))

        main = self._button("paramètres d'édition", "rgba(255, 0, 0, 128)", radius=2)
        main.setObjectName("EditModeButton")
        main.setFont(role_font("code", 8, 500))
        main.setFixedWidth(scaled(220))
        main.setStyleSheet(
            f"QPushButton {{ color: black; background: rgba(255,0,0,128); border: none; "
            f"border-top-left-radius: 0px; border-top-right-radius: 0px; "
            f"border-bottom-left-radius: {scaled(2)}px; border-bottom-right-radius: {scaled(2)}px; "
            f"padding: 0 {scaled(7)}px; }}"
            "QPushButton:hover { background: rgba(255,0,0,175); }"
        )
        self.edit_button = main
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(scaled(3))
        title_row.addWidget(main)
        close = QPushButton("✕", toolbar)
        close.setObjectName("CloseEditModeButton")
        close.setAccessibleName("Fermer le mode édition")
        close.setFixedSize(scaled(22), scaled(22))
        close.setFont(role_font("code", 18, 700))
        close.setCursor(Qt.ArrowCursor)
        close.setStyleSheet(
            f"QPushButton {{ color: white; background: rgba(255,0,0,128); border: none; "
            f"border-radius: {scaled(2)}px; padding: 0px; }}"
            "QPushButton:hover { background: rgba(255,0,0,175); }"
        )
        close.clicked.connect(self._deactivate)
        self.close_edit_button = close
        title_row.addWidget(close)
        layout.addLayout(title_row)

        self.reset_button = self._button("reset objets", "rgba(190, 25, 25, 220)")
        self.reset_all_button = self._button("reset tous", "rgba(190, 25, 25, 220)")
        reset_qss = (
            f"QPushButton {{ color: black; background: rgba(255,0,0,128); border: none; "
            f"border-radius: {scaled(2)}px; padding: 0 {scaled(5)}px; }}"
            "QPushButton:hover { background: rgba(255,0,0,175); }"
            "QPushButton:pressed { background: rgba(255,0,0,96); }"
        )
        self.reset_button.setStyleSheet(reset_qss)
        self.reset_all_button.setStyleSheet(reset_qss)
        self.debug_button = self._button("debug", "rgba(180, 125, 20, 230)")
        self.debug_button.setStyleSheet(
            f"QPushButton {{ color: black; background: rgba(180,125,20,230); border: none; "
            f"border-radius: {scaled(2)}px; padding: 0 {scaled(5)}px; }}"
            "QPushButton:hover { background: rgba(180,125,20,255); }"
            "QPushButton:pressed { background: rgba(180,125,20,190); }"
        )
        self.reset_button.clicked.connect(self._reset_current)
        self.reset_all_button.clicked.connect(self._reset_all)
        self.debug_button.clicked.connect(self._toggle_debug)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.reset_all_button)
        layout.addWidget(self.debug_button)
        self.secondary_windows_button = self._button(
            "fenêtres sup. modifiables", "rgba(64,67,71,255)")
        self.secondary_windows_button.setStyleSheet(
            f"QPushButton {{ color: black; background: rgba(64,67,71,255); border: none; "
            f"border-radius: {scaled(2)}px; padding: 0 {scaled(5)}px; }}"
            "QPushButton:hover { background: rgba(78,81,85,255); }"
        )
        self.secondary_windows_button.clicked.connect(self._include_open_windows)
        layout.addWidget(self.secondary_windows_button)
        self.scope_button = QToolButton(toolbar)
        self.scope_button.setPopupMode(QToolButton.InstantPopup)
        self.scope_button.setFixedSize(scaled(220), scaled(30))
        self.scope_button.setStyleSheet(
            f"QToolButton {{ color: black; background: rgba(64,67,71,255); border: none; "
            f"border-radius: {scaled(2)}px; padding: 2px; }}"
            "QToolButton:hover { background: rgba(78,81,85,255); }"
        )
        self.scope_button.hide()
        layout.addWidget(self.scope_button)
        self.style_buttons = {}
        self.style_button = self._make_style_button(self.browser)
        self.style_buttons[self.browser] = self.style_button
        self.style_button.hide()
        self.style_scope = ("this", "Cet élément seulement")
        self._scope_menu_signature = None
        toolbar.adjustSize()
        toolbar.hide()
        return toolbar

    def _make_style_button(self, parent):
        button = QPushButton("style", parent)
        button.setFont(role_font("code", 8, 500))
        button.setCursor(Qt.ArrowCursor)
        button.setFixedHeight(scaled(16))
        button.setStyleSheet(
            f"QPushButton {{ color: black; background: rgba(255,0,0,180); border: none; "
            f"border-radius: {scaled(2)}px; padding: 0 {scaled(5)}px; }}"
            "QPushButton:hover { background: rgba(255,0,0,230); }"
        )
        button.clicked.connect(self._open_selected_text_style)
        return button

    def _include_open_windows(self):
        if not self.active:
            return
        self.editable_windows.update(
            window for window in QApplication.topLevelWidgets()
            if window.isVisible() and self._eligible_window(window)
        )
        self._sync_text_style_overrides()
        self._sync_windows()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.KeyPress:
            in_browser = watched.isWidgetType() and self._editable_window(watched.window())
            modifiers = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
            if event.key() == Qt.Key_Backslash and modifiers == self._ACTIVATE_MODIFIERS:
                window = watched.window() if watched.isWidgetType() else None
                if (in_browser or (not self.active and self._eligible_window(window))):
                    self._toggle()
                    return True
            if self.active and in_browser and event.key() == Qt.Key_Escape:
                self._deactivate()
                return True
            if self.active and in_browser and event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
                self._undo()
                return True
            if self.active and in_browser and event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
                delta = {
                    Qt.Key_Left: QPoint(-1, 0), Qt.Key_Right: QPoint(1, 0),
                    Qt.Key_Up: QPoint(0, -1), Qt.Key_Down: QPoint(0, 1),
                }[event.key()]
                self._move_selected(delta)
                return True
            return False
        if self.active and kind == QEvent.Resize and watched is self.browser:
            self._refresh_window_frame()
            return False
        if self.active and watched.isWidgetType() and self.edit_toolbar.isAncestorOf(watched):
            if watched is self.edit_button:
                if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                    self.toolbar_press = event.globalPosition().toPoint()
                    self.toolbar_start_x = self.edit_toolbar.x()
                    self.toolbar_dragged = False
                    return True
                if kind == QEvent.MouseMove and self.toolbar_press is not None:
                    delta = event.globalPosition().toPoint() - self.toolbar_press
                    if abs(delta.x()) >= 2:
                        self.toolbar_dragged = True
                    if self.toolbar_dragged:
                        self._move_toolbar_horizontally(self.toolbar_start_x + delta.x())
                    return True
                if kind == QEvent.MouseButtonRelease and self.toolbar_press is not None:
                    was_dragged = self.toolbar_dragged
                    self.toolbar_press = None
                    self.toolbar_dragged = False
                    if not was_dragged:
                        self._open_settings()
                    return True
            return False
        if self.active and watched.isWidgetType() and any(
                watched is button or button.isAncestorOf(watched) for button in self.style_buttons.values()
                if shiboken6.isValid(button)):
            return False
        if not self.active or kind not in {
            QEvent.MouseButtonPress, QEvent.MouseButtonDblClick, QEvent.MouseMove, QEvent.MouseButtonRelease,
        }:
            return False
        if not watched.isWidgetType() or not self._editable_window(watched.window()):
            return False
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            if event.button() == Qt.MiddleButton:
                path = self._selection_path(event.globalPosition().toPoint())
                target = next((item for item in path if item in self.selected), None)
                if target is not None:
                    self._deselect(target)
                self.pending_refinement = None
                return True
            if event.button() != Qt.LeftButton:
                return False
            path = self._selection_path(event.globalPosition().toPoint())
            if not path:
                self._clear_selection()
                return True
            self.pending_refinement = None
            resize_gesture = bool(event.modifiers() & Qt.ControlModifier and event.modifiers() & Qt.ShiftModifier)
            shift = bool(event.modifiers() & Qt.ShiftModifier) and not resize_gesture
            click_pos = event.globalPosition().toPoint()
            same_click = (self.last_click_pos is not None
                          and (click_pos - self.last_click_pos).manhattanLength() <= 3)
            if resize_gesture:
                if path[0] not in self.selected:
                    self._select(path[0])
            elif shift:
                depth = min(self.selection_depth, len(path) - 1)
                target = path[depth]
                if target in self.selected:
                    self._deselect(target)
                else:
                    self._add_selection(target, allow_ancestors=True)
                self.last_click_pos = click_pos
            elif same_click:
                current = next((item for item in path if item in self.selected), None)
                if current is None:
                    self._select(path[0])
                    self.selection_depth = 0
                else:
                    rank = path.index(current)
                    if rank + 1 < len(path):
                        self.pending_refinement = (current, path[rank + 1])
                        self.selection_depth = rank + 1
                    else:
                        self.last_click_pos = click_pos
            else:
                self._select(path[0])
                self.selection_depth = 0
                self.last_click_pos = click_pos
            self.press_global = event.globalPosition().toPoint()
            move_targets = self._movement_scope_targets()
            self.press_positions = {
                widget: widget.mapToGlobal(QPoint(0, 0)) for widget in move_targets
            }
            self.press_widget_positions = {
                widget: widget.pos() for widget in move_targets
            }
            self.press_widget_states = {
                widget: self._snapshot_widget(widget) for widget in move_targets
            }
            modifiers = event.modifiers()
            self.drag_mode = ("resize" if modifiers & Qt.ControlModifier and modifiers & Qt.ShiftModifier
                              else "move")
            self.drag_axis = None
            self.drag_resize = None
            if self.drag_mode == "resize" and len(self.selected) == 1:
                target = self.selected[0]
                context = self._object_context(target)
                if context is not None and not isinstance(target, PaintedTarget):
                    import settings_cells as cells
                    state, key, host = context
                    if getattr(target, "_float_slot", None) is None:
                        cells._float_object(host, target)
                    if getattr(target, "_float_slot", None) is not None:
                        slot = target._float_slot
                        origin = slot.mapTo(host, QPoint(0, 0))
                        rect = QRect(target.geometry())
                        edge = cells._edge_at(target.mapFromGlobal(click_pos), target.width(), target.height())
                        self.drag_resize = {"target": target, "state": state, "key": key, "host": host,
                                            "edge": edge, "rect": rect, "base": origin,
                                            "record": list(getattr(target, "_float_rec", [0, 0, 0, 0]))}
            self.dragging = False
            return True
        if self.press_global is None:
            return False
        current = event.globalPosition().toPoint()
        if kind == QEvent.MouseMove:
            delta = current - self.press_global
            if not self.dragging and delta.manhattanLength() < QApplication.startDragDistance():
                return True
            self.dragging = True
            if self.drag_mode == "resize" and self.drag_resize is not None:
                self._resize_selected(current)
            else:
                if event.modifiers() & Qt.ShiftModifier:
                    if self.drag_axis is None and delta.manhattanLength() >= QApplication.startDragDistance():
                        self.drag_axis = "x" if abs(delta.x()) >= abs(delta.y()) else "y"
                    if self.drag_axis == "x":
                        delta.setY(0)
                    elif self.drag_axis == "y":
                        delta.setX(0)
                else:
                    self.drag_axis = None
                self._move_to_positions(delta, current)
            return True
        self.press_global = None
        self.press_positions = {}
        if self.dragging:
            self._record_undo(self.press_widget_states)
        elif self.pending_refinement is not None:
            self._refine_selection(*self.pending_refinement)
            self.last_click_pos = current
        self.pending_refinement = None
        self.press_widget_positions = {}
        self.press_widget_states = {}
        self.dragging = False
        self.drag_mode = "move"
        self.drag_axis = None
        self.drag_resize = None
        return True

    def _toggle(self):
        if self.active:
            self._deactivate()
            return
        self.editable_windows = {
            window for window in QApplication.topLevelWidgets()
            if window.isVisible() and self._eligible_window(window)
        }
        self.active = True
        self.browser.setCursor(Qt.CrossCursor)
        self._refresh_window_frame()
        self._position_toolbar()
        self.edit_toolbar.show()
        self.edit_toolbar.raise_()
        self._sync_windows()
        self.window_frame.show()
        self.window_frame.raise_()
        self.edit_toolbar.raise_()

    def _deactivate(self):
        self.active = False
        self.debug_enabled = False
        self.debug_button.setText("debug")
        self.press_global = None
        self.press_positions = {}
        self.press_widget_positions = {}
        self.press_widget_states = {}
        self.dragging = False
        self._clear_selection()
        self._refresh_debug_frames()
        self.window_frame.hide()
        for frame in self.window_frames.values():
            if shiboken6.isValid(frame):
                frame.hide()
        self.edit_toolbar.hide()
        self.editable_windows.clear()
        for button in self.style_buttons.values():
            if shiboken6.isValid(button):
                button.hide()
        self.scope_button.hide()
        if getattr(self, "settings_window", None) is not None:
            self.settings_window.close()
            self.settings_window = None
        self.browser.unsetCursor()

    def _refresh_window_frame(self):
        self.window_frame.setGeometry(self.browser.rect())
        self.window_frame.raise_()
        if self.active:
            self._position_toolbar()

    def _position_toolbar(self):
        self.edit_toolbar.adjustSize()
        frame = self.window_frame.geometry()
        x = max(frame.left(), frame.left() + (frame.width() - self.edit_toolbar.width()) // 2)
        y = frame.top() + self._EDIT_BORDER_THICKNESS
        self.edit_toolbar.move(QPoint(x, y))

    def _move_toolbar_horizontally(self, x: int):
        frame = self.window_frame.geometry()
        x = max(frame.left(), min(int(x), frame.right() - self.edit_toolbar.width() + 1))
        y = frame.top() + self._EDIT_BORDER_THICKNESS
        self.edit_toolbar.move(QPoint(x, y))

    def _open_settings(self):
        window = getattr(self, "settings_window", None)
        if window is not None and window.isVisible():
            window.raise_()
            window.activateWindow()
            return
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow

        specs = (
            v2.Spec("edit_selection_border_enabled", "Objets sélectionnés : bordure", "sides_thick", True,
                    {"colors_key": "edit_selection_border", "thickness_key": "edit_selection_border_thickness",
                     "width": 140, "box": 58},
                    extra_keys=("edit_selection_border", "edit_selection_border_thickness")),
            v2.Spec("edit_selection_background", "Objets sélectionnés : couleur fond", "color", self._color_css(self.selection_background)),
            v2.Spec("edit_selection_border_radius", "Objets sélectionnés : border radius", "corners", 0,
                    {"max": 40}),
            v2.Spec("edit_debug_border_enabled", "Objets en focus debug : bordure", "sides_thick", True,
                    {"colors_key": "edit_debug_border", "thickness_key": "edit_debug_border_thickness",
                     "width": 140, "box": 58},
                    extra_keys=("edit_debug_border", "edit_debug_border_thickness")),
            v2.Spec("edit_debug_background", "Objets en focus debug : couleur fond", "color", self._color_css(self.debug_background)),
            v2.Spec("edit_debug_border_radius", "Objets en focus debug : border radius", "corners", 0,
                    {"max": 40}),
        )
        values = {
            "edit_selection_border_enabled": dict(self.selection_border_enabled),
            "edit_selection_border": dict(self.selection_border_colors),
            "edit_selection_border_enabled_linked": True,
            "edit_selection_border_thickness": self.selection_border_width,
            "edit_selection_background": self._color_css(self.selection_background),
            "edit_selection_border_radius": {side: self.selection_radius for side in ("top_left", "top_right", "bottom_right", "bottom_left")},
            "edit_selection_border_radius_linked": True,
            "edit_debug_border_enabled": dict(self.debug_border_enabled),
            "edit_debug_border": dict(self.debug_border_colors),
            "edit_debug_border_enabled_linked": True,
            "edit_debug_border_thickness": self.debug_border_width,
            "edit_debug_background": self._color_css(self.debug_background),
            "edit_debug_border_radius": {side: self.debug_radius for side in ("top_left", "top_right", "bottom_right", "bottom_left")},
            "edit_debug_border_radius_linked": True,
            "colors": load_settings().get("colors") or {}, "slider_ranges": {},
        }
        window = self.settings_window = QuickStyleWindow(
            "Mode édition", specs, values, title="Mode édition",
            settings=ui_state.APPLIED_SETTINGS or load_settings(), parent=self.browser,
        )
        # Ce tableau doit suivre exactement le style commun des tableaux des
        # réglages (bordures, épaisseur, couleurs et coins), pas un style Qt
        # implicite propre à cette fenêtre.
        from settings_layout import set_table_look
        set_table_look(window.table, None)
        window.styleChanged.connect(self._apply_edit_settings)
        window.destroyed.connect(lambda *_args: setattr(self, "settings_window", None))
        window.show()
        window.raise_()
        window.activateWindow()

    def _apply_edit_settings(self, values: dict):
        for key, attr in (("edit_selection_background", "selection_background"),
                          ("edit_debug_background", "debug_background")):
            if key in values:
                color = QColor(values[key])
                if color.isValid():
                    setattr(self, attr, color)
        for prefix, attr in (("edit_selection", "selection"), ("edit_debug", "debug")):
            radius = values.get(f"{prefix}_border_radius")
            if isinstance(radius, dict):
                setattr(self, f"{attr}_radius", max(0, max((int(value) for value in radius.values()), default=0)))
            enabled = values.get(f"{prefix}_border_enabled")
            colors = values.get(f"{prefix}_border")
            if isinstance(enabled, dict):
                setattr(self, f"{attr}_border_enabled", dict(enabled))
            if isinstance(colors, dict):
                setattr(self, f"{attr}_border_colors", dict(colors))
                first = next((resolve_color_ref(value) for value in colors.values() if value), "")
                color = QColor(first)
                if color.isValid():
                    setattr(self, f"{attr}_border", color)
            thickness = values.get(f"{prefix}_border_thickness")
            if thickness is not None:
                setattr(self, f"{attr}_border_width", max(0, int(thickness)))
        self._refresh_frames()
        self._save_edit_appearance()

    def _toggle_debug(self):
        self.debug_enabled = not self.debug_enabled
        self.debug_button.setText("debug : ON" if self.debug_enabled else "debug")
        if self.debug_enabled:
            self._sync_text_style_overrides()
        self._refresh_frames()

    def _sync_text_style_overrides(self, overrides=None):
        """Suit les textes ayant un override pour les afficher dans le debug."""
        import settings_element_style as styles

        if not isinstance(overrides, dict):
            overrides = load_settings().get(styles.KEY) or {}
        if not isinstance(overrides, dict):
            overrides = {}
        modified = set()
        for window in QApplication.topLevelWidgets():
            if not (self._editable_window(window) and window.isVisible()):
                continue
            for label in window.findChildren(QWidget):
                if not self._visible_target(label):
                    continue
                if not styles.is_text_widget(label):
                    continue
                path = styles.widget_path(label, window)
                if path and overrides.get(f"text:{type(window).__name__}:{path}"):
                    modified.add(label)
            for column in window.findChildren(Column):
                view = column.list
                for key, parts in getattr(view, "_edit_geometry", {}).items():
                    if "text" not in parts or not overrides.get(f"row-text:{column.style_title}:{key}"):
                        continue
                    target = self.painted_targets.get((view, key, "text"))
                    if target is None or not shiboken6.isValid(target):
                        target = self.painted_targets[(view, key, "text")] = PaintedTarget(
                            view, key, "text", parts["text"])
                    if self._visible_target(target):
                        modified.add(target)
            try:
                from settings_widgets import _TableFrame, PART_LOOKS
                for frame in window.findChildren(_TableFrame):
                    parts = PART_LOOKS.get(frame.dimsKey()) or {}
                    if not parts or not self._visible_target(frame):
                        continue
                    cells = getattr(getattr(frame, "_extra_dims", None), "cells", {}) or {}
                    for cell in cells.values():
                        look = getattr(cell, "_part_look", None) or {}
                        if any(key in look for key in ("bg", "padding", "border", "font")):
                            modified.add(cell)
            except ImportError:
                pass
            gallery_styles = getattr(__import__("ui_state"), "GALLERY_STYLE_OVERRIDES", {}) or {}
            try:
                from focus import FocusGallery
                for gallery in window.findChildren(FocusGallery):
                    if not gallery.isVisible():
                        continue
                    for element, values in gallery_styles.items():
                        if not values or not element.startswith("gallery-"):
                            continue
                        match = next((part for part in ("cell", "image", "name", "info")
                                      if element.startswith(f"gallery-{part}:")), None)
                        if match is None:
                            continue
                        path = element[len(f"gallery-{match}:"):]
                        row = next((i for i in range(gallery.count())
                                    if str(gallery.item(i).data(Qt.UserRole)) == path), None)
                        if row is None:
                            continue
                        rect = gallery.visualRect(gallery.model().index(row, 0))
                        if not rect.intersects(gallery.viewport().rect()):
                            continue
                        gallery.edit_target_at(rect.center())
                        part = f"gallery-{match}"
                        target_rect = gallery._edit_geometry[path].get(part, rect)
                        target_key = (gallery, path, part)
                        target = self.painted_targets.get(target_key)
                        if target is None or not shiboken6.isValid(target):
                            target = self.painted_targets[target_key] = PaintedTarget(
                                gallery, path, part, target_rect)
                        else:
                            target.sync(target_rect)
                        modified.add(target)
            except ImportError:
                pass
        self.text_modified = modified
        self._refresh_debug_frames()

    def _on_text_style_saved(self, key: str, value):
        if key == "element_style_overrides" and self.debug_enabled:
            self._sync_text_style_overrides(value)

    def _reset_current(self):
        self._restore_visible_positions()
        before = {widget: self._snapshot_widget(widget) for widget in self.selected
                  if self._visible_target(widget)}
        style_targets = self._selected_text_scope()
        self._append_text_style_snapshots(before, style_targets)
        for widget in before:
            if widget in self.selected:
                self._restore_original_position(widget)
                self._forget_position(widget)
        self._remove_text_styles(style_targets)
        self._save_position_overrides()
        self._flush_positions()
        self._record_undo(before)
        self._sync_modified()
        self._refresh_frames()

    def _reset_all(self):
        self._restore_visible_positions()
        before = {widget: self._snapshot_widget(widget) for widget in self.original_positions
                  if self._visible_target(widget)}
        style_targets = self._visible_text_style_targets()
        self._append_text_style_snapshots(before, style_targets)
        for widget in before:
            self._restore_original_position(widget)
            self._forget_position(widget)
        # Les objets libres des tableaux sont retenus dans table_dims, même s'ils
        # n'ont pas encore été sélectionnés dans le mode édition.
        for window in QApplication.topLevelWidgets():
            if not self._editable_window(window) or not window.isVisible():
                continue
            for frame in [window, *window.findChildren(QWidget)]:
                state = getattr(frame, "_extra_dims", None)
                if state is None or not getattr(state, "objects", None):
                    continue
                import settings_cells as cells
                for key, rec in list(state.objects.items()):
                    cell_key, _sep, path = key.partition("|")
                    cell = getattr(state, "cells", {}).get(cell_key)
                    target = cells._resolve_object(cell, path) if cell is not None else None
                    if target is None or not self._visible_target(target):
                        continue
                    before.setdefault(target, {"kind": "object", "state": state,
                                               "key": key, "record": list(rec)})
                    state.set_object(key, None)
                    state.commit()
                    self._forget_position(target)
        self._remove_text_styles(style_targets)
        self._save_position_overrides()
        self._flush_positions()
        self._record_undo(before)
        self._sync_modified()
        self._refresh_frames()

    def _selected_text_scope(self):
        import settings_element_style as styles
        selected_texts = [widget for widget in self.selected
                          if self._has_display_text(widget) or self._has_gallery_style(widget)]
        if len(selected_texts) != 1:
            members = selected_texts
        else:
            selected = selected_texts[0]
            options = (self._scope_options if getattr(self, "_scope_options_widget", None) is selected
                       else self._text_scope_options(selected))
            members = (next((items for title, items in options if title == self.style_scope[1]), [selected])
                       if self.style_scope[0] != "this" else [selected])
        targets = []
        for member in members:
            target = (member if isinstance(member, styles.TextTarget)
                      else self._make_text_target(member, self.style_scope[1]))
            if target is not None:
                targets.append(target)
        return list({target.element: target for target in targets}.values())

    def _visible_text_style_targets(self):
        import settings_element_style as styles
        settings = styles.load_settings()
        overrides = settings.get(styles.KEY) or {}
        targets = []
        for window in QApplication.topLevelWidgets():
            if not self._editable_window(window) or not window.isVisible():
                continue
            widgets = ([window] if isinstance(window, QLabel) else []) + window.findChildren(QWidget)
            for label in widgets:
                if not self._visible_target(label) or not self._has_display_text(label):
                    continue
                path = widget_path(label, window)
                if not path:
                    continue
                element = f"text:{type(window).__name__}:{path}"
                if overrides.get(element):
                    targets.append(styles.TextTarget(element, label, styles.text_of(label)))
            try:
                from settings_widgets import _TableFrame
                for frame in window.findChildren(_TableFrame):
                    prefix = styles.table_id(frame)
                    state = getattr(frame, "_extra_dims", None)
                    cells = getattr(state, "cells", {}) or {}
                    for element, saved in overrides.items():
                        if not saved or not (element == prefix or element.startswith(prefix + styles.PART_SEP)):
                            continue
                        for cell in cells.values():
                            if not self._visible_target(cell):
                                continue
                            table_target = next((target for target in styles.targets_for(cell)
                                                 if target.element == element
                                                 and isinstance(target, (styles.TablePartTarget, styles.TableTarget))), None)
                            if table_target is None:
                                continue
                            anchor = next((label for label in cell.findChildren(QLabel)
                                           if styles.is_text_widget(label) and self._visible_target(label)), cell)
                            text_element = f"edit-cell:{prefix}:{element.rsplit('::', 1)[-1]}"
                            text_target = styles.TextTarget(text_element, anchor,
                                                           styles.text_of(anchor) if styles.is_text_widget(anchor) else "cellule")
                            targets.append(styles.TableTextTarget(text_target, table_target))
                            break
            except ImportError:
                pass
            for column in window.findChildren(Column):
                view = column.list
                for key, parts in getattr(view, "_edit_geometry", {}).items():
                    if "text" not in parts:
                        continue
                    target_widget = self.painted_targets.get((view, key, "text"))
                    if target_widget is None or not shiboken6.isValid(target_widget):
                        target_widget = self.painted_targets[(view, key, "text")] = PaintedTarget(
                            view, key, "text", parts["text"])
                    element = f"row-text:{column.style_title}:{key}"
                    if overrides.get(element) and self._visible_target(target_widget):
                        target = self._make_text_target(target_widget)
                        if target is not None:
                            targets.append(target)
            try:
                from focus import FocusGallery
                galleries = window.findChildren(FocusGallery)
            except ImportError:
                galleries = []
            for gallery in galleries:
                if not gallery.isVisible():
                    continue
                for row in range(gallery.count()):
                    item = gallery.item(row)
                    path = str(item.data(Qt.UserRole) or "")
                    rect = gallery.visualRect(gallery.model().index(row, 0))
                    if not rect.intersects(gallery.viewport().rect()):
                        continue
                    for element, saved in overrides.items():
                        prefix = "gallery-"
                        if not element.startswith(prefix) or not saved:
                            continue
                        part, _sep, target_path = element[len(prefix):].partition(":")
                        if target_path != path:
                            continue
                        target_key = (gallery, path, f"gallery-{part}")
                        target_widget = self.painted_targets.get(target_key)
                        if target_widget is None or not shiboken6.isValid(target_widget):
                            target_widget = self.painted_targets[target_key] = PaintedTarget(
                                gallery, path, f"gallery-{part}", rect)
                        targets.append(styles.GalleryStyleTarget(target_widget, path, part, item.text()))
        return targets

    def _remove_text_styles(self, widgets):
        import settings_element_style as styles
        targets = []
        settings = styles.load_settings()
        overrides = settings.get(styles.KEY) or {}
        for item in widgets:
            target = (item if isinstance(item, styles.TextTarget)
                      else self._make_text_target(item, self.style_scope[1]))
            if target is None:
                continue
            if isinstance(target, styles.TableTextTarget):
                if overrides.get(target.element) or overrides.get(target.cell_target.element):
                    target.remove()
                continue
            element = target.element
            saved = overrides.get(element)
            if saved:
                targets.append((target, None))
        styles.update_text_overrides(targets)

    def _restore_original_position(self, widget, original=None):
        context = self._object_context(widget)
        if context is not None:
            state, key, _host = context
            if key in getattr(state, "objects", {}) or getattr(widget, "_float_slot", None) is not None:
                state.set_object(key, None)
                state.commit()
                self.modified.discard(widget)
                return widget.pos()
        if original is None:
            original = self.original_positions.get(widget)
        if original is None:
            saved = self.position_overrides.get(self._position_key(widget), {})
            offset = saved.get("offset", [0, 0]) if isinstance(saved, dict) else [0, 0]
            if isinstance(widget, PaintedTarget):
                original = widget.base.topLeft()
            elif isinstance(offset, list) and len(offset) == 2:
                original = widget.pos() - QPoint(*offset)
            else:
                original = widget.pos()
            self.original_positions[widget] = original
        widget.move(original)
        if isinstance(widget, PaintedTarget):
            offsets = getattr(widget.view, "_edit_offsets", {}).get(widget.key, {})
            offsets.pop(widget.part, None)
            widget.view.viewport().update()
        return original

    @staticmethod
    def _is_table(widget) -> bool:
        return isinstance(widget, QAbstractItemView) or widget.objectName() == "TableFrame"

    def _cell_ancestor(self, widget):
        """Cellule qui borne un élément interne du tableau, en-têtes compris."""
        parent = widget.parentWidget()
        while parent is not None and parent is not self.browser:
            if self._is_table(parent):
                return None
            name = f"{parent.objectName()} {parent.__class__.__name__}".lower()
            if "cell" in name or "header" in name:
                return parent
            parent = parent.parentWidget()
        return None

    def _bounded_position(self, widget, position: QPoint) -> QPoint:
        if isinstance(widget, PaintedTarget):
            parts = getattr(widget.view, "_edit_geometry", {}).get(widget.key, {})
            if widget.part in {"gallery-name", "gallery-info"}:
                bounds = parts.get("gallery-text-bounds", widget.base)
            elif widget.part.startswith("gallery-"):
                bounds = parts.get("gallery-cell", widget.base)
            else:
                bounds = parts.get("row", widget.base) if widget.part != "row" else widget.view.viewport().rect()
            if widget.part != "row":
                bounds = bounds.translated(getattr(widget.view, "_edit_offsets", {}).get(widget.key, {}).get("row", QPoint()))
            return QPoint(max(bounds.left(), min(position.x(), max(bounds.left(), bounds.right() - widget.width() + 1))),
                          max(bounds.top(), min(position.y(), max(bounds.top(), bounds.bottom() - widget.height() + 1))))
        header = widget.parentWidget()
        cells = getattr(header, "_cells", None) if header is not None else None
        if cells and widget in cells and hasattr(header, "_column_spans"):
            index = cells.index(widget)
            spans = header._column_spans()
            if index < len(spans):
                left, right = spans[index]
                bounds = QRect(left, 0, right - left, header.height())
                max_x = max(bounds.left(), bounds.right() - widget.width() + 1)
                max_y = max(bounds.top(), bounds.bottom() - widget.height() + 1)
                return QPoint(max(bounds.left(), min(position.x(), max_x)),
                              max(bounds.top(), min(position.y(), max_y)))
        cell = self._cell_ancestor(widget)
        parent = widget.parentWidget()
        if cell is None or parent is None:
            return position
        bounds = QRect(cell.mapTo(parent, QPoint(0, 0)), cell.size())
        max_x = max(bounds.left(), bounds.right() - widget.width() + 1)
        max_y = max(bounds.top(), bounds.bottom() - widget.height() + 1)
        return QPoint(max(bounds.left(), min(position.x(), max_x)),
                      max(bounds.top(), min(position.y(), max_y)))

    def _window_key(self, window):
        return "main" if window is self.browser else f"{type(window).__name__}:{getattr(window, 'name', window.windowTitle())}"

    def _position_key(self, widget):
        window = widget.window()
        prefix = self._window_key(window)
        if isinstance(widget, PaintedTarget):
            return f"{prefix}|{widget_path(widget.view, window)}|{widget.key}|{widget.part}"
        return f"{prefix}|{widget_path(widget, window)}"

    def _selection_path(self, global_pos):
        """Ne retient que les petits objets éditables, jamais leurs conteneurs."""
        widget = QApplication.widgetAt(global_pos)
        if widget is None or not self._editable_window(widget.window()):
            return []
        window = widget.window()
        # childAt ignore les textes transparents à la souris : recherche
        # géométrique complémentaire pour ces feuilles uniquement.
        labels = [child for child in widget.findChildren(QLabel)
                  if child.isVisible() and child.rect().contains(child.mapFromGlobal(global_pos))]
        if labels:
            widget = labels[-1]
        chain = []
        node = widget
        while node is not None and node is not window:
            if node is self.edit_toolbar or isinstance(node, (_InterfaceMoveFrame, PaintedTarget)):
                return []
            if node is self.window_frame or node in self.window_frames.values():
                return []
            chain.append(node)
            node = node.parentWidget()
        column = next((node for node in chain if isinstance(node, Column)), None)
        try:
            from focus import FocusGallery
        except ImportError:
            FocusGallery = ()
        gallery = next((node for node in chain if isinstance(node, FocusGallery)), None) if FocusGallery else None
        if gallery is not None and gallery.viewport().rect().contains(
                gallery.viewport().mapFromGlobal(global_pos)):
            point = gallery.viewport().mapFromGlobal(global_pos)
            hit = gallery.edit_target_at(point)
            if hit is None:
                return []
            key, part, rect, cell_rect = hit
            targets = []
            for target_part, target_rect in ((part, rect), ("gallery-cell", cell_rect)):
                target_key = (gallery, key, target_part)
                target = self.painted_targets.get(target_key)
                if target is None or not shiboken6.isValid(target):
                    target = self.painted_targets[target_key] = PaintedTarget(
                        gallery, key, target_part, target_rect)
                else:
                    target.sync(target_rect)
                if not targets or target is not targets[-1]:
                    targets.append(target)
            return targets
        if column is not None and column.list.viewport().rect().contains(column.list.viewport().mapFromGlobal(global_pos)):
            view = column.list
            index = view.indexAt(view.viewport().mapFromGlobal(global_pos))
            leaf = None
            if index.isValid():
                key = str(index.data(ROLE_PATH) or index.row())
                parts = getattr(view, "_edit_geometry", {}).get(key, {})
                point = view.viewport().mapFromGlobal(global_pos)
                for part in ("media-video", "media-photo", "text", "icon", "preview"):
                    rect = parts.get(part)
                    if rect is None:
                        continue
                    target_key = (view, key, part)
                    target = self.painted_targets.get(target_key)
                    if target is None or not shiboken6.isValid(target):
                        target = self.painted_targets[target_key] = PaintedTarget(view, key, part, rect)
                    else:
                        target.sync(rect)
                    if not target.geometry().contains(point):
                        continue
                    leaf = target
                    break
                return [leaf] if leaf is not None else []
            return []
        target = next((node for node in chain if self._editable_object(node)), None)
        return [target] if target is not None else []

    @staticmethod
    def _editable_object(widget):
        """Contrôles, textes et petits widgets visuels; exclut les tableaux et conteneurs."""
        if isinstance(widget, (PaintedTarget, QLabel, QPushButton, QLineEdit)):
            return True
        if hasattr(widget, "_min") and hasattr(widget, "_max"):
            return True                # slider peint a la main, ex. settings_widgets._MiniSlider
        try:
            from PySide6.QtWidgets import (
                QAbstractButton, QAbstractSlider, QAbstractSpinBox, QComboBox,
                QPlainTextEdit, QSlider, QTextEdit,
            )
            if isinstance(widget, (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                                   QComboBox, QPlainTextEdit, QSlider, QTextEdit)):
                return True
        except ImportError:
            pass
        name = f"{widget.objectName()} {type(widget).__name__}".lower()
        return bool(getattr(widget, "_free_object", False)
                    or type(widget).__name__.startswith("_Toggle")
                    or "iconbutton" in name)

    @staticmethod
    def _has_display_text(widget):
        try:
            if isinstance(widget, PaintedTarget):
                return widget.part in {"text", "gallery-name", "gallery-info", "media-photo", "media-video"} \
                    and bool(_InterfaceMoveMode._painted_text(widget))
            import settings_element_style as styles
            return styles.is_text_widget(widget)
        except RuntimeError:
            return False

    @staticmethod
    def _has_gallery_style(widget):
        return isinstance(widget, PaintedTarget) and widget.part.startswith("gallery-")

    @staticmethod
    def _text_value(widget):
        if isinstance(widget, PaintedTarget):
            return _InterfaceMoveMode._painted_text(widget)
        try:
            import settings_element_style as styles
            return styles.text_of(widget)
        except RuntimeError:
            return ""

    @staticmethod
    def _make_text_target(widget, table_scope: str | None = None):
        import settings_element_style as styles
        if isinstance(widget, PaintedTarget):
            return next((target for target in styles.targets_for(widget)
                         if isinstance(target, styles.TextTarget)), None)
        path = widget_path(widget, widget.window())
        if not path:
            return None
        text = styles.text_of(widget).replace("\n", " ")[:40]
        text_target = styles.TextTarget(f"text:{type(widget.window()).__name__}:{path}", widget, text)
        try:
            from settings_widgets import _TableFrame
            frame = styles._ancestor(widget, _TableFrame)
            if frame is not None:
                parts = styles._table_part_targets(widget, frame)
                cell_target = parts[0] if parts else None
                if table_scope in {
                    "Tous les textes de la ligne (y compris sous-cellules)",
                } and len(parts) > 1:
                    cell_target = parts[1]
                elif table_scope in {
                    "Tous les textes de la colonne (sauf entête)",
                    "Tous les textes de la colonne",
                } and len(parts) > 2:
                    cell_target = parts[2]
                elif table_scope in {
                    "Tous les textes du tableau (sauf entête)",
                    "Tous les textes du tableau",
                }:
                    cell_target = styles.TableTarget(styles.table_id(frame), frame,
                                                     f"« {frame.dimsKey()} »")
                if cell_target is not None:
                    return styles.TableTextTarget(text_target, cell_target)
        except (ImportError, RuntimeError):
            pass
        return text_target

    @staticmethod
    def _painted_text(target):
        if target.part.startswith("gallery-"):
            for row in range(target.view.count()):
                item = target.view.item(row)
                if str(item.data(Qt.UserRole)) == str(target.key):
                    return str(item.text() if target.part == "gallery-name" else item.data(Qt.UserRole + 2) or "")
            return ""
        from settings_element_style import _row_index
        index = _row_index(target.view, str(target.key))
        if index is not None and target.part in {"media-photo", "media-video"}:
            counts = index.data(ROLE_MEDIA_COUNTS)
            try:
                count = max(0, int(counts[0 if target.part == "media-photo" else 1]))
                return f"{'IMG' if target.part == 'media-photo' else 'VID'} {count}"
            except (TypeError, ValueError, IndexError):
                return ""
        return str(index.data(Qt.DisplayRole) or "").strip() if index is not None else ""

    def _object_context(self, widget, create=True):
        """(magasin, cle, hôte) pour un objet déplaçable par le mécanisme libre."""
        if isinstance(widget, PaintedTarget):
            return None
        import settings_cells as cells
        host = cells._cell_of(widget)
        if host is None:
            parent = widget.parentWidget()
            layout = parent.layout() if parent is not None else None
            if layout is None or layout.indexOf(widget) < 0:
                return None
            host = parent
        state, host_key = cells._state_of(host)
        if state is None:
            window = widget.window()
            host_path = widget_path(host, window)
            if host is not window and not host_path:
                return None
            state = self.object_stores.get(window)
            if state is None:
                state = self.object_stores[window] = _InterfaceObjectStore(self, window)
            state.hosts[host_path] = host
            if getattr(host, "_objects_host", None) is None:
                host._objects_host = lambda s=state, k=host_path: (s, k)
            host_key = host_path
        path = cells._object_path(host, widget)
        if not path:
            return None
        return state, f"{host_key}|{path}", host

    def _set_object_global_position(self, widget, global_pos):
        """Déplace un contrôle via sa place flottante; les layouts ne peuvent plus l'écraser."""
        if isinstance(widget, PaintedTarget):
            parent = widget.parentWidget()
            position = self._bounded_position(widget, parent.mapFromGlobal(global_pos))
            widget.move(position)
            self._remember_position(widget)
            self.modified.add(widget)
            return True
        context = self._object_context(widget)
        if context is None:
            parent = widget.parentWidget()
            if parent is None:
                return False
            widget.move(self._bounded_position(widget, parent.mapFromGlobal(global_pos)))
            self._remember_position(widget)
            return False
        import settings_cells as cells
        state, key, host = context
        if getattr(widget, "_float_slot", None) is None and not cells._float_object(host, widget):
            return False
        base = widget._float_slot.mapTo(host, QPoint(0, 0))
        wanted = host.mapFromGlobal(global_pos)
        rec = list(getattr(widget, "_float_rec", [0, 0, 0, 0]))
        rec[0], rec[1] = wanted.x() - base.x(), wanted.y() - base.y()
        state.set_object(key, rec)
        state.commit()
        self.original_positions.setdefault(widget, base)
        self.modified.add(widget)
        return True

    def _save_position_overrides(self):
        self._position_save_timer.start()

    def _flush_positions(self):
        save_live_state("interface_move_positions", dict(self.position_overrides))

    def _remember_position(self, widget):
        key = self._position_key(widget)
        if key:
            delta = widget.pos() - self.original_positions.get(widget, widget.pos())
            if delta.isNull():
                self.position_overrides.pop(key, None)
            else:
                self.position_overrides[key] = {"offset": [delta.x(), delta.y()]}

    def _forget_position(self, widget):
        key = self._position_key(widget)
        if key:
            self.position_overrides.pop(key, None)

    def _select(self, widget):
        self._clear_selection()
        self.style_scope = ("this", "Cet élément seulement")
        self._add_selection(widget)

    def _add_selection(self, widget, allow_ancestors=False):
        # Parent + enfant : le déplacement en groupe doublerait le décalage.
        for current in self.selected:
            if current is widget or (not allow_ancestors and current.isAncestorOf(widget)):
                return
        if not allow_ancestors:
            for current in [item for item in self.selected if widget.isAncestorOf(item)]:
                self._deselect(current)
        self.selected.append(widget)
        context = self._object_context(widget)
        if context is not None and getattr(widget, "_float_slot", None) is not None:
            _state, _key, host = context
            baseline = widget._float_slot.mapTo(host, QPoint(0, 0))
        else:
            baseline = widget.pos()
        self.original_positions.setdefault(widget, baseline)
        saved = self.position_overrides.get(self._position_key(widget))
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            try:
                widget.move(int(saved[0]), int(saved[1]))
            except (TypeError, ValueError):
                pass
        frame = self._make_frame(widget, debug=False)
        self.frames[widget] = frame
        frame.show()
        frame.raise_()
        self._refresh_frames()

    def _deselect(self, widget):
        if widget not in self.selected:
            return
        self.selected.remove(widget)
        frame = self.frames.pop(widget, None)
        if frame is not None and shiboken6.isValid(frame):
            frame.deleteLater()
        self._refresh_frames()

    def _refine_selection(self, table, widget):
        """Remplace un tableau retenu par le widget interne visé au second clic."""
        try:
            index = self.selected.index(table)
        except ValueError:
            self._select(widget)
            return
        self.selected.pop(index)
        frame = self.frames.pop(table, None)
        if frame is not None:
            frame.deleteLater()
        self.selected.insert(index, widget)
        self.style_scope = ("this", "Cet élément seulement")
        self.original_positions.setdefault(widget, widget.pos())
        saved = self.position_overrides.get(self._position_key(widget))
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            try:
                widget.move(int(saved[0]), int(saved[1]))
            except (TypeError, ValueError):
                pass
        frame = self._make_frame(widget, debug=False)
        self.frames[widget] = frame
        frame.show()
        frame.raise_()
        self._refresh_frames()

    def _clear_selection(self):
        self.selected.clear()
        for frame in self.frames.values():
            if shiboken6.isValid(frame):
                frame.deleteLater()
        self.frames.clear()

    def _refresh_frames(self):
        self._sync_selection_tools()
        self._refresh_debug_frames()
        for widget, frame in list(self.frames.items()):
            if not shiboken6.isValid(frame):
                self.frames.pop(widget, None)
                if widget in self.selected:
                    self.selected.remove(widget)
                continue
            if not self.active or not self._editable_window(widget.window()) or not self._visible_target(widget):
                frame.hide()
                continue
            rect = QRect(widget.mapTo(widget.window(), QPoint(0, 0)), widget.size())
            frame.setGeometry(rect.adjusted(-2, -2, 1, 1))
            self._style_edit_frame(frame, False)
            frame.show()
            frame.raise_()

    def _text_scope_options(self, widget):
        """Libellés ciblés par les portées du menu d'édition."""
        gallery_part = widget.part.removeprefix("gallery-") if isinstance(widget, PaintedTarget) \
            and widget.part.startswith("gallery-") else None
        if not self._has_display_text(widget) and gallery_part not in {"image", "cell"}:
            return []
        import settings_element_style as styles
        if gallery_part is not None:
            gallery = widget.view
            rows = [(str(gallery.item(row).data(Qt.UserRole)), gallery.item(row))
                    for row in range(gallery.count())]
            if gallery_part in {"name", "info"}:
                one = styles.GalleryStyleTarget(widget, str(widget.key), gallery_part, self._painted_text(widget))
                same_type = [styles.GalleryStyleTarget(widget, key, gallery_part, item.text()) for key, item in rows]
                all_texts = [styles.GalleryStyleTarget(widget, key, part, item.text())
                             for key, item in rows for part in ("name", "info")
                             if item.data(Qt.UserRole + 2) or part == "name"]
                return [("Cette cellule seulement", [one]),
                        ("Toutes les cellules pour ce type de texte", same_type),
                        ("Toutes les cellules pour tous les textes", all_texts)]
            part = "image" if gallery_part == "image" else "cell"
            current = styles.GalleryStyleTarget(widget, str(widget.key), part)
            every = [styles.GalleryStyleTarget(widget, key, part, item.text()) for key, item in rows]
            return [("Cette cellule seulement", [current]),
                    ("Toutes les cellules du tableau", every)]
        if isinstance(widget, PaintedTarget):
            column = styles._column_for_view(widget.view)
            if column is None:
                return []
            if widget.part in {"media-photo", "media-video"}:
                kind = "IMG" if widget.part == "media-photo" else "VID"
                targets = []
                model = widget.view.model()
                for row in range(model.rowCount()):
                    index = model.index(row, 0)
                    counts = index.data(ROLE_MEDIA_COUNTS)
                    path = str(index.data(ROLE_PATH) or "")
                    try:
                        count = max(0, int(counts[0 if widget.part == "media-photo" else 1]))
                    except (TypeError, ValueError, IndexError):
                        continue
                    if path and counts is not None:
                        targets.append(styles.RowMediaTextTarget(
                            widget, path, getattr(column, "style_title", ""), widget.part,
                            f"{kind} {count}"))
                current = styles.RowMediaTextTarget(
                    widget, str(widget.key), getattr(column, "style_title", ""), widget.part,
                    self._painted_text(widget))
                global_target = styles.RowMediaTextTarget(
                    widget, str(widget.key), getattr(column, "style_title", ""), widget.part,
                    self._painted_text(widget), all_columns=True)
                return [("Cette indication seulement", [current]),
                        (f"Toutes les indications {kind} de cette colonne", targets),
                        (f"Toutes les indications {kind} pour toutes les colonnes", [global_target])]
            targets = []
            model = widget.view.model()
            for row in range(model.rowCount()):
                index = model.index(row, 0)
                path = str(index.data(ROLE_PATH) or index.row())
                text = str(index.data(Qt.DisplayRole) or "").strip()
                if path and text:
                    targets.append(styles.RowTextTarget(widget, path, getattr(column, "style_title", ""), text))
            return [("Ce texte seulement", [widget]),
                    ("Les éléments de ce type dans toute la colonne", targets)]
        import settings_cells as cells
        from settings_widgets import _TableFrame

        def labels(nodes):
            found = []
            for node in nodes:
                if styles.is_text_widget(node):
                    found.append(node)
                found.extend(lb for lb in node.findChildren(QWidget) if styles.is_text_widget(lb))
            return list(dict.fromkeys(found))

        frame = styles._ancestor(widget, _TableFrame)
        if frame is not None:
            state = getattr(frame, "_extra_dims", None)
            table_cells = getattr(state, "cells", {}) if state else {}
            cell = cells._cell_of(widget)
            current = next((key for key, item in table_cells.items() if item is cell), None)
            if current:
                row, col = (int(n) for n in current[1:].split("c"))
                row_nodes = [item for key, item in table_cells.items() if key.startswith(f"r{row}c")]
                col_nodes = [item for key, item in table_cells.items() if key.endswith(f"c{col}")]
                data_nodes = list(table_cells.values())
                head = getattr(frame, "_flat_head", None)
                header_labels = [lb for lb in getattr(head, "_cells", []) if styles.is_text_widget(lb)]
                whole = labels(data_nodes)
                whole_with_head = list(dict.fromkeys([*whole, *header_labels]))
                options = [
                    ("Ce texte seulement", [widget]),
                    ("Tous les textes de la ligne (y compris sous-cellules)", labels(row_nodes)),
                    ("Tous les textes de la colonne (sauf entête)", labels(col_nodes)),
                    ("Tous les textes du tableau (sauf entête)", whole),
                    ("Tous les textes du tableau", whole_with_head),
                ]
                return [(title, [lb for lb in members if shiboken6.isValid(lb)])
                        for title, members in options]
            head = getattr(frame, "_flat_head", None)
            header_labels = [lb for lb in getattr(head, "_cells", [])
                             if styles.is_text_widget(lb)]
            if widget in header_labels:
                data_labels = labels(list(table_cells.values()))
                return [(title, members) for title, members in (
                    ("Ce texte seulement", [widget]),
                    ("Tous les textes de l'entête", header_labels),
                    ("Tous les textes du tableau (sauf entête)", data_labels),
                    ("Tous les textes du tableau", list(dict.fromkeys([*data_labels, *header_labels]))),
                )]
        node = widget.parentWidget()
        while node is not None and not isinstance(node, Column):
            node = node.parentWidget()
        if node is not None:
            same_type = [lb for lb in node.findChildren(type(widget)) if styles.is_text_widget(lb)]
            return [("Cet élément seulement", [widget]), ("Les éléments de ce type dans toute la colonne", same_type)]
        try:
            from settings_layout import _SectionHeader
            title_header = styles._ancestor(widget, (_SectionHeader,))
        except ImportError:
            title_header = None
        if title_header is not None:
            level = getattr(title_header.parentWidget(), "_level", None)
            title_labels = []
            for header in widget.window().findChildren(_SectionHeader):
                parent = header.parentWidget()
                label = getattr(parent, "_name_label", None)
                if label is not None and (level is None or getattr(parent, "_level", None) == level):
                    title_labels.append(label)
            return [("Ce titre seulement", [widget]), ("Tous les titres de même niveau", title_labels)]
        return []

    def _sync_selection_tools(self):
        try:
            import settings_element_style as styles
            for window in list(styles._OPEN.values()):
                try:
                    if (getattr(window, "_interface_selection_owner", None) is self
                            and getattr(window, "_interface_selection_anchor", None) not in self.selected):
                        window.close()
                except RuntimeError:
                    continue
        except ImportError:
            pass
        style_selected = [widget for widget in self.selected
                          if self._has_display_text(widget) or self._has_gallery_style(widget)]
        anchor = style_selected[0] if style_selected else None
        selected = anchor if len(self.selected) == 1 else None
        model_rows = (selected.view.model().rowCount()
                      if isinstance(selected, PaintedTarget) else None)
        options_key = (id(selected), model_rows) if selected is not None else None
        if options_key is None:
            options = []
            self._scope_options_key = None
            self._scope_options_widget = None
            self._scope_options = []
        elif (not isinstance(selected, PaintedTarget)
              or options_key != getattr(self, "_scope_options_key", None)):
            options = self._text_scope_options(selected) if selected is not None else []
            self._scope_options_key = options_key
            self._scope_options_widget = selected
            self._scope_options = options
        else:
            options = self._scope_options
        scope_title = (options[0][0] if self.style_scope[0] == "this" and options
                       else self.style_scope[1] or "Cet élément seulement")
        signature = (id(selected), scope_title,
                     tuple((title, tuple(getattr(item, "element", id(item)) for item in members))
                           for title, members in options))
        if signature != self._scope_menu_signature:
            old_menu = self.scope_button.menu()
            menu = QMenu(self.scope_button)
            scope_group = QActionGroup(menu)
            scope_group.setExclusive(True)
            selected_scope = scope_title
            for title, members in options:
                action = menu.addAction(title)
                action.setCheckable(True)
                action.setChecked(title == selected_scope)
                scope_group.addAction(action)
                action.setEnabled(bool(members))
                action.triggered.connect(lambda _checked=False, t=title: self._choose_style_scope(t))
            self.scope_button.setMenu(menu)
            if old_menu is not None:
                old_menu.deleteLater()
            self._scope_menu_signature = signature
        show_scope = self.active and len(options) > 1
        short_scope = {
            "Ce texte seulement": "Texte seul",
            "Cet élément seulement": "Élément seul",
            "Tous les textes de la ligne (y compris sous-cellules)": "Textes de la ligne",
            "Tous les textes de la colonne (sauf entête)": "Textes de la colonne",
            "Tous les textes du tableau (sauf entête)": "Textes du tableau",
            "Tous les textes du tableau": "Textes + entête",
            "Tous les titres de même niveau": "Titres du même niveau",
            "Les éléments de ce type dans toute la colonne": "Type, toute la colonne",
        }.get(scope_title, scope_title)
        self.scope_button.setText(f"Portée : {short_scope}")
        self.scope_button.setToolTip(scope_title)
        changed = self.scope_button.isVisible() != show_scope
        self.scope_button.setVisible(show_scope)
        if changed and self.active:
            old_x = self.edit_toolbar.x()
            self.edit_toolbar.adjustSize()
            self._move_toolbar_horizontally(old_x)
        for button in list(self.style_buttons.values()):
            if (shiboken6.isValid(button)
                    and (anchor is None or button.parentWidget() is not anchor.window())):
                button.hide()
        if (self.active and anchor is not None and self._editable_window(anchor.window())):
            owner = anchor.window()
            button = self.style_buttons.get(owner)
            if button is None or not shiboken6.isValid(button):
                button = self.style_buttons[owner] = self._make_style_button(owner)
                owner.destroyed.connect(lambda *_args, w=owner: self.style_buttons.pop(w, None))
            rect = QRect(anchor.mapTo(owner, QPoint(0, 0)), anchor.size())
            button.adjustSize()
            x = min(owner.width() - button.width(), rect.right() + 3)
            x = max(0, x)
            pos = QPoint(x, max(0, rect.top()))
            if button.pos() != pos:
                button.move(pos)
            if not button.isVisible():
                button.show()
            button.raise_()

    def _choose_style_scope(self, title: str):
        is_single = bool(self._scope_options and title == self._scope_options[0][0])
        self.style_scope = ("this", title) if is_single else (title, title)
        self._sync_selection_tools()

    def _open_selected_text_style(self):
        selected_texts = [widget for widget in self.selected
                          if self._has_display_text(widget) or self._has_gallery_style(widget)]
        if not selected_texts:
            return
        import settings_element_style as styles
        anchor = selected_texts[0]

        if len(selected_texts) > 1:
            targets = [target for widget in selected_texts
                       if (target := self._make_text_target(widget)) is not None]
            description = "Sélection multiple"
        else:
            _scope, description = self.style_scope
            options = (self._scope_options if getattr(self, "_scope_options_widget", None) is anchor
                       else self._text_scope_options(anchor))
            target = self._make_text_target(anchor, description)
            if target is None:
                return
            members = ([anchor] if _scope == "this" else
                       next((items for title, items in options if title == description), [anchor]))
            targets = [target]
            for member in members:
                if member is target or member is anchor:
                    continue
                next_target = member if isinstance(member, styles.TextTarget) else self._make_text_target(member, description)
                if next_target is not None:
                    targets.append(next_target)
        targets = list({target.element: target for target in targets}.values())
        if not targets:
            return
        target = targets[0]
        if len(targets) > 1:
            target = styles.TextGroupTarget(targets, f"{description}:{target.element}")
        window = styles.open_override(target, parent=anchor.window())
        window._interface_selection_owner = self
        window._interface_selection_anchor = anchor

    def _make_frame(self, widget, debug: bool):
        frame = _InterfaceMoveFrame(widget.window(), self, debug)
        self._style_edit_frame(frame, debug)
        return frame

    def _style_edit_frame(self, frame, debug):
        frame.debug = debug
        frame.update()

    def _refresh_debug_frames(self):
        wanted = {widget for widget in (self.modified | self.text_modified) - set(self.selected)
                  if self._visible_target(widget)} if self.debug_enabled and self.active else set()
        for widget in list(self.debug_frames):
            if widget not in wanted or not shiboken6.isValid(widget):
                frame = self.debug_frames.pop(widget)
                if shiboken6.isValid(frame):
                    frame.deleteLater()
        for widget in wanted:
            if widget not in self.debug_frames:
                frame = self._make_frame(widget, debug=True)
                self.debug_frames[widget] = frame
                frame.show()
            frame = self.debug_frames[widget]
            if widget.isVisible():
                self._style_edit_frame(frame, True)
                frame.setGeometry(QRect(widget.mapTo(widget.window(), QPoint(0, 0)), widget.size()).adjusted(-2, -2, 1, 1))
                frame.raise_()

    def _mark_modified(self, widgets):
        for widget in widgets:
            if shiboken6.isValid(widget) and widget.pos() != self.original_positions.get(widget, widget.pos()):
                self.modified.add(widget)
        self._refresh_debug_frames()

    def _movement_scope_targets(self):
        """Objets déplacés ensemble selon la portée choisie pour le texte sélectionné."""
        import settings_element_style as styles

        chosen = [w for w in self.selected
                  if self._has_display_text(w) or self._has_gallery_style(w)]
        if len(chosen) != 1 or self.style_scope[0] == "this":
            return list(dict.fromkeys(self.selected))
        anchor = chosen[0]
        options = (self._scope_options if getattr(self, "_scope_options_widget", None) is anchor
                   else self._text_scope_options(anchor))
        members = next((items for title, items in options if title == self.style_scope[1]), None)
        if not members:
            return list(dict.fromkeys(self.selected))

        resolved = list(self.selected)
        for member in members:
            if isinstance(member, PaintedTarget):
                target = member
            elif isinstance(member, styles.RowTextTarget):
                view = member.view
                rect = getattr(view, "_edit_geometry", {}).get(member.path, {}).get("text")
                if rect is None or not rect.intersects(view.viewport().rect()):
                    continue
                key = (view, member.path, "text")
                target = self.painted_targets.get(key)
                if target is None or not shiboken6.isValid(target):
                    target = self.painted_targets[key] = PaintedTarget(view, member.path, "text", rect)
                else:
                    target.sync(rect)
            elif isinstance(member, styles.GalleryStyleTarget):
                gallery = member.gallery
                row = next((i for i in range(gallery.count())
                            if str(gallery.item(i).data(Qt.UserRole)) == member.path), None)
                if row is None:
                    continue
                rect = gallery.visualRect(gallery.model().index(row, 0))
                if not rect.intersects(gallery.viewport().rect()):
                    continue
                gallery.edit_target_at(rect.center())
                part = f"gallery-{member.part}"
                part_rect = gallery._edit_geometry.get(member.path, {}).get(part, rect)
                key = (gallery, member.path, part)
                target = self.painted_targets.get(key)
                if target is None or not shiboken6.isValid(target):
                    target = self.painted_targets[key] = PaintedTarget(gallery, member.path, part, part_rect)
                else:
                    target.sync(part_rect)
            elif isinstance(member, QWidget):
                target = member
            else:
                continue
            if self._visible_target(target) and target not in resolved:
                resolved.append(target)
        return resolved

    def _sync_modified(self):
        keep = set()
        for widget in self.modified:
            if not shiboken6.isValid(widget):
                continue
            context = self._object_context(widget)
            if context is not None:
                state, key, _host = context
                if getattr(state, "objects", {}).get(key):
                    keep.add(widget)
            elif widget.pos() != self.original_positions.get(widget, widget.pos()):
                keep.add(widget)
        self.modified = keep

    def _move_to_positions(self, delta: QPoint, cursor: QPoint | None = None):
        if cursor is not None and self.selected and not isinstance(self.selected[0], PaintedTarget):
            import settings_cells as cells
            context = self._object_context(self.selected[0])
            if context is not None:
                state = context[0]
                target = self.selected[0]
                rect = QRect(self.press_positions.get(target, target.mapToGlobal(QPoint(0, 0))), target.size())
                wanted = rect.translated(delta)
                snap_x = cells.OBJECT_GESTURES._snap_shift(
                    wanted.left(), wanted.left() + wanted.width(), True, cursor, target, state)
                snap_y = cells.OBJECT_GESTURES._snap_shift(
                    wanted.top(), wanted.top() + wanted.height(), False, cursor, target, state)
                if self.drag_axis != "y":
                    delta.setX(delta.x() + snap_x)
                if self.drag_axis != "x":
                    delta.setY(delta.y() + snap_y)
        for widget, start in self.press_positions.items():
            if not self._visible_target(widget):
                continue
            self._set_object_global_position(widget, start + delta)
        self._save_position_overrides()
        self._mark_modified(list(self.press_positions))
        self._refresh_frames()

    def _resize_selected(self, cursor: QPoint):
        drag = self.drag_resize
        if not drag:
            return
        import settings_cells as cells
        target, state, key, host = drag["target"], drag["state"], drag["key"], drag["host"]
        if not self._visible_target(target):
            return
        delta = cursor - self.press_global
        rect = QRect(drag["rect"])
        edge = drag["edge"]
        horizontal = edge in ("left", "right")
        origin = host.mapToGlobal(QPoint(0, 0))
        if horizontal:
            value = drag["rect"].left() + delta.x() if edge == "left" else drag["rect"].left() + drag["rect"].width() + delta.x()
            value = cells.OBJECT_GESTURES._snap(value + origin.x(), True, cursor, target, state) - origin.x()
        else:
            value = drag["rect"].top() + delta.y() if edge == "top" else drag["rect"].top() + drag["rect"].height() + delta.y()
            value = cells.OBJECT_GESTURES._snap(value + origin.y(), False, cursor, target, state) - origin.y()
        if edge == "left":
            right = drag["rect"].right() + 1
            left = max(0, min(value, right - cells._OBJECT_MIN))
            rect = QRect(left, rect.top(), right - left, rect.height())
        elif edge == "right":
            right = min(host.width(), max(value, rect.left() + cells._OBJECT_MIN))
            rect.setWidth(right - rect.left())
        elif edge == "top":
            bottom = drag["rect"].bottom() + 1
            top = max(0, min(value, bottom - cells._OBJECT_MIN))
            rect = QRect(rect.left(), top, rect.width(), bottom - top)
        else:
            bottom = min(host.height(), max(value, rect.top() + cells._OBJECT_MIN))
            rect.setHeight(bottom - rect.top())
        rec = list(drag["record"])
        rec[0], rec[1] = rect.left() - drag["base"].x(), rect.top() - drag["base"].y()
        rec[2], rec[3] = rect.width(), rect.height()
        target._float_rec = rec
        state.set_object(key, rec)
        state.commit()
        self._save_position_overrides()
        self._mark_modified([target])
        self._refresh_frames()

    def _move_selected(self, delta: QPoint):
        targets = self._movement_scope_targets()
        before = {widget: self._snapshot_widget(widget) for widget in targets
                  if self._visible_target(widget)}
        for widget in before:
            self._set_object_global_position(widget, widget.mapToGlobal(QPoint(0, 0)) + delta)
        self._save_position_overrides()
        self._mark_modified(list(before))
        self._record_undo(before)
        self._refresh_frames()

    def _snapshot_widget(self, widget):
        if isinstance(widget, PaintedTarget):
            return {"kind": "position", "position": QPoint(widget.pos())}
        context = self._object_context(widget)
        if context is not None:
            state, key, _host = context
            record = getattr(state, "objects", {}).get(key)
            snapshot = {"kind": "object", "state": state, "key": key,
                        "record": list(record) if record else None}
        else:
            snapshot = {"kind": "position", "position": QPoint(widget.pos())}
        if self._has_display_text(widget):
            target = self._make_text_target(widget)
            if target is not None:
                self._snapshot_style_target(snapshot, target)
        return snapshot

    @staticmethod
    def _snapshot_style_target(snapshot, target):
        import copy
        import settings_element_style as styles
        overrides = styles.load_settings().get(styles.KEY) or {}
        if isinstance(target, styles.TableTextTarget):
            saved = target.snapshot_overrides()
            if saved.get("text") or saved.get("cell"):
                snapshot.setdefault("text_styles", []).append((target, saved))
        else:
            saved = overrides.get(target.element)
            if saved:
                snapshot.setdefault("text_styles", []).append((target, copy.deepcopy(saved)))

    def _append_text_style_snapshots(self, before, targets):
        import copy
        import settings_element_style as styles
        overrides = styles.load_settings().get(styles.KEY) or {}
        for target in targets:
            widget = target.widget
            if not self._visible_target(widget):
                continue
            snapshot = before.get(widget)
            if snapshot is None:
                snapshot = before[widget] = self._snapshot_widget(widget)
            records = snapshot.setdefault("text_styles", [])
            if not any(existing.element == target.element for existing, _values in records):
                if isinstance(target, styles.TableTextTarget):
                    saved = target.snapshot_overrides()
                    if saved.get("text") or saved.get("cell"):
                        records.append((target, saved))
                else:
                    saved = overrides.get(target.element)
                    if saved:
                        records.append((target, copy.deepcopy(saved)))

    def _restore_snapshot(self, widget, snapshot):
        if snapshot.get("kind") == "object":
            state = snapshot["state"]
            state.set_object(snapshot["key"], snapshot.get("record"))
            state.commit()
            if snapshot.get("record"):
                self.modified.add(widget)
            else:
                self.modified.discard(widget)
        elif shiboken6.isValid(widget) and widget.parentWidget() is not None:
            widget.move(snapshot["position"])
            if isinstance(widget, PaintedTarget):
                widget.view.viewport().update()
        saved_styles = snapshot.get("text_styles") or []
        if saved_styles:
            import settings_element_style as styles
            regular, composite = [], []
            for target, values in saved_styles:
                if isinstance(target, styles.TableTextTarget):
                    composite.append((target, values))
                else:
                    regular.append((target, values))
            if regular:
                styles.update_text_overrides(regular)
            for target, values in composite:
                target.restore_overrides(values)

    def _record_undo(self, before: dict[QWidget, dict]):
        if not before:
            return
        self.undo_stack.append(before)
        del self.undo_stack[:-100]

    def _undo(self):
        while self.undo_stack:
            snapshots = self.undo_stack.pop()
            valid = {widget: snapshot for widget, snapshot in snapshots.items()
                     if self._visible_target(widget) and widget.parentWidget() is not None}
            if not valid:
                continue
            for widget, snapshot in valid.items():
                self._restore_snapshot(widget, snapshot)
            self._save_position_overrides()
            self._sync_modified()
            self._refresh_frames()
            return


# Fenetre principale
# ==========================================================================

def _shown_or_pending(widget) -> bool:
    """Visible, ou sur le point de l'etre : un widget tout juste (re)construit (ex. colonne Focus
    rebatie par une navigation pendant que les colonnes sont masquees) n'est pas encore visible
    mais Qt l'affichera de lui-meme, faute d'avoir ete masque explicitement. Un widget masque
    expres par ailleurs (WA_WState_ExplicitShowHide + cache) n'est pas concerne."""
    return widget.isVisible() or not widget.testAttribute(Qt.WA_WState_ExplicitShowHide)


class _ViewerButtonDrag(QObject):
    """Ctrl + glisser un bouton de la rangee de la visionneuse / planche (masquer, planche, filtre,
    PureRef) : regle de l'appli pour tout deplacement — le bouton suit le curseur a 75 %
    (DRAG_GHOST_OPACITY), son emplacement d'origine reste a 25 %, le seul emplacement vise est en
    surbrillance (`settings_layout._ReorderOverlay`, axe x, pose sur une bande de la hauteur de la
    rangee). Sans Ctrl, le clic garde son sens."""

    def __init__(self, browser):
        super().__init__(browser)
        self.browser = browser
        self.press = None                    # (bouton, position globale de l'appui)
        self.overlay = None
        self.strip = None
        self.keys: list = []

    def hook(self, button):
        if not getattr(button, "_row_drag_hooked", False):
            button._row_drag_hooked = True
            button.installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() & Qt.ControlModifier:
                self.press = (obj, event.globalPosition().toPoint())
                return True                  # Ctrl : pas de clic
            return False
        if self.press is None or self.press[0] is not obj:
            return False
        if kind == QEvent.MouseMove:
            pos = event.globalPosition().toPoint()
            if self.overlay is None and (pos - self.press[1]).manhattanLength() >= 4:
                self._start(obj)
            if self.overlay is not None:
                self.overlay.follow(self.strip.mapFromGlobal(pos).x())
            return True
        if kind == QEvent.MouseButtonRelease:
            self._finish()
            return True
        return kind == QEvent.MouseButtonDblClick

    def _start(self, button):
        from types import SimpleNamespace
        from settings_layout import _ReorderOverlay
        browser = self.browser
        items = browser._viewer_row_items()
        widgets = [w for _k, w in items]
        if button not in widgets:
            self.press = None
            return
        viewport = button.parentWidget()          # le cadre « Visionneuse » de la barre de navigation
        self.keys = [k for k, _w in items]
        rects = [QRect(w.mapTo(viewport, QPoint(0, 0)), w.size()) for w in widgets]
        top = min(r.top() for r in rects)
        bottom = max(r.bottom() for r in rects)
        left = max(0, min(r.left() for r in rects) - scaled(8, 0))
        right = min(viewport.width(), max(r.right() for r in rects) + scaled(8, 0))
        strip = self.strip = QWidget(viewport)
        strip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        strip.setStyleSheet("background: transparent;")     # les autres boutons restent visibles dessous
        strip.setGeometry(left, top, max(1, right - left), bottom - top + 1)
        strip.show()
        strip.raise_()
        spans = [(r.left() - left, r.right() + 1 - left) for r in rects]
        head = SimpleNamespace(_column_spans=lambda: spans, _order=list(range(len(spans))))
        source = widgets.index(button)
        grab_dx = strip.mapFromGlobal(self.press[1]).x() - spans[source][0]
        # Voile de l'emplacement d'origine : la couleur du fond juste a gauche de la rangee.
        probe = viewport.grab(QRect(max(0, left - 2), top + (bottom - top) // 2, 1, 1)).toImage()
        self.overlay = _ReorderOverlay(strip, head, source, button.grab(), 0, grab_dx)
        self.overlay.setStyleSheet("background: transparent;")
        self.overlay.veil_color = probe.pixelColor(0, 0).name() if not probe.isNull() else C["void"]

    def _finish(self):
        overlay, strip = self.overlay, self.strip
        self.press = self.overlay = self.strip = None
        if overlay is None:
            return
        target, source = overlay.target, overlay.source
        strip.hide()
        strip.deleteLater()
        if target is not None:
            self.browser._move_viewer_button(self.keys, source, target)



def settings_window_v2_preload_enabled() -> bool:
    """Prechargement de la fenetre de reglages au lancement (coupe par PIPELINE_NO_PREBUILD : tests)."""
    return not os.environ.get("PIPELINE_NO_PREBUILD")


class _DrawingRelay(QObject):
    """Retour d'une lecture de dessin DXF / DWG faite dans un fil a part (signal en file d'attente)."""
    done = Signal(object, object, object)               # donnees du board, compte rendu, erreur


class PipelineBrowser(QMainWindow):
    _bulk_navigation = False        # _navigate_to en cours : niveaux intermediaires sans fondu ni animation

    @property
    def _project_columns_hidden(self) -> bool:
        return self.__dict__.get("_columns_hidden_flag", False)

    @_project_columns_hidden.setter
    def _project_columns_hidden(self, value):
        """Colonnes masquees (visionneuse, planche) : le filtre du bouton « precedent » de la souris n'est
        pose qu'a ce moment. Pose en permanence sur l'application, il etait appele pour CHAQUE evenement de
        l'appli (~50 000 pendant quelques clics de navigation) pour ne rien faire."""
        value = bool(value)
        self.__dict__["_columns_hidden_flag"] = value
        back = self.__dict__.get("_mouse_back")
        if back is not None:
            app = QApplication.instance()
            if value:
                app.installEventFilter(back)
            else:
                app.removeEventFilter(back)


    def __init__(self, root: Path):
        super().__init__()
        self.setWindowTitle("Pipeline Browser")
        # Sans decoration systeme : le chrome blanc/bleu de Windows (barre de
        # titre, boutons min/max/fermer natifs) est remplace par la barre
        # intrinseque de l'appli (voir TitleBar), habillee comme le reste de
        # l'interface. Le redimensionnement par les bords, perdu avec le
        # cadre systeme, est retrouve via nativeEvent (voir plus bas).
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        # Fond translucide (voir Parametres > General > "Border radius de la
        # fenetre principale") : indispensable pour qu'un rayon de bordure
        # non nul, applique plus bas en QSS sur `central`, laisse voir au
        # travers des coins au lieu de les peindre carres derriere le
        # widget arrondi. Actif en permanence (rayon 0 = coins carres, rendu
        # identique a avant) pour que le reglage marche en direct sans
        # devoir re-afficher la fenetre.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(1280, 620)
        self.columns: list[Column] = []
        # Etat courant (unique source de verite, voir _sync_collapse_state/
        # _toggle_project_columns) de repli de Type/Projets/Sous-projet, et
        # icone associee sur la colonne des vignettes (voir
        # PreviewColumn.set_toggle_state).
        self._project_columns_collapsed = False
        self._project_columns_hidden = False
        self._columns_fade = None
        self._focus_overlay = None    # objet en focus au centre (voir _start_focus_overlay)
        self._focus_src = None        # (pixmap, QRect dans le viewport) de l'objet dans l'inspecteur
        self._focus_gallery = None    # planche des images du dossier (voir _toggle_focus_gallery)
        self._viewer_entry_source = None   # double-clic sur une ligne : apercu de la ligne (depart du vol)
        self._floating_gallery_btn = None   # son bouton quand il n'y a pas de colonne Focus
        self._lightroom_btn = None          # ouvrir la photo courante dans Lightroom Classic
        self._viewer_100_btn = None         # afficher l'image a sa taille reelle
        self._recursive_btn = None          # « Récursif » : photos des sous-dossiers aussi
        self._viewer_folder: Path | None = None       # dossier de la visionneuse (liste, mode récursif)
        self._viewer_entry_folder: Path | None = None  # double-clic sur un dossier : lui, pas le parent du 1er fichier
        self._pending_folder_view = None    # (dossier, colonne) en attente du parcours récursif
        self._viewer_purs: list = []        # planches PureRef du dossier de la visionneuse
        self._pur_buttons: list = []        # un bouton « ouvrir » par planche (en haut a droite)
        # Filtres de la planche (file_filters ; le temps de la session) : bouton filtre (planche ouverte),
        # elements du filtre ecrits a cote, fenetre des filtres, fichiers des portees larges (parcours en fond).
        self._viewer_filter: dict = dict(file_filters.DEFAULT_FILTER)
        self._viewer_filter_enabled = False
        self._filter_btn = None
        self._filter_chips = None
        self._filter_window = None
        self._filter_scopes_cache: list = []
        self._scope_files: dict = {}        # dossier de la portee -> [(chemin, taille, date)]
        self._filter_task = None
        self._filter_timer = None
        self._pending_filter = None
        self._gallery_list: list = []       # fichiers montres par la planche (filtres ou non)
        self._viewer_base: list = []        # fichiers de la visionneuse avant filtre (colonne en cours)
        self._button_drag = _ViewerButtonDrag(self)   # Ctrl + glisser un bouton de la rangee
        self._focus_home = None       # place de l'objet en focus dans l'inspecteur, gardee pendant la planche
        self._select_fade = None
        self._columns_slide = None
        self._slide_snapshot = None
        # Prechauffage (voir _prewarm_snapshots) : le 1er usage des boutons de repli /
        # de masquage doit etre aussi fluide que les suivants, donc les captures
        # (et le premier rendu a froid des colonnes, ~150 ms) sont faites des que
        # l'interface se repose, pas au clic.
        self._prewarm_timer = QTimer(self)
        self._prewarm_timer.setSingleShot(True)
        self._prewarm_timer.setInterval(700)
        self._prewarm_timer.timeout.connect(self._prewarm_snapshots)
        self._columns_snapshot = None
        self._columns_epoch = 0
        # Tant que ce drapeau est vrai, la prochaine fois que Sous-projet
        # obtient une selection declenche le repli automatique une fois
        # (voir _sync_collapse_state) — desarme par un repli/depli manuel
        # (icone) pour ne pas annuler le choix de l'utilisateur tant que la
        # selection reste la meme, puis rearme des que Sous-projet perd sa
        # selection (retour en arriere).
        self._auto_collapse_armed = True
        # Signature du dernier RENDU de update_preview_stack (voir
        # _preview_style_snapshot/refresh_all_columns) — permet a
        # refresh_all_columns(rescan=False) de sauter une reconstruction
        # complete (detruit/recree jusqu'a 6 widgets, RE-SCANNE LE DISQUE :
        # vignettes/in/over/out/logiciels) quand rien de ce dont depend le
        # RENDU n'a change depuis le dernier appel — voir la remarque de
        # l'utilisateur, "gros ralentissements ... les manips sont donc
        # tres lourdes". None : jamais encore rendu, le premier appel via
        # cette voie reconstruit TOUJOURS (repli surs).
        self._last_preview_style_snapshot: str | None = None
        # Groupe IN/OVER/OUT/LOGICIELS (voir update_preview_stack) : 4
        # colonnes fantomes EMPILEES VERTICALEMENT (meme principe que
        # _preview_stack_wrapper ci-dessous) — reconstruites SEULEMENT
        # quand le contexte de navigation change reellement (voir
        # _group_context_key ci-dessous), jamais a chaque appel : ces
        # instances restent stables d'une navigation a l'autre, EXACTEMENT
        # comme Type/Projets/Sous-projet — voir la remarque de
        # l'utilisateur, "leur comportement ne fonctionne pas du tout ...
        # base toi sur les colonnes creees avant les focus".
        self._group_stack_wrapper: QWidget | None = None
        self.group_columns: list[Column] = []
        # (terminal_path, tuple(levels), work_dir_style) de la DERNIERE
        # construction reussie du groupe (voir update_preview_stack) — None
        # tant qu'aucune construction n'a encore eu lieu (repli sur : le
        # premier appel reconstruit toujours).
        self._group_context_key: object | None = None
        # Colonne du groupe IN/OVER/OUT/LOGICIELS la plus RECEMMENT
        # selectionnee (voir update_active_column/_on_group_item_selected) —
        # une SEULE des 4 doit apparaitre "focus" (fond bleu) a la fois,
        # pas les 4 independamment des qu'elles ont chacune une selection —
        # voir la remarque de l'utilisateur, capture a l'appui, "blender,
        # reference et screenshots ... ont un fond bleu alors qu'un seul
        # devrait l'avoir".
        self._last_active_group_column: Column | None = None
        # Largeur commune aux 4 colonnes du groupe (voir Column.__init__
        # user_width/on_resize, _on_group_column_resized) — MEME principe/
        # MEME raison que _preview_column_user_width plus bas (colonnes
        # RECONSTRUITES a chaque navigation) — voir la remarque de
        # l'utilisateur, "les 4 colonnes doivent avoir la meme largeur
        # constamment".
        self._group_column_user_width: int | None = None
        # Hauteur INDEPENDANTE de chacune des colonnes du groupe (voir
        # Column.__init__ user_height/on_height_resize/fill_height,
        # _on_group_height_resized), par kind ("in"/"over"/"out"/
        # "logiciels") — PAS une largeur commune : contrairement a la
        # largeur (memes proportions pour les 4), chaque colonne garde SA
        # PROPRE hauteur — voir la remarque de l'utilisateur, "je ne veux
        # pas qu'elles aient toute la meme hauteur, mais chacune leur
        # hauteur". La DERNIERE colonne de _group_column_order n'y figure
        # jamais activement (voir fill_height) : elle reste etiree jusqu'en
        # bas de la page, jamais une hauteur fixe.
        self._group_column_user_heights: dict[str, int] = {}
        # Etat du glisser de hauteur EN COURS (voir _on_group_height_resize_
        # begin/_on_group_height_resized) : (colonne du dessus, colonne du
        # dessous, sa hauteur de depart, la hauteur de depart de sa voisine)
        # — None hors glisser. Scission a 2 (voir leurs remarques) : SEULES
        # ces 2 colonnes-la sont jamais touchees, jamais tout le groupe.
        self._group_height_drag: tuple[Column, Column, int, int] | None = None
        # Configuration de chaine de navigation DU PROJET COURANT (voir
        # load_project_columns/on_selected/ColumnConfigDialog) — None tant
        # qu'aucun projet n'est selectionne OU que le projet selectionne n'a
        # pas de fichier de configuration (repli sur la chaine legacy fixe,
        # voir COLUMN_LABELS) — voir la remarque de l'utilisateur, "cette
        # configuration [doit changer] suivant les besoins de l'utilisateur".
        self._active_project_config: dict | None = None
        # Ordre d'affichage des 4 colonnes du groupe (voir update_preview_
        # stack/_on_group_reorder) — LOGICIELS en premier par defaut, voir
        # la remarque de l'utilisateur, "la colonne logiciel doit etre en
        # premiere position en haut". Reordonnable par glisser-deposer de
        # l'entete (voir Column.__init__ group_kind/on_reorder).
        self._group_column_order: list[str] = ["logiciels", "in", "over", "out"]
        # Groupe des animations de position en cours (voir
        # _reorder_group_columns_animated) — reference gardee pour ne pas
        # etre ramassee par le GC avant la fin, meme raison que Column.
        # _width_anim.
        self._group_reorder_anim: QParallelAnimationGroup | None = None
        # Colonnes fantomes PERMANENTES des vignettes (voir _PreviewBlock) :
        # jamais remplacees par une vraie colonne, contrairement au groupe
        # IN/OVER/OUT/LOGICIELS ci-dessus (dont le clic sur une ligne ouvre,
        # lui, une vraie colonne). UNE VRAIE colonne fantome SEPAREE par niveau
        # selectionne (Projets, Sous-projet), PLUS une derniere colonne
        # fantome vide (voir PreviewColumn.set_preview_block/set_empty) —
        # chacune avec son PROPRE cadre/bordure/entete (voir app_style.
        # column_style_for), empilees VERTICALEMENT dans UN SEUL conteneur
        # (voir _preview_stack_wrapper ci-dessous), lui-meme insere comme
        # UNE SEULE colonne dans columns_layout — voir la remarque de
        # l'utilisateur, "je veux les trois colonnes ... les unes sur les
        # autres" puis "chaque colonne doit avoir sa propre entete" puis,
        # apres un essai fusionnant tout dans une seule carte, "non, tu as
        # merger les deux colonnes en une seule, ce que je veux c'est deux
        # colonnes separees, une en dessous de l'autre !".
        self.image_preview_columns: list[PreviewColumn] = []
        # Conteneur vertical (QWidget+QVBoxLayout) qui heberge les colonnes
        # ci-dessus, INSERE comme un SEUL element de columns_layout — voir
        # update_preview_stack.
        self._preview_stack_wrapper: QWidget | None = None
        # Largeur choisie a la main sur la colonne Focus (voir PreviewColumn.
        # resize_begin/resize_update, _on_preview_column_resized) — vit ICI
        # (pas sur les instances PreviewColumn elles-memes) car update_
        # preview_stack() les RECONSTRUIT entierement a chaque navigation :
        # sans ce relais, tout glisser de bordure serait perdu des le clic
        # suivant. PARTAGEE par toutes (pas par niveau) : ce sont des
        # colonnes SEPAREES mais elles doivent rester alignees a la meme
        # largeur (voir PreviewColumn.set_width_external) — None = pas
        # encore ajustee a la main, retombe sur col_width("Projets") — voir
        # la remarque de l'utilisateur, "je veux pouvoir controler la
        # largeur des colonnes focus projet et sous projet en slidant les
        # bords de celles-ci".
        self._preview_column_user_width: int | None = None
        # Cle (couleurs + rayon des boutons) du dernier _apply_settings :
        # sert a ne reconstruire la feuille de style globale (voir
        # refresh_colors) que lorsque l'un des deux a vraiment change,
        # plutot qu'a chaque cran de n'importe quel slider.
        self._last_style_key = None
        # app.setStyleSheet (voir refresh_colors/refresh_style) est de
        # LOIN le poste le plus cher de tout ce rafraichissement — mesure
        # a plus de 3 SECONDES par appel une fois la fenetre de parametres
        # ouverte (des milliers de widgets, chacun avec son propre QSS
        # local a re-cascader) — voir la remarque de l'utilisateur, "il y
        # a toujours un tres gros problemes de performance dans les
        # settings". Le gate ci-dessus (style_key) evite de le rejouer
        # quand RIEN n'a change, mais durant un glisser de COULEUR, la
        # valeur change reellement a CHAQUE tick (~30ms) : ce gate seul ne
        # peut donc rien y faire. Regroupe ici les reconstructions
        # rapprochees (voir _flush_stylesheet_rebuild) : le reste de
        # refresh_colors (couleurs des colonnes/boutons individuels, DEJA
        # rapide et DEJA la source principale du retour visuel en direct)
        # continue de tourner a CHAQUE tick, seul cet appel natif couteux
        # est repousse a un rythme beaucoup plus lache — invisible a
        # l'oeil (le style GENERIQUE — boutons/scrollbars/menus — n'est de
        # toute facon pas ce qu'on regarde en glissant une pastille de
        # couleur), mais qui evite l'accumulation de secondes de latence.
        # Reperes de la barre de navigation (choix de chaque colonne) : mises a jour regroupees.
        self._crumb_timer = QTimer(self)
        self._crumb_timer.setSingleShot(True)
        self._crumb_timer.setInterval(0)
        self._crumb_timer.timeout.connect(self._refresh_crumbs)
        self._pending_stylesheet_rebuild = False
        self._stylesheet_rebuild_timer = QTimer(self)
        self._stylesheet_rebuild_timer.setSingleShot(True)
        self._stylesheet_rebuild_timer.setInterval(250)
        self._stylesheet_rebuild_timer.timeout.connect(self._flush_stylesheet_rebuild)

        # --- barre de navigation (ex barre du haut, supprimee) : racine, parcourir, presets, reglages ---
        self.root_field = QLineEdit(str(root))
        self.root_field.setFont(role_font("info", 11, 400))
        self.root_field.setFixedHeight(self._nav_input_height())
        self.root_field.setFixedWidth(scaled(190))
        self.root_field.setToolTip("Racine des projets")
        self.root_field.returnPressed.connect(self.reload)

        # Boutons de la barre : TOUS de la meme taille, chacun avec son icone (Reglages > Barre de navigation).
        self.btn_browse = IconButton("browse", role_color("buttons", "#c4cacf"), C["text"])
        self.btn_presets = IconButton("presets", role_color("buttons", "#c4cacf"), C["text"])
        # IconButton (voir la classe, juste avant TitleBar), PAS un glyphe
        # de police "⚙" : aucune police testee (sans_family(), Segoe UI
        # Symbol...) ne le rendait de facon fiable a cette taille — meme
        # correctif que pour les boutons min/max/close de TitleBar.
        self.btn_settings = IconButton("gear", role_color("buttons", "#c4cacf"), C["text"])
        # Ancien bouton de la fenetre v1 (retiree) : cache, garde pour les chemins de widgets enregistres.
        self.btn_style = IconButton("sliders", role_color("buttons", "#c4cacf"), C["text"])
        # Repli / depli des colonnes de set (ex bouton de la colonne Focus), maintenant dans la barre.
        self.btn_collapse = IconButton("dchevron_right", role_color("buttons", "#c4cacf"), C["text"])
        # Modes (demande de l'utilisateur) : visionneuse sur la selection, editeur de texte (grise tant que la
        # selection n'est pas un fichier texte, voir _sync_mode_buttons).
        self.btn_viewer = IconButton("viewer", role_color("buttons", "#c4cacf"), C["text"])
        self.btn_text_editor = IconButton("text_editor", role_color("buttons", "#c4cacf"), C["text"])
        # Board (paquet board/, facon Miro) : grise tant que la selection n'est pas un fichier .mro.
        self.btn_board = IconButton("board", role_color("buttons", "#c4cacf"), C["text"])
        # Module video (paquet fm_video/) : grise tant que la selection n'est pas une video ou une image.
        self.btn_video = IconButton("video", role_color("buttons", "#c4cacf"), C["text"])
        self.btn_video.setToolTip("Module vidéo (vidéo, séquence d'images EXR / TIFF / PNG…)")
        self.btn_video.clicked.connect(self._toggle_video)
        self._video = None
        self._video_buttons = []
        self.btn_viewer.setToolTip("Visionneuse (sélection en cours)")
        self.btn_text_editor.setToolTip("Éditeur Markdown / code (sélectionner une note, un fichier texte ou de code)")
        self.btn_board.setToolTip("Board (sélectionner un fichier .mro — clic droit dans une colonne > Créer un mro)")
        self.btn_viewer.clicked.connect(self._on_viewer_button)
        self.btn_text_editor.clicked.connect(self._toggle_md_editor)
        self.btn_board.clicked.connect(self._toggle_board)
        self._md_open = False                    # module Markdown / code (paquet mdeditor/) ouvert
        self._editor_buttons = []
        self._board = None
        self._drawing_relay = None               # lecture de dessin DXF / DWG en cours (_open_cad_drawing)
        self._board_buttons = []
        for btn in (self.btn_browse, self.btn_presets, self.btn_settings, self.btn_collapse, self.btn_viewer,
                    self.btn_text_editor, self.btn_board, self.btn_video):
            btn.setCursor(Qt.ArrowCursor)
            btn.setFlat(True)
            btn.setStyleSheet("QPushButton { background: transparent; border: none; }"
                              f"QPushButton:hover {{ background: {C['hover']}; }}")
        self.btn_browse.setToolTip("Parcourir…")
        self.btn_presets.setToolTip("Gérer les presets…")
        self.btn_settings.setToolTip("Parametres")
        self.btn_collapse.setToolTip("Replier les colonnes de set")
        self.btn_collapse.clicked.connect(lambda: self._toggle_project_columns())
        _HoverPrime(self.btn_collapse, self._prime_slide_snapshot)      # capture preparee des le survol
        self.btn_style.setToolTip("Parametres visuels")
        self.btn_style.setVisible(False)
        self.btn_browse.clicked.connect(self.browse_root)
        self.btn_presets.clicked.connect(self._open_preset_manager)
        self.btn_settings.clicked.connect(lambda: self.open_settings("general"))
        # Chemin ouvert a la derniere fermeture (voir closeEvent, go_to_last_place).
        self._last_place: Path | None = None

        self.preview_cache_progress = QProgressBar()
        self.preview_cache_progress.setFixedSize(scaled(132), scaled(15))
        self.preview_cache_progress.setTextVisible(False)
        self.preview_cache_progress.setRange(0, 1)
        self.preview_cache_progress.setValue(0)
        self.preview_cache_progress.setVisible(False)
        self.preview_cache_progress.setToolTip("Mise en cache des aperçus")
        self.preview_cache_progress.setStyleSheet(
            f"QProgressBar {{ background: {C['chrome']}; border: 1px solid {C['border']}; "
            f"border-radius: 3px; }} QProgressBar::chunk {{ background: {C['accent']}; border-radius: 2px; }}"
        )

        # Presets : menu deroulant (preset actif) dans la barre ; « Gerer les presets… » = l'icone btn_presets
        # (settings_presets.py, briques des reglages).
        import settings_window_v2
        from settings_presets import PresetPicker
        settings_window_v2.seed_window_look(ui_state.APPLIED_SETTINGS or load_settings())
        self.preset_picker = PresetPicker()
        self.preset_picker.manage.hide()
        self.preset_picker.select.setFixedHeight(self._nav_input_height())
        self.preset_picker.refresh(ui_state.APPLIED_SETTINGS or load_settings())
        self.preset_picker.presetChosen.connect(self._choose_preset)
        self.preset_picker.manageRequested.connect(self._open_preset_manager)
        self._preset_manager = None

        # --- zone des colonnes ---
        self.columns_layout = QHBoxLayout()
        self.columns_layout.setContentsMargins(0, 0, 0, 0)
        # column_gap() (pas 0 en dur) : lit deja la valeur persistee (voir
        # apply_all_settings, appele par main() AVANT la construction de
        # cette fenetre) — Fenetre de parametres > Colonnes > Distance
        # entre colonnes, voir la remarque de l'utilisateur. max(0, ...) :
        # column_gap() peut valoir -1 (voir set_column_gap/la remarque de
        # l'utilisateur, "que les bordures ne se cumulent pas"), mais
        # QBoxLayout.setSpacing() n'accepte PAS un espacement reellement
        # negatif — verifie directement, TOUTE valeur negative y retombe
        # silencieusement sur l'espacement du STYLE (6px ici, pire qu'un
        # simple 0) plutot que -1px reel. L'effet "-1" (filet non cumule)
        # passe donc par Column._suppress_left()/DetailPanel._suppress_left()
        # (chacune masque son propre bord gauche quand collee a sa voisine),
        # pas par un espacement negatif ici.
        self.columns_layout.setSpacing(scaled(max(0, column_gap()), 0))

        self.detail = DetailPanel()
        from background_status import BackgroundStatus
        self._background_status = BackgroundStatus(self.detail)
        self.detail.preview_double_clicked.connect(self._toggle_project_columns_hidden)
        self._detail_state_width = {}   # {replie: largeur de l'inspecteur} (voir _set_columns_collapsed_now)
        self._inspector_visible = False
        self.detail.hide()
        self._inspector_shortcut = QShortcut(QKeySequence("I"), self)
        self._inspector_shortcut.setContext(Qt.WindowShortcut)
        self._inspector_shortcut.activated.connect(self._toggle_inspector)

        # objectName + selecteur ID : le fond au-dela de la derniere colonne
        # (l'espace que la colonne Inspecteur, desormais a largeur fixe, ne
        # comble plus) est C["window"] ("Fond") — DISTINCT du fond de chaque
        # colonne/panneau (C["void"], peint par chacun sur lui-meme, voir
        # Column/PreviewColumn/DetailPanel), qui ne depend plus de ce widget
        # pour son propre "vide" — voir la remarque de l'utilisateur,
        # nouvelle capture annotee a l'appui (auparavant les deux etaient
        # confondus dans le meme C["void"]).
        columns_host = QWidget()
        self.columns_host = columns_host
        columns_host.setObjectName("ColumnsHost")
        columns_host.setStyleSheet(f"#ColumnsHost {{ background: {C['window']}; }}")
        host_layout = QHBoxLayout(columns_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(0)
        host_layout.addLayout(self.columns_layout)
        host_layout.addStretch(1)
        host_layout.addWidget(self.detail, 0)

        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(columns_host)
        # Molette en etat focus : image suivante / precedente (voir eventFilter).
        self.scroll.viewport().installEventFilter(self)
        # Clic dans le vide a cote de l'image en focus : elle se replie dans la planche.
        columns_host.installEventFilter(self)
        # Bouton « precedent » de la souris : sortie de la visionneuse (voir _MouseBackFilter).
        self._mouse_back = _MouseBackFilter(self)
        self._project_columns_hidden = self._project_columns_hidden   # filtre pose seulement colonnes masquees
        self._focus_wheel = 0
        self._focus_path = None       # fichier montre au centre quand il attend son apercu (voir _focus_on_file)
        _previews._PREVIEW_DECODE_MANAGER.ready.connect(self._on_focus_preview_ready)
        # Visionneuse (colonnes masquees, image seule au centre, voir _enter_viewer) : fichiers a
        # apercu du dossier et rang de celui montre ; images decodees en fond ; la colonne et
        # l'inspecteur (masques) ne suivent qu'au repos (_viewer_sync) ou au retour des colonnes.
        self._viewer_paths: list = []
        self._viewer_index = -1
        self._viewer_previews: dict = {}      # apercus des voisines non-images (PSD, 3D...), pour le ruban
        self._focus_origin_badge = QLabel(self.scroll.viewport())
        self._focus_origin_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._focus_origin_badge.setStyleSheet(
            "color: #d7e0e8; background: #30363dcc; border-radius: 3px; padding: 3px 7px; font-size: 10px;"
        )
        self._focus_origin_badge.hide()
        self._focus_images = FocusImageLoader(self)
        self._focus_images.ready.connect(self._on_focus_image_ready)
        self._viewer_sync = QTimer(self)
        self._viewer_sync.setSingleShot(True)
        self._viewer_sync.setInterval(self._VIEWER_SYNC_MS)
        self._viewer_sync.timeout.connect(self._sync_viewer_selection)
        self._large_lightroom_timer = QTimer(self)
        self._large_lightroom_timer.setInterval(10000)
        self._large_lightroom_timer.timeout.connect(self._request_current_lightroom_preview)
        # Capture des colonnes pour leur RETOUR, faite d'avance au repos dans la visionneuse (_pregrab_columns).
        self._return_grab = QTimer(self)
        self._return_grab.setSingleShot(True)
        self._return_grab.setInterval(900)
        self._return_grab.timeout.connect(self._pregrab_columns)
        self._gallery_deselected = False         # colonne deselectionnee d'avance, planche ouverte
        self._filmstrip = None
        self._viewer_keys: list = []
        self._viewer_cursor = None
        self._viewer_idle = QTimer(self)        # la pellicule revient au moindre mouvement de souris
        self._viewer_idle.setInterval(150)
        self._viewer_idle.timeout.connect(self._poll_viewer_cursor)
        self._focus_pinch = 0
        # Planches PureRef dans la visionneuse : chaque .pur est remplace par ses images (fichiers du
        # cache, voir preview_column.pur_image_files) ; image -> (planche, rang) pour suivre la colonne.
        self._pur_expansions: dict = {}         # planche -> (date, [fichiers])
        self._pur_sources: dict = {}            # image (str) -> (planche Path, rang)
        self._pur_tasks: dict = {}              # planche (str) -> PureRefImagesTask en cours
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # --- barre de statut ---
        self.path_label = QLabel("")
        import lightroom_bridge
        lightroom_bridge._signal_bus().failed.connect(self._on_lightroom_proxy_error)
        lightroom_bridge._signal_bus().updated.connect(self._on_lightroom_attribute_written)
        self._lightroom_error_connected = True
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right = QLabel("read-only")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        self.md_margin_slider = QSlider(Qt.Horizontal)
        self.md_margin_slider.setRange(0, 1000)
        self.md_margin_slider.setFixedWidth(scaled(140))
        self.md_margin_slider.setToolTip("Marge gauche et droite du module Markdown")
        self.md_margin_slider.setValue(int((ui_state.APPLIED_SETTINGS or {}).get("md_module_padding", 0)))
        self.md_margin_slider.valueChanged.connect(self._set_md_margin)
        self.md_margin_slider.hide()
        self._md_margin_timer = QTimer(self)
        self._md_margin_timer.setSingleShot(True)
        self._md_margin_timer.setInterval(300)
        self._md_margin_timer.timeout.connect(self._persist_md_margin)

        statusbar = QWidget()
        self.statusbar = statusbar
        statusbar.setFixedHeight(STATUS_HEIGHT)
        # objectName + selecteur ID : meme piege/correctif que #TitleBar.
        statusbar.setObjectName("StatusBar")
        statusbar.setStyleSheet(
            f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}"
        )
        status_layout = QHBoxLayout(statusbar)
        status_layout.setContentsMargins(10, 0, 10, 0)
        status_layout.setSpacing(12)
        status_layout.addWidget(self.path_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self.preview_cache_progress)
        status_layout.addWidget(self.status_right)
        status_layout.addWidget(self.md_margin_slider)

        self.titlebar = TitleBar(self)
        self.titlebar._background_status = self._background_status
        self.titlebar.add_tools(self.root_field, self.btn_browse, self.preset_picker, self.btn_presets,
                                self.btn_settings, self.btn_collapse, self.btn_viewer, self.btn_text_editor,
                                self.btn_board, self.btn_video)
        self._sync_mode_buttons()
        self.titlebar.refresh_sizes()
        self.titlebar.refresh_look()

        # objectName + selecteur ID : une regle "nue" (sans selecteur) posee
        # via setStyleSheet sur un widget conteneur se propage a TOUS ses
        # descendants sans style propre (fond ET bordure y compris) — un
        # "border" ici sans ce ciblage strict entourait chaque QLabel de
        # l'inspecteur d'un cadre. Le contour est peint ici meme (pas
        # seulement laisse a Windows/_apply_native_frame) : DWM ne le
        # rendait pas de facon fiable dans tous les cas (coins carres
        # compris), ce filet QSS garantit un contour visible tout autour de
        # la fenetre quel que soit le reglage de coins.
        central = QWidget()
        self.central = central
        central.setObjectName("CentralFrame")
        # Indispensable pour que le "border"/"border-radius" ci-dessous soit
        # reellement peint : sur un QWidget nu, Qt applique le fond du QSS
        # via un chemin rapide qui ignore ce flag, mais PAS la bordure — sans
        # lui, la bordure etait silencieusement ignorée (verifie pixel par
        # pixel : le bord de la fenetre restait exactement la couleur de
        # fond, jamais {C['border']}). Meme remarque que pour TitleBar/
        # Column plus bas, mais leur cas ne concernait jusque-la que le fond.
        central.setAttribute(Qt.WA_StyledBackground, True)
        central.setStyleSheet(
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {ui_state.WINDOW_RADIUS}px; }}"
        )
        layout = QVBoxLayout(central)
        # Marge de 1px (= l'epaisseur du filet ci-dessus), PAS 0 : a marge
        # nulle, les enfants (titlebar, colonnes...) sont peints PAR-DESSUS
        # la bordure de central sur ses 4 cotes (verifie pixel par pixel),
        # la rendant invisible malgre WA_StyledBackground — l'ordre de
        # peinture Qt fait passer les enfants apres le fond/bordure du
        # parent, donc un enfant a bord franc la recouvre entierement.
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.titlebar)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(statusbar)
        self.setCentralWidget(central)

        self.addAction(QAction(self, shortcut="F5", triggered=self.reload))
        self.reload()
        self._apply_native_frame()

        self._restore_window_state()
        self._idle_preview_scheduler = _IdlePreviewScheduler(self)
        self._idle_preview_scheduler.cache_progress.connect(self._update_preview_cache_progress)
        self._interface_move_mode = _InterfaceMoveMode(self)
        # Les aperçus demandés par les colonnes arrivent avant le balayage
        # automatique (actuellement optionnel) : la barre reste utile dans ce
        # cas aussi, même si le nombre total n'est pas encore connu.
        self._preview_cache_active = set()
        _previews._PREVIEW_DECODE_MANAGER.started.connect(self._preview_cache_started)
        _previews._PREVIEW_DECODE_MANAGER.ready.connect(self._preview_cache_finished)
        _previews._PREVIEW_DECODE_MANAGER.turntable_ready.connect(self._preview_cache_finished)
        import settings_element_style       # clic droit > « Override settings » sur les elements des reglages
        settings_element_style.add_listener(self._on_element_style_saved)

    def _update_preview_cache_progress(self, visible: bool, completed: int, total: int, message: str):
        """Affiche l'avancement du cache automatique sans interrompre l'interface."""
        bar = self.preview_cache_progress
        if not visible:
            bar.setVisible(False)
            return
        bar.setVisible(True)
        if total <= 0:
            bar.setRange(0, 0)
            bar.setToolTip(message or "Recherche des images à mettre en cache…")
        else:
            bar.setRange(0, total)
            bar.setValue(min(completed, total))
            bar.setToolTip(message or f"Mise en cache des images — {completed}/{total}")

    def _on_lightroom_proxy_error(self, path: str, message: str):
        self.path_label.setText(f"Lightroom · {Path(path).name} : {message}")

    def _on_lightroom_attribute_written(self, path: str, field: str):
        if field == "open":
            self.path_label.setText(f"Lightroom · {Path(path).name} ouvert en mode Développement")
            return
        labels = {"rating": "note", "color": "couleur", "status": "drapeau", "keywords": "mots-clés"}
        self.path_label.setText(f"Lightroom · {labels.get(field, field)} enregistré pour {Path(path).name}")

    def _preview_cache_started(self, path: str):
        """Affiche au moins un indicateur pendant un cache lancé par une colonne."""
        self._preview_cache_active.add(path)
        scheduler = self._idle_preview_scheduler
        if scheduler.scan_in_progress or scheduler.batch_total:
            return
        bar = self.preview_cache_progress
        bar.setRange(0, 0)
        bar.setVisible(True)
        bar.setToolTip(f"Mise en cache de {Path(path).name}")

    def _preview_cache_finished(self, path: str, *_args):
        self._preview_cache_active.discard(path)
        scheduler = self._idle_preview_scheduler
        if self._preview_cache_active or scheduler.scan_in_progress or scheduler.batch_total:
            return
        self.preview_cache_progress.setVisible(False)

    def _restore_window_state(self):
        """Reapplique la position/taille de fenetre au moment de la derniere
        fermeture (voir closeEvent). L'appli s'ouvre toujours a la racine :
        le dossier parcouru a la derniere fermeture n'est pas retrouve
        automatiquement, mais retenu pour le bouton "Dernier endroit" (voir
        go_to_last_place)."""
        state = load_window_state()
        geometry_b64 = state.get("geometry")
        if geometry_b64:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry_b64.encode("ascii")))
            except (ValueError, TypeError):
                pass
        last_path = state.get("last_path")
        self._last_place = Path(last_path) if last_path else None

    def go_to_last_place(self):
        if self._last_place is not None:
            self._navigate_to(self._last_place)

    def _navigate_to(self, target: Path):
        """Deplie les colonnes jusqu'a `target` en simulant les selections
        successives (a partir de la PREMIERE colonne, quel que soit l'endroit
        ou l'on se trouve deja), sans effet si `target` n'existe plus ou n'est
        pas sous la racine actuellement affichee. Un dossier in/over/out est
        franchi : la suite se cherche dans les colonnes du groupe IN/OVER/OUT/
        LOGICIELS, qui ouvrent ensuite leur propre colonne de contenu."""
        root = Path(self.root_field.text())
        try:
            parts = target.relative_to(root).parts
        except ValueError:
            return
        self._nav_plan = {"root": root, "parts": parts, "index": 0, "column": 0, "current": root}
        self._resume_path_navigation()

    def _resume_path_navigation(self):
        """Un niveau par tour Qt ; les colonnes en lecture reprennent par leur signal loaded."""
        plan = getattr(self, "_nav_plan", None)
        if plan is None or getattr(self, "_remote_selection", None):
            return
        if plan["index"] >= len(plan["parts"]):
            self._nav_plan = None
            if self.columns:
                for column in reversed(self.columns):
                    path = column.current_path()
                    if path is not None:
                        self.detail.show_path(path)
                        break
                last = self.columns[-1]
                QTimer.singleShot(0, lambda c=last: self._animate_column_in(c))
            return
        col_index = plan["column"]
        if not self.columns:
            self._nav_plan = None
            return
        candidates = ([self.columns[col_index]] if col_index < len(self.columns)
                      else [self.columns[-1], *self.group_columns])
        if any(c.loading or c._load_timer.isActive() for c in candidates):
            return
        part = plan["parts"][plan["index"]]
        current = plan["current"] / part
        match = column = None
        for candidate in candidates:
            for i in range(candidate.list.count()):
                item = candidate.list.item(i)
                if Path(item.data(ROLE_PATH)).name == part:
                    match, column = item, candidate
                    break
            if match is not None:
                break
        plan["index"] += 1
        plan["current"] = current
        if match is None:
            # Les dossiers de statut sont franchis dans le groupe, hors liste.
            if part.lower() not in STATUS_FOLDERS:
                self._nav_plan = None
                return
        else:
            in_group = column in self.group_columns
            is_dir = bool(match.data(ROLE_ISDIR))
            self._bulk_navigation = self._navigating_step = True
            try:
                if column.list.currentItem() is match:
                    column.reselect_current()
                else:
                    column.list.setCurrentItem(match)
            finally:
                self._bulk_navigation = self._navigating_step = False
            plan["column"] = len(self.columns) - 1 if in_group else col_index + 1
            if not is_dir:
                plan["index"] = len(plan["parts"])
        QTimer.singleShot(0, self._resume_path_navigation)

    # -- Espace au-dessus d'un element de la fenetre (clic droit la ou rien d'autre n'a de menu) --
    # Les lignes des colonnes ont leur propre ligne de menu (Column.set_item_space) ; ici, tout le
    # reste. Retenu dans les reglages (`ui_spaces`, cle = chemin du widget dans la fenetre).

    def contextMenuEvent(self, event):
        clicked = self.childAt(event.pos())
        target = space_target(clicked, self)
        key = widget_path(target, self) if target is not None else None
        if key is None:
            event.ignore()
            return
        menu = Menu(self)
        make_space_actions(menu, int(getattr(target, "_space_above_px", 0)), int(getattr(target, "_space_below_px", 0)),
                           lambda value, t=target, k=key: self._set_ui_space(t, k, value),
                           lambda value, t=target, k=key: self._set_ui_space(t, k, value, below=True),
                           widget=clicked)
        menu.exec(event.globalPos())
        event.accept()

    _UI_SPACE_KEYS = {False: "ui_spaces", True: "ui_spaces_below"}

    def _set_ui_space(self, target: QWidget, key: str, height: int, below: bool = False):
        (set_space_below if below else set_space_above)(target, height)
        name = self._UI_SPACE_KEYS[below]
        stores = self._ui_space_stores = getattr(self, "_ui_space_stores", None) or {}
        if name not in stores:
            stores[name] = dict((ui_state.APPLIED_SETTINGS or {}).get(name) or {})
        spaces = stores[name]
        if height:
            spaces[key] = int(height)
        else:
            spaces.pop(key, None)
        timer = getattr(self, "_ui_space_timer", None)
        if timer is None:
            timer = self._ui_space_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(400)
            timer.timeout.connect(self._save_ui_spaces)
        timer.start()

    def _save_ui_spaces(self):
        settings = load_settings()
        for name, spaces in (getattr(self, "_ui_space_stores", None) or {}).items():
            settings[name] = dict(spaces)
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS[name] = dict(spaces)
        save_settings(settings)

    def _apply_ui_spaces(self):
        import settings_element_style            # styles propres (« Override settings ») des elements
        settings_element_style.reapply_soon(self, ui_state.APPLIED_SETTINGS)
        for below, name in self._UI_SPACE_KEYS.items():
            for key, height in ((ui_state.APPLIED_SETTINGS or {}).get(name) or {}).items():
                target = widget_at_path(self, key)
                if target is not None and height:
                    (set_space_below if below else set_space_above)(target, int(height))
        # Style choisi a la main pour un toggle de la fenetre (clic droit > Style du toggle).
        overrides = (ui_state.APPLIED_SETTINGS or {}).get("toggle_style_overrides") or {}
        for toggle in self.findChildren(_Toggle):
            key = overrides.get(self._toggle_id(toggle) or "")
            if key:
                toggle.setStyleKey(key)

    def _toggle_id(self, toggle: QWidget) -> str | None:
        path = widget_path(toggle, self)
        return f"main|{path}" if path else None

    def _set_toggle_style(self, toggle: QWidget, key: str | None):
        toggle_id = self._toggle_id(toggle)
        if toggle_id is None:
            return
        settings = load_settings()
        overrides = dict(settings.get("toggle_style_overrides") or {})
        if key:
            overrides[toggle_id] = key
        else:
            overrides.pop(toggle_id, None)
        settings["toggle_style_overrides"] = overrides
        save_settings(settings)
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS["toggle_style_overrides"] = dict(overrides)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_ui_spaces_applied", False):
            self._ui_spaces_applied = True
            QTimer.singleShot(0, self._apply_ui_spaces)

    def closeEvent(self, event):
        video_pane = getattr(self, "_video", None)
        if video_pane is not None:                                      # module video : fils de fond arretes
            video_pane.shutdown()
        board_pane = getattr(self, "_board", None)
        if board_pane is not None and not board_pane.confirm_leave():   # board : enregistre (contenu + vue)
            event.ignore()
            return
        import mdeditor.pane as md_pane
        pane = md_pane.instance(create=False)
        if getattr(self, "_md_open", False) and pane is not None and not pane.confirm_leave():
            event.ignore()                                            # module Markdown : tout est enregistre
            return
        if pane is not None and pane.parentWidget() is None:
            pane.deleteLater()           # page prechargee sans parent : detruite avant l'application (QtWebEngine)
        automatic = getattr(self, "_automatic_tasks", None)
        if automatic is not None:
            automatic.stop()
        state = load_window_state()
        state["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        state["last_path"] = str(self.columns[-1].directory) if self.columns else ""
        save_window_state(state)
        dialog = getattr(self, "_settings_dialog_v2", None)       # fenetre sans parent : elle part avec celle-ci
        if dialog is not None:
            try:
                dialog.close()
                dialog.deleteLater()
            except RuntimeError:
                pass
        import mdeditor.css_sync as css_sync                       # feuille partagee avec Obsidian : rien en attente
        css_sync.engine().flush()
        self._nav_plan = None
        pending = getattr(self, "_remote_selection", None)
        if pending is not None:
            from column_loading import loader
            loader().cancel(pending[0], self)
            self._remote_selection = None
        for column in [*self.columns, *self.group_columns]:
            if hasattr(column, "cancel_loading"):
                column.cancel_loading()
        super().closeEvent(event)

    _RESIZE_BORDER = 6

    def nativeEvent(self, eventType, message):
        """Redonne le redimensionnement par les bords a cette fenetre sans
        decoration systeme (voir __init__) — voir app_style.resize_hit_test
        pour le detail (partage avec SettingsWindow.nativeEvent)."""
        if eventType == b"windows_generic_MSG":
            result = resize_hit_test(self, message, self._RESIZE_BORDER)
            if result is not None:
                return result
        return super().nativeEvent(eventType, message)

    def _apply_native_frame(self):
        """Coins/bordure DWM (voir app_style.apply_dwm_frame) + accrochage
        aux bords (resizable=True, seule cette fenetre est vraiment
        redimensionnable par l'utilisateur — voir nativeEvent/WM_NCHITTEST
        pour le redimensionnement par les bords, gere a la main)."""
        apply_dwm_frame(self, ui_state.WINDOW_RADIUS, C["border"], resizable=True)

    # -- gestion des colonnes ------------------------------------------

    def reload(self):
        import browser_core
        browser_core.forget_all_config()     # F5 : relecture réelle, même cache encore frais
        self._nav_plan = None
        pending = getattr(self, "_remote_selection", None)
        if pending is not None:
            from column_loading import loader
            loader().cancel(pending[0], self)
            self._remote_selection = None
        root = Path(self.root_field.text())
        self.prune_after(-1)
        self.detail.clear()
        if not _previews.is_remote_path(root) and not root.is_dir():
            self.path_label.setText(f"Introuvable : {root}")
            return
        self._project_columns_collapsed = False
        self._project_columns_hidden = False
        self._sync_viewer_chrome()
        self._auto_collapse_armed = True
        self.add_column(root, 0)
        self.path_label.setText(str(root))
        self._request_crumbs()
        self.update_preview_stack()
        self._sync_collapse_state()

    def _detach_group_stack(self):
        """Retire le groupe fantome de columns_layout SANS le detruire
        (voir add_column) — contrairement a _clear_group_stack, garde
        `self.group_columns`/`self._group_context_key` intacts : le
        prochain update_preview_stack (toujours appele juste apres, voir
        add_column) le REINSERE tel quel si le contexte de navigation n'a
        pas change, ou le detruira lui-meme via _clear_group_stack si
        besoin d'une reconstruction complete."""
        if self._group_stack_wrapper is not None:
            self.columns_layout.removeWidget(self._group_stack_wrapper)

    def _clear_group_stack(self):
        for column in self.group_columns:
            if hasattr(column, "cancel_loading"):
                column.cancel_loading()
        wrapper = self._group_stack_wrapper
        if wrapper is not None:
            # Remis a None AVANT setParent(None) : le focus qui quitte le conteneur
            # peut relancer une navigation (reentrante) qui repasse par ici.
            self._group_stack_wrapper = None
            self.columns_layout.removeWidget(wrapper)
            wrapper.setParent(None)
            wrapper.deleteLater()
        self.group_columns = []
        self._group_context_key = None
        self._last_active_group_column = None

    def _clear_image_preview_columns(self):
        wrapper = self._preview_stack_wrapper
        if wrapper is not None:
            # Remis a None AVANT setParent(None) : le focus qui quitte le conteneur
            # peut relancer une navigation (reentrante) qui repasse par ici.
            self._preview_stack_wrapper = None
            self.columns_layout.removeWidget(wrapper)
            wrapper.setParent(None)
            wrapper.deleteLater()
        self.image_preview_columns = []

    def add_column(self, directory: Path, depth: int, title: str | None = None,
                   is_focus_level: bool | None = None,
                   show_dirs: bool = True, show_files: bool = True,
                   omit_dirs: frozenset = frozenset(), omit_files: frozenset = frozenset(),
                   style_title: str | None = None, display_title: str | None = None):
        # `title` : impose un intitule (voir _open_group_folder, qui ouvre
        # un dossier in/over/out/logiciel sans rapport avec ce que la profondeur
        # suggererait normalement — pas question d'afficher "SOUS-PROJET" au
        # dessus du contenu de "in"). None (cas normal) : intitule deduit de
        # la profondeur, comme avant. `is_focus_level`/`show_dirs`/`show_files`/
        # `omit_dirs`/`omit_files` (voir Column.__init__, on_selected) :
        # SEULEMENT fournis pour un niveau de la chaine CONFIGUREE (voir
        # load_project_columns) — valeurs par defaut = comportement INCHANGE
        # pour tout le reste (Type/Sous-projet legacy/Logiciels/Contenu).
        # `style_title` (voir Column.style_title/on_selected) : cle de STYLE
        # SEPAREE du nom affiche — utilisee pour qu'un niveau de chaine
        # CONFIGUREE (nom quelconque, ex. "test1") suive quand meme le
        # reglage General > Colonnes > INTERMEDIAIRE (voir la remarque de
        # l'utilisateur, "doit controler toutes les colonnes entre celle de
        # projet et focus"). None (repli, comportement INCHANGE) : style_title
        # = title, comme avant ce reglage.
        normal_navigation = title is None
        if title is None:
            title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
        if display_title is None and normal_navigation and depth > 1:
            # En-tete DYNAMIQUE pour toute colonne "de set" APRES Type ET
            # Projets (Type garde son titre fixe, aucune colonne
            # PRECEDENTE dont reprendre le nom ; "Projets" doit lui
            # TOUJOURS s'appeler ainsi — voir la remarque de l'utilisateur,
            # "la deuxieme colonne doit toujours s'appeler PROJETS", une
            # correction de la demande initiale "dans les colonnes de set
            # le nom des colonnes correspond au nom du repertoire
            # selectionne") : `directory` EST precisement le dossier
            # SELECTIONNE dans la colonne precedente (celui dont cette
            # nouvelle colonne liste le contenu). Seulement en navigation
            # NORMALE (`title` deja None avant l'affectation ci-dessus) :
            # PAS pour _open_group_folder, qui fixe deja lui-meme son
            # propre display_title (voir sa remarque).
            display_title = directory.name
        column = Column(
            directory, title, parent=self.columns_host, is_focus_level=is_focus_level, style_title=style_title, async_load=True,
            display_title=display_title,
            show_dirs=show_dirs, show_files=show_files, omit_dirs=omit_dirs, omit_files=omit_files)
        column.selected.connect(self.on_selected)
        column.loaded.connect(self._column_loaded)
        column.activated.connect(self.on_activated)
        column.view_requested.connect(lambda path, c=column: self._view_in_viewer(path, c))
        column.folder_view_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c))
        column.folder_gallery_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c, True))
        column.recursive_requested.connect(self._set_recursive)
        beyond_chain = len(self.columns) >= self._chain_expected_total()
        self.columns.append(column)
        # Le groupe fantome IN/OVER/OUT/LOGICIELS (voir update_preview_
        # stack) peut occuper cet emplacement depuis la selection
        # precedente : le RETIRER (pas le DETRUIRE, voir _detach_group_
        # stack) avant d'ajouter la vraie colonne, sinon celle-ci se
        # retrouverait ajoutee APRES lui dans columns_layout (ordre visuel
        # casse). image_preview_column, elle, n'est PAS retiree ici : c'est
        # une colonne permanente qui doit rester juste avant celle qu'on
        # ajoute (voir update_preview_stack, qui la reconstruit a la bonne
        # position a chaque appel). update_preview_stack (appele juste
        # apres, a la fin de on_selected/_open_group_folder) le REINSERE
        # a la bonne position SANS le reconstruire si le contexte de
        # navigation n'a pas change (voir sa remarque, la remarque de
        # l'utilisateur "base toi sur les colonnes creees avant les
        # focus") — un _clear_group_stack() (destructeur) ici aurait
        # recree les 4 colonnes a CHAQUE _open_group_folder, y compris pour
        # une simple creation de dossier qui re-selectionne l'element cree.
        if not (beyond_chain and self._group_stack_wrapper is not None
                and self.columns_layout.indexOf(self._group_stack_wrapper) >= 0):
            self._detach_group_stack()
        # Contenu ouvert APRES la chaine : il se pose a la suite du groupe, deja a sa place (pas de retrait :
        # la pile n'est alors plus refaite, voir update_preview_stack).
        self.columns_layout.addWidget(column)
        # _suppress_left() (voir Column._containing_layout) a besoin que la
        # colonne soit DEJA dans columns_layout pour detecter correctement
        # sa voisine de gauche — au moment de Column.__init__ (donc de son
        # 1er refresh_header()/refresh_colors(), voir plus haut), elle n'a
        # encore AUCUN parent, _suppress_left() y renvoie donc TOUJOURS
        # False, figeant a tort un padding/bordure gauche PLEIN (jamais
        # supprime) pour toute colonne qui n'est pourtant PAS la premiere
        # de la rangee — voir la remarque de l'utilisateur, "la distance
        # entre deux colonnes est toujours deux fois plus grande que la
        # valeur du padding" : rejouer les 2 ICI, une fois REELLEMENT
        # inseree, recalcule enfin la bonne valeur.
        column.refresh_header()
        column.refresh_colors()
        self.update_active_column()
        self._sync_software_buttons()
        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _sync_software_buttons(self) -> None:
        """Dans un set, un logiciel choisi dans la colonne LOGICIELS (dossier reconnu, ex. « blender ») qui a
        un lanceur (`software_launch.LAUNCHERS`, Blender seulement pour l'instant) : TOUTES les colonnes
        ouvertes sous son dossier ont, a cote de leur punaise, un bouton a son icone qui l'ouvre dans LEUR
        dossier (« Enregistrer sous » y est deja) — demande de l'utilisateur. Les autres colonnes n'en ont pas."""
        software = None
        for group_column in self.group_columns:
            if getattr(group_column, "_group_kind", None) != "logiciels" or not shiboken6.isValid(group_column):
                continue
            selected = group_column.current_path()
            if selected is not None and entry_is_dir(selected):
                key = _previews.software_icon_key(selected.name)
                if software_launch.can_launch(key):
                    software = (key, selected)
        # Nom COMPLET du SET (tous les dossiers de la chaine, de la racine au
        # terminal) : nom du favori ajoute dans le logiciel (demande de
        # l'utilisateur), par exemple « 3d - _assets - airplane ».
        set_name = self._chain_set_name() if software is not None else None
        for column in self.columns:
            if not shiboken6.isValid(column):
                continue
            directory = column.directory
            if software is not None and (directory == software[1] or software[1] in directory.parents):
                column.set_launcher(software[0], lambda k=software[0], d=directory, n=set_name:
                                    self._launch_software(k, d, n))
            else:
                column.set_launcher(None)

    def _launch_software(self, key: str, folder: Path, set_name: str | None = None) -> None:
        """Bouton logiciel d'une colonne (voir _sync_software_buttons) : le logiciel s'ouvre dans `folder`
        (favori de sa fenetre de fichiers au nom du set)."""
        if not software_launch.launch(key, folder, set_name):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Logiciel introuvable",
                                f"Impossible de lancer {key.capitalize()} (installation introuvable).")

    def prune_after(self, index: int):
        while len(self.columns) > index + 1:
            column = self.columns.pop()
            column.cancel_loading()
            self.columns_layout.removeWidget(column)
            column.setParent(None)
            column.deleteLater()
        self._request_crumbs()

    def _request_crumbs(self):
        timer = getattr(self, "_crumb_timer", None)
        if timer is not None:
            timer.start()

    def _refresh_crumbs(self):
        """Barre de navigation : le choix (nom) de chaque colonne, dans l'ordre, jusqu'au premier sans choix ;
        visionneuse ouverte : le dossier central puis l'image regardee (`_viewer_crumb_items`)."""
        if self._project_columns_hidden and self._viewer_folder is not None:
            self.titlebar.set_crumbs(self._viewer_crumb_items())
        else:
            self.titlebar.set_crumbs(self._crumb_items())

    def _viewer_crumb_items(self) -> list:
        """Cheminement de la visionneuse, calcule sur SON etat (jamais sur les colonnes cachees, qui ne suivent
        qu'au repos — le cheminement arrivait 700 ms et plus apres l'image, signale) : les reperes des colonnes
        jusqu'au DOSSIER CENTRAL (`_viewer_folder` : la visionneuse montre ses images, sous-dossiers compris en
        mode recursif), qui a le FOCUS, puis — genre « after_focus », l'image garde tout son cheminement — les
        sous-dossiers de l'image regardee et l'image. Clic sur un dossier = il devient le dossier central
        (`_set_viewer_folder`)."""
        folder = Path(self._viewer_folder)
        items, last = [], None
        for kind, path, _column in self._crumb_entries():
            if path != folder and path not in folder.parents:
                break
            items.append((kind, path.name or str(path), lambda _c=False, p=path: self._set_viewer_folder(p)))
            last = path
        if last != folder:
            # Dossiers entre le dernier repere des colonnes (ou la racine) et le dossier central.
            base = last if last is not None else Path(self.root_field.text())
            try:
                parts = folder.relative_to(base).parts
            except ValueError:
                base, parts = folder.parent, (folder.name,)
            for part in parts:
                base = base / part
                items.append(("after", part, lambda _c=False, p=base: self._set_viewer_folder(p)))
        if items:
            kind, name, callback = items[-1]
            items[-1] = (kind + "!", name, callback)             # le dossier central a le focus
        if self._focus_gallery is None and 0 <= self._viewer_index < len(self._viewer_paths):
            path = Path(self._viewer_paths[self._viewer_index])
            if self._pur_sources.get(str(path)) is not None:     # image d'une planche PureRef
                pur = self._pur_sources[str(path)][0]
                parts, shown = self._relative_parts(Path(pur).parent, folder), _focus.display_name(path)
            else:
                parts, shown = self._relative_parts(path.parent, folder), path.name
            base = folder
            for part in parts:
                base = base / part
                items.append(("after_focus", part, lambda _c=False, p=base: self._set_viewer_folder(p)))
            items.append(("after_focus", shown, lambda _c=False: None))
        return items

    @staticmethod
    def _relative_parts(path: Path, folder: Path) -> tuple:
        try:
            return Path(path).relative_to(folder).parts
        except ValueError:
            return ()

    def _set_viewer_folder(self, folder: Path):
        """Clic sur un dossier du cheminement, visionneuse ouverte : il devient le dossier CENTRAL — la
        visionneuse (pellicule, planche) montre ses images, celles des sous-dossiers aussi si « Récursif » est
        coche ; l'image regardee est gardee si elle y est encore, sinon la 1re."""
        folder = Path(folder)
        if not self._project_columns_hidden or self._viewer_folder is None:
            return
        if folder == Path(self._viewer_folder):
            return
        if self._recursive_on():
            self._start_filter_scan(folder)                      # liste a jour, lue en fond
        elif not self._viewer_folder_files(folder):
            self.path_label.setText(f"Aucune photo directement dans {folder.name} (cocher « Récursif » "
                                    "pour celles des sous-dossiers)")
            return
        self._viewer_folder = folder
        self._viewer_base = []                                   # liste refaite meme si identique
        self._apply_viewer_base()
        self.path_label.setText(str(folder))
        self._request_crumbs()

    def _crumb_entries(self) -> list:
        """[(genre, chemin, colonne)] : voir `_crumb_items`."""
        config = self._active_project_config
        settable = config is None or bool(config.get("set_enabled", True))
        total = self._chain_expected_total()
        entries = []

        def add(kind, column):
            path = column.current_path()
            if path is None:
                return False
            entries.append((kind, path, column))
            return True

        try:
            chain = self.columns[:total]
            for column in chain:
                if not add("set" if settable else "after", column):
                    return entries
            if len(chain) < total:
                return entries
            for column in self.group_columns:
                if add("after", column):
                    break
            for column in self.columns[total:]:
                if not add("after", column):
                    break
        except RuntimeError:
            pass
        return entries

    def _crumb_items(self) -> list:
        """[(genre, nom, rappel)] : le choix de chaque colonne de la chaine (genre « set », ou « after » quand le
        projet choisi n'a pas de set), puis le dossier choisi dans LOGICIELS / IN / OVER / OUT, puis les colonnes
        ouvertes a leur suite (« after »). Le dernier a le FOCUS (genre suffixe « ! ») ; les reperes du chemin
        parcouru AU-DELA de lui sont gardes (demande de l'utilisateur : l'image affichee garde tout son
        cheminement), genre « after_focus » — tant que le chemin actuel en est le debut (`_crumb_trail`). Un clic =
        focus sur l'element de sa colonne ; sur un repere apres le focus : les colonnes vont jusqu'a lui."""
        entries = self._crumb_entries()
        items = [(kind, path.name or str(path), lambda _c=False, col=column: self._crumb_clicked(col))
                 for kind, path, column in entries]
        paths = [path for _k, path, _c in entries]
        trail = getattr(self, "_crumb_trail", None) or []
        if len(trail) > len(paths) and [p for p, _n in trail[:len(paths)]] == paths:
            beyond = trail[len(paths):]                          # meme debut : le reste est garde
        else:
            beyond = []
            self._crumb_trail = [(path, path.name or str(path)) for path in paths]
        if items:
            kind, name, callback = items[-1]
            items[-1] = (kind + "!", name, callback)
        for path, name in beyond:
            items.append(("after_focus", name, lambda _c=False, p=path: self._crumb_go(p)))
        return items

    def _crumb_go(self, path: Path):
        """Clic sur un repere APRES le focus : les colonnes vont jusqu'a lui (il prend le focus)."""
        self._navigate_to(Path(path))
        column = next((c for c in reversed([*self.columns, *self.group_columns])
                       if shiboken6.isValid(c) and c.current_path() == Path(path)), None)
        if column is not None:
            column.list.setFocus(Qt.MouseFocusReason)
            self.update_active_column()

    def _crumb_clicked(self, column):
        """Clic sur un repere du cheminement = FOCUS sur lui (demande de l'utilisateur ; avant : defocus, comme un
        re-clic) : sa ligne reste selectionnee et devient la ligne en focus, les colonnes ouvertes apres elle se
        referment et son contenu est reaffiche (meme chemin qu'une selection, `reselect_current`)."""
        if not shiboken6.isValid(column) or column.current_path() is None:
            return
        column.reselect_current()
        if shiboken6.isValid(column):
            column.list.setFocus(Qt.MouseFocusReason)
            self.update_active_column()

    def refresh_all_columns(self, rescan: bool = True, relayout_titles: set | None = None):
        """Reapplique aux colonnes existantes (largeur, delegate, polices)
        les reglages globaux courants, SANS reconstruire l'arborescence : la
        navigation en cours (profondeur, selection) reste intacte. Utilise
        par le glisser-deposer (rescan=True : le contenu du dossier a change
        sur le disque), et par la previsualisation en direct des parametres
        (voir _apply_settings, rescan=False : aucun reglage cosmetique
        (police, largeur, hauteur de ligne...) ne change le contenu d'un
        dossier — retourner sur le disque, y compris le comptage recursif
        des colonnes a vignettes, a chaque cran de slider n'apporterait
        rien et coute cher sur un partage reseau).

        `relayout_titles` (uniquement pertinent avec rescan=False, voir
        _apply_settings) : titres de colonne dont col_row_height()/
        col_spacing() ont REELLEMENT change depuis le dernier appel — les
        AUTRES colonnes sautent le doItemsLayout() de Column.relayout()
        (voir sa docstring), puisqu'un cran de slider qui ne touche qu'a une
        couleur/bordure/rayon n'a aucune raison de recalculer le sizeHint()
        de CHAQUE ligne — None (comportement par defaut, tous les autres
        appelants) relayoute TOUJOURS tout, sans cette optimisation — voir
        la remarque de l'utilisateur, "il y a des ralentissements dans les
        animations, optimise un maximum"."""
        for column in self.columns:
            # Une colonne repliee (voir Column.set_collapsed) garde une
            # largeur nulle : col_width(...) est la largeur DEPLOYEE, la
            # reappliquer ici la ferait rebondir a pleine largeur a chaque
            # glisser-deposer/reglage sans que column.collapsed n'ait change.
            # Largeur choisie a la main (voir Column._user_width) prioritaire
            # sur col_width(...) : sinon repasser sur N'IMPORTE quel reglage
            # (y compris Colonnes > Padding/Bordure, rejoue a chaque cran de
            # slider pour la previsualisation en direct) ecrasait aussitot
            # tout redimensionnement manuel par la largeur par defaut.
            if not column.collapsed:
                # _pin_column_width (voir Column._toggle_pin) EN PREMIER :
                # sans lui, tout changement de reglage (n'importe quel
                # champ de la fenetre de parametres, voir _apply_settings)
                # ecrasait aussitot la largeur FIGEE d'une colonne pinnee —
                # voir la remarque de l'utilisateur, "quand on fait une
                # modif dans les settings, ca annule toutes les valeurs
                # des colonnes qui sont pinnees".
                column.setFixedWidth(
                    column._pin_column_width or column._user_width or col_width(column.style_title))
            else:
                column.setFixedWidth(0)
            column.refresh_header()
            column.sync_uniform_sizes()            # pas uniforme si une ligne a un espace au-dessus
            delegate = column.list.itemDelegate()
            if hasattr(delegate, "refresh_fonts"):
                delegate.refresh_fonts()
            if rescan:
                column.refresh()
                # doItemsLayout() supplementaire : refresh() ci-dessus vide
                # puis repeuple la liste (clear()+addItem() par entree), sans
                # jamais rejouer explicitement la mise en page finale — voir
                # relayout() juste en dessous, qui elle le fait DEJA (pas de
                # doItemsLayout() double dans ce cas, voir la remarque de
                # l'utilisateur, "il y a des ralentissements dans les
                # animations, optimise un maximum" : ce 2e appel tournait
                # inutilement a CHAQUE cran de slider pendant la
                # previsualisation en direct, voir rescan=False plus bas).
                column.list.doItemsLayout()
            else:
                do_layout = relayout_titles is None or column.style_title in relayout_titles
                column.relayout(do_layout=do_layout)
        if rescan:
            self.update_preview_stack()
        else:
            # Gate (voir _preview_style_snapshot/la remarque de tete de
            # cette methode) : SEULEMENT pour la previsualisation en direct
            # des parametres (rescan=False, seul appelant de cette
            # branche) — sauter la reconstruction complete du groupe IN/
            # OVER/OUT/LOGICIELS/des vignettes Focus (destruction/recreation
            # de jusqu'a 6 widgets + RE-SCAN DU DISQUE) quand rien de ce
            # qu'elle utilise n'a change depuis le dernier rendu, au lieu de
            # la rejouer a CHAQUE cran de glisser de N'IMPORTE quel slider
            # de la fenetre de parametres — voir la remarque de
            # l'utilisateur, "gros ralentissements ... les manips sont donc
            # tres lourdes".
            snapshot = self._preview_style_snapshot()
            if snapshot != self._last_preview_style_snapshot:
                self.update_preview_stack()

    def update_active_column(self):
        last_selected = -1
        for i, column in enumerate(self.columns):
            if column.current_path() is not None:
                last_selected = i
        # Un clic dans une colonne du groupe IN/OVER/OUT/LOGICIELS (dossier OU
        # fichier) y laisse le focus brillant TANT QU'AUCUNE colonne ouverte
        # apres la chaine n'a de selection — comme une colonne normale, ou la
        # ligne cliquee reste en focus avant qu'on choisisse plus loin. Sans
        # ca, revenir cliquer un dossier du groupe donnait le focus a la
        # ligne de la colonne PRECEDENTE.
        group_focus = None
        group_column = self._last_active_group_column
        if group_column is not None and group_column.current_path() is not None:
            first_opened = self._chain_expected_total()
            if not any(c.current_path() is not None for c in self.columns[first_opened:]):
                group_focus = group_column
        for i, column in enumerate(self.columns):
            column.set_active(group_focus is None and i == last_selected)
        # Colonnes du groupe IN/OVER/OUT/LOGICIELS : UNE SEULE a la fois
        # doit apparaitre "focus" (voir _last_active_group_column, mis a
        # jour par _on_group_item_selected a CHAQUE clic sur l'une d'elles)
        # — pas les 4 independamment des qu'elles ont chacune une
        # selection (1ere version de ce correctif, revenue sur elle : voir
        # la remarque de l'utilisateur, capture a l'appui, "blender,
        # reference et screenshots ... ont un fond bleu alors qu'un seul
        # devrait l'avoir").
        for column in self.group_columns:
            column.set_active(column is group_focus)

    def _chain_expected_total(self) -> int:
        """Nombre de colonnes REELLES requises pour que la chaine de
        navigation soit complete (Type + Projets + niveaux configures, voir
        load_project_columns/self._active_project_config) — 3 (Type,
        Projets, Sous-projet) si aucune config (chaine legacy). Utilise a
        la fois par update_preview_stack (position des vignettes/du groupe)
        et _open_group_folder (position ou du contenu ouvert depuis ce
        groupe doit s'inserer) — voir leurs remarques, "ancrer sur la FIN
        DE LA CHAINE REQUISE, pas sur le dernier niveau focus"."""
        active_config = self._active_project_config
        if active_config is None:
            return 3
        # Toggle "set" DESACTIVE (voir ColumnConfigDialog, la remarque de
        # l'utilisateur, "si il est a 0, le set ne se fait pas, et on passe
        # directement de la colonne projets a la colonne apres les
        # logiciels/in/out/over") : ignore les niveaux configures, comme
        # une chaine "base 2" (Type+Projets seuls).
        if not active_config.get("set_enabled", True):
            return 2
        return 2 + len(active_config["columns"])

    def _chain_terminal_path(self) -> Path | None:
        """Chemin actuellement selectionne dans la DERNIERE colonne requise
        de la chaine (voir _chain_expected_total) — None tant que la chaine
        n'est pas COMPLETEMENT settee jusqu'au repertoire de travail (soit
        pas assez de colonnes reelles encore ouvertes, soit rien de
        selectionne dans la derniere). self.columns[expected_total - 1]
        (position FIXE), PAS self.columns[-1] : une fois du contenu ouvert
        depuis le groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder),
        self.columns contient des colonnes SUPPLEMENTAIRES apres la chaine
        — voir update_preview_stack, meme remarque. Partagee par
        update_preview_stack (afficher ou non les vignettes/le groupe) ET
        _sync_collapse_state (repli automatique des colonnes de set, voir
        la remarque de l'utilisateur, "une fois que l'on est sur l'espace
        de travail")."""
        expected_total = self._chain_expected_total()
        if len(self.columns) < expected_total:
            return None
        path = self.columns[expected_total - 1].current_path()
        # Un FICHIER selectionne dans cette colonne ne "sette" PAS le
        # projet — seul un REPERTOIRE marque l'espace de travail atteint
        # (voir update_preview_stack/_sync_collapse_state/_on_group_
        # height_resize_end, tous les 3 appelants) — voir la remarque de
        # l'utilisateur, "les fichiers ne sont pas des elements de set".
        if path is not None and not entry_is_dir(path):
            return None
        return path

    def _chain_set_name(self) -> str | None:
        """Nom lisible du set complet, compose de tous les dossiers choisis
        dans la chaine, de la racine du pipeline jusqu'au terminal.

        Le dossier racine lui-meme n'est pas inclus : un set
        `PIPELINE/3d/_assets/airplane` devient donc
        « 3d - _assets - airplane ».
        """
        terminal = self._chain_terminal_path()
        if terminal is None:
            return None
        root = Path(self.root_field.text())
        try:
            parts = terminal.relative_to(root).parts
        except ValueError:
            # Repli pour un chemin qui ne serait plus sous la racine courante.
            parts = (terminal.name,)
        return " - ".join(part for part in parts if part)

    def _preview_style_snapshot(self) -> str:
        """Signature LEGERE de tout ce dont depend le RENDU (pas le
        contenu/la selection, jamais impactes par un simple reglage
        cosmetique) de update_preview_stack — les 3 styles resolus qu'elle
        utilise pour construire ses widgets (vignettes Focus, groupe IN/
        OVER/OUT au style "Contenu", groupe LOGICIELS) plus l'espacement
        entre colonnes. Comparee par refresh_all_columns(rescan=False,
        voir sa remarque) pour sauter une reconstruction complete —
        detruire/recreer jusqu'a 6 widgets et RE-SCANNER LE DISQUE
        (vignettes/in/over/out/logiciels) — quand AUCUNE de ces 4 valeurs
        n'a reellement change depuis le dernier rendu, plutot qu'a CHAQUE
        cran de glisser d'un slider quelconque de la fenetre de parametres,
        meme sans aucun rapport avec ces colonnes — voir la remarque de
        l'utilisateur, "gros ralentissements ... les manips sont donc tres
        lourdes". json.dumps (pas un simple tuple) : ces styles sont des
        dict (parfois imbriques, bordures/rayons par cote/coin), non
        hashables tels quels — sort_keys=True pour une representation
        STABLE (ordre d'iteration du dict sans importance)."""
        return json.dumps(
            [
                column_style_for(PREVIEW_STACK_TITLE),
                column_style_for("Contenu"),
                column_style_for("Logiciels"),
                column_gap(),
            ],
            sort_keys=True, default=str,
        )

    def update_preview_stack(self, if_changed: bool = False):
        """La pile (vignettes Focus, groupe IN/OVER/OUT/LOGICIELS) ne depend que de la CHAINE des dossiers
        selectionnes et de l'habillage : inchangee (selection d'un fichier, navigation dans le contenu ouvert
        APRES le groupe, a n'importe quelle profondeur), elle n'est ni reconstruite ni relue. Avant, chaque clic
        sur un dossier la refaisait : 2 colonnes Focus recreees et les 4 colonnes du groupe relues sur le disque
        (~65 ms par clic en local, 4 allers-retours de plus sur un partage reseau). `if_changed` : garde pour
        les appelants, meme comportement."""
        self._columns_epoch += 1
        self._prewarm_timer.start()
        key = self._preview_stack_key()
        if not (key == getattr(self, "_preview_stack_built", None) and self._preview_stack_in_place()):
            self._update_preview_stack_impl()
            self._preview_stack_built = key
        self._enforce_hidden_columns(final=True)

    def _preview_stack_key(self):
        """Ce dont depend la pile d'apercus : colonnes de la chaine (objet, dossier, selection), config du
        projet, habillage des colonnes Focus. Les colonnes ouvertes APRES la chaine n'y sont pas : elles
        s'ajoutent a la suite du groupe sans le deplacer (voir add_column)."""
        chain = self.columns[:self._chain_expected_total()]
        return (tuple((id(c), str(c.directory), str(c.current_path())) for c in chain),
                id(self._active_project_config), self._preview_style_snapshot())

    def _preview_stack_in_place(self) -> bool:
        """Conteneurs de la pile toujours vivants et poses dans la rangee des colonnes."""
        for wrapper in (getattr(self, "_preview_stack_wrapper", None), self._group_stack_wrapper):
            if wrapper is None:
                continue
            if not shiboken6.isValid(wrapper) or self.columns_layout.indexOf(wrapper) < 0:
                return False
        return True

    def _update_preview_stack_impl(self):
        """Recalcule l'apercu empile : un bloc par colonne a vignettes
        (Projets, Sous-projet) actuellement selectionnee, dans l'ordre de
        navigation, reparti sur DEUX emplacements juste apres la derniere
        colonne A VIGNETTES :

        1. Les vignettes (voir _PreviewBlock) : DEUX colonnes fantomes
           PERMANENTES SEPAREES (image_preview_columns), une par niveau
           selectionne (Projets, Sous-projet), empilees VERTICALEMENT dans
           un conteneur commun (voir _preview_stack_wrapper), reconstruites
           ici a chaque fois a la bonne position — il n'y a pas de
           "dossier" pour des images, donc jamais de vraie colonne a cet
           endroit. Les 2 partagent le MEME style (fond/bordure/rayon/
           entete), TOUJOURS celui de l'onglet "Focus" des reglages (voir
           PreviewColumn.display_title) — voir la remarque de
           l'utilisateur, "il doit y avoir deux colonnes, une focus projet
           et l'autre focus sous projet, je veux aucune autre entete ...
           les settings 'focus' doivent controler les deux colonnes".
        2. Le groupe IN/OVER/OUT/LOGICIELS (voir group_columns) : 4 VRAIES
           colonnes fantomes (liste cliquable/navigable comme n'importe
           quelle Column, pas un simple detail statique), empilees
           VERTICALEMENT juste apres les vignettes, RECONSTRUITES ici a
           chaque fois — remplace l'ancien detail "Fichiers pour X" +
           l'ancienne colonne reelle "Logiciels" (melangeant blocs de
           statut et liste de logiciels) — voir la remarque de
           l'utilisateur, "je veux creer 4 colonnes empilees les unes sur
           les autres : colonne IN, OVER, OUT et LOGICIEL". IN/OVER/OUT :
           contenu FUSIONNE du dossier correspondant du Projet ET du
           Sous-projet selectionnes (voir status_folder_state) — voir la
           remarque de l'utilisateur, "contenu de tous les dossiers des
           repertoires IN des sections projet et sous projets". LOGICIELS :
           SEUL le niveau le plus profond (Sous-projet si selectionne,
           sinon Projet), meme source que l'ancienne colonne reelle "Logi-
           ciels" (voir _softs_subdir) — voir la remarque de l'utilisateur,
           "identique au contenu actuel". Cliquer une ligne ouvre son
           contenu dans une VRAIE colonne juste apres le groupe (voir
           _open_group_folder), navigation normale comme partout ailleurs
           dans l'appli."""
        # Signature du RENDU en cours (voir _preview_style_snapshot/
        # refresh_all_columns) : mise a jour ICI, EN PREMIER, quel que soit
        # le chemin de sortie ci-dessous (chaine incomplete -> vide, ou
        # reconstruction complete) — reste ainsi TOUJOURS en phase avec ce
        # qui est REELLEMENT affiche, peu importe quel appelant a declenche
        # ce rendu (navigation normale, glisser-deposer, ou previsualisation
        # de reglages).
        self._last_preview_style_snapshot = self._preview_style_snapshot()
        self._clear_image_preview_columns()
        if not self.columns:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # Rien n'apparait (ni vignettes, ni groupe IN/OVER/OUT/LOGICIELS)
        # tant que la chaine n'est pas COMPLETEMENT settee jusqu'au
        # repertoire de travail (voir load_project_columns/on_selected,
        # expected_total = Type+Projets+niveaux configures) — voir la
        # remarque de l'utilisateur, "ne pas faire apparaitre les colonnes
        # focus tant que le set n'est pas fini jusqu'a l'espace de
        # travail". AVANT (pas seulement pour softs_dirs comme avant) :
        # deplace ici, calcule EN PREMIER, pour pouvoir couper court avant
        # meme de construire les vignettes — un focus PARTIEL (ex.
        # seulement "Projets" selectionne, avant tout choix dans "Sous-
        # projet") ne doit plus rien afficher du tout.
        active_config = self._active_project_config
        expected_total = self._chain_expected_total()
        # Toggles "focus"/"in_over_out" (voir ColumnConfigDialog, la
        # remarque de l'utilisateur, "si il est a 0, on n'affiche pas la
        # colonne focus"/"in over et out") — True par defaut (chaine legacy
        # OU champ absent d'une config plus ancienne). Toggle "logiciels"
        # SUPPRIME (voir la remarque de l'utilisateur, "supprime le toggle
        # logiciels") — la colonne LOGICIELS du groupe est desormais
        # TOUJOURS affichee, sans condition.
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        in_over_out_enabled = True if active_config is None else active_config.get("in_over_out_enabled", True)
        if active_config is None:
            work_dir_info = WORK_DIR_TYPES[DEFAULT_WORK_DIR_TYPE]
        else:
            work_dir_info = WORK_DIR_TYPES.get(
                active_config["work_dir"]["type"], WORK_DIR_TYPES[DEFAULT_WORK_DIR_TYPE])
        # _chain_terminal_path (voir sa remarque de tete) : PAS
        # self.columns[-1] — une fois du contenu ouvert depuis le groupe
        # IN/OVER/OUT/LOGICIELS (voir _open_group_folder), self.columns
        # contient des colonnes SUPPLEMENTAIRES apres la chaine, dont le
        # dernier ne represente plus le niveau REEL terminal.
        terminal_path = self._chain_terminal_path()
        if terminal_path is None:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # Hauteurs des colonnes du groupe IN/OVER/OUT/LOGICIELS PROPRES a
        # CE dossier terminal (voir load_layout_settings/
        # _on_group_height_resize_end) — remplace INTEGRALEMENT le dict en
        # memoire (jamais fusionne avec l'ancien contenu) : ce dict est
        # TOUJOURS synchronise avec le disque a la fin de chaque glisser
        # (_on_group_height_resize_end persiste immediatement, "temps
        # reel"), donc jamais de valeur "en attente" a preserver ici — voir
        # la remarque de l'utilisateur, "le dimensionnement en hauteur des
        # colonnes de focus doit etre enregistre en temps reel et ce
        # dependant du [sous-]dossier ... d'un sous dossier a l'autre, les
        # dimensionnements seront differents".
        raw_group_heights = load_layout_settings(terminal_path).get("group_heights")
        self._group_column_user_heights = {}
        if isinstance(raw_group_heights, dict):
            for kind, height in raw_group_heights.items():
                if isinstance(height, (int, float)):
                    self._group_column_user_heights[kind] = int(height)

        entries: list[tuple[str, QPixmap, Path, object, str, Column]] = []
        for column in self.columns if focus_enabled else ():
            if not column.is_focus_level:
                continue
            path = column.current_path()
            if path is None:
                continue
            open_status = lambda p: self._open_group_folder(p)
            # `column.column_title` (5e element, "Projets"/"Sous-projet") :
            # niveau REEL de ce bloc empile — voir _PreviewBlock/la remarque
            # de l'utilisateur, "ce n'est pas deux blocs empiles, mais deux
            # colonnes empilees" (chaque bloc doit reprendre l'entete REEL
            # de SA colonne, pas un entete generique commun aux deux).
            # `column` (6e element, la VRAIE Column source) : voir
            # _PreviewBlock._rename/set_preview_block, la remarque de
            # l'utilisateur, "je veux que le comportement des colonnes
            # fonctionne de la meme maniere sur tous les points" — permet
            # au bloc Focus de retrouver la VRAIE colonne dont il reprend
            # la selection, pour y appliquer un Renommer avec la MEME
            # resynchronisation de la navigation qu'une ligne normale
            # (voir Column._rename_item : renommer puis re-selectionner
            # l'item renomme retriggue on_selected/prune_after tout seul).
            entries.append((path.name, project_thumbnail_pixmap(path), path, open_status, column.column_title, column))

        if focus_enabled and not entries:
            self._clear_group_stack()
            self._group_context_key = None
            return

        # 1. Vignettes : juste APRES LA FIN DE LA CHAINE REQUISE (Type +
        # Projets + niveaux configures, voir expected_total plus haut) —
        # PAS le dernier niveau FOCUS (un niveau configure peut avoir
        # focus=False, y compris le DERNIER juste avant le repertoire de
        # travail : dans ce cas le dernier focus-level est plus TOT dans la
        # chaine, et ancrer dessus inserait les vignettes/le groupe AU
        # MILIEU des colonnes reelles au lieu d'apres toutes — voir la
        # remarque de l'utilisateur, "si nous sommes en presence d'un
        # projet a 4 etapes avant set, les colonnes de focus devront etre a
        # la 5eme place"). PAS len(self.columns) non plus : cet indice peut
        # DEPASSER expected_total une fois du contenu ouvert depuis le
        # groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) — les
        # vignettes/le groupe doivent rester COLLES juste apres la chaine
        # requise, pas glisser plus loin derriere ce contenu deja ouvert.
        # A cet instant columns_layout contient exactement self.columns,
        # dans l'ordre : l'indice de colonne vaut l'indice de layout.
        anchor = expected_total - 1
        # Toggle "focus" DESACTIVE (voir ColumnConfigDialog, la remarque de
        # l'utilisateur, "si il est a 0, on n'affiche pas la colonne
        # focus") : aucune vignette construite, le groupe IN/OVER/OUT/
        # LOGICIELS vient alors s'inserer JUSTE apres la chaine (anchor+1)
        # au lieu de anchor+2 (pas de gap laisse par des vignettes
        # absentes).
        group_anchor_offset = 2
        if focus_enabled:
            # Conteneur vertical UNIQUE (voir _preview_stack_wrapper) : occupe
            # UNE SEULE place dans columns_layout (horizontal), mais empile ses
            # colonnes fantomes VERTICALEMENT en son sein — voir la remarque de
            # l'utilisateur, "deux colonnes separees, une en dessous de
            # l'autre". Espacement VERTICAL entre elles : meme reglage GENERAL
            # que "Distance entre colonnes" (column_gap), transpose a la
            # verticale — coherent avec l'espacement HORIZONTAL habituel entre
            # colonnes.
            wrapper = QWidget(self.columns_host)
            wrapper.setStyleSheet("background: transparent;")
            wrapper_layout = QVBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(scaled(max(0, column_gap()), 0))
            wrapper_layout.setAlignment(Qt.AlignTop)
            # EXACTEMENT une colonne par entree (Projets, Sous-projet), AUCUNE
            # autre entete (ni entete generique "Focus" a part, ni 3e colonne
            # vide) — texte d'entete "Focus <niveau>" (voir _FOCUS_LEVEL_LABEL),
            # mais STYLE (fond/bordure/rayon/police/padding/image/zone titre/
            # bouton repliement) TOUJOURS celui de PREVIEW_STACK_TITLE (l'onglet
            # "Focus" des reglages, PAS "Projets"/"Sous-projets") pour LES DEUX
            # — voir la remarque de l'utilisateur, "il doit y avoir deux
            # colonnes, une focus projet et l'autre focus sous projet, je veux
            # aucune autre entete. a savoir que les settings 'focus' doivent
            # controler les deux colonnes".
            for offset, (title, pixmap, path, open_status, level_title, source_column) in enumerate(entries):
                column = PreviewColumn(
                    PREVIEW_STACK_TITLE, parent=wrapper, on_toggle=None,
                    on_hide_columns=None,
                    on_gallery=None,     # plus de bouton image / planche (demande de l'utilisateur : touche G)
                    user_width=self._preview_column_user_width,
                    on_resize=self._on_preview_column_resized, fit_height=True,
                    display_title=_FOCUS_LEVEL_LABEL.get(level_title, PREVIEW_STACK_TITLE))
                if offset == 0:
                    column.on_buttons_placed = self._layout_viewer_buttons
                    column.set_toggle_state(self._project_columns_collapsed)
                    column.set_hide_state(self._project_columns_hidden)
                    column.set_gallery_state(self._focus_gallery is not None)
                    if column.toggle_btn is not None:
                        _HoverPrime(column.toggle_btn, self._prime_slide_snapshot)
                    if column.hide_btn is not None:
                        _HoverPrime(column.hide_btn, self._prime_fade_snapshot)
                wrapper_layout.addWidget(column)
                column.set_preview_block(title, pixmap, path, open_status, source_column)
                self.image_preview_columns.append(column)
            self._preview_stack_wrapper = wrapper
            self.columns_layout.insertWidget(anchor + 1, wrapper)
        else:
            group_anchor_offset = 1

        # 2. Groupe IN/OVER/OUT/LOGICIELS : insere JUSTE APRES LES VIGNETTES
        # (anchor + group_anchor_offset), PAS ajoute en fin (`addWidget`) — meme raison que
        # pour les vignettes ci-dessus : une colonne ouverte depuis une
        # PRECEDENTE navigation dans le groupe peut deja trainer en fin de
        # columns_layout (voir _open_group_folder) au moment ou ce groupe
        # est reconstruit, il doit malgre tout rester colle juste apres les
        # vignettes, pas relegue derriere.
        # IN/OVER/OUT : fusionne le contenu de CHAQUE colonne "de set"
        # actuellement selectionnee (Type + Projets + tout niveau
        # intermediaire configure, FOCUS ou non), pas seulement les niveaux
        # FOCUS (voir `entries` ci-dessus, qui reste lui limite aux
        # vignettes) — voir la remarque de l'utilisateur, "que si a
        # l'interieur des colonnes de set il y a un repertoire in out ou
        # over, son contenu doit se retrouver dans les colonnes
        # correspondantes". Borne a expected_total (pas self.columns en
        # entier) : au-dela, self.columns contient du contenu deja OUVERT
        # depuis le groupe IN/OVER/OUT/LOGICIELS lui-meme (voir
        # _open_group_folder) — jamais une source a refusionner ici.
        status_levels: list[Path] = []
        level_labels: list[str] = []
        for column in self.columns[:expected_total]:
            level_path = column.current_path()
            if level_path is None:
                continue
            status_levels.append(level_path)
            if column.column_title == "Projets":
                level_labels.append("projet")
            elif column.column_title == "Type":
                level_labels.append("Type")
            else:
                level_labels.append(level_path.name)
        levels = status_levels or [path for (_name, _pix, path, _open, _level, _col) in entries]
        # LOGICIELS/"Repertoire de travail" (voir add_group_column plus bas) :
        # `terminal_path`/`expected_total`/`work_dir_info` deja calcules et
        # verifies EN HAUT de la methode (voir la remarque de tete) — le
        # groupe n'est construit que lorsque la chaine est deja complete,
        # `terminal_path` est donc garanti non-None ici.
        softs_dirs = [_named_subdir(terminal_path, work_dir_info["folder_name"])]
        work_dir_display = (
            terminal_path.name if work_dir_info.get("display_from_selection")
            else work_dir_info["display"]
        )
        work_dir_style = work_dir_info["style_title"]
        work_dir_only_recognized_software = work_dir_info["only_recognized_software"]

        # Reconstruction EVITEE si le contexte de navigation n'a pas change
        # (meme dossier terminal, memes niveaux fusionnes, meme type de
        # repertoire de travail) — voir la remarque de tete de cette
        # methode et celle de l'utilisateur, "leur comportement ne
        # fonctionne pas du tout ... base toi sur les colonnes creees
        # avant les focus". AVANT ce correctif, les 4 colonnes etaient
        # DETRUITES ET RECONSTRUITES a CHAQUE appel de update_preview_stack
        # (a chaque selection, a chaque previsualisation de reglages en
        # direct) — exactement comme si Type/Projets/Sous-projet etaient
        # recrees a chaque clic — leur faisant perdre punaise/overrides de
        # menu contextuel/etat "actif" en permanence, et forçant un dict
        # separe (GROUP_ROW_HEIGHT, desormais supprime) pour simuler une
        # persistance qu'une VRAIE colonne stable obtient gratuitement.
        # `column.refresh()` (pas un no-op) : capte quand meme un
        # changement de CONTENU sur le disque (ex. refresh_all_columns
        # (rescan=True)) sans reconstruire les objets.
        # Toggle "in_over_out" DESACTIVE (voir ColumnConfigDialog, la
        # remarque de l'utilisateur, "si il est a 0, on n'affiche pas les
        # colonnes in over et out") : filtre localement,
        # self._group_column_order (ordre PERSISTE, voir _on_group_reorder)
        # reste INCHANGE pour retrouver la meme disposition une fois le
        # toggle reactive.
        active_group_order = list(self._group_column_order)
        if not in_over_out_enabled:
            active_group_order = [k for k in active_group_order if k not in ("in", "over", "out")]
        # `in_over_out_enabled` DANS la cle (pas seulement la longueur
        # comparee juste apres) : sans lui, basculer ce toggle SANS changer
        # de dossier terminal semblait "contexte inchange" et ne rejouait
        # que column.refresh() sur les colonnes DEJA existantes, sans
        # jamais ajouter/retirer les colonnes concernees.
        context_key = (terminal_path, tuple(levels), work_dir_style, in_over_out_enabled)
        if context_key == self._group_context_key and len(self.group_columns) == len(active_group_order):
            for column in self.group_columns:
                column.refresh()
            if self._group_stack_wrapper is not None:
                self.columns_layout.removeWidget(self._group_stack_wrapper)
                self.columns_layout.insertWidget(anchor + group_anchor_offset, self._group_stack_wrapper)
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.maximum())
            return

        self._clear_group_stack()
        self._group_context_key = context_key
        group_wrapper = QWidget(self.columns_host)
        group_wrapper.setStyleSheet("background: transparent;")
        group_layout = QVBoxLayout(group_wrapper)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(scaled(max(0, column_gap()), 0))
        # PAS de setAlignment(Qt.AlignTop) ici (contrairement a wrapper_
        # layout ci-dessus) : la DERNIERE colonne de l'ordre (voir
        # fill_height plus bas) porte un facteur d'etirement (stretch=1)
        # pour absorber tout l'espace restant jusqu'en bas de group_wrapper
        # — AlignTop l'en empecherait, en tassant les 4 colonnes en haut et
        # laissant un vide sous la derniere — voir la remarque de
        # l'utilisateur, "il est important que la derniere colonne aille
        # bien jusqu'en bas de la page".
        last_kind = active_group_order[-1] if active_group_order else None

        # Annotation "(projet)"/"(<nom de la colonne>)" (voir Column.
        # __init__ source_labels/ROLE_SOURCE_LABEL) : UNE par colonne "de
        # set" fusionnee, PARALLELE a `levels`/`level_labels` deja calcules
        # plus haut (voir leur remarque) — SEULEMENT pour IN/OVER/OUT (voir
        # add_group_column) : LOGICIELS n'a qu'UNE SEULE source (le niveau
        # le plus profond, voir softs_dirs), une annotation n'y aurait aucun
        # sens.

        def add_group_column(kind: str, display: str, source_dirs: list[Path], style_title: str,
                              source_labels: list[str] | None = None):
            fill = kind == last_kind
            # Identite de dossier STABLE (pas "source_dirs[0]", qui varie
            # selon la selection courante ET l'ordre des sources fusionnees)
            # : "in"/"over"/"out" pointent vers le dossier statut du niveau
            # le plus profond (deja l'une des sources fusionnees, jamais
            # synthetique), "logiciels" vers son unique source (softs_dirs,
            # deja stable) — voir la remarque de l'utilisateur, "base toi
            # sur les colonnes creees avant les focus" : necessaire pour que
            # la punaise/la hauteur de ligne/les overrides de menu
            # contextuel persistent correctement sur le MEME dossier d'une
            # navigation a l'autre, exactement comme une colonne normale.
            stable_directory = softs_dirs[0] if kind == "logiciels" else terminal_path / kind
            column = Column(
                stable_directory, style_title, parent=group_wrapper, async_load=True,
                source_dirs=source_dirs, source_labels=source_labels, display_title=display,
                user_width=self._group_column_user_width, on_resize=self._on_group_column_resized,
                on_resize_end=self._on_group_column_resize_end,
                group_kind=kind, on_reorder=self._on_group_reorder,
                user_height=self._group_column_user_heights.get(kind), on_height_resize=self._on_group_height_resized,
                on_height_resize_begin=self._on_group_height_resize_begin,
                on_height_resize_end=self._on_group_height_resize_end,
                fill_height=fill,
                only_recognized_software=(kind == "logiciels" and work_dir_only_recognized_software),
                on_group_maximize=self._on_group_maximize, on_group_equalize=self._on_group_equalize)
            column.selected.connect(lambda col, p, k=kind: self._on_group_item_selected(col, p, k))
            column.loaded.connect(self._column_loaded)
            column.activated.connect(self.on_activated)
            column.view_requested.connect(lambda path, c=column: self._view_in_viewer(path, c))
            column.folder_view_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c))
            column.folder_gallery_requested.connect(lambda path, c=column: self._view_folder_in_viewer(path, c, True))
            column.recursive_requested.connect(self._set_recursive)
            group_layout.addWidget(column, 1 if fill else 0)
            self.group_columns.append(column)

        # Chaque groupe (kind -> libelle/sources/style/annotations) construit
        # une fois, puis ajoute dans l'ORDRE COURANT (voir
        # _group_column_order, LOGICIELS premiere par defaut, reordonnable
        # par glisser-deposer de l'entete — voir la remarque de
        # l'utilisateur, "la colonne logiciel doit etre en premiere position
        # en haut ... possible de pouvoir glisser deposer ces colonnes afin
        # de pouvoir interchanger leur place ?").
        groups = {
            "logiciels": (work_dir_display, softs_dirs, work_dir_style, None),
        }
        for status_name in STATUS_FOLDERS:
            source_dirs = [status_folder_state(level, status_name)[1] for level in levels]
            # style_title = "IN"/"OVER"/"OUT" (PLUS "Contenu" partage) :
            # onglet de surcharge DEDIE desormais disponible pour chacune
            # (voir SettingsWindow._build_columns_page, la remarque de
            # l'utilisateur, "ajoute ... in over et out"). Le contenu
            # ouvert AU-DELA (voir _open_group_folder/on_selected, clic
            # sur une ligne DE ce groupe) reste lui sur le bucket generique
            # "Contenu", INCHANGE — seule la ligne DU groupe elle-meme
            # devient independamment stylable.
            groups[status_name] = (status_name.upper(), source_dirs, status_name.upper(), level_labels)
        for kind in active_group_order:
            display, source_dirs, style_title, source_labels = groups[kind]
            add_group_column(kind, display, source_dirs, style_title, source_labels)
        self._sync_group_widths()

        self._group_stack_wrapper = group_wrapper
        self.columns_layout.insertWidget(anchor + group_anchor_offset, group_wrapper)

        bar = self.scroll.horizontalScrollBar()
        bar.setValue(bar.maximum())

    def _on_group_item_selected(self, column: Column, path: Path | None, kind: str) -> None:
        """Reagit a un clic sur une ligne du groupe IN/OVER/OUT/LOGICIELS
        (voir update_preview_stack) : un dossier ouvre son contenu dans une
        VRAIE colonne suivante (voir _open_group_folder) — navigation
        normale, pas l'explorateur Windows. Un fichier n'ouvre rien mais
        s'affiche dans l'inspecteur (Column.selected n'est pas branche sur
        on_selected pour ce groupe : c'est fait ici) ; double-clic l'ouvre
        via l'application par defaut (voir Column.activated/on_activated).
        `column` (colonne SOURCE, IN/OVER/OUT/LOGICIELS) : recupere
        l'etiquette d'origine (ROLE_SOURCE_LABEL) de la ligne cliquee sur
        SON item courant, pour l'ajouter entre parentheses a l'en-tete de
        la colonne ouverte — voir _open_group_folder/la remarque de
        l'utilisateur, "pour les titres dans les entetes de colonnes apres
        in over et out, j'aimerais ajouter aussi la mention entre
        parenthese"."""
        # Une SEULE selection de groupe a la fois : les 3 AUTRES groupes
        # n'ont plus rien a voir avec le point courant des qu'on clique
        # dans CELUI-CI — deselectionnes ENTIEREMENT (pas seulement rendus
        # "non focus"), sinon une vieille selection sans rapport (ex.
        # OVER > textures cliquee il y a longtemps) restait affichee
        # coloree indefiniment — voir la remarque de l'utilisateur, capture
        # a l'appui, "le repertoire textures est encore en selection alors
        # qu'il ne devrait pas du tout".
        if path is not None and not getattr(self, "_navigating_step", False):
            self._nav_plan = None
            pending = getattr(self, "_remote_selection", None)
            if pending is not None:
                from column_loading import loader
                loader().cancel(pending[0], self)
                self._remote_selection = None
        if path is not None:
            for other in self.group_columns:
                if other is not column:
                    other.list.clearSelection()
                    other.list.setCurrentItem(None)
        # Focus brillant : la ligne cliquee (dossier ou fichier) le garde tant
        # qu'aucune colonne ouverte plus loin n'a de selection (voir
        # update_active_column) ; il passe ensuite a cette colonne, et la ligne
        # redevient "chemin" (bleu FONCE) comme une colonne ancestrale.
        if path is not None:
            self._last_active_group_column = column
        self.update_active_column()
        if path is None:
            return
        # Inspecteur (apercu image/turntable, rendu manuel du menu contextuel) :
        # comme une colonne normale (voir _on_selected_now), la ligne cliquee,
        # dossier ou fichier, y est affichee.
        self.path_label.setText(str(path))
        self._request_crumbs()
        self.detail.show_path(path)
        if not entry_is_dir(path):
            # Un fichier n'ouvre rien : le contenu deja ouvert depuis ce groupe
            # (dossier clique avant) se ferme, comme apres un fichier d'une colonne normale.
            keep_index = self._chain_expected_total() - 1
            if len(self.columns) > keep_index + 1:
                pending = self._select_fade
                if _anim_running(pending):
                    pending.finish_now()
                fade = self._fade_before_select(self._group_stack_wrapper)
                self.prune_after(keep_index)
                self.update_active_column()
                self._slide_snapshot = None
                if fade is not None:
                    QTimer.singleShot(0, lambda: self._raise_select_fade(fade))
            return
        current_item = column.list.currentItem()
        source_label = current_item.data(ROLE_SOURCE_LABEL) if current_item is not None else None
        self._open_group_folder(path, source_label=source_label)

    def _open_group_folder(self, path: Path, title: str | None = None, source_label: str | None = None) -> None:
        """Ouvre `path` (indicateur in/over/out d'un _PreviewBlock, ou une
        ligne de dossier du groupe IN/OVER/OUT/LOGICIELS, voir
        update_preview_stack/_on_group_item_selected) dans une VRAIE
        colonne juste apres la FIN DE LA CHAINE REQUISE (voir
        _chain_expected_total, PAS le dernier niveau focus — meme raison
        que dans update_preview_stack, un niveau configure peut ne pas etre
        focus meme en derniere position) — jamais `Column_index`, une
        colonne arbitraire plus loin : ce groupe est TOUJOURS positionne
        juste apres la chaine, quoi que la navigation ait deja ouvert plus
        loin. STYLE toujours le bucket generique "Contenu" (comme toute
        colonne "au-dela de la chaine", voir on_selected/COLUMN_LABELS) —
        avant ce correctif, le nom du dossier lui-meme (en capitales)
        servait AUSSI de cle de style, creant une entree COLUMN_SETTINGS
        orpheline par nom de dossier different. En-tete AFFICHE, lui,
        dynamique (voir add_column/display_title) — le nom du dossier
        SELECTIONNE dans la colonne precedente (ici, la ligne cliquee dans
        IN/OVER/OUT/LOGICIELS) — voir la remarque de l'utilisateur, "le
        titre dans les colonnes apres focus doit aussi etre le nom du
        repertoire de la colonne precedente sauf les colonnes LOGICIELS IN
        OVER OUT" (ces 4-la restent des colonnes FANTOMES distinctes,
        jamais construites ici)."""
        insert_index = self._chain_expected_total() - 1
        # Contenu deja ouvert apres le groupe : il s'estompe (voir on_selected).
        pending = self._select_fade
        if _anim_running(pending):
            pending.finish_now()
        fade = self._fade_before_select(self._group_stack_wrapper)
        self.prune_after(insert_index)
        # "(<etiquette d'origine>)" (voir source_label/ROLE_SOURCE_LABEL) —
        # MEME texte que l'annotation de la ligne cliquee dans IN/OVER/OUT,
        # mais rendu ici dans la couleur STANDARD de l'en-tete (un seul
        # QLabel, une seule couleur) — voir la remarque de l'utilisateur,
        # "avec la couleur standard de texte pour l'entete" (PAS la couleur
        # dediee aux annotations de ligne).
        display_title = f"{path.name} ({source_label})" if source_label else path.name
        self.add_column(path, insert_index + 1, title=title or "Contenu", display_title=display_title)
        self.update_active_column()
        self.update_preview_stack()
        self._sync_collapse_state()
        self._slide_snapshot = None
        if len(self.columns) > insert_index + 1:
            QTimer.singleShot(0, lambda c=self.columns[insert_index + 1]: self._animate_column_in(c))
        if fade is not None:
            QTimer.singleShot(0, lambda: self._raise_select_fade(fade))

    def _on_group_column_resized(self, new_width: int) -> None:
        """Relais de Column.resize_update pour une colonne du groupe
        IN/OVER/OUT/LOGICIELS (voir Column.__init__ user_width/on_resize,
        MEME principe que PipelineBrowser._on_preview_column_resized) :
        conserve la largeur choisie a la main pour qu'elle survive a la
        PROCHAINE reconstruction du groupe (update_preview_stack, appelee a
        chaque navigation), ET la repercute TOUT DE SUITE sur les 3 AUTRES
        colonnes du groupe — voir la remarque de l'utilisateur, "les 4
        colonnes doivent avoir la meme largeur constamment"."""
        self._group_column_user_width = new_width
        for column in self.group_columns:
            # Une colonne pinnee suit aussi : la largeur du groupe est commune,
            # punaise ou non (sinon les autres reprenaient leur largeur a la
            # reconstruction suivante). Enregistree au relachement, voir
            # _on_group_column_resize_end.
            if column._pin_active:
                column._pin_column_width = new_width
            if column.width() != new_width:
                column._user_width = new_width
                column.setFixedWidth(new_width)

    def _on_group_column_resize_end(self) -> None:
        """Fin d'un glisser de largeur dans le groupe : enregistre la largeur
        commune dans le dossier de CHAQUE colonne pinnee du groupe."""
        for column in self.group_columns:
            if column._pin_active and column._pin_column_width:
                _update_layout_setting(column.directory, "pinned_column_width", column._pin_column_width)

    def _sync_group_widths(self) -> None:
        """Largeur COMMUNE aux colonnes du groupe IN/OVER/OUT/LOGICIELS apres
        leur (re)construction : la largeur figee de la premiere colonne pinnee
        (ordre courant) l'emporte, sinon la derniere largeur choisie a la main."""
        pinned = [c._pin_column_width for c in self.group_columns if c._pin_active and c._pin_column_width]
        width = pinned[0] if pinned else self._group_column_user_width
        if not width:
            return
        self._group_column_user_width = width
        for column in self.group_columns:
            column._user_width = width
            if column._pin_active:
                column._pin_column_width = width
            column.setFixedWidth(width)

    def _on_group_height_resize_begin(self, kind: str) -> None:
        """Debut d'un glisser du bord bas d'une colonne du groupe (voir
        Column.height_resize_begin) : identifie les 2 SEULES colonnes
        concernees — `kind` ET sa voisine IMMEDIATEMENT SUIVANTE dans
        l'ordre COURANT (voir group_columns, deja dans cet ordre) — et fige
        leurs 2 hauteurs de depart. Aucune 3e colonne n'est jamais
        impliquee — voir la remarque de l'utilisateur, "les deux colonnes
        concernees doivent etre seulement les deux colonnes de part et
        d'autre de la zone de selection pour le slide" (redemande apres
        une tentative de simplification "hauteur independante par colonne"
        qui avait par erreur remplace cette regle — voir _on_group_height_
        resize_end pour la persistance par dossier, elle INCHANGEE, seule
        la MECANIQUE du glisser lui-meme revient ici a la regle d'origine)."""
        columns = self.group_columns
        idx = next((i for i, c in enumerate(columns) if c._group_kind == kind), None)
        if idx is None or idx + 1 >= len(columns):
            self._group_height_drag = None
            return
        above, below = columns[idx], columns[idx + 1]
        self._group_height_drag = (above, below, above.height(), below.height())
        # Badge de mesure (voir _show_resize_width) SUR LES 2 colonnes
        # concernees, pas seulement celle dont le bord est glisse (voir
        # Column.height_resize_begin, qui affiche deja le sien avec la cle
        # par defaut) — voir la remarque de l'utilisateur, "je veux le
        # cadre de mesure de la hauteur pour les deux colonnes concernees
        # par le redimensionnement".
        _show_resize_width(below, below.height(), key="group_below")

    def _on_group_height_resized(self, kind: str, delta: int) -> None:
        """Relais de Column.height_resize_update (voir sa remarque de tete —
        transmet un DELTA brut, ne se redimensionne pas elle-meme) : reporte
        `delta` sur la colonne du dessus (grandit/retrecit) et applique
        l'INVERSE exact a sa voisine du dessous (retrecit/grandit d'autant)
        — la somme des 2 hauteurs reste CONSTANTE, donc AUCUNE autre colonne
        ne bouge, ni en taille ni en position (contrairement a une seule
        colonne redimensionnee dans son coin, qui aurait pousse tout ce qui
        suit vers le bas) — voir la remarque de l'utilisateur, "ne pas
        descendre l'ensemble des colonnes vers le bas". Voisine du dessous
        = colonne fill_height (la derniere, voir set_group_fill_height) :
        elle n'a pas de hauteur PROPRE a faire varier en retour, son
        minimumHeight (deja pose par set_group_fill_height) suffit a lui
        seul a borner `delta` via le layout — rien a lui appliquer ici."""
        drag = self._group_height_drag
        if drag is None:
            return
        above, below, start_above, start_below = drag
        if above._group_kind != kind:
            return
        new_above = max(GROUP_COLUMN_MIN_HEIGHT, min(GROUP_COLUMN_MAX_HEIGHT, start_above + delta))
        if not below._group_fill_height:
            # Le delta REELLEMENT applicable est borne par la place que
            # peut ceder la voisine (jusqu'a SON minimum) — au-dela, la
            # colonne du dessus s'arrete de grandir plutot que de pousser
            # la voisine sous son minimum.
            max_above = start_above + (start_below - GROUP_COLUMN_MIN_HEIGHT)
            new_above = min(new_above, max_above)
            new_below = start_above + start_below - new_above
            below._group_user_height = new_below
            below.setFixedHeight(new_below)
            self._group_column_user_heights[below._group_kind] = new_below
        above._group_user_height = new_above
        above.setFixedHeight(new_above)
        # Force la mise a jour REELLE des positions/tailles AVANT de lire
        # below.mapToGlobal(...) dans _show_resize_width juste apres (voir
        # sa remarque, ancre sur le coin de `below`) — voir la remarque de
        # l'utilisateur, "pourquoi lorsque l'on change la hauteur
        # l'indication de hauteur de la colonne du bas change de position
        # si on monte ou si on descend" : SANS ce activate() ICI (deja fait
        # pour la branche fill_height, mais PAS pour celle-ci), la position
        # de `below` lue par mapToGlobal restait celle d'AVANT que `above`
        # n'ait sa NOUVELLE hauteur (setFixedHeight, juste au-dessus, ne
        # reflue le layout QUE de facon DIFFEREE) — d'ou un badge qui
        # "sautait" d'une quantite differente selon le sens du glisser (le
        # decalage accumule dependait de l'historique des positions
        # PRECEDEMMENT lues, pas de la position REELLE courante).
        wrapper = self._group_stack_wrapper
        if wrapper is not None:
            wrapper.layout().activate()
        _show_resize_width(below, below.height(), key="group_below")
        self._group_column_user_heights[kind] = new_above

    def _on_group_height_resize_end(self) -> None:
        self._group_height_drag = None
        _hide_resize_width(self, key="group_below")
        # Persiste EN TEMPS REEL (voir load_layout_settings/
        # update_preview_stack, la remarque de l'utilisateur "doit etre
        # enregistre en temps reel") dans le dossier TERMINAL courant (voir
        # _chain_terminal_path) — chaque relachement de glisser ecrit
        # immediatement le dict COMPLET (les 2 colonnes concernees, voir
        # _on_group_height_resized) : la PROCHAINE fois que ce MEME dossier
        # sera navigue, ces hauteurs seront retrouvees telles quelles.
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_maximize(self, kind: str) -> None:
        """Bouton d'entete "⤢" (voir Column.__init__ on_group_maximize) :
        agrandit `kind` au maximum, reduit les 3 AUTRES colonnes du groupe
        a la hauteur necessaire pour montrer TOUT leur contenu sans scroll
        (voir Column.group_content_height_hint) — voir la remarque de
        l'utilisateur, "un bouton qui me permette d'agrandir au maximum la
        fenetre en cours et de minimiser les autres au maximum en fonction
        de leur contenu". `layout.setStretchFactor` (PAS de reconstruction,
        voir _reorder_group_columns_animated pour le meme principe) :
        seule `kind` recoit desormais le facteur d'etirement, quelle que
        soit sa position dans l'ordre COURANT (independant de `fill_
        height`/set_group_fill_height, normalement lie a la DERNIERE
        position — ce bouton doit fonctionner sur N'IMPORTE LAQUELLE)."""
        columns = self.group_columns
        target = next((c for c in columns if c._group_kind == kind), None)
        wrapper = self._group_stack_wrapper
        if target is None or wrapper is None:
            return
        layout = wrapper.layout()
        for c in columns:
            if c is target:
                continue
            content_h = c.group_content_height_hint()
            c._group_fill_height = False
            c.setMinimumHeight(0)
            c.setMaximumHeight(_WIDGET_SIZE_MAX)
            c.setFixedHeight(content_h)
            c._group_user_height = content_h
            self._group_column_user_heights[c._group_kind] = content_h
            layout.setStretchFactor(c, 0)
        target._group_fill_height = True
        target.setMinimumHeight(0)
        target.setMaximumHeight(_WIDGET_SIZE_MAX)
        layout.setStretchFactor(target, 1)
        self._group_column_user_heights.pop(kind, None)
        layout.activate()
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_equalize(self) -> None:
        """Bouton d'entete "≡" (voir Column.__init__ on_group_equalize) :
        repartit la hauteur TOTALE actuelle du groupe (deja exactement
        celle du conteneur, une colonne l'occupant TOUJOURS en entier —
        voir fill_height) a PARTS EGALES entre les 4 — voir la remarque de
        l'utilisateur, "je veux un autre bouton pour mettre les 4 colonnes
        a exactement la meme hauteur". Aucune des 4 ne garde le facteur
        d'etirement ensuite (`setStretchFactor(c, 0)` partout) : un
        redimensionnement MANUEL derriere resterait sans effet sur le
        conteneur sinon (les 4 sont desormais TOUTES a hauteur FIXE)."""
        columns = self.group_columns
        wrapper = self._group_stack_wrapper
        if not columns or wrapper is None:
            return
        layout = wrapper.layout()
        total = sum(c.height() for c in columns) or GROUP_COLUMN_DEFAULT_HEIGHT * len(columns)
        equal = max(GROUP_COLUMN_MIN_HEIGHT, total // len(columns))
        for c in columns:
            c._group_fill_height = False
            c.setMinimumHeight(0)
            c.setMaximumHeight(_WIDGET_SIZE_MAX)
            c.setFixedHeight(equal)
            c._group_user_height = equal
            self._group_column_user_heights[c._group_kind] = equal
            layout.setStretchFactor(c, 0)
        layout.activate()
        terminal = self._chain_terminal_path()
        if terminal is not None:
            _update_layout_setting(terminal, "group_heights", dict(self._group_column_user_heights))

    def _on_group_reorder(self, source_kind: str, target_kind: str) -> None:
        """Reagit au depot de l'entete `source_kind` sur l'entete
        `target_kind` (voir Column.__init__ group_kind/on_reorder,
        eventFilter) : deplace `source_kind` juste devant `target_kind` dans
        _group_column_order, puis reordonne les colonnes EXISTANTES en
        animant leur glissement (voir _reorder_group_columns_animated) —
        voir la remarque de l'utilisateur, "possible de pouvoir glisser
        deposer ces colonnes afin de pouvoir interchanger leur place ?"."""
        if source_kind == target_kind or source_kind not in self._group_column_order:
            return
        order = self._group_column_order
        order.remove(source_kind)
        order.insert(order.index(target_kind), source_kind)
        self._reorder_group_columns_animated()

    def _reorder_group_columns_animated(self, duration: int = 220) -> None:
        """Reordonne les widgets DEJA CONSTRUITS du groupe IN/OVER/OUT/
        LOGICIELS (voir group_columns) selon le nouvel ordre de
        _group_column_order, SANS reconstruction (leur contenu ne change
        pas, seule leur place change) : chacune glisse de son ancienne
        position vers la nouvelle plutot que de sauter instantanement — voir
        la remarque de l'utilisateur, "j'aimerai egalement une animation des
        colonnes qui s'interchange lorsque l'on depose la colonne".

        removeWidget()+addWidget() (pas insertWidget a un index precis) :
        reordonne le layout ENTIER, dans l'ordre d'iteration de
        _group_column_order, en une passe — plus simple qu'un deplacement
        relatif d'UN SEUL item. Le role fill_height (voir Column.
        set_group_fill_height) suit aussi l'ordre : si la colonne qui
        devient DERNIERE change, celle qui l'etait perd sa place etiree
        (reprend une hauteur fixe) et la nouvelle derniere l'acquiert —
        voir la remarque de l'utilisateur, "il est important que la
        derniere colonne aille bien jusqu'en bas de la page". Anime la
        geometrie ENTIERE (pas seulement la position) : la colonne qui
        change de role fill_height change aussi de TAILLE, pas seulement de
        place. layout.activate() force le recalcul SYNCHRONE des geometries
        (sinon les nouvelles valeurs ne seraient connues qu'au prochain
        passage par la boucle d'evenements, une fois l'animation deja
        demarree sur les anciennes)."""
        wrapper = self._group_stack_wrapper
        if wrapper is None or not self.group_columns:
            self.update_preview_stack()
            return
        by_kind = {c._group_kind: c for c in self.group_columns}
        old_geometries = {c: c.geometry() for c in self.group_columns}
        layout = wrapper.layout()
        new_last_kind = self._group_column_order[-1] if self._group_column_order else None
        for kind in self._group_column_order:
            column = by_kind.get(kind)
            if column is None:
                continue
            layout.removeWidget(column)
            layout.addWidget(column, 1 if kind == new_last_kind else 0)
            column.set_group_fill_height(kind == new_last_kind)
        layout.activate()
        self.group_columns = [by_kind[k] for k in self._group_column_order if k in by_kind]

        if getattr(self, "_group_reorder_anim", None) is not None:
            self._group_reorder_anim.stop()
        group = QParallelAnimationGroup(self)
        for column, old_geom in old_geometries.items():
            new_geom = column.geometry()
            if new_geom == old_geom:
                continue
            column.setGeometry(old_geom)
            anim = QPropertyAnimation(column, b"geometry")
            anim.setDuration(duration)
            anim.setStartValue(old_geom)
            anim.setEndValue(new_geom)
            anim.setEasingCurve(QEasingCurve.InOutCubic)
            group.addAnimation(anim)
        # Garder la reference : sans elle, le GC Python peut detruire le
        # groupe avant la fin de l'animation (meme piege que Column.
        # _animate_width).
        self._group_reorder_anim = group
        group.start()

    def on_selected(self, column: Column, path: Path | None):
        """Si des colonnes sont deja deployees apres `column`, elles s'estompent
        toutes ensemble pendant que la navigation s'applique
        et que la nouvelle colonne sort de dessous."""
        if column not in self.columns:
            # Colonne deja retiree (signal emis pendant sa destruction, ou focus
            # passe a une liste pendant une reconstruction) : rien a naviguer.
            return
        if not getattr(self, "_navigating_step", False):
            self._nav_plan = None
        previous = getattr(self, "_remote_selection", None)
        if previous is not None:
            from column_loading import loader
            loader().cancel(previous[0], self)
            self._remote_selection = None
        if path is not None and _previews.is_remote_path(path) and entry_is_dir(path):
            from column_loading import loader
            service = loader()
            if not getattr(self, "_remote_selection_connected", False):
                service.ready.connect(self._navigation_data_ready)
                self._remote_selection_connected = True
            excluded = frozenset(STATUS_FOLDERS)
            key = service.key([path], excluded)
            cached = service.cached(key)
            if cached is None:
                self._remote_selection = (key, column, path)
                self.path_label.setText(str(path))
                self._request_crumbs()
                service.request(key, [path], excluded, self)
                return
        pending = self._select_fade
        if _anim_running(pending):
            pending.finish_now()
        overlay = None if self._bulk_navigation else self._fade_before_select(column)
        self._on_selected_now(column, path)
        if overlay is not None:
            # Au-dessus de l'apparition (creee en differe par _on_selected_now) : l'ancien
            # contenu s'estompe PENDANT que la nouvelle colonne sort de dessous.
            QTimer.singleShot(0, lambda: self._raise_select_fade(overlay))

    def _navigation_data_ready(self, key, data, error):
        pending = getattr(self, "_remote_selection", None)
        if pending is None or pending[0] != key:
            return
        self._remote_selection = None
        from column_loading import loader
        loader().cancel(key, self)
        _, column, path = pending
        if column not in self.columns or column.current_path() != path:
            return
        if data is None or data.errors.get(str(path)):
            error = error or data.errors.get(str(path), "")
            self.path_label.setText(f"{path} — {error}")
            self._nav_plan = None
            return
        self._navigating_step = bool(getattr(self, "_nav_plan", None))
        try:
            self.on_selected(column, path)
        finally:
            self._navigating_step = False
        self._resume_path_navigation()

    def _column_loaded(self):
        """Métadonnées de l'inspecteur reprises du scan ; jamais un second scan GUI."""
        path = getattr(self.detail, "_current_path", None)
        if path:
            self.detail._fill_folder_count(path, scan=False)
        if getattr(self, "_nav_plan", None):
            QTimer.singleShot(0, self._resume_path_navigation)

    def on_reclicked(self, column: Column):
        """Clic sur la ligne DEJA selectionnee de `column` (voir FileListWidget.mouseReleaseEvent) :
        elle est deselectionnee (la colonne perd son focus) et TOUTES les colonnes ouvertes apres elle
        se referment, en fondu ; l'inspecteur se vide. Colonne normale : meme chemin qu'une selection
        vide (on_selected avec None). Colonne du groupe IN/OVER/OUT/LOGICIELS : le contenu ouvert
        depuis elle se ferme, le groupe reste."""
        if column.current_path() is None:
            return
        if column in self.columns:
            column.list.clearSelection()
            column.list.setCurrentItem(None)        # -> on_selected(column, None) : fondu + fermeture
            return
        if column not in self.group_columns:
            return
        pending = self._select_fade
        if _anim_running(pending):
            pending.finish_now()
        keep_index = self._chain_expected_total() - 1
        fade = self._fade_before_select(self._group_stack_wrapper) if len(self.columns) > keep_index + 1 else None
        self.prune_after(keep_index)
        column.list.blockSignals(True)
        column.list.clearSelection()
        column.list.setCurrentItem(None)
        column.list.blockSignals(False)
        column.list.viewport().update()
        self._last_active_group_column = None
        self.detail.clear()
        self.update_active_column()
        self._sync_collapse_state()
        self._slide_snapshot = None
        if fade is not None:
            QTimer.singleShot(0, lambda: self._raise_select_fade(fade))

    def _raise_select_fade(self, overlay):
        try:
            if _anim_running(overlay):
                overlay.raise_()
        except RuntimeError:
            pass

    def _fade_before_select(self, column):
        """`column` : widget apres lequel le contenu deja ouvert s'estompe (une colonne,
        ou le bloc IN/OVER/OUT/LOGICIELS)."""
        try:
            if (column is None or not self.isVisible() or self._project_columns_hidden
                    or _anim_running(self._columns_fade)):
                return None
            if _anim_running(self._columns_slide):
                # Clic pendant un glissement (apparition de la colonne precedente,
                # repli auto...) : on le termine (etat final pose) puis on capture.
                # L'abandonner faisait disparaitre l'ancien contenu sans fondu.
                self._columns_slide.finish_now()
            self.columns_layout.activate()
            rect = self._columns_visible_rect()
            viewport = self.scroll.viewport()
            if rect.isEmpty() or not column.isVisible():
                return None
            column_right = column.mapTo(viewport, QPoint(0, 0)).x() - rect.x() + column.width()
            spans = [span for span in self._column_spans(rect) if span[0] >= column_right]
            if not spans:
                return None
            x0 = spans[0][0]
            target = QRect(rect.x() + x0, rect.y(), rect.width() - x0, rect.height())
            # Seulement la partie qui s'estompe (capturer toute la zone puis la recouper repeignait aussi les
            # colonnes de gauche, de plus en plus nombreuses avec la profondeur).
            pixmap = viewport.grab(target)
            overlay = _FadeOverlay(viewport, pixmap, target, 1.0, 0.0, 520,
                                   on_done=lambda: setattr(self, "_select_fade", None))
            # Pas de set_spans : l'ancien contenu s'estompe d'un bloc (et non colonne apres colonne).
            overlay.show()
            overlay.raise_()
            self._select_fade = overlay
            return overlay
        except RuntimeError:
            return None

    def _on_selected_now(self, column: Column, path: Path | None):
        index = self.columns.index(column)
        # Une selection dans une colonne NORMALE reprend le focus brillant au
        # groupe IN/OVER/OUT/LOGICIELS (voir update_active_column).
        self._last_active_group_column = None
        # Revenir sur une colonne de la CHAINE (pas sur un contenu ouvert
        # apres le groupe) ferme le contenu ouvert : la selection restee dans
        # IN/OVER/OUT/LOGICIELS n'a plus lieu d'etre (sinon "Claude" gardait
        # un fond de selection apres un clic sur "notes").
        if index < self._chain_expected_total():
            for group_column in self.group_columns:
                if group_column.current_path() is not None:
                    group_column.list.clearSelection()
                    group_column.list.setCurrentItem(None)
        self.prune_after(index)
        # Configuration de chaine (voir load_project_columns) : (re)lue
        # UNIQUEMENT quand c'est la colonne Projets elle-meme qui vient
        # d'etre cliquee — None si aucune selection (repli legacy) ou si ce
        # projet n'a pas de fichier de configuration — voir la remarque de
        # tete de _active_project_config. REMISE A None des que "Type"
        # change de selection : sans ca, une configuration "base 2" (voir
        # ColumnConfigDialog.MIN_STEPS) restait ACCROCHEE au projet
        # PRECEDENT tant que "Projets" n'avait pas encore ete recliquee —
        # voir la remarque de l'utilisateur, "quand je suis sette par
        # exemple dans bib/houdini en base 2 et que je reviens en 3d des
        # colonnes disparaissent" : reselectionner "Type" (depth=1,
        # ajoute TOUJOURS "Projets" via la logique GENERIQUE, jamais
        # pilotee par une config de projet) tombait alors, a tort, dans la
        # branche "chaine configuree" du bloc plus bas (index=0 < expected_
        # total-1, calcule depuis ce config PERIME) avec level_index=-1 —
        # `config["columns"][-1]` levait IndexError sur une liste VIDE
        # (base 2), interrompant on_selected APRES le prune_after mais
        # AVANT de rajouter la nouvelle colonne "Projets" : elle
        # disparaissait alors purement et simplement, sans jamais
        # revenir.
        if column.column_title == "Type":
            self._active_project_config = None
        elif column.column_title == "Projets":
            self._active_project_config = load_project_columns(path) if path is not None else None
        if path is None:
            self.detail.clear()
            self.update_active_column()
            self._sync_mode_buttons()
            # Deselection : la pile n'est refaite que si la chaine a change (deselectionner un fichier, ex.
            # sortie de la planche, la reconstruisait pour rien : ~95 ms au clic).
            self.update_preview_stack(if_changed=True)
            self._sync_collapse_state()
            return
        self.path_label.setText(str(path))
        self._request_crumbs()
        if not self._bulk_navigation:
            self.detail.show_path(path)
        self._sync_mode_buttons()
        is_dir = entry_is_dir(path)          # type connu par la lecture du dossier : pas d'acces disque
        if is_dir:
            depth = index + 1
            config = self._active_project_config
            # `index < expected_total - 1` (PAS juste `config is not None`) :
            # la chaine CONFIGUREE ne pilote QUE les colonnes ENCORE DANS
            # la chaine elle-meme (avant le repertoire de travail) — au-
            # dela (contenu ouvert depuis le groupe fantome IN/OVER/OUT/
            # LOGICIELS, voir _open_group_folder, ou tout niveau descendu
            # ENSUITE), la navigation doit rester GENERIQUE et illimitee,
            # exactement comme en legacy — voir la remarque de
            # l'utilisateur, "quand on navigue de dossier en dossier, au
            # bout d'un moment tu ne crees plus de colonnes, comme si tu
            # avais mis une limite, je veux supprimer cette limite" :
            # AVANT ce correctif, `level_index < len(columns_cfg)` restait
            # FAUX pour TOUJOURS des qu'on descendait plus loin que la
            # chaine configuree elle-meme (son index ne fait QUE croitre),
            # bloquant silencieusement toute colonne suivante dans une
            # BRANCHE de contenu ouverte apres le groupe.
            expected_total = self._chain_expected_total()
            # `index >= 1` (garde-fou EN PLUS de la remise a None ci-dessus,
            # voir sa remarque) : depth=1 (index=0, "Type") ajoute TOUJOURS
            # "Projets" par la logique GENERIQUE plus bas, jamais par la
            # chaine configuree d'un projet — quel que soit `config`,
            # level_index (= depth - 2) y serait negatif.
            if config is not None and index >= 1 and index < expected_total - 1:
                # Chaine CONFIGUREE (voir ColumnConfigDialog) : depth 2 =
                # 1er niveau configure (config["columns"][0]), etc. Chaque
                # niveau pointe vers un sous-dossier au nom FIXE (voir
                # _named_subdir) — la colonne liste ensuite son CONTENU
                # (filtre par show_dirs/show_files/omit_dirs/omit_files),
                # l'utilisateur clique une entree pour descendre — voir la
                # remarque de l'utilisateur, "chaque colonne configuree
                # pointe vers un nom de dossier fixe ... la colonne liste
                # le contenu ... filtre par les options Afficher/Omettre".
                level_index = depth - 2
                col_cfg = config["columns"][level_index]
                child_dir = _named_subdir(path, col_cfg["name"])
                # style_title="Sous-projet" (voir Column.style_title,
                # settings_window "INTERMEDIAIRE") : le NOM affiche
                # reste celui choisi par l'utilisateur (title=col_cfg
                # ["name"], ex. "test1" — identite/annotations
                # inchangees), mais l'APPARENCE (hauteur de ligne,
                # police, couleurs, bordures, padding...) suit TOUJOURS
                # le MEME reglage General > Colonnes > INTERMEDIAIRE,
                # quel que soit le nombre de niveaux configures — voir
                # la remarque de l'utilisateur, "doit controler toutes
                # les colonnes entre celle de projet et focus" : sans
                # ca, un titre inconnu retombait sur le bucket
                # generique "Contenu" (voir _col_key), partage a tort
                # avec les colonnes fantomes IN/OVER/OUT.
                self.add_column(
                    child_dir, depth, title=col_cfg["name"],
                    is_focus_level=col_cfg["focus"], style_title="Sous-projet",
                    show_dirs=col_cfg["show_dirs"], show_files=col_cfg["show_files"],
                    omit_dirs=frozenset(n.lower() for n in col_cfg["omit_dirs"]),
                    omit_files=frozenset(n.lower() for n in col_cfg["omit_files"]),
                    # En-tete DYNAMIQUE (voir add_column/la remarque de
                    # l'utilisateur, "le nom des colonnes correspond au nom
                    # du repertoire selectionne dans la colonne
                    # precedente") : `path` est le dossier SELECTIONNE dans
                    # la colonne precedente — `child_dir` (son contenu
                    # FIXE, ex. "test1") n'aurait ici aucun rapport.
                    display_title=path.name)
            elif config is not None and index == expected_total - 1:
                # Dernier niveau configure ATTEINT (`column` EST le niveau
                # terminal, pas encore de contenu ouvert au-dela) — comme
                # "Logiciels" en legacy, pas de vraie colonne ici, le
                # groupe fantome (update_preview_stack) gere le
                # "Repertoire de travail" (config["work_dir"]).
                pass
            else:
                # Legacy (config is None) : `depth` reste ALIGNE sur
                # COLUMN_LABELS par construction (Type/Projets/Sous-projet/
                # Logiciels/Contenu, expected_total TOUJOURS 3) — depth 3
                # ("Logiciels") reste donc le seul et unique endroit ou
                # sauter l'ajout d'une VRAIE colonne : elle fait partie du
                # groupe fantome IN/OVER/OUT/LOGICIELS (voir update_preview_
                # stack), reconstruit a partir de la selection courante.
                #
                # Chaine CONFIGUREE (config is not None) : tout ce qui
                # atteint CETTE branche est du contenu ouvert AU-DELA du
                # terminal (voir _open_group_folder, puis toute descente
                # ulterieure) — le terminal lui-meme est deja gere par le
                # "elif index == expected_total - 1" ci-dessus. `depth` n'y
                # est PLUS forcement aligne avec COLUMN_LABELS des que "set"
                # est desactive ou que le nombre de niveaux configures
                # differe de 1 (voir _chain_expected_total) : y reappliquer
                # le lookup COLUMN_LABELS/le test SOFTWARE_COLUMN_LABEL
                # pouvait a tort retomber sur "Logiciels" et sauter
                # l'ajout — voir la remarque de l'utilisateur, "on ne doit
                # pas avoir de limite de repertoire quand le set est
                # desactive, actuellement je ne peux pas aller dans plus de
                # deux repertoire". Toujours le bucket generique "Contenu"
                # ici (comme _open_group_folder), jamais de lookup par depth.
                if config is None:
                    title = COLUMN_LABELS[depth] if depth < len(COLUMN_LABELS) else "Contenu"
                    if title != SOFTWARE_COLUMN_LABEL:
                        self.add_column(path, depth)
                else:
                    self.add_column(path, depth, title="Contenu")
        self.update_active_column()
        self._sync_collapse_state()
        self.update_preview_stack(if_changed=not is_dir)   # un fichier : pile refaite si la chaine change
        self._slide_snapshot = None   # les colonnes de droite ont change : capture perimee
        if self._bulk_navigation:
            return                     # navigation directe (_navigate_to) : seule la derniere colonne apparait
        if len(self.columns) > index + 1:
            QTimer.singleShot(0, lambda c=self.columns[index + 1]: self._animate_column_in(c))
        else:
            # Pas de nouvelle vraie colonne (dernier niveau atteint) : c'est le groupe
            # IN/OVER/OUT/LOGICIELS ou les colonnes Focus qui apparaissent ; ils sortent
            # de dessous de la meme facon (sinon ils surgissaient sous le fondu).
            QTimer.singleShot(0, lambda c=column: self._animate_column_in(self._widget_after(c)))

    def _widget_after(self, widget):
        """Premier widget visible place apres `widget` dans columns_layout, ou None."""
        found = False
        for i in range(self.columns_layout.count()):
            item = self.columns_layout.itemAt(i).widget()
            if item is None:
                continue
            if found and item.isVisible() and item.width() > 0:
                return item
            if item is widget:
                found = True
        return None

    def _animate_column_in(self, column):
        """Apparition d'une colonne nouvellement ajoutee : meme mouvement que le
        depliage des colonnes de set (voir _SlideOverlay) — la colonne et ce qui la
        suit sortent de SOUS la colonne precedente (fixe), avec une ombre portee. Joue sur des
        captures de l'etat final ; les colonnes de gauche ne bougent pas."""
        try:
            # `column` : une colonne, ou le bloc IN/OVER/OUT/LOGICIELS ou Focus (voir _widget_after).
            if column is None or not shiboken6.isValid(column):
                return
            if (not (column in self.columns or column in (self._group_stack_wrapper, self._preview_stack_wrapper))
                    or not self.isVisible() or self._project_columns_hidden
                    or column.width() <= 0 or getattr(column, "collapsed", False)
                    or _anim_running(self._columns_slide)):
                return
            self.columns_layout.activate()
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.maximum())
            viewport = self.scroll.viewport()
            x = column.mapTo(viewport, QPoint(0, 0)).x()
            # Le fondu de l'ancien contenu (voir on_selected) est un enfant du viewport :
            # il serait recopie dans la capture. On le retire le temps de la prise.
            fade = self._select_fade
            fade_up = _anim_running(fade) and fade.isVisible()
            if fade_up:
                fade.hide()
            # Seule la zone a partir de la colonne sous laquelle la nouvelle sort bouge : rien a capturer ni a
            # couvrir a sa gauche (les captures de TOUTES les colonnes visibles coutaient de plus en plus cher
            # avec la profondeur, ~50 ms a 10 niveaux).
            origin = max(0, x - column.width())
            try:
                snapshot = self._grab_set_columns_at(x, start=origin)
            finally:
                if fade_up:
                    fade.show()
            if snapshot is None:
                return
            left, right, x, background, limit = snapshot
            overlay = _SlideOverlay(
                viewport, left, right, x - column.width(), x, background, 0.0, 1.0, 200,
                None, on_done=lambda: setattr(self, "_columns_slide", None), limit=limit,
                emerge=True, origin=origin)
            overlay.show()
            overlay.raise_()
            self._columns_slide = overlay
            if fade_up:
                # La colonne qui sort reste 100 % opaque : le fondu ne la recouvre pas
                # (son dernier emplacement est conserve une fois l'animation finie).
                last = {}
                # Largeur du contenu REEL qui sort (colonne + ce qui la suit), SANS
                # l'inspecteur : l'inclure etendait la zone exclue a toute la droite et
                # l'ancien contenu disparaissait d'un coup au lieu de s'estomper.
                content_w = max(1, self._columns_content_right() - x)

                def covered(slide=overlay):
                    try:
                        last["rect"] = slide.right_rect(content_w)
                    except RuntimeError:
                        pass
                    return last.get("rect")
                fade.set_exclude(covered)
                fade.raise_()
        except RuntimeError:
            pass

    def _sync_collapse_state(self):
        """Replie automatiquement TOUTES les colonnes de la chaine requise
        (voir _chain_expected_total/Column.collapsible, PAS une liste de
        titres fixe — N quelconque : 3 en legacy, ou le nombre de niveaux
        configures, voir la remarque de l'utilisateur, "si un projet est
        sur une base 3 etapes, 3 colonnes devront se rabattre, si c'est une
        base 4, 4 colonnes ... en fait c'est toutes les colonnes avant les
        colonnes de focus") des que la chaine est COMPLETEMENT settee
        jusqu'au repertoire de travail (voir _chain_terminal_path) : ce
        contexte devient fixe, ces colonnes de navigation n'ont plus besoin
        de rester deployees. Desactivable entierement (voir General >
        Application, "un toggle qui permet ou pas de rabattre les colonnes
        de set" — auto_collapse_set_columns()) : dans ce cas, jamais replie
        automatiquement, mais l'icone de repli MANUEL sur la colonne des
        vignettes reste disponible (voir _toggle_project_columns). Ne force
        ce repli qu'UNE fois par selection (voir _auto_collapse_armed) : un
        depli manuel ensuite (icone sur la colonne des vignettes) n'est pas
        systematiquement annule tant que la selection reste la meme.
        Redeploie tout automatiquement des que la chaine n'est plus
        complete (retour en arriere dans la navigation), pour laisser le
        choix a nouveau visible, et rearme alors le repli automatique pour
        la prochaine selection."""
        self._enforce_hidden_columns()
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        has_selection = self._chain_terminal_path() is not None
        if not has_selection or not focus_enabled:
            # Sans colonne Focus (voir ColumnConfigDialog, toggle "Focus" a
            # 0), replier les colonnes d'avant n'a plus aucun but (voir sa
            # remarque de tete : ce repli sert a REVELER la colonne Focus,
            # qui n'existe pas ici) — les colonnes de la chaine restent donc
            # TOUJOURS deployees dans ce cas.
            self._auto_collapse_armed = True
            if self._project_columns_collapsed:
                # Differe aussi (voir plus bas) : jamais de capture ni de boucle
                # d'evenements au milieu d'une navigation.
                QTimer.singleShot(0, self._auto_expand_now)
        elif auto_collapse_set_columns() and self._auto_collapse_armed and not self._project_columns_collapsed:
            # Differe d'un tour de boucle : _sync_collapse_state est appelee AVANT que
            # update_preview_stack ait reconstruit les vignettes/le groupe ; capturer
            # maintenant figerait un etat intermediaire (puis un saut a l'ecran).
            self._auto_collapse_armed = False
            # Navigation directe (_navigate_to) : repli pose sans animation (rien n'a ete montre entre-temps).
            animate = not self._bulk_navigation
            QTimer.singleShot(0, lambda: self._auto_collapse_now(animate))

    def _toggle_project_columns_hidden(self):
        """Bouton « masquer les colonnes » (voir PreviewColumn.hide_btn) : TOUTES
        les colonnes disparaissent en fondu puis quittent la mise en page — leur
        place est liberee ; seuls les deux boutons restent. Un nouveau clic
        ramene tout (fondu inverse). Le fondu anime une capture fixe de la zone
        (voir _FadeOverlay) pendant que les vrais widgets sont deja masques."""
        self._set_columns_hidden(not self._project_columns_hidden)

    def _hideable_widgets(self) -> list:
        """Tout ce que columns_layout contient, sauf le conteneur des vignettes
        Focus (qui porte les boutons)."""
        widgets = []
        for i in range(self.columns_layout.count()):
            widget = self.columns_layout.itemAt(i).widget()
            if widget is not None and widget is not self._preview_stack_wrapper:
                widgets.append(widget)
        return widgets

    def _toggled_widgets(self) -> list:
        return self._hideable_widgets() + list(self.image_preview_columns[1:]) + [self.detail]

    def _apply_columns_hidden(self, hidden: bool):
        """Masque/restaure INSTANTANEMENT ; ne restaure que ce que le bouton a
        lui-meme masque (une colonne de set deja repliee reste repliee)."""
        if self.image_preview_columns and self.image_preview_columns[0].hide_btn is not None:
            # Le focus reste sur le bouton : masquer une liste qui l'a le donnerait a
            # une autre liste, qui changerait de selection (et rebatirait les colonnes).
            self.image_preview_columns[0].hide_btn.setFocus()
        elif hidden:
            # Pas de bouton (masquage par double-clic sans colonnes Focus) : le
            # focus est gare sur la zone des colonnes, pour la meme raison.
            self.scroll.viewport().setFocus()
        for widget in self._toggled_widgets():
            if hidden:
                if _shown_or_pending(widget):
                    widget._hidden_by_toggle = True
                    widget.setVisible(False)
            elif getattr(widget, "_hidden_by_toggle", False):
                widget._hidden_by_toggle = False
                widget.setVisible(True)
        if self.image_preview_columns:
            self.image_preview_columns[0].set_buttons_only(hidden)

    def _columns_visible_rect(self) -> QRect:
        viewport = self.scroll.viewport()
        rect = QRect()
        candidates = [*self._hideable_widgets(), *self.image_preview_columns, self.detail]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        for widget in candidates:
            if widget.isVisible():
                rect = rect.united(QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size()))
        return rect.intersected(viewport.rect())

    def _columns_content_right(self) -> int:
        """Bord droit (repere du viewport) de la derniere colonne visible, inspecteur exclu."""
        viewport = self.scroll.viewport()
        right = 0
        candidates = [*self._hideable_widgets(), *self.image_preview_columns]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        for widget in candidates:
            if widget.isVisible() and widget.width() > 0:
                right = max(right, widget.mapTo(viewport, QPoint(0, 0)).x() + widget.width())
        return right

    def _column_spans(self, rect: QRect) -> list:
        """Bandes (x0, x1), dans le repere de `rect`, une par colonne visible, de gauche a
        droite ; elles se touchent (l'espace entre deux colonnes va a la precedente)."""
        viewport = self.scroll.viewport()
        candidates = [*self._hideable_widgets(), *self.image_preview_columns, self.detail]
        if self._preview_stack_wrapper is not None:
            candidates.append(self._preview_stack_wrapper)
        starts = sorted({max(0, widget.mapTo(viewport, QPoint(0, 0)).x() - rect.x())
                         for widget in candidates if widget.isVisible() and widget.width() > 0})
        starts = [x for x in starts if x < rect.width()]
        if len(starts) < 2:
            return []
        starts[0] = 0
        return list(zip(starts, [*starts[1:], rect.width()]))

    def _button_rects(self) -> list:
        """Boutons poses SUR la zone des colonnes (trous de l'image, clics a cote) ; ceux du cadre « Visionneuse »
        de la barre de navigation n'y sont pas."""
        viewport = self.scroll.viewport()
        rects = self._base_button_rects()
        for widget in (self._filter_btn, self._filter_chips, self._lightroom_btn, self._viewer_100_btn,
                       self._recursive_btn, *self._pur_buttons):
            if widget is not None and widget.isVisible() and widget.parentWidget() is viewport:
                rects.append(widget.geometry())
        return rects

    def _base_button_rects(self) -> list:
        """Boutons repli / masquer / planche (ou le bouton flottant) : les autres viennent a leur suite."""
        viewport = self.scroll.viewport()
        rects = []
        if self.image_preview_columns:
            pc = self.image_preview_columns[0]
            for button in (pc.toggle_btn, pc.hide_btn, pc.gallery_btn):
                if (button is not None and (button is not pc.gallery_btn or button.isVisible())
                        and viewport.isAncestorOf(button)):
                    rects.append(QRect(button.mapTo(viewport, QPoint(0, 0)), button.size()))
        floating = self._floating_gallery_btn
        if floating is not None and floating.isVisible() and floating.parentWidget() is viewport:
            rects.append(floating.geometry())
        return rects

    def _fade_snapshot_fresh(self) -> bool:
        """La capture « masquer » depend de la taille, de la navigation ET de l'etat
        replie/deplie des colonnes de set."""
        cached = self._columns_snapshot
        return (cached is not None and len(cached) > 5 and cached[2] == self.scroll.viewport().size()
                and cached[3] == self._columns_epoch and cached[5] == self._project_columns_collapsed
                and time.monotonic() - cached[4] < 8.0)

    def _grab_columns(self) -> tuple:
        """Capture de la zone des colonnes dans son etat actuel, avec les boutons
        effaces (transparents) : ils restent reels et ne s'estompent pas. Les
        boutons ne sont PAS masques pour la capture : masquer celui qui a le
        focus le transmettrait a une liste, qui changerait de selection."""
        if _anim_running(self._columns_slide):
            self._columns_slide.finish_now()   # jamais de capture avec un overlay par-dessus
        rect = self._columns_visible_rect()
        viewport = self.scroll.viewport()
        self._columns_spans = self._column_spans(rect)
        image = viewport.grab(rect).toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        for button_rect in self._button_rects():
            painter.fillRect(button_rect.translated(-rect.topLeft()), Qt.transparent)
        painter.end()
        return QPixmap.fromImage(image), rect, viewport.size(), self._columns_epoch

    def _set_columns_hidden(self, hidden: bool, animate: bool = True):
        # Sans colonnes Focus (donc sans bouton), on ne masque que si un objet
        # peut partir au centre : on revient par Echap ou le bouton « precedent » de la souris.
        if hidden == self._project_columns_hidden or (
                hidden and not self.image_preview_columns and self._focus_source() is None
                and getattr(self, "_viewer_entry_source", None) is None
                and not getattr(self, "_viewer_force_hide", False)):
            return
        if not hidden:
            if self._focus_gallery is not None:
                # Sortie depuis la PLANCHE : aucune image n'a le focus, donc aucune selectionnee.
                self._leave_viewer_unselected()
            else:
                self._close_focus_gallery(animate=False)   # l'image revient au centre avant de repartir
                self._flush_viewer_sync()                   # colonne + inspecteur sur l'image montree
                if self._focus_overlay is not None:
                    self._focus_overlay.reset_view()        # repart ajustee, sans zoom
        self._project_columns_hidden = hidden
        self._sync_floating_gallery_btn()
        for preview_column in self.image_preview_columns:
            preview_column.set_hide_state(hidden)
        overlay = self._columns_fade
        if _anim_running(overlay):
            # Clic pendant un fondu : on repart de l'opacite courante, a l'envers.
            overlay.retarget(0.0 if hidden else 1.0, None if hidden else self._show_columns_now)
            if self._focus_overlay is not None:
                self._focus_overlay.retarget(1.0 if hidden else 0.0)
            if hidden:
                self._enter_viewer()
            return
        if not animate:
            self._apply_columns_hidden(hidden)
            if hidden:
                self._enter_viewer()
            return
        if hidden:
            if self._columns_slide is not None:
                self._columns_slide.finish_now()   # on ne capture jamais un mouvement en cours
            self.columns_layout.activate()
            self._clear_focus_overlay()
            home = self._focus_source()
            self._focus_src = self._entry_focus_source(home)      # double-clic : depuis la ligne
            from_row = self._focus_src is not home
            if not self._fade_snapshot_fresh():
                self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)
            self._apply_columns_hidden(True)
            self._start_columns_fade(1.0, 0.0, None)
            self._start_focus_overlay(1.0)
            if from_row:
                self._focus_src = home
                overlay = self._focus_overlay
                if overlay is not None:
                    overlay._on_finished = lambda o=overlay, h=home: self._send_focus_home(o, h)
            self._enter_viewer()
            return
        if not self._fade_snapshot_fresh() and self._columns_snapshot is not None and \
                (self._columns_snapshot[2] != self.scroll.viewport().size()
                 or self._columns_snapshot[3] != self._columns_epoch
                 or (len(self._columns_snapshot) > 5 and self._columns_snapshot[5] != self._project_columns_collapsed)):
            self._columns_snapshot = None
        snapshot = self._columns_snapshot
        if snapshot is None:
            # Capture perimee (navigation, redimensionnement ou visionneuse pendant le masquage) :
            # on affiche, on capture, on re-masque avant tout rendu a l'ecran (aucun retour a la
            # boucle d'evenements entre les deux). PAS de setUpdatesEnabled(False) ici : grab()
            # respecte ce drapeau et rendait une capture VIDE (fond seul) -> pas de fondu, les
            # colonnes surgissaient d'un coup a la fin.
            try:
                self._apply_columns_hidden(False)
                self._settle_columns_layout()
                self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)
                self._retarget_focus_source()
            finally:
                self._apply_columns_hidden(True)
        elif len(snapshot) > 6 and snapshot[6] is not None:
            self._retarget_focus_source(snapshot[6])     # capture faite d'avance : sa place de retour
        self._start_columns_fade(0.0, 1.0, self._show_columns_now)
        self._start_focus_overlay(0.0)

    def _leave_viewer_unselected(self):
        """Sortie de la visionneuse alors que la planche est ouverte (aucune image en grand) : la
        planche disparait, l'image en focus aussi (rien ne repart vers l'inspecteur) et la colonne du
        dossier n'a plus AUCUN fichier selectionne (meme chemin qu'un re-clic sur la ligne : les
        colonnes ouvertes apres elle se ferment, l'inspecteur se vide). Appele colonnes encore
        masquees : la deselection se fait sans fondu, celui du retour des colonnes suffit."""
        gallery = self._focus_gallery
        self._focus_gallery = None
        self._set_gallery_buttons_state(False)
        if gallery is not None:
            self._gallery_memory = (gallery.path_keys(), gallery.first_visible_row())
            gallery.blockSignals(True)
            gallery.hide()
            gallery.deleteLater()
        self._viewer_sync.stop()
        self._clear_focus_overlay()
        self._focus_src = None
        if not self._gallery_deselected:
            self._deselect_viewer_file()
        self._gallery_deselected = False

    def _deselect_viewer_file(self):
        """La colonne du dossier de la visionneuse n'a plus AUCUN fichier selectionne (meme chemin qu'un
        re-clic), l'inspecteur se vide. Colonnes masquees : sans fondu."""
        column, current = self._focus_file_column()
        if column is None:
            # Colonne pas encore alignee sur le fichier (navigation en attente) : celle qui montre
            # un fichier du dossier de la visionneuse.
            folder = Path(self._viewer_paths[0]).parent if self._viewer_paths else None
            column = next((c for c in [*self.columns, *self.group_columns]
                           if folder is not None and c.current_path() is not None
                           and c.current_path().parent == folder), None)
        if column is not None:
            self.on_reclicked(column)
        else:
            self.detail.clear()

    def _retarget_focus_source(self, relevee: tuple | None = None):
        """Capture perimee : l'inspecteur vient d'etre re-affiche pour la refaire,
        on en profite pour relever la vraie place de l'objet en focus (et son
        contenu actuel) comme point d'arrivee du retour. `relevee` : place deja
        relevee lors de la capture faite d'avance (_pregrab_columns), `(source,)`."""
        source = self._focus_source() if relevee is None else relevee[0]
        self._focus_src = source
        overlay = self._focus_overlay
        if source is None:
            self._clear_focus_overlay()
        elif overlay is not None:
            if getattr(self.detail, "_current_path", None) != self._focus_path:
                # Autre fichier que celui montre : son image. Sinon l'image du centre (pleine
                # definition) repart telle quelle, sans passer par l'apercu de l'inspecteur.
                overlay._base = source[0]
                overlay._natural = None
                overlay._cache_key = None
            overlay.set_geometry_target(None, QRectF(source[1]))     # meme zone : l'image ne saute pas

    def _show_columns_now(self):
        self._apply_columns_hidden(False)
        self._clear_focus_overlay()
        self._focus_src = None

    def _start_columns_fade(self, start: float, end: float, on_finished):
        pixmap, rect = self._columns_snapshot[0], self._columns_snapshot[1]
        self.columns_layout.activate()
        spans = getattr(self, "_columns_spans", [])
        overlay = _FadeOverlay(self.scroll.viewport(), pixmap, rect, start, end, 420 if len(spans) > 1 else 260,
                               on_finished, on_done=lambda: setattr(self, "_columns_fade", None))
        overlay.set_spans(spans)
        holes = self._button_rects()
        if self._focus_src is not None:
            holes.append(self._focus_src[1])   # l'objet en focus voyage a part : pas de double dans le fondu
        overlay.set_holes(holes)
        overlay.show()
        overlay.raise_()
        self._columns_fade = overlay
        if self._focus_overlay is not None:
            self._focus_overlay.raise_()
        self._raise_viewer_chrome()

    def _focus_source(self):
        """(pixmap, QRect en coordonnees du viewport) de l'objet en focus tel que
        l'inspecteur l'affiche, ou None. Exige l'inspecteur visible et mis en page."""
        if not self.detail.isVisible():
            return None
        source = self.detail.focus_source()
        if source is None:
            return None
        pixmap, rect = source
        viewport = self.scroll.viewport()
        return pixmap, QRect(self.detail.mapTo(viewport, rect.topLeft()), rect.size())

    def _focus_area(self) -> QRect:
        return self.scroll.viewport().rect()

    def _start_focus_overlay(self, end: float):
        """Fait voyager l'objet en focus : end=1.0 de l'inspecteur vers le centre
        (masquage), end=0.0 du centre vers l'inspecteur (retour). Meme duree que
        le fondu des colonnes."""
        source = self._focus_src
        if source is None:
            return
        pixmap, rect = source
        spans = getattr(self, "_columns_spans", [])
        duration = 420 if len(spans) > 1 else 260
        overlay = self._focus_overlay
        if overlay is not None:
            overlay._duration = duration
            overlay.retarget(end)
            overlay.raise_()
            self._raise_viewer_chrome()
            return
        area = self._viewer_area()
        overlay = FocusOverlay(self.scroll.viewport(), pixmap, QRectF(rect), FocusOverlay.target_rect(pixmap, area),
                                1.0 - end, end, duration,
                                on_double_click=self._toggle_project_columns_hidden,
                                on_wheel=self._on_focus_wheel)
        overlay.show()
        overlay.raise_()
        self._focus_overlay = overlay
        self._raise_viewer_chrome()

    def _clear_focus_overlay(self):
        overlay = self._focus_overlay
        self._focus_overlay = None
        self._focus_home = None
        self._focus_path = None
        if overlay is not None:
            overlay.dispose()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pur_buttons or self._filter_btn is not None:
            self._sync_filter_button()               # bouton filtre puis boutons PureRef : a la suite des autres
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.set_geometry_target(self._viewer_area())
        self._position_focus_origin_badge()
        if self._focus_gallery is not None:
            self._focus_gallery.setGeometry(self._gallery_rect())
        self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())
        if self._filmstrip is not None:
            self._filmstrip.setGeometry(self._filmstrip_rect())
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.setGeometry(self._info_rect())

    # -- Planche des images du dossier (etat focus) --

    def _toggle_focus_gallery(self):
        """Bouton voisin de « masquer » (etat focus seulement) : image en cours <-> planche de
        toutes les images du dossier de l'image en cours."""
        if self._focus_gallery is not None:
            self._close_focus_gallery()
        else:
            self._open_focus_gallery()

    def _focus_file_column(self):
        """(colonne, chemin) du fichier affiche par l'inspecteur ; colonne None si introuvable. Double-clic
        sur une ligne en cours : CE fichier et sa colonne (`_viewer_entry_path`), quoi que montre
        l'inspecteur."""
        entry = getattr(self, "_viewer_entry_path", None)
        if entry is not None:
            return entry
        current = getattr(self.detail, "_current_path", None)
        if not current:
            return None, None
        path = Path(current)
        for column in [*self.columns, *self.group_columns]:
            if column.current_path() == path:
                return column, path
        return None, path

    def _gallery_paths(self, rescan: bool = True) -> tuple:
        """Fichiers de la planche et fichier en cours : ceux de la visionneuse s'ils sont connus
        (l'image montree peut avoir devance la colonne, voir _viewer_sync), sinon relus ; filtre applique
        (voir _filtered_gallery)."""
        if 0 <= self._viewer_index < len(self._viewer_paths):
            paths = list(self._viewer_base or self._viewer_paths)
            current = str(self._viewer_paths[self._viewer_index])
        else:
            paths, current = self._scan_viewer_paths()
        return self._filtered_gallery(paths, current, rescan)

    # -- Filtres de la planche (demande de l'utilisateur) --

    def _filtered_gallery(self, paths: list, current: str | None, rescan: bool = True) -> tuple:
        """Filtre de la planche applique a `paths` (colonne en cours) ou, portee plus large, aux fichiers
        du dossier de la portee : parcourus EN FOND (`rescan` : relus a l'ouverture de la planche), la
        colonne filtree en attendant le premier parcours. Fichier en cours : None s'il est ecarte."""
        spec = file_filters.normalized(self._viewer_filter)
        if not self._viewer_filter_active():
            return paths, current
        folder = self._filter_scope_folder(spec["scope"])
        entries = paths
        if folder is not None:
            known = self._scope_files.get(str(folder))
            if rescan or known is None:
                self._start_filter_scan(folder)
            if known is not None:
                entries = known
        found = file_filters.filter_entries(entries, spec, self._filter_root())
        return found, (current if current is not None and any(str(p) == current for p in found) else None)

    def _filter_root(self) -> Path:
        return Path(self.root_field.text())

    def _filter_provenances(self) -> list:
        """Provenances proposees : les fixes, puis les sous-dossiers de in / over / out des fichiers connus
        (colonne en cours et portees deja parcourues)."""
        entries = list(self._viewer_base or self._viewer_paths)
        for known in self._scope_files.values():
            entries.extend(known)
        return file_filters.provenance_choices(entries, self._filter_root())

    def _filter_scopes(self) -> list:
        """(cle, libelle) des portees : la colonne en cours, chaque dossier de la chaine du set (Type,
        Projet, Sous-projet…), toute la racine."""
        scopes = [(file_filters.SCOPE_LOCAL, "Local (colonne en cours)")]
        for index in range(min(len(self.columns), self._chain_expected_total())):
            column = self.columns[index]
            chosen = column.current_path()
            if chosen is None or not chosen.is_dir():
                break
            title = column.title_label.text() or column.column_title
            scopes.append((f"level:{index}", f"{title.capitalize()} : {chosen.name}"))
        scopes.append((file_filters.SCOPE_ROOT, "Toute la racine"))
        self._filter_scopes_cache = scopes
        return scopes

    def _filter_scope_folder(self, scope: str) -> Path | None:
        """Dossier parcouru pour une portee large ; None = la colonne en cours."""
        if scope == file_filters.SCOPE_ROOT:
            return Path(self.root_field.text())
        if scope.startswith("level:"):
            try:
                column = self.columns[int(scope.split(":", 1)[1])]
            except (ValueError, IndexError):
                return None
            chosen = column.current_path()
            return chosen if chosen is not None and chosen.is_dir() else None
        return None

    def _filter_scope_label(self, scope: str) -> str:
        labels = dict(self._filter_scopes_cache)
        if scope not in labels:
            labels = dict(self._filter_scopes())
        return labels.get(scope, "")

    def _start_filter_scan(self, folder: Path):
        task = self._filter_task
        if task is not None:
            if task.folder == folder and not task.cancel:
                return                                   # deja en cours
            task.cancel = True
        task = self._filter_task = file_filters.FilterScanTask(folder)
        task.signals.finished.connect(self._on_filter_scan_done)
        file_filters.pool().start(task)

    def _on_filter_scan_done(self, folder: str, entries):
        task = self._filter_task
        if task is not None and str(task.folder) == folder:
            self._filter_task = None
        self._scope_files[folder] = entries
        pending = self._pending_folder_view
        if pending is not None and str(pending[0]) == folder:
            self._pending_folder_view = None
            self._view_folder_in_viewer(*pending)             # double-clic sur un dossier : parcours fini
        elif self._project_columns_hidden and self._recursive_on() and self._viewer_folder is not None \
                and str(self._viewer_folder) == folder:
            self._apply_viewer_base()                         # mode récursif : liste complète arrivée
        # Images des planches PureRef parcourues : rangees comme celles de la visionneuse (nom affiche
        # « planche.pur · n/N », planche retrouvee au retour aux colonnes, attributs de la planche).
        boards: dict = {}
        for entry in entries:
            if len(entry) > 3:
                boards.setdefault(entry[3], []).append(entry[0])
        for (pur, mtime), images in boards.items():
            self._remember_pur(pur, mtime, images)
        self._refresh_focus_gallery(rescan=False)
        self._sync_filter_button()

    def _sync_filter_button(self):
        """Planche ouverte : bouton filtre a la suite des autres boutons (rouge quand un filtre agit), et les
        elements du filtre ecrits a cote, en « style code » (FilterChips) ; puis les boutons PureRef."""
        spec = file_filters.normalized(self._viewer_filter)
        configured = file_filters.is_active(spec)
        active = configured and self._viewer_filter_enabled
        # Le filtre reste une action de la visionneuse, même lorsqu'on est
        # revenu à l'image seule : l'icône doit alors rester dans la rangée
        # pour signaler l'état actif et permettre de le modifier.
        viewer_mode = self._focus_gallery is not None or self._viewer_active()
        want = viewer_mode and (self._focus_gallery is not None or configured)
        button, chips = self._filter_btn, self._filter_chips
        if not want:
            for widget in (button, chips):
                if widget is not None:
                    widget.hide()
            self._sync_pur_buttons()
            return
        viewport = self.scroll.viewport()
        if button is None:
            button = self._filter_btn = IconButton("filter", role_color("buttons", "#c4cacf"), C["text"],
                                                   parent=viewport)
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._on_filter_button_clicked)
            button.setContextMenuPolicy(Qt.CustomContextMenu)
            button.customContextMenuRequested.connect(self._filter_button_menu)
            chips = self._filter_chips = FilterChips(viewport)
        style_focus_button(button)
        settings = ui_state.APPLIED_SETTINGS or {}
        button.set_alert(resolve_color_ref(settings.get("viewer_filter_active_color") or "#c62828")
                         if active else None)
        button.setToolTip(("Filtres actifs — cliquer pour désactiver (clic droit : retirer)" if active
                           else "Filtres en mémoire, désactivés — cliquer pour réactiver"
                           if configured else "Filtres de la planche"))
        button.show()
        button.raise_()
        if active and self._focus_gallery is not None:
            items = file_filters.describe(spec, [name for name, _c in _focus.filter_colors()],
                                          self._filter_scope_label(spec["scope"]))
            if self._filter_task is not None:
                items.append("recherche…")
            else:
                count = len(self._gallery_list)
                items.append(f"{count} fichier{'s' if count > 1 else ''}")
            chips.restyle()
            chips.set_items(items)
            chips.show()
            chips.raise_()
        else:
            chips.hide()
        self._sync_pur_buttons()

    def _filter_button_menu(self, pos):
        if not file_filters.is_active(self._viewer_filter):
            return
        menu = Menu(self)
        menu.addAction("Retirer le filtre", self._clear_viewer_filter)
        menu.exec(self._filter_btn.mapToGlobal(pos))

    def _clear_viewer_filter(self):
        if self._filter_window is not None:
            self._filter_window.close()          # rouverte, elle repart des valeurs vides
        self._set_viewer_filter(dict(file_filters.DEFAULT_FILTER))

    def _on_filter_button_clicked(self):
        """Sans critères, ouvre leur réglage ; avec des critères, active/désactive leur application."""
        if file_filters.is_active(self._viewer_filter):
            self._viewer_filter_enabled = not self._viewer_filter_enabled
            self._refresh_focus_gallery(rescan=True)
            self._sync_filter_button()
            return
        self._open_filter_window()

    def _open_filter_window(self):
        window = self._filter_window
        if window is not None:
            window.raise_()
            window.activateWindow()
            return
        window = self._filter_window = filter_window(
            self._viewer_filter, self._filter_scopes(), settings=ui_state.APPLIED_SETTINGS, parent=self,
            provenances=self._filter_provenances())
        window.styleChanged.connect(self._on_filter_window_changed)
        window.destroyed.connect(lambda *_a: setattr(self, "_filter_window", None))
        window.on_row_style = self._open_filter_row_style      # clic droit > « Style des filtres actives… »
        window.show()

    def _open_filter_row_style(self):
        """Style des lignes ou un filtre est applique (fond, bordures) : fenetre « a la volee », valeurs
        appliquees en direct et enregistrees comme les styles des diapositives (_on_filmstrip_style)."""
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow
        previous = getattr(self, "_filter_row_window", None)
        if previous is not None:
            try:
                previous.raise_()
                previous.activateWindow()
                return
            except RuntimeError:
                pass
        settings = dict(DEFAULT_SETTINGS)
        settings.update(ui_state.APPLIED_SETTINGS or load_settings())
        window = self._filter_row_window = QuickStyleWindow(
            "Filtres actifs", v2.FILTER_ROW_SPECS, settings, title="Style des filtres activés",
            settings=settings, parent=self)
        window.styleChanged.connect(self._on_filter_row_style)
        window.destroyed.connect(lambda *_a: setattr(self, "_filter_row_window", None))
        window.show()

    def _on_filter_row_style(self, values: dict):
        self._on_filmstrip_style(values, light=True)          # applique + enregistre (et preset actif)
        # Enregistre EN TEMPS REEL (demande de l'utilisateur) : tout de suite, sauf pendant un geste
        # (curseur tire) ou l'ecriture attend le relachement (minuteur de _on_filmstrip_style).
        if QApplication.mouseButtons() == Qt.NoButton:
            self._flush_filmstrip_style()
        window = self._filter_window
        if window is not None:
            try:
                window.refresh_marks()
            except RuntimeError:
                pass

    def _on_filter_window_changed(self, values: dict):
        """Changement dans la fenetre des filtres : applique apres une courte pause (frappe au clavier)."""
        self._pending_filter = values
        if self._filter_timer is None:
            self._filter_timer = QTimer(self)
            self._filter_timer.setSingleShot(True)
            self._filter_timer.setInterval(250)
            self._filter_timer.timeout.connect(lambda: self._set_viewer_filter(self._pending_filter))
        self._filter_timer.start()

    def _set_viewer_filter(self, spec: dict | None):
        self._viewer_filter = file_filters.normalized(spec)
        self._viewer_filter_enabled = file_filters.is_active(self._viewer_filter)
        self._refresh_focus_gallery(rescan=True)
        self._sync_filter_button()

    def _viewer_filter_active(self) -> bool:
        return self._viewer_filter_enabled and file_filters.is_active(self._viewer_filter)

    def _refresh_focus_gallery(self, rescan: bool = True):
        """Filtre change (ou parcours termine) : la planche est refaite sur place avec les fichiers retenus,
        en fondu (sans vague)."""
        old = self._focus_gallery
        if old is None:
            return
        paths, current = self._gallery_paths(rescan=rescan)
        if [str(p) for p in paths] == [str(p) for p in self._gallery_list]:
            return
        gallery = self._make_focus_gallery(paths, current)
        self._focus_gallery = gallery
        gallery.show()
        gallery.reveal_current(None)
        gallery.warm_cells(False)
        gallery.start_ripple(wave=False)
        gallery.raise_()
        old.blockSignals(True)
        old.hide()
        old.deleteLater()
        self._raise_gallery_buttons()

    def _scan_viewer_paths(self) -> tuple:
        """Fichiers a apercu (images, 3D, PSD, plans, videos...) du dossier du fichier en cours,
        dans l'ordre de sa colonne (ordre choisi a la main compris) ; a defaut de colonne, ceux du
        dossier, tries par nom. Aucune lecture disque par fichier (les lignes savent si elles
        sont des dossiers)."""
        column, current = self._focus_file_column()
        if current is None:
            return [], None
        recursive = self._recursive_known() if self._project_columns_hidden or self._viewer_entry_folder else None
        if recursive and str(current) in {str(p) for p in recursive}:
            return list(recursive), str(current)          # mode récursif : tout le dossier et dessous
        if column is not None:
            items = [column.list.item(i) for i in range(column.list.count())]
            paths = [Path(item.data(ROLE_PATH)) for item in items if not item.data(ROLE_ISDIR)]
        else:
            try:
                paths = sorted((p for p in current.parent.iterdir() if p.is_file()), key=lambda p: p.name.casefold())
            except OSError:
                paths = []
        # Planches PureRef comprises : leurs images y entrent (voir _expand_viewer_pureref).
        images = [p for p in paths if p.suffix.lower() in PREVIEWABLE_EXTENSIONS | PUR_PREVIEW_EXTENSIONS]
        return images, str(current)

    def _gallery_rect(self) -> QRect:
        """Zone des colonnes, sous les boutons (qui restent cliquables)."""
        area = self._focus_area()
        top = max((r.bottom() for r in self._button_rects()), default=0) + 10
        return QRect(area.x() + 16, top, max(1, area.width() - 32), max(1, area.bottom() - top))

    def _sync_floating_gallery_btn(self):
        """Focus SANS colonne Focus (donc sans bouton « masquer », retour par double-clic) : le
        bouton de la planche flotte seul en haut a gauche de la zone des colonnes, meme style.
        Avec une colonne Focus, c'est elle qui le porte (PreviewColumn.gallery_btn)."""
        self._sync_viewer_chrome()
        # Bouton de passage image / planche SUPPRIME (demande de l'utilisateur) : la touche G, le clic sur l'image
        # et Ctrl+molette restent.
        want = False
        button = self._floating_gallery_btn
        if not want:
            if button is not None:
                button.hide()
            return
        if button is None:
            button = self._floating_gallery_btn = IconButton(
                "gallery", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._toggle_focus_gallery)
        style_focus_button(button)
        style = column_style_for(PREVIEW_STACK_TITLE)
        button.move(scaled(int(style.get("preview_toggle_x", 8)), 0) + scaled(8, 0), scaled(10, 0))
        self._set_gallery_buttons_state(self._focus_gallery is not None)
        button.show()
        button.raise_()
        self._layout_viewer_buttons()

    def _set_gallery_buttons_state(self, shown: bool):
        if self.image_preview_columns:
            self.image_preview_columns[0].set_gallery_state(shown)
        button = self._floating_gallery_btn
        if button is not None:
            button.set_kind("single_image" if shown else "gallery")
            button.setToolTip("Revenir a l'image en cours" if shown else "Toutes les images du dossier")
        self._sync_filter_button()

    def _open_focus_gallery(self):
        if not self._project_columns_hidden:
            return
        paths, current = self._gallery_paths()
        if getattr(self, "_gallery_no_focus", False):
            current = None                 # ouverte depuis un dossier : aucune image en focus
        if not paths and not self._viewer_filter_active():
            return
        viewport = self.scroll.viewport()
        gallery = self._make_focus_gallery(paths, current)
        self._focus_gallery = gallery
        self._sync_viewer_chrome()                 # pellicule et raccourcis de l'image : retires
        gallery.show()
        memory = getattr(self, "_gallery_memory", None)
        gallery.reveal_current(memory[1] if memory is not None and memory[0] == gallery.path_keys() else None)
        # Les cases apparaissent en vague depuis l'image ; vague coupee (Reglages > Visionneuse) :
        # toutes ensemble, en fondu. Leurs images sont faites avant qu'elles ne se montrent.
        wave = bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_gallery_ripple_enabled", True))
        gallery.warm_cells(wave)
        gallery.start_ripple(wave=wave)
        self._return_grab.start()          # au repos : sortie vers les colonnes preparee d'avance
        gallery.raise_()
        gallery.setFocus()
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.finish_now()
            # L'image en focus se pose dans sa vignette (et la case reste vide pendant le vol) ;
            # sa place dans l'inspecteur est gardee pour le retour des colonnes.
            tile = gallery.image_rect_in(viewport, current, overlay._base)
            if tile is None:
                overlay.hide()
            else:
                self._focus_home = overlay._source
                gallery.set_hidden_path(current)
                overlay._source = QRectF(tile)
                overlay._duration = self._GALLERY_FLIGHT_MS
                overlay.retarget(0.0, self._on_focus_landed_in_gallery)
                overlay.raise_()
        self._set_gallery_buttons_state(True)
        self._raise_gallery_buttons()

    def _make_focus_gallery(self, paths: list, current: str | None):
        gallery = FocusGallery(self.scroll.viewport(), paths, current, on_split=self._on_gallery_split,
                               on_menu=self._filmstrip_menu)
        gallery.setGeometry(self._gallery_rect())
        gallery.chosen.connect(self._on_gallery_chosen)
        gallery.zoomed_into.connect(self._on_gallery_chosen)
        gallery.closed.connect(self._close_focus_gallery)
        self._gallery_list = [Path(p) for p in paths]
        return gallery

    def _raise_gallery_buttons(self):
        for button in (self._floating_gallery_btn, self._filter_btn, self._filter_chips, *self._pur_buttons):
            if button is not None and button.isVisible():
                button.raise_()

    _GALLERY_FLIGHT_MS = 380

    def _on_focus_landed_in_gallery(self):
        """L'image est dans sa case : la planche la dessine, l'objet en focus se cache."""
        if self._focus_overlay is not None:
            self._focus_overlay.hide()
        if self._focus_gallery is not None:
            self._focus_gallery.set_hidden_path(None)

    def _close_focus_gallery(self, animate: bool = True, path: str | None = None):
        """Retour a l'image : elle quitte sa vignette (`path`, par defaut le fichier de
        l'inspecteur) pour le centre pendant que la planche s'estompe. `animate=False` : tout de
        suite (les colonnes reviennent : l'objet doit etre au centre, avec sa place d'origine)."""
        gallery = self._focus_gallery
        if gallery is None:
            overlay = self._focus_overlay
            if not animate and overlay is not None and self._focus_home is not None:
                # Retour de vignette encore en vol : l'objet est pose au centre avec sa vraie place.
                overlay.jump(1.0)
                overlay._source = self._focus_home
                self._focus_home = None
            return
        self._focus_gallery = None
        self._request_crumbs()                   # l'image regardee revient au bout du cheminement
        if self._gallery_deselected:
            # Retour a l'image depuis la planche : la colonne et l'inspecteur la reprennent (deselectionnes
            # d'avance pour la sortie, _pregrab_columns).
            self._gallery_deselected = False
            self._viewer_sync.start()
        # Position de la planche (premiere ligne visible), retrouvee a sa prochaine ouverture sur le
        # meme dossier (_open_focus_gallery) : jamais recentree sur l'image.
        self._gallery_memory = (gallery.path_keys(), gallery.first_visible_row())
        self._set_gallery_buttons_state(False)
        self._sync_viewer_chrome()
        self._park_keyboard_focus()
        gallery.blockSignals(True)
        gallery.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        overlay = self._focus_overlay
        viewport = self.scroll.viewport()
        if path is None:
            path = self._focus_path or getattr(self.detail, "_current_path", None)
        tile = gallery.image_rect_in(viewport, path, overlay._base) if (animate and overlay is not None) else None
        home = self._focus_home

        def restore_home():
            if self._focus_overlay is overlay and overlay is not None and home is not None:
                overlay._source = home       # au centre (valeur 1) : rien ne bouge a l'ecran
            if self._focus_home is home:
                self._focus_home = None

        def drop_gallery():
            gallery.hide()
            gallery.deleteLater()

        if overlay is None:
            drop_gallery()
            restore_home()
            return
        if tile is None:
            overlay.jump(1.0)
            restore_home()
            overlay.show()
            overlay.raise_()
            if animate:
                gallery.fade(0.0, self._GALLERY_FLIGHT_MS, drop_gallery)
            else:
                drop_gallery()
            return
        gallery.set_hidden_path(path)
        overlay.jump(0.0)
        overlay._source = QRectF(tile)
        overlay._duration = self._GALLERY_FLIGHT_MS
        overlay.show()
        overlay.raise_()
        overlay.retarget(1.0, restore_home)
        gallery.fade(0.0, self._GALLERY_FLIGHT_MS, drop_gallery)

    def _on_gallery_chosen(self, path: Path):
        """Vignette choisie : elle devient le fichier selectionne (colonne + inspecteur) et
        l'image en focus au centre."""
        gallery = self._focus_gallery
        self._focus_on_file(path, gallery.tile_pixmap(path, None) if gallery is not None else None)
        # La vignette choisie s'envole vers le centre (voir _close_focus_gallery).
        if gallery is not None:
            gallery.current = str(path)          # son cadre d'accent pendant que la planche s'estompe
        self._close_focus_gallery(path=str(path))

    def _focus_on_file(self, path: Path, fallback: QPixmap | None = None):
        """`path` (choisi dans la planche) devient l'image au centre ; la colonne et l'inspecteur
        suivent au repos (voir _viewer_sync)."""
        listed = self._gallery_list if self._focus_gallery is not None else []
        if path in listed and listed != self._viewer_paths:
            # Planche filtree (ou filtre retire) : la visionneuse parcourt les fichiers de la planche.
            self._viewer_paths = list(listed)
            if self._filmstrip is not None:
                self._filmstrip.set_paths(self._viewer_paths, listed.index(path))
        index = next((i for i, p in enumerate(self._viewer_paths) if p == path), -1)
        if index < 0:
            paths, _current = self._scan_viewer_paths()
            index = next((i for i, p in enumerate(paths) if p == path), -1)
            if index < 0:
                return
            self._viewer_paths = paths
            if self._filmstrip is not None:
                self._filmstrip.set_paths(paths, index)
        self._viewer_go(index, 0, fallback)

    def _focus_pixmap(self, path: Path, fallback: QPixmap | None = None) -> QPixmap:
        """Image a montrer au centre pour `path` en attendant mieux, SANS rien decoder ici.
        Les formats image attendent le decodage plein format : ne jamais agrandir une vignette
        au centre. Pour les autres fichiers, utiliser l'apercu en cache ou le fallback fourni."""
        self._focus_path = str(path)
        if self._focus_images.supports(path):
            return placeholder_pixmap(path, "Chargement de l’image…")
        mtime = _previews.cached_mtime(path)
        if mtime is not None:
            cached = _previews._file_image_cache.get(str(path))
            if cached is not None and cached[0] == mtime and not cached[1].isNull():
                return cached[1]
            pixmap, _stale = _previews._read_preview_pixmap(path, mtime)
            if pixmap is not None and not pixmap.isNull():
                return pixmap
            small = _previews.file_image_pixmap(path, asynchronous=True)     # demande l'apercu en fond
            if fallback is None and small is not None and not small.isNull():
                fallback = small
        if fallback is not None and not fallback.isNull():
            return fallback
        if path.suffix.lower() in RENDERABLE_3D_EXTENSIONS:
            note = "Aperçu pas encore rendu (clic droit dans la colonne pour le rendre)"
        else:
            note = "Aperçu en cours de chargement…"
        return placeholder_pixmap(path, note)

    def _on_focus_preview_ready(self, path_str: str, mtime: float, image):
        """Apercu du pipeline arrive : vignette de la pellicule, voisine du ruban, ou image au
        centre qui n'avait encore rien de mieux (il remplace la carte / la petite vignette)."""
        import focus
        focus._FILM.pop(path_str, None)
        focus._FILM_FAILED.pop(path_str, None)
        focus._CELLS.pop(path_str, None)
        focus._PROXY_SOURCES.pop(path_str, None)     # le proxy a pu changer de source
        self._focus_images.invalidate(Path(path_str))
        for mark in ("focus", "hover"):
            focus._MARKED.pop((path_str, mark), None)
        for key in [key for key in focus._THUMBS if key[0] == path_str]:
            focus._THUMBS.pop(key, None)
        if not self._project_columns_hidden:
            return
        if self._filmstrip is not None and self._filmstrip.isVisible():
            self._filmstrip.update()
        if self._focus_gallery is not None:
            self._focus_gallery.preview_ready(path_str)
        if image is not None and not image.isNull() and path_str in self._viewer_paths:
            self._focus_images.request(Path(path_str), urgent=path_str == self._focus_path)
            if path_str == self._focus_path and self._focus_images.get(Path(path_str)) is None:
                self._set_focus_origin_badge(Path(path_str), application_preview=True)
        overlay = self._focus_overlay
        if overlay is None or image is None or image.isNull():
            return
        if path_str != self._focus_path:
            if overlay.animating():
                overlay.update()
            return
        path = Path(path_str)
        if self._focus_images.supports(path):
            return  # le chargeur plein format remplacera l'image, jamais la vignette du pipeline
        if self._focus_images.get(path) is not None:
            return                                  # deja en pleine definition
        overlay.upgrade(QPixmap.fromImage(image), self._focus_images.known_natural(path))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and watched is self.scroll.viewport() and self._on_focus_wheel(event):
            return True
        return super().eventFilter(watched, event)

    def _on_focus_wheel(self, event) -> bool:
        """Etat focus (image seule au centre) : la molette passe d'une image a l'autre du dossier,
        vers le bas = suivante. Recue sur l'image elle-meme (FocusOverlay, on_wheel) ou n'importe
        ou dans la zone des colonnes masquees. Crans cumules (pave tactile : petits deltas)."""
        if not self._project_columns_hidden or self._focus_gallery is not None:
            return False
        if event.modifiers() & Qt.ControlModifier:
            self._viewer_ctrl_wheel(event)
            return True
        self._focus_wheel += event.angleDelta().y() or event.angleDelta().x()
        steps = int(self._focus_wheel / 120)
        if steps:
            self._focus_wheel -= steps * 120
            self._step_focus_image(-steps)
        return True

    def _step_focus_image(self, step: int):
        """Fichier `step` places plus loin (negatif : avant) parmi les fichiers a apercu de la
        colonne du fichier en cours (images, mais aussi .ma, .obj, .blend, PSD, plans, videos...),
        dans son ordre ; aux extremites, l'image rebondit (bump) au lieu de changer."""
        count = len(self._viewer_paths)
        if not step or not 0 <= self._viewer_index < count:
            return
        overlay = self._focus_overlay
        if overlay is not None and overlay.running:
            overlay.finish_now()
        target = max(0, min(count - 1, self._viewer_index + step))
        if target == self._viewer_index:
            if overlay is not None:
                overlay.bump(step)
            return
        self._viewer_go(target, target - self._viewer_index)

    # -- Visionneuse : ruban, pellicule, clavier, zoom --

    _VIEWER_SYNC_MS = 700

    def _enter_viewer(self):
        """Colonnes masquees : la visionneuse prend la main. Liste des fichiers du dossier (ordre
        de la colonne), image en cours a sa place definitive (taille reelle lue dans l'entete) et
        demandee en pleine definition, voisines prechargees, pellicule et clavier."""
        _column, first = self._focus_file_column()
        self._viewer_folder = self._viewer_entry_folder or (first.parent if first is not None else None)
        if self._recursive_on() and self._viewer_folder is not None:
            self._start_filter_scan(self._viewer_folder)         # liste à jour : relue en fond
        paths, current = self._scan_viewer_paths()
        self._viewer_purs = [p for p in paths if p.suffix.lower() in PUR_PREVIEW_EXTENSIONS]
        paths, self._viewer_index = self._expand_viewer_pureref(paths, current)
        self._viewer_paths = self._viewer_base = paths
        self._viewer_previews = {}
        if self._filmstrip is not None and self._viewer_index >= 0:
            self._filmstrip.set_paths(paths, self._viewer_index)
        self._sync_viewer_chrome()                       # pellicule creee : sa bande est reservee
        self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())
        if self._viewer_index >= 0:
            path = paths[self._viewer_index]
            self._focus_path = str(path)
            overlay = self._focus_overlay
            if overlay is not None:
                self._attach_viewer(overlay)
                # Place definitive (taille reelle, au-dessus de la pellicule), posee en debut de vol :
                # rien ne saute.
                overlay.set_natural(self._focus_images.natural_size(path) or overlay._natural, self._viewer_area())
                hit = self._focus_images.get(path)
                if hit is not None:
                    overlay.upgrade(hit[0], hit[2], hit[1])
                else:
                    self._focus_images.request(path, urgent=True)
            self._prefetch_viewer(self._viewer_index, 1)

    # -- Planches PureRef : leurs images dans la visionneuse --

    def _expand_viewer_pureref(self, paths: list, current: str | None) -> tuple:
        """(liste, rang du fichier en cours) ou chaque planche .pur est remplacee par ses images
        quand elles existent deja en fichiers ; sinon la planche reste (son apercu) et ses images
        sont extraites en fond (_on_pur_images_ready la remplacera). Planche en cours : l'image que
        l'inspecteur montre."""
        out, index = [], -1
        for path in paths:
            files = self._pur_files(path) if path.suffix.lower() in PUR_PREVIEW_EXTENSIONS else None
            if files:
                if str(path) == current:
                    shown = getattr(self.detail, "_pur_image_index", 0) \
                        if getattr(self.detail, "_pur_image_path", None) == str(path) else 0
                    index = len(out) + max(0, min(len(files) - 1, int(shown or 0)))
                out.extend(files)
                continue
            if str(path) == current:
                index = len(out)
            out.append(path)
        return out, index

    def _pur_files(self, pur: Path) -> list | None:
        mtime = _previews.cached_mtime(pur)
        if mtime is None:
            return None
        known = self._pur_expansions.get(str(pur))
        if known is not None and known[0] == mtime:
            return known[1] or None
        files = pur_image_files(pur, mtime)
        if files is None:
            self._start_pur_images(pur, mtime)
            return None
        self._remember_pur(pur, mtime, files)
        return files or None

    def _remember_pur(self, pur: Path, mtime: float, files: list):
        files = [Path(f) for f in files]
        self._pur_expansions[str(pur)] = (mtime, files)
        for rank, image in enumerate(files):
            self._pur_sources[str(image)] = (pur, rank)
            file_attributes.set_alias(image, pur.parent, f"{pur.name}/{image.name}")   # attributs : ceux de la planche
            _focus.DISPLAY_NAMES[str(image)] = f"{pur.name} · {rank + 1}/{len(files)}"

    def _start_pur_images(self, pur: Path, mtime: float):
        task = self._pur_tasks.get(str(pur))
        if task is not None and task.mtime == mtime:
            return
        task = PureRefImagesTask(pur, mtime)
        task.signals.finished.connect(self._on_pur_images_ready)
        self._pur_tasks[str(pur)] = task
        _PUR_EXPORT_POOL.start(task)

    def _on_pur_images_ready(self, pur_str: str, mtime: float, files, error: str):
        """Images d'une planche pretes : si la visionneuse la montre encore, elle est remplacee par
        ses images, sans changer l'image regardee (ou par sa 1re image si c'etait elle)."""
        self._pur_tasks.pop(pur_str, None)
        pur = Path(pur_str)
        if not files:
            self._pur_expansions[pur_str] = (mtime, [])
            return
        self._remember_pur(pur, mtime, files)
        try:
            pos = next(i for i, p in enumerate(self._viewer_paths) if str(p) == pur_str)
        except StopIteration:
            return
        images = self._pur_expansions[pur_str][1]
        self._viewer_paths[pos:pos + 1] = images
        current = self._viewer_index
        if current > pos:
            self._viewer_index = current + len(images) - 1
        if self._filmstrip is not None:
            self._filmstrip.set_paths(self._viewer_paths, self._viewer_index)
        if current == pos and self._viewer_active():
            self._viewer_go(pos, 0)                 # la planche montree devient sa 1re image

    def _viewer_active(self) -> bool:
        return (self._project_columns_hidden and self._focus_gallery is None
                and 0 <= self._viewer_index < len(self._viewer_paths))

    # -- Dossier dans la visionneuse + mode récursif (demande de l'utilisateur) --

    def _recursive_on(self) -> bool:
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_recursive", False))

    def _recursive_known(self) -> list | None:
        """Photos du dossier de la visionneuse ET de ses sous-dossiers (parcours en fond, file_filters.scan_files) ;
        None : mode coupé ou parcours pas encore fait."""
        folder = self._viewer_entry_folder or self._viewer_folder
        if not self._recursive_on() or folder is None:
            return None
        known = self._scope_files.get(str(folder))
        return [Path(entry[0]) for entry in known] if known is not None else None

    def _viewer_folder_files(self, folder: Path) -> list:
        """Fichiers à aperçu DIRECTEMENT dans `folder` : l'ordre de sa colonne si elle est ouverte, sinon le
        nom."""
        kinds = PREVIEWABLE_EXTENSIONS | PUR_PREVIEW_EXTENSIONS
        for column in [*self.columns, *self.group_columns]:
            if Path(column.directory) == folder:
                return [Path(item.data(ROLE_PATH)) for item in
                        (column.list.item(i) for i in range(column.list.count()))
                        if not item.data(ROLE_ISDIR) and Path(item.data(ROLE_PATH)).suffix.lower() in kinds]
        try:
            return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in kinds
                           and not p.name.startswith(".")), key=lambda p: p.name.casefold())
        except OSError:
            return []

    def _view_folder_in_viewer(self, folder: Path, column=None, gallery: bool = False):
        """Double-clic sur un dossier : la visionneuse s'ouvre sur sa première photo (la planche est à une
        touche : G). `gallery` (menu « Ouvrir la visionneuse à cet endroit ») : directement la PLANCHE, sans
        aucune image en focus. Mode récursif : les photos des sous-dossiers aussi (parcours en fond si
        besoin). Sans aucune photo à montrer : l'explorateur, comme avant."""
        if self._project_columns_hidden:
            return
        folder = Path(folder)
        files = self._viewer_folder_files(folder)
        if gallery and not files and not self._recursive_on():
            # Les photos sont dans les sous-dossiers : la planche les montre (mode récursif allumé pour cela,
            # remis si finalement il n'y en a aucune) ; jamais l'explorateur depuis ce menu.
            self._auto_recursive = True
            self._set_recursive(True)
        if self._recursive_on():
            known = self._scope_files.get(str(folder))
            if known is None:
                self._pending_folder_view = (folder, column, gallery)
                self._start_filter_scan(folder)
                return
            files = [Path(entry[0]) for entry in known] or files
        if not files:
            if gallery:
                self.path_label.setText(f"Aucune photo dans {folder.name} ni dans ses sous-dossiers")
                if getattr(self, "_auto_recursive", False):
                    self._set_recursive(False)
                self._auto_recursive = False
                return
            self.on_activated(folder)
            return
        self._auto_recursive = False
        first = files[0]

        def go():
            pixmap = self._focus_pixmap(first, None)
            slot = None
            if column is not None and pixmap is not None and not pixmap.isNull():
                for i in range(column.list.count()):
                    item = column.list.item(i)
                    if item.data(ROLE_PATH) == str(folder):
                        rect = column.list.visualItemRect(item)
                        side = max(8, min(rect.height(), rect.width()))
                        thumb = QRect(0, 0, side, side)
                        thumb.moveCenter(rect.center())
                        viewport = self.scroll.viewport()
                        slot = QRect(viewport.mapFromGlobal(column.list.viewport().mapToGlobal(thumb.topLeft())),
                                     thumb.size())
                        break
            if gallery:
                slot = None                                      # planche directe : aucune image ne vole
            if slot is not None:
                self._viewer_entry_source = (pixmap, slot)       # l'image part de la ligne du dossier
            self._viewer_entry_path = (None, first)
            self._viewer_entry_folder = folder
            # Planche directe : pas d'objet qui part au centre, donc la garde « sans colonne Focus » ne
            # s'applique pas (sinon les colonnes restaient et l'explorateur s'ouvrait).
            self._viewer_force_hide = gallery
            try:
                self._set_columns_hidden(True, animate=not gallery)
            finally:
                self._viewer_force_hide = False
                self._viewer_entry_source = None
                self._viewer_entry_path = None
                self._viewer_entry_folder = None
            if not self._project_columns_hidden:
                self.on_activated(folder)
            elif gallery:
                self._gallery_no_focus = True                    # aucune case « en cours » : pas de focus
                self._open_focus_gallery()
                self._gallery_no_focus = False
            elif self._focus_overlay is None and 0 <= self._viewer_index < len(self._viewer_paths):
                self._viewer_go(self._viewer_index)              # aucun objet au centre au départ : créé ici

        QTimer.singleShot(0, go)

    def _sync_recursive_button(self):
        """Bouton « Récursif » (visionneuse ou planche ouverte) : allumé (couleur du filtre actif) quand les
        photos des sous-dossiers sont montrées aussi."""
        viewer_mode = self._project_columns_hidden and (self._focus_gallery is not None or self._viewer_active())
        button = self._recursive_btn
        if not viewer_mode:
            if button is not None and not button.isHidden():
                button.hide()
                self._layout_viewer_buttons()
            return
        if button is None:
            # Icone (demande de l'utilisateur ; Reglages > Visionneuse > Icones > Recursif), plus un texte.
            button = self._recursive_btn = IconButton(
                "recursive", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._toggle_recursive)
        style_focus_button(button)
        on = self._recursive_on()
        button.set_alert(resolve_color_ref((ui_state.APPLIED_SETTINGS or {}).get("viewer_filter_active_color")
                                           or "#c62828") if on else None)
        button.setToolTip("Récursif : photos des sous-dossiers montrées (clic pour les retirer)" if on
                          else "Récursif : montrer aussi les photos des sous-dossiers")
        button.show()
        button.raise_()
        self._layout_viewer_buttons()
        if self._focus_overlay is not None:
            self._focus_overlay.set_holes(self._button_rects())

    def _toggle_recursive(self):
        """Bouton « Récursif » : bascule (voir `_set_recursive`)."""
        self._set_recursive(not self._recursive_on())

    def _set_recursive(self, value: bool):
        """Mode récursif (bouton « Récursif » ou case du menu d'un dossier), enregistré aussitôt (état temps
        réel) ; la liste de la visionneuse, la pellicule et la planche sont refaites sur place, l'image
        regardée gardée si elle y est encore."""
        value = bool(value)
        if value == self._recursive_on():
            return
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS["viewer_recursive"] = value
        from settings_store import save_live_state
        save_live_state("viewer_recursive", value)
        self._recursive_applied = value
        self._sync_settings_row("viewer_recursive", value)      # sa ligne de Reglages > Visionneuse suit
        self._refresh_recursive_list(value)

    def _sync_settings_row(self, setting: str, value):
        """La ligne `setting` de la fenetre de reglages (ouverte ou gardee en memoire) prend `value`."""
        dialog = getattr(self, "_settings_dialog_v2", None)
        if dialog is None:
            return
        try:
            for store in dialog.stores.values():
                for spec, widget in store.get("specs", ()):
                    if getattr(spec, "key", None) == setting and widget.isChecked() != bool(value):
                        widget.blockSignals(True)
                        widget.setChecked(bool(value))
                        widget.blockSignals(False)
        except (RuntimeError, AttributeError):
            pass

    def _refresh_recursive_list(self, value: bool):
        """Liste de la visionneuse / planche refaite pour le mode recursif `value`."""
        folder = self._viewer_folder
        if value and folder is not None:
            self._start_filter_scan(folder)                      # liste complète lue en fond
        self._apply_viewer_base()
        self._sync_recursive_button()

    def _apply_viewer_base(self):
        """Refait la liste de la visionneuse (récursive ou non) sans quitter l'image en cours ; pellicule et
        planche suivent."""
        folder = self._viewer_folder
        if not self._project_columns_hidden or folder is None:
            return
        recursive = self._recursive_on()
        if recursive:
            paths = self._recursive_known()
            if paths is None:
                return                                           # parcours en cours : l'arrivée relancera
        else:
            paths = self._viewer_folder_files(folder)
        if not paths:
            return
        current = (str(self._viewer_paths[self._viewer_index])
                   if 0 <= self._viewer_index < len(self._viewer_paths) else None)
        if not recursive:
            self._viewer_purs = [p for p in paths if p.suffix.lower() in PUR_PREVIEW_EXTENSIONS]
            paths, _index = self._expand_viewer_pureref(paths, current)
        else:
            self._viewer_purs = []
        if [str(p) for p in paths] == [str(p) for p in (self._viewer_base or [])]:
            return
        self._viewer_base = list(paths)
        shown, _found = self._filtered_gallery(list(paths), current, rescan=False)
        self._viewer_paths = list(shown or paths)
        index = next((i for i, p in enumerate(self._viewer_paths) if str(p) == current), -1)
        if self._filmstrip is not None:
            self._filmstrip.set_paths(self._viewer_paths, max(0, index))
        self._viewer_index = index if index >= 0 else 0
        if index < 0 and self._focus_gallery is None:
            self._viewer_go(0)                                   # l'image regardée n'est plus dans la liste
        if self._focus_gallery is not None:
            self._refresh_focus_gallery(rescan=False)
        self._sync_pur_buttons()
        self._sync_recursive_button()

    def _position_focus_origin_badge(self):
        badge = getattr(self, "_focus_origin_badge", None)
        if badge is not None:
            badge.move(scaled(12, 0), scaled(48, 0))

    def _set_focus_origin_badge(self, path: Path | None, *, decoded: bool = False,
                                application_preview: bool = False):
        """La source de l'image au centre (et celle du proxy) est dans le tableau de droite,
        « Paramètres de l'image » (lignes « Source du proxy » / « Source de l'aperçu plein écran »,
        demande de l'utilisateur) — plus d'encart près des boutons : ce tableau est relu quand
        l'image en focus ou son proxy arrive (la source a pu changer)."""
        badge = getattr(self, "_focus_origin_badge", None)
        if badge is not None:
            badge.hide()
        panel = getattr(self, "_info_panel", None)
        if panel is not None and path is not None and (decoded or application_preview):
            panel.refresh(path)

    def _sync_viewer_chrome(self):
        """Pellicule, raccourcis clavier et suivi de la souris : actifs seulement colonnes
        masquees, image seule au centre (pas pendant la planche)."""
        self._sync_collapse_button()
        self._request_crumbs()                   # visionneuse ouverte / fermee : son cheminement ou celui des colonnes
        if not self._project_columns_hidden:
            self._release_viewer_buttons()       # cadre « Visionneuse » de la barre : boutons rendus
            self._viewer_sync.stop()
            self._viewer_paths, self._viewer_index = [], -1
            self._viewer_base = []
            self._viewer_purs = []
            self._viewer_folder = None
            self._pending_folder_view = None
            if hasattr(self, "_focus_origin_badge"):
                self._focus_origin_badge.hide()
        self._sync_recursive_button()
        self._sync_pur_buttons()
        active = self._viewer_active()
        # I bascule l'inspecteur dans la navigation normale; en visionneuse,
        # cette touche reste réservée au tableau « Paramètres de l'image ».
        if hasattr(self, "_inspector_shortcut"):
            self._inspector_shortcut.setEnabled(not self._project_columns_hidden)
        if active and not self._large_lightroom_timer.isActive():
            self._large_lightroom_timer.start()
        elif not active:
            self._large_lightroom_timer.stop()
        if not active and hasattr(self, "_focus_origin_badge"):
            self._focus_origin_badge.hide()
        self._sync_lightroom_button()
        self._sync_viewer_100_button(active)
        if active and not self._viewer_keys:
            self._ensure_viewer_keys()
        for shortcut in self._viewer_keys:
            shortcut.setEnabled(active)
        self._sync_info_panel(active)
        strip = self._filmstrip
        if not active or not self._filmstrip_enabled():
            self._viewer_idle.stop()
            if strip is not None and not strip.isHidden():
                strip.hide()
            if active and self._focus_overlay is not None:
                self._focus_overlay.set_holes(self._button_rects())
            return
        if strip is None:
            strip = self._filmstrip = FocusFilmstrip(
                self.scroll.viewport(), focus_thumbnail, on_wheel=self._on_focus_wheel,
                on_double_click=self._toggle_project_columns_hidden,
                on_resized=self._on_filmstrip_resized, on_split=self._on_filmstrip_split,
                on_menu=self._filmstrip_menu)
            strip.keep_shown = self._film_style_open
            strip.chosen.connect(self._on_filmstrip_chosen)
            strip.set_paths(self._viewer_paths, self._viewer_index)
        if strip.isHidden():
            strip.setGeometry(self._filmstrip_rect())
            strip.set_current(self._viewer_index)
            strip.set_position(self._viewer_index)
            strip.show()
            strip.reveal()
        strip.raise_()
        if self._focus_overlay is not None:
            self._focus_overlay.set_holes(self._button_rects())
        holder = QApplication.focusWidget()
        if holder is None or not holder.isVisible():
            # Le widget qui avait le clavier a disparu (colonnes Focus rebaties par la navigation
            # de la visionneuse) : sans lui, plus aucun raccourci ne repondrait.
            self._park_keyboard_focus()
        if not self._viewer_idle.isActive():
            self._viewer_cursor = None
            self._viewer_idle.start()

    def _toggle_inspector(self):
        """Affiche ou masque l'inspecteur avec I, hors visionneuse."""
        if self._project_columns_hidden:
            return
        self._inspector_visible = not self._inspector_visible
        self.detail.setVisible(self._inspector_visible)

    def _sync_pur_buttons(self):
        """Visionneuse (ou planche) ouverte sur un dossier qui contient des planches PureRef : un
        bouton par fichier, a la suite des autres boutons (repli / masquer / planche, ou le bouton
        flottant), sur leur ligne, qui l'ouvre dans PureRef (logiciel par defaut). Meme habillage
        que ces boutons (style_focus_button), largeur = le nom."""
        purs = self._viewer_purs if self._project_columns_hidden else []
        viewport = self.scroll.viewport()
        while len(self._pur_buttons) < len(purs):
            button = IconButton("text", role_color("buttons", "#c4cacf"), C["text"], parent=viewport)
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(lambda _c=False, b=button: open_path(b._pur_path))
            self._pur_buttons.append(button)
        for button, pur in zip(self._pur_buttons, purs):
            style_focus_button(button)
            button._pur_path = pur
            button.set_text_label(pur.name)
            button.setToolTip(f"Ouvrir {pur.name} dans PureRef")
            width = button.fontMetrics().horizontalAdvance(pur.name) + scaled(20)
            button.setFixedWidth(max(button.width(), width))
            button.show()
            button.raise_()
        for button in self._pur_buttons[len(purs):]:
            button.hide()
        self._layout_viewer_buttons()

    def _sync_lightroom_button(self):
        """Affiche le bouton uniquement pour une photo gérée par un catalogue Lightroom."""
        button = self._lightroom_btn
        path = (self._viewer_paths[self._viewer_index]
                if self._viewer_active() else None)
        try:
            import lightroom_bridge
            available = path is not None and path.suffix.casefold() in lightroom_bridge._PREFETCH_EXTENSIONS \
                and lightroom_bridge.is_managed(path)
        except (ImportError, OSError, ValueError):
            available = False
        if not available:
            if button is not None:
                button.hide()
                self._layout_viewer_buttons()
            return
        if button is None:
            button = self._lightroom_btn = IconButton(
                "text", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._open_current_in_lightroom)
        style_focus_button(button)
        button.set_text_label("Modifier dans Lightroom")
        button.setToolTip("Ouvrir cette photo dans Lightroom Classic, en mode Développement")
        button.setFixedWidth(button.fontMetrics().horizontalAdvance("Modifier dans Lightroom") + scaled(20))
        button.show()
        button.raise_()
        self._layout_viewer_buttons()
        if self._focus_overlay is not None:
            button_rects = self._button_rects()
            self._focus_overlay.set_holes(button_rects)

    def _open_current_in_lightroom(self):
        if not self._viewer_active():
            return
        import lightroom_bridge
        path = self._viewer_paths[self._viewer_index]
        self.path_label.setText(f"Lightroom · ouverture de {path.name}…")
        lightroom_bridge.open_in_lightroom(path)

    def _sync_viewer_100_button(self, active: bool):
        """Bouton de taille reelle, visible uniquement dans la visionneuse d'image."""
        if not active:
            if self._viewer_100_btn is not None:
                self._viewer_100_btn.hide()
                self._layout_viewer_buttons()
            return
        button = self._viewer_100_btn
        if button is None:
            button = self._viewer_100_btn = IconButton(
                "text", role_color("buttons", "#c4cacf"), C["text"], parent=self.scroll.viewport())
            button.setCursor(Qt.ArrowCursor)
            button.setFlat(True)
            button.clicked.connect(self._viewer_show_actual_size)
        style_focus_button(button)
        button.set_text_label("100 %")
        button.setToolTip("Afficher la photo a sa taille reelle (100 %)")
        button.setFixedWidth(button.fontMetrics().horizontalAdvance("100 %") + scaled(20))
        button.show()
        button.raise_()
        self._layout_viewer_buttons()
        if self._focus_overlay is not None:
            self._focus_overlay.set_holes(self._button_rects())

    def _viewer_show_actual_size(self):
        if self._viewer_active() and self._focus_overlay is not None:
            self._focus_overlay.zoom_toggle_actual()

    # -- Rangee des boutons de la visionneuse / planche : ordre choisi a la main (Ctrl + glisser) --

    _BUTTON_DEFAULT_ORDER = ("hide", "gallery", "zoom100", "lightroom", "filter", "recursive", "pur")

    def _viewer_row_items(self) -> list:
        """(identifiant, bouton) des boutons deplacables de la rangee, dans l'ordre retenu
        (`viewer_button_order`) ; ceux qui n'y sont pas encore suivent, dans l'ordre par defaut. Le bouton
        de repliement reste en tete (sa place est un reglage)."""
        items = []
        if self.image_preview_columns:
            pc = self.image_preview_columns[0]
            for key, button in (("hide", pc.hide_btn), ("gallery", pc.gallery_btn)):
                if button is not None and not button.isHidden():
                    items.append((key, button))
        for key, button in (("gallery", self._floating_gallery_btn),
                            ("zoom100", self._viewer_100_btn),
                            ("lightroom", self._lightroom_btn), ("filter", self._filter_btn),
                            ("recursive", self._recursive_btn)):
            if button is not None and not button.isHidden():
                items.append((key, button))
        items.extend((f"pur:{b._pur_path.name}", b) for b in self._pur_buttons if not b.isHidden())
        order = list((ui_state.APPLIED_SETTINGS or {}).get("viewer_button_order") or [])
        defaults = self._BUTTON_DEFAULT_ORDER

        def rank(pair):
            index, (key, _button) = pair
            if key in order:
                return (0, order.index(key), index)
            return (1, defaults.index(key.split(":", 1)[0]), index)
        return [item for _i, item in sorted(enumerate(items), key=rank)]

    def _layout_viewer_buttons(self):
        """Pose la rangee dans l'ordre retenu DANS le cadre « Visionneuse » de la barre de navigation (demande de
        l'utilisateur) ; les elements du filtre suivent son bouton. Colonnes masquees seulement : sinon les
        boutons retournent chez eux (la colonne Focus place elle-meme les siens)."""
        if not self._project_columns_hidden:
            self._release_viewer_buttons()
            return
        group = self.titlebar.viewer_group()
        items = self._viewer_row_items()
        chips = self._filter_chips
        hosted = []
        origin = group.content_origin()
        x = origin.x()
        gap = scaled(4, 0)
        height = max((button.height() for _k, button in items), default=0)
        for key, button in items:
            self._host_in_group(button, group)
            hosted.append(button)
            button.move(x, origin.y() + (height - button.height()) // 2)
            x += button.width() + gap
            self._button_drag.hook(button)
            if key == "filter" and chips is not None and not chips.isHidden():
                self._host_in_group(chips, group)
                hosted.append(chips)
                chips.move(x - gap + scaled(6), origin.y() + (height - chips.height()) // 2)
                x = chips.x() + chips.width() + scaled(6)
        for widget in list(getattr(self, "_group_hosted", ())):  # n'est plus dans la rangee : rendu a son parent
            if widget not in hosted:
                self._send_home(widget)
        self._group_hosted = hosted
        if not hosted:
            group.hide()
            return
        group.fit(x - gap, height)
        group.show()
        self.titlebar.place_viewer_group()
        for widget in hosted:
            widget.show()
            widget.raise_()
        pc = self.image_preview_columns[0] if self.image_preview_columns else None
        if pc is not None:
            pc.fit_buttons()

    @staticmethod
    def _host_in_group(widget: QWidget, group: QWidget):
        if widget.parentWidget() is not group:
            if not hasattr(widget, "_viewer_home"):
                widget._viewer_home = widget.parentWidget()
            widget.setParent(group)

    def _send_home(self, widget: QWidget):
        """Bouton sorti du cadre « Visionneuse » : rendu a son parent d'origine (colonne Focus, zone des colonnes) ;
        son parent a disparu (colonne Focus refaite) : detruit."""
        try:
            home = getattr(widget, "_viewer_home", None)
            if home is not None and shiboken6.isValid(home):
                widget.setParent(home)
                widget.hide()
                del widget._viewer_home
            else:
                widget.hide()
                widget.deleteLater()
        except RuntimeError:
            pass

    def _release_viewer_buttons(self):
        """Colonnes revenues : tous les boutons du cadre « Visionneuse » repartent chez eux, le cadre se cache ; le
        bouton « masquer » de la colonne Focus y redevient visible a sa place."""
        hosted = list(getattr(self, "_group_hosted", ()))
        self._group_hosted = []
        group = getattr(getattr(self, "titlebar", None), "_viewer_group", None)
        if group is not None and not group.isHidden():
            group.hide()
        if not hosted:
            return
        for widget in hosted:
            self._send_home(widget)
        for pc in self.image_preview_columns:
            if not shiboken6.isValid(pc):
                continue
            if pc.hide_btn is not None and pc.hide_btn.parentWidget() is pc:
                pc.hide_btn.show()
            pc._place_hide_btn()

    def _move_viewer_button(self, keys: list, source: int, target: int):
        """Glisser termine : le bouton `source` passe devant l'emplacement `target` (0..len) ; ordre
        enregistre aussitot (etat temps reel), les boutons absents gardent leur rang relatif a la fin."""
        keys = list(keys)
        moved = keys.pop(source)
        keys.insert(target - (1 if target > source else 0), moved)
        settings = ui_state.APPLIED_SETTINGS if isinstance(ui_state.APPLIED_SETTINGS, dict) else {}
        saved = list(settings.get("viewer_button_order") or [])
        order = keys + [k for k in saved if k not in keys]
        settings["viewer_button_order"] = order
        from settings_store import save_live_state
        save_live_state("viewer_button_order", order)
        self._layout_viewer_buttons()

    @staticmethod
    def _filmstrip_enabled() -> bool:
        """Reglages > Visionneuse > « Diapositives sous l'image en focus » (la pellicule)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_filmstrip_enabled", True))

    @staticmethod
    def _info_enabled() -> bool:
        """Reglages > Visionneuse > « Parametres de l'image » (tableau a droite de l'image)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_info_enabled", False))

    @staticmethod
    def _viewer_slide_enabled() -> bool:
        """Reglages > Visionneuse > « Effet slide entre les images » (le ruban)."""
        return bool((ui_state.APPLIED_SETTINGS or {}).get("viewer_slide_enabled", True))

    def _apply_viewer_settings(self):
        """Reglages de la visionneuse appliques en direct : pellicule affichee ou non, et l'image
        au centre recalee sur la zone qui lui revient (la bande de la pellicule est liberee)."""
        self._sync_viewer_toggle_keys()
        recursive = self._recursive_on()
        if recursive != getattr(self, "_recursive_applied", recursive):
            self._recursive_applied = recursive                  # ligne « Recursif » des reglages
            self._refresh_recursive_list(recursive)
        self._recursive_applied = recursive
        group = getattr(getattr(self, "titlebar", None), "_viewer_group", None)
        if group is not None:
            group.restyle()                     # Reglages > Visionneuse > Regroupement
            if not group.isHidden():
                self._layout_viewer_buttons()
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.restyle()                     # habillage des reglages : suit leurs changements
        self._sync_viewer_chrome()
        strip = self._filmstrip
        if strip is not None and strip.isVisible():
            # Habillage des diapositives (Reglages > Visionneuse > Tableau / sous-cellules) : la
            # bande suit la hauteur des cellules (image + texte).
            if strip.height() != strip.strip_height():
                strip.setGeometry(self._filmstrip_rect())
            strip.update()
            strip.reveal()                       # montree pendant qu'on la regle (sinon effacee)
        if self._focus_gallery is not None:
            self._focus_gallery.restyle()        # la planche : memes reglages
        overlay = self._focus_overlay
        if overlay is not None:
            overlay.restyle()                    # Reglages > Visionneuse > Focus : cadre de l'image
        if overlay is not None and self._project_columns_hidden:
            overlay.set_geometry_target(self._viewer_area())
            self._focus_images.set_fit(self._viewer_fit_size(), self.devicePixelRatioF())

    # -- Diapositives : sous-cellules image | texte, tableau a la volee (clic droit) --

    def _on_filmstrip_split(self, ratio: float, final: bool):
        """Ctrl + bordure image | texte d'une diapositive : hauteur du texte, appliquee en direct (seule
        la bande suit pendant le geste ; l'image au centre se recale au relachement) et enregistree."""
        self._on_filmstrip_style({"viewer_film_text_ratio": round(float(ratio), 4)}, light=not final)
        if final:
            self._flush_filmstrip_style()

    def _on_gallery_split(self, height: int, final: bool):
        """Ctrl + bordure image | texte d'une case de la planche : hauteur du texte (px), en direct,
        enregistree."""
        self._on_filmstrip_style({"viewer_gallery_text_height": int(height)}, light=True)
        if self._focus_gallery is not None:
            self._focus_gallery.restyle()
        if final:
            self._flush_filmstrip_style()

    def _filmstrip_menu(self, global_pos):
        """Clic droit sur la pellicule : style du tableau, de la sous-cellule image ou de la sous-cellule
        texte, dans la fenetre « Changement de style a la volee » (pas d'override : une seule visionneuse,
        ce sont les valeurs de Reglages > Visionneuse)."""
        from settings_window_v2 import VIEWER_FILM_GROUPS
        menu = Menu(self)
        head = menu.addAction("Changement de style à la volée")
        head.setEnabled(False)
        menu.addSeparator()
        names = {"Tableau": "Tableau…", "Cellules": "Cellules…", "Sous cellule texte": "Cellule texte…"}
        actions = {menu.addAction(names.get(title, title)): (title, group) for title, group in VIEWER_FILM_GROUPS}
        chosen = menu.exec(global_pos)
        if chosen in actions:
            QTimer.singleShot(0, lambda: self._open_filmstrip_style(*actions[chosen]))

    def _open_filmstrip_style(self, title: str, group: str):
        import settings_window_v2 as v2
        from settings_quick_style import QuickStyleWindow
        previous, self._film_style_window = getattr(self, "_film_style_window", None), None
        if previous is not None:
            try:
                previous.close()
            except RuntimeError:              # deja detruite
                pass
        settings = dict(DEFAULT_SETTINGS)
        settings.update(ui_state.APPLIED_SETTINGS or load_settings())
        window = self._film_style_window = QuickStyleWindow(
            f"Visionneuse : {title}", v2.CATALOG[group], settings, title=f"Diapositives — {title.lower()}",
            settings=settings, parent=self)
        window.styleChanged.connect(self._on_filmstrip_style)
        window.destroyed.connect(lambda *_a, w=window: self._forget_film_style_window(w))
        window.move(QCursor.pos() + QPoint(12, 12))
        window.show()

    def _film_style_open(self) -> bool:
        """Une fenetre qui regle les diapositives est ouverte (tableau a la volee, reglages v2) : la
        pellicule reste affichee pour qu'on voie l'effet."""
        for window in (getattr(self, "_film_style_window", None), getattr(self, "_settings_dialog_v2", None)):
            try:
                if window is not None and window.isVisible():
                    return True
            except RuntimeError:
                pass
        return False

    def _forget_film_style_window(self, window):
        if getattr(self, "_film_style_window", None) is window:
            self._film_style_window = None
        self._flush_filmstrip_style()

    def _on_filmstrip_style(self, values: dict, light: bool = False):
        """Valeurs des diapositives changees (tableau a la volee, bordure image | texte) : appliquees aussitot,
        ecrites sur le disque 300 ms apres la derniere (regroupe un glissement de curseur)."""
        if not isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS = load_settings()
        ui_state.APPLIED_SETTINGS.update(values)
        pending = getattr(self, "_film_style_pending", None)
        if pending is None:
            pending = self._film_style_pending = {}
        pending.update(values)
        timer = getattr(self, "_film_style_timer", None)
        if timer is None:
            timer = self._film_style_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(300)
            timer.timeout.connect(self._flush_filmstrip_style)
        timer.start()
        strip = self._filmstrip
        if light:
            if strip is not None and strip.isVisible():
                strip.setGeometry(self._filmstrip_rect())
                strip.update()
        else:
            self._apply_viewer_settings()

    def _flush_filmstrip_style(self):
        """Enregistre les valeurs en attente ; la fenetre de reglages ouverte les reprend (ses tableaux
        Visionneuse sont refaits), sinon elle les ecraserait avec ses anciennes valeurs."""
        timer = getattr(self, "_film_style_timer", None)
        if timer is not None:
            timer.stop()
        pending = getattr(self, "_film_style_pending", None)
        if not pending:
            return
        values, self._film_style_pending = dict(pending), {}
        settings = load_settings()
        settings.update(values)
        save_settings(settings)
        # Preset par defaut actif : le mettre a jour aussi, sinon load_settings le rejoue PAR-DESSUS le
        # fichier au prochain lancement et les valeurs a la volee sont perdues (bug signale).
        import browser_core
        browser_core._sync_default_preset_override(settings, lambda preset: preset.update(values))
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values(values)
        except RuntimeError:                  # fenetre de reglages detruite
            pass

    def _on_filmstrip_resized(self):
        """Vignettes de la pellicule zoomees (Ctrl+molette) : sa bande change de hauteur, l'image
        au centre se recale sur la zone qui lui reste."""
        if self._filmstrip is not None and self._filmstrip.isVisible():
            self._filmstrip.setGeometry(self._filmstrip_rect())
        self._apply_viewer_settings()

    def _raise_viewer_chrome(self):
        """La pellicule et le bouton flottant restent au-dessus de l'image et des fondus."""
        for widget in (self._filmstrip, getattr(self, "_info_panel", None), self._floating_gallery_btn,
                       self._lightroom_btn, self._viewer_100_btn, self._recursive_btn,
                       getattr(self, "_focus_origin_badge", None), *self._pur_buttons):
            if widget is not None and widget.isVisible():
                widget.raise_()

    def _park_keyboard_focus(self):
        """Clavier gare sur le bouton « masquer » (ou la zone des colonnes) : jamais sur un champ
        texte visible, qui avalerait les raccourcis de la visionneuse."""
        if not self._project_columns_hidden:
            return
        if self.image_preview_columns and self.image_preview_columns[0].hide_btn is not None:
            self.image_preview_columns[0].hide_btn.setFocus()
        else:
            self.scroll.viewport().setFocus()

    def _filmstrip_rect(self) -> QRect:
        viewport = self.scroll.viewport()
        height = self._filmstrip.strip_height() if self._filmstrip is not None else 0
        return QRect(0, viewport.height() - height, viewport.width(), height)

    def _viewer_area(self) -> QRect:
        """Zone ou l'image se pose au centre : celle des colonnes, moins la bande de la pellicule
        (reservee meme quand elle s'efface : l'image ne bouge jamais et n'est jamais couverte) et
        moins celle du tableau des parametres a droite (Reglages > Visionneuse)."""
        area = QRect(self._focus_area())
        if not (self._project_columns_hidden and 0 <= self._viewer_index < len(self._viewer_paths)):
            return area                     # (planche ouverte comprise : l'image y revient a la meme place)
        strip = self._filmstrip
        if strip is not None and self._filmstrip_enabled():
            area.setHeight(max(1, area.height() - max(0, strip.strip_height() - scaled(30))))
        if self._info_enabled():
            # Bande du tableau retiree des DEUX cotes : l'image reste centree sur toute la largeur,
            # sans jamais passer sous le tableau.
            band = min(FocusInfoPanel.panel_width() + scaled(16), max(0, area.width() // 2 - 1))
            area.adjust(band, 0, -band, 0)
        return area

    def _info_rect(self) -> QRect:
        """Place du tableau des parametres : a droite de l'image, au-dessus de la pellicule."""
        full, area = self._focus_area(), self._viewer_area()
        margin = scaled(16)
        width = FocusInfoPanel.panel_width()
        return QRect(full.right() + 1 - margin - width, area.y() + margin, width,
                     max(1, area.height() - 2 * margin))

    def _sync_info_panel(self, active: bool):
        """Tableau des parametres de l'image (Reglages > Visionneuse > « Parametres de l'image »,
        touche I) : visible visionneuse ouverte, sur le fichier en cours."""
        panel = getattr(self, "_info_panel", None)
        if not (active and self._info_enabled()):
            if panel is not None and not panel.isHidden():
                panel.hide()
            return
        if panel is None:
            panel = self._info_panel = FocusInfoPanel(self.scroll.viewport())
        panel.setGeometry(self._info_rect())
        if 0 <= self._viewer_index < len(self._viewer_paths):
            panel.set_path(self._viewer_paths[self._viewer_index])
        if panel.isHidden():
            panel.show()
        panel.raise_()

    def _viewer_fit_size(self) -> QSize:
        """Zone ou l'image est ajustee, en pixels physiques (marges de fit_rect retirees)."""
        area = self._viewer_area()
        dpr = self.devicePixelRatioF() or 1.0
        return QSize(max(1, round((area.width() - 80) * dpr)), max(1, round((area.height() - 80) * dpr)))

    def _attach_viewer(self, overlay):
        overlay.set_viewer(self._viewer_neighbour, self._on_viewer_moved, self._button_rects(),
                           on_click=self._on_viewer_image_click)

    def _on_viewer_image_click(self, anchor=None):
        """Clic simple sur l'image : bascule entre ajustement ecran et taille reelle (100 %)."""
        if self._viewer_active() and self._focus_overlay is not None:
            self._focus_overlay.zoom_toggle_actual(anchor)

    def _viewer_go(self, index: int, delta: int = 0, fallback: QPixmap | None = None):
        """Montre le fichier de rang `index` ; `delta` = son ecart avec le precedent (le ruban
        glisse de ce cote). Rien de bloquant : image prete, sinon la meilleure en memoire en
        attendant (_on_focus_image_ready la remplace)."""
        paths = self._viewer_paths
        if not 0 <= index < len(paths):
            return
        self._viewer_index = index
        path = paths[index]
        self._sync_lightroom_button()
        self._focus_path = str(path)
        self._request_crumbs()                   # cheminement : l'image suit AUSSITOT (pas la colonne cachee)
        pixmap, natural, full = self._viewer_image(path, fallback)
        self._set_focus_origin_badge(path)     # la source se lit dans « Paramètres de l'image »
        overlay = self._focus_overlay
        if overlay is None and self._project_columns_hidden and not pixmap.isNull():
            # Colonnes masquees sans objet au centre (fichier sans apercu au depart) : on le cree.
            size = natural if natural is not None else QSizeF(pixmap.width(), pixmap.height())
            target = fit_rect(size, self._viewer_area())
            overlay = self._focus_overlay = FocusOverlay(
                self.scroll.viewport(), pixmap, target, target, 1.0, 1.0, 1,
                on_double_click=self._toggle_project_columns_hidden, on_wheel=self._on_focus_wheel)
            self._attach_viewer(overlay)
            overlay.show()
            overlay.raise_()
            self._raise_viewer_chrome()
            delta = 0
        # Reglages > Visionneuse > « Effet slide entre les images » coupe : l'image change sur place
        # (pas de ruban) ; la pellicule, elle, defile comme avant ; `delta` sert aussi au prechargement.
        slide = delta if self._viewer_slide_enabled() else 0
        if overlay is not None and not pixmap.isNull():
            overlay.show_image(pixmap, natural, full, slide)
        # Le retour vers l'inspecteur doit viser la place de la NOUVELLE image : capture refaite.
        self._columns_snapshot = None
        self._prefetch_viewer(index, -1 if delta < 0 else 1)
        strip = self._filmstrip
        if strip is not None:
            strip.set_current(index)
            if not delta:
                strip.set_position(index)
            elif not slide:                          # pas de ruban a suivre : la pellicule glisse seule
                strip.glide_to(index)
        panel = getattr(self, "_info_panel", None)
        if panel is not None and panel.isVisible():
            panel.set_path(path)
            if strip is not None:
                strip.reveal()                   # pas de pellicule (reglage coupe) : rien a montrer
        self._viewer_sync.start()

    def _viewer_image(self, path: Path, fallback: QPixmap | None = None) -> tuple:
        """(pixmap, taille reelle ou None, image pleine definition ou None) pour `path`."""
        hit = self._focus_images.get(path)
        if hit is not None:
            return hit[0], hit[2], hit[1]
        natural = self._focus_images.natural_size(path)
        self._focus_images.request(path, urgent=True)
        return self._focus_pixmap(path, fallback), natural, None

    def _viewer_neighbour(self, k: int):
        """Voisine k du ruban, pour le dessin du glissement : seulement ce qui est deja en memoire."""
        i = self._viewer_index + k
        if not 0 <= i < len(self._viewer_paths):
            return None
        path = self._viewer_paths[i]
        hit = self._focus_images.get(path)
        if hit is not None:
            return hit[0], hit[2]
        pixmap = self._viewer_previews.get(str(path))
        if pixmap is None:
            cached = _previews._file_image_cache.get(str(path))
            pixmap = cached[1] if cached is not None else None
        if pixmap is None or pixmap.isNull():
            # Defilement rapide : la petite vignette des colonnes en attendant, plutot que du vide.
            pixmap = _previews.file_image_pixmap(path, asynchronous=True)
        if pixmap is None or pixmap.isNull():
            return None
        return pixmap, self._focus_images.known_natural(path)

    def _prefetch_viewer(self, index: int, direction: int):
        """Prepare les voisines (d'abord dans le sens de la marche) : decodage en fond des images,
        apercus des autres fichiers lus apres le glissement (lecture disque)."""
        paths = self._viewer_paths
        later = []
        self._focus_images.retain(paths[max(0, index - 3):index + 4])
        for k in (direction, -direction, 2 * direction, 3 * direction, -2 * direction):
            i = index + k
            if not 0 <= i < len(paths):
                continue
            path = paths[i]
            if self._focus_images.supports(path):
                if path.suffix.casefold() in RAW_EXTENSIONS and abs(k) > 1:
                    continue  # grands JPEG embarqués : seulement les deux voisines immédiates
                self._focus_images.natural_size(path)
                self._focus_images.request(path)
            elif str(path) not in self._viewer_previews:
                later.append(path)
        if later:
            QTimer.singleShot(FocusOverlay.SLIDE_MS + 40, lambda: self._prefetch_previews(later))

    def _prefetch_previews(self, paths: list):
        if not self._project_columns_hidden:
            return
        for path in paths:
            key = str(path)
            if key in self._viewer_previews:
                continue
            mtime = _previews.cached_mtime(path)
            if mtime is None:
                continue
            cached = _previews._file_image_cache.get(key)
            pixmap = cached[1] if cached is not None and cached[0] == mtime else None
            if pixmap is None:
                pixmap, _stale = _previews._read_preview_pixmap(path, mtime)
            if pixmap is None or pixmap.isNull():
                _previews.file_image_pixmap(path, asynchronous=True)
                continue
            if len(self._viewer_previews) > 48:
                self._viewer_previews.clear()
            self._viewer_previews[key] = pixmap

    def _on_viewer_moved(self, offset: float):
        """Chaque pas du ruban : la pellicule glisse avec lui (sauf quand elle glisse seule, effet slide
        coupe : un pas sans decalage, zoom ou rebond, l'arreterait net)."""
        strip = self._filmstrip
        if strip is not None and self._viewer_index >= 0 and not (offset == 0 and strip.gliding()):
            strip.set_position(self._viewer_index - offset)

    def _on_focus_image_ready(self, key: str):
        """Image pleine definition prete : celle du centre se precise (sans bouger), une voisine
        en plein glissement apparait."""
        overlay = self._focus_overlay
        if overlay is None or not self._project_columns_hidden:
            return
        if 0 <= self._viewer_index < len(self._viewer_paths) and key == str(self._viewer_paths[self._viewer_index]):
            hit = self._focus_images.get(Path(key))
            if hit is not None:
                self._set_focus_origin_badge(Path(key), decoded=True)
                overlay.upgrade(hit[0], hit[2], hit[1])
        elif overlay.animating():
            overlay.update()

    def _on_filmstrip_chosen(self, index: int):
        if index != self._viewer_index:
            self._viewer_go(index, index - self._viewer_index)

    def _viewer_jump(self, index: int):
        index = max(0, min(len(self._viewer_paths) - 1, index))
        if 0 <= self._viewer_index != index:
            self._viewer_go(index, index - self._viewer_index)

    def _sync_viewer_selection(self):
        """Au repos : la colonne (masquee) et l'inspecteur passent sur l'image montree. Repousse
        tant que l'image bouge (pas d'a-coup en plein glissement)."""
        if not self._viewer_active():
            return
        overlay = self._focus_overlay
        if overlay is not None and overlay.animating():
            self._viewer_sync.start()
            return
        path = self._viewer_paths[self._viewer_index]
        self._select_viewer_file(path)
        self._request_current_lightroom_preview()
        self._return_grab.start()                # colonnes changees : leur capture de retour, au repos

    def _request_current_lightroom_preview(self):
        if not self._viewer_active():
            return
        import lightroom_bridge
        fit = self._viewer_fit_size()
        lightroom_bridge.ensure_large_preview(
            self._viewer_paths[self._viewer_index], fit.width(), fit.height())

    def _settle_columns_layout(self):
        """Colonnes re-affichees le temps d'une capture : leurs mises en page en attente (inspecteur mis a
        jour pendant le masquage : un widget cache ne se remet pas en page) sont faites TOUT DE SUITE, sans
        rien peindre. Sinon capture et place de retour de l'image etaient relevees sur l'ancienne mise en
        page : l'image arrivait 50 a 80 px a cote de l'apercu de l'inspecteur et sautait a la fin."""
        self.columns_layout.activate()
        for _ in range(3):
            QCoreApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        self.columns_layout.activate()

    def _pregrab_columns(self):
        """Visionneuse ouverte, au repos : la capture des colonnes pour leur retour est faite D'AVANCE
        (colonnes affichees, capturees, re-masquees sans retour a la boucle d'evenements : rien ne
        s'affiche), avec la place de retour de l'image dans l'inspecteur. Le retour la trouve a jour et
        demarre aussitot ; avant, il la refaisait au clic (~50 ms) apres la synchro de la colonne (~100 ms) :
        la saccade signalee au retour aux colonnes."""
        if not self._project_columns_hidden:
            return
        overlay, gallery = self._focus_overlay, self._focus_gallery
        if (_anim_running(self._columns_fade) or self._viewer_sync.isActive()
                or (overlay is not None and (overlay.running or overlay.animating()))
                or (gallery is not None and gallery._busy())):
            self._return_grab.start()            # une animation tourne : plus tard
            return
        if gallery is not None and not self._gallery_deselected:
            # Planche ouverte : sa sortie vers les colonnes laisse la colonne SANS fichier selectionne. Cette
            # deselection est faite d'avance (colonnes masquees : rien ne se voit) pour que la capture du
            # retour la montre deja ; la sortie demarre alors aussitot (avant : ~90 ms au clic). Revenir a
            # une image la reselectionne (_close_focus_gallery -> synchro).
            self._gallery_deselected = True
            self._deselect_viewer_file()
        cached = self._columns_snapshot
        if (cached is not None and len(cached) > 5 and cached[2] == self.scroll.viewport().size()
                and cached[3] == self._columns_epoch and cached[5] == self._project_columns_collapsed):
            return                               # deja a jour
        try:
            self._apply_columns_hidden(False)
            self._settle_columns_layout()
            snapshot = self._grab_columns()
            source = self._focus_source()        # place de retour (inspecteur affiche le temps de la capture)
            self._columns_snapshot = (*snapshot, time.monotonic(), self._project_columns_collapsed, (source,))
        finally:
            self._apply_columns_hidden(True)

    def _flush_viewer_sync(self):
        """Tout de suite (retour des colonnes) : la colonne et l'inspecteur rattrapent l'image."""
        pending = self._viewer_sync.isActive()
        self._viewer_sync.stop()
        if pending and 0 <= self._viewer_index < len(self._viewer_paths):
            self._select_viewer_file(self._viewer_paths[self._viewer_index])

    def _select_viewer_file(self, path: Path):
        source = self._pur_sources.get(str(path))
        if source is not None:
            # Image d'une planche PureRef : la planche dans sa colonne, l'inspecteur sur cette image.
            self._select_viewer_file(source[0])
            # L'inspecteur va sur CETTE image de la planche, meme si ses images ne sont pas encore listees
            # (extraction en fond : avant, il finissait sur la premiere — signale).
            self.detail.select_pur_image(str(source[0]), source[1])
            return
        key = str(path)
        column, current = self._focus_file_column()
        if current is not None and str(current) == key:
            return
        candidates = [column] if column is not None else []
        candidates += [c for c in [*self.columns, *self.group_columns] if c is not column]
        for candidate in candidates:
            view = candidate.list
            for i in range(view.count()):
                item = view.item(i)
                if item.data(ROLE_PATH) == key:
                    if view.currentItem() is not item:
                        view.setCurrentItem(item)          # navigation : l'inspecteur suit
                    view.scrollToItem(item)
                    return
        # Fichier d'un autre dossier (planche filtree sur une portee large) : les colonnes vont jusqu'a lui.
        self._navigate_to(path)

    def _ensure_viewer_keys(self):
        """Raccourcis de la visionneuse (actifs seulement image seule au centre, voir
        _sync_viewer_chrome) : fleches / Page / Espace / Retour arriere = suivante / precedente,
        Debut / Fin, G = planche, + / - / 0 / 1 = zoom (- sur l'image ajustee : planche), Echap =
        dezoomer puis revenir aux colonnes."""
        def add(keys, slot):
            for key in keys:
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.setContext(Qt.WindowShortcut)
                shortcut.setEnabled(False)
                shortcut.activated.connect(slot)
                self._viewer_keys.append(shortcut)
        add(("Right", "Down", "PgDown", "Space"), lambda: self._step_focus_image(1))
        add(("Left", "Up", "PgUp", "Backspace"), lambda: self._step_focus_image(-1))
        add(("Home",), lambda: self._viewer_jump(0))
        add(("End",), lambda: self._viewer_jump(len(self._viewer_paths) - 1))
        add(("G",), self._toggle_focus_gallery)
        add(("+", "="), lambda: self._viewer_zoom(1.25))
        add(("-",), lambda: self._viewer_zoom(0.8))
        add(("0",), lambda: self._focus_overlay is not None and self._focus_overlay.zoom_reset())
        add(("1",), lambda: self._focus_overlay is not None and self._focus_overlay.zoom_toggle_actual())
        add(("Esc",), self._viewer_escape)
        # Touches reglables (Reglages > Visionneuse, colonne Raccourci) : chacune bascule sa ligne.
        self._viewer_toggle_keys = {}
        for setting in self._VIEWER_TOGGLES:
            shortcut = QShortcut(self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.setEnabled(False)
            shortcut.activated.connect(lambda setting=setting: self._toggle_viewer_setting(setting))
            self._viewer_keys.append(shortcut)
            self._viewer_toggle_keys[setting] = shortcut
        self._sync_viewer_toggle_keys()

    # Lignes de Reglages > Visionneuse qui ont une touche : reglage -> (cle de la touche, defaut).
    _VIEWER_TOGGLES = {"viewer_filmstrip_enabled": ("viewer_filmstrip_shortcut", True),
                       "viewer_info_enabled": ("viewer_info_shortcut", False)}

    def _on_element_style_saved(self, key: str, value):
        """Override d'un element enregistre (clic droit > Override settings) : les reglages appliques
        le connaissent ; une surcharge de colonne restyle la fenetre (regroupe, 60 ms)."""
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        self._interface_move_mode._on_text_style_saved(key, value)
        if key == "element_style_overrides":
            return
        timer = getattr(self, "_override_apply_timer", None)
        if timer is None:
            timer = self._override_apply_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(60)
            timer.timeout.connect(lambda: self._apply_settings(dict(ui_state.APPLIED_SETTINGS or {})))
        timer.start()

    def _sync_viewer_toggle_keys(self):
        applied = ui_state.APPLIED_SETTINGS or {}
        for setting, shortcut in (getattr(self, "_viewer_toggle_keys", None) or {}).items():
            shortcut.setKey(QKeySequence(str(applied.get(self._VIEWER_TOGGLES[setting][0]) or "")))

    def _toggle_viewer_setting(self, setting: str):
        """Touche d'une ligne de Reglages > Visionneuse : bascule le reglage, l'enregistre aussitot ;
        la fenetre de reglages ouverte suit (sa ligne est mise a jour)."""
        default = self._VIEWER_TOGGLES[setting][1]
        enabled = not bool((ui_state.APPLIED_SETTINGS or {}).get(setting, default))
        self._write_setting_now(setting, enabled)
        self._apply_viewer_settings()

    def _write_setting_now(self, setting: str, enabled: bool):
        """Reglage oui / non change hors de la fenetre de reglages (touche, bouton du board) : enregistre
        aussitot (fichier + preset par defaut actif) ; la fenetre de reglages ouverte suit (sa ligne)."""
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            for store in (dialog.stores.values() if dialog is not None and dialog.isVisible() else ()):
                for spec, widget in store.get("specs", ()):
                    if getattr(spec, "key", None) == setting:
                        if isinstance(enabled, bool) and hasattr(widget, "setChecked"):
                            widget.setChecked(enabled)
                        elif isinstance(enabled, (int, float)) and hasattr(widget, "setValue"):
                            widget.setValue(int(enabled))   # curseur (module CAD : fenetre des accrochages)
        except (RuntimeError, TypeError):
            pass
        settings = load_settings()
        settings[setting] = enabled
        save_settings(settings)
        import browser_core                       # preset par defaut actif : sinon il rejoue l'ancienne valeur
        browser_core._sync_default_preset_override(settings, lambda preset: preset.__setitem__(setting, enabled))
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[setting] = enabled

    def _viewer_zoom(self, factor: float):
        overlay = self._focus_overlay
        if overlay is None:
            return
        if factor < 1.0 and not overlay.zoomed():
            self._open_focus_gallery()               # dezoomer l'image ajustee = voir tout le dossier
            return
        overlay.zoom_by(factor)

    def _viewer_escape(self):
        overlay = self._focus_overlay
        if overlay is not None and overlay.zoomed():
            overlay.zoom_reset()
        else:
            self._set_columns_hidden(False)

    def _viewer_ctrl_wheel(self, event):
        """Ctrl+molette : zoom autour du curseur ; vers l'arriere sur l'image ajustee, ouvre la
        planche (zoom « semantique », le pendant de Ctrl+molette avant dans la planche)."""
        overlay = self._focus_overlay
        delta = event.angleDelta().y()
        if overlay is None or not delta:
            return
        if delta < 0 and not overlay.zoomed():
            self._focus_pinch += delta
            if self._focus_pinch <= -120:
                self._focus_pinch = 0
                self._open_focus_gallery()
            return
        self._focus_pinch = 0
        anchor = QPointF(overlay.mapFromGlobal(event.globalPosition().toPoint()))
        overlay.zoom_by(1.2 ** (delta / 120), anchor)

    def _poll_viewer_cursor(self):
        """La pellicule s'efface quand la souris ne bouge plus et revient au moindre mouvement
        au-dessus de la fenetre (releve leger, pas de suivi de souris sur toute la zone)."""
        pos = QCursor.pos()
        if pos == self._viewer_cursor:
            return
        moved = self._viewer_cursor is not None
        self._viewer_cursor = pos
        if moved and self._filmstrip is not None and self.rect().contains(self.mapFromGlobal(pos)):
            self._filmstrip.reveal()

    def _enforce_hidden_columns(self, final: bool = False):
        try:
            self._enforce_hidden_columns_now(final)
        finally:
            # Colonnes Focus apparues / disparues, ou retour force : le bouton flottant suit.
            self._sync_floating_gallery_btn()

    def _enforce_hidden_columns_now(self, final: bool = False):
        """Garde tout masque pendant que le bouton « masquer » est actif, y
        compris ce que la navigation vient de (re)construire. Sans colonne
        Focus (donc sans bouton pour revenir) ni objet au centre (double-clic
        pour revenir), tout est reaffiche — decision prise uniquement apres une
        reconstruction COMPLETE des vignettes (`final`), pas pendant l'etat
        transitoire d'une navigation."""
        if not self._project_columns_hidden:
            return
        if self._focus_gallery is not None:
            # Planche ouverte (ex. « Ouvrir la visionneuse à cet endroit » : aucune image en focus, donc aucun
            # objet au centre) : tout reste masqué, c'est la planche qui est le contenu.
            return
        if not self.image_preview_columns and self._focus_overlay is not None:
            # Masque par double-clic sur un apercu, sans colonnes Focus : rien a
            # reconstruire, on garde juste tout masque.
            if not _anim_running(self._columns_fade):
                self._apply_columns_hidden(True)
            return
        if not self.image_preview_columns:
            if final:
                self._project_columns_hidden = False
                self._apply_columns_hidden(False)
                self._clear_focus_overlay()
                self._focus_src = None
            else:
                for widget in self._toggled_widgets():
                    if _shown_or_pending(widget):
                        widget._hidden_by_toggle = True
                        widget.setVisible(False)
            return
        if _anim_running(self._columns_fade):
            return
        self._apply_columns_hidden(True)
        for preview_column in self.image_preview_columns:
            preview_column.set_hide_state(True)

    def _auto_expand_now(self):
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        if self._project_columns_collapsed and (self._chain_terminal_path() is None or not focus_enabled):
            self._apply_project_columns_collapsed(False)

    def _auto_collapse_now(self, animate: bool = True):
        """Repli automatique differe (voir _sync_collapse_state), re-verifie : la
        navigation a pu changer entre-temps."""
        active_config = self._active_project_config
        focus_enabled = True if active_config is None else active_config.get("focus_enabled", True)
        if (self._chain_terminal_path() is not None and focus_enabled and auto_collapse_set_columns()
                and not self._project_columns_collapsed):
            self._apply_project_columns_collapsed(True, animate=animate)

    def _toggle_project_columns(self):
        """Reagit a l'icone unique portee par la colonne des vignettes
        (voir PreviewColumn/update_preview_stack) : bascule les colonnes de
        la chaine (voir _apply_project_columns_collapsed), et desarme le
        repli automatique pour que ce choix manuel ne soit pas aussitot
        ecrase par _sync_collapse_state tant que la chaine reste la meme.
        Toujours disponible, MEME si le repli automatique est desactive
        (voir auto_collapse_set_columns/_sync_collapse_state) : c'est un
        geste manuel independant."""
        self._apply_project_columns_collapsed(not self._project_columns_collapsed)

    def _on_preview_column_resized(self, new_width: int):
        """Relais de PreviewColumn.resize_update (voir _preview_column_
        user_width, sa remarque de tete) : conserve la largeur choisie a la
        main pour qu'elle survive a la PROCHAINE reconstruction des
        colonnes Focus (update_preview_stack, appelee a chaque navigation),
        ET la repercute TOUT DE SUITE sur les AUTRES colonnes Focus (voir
        PreviewColumn.set_width_external) : ce sont des colonnes SEPAREES
        (voir la remarque de l'utilisateur, "deux colonnes separees, une
        en dessous de l'autre") mais elles doivent rester alignees a la
        meme largeur, glisser le bord de L'UNE suffit a redimensionner
        les autres."""
        self._preview_column_user_width = new_width
        for column in self.image_preview_columns:
            if column.width() != new_width:
                column.set_width_external(new_width)
        self._auto_collapse_armed = False

    def _apply_project_columns_collapsed(self, collapsed: bool, animate: bool = True):
        """Replie/deplie EXACTEMENT les N premieres colonnes de self.columns
        (voir _chain_expected_total), N = le nombre d'etapes du projet
        courant — jamais au-dela : une colonne de contenu ouverte depuis le
        groupe IN/OVER/OUT/LOGICIELS (voir _open_group_folder) reste
        TOUJOURS deployee, quoi qu'il arrive aux colonnes de set — voir la
        remarque de l'utilisateur, "attention a bien rabattre toutes
        colonnes ... c'est toutes les colonnes avant les colonnes de
        focus". Le mouvement est joue sur des captures (voir _SlideOverlay) :
        l'etat final est applique tout de suite, sans animer de largeur reelle
        (ce qui recalculait toutes les colonnes a chaque image)."""
        was_collapsed = self._project_columns_collapsed
        self._project_columns_collapsed = collapsed
        self._columns_snapshot = None   # le contenu des colonnes change : capture du fondu perimee
        if self.image_preview_columns:
            self.image_preview_columns[0].set_toggle_state(collapsed)
        self._sync_collapse_button()
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        slide = self._columns_slide
        if _anim_running(slide) and slide.emerge:
            slide.finish_now()   # apparition d'une colonne : on la termine, elle ne se « retourne » pas
            slide = None
        if _anim_running(slide):
            # Clic pendant le mouvement : repart de la position courante.
            slide.retarget(0.0 if collapsed else 1.0, None if collapsed else self._expand_columns_now)
            return
        if (not animate or self._project_columns_hidden or not targets or was_collapsed == collapsed
                or not self.isVisible()):
            self._set_columns_collapsed_now(collapsed)
            return
        viewport = self.scroll.viewport()
        cached = self._slide_snapshot
        valid = (cached is not None and cached[5] == self._columns_epoch and cached[6] == viewport.size()
                 and cached[7] == len(targets))
        if collapsed:
            self._detail_state_width[False] = self.detail.width()   # etat deplie reel, avant repli
            if valid and time.monotonic() - cached[8] < 8.0:
                snapshot = cached[:5]             # amorcee au survol du bouton
            else:
                self.columns_layout.activate()
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
                snapshot = self._grab_set_columns()   # etat deplie actuel
            self._set_columns_collapsed_now(True)
        elif valid:
            snapshot = cached[:5]                 # capture deja prise au repli : aucun cout au depart
        else:
            snapshot = self._grab_expanded_silently()   # etat deplie final, jamais affiche
        if snapshot is not None and self._snapshot_blank(snapshot):
            # Capture vide (colonnes pas encore peintes) : on ne l'anime jamais sur un fond
            # vide. Nouvelle capture, cette fois sans suspendre les mises a jour.
            self._slide_snapshot = None
            snapshot = None if collapsed else self._grab_expanded_silently(suspend=False)
            if snapshot is not None and self._snapshot_blank(snapshot):
                snapshot = None
        if snapshot is None:
            self._set_columns_collapsed_now(collapsed)
            return
        self._slide_snapshot = (*snapshot, self._columns_epoch, viewport.size(), len(targets), time.monotonic())
        left, right, x_expanded, background, limit = snapshot
        self.columns_layout.activate()
        x_collapsed = self._set_columns_anchor_x()
        follow = None
        overlay_ref = []
        if self.detail.isVisible():
            # w_expanded : largeur de l'inspecteur dans la capture (colonnes depliees) ;
            # w_collapsed : sa largeur colonnes repliees (deja appliquee ici).
            widths = self._detail_state_width
            follow = self._detail_follow(
                overlay_ref, self.detail.width(),
                widths.get(False, self.detail.width()), limit)
        overlay = _SlideOverlay(
            viewport, left, right, x_collapsed, x_expanded, background,
            0.0 if collapsed is False else 1.0, 0.0 if collapsed else 1.0, 200,
            None if collapsed else self._expand_columns_now,
            on_done=self._slide_done, limit=limit, on_progress=follow)
        overlay_ref.append(overlay)
        if follow is not None:
            follow(overlay._value)
        overlay.show()
        overlay.raise_()
        self._columns_slide = overlay

    def _slide_done(self):
        self._columns_slide = None
        self._columns_snapshot = None   # etat final change : toute capture du fondu est perimee

    def _prime_slide_snapshot(self):
        """Au survol du bouton de repli : prepare la capture de l'etat deplie."""
        if (self._project_columns_hidden or _anim_running(self._columns_slide)
                or not self.isVisible()):
            return
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        if self._project_columns_collapsed:
            # Replie : il faut deplier un instant (sans rien afficher) pour capturer
            # l'etat deplie. Differe et conditionne a un survol qui dure, pour ne
            # pas figer l'interface quand la souris ne fait que passer.
            QTimer.singleShot(60, self._prime_expanded_snapshot)
            return
        cached = self._slide_snapshot
        size = self.scroll.viewport().size()
        if (not targets or (cached is not None and cached[5] == self._columns_epoch and cached[6] == size
                            and cached[7] == len(targets) and time.monotonic() - cached[8] < 8.0)):
            return
        self.columns_layout.activate()
        snapshot = self._grab_set_columns()
        if snapshot is not None:
            self._slide_snapshot = (*snapshot, self._columns_epoch, size, len(targets), time.monotonic())

    def _prime_expanded_snapshot(self, force: bool = False):
        column = self.image_preview_columns[0] if self.image_preview_columns else None
        if (column is None or not (force or self.btn_collapse.underMouse())
                or not self._project_columns_collapsed or self._project_columns_hidden
                or _anim_running(self._columns_slide)):
            return
        targets = [c for c in self.columns[:self._chain_expected_total()] if c.collapsible]
        size = self.scroll.viewport().size()
        cached = self._slide_snapshot
        if not targets or (cached is not None and cached[5] == self._columns_epoch and cached[6] == size
                           and cached[7] == len(targets) and time.monotonic() - cached[8] < 8.0):
            return
        snapshot = self._grab_expanded_silently()
        if snapshot is not None:
            self._slide_snapshot = (*snapshot, self._columns_epoch, size, len(targets), time.monotonic())

    def _prewarm_snapshots(self):
        """Apres 700 ms sans navigation : prepare les captures des deux boutons, en
        deux temps (chacun court) et seulement si l'utilisateur n'est pas en train
        d'agir (bouton de souris, menu, animation en cours)."""
        if (not self.isVisible() or self._project_columns_hidden or not self.image_preview_columns
                or QApplication.mouseButtons() != Qt.NoButton or QApplication.activePopupWidget() is not None
                or _anim_running(self._columns_slide)
                or _anim_running(self._columns_fade)):
            return
        self._prime_fade_snapshot()
        QTimer.singleShot(40, self._prewarm_slide)

    def _prewarm_slide(self):
        if (not self.isVisible() or self._project_columns_hidden or QApplication.mouseButtons() != Qt.NoButton
                or QApplication.activePopupWidget() is not None):
            return
        if self._project_columns_collapsed:
            self._prime_expanded_snapshot(force=True)
        else:
            self._prime_slide_snapshot()

    def _prime_fade_snapshot(self):
        """Au survol du bouton « masquer » : prepare la capture des colonnes."""
        if (self._project_columns_hidden or not self.image_preview_columns or not self.isVisible()
                or _anim_running(self._columns_fade)
                or _anim_running(self._columns_slide)):
            return
        if self._fade_snapshot_fresh():
            return
        self.columns_layout.activate()
        self._columns_snapshot = (*self._grab_columns(), time.monotonic(), self._project_columns_collapsed)

    @staticmethod
    def _snapshot_blank(snapshot) -> bool:
        """True si la capture des colonnes de set ne contient que la couleur de fond."""
        left, _right, _x, background, _limit = snapshot
        if left.isNull():
            return True
        image = left.toImage().scaled(48, 48, Qt.IgnoreAspectRatio, Qt.FastTransformation)
        bg = background.rgb()
        return all((image.pixel(i, j) & 0xFFFFFF) == (bg & 0xFFFFFF)
                   for i in range(image.width()) for j in range(image.height()))

    def _grab_expanded_silently(self, suspend: bool = True):
        """Capture l'etat DEPLIE alors que les colonnes sont repliees, sans que cet etat
        ne soit jamais affiche : aucun retour a la boucle d'evenements entre le depli
        et le repli (sinon l'ecran se repeint et les colonnes « clignotent »), et les
        mises a jour sont suspendues par precaution."""
        viewport = self.scroll.viewport()
        host = self.columns_host
        if suspend:
            viewport.setUpdatesEnabled(False)
            host.setUpdatesEnabled(False)
        try:
            self._set_columns_collapsed_now(False)
            self.columns_layout.activate()
            snapshot = self._grab_set_columns()
        finally:
            self._set_columns_collapsed_now(True)
            if suspend:
                host.setUpdatesEnabled(True)
                viewport.setUpdatesEnabled(True)
        return snapshot

    def _set_columns_collapsed_now(self, collapsed: bool):
        for column in self.columns[:self._chain_expected_total()]:
            column.set_collapsed(collapsed, animate=False)
        self._fit_detail_now()
        # Largeur de l'inspecteur dans chaque etat, memorisee pour l'animation du depliage.
        self._detail_state_width[collapsed] = self.detail.width()

    def _fit_detail_width(self) -> int:
        """Largeur de l'inspecteur qui evite tout debordement (donc toute barre de
        defilement) avec les colonnes dans leur etat actuel : sa largeur voulue, reduite
        au besoin jusqu'a DETAIL_PANEL_MIN_WIDTH."""
        self.columns_layout.invalidate()   # sizeHint() est mis en cache : largeurs des colonnes qui viennent de changer
        available = self.scroll.viewport().width() - self.columns_layout.sizeHint().width()
        return max(DETAIL_PANEL_MIN_WIDTH, min(self.detail._natural_width, available))

    def _fit_detail_now(self):
        if not self.detail.isVisible() or self.detail._resizing:
            return
        width = self._fit_detail_width()
        if self.detail.width() != width:
            self.detail.setFixedWidth(width)
        self.columns_host.layout().activate()   # replace l'inspecteur (capture, limite)

    def _detail_follow(self, overlay_ref: list, w_collapsed: int, w_expanded: int, limit: int):
        """Callback de progression du depliage : l'inspecteur se redimensionne en meme
        temps que les colonnes qui arrivent contre lui, et la capture (limitee a son bord
        gauche, `limit` quand il vaut `w_expanded`) suit."""
        def follow(p: float):
            width = max(1, int(round(w_collapsed + (w_expanded - w_collapsed) * p)))
            if self.detail.width() != width:
                self.detail.setFixedWidth(width)
            overlay = overlay_ref[0] if overlay_ref else None
            if overlay is not None:
                viewport = self.scroll.viewport()
                overlay.setGeometry(QRect(0, 0, max(1, limit + w_expanded - width), viewport.height()))
        return follow

    def _expand_columns_now(self):
        self._set_columns_collapsed_now(False)

    def _set_columns_anchor_x(self) -> int:
        """Abscisse (dans le viewport) du 1er widget place APRES les colonnes de set ;
        a defaut (rien encore a droite, par exemple pendant une navigation), le
        bord droit des colonnes de set elles-memes."""
        viewport = self.scroll.viewport()
        index = self._chain_expected_total()
        if index < self.columns_layout.count():
            widget = self.columns_layout.itemAt(index).widget()
            if widget is not None and widget.isVisible():
                return max(0, widget.mapTo(viewport, QPoint(0, 0)).x())
        edge = 0
        for column in self.columns[:index]:
            if column.isVisible() and column.width() > 0:
                edge = max(edge, column.mapTo(viewport, QPoint(column.width(), 0)).x())
        return edge + self.columns_layout.spacing() if edge else 0

    def _grab_set_columns(self):
        """(colonnes de set, colonnes a droite JUSQU'A L'INSPECTEUR, abscisse de
        separation, couleur de fond, abscisse de l'inspecteur) dans l'etat actuel ;
        None si rien a animer. L'inspecteur n'est jamais capture : il ne bouge pas."""
        return self._grab_set_columns_at(self._set_columns_anchor_x())

    def _grab_set_columns_at(self, x: int, start: int = 0):
        """`start` : la capture de gauche commence a cet x (apparition d'une colonne : seule la zone qui bouge)."""
        viewport = self.scroll.viewport()
        width, height = viewport.width(), viewport.height()
        limit = width
        if self.detail.isVisible():
            limit = min(width, max(0, self.detail.mapTo(viewport, QPoint(0, 0)).x()))
        if x <= 0 or x > limit or height <= 0:
            return None
        start = max(0, min(int(start), x - 1))
        # Une seule peinture : deux grab voisins repassaient dans les effets
        # graphiques des mêmes cartes. Découper ensuite les pixels déjà peints.
        whole = viewport.grab(QRect(start, 0, limit - start, height))
        dpr = whole.devicePixelRatio() or 1.0
        split = round((x - start) * dpr)
        left = whole.copy(0, 0, split, whole.height())
        right = whole.copy(split, 0, whole.width() - split, whole.height()) if limit > x else QPixmap()
        return left, right, x, QColor(C["window"]), limit

    def on_activated(self, path: Path):
        # Double-clic (ou "Ouvrir") : un dossier s'ouvre dans l'explorateur
        # Windows, un fichier dans son application par defaut. Une note .md d'un coffre Obsidian
        # s'ouvre dans Obsidian, SUR cette note (demande de l'utilisateur) ; a defaut, son logiciel.
        if path.is_dir():
            open_in_file_manager(path)
            return
        if self._video_claims(path) and self._open_video(path):   # module video : video / sequence d'images
            return
        import board
        if board.is_board_file(path):                     # board facon Miro : ouvert DANS l'appli
            if self._open_board(path):
                return
        if board.is_cad_drawing(path) and (ui_state.APPLIED_SETTINGS or {}).get("board_open_cad_drawings", True):
            self._open_cad_drawing(path)                  # dessin DXF / DWG : module MRO (lu en fond)
            return
        if self._md_opens_on_double_click(path):
            if self._open_md_editor(path):                # module Markdown / code : note ou fichier DANS l'appli
                return
        if path.suffix.lower() == ".md":
            import markdown_preview
            url = markdown_preview.obsidian_open_url(path)
            if url is not None:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                if QDesktopServices.openUrl(QUrl(url)):
                    return
        open_path(path)

    def _view_in_viewer(self, path: Path, column=None):
        """Double-clic sur une ligne d'une colonne (image, planche PureRef, fichier qui a un apercu,
        voir column.opens_in_viewer) : la visionneuse de l'appli (colonnes masquees, l'image au centre),
        une fois que le clic l'a montree dans l'inspecteur. L'image part de l'apercu de la LIGNE
        (pas de celui de l'inspecteur) ; le retour aux colonnes la ramene dans l'inspecteur."""
        if self._project_columns_hidden:
            return
        if self._video_claims(path) and self._open_video(path):   # video / sequence EXR, TIFF… : module video
            return

        def go():
            source = column.preview_source(path) if column is not None else None
            if source is not None:
                pixmap, rect = source
                viewport = self.scroll.viewport()
                self._viewer_entry_source = (pixmap, QRect(viewport.mapFromGlobal(rect.topLeft()), rect.size()))
            # La visionneuse s'ouvre sur CE fichier, meme si l'inspecteur ne le montre pas : double-clic sur
            # la ligne DEJA selectionnee = son 1er clic est un re-clic, qui la deselectionne et vide
            # l'inspecteur ; la visionneuse ne trouvait alors aucun fichier et seule la miniature de la
            # ligne arrivait au centre, a sa petite taille (bug signale). Au retour, la colonne et
            # l'inspecteur reprennent l'image montree (_flush_viewer_sync).
            self._viewer_entry_path = (column, Path(path))
            try:
                self._set_columns_hidden(True)
            finally:
                self._viewer_entry_source = None
                self._viewer_entry_path = None
            if not self._project_columns_hidden:
                self.on_activated(path)          # rien a montrer (planche sans apercu...) : son logiciel

        QTimer.singleShot(0, go)

    def _entry_focus_source(self, home):
        """Depart du vol vers la visionneuse quand on vient d'un double-clic sur une ligne : la place de
        l'apercu de la ligne, avec l'image de l'inspecteur (meme fichier, meilleure definition)."""
        entry = getattr(self, "_viewer_entry_source", None)
        if entry is None:
            return home
        pixmap = home[0] if home is not None else entry[0]
        dpr = pixmap.devicePixelRatio() or 1.0
        size = QSize(round(pixmap.width() / dpr), round(pixmap.height() / dpr))
        size.scale(entry[1].size(), Qt.KeepAspectRatio)
        rect = QRect(0, 0, max(1, size.width()), max(1, size.height()))
        rect.moveCenter(entry[1].center())
        return pixmap, rect

    def _send_focus_home(self, overlay, home):
        """Vol depuis une ligne termine (image au centre, rien ne bouge) : le retour aux colonnes la
        ramenera dans l'inspecteur, sa vraie place, pas sur la ligne."""
        if overlay is self._focus_overlay and home is not None and shiboken6.isValid(overlay):
            overlay.set_geometry_target(None, QRectF(home[1]))

    def browse_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Racine du pipeline", self.root_field.text()
        )
        if chosen:
            self.root_field.setText(chosen)
            self.reload()

    # -- Presets (menu deroulant de la barre du haut, fenetre « Gerer les presets ») --

    def _choose_preset(self, name: str):
        """Menu deroulant : `name` devient le preset actif ("" = aucun) ; ses valeurs sont appliquees a
        toute l'appli et enregistrees (pipeline_settings.json)."""
        from settings_store import apply_preset
        settings = apply_preset(name)
        self._apply_settings(settings)
        # Valeurs de punaise propres au preset (browser_core.PIN_LAYOUT_KEYS) : chaque colonne reprend les siennes.
        for column in self.findChildren(Column):
            try:
                column.reload_pin_state()
            except RuntimeError:
                pass
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values(settings)        # ses champs ouverts suivent le preset
        except RuntimeError:
            pass
        self._refresh_preset_ui(settings)

    def _refresh_preset_ui(self, settings: dict | None = None):
        import settings_window_v2
        settings = settings or ui_state.APPLIED_SETTINGS or load_settings()
        settings_window_v2.seed_window_look(settings)
        self.preset_picker.restyle()
        self.preset_picker.refresh(settings)

    def _open_preset_manager(self):
        from settings_presets import PresetManagerWindow
        window = self._preset_manager
        try:
            if window is not None and window.isVisible():
                window.raise_()
                window.activateWindow()
                return
        except RuntimeError:
            pass
        window = self._preset_manager = PresetManagerWindow(ui_state.APPLIED_SETTINGS or load_settings(), parent=self)
        window.presetsChanged.connect(lambda: self.preset_picker.refresh())
        window.destroyed.connect(lambda *_a: setattr(self, "_preset_manager", None))
        window.adjustSize()
        anchor = self.preset_picker.mapToGlobal(QPoint(0, self.preset_picker.height() + 6))
        window.move(anchor)
        window.show()

    def open_settings_v2(self):
        """Ouvre la fenetre de reglages (settings_window_v2.py), gardee en memoire d'une ouverture a l'autre."""
        import settings_window_v2
        existing = getattr(self, "_settings_dialog_v2", None)
        try:
            if existing is not None and existing.isVisible():
                existing.raise_()
                return
        except RuntimeError:
            pass
        # Fenetre gardee en memoire (preparee sur inactivite, voir _start_settings_idle_watch) : on la rouvre telle
        # quelle, remise a jour des reglages changes entre-temps. Fermee en annulant des modifications, ses
        # champs gardent ces valeurs : elle est jetee et refaite.
        try:
            if existing is not None and not existing.isVisible() and not existing.discard_on_reopen():
                existing.reopen()
                return
            if existing is not None:
                existing.deleteLater()
        except RuntimeError:
            pass
        dialog = self._make_settings_v2()
        dialog.show()

    def _make_settings_v2(self):
        """Cree la fenetre de reglages v2 (cachee) et la garde pour toute la session."""
        import settings_window_v2
        # SANS parent (lien « transitoire » de fenetre seulement : elle reste au-dessus de celle-ci) : la feuille de
        # style de la fenetre principale ne se propage pas a ses ~20 000 widgets (voir _apply_global_stylesheet).
        dialog = settings_window_v2.SettingsWindowV2(None)
        dialog.prebuild_hold = self._settings_prebuild_hold
        dialog.prebuild_unattended = self._settings_unattended
        dialog.prebuild_progress = self._on_settings_prebuild_progress
        dialog.create()
        handle, owner = dialog.windowHandle(), self.windowHandle()
        if handle is not None and owner is not None:
            handle.setTransientParent(owner)
        # Sections branchees (settings_window_v2.WIRED_SECTIONS) : apercu en
        # direct et enregistrement passent par les memes rappels que la
        # fenetre reelle.
        dialog.settingsChanged.connect(
            lambda settings, d=dialog: self._apply_settings(settings, getattr(d, "live_changed_keys", None)))
        dialog.settingsSaved.connect(self._apply_settings)
        self._settings_dialog_v2 = dialog
        return dialog

    def _heavy_foreground_work(self) -> bool:
        """Vrai quand l'appli a besoin de toute la boucle d'interface : lecture video en cours. Les preparations
        de fond qui s'executent sur le fil de l'interface (fenetre de reglages) attendent."""
        pane = getattr(self, "_video", None)
        return bool(pane is not None and getattr(pane, "_playing", False))

    # -- Chargement des reglages sur inactivite (demande de l'utilisateur) --
    # Plus rien au lancement : la fenetre de reglages est creee cachee et ses sections construites en fond
    # seulement apres SETTINGS_IDLE_LOAD_S sans aucune action sur l'APPLI (l'activite du reste de l'ordinateur ne
    # compte pas), jamais pendant qu'un module (Markdown, board, visionneuse, video) est ouvert. Le moindre geste
    # sur l'appli l'arrete aussitot (filtre d'application pose seulement pendant le chargement) ; il reprend ou
    # il en etait a la prochaine minute d'inactivite. Avancement : barre « Réglages n % » de la barre de navigation.

    SETTINGS_IDLE_LOAD_S = 60.0
    _INPUT_EVENTS = frozenset((QEvent.MouseMove, QEvent.MouseButtonPress, QEvent.MouseButtonDblClick,
                               QEvent.Wheel, QEvent.KeyPress, QEvent.NonClientAreaMouseMove,
                               QEvent.NonClientAreaMouseButtonPress, QEvent.TouchBegin, QEvent.TabletPress))

    def _start_settings_idle_watch(self):
        """Releve de l'activite de l'appli, une fois par seconde (aucun filtre d'evenements permanent)."""
        if not settings_window_v2_preload_enabled() or getattr(self, "_settings_idle_timer", None) is not None:
            return
        self._settings_idle_loading = False
        self._app_input_at = time.monotonic()
        from automatic_tasks import AutomaticTasks
        self._automatic_tasks = AutomaticTasks(self)
        self.titlebar.set_load_progress(0)
        self.titlebar.set_load_progress(None)
        timer = self._settings_idle_timer = QTimer(self)
        timer.setInterval(1000)
        timer.timeout.connect(self._settings_idle_tick)
        timer.start()

    def _module_open(self) -> bool:
        """Un module occupe l'appli : Markdown / code, board, visionneuse (ou planche), video."""
        return bool(getattr(self, "_md_open", False) or getattr(self, "_board", None) is not None
                    or getattr(self, "_video", None) is not None or getattr(self, "_project_columns_hidden", False))

    def _app_used_recently(self) -> bool:
        """Entree clavier / souris recente ET destinee a l'appli (fenetre active, ou curseur sur l'une de ses
        fenetres) : l'horloge d'entree de Windows seule compterait tout l'ordinateur."""
        import settings_window_v2
        if QApplication.mouseButtons() != Qt.NoButton and QApplication.activeWindow() is not None:
            return True
        idle = settings_window_v2._system_idle_ms()
        cursor = QCursor.pos()
        if idle is None:                                   # hors Windows : mouvement du curseur sur l'appli
            last, self._idle_cursor = getattr(self, "_idle_cursor", None), cursor
            return last is not None and last != cursor and QApplication.widgetAt(cursor) is not None
        if idle > 1500:
            return False
        return QApplication.activeWindow() is not None or QApplication.widgetAt(cursor) is not None

    def _live_settings_dialog(self):
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None:
                dialog.isVisible()
            return dialog
        except RuntimeError:
            self._settings_dialog_v2 = None                # detruite
            return None

    def _settings_idle_tick(self):
        automatic = getattr(self, "_automatic_tasks", None)
        if automatic is not None:
            automatic.tick()
            return
        now = time.monotonic()
        dialog = self._live_settings_dialog()
        if self._settings_idle_loading:
            if self._module_open() or self._heavy_foreground_work() or (dialog is not None and dialog.isVisible()):
                self._stop_settings_idle_load()
            return
        if self._module_open() or self._heavy_foreground_work() or self._app_used_recently():
            self._app_input_at = now                       # module ouvert : la minute ne compte qu'apres sa fermeture
            return
        if dialog is not None and (dialog.isVisible()
                                   or (dialog.prebuild_finished() and not dialog.discard_on_reopen())):
            return                                         # ouverte (elle se construit seule) ou deja prete
        if now - self._app_input_at >= self.SETTINGS_IDLE_LOAD_S:
            self._begin_settings_idle_load()

    def _begin_settings_idle_load(self):
        dialog = self._live_settings_dialog()
        if dialog is not None and dialog.discard_on_reopen():
            dialog.deleteLater()                           # fermee en annulant : ses champs ne servent plus
            dialog = self._settings_dialog_v2 = None
        self._settings_idle_loading = True
        self._background_status.report('settings', 'Chargement des réglages en mémoire')
        watch = getattr(self, "_idle_input_watch", None)
        if watch is None:
            watch = self._idle_input_watch = _AppInputWatch(self._INPUT_EVENTS, self._stop_settings_idle_load)
        QApplication.instance().installEventFilter(watch)
        if dialog is None:
            dialog = self._make_settings_v2()
        self.titlebar.set_load_progress(int(dialog.prebuild_fraction() * 100))
        dialog.start_background_build()

    def _stop_settings_idle_load(self):
        """L'utilisateur revient (ou un module s'ouvre) : chargement suspendu, barre retiree, minute recomptee."""
        self._app_input_at = time.monotonic()
        if not getattr(self, "_settings_idle_loading", False):
            return
        self._settings_idle_loading = False
        self._background_status.finish('settings', 'Chargement des réglages terminé ou suspendu')
        watch = getattr(self, "_idle_input_watch", None)
        if watch is not None:
            QApplication.instance().removeEventFilter(watch)
        self.titlebar.set_load_progress(None)

    def _settings_unattended(self) -> bool:
        """Chargement sur inactivite en cours, fenetre de reglages cachee."""
        dialog = self._live_settings_dialog()
        return bool(getattr(self, "_settings_idle_loading", False) and dialog is not None
                    and not dialog.isVisible())

    def _settings_prebuild_hold(self) -> bool:
        """Preparation suspendue : lecture video, ou fenetre cachee hors du chargement sur inactivite (fenetre
        ouverte par l'utilisateur : elle se prepare comme avant)."""
        automatic = getattr(self, "_automatic_tasks", None)
        if automatic is not None and getattr(self, "_settings_idle_loading", False):
            import ui_state
            if not automatic.eligible('settings', ui_state.APPLIED_SETTINGS or {}):
                self._stop_settings_idle_load()
                return True
        if self._heavy_foreground_work():
            return True
        dialog = self._live_settings_dialog()
        visible = dialog is not None and dialog.isVisible()
        return not visible and not getattr(self, "_settings_idle_loading", False)

    def _on_settings_prebuild_progress(self, fraction: float):
        self.titlebar.set_load_progress(int(fraction * 100))
        if not getattr(self, "_settings_idle_loading", False):
            self.titlebar.set_load_progress(None)
            return
        if fraction >= 1.0:
            self._stop_settings_idle_load()                # tout est pret : la barre disparait
            return
        self.titlebar.set_load_progress(int(fraction * 100))

    def open_settings(self, mode: str = "visuel"):
        """Ouvre la fenetre de reglages (v2 ; l'ancienne fenetre v1 a ete retiree)."""
        self.open_settings_v2()

    def _apply_settings(self, settings: dict, changed_keys: set | None = None):
        """Applique des reglages (live, pendant qu'on les ajuste dans la
        fenetre de parametres, ou definitifs a l'enregistrement — les deux
        cas appellent cette meme methode). N'ecrit jamais sur le disque
        (voir SettingsWindow._on_save pour la persistance).

        Si la racine n'a pas change, les colonnes existantes sont juste
        rafraichies sur place (refresh_all_columns) : la navigation en cours
        (profondeur, selection) n'est PAS perdue. Un reload() complet n'a
        lieu que si la racine elle-meme a change, ce qui invalide de toute
        facon le chemin courant."""
        # Cliche AVANT/APRES (voir refresh_all_columns(relayout_titles=...))
        # de la hauteur/l'espacement de ligne EFFECTIFS (COLUMN_SETTINGS,
        # deja resolus general/surcharge par apply_all_settings) de CHAQUE
        # colonne : seules celles ou cette paire a reellement change auront
        # besoin d'un doItemsLayout() plus bas — un cran de slider qui ne
        # touche qu'une couleur/bordure/rayon/padding n'affecte le sizeHint()
        # d'AUCUNE ligne, quelle que soit la colonne — voir la remarque de
        # l'utilisateur, "il y a des ralentissements dans les animations,
        # optimise un maximum".
        if changed_keys and all(k.startswith("auto_") for k in changed_keys):
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed_keys})
            automatic = getattr(self, "_automatic_tasks", None)
            if automatic is not None:
                automatic.tick()
            return
        if self._last_style_key is None:
            # Premier changement : la reference est l'etat DEJA applique (sans
            # elle, le tout premier cran de n'importe quel slider declenchait
            # une reconstruction globale de plus d'une seconde).
            self._last_style_key = self._style_key(load_settings())
        # Chemin RAPIDE (glisser une couleur / un rayon dans Bouton, Zone de saisie, Tabs : un apercu toutes les
        # ~30 ms) : si seules des cles de ces trois groupes ont change depuis ce qui est applique, rien d'autre ne
        # bouge (ni colonnes, ni couleurs de l'appli, ni tailles) — pas de rafraichissement de toutes les colonnes.
        previous = ui_state.APPLIED_SETTINGS or {}
        # `changed_keys` (apercu en direct de la v2) : les cles que le geste a vraiment changees.
        changed = set(changed_keys) if changed_keys else (
            {k for k, v in settings.items() if previous.get(k) != v} | (previous.keys() - settings.keys()))
        md_changed = {k for k in changed if k.startswith("md_")}
        if md_changed:
            # Feuille CSS partagee avec Obsidian : apercu aussitot, ecriture regroupee apres le geste (css_sync).
            import mdeditor.css_sync as css_sync
            css_sync.engine().update(settings, md_changed)
        if changed and all(k.startswith("md_") for k in changed):
            # Onglet Markdown : seule la page du module (si elle existe) les reprend, sans rechargement ; l'apercu
            # des notes de l'inspecteur suit a la prochaine note affichee.
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed})
            if changed.intersection({"md_toolbar_enabled", "md_toolbar_margin", "md_toolbar_border_enabled",
                                    "md_toolbar_border", "md_toolbar_border_thickness"}):
                self.titlebar.refresh_look()
            if "md_module_padding" in changed:
                self.md_margin_slider.blockSignals(True)
                self.md_margin_slider.setValue(int(settings.get("md_module_padding") or 0))
                self.md_margin_slider.blockSignals(False)
            import mdeditor.pane as md_pane
            pane = md_pane.instance(create=False)
            if pane is not None:
                pane.apply_settings(ui_state.APPLIED_SETTINGS or settings, changed)
            timer = getattr(self, "_md_inspector_timer", None)
            if timer is None:                    # apercu de l'inspecteur : une fois, apres le geste
                timer = self._md_inspector_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(350)
                timer.timeout.connect(self.detail.refresh_markdown_style)
            timer.start()
            return
        if changed and all(k.startswith("video_") for k in changed):
            # Reglages > Module video : seul le module ouvert est refait.
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed})
            if getattr(self, "_video", None) is not None:
                self._video.apply_settings(ui_state.APPLIED_SETTINGS or settings)
            return
        if changed and all(k.startswith("board_") for k in changed):
            # Reglages > Module MRO (magnetisme du board) : rien d'autre a refaire que le board ouvert.
            if isinstance(ui_state.APPLIED_SETTINGS, dict):
                ui_state.APPLIED_SETTINGS.update({k: settings.get(k) for k in changed})
            if getattr(self, "_board", None) is not None:
                self._board.apply_settings(ui_state.APPLIED_SETTINGS or settings)
            return
        if getattr(self, "_board", None) is not None:
            self._board.apply_settings(settings)
        if getattr(self, "_video", None) is not None:
            self._video.apply_settings(settings)
        if changed and all(k.startswith(("button_", "input_", "tabs_", "crumb_")) for k in changed):
            apply_all_settings(settings)
            style_key = self._style_key(settings)
            if style_key != self._last_style_key:
                self._last_style_key = style_key
                self._pending_stylesheet_rebuild = True
                self._stylesheet_rebuild_timer.start()
            self._refresh_button_shadows()
            if "input_height" in changed:
                self.refresh_chrome_sizes()               # champs de la barre de navigation
            if any(k.startswith("crumb_") for k in changed):
                self.titlebar.refresh_crumbs()            # cheminement : habillage et hauteur de la barre
            return
        prev_geometry = {title: (conf["height"], conf["spacing"]) for title, conf in COLUMN_SETTINGS.items()}
        prev_omissions = (GLOBAL_OMIT_DIR_NAMES.copy(), GLOBAL_OMIT_FILE_NAMES.copy(),
                          GLOBAL_OMIT_FILE_EXTENSIONS.copy())
        apply_all_settings(settings)
        picker = getattr(self, "preset_picker", None)
        if picker is not None:
            picker.restyle()                        # habillage des reglages (palette M) : suit
        omissions_changed = prev_omissions != (GLOBAL_OMIT_DIR_NAMES, GLOBAL_OMIT_FILE_NAMES,
                                                GLOBAL_OMIT_FILE_EXTENSIONS)
        changed_titles = {
            title for title, conf in COLUMN_SETTINGS.items()
            if (conf["height"], conf["spacing"]) != prev_geometry.get(title)
        }
        # column_gap() : apply_all_settings vient de le mettre a jour (voir
        # set_column_gap ci-dessus), mais c'est un global — encore besoin
        # de le repercuter ICI sur l'instance reelle de columns_layout,
        # comme refresh_all_columns le fait deja pour la largeur/hauteur
        # des colonnes.
        self.columns_layout.setSpacing(scaled(max(0, column_gap()), 0))
        if settings["root_path"] != self.root_field.text():
            self.root_field.setText(settings["root_path"])
            self.reload()
        else:
            self.refresh_all_columns(
                rescan=omissions_changed,
                relayout_titles=None if omissions_changed else changed_titles,
            )
        if omissions_changed:
            hidden_path = self.detail._current_path
            if hidden_path and _is_globally_omitted_path(Path(hidden_path)):
                self.detail.clear()
            idle_scheduler = getattr(self, "_idle_preview_scheduler", None)
            if idle_scheduler is not None:
                if idle_scheduler.scan_cancel_event is not None:
                    idle_scheduler.scan_cancel_event.set()
                idle_scheduler.queue.clear()
                idle_scheduler.done.clear()
                if (idle_scheduler.active_key is not None and idle_scheduler.cancel_event is not None):
                    if _is_globally_omitted_path(Path(idle_scheduler.active_key)):
                        idle_scheduler.cancel_event.set()
                idle_scheduler.last_scan = 0.0
        # app.setStyleSheet (dans refresh_colors -> refresh_style) repolit
        # TOUS les widgets de TOUTES les fenetres de l'appli — le poste le
        # plus cher, et de loin, de tout ce rafraichissement (mesure a
        # plus de 3 SECONDES par appel une fois la fenetre de parametres
        # ouverte, voir _flush_stylesheet_rebuild). Un slider qui ne
        # touche ni aux couleurs, ni au cadre/rayon des boutons, ni au
        # cadre/rayon des zones de saisie, ni au rayon des tableaux (largeur
        # de colonne, echelle, hauteur d'entete...) n'a aucune raison de le
        # declencher a chaque cran : seule une vraie difference sur ces
        # points (les seuls que build_stylesheet lit reellement) force la
        # reconstruction complete de la feuille de style — MAIS durant un
        # glisser de COULEUR, cette difference est reelle a CHAQUE tick, ce
        # gate seul ne suffit donc plus (voir la remarque de l'utilisateur,
        # "il y a toujours un tres gros problemes de performance") : la
        # reconstruction elle-meme est donc REGROUPEE (voir
        # _flush_stylesheet_rebuild), jamais appelee directement ici.
        style_key = self._style_key(settings)
        if style_key != self._last_style_key:
            self._last_style_key = style_key
            self._pending_stylesheet_rebuild = True
            # Relance a chaque changement (et non plus toutes les 250 ms) : la reconstruction coute ~430 ms
            # (toutes les fenetres repolies) ; faite PENDANT un glisser de couleur, elle le figeait (signale).
            self._stylesheet_rebuild_timer.start()
        self.refresh_colors(rebuild_stylesheet=False)
        self.refresh_chrome_sizes()
        self._apply_native_frame()
        self._apply_viewer_settings()
        import settings_element_style            # styles propres des elements : pas effaces par le restylage
        settings_element_style.reapply_soon(self, ui_state.APPLIED_SETTINGS)

    @staticmethod
    def _style_key(settings: dict) -> tuple:
        """Ce que build_stylesheet lit reellement : si elle ne bouge pas, la
        feuille de style globale n'a pas a etre reconstruite."""
        colors = settings.get("colors") or {}
        return (
            tuple(colors.get(k, C[k]) for k in STYLESHEET_COLOR_KEYS),
            settings.get("button_radius"),
            settings.get("button_frame"),
            settings.get("input_radius"),
            settings.get("input_frame"),
            settings.get("table_radius"),
            json.dumps({k: v for k, v in settings.items()
                        if k.startswith(("button_", "input_"))}, sort_keys=True, default=str),
        )

    def _flush_stylesheet_rebuild(self):
        """Reconstruction DIFFEREE et REGROUPEE de la feuille de style
        globale (voir _apply_settings/app_style.refresh_style) — le SEUL
        appel a ce chemin couteux (mesure a plus de 3 SECONDES une fois la
        fenetre de parametres ouverte, des milliers de widgets ayant
        chacun leur propre QSS local a re-cascader contre le nouveau QSS
        d'appli). `_stylesheet_rebuild_timer` (250ms, singleShot, voir
        __init__) le declenche au plus tot 250ms apres le DERNIER
        changement de style_key — pendant un glisser continu de couleur,
        cela ramene un cout de plusieurs secondes PAR TICK (~30ms) a un
        seul appel toutes les ~250ms, invisible a l'oeil (le style
        GENERIQUE — boutons/scrollbars/menus — n'est de toute facon pas ce
        qu'on regarde en glissant une pastille de couleur ; tout le reste
        du retour visuel en direct passe par refresh_colors(rebuild_
        stylesheet=False), deja rejoue a chaque tick, DEJA rapide)."""
        if not self._pending_stylesheet_rebuild:
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            # Geste en cours (curseur de couleur tenu) : on attend qu'il soit relache.
            self._stylesheet_rebuild_timer.start()
            return
        self._pending_stylesheet_rebuild = False
        self._apply_global_stylesheet()

    @staticmethod
    def _nav_input_height() -> int:
        """Hauteur des champs de la barre de navigation : Reglages > Zone de saisie > Hauteur (0 = 20 px), sans
        depasser la rangee des boutons."""
        from settings_store import input_height
        return min(scaled(TITLEBAR_HEIGHT), scaled(input_height() or 20))

    def _sync_collapse_button(self):
        """Icone / infobulle / disponibilite du bouton de repli des colonnes de la barre : replie ou deplie
        selon l'etat, grise quand les colonnes sont masquees (visionneuse)."""
        button = getattr(self, "btn_collapse", None)
        if button is None:
            return
        collapsed = bool(getattr(self, "_project_columns_collapsed", False))
        button.set_kind("dchevron_left" if collapsed else "dchevron_right")
        button.setToolTip("Deplier les colonnes de set" if collapsed else "Replier les colonnes de set")
        usable = (not getattr(self, "_project_columns_hidden", False) and not getattr(self, "_md_open", False)
                  and getattr(self, "_board", None) is None)
        self._set_button_usable(button, usable)
        self._sync_mode_buttons()

    @staticmethod
    def _set_button_usable(button, usable: bool):
        if button.isEnabled() == usable and (button.graphicsEffect() is None) == usable:
            return
        button.setEnabled(usable)
        button.setGraphicsEffect(None)
        if not usable:
            effect = QGraphicsOpacityEffect(button)
            effect.setOpacity(0.35)
            button.setGraphicsEffect(effect)

    def _selected_path(self) -> tuple:
        """(colonne, chemin) du choix le plus profond des colonnes, ou (None, None)."""
        for column in reversed(getattr(self, "columns", [])):
            try:
                path = column.current_path()
            except RuntimeError:
                continue
            if path is not None:
                return column, Path(path)
        return None, None

    def _sync_mode_buttons(self):
        """Boutons visionneuse / editeur de texte de la barre : l'editeur n'est disponible que sur un fichier
        texte selectionne (ou deja ouvert, pour en sortir) ; la visionneuse sur une selection (ou ouverte)."""
        if not hasattr(self, "btn_text_editor"):
            return
        import mdeditor
        editing = getattr(self, "_md_open", False)
        _column, path = self._selected_path()
        viewer_open = getattr(self, "_project_columns_hidden", False)
        # Type repris de la lecture du dossier (un `is_file()` par bouton = 3 allers-retours par clic en reseau).
        is_file = path is not None and not entry_is_dir(path)
        self._set_button_usable(self.btn_text_editor,
                                editing or (not viewer_open and is_file and mdeditor.is_text_file(path)))
        self._set_button_usable(self.btn_viewer, viewer_open or editing or path is not None)
        self.btn_text_editor.set_alert(self._mode_on_color() if editing else None)
        self.btn_viewer.set_alert(self._mode_on_color() if viewer_open else None)
        import board
        on_board = self._board is not None
        self._set_button_usable(self.btn_board, on_board or (not viewer_open and is_file and (
            board.is_board_file(path) or board.is_cad_drawing(path))))
        self.btn_board.set_alert(self._mode_on_color() if on_board else None)
        import fm_video as video
        on_video = getattr(self, "_video", None) is not None
        self._set_button_usable(self.btn_video, on_video or (not viewer_open and is_file
                                                             and video.is_media_file(path)))
        self.btn_video.set_alert(self._mode_on_color() if on_video else None)

    @staticmethod
    def _mode_on_color() -> str:
        color = QColor(C["accent"])
        color.setAlpha(90)
        return color.name(QColor.HexArgb)

    # -- Bouton « visionneuse » de la barre --

    def _on_viewer_button(self):
        """Visionneuse ouverte : retour aux colonnes. Sinon elle s'ouvre sur la selection : un fichier a apercu
        tel quel, un dossier (sa premiere photo), un autre fichier (les photos de son dossier)."""
        if self._project_columns_hidden:
            self._toggle_project_columns_hidden()
            return
        if not self._close_md_editor():
            return
        if self._board is not None and not self._close_board():
            return
        self._close_video()
        from column import opens_in_viewer
        column, path = self._selected_path()
        if path is None:
            return
        if path.is_dir():
            self._view_folder_in_viewer(path, column)
        elif opens_in_viewer(path):
            self._view_in_viewer(path, column)
        else:
            self._view_folder_in_viewer(path.parent, column)

    # -- Module Markdown / code (paquet mdeditor/) --

    def _set_md_margin(self, value):
        settings = ui_state.APPLIED_SETTINGS if isinstance(ui_state.APPLIED_SETTINGS, dict) else {}
        settings["md_module_padding"] = value
        import mdeditor.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is not None:
            pane._apply_module_padding(settings)
        self._md_margin_timer.start()

    def _persist_md_margin(self):
        value = self.md_margin_slider.value()
        save_live_state("md_module_padding", value)
        import browser_core
        browser_core._sync_default_preset_override(ui_state.APPLIED_SETTINGS or {},
                                                   lambda preset: preset.update(md_module_padding=value))
        dialog = getattr(self, "_settings_dialog_v2", None)
        try:
            if dialog is not None and dialog.isVisible():
                dialog.external_values({"md_module_padding": value})
        except RuntimeError:
            pass

    def _md_pane(self):
        """Le module (instance unique, prechargee) : branche une fois sur la barre et les reglages."""
        import mdeditor.pane as md_pane
        import mdeditor.style as md_style
        from browser_core import _resolve_font_family
        md_style.FONT_RESOLVER = _resolve_font_family
        md_pane.HOOKS["settings"] = lambda: ui_state.APPLIED_SETTINGS or {}
        md_pane.HOOKS["save_state"] = self._save_md_state
        import mdeditor.css_sync as css_sync                 # module ouvert avant le demarrage de la synchro
        css_sync.HOOKS["external"] = self._apply_md_external
        pane = md_pane.instance(create=True)
        if not getattr(pane, "_pb_connected", False):
            pane._pb_connected = True
            pane.stateChanged.connect(self._layout_md_buttons)
            pane.pathChanged.connect(lambda path: self.path_label.setText(path))
            pane.closeRequested.connect(self._close_md_editor)
        return pane

    def _save_md_state(self, key: str, value):
        """Etat temps reel du module (dernier mode, taille du texte des fichiers de code) : fichier de reglages."""
        from settings_store import save_live_state
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        save_live_state(key, value)

    def _start_css_sync(self):
        """Feuille CSS partagee avec Obsidian (Reglages > Markdown > CSS) : lue une fois au demarrage — ses valeurs
        (peut-etre modifiees dans Obsidian pendant que l'appli etait fermee) sont reprises dans les reglages —, puis
        suivie sur le disque (mdeditor/css_sync.py)."""
        import mdeditor.css_sync as css_sync
        import mdeditor.style as md_style
        from browser_core import _resolve_font_family
        md_style.FONT_RESOLVER = _resolve_font_family         # polices « de l'appli » comparees sous leur vrai nom
        css_sync.HOOKS["external"] = self._apply_md_external
        css_sync.engine().update(ui_state.APPLIED_SETTINGS or load_settings())

    def _apply_md_external(self, values: dict):
        """Reglages Markdown repris de la feuille partagee (modifiee dans Obsidian ou un editeur) : appliques au
        module et a l'inspecteur, enregistres (fichier + preset actif), montres par la fenetre de reglages ouverte
        — sinon une valeur perimee y resterait et ecraserait la modification a l'enregistrement suivant."""
        if not values:
            return
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS.update(values)
        settings = load_settings()
        settings.update(values)
        save_settings(settings)
        import browser_core
        browser_core._sync_default_preset_override(settings, lambda preset: preset.update(values))
        dialog = getattr(self, "_settings_dialog_v2", None)
        if dialog is not None:
            try:
                dialog.external_values(values)
            except RuntimeError:
                pass
        import mdeditor.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is not None:
            pane.apply_settings(ui_state.APPLIED_SETTINGS or settings, set(values))
        timer = getattr(self, "_md_inspector_timer", None)
        if timer is not None:
            timer.start()
        else:
            self.detail.refresh_markdown_style()

    def _preload_md_editor(self):
        """Module prepare en fond (page, CodeMirror et feuille charges) : l'ouvrir est ensuite immediat."""
        if not (ui_state.APPLIED_SETTINGS or {}).get("md_preload", True):
            return
        if QApplication.mouseButtons() != Qt.NoButton or self._heavy_foreground_work():
            QTimer.singleShot(1500, self._preload_md_editor)       # souris enfoncee / lecture video : plus tard
            return
        try:
            self._md_pane()
        except ImportError:
            pass

    def _md_opens_on_double_click(self, path: Path) -> bool:
        """Double-clic : extensions de Markdown > Ouverture ; une note .md va a l'application Obsidian si le
        reglage le demande."""
        import mdeditor.pane as md_pane
        settings = ui_state.APPLIED_SETTINGS or {}
        if path.suffix.lower() == ".md" and settings.get("md_open_md") == "obsidian":
            return False
        return md_pane.opens_on_double_click(path, settings)

    def _toggle_md_editor(self):
        if getattr(self, "_md_open", False):
            self._close_md_editor()
            return
        import mdeditor
        _column, path = self._selected_path()
        if path is not None and path.is_file() and mdeditor.is_text_file(path):
            self._open_md_editor(path)

    def _open_md_editor(self, path: Path) -> bool:
        """Le fichier recouvre les colonnes ; ses boutons dans le cadre « Éditeur » de la barre de navigation."""
        if self._project_columns_hidden:
            return False
        if self._board is not None and not self._close_board():
            return False
        self._close_video()
        try:
            pane = self._md_pane()
        except ImportError:
            return False
        reason = pane.can_open(Path(path))
        if reason is not None:
            self.path_label.setText(reason)
            return False
        pane.attach(self.scroll.viewport())
        pane.open(Path(path))
        if not getattr(self, "_md_open", False):
            self._md_open = True
            self.status_right.hide()
            self.md_margin_slider.show()
            self.titlebar.refresh_look()
            pane.fade_in()
        else:
            pane.raise_()
        self._layout_md_buttons()
        self._sync_collapse_button()
        self.path_label.setText(str(path))
        return True

    def _close_md_editor(self) -> bool:
        """Retour aux colonnes (tout est enregistre ; un conflit demande a l'utilisateur). False = annule. La page
        reste chargee (cachee) : la rouvrir est immediat."""
        if not getattr(self, "_md_open", False):
            return True
        import mdeditor.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is not None and not pane.confirm_leave():
            return False
        self._md_open = False
        self.md_margin_slider.hide()
        self.status_right.show()
        self.titlebar.refresh_look()
        self.titlebar.editor_group().hide()
        if pane is not None:
            pane.fade_out()
        self._sync_collapse_button()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()
        return True

    def _layout_md_buttons(self):
        """Cadre « Éditeur » de la barre : precedent, suivant, lecture / edition, rechercher, enregistrer, ouvrir dans
        l'application Obsidian (note d'un coffre), fermer."""
        group = self.titlebar.editor_group()
        if not getattr(self, "_md_open", False):
            group.hide()
            return
        import mdeditor.pane as md_pane
        pane = md_pane.instance(create=False)
        if pane is None:
            group.hide()
            return
        self.titlebar.refresh_look()       # le trait partagé suit le mode lecture/édition et le type de fichier
        if not self._editor_buttons:
            current = lambda: md_pane.instance(create=False)          # noqa: E731
            for kind, tip, slot in (
                    ("nav_back", "Précédent (Alt+←)", lambda: current() and current().go(-1)),
                    ("nav_forward", "Suivant (Alt+→)", lambda: current() and current().go(1)),
                    ("reading", "Lecture / édition (Ctrl+E)", lambda: current() and current().toggle_mode()),
                    ("find", "Rechercher (Ctrl+F)", lambda: current() and current().find()),
                    ("save", "Enregistrer (Ctrl+S)", lambda: current() and current().flush()),
                    ("external", "Ouvrir dans l'application Obsidian",
                     lambda: current() and current().open_in_obsidian()),
                    ("close", "Fermer l'éditeur (Échap)", self._close_md_editor)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                button.clicked.connect(slot)
                button._editor_kind = kind
                self._editor_buttons.append(button)
        import markdown_preview
        on = self._mode_on_color()
        if pane.path != getattr(self, "_md_vault_path", None):        # une fois par fichier (lecture du disque)
            self._md_vault_path = pane.path
            self._md_in_vault = pane.path is not None and pane.kind == "markdown" and \
                markdown_preview.vault_containing(pane.path) is not None
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in self._editor_buttons:
            kind = button._editor_kind
            visible = not (kind == "external" and not self._md_in_vault) and \
                not (kind == "reading" and pane.kind != "markdown")
            button.setVisible(visible)
            if not visible:
                continue
            style_focus_button(button)
            if kind == "nav_back":
                self._set_button_usable(button, pane.can_back)
            elif kind == "nav_forward":
                self._set_button_usable(button, pane.can_forward)
            elif kind == "reading":
                button.set_alert(on if pane.mode == "reading" else None)
            elif kind == "save":
                button.set_alert(resolve_color_ref("#c62828") if pane.is_dirty() else None)
            button.move(x, origin.y())
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()

    # -- Module video (paquet fm_video/) --

    def _preload_video(self):
        """Bibliotheques lourdes du module video (PyOpenGL ~1,2 s, PyAV, OpenImageIO, OpenColorIO + configuration
        ACES integree) importees dans un fil de fond : la 1re ouverture du module ne les attend plus."""
        import threading
        import fm_video as video
        threading.Thread(target=video.preload, name="video-preload", daemon=True).start()

    def _video_claims(self, path) -> bool:
        """Le double-clic va-t-il au module video ? Videos (reglage « Double-clic sur une video ») ; images EXR /
        TIFF / DPX numerotees d'une sequence (reglage « … sa sequence »)."""
        import fm_video as video
        settings = ui_state.APPLIED_SETTINGS or {}
        path = Path(path)
        if not path.is_file():
            return False
        if video.is_video_file(path):
            return bool(settings.get("video_open_videos", True))
        if path.suffix.lower() in video.PRO_IMAGE_EXTENSIONS and settings.get("video_open_sequences", True):
            from fm_video.media import find_sequence
            return find_sequence(path) is not None
        return False

    def _install_video_hooks(self):
        import fm_video.pane as video_pane
        from app_style import resolve_color_ref
        from browser_core import _resolve_font_family
        video_pane.HOOKS.update({
            "settings": lambda: ui_state.APPLIED_SETTINGS or load_settings(),
            "save_state": self._save_video_state,
            "write_setting": self._write_video_setting,
            "resolve_color": resolve_color_ref,
            "resolve_font": lambda family: _resolve_font_family(family, 12),
            "status": self.path_label.setText,
        })

    def _write_video_setting(self, key: str, value):
        """Valeur vidéo choisie dans le module : fichier, preset et réglages ouverts."""
        settings = load_settings()
        settings[key] = value
        save_settings(settings)
        import browser_core
        browser_core._sync_default_preset_override(settings, lambda preset: preset.__setitem__(key, value))
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        dialog = getattr(self, '_settings_dialog_v2', None)
        if dialog is not None:
            try:
                dialog.external_values({key: value})
            except RuntimeError:
                pass

    def _save_video_state(self, key: str, value):
        """Etat temps reel du module (corrections, presets, derniers parametres d'export, I, boucle, volume) :
        enregistre aussitot, et suivi par les reglages appliques."""
        from settings_store import save_live_state
        if isinstance(ui_state.APPLIED_SETTINGS, dict):
            ui_state.APPLIED_SETTINGS[key] = value
        save_live_state(key, value)

    def _toggle_video(self):
        if self._video is not None:
            self._close_video()
            return
        import fm_video as video
        _column, path = self._selected_path()
        if path is not None and path.is_file() and video.is_media_file(path):
            self._open_video(path)

    def _open_video(self, path: Path) -> bool:
        """Le module video recouvre les colonnes ; ses boutons dans le cadre « Vidéo » de la barre de navigation.
        Modes exclusifs (editeur, board, visionneuse)."""
        if self._project_columns_hidden:
            return False
        if not self._close_md_editor():
            return False
        if self._board is not None and not self._close_board():
            return False
        self._install_video_hooks()
        if self._video is None:
            from fm_video.pane import VideoPane
            pane = VideoPane(self.scroll.viewport(), ui_state.APPLIED_SETTINGS or {})
            pane.closeRequested.connect(self._close_video)
            pane.stateChanged.connect(self._layout_video_buttons)
            self._video = pane
        pane = self._video
        if not pane.open(path):
            if pane.source is None:
                pane.shutdown()
                pane.deleteLater()
                self._video = None
            return False
        pane.fade_in()
        # Colonnes VRAIMENT masquees sous le module : sinon Qt les repeignait a chaque image de la lecture
        # (composition OpenGL : ~20 ms par image, lecture 1080p saccadee). Remontrees a la fermeture.
        host = self.scroll.widget()
        if host is not None and host.isVisible():
            host.hide()
            self._video_hid_columns = True
        self._layout_video_buttons()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        self.path_label.setText(str(path))
        return True

    def _close_video(self):
        """Retour aux colonnes : lecture et fils de fond arretes, memoire du cache rendue."""
        pane = self._video
        if pane is None:
            return
        self._video = None
        self.titlebar.video_group().hide()
        if getattr(self, "_video_hid_columns", False):
            self._video_hid_columns = False
            host = self.scroll.widget()
            if host is not None:
                host.show()
        pane.shutdown()
        pane.hide()
        pane.deleteLater()
        self._sync_collapse_button()
        self._sync_mode_buttons()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()

    def _video_menu(self, button):
        """Bouton « Corrections » : fenetres de corrections, presets de corrections, reinitialiser."""
        from settings_menu import Menu
        pane = self._video
        if pane is None:
            return
        menu = Menu(self)
        menu.addAction("Corrections colorimétriques et LUT…").triggered.connect(
            lambda: pane.open_grade_window("grade_main"))
        menu.addAction("Corrections par canal et niveaux…").triggered.connect(
            lambda: pane.open_grade_window("grade_channels"))
        menu.addSeparator()
        presets = pane.grade_presets()
        load = menu.addMenu("Charger un preset de corrections")
        load.setEnabled(bool(presets))
        for name in sorted(presets):
            load.addAction(name).triggered.connect(lambda _c=False, n=name: pane.load_grade_preset(n))
        menu.addAction("Enregistrer les corrections comme preset…").triggered.connect(
            lambda: self._ask_video_preset(pane))
        menu.addAction("Réinitialiser les corrections").triggered.connect(pane.reset_grade)
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _ask_video_preset(self, pane):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Preset de corrections", "Nom du preset :")
        if ok and name.strip():
            pane.save_grade_preset(name.strip())

    def _layout_video_buttons(self):
        """Boutons du cadre « Vidéo » : corrections, exporter, informations, plein ecran, fermer."""
        pane = self._video
        group = self.titlebar.video_group()
        if pane is None:
            group.hide()
            return
        if not self._video_buttons:
            for kind, tip, slot in (
                    ("grade", "Corrections colorimétriques, LUT, presets", None),
                    ("export", "Exporter (sélection IN / OUT ou média complet)…",
                     lambda: self._video and self._video.open_export_window()),
                    ("info", "Informations en surimpression (I)", lambda: self._video and self._video.toggle_info()),
                    ("fullscreen", "Plein écran (F, Échap pour sortir)",
                     lambda: self._video and self._video.toggle_fullscreen()),
                    ("close", "Fermer le module vidéo (Échap)", self._close_video)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                if slot is None:
                    button.clicked.connect(lambda _c=False, b=button: self._video_menu(b))
                else:
                    button.clicked.connect(slot)
                button._video_kind = kind
                self._video_buttons.append(button)
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in self._video_buttons:
            style_focus_button(button)
            if button._video_kind == "info":
                button.set_alert(self._mode_on_color() if pane.info_visible() else None)
            button.move(x, origin.y())
            button.show()
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()

    # -- Mode « Board » (paquet board/, facon Miro) --

    @staticmethod
    def _board_icon(kind: str, size: int):
        """Icone perso d'un bouton du board (Reglages > Module MRO > Icones), sinon None (glyphe peint)."""
        from previews import custom_ui_icon_pixmap
        return custom_ui_icon_pixmap(f"ui_board_{kind}", size)

    def _toggle_board(self):
        if self._board is not None:
            self._close_board()
            return
        import board
        _column, path = self._selected_path()
        if path is not None and path.is_file() and board.is_board_file(path):
            self._open_board(path)
        elif path is not None and path.is_file() and board.is_cad_drawing(path):
            self._open_cad_drawing(path)

    def _open_cad_drawing(self, path: Path):
        """Dessin DXF / DWG dans le module MRO (demande de l'utilisateur) : lu et converti HORS du fil de
        l'interface (`board.cad_import`, conversion ODA pour un DWG : plusieurs secondes possibles), puis ouvert
        comme un board en memoire (le dessin d'origine n'est jamais reecrit ; voir `BoardPane.open_import`)."""
        import threading
        from board import cad_import
        path = Path(path)
        if self._board is not None and self._board.source == path:
            return
        relay = _DrawingRelay(self)
        self._drawing_relay = relay                        # seule la derniere demande est ouverte
        relay.done.connect(lambda data, report, error: self._cad_drawing_read(relay, path, data, report, error))
        self.path_label.setText(f"Lecture de {path.name}…")

        def work():
            try:
                data, report = cad_import.read_drawing(path)
                relay.done.emit(data, report, None)
            except cad_import.DrawingError as exc:
                relay.done.emit(None, None, str(exc))
            except Exception as exc:                        # noqa: BLE001 - fichier inattendu : message
                relay.done.emit(None, None, f"{type(exc).__name__} : {exc}")
        threading.Thread(target=work, name="lecture DXF", daemon=True).start()

    def _cad_drawing_read(self, relay, path: Path, data, report, error):
        relay.deleteLater()
        if relay is not self._drawing_relay:
            return                                          # une autre ouverture a ete demandee depuis
        self._drawing_relay = None
        from board import cad_import
        if error is not None:
            self.path_label.setText(f"{path.name} : {error}")
            return
        if self._open_board(path, imported=data):
            self.path_label.setText(cad_import.describe(report))

    def _open_board(self, path: Path, imported: dict | None = None) -> bool:
        """Le board recouvre les colonnes (comme l'editeur de texte) ; ses boutons dans le cadre « Board » de la
        barre de navigation. Un autre board ouvert est d'abord enregistre et ferme. `imported` : dessin DXF / DWG
        deja lu (`_open_cad_drawing`), ouvert en memoire."""
        import board.ui
        from board.ui import BoardPane
        board.ui.ICON_PROVIDER = self._board_icon
        board.ui.SETTING_WRITER = self._write_setting_now
        import board.cad_export
        from previews import _oda_file_converter
        board.cad_export.ODA_PROVIDER = _oda_file_converter     # meme recherche que les apercus DWG
        # Overrides des menus du board (Reglages > Module MRO > Menus contextuels) : la correspondance des lignes est
        # dans le catalogue des reglages (deja charge par le prechargement de la fenetre, sinon ~0,1 s une fois).
        import settings_window_v2  # noqa: F401
        if self._project_columns_hidden:
            return False
        if not self._close_md_editor():
            return False
        self._close_video()
        if self._board is not None:
            if (self._board.source if imported is not None else self._board.path) == Path(path):
                return True
            if not self._close_board():
                return False
        pane = BoardPane(self.scroll.viewport(), ui_state.APPLIED_SETTINGS or {})
        if not (pane.open_import(imported, path) if imported is not None else pane.open(path)):
            pane.deleteLater()
            return False
        self._board = pane
        pane.closeRequested.connect(self._close_board)
        pane.stateChanged.connect(self._layout_board_buttons)
        pane.dirtyChanged.connect(lambda _d: self._layout_board_buttons())
        pane.fade_in()
        self._layout_board_buttons()
        self._sync_collapse_button()
        self.path_label.setText(str(path))
        return True

    def _close_board(self) -> bool:
        """Retour aux colonnes (le board est enregistre, avec sa vue). False = annule."""
        pane = self._board
        if pane is None:
            return True
        if not pane.confirm_leave():
            return False
        self._board = None
        self.titlebar.board_group().hide()
        pane.fade_out(pane.deleteLater)
        self._sync_collapse_button()
        column, _path = self._selected_path()
        if column is not None:
            column.list.setFocus()
        return True

    def _layout_board_buttons(self):
        """Boutons du cadre « Board » : annuler, retablir, tout voir, exporter, fermer."""
        pane = self._board
        group = self.titlebar.board_group()
        if pane is None:
            group.hide()
            return
        if not self._board_buttons:
            for kind, tip, slot in (
                    ("undo", "Annuler (Ctrl+Z)", lambda: self._board and self._board.undo()),
                    ("redo", "Rétablir (Ctrl+Y)", lambda: self._board and self._board.redo()),
                    ("fit", "Tout voir (Maj+1)", lambda: self._board and self._board.view.fit_all()),
                    ("export", "Exporter (PNG, SVG, PDF)…", lambda: self._board and self._board.export_dialog()),
                    ("close", "Fermer le board (Échap)", self._close_board)):
                button = IconButton(kind, role_color("buttons", "#c4cacf"), C["text"], parent=group)
                button.setCursor(Qt.ArrowCursor)
                button.setFlat(True)
                button.setToolTip(tip)
                button.clicked.connect(slot)
                button._board_kind = kind
                self._board_buttons.append(button)
        origin = group.content_origin()
        x, height = origin.x(), 0
        for button in self._board_buttons:
            style_focus_button(button)
            kind = button._board_kind
            if kind == "undo":
                self._set_button_usable(button, pane.can_undo())
            elif kind == "redo":
                self._set_button_usable(button, pane.can_redo())
            button.move(x, origin.y())
            button.show()
            x += button.width() + scaled(6, 0)
            height = max(height, button.height())
        group.restyle()
        group.fit(x - scaled(6, 0), height)
        group.show()
        group.raise_()
        self.titlebar.place_viewer_group()

    def _apply_global_stylesheet(self):
        """Feuille de style commune (boutons, zones de saisie, couleurs) reappliquee a la fenetre principale et a
        tout ce qui en depend — PAS a l'application entiere : `QApplication.setStyleSheet` repolit TOUS les
        widgets, y compris ceux de la fenetre de reglages gardee en memoire (~24 000, soit ~70 s) ; sur la seule
        fenetre principale (~160 widgets) : ~0,05 s. La feuille de l'application (posee au lancement) reste la base ;
        celle-ci passe devant pour tout ce qui est dans la fenetre principale."""
        self.setStyleSheet(build_stylesheet())

    def refresh_chrome_sizes(self):
        """Reapplique l'echelle courante (voir app_style.scaled) aux
        widgets permanents de la fenetre (barre de titre, barre du haut),
        qui comme leurs polices (voir refresh_chrome_fonts) ne sont
        construits qu'une fois et ne suivraient donc pas le slider d'echelle
        sans ce rafraichissement explicite."""
        self.titlebar.refresh_sizes()
        self.titlebar.refresh_look()
        self.root_field.setFixedHeight(self._nav_input_height())
        self.root_field.setFixedWidth(scaled(190))
        self.preset_picker.select.setFixedHeight(self._nav_input_height())

    def refresh_chrome_fonts(self):
        """Reapplique les polices de role aux widgets permanents de la
        fenetre (topbar, statut, panneau de detail), qui contrairement aux
        colonnes ne sont pas recrees par reload()."""
        self.titlebar.refresh_look()
        self.root_field.setFont(role_font("info", 11, 400))
        for btn in (self.btn_browse, self.btn_presets, self.btn_settings, self.btn_style, self.btn_collapse,
                    self.btn_viewer, self.btn_text_editor, self.btn_board, self.btn_video):
            btn.set_colors(role_color("buttons", "#c4cacf"), C["text"])
        self.path_label.setFont(role_font("info", 11, 400))
        self.path_label.setStyleSheet(f"color: {role_color('info', C['text_mono'])}; background: transparent;")
        self.status_right.setFont(role_font("info2", 11, 400))
        self.status_right.setStyleSheet(f"color: {role_color('info2', C['dim'])}; background: transparent;")
        for column in self.columns:
            column.refresh_header()
        self.detail.refresh_header()
        for column in self.image_preview_columns:
            column.refresh_header()
        for column in self.group_columns:
            column.refresh_header()
        is_dir = True
        if self.columns:
            selected = self.columns[-1].current_path()
            if selected is not None:
                is_dir = selected.is_dir()
        self.detail.refresh_fonts(is_dir)

    def refresh_colors(self, rebuild_stylesheet: bool = True):
        """Reapplique toutes les couleurs (voir app_style.C, mutable via
        set_color) aux widgets dont le style QSS a ete fixe une fois pour
        toutes a la construction — indispensable pour que la page Couleurs
        de la fenetre de parametres s'applique en temps reel (voir la
        remarque sur set_color dans app_style.py).

        rebuild_stylesheet=False saute uniquement le app.setStyleSheet
        global (repolissage de TOUS les widgets de l'appli, tres couteux) :
        a utiliser quand on sait qu'aucune des valeurs lues par
        build_stylesheet (couleurs, cadre/rayon des boutons, cadre/rayon des
        zones de saisie, rayon des tableaux) n'a bouge (voir _apply_settings),
        le reste de cette methode restant assez leger pour tourner a chaque
        rafraichissement."""
        if rebuild_stylesheet:
            self._apply_global_stylesheet()
        _set_qss(self.central,
            f"#CentralFrame {{ background: {C['window']}; border: 1px solid {C['border']}; "
            f"border-radius: {ui_state.WINDOW_RADIUS}px; }}"
        )
        _set_qss(self.columns_host, f"#ColumnsHost {{ background: {C['window']}; }}")
        self.titlebar.refresh_look()
        for btn in (self.titlebar.btn_min, self.titlebar.btn_max, self.titlebar.btn_close):
            btn.set_colors(C["label"], C["text"])
        self._refresh_button_shadows()
        _set_qss(self.statusbar, f"#StatusBar {{ background: {C['chrome']}; border-top: 1px solid {C['border']}; }}")
        for column in self.columns:
            column.refresh_colors()
        for column in self.group_columns:
            column.refresh_colors()
        for column in self.image_preview_columns:
            column.refresh_colors()
        self.detail.refresh_colors()
        self.refresh_chrome_fonts()

    def _refresh_button_shadows(self):
        """Ombre du groupe Bouton sur les boutons de la fenêtre principale."""
        look = shadow_look(ui_state.APPLIED_SETTINGS or {}, "button_shadow", resolve_color_ref)
        # Meme ombre que la derniere fois : seuls les boutons NOUVEAUX en ont besoin (chaque tick d'un glisser
        # de couleur reposait l'effet sur tous les boutons : effets graphiques recalcules, lent).
        sig = repr(look)
        unchanged = sig == getattr(self, "_button_shadow_sig", None)
        self._button_shadow_sig = sig
        for button in self.findChildren(QPushButton):
            own = getattr(button, "_app_shadow_effect", None)
            if unchanged and (own is not None or look is None):
                continue
            if look is None:
                if own is not None:
                    button.setGraphicsEffect(None)
                    button._app_shadow_effect = None
                continue
            if own is None and button.graphicsEffect() is not None:
                continue
            if own is None:
                own = QGraphicsDropShadowEffect(button)
                button._app_shadow_effect = own
                button.setGraphicsEffect(own)
            sides = look["on"]
            size = look["size"]
            own.setBlurRadius(max(1, size * 2))
            own.setOffset((int(sides["right"]) - int(sides["left"])) * size / 3,
                          (int(sides["bottom"]) - int(sides["top"])) * size / 3)
            color = next((look["colors"][side] for side in ("bottom", "right", "top", "left") if sides[side]), None)
            if color is None:                      # aucun cote allume : pas d'ombre (jamais d'exception ici)
                button.setGraphicsEffect(None)
                button._app_shadow_effect = None
                continue
            own.setColor(QColor(color))

def _save_menu_layouts(layouts: dict) -> None:
    """Disposition des menus contextuels choisie a la main (settings_menu) : etat temps reel, ecrit aussitot,
    SEULE (save_live_state : jamais le preset actif fige dans le fichier au passage)."""
    from settings_store import save_live_state
    save_live_state("context_menu_layouts", layouts)
    if isinstance(ui_state.APPLIED_SETTINGS, dict):
        ui_state.APPLIED_SETTINGS["context_menu_layouts"] = layouts


def _install_context_menus() -> None:
    """Menus contextuels (settings_menu) : habillage = Reglages > Menu contextuel, lu a chaque ouverture."""
    from config import DATA_DIR, ICONS_DIR
    from browser_core import _resolve_font_family
    import settings_menu
    settings_menu.install(
        values=lambda: ui_state.APPLIED_SETTINGS,
        load_layouts=lambda: (ui_state.APPLIED_SETTINGS or {}).get("context_menu_layouts") or {},
        save_layouts=_save_menu_layouts,
        font_family=lambda label, size, weight: _resolve_font_family(label, size, weight),
        icon_dir=DATA_DIR / "menu_icons", icon_sources=(ICONS_DIR,))


def _install_qt_message_filter():
    """Retire deux avertissements Qt inoffensifs qui noyaient la console :
    - « QWidgetWindow(...) must be a top level window » : une video affichee dans une
      QScrollArea (la zone des colonnes) rend natifs tous ses parents (comportement
      de Qt), puis chaque menu ou boite de dialogue ouvert depuis eux le signale ;
    - les alertes libpng sur le profil colorimetrique de certaines captures PNG.
    Tous les autres messages restent affiches."""
    from PySide6.QtCore import QLoggingCategory, qInstallMessageHandler
    QLoggingCategory.setFilterRules("qt.gui.imageio.warning=false")

    def handler(_mode, _context, message):
        if "must be a top level window" in message:
            return
        sys.stderr.write(message + "\n")

    qInstallMessageHandler(handler)


def _main_toggle_style_listener(toggle, key):
    """Style choisi au clic droit sur un toggle de la fenetre principale : enregistre pour lui."""
    window = toggle.window()
    if isinstance(window, PipelineBrowser):
        window._set_toggle_style(toggle, key)


TOGGLE_STYLE_LISTENERS.append(_main_toggle_style_listener)


def _install_error_log():
    """Exceptions Python non rattrapees (dont celles des fonctions appelees par Qt : peinture, souris…) : ecrites aussi
    dans `data/error_log.txt` (`pythonw` n'a pas de console). Aucun gestionnaire d'exceptions Windows (`faulthandler`
    fait planter QtWebEngine)."""
    import traceback
    log = Path(__file__).with_name("data") / "error_log.txt"
    previous = sys.excepthook

    def hook(kind, value, trace):
        try:
            with open(log, "a", encoding="utf-8") as handle:
                handle.write("\n--- " + time.strftime("%Y-%m-%d %H:%M:%S") + " ---\n")
                handle.write("".join(traceback.format_exception(kind, value, trace)))
        except OSError:
            pass
        previous(kind, value, trace)
    sys.excepthook = hook


def main():
    _install_error_log()
    _install_qt_message_filter()
    settings = load_settings(startup=True)      # le preset par defaut devient le preset actif
    apply_all_settings(settings)
    root = Path(settings["root_path"])
    _config.ROOT = root
    # Cache en arriere-plan : index des noms (lu une fois), anciens noms renommes, puis menage (ni images
    # inutiles ni apercus de fichiers supprimes). Rien de tout cela sur le fil de l'interface.
    threading.Thread(target=lambda: (migrate_cache_names(), sweep_preview_cache_if_due()),
                     name="preview-cache-sweep", daemon=True).start()

    # Le winId() d'une fenetre enfant (reglages, config des colonnes : voir
    # apply_dwm_frame) rendait natifs ses « freres », dont #CentralFrame : un
    # cadre natif dans la fenetre translucide n'est plus recompose image par
    # image et les animations des colonnes sautaient des l'ouverture des
    # reglages (tests/_probe_screen_anim.py).
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    # QtWebEngine (inspecteur des notes, module Markdown) cree apres l'application : contextes OpenGL partages.
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    # OpenGL : echange de tampons SANS attendre le balayage de l'ecran (format de la FENETRE, a poser avant
    # l'application) — une image de retard en moins pendant un pan du CAD ; la couche GPU cadence elle-meme ses
    # images (board/cad_gpu.py, FramePacer).
    try:
        from board.cad_gpu import low_latency_format
        low_latency_format()
    except Exception:                                   # noqa: BLE001 - paquet du board absent : format par defaut
        pass
    app = QApplication(sys.argv)
    apply_style(app)
    _install_context_menus()
    window = PipelineBrowser(root)
    window.show()
    window._start_settings_idle_watch()     # reglages prepares apres 1 min sans activite sur l'appli (rien au lancement)
    QTimer.singleShot(6000, window._preload_md_editor)       # module Markdown / code prepare en fond
    QTimer.singleShot(4500, window._preload_video)            # module video : bibliotheques chargees en fond
    QTimer.singleShot(1500, window._start_css_sync)          # feuille CSS partagee avec Obsidian
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
