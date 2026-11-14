"""Contrôleur de poursuite de la mission audio (`tools/hooks/audio_music_guard.py`, `audio_music_registry.py`) :
les HOOKS sont lancés comme Claude Code les lance (sous-processus, JSON sur stdin, verdict sur stdout / code de
sortie), sur un registre FICTIF dans un dossier temporaire (jamais le vrai registre, ni les modules)."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(ROOT, "tools", "hooks", "audio_music_guard.py")
SESSION = "sess-A"


def registry(tasks, requirements=None):
    reqs = requirements or [{"id": "R-1", "title": "exigence 1", "phase": "P0", "validations": {"automatic": True}}]
    return {"schema_version": 1, "mission_id": "test", "requirements": reqs, "tasks": tasks, "evidence": [],
            "blockers": [], "decisions": [], "next_action": ""}


def task(tid, status="todo", req="R-1", **extra):
    return dict({"id": tid, "requirement": req, "phase": "P0", "title": tid, "kind": "code", "status": status,
                 "depends_on": [], "criteria": [], "paths": [], "blocker": None, "next_action": f"faire {tid}"}, **extra)


class GuardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="am_guard_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = os.path.join(self.tmp, "state.json")
        self.env = dict(os.environ, PIPE_AUDIO_MUSIC_STATE=self.state, PIPE_AUDIO_MUSIC_ROOT=self.tmp,
                        PIPE_AUDIO_MUSIC_RUNS_DIR=os.path.join(self.tmp, "runs"),
                        PIPE_AUDIO_MUSIC_CONFIRM=os.path.join(self.tmp, "confirm.json"),
                        CLAUDE_CODE_SESSION_ID=SESSION)
        self.env.pop("PIPE_AUDIO_MUSIC_RUN", None)

    def write(self, data):
        with open(self.state, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def read(self):
        with open(self.state, encoding="utf-8") as handle:
            return json.load(handle)

    def set_status(self, tid, status, **extra):
        data = self.read()
        for t in data["tasks"]:
            if t["id"] == tid:
                t.update(status=status, **extra)
        self.write(data)

    def cli(self, *args, env=None):
        proc = subprocess.run([sys.executable, "-S", GUARD, *args], capture_output=True, env=env or self.env,
                              cwd=self.tmp)
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")

    def hook(self, name, session=SESSION, **event):
        payload = json.dumps(dict(session_id=session, hook_event_name=name, **event)).encode("utf-8")
        proc = subprocess.run([sys.executable, "-S", GUARD, name], input=payload, capture_output=True,
                              env=self.env, cwd=self.tmp)
        out = proc.stdout.decode("utf-8").strip()
        return proc.returncode, out, proc.stderr.decode("utf-8")

    def stop(self, session=SESSION, active=False):
        code, out, _err = self.hook("stop", session=session, stop_hook_active=active)
        self.assertEqual(code, 0)
        return json.loads(out) if out else {}

    def armed(self):
        self.assertEqual(self.cli("arm", "--run-id", "r1")[0], 0)
        self.assertEqual(self.cli("bind", "--run-id", "r1")[0], 0)

    def prove(self, tid, *files, code=0):
        args = ["run", "--task", tid]
        for f in files:
            args += ["--file", f]
        return self.cli(*args, "--", sys.executable, "-c", f"import sys; print('Ran 2 tests'); sys.exit({code})")

    def touch(self, name, text):
        with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as handle:
            handle.write(text)


class StopHookTest(GuardCase):
    def test_actionable_task_blocks_stop_even_with_stop_hook_active(self):
        self.write(registry([task("T-1"), task("T-2", depends_on=["T-1"])]))
        self.armed()
        verdict = self.stop()
        self.assertEqual(verdict["decision"], "block")
        self.assertIn("faire T-1", verdict["reason"])
        self.set_status("T-1", "in_progress")                 # progrès -> on continue, même stop_hook_active
        self.assertEqual(self.stop(active=True)["decision"], "block")

    def test_two_increments_then_complete(self):
        self.touch("a.py", "x = 1\n")
        self.write(registry([task("T-1", paths=["a.py"]), task("T-2", depends_on=["T-1"])]))
        self.armed()
        self.assertIn("T-1", self.stop()["reason"])
        self.assertEqual(self.prove("T-1")[0], 0)
        self.set_status("T-1", "implemented")
        self.assertIn("faire T-2", self.stop(active=True)["reason"])      # enchaîne sur la tâche suivante
        self.prove("T-2")
        self.set_status("T-2", "implemented")
        verdict = self.stop(active=True)
        self.assertNotIn("decision", verdict)
        self.assertIn("toutes les exigences", verdict["systemMessage"])

    def test_stale_evidence_requires_new_proof(self):
        self.touch("a.py", "x = 1\n")
        self.write(registry([task("T-1", paths=["a.py"])]))
        self.armed()
        self.prove("T-1")
        self.set_status("T-1", "implemented")
        self.assertNotIn("decision", self.stop())
        self.touch("a.py", "x = 22\n")                          # taille changée : périmée
        verdict = self.stop()
        self.assertEqual(verdict["decision"], "block")
        self.assertIn("re-prouver T-1", verdict["reason"])
        code, _out, err = self.hook("task", task_id="1", task_subject="[T-1] tâche")
        self.assertEqual(code, 2)
        self.assertIn("stale", err)

    def test_hardware_validation_pending_allows_stop_but_not_complete(self):
        reqs = [{"id": "R-1", "title": "guitare", "phase": "P3", "validations": {"automatic": True, "hardware": True}}]
        self.write(registry([task("T-1"), task("T-H", kind="hardware")], reqs))
        self.armed()
        self.prove("T-1")
        self.set_status("T-1", "implemented")
        verdict = self.stop()
        self.assertNotIn("decision", verdict)
        self.assertIn("INACHEVÉE", verdict["systemMessage"])
        self.assertEqual(self.hook("prompt", prompt="VALIDE R-1 matériel")[0], 0)   # confirmation de l'utilisateur
        self.assertIn("toutes les exigences", self.stop()["systemMessage"])

    def test_stalled_task_redirects_to_independent_task_then_limit(self):
        self.write(registry([task("T-1"), task("T-2")]))
        self.armed()
        reasons = [self.stop(active=True)["reason"] for _ in range(4)]   # le 1er arrêt sert de référence
        self.assertIn("faire T-1", reasons[0])
        self.assertIn("T-1 : 3 arrêts sans progrès", reasons[3])
        self.assertIn("faire T-2", reasons[3])                # tâche indépendante proposée
        self.assertIn("T-2", self.stop(active=True)["reason"])
        self.stop(active=True)
        verdict = self.stop(active=True)                       # 6 arrêts sans aucun progrès
        self.assertNotIn("decision", verdict)
        self.assertIn("limit_reached", verdict["systemMessage"])

    def test_documented_blocker_lets_session_stop_unfinished(self):
        self.write(registry([task("T-1")]))
        self.armed()
        for _ in range(4):
            last = self.stop(active=True)
        self.assertIn("aucune autre tâche", last["reason"])
        self.set_status("T-1", "blocked", blocker="licence ASIO à choisir par l'utilisateur")
        verdict = self.stop(active=True)
        self.assertNotIn("decision", verdict)
        self.assertIn("INACHEVÉE", verdict["systemMessage"])

    def test_truncated_registry_bounded_repair(self):
        self.write(registry([task("T-1")]))
        self.armed()
        with open(self.state, "w", encoding="utf-8") as handle:
            handle.write('{"schema_version": 1, "tasks": [')
        for i in range(3):
            verdict = self.stop()
            self.assertEqual(verdict["decision"], "block")
            self.assertIn("invalide", verdict["reason"])
        verdict = self.stop()
        self.assertNotIn("decision", verdict)
        self.assertIn("INVALIDE", verdict["systemMessage"])

    def test_foreign_session_disarm_and_user_stop(self):
        self.write(registry([task("T-1")]))
        self.armed()
        self.assertEqual(self.stop(session="autre"), {})       # autre conversation : jamais retenue
        self.assertEqual(self.cli("bind", "--run-id", "r1", env=dict(self.env, CLAUDE_CODE_SESSION_ID="B"))[0], 1)
        self.assertEqual(self.hook("prompt", prompt="STOP MISSION, j'ai besoin du poste")[0], 0)
        self.assertIn("arrêt demandé", self.stop()["systemMessage"])
        self.cli("arm", "--run-id", "r1")                       # réarmement explicite
        self.assertEqual(self.stop()["decision"], "block")
        self.cli("disarm", "--run-id", "r1")
        self.assertEqual(self.stop(), {})

    def test_env_variable_binds_first_session_and_counters_survive(self):
        self.write(registry([task("T-1")]))
        self.cli("arm", "--run-id", "r1")
        self.env["PIPE_AUDIO_MUSIC_RUN"] = "r1"
        self.assertEqual(self.stop()["decision"], "block")     # liée au premier session_id
        self.assertEqual(self.stop(session="autre"), {})       # second écrivain : pas forcé
        code, out, _err = self.hook("context", session="autre")
        self.assertIn("déjà lié à une autre session", out)
        self.cli("disarm", "--run-id", "r1")
        self.cli("arm", "--run-id", "r1")
        _code, out, _err = self.cli("status", "--run-id", "r1")
        self.assertIn("arrêts=1", out)                         # compteurs conservés à la reprise
        self.assertIn("sans_progrès=0", out)


class VerifierAndRunnerTest(GuardCase):
    def test_false_status_and_structure_problems(self):
        reqs = [{"id": "R-1", "title": "a", "phase": "P0"}, {"id": "R-2", "title": "sans tâche", "phase": "P0"}]
        data = registry([task("T-1", status="implemented"), task("T-2", depends_on=["T-3"]),
                         task("T-3", depends_on=["T-2"])], reqs)
        data["evidence"].append({"id": "E-x", "task": "T-1", "returncode": 0, "files": {}})
        self.write(data)
        code, out, _err = self.cli("check")
        self.assertEqual(code, 1)
        for text in ("R-2 : exigence sans tâche", "cyclique", "non produite par le runner"):
            self.assertIn(text, out)
        self.assertEqual(self.cli("arm", "--run-id", "r1")[0], 1)    # contrôleur jamais armé sur registre invalide

    def test_removed_requirement_and_doc_only_tasks_do_not_validate(self):
        data = registry([task("T-1", kind="doc")])
        data["baseline_requirements"] = ["R-1", "R-9"]
        self.write(data)
        self.assertIn("R-9 : exigence du périmètre initial RETIRÉE", self.cli("check")[1])
        data["baseline_requirements"] = ["R-1"]
        self.write(data)
        self.prove("T-1")
        self.set_status("T-1", "implemented")
        out = self.cli("check")[1]
        self.assertIn("verdict=blocked", out)                  # une décomposition documentée ne valide pas R-1
        self.assertIn("exigences validées 0/1", out)

    def test_runner_records_evidence_and_refuses_forbidden_commands(self):
        self.touch("a.py", "x = 1\n")
        self.write(registry([task("T-1", paths=["a.py"])]))
        self.assertEqual(self.prove("T-1", code=3)[0], 3)
        ev = self.read()["evidence"][-1]
        self.assertEqual((ev["returncode"], ev["tests_run"], ev["runner"]), (3, 2, True))
        self.assertIn("a.py", ev["files"])
        code, _out, err = self.cli("run", "--task", "T-1", "--", sys.executable, "tests/run.py")
        self.assertEqual(code, 2)
        self.assertIn("garde_fous", err)
        self.set_status("T-1", "implemented")                   # preuve en échec seulement : faux statut
        self.assertIn("faux statut", self.cli("check")[1])

    def test_task_completed_hook_and_refresh(self):
        self.touch("a.py", "x = 1\n")
        self.write(registry([task("T-1", paths=["a.py"]), task("T-H", kind="human")]))
        self.armed()
        self.assertEqual(self.hook("task", task_id="9", task_subject="[T-1] code")[0], 2)    # pas encore prouvée
        self.prove("T-1")
        self.set_status("T-1", "implemented")
        self.assertEqual(self.hook("task", task_id="9", task_subject="[T-1] code")[0], 0)
        self.assertEqual(self.hook("task", task_id="8", task_subject="[T-H] écoute")[0], 2)
        self.assertEqual(self.hook("task", task_id="7", task_subject="tâche libre")[0], 0)
        later = time.time() + 5
        os.utime(os.path.join(self.tmp, "a.py"), (later, later))  # même contenu, date changée (synchro)
        self.assertEqual(self.hook("task", task_id="9", task_subject="[T-1] code")[0], 2)
        self.assertIn("1 empreinte", self.cli("check", "--refresh")[1])
        self.assertEqual(self.hook("task", task_id="9", task_subject="[T-1] code")[0], 0)

    def test_run_specific_registry_paths(self):
        """Run d'essai : son registre fictif est imposé aux hooks et au runner, sans variable d'environnement."""
        sub = os.path.join(self.tmp, "essai")
        os.makedirs(sub)
        with open(os.path.join(sub, "f1.txt"), "w", encoding="utf-8") as handle:
            handle.write("1")
        with open(os.path.join(sub, "state.json"), "w", encoding="utf-8") as handle:
            json.dump(registry([task("T-9", paths=["f1.txt"])]), handle)
        self.write(registry([task("T-1")]))                       # « vrai » registre, à ne pas toucher
        env = {k: v for k, v in self.env.items() if k not in ("PIPE_AUDIO_MUSIC_STATE", "PIPE_AUDIO_MUSIC_ROOT")}
        self.assertEqual(self.cli("arm", "--run-id", "essai", "--state", os.path.join(sub, "state.json"),
                                  "--root", sub, env=env)[0], 0)
        self.assertEqual(self.cli("bind", "--run-id", "essai", env=env)[0], 0)
        self.env = env
        self.assertIn("faire T-9", self.stop()["reason"])
        code, _out, _err = self.cli("run", "--run-id", "essai", "--task", "T-9", "--", sys.executable, "-c",
                                    "assert open('f1.txt').read() == '1'")
        self.assertEqual(code, 0)
        venv = os.path.relpath(sys.executable, ROOT)              # exécutable relatif au DÉPÔT (essais réels A/B)
        if not venv.startswith(".."):
            code, _out, _err = self.cli("run", "--run-id", "essai", "--task", "T-9", "--", venv, "-c", "pass")
            self.assertEqual(code, 0)
        with open(os.path.join(sub, "state.json"), encoding="utf-8") as handle:
            self.assertIn("f1.txt", json.load(handle)["evidence"][-1]["files"])
        self.assertEqual(self.read()["evidence"], [])

    def test_hooks_are_inert_without_armed_run(self):
        self.write(registry([task("T-1")]))
        self.assertEqual(self.stop(), {})
        self.assertEqual(self.hook("context")[1], "")
        self.assertEqual(self.hook("task", task_subject="[T-1]")[0], 0)


if __name__ == "__main__":
    unittest.main()
