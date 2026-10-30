"""Valeurs des cellules (SANS Qt) : erreurs d'Excel, saisie typée, texte d'édition.

Une cellule garde une valeur TYPÉE (float, int, str, bool, `XLError`, None) — jamais tout en texte. La saisie de
l'utilisateur est reconnue comme Excel : nombre (virgule ou point décimal, espaces de milliers), pourcentage,
monnaie, date (jj/mm/aaaa, aaaa-mm-jj, jj/mm), heure, booléen (VRAI / FAUX), erreur littérale, texte (« ' » en tête
force le texte), formule (« = » en tête). Une date est un nombre de série d'Excel accompagné d'un format de date."""
from __future__ import annotations

import datetime as _dt
import math
import re

from . import numfmt

ERROR_CODES = ("#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A", "#GETTING_DATA", "#SPILL!",
               "#CALC!", "#CIRC!", "#N/IMPL")
# Genres d'erreur du moteur (formualizer) -> code affiché
ENGINE_ERRORS = {"Null": "#NULL!", "Div": "#DIV/0!", "Value": "#VALUE!", "Ref": "#REF!", "Name": "#NAME?",
                 "Num": "#NUM!", "NA": "#N/A", "Na": "#N/A", "Spill": "#SPILL!", "Calc": "#CALC!", "Circ": "#CIRC!",
                 "GettingData": "#GETTING_DATA", "NImpl": "#N/IMPL", "Error": "#ERROR!"}
CODE_TO_KIND = {code: kind for kind, code in ENGINE_ERRORS.items() if kind != "NA"}


class XLError:
    """Valeur d'erreur d'Excel (#DIV/0!…). Comparée par son code."""
    __slots__ = ("code", "message")

    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message

    def __eq__(self, other):
        return isinstance(other, XLError) and other.code == self.code

    def __hash__(self):
        return hash(("XLError", self.code))

    def __repr__(self):
        return f"XLError({self.code!r})"

    def __str__(self):
        return self.code


def is_error(value) -> bool:
    return isinstance(value, XLError)


class Parsed:
    __slots__ = ("value", "formula", "fmt")

    def __init__(self, value=None, formula=None, fmt=None):
        self.value = value
        self.formula = formula
        self.fmt = fmt

    def __repr__(self):
        return f"Parsed({self.value!r}, {self.formula!r}, {self.fmt!r})"


_SPACES = re.compile(r"[\s  ]")
_NUMBER = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")
_CURRENCIES = ("€", "$", "£", "¥", "CHF")
_TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}(?:[.,]\d+)?))?\s*([AaPp][Mm])?$")
_DATE_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?$")
_DATE_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_BOOLS = {"VRAI": True, "TRUE": True, "FAUX": False, "FALSE": False}


def parse_number(text: str, decimal: str = ","):
    """Nombre écrit à la française ou à l'anglaise ; None sinon. « 1 234,5 », « 1234.5 », « 1,234.5 »."""
    raw = _SPACES.sub("", text)
    if not raw:
        return None
    neg = False
    if raw.startswith("(") and raw.endswith(")"):
        raw, neg = raw[1:-1], True
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif raw.count(",") > 1 or raw.count(".") > 1:
        sep = "," if raw.count(",") > 1 else "."
        if not re.fullmatch(r"[+-]?\d{1,3}(" + re.escape(sep) + r"\d{3})+", raw):
            return None
        raw = raw.replace(sep, "")
    elif "," in raw:
        if decimal != "," and re.fullmatch(r"[+-]?\d{1,3},\d{3}", raw):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(",", ".")
    if not _NUMBER.match(raw):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return -value if neg else value


def _decimals_of(text: str) -> int:
    m = re.search(r"[.,](\d+)\s*(?:%|€|\$|£|¥|CHF)?\s*$", text.strip())
    return len(m.group(1)) if m else 0


def _as_int(value: float):
    return int(value) if value.is_integer() and abs(value) < 2 ** 53 else value


def parse_input(text: str, decimal: str = ",", date_order: str = "dmy", today: _dt.date | None = None) -> Parsed:
    """Ce que l'utilisateur a tapé -> valeur typée, formule, format implicite (ou None)."""
    if text is None:
        return Parsed()
    if text.startswith("="):
        return Parsed(formula=text) if len(text) > 1 else Parsed(value="=")
    if text.startswith("'"):
        return Parsed(value=text[1:])
    stripped = text.strip()
    if not stripped:
        return Parsed()
    upper = stripped.upper()
    if upper in _BOOLS:
        return Parsed(value=_BOOLS[upper])
    if upper in ERROR_CODES:
        return Parsed(value=XLError(upper))
    if stripped.endswith("%"):
        number = parse_number(stripped[:-1], decimal)
        if number is not None:
            places = _decimals_of(stripped)
            return Parsed(value=number / 100, fmt="0%" if not places else "0." + "0" * places + "%")
    for symbol in _CURRENCIES:
        if stripped.startswith(symbol) or stripped.endswith(symbol):
            body = stripped[len(symbol):] if stripped.startswith(symbol) else stripped[:-len(symbol)]
            number = parse_number(body, decimal)
            if number is not None:
                places = 2 if _decimals_of(stripped) else 0
                pattern = "#,##0" + ("." + "0" * places if places else "")
                fmt = f'{pattern} "{symbol}"' if stripped.endswith(symbol) else f'"{symbol}"{pattern}'
                return Parsed(value=_as_int(number), fmt=fmt)
    number = parse_number(stripped, decimal)
    if number is not None:
        fmt = None
        if re.search(r"\d[\s  ]\d{3}", stripped) or re.search(r"\d,\d{3}\.", stripped):
            fmt = "#,##0" + ("." + "0" * _decimals_of(stripped) if _decimals_of(stripped) else "")
        elif "e" in stripped.lower():
            fmt = "0.00E+00"
        return Parsed(value=_as_int(number), fmt=fmt)
    when = parse_date_time(stripped, date_order, today)
    if when is not None:
        return Parsed(value=_as_int(round(when[0], 10)), fmt=when[1])
    return Parsed(value=text)


def parse_date_time(text: str, date_order: str = "dmy", today: _dt.date | None = None):
    """(série, format) d'une date et / ou heure ; None sinon."""
    date_part, _, time_part = text.strip().partition(" ")
    serial = None
    fmt = None
    if _TIME.match(text.strip()):
        date_part, time_part = "", text.strip()
    if date_part:
        m = _DATE_ISO.match(date_part)
        if m:
            year, month, day = (int(g) for g in m.groups())
            fmt = "yyyy-mm-dd"
        else:
            m = _DATE_DMY.match(date_part)
            if not m:
                return None
            a, b, year = m.group(1), m.group(2), m.group(3)
            day, month = (int(a), int(b)) if date_order == "dmy" else (int(b), int(a))
            if year is None:
                year = (today or _dt.date.today()).year
                fmt = "dd-mmm" if date_order == "dmy" else "mmm-dd"
            else:
                year = int(year)
                if len(m.group(3)) == 2:
                    year += 2000 if year < 30 else 1900
                elif len(m.group(3)) == 3:
                    return None
                fmt = "dd/mm/yyyy" if date_order == "dmy" else "mm/dd/yyyy"
        try:
            serial = numfmt.datetime_to_serial(_dt.date(year, month, day))
        except ValueError:
            return None
    if time_part:
        m = _TIME.match(time_part.strip())
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        second = float(m.group(3).replace(",", ".")) if m.group(3) else 0.0
        ampm = (m.group(4) or "").upper()
        if ampm == "PM" and hour < 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59 or second >= 60:
            return None
        frac = (hour * 3600 + minute * 60 + second) / 86400
        tfmt = "hh:mm:ss" if m.group(3) else "hh:mm"
        if ampm:
            tfmt = "h:mm" + (":ss" if m.group(3) else "") + " AM/PM"
        if serial is None:
            return frac, tfmt
        return serial + frac, fmt + " " + tfmt
    if serial is None:
        return None
    return serial, fmt


def edit_text(value, formula: str | None, fmt: str | None, loc: numfmt.Locale = numfmt.DEFAULT_LOCALE) -> str:
    """Texte proposé à l'édition (barre de formule, cellule) : formule telle quelle, nombre complet, date lisible."""
    if formula:
        return formula
    if value is None:
        return ""
    if isinstance(value, bool):
        return ("VRAI" if value else "FAUX") if loc.lang == "fr" else ("TRUE" if value else "FALSE")
    if isinstance(value, XLError):
        return value.code
    if isinstance(value, (int, float)):
        if fmt and numfmt.is_date_code(fmt):
            when = numfmt.serial_to_datetime(float(value))
            if when is not None:
                has_time = abs(float(value) - int(float(value))) > 1e-9
                if float(value) < 1:
                    return when.strftime("%H:%M:%S")
                text = when.strftime("%d/%m/%Y" if loc.lang == "fr" else "%m/%d/%Y")
                return text + (when.strftime(" %H:%M:%S") if has_time else "")
        if fmt and numfmt.is_percent_code(fmt):
            return number_text(float(value) * 100, loc) + "%"
        return number_text(value, loc)
    text = str(value)
    if (parse_input(text, loc.decimal).value != text) and not text.startswith("="):
        return "'" + text                              # texte qui ressemble à un nombre : gardé en texte
    return text


def number_text(value, loc: numfmt.Locale = numfmt.DEFAULT_LOCALE) -> str:
    """Nombre complet (15 chiffres significatifs, comme la barre de formule d'Excel)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    value = float(value)
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    text = format(value, ".15g")
    if "e" in text:
        mantissa, exp = text.split("e")
        text = f"{mantissa}E{exp[0]}{exp[1:].zfill(2)}"
    return text.replace(".", loc.decimal)


def from_engine(value):
    """Valeur rendue par le moteur -> valeur de cellule (dates en nombres de série, erreurs en `XLError`)."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict) and value.get("type") == "Error":
        return XLError(ENGINE_ERRORS.get(value.get("kind"), "#VALUE!"), str(value.get("message") or ""))
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return numfmt.datetime_to_serial(value)
    if isinstance(value, _dt.timedelta):
        return value.total_seconds() / 86400
    if isinstance(value, list):                        # tableau non répandu : sa première valeur
        first = value[0] if value else None
        while isinstance(first, list):
            first = first[0] if first else None
        return from_engine(first)
    return str(value)


def engine_kind(value) -> str | None:
    """Genre de valeur rendue par le moteur qui impose un format d'affichage (date / heure) : "date", "datetime",
    "time" ou None."""
    if isinstance(value, _dt.datetime):
        return "datetime"
    if isinstance(value, _dt.date):
        return "date"
    if isinstance(value, (_dt.time, _dt.timedelta)):
        return "time"
    return None
