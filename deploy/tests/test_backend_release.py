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


if __name__ == "__main__":
    unittest.main()
