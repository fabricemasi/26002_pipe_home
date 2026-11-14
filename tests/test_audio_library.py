"""Bibliothèque commune et workflow obligatoire : prise dans FM Audio -> traitement -> publication v1
-> insertion dans FM Music -> réouverture de la source dans FM Audio -> publication v2 ->
proposition dans FM Music -> adoption (annulable) ou refus explicite ; cas du cloud (manifeste
tronqué, fichier pas encore arrivé, copie de conflit), médias absents, reliaison, collecte."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import _isolate  # noqa: F401

import numpy as np

from fm_audio_engine import client, dsp_offline, library, wavio
from fm_audio_engine.project import Clip, Project, Track, compile_spec

SR = 48000


class LibraryWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.lib = library.Library(self.dir / "biblio")
        rng = np.random.default_rng(3)
        t = np.arange(SR * 2) / SR
        take = (0.4 * np.sin(2 * np.pi * 220 * t) + rng.standard_normal(t.size) * 0.03).astype(np.float32)
        take[:SR // 2] = (rng.standard_normal(SR // 2) * 0.03).astype(np.float32)
        self.take = wavio.write(self.dir / "prise_voix.wav", take[None, :], SR)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_workflow_v1_v2_adopt_refuse(self):
        # FM Audio : traitement de la prise (réduction de bruit), publication v1
        x, _ = wavio.read(self.take)
        clean, _ = dsp_offline.noise_reduce(x, x[:, :SR // 2])
        v1_file = wavio.write(self.dir / "voix_v1.wav", clean, SR)
        rid, n1 = self.lib.publish(v1_file, "Voix", "prise", recipe={"op": "noise_reduce"}, source=None)
        self.assertEqual(n1, 1)
        self.assertTrue(self.take.exists())                                 # source jamais déplacée
        # FM Music : insertion épinglée sur r1, arrangement (décalage, fondus)
        music = Project("music", "Morceau")
        tr = music.add_track(Track(name="Voix"))
        c = library.insert(music, self.lib, rid, tr.id, start=SR)
        with music.edit("arranger", tr.id):
            c.offset, c.length, c.fade_in, c.fade_out = 4800, int(SR * 1.5), 480, 4800
        self.assertEqual(library.pending_updates(music, self.lib), [])
        # FM Audio : réouverture de la SOURCE de r1, nouveau traitement plus court, publication v2
        src_r1 = self.lib.revision_path(rid, 1, verify=True)
        y, _ = wavio.read(src_r1)
        v2 = dsp_offline.time_stretch(y, 0.6)                               # durée changée : 1,2 s
        v2_file = wavio.write(self.dir / "voix_v2.wav", v2, SR)
        _, n2 = self.lib.publish(v2_file, resource=rid, recipe={"op": "time_stretch", "factor": 0.6}, source=(rid, 1))
        self.assertEqual(n2, 2)
        self.assertEqual([n for _, n, _ in self.lib.lineage(rid)], [2, 1])
        # FM Music : proposition, adoption annulable, arrangement non détruit
        (prop,) = library.pending_updates(music, self.lib)
        self.assertEqual((prop["current"], prop["proposed"]), (1, 2))
        before = music.to_dict()
        rep = library.adopt(music, self.lib, tr.id, c.id)
        c2 = music.track(tr.id).clips[0]
        self.assertEqual((c2.revision, c2.start, c2.offset), (2, SR, 4800))
        self.assertEqual(c2.length, int(SR * 1.2) - 4800)                    # réduit à ce qui existe
        self.assertTrue(rep["adjusted"])
        self.assertEqual(c2.fade_in, 480)
        music.history.undo()
        self.assertEqual(music.to_dict()["tracks"], before["tracks"])     # adoption annulée exactement
        # refus explicite : plus proposé ; nouvelle révision r3 : de nouveau proposé
        library.refuse(music, self.lib, rid, 2)
        self.assertEqual(library.pending_updates(music, self.lib), [])
        _, n3 = self.lib.publish(v1_file, resource=rid, recipe={"op": "copie"})
        self.assertEqual(library.pending_updates(music, self.lib)[0]["proposed"], n3)
        # le rendu de la composition utilise bien la révision épinglée
        if client.available()[0]:
            res = client.render_offline(compile_spec(music), self.dir / "m.wav", end=SR * 2, tail=0)
            out, _ = wavio.read(res["path"])
            self.assertGreater(float(np.max(np.abs(out[:, SR:]))), 0.1)
        # index reconstruit depuis les manifestes seuls (autre poste)
        again = library.Library(self.dir / "biblio")
        self.assertEqual(again.latest(rid), 3)
        self.assertEqual(again.manifest(rid)["projects"], [music.id])

    def test_cloud_cases(self):
        rid, _ = self.lib.publish(self.take, "Voix")
        d = self.lib.res_dir / rid
        # fichier de révision pas encore arrivé : révision en attente, non adoptable
        m = json.loads((d / "manifest.json").read_text("utf-8"))
        m["revisions"].append(dict(m["revisions"][0], n=2, file="r2.wav", sha256="00"))
        (d / "manifest.json").write_text(json.dumps(m), "utf-8")
        lib = library.Library(self.dir / "biblio")
        self.assertEqual(lib.latest(rid), 1)
        self.assertEqual(lib.latest(rid, ready_only=False), 2)
        self.assertIsNone(lib.revision_path(rid, 2))
        # copie de conflit du synchroniseur, même révision, contenu différent : signalée
        (d / "manifest (conflit de PC-2).json").write_text(json.dumps(dict(m, revisions=[dict(m["revisions"][0], sha256="ff")])), "utf-8")
        # manifeste tronqué d'une autre ressource : diagnostic, aucune erreur
        (self.lib.res_dir / "tronquee").mkdir()
        (self.lib.res_dir / "tronquee" / "manifest.json").write_text('{"id": "tronq', "utf-8")
        lib = library.Library(self.dir / "biblio")
        text = " | ".join(lib.diagnostics)
        self.assertIn("conflit", text)
        self.assertIn("CONFLIT", text)
        self.assertIn("illisible", text)
        self.assertIn(rid, lib.index)
        # contenu altéré : détecté à la vérification
        (d / "r1.wav").write_bytes((d / "r1.wav").read_bytes()[:-4] + b"\x01\x02\x03\x04")
        with self.assertRaises(library.LibraryError):
            lib.revision_path(rid, 1, verify=True)

    def test_missing_media_relink_and_collect(self):
        p = Project("audio", "Montage")
        t = p.add_track(Track(name="A"))
        with p.edit("x", t.id):
            t.clips.append(Clip(path=str(self.take), start=0, length=SR))
            t.clips.append(Clip(path=str(self.dir / "absent.wav"), start=SR, length=100))
        miss = library.missing_media(p)
        self.assertEqual([m["path"] for m in miss], [str(self.dir / "absent.wav")])
        # collecte : le projet d'origine n'est pas modifié ; l'absent reste référencé et listé
        out = library.collect(p, self.dir / "portable")
        d = json.loads(out.read_text("utf-8"))
        paths = [c["path"] for c in d["tracks"][0]["clips"]]
        self.assertTrue(paths[0].startswith(str(self.dir / "portable" / "media")))
        self.assertEqual(paths[1], str(self.dir / "absent.wav"))
        self.assertEqual(d["extensions"]["collected_missing"], [str(self.dir / "absent.wav")])
        self.assertEqual(p.tracks[0].clips[0].path, str(self.take))
        # reliaison contrôlée (contenu vérifié), annulable
        (self.dir / "trouve").mkdir()
        shutil.copy2(self.take, self.dir / "trouve" / "absent.wav")
        cands = library.find_candidates(str(self.dir / "absent.wav"), [self.dir / "trouve", self.dir / "rien"])
        self.assertEqual(len(cands), 1)
        with self.assertRaises(library.LibraryError):
            library.relink(p, str(self.dir / "absent.wav"), str(cands[0]), verify_hash="mauvais")
        self.assertEqual(library.relink(p, str(self.dir / "absent.wav"), str(cands[0])), 1)
        self.assertEqual(library.missing_media(p), [])
        p.history.undo()
        self.assertEqual(len(library.missing_media(p)), 1)


if __name__ == "__main__":
    unittest.main()
