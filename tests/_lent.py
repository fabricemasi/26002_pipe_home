"""Marque des tests LENTS (Blender / Maya installés, fenêtre de réglages entièrement construite, appli
complète, sondes de fluidité) : sautés par défaut, lancés seulement sur demande.

    from _lent import lent

    @lent
    class GrosTest(unittest.TestCase): ...

Les lancer : `python tests/run.py <module> --lent` (ou `PIPELINE_TESTS_LENTS=1` avant `unittest`).
Plan : docs/agents/fm_theme.md, « Tests rapides par module »."""
import os
import unittest

ACTIFS = os.environ.get("PIPELINE_TESTS_LENTS") == "1"

lent = unittest.skipUnless(ACTIFS, "test lent : python tests/run.py <module> --lent")
