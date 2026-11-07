"""Documents des éléments PDF du Board (Qt, sans widget) : UNE session par élément (`PdfSession`, ouverte dans le
fil du moteur avec le JavaScript et le XFA, comme l'éditeur), qui sert À LA FOIS à l'aperçu et à l'édition sur place.

Pourquoi (demande de l'utilisateur, 2026-11-06 : le Board montrait « Please wait… » d'un XFA de l'IRCC, une seule
page) : l'aperçu ouvrait le fichier SANS JavaScript, or PDFium n'exécute le XFA qu'avec lui (sonde : IMM 1344 = 1 page
de repli sans, 14 pages avec) ; et chaque taille d'aperçu rouvrait le document (7 s pour l'IMM 1344). Désormais le
document est ouvert UNE fois par élément ; activer le module puis cliquer l'élément l'édite aussitôt (rien à rouvrir),
et l'aperçu montre les valeurs saisies, même non enregistrées.

- Registre : (jeton de la scène, identifiant de l'élément) -> `DocEntry` (un élément supprimé puis rétabli par
  l'annulation retrouve son document et ses saisies). Fermé avec la scène (`close_scene`).
- Images de l'aperçu : page entière à une largeur ARRONDIE à la puissance de 2 (au plus 2 fois trop grande, lissée),
  rendues à la priorité « miniatures » ; mémoire bornée en octets (`IMAGE_BUDGET`).
- Fermeture du Board : `confirm_leave` demande pour chaque document modifié (Enregistrer / Ne pas enregistrer /
  Annuler)."""
from __future__ import annotations

import math
import os
import time
import uuid
import weakref

from PySide6.QtCore import QObject, QTimer

from .worker import PRIO_THUMB

IMAGE_BUDGET = 192 * 1024 * 1024
FILE_CHECK_S = 2.0
_REGISTRY: dict = {}                     # (jeton, identifiant) -> DocEntry
_IMAGES: dict = {}                       # (entrée, génération, page, largeur) -> QImage, du plus ancien au plus récent
_IMAGE_BYTES = [0]


def width_bucket(need_px: float) -> int:
    """Largeur rendue pour une page affichée sur `need_px` pixels : puissance de 2 au-dessus (64 à 2048)."""
    need = max(64.0, min(2048.0, float(need_px)))
    return int(2 ** math.ceil(math.log2(need)))


def scene_token(scene) -> str:
    token = getattr(scene, "_pdf_token", None)
    if token is None:
        token = scene._pdf_token = uuid.uuid4().hex
        weakref.finalize(scene, close_token, token)
        try:
            scene.destroyed.connect(lambda *_a, t=token: close_token(t))
        except (AttributeError, RuntimeError):
            pass
    return token


class DocEntry(QObject):
    """Le document d'un élément : sa session, ses images d'aperçu, l'élément à repeindre."""

    def __init__(self, key, path, settings: dict):
        super().__init__()
        from .session import PdfSession
        self.key = key
        self.path = path
        self.error = ""
        self.needs_password = False
        self.live_wanted = False                      # clic pendant l'ouverture : éditer dès que prêt
        self._item = None
        self._checked = time.monotonic()
        self._pending: set = set()
        self.session = PdfSession()
        self.session.options["javascript"] = bool(settings.get("pdf_javascript", True))
        self.session.opened.connect(self._changed)
        self.session.reloaded.connect(self._changed)
        self.session.failed.connect(self._failed)
        self.session.stateChanged.connect(self._repaint)
        self.session.events.connect(self._events)
        self.session.open_path(path)

    # -- élément --

    def attach(self, item) -> None:
        self._item = weakref.ref(item)

    def item(self):
        return self._item() if self._item is not None else None

    def _repaint(self, *_a) -> None:
        item = self.item()
        if item is not None:
            try:
                item.update()
            except RuntimeError:                       # élément détruit entre-temps
                self._item = None

    # -- état du document --

    @property
    def info(self) -> dict:
        return self.session.info

    def ready(self) -> bool:
        return bool(self.session.info.get("page_count"))

    def _changed(self, _info=None) -> None:
        self.error = ""
        self.needs_password = False
        self.drop_images()
        self._repaint()
        QTimer.singleShot(0, self._fit_frame)          # élément d'avant les pages bord à bord : recalé une fois
        if self.live_wanted:                           # cliqué pendant l'ouverture : édition maintenant
            self.live_wanted = False
            QTimer.singleShot(0, self._live_now)

    def _fit_frame(self) -> None:
        item = self.item()
        try:
            if item is not None and item.scene() is not None:
                item.fit_frame_once()
        except RuntimeError:                           # élément détruit entre-temps
            pass

    def _live_now(self) -> None:
        item = self.item()
        try:
            if item is not None and item.scene() is not None and item._module_active():
                item.go_live()
        except RuntimeError:                           # élément détruit entre-temps
            pass

    def _failed(self, message: str, needs_password: bool) -> None:
        self.error = message
        self.needs_password = needs_password
        self._repaint()

    def _events(self, events: list) -> None:
        """Zones redessinées par le formulaire (saisie, scripts) : les images d'aperçu de ces pages sont périmées."""
        pages = {e[1] for e in events if e and e[0] == "invalidate"}
        if pages or any(e and e[0] == "pages_changed" for e in events):
            self.drop_images(pages or None)

    def reopen_if_changed(self) -> bool:
        """Fichier changé ailleurs (éditeur plein cadre, autre logiciel) et document NON modifié ici : rouvert."""
        from . import fileio
        session = self.session
        if session.closed or session.dirty or session.file_sig is None:
            return False
        try:
            if fileio.signature(self.path) == session.file_sig:
                return False
        except OSError:
            return False
        session.open_path(self.path, session.password)
        return True

    def check_file(self) -> None:
        """Appelé à la peinture : au plus une vérification du fichier toutes les `FILE_CHECK_S` secondes."""
        now = time.monotonic()
        if now - self._checked >= FILE_CHECK_S:
            self._checked = now
            self.reopen_if_changed()

    # -- images de l'aperçu --

    def page_image(self, page: int, width_px: int):
        """Image de la page à `width_px` de large (gardée), sinon demandée au moteur : l'élément est repeint à
        l'arrivée. Pendant l'attente : l'image d'une autre largeur si elle existe (aperçu flou plutôt que vide)."""
        gen = self.session.generation
        key = (self, gen, page, width_px)
        img = _IMAGES.get(key)
        if img is not None:
            _IMAGES[key] = _IMAGES.pop(key)            # le plus récent à la fin
            return img
        if key not in self._pending and self.ready() and page < len(self.info.get("sizes", ())):
            w, h = self.info["sizes"][page]
            scale = width_px / max(1.0, w)
            self._pending.add(key)

            def done(result, error, key=key):
                self._pending.discard(key)
                if error is None and result is not None and result[0] == self.session.generation:
                    _put(key, result[1])
                    self._repaint()
            self.session.render_tile(page, scale, (0, 0, max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                                     0, PRIO_THUMB, done)
        return next((im for (e, g, p, _w), im in reversed(_IMAGES.items()) if e is self and g == gen and p == page),
                    None)

    def drop_images(self, pages=None) -> None:
        for key in [k for k in _IMAGES if k[0] is self and (pages is None or k[2] in pages)]:
            _drop(key)

    # -- fin --

    def close(self) -> None:
        self.drop_images()
        self.session.close()


def _put(key, img) -> None:
    _IMAGES[key] = img
    _IMAGE_BYTES[0] += img.sizeInBytes()
    while _IMAGE_BYTES[0] > IMAGE_BUDGET and len(_IMAGES) > 1:
        _drop(next(iter(_IMAGES)))


def _drop(key) -> None:
    img = _IMAGES.pop(key, None)
    if img is not None:
        _IMAGE_BYTES[0] -= img.sizeInBytes()


# -- registre --

def entry_for(item, path, settings: dict) -> DocEntry | None:
    """Document de l'élément (ouvert au premier appel) ; un autre fichier lié = nouveau document."""
    scene = item.scene()
    if scene is None or path is None:
        return None
    key = (scene_token(scene), item.item_id)
    entry = _REGISTRY.get(key)
    if entry is not None and entry.path != path:
        if entry.session.dirty:                          # lien changé avec des saisies : on garde le document
            entry.attach(item)
            return entry
        entry.close()
        entry = None
    if entry is None:
        entry = _REGISTRY[key] = DocEntry(key, path, settings)
    entry.attach(item)
    return entry


def existing_entry(item) -> DocEntry | None:
    scene = item.scene()
    if scene is None:
        return None
    return _REGISTRY.get((scene_token(scene), item.item_id))


def entries_of(scene) -> list[DocEntry]:
    token = getattr(scene, "_pdf_token", None)
    return [e for k, e in _REGISTRY.items() if k[0] == token] if token else []


def close_token(token) -> None:
    for key in [k for k in _REGISTRY if k[0] == token]:
        entry = _REGISTRY.pop(key)
        try:
            entry.close()
        except RuntimeError:
            pass


def close_scene(scene) -> None:
    token = getattr(scene, "_pdf_token", None)
    if token:
        close_token(token)


def reopen_path(scene, path) -> None:
    """Après l'éditeur plein cadre : les documents de ce fichier (non modifiés ici) sont rouverts s'il a changé."""
    for entry in entries_of(scene):
        if os.path.normcase(str(entry.path)) == os.path.normcase(str(path)):
            entry.reopen_if_changed()


def confirm_leave(parent, scene) -> bool:
    """Fermeture du Board : chaque document modifié -> Enregistrer / Ne pas enregistrer / Annuler. False = annulé."""
    from . import fileio, ui_kit
    for entry in entries_of(scene):
        session = entry.session
        if not session.dirty or session.closed:
            continue
        name = session.path.name if session.path else "Sans titre"
        choice = ui_kit.choose(parent, "Document PDF modifié", "« %s » a des modifications non enregistrées." % name,
                               [("save", "Enregistrer"), ("discard", "Ne pas enregistrer")])
        if choice == "discard":
            if session.path is not None:
                fileio.drop_recovery(session.path)
            continue
        if choice != "save" or not save_and_wait(entry, parent):
            return False
    return True


def save_and_wait(entry, parent=None, timeout: float = 120.0) -> bool:
    """Enregistre le document de l'élément et attend la fin (fermeture du Board)."""
    from PySide6.QtWidgets import QApplication
    done = []
    save(entry, parent, callback=lambda ok: done.append(ok))
    end = time.perf_counter() + timeout
    while not done and time.perf_counter() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    return bool(done and done[0])


def save(entry, parent=None, callback=None, settings: dict | None = None) -> None:
    """Enregistre le fichier lié (écriture transactionnelle vérifiée de la session). Fichier modifié ailleurs depuis
    l'ouverture : Garder ma version / Recharger (perdre mes changements) / Annuler ; `callback(ok)` est TOUJOURS
    appelé."""
    from . import fileio, ui_kit
    session = entry.session
    if session.path is None:
        if callback:
            callback(False)
        return
    mode = (settings or {}).get("pdf_save_mode", "auto")
    incremental = None if mode == "auto" else (mode == "incremental")
    try:
        changed = session.file_sig is not None and fileio.signature(session.path) != session.file_sig
    except OSError:
        changed = False
    if changed:
        choice = ui_kit.choose(parent, "Fichier modifié ailleurs",
                               "« %s » a été modifié par un autre logiciel depuis son ouverture." % session.path.name,
                               [("mine", "Garder ma version"), ("reload", "Recharger (perdre mes changements)")])
        if choice == "reload":
            session.open_path(session.path, session.password)
        if choice != "mine":
            if callback:
                callback(False)
            return
    session.save(incremental=incremental, force=True, callback=callback)   # conflit déjà vérifié ci-dessus
