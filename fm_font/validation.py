"""Diagnostic du projet (sans Qt), trois niveaux : BLOQUANT (l'export s'arrête), AVERTISSEMENT (la police se
compile mais un logiciel risque de mal l'afficher), SUGGESTION (qualité professionnelle). FontBakery, s'il est
installé, se lance à part sur la police compilée (`run_fontbakery`, dans un fil : ~4 s), ses résultats rangés dans
les mêmes niveaux (FAIL -> avertissement, WARN -> suggestion)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import contours as C
from . import components, features, glyph_info, interpolation, kerning

BLOCKING, WARNING, SUGGESTION = "bloquant", "avertissement", "suggestion"
_NAME_RE = re.compile(r"^[A-Za-z_.][A-Za-z0-9_.\-]*$")


class Diagnostic:
    __slots__ = ("level", "message", "glyph", "master")

    def __init__(self, level: str, message: str, glyph: str | None = None, master: str | None = None):
        self.level, self.message, self.glyph, self.master = level, message, glyph, master

    def __str__(self):
        where = f"[{self.master}] " if self.master else ""
        return f"{where}{self.message}"

    def __repr__(self):
        return f"Diagnostic({self.level!r}, {self.message!r})"


def diagnose(project, variable: bool = False) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for master in project.masters:
        out += _diagnose_font(master.font, master.name if len(project.masters) > 1 else None)
    if len(project.masters) > 1:
        level = BLOCKING if variable else WARNING
        for problem in interpolation.incompatibilities(project)[:200]:
            out.append(Diagnostic(level, f"Interpolation : {problem}"))
    order = {BLOCKING: 0, WARNING: 1, SUGGESTION: 2}
    out.sort(key=lambda d: order[d.level])
    return out


def _diagnose_font(font, master: str | None) -> list[Diagnostic]:
    out = []

    def add(level, message, glyph=None):
        out.append(Diagnostic(level, message, glyph, master))
    info = font.info
    if ".notdef" not in font:
        add(BLOCKING, "Glyphe .notdef absent (obligatoire).")
    if not info.familyName:
        add(BLOCKING, "Nom de famille vide.")
    if not info.unitsPerEm or not 16 <= info.unitsPerEm <= 16384:
        add(BLOCKING, f"Unités par em hors limites (16 à 16384) : {info.unitsPerEm}.")
    for cycle in components.find_cycles(font):
        add(BLOCKING, f"Cycle de composants : {' -> '.join(cycle)}.", cycle[0])
    seen: dict[int, str] = {}
    for glyph in font:
        name = glyph.name
        if not _NAME_RE.match(name) or len(name) > 63:
            add(BLOCKING, f"Nom de glyphe invalide : « {name} » (lettres ASCII, chiffres, _ . -, 63 car. max).", name)
        for code in glyph.unicodes:
            if code in seen:
                add(BLOCKING, f"U+{code:04X} attribué à « {seen[code]} » et à « {name} ».", name)
            seen[code] = name
        for comp in glyph.components:
            if comp.baseGlyph not in font:
                add(BLOCKING, f"{name} : composant « {comp.baseGlyph} » introuvable.", name)
        for k, contour in enumerate(glyph.contours):
            if not C.is_closed(contour):
                add(BLOCKING, f"{name} : contour {k + 1} ouvert (une police ne remplit que des contours fermés).", name)
            elif len([p for p in contour if p.type]) < 2:
                add(WARNING, f"{name} : contour {k + 1} dégénéré (moins de deux nœuds).", name)
        if glyph.width < 0:
            add(WARNING, f"{name} : chasse négative ({glyph.width}).", name)
        out += [Diagnostic(level, msg, name, master) for level, msg in _glyph_quality(glyph)]
        if glyph.unicodes and not glyph.contours and not glyph.components and not _is_blank(glyph.unicodes[0]):
            add(WARNING, f"{name} : glyphe vide pour U+{glyph.unicodes[0]:04X}.", name)
    errors = features.check(font.features.text or "", font.keys())
    for err in errors:
        add(BLOCKING, f"Features : {err}")
    groups_left, groups_right = {}, {}
    for group, members in font.groups.items():
        target = groups_left if group.startswith(kerning.KERN1) else groups_right if group.startswith(kerning.KERN2) \
            else None
        if target is None:
            continue
        for g in members:
            if g in target and target[g] != group:
                add(WARNING, f"« {g} » est dans deux classes de crénage ({target[g]}, {group}).", g)
            target[g] = group
            if g not in font:
                add(WARNING, f"Classe {group} : glyphe « {g} » introuvable.")
    for left, right in font.kerning:
        for side in (left, right):
            if side not in font and side not in font.groups:
                add(WARNING, f"Paire de crénage ({left}, {right}) : « {side} » introuvable.")
                break
    for attr, label in (("ascender", "ascendante"), ("descender", "descendante"), ("capHeight", "hauteur de capitale"),
                        ("xHeight", "hauteur d'x")):
        if getattr(info, attr) is None:
            add(WARNING, f"Métrique verticale « {label} » non renseignée.")
    cmap = {c for g in font for c in g.unicodes}
    missing_basic = [c for c in glyph_info.CHARSETS["Latin de base"] if c not in cmap]
    if missing_basic and len(missing_basic) < len(glyph_info.CHARSETS["Latin de base"]):
        add(SUGGESTION, f"{len(missing_basic)} caractère(s) du latin de base manquant(s) "
                        f"(ex. « {chr(missing_basic[0])} »).")
    return out


def _is_blank(code: int) -> bool:
    import unicodedata
    return unicodedata.category(chr(code)) in ("Zs", "Cc", "Cf", "Zl", "Zp")


def _glyph_quality(glyph) -> list[tuple[str, str]]:
    out = []
    name = glyph.name
    if len(glyph.contours) and C.wrong_directions(glyph):
        out.append((WARNING, f"{name} : sens de contour incorrect (extérieur anti-horaire attendu)."))
    for k, contour in enumerate(glyph.contours):
        for seg in C.segments(contour):
            if seg[3] == "curve" and len(seg[1]) == 2 and _missing_extremum(C.segment_points(contour, seg)):
                out.append((SUGGESTION, f"{name} : point d'extremum manquant (contour {k + 1})."))
                break
        pts = contour.points
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            if p is not q and p.type and q.type == "line" and abs(p.x - q.x) < 0.5 and abs(p.y - q.y) < 0.5:
                out.append((WARNING, f"{name} : nœuds confondus (contour {k + 1})."))
                break
    return out


def _missing_extremum(pts) -> bool:
    """Extremum horizontal ou vertical strictement à l'intérieur d'une cubique (les logiciels préfèrent un nœud
    à chaque extremum)."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
    for a, b, c, d in ((x0, x1, x2, x3), (y0, y1, y2, y3)):
        # dérivée : 3[(b-a)(1-t)^2 + 2(c-b)t(1-t) + (d-c)t^2]
        qa = (b - a) - 2 * (c - b) + (d - c)
        qb = 2 * ((c - b) - (b - a))
        qc = b - a
        roots = []
        if abs(qa) < 1e-9:
            if abs(qb) > 1e-9:
                roots.append(-qc / qb)
        else:
            disc = qb * qb - 4 * qa * qc
            if disc >= 0:
                s = disc ** 0.5
                roots += [(-qb + s) / (2 * qa), (-qb - s) / (2 * qa)]
        for t in roots:
            if 0.02 < t < 0.98:
                value = (1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d
                if abs(value - a) > 1 and abs(value - d) > 1:
                    return True
    return False


def fontbakery_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("fontbakery") is not None


_FB_LEVELS = {"FATAL": WARNING, "ERROR": WARNING, "FAIL": WARNING, "WARN": SUGGESTION}
_FB_ORDER = ("FATAL", "ERROR", "FAIL", "WARN", "INFO", "SKIP", "PASS")


def parse_fontbakery(report: dict) -> list[Diagnostic]:
    """Diagnostics tirés du rapport JSON de FontBakery (contrôles FAIL / WARN / ERROR seulement)."""
    out = []
    for section in report.get("sections", []):
        for check in section.get("checks", []):
            statuses = [log.get("status") for log in check.get("logs", [])]
            worst = min(statuses, key=lambda s: _FB_ORDER.index(s) if s in _FB_ORDER else 99, default=None)
            if worst not in _FB_LEVELS:
                continue
            detail = next((log.get("message", {}) for log in check.get("logs", []) if log.get("status") == worst),
                          {})
            message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
            first = " ".join(message.split())[:220]
            out.append(Diagnostic(_FB_LEVELS[worst], f"FontBakery {worst} — {check.get('description', '')}"
                                                     + (f" : {first}" if first else "")))
    order = {BLOCKING: 0, WARNING: 1, SUGGESTION: 2}
    out.sort(key=lambda d: order[d.level])
    return out


def run_fontbakery(font_path, timeout: int = 300) -> list[Diagnostic]:
    """FontBakery (profil universel) sur une police compilée, dans un processus à part (interpréteur courant :
    pas besoin de `fontbakery` dans le PATH). À appeler hors du fil de l'interface (~4 s)."""
    if not fontbakery_available():
        return [Diagnostic(WARNING, "FontBakery n'est pas installé (pip install fontbakery) : diagnostic intégré "
                                    "seulement.")]
    with tempfile.TemporaryDirectory(prefix="fmfont_fb_") as folder:
        report = Path(folder) / "rapport.json"
        result = subprocess.run([sys.executable, "-m", "fontbakery", "check-universal", "-l", "WARN", "--json",
                                 str(report), str(font_path)], capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace",
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not report.is_file():
            last = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["sans message"]
            return [Diagnostic(WARNING, f"FontBakery n'a pas produit de rapport : {last[0]}")]
        found = parse_fontbakery(json.loads(report.read_text(encoding="utf-8")))
    return found or [Diagnostic(SUGGESTION, "FontBakery : aucun FAIL ni WARN.")]
