"""Habillage commun des fenetres de reglages et des fenetres additionnelles (barre de titre, panneau,
ombre, Fenetres additionnelles) et champ des omissions. L'ancienne fenetre de reglages v1
(`SettingsWindow`) a ete retiree : la fenetre de reglages est `settings_window_v2.SettingsWindowV2`."""
from PySide6.QtCore import QEvent, QMargins, QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from app_style import (
    C,
    start_native_move,
)
from settings_theme import _set_text_role
from settings_store import (
    DEFAULT_SETTINGS,
    M,
    _coerce_corner_radius,
    _coerce_side_enabled,
    _resolve_color_value,
)
from settings_widgets import (
    _qfont,
)


# ==========================================================================
# Barre de titre, panneau et ombre des fenetres de reglages / additionnelles.
# ==========================================================================

class _CloseButton(QPushButton):
    """Croix de la barre de navigation : tracee au CENTRE EXACT du bouton (demande de l'utilisateur) — le
    caractere « × » d'une police est dessine plus bas que le milieu de sa ligne. Fond / survol : feuille de
    style ; taille de la croix = police du bouton (`apply_extra`)."""

    def paintEvent(self, event):
        super().paintEvent(event)                 # fond (survol, coins arrondis), sans texte
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        color = M["close_hover_fg"] if self.underMouse() else M["close_fg"]
        size = self.font().pixelSize() if self.font().pixelSize() > 0 else QFontMetrics(self.font()).height()
        half = max(3.0, size * 0.22)
        center = QRectF(self.rect()).center()
        p.setPen(QPen(QColor(color), max(1.2, size / 13), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(center.x() - half, center.y() - half, center.x() + half, center.y() + half)
        p.drawLine(center.x() - half, center.y() + half, center.x() + half, center.y() - half)
        p.end()


class _TitleText(QLabel):
    """Titre de la barre de navigation, centre sur la HAUTEUR DES CAPITALES (demande de l'utilisateur) : une
    ligne de texte n'est centree que sur sa boite (hampes et jambages compris), les lettres tombaient a cote
    du milieu. Remplit la hauteur de la barre ; couleur `_color` (role, puis Fenetres additionnelles)."""

    def __init__(self, text: str):
        super().__init__(text)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._color = None

    def paintEvent(self, event):
        from PySide6.QtGui import QFontMetricsF
        p = QPainter(self)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        p.setFont(self.font())
        metrics = QFontMetricsF(self.font())
        baseline = (self.height() + metrics.capHeight()) / 2
        p.setPen(QColor(self._color or M["title_fg"]))
        text = metrics.elidedText(self.text(), Qt.ElideRight, self.width())
        p.drawText(QPointF(0, baseline), text)
        p.end()


class _SettingsTitleBar(QWidget):
    closeClicked = Signal()
    # Clic sur « modifications non enregistrees » (demande de l'utilisateur) : la fenetre enregistre.
    saveClicked = Signal()

    def __init__(self, dialog: QDialog, parent=None, title: str = "Parametres generaux"):
        super().__init__(parent)
        self._dialog = dialog
        self.setObjectName("SettingsTitleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#SettingsTitleBar {{ background: {M['titlebar_bg']}; border-bottom: 1px solid {M['panel_border']}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(9)
        import previews as pb_previews

        # Icone et croix A L'ECHELLE DU TITRE (role « window_title ») : en tailles fixes (9 px, police 11)
        # elles restaient minuscules a cote d'un titre plus grand (signale, fenetres d'override).
        title = self._title = _TitleText(title)
        _set_text_role(title, "window_title")
        from settings_theme import _text_color
        title._color = _text_color("window_title")
        text_h = self._text_h = QFontMetrics(title.font()).height()
        icon = max(12, round(text_h * 0.95))
        bar_h = max(32, text_h + 16)
        self.setFixedHeight(bar_h)
        dot = self._dot = QLabel()
        dot.setFixedSize(icon, icon)
        # Icone perso (voir Settings > ICONES > General, UI_ICON_SETTINGS_
        # GEAR) si l'utilisateur en a choisi une, sinon le carre neutre
        # d'origine — voir la remarque de l'utilisateur, "cette icone sera
        # aussi utilisee sur la fenetre de settings elle-meme avant le
        # titre dans la barre de navigation".
        custom_gear = pb_previews.custom_ui_icon_pixmap(pb_previews.UI_ICON_SETTINGS_GEAR, icon)
        if custom_gear is not None:
            dot.setPixmap(custom_gear)
            dot.setStyleSheet("background: transparent;")
        else:
            dot.setStyleSheet(f"border: 1px solid {M['dot_border']}; background: transparent;")
        layout.addWidget(dot)
        layout.addWidget(title)
        layout.addStretch(1)
        self.dirty_label = QLabel("")
        self.dirty_label.setFont(_qfont(10, 400, mono=True))
        self.dirty_label.installEventFilter(self)
        self._dirty = False
        layout.addWidget(self.dirty_label)
        self.close_btn = _CloseButton()           # croix tracee, centree
        self.close_btn.setFixedSize(max(36, round(text_h * 2.6)), bar_h)
        self.close_btn.setCursor(Qt.ArrowCursor)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setFlat(True)
        close_font = QFont(title.font())
        close_font.setBold(False)
        close_font.setPixelSize(max(18, round(text_h * 1.45)))
        self.close_btn.setFont(close_font)
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; color: " + M["close_fg"] + "; }"
            "QPushButton:hover { background: " + M["close_hover_bg"] + "; color: " + M["close_hover_fg"] + "; }"
        )
        self.close_btn.clicked.connect(self.closeClicked.emit)
        layout.addWidget(self.close_btn)
        self.set_dirty(False)

    def apply_extra(self, look: dict):
        """Habillage de Reglages > Fenetres additionnelles : texte (police, couleur), hauteur, couleur, filet du
        bas, coins du haut (ceux de la fenetre, moins sa bordure) ; boutons (croix) : taille X / Y, border
        radius."""
        font = look.get("title_font")
        if font is not None:
            self._title.setFont(font)
            self._title.setStyleSheet(f"color: {look['title_color']}; background: transparent;")
            self._title._color = look["title_color"]
            self._title.update()
            self._text_h = QFontMetrics(font).height()
            icon = max(12, round(self._text_h * 0.95))
            if self._dot.width() != icon:
                import previews as pb_previews
                self._dot.setFixedSize(icon, icon)
                gear = pb_previews.custom_ui_icon_pixmap(pb_previews.UI_ICON_SETTINGS_GEAR, icon)
                if gear is not None:
                    self._dot.setPixmap(gear)
        bw, bh = look.get("button_size") or (self.close_btn.width(), self.close_btn.height())
        height = max(int(look["title_h"]), self._text_h + 4, bh)
        self.setFixedHeight(height)
        self.close_btn.setFixedSize(bw, bh)
        glyph = QFont(self.close_btn.font())
        glyph.setPixelSize(max(10, min(round(self._text_h * 1.45), bh - 4)))
        self.close_btn.setFont(glyph)
        on, color, thick = look["title_line"]
        tl, tr = look["inner_radius"]["top_left"], look["inner_radius"]["top_right"]
        self.setStyleSheet(
            f"#SettingsTitleBar {{ background: {look['title_bg']}; "
            f"border-bottom: {thick if on else 0}px solid {color}; "
            f"border-top-left-radius: {tl}px; border-top-right-radius: {tr}px; }}")
        r = dict(look.get("button_radius") or {})
        if bh >= height:                       # bouton contre le coin de la fenetre : il en suit l'arrondi
            r["top_right"] = max(r.get("top_right", 0), tr)
        self.close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0; color: " + M["close_fg"] + "; "
            f"border-top-left-radius: {r.get('top_left', 0)}px; border-top-right-radius: {r.get('top_right', 0)}px; "
            f"border-bottom-right-radius: {r.get('bottom_right', 0)}px; "
            f"border-bottom-left-radius: {r.get('bottom_left', 0)}px; }}"
            "QPushButton:hover { background: " + M["close_hover_bg"] + "; color: " + M["close_hover_fg"] + "; }")

    def set_dirty(self, dirty: bool):
        """Etat « non enregistre » : texte en ROUGE (meme rouge que la bordure de la fenetre,
        M["dirty_frame"]) et cliquable (saveClicked)."""
        self._dirty = dirty
        self.dirty_label.setText("modifications non enregistrees" if dirty else "a jour")
        self.dirty_label.setStyleSheet(
            f"color: {M['dirty_frame'] if dirty else M['clean_fg']}; background: transparent;"
        )
        self.dirty_label.setCursor(Qt.PointingHandCursor if dirty else Qt.ArrowCursor)
        self.dirty_label.setToolTip("Cliquer pour enregistrer" if dirty else "")

    def eventFilter(self, obj, event):
        if obj is self.dirty_label and self._dirty and event.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease) and event.button() == Qt.LeftButton:
            if event.type() == QEvent.MouseButtonRelease and self.dirty_label.rect().contains(
                    event.position().toPoint()):
                self.saveClicked.emit()
            return True                     # pas de deplacement de la fenetre
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            start_native_move(self._dialog)
            event.accept()
        else:
            super().mousePressEvent(event)

class _NoSqueezeScrollArea(QScrollArea):
    """QScrollArea dont le widget interne suit la LARGEUR de la fenetre
    (comme un setWidgetResizable(True) classique) mais ne descend JAMAIS en
    hauteur sous sa taille naturelle (minimumSizeHint, recalculee a chaque
    fois — suit donc aussi un contenu qui change, par exemple une section
    repliee) : au-dela, une scrollbar verticale apparait a la place d'un
    tassement des lignes.

    Necessaire car setWidgetResizable(True) seul redimensionne bel et bien
    son widget a la taille EXACTE du viewport, y compris en dessous de son
    minimumSizeHint — resize() ne respecte le minimum d'un widget QUE
    lorsqu'il est appele PAR le systeme de layout/redimensionnement
    interactif d'une fenetre, jamais sur un appel direct comme celui-ci.
    Le contenu se retrouvait alors tasse (chaque ligne ecrasee en dessous
    de sa hauteur minimale, jusqu'au chevauchement de texte) au lieu de
    faire apparaitre une scrollbar — voir la remarque de l'utilisateur,
    capture a l'appui. Corrige ici en reprenant la main juste APRES le
    redimensionnement automatique de Qt, pour forcer un plancher."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        widget = self.widget()
        if widget is not None:
            target_height = max(self.viewport().height(), widget.minimumSizeHint().height())
            if widget.height() != target_height or widget.width() != self.viewport().width():
                widget.resize(self.viewport().width(), target_height)

class _PanelFrame(QWidget):
    """Conteneur racine de tout le contenu du dialogue (titlebar, toolbar,
    corps — ~300 widgets descendants) : fond + bordure + coins arrondis
    peints a la main, PAS en QSS (voir setColors/setRadius). Un widget avec
    un tel nombre de descendants coute cher a restyler via setStyleSheet —
    Qt doit repasser en cascade sur tout le sous-arbre a chaque appel
    (comportement documente), mesure a ~20ms ici — rejoue par
    SettingsWindow._apply_panel_radius a CHAQUE glisser d'un slider de
    couleur qui touche 'well'/'topbar' (voir _refresh_dynamic_colors) :
    l'essentiel de la latence residuelle signalee par l'utilisateur, une
    fois les autres pastilles de couleur deja court-circuitees. Peindre
    directement ne coute qu'un repaint de ce SEUL widget, quel que soit le
    nombre de descendants."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = "#000000"
        self._border = "#000000"
        self._radius = 0
        self._extra = False          # fenetre additionnelle : cadre de EXTRA_WINDOW_LOOK
        self._alert: str | None = None

    def setAlert(self, color: str | None):
        """Bordure d'alerte (ex. « non enregistre », rouge) a la place de celle reglee ; None = reglee."""
        if color != self._alert:
            self._alert = color
            self.update()

    def setColors(self, bg: str, border: str):
        if (bg, border) != (self._bg, self._border):
            self._bg, self._border = bg, border
            self.update()

    def setRadius(self, radius: int):
        radius = max(0, int(radius))
        if radius != self._radius:
            self._radius = radius
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._extra:
            from settings_widgets import _paint_bordered_vector
            look = EXTRA_WINDOW_LOOK
            sides, colors, thick = look["sides"], look["border_colors"], look["thickness"]
            if self._alert:
                sides = {k: True for k in sides}
                colors = {k: self._alert for k in colors}
                thick = max(1, thick)
            _paint_bordered_vector(p, self.rect(), look["radius"], sides, thick, colors, self._bg)
            p.end()
            return
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        p.fillPath(path, QColor(self._bg))
        p.setPen(QPen(QColor(self._alert or self._border), 1))
        p.drawPath(path)
        p.end()


# -- Fenetres additionnelles (demande de l'utilisateur) : toutes les fenetres en plus de la principale
# (reglages, override / a la volee, presets) partagent Reglages > Fenetres additionnelles : bordures,
# border radius EXACT, ombre, barre de navigation (hauteur, couleur, filet), filet de la barre des boutons.
# Fenetre TRANSPARENTE : le panneau (_PanelFrame) est peint arrondi, l'ombre dans une marge autour
# (_WindowShadow) ; pas d'ombre ni de filet de Windows. --

EXTRA_WINDOW_LOOK: dict = {}
_EXTRA_WINDOWS: list = []


def seed_extra_window_look(settings: dict) -> None:
    """Habillage des fenetres additionnelles d'apres `settings` ; les fenetres ouvertes le reprennent."""
    from settings_menu import _font as _gabarit_font      # police d'une ligne gabarit (role de l'appli resolu)
    from settings_widgets import shadow_look
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    colors = s.get("colors") or {}

    def res(value):
        return _resolve_color_value(value, colors)

    def line(name):
        return (bool(s[f"extra_window_{name}_enabled"]), res(s[f"extra_window_{name}_color"]),
                max(0, int(s[f"extra_window_{name}_thickness"] or 0)))

    sides = _coerce_side_enabled(s["extra_window_border_enabled"])
    thickness = max(0, int(s["extra_window_border_thickness"] or 0))
    radius = _coerce_corner_radius(s["extra_window_radius"])
    EXTRA_WINDOW_LOOK.update(
        sides=sides, thickness=thickness, radius=radius,
        border_colors={k: res(v) for k, v in (s["extra_window_border"] or {}).items()},
        # Coins des barres (titre en haut, boutons en bas) : ceux de la fenetre, moins sa bordure.
        inner_radius={k: max(0, v - thickness) for k, v in radius.items()},
        shadow=shadow_look(s, "extra_window_shadow", res),
        title_h=int(s["extra_window_title_height"] or 0), title_bg=res(s["extra_window_title_bg"]),
        title_font=_gabarit_font(s, "extra_window_title_text", 11),
        title_color=res(s["extra_window_title_text_font_color"]),
        button_size=(max(8, int(s["extra_window_title_button_width"] or 0)),
                     max(8, int(s["extra_window_title_button_height"] or 0))),
        button_radius=_coerce_corner_radius(s["extra_window_title_button_radius"]),
        title_line=line("title_line"), buttons_line=line("buttons_line"))
    for window in list(_EXTRA_WINDOWS):
        try:
            apply_extra_window_look(window)
        except RuntimeError:                       # fenetre detruite
            _EXTRA_WINDOWS.remove(window)


class _WindowShadow(QWidget):
    """Ombre d'une fenetre additionnelle, peinte dans la marge transparente autour de son panneau."""

    def __init__(self, window: QWidget, panel: QWidget):
        super().__init__(window)
        self._panel = panel
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.lower()

    def paintEvent(self, event):
        from settings_widgets import paint_shadow
        look = EXTRA_WINDOW_LOOK.get("shadow")
        if look is None:
            return
        p = QPainter(self)
        paint_shadow(p, self._panel.geometry(), EXTRA_WINDOW_LOOK["radius"], look)
        p.end()


def chrome_size(window: QWidget) -> tuple[int, int]:
    """(largeur, hauteur) que le cadre d'une fenetre additionnelle ajoute a son contenu : marge de
    l'ombre + bordure du panneau."""
    chrome = getattr(window, "_extra_chrome", None)
    if chrome is None:
        return 2, 2
    outer = chrome["outer"].contentsMargins()
    inner = chrome["root"].contentsMargins()
    return (outer.left() + outer.right() + inner.left() + inner.right(),
            outer.top() + outer.bottom() + inner.top() + inner.bottom())


def shadow_margins(window: QWidget) -> QMargins | None:
    """Marge transparente (ombre) autour du panneau : les bords de redimensionnement sont ceux du panneau."""
    chrome = getattr(window, "_extra_chrome", None)
    return chrome["outer"].contentsMargins() if chrome is not None else None


def install_extra_window(window: QWidget, panel: "_PanelFrame", outer, root, titlebar=None, buttons=None):
    """Fait de `window` une fenetre additionnelle : `outer` = mise en page de la fenetre (contient le
    panneau), `root` = celle du panneau ; `buttons` = barre des boutons du bas (son filet du haut)."""
    window.setAttribute(Qt.WA_TranslucentBackground, True)
    panel._extra = True
    shadow = _WindowShadow(window, panel)
    window._extra_chrome = {"panel": panel, "outer": outer, "root": root, "titlebar": titlebar,
                            "buttons": buttons, "shadow": shadow}
    window.installEventFilter(_SHADOW_FOLLOW)
    _EXTRA_WINDOWS.append(window)
    window.destroyed.connect(lambda *_a, w=window: _EXTRA_WINDOWS.remove(w) if w in _EXTRA_WINDOWS else None)
    if not EXTRA_WINDOW_LOOK:
        seed_extra_window_look(DEFAULT_SETTINGS)
    apply_extra_window_look(window)


def apply_extra_window_look(window: QWidget) -> None:
    chrome = window._extra_chrome
    look = EXTRA_WINDOW_LOOK
    shadow = look.get("shadow")
    size = shadow["size"] if shadow else 0
    on = (shadow or {}).get("on") or {}
    chrome["outer"].setContentsMargins(*(size if on.get(k) else 0 for k in ("left", "top", "right", "bottom")))
    t, sides = look["thickness"], look["sides"]
    chrome["root"].setContentsMargins(*(t if sides.get(k) else 0 for k in ("left", "top", "right", "bottom")))
    if chrome["titlebar"] is not None:
        chrome["titlebar"].apply_extra(look)
    buttons = chrome["buttons"]
    if buttons is not None:
        b_on, b_color, b_thick = look["buttons_line"]
        bl, br = look["inner_radius"]["bottom_left"], look["inner_radius"]["bottom_right"]
        buttons.setObjectName("ExtraButtonsBar")
        buttons.setAttribute(Qt.WA_StyledBackground, True)
        buttons.setStyleSheet(
            f"#ExtraButtonsBar {{ background: {M['toolbar_bg']}; border-top: {b_thick if b_on else 0}px solid {b_color}; "
            f"border-bottom-left-radius: {bl}px; border-bottom-right-radius: {br}px; }}")
    chrome["shadow"].setGeometry(window.rect())
    chrome["panel"].update()
    chrome["shadow"].update()
    hook = getattr(window, "_on_chrome_changed", None)
    if hook is not None:
        hook()


class _ShadowFollow(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            chrome = getattr(obj, "_extra_chrome", None)
            if chrome is not None:
                chrome["shadow"].setGeometry(obj.rect())
        return False


_SHADOW_FOLLOW = _ShadowFollow()

class _OmitListField(QWidget):
    """Liste de noms à masquer, avec les mêmes commandes + et − que Configuration (`prompt` = question
    posée par « + »)."""

    changed = Signal()

    def __init__(self, parent=None, prompt: str = "Nom à omettre :"):
        super().__init__(parent)
        self._prompt = prompt
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.list = QListWidget(self)
        self.list.setFixedHeight(96)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        for label, callback in (("+", self._add), ("-", self._remove_selected)):
            button = QPushButton(label, self)
            button.setFixedSize(24, 20)
            button.setFont(_qfont(13, 700))
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.refresh_style()

    def refresh_style(self):
        self.list.setStyleSheet(
            f"QListWidget {{ background: {C['well']}; color: {C['text']}; "
            f"border: 1px solid {C['border']}; border-radius: 0px; }}"
            "QListWidget::item { padding: 2px 4px; }"
            f"QListWidget::item:selected {{ background: {C['sel_idle']}; }}"
        )
        for button in self.findChildren(QPushButton):
            button.setStyleSheet(
                f"QPushButton {{ background: {C['btn']}; color: {C['text']}; "
                f"border: 1px solid {C['btn_border']}; border-radius: 3px; padding: 0px; }}"
                f"QPushButton:hover {{ background: {C['btn_hover']}; }}"
            )

    def _add(self):
        name, ok = self._ask()
        name = name.strip()
        if ok and name and name.casefold() not in {value.casefold() for value in self.values()}:
            self.list.addItem(name)
            self.changed.emit()

    def _ask(self) -> tuple[str, bool]:
        return QInputDialog.getText(self, "Ajouter", self._prompt)

    def _remove_selected(self):
        selected = self.list.selectedItems()
        for item in selected:
            self.list.takeItem(self.list.row(item))
        if selected:
            self.changed.emit()

    def values(self) -> list[str]:
        return [self.list.item(index).text() for index in range(self.list.count())]

    def set_values(self, values):
        self.list.clear()
        self.list.addItems([str(value) for value in (values or [])])

def _omit_file_values(settings: dict) -> list[str]:
    """Affiche les anciennes extensions comme règles *.ext modifiables."""
    names = settings.get("application_omit_file_names") or []
    extensions = settings.get("application_omit_extensions") or []
    if isinstance(names, str):
        names = names.replace(";", ",").split(",")
    if isinstance(extensions, str):
        extensions = [extensions]
    values = [str(name).strip() for name in names if str(name).strip()]
    for raw in extensions:
        for extension in str(raw).replace(",", " ").replace(";", " ").split():
            suffix = extension.casefold().removeprefix("*.").lstrip(".")
            if suffix:
                values.append(f"*.{suffix}")
    return list(dict((value.casefold(), value) for value in values).values())
