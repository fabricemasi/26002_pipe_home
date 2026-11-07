"""Enregistrement du conteneur EN ARRIÈRE-PLAN (SANS Qt).

Sur une grande page (2480 x 3508 : un calque = 35 Mo), encoder le PNG du calque modifié, calculer l'empreinte et écrire
l'archive prenait 0,1 s (page blanche) à plus de 0,6 s (page peinte) SUR LE FIL DE L'INTERFACE, 800 ms après chaque trait
(enregistrement automatique du Board) : le curseur de brosse se figeait à chaque pause. Le travail est maintenant fait
dans un fil, juste après le geste ; l'enregistrement du Board trouve le conteneur déjà prêt.

Garanties : le fil ne lit RIEN de vivant (manifeste en texte, plans copiés par `container.Prepared`) ; un clic « Enregistrer »
pendant le travail ATTEND le même travail (`join`) au lieu de le refaire ; l'échec d'un fil (dossier disparu…) n'est jamais
fatal : l'enregistrement synchrone suivant refait le travail et signale l'erreur lui-même."""
from __future__ import annotations

import threading

from . import container


class FlushJob:
    def __init__(self, version: int, prepared, store):
        self.version = version                      # `History.version` du document figé par `prepared`
        self.prepared = prepared
        self.store = store                          # store(octets, suffixe) -> nom (thread-safe : empreinte + écriture atomique)
        self.name: str | None = None
        self.error: BaseException | None = None
        self.cancelled = False
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, name="fm_photoshop_flush", daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        try:
            payload = self.prepared.build(cancelled=lambda: self.cancelled)
            if not self.cancelled:
                self.name = self.store(payload, ".fmps")
        except container.Cancelled:
            pass
        except BaseException as exc:                # (jamais fatal dans un fil : l'enregistrement synchrone refera et dira)
            self.error = exc
        finally:
            self.prepared = None
            self.done.set()

    def finished(self) -> bool:
        return self.done.is_set()

    def join(self, timeout: float | None = None) -> bool:
        return self.done.wait(timeout)

    def cancel(self, timeout: float | None = 10.0):
        self.cancelled = True
        self.done.wait(timeout)
