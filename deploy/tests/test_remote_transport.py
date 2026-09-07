"""Remote bootstrap consumes long source and JSON without long SSH arguments."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import static_sync


class RemoteTransportTests(unittest.TestCase):
    def test_long_unicode_source_and_request_round_trip(self):
        original_run = subprocess.run
        request = {"value": "引号'\"\\\n" * 10000}
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "remote.py"
            script.write_text("# " + "long source " * 10000 + "\nimport sys,json\nprint(json.dumps(json.load(sys.stdin)))", encoding="utf-8")

            def emulate_remote(args, **kwargs):
                self.assertLess(len(args[-1]), 200)
                command = shlex.split(args[-1])
                self.assertEqual(command[:3], ["sudo", "-n", "python3"])
                return original_run([sys.executable, *command[3:]], **kwargs)

            with patch.object(static_sync.subprocess, "run", side_effect=emulate_remote):
                result = static_sync.remote_python("example", script, request, sudo=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), request)

    def test_remote_failure_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "remote.py"
            script.write_text("raise RuntimeError('probe')", encoding="utf-8")
            failure = subprocess.CompletedProcess([], 1, "", "remote failure")
            with patch.object(static_sync.subprocess, "run", return_value=failure):
                self.assertIs(static_sync.remote_python("example", script, {}), failure)


if __name__ == "__main__":
    unittest.main()
