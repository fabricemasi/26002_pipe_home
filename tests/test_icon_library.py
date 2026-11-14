"""Bibliothèque d'icônes et couleur dynamique des modules (fm_theme.icon_colors, fm_theme.icon_library,
browser_core_parts.settings.apply_module_icon_colors) : dominante = couleur du module dans les réglages, tons dérivés
en OKLCH, substitution limitée aux attributs fill / stroke, monochrome et icônes générales intacts, cache purgé pour
le seul module changé. Bibliothèque temporaire : jamais le vrai dossier d'iconographie."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from fm_theme import icon_colors, icon_library

PALETTE = {"bleu": "#78A9E8", "cyan": "#65C6DF", "orange": "#E8B477", "violet": "#B29ADD", "rouge": "#E88F94",
           "vert": "#74C69D", "jaune": "#E6CA78", "neutre": "#CCD4DF", "encre": "#263444"}
REF_CAD = icon_colors.derive(PALETTE["orange"])


def _svg(*parts: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">'
            + "".join(parts) + "</svg>")


class IconColorsTest(unittest.TestCase):
    def test_reference_rendue_au_chiffre_pres(self):
        for name, value in PALETTE.items():
            if name != "encre":
                self.assertEqual(icon_colors.derive(value)["module"], value, name)

    def test_extremes_lisibles_et_teinte_gardee(self):
        for value in ("#1a237e", "#000000", "#ffffff", "#00ff00", "#ff0000", "#fffde0", "#e0604f"):
            roles = icon_colors.derive(value)
            for role in roles.values():
                self.assertRegex(role, r"^#[0-9A-F]{6}$")
            module = roles["module"]
            self.assertGreaterEqual(icon_colors.contraste(module, icon_colors.FOND), 3.5, value)
            self.assertGreaterEqual(icon_colors.contraste(module, icon_colors.ENCRE), 3.0, value)
            L, C, h = icon_colors.oklch(value)
            Lm, Cm, hm = icon_colors.oklch(module)
            if C > 0.05:                                     # teinte perçue conservée (couleur reconnaissable)
                self.assertLess(abs((hm - h + 180) % 360 - 180), 4, value)
            Lc, Ls = icon_colors.oklch(roles["module_clair"])[0], icon_colors.oklch(roles["module_sombre"])[0]
            self.assertGreater(Lc, Lm)
            self.assertGreater(Lm - Ls, 0.12, value)            # ombre nettement distincte de la dominante

    def test_recolorer_seulement_fill_et_stroke(self):
        raw = _svg('<path d="M0 0 H10" fill="#e8b477" stroke="#263444"/>',
                   '<rect x="1" y="1" width="2" height="2" fill="#E8B477"/>').encode()
        out = icon_library.recolorer(raw, {"#E8B477": "#00FF00"}).decode()
        self.assertEqual(out.count('fill="#00FF00"'), 2)
        self.assertIn('stroke="#263444"', out)
        self.assertNotIn("ns0", out)                         # espace de noms SVG par défaut conservé


class IconLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        doc = root / "documentation"
        doc.mkdir()
        icons = [
            ("modules/cad/conge_01", "cad", "modules/cad/conge_01.svg",
             _svg(f'<path d="M0 0 H512" fill="none" stroke="{PALETTE["orange"]}"/>',
                  f'<circle cx="9" cy="9" r="9" fill="{REF_CAD["module_sombre"]}"/>',
                  f'<rect x="1" y="1" width="9" height="9" fill="{PALETTE["neutre"]}"/>')),
            ("modules/photoshop/masque_01", "photoshop", "modules/photoshop/masque_01.svg",
             _svg(f'<rect x="0" y="0" width="512" height="512" fill="{PALETTE["violet"]}"/>')),
            ("general/recherche_01", "general", "recherche_01.svg",
             _svg(f'<circle cx="256" cy="256" r="200" fill="{PALETTE["bleu"]}"/>')),
            ("general/supprimer_01", "general", "supprimer_01.svg",
             _svg(f'<rect x="0" y="0" width="512" height="512" fill="{PALETTE["rouge"]}"/>')),
        ]
        entries = []
        for id_logique, module, fichier, body in icons:
            for style in icon_library.STYLES:
                path = root / style / fichier
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body if style == icon_library.COULEUR else body.replace(PALETTE["orange"], "#FFFFFF"),
                                encoding="utf-8")
            entries.append({"id_logique": id_logique, "module": module, "fichier": fichier,
                            "disponibilite": {s: True for s in icon_library.STYLES}})
        (doc / "manifest_icons.json").write_text(json.dumps({"palette": PALETTE, "icones": entries}), encoding="utf-8")
        (doc / "modules.json").write_text(json.dumps({"modules": {
            "cad": {"accent": "orange"}, "photoshop": {"accent": "violet"}, "general": {"accent": "bleu"}}}),
            encoding="utf-8")
        icon_library.configure(None)
        icon_library.configure(root)
        self.addCleanup(icon_library.configure, None)
        self.addCleanup(icon_library._couleurs.clear)
        icon_library._couleurs.clear()

    def _centre(self, id_logique, **kw):
        return QColor(icon_library.pixmap(id_logique, 32, **kw).toImage().pixel(16, 16)).name().upper()

    def test_chemins_du_rangement(self):
        # Rangement du 13 novembre 2026 : `chemins` par style (icones/module <id>/<nom>_<nn>_m|c.svg) prioritaire.
        root = Path(self.tmp.name)
        cible = root / "icones" / "module cad" / "conge_01_c.svg"
        cible.parent.mkdir(parents=True)
        cible.write_text(_svg('<rect x="0" y="0" width="9" height="9" fill="#FFFFFF"/>'), encoding="utf-8")
        e = icon_library.entree("modules/cad/conge_01")
        self.addCleanup(e.pop, "chemins", None)
        e["chemins"] = {icon_library.COULEUR: "icones/module cad/conge_01_c.svg",
                        icon_library.MONOCHROME: "icones/module cad/conge_01_m.svg"}
        self.assertEqual(icon_library.chemin("modules/cad/conge_01"), cible)

    def test_sans_couleur_le_fichier_tel_quel(self):
        raw = icon_library.svg_bytes("modules/cad/conge_01")
        self.assertEqual(raw, icon_library.chemin("modules/cad/conge_01").read_bytes())

    def test_couleur_du_module_et_tons_derives(self):
        icon_library.set_module_colors({"cad": "#6fa8ff"})
        roles = icon_colors.derive("#6fa8ff")
        out = icon_library.svg_bytes("modules/cad/conge_01").decode()
        self.assertIn(f'stroke="{roles["module"]}"', out)
        self.assertIn(f'fill="{roles["module_sombre"]}"', out)
        self.assertIn(f'fill="{PALETTE["neutre"]}"', out)       # neutre : jamais lié au module
        mono = icon_library.svg_bytes("modules/cad/conge_01", style="flat monochrome").decode()
        self.assertNotIn(roles["module"], mono)

    def test_un_changement_ne_touche_que_son_module(self):
        seen = []
        icon_library.on_change(seen.append)
        self.addCleanup(icon_library.remove_listener, seen.append)
        before_ps = icon_library.pixmap("modules/photoshop/masque_01", 32)
        icon_library.pixmap("modules/cad/conge_01", 24)
        self.assertEqual(icon_library.set_module_colors({"cad": "#00aa00", "photoshop": None}), {"cad"})
        self.assertEqual(seen, [{"cad"}])
        self.assertIs(icon_library.pixmap("modules/photoshop/masque_01", 32), before_ps)   # cache gardé
        self.assertEqual(icon_library.set_module_colors({"cad": "#00AA00"}), set())        # sans effet : rien
        self.assertEqual(seen, [{"cad"}])

    def test_retour_a_la_couleur_precedente(self):
        self.assertEqual(self._centre("modules/photoshop/masque_01"), PALETTE["violet"])
        icon_library.set_module_colors({"photoshop": "#3366ff"})
        self.assertEqual(self._centre("modules/photoshop/masque_01"), icon_colors.derive("#3366ff")["module"])
        icon_library.set_module_colors({"photoshop": None})                                 # annulation
        self.assertEqual(self._centre("modules/photoshop/masque_01"), PALETTE["violet"])

    def test_icones_generales_et_semantiques(self):
        icon_library.set_module_colors({"cad": "#00aa00"})
        green = icon_colors.derive("#00aa00")["module"]
        self.assertEqual(self._centre("general/recherche_01"), PALETTE["bleu"])             # jamais globalement
        self.assertEqual(self._centre("general/recherche_01", contexte="cad"), green)       # contexte explicite
        self.assertEqual(self._centre("general/supprimer_01", contexte="cad"), PALETTE["rouge"])   # sémantique

    def test_pixmap_haute_densite(self):
        pix = icon_library.pixmap("modules/cad/conge_01", 24, dpr=1.5)
        self.assertEqual((pix.width(), pix.height()), (36, 36))
        self.assertAlmostEqual(pix.devicePixelRatio(), 1.5)


    def test_cadre_cache_et_couleur_locale(self):
        cad = "modules/cad/conge_01"
        photoshop = "modules/photoshop/masque_01"
        icon_library.set_module_colors({"cad": "#3D7BFF"})
        cadre = icon_library.pixmap_cadre(cad, 32, 2)
        autre = icon_library.pixmap_cadre(photoshop, 32, 2)
        self.assertEqual(cadre.devicePixelRatio(), 2)
        self.assertIs(icon_library.pixmap_cadre(cad, 32, 2), cadre)
        local = icon_library.pixmap_cadre(cad, 32, 2, couleur_module="#FFFFFF")
        self.assertNotEqual(cadre.toImage(), local.toImage())
        icon_library.set_module_colors({"cad": "#2FBF71"})
        self.assertIsNot(icon_library.pixmap_cadre(cad, 32, 2), cadre)
        self.assertIs(icon_library.pixmap_cadre(photoshop, 32, 2), autre)


class ModuleIconColorSettingsTest(unittest.TestCase):
    def test_reglages_existants_blanc_telle_quelle(self):
        from browser_core_parts.settings import MODULE_ICON_COLOR_KEYS, apply_module_icon_colors
        from settings_store import DEFAULT_SETTINGS
        pushed = {}
        original = icon_library.set_module_colors
        icon_library.set_module_colors = lambda colors: pushed.update(colors) or set()
        self.addCleanup(setattr, icon_library, "set_module_colors", original)
        self.addCleanup(icon_library.configure, None)
        apply_module_icon_colors(dict(DEFAULT_SETTINGS, board_modulebar_color_cad="#00ff00",
                                      navtool_icon_color_viewer="#ffffff"))
        self.assertEqual(set(pushed), set(MODULE_ICON_COLOR_KEYS))
        self.assertEqual(pushed["cad"], "#00FF00")
        self.assertIsNone(pushed["viewer"])                                     # blanc : icône telle quelle
        for key in MODULE_ICON_COLOR_KEYS.values():
            self.assertIn(key, DEFAULT_SETTINGS)                                # une clé EXISTANTE par module


class StyleInterfaceTest(unittest.TestCase):
    """Thème > Général > « Style des icônes » (`icon_library_style`, 2026-11-13) : flat monochrome ou flat couleur."""

    def setUp(self):
        self.addCleanup(icon_library.set_interface_style, icon_library._style_interface, icon_library._encre)

    def test_bascule_et_abonnes(self):
        seen = []
        icon_library.on_change(seen.append)
        self.addCleanup(icon_library.remove_listener, seen.append)
        icon_library.set_interface_style("couleur", "#c4cacf")
        seen.clear()
        self.assertEqual(icon_library.style_affiche(), icon_library.COULEUR)
        self.assertTrue(icon_library.set_interface_style("monochrome", "#c4cacf"))
        self.assertFalse(icon_library.set_interface_style("monochrome", "#c4cacf"))        # inchangé : rien
        self.assertEqual(icon_library.style_affiche(), icon_library.MONOCHROME)
        self.assertEqual(icon_library.style_affiche(False), icon_library.MONOCHROME)       # grisée : toujours
        self.assertEqual(len(seen), 1)
        self.assertIn("cad", seen[0])                                                      # TOUS les modules
        self.assertTrue(icon_library.set_interface_style("monochrome", "#ff0000"))         # couleur des icônes
        self.assertEqual(icon_library.encre_defaut(), "#ff0000")

    def test_reglage_declare(self):
        import fm_theme.presets as tp
        from settings_store import DEFAULT_SETTINGS
        self.assertEqual(DEFAULT_SETTINGS["icon_library_style"], "monochrome")
        self.assertIn("icon_library_style", tp.GENERAL_KEYS)


class IconePersoSvgTest(unittest.TestCase):
    """Icône perso choisie en SVG (demande de l'utilisateur, 2026-11-13) : gardée vectorielle (<clé>.svg), prioritaire
    sur un PNG, rendue à la taille demandée."""

    def test_svg_prioritaire_et_rendu(self):
        from unittest import mock
        from preview_services import icons, mtime
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        with mock.patch.object(icons, "CUSTOM_SOFTWARE_ICON_DIR", folder):
            key = "ui_board_cad_erase"
            svg, png = icons.custom_icon_files(key)
            self.assertEqual(icons.custom_software_icon_path(key), png)          # rien : le PNG (absent)
            svg.write_text(_svg('<rect x="64" y="64" width="384" height="384" fill="#FFFFFF"/>'), encoding="utf-8")
            mtime.forget_mtime(svg)
            self.assertEqual(icons.custom_software_icon_path(key), svg)
            pix = icons.custom_ui_icon_pixmap(key, 24)
            self.assertIsNotNone(pix)
            self.assertEqual((pix.width(), pix.height()), (24, 24))
            self.assertEqual(icons.load_icon_image(svg, 24).width(), 96)       # rendu à 4 x la taille


class BranchementsTest(unittest.TestCase):
    """Commandes de l'interface branchées sur une icône officielle du catalogue (identifiants seulement : aucun accès
    au vrai dossier d'iconographie)."""

    def test_commandes_du_catalogue(self):
        from fm_board.bars import BoardTool
        from preview_column import IconButton
        self.assertEqual(IconButton("find", "#c4cacf", "#ffffff")._library_icon, "general/recherche_02")
        self.assertEqual(BoardTool("design_delete", "Supprimer")._svg_id, "general/supprimer_02")
        self.assertEqual(BoardTool("cad_erase", "Effacer")._svg_id, "modules/cad/gomme_01")    # gomme du CAD

    def test_bouton_glyphe_icone_et_secours(self):
        from fm_board.ui import _GlyphButton
        icon_library.configure(None)                         # bibliothèque absente : le glyphe reste peint
        self.addCleanup(icon_library.configure, None)
        button = _GlyphButton("plus", "Nouveau calque", None, 26)
        before = button.paint_key()
        button.set_library_icon("general/ajouter_02")
        self.assertNotEqual(button.paint_key(), before)      # image gardée refaite à l'arrivée de l'icône
        self.assertFalse(button.grab().isNull())


if __name__ == "__main__":
    unittest.main()
