"""Synchronisation de l'agenda (aucun widget) :
- `provider`    interface d'une source distante (Google aujourd'hui, serveur personnel demain) et ses erreurs ;
- `credentials` jetons dans le Gestionnaire d'identifiants Windows (jamais dans un fichier de réglages) ;
- `oauth`       OAuth 2.0 pour application installée (navigateur du système, boucle locale 127.0.0.1, PKCE) ;
- `google`      client de l'API Google Calendar v3 (HTTP, reprises avec attente exponentielle) et correspondance
                des champs ;
- `engine`      moteur générique : réception (jeton de synchronisation incrémentale, 410), envoi (file persistante,
                idempotent), fusion à trois voies et conflits, provenance (anti-boucles) ;
- `manager`     pilotage depuis l'interface : fil de synchronisation, minuteries, comptes, état."""
