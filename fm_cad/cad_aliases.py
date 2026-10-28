"""Alias de commandes du CAD d'apres un fichier .pgp d'AutoCAD (acad.pgp) — couche pure, aucune dependance Qt.

Format lu (celui d'AutoCAD, fichier texte, CRLF ou LF, Windows-1252 ou UTF-8) :

    ; commentaire
    L,      *LIGNE
    -B,     *-BLOC

Un alias = ce que l'on tape a « Commande : » ; la commande vise une commande AutoCAD, francaise ou anglaise,
traduite vers celles de l'appli (`cad_commands.REGISTRY`) :
  - disponible   : l'alias la lance ;
  - prevue       : l'alias annonce « prevue en phase N » (le registre l'a deja declaree) — l'alias est pris des
                   maintenant, sa fonction viendra avec la commande ;
  - sans equivalent : la commande n'existe pas dans l'appli (AIRE, BLOC…) — l'alias est ignore et ne masque
                   JAMAIS un alias d'origine.
Les alias du fichier passent avant ceux d'origine (« A » = AJUSTER prend la place de « A » = ARC) ; les alias
d'origine non cites par le fichier restent. Le fichier de l'utilisateur n'est jamais modifie.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import cad_commands

# Noms AutoCAD absents du registre (variantes de la version francaise, formes anglaises courantes).
SYNONYMS = {
    "PROLONGE": "EXTEND", "COPYM": "COPY", "COPIERM": "COPY", "FHACH": "HATCH", "HACHURE": "HATCH",
    "BHATCH": "HATCH", "CORRESPROP": "MATCHPROP", "REGNTOUT": "REGENALL", "REGENERER": "REGEN",
    "RÉGÉNÉRER": "REGEN",
}

AVAILABLE, PLANNED, UNKNOWN = "disponible", "prévue", "sans équivalent"


@dataclass
class Alias:
    alias: str
    command: str            # nom AutoCAD tel que dans le fichier (sans « * »)
    line: int
    target: str = ""        # nom de la commande de l'appli (vide : sans equivalent)
    state: str = UNKNOWN
    phase: str = ""


@dataclass
class AliasSet:
    path: str = ""
    entries: list = field(default_factory=list)
    error: str = ""

    def count(self, state: str) -> int:
        return sum(1 for a in self.entries if a.state == state)

    def summary(self) -> str:
        if self.error:
            return "⚠ " + self.error
        return (f"✓ {Path(self.path).name} — {len(self.entries)} alias : {self.count(AVAILABLE)} actifs, "
                f"{self.count(PLANNED)} prévus, {self.count(UNKNOWN)} sans équivalent")

    def report(self) -> str:
        """Correspondance complete (info-bulle) : un alias par ligne, groupes par etat."""
        if self.error:
            return self.error
        rows = []
        for state in (AVAILABLE, PLANNED, UNKNOWN):
            group = [a for a in self.entries if a.state == state]
            if not group:
                continue
            rows.append({AVAILABLE: "Actifs", PLANNED: "Prévus (commande pas encore disponible)",
                         UNKNOWN: "Sans équivalent dans l'appli (ignorés)"}[state] + " :")
            for a in group:
                line = f"  {a.alias} → {a.command}"
                if a.target and a.target != a.command.upper().lstrip("_-"):
                    line += f"  [{a.target}]"
                if a.state == PLANNED and a.phase:
                    line += f"  ({a.phase})"
                rows.append(line)
        return "\n".join(rows)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def parse(text: str) -> list:
    """Lignes « ALIAS, [drapeaux]*COMMANDE » du texte (commentaires « ; », lignes vides et sections ignores)."""
    out = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("["):
            continue
        line = line.split(";", 1)[0].strip()
        if "," not in line:
            continue
        alias, _, rest = line.partition(",")
        alias = alias.strip()
        rest = rest.strip()
        if not alias or "*" not in rest or " " in alias or "\t" in alias:
            continue
        command = rest.split("*", 1)[1].strip().split(",")[0].strip()
        if command:
            out.append((alias, command, number))
    return out


def _target(command: str):
    """Commande de l'appli visee par un nom AutoCAD, ou None."""
    word = command.strip().upper().lstrip("_").lstrip("-")
    mapped = SYNONYMS.get(word)
    if mapped:
        for entry in cad_commands.REGISTRY:
            if entry.name == mapped:
                return entry
    return cad_commands.lookup_builtin(word)


def load(path: str) -> AliasSet:
    """Fichier .pgp lu et traduit (jamais d'exception : `error` le dit)."""
    result = AliasSet(path=str(path or ""))
    if not path:
        return result
    try:
        text = _decode(Path(path).read_bytes())
    except OSError as exc:
        result.error = f"fichier illisible ({exc.strerror or exc})"
        return result
    seen = set()
    for alias, command, number in parse(text):
        key = alias.upper()
        if key in seen:                              # AutoCAD : le premier alias d'un mot l'emporte
            continue
        seen.add(key)
        entry = _target(command)
        item = Alias(alias, command, number)
        if entry is not None:
            item.target = entry.name
            item.state = PLANNED if entry.planned else AVAILABLE
            item.phase = entry.planned
        result.entries.append(item)
    if not result.entries:
        result.error = "aucun alias reconnu (format : « L, *LIGNE »)"
    return result


# -- installation (un seul jeu actif, relu quand le fichier change) --
_state = {"path": "", "stamp": None}


def _stamp(path: str):
    try:
        info = os.stat(path)
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return None


def install(path: str) -> AliasSet:
    """Pose les alias du fichier dans le registre (vide / illisible : alias d'origine seulement)."""
    path = (path or "").strip()
    loaded = load(path)
    table = {}
    for item in loaded.entries:
        if item.state == UNKNOWN:
            continue
        entry = next((e for e in cad_commands.REGISTRY if e.name == item.target), None)
        if entry is not None:
            table[item.alias.upper()] = entry
    cad_commands.USER_ALIASES = table
    _state["path"] = path
    _state["stamp"] = _stamp(path) if path else None
    return loaded


def refresh() -> bool:
    """Relit le fichier s'il a change sur le disque (appelee quand le CAD s'active) ; vrai si relu."""
    path = _state["path"]
    if path and _stamp(path) != _state["stamp"]:
        install(path)
        return True
    return False
