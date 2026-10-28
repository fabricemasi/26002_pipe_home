"""Mode « Déplacer l'interface » : objets libres de la fenêtre, cadres de déplacement, positions enregistrées.

Découpé de pipeline_browser.py (2026-10-28) ; carte : docs/agents/fm_browser.md."""
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QActionGroup, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QToolButton, QSlider,
    QVBoxLayout, QWidget,
)

from app_style import resolve_color_ref, role_font, scaled
from settings_store import load_settings, save_live_state
from settings_widgets import widget_at_path, widget_path
from browser_core import ROLE_MEDIA_COUNTS, ROLE_PATH
from column import Column
from fm_visionneuse.focus import FocusGallery
from interface_edit_targets import PaintedTarget
import ui_state
import shiboken6


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
                from fm_visionneuse.focus import FocusGallery
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
                from fm_visionneuse.focus import FocusGallery
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
            from fm_visionneuse.focus import FocusGallery
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
