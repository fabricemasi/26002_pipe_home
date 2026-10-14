"""« Override settings » : style PROPRE a un element construit avec les briques des reglages.

Partout ou un clic droit propose « Ajouter une espace au-dessus / en dessous » (fenetre de reglages,
fenetre principale, lignes des colonnes), une ligne « Override settings… » suit (sous-menu quand
plusieurs elements sont sous le clic : le texte, son tableau, son titre...). Elle ouvre la fenetre
« Changement de style a la volee » avec TOUT ce qui compose l'element, plus ses deux espaces (au-dessus /
en dessous). Les valeurs ne s'appliquent qu'a CET element et sont enregistrees aussitot ; « Retirer
l'override » rend le style general.

Elements (une classe *Target chacun : identifiant stable, lignes, valeurs, application en direct) :
- tableau  `table:<cle de dimensions>`  : Reglages > Tableaux (apparence) + couleurs de fond + police
  du texte ; sur une cellule, le menu demande la PORTEE : cellule / ligne / colonne en cours ou
  tableau entier (`table:<cle>::cell:r<l>c<c>` / `::row:<l>` / `::col:<c>`, indices LOGIQUES : fond,
  padding, police ; cellule > ligne > colonne > tableau, champ par champ, settings_widgets.PART_LOOKS) ;
  colonne et tableau ne touchent pas l'entete ; clic dans l'entete = portees « Cellule en cours »
  (`table:<cle>::head:c<c>`, le titre clique : fond et police) et « Entete entier »
  (`table:<cle>::head` : couleur de fond et police des titres de l'entete) ;
- titre    `title:<onglet|title:chemin>` (fenetre v2) : police de son niveau + Paragraphes > Niveau N ;
- texte    `text:<fenetre>:<chemin>`     : police, gras, italique, hauteur, lissage, couleur, padding ;
- toggle   `toggle:<identifiant>`        : Type / Cadre / Coche de son style (style cache, propre a lui) ;
- colonne  (fenetre principale, fournie par l'appli : TARGET_RESOLVERS) : les tableaux de son onglet de
  surcharge, ecrits dans les surcharges de colonne existantes.
Les quatre premiers sont enregistres dans `element_style_overrides` ({identifiant : valeurs}, etat
temps reel de _LIVE_STATE_KEYS) et reappliques a la construction / apres un restylage general
(`apply_saved(fenetre)`). Couche reglages : rien de propre a l'appli ; l'appli est prevenue par
add_listener (cle, valeur) a chaque enregistrement."""
from __future__ import annotations

import copy
import weakref

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontInfo
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QComboBox, QLabel, QLineEdit, QMenu, QPlainTextEdit, QTextEdit, QWidget,
)

from settings_layout import _flat_tables, set_table_look
from settings_store import _coerce_side_enabled, _resolve_color_value, load_settings, save_settings
from settings_widgets import (
    CONTEXT_MENU_FINAL, ELEMENT_LOOKS, PART_LOOKS, SPACE_ABOVE_TEXT, SPACE_BELOW_TEXT, SPACE_MENU_HOOKS,
    _TableFrame, _Toggle, widget_at_path, widget_path,
)

KEY = "element_style_overrides"
SAVED_LISTENERS: list = []          # references (faibles) de rappels (cle, valeur), voir add_listener
TARGET_RESOLVERS: list = []         # rappels (widget) -> [Target] fournis par l'appli (colonnes...)
_SPACE_KEYS = ("__space_above", "__space_below")
_ROW_TEXT_CACHE_READY = False
_ROW_MODEL_CACHE = {}


def _row_index(view, path: str):
    """Index des chemins construit une fois par version de modèle, pas une fois par texte."""
    from browser_core import ROLE_PATH
    model = view.model()
    count = model.rowCount()
    key = id(view)
    if getattr(view, "_row_text_cache_model", None) is not model:
        invalidate = lambda *_args, cache_key=key: _ROW_MODEL_CACHE.pop(cache_key, None)
        for signal_name in ("modelReset", "rowsInserted", "rowsRemoved", "dataChanged"):
            signal = getattr(model, signal_name, None)
            if signal is not None:
                signal.connect(invalidate)
        view._row_text_cache_model = model
    entry = _ROW_MODEL_CACHE.get(key)
    if entry is None or entry[0] != id(model) or entry[1] != count:
        cached = {}
        for row in range(count):
            index = model.index(row, 0)
            cached[str(index.data(ROLE_PATH) or index.row())] = index
        _ROW_MODEL_CACHE[key] = (id(model), count, cached)
    else:
        cached = entry[2]
    return cached.get(str(path))


def _column_for_view(view):
    """La liste est réhébergée sous la carte de la colonne après sa création."""
    column = getattr(view.itemDelegate(), "column", None)
    if column is not None and getattr(column, "style_title", None):
        return column
    node = view.parentWidget()
    while node is not None and not getattr(node, "style_title", None):
        node = node.parentWidget()
    return node


def text_of(widget: QWidget) -> str:
    """Texte visible d'un contrôle, y compris l'invite d'un champ vide."""
    if isinstance(widget, QLabel):
        return widget.text().strip()
    if isinstance(widget, (QAbstractButton, QComboBox, QAbstractSpinBox)):
        if isinstance(widget, QAbstractSpinBox):
            line = widget.lineEdit()
            value = (line.text() or line.placeholderText()) if line is not None else ""
        else:
            value = widget.text() if hasattr(widget, "text") else widget.currentText()
        return str(value or "").strip()
    if isinstance(widget, QLineEdit):
        return (widget.text() or widget.placeholderText() or "").strip()
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return (widget.toPlainText() or widget.placeholderText() or "").strip()
    return ""


def is_text_widget(widget) -> bool:
    return isinstance(widget, (QLabel, QAbstractButton, QComboBox, QAbstractSpinBox,
                               QLineEdit, QPlainTextEdit, QTextEdit)) and bool(text_of(widget))


def _publish_row_text_overrides(overrides: dict | None) -> None:
    global _ROW_TEXT_CACHE_READY
    import ui_state
    overrides = overrides or {}
    ui_state.ROW_TEXT_OVERRIDES = {
        key: value for key, value in overrides.items()
        if key.startswith("row-text:") and value
    }
    ui_state.GALLERY_STYLE_OVERRIDES = {
        key: value for key, value in overrides.items()
        if key.startswith("gallery-") and value
    }
    _ROW_TEXT_CACHE_READY = True


def ensure_row_text_overrides() -> None:
    """Charge une seule fois le cache peint des libellés de colonnes."""
    global _ROW_TEXT_CACHE_READY
    if not _ROW_TEXT_CACHE_READY:
        _publish_row_text_overrides(load_settings().get(KEY) or {})
        _ROW_TEXT_CACHE_READY = True


def add_listener(callback) -> None:
    """Prevenu (cle, valeur) a chaque enregistrement ; une methode est gardee par reference faible."""
    ref = weakref.WeakMethod(callback) if hasattr(callback, "__self__") else (lambda cb=callback: cb)
    SAVED_LISTENERS.append(ref)


def _notify(key: str, value) -> None:
    for ref in list(SAVED_LISTENERS):
        callback = ref()
        if callback is None:
            SAVED_LISTENERS.remove(ref)
            continue
        try:
            callback(key, copy.deepcopy(value))
        except RuntimeError:            # fenetre detruite
            SAVED_LISTENERS.remove(ref)


def merged(settings: dict, override: dict | None) -> dict:
    """Reglages generaux + valeurs d'un element (couleurs fondues cle par cle)."""
    out = dict(settings)
    override = override or {}
    out.update({k: v for k, v in override.items() if k != "colors"})
    out["colors"] = {**(settings.get("colors") or {}), **(override.get("colors") or {})}
    return out


def _fold_colors(values: dict) -> dict:
    """Valeurs lues dans la fenetre (`colors:<cle>` a part) -> forme des reglages."""
    out = {k: v for k, v in values.items() if not k.startswith("colors:")}
    colors = {k[len("colors:"):]: v for k, v in values.items() if k.startswith("colors:")}
    if colors:
        out["colors"] = colors
    return out


def _normalized(specs: list, values: dict) -> dict:
    """`values` relues comme les champs les relisent (formes normalisees : bordures, coins...) : la
    reference a laquelle comparer ce que la fenetre d'override renvoie."""
    import settings_window_v2 as v2
    scope = v2.ScopeValues(values, None)
    out = {}
    for spec in specs:
        widget = v2.make_field(spec, scope, values.get("colors") or {})
        try:
            out.update(v2.read_spec(spec, widget))
        finally:
            widget.deleteLater()
    return out


def _diff(general: dict, values: dict) -> dict:
    """Ce qui differe du general (seul garde comme override). `general` : valeurs generales relues par
    les memes champs (_normalized), cles `colors:<cle>` comprises."""
    out, colors = {}, {}
    for key, value in values.items():
        if key in _SPACE_KEYS:
            continue
        if key.startswith("colors:"):
            real = key[len("colors:"):]
            reference = general[key] if key in general else (general.get("colors") or {}).get(real)
            if value != reference:
                colors[real] = value
        elif value != general.get(key):
            out[key] = value
    if colors:
        out["colors"] = colors
    return out


def save_override(element: str, override: dict | None) -> None:
    """Enregistre aussitot l'override de `element` (vide / None = retire)."""
    settings = load_settings()
    overrides = dict(settings.get(KEY) or {})
    if override:
        overrides[element] = override
    else:
        overrides.pop(element, None)
    settings[KEY] = overrides
    save_settings(settings)
    _publish_row_text_overrides(overrides)
    _notify(KEY, overrides)


def update_text_overrides(changes: list[tuple["TextTarget", dict | None]]) -> None:
    """Enregistre en une fois des overrides de texte et restaure aussitot leur apparence visible."""
    changes = [(target, copy.deepcopy(values) if values else None) for target, values in changes
               if isinstance(target, TextTarget)]
    if not changes:
        return
    settings = load_settings()
    overrides = dict(settings.get(KEY) or {})
    for target, values in changes:
        if isinstance(target, RowTextTarget):
            overrides.pop(target.legacy_element, None)
        if values:
            overrides[target.element] = values
        else:
            overrides.pop(target.element, None)
    settings[KEY] = overrides
    save_settings(settings)
    _publish_row_text_overrides(overrides)
    _notify(KEY, overrides)
    for target, values in changes:
        try:
            if isinstance(target, GalleryStyleTarget):
                target.apply(values)
            else:
                target.apply(merged(target.general(settings), values) if values else None)
        except RuntimeError:
            continue


def _saved(element: str) -> dict:
    return dict((load_settings().get(KEY) or {}).get(element) or {})


def _scope_of(window: QWidget) -> str:
    return type(window).__name__


def _ancestor(widget, kinds):
    node = widget
    while node is not None and not isinstance(node, kinds):
        node = node.parentWidget()
    return node


# ==========================================================================
# Elements
# ==========================================================================

class Target:
    """Un element sous le clic. `element` : identifiant stable ; `widget` : l'element lui-meme."""

    kind = "Élément"
    stored = True                      # valeurs dans `element_style_overrides`

    def __init__(self, element: str, widget: QWidget, label: str):
        self.element, self.widget, self.label = element, widget, label

    def specs(self) -> list:
        raise NotImplementedError

    def general(self, settings: dict) -> dict:
        """Valeurs generales de l'element (sans son override)."""
        return settings

    def values(self, settings: dict) -> dict:
        return merged(self.general(settings), _saved(self.element))

    def has_override(self) -> bool:
        return bool(_saved(self.element))

    def save(self, values: dict) -> None:
        settings = load_settings()
        general = self.general(settings)
        override = _diff(_normalized(self.specs(), general), values)
        save_override(self.element, override)
        self.apply(merged(general, override) if override else None)

    def remove(self) -> None:
        save_override(self.element, None)
        self.apply(None)

    def apply(self, values: dict | None) -> None:
        """Pose `values` sur l'element (None : style general)."""
        raise NotImplementedError


# -- Tableau ------------------------------------------------------------------

_TABLE_BEHAVIOUR = ("columns_resizable", "table_rows_movable")
_TABLE_COLOR_SLOTS = ("table_row",)
# L'entete est a part (« Entete entier ») : le tableau entier ne le touche pas.
_HEAD_KEYS = ("table_head_color",)
_HEAD_COLOR_SLOTS = ("table_head",)


def table_state(values: dict) -> dict:
    """Etat resolu d'un tableau (conteneurs de settings_layout.table_look_scope)."""
    import settings_window_v2 as v2
    colors = values.get("colors") or {}
    inner = {axis: {"enabled": bool(values.get(f"table_inner_{axis}_enabled", True)),
                    "color": _resolve_color_value(values.get(f"table_inner_{axis}_color", ""), colors),
                    "thickness": max(0, int(values.get(f"table_inner_{axis}_thickness", 1) or 0))}
             for axis in ("h", "v")}
    border = (_coerce_side_enabled(values.get("table_border_enabled", True)),
              {k: _resolve_color_value(v, colors) for k, v in (values.get("table_border") or {}).items()},
              int(values.get("table_border_thickness", 1)))
    state = {
        "flat": {"radius": int(values.get("table_radius", 0)), "border": border,
                 "padding": v2._padding_tuple(values.get("table_cell_padding") or {})},
        "head": {"bg": v2._head_hex(colors, values.get("table_head_color", "tableHead")),
                 "cell_bg": v2._head_hex(colors, values.get("table_cell_head_color", "tableHead"))},
        "selection": {"color": _resolve_color_value(values.get("table_selection_color", "#5f9bd0"), colors)},
        "inner": inner,
        "M": {},
    }
    if colors.get("table_head"):
        state["M"]["table_head_bg"] = colors["table_head"]
    if colors.get("table_row"):
        state["M"]["table_row_a"] = state["M"]["table_row_b"] = colors["table_row"]
    return state


def table_id(frame: _TableFrame) -> str:
    return f"table:{frame.dimsKey()}"


def _table_look_values(settings: dict, dims_key: str) -> dict | None:
    """Valeurs d'apparence du tableau `dims_key` : son override (« Tableau entier sauf entete »), la
    couleur de l'entete venant seulement de l'override « Entete entier ». None : aucun des deux."""
    overrides = settings.get(KEY) or {}
    table = overrides.get(f"table:{dims_key}") or {}
    head = overrides.get(f"table:{dims_key}{PART_SEP}head") or {}
    if not table and not head:
        return None
    out, head_values = merged(settings, table), merged(settings, head)
    for key in _HEAD_KEYS:
        if key in head_values:
            out[key] = head_values[key]
        else:
            out.pop(key, None)
    for slot in _HEAD_COLOR_SLOTS:
        if slot in head_values["colors"]:
            out["colors"][slot] = head_values["colors"][slot]
        else:
            out["colors"].pop(slot, None)
    return out


def _refresh_table(dims_key: str) -> None:
    """Reapplique aux tableaux vivants de `dims_key` leur apparence, leurs parties et leur entete."""
    settings = load_settings()
    _refresh_parts(dims_key, settings)
    values = _table_look_values(settings, dims_key)
    element = f"table:{dims_key}"
    state = table_state(values) if values else None
    if state:
        ELEMENT_LOOKS[element] = state
    else:
        ELEMENT_LOOKS.pop(element, None)
    for frame in _flat_tables():           # tous les tableaux vivants de cet identifiant (lies compris)
        try:
            if isinstance(frame, _TableFrame) and table_id(frame) == element:
                set_table_look(frame, state)
        except RuntimeError:
            continue


# -- Police du texte d'un tableau, parties d'un tableau (cellule / ligne / colonne) -----------------

TEXT_PREFIX = "table_text"
PART_SEP = "::"


def _font_spec():
    """Ligne « police » (gabarit des reglages) : cles `table_text_font_*`, hauteur en px."""
    from settings_quick_style import font_padding_specs
    return font_padding_specs(TEXT_PREFIX, size=(6, 48), size_default=12, color_title="Couleur du texte")[0]


def _cell_border_specs():
    import settings_window_v2 as v2
    return [v2.Spec(
        "table_cell_border_enabled", "Bordures des cellules", "sides_thick", False,
        {"colors_key": "table_cell_border", "thickness_key": "table_cell_border_thickness",
         "width": 90, "box": 54},
        extra_keys=("table_cell_border", "table_cell_border_thickness"),
    )]


def _font_seed() -> dict:
    """Valeurs « generales » de la police d'un tableau : celles des libelles (role row_label). Seul ce
    qui en DIFFERE est garde, et seul ce qui est garde change le texte (taille seule, gras seul...)."""
    from settings_store import M
    p = f"{TEXT_PREFIX}_font_"
    return {f"{p}family": "", f"{p}bold": False, f"{p}italic": False, f"{p}size": 12,
            f"{p}smoothing_enabled": False, f"{p}smoothing": "current", f"{p}color": M.get("row_label", "#d6d9dc")}


def font_look(override: dict, colors: dict) -> dict:
    """Police propre (settings_theme.text_look_font) tiree d'un override : seulement ce qu'il change."""
    p = f"{TEXT_PREFIX}_font_"
    look = {}
    if override.get(f"{p}family"):
        look["family"] = override[f"{p}family"]
    for name in ("bold", "italic", "size"):
        if f"{p}{name}" in override:
            look[name] = override[f"{p}{name}"]
    if f"{p}smoothing_enabled" in override or f"{p}smoothing" in override:
        values = {**_font_seed(), **override}
        if values[f"{p}smoothing_enabled"] and values[f"{p}smoothing"] != "current":
            look["smoothing"] = values[f"{p}smoothing"]
    if override.get(f"{p}color"):
        look["color"] = _resolve_color_value(override[f"{p}color"], colors)
    return look


def part_look(override: dict, colors: dict) -> dict:
    """Fond, padding, bordures et police propres d'une cellule / ligne / colonne."""
    import settings_window_v2 as v2
    look = {}
    bg = (override.get("colors") or {}).get("table_row")
    if bg:
        look["bg"] = _resolve_color_value(bg, colors)
    if override.get("table_cell_padding"):
        look["padding"] = v2._padding_tuple(override["table_cell_padding"])
    if override.get("table_cell_border_enabled"):
        look["border"] = {
            "enabled": _coerce_side_enabled(override["table_cell_border_enabled"]),
            "colors": {side: _resolve_color_value(color, colors)
                       for side, color in (override.get("table_cell_border") or {}).items()},
            "thickness": max(1, int(override.get("table_cell_border_thickness", 1) or 1)),
        }
    font = font_look(override, colors)
    if font:
        look["font"] = font
    return look


def head_cell_look(override: dict, colors: dict) -> dict | None:
    """Fond et police propres d'un titre de l'entete (Cellule en cours, dans l'entete)."""
    import settings_window_v2 as v2
    look = {}
    bg = (override.get("colors") or {}).get("table_head")
    if bg:
        look["bg"] = _resolve_color_value(bg, colors)
    elif override.get("table_head_color"):
        look["bg"] = v2._head_hex(colors, override["table_head_color"])
    font = font_look(override, colors)
    if font:
        look["font"] = font
    return look or None


def _part_key(part: tuple) -> str:
    if part[0] == "head":
        return "head"
    if part[0] == "headcell":
        return f"head:c{part[1]}"
    return f"cell:r{part[1]}c{part[2]}" if part[0] == "cell" else f"{part[0]}:{part[1]}"


def _parse_part(text: str) -> tuple | None:
    if text == "head":
        return ("head",)
    if text.startswith("head:c"):
        try:
            return ("headcell", int(text[len("head:c"):]))
        except ValueError:
            return None
    try:
        kind, rest = text.split(":", 1)
        if kind == "cell":
            r, c = rest[1:].split("c")
            return ("cell", int(r), int(c))
        if kind in ("row", "col"):
            return (kind, int(rest))
    except ValueError:
        pass
    return None


def _parts_of(settings: dict, dims_key: str) -> dict:
    """Styles propres des parties du tableau `dims_key` (et police du tableau entier)."""
    prefix, colors = f"table:{dims_key}", settings.get("colors") or {}
    out = {}
    for element, override in (settings.get(KEY) or {}).items():
        if not override:
            continue
        if element == prefix:
            look = part_look(override, colors)
            font = font_look(override, colors)
            if font:
                look["font"] = font
            if look:
                out[("table",)] = look
        elif element.startswith(prefix + PART_SEP):
            part = _parse_part(element[len(prefix) + len(PART_SEP):])
            if part == ("head",):                # entete : sa police seulement (son fond : table_state)
                font = font_look(override, colors)
                look = {"font": font} if font else None
            elif part and part[0] == "headcell":       # titre de l'entete : fond et police
                look = head_cell_look(override, colors)
            else:
                look = part_look(override, colors) if part else None
            if look:
                out[part] = look
    return out


def _refresh_parts(dims_key: str, settings: dict | None = None) -> None:
    """Relit les parties de `dims_key` et les pose sur ses tableaux vivants (tableaux lies compris)."""
    from settings_layout import apply_part_looks
    parts = _parts_of(settings if settings is not None else load_settings(), dims_key)
    if parts:
        PART_LOOKS[dims_key] = parts
    else:
        PART_LOOKS.pop(dims_key, None)
    for frame in _flat_tables():
        try:
            if isinstance(frame, _TableFrame) and frame.dimsKey() == dims_key:
                apply_part_looks(frame)
        except RuntimeError:
            continue


class TableTarget(Target):
    kind = "Tableau"

    def specs(self) -> list:
        import settings_window_v2 as v2
        specs = [sp for sp in v2.CATALOG["Tableaux"] if sp.key not in _TABLE_BEHAVIOUR + _HEAD_KEYS]
        specs += [sp for sp in v2.CATALOG["Couleurs"] if sp.params.get("real_key") in _TABLE_COLOR_SLOTS]
        specs += _cell_border_specs()
        return specs + [_font_spec()]

    def general(self, settings: dict) -> dict:
        return {**settings, **_font_seed()}

    def cell_specs(self) -> list:
        import settings_window_v2 as v2
        bg = [sp for sp in v2.CATALOG["Couleurs"] if sp.params.get("real_key") == "table_row"]
        padding = [sp for sp in v2.CATALOG["Tableaux"] if sp.key == "table_cell_padding"]
        return [*bg, *padding, *_cell_border_specs()]

    @property
    def dims_key(self):
        return self.element[len("table:"):]

    def apply(self, values):
        _refresh_table(self.element[len("table:"):])


class HeadTarget(Target):
    """Entete d'un tableau (« Entete entier ») : couleur de fond et police de ses titres."""
    kind = "Entête"

    def __init__(self, frame: _TableFrame, label: str):
        self.dims_key = frame.dimsKey()
        super().__init__(f"table:{self.dims_key}{PART_SEP}head", frame, label)

    def specs(self) -> list:
        import settings_window_v2 as v2
        specs = [sp for sp in v2.CATALOG["Tableaux"] if sp.key in _HEAD_KEYS]
        specs += [sp for sp in v2.CATALOG["Couleurs"] if sp.params.get("real_key") in _HEAD_COLOR_SLOTS]
        return specs + [_font_spec()]

    def general(self, settings: dict) -> dict:
        return {**settings, **_font_seed()}

    def apply(self, values):
        _refresh_table(self.dims_key)


class HeadCellTarget(HeadTarget):
    """Un titre de l'entete (« Cellule en cours » dans l'entete) : fond et police. Valeurs de depart =
    celles de l'entete entier (son override compris)."""
    kind = "Cellule d'entête"

    def __init__(self, frame: _TableFrame, column: int, label: str):
        super().__init__(frame, label)
        self.column = column
        self.element = f"table:{self.dims_key}{PART_SEP}{_part_key(('headcell', column))}"

    def general(self, settings: dict) -> dict:
        return merged({**settings, **_font_seed()}, _saved(f"table:{self.dims_key}{PART_SEP}head"))


def _head_column(head: QWidget) -> int | None:
    """Colonne LOGIQUE du titre sous le clic droit (posee par le menu de l'entete, sinon le curseur)."""
    column = getattr(head, "_menu_column", None)
    if column is None and hasattr(head, "_column_at"):
        from PySide6.QtGui import QCursor
        column = head._column_at(head.mapFromGlobal(QCursor.pos()).x())
    return column


class TablePartTarget(Target):
    """Cellule, ligne ou colonne d'un tableau a cellules : fond, padding, police. Valeurs de depart =
    celles du tableau (son override compris) et, pour une cellule, de sa colonne puis de sa ligne."""

    def __init__(self, frame: _TableFrame, part: tuple, kind: str, label: str):
        self.dims_key = frame.dimsKey()
        super().__init__(f"table:{self.dims_key}{PART_SEP}{_part_key(part)}", frame, label)
        self.part, self.kind = part, kind

    def specs(self) -> list:
        import settings_window_v2 as v2
        bg = [sp for sp in v2.CATALOG["Couleurs"] if sp.params.get("real_key") == "table_row"]
        padding = [sp for sp in v2.CATALOG["Tableaux"] if sp.key == "table_cell_padding"]
        return [*bg, *padding, *_cell_border_specs(), _font_spec()]

    def cell_specs(self) -> list:
        import settings_window_v2 as v2
        bg = [sp for sp in v2.CATALOG["Couleurs"] if sp.params.get("real_key") == "table_row"]
        padding = [sp for sp in v2.CATALOG["Tableaux"] if sp.key == "table_cell_padding"]
        return [*bg, *padding, *_cell_border_specs()]

    def general(self, settings: dict) -> dict:
        table = f"table:{self.dims_key}"
        out = merged({**settings, **_font_seed()}, _saved(table))
        if self.part[0] == "cell":
            for wider in (("col", self.part[2]), ("row", self.part[1])):
                out = merged(out, _saved(f"{table}{PART_SEP}{_part_key(wider)}"))
        return out

    def apply(self, values):
        _refresh_parts(self.dims_key)


def _table_part_targets(widget: QWidget, frame: _TableFrame) -> list:
    """Cellule, ligne et colonne sous le clic (tableaux a cellules seulement)."""
    from settings_cells import _Cell
    cells = getattr(getattr(frame, "_extra_dims", None), "cells", None) or {}
    cell = _ancestor(widget, _Cell)
    key = next((k for k, c in cells.items() if c is cell), None) if cell is not None else None
    if key is None:
        return []
    r, c = (int(n) for n in key[1:].split("c"))
    titles = getattr(getattr(frame, "_flat_head", None), "_titles", None) or []
    column = titles[c].capitalize() if c < len(titles) and titles[c] else f"colonne {c + 1}"
    first = cells.get(f"r{r}c0")
    texts = [lb.text().strip() for lb in first.findChildren(QLabel)] if first is not None else []
    row = next((t for t in texts if t), f"ligne {r + 1}").replace("\n", " ")[:40]
    out = [TablePartTarget(frame, ("cell", r, c), "Cellule", f"« {row} › {column} »"),
           TablePartTarget(frame, ("row", r), "Ligne", f"« {row} »"),
           TablePartTarget(frame, ("col", c), "Colonne", f"« {column} »")]
    for target, scope in zip(out, ("Cellule en cours", "Ligne en cours", "Colonne en cours sauf entête")):
        target.scope_label = scope
    return out


# -- Titre (fenetre v2) -------------------------------------------------------

def title_state(values: dict, level: int) -> dict:
    """Police, couleur et boite d'un titre de `level` pour `values` (le style general des titres est
    remis aussitot apres)."""
    from settings_store import _TITLE_LEVEL_STYLE, _sync_title_level_style, _title_box, _title_color, _title_font
    saved = copy.deepcopy(_TITLE_LEVEL_STYLE)
    try:
        _sync_title_level_style(values)
        return {"font": QFont(_title_font(level)), "color": _title_color(level), "box": _title_box(level)}
    finally:
        for lv, style in saved.items():
            _TITLE_LEVEL_STYLE[lv].clear()
            _TITLE_LEVEL_STYLE[lv].update(style)


class TitleTarget(Target):
    kind = "Titre"

    def __init__(self, element, widget, label, level: int):
        super().__init__(element, widget, label)
        self.level = level

    def specs(self) -> list:
        import settings_window_v2 as v2
        return [v2.CATALOG["Titre : Polices"][self.level - 1], *v2.CATALOG[f"Titre : Fond {self.level}"]]

    def apply(self, values):
        apply_title_look(self.widget, title_state(values, self.level) if values else None, self.level)


def apply_title_look(title: QWidget, look: dict | None, level: int) -> None:
    from settings_store import _title_color, _title_font
    title._title_look = look
    font, color = (look["font"], look["color"]) if look else (_title_font(level), _title_color(level))
    title._name_label.setFont(font)
    title._name_label.setStyleSheet(f"color: {color}; background: transparent;")
    title._chevron.setColor(color)
    titles = [title, *[t for t in title.findChildren(QWidget) if hasattr(t, "apply_box")]]
    for t in titles:                        # parents d'abord : l'abscisse d'un enfant en depend
        t.apply_box()
    relayout = getattr(title.window(), "_relayout", None)
    if relayout is not None:
        relayout()


# -- Texte ----------------------------------------------------------------------

def _text_specs() -> tuple:
    from settings_quick_style import font_padding_specs
    import settings_window_v2 as v2
    return (*font_padding_specs("text", size=(6, 72)),
            v2.Spec("text_border_enabled", "Bordures", "sides_thick", False,
                    {"colors_key": "text_border", "thickness_key": "text_border_thickness",
                     "width": 90, "box": 54},
                    extra_keys=("text_border", "text_border_thickness")),
            v2.Spec("text_border_radius", "Border radius", "corners", 0, {"max": 30}),
            v2.Spec("text_background_enabled", "Couleur de fond", "bg_fill", False,
                    {"color_key": "text_background_color", "color_default": "#00000000",
                     "width": 90, "box": 54},
                    extra_keys=("text_background_color",)))


def _editable_font_size(font: QFont) -> int:
    """Taille en pixels logiques attendue par app_style.font, sans reduire les polices Qt en points."""
    from app_style import ui_scale
    pixels = font.pixelSize() if font.pixelSize() > 0 else QFontInfo(font).pixelSize()
    return max(1, round(pixels * 100 / ui_scale()))


class TextTarget(Target):
    kind = "Texte"

    def specs(self) -> list:
        return list(_text_specs())

    def general(self, settings: dict) -> dict:
        """Apparence d'origine du texte (relevee avant le premier override)."""
        label = self.widget
        orig = getattr(label, "_look_orig", None)
        font = orig[0] if orig else label.font()
        size = _editable_font_size(font)
        color = label.palette().color(label.foregroundRole()).name()
        margins = orig[2] if orig else label.contentsMargins()
        out = dict(settings)
        out.update({"text_font_family": font.family(), "text_font_bold": font.weight() >= QFont.DemiBold,
                    "text_font_italic": font.italic(), "text_font_size": size,
                    "text_font_smoothing_enabled": False, "text_font_smoothing": "current",
                    "text_font_color": orig[3] if orig else color,
                    "text_padding": {"left": margins.left(), "top": margins.top(),
                                     "right": margins.right(), "bottom": margins.bottom()},
                    "text_padding_linked": False,
                    "text_border_enabled": {side: False for side in ("top", "right", "bottom", "left")},
                    "text_border": {side: "#00000000" for side in ("top", "right", "bottom", "left")},
                    "text_border_enabled_linked": True, "text_border_thickness": 1,
                    "text_border_radius": {corner: 0 for corner in ("top_left", "top_right", "bottom_right", "bottom_left")},
                    "text_border_radius_linked": True,
                    "text_background_enabled": False, "text_background_color": "#00000000"})
        return out

    def apply(self, values):
        apply_text_look(self.widget, values)

    def preview(self, values: dict) -> None:
        settings = load_settings()
        general = self.general(settings)
        override = _diff(_normalized(self.specs(), general), values)
        self.apply(merged(general, override) if override else None)


class TableTextTarget(TextTarget):
    """Style du texte selectionne et de sa cellule/portee de tableau."""

    def __init__(self, text_target: TextTarget, cell_target: Target):
        self.text_target, self.cell_target = text_target, cell_target
        super().__init__(text_target.element, text_target.widget, text_target.label)

    def specs(self) -> list:
        return [*self.text_target.specs(), *self.cell_target.cell_specs()]

    def general(self, settings: dict) -> dict:
        return {**self.text_target.general(settings), **self.cell_target.general(settings)}

    def values(self, settings: dict) -> dict:
        return {**self.text_target.values(settings),
                **merged(self.cell_target.general(settings), _saved(self.cell_target.element))}

    def has_override(self) -> bool:
        return self.text_target.has_override() or self.cell_target.has_override()

    def _split(self, values: dict) -> tuple[dict, dict]:
        specs = self.cell_target.cell_specs()
        cell_keys = {sp.key for sp in specs}
        cell_keys.update(f"colors:{sp.params['real_key']}" for sp in specs
                         if sp.params and sp.params.get("real_key"))
        cell_keys.update(key for sp in specs for key in getattr(sp, "extra_keys", ()))
        cell_keys.update(key for sp in specs for key in (sp.params or {}).values()
                         if isinstance(key, str) and key not in cell_keys)
        return ({key: value for key, value in values.items() if key not in cell_keys},
                {key: value for key, value in values.items() if key in cell_keys})

    def save(self, values: dict) -> None:
        text_values, cell_values = self._split(values)
        settings = load_settings()
        overrides = dict(settings.get(KEY) or {})
        for target, supplied, specs in (
            (self.text_target, text_values, self.text_target.specs()),
            (self.cell_target, cell_values, self.cell_target.cell_specs()),
        ):
            general = target.general(settings)
            override = _diff(_normalized(specs, general), supplied)
            if override:
                overrides[target.element] = override
            else:
                overrides.pop(target.element, None)
        settings[KEY] = overrides
        save_settings(settings)
        _publish_row_text_overrides(overrides)
        _notify(KEY, overrides)
        self.text_target.apply(merged(self.text_target.general(settings),
                                      _saved(self.text_target.element))
                               if _saved(self.text_target.element) else None)
        _refresh_parts(self.cell_target.dims_key)

    def preview(self, values: dict) -> None:
        text_values, cell_values = self._split(values)
        self.text_target.preview(text_values)
        settings = load_settings()
        overrides = dict(settings.get(KEY) or {})
        general = self.cell_target.general(settings)
        override = _diff(_normalized(self.cell_target.cell_specs(), general), cell_values)
        if override:
            overrides[self.cell_target.element] = override
        else:
            overrides.pop(self.cell_target.element, None)
        settings[KEY] = overrides
        _refresh_parts(self.cell_target.dims_key, settings)

    def remove(self) -> None:
        settings = load_settings()
        overrides = dict(settings.get(KEY) or {})
        overrides.pop(self.text_target.element, None)
        overrides.pop(self.cell_target.element, None)
        settings[KEY] = overrides
        save_settings(settings)
        _publish_row_text_overrides(overrides)
        _notify(KEY, overrides)
        self.text_target.apply(None)
        _refresh_parts(self.cell_target.dims_key)

    def snapshot_overrides(self) -> dict:
        overrides = load_settings().get(KEY) or {}
        return {"text": copy.deepcopy(overrides.get(self.text_target.element)),
                "cell": copy.deepcopy(overrides.get(self.cell_target.element))}

    def restore_overrides(self, snapshot: dict) -> None:
        settings = load_settings()
        overrides = dict(settings.get(KEY) or {})
        for target, value in ((self.text_target, snapshot.get("text")),
                              (self.cell_target, snapshot.get("cell"))):
            if value:
                overrides[target.element] = copy.deepcopy(value)
            else:
                overrides.pop(target.element, None)
        settings[KEY] = overrides
        save_settings(settings)
        _publish_row_text_overrides(overrides)
        _notify(KEY, overrides)
        self.text_target.apply(merged(self.text_target.general(settings),
                                      _saved(self.text_target.element))
                               if _saved(self.text_target.element) else None)
        _refresh_parts(self.cell_target.dims_key)

    def apply(self, values):
        text_values, _cell_values = self._split(values or {})
        self.text_target.apply(text_values or None)
        _refresh_parts(self.cell_target.dims_key)


class RowTextTarget(TextTarget):
    """Override d'un nom peint dans une ligne de colonne (plutôt qu'un QLabel)."""

    def __init__(self, widget, path: str, column_title: str, label: str = ""):
        self.view = widget.view
        self.path = str(path)
        self.column_title = str(column_title)
        super().__init__(f"row-text:{self.column_title}:{self.path}", widget,
                         label or self.path.rsplit("\\", 1)[-1])

    @property
    def legacy_element(self):
        return f"row-text::{self.path}"

    def values(self, settings: dict) -> dict:
        return merged(self.general(settings), _saved(self.element) or _saved(self.legacy_element))

    def has_override(self) -> bool:
        return bool(_saved(self.element) or _saved(self.legacy_element))

    def save(self, values: dict) -> None:
        settings = load_settings()
        general = self.general(settings)
        override = _diff(_normalized(self.specs(), general), values)
        overrides = dict(settings.get(KEY) or {})
        overrides.pop(self.legacy_element, None)
        if override:
            overrides[self.element] = override
        else:
            overrides.pop(self.element, None)
        settings[KEY] = overrides
        save_settings(settings)
        _publish_row_text_overrides(overrides)
        _notify(KEY, overrides)
        self.apply(merged(general, override) if override else None)

    def remove(self) -> None:
        settings = load_settings()
        overrides = dict(settings.get(KEY) or {})
        overrides.pop(self.element, None)
        overrides.pop(self.legacy_element, None)
        settings[KEY] = overrides
        save_settings(settings)
        _publish_row_text_overrides(overrides)
        _notify(KEY, overrides)
        self.apply(None)

    def general(self, settings: dict) -> dict:
        from browser_core import ROLE_IS_SHORTCUT, _resolve_shortcut_font_color
        delegate = self.view.itemDelegate()
        base_font = getattr(delegate, "type_font", getattr(delegate, "font_name", self.widget.font()))
        base_color = getattr(delegate, "type_color", getattr(delegate, "color_name", "#d6d9dc"))
        index = _row_index(self.view, self.path)
        if index is not None and index.data(ROLE_IS_SHORTCUT):
            base_font, base_color = _resolve_shortcut_font_color()
        size = _editable_font_size(base_font)
        out = dict(settings)
        out.update({"text_font_family": base_font.family(), "text_font_bold": base_font.weight() >= QFont.DemiBold,
                    "text_font_italic": base_font.italic(), "text_font_size": max(1, size),
                    "text_font_smoothing_enabled": False, "text_font_smoothing": "current",
                    "text_font_color": base_color,
                    "text_padding": {s: 0 for s in ("left", "top", "right", "bottom")},
                    "text_padding_linked": False,
                    "text_border_enabled": {s: False for s in ("top", "right", "bottom", "left")},
                    "text_border": {s: "#00000000" for s in ("top", "right", "bottom", "left")},
                    "text_border_enabled_linked": True, "text_border_thickness": 1,
                    "text_border_radius": {c: 0 for c in ("top_left", "top_right", "bottom_right", "bottom_left")},
                    "text_border_radius_linked": True,
                    "text_background_enabled": False, "text_background_color": "#00000000"})
        return out

    def apply(self, values):
        import ui_state
        row_looks = dict(getattr(ui_state, "ROW_TEXT_OVERRIDES", {}) or {})
        if values:
            row_looks[self.element] = copy.deepcopy(values)
        else:
            row_looks.pop(self.element, None)
            row_looks.pop(self.legacy_element, None)
        ui_state.ROW_TEXT_OVERRIDES = row_looks
        self.view.viewport().update()


class GalleryStyleTarget(TextTarget):
    """Style local d'une cellule, d'une image ou d'un des textes de la planche."""

    def __init__(self, widget, path: str, part: str, label: str = ""):
        self.gallery = widget.view
        self.path = str(path)
        self.part = part
        self._specs = self._make_specs()
        super().__init__(f"gallery-{part}:{self.path}", widget, label or self.path.rsplit("/", 1)[-1])

    def _make_specs(self):
        import settings_window_v2 as v2
        table_bg = next(spec for spec in v2.CATALOG["Couleurs"]
                        if spec.key == "colors:tableRow")
        cell = [v2.Spec("gallery_cell_bg", table_bg.label, table_bg.kind, table_bg.default,
                        dict(table_bg.params or {})),
                v2.Spec("gallery_cell_padding", "Cellule : padding", "padding", {}),
                v2.Spec("gallery_cell_border_enabled", "Cellule : bordures", "sides_thick", False,
                        {"colors_key": "gallery_cell_border", "thickness_key": "gallery_cell_border_thickness",
                         "width": 90, "box": 54},
                        extra_keys=("gallery_cell_border", "gallery_cell_border_thickness")),
                v2.Spec("gallery_cell_border_radius", "Cellule : border radius", "corners", 0, {"max": 30})]
        if self.part in {"name", "info"}:
            return [*_text_specs(), *cell]
        image = list(v2.CATALOG["Visionneuse : Cellule image"])
        if self.part == "image":
            return [spec for spec in image
                    if spec.key.startswith("viewer_film_image_border_")
                    or spec.key == "viewer_film_image_border_radius"
                    or spec.key.startswith("viewer_film_image_shadow")]
        return cell

    def specs(self) -> list:
        return self._specs

    @staticmethod
    def sparse_look(override: dict) -> dict:
        """Ne garder que les champs modifiés; la couleur du tableau est une clé UI."""
        saved = {key: copy.deepcopy(value) for key, value in override.items() if key != "colors"}
        color = (override.get("colors") or {}).get("table_row")
        if color is not None:
            saved["gallery_cell_bg"] = color
        return saved

    def values(self, settings: dict) -> dict:
        values = self.general(settings)
        saved = _saved(self.element)
        values.update(saved)
        if "gallery_cell_bg" in saved:
            values["colors"] = {**(values.get("colors") or {}),
                                "table_row": saved["gallery_cell_bg"]}
        return values

    def general(self, settings: dict) -> dict:
        if self.part not in {"name", "info"}:
            return dict(settings)
        look = self.gallery.film_look
        qfont, qcolor = look["name_font" if self.part == "name" else "rank_font"]
        size = _editable_font_size(qfont)
        out = dict(settings)
        out.update({"text_font_family": qfont.family(), "text_font_bold": qfont.weight() >= QFont.DemiBold,
                    "text_font_italic": qfont.italic(), "text_font_size": max(1, size),
                    "text_font_smoothing_enabled": False, "text_font_smoothing": "current",
                    "text_font_color": qcolor.name(QColor.NameFormat.HexArgb),
                    "text_padding": {s: 0 for s in ("left", "top", "right", "bottom")},
                    "text_padding_linked": False,
                    "text_border_enabled": {s: False for s in ("top", "right", "bottom", "left")},
                    "text_border": {s: "#00000000" for s in ("top", "right", "bottom", "left")},
                    "text_border_enabled_linked": True, "text_border_thickness": 1,
                    "text_border_radius": {c: 0 for c in ("top_left", "top_right", "bottom_right", "bottom_left")},
                    "text_border_radius_linked": True,
                    "text_background_enabled": False, "text_background_color": "#00000000"})
        return out

    def save(self, values: dict) -> None:
        settings = load_settings()
        override = _diff(_normalized(self.specs(), self.general(settings)), values)
        saved = self.sparse_look(override)
        save_override(self.element, saved)
        self.apply(saved)

    def preview(self, values: dict) -> None:
        settings = load_settings()
        override = _diff(_normalized(self.specs(), self.general(settings)), values)
        self.apply(self.sparse_look(override))

    def apply(self, values):
        import ui_state
        overrides = dict(getattr(ui_state, "GALLERY_STYLE_OVERRIDES", {}) or {})
        if values:
            overrides[self.element] = copy.deepcopy(values)
        else:
            overrides.pop(self.element, None)
        ui_state.GALLERY_STYLE_OVERRIDES = overrides
        self.gallery.invalidate_edited_cell(self.path)


class TextGroupTarget(TextTarget):
    """Un même override de texte appliqué à un ensemble explicite de libellés."""

    def __init__(self, targets: list[TextTarget], label: str):
        self.targets = targets
        self._gallery_initial = None
        first = targets[0]
        super().__init__(f"text-group:{label}", first.widget, label)

    def general(self, settings: dict) -> dict:
        return self.targets[0].general(settings)

    def specs(self) -> list:
        return list(self.targets[0].specs())

    def values(self, settings: dict) -> dict:
        values = self.targets[0].values(settings)
        if all(isinstance(target, GalleryStyleTarget) for target in self.targets):
            self._gallery_initial = _normalized(self.specs(), values)
        return values

    def _gallery_changes(self, values: dict, settings: dict) -> dict:
        """Deux références au plus (nom/info), quel que soit le nombre de diapos."""
        if self._gallery_initial is None:
            self._gallery_initial = _normalized(self.specs(), self.targets[0].values(settings))
        changed = {key: value for key, value in values.items()
                   if key in self._gallery_initial and value != self._gallery_initial[key]}
        normalized = {}
        stored = settings.get(KEY) or {}
        changes = {}
        for target in self.targets:
            part = target.part
            if part not in normalized:
                normalized[part] = _normalized(target.specs(), target.general(settings))
            general = normalized[part]
            saved = stored.get(target.element) or {}
            current = {**general, **{key: value for key, value in saved.items()
                                    if key not in {"gallery_cell_bg", "colors"}}}
            if "gallery_cell_bg" in saved:
                current["colors:table_row"] = saved["gallery_cell_bg"]
            elif (saved.get("colors") or {}).get("table_row") is not None:
                current["colors:table_row"] = saved["colors"]["table_row"]
            desired = {**current, **changed}
            changes[target.element] = target.sparse_look(_diff(general, desired))
        return changes

    def _gallery_refresh(self, changes: dict) -> None:
        galleries = {}
        for target in self.targets:
            galleries.setdefault(target.gallery, set()).add(target.path)
        for gallery, paths in galleries.items():
            for path in paths:
                gallery.invalidate_edited_cell(path, repaint=False)
            gallery.viewport().update()

    def save(self, values: dict) -> None:
        if any(isinstance(target, TableTextTarget) for target in self.targets):
            for target in self.targets:
                if isinstance(target, TableTextTarget):
                    target.save(values)
                else:
                    keys = {sp.key for sp in target.specs()}
                    keys.update(key for sp in target.specs() for key in getattr(sp, "extra_keys", ()))
                    target.save({key: value for key, value in values.items() if key in keys})
            return
        if all(isinstance(target, GalleryStyleTarget) for target in self.targets):
            settings = load_settings()
            overrides = dict(settings.get(KEY) or {})
            changes = self._gallery_changes(values, settings)
            for element, saved in changes.items():
                if saved:
                    overrides[element] = saved
                else:
                    overrides.pop(element, None)
            settings[KEY] = overrides
            save_settings(settings)
            _publish_row_text_overrides(overrides)
            _notify(KEY, overrides)
            self._gallery_refresh(changes)
            return
        settings = load_settings()
        overrides = dict(settings.get(KEY) or {})
        applied = []
        normalized_cache = {}
        for target in self.targets:
            general = target.general(settings)
            signature = repr(sorted(general.items(), key=lambda item: item[0]))
            normalized = normalized_cache.get(signature)
            if normalized is None:
                normalized = normalized_cache[signature] = _normalized(target.specs(), general)
            override = _diff(normalized, values)
            if isinstance(target, RowTextTarget):
                overrides.pop(target.legacy_element, None)
            if override:
                overrides[target.element] = override
            else:
                overrides.pop(target.element, None)
            applied.append((target, merged(general, override) if override else None))
        settings[KEY] = overrides
        save_settings(settings)
        _publish_row_text_overrides(overrides)
        _notify(KEY, overrides)
        for target, look in applied:
            try:
                target.apply(look)
            except RuntimeError:
                continue

    def preview(self, values: dict) -> None:
        if all(isinstance(target, GalleryStyleTarget) for target in self.targets):
            changes = self._gallery_changes(values, load_settings())
            import ui_state
            overrides = dict(getattr(ui_state, "GALLERY_STYLE_OVERRIDES", {}) or {})
            for element, saved in changes.items():
                if saved:
                    overrides[element] = saved
                else:
                    overrides.pop(element, None)
            ui_state.GALLERY_STYLE_OVERRIDES = overrides
            self._gallery_refresh(changes)
            return
        settings = load_settings()
        normalized_cache = {}
        for target in self.targets:
            general = target.general(settings)
            signature = repr(sorted(general.items(), key=lambda item: item[0]))
            normalized = normalized_cache.get(signature)
            if normalized is None:
                normalized = normalized_cache[signature] = _normalized(target.specs(), general)
            override = _diff(normalized, values)
            if isinstance(target, TableTextTarget):
                target.preview(values)
            else:
                target.apply(merged(general, override) if override else None)

    def apply(self, values):
        for target in self.targets:
            target.apply(values)

    def has_override(self) -> bool:
        return any(target.has_override() for target in self.targets)

    def remove(self) -> None:
        for target in self.targets:
            target.remove()


def apply_text_look(label: QWidget, values: dict | None) -> None:
    if getattr(label, "_look_orig", None) is None:
        color = label.palette().color(label.foregroundRole()).name()
        label._look_orig = (QFont(label.font()), label.styleSheet(), label.contentsMargins(), color)
    font0, sheet0, margins0, _color0 = label._look_orig
    if not values:
        label.setFont(font0)
        label.setStyleSheet(sheet0)
        label.setContentsMargins(margins0)
        label._look_values = None
        return
    from app_style import font as app_font
    size = int(values.get("text_font_size", 10) or 10)
    weight = 600 if values.get("text_font_bold") else 400
    smoothing = values.get("text_font_smoothing", "current") if values.get("text_font_smoothing_enabled") else "current"
    family = (values.get("text_font_family") or "").strip() or font0.family()
    label.setFont(app_font(size, weight, family=family, italic=bool(values.get("text_font_italic")),
                           smoothing=smoothing))
    color = _resolve_color_value(values.get("text_font_color") or "", values.get("colors") or {})
    bg = (_resolve_color_value(values.get("text_background_color") or "", values.get("colors") or {})
          if values.get("text_background_enabled") else "transparent")
    sides = values.get("text_border_enabled") or {}
    border_colors = values.get("text_border") or {}
    thickness = max(0, int(values.get("text_border_thickness", 1) or 0))
    border_css = " ".join(
        f"border-{side}: {thickness if sides.get(side) else 0}px solid "
        f"{_resolve_color_value(border_colors.get(side, ""), values.get("colors") or {}) or "transparent"};"
        for side in ("top", "right", "bottom", "left"))
    radius = values.get("text_border_radius") or {}
    corners = ("top_left", "top_right", "bottom_right", "bottom_left")
    radii = [int(radius.get(corner, 0) or 0) for corner in corners]
    radius_css = " ".join(f"border-{corner.replace('_', '-')}-radius: {value}px;"
                          for corner, value in zip(corners, radii))
    style = f"color: {color};" if color else ""
    label.setStyleSheet(f"{style} background: {bg}; {border_css} {radius_css}" if style or bg != "transparent" or any(sides.values()) or any(radii) else sheet0)
    pad = values.get("text_padding") or {}
    label.setContentsMargins(*(int(pad.get(s, 0)) for s in ("left", "top", "right", "bottom")))
    label._look_values = values


# -- Toggle -----------------------------------------------------------------------

class ToggleTarget(Target):
    kind = "Toggle"

    def __init__(self, element, widget, label):
        super().__init__(element, widget, label)
        self.prefix = widget._style_key()

    def specs(self) -> list:
        import settings_window_v2 as v2
        kind, frame, check = v2._toggle_specs(self.prefix)
        return [*kind, *frame, *check]

    def apply(self, values):
        apply_toggle_look(self.widget, values, self.prefix)


def apply_toggle_look(toggle: _Toggle, values: dict | None, prefix: str) -> None:
    from settings_widgets import _sync_toggle_shape_style, _toggle_style_dict
    if values:
        style = copy.deepcopy(_toggle_style_dict(prefix))
        _sync_toggle_shape_style(style, values, prefix)
        toggle._look_style = style
    else:
        toggle._look_style = None
    toggle._look_prefix = prefix
    toggle.apply_style()
    toggle.update()


def toggle_id(toggle: _Toggle, window: QWidget) -> str | None:
    style_id = getattr(toggle, "style_id", None)
    if style_id:
        return f"toggle:{style_id}"
    path = widget_path(toggle, window)
    return f"toggle:{_scope_of(window)}:{path}" if path else None


# -- Colonne (surcharges existantes, fournie par l'appli) -----------------------------

class ColumnTarget(Target):
    """Colonne de la fenetre principale : les tableaux de son onglet de surcharge (Reglages > onglet de
    la colonne) ; ecrit dans les surcharges de colonne (cle activee par ligne), pas dans
    `element_style_overrides`."""

    kind = "Colonne"
    stored = False
    _NAMES = {"overrides": ("column_type_overrides", "column_overrides_by_title"),
              "enabled": ("column_type_override_enabled", "column_override_enabled_by_title")}

    def __init__(self, title: str, widget: QWidget, label: str | None = None):
        super().__init__(f"column:{title}", widget, label or title)
        self.title = title

    def specs(self) -> list:
        import settings_window_v2 as v2
        groups, stack = [], list(v2.nodes_for(self.title))
        while stack:
            node = stack.pop(0)
            if node.group:
                groups.append(node.group)
            stack[0:0] = list(node.children)
        specs = []
        for group in groups:
            if group in v2.COLUMN_TABLES:
                continue
            specs += [sp for sp in v2.CATALOG.get(group, ()) if sp.applies(self.title)]
        return specs

    def _store(self, settings: dict, kind: str) -> dict:
        type_key, by_title_key = self._NAMES[kind]
        if self.title == "Type":
            return dict(settings.get(type_key) or {})
        return dict((settings.get(by_title_key) or {}).get(self.title) or {})

    def _put(self, settings: dict, kind: str, store: dict) -> None:
        type_key, by_title_key = self._NAMES[kind]
        if self.title == "Type":
            settings[type_key] = store
        else:
            all_ = dict(settings.get(by_title_key) or {})
            all_[self.title] = store
            settings[by_title_key] = all_

    def _keys(self) -> list:
        return [k for sp in self.specs() for k in (sp.key, *sp.extra_keys)]

    def values(self, settings: dict) -> dict:
        overrides, enabled = self._store(settings, "overrides"), self._store(settings, "enabled")
        out = dict(settings)
        for key in self._keys():
            if enabled.get(key) and key in overrides:
                out[key] = overrides[key]
        return out

    def has_override(self) -> bool:
        enabled = self._store(load_settings(), "enabled")
        return any(enabled.get(k) for k in self._keys())

    def save(self, values: dict) -> None:
        settings = load_settings()
        overrides, enabled = self._store(settings, "overrides"), self._store(settings, "enabled")
        flat = {k for sp in self.specs() if sp.flat for k in (sp.key, *sp.extra_keys)}
        for key, value in _fold_colors(values).items():
            if key in _SPACE_KEYS or key == "colors":
                continue
            if key in flat:                          # reglage propre a la colonne : cle generale
                settings[key] = value
            elif value != settings.get(key):
                overrides[key], enabled[key] = value, True
            elif key in overrides:
                overrides.pop(key, None)
                enabled.pop(key, None)
        self._put(settings, "overrides", overrides)
        self._put(settings, "enabled", enabled)
        save_settings(settings)
        for name in (*self._NAMES["overrides"], *self._NAMES["enabled"], *flat):
            _notify(name, settings.get(name))

    def remove(self) -> None:
        settings = load_settings()
        overrides, enabled = self._store(settings, "overrides"), self._store(settings, "enabled")
        for key in self._keys():
            overrides.pop(key, None)
            enabled.pop(key, None)
        self._put(settings, "overrides", overrides)
        self._put(settings, "enabled", enabled)
        save_settings(settings)
        for name in (*self._NAMES["overrides"], *self._NAMES["enabled"]):
            _notify(name, settings.get(name))

    def apply(self, values):
        pass                                     # l'appli se restyle (prevenue par _notify)


# ==========================================================================
# Elements sous un clic
# ==========================================================================

def targets_for(widget: QWidget) -> list:
    """Elements sous `widget`, du plus proche au plus large (texte, toggle, titre, tableau, colonne...)."""
    window = widget.window()
    out = []
    toggle = _ancestor(widget, _Toggle)
    if toggle is not None:
        element = toggle_id(toggle, window)
        if element:
            out.append(ToggleTarget(element, toggle, "toggle"))
    header = None
    try:
        from settings_layout import _SectionHeader
        header = _ancestor(widget, _SectionHeader)
    except ImportError:
        pass
    if getattr(widget, "part", None) == "text" and hasattr(widget, "view"):
        from browser_core import ROLE_PATH
        view = widget.view
        column = _column_for_view(view)
        model = view.model()
        path, name = str(widget.key), ""
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if str(index.data(ROLE_PATH) or index.row()) == path:
                name = str(index.data(Qt.DisplayRole) or "")
                break
        if name and column is not None:
            out.append(RowTextTarget(widget, path, getattr(column, "style_title", ""), name))
    if getattr(widget, "part", "").startswith("gallery-") and hasattr(widget, "view"):
        part = widget.part.removeprefix("gallery-")
        label = str(widget.key)
        for row in range(widget.view.count()):
            item = widget.view.item(row)
            if str(item.data(Qt.UserRole)) == str(widget.key):
                label = item.text()
                break
        out.append(GalleryStyleTarget(widget, str(widget.key), part, label))
    if is_text_widget(widget) and header is None and toggle is None:
        path = widget_path(widget, window)
        if path:
            text = text_of(widget).replace("\n", " ")
            out.append(TextTarget(f"text:{_scope_of(window)}:{path}", widget,
                                  f"« {text[:40]}{'…' if len(text) > 40 else ''} »"))
    if header is not None:
        title = header.parentWidget()
        key = _title_key(title)
        if key and hasattr(title, "_name_label"):
            out.append(TitleTarget(f"title:{key}", title, title._name_label.text().title(),
                                   getattr(title, "_level", 1)))
    frame = _ancestor(widget, _TableFrame)
    if frame is not None:
        label = frame.dimsKey().rsplit("#", 1)[0].replace("/", " › ").split("|")[-1] or "tableau"
        parts = _table_part_targets(widget, frame)
        head = getattr(frame, "_flat_head", None)
        if head is not None and _ancestor(widget, type(head)) is head:     # clic dans l'entete
            column = _head_column(head)
            titles = getattr(head, "_titles", None) or []
            if column is not None and 0 <= column < len(titles):
                name = titles[column].capitalize() or f"colonne {column + 1}"
                cell = HeadCellTarget(frame, column, f"« {name} »")
                cell.scope_label = "Cellule en cours"
                parts.append(cell)
            target = HeadTarget(frame, label)
            target.scope_label = "Entête entier"
            parts.append(target)
        table = TableTarget(table_id(frame), frame, label)
        if parts:                            # le menu demande la portee : cellule / ligne / colonne / tableau
            table.scope_label = "Tableau entier sauf entête"
        out += [*parts, table]
    for resolver in list(TARGET_RESOLVERS):
        out += resolver(widget) or []
    return out


def _title_key(title: QWidget) -> str | None:
    """Cle stable d'un titre de la fenetre v2 (la meme que pour ses espaces)."""
    window = title.window()
    element = getattr(window, "_space_element", None)
    key_of = getattr(window, "_space_key", None)
    if element is None or key_of is None:
        return None
    node = element(title)
    return key_of(node) if node is not None else None


# ==========================================================================
# Fenetre d'override, menus
# ==========================================================================

_OPEN: dict = {}          # identifiant -> fenetre ouverte


def open_override(target: Target, space: dict | None = None, parent=None):
    """Fenetre « Changement de style a la volee » : tout ce qui compose l'element, puis ses deux espaces ;
    chaque changement est applique a lui seul et enregistre aussitot."""
    import settings_window_v2 as v2
    from settings_quick_style import QuickStyleWindow
    window = _OPEN.get(target.element)
    try:
        if window is not None and window.isVisible():
            window.raise_()
            window.activateWindow()
            return window
    except RuntimeError:
        pass
    settings = load_settings()
    values = target.values(settings)
    specs = list(target.specs())
    if space is not None:
        maximum = int(space.get("maximum", 200))
        specs += [v2.Spec(_SPACE_KEYS[0], SPACE_ABOVE_TEXT, "slider", 0, {"min": 0, "max": maximum}),
                  v2.Spec(_SPACE_KEYS[1], SPACE_BELOW_TEXT, "slider", 0, {"min": 0, "max": maximum})]
        values[_SPACE_KEYS[0]], values[_SPACE_KEYS[1]] = int(space.get("above", 0)), int(space.get("below", 0))
    window = QuickStyleWindow(f"Override {target.kind}", specs, values,
                              title=f"Override settings — {target.kind} {target.label}", settings=settings,
                              parent=parent)
    last = {k: values.get(k) for k in _SPACE_KEYS}

    def changed(style: dict):
        if space is not None:
            for key, setter in zip(_SPACE_KEYS, (space["set_above"], space["set_below"])):
                if style.get(key) != last[key]:
                    last[key] = style.get(key)
                    setter(int(style.get(key) or 0))
        values = {k: v for k, v in style.items() if k not in _SPACE_KEYS}
        if isinstance(target, TextTarget):
            target.preview(values)
            window._pending_text_style = values
            if not hasattr(window, "_text_save_timer"):
                window._text_save_timer = QTimer(window)
                window._text_save_timer.setSingleShot(True)
                # La planche peut viser des centaines de cases : son aperçu
                # est immédiat, mais l'écriture sur disque attend la fin du
                # geste. Les autres textes gardent la sauvegarde au tour suivant.
                gallery_scope = isinstance(target, GalleryStyleTarget) or (
                    isinstance(target, TextGroupTarget)
                    and all(isinstance(item, GalleryStyleTarget) for item in target.targets))
                window._text_save_timer.setInterval(180 if gallery_scope else 0)
                window._text_save_timer.timeout.connect(
                    lambda w=window, t=target: t.save(getattr(w, "_pending_text_style", {})))
            window._text_save_timer.start()
        else:
            target.save(values)

    def flush_pending():
        timer = getattr(window, "_text_save_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
            target.save(getattr(window, "_pending_text_style", {}))

    window.styleChanged.connect(changed)
    window.finished.connect(flush_pending)
    _OPEN[target.element] = window
    try:
        pos = target.widget.mapToGlobal(target.widget.rect().topRight())
        window.move(pos.x() + 12, pos.y())
    except RuntimeError:
        pass
    window.show()
    window.raise_()
    window.activateWindow()
    return window


def remove_override(target: Target) -> None:
    target.remove()
    window = _OPEN.pop(target.element, None)
    try:
        if window is not None:
            window.close()
    except RuntimeError:
        pass


def add_override_actions(widget: QWidget, menu: QMenu, space: dict | None = None) -> None:
    """« Override settings… » (sous-menu si plusieurs elements) et « Retirer l'override »."""
    if getattr(menu, "_override_done", False):
        return
    menu._override_done = True
    targets = targets_for(widget)
    if not targets:
        return
    parent = widget.window()
    menu.addSeparator()
    if len(targets) == 1:
        target = targets[0]
        menu.addAction("Override settings…", lambda t=target: open_override(t, space, parent))
        if target.has_override():
            menu.addAction("Retirer l'override", lambda t=target: remove_override(t))
        return
    sub = menu.addMenu("Override settings")
    scoped = [t for t in targets if getattr(t, "scope_label", None)]     # portees d'un tableau
    others = [t for t in targets if t not in scoped]

    def fill(into: QMenu, group: list, scope: bool):
        for target in group:
            text = target.scope_label if scope else f"{target.kind} {target.label}"
            into.addAction(f"{text}…", lambda t=target: open_override(t, space, parent))
        removable = [t for t in group if t.has_override()]
        if removable:
            into.addSeparator()
            for target in removable:
                text = target.scope_label.lower() if scope else f"{target.kind} {target.label}"
                into.addAction(f"Retirer l'override : {text}", lambda t=target: remove_override(t))

    fill(sub, others, False)
    if scoped:
        table = scoped[-1]
        into = sub.addMenu(f"Tableau {table.label}") if others else sub
        fill(into, scoped, True)


def _space_hook(widget, menu, context) -> None:
    add_override_actions(widget, menu, context)


def _final_extra(widget, menu) -> None:
    """Menu sans lignes d'espace (ex. cellule d'un tableau hors de la fenetre de reglages)."""
    add_override_actions(widget, menu, None)


if _space_hook not in SPACE_MENU_HOOKS:
    SPACE_MENU_HOOKS.append(_space_hook)
if _final_extra not in CONTEXT_MENU_FINAL:
    CONTEXT_MENU_FINAL.append(_final_extra)


# ==========================================================================
# Overrides enregistres : chargement, reapplication
# ==========================================================================

def load(settings: dict) -> None:
    """(Re)lit les overrides de tableaux (et de leurs parties) : chaque tableau les reprend a son
    affichage."""
    for element in [k for k in ELEMENT_LOOKS if k.startswith("table:")]:
        ELEMENT_LOOKS.pop(element, None)
    PART_LOOKS.clear()
    _publish_row_text_overrides(settings.get(KEY) or {})
    for element, override in (settings.get(KEY) or {}).items():
        if not element.startswith("table:") or not override:
            continue
        dims_key = element[len("table:"):].split(PART_SEP)[0]
        if dims_key not in PART_LOOKS:
            parts = _parts_of(settings, dims_key)
            if parts:
                PART_LOOKS[dims_key] = parts
        if f"table:{dims_key}" not in ELEMENT_LOOKS:
            values = _table_look_values(settings, dims_key)
            if values:
                ELEMENT_LOOKS[f"table:{dims_key}"] = table_state(values)


def apply_saved(window: QWidget, settings: dict | None = None) -> None:
    """Reapplique a `window` les overrides de ses textes, titres et toggles (construction, ou apres un
    restylage general qui les aurait ecrases)."""
    settings = settings if settings is not None else load_settings()
    overrides = settings.get(KEY) or {}
    if not overrides:
        return
    scope = _scope_of(window)
    toggles = None
    for element, override in overrides.items():
        if not override:
            continue
        values = merged(settings, override)
        if element.startswith(f"text:{scope}:"):
            label = widget_at_path(window, element[len(f"text:{scope}:"):])
            if is_text_widget(label):
                target = TextTarget(element, label, "")
                apply_text_look(label, merged(target.general(settings), override))
        elif element.startswith("title:"):
            for node in _title_nodes(window):
                if f"title:{_title_key(node) or ''}" == element:
                    apply_title_look(node, title_state(values, getattr(node, "_level", 1)), getattr(node, "_level", 1))
        elif element.startswith("toggle:"):
            if toggles is None:
                toggles = {toggle_id(t, window): t for t in window.findChildren(_Toggle)}
            toggle = toggles.get(element)
            if toggle is not None:
                apply_toggle_look(toggle, values, getattr(toggle, "_look_prefix", None) or toggle._style_key())


def _title_nodes(window: QWidget) -> list:
    try:
        from settings_layout import _Section, _SubSection
    except ImportError:
        return []
    return window.findChildren(_Section) + window.findChildren(_SubSection)


def reapply_soon(window: QWidget, settings: dict | None = None) -> None:
    """apply_saved au prochain passage de la boucle (apres le restylage en cours). Sans override
    enregistre : rien (appele a chaque restylage en direct)."""
    if settings is not None and not settings.get(KEY):
        return
    QTimer.singleShot(0, lambda w=window, s=settings: _safe_apply(w, s))


def _safe_apply(window, settings):
    try:
        apply_saved(window, settings)
    except RuntimeError:
        pass
