# Module PDF de PIPE FMZ (`fm_pdf/`) — suivi et rapport de mission

Mission (2026-11-06) : éditeur PDF professionnel intégré au Board et à la barre de navigation, priorité absolue aux
formulaires XFA (« Please wait… ») et à la CRÉATION de formulaires AcroForm remplissables dans Acrobat Reader.
Carte technique, pièges, mesures : `docs/agents/fm_pdf.md`.

## 1. Architecture retenue et moteurs

- **PDFium compilé avec V8 + XFA** (pdfium-binaries chromium/8076, `fm_pdf/native/pdfium.dll`, empreinte
  SHA-256 vérifiée = celle publiée par GitHub ; installé par `python tools/install_pdfium_xfa.py`), piloté par les
  bindings ctypes de pypdfium2 5.14.0 (même révision). Rendu, texte, recherche, formulaires AcroForm ET XFA
  (mise en page dynamique, JavaScript et FormCalc), enregistrement.
- **Un fil unique du moteur** (`worker.py`) : file à priorités (saisie > enregistrement > tuiles visibles >
  voisines > miniatures > fond), annulation, minuteries de PDFium ; ctypes rend le GIL : rendu en parallèle de
  l'interface. Tuiles rendues directement dans des `QImage` (aucune copie).
- **Écriture** : PyMuPDF (conception AcroForm, annotations, pages, caviardage, OCR en couche texte), pikepdf / qpdf
  (structure, mises à jour incrémentales, optimisation), pyHanko (signatures), OCR intégré à Windows (fr-FR, en-US).
- Composants isolés (un fichier par responsabilité, 34 fichiers) : détecteur / moteur (`engine`), formulaires
  (`formfill`, `acroform`), réparations XFA (`xfa_packets`, `xfa_save`, `incremental`), édition (`content`),
  annotations (`annots`), pages (`pages`), OCR (`ocr`), sécurité / signatures (`security`), export / impression,
  cache (`tiles`), session (`session`), vue (`view`), éditeur (`pane`) et outils.

## 2. Raisons des choix

PDFium V8/XFA est le seul moteur libre, local et gratuit qui exécute réellement les XFA dynamiques (pdf.js en
JavaScript seulement dans un navigateur, MuPDF / Qt PDF / pypdf / pikepdf : aucun XFA ; SDK commerciaux évités
puisqu'une solution libre fonctionne). PyMuPDF génère des apparences de champs et d'annotations conformes, lues par
tous les lecteurs. Aucun abonnement, aucune action réseau (sauf l'installation du moteur, vérifiée).

## 3. Fonctionnalités opérationnelles (prouvées par tests)

Lecture (continu, page, double page, ajuster largeur / page, 100 %, zoom fluide, rotation de vue, mode lecture,
plein écran, miniatures, signets, historique Alt+←/→, aller à la page / étiquette, recherche casse / mot / accents,
sélection et copie, liens avec accord) ; formulaires AcroForm et XFA au clavier (Tab / Maj+Tab, cases, radios,
listes, calculs, validations, champs obligatoires vides listés) ; **conception de formulaires AcroForm** (mode
distinct, 10 types, glisser au point près, poignées, flèches ±1 pt / 10 pt, alignement, distribution, même taille,
duplication, ordre de tabulation par clics, propriétés : nom, info-bulle, obligatoire, lecture seule, valeurs, police,
taille, couleurs, bordure, alignement, longueur, choix, export, décimales, devise, format de date, min / max, calcul
simple ou script, validation, action de bouton ; test immédiat en Remplissage) ; édition réelle du contenu (texte,
images, formes, couleurs, ordre, suppression) ; annotations (13 outils, auteur, date, couleur, épaisseur, opacité,
panneau des commentaires) ; pages (insérer, vierge, supprimer, dupliquer, déplacer au Ctrl + glisser, pivoter,
recadrer, extraire, fusionner, diviser, numéros, en-tête / pied, filigrane) ; OCR asynchrone annulable avec relecture
et couche texte invisible ; caviardage réel vérifié ; chiffrement AES-256, retrait du chiffrement et des métadonnées ;
signature visuelle (dite non cryptographique) et numérique (pyHanko) + vérification ; impression ; exports (PNG,
JPEG, TIFF, texte, PDF optimisé, pages, PDF aplati sur demande) ; enregistrement transactionnel vérifié, conflit de
fichier modifié ailleurs, copie de secours ; réglages « PDF » (aussi dans « Réglages : Board ») appliqués à chaud.
Intégration : bouton et cadre « PDF » de la barre de navigation, double-clic sur un .pdf, menu « Ouvrir dans
l'éditeur PDF », module « PDF » de la barre des modules du Board (élément lié + éditeur plein cadre).
Board, 2026-11-06 (demande de l'utilisateur) : le document s'affiche dans l'élément avec TOUTES ses pages (XFA réel,
plus la page « Please wait… ») et s'édite sur place quand le module est actif ; barres « Document » et « Affichage »
(pleine page, pleine largeur, plein écran) ; mesures dans `docs/agents/fm_pdf.md` (« Mesures », Board).

## 4. Compatibilité AcroForm et XFA

| Cas | État | Preuve |
|---|---|---|
| PDF ordinaire, multipage (300 pages) | testé, fonctionnel | `test_pdf_engine`, sonde |
| PDF protégé par mot de passe | testé, fonctionnel | `test_password_protected` |
| PDF endommagé / tronqué | testé : erreur propre, aucun plantage | `test_damaged_and_truncated` |
| PDF numérisé (OCR) | testé, fonctionnel | `OcrTest` |
| PDF avec annotations | testé, fonctionnel | `AnnotsTest`, `test_pdf_pane` |
| PDF signé numériquement (signature, vérification, altération détectée) | testé, fonctionnel | `test_sign_verify_and_detect_later_change` |
| Polices incorporées (sous-ensemble) à l'édition | testé : repli explicite | `test_missing_glyphs_fall_back_to_a_standard_font` |
| AcroForm : création, saisie au clavier, Tab, calcul, case, radio, listes, enregistrement, réouverture, relecture MuPDF | testé, fonctionnel | `test_pdf_forms`, `test_pdf_pane`, `test_pdf_view` |
| XFA dynamique : contenu réel au lieu de « Please wait… » | testé, fonctionnel | ACIA (chiffré AES-128, droits /Perms), IRCC IMM 1344 |
| XFA dynamique : saisie, Tab / Maj+Tab, enregistrement complet ET incrémental, réouverture, données exactes | testé, fonctionnel | `XfaFillTest`, `XfaImm1344Test` (lent) |
| XFA : scripts, calculs, validations | partiel : exécutés par PDFium (validation visible sur l'IMM 1344) ; pas de test dédié | — |
| XFA : pagination dynamique | partiel : mise en page 10 -> 14 pages gérée ; ajout de sections par bouton non testé | — |
| XFA statique (XFAF) | non testé (aucun fichier) | — |
| XFA : recherche / sélection de texte | non pris en charge | — |
| Lecture dans Acrobat | VÉRIFIÉ PAR L'UTILISATEUR (2026-11-06) : les fichiers créés et remplis par le module (`tmp_shot/acrobat/cree_par_pipe.pdf`, `xfa_rempli_par_pipe.pdf`) s'ouvrent et fonctionnent dans Acrobat | essai manuel de l'utilisateur ; `tools/acrobat_crosscheck.py` (COM refusé sur cette machine) |

## 5. Performances mesurées (vraie fenêtre, `tools/probe_pdf_latency.py`)

Ouverture 300 pages 196 ms (rendu net 291 ms) ; changement de page 79 ms ; image de défilement 5,6 ms (pire 11,7) ;
cran de zoom 13,4 ms, net 192 ms après ; frappe AcroForm 11,5 ms, XFA 29 ms (ACIA) / 45 ms (IMM 1344) ; ouverture
XFA IMM 1344 8,6 s (6,3 s dans PDFium, interface libre) ; mémoire stable (éditeur 0,64 Mo par ouverture / fermeture).

## 6. Principales optimisations (avant -> après)

Frappe : focus confirmé par le moteur au clic (506 -> 11,5 ms AcroForm, 602 -> 45 ms XFA) ; zoom : tuiles étirées
pendant le geste, rendu net après 120 ms ; tuiles hors écran annulées ; invalidations regroupées (une seule
re-tuile en vol) ; miniature floue avant les tuiles d'une page sautée ; rendu sans copie dans les QImage ; fuite des
rappels annulés supprimée ; caches libérés à la fermeture (21 -> 0,64 Mo par cycle).

## 7. Tests exécutés

`python tests/run.py fm_pdf --lent` : 11 fichiers, ~42 tests, tous verts (engine 6, forms 6, xfa 6 dont IMM 1344,
view 2, pane 3, content 4, tools 8, board 1, settings 2, app 1 lent). Non-régression : coque du Board + fenêtre de
réglages 145 tests verts, fm_font 8, barre de navigation 17 (+16 lents sautés), fm_markdown : 1 échec SANS LIEN
(`test_md_live_preview.test_font_color_remains_applied…`, couleur de l'aperçu Markdown) signalé, non examiné.

## 8. Limitations résiduelles

Voir `docs/agents/fm_pdf.md`, « Limites réelles » : XFA sans couche texte ni
conception, XFA statique non testé, révocation des certificats non vérifiée, DOCX / PDF-A non proposés, ouverture
lourde des très gros XFA, édition de texte objet par objet (pas de réagencement de paragraphe), barres de l'éditeur
fixes (pas encore les barres flottantes fm_theme).

## 9. Dépendances et licences

PDFium (BSD-3), V8 (BSD-3), pypdfium2 5.14.0 (Apache-2.0 / BSD-3), pikepdf (MPL-2.0) + qpdf (Apache-2.0),
**PyMuPDF (AGPL-3.0 : sans contrainte pour un usage personnel ; distribution = obligations AGPL ou licence
commerciale Artifex)**, cryptography (Apache-2.0 / BSD), pyHanko (MIT), pywinrt « winrt-* » (MIT, OCR de Windows),
pywin32 (PSF, outil Acrobat seulement). DLL V8 (31 Mo) hors git (`.gitignore`), installée par l'outil.

## 10. Lignes de code

Ajoutées : `fm_pdf/` 9 045 lignes (34 fichiers), tests 1 366 (11 fichiers), outils 899, mixin de la fenêtre 169,
documentation 214. Modifiées (crochets) : ~90 lignes dans 19 fichiers (fenêtre principale, coque du Board, réglages,
icône de la barre).

## 11. Non-régression

Voir 7. Aucun commit n'a été fait (dépôt partagé avec d'autres travaux non enregistrés).

## 12. Lancement

```
python tools/install_pdfium_xfa.py --check        # moteur XFA présent ? (sinon : sans --check pour l'installer)
pip install -r requirements.txt                    # pypdfium2==5.14.0, pikepdf, PyMuPDF, cryptography (+ pyhanko, winrt-* pour signatures / OCR)
python pipeline_browser.py                         # double-clic sur un .pdf, ou bouton « PDF » de la barre
python tests/run.py fm_pdf [--lent]
QT_QPA_PLATFORM=windows python tools/probe_pdf_latency.py
```
