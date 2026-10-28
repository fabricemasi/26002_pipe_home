"""Presse-papiers avec les AUTRES logiciels, Miro en tete (texte, tableaux, images), sans reseau.

Ce que fait Miro (etude d'octobre 2026, aide officielle + forum Miro ; non verifie dans Miro faute de compte) :
- copier dans Miro place du TEXTE BRUT (les textes des post-it, formes, textes, cadres...) et un HTML qui
  contient une balise `data-meta` avec les donnees internes de Miro, ENCODEES et NON DOCUMENTEES (format
  susceptible de changer) suivie du texte des objets ; « copier en image » place un PNG ;
- coller dans Miro : texte brut -> un texte (un post-it pour un texte court) ; un TABLEAU (cellules venues
  d'Excel, HTML `<table>`) -> Miro propose « tableau » ou « post-it » ; une image -> une image.

Donc, de MRO vers Miro : texte brut (une ligne par objet) + HTML `<table>` (une cellule par objet a texte :
la voie documentee pour obtenir des post-it MODIFIABLES dans Miro) ; « Copier en image » a part (PNG, rendu
APLATI). De Miro vers MRO : on ne decode PAS `data-meta` (non documente) ; le HTML de Miro est lu pour son TEXTE,
un post-it par objet ; un tableau HTML -> un post-it par cellule ; une image -> une image ; sinon le texte brut.
Le format interne de MRO (`application/x-pipeline-board`) reste prioritaire entre deux boards."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

MIRO_MARKER = re.compile(r"data-meta=|miro-data", re.I)


def items_text(items) -> list[str]:
    """Textes des elements (dans l'ordre de lecture : haut en bas, gauche a droite)."""
    rows = []
    for item in sorted(items, key=lambda i: (round(i.scene_rect().top() / 20), i.scene_rect().left())):
        key = getattr(item, "TEXT_KEY", None)
        if key and item.text_item is not None:
            text = item.text_item.toPlainText().strip()
            if text:
                rows.append(text)
    return rows


def table_html(texts: list[str]) -> str:
    """HTML d'un tableau d'une colonne (comme une plage de cellules d'Excel)."""
    cells = "".join(f"<tr><td>{html.escape(t).replace(chr(10), '<br>')}</td></tr>" for t in texts)
    return f'<meta charset="utf-8"><table>{cells}</table>'


class _Blocks(HTMLParser):
    """Textes d'un HTML : cellules d'un tableau, ou blocs de premier niveau (div / p)."""

    BLOCKS = {"div", "p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells: list[str] = []
        self.blocks: list[str] = []
        self._cell = None
        self._depth = 0
        self._block = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self._skip += 1
        elif tag in ("td", "th"):
            self._cell = []
        elif tag == "br":
            for target in (self._cell, self._block):
                if target is not None:
                    target.append("\n")
        if tag in self.BLOCKS and tag not in ("td", "th"):
            self._depth += 1
            if self._depth == 1:
                self._block = []
        elif tag in ("p", "div") and self._block is not None:
            self._block.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None:
            self.cells.append("".join(self._cell).strip())
            self._cell = None
        if tag in self.BLOCKS and tag not in ("td", "th") and self._depth:
            self._depth -= 1
            if self._depth == 0 and self._block is not None:
                text = re.sub(r"\n{3,}", "\n\n", "".join(self._block)).strip()
                if text:
                    self.blocks.append(text)
                self._block = None

    def handle_data(self, data):
        if self._skip:
            return
        for target in (self._cell, self._block):
            if target is not None:
                target.append(data)


def html_texts(markup: str) -> tuple[str, list[str]]:
    """("table" | "miro" | "html", textes) d'un HTML colle."""
    parser = _Blocks()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:                                      # noqa: BLE001 - HTML abime : on se rabat sur le texte
        return "html", []
    if parser.cells:
        return "table", [c for c in parser.cells if c]
    kind = "miro" if MIRO_MARKER.search(markup) else "html"
    return kind, parser.blocks
