"""Formats de nombres d'Excel (SANS Qt) : `format_value(valeur, code)` -> (texte, couleur ou None).

Pris en charge : « General » ; sections `positif;négatif;zéro;texte` et conditions `[>=100]` ; 0 # ? ; séparateur
de milliers et mise à l'échelle par virgules ; % ; notation scientifique E+00 ; texte "…", \\x, _x (espace) ; *x
(remplissage, ignoré) ; couleurs [Red] [Color12] ; devises [$€-40C] ; @ ; dates et heures (y m d h s, AM/PM,
[h] [mm] [ss] écoulés, fractions de seconde .0) ; fractions `# ?/?`, `?/8`. Sortie localisée : séparateur décimal et de milliers donnés par l'appelant (réglages du module).

Dates : nombres de série d'Excel, système 1900 avec le 29/02/1900 fictif d'Excel (série 60)."""
from __future__ import annotations

import datetime as _dt
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

EPOCH = _dt.datetime(1899, 12, 30)
GENERAL = "General"

MONTHS = {
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
}
MONTHS_SHORT = {
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
DAYS = {
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
DAYS_SHORT = {
    "fr": ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
COLORS = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#00b050", "blue": "#0000ff",
          "yellow": "#ffff00", "magenta": "#ff00ff", "cyan": "#00ffff"}
# 56 couleurs de la palette d'Excel ([Color1] … [Color56]) : les 8 premières suffisent à l'usage courant
PALETTE = ["#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff"]


class Locale:
    __slots__ = ("decimal", "thousands", "lang")

    def __init__(self, decimal: str = ",", thousands: str = " ", lang: str = "fr"):
        self.decimal = decimal
        self.thousands = thousands
        self.lang = lang if lang in MONTHS else "fr"


DEFAULT_LOCALE = Locale()


# ---------------------------------------------------------------- dates
def serial_to_datetime(serial: float) -> _dt.datetime | None:
    if serial is None or not math.isfinite(serial) or serial < 0 or serial >= 2958466:
        return None
    if serial < 61:
        if 60 <= serial < 61:                          # 29/02/1900 d'Excel : n'existe pas
            return None
        serial += 1                                    # avant le jour fictif : décalage d'un jour
    days = int(serial)
    seconds = round((serial - days) * 86400, 6)
    return EPOCH + _dt.timedelta(days=days, seconds=seconds)


def datetime_to_serial(value) -> float:
    if isinstance(value, _dt.datetime):
        delta = value - EPOCH
    elif isinstance(value, _dt.date):
        delta = _dt.datetime(value.year, value.month, value.day) - EPOCH
    elif isinstance(value, _dt.time):
        return (value.hour * 3600 + value.minute * 60 + value.second + value.microsecond / 1e6) / 86400
    else:
        raise TypeError(value)
    serial = delta.days + delta.seconds / 86400 + delta.microseconds / 86400e6
    if serial < 61:
        serial -= 1
    return serial


# ---------------------------------------------------------------- analyse des codes
_SECTION_SPLIT = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|;|[^"\\\[;]+')
_COND = re.compile(r"^\[(<=|>=|<>|<|>|=)(-?\d+(?:\.\d+)?)\]$")


def _split_sections(code: str) -> list[str]:
    sections = [""]
    for m in _SECTION_SPLIT.finditer(code):
        if m.group(0) == ";":
            sections.append("")
        else:
            sections[-1] += m.group(0)
    return sections


_TOKEN = re.compile(
    r'"(?P<lit>[^"]*)"|\\(?P<esc>.)|_(?P<pad>.)|\*(?P<fill>.)|\[(?P<br>[^\]]*)\]'
    r'|(?P<ampm>AM/PM|am/pm|A/P|a/p)|(?P<gen>General|GENERAL|general|Standard|STANDARD|standard)'
    r'|(?P<date>yyyy|yyy|yy|y|mmmmm|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|YYYY|YY|MMMM|MMM|MM|M|DDDD|DDD|DD|D'
    r'|HH|H|SS|S|aaaa|aaa|jjjj|jjj|jj|j|aa|AAAA|AAA|JJ|J)'
    r'|(?P<sci>[Ee][+-])|(?P<num>[0#?])|(?P<other>.)', re.S)


class _Section:
    __slots__ = ("tokens", "color", "cond", "is_date", "is_text", "percent", "scale", "group", "int_ph",
                 "frac_ph", "sci", "exp_ph", "elapsed", "general", "ampm")

    def __init__(self):
        self.tokens = []
        self.color = None
        self.cond = None
        self.is_date = False
        self.is_text = False
        self.percent = 0
        self.scale = 0
        self.group = False
        self.int_ph = ""
        self.frac_ph = ""
        self.sci = None
        self.exp_ph = ""
        self.elapsed = False
        self.general = False
        self.ampm = False


_DATE_LETTERS = {"y", "m", "d", "h", "s"}
# Codes de format localisés (Excel français : « jj/mm/aaaa ») : ramenés aux lettres anglaises
_FR_DATE = {"a": "y", "j": "d"}


def _parse_section(text: str) -> _Section:
    sec = _Section()
    raw = []
    for m in _TOKEN.finditer(text):
        kind = m.lastgroup
        value = m.group(kind)
        if kind == "br":
            low = value.lower()
            cond = _COND.match("[" + value + "]")
            if cond:
                sec.cond = (cond.group(1), float(cond.group(2)))
            elif low in COLORS:
                sec.color = COLORS[low]
            elif low.startswith("color") and low[5:].isdigit():
                index = int(low[5:]) - 1
                sec.color = PALETTE[index] if 0 <= index < len(PALETTE) else None
            elif value.startswith("$"):
                symbol = value[1:].split("-", 1)[0]
                raw.append(("lit", symbol))
            elif low and set(low) <= {"h", "m", "s"}:
                raw.append(("elapsed", low))
                sec.is_date = True
                sec.elapsed = True
            continue
        if kind == "date":
            letter = value[0].lower()
            letter = _FR_DATE.get(letter, letter)
            value = letter * len(value)
            sec.is_date = True
        if kind == "ampm":
            sec.ampm = True
        if kind == "gen":
            sec.general = True
        if kind == "other" and value == "@":
            sec.is_text = True
            kind = "at"
        raw.append((kind, value))
    # minutes : « m » après des heures ou avant des secondes
    dates = [i for i, (k, _v) in enumerate(raw) if k in ("date", "elapsed")]
    for pos, i in enumerate(dates):
        kind, value = raw[i]
        if kind != "date" or value[0] != "m" or len(value) > 2:
            continue
        before = raw[dates[pos - 1]][1] if pos > 0 else ""
        after = raw[dates[pos + 1]][1] if pos + 1 < len(dates) else ""
        if before[:1] == "h" or after[:1] == "s" or before == "[h]" or before.startswith("h"):
            raw[i] = ("minute", value)
    if not sec.is_date:
        _number_layout(sec, raw)
    sec.tokens = raw
    return sec


def _number_layout(sec: _Section, raw: list):
    """Placeholders d'un format numérique : partie entière, décimales, exposant, milliers, échelle, %."""
    seen_point = False
    in_exp = False
    last_num = None
    for i, (kind, value) in enumerate(raw):
        if kind == "num":
            if in_exp:
                sec.exp_ph += value
            elif seen_point:
                sec.frac_ph += value
            else:
                sec.int_ph += value
            last_num = i
        elif kind == "other" and value == "." and not in_exp and not seen_point:
            seen_point = True
            raw[i] = ("point", ".")
        elif kind == "other" and value == "%":
            sec.percent += 1
        elif kind == "sci":
            sec.sci = value[1]
            in_exp = True
        elif kind == "other" and value == ",":
            nxt = raw[i + 1] if i + 1 < len(raw) else None
            if last_num is not None and nxt is not None and nxt[0] == "num" and not seen_point:
                sec.group = True
                raw[i] = ("skip", ",")
            elif last_num is not None and (nxt is None or nxt[0] != "num"):
                # virgules à droite des chiffres : mise à l'échelle (÷ 1000 chacune)
                j = i
                while j > 0 and raw[j - 1] == ("skip", ","):
                    j -= 1
                if raw[j - 1][0] in ("num", "point", "skip"):
                    sec.scale += 1
                    raw[i] = ("skip", ",")


@lru_cache(maxsize=512)
def parse_code(code: str) -> tuple:
    return tuple(_parse_section(s) for s in _split_sections(code or GENERAL))


def is_date_code(code: str) -> bool:
    secs = parse_code(code)
    return bool(secs) and secs[0].is_date


def is_percent_code(code: str) -> bool:
    secs = parse_code(code)
    return bool(secs) and secs[0].percent > 0


# ---------------------------------------------------------------- rendu
def _round_half_up(value: float, digits: int) -> Decimal:
    """Arrondi d'affichage d'Excel (au plus près, moitié en s'éloignant de zéro), sur 15 chiffres significatifs."""
    d = Decimal(repr(value)) if math.isfinite(value) else Decimal(0)
    if d != 0:
        d = Decimal(format(float(d), ".15g"))
    return d.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)


def general(value: float, loc: Locale = DEFAULT_LOCALE) -> str:
    """Format « Standard » : 11 caractères au plus, comme une cellule d'Excel de largeur ordinaire."""
    if value == 0:
        return "0"
    if isinstance(value, bool):
        return "VRAI" if value else "FAUX"
    absv = abs(value)
    if 1e-9 <= absv < 1e11:
        int_digits = max(1, len(str(int(absv))))
        decimals = max(0, 10 - int_digits)
        text = f"{value:.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if text in ("-0", ""):
            text = "0"
        if abs(float(text)) == 0:
            text = f"{value:.5E}"
        else:
            return text.replace(".", loc.decimal)
    mantissa, exp = f"{value:.5E}".split("E")
    mantissa = mantissa.rstrip("0").rstrip(".")
    sign = exp[0]
    return f"{mantissa.replace('.', loc.decimal)}E{sign}{exp[1:].zfill(2)}"


def _group(digits: str, sep: str) -> str:
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return sep.join(out)


def _render_fraction(sec: _Section, value: float, signed: bool) -> str:
    """« # ?/? », « ?/?? », « # ?/8 » : partie entière (si un groupe de chiffres précède le numérateur)."""
    from fractions import Fraction
    toks = sec.tokens
    slash = next(i for i, t in enumerate(toks) if t == ("other", "/"))
    den_ph = "".join(v for k, v in toks[slash + 1:] if k == "num")
    fixed = "".join(v for k, v in toks[slash + 1:] if k == "other" and v.isdigit())
    groups = []
    for k, v in toks[:slash]:
        if k == "num":
            if not groups or groups[-1] is None:
                groups.append("")
            groups[-1] += v
        elif groups and groups[-1] is not None:
            groups.append(None)
    groups = [g for g in groups if g]
    v = abs(value)
    whole = int(v) if len(groups) >= 2 else 0
    rest = v - whole
    frac = Fraction(rest).limit_denominator(int(fixed)) if fixed else \
        Fraction(rest).limit_denominator(10 ** max(1, len(den_ph)) - 1)
    if fixed:
        frac = Fraction(round(rest * int(fixed)), int(fixed))
    if frac == 1:
        whole, frac = whole + 1, Fraction(0)
    sign = "-" if signed and value < 0 else ""
    if frac == 0:
        return sign + str(whole if len(groups) >= 2 else 0)
    head = f"{whole} " if len(groups) >= 2 and whole else ""
    return f"{sign}{head}{frac.numerator}/{frac.denominator}"


def _render_number(sec: _Section, value: float, loc: Locale, signed: bool) -> str:
    if ("other", "/") in sec.tokens:
        return _render_fraction(sec, value, signed)
    v = abs(value) * (100 ** sec.percent) / (1000 ** sec.scale)
    neg = signed and value < 0
    if sec.general:
        body = general(v, loc)
        out = []
        for kind, val in sec.tokens:
            if kind == "gen":
                out.append(body)
            elif kind in ("lit", "esc", "other"):
                out.append(val)
            elif kind == "pad":
                out.append(" ")
        return ("-" if neg else "") + "".join(out)
    exponent = 0
    if sec.sci and v:
        exponent = math.floor(math.log10(v))
        int_len = max(1, len(sec.int_ph))
        if len(sec.int_ph) > 1:                       # ##0.0E+0 : exposant multiple du nombre de chiffres
            exponent = int(math.floor(exponent / int_len) * int_len)
        v = v / (10 ** exponent)
        if float(_round_half_up(v, len(sec.frac_ph))) >= 10 ** max(1, len(sec.int_ph)):
            v /= 10 ** max(1, len(sec.int_ph))
            exponent += max(1, len(sec.int_ph))
    rounded = _round_half_up(v, len(sec.frac_ph))
    text = format(rounded, "f")
    int_part, _, frac_part = text.partition(".")
    if int_part == "0" and "0" not in sec.int_ph:
        int_part = ""
    min_int = sec.int_ph.count("0")
    if len(int_part) < min_int:
        int_part = int_part.zfill(min_int)
    if sec.group and int_part:
        int_part = _group(int_part, loc.thousands)
    pad_q = sec.int_ph.count("?") - max(0, len(int_part) - sec.int_ph.count("0"))
    if pad_q > 0 and "0" not in sec.int_ph:
        int_part = " " * pad_q + int_part
    # décimales : # = chiffre seulement s'il compte, ? = espace à la place d'un zéro final
    frac_out = list(frac_part)
    for i in range(len(sec.frac_ph) - 1, -1, -1):
        if frac_out and frac_out[i] == "0" and sec.frac_ph[i] in "#?":
            frac_out[i] = "" if sec.frac_ph[i] == "#" else " "
        else:
            break
    frac_text = "".join(frac_out)
    if neg and float(rounded) == 0 and not frac_text.strip("0 "):
        neg = False                                   # -0,00 affiché 0,00 comme Excel
    out = []
    int_done = False
    frac_done = False
    exp_done = False
    for kind, val in sec.tokens:
        if kind == "num":
            if sec.sci and exp_done:
                continue
            if not int_done and not frac_done:
                out.append(int_part)
                int_done = True
            continue
        if kind == "point":
            if not int_done:
                out.append(int_part)
                int_done = True
            if frac_text:
                out.append(loc.decimal + frac_text)
            elif sec.frac_ph and set(sec.frac_ph) <= {"?"}:
                out.append(loc.decimal)
            frac_done = True
            continue
        if kind == "sci":
            if not int_done:
                out.append(int_part)
                int_done = True
            sign = "-" if exponent < 0 else ("+" if sec.sci == "+" else "")
            out.append("E" + sign + str(abs(exponent)).zfill(max(1, len(sec.exp_ph))))
            exp_done = True
            continue
        if kind in ("lit", "esc"):
            out.append(val)
        elif kind == "pad":
            out.append(" ")
        elif kind == "other":
            out.append(val)
    if not int_done and not frac_done:
        out.append(int_part)
    return ("-" if neg else "") + "".join(out)


def _render_date(sec: _Section, value: float, loc: Locale) -> str | None:
    when = serial_to_datetime(value)
    if when is None:
        return None
    has_frac = any(k == "other" and v == "." for k, v in sec.tokens)
    if not has_frac:
        total = round(value * 86400)
        when = serial_to_datetime(total / 86400) or when
    out = []
    tokens = sec.tokens
    i = 0
    while i < len(tokens):
        kind, val = tokens[i]
        if kind == "date":
            n = len(val)
            letter = val[0]
            if letter == "y":
                out.append(str(when.year)[-2:] if n <= 2 else str(when.year))
            elif letter == "m":
                if n == 1:
                    out.append(str(when.month))
                elif n == 2:
                    out.append(f"{when.month:02d}")
                elif n == 3:
                    out.append(MONTHS_SHORT[loc.lang][when.month - 1])
                elif n == 5:
                    out.append(MONTHS[loc.lang][when.month - 1][0])
                else:
                    out.append(MONTHS[loc.lang][when.month - 1])
            elif letter == "d":
                if n == 1:
                    out.append(str(when.day))
                elif n == 2:
                    out.append(f"{when.day:02d}")
                elif n == 3:
                    out.append(DAYS_SHORT[loc.lang][when.weekday()])
                else:
                    out.append(DAYS[loc.lang][when.weekday()])
            elif letter == "h":
                hour = when.hour
                if sec.ampm:
                    hour = hour % 12 or 12
                out.append(f"{hour:02d}" if n >= 2 else str(hour))
            elif letter == "s":
                out.append(f"{when.second:02d}" if n >= 2 else str(when.second))
                if i + 1 < len(tokens) and tokens[i + 1] == ("other", "."):
                    j = i + 2
                    zeros = 0
                    while j < len(tokens) and tokens[j] == ("num", "0"):
                        zeros += 1
                        j += 1
                    if zeros:
                        frac = (value * 86400) % 1
                        digits = str(int(round(frac * 10 ** zeros))).zfill(zeros)[:zeros]
                        out.append(loc.decimal + digits)
                        i = j
                        continue
        elif kind == "minute":
            out.append(f"{when.minute:02d}" if len(val) >= 2 else str(when.minute))
        elif kind == "elapsed":
            total = value * 86400
            if val[0] == "h":
                number = int(total // 3600)
            elif val[0] == "m":
                number = int(total // 60)
            else:
                number = int(round(total))
            out.append(str(number).zfill(len(val)))
        elif kind == "ampm":
            am = when.hour < 12
            if val.upper() == "A/P":
                out.append(("A" if am else "P") if val[0] == "A" else ("a" if am else "p"))
            else:
                out.append("AM" if am else "PM")
        elif kind in ("lit", "esc", "other"):
            out.append(val)
        elif kind == "pad":
            out.append(" ")
        i += 1
    return "".join(out)


def _matches(cond, value) -> bool:
    op, ref = cond
    return {"<": value < ref, ">": value > ref, "=": value == ref, "<=": value <= ref, ">=": value >= ref,
            "<>": value != ref}[op]


def format_value(value, code: str = GENERAL, loc: Locale = DEFAULT_LOCALE) -> tuple[str, str | None]:
    """Texte affiché d'une valeur selon un code de format d'Excel, et sa couleur imposée (ou None)."""
    if value is None:
        return "", None
    if isinstance(value, bool):
        return ("VRAI" if value else "FAUX") if loc.lang == "fr" else ("TRUE" if value else "FALSE"), None
    sections = parse_code(code or GENERAL)
    if isinstance(value, str):
        text_sec = None
        if len(sections) >= 4:
            text_sec = sections[3]
        elif sections and sections[0].is_text:
            text_sec = sections[0]
        if text_sec is None:
            return value, None
        out = []
        for kind, val in text_sec.tokens:
            if kind == "at":
                out.append(value)
            elif kind in ("lit", "esc", "other"):
                out.append(val)
            elif kind == "pad":
                out.append(" ")
        return "".join(out), text_sec.color
    if not isinstance(value, (int, float)):
        return str(value), None
    value = float(value)
    if not math.isfinite(value):
        return "#NUM!", None
    sec = None
    signed = True
    conds = [s for s in sections[:3] if s.cond is not None]
    if conds:
        for s in sections[:3]:
            if s.cond is not None and _matches(s.cond, value):
                sec, signed = s, s.cond[1] >= 0 and s.cond[0] not in ("<", "<=")
                break
        if sec is None:
            rest = [s for s in sections[:3] if s.cond is None]
            sec = rest[0] if rest else sections[0]
    elif len(sections) == 1 or (len(sections) >= 2 and value > 0):
        sec = sections[0]
    elif value < 0 and len(sections) >= 2:
        sec, signed = sections[1], False
    elif value == 0:
        sec = sections[2] if len(sections) >= 3 else sections[0]
    else:
        sec = sections[0]
    if sec.is_text and not sec.is_date and not sec.int_ph and not sec.general:
        return general(value, loc), None
    if sec.is_date:
        text = _render_date(sec, value, loc)
        if text is None:
            return "#" * 8, sec.color                 # date négative / hors limites : comme Excel
        return text, sec.color
    if not (sec.int_ph or sec.frac_ph or sec.general):
        # section sans chiffre (ex. "-" pour les zéros) : texte seul
        out = "".join(val if kind in ("lit", "esc", "other") else " " if kind == "pad" else ""
                      for kind, val in sec.tokens)
        return ("-" + out if signed and value < 0 and len(sections) == 1 else out), sec.color
    return _render_number(sec, value, loc, signed), sec.color


# ---------------------------------------------------------------- formats courants (barre d'outils)
PRESETS = [
    ("Standard", GENERAL),
    ("Nombre", "#,##0.00"),
    ("Monétaire", '#,##0.00 "€"'),
    ("Comptabilité", '_-* #,##0.00 "€"_-;-* #,##0.00 "€"_-;_-* "-"?? "€"_-;_-@_-'),
    ("Date courte", "dd/mm/yyyy"),
    ("Date longue", "dddd d mmmm yyyy"),
    ("Heure", "hh:mm:ss"),
    ("Pourcentage", "0.00%"),
    ("Scientifique", "0.00E+00"),
    ("Texte", "@"),
]


def change_decimals(code: str, delta: int) -> str:
    """Ajouter / retirer une décimale (boutons de la barre) : sur chaque section numérique."""
    if not code or code == GENERAL:
        return "0" + (("." + "0" * delta) if delta > 0 else "")
    out = []
    for section in _split_sections(code):
        sec = _parse_section(section)
        if sec.is_date or sec.is_text or not (sec.int_ph or sec.frac_ph):
            out.append(section)
            continue
        m = re.search(r"([0#?])(\.([0#?]*))?(?![^\"]*\"(?:[^\"]*\"[^\"]*\")*[^\"]*$)", section[::-1])
        # repère la DERNIÈRE suite de chiffres (texte lu à l'envers) hors guillemets
        if m is None:
            out.append(section)
            continue
        idx = len(section) - m.start()                 # fin de la dernière suite de chiffres
        head = section[:idx]
        tail = section[idx:]
        if "." in head.rsplit('"', 1)[-1]:
            point = head.rfind(".")
            decimals = len(head) - point - 1
            if delta > 0:
                head = head + "0" * delta
            elif decimals + delta <= 0:
                head = head[:point]
            else:
                head = head[:len(head) + delta]
        elif delta > 0:
            head = head + "." + "0" * delta
        out.append(head + tail)
    return ";".join(out)
