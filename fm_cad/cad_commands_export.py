"""Module CAD du board : EXPORTER la SELECTION (clic droit > Exporter, demande de l'utilisateur, 2026-11-08).

Quatre sorties : vers Photoshop en pixels (PNG transparent ouvert dans Photoshop), vers Photoshop en vectoriel (PDF
ouvert dans Photoshop), fichier SVG, fichier PNG. Toujours les SEULES entites selectionnees (rien sans selection).
Deroule : premier coin de la zone d'export (Entree = l'emprise exacte de la selection), coin oppose, largeur en px
(Entree = 512), hauteur en px (Entree = proportionnelle a la zone). L'image couvre EXACTEMENT la zone : ni marge, ni
cadre, fond transparent. Rendu : `cad_photoshop.render_zone` / `write_zone_vector`. Inscrites dans le REGISTRE de
`cad_commands` a l'import (`register`)."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from .cad_commands import Command, Prompt

DEFAULT_WIDTH = 512
MAX_SIDE = 16000

TARGETS = {          # cle -> (libelle du menu, extension)
    "ps_pixel": ("Vers Photoshop en pixels", ".png"),
    "ps_vector": ("Vers Photoshop en vectoriel", ".pdf"),
    "svg": ("Fichier SVG…", ".svg"),
    "png": ("Fichier PNG…", ".png"),
}


def default_height(zone, width: int) -> int:
    """Hauteur (px) proportionnelle a la zone [x0, y0, x1, y1] pour `width`."""
    w, h = zone[2] - zone[0], zone[3] - zone[1]
    return max(1, round(width * h / w)) if w > 0 else width


def parse_pixels(word: str) -> int | None:
    """« 512 », « 512px », « 512,0 » -> 512 ; illisible ou hors 1..MAX_SIDE -> None."""
    word = word.strip().lower().removesuffix("px").strip().replace(",", ".")
    try:
        value = round(float(word))
    except ValueError:
        return None
    return value if 1 <= value <= MAX_SIDE else None


class ExportCommand(Command):
    TARGET = "png"
    REPEATABLE = False

    def start(self):
        self.items = list(self.ctx.selection())
        self.corner = self.zone = self.width = None
        if not self.items:
            self.ctx.message("Exporter : sélectionnez d'abord les éléments à exporter.", error=True)
            self.finish()

    def _extents(self) -> list:
        from .cad_plot_ui import drawing_extents
        return drawing_extents(self.items)

    def prompt(self):
        if self.zone is None and self.corner is None:
            return Prompt("Premier coin de la zone d'export", [], "point", None, "emprise de la sélection")
        if self.zone is None:
            return Prompt("Coin opposé de la zone d'export", [], "point", self.corner)
        if self.width is None:
            return Prompt("Largeur de l'image (px)", [], "text", None, str(DEFAULT_WIDTH))
        return Prompt("Hauteur de l'image (px)", [], "text", None, str(default_height(self.zone, self.width)))

    def typed(self, text: str):
        pass

    def click(self, p, raw: str):
        if raw.strip():
            self.text(raw)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.zone is not None:
            return
        if self.corner is None:
            self.corner = p
            return
        a = self.corner
        if abs(a[0] - p[0]) <= 1e-9 or abs(a[1] - p[1]) <= 1e-9:
            self.ctx.message("Zone vide : donnez un coin opposé distinct du premier.", error=True)
            return
        self.zone = [min(a[0], p[0]), min(a[1], p[1]), max(a[0], p[0]), max(a[1], p[1])]

    def enter(self):
        if self.zone is None and self.corner is None:
            x0, y0, x1, y1 = self._extents()
            if x1 - x0 <= 1e-9 or y1 - y0 <= 1e-9:
                self.ctx.message("Emprise de la sélection sans largeur ou sans hauteur : donnez deux coins.",
                                 error=True)
                return
            self.zone = [x0, y0, x1, y1]
        elif self.zone is None:
            return
        else:
            self.text("")

    def text(self, raw: str):
        word = raw.strip()
        if self.zone is None:
            if not word and self.corner is None:
                self.enter()
            return
        if self.width is None:
            value = parse_pixels(word) if word else DEFAULT_WIDTH
            if value is None:
                self.ctx.message(f"Largeur « {word} » illisible (1 à {MAX_SIDE} px).", error=True)
                return
            self.width = value
            return
        height = parse_pixels(word) if word else min(MAX_SIDE, default_height(self.zone, self.width))
        if height is None:
            self.ctx.message(f"Hauteur « {word} » illisible (1 à {MAX_SIDE} px).", error=True)
            return
        self._export(self.width, height)
        self.finish()

    def preview(self, p):
        if self.zone is None and self.corner is not None:
            a, b = self.corner, p
        elif self.zone is not None:
            a, b = (self.zone[0], self.zone[1]), (self.zone[2], self.zone[3])
        else:
            return []
        c, d = (b[0], a[1]), (a[0], b[1])
        return [("rubber", a, c), ("rubber", c, b), ("rubber", b, d), ("rubber", d, a)]

    # -- sortie --
    def _export(self, width: int, height: int):
        from . import cad_photoshop
        target = self.TARGET
        what = f"{len(self.items)} élément(s), {width} x {height} px"
        try:
            if target in ("svg", "png"):
                label = "Image SVG vectorielle" if target == "svg" else "Image PNG transparente"
                path = cad_photoshop._ask_path(self.ctx, "Exporter la sélection", ((label, TARGETS[target][1]),))
                if path is None:
                    self.ctx.message("Export annulé.")
                    return
            else:
                folder = Path(tempfile.gettempdir()) / "pipeline_photoshop"
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f"{cad_photoshop._stem(self.ctx)}_{time.strftime('%Y%m%d_%H%M%S')}{TARGETS[target][1]}"
            if target in ("svg", "ps_vector"):
                cad_photoshop.write_zone_vector(self.ctx.scene, self.items, self.zone, width, height, path)
            else:
                image = cad_photoshop.render_zone(self.ctx.scene, self.items, self.zone, width, height)
                if not image.save(str(path)):
                    raise OSError(f"Impossible d'écrire {path}")
            if target.startswith("ps_"):
                if cad_photoshop.open_in_photoshop(path):
                    self.ctx.message(f"{what} envoyé(s) vers Photoshop.")
                else:
                    self.ctx.message("Photoshop introuvable : fichier ouvert avec l'application associée.", error=True)
            else:
                self.ctx.message(f"{what} exporté(s) : {path.name}")
        except Exception as exc:                            # noqa: BLE001 - message a l'utilisateur
            self.ctx.message(f"Export impossible : {exc}", error=True)


def _command(key: str, name: str):
    return type(f"Export_{key}", (ExportCommand,), {"TARGET": key, "NAME": name, "LABEL": TARGETS[key][0]})


EXPORT_NAMES = {"ps_pixel": "EXPORTPSPIX", "ps_vector": "EXPORTPSVECT", "svg": "EXPORTSVGZONE", "png": "EXPORTPNGZONE"}

NEW_ENTRIES = (
    ("EXPORTPSPIX", "Exporter la sélection vers Photoshop en pixels", ("EXPPSPIX",), _command("ps_pixel", "EXPORTPSPIX")),
    ("EXPORTPSVECT", "Exporter la sélection vers Photoshop en vectoriel", ("EXPPSVECT",),
     _command("ps_vector", "EXPORTPSVECT")),
    ("EXPORTSVGZONE", "Exporter la sélection en fichier SVG", ("EXPSVG",), _command("svg", "EXPORTSVGZONE")),
    ("EXPORTPNGZONE", "Exporter la sélection en fichier PNG", ("EXPPNG",), _command("png", "EXPORTPNGZONE")),
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
