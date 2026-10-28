"""Module CAD du board (paquet fm_cad/) : dessin technique (lignes, arcs, cotes, hachures, textes), accrochage,
commandes à la AutoCAD, import / export DXF / DWG, rendu GPU. Se branche sur la coque fm_board/.
Garder ce fichier MINIMAL : fm_board et fm_cad dépendent encore l'un de l'autre (cycle chargeable tant qu'aucun
__init__ n'importe ses sous-modules). Carte : docs/agents/fm_cad.md."""
