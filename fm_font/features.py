"""Features OpenType (sans Qt) : texte .fea du projet, vérification rapide avec erreurs lisibles (fontTools.feaLib),
génération de features courantes depuis les suffixes des noms de glyphes.

kern et mark / mkmk ne s'écrivent pas à la main : ufo2ft les génère à la compilation depuis le crénage et les
ancres (« feature writers ») ; une feature kern écrite dans le .fea les remplace."""
from __future__ import annotations

import io
import re

from fontTools.feaLib.error import FeatureLibError
from fontTools.feaLib.parser import Parser

# Features prises en charge par le générateur : tag -> (suffixe des glyphes cibles, description).
SUFFIX_FEATURES = {
    "smcp": (".sc", "Petites capitales (a -> a.sc)"),
    "c2sc": (".sc", "Capitales en petites capitales (A -> a.sc)"),
    "onum": (".osf", "Chiffres elzéviriens"),
    "lnum": (".lf", "Chiffres alignés"),
    "tnum": (".tf", "Chiffres tabulaires"),
    "pnum": (".pf", "Chiffres proportionnels"),
    "case": (".case", "Formes pour capitales"),
    "salt": (".salt", "Variantes stylistiques"),
}
for _n in range(1, 21):
    SUFFIX_FEATURES[f"ss{_n:02d}"] = (f".ss{_n:02d}", f"Jeu stylistique {_n}")
DESCRIPTIONS = {"liga": "Ligatures standard", "dlig": "Ligatures discrétionnaires", "calt": "Variantes contextuelles",
                "frac": "Fractions", "kern": "Crénage (généré depuis le crénage)",
                "mark": "Positionnement des marques (généré depuis les ancres)",
                "mkmk": "Marques sur marques (généré depuis les ancres)",
                **{k: v[1] for k, v in SUFFIX_FEATURES.items()}}
STANDARD_LIGATURES = ("f_f", "f_i", "f_l", "f_f_i", "f_f_l", "f_j", "f_t")


class FeaError:
    """Erreur lisible : ligne et colonne (1 = première), message en français quand il est connu."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None):
        self.message, self.line, self.column = message, line, column

    def __str__(self):
        where = f"Ligne {self.line}, colonne {self.column} : " if self.line else ""
        return where + self.message


_TRANSLATIONS = [
    (re.compile(r'Expected "?;"?'), "« ; » attendu"),
    (re.compile(r"Expected a glyph class, glyph name, or class name|Expected glyph class"), "glyphe ou classe attendu"),
    (re.compile(r'Unknown glyph class @(\S+)'), r"classe inconnue @\1"),
    (re.compile(r'Expected feature, languagesystem, lookup, markClass, table, or glyph class definition'),
     "feature, languagesystem, lookup, markClass, table ou classe attendu"),
    (re.compile(r'Expected "\}"'), "« } » attendu"),
]


def _translate(message: str) -> str:
    glyph = (re.search(r'(?:glyph|Glyph) "?([^\s"]+)"? (?:is not in the glyph set|not in glyph set)', message)
             or re.search(r'missing from the glyph set:\s*(\S+)', message))
    if glyph:
        return f"glyphe « {glyph.group(1)} » absent de la police"
    for pattern, text in _TRANSLATIONS:
        if pattern.search(message):
            return pattern.sub(text, message) if "\\1" in text else text
    return message


def check(text: str, glyph_names) -> list[FeaError]:
    """Analyse syntaxique + noms de glyphes (quelques ms) : à la frappe (temporisée)."""
    if not text.strip():
        return []
    try:
        Parser(io.StringIO(text), glyphNames=set(glyph_names), followIncludes=False).parse()
    except FeatureLibError as exc:
        return [from_exception(exc)]
    return []


def from_exception(exc: Exception) -> FeaError:
    location = getattr(exc, "location", None)
    line = getattr(location, "line", None)
    column = getattr(location, "column", None)
    message = str(exc)
    if location is not None:
        message = re.sub(r"^[^:]*:\d+:\d+:\s*", "", message)
    return FeaError(_translate(message), line, column)


def features_in(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\bfeature\s+([A-Za-z0-9]{4})\s*\{", text)))


DIGITS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _fraction_lines(names) -> list[str]:
    """frac (méthode courante) : barre de fraction, tous les chiffres en numérateurs, puis ceux qui suivent la barre
    ou un dénominateur deviennent dénominateurs (« 12/34 » -> 1 2 numérateurs, 3 4 dénominateurs). Il faut
    les chiffres et leurs variantes .numr ET .dnom."""
    digits = [d for d in DIGITS if d in names and f"{d}.numr" in names and f"{d}.dnom" in names]
    if not digits:
        return []
    numr = " ".join(f"{d}.numr" for d in digits)
    dnom = " ".join(f"{d}.dnom" for d in digits)
    bar = "fraction" if "fraction" in names else ("slash" if "slash" in names else None)
    lines = []
    if bar == "fraction" and "slash" in names:
        lines.append("    lookup FRAC_BAR { sub slash by fraction; } FRAC_BAR;")
    lines.append(f"    lookup FRAC_NUMR {{ sub [{' '.join(digits)}] by [{numr}]; }} FRAC_NUMR;")
    if bar is not None:
        lines.append(f"    lookup FRAC_DNOM {{ sub [{bar} {dnom}] [{numr}]' by [{dnom}]; }} FRAC_DNOM;")
    return lines


def generate(font, tags) -> str:
    """Code .fea pour les features demandées, d'après les glyphes présents (ligatures f_i, suffixes .sc, .osf…)."""
    names = set(font.keys())
    cmap = {c: g.name for g in font for c in g.unicodes}
    blocks = []
    for tag in tags:
        lines = []
        if tag in ("liga", "dlig"):
            candidates = STANDARD_LIGATURES if tag == "liga" else sorted(
                n for n in names if "_" in n and n not in STANDARD_LIGATURES and "." not in n)
            for lig in candidates:
                parts = lig.split("_")
                if lig in names and all(p in names for p in parts):
                    lines.append(f"    sub {' '.join(parts)} by {lig};")
        elif tag == "frac":
            lines += _fraction_lines(names)
        elif tag in SUFFIX_FEATURES:
            suffix = SUFFIX_FEATURES[tag][0]
            for name in sorted(names):
                if name.endswith(suffix):
                    base = name[: -len(suffix)]
                    if tag == "c2sc":
                        code = next((c for c, g in cmap.items() if g == base), None)
                        upper = cmap.get(ord(chr(code).upper())) if code else None
                        if upper and upper != base:
                            lines.append(f"    sub {upper} by {name};")
                        continue
                    if base in names:
                        lines.append(f"    sub {base} by {name};")
        if lines:
            blocks.append(f"feature {tag} {{\n" + "\n".join(lines) + f"\n}} {tag};")
    return "\n\n".join(blocks)


def merge(existing: str, generated: str) -> str:
    """Ajoute les features générées en remplaçant les blocs de même tag déjà présents."""
    text = existing
    for tag in features_in(generated):
        text = re.sub(rf"\bfeature\s+{tag}\s*\{{.*?\}}\s*{tag}\s*;\s*", "", text, flags=re.S)
    if "languagesystem" not in text and "languagesystem" not in generated:
        text = "languagesystem DFLT dflt;\nlanguagesystem latn dflt;\n\n" + text.lstrip()
    return (text.rstrip() + "\n\n" + generated + "\n").lstrip()


def set_features(project, text: str) -> None:
    """Texte .fea (tous les masters : les features d'une famille variable sont communes), un pas d'annulation."""
    before = [m.font.features.text for m in project.masters]
    if all(b == text for b in before):
        return

    def apply(values):
        for m, v in zip(project.masters, values):
            m.font.features.text = v
        project.notify("features", None)
    after = [text] * len(project.masters)
    apply(after)
    project.undo.push("Features", lambda: apply(before), lambda: apply(after))
