"""Backend readiness and restart decisions, with no live service/database access."""

import io
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import remote_backend


class BackendReleaseTests(unittest.TestCase):
    def test_readiness_uses_real_health_contract(self):
        response = io.BytesIO(b'{"status":"ok","database":"connected"}')
        response.status = 200
        with patch.object(remote_backend.urllib.request, "urlopen", return_value=response):
            remote_backend.healthy()

    def test_database_error_is_not_healthy(self):
        response = io.BytesIO(b'{"status":"ok","database":"error"}')
        response.status = 200
        with patch.object(remote_backend.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError):
                remote_backend.healthy()

    def test_schema_change_restarts_even_when_code_is_already_at_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / ".deploy_state"
            state.mkdir()
            revision = "a" * 40
            info = {"revision":revision,"previous":revision,"schema":"137","schema_changed":True,"changed":False,"environment":None}
            (state / ("backend-prepared-" + revision + ".json")).write_text(json.dumps(info))
            def run(args, **kwargs):
                return revision if args[:2] == ["git", "rev-parse"] else ""
            with patch.object(remote_backend, "ROOT", root), patch.object(remote_backend, "STATE", state), patch.object(remote_backend, "run", side_effect=run) as command, patch.object(remote_backend, "schema_check"), patch.object(remote_backend, "healthy"), patch.object(remote_backend, "database_lock", return_value=nullcontext()):
                result = remote_backend.activate(revision)
            self.assertEqual(result["status"], "updated")
            self.assertTrue(any(call.args[0] == ["sudo","-n","systemctl","start","ark-backend"] for call in command.call_args_list))

    def exercise_colorwork_activation(self, changed=True, fail_colorwork=False, fail_backend=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = root / ".deploy_state"
            state.mkdir()
            revision = "a" * 40
            previous = "b" * 40
            info = {"revision": revision, "previous": previous, "schema": "160",
                    "schema_changed": changed, "changed": changed, "environment": None,
                    "colorwork": {"status": "prepared"}}
            (state / ("backend-prepared-" + revision + ".json")).write_text(json.dumps(info))
            events = []

            def run(args, **kwargs):
                if args[:2] == ["git", "rev-parse"]:
                    return previous
                if "activate" in args:
                    events.append("colorwork")
                    self.assertIn("backend-healthy", events)
                    if fail_colorwork:
                        raise RuntimeError("colorwork unavailable")
                if args[:3] == ["sudo", "-n", "systemctl"]:
                    events.append(args[3])
                if args[:2] == ["git", "checkout"]:
                    events.append("checkout:" + args[-1])
                return ""

            def healthy():
                if fail_backend:
                    raise RuntimeError("backend unavailable")
                events.append("backend-healthy")

            with patch.object(remote_backend, "ROOT", root), patch.object(remote_backend, "STATE", state), patch.object(remote_backend, "run", side_effect=run), patch.object(remote_backend, "schema_check"), patch.object(remote_backend, "healthy", side_effect=healthy), patch.object(remote_backend.time, "sleep"):
                if fail_colorwork or fail_backend:
                    with self.assertRaises(RuntimeError):
                        remote_backend.activate_locked(revision)
                else:
                    remote_backend.activate_locked(revision)
            if fail_backend:
                self.assertNotIn("colorwork", events)
                self.assertFalse((state / "backend-success.json").exists())
            else:
                self.assertLess(events.index("backend-healthy"), events.index("colorwork"))
                if changed:
                    self.assertLess(events.index("start"), events.index("backend-healthy"))
                    self.assertEqual(events.count("stop"), 1)
                    self.assertNotIn("checkout:" + previous, events)
                    self.assertTrue((state / "backend-success.json").exists())
                else:
                    self.assertNotIn("stop", events)

    def test_colorwork_cos_bridge_waits_for_migrated_backend(self):
        self.exercise_colorwork_activation()

    def test_unchanged_backend_is_verified_before_colorwork(self):
        self.exercise_colorwork_activation(changed=False)

    def test_colorwork_failure_keeps_verified_backend_running(self):
        self.exercise_colorwork_activation(fail_colorwork=True)

    def test_failed_backend_never_activates_colorwork(self):
        self.exercise_colorwork_activation(fail_backend=True)


if __name__ == "__main__":
    unittest.main()
