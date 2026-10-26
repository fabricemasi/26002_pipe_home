"""Module « Board » (demande de l'utilisateur) : tableau blanc infini facon Miro, LOCAL et personnel (aucun reseau,
aucun compte). Un board est un fichier `.mro` (JSON) ; ses images sont copiees dans un dossier cache a cote
(`<nom>_assets`).

Couches (chacune n'importe que les precedentes) :
- `model` : schema du fichier (types d'elements, valeurs par defaut, normalisation) ;
- `serialization` : lecture / ecriture fidele et atomique, dossier des images ;
- `items` : elements de la scene (post-it, texte, forme, image, trait, cadre, connecteur) ;
- `commands` : annulation (QUndoStack, une commande « etat avant / apres » pour tout changement) ;
- `scene` : la scene (grille de points, aimantation, guides, copier / coller) ;
- `view` : la vue (zoom autour du curseur, deplacement, outils a la souris et au clavier) ;
- `export` : PNG / SVG / PDF ; `cad_export` / `cad_import` : dessins DXF / DWG du module CAD ;
- `ui` : `BoardPane`, le board pose sur la zone des colonnes de la fenetre principale (barre d'outils flottante,
  barre de style de la selection, zoom).

Orchestration dans `PipelineBrowser._open_board` / `_close_board` ; ce paquet ne depend d'aucun code propre a la
fenetre principale."""
from .model import EXTENSION, empty_board  # noqa: F401
from .cad_import import is_cad_drawing  # noqa: F401
from .serialization import create_board_file, is_board_file  # noqa: F401
