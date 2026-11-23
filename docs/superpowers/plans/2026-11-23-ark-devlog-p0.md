# 方舟开发动态看板 P0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 只用 Git 和全局发布账本这两类确定性数据，在方舟里做出「方舟开发动态」技术视图。它要回答四个问题：哪些在开发、哪些已提交待发布、哪些已上线、发布前要做什么。

**Architecture:**
- **采集器**：开发机上的 `scripts/devlog/` 是纯标准库 Python 脚本，只读 Git，把痕迹归并成「事项」。状态按 patch-id 内容等价计算，结果经机器 token 推到生产 `POST /api/devlog/ingest`。
- **发布账本**：全局发布成功后，由部署器在办公室调用 `python -m app.devlog.ledger_cli` 写入，不经过开发机。
- **前端**：新增 `/system/devlog` 页面，包含 KPI、看板、时间线、待发布清单和详情抽屉。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic（领域模块 `app/devlog/`）、Pydantic v2、Python 标准库（采集器）、Vue 3 + Element Plus、node:test。

**依据：** 设计稿 [docs/requirements/2026-11-23-ark-devlog-board-design.md](../../requirements/2026-11-23-ark-devlog-board-design.md)，原型 [docs/prototypes/ark-devlog-board.html](../../prototypes/ark-devlog-board.html)。

**P0 不做（留给 P1/P2，不要提前实现）：**
- 会话（Codex/Claude）、handoff 解析和对账
- 数据修复回执
- 大模型摘要和员工/客户名词典去敏
- 人工修正 overlay
- 全员更新日志

**相对设计稿 §9 的范围调整（已同步改设计稿，开工前请亮哥确认）：**
- **运行版本文件校验推迟到 P1。** 原因：版本文件要写进候选源码目录，而部署器对该目录有「无本地改动、无未知文件」的门禁，贸然写入会让发布或保留清理失败。P0 的替代保证：部署器在全部验收通过后才写账本。
- **已知缺口：恢复入口不写账本。** `release_finalize.py`、`recover_release_completion.py` 等恢复入口也能把发布标为成功，但 P0 不在这些入口写账本。缺口记入 module-notes；发生恢复发布后，用回填脚本 `--add` 手工补一条。

**分组规则说明**（对抗审查实测：main 自 09-01 起有 191 个 first-parent 合并，只有 59 个是标准的 `Merge branch 'X'`；另有 526 个直接提交）：
- P0 的「一件事」是用 Git 能确定的最好近似：
  - 能识别分支名的合并，按分支归为一件事；
  - 识别不了分支名的合并，整个合并算一件事；
  - 直接提交按「北京日期 + 模块 + 代理」归为一件事；
- 同一提交第一次归到哪件事，就记进 `.devlog_state/keymap.json`，以后一直沿用，事项键不随分支删除或 fast-forward 漂移；
- 更精确的归并靠 P1 的会话证据和人工修正。

---

## 开工前必读的项目规则（违反即返工）

- 在 worktree 里工作，分支 `claude/devlog-p0`；主目录 `commission-system` 只用于最后的合并。git 命令所在 shell 必须设 `ARK_AGENT=claude`。commit 前核对 `git rev-parse --show-toplevel`、`git branch --show-current`、`git diff --cached`。
- **禁止**在开发机上执行 `alembic upgrade`，也禁止连生产库跑写入型测试。后端测试一律用 `backend/tests/conftest.py` 提供的内存 SQLite `db` fixture。
- 采集器的 `--push`、回填的 `--apply`、计划任务注册、合并 main、push、部署，全部要等亮哥授权（见 Task 15），实现阶段只用 `--dry-run`。
- 所有业务时间用 `app.core.time.beijing_now()`。外部带偏移的时间先换算成北京时间再去掉 tzinfo（红线 23）。
- 异常不能静默吞掉：至少 `logger.warning` 加 `print(..., flush=True)`。批量循环用 savepoint（红线 6）。
- 颜色只用 `tokens.css` 变量，新页面只在 `navigation.js` 加一条 entry，API client 从 `api/clients.js` 取。

## 文件结构

| 文件 | 职责 |
|---|---|
| `backend/app/devlog/__init__.py` | 领域包 |
| `backend/app/devlog/models.py` | 5 张表：事项、证据、状态事件、发布账本、同步记录 |
| `backend/app/devlog/schemas.py` | ingest 白名单 schema（`extra="forbid"`，字段限长、限格式） |
| `backend/app/devlog/machine_auth.py` | 采集器机器 token 校验（SHA-256 列表，支持轮换） |
| `backend/app/devlog/ingest_service.py` | upsert 事项、替换证据、记录状态事件、写同步记录 |
| `backend/app/devlog/release_service.py` | 发布账本写入（幂等）与列表 |
| `backend/app/devlog/query_service.py` | summary / detail / pending / health 查询口径 |
| `backend/app/devlog/ledger_cli.py` | 部署器在办公室调用的账本写入入口（stdin JSON） |
| `backend/app/devlog/router.py` | 用户端点（`devlog:read`）+ 机器端点 |
| `backend/alembic/versions/278_devlog_tables.py` | 建表迁移（编号以 Task 0 实查为准） |
| `deploy/devlog_ledger.py` | 部署器侧：发布成功后调用 ledger_cli，失败只告警 |
| `scripts/devlog/gitdata.py` | 只读 Git：分支、worktree、提交、patch-id |
| `scripts/devlog/redact.py` | 标题去敏规则 |
| `scripts/devlog/classify.py` | 类型 / 模块 / 代理推断 |
| `scripts/devlog/grouping.py` | 痕迹 → 事项归并 |
| `scripts/devlog/status.py` | 内容等价状态判定 + 上线前提提取 |
| `scripts/devlog/client.py` | 读本地配置、调生产机器端点 |
| `scripts/devlog/collect.py` | CLI：采集 → 写 payload → 可选推送 |
| `scripts/devlog/backfill_releases.py` | 从 `.deploy_state/global-release-*/revision.json` 回填账本 |
| `frontend/src/api/devlog.js` | 前端 API |
| `frontend/src/views/devlog/devlogPresentation.js` | 纯展示函数（文案、日期范围、能否发布） |
| `frontend/src/views/devlog/composables/useDevlogBoard.js` | 页面状态与数据加载 |
| `frontend/src/views/devlog/DevlogBoard.vue` | 页面 |
| `frontend/src/views/devlog/DevlogItemDrawer.vue` | 详情抽屉 |

---

### Task 0: Worktree 与迁移编号

**Files:** 无代码改动

- [ ] **Step 1: 建 worktree**

```powershell
$env:ARK_AGENT='claude'
git -C D:\MyProgram\commission-system worktree add D:\MyProgram\commission-system-devlog-p0 -b claude/devlog-p0 main
```

- [ ] **Step 2: 查所有分支的最新迁移编号（AGENTS.md 规则）**

```powershell
git -C D:\MyProgram\commission-system-devlog-p0 log --all --oneline -- backend/alembic/versions/ | Select-Object -First 15
Get-ChildItem D:\MyProgram\commission-system-devlog-p0\backend\alembic\versions -Filter "27*" | Sort-Object Name -Descending | Select-Object -First 5 Name
```

Expected: 2026-11-23 的 main 头是 `277_cross_border_review`。如果任何分支已经出现 `278_*`，本计划所有 `278_devlog_tables` / `down_revision = "277_cross_border_review"` 都顺延到下一个空号，并把 `down_revision` 改成那个分支合并后的头。后面所有步骤都在 worktree `D:\MyProgram\commission-system-devlog-p0` 下执行。

---

### Task 1: 配置、权限、忽略目录

**Files:**
- Modify: `backend/app/core/config.py`（`AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON` 附近）
- Modify: `backend/.env.example`
- Modify: `backend/app/auth/service.py:394-395` 附近（`seed_role_permissions` 列表）
- Modify: `.gitignore`

- [ ] **Step 1: config.py 加配置项**（放在 `AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON: str = ""` 的下一行）

```python
    # 方舟开发动态：开发机采集器 token 的 SHA-256（小写 hex），逗号分隔，可新旧并存以便轮换
    DEVLOG_INGEST_TOKEN_HASHES: str = Field(default="", repr=False)
    # 发布账本回填开关：仅在人工核对回填清单后临时打开，回填完立即关闭（防止常驻 token 伪造「已发布」）
    DEVLOG_BACKFILL_ENABLED: bool = False
```

- [ ] **Step 2: .env.example 追加**（文件末尾，注意用户已有未提交改动，只追加不改其他行）

```
# 方舟开发动态采集器 token 的 SHA-256，逗号分隔支持轮换；明文 token 只放开发机 .devlog_state/collector.json
DEVLOG_INGEST_TOKEN_HASHES=
# 发布账本回填开关，回填完立即改回 false
DEVLOG_BACKFILL_ENABLED=false
```

- [ ] **Step 3: seed 权限**（紧跟 `cross_border:write` 那一行后面）

```python
        ("devlog:read", "devlog", "read", "查看方舟开发动态（事项、发布账本、待发布清单）"),
```

- [ ] **Step 4: .gitignore 追加**

```
/.devlog_state/
```

- [ ] **Step 5: 跑约定检查**

Run: `python scripts/check_conventions.py`
Expected: 本次改动无红项

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/config.py backend/.env.example backend/app/auth/service.py .gitignore
git commit -m "Add devlog permission, ingest token setting and local state ignore"
```

---

### Task 2: 模型与迁移

**Files:**
- Create: `backend/app/devlog/__init__.py`
- Create: `backend/app/devlog/models.py`
- Create: `backend/alembic/versions/278_devlog_tables.py`
- Modify: `backend/alembic/env.py:22` 附近
- Test: `backend/tests/test_devlog_models.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_devlog_models.py
"""devlog 表能在共享 SQLite fixture 上建出并往返读写。"""
from datetime import datetime

from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogRelease, DevlogSyncRun


def test_tables_round_trip(db):
    item = DevlogItem(item_key="branch:codex/demo", title="Add demo", item_type="feature", module="invoice",
                      agent="codex", status="pending_merge", status_at=datetime(2026, 11, 23, 9),
                      last_activity_at=datetime(2026, 11, 23, 9), preconditions={}, fingerprint="0" * 64)
    db.add(item)
    db.flush()
    db.add(DevlogEvidence(item_id=item.id, kind="commit", ref="a" * 40, occurred_at=datetime(2026, 11, 23, 9)))
    db.add(DevlogItemEvent(item_id=item.id, from_status=None, to_status="pending_merge",
                           occurred_at=datetime(2026, 11, 23, 9), recorded_at=datetime(2026, 11, 23, 9)))
    db.add(DevlogRelease(revision="b" * 40, release_id="r1", scope="office-and-cloud",
                         released_at=datetime(2026, 11, 23, 14), source="deployer"))
    db.add(DevlogSyncRun(started_at=datetime(2026, 11, 23, 15), finished_at=datetime(2026, 11, 23, 15, 1),
                         sources=[{"name": "git", "ok": True}], item_count=1, failed_keys=[]))
    db.flush()
    assert db.query(DevlogItem).one().stale is False
    assert db.query(DevlogItem).one().superseded is False
    assert db.query(DevlogEvidence).count() == 1
```

- [ ] **Step 2: 确认失败**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_models.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.devlog'`

- [ ] **Step 3: 写模型**

```python
# backend/app/devlog/__init__.py
"""方舟开发动态：开发事项、发布账本与采集同步。"""
```

```python
# backend/app/devlog/models.py
"""开发动态的事项、证据、状态事件、全局发布账本与采集同步记录。

状态只由采集器按 Git 证据计算后上报，服务端不推断；证据只存结构化标识，不存任何原文。
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint

from app.core.database import Base
from app.core.time import beijing_now

ITEM_STATUSES = ("dev", "pending_merge", "pending_push", "pending_release", "released")
GLOBAL_SCOPE = "office-and-cloud"


class DevlogItem(Base):
    __tablename__ = "ark_devlog_items"
    __table_args__ = {"comment": "开发动态事项（一件事）"}

    id = Column(Integer, primary_key=True, comment="事项主键")
    item_key = Column(String(191), nullable=False, unique=True, comment="采集器稳定键，如 branch:codex/x、merge:<sha>、commit:<sha>")
    title = Column(String(80), nullable=False, comment="去敏后的标题")
    item_type = Column(String(16), nullable=False, comment="feature/improve/bug/data/ops/docs")
    module = Column(String(40), nullable=False, default="", comment="影响模块标识，取源码领域目录名")
    agent = Column(String(16), nullable=False, default="unknown", comment="codex/claude/kimi/accio/unknown")
    status = Column(String(16), nullable=False, comment="dev/pending_merge/pending_push/pending_release/released")
    status_at = Column(DateTime, nullable=False, comment="进入当前状态的北京时间（采集器按证据估计）")
    last_activity_at = Column(DateTime, nullable=False, comment="最后一条证据的北京时间")
    stale = Column(Boolean, nullable=False, default=False, comment="未发布且 14 天无新证据")
    superseded = Column(Boolean, nullable=False, default=False, comment="在完整快照中已不存在（分支清理等），默认不展示，不删除")
    unmerged_hotfix = Column(Boolean, nullable=False, default=False, comment="已进全局发布但内容未回合 main")
    released_revision = Column(String(40), nullable=True, comment="首次覆盖本事项的全局发布 revision")
    preconditions = Column(JSON, nullable=False, comment="上线前提：migrations/config_keys/permissions")
    fingerprint = Column(String(64), nullable=False, comment="证据与状态指纹，相同则跳过更新")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="首次采集北京时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="最后更新北京时间")


class DevlogEvidence(Base):
    __tablename__ = "ark_devlog_evidences"
    __table_args__ = (
        UniqueConstraint("item_id", "kind", "ref", name="uq_devlog_evidence"),
        {"comment": "开发动态事项的结构化证据（只存标识，不存原文）"},
    )

    id = Column(Integer, primary_key=True, comment="证据主键")
    item_id = Column(Integer, ForeignKey("ark_devlog_items.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属事项")
    kind = Column(String(16), nullable=False, comment="branch/commit/release/worktree")
    ref = Column(String(120), nullable=False, comment="分支名、commit sha、发布 revision 或 worktree 标识")
    occurred_at = Column(DateTime, nullable=False, comment="证据发生北京时间")


class DevlogItemEvent(Base):
    __tablename__ = "ark_devlog_item_events"
    __table_args__ = (
        Index("idx_devlog_event_time", "occurred_at"),
        {"comment": "开发动态事项状态变化事件，统计按事件时间落桶"},
    )

    id = Column(Integer, primary_key=True, comment="事件主键")
    item_id = Column(Integer, ForeignKey("ark_devlog_items.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属事项")
    from_status = Column(String(16), nullable=True, comment="变化前状态，首次出现为空")
    to_status = Column(String(16), nullable=False, comment="变化后状态")
    occurred_at = Column(DateTime, nullable=False, comment="状态发生北京时间")
    recorded_at = Column(DateTime, nullable=False, default=beijing_now, comment="服务端记录北京时间")


class DevlogRelease(Base):
    __tablename__ = "ark_devlog_releases"
    __table_args__ = {"comment": "方舟发布账本（部署器写入或人工回填）"}

    id = Column(Integer, primary_key=True, comment="账本主键")
    revision = Column(String(40), nullable=False, index=True, comment="实际发布的完整 commit")
    release_id = Column(String(64), nullable=False, unique=True, comment="部署器发布身份或回填标识")
    scope = Column(String(20), nullable=False, comment="office-and-cloud 为全局发布；cloud-only 等为专项")
    released_at = Column(DateTime, nullable=False, comment="发布验收通过北京时间")
    source = Column(String(16), nullable=False, comment="deployer/backfill")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="写入北京时间")


class DevlogSyncRun(Base):
    __tablename__ = "ark_devlog_sync_runs"
    __table_args__ = {"comment": "开发机采集器每次上报记录"}

    id = Column(Integer, primary_key=True, comment="同步记录主键")
    started_at = Column(DateTime, nullable=False, comment="采集开始北京时间")
    finished_at = Column(DateTime, nullable=False, comment="采集结束北京时间")
    sources = Column(JSON, nullable=False, comment="各来源读取结果 [{name, ok, detail}]")
    item_count = Column(Integer, nullable=False, comment="本次上报事项数")
    failed_keys = Column(JSON, nullable=False, comment="服务端写入失败的事项键")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="服务端接收北京时间")
```

- [ ] **Step 4: alembic/env.py 注册模型**（在 `import app.cross_border.models  # noqa: F401` 下一行）

```python
import app.devlog.models  # noqa: F401
```

- [ ] **Step 5: 写迁移**

```python
# backend/alembic/versions/278_devlog_tables.py
"""方舟开发动态：事项、证据、状态事件、发布账本、同步记录。"""
from alembic import op
import sqlalchemy as sa

revision = "278_devlog_tables"
down_revision = "277_cross_border_review"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ark_devlog_items",
        sa.Column("id", sa.Integer(), nullable=False, comment="事项主键"),
        sa.Column("item_key", sa.String(191), nullable=False, comment="采集器稳定键，如 branch:codex/x、merge:<sha>、commit:<sha>"),
        sa.Column("title", sa.String(80), nullable=False, comment="去敏后的标题"),
        sa.Column("item_type", sa.String(16), nullable=False, comment="feature/improve/bug/data/ops/docs"),
        sa.Column("module", sa.String(40), nullable=False, comment="影响模块标识，取源码领域目录名"),
        sa.Column("agent", sa.String(16), nullable=False, comment="codex/claude/kimi/accio/unknown"),
        sa.Column("status", sa.String(16), nullable=False, comment="dev/pending_merge/pending_push/pending_release/released"),
        sa.Column("status_at", sa.DateTime(), nullable=False, comment="进入当前状态的北京时间（采集器按证据估计）"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False, comment="最后一条证据的北京时间"),
        sa.Column("stale", sa.Boolean(), nullable=False, comment="未发布且 14 天无新证据"),
        sa.Column("superseded", sa.Boolean(), nullable=False, comment="在完整快照中已不存在（分支清理等），默认不展示，不删除"),
        sa.Column("unmerged_hotfix", sa.Boolean(), nullable=False, comment="已进全局发布但内容未回合 main"),
        sa.Column("released_revision", sa.String(40), nullable=True, comment="首次覆盖本事项的全局发布 revision"),
        sa.Column("preconditions", sa.JSON(), nullable=False, comment="上线前提：migrations/config_keys/permissions"),
        sa.Column("fingerprint", sa.String(64), nullable=False, comment="证据与状态指纹，相同则跳过更新"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="首次采集北京时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="最后更新北京时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_key"),
        comment="开发动态事项（一件事）",
    )
    op.create_table(
        "ark_devlog_evidences",
        sa.Column("id", sa.Integer(), nullable=False, comment="证据主键"),
        sa.Column("item_id", sa.Integer(), nullable=False, comment="所属事项"),
        sa.Column("kind", sa.String(16), nullable=False, comment="branch/commit/release/worktree"),
        sa.Column("ref", sa.String(120), nullable=False, comment="分支名、commit sha、发布 revision 或 worktree 标识"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, comment="证据发生北京时间"),
        sa.ForeignKeyConstraint(["item_id"], ["ark_devlog_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", "kind", "ref", name="uq_devlog_evidence"),
        comment="开发动态事项的结构化证据（只存标识，不存原文）",
    )
    op.create_index("ix_ark_devlog_evidences_item_id", "ark_devlog_evidences", ["item_id"])
    op.create_table(
        "ark_devlog_item_events",
        sa.Column("id", sa.Integer(), nullable=False, comment="事件主键"),
        sa.Column("item_id", sa.Integer(), nullable=False, comment="所属事项"),
        sa.Column("from_status", sa.String(16), nullable=True, comment="变化前状态，首次出现为空"),
        sa.Column("to_status", sa.String(16), nullable=False, comment="变化后状态"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, comment="状态发生北京时间"),
        sa.Column("recorded_at", sa.DateTime(), nullable=False, comment="服务端记录北京时间"),
        sa.ForeignKeyConstraint(["item_id"], ["ark_devlog_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="开发动态事项状态变化事件，统计按事件时间落桶",
    )
    op.create_index("ix_ark_devlog_item_events_item_id", "ark_devlog_item_events", ["item_id"])
    op.create_index("idx_devlog_event_time", "ark_devlog_item_events", ["occurred_at"])
    op.create_table(
        "ark_devlog_releases",
        sa.Column("id", sa.Integer(), nullable=False, comment="账本主键"),
        sa.Column("revision", sa.String(40), nullable=False, comment="实际发布的完整 commit"),
        sa.Column("release_id", sa.String(64), nullable=False, comment="部署器发布身份或回填标识"),
        sa.Column("scope", sa.String(20), nullable=False, comment="office-and-cloud 为全局发布；cloud-only 等为专项"),
        sa.Column("released_at", sa.DateTime(), nullable=False, comment="发布验收通过北京时间"),
        sa.Column("source", sa.String(16), nullable=False, comment="deployer/backfill"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="写入北京时间"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("release_id"),
        comment="方舟发布账本（部署器写入或人工回填）",
    )
    op.create_index("ix_ark_devlog_releases_revision", "ark_devlog_releases", ["revision"])
    op.create_table(
        "ark_devlog_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False, comment="同步记录主键"),
        sa.Column("started_at", sa.DateTime(), nullable=False, comment="采集开始北京时间"),
        sa.Column("finished_at", sa.DateTime(), nullable=False, comment="采集结束北京时间"),
        sa.Column("sources", sa.JSON(), nullable=False, comment="各来源读取结果 [{name, ok, detail}]"),
        sa.Column("item_count", sa.Integer(), nullable=False, comment="本次上报事项数"),
        sa.Column("failed_keys", sa.JSON(), nullable=False, comment="服务端写入失败的事项键"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="服务端接收北京时间"),
        sa.PrimaryKeyConstraint("id"),
        comment="开发机采集器每次上报记录",
    )


def downgrade():
    op.drop_table("ark_devlog_sync_runs")
    op.drop_index("ix_ark_devlog_releases_revision", table_name="ark_devlog_releases")
    op.drop_table("ark_devlog_releases")
    op.drop_index("idx_devlog_event_time", table_name="ark_devlog_item_events")
    op.drop_index("ix_ark_devlog_item_events_item_id", table_name="ark_devlog_item_events")
    op.drop_table("ark_devlog_item_events")
    op.drop_index("ix_ark_devlog_evidences_item_id", table_name="ark_devlog_evidences")
    op.drop_table("ark_devlog_evidences")
    op.drop_table("ark_devlog_items")
```

迁移自查（MySQL DDL 不可回滚）：只新建表，不动现有表；FK 是 `Integer` 指向 `Integer` 主键，类型一致；revision ID 17 个字符，不超过 32。

- [ ] **Step 6: 测试通过 + 迁移链只读校验**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_models.py -q`
Expected: PASS

Run: `cd backend; .venv\Scripts\python.exe -m alembic heads`
Expected: 只有一个 head，即 `278_devlog_tables`。`alembic heads` 只读脚本目录，不连库；**不要**执行 `upgrade`。

- [ ] **Step 7: Commit**

```powershell
git add backend/app/devlog/__init__.py backend/app/devlog/models.py backend/alembic/versions/278_devlog_tables.py backend/alembic/env.py backend/tests/test_devlog_models.py
git commit -m "Add devlog item, evidence, event, release ledger and sync run tables"
```

---

### Task 3: Ingest schema 与机器鉴权

**Files:**
- Create: `backend/app/devlog/schemas.py`
- Create: `backend/app/devlog/machine_auth.py`
- Test: `backend/tests/test_devlog_schemas.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_devlog_schemas.py
"""ingest 只接受白名单字段；未知字段、超长文本、非法键整批拒收。机器 token 支持轮换。"""
import hashlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import get_settings
from app.devlog.machine_auth import _require_devlog_machine
from app.devlog.schemas import IngestIn

ITEM = {
    "key": "branch:codex/cross-border-review", "title": "Add 9610 cross-border review", "type": "feature",
    "module": "cross_border", "agent": "codex", "status": "pending_release",
    "status_at": "2026-11-23T09:05:00", "last_activity_at": "2026-11-23T09:05:00",
    "fingerprint": "a" * 64, "evidences": [{"kind": "commit", "ref": "b" * 40, "at": "2026-11-23T09:05:00"}],
}
RUN = {"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
       "sources": [{"name": "git", "ok": True}], "items": [ITEM]}


def test_valid_payload_parses():
    payload = IngestIn.model_validate(RUN)
    assert payload.items[0].preconditions.migrations == []


@pytest.mark.parametrize("patch", [
    {"raw_text": "会话原文"},                       # 未知字段
    {"title": "x" * 41},                            # 超长标题
    {"key": "session:abc"},                         # 非法键前缀
    {"evidences": [{"kind": "session", "ref": "x", "at": "2026-11-23T09:00:00"}]},  # 非法证据类型
    {"evidences": [{"kind": "commit", "ref": "客户张三", "at": "2026-11-23T09:00:00"}]},  # 证据只允许标识字符
])
def test_rejects_non_whitelisted_content(patch):
    with pytest.raises(ValidationError):
        IngestIn.model_validate({**RUN, "items": [{**ITEM, **patch}]})


def test_rejects_duplicate_keys_in_one_payload():
    with pytest.raises(ValidationError):
        IngestIn.model_validate({**RUN, "items": [ITEM, ITEM]})


def test_batch_key_and_snapshot_flag():
    payload = IngestIn.model_validate({**RUN, "snapshot": True, "items": [{**ITEM, "key": "batch:20261123-invoice-codex"}]})
    assert payload.snapshot is True


def test_machine_token_accepts_any_registered_hash(monkeypatch):
    old, new = "o" * 32, "n" * 32
    hashes = ",".join(hashlib.sha256(t.encode()).hexdigest() for t in (old, new))
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashes)
    assert _require_devlog_machine(x_devlog_token=old) is None
    assert _require_devlog_machine(x_devlog_token=new) is None
    with pytest.raises(HTTPException) as err:
        _require_devlog_machine(x_devlog_token="z" * 32)
    assert err.value.status_code == 401


def test_machine_token_rejected_when_unconfigured(monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", "")
    with pytest.raises(HTTPException):
        _require_devlog_machine(x_devlog_token="o" * 32)
```

- [ ] **Step 2: 确认失败**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_schemas.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.devlog.schemas'`

- [ ] **Step 3: 实现 schema**

```python
# backend/app/devlog/schemas.py
"""采集器上报白名单：只收结构化标识和去敏后的短文本，未知字段与超限整批拒收。"""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ItemStatus = Literal["dev", "pending_merge", "pending_push", "pending_release", "released"]
ItemType = Literal["feature", "improve", "bug", "data", "ops", "docs"]
Agent = Literal["codex", "claude", "kimi", "accio", "unknown"]

MigrationId = Annotated[str, Field(max_length=64, pattern=r"^[A-Za-z0-9_]+$")]
ConfigKey = Annotated[str, Field(max_length=64, pattern=r"^[A-Z][A-Z0-9_]+$")]
PermissionCode = Annotated[str, Field(max_length=64, pattern=r"^[a-z0-9_]+:[a-z0-9_]+$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceIn(Strict):
    kind: Literal["branch", "commit", "release", "worktree"]
    ref: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._/@+-]+$")
    at: datetime


class Preconditions(Strict):
    migrations: list[MigrationId] = Field(default_factory=list, max_length=20)
    config_keys: list[ConfigKey] = Field(default_factory=list, max_length=20)
    permissions: list[PermissionCode] = Field(default_factory=list, max_length=20)


class ItemIn(Strict):
    key: str = Field(max_length=191, pattern=r"^(branch|merge|commit|batch):[A-Za-z0-9._/@+-]+$")
    title: str = Field(min_length=1, max_length=40)
    type: ItemType
    module: str = Field(default="", max_length=40, pattern=r"^[a-z0-9_]*$")
    agent: Agent = "unknown"
    status: ItemStatus
    status_at: datetime
    last_activity_at: datetime
    stale: bool = False
    unmerged_hotfix: bool = False
    released_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    preconditions: Preconditions = Field(default_factory=Preconditions)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidences: list[EvidenceIn] = Field(default_factory=list, max_length=60)


class SourceState(Strict):
    name: Literal["git", "fetch", "releases"]
    ok: bool
    detail: str = Field(default="", max_length=120)


class IngestIn(Strict):
    started_at: datetime
    finished_at: datetime
    # True 表示 Git 源完整读取成功、items 是全量：服务端把缺席事项标为 superseded（不删除）
    snapshot: bool = False
    sources: list[SourceState] = Field(max_length=10)
    items: list[ItemIn] = Field(max_length=3000)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [item.key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("同一次上报里事项键重复")
        return self


class ReleaseIn(Strict):
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    release_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    scope: Literal["office-and-cloud", "cloud-only"]
    released_at: datetime


class ReleaseBackfillIn(Strict):
    items: list[ReleaseIn] = Field(max_length=500)


class SummaryQuery(Strict):
    start: date
    end: date
    type: ItemType | None = None
    module: str | None = Field(default=None, max_length=40)
    agent: Agent | None = None
```

- [ ] **Step 4: 实现机器鉴权**

```python
# backend/app/devlog/machine_auth.py
"""开发机采集器的机器对机器鉴权（红线 3 白名单：无用户身份，凭 token 的 SHA-256 列表校验）。

Settings.DEVLOG_INGEST_TOKEN_HASHES 允许同时登记新旧两个哈希，轮换时先加新、改开发机、再删旧。
"""
import hashlib
import hmac

from fastapi import Header, HTTPException, Request

from app.core.config import get_settings

MAX_BODY_BYTES = 4 * 1024 * 1024


def _require_devlog_machine(x_devlog_token: str | None = Header(default=None)) -> None:
    hashes = [value.strip().lower() for value in get_settings().DEVLOG_INGEST_TOKEN_HASHES.split(",") if value.strip()]
    if not hashes or not x_devlog_token or len(x_devlog_token) < 24:
        raise HTTPException(status_code=401, detail="采集器凭证无效")
    digest = hashlib.sha256(x_devlog_token.encode("utf-8")).hexdigest()
    matched = False
    for expected in hashes:
        matched = hmac.compare_digest(digest, expected) or matched
    if not matched:
        raise HTTPException(status_code=401, detail="采集器凭证无效")


def _require_small_body(request: Request) -> None:
    length = request.headers.get("content-length")
    if length is None or not length.isdigit() or int(length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="上报内容超过上限或缺少长度")
```

- [ ] **Step 5: 测试通过**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_schemas.py -q`
Expected: PASS（10 passed）

- [ ] **Step 6: Commit**

```powershell
git add backend/app/devlog/schemas.py backend/app/devlog/machine_auth.py backend/tests/test_devlog_schemas.py
git commit -m "Add devlog ingest whitelist schema and rotating machine token auth"
```

---

### Task 4: Ingest service

**Files:**
- Create: `backend/app/devlog/ingest_service.py`
- Test: `backend/tests/test_devlog_ingest.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_devlog_ingest.py
"""upsert、状态事件、缺席不删除、指纹相同跳过、外部偏移时间换算北京时间。"""
from datetime import datetime

from app.devlog.ingest_service import ingest
from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogSyncRun
from app.devlog.schemas import IngestIn


def item(key="branch:codex/a", status="pending_merge", fingerprint="a" * 64, **extra):
    return {"key": key, "title": "Add thing", "type": "feature", "module": "invoice", "agent": "codex",
            "status": status, "status_at": "2026-11-23T09:00:00", "last_activity_at": "2026-11-23T09:00:00",
            "fingerprint": fingerprint, "evidences": [{"kind": "commit", "ref": "c" * 40, "at": "2026-11-23T09:00:00"}],
            **extra}


def run(*items):
    return IngestIn.model_validate({"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
                                    "sources": [{"name": "git", "ok": True}], "items": list(items)})


def test_first_ingest_creates_item_event_and_sync_run(db):
    result = ingest(db, run(item()))
    assert result == {"created": 1, "updated": 0, "unchanged": 0, "transitions": 1, "failed": []}
    event = db.query(DevlogItemEvent).one()
    assert (event.from_status, event.to_status) == (None, "pending_merge")
    assert db.query(DevlogEvidence).count() == 1
    assert db.query(DevlogSyncRun).one().item_count == 1


def test_status_change_records_transition_and_same_fingerprint_is_skipped(db):
    ingest(db, run(item()))
    assert ingest(db, run(item()))["unchanged"] == 1
    result = ingest(db, run(item(status="released", fingerprint="b" * 64, released_revision="d" * 40,
                                 status_at="2026-11-23T14:02:00")))
    assert result["transitions"] == 1
    last = db.query(DevlogItemEvent).order_by(DevlogItemEvent.id.desc()).first()
    assert (last.from_status, last.to_status, last.occurred_at) == ("pending_merge", "released", datetime(2026, 11, 23, 14, 2))


def test_absent_items_are_not_deleted_or_downgraded(db):
    ingest(db, run(item(), item(key="branch:codex/b")))
    ingest(db, run(item()))
    assert db.query(DevlogItem).count() == 2
    assert db.query(DevlogItem).filter_by(item_key="branch:codex/b").one().superseded is False


def test_full_snapshot_marks_absent_items_superseded_and_revives_on_return(db):
    ingest(db, run(item(), item(key="branch:codex/b")))
    full = run(item())
    full.snapshot = True
    ingest(db, full)
    row = db.query(DevlogItem).filter_by(item_key="branch:codex/b").one()
    assert row.superseded is True and row.status == "pending_merge"   # 不删除、不降级
    back = run(item(), item(key="branch:codex/b"))
    back.snapshot = True
    ingest(db, back)
    db.refresh(row)
    assert row.superseded is False


def test_snapshot_ignored_when_git_source_failed(db):
    ingest(db, run(item(), item(key="branch:codex/b")))
    broken = IngestIn.model_validate({"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
                                      "snapshot": True, "sources": [{"name": "git", "ok": False}], "items": [item()]})
    ingest(db, broken)
    assert db.query(DevlogItem).filter_by(superseded=True).count() == 0


def test_offset_times_convert_to_beijing_across_midnight(db):
    # 非东八区来源的 16:30Z = 北京次日 00:30，必须落在 11-23
    ingest(db, run(item(status_at="2026-11-22T16:30:00+00:00", last_activity_at="2026-11-22T16:30:00Z")))
    row = db.query(DevlogItem).one()
    assert row.status_at == datetime(2026, 11, 23, 0, 30)
    assert row.status_at.tzinfo is None


def test_one_bad_item_does_not_block_others(db, monkeypatch):
    import app.devlog.ingest_service as service
    original = service._upsert

    def flaky(db_, item_in, now):
        if item_in.key.endswith("/bad"):
            raise RuntimeError("boom")
        return original(db_, item_in, now)

    monkeypatch.setattr(service, "_upsert", flaky)
    result = ingest(db, run(item(key="branch:codex/bad"), item(key="branch:codex/good")))
    assert result["failed"] == ["branch:codex/bad"] and result["created"] == 1
    assert db.query(DevlogSyncRun).one().failed_keys == ["branch:codex/bad"]
```

- [ ] **Step 2: 确认失败**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_ingest.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.devlog.ingest_service'`

- [ ] **Step 3: 实现**

```python
# backend/app/devlog/ingest_service.py
"""采集器上报落库：按 item_key upsert，状态变化写事件，上报里缺席的事项保持原样（缺源不等于消失）。"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.time import beijing_now, to_beijing_naive
from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogSyncRun
from app.devlog.schemas import IngestIn, ItemIn

logger = logging.getLogger(__name__)


def _bj(value: datetime) -> datetime:
    return to_beijing_naive(value, naive_is_beijing=True)


def _upsert(db: Session, item: ItemIn, now: datetime) -> str:
    row = db.query(DevlogItem).filter(DevlogItem.item_key == item.key).one_or_none()
    if (row is not None and row.fingerprint == item.fingerprint and row.status == item.status
            and row.stale == item.stale and not row.superseded):
        return "unchanged"
    outcome = "updated" if row is not None else "created"
    previous = row.status if row is not None else None
    if row is None:
        row = DevlogItem(item_key=item.key, created_at=now)
        db.add(row)
    row.title = item.title
    row.item_type = item.type
    row.module = item.module
    row.agent = item.agent
    row.status = item.status
    row.status_at = _bj(item.status_at)
    row.last_activity_at = _bj(item.last_activity_at)
    row.stale = item.stale
    row.superseded = False
    row.unmerged_hotfix = item.unmerged_hotfix
    row.released_revision = item.released_revision
    row.preconditions = item.preconditions.model_dump()
    row.fingerprint = item.fingerprint
    row.updated_at = now
    db.flush()
    if previous != item.status:
        db.add(DevlogItemEvent(item_id=row.id, from_status=previous, to_status=item.status,
                               occurred_at=_bj(item.status_at), recorded_at=now))
    db.query(DevlogEvidence).filter(DevlogEvidence.item_id == row.id).delete(synchronize_session=False)
    seen = set()
    for evidence in item.evidences:
        if (evidence.kind, evidence.ref) in seen:
            continue
        seen.add((evidence.kind, evidence.ref))
        db.add(DevlogEvidence(item_id=row.id, kind=evidence.kind, ref=evidence.ref, occurred_at=_bj(evidence.at)))
    db.flush()
    return outcome + ("+transition" if previous != item.status else "")


def ingest(db: Session, payload: IngestIn) -> dict:
    now = beijing_now()
    counts = {"created": 0, "updated": 0, "unchanged": 0, "transitions": 0, "failed": []}
    for item in payload.items:
        try:
            with db.begin_nested():
                outcome = _upsert(db, item, now)
        except Exception as exc:  # 单条失败隔离在 savepoint 内，继续处理其余事项
            logger.warning("devlog ingest item failed key=%s error=%s", item.key, type(exc).__name__)
            print(f"[devlog] ingest item failed key={item.key} error={type(exc).__name__}", flush=True)
            counts["failed"].append(item.key)
            continue
        base, _, transition = outcome.partition("+")
        counts[base] += 1
        if transition:
            counts["transitions"] += 1
    git_ok = any(source.name == "git" and source.ok for source in payload.sources)
    if payload.snapshot and git_ok and not counts["failed"]:
        present = [item.key for item in payload.items]
        (db.query(DevlogItem)
         .filter(DevlogItem.superseded.is_(False), DevlogItem.item_key.notin_(present or [""]))
         .update({DevlogItem.superseded: True, DevlogItem.updated_at: now}, synchronize_session=False))
    db.add(DevlogSyncRun(started_at=_bj(payload.started_at), finished_at=_bj(payload.finished_at),
                         sources=[source.model_dump() for source in payload.sources],
                         item_count=len(payload.items), failed_keys=counts["failed"], created_at=now))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return counts
```

- [ ] **Step 4: 测试通过**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_ingest.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: Commit**

```powershell
git add backend/app/devlog/ingest_service.py backend/tests/test_devlog_ingest.py
git commit -m "Ingest devlog items with transition events and per-item savepoints"
```

---

### Task 5: 发布账本 service 与 ledger CLI

**Files:**
- Create: `backend/app/devlog/release_service.py`
- Create: `backend/app/devlog/ledger_cli.py`
- Test: `backend/tests/test_devlog_releases.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_devlog_releases.py
"""账本幂等写入；只有 office-and-cloud 算全局发布；CLI 读 stdin JSON。"""
import io
import json
from datetime import datetime

from app.devlog import ledger_cli
from app.devlog.models import DevlogRelease
from app.devlog.release_service import latest_global, list_releases, record_release

REV = "d1f5bbb7f83f0f8d96daf664d2c621bd0be61a3d"


def test_record_is_idempotent_by_release_id(db):
    assert record_release(db, revision=REV, release_id="7dbf", scope="office-and-cloud",
                          released_at=datetime(2026, 11, 23, 14, 2), source="deployer") is True
    assert record_release(db, revision=REV, release_id="7dbf", scope="office-and-cloud",
                          released_at=datetime(2026, 11, 23, 14, 2), source="deployer") is False
    assert db.query(DevlogRelease).count() == 1


def test_latest_global_ignores_partial_scope(db):
    record_release(db, revision=REV, release_id="g", scope="office-and-cloud", released_at=datetime(2026, 11, 23, 14), source="deployer")
    record_release(db, revision="e" * 40, release_id="c", scope="cloud-only", released_at=datetime(2026, 11, 23, 16), source="deployer")
    assert latest_global(db)["revision"] == REV
    assert [r["scope"] for r in list_releases(db)] == ["office-and-cloud", "cloud-only"]


def test_cli_reads_stdin_and_uses_beijing_now(db, monkeypatch, capsys):
    monkeypatch.setattr(ledger_cli, "SessionLocal", lambda: db)
    monkeypatch.setattr(ledger_cli, "beijing_now", lambda: datetime(2026, 11, 23, 14, 2))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"revision": REV, "release_id": "7dbf", "scope": "office-and-cloud"})))
    assert ledger_cli.main() == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"recorded": True}
    assert db.query(DevlogRelease).one().released_at == datetime(2026, 11, 23, 14, 2)
```

- [ ] **Step 2: 确认失败**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_releases.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 service**

```python
# backend/app/devlog/release_service.py
"""发布账本：部署器验收通过后写入，回填走同一入口；按 release_id 幂等。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.devlog.models import GLOBAL_SCOPE, DevlogRelease


def record_release(db: Session, *, revision: str, release_id: str, scope: str, released_at: datetime, source: str) -> bool:
    if db.query(DevlogRelease.id).filter(DevlogRelease.release_id == release_id).first():
        return False
    db.add(DevlogRelease(revision=revision, release_id=release_id, scope=scope, released_at=released_at, source=source))
    db.flush()
    return True


def _row(release: DevlogRelease) -> dict:
    return {"revision": release.revision, "release_id": release.release_id, "scope": release.scope,
            "released_at": release.released_at.isoformat(timespec="seconds"), "source": release.source}


def list_releases(db: Session) -> list[dict]:
    return [_row(r) for r in db.query(DevlogRelease).order_by(DevlogRelease.released_at, DevlogRelease.id).all()]


def latest_global(db: Session) -> dict | None:
    release = (db.query(DevlogRelease).filter(DevlogRelease.scope == GLOBAL_SCOPE)
               .order_by(DevlogRelease.released_at.desc(), DevlogRelease.id.desc()).first())
    return _row(release) if release else None
```

- [ ] **Step 4: 实现 CLI**

```python
# backend/app/devlog/ledger_cli.py
"""部署器在办公室调用的账本写入入口：python -m app.devlog.ledger_cli < {"revision","release_id","scope"}

属 bootstrap 类一次性进程（红线 4 允许自建 SessionLocal）；时间取本进程 beijing_now()，即验收通过时刻。
"""
import json
import logging
import sys

from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.devlog.release_service import record_release
from app.devlog.schemas import ReleaseIn

logger = logging.getLogger(__name__)


def main() -> int:
    request = json.loads(sys.stdin.read())
    release = ReleaseIn.model_validate({**request, "released_at": beijing_now()})
    db = SessionLocal()
    try:
        recorded = record_release(db, revision=release.revision, release_id=release.release_id, scope=release.scope,
                                  released_at=release.released_at, source="deployer")
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("devlog ledger write failed: %s", type(exc).__name__)
        print(f"[devlog] ledger write failed: {type(exc).__name__}", flush=True)
        return 1
    finally:
        db.close()
    print(json.dumps({"recorded": recorded}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 测试通过**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_releases.py -q`
Expected: PASS（3 passed）。如果 `db.close()` 关闭 fixture session 导致后续断言失败，就在测试里用 `monkeypatch.setattr(db, "close", lambda: None)`，不要改 CLI。

- [ ] **Step 6: Commit**

```powershell
git add backend/app/devlog/release_service.py backend/app/devlog/ledger_cli.py backend/tests/test_devlog_releases.py
git commit -m "Add idempotent devlog release ledger and deployer CLI entry"
```

---

### Task 6: 查询 service

**Files:**
- Create: `backend/app/devlog/query_service.py`
- Test: `backend/tests/test_devlog_query.py`

**口径**：
- 看板显示两类事项：本期有状态事件的，以及当前未发布且未停滞的（在做的事不受时间范围影响）。
- 「已发布」列只放本期内发布的事项。
- KPI：上线功能和修复问题按本期 `released` 事件计数；开发中、待发布、停滞按当前状态计数。
- 时间线按事件的北京时间日期倒序排列。
- 「能否随下次发布」：只有 `pending_release` 且没有新配置项、没有新权限时为「可以」。迁移会随发布入口执行，只展示，不算阻塞。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_devlog_query.py
from datetime import date, datetime

from app.devlog.ingest_service import ingest
from app.devlog.query_service import health, item_detail, pending_list, summary
from app.devlog.release_service import record_release
from app.devlog.schemas import IngestIn


def push(db, items, finished="2026-11-23T15:01:00"):
    ingest(db, IngestIn.model_validate({"started_at": "2026-11-23T15:00:00", "finished_at": finished,
                                        "sources": [{"name": "git", "ok": True}], "items": items}))


def it(key, status, at, type_="feature", stale=False, fp="a", pre=None):
    return {"key": key, "title": key.split("/")[-1], "type": type_, "module": "invoice", "agent": "codex",
            "status": status, "status_at": at, "last_activity_at": at, "stale": stale,
            "fingerprint": fp * 64, "preconditions": pre or {}, "evidences": []}


def seed(db):
    push(db, [
        it("branch:codex/old-release", "released", "2026-11-10T10:00:00"),
        it("branch:codex/fix", "released", "2026-11-23T14:02:00", type_="bug"),
        it("branch:codex/wip", "dev", "2026-11-23T10:00:00"),
        it("branch:codex/ready", "pending_release", "2026-11-22T10:00:00"),
        it("branch:codex/needs-config", "pending_release", "2026-11-21T10:00:00",
           pre={"migrations": ["276_invoice_alibaba_order"], "config_keys": ["CROSS_BORDER_DXP_ID"], "permissions": []}),
        it("branch:codex/forgotten", "pending_merge", "2026-10-01T10:00:00", stale=True),
    ])


def test_week_summary_buckets_by_event_time(db):
    seed(db)
    data = summary(db, start=date(2026, 11, 17), end=date(2026, 11, 23))
    assert data["kpis"] == {"features": 0, "bugs": 1, "data": 0, "dev": 1, "pending_release": 2, "stale": 1}
    titles = {c: [i["title"] for i in data["columns"][c]] for c in data["columns"]}
    assert titles["released"] == ["fix"]
    assert "old-release" not in sum(titles.values(), [])
    assert "forgotten" not in sum(titles.values(), [])
    assert data["timeline"][0]["date"] == "2026-11-23"


def test_type_filter(db):
    seed(db)
    data = summary(db, start=date(2026, 11, 17), end=date(2026, 11, 23), item_type="bug")
    assert data["kpis"]["pending_release"] == 0 and data["kpis"]["bugs"] == 1


def test_pending_list_ready_flags(db):
    seed(db)
    rows = {r["title"]: r for r in pending_list(db)}
    assert rows["ready"]["ready"] is True
    assert rows["needs-config"]["ready"] is False
    assert "forgotten" not in rows   # 停滞项不进清单


def test_health_marks_stale_after_six_hours(db, monkeypatch):
    import app.devlog.query_service as qs
    record_release(db, revision="d" * 40, release_id="g", scope="office-and-cloud", released_at=datetime(2026, 11, 23, 14, 2), source="deployer")
    push(db, [], finished="2026-11-23T07:12:00")
    monkeypatch.setattr(qs, "beijing_now", lambda: datetime(2026, 11, 23, 15, 20))
    data = health(db)
    assert data["is_stale"] is True and data["ledger_latest"]["revision"] == "d" * 40


def test_detail_contains_events(db):
    seed(db)
    first = summary(db, start=date(2026, 11, 17), end=date(2026, 11, 23))["columns"]["released"][0]
    detail = item_detail(db, first["id"])
    assert detail["events"][-1]["to_status"] == "released"
```

- [ ] **Step 2: 确认失败**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_query.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# backend/app/devlog/query_service.py
"""开发动态查询口径：看板、KPI、时间线、待发布清单、同步健康。"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.devlog.models import DevlogEvidence, DevlogItem, DevlogItemEvent, DevlogSyncRun
from app.devlog.release_service import latest_global

COLUMN = {"dev": "dev", "pending_merge": "committed", "pending_push": "committed",
          "pending_release": "committed", "released": "released"}
STALE_SYNC_HOURS = 6


def _item(row: DevlogItem) -> dict:
    return {"id": row.id, "key": row.item_key, "title": row.title, "type": row.item_type, "module": row.module,
            "agent": row.agent, "status": row.status, "status_at": row.status_at.isoformat(timespec="minutes"),
            "last_activity_at": row.last_activity_at.isoformat(timespec="minutes"), "stale": row.stale,
            "unmerged_hotfix": row.unmerged_hotfix, "released_revision": row.released_revision,
            "preconditions": row.preconditions or {}}


def _filtered(db: Session, item_type: str | None, module: str | None, agent: str | None):
    query = db.query(DevlogItem).filter(DevlogItem.superseded.is_(False))
    if item_type:
        query = query.filter(DevlogItem.item_type == item_type)
    if module:
        query = query.filter(DevlogItem.module == module)
    if agent:
        query = query.filter(DevlogItem.agent == agent)
    return query.all()


def summary(db: Session, *, start: date, end: date, item_type: str | None = None,
            module: str | None = None, agent: str | None = None) -> dict:
    if end < start or (end - start).days > 400:
        raise HTTPException(status_code=422, detail="日期范围无效")
    items = {row.id: row for row in _filtered(db, item_type, module, agent)}
    window = (datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min))
    events = (db.query(DevlogItemEvent)
              .filter(DevlogItemEvent.occurred_at >= window[0], DevlogItemEvent.occurred_at < window[1],
                      DevlogItemEvent.item_id.in_(list(items) or [0]))
              .order_by(DevlogItemEvent.occurred_at.desc()).all())
    touched = {event.item_id for event in events}
    released_ids = {event.item_id for event in events if event.to_status == "released"}
    columns = {"dev": [], "committed": [], "released": []}
    for row in sorted(items.values(), key=lambda r: r.status_at, reverse=True):
        if row.status == "released":
            if row.id in released_ids:
                columns["released"].append(_item(row))
        elif not row.stale or row.id in touched:
            columns[COLUMN[row.status]].append(_item(row))
    released = [items[i] for i in released_ids]
    open_rows = [r for r in items.values() if r.status != "released"]
    kpis = {
        "features": sum(r.item_type in ("feature", "improve") for r in released),
        "bugs": sum(r.item_type == "bug" for r in released),
        "data": sum(items[i].item_type == "data" for i in touched),
        "dev": sum(r.status == "dev" and not r.stale for r in open_rows),
        "pending_release": sum(r.status == "pending_release" for r in open_rows),
        "stale": sum(r.stale for r in open_rows),
    }
    days = defaultdict(list)
    for event in events:
        days[event.occurred_at.date().isoformat()].append(
            {**_item(items[event.item_id]), "to_status": event.to_status,
             "occurred_at": event.occurred_at.isoformat(timespec="minutes")})
    timeline = [{"date": day, "entries": entries} for day, entries in sorted(days.items(), reverse=True)]
    return {"kpis": kpis, "columns": columns, "timeline": timeline}


def item_detail(db: Session, item_id: int) -> dict:
    row = db.get(DevlogItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="事项不存在")
    evidences = (db.query(DevlogEvidence).filter(DevlogEvidence.item_id == item_id)
                 .order_by(DevlogEvidence.occurred_at).all())
    events = (db.query(DevlogItemEvent).filter(DevlogItemEvent.item_id == item_id)
              .order_by(DevlogItemEvent.occurred_at, DevlogItemEvent.id).all())
    return {**_item(row),
            "evidences": [{"kind": e.kind, "ref": e.ref, "at": e.occurred_at.isoformat(timespec="minutes")} for e in evidences],
            "events": [{"from_status": e.from_status, "to_status": e.to_status,
                        "at": e.occurred_at.isoformat(timespec="minutes")} for e in events]}


def pending_list(db: Session) -> list[dict]:
    order = {"pending_release": 0, "pending_push": 1, "pending_merge": 2}
    # 停滞与已被取代的事项不进上线准备清单（停滞项在看板折叠行里查看）
    rows = (db.query(DevlogItem).filter(DevlogItem.status.in_(list(order)), DevlogItem.stale.is_(False),
                                        DevlogItem.superseded.is_(False)).all())
    rows.sort(key=lambda r: (order[r.status], -r.status_at.timestamp()))
    result = []
    for row in rows:
        pre = row.preconditions or {}
        ready = row.status == "pending_release" and not pre.get("config_keys") and not pre.get("permissions")
        result.append({**_item(row), "ready": ready})
    return result


def health(db: Session) -> dict:
    last = db.query(DevlogSyncRun).order_by(DevlogSyncRun.finished_at.desc(), DevlogSyncRun.id.desc()).first()
    now = beijing_now()
    hours = None if last is None else round((now - last.finished_at).total_seconds() / 3600, 1)
    return {"last_sync_at": last.finished_at.isoformat(timespec="minutes") if last else None,
            "sources": last.sources if last else [], "hours_since_sync": hours,
            "is_stale": last is None or hours > STALE_SYNC_HOURS,
            "ledger_latest": latest_global(db)}
```

- [ ] **Step 4: 测试通过**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_query.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit**

```powershell
git add backend/app/devlog/query_service.py backend/tests/test_devlog_query.py
git commit -m "Add devlog summary, timeline, pending list and sync health queries"
```

---

### Task 7: Router 与注册

**Files:**
- Create: `backend/app/devlog/router.py`
- Modify: `backend/app/routers.py`（import 区 + `register_routers` 内）
- Test: `backend/tests/test_devlog_api.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_devlog_api.py
import hashlib
import json
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils import create_access_token
from app.core.config import get_settings
from app.core.database import get_db

TOKEN = "t" * 32
BODY = {"started_at": "2026-11-23T15:00:00", "finished_at": "2026-11-23T15:01:00",
        "sources": [{"name": "git", "ok": True}], "items": []}


@contextmanager
def client(db, permissions=("devlog:read",)):
    from app.devlog.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/devlog")
    app.dependency_overrides[get_db] = lambda: db
    token = create_access_token({"sub": "1", "username": "u", "real_name": "u", "roles": [], "permissions": list(permissions)})
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


def test_ingest_requires_machine_token(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashlib.sha256(TOKEN.encode()).hexdigest())
    with client(db) as c:
        assert c.post("/api/devlog/ingest", json=BODY).status_code == 401
        ok = c.post("/api/devlog/ingest", json=BODY, headers={"X-Devlog-Token": TOKEN})
        assert ok.status_code == 200 and ok.json()["code"] == 200


def test_ingest_rejects_unknown_fields(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashlib.sha256(TOKEN.encode()).hexdigest())
    with client(db) as c:
        assert c.post("/api/devlog/ingest", json={**BODY, "transcript": "x"}, headers={"X-Devlog-Token": TOKEN}).status_code == 422


def test_user_endpoints_require_permission(db):
    with client(db, permissions=()) as c:
        assert c.get("/api/devlog/summary", params={"start": "2026-11-17", "end": "2026-11-23"}).status_code == 403
    with client(db) as c:
        assert c.get("/api/devlog/summary", params={"start": "2026-11-17", "end": "2026-11-23"}).json()["data"]["kpis"]["dev"] == 0
        assert c.get("/api/devlog/health").json()["data"]["is_stale"] is True
        assert c.get("/api/devlog/pending").json()["data"]["items"] == []


def test_machine_release_backfill_and_list(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "DEVLOG_INGEST_TOKEN_HASHES", hashlib.sha256(TOKEN.encode()).hexdigest())
    rel = {"revision": "d" * 40, "release_id": "backfill-dddddddddddd", "scope": "office-and-cloud",
           "released_at": "2026-11-20T21:56:00"}
    with client(db) as c:
        h = {"X-Devlog-Token": TOKEN}
        monkeypatch.setattr(get_settings(), "DEVLOG_BACKFILL_ENABLED", False)
        assert c.post("/api/devlog/machine/releases", json={"items": [rel]}, headers=h).status_code == 403
        monkeypatch.setattr(get_settings(), "DEVLOG_BACKFILL_ENABLED", True)
        assert c.post("/api/devlog/machine/releases", json={"items": [rel]}, headers=h).json()["data"] == {"recorded": 1}
        assert c.get("/api/devlog/machine/releases", headers=h).json()["data"]["items"][0]["source"] == "backfill"
```

- [ ] **Step 2: 确认失败**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_api.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.devlog.router'`

- [ ] **Step 3: 实现 router**

```python
# backend/app/devlog/router.py
"""方舟开发动态 API。

用户端点：devlog:read。
机器端点（红线 3 白名单，开发机采集器专用）：/ingest、/machine/releases，
凭 _require_devlog_machine 校验 token 哈希，不接受用户 JWT。
"""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.core.response import ok
from app.devlog import ingest_service, query_service, release_service
from app.devlog.machine_auth import _require_devlog_machine, _require_small_body
from app.devlog.schemas import IngestIn, ReleaseBackfillIn

router = APIRouter()
Database = Annotated[Session, Depends(get_db)]
READ = "devlog:read"


@router.post("/ingest", dependencies=[Depends(_require_devlog_machine), Depends(_require_small_body)])
def ingest(payload: IngestIn, db: Database):
    return ok(ingest_service.ingest(db, payload))


@router.get("/machine/releases", dependencies=[Depends(_require_devlog_machine)])
def machine_releases(db: Database):
    return ok({"items": release_service.list_releases(db)})


@router.post("/machine/releases", dependencies=[Depends(_require_devlog_machine), Depends(_require_small_body)])
def backfill_releases(payload: ReleaseBackfillIn, db: Database):
    return ok({"recorded": release_service.backfill(db, payload.items)})


@router.get("/summary")
def summary(db: Database, start: date, end: date, type: str | None = Query(default=None, max_length=16),
            module: str | None = Query(default=None, max_length=40), agent: str | None = Query(default=None, max_length=16),
            user=Depends(require_permission(READ))):
    return ok(query_service.summary(db, start=start, end=end, item_type=type, module=module, agent=agent))


@router.get("/items/{item_id}")
def item_detail(item_id: int, db: Database, user=Depends(require_permission(READ))):
    return ok(query_service.item_detail(db, item_id))


@router.get("/pending")
def pending(db: Database, user=Depends(require_permission(READ))):
    return ok({"items": query_service.pending_list(db)})


@router.get("/health")
def health(db: Database, user=Depends(require_permission(READ))):
    return ok(query_service.health(db))
```

回填逻辑放在 service 层（红线 2），由 `DEVLOG_BACKFILL_ENABLED` 开关控制，并做北京时间换算（红线 23）。在 `backend/app/devlog/release_service.py` 末尾追加：

```python
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.time import to_beijing_naive


def backfill(db: Session, items) -> int:
    """人工核对后的一次性回填；开关默认关闭，防止常驻采集器 token 伪造「已发布」。"""
    if not get_settings().DEVLOG_BACKFILL_ENABLED:
        raise HTTPException(status_code=403, detail="发布账本回填未开启")
    recorded = 0
    for item in items:
        recorded += record_release(db, revision=item.revision, release_id=item.release_id, scope=item.scope,
                                   released_at=to_beijing_naive(item.released_at, naive_is_beijing=True), source="backfill")
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return recorded
```

把这几行 import 并到文件顶部的 import 区，不要留在函数附近。

- [ ] **Step 4: 注册 router**（`backend/app/routers.py`）

import 区紧跟 `from app.cross_border.router import router as cross_border_router` 之后：

```python
from app.devlog.router import router as devlog_router
```

`register_routers` 内紧跟 cross_border 的 `include_router` 之后：

```python
    app.include_router(devlog_router, prefix="/api/devlog", tags=["方舟开发动态"])
```

- [ ] **Step 5: 测试通过 + 全量回归 + 约定检查**

Run: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_devlog_api.py tests/test_devlog_query.py tests/test_devlog_releases.py tests/test_devlog_ingest.py tests/test_devlog_schemas.py tests/test_devlog_models.py -q`
Expected: 全部 PASS

Run: `cd backend; .venv\Scripts\python.exe -c "import app.routers"`
Expected: 无输出、退出码 0

Run: `python scripts/check_conventions.py`
Expected: 无红项（`_require_devlog_machine` 命中 `_require_\w+` 鉴权白名单）

- [ ] **Step 6: Commit**

```powershell
git add backend/app/devlog/router.py backend/app/devlog/release_service.py backend/app/routers.py backend/tests/test_devlog_api.py
git commit -m "Expose devlog user and machine endpoints"
```

---

### Task 8: 部署器写账本

**Files:**
- Create: `deploy/devlog_ledger.py`
- Modify: `deploy/publish.py:346-348`（`publish-success.json` 写入之后）
- Test: `deploy/tests/test_devlog_ledger.py`

- [ ] **Step 1: 写失败测试**

```python
# deploy/tests/test_devlog_ledger.py
from pathlib import Path
import json
import subprocess
import sys
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parents[1]))
import devlog_ledger


def test_records_global_release_through_office_python(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout='{"recorded": true}\n', stderr="")
    monkeypatch.setattr(devlog_ledger.subprocess, "run", fake_run)
    result = devlog_ledger.record({"python": "C:/py/python.exe"}, tmp_path, "a" * 40, "rid", "office-and-cloud")
    assert result == {"status": "recorded"}
    cmd, kw = calls[0]
    assert cmd == ["C:/py/python.exe", "-m", "app.devlog.ledger_cli"]
    assert kw["cwd"] == tmp_path / "backend"
    assert json.loads(kw["input"]) == {"revision": "a" * 40, "release_id": "rid", "scope": "office-and-cloud"}


def test_failure_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(devlog_ledger.subprocess, "run", Mock(side_effect=OSError("missing")))
    assert devlog_ledger.record({"python": "x"}, tmp_path, "a" * 40, "rid", "office-and-cloud")["status"] == "failed"
    monkeypatch.setattr(devlog_ledger.subprocess, "run",
                        Mock(return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="boom")))
    assert devlog_ledger.record({"python": "x"}, tmp_path, "a" * 40, "rid", "office-and-cloud")["status"] == "failed"


def test_skips_without_office(tmp_path):
    assert devlog_ledger.record(None, tmp_path, "a" * 40, "rid", "cloud-only") == {"status": "skipped"}
```

- [ ] **Step 2: 确认失败**

Run: `backend\.venv\Scripts\python.exe -m pytest deploy/tests/test_devlog_ledger.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'devlog_ledger'`

- [ ] **Step 3: 实现**

```python
# deploy/devlog_ledger.py
"""全局发布验收通过后写入方舟开发动态账本。失败只告警，绝不影响发布结果。

只在含办公室的完整发布时执行（cloud-only 没有办公室 Python，且不算全局发布）。
"""
import json
import subprocess


def record(office, root, revision, release_id, scope):
    if not office:
        return {"status": "skipped"}
    request = json.dumps({"revision": revision, "release_id": release_id, "scope": scope})
    try:
        result = subprocess.run([str(office["python"]), "-m", "app.devlog.ledger_cli"], cwd=root / "backend",
                                input=request, text=True, capture_output=True, timeout=60)
    except Exception as error:
        print("WARNING devlog ledger not recorded: " + type(error).__name__, flush=True)
        return {"status": "failed", "error": type(error).__name__}
    if result.returncode:
        print("WARNING devlog ledger not recorded: exit " + str(result.returncode), flush=True)
        return {"status": "failed", "error": "exit " + str(result.returncode)}
    return {"status": "recorded"}
```

- [ ] **Step 4: 接入 publish.py**

在 `deploy/publish.py` 的 `record_success` 块**之后**插入，也就是这段代码的后面：

```python
        if office:
            from candidate_retention import record_success
            try:
                record_success(STATE, revision, previous)
            except Exception as error:
                journal['candidate_retention_error'] = type(error).__name__
                atomic_json(STATE / 'publish-current.json', journal)
                raise
```

插入：

```python
        # 方舟开发动态账本：全部验收与回滚历史记账之后执行；整段吞异常只告警，绝不改变发布结果
        try:
            from devlog_ledger import record as record_devlog_release
            summary["devlog_ledger"] = record_devlog_release(office, ROOT, revision, release_id, scope)
        except Exception as error:
            summary["devlog_ledger"] = {"status": "failed", "error": type(error).__name__}
            print("WARNING devlog ledger hook failed: " + type(error).__name__, flush=True)
        atomic_json(STATE / "publish-success.json", summary)
```

放在这里，账本写入既不会抢在回滚历史记账之前，也不会把已成功的发布变成失败退出。`summary` 后面的分支还会再次写 `publish-success.json`，`devlog_ledger` 字段会一并保留。

- [ ] **Step 4b: 发布级契约测试**

在 `deploy/tests/test_pipeline_contract.py` 的 `pipeline` fixture 里，紧跟 `monkeypatch.setattr(okki_outbound_release,'pause_registered',Mock())` 加两行，避免既有用例真的去调用 `isolated-python`：

```python
    import devlog_ledger
    monkeypatch.setattr(devlog_ledger, 'record', Mock(return_value={'status': 'recorded'}))
```

文件末尾追加：

```python
def test_devlog_ledger_failure_never_fails_publish(pipeline, monkeypatch):
    import devlog_ledger
    monkeypatch.setattr(devlog_ledger, 'record', Mock(side_effect=RuntimeError('ledger down')))
    publish.publish(pipeline.args)
    success = json.loads((pipeline.state / "publish-success.json").read_text())
    assert success["revision"] == "a" * 40 and success["devlog_ledger"]["status"] == "failed"
    assert json.loads((pipeline.state / "publish-current.json").read_text())["status"] == "succeeded"
```

- [ ] **Step 5: 测试通过 + 部署器回归**

Run: `backend\.venv\Scripts\python.exe -m pytest deploy/tests/test_devlog_ledger.py deploy/tests/test_pipeline_contract.py deploy/tests/test_atomic_publish_journal.py -q`
Expected: PASS

Run: `backend\.venv\Scripts\python.exe -m pytest deploy/tests -q`
Expected: 与改动前的通过数一致（先在 main 上跑一次记下基线；已有失败如实记录，不算本任务引入）

- [ ] **Step 6: Commit**

```powershell
git add deploy/devlog_ledger.py deploy/publish.py deploy/tests/test_devlog_ledger.py deploy/tests/test_pipeline_contract.py
git commit -m "Record verified global releases into the devlog ledger"
```

---

### Task 9: 采集器 Git 层

**Files:**
- Create: `scripts/devlog/__init__.py`（空文件）
- Create: `scripts/devlog/gitdata.py`
- Create: `scripts/devlog/tests/conftest.py`
- Test: `scripts/devlog/tests/test_gitdata.py`

- [ ] **Step 1: 夹具仓库 conftest**

```python
# scripts/devlog/tests/conftest.py
"""在临时目录建真实 Git 仓库，覆盖 merge、cherry-pick、worktree 场景。"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))


def sh(repo, *args, env_date=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    if env_date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = env_date
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


def commit(repo, path, content, message, when="2026-11-20T10:00:00+08:00"):
    file = Path(repo) / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    sh(repo, "add", path)
    sh(repo, "commit", "-m", message, env_date=when)
    return sh(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    sh(root, "init", "-b", "main")
    # 早于各测试的 SINCE（2026-10-01），不进入采集窗口，避免初始提交被算成事项
    commit(root, "README.md", "base\n", "Initial commit", "2026-09-01T09:00:00+08:00")
    return root
```

- [ ] **Step 2: 写失败测试**

```python
# scripts/devlog/tests/test_gitdata.py
from datetime import datetime

from conftest import commit, sh
import gitdata


def test_to_bj_naive_converts_offset_across_midnight():
    assert gitdata.to_bj_naive("2026-11-22T16:30:00+00:00") == datetime(2026, 11, 23, 0, 30)


def test_cherry_picked_commit_has_same_patch_id(repo):
    sh(repo, "checkout", "-b", "codex/fix")
    original = commit(repo, "backend/app/invoice/a.py", "x = 1\n", "Fix invoice rounding")
    sh(repo, "checkout", "main")
    sh(repo, "cherry-pick", original)
    picked = sh(repo, "rev-parse", "HEAD")
    ids = gitdata.patch_ids(repo, [original, picked])
    assert original != picked and ids[original] == ids[picked]


def test_first_parent_history_reports_merges_with_branch_name(repo):
    sh(repo, "checkout", "-b", "codex/feature")
    commit(repo, "backend/app/stock/s.py", "s = 1\n", "Add stock thing")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/feature", "-m", "Merge branch 'codex/feature'")
    history = gitdata.first_parent(repo, "main", "2026-10-01")
    merge = history[0]
    assert merge.is_merge and merge.subject == "Merge branch 'codex/feature'"
    inner = gitdata.range_commits(repo, merge.parents[0], merge.parents[1])
    assert [c.subject for c in inner] == ["Add stock thing"]
    assert inner[0].files == [("A", "backend/app/stock/s.py")]


def test_branches_and_dirty_worktrees(repo, tmp_path):
    sh(repo, "branch", "claude/wip")
    wt = tmp_path / "wt"
    sh(repo, "worktree", "add", str(wt), "claude/wip")
    (wt / "new.txt").write_text("draft", encoding="utf-8")
    branches = {b.name for b in gitdata.branches(repo)}
    assert {"main", "claude/wip"} <= branches
    trees = {w.branch: w for w in gitdata.worktrees(repo)}
    assert trees["claude/wip"].dirty_files == 1 and trees["claude/wip"].dirty_mtime is not None
    assert trees["main"].dirty_files == 0 and trees["main"].dirty_mtime is None


def test_reach_and_name_rev(repo):
    sh(repo, "checkout", "-b", "codex/named")
    tip = commit(repo, "a.txt", "a\n", "Add a")
    sh(repo, "checkout", "main")
    assert tip in gitdata.reach(repo, "codex/named") and tip not in gitdata.reach(repo, "main")
    assert gitdata.name_rev(repo, tip) == "codex/named"
    sh(repo, "merge", "--no-ff", "codex/named", "-m", "Merge something")
    sh(repo, "branch", "-D", "codex/named")
    assert gitdata.name_rev(repo, tip) is None   # 分支删除后不能被命名成 main~N
    merge = sh(repo, "rev-parse", "HEAD")
    sh(repo, "branch", "codex/later")            # 合并之后才从 main 切出的分支
    assert gitdata.is_ancestor(repo, merge, "codex/later") is True


def test_status_does_not_escape_chinese_paths(repo, tmp_path):
    sh(repo, "branch", "claude/zh")
    wt = tmp_path / "wt-zh"
    sh(repo, "worktree", "add", str(wt), "claude/zh")
    (wt / "发票说明.md").write_text("x", encoding="utf-8")
    tree = {w.branch: w for w in gitdata.worktrees(repo)}["claude/zh"]
    assert tree.dirty_files == 1 and tree.dirty_mtime is not None


def test_object_exists(repo):
    head = sh(repo, "rev-parse", "HEAD")
    assert gitdata.object_exists(repo, head) is True
    assert gitdata.object_exists(repo, "0" * 40) is False
```

- [ ] **Step 3: 确认失败**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests/test_gitdata.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'gitdata'`

- [ ] **Step 4: 实现**

```python
# scripts/devlog/gitdata.py
"""只读 Git 采集：分支、worktree、first-parent 历史、区间提交与 patch-id。除 fetch 外不做任何写操作。"""
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8))
SEP, REC = "\x1f", "\x1e"
LOG_FORMAT = f"{REC}%H{SEP}%P{SEP}%cI{SEP}%s{SEP}%(trailers:key=Co-Authored-By,valueonly,separator=%x20)"


def git(repo, *args, input_text=None, check=True) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], input=input_text, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=check)
    return result.stdout


def to_bj_naive(iso: str) -> datetime:
    """Git 的 ISO 时间带偏移：先换算到北京时间再去 tzinfo（红线 23）。"""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BJ).replace(tzinfo=None)


@dataclass
class Commit:
    sha: str
    parents: list[str]
    at: datetime
    subject: str
    coauthors: str = ""
    files: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


def _parse_log(text: str) -> list[Commit]:
    commits = []
    for record in text.split(REC):
        if not record.strip():
            continue
        header, _, rest = record.partition("\n")
        sha, parents, at, subject, coauthors = (header.split(SEP) + [""] * 5)[:5]
        files = []
        for line in rest.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0]:
                files.append((parts[0][0], parts[-1]))
        commits.append(Commit(sha=sha, parents=parents.split() if parents else [], at=to_bj_naive(at),
                              subject=subject.strip(), coauthors=coauthors.strip(), files=files))
    return commits


def first_parent(repo, ref: str, since: str) -> list[Commit]:
    return _parse_log(git(repo, "log", "--first-parent", f"--since={since}", f"--format={LOG_FORMAT}", "--name-status", ref))


def range_commits(repo, exclude: str, include: str) -> list[Commit]:
    """include 可达、exclude 不可达的非合并提交，按时间正序。"""
    return list(reversed(_parse_log(git(repo, "log", "--no-merges", f"--format={LOG_FORMAT}", "--name-status",
                                        include, f"^{exclude}"))))


def reachable_shas(repo, ref: str, since: str) -> list[str]:
    return git(repo, "rev-list", "--no-merges", f"--since={since}", ref).split()


def patch_ids(repo, shas: list[str]) -> dict[str, str]:
    """commit → patch-id（内容等价判定）。空 diff 的提交不出现在结果里。"""
    if not shas:
        return {}
    patches = git(repo, "log", "--no-walk=unsorted", "--stdin", "-p", "--no-color", "--format=commit %H",
                  input_text="\n".join(shas) + "\n")
    out = git(repo, "patch-id", "--stable", input_text=patches)
    return {commit: pid for pid, commit in (line.split() for line in out.splitlines() if line.strip())}


@dataclass
class Branch:
    name: str
    sha: str
    at: datetime


def branches(repo) -> list[Branch]:
    out = git(repo, "for-each-ref", f"--format=%(refname:short){SEP}%(objectname){SEP}%(committerdate:iso-strict)", "refs/heads")
    return [Branch(name, sha, to_bj_naive(at)) for name, sha, at in (line.split(SEP) for line in out.splitlines() if line)]


@dataclass
class Worktree:
    path: Path
    branch: str | None
    dirty_files: int
    dirty_mtime: datetime | None   # 改动文件最近修改的北京时间；用于排除早已废弃的残留改动


def _status_entries(path: Path) -> list[str]:
    """--no-optional-locks：不改写其他代理 worktree 的 index；-z：中文路径不被转义。"""
    raw = subprocess.run(["git", "--no-optional-locks", "-C", str(path), "status", "--porcelain", "-z"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    entries, parts, i = [], raw.split("\0"), 0
    while i < len(parts):
        entry = parts[i]
        if len(entry) > 3:
            entries.append(entry[3:])
            if entry[0] in "RC":   # 重命名/复制：-z 模式下原路径紧跟在后面
                i += 1
        i += 1
    return entries


def _dirty_mtime(path: Path, names: list[str]) -> datetime | None:
    stamps = []
    for name in names:
        target = path / name
        if target.exists():
            stamps.append(target.stat().st_mtime)
    if not stamps:
        return None
    return datetime.fromtimestamp(max(stamps), BJ).replace(tzinfo=None)


def worktrees(repo) -> list[Worktree]:
    result, current = [], {}
    for line in git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if current.get("worktree"):
                path = Path(current["worktree"])
                names = _status_entries(path) if path.exists() else []
                branch = current.get("branch", "").removeprefix("refs/heads/") or None
                result.append(Worktree(path, branch, len(names), _dirty_mtime(path, names)))
            current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return result


def reach(repo, ref: str) -> set[str]:
    """ref 可达的全部提交（不截断日期；只取 sha，开销很小）。"""
    return set(git(repo, "rev-list", ref).split())


def name_rev(repo, sha: str) -> str | None:
    """为无名合并找回功能分支名（只看本地分支，排除 main/master，否则已合入的提交都会被命名成 main~N）。"""
    out = git(repo, "name-rev", "--name-only", "--no-undefined", "--exclude=refs/heads/main",
              "--exclude=refs/heads/master", "--refs=refs/heads/*", sha, check=False).strip()
    if not out:
        return None
    return re.split(r"[~^]", out, maxsplit=1)[0] or None


def is_ancestor(repo, older: str, newer: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True).returncode == 0


def object_exists(repo, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def fetch(repo) -> tuple[bool, str]:
    result = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin"], capture_output=True, text=True)
    return result.returncode == 0, "" if result.returncode == 0 else "fetch failed"


def show_added_lines(repo, sha: str, path: str) -> list[str]:
    diff = git(repo, "show", "--no-color", "--format=", sha, "--", path, check=False)
    return [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
```

- [ ] **Step 5: 测试通过**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests/test_gitdata.py -q`
Expected: PASS（7 passed）

- [ ] **Step 6: Commit**

```powershell
git add scripts/devlog/__init__.py scripts/devlog/gitdata.py scripts/devlog/tests/conftest.py scripts/devlog/tests/test_gitdata.py
git commit -m "Add read-only git layer for the devlog collector"
```

---

### Task 10: 去敏、分类、归并、状态

**Files:**
- Create: `scripts/devlog/redact.py`
- Create: `scripts/devlog/classify.py`
- Create: `scripts/devlog/grouping.py`
- Create: `scripts/devlog/status.py`
- Test: `scripts/devlog/tests/test_rules.py`
- Test: `scripts/devlog/tests/test_grouping_status.py`

- [ ] **Step 1: 写规则层失败测试**

```python
# scripts/devlog/tests/test_rules.py
import pytest

from classify import agent_of, item_type, module_of
from redact import redact_title


@pytest.mark.parametrize("raw, expected", [
    ("Notify ops@leshinehair.com on failure", "Notify [邮箱] on failure"),
    ("Fix total 146,352.55 USD rounding", "Fix total [金额] rounding"),
    ("Call +86 138 0013 8000 back", "Call [号码] back"),
    ("Repair order 240611093 outbound", "Repair order [编号] outbound"),
    ("Rotate sk-abcdefghijklmnop key", "Rotate [密钥] key"),
    ("Fix 1751 outbound name", "Fix 1751 outbound name"),
])
def test_redact(raw, expected):
    assert redact_title(raw) == expected


def test_redact_truncates_to_40_chars():
    assert len(redact_title("Implement " + "very long subject " * 5)) == 40


def test_item_type_priority():
    assert item_type(["Add cross border review", "Fix typo"]) == "feature"
    assert item_type(["Fix invoice rounding"]) == "bug"
    assert item_type(["Backfill receipt dates"]) == "data"
    assert item_type(["Speed up invoice matching"]) == "improve"


def test_item_type_by_paths_when_subjects_neutral():
    assert item_type(["Update notes"], [("M", "docs/handoff.md")]) == "docs"
    assert item_type(["Tune retention"], [("M", "deploy/publish.py")]) == "ops"


def test_module_of_counts_domain_dirs():
    files = [("M", "backend/app/cross_border/a.py"), ("M", "backend/app/cross_border/b.py"),
             ("A", "frontend/src/views/cross_border/X.vue"), ("M", "backend/app/core/config.py")]
    assert module_of(files) == "cross_border"
    assert module_of([("M", "docs/a.md")]) == ""


def test_agent_of():
    assert agent_of("codex/fix-x", "") == "codex"
    assert agent_of(None, "Claude Opus <noreply@anthropic.com>") == "claude"
    assert agent_of(None, "") == "unknown"
```

- [ ] **Step 2: 确认失败**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests/test_rules.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 redact 与 classify**

```python
# scripts/devlog/redact.py
"""标题去敏：命中即打码。P0 只处理 commit 首行（项目约定英文意图描述）；人名/客户名词典在 P1。"""
import re

RULES = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[邮箱]"),
    (re.compile(r"https?://\S+"), "[链接]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[密钥]"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "[密钥]"),
    (re.compile(r"(?:\$|¥|￥|USD|CNY|RMB)\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:USD|CNY|RMB|美元|元)"), "[金额]"),
    (re.compile(r"\+\d[\d -]{8,}\d|\b1[3-9]\d{9}\b"), "[号码]"),
    (re.compile(r"\b\d{6,}\b"), "[编号]"),
]
MAX_TITLE = 40


def redact_title(text: str) -> str:
    value = " ".join(text.split())
    for pattern, mask in RULES:
        value = pattern.sub(mask, value)
    if len(value) > MAX_TITLE:
        value = value[:MAX_TITLE - 1] + "…"
    return value or "未命名改动"
```

```python
# scripts/devlog/classify.py
"""类型 / 模块 / 代理推断：确定性规则，判不出就给保守默认值。"""
import re
from collections import Counter

TYPE_RULES = [
    ("data", re.compile(r"\b(backfill|recover|restore|reconcile|migrate data|data repair)\b", re.I)),
    ("bug", re.compile(r"^(fix|hotfix|repair|correct|prevent|guard)\b|\bfix(es|ed)?\b", re.I)),
    ("feature", re.compile(r"^(add|implement|introduce|support|enable|feat|create|build)\b", re.I)),
]
PRIORITY = ["feature", "data", "bug", "improve", "ops", "docs"]
SHARED_DIRS = {"core", "api", "services", "models", "schemas", "utils", "bootstrap", "schedulers", "tests",
               "components", "composables", "styles", "config", "layout"}
AGENTS = ("codex", "claude", "kimi", "accio")


def _subject_type(subject: str) -> str:
    for name, pattern in TYPE_RULES:
        if pattern.search(subject):
            return name
    return "improve"


def _path_type(files) -> str | None:
    paths = [path for _, path in files]
    if paths and all(p.startswith("docs/") or p.endswith(".md") for p in paths):
        return "docs"
    if paths and all(p.startswith(("deploy/", "scripts/")) for p in paths):
        return "ops"
    return None


def item_type(subjects: list[str], files=()) -> str:
    counts = Counter(_subject_type(s) for s in subjects)
    by_path = _path_type(files)
    if by_path and set(counts) == {"improve"}:
        return by_path
    best = max(counts.values())
    return next(name for name in PRIORITY if counts.get(name) == best)


def module_of(files) -> str:
    counts = Counter()
    for _, path in files:
        parts = path.split("/")
        if parts[:2] == ["backend", "app"] and len(parts) > 3:
            counts[parts[2]] += 1
        elif parts[:3] == ["frontend", "src", "views"] and len(parts) > 4:
            counts[parts[3].replace("-", "_")] += 1
    for name, _ in counts.most_common():
        if name not in SHARED_DIRS and re.fullmatch(r"[a-z0-9_]{1,40}", name):
            return name
    return ""


def agent_of(branch: str | None, coauthors: str) -> str:
    if branch and branch.split("/")[0] in AGENTS:
        return branch.split("/")[0]
    lowered = coauthors.lower()
    return next((name for name in AGENTS if name in lowered), "unknown")
```

- [ ] **Step 4: 规则测试通过**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests/test_rules.py -q`
Expected: PASS

- [ ] **Step 5: 写归并与状态失败测试**

```python
# scripts/devlog/tests/test_grouping_status.py
import os
import time
from datetime import datetime

from conftest import commit, sh
from grouping import KeyMap, build_groups, is_process_branch
from status import PatchCache, Release, compute_items

SINCE = "2026-10-01"
NOW = datetime(2026, 11, 23, 15, 0)


def collect(repo, tmp_path, releases=(), origin="main", now=NOW):
    cache = PatchCache(tmp_path / "patch-ids.json")
    keymap = KeyMap(tmp_path / "keymap.json")
    groups = build_groups(repo, SINCE, keymap=keymap, cache=cache, now=now)
    items = compute_items(repo, groups, SINCE, releases=list(releases), origin_ref=origin, now=now, cache=cache)
    keymap.save()
    cache.save()
    return items


def by_key(items):
    return {i["key"]: i for i in items}


def test_process_branch_patterns():
    for name in ["main", "origin/main", "codex/global-release-96e42ec3", "codex/release-followup-strategy-20261123",
                 "codex/followup-strategy-main-integration", "codex/x-pilot-release", "codex/outbound-proof-20261111-release",
                 "integration-agent-cloud-20260926", "codex/x-integration-20261019"]:
        assert is_process_branch(name), name
    for name in ["codex/cross-border-review", "accio/private-sea-integration-ce44d944", "codex/release-notes-page"]:
        assert not is_process_branch(name), name


def test_merged_branch_and_cherry_pick_release_counts_as_released(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/strategy")
    fix = commit(repo, "backend/app/domestic_followup/s.py", "retry = 1\n", "Recover truncated strategies", "2026-11-23T11:02:00+08:00")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/strategy", "-m", "Merge branch 'codex/strategy'")
    sh(repo, "checkout", "-b", "codex/release-strategy-20261123", "HEAD~1")   # 发布分支从旧基点 cherry-pick
    sh(repo, "cherry-pick", fix)
    release_rev = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = by_key(collect(repo, tmp_path, [Release(release_rev, datetime(2026, 11, 23, 14, 2), "office-and-cloud")]))
    assert list(items) == ["branch:codex/strategy"]
    item = items["branch:codex/strategy"]
    assert item["status"] == "released" and item["released_revision"] == release_rev
    assert item["status_at"] == "2026-11-23T14:02:00" and item["unmerged_hotfix"] is False
    assert (item["agent"], item["module"], item["type"]) == ("codex", "domestic_followup", "data")


def test_partial_release_does_not_count(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/a")
    commit(repo, "backend/app/stock/a.py", "a = 1\n", "Add a")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/a", "-m", "Merge branch 'codex/a'")
    head = sh(repo, "rev-parse", "HEAD")
    item = collect(repo, tmp_path, [Release(head, datetime(2026, 11, 23, 14), "cloud-only")])[0]
    assert item["status"] == "pending_release"


def test_hotfix_only_on_release_branch_is_released_and_flagged(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/release-hotfix-20261123")
    commit(repo, "backend/app/invoice/h.py", "h = 1\n", "Fix invoice crash")
    release_rev = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = by_key(collect(repo, tmp_path, [Release(release_rev, datetime(2026, 11, 23, 16), "office-and-cloud")]))
    hotfix = items["batch:hotfix-" + release_rev[:12]]
    assert hotfix["status"] == "released" and hotfix["unmerged_hotfix"] is True and hotfix["type"] == "bug"


def test_unnamed_merge_of_deleted_branch_is_one_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/editor")
    commit(repo, "backend/app/invoice/e1.py", "a\n", "Add editor lock")
    commit(repo, "backend/app/invoice/e2.py", "b\n", "Fix editor save")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/editor", "-m", "Merge invoice editor fix")
    sh(repo, "branch", "-D", "codex/editor")
    items = collect(repo, tmp_path)
    assert len(items) == 1 and items[0]["key"].startswith("merge:")
    assert items[0]["title"] == "Merge invoice editor fix" and len([e for e in items[0]["evidences"] if e["kind"] == "commit"]) == 2


def test_unnamed_merge_not_attributed_to_branch_cut_later(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/gone")
    commit(repo, "backend/app/invoice/g.py", "g\n", "Add gone")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/gone", "-m", "Merge gone work")
    sh(repo, "branch", "-D", "codex/gone")
    sh(repo, "branch", "codex/later")   # 合并后才切出的分支，name-rev 会误认它
    items = collect(repo, tmp_path)
    assert [i["key"].split(":")[0] for i in items] == ["merge"]


def test_free_text_sync_merge_is_not_a_feature(repo, tmp_path):
    sh(repo, "checkout", "-b", "elsewhere2")
    commit(repo, "backend/app/stock/q.py", "q\n", "Speed up stock query", "2026-11-21T10:00:00+08:00")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "elsewhere2", "-m", "Merge origin/main into main")
    sh(repo, "branch", "-D", "elsewhere2")
    assert [i["key"] for i in collect(repo, tmp_path)] == ["batch:20261121-stock-unknown"]


def test_same_revision_twice_in_ledger_yields_one_hotfix_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/release-hotfix-20261124")
    commit(repo, "backend/app/invoice/h2.py", "h\n", "Fix invoice crash again")
    rev = sh(repo, "rev-parse", "HEAD")
    sh(repo, "checkout", "main")
    items = collect(repo, tmp_path, [Release(rev, datetime(2026, 11, 24, 9), "office-and-cloud"),
                                     Release(rev, datetime(2026, 11, 24, 10), "office-and-cloud")])
    keys = [i["key"] for i in items]
    assert keys.count("batch:hotfix-" + rev[:12]) == 1
    assert items[0]["status_at"] == "2026-11-24T09:00:00"


def test_sync_merge_of_origin_main_creates_no_fake_branch_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "elsewhere")
    commit(repo, "backend/app/stock/r.py", "r\n", "Speed up stock list", "2026-11-20T10:00:00+08:00")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "elsewhere", "-m", "Merge remote-tracking branch 'origin/main'")
    sh(repo, "branch", "-D", "elsewhere")
    keys = list(by_key(collect(repo, tmp_path)))
    assert keys == ["batch:20261120-stock-unknown"]


def test_same_branch_merged_twice_is_one_item(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/twice")
    commit(repo, "backend/app/stock/t1.py", "1\n", "Add t1")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/twice", "-m", "Merge branch 'codex/twice'")
    sh(repo, "checkout", "codex/twice")
    commit(repo, "backend/app/stock/t2.py", "2\n", "Fix t2")
    sh(repo, "checkout", "main")
    sh(repo, "merge", "--no-ff", "codex/twice", "-m", "Merge branch 'codex/twice'")
    items = collect(repo, tmp_path)
    assert [i["key"] for i in items] == ["branch:codex/twice"]
    assert len([e for e in items[0]["evidences"] if e["kind"] == "commit"]) == 2


def test_direct_commits_group_by_day_module_agent(repo, tmp_path):
    commit(repo, "backend/app/stock/a.py", "a\n", "Speed up stock a", "2026-11-20T10:00:00+08:00")
    commit(repo, "backend/app/stock/b.py", "b\n", "Speed up stock b", "2026-11-20T11:00:00+08:00")
    commit(repo, "backend/app/invoice/c.py", "c\n", "Fix invoice c", "2026-11-20T12:00:00+08:00")
    items = by_key(collect(repo, tmp_path))
    assert set(items) == {"batch:20261120-stock-unknown", "batch:20261120-invoice-unknown"}
    assert items["batch:20261120-stock-unknown"]["title"].endswith("等2项")


def test_keymap_keeps_key_after_fast_forward_and_branch_delete(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/ff")
    commit(repo, "backend/app/stock/f.py", "f\n", "Add ff")
    sh(repo, "checkout", "main")
    assert collect(repo, tmp_path)[0]["key"] == "branch:codex/ff"
    sh(repo, "merge", "--ff-only", "codex/ff")
    sh(repo, "branch", "-D", "codex/ff")
    items = collect(repo, tmp_path)
    assert [(i["key"], i["status"]) for i in items] == [("branch:codex/ff", "pending_release")]


def test_unmerged_branch_states_and_preconditions(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/cross-border")
    commit(repo, "backend/alembic/versions/277_cross_border_review.py", "revision = '277'\n", "Add cross border review")
    commit(repo, "backend/app/core/config.py", "class S:\n    CROSS_BORDER_DXP_ID: str = ''\n", "Add DXP setting")
    commit(repo, "backend/app/auth/service.py", 'P = [\n    ("cross_border:read", "cross_border", "read", "x"),\n]\n', "Add permission")
    sh(repo, "checkout", "main")
    item = collect(repo, tmp_path)[0]
    assert item["key"] == "branch:codex/cross-border" and item["status"] == "pending_merge"
    assert item["preconditions"] == {"migrations": ["277_cross_border_review"], "config_keys": ["CROSS_BORDER_DXP_ID"],
                                     "permissions": ["cross_border:read"]}


def test_local_main_ahead_of_origin_is_pending_push(repo, tmp_path):
    sh(repo, "branch", "origin-snapshot")
    commit(repo, "backend/app/stock/x.py", "x\n", "Speed up stock list", "2026-11-22T10:00:00+08:00")
    item = collect(repo, tmp_path, origin="origin-snapshot")[0]
    assert item["status"] == "pending_push" and item["type"] == "improve"


def test_dev_worktree_only_with_recent_dirt_and_main_dirt_ignored(repo, tmp_path):
    (repo / "scratch.txt").write_text("main dirt", encoding="utf-8")
    sh(repo, "branch", "claude/devlog")
    sh(repo, "branch", "codex/abandoned")
    fresh, old = tmp_path / "fresh", tmp_path / "old"
    sh(repo, "worktree", "add", str(fresh), "claude/devlog")
    sh(repo, "worktree", "add", str(old), "codex/abandoned")
    (fresh / "draft.md").write_text("x", encoding="utf-8")
    stale_file = old / "left.md"
    stale_file.write_text("x", encoding="utf-8")
    past = time.time() - 30 * 86400
    os.utime(stale_file, (past, past))
    # 改动新鲜度按真实当前时间判断（文件 mtime 是真实时间），不用固定的 NOW
    items = collect(repo, tmp_path, now=datetime.now().replace(microsecond=0))
    assert [(i["key"], i["status"]) for i in items] == [("branch:claude/devlog", "dev")]


def test_stale_flag_after_14_days(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/old")
    commit(repo, "backend/app/stock/o.py", "o\n", "Add old idea", "2026-11-01T10:00:00+08:00")
    sh(repo, "checkout", "main")
    item = collect(repo, tmp_path)[0]
    assert item["status"] == "pending_merge" and item["stale"] is True


def test_fingerprint_stable_and_patch_cache_reused(repo, tmp_path):
    sh(repo, "checkout", "-b", "codex/a")
    commit(repo, "backend/app/stock/a.py", "a\n", "Add a")
    sh(repo, "checkout", "main")
    first = collect(repo, tmp_path)[0]
    assert (tmp_path / "patch-ids.json").is_file()
    assert collect(repo, tmp_path)[0]["fingerprint"] == first["fingerprint"]
```

- [ ] **Step 6: 确认失败**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests/test_grouping_status.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'grouping'`

- [ ] **Step 7: 实现 grouping**

```python
# scripts/devlog/grouping.py
"""痕迹 → 事项（P0 用 Git 能确定的最好近似；精确归并靠 P1 会话与人工修正）。

1. main first-parent 上的合并：识别出功能分支名 → branch:<名>（同名多次合并并成一件）；
   名字是 main/master（含 origin/main 同步合并）→ 带进来的提交当作直接提交；
   识别不了或是过程分支 → merge:<sha>，整个合并算一件事，标题用合并信息。
2. 直接提交 → batch:<北京日期>-<模块>-<代理>。
3. 未合入 main 的功能分支（tip 不早于 since）→ main..branch 的提交；
   直接提交若与某未合并分支提交内容等价（cherry-pick 进 main），归该分支。
4. 非 main 的 worktree 有 14 天内的未提交改动 → 证据挂到该分支事项；分支无提交则成为「开发中」事项。
5. 同一提交第一次归到哪件事就永久沿用（KeyMap），防止分支删除 / fast-forward 后键漂移。
"""
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import gitdata
from classify import agent_of, module_of

PROCESS = re.compile(
    r"^(main|master)$|^origin/|(^|/)global-release-|(^|/)release-.*\d{6,}|-release(-\d+)?$"
    r"|main-integration$|(^|/)integration-.*\d{8}|-integration-\d{8}"
)
MERGE_NAME = re.compile(r"^Merge (?:remote-tracking )?branch '([^']+)'")
# 自由文本的同步合并，如「Merge origin/main into main」「Merge main into codex/x」
SYNC_MERGE = re.compile(r"^Merge (?:remote-tracking branch |branch )?'?(?:origin/)?(?:main|master)'?(?:\s+into\b|$)")
DIRTY_FRESH_DAYS = 14


def is_process_branch(name: str) -> bool:
    return bool(PROCESS.search(name))


def _normalize(name: str) -> str:
    return name.removeprefix("origin/")


class KeyMap:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}

    def resolve(self, commits, proposed: str) -> str:
        votes = Counter(self.data[c.sha] for c in commits if c.sha in self.data)
        key = votes.most_common(1)[0][0] if votes else proposed
        for c in commits:
            self.data.setdefault(c.sha, key)
        return key

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.path)


@dataclass
class Group:
    key: str
    branch: str | None = None
    title_hint: str | None = None
    commits: list = field(default_factory=list)
    dirty_files: int = 0
    dirty_mtime: datetime | None = None


def _merge_name(repo, merge) -> str | None:
    if SYNC_MERGE.match(merge.subject):
        return "main"
    match = MERGE_NAME.match(merge.subject)
    if match:
        return _normalize(match.group(1))
    found = gitdata.name_rev(repo, merge.parents[1])
    # name-rev 可能把提交算到「合并之后才从 main 切出」的分支名下（实测 111 个无名合并错 94 个）：
    # 该分支若已包含这次合并本身，说明它不是被合并的那个分支，丢弃名字
    if not found or gitdata.is_ancestor(repo, merge.sha, found):
        return None
    return _normalize(found)


def _batch_key(c) -> str:
    return f"batch:{c.at:%Y%m%d}-{module_of(c.files) or 'misc'}-{agent_of(None, c.coauthors)}"


def build_groups(repo, since: str, *, keymap: KeyMap, cache, now: datetime, main: str = "main") -> list[Group]:
    proposed: dict[str, Group] = {}

    def add(key, commits, branch=None, title_hint=None):
        group = proposed.setdefault(key, Group(key=key, branch=branch, title_hint=title_hint))
        known = {c.sha for c in group.commits}
        group.commits.extend(c for c in commits if c.sha not in known)

    loose = []
    for entry in gitdata.first_parent(repo, main, since):
        if not entry.is_merge:
            loose.append(entry)
            continue
        inner = gitdata.range_commits(repo, entry.parents[0], entry.parents[1])
        if not inner:
            continue
        name = _merge_name(repo, entry)
        if name in ("main", "master"):
            loose.extend(inner)
        elif name and not is_process_branch(name):
            add(f"branch:{name}", inner, branch=name)
        else:
            add(f"merge:{entry.sha}", inner, title_hint=entry.subject)

    since_at = gitdata.to_bj_naive(since + "T00:00:00+08:00")
    open_groups = {}
    for branch in gitdata.branches(repo):
        if is_process_branch(branch.name) or branch.at < since_at:
            continue
        own = gitdata.range_commits(repo, main, branch.name)
        if own:
            open_groups[branch.name] = own
            add(f"branch:{branch.name}", own, branch=branch.name)

    # 直接提交若与未合并分支内容等价，归该分支，避免一件事算两次
    branch_pids = cache.get(repo, [c.sha for own in open_groups.values() for c in own])
    owner = {branch_pids[c.sha]: name for name, own in open_groups.items() for c in own if c.sha in branch_pids}
    loose_pids = cache.get(repo, [c.sha for c in loose])
    for c in loose:
        name = owner.get(loose_pids.get(c.sha))
        add(f"branch:{name}" if name else _batch_key(c), [c], branch=name)

    fresh_after = now - timedelta(days=DIRTY_FRESH_DAYS)
    for tree in gitdata.worktrees(repo):
        if (not tree.branch or tree.branch == main or is_process_branch(tree.branch) or tree.dirty_files == 0
                or tree.dirty_mtime is None or tree.dirty_mtime < fresh_after):
            continue
        group = proposed.setdefault(f"branch:{tree.branch}", Group(key=f"branch:{tree.branch}", branch=tree.branch))
        group.dirty_files, group.dirty_mtime = tree.dirty_files, tree.dirty_mtime

    final: dict[str, Group] = {}
    for group in proposed.values():
        key = keymap.resolve(group.commits, group.key) if group.commits else group.key
        target = final.setdefault(key, Group(key=key, branch=group.branch, title_hint=group.title_hint))
        known = {c.sha for c in target.commits}
        target.commits.extend(c for c in group.commits if c.sha not in known)
        target.branch = target.branch or group.branch
        target.title_hint = target.title_hint or group.title_hint
        if group.dirty_files:
            target.dirty_files, target.dirty_mtime = group.dirty_files, group.dirty_mtime
    for group in final.values():
        group.commits.sort(key=lambda c: c.at)
    return list(final.values())
```

- [ ] **Step 8: 实现 status**

```python
# scripts/devlog/status.py
"""状态判定：先看 sha 是否可达（祖先关系，开销小），不可达时再比 patch-id（cherry-pick 的内容等价）。
patch-id 持久缓存在 .devlog_state/patch-ids.json，首轮之后只算新增提交。只看 Git 证据，不读任何人写的状态词。
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import gitdata
from classify import agent_of, item_type, module_of
from grouping import Group
from redact import redact_title

STALE_DAYS = 14
PID_MARGIN_DAYS = 120
GLOBAL_SCOPE = "office-and-cloud"
CONFIG_LINE = re.compile(r"^\s{4}([A-Z][A-Z0-9_]+)\s*:")
PERMISSION_LINE = re.compile(r'^\s*\("([a-z0-9_]+:[a-z0-9_]+)"')


@dataclass
class Release:
    revision: str
    released_at: datetime
    scope: str


class PatchCache:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}

    def get(self, repo, shas) -> dict[str, str]:
        missing = [s for s in dict.fromkeys(shas) if s not in self.data]
        for start in range(0, len(missing), 400):
            chunk = missing[start:start + 400]
            computed = gitdata.patch_ids(repo, chunk)
            for sha in chunk:
                self.data[sha] = computed.get(sha, "")   # "" = 空 diff，不参与内容比对
        return {s: self.data[s] for s in shas if self.data.get(s)}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        os.replace(tmp, self.path)


class Membership:
    def __init__(self, shas: set[str], pids: set[str]):
        self.shas, self.pids = shas, pids

    def contains(self, sha: str, pid: str | None) -> bool:
        return sha in self.shas or (pid is not None and pid in self.pids)


def _branch_membership(repo, ref, since, cache) -> Membership:
    margin = (datetime.fromisoformat(since) - timedelta(days=PID_MARGIN_DAYS)).date().isoformat()
    recent = gitdata.reachable_shas(repo, ref, margin)
    return Membership(gitdata.reach(repo, ref), set(cache.get(repo, recent).values()))


def _release_membership(repo, release, main, cache) -> Membership:
    only = [c.sha for c in gitdata.range_commits(repo, main, release.revision)]
    return Membership(gitdata.reach(repo, release.revision), set(cache.get(repo, only).values()))


def _hotfix_groups(repo, releases, main, main_m, origin_m, cache) -> list[Group]:
    """只在发布分支上、未回合 main 的提交。同一 revision 只取最早一次；同一提交只归最早那次发布。"""
    groups, seen_revisions, claimed = [], set(), set()
    for release in releases:   # 已按 released_at 升序
        if release.revision in seen_revisions:
            continue
        seen_revisions.add(release.revision)
        only = gitdata.range_commits(repo, main, release.revision)
        pids = cache.get(repo, [c.sha for c in only])
        fixes = [c for c in only if c.sha not in claimed
                 and not main_m.contains(c.sha, pids.get(c.sha)) and not origin_m.contains(c.sha, pids.get(c.sha))]
        claimed.update(c.sha for c in fixes)
        if fixes:
            groups.append(Group(key=f"batch:hotfix-{release.revision[:12]}", commits=fixes))
    return groups


def _preconditions(repo, commits):
    migrations, config_keys, permissions = [], [], []
    for c in commits:
        for change, path in c.files:
            if change == "A" and path.startswith("backend/alembic/versions/") and path.endswith(".py"):
                migrations.append(path.rsplit("/", 1)[-1][:-3])
            if path == "backend/app/core/config.py":
                config_keys += [m.group(1) for line in gitdata.show_added_lines(repo, c.sha, path) if (m := CONFIG_LINE.match(line))]
            if path == "backend/app/auth/service.py":
                permissions += [m.group(1) for line in gitdata.show_added_lines(repo, c.sha, path) if (m := PERMISSION_LINE.match(line))]
    unique = lambda values: list(dict.fromkeys(values))[:20]
    return {"migrations": unique(migrations), "config_keys": unique(config_keys), "permissions": unique(permissions)}


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _title(group: Group, subjects: list[str]) -> str:
    if group.title_hint:
        return redact_title(group.title_hint)
    if subjects:
        text = subjects[0] + (f" 等{len(subjects)}项" if group.key.startswith("batch:") and len(subjects) > 1 else "")
        if len(text) > 40 and text.endswith("项"):   # 保住「等N项」后缀
            suffix = f" 等{len(subjects)}项"
            text = subjects[0][:40 - len(suffix) - 1] + "…" + suffix
        return redact_title(text)
    return redact_title((group.branch or "").split("/")[-1].replace("-", " "))


def compute_items(repo, groups, since, *, releases, cache, origin_ref="origin/main", main="main", now: datetime) -> list[dict]:
    main_m = _branch_membership(repo, main, since, cache)
    origin_m = _branch_membership(repo, origin_ref, since, cache)
    global_releases = sorted((r for r in releases if r.scope == GLOBAL_SCOPE), key=lambda r: r.released_at)
    release_ms = [(r, _release_membership(repo, r, main, cache)) for r in global_releases]
    groups = list(groups) + _hotfix_groups(repo, global_releases, main, main_m, origin_m, cache)
    items = []
    for group in groups:
        commits = group.commits
        pids = cache.get(repo, [c.sha for c in commits])
        relevant = [c for c in commits if c.sha in pids] or commits

        def covered(m):
            return bool(relevant) and all(m.contains(c.sha, pids.get(c.sha)) for c in relevant)

        last_commit_at = max((c.at for c in commits), default=None)
        released = next((r for r, m in release_ms if covered(m)), None)
        if not commits:
            status, status_at = "dev", group.dirty_mtime
        elif released:
            status, status_at = "released", released.released_at
        elif covered(origin_m):
            status, status_at = "pending_release", last_commit_at
        elif covered(main_m):
            status, status_at = "pending_push", last_commit_at
        else:
            status, status_at = "pending_merge", last_commit_at
        last_activity = max(t for t in (last_commit_at, group.dirty_mtime, status_at) if t)
        stale = status != "released" and last_activity < now - timedelta(days=STALE_DAYS)
        subjects = [c.subject for c in commits]
        files = [f for c in commits for f in c.files]
        evidences = [{"kind": "branch", "ref": group.branch, "at": _iso(last_activity)}] if group.branch else []
        evidences += [{"kind": "commit", "ref": c.sha, "at": _iso(c.at)} for c in commits[-50:]]
        if released:
            evidences.append({"kind": "release", "ref": released.revision, "at": _iso(released.released_at)})
        if group.dirty_files:
            evidences.append({"kind": "worktree", "ref": f"dirty-{group.dirty_files}", "at": _iso(group.dirty_mtime)})
        item = {
            "key": group.key, "title": _title(group, subjects), "type": item_type(subjects or ["Add draft"], files),
            "module": module_of(files), "agent": agent_of(group.branch, " ".join(c.coauthors for c in commits)),
            "status": status, "status_at": _iso(status_at), "last_activity_at": _iso(last_activity), "stale": stale,
            "unmerged_hotfix": bool(released) and not covered(main_m),
            "released_revision": released.revision if released else None,
            "preconditions": _preconditions(repo, commits) if status != "released" else {"migrations": [], "config_keys": [], "permissions": []},
            "evidences": evidences,
        }
        basis = {k: item[k] for k in ("key", "status", "stale", "released_revision", "title", "type", "module")}
        basis["commits"] = sorted(c.sha for c in commits)
        basis["dirty"] = group.dirty_files
        item["fingerprint"] = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
        items.append(item)
    return items
```

性能说明（第 2 轮审查在真实仓库实测）：
- 首轮约 47 秒，有缓存后约 35 秒，其中 worktree 扫描约 6.5 秒；
- patch-id 只对 main / origin 最近 `since - 120 天` 的提交，以及发布独有的少量提交计算，并持久缓存；
- 每 2 小时跑一次可以接受。Task 11 Step 6 把两次耗时记进 handoff，超过 2 分钟再优化（例如合并多次 `range_commits` 调用）。

**事项键重置**：开发调试期间只要改了归并规则，就先删掉 `.devlog_state/keymap.json` 再干跑，否则旧规则分出的错误键会被永久沿用。上线后不要随意删除，删了会让全部事项换键，库里留下一批 superseded 的旧事项。

- [ ] **Step 9: 测试通过**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests -q`
Expected: 全部 PASS。失败时先查实现是否偏离 Step 7/8 的规则，不要为凑测试去改断言。最容易出问题的三处：
- `name_rev` 在分支已删除时返回 None；
- `range_commits` 的提交顺序；
- `KeyMap` 第二轮复用的键。

- [ ] **Step 10: Commit**

```powershell
git add scripts/devlog/redact.py scripts/devlog/classify.py scripts/devlog/grouping.py scripts/devlog/status.py scripts/devlog/tests/test_rules.py scripts/devlog/tests/test_grouping_status.py
git commit -m "Group git traces into stable devlog items with ancestry-first status and hotfix detection"
```


---

### Task 11: 采集器 CLI、推送客户端、账本回填

**Files:**
- Create: `scripts/devlog/client.py`
- Create: `scripts/devlog/collect.py`
- Create: `scripts/devlog/backfill_releases.py`
- Test: `scripts/devlog/tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# scripts/devlog/tests/test_cli.py
import json
from datetime import datetime

from conftest import commit, sh
import backfill_releases
import collect


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
    assert {s["name"]: s["ok"] for s in payload["sources"]} == {"git": True, "fetch": True, "releases": False}
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
```

- [ ] **Step 2: 确认失败**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests/test_cli.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 实现 client**

```python
# scripts/devlog/client.py
"""读取开发机本地配置（.devlog_state/collector.json，Git 忽略），调用生产机器端点。token 不进代码、不打印。"""
import json
import urllib.request
from pathlib import Path


def load_config(state: Path) -> dict | None:
    path = state / "collector.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("base_url") or len(data.get("token", "")) < 24:
        return None
    return data


def _request(config, method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(config["base_url"].rstrip("/") + path, data=data, method=method,
                                     headers={"X-Devlog-Token": config["token"], "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(config, path, body):
    return _request(config, "POST", path, body)


def get_json(config, path):
    return _request(config, "GET", path)
```

- [ ] **Step 4: 实现 collect**

```python
# scripts/devlog/collect.py
"""方舟开发动态采集器。

python scripts/devlog/collect.py               # 采集并写 .devlog_state/last-payload.json，不联网推送
python scripts/devlog/collect.py --push        # 采集后推送生产（需 collector.json，且须亮哥授权启用）
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client  # noqa: E402
import gitdata  # noqa: E402
from grouping import KeyMap, build_groups  # noqa: E402
from status import PatchCache, Release, compute_items  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _now(value: str | None) -> datetime:
    return datetime.fromisoformat(value) if value else datetime.now(gitdata.BJ).replace(tzinfo=None)


def _releases(repo, state, config, sources):
    cache = state / "releases.json"
    rows = None
    if config:
        try:
            rows = client.get_json(config, "/api/devlog/machine/releases")["data"]["items"]
            cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        except Exception as error:
            print(f"[devlog] release ledger unavailable: {type(error).__name__}", flush=True)
    if rows is None and cache.is_file():
        rows = json.loads(cache.read_text(encoding="utf-8"))
    if rows is None:
        sources.append({"name": "releases", "ok": False, "detail": "no ledger"})
        return []
    missing = [r["revision"][:8] for r in rows if not gitdata.object_exists(repo, r["revision"])]
    sources.append({"name": "releases", "ok": not missing, "detail": ("missing " + ",".join(missing))[:120] if missing else ""})
    return [Release(r["revision"], datetime.fromisoformat(r["released_at"]), r["scope"])
            for r in rows if gitdata.object_exists(repo, r["revision"])]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--state", default=str(REPO / ".devlog_state"))
    parser.add_argument("--since", default="2026-09-01")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--now", help="测试用：固定北京时间")
    args = parser.parse_args(argv)
    repo, state = Path(args.repo), Path(args.state)
    state.mkdir(parents=True, exist_ok=True)
    config = client.load_config(state)
    if args.push and not config:
        print("[devlog] --push 需要 .devlog_state/collector.json（base_url + token）", flush=True)
        return 2
    started = _now(args.now)
    sources = []
    fetched, detail = (True, "") if args.no_fetch else gitdata.fetch(repo)
    sources.append({"name": "fetch", "ok": fetched, "detail": detail})
    releases = _releases(repo, state, config if args.push else None, sources)
    origin = "origin/main" if gitdata.object_exists(repo, "origin/main") else "main"
    cache = PatchCache(state / "patch-ids.json")
    keymap = KeyMap(state / "keymap.json")
    try:
        groups = build_groups(repo, args.since, keymap=keymap, cache=cache, now=started)
        items = compute_items(repo, groups, args.since, releases=releases, origin_ref=origin, now=started, cache=cache)
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
        if not next(s["ok"] for s in sources if s["name"] == "releases"):
            # 账本读不全就算不出「已发布」，推上去会把已发布事项整体降级并写入假事件
            print("[devlog] 发布账本不可用或有 revision 本地缺失，本轮不推送；payload 已留在本地供排查", flush=True)
            return 3
        result = client.post_json(config, "/api/devlog/ingest", payload)
        print(f"[devlog] pushed: {json.dumps(result.get('data'), ensure_ascii=False)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 实现回填**

```python
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
    except (OSError, ValueError):
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
        if receipt:
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
        rows.append(_row(sha, datetime.fromisoformat(at), "manual"))
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
```

- [ ] **Step 6: 测试通过 + 本机真实仓库干跑**

Run: `backend\.venv\Scripts\python.exe -m pytest scripts/devlog/tests -q`
Expected: 全部 PASS

Run: `backend\.venv\Scripts\python.exe scripts/devlog/collect.py --no-fetch`
Expected: 打印 `[devlog] N items collected`（第 2 轮审查实测约 380 条），并生成 `.devlog_state/last-payload.json`、`keymap.json`、`patch-ids.json`。用 `Measure-Command` 记下首轮和第二轮的耗时（实测约 47 秒 / 35 秒）。抽查：
- `branch:codex/cross-border-review` 一类功能分支的状态合理；
- 没有 `branch:main`、`branch:origin/main`、`codex/global-release-*` 这样的事项；
- payload 里 key 不重复：`python -c "import json;d=json.load(open('.devlog_state/last-payload.json',encoding='utf-8'));k=[i['key'] for i in d['items']];print(len(k),len(set(k)))"` 两个数相等；
- `dev` 事项数应在个位数到十几个，不应接近 35 个脏 worktree 的数量；
- 没有某个分支事项吞下几十次合并的情况：统计每个事项的 commit 证据数，前 5 名逐个看是否合理；
- 干跑期间其他代理的 worktree 没有出现 `index.lock` 冲突（状态读取用 `--no-optional-locks`）；
- 标题里没有邮箱、金额、长数字。

抽查结果和事项总数写进 Task 14 的 handoff 条目。此时还没有账本缓存，所有事项都不会是 `released`，这是预期行为。

Run: `backend\.venv\Scripts\python.exe scripts/devlog/backfill_releases.py`
Expected: 列出 `global-release-*` 回填行（第 2 轮审查实测只有 6～7 条，最早在 11-13）和跳过的目录。**不加 `--apply`**。

**`--apply` 之前必做（写进 Task 15 的授权材料）：**
- 只回填目录里的记录不够：实测 361 个已发布事项中，有 331 个的发布时间会被压到 11-13，周报口径严重失真。必须按 handoff 里日期最新的全局发布记录，用 `--add <sha>@<北京时间>` 补齐 2026-09-01 到 2026-11-12 的每一次**全局**发布。只发一台或单个组件的专项发布不补。
- 标「文件修改时间」的行，要和 handoff 的发布时间逐条核对。
- 抽查方法：补齐后加 `--write-cache` 再跑一次回填脚本（仍不加 `--apply`），然后干跑一次 `collect.py --no-fetch`，统计 `released` 事项的 `status_at` 按日期的分布，不能出现单日堆积几百条的情况。统计命令：`python -c "import json,collections;d=json.load(open('.devlog_state/last-payload.json',encoding='utf-8'));print(collections.Counter(i['status_at'][:10] for i in d['items'] if i['status']=='released').most_common(10))"`。

- [ ] **Step 7: Commit**

```powershell
git add scripts/devlog/client.py scripts/devlog/collect.py scripts/devlog/backfill_releases.py scripts/devlog/tests/test_cli.py
git commit -m "Add devlog collector CLI, push client and release backfill"
```

---

### Task 12: 前端 API 与展示逻辑

**Files:**
- Modify: `frontend/src/api/clients.js`
- Create: `frontend/src/api/devlog.js`
- Create: `frontend/src/views/devlog/devlogPresentation.js`
- Create: `frontend/src/views/devlog/composables/useDevlogBoard.js`
- Modify: `frontend/package.json`（scripts）
- Test: `frontend/tests/devlog.test.mjs`

- [ ] **Step 1: 写失败测试**

```javascript
// frontend/tests/devlog.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { COLUMN_LABELS, STATUS_LABELS, TYPE_META, readinessLabel, rangeFor, preconditionTags } from '../src/views/devlog/devlogPresentation.js'

test('range presets are Beijing calendar based and inclusive', () => {
  assert.deepEqual(rangeFor('day', '2026-11-23'), { start: '2026-11-23', end: '2026-11-23' })
  assert.deepEqual(rangeFor('week', '2026-11-23'), { start: '2026-11-17', end: '2026-11-23' })
  assert.deepEqual(rangeFor('month', '2026-11-23'), { start: '2026-11-01', end: '2026-11-23' })
})

test('status, column and type labels cover every backend value', () => {
  for (const s of ['dev', 'pending_merge', 'pending_push', 'pending_release', 'released']) assert.ok(STATUS_LABELS[s])
  assert.deepEqual(Object.keys(COLUMN_LABELS), ['dev', 'committed', 'released'])
  for (const t of ['feature', 'improve', 'bug', 'data', 'ops', 'docs']) assert.ok(TYPE_META[t].label && TYPE_META[t].tone)
})

test('readiness wording tells what to do next', () => {
  assert.equal(readinessLabel({ status: 'pending_merge', ready: false }), '先合入 main')
  assert.equal(readinessLabel({ status: 'pending_push', ready: false }), '先推送')
  assert.equal(readinessLabel({ status: 'pending_release', ready: false }), '先完成前提')
  assert.equal(readinessLabel({ status: 'pending_release', ready: true }), '可以')
})

test('precondition tags list migrations, config and permissions', () => {
  assert.deepEqual(preconditionTags({ migrations: ['277_x'], config_keys: ['A_B'], permissions: ['x:read'] }).map(t => t.text),
    ['迁移 277_x', '配置 A_B', '权限 x:read'])
})

test('api module uses the shared client and no raw colors leak into the page', async () => {
  const api = await readFile(new URL('../src/api/devlog.js', import.meta.url), 'utf8')
  assert.match(api, /from '\.\/clients'/)
  const page = await readFile(new URL('../src/views/devlog/DevlogBoard.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(page.replace(/<!--[\s\S]*?-->/g, ''), /#[0-9a-fA-F]{3,8}\b/)
})
```

- [ ] **Step 2: 加脚本并确认失败**

`frontend/package.json` 的 `scripts` 里紧跟 `"test:cross-border"` 加一行：

```json
    "test:devlog": "node --test tests/devlog.test.mjs",
```

Run: `cd frontend; npm run test:devlog`
Expected: FAIL，找不到 `devlogPresentation.js`

- [ ] **Step 3: client 与 API**

`frontend/src/api/clients.js` 在 `crossBorderClient` 那一行后追加：

```javascript
export const devlogClient = createApiClient({ baseURL: '/api/devlog', timeout: 30000 })
```

```javascript
// frontend/src/api/devlog.js
import { devlogClient as client } from './clients'
const quiet = { showLoading: false, suppressToast: true }
const clean = params => Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v != null))
export const devlogApi = {
  summary: (params, config) => client.get('/summary', { ...quiet, ...config, params: clean(params) }),
  item: (id, config) => client.get(`/items/${id}`, { ...quiet, ...config }),
  pending: config => client.get('/pending', { ...quiet, ...config }),
  health: config => client.get('/health', { ...quiet, ...config }),
}
```

- [ ] **Step 4: 展示逻辑**

```javascript
// frontend/src/views/devlog/devlogPresentation.js
/** 方舟开发动态的纯展示规则：文案、颜色语义、日期范围（北京时间日历）。 */
export const STATUS_LABELS = {
  dev: '开发中', pending_merge: '待合并', pending_push: '待推送', pending_release: '待发布', released: '已发布',
}
export const COLUMN_LABELS = { dev: '开发中', committed: '已提交', released: '已发布' }
export const TYPE_META = {
  feature: { label: '新功能', tone: 'gold' },
  improve: { label: '改进', tone: 'info' },
  bug: { label: 'BUG 修复', tone: 'danger' },
  data: { label: '数据修复', tone: 'violet' },
  ops: { label: '运维发布', tone: 'neutral' },
  docs: { label: '规范文档', tone: 'neutral' },
}
export const AGENT_LABELS = { codex: 'Codex', claude: 'Claude', kimi: 'Kimi', accio: 'Accio', unknown: '未标注' }
export const SUB_TONE = { pending_merge: 'info', pending_push: 'gold', pending_release: 'warning' }

function shift(isoDate, days) {
  const [y, m, d] = isoDate.split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d + days))
  return date.toISOString().slice(0, 10)   // 纯日历运算，UTC 午夜不涉及时区换算
}

export function rangeFor(kind, today) {
  if (kind === 'day') return { start: today, end: today }
  if (kind === 'week') return { start: shift(today, -6), end: today }
  if (kind === 'month') return { start: `${today.slice(0, 7)}-01`, end: today }
  throw new Error(`unknown range ${kind}`)
}

export function readinessLabel(item) {
  if (item.status === 'pending_merge') return '先合入 main'
  if (item.status === 'pending_push') return '先推送'
  return item.ready ? '可以' : '先完成前提'
}

export function preconditionTags(pre = {}) {
  return [
    ...(pre.migrations || []).map(text => ({ text: `迁移 ${text}`, tone: 'warning' })),
    ...(pre.config_keys || []).map(text => ({ text: `配置 ${text}`, tone: 'gold' })),
    ...(pre.permissions || []).map(text => ({ text: `权限 ${text}`, tone: 'info' })),
  ]
}

export function shortSha(value) {
  return /^[0-9a-f]{40}$/.test(value || '') ? value.slice(0, 8) : value
}
```

`rangeFor` 里的 `toISOString().slice(0,10)` 只作用在由日历日构造的 UTC 午夜上，结果等价于纯日期运算，不读取客户端时区。如果约定检查对这一行报黄，就在报告里说明原因，不要改成 `currentBeijingDate`，否则会把「今天」的来源和日历运算混在一起。

- [ ] **Step 5: 页面状态 composable**

```javascript
// frontend/src/views/devlog/composables/useDevlogBoard.js
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource.js'
import { currentBeijingDate } from '@/utils/datetime.js'
import { devlogApi } from '@/api/devlog.js'
import { rangeFor } from '../devlogPresentation.js'

export function useDevlogBoard() {
  const today = currentBeijingDate()
  const filters = reactive({ range: 'week', custom: [], type: '', module: '', agent: '' })
  const tab = ref('board')
  const drawer = reactive({ open: false, id: null })
  const period = computed(() => filters.range === 'custom' && filters.custom?.length === 2
    ? { start: filters.custom[0], end: filters.custom[1] }
    : rangeFor(filters.range === 'custom' ? 'week' : filters.range, today))
  const summary = useAsyncResource((params, { signal }) => devlogApi.summary(params, { signal }).then(r => r.data),
    { initialData: { kpis: {}, columns: { dev: [], committed: [], released: [] }, timeline: [] } })
  const health = useAsyncResource((_, { signal }) => devlogApi.health({ signal }).then(r => r.data))
  const pending = useAsyncResource((_, { signal }) => devlogApi.pending({ signal }).then(r => r.data.items), { initialData: [] })
  const detail = useAsyncResource((id, { signal }) => devlogApi.item(id, { signal }).then(r => r.data))
  // 只有健康信息真正加载成功才判断过期；加载中或请求失败不冒充「开发机未上报」
  const syncState = computed(() => {
    if (health.error.value) return 'unknown'
    if (!health.hasLoaded.value) return 'loading'
    if (!health.data.value?.last_sync_at) return 'never'
    return health.data.value.is_stale ? 'stale' : 'fresh'
  })
  const stale = computed(() => syncState.value === 'stale' || syncState.value === 'never')
  const pendingReleaseCount = computed(() => pending.data.value.filter(item => item.status === 'pending_release').length)

  function load() {
    summary.load({ ...period.value, type: filters.type, module: filters.module, agent: filters.agent })
  }
  function openItem(id) {
    drawer.id = id; drawer.open = true
    detail.load(id, { clear: true })
  }
  function pickKpi(key) {
    if (key === 'pending_release') tab.value = 'pending'
    else if (key === 'bugs') { filters.type = filters.type === 'bug' ? '' : 'bug'; tab.value = 'board' }
  }
  watch(() => [period.value.start, period.value.end, filters.type, filters.module, filters.agent], load)
  onMounted(() => { load(); health.load(); pending.load() })
  return { today, filters, tab, drawer, period, summary, health, pending, detail, stale, syncState, pendingReleaseCount, openItem, pickKpi, load }
}
```

先确认 `frontend/src/composables/useAsyncResource.js` 的返回值里有 `hasLoaded`：它在该文件第 7 行定义。如果没有返回，就在 return 里补上，并同步跑一遍使用它的既有页面测试。

- [ ] **Step 6: 测试除页面断言外通过**

Run: `cd frontend; npm run test:devlog`
Expected: 只有最后一条（读 `DevlogBoard.vue`）还失败，因为页面要到 Task 13 才写

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/api/clients.js frontend/src/api/devlog.js frontend/src/views/devlog/devlogPresentation.js frontend/src/views/devlog/composables/useDevlogBoard.js frontend/package.json frontend/tests/devlog.test.mjs
git commit -m "Add devlog frontend API, presentation rules and board state"
```

---

### Task 13: 页面、抽屉、导航

**Files:**
- Create: `frontend/src/views/devlog/DevlogBoard.vue`
- Create: `frontend/src/views/devlog/DevlogItemDrawer.vue`
- Modify: `frontend/src/config/navigation.js`（`/system/navigation` entry 之后）
- Modify（构建自动生成）: `backend/app/system/navigation_access_manifest.json`、`backend/app/system/navigation_config_catalog.json`

视觉以原型 `docs/prototypes/ark-devlog-board.html` 为准：
- KPI 用 `components/OverviewMetricCard.vue`，tone 对应：上线功能 gold / 修复问题 success / 数据修复 violet / 开发中 info / 待发布 warning；
- 看板列和时间线用 `.lg-card` 玻璃面板，抽屉用 `components/DetailDrawer.vue`；
- 动效只保留卡片 hover（仅精确指针）和按压缩放，筛选、切页签不加动画（DESIGN.md 看板概览卡片节）。

- [ ] **Step 1: 抽屉组件**

```vue
<!-- frontend/src/views/devlog/DevlogItemDrawer.vue -->
<template>
  <DetailDrawer :model-value="modelValue" :title="item?.title || '事项详情'" @update:model-value="$emit('update:modelValue', $event)">
    <el-skeleton v-if="loading && !item" :rows="6" animated />
    <el-alert v-else-if="error" type="error" :closable="false" title="详情加载失败" />
    <div v-else-if="item" class="devlog-drawer">
      <div class="devlog-drawer__tags">
        <StatusBadge :type="tagType(TYPE_META[item.type].tone)" effect="light" :label="TYPE_META[item.type].label" />
        <StatusBadge v-if="item.status !== 'released'" type="warning" :label="STATUS_LABELS[item.status]" />
        <StatusBadge v-if="item.unmerged_hotfix" type="danger" label="未回合 main" />
        <span class="devlog-drawer__meta">{{ item.module || '未归模块' }} · {{ AGENT_LABELS[item.agent] }}</span>
      </div>
      <section>
        <h3 class="devlog-drawer__h">进度</h3>
        <ol class="devlog-steps">
          <li v-for="event in item.events" :key="event.at + event.to_status" class="is-done">
            <span class="devlog-steps__dot" aria-hidden="true" />
            <span>{{ STATUS_LABELS[event.to_status] }}</span>
            <time>{{ event.at.replace('T', ' ') }}</time>
          </li>
        </ol>
        <p v-if="item.released_revision" class="devlog-drawer__note">
          发布版本 <code>{{ shortSha(item.released_revision) }}</code>（按代码内容比对）
        </p>
      </section>
      <section v-if="tags.length">
        <h3 class="devlog-drawer__h">上线前提</h3>
        <div class="devlog-drawer__tags"><StatusBadge v-for="tag in tags" :key="tag.text" :type="tagType(tag.tone)" :label="tag.text" /></div>
      </section>
      <section>
        <h3 class="devlog-drawer__h">证据</h3>
        <ul class="devlog-evidence">
          <li v-for="e in item.evidences" :key="e.kind + e.ref">
            <span class="devlog-evidence__kind">{{ EVIDENCE_LABELS[e.kind] }}</span>
            <code>{{ shortSha(e.ref) }}</code>
            <time>{{ e.at.replace('T', ' ') }}</time>
          </li>
        </ul>
      </section>
    </div>
  </DetailDrawer>
</template>

<script setup>
import { computed } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { AGENT_LABELS, STATUS_LABELS, TYPE_META, preconditionTags, shortSha } from './devlogPresentation.js'

const props = defineProps({ modelValue: Boolean, item: Object, loading: Boolean, error: [Object, String, null] })
defineEmits(['update:modelValue'])
const EVIDENCE_LABELS = { branch: '分支', commit: 'commit', release: '发布', worktree: '未提交改动' }
const tags = computed(() => preconditionTags(props.item?.preconditions))
const tagType = tone => ({ gold: 'warning', info: 'primary', danger: 'danger', violet: 'info', neutral: 'info', warning: 'warning', success: 'success' }[tone] || 'info')
</script>

<style scoped>
.devlog-drawer { display: flex; flex-direction: column; gap: 18px; }
.devlog-drawer__tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.devlog-drawer__meta { font-size: 12px; color: var(--text-muted); }
.devlog-drawer__h { margin: 0 0 8px; font: 700 12px/1.4 Outfit, sans-serif; letter-spacing: 0.08em; color: var(--text-muted); }
.devlog-drawer__note { margin: 4px 0 0; font-size: 12px; color: var(--text-secondary); }
.devlog-steps { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
.devlog-steps li { display: grid; grid-template-columns: 14px minmax(0, 1fr) auto; gap: 10px; align-items: center; font-size: 13px; }
.devlog-steps__dot { width: 12px; height: 12px; border-radius: 50%; background: var(--tag-success-solid); }
.devlog-steps time, .devlog-evidence time { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.devlog-evidence { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.devlog-evidence li { display: flex; gap: 8px; align-items: center; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border-color); background: var(--toolbar-bg); font-size: 13px; }
.devlog-evidence__kind { width: 72px; flex: none; font-size: 12px; color: var(--text-muted); }
.devlog-evidence time { margin-left: auto; }
</style>
```

实现前用 `Grep` 核对 `tokens.css` 里是否存在 `--text-muted`、`--text-secondary`、`--border-color`、`--toolbar-bg`、`--tag-success-solid`。不存在的，换成 tokens.css 里同义的现有变量名（例如中性边框可能叫 `--color-border`），**不新增裸 hex**。

- [ ] **Step 2: 页面**

```vue
<!-- frontend/src/views/devlog/DevlogBoard.vue -->
<template>
  <div class="devlog-page" :class="{ 'is-stale': stale }">
    <div class="devlog-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="devlog-head">
      <h1 class="devlog-head__title">方舟开发动态</h1>
      <div class="devlog-sync" role="status">
        <span class="devlog-sync__dot" :class="{ 'is-warn': stale }" aria-hidden="true" />
        <template v-if="health.data.value?.last_sync_at">最后同步 {{ health.data.value.last_sync_at.slice(11) }}</template>
        <template v-else>尚未同步</template>
        <template v-if="ledger"> · 账本最新 <code>{{ shortSha(ledger.revision) }}</code>（{{ ledger.released_at.slice(5, 16).replace('T', ' ') }}）</template>
      </div>
    </header>

    <el-alert v-if="syncState === 'stale'" class="devlog-stale" type="warning" :closable="false" show-icon
      :title="`数据截至 ${health.data.value.last_sync_at.replace('T', ' ')}，开发机可能未开机。数字仅供参考，别用它判断能否发布。`" />
    <el-alert v-else-if="syncState === 'never'" class="devlog-stale" type="warning" :closable="false" show-icon title="开发机还没有上报过数据。" />
    <el-alert v-else-if="syncState === 'unknown'" class="devlog-stale" type="error" :closable="false" show-icon title="同步状态读取失败，请刷新重试。" />

    <div class="devlog-bar">
      <el-radio-group v-model="filters.range" aria-label="时间范围">
        <el-radio-button value="day">今日</el-radio-button><el-radio-button value="week">本周</el-radio-button>
        <el-radio-button value="month">本月</el-radio-button><el-radio-button value="custom">自定义</el-radio-button>
      </el-radio-group>
      <el-date-picker v-if="filters.range === 'custom'" v-model="filters.custom" type="daterange" value-format="YYYY-MM-DD" unlink-panels class="filter-w-lg" />
      <span v-else class="devlog-bar__range">{{ period.start }} ~ {{ period.end }}</span>
      <el-select v-model="filters.type" clearable placeholder="全部类型" class="filter-w-sm">
        <el-option v-for="(meta, key) in TYPE_META" :key="key" :label="meta.label" :value="key" />
      </el-select>
      <el-select v-model="filters.agent" clearable placeholder="全部代理" class="filter-w-sm">
        <el-option v-for="(label, key) in AGENT_LABELS" :key="key" :label="label" :value="key" />
      </el-select>
    </div>

    <div class="devlog-data">
      <div class="devlog-kpis">
        <OverviewMetricCard label="上线功能" :value="kpis.features ?? '—'" :icon="Promotion" tone="gold" hint="所选期间已发布" />
        <OverviewMetricCard label="修复问题" :value="kpis.bugs ?? '—'" :icon="CircleCheck" tone="success" hint="所选期间已发布"
          interactive :selected="filters.type === 'bug'" @click="pickKpi('bugs')" />
        <OverviewMetricCard label="数据修复" :value="kpis.data ?? '—'" :icon="Coin" tone="violet" hint="P1 起接入" />
        <OverviewMetricCard label="开发中" :value="kpis.dev ?? '—'" :icon="EditPen" tone="info" :hint="kpis.stale ? `另有 ${kpis.stale} 项停滞` : ''" />
        <OverviewMetricCard label="待发布" :value="kpis.pending_release ?? '—'" :icon="Clock" tone="warning" hint="已合入 main，未部署"
          interactive :selected="tab === 'pending'" @click="pickKpi('pending_release')" />
      </div>

      <el-tabs v-model="tab" class="devlog-tabs">
        <el-tab-pane label="看板" name="board">
          <el-alert v-if="summary.error.value" type="error" :closable="false" title="加载失败" />
          <div v-else class="devlog-board">
            <section v-for="(label, key) in COLUMN_LABELS" :key="key" class="devlog-col lg-card is-static" :aria-label="label">
              <h2 class="devlog-col__h"><span class="devlog-col__bar" :class="`is-${key}`" />{{ label }}<span class="devlog-col__n">{{ columns[key].length }}</span></h2>
              <button v-for="item in columns[key]" :key="item.id" type="button" class="devlog-card" @click="openItem(item.id)">
                <span class="devlog-card__tags">
                  <StatusBadge :type="tagType(TYPE_META[item.type].tone)" effect="light" :label="TYPE_META[item.type].label" />
                  <StatusBadge v-if="key === 'committed'" :type="tagType(SUB_TONE[item.status])" :label="STATUS_LABELS[item.status]" />
                  <StatusBadge v-if="item.unmerged_hotfix" type="danger" label="未回合 main" />
                </span>
                <span class="devlog-card__title">{{ item.title }}</span>
                <span class="devlog-card__meta">{{ item.module || '未归模块' }} · {{ AGENT_LABELS[item.agent] }} · {{ item.status_at.slice(5, 10) }}</span>
              </button>
              <p v-if="!columns[key].length" class="devlog-empty">这段时间没有</p>
            </section>
          </div>
        </el-tab-pane>

        <el-tab-pane label="时间线" name="timeline">
          <p v-if="!summary.data.value.timeline.length" class="devlog-empty">这段时间没有状态变化</p>
          <section v-for="day in summary.data.value.timeline" :key="day.date" class="devlog-day lg-card is-static">
            <h2 class="devlog-day__h">{{ day.date.slice(5) }}<span>{{ day.entries.length }} 条变化</span></h2>
            <ul class="devlog-day__list">
              <li v-for="entry in day.entries" :key="entry.id + entry.to_status">
                <StatusBadge :type="tagType(TYPE_META[entry.type].tone)" effect="light" :label="TYPE_META[entry.type].label" />
                <span class="devlog-day__to">{{ STATUS_LABELS[entry.to_status] }}</span>
                <button type="button" class="devlog-link" @click="openItem(entry.id)">{{ entry.title }}</button>
              </li>
            </ul>
          </section>
        </el-tab-pane>

        <el-tab-pane :label="`待发布清单 ${pendingReleaseCount}`" name="pending">
          <div class="devlog-table lg-card is-static">
            <el-table :data="pending.data.value" v-loading="pending.loading.value" border class="list-table" v-sticky-scrollbar>
              <template #empty><el-empty :image-size="96" :description="pending.error.value ? '加载失败，请刷新重试' : '没有待上线的事项'" /></template>
              <el-table-column label="事项" min-width="220" max-width="360" show-overflow-tooltip>
                <template #default="{ row }"><button type="button" class="devlog-link" @click="openItem(row.id)">{{ row.title }}</button></template>
              </el-table-column>
              <el-table-column label="状态" min-width="100" max-width="120">
                <template #default="{ row }"><StatusBadge :type="tagType(SUB_TONE[row.status])" :label="STATUS_LABELS[row.status]" /></template>
              </el-table-column>
              <el-table-column label="上线前提" min-width="260" max-width="420">
                <template #default="{ row }">
                  <span class="devlog-card__tags">
                    <StatusBadge v-for="tag in preconditionTags(row.preconditions)" :key="tag.text" :type="tagType(tag.tone)" :label="tag.text" />
                    <span v-if="!preconditionTags(row.preconditions).length" class="devlog-muted">无</span>
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="模块" prop="module" min-width="120" max-width="180" show-overflow-tooltip />
              <el-table-column label="能否随下次发布" min-width="140" max-width="180">
                <template #default="{ row }"><span :class="row.ready ? 'devlog-ok' : 'devlog-warn'">{{ readinessLabel(row) }}</span></template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <DevlogItemDrawer v-model="drawer.open" :item="detail.data.value" :loading="detail.loading.value" :error="detail.error.value" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { CircleCheck, Clock, Coin, EditPen, Promotion } from '@element-plus/icons-vue'
import OverviewMetricCard from '@/components/OverviewMetricCard.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import DevlogItemDrawer from './DevlogItemDrawer.vue'
import { useDevlogBoard } from './composables/useDevlogBoard.js'
import { AGENT_LABELS, COLUMN_LABELS, STATUS_LABELS, SUB_TONE, TYPE_META, preconditionTags, readinessLabel, shortSha } from './devlogPresentation.js'

const { filters, tab, drawer, period, summary, health, pending, detail, stale, syncState, pendingReleaseCount, openItem, pickKpi } = useDevlogBoard()
const kpis = computed(() => summary.data.value.kpis || {})
const columns = computed(() => summary.data.value.columns)
const ledger = computed(() => health.data.value?.ledger_latest)
const tagType = tone => ({ gold: 'warning', info: 'primary', danger: 'danger', violet: 'info', neutral: 'info', warning: 'warning', success: 'success' }[tone] || 'info')
</script>

<style scoped>
.devlog-page { position: relative; }
.devlog-aurora { inset: -24px -28px; }
.devlog-head, .devlog-stale, .devlog-bar, .devlog-data { position: relative; z-index: 1; }
.devlog-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.devlog-head__title { margin: 0; font: 700 17px/1.3 Outfit, sans-serif; }
.devlog-sync { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-secondary); }
.devlog-sync__dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tag-success-solid); }
.devlog-sync__dot.is-warn { background: var(--tag-warning-solid); }
.devlog-stale { margin-bottom: 14px; }
.devlog-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 16px; }
.devlog-bar__range { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.is-stale .devlog-data { filter: grayscale(0.85); opacity: 0.55; }
.devlog-kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin-bottom: 8px; }
.devlog-board { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; align-items: start; }
.devlog-col { padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.devlog-col__h { display: flex; align-items: center; gap: 8px; margin: 0 0 2px; font: 700 15px/1.3 Outfit, sans-serif; }
.devlog-col__bar { width: 4px; height: 16px; border-radius: 2px; }
.devlog-col__bar.is-dev { background: var(--tag-info-solid); }
.devlog-col__bar.is-committed { background: var(--tag-warning-solid); }
.devlog-col__bar.is-released { background: var(--tag-success-solid); }
.devlog-col__n { font-size: 12px; font-weight: 500; color: var(--text-muted); }
.devlog-card { display: flex; flex-direction: column; gap: 6px; width: 100%; text-align: left; padding: 10px 12px; border-radius: 12px;
  border: 1px solid var(--border-color); background: var(--button-surface); cursor: pointer;
  transition: transform 200ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 200ms cubic-bezier(0.23, 1, 0.32, 1); }
.devlog-card:active { transform: scale(0.98); }
@media (hover: hover) and (pointer: fine) { .devlog-card:hover { transform: translateY(-2px); box-shadow: var(--dash-glass-shadow); } }
.devlog-card:focus-visible, .devlog-link:focus-visible { outline: 2px solid var(--button-primary); outline-offset: 2px; }
.devlog-card__tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.devlog-card__title { font-size: 14px; font-weight: 600; line-height: 1.4; color: var(--text-primary); }
.devlog-card__meta, .devlog-muted { font-size: 12px; color: var(--text-muted); }
.devlog-empty { margin: 0; padding: 24px 8px; text-align: center; font-size: 13px; color: var(--text-muted); }
.devlog-day { padding: 14px 18px; margin-bottom: 12px; }
.devlog-day__h { display: flex; gap: 10px; align-items: baseline; margin: 0 0 8px; font: 700 15px/1.3 Outfit, sans-serif; }
.devlog-day__h span { font: 500 12px/1 'DM Sans', sans-serif; color: var(--text-muted); }
.devlog-day__list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.devlog-day__list li { display: flex; gap: 8px; align-items: center; font-size: 13px; }
.devlog-day__to { width: 52px; flex: none; font-size: 12px; color: var(--text-secondary); }
.devlog-link { border: 0; background: none; padding: 0; text-align: left; font-weight: 600; color: var(--button-primary-text); cursor: pointer; }
@media (hover: hover) and (pointer: fine) { .devlog-link:hover { text-decoration: underline; } }
.devlog-table { padding: 4px; }
.devlog-ok { color: var(--tag-success-text); font-weight: 600; }
.devlog-warn { color: var(--tag-warning-text); font-weight: 600; }
@media (max-width: 1180px) { .devlog-kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px) { .devlog-board { grid-template-columns: minmax(0, 1fr); } }
@media (max-width: 768px) {
  .devlog-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .devlog-kpis > :last-child { grid-column: span 2; }
}
@media (prefers-reduced-motion: reduce) { .devlog-card, .devlog-card:active { transition: none; transform: none; } }
</style>
```

同样先用 `Grep` 核对样式里用到的每个 CSS 变量都在 `tokens.css` 或 `liquid-glass.css` 中定义过，再用 Element Plus 图标表确认 `Promotion`、`CircleCheck`、`Coin`、`EditPen`、`Clock` 存在。

- [ ] **Step 3: 导航 entry**（`navigation.js` 中 `/system/navigation` entry 之后）

```javascript
  {
    path: '/system/devlog', name: 'DevlogBoard',
    component: () => import('@/views/devlog/DevlogBoard.vue'),
    title: '方舟开发动态', permission: 'devlog:read',
    menu: { group: 'system', title: '方舟开发动态', icon: DataBoard, order: 90, permission: 'devlog:read' },
  },
```

并在同一文件的 `system` 分组 `anyPermission` 数组里加 `'devlog:read'`，否则只有这个权限的用户看不到分组（文件内已有注释说明这个坑）。`DataBoard` 已在该文件中被 import，不需要新增。

- [ ] **Step 4: 构建与前端测试**

Run: `cd frontend; npm run test:devlog`
Expected: 全部 PASS

Run: `cd frontend; node --test tests/navigationCatalog.test.mjs`
Expected: PASS

Run: `cd frontend; npm run build`
Expected: 构建成功；`backend/app/system/navigation_access_manifest.json`、`navigation_config_catalog.json` 被插件更新，新增了 `/system/devlog`。**注意**：这两个文件在主目录里有亮哥未提交的改动。worktree 里是干净副本，只提交插件生成的 devlog 相关差异。合并时如有冲突，以重新构建的结果为准，不要手写。

- [ ] **Step 5: 浏览器验收（夹具隔离，不连任何后端）**

开发配置连的库里没有 devlog 表，接口会 500，所以不用 `start.bat`。按 `frontend/tests/fixtures/navigation-badge/` 的做法建夹具，替换所有 client 的 adapter，所有请求都在浏览器内返回假数据：

```html
<!-- frontend/tests/fixtures/devlog-board/index.html -->
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Devlog board fixture</title></head><body><div id="app"></div><script type="module" src="./main.js"></script></body></html>
```

```javascript
// frontend/tests/fixtures/devlog-board/main.js
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import '../../../src/styles/liquid-glass.css'
import DevlogBoard from '../../../src/views/devlog/DevlogBoard.vue'
import * as clients from '../../../src/api/clients'
// 每个请求都在浏览器内返回夹具数据；?state=stale|never|error|empty 切换状态
const state = new URLSearchParams(location.search).get('state') || 'fresh'
const item = (id, title, type, status, at, extra = {}) => ({ id, key: `branch:codex/${id}`, title, type, module: 'invoice', agent: 'codex',
  status, status_at: at, last_activity_at: at, stale: false, unmerged_hotfix: false, released_revision: null,
  preconditions: { migrations: [], config_keys: [], permissions: [] }, ...extra })
const items = state === 'empty' ? [] : [
  item(1, 'Add 9610 cross-border review', 'feature', 'pending_release', '2026-11-23T09:05',
    { preconditions: { migrations: ['276_invoice_alibaba_order', '277_cross_border_review'], config_keys: ['CROSS_BORDER_DXP_ID'], permissions: ['cross_border:read'] } }),
  item(2, 'Recover truncated strategies', 'bug', 'released', '2026-11-23T14:02', { released_revision: 'd1f5bbb7f83f0f8d96daf664d2c621bd0be61a3d' }),
  item(3, 'Devlog board', 'feature', 'dev', '2026-11-23T15:10'),
  item(4, 'Private research evidence binding', 'bug', 'pending_merge', '2026-11-17T10:00'),
]
const col = s => s === 'dev' ? 'dev' : s === 'released' ? 'released' : 'committed'
const routes = {
  '/summary': () => ({ kpis: { features: 0, bugs: 1, data: 0, dev: 1, pending_release: 1, stale: 6 },
    columns: { dev: items.filter(i => col(i.status) === 'dev'), committed: items.filter(i => col(i.status) === 'committed'), released: items.filter(i => col(i.status) === 'released') },
    timeline: items.length ? [{ date: '2026-11-23', entries: items.map(i => ({ ...i, to_status: i.status, occurred_at: i.status_at })) }] : [] }),
  '/health': () => ({ last_sync_at: state === 'never' ? null : state === 'stale' ? '2026-11-23T07:12' : '2026-11-23T15:20',
    is_stale: state !== 'fresh' && state !== 'empty', hours_since_sync: 8.1, sources: [],
    ledger_latest: { revision: 'd1f5bbb7f83f0f8d96daf664d2c621bd0be61a3d', released_at: '2026-11-23T14:02:00', scope: 'office-and-cloud' } }),
  '/pending': () => ({ items: items.filter(i => i.status.startsWith('pending')).map(i => ({ ...i, ready: i.status === 'pending_release' && !i.preconditions.config_keys.length })) }),
}
for (const client of Object.values(clients)) if (client?.defaults) client.defaults.adapter = async config => {
  if (state === 'error' && config.url === '/health') return Promise.reject(Object.assign(new Error('fixture'), { config, response: { status: 500, data: {} } }))
  const detail = config.url.match(/^\/items\/(\d+)/)
  const data = detail ? { ...items.find(i => i.id === Number(detail[1])), evidences: [{ kind: 'commit', ref: 'b8c1bd75a1b2c3d4e5f60718293a4b5c6d7e8f90', at: '2026-11-23T09:05' }],
    events: [{ from_status: null, to_status: 'pending_merge', at: '2026-11-22T18:40' }] } : (routes[config.url]?.() ?? {})
  return { config, status: 200, headers: {}, data: { code: 200, message: 'ok', data } }
}
createApp({ components: { DevlogBoard }, template: '<main style="padding:24px 28px"><DevlogBoard /></main>' }).use(ElementPlus).mount('#app')
```

如果 `DevlogBoard` 用到的 `v-sticky-scrollbar` 等全局指令在夹具里报未注册，就照 `frontend/src/main.js` 注册指令的方式，在夹具里补上同一个注册调用，不要从页面里删掉指令。

Run（后台运行）：`cd frontend; npx vite --port 3301 --strictPort`

在内置浏览器里依次打开 `http://localhost:3301/tests/fixtures/devlog-board/index.html`，并分别加上 `?state=stale`、`?state=never`、`?state=error`、`?state=empty`。逐项核对：
- fresh：KPI、三列看板、时间线、待发布清单（页签计数为 1）、详情抽屉正常；
- stale：顶部黄色提示、数据区变灰；
- never：「开发机还没有上报过数据」；
- error：显示红色「同步状态读取失败」，**不**显示「未上报」；
- empty：各列显示「这段时间没有」，表格显示空状态；
- 375px 宽度下 KPI 两列、无横向滚动；
- 控制台没有报错。

每种状态截一张图，存到 `tmp/devlog-p0/`（已被 Git 忽略）。

上线后的真实数据截图验收见 Task 15 Step 5。

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/devlog/DevlogBoard.vue frontend/src/views/devlog/DevlogItemDrawer.vue frontend/tests/fixtures/devlog-board/index.html frontend/tests/fixtures/devlog-board/main.js frontend/src/config/navigation.js backend/app/system/navigation_access_manifest.json backend/app/system/navigation_config_catalog.json
git commit -m "Add devlog board page with kanban, timeline and pending release list"
```

---

### Task 14: 文档同步

**Files:**
- Modify: `docs/api-reference.md`（加 devlog 端点一节）
- Modify: `docs/database.md`（加 5 张表）
- Modify: `docs/module-notes.md`（加「方舟开发动态」专题）
- Modify: `docs/runbook.md`（token 轮换 + 采集器排障）
- Modify: `docs/handoff.md`（顶部新条目）
- Modify: `docs/requirements/2026-11-23-ark-devlog-board-design.md`（状态改为「P0 已实现，待部署」）

- [ ] **Step 1: api-reference.md**：按文件现有格式列出 7 个端点，并标明两个机器端点只认 `X-Devlog-Token`。
- [ ] **Step 2: database.md**：按「命名宪法」表格格式登记 `ark_devlog_items / evidences / item_events / releases / sync_runs`，写明「证据只存标识不存原文」。
- [ ] **Step 3: module-notes.md 写这几条坑：**
  - 「已发布」按 patch-id 判断，不按祖先关系。原因：生产版本是 cherry-pick 出来的，例子是 `07c450d8` 与 `d1f5bbb7`；
  - 发布账本只由部署器写，cloud-only 发布不算全局；
  - 上报里缺席的事项不删除；
  - 过程分支的识别规则、KeyMap 的作用，以及「删除 `.devlog_state/keymap.json` 会让事项键重新分配」；
  - 已知缺口：恢复入口不写账本（发生恢复发布后用 `backfill_releases.py --add` 补）；运行版本校验推迟到 P1；
  - P1/P2 待办清单。
- [ ] **Step 4: runbook.md 写两部分：**
  - token 轮换：生成新 token → 把新哈希追加到 `DEVLOG_INGEST_TOKEN_HASHES` 并发布 → 改开发机 `.devlog_state/collector.json` → 删掉旧哈希；
  - 采集器排障：看 `.devlog_state/last-payload.json`、页面「来源」状态、`ark_devlog_sync_runs.failed_keys`。
- [ ] **Step 5: handoff.md**：写「2026-11-2X 方舟开发动态 P0（Claude Code，待部署）」条目，内容包括分支名、测试结果、Task 11 干跑抽查结论，以及待授权事项（对应 Task 15 的清单）。
- [ ] **Step 6: Commit**

```powershell
git add docs/api-reference.md docs/database.md docs/module-notes.md docs/runbook.md docs/handoff.md docs/requirements/2026-11-23-ark-devlog-board-design.md
git commit -m "Document devlog P0 endpoints, tables, pitfalls and operations"
```

---

### Task 15: 完工验证与待授权上线清单

**Files:** 无新代码

- [ ] **Step 1: 全量验证**

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q
```
```powershell
backend\.venv\Scripts\python.exe -m pytest deploy/tests scripts/devlog/tests -q
```
```powershell
cd frontend; npm run test:devlog; npm run build
```
```powershell
python scripts/check_conventions.py --base main
```
```powershell
python scripts/git_sweep.py --no-fetch
```

Expected:
- 新增测试全部通过；全量后端测试与 main 基线一致（先在 main 上跑一次记下基线，已有失败如实列出）；
- 约定检查无红项；如有机械阈值黄项，写明原因；
- `git_sweep` 无本分支相关欠账。

- [ ] **Step 2: 按 `completion-checklist` skill 逐项核对**，不适用的项写明原因。

- [ ] **Step 3: 对抗性审查**：本次改动涉及对外写入通道、部署器和 3 个以上非测试文件，按用户级规则交给 1 个独立 Agent 审查。只给它设计稿、本计划和 `git diff main...claude/devlog-p0`，最多两轮。

- [ ] **Step 4: 把下面的待授权清单交给亮哥，每一项单独确认，未获授权不执行：**

| # | 动作 | 为什么要授权 |
|---|---|---|
| 1 | 合并 `claude/devlog-p0` 到 main（在主目录执行） | 合并回 main 需授权 |
| 2 | push main | 远端写入 |
| 3 | `deploy\deploy.bat` 全局发布（含迁移 `278_devlog_tables`） | 部署 + 生产 schema 变更（只新建表） |
| 4 | 在办公室与北京后端 `.env` 配置 `DEVLOG_INGEST_TOKEN_HASHES`，开发机写 `.devlog_state/collector.json` | 新增开发机→生产写入通道 |
| 5 | 角色管理页给亮哥（及指定技术人员）分配 `devlog:read` | 权限变更 |
| 6 | 临时打开 `DEVLOG_BACKFILL_ENABLED`，执行 `backfill_releases.py --apply`，完成后关闭开关。执行前先给亮哥看两份材料：用 `--add` 补齐 09-01 起全部全局发布后的清单，以及按日期统计的分布 | 生产写入 |
| 7 | 首次 `collect.py --push`，再注册 Windows 计划任务（8:00–23:00 每 2 小时） | 定时远端写入 |

第 7 项的计划任务命令（等授权后再执行）：

```powershell
schtasks /Create /TN "ArkDevlogCollector" /SC HOURLY /MO 2 /ST 08:00 /ET 23:00 /TR "\"D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe\" \"D:\MyProgram\commission-system\scripts\devlog\collect.py\" --push"
```

- [ ] **Step 5: 上线后验收（授权完成后）**：
  - 页面同步状态为绿色，「账本最新」与 handoff 里最新的全局发布一致；
  - 抽 3 件已知事项核对状态：`07c450d8` 那次跟进策略修复应为「已发布」；跨境申报核对在部署前应为「待发布」，并列出迁移 276/277 和 `CROSS_BORDER_*` 配置；
  - 截图留证。
