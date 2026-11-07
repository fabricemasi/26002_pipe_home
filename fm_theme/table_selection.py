"""Sélections des tableaux (colonnes d'un entête, sous-cellules des cellules divisées), communes à toute l'appli
(demande de l'utilisateur, 2026-10-30) :

- un clic SANS Maj qui sélectionne une colonne ou une sous-cellule désélectionne toutes les autres (autres lignes,
  autres tableaux) ; avec Maj, la sélection multiple est gardée ;
- un clic EN DEHORS de la sélection (ailleurs dans le tableau, dans une autre fenêtre…) désélectionne tout.

Un « propriétaire » (entête `_ResizableTableHeader`, cellule divisée `SplitCell`) appelle `changed(self, exclusive)`
après chaque clic de sélection et fournit `has_selection()`, `clear_selection()` et `owns_press(pos_globale)` (vrai
pour un clic qu'il traite lui-même : légende, titre, bordure à tirer — tirer la bordure d'une colonne sélectionnée
garde la sélection, qui donne la largeur commune). Le filtre d'application n'est posé QUE tant qu'une sélection
existe (règle de l'appli : jamais de filtre permanent). Aucun import de l'appli.
"""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

_OWNERS: list = []          # propriétaires qui ont une sélection
_FILTER = None


def _alive(owner) -> bool:
    try:
        return shiboken6.isValid(owner) and owner.has_selection()
    except RuntimeError:
        return False


def changed(owner, exclusive: bool) -> None:
    """Sélection de `owner` modifiée par un clic ; `exclusive` (clic sans Maj) : les autres sont vidées."""
    if exclusive:
        clear_all(keep=owner)
    _OWNERS[:] = [o for o in _OWNERS if o is not owner and _alive(o)]
    if _alive(owner):
        _OWNERS.append(owner)
    _sync_filter()


def clear_all(keep=None) -> None:
    """Vide toutes les sélections (sauf celle de `keep`)."""
    for owner in list(_OWNERS):
        if owner is keep:
            continue
        try:
            if shiboken6.isValid(owner):
                owner.clear_selection()
        except RuntimeError:
            pass
    _OWNERS[:] = [keep] if keep is not None and _alive(keep) else []
    _sync_filter()


def _sync_filter() -> None:
    global _FILTER
    app = QApplication.instance()
    if app is None:
        return
    if _OWNERS and _FILTER is None:
        _FILTER = _OutsideClick()
        app.installEventFilter(_FILTER)
    elif not _OWNERS and _FILTER is not None:
        app.removeEventFilter(_FILTER)
        _FILTER.deleteLater()
        _FILTER = None


class _OutsideClick(QObject):
    """Clic gauche hors de ce que traitent les propriétaires : toutes les sélections sont vidées."""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and _OWNERS:
            pos = event.globalPosition().toPoint()
            owned = False
            # Le widget clique (ou un parent) traite lui-meme ce clic : legende d'une AUTRE cellule divisee, titre
            # d'un autre entete (son propre clic decide : seul = exclusif, Maj = ajoute).
            widget = watched if watched.isWidgetType() else None
            while widget is not None and not owned:
                owns = getattr(widget, "owns_press", None)
                owned = bool(owns is not None and owns(pos))
                widget = widget.parentWidget()
            for owner in [] if owned else list(_OWNERS):
                try:
                    if shiboken6.isValid(owner) and owner.owns_press(pos):
                        owned = True
                        break
                except RuntimeError:
                    continue
            if not owned:
                clear_all()
        return False
