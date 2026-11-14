import _isolate  # noqa: F401 -- aucune ecriture dans les reglages reels
"""Contrat OBSERVE du pont Lightroom, fige avant la mission photo (docs/agents/fm_photo.md, « Contrat Lightroom »).

Ce que l'appli echange REELLEMENT avec Lightroom Classic, et rien de plus :
- LECTURE directe du catalogue (SQLite, lecture seule) : identite (uuid, id local), note, libelle de couleur,
  drapeau, mots cles, orientation, revision de developpement ;
- ECRITURE seulement par le module SDK, a travers une file de fichiers `requests/<id>.req` (9 champs en
  hexadecimal separes par des tabulations) et `replies/<id>.json` ; champs ecrits : note, couleur, drapeau,
  mots cles. Aucun reglage de developpement n'est ecrit ; seul le NOM du profil est lu (op `profile`).
Un catalogue jouet, dans un dossier temporaire : aucun vrai catalogue n'est ouvert."""
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import lightroom_bridge

_app = QApplication.instance() or QApplication([])

UUID = "0F0E0D0C-1111-2222-3333-444455556666"
FIELDS = ("id", "op", "uuid", "field", "before", "value", "target", "collection", "catalog")


class _Catalogue(unittest.TestCase):
    """Dossier associe + catalogue jouet au schema que lit `_catalog_photo`."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.folder = self.base / "Photos" / "2026"
        self.folder.mkdir(parents=True)
        self.photo = self.folder / "DSCF0001.RAF"
        self.photo.write_bytes(b"raw")
        self.catalog = self.base / "cat.lrcat"
        (self.base / "Photos" / lightroom_bridge.MARKER).write_text(
            json.dumps({"catalog": str(self.catalog)}), encoding="utf-8")
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.executescript("""
                CREATE TABLE AgLibraryRootFolder (id_local INTEGER, absolutePath TEXT);
                CREATE TABLE AgLibraryFolder (id_local INTEGER, pathFromRoot TEXT, rootFolder INTEGER);
                CREATE TABLE AgLibraryFile (id_local INTEGER, folder INTEGER, idx_filename TEXT, modTime);
                CREATE TABLE Adobe_images (id_global TEXT, id_local INTEGER, rootFile INTEGER, rating,
                    colorLabels TEXT, pick, fileFormat TEXT, developSettingsIDCache, orientation TEXT);
                CREATE TABLE AgLibraryKeyword (id_local INTEGER, name TEXT);
                CREATE TABLE AgLibraryKeywordImage (image INTEGER, tag INTEGER);
            """)
            db.execute("INSERT INTO AgLibraryRootFolder VALUES (1, ?)", (str(self.base / "Photos") + "/",))
            db.execute("INSERT INTO AgLibraryFolder VALUES (1, '2026/', 1)")
            db.execute("INSERT INTO AgLibraryFile VALUES (10, 1, 'DSCF0001.RAF', 123.5)")
            db.execute("INSERT INTO Adobe_images VALUES (?, 77, 10, 4, 'Rouge', -1, 'RAW', 9001, 'BC')", (UUID,))
            db.executemany("INSERT INTO AgLibraryKeyword VALUES (?, ?)", [(1, "portrait"), (2, "studio")])
            db.executemany("INSERT INTO AgLibraryKeywordImage VALUES (77, ?)", [(1,), (2,)])
        self.cache = self.base / "cache"
        for name in ("requests", "replies", "images", "errors"):
            (self.cache / name).mkdir(parents=True)
        self.plugin = self.base / "plugin"
        lightroom_bridge._metadata_cache.clear()
        self.addCleanup(lightroom_bridge._metadata_cache.clear)
        self.addCleanup(self._close_connections)
        for patcher in (patch.object(lightroom_bridge, "_cache_root", return_value=self.cache),
                        patch.object(lightroom_bridge, "PLUGIN", self.plugin)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _close_connections(self):
        conns = lightroom_bridge._db_local.__dict__.get("catalogs", {})
        for key in [key for key in conns if Path(key) == self.catalog]:
            conns.pop(key).close()

    def _digest(self):
        return hashlib.sha256(self.catalog.read_bytes()).hexdigest()


class LectureDuCatalogueTest(_Catalogue):
    def test_identite_et_revision_lues_dans_le_catalogue(self):
        photo = lightroom_bridge._catalog_photo(self.catalog, self.photo)
        self.assertEqual(photo["uuid"], UUID)                 # identite stable de la photo cote Lightroom
        self.assertEqual(photo["local_id"], 77)
        self.assertEqual(photo["revision"], "9001:123.5")     # reglages de developpement : fichier modifie
        self.assertEqual(photo["orientation"], "BC")
        self.assertEqual(photo["format"], "RAW")
        self.assertEqual(lightroom_bridge.orientation(self.photo), "BC")

    def test_attributs_lightroom_sous_les_cles_de_l_appli(self):
        self.assertEqual(lightroom_bridge.attributes(self.photo),
                         {"rating": 4, "color": 1, "keywords": ["portrait", "studio"], "status": "delete"})

    def test_libelle_personnalise_traduit_par_la_table_du_sdk(self):
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("UPDATE Adobe_images SET colorLabels='À livrer', pick=1")
        (self.cache / "status.json").write_text(json.dumps(
            {"catalog": str(self.catalog), "labels": {"green": "A livrer"}}), encoding="utf-8")
        found = lightroom_bridge.attributes(self.photo)
        self.assertEqual((found["color"], found["status"]), (3, "keep"))

    def test_photo_absente_du_catalogue_attributs_neutres(self):
        other = self.folder / "absente.jpg"
        other.write_bytes(b"x")
        self.assertEqual(lightroom_bridge.attributes(other),
                         {"rating": 0, "color": 0, "keywords": [], "status": ""})

    def test_dossier_non_associe_ne_dit_rien(self):
        lone = self.base / "Ailleurs" / "photo.jpg"
        lone.parent.mkdir()
        lone.write_bytes(b"x")
        self.assertIsNone(lightroom_bridge.attributes(lone))
        with patch.object(lightroom_bridge._pool, "submit") as submit:
            lightroom_bridge.write_attributes(lone, {"rating": 5})
        submit.assert_not_called()

    def test_le_catalogue_n_est_jamais_modifie(self):
        before = self._digest()
        lightroom_bridge.attributes(self.photo)
        lightroom_bridge.orientation(self.photo)
        with patch.object(lightroom_bridge._pool, "submit"):
            lightroom_bridge.write_attributes(self.photo, {"rating": 1, "color": 2, "status": "keep",
                                                           "keywords": ["x"]})
        self.assertEqual(self._digest(), before)
        db = lightroom_bridge._db_local.__dict__["catalogs"][self.catalog]
        with self.assertRaises(sqlite3.Error):                 # connexion gardee : lecture seule
            db.execute("UPDATE Adobe_images SET rating=5")


class EcritureParLeSdkTest(_Catalogue):
    def _commands(self, changes):
        with patch.object(lightroom_bridge._pool, "submit") as submit:
            lightroom_bridge.write_attributes(self.photo, changes)
        for call in submit.call_args_list:
            self.assertIs(call.args[0], lightroom_bridge._write_attribute)
            self.assertEqual(call.args[1:4], (self.photo, self.catalog, UUID))
        return [call.args[4:6] for call in submit.call_args_list]

    def test_valeurs_envoyees_au_sdk(self):
        self.assertEqual(self._commands({"rating": 3}), [("rating", "3")])
        self.assertEqual(self._commands({"rating": 0}), [("rating", "")])           # 0 = note effacee
        self.assertEqual(self._commands({"color": 2}), [("color", "yellow")])       # nom standard, pas le libelle
        self.assertEqual(self._commands({"color": 0}), [("color", "")])
        self.assertEqual(self._commands({"status": "keep"}), [("status", "1")])
        self.assertEqual(self._commands({"status": "delete"}), [("status", "-1")])
        self.assertEqual(self._commands({"status": ""}), [("status", "0")])
        self.assertEqual(self._commands({"keywords": [" studio ", "", "a\nb", "portrait"]}),
                         [("keywords", "studio\nportrait")])
        self.assertEqual(self._commands({"inconnu": 1}), [])                        # rien d'autre n'est ecrit

    def test_une_commande_par_attribut_et_connexion_du_module(self):
        fields = [field for field, _ in self._commands({"rating": 2, "color": 5, "status": "", "keywords": []})]
        self.assertEqual(fields, ["rating", "color", "status", "keywords"])
        lines = (self.plugin / "connection.txt").read_text(encoding="ascii").split()
        self.assertEqual([bytes.fromhex(line).decode("utf-8") for line in lines],
                         [str(self.cache), str(self.catalog)])

    def _plugin(self, answer, seen):
        """Joue le module SDK : lit la requete, repond, comme `Start.lua`."""
        def run():
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                requests = list((self.cache / "requests").glob("*.req"))
                if requests:
                    line = requests[0].read_text(encoding="ascii")
                    seen["name"] = requests[0].stem
                    seen["raw"] = line
                    (self.cache / "replies" / f"{requests[0].stem}.json").write_text(
                        json.dumps(answer), encoding="utf-8")
                    return
                time.sleep(.02)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def _signals(self):
        got = {"updated": [], "failed": []}
        bus = lightroom_bridge._signal_bus()
        on_updated = lambda path, field: got["updated"].append((path, field))
        on_failed = lambda path, text: got["failed"].append((path, text))
        bus.updated.connect(on_updated)
        bus.failed.connect(on_failed)
        self.addCleanup(bus.updated.disconnect, on_updated)
        self.addCleanup(bus.failed.disconnect, on_failed)
        return got

    def test_requete_set_neuf_champs_hex_puis_confirmation(self):
        lightroom_bridge._catalog_photo(self.catalog, self.photo)               # remplit le cache d'attributs
        got, seen = self._signals(), {}
        thread = self._plugin({"ok": True}, seen)
        lightroom_bridge._write_attribute(self.photo, self.catalog, UUID, "rating", "5", "00000000000000000001_abcd1234")
        thread.join(5)
        self.assertTrue(seen["raw"].endswith("\n"))
        tokens = seen["raw"].rstrip("\n").split("\t")
        self.assertEqual(len(tokens), len(FIELDS))                               # « Version de protocole inconnue » sinon
        command = dict(zip(FIELDS, (bytes.fromhex(token).decode("utf-8") for token in tokens)))
        self.assertEqual(command, {"id": "00000000000000000001_abcd1234", "op": "set", "uuid": UUID,
                                   "field": "rating", "before": "", "value": "5", "target": "",
                                   "collection": "", "catalog": str(self.catalog)})
        self.assertEqual(seen["name"], command["id"])
        self.assertEqual(got["updated"], [(str(self.photo), "rating")])
        self.assertEqual(got["failed"], [])
        self.assertEqual(lightroom_bridge._metadata_cache, {})                   # relu dans le catalogue ensuite
        self.assertEqual(list((self.cache / "requests").iterdir()), [])          # file nettoyee
        self.assertEqual(list((self.cache / "replies").iterdir()), [])

    def test_refus_du_sdk_signale_sans_rien_ecrire_ailleurs(self):
        before = self._digest()
        got, seen = self._signals(), {}
        thread = self._plugin({"error": "Le catalogue actif a changé"}, seen)
        lightroom_bridge._write_attribute(self.photo, self.catalog, UUID, "color", "red", "00000000000000000002_abcd1234")
        thread.join(5)
        self.assertEqual(got["updated"], [])
        self.assertEqual(len(got["failed"]), 1)
        self.assertIn("Le catalogue actif a changé", got["failed"][0][1])
        self.assertEqual(self._digest(), before)
        self.assertEqual(list((self.cache / "requests").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
