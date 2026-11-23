# scripts/devlog/tests/test_cli.py
import json
from datetime import datetime

from conftest import commit, sh
import backfill_releases
import collect
import client


def test_dry_run_writes_payload_without_network(repo, tmp_path, monkeypatch):
    sh(repo, "checkout", "-b", "codex/a")
    commit(repo, "backend/app/stock/a.py", "a = 1\n", "Add a")
    sh(repo, "checkout", "main")
    state = tmp_path / "state"
    monkeypatch.setattr(collect.client, "post_json", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    code = collect.main(["--repo", str(repo), "--state", str(state), "--since", "2026-10-01", "--no-fetch",
                         "--now", "2026-11-23T15:00:00"])
    payload = json.loads((state / "last-payload.json").read_text(encoding="utf-8"))
    assert code == 0 and payload["items"][0]["key"] == "branch:codex/a" and payload["snapshot"] is True
    assert {s["name"]: s["ok"] for s in payload["sources"]} == {"git": True, "fetch": False, "releases": False}
    assert (state / "keymap.json").is_file() and (state / "patch-ids.json").is_file()


def test_push_requires_config(repo, tmp_path):
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--push", "--no-fetch"]) == 2


def test_push_refused_when_release_ledger_unavailable(repo, tmp_path, monkeypatch):
    (tmp_path / "collector.json").write_text(json.dumps({"base_url": "https://example.invalid", "token": "t" * 32}), encoding="utf-8")
    monkeypatch.setattr(collect.client, "get_json", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    posted = []
    monkeypatch.setattr(collect.client, "post_json", lambda *a, **k: posted.append(a))
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--push", "--no-fetch"]) == 3
    assert posted == []


def test_backfill_prefers_activate_result_with_bom_and_time(tmp_path):
    timed = tmp_path / "global-release-20d86027-20261118"
    timed.mkdir()
    (timed / "activate-result.json").write_bytes("﻿".encode("utf-8") + json.dumps(
        {"phase": "activate", "revision": "a" * 40, "exit_code": 0, "time": "2026-11-18T22:50:52.6366808+08:00"}).encode())
    untimed = tmp_path / "global-release-24d2cb6f-20261113"
    untimed.mkdir()
    (untimed / "activate-result.json").write_text(json.dumps({"revision": "b" * 40, "exit_code": 0}), encoding="utf-8")
    failed = tmp_path / "global-release-ffffffff-20261112"
    failed.mkdir()
    (failed / "activate-result.json").write_text(json.dumps({"revision": "c" * 40, "exit_code": 1}), encoding="utf-8")
    legacy = tmp_path / "global-release-96e42ec3-20261120"
    legacy.mkdir()
    (legacy / "revision.json").write_text(json.dumps({"candidate": "d" * 40}), encoding="utf-8")
    (tmp_path / "global-release-broken-20261101").mkdir()
    text_only = tmp_path / "global-release-ee3e3a8c-20261119"
    text_only.mkdir()
    (text_only / "revision.txt").write_text("e" * 40 + "\n", encoding="utf-8")
    rows, skipped = backfill_releases.scan(tmp_path)
    by_rev = {r["revision"][0]: r for r in rows}
    assert by_rev["e"]["time_source"] == "file-mtime"
    assert by_rev["a"]["released_at"] == "2026-11-18T22:50:52" and by_rev["a"]["time_source"] == "receipt"
    assert by_rev["b"]["time_source"] == "file-mtime" and by_rev["d"]["time_source"] == "file-mtime"
    assert "c" not in by_rev
    assert set(skipped) == {"global-release-ffffffff-20261112", "global-release-broken-20261101"}


def test_cached_ledger_does_not_allow_push_after_live_read_failure(repo, tmp_path, monkeypatch):
    (tmp_path / "collector.json").write_text(json.dumps({"base_url": "https://example.invalid", "token": "t" * 32}))
    (tmp_path / "releases.json").write_text("[]")
    monkeypatch.setattr(client, "get_json", lambda *a: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(client, "post_json", lambda *a: (_ for _ in ()).throw(AssertionError("must not push")))
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--push", "--no-fetch"]) == 3


def test_lock_prevents_overlapping_collection(repo, tmp_path):
    (tmp_path / "collector.lock").touch()
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--no-fetch"]) == 5
    assert (tmp_path / "collector.lock").exists()


def test_corrupt_receipt_does_not_fall_back_to_candidate(tmp_path):
    folder = tmp_path / "global-release-broken"
    folder.mkdir()
    (folder / "activate-result.json").write_text("{incomplete")
    (folder / "revision.json").write_text(json.dumps({"candidate": "a" * 40}))
    rows, skipped = backfill_releases.scan(tmp_path)
    assert not rows and skipped == [folder.name]


def test_manual_backfill_replaces_inferred_timestamp(tmp_path):
    folder = tmp_path / "global-release-old"
    folder.mkdir()
    sha = "a" * 40
    (folder / "revision.txt").write_text(sha)
    state = tmp_path / "state"
    assert backfill_releases.main(["--deploy-state", str(tmp_path), "--state", str(state),
                                  "--add", sha + "@2026-11-22T16:30:00+00:00", "--write-cache"]) == 0
    rows = json.loads((state / "releases.json").read_text())
    assert len(rows) == 1 and rows[0]["released_at"] == "2026-11-23T00:30:00"


def test_config_requires_https_without_embedded_credentials(tmp_path):
    for url in ["http://example.invalid", "https://user:pass@example.invalid", "https://example.invalid?token=x"]:
        (tmp_path / "collector.json").write_text(json.dumps({"base_url": url, "token": "t" * 32}))
        assert client.load_config(tmp_path) is None


def test_client_refuses_token_forwarding_redirect():
    import pytest
    with pytest.raises(OSError, match="redirect refused"):
        client.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid")


def test_now_normalizes_offset_to_beijing():
    assert collect._now("2026-11-22T16:30:00+00:00") == datetime(2026, 11, 23, 0, 30)


def test_partial_server_failure_returns_nonzero(repo, tmp_path, monkeypatch):
    sh(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (tmp_path / "collector.json").write_text(json.dumps({"base_url": "https://example.invalid", "token": "t" * 32}))
    monkeypatch.setattr(client, "get_json", lambda *a: {"data": {"items": []}})
    monkeypatch.setattr(client, "post_json", lambda *a: {"code": 200, "data": {"failed": ["branch:x"]}})
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--push", "--no-fetch"]) == 4


def test_failed_git_read_never_writes_empty_payload(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "build_groups", lambda *a, **k: (_ for _ in ()).throw(OSError("unreadable")))
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--no-fetch"]) == 1
    assert not (tmp_path / "last-payload.json").exists()
    assert not (tmp_path / "collector.lock").exists()


def test_missing_origin_main_blocks_push_and_never_implies_pending_release(repo, tmp_path, monkeypatch):
    commit(repo, "backend/app/stock/local.py", "local\n", "Add local change")
    (tmp_path / "collector.json").write_text(json.dumps({"base_url": "https://example.invalid", "token": "t" * 32}))
    monkeypatch.setattr(client, "get_json", lambda *a: {"data": {"items": []}})
    monkeypatch.setattr(client, "post_json", lambda *a: (_ for _ in ()).throw(AssertionError("must not push")))
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--push", "--no-fetch"]) == 3
    payload = json.loads((tmp_path / "last-payload.json").read_text(encoding="utf-8"))
    assert payload["items"][0]["status"] == "pending_push"
    assert not next(s["ok"] for s in payload["sources"] if s["name"] == "fetch")


def test_push_without_fetch_reports_incomplete_source(repo, tmp_path, monkeypatch):
    sh(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    (tmp_path / "collector.json").write_text(json.dumps({"base_url": "https://example.invalid", "token": "t" * 32}))
    monkeypatch.setattr(client, "get_json", lambda *a: {"data": {"items": []}})
    sent = []
    def post(config, path, payload):
        sent.append(payload)
        return {"code": 200, "data": {"failed": []}}
    monkeypatch.setattr(client, "post_json", post)
    assert collect.main(["--repo", str(repo), "--state", str(tmp_path), "--push", "--no-fetch"]) == 0
    fetch = next(s for s in sent[0]["sources"] if s["name"] == "fetch")
    assert fetch == {"name": "fetch", "ok": False, "detail": "fetch skipped; local snapshot"}
