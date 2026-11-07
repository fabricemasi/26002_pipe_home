"""Module CAD du board : BLOCS DYNAMIQUES — ETATS DE VISIBILITE (ETATVIS / BVSTATE / VISIBILITE) : une reference de
bloc, puis le nom d'un etat (il est montre), ou Nouveau (copie de l'etat montre), Masquer (clic sur les objets du
bloc : masque / montre dans l'etat), Renommer, Supprimer, « ? » (la liste). Donnees : `cad_block.states`. Une etape
d'annulation par commande. Inscrite dans le REGISTRE de `cad_commands` a l'import (`register`)."""
from __future__ import annotations

from . import cad_block, cad_model, cad_shapes
from .cad_commands import Command, Prompt

PICK_PX = 8.0


def entity_prims(cad: dict, insert: dict, indices) -> list:
    """Primitives (document) des entites `indices` de la definition, posees par la reference (etat ignore)."""
    s = cad_block.style_of(insert)
    definition = cad_block.blocks(cad).get(s["block"])
    if definition is None:
        return []
    base = definition.get("base") or [0.0, 0.0]
    out = []
    items = definition.get("items") or []
    for index in sorted(indices):
        if not 0 <= index < len(items):
            continue
        entity = items[index]
        kind = entity.get("type")
        if kind == "cad_insert":
            out.extend(cad_block.parts(cad, cad_block.nested(entity, base, insert))["prims"])
        elif kind == "cad_text":
            from . import cad_text
            box = cad_text.layout(cad_block.placed(kind, entity, base, insert))["corners"]
            out.extend(("segment", tuple(box[i]), tuple(box[(i + 1) % 4])) for i in range(4))
        elif kind in cad_shapes.CAD_TYPES and kind != "cad_point":
            out.extend(cad_shapes.prims(kind, cad_block.placed(kind, entity, base, insert)))
    return out


class VisibilityStateCommand(Command):
    """ETATS DE VISIBILITE d'un bloc (ETATVIS / BVSTATE / VISIBILITE), voir l'entete du fichier."""

    NAME = "BVSTATE"
    LABEL = "États de visibilité"
    IMMEDIATE_PICK = True

    def start(self):
        self.item = None
        self.stage = "pick"                     # pick | menu | new | rename | hide
        self.before = None
        refs = [i for i in self.ctx.selection() if i.kind == "cad_insert"]
        if len(refs) == 1:
            self._take(refs[0])

    # -- donnees --
    def _definition(self):
        return cad_block.blocks(self.ctx.cad_page()).get(str(self.item.data.get("block") or ""))

    def _states(self) -> dict:
        return cad_block.states(self._definition())

    def _current(self) -> str:
        return cad_block.state_of(self._definition(), self.item.data)

    def _take(self, item):
        if item.locked():
            self.ctx.message("Référence verrouillée (ou sur un calque verrouillé) : non modifiable.", error=True)
            return
        self.item = item
        self.stage = "menu"
        from fm_board.scene import PAGE
        self.ctx.scene.commit_live()
        self.refs = [r for r in self.ctx.cad_items() if r.kind == "cad_insert"
                     and r.data.get("block") == item.data.get("block")]          # toutes : RENOMMER les fait suivre
        self.before = self.ctx.scene.snapshot([PAGE] + [r.item_id for r in self.refs])
        self.ctx.scene.clearSelection()
        self._say()

    def _say(self):
        names = list(self._states())
        if names:
            self.ctx.message(f"Bloc « {self.item.data.get('block')} » : états {', '.join(names)} ; montré : "
                             f"{self._current()}.")
        else:
            self.ctx.message(f"Bloc « {self.item.data.get('block')} » : aucun état (Nouveau pour en créer un).")

    def _set_states(self, new_states: dict, show: str | None = None):
        """Etats remplaces dans une definition NEUVE (dessin a jour tout de suite, annulation a la fin)."""
        cad = cad_model.copy_cad(self.ctx.cad_page())
        name = str(self.item.data.get("block") or "")
        cad["blocks"][name] = cad_block.with_states(cad["blocks"][name], new_states)
        self.ctx.scene.set_page({"cad": cad}, record=False)
        if show is not None:
            self.ctx.set_entity_values(self.item, {"state": show})

    # -- invites --
    def prompt(self):
        if self.stage == "pick":
            return Prompt("Choisissez une référence de bloc", [], "select")
        if self.stage == "new":
            return Prompt("Nom du nouvel état", [], "text")
        if self.stage == "rename":
            return Prompt(f"Nouveau nom de l'état « {self._current()} »", [], "text")
        if self.stage == "hide":
            return Prompt(f"Cliquez les objets du bloc à masquer / montrer dans l'état « {self._current()} » "
                          "(Entrée = terminé)", [], "point")
        names = list(self._states())
        hint = "/".join(names[:6]) + ("/…" if len(names) > 6 else "")
        return Prompt("Nom de l'état à montrer" + (f" [{hint}]" if hint else "")
                      + " ou Nouveau / Masquer / Renommer / Supprimer / ? (Entrée = terminé)", [], "text")

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
        if raw.strip():
            self.text(raw)

    def text(self, raw: str):
        word = raw.strip()
        if self.stage == "new":
            self._new(word)
            return
        if self.stage == "rename":
            self._rename(word)
            return
        if self.stage != "menu":
            return
        if not word:
            self._done()
            return
        states = self._states()
        exact = {n.upper(): n for n in states}
        key = word.upper()
        if key in exact:                                    # un etat (avant les mots-cles : « N » peut en etre un)
            self.ctx.set_entity_values(self.item, {"state": exact[key]})
            self.ctx.message(f"État « {exact[key]} » montré.")
        elif key in ("N", "NOUVEAU", "NEW"):
            self.stage = "new"
        elif key in ("M", "MASQUER", "H", "HIDE"):
            if not states:
                self.ctx.message("Créez d'abord un état (Nouveau).", error=True)
                return
            self.stage = "hide"
        elif key in ("R", "RENOMMER", "RENAME"):
            if states:
                self.stage = "rename"
        elif key in ("S", "SUPPRIMER", "D", "DELETE"):
            current = self._current()
            if current:
                rest = {k: v for k, v in states.items() if k != current}
                self._set_states(rest, next(iter(rest), ""))
                self.ctx.message(f"État « {current} » supprimé.")
        elif key in ("?", "L", "LISTE"):
            self._say()
        else:
            self.ctx.message(f"État « {word} » inconnu (Nouveau pour le créer).", error=True)

    def _new(self, name: str):
        name = name.strip()
        if not name:
            self.stage = "menu"
            return
        states = self._states()
        if name in states:
            self.ctx.message(f"L'état « {name} » existe déjà.", error=True)
            return
        hidden = cad_block.hidden_of(self._definition(), self.item.data)
        if not states:
            states = {}
        states[name] = set(hidden)
        self._set_states(states, name)
        self.ctx.message(f"État « {name} » créé : cliquez les objets à masquer.")
        self.stage = "hide"

    def _rename(self, name: str):
        current = self._current()
        name = name.strip()
        states = self._states()
        if not name or name == current:
            self.stage = "menu"
            return
        if name in states:
            self.ctx.message(f"L'état « {name} » existe déjà.", error=True)
            return
        renamed = {(name if k == current else k): v for k, v in states.items()}
        self._set_states(renamed, name)
        for ref in self.refs:                               # les autres references de ce bloc suivent
            if ref is not self.item and ref.scene() is not None and ref.data.get("state") == current:
                self.ctx.set_entity_values(ref, {"state": name})
        self.stage = "menu"

    def point(self, p):
        if self.stage != "hide":
            return
        cad = self.ctx.cad_page()
        index = cad_block.index_at(cad, self.item.data, (float(p[0]), float(p[1])), PICK_PX / self.ctx.scale())
        if index is None:
            self.ctx.message("Aucun objet du bloc ici.", error=True)
            return
        states = self._states()
        current = self._current()
        hidden = states[current]
        if index in hidden:
            hidden.discard(index)
        else:
            hidden.add(index)
        self._set_states(states)

    def enter(self):
        if self.stage in ("hide", "new", "rename"):
            self.stage = "menu"
        else:
            self._done()

    def cancel(self):
        self._done()

    def ghosts(self, p):
        """En masquant : les objets masques de l'etat (en fantome, pour les remontrer d'un clic)."""
        if self.stage != "hide" or self.item is None:
            return []
        hidden = cad_block.hidden_of(self._definition(), self.item.data)
        return cad_shapes.display_segments(entity_prims(self.ctx.cad_page(), self.item.data, hidden),
                                           self.ctx.tess_tol())

    def _done(self):
        if self.before is not None:
            scene = self.ctx.scene
            after = scene.snapshot(list(self.before))
            if after != self.before:
                scene.push(self.before, after, "États de visibilité")
            self.before = None
        self.finish()


NEW_ENTRIES = (
    ("BVSTATE", "États de visibilité", ("ETATVIS", "VISIBILITE", "VISIBILITÉ", "ETATBLOC", "BVS"),
     VisibilityStateCommand),
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
