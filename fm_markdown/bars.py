"""Module Markdown / code : barres d'outils FLOTTANTES de fm_theme (`fm_theme.bar_manager.BarManager`, aspect = section
« Barres d'outils » de fm_theme), posées sur le panneau, au-dessus de la page.

- Barre « Markdown » : commandes de `toolbar.json` (reprise du plugin Editing Toolbar) + numéros de ligne des notes ;
  visible en édition d'une note (et si Réglages > Markdown > Barre d'outils l'affiche).
- Barre « Texte » : numéros de ligne et retour à la ligne des fichiers texte / code ; visible sur un tel fichier.
- Un clic envoie la commande à la page (message « command ») : elle agit sur la sélection dans CodeMirror. Un groupe de
  commandes (Titres, Outils de texte…) ouvre un menu de l'appli ; la couleur : clic = l'appliquer, petit triangle ou
  clic droit = la choisir.
- Les barres clipsées sur un bord réservent leur place dans la page (message « insets ») : rien n'est caché dessous.
- Disposition retenue dans `md_bars` (état temps réel). Les éléments qui ne s'appliquent pas sont cachés (une barre dont
  tout est caché disparaît)."""
from __future__ import annotations

import json
import re

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPolygonF

from fm_markdown import PACKAGE_DIR

DIVIDER = "editingToolbar-Divider-Line"
NOTE_LINE_NUMBERS = "md:note-line-numbers"
TEXT_LINE_NUMBERS = "txt:line-numbers"
TEXT_WRAP = "txt:wrap"
NOTE_SPELL = "md:spellcheck"           # orthographe (spell.py) : un bouton par barre, un seul réglage
TEXT_SPELL = "txt:spellcheck"
SPELL_TIP = ("Orthographe : souligner les fautes (avec du texte sélectionné : seulement dans la sélection) ; "
             "clic droit sur un mot souligné : corrections")
TOGGLES = {NOTE_LINE_NUMBERS: ("md_note_line_numbers", "Numéros de ligne"),
           TEXT_LINE_NUMBERS: ("md_line_numbers", "Numéros de ligne"),
           TEXT_WRAP: ("md_code_wrap", "Retour à la ligne"),
           NOTE_SPELL: ("md_spellcheck", SPELL_TIP),
           TEXT_SPELL: ("md_spellcheck", SPELL_TIP)}
TEXT_ITEMS = (TEXT_LINE_NUMBERS, TEXT_WRAP, TEXT_SPELL)
# Éléments ajoutés après coup : dans une disposition enregistrée qui ne les connaît pas, posés dans la barre de leur voisin
# (sinon la 1re barre les prendrait, et la barre « Markdown » se montrerait sur un fichier texte).
NEW_ITEM_HOMES = {NOTE_SPELL: NOTE_LINE_NUMBERS, TEXT_SPELL: TEXT_WRAP}
COLORS = {"editing-toolbar:change-font-color": ("fontColor", "md_toolbar_font_color", "Couleur du texte",
                                                "change-font-color-icon"),
          "editing-toolbar:change-background-color": ("backgroundColor", "md_toolbar_background_color",
                                                      "Couleur de fond", "change-background-color-icon")}

# Icônes des bascules (dessin au trait façon Lucide, comme celles de la barre).
_SVG_HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
             'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">')
LINE_NUMBERS_SVG = (_SVG_HEAD + '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/>'
                    '<path d="M5.5 7.5h1"/><path d="M5.5 12h1"/><path d="M5.5 16.5h1"/><path d="M12.5 7.5h5"/>'
                    '<path d="M12.5 12h5"/><path d="M12.5 16.5h3"/></svg>')
WRAP_SVG = (_SVG_HEAD + '<path d="M3 6h18"/><path d="M3 12h15a3 3 0 1 1 0 6h-4"/><path d="m16 16-2 2 2 2"/>'
            '<path d="M3 18h7"/></svg>')
SPELL_SVG = (_SVG_HEAD + '<path d="m6 16 6-12 6 12"/><path d="M8 12h8"/><path d="m16 20 2 2 4-4"/></svg>')
_TOGGLE_SVG = {TEXT_WRAP: WRAP_SVG, NOTE_SPELL: SPELL_SVG, TEXT_SPELL: SPELL_SVG}

NAMES_FR = {
    "Undo Edit": "Annuler", "Redo Edit": "Rétablir", "Format Brush": "Pinceau de format",
    "Clear Text Formatting": "Effacer la mise en forme", "Bold": "Gras", "Italic": "Italique",
    "Strikethrough": "Barré", "Underline": "Souligné", "Highlight": "Surligner", "Header 1": "Titre 1",
    "Header 2": "Titre 2", "Header 3": "Titre 3", "Header 4": "Titre 4", "Header 5": "Titre 5", "Header 6": "Titre 6",
    "submenu": "Titres", "Text Tools": "Outils de texte", "Get Plain Text": "Texte brut",
    "Full Half Converter": "Pleine / demi-chasse", "Line Operations": "Lignes", "Text Processing": "Texte",
    "Advanced Tools": "Avancé", "Insert Blank Lines": "Insérer des lignes vides",
    "Remove Blank Lines": "Retirer les lignes vides", "Split Lines": "Couper les lignes",
    "Merge Lines": "Fusionner les lignes", "Dedupe Lines": "Dédoublonner les lignes",
    "Add Prefix/Suffix": "Préfixe / suffixe", "Number Lines (Custom)": "Numéroter les lignes",
    "Trim Line Ends": "Rogner les fins de ligne", "Shrink Extra Spaces": "Compresser les espaces",
    "Remove All Whitespace": "Retirer tous les espaces", "List to Table": "Liste vers tableau",
    "Table to List": "Tableau vers liste", "Extract Between Strings": "Extraire entre deux chaînes",
    "Cut": "Couper", "Copy": "Copier", "Paste": "Coller", "Swap Line Down": "Descendre la ligne",
    "Swap Line Up": "Monter la ligne", "Attach File": "Joindre un fichier", "Insert Table": "Insérer un tableau",
    "Cycle List and Checklist": "Liste / case à cocher", "Blockquote": "Citation", "Callout": "Callout",
    "Superscript": "Exposant", "Subscript": "Indice", "Inline Code": "Code en ligne", "Code Block": "Bloc de code",
    "Wikilink": "Lien interne", "Embed": "Intégration", "Link": "Lien", "Horizontal Divider": "Séparateur",
    "Checklist": "Cocher / décocher", "Renumber Ordered List": "Renuméroter", "Ordered List": "Liste numérotée",
    "Unordered List": "Liste à puces", "Unindent List": "Désindenter", "Indent list": "Indenter",
    "Justify Text": "Justifier", "Align Text Left": "Gauche", "Center Text": "Centrer", "Align Text Right": "Droite",
    "Change Font Color": "Couleur du texte", "Change Background Color": "Couleur de fond",
}
_GROUP_NAMES = {"SubmenuCommands-header": "Titres", "SubmenuCommands-lucdf3en5": "Presse-papiers et lignes",
                "SubmenuCommands-luc8efull": "Citation et callout", "SubmenuCommands-mdcmder": "Code, liens, insertions",
                "SubmenuCommands-list": "Listes", "SubmenuCommands-aligin": "Alignement"}


def label(item: dict) -> str:
    if item.get("id") in _GROUP_NAMES:
        return _GROUP_NAMES[item["id"]]
    name = str(item.get("name") or item.get("id") or "").strip()
    return NAMES_FR.get(name, name)


_DATA: dict | None = None


def toolbar_data() -> dict:
    """`toolbar.json` (lu une fois)."""
    global _DATA
    if _DATA is None:
        try:
            _DATA = json.loads((PACKAGE_DIR / "toolbar.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _DATA = {"commands": []}
    return _DATA


def ordered_commands(data: dict) -> list[dict]:
    """Commandes de la barre dans leur ordre ; H1 sorti de son groupe, juste avant H2 (comme le plugin)."""
    items = [c for c in (data.get("commands") or []) if isinstance(c, dict) and c.get("id") != DIVIDER]
    h1_id = "editing-toolbar:header1-text"
    h1 = next((c for c in items if c.get("id") == h1_id), None)
    if h1 is None:
        for group in items:
            h1 = next((c for c in group.get("SubmenuCommands") or [] if c.get("id") == h1_id), None)
            if h1 is not None:
                break
    if h1 is not None:
        items = [c for c in items if c.get("id") != h1_id]
        at = next((i for i, c in enumerate(items) if c.get("id") == "editing-toolbar:header2-text"), len(items))
        items.insert(at, h1)
    return items


def place_new_items(state):
    """Copie de la disposition enregistrée où chaque élément de `NEW_ITEM_HOMES` qu'elle ignore (ni posé, ni en
    mémoire) rejoint la barre de son voisin ; rendue telle quelle si rien ne manque."""
    if not isinstance(state, dict) or not isinstance(state.get("bars"), list):
        return state
    bars = [b for b in state["bars"] if isinstance(b, dict) and isinstance(b.get("items"), dict)]
    memory = state.get("memory") if isinstance(state.get("memory"), dict) else {}
    missing = [k for k in NEW_ITEM_HOMES if k not in memory and not any(k in b["items"] for b in bars)]
    if not missing:
        return state
    state = json.loads(json.dumps(state))
    bars = [b for b in state["bars"] if isinstance(b, dict) and isinstance(b.get("items"), dict)]
    for key in missing:
        home = next((b for b in bars if NEW_ITEM_HOMES[key] in b["items"]), None)
        if home is not None:
            home["items"][key] = None                  # première case libre (la grille grandit s'il le faut)
    return state


def default_bars_state(keys: list[str]) -> dict:
    """Barres par défaut : « Markdown » (toutes ses icônes) et « Texte », clipsées en haut à gauche (jamais montrées
    ensemble : une note OU un fichier texte)."""
    md = [k for k in keys if k not in TEXT_ITEMS]
    return {"next": 3, "bars": [
        {"id": "b1", "title": "Markdown", "dock": "top", "orient": "h", "along": 0, "x": 0, "y": 0,
         "cols": max(1, len(md)), "rows": 1, "items": {k: [i, 0, 1] for i, k in enumerate(md)}},
        {"id": "b2", "title": "Texte", "dock": "top", "orient": "h", "along": 0, "x": 0, "y": 0,
         "cols": len(TEXT_ITEMS), "rows": 1, "items": {k: [i, 0, 1] for i, k in enumerate(TEXT_ITEMS)}}]}


# -- Icônes ------------------------------------------------------------------------------------------------------------

def _css_rgba(value: str) -> tuple[str, float]:
    """Couleur CSS (« #rrggbbaa » possible) -> (« #rrggbb », opacité)."""
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{8}", text):
        return "#" + text[1:7], int(text[7:9], 16) / 255
    color = QColor(text)
    return (color.name(), color.alphaF()) if color.isValid() else ("#000000", 1.0)


def qcolor(value: str) -> QColor:
    rgb, alpha = _css_rgba(value)
    color = QColor(rgb)
    color.setAlphaF(alpha)
    return color


_RENDERERS: dict = {}


def _renderer(svg: str):
    renderer = _RENDERERS.get(svg)
    if renderer is None:
        from PySide6.QtSvg import QSvgRenderer
        renderer = _RENDERERS[svg] = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if len(_RENDERERS) > 400:
            _RENDERERS.clear()
    return renderer


def paint_svg(painter: QPainter, rect: QRectF, svg: str, color: QColor, swatch: tuple | None = None) -> bool:
    """Peint une icône SVG de la barre (« currentColor » = `color`, passée par `ink` : magenta provisoire) ; `swatch` =
    (id de l'élément, couleur CSS) : pastille de la couleur active, gardée TELLE QUELLE."""
    from fm_theme.placeholder import ink
    shown = ink(color)
    text = svg.replace("currentColor", shown.name())
    if swatch is not None:
        rgb, alpha = _css_rgba(swatch[1])
        text = re.sub(r'(id="%s"[^>]*?style=")[^"]*"' % re.escape(swatch[0]),
                      lambda m: f'{m.group(1)}fill:{rgb};fill-opacity:{alpha:.3f}"', text)
    renderer = _renderer(text)
    if not renderer.isValid():
        return False
    size = renderer.defaultSize()

    def draw(p: QPainter, frame: QRectF) -> None:
        target = QRectF(frame)
        if size.width() > 0 and size.height() > 0 and size.width() != size.height():   # proportions gardées
            ratio = size.width() / size.height()
            if ratio < 1:
                target.setWidth(frame.height() * ratio)
            else:
                target.setHeight(frame.width() / ratio)
            target.moveCenter(frame.center())
        renderer.render(p, target)
    from fm_theme.icon_frame import paint_framed
    painter.save()
    painter.setOpacity(painter.opacity() * shown.alphaF())
    paint_framed(painter, QRectF(rect), draw, key=("md-svg", text))     # cadre des icônes (Thème > Général)
    painter.restore()
    return True


def _text_glyph(text: str):
    def glyph(painter: QPainter, rect: QRectF, color: QColor) -> None:
        from fm_theme.placeholder import ink
        font = QFont(painter.font())
        font.setBold(True)
        font.setPixelSize(max(6, int(rect.height() * 0.62)))
        painter.setFont(font)
        painter.setPen(ink(color))
        painter.drawText(rect, Qt.AlignCenter, text)
    return glyph


def item_glyph(item: dict):
    svg = item.get("icon") if isinstance(item.get("icon"), str) else ""
    if svg and re.match(r"\s*<svg", svg):
        return lambda painter, rect, color: paint_svg(painter, rect, svg, color)
    m = re.search(r"header(\d)-text", item.get("id") or "")
    return _text_glyph(f"H{m.group(1)}" if m else label(item)[:2])


def _paint_caret(painter: QPainter, rect: QRectF, color: QColor) -> None:
    """Petit triangle dans le coin bas-droit : l'élément ouvre un menu."""
    from fm_theme.placeholder import ink
    s = max(3.0, rect.width() * 0.13)
    x, y = rect.right() - s * 0.6, rect.bottom() - s * 0.6
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(ink(color))
    painter.drawPolygon(QPolygonF([QPointF(x - s, y - s / 2), QPointF(x, y - s / 2), QPointF(x - s / 2, y + s / 4)]))
    painter.restore()


def entry_icon(entry: dict, ratio: float) -> QIcon | None:
    """Icône d'une ligne de menu : pastille de couleur, ou icône SVG de la barre d'outils."""
    size = 16
    if entry.get("id") == "editing-toolbar:codeblock":
        from fm_theme import icon_library
        style = icon_library.style_affiche()
        officiel = icon_library.pixmap_cadre("modules/markdown/bloc_code_03", size, ratio, style=style,
                                             teinte=None if style == icon_library.COULEUR else icon_library.encre_defaut())
        if officiel is not None:
            return QIcon(officiel)
    if not entry.get("color") and not entry.get("svg"):
        return None
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    ok = True
    if entry.get("color"):
        painter.setBrush(qcolor(str(entry["color"])))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    else:
        ok = paint_svg(painter, QRectF(0, 0, size, size), str(entry["svg"]), QColor("#ffffff"))
    painter.end()
    return QIcon(pixmap) if ok else None


def run_menu(parent, entries: list, global_pos: QPoint) -> int:
    """Menu de l'appli (habillage des réglages) ; rang de la ligne choisie parmi les lignes cliquables, ou -1."""
    from settings_menu import Menu, _section_action
    menu = Menu(parent, key="mdeditor:toolbar", editable=False)
    actions = []
    for entry in entries or []:
        if entry == "-":
            menu.addSeparator()
            continue
        if isinstance(entry, dict) and entry.get("section"):
            menu.addAction(_section_action(menu, entry["section"]))
            continue
        action = menu.addAction(str(entry.get("title", "")))
        icon = entry_icon(entry, parent.devicePixelRatioF())
        if icon is not None:
            action.setIcon(icon)
        actions.append(action)
    chosen = menu.exec(global_pos)
    menu.deleteLater()
    return actions.index(chosen) if chosen in actions else -1


# -- Éléments ----------------------------------------------------------------------------------------------------------

def _button_classes():
    from fm_theme.palette import PaletteButton

    class MenuButton(PaletteButton):
        """Groupe de commandes : un menu au clic (triangle dans le coin)."""

        def _paint_content(self, painter):
            super()._paint_content(painter)
            from fm_theme.palette import LOOK
            _paint_caret(painter, QRectF(self.rect()), QColor(self.ink or LOOK["icon_ink"]))

    class ColorButton(PaletteButton):
        """Couleur du texte / de fond : clic = appliquer la couleur active (pastille de l'icône) ; clic sur le triangle
        ou clic droit = la choisir."""

        def __init__(self, key, tip, svg, swatch_id, color, parent=None):
            super().__init__(key, tip, self._glyph, parent)
            self.svg, self.swatch_id, self.color = svg, swatch_id, color
            self.caret_hit = False
            self.pick = None                       # posé par la barre : ouvre le sélecteur

        def _glyph(self, painter, rect, color):
            paint_svg(painter, rect, self.svg, color, (self.swatch_id, self.color))

        def set_color(self, color: str) -> None:
            if color != self.color:
                self.color = color
                self.update()

        def extra_key(self):
            return (self.color,)

        def mousePressEvent(self, event):
            p = event.position()
            self.caret_hit = p.x() > self.width() * 0.66 and p.y() > self.height() * 0.6
            super().mousePressEvent(event)

        def contextMenuEvent(self, event):
            if self.pick is not None:
                self.pick()

        def _paint_content(self, painter):
            super()._paint_content(painter)
            from fm_theme.palette import LOOK
            _paint_caret(painter, QRectF(self.rect()), QColor(self.ink or LOOK["icon_ink"]))

    return PaletteButton, MenuButton, ColorButton


class MarkdownBars(QObject):
    """Les barres du panneau (`pane` : `MarkdownPane`)."""

    def __init__(self, pane, settings: dict):
        super().__init__(pane)
        from fm_theme.bar_manager import BarManager
        self.pane = pane
        self.manager = BarManager(pane)
        self.buttons: dict = {}
        self.colors = {"fontColor": str(settings.get("md_toolbar_font_color") or toolbar_data().get("fontColor") or "#D83931"),
                       "backgroundColor": str(settings.get("md_toolbar_background_color")
                                              or toolbar_data().get("backgroundColor") or "#FFB78B8C")}
        self._insets = None
        self._watched: set = set()
        self._inset_timer = QTimer(self)
        self._inset_timer.setSingleShot(True)
        self._inset_timer.setInterval(0)
        self._inset_timer.timeout.connect(self.push_insets)
        self.apply_look(settings)
        self._build()
        self.manager.default_state = default_bars_state(list(self.buttons))
        saved = settings.get("md_bars")
        self.manager.restore(place_new_items(saved) if isinstance(saved, dict) and saved.get("bars") else None)
        self.manager.layoutChanged.connect(self._save)
        self.manager.layoutChanged.connect(self._watch_bars)
        self.sync(settings)

    def _build(self) -> None:
        PaletteButton, MenuButton, ColorButton = _button_classes()
        for item in ordered_commands(toolbar_data()):
            key = str(item.get("id"))
            if key in COLORS:
                field, _setting, title, swatch = COLORS[key]
                b = ColorButton(key, label(item) + " (triangle ou clic droit : choisir)", str(item.get("icon") or ""),
                                swatch, self.colors[field])
                b.pick = lambda k=key: self.pick_color(k)
                b.clicked.connect(lambda _c=False, k=key, w=b: self.pick_color(k) if w.caret_hit else self.command(k))
            elif item.get("SubmenuCommands"):
                b = MenuButton(key, label(item), item_glyph(item))
                b.clicked.connect(lambda _c=False, it=item, w=b: self.open_group(it, w))
            else:
                b = PaletteButton(key, label(item), item_glyph(item))
                b.clicked.connect(lambda _c=False, k=key: self.command(k))
            self._register(key, b)
        for key in (NOTE_LINE_NUMBERS, NOTE_SPELL, *TEXT_ITEMS):
            svg = _TOGGLE_SVG.get(key, LINE_NUMBERS_SVG)
            b = PaletteButton(key, TOGGLES[key][1], lambda p, r, c, s=svg: paint_svg(p, r, s, c))
            b.clicked.connect(lambda _c=False, k=key: self.toggle(k))
            self._register(key, b)

    def _register(self, key: str, button) -> None:
        self.buttons[key] = button
        self.manager.register(key, button)

    @staticmethod
    def apply_look(settings: dict) -> None:
        """Aspect STANDARD des barres de fm_theme (section « Barres d'outils », clés `palette_*` du thème en usage).
        L'habillage commun (`palette.LOOK`) n'était posé qu'à l'ouverture du Board ou au changement des réglages : sans
        lui, un module ouvert avant le Board gardait les dimensions du prototype. Rien n'est refait s'il n'a pas changé."""
        from fm_theme.palette import restyle_palettes_in
        restyle_palettes_in(None, settings)

    # -- état du panneau -----------------------------------------------------------------------------------------------
    def sync(self, settings: dict | None = None) -> None:
        """Éléments montrés selon le fichier ouvert et le mode ; bascules à jour. Rien n'est refait si rien ne change."""
        from fm_markdown.pane import _settings
        s = settings if settings is not None else _settings()
        self.apply_look(s)
        pane = self.pane
        opened = pane.path is not None
        note = opened and pane.kind == "markdown" and pane.mode == "edit" and bool(s.get("md_toolbar_enabled", True))
        text = opened and pane.kind == "code"
        changed = False
        for key, b in self.buttons.items():
            shown = text if key in TEXT_ITEMS else note
            if key == TEXT_SPELL:
                from fm_markdown.spell import checks
                shown = shown and checks(pane.path)        # texte oui, code non
            if shown == b.isHidden():
                b.setVisible(shown)
                changed = True
            if key in TOGGLES:
                b.set_active(bool(s.get(TOGGLES[key][0])) or (key in (NOTE_SPELL, TEXT_SPELL) and pane.spell_zone))
        if changed:
            self.manager.sync_visibility()
            self._watch_bars()
            self._inset_timer.start()

    def set_active(self, key: str, active: bool) -> None:
        b = self.buttons.get(key)
        if b is not None:
            b.set_active(active)

    # -- actions -------------------------------------------------------------------------------------------------------
    def command(self, key: str) -> None:
        self.pane._push({"type": "command", "id": key, "colors": dict(self.colors)})

    def open_group(self, item: dict, anchor) -> None:
        entries, ids = [], []
        for child in item.get("SubmenuCommands") or []:
            if child.get("id") == DIVIDER:
                entries.append("-")
                continue
            svg = child.get("icon") if isinstance(child.get("icon"), str) and re.match(r"\s*<svg", child["icon"]) else None
            entries.append({"title": label(child), "svg": svg, "id": child.get("id")})
            ids.append(str(child.get("id")))
        anchor.set_active(True)
        try:
            index = run_menu(self.pane, entries, anchor.mapToGlobal(anchor.rect().bottomLeft()))
        finally:
            anchor.set_active(False)
        if 0 <= index < len(ids):
            self.command(ids[index])

    def pick_color(self, key: str) -> None:
        from settings_widgets import _ColorPickerPopup
        field, setting, title, _swatch = COLORS[key]
        button = self.buttons[key]
        popup = _ColorPickerPopup(self.colors[field], title, self.pane)

        def committed(value):
            popup.deleteLater()
            color = QColor(str(value))
            if not color.isValid():
                return
            text = str(value)
            self.colors[field] = text
            button.set_color(text)
            saver = _hooks().get("save_state")
            if saver is not None:
                saver(setting, color.name(QColor.NameFormat.HexArgb) if color.alpha() < 255 else color.name())
            self.command(key)
        popup.committed.connect(committed)
        popup.cancelled.connect(popup.deleteLater)
        popup.show_near(button)

    def set_spell_active(self, active: bool) -> None:
        for key in (NOTE_SPELL, TEXT_SPELL):
            self.set_active(key, active)

    def toggle(self, key: str) -> None:
        """Numéros de ligne / retour à la ligne : le réglage bascule, appliqué aussitôt à la page. Orthographe : le
        panneau décide (document entier ou sélection, `MarkdownPane.toggle_spell`)."""
        if key in (NOTE_SPELL, TEXT_SPELL):
            self.pane.toggle_spell()
            return
        from fm_markdown.pane import _settings
        setting = TOGGLES[key][0]
        settings = _settings()
        value = not bool(settings.get(setting))
        if isinstance(settings, dict):
            settings[setting] = value
        saver = _hooks().get("save_state")
        if saver is not None:
            saver(setting, value)
        self.buttons[key].set_active(value)
        self.pane._push_style({**settings, setting: value})

    # -- place réservée dans la page -------------------------------------------------------------------------------------
    def _watch_bars(self) -> None:
        for bar in self.manager.bars:
            if id(bar) not in self._watched:
                self._watched.add(id(bar))
                bar.installEventFilter(self)
                bar.destroyed.connect(lambda _o=None, i=id(bar): self._watched.discard(i))
        self._inset_timer.start()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide):
            self._inset_timer.start()
        return False

    def insets(self) -> dict:
        """Place prise par les barres clipsées visibles, sur chaque bord de la page (px CSS : zoom de la page compris)."""
        view = self.pane.view.geometry()
        out = {"top": 0, "left": 0, "right": 0, "bottom": 0}
        for bar in self.manager.bars:
            if bar.isHidden() or not bar.dock:
                continue
            g = bar.geometry()
            depth = {"top": g.bottom() + 1 - view.top(), "bottom": view.bottom() + 1 - g.top(),
                     "left": g.right() + 1 - view.left(), "right": view.right() + 1 - g.left()}[bar.dock]
            out[bar.dock] = max(out[bar.dock], depth)
        zoom = self.pane.view.zoomFactor() or 1.0
        return {k: max(0, round(v / zoom)) for k, v in out.items()}

    def push_insets(self, force: bool = False) -> None:
        insets = self.insets()
        if insets != self._insets or force:
            self._insets = insets
            self.pane.place_grips()
            if self.pane._page_ready:
                self.pane._push({"type": "insets", "insets": insets})

    def _save(self) -> None:
        state = self.manager.state()
        from fm_markdown.pane import _settings
        settings = _settings()
        if isinstance(settings, dict):
            settings["md_bars"] = state
        saver = _hooks().get("save_state")
        if saver is not None:
            saver("md_bars", state)
        self._inset_timer.start()


def _hooks() -> dict:
    from fm_markdown.pane import HOOKS
    return HOOKS
