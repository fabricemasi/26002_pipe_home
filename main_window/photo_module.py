"""Environnement photo (`fm_photo`) dans la fenêtre principale : les rendus développés entrent dans la visionneuse.

Une seule visionneuse : le moteur photo ne possède aucun affichage. Quand le chargeur de la visionneuse a décodé
une image, son état de développement enregistré (`.pipeline_photo.json` du dossier) est lu et rendu EN FOND par
`fm_photo.rendu.ServiceRendu` ; le résultat remplace l'image décodée par `FocusImageLoader.set_rendition`
(centre, ruban, zoom, visionneuse à côté). Sans état, rien ne change. Coût sur le fil de l'interface par image
prête : une recherche de dictionnaire et le lancement d'une tâche. Détail : docs/agents/fm_photo.md."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication


class PhotoModuleMixin:
    def _install_photo(self) -> None:
        """Une fois, après la création du chargeur de la visionneuse (`_focus_images`)."""
        self._photo_rendus = None
        self._focus_images.ready.connect(self._on_photo_image_ready)

    def _photo_service(self):
        service = self._photo_rendus
        if service is None:
            from fm_photo.rendu import ServiceRendu
            service = self._photo_rendus = ServiceRendu(self)
            service.pret.connect(self._on_photo_rendu)
            service.sans_rendu.connect(self._on_photo_sans_rendu)
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(service.tout_abandonner)      # la fermeture n'attend aucun calcul
        return service

    def photo_develop(self, path: Path, suite: list) -> None:
        """Montre `suite` (opérations de `fm_photo.etat`) sur cette photo dans la visionneuse, sans l'enregistrer :
        point d'entrée des outils de développement, des recettes et de FM Film (aperçu en direct)."""
        self._photo_service().demander(Path(path), self._focus_images.fit(), suite, urgent=True)

    def _on_photo_image_ready(self, key: str) -> None:
        path = Path(key)
        if self._focus_images.has_rendition(path):
            return                                   # le rendu développé vient d'arriver, ou il est déjà montré
        self._photo_service().demander(path, self._focus_images.fit())

    def _on_photo_rendu(self, key: str, rendu) -> None:
        self._focus_images.set_rendition(Path(key), rendu.image, rendu.ajustee, rendu.naturelle, rendu.origine())

    def _on_photo_sans_rendu(self, key: str) -> None:
        self._focus_images.clear_rendition(Path(key))
