#!/usr/bin/env python3
"""跨代理共享的 Git 门禁（Claude Code / Codex / Kimi / Accio / 人工 通用）。

Claude Code 的 PreToolUse hooks 只约束 Claude 自己；这里把 AGENTS.md 中能机器判定的规则
下沉到 git 本身，任何代理或人提交、推送时都会经过。由 .githooks/* 的 sh 垫片调用。

用法：
    python scripts/git_hooks.py install     # git config core.hooksPath .githooks（全部 worktree 生效）
    python scripts/git_hooks.py status
    python scripts/git_hooks.py uninstall

pre-commit 拦截：main 只能在主 worktree 提交；ARK_AGENT 与分支前缀不符；暂存区空白/冲突标记；
密钥文件与私钥内容；暂存后 Alembic 出现多个 head 或重复 revision。check_conventions 默认只提示，
ARK_HOOKS_STRICT=1 时阻断。
pre-push 拦截：代理（设置了 ARK_AGENT）推送须 ARK_PUSH_APPROVED=1；推送他人前缀分支；
main/master/tag 的删除或非快进（代理对任何分支）须 ARK_PUSH_FORCE_APPROVED=1。
代理不得使用 --no-verify 绕过（AGENTS.md）。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HOOKS_PATH = ".githooks"
ZERO_SHA = "0" * 40
AGENT_PREFIXES = ("claude", "codex", "kimi", "accio")
MAIN_OWNER = "claude"
PROTECTED_BRANCHES = ("refs/heads/main", "refs/heads/master")
MIGRATION_DIR = "backend/alembic/versions"
CODE_SUFFIXES = (".py", ".vue", ".js")

SECRET_PATH = re.compile(
    r"(^|/)(\.env(\.[\w.-]+)?|id_(rsa|dsa|ecdsa|ed25519)|[^/]+\.(pem|p12|pfx|keystore|jks))$"
)
SECRET_PATH_ALLOW = re.compile(r"(^|/)\.env\.(example|sample|template)$")
PRIVATE_KEY_LINE = re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")
REVISION_RE = re.compile(r"^revision\s*(?::[^=]*)?=\s*['\"]([^'\"]+)['\"]", re.M)
DOWN_RE = re.compile(r"^down_revision\s*(?::[^=]*)?=\s*(.+)$", re.M)
QUOTED_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def git(repo: Path, *args: str, check: bool = True, stdin: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, input=stdin, capture_output=True,
    )
    if check and result.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout.decode("utf-8", "replace")


def git_ok(repo: Path, *args: str) -> int:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True).returncode


def git_path_exists(repo: Path, name: str) -> bool:
    return (repo / git(repo, "rev-parse", "--git-path", name).strip()).exists()


def current_branch(repo: Path) -> str:
    return git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()


def is_main_worktree(repo: Path) -> bool:
    git_dir = (repo / git(repo, "rev-parse", "--git-dir").strip()).resolve()
    common = (repo / git(repo, "rev-parse", "--git-common-dir").strip()).resolve()
    return git_dir == common


def in_merge(repo: Path) -> bool:
    return git_path_exists(repo, "MERGE_HEAD")


def agent_name() -> str:
    return os.environ.get("ARK_AGENT", "").strip().lower()


# ---------------------------------------------------------------- pre-commit

def check_branch(repo: Path, agent: str) -> list[str]:
    errors: list[str] = []
    branch = current_branch(repo)
    if branch == "main" and not is_main_worktree(repo):
        errors.append("main 只能在主目录 worktree 提交或合并（AGENTS.md：merge 回 main 只能在主目录做）")
    if not agent:
        return errors
    if agent not in AGENT_PREFIXES:
        errors.append(f"未知 ARK_AGENT={agent}，应为 {'/'.join(AGENT_PREFIXES)}")
        return errors
    if not branch:
        return errors  # rebase/bisect 等分离 HEAD 场景交由分支提交时把关
    if branch == "main":
        if agent != MAIN_OWNER:
            errors.append(f"{agent} 不能在 main 上提交；请在 {agent}/<topic> 分支的独立 worktree 开发")
    elif not branch.startswith(f"{agent}/"):
        errors.append(f"分支 {branch} 不属于 {agent}；禁止在别的代理的分支提交（应为 {agent}/<topic>）")
    return errors


def check_whitespace(repo: Path) -> list[str]:
    result = subprocess.run(["git", "diff", "--cached", "--check"], cwd=repo, capture_output=True)
    if result.returncode == 0:
        return []
    lines = result.stdout.decode("utf-8", "replace").strip().splitlines()
    shown = "\n    ".join(lines[:20]) + ("\n    ..." if len(lines) > 20 else "")
    return [f"暂存区存在空白错误或冲突标记（git diff --cached --check）：\n    {shown}"]


def staged_files(repo: Path) -> list[str]:
    out = git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return [p for p in out.split("\0") if p]


def check_secrets(repo: Path, files: list[str]) -> list[str]:
    errors = [
        f"禁止提交密钥类文件：{path}"
        for path in files
        if SECRET_PATH.search(path) and not SECRET_PATH_ALLOW.search(path)
    ]
    diff = git(repo, "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACMR")
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and PRIVATE_KEY_LINE.search(line):
            errors.append(f"新增内容包含私钥：{current}")
    return errors


def read_blobs(repo: Path, specs: list[str]) -> dict[str, str]:
    if not specs:
        return {}
    out = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=repo, capture_output=True,
        input="".join(f"{s}\n" for s in specs).encode("utf-8"),
    ).stdout
    blobs: dict[str, str] = {}
    pos = 0
    for spec in specs:
        end = out.index(b"\n", pos)
        header = out[pos:end].decode("utf-8", "replace").split()
        pos = end + 1
        if len(header) < 3 or header[-1] == "missing":
            continue
        size = int(header[2])
        blobs[spec] = out[pos:pos + size].decode("utf-8", "replace")
        pos += size + 1
    return blobs


def migration_graph(sources: list[str]) -> tuple[set[str], list[str]]:
    """返回 (heads, 重复 revision 列表)。"""
    revisions: list[str] = []
    downs: set[str] = set()
    for text in sources:
        rev = REVISION_RE.search(text)
        if not rev:
            continue
        revisions.append(rev.group(1))
        down = DOWN_RE.search(text)
        if down:
            downs.update(QUOTED_RE.findall(down.group(1)))
    duplicates = sorted({r for r in revisions if revisions.count(r) > 1})
    return set(revisions) - downs, duplicates


def check_migrations(repo: Path, files: list[str]) -> list[str]:
    if not any(f.startswith(MIGRATION_DIR + "/") for f in files):
        return []
    index_paths = [p for p in git(repo, "ls-files", "--", MIGRATION_DIR).splitlines() if p.endswith(".py")]
    has_head = git_ok(repo, "rev-parse", "--verify", "-q", "HEAD") == 0
    head_paths = (
        [p for p in git(repo, "ls-tree", "-r", "--name-only", "HEAD", "--", MIGRATION_DIR).splitlines()
         if p.endswith(".py")] if has_head else []
    )
    index_heads, duplicates = migration_graph(list(read_blobs(repo, [f":{p}" for p in index_paths]).values()))
    head_heads, _ = migration_graph(list(read_blobs(repo, [f"HEAD:{p}" for p in head_paths]).values()))
    errors: list[str] = []
    if duplicates:
        errors.append(f"Alembic revision 重复：{', '.join(duplicates)}")
    if len(index_heads) > max(1, len(head_heads)):
        errors.append(
            f"提交后 Alembic 将出现 {len(index_heads)} 个 head：{', '.join(sorted(index_heads))}。"
            "先查全部分支最新编号（git log --all --oneline -- backend/alembic/versions/）再接链"
        )
    return errors


def run_conventions(repo: Path, files: list[str]) -> tuple[bool, str]:
    script = repo / "scripts" / "check_conventions.py"
    if not script.is_file() or not any(f.endswith(CODE_SUFFIXES) for f in files):
        return True, ""
    result = subprocess.run(
        [sys.executable, str(script), "--strict"], cwd=repo, capture_output=True,
    )
    output = (result.stdout + result.stderr).decode("utf-8", "replace").strip().splitlines()
    return result.returncode == 0, "\n    ".join(output[-15:])


def pre_commit(repo: Path) -> int:
    agent = agent_name()
    merging = in_merge(repo)
    files = staged_files(repo)
    errors = check_branch(repo, agent)
    warnings: list[str] = []
    whitespace = check_whitespace(repo)
    # 合并提交带入的是对方分支已提交内容，空白问题只提示，避免合并被旧账卡死
    (warnings if merging else errors).extend(whitespace)
    errors += check_secrets(repo, files)
    errors += check_migrations(repo, files)
    if not merging:
        ok, tail = run_conventions(repo, files)
        if not ok:
            message = f"check_conventions --strict 未通过（检查的是整个工作区改动）：\n    {tail}"
            (errors if os.environ.get("ARK_HOOKS_STRICT") == "1" else warnings).append(message)
    return report("pre-commit", errors, warnings)


# ---------------------------------------------------------------- pre-push

def parse_push_lines(text: str) -> list[tuple[str, str, str, str]]:
    updates = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4:
            updates.append((parts[0], parts[1], parts[2], parts[3]))
    return updates


def is_fast_forward(repo: Path, remote_sha: str, local_sha: str) -> bool:
    return git_ok(repo, "merge-base", "--is-ancestor", remote_sha, local_sha) == 0


def check_push(repo: Path, agent: str, updates: list[tuple[str, str, str, str]]) -> list[str]:
    errors: list[str] = []
    approved = os.environ.get("ARK_PUSH_APPROVED") == "1"
    force_approved = os.environ.get("ARK_PUSH_FORCE_APPROVED") == "1"
    if agent and updates and not approved:
        errors.append(
            f"代理（ARK_AGENT={agent}）推送须亮哥明确授权；获授权后以 ARK_PUSH_APPROVED=1 执行本次推送"
        )
    for _local_ref, local_sha, remote_ref, remote_sha in updates:
        deleting = local_sha == ZERO_SHA
        rewriting = not deleting and remote_sha != ZERO_SHA and not is_fast_forward(repo, remote_sha, local_sha)
        protected = remote_ref in PROTECTED_BRANCHES or remote_ref.startswith("refs/tags/")
        if (deleting or rewriting) and (protected or agent) and not force_approved:
            action = "删除" if deleting else "非快进覆盖"
            errors.append(f"{action} {remote_ref} 须单独授权（ARK_PUSH_FORCE_APPROVED=1）")
        if agent and remote_ref.startswith("refs/heads/"):
            prefix = remote_ref[len("refs/heads/"):].split("/", 1)[0]
            if prefix in AGENT_PREFIXES and prefix != agent:
                errors.append(f"{agent} 不能推送别的代理的分支 {remote_ref}")
    return errors


def pre_push(repo: Path, stdin_text: str) -> int:
    return report("pre-push", check_push(repo, agent_name(), parse_push_lines(stdin_text)), [])


# ---------------------------------------------------------------- output / install

def report(stage: str, errors: list[str], warnings: list[str]) -> int:
    for message in warnings:
        print(f"[ark-hooks] {stage} 提示：{message}", file=sys.stderr)
    if not errors:
        return 0
    for message in errors:
        print(f"[ark-hooks] {stage} 拦截：{message}", file=sys.stderr)
    print("[ark-hooks] 规则见 AGENTS.md；代理不得用 --no-verify 绕过。", file=sys.stderr)
    return 1


def install(repo: Path, force: bool) -> int:
    current = git(repo, "config", "--get", "core.hooksPath", check=False).strip()
    if current and current != HOOKS_PATH and not force:
        print(f"core.hooksPath 已是 {current}，未覆盖（确认后加 --force）")
        return 1
    git(repo, "config", "core.hooksPath", HOOKS_PATH)
    print(f"已启用：core.hooksPath={HOOKS_PATH}（本仓库全部 worktree 生效）")
    return 0


def uninstall(repo: Path) -> int:
    if git(repo, "config", "--get", "core.hooksPath", check=False).strip() == HOOKS_PATH:
        git(repo, "config", "--unset", "core.hooksPath")
        print("已停用 ark git hooks")
    else:
        print("ark git hooks 未启用，无需操作")
    return 0


def status(repo: Path) -> int:
    current = git(repo, "config", "--get", "core.hooksPath", check=False).strip()
    print(f"core.hooksPath={current or '(未设置)'}; 启用={'是' if current == HOOKS_PATH else '否'}")
    print(f"ARK_AGENT={agent_name() or '(未设置，按人工处理)'}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    repo = Path.cwd()
    command = argv[0]
    if command == "pre-commit":
        return pre_commit(repo)
    if command == "pre-push":
        return pre_push(repo, sys.stdin.read())
    if command == "install":
        return install(repo, "--force" in argv[1:])
    if command == "uninstall":
        return uninstall(repo)
    if command == "status":
        return status(repo)
    print(f"未知命令：{command}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
