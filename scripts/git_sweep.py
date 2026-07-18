"""git_sweep — 多智能体并行开发的 git 欠账巡检 + 可视化看板。

扫描本仓库全部 worktree 与本地分支，报告六类欠账：
  1. 未提交改动（每个 worktree）
  2. 未推送提交（ahead of upstream / 无 upstream）
  3. 未合并进 main 的分支（含闲置天数）
  4. 已合并可删除的分支
  5. stash
  6. Alembic 迁移编号撞号（跨分支，cerebrum 2026-07-17 教训）

输出：控制台摘要 + tmp/git-sweep.html 可视化看板。

用法：
  python scripts/git_sweep.py            # 巡检 + 生成看板
  python scripts/git_sweep.py --open     # 巡检后用浏览器打开看板
  python scripts/git_sweep.py --notify   # 有欠账时推送钉钉（复用后端告警机器人）
  python scripts/git_sweep.py --no-fetch # 跳过 git fetch（离线/代理不通时）

定时任务（每日 18:00，deploy 无关，仅开发机）：
  schtasks /Create /TN LeShine-GitSweep /SC DAILY /ST 18:00 /TR
    "<venv python> <本文件> --notify"
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]  # 锚定仓库根，cwd 无关（定时任务 cwd=system32）
OUTPUT_HTML = REPO_ROOT / "tmp" / "git-sweep.html"
MAIN = "main"
TOOL_PREFIXES = {"claude": "Claude", "codex": "Codex", "kimi": "Kimi"}
MIGRATION_DIR = "backend/alembic/versions"

# Windows 控制台默认 GBK，中文分支名/提交题目会炸
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def git(*args: str, cwd: Path | None = None, timeout: int = 30) -> str:
    """跑 git 命令返回 stdout；失败抛 RuntimeError。"""
    cmd = ["git", "-C", str(cwd or REPO_ROOT), *args]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


@dataclass
class Worktree:
    path: str
    branch: str          # 空 = detached
    dirty_tracked: int = 0
    dirty_untracked: int = 0

    @property
    def dirty_total(self) -> int:
        return self.dirty_tracked + self.dirty_untracked


@dataclass
class Branch:
    name: str
    sha: str
    subject: str
    committer_unix: int
    upstream: str        # 空 = 无 upstream
    ahead_upstream: int = 0
    behind_upstream: int = 0
    upstream_gone: bool = False
    ahead_main: int = 0
    behind_main: int = 0
    merged_into_main: bool = False
    checked_out_at: str = ""   # worktree 路径，空 = 未检出

    @property
    def tool(self) -> str:
        prefix = self.name.split("/")[0]
        if self.name == MAIN:
            return "—"
        return TOOL_PREFIXES.get(prefix, "legacy")

    @property
    def idle_days(self) -> int:
        return max(0, int((datetime.now().timestamp() - self.committer_unix) // 86400))

    @property
    def unpushed(self) -> bool:
        return (not self.upstream) or self.upstream_gone or self.ahead_upstream > 0


@dataclass
class Report:
    generated_at: str
    fetch_ok: bool
    fetch_note: str
    worktrees: list[Worktree] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    stashes: list[str] = field(default_factory=list)
    migration_collisions: list[str] = field(default_factory=list)

    # ---- 派生欠账 ----
    @property
    def dirty_worktrees(self) -> list[Worktree]:
        return [w for w in self.worktrees if w.dirty_total > 0]

    @property
    def unpushed_branches(self) -> list[Branch]:
        return [b for b in self.branches if b.unpushed and b.name != MAIN]

    @property
    def unmerged_branches(self) -> list[Branch]:
        return [b for b in self.branches if not b.merged_into_main and b.name != MAIN]

    @property
    def deletable_branches(self) -> list[Branch]:
        return [
            b for b in self.branches
            if b.merged_into_main and b.name != MAIN and not b.checked_out_at
        ]

    @property
    def main_branch(self) -> Branch | None:
        return next((b for b in self.branches if b.name == MAIN), None)

    @property
    def debt_count(self) -> int:
        main_drift = 0
        m = self.main_branch
        if m and (m.ahead_upstream or m.behind_upstream):
            main_drift = 1
        return (
            len(self.dirty_worktrees) + len(self.unpushed_branches)
            + len(self.unmerged_branches) + len(self.deletable_branches)
            + len(self.stashes) + len(self.migration_collisions) + main_drift
        )


# ──────────────────────────────── 采集 ────────────────────────────────

def collect_worktrees() -> list[Worktree]:
    out = git("worktree", "list", "--porcelain")
    result: list[Worktree] = []
    cur_path, cur_branch = "", ""
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            cur_path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            cur_branch = line[len("branch "):].replace("refs/heads/", "").strip()
        elif not line and cur_path:
            result.append(Worktree(path=cur_path, branch=cur_branch))
            cur_path, cur_branch = "", ""
    for wt in result:
        try:
            status = git("status", "--porcelain", cwd=Path(wt.path))
            for s_line in status.splitlines():
                if s_line.startswith("??"):
                    wt.dirty_untracked += 1
                elif s_line.strip():
                    wt.dirty_tracked += 1
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"[warn] status failed for {wt.path}: {exc}", flush=True)
    return result


def collect_branches(worktrees: list[Worktree]) -> list[Branch]:
    fmt = "%(refname:short)\x01%(objectname:short)\x01%(upstream:short)\x01%(upstream:track)\x01%(committerdate:unix)\x01%(subject)"
    out = git("for-each-ref", "refs/heads", f"--format={fmt}")
    merged = set(
        git("branch", "--merged", MAIN, "--format=%(refname:short)").split()
    )
    checkout_map = {w.branch: w.path for w in worktrees if w.branch}
    branches: list[Branch] = []
    for line in out.splitlines():
        parts = line.split("\x01")
        if len(parts) != 6:
            continue
        name, sha, upstream, track, cunix, subject = parts
        b = Branch(
            name=name, sha=sha, subject=subject,
            committer_unix=int(cunix or 0), upstream=upstream,
        )
        if track == "[gone]":
            b.upstream_gone = True
        else:
            m = re.search(r"ahead (\d+)", track)
            b.ahead_upstream = int(m.group(1)) if m else 0
            m = re.search(r"behind (\d+)", track)
            b.behind_upstream = int(m.group(1)) if m else 0
        b.merged_into_main = name in merged
        b.checked_out_at = checkout_map.get(name, "")
        if name != MAIN:
            try:
                counts = git("rev-list", "--left-right", "--count", f"{MAIN}...{name}")
                left, right = counts.split()
                b.behind_main, b.ahead_main = int(left), int(right)
            except (RuntimeError, ValueError):
                pass
        branches.append(b)
    return branches


def collect_stashes() -> list[str]:
    try:
        out = git("stash", "list", "--format=%gd %ci %gs")
        return [line.strip() for line in out.splitlines() if line.strip()]
    except RuntimeError:
        return []


def collect_migration_collisions(branches: list[Branch]) -> list[str]:
    """跨分支扫 Alembic 迁移编号：同一数字前缀出现 ≥2 个不同文件名即撞号。
    全部文件都已在 main 里的（历史上已解决的撞号）不再报。"""
    prefix_files: dict[str, dict[str, set[str]]] = {}
    main_files: set[str] = set()
    for b in branches:
        try:
            out = git("ls-tree", "-r", "--name-only", b.name, "--", MIGRATION_DIR)
        except RuntimeError:
            continue
        for path in out.splitlines():
            fname = path.rsplit("/", 1)[-1]
            m = re.match(r"^(\d+)_.+\.py$", fname)
            if not m:
                continue
            if b.name == MAIN:
                main_files.add(fname)
            prefix_files.setdefault(m.group(1), {}).setdefault(fname, set()).add(b.name)
    collisions = []
    for prefix, files in sorted(prefix_files.items()):
        if len(files) < 2:
            continue
        if all(f in main_files for f in files):
            continue  # 已在 main 共存 = 历史已解决
        detail = "; ".join(
            f"{f}({','.join(sorted(bs))})" for f, bs in sorted(files.items())
        )
        collisions.append(f"编号 {prefix}: {detail}")
    return collisions


def build_report(do_fetch: bool) -> Report:
    fetch_ok, fetch_note = True, "已 fetch origin"
    if do_fetch:
        try:
            git("fetch", "origin", "--prune", timeout=60)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            fetch_ok, fetch_note = False, f"fetch 失败（基于本地缓存）: {exc}"
            print(f"[warn] {fetch_note}", flush=True)
    else:
        fetch_ok, fetch_note = True, "跳过 fetch（--no-fetch）"
    worktrees = collect_worktrees()
    branches = collect_branches(worktrees)
    return Report(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        fetch_ok=fetch_ok, fetch_note=fetch_note,
        worktrees=worktrees, branches=branches,
        stashes=collect_stashes(),
        migration_collisions=collect_migration_collisions(branches),
    )


# ──────────────────────────────── 控制台输出 ────────────────────────────────

def print_console(r: Report) -> None:
    print(f"\n=== Git 巡检 {r.generated_at}（{r.fetch_note}）===\n", flush=True)
    m = r.main_branch
    if m:
        if m.ahead_upstream:
            print(f"[!] main 领先 origin/main {m.ahead_upstream} 个提交——待亮哥指令 push", flush=True)
        elif m.behind_upstream:
            print(f"[!] main 落后 origin/main {m.behind_upstream} 个提交——需要 pull", flush=True)
        else:
            print("[ok] main 与 origin/main 同步", flush=True)

    if r.dirty_worktrees:
        print("\n-- 未提交改动 --", flush=True)
        for w in r.dirty_worktrees:
            print(f"  {w.path} [{w.branch or 'detached'}] 改动 {w.dirty_tracked} + 未跟踪 {w.dirty_untracked}", flush=True)
    if r.unpushed_branches:
        print("\n-- 未推送 --", flush=True)
        for b in r.unpushed_branches:
            why = "无 upstream" if not b.upstream else ("upstream 已删" if b.upstream_gone else f"ahead {b.ahead_upstream}")
            print(f"  {b.name} ({why})", flush=True)
    if r.unmerged_branches:
        print("\n-- 未合并进 main --", flush=True)
        for b in r.unmerged_branches:
            print(f"  {b.name} [{b.tool}] +{b.ahead_main}/-{b.behind_main} vs main, 闲置 {b.idle_days} 天", flush=True)
    if r.deletable_branches:
        print("\n-- 已合并可删 --", flush=True)
        for b in r.deletable_branches:
            print(f"  {b.name}  (git branch -d {b.name})", flush=True)
    if r.stashes:
        print("\n-- stash --", flush=True)
        for s in r.stashes:
            print(f"  {s}", flush=True)
    if r.migration_collisions:
        print("\n-- Alembic 迁移撞号 --", flush=True)
        for c in r.migration_collisions:
            print(f"  [!!] {c}", flush=True)
    if r.debt_count == 0:
        print("\n[ok] 无欠账，工作区干净。", flush=True)
    print(f"\n看板: {OUTPUT_HTML}", flush=True)


# ──────────────────────────────── HTML 看板 ────────────────────────────────

_CSS = """
:root{
  --bg:#0f0e0c; --panel:#171512; --panel-2:#1d1a16; --line:#2a261f;
  --text:#e8e3d9; --muted:#8d8677; --gold:#c9a063; --gold-dim:#8a6f45;
  --ok:#7fb069; --warn:#e0a458; --danger:#d0654f; --mono:'Cascadia Code',Consolas,monospace;
}
@media (prefers-color-scheme: light){
  :root{--bg:#faf8f4;--panel:#fff;--panel-2:#f4f0e8;--line:#e4ddd0;
        --text:#2b2721;--muted:#948b79;--gold:#a97e3f;--gold-dim:#c9b48e;}
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,'Segoe UI','Microsoft YaHei',sans-serif;padding:32px 20px 64px}
.wrap{max-width:960px;margin:0 auto}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:20px;font-weight:650;letter-spacing:.02em}
h1 b{color:var(--gold);font-weight:650}
.meta{color:var(--muted);font-size:12.5px}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.pill.ok{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 40%,transparent)}
.pill.warn{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 40%,transparent)}
.pill.danger{color:var(--danger);border-color:color-mix(in srgb,var(--danger) 40%,transparent)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:22px 0 30px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .n{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums}
.tile .l{color:var(--muted);font-size:12.5px;margin-top:2px}
.tile.zero .n{color:var(--muted)}
.tile.warn .n{color:var(--warn)}
.tile.danger .n{color:var(--danger)}
section{margin-bottom:30px}
h2{font-size:13px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.tablewrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{color:var(--muted);font-weight:500;font-size:12px;text-align:left;padding:9px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 14px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
.mono{font-family:var(--mono);font-size:12.5px}
.tool{display:inline-block;font-size:11px;padding:1px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.tool.Claude{color:var(--gold);border-color:var(--gold-dim)}
.tool.Codex{color:#8fb4d9;border-color:#3d5670}
.tool.Kimi{color:#b596d9;border-color:#54406e}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.ok-t{color:var(--ok)}.warn-t{color:var(--warn)}.danger-t{color:var(--danger)}
.muted{color:var(--muted)}
.subject{max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.empty{padding:18px 16px;color:var(--muted)}
.allclear{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:28px;text-align:center;color:var(--ok);font-size:15px;margin-bottom:30px}
.alert{border-left:3px solid var(--danger);background:var(--panel-2);padding:10px 14px;border-radius:6px;margin-bottom:8px;font-size:13px}
footer{color:var(--muted);font-size:12px;margin-top:36px}
footer code{font-family:var(--mono);background:var(--panel-2);padding:1px 6px;border-radius:4px}
.rise{opacity:0;transform:translateY(6px);animation:rise .2s cubic-bezier(.23,1,.32,1) forwards}
@keyframes rise{to{opacity:1;transform:translateY(0)}}
@media (prefers-reduced-motion: reduce){.rise{animation:none;opacity:1;transform:none}}
"""


def _tile(count: int, label: str, danger: bool = False) -> str:
    cls = "zero" if count == 0 else ("danger" if danger else "warn")
    return f'<div class="tile {cls}"><div class="n">{count}</div><div class="l">{html.escape(label)}</div></div>'


def render_html(r: Report) -> str:
    e = html.escape
    m = r.main_branch
    if m and m.ahead_upstream:
        main_pill = f'<span class="pill warn">main 领先远端 {m.ahead_upstream}（待指令 push）</span>'
    elif m and m.behind_upstream:
        main_pill = f'<span class="pill danger">main 落后远端 {m.behind_upstream}（需 pull）</span>'
    else:
        main_pill = '<span class="pill ok">main 已同步</span>'
    fetch_pill = "" if r.fetch_ok else '<span class="pill danger">fetch 失败·本地缓存</span>'

    tiles = "".join([
        _tile(len(r.dirty_worktrees), "未提交 worktree"),
        _tile(len(r.unpushed_branches), "未推送分支", danger=True),
        _tile(len(r.unmerged_branches), "未合并进 main"),
        _tile(len(r.deletable_branches), "可清理分支"),
        _tile(len(r.migration_collisions), "迁移撞号", danger=True),
    ])

    wt_rows = ""
    for w in sorted(r.worktrees, key=lambda x: x.path):
        if w.dirty_total:
            dirty = f'<span class="warn-t num">改动 {w.dirty_tracked} · 未跟踪 {w.dirty_untracked}</span>'
        else:
            dirty = '<span class="ok-t">干净</span>'
        br = next((b for b in r.branches if b.name == w.branch), None)
        tool = br.tool if br else "?"
        wt_rows += (
            f'<tr><td class="mono">{e(w.path)}</td>'
            f'<td><span class="tool {e(tool)}">{e(tool)}</span></td>'
            f'<td class="mono">{e(w.branch or "detached")}</td><td>{dirty}</td></tr>'
        )

    br_rows = ""
    for b in sorted(r.branches, key=lambda x: (x.name != MAIN, x.merged_into_main, -x.committer_unix)):
        if b.name == MAIN:
            vs_main, state = '<span class="muted">—</span>', ""
        elif b.merged_into_main:
            vs_main = '<span class="muted">已合并</span>'
            state = '<span class="ok-t">可删除</span>' if not b.checked_out_at else '<span class="muted">worktree 检出中</span>'
        else:
            vs_main = f'<span class="num">+{b.ahead_main} / −{b.behind_main}</span>'
            idle_cls = "danger-t" if b.idle_days >= 3 else ("warn-t" if b.idle_days >= 1 else "muted")
            state = f'<span class="{idle_cls}">闲置 {b.idle_days} 天</span>'
        if not b.upstream:
            push = '<span class="danger-t">无 upstream</span>'
        elif b.upstream_gone:
            push = '<span class="danger-t">upstream 已删</span>'
        elif b.ahead_upstream:
            push = f'<span class="danger-t num">未推 {b.ahead_upstream}</span>'
        elif b.behind_upstream:
            push = f'<span class="warn-t num">落后 {b.behind_upstream}</span>'
        else:
            push = '<span class="ok-t">已推送</span>'
        br_rows += (
            f'<tr><td class="mono">{e(b.name)}</td>'
            f'<td><span class="tool {e(b.tool)}">{e(b.tool)}</span></td>'
            f'<td>{vs_main}</td><td>{push}</td><td>{state}</td>'
            f'<td class="subject muted" title="{e(b.subject)}">{e(b.subject)}</td></tr>'
        )

    alerts = ""
    for c in r.migration_collisions:
        alerts += f'<div class="alert">Alembic 撞号 — {e(c)}</div>'
    for s in r.stashes:
        alerts += f'<div class="alert">stash 未处理 — <span class="mono">{e(s)}</span></div>'
    alerts_section = f"<section class='rise'><h2>警报</h2>{alerts}</section>" if alerts else ""

    allclear = '<div class="allclear rise">✓ 无欠账，所有分支已推送、已合并或正在 worktree 中开发</div>' if r.debt_count == 0 else ""

    delay = lambda i: f"style='animation-delay:{i * 40}ms'"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Git 巡检看板 — 莱莎方舟</title><style>{_CSS}</style></head><body><div class="wrap">
<header class="rise"><h1><b>Git 巡检</b> 莱莎方舟</h1>
<span class="meta">{e(r.generated_at)}</span>{main_pill}{fetch_pill}</header>
<div class="meta rise" {delay(1)}>{e(str(REPO_ROOT))} · {len(r.worktrees)} worktrees · {len(r.branches)} 本地分支</div>
<div class="tiles rise" {delay(2)}>{tiles}</div>
{allclear}{alerts_section}
<section class="rise" {delay(3)}><h2>Worktrees</h2><div class="card tablewrap"><table>
<tr><th>目录</th><th>代理</th><th>分支</th><th>工作区</th></tr>{wt_rows}</table></div></section>
<section class="rise" {delay(4)}><h2>分支账本</h2><div class="card tablewrap"><table>
<tr><th>分支</th><th>代理</th><th>vs main</th><th>推送</th><th>状态</th><th>最后提交</th></tr>{br_rows}</table></div></section>
<footer class="rise" {delay(5)}>重新生成：<code>python scripts/git_sweep.py --open</code> · 约定见 <code>AGENTS.md</code> / <code>CLAUDE.md</code> · 每日 18:00 自动巡检推钉钉</footer>
</div></body></html>"""


# ──────────────────────────────── 钉钉通知 ────────────────────────────────

def notify_dingtalk(r: Report) -> None:
    """复用后端告警机器人（与定时任务告警同一群）。仅在有欠账时调用。"""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    try:
        import asyncio
        from app.dingtalk.webhook import get_webhook_sender  # noqa: 需 backend/.venv 环境
    except ImportError as exc:
        print(f"[warn] 钉钉通知不可用（需用 backend/.venv 的 python 运行）: {exc}", flush=True)
        return
    lines = [f"### Git 巡检 {r.generated_at}"]
    m = r.main_branch
    if m and m.ahead_upstream:
        lines.append(f"- **main 领先远端 {m.ahead_upstream} 个提交**（待指令 push）")
    if m and m.behind_upstream:
        lines.append(f"- **main 落后远端 {m.behind_upstream} 个提交**（需 pull）")
    if r.dirty_worktrees:
        detail = "；".join(f"{Path(w.path).name}[{w.branch}] {w.dirty_total} 个文件" for w in r.dirty_worktrees)
        lines.append(f"- 未提交：{detail}")
    if r.unpushed_branches:
        lines.append(f"- 未推送：{'、'.join(b.name for b in r.unpushed_branches)}")
    if r.unmerged_branches:
        detail = "；".join(f"{b.name}(+{b.ahead_main},闲置{b.idle_days}天)" for b in r.unmerged_branches)
        lines.append(f"- 未合并进 main：{detail}")
    if r.deletable_branches:
        lines.append(f"- 可清理：{'、'.join(b.name for b in r.deletable_branches)}")
    if r.migration_collisions:
        lines.append(f"- **迁移撞号：{'；'.join(r.migration_collisions)}**")
    if r.stashes:
        lines.append(f"- stash：{len(r.stashes)} 条未处理")
    lines.append("\n> 开发机看板：tmp/git-sweep.html")
    try:
        asyncio.run(get_webhook_sender().send_markdown("Git 巡检", "\n".join(lines)))
        print("[ok] 钉钉巡检通知已发送", flush=True)
    except Exception as exc:  # 通知失败不影响巡检本身
        print(f"[warn] 钉钉通知发送失败: {exc}", flush=True)


# ──────────────────────────────── 入口 ────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="git 欠账巡检 + 可视化看板")
    parser.add_argument("--open", action="store_true", help="生成后用浏览器打开看板")
    parser.add_argument("--notify", action="store_true", help="有欠账时推送钉钉")
    parser.add_argument("--no-fetch", action="store_true", help="跳过 git fetch")
    args = parser.parse_args()

    r = build_report(do_fetch=not args.no_fetch)
    print_console(r)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(render_html(r), encoding="utf-8")

    if args.open:
        import os
        os.startfile(OUTPUT_HTML)  # noqa: Windows only
    if args.notify:
        if r.debt_count == 0:
            print("[ok] 无欠账，不打扰。", flush=True)
        else:
            notify_dingtalk(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
