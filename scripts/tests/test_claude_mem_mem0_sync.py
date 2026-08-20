import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock


MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "memory")
MODULE_PATH = os.path.join(MEMORY_DIR, "claude_mem_mem0_sync.py")
sys.path.insert(0, MEMORY_DIR)
SPEC = importlib.util.spec_from_file_location("claude_mem_mem0_sync", MODULE_PATH)
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class Row(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


def row(obs_type, title, text=""):
    return Row(
        id=1,
        project="commission-system",
        type=obs_type,
        title=title,
        text=text,
        narrative="",
        facts="",
        created_at="2026-08-14T00:00:00Z",
    )


class ClassificationTests(unittest.TestCase):
    def test_allows_architecture_decision(self):
        self.assertEqual(SYNC.classify(row("decision", "架构选型：统一使用领域 service")), (True, "eligible"))

    def test_allows_stable_preference(self):
        self.assertTrue(SYNC.classify(row("decision", "Stable preference: prefer explicit schemas"))[0])

    def test_rejects_unverified_bugfix(self):
        allowed, reason = SYNC.classify(row("bugfix", "可能修复登录失败"))
        self.assertFalse(allowed)
        self.assertIn(reason, ("tentative_or_temporary", "bugfix_not_verified"))

    def test_allows_verified_bugfix(self):
        self.assertTrue(SYNC.classify(row("bugfix", "根因已修复，回归测试通过"))[0])

    def test_rejects_secret(self):
        allowed, reason = SYNC.classify(row("discovery", "关键发现", "api_key=m0-abcdefghijklmnop"))
        self.assertFalse(allowed)
        self.assertEqual(reason, "sensitive_content")

    def test_rejects_github_token(self):
        token = "ghp_" + ("a" * 36)
        self.assertEqual(
            SYNC.classify(row("decision", "Architecture credential", token))[1],
            "sensitive_content",
        )

    def test_rejects_webhook_and_jwt(self):
        webhook = "https://hooks.slack.com/services/T000/B000/secretvalue"
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"
        self.assertEqual(SYNC.classify(row("discovery", "Important finding", webhook))[1], "sensitive_content")
        self.assertEqual(SYNC.classify(row("discovery", "Important finding", jwt))[1], "sensitive_content")

    def test_rejects_stack_trace(self):
        trace = "ERROR stack trace\n    at handler (/srv/app.js:42:9)"
        self.assertEqual(SYNC.classify(row("decision", "Architecture failure handling", trace))[1], "raw_log_content")

    def test_rejects_progress_type(self):
        self.assertEqual(SYNC.classify(row("progress", "关键进度")), (False, "type_not_allowed"))


class CursorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "claude-mem.db")
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            """
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY,
                project TEXT,
                type TEXT,
                title TEXT,
                text TEXT,
                narrative TEXT,
                facts TEXT,
                created_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO observations VALUES (7, 'repo', 'discovery', '关键发现', '', '', '', 'now')"
        )
        connection.commit()
        connection.close()
        self.config = {
            "user_id": "leshine-ark-owner-v1",
            "source_device": "test-device",
            "db_path": self.db_path,
            "state_path": os.path.join(self.temp.name, "cursor.json"),
            "lock_path": os.path.join(self.temp.name, "sync.lock"),
            "api_base_url": "https://api.mem0.ai",
            "api_key_env": "MEM0_API_KEY_TEST_DO_NOT_SET",
            "api_key_keychain_service": "",
            "api_key_keychain_account": "",
            "project_aliases": {},
            "retry_attempts": 1,
            "event_poll_attempts": 1,
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_first_run_initializes_at_latest_without_api_key(self):
        args = SYNC.parse_args(["--dry-run"])
        args.dry_run = False
        SYNC.run_sync(self.config, args)
        with open(self.config["state_path"], encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(state["cursor"], 7)
        self.assertIsNone(state["pending"])

    def test_backfill_needs_exact_confirmation(self):
        args = SYNC.parse_args(["--backfill-from", "1"])
        with self.assertRaises(SYNC.SyncError):
            SYNC.run_sync(self.config, args)

    def test_successful_upload_advances_cursor_with_required_metadata(self):
        SYNC.atomic_write_json(self.config["state_path"], SYNC.new_state(self.config, 0))
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "UPDATE observations SET type='bugfix', title='根因已修复，回归测试通过' WHERE id=7"
        )
        connection.commit()
        connection.close()

        class FakeClient:
            added = []

            def __init__(self, *args, **kwargs):
                pass

            def source_exists(self, user_id, unique_source_key):
                return False

            def add(self, user_id, unique_source_key, text, metadata):
                self.added.append((user_id, unique_source_key, text, metadata))
                return {"status": "SUCCEEDED"}

        args = SYNC.parse_args([])
        with mock.patch.object(SYNC, "Mem0Client", FakeClient), mock.patch.object(
            SYNC, "get_api_key", return_value="fake-key"
        ):
            SYNC.run_sync(self.config, args)

        with open(self.config["state_path"], encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(state["cursor"], 7)
        user_id, unique_source_key, _, metadata = FakeClient.added[0]
        self.assertEqual(user_id, "leshine-ark-owner-v1")
        self.assertEqual(unique_source_key, "claude-mem:test-device:7")
        self.assertEqual(
            set(metadata),
            {
                "project",
                "source",
                "source_device",
                "obs_id",
                "source_key",
                "memory_type",
                "source_created_at",
            },
        )

    def test_pending_event_timeout_remains_recoverable(self):
        SYNC.atomic_write_json(self.config["state_path"], SYNC.new_state(self.config, 0))
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "UPDATE observations SET type='bugfix', title='根因已修复，回归测试通过' WHERE id=7"
        )
        connection.commit()
        connection.close()

        class PendingClient:
            def __init__(self, *args, **kwargs):
                pass

            def source_exists(self, *args):
                return False

            def add(self, *args):
                return {"status": "PENDING", "event_id": "event-7"}

        args = SYNC.parse_args([])
        with mock.patch.object(SYNC, "Mem0Client", PendingClient), mock.patch.object(
            SYNC, "get_api_key", return_value="fake-key"
        ), mock.patch.object(
            SYNC, "wait_for_event", side_effect=SYNC.RetryableSyncError("still pending")
        ):
            with self.assertRaises(SYNC.RetryableSyncError):
                SYNC.run_sync(self.config, args)

        with open(self.config["state_path"], encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(state["cursor"], 0)
        self.assertEqual(state["pending"], {"obs_id": 7, "event_id": "event-7"})

    def test_cursor_ahead_of_database_fails_closed(self):
        SYNC.atomic_write_json(self.config["state_path"], SYNC.new_state(self.config, 99))
        with self.assertRaises(SYNC.SyncError):
            SYNC.run_sync(self.config, SYNC.parse_args([]))


class SearchPresetTests(unittest.TestCase):
    def test_constants_match_policy(self):
        self.assertEqual(SYNC.SEARCH_TOP_K, 5)
        self.assertEqual(SYNC.SEARCH_THRESHOLD, 0.4)

    def test_project_search_payload_has_fixed_parameters(self):
        class RecordingClient(SYNC.Mem0Client):
            def __init__(self):
                self.payload = None

            def request(self, method, path, payload=None):
                self.payload = payload
                return {"results": []}

        client = RecordingClient()
        client.search("architecture", "leshine-ark-owner-v1", project="commission-system")
        self.assertEqual(client.payload["top_k"], 5)
        self.assertEqual(client.payload["threshold"], 0.4)
        self.assertIs(client.payload["rerank"], True)
        self.assertEqual(
            client.payload["filters"],
            {
                "AND": [
                    {"user_id": "leshine-ark-owner-v1"},
                    {"metadata": {"project": "commission-system"}},
                ]
            },
        )

    def test_source_key_is_unique_per_device_and_observation(self):
        config = {"source_device": "mac-mini-11"}
        self.assertEqual(SYNC.source_key(config, 42), "claude-mem:mac-mini-11:42")
        self.assertNotEqual(
            SYNC.source_key(config, 42),
            SYNC.source_key({"source_device": "macbook-1"}, 42),
        )

    def test_search_requires_project(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            SYNC.parse_args(["--search", "architecture"])

    def test_search_rejects_empty_query(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            SYNC.parse_args(["--search", "  ", "--project", "commission-system"])

    def test_project_miss_falls_back_exactly_once(self):
        class FakeClient:
            calls = []

            def __init__(self, *args, **kwargs):
                pass

            def search(self, query, user_id, project=None):
                self.calls.append(project)
                return [] if project else [{"memory": "fallback"}]

        output = io.StringIO()
        with mock.patch.object(SYNC, "Mem0Client", FakeClient), mock.patch.object(
            SYNC, "get_api_key", return_value="fake-key"
        ), redirect_stdout(output):
            SYNC.run_search(
                {
                    "api_base_url": "https://api.mem0.ai",
                    "retry_attempts": 1,
                    "user_id": "leshine-ark-owner-v1",
                },
                "architecture",
                "commission-system",
            )
        self.assertEqual(FakeClient.calls, ["commission-system", None])
        self.assertEqual(json.loads(output.getvalue())["scope"], "user_fallback")

    def test_agent_worktrees_share_stable_project_slug(self):
        aliases = {"commission-system-*": "commission-system"}
        self.assertEqual(
            SYNC.normalize_project("/srv/commission-system-codex-memory", aliases),
            "commission-system",
        )
        self.assertEqual(
            SYNC.normalize_project("/srv/commission-system-kimi", aliases),
            "commission-system",
        )


if __name__ == "__main__":
    unittest.main()
