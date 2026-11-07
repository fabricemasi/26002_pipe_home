"""Module CAD du board : ATTRIBUTS de bloc — DEFINITION D'ATTRIBUT (ATTDEF / ATT), MODIFIER LES ATTRIBUTS (ATTEDIT /
ATE / EATTEDIT / DDATTE), AFFICHAGE DES ATTRIBUTS (ATTDISP) ; donnees dans `cad_attrib`. INSERER demande les valeurs
(`cad_commands_blocks.InsertCommand`). Inscrites dans le REGISTRE de `cad_commands` a l'import (`register`)."""
from __future__ import annotations

from . import cad_attrib, cad_block
from .cad_commands import Command, Prompt, TextCommand

MODE_OPTIONS = [("invisible", "Invisible", ("I", "INVISIBLE")), ("constant", "Constant", ("C", "CONSTANT")),
                ("go", "Continuer", ("O", "CONTINUER", "GO"))]


class AttdefCommand(TextCommand):
    """DEFINITION D'ATTRIBUT (ATTDEF / ATT, comme -ATTDEF d'AutoCAD) : modes (Invisible / Constant, Entree =
    continuer), etiquette, question, valeur par defaut, puis point d'insertion (ou Justifier), hauteur, rotation comme
    TEXTE. Le texte cree affiche l'etiquette ; pris dans un BLOC, il affiche la valeur de chaque reference."""

    NAME = "ATTDEF"
    LABEL = "Définition d'attribut"
    TEXT = "Définition d'attribut"

    def start(self):
        super().start()
        self.modes = {"invisible": False, "constant": False}
        self.stage = "modes"                    # modes | tag | prompt | default | (puis TEXTE)
        self.attdef = {}

    def prompt(self):
        if self.stage == "modes":
            on = [k for k, v in self.modes.items() if v]
            state = ", ".join({"invisible": "invisible", "constant": "constant"}[k] for k in on) or "normal"
            return Prompt(f"Modes de l'attribut ({state}) : Entrée pour continuer", MODE_OPTIONS, "point")
        if self.stage == "tag":
            return Prompt("Etiquette de l'attribut", [], "text")
        if self.stage == "prompt":
            return Prompt("Question de l'attribut", [], "text", None, self.attdef["tag"])
        if self.stage == "default":
            label = "Valeur de l'attribut" if self.modes["constant"] else "Valeur par défaut de l'attribut"
            return Prompt(label, [], "text")
        return super().prompt()

    def typed(self, text: str):
        if self.stage == "done":
            super().typed(text)

    def keyword(self, key):
        if self.stage == "modes":
            if key == "go":
                self.stage = "tag"
            elif key in self.modes:
                self.modes[key] = not self.modes[key]
            return
        super().keyword(key)

    def point(self, p):
        if self.stage == "modes":
            self.stage = "tag"
            return
        if self.stage == "done":
            super().point(p)

    def enter(self):
        if self.stage == "modes":
            self.stage = "tag"
            return
        super().enter()

    def click(self, p, raw: str):
        if self.stage in ("tag", "prompt", "default"):
            self.text(raw)
            return
        super().click(p, raw)

    def text(self, raw: str):
        if self.stage == "tag":
            tag = cad_attrib.clean_tag(raw)
            if not tag:
                self.ctx.message("Etiquette vide (sans espace ni ! \" ' < > / \\ : ; ? * | , = `).", error=True)
                return
            self.attdef = {"tag": tag, **self.modes}
            self.stage = "default" if self.modes["constant"] else "prompt"
            return
        if self.stage == "prompt":
            self.attdef["prompt"] = raw.strip() or self.attdef["tag"]
            self.stage = "default"
            return
        if self.stage == "default":
            self.attdef["default"] = raw.strip()
            if self.modes["constant"] and not self.attdef["default"]:
                self.ctx.message("Un attribut constant doit avoir une valeur.", error=True)
                return
            self.stage = "done"
            return
        super().text(raw)

    def _new_line(self, pos):
        """Point, hauteur et rotation donnes : la definition est creee (une etape d'annulation)."""
        style = self.ctx.text_style()
        item = self.ctx.create_entity("cad_text", {
            "pos": [pos[0], pos[1]], "text": self.attdef["tag"], "height": self.height, "rot": self.rot,
            "justify": self.justify, "font": style["font"], "spacing": style["spacing"], "mtext": False,
            "attdef": cad_attrib.clean_attdef(self.attdef)})
        self.ctx.commit_created([item], f"Attribut {self.attdef['tag']}")
        self.finish()


class AttEditCommand(Command):
    """MODIFIER LES ATTRIBUTS (ATTEDIT / ATE / EATTEDIT / DDATTE) : une reference de bloc (la selection si elle en a
    une), puis chaque attribut a son tour (Entree = valeur gardee) ; une etape d'annulation."""

    NAME = "ATTEDIT"
    LABEL = "Modifier les attributs"
    IMMEDIATE_PICK = True

    def start(self):
        self.item = None
        self.todo = []
        self.values = {}
        refs = [i for i in self.ctx.selection() if i.kind == "cad_insert"]
        if len(refs) == 1:
            self._take(refs[0])

    def _definition(self, item):
        return cad_block.blocks(self.ctx.cad_page()).get(str(item.data.get("block") or ""))

    def _take(self, item):
        if item.locked():
            self.ctx.message("Référence verrouillée (ou sur un calque verrouillé) : non modifiable.", error=True)
            return
        found = cad_attrib.asked(self._definition(item))
        if not found:
            self.ctx.message(f"Le bloc « {item.data.get('block')} » n'a pas d'attribut modifiable.", error=True)
            return
        self.item = item
        self.todo = list(found)
        self.values = dict(cad_attrib.clean_attribs(item.data.get("attribs")))
        self.ctx.scene.clearSelection()

    def prompt(self):
        if self.item is None:
            return Prompt("Choisissez une référence de bloc", [], "select")
        attdef = self.todo[0]
        current = self.values.get(attdef["tag"], attdef["default"])
        return Prompt(f"{attdef['prompt']} ({attdef['tag']})", [], "text", None, current)

    def picked(self, items):
        refs = [i for i in items if i.kind == "cad_insert"]
        if not refs:
            self.ctx.message("Ce n'est pas une référence de bloc.", error=True)
            return
        self._take(refs[0])

    def selection_done(self, items):
        if self.item is None:
            if items:
                self.picked(items)
            else:
                self.finish()

    def typed(self, text: str):
        pass

    def click(self, p, raw: str):
        if self.item is not None:
            self.text(raw)

    def text(self, raw: str):
        if self.item is None:
            return
        attdef = self.todo.pop(0)
        if raw.strip():
            self.values[attdef["tag"]] = raw.strip()
        else:
            self.values.setdefault(attdef["tag"], attdef["default"])
        if not self.todo:
            self._apply()

    def cancel(self):
        if self.item is not None and len(self.values):
            self._apply()
        else:
            self.finish()

    def _apply(self):
        item = self.item
        before = self.ctx.snapshot_items([item])
        self.ctx.set_entity_values(item, {"attribs": cad_attrib.clean_attribs(self.values)})
        self.ctx.push_change(before, [item], "Modifier les attributs")
        self.ctx.message(f"Attributs de « {item.data.get('block')} » modifiés.")
        self.finish()


NEW_ENTRIES = (
    ("ATTDEF", "Définition d'attribut", ("ATT", "-ATTDEF", "DDATTDEF", "ATTDEFINIR", "-ATTDEFINIR"), AttdefCommand),
    ("ATTEDIT", "Modifier les attributs", ("ATE", "-ATTEDIT", "EATTEDIT", "DDATTE", "ATTEDITER", "ATTMODIF"),
     AttEditCommand),
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
