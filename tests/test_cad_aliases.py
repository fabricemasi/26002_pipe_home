"""Alias de commandes d'un fichier .pgp d'AutoCAD (board/cad_aliases.py) : couche pure, sans fenetre."""
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401  (jamais les vrais reglages de l'utilisateur)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from board import cad_aliases, cad_commands  # noqa: E402

PGP = (";  FABRICE\r\n;  =======\r\n\r\nA,         \t*AJUSTER\r\nAI,        \t*AIRE\r\n\r\nC,   *COPIER\r\n"
       "CE,  *CERCLE\r\nD,   *DEPLACER\r\nDC,  *DECALER\r\nL,   *LIGNE\r\nLL,  *POLYLIGN\r\nM,   *MIROIR\r\n"
       "P,   *PROLONGE\r\nRG,  *REGEN\r\nRD,  *RACCORD\r\nV,   *MATCHPROP\r\n;;;;;J\r\n-B,  *-BLOC\r\n")


class PgpAliasesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "acad.pgp")
        self.write(PGP.encode("cp1252"))

    def tearDown(self):
        cad_aliases.install("")
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, raw: bytes):
        with open(self.path, "wb") as handle:
            handle.write(raw)

    def test_parse_skips_comments_and_blank_lines(self):
        parsed = cad_aliases.parse(PGP)
        self.assertEqual([a for a, _c, _n in parsed][:4], ["A", "AI", "C", "CE"])
        self.assertEqual({a: c for a, c, _n in parsed}["-B"], "-BLOC")

    def test_commands_are_mapped_to_the_apps_commands(self):
        loaded = cad_aliases.load(self.path)
        by_alias = {a.alias: a for a in loaded.entries}
        self.assertEqual((by_alias["L"].target, by_alias["L"].state), ("LINE", cad_aliases.AVAILABLE))
        self.assertEqual(by_alias["CE"].target, "CIRCLE")
        self.assertEqual(by_alias["D"].target, "MOVE")
        self.assertEqual(by_alias["DC"].target, "OFFSET")
        self.assertEqual(by_alias["LL"].target, "PLINE")
        self.assertEqual(by_alias["RD"].target, "FILLET")
        self.assertEqual(by_alias["V"].target, "MATCHPROP")
        self.assertEqual(by_alias["RG"].target, "REGEN")
        self.assertEqual((by_alias["A"].target, by_alias["A"].state), ("TRIM", cad_aliases.AVAILABLE))
        self.assertEqual((by_alias["P"].target, by_alias["P"].state), ("EXTEND", cad_aliases.PLANNED))
        self.assertEqual(by_alias["P"].target, "EXTEND")                       # nom francais propre a AutoCAD
        self.assertEqual(by_alias["AI"].state, cad_aliases.UNKNOWN)            # AIRE : pas d'equivalent
        self.assertEqual(by_alias["-B"].state, cad_aliases.UNKNOWN)
        self.assertIn("alias", loaded.summary())
        self.assertIn("Sans équivalent", loaded.report())

    def test_installed_aliases_come_first_and_originals_stay(self):
        self.assertEqual(cad_commands.lookup("C").name, "CIRCLE")              # d'origine
        cad_aliases.install(self.path)
        self.assertEqual(cad_commands.lookup("C").name, "COPY")                # le fichier passe avant
        self.assertEqual(cad_commands.lookup("a").name, "TRIM")                # prevue : annoncee, A n'est plus l'arc
        self.assertEqual(cad_commands.lookup("M").name, "MIRROR")
        self.assertEqual(cad_commands.lookup("LINE").name, "LINE")             # les noms entiers restent
        self.assertEqual(cad_commands.lookup("EL").name, "ELLIPSE")            # alias d'origine non cite : garde
        self.assertEqual([w for w, _e in cad_commands.completions("DC")][0], "DC")
        cad_aliases.install("")
        self.assertEqual(cad_commands.lookup("C").name, "CIRCLE")              # retire : retour a l'origine

    def test_unknown_command_never_hides_a_builtin_alias(self):
        self.write(b"E, *INCONNUE\r\n")
        cad_aliases.install(self.path)
        self.assertEqual(cad_commands.lookup("E").name, "ERASE")

    def test_changed_file_is_read_again_and_bad_files_are_reported(self):
        cad_aliases.install(self.path)
        time.sleep(0.02)
        self.write(b"C, *CERCLE\r\n")
        self.assertTrue(cad_aliases.refresh())
        self.assertEqual(cad_commands.lookup("C").name, "CIRCLE")
        self.assertFalse(cad_aliases.refresh())                                # rien de change
        self.assertTrue(cad_aliases.load(os.path.join(self.folder, "absent.pgp")).error)
        self.write(b"rien d'utile ici\r\n")
        self.assertIn("aucun alias", cad_aliases.load(self.path).error)

    def test_the_users_file_is_readable_when_present(self):
        real = r"F:\SYNC\Sync\PIPELINE\bib\autocad\CONFIG\acad.pgp"
        if not os.path.isfile(real):
            self.skipTest("fichier de l'utilisateur absent")
        loaded = cad_aliases.load(real)
        self.assertFalse(loaded.error)
        self.assertGreater(loaded.count(cad_aliases.AVAILABLE), 8)


if __name__ == "__main__":
    unittest.main()
