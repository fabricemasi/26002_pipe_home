"""Synchronisation du module Tâches (Google Tasks ; Apple Rappels en phase 5).

Partage du travail : le fil de synchronisation fait le RÉSEAU et ne fait que LIRE la base (`engine.py`) ; ce qu'il
rapporte est fusionné dans le fil de l'interface (`merge.py`) puis écrit par le fil d'écriture du service. Les
tâches en mémoire restent ainsi la seule référence, et deux fils n'écrivent jamais la même ligne."""
