# scripts/devlog/backfill_releases.py
"""从 .deploy_state/global-release-*/revision.json 回填全局发布账本。

python scripts/devlog/backfill_releases.py                 # 只打印，供人工核对
python scripts/devlog/backfill_releases.py --apply         # 推送（须亮哥授权）
python scripts/devlog/backfill_releases.py --add <sha>@2026-10-14T18:00   # 补 handoff 里有、目录里没有的发布
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client  # noqa: E402
import gitdata  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SHA = re.compile(r"^[0-9a-f]{40}$")


def _row(revision, released_at, time_source):
    return {"revision": revision, "release_id": "backfill-" + revision[:12], "scope": "office-and-cloud",
            "released_at": released_at.replace(microsecond=0).isoformat(timespec="seconds"), "time_source": time_source}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))   # 部署回执带 UTF-8 BOM
    except (OSError, ValueError) as error:
        print(f"[devlog] unreadable receipt: {path.name} ({type(error).__name__})", flush=True)
        return {}


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, gitdata.BJ).replace(tzinfo=None)


def scan(deploy_state: Path):
    """优先读 activate-result.json（revision + exit_code + time）；只有 revision.json 的旧目录用文件时间并标注需核对。"""
    rows, skipped = [], []
    for folder in sorted(deploy_state.glob("global-release-*")):
        text_marker = folder / "revision.txt"   # 个别目录只有纯文本 revision（如 ee3e3a8c-20261119）
        receipt_path = folder / "activate-result.json"
        if not receipt_path.is_file() and not (folder / "revision.json").is_file() and text_marker.is_file():
            revision = text_marker.read_text(encoding="utf-8-sig").strip()
            if SHA.match(revision):
                rows.append(_row(revision, _mtime(text_marker), "file-mtime"))
            else:
                skipped.append(folder.name)
            continue
        receipt = _read(receipt_path)
        if receipt_path.is_file():
            if receipt.get("exit_code") != 0 or not SHA.match(receipt.get("revision", "")):
                skipped.append(folder.name)
                continue
            if receipt.get("time"):
                # PowerShell 写出 7 位小数秒，先截到 6 位再交给 fromisoformat
                stamp = gitdata.to_bj_naive(re.sub(r"(\.\d{6})\d+", r"\1", receipt["time"]))
                rows.append(_row(receipt["revision"], stamp, "receipt"))
            else:
                rows.append(_row(receipt["revision"], _mtime(receipt_path), "file-mtime"))
            continue
        legacy = folder / "revision.json"
        revision = _read(legacy).get("candidate", "")
        if SHA.match(revision):
            rows.append(_row(revision, _mtime(legacy), "file-mtime"))
        else:
            skipped.append(folder.name)
    return rows, skipped


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy-state", default=str(REPO / ".deploy_state"))
    parser.add_argument("--state", default=str(REPO / ".devlog_state"))
    parser.add_argument("--add", action="append", default=[], help="<sha>@<YYYY-MM-DDTHH:MM> 北京时间")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--write-cache", action="store_true", help="把回填清单写成本地 releases.json，供干跑核对")
    args = parser.parse_args(argv)
    rows, skipped = scan(Path(args.deploy_state))
    for extra in args.add:
        sha, _, at = extra.partition("@")
        if not SHA.match(sha):
            print(f"跳过无效 revision: {sha}")
            continue
        stamp = datetime.fromisoformat(at)
        if stamp.tzinfo:
            stamp = gitdata.to_bj_naive(at)
        # A verified manual timestamp replaces an inferred file mtime for this revision.
        rows = [row for row in rows if row["revision"] != sha]
        rows.append(_row(sha, stamp, "manual"))
    for row in sorted(rows, key=lambda r: r["released_at"]):
        flag = "" if row["time_source"] != "file-mtime" else "  ← 时间取自文件修改时间，请与 handoff 核对，必要时改用 --add"
        print(f"{row['released_at']}  {row['revision'][:12]}  {row['release_id']}{flag}")
    print(f"共 {len(rows)} 条；跳过 {len(skipped)} 个目录：{', '.join(skipped)}")
    if args.write_cache:
        # 供 apply 前用 collect.py 干跑核对分布；正式推送时 collect 会用服务端账本覆盖这个缓存
        cache = Path(args.state) / "releases.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([{**{k: v for k, v in r.items() if k != "time_source"}, "source": "backfill-draft"}
                                     for r in rows], ensure_ascii=False), encoding="utf-8")
        print(f"已写入本地草稿缓存 {cache}")
    if not args.apply:
        return 0
    config = client.load_config(Path(args.state))
    if not config:
        print("--apply 需要 .devlog_state/collector.json")
        return 2
    payload = [{k: v for k, v in row.items() if k != "time_source"} for row in rows]   # 服务端白名单不收辅助字段
    result = client.post_json(config, "/api/devlog/machine/releases", {"items": payload})
    print(f"已写入 {result['data']['recorded']} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
