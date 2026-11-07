"""Module CAD du board : PRESENTATIONS et IMPRESSION — MISE EN PAGE (PAGESETUP / PRESENTATION / LAYOUT : creer,
regler, choisir, renommer, supprimer une presentation) et TRACEUP (PLOT / IMPRIMER : PDF vectoriel ou imprimante).
Donnees : `cad_plot` ; rendu : `cad_plot_ui`. Inscrites dans le REGISTRE de `cad_commands` a l'import (`register`)."""
from __future__ import annotations

from pathlib import Path

from . import cad_plot
from .cad_commands import Command, Prompt

SETUP_WORDS = {
    "N": "new", "NOUVEAU": "new", "NEW": "new",
    "P": "paper", "PAPIER": "paper", "PAPER": "paper",
    "O": "orient", "ORIENTATION": "orient",
    "E": "scale", "ECHELLE": "scale", "ÉCHELLE": "scale", "SCALE": "scale",
    "F": "window", "FENETRE": "window", "FENÊTRE": "window", "WINDOW": "window",
    "T": "extents", "ETENDUE": "extents", "ÉTENDUE": "extents", "EXTENTS": "extents",
    "M": "margin", "MARGE": "margin", "MARGIN": "margin",
    "C": "center", "CENTRER": "center", "CENTER": "center",
    "R": "rename", "RENOMMER": "rename", "RENAME": "rename",
    "S": "delete", "SUPPRIMER": "delete", "DELETE": "delete",
    "?": "list", "L": "list", "LISTE": "list",
}


def describe(layout: dict) -> str:
    pw, ph = cad_plot.paper_size(layout)
    area = "fenêtre" if layout["area"] else "étendue"
    return (f"« {layout['name']} » : {layout['paper']} {'paysage' if layout['landscape'] else 'portrait'} "
            f"({pw:g} x {ph:g} mm), échelle {cad_plot.describe_scale(layout['scale'])}, zone {area}, "
            f"marge {layout['margin']:g} mm{', centrée' if layout['center'] else ''}")


class PageSetupCommand(Command):
    """MISE EN PAGE (PAGESETUP / PRESENTATION / LAYOUT) : la presentation courante (creee au besoin), puis des
    options a la suite (Entree = termine) : Nouveau, Papier (A4…A0, Letter, LxH en mm), Orientation, Echelle
    (« 1:100 », « ajuster »), Fenetre (deux coins), eTendue, Marge, Centrer, Renommer, Supprimer, ? (la liste), ou le
    nom d'une presentation pour la rendre courante. UNE etape d'annulation pour toute la commande."""

    NAME = "PAGESETUP"
    LABEL = "Mise en page"

    def start(self):
        self.stage = "menu"             # menu | new | paper | scale | margin | rename | corner1 | corner2
        self.corner = None
        self.cad = dict(self.ctx.cad_page())
        if cad_plot.current(self.cad) is None:
            self.cad = cad_plot.with_layout(self.cad, dict(cad_plot.DEFAULT, name=cad_plot.unique_name(self.cad)))
        self.changed = False
        self.ctx.message(describe(cad_plot.current(self.cad)))

    def _layout(self) -> dict:
        return cad_plot.current(self.cad)

    def _put(self, **values):
        layout = dict(self._layout(), **values)
        self.cad = cad_plot.with_layout(self.cad, layout)
        self.changed = True
        self.ctx.message(describe(cad_plot.current(self.cad)))

    def prompt(self):
        if self.stage == "new":
            return Prompt("Nom de la nouvelle présentation", [], "text", None, cad_plot.unique_name(self.cad))
        if self.stage == "paper":
            return Prompt("Papier (" + "/".join(cad_plot.PAPERS) + " ou LxH en mm)", [], "text", None,
                          self._layout()["paper"])
        if self.stage == "scale":
            return Prompt("Échelle (1:N, ou « ajuster »)", [], "text", None,
                          cad_plot.describe_scale(self._layout()["scale"]))
        if self.stage == "margin":
            return Prompt("Marge (mm)", [], "text", None, f"{self._layout()['margin']:g}")
        if self.stage == "rename":
            return Prompt(f"Nouveau nom de « {self._layout()['name']} »", [], "text")
        if self.stage == "corner1":
            return Prompt("Premier coin de la zone à imprimer", [], "point")
        if self.stage == "corner2":
            return Prompt("Coin opposé", [], "point", self.corner)
        return Prompt(f"Présentation « {self._layout()['name']} » : Nouveau / Papier / Orientation / Échelle / "
                      "Fenêtre / éTendue / Marge / Centrer / Renommer / Supprimer / ? (Entrée = terminé)", [], "text")

    def typed(self, text: str):
        pass

    def click(self, p, raw: str):
        if raw.strip():
            self.text(raw)

    def text(self, raw: str):
        word = raw.strip()
        stage, self.stage = self.stage, "menu"
        if stage == "new":
            name = word or cad_plot.unique_name(self.cad)
            if cad_plot.by_name(self.cad, name) is not None:
                self.ctx.message(f"La présentation « {name} » existe déjà.", error=True)
                return
            self.cad = cad_plot.with_layout(self.cad, dict(self._layout(), name=name))
            self.changed = True
            self.ctx.message(describe(cad_plot.current(self.cad)))
        elif stage == "paper":
            if word:
                value = next((k for k in cad_plot.PAPERS if k.lower() == word.lower()), None)
                value = value or cad_plot._custom_paper(word)
                if value == "A4" and word.upper() != "A4":
                    self.ctx.message(f"Papier « {word} » inconnu.", error=True)
                    return
                self._put(paper=value)
        elif stage == "scale":
            value = cad_plot.parse_scale(word) if word else self._layout()["scale"]
            if value is None:
                self.ctx.message(f"Échelle « {word} » illisible (1:100, ajuster).", error=True)
                return
            self._put(scale=value)
        elif stage == "margin":
            try:
                value = float(word.replace(",", ".")) if word else self._layout()["margin"]
            except ValueError:
                self.ctx.message(f"Marge « {word} » illisible.", error=True)
                return
            self._put(margin=value)
        elif stage == "rename":
            if word and cad_plot.by_name(self.cad, word) is None:
                old = self._layout()["name"]
                self.cad = cad_plot.with_layout(cad_plot.without_layout(self.cad, old), dict(self._layout(), name=word))
                self.changed = True
        else:
            self._menu(word)

    def _menu(self, word: str):
        if not word:
            self._done()
            return
        found = cad_plot.by_name(self.cad, word)
        if found is not None:
            self.cad = dict(self.cad, layout=found["name"])
            self.changed = True
            self.ctx.message(describe(found))
            return
        key = SETUP_WORDS.get(word.upper())
        if key in ("new", "paper", "scale", "margin", "rename"):
            self.stage = key
        elif key == "orient":
            self._put(landscape=not self._layout()["landscape"])
        elif key == "window":
            self.stage = "corner1"
        elif key == "extents":
            self._put(area=None)
        elif key == "center":
            self._put(center=not self._layout()["center"])
        elif key == "delete":
            name = self._layout()["name"]
            self.cad = cad_plot.without_layout(self.cad, name)
            self.changed = True
            self.ctx.message(f"Présentation « {name} » supprimée.")
            if cad_plot.current(self.cad) is None:
                self._done()
        elif key == "list":
            self.ctx.message(" ; ".join(describe(l) for l in cad_plot.layouts(self.cad)))
        else:
            self.ctx.message(f"« {word} » : option ou présentation inconnue.", error=True)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.stage == "corner1":
            self.corner = p
            self.stage = "corner2"
        elif self.stage == "corner2":
            a, b = self.corner, p
            if abs(a[0] - b[0]) > 1e-9 and abs(a[1] - b[1]) > 1e-9:
                self._put(area=[min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])])
            self.stage = "menu"

    def enter(self):
        if self.stage != "menu":
            self.stage = "menu"
        else:
            self._done()

    def cancel(self):
        self._done()

    def preview(self, p):
        if self.stage == "corner2" and self.corner is not None:
            a, b = self.corner, p
            c, d = (b[0], a[1]), (a[0], b[1])
            return [("rubber", a, c), ("rubber", c, b), ("rubber", b, d), ("rubber", d, a)]
        return []

    def ghosts(self, p):
        """Zone imprimee de la presentation courante (fenetre), en fantome."""
        layout = cad_plot.current(self.cad)
        if layout is None or not layout["area"] or self.stage == "corner2":
            return []
        x0, y0, x1, y1 = layout["area"]
        return [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]

    def _done(self):
        if self.changed:
            self.ctx.set_cad(self.cad, "Mise en page")
        self.finish()


class PlotCommand(Command):
    """TRACEUP (PLOT / IMPRIMER) : la presentation (Entree = la courante ; aucune = l'etendue ajustee sur un A4
    paysage), puis le fichier PDF (Entree = a cote du dessin) ou « imprimante » (boite d'impression du systeme)."""

    NAME = "PLOT"
    LABEL = "Imprimer"

    def start(self):
        self.layout = None

    def _default_layout(self) -> dict:
        return cad_plot.current(self.ctx.cad_page()) or dict(cad_plot.DEFAULT, name="Étendue")

    def _default_path(self) -> Path:
        pane = getattr(self.ctx, "pane", None)
        base = getattr(pane, "path", None) or getattr(pane, "source", None)
        folder = Path(base).parent if base else Path.home()
        stem = Path(base).stem if base else "dessin"
        return folder / f"{stem} - {self.layout['name']}.pdf"

    def prompt(self):
        if self.layout is None:
            return Prompt("Présentation à imprimer", [], "text", None, self._default_layout()["name"])
        return Prompt("Fichier PDF (ou « imprimante »)", [], "text", None, str(self._default_path()))

    def typed(self, text: str):
        pass

    def click(self, p, raw: str):
        if raw.strip():
            self.text(raw)

    def text(self, raw: str):
        word = raw.strip().strip('"')
        if self.layout is None:
            found = cad_plot.by_name(self.ctx.cad_page(), word) if word else self._default_layout()
            if found is None:
                names = ", ".join(l["name"] for l in cad_plot.layouts(self.ctx.cad_page())) or "aucune"
                self.ctx.message(f"Présentation « {word} » inconnue (présentations : {names}).", error=True)
                return
            self.layout = found
            return
        from . import cad_plot_ui
        extents = cad_plot_ui.drawing_extents(self.ctx.cad_items())
        frame = cad_plot.plot_frame(self.layout, extents)
        if not frame["fits"]:
            self.ctx.message("La zone dépasse la feuille à cette échelle : elle sera coupée.", error=True)
        if word.lower() in ("imprimante", "printer", "i"):
            done = cad_plot_ui.plot_printer(self.ctx.scene, self.layout, extents, self.ctx.view)
            self.ctx.message("Envoyé à l'imprimante." if done else "Impression annulée.")
        else:
            path = Path(word) if word else self._default_path()
            if path.suffix.lower() != ".pdf":
                path = path.with_suffix(".pdf")
            try:
                cad_plot_ui.plot_pdf(self.ctx.scene, self.layout, extents, path)
            except OSError as exc:
                self.ctx.message(f"PDF impossible : {exc}", error=True)
                return
            self.ctx.message(f"Imprimé dans {path} (échelle {cad_plot.describe_scale(frame['scale'])}).")
        self.finish()


NEW_ENTRIES = (
    ("PAGESETUP", "Mise en page", ("PRESENTATION", "PRÉSENTATION", "LAYOUT", "-LAYOUT", "MISEENPAGE", "MEP"),
     PageSetupCommand),
    ("PLOT", "Imprimer", ("TRACEUP", "IMPRIMER", "PRINT", "-PLOT"), PlotCommand),
)


def register(registry, entry_class, by_word):
    for name, label, aliases, factory in NEW_ENTRIES:
        if any(e.name == name for e in registry):
            continue
        entry = entry_class(name, label, aliases, factory)
        registry.append(entry)
        for word in (name, *aliases):
            by_word.setdefault(word.upper(), entry)


def _self_register():
    from . import cad_commands as _cc
    if hasattr(_cc, "_BY_WORD"):
        register(_cc.REGISTRY, _cc.Entry, _cc._BY_WORD)


_self_register()
