"""Module CAD du board : BLOCS — BLOC (BLOCK / B), INSERER (INSERT / I), et DECOMPOSER une reference (`exploded_insert`,
branche dans `cad_commands.exploded`) ; definitions et geometrie dans `cad_block`. Inscrites dans le REGISTRE de
`cad_commands` a l'import (`register`)."""
from __future__ import annotations

import copy

from . import cad_attrib, cad_block, cad_model, cad_shapes
from . import cad_geometry as geo
from .cad_commands import Command, Prompt

DROP_KEYS = ("id", "type", "x", "y", "z", "locked", "link", "rotation")


def entity_record(item) -> dict:
    """Entite du board -> entite de definition de bloc (document, sans identite ni place Qt)."""
    data = item.to_dict()
    data["type"] = item.kind
    for key in ("id", "x", "y", "z", "locked", "link"):
        data.pop(key, None)
    return data


def exploded_insert(item, cad: dict) -> list:
    """[(type, champs, None)] des entites qui remplacent une reference (UN niveau, comme AutoCAD : les blocs
    imbriques restent des references) ; calque 0 et PARBLOC des entites du bloc -> ceux de la reference (meme dessin
    qu'avant, `cad_block.inherit`)."""
    data = item.to_dict()
    definition = cad_block.blocks(cad).get(str(data.get("block") or ""))
    if definition is None:
        return []
    base = definition.get("base") or [0.0, 0.0]
    hidden = cad_block.hidden_of(definition, data)          # etat de visibilite : ce qui est montre seulement
    out = []
    for index, entity in enumerate(definition.get("items") or []):
        if index in hidden:
            continue
        kind = entity.get("type")
        if kind == "cad_text" and entity.get("attdef"):     # attribut : la valeur de la reference (texte ordinaire)
            entity = cad_attrib.shown(entity, data)
            if entity is None:
                continue
            entity = {k: v for k, v in entity.items() if k != "attdef"}
        if kind == "cad_insert":
            placed = cad_block.nested(entity, base, data)
        elif kind in cad_shapes.CAD_TYPES:
            placed = cad_block.placed(kind, entity, base, data)
        else:
            continue
        values = {k: copy.deepcopy(v) for k, v in placed.items() if k not in DROP_KEYS}
        if values.get("layer") in (None, cad_model.LAYER0):          # calque 0 -> celui de la reference
            values["layer"] = data.get("layer", cad_model.LAYER0)
        for key in ("color", "lineweight"):                          # PARBLOC -> celle de la reference
            if values.get(key) == cad_model.BYBLOCK:
                values[key] = data.get(key, cad_model.BYLAYER)
        out.append((kind, values, None))
    return out


class BlockCommand(Command):
    """BLOC (BLOCK / B) : le nom (une definition du meme nom est REDEFINIE, ses references suivent), le point de
    base, puis les objets (la selection courante si elle existe) ; option Conserver / Convertir en bloc (par defaut :
    les objets sont remplaces par une reference, comme « Convertir en bloc » d'AutoCAD) ; une etape d'annulation."""

    NAME = "BLOCK"
    LABEL = "Créer un bloc"

    def start(self):
        self.name = None
        self.base = None
        self.keep = False
        self.items = [i for i in self.ctx.selection() if not i.locked()]

    def prompt(self):
        if self.name is None:
            return Prompt("Nom du bloc", [], "text")
        if self.base is None:
            return Prompt("Spécifiez le point de base", [("keep", "Conserver les objets", ("C", "CONSERVER", "R",
                                                                                         "RETAIN"))], "point")
        return Prompt("Choix des objets", [], "select")

    def typed(self, text: str):
        pass

    def text(self, raw: str):
        name = cad_block.clean_name(raw)
        if not name:
            self.ctx.message("Nom de bloc vide (caractères < > / \\ \" : ; ? * | , = ` interdits).", error=True)
            return
        self.name = name
        if name in cad_block.blocks(self.ctx.cad_page()):
            self.ctx.message(f"Le bloc « {name} » existe : il sera redéfini (ses références suivent).")

    def click(self, p, raw: str):
        if raw.strip():
            self.text(raw)

    def keyword(self, key):
        if key == "keep":
            self.keep = True
            self.ctx.message("Les objets d'origine seront conservés.")

    def point(self, p):
        if self.name is None:
            return
        self.base = (float(p[0]), float(p[1]))
        if self.items:
            self._make(self.items)
        else:
            self.ctx.begin_object_selection()

    def selection_done(self, items):
        items = [i for i in items if not i.locked()]
        if not items:
            self.ctx.message("Aucun objet choisi : bloc non créé.", error=True)
            self.finish()
            return
        self._make(items)

    def _make(self, items):
        cad = cad_model.copy_cad(self.ctx.cad_page())
        if any(i.kind == "cad_insert" and cad_block.uses(cad, self.name, str(i.data.get("block") or ""))
               for i in items):
            self.ctx.message("Un bloc ne peut pas se contenir lui-même.", error=True)
            self.finish()
            return
        cad.setdefault("blocks", {})
        cad["blocks"] = dict(cad["blocks"])
        cad["blocks"][self.name] = cad_block.definition_from([entity_record(i) for i in items], self.base)
        scene = self.ctx.scene
        from fm_board.scene import PAGE
        scene.commit_live()
        refs = [i for i in self.ctx.cad_items() if i.kind == "cad_insert" and i.data.get("block") == self.name]
        gone = [] if self.keep else items
        before = scene.snapshot([PAGE] + [i.item_id for i in gone])
        scene.set_page({"cad": cad}, record=False)
        made = []
        if not self.keep:
            for item in gone:
                scene._remove(item.item_id)
            made.append(self.ctx.create_entity("cad_insert", {"block": self.name, "pos": list(self.base),
                                                              "scale": 1.0, "rot": 0.0, "mirror": False}))
        before.update({i.item_id: None for i in made})
        scene.push(before, scene.snapshot(list(before)), f"Bloc « {self.name} »")
        for ref in refs:
            ref.refresh_block()
        self.ctx.tool_memory["insert_block"] = self.name
        self.ctx.message(f"Bloc « {self.name} » : {len(items)} objet(s).")
        self.finish()


class InsertCommand(Command):
    """INSERER (INSERT / I) : le nom du bloc (Entree = le dernier ; « ? » = la liste), le point d'insertion, l'echelle
    (Entree = 1) puis la rotation (Entree = 0) ; options Echelle / Rotation au point d'insertion ; puis la valeur de
    chaque attribut du bloc (Entree = la valeur par defaut, cad_attrib). Une reference par commande."""

    NAME = "INSERT"
    LABEL = "Insérer un bloc"

    def start(self):
        self.name = None
        self.pos = None
        self.scale = 1.0
        self.rot = 0.0
        self.stage = "name"                 # name | point | scale | rot | attr
        self.asked = []                     # attributs encore a demander
        self.values = {}

    def _default(self) -> str:
        found = self.ctx.tool_memory.get("insert_block")
        names = cad_block.blocks(self.ctx.cad_page())
        return found if found in names else (sorted(names)[0] if names else "")

    def prompt(self):
        if self.stage == "name":
            return Prompt(f"Nom du bloc (« ? » = la liste) <{self._default()}>", [], "text")
        if self.stage == "attr":
            attdef = self.asked[0]
            return Prompt(f"{attdef['prompt']} ({attdef['tag']})", [], "text", None, attdef["default"])
        if self.stage == "point":
            return Prompt("Spécifiez le point d'insertion", [("scale", "Echelle", ("E", "ECHELLE", "S", "SCALE")),
                                                              ("rot", "Rotation", ("R", "ROTATION"))], "point")
        if self.stage in ("scale", "pre_scale"):
            return Prompt("Spécifiez le facteur d'échelle", [], "point", self.pos, f"{self.scale:g}", value="count")
        return Prompt("Spécifiez l'angle de rotation", [], "point", self.pos, f"{self.rot:g}", value="angle")

    def typed(self, text: str):
        pass

    def text(self, raw: str):
        if self.stage == "attr":
            attdef = self.asked.pop(0)
            self.values[attdef["tag"]] = raw.strip() or attdef["default"]
            if not self.asked:
                self._create()
            return
        names = cad_block.blocks(self.ctx.cad_page())
        word = raw.strip() or self._default()
        if word == "?":
            self.ctx.message("Blocs : " + (", ".join(sorted(names)) if names else "aucun"))
            return
        if word not in names:
            match = [n for n in names if n.lower() == word.lower()]
            if not match:
                self.ctx.message(f"Bloc « {word} » introuvable." + (" Blocs : " + ", ".join(sorted(names))
                                                                     if names else " Aucun bloc dans ce dessin."),
                                 error=True)
                return
            word = match[0]
        self.name = word
        self.ctx.tool_memory["insert_block"] = word
        self.stage = "point"

    def click(self, p, raw: str):
        self.text(raw)

    def keyword(self, key):
        if self.stage == "point" and key in ("scale", "rot"):
            self.stage = "pre_" + key

    def value(self, number):
        if self.stage in ("scale", "pre_scale"):
            if number <= 0:
                self.ctx.message("L'échelle doit être positive.", error=True)
                return
            self.scale = number
            self.stage = "point" if self.stage == "pre_scale" else "rot"
        elif self.stage in ("rot", "pre_rot"):
            self.rot = number % 360.0
            if self.stage == "pre_rot":
                self.stage = "point"
            else:
                self._make()

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.stage == "point":
            self.pos = p
            self.stage = "scale"
        elif self.stage == "scale":
            self.value(geo.distance(self.pos, p) / max(geo.EPS, self.ctx.unit()))
        elif self.stage == "rot":
            self.value(geo.angle_deg(self.pos, p))

    def enter(self):
        if self.stage == "scale":
            self.stage = "rot"
        elif self.stage == "rot":
            self._make()
        elif self.stage == "name":
            self.text("")
        else:
            self.finish()

    def _data(self, pos) -> dict:
        definition = cad_block.blocks(self.ctx.cad_page()).get(self.name)
        return {"block": self.name, "pos": [pos[0], pos[1]], "scale": self.scale, "rot": self.rot, "mirror": False,
                "attribs": cad_attrib.values_for(definition, self.values)}

    def _make(self):
        self.asked = cad_attrib.asked(cad_block.blocks(self.ctx.cad_page()).get(self.name))
        if self.asked:
            self.stage = "attr"                 # les valeurs des attributs d'abord
            return
        self._create()

    def _create(self):
        item = self.ctx.create_entity("cad_insert", self._data(self.pos))
        self.ctx.commit_created([item], f"Insérer « {self.name} »")
        self.finish()

    def ghosts(self, p):
        if self.name is None or self.stage == "name":
            return []
        pos = self.pos if self.pos is not None and self.stage != "point" else (float(p[0]), float(p[1]))
        data = self._data(pos)
        if self.stage == "rot" and self.pos is not None and geo.distance(self.pos, p) > geo.EPS:
            data["rot"] = geo.angle_deg(self.pos, p)
        found = cad_block.parts(self.ctx.cad_page(), data)
        return cad_shapes.display_segments(found["prims"], self.ctx.tess_tol())

    def preview(self, p):
        if self.pos is not None and self.stage in ("scale", "rot"):
            return [("rubber", self.pos, p)]
        return []


NEW_ENTRIES = (
    ("BLOCK", "Créer un bloc", ("B", "BLOC", "BMAKE"), BlockCommand),
    ("INSERT", "Insérer un bloc", ("I", "INSERER", "INSÉRER", "DDINSERT"), InsertCommand),
)


def register(registry, entry_class, by_word):
    for name, label, aliases, factory in NEW_ENTRIES:
        if any(e.name == name for e in registry):
            continue                                    # deja inscrite
        entry = entry_class(name, label, aliases, factory)
        registry.append(entry)
        for word in (name, *aliases):
            by_word.setdefault(word.upper(), entry)


def _self_register():
    """Importe AVANT `cad_commands` : `cad_commands` n'a pas pu l'inscrire (fichier encore incomplet), il le fait ici."""
    from . import cad_commands as _cc
    if hasattr(_cc, "_BY_WORD"):
        register(_cc.REGISTRY, _cc.Entry, _cc._BY_WORD)


_self_register()
