"""Moteur de calcul (SANS Qt) : pont entre le modèle (`document.Workbook`) et formualizer.

Choix (2026-10-30, évaluation dans `docs/agents/fm_tableur.md`) : formualizer 0.13 (moteur Rust, licences MIT /
Apache-2.0, roue Windows) — graphe de dépendances INCRÉMENTAL (une cellule modifiée : seules ses dépendantes sont
recalculées, ~0,4 ms), références circulaires (#CIRC!), tableaux dynamiques (#SPILL!, FILTER, SEQUENCE, LET…),
fonctions volatiles, ~0,3 µs par lecture de valeur. Aucun `eval` : la formule est analysée par le moteur.

Le MODÈLE reste la source de vérité (formules, valeurs saisies, styles) ; le moteur n'en est qu'un miroir pour le
calcul : chaque modification lui est poussée (`push`), puis `recalc` (mode automatique). Ce que formualizer ne sait
pas faire est fait ici : supprimer / renommer une feuille (moteur reconstruit, `rebuild`), noms définis (développés
dans la formule envoyée au moteur ; le modèle garde le nom). Sans formualizer installé : `available` est faux, les
formules gardent leur dernière valeur connue (celle du fichier importé) et l'interface le signale."""
from __future__ import annotations

import re
import time

from . import values as V
from .document import Cell, Workbook

try:                                                   # dépendance déclarée dans requirements.txt
    import formualizer as fz
except Exception:                                      # noqa: BLE001 - absent ou cassé : mode dégradé signalé
    fz = None

MAX_EVAL_MS = 20_000                                   # garde-fou : calcul interminable interrompu
BATCH_MIN = 300                                        # au-delà : écriture par lots (voir CalcEngine._write)
BAND_ROWS = 512
SCRATCH = "__fm_tableur_eval__"                        # feuille du moteur réservée aux formules hors cellule
_MISSING = object()


def engine_version() -> str | None:
    if fz is None:
        return None
    try:
        from importlib.metadata import version
        return version("formualizer")
    except Exception:                                  # noqa: BLE001
        return "?"


def _literal(value):
    L = fz.LiteralValue
    if value is None:
        return L.empty()
    if isinstance(value, bool):
        return L.boolean(value)
    if isinstance(value, int):
        return L.number(float(value))
    if isinstance(value, float):
        return L.number(value)
    if isinstance(value, V.XLError):
        kind = V.CODE_TO_KIND.get(value.code, "Value")
        try:
            return L.error(kind, value.message or "")
        except Exception:                              # noqa: BLE001 - genre inconnu du moteur
            return L.error("Value", value.code)
    return L.text(str(value))


_IDENT = re.compile(r"[A-Za-z_\\À-￿][\w.À-￿]*")


def expand_names(formula: str, names: dict[str, str]) -> str:
    """Noms définis remplacés par leur référence (entre parenthèses) ; chaînes et noms de feuille respectés."""
    if not names:
        return formula
    lower = {k.lower(): v for k, v in names.items()}
    out = []
    i = 0
    n = len(formula)
    while i < n:
        ch = formula[i]
        if ch in "\"'":
            j = i + 1
            while j < n:
                if formula[j] == ch:
                    if j + 1 < n and formula[j + 1] == ch:
                        j += 2
                        continue
                    break
                j += 1
            out.append(formula[i:j + 1])
            i = j + 1
            continue
        m = _IDENT.match(formula, i)
        prev = formula[i - 1] if i else ""
        if m and not (prev and (prev.isalnum() or prev in "_.$!")):
            word = m.group(0)
            nxt = formula[m.end()] if m.end() < n else ""
            target = lower.get(word.lower())
            if target is not None and not (nxt and nxt in "(!"):
                body = target[1:] if target.startswith("=") else target
                out.append("(" + body + ")")
            else:
                out.append(word)
            i = m.end()
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def check_formula(formula: str) -> str | None:
    """Message si la formule n'est pas valable (parenthèses, opérateurs…), sinon None."""
    if fz is None:
        return None
    try:
        fz.parse(formula)
    except Exception as exc:                           # noqa: BLE001 - message du moteur montré tel quel
        return str(exc) or "Formule non valable."
    depth = 0
    in_str = False
    for ch in formula:
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            depth += ch == "("
            depth -= ch == ")"
            if depth < 0:
                return "Parenthèse fermante en trop."
    if depth > 0:
        return "Parenthèse fermante manquante."
    if in_str:
        return "Guillemet fermant manquant."
    return None


# Formules qui peuvent DÉBORDER (tableaux dynamiques). formualizer 0.13 ne recalcule pas une telle formule quand une
# cellule de sa zone de débordement change (obstacle posé / retiré : #SPILL! resté ou manquant, vérifié) : après
# toute modification de leur feuille, ces formules sont reposées (peu nombreuses) pour être recalculées.
_DYNAMIC = re.compile(
    r"\b(SEQUENCE|FILTER|SORT|SORTBY|UNIQUE|RANDARRAY|TRANSPOSE|MMULT|MINVERSE|TEXTSPLIT|VSTACK|HSTACK|TOCOL"
    r"|TOROW|WRAPROWS|WRAPCOLS|TAKE|DROP|CHOOSECOLS|CHOOSEROWS|EXPAND|MAP|SCAN|MAKEARRAY|BYROW|BYCOL|FREQUENCY"
    r"|LINEST|LOGEST|TREND|GROWTH|OFFSET|INDIRECT)\s*\(|[-+*/^&=<>]\s*\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+"
    r"|\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+\s*[-+*/^&<>]|^=\s*\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+\s*$",
    re.I)


class CalcEngine:
    def __init__(self, book: Workbook):
        self.book = book
        self.available = fz is not None
        self.error: str | None = None if self.available else "moteur de calcul absent (paquet formualizer)"
        self.last_ms = 0.0                              # durée du dernier calcul (barre d'état, mesures)
        self._wb = None
        self._sheets: dict[str, object] = {}
        self._anchors: dict[int, set] = {}              # feuille -> formules qui peuvent déborder
        self._table_names: list[str] = []
        self.hold_tables = False                        # vrai : l'appelant retraduit lui-même (entête renommée)
        self._dirty = True
        book.engine = self
        self.rebuild()

    # -- construction --
    def rebuild(self):
        """Moteur refait depuis le modèle : ouverture, feuille supprimée / renommée (formualizer ne sait pas)."""
        if not self.available:
            return
        try:
            config = fz.WorkbookConfig(mode=fz.WorkbookMode.Interactive)
            try:
                ec = fz.EvaluationConfig()
                ec.max_eval_time_ms = MAX_EVAL_MS
                config.eval_config = ec
            except Exception:                          # noqa: BLE001 - option absente : sans garde-fou
                pass
            self._wb = fz.Workbook(config=config)
        except Exception:                              # noqa: BLE001
            self._wb = fz.Workbook()
        from . import extra_functions
        extra_functions.register(self._wb, fz)            # MMULT, MINVERSE, DISC… absentes de formualizer 0.13
        self._sheets = {}
        self._anchors = {}
        from .structured import all_tables
        self._table_names = [t["name"] for _s, t in all_tables(self.book)]
        for sheet in self.book.sheets:
            self._ensure_sheet(sheet.name)
        for sheet in self.book.sheets:
            engine_sheet = self._sheets[sheet.name.lower()]
            self._write(engine_sheet, sheet, list(sheet.cells), empty_ok=True)
            anchors = {k for k, cell in sheet.cells.items() if cell.formula and _DYNAMIC.search(cell.formula)}
            if anchors:
                self._anchors[sheet.uid] = anchors
        self._dirty = True
        self.recalc()

    def _write(self, engine_sheet, sheet, keys, empty_ok=False):
        """Cellules `keys` du modèle -> moteur. Beaucoup de cellules : par BANDES de lignes, les constantes en UN
        lot rectangulaire (`set_values_batch`) puis les formules une à une — cellule par cellule, 100 000 valeurs
        coûtaient ~2,1 s, en lots ~0,15-0,4 s (mesure de la sonde, formualizer 0.13). `empty_ok` : moteur neuf
        (les cellules absentes du modèle sont déjà vides)."""
        cells = sheet.cells
        if len(keys) < BATCH_MIN:
            for row, col in keys:
                self._set(sheet, engine_sheet, row, col, cells.get((row, col)))
            return
        empty = fz.LiteralValue.empty()
        bands: dict[int, list] = {}
        for key in keys:
            bands.setdefault(key[0] // BAND_ROWS, []).append(key)
        for band in bands.values():
            r0 = min(k[0] for k in band)
            r1 = max(k[0] for k in band)
            c0 = min(k[1] for k in band)
            c1 = max(k[1] for k in band)
            area = (r1 - r0 + 1) * (c1 - c0 + 1)
            if area > 4 * len(band) + 64:                   # bande trop creuse : cellule par cellule
                for row, col in band:
                    self._set(sheet, engine_sheet, row, col, cells.get((row, col)))
                continue
            wanted = set(band)
            formulas = []
            rows = []
            for r in range(r0, r1 + 1):
                line = []
                for c in range(c0, c1 + 1):
                    cell = cells.get((r, c))
                    if cell is None or cell.formula or cell.value is None:
                        line.append(empty)
                        if cell is not None and cell.formula and ((r, c) in wanted or not empty_ok):
                            formulas.append((r, c, cell))
                    else:
                        line.append(_literal(cell.value))
                rows.append(line)
            try:
                engine_sheet.set_values_batch(r0 + 1, c0 + 1, r1 - r0 + 1, c1 - c0 + 1, rows)
            except Exception:                              # noqa: BLE001 - lot refusé : cellule par cellule
                for row, col in band:
                    self._set(sheet, engine_sheet, row, col, cells.get((row, col)))
                continue
            for r, c, cell in formulas:
                self._set(sheet, engine_sheet, r, c, cell)

    def _ensure_sheet(self, name: str):
        key = name.lower()
        found = self._sheets.get(key)
        if found is None:
            if name not in self._wb.sheet_names:
                self._wb.add_sheet(name)
            found = self._wb.sheet(name)
            self._sheets[key] = found
        return found

    def _set(self, sheet, engine_sheet, row: int, col: int, cell: Cell | None):
        try:
            if cell is None or (cell.value is None and not cell.formula):
                engine_sheet.set_value(row + 1, col + 1, fz.LiteralValue.empty())
            elif cell.formula:
                text = expand_names(cell.formula, self.book.names)
                if "[" in text or self._table_names:
                    from .structured import resolve            # références structurées -> plages A1
                    text = resolve(text, self.book, sheet, row, col)
                engine_sheet.set_formula(row + 1, col + 1, text)
            else:
                engine_sheet.set_value(row + 1, col + 1, _literal(cell.value))
        except Exception as exc:                       # noqa: BLE001 - formule refusée : #NAME? / #VALUE! en valeur
            # le moteur annonce parfois le code dans son message (« #CIRC!: Self-reference detected »)
            found = re.search(r"#[A-Z0-9/]+[!?]?", str(exc))
            kind = V.CODE_TO_KIND.get(found.group(0), "Error") if found else "Error"
            try:
                engine_sheet.set_value(row + 1, col + 1, fz.LiteralValue.error(kind, str(exc)[:200]))
            except Exception:                          # noqa: BLE001
                pass

    # -- mises à jour --
    def push(self, sheet, keys):
        """Cellules (ligne, colonne) de `sheet` modifiées dans le modèle -> moteur."""
        if not self.available:
            return
        engine_sheet = self._ensure_sheet(sheet.name)
        cells = sheet.cells
        anchors = self._anchors.setdefault(sheet.uid, set())
        keys = list(keys)
        self._write(engine_sheet, sheet, keys)
        for key in keys:
            cell = cells.get(key)
            if cell is not None and cell.formula and _DYNAMIC.search(cell.formula):
                anchors.add(key)
            else:
                anchors.discard(key)
        for row, col in anchors:
            self._set(sheet, engine_sheet, row, col, cells.get((row, col)))
        if sheet.tables and not self.hold_tables and len(keys) < 5000 and any(
                t.get("header", True) and t["ref"][0] == r and t["ref"][1] <= c <= t["ref"][3]
                for r, c in keys for t in sheet.tables):
            self.tables_changed()                          # entête modifiée : noms de colonnes changés
        self._dirty = True

    def tables_changed(self, size_only: bool = False):
        """Tableaux créés / redimensionnés / renommés / entêtes changées : les formules à références structurées
        (ou qui citent un nom de tableau) sont retraduites et renvoyées au moteur. `size_only` (le tableau a
        seulement grandi / rétréci) : les formules « ligne courante » ([@Col]) ne changent pas, elles sont sautées
        (tableau de 10 000 lignes : ~0,9 s -> quelques ms)."""
        if not self.available:
            return
        from .structured import all_tables, has_structured, row_only
        self._table_names = [t["name"] for _s, t in all_tables(self.book)]
        names = self._table_names
        for sheet in self.book.sheets:
            keys = [k for k, cell in sheet.cells.items() if cell.formula and has_structured(cell.formula, self.book)
                    and not (size_only and row_only(cell.formula, names))]
            if keys:
                engine_sheet = self._ensure_sheet(sheet.name)
                for row, col in keys:
                    self._set(sheet, engine_sheet, row, col, sheet.cells.get((row, col)))
        self._dirty = True

    def add_sheet(self, sheet):
        if self.available:
            if sheet.name.lower() in self._sheets or sheet.name in self._wb.sheet_names:
                self.rebuild()                         # nom déjà connu du moteur (feuille supprimée puis recréée)
                return
            self._ensure_sheet(sheet.name)
            self.push(sheet, list(sheet.cells))

    def names_changed(self):
        self.rebuild()

    def recalc(self, force: bool = False) -> bool:
        """Calcul des cellules à refaire (incrémental). Rend vrai si un calcul a eu lieu."""
        if not self.available or not (self._dirty or force):
            return False
        start = time.perf_counter()
        try:
            self._wb.evaluate_all()
            self.error = None
        except Exception as exc:                       # noqa: BLE001 - calcul interrompu (garde-fou), signalé
            self.error = f"calcul interrompu : {exc}"
        self.last_ms = (time.perf_counter() - start) * 1000
        self._dirty = False
        return True

    def evaluate(self, sheet, formula: str):
        """Valeur d'une formule HORS cellule (mise en forme conditionnelle, validation) : posée dans une feuille du
        moteur réservée, ses références sans feuille rapportées à `sheet`. Gardée tant que rien ne change."""
        if not self.available:
            return None
        memo = getattr(self, "_eval_memo", None)
        key = (self.book.revision, self.last_ms)
        if memo is None or memo[0] != key:
            memo = self._eval_memo = (key, {})
        found = memo[1].get((sheet.uid, formula), _MISSING)
        if found is not _MISSING:
            return found
        from . import refs as R
        qualified = R.rewrite(formula, lambda ref: ref.text() if ref.sheet is not None else
                              R.quote_sheet(sheet.name) + "!" + ref.text())
        scratch = self._ensure_sheet(SCRATCH)
        try:
            scratch.set_formula(1, 1, expand_names(qualified, self.book.names))
            value = V.from_engine(self._wb.evaluate_cell(SCRATCH, 1, 1))
        except Exception as exc:                       # noqa: BLE001 - formule refusée : erreur affichable
            value = V.XLError("#VALUE!", str(exc)[:200])
        memo[1][(sheet.uid, formula)] = value
        return value

    # -- lecture --
    def raw(self, sheet, row: int, col: int):
        if not self.available:
            return None
        try:
            return self._wb.get_value(sheet.name, row + 1, col + 1)
        except Exception:                              # noqa: BLE001
            return None

    def value(self, sheet, row: int, col: int):
        """Valeur calculée (modèle si pas de moteur)."""
        if not self.available:
            cell = sheet.cells.get((row, col))
            return cell.value if cell is not None else None
        return V.from_engine(self.raw(sheet, row, col))


def cell_value(book: Workbook, sheet, row: int, col: int):
    """Valeur affichée d'une cellule : constante du modèle, ou résultat du moteur (formules, débordements)."""
    cell = sheet.cells.get((row, col))
    if cell is not None and not cell.formula:
        return cell.value
    engine = book.engine
    if engine is None or not engine.available:
        return cell.value if cell is not None else None
    return engine.value(sheet, row, col)
