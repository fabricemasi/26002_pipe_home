"""Fonctions d'Excel ABSENTES de formualizer 0.13, ajoutées au moteur (`Workbook.register_function`, callbacks
Python ; jamais d'accès au classeur depuis un callback). Matrice : `tools/tableur_functions.py`.

MMULT, MINVERSE, MDETERM, MUNIT (matrices, débordent comme dans Excel), FVSCHEDULE, DISC, INTRATE (base de calcul
des jours 0 à 4 comme Excel). Résultats vérifiés contre les exemples de l'aide de Microsoft
(`tests/test_tableur_engine.py`, `ExtraFunctionsTest`)."""
from __future__ import annotations

import datetime as _dt

from . import numfmt


class _Num(Exception):
    pass


def _matrix(value):
    if not isinstance(value, list):
        value = [[value]]
    elif value and not isinstance(value[0], list):
        value = [value]
    out = []
    for row in value:
        line = []
        for v in row:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError("valeurs non numériques")
            line.append(float(v))
        out.append(line)
    if not out or any(len(r) != len(out[0]) for r in out):
        raise ValueError("matrice irrégulière")
    return out


def mmult(a, b):
    a, b = _matrix(a), _matrix(b)
    if len(a[0]) != len(b):
        raise ValueError("dimensions incompatibles")
    return [[sum(x * y for x, y in zip(row, col)) for col in zip(*b)] for row in a]


def _lu(m):
    n = len(m)
    if any(len(r) != n for r in m):
        raise ValueError("matrice non carrée")
    return [row[:] for row in m], n


def mdeterm(a):
    m, n = _lu(_matrix(a))
    det = 1.0
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(m[r][i]))
        if m[pivot][i] == 0:
            return 0.0
        if pivot != i:
            m[i], m[pivot] = m[pivot], m[i]
            det = -det
        det *= m[i][i]
        for r in range(i + 1, n):
            f = m[r][i] / m[i][i]
            for c in range(i, n):
                m[r][c] -= f * m[i][c]
    return det


def minverse(a):
    m, n = _lu(_matrix(a))
    aug = [row + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(aug[r][i]))
        if abs(aug[pivot][i]) < 1e-300:
            raise _Num("matrice singulière")
        aug[i], aug[pivot] = aug[pivot], aug[i]
        p = aug[i][i]
        aug[i] = [v / p for v in aug[i]]
        for r in range(n):
            if r != i and aug[r][i]:
                f = aug[r][i]
                aug[r] = [x - f * y for x, y in zip(aug[r], aug[i])]
    return [row[n:] for row in aug]


def munit(n):
    n = int(n)
    if n < 1:
        raise ValueError("dimension < 1")
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def fvschedule(principal, schedule):
    total = float(principal)
    for row in _matrix(schedule):
        for rate in row:
            total *= 1 + rate
    return total


def _date(value) -> _dt.date:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    when = numfmt.serial_to_datetime(float(int(value)))
    if when is None:
        raise ValueError("date non valable")
    return when.date()


def _days_360(a: _dt.date, b: _dt.date, european: bool) -> int:
    d1, d2 = a.day, b.day
    if european:
        d1, d2 = min(d1, 30), min(d2, 30)
    else:
        if d1 == 31:
            d1 = 30
        if d2 == 31 and d1 >= 30:
            d2 = 30
    return (b.year - a.year) * 360 + (b.month - a.month) * 30 + (d2 - d1)


def _year_basis(settlement: _dt.date, maturity: _dt.date, basis: int):
    """(jours entre les dates, jours dans l'année) selon la base d'Excel."""
    if basis == 0:
        return _days_360(settlement, maturity, False), 360
    if basis == 4:
        return _days_360(settlement, maturity, True), 360
    days = (maturity - settlement).days
    if basis == 2:
        return days, 360
    if basis == 3:
        return days, 365
    if basis == 1:
        years = range(settlement.year, maturity.year + 1)
        if maturity.year == settlement.year or (maturity - settlement).days <= 365:
            leap = any(_is_leap(y) for y in years) and _covers_feb29(settlement, maturity)
            return days, 366 if leap else 365
        total = sum(366 if _is_leap(y) else 365 for y in years)
        return days, total / len(years)
    raise _Num("base non valable")


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _covers_feb29(a, b):
    for year in range(a.year, b.year + 1):
        if _is_leap(year):
            feb29 = _dt.date(year, 2, 29)
            if a <= feb29 <= b:
                return True
    return False


def disc(settlement, maturity, pr, redemption, basis=0):
    s, m = _date(settlement), _date(maturity)
    if pr <= 0 or redemption <= 0 or s >= m:
        raise _Num("arguments hors limites")
    days, year = _year_basis(s, m, int(basis or 0))
    return (redemption - pr) / redemption * year / days


def intrate(settlement, maturity, investment, redemption, basis=0):
    s, m = _date(settlement), _date(maturity)
    if investment <= 0 or redemption <= 0 or s >= m:
        raise _Num("arguments hors limites")
    days, year = _year_basis(s, m, int(basis or 0))
    return (redemption - investment) / investment * year / days


FUNCTIONS = {
    "MMULT": (mmult, 2, 2), "MINVERSE": (minverse, 1, 1), "MDETERM": (mdeterm, 1, 1), "MUNIT": (munit, 1, 1),
    "FVSCHEDULE": (fvschedule, 2, 2), "DISC": (disc, 4, 5), "INTRATE": (intrate, 4, 5),
}


def _wrap(fn, fz):
    def call(*args):
        try:
            return fn(*args)
        except _Num:
            return fz.LiteralValue.error("Num", "")
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            if isinstance(exc, ZeroDivisionError):
                return fz.LiteralValue.error("Div", "")
            return fz.LiteralValue.error("Value", str(exc))
    return call


def register(workbook, fz):
    """Fonctions ajoutées au classeur du moteur (à chaque construction)."""
    for name, (fn, low, high) in FUNCTIONS.items():
        try:
            workbook.register_function(name, _wrap(fn, fz), min_args=low, max_args=high)
        except Exception:                                  # noqa: BLE001 - déjà fournie par une version récente
            pass
