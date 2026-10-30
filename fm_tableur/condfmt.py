"""Mise en forme conditionnelle (règles d'une feuille, `Sheet.cond_formats`), évaluée à la peinture.

Règle = dictionnaire : `ranges` [(r0, c0, r1, c1)], `type` :
- « cell » : `op` (between, notBetween, equal, notEqual, greaterThan, lessThan, greaterThanOrEqual,
  lessThanOrEqual), `value` (et `value2`) — nombres ou textes ;
- « text » : `op` (contains, notContains, beginsWith, endsWith), `value` ;
- « formula » : `formula` écrite pour la cellule en haut à gauche de la 1re plage (références relatives recopiées) ;
- « duplicate » / « unique » ; « top » / « bottom » (`rank`, `percent`) ; « above_average » / « below_average » ;
- « blank » / « not_blank » ; « error » ;
- « bar » (barre de données : `color`) ; « scale » (échelle : `colors` = [min, max] ou [min, milieu, max]).
`style` : {fill, color, bold, italic, underline, strike} appliqué quand la règle est vraie ; `stop` : arrête les
règles suivantes. Ordre : la 1re règle vraie l'emporte pour chaque clé (Excel). Calculs par règle (min / max,
doublons, seuils) faits UNE fois par peinture."""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from . import refs as R
from . import values as V
from .engine import cell_value

TYPES = [("cell", "Valeur de la cellule"), ("text", "Texte qui contient"), ("formula", "Formule"),
         ("duplicate", "Valeurs en double"), ("unique", "Valeurs uniques"), ("top", "Valeurs les plus élevées"),
         ("bottom", "Valeurs les plus faibles"), ("above_average", "Au-dessus de la moyenne"),
         ("below_average", "En dessous de la moyenne"), ("blank", "Cellules vides"), ("error", "Erreurs"),
         ("bar", "Barres de données"), ("scale", "Échelle de couleurs")]


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            return None
    return None


def _in(ranges, r, c):
    for r0, c0, r1, c1 in ranges:
        if r0 <= r <= r1 and c0 <= c <= c1:
            return True
    return False


def _range_values(book, sheet, ranges, limit=200_000):
    out = []
    for r0, c0, r1, c1 in ranges:
        if (r1 - r0 + 1) * (c1 - c0 + 1) > limit:
            keys = [k for k in sheet.cells if r0 <= k[0] <= r1 and c0 <= k[1] <= c1]
        else:
            keys = [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]
        for r, c in keys:
            out.append(cell_value(book, sheet, r, c))
    return out


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


class Evaluator:
    def __init__(self, book, sheet, cache=None):
        self.book = book
        self.sheet = sheet
        self.rules = sheet.cond_formats
        self._stats: dict[int, dict] = {}
        self._memo: dict = {}

    def _stat(self, index, rule):
        found = self._stats.get(index)
        if found is not None:
            return found
        values = _range_values(self.book, self.sheet, rule.get("ranges", []))
        numbers = [n for n in (_number(v) if not isinstance(v, str) else None for v in values) if n is not None]
        stat = {"min": min(numbers) if numbers else 0.0, "max": max(numbers) if numbers else 0.0,
                "avg": sum(numbers) / len(numbers) if numbers else 0.0}
        if rule.get("type") in ("duplicate", "unique"):
            counts = {}
            for v in values:
                if v is None:
                    continue
                key = v.casefold() if isinstance(v, str) else v
                counts[key] = counts.get(key, 0) + 1
            stat["counts"] = counts
        if rule.get("type") in ("top", "bottom"):
            rank = int(rule.get("rank", 10) or 10)
            ordered = sorted(numbers, reverse=rule["type"] == "top")
            if rule.get("percent"):
                rank = max(1, int(len(ordered) * rank / 100))
            stat["threshold"] = ordered[min(rank, len(ordered)) - 1] if ordered else None
        if rule.get("type") == "scale" and len(rule.get("colors") or []) == 3:
            ordered = sorted(numbers)
            stat["mid"] = ordered[len(ordered) // 2] if ordered else 0.0
        self._stats[index] = stat
        return stat

    def _true(self, index, rule, r, c) -> bool:
        kind = rule.get("type")
        value = cell_value(self.book, self.sheet, r, c)
        if kind == "cell":
            a, b = rule.get("value"), rule.get("value2")
            n, na, nb = _number(value), _number(a), _number(b)
            op = rule.get("op", "greaterThan")
            if na is None:                                  # comparaison de textes
                left = str(value or "").casefold()
                right = str(a or "").casefold()
                return {"equal": left == right, "notEqual": left != right}.get(op, False)
            if n is None:
                return False
            return {"between": nb is not None and min(na, nb) <= n <= max(na, nb),
                    "notBetween": nb is not None and not (min(na, nb) <= n <= max(na, nb)),
                    "equal": n == na, "notEqual": n != na, "greaterThan": n > na, "lessThan": n < na,
                    "greaterThanOrEqual": n >= na, "lessThanOrEqual": n <= na}.get(op, False)
        if kind == "text":
            hay = str(value or "").casefold()
            needle = str(rule.get("value") or "").casefold()
            op = rule.get("op", "contains")
            return {"contains": needle in hay, "notContains": needle not in hay,
                    "beginsWith": hay.startswith(needle), "endsWith": hay.endswith(needle)}.get(op, False)
        if kind in ("duplicate", "unique"):
            if value is None:
                return False
            counts = self._stat(index, rule)["counts"]
            n = counts.get(value.casefold() if isinstance(value, str) else value, 0)
            return n > 1 if kind == "duplicate" else n == 1
        if kind in ("top", "bottom"):
            n = _number(value) if not isinstance(value, str) else None
            threshold = self._stat(index, rule).get("threshold")
            if n is None or threshold is None:
                return False
            return n >= threshold if kind == "top" else n <= threshold
        if kind in ("above_average", "below_average"):
            n = _number(value) if not isinstance(value, str) else None
            if n is None:
                return False
            avg = self._stat(index, rule)["avg"]
            return n > avg if kind == "above_average" else n < avg
        if kind == "blank":
            return value is None or value == ""
        if kind == "not_blank":
            return not (value is None or value == "")
        if kind == "error":
            return isinstance(value, V.XLError)
        if kind == "formula":
            formula = rule.get("formula") or ""
            first = (rule.get("ranges") or [(r, c, r, c)])[0]
            moved = R.translate(formula, r - first[0], c - first[1])
            engine = self.book.engine
            if engine is None or not engine.available:
                return False
            result = engine.evaluate(self.sheet, moved)
            if isinstance(result, bool):
                return result
            n = _number(result) if not isinstance(result, str) else None
            return bool(n)
        return False

    def style(self, r, c) -> dict:
        key = ("s", r, c)
        found = self._memo.get(key)
        if found is not None:
            return found
        out = {}
        for index, rule in enumerate(self.rules):
            if rule.get("type") in ("bar", "scale") or not _in(rule.get("ranges", []), r, c):
                continue
            if self._true(index, rule, r, c):
                for k, v in (rule.get("style") or {}).items():
                    out.setdefault(k, v)
                if rule.get("stop"):
                    break
        self._memo[key] = out
        return out

    def fill(self, r, c):
        st = self.style(r, c)
        if st.get("fill"):
            return st["fill"]
        for index, rule in enumerate(self.rules):
            if rule.get("type") == "scale" and _in(rule.get("ranges", []), r, c):
                n = _number(cell_value(self.book, self.sheet, r, c))
                if n is None:
                    continue
                stat = self._stat(index, rule)
                colors = [QColor(x) for x in (rule.get("colors") or ["#f8696b", "#63be7b"])]
                lo, hi = stat["min"], stat["max"]
                if len(colors) == 3:
                    mid = stat.get("mid", (lo + hi) / 2)
                    if n <= mid:
                        color = _mix(colors[0], colors[1], (n - lo) / (mid - lo) if mid > lo else 0)
                    else:
                        color = _mix(colors[1], colors[2], (n - mid) / (hi - mid) if hi > mid else 1)
                else:
                    color = _mix(colors[0], colors[-1], (n - lo) / (hi - lo) if hi > lo else 0)
                return color.name()
        return None

    def paint_bars(self, painter, visible):
        bars = [(i, rule) for i, rule in enumerate(self.rules) if rule.get("type") == "bar"]
        if not bars:
            return
        for r, c, _cell, x, y, w, h in visible:
            for index, rule in bars:
                if not _in(rule.get("ranges", []), r, c):
                    continue
                n = _number(cell_value(self.book, self.sheet, r, c))
                if n is None:
                    continue
                stat = self._stat(index, rule)
                lo, hi = min(0.0, stat["min"]), stat["max"]
                frac = (n - lo) / (hi - lo) if hi > lo else 0.0
                color = QColor(rule.get("color") or "#638ec6")
                color.setAlpha(170)
                painter.fillRect(QRectF(x + 2, y + 2, max(0.0, (w - 4) * frac), h - 4), color)
                break
