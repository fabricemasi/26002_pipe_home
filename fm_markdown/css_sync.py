"""Synchronisation des reglages Markdown avec la feuille CSS partagee avec Obsidian (Reglages > Markdown > CSS).

LA FEUILLE EST UNE SOURCE DE STYLE COMMUNE aux deux applications :
- un reglage change dans Pipeline Browser est montre AUSSITOT dans le module (le bloc gere, recalcule en memoire, est
  pose dans la page : `injectionChanged`), puis ecrit dans le fichier apres une courte pause, au relachement de la
  souris (`WRITE_DELAY_MS`) — jamais a chaque cran ;
- le fichier modifie ailleurs (Obsidian, editeur) est relu : les valeurs que le module sait interpreter sont reprises
  dans les reglages (`HOOKS["external"]`), la page recharge la feuille (`fileChanged`).

METHODE (robuste, non destructive) : Pipeline Browser ne gere QUE le contenu d'un bloc delimite par deux commentaires
(`BEGIN` … `END`), cree a la fin du fichier au premier reglage change ; dans ce bloc il ne modifie QUE les
declarations qu'il connait (table `DECLS` : un selecteur d'Obsidian, une propriete, les reglages qui la donnent), une
par une, sur place (`patch`). Tout le reste — regles, commentaires, selecteurs et valeurs personnalisees, y compris
ajoutes dans le bloc — est garde octet pour octet ; encodage, BOM et fins de ligne aussi (`markdown_preview.read_note`
/ `write_note`, ecriture par fichier temporaire). Seules les declarations des reglages CHANGES ici sont ecrites : le
fichier n'est jamais reecrit en entier et les styles propres a Obsidian ne sont pas remplaces par les valeurs d'origine.

Les declarations du bloc sont en `!important` sur des selecteurs d'Obsidian plus precis que ceux d'une feuille
ecrite a la main (bloc a la fin) : dans Obsidian comme dans le module, elles l'emportent sur le reste du fichier pour
ces proprietes seulement. Les regles techniques du module (web/structure.css) ne sont jamais dans ce fichier.

CONFLITS : avant chaque ecriture le fichier est relu ; modifie entre-temps, ses valeurs sont d'abord reprises. Une
meme declaration changee des deux cotes avant l'ecriture : celle de Pipeline Browser (le geste le plus recent) gagne
et l'etat le signale. Une valeur que le module ne sait pas interpreter (unite `em`, `var(…)`, `calc(…)`…) reste dans
le fichier et dans la page telle quelle ; le reglage n'est pas touche (il ne l'ecrase que si on le change ici)."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication

from fm_markdown import preview as markdown_preview
from fm_markdown.settings_defaults import MARKDOWN_DEFAULTS
from fm_markdown import style

BEGIN = "/* pipeline-browser:sync:begin"
END = "/* pipeline-browser:sync:end */"
BEGIN_COMMENT = (BEGIN + "\n   Réglages Markdown de Pipeline Browser (Réglages > Markdown), synchronisés dans les deux sens :\n"
                 "   une valeur changée ici (Obsidian, éditeur) est reprise par Pipeline Browser, et inversement.\n"
                 "   Seules les propriétés connues de ce bloc sont modifiées ; le reste du fichier ne l'est jamais. */")
WRITE_DELAY_MS = 400            # ecriture regroupee apres le dernier changement (et la souris relachee)
HOOKS: dict = {}                # "external": callable(dict) — reglages repris du fichier, a appliquer par l'appli

R = ".markdown-rendered"
S = ".markdown-source-view.mod-cm6"
ROOT = "body.theme-dark, body.theme-light"
SIDES = ("top", "right", "bottom", "left")


# -- Lecture des valeurs CSS ---------------------------------------------------------------------------------------
_NAMED = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0),
          "blue": (0, 0, 255), "yellow": (255, 255, 0), "orange": (255, 165, 0), "gray": (128, 128, 128),
          "grey": (128, 128, 128), "silver": (192, 192, 192)}


def _strip_important(css: str) -> str:
    return re.sub(r"\s*!\s*important\s*$", "", css.strip(), flags=re.I)


def css_to_color(css: str) -> str | None:
    """Couleur CSS -> « #aarrggbb » (format des reglages) ; None si non interpretable (var(), fonction…)."""
    s = css.strip().lower()
    if s == "transparent":
        return "#00000000"
    if s in _NAMED:
        r, g, b = _NAMED[s]
        return f"#ff{r:02x}{g:02x}{b:02x}"
    m = re.fullmatch(r"#([0-9a-f]{3,8})", s)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) == 6:
            return f"#ff{h}"
        if len(h) == 8:
            return f"#{h[6:]}{h[:6]}"
        return None
    m = re.fullmatch(r"rgba?\(\s*([^)]*)\)", s)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(1)) if p]
    if len(parts) not in (3, 4):
        return None
    try:
        rgb = [max(0, min(255, round(float(p[:-1]) * 2.55 if p.endswith("%") else float(p)))) for p in parts[:3]]
        a = parts[3] if len(parts) == 4 else "1"
        alpha = float(a[:-1]) / 100 if a.endswith("%") else float(a)
    except ValueError:
        return None
    return f"#{round(max(0.0, min(1.0, alpha)) * 255):02x}{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _number(css: str, unit: str = "px") -> float | None:
    m = re.fullmatch(rf"(-?\d+(?:\.\d+)?|-?\.\d+)({unit})?", css.strip().lower())
    if not m or (m.group(2) is None and float(m.group(1)) != 0 and unit == "px"):
        return None
    return float(m.group(1))


def _px_list(css: str) -> list[int] | None:
    values = [_number(t) for t in css.split()]
    return None if not values or len(values) > 4 or None in values else [int(round(v)) for v in values]


def _box_sides(values: list[int]) -> dict:
    t, r, b, l = (values * 4)[:1] * 4 if len(values) == 1 else (
        (values[0], values[1], values[0], values[1]) if len(values) == 2 else
        (values[0], values[1], values[2], values[1]) if len(values) == 3 else tuple(values))
    return {"left": l, "top": t, "right": r, "bottom": b}


def _corners(values: list[int]) -> dict:
    tl, tr, br, bl = (values * 4)[:4] if len(values) == 1 else (
        (values[0], values[1], values[0], values[1]) if len(values) == 2 else
        (values[0], values[1], values[2], values[1]) if len(values) == 3 else tuple(values))
    return {"top_left": tl, "top_right": tr, "bottom_right": br, "bottom_left": bl}


def _first_family(css: str) -> str | None:
    first = next(iter(re.findall(r'"[^"]*"|\'[^\']*\'|[^,]+', css)), "").strip().strip("\"'").strip()
    if not first or "(" in first:
        return None
    return "Systeme" if first.lower() in ("system-ui", "sans-serif", "-apple-system") else first


# -- Table des declarations gerees ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Decl:
    id: str
    selector: str
    prop: str
    keys: tuple
    fwd: Callable          # (variables brutes, reglages) -> valeur CSS, ou None (non geree pour ces reglages)
    parse: Callable | None  # (valeur CSS, reglages) -> {cle: valeur} ou None (non interpretable)


def _get(values: dict, key: str):
    value = values.get(key)
    return MARKDOWN_DEFAULTS.get(key) if value is None else value


def _p_color(key):
    return lambda css, v: (lambda c: None if c is None else {key: c})(css_to_color(css))


def _p_px(key):
    return lambda css, v: (lambda n: None if n is None else {key: int(round(n))})(_number(css))


def _p_translate_y(key):
    def parse(css, _values):
        match = re.fullmatch(r"translateY\(\s*(-?\d+(?:\.\d+)?)px\s*\)", css.strip(), re.I)
        return {key: int(round(float(match.group(1))))} if match else None
    return parse


def _p_scaled(key, unit, factor):
    return lambda css, v: (lambda n: None if n is None else {key: int(round(n * factor))})(_number(css, unit))


def _p_lh(key):
    def parse(css, v):
        try:
            return {key: int(round(float(css.strip()) * 100))}
        except ValueError:
            return None
    return parse


def _p_family(key):
    return lambda css, v: (lambda f: None if f is None else {key: f})(_first_family(css))


def _p_weight(key, as_bool=False):
    def parse(css, v):
        s = css.strip().lower()
        weight = {"bold": 700, "normal": 400, "bolder": 700, "lighter": 300}.get(s)
        if weight is None:
            try:
                weight = int(float(s))
            except ValueError:
                return None
        return {key: weight >= 600} if as_bool else {key: max(100, min(900, weight))}
    return parse


def _p_italic(key):
    return lambda css, v: {key: css.strip().lower() in ("italic", "oblique")} if css.strip().lower() in (
        "italic", "oblique", "normal") else None


def _p_flag(key, on_word):
    return lambda css, v: {key: on_word in css.lower()} if (on_word in css.lower() or css.strip().lower() == "none") \
        else None


def _p_box(key):
    return lambda css, v: (lambda l: None if l is None else {key: _box_sides(l)})(_px_list(css))


def _p_radius(key):
    return lambda css, v: (lambda l: None if l is None else {key: _corners(l)})(_px_list(css))


def _p_margin_v(key):
    return lambda css, v: (lambda l: None if l is None else {key: l[0]})(_px_list(css))


def _p_char(key):
    def parse(css, v):
        m = re.fullmatch(r'\s*"((?:[^"\\]|\\.)*)"\s*|\s*\'((?:[^\'\\]|\\.)*)\'\s*', css)
        if not m:
            return None
        text = m.group(1) if m.group(1) is not None else m.group(2)
        return {key: re.sub(r"\\(.)", r"\1", text)} if text else None
    return parse


def _p_border_side(base, side):
    """« Npx solid C » / none -> cote allume, sa couleur, l'epaisseur (commune)."""
    def parse(css, v):
        enabled = dict(_get(v, f"{base}_enabled") or {})
        colors = dict(_get(v, base) or {})
        s = css.strip().lower()
        if s in ("none", "0", "hidden") or s.startswith("0 ") or s.startswith("0px "):
            enabled[side] = False
            return {f"{base}_enabled": enabled}
        m = re.fullmatch(r"(\S+)\s+(solid|dashed|dotted|double)\s+(.+)", css.strip(), flags=re.I)
        width = _number(m.group(1)) if m else None
        color = css_to_color(m.group(3)) if m else None
        if width is None or color is None:
            return None
        enabled[side], colors[side] = True, color
        return {f"{base}_enabled": enabled, base: colors, f"{base}_thickness": int(round(width))}
    return parse


def _f(name):
    """Valeur brute d'une variable --md-* ; « inherit » / « currentColor » = rien a ecrire."""
    def fwd(out, v):
        value = out.get(name)
        return None if value in (None, "inherit", "currentColor", "var(--md-text-font)") else value
    return fwd


def _f_family(name, prefix):
    def fwd(out, v):
        if prefix in style._INHERIT_TEXT_FONT and style._inherits_text_font(v, prefix):
            return None                                    # police du texte : rien de propre a ce titre
        value = out.get(name)
        return None if value in (None, "inherit") else value
    return fwd


def _f_border(name, side):
    return lambda out, v: (lambda value: "none" if value.startswith("0 ") else value)(out[f"--md-{name}-border-{side}"])


DECLS: list[Decl] = []


def _add(id_, selector, prop, keys, fwd, parse):
    DECLS.append(Decl(id_, selector, prop, tuple(keys), fwd, parse))


def _font(group, selector, prefix, name, weight_key=None, bold_key=None, family=True, size=True, italic=True):
    _add(f"{group}.color", selector, "color", [f"{prefix}_font_color"], _f(f"--md-{name}-color"),
         _p_color(f"{prefix}_font_color"))
    if family:
        _add(f"{group}.family", selector, "font-family", [f"{prefix}_font_family"], _f_family(f"--md-{name}-font", prefix),
             _p_family(f"{prefix}_font_family"))
    if size:
        _add(f"{group}.size", selector, "font-size", [f"{prefix}_font_size"], _f(f"--md-{name}-size"),
             _p_px(f"{prefix}_font_size"))
    if weight_key or bold_key:
        _add(f"{group}.weight", selector, "font-weight", [weight_key or bold_key], _f(f"--md-{name}-weight"),
             _p_weight(weight_key or bold_key, as_bool=bool(bold_key)))
    if italic:
        _add(f"{group}.style", selector, "font-style", [f"{prefix}_font_italic"], _f(f"--md-{name}-style"),
             _p_italic(f"{prefix}_font_italic"))


def _build():
    # Page (variables d'Obsidian)
    for id_, var, md, key in (("bg", "--background-primary", "--md-bg", "md_bg_color"),
                              ("bg2", "--background-secondary", "--md-bg-secondary", "md_bg_secondary"),
                              ("selection", "--text-selection", "--md-selection", "md_selection_color"),
                              ("caret", "--caret-color", "--md-caret", "md_caret_color"),
                              ("checkbox", "--checkbox-color", "--md-checkbox-color", "md_checkbox_color"),
                              ("task_done", "--checklist-done-color", "--md-task-done-color", "md_task_done_color"),
                              ("hr", "--hr-color", "--md-hr-color", "md_hr_color")):
        _add(f"var.{id_}", ROOT, var, [key], _f(md), _p_color(key))
    for id_, var, md, key in (("p_spacing", "--p-spacing", "--md-p-spacing", "md_paragraph_spacing"),
                              ("list_indent", "--list-indent", "--md-list-indent", "md_list_indent"),
                              ("list_spacing", "--list-spacing", "--md-list-spacing", "md_list_spacing"),
                              ("checkbox_size", "--checkbox-size", "--md-checkbox-size", "md_checkbox_size"),
                              ("hr_thickness", "--hr-thickness", "--md-hr-thickness", "md_hr_thickness")):
        _add(f"var.{id_}", ROOT, var, [key], _f(md), _p_px(key))
    _add("var.task_done_strike", ROOT, "--checklist-done-decoration", ["md_task_done_strike"],
         _f("--md-task-done-decoration"), _p_flag("md_task_done_strike", "line-through"))
    _add("var.link_hover", ROOT, "--link-decoration-hover", ["md_link_hover_underline"],
         _f("--md-link-hover-decoration"), _p_flag("md_link_hover_underline", "underline"))
    # Les themes Obsidian n'appliquent pas tous la couleur directement au lien : plusieurs la definissent par
    # --link-color / --link-external-color. Les synchroniser aussi garantit que les themes bases sur ces variables
    # suivent le choix de couleur fait dans Pipeline Browser.
    for variable in ("--link-color", "--link-external-color"):
        _add("var." + variable[2:].replace("-", "_"), ROOT, variable, ["md_link_font_color"],
             _f("--md-link-color"), _p_color("md_link_font_color"))
    _add("var.link_unresolved", ROOT, "--link-unresolved-opacity", ["md_link_unresolved_opacity"],
         _f("--md-link-unresolved-opacity"), _p_scaled("md_link_unresolved_opacity", "", 100))
    # Cadre de la page dans Obsidian. Le module utilise ses propres variables pour la meme apparence.
    page = ('.workspace-leaf-content[data-type="markdown"] .view-content > .markdown-source-view, '
            '.workspace-leaf-content[data-type="markdown"] .view-content > .markdown-reading-view')
    _add("page.margin", page, "margin", ["md_page_margin"],
         lambda out, v: style._box(_get(v, "md_page_margin")), _p_box("md_page_margin"))
    _add("page.radius", page, "border-radius", ["md_page_radius"], _f("--md-page-radius"),
         _p_radius("md_page_radius"))
    # Le fond porte lui-meme le rayon : le fond de la page Obsidian suit donc les coins, pas seulement le trait.
    _add("page.background", page, "background-color", ["md_bg_color"], _f("--md-bg"),
         _p_color("md_bg_color"))
    for side in ("top", "right", "bottom", "left"):
        _add(f"page.border_{side}", page, f"border-{side}",
             ["md_page_border_enabled", "md_page_border", "md_page_border_thickness"],
             _f_border("page", side), _p_border_side("md_page_border", side))
    # Variables natives d'Obsidian pour les couleurs de defilement.
    for ident, var, key in (("thumb", "--scrollbar-thumb-bg", "md_scroll_thumb_color"),
                            ("hover", "--scrollbar-active-thumb-bg", "md_scroll_thumb_hover_color"),
                            ("track", "--scrollbar-bg", "md_scroll_track_color")):
        _add(f"scroll.{ident}", ROOT, var, [key], _f("--md-scroll-" + key.removeprefix("md_scroll_").replace("_", "-")),
             _p_color(key))
    scroll = '.workspace-leaf-content[data-type="markdown"]'
    _add("scroll.width", f"{scroll} ::-webkit-scrollbar", "width", ["md_scroll_width", "md_scroll_offset"],
         lambda out, v: f"{max(0, int(_get(v, 'md_scroll_width'))) + max(0, int(_get(v, 'md_scroll_offset')))}px", None)
    _add("scroll.radius", f"{scroll} ::-webkit-scrollbar-thumb", "border-radius", ["md_scroll_radius"],
         _f("--md-scroll-radius"), _p_px("md_scroll_radius"))
    _add("scroll.offset", f"{scroll} ::-webkit-scrollbar-thumb:vertical", "border-right", ["md_scroll_offset", "md_scroll_padding"],
         lambda out, v: f"calc({out['--md-scroll-offset']} + {out['--md-scroll-padding']}) solid transparent", None)
    for side in ("top", "bottom", "left"):
        _add(f"scroll.padding.{side}", f"{scroll} ::-webkit-scrollbar-thumb", f"border-{side}", ["md_scroll_padding"],
             lambda out, v: out["--md-scroll-padding"] + " solid transparent", None)
    _add("scroll.clip", f"{scroll} ::-webkit-scrollbar-thumb:vertical", "background-clip", ["md_scroll_offset"],
         lambda out, v: "padding-box", None)
    # Texte
    text = f"{R}, {S} .cm-line"
    _font("text", text, "md_text", "text", weight_key="md_text_weight", italic=False)
    _add("text.line_height", text, "line-height", ["md_line_height"], _f("--md-line-height"), _p_lh("md_line_height"))
    _add("text.letter_spacing", text, "letter-spacing", ["md_letter_spacing"], _f("--md-letter-spacing"),
         _p_scaled("md_letter_spacing", "px", 10))
    # Titre de la note
    title = "body .inline-title"
    _font("title", title, "md_title", "title", weight_key="md_title_weight")
    _add("title.spacing", title, "margin-bottom", ["md_title_spacing"], _f("--md-title-spacing"),
         _p_px("md_title_spacing"))
    _add("title.display", title, "display", ["md_title_enabled"],
         lambda out, v: None if _get(v, "md_title_enabled") else "none",
         lambda css, v: {"md_title_enabled": css.strip().lower() != "none"})
    # Titres
    for n in range(1, 7):
        heading = f"{R} h{n}, {S} .cm-line .cm-header-{n}"
        _font(f"h{n}", heading, f"md_h{n}", f"h{n}", weight_key=f"md_h{n}_weight")
        _add(f"h{n}.line_height", heading, "line-height", [f"md_h{n}_line_height"], _f(f"--md-h{n}-line-height"),
             _p_lh(f"md_h{n}_line_height"))
        for edge, md_edge in (("top", "before"), ("bottom", "after")):
            key = f"md_h{n}_space_{md_edge}"
            _add(f"h{n}.margin_{edge}", f"{R} h{n}", f"margin-{edge}", [key], _f(f"--md-h{n}-{md_edge}"), _p_px(key))
            _add(f"h{n}.padding_{edge}", f"{S} .cm-line.HyperMD-header-{n}", f"padding-{edge}", [key],
                 _f(f"--md-h{n}-{md_edge}"), _p_px(key))
    # Mise en forme
    bold = f"{R} strong, {R} b, {S} .cm-strong"
    _add("bold.color", bold, "color", ["md_bold_color"], _f("--md-bold-color"), _p_color("md_bold_color"))
    _add("bold.weight", bold, "font-weight", ["md_bold_weight"], _f("--md-bold-weight"), _p_weight("md_bold_weight"))
    _add("italic.color", f"{R} em, {R} i, {S} .cm-em", "color", ["md_italic_color"], _f("--md-italic-color"),
         _p_color("md_italic_color"))
    strike = f"{R} del, {R} s, {S} .cm-strikethrough"
    for prop, key, md in (("color", "md_strike_color", "--md-strike-color"),
                          ("text-decoration-color", "md_strike_line_color", "--md-strike-line"),
                          ("background-color", "md_strike_bg", "--md-strike-bg")):
        _add(f"strike.{prop}", strike, prop, [key], _f(md), _p_color(key))
    mark = f"{R} mark, {S} .cm-highlight"
    _add("highlight.color", mark, "color", ["md_highlight_color"], _f("--md-highlight-color"),
         _p_color("md_highlight_color"))
    _add("highlight.bg", mark, "background-color", ["md_highlight_bg"], _f("--md-highlight-bg"),
         _p_color("md_highlight_bg"))
    tag = f"{R} a.tag, {S} .cm-hashtag"
    _add("tag.color", tag, "color", ["md_tag_color"], _f("--md-tag-color"), _p_color("md_tag_color"))
    _add("tag.bg", tag, "background-color", ["md_tag_bg"], _f("--md-tag-bg"), _p_color("md_tag_bg"))
    # Liens
    link = (f"{R} a, .markdown-preview-view a, {S} .cm-hmd-internal-link, {S} .cm-link, {S} .cm-url, "
            f"{S} .cm-hmd-internal-link .cm-underline, {S} .cm-link .cm-underline, {S} .cm-url .cm-underline")
    _font("link", link, "md_link", "link", italic=False)
    _add("link.letter_spacing", link, "letter-spacing", ["md_link_letter_spacing"], _f("--md-link-letter-spacing"),
         _p_scaled("md_link_letter_spacing", "px", 10))
    _add("link.decoration", link, "text-decoration", ["md_link_underline"], _f("--md-link-decoration"),
         _p_flag("md_link_underline", "underline"))
    # Listes (puces de l'edition : meme principe que fabrice.css, le tiret masque, la puce dessinee par ::before)
    # Toutes les declarations des puces vont ensemble (une puce sans taille serait invisible dans Obsidian).
    bullets = [f"md_bullet_{n}_{part}" for n in (1, 2, 3) for part in ("char", "font_color", "font_size")]
    _add("list.bullet_hide_size", f"{S} .list-bullet", "font-size", bullets, lambda out, v: "0", None)
    _add("list.bullet_hide_color", f"{S} .list-bullet", "color", bullets, lambda out, v: "transparent", None)
    _add("list.bullet_hide_after", f"{S} .list-bullet::after", "display", bullets, lambda out, v: "none", None)
    for n in (1, 2, 3):
        selector = f"{S} .cm-list-{n} .list-bullet::before"
        _add(f"bullet{n}.char", selector, "content", bullets, _f(f"--md-bullet-{n}-char"),
             _p_char(f"md_bullet_{n}_char"))
        _add(f"bullet{n}.color", selector, "color", bullets, _f(f"--md-bullet-{n}-color"),
             _p_color(f"md_bullet_{n}_font_color"))
        _add(f"bullet{n}.fill", selector, "-webkit-text-fill-color", bullets, _f(f"--md-bullet-{n}-color"), None)
        _add(f"bullet{n}.shadow", selector, "text-shadow", bullets, lambda out, v: "none", None)
        _add(f"bullet{n}.size", selector, "font-size", bullets, _f(f"--md-bullet-{n}-size"),
             _p_px(f"md_bullet_{n}_font_size"))
        _add(f"bullet{n}.vertical_offset", selector, "transform", [f"md_bullet_{n}_vertical_offset"],
             lambda out, v, n=n: f"translateY({out[f'--md-bullet-{n}-vertical-offset']})",
             _p_translate_y(f"md_bullet_{n}_vertical_offset"))
    _add("number.color", f"{R} ol > li::marker, {S} .cm-formatting-list-ol", "color", ["md_number_color"],
         _f("--md-number-color"), _p_color("md_number_color"))
    # Citations
    quote_r, quote_s = f"{R} blockquote", f"{S} .cm-line.HyperMD-quote"
    _add("quote.bg", f"{quote_r}, {quote_s}", "background-color", ["md_quote_bg"], _f("--md-quote-bg"),
         _p_color("md_quote_bg"))
    quote_text = f"{quote_r}, {quote_s}, {quote_s} span:not(.cm-formatting-quote)"
    _add("quote.color", quote_text, "color", ["md_quote_font_color"], _f("--md-quote-color"),
         _p_color("md_quote_font_color"))
    _add("quote.style", quote_text, "font-style", ["md_quote_font_italic"], _f("--md-quote-style"),
         _p_italic("md_quote_font_italic"))
    _add("quote.border_left", quote_r, "border-left", ["md_quote_border_enabled", "md_quote_border",
                                                       "md_quote_border_thickness"],
         _f_border("quote", "left"), _p_border_side("md_quote_border", "left"))
    _add("quote.radius", quote_r, "border-radius", ["md_quote_radius"], _f("--md-quote-radius"),
         _p_radius("md_quote_radius"))
    _add("quote.padding", quote_r, "padding", ["md_quote_padding"], _f("--md-quote-padding"),
         _p_box("md_quote_padding"))
    _add("quote.margin", quote_r, "margin", ["md_quote_spacing"],
         lambda out, v: f"{out['--md-quote-spacing']} 0", _p_margin_v("md_quote_spacing"))
    # Callouts
    _add("callout.bg", ".callout", "background-color", ["md_callout_bg"], _f("--md-callout-bg"),
         _p_color("md_callout_bg"))
    _add("callout.border", ".callout", "border-left", ["md_callout_border_width", "md_callout_border_color"],
         _f("--md-callout-border"),
         lambda css, v: (lambda p: None if p is None or not p.get("md_callout_border_enabled", {}).get("left") else {
             "md_callout_border_width": p["md_callout_border_thickness"],
             "md_callout_border_color": p["md_callout_border"]["left"]})(
             _p_border_side("md_callout_border", "left")(css, {"md_callout_border_enabled": {}, "md_callout_border": {}})))
    _add("callout.radius", ".callout", "border-radius", ["md_callout_radius"], _f("--md-callout-radius"),
         _p_radius("md_callout_radius"))
    _add("callout.title", ".callout .callout-title", "color", ["md_callout_title_color"],
         _f("--md-callout-title-color"), _p_color("md_callout_title_color"))
    # Code en ligne
    inline = f"{R} :not(pre) > code, {S} .cm-inline-code:not(.cm-formatting)"
    _font("code_inline", inline, "md_code_inline", "code-inline", weight_key="md_code_inline_weight", italic=False)
    _add("code_inline.bg", inline, "background-color", ["md_code_inline_bg"], _f("--md-code-inline-bg"),
         _p_color("md_code_inline_bg"))
    _add("code_inline.radius", inline, "border-radius", ["md_code_inline_radius"], _f("--md-code-inline-radius"),
         _p_radius("md_code_inline_radius"))
    _add("code_inline.padding", inline, "padding", ["md_code_inline_padding"], _f("--md-code-inline-padding"),
         _p_box("md_code_inline_padding"))
    # Blocs de code
    block_text = f"{R} pre code, {S} .cm-line.HyperMD-codeblock, {S} .cm-line.HyperMD-codeblock span"
    _font("codeblock", block_text, "md_codeblock", "codeblock", weight_key="md_codeblock_weight", italic=False)
    _add("codeblock.line_height", f"{R} pre code, {S} .cm-line.HyperMD-codeblock", "line-height",
         ["md_codeblock_line_height"], _f("--md-codeblock-line-height"), _p_lh("md_codeblock_line_height"))
    pre = f"{R} pre"
    _add("codeblock.bg", f"{pre}, {S} .cm-line.HyperMD-codeblock", "background-color", ["md_codeblock_bg"],
         _f("--md-codeblock-bg"), _p_color("md_codeblock_bg"))
    _add("codeblock.radius", pre, "border-radius", ["md_codeblock_radius"], _f("--md-codeblock-radius"),
         _p_radius("md_codeblock_radius"))
    _add("codeblock.padding", pre, "padding", ["md_codeblock_padding"], _f("--md-codeblock-padding"),
         _p_box("md_codeblock_padding"))
    _add("codeblock.margin", pre, "margin", ["md_codeblock_spacing"],
         lambda out, v: f"{out['--md-codeblock-spacing']} 0", _p_margin_v("md_codeblock_spacing"))
    for side in SIDES:
        _add(f"codeblock.border_{side}", pre, f"border-{side}",
             ["md_codeblock_border_enabled", "md_codeblock_border", "md_codeblock_border_thickness"],
             _f_border("codeblock", side), _p_border_side("md_codeblock_border", side))
    corners = lambda out: out["--md-codeblock-radius"].split()          # noqa: E731
    _add("codeblock.begin_tl", f"{S} .cm-line.HyperMD-codeblock-begin", "border-top-left-radius",
         ["md_codeblock_radius"], lambda out, v: corners(out)[0], None)
    _add("codeblock.begin_tr", f"{S} .cm-line.HyperMD-codeblock-begin", "border-top-right-radius",
         ["md_codeblock_radius"], lambda out, v: corners(out)[1], None)
    _add("codeblock.end_br", f"{S} .cm-line.HyperMD-codeblock-end", "border-bottom-right-radius",
         ["md_codeblock_radius"], lambda out, v: corners(out)[2], None)
    _add("codeblock.end_bl", f"{S} .cm-line.HyperMD-codeblock-end", "border-bottom-left-radius",
         ["md_codeblock_radius"], lambda out, v: corners(out)[3], None)
    # Coloration syntaxique (Prism en lecture, CodeMirror en edition)
    for name, prism in (("comment", "comment"), ("keyword", "keyword"), ("string", "string"), ("number", "number"),
                        ("def", "function"), ("variable", "variable"), ("type", "class-name"),
                        ("builtin", "builtin"), ("operator", "operator"), ("property", "property"), ("tag", "tag"),
                        ("attribute", "attr-name"), ("meta", "important")):
        key = f"md_syntax_{name}"
        selector = f"{R} pre code .token.{prism}, {S} .cm-line.HyperMD-codeblock .cm-{name}"
        _add(f"syntax.{name}", selector, "color", [key], _f(f"--md-syntax-{name}"), _p_color(key))
    _add("syntax.comment_style", f"{R} pre code .token.comment, {S} .cm-line.HyperMD-codeblock .cm-comment",
         "font-style", ["md_syntax_italic_comments"], _f("--md-syntax-comment-style"),
         _p_italic("md_syntax_italic_comments"))
    # Tableaux
    table = f"{R} table"
    _add("table.grid", table, "background-color", ["md_table_grid_color"], _f("--md-table-grid"),
         _p_color("md_table_grid_color"))
    _add("table.grid_width", table, "border-spacing", ["md_table_grid_width"], _f("--md-table-grid-width"),
         _p_px("md_table_grid_width"))
    _add("table.radius", table, "border-radius", ["md_table_radius"], _f("--md-table-radius"),
         _p_radius("md_table_radius"))
    _add("table.margin", table, "margin", ["md_table_spacing"], lambda out, v: f"{out['--md-table-spacing']} 0",
         _p_margin_v("md_table_spacing"))
    _add("table.padding", f"{R} th, {R} td", "padding", ["md_table_cell_padding"], _f("--md-table-cell-padding"),
         _p_box("md_table_cell_padding"))
    _add("table.cell_bg", f"{R} td", "background-color", ["md_table_cell_bg"], _f("--md-table-cell-bg"),
         _p_color("md_table_cell_bg"))
    _add("table.marked_cell_bg", f"{R} td:has(span.pb-table-cell-bg), {R} th:has(span.pb-table-cell-bg)",
         "overflow", ["md_table_cell_bg"], lambda out, v: "hidden", None)
    _add("table.marked_cell_padding", f"{R} td:has(span.pb-table-cell-bg), {R} th:has(span.pb-table-cell-bg)",
         "padding", ["md_table_cell_bg"], lambda out, v: "0", None)
    _font("table", f"{R} td", "md_table", "table", bold_key="md_table_font_bold", family=False, italic=False)
    _add("table.alt_bg", f"{R} tbody tr:nth-child(2n) td", "background-color", ["md_table_alt_bg"],
         _f("--md-table-alt-bg"), _p_color("md_table_alt_bg"))
    _add("table.head_bg", f"{R} th", "background-color", ["md_table_head_bg"], _f("--md-table-head-bg"),
         _p_color("md_table_head_bg"))
    _font("table_head", f"{R} th", "md_table_head", "table-head", bold_key="md_table_head_font_bold", family=False,
          italic=False)
    # Separateurs, images
    _add("hr.margin", f"{R} hr", "margin", ["md_hr_spacing"], lambda out, v: f"{out['--md-hr-spacing']} 0",
         _p_margin_v("md_hr_spacing"))
    image = f"{R} img, {S} img"
    _add("image.max_width", image, "max-width", ["md_image_max_width"], _f("--md-image-max-width"),
         _p_scaled("md_image_max_width", "%", 1))
    _add("image.radius", image, "border-radius", ["md_image_radius"], _f("--md-image-radius"),
         _p_radius("md_image_radius"))


_build()
BY_ID = {d.id: d for d in DECLS}
KEY_INDEX: dict[str, list[Decl]] = {}
for _d in DECLS:
    for _k in _d.keys:
        KEY_INDEX.setdefault(_k, []).append(_d)
SYNCED_KEYS = frozenset(KEY_INDEX)


def _norm(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s*,\s*", ", ", text)


def _norm_value(css: str) -> str:
    return _norm(_strip_important(css)).lower().replace("'", '"').replace(", ", ",")


_SELECTORS = {}
for _d in DECLS:
    _SELECTORS.setdefault(_norm(_d.selector), {}).setdefault(_d.prop, _d)


# -- Analyse du bloc -------------------------------------------------------------------------------------------------
@dataclass
class _Prop:
    name: str
    start: int            # debut de la declaration
    value_start: int
    value_end: int
    end: int              # apres le « ; » eventuel


@dataclass
class _Rule:
    selector: str
    body_start: int
    body_end: int         # position du « } »
    text: str

    @property
    def props(self) -> list:          # analysees seulement pour les regles visees
        return _props(self.text, self.body_start, self.body_end)


def _skip(text: str, i: int, end: int) -> int:
    """Saute les blancs et commentaires."""
    while i < end:
        if text[i].isspace():
            i += 1
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = end if j < 0 else j + 2
        else:
            break
    return i


_FIND_RE: dict = {}


def _find(text: str, i: int, end: int, chars: str) -> int:
    """Premier caractere de `chars` hors chaines, commentaires et parentheses ; `end` sinon (saut par expression
    reguliere : l'analyse d'un bloc de ~200 declarations reste sous la milliseconde)."""
    pattern = _FIND_RE.get(chars)
    if pattern is None:
        pattern = _FIND_RE[chars] = re.compile(r"/\*|[\"'()" + re.escape(chars) + "]")
    depth = 0
    while i < end:
        m = pattern.search(text, i, end)
        if m is None:
            return end
        j, token = m.start(), m.group()
        if token == "/*":
            k = text.find("*/", j + 2)
            i = end if k < 0 else k + 2
        elif token in "\"'":
            k = j + 1
            while k < end and text[k] != token:
                k += 2 if text[k] == "\\" else 1
            i = k + 1
        elif token == "(":
            depth, i = depth + 1, j + 1
        elif token == ")":
            depth, i = max(0, depth - 1), j + 1
        elif depth == 0:
            return j
        else:
            i = j + 1
    return end


def _match_brace(text: str, i: int, end: int) -> int:
    """`text[i]` == « { » : position du « } » correspondant."""
    depth = 0
    while i < end:
        j = _find(text, i, end, "{}")
        if j >= end:
            return end
        depth += 1 if text[j] == "{" else -1
        if depth == 0:
            return j
        i = j + 1
    return end


def _props(text: str, start: int, end: int) -> list:
    out, i = [], start
    while i < end:
        i = _skip(text, i, end)
        if i >= end:
            break
        stop = _find(text, i, end, ";{")
        if stop < end and text[stop] == "{":                   # regle imbriquee : laissee telle quelle
            close = _match_brace(text, stop, end)
            i = close + 1
            continue
        colon = _find(text, i, stop, ":")
        if colon < stop:
            name = text[i:colon].strip().lower()
            value_start = _skip(text, colon + 1, stop)
            value_end = stop
            while value_end > value_start and text[value_end - 1].isspace():
                value_end -= 1
            out.append(_Prop(name, i, value_start, value_end, stop + 1 if stop < end else stop))
        i = stop + 1
    return out


def _rules(text: str, start: int, end: int) -> list:
    out, i = [], start
    while i < end:
        i = _skip(text, i, end)
        if i >= end:
            break
        brace = _find(text, i, end, "{;")
        if brace >= end:
            break
        if text[brace] == ";":                                 # @import … ; et autres instructions
            i = brace + 1
            continue
        close = _match_brace(text, brace, end)
        selector = text[i:brace]
        if not selector.lstrip().startswith("@"):
            out.append(_Rule(_norm(selector), brace + 1, close, text))
        i = close + 1
    return out


def block_span(text: str):
    """(debut, fin) du contenu du bloc gere ; None s'il n'y en a pas ; ValueError s'il est incomplet."""
    begin = text.find(BEGIN)
    if begin < 0:
        return None
    start = text.find("*/", begin)
    end = text.find(END, start + 2 if start >= 0 else begin)
    if start < 0 or end < 0:
        raise ValueError("bloc de synchronisation incomplet (commentaire de fin absent)")
    return start + 2, end


def block_text(text: str) -> str:
    try:
        span = block_span(text)
    except ValueError:
        return ""
    return text[span[0]:span[1]] if span else ""


def read_block(text: str) -> dict:
    """{id de declaration: valeur CSS ecrite} pour les declarations connues du bloc (la DERNIERE d'une regle)."""
    try:
        span = block_span(text)
    except ValueError:
        return {}
    if not span:
        return {}
    found = {}
    for rule in _rules(text, *span):
        known = _SELECTORS.get(rule.selector)
        if not known:
            continue
        for prop in rule.props:            # noqa: B007
            decl = known.get(prop.name)
            if decl is not None:
                found[decl.id] = _strip_important(text[prop.value_start:prop.value_end])
    return found


def _with_block(text: str) -> str:
    if block_span(text) is not None:
        return text
    sep = "" if not text or text.endswith("\n") else "\n"
    return f"{text}{sep}\n{BEGIN_COMMENT}\n{END}\n"


def _patch_one(text: str, decl: Decl, css: str | None) -> str:
    start, end = block_span(text)
    written = None if css is None else css + ("" if decl.prop.startswith("--") else " !important")
    target = _norm(decl.selector)
    rule = next((r for r in _rules(text, start, end) if r.selector == target), None)
    if rule is not None:
        props = rule.props
        prop = next((p for p in reversed(props) if p.name == decl.prop), None)
        if prop is not None:
            if written is None:                                # retiree : la ligne entiere
                cut_end = prop.end
                while cut_end < rule.body_end and text[cut_end] in " \t":
                    cut_end += 1
                if cut_end < rule.body_end and text[cut_end] == "\n":
                    cut_end += 1
                cut_start = prop.start
                while cut_start > rule.body_start and text[cut_start - 1] in " \t":
                    cut_start -= 1
                return text[:cut_start] + text[cut_end:]
            return text[:prop.value_start] + written + text[prop.value_end:]
        if written is None:
            return text
        body = text[rule.body_start:rule.body_end]
        head = text[:rule.body_start] + body.rstrip()
        if body.strip() and not body.rstrip().endswith(";"):
            head += ";"
        return f"{head}\n  {decl.prop}: {written};\n" + text[rule.body_end:]
    if written is None:
        return text
    before = text[:end]
    sep = "" if before.endswith("\n") else "\n"
    return f"{before}{sep}{decl.selector} {{\n  {decl.prop}: {written};\n}}\n" + text[end:]


def patch(text: str, updates: dict) -> str:
    """Ecrit les declarations `updates` ({id: valeur CSS ou None = retirer}) dans le bloc, une par une, sur place.
    Le reste du texte est garde tel quel ; le bloc est cree a la fin du fichier s'il n'existe pas."""
    if not updates:
        return text
    if block_span(text) is None:
        if all(css is None for css in updates.values()):
            return text
        text = _with_block(text)
    for decl_id, css in updates.items():
        text = _patch_one(text, BY_ID[decl_id], css)
    return text


def interpret(found: dict, values: dict) -> tuple[dict, list]:
    """Valeurs du bloc -> reglages : ({cle: valeur} qui different des reglages, [ids non interpretables])."""
    updates, unparsed = {}, []
    merged = dict(values)
    out = style.variables(merged)
    for decl_id, css in found.items():
        decl = BY_ID[decl_id]
        current = decl.fwd(out, merged)
        if current is not None and _norm_value(current) == _norm_value(css):
            continue
        if decl.parse is None:
            continue                                         # deduite d'un autre reglage (coins des blocs…)
        parsed = decl.parse(css, merged)
        if parsed is None:
            unparsed.append(decl_id)
            continue
        changed = {k: v for k, v in parsed.items() if merged.get(k, MARKDOWN_DEFAULTS.get(k)) != v}
        if changed:
            merged.update(changed)
            updates.update(changed)
            out = style.variables(merged)
    return updates, unparsed


# -- Moteur ------------------------------------------------------------------------------------------------------------
class CssSync(QObject):
    """Une feuille partagee a la fois (celle de Reglages > Markdown > CSS). Voir le commentaire du module."""

    injectionChanged = Signal(str)      # CSS a poser dans la page (couche md-user, apres la feuille) ; "" = rien
    fileChanged = Signal()              # feuille modifiee hors de l'appli : la page la recharge
    statusChanged = Signal(str)

    def __init__(self, enabled: bool | None = None, parent=None):
        super().__init__(parent)
        self.enabled = (not os.environ.get("PIPELINE_NO_CSS_SYNC")) if enabled is None else enabled
        self.path: Path | None = None
        self.text: str | None = None
        self.info: dict = {}
        self.values: dict = {}
        self.dirty: dict[str, float] = {}       # id -> moment du changement (pas encore ecrit)
        self.known: dict[str, str] = {}         # id -> valeur lue dans le fichier
        self.unparsed: list[str] = []
        self.conflicts: list[str] = []
        self.injection = ""
        self.status = ""
        self.writes = 0
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(lambda _p: self._disk_timer.start())
        self._disk_timer = QTimer(self)
        self._disk_timer.setSingleShot(True)
        self._disk_timer.setInterval(120)
        self._disk_timer.timeout.connect(self.check_disk)
        self._write_timer = QTimer(self)
        self._write_timer.setSingleShot(True)
        self._write_timer.setInterval(WRITE_DELAY_MS)
        self._write_timer.timeout.connect(self._write_when_released)

    # -- reglages -> fichier -------------------------------------------------------------------------------------
    def update(self, values: dict, changed=None):
        """Reglages appliques (apercu en direct compris). Seules les declarations des reglages CHANGES deviennent a
        ecrire ; apercu dans la page aussitot, ecriture regroupee ensuite."""
        values = dict(values or {})
        path = style.user_css(values)[0] if self.enabled else None
        if path != self.path:
            self.flush()
            self.values = values
            self._retarget(path)
            return
        keys = SYNCED_KEYS if changed is None else SYNCED_KEYS.intersection(changed)
        diff = [k for k in keys if values.get(k) != self.values.get(k)]
        self.values = values
        if not diff or self.path is None or self.text is None:
            return
        now = time.monotonic()
        for key in diff:
            for decl in KEY_INDEX[key]:
                self.dirty[decl.id] = now
        self._refresh_injection()
        self._write_timer.start()

    def ensure_table_cell_background_css(self):
        """Ecrit dans la feuille partagee le clipping necessaire aux fonds de cellule marques dans les notes."""
        if self.path is None or self.text is None:
            return False
        now = time.monotonic()
        for decl_id in ("table.marked_cell_bg", "table.marked_cell_padding"):
            self.dirty[decl_id] = now
        self._refresh_injection()
        self._write_timer.start()
        return True

    def _pending(self) -> dict:
        out = style.variables(self.values)
        return {decl_id: BY_ID[decl_id].fwd(out, self.values) for decl_id in self.dirty}

    def _refresh_injection(self):
        text = self.text
        if text is not None and self.dirty:
            try:
                text = patch(text, self._pending())
            except ValueError:
                pass
        block = block_text(text) if text is not None else ""
        css = f"@layer md-user {{\n{block}\n}}\n" if block.strip() else ""
        if css != self.injection:
            self.injection = css
            self.injectionChanged.emit(css)

    def _write_when_released(self):
        # Curseur encore tenu (glisser un curseur) : on attend le relachement.
        if QApplication.mouseButtons() != Qt.NoButton:
            self._write_timer.start(150)
            return
        self.flush()

    def flush(self) -> bool:
        """Ecrit maintenant ce qui attend (fermeture, changement de feuille…). Faux en cas d'echec."""
        self._write_timer.stop()
        if not self.dirty or self.path is None:
            return True
        try:
            disk, info = markdown_preview.read_note(self.path)
        except OSError as exc:
            return self._retry(f"Feuille illisible ({exc.__class__.__name__}) : rien n'est écrit.")
        if disk != self.text:                                  # modifiee entre-temps : ses valeurs d'abord
            self._absorb(disk, info)
        pending = self._pending()
        try:
            new = patch(self.text, pending)
        except ValueError as exc:
            self._set_status(f"Feuille non modifiée : {exc}.")
            return False
        try:
            if new != self.text:
                markdown_preview.write_note(self.path, new, self.info)
                self.writes += 1
        except OSError as exc:
            return self._retry(f"Écriture impossible ({exc.__class__.__name__}) : la feuille n'est pas modifiée.")
        self._retries = 0
        self.text = new
        self.known = read_block(new)
        self.dirty.clear()
        self._watch()
        conflict = f" ; conflit : {len(self.conflicts)} valeur(s) gardée(s) de Pipeline Browser" if self.conflicts else ""
        self.conflicts = []
        self._set_status(f"Synchronisé avec « {self.path.name} » à {time.strftime('%H:%M:%S')}{conflict}.")
        return True

    # -- fichier -> reglages -------------------------------------------------------------------------------------
    def _retarget(self, path: Path | None):
        self._unwatch()
        self.path, self.text, self.known, self.dirty, self.unparsed = path, None, {}, {}, []
        if path is None:
            self._set_status("" if not self.enabled else "Aucune feuille partagée.")
            self._refresh_injection()
            return
        try:
            text, info = markdown_preview.read_note(path)
        except OSError as exc:
            self.path = None
            self._set_status(f"Feuille illisible ({exc.__class__.__name__}).")
            self._refresh_injection()
            return
        self.text, self.info = text, info
        self._absorb(text, info, initial=True)
        self._watch()
        self._refresh_injection()

    def check_disk(self):
        """Fichier signale modifie : relu ; ses valeurs reprises ; la page recharge la feuille."""
        if self.path is None:
            return
        self._watch()                                          # remplace par un nouveau fichier : suivi repris
        try:
            text, info = markdown_preview.read_note(self.path)
        except OSError:
            return
        if text == self.text:
            self.info["mtime_ns"] = info["mtime_ns"]
            return
        self._absorb(text, info)
        self._refresh_injection()
        self.fileChanged.emit()

    def _absorb(self, text: str, info: dict, initial: bool = False):
        """Texte du fichier -> etat : valeurs reprises dans les reglages (sauf celles changees ici et pas encore
        ecrites : conflit, Pipeline Browser gagne), valeurs non interpretables notees."""
        found = read_block(text)
        for decl_id, css in found.items():
            if decl_id in self.dirty and self.known.get(decl_id) != css and not initial:
                self.conflicts.append(decl_id)
        external = {i: css for i, css in found.items() if i not in self.dirty}
        updates, self.unparsed = interpret(external, self.values)
        self.text, self.info, self.known = text, info, found
        if updates:
            self.values.update(updates)
            # Les autres declarations DEJA dans le bloc pour les memes reglages (lecture / edition) suivent.
            out, now = style.variables(self.values), time.monotonic()
            for key in updates:
                for decl in KEY_INDEX.get(key, ()):
                    value = decl.fwd(out, self.values)
                    if decl.id in found and value is not None and not self._same(decl, found[decl.id], value):
                        self.dirty.setdefault(decl.id, now)
            hook = HOOKS.get("external")
            if hook is not None:
                hook(dict(updates))
            self._write_timer.start()
        note = f" ; {len(self.unparsed)} valeur(s) gardée(s) telles quelles (non interprétables)" if self.unparsed else ""
        self._set_status(f"Feuille partagée « {self.path.name} » lue{note}." if self.path else "")

    def _retry(self, message: str) -> bool:
        """Fichier tenu ouvert par un autre programme (Obsidian qui le relit, synchronisation…) : Windows refuse
        alors de le remplacer un court instant. Nouvel essai bientot ; le message seulement apres ~3 s d'echecs."""
        self._retries = getattr(self, "_retries", 0) + 1
        if self._retries <= 10:
            self._write_timer.start(300)
        else:
            self._retries = 0
            self._set_status(message)
        return False

    def _same(self, decl: Decl, written: str, value: str) -> bool:
        """La valeur ecrite donne deja les reglages (meme sous une autre forme : rgb(), raccourci…) : on la garde
        telle que l'utilisateur l'a ecrite."""
        if _norm_value(written) == _norm_value(value):
            return True
        parsed = decl.parse(written, self.values) if decl.parse is not None else None
        return parsed is not None and all(self.values.get(k) == v for k, v in parsed.items())

    # -- divers --------------------------------------------------------------------------------------------------
    def _watch(self):
        if self.path is not None and str(self.path) not in self._watcher.files() and self.path.exists():
            self._watcher.addPath(str(self.path))

    def _unwatch(self):
        files = self._watcher.files()
        if files:
            self._watcher.removePaths(files)

    def _set_status(self, text: str):
        if text != self.status:
            self.status = text
            self.statusChanged.emit(text)


_ENGINE: CssSync | None = None


def engine() -> CssSync:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = CssSync()
    return _ENGINE


def current_injection() -> str:
    """Bloc gere tel que montre (avec les changements pas encore ecrits) : pour l'apercu de l'inspecteur."""
    return _ENGINE.injection if _ENGINE is not None else ""
