"""Service de rendu du moteur photo : TOUT le calcul hors du fil de l'interface, annulable, périmés abandonnés.

Une demande par photo (`demander`) ; une nouvelle demande pour la même photo, ou `abandonner`, périme les
précédentes : le calcul en cours s'arrête à sa prochaine étape (`operations.Annule`) et un résultat arrivé trop
tard n'est jamais émis. Chaque demande rend d'abord un aperçu PROVISOIRE (grand côté <= 1024 px : les traitements
spatiaux y sont calculés à une autre échelle, voir `operations.py`), puis le rendu à la définition de la zone
d'affichage. `pret(clé, Rendu)` arrive sur le fil de l'interface ; `sans_rendu(clé)` quand il n'y a rien à
développer (pas d'état, opérations neutres, source illisible).

Mémoire : sources en float32 gardées dans un cache borné (`BUDGET_SOURCES`, les moins récemment servies partent
d'abord), jamais dans le cache d'images de la visionneuse. Deux fils au plus ; numpy n'en lance pas d'autres pour
ces calculs (pas de parallélisme imbriqué)."""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, QSizeF, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage

from fm_photo import etat, moteur, operations, sources


@dataclass
class Rendu:
    cle: str
    signature: str               # etat.signature de la suite rendue
    image: QImage                # rendu à l'échelle 1 / facteur (RGB32, sRGB)
    ajustee: QImage              # même rendu, ajusté à la zone d'affichage
    naturelle: QSizeF            # taille réelle de la photo (pleine définition)
    provisoire: bool             # aperçu rapide, remplacé par le rendu à la définition de l'écran
    facteur: int                 # réduction entière appliquée à la source (1 = pleine définition)
    provenance: str              # d'où viennent les pixels source
    executant: str               # « Rust » ou « référence numpy » (moteur.executant)
    duree_ms: float

    def origine(self) -> str:
        """Texte du badge de la visionneuse : jamais un aperçu provisoire présenté comme définitif."""
        etat_rendu = "aperçu provisoire" if self.provisoire else (
            "pleine définition" if self.facteur == 1 else f"définition de l'écran (1/{self.facteur})")
        return f"Développement PIPE FMZ · {etat_rendu} · {self.executant} · {self.provenance}"


class _Signaux(QObject):
    fini = Signal(str, int, object)          # clé, génération, Rendu ou None


def _timbre(cle: str):
    try:
        info = os.stat(cle)
        return info.st_mtime_ns, info.st_size
    except OSError:
        return None


class _Tache(QRunnable):
    def __init__(self, service: "ServiceRendu", cle: str, generation: int, suite, cible: QSize):
        super().__init__()
        self.setAutoDelete(True)
        self._service, self._cle, self._generation, self._suite, self._cible = service, cle, generation, suite, cible

    def _perimee(self) -> bool:
        return self._service._generations.get(self._cle) != self._generation

    def _geree_par_lightroom(self) -> bool:
        """Photo d'un dossier associé à Lightroom : la visionneuse montre SON rendu développé ; un état PIPE FMZ
        enregistré ne le remplace pas d'office (règle de priorité à arrêter, voir docs/agents/fm_photo.md)."""
        try:
            from lightroom_bridge import is_managed
            return is_managed(Path(self._cle))
        except Exception:
            return False

    def _emettre(self, rendu):
        try:
            self._service._signaux.fini.emit(self._cle, self._generation, rendu)
        except RuntimeError:                 # appli en train de se fermer
            pass

    def run(self):
        try:
            suite = self._suite
            if suite is None and self._geree_par_lightroom():
                self._emettre(None)
                return
            if suite is None:                # état enregistré de la photo, lu ici (jamais sur le fil de l'interface)
                enregistre = etat.lire(Path(self._cle))
                suite = etat.operations(enregistre) if enregistre else []
            if not operations.chaine(suite) or self._perimee():
                self._emettre(None)
                return
            source = self._service._source(self._cle)
            if source is None or self._perimee():
                self._emettre(None)
                return
            hauteur, largeur = source.pixels.shape[:2]
            final = moteur.facteur_pour(largeur, hauteur, self._cible.width(), self._cible.height())
            rapide = moteur.facteur_rapide(largeur, hauteur)
            etapes = [(True, rapide), (False, final)] if rapide > final else [(False, final)]
            signature = etat.signature(suite)
            for provisoire, facteur in etapes:
                debut = time.perf_counter()
                tampon = moteur.rendre_affichage(source.pixels, suite, facteur, self._perimee, source.cle)
                image = QImage(tampon.data, tampon.shape[1], tampon.shape[0], tampon.shape[1] * 4,
                               QImage.Format_RGBX8888).convertToFormat(QImage.Format_RGB32)   # copie détachée
                ajustee = image
                if self._cible.isValid() and (image.width() > self._cible.width()
                                              or image.height() > self._cible.height()):
                    ajustee = image.scaled(self._cible, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                if self._perimee():
                    return
                self._emettre(Rendu(self._cle, signature, image, ajustee, QSizeF(largeur, hauteur), provisoire,
                                    facteur, source.provenance, moteur.executant(suite),
                                    (time.perf_counter() - debut) * 1000.0))
        except operations.Annule:
            return
        except Exception:                    # état illisible, opération inconnue… : l'image décodée reste
            self._emettre(None)


class ServiceRendu(QObject):
    pret = Signal(str, object)               # clé, Rendu
    sans_rendu = Signal(str)                 # clé : rien à développer pour cette photo

    BUDGET_SOURCES = 1024 * 1024 * 1024

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._signaux = _Signaux(self)
        self._signaux.fini.connect(self._sur_fini)
        self._generations: dict[str, int] = {}
        self._compteur = 0
        self._verrou = threading.Lock()
        self._sources: OrderedDict = OrderedDict()       # clé -> (timbre du fichier, Source)
        self._octets = 0

    def demander(self, chemin: Path, cible: QSize, suite: list | None = None, urgent: bool = False) -> None:
        """Rend `suite` (ou, `None`, l'état enregistré de la photo) pour une zone de `cible` pixels physiques."""
        cle = str(chemin)
        self._compteur += 1
        self._generations[cle] = self._compteur
        if len(self._generations) > 4096:
            self._generations = {cle: self._compteur}
        self._pool.start(_Tache(self, cle, self._compteur, suite, QSize(cible)), 1 if urgent else 0)

    def abandonner(self, chemin: Path) -> None:
        """Périme les demandes de cette photo : calcul en cours arrêté, résultat tardif jamais émis."""
        self._compteur += 1
        self._generations[str(chemin)] = self._compteur

    def tout_abandonner(self) -> None:
        """Fermeture de l'appli : plus aucun calcul n'aboutit, les tâches en file ne démarrent pas."""
        self._pool.clear()
        for cle in list(self._generations):
            self._compteur += 1
            self._generations[cle] = self._compteur

    def oublier_source(self, chemin: Path) -> None:
        with self._verrou:
            ancienne = self._sources.pop(str(chemin), None)
            if ancienne is not None:
                self._octets -= ancienne[1].octets
                moteur.oublier(ancienne[1].cle)

    def attendre(self, delai_ms: int = 30000) -> bool:
        """Pour les tests et l'arrêt : attend la fin des tâches lancées."""
        return self._pool.waitForDone(delai_ms)

    def _source(self, cle: str):
        timbre = _timbre(cle)
        with self._verrou:
            connue = self._sources.get(cle)
            if connue is not None and connue[0] == timbre:
                self._sources.move_to_end(cle)
                return connue[1]
        source = sources.charger(Path(cle)) if timbre is not None else None
        if source is None:
            return None
        with self._verrou:
            ancienne = self._sources.pop(cle, None)
            if ancienne is not None:
                self._octets -= ancienne[1].octets
                moteur.oublier(ancienne[1].cle)
            self._sources[cle] = (timbre, source)
            self._octets += source.octets
            while self._octets > self.BUDGET_SOURCES and len(self._sources) > 1:
                _cle, partie = self._sources.popitem(last=False)
                self._octets -= partie[1].octets
                moteur.oublier(partie[1].cle)
        return source

    def _sur_fini(self, cle: str, generation: int, rendu):
        if self._generations.get(cle) != generation:
            return                           # périmé : une demande plus récente existe, ou abandon
        if rendu is None:
            self.sans_rendu.emit(cle)
        else:
            self.pret.emit(cle, rendu)
