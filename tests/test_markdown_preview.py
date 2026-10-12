"""Notes Markdown rendues avec le CSS d'Obsidian (markdown_preview) : syntaxe Obsidian, coffre et
son apparence, extraction de app.css depuis l'archive d'Obsidian. Sans QtWebEngine (HTML seul)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import markdown_preview as mp


@unittest.skipUnless(mp.available(), "markdown-it-py absent")
class MarkdownPageTest(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.vault, True)
        settings = self.vault / ".obsidian"
        (settings / "snippets").mkdir(parents=True)
        (settings / "appearance.json").write_text(json.dumps({
            "theme": "obsidian", "accentColor": "#5ca6f5", "textFontFamily": "Inter", "baseFontSize": 16,
            "enabledCssSnippets": ["second", "absent", "premier"]}), encoding="utf-8")
        (settings / "snippets" / "premier.css").write_text("h1 { color: red; }", encoding="utf-8")
        (settings / "snippets" / "second.css").write_text("h2 { color: blue; }", encoding="utf-8")
        (settings / "snippets" / "inactif.css").write_text("p { color: green; }", encoding="utf-8")
        (self.vault / "images").mkdir()
        (self.vault / "images" / "photo.png").write_bytes(b"\x89PNG")
        (self.vault / "Autre note.md").write_text("x", encoding="utf-8")
        self.note = self.vault / "dossier" / "note.md"
        self.note.parent.mkdir()

    def page(self, text: str) -> str:
        self.note.write_text(text, encoding="utf-8")
        with mock.patch.object(mp, "obsidian_assets", return_value=None):
            return mp.render_page(self.note)

    def test_vault_appearance_and_enabled_snippets_in_order(self):
        page = self.page("# Titre")
        self.assertEqual(mp.vault_for(self.note), self.vault)
        sheets = [Path(p).name for p in mp.vault_stylesheets(self.vault, json.loads(
            (self.vault / ".obsidian" / "appearance.json").read_text()))]
        self.assertEqual(sheets, ["second.css", "premier.css"])    # ordre d'Obsidian, inactifs et absents exclus
        self.assertLess(page.index("second.css"), page.index("premier.css"))
        self.assertNotIn("inactif.css", page)
        self.assertIn("theme-dark", page)
        self.assertIn("--accent-h: 211", page)
        self.assertIn("--font-text-override: 'Inter'", page)
        self.assertIn("--font-text-size: 16px", page)
        self.assertIn('class="markdown-preview-view markdown-rendered', page)
        self.assertIn('<div class="el-h1"><h1>Titre</h1>', page)

    def test_obsidian_syntax(self):
        page = self.page(
            "Lien [[Autre note|vers l'autre]], manquant [[Inconnue]], image ![[photo.png|200]]\n"
            "==fluo== #projet/pipe https://exemple.org/page. %%secret%%\n\n"
            "```py\n[[pas un lien]] ==pas fluo==\n```\n\n"
            "> [!tip]+ Astuce **utile**\n> contenu\n\n> citation simple\n")
        self.assertIn('class="internal-link">vers l&#x27;autre</a>', page)
        self.assertIn('class="internal-link is-unresolved">Inconnue</a>', page)
        self.assertIn('width="200"', page)
        self.assertIn((self.vault / "images" / "photo.png").resolve().as_uri(), page)
        self.assertIn("<mark>fluo</mark>", page)
        self.assertIn('class="tag">#projet/pipe</a>', page)
        self.assertIn('href="https://exemple.org/page"', page)            # sans le point final
        self.assertNotIn("secret", page)
        self.assertIn("[[pas un lien]] ==pas fluo==", page)               # rien dans le code
        self.assertIn('data-callout="tip"', page)
        self.assertIn('is-collapsible"', page)
        self.assertIn('callout-title-inner">Astuce <strong>utile</strong>', page)
        self.assertIn("<blockquote>", page)                              # une citation reste une citation

    def test_properties(self):
        page = self.page("---\ntype: memo\ntags:\n  - a\n  - b\n---\nTexte")
        self.assertIn('data-property-key="type"', page)
        self.assertIn(">a, b<", page)
        self.assertNotIn("type: memo", page)


class OpenInObsidianTest(unittest.TestCase):
    """Double-clic sur une note d'un coffre : Obsidian s'ouvre SUR elle (obsidian://open?path=...) ; une note
    hors de tout coffre garde son logiciel. Jamais Obsidian lance ici."""

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


class ObsidianAssetsTest(unittest.TestCase):
    """app.css et public/ extraits d'une archive asar (format d'Electron), une seule fois."""

    def test_extract_from_asar(self):
        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, True)
        files = {"app.css": b"body { color: red; }", "public/fonts/a.woff2": b"FONT", "app.js": b"js"}
        blobs, tree, offset = b"", {"files": {}}, 0
        for name, data in files.items():
            node = tree
            parts = name.split("/")
            for part in parts[:-1]:
                node = node["files"].setdefault(part, {"files": {}})
            node["files"][parts[-1]] = {"size": len(data), "offset": str(offset)}
            blobs += data
            offset += len(data)
        header = json.dumps(tree).encode()
        asar = work / "obsidian.asar"
        asar.write_bytes(struct.pack("<4I", 4, len(header) + 8, len(header) + 4, len(header)) + header + blobs)
        with mock.patch.object(mp, "obsidian_asar", return_value=asar), \
                mock.patch.object(mp, "CACHE_DIR", work / "cache"):
            assets = mp.obsidian_assets()
            self.assertEqual((assets / "app.css").read_bytes(), files["app.css"])
            self.assertEqual((assets / "public" / "fonts" / "a.woff2").read_bytes(), b"FONT")
            self.assertFalse((assets / "app.js").exists())
            self.assertEqual(mp.obsidian_assets(), assets)              # deja extrait : reutilise


if __name__ == "__main__":
    unittest.main()
