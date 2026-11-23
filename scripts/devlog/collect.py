# scripts/devlog/collect.py
"""方舟开发动态采集器。

python scripts/devlog/collect.py               # 采集并写 .devlog_state/last-payload.json，不联网推送
python scripts/devlog/collect.py --push        # 采集后推送生产（需 collector.json，且须亮哥授权启用）
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client  # noqa: E402
import gitdata  # noqa: E402
from grouping import KeyMap, build_groups  # noqa: E402
from status import PatchCache, Release, compute_items  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _now(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value)
        return gitdata.to_bj_naive(value) if parsed.tzinfo else parsed
    return datetime.fromtimestamp(time.time(), gitdata.BJ).replace(tzinfo=None)


def _releases(repo, state, config, sources):
    cache = state / "releases.json"
    rows = None
    live_ok = not config
    if config:
        try:
            rows = client.get_json(config, "/api/devlog/machine/releases")["data"]["items"]
            live_ok = True
            cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        except Exception as error:
            print(f"[devlog] release ledger unavailable: {type(error).__name__}", flush=True)
    if rows is None and cache.is_file():
        rows = json.loads(cache.read_text(encoding="utf-8"))
    if rows is None:
        sources.append({"name": "releases", "ok": False, "detail": "no ledger"})
        return []
    missing = [r["revision"][:8] for r in rows if not gitdata.object_exists(repo, r["revision"])]
    sources.append({"name": "releases", "ok": not missing and live_ok, "detail": ("missing " + ",".join(missing))[:120] if missing else ("" if live_ok else "cached ledger; refresh failed")})
    return [Release(r["revision"], _now(r["released_at"]), r["scope"])
            for r in rows if gitdata.object_exists(repo, r["revision"])]


def _run(args) -> int:
    repo, state = Path(args.repo), Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    config = client.load_config(state)
    if args.push and not config:
        print("[devlog] --push 需要 .devlog_state/collector.json（base_url + token）", flush=True)
        return 2
    started = _now(args.now)
    sources = []
    try:
        fetched, detail = (False, "fetch skipped; local snapshot") if args.no_fetch else gitdata.fetch(repo)
    except Exception as error:
        print(f"[devlog] fetch failed: {type(error).__name__}", flush=True)
        fetched, detail = False, "fetch failed"
    sources.append({"name": "fetch", "ok": fetched, "detail": detail})
    try:
        releases = _releases(repo, state, config if args.push else None, sources)
    except (ValueError, KeyError, TypeError, OSError):
        print("[devlog] invalid release ledger; collection aborted", flush=True)
        return 3
    origin = "origin/main" if gitdata.object_exists(repo, "origin/main") else None
    if origin is None:
        sources[0].update(ok=False, detail="origin/main unavailable")
    try:
        cache = PatchCache(state / "patch-ids.json")
        keymap = KeyMap(state / "keymap.json")
        groups = build_groups(repo, args.since, keymap=keymap, cache=cache, now=started)
        items = compute_items(repo, groups, args.since, releases=releases, origin_ref=origin, now=started, cache=cache, keymap=keymap)
        sources.insert(0, {"name": "git", "ok": True, "detail": ""})
    except Exception as error:
        print(f"[devlog] git collection failed: {type(error).__name__}", flush=True)
        return 1   # Git 读不到就不上报，避免用空结果覆盖任何东西
    cache.save()
    keymap.save()
    payload = {"started_at": started.isoformat(timespec="seconds"),
               "finished_at": _now(args.now).isoformat(timespec="seconds"),
               "snapshot": True,   # 走到这里说明 Git 全量读取成功
               "sources": sources, "items": items}
    (state / "last-payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[devlog] {len(items)} items collected", flush=True)
    if args.push:
        if origin is None:
            print("[devlog] origin/main unavailable; refusing to infer remote state from local main", flush=True)
            return 3
        if not next(s["ok"] for s in sources if s["name"] == "releases"):
            # 账本读不全就算不出「已发布」，推上去会把已发布事项整体降级并写入假事件
            print("[devlog] 发布账本不可用或有 revision 本地缺失，本轮不推送；payload 已留在本地供排查", flush=True)
            return 3
        try:
            result = client.post_json(config, "/api/devlog/ingest", payload)
            if result.get("code") != 200 or result.get("data", {}).get("failed"):
                print("[devlog] server reported rejected items; inspect sync health", flush=True)
                return 4
        except Exception as error:
            print(f"[devlog] push failed: {type(error).__name__}", flush=True)
            return 4
        print("[devlog] push completed", flush=True)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--state", default=str(REPO / ".devlog_state"))
    parser.add_argument("--since", default="2026-09-01")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--now", help="测试用：固定北京时间")
    args = parser.parse_args(argv)
    # Exclusive create prevents concurrent collectors racing keymap/cache files.
    state = Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "collector.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        print("[devlog] collector.lock exists; confirm no collector is running before removing it", flush=True)
        return 5
    try:
        with handle:
            handle.write(str(os.getpid()))
        return _run(args)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
