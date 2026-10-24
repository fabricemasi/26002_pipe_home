"""Rendu des notes Markdown (markdown_preview) : syntaxe des notes, images et liens resolus depuis la note, page de
l'inspecteur habillee par la feuille du module Markdown ; ouverture dans l'application Obsidian."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import markdown_preview as mp


@unittest.skipUnless(mp.available(), "markdown-it-py absent")
class MarkdownRenderTest(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.vault, True)
        (self.vault / ".obsidian").mkdir()
        (self.vault / "images").mkdir()
        (self.vault / "images" / "photo.png").write_bytes(b"\x89PNG")
        (self.vault / "Autre note.md").write_text("x", encoding="utf-8")
        self.note = self.vault / "dossier" / "note.md"
        self.note.parent.mkdir()
        (self.note.parent / "img").mkdir()
        (self.note.parent / "img" / "local image.jpg").write_bytes(b"\xff\xd8")
        mp.forget_index()

    def body(self, text: str) -> str:
        self.note.write_text(text, encoding="utf-8")
        return mp.render_body(self.note, text)

    def test_note_syntax(self):
        html = self.body(
            "Lien [[Autre note|vers l'autre]], manquant [[Inconnue]], image ![[photo.png|200]]\n"
            "==fluo== #projet/pipe https://exemple.org/page. %%secret%%\n\n"
            "```py\n[[pas un lien]] ==pas fluo==\n```\n\n"
            "> [!tip]+ Astuce **utile**\n> contenu\n\n> citation simple\n")
        self.assertIn('class="internal-link">vers l&#x27;autre</a>', html)
        self.assertIn('class="internal-link is-unresolved">Inconnue</a>', html)
        self.assertIn('width="200"', html)
        self.assertIn((self.vault / "images" / "photo.png").resolve().as_uri(), html)   # trouvee par son nom
        self.assertIn("<mark>fluo</mark>", html)
        self.assertIn('class="tag" data-tag="projet/pipe">#projet/pipe</a>', html)
        self.assertIn('href="https://exemple.org/page"', html)            # sans le point final
        self.assertNotIn("secret", html)
        self.assertIn("[[pas un lien]] ==pas fluo==", html)               # rien dans le code
        self.assertIn('class="language-py"', html)
        self.assertIn('data-callout="tip"', html)
        self.assertIn('is-collapsible"', html)
        self.assertIn('callout-title-inner">Astuce <strong>utile</strong>', html)
        self.assertIn("<blockquote>", html)                              # une citation reste une citation

    def test_relative_images_and_links_resolve_from_the_note(self):
        html = self.body("![vue|320](img/local%20image.jpg) ![absente](img/rien.png) [lien](../Autre%20note.md)\n"
                         "![[local image.jpg]]")
        url = (self.note.parent / "img" / "local image.jpg").resolve().as_uri()
        self.assertIn(f'src="{url}" alt="vue" width="320"', html)          # sous-dossier, largeur « |320 »
        self.assertIn('md-image-missing">img/rien.png', html)
        self.assertIn('data-href="../Autre%20note.md"', html)             # la reference d'origine reste
        self.assertIn((self.vault / "Autre note.md").resolve().as_uri(), html)
        self.assertEqual(html.count(url), 2)

    def test_properties(self):
        html = self.body("---\ntype: memo\ntags:\n  - a\n  - b\n---\nTexte")
        self.assertIn("<th>type</th><td>memo</td>", html)
        self.assertIn("<td>a, b</td>", html)
        self.assertNotIn("type: memo", html)

    def test_inspector_page_uses_the_module_style(self):
        self.note.write_text("# Titre\n\n```python\nx = 1\n```\n", encoding="utf-8")
        page = mp.render_page(self.note, settings={"md_h1_font_color": "#ff112233"})
        self.assertIn("base.css", page)
        self.assertIn("--md-h1-color: var(--h1-color, #112233ff);", page)   # couleur de l'appli -> CSS (Obsidian d'abord)
        self.assertIn("MD.highlightAll", page)                            # coloration des blocs de code
        page = mp.render_page(self.note, "Sans code", settings={})
        self.assertNotIn("codemirror.js", page)                          # CodeMirror seulement si besoin


class OpenInObsidianTest(unittest.TestCase):
    """Double-clic sur une note d'un coffre (reglage « Application Obsidian ») : Obsidian s'ouvre SUR elle
    (obsidian://open?path=...) ; une note hors de tout coffre garde son logiciel. Jamais Obsidian lance ici."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.appdata = self.dir / "appdata"
        (self.appdata / "obsidian").mkdir(parents=True)
        patcher = mock.patch.dict(os.environ, {"APPDATA": str(self.appdata)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_note_inside_a_vault(self):
        vault = self.dir / "Coffre"
        (vault / ".obsidian").mkdir(parents=True)
        note = vault / "Projets" / "Ma note.md"
        note.parent.mkdir()
        note.write_text("# x", encoding="utf-8")
        url = mp.obsidian_open_url(note)
        self.assertTrue(url.startswith("obsidian://open?path="))
        from urllib.parse import unquote
        self.assertEqual(Path(unquote(url.split("=", 1)[1])), note.resolve())

    def test_registered_vault_without_local_marker(self):
        vault = self.dir / "Declare"
        vault.mkdir()
        (self.appdata / "obsidian" / "obsidian.json").write_text(
            json.dumps({"vaults": {"a": {"path": str(vault), "open": True}}}), encoding="utf-8")
        note = vault / "n.md"
        note.write_text("x", encoding="utf-8")
        self.assertIsNotNone(mp.obsidian_open_url(note))

    def test_note_outside_any_vault(self):
        other = self.dir / "ailleurs" / "n.md"
        other.parent.mkdir()
        other.write_text("x", encoding="utf-8")
        vault = self.dir / "Coffre"
        (vault / ".obsidian").mkdir(parents=True)
        (self.appdata / "obsidian" / "obsidian.json").write_text(
            json.dumps({"vaults": {"a": {"path": str(vault), "open": True}}}), encoding="utf-8")
        self.assertIsNone(mp.obsidian_open_url(other))               # pas de repli sur le coffre ouvert
        self.assertIsNone(mp.obsidian_open_url(vault / "image.png"))


if __name__ == "__main__":
    unittest.main()
