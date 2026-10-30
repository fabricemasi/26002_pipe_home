"""Contenu du PANNEAU latéral du module Design (un onglet = une fonction `build_<onglet>`) :
modèles et formats, éléments (formes, lignes, dégradés), texte (titres, combinaisons), images (import, bibliothèque
locale), position et calques (X / Y / L / H / rotation, alignement, ordre, liste des calques).
Briques : boutons du board (`_GlyphButton`, `_TextButton`), rôles de texte des réglages, champs de saisie de l'appli."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit,
                               QSizePolicy, QVBoxLayout, QWidget)

from fm_board.ui import _GlyphButton, _TextButton
from . import design_model as dm, document as doc, geometry, templates
from .items import DesignImageItem, DesignShapeItem, DesignTextItem

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
_LIBRARY = {"folder": None}                    # dossier d'images choisi (session)


def _label(text, role="card_title"):
    from settings_theme import _text_label
    label = _text_label(text, role)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return label


def _column(parent):
    widget = QWidget(parent)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 4, 0)
    layout.setSpacing(6)
    return widget, layout


def _wide_button(text, tip, slot, parent):
    button = _TextButton(text, tip, parent)
    button.setMinimumHeight(30)
    button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)      # texte long : le panneau garde sa largeur
    button.clicked.connect(slot)
    return button


def build(name, ctl, parent) -> QWidget:
    return {"templates": build_templates, "elements": build_elements, "text": build_text,
            "images": build_images, "layers": build_layers}[name](ctl, parent)


# ---------------------------------------------------------------- modèles et formats
class TemplateTile(QAbstractButton):
    """Aperçu peint d'un modèle (fond + formes simples + traits figurant les textes) : sans scène, ~0,1 ms."""

    def __init__(self, template, parent):
        super().__init__(parent)
        self.template = template
        self.setFixedSize(QSize(128, 112))
        self.setToolTip(f"{template['name']} ({template['w']:.0f} × {template['h']:.0f})")
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _event):
        from app_style import C
        from .items import fill_brush
        t = self.template
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        k = min(120 / t["w"], 88 / t["h"])
        w, h = t["w"] * k, t["h"] * k
        ox, oy = (self.width() - w) / 2, 4
        page = QRectF(ox, oy, w, h)
        p.fillRect(page, QColor("#ffffff"))
        data = dict(t.get("page", {}))
        p.setPen(Qt.NoPen)
        p.setBrush(fill_brush({"bg_type": "solid", "background": "#ffffff", **data}, page, "background", "bg_type",
                              "bg2", "bg_angle"))
        p.drawRect(page)
        p.setClipRect(page)
        for raw in t["items"]:
            r = QRectF(ox + raw["x"] * k, oy + raw["y"] * k, raw["w"] * k, raw["h"] * k)
            p.setOpacity(float(raw.get("opacity", 1.0)))
            if raw["type"] == dm.SHAPE:
                from fm_miro.items import shape_path
                p.setBrush(fill_brush({"fill_type": "solid", **raw}, r))
                p.drawPath(shape_path(raw.get("shape", "rect"), r, float(raw.get("radius", 0)) * k))
            elif raw["type"] == dm.TEXT:
                p.setBrush(QColor(raw.get("color", dm.INK)))
                line = max(1.0, raw["font_size"] * k * 0.55)
                p.drawRoundedRect(QRectF(r.x(), r.y() + line * 0.3, min(r.width(), len(raw["text"]) * line * 0.9),
                                         line), line / 2, line / 2)
        p.setOpacity(1.0)
        p.setClipping(False)
        if self.underMouse():
            p.setPen(QPen(QColor(dm.ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(page)
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(0, oy + h + 2, self.width(), 18), Qt.AlignHCenter | Qt.AlignTop, t["name"][:20])
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


def build_templates(ctl, parent):
    widget, layout = _column(parent)
    has_pages = bool(ctl.pages())
    layout.addWidget(_label("Nouveau format" if has_pages else "Créer un design : choisissez un format"))
    for key, label, w, h in dm.PAGE_FORMATS:
        layout.addWidget(_wide_button(label, "Ajoute une page de ce format" if has_pages else "Crée le design",
                                      lambda _c=False, k=key, w=w, h=h: new_format(ctl, k, w, h), widget))
    layout.addWidget(_wide_button("Taille personnalisée…", "Largeur × hauteur en px, mm, cm ou in",
                                  lambda: custom_format(ctl), widget))
    layout.addSpacing(8)
    layout.addWidget(_label("Modèles"))
    layout.addWidget(_label("Sur une page vide : appliqué à elle ; sinon : nouvelle page.", "value_muted"))
    grid = QGridLayout()
    grid.setSpacing(6)
    for n, template in enumerate(templates.TEMPLATES):
        tile = TemplateTile(template, widget)
        tile.clicked.connect(lambda _c=False, t=template: use_template(ctl, t))
        grid.addWidget(tile, n // 2, n % 2)
    layout.addLayout(grid)
    layout.addStretch(1)
    return widget


def new_format(ctl, key, w, h):
    current = ctl.current_page()
    page = doc.add_page(ctl.scene, w, h, after=current, values={"format": key},
                        origin=ctl.view.view_center(), text="Nouveau design" if current is None else "Ajouter une page")
    ctl.set_current_page(page, show=True)
    ctl.pagesChanged.emit()
    ctl.ui.set_tab("templates")


def custom_format(ctl):
    from .ui import ask_size
    size = ask_size(ctl.pane)
    if size:
        new_format(ctl, "custom", *size)


def use_template(ctl, template):
    current = ctl.current_page()
    page = doc.apply_template(ctl.scene, template, page=current, after=current, origin=ctl.view.view_center())
    ctl.set_current_page(page, show=True)
    ctl.pagesChanged.emit()


# ---------------------------------------------------------------- éléments
GRADIENTS = [("#8c52ff", "#5ce1e6"), ("#ff66c4", "#ffde59"), ("#004aad", "#cb6ce6"), ("#ff3131", "#ff914d"),
             ("#0097b2", "#7ed957"), ("#000000", "#737373")]


def build_elements(ctl, parent):
    widget, layout = _column(parent)
    layout.addWidget(_label("Formes (R rectangle, C cercle)"))
    grid = QGridLayout()
    grid.setSpacing(4)
    kinds = [k for k in dm.SHAPE_KINDS if k != "line"]
    for n, kind in enumerate(kinds):
        button = _GlyphButton(f"design_shape:{kind}", kind, widget, 52)
        button.clicked.connect(lambda _c=False, k=kind: ctl.add_shape(k))
        grid.addWidget(button, n // 5, n % 5)
    layout.addLayout(grid)
    layout.addWidget(_label("Lignes (L)"))
    row = QHBoxLayout()
    for text, caps in (("Ligne", ("none", "none")), ("Flèche", ("none", "arrow")),
                       ("Flèche pleine", ("none", "filled")), ("Double", ("arrow", "arrow"))):
        row.addWidget(_wide_button(text, "Ajouter une ligne", lambda _c=False, c=caps: ctl.add_shape(
            "line", {"cap_start": c[0], "cap_end": c[1]}), widget))
    layout.addLayout(row)
    dashed = QHBoxLayout()
    dashed.addWidget(_wide_button("Tirets", "Ligne en tirets", lambda: ctl.add_shape(
        "line", {"stroke_style": "dashed"}), widget))
    dashed.addWidget(_wide_button("Pointillés", "Ligne pointillée", lambda: ctl.add_shape(
        "line", {"stroke_style": "dotted"}), widget))
    layout.addLayout(dashed)
    layout.addWidget(_label("Grilles de photos (déposez une image dans une case)"))
    grids = QGridLayout()
    grids.setSpacing(4)
    for n, name in enumerate(geometry.GRIDS):
        tile = GridTile(name, widget)
        tile.clicked.connect(lambda _c=False, k=name: ctl.add_grid(k))
        grids.addWidget(tile, n // 3, n % 3)
    layout.addLayout(grids)
    layout.addWidget(_label("Cadres (image dans une forme)"))
    frames = QHBoxLayout()
    frames.setSpacing(2)
    for mask in ("", "ellipse", "round", "star", "heart", "hexagon"):
        button = _GlyphButton(f"design_shape:{mask or 'rect'}", "Cadre vide " + (mask or "rectangle"), widget, 40)
        button.clicked.connect(lambda _c=False, m=mask: ctl.add_frame(m))
        frames.addWidget(button)
    layout.addLayout(frames)
    layout.addWidget(_label("Tableaux et graphiques (double-clic : modifier)"))
    data_row = QHBoxLayout()
    data_row.setSpacing(2)
    for glyph, tip, slot in (("design_table", "Tableau 3 × 3", lambda: ctl.add_table(3, 3)),
                             ("design_chart_bar", "Graphique en barres", lambda: ctl.add_chart("bar")),
                             ("design_chart_line", "Courbe", lambda: ctl.add_chart("line")),
                             ("design_chart_pie", "Secteurs", lambda: ctl.add_chart("pie")),
                             ("design_chart_donut", "Anneau", lambda: ctl.add_chart("donut"))):
        button = _GlyphButton(glyph, tip, widget, 44)
        button.clicked.connect(lambda _c=False, f=slot: f())
        data_row.addWidget(button)
    layout.addLayout(data_row)
    layout.addWidget(_label("Dégradés"))
    grid2 = QGridLayout()
    grid2.setSpacing(4)
    for n, (a, b) in enumerate(GRADIENTS):
        button = GradientSwatch(a, b, widget)
        button.clicked.connect(lambda _c=False, a=a, b=b: ctl.add_shape(
            "rect", {"fill_type": "linear", "fill": a, "fill2": b, "gradient_angle": 45.0}))
        grid2.addWidget(button, n // 3, n % 3)
    layout.addLayout(grid2)
    layout.addStretch(1)
    return widget


class GridTile(QAbstractButton):
    def __init__(self, name, parent):
        super().__init__(parent)
        self.name = name
        self.setFixedSize(80, 56)
        self.setToolTip(f"Grille « {name} » : cadres vides sur toute la page")
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.fillRect(r, QColor("#ffffff"))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#b9b9cc"))
        for x, y, w, h in geometry.grid_cells(self.name, r.width(), r.height(), 3):
            p.drawRect(QRectF(r.x() + x, r.y() + y, w, h))
        p.end()


class GradientSwatch(QAbstractButton):
    def __init__(self, a, b, parent):
        super().__init__(parent)
        self.colors = (a, b)
        self.setFixedSize(80, 48)
        self.setToolTip(f"Rectangle en dégradé {a} → {b}")
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _event):
        from .items import fill_brush
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(Qt.NoPen)
        p.setBrush(fill_brush({"fill_type": "linear", "fill": self.colors[0], "fill2": self.colors[1],
                               "gradient_angle": 45.0}, r))
        p.drawRoundedRect(r, 6, 6)
        p.end()


# ---------------------------------------------------------------- texte
FONT_PAIRS = [("Georgia", "Segoe UI", "Élégant"), ("Arial Black", "Segoe UI", "Impact"),
              ("Segoe UI", "Georgia", "Éditorial"), ("Impact", "Arial", "Affiche"),
              ("Trebuchet MS", "Verdana", "Moderne"), ("Courier New", "Consolas", "Machine à écrire")]


def build_text(ctl, parent):
    widget, layout = _column(parent)
    layout.addWidget(_label("Ajouter du texte (T)"))
    for preset, text in (("heading", "Ajouter un titre"), ("subheading", "Ajouter un sous-titre"),
                         ("body", "Ajouter un peu de texte")):
        button = _wide_button(text, "Double-clic sur un texte pour le modifier",
                              lambda _c=False, p=preset: ctl.add_text(p), widget)
        font = button.font()
        font.setPointSizeF({"heading": 15, "subheading": 12, "body": 10}[preset])
        font.setBold(preset != "body")
        button.setFont(font)
        button.setStyleSheet(f"font-size: {int(font.pointSizeF())}pt; font-weight: {700 if preset != 'body' else 400};")
        button.setMinimumHeight({"heading": 44, "subheading": 36, "body": 30}[preset])
        layout.addWidget(button)
    styles = document_text_styles(ctl)
    if styles:
        layout.addSpacing(6)
        layout.addWidget(_label("Styles du document (clic : appliquer à la sélection, sinon nouveau texte)"))
        for style in styles:
            label = f"{style['font_family'] or 'Police par défaut'} · {style['font_size']:g} px" + (
                " · gras" if style.get("bold") else "")
            button = _wide_button(label, "Style de texte déjà utilisé dans ce design",
                                  lambda _c=False, st=style: apply_text_style(ctl, st), widget)
            button.setStyleSheet(f"color: {style['color']}; font-family: '{style['font_family']}';"
                                 if QColor(style["color"]).lightness() > 60 else
                                 f"font-family: '{style['font_family']}';")
            layout.addWidget(button)
    layout.addSpacing(6)
    layout.addWidget(_label("Combinaisons de polices"))
    for title_font, body_font, name in FONT_PAIRS:
        button = _wide_button(f"{name} — {title_font} / {body_font}", "Titre + texte, groupés",
                              lambda _c=False, a=title_font, b=body_font: add_pair(ctl, a, b), widget)
        button.setStyleSheet(f"font-family: '{title_font}';")
        layout.addWidget(button)
    layout.addStretch(1)
    return widget


TEXT_STYLE_KEYS = ("font_family", "font_size", "color", "bold", "italic", "underline", "uppercase", "letter_spacing",
                   "line_height")


def document_text_styles(ctl) -> list[dict]:
    """Styles de texte DISTINCTS du design (les plus grands d'abord, 8 au plus) : styles réutilisables."""
    seen, out = set(), []
    for item in doc.elements(ctl.scene):
        if isinstance(item, DesignTextItem):
            style = {k: item.data.get(k) for k in TEXT_STYLE_KEYS}
            key = tuple(style.values())
            if key not in seen:
                seen.add(key)
                out.append(style)
    return sorted(out, key=lambda st: -float(st["font_size"] or 0))[:8]


def apply_text_style(ctl, style):
    texts = [i for i in ctl.selection() if isinstance(i, DesignTextItem)]
    if texts:
        doc.change(ctl.scene, texts, lambda i: i.data.update(style), "Style de texte")
    else:
        ctl.add_text("body", {**style, "text": "Votre texte"})


def add_pair(ctl, title_font, body_font):
    page = ctl.ensure_page()
    w, h = page.size()
    x, y = round(w * 0.1, 2), round(h * 0.35, 2)
    size = round(min(w, h) * 0.09, 1)
    dicts = [{"type": dm.TEXT, "id": "a", "x": x, "y": y, "w": round(w * 0.8, 2), "h": size * 1.3, "z": 1.0,
              "text": "Titre accrocheur", "font_family": title_font, "font_size": size, "bold": True, "group": "g"},
             {"type": dm.TEXT, "id": "b", "x": x, "y": round(y + size * 1.5, 2), "w": round(w * 0.8, 2),
              "h": size * 0.6, "z": 2.0, "text": "Un texte d'accompagnement, sur une ou deux lignes.",
              "font_family": body_font, "font_size": round(size * 0.4, 1), "group": "g"}]
    added = doc.insert_elements(ctl.scene, page, dicts, text="Ajouter un texte")
    ctl._select(added)


# ---------------------------------------------------------------- images
class ImageTile(QAbstractButton):
    def __init__(self, path: Path, parent):
        super().__init__(parent)
        self.path = path
        self.pixmap = None
        self.setFixedSize(84, 84)
        self.setToolTip(f"{path.name}\nClic : ajouter à la page")
        self.setCursor(Qt.PointingHandCursor)

    def load(self):
        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            size.scale(160, 160, Qt.KeepAspectRatio)
            reader.setScaledSize(size)
        image = reader.read()
        self.pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.fillRect(r, QColor(255, 255, 255, 18))
        if self.pixmap is not None and not self.pixmap.isNull():
            pw, ph = self.pixmap.width(), self.pixmap.height()
            k = min(r.width() / pw, r.height() / ph)
            target = QRectF(0, 0, pw * k, ph * k)
            target.moveCenter(r.center())
            p.drawPixmap(target, self.pixmap, QRectF(self.pixmap.rect()))
        if self.underMouse():
            p.setPen(QPen(QColor(dm.ACCENT), 2))
            p.drawRect(r)
        p.end()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


def library_files(ctl) -> list[Path]:
    """Images de la bibliothèque locale : celles déjà importées dans ce board, puis le dossier choisi."""
    from fm_board import serialization
    out = []
    board = ctl.scene.board_path
    if board is not None:
        folder = serialization.assets_dir(board)
        if folder.is_dir():
            out += sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS and p.is_file()),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    chosen = _LIBRARY["folder"]
    if chosen is not None and Path(chosen).is_dir():
        out += sorted(p for p in Path(chosen).iterdir() if p.suffix.lower() in IMAGE_EXTS and p.is_file())
    return out[:400]


def build_images(ctl, parent):
    widget, layout = _column(parent)
    layout.addWidget(_wide_button("Importer des images…", "Copiées dans le dossier du board",
                                  lambda: import_dialog(ctl), widget))
    layout.addWidget(_wide_button("Choisir un dossier d'images…", "Bibliothèque locale (pour cette session)",
                                  lambda: choose_folder(ctl), widget))
    layout.addWidget(_label("Glisser-déposer des fichiers sur une page les ajoute aussi.", "value_muted"))
    from .panel_brand import build_brand_logos, library_menu
    tiles = []
    build_brand_logos(ctl, widget, layout, tiles)
    files = library_files(ctl)
    layout.addWidget(_label(f"Bibliothèque ({len(files)})"))
    grid = QGridLayout()
    grid.setSpacing(4)
    for n, path in enumerate(files):
        tile = ImageTile(path, widget)
        tile.clicked.connect(lambda _c=False, p=path: ctl.add_image_files([p]))
        tile.setContextMenuPolicy(Qt.CustomContextMenu)
        tile.customContextMenuRequested.connect(lambda pos, t=tile, p=path: library_menu(ctl, t, p, pos))
        grid.addWidget(tile, n // 3, n % 3)
        tiles.append(tile)
    layout.addLayout(grid)
    layout.addStretch(1)
    # Miniatures lues par tranches (8 par passage de boucle) : le panneau s'ouvre tout de suite.
    pending = list(tiles)

    def step():
        for _ in range(8):
            if not pending:
                return
            tile = pending.pop(0)
            try:
                tile.load()
            except RuntimeError:                         # panneau refermé entre-temps
                pending.clear()
                return
        QTimer.singleShot(0, step)
    QTimer.singleShot(0, step)
    return widget


def import_dialog(ctl):
    paths, _f = QFileDialog.getOpenFileNames(ctl.pane, "Importer des images", "",
                                             "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
    if paths:
        ctl.add_image_files([Path(p) for p in paths])
        ctl.ui.set_tab("images")


def choose_folder(ctl):
    folder = QFileDialog.getExistingDirectory(ctl.pane, "Dossier d'images")
    if folder:
        _LIBRARY["folder"] = folder
        ctl.ui.set_tab("images")


# ---------------------------------------------------------------- position et calques
class LayerList(QWidget):
    """Calques de la page courante, le plus haut en premier. Clic = choisir (Maj = ajouter) ; Ctrl + glisser =
    changer l'ordre (règle de l'appli) ; cadenas à droite = verrouiller."""

    ROW = 30
    reordered = Signal()

    def __init__(self, ctl, parent):
        super().__init__(parent)
        self.ctl = ctl
        self.items = []
        self._press = None
        self._drag_to = None
        self.setMouseTracking(True)
        self.sync()

    def sync(self):
        page = self.ctl.current_page()
        self.items = list(reversed(doc.elements(self.ctl.scene, page))) if page is not None else []
        self.setFixedHeight(max(self.ROW, len(self.items) * self.ROW))
        self.update()

    @staticmethod
    def label(item) -> str:
        if item.data.get("name"):
            return item.data["name"]
        if isinstance(item, DesignTextItem):
            return (item.data.get("text") or "Texte").splitlines()[0][:32] or "Texte"
        if isinstance(item, DesignImageItem):
            return "Image"
        if isinstance(item, DesignShapeItem):
            return "Ligne" if item.data.get("shape") == "line" else f"Forme ({item.data.get('shape')})"
        return item.kind

    def paintEvent(self, _event):
        from app_style import C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        for n, item in enumerate(self.items):
            r = QRectF(0, n * self.ROW, self.width(), self.ROW - 2)
            if item.isSelected():
                fill = QColor(dm.ACCENT)
                fill.setAlpha(90)
                p.fillRect(r, fill)
            elif n % 2:
                p.fillRect(r, QColor(255, 255, 255, 8))
            p.setPen(QColor(C["text"]))
            group = "▣ " if item.data.get("group") else ""
            p.drawText(r.adjusted(8, 0, -30, 0), Qt.AlignVCenter | Qt.AlignLeft, group + self.label(item))
            p.drawText(QRectF(r.right() - 26, r.top(), 22, r.height()), Qt.AlignCenter,
                       "🔒" if item.locked() else "·")
        if self._drag_to is not None:
            y = self._drag_to * self.ROW - 1
            p.setPen(QPen(QColor(dm.ACCENT), 2))
            p.drawLine(0, y, self.width(), y)
            # Fantôme de la ligne tirée (règle de l'appli : opacité DRAG_GHOST_OPACITY), sous le pointeur.
            from settings_widgets import DRAG_GHOST_OPACITY
            n, _pos, _ctrl = self._press
            ghost = QRectF(0, self._ghost_y - self.ROW / 2, self.width(), self.ROW - 2)
            p.setOpacity(DRAG_GHOST_OPACITY)
            fill = QColor(dm.ACCENT)
            fill.setAlpha(140)
            p.fillRect(ghost, fill)
            p.setPen(QColor(C["text"]))
            p.drawText(ghost.adjusted(8, 0, -30, 0), Qt.AlignVCenter | Qt.AlignLeft, self.label(self.items[n]))
            p.setOpacity(1.0)
        p.end()

    def _row_at(self, y) -> int:
        return max(0, min(len(self.items) - 1, int(y // self.ROW)))

    def mousePressEvent(self, event):
        if not self.items or event.button() != Qt.LeftButton:
            return
        n = self._row_at(event.position().y())
        item = self.items[n]
        if event.position().x() > self.width() - 30:
            self.ctl._select([item])
            self.ctl.toggle_lock()
            self.sync()
            return
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self._press = (n, event.position(), ctrl)
        if event.modifiers() & Qt.ShiftModifier:
            item.setSelected(not item.isSelected())
        elif not ctrl or not item.isSelected():
            self.ctl._select([item])
        self.update()

    def mouseMoveEvent(self, event):
        press = self._press
        if press is None or not press[2] or (event.position() - press[1]).manhattanLength() < 4:
            return
        self._drag_to = max(0, min(len(self.items), int(round(event.position().y() / self.ROW))))
        self._ghost_y = event.position().y()
        self.update()

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        target, self._drag_to = self._drag_to, None
        if press is None or target is None:
            self.update()
            return
        moved = self.items[press[0]]
        order = [i for i in self.items if i is not moved]
        index = target - (1 if target > press[0] else 0)
        order.insert(max(0, min(len(order), index)), moved)
        bottom_up = list(reversed(order))
        z_of = {item: float(n + 1) for n, item in enumerate(bottom_up)}
        changed = [i for i in bottom_up if i.zValue() != z_of[i]]
        if changed:
            doc.change(self.ctl.scene, changed, lambda i: i.data.update(z=z_of[i]), "Ordre des calques")
        self.sync()


class PositionPanel(QWidget):
    """X, Y, largeur, hauteur, rotation (sélection d'un élément), alignement, ordre, calques ; `sync` le relit."""

    FIELDS = (("x", "X"), ("y", "Y"), ("w", "L"), ("h", "H"), ("rotation", "Rot. °"))

    def __init__(self, ctl, parent):
        super().__init__(parent)
        self.ctl = ctl
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(6)
        layout.addWidget(_label("Disposition"))
        grid = QGridLayout()
        grid.setSpacing(4)
        self.fields = {}
        for n, (key, text) in enumerate(self.FIELDS):
            grid.addWidget(_label(text, "value_muted"), n // 2, (n % 2) * 2)
            field = QLineEdit(self)
            field.setFixedWidth(84)
            field.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            field.editingFinished.connect(lambda k=key: self.commit(k))
            grid.addWidget(field, n // 2, (n % 2) * 2 + 1)
            self.fields[key] = field
        layout.addLayout(grid)
        layout.addWidget(_label("Aligner (sur la page s'il n'y a qu'un élément)"))
        row = QHBoxLayout()
        row.setSpacing(2)
        for mode, tip in (("left", "Gauche"), ("hcenter", "Centre"), ("right", "Droite"), ("top", "Haut"),
                          ("vcenter", "Milieu"), ("bottom", "Bas")):
            button = _GlyphButton(f"design_align_{mode}", f"Aligner : {tip.lower()}", self, 34)
            button.clicked.connect(lambda _c=False, m=mode: doc.align_items(
                ctl.scene, ctl.selection(), m, len(ctl.selection()) == 1))
            row.addWidget(button)
        layout.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(_wide_button("Répartir ↔", "Espaces horizontaux égaux (3 éléments ou plus)",
                                    lambda: doc.distribute_items(ctl.scene, ctl.selection(), "h"), self))
        row2.addWidget(_wide_button("Répartir ↕", "Espaces verticaux égaux (3 éléments ou plus)",
                                    lambda: doc.distribute_items(ctl.scene, ctl.selection(), "v"), self))
        layout.addLayout(row2)
        row3 = QHBoxLayout()
        for how, text in (("front", "Premier plan"), ("forward", "Avancer"), ("backward", "Reculer"),
                          ("back", "Arrière")):
            row3.addWidget(_wide_button(text, text, lambda _c=False, h=how: doc.restack(ctl.scene, ctl.selection(), h),
                                        self))
        layout.addLayout(row3)
        layout.addSpacing(6)
        layout.addWidget(_label("Calques de la page (Ctrl + glisser : ordre)"))
        self.layers = LayerList(ctl, self)
        layout.addWidget(self.layers)
        layout.addStretch(1)
        self.sync()

    def sync(self):
        sel = self.ctl.selection()
        single = sel[0] if len(sel) == 1 else None
        for key, field in self.fields.items():
            field.setEnabled(single is not None and not single.locked())
            if single is None:
                field.setText("")
                continue
            value = single.rotation() if key == "rotation" else single.to_dict().get(key, 0.0)
            if not field.hasFocus():
                field.setText(f"{float(value):g}" if abs(float(value)) < 1e6 else "")
        self.layers.sync()

    def commit(self, key):
        sel = self.ctl.selection()
        if len(sel) != 1:
            return
        try:
            value = float(self.fields[key].text().replace(",", "."))
        except ValueError:
            self.sync()
            return
        item = sel[0]
        if key in ("w", "h"):
            value = max(dm.MIN_SIZE, value)
        current = item.rotation() if key == "rotation" else float(item.to_dict().get(key, 0.0))
        if abs(current - value) < 1e-6:
            return

        def mutate(i):
            i.data[key] = round(value, 2)                  # taille : autour du coin haut gauche (comme Canva)
        doc.change(self.ctl.scene, [item], mutate, "Disposition")


def build_layers(ctl, parent):
    return PositionPanel(ctl, parent)
