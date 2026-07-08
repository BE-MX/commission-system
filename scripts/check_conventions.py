#!/usr/bin/env python3
"""约定检查脚本 — 机器可查的规范不靠提示词自觉（架构评估 G-3）。

只检查增量（git diff 相对 HEAD 的新增行 + 新增文件），不翻旧账。
用法：
    python scripts/check_conventions.py            # 检查工作区未提交改动
    python scripts/check_conventions.py --base <ref>  # 检查相对某 commit 的改动
    python scripts/check_conventions.py --strict   # 红项使 exit code = 1（跑顺一周后再挂 hook）

输出分级：
    [红] 明确违规，必须修
    [黄] 需要人工判断的警告
误报是这个脚本的生死线——发现误报立即修白名单，不要教人忽略它。
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent.parent

# 鉴权依赖的合法形态（白名单，见评估 G-3 修订）
AUTH_PATTERNS = re.compile(
    r"require_permission|require_any_permission|get_current_user"
    r"|get_current_mini_user|_require_\w+|_verify_\w+"
)
# 无鉴权豁免的 router 文件（机器对机器/公开入口，均有刻意决策记录）
AUTH_EXEMPT_FILES = ("mini/router.py", "auth/router.py", "api/short_link.py", "stock/public_router.py")
# 无鉴权豁免的端点路径关键词
AUTH_EXEMPT_ROUTES = ("share", "callback", "login", "health", "print/")

FORBIDDEN_EXPO_WORDS = ["便宜", "划算", "性价比", "打折", "薅羊毛"]

# 权限动作词汇白名单（权限重设计方案第二节：新权限只允许标准动作 + 登记特例）
ALLOWED_PERM_ACTIONS = {
    "read", "write", "delete", "admin",              # 标准四动作
    "manage",                                         # ≡admin，历史用词
    "self_read", "read_all", "internal_read",         # 数据范围类
    "daily_report", "audit", "invoke", "print",       # 登记特例
    "sync", "design", "import",
    # legacy 回填行的历史动作（is_legacy=1，不再新增）
    "read_own", "settle", "export", "submit", "approve",
    "config", "logs", "backup", "assign_role",
}

# 命名宪法（docs/database.md 头部，2026-07-08）——列名禁用词 → 规范名
FORBIDDEN_COLUMN_NAMES = {
    "create_time": "created_at", "created_time": "created_at", "gmt_create": "created_at",
    "update_time": "updated_at", "updated_time": "updated_at", "gmt_modified": "updated_at",
    "create_user": "created_by", "update_user": "updated_by",
    "is_deleted": "deleted_at", "deleted_flag": "deleted_at",
    "del_flag": "deleted_at", "delete_flag": "deleted_at",
    "state": "status", "note": "remark", "notes": "remark", "comment": "remark",
    "operator": "created_by/updated_by 或 xxx_name", "operator_id": "created_by/updated_by",
}
# 业务库(lsordertest)只读投影表——无 ark_ 前缀豁免
BUSINESS_RO_TABLES = {"okki_orders", "okki_receipts", "okki_products", "okki_inventory",
                      "okki_order_items", "customer_info", "user_basic"}

RED, YELLOW = "红", "黄"


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, cwd=REPO, encoding="utf-8", errors="replace").stdout


def added_lines_by_file(base: str) -> dict[str, list[tuple[int, str]]]:
    """返回 {文件: [(新行号, 行内容)]}，含未暂存与已暂存改动。"""
    diff = sh("git", "diff", base, "--unified=0", "--no-color")
    result: dict[str, list[tuple[int, str]]] = {}
    current, lineno = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
            result.setdefault(current, [])
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++") and current:
            result[current].append((lineno, raw[1:]))
            lineno += 1
    # 未追踪的新文件整个算新增
    for f in sh("git", "ls-files", "--others", "--exclude-standard").splitlines():
        if f and f not in result:
            p = REPO / f
            if p.is_file() and p.suffix in (".py", ".vue", ".js"):
                try:
                    result[f] = list(enumerate(p.read_text(encoding="utf-8").splitlines(), 1))
                except (UnicodeDecodeError, OSError):
                    pass
    return result


def check(base: str) -> list[tuple[str, str, str]]:
    """返回 [(级别, 位置, 说明)]"""
    findings: list[tuple[str, str, str]] = []
    changes = added_lines_by_file(base)

    for file, lines in changes.items():
        posix = file.replace("\\", "/")
        is_vue_view = posix.startswith("frontend/src/views/") and posix.endswith(".vue")
        is_frontend = posix.startswith("frontend/src/")
        is_backend = posix.startswith("backend/app/")

        for n, line in lines:
            loc = f"{posix}:{n}"
            # 1.[红] 前端自建 axios（clients.js/request.js/auth.js 之外）
            if is_frontend and "axios.create" in line and not posix.endswith(("request.js", "auth.js", "clients.js")):
                findings.append((RED, loc, "自建 axios 实例——从 api/clients.js 取 client（宪法 11）"))
            # 2.[黄] views 下新增裸 hex 颜色
            if is_vue_view and re.search(r"#[0-9a-fA-F]{6}\b", line) and "var(--" not in line:
                findings.append((YELLOW, loc, "新增裸 hex 颜色——应使用 tokens.css 变量（宪法 13）"))
            # 5.[红] 吞异常
            if is_backend and re.search(r"^\s*except\s*(Exception\s*)?:\s*$", line):
                nxt = next((l for m, l in lines if m == n + 1), "")
                if re.fullmatch(r"\s*pass\s*", nxt or "pass"):
                    findings.append((RED, loc, "疑似无声吞异常（except+pass）——至少 logger+print(flush=True)（宪法 6）"))
            # 7.[黄] 共享层冻结
            if re.match(r"backend/app/(api|services|models|schemas)/[^/]+\.py$", posix) \
                    and posix.split("/")[-1] not in ("__init__.py",) and (REPO / file).exists():
                pass  # 目录级检查放循环外

        # 3.[黄] 新增 .vue 文件超 500 行
        if is_vue_view and len(lines) > 500 and not sh("git", "ls-files", file).strip():
            findings.append((YELLOW, posix, f"新页面 {len(lines)} 行 >500——拆 composables/use*.js（宪法 12）"))

        # 4.[黄] 新增 router 端点无鉴权依赖（按端点块检查）
        if is_backend and posix.endswith("router.py") and not any(x in posix for x in AUTH_EXEMPT_FILES):
            text_new = "\n".join(l for _, l in lines)
            for m in re.finditer(r'@router\.(get|post|put|delete|patch)\(\s*"([^"]*)"', text_new):
                route = m.group(2)
                if any(k in route for k in AUTH_EXEMPT_ROUTES):
                    continue
                # 端点装饰器后 ~15 行内应出现鉴权依赖
                tail = text_new[m.start(): m.start() + 800]
                if not AUTH_PATTERNS.search(tail):
                    findings.append((YELLOW, f"{posix} 端点 {route}", "新增端点未见鉴权依赖——加 require_permission 或注明豁免（宪法 3）"))

        # 8.[黄] seed 新增权限的 action 不在词汇白名单（宪法 8 / 权限方案第二节）
        if posix.endswith("auth/service.py"):
            for n, line in lines:
                m = re.search(r'\(\s*"[\w:]+"\s*,\s*"\w+"\s*,\s*"(\w+)"\s*,', line)
                if m and m.group(1) not in ALLOWED_PERM_ACTIONS:
                    findings.append((YELLOW, f"{posix}:{n}",
                                     f"新权限动作 '{m.group(1)}' 不在词汇白名单——用 read/write/delete/admin 或先登记特例"))

        # 6.[红] 迁移 revision ID 超长
        if posix.startswith("backend/alembic/versions/") and posix.endswith(".py"):
            text_new = "\n".join(l for _, l in lines)
            m = re.search(r'revision\s*=\s*"([^"]+)"', text_new)
            if m and len(m.group(1)) > 32:
                findings.append((RED, posix, f"revision ID {len(m.group(1))} 字符 >32——alembic_version 列会截断（宪法 5）"))

        # 7.[黄] 共享层新增业务文件
        if re.match(r"backend/app/(api|services|models|schemas)/[^/]+\.py$", posix) \
                and not sh("git", "ls-files", file).strip():
            findings.append((YELLOW, posix, "共享层已冻结——新业务放领域模块 app/<domain>/（宪法 1）"))

        # 9.[红/黄] 数据库命名宪法（docs/database.md 头部，2026-07-08）
        # 误报守卫：只认「真正新增」——基线版本已有同名表/列的（改存量行触发的 diff）一律跳过
        # 已知缺口（2026-07-08 对抗性审查登记，触发时按此排查而非直接忽略红项）：
        #   a) 9a 豁免判据是全文件子串（f'"{t}"'），基线里 docstring/secondary="表名" 出现同名串会误放行
        #   b) 9b 列名禁用词未豁免业务库（lsordertest）只读投影的外部列名——将来建投影时给该文件加白名单
        #   c) P2 治理把 legacy 模型搬新文件时，untracked 新文件会把存量表名报成"新表"——先 git add 建基线再跑
        #   d) --base <旧ref> 时 tracked 判断用当前索引，base 后新增已提交文件会整文件当新增（方向是误报，可接受）
        if is_backend and posix.endswith(".py") and "alembic" not in posix:
            text_new = "\n".join(l for _, l in lines)
            base_text = sh("git", "show", f"{base}:{file}") if sh("git", "ls-files", file).strip() else ""
            # 9a. 新表名必须 ark_ 前缀（__tablename__ 与 Table() 两种声明都查）
            for m in re.finditer(r'(?:__tablename__\s*=\s*|Table\(\s*)"(\w+)"', text_new):
                t = m.group(1)
                if f'"{t}"' in base_text:
                    continue
                if not t.startswith("ark_") and t not in BUSINESS_RO_TABLES:
                    findings.append((RED, posix, f'新表 "{t}" 无 ark_ 前缀——命名宪法：ark_<domain>_<entity> 复数'))
                elif t.endswith("_log"):
                    findings.append((YELLOW, posix, f'新表 "{t}" 用 _log 单数——日志类统一 _logs 复数'))
            # 9b/9c. 仅 models 文件查列定义（多行 Column 合并匹配）
            if posix.endswith("models.py") or "/models/" in posix:
                for m in re.finditer(r"(\w+)\s*=\s*Column\((?:[^()]|\([^()]*\))*\)", text_new, re.DOTALL):
                    col, defn = m.group(1), m.group(0)
                    if re.search(rf"\b{re.escape(col)}\s*=\s*Column\(", base_text):
                        continue
                    if col in FORBIDDEN_COLUMN_NAMES:
                        findings.append((RED, posix,
                                         f'新列 "{col}" 是禁用命名——用 {FORBIDDEN_COLUMN_NAMES[col]}（命名宪法）'))
                    if "comment=" not in defn and "primary_key=True" not in defn:
                        findings.append((YELLOW, posix, f'新列 "{col}" 缺 comment= 中文注释（命名宪法）'))

        # 20.[红] expo 相关文件出现品牌禁用词
        # 白名单：定义禁用词表/警示提示文案本身（含"禁用"或 FORBIDDEN 的行是元引用，不是违规使用）
        if "expo" in posix.lower():
            for n, line in lines:
                if any(k in line for k in ("禁用", "不说", "话术规范")) or "FORBIDDEN" in line.upper():
                    continue
                hit = [w for w in FORBIDDEN_EXPO_WORDS if w in line]
                if hit:
                    findings.append((RED, f"{posix}:{n}", f"expo 品牌禁用词 {hit}（宪法 20）"))

    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD", help="diff 基准（默认 HEAD=工作区改动）")
    ap.add_argument("--strict", action="store_true", help="有红项时 exit 1")
    args = ap.parse_args()

    findings = check(args.base)
    reds = [f for f in findings if f[0] == RED]
    yellows = [f for f in findings if f[0] == YELLOW]

    if not findings:
        print("check_conventions: 增量改动无违规 ✓")
        return 0
    for level, loc, msg in sorted(findings):
        print(f"[{level}] {loc}\n     {msg}")
    print(f"\n合计：红 {len(reds)} / 黄 {len(yellows)}（红=必须修，黄=人工判断）")
    if reds and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
