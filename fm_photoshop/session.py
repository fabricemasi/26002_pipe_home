"""Session d'un document (SANS Qt) : LE document partagé par toutes ses présentations.

Une session = document + historique + état de travail (outil, brosse, couleurs, calque actif, cible pixels / masque,
zoom et position de la vue, sélection). L'élément du Board et l'éditeur Standard affichent la MÊME session : passer
de l'un à l'autre ne recharge rien, ne copie rien, garde l'historique, l'outil et la vue. Registre par clé
(jeton de la scène + identifiant de l'élément)."""
from __future__ import annotations

import hashlib

from . import container, ops
from .brush import Brush
from .history import History
from .model import Document, new_document


class Session:
    def __init__(self, doc: Document, key=None):
        self.key = key
        self.doc = doc
        self.history = History()
        self.listeners: list = []                  # callables (kind, rect) : "edit" / "structure" / "view" / "reload"
        self.tool = "brush"
        self.brush = Brush()
        self.fg = (0, 0, 0)
        self.bg = (255, 255, 255)
        self.target = "pixels"                     # cible des outils : "pixels" ou "mask"
        self.active_uid = doc.layers[-1].uid
        self.zoom = None                           # None = ajusté à la zone (premier affichage)
        self.center = None                         # point du document au centre de la vue
        self.selection = None                      # `selection.Selection` ou None (rien de sélectionné)
        self.options = {"tolerance": 32, "contiguous": True, "sample": "layer"}      # baguette magique
        self.clone = {"source": None, "offset": None, "aligned": True}      # tampon / correcteur : source explicite
        self.shape_options = {"fill": True, "stroke": False, "stroke_width": 4, "radius": 0}      # outils de forme
        self.asset: str | None = None              # dernier conteneur écrit dans le dossier du Board
        self.flushed_version = -1
        self.error: str | None = None              # ressource absente / illisible (diagnostic)

    # -- accès --
    def layer(self):
        found = self.doc.find(self.active_uid)
        if found is None:
            found = self.doc.layers[-1]
            self.active_uid = found.uid
        return found

    def select_layer(self, layer):
        self.active_uid = layer.uid
        if self.target == "mask" and layer.mask is None:
            self.target = "pixels"
        self.notify("view", None)

    # -- notification --
    def notify(self, kind: str, rect):
        for callback in list(self.listeners):
            callback(kind, rect)

    # -- édition --
    def do(self, command, notified: bool = False):
        """Pousse une étape DÉJÀ appliquée (None = rien n'a changé). `notified` : les présentations ont déjà reçu
        les zones modifiées au fil du geste (trait, déplacement) : elles ne reçoivent que « committed »."""
        if command is None:
            return None
        self.history.push(command)
        if notified:
            self.notify("committed", None)
        else:
            self.notify(self._kind_of(command), command.rect)
        return command

    def undo(self):
        command = self.history.undo()
        if command is not None:
            self._after_history(command)
        return command

    def redo(self):
        command = self.history.redo()
        if command is not None:
            self._after_history(command)
        return command

    @staticmethod
    def _kind_of(command):
        from .history import SelectionCommand
        return "selection" if isinstance(command, SelectionCommand) else "structure" if command.structural else "edit"

    def _after_history(self, command):
        if self.doc.find(self.active_uid) is None:
            self.active_uid = self.doc.layers[-1].uid
        layer = self.layer()
        if self.target == "mask" and layer.mask is None:
            self.target = "pixels"
        self.notify(self._kind_of(command), command.rect)

    def is_dirty(self) -> bool:
        return self.history.dirty()

    # -- sauvegarde --
    def flush(self, store) -> str:
        """Conteneur à jour dans le dossier du Board. `store(octets, suffixe) -> nom` écrit (atomiquement) sous un
        nom d'empreinte. Rien n'est refait tant que le document n'a pas changé."""
        if self.asset is not None and (self.flushed_version == self.history.version
                                       or (self.error and self.history.version == 0)):
            return self.asset                      # (session en erreur et intacte : on garde la référence d'origine)
        payload = container.dumps(self.doc, preview=False)
        name = store(payload, ".fmps")
        self.asset, self.flushed_version = name, self.history.version
        return name

    def digest(self) -> str:
        return hashlib.sha1(container.dumps(self.doc)).hexdigest()[:16]


_REGISTRY: dict = {}


def get(key):
    return _REGISTRY.get(key)


def register(session: Session):
    _REGISTRY[session.key] = session
    return session


def forget(key):
    _REGISTRY.pop(key, None)


def create(key, width: int, height: int, name: str, dpi: float = 72.0, background=(255, 255, 255, 255)) -> Session:
    return register(Session(new_document(width, height, name, dpi, background), key))


def open_asset(key, payload: bytes | None, fallback: dict | None = None, asset_name: str | None = None) -> Session:
    """Session déjà ouverte pour `key`, sinon lue depuis le conteneur `payload` (octets). Ressource absente ou
    illisible : session VIDE (la taille d'origine vient de `fallback`) avec `error` renseigné — rien n'est inventé."""
    found = _REGISTRY.get(key)
    if found is not None:
        return found
    fallback = fallback or {}
    try:
        if payload is None:
            raise container.ContainerError("Ressource du document absente du dossier du Board.")
        session = Session(container.loads(payload), key)
        session.asset, session.flushed_version = asset_name, 0
    except container.ContainerError as exc:
        session = Session(new_document(int(fallback.get("w", 800)), int(fallback.get("h", 600)),
                                       fallback.get("title", "Document"), background=None), key)
        session.error = str(exc)
        session.asset = asset_name                 # la référence d'origine est conservée (rien n'est écrasé)
    return register(session)
