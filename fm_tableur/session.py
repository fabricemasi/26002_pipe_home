"""Session d'un classeur (SANS Qt) : LE document partagé par toutes ses présentations.

Une session = classeur + moteur de calcul + pile d'annulation + état de navigation (feuille active, cellule
active, sélection, défilement, par feuille). L'élément du Board et le mode Standard affichent la MÊME session :
passer de l'un à l'autre ne recharge rien, ne recalcule rien, garde l'annulation, la feuille, la sélection et la
position (demande de l'utilisateur). Registre par clé (identifiant de l'élément du board ou chemin de fichier)."""
from __future__ import annotations

from . import io_native
from .commands import UndoStack
from .document import Workbook, new_workbook
from .engine import CalcEngine


class SheetView:
    """Navigation dans une feuille : cellule active, sélections (plages), défilement (pixels à 100 %)."""
    __slots__ = ("current", "anchor", "ranges", "scroll")

    def __init__(self):
        self.current = (0, 0)
        self.anchor = (0, 0)
        self.ranges = [(0, 0, 0, 0)]
        self.scroll = (0.0, 0.0)


class Session:
    def __init__(self, book: Workbook | None = None, active: int = 0, key=None):
        self.key = key
        self.book = book or new_workbook()
        self.engine = CalcEngine(self.book)
        self.stack = UndoStack(self.book)
        self.active_uid = self.book.sheets[max(0, min(active, len(self.book.sheets) - 1))].uid
        self.views: dict[int, SheetView] = {}
        self.show_formulas = False
        self._snapshot = None                   # (révision, dictionnaire natif) : sérialisation gardée
        self.owners: list = []                  # présentations ouvertes (widgets) : une seule a le clavier

    # -- feuille active --
    @property
    def sheet(self):
        found = self.book.sheet_by_uid(self.active_uid)
        if found is None:
            found = self.book.sheets[0]
            self.active_uid = found.uid
        return found

    def set_active(self, sheet):
        self.active_uid = sheet.uid
        self.book.notify("active", sheet)

    def view(self, sheet=None) -> SheetView:
        sheet = sheet or self.sheet
        found = self.views.get(sheet.uid)
        if found is None:
            found = self.views[sheet.uid] = SheetView()
        return found

    def active_index(self) -> int:
        try:
            return self.book.index_of(self.sheet)
        except ValueError:
            return 0

    # -- sérialisation --
    def snapshot(self) -> dict:
        """Dictionnaire natif, refait seulement si le classeur a changé (enregistrement automatique du Board)."""
        key = (self.book.revision, self.active_index())
        if self._snapshot is None or self._snapshot[0] != key:
            self._snapshot = (key, io_native.to_dict(self.book, self.active_index()))
        return self._snapshot[1]

    @classmethod
    def from_dict(cls, raw, key=None) -> "Session":
        book, active = io_native.from_dict(raw)
        session = cls(book, active, key)
        session._snapshot = ((book.revision, active), raw) if isinstance(raw, dict) and raw.get("sheets") else None
        return session


_REGISTRY: dict = {}


def get(key):
    return _REGISTRY.get(key)


def register(session: Session):
    _REGISTRY[session.key] = session
    return session


def forget(key):
    _REGISTRY.pop(key, None)


def obtain(key, raw=None) -> Session:
    """Session déjà ouverte pour `key`, sinon construite depuis `raw` (dictionnaire natif)."""
    found = _REGISTRY.get(key)
    if found is None:
        found = register(Session.from_dict(raw, key))
    return found
