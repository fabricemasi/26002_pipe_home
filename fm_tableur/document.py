"""Modèle du classeur (SANS Qt) : classeur -> feuilles -> cellules éparses.

- `Cell` : valeur typée, formule (texte « =… », syntaxe d'Excel en anglais), style (indice dans la table de
  styles du classeur). Une cellule est IMMUABLE par convention : toute modification la remplace (les commandes
  d'annulation gardent les anciennes sans copie). Pour une cellule à formule, `value` = dernier résultat connu
  (lu dans un .xlsx ou calculé) : sert d'affichage quand le moteur est absent et de valeur en cache à l'export.
- Stockage ÉPARS : `Sheet.cells` = {(ligne, colonne): Cell} ; une feuille vide ne coûte rien, 1 048 576 x 16 384.
- `Axis` : tailles des lignes / colonnes (défaut + exceptions + masquées) ; position <-> indice en O(log n).
- `StyleTable` : styles dédoublonnés (un dictionnaire figé par style, la cellule n'en garde que l'indice).
Les modifications passent par `commands.py` (annulation) ; le calcul par `engine.py`."""
from __future__ import annotations

import bisect
import copy
import itertools

from .refs import MAX_COLS, MAX_ROWS

DEFAULT_ROW_HEIGHT = 20.0           # pixels à 100 % (Excel : 15 points = 20 px)
DEFAULT_COL_WIDTH = 64.0            # pixels à 100 % (Excel : 8,43 caractères = 64 px)
DEFAULT_FONT = ("Calibri", 11.0)

# Clés d'un style (absente = valeur par défaut) :
#   font, size, bold, italic, underline, strike, color (#rrggbb), fill (#rrggbb), halign (left / center / right /
#   fill / justify / centerContinuous / general), valign (top / center / bottom), wrap, fmt (code de format), indent,
#   rotation, border_l / border_r / border_t / border_b ((style, couleur)), locked, hidden_formula
STYLE_KEYS = ("font", "size", "bold", "italic", "underline", "strike", "color", "fill", "halign", "valign", "wrap",
              "fmt", "indent", "rotation", "border_l", "border_r", "border_t", "border_b", "locked", "hidden_formula",
              "shrink")


class Cell:
    __slots__ = ("value", "formula", "style")

    def __init__(self, value=None, formula: str | None = None, style: int = 0):
        self.value = value
        self.formula = formula
        self.style = style

    def is_blank(self) -> bool:
        return self.value is None and self.formula is None

    def with_(self, **changes) -> "Cell":
        return Cell(changes.get("value", self.value), changes.get("formula", self.formula),
                    changes.get("style", self.style))

    def __eq__(self, other):
        return (isinstance(other, Cell) and self.value == other.value and self.formula == other.formula
                and self.style == other.style and type(self.value) is type(other.value))

    def __repr__(self):
        return f"Cell({self.value!r}, {self.formula!r}, {self.style})"


class StyleTable:
    """Styles dédoublonnés : indice 0 = style par défaut (vide)."""

    def __init__(self):
        self._styles: list[dict] = [{}]
        self._index: dict[tuple, int] = {(): 0}

    def intern(self, style: dict) -> int:
        clean = {k: v for k, v in style.items() if v not in (None, False, "", 0) or k in ("rotation",) and v}
        key = tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in clean.items()))
        found = self._index.get(key)
        if found is not None:
            return found
        self._styles.append({k: (tuple(v) if isinstance(v, list) else v) for k, v in clean.items()})
        self._index[key] = len(self._styles) - 1
        return len(self._styles) - 1

    def get(self, index: int) -> dict:
        try:
            return self._styles[index]
        except (IndexError, TypeError):
            return self._styles[0]

    def merged(self, index: int, changes: dict) -> int:
        """Style `index` modifié par `changes` (valeur None = clé retirée)."""
        style = dict(self.get(index))
        for key, value in changes.items():
            if value is None:
                style.pop(key, None)
            else:
                style[key] = value
        return self.intern(style)

    def __len__(self):
        return len(self._styles)

    def to_list(self) -> list[dict]:
        return [{k: (list(v) if isinstance(v, tuple) else v) for k, v in s.items()} for s in self._styles]

    @classmethod
    def from_list(cls, items) -> "StyleTable":
        table = cls()
        table._styles = [{}]
        table._index = {(): 0}
        for raw in items or []:
            if not isinstance(raw, dict):
                raw = {}
            style = {k: (tuple(v) if isinstance(v, list) else v) for k, v in raw.items() if k in STYLE_KEYS}
            key = tuple(sorted(style.items()))
            if not table._styles[0] and not style and len(table._styles) == 1 and key == ():
                continue                                     # l'indice 0 (défaut) est déjà là
            table._styles.append(style)
            table._index.setdefault(key, len(table._styles) - 1)
        return table


class Axis:
    """Tailles d'une dimension (lignes ou colonnes) : défaut + exceptions + indices masqués ; styles par ligne /
    colonne entière (mise en forme d'une colonne sans créer un million de cellules)."""

    def __init__(self, default: float, count: int):
        self.default = float(default)
        self.count = count
        self.sizes: dict[int, float] = {}
        self.hidden: set[int] = set()
        self.styles: dict[int, int] = {}
        self._keys: list[int] | None = None
        self._prefix: list[float] = []

    def copy(self) -> "Axis":
        other = Axis(self.default, self.count)
        other.sizes = dict(self.sizes)
        other.hidden = set(self.hidden)
        other.styles = dict(self.styles)
        return other

    def state(self) -> tuple:
        return dict(self.sizes), set(self.hidden), dict(self.styles), self.default

    def restore(self, state: tuple):
        self.sizes, self.hidden, self.styles, self.default = dict(state[0]), set(state[1]), dict(state[2]), state[3]
        self.changed()

    def changed(self):
        self._keys = None

    def _index(self):
        if self._keys is None:
            keys = sorted(set(self.sizes) | self.hidden)
            prefix = [0.0]
            for k in keys:
                prefix.append(prefix[-1] + self.size(k) - self.default)
            self._keys, self._prefix = keys, prefix
        return self._keys, self._prefix

    def size(self, index: int) -> float:
        if index in self.hidden:
            return 0.0
        return self.sizes.get(index, self.default)

    def raw_size(self, index: int) -> float:
        return self.sizes.get(index, self.default)

    def pos(self, index: int) -> float:
        """Début de `index` en pixels (à 100 %)."""
        keys, prefix = self._index()
        k = bisect.bisect_left(keys, index)
        return index * self.default + prefix[k]

    def total(self) -> float:
        return self.pos(self.count)

    def index_at(self, pixel: float) -> int:
        """Indice dont la zone contient `pixel` (les indices masqués sont sautés)."""
        if pixel <= 0:
            index = 0
        else:
            keys, prefix = self._index()
            lo, hi = 0, len(keys)
            # dernier indice spécial dont le début <= pixel
            while lo < hi:
                mid = (lo + hi) // 2
                if keys[mid] * self.default + prefix[mid] <= pixel:
                    lo = mid + 1
                else:
                    hi = mid
            if lo == 0:
                index = int(pixel // self.default)
            else:
                k = lo - 1
                start = keys[k] * self.default + prefix[k]
                end = start + self.size(keys[k])
                if pixel < end:
                    index = keys[k]
                else:
                    index = keys[k] + 1 + int((pixel - end) // self.default)
                    nxt = keys[k + 1] if k + 1 < len(keys) else None
                    if nxt is not None and index > nxt:
                        index = nxt
        index = max(0, min(self.count - 1, index))
        while index < self.count - 1 and self.size(index) == 0:
            index += 1
        return index

    def next_visible(self, index: int, step: int) -> int:
        """Indice visible suivant (step = +1 / -1), borné."""
        i = index + step
        while 0 <= i < self.count and i in self.hidden:
            i += step
        return max(0, min(self.count - 1, i if 0 <= i < self.count else index))

    # -- insertions / suppressions --
    def insert(self, at: int, count: int):
        self.sizes = {(k + count if k >= at else k): v for k, v in self.sizes.items() if k + count < self.count
                      or k < at}
        self.hidden = {(k + count if k >= at else k) for k in self.hidden}
        self.styles = {(k + count if k >= at else k): v for k, v in self.styles.items()}
        self.changed()

    def delete(self, at: int, count: int):
        def move(d):
            return {(k - count if k >= at + count else k): v for k, v in d.items() if not at <= k < at + count}
        self.sizes = move(self.sizes)
        self.styles = move(self.styles)
        self.hidden = {(k - count if k >= at + count else k) for k in self.hidden if not at <= k < at + count}
        self.changed()


_SHEET_IDS = itertools.count(1)


class Sheet:
    def __init__(self, name: str):
        self.uid = next(_SHEET_IDS)             # identifiant de session (le nom peut changer)
        self.name = name
        self.cells: dict[tuple[int, int], Cell] = {}
        self.rows = Axis(DEFAULT_ROW_HEIGHT, MAX_ROWS)
        self.cols = Axis(DEFAULT_COL_WIDTH, MAX_COLS)
        self.merges: list[tuple[int, int, int, int]] = []
        self.freeze = (0, 0)                    # lignes, colonnes figées
        self.show_grid = True
        self.zoom = 1.0
        self.tab_color: str | None = None
        self.hidden = False
        self.comments: dict[tuple[int, int], str] = {}
        self.cond_formats: list[dict] = []      # mises en forme conditionnelles (voir condfmt.py)
        self.validations: list[dict] = []       # validations de données (listes déroulantes…)
        self.charts: list[dict] = []            # graphiques liés aux données (voir charts.py)
        self.tables: list[dict] = []            # tableaux structurés (voir structured.py)
        self.autofilter: tuple[int, int, int, int] | None = None
        self.filters: dict[int, dict] = {}      # colonne -> critère du filtre automatique
        self.protected = False
        self.extra: dict = {}                   # données inconnues gardées telles quelles
        self._bounds = None

    # -- cellules --
    def cell(self, row: int, col: int) -> Cell | None:
        return self.cells.get((row, col))

    def put(self, row: int, col: int, cell: Cell | None):
        """Pose (ou retire, None / cellule vide sans style) une cellule. Bas niveau : passer par les commandes."""
        if cell is None or (cell.is_blank() and not cell.style):
            if self.cells.pop((row, col), None) is not None:
                self._bounds = None
        else:
            if (row, col) not in self.cells:
                b = self._bounds
                if b is not None:
                    self._bounds = (min(b[0], row), min(b[1], col), max(b[2], row), max(b[3], col))
            self.cells[(row, col)] = cell

    def used_range(self) -> tuple[int, int, int, int] | None:
        """(r0, c0, r1, c1) des cellules non vides (styles compris), None si la feuille est vide."""
        if self._bounds is None and self.cells:
            rows = [k[0] for k in self.cells]
            cols = [k[1] for k in self.cells]
            self._bounds = (min(rows), min(cols), max(rows), max(cols))
        return self._bounds if self.cells else None

    def invalidate_bounds(self):
        self._bounds = None

    def merge_at(self, row: int, col: int):
        """Fusion qui contient (row, col), ou None."""
        for m in self.merges:
            if m[0] <= row <= m[2] and m[1] <= col <= m[3]:
                return m
        return None

    def style_index(self, row: int, col: int) -> int:
        cell = self.cells.get((row, col))
        if cell is not None and cell.style:
            return cell.style
        return self.rows.styles.get(row) or self.cols.styles.get(col) or 0

    def state(self) -> dict:
        """Propriétés hors cellules (annulation des opérations de structure)."""
        return {"rows": self.rows.state(), "cols": self.cols.state(), "merges": list(self.merges),
                "freeze": self.freeze, "comments": dict(self.comments),
                "cond_formats": copy.deepcopy(self.cond_formats), "validations": copy.deepcopy(self.validations),
                "charts": copy.deepcopy(self.charts), "tables": copy.deepcopy(self.tables),
                "autofilter": self.autofilter,
                "filters": copy.deepcopy(self.filters)}

    def restore(self, state: dict):
        self.rows.restore(state["rows"])
        self.cols.restore(state["cols"])
        self.merges = list(state["merges"])
        self.freeze = state["freeze"]
        self.comments = dict(state["comments"])
        self.cond_formats = copy.deepcopy(state["cond_formats"])
        self.validations = copy.deepcopy(state["validations"])
        self.charts = copy.deepcopy(state["charts"])
        self.tables = copy.deepcopy(state.get("tables", []))
        self.autofilter = state["autofilter"]
        self.filters = copy.deepcopy(state["filters"])


class Workbook:
    """Classeur : feuilles ordonnées, table de styles, noms définis, mode de calcul.

    `listeners` : fonctions appelées avec un événement après chaque modification (`notify`) :
    ("cells", feuille), ("structure", feuille), ("sheets", None), ("view", feuille)."""

    def __init__(self):
        self.sheets: list[Sheet] = []
        self.styles = StyleTable()
        self.names: dict[str, str] = {}         # nom défini -> référence / expression (« Feuil1!$A$1:$A$10 »)
        self.calc_mode = "auto"                 # « auto » / « manual »
        self.date_1904 = False
        self.default_font = DEFAULT_FONT
        self.revision = 0                        # augmente à chaque modification (cache de sérialisation)
        self.extra: dict = {}                    # données inconnues gardées telles quelles
        self.source: dict = {}                   # origine (fichier importé, éléments perdus signalés)
        self.listeners: list = []
        self.engine = None                       # engine.CalcEngine, posé par l'appelant

    # -- feuilles --
    def sheet(self, name: str) -> Sheet | None:
        low = name.lower()
        for s in self.sheets:
            if s.name.lower() == low:
                return s
        return None

    def sheet_by_uid(self, uid: int) -> Sheet | None:
        for s in self.sheets:
            if s.uid == uid:
                return s
        return None

    def index_of(self, sheet: Sheet) -> int:
        return self.sheets.index(sheet)

    def unique_name(self, base: str = "Feuil") -> str:
        names = {s.name.lower() for s in self.sheets}
        if base.lower() not in names and base != "Feuil":
            return base
        for i in itertools.count(1):
            name = f"{base}{i}" if base == "Feuil" else f"{base} ({i})"
            if name.lower() not in names:
                return name
        return base

    def add_sheet(self, name: str | None = None, index: int | None = None) -> Sheet:
        """Bas niveau (sans annulation) : construction, import."""
        sheet = Sheet(name or self.unique_name())
        if index is None:
            self.sheets.append(sheet)
        else:
            self.sheets.insert(index, sheet)
        return sheet

    # -- notifications --
    def notify(self, kind: str, sheet: Sheet | None = None):
        if kind not in ("active", "selection"):          # navigation : le contenu n'a pas changé
            self.revision += 1
        for listener in list(self.listeners):
            listener(kind, sheet)

    # -- lecture --
    def style_of(self, sheet: Sheet, row: int, col: int) -> dict:
        return self.styles.get(sheet.style_index(row, col))

    def formula_cells(self):
        """(feuille, (ligne, colonne), cellule) de toutes les formules."""
        for sheet in self.sheets:
            for key, cell in sheet.cells.items():
                if cell.formula:
                    yield sheet, key, cell


# Nouveaux classeurs (Réglages : Board > Tableur > Nouveaux classeurs) : posé par `set_new_book_defaults`.
NEW_BOOK = {"font": DEFAULT_FONT, "calc_mode": "auto"}


def set_new_book_defaults(settings: dict | None) -> None:
    """Police et mode de calcul des classeurs créés ensuite (clés `tableur_font_*`, `tableur_calc_mode`)."""
    get = (settings or {}).get
    family = str(get("tableur_font_family") or "").strip() or DEFAULT_FONT[0]
    try:
        size = max(1.0, min(409.0, float(get("tableur_font_size") or DEFAULT_FONT[1])))
    except (TypeError, ValueError):
        size = DEFAULT_FONT[1]
    NEW_BOOK["font"] = (family, size)
    NEW_BOOK["calc_mode"] = "manual" if get("tableur_calc_mode") == "manual" else "auto"


def new_workbook(sheets: int = 1) -> Workbook:
    book = Workbook()
    book.default_font = NEW_BOOK["font"]
    book.calc_mode = NEW_BOOK["calc_mode"]
    for _ in range(max(1, sheets)):
        book.add_sheet()
    return book


def valid_sheet_name(name: str, book: Workbook, current: Sheet | None = None) -> str | None:
    """Message d'erreur si le nom est refusé par Excel (sinon None)."""
    name = name.strip() if name else ""
    if not name:
        return "Le nom d'une feuille ne peut pas être vide."
    if len(name) > 31:
        return "31 caractères au plus."
    bad = set('[]:*?/\\') & set(name)
    if bad:
        return "Caractères interdits : " + " ".join(sorted(bad))
    if name.startswith("'") or name.endswith("'"):
        return "Pas d'apostrophe au début ni à la fin."
    other = book.sheet(name)
    if other is not None and other is not current:
        return "Une feuille porte déjà ce nom."
    if name.lower() == "historique":
        return "« Historique » est un nom réservé par Excel."
    return None
