# 任务中心一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在方舟里上线个人任务中心一期：领域模块 `app/task/`，树形 / 看板 / 模块地图三视图，导航悬浮 `+` 和页头「记任务」两个快速入口，一句话 AI 建任务，模块注册表（导航清单在构建期导出），简版每日简报（不含 git）。

**Architecture:** 后端新增自包含领域模块 `app/task/`：models / errors / service（任务树与状态机）/ module_service / ai_service / brief_service / scheduler / router。数据按 `owner_id` 隔离；个人规模下，树操作一次载入该 owner 的全部任务，在内存里计算。前端新增 `/task` 页面和一个全局快速建任务浮层；导航清单由 vite 插件在构建收尾时导出为 `nav-manifest.json`，后端在启动时读取并同步（只有开启 Settings 开关的环境才写库）。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + APScheduler；Vue 3 + Element Plus + Vite 5；pytest（SQLite 内存库）；`node --test`。

**执行记录（2026-10-01）：** 计划中的 `172_task_center` 已与现有 `172_workbench_lifecycle` 冲突，实际使用 `173_task_center`（父版本 `172_workbench_lifecycle`）；实现分支为 `codex/task-center-phase1`。原步骤保留为历史计划，不应直接照旧命令执行。

**依据：** 设计文档 `docs/superpowers/specs/2026-09-30-task-center-design.md`；原型 `docs/requirements/task-center-prototype/`。

---

## 前置约束（执行前必读）

1. **数据库**：开发配置尚未隔离，**本计划全程不执行 `alembic upgrade`，也不跑任何连接真实 MySQL 的写入型测试**。后端测试全部走 `tests/conftest.py` 的 SQLite 内存库。迁移只做两项离线检查：`alembic heads` 只剩一个 head，以及 `check_conventions.py`。真正建表由 `deploy\deploy.bat` 统一执行。
2. **迁移编号**：写迁移前先跑 `git log --all --oneline -- backend/alembic/versions/`，并列出各分支里的最大编号。写本计划时（2026-09-30）最新是 `171_customer_tag_display_value`，所以本计划用 `172_task_center`。若执行时已被占用，顺延编号，同时改 `down_revision`。
3. **Worktree**：在自己的 worktree `commission-system-task-center`（分支 `claude/task-center`）里开发。主目录只做 merge。push 和合并都要等亮哥授权。
4. **时间**：写库只能用 `beijing_now()` / `beijing_today()`；前端的日期统一用 `utils/datetime.js`。
5. **每个 task 完成后**先跑该 task 的测试，再 commit。commit message 用英文。

## 文件地图

**后端（新建）**

| 文件 | 职责 |
|------|------|
| `backend/app/task/__init__.py` | 包标记 |
| `backend/app/task/models.py` | 5 张表 + 常量（优先级 / 状态 / 深度上限） |
| `backend/app/task/errors.py` | 领域异常（带 HTTP 状态码） |
| `backend/app/task/service.py` | 任务 CRUD、树规则、状态机、回收站、统计、序列化 |
| `backend/app/task/module_service.py` | 模块注册表：默认种子、导航清单同步、私有分类 |
| `backend/app/task/ai_service.py` | 一句话建任务的草稿（值域在运行时注入，失败降级） |
| `backend/app/task/brief_service.py` | 每日简报：确定性排序、AI 选前三、模板降级、钉钉 markdown |
| `backend/app/task/scheduler.py` | 08:53 简报推送任务 |
| `backend/app/task/schemas.py` | Pydantic 入参 |
| `backend/app/task/router.py` | HTTP 薄适配层 |
| `backend/app/bootstrap/seed_task.py` | 启动期：默认模块种子 + 导航清单同步 |
| `backend/alembic/versions/172_task_center.py` | 建表迁移 |
| `backend/tests/task_helpers.py` | 测试用户 / 客户端工具 |
| `backend/tests/test_task_*.py` | 各层测试 |

**后端（修改）**：`app/routers.py`（注册路由）、`app/auth/service.py`（权限种子）、`app/bootstrap/seed_ai.py`（2 个 preset）、`app/bootstrap/__init__.py` 与 `app/main.py`（启动种子）、`app/core/config.py`（`TASK_MODULE_SYNC_ENABLED`）、`app/schedulers/registry.py`（任务注册）、`tests/conftest.py`（导入模型）。

**前端（新建）**

| 文件 | 职责 |
|------|------|
| `frontend/src/config/navManifest.js` | 纯函数：`MENU_GROUPS` + `NAV_ENTRIES` → 清单 |
| `frontend/src/api/task.js` | 任务 API |
| `frontend/src/composables/useQuickTask.js` | 快速建任务的全局单例状态 |
| `frontend/src/components/task/QuickTaskPopover.vue` | 快速建任务浮层（全局挂载） |
| `frontend/src/views/task/taskLabels.js` | 状态 / 优先级文案与样式映射（纯） |
| `frontend/src/views/task/taskTree.js` | 树筛选、叶子收集、看板列（纯） |
| `frontend/src/views/task/TaskCenter.vue` | 页面壳：统计、简报、工具栏、视图切换 |
| `frontend/src/views/task/composables/useTaskCenter.js` | 页面状态与动作 |
| `frontend/src/views/task/components/TaskTreeView.vue` | 树形视图 |
| `frontend/src/views/task/components/TaskBoardView.vue` | 看板视图 |
| `frontend/src/views/task/components/TaskModuleMap.vue` | 模块地图 |
| `frontend/src/views/task/components/TaskBriefCard.vue` | 今日简报卡 |
| `frontend/src/views/task/components/TaskDetailDrawer.vue` | 详情抽屉 |
| `frontend/tests/taskCenter.test.mjs` | 纯函数测试 |

**前端（修改）**：`api/clients.js`、`config/navigation.js`、`views/layout/SidebarNavigation.vue`、`views/layout/MainLayout.vue`、`vite.config.js`、`package.json`。

**文档（修改）**：`docs/api-reference.md`、`docs/database.md`、`docs/module-notes.md`、`docs/handoff.md`，另在设计文档里注明「工作台卡片推迟到二期」。

---

### Task 0: 建 worktree 并提交设计资料

**Files:** 无代码改动

- [ ] **Step 1: 建 worktree**

```bash
cd /d/MyProgram/commission-system
git worktree add ../commission-system-task-center -b claude/task-center main
```

- [ ] **Step 2: 把主目录里未提交的设计资料拷进 worktree**

```bash
cd /d/MyProgram/commission-system
cp docs/superpowers/specs/2026-09-30-task-center-design.md ../commission-system-task-center/docs/superpowers/specs/
cp docs/superpowers/plans/2026-09-30-task-center-phase1.md ../commission-system-task-center/docs/superpowers/plans/
cp -r docs/requirements/task-center-prototype ../commission-system-task-center/docs/requirements/
```

- [ ] **Step 3: 在 worktree 里核对并提交**

```bash
cd /d/MyProgram/commission-system-task-center
git rev-parse --show-toplevel && git branch --show-current   # 期望 .../commission-system-task-center 与 claude/task-center
git add docs/superpowers/specs/2026-09-30-task-center-design.md docs/superpowers/plans/2026-09-30-task-center-phase1.md docs/requirements/task-center-prototype
git commit -m "docs: add task center design, prototype and phase 1 plan"
```

- [ ] **Step 4: 删除主目录里的三份副本，避免两处各改一份**

```bash
cd /d/MyProgram/commission-system
rm docs/superpowers/specs/2026-09-30-task-center-design.md docs/superpowers/plans/2026-09-30-task-center-phase1.md
rm -r docs/requirements/task-center-prototype
```

- [ ] **Step 5: 准备后端虚拟环境**

worktree 里没有 `backend/.venv`，直接用主目录的解释器（依赖相同）：

```bash
export ARK_PY=/d/MyProgram/commission-system/backend/.venv/Scripts/python.exe
cd /d/MyProgram/commission-system-task-center/backend && $ARK_PY -m pytest tests/test_training_service.py -q 2>/dev/null | tail -1
```

Expected：输出一行 `passed` 汇总，证明解释器可用。若该测试文件不存在，换成 `tests/test_announcement.py`。之后所有 `pytest` 命令都在 `backend/` 下用 `$ARK_PY -m pytest` 执行。

- [ ] **Step 6: 安装前端依赖**（新 worktree 没有 `node_modules`，否则后续 `npm run build` 找不到 vite）

```bash
cd /d/MyProgram/commission-system-task-center/frontend && npm ci --no-audit --no-fund
```

Expected：安装完成，`node_modules/.bin/vite` 存在。

---

### Task 1: 模型、异常与迁移

**Files:**
- Create: `backend/app/task/__init__.py`、`backend/app/task/models.py`、`backend/app/task/errors.py`、`backend/alembic/versions/172_task_center.py`、`backend/tests/task_helpers.py`、`backend/tests/test_task_models.py`
- Modify: `backend/tests/conftest.py`（导入区）

- [ ] **Step 1: 写失败测试 `backend/tests/test_task_models.py`**

```python
"""任务中心模型：建表、编号派生、唯一约束。"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.task.models import TaskBrief, TaskItem, TaskLink, TaskModule
from tests.task_helpers import make_user


def test_task_code_derives_from_id(db):
    owner = make_user(db, "tc_owner")
    db.add(TaskModule(key="custom.report", kind="custom", group_key="custom", group_title="方舟外", title="汇报材料"))
    task = TaskItem(owner_id=owner.id, title="写汇报", module_key="custom.report")
    db.add(task)
    db.flush()
    assert task.code == f"T-{task.id}"
    assert task.status == "todo" and task.priority == "P2"


def test_link_unique_per_task_kind_ref(db):
    owner = make_user(db, "tc_link")
    task = TaskItem(owner_id=owner.id, title="挂文档")
    db.add(task)
    db.flush()
    db.add(TaskLink(task_id=task.id, kind="doc", ref="docs/a.md", title="a"))
    db.flush()
    db.add(TaskLink(task_id=task.id, kind="doc", ref="docs/a.md", title="a"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_brief_unique_per_owner_and_date(db):
    from datetime import date
    owner = make_user(db, "tc_brief")
    db.add(TaskBrief(owner_id=owner.id, brief_date=date(2026, 9, 30), content_json={}, source="template"))
    db.flush()
    db.add(TaskBrief(owner_id=owner.id, brief_date=date(2026, 9, 30), content_json={}, source="template"))
    with pytest.raises(IntegrityError):
        db.flush()
```

- [ ] **Step 2: 写测试工具 `backend/tests/task_helpers.py`**

```python
"""任务中心测试工具：建用户、带 JWT 的 TestClient。"""
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.models import ArkUser
from app.auth.utils import create_access_token
from app.core.database import get_db


def make_user(db, username, dingtalk_id=None):
    user = ArkUser(username=username, password_hash="test-hash", real_name=username, dingtalk_id=dingtalk_id)
    db.add(user)
    db.flush()
    return user


@contextmanager
def task_client(db, user, permissions=("task:read", "task:write")):
    from app.task.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/task")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    token = create_access_token({
        "sub": str(user.id), "username": user.username, "real_name": user.real_name,
        "roles": [], "permissions": list(permissions),
    })
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client
```

- [ ] **Step 3: 在 `backend/tests/conftest.py` 的模型导入区末尾加一行**

在 `from app.system import models as _system_models  # noqa: F401` 下面追加：

```python
# 任务中心表 FK 指向 ark_users，单跑测试文件时需显式导入
from app.task import models as _task_models  # noqa: F401
```

- [ ] **Step 4: 运行测试确认失败**

Run: `$ARK_PY -m pytest tests/test_task_models.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.task'`

- [ ] **Step 5: 写 `backend/app/task/__init__.py`**

```python
"""任务中心：个人任务树 + 方舟模块关联 + AI 建任务 + 每日简报。"""
```

- [ ] **Step 6: 写 `backend/app/task/errors.py`**

```python
"""任务中心领域异常。router 统一转换为 HTTPException，detail 为中文提示。"""


class TaskError(Exception):
    status_code = 400

    def __init__(self, message: str, code: str | None = None, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


class TaskNotFound(TaskError):
    status_code = 404


class TaskConflict(TaskError):
    status_code = 409


class TaskInvalid(TaskError):
    status_code = 422
```

- [ ] **Step 7: 写 `backend/app/task/models.py`**

```python
"""任务中心数据模型。全部按 owner_id 隔离；编号 T-<id> 由自增主键派生，不另建序列。"""
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects import mysql

from app.core.database import Base
from app.core.time import beijing_now

USER_ID = mysql.INTEGER(unsigned=True)

PRIORITIES = ("P0", "P1", "P2", "P3")
PRIORITY_LABELS = {"P0": "紧急", "P1": "高", "P2": "中", "P3": "低"}
STATUSES = ("todo", "in_progress", "blocked", "pending_confirm", "done", "shelved")
STATUS_LABELS = {
    "todo": "待办", "in_progress": "进行中", "blocked": "受阻",
    "pending_confirm": "待确认", "done": "已完成", "shelved": "已搁置",
}
OPEN_STATUSES = ("todo", "in_progress", "blocked")
CLOSED_STATUSES = ("done", "shelved")
MODULE_KINDS = ("nav", "infra", "custom")
LINK_KINDS = ("doc", "prototype", "url")  # 二期追加 branch / commit / merge
SOURCES = ("manual", "nav_quick", "header_quick", "ai_split", "mcp")
MAX_DEPTH = 4


class TaskModule(Base):
    __tablename__ = "ark_task_modules"
    __table_args__ = {"comment": "任务中心-模块注册表（nav 条目来自构建期导出的 navigation 清单）"}

    key = Column(String(100), primary_key=True, comment="模块键：nav=前端路由 name；infra.* / custom.*")
    kind = Column(String(10), nullable=False, comment="nav/infra/custom")
    group_key = Column(String(64), nullable=False, default="", comment="分组键")
    group_title = Column(String(64), nullable=False, default="", comment="分组名称")
    title = Column(String(100), nullable=False, comment="模块名称")
    route = Column(String(200), nullable=True, comment="前端路由 path（nav 才有）")
    sort_order = Column(Integer, nullable=False, default=0, comment="组内排序")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=True, comment="私有分类所有者；公共条目为空")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否有效（清单中消失即置 0，旧任务保留引用）")
    synced_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="最近同步时间")


class TaskItem(Base):
    __tablename__ = "ark_task_items"
    __table_args__ = (
        Index("idx_ark_task_items_owner_status", "owner_id", "status"),
        Index("idx_ark_task_items_owner_parent", "owner_id", "parent_id"),
        {"comment": "任务中心-任务（树形，parent_id 自关联）"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键；编号 T-<id>")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="所有者 ark_users.id")
    parent_id = Column(BigInteger, ForeignKey("ark_task_items.id"), nullable=True, comment="父任务 ark_task_items.id")
    title = Column(String(200), nullable=False, comment="标题")
    description = Column(Text, nullable=True, comment="描述")
    acceptance = Column(JSON, nullable=True, comment="验收标准列表（AI 提议完成的对照依据）")
    priority = Column(String(2), nullable=False, default="P2", comment="P0 紧急/P1 高/P2 中/P3 低")
    status = Column(String(20), nullable=False, default="todo", comment="todo/in_progress/blocked/pending_confirm/done/shelved")
    blocked_reason = Column(String(500), nullable=True, comment="受阻原因（置 blocked 必填）")
    module_key = Column(String(100), ForeignKey("ark_task_modules.key"), nullable=True, comment="关联模块 ark_task_modules.key")
    due_date = Column(Date, nullable=True, comment="截止日期（北京时间）")
    sort_order = Column(Integer, nullable=False, default=0, comment="同级排序")
    source = Column(String(20), nullable=False, default="manual", comment="manual/nav_quick/header_quick/ai_split/mcp")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=beijing_now, onupdate=beijing_now, comment="更新时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    deleted_at = Column(DateTime, nullable=True, comment="软删时间")
    delete_batch = Column(String(32), nullable=True, comment="软删批次号：同一次删除的子树共用，恢复按批次整体还原")

    @property
    def code(self) -> str:
        return f"T-{self.id}"


class TaskLink(Base):
    __tablename__ = "ark_task_links"
    __table_args__ = (
        UniqueConstraint("task_id", "kind", "ref", name="uq_ark_task_links_task_kind_ref"),
        {"comment": "任务中心-任务关联（一期 doc/prototype/url；二期 git 类）"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(BigInteger, ForeignKey("ark_task_items.id"), nullable=False, comment="任务 ark_task_items.id")
    kind = Column(String(20), nullable=False, comment="doc/prototype/url（二期 branch/commit/merge）")
    ref = Column(String(500), nullable=False, comment="仓库路径 / URL / sha")
    title = Column(String(200), nullable=False, default="", comment="显示名")
    match = Column(String(10), nullable=False, default="exact", comment="exact/suggested")
    state = Column(String(10), nullable=False, default="active", comment="active/pending/rejected")
    payload_json = Column(JSON, nullable=True, comment="附加信息")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="创建时间")


class TaskEvent(Base):
    __tablename__ = "ark_task_events"
    __table_args__ = (
        Index("idx_ark_task_events_task", "task_id"),
        {"comment": "任务中心-任务时间线"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    task_id = Column(BigInteger, ForeignKey("ark_task_items.id"), nullable=False, comment="任务 ark_task_items.id")
    actor = Column(String(10), nullable=False, comment="user/ai/reporter/mcp")
    type = Column(String(30), nullable=False, comment="created/updated/status_changed/moved/deleted/restored/linked/unlinked")
    payload_json = Column(JSON, nullable=True, comment="事件详情")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="发生时间")


class TaskBrief(Base):
    __tablename__ = "ark_task_briefs"
    __table_args__ = (
        UniqueConstraint("owner_id", "brief_date", name="uq_ark_task_briefs_owner_date"),
        {"comment": "任务中心-每日简报"},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    owner_id = Column(USER_ID, ForeignKey("ark_users.id"), nullable=False, comment="所有者 ark_users.id")
    brief_date = Column(Date, nullable=False, comment="简报日期（北京时间）")
    content_json = Column(JSON, nullable=False, comment="简报内容：top/pending_confirm/overdue/blocked")
    source = Column(String(10), nullable=False, comment="ai/template")
    pushed_at = Column(DateTime, nullable=True, comment="钉钉推送时间")
    created_at = Column(DateTime, nullable=False, default=beijing_now, comment="生成时间")
```

- [ ] **Step 8: 运行测试确认通过**

Run: `$ARK_PY -m pytest tests/test_task_models.py -q`
Expected: `3 passed`

- [ ] **Step 9: 写迁移 `backend/alembic/versions/172_task_center.py`**

```python
"""Task center phase 1: modules, items, links, events, daily briefs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "172_task_center"
down_revision = "171_customer_tag_display_value"
branch_labels = None
depends_on = None

USER_ID = mysql.INTEGER(unsigned=True)
_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade():
    op.create_table(
        "ark_task_modules",
        sa.Column("key", sa.String(100), primary_key=True, comment="模块键：nav=前端路由 name；infra.* / custom.*"),
        sa.Column("kind", sa.String(10), nullable=False, comment="nav/infra/custom"),
        sa.Column("group_key", sa.String(64), nullable=False, server_default="", comment="分组键"),
        sa.Column("group_title", sa.String(64), nullable=False, server_default="", comment="分组名称"),
        sa.Column("title", sa.String(100), nullable=False, comment="模块名称"),
        sa.Column("route", sa.String(200), nullable=True, comment="前端路由 path（nav 才有）"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="组内排序"),
        sa.Column("owner_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=True, comment="私有分类所有者；公共条目为空"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true(), comment="是否有效"),
        sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="最近同步时间"),
        comment="任务中心-模块注册表（nav 条目来自构建期导出的 navigation 清单）",
    )
    op.create_table(
        "ark_task_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键；编号 T-<id>"),
        sa.Column("owner_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="所有者 ark_users.id"),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("ark_task_items.id"), nullable=True, comment="父任务"),
        sa.Column("title", sa.String(200), nullable=False, comment="标题"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("acceptance", sa.JSON(), nullable=True, comment="验收标准列表"),
        sa.Column("priority", sa.String(2), nullable=False, server_default="P2", comment="P0/P1/P2/P3"),
        sa.Column("status", sa.String(20), nullable=False, server_default="todo", comment="任务状态"),
        sa.Column("blocked_reason", sa.String(500), nullable=True, comment="受阻原因"),
        sa.Column("module_key", sa.String(100), sa.ForeignKey("ark_task_modules.key"), nullable=True, comment="关联模块"),
        sa.Column("due_date", sa.Date(), nullable=True, comment="截止日期（北京时间）"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="同级排序"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual", comment="创建来源"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="更新时间"),
        sa.Column("completed_at", sa.DateTime(), nullable=True, comment="完成时间"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删时间"),
        sa.Column("delete_batch", sa.String(32), nullable=True, comment="软删批次号：同一次删除的子树共用"),
        comment="任务中心-任务（树形，parent_id 自关联）",
    )
    op.create_index("idx_ark_task_items_owner_status", "ark_task_items", ["owner_id", "status"])
    op.create_index("idx_ark_task_items_owner_parent", "ark_task_items", ["owner_id", "parent_id"])
    op.create_table(
        "ark_task_links",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("ark_task_items.id"), nullable=False, comment="任务"),
        sa.Column("kind", sa.String(20), nullable=False, comment="doc/prototype/url"),
        sa.Column("ref", sa.String(500), nullable=False, comment="仓库路径 / URL / sha"),
        sa.Column("title", sa.String(200), nullable=False, server_default="", comment="显示名"),
        sa.Column("match", sa.String(10), nullable=False, server_default="exact", comment="exact/suggested"),
        sa.Column("state", sa.String(10), nullable=False, server_default="active", comment="active/pending/rejected"),
        sa.Column("payload_json", sa.JSON(), nullable=True, comment="附加信息"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="创建时间"),
        sa.UniqueConstraint("task_id", "kind", "ref", name="uq_ark_task_links_task_kind_ref"),
        comment="任务中心-任务关联",
    )
    op.create_table(
        "ark_task_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("ark_task_items.id"), nullable=False, comment="任务"),
        sa.Column("actor", sa.String(10), nullable=False, comment="user/ai/reporter/mcp"),
        sa.Column("type", sa.String(30), nullable=False, comment="事件类型"),
        sa.Column("payload_json", sa.JSON(), nullable=True, comment="事件详情"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="发生时间"),
        comment="任务中心-任务时间线",
    )
    op.create_index("idx_ark_task_events_task", "ark_task_events", ["task_id"])
    op.create_table(
        "ark_task_briefs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True, comment="主键"),
        sa.Column("owner_id", USER_ID, sa.ForeignKey("ark_users.id"), nullable=False, comment="所有者"),
        sa.Column("brief_date", sa.Date(), nullable=False, comment="简报日期（北京时间）"),
        sa.Column("content_json", sa.JSON(), nullable=False, comment="简报内容"),
        sa.Column("source", sa.String(10), nullable=False, comment="ai/template"),
        sa.Column("pushed_at", sa.DateTime(), nullable=True, comment="钉钉推送时间"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_NOW, comment="生成时间"),
        sa.UniqueConstraint("owner_id", "brief_date", name="uq_ark_task_briefs_owner_date"),
        comment="任务中心-每日简报",
    )


def downgrade():
    op.drop_table("ark_task_briefs")
    op.drop_index("idx_ark_task_events_task", table_name="ark_task_events")
    op.drop_table("ark_task_events")
    op.drop_table("ark_task_links")
    op.drop_index("idx_ark_task_items_owner_parent", table_name="ark_task_items")
    op.drop_index("idx_ark_task_items_owner_status", table_name="ark_task_items")
    op.drop_table("ark_task_items")
    op.drop_table("ark_task_modules")
```

- [ ] **Step 10: 离线检查迁移只有一个 head（不连库）**

Run: `$ARK_PY -m alembic heads`
Expected: 只有一行 `172_task_center (head)`。如果出现两个 head，说明有别的分支已占用 172，按「前置约束 2」顺延编号。

- [ ] **Step 11: Commit**

```bash
git add backend/app/task/__init__.py backend/app/task/models.py backend/app/task/errors.py backend/alembic/versions/172_task_center.py backend/tests/task_helpers.py backend/tests/test_task_models.py backend/tests/conftest.py
git commit -m "feat(task): add task center models and migration"
```

---

### Task 2: 模块注册表服务

**Files:**
- Create: `backend/app/task/module_service.py`、`backend/tests/test_task_modules.py`

- [ ] **Step 1: 写失败测试 `backend/tests/test_task_modules.py`**

```python
"""模块注册表：默认种子、导航清单同步、私有分类、可用性校验。"""
import pytest

from app.task import module_service
from app.task.errors import TaskInvalid
from app.task.models import TaskModule
from tests.task_helpers import make_user

MANIFEST = {
    "version": 1,
    "entries": [
        {"key": "InvoiceManage", "title": "订单发票", "group_key": "invoice", "group_title": "订单管理", "route": "/invoice", "sort": 1},
        {"key": "TaskCenter", "title": "任务中心", "group_key": "task", "group_title": "个人效率", "route": "/task", "sort": 1},
    ],
}


def test_seed_defaults_is_idempotent(db):
    module_service.seed_default_modules(db)
    module_service.seed_default_modules(db)
    keys = {m.key for m in db.query(TaskModule).all()}
    assert {"infra.backend", "infra.deploy", "infra.mini", "infra.docs", "custom.report", "custom.research", "custom.admin"} <= keys


def test_sync_manifest_upserts_and_deactivates_missing(db):
    module_service.sync_nav_manifest(db, MANIFEST)
    smaller = {"version": 1, "entries": [MANIFEST["entries"][0] | {"title": "订单发票管理"}]}
    result = module_service.sync_nav_manifest(db, smaller)
    assert result == {"upserted": 1, "deactivated": 1}
    invoice = db.get(TaskModule, "InvoiceManage")
    assert invoice.title == "订单发票管理" and invoice.is_active
    assert db.get(TaskModule, "TaskCenter").is_active is False


def test_sync_rejects_empty_manifest_and_keeps_registry(db):
    module_service.sync_nav_manifest(db, MANIFEST)
    with pytest.raises(ValueError):
        module_service.sync_nav_manifest(db, {"version": 1, "entries": []})
    assert db.get(TaskModule, "TaskCenter").is_active is True


def test_custom_module_private_to_owner(db):
    module_service.seed_default_modules(db)
    alice, bob = make_user(db, "mod_alice"), make_user(db, "mod_bob")
    key = module_service.add_custom(db, alice.id, "家里的事")
    assert key.startswith(f"custom.u{alice.id}.")
    assert key in {m["key"] for m in module_service.list_modules(db, alice.id)}
    assert key not in {m["key"] for m in module_service.list_modules(db, bob.id)}
    with pytest.raises(TaskInvalid):
        module_service.ensure_usable(db, bob.id, key)


def test_ensure_usable_rejects_inactive(db):
    module_service.sync_nav_manifest(db, MANIFEST)
    module_service.sync_nav_manifest(db, {"version": 1, "entries": [MANIFEST["entries"][0]]})
    owner = make_user(db, "mod_inactive")
    with pytest.raises(TaskInvalid):
        module_service.ensure_usable(db, owner.id, "TaskCenter")
    assert module_service.ensure_usable(db, owner.id, None) is None


def test_deactivate_custom_only_own(db):
    alice, bob = make_user(db, "mod_da"), make_user(db, "mod_db")
    key = module_service.add_custom(db, alice.id, "副业")
    with pytest.raises(TaskInvalid):
        module_service.deactivate_custom(db, bob.id, key)
    module_service.deactivate_custom(db, alice.id, key)
    assert db.get(TaskModule, key).is_active is False
```

- [ ] **Step 2: 运行确认失败**

Run: `$ARK_PY -m pytest tests/test_task_modules.py -q`
Expected: FAIL，`ImportError: cannot import name 'module_service'`

- [ ] **Step 3: 写 `backend/app/task/module_service.py`**

```python
"""任务中心模块注册表。

nav 条目的唯一来源是前端 navigation.js：构建期由 vite 插件导出 dist/nav-manifest.json，
后端启动时读取同步（见 bootstrap/seed_task.py）。浏览器不参与同步，避免多环境版本来回翻转。
"""
import json
import logging
import secrets
from pathlib import Path

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.time import beijing_now
from app.task.errors import TaskInvalid
from app.task.models import TaskModule

logger = logging.getLogger("commission")

# (key, kind, group_key, group_title, title, sort)
DEFAULT_MODULES = (
    ("infra.backend", "infra", "infra", "工程域", "后端基建", 1),
    ("infra.deploy", "infra", "infra", "工程域", "部署发布", 2),
    ("infra.mini", "infra", "infra", "工程域", "微信小程序", 3),
    ("infra.docs", "infra", "infra", "工程域", "文档与规范", 4),
    ("custom.report", "custom", "custom", "方舟外", "汇报材料", 1),
    ("custom.research", "custom", "custom", "方舟外", "调研", 2),
    ("custom.admin", "custom", "custom", "方舟外", "部门行政", 3),
)
_KIND_ORDER = {"nav": 0, "infra": 1, "custom": 2}


def seed_default_modules(db: Session) -> None:
    for key, kind, group_key, group_title, title, sort in DEFAULT_MODULES:
        row = db.get(TaskModule, key)
        if row is None:
            db.add(TaskModule(key=key, kind=kind, group_key=group_key, group_title=group_title,
                              title=title, sort_order=sort, is_active=True))
    db.flush()


def load_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def sync_nav_manifest(db: Session, manifest: dict) -> dict:
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if not entries:
        raise ValueError("导航清单为空，保留现有模块注册表")
    now = beijing_now()
    seen = set()
    for entry in entries:
        key = str(entry["key"])[:100]
        seen.add(key)
        row = db.get(TaskModule, key)
        if row is None:
            row = TaskModule(key=key, kind="nav")
            db.add(row)
        row.kind = "nav"
        row.title = str(entry.get("title") or key)[:100]
        row.group_key = str(entry.get("group_key") or "")[:64]
        row.group_title = str(entry.get("group_title") or "")[:64]
        row.route = entry.get("route")
        row.sort_order = int(entry.get("sort") or 0)
        row.is_active = True
        row.synced_at = now
    stale = db.query(TaskModule).filter(TaskModule.kind == "nav", TaskModule.is_active.is_(True),
                                        TaskModule.key.notin_(seen)).all()
    for row in stale:
        row.is_active = False
        row.synced_at = now
    db.flush()
    return {"upserted": len(seen), "deactivated": len(stale)}


def _visible_query(db: Session, owner_id: int):
    return db.query(TaskModule).filter(or_(TaskModule.owner_id.is_(None), TaskModule.owner_id == owner_id))


def serialize_module(row: TaskModule) -> dict:
    return {"key": row.key, "kind": row.kind, "group_key": row.group_key, "group_title": row.group_title,
            "title": row.title, "route": row.route, "is_active": row.is_active, "is_private": row.owner_id is not None}


def list_modules(db: Session, owner_id: int, include_inactive: bool = False) -> list[dict]:
    q = _visible_query(db, owner_id)
    if not include_inactive:
        q = q.filter(TaskModule.is_active.is_(True))
    # nav 的 sort_order 由清单编码为「分组序号*1000 + 组内序号」，因此直接按 sort_order 排序即可保持导航顺序
    rows = sorted(q.all(), key=lambda m: (_KIND_ORDER.get(m.kind, 9), m.sort_order, m.key))
    return [serialize_module(r) for r in rows]


def ensure_usable(db: Session, owner_id: int, key: str | None) -> str | None:
    """新建/改关联时校验模块可用；None 表示不关联模块。已停用模块不允许新关联。"""
    if key is None:
        return None
    row = db.get(TaskModule, key)
    if row is None or not row.is_active or (row.owner_id is not None and row.owner_id != owner_id):
        raise TaskInvalid("关联的模块不存在或已停用")
    return key


def add_custom(db: Session, owner_id: int, title: str) -> str:
    title = (title or "").strip()
    if not title or len(title) > 100:
        raise TaskInvalid("分类名称需为 1~100 个字")
    key = f"custom.u{owner_id}.{secrets.token_hex(4)}"
    db.add(TaskModule(key=key, kind="custom", group_key="custom", group_title="方舟外", title=title,
                      sort_order=100, owner_id=owner_id, is_active=True))
    db.flush()
    return key


def deactivate_custom(db: Session, owner_id: int, key: str) -> None:
    row = db.get(TaskModule, key)
    if row is None or row.owner_id != owner_id:
        raise TaskInvalid("只能停用自己新建的分类")
    row.is_active = False
    db.flush()
```

- [ ] **Step 4: 运行确认通过**

Run: `$ARK_PY -m pytest tests/test_task_modules.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/task/module_service.py backend/tests/test_task_modules.py
git commit -m "feat(task): add module registry with manifest sync"
```

---

### Task 3: 任务服务——创建、更新、树规则

**Files:**
- Create: `backend/app/task/service.py`、`backend/tests/test_task_service.py`

- [ ] **Step 1: 写失败测试 `backend/tests/test_task_service.py`（本 task 只覆盖创建、更新、树规则部分）**

```python
"""任务服务：创建/更新/树规则/隔离。状态机与回收站见 test_task_state.py。"""
import pytest

from app.task import module_service, service
from app.task.errors import TaskInvalid, TaskNotFound
from app.task.models import TaskEvent
from tests.task_helpers import make_user


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    return make_user(db, "svc_owner")


def chain(db, owner_id, depth):
    """建一条深度为 depth 的父子链，返回自顶向下的任务列表。"""
    tasks, parent = [], None
    for i in range(depth):
        t = service.create_task(db, owner_id, title=f"L{i + 1}", parent_id=parent)
        tasks.append(t)
        parent = t.id
    return tasks


def test_create_defaults_and_event(db, owner):
    t = service.create_task(db, owner.id, title="  写汇报  ", module_key="custom.report", source="nav_quick")
    assert t.title == "写汇报" and t.priority == "P2" and t.status == "todo" and t.source == "nav_quick"
    ev = db.query(TaskEvent).filter_by(task_id=t.id).one()
    assert ev.type == "created" and ev.actor == "user"


@pytest.mark.parametrize("bad", [{"title": ""}, {"title": "x" * 201}, {"title": "ok", "priority": "P9"},
                                 {"title": "ok", "module_key": "nope"}, {"title": "ok", "source": "hack"}])
def test_create_validation(db, owner, bad):
    with pytest.raises(TaskInvalid):
        service.create_task(db, owner.id, **bad)


def test_acceptance_is_cleaned(db, owner):
    t = service.create_task(db, owner.id, title="t", acceptance=["  a  ", "", "b", *["c"] * 10])
    assert t.acceptance == ["a", "b", "c", "c", "c", "c", "c", "c"]


def test_depth_limit_four(db, owner):
    tasks = chain(db, owner.id, 4)
    with pytest.raises(TaskInvalid, match="4 层"):
        service.create_task(db, owner.id, title="L5", parent_id=tasks[-1].id)


def test_parent_must_belong_to_owner(db, owner):
    other = make_user(db, "svc_other")
    foreign = service.create_task(db, other.id, title="别人的")
    with pytest.raises(TaskNotFound):
        service.create_task(db, owner.id, title="挂到别人下面", parent_id=foreign.id)


def test_get_task_isolated(db, owner):
    other = make_user(db, "svc_iso")
    t = service.create_task(db, owner.id, title="mine")
    with pytest.raises(TaskNotFound):
        service.get_task(db, other.id, t.id)


def test_update_whitelist_and_event(db, owner):
    t = service.create_task(db, owner.id, title="old")
    service.update_task(db, owner.id, t.id, {"title": "new", "priority": "P0", "due_date": "2026-10-01"})
    assert t.title == "new" and t.priority == "P0" and str(t.due_date) == "2026-10-01"
    with pytest.raises(TaskInvalid):
        service.update_task(db, owner.id, t.id, {"status": "done"})
    ev = db.query(TaskEvent).filter_by(task_id=t.id, type="updated").one()
    assert set(ev.payload_json["fields"]) == {"title", "priority", "due_date"}


def test_move_rejects_cycle_and_depth(db, owner):
    a, b, c = chain(db, owner.id, 3)
    with pytest.raises(TaskInvalid, match="子任务"):
        service.move_task(db, owner.id, a.id, c.id)
    with pytest.raises(TaskInvalid, match="子任务"):
        service.move_task(db, owner.id, a.id, a.id)
    d1, d2 = chain(db, owner.id, 2)
    with pytest.raises(TaskInvalid, match="4 层"):
        service.move_task(db, owner.id, a.id, d2.id)   # a 子树高 3 + d2 深度 2 = 5
    service.move_task(db, owner.id, c.id, None)
    assert c.parent_id is None


def test_list_tree_progress_counts_closed_leaves(db, owner):
    root = service.create_task(db, owner.id, title="root")
    k1 = service.create_task(db, owner.id, title="k1", parent_id=root.id)
    service.create_task(db, owner.id, title="k2", parent_id=root.id)
    service.create_task(db, owner.id, title="g1", parent_id=k1.id)
    done = service.create_task(db, owner.id, title="g2", parent_id=k1.id)
    service.change_status(db, owner.id, done.id, "done")
    tree = service.list_tree(db, owner.id)
    node = next(n for n in tree if n["id"] == root.id)
    assert node["progress"] == {"done": 1, "total": 3}
    assert [c["title"] for c in node["children"]] == ["k1", "k2"]
    assert node["code"] == f"T-{root.id}"
```

- [ ] **Step 2: 运行确认失败**

Run: `$ARK_PY -m pytest tests/test_task_service.py -q`
Expected: FAIL，`ImportError: cannot import name 'service'`

- [ ] **Step 3: 写 `backend/app/task/service.py`**

```python
"""任务中心核心服务：CRUD、树规则、状态机、回收站、统计。

个人任务规模有限（千级），树操作一次载入 owner 全部未删除任务在内存计算，
比递归 SQL 简单可靠；所有查询都带 owner_id，跨 owner 一律视为不存在（404）。
"""
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today
from app.task import module_service
from app.task.errors import TaskConflict, TaskInvalid, TaskNotFound
from app.task.models import (
    CLOSED_STATUSES, MAX_DEPTH, OPEN_STATUSES, PRIORITIES, SOURCES, STATUS_LABELS, STATUSES,
    TaskEvent, TaskItem, TaskLink, LINK_KINDS,
)

EDITABLE_FIELDS = ("title", "description", "acceptance", "priority", "module_key", "due_date")
MAX_ACCEPTANCE = 8


# ── 基础 ────────────────────────────────────────────────────────────────

def _event(db: Session, task_id: int, type_: str, payload: dict | None = None, actor: str = "user") -> None:
    db.add(TaskEvent(task_id=task_id, actor=actor, type=type_, payload_json=payload or {}))


def get_task(db: Session, owner_id: int, task_id: int, include_deleted: bool = False) -> TaskItem:
    q = db.query(TaskItem).filter(TaskItem.id == task_id, TaskItem.owner_id == owner_id)
    if not include_deleted:
        q = q.filter(TaskItem.deleted_at.is_(None))
    task = q.first()
    if task is None:
        raise TaskNotFound("任务不存在")
    return task


def _owner_tasks(db: Session, owner_id: int) -> dict[int, TaskItem]:
    rows = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.is_(None)).all()
    return {t.id: t for t in rows}


def _children_map(tasks: dict[int, TaskItem]) -> dict[int | None, list[TaskItem]]:
    result: dict[int | None, list[TaskItem]] = {}
    for t in tasks.values():
        result.setdefault(t.parent_id, []).append(t)
    for siblings in result.values():
        siblings.sort(key=lambda x: (x.sort_order, x.id))
    return result


def _depth(tasks: dict[int, TaskItem], task_id: int | None) -> int:
    """task_id 所在层级（顶层=1）；None 表示根之上，返回 0。"""
    depth, current = 0, task_id
    while current is not None:
        depth += 1
        current = tasks[current].parent_id if current in tasks else None
    return depth


def _descendant_ids(children: dict, task_id: int) -> list[int]:
    out, stack = [], [task_id]
    while stack:
        for child in children.get(stack.pop(), []):
            out.append(child.id)
            stack.append(child.id)
    return out


def _subtree_height(children: dict, task_id: int) -> int:
    kids = children.get(task_id, [])
    return 1 + max((_subtree_height(children, k.id) for k in kids), default=0)


def _clean_title(title) -> str:
    title = (title or "").strip()
    if not title or len(title) > 200:
        raise TaskInvalid("标题需为 1~200 个字")
    return title


def _clean_acceptance(items) -> list[str] | None:
    if items is None:
        return None
    if not isinstance(items, list):
        raise TaskInvalid("验收标准需为列表")
    cleaned = [str(x).strip()[:200] for x in items if str(x).strip()]
    return cleaned[:MAX_ACCEPTANCE]


def _clean_priority(priority) -> str:
    if priority not in PRIORITIES:
        raise TaskInvalid("重要性只能是 P0~P3")
    return priority


def _clean_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise TaskInvalid("日期格式应为 YYYY-MM-DD") from exc


# ── 创建 / 更新 / 移动 ─────────────────────────────────────────────────

def create_task(db: Session, owner_id: int, *, title, description=None, acceptance=None, priority="P2",
                module_key=None, parent_id=None, due_date=None, source="manual") -> TaskItem:
    if source not in SOURCES:
        raise TaskInvalid("未知的创建来源")
    title = _clean_title(title)
    priority = _clean_priority(priority)
    module_key = module_service.ensure_usable(db, owner_id, module_key)
    tasks = _owner_tasks(db, owner_id)
    if parent_id is not None:
        get_task(db, owner_id, parent_id)
        if _depth(tasks, parent_id) + 1 > MAX_DEPTH:
            raise TaskInvalid(f"任务最多 {MAX_DEPTH} 层，不能再往下加子任务")
    siblings = [t for t in tasks.values() if t.parent_id == parent_id]
    task = TaskItem(
        owner_id=owner_id, parent_id=parent_id, title=title, description=description,
        acceptance=_clean_acceptance(acceptance), priority=priority, module_key=module_key,
        due_date=_clean_date(due_date), source=source,
        sort_order=max((t.sort_order for t in siblings), default=0) + 1,
    )
    db.add(task)
    db.flush()
    _event(db, task.id, "created", {"source": source})
    db.flush()
    return task


def update_task(db: Session, owner_id: int, task_id: int, changes: dict) -> TaskItem:
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise TaskInvalid(f"不能直接修改字段：{', '.join(sorted(unknown))}")
    task = get_task(db, owner_id, task_id)
    for field, value in changes.items():
        if field == "title":
            value = _clean_title(value)
        elif field == "acceptance":
            value = _clean_acceptance(value)
        elif field == "priority":
            value = _clean_priority(value)
        elif field == "module_key":
            value = module_service.ensure_usable(db, owner_id, value)
        elif field == "due_date":
            value = _clean_date(value)
        setattr(task, field, value)
    if changes:
        _event(db, task.id, "updated", {"fields": sorted(changes)})
    db.flush()
    return task


def move_task(db: Session, owner_id: int, task_id: int, new_parent_id: int | None) -> TaskItem:
    task = get_task(db, owner_id, task_id)
    tasks = _owner_tasks(db, owner_id)
    children = _children_map(tasks)
    if new_parent_id is not None:
        get_task(db, owner_id, new_parent_id)
        if new_parent_id == task_id or new_parent_id in _descendant_ids(children, task_id):
            raise TaskInvalid("不能把任务移动到它自己或它的子任务下面")
        if _depth(tasks, new_parent_id) + _subtree_height(children, task_id) > MAX_DEPTH:
            raise TaskInvalid(f"移动后会超过 {MAX_DEPTH} 层")
    old_parent = task.parent_id
    task.parent_id = new_parent_id
    siblings = children.get(new_parent_id, [])
    task.sort_order = max((t.sort_order for t in siblings), default=0) + 1
    _event(db, task.id, "moved", {"from": old_parent, "to": new_parent_id})
    db.flush()
    return task


# ── 序列化 / 树 ────────────────────────────────────────────────────────

def serialize_task(task: TaskItem) -> dict:
    return {
        "id": task.id, "code": task.code, "parent_id": task.parent_id, "title": task.title,
        "description": task.description, "acceptance": task.acceptance or [],
        "priority": task.priority, "status": task.status, "blocked_reason": task.blocked_reason,
        "module_key": task.module_key, "due_date": task.due_date.isoformat() if task.due_date else None,
        "source": task.source, "sort_order": task.sort_order,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


def _leaf_progress(children: dict, task: TaskItem) -> tuple[int, int]:
    kids = children.get(task.id, [])
    if not kids:
        return (1 if task.status in CLOSED_STATUSES else 0, 1)
    done = total = 0
    for k in kids:
        d, t = _leaf_progress(children, k)
        done, total = done + d, total + t
    return done, total


def list_tree(db: Session, owner_id: int) -> list[dict]:
    tasks = _owner_tasks(db, owner_id)
    children = _children_map(tasks)

    def build(task: TaskItem) -> dict:
        node = serialize_task(task)
        kids = children.get(task.id, [])
        node["children"] = [build(k) for k in kids]
        if kids:
            done, total = _leaf_progress(children, task)
            node["progress"] = {"done": done, "total": total}
        return node

    return [build(t) for t in children.get(None, [])]
```

注：`change_status` 在 Task 4 实现。本 task 的最后一个测试会用到它，所以先在 service.py 末尾追加 Task 4 Step 3 的代码，再跑测试。执行时可以把 Task 3 和 Task 4 合并成一次提交；也可以先把该测试标记 `@pytest.mark.skip` 跑通其余用例，到 Task 4 再取消 skip。**推荐合并执行**。

- [ ] **Step 4: 进入 Task 4 完成状态机后一起运行（见 Task 4 Step 4）**

---

### Task 4: 状态机、回收站、关联、统计

**Files:**
- Modify: `backend/app/task/service.py`（追加）
- Create: `backend/tests/test_task_state.py`

- [ ] **Step 1: 写失败测试 `backend/tests/test_task_state.py`**

```python
"""状态迁移矩阵、子任务未结束确认、回收站、关联、统计（含北京时间跨日）。"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.task import module_service, service
from app.task.errors import TaskConflict, TaskInvalid, TaskNotFound
from app.task.models import TaskEvent, TaskItem
from tests.task_helpers import make_user


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    return make_user(db, "state_owner")


@pytest.mark.parametrize("frm,to,ok", [
    ("todo", "in_progress", True), ("in_progress", "blocked", True), ("blocked", "todo", True),
    ("todo", "done", True), ("todo", "shelved", True),
    ("todo", "pending_confirm", False),          # 待确认只能由 AI/MCP 提议
    ("pending_confirm", "done", True), ("pending_confirm", "in_progress", True),
    ("done", "todo", True), ("done", "in_progress", False), ("shelved", "done", False),
])
def test_user_transition_matrix(frm, to, ok):
    assert service.can_transition("user", frm, to) is ok


def test_ai_can_only_propose():
    assert service.can_transition("ai", "in_progress", "pending_confirm") is True
    assert service.can_transition("ai", "pending_confirm", "done") is False
    assert service.can_transition("reporter", "todo", "done") is False


def test_blocked_requires_reason_and_clears_on_leave(db, owner):
    t = service.create_task(db, owner.id, title="t")
    with pytest.raises(TaskInvalid, match="原因"):
        service.change_status(db, owner.id, t.id, "blocked")
    service.change_status(db, owner.id, t.id, "blocked", reason="等财务口径")
    assert t.blocked_reason == "等财务口径"
    service.change_status(db, owner.id, t.id, "in_progress")
    assert t.blocked_reason is None


def test_user_cannot_set_pending_confirm(db, owner):
    t = service.create_task(db, owner.id, title="t")
    with pytest.raises(TaskConflict):
        service.change_status(db, owner.id, t.id, "pending_confirm")


def test_done_with_open_children_needs_confirmation(db, owner):
    parent = service.create_task(db, owner.id, title="p")
    service.create_task(db, owner.id, title="c", parent_id=parent.id)
    with pytest.raises(TaskConflict) as exc:
        service.change_status(db, owner.id, parent.id, "done")
    assert exc.value.code == "open_children" and exc.value.extra == {"open_children": 1}
    service.change_status(db, owner.id, parent.id, "done", confirm_open_children=True)
    assert parent.status == "done" and parent.completed_at is not None


def test_reopen_clears_completed_at_and_logs(db, owner):
    t = service.create_task(db, owner.id, title="t")
    service.change_status(db, owner.id, t.id, "done")
    service.change_status(db, owner.id, t.id, "todo")
    assert t.completed_at is None
    ev = db.query(TaskEvent).filter_by(task_id=t.id, type="status_changed").order_by(TaskEvent.id.desc()).first()
    assert ev.payload_json == {"from": "done", "to": "todo", "reason": None}


def test_soft_delete_subtree_and_restore(db, owner):
    root = service.create_task(db, owner.id, title="root")
    kid = service.create_task(db, owner.id, title="kid", parent_id=root.id)
    service.delete_task(db, owner.id, root.id)
    assert root.deleted_at is not None and kid.delete_batch == root.delete_batch
    with pytest.raises(TaskNotFound):
        service.get_task(db, owner.id, kid.id)
    assert [t["id"] for t in service.list_trash(db, owner.id)] == [root.id]
    service.restore_task(db, owner.id, root.id)
    assert root.deleted_at is None and kid.deleted_at is None


def test_restore_child_whose_parent_is_deleted_becomes_top_level(db, owner):
    root = service.create_task(db, owner.id, title="root")
    kid = service.create_task(db, owner.id, title="kid", parent_id=root.id)
    service.delete_task(db, owner.id, kid.id)
    service.delete_task(db, owner.id, root.id)
    service.restore_task(db, owner.id, kid.id)
    assert kid.parent_id is None and kid.deleted_at is None


def test_links_add_remove_and_dedupe(db, owner):
    t = service.create_task(db, owner.id, title="t")
    link = service.add_link(db, owner.id, t.id, kind="doc", ref="docs/a.md", title="设计")
    with pytest.raises(TaskConflict):
        service.add_link(db, owner.id, t.id, kind="doc", ref="docs/a.md", title="设计")
    with pytest.raises(TaskInvalid):
        service.add_link(db, owner.id, t.id, kind="branch", ref="x", title="")
    with pytest.raises(TaskInvalid):
        service.add_link(db, owner.id, t.id, kind="doc", ref="../secret.md", title="")
    service.remove_link(db, owner.id, link.id)
    assert service.task_detail(db, owner.id, t.id)["links"] == []


def test_stats_uses_beijing_date(db, owner):
    t = service.create_task(db, owner.id, title="逾期", due_date="2026-09-29", priority="P0")
    service.create_task(db, owner.id, title="today", due_date="2026-09-30")
    s = service.stats(db, owner.id, today=date(2026, 9, 30))
    assert s == {"in_progress": 0, "pending_confirm": 0, "p0_open": 1, "overdue": 1}
    service.change_status(db, owner.id, t.id, "done")
    assert service.stats(db, owner.id, today=date(2026, 9, 30))["overdue"] == 0


class _LosAngelesClock(datetime):
    """模拟服务器在 UTC-7：UTC 2026-09-29 16:30 = 北京 09-30 00:30 = 洛杉矶 09-29 09:30。"""
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 9, 29, 16, 30, tzinfo=timezone.utc)
        return base.astimezone(tz) if tz else (base - timedelta(hours=7)).replace(tzinfo=None)


def test_stats_default_today_crosses_midnight_on_non_beijing_server(db, owner, monkeypatch):
    monkeypatch.setattr("app.core.time.datetime", _LosAngelesClock)
    service.create_task(db, owner.id, title="昨天到期", due_date="2026-09-29")
    assert service.stats(db, owner.id)["overdue"] == 1   # 北京已是 09-30，09-29 到期即逾期
```

- [ ] **Step 2: 运行确认失败**

Run: `$ARK_PY -m pytest tests/test_task_state.py -q`
Expected: FAIL，`AttributeError: module 'app.task.service' has no attribute 'can_transition'`

- [ ] **Step 3: 在 `backend/app/task/service.py` 末尾追加**

```python
# ── 状态机 ─────────────────────────────────────────────────────────────
# 迁移矩阵见设计文档第 3 节。done 只有 user 可写；ai/mcp 只能提议 pending_confirm（二期起用）。

_OPEN = set(OPEN_STATUSES)


def can_transition(actor: str, frm: str, to: str) -> bool:
    if frm == to:
        return False
    if actor == "user":
        if frm in _OPEN:
            return to in _OPEN | {"done", "shelved"}
        if frm == "pending_confirm":
            return to in _OPEN | {"done", "shelved"}
        if frm in CLOSED_STATUSES:
            return to == "todo"
        return False
    if actor in ("ai", "mcp"):
        return frm in _OPEN and to == "pending_confirm"
    return False


def change_status(db: Session, owner_id: int, task_id: int, to: str, *, actor: str = "user",
                  reason: str | None = None, confirm_open_children: bool = False) -> TaskItem:
    if to not in STATUSES:
        raise TaskInvalid("未知状态")
    task = get_task(db, owner_id, task_id)
    frm = task.status
    if not can_transition(actor, frm, to):
        raise TaskConflict(f"不能从「{STATUS_LABELS[frm]}」改为「{STATUS_LABELS[to]}」", code="transition")
    reason = (reason or "").strip() or None
    if to == "blocked" and not reason:
        raise TaskInvalid("标记受阻需要填写原因")
    if to == "done" and not confirm_open_children:
        tasks = _owner_tasks(db, owner_id)
        open_count = sum(1 for i in _descendant_ids(_children_map(tasks), task.id)
                         if tasks[i].status not in CLOSED_STATUSES)
        if open_count:
            raise TaskConflict(f"还有 {open_count} 个子任务没结束", code="open_children",
                               extra={"open_children": open_count})
    task.status = to
    task.blocked_reason = reason if to == "blocked" else None
    task.completed_at = beijing_now() if to == "done" else None
    _event(db, task.id, "status_changed", {"from": frm, "to": to, "reason": reason}, actor=actor)
    db.flush()
    return task


# ── 回收站 ─────────────────────────────────────────────────────────────

def delete_task(db: Session, owner_id: int, task_id: int) -> None:
    task = get_task(db, owner_id, task_id)
    children = _children_map(_owner_tasks(db, owner_id))
    stamp, batch = beijing_now(), uuid.uuid4().hex
    ids = [task.id, *_descendant_ids(children, task.id)]
    db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.id.in_(ids)).update(
        {TaskItem.deleted_at: stamp, TaskItem.delete_batch: batch}, synchronize_session="fetch")
    _event(db, task.id, "deleted", {"count": len(ids)})
    db.flush()


def list_trash(db: Session, owner_id: int) -> list[dict]:
    rows = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.isnot(None)).all()
    by_id = {t.id: t for t in rows}
    roots = [t for t in rows if t.parent_id not in by_id or by_id[t.parent_id].delete_batch != t.delete_batch]
    roots.sort(key=lambda t: (t.deleted_at, t.id), reverse=True)
    return [serialize_task(t) | {"deleted_at": t.deleted_at.isoformat()} for t in roots]


def restore_task(db: Session, owner_id: int, task_id: int) -> TaskItem:
    task = get_task(db, owner_id, task_id, include_deleted=True)
    if task.deleted_at is None:
        raise TaskConflict("任务没有被删除")
    batch = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.delete_batch == task.delete_batch).all()
    children: dict = {}
    for t in batch:
        children.setdefault(t.parent_id, []).append(t)
    ids = {task.id, *_descendant_ids(children, task.id)}
    if task.parent_id is not None:
        parent = db.query(TaskItem).filter(TaskItem.id == task.parent_id).first()
        if parent is None or parent.deleted_at is not None:
            task.parent_id = None
    for t in batch:
        if t.id in ids:
            t.deleted_at = None
            t.delete_batch = None
    _event(db, task.id, "restored", {"count": len(ids)})
    db.flush()
    return task


# ── 关联 ───────────────────────────────────────────────────────────────

def _clean_ref(kind: str, ref: str) -> str:
    ref = (ref or "").strip().replace("\\", "/")
    if not ref or len(ref) > 500:
        raise TaskInvalid("关联地址需为 1~500 个字符")
    if kind == "url":
        if not ref.startswith(("https://", "http://")):
            raise TaskInvalid("链接需以 http:// 或 https:// 开头")
    elif ".." in ref.split("/") or ref.startswith("/"):
        raise TaskInvalid("仓库路径需为 docs/ 等相对路径，不能包含 ..")
    return ref


def add_link(db: Session, owner_id: int, task_id: int, *, kind: str, ref: str, title: str = "") -> TaskLink:
    if kind not in LINK_KINDS:
        raise TaskInvalid("一期只支持挂文档、原型或链接")
    task = get_task(db, owner_id, task_id)
    ref = _clean_ref(kind, ref)
    exists = db.query(TaskLink).filter_by(task_id=task.id, kind=kind, ref=ref).first()
    if exists:
        raise TaskConflict("这条关联已经存在")
    link = TaskLink(task_id=task.id, kind=kind, ref=ref, title=(title or "").strip()[:200] or ref.rsplit("/", 1)[-1])
    db.add(link)
    db.flush()
    _event(db, task.id, "linked", {"kind": kind, "ref": ref})
    db.flush()
    return link


def remove_link(db: Session, owner_id: int, link_id: int) -> None:
    link = db.query(TaskLink).filter(TaskLink.id == link_id).first()
    if link is None:
        raise TaskNotFound("关联不存在")
    get_task(db, owner_id, link.task_id)
    _event(db, link.task_id, "unlinked", {"kind": link.kind, "ref": link.ref})
    db.delete(link)
    db.flush()


def serialize_link(link: TaskLink) -> dict:
    return {"id": link.id, "kind": link.kind, "ref": link.ref, "title": link.title,
            "match": link.match, "state": link.state}


def task_detail(db: Session, owner_id: int, task_id: int) -> dict:
    task = get_task(db, owner_id, task_id)
    tasks = _owner_tasks(db, owner_id)
    children = _children_map(tasks)
    path, cur = [], task.parent_id
    while cur is not None and cur in tasks:
        path.insert(0, {"id": cur, "code": tasks[cur].code, "title": tasks[cur].title})
        cur = tasks[cur].parent_id
    links = db.query(TaskLink).filter(TaskLink.task_id == task.id).order_by(TaskLink.id).all()
    events = (db.query(TaskEvent).filter(TaskEvent.task_id == task.id)
              .order_by(TaskEvent.id.desc()).limit(50).all())
    detail = serialize_task(task)
    detail.update({
        "path": path,
        "children": [serialize_task(c) for c in children.get(task.id, [])],
        "links": [serialize_link(l) for l in links],
        "events": [{"id": e.id, "actor": e.actor, "type": e.type, "payload": e.payload_json or {},
                    "created_at": e.created_at.isoformat()} for e in events],
    })
    if children.get(task.id):
        done, total = _leaf_progress(children, task)
        detail["progress"] = {"done": done, "total": total}
    return detail


# ── 统计 ───────────────────────────────────────────────────────────────

def stats(db: Session, owner_id: int, today: date | None = None) -> dict:
    today = today or beijing_today()
    tasks = [t for t in _owner_tasks(db, owner_id).values() if t.status not in CLOSED_STATUSES]
    return {
        "in_progress": sum(1 for t in tasks if t.status == "in_progress"),
        "pending_confirm": sum(1 for t in tasks if t.status == "pending_confirm"),
        "p0_open": sum(1 for t in tasks if t.priority == "P0"),
        "overdue": sum(1 for t in tasks if t.due_date and t.due_date < today),
    }
```

回收站按 `delete_batch`（每次删除生成一个 uuid 批次号）识别「同一批删除的子树」，不依赖时间戳：Windows 上 `datetime.now()` 精度约 15ms，同一秒甚至同一毫秒内先删子、再删父的两次操作，时间戳可能相同。

- [ ] **Step 4: 运行 Task 3 与 Task 4 的全部测试**

Run: `$ARK_PY -m pytest tests/test_task_service.py tests/test_task_state.py -q`
Expected: 全部 passed（约 30 个用例）

- [ ] **Step 5: Commit**

```bash
git add backend/app/task/service.py backend/tests/test_task_service.py backend/tests/test_task_state.py
git commit -m "feat(task): add task tree service and status state machine"
```

---

### Task 5: 一句话建任务（AI 草稿）

**Files:**
- Create: `backend/app/task/ai_service.py`、`backend/tests/test_task_ai.py`

设计要点：值域（模块、优先级、候选父任务 / 重复任务）一律在运行时注入 user message，system prompt 只描述输出格式（宪法第 7 条）。AI 返回的每个字段都在服务端校验，不合法的回落到预填值；调用失败时整体降级，直接用原文作标题。

- [ ] **Step 1: 写失败测试 `backend/tests/test_task_ai.py`**

```python
"""AI 草稿：值域运行时注入、输出逐字段校验、失败降级。"""
import json
from datetime import date

import pytest

from app.task import ai_service, module_service, service
from tests.task_helpers import make_user


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    module_service.sync_nav_manifest(db, {"version": 1, "entries": [
        {"key": "ReceiptList", "title": "回款管理", "group_key": "invoice", "group_title": "订单管理", "route": "/receipts", "sort": 2},
    ]})
    return make_user(db, "ai_owner")


def fake_chat(payload, calls):
    def _chat(**kwargs):
        calls.append(kwargs)
        return {"content": "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"}
    return _chat


def test_draft_injects_domain_and_validates(db, owner, monkeypatch):
    parent = service.create_task(db, owner.id, title="回款管理：生产验证收尾", module_key="ReceiptList")
    calls = []
    monkeypatch.setattr("app.ai.service.chat", fake_chat({
        "title": "回款列表按业务员筛选提速", "priority": "P1", "acceptance": ["P95 < 1s", "走索引"],
        "module_key": "ReceiptList", "parent_id": parent.id, "duplicate_ids": [parent.id, 99999],
        "due_date": "2026-10-01",
    }, calls))
    draft = ai_service.draft_task(db, owner.id, "回款列表按业务员筛选很慢，明天搞定",
                                  module_key="ReceiptList", today=date(2026, 9, 30))
    user_msg = json.loads(calls[0]["messages"][0]["content"])
    assert calls[0]["preset_name"] == "task_draft" and calls[0]["caller_module"] == "task"
    assert {m["key"] for m in user_msg["modules"]} >= {"ReceiptList", "custom.report"}
    assert user_msg["priorities"] == {"P0": "紧急", "P1": "高", "P2": "中", "P3": "低"}
    assert user_msg["today"] == "2026-09-30"
    assert draft["title"] == "回款列表按业务员筛选提速" and draft["priority"] == "P1"
    assert draft["parent_id"] == parent.id and draft["due_date"] == "2026-10-01"
    assert [d["id"] for d in draft["duplicates"]] == [parent.id]   # 不存在的 id 被丢弃
    assert draft["degraded"] is False


def test_draft_rejects_out_of_domain_values(db, owner, monkeypatch):
    other = make_user(db, "ai_other")
    foreign = service.create_task(db, other.id, title="别人的")
    monkeypatch.setattr("app.ai.service.chat", fake_chat({
        "title": "", "priority": "P7", "acceptance": "not-a-list", "module_key": "Hacked",
        "parent_id": foreign.id, "duplicate_ids": [foreign.id], "due_date": "明天",
    }, []))
    draft = ai_service.draft_task(db, owner.id, "随便写一句", module_key="ReceiptList")
    assert draft["title"] == "随便写一句" and draft["priority"] == "P2" and draft["acceptance"] == []
    assert draft["module_key"] == "ReceiptList" and draft["parent_id"] is None
    assert draft["duplicates"] == [] and draft["due_date"] is None


def test_draft_degrades_on_ai_failure(db, owner, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr("app.ai.service.chat", boom)
    draft = ai_service.draft_task(db, owner.id, "  写四季度汇报  ", module_key="custom.report")
    assert draft["degraded"] is True and draft["title"] == "写四季度汇报"
    assert draft["module_key"] == "custom.report" and "AI 暂不可用" in draft["notice"]


def test_draft_rejects_empty_text(db, owner):
    from app.task.errors import TaskInvalid
    with pytest.raises(TaskInvalid):
        ai_service.draft_task(db, owner.id, "   ")
```

- [ ] **Step 2: 运行确认失败**

Run: `$ARK_PY -m pytest tests/test_task_ai.py -q`
Expected: FAIL，`ImportError: cannot import name 'ai_service'`

- [ ] **Step 3: 写 `backend/app/task/ai_service.py`**

```python
"""一句话建任务：AI 生成草稿，用户确认后才写库。

值域全部运行时注入 user message（模块来自 ark_task_modules，优先级来自代码常量，
候选父任务/重复任务来自该 owner 的未结束任务）；preset 的 system prompt 只描述输出格式。
AI 输出逐字段校验，越界值回落到预填值；调用失败整体降级为原文标题。
"""
import json
import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from app.core.time import beijing_today
from app.task import module_service
from app.task.errors import TaskInvalid
from app.task.models import CLOSED_STATUSES, PRIORITIES, PRIORITY_LABELS, TaskItem

logger = logging.getLogger("commission")

DRAFT_PRESET = "task_draft"
MAX_TEXT = 1000
MAX_CANDIDATES = 30


def parse_json(content: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (content or "").strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("AI 返回内容不是 JSON")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("AI 返回内容不是 JSON 对象")
    return data


def _open_candidates(db: Session, owner_id: int, module_key: str | None) -> list[TaskItem]:
    q = db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.is_(None),
                                  TaskItem.status.notin_(CLOSED_STATUSES))
    if module_key:
        q = q.filter(TaskItem.module_key == module_key)
    return q.order_by(TaskItem.updated_at.desc()).limit(MAX_CANDIDATES).all()


def _fallback(text: str, module_key, parent_id, notice: str) -> dict:
    return {"title": text[:200], "priority": "P2", "acceptance": [], "module_key": module_key,
            "parent_id": parent_id, "due_date": None, "duplicates": [], "degraded": True, "notice": notice}


def draft_task(db: Session, owner_id: int, text: str, *, module_key: str | None = None,
               parent_id: int | None = None, today: date | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise TaskInvalid("先写一句话说明要做什么")
    text = text[:MAX_TEXT]
    today = today or beijing_today()
    module_key = module_service.ensure_usable(db, owner_id, module_key)
    modules = module_service.list_modules(db, owner_id)
    candidates = _open_candidates(db, owner_id, module_key)
    candidate_ids = {t.id for t in candidates}
    if parent_id is not None and parent_id not in candidate_ids:
        parent = db.query(TaskItem).filter(TaskItem.id == parent_id, TaskItem.owner_id == owner_id,
                                           TaskItem.deleted_at.is_(None)).first()
        if parent is None:
            parent_id = None
        else:
            candidates.append(parent)
            candidate_ids.add(parent.id)

    user_payload = {
        "text": text,
        "today": today.isoformat(),
        "preset_module": module_key,
        "preset_parent_id": parent_id,
        "modules": [{"key": m["key"], "title": m["title"], "group": m["group_title"]} for m in modules],
        "priorities": dict(PRIORITY_LABELS),
        "open_tasks": [{"id": t.id, "title": t.title, "module_key": t.module_key} for t in candidates],
    }
    try:
        from app.ai.service import chat
        result = chat(db=db, preset_name=DRAFT_PRESET, caller_module="task", caller_user_id=owner_id,
                      messages=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}])
        raw = parse_json(result.get("content", ""))
    except Exception as exc:  # noqa: BLE001 — AI 失败一律降级，不阻断建任务
        logger.warning("task draft degraded: %s", type(exc).__name__)
        print(f"[task] draft degraded: {type(exc).__name__}: {exc}", flush=True)
        return _fallback(text, module_key, parent_id, "AI 暂不可用，已按原文生成草稿")

    module_keys = {m["key"] for m in modules}
    raw_title = raw.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) and raw_title.strip() else text
    acceptance = raw.get("acceptance") if isinstance(raw.get("acceptance"), list) else []
    ai_parent = raw.get("parent_id")
    try:
        due = date.fromisoformat(str(raw.get("due_date"))).isoformat() if raw.get("due_date") else None
    except ValueError:
        due = None
    dup_ids = [i for i in (raw.get("duplicate_ids") or []) if isinstance(i, int) and i in candidate_ids][:3]
    by_id = {t.id: t for t in candidates}
    return {
        "title": title[:200],
        "priority": raw.get("priority") if raw.get("priority") in PRIORITIES else "P2",
        "acceptance": [str(a).strip()[:200] for a in acceptance if str(a).strip()][:5],
        "module_key": raw.get("module_key") if raw.get("module_key") in module_keys else module_key,
        "parent_id": ai_parent if isinstance(ai_parent, int) and ai_parent in candidate_ids else parent_id,
        "due_date": due,
        "duplicates": [{"id": i, "code": by_id[i].code, "title": by_id[i].title} for i in dup_ids],
        "degraded": False,
        "notice": None,
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `$ARK_PY -m pytest tests/test_task_ai.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/task/ai_service.py backend/tests/test_task_ai.py
git commit -m "feat(task): add AI task draft with runtime-injected domains"
```

---

### Task 6: 每日简报与定时推送

**Files:**
- Create: `backend/app/task/brief_service.py`、`backend/app/task/scheduler.py`、`backend/tests/test_task_brief.py`

事件循环约定：`AsyncIOScheduler` 与 FastAPI 同进程，`chat()` 和数据库访问都是同步阻塞调用，**不能直接写在 async job 里**（`registry.py` 第 300 行附近的明文禁令）。所以推送拆成三段：`prepare_pushes`（同步，线程池里跑：生成简报、拼 markdown）→ `send_pushes`（async，在主循环里调钉钉异步客户端）→ `mark_pushed`（同步，线程池里跑：写推送时间）。提交由调用方负责，测试直接用 conftest 的 session。

- [ ] **Step 1: 写失败测试 `backend/tests/test_task_brief.py`**

```python
"""每日简报：确定性排序、AI 选前三（只许从候选里选）、模板降级、同日幂等、钉钉推送。"""
import json
from datetime import date

import pytest

from app.task import brief_service, module_service, service
from app.task.models import TaskBrief
from tests.task_helpers import make_user

TODAY = date(2026, 9, 30)


@pytest.fixture
def owner(db):
    module_service.seed_default_modules(db)
    return make_user(db, "brief_owner", dingtalk_id="ding-brief")


def seed(db, owner_id):
    overdue = service.create_task(db, owner_id, title="逾期的", priority="P1", due_date="2026-09-26")
    p0 = service.create_task(db, owner_id, title="紧急的", priority="P0")
    soon = service.create_task(db, owner_id, title="今天到期", priority="P2", due_date="2026-09-30")
    later = service.create_task(db, owner_id, title="不急", priority="P3")
    parent = service.create_task(db, owner_id, title="父任务", priority="P0")
    service.create_task(db, owner_id, title="父的子", priority="P2", parent_id=parent.id)
    done = service.create_task(db, owner_id, title="已完成", priority="P0")
    service.change_status(db, owner_id, done.id, "done")
    return overdue, p0, soon, later


def test_rank_orders_p0_then_overdue_then_due(db, owner):
    seed(db, owner.id)
    titles = [t.title for t in brief_service.rank_candidates(db, owner.id, TODAY)]
    assert titles == ["紧急的", "逾期的", "今天到期", "父的子", "不急"]   # 父任务与已完成不参与


def test_template_brief_reasons(db, owner):
    seed(db, owner.id)
    content = brief_service.build_template(db, owner.id, TODAY)
    reasons = {t["title"]: t["reason"] for t in content["top"]}
    assert reasons == {"紧急的": "P0 紧急", "逾期的": "已逾期 4 天", "今天到期": "今天到期"}
    assert content["overdue"] == 1 and content["pending_confirm"] == 0


def test_ai_brief_only_accepts_candidate_ids(db, owner, monkeypatch):
    overdue, p0, soon, later = seed(db, owner.id)
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        return {"content": json.dumps({"top": [
            {"id": later.id, "reason": "顺手做"}, {"id": 999999, "reason": "编的"}, {"id": p0.id, "reason": "卡住别人"},
        ]}, ensure_ascii=False)}
    monkeypatch.setattr("app.ai.service.chat", fake_chat)
    content, source = brief_service.build_content(db, owner.id, TODAY)
    assert source == "ai" and calls[0]["preset_name"] == "task_brief"
    assert [t["id"] for t in content["top"]] == [later.id, p0.id]
    assert content["top"][1]["reason"] == "卡住别人"


def test_ai_failure_falls_back_to_template(db, owner, monkeypatch):
    seed(db, owner.id)
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "not json"})
    content, source = brief_service.build_content(db, owner.id, TODAY)
    assert source == "template" and len(content["top"]) == 3


def test_get_or_create_is_idempotent_per_day(db, owner, monkeypatch):
    seed(db, owner.id)
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "{}"})
    first = brief_service.get_or_create_brief(db, owner.id, TODAY)
    second = brief_service.get_or_create_brief(db, owner.id, TODAY)
    assert first.id == second.id and db.query(TaskBrief).count() == 1


def test_markdown_contains_top_and_counts(db, owner):
    seed(db, owner.id)
    md = brief_service.render_markdown(brief_service.build_template(db, owner.id, TODAY), TODAY)
    assert "09/30" in md and "紧急的" in md and "逾期 1" in md


async def test_prepare_send_mark_pushes_once_per_day(db, owner, monkeypatch):
    seed(db, owner.id)
    make_user(db, "brief_no_ding")   # 没有钉钉 ID、也没有任务的用户不参与
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "{}"})
    sent = []

    class FakeNotifier:
        async def send_to_users(self, user_ids, title, markdown_text):
            sent.append((user_ids, title))
            return True

    monkeypatch.setattr("app.dingtalk.work_notify.get_work_notifier", lambda: FakeNotifier())
    pushes = brief_service.prepare_pushes(db, TODAY)
    assert [p["dingtalk_id"] for p in pushes] == ["ding-brief"]
    ok_ids = await brief_service.send_pushes(pushes)
    brief_service.mark_pushed(db, ok_ids)
    assert sent == [(["ding-brief"], "任务简报 09/30")]
    assert db.query(TaskBrief).one().pushed_at is not None
    assert brief_service.prepare_pushes(db, TODAY) == []   # 同日已推送，不再准备
```

- [ ] **Step 2: 运行确认失败**

Run: `$ARK_PY -m pytest tests/test_task_brief.py -q`
Expected: FAIL，`ImportError: cannot import name 'brief_service'`

- [ ] **Step 3: 写 `backend/app/task/brief_service.py`**

```python
"""每日简报（一期不含 git）：未结束叶子任务确定性排序 → AI 从前 12 个候选里挑 3 个并给理由；
AI 失败或越界则用模板理由。同一 owner 同一天只生成一次、只推送一次。本模块只 flush，提交由调用方负责。"""
import json
import logging
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import beijing_now, beijing_today
from app.task.ai_service import parse_json
from app.task.models import CLOSED_STATUSES, PRIORITIES, PRIORITY_LABELS, TaskBrief, TaskItem

logger = logging.getLogger("commission")

BRIEF_PRESET = "task_brief"
TOP_N = 3
AI_CANDIDATES = 12


def _open_tasks(db: Session, owner_id: int) -> list[TaskItem]:
    return db.query(TaskItem).filter(TaskItem.owner_id == owner_id, TaskItem.deleted_at.is_(None),
                                     TaskItem.status.notin_(CLOSED_STATUSES)).all()


def rank_candidates(db: Session, owner_id: int, today: date) -> list[TaskItem]:
    tasks = _open_tasks(db, owner_id)
    parent_ids = {t.parent_id for t in tasks if t.parent_id}
    leaves = [t for t in tasks if t.id not in parent_ids and t.status != "pending_confirm"]

    def key(t: TaskItem):
        overdue = bool(t.due_date and t.due_date < today)
        return (t.priority != "P0", not overdue, t.due_date or date.max, PRIORITIES.index(t.priority), t.id)

    return sorted(leaves, key=key)


def _template_reason(t: TaskItem, today: date) -> str:
    if t.priority == "P0":
        return "P0 紧急"
    if t.due_date and t.due_date < today:
        return f"已逾期 {(today - t.due_date).days} 天"
    if t.due_date == today:
        return "今天到期"
    if t.due_date:
        return f"{(t.due_date - today).days} 天后到期"
    return f"重要性 {t.priority} {PRIORITY_LABELS[t.priority]}"


def _counts(db: Session, owner_id: int, today: date) -> dict:
    tasks = _open_tasks(db, owner_id)
    return {
        "pending_confirm": sum(1 for t in tasks if t.status == "pending_confirm"),
        "overdue": sum(1 for t in tasks if t.due_date and t.due_date < today),
        "blocked": sum(1 for t in tasks if t.status == "blocked"),
    }


def _item(t: TaskItem, reason: str) -> dict:
    return {"id": t.id, "code": t.code, "title": t.title, "priority": t.priority, "reason": reason[:120]}


def build_template(db: Session, owner_id: int, today: date) -> dict:
    top = [_item(t, _template_reason(t, today)) for t in rank_candidates(db, owner_id, today)[:TOP_N]]
    return {"top": top, **_counts(db, owner_id, today)}


def build_content(db: Session, owner_id: int, today: date) -> tuple[dict, str]:
    ranked = rank_candidates(db, owner_id, today)[:AI_CANDIDATES]
    if not ranked:
        return build_template(db, owner_id, today), "template"
    payload = {
        "today": today.isoformat(),
        "priorities": dict(PRIORITY_LABELS),
        "candidates": [{"id": t.id, "title": t.title, "priority": t.priority, "status": t.status,
                        "due_date": t.due_date.isoformat() if t.due_date else None,
                        "blocked_reason": t.blocked_reason} for t in ranked],
    }
    try:
        from app.ai.service import chat
        result = chat(db=db, preset_name=BRIEF_PRESET, caller_module="task", caller_user_id=owner_id,
                      messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        picks = parse_json(result.get("content", "")).get("top") or []
        by_id = {t.id: t for t in ranked}
        top, seen = [], set()
        for p in picks:
            if not isinstance(p, dict):
                continue
            tid, reason = p.get("id"), str(p.get("reason") or "").strip()
            if tid in by_id and tid not in seen and reason:
                top.append(_item(by_id[tid], reason))
                seen.add(tid)
            if len(top) == TOP_N:
                break
        if not top:
            raise ValueError("AI 没有给出有效候选")
        return {"top": top, **_counts(db, owner_id, today)}, "ai"
    except Exception as exc:  # noqa: BLE001 — 简报失败降级为模板，不影响推送
        logger.warning("task brief degraded: %s", type(exc).__name__)
        print(f"[task] brief degraded: {type(exc).__name__}: {exc}", flush=True)
        return build_template(db, owner_id, today), "template"


def get_or_create_brief(db: Session, owner_id: int, today: date | None = None) -> TaskBrief:
    today = today or beijing_today()
    row = db.query(TaskBrief).filter_by(owner_id=owner_id, brief_date=today).first()
    if row:
        return row
    content, source = build_content(db, owner_id, today)
    row = TaskBrief(owner_id=owner_id, brief_date=today, content_json=content, source=source)
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        # 页面请求与定时任务并发生成：以先写入的为准
        return db.query(TaskBrief).filter_by(owner_id=owner_id, brief_date=today).one()
    return row


def serialize_brief(row: TaskBrief) -> dict:
    return {"brief_date": row.brief_date.isoformat(), "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "pushed_at": row.pushed_at.isoformat() if row.pushed_at else None, **row.content_json}


def render_markdown(content: dict, today: date) -> str:
    lines = [f"### 任务简报 {today.strftime('%m/%d')}", "", "**今天建议先做：**"]
    for i, t in enumerate(content.get("top") or [], 1):
        lines.append(f"{i}. **{t['code']}** {t['title']} —— {t['reason']}")
    if not content.get("top"):
        lines.append("没有未结束的任务。")
    lines += ["", f"待确认 {content.get('pending_confirm', 0)} · 逾期 {content.get('overdue', 0)} · "
                  f"受阻 {content.get('blocked', 0)}"]
    return "\n".join(lines)


def owners_with_open_tasks(db: Session) -> list[int]:
    return [r[0] for r in db.query(TaskItem.owner_id).filter(
        TaskItem.deleted_at.is_(None), TaskItem.status.notin_(CLOSED_STATUSES)).distinct().all()]


def prepare_pushes(db: Session, today: date, commit=None) -> list[dict]:
    """同步：为每个有未结束任务的 owner 生成当日简报，返回待推送清单（已推送或无钉钉 ID 的跳过）。
    会调用 AI，必须在线程池里执行。commit 由调用方传入（scheduler 传 db.commit）。"""
    from app.auth.models import ArkUser

    pushes = []
    for owner_id in owners_with_open_tasks(db):
        try:
            brief = get_or_create_brief(db, owner_id, today)
            if commit:
                commit()
            user = db.get(ArkUser, owner_id)
            if brief.pushed_at or not (user and user.dingtalk_id):
                continue
            pushes.append({"brief_id": brief.id, "dingtalk_id": user.dingtalk_id,
                           "title": f"任务简报 {today.strftime('%m/%d')}",
                           "markdown": render_markdown(brief.content_json, today)})
        except Exception as exc:  # noqa: BLE001 — 单个 owner 失败不影响其他人
            db.rollback()
            logger.warning("task brief prepare failed owner=%s: %s", owner_id, type(exc).__name__)
            print(f"[task] brief prepare failed owner={owner_id}: {type(exc).__name__}: {exc}", flush=True)
    return pushes


async def send_pushes(pushes: list[dict]) -> list[int]:
    """异步：在主事件循环里调钉钉工作通知，返回发送成功的 brief_id。"""
    from app.dingtalk.work_notify import get_work_notifier

    notifier, ok_ids = get_work_notifier(), []
    for p in pushes:
        try:
            if await notifier.send_to_users(user_ids=[p["dingtalk_id"]], title=p["title"], markdown_text=p["markdown"]):
                ok_ids.append(p["brief_id"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("task brief send failed brief=%s: %s", p["brief_id"], type(exc).__name__)
            print(f"[task] brief send failed brief={p['brief_id']}: {type(exc).__name__}: {exc}", flush=True)
    return ok_ids


def mark_pushed(db: Session, brief_ids: list[int]) -> None:
    if brief_ids:
        db.query(TaskBrief).filter(TaskBrief.id.in_(brief_ids)).update(
            {TaskBrief.pushed_at: beijing_now()}, synchronize_session="fetch")
        db.flush()
```

- [ ] **Step 4: 写 `backend/app/task/scheduler.py`**

```python
"""任务中心定时任务入口（单活 scheduler 内运行，自建 session）。

AI 与数据库是同步阻塞调用，放到线程池；只有钉钉异步发送留在主事件循环（registry.py 禁止 async job 里做同步 IO）。
"""
import asyncio
import logging
from datetime import date

from app.core.database import SessionLocal
from app.core.time import beijing_today
from app.task import brief_service

logger = logging.getLogger("commission")


def _prepare(today: date) -> list[dict]:
    with SessionLocal() as db:
        return brief_service.prepare_pushes(db, today, commit=db.commit)


def _mark(brief_ids: list[int]) -> None:
    with SessionLocal() as db:
        brief_service.mark_pushed(db, brief_ids)
        db.commit()


async def send_task_briefs_job():
    try:
        pushes = await asyncio.to_thread(_prepare, beijing_today())
        ok_ids = await brief_service.send_pushes(pushes)
        await asyncio.to_thread(_mark, ok_ids)
        print(f"[task] daily briefs pushed: {len(ok_ids)}/{len(pushes)}", flush=True)
    except Exception as exc:
        logger.warning("task brief job failed: %s", type(exc).__name__)
        print(f"[task] brief job failed: {type(exc).__name__}: {exc}", flush=True)
        raise
```

- [ ] **Step 5: 运行确认通过**

Run: `$ARK_PY -m pytest tests/test_task_brief.py -q`
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/task/brief_service.py backend/app/task/scheduler.py backend/tests/test_task_brief.py
git commit -m "feat(task): add daily brief with AI ranking and template fallback"
```

---

### Task 7: 路由、权限、preset、启动种子、定时注册

**Files:**
- Create: `backend/app/task/schemas.py`、`backend/app/task/router.py`、`backend/app/bootstrap/seed_task.py`、`backend/tests/test_task_api.py`
- Modify: `backend/app/routers.py`、`backend/app/auth/service.py`、`backend/app/bootstrap/seed_ai.py`、`backend/app/bootstrap/__init__.py`、`backend/app/main.py`、`backend/app/core/config.py`、`backend/app/schedulers/registry.py`

- [ ] **Step 1: 写失败测试 `backend/tests/test_task_api.py`**

```python
"""HTTP 层：权限、信封、错误码映射、owner 隔离。"""
from app.task import module_service
from tests.task_helpers import make_user, task_client


def _setup(db):
    module_service.seed_default_modules(db)
    return make_user(db, "api_owner")


def test_create_list_detail_roundtrip(db):
    owner = _setup(db)
    with task_client(db, owner) as c:
        r = c.post("/api/task/items", json={"title": "写汇报", "module_key": "custom.report", "priority": "P1"})
        assert r.status_code == 200 and r.json()["code"] == 200
        tid = r.json()["data"]["id"]
        kid = c.post("/api/task/items", json={"title": "收集数据", "parent_id": tid}).json()["data"]
        tree = c.get("/api/task/items").json()["data"]
        assert tree[0]["id"] == tid and tree[0]["children"][0]["id"] == kid["id"]
        detail = c.get(f"/api/task/items/{tid}").json()["data"]
        assert detail["code"] == f"T-{tid}" and detail["events"][0]["type"] == "created"


def test_read_only_permission_cannot_write(db):
    owner = _setup(db)
    with task_client(db, owner, permissions=("task:read",)) as c:
        assert c.get("/api/task/items").status_code == 200
        assert c.post("/api/task/items", json={"title": "x"}).status_code == 403


def test_no_permission_forbidden(db):
    owner = _setup(db)
    with task_client(db, owner, permissions=()) as c:
        assert c.get("/api/task/items").status_code == 403


def test_other_owner_gets_404(db):
    owner = _setup(db)
    other = make_user(db, "api_other")
    with task_client(db, owner) as c:
        tid = c.post("/api/task/items", json={"title": "mine"}).json()["data"]["id"]
    with task_client(db, other) as c:
        assert c.get(f"/api/task/items/{tid}").status_code == 404
        assert c.patch(f"/api/task/items/{tid}", json={"title": "hack"}).status_code == 404
        assert c.get("/api/task/items").json()["data"] == []


def test_status_conflict_carries_code(db):
    owner = _setup(db)
    with task_client(db, owner) as c:
        pid = c.post("/api/task/items", json={"title": "p"}).json()["data"]["id"]
        c.post("/api/task/items", json={"title": "c", "parent_id": pid})
        r = c.post(f"/api/task/items/{pid}/status", json={"status": "done"})
        assert r.status_code == 409
        assert r.json()["detail"] == {"message": "还有 1 个子任务没结束", "code": "open_children", "open_children": 1}
        r = c.post(f"/api/task/items/{pid}/status", json={"status": "done", "confirm_open_children": True})
        assert r.json()["data"]["status"] == "done"


def test_modules_stats_trash_and_links(db):
    owner = _setup(db)
    with task_client(db, owner) as c:
        keys = {m["key"] for m in c.get("/api/task/modules").json()["data"]}
        assert "custom.report" in keys
        key = c.post("/api/task/modules/custom", json={"title": "副业"}).json()["data"]["key"]
        assert key.startswith("custom.u")
        tid = c.post("/api/task/items", json={"title": "t", "due_date": "2000-01-01"}).json()["data"]["id"]
        assert c.get("/api/task/stats").json()["data"]["overdue"] == 1
        link = c.post(f"/api/task/items/{tid}/links", json={"kind": "doc", "ref": "docs/a.md"}).json()["data"]
        assert c.delete(f"/api/task/links/{link['id']}").status_code == 200
        c.delete(f"/api/task/items/{tid}")
        assert [t["id"] for t in c.get("/api/task/trash").json()["data"]] == [tid]
        c.post(f"/api/task/items/{tid}/restore")
        assert c.get("/api/task/trash").json()["data"] == []


def test_ai_draft_endpoint_degrades(db, monkeypatch):
    owner = _setup(db)

    def boom(**kwargs):
        raise RuntimeError("down")
    monkeypatch.setattr("app.ai.service.chat", boom)
    with task_client(db, owner) as c:
        r = c.post("/api/task/ai/draft", json={"text": "写汇报", "module_key": "custom.report"})
        assert r.json()["data"]["degraded"] is True


def test_brief_today_endpoint(db, monkeypatch):
    owner = _setup(db)
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "{}"})
    with task_client(db, owner) as c:
        c.post("/api/task/items", json={"title": "紧急", "priority": "P0"})
        data = c.get("/api/task/brief/today").json()["data"]
        assert data["top"][0]["title"] == "紧急" and data["source"] == "template"
```

- [ ] **Step 2: 运行确认失败**

Run: `$ARK_PY -m pytest tests/test_task_api.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.task.router'`

- [ ] **Step 3: 写 `backend/app/task/schemas.py`**

```python
"""任务中心入参。字段值域的业务校验在 service 层（返回中文提示），这里只做形状约束。"""
from typing import Optional

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    acceptance: Optional[list[str]] = None
    priority: str = "P2"
    module_key: Optional[str] = None
    parent_id: Optional[int] = None
    due_date: Optional[str] = None
    source: str = "manual"


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=10000)
    acceptance: Optional[list[str]] = None
    priority: Optional[str] = None
    module_key: Optional[str] = None
    due_date: Optional[str] = None


class StatusChange(BaseModel):
    status: str
    reason: Optional[str] = Field(None, max_length=500)
    confirm_open_children: bool = False


class MoveInput(BaseModel):
    parent_id: Optional[int] = None


class LinkCreate(BaseModel):
    kind: str
    ref: str = Field(..., max_length=500)
    title: str = Field("", max_length=200)


class CustomModuleCreate(BaseModel):
    title: str = Field(..., max_length=100)


class DraftRequest(BaseModel):
    text: str = Field(..., max_length=1000)
    module_key: Optional[str] = None
    parent_id: Optional[int] = None
```

- [ ] **Step 4: 写 `backend/app/task/router.py`**

```python
"""任务中心 HTTP 薄适配层。

权限：task:read（查看）/ task:write（建、改、删、AI 草稿）。数据按 JWT sub 隔离，
跨 owner 访问一律 404。统一信封 ok()；领域异常转 HTTPException，409 带 code 供前端分支处理。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission
from app.core.database import get_db
from app.core.response import ok
from app.task import ai_service, brief_service, module_service, service
from app.task.errors import TaskError
from app.task.schemas import (
    CustomModuleCreate, DraftRequest, LinkCreate, MoveInput, StatusChange, TaskCreate, TaskUpdate,
)

router = APIRouter()
READ = ("task:read", "task:write")
WRITE = ("task:write",)


def _owner(user: dict) -> int:
    return int(user["sub"])


def _call(db: Session, fn, *args, commit: bool = False, **kwargs):
    try:
        result = fn(db, *args, **kwargs)
        if commit:
            db.commit()
        return result
    except TaskError as exc:
        db.rollback()
        detail = {"message": str(exc), "code": exc.code, **exc.extra} if exc.code else str(exc)
        raise HTTPException(exc.status_code, detail) from exc


@router.get("/items", summary="任务树")
def list_items(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(service.list_tree(db, _owner(user)))


@router.post("/items", summary="新建任务")
def create_item(payload: TaskCreate, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.create_task, _owner(user), commit=True, **payload.model_dump())
    return ok(service.serialize_task(task))


@router.get("/items/{task_id}", summary="任务详情")
def get_item(task_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(_call(db, service.task_detail, _owner(user), task_id))


@router.patch("/items/{task_id}", summary="修改任务字段")
def update_item(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db),
                user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.update_task, _owner(user), task_id, payload.model_dump(exclude_unset=True), commit=True)
    return ok(service.serialize_task(task))


@router.post("/items/{task_id}/status", summary="变更状态")
def change_status(task_id: int, payload: StatusChange, db: Session = Depends(get_db),
                  user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.change_status, _owner(user), task_id, payload.status, reason=payload.reason,
                 confirm_open_children=payload.confirm_open_children, commit=True)
    return ok(service.serialize_task(task))


@router.post("/items/{task_id}/move", summary="调整父任务")
def move_item(task_id: int, payload: MoveInput, db: Session = Depends(get_db),
              user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.move_task, _owner(user), task_id, payload.parent_id, commit=True)
    return ok(service.serialize_task(task))


@router.delete("/items/{task_id}", summary="删除任务（连同子任务进回收站）")
def delete_item(task_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    _call(db, service.delete_task, _owner(user), task_id, commit=True)
    return ok({"deleted": True})


@router.post("/items/{task_id}/restore", summary="从回收站恢复")
def restore_item(task_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    task = _call(db, service.restore_task, _owner(user), task_id, commit=True)
    return ok(service.serialize_task(task))


@router.get("/trash", summary="回收站")
def trash(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(service.list_trash(db, _owner(user)))


@router.post("/items/{task_id}/links", summary="挂文档/原型/链接")
def add_link(task_id: int, payload: LinkCreate, db: Session = Depends(get_db),
             user: dict = Depends(require_any_permission(*WRITE))):
    link = _call(db, service.add_link, _owner(user), task_id, commit=True, **payload.model_dump())
    return ok(service.serialize_link(link))


@router.delete("/links/{link_id}", summary="移除关联")
def remove_link(link_id: int, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    _call(db, service.remove_link, _owner(user), link_id, commit=True)
    return ok({"deleted": True})


@router.get("/stats", summary="页头统计")
def stats(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(service.stats(db, _owner(user)))


@router.get("/modules", summary="模块注册表（含本人私有分类）")
def modules(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    return ok(module_service.list_modules(db, _owner(user)))


@router.post("/modules/custom", summary="新建私有分类")
def add_custom_module(payload: CustomModuleCreate, db: Session = Depends(get_db),
                      user: dict = Depends(require_any_permission(*WRITE))):
    key = _call(db, module_service.add_custom, _owner(user), payload.title, commit=True)
    return ok({"key": key})


@router.delete("/modules/custom/{key}", summary="停用私有分类")
def remove_custom_module(key: str, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    _call(db, module_service.deactivate_custom, _owner(user), key, commit=True)
    return ok({"deactivated": True})


@router.post("/ai/draft", summary="一句话生成任务草稿（不写库）")
def ai_draft(payload: DraftRequest, db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*WRITE))):
    return ok(_call(db, ai_service.draft_task, _owner(user), payload.text,
                    module_key=payload.module_key, parent_id=payload.parent_id))


@router.get("/brief/today", summary="今日简报（没有则即时生成，不推送）")
def brief_today(db: Session = Depends(get_db), user: dict = Depends(require_any_permission(*READ))):
    row = _call(db, brief_service.get_or_create_brief, _owner(user), commit=True)
    return ok(brief_service.serialize_brief(row))
```

- [ ] **Step 5: 运行 API 测试确认通过**

Run: `$ARK_PY -m pytest tests/test_task_api.py -q`
Expected: `8 passed`

- [ ] **Step 6: 注册路由**：在 `backend/app/routers.py` 中

import 区（紧挨 `from app.training.router import router as training_router`）加：

```python
from app.task.router import router as task_router
```

`app.include_router(training_router, prefix="/api/training", tags=["培训速递"])` 下一行加：

```python
    app.include_router(task_router, prefix="/api/task", tags=["任务中心"])
```

- [ ] **Step 7: 权限种子**：在 `backend/app/auth/service.py` 的 `seeds` 列表里，紧跟 `("training:admin", ...)` 那一行之后加：

```python
        # 任务中心（2026-09-30，个人任务，数据按本人隔离）
        ("task:read",             "task",       "read",       "查看任务中心"),
        ("task:write",            "task",       "write",      "新建/编辑任务、导航悬浮 + 快速建任务、AI 草稿"),
```

- [ ] **Step 8: AI preset**：在 `backend/app/bootstrap/seed_ai.py` 中，找到 `_TRAINING_DRAFT_SYSTEM_PROMPT = ` 的定义，在它结束之后加两个常量：

```python
_TASK_DRAFT_SYSTEM_PROMPT = """你是个人任务助手。用户消息是一个 JSON：text 是用户随手写的一句话；
modules 是可选模块，priorities 是可选重要性，open_tasks 是用户现有的未结束任务，today 是北京时间今天，
preset_module / preset_parent_id 是用户所在位置的预填值。

只输出一个 JSON 对象，不要解释：
{"title": 不超过40字的动宾短句标题,
 "priority": priorities 的某个键,
 "acceptance": 2~4 条可客观核验的验收标准（字符串数组）,
 "module_key": modules 中最相关条目的 key；拿不准就用 preset_module,
 "parent_id": 若明显属于 open_tasks 中某个任务的子任务则填其 id，否则填 preset_parent_id,
 "duplicate_ids": open_tasks 中与本任务几乎是同一件事的 id 数组（没有就空数组）,
 "due_date": 用户明确提到时间时按 today 推算的 YYYY-MM-DD，否则 null}
所有取值只能来自用户消息给出的范围，不得编造 key 或 id。"""

_TASK_BRIEF_SYSTEM_PROMPT = """你是个人任务助手，为用户挑出今天最该先做的三件事。用户消息是一个 JSON：
candidates 是已按紧急程度粗排的未结束任务，today 是北京时间今天，priorities 是重要性含义。

只输出一个 JSON 对象，不要解释：
{"top": [{"id": candidates 中的 id, "reason": 不超过40字的理由，说清为什么今天先做它}]}
最多 3 项；id 只能来自 candidates；理由要具体（逾期几天、卡住什么、截止在哪天），不要空话。"""
```

在 `_auto_create_preset(preset_name="training_digest_draft", ...)` 调用之后加：

```python
    _auto_create_preset(
        preset_name="task_draft",
        system_prompt=_TASK_DRAFT_SYSTEM_PROMPT,
        parameters={"temperature": 0.2, "max_tokens": 1024},
        description="任务中心：一句话生成任务草稿（值域运行时注入）",
    )
    _auto_create_preset(
        preset_name="task_brief",
        system_prompt=_TASK_BRIEF_SYSTEM_PROMPT,
        parameters={"temperature": 0.3, "max_tokens": 1024},
        description="任务中心：每日简报挑选今日前三",
    )
```

- [ ] **Step 9: 配置开关**：在 `backend/app/core/config.py` 的 `ANNOUNCEMENT_WORKER_ENABLED: bool = True` 下一行加：

```python
    # 任务中心：启动时用 frontend/dist/nav-manifest.json 同步模块注册表。仅生产 .env 置 true；
    # 开发机与云端展会实例保持 false，避免不同版本的导航清单互相覆盖共享库
    TASK_MODULE_SYNC_ENABLED: bool = False
```

- [ ] **Step 10: 启动种子**：写 `backend/app/bootstrap/seed_task.py`

```python
"""任务中心启动种子：默认模块（幂等）+ 导航清单同步（仅 TASK_MODULE_SYNC_ENABLED 环境）。失败不阻塞启动。"""
import logging

from app.bootstrap.static_files import FRONTEND_DIST
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.task import module_service

logger = logging.getLogger("commission")


def seed_task_modules() -> None:
    try:
        with SessionLocal() as db:
            module_service.seed_default_modules(db)
            if get_settings().TASK_MODULE_SYNC_ENABLED:
                manifest = module_service.load_manifest(FRONTEND_DIST / "nav-manifest.json")
                if manifest is None:
                    print("[task] nav-manifest.json missing, module registry kept", flush=True)
                else:
                    result = module_service.sync_nav_manifest(db, manifest)
                    print(f"[task] nav modules synced: {result}", flush=True)
            db.commit()
    except Exception as exc:
        logger.warning("task module seed skipped: %s", exc)
        print(f"[task] module seed skipped: {exc}", flush=True)
```

`backend/app/bootstrap/__init__.py`：import 区加 `from app.bootstrap.seed_task import seed_task_modules`，`__all__` 加 `"seed_task_modules",`。

`backend/app/main.py`：第 18~19 行从 `app.bootstrap` 导入的名单里加上 `seed_task_modules`；lifespan 里 `seed_whatsapp_translation_glossary()` 的下一行加 `seed_task_modules()`。

- [ ] **Step 11: 定时注册**：在 `backend/app/schedulers/registry.py` 的 `if settings.ANNOUNCEMENT_WORKER_ENABLED:` 代码块之前加：

```python
    from app.task.scheduler import send_task_briefs_job
    scheduler.add_job(send_task_briefs_job, trigger="cron", hour=8, minute=53, timezone="Asia/Shanghai",
                      id="task_daily_brief", replace_existing=True, max_instances=1, coalesce=True,
                      misfire_grace_time=1800)
```

在 `backend/app/operations/models.py` 的 `JOB_METADATA` 字典里（紧跟 `"announcement_weekly": ...` 那一行）加：

```python
    "task_daily_brief": JobMetadata("任务中心每日简报", "任务中心", "平台研发"),
```

否则运维中心会把它显示成「未归类 / 待指定」，查运行记录时还会报「任务不存在」。

- [ ] **Step 12: 冒烟与回归**

Run: `$ARK_PY -c "import app.main"`
Expected: 无异常退出（只验证能导入，不启动服务，也不连库）

Run: `$ARK_PY -m pytest tests/test_task_models.py tests/test_task_modules.py tests/test_task_service.py tests/test_task_state.py tests/test_task_ai.py tests/test_task_brief.py tests/test_task_api.py -q`
Expected: 全部 passed

Run: `$ARK_PY -m pytest tests -q -k "scheduler or registry or permission or seed" 2>&1 | tail -3`
Expected: 无失败。若出现失败，先切回 main 跑同一条命令确认是否本来就失败，只处理本次引入的。

- [ ] **Step 13: Commit**

```bash
git add backend/app/task/schemas.py backend/app/task/router.py backend/app/bootstrap/seed_task.py backend/tests/test_task_api.py backend/app/routers.py backend/app/auth/service.py backend/app/bootstrap/seed_ai.py backend/app/bootstrap/__init__.py backend/app/main.py backend/app/core/config.py backend/app/schedulers/registry.py backend/app/operations/models.py
git commit -m "feat(task): expose task center API, permissions, presets and brief job"
```

---

### Task 8: 前端纯函数层 + 导航清单导出

**Files:**
- Create: `frontend/src/config/navManifest.js`、`frontend/build/navManifestPlugin.js`、`frontend/src/views/task/taskLabels.js`、`frontend/src/views/task/taskTree.js`、`frontend/tests/taskCenter.test.mjs`
- Modify: `frontend/vite.config.js`、`frontend/package.json`

- [ ] **Step 1: 写失败测试 `frontend/tests/taskCenter.test.mjs`**

```js
import test from 'node:test'
import assert from 'node:assert/strict'
import { buildNavManifest } from '../src/config/navManifest.js'
import { boardColumns, filterTree, moduleHeat, openDescendantCount, parentTitles } from '../src/views/task/taskTree.js'
import { isOverdue, userStatusOptions } from '../src/views/task/taskLabels.js'

const GROUPS = { invoice: { title: '订单管理' }, task: { title: '个人效率' } }
const ENTRIES = [
  { path: '/dashboard', name: 'Dashboard', title: '工作台', menu: { title: '我的工作台', order: 0 } },
  { path: '/invoice', name: 'InvoiceManage', title: '订单发票', menu: { group: 'invoice', order: 2 } },
  { path: '/receipts', name: 'ReceiptList', title: '回款管理', menu: { group: 'invoice', title: '回款', order: 1 } },
  { path: '/invoice/:id', name: 'InvoiceDetail', title: '详情', hideInMenu: true },
  { path: '/6010/', name: 'Static6010', title: '静态页', external: true, menu: { group: 'invoice' } },
  { path: '/task', name: 'TaskCenter', title: '任务中心', menu: { group: 'task', order: 1 } },
]

test('nav manifest keeps menu entries in navigation order', () => {
  const m = buildNavManifest(GROUPS, ENTRIES)
  assert.equal(m.version, 1)
  const ordered = [...m.entries].sort((a, b) => a.sort - b.sort).map(e => e.key)
  assert.deepEqual(ordered, ['Dashboard', 'ReceiptList', 'InvoiceManage', 'TaskCenter'])
  const receipt = m.entries.find(e => e.key === 'ReceiptList')
  assert.deepEqual(receipt, { key: 'ReceiptList', title: '回款', group_key: 'invoice', group_title: '订单管理', route: '/receipts', sort: 1001 })
  assert.equal(m.entries.find(e => e.key === 'Dashboard').group_title, '一级页面')
})

test('nav manifest rejects duplicate route names', () => {
  assert.throws(() => buildNavManifest(GROUPS, [ENTRIES[1], { ...ENTRIES[1], path: '/x' }]), /重复/)
})

const TREE = [
  { id: 1, title: '客户工作台 v2', priority: 'P0', status: 'in_progress', module_key: 'Cust', due_date: '2026-10-10', children: [
    { id: 2, title: '分层口径', priority: 'P0', status: 'pending_confirm', module_key: 'Cust', due_date: '2026-09-29', children: [] },
    { id: 3, title: '合并入口', priority: 'P1', status: 'done', module_key: 'Cust', due_date: null, children: [] },
  ] },
  { id: 4, title: '汇报材料', priority: 'P2', status: 'shelved', module_key: 'custom.report', due_date: null, children: [] },
  { id: 5, title: '薪资权限', priority: 'P0', status: 'blocked', module_key: 'Salary', due_date: '2026-09-26', children: [] },
]

test('filterTree keeps ancestors of matches and hides closed', () => {
  const hidden = filterTree(TREE, { hideClosed: true })
  assert.deepEqual(hidden.map(n => n.id), [1, 5])
  assert.deepEqual(hidden[0].children.map(n => n.id), [2])
  const q = filterTree(TREE, { q: 't-3', hideClosed: false })
  assert.deepEqual(q.map(n => n.id), [1])
  assert.deepEqual(q[0].children.map(n => n.id), [3])
  const byPrio = filterTree(TREE, { priorities: ['P1'], hideClosed: false })
  assert.deepEqual(byPrio[0].children.map(n => n.id), [3])
})

test('boardColumns only uses leaves and skips shelved', () => {
  const cols = boardColumns(TREE, {})
  assert.deepEqual(Object.fromEntries(Object.entries(cols).map(([k, v]) => [k, v.map(t => t.id)])),
    { todo: [], in_progress: [], blocked: [5], pending_confirm: [2], done: [3] })
})

test('moduleHeat counts open leaves per module', () => {
  const modules = [
    { key: 'Cust', title: '客户工作台', group_key: 'customer', group_title: '客户经营' },
    { key: 'Salary', title: '薪资工作台', group_key: 'salary', group_title: '薪资计算' },
    { key: 'custom.report', title: '汇报材料', group_key: 'custom', group_title: '方舟外' },
  ]
  const heat = moduleHeat(TREE, modules)
  assert.deepEqual(heat.map(g => [g.group_title, g.open]), [['客户经营', 1], ['薪资计算', 1], ['方舟外', 0]])
  assert.equal(heat[1].items[0].hasP0, true)
})

test('parentTitles maps child id to parent title', () => {
  assert.equal(parentTitles(TREE).get(2), '客户工作台 v2')
})

test('openDescendantCount ignores closed descendants', () => {
  assert.equal(openDescendantCount(TREE, 1), 1)
  assert.equal(openDescendantCount(TREE, 5), 0)
  assert.equal(openDescendantCount(TREE, 999), 0)
})

test('status options follow the user transition matrix', () => {
  assert.deepEqual(userStatusOptions('done'), ['done', 'todo'])
  assert.deepEqual(userStatusOptions('pending_confirm'), ['pending_confirm', 'todo', 'in_progress', 'blocked', 'done', 'shelved'])
  assert.ok(!userStatusOptions('todo').includes('pending_confirm'))
})

test('isOverdue uses beijing today string and ignores closed', () => {
  assert.equal(isOverdue({ due_date: '2026-09-29', status: 'todo' }, '2026-09-30'), true)
  assert.equal(isOverdue({ due_date: '2026-09-29', status: 'done' }, '2026-09-30'), false)
  assert.equal(isOverdue({ due_date: '2026-09-30', status: 'todo' }, '2026-09-30'), false)
})
```

- [ ] **Step 2: 在 `frontend/package.json` 的 scripts 里加一行（放在 `test:invoice-layout` 之前）**

```json
    "test:task-center": "node --test tests/taskCenter.test.mjs",
```

- [ ] **Step 3: 运行确认失败**

Run: `cd frontend && npm run test:task-center`
Expected: FAIL，`Cannot find module '.../src/config/navManifest.js'`

- [ ] **Step 4: 写 `frontend/src/config/navManifest.js`**

```js
/**
 * 导航配置 → 任务中心模块清单（纯函数）。
 * 构建期由 build/navManifestPlugin.js 调用并写出 dist/nav-manifest.json，后端启动时同步到
 * ark_task_modules。模块键用路由 name（唯一且稳定）；sort = 分组序号*1000 + 组内 order，
 * 后端按 sort 排序即可还原导航顺序。
 */
export const NAV_MANIFEST_VERSION = 1

export function buildNavManifest(menuGroups, navEntries) {
  const groupKeys = Object.keys(menuGroups)
  const entries = navEntries
    .filter(entry => entry.menu && !entry.hideInMenu && !entry.external && entry.name)
    .map(entry => {
      const groupKey = entry.menu.group || 'top'
      const groupIndex = entry.menu.group ? groupKeys.indexOf(groupKey) + 1 : 0
      return {
        key: entry.name,
        title: entry.menu.title ?? entry.title,
        group_key: groupKey,
        group_title: entry.menu.group ? (menuGroups[groupKey]?.title ?? groupKey) : '一级页面',
        route: entry.path,
        sort: groupIndex * 1000 + (entry.menu.order ?? 999),
      }
    })
  const seen = new Set()
  for (const entry of entries) {
    if (seen.has(entry.key)) throw new Error(`导航路由 name 重复：${entry.key}`)
    seen.add(entry.key)
  }
  return { version: NAV_MANIFEST_VERSION, entries }
}
```

- [ ] **Step 5: 写 `frontend/src/views/task/taskLabels.js`**

```js
/** 任务中心文案与状态规则（纯模块，与后端 app/task/models.py、service.can_transition 同口径）。 */
export const STATUS_META = {
  todo: { label: '待办', tone: 'todo' },
  in_progress: { label: '进行中', tone: 'doing' },
  blocked: { label: '受阻', tone: 'blocked' },
  pending_confirm: { label: '待确认', tone: 'pending' },
  done: { label: '已完成', tone: 'done' },
  shelved: { label: '已搁置', tone: 'shelved' },
}
export const PRIORITY_META = {
  P0: { label: '紧急', tone: 'p0' },
  P1: { label: '高', tone: 'p1' },
  P2: { label: '中', tone: 'p2' },
  P3: { label: '低', tone: 'p3' },
}
export const PRIORITIES = Object.keys(PRIORITY_META)
export const CLOSED = new Set(['done', 'shelved'])
export const BOARD_COLUMNS = ['todo', 'in_progress', 'blocked', 'pending_confirm', 'done']
export const LINK_KIND_META = { doc: '文档', prototype: '原型', url: '链接' }
export const EVENT_LABELS = {
  created: '创建', updated: '修改字段', status_changed: '变更状态', moved: '调整父任务',
  deleted: '删除', restored: '恢复', linked: '添加关联', unlinked: '移除关联',
}
export const ACTOR_LABELS = { user: '我', ai: 'AI', reporter: '上报器', mcp: '代理' }

const OPEN = ['todo', 'in_progress', 'blocked']

/** 详情抽屉「状态」下拉的可选项：首项为当前状态，其余为用户可迁移的目标。 */
export function userStatusOptions(current) {
  if (CLOSED.has(current)) return [current, 'todo']
  if (current === 'pending_confirm') return ['pending_confirm', ...OPEN, 'done', 'shelved']
  return [current, ...OPEN.filter(s => s !== current), 'done', 'shelved']
}

/** today 为北京时间 YYYY-MM-DD（utils/datetime.js 的 currentBeijingDate()）。 */
export function isOverdue(task, today) {
  return Boolean(task.due_date) && task.due_date < today && !CLOSED.has(task.status)
}
```

注意：`userStatusOptions('todo')` 返回 `['todo', 'in_progress', 'blocked', 'done', 'shelved']`，满足测试「不含 pending_confirm」。

- [ ] **Step 6: 写 `frontend/src/views/task/taskTree.js`**

```js
/** 任务树的纯函数：筛选、看板分列、模块热度、父标题索引。 */
import { BOARD_COLUMNS, CLOSED } from './taskLabels.js'

function selfMatches(task, filters) {
  const q = (filters.q || '').trim().toLowerCase()
  if (q && !(`t-${task.id}`.includes(q) || task.title.toLowerCase().includes(q))) return false
  if (filters.moduleKey && task.module_key !== filters.moduleKey) return false
  if (filters.priorities?.length && !filters.priorities.includes(task.priority)) return false
  if (filters.hideClosed && CLOSED.has(task.status)) return false
  return true
}

/** 保留自身命中或有后代命中的节点；返回新树，不修改入参。 */
export function filterTree(nodes, filters = {}) {
  const out = []
  for (const node of nodes) {
    const children = filterTree(node.children || [], filters)
    if (selfMatches(node, filters) || children.length) out.push({ ...node, children })
  }
  return out
}

export function collectLeaves(nodes, acc = []) {
  for (const node of nodes) {
    if (node.children?.length) collectLeaves(node.children, acc)
    else acc.push(node)
  }
  return acc
}

/** 看板只放叶子任务；已搁置不上板；「已完成」列始终显示，所以忽略 hideClosed。 */
export function boardColumns(nodes, filters = {}) {
  const cols = Object.fromEntries(BOARD_COLUMNS.map(s => [s, []]))
  const leaves = collectLeaves(nodes).filter(t => selfMatches(t, { ...filters, hideClosed: false }))
  for (const task of leaves) {
    if (cols[task.status]) cols[task.status].push(task)
  }
  return cols
}

/** 按模块分组统计未结束叶子数；modules 顺序即展示顺序。 */
export function moduleHeat(nodes, modules) {
  const open = collectLeaves(nodes).filter(t => !CLOSED.has(t.status))
  const groups = new Map()
  for (const m of modules) {
    if (!groups.has(m.group_key)) groups.set(m.group_key, { group_key: m.group_key, group_title: m.group_title, open: 0, items: [] })
    const mine = open.filter(t => t.module_key === m.key)
    const group = groups.get(m.group_key)
    group.items.push({ key: m.key, title: m.title, open: mine.length, hasP0: mine.some(t => t.priority === 'P0'), isPrivate: Boolean(m.is_private) })
    group.open += mine.length
  }
  return [...groups.values()]
}

export function findNode(nodes, id) {
  for (const node of nodes) {
    if (node.id === id) return node
    const found = findNode(node.children || [], id)
    if (found) return found
  }
  return null
}

/** 某任务下未结束的子孙数：标记完成前的确认文案用（后端仍会校验）。 */
export function openDescendantCount(nodes, id) {
  let count = 0
  const walk = list => {
    for (const node of list) {
      if (!CLOSED.has(node.status)) count += 1
      walk(node.children || [])
    }
  }
  walk(findNode(nodes, id)?.children || [])
  return count
}

export function parentTitles(nodes, parent = null, map = new Map()) {
  for (const node of nodes) {
    if (parent) map.set(node.id, parent.title)
    parentTitles(node.children || [], node, map)
  }
  return map
}

/** 下拉选择父任务用：扁平化并带缩进层级。 */
export function flattenForSelect(nodes, depth = 0, acc = []) {
  for (const node of nodes) {
    if (!CLOSED.has(node.status)) acc.push({ id: node.id, label: `${'　'.repeat(depth)}T-${node.id} ${node.title}`, depth })
    flattenForSelect(node.children || [], depth + 1, acc)
  }
  return acc
}
```

- [ ] **Step 7: 运行确认通过**

Run: `cd frontend && npm run test:task-center`
Expected: `# pass 9`、`# fail 0`

- [ ] **Step 8: 写构建插件 `frontend/build/navManifestPlugin.js`**

```js
import fs from 'node:fs'
import path from 'node:path'
import { createServer } from 'vite'

/**
 * 构建收尾时导出 <outDir>/nav-manifest.json，供任务中心后端启动时同步模块注册表。
 * 用 vite SSR 加载 navigation.js（它依赖 @ 别名与图标包，组件是懒加载不会执行）。
 * 导出失败只告警不阻断构建：后端找不到清单会保留现有注册表。
 */
export function navManifestPlugin() {
  let root
  let outDir
  return {
    name: 'ark-nav-manifest',
    apply: 'build',
    configResolved(config) {
      root = config.root
      outDir = path.resolve(config.root, config.build.outDir)
    },
    async closeBundle() {
      let server
      try {
        server = await createServer({
          configFile: false,
          root,
          logLevel: 'error',
          appType: 'custom',
          server: { middlewareMode: true, hmr: false },
          resolve: { alias: { '@': path.resolve(root, 'src') } },
          optimizeDeps: { noDiscovery: true, include: [] },
        })
        const nav = await server.ssrLoadModule('/src/config/navigation.js')
        const { buildNavManifest } = await server.ssrLoadModule('/src/config/navManifest.js')
        const manifest = buildNavManifest(nav.MENU_GROUPS, nav.NAV_ENTRIES)
        fs.writeFileSync(path.join(outDir, 'nav-manifest.json'), JSON.stringify(manifest, null, 2))
        console.log(`[nav-manifest] ${manifest.entries.length} entries -> nav-manifest.json`)
      } catch (err) {
        console.warn(`[nav-manifest] export skipped: ${err.message}`)
      } finally {
        await server?.close()
      }
    },
  }
}
```

- [ ] **Step 9: 挂到 `frontend/vite.config.js`**

文件顶部 import 区加：

```js
import { navManifestPlugin } from './build/navManifestPlugin.js'
```

`plugins: [` 数组的 `vue(),` 下一行加：

```js
    navManifestPlugin(),
```

- [ ] **Step 10: 验证构建产出清单**

Run: `cd frontend && npm run build 2>&1 | grep nav-manifest && node -e "const m=require('./dist/nav-manifest.json');console.log(m.entries.length, m.entries.some(e=>e.key==='TaskCenter'))"`
Expected: 第一行 `[nav-manifest] N entries -> nav-manifest.json`（N > 50）。第二行现在输出 `N false`；Task 9 加入导航条目后重跑应为 `true`。

如果看到 `export skipped`，按报错定位（最常见的是 navigation.js 新增了非懒加载的 `.vue` 顶层 import），修好后再继续，不要带着 skipped 进入后续任务。

- [ ] **Step 11: Commit**

```bash
git add frontend/src/config/navManifest.js frontend/build/navManifestPlugin.js frontend/src/views/task/taskLabels.js frontend/src/views/task/taskTree.js frontend/tests/taskCenter.test.mjs frontend/vite.config.js frontend/package.json
git commit -m "feat(task): add nav manifest export and task tree helpers"
```

---

### Task 9: API 模块、导航条目、快速建任务浮层与两个入口

**Files:**
- Create: `frontend/src/api/task.js`、`frontend/src/composables/useQuickTask.js`、`frontend/src/components/task/QuickTaskPopover.vue`、`frontend/src/views/task/task-tags.css`
- Modify: `frontend/src/api/clients.js`、`frontend/src/config/navigation.js`、`frontend/src/views/layout/SidebarNavigation.vue`、`frontend/src/views/layout/MainLayout.vue`

弹层策略：浮层里的下拉和日期面板保持 Element 默认的 teleport 到 body（若渲染在浮层内部，会被浮层的滚动容器裁切）。因此需要：
- 浮层打开时用 Element 的 `useZIndex().nextZIndex()` 取层级。这样既能盖住详情抽屉，之后弹出的下拉面板层级也会更高。
- 「点浮层外关闭」要放过 `.el-popper`。
- 用 `visible-change` 计数「内层面板是否打开」。内层打开时按 Esc 只收起面板，不关浮层。

UI 债务门禁（`scripts/audit_frontend_ui.py`）：`.vue` 和 `.js` 里不许直接调用 `ElMessage` / `ElMessageBox`，一律用 `utils/feedback` 的 `msgSuccess` / `msgError` / `confirmDanger`；非危险的确认和输入走任务中心自己的 `TaskPromptDialog`（Task 10）。也不许新增 `:deep(.el-…)`。

- [ ] **Step 1: 在 `frontend/src/api/clients.js` 末尾登记 client**

```js
export const taskClient = createApiClient({ baseURL: '/api/task', timeout: 60000 })
```

- [ ] **Step 2: 写 `frontend/src/api/task.js`**

```js
// 任务中心 API（拦截器已校验信封，调用方取数用 res.data）
import { taskClient } from './clients'

// 页面自带骨架/占位，不弹全局 loading 遮罩
const quiet = { showLoading: false }

export const listTasks = () => taskClient.get('/items', quiet)
export const getTask = id => taskClient.get(`/items/${id}`, quiet)
export const createTask = data => taskClient.post('/items', data)
export const updateTask = (id, data) => taskClient.patch(`/items/${id}`, data, quiet)
// 状态变更自己处理 409（子任务未结束需二次确认），不走拦截器的通用 toast
export const changeTaskStatus = (id, data) => taskClient.post(`/items/${id}/status`, data, { suppressToast: true })
export const moveTask = (id, parentId) => taskClient.post(`/items/${id}/move`, { parent_id: parentId })
export const deleteTask = id => taskClient.delete(`/items/${id}`)
export const restoreTask = id => taskClient.post(`/items/${id}/restore`)
export const listTrash = () => taskClient.get('/trash', quiet)
export const addTaskLink = (id, data) => taskClient.post(`/items/${id}/links`, data, quiet)
export const removeTaskLink = linkId => taskClient.delete(`/links/${linkId}`, quiet)
export const getTaskStats = () => taskClient.get('/stats', quiet)
export const listTaskModules = () => taskClient.get('/modules', quiet)
export const addCustomModule = title => taskClient.post('/modules/custom', { title })
export const removeCustomModule = key => taskClient.delete(`/modules/custom/${encodeURIComponent(key)}`)
export const draftTask = data => taskClient.post('/ai/draft', data, { ...quiet, timeout: 90000 })
export const getTodayBrief = () => taskClient.get('/brief/today', { ...quiet, timeout: 90000 })
```

- [ ] **Step 3: 导航条目**：`frontend/src/config/navigation.js`

在第 16~22 行的 `@element-plus/icons-vue` import 列表末尾加上 `Finished,`。

在 `MENU_GROUPS` 对象最后一个分组之后加：

```js
  task: {
    title: '个人效率',
    icon: Finished,
    anyPermission: ['task:read', 'task:write'],
  },
```

在 `NAV_ENTRIES` 数组末尾（最后一个条目之后）加：

```js
  // ── 任务中心（个人任务，数据按本人隔离） ─────────────────────
  {
    path: '/task',
    name: 'TaskCenter',
    component: () => import('@/views/task/TaskCenter.vue'),
    title: '任务中心',
    anyPermission: ['task:read', 'task:write'],
    menu: {
      group: 'task', title: '任务中心', icon: Finished, order: 1,
      anyPermission: ['task:read', 'task:write'],
    },
  },
```

同时在 `frontend/src/views/system/composables/usePermissionMatrix.js` 里登记，否则角色管理页会把它显示成裸 `task`、归到「其他」：
- `MODULE_LABELS` 里 `training: '培训速递',` 下一行加 `task: '任务中心',`
- `ROW_GROUPS` 的「营销 · 展会与洞见」组里，`'training',` 改为 `'training', 'task',`

- [ ] **Step 4: 写 `frontend/src/composables/useQuickTask.js`**

```js
/**
 * 快速建任务浮层的全局单例状态。侧栏悬浮 +、页头「记任务」、任务中心页都通过
 * openQuickTask 打开同一个浮层（QuickTaskPopover 挂在 MainLayout）。
 * seq 每次打开自增：浮层已开着时换一个入口再点，也能重新初始化。
 */
import { reactive, ref } from 'vue'

const state = reactive({ open: false, seq: 0, anchor: null, moduleKey: null, parentId: null, source: 'manual' })
const lastCreatedId = ref(0)
let returnFocusEl = null

export function useQuickTask() {
  function openQuickTask({ anchorEl = null, moduleKey = null, parentId = null, source = 'manual' } = {}) {
    const rect = anchorEl?.getBoundingClientRect?.()
    returnFocusEl = anchorEl
    Object.assign(state, {
      open: true,
      seq: state.seq + 1,
      moduleKey,
      parentId,
      source,
      anchor: rect
        ? { top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left,
            side: anchorEl.closest?.('.aside') ? 'right' : 'below' }
        : null,
    })
  }

  function closeQuickTask() {
    if (!state.open) return
    state.open = false
    returnFocusEl?.focus?.()
    returnFocusEl = null
  }

  function notifyCreated(id) {
    lastCreatedId.value = id
  }

  return { quickTask: state, lastCreatedId, openQuickTask, closeQuickTask, notifyCreated }
}
```

- [ ] **Step 5: 写共享标签样式 `frontend/src/views/task/task-tags.css`**

```css
/* 任务中心状态/重要性标签（多个组件共用，非 scoped）。颜色只用 tokens.css 变量。 */
.task-code { font: 600 11.5px var(--font-mono); color: var(--text-muted); white-space: nowrap; }
.task-status {
  display: inline-flex; align-items: center; height: 24px; padding: 0 9px; border-radius: 6px;
  font: 600 12px var(--font-display); white-space: nowrap;
}
.task-status.is-todo { color: var(--text-secondary); background: var(--color-info-bg); }
.task-status.is-doing { color: var(--color-info-text); background: var(--color-info-bg); }
.task-status.is-blocked { color: var(--color-danger-text); background: var(--color-danger-bg); }
.task-status.is-pending { color: var(--color-warning-text); background: var(--color-warning-bg); box-shadow: inset 0 0 0 1px var(--color-primary-glow); }
.task-status.is-done { color: var(--color-success-text); background: var(--color-success-bg); }
.task-status.is-shelved { color: var(--text-muted); background: var(--color-info-bg); }
.task-prio { display: inline-flex; align-items: center; gap: 6px; font: 700 12px var(--font-display); white-space: nowrap; }
.task-prio::before { content: ""; width: 8px; height: 8px; border-radius: 3px; background: currentColor; }
.task-prio.is-P0 { color: var(--color-danger); }
.task-prio.is-P1 { color: var(--color-primary); }
.task-prio.is-P2 { color: var(--color-info-text); }
.task-prio.is-P3 { color: var(--text-muted); }
.task-due.is-overdue { color: var(--color-danger-text); font-weight: 600; }

/* 树形表格行态：行由 el-table 渲染，不带组件 scope，放在这里而不是 :deep */
.task-tree-table .el-table__row { cursor: pointer; }
.task-tree-table .el-table__row.is-pending > td { background: var(--color-warning-bg); }
.task-tree-table .el-table__row.is-closed .tt-title { color: var(--text-muted); text-decoration: line-through; }
```

- [ ] **Step 6: 写 `frontend/src/components/task/QuickTaskPopover.vue`**

```vue
<template>
  <Teleport to="body">
    <Transition name="quick-pop">
      <section
        v-if="quickTask.open"
        ref="panelRef"
        class="quick-task"
        :style="panelStyle"
        role="dialog"
        aria-labelledby="quick-task-title"
        @keydown="onKeydown"
      >
        <header class="quick-task__head">
          <h2 id="quick-task-title">{{ quickTask.parentId ? '加子任务' : '记任务' }}</h2>
          <span v-if="moduleLabel" class="quick-task__pill">
            {{ moduleLabel }}
            <button type="button" aria-label="取消预填模块" @click="clearModule">×</button>
          </span>
          <span v-else class="quick-task__pill is-muted">AI 自动识别模块</span>
          <button type="button" class="quick-task__close" aria-label="关闭" @click="closeQuickTask">×</button>
        </header>

        <el-input
          ref="textRef"
          v-model="text"
          type="textarea"
          :autosize="{ minRows: 3, maxRows: 6 }"
          maxlength="1000"
          placeholder="一句话说清要做什么，例如：回款列表按业务员筛选很慢，明天前搞定"
        />

        <p v-if="drafting" class="quick-task__thinking" aria-live="polite">
          <span class="quick-task__shimmer" />AI 正在补全标题、重要性和验收标准…
        </p>

        <div v-if="draft" class="quick-task__draft">
          <el-alert v-if="draft.notice" :title="draft.notice" type="warning" :closable="false" show-icon />
          <p v-if="draft.duplicates.length" class="quick-task__dup">
            可能和
            <template v-for="(d, i) in draft.duplicates" :key="d.id">{{ i ? '、' : '' }}<b>{{ d.code }} {{ d.title }}</b></template>
            重复，确认是新任务再创建
          </p>
          <el-form label-position="top">
            <el-form-item label="标题"><el-input v-model="draft.title" maxlength="200" /></el-form-item>
            <div class="quick-task__grid">
              <el-form-item label="重要性">
                <el-select v-model="draft.priority" @visible-change="trackInner">
                  <el-option v-for="p in PRIORITIES" :key="p" :value="p" :label="`${p} ${PRIORITY_META[p].label}`" />
                </el-select>
              </el-form-item>
              <el-form-item label="截止">
                <el-date-picker v-model="draft.due_date" type="date" value-format="YYYY-MM-DD" clearable class="quick-task__date" @visible-change="trackInner" />
              </el-form-item>
              <el-form-item label="关联模块">
                <el-select v-model="draft.module_key" filterable clearable placeholder="不关联" @visible-change="trackInner">
                  <el-option-group v-for="g in moduleGroups" :key="g.title" :label="g.title">
                    <el-option v-for="m in g.items" :key="m.key" :value="m.key" :label="m.title" />
                  </el-option-group>
                </el-select>
              </el-form-item>
              <el-form-item label="父任务">
                <el-select v-model="draft.parent_id" filterable clearable placeholder="顶层任务" @visible-change="trackInner">
                  <el-option v-for="p in parentOptions" :key="p.id" :value="p.id" :label="p.label" />
                </el-select>
              </el-form-item>
            </div>
            <el-form-item label="验收标准（每行一条）">
              <el-input v-model="acceptanceText" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
            </el-form-item>
          </el-form>
        </div>

        <footer class="quick-task__actions">
          <span class="quick-task__hint"><kbd>Ctrl</kbd>+<kbd>Enter</kbd> {{ draft ? '创建' : 'AI 补全' }} · <kbd>Esc</kbd> 关闭</span>
          <template v-if="draft">
            <GlassButton size="sm" :disabled="drafting || !hasText" @click="runDraft">重新补全</GlassButton>
            <GlassButton size="sm" variant="primary" :loading="saving" :disabled="!draft.title.trim()" @click="create(false)">创建任务</GlassButton>
          </template>
          <template v-else>
            <GlassButton size="sm" :disabled="drafting || saving || !hasText" @click="create(true)">直接创建</GlassButton>
            <GlassButton size="sm" variant="primary" :loading="drafting" :disabled="!hasText" @click="runDraft">AI 补全</GlassButton>
          </template>
        </footer>
      </section>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useZIndex } from 'element-plus'
import GlassButton from '@/components/GlassButton.vue'
import { createTask, draftTask, listTaskModules, listTasks } from '@/api/task'
import { useQuickTask } from '@/composables/useQuickTask'
import { msgSuccess } from '@/utils/feedback'
import { PRIORITIES, PRIORITY_META } from '@/views/task/taskLabels.js'
import { flattenForSelect } from '@/views/task/taskTree.js'

const WIDTH = 440
const EST_HEIGHT = 540
const { quickTask, closeQuickTask, notifyCreated } = useQuickTask()
const { nextZIndex } = useZIndex()

const panelRef = ref(null)
const textRef = ref(null)
const text = ref('')
const draft = ref(null)
const acceptanceText = ref('')
const moduleKey = ref(null)
const drafting = ref(false)
const saving = ref(false)
const modules = ref([])
const tree = ref([])
const zIndex = ref(2000)
const innerOpen = ref(0)   // 打开中的内层下拉/日期面板数：>0 时 Esc 只交给面板自己收起

const hasText = computed(() => Boolean(text.value.trim()))
const moduleLabel = computed(() => {
  const m = modules.value.find(x => x.key === moduleKey.value)
  return m ? `${m.group_title} · ${m.title}` : ''
})
const moduleGroups = computed(() => {
  const groups = new Map()
  for (const m of modules.value) {
    if (!groups.has(m.group_title)) groups.set(m.group_title, { title: m.group_title, items: [] })
    groups.get(m.group_title).items.push(m)
  }
  return [...groups.values()]
})
const parentOptions = computed(() => flattenForSelect(tree.value))

// 侧栏入口在菜单项右侧展开，页头/页面入口在按钮下方右对齐；都夹在视口内。
const panelStyle = computed(() => {
  const a = quickTask.anchor
  const vw = window.innerWidth
  const vh = window.innerHeight
  let left
  let top
  let origin
  if (!a) {
    left = (vw - WIDTH) / 2; top = 96; origin = 'center top'
  } else if (a.side === 'right') {
    left = a.right + 10; top = a.top - 8; origin = 'left top'
  } else {
    left = a.right - WIDTH; top = a.bottom + 8; origin = 'right top'
  }
  left = Math.max(12, Math.min(left, vw - WIDTH - 12))
  top = Math.max(12, Math.min(top, vh - EST_HEIGHT - 12))
  return {
    left: `${left}px`, top: `${top}px`, width: `${Math.min(WIDTH, vw - 24)}px`,
    transformOrigin: origin, zIndex: zIndex.value,
  }
})

function trackInner(visible) {
  innerOpen.value = Math.max(0, innerOpen.value + (visible ? 1 : -1))
}

// 每次打开都重取：新建的私有分类、刚建的任务都能立刻出现在下拉里
async function loadOptions() {
  const [m, t] = await Promise.all([listTaskModules(), listTasks()])
  modules.value = m.data
  tree.value = t.data
  if (moduleKey.value && !modules.value.some(x => x.key === moduleKey.value)) moduleKey.value = null
}

watch(() => quickTask.seq, async () => {
  if (!quickTask.open) return
  zIndex.value = nextZIndex()
  innerOpen.value = 0
  text.value = ''
  draft.value = null
  acceptanceText.value = ''
  moduleKey.value = quickTask.moduleKey
  await nextTick()
  textRef.value?.focus()
  loadOptions().catch(() => { /* 拦截器已提示；浮层仍可「直接创建」 */ })
})

function clearModule() {
  moduleKey.value = null
  if (draft.value) draft.value.module_key = null
}

async function runDraft() {
  if (!hasText.value || drafting.value) return
  drafting.value = true
  try {
    const res = await draftTask({ text: text.value, module_key: moduleKey.value, parent_id: quickTask.parentId })
    draft.value = { ...res.data }
    acceptanceText.value = (res.data.acceptance || []).join('\n')
  } finally {
    drafting.value = false
  }
}

async function create(raw) {
  if (saving.value || (raw ? !hasText.value : !draft.value?.title.trim())) return
  const payload = raw
    ? { title: text.value.trim().slice(0, 200), module_key: moduleKey.value, parent_id: quickTask.parentId, source: quickTask.source }
    : {
        title: draft.value.title.trim(),
        priority: draft.value.priority,
        due_date: draft.value.due_date || null,
        module_key: draft.value.module_key || null,
        parent_id: draft.value.parent_id || null,
        acceptance: acceptanceText.value.split('\n').map(line => line.trim()).filter(Boolean),
        source: quickTask.source,
      }
  saving.value = true
  try {
    const res = await createTask(payload)
    msgSuccess(`创建 T-${res.data.id} `)
    notifyCreated(res.data.id)
    closeQuickTask()
  } finally {
    saving.value = false
  }
}

function onKeydown(event) {
  if (event.key === 'Escape') {
    if (innerOpen.value) return
    event.stopPropagation()
    closeQuickTask()
  } else if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    if (draft.value) create(false)
    else runDraft()
  }
}

// 点浮层外关闭；放过：另一个入口按钮（交给 openQuickTask 重新初始化）、teleport 出去的下拉/日期面板、消息框
function onPointerDown(event) {
  if (!quickTask.open || panelRef.value?.contains(event.target)) return
  if (event.target.closest?.('[data-quick-task-trigger], .el-popper, .el-message-box, .el-overlay')) return
  closeQuickTask()
}
document.addEventListener('pointerdown', onPointerDown, true)
onBeforeUnmount(() => document.removeEventListener('pointerdown', onPointerDown, true))
</script>

<style scoped>
.quick-task {
  position: fixed;
  max-height: calc(100dvh - 24px);
  overflow-y: auto;
  padding: 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: 16px;
  background: var(--card-bg);
  box-shadow: 0 24px 60px rgba(20, 18, 16, 0.28);
}
.quick-task__head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.quick-task__head h2 { margin: 0; font: 700 14px var(--font-display); color: var(--text-primary); }
.quick-task__pill {
  display: inline-flex; align-items: center; gap: 6px; height: 24px; padding: 0 9px; border-radius: 6px;
  font-size: 12px; color: var(--color-warning-text); background: var(--color-gold-soft);
}
.quick-task__pill.is-muted { color: var(--text-muted); background: var(--color-info-bg); }
.quick-task__pill button, .quick-task__close { border: 0; background: none; color: inherit; cursor: pointer; }
.quick-task__close { margin-left: auto; width: 28px; height: 28px; border-radius: 8px; font-size: 18px; color: var(--text-muted); }
.quick-task__close:hover { background: var(--color-info-bg); }
.quick-task__thinking { display: flex; align-items: center; gap: 10px; margin: 12px 0 0; font-size: 12.5px; color: var(--text-secondary); }
.quick-task__shimmer {
  width: 80px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg, var(--color-info-bg), var(--color-gold-soft), var(--color-info-bg));
  background-size: 200% 100%; animation: quick-shimmer 1s linear infinite;
}
@keyframes quick-shimmer { to { background-position: -200% 0; } }
.quick-task__draft { margin-top: 12px; padding: 12px; border-radius: 12px; border: 1px solid var(--border-color); }
.quick-task__dup { margin: 0 0 10px; padding: 8px 10px; border-radius: 8px; font-size: 12px; color: var(--color-warning-text); background: var(--color-warning-bg); }
.quick-task__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
.quick-task__date { width: 100%; }
.quick-task__actions { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.quick-task__hint { margin-right: auto; font-size: 11.5px; color: var(--text-muted); }
.quick-task__hint kbd { padding: 0 4px; border: 1px solid var(--border-color); border-radius: 4px; font: 600 10.5px var(--font-mono); }

/* 起止动效：进 200ms、出 120ms，strong ease-out；从触发点方向缩放展开 */
.quick-pop-enter-active { transition: opacity 180ms cubic-bezier(0.23, 1, 0.32, 1), transform 200ms cubic-bezier(0.23, 1, 0.32, 1); }
.quick-pop-leave-active { transition: opacity 120ms ease, transform 120ms ease; }
.quick-pop-enter-from, .quick-pop-leave-to { opacity: 0; transform: scale(0.96); }
@media (prefers-reduced-motion: reduce) {
  .quick-pop-enter-from, .quick-pop-leave-to { transform: none; }
  .quick-task__shimmer { animation: none; }
}
@media (max-width: 480px) {
  .quick-task__grid { grid-template-columns: 1fr; }
}
</style>
```

- [ ] **Step 7: 侧栏悬浮 +**：修改 `frontend/src/views/layout/SidebarNavigation.vue`

(a) `<script setup>` 的 import 区加：

```js
import { useQuickTask } from '@/composables/useQuickTask'
```

`const searchQuery = ref('')` 上一行加：

```js
const { openQuickTask } = useQuickTask()

function quickAdd(event, item) {
  openQuickTask({ anchorEl: event.currentTarget, moduleKey: item.name, source: 'nav_quick' })
}
```

(b) `accessibleTopLevelItems` 的 `.map(entry => ({ path: entry.path, title: ..., icon: ... }))` 改为：

```js
  .map(entry => ({ path: entry.path, name: entry.name, title: entry.menu.title ?? entry.title, icon: entry.menu.icon })))
```

`accessibleGroups` 的 `.map(entry => ({ ... }))` 里，在 `path: entry.path,` 下一行加 `name: entry.name,`。

(c) 模板：顶层条目的 `<template #title>{{ item.title }}</template>` 改为：

```html
        <template #title>
          <span>{{ item.title }}</span>
          <button
            v-if="!collapsed && item.name"
            v-permission="'task:write'"
            type="button"
            class="nav-add"
            data-quick-task-trigger
            :aria-label="`为「${item.title}」记任务`"
            :title="`为「${item.title}」记任务`"
            @click.stop.prevent="quickAdd($event, item)"
          >+</button>
        </template>
```

分组内 `<el-menu-item v-else :index="item.path">` 的 `<template #title>` 里，在 `<span v-else>{{ item.title }}</span>` 之后加上同样的 `<button ...>+</button>`（与上面完全一致）。

(d) scoped 样式末尾（第一个 `<style scoped>` 的结束标签前）加：

```css
/* 任务中心：导航项悬浮 +（hover 高频出现，只做 120ms opacity + 轻微位移）。
   scoped 只给选择器最后一段 .nav-add 加作用域属性，祖先写 .el-menu-item 无需 :deep；
   el-menu-item 本身是 flex，按钮用 margin-left:auto 贴右，不需要改它的定位上下文。 */
.nav-add {
  display: grid;
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  margin-left: auto;
  place-items: center;
  border: 0;
  border-radius: 7px;
  background: rgba(245, 203, 92, 0.14);
  box-shadow: inset 0 0 0 1px rgba(245, 203, 92, 0.35);
  color: var(--color-gold);
  font: 600 15px/1 var(--font-display);
  cursor: pointer;
  opacity: 0;
  pointer-events: none;
  transform: translateX(4px);
  transition: opacity 120ms ease, transform 120ms cubic-bezier(0.23, 1, 0.32, 1), background-color 150ms ease;
}
.side-menu .el-menu-item:hover .nav-add,
.side-menu .el-menu-item:focus-within .nav-add,
.nav-add:focus-visible { opacity: 1; pointer-events: auto; transform: none; }
.nav-add:hover { background: rgba(245, 203, 92, 0.26); }
.nav-add:active { transform: scale(0.94); }
.nav-add:focus-visible { outline: 2px solid var(--color-gold); outline-offset: 1px; }
.side-menu .el-menu-item.is-active .nav-add { color: var(--card-bg); background: rgba(255, 255, 255, 0.3); box-shadow: none; }
@media (hover: none) { .nav-add { display: none; } }
```

- [ ] **Step 8: 页头「记任务」与全局挂载**：修改 `frontend/src/views/layout/MainLayout.vue`

(a) 模板：`<div class="header-badge">莱莎发制品</div>` 上一行加：

```html
          <GlassButton
            v-permission="'task:write'"
            class="header-quick-task"
            size="sm"
            left-icon="EditPen"
            data-quick-task-trigger
            @click="openHeaderQuickTask"
          >记任务</GlassButton>
```

(b) 模板最外层 `<el-container class="main-layout">` 的结束标签前加：

```html
    <QuickTaskPopover />
```

(c) `<script setup>` import 区加：

```js
import GlassButton from '@/components/GlassButton.vue'
import QuickTaskPopover from '@/components/task/QuickTaskPopover.vue'
import { useQuickTask } from '@/composables/useQuickTask'
import { NAV_ENTRIES } from '@/config/navigation'
```

（如果 MainLayout 已经 import 了 GlassButton 或 NAV_ENTRIES，就不要重复加。）

在 `const authStore = useAuthStore()` 下面加：

```js
const { openQuickTask } = useQuickTask()

// 预填当前页面对应的模块：详情等隐藏页按 activeMenu 找回它所属的导航页；浮层会校验模块是否在注册表里
function currentModuleKey() {
  const menuPath = route.meta.activeMenu || route.path
  return NAV_ENTRIES.find(entry => entry.menu && entry.path === menuPath)?.name ?? route.name ?? null
}

function openHeaderQuickTask(event) {
  openQuickTask({ anchorEl: event?.currentTarget, moduleKey: currentModuleKey(), source: 'header_quick' })
}
```

(d) scoped 样式里，在 `@media (max-width: 640px)` 或同类窄屏块中加 `.header-quick-task { display: none; }`；没有这个块就新建一个。窄屏的导航是抽屉形式，入口保留在任务中心页里。

- [ ] **Step 9: 构建验证**

Run: `cd frontend && npm run build 2>&1 | tail -5 && node -e "console.log(require('./dist/nav-manifest.json').entries.some(e=>e.key==='TaskCenter'))"`
Expected: 构建成功；输出 `true`

TaskCenter.vue 要到 Task 10 才创建。如果构建报 `Could not resolve '@/views/task/TaskCenter.vue'`，先建一个占位文件 `<template><div /></template>`，Task 10 再覆盖；或者直接接着做 Task 10，完成后再验证。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/clients.js frontend/src/api/task.js frontend/src/config/navigation.js frontend/src/composables/useQuickTask.js frontend/src/components/task/QuickTaskPopover.vue frontend/src/views/task/task-tags.css frontend/src/views/layout/SidebarNavigation.vue frontend/src/views/layout/MainLayout.vue
git commit -m "feat(task): add quick task popover with sidebar and header entries"
```

---

### Task 10: 任务中心页面壳、状态动作与简报卡

**Files:**
- Create: `frontend/src/views/task/TaskCenter.vue`、`frontend/src/views/task/composables/useTaskCenter.js`、`frontend/src/views/task/composables/useTaskDialog.js`、`frontend/src/views/task/components/TaskPromptDialog.vue`、`frontend/src/views/task/components/TaskBriefCard.vue`

- [ ] **Step 0a: 写 `frontend/src/views/task/composables/useTaskDialog.js`**（非危险确认与短输入的统一出口；UI 门禁禁止直接调用 ElMessageBox）

```js
/** 任务中心页内确认/输入对话框（单例，Promise 化）。ask() 返回 true / 输入值；取消返回 null。 */
import { reactive } from 'vue'

const DEFAULTS = { open: false, title: '', message: '', input: false, placeholder: '', confirmText: '确定', value: '', error: '', validate: null }
const dialog = reactive({ ...DEFAULTS })
let resolver = null

function settle(result) {
  dialog.open = false
  const resolve = resolver
  resolver = null
  resolve?.(result)
}

export function useTaskDialog() {
  function ask(options) {
    resolver?.(null)
    Object.assign(dialog, DEFAULTS, options, { open: true })
    return new Promise(resolve => { resolver = resolve })
  }

  function confirm() {
    if (!dialog.input) return settle(true)
    const value = dialog.value.trim()
    const error = dialog.validate?.(value) || ''
    if (error) {
      dialog.error = error
      return undefined
    }
    return settle(value)
  }

  return { dialog, ask, confirm, cancel: () => settle(null) }
}
```

- [ ] **Step 0b: 写 `frontend/src/views/task/components/TaskPromptDialog.vue`**

```vue
<template>
  <el-dialog :model-value="dialog.open" :title="dialog.title" width="480" append-to-body @update:model-value="onToggle">
    <p v-if="dialog.message" class="tpd-message">{{ dialog.message }}</p>
    <el-input
      v-if="dialog.input"
      v-model="dialog.value"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 4 }"
      maxlength="500"
      :placeholder="dialog.placeholder"
      @keydown.enter.ctrl.prevent="confirm"
    />
    <p v-if="dialog.error" class="tpd-error" role="alert">{{ dialog.error }}</p>
    <template #footer>
      <GlassButton @click="cancel">取消</GlassButton>
      <GlassButton variant="primary" @click="confirm">{{ dialog.confirmText }}</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'
import { useTaskDialog } from '../composables/useTaskDialog'

const { dialog, confirm, cancel } = useTaskDialog()

function onToggle(open) {
  if (!open) cancel()
}
</script>

<style scoped>
.tpd-message { margin: 0 0 12px; font-size: 13.5px; line-height: 1.6; color: var(--text-secondary); white-space: pre-line; }
.tpd-error { margin: 8px 0 0; font-size: 12.5px; color: var(--color-danger-text); }
</style>
```

- [ ] **Step 1: 写 `frontend/src/views/task/composables/useTaskCenter.js`**

```js
/** 任务中心页状态与动作：加载、筛选、视图切换（本机记忆）、状态变更（受阻原因 / 完成确认）、回收站、私有分类。 */
import { computed, reactive, ref, watch } from 'vue'
import {
  addCustomModule, changeTaskStatus, getTaskStats, getTodayBrief, listTaskModules, listTasks, listTrash,
  removeCustomModule, restoreTask,
} from '@/api/task'
import { currentBeijingDate } from '@/utils/datetime'
import { msgError, msgSuccess } from '@/utils/feedback'
import { STATUS_META } from '../taskLabels.js'
import { boardColumns, filterTree, moduleHeat, openDescendantCount, parentTitles } from '../taskTree.js'
import { useTaskDialog } from './useTaskDialog'

const VIEW_KEY = 'ark.task.view'
const VIEWS = ['tree', 'board', 'map']

function readView() {
  try {
    const saved = localStorage.getItem(VIEW_KEY)
    return VIEWS.includes(saved) ? saved : 'tree'
  } catch {
    return 'tree'
  }
}

export function errorMessage(err, fallback = '操作失败') {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return detail?.message || err?.response?.data?.message || fallback
}

export function useTaskCenter() {
  const { ask } = useTaskDialog()
  const tree = ref([])
  const modules = ref([])
  const stats = ref({ in_progress: 0, pending_confirm: 0, p0_open: 0, overdue: 0 })
  const brief = ref(null)
  const trash = ref([])
  const loading = ref(false)
  const briefLoading = ref(false)
  const version = ref(0)
  const today = ref(currentBeijingDate())
  const view = ref(readView())
  const filters = reactive({ q: '', moduleKey: '', priorities: [], hideClosed: true })

  watch(view, value => {
    try { localStorage.setItem(VIEW_KEY, value) } catch { /* 隐私模式不记忆，不影响使用 */ }
  })

  const modulesByKey = computed(() => Object.fromEntries(modules.value.map(m => [m.key, m])))
  const filteredTree = computed(() => filterTree(tree.value, filters))
  const columns = computed(() => boardColumns(tree.value, filters))
  const heat = computed(() => moduleHeat(tree.value, modules.value))
  const parentTitleMap = computed(() => parentTitles(tree.value))

  async function refresh() {
    loading.value = true
    try {
      const [t, s] = await Promise.all([listTasks(), getTaskStats()])
      tree.value = t.data
      stats.value = s.data
      today.value = currentBeijingDate()
      version.value += 1
    } finally {
      loading.value = false
    }
  }

  async function loadModules() {
    modules.value = (await listTaskModules()).data
  }

  async function loadBrief() {
    briefLoading.value = true
    try {
      brief.value = (await getTodayBrief()).data
    } catch {
      brief.value = null
    } finally {
      briefLoading.value = false
    }
  }

  async function loadAll() {
    await Promise.all([refresh(), loadModules(), loadBrief()])
  }

  // 设计文档第 3 节：任何未结束任务标记完成都要人确认；有未结束子任务时文案里说明
  async function confirmDone(task) {
    const open = openDescendantCount(tree.value, task.id)
    return ask({
      title: `确认 T-${task.id} 已完成？`,
      message: open ? `${task.title}\n还有 ${open} 个子任务没结束，它们会保持原状态。` : task.title,
      confirmText: '确认完成',
    })
  }

  async function setStatus(task, to) {
    // 「待确认」只能由 AI/代理提议：抽屉不提供该选项，看板拖入直接忽略
    if (!task || task.status === to || to === 'pending_confirm') return
    const payload = { status: to }
    if (to === 'blocked') {
      const reason = await ask({
        title: `T-${task.id} 受阻原因`,
        message: '写清楚卡在哪里，方便之后跟进',
        input: true,
        placeholder: '例如：等财务给 9 月汇率口径',
        confirmText: '标记受阻',
        validate: value => (value ? '' : '受阻原因必填'),
      })
      if (!reason) return
      payload.reason = reason
    }
    if (to === 'done') {
      if (!(await confirmDone(task))) return
      payload.confirm_open_children = true
    }
    try {
      await changeTaskStatus(task.id, payload)
    } catch (err) {
      msgError(errorMessage(err))
      return
    }
    msgSuccess(`T-${task.id} 改为「${STATUS_META[to].label}」`)
    await refresh()
  }

  async function loadTrash() {
    trash.value = (await listTrash()).data
  }

  async function restore(item) {
    await restoreTask(item.id)
    msgSuccess(`恢复 T-${item.id} `)
    await Promise.all([refresh(), loadTrash()])
  }

  async function addCustom() {
    const title = await ask({
      title: '新建方舟外分类',
      message: '例如：家里的事、副业、学习',
      input: true,
      confirmText: '新建',
      validate: value => (value && value.length <= 100 ? '' : '分类名称需为 1~100 个字'),
    })
    if (!title) return
    await addCustomModule(title)
    msgSuccess(`新建分类「${title}」`)
    await loadModules()
  }

  async function removeCustom(module) {
    const ok = await ask({
      title: `停用分类「${module.title}」？`,
      message: '已关联的任务保留原分类，只是不能再选它。',
      confirmText: '停用',
    })
    if (!ok) return
    await removeCustomModule(module.key)
    await loadModules()
  }

  function togglePriority(p) {
    const i = filters.priorities.indexOf(p)
    if (i >= 0) filters.priorities.splice(i, 1)
    else filters.priorities.push(p)
  }

  return {
    tree, modules, stats, brief, trash, loading, briefLoading, version, today, view, filters,
    modulesByKey, filteredTree, columns, heat, parentTitleMap,
    refresh, loadAll, loadBrief, setStatus, loadTrash, restore, togglePriority, addCustom, removeCustom,
  }
}
```

- [ ] **Step 2: 写 `frontend/src/views/task/components/TaskBriefCard.vue`**

```vue
<template>
  <section class="brief lg-card is-static" aria-label="今日简报">
    <div class="brief__meta">
      <h3><span class="brief__badge">{{ brief?.source === 'ai' ? 'AI' : '规则' }}</span>今日简报</h3>
      <p v-if="brief">{{ brief.brief_date.slice(5).replace('-', '/') }} · {{ brief.pushed_at ? '已推送钉钉' : '未推送' }}</p>
      <p v-else-if="loading">正在生成…</p>
      <p v-else>简报暂不可用，稍后刷新</p>
    </div>
    <ol v-if="brief?.top?.length" class="brief__list">
      <li v-for="(item, i) in brief.top" :key="item.id">
        <button type="button" @click="emit('open', item.id)">
          <span class="brief__n">{{ i + 1 }}</span>
          <span class="brief__body">
            <span class="brief__title"><span class="task-code">{{ item.code }}</span> {{ item.title }}</span>
            <span class="brief__why">{{ item.reason }}</span>
          </span>
        </button>
      </li>
    </ol>
    <p v-else-if="brief" class="brief__empty">没有未结束的任务，今天可以专注新想法。</p>
    <div v-if="brief" class="brief__counts">
      <div><b>{{ brief.pending_confirm }}</b><span>待确认</span></div>
      <div :class="{ 'is-alert': brief.overdue }"><b>{{ brief.overdue }}</b><span>逾期</span></div>
      <div :class="{ 'is-alert': brief.blocked }"><b>{{ brief.blocked }}</b><span>受阻</span></div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  brief: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['open'])
</script>

<style scoped>
.brief { display: grid; grid-template-columns: 200px 1fr auto; gap: 20px; align-items: start; padding: 16px 20px; }
.brief__meta h3 { display: flex; align-items: center; gap: 8px; margin: 0; font: 700 15px var(--font-display); }
.brief__meta p { margin: 6px 0 0; font-size: 12px; color: var(--text-muted); }
.brief__badge { padding: 2px 6px; border-radius: 6px; font: 700 11px var(--font-display); color: var(--card-bg); background: var(--sidebar-glass-from); }
.brief__list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.brief__list button {
  display: grid; grid-template-columns: 20px 1fr; gap: 10px; width: 100%; padding: 9px 12px;
  border: 0; border-radius: 12px; background: rgba(255, 255, 255, 0.55); text-align: left; cursor: pointer;
  transition: background-color 150ms ease, transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.brief__list button:hover { background: rgba(255, 255, 255, 0.9); }
.brief__list button:active { transform: scale(0.99); }
.brief__n { font: 800 15px var(--font-display); color: var(--color-primary); }
.brief__body { display: grid; gap: 2px; }
.brief__title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.brief__why { font-size: 12px; color: var(--text-secondary); }
.brief__empty { margin: 0; font-size: 13px; color: var(--text-secondary); }
.brief__counts { display: flex; gap: 8px; }
.brief__counts div { min-width: 64px; padding: 10px 12px; border-radius: 12px; background: var(--color-gold-soft); text-align: center; }
.brief__counts b { display: block; font: 800 20px var(--font-display); color: var(--color-warning-text); font-variant-numeric: tabular-nums; }
.brief__counts span { font-size: 11.5px; color: var(--color-warning-text); }
.brief__counts .is-alert { background: var(--color-danger-bg); }
.brief__counts .is-alert b, .brief__counts .is-alert span { color: var(--color-danger-text); }
@media (max-width: 960px) { .brief { grid-template-columns: 1fr; } }
</style>
```

- [ ] **Step 3: 写 `frontend/src/views/task/TaskCenter.vue`**

```vue
<template>
  <div class="task-center">
    <div class="task-center-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="tc-head">
      <div>
        <h2 class="tc-title">任务中心</h2>
        <p class="tc-sub">方舟开发需求与个人事项 · 仅本人可见 · 导航栏悬停 + 可随手记</p>
      </div>
      <div class="tc-stats">
        <div v-for="s in statCards" :key="s.key" class="tc-stat" :class="s.tone">
          <b>{{ stats[s.key] }}</b><span>{{ s.label }}</span>
        </div>
      </div>
    </header>

    <TaskBriefCard class="tc-block" :brief="brief" :loading="briefLoading" @open="openTask" />

    <section class="tc-toolbar tc-block lg-card is-static">
      <el-segmented v-model="view" :options="VIEW_OPTIONS" />
      <el-input v-model="filters.q" clearable placeholder="搜索标题 / T-编号" class="tc-search" />
      <el-select v-model="filters.moduleKey" clearable filterable placeholder="全部模块" class="tc-module">
        <el-option-group v-for="g in heat" :key="g.group_key" :label="g.group_title">
          <el-option v-for="m in g.items" :key="m.key" :value="m.key" :label="m.title" />
        </el-option-group>
      </el-select>
      <div class="tc-prios" role="group" aria-label="按重要性筛选">
        <el-check-tag v-for="p in PRIORITIES" :key="p" :checked="filters.priorities.includes(p)" @change="togglePriority(p)">{{ p }}</el-check-tag>
      </div>
      <el-checkbox v-model="filters.hideClosed">隐藏已结束</el-checkbox>
      <span class="tc-spacer" />
      <el-popover trigger="click" :width="380" placement="bottom-end" @show="loadTrash">
        <template #reference><GlassButton>回收站</GlassButton></template>
        <p v-if="!trash.length" class="tc-trash-empty">回收站是空的</p>
        <ul v-else class="tc-trash">
          <li v-for="item in trash" :key="item.id">
            <span class="task-code">T-{{ item.id }}</span><span class="tc-trash-title">{{ item.title }}</span>
            <el-button v-permission="'task:write'" link type="primary" @click="restore(item)">恢复</el-button>
          </li>
        </ul>
      </el-popover>
      <GlassButton v-permission="'task:write'" variant="primary" left-icon="Plus" data-quick-task-trigger @click="newTask">新建任务</GlassButton>
    </section>

    <section v-loading="loading && !tree.length" class="tc-block">
      <TaskTreeView
        v-if="view === 'tree'"
        :nodes="filteredTree"
        :modules-by-key="modulesByKey"
        :today="today"
        @open="openTask"
        @add-child="addChild"
      />
      <TaskBoardView
        v-else-if="view === 'board'"
        :columns="columns"
        :modules-by-key="modulesByKey"
        :parent-titles="parentTitleMap"
        :today="today"
        @open="openTask"
        @move="setStatus"
      />
      <TaskModuleMap v-else :groups="heat" @pick="pickModule" @add-custom="addCustom" @remove-custom="removeCustom" />
    </section>

    <TaskDetailDrawer
      v-model="drawerOpen"
      :task-id="selectedId"
      :refresh-key="version"
      :modules="modules"
      :tree="tree"
      @status="setStatus"
      @changed="refresh"
      @open="openTask"
      @add-child="addChild"
    />
    <TaskPromptDialog />
  </div>
</template>

<script setup>
import './task-tags.css'
import { onActivated, onMounted, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { useQuickTask } from '@/composables/useQuickTask'
import TaskBoardView from './components/TaskBoardView.vue'
import TaskBriefCard from './components/TaskBriefCard.vue'
import TaskDetailDrawer from './components/TaskDetailDrawer.vue'
import TaskModuleMap from './components/TaskModuleMap.vue'
import TaskPromptDialog from './components/TaskPromptDialog.vue'
import TaskTreeView from './components/TaskTreeView.vue'
import { useTaskCenter } from './composables/useTaskCenter'
import { PRIORITIES } from './taskLabels.js'

defineOptions({ name: 'TaskCenter' })

const VIEW_OPTIONS = [
  { label: '树形', value: 'tree' },
  { label: '看板', value: 'board' },
  { label: '模块地图', value: 'map' },
]
const statCards = [
  { key: 'in_progress', label: '进行中', tone: '' },
  { key: 'pending_confirm', label: '待确认完成', tone: 'is-gold' },
  { key: 'p0_open', label: 'P0 未结束', tone: 'is-red' },
  { key: 'overdue', label: '已逾期', tone: 'is-red' },
]

const {
  tree, modules, stats, brief, trash, loading, briefLoading, version, today, view, filters,
  modulesByKey, filteredTree, columns, heat, parentTitleMap,
  refresh, loadAll, setStatus, loadTrash, restore, togglePriority, addCustom, removeCustom,
} = useTaskCenter()
const { openQuickTask, lastCreatedId } = useQuickTask()

const drawerOpen = ref(false)
const selectedId = ref(null)

function openTask(id) {
  selectedId.value = id
  drawerOpen.value = true
}

function newTask(event) {
  openQuickTask({ anchorEl: event?.currentTarget, moduleKey: filters.moduleKey || null, source: 'manual' })
}

function addChild(task, event) {
  openQuickTask({ anchorEl: event?.currentTarget, moduleKey: task.module_key, parentId: task.id, source: 'manual' })
}

function pickModule(key) {
  filters.moduleKey = key
  view.value = 'tree'
}

watch(lastCreatedId, refresh)
onMounted(loadAll)
// 页面被多标签缓存（keep-alive）时，切回来刷新一次，吃到在别的页面用悬浮 + 建的任务；
// 首次挂载时 onActivated 也会触发，跳过它避免与 loadAll 重复请求
let activatedOnce = false
onActivated(() => {
  if (activatedOnce) refresh()
  activatedOnce = true
})
</script>

<style scoped>
.task-center { position: relative; }
.task-center-aurora { inset: -24px -28px; }
.tc-head, .tc-block { position: relative; z-index: 1; }
.tc-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.tc-title { margin: 0; font: 800 26px var(--font-display); color: var(--text-primary); }
.tc-sub { margin: 4px 0 0; font-size: 13px; color: var(--text-secondary); }
.tc-stats { display: flex; flex-wrap: wrap; gap: 10px; }
.tc-stat {
  min-width: 100px; padding: 10px 14px; border: 1px solid var(--dash-glass-border); border-radius: 14px;
  background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow);
}
.tc-stat b { display: block; font: 800 22px var(--font-display); font-variant-numeric: tabular-nums; }
.tc-stat span { font-size: 11.5px; color: var(--text-secondary); }
.tc-stat.is-gold b { color: var(--color-primary); }
.tc-stat.is-red b { color: var(--color-danger); }
.tc-block { margin-bottom: 14px; }
.tc-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 10px 12px; }
.tc-search { width: 200px; }
.tc-module { width: 200px; }
.tc-prios { display: flex; gap: 4px; }
.tc-spacer { flex: 1; }
.tc-trash { display: grid; gap: 6px; max-height: 320px; margin: 0; padding: 0; overflow-y: auto; list-style: none; }
.tc-trash li { display: flex; align-items: center; gap: 8px; }
.tc-trash-title { flex: 1; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.tc-trash-empty { margin: 0; font-size: 13px; color: var(--text-muted); }
@media (max-width: 640px) {
  .tc-search, .tc-module { width: 100%; }
  .tc-spacer { display: none; }
}
</style>
```

- [ ] **Step 4: 暂不构建**（三个视图组件和抽屉在 Task 11、12 创建，之后统一构建验证）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/task/TaskCenter.vue frontend/src/views/task/composables/useTaskCenter.js frontend/src/views/task/composables/useTaskDialog.js frontend/src/views/task/components/TaskPromptDialog.vue frontend/src/views/task/components/TaskBriefCard.vue
git commit -m "feat(task): add task center page shell, actions and brief card"
```

---

### Task 11: 树形、看板、模块地图三个视图

**Files:**
- Create: `frontend/src/views/task/components/TaskTreeView.vue`、`TaskBoardView.vue`、`TaskModuleMap.vue`

- [ ] **Step 1: 写 `frontend/src/views/task/components/TaskTreeView.vue`**

```vue
<template>
  <div class="task-tree lg-card is-static">
    <el-table
      :data="nodes"
      row-key="id"
      default-expand-all
      border
      class="list-table task-tree-table"
      :tree-props="{ children: 'children' }"
      :row-class-name="rowClass"
      @row-click="row => emit('open', row.id)"
    >
      <el-table-column label="任务" min-width="380">
        <template #default="{ row }">
          <span class="tt-cell">
            <span class="task-code">T-{{ row.id }}</span>
            <span class="tt-title">{{ row.title }}</span>
            <button
              v-permission="'task:write'"
              type="button"
              class="tt-add"
              data-quick-task-trigger
              @click.stop="emit('add-child', row, $event)"
            >+ 子任务</button>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="重要性" min-width="100" max-width="120">
        <template #default="{ row }">
          <span class="task-prio" :class="`is-${row.priority}`">{{ row.priority }} {{ PRIORITY_META[row.priority].label }}</span>
        </template>
      </el-table-column>
      <el-table-column label="关联模块" min-width="170" max-width="240" show-overflow-tooltip>
        <template #default="{ row }">{{ moduleLabel(row.module_key) }}</template>
      </el-table-column>
      <el-table-column label="状态 / 进度" min-width="160" max-width="200">
        <template #default="{ row }">
          <span class="tt-status">
            <span class="task-status" :class="`is-${STATUS_META[row.status].tone}`">{{ STATUS_META[row.status].label }}</span>
            <span v-if="row.progress" class="tt-progress">
              <el-progress :percentage="percent(row)" :show-text="false" :stroke-width="5" />
              {{ row.progress.done }}/{{ row.progress.total }}
            </span>
          </span>
        </template>
      </el-table-column>
      <el-table-column label="截止" min-width="80" max-width="100">
        <template #default="{ row }">
          <span class="task-due" :class="{ 'is-overdue': isOverdue(row, today) }">{{ row.due_date ? row.due_date.slice(5).replace('-', '/') : '—' }}</span>
        </template>
      </el-table-column>
      <template #empty>
        <p class="tt-empty">没有符合条件的任务，换个筛选或直接新建</p>
      </template>
    </el-table>
  </div>
</template>

<script setup>
import { CLOSED, PRIORITY_META, STATUS_META, isOverdue } from '../taskLabels.js'

const props = defineProps({
  nodes: { type: Array, required: true },
  modulesByKey: { type: Object, required: true },
  today: { type: String, required: true },
})
const emit = defineEmits(['open', 'add-child'])

function moduleLabel(key) {
  const m = props.modulesByKey[key]
  return m ? `${m.group_title} · ${m.title}` : (key ? '已停用模块' : '—')
}

function percent(row) {
  return row.progress.total ? Math.round((row.progress.done / row.progress.total) * 100) : 0
}

function rowClass({ row }) {
  return [
    row.status === 'pending_confirm' ? 'is-pending' : '',
    CLOSED.has(row.status) ? 'is-closed' : '',
  ].join(' ')
}
</script>

<style scoped>
/* 表格融入玻璃：用 Element 的 CSS 变量在容器上继承，不做 Element 内部类的深度覆盖（UI 门禁） */
.task-tree {
  overflow: hidden;
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
}
.tt-cell { display: inline-flex; align-items: center; gap: 8px; max-width: calc(100% - 24px); vertical-align: middle; }
.tt-title { overflow: hidden; font-size: 13.5px; text-overflow: ellipsis; white-space: nowrap; }
.tt-add {
  flex-shrink: 0; height: 24px; padding: 0 8px; border: 0; border-radius: 6px;
  background: var(--color-gold-soft); color: var(--color-warning-text); font-size: 12px; cursor: pointer;
  opacity: 0; transition: opacity 120ms ease;
}
.el-table__row:hover .tt-add, .tt-add:focus-visible { opacity: 1; }
@media (hover: none) { .tt-add { opacity: 1; } }
.tt-status { display: grid; gap: 4px; }
.tt-progress { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 6px; font-size: 11.5px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.tt-empty { margin: 24px 0; font-size: 13px; color: var(--text-muted); }
</style>
```

- [ ] **Step 2: 写 `frontend/src/views/task/components/TaskBoardView.vue`**

```vue
<template>
  <div class="task-board">
    <section
      v-for="col in BOARD_COLUMNS"
      :key="col"
      class="tb-col"
      :class="{ 'is-over': overCol === col }"
      :aria-label="STATUS_META[col].label"
      @dragover.prevent="overCol = col"
      @dragleave="onLeave($event)"
      @drop.prevent="onDrop(col)"
    >
      <header class="tb-head">{{ STATUS_META[col].label }}<span>{{ columns[col].length }}</span></header>
      <article
        v-for="task in columns[col]"
        :key="task.id"
        class="tb-card"
        :class="{ 'is-drag': dragId === task.id }"
        draggable="true"
        tabindex="0"
        @dragstart="dragId = task.id"
        @dragend="dragId = null; overCol = null"
        @click="emit('open', task.id)"
        @keydown.enter="emit('open', task.id)"
      >
        <div class="tb-top">
          <span class="task-code">T-{{ task.id }}</span>
          <span class="task-prio" :class="`is-${task.priority}`">{{ task.priority }}</span>
        </div>
        <div class="tb-title">{{ task.title }}</div>
        <div v-if="parentTitles.get(task.id)" class="tb-parent">↳ {{ parentTitles.get(task.id) }}</div>
        <div class="tb-foot">
          <span class="tb-module">{{ moduleLabel(task.module_key) }}</span>
          <span class="task-due" :class="{ 'is-overdue': isOverdue(task, today) }">{{ task.due_date ? task.due_date.slice(5).replace('-', '/') : '' }}</span>
        </div>
      </article>
      <p v-if="!columns[col].length" class="tb-empty">{{ col === 'pending_confirm' ? 'AI 提议完成后出现在这里' : '拖到这里' }}</p>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { BOARD_COLUMNS, STATUS_META, isOverdue } from '../taskLabels.js'

const props = defineProps({
  columns: { type: Object, required: true },
  modulesByKey: { type: Object, required: true },
  parentTitles: { type: Map, required: true },
  today: { type: String, required: true },
})
const emit = defineEmits(['open', 'move'])

const dragId = ref(null)
const overCol = ref(null)

function moduleLabel(key) {
  return props.modulesByKey[key]?.title ?? ''
}

function onLeave(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) overCol.value = null
}

// 完成确认、受阻原因都由 useTaskCenter.setStatus 统一处理；「待确认」列只接受 AI 提议，拖入忽略（列内有说明）
function onDrop(col) {
  const task = Object.values(props.columns).flat().find(t => t.id === dragId.value)
  dragId.value = null
  overCol.value = null
  if (!task || task.status === col || col === 'pending_confirm') return
  emit('move', task, col)
}
</script>

<style scoped>
.task-board { display: grid; grid-template-columns: repeat(5, minmax(200px, 1fr)); gap: 12px; align-items: start; overflow-x: auto; }
.tb-col {
  min-height: 320px; padding: 10px; border: 1px solid var(--dash-glass-border); border-radius: 16px;
  background: rgba(255, 255, 255, 0.4); transition: background-color 150ms ease, box-shadow 150ms ease;
}
.tb-col.is-over { background: rgba(255, 255, 255, 0.75); box-shadow: inset 0 0 0 2px var(--color-primary-glow); }
.tb-head { display: flex; justify-content: space-between; padding: 4px 6px 10px; font: 700 13px var(--font-display); }
.tb-head span { color: var(--text-muted); font-variant-numeric: tabular-nums; }
.tb-card {
  margin-bottom: 8px; padding: 11px 12px; border: 1px solid var(--dash-glass-border); border-radius: 12px;
  background: rgba(255, 255, 255, 0.88); box-shadow: 0 4px 12px rgba(146, 103, 24, 0.08); cursor: grab;
  transition: transform 200ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 200ms ease;
}
@media (hover: hover) and (pointer: fine) {
  .tb-card:hover { transform: translateY(-2px); box-shadow: 0 10px 22px rgba(146, 103, 24, 0.14); }
}
.tb-card.is-drag { opacity: 0.45; }
.tb-card:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.tb-top, .tb-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.tb-title { margin-top: 6px; font-size: 13px; font-weight: 600; line-height: 1.45; }
.tb-parent { margin-top: 4px; font-size: 11.5px; color: var(--text-muted); }
.tb-foot { margin-top: 8px; font-size: 11.5px; color: var(--text-secondary); }
.tb-module { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tb-empty { margin: 24px 0; font-size: 12px; color: var(--text-muted); text-align: center; }
</style>
```

- [ ] **Step 3: 写 `frontend/src/views/task/components/TaskModuleMap.vue`**

```vue
<template>
  <div class="module-map">
    <section v-for="g in groups" :key="g.group_key" class="mm-group lg-card is-static">
      <h3>{{ g.group_title }}<span>{{ g.open }} 项未结束</span></h3>
      <div v-for="m in g.items" :key="m.key" class="mm-row">
        <button type="button" class="mm-cell" @click="emit('pick', m.key)">
          <span class="mm-name">{{ m.title }}</span>
          <span v-if="m.hasP0" class="mm-p0" title="含 P0 任务" />
          <span class="mm-heat"><i :style="{ width: `${(m.open / max) * 100}%` }" /></span>
          <span class="mm-num">{{ m.open }}</span>
        </button>
        <button
          v-if="m.isPrivate"
          v-permission="'task:write'"
          type="button"
          class="mm-remove"
          :aria-label="`停用分类「${m.title}」`"
          @click="emit('remove-custom', m)"
        >×</button>
      </div>
      <el-button v-if="g.group_key === 'custom'" v-permission="'task:write'" link type="primary" class="mm-add" @click="emit('add-custom')">+ 新分类</el-button>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ groups: { type: Array, required: true } })
const emit = defineEmits(['pick', 'add-custom', 'remove-custom'])
const max = computed(() => Math.max(1, ...props.groups.flatMap(g => g.items.map(m => m.open))))
</script>

<style scoped>
.module-map { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
.mm-group { padding: 16px; }
.mm-group h3 { display: flex; justify-content: space-between; margin: 0 0 10px; font: 700 14px var(--font-display); }
.mm-group h3 span { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.mm-cell {
  display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; border: 0; border-radius: 10px;
  background: transparent; text-align: left; cursor: pointer; transition: background-color 150ms ease;
}
.mm-cell:hover { background: rgba(255, 255, 255, 0.8); }
.mm-name { flex: 1; font-size: 13px; color: var(--text-primary); }
.mm-p0 { width: 8px; height: 8px; border-radius: 50%; background: var(--color-danger); }
.mm-heat { width: 70px; height: 8px; overflow: hidden; border-radius: 4px; background: var(--color-info-bg); }
.mm-heat i { display: block; height: 100%; background: linear-gradient(90deg, var(--color-gold), var(--color-primary)); }
.mm-num { width: 22px; font: 700 13px var(--font-display); text-align: right; font-variant-numeric: tabular-nums; }
.mm-row { display: flex; align-items: center; gap: 4px; }
.mm-remove { width: 24px; height: 24px; border: 0; border-radius: 6px; background: transparent; color: var(--text-muted); cursor: pointer; }
.mm-remove:hover { background: var(--color-danger-bg); color: var(--color-danger-text); }
.mm-add { margin-top: 6px; }
</style>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/task/components/TaskTreeView.vue frontend/src/views/task/components/TaskBoardView.vue frontend/src/views/task/components/TaskModuleMap.vue
git commit -m "feat(task): add tree, board and module map views"
```

---

### Task 12: 详情抽屉

**Files:**
- Create: `frontend/src/views/task/components/TaskDetailDrawer.vue`

- [ ] **Step 1: 写 `frontend/src/views/task/components/TaskDetailDrawer.vue`**

```vue
<template>
  <DetailDrawer
    :model-value="modelValue"
    :title="detail ? `T-${detail.id}` : '任务详情'"
    :width="640"
    :loading="loading"
    @update:model-value="v => emit('update:modelValue', v)"
  >
    <template v-if="detail">
      <p v-if="detail.path.length" class="td-path">{{ detail.path.map(p => `${p.code} ${p.title}`).join(' › ') }}</p>
      <el-input v-model="form.title" maxlength="200" :input-style="TITLE_STYLE" :disabled="!canWrite" @change="save('title')" />
      <el-alert v-if="detail.status === 'blocked'" :title="`受阻：${detail.blocked_reason}`" type="error" :closable="false" class="td-alert" />

      <div class="td-fields">
        <label class="td-field">
          <span>状态</span>
          <el-select :model-value="detail.status" class="td-control" :disabled="!canWrite" @change="to => emit('status', detail, to)">
            <el-option v-for="s in userStatusOptions(detail.status)" :key="s" :value="s" :label="STATUS_META[s].label" :disabled="s === detail.status" />
          </el-select>
        </label>
        <label class="td-field">
          <span>重要性</span>
          <el-select v-model="form.priority" class="td-control" :disabled="!canWrite" @change="save('priority')">
            <el-option v-for="p in PRIORITIES" :key="p" :value="p" :label="`${p} ${PRIORITY_META[p].label}`" />
          </el-select>
        </label>
        <label class="td-field">
          <span>关联模块</span>
          <el-select v-model="form.module_key" class="td-control" filterable clearable placeholder="不关联" :disabled="!canWrite" @change="save('module_key')">
            <el-option v-if="form.module_key && !moduleKeys.has(form.module_key)" :value="form.module_key" label="已停用模块" disabled />
            <el-option-group v-for="g in moduleGroups" :key="g.title" :label="g.title">
              <el-option v-for="m in g.items" :key="m.key" :value="m.key" :label="m.title" />
            </el-option-group>
          </el-select>
        </label>
        <label class="td-field td-field--wide">
          <span>父任务</span>
          <el-select v-model="form.parent_id" class="td-control" filterable clearable placeholder="顶层任务" :disabled="!canWrite" @change="move">
            <el-option v-for="p in parentOptions" :key="p.id" :value="p.id" :label="p.label" :disabled="p.id === detail.id" />
          </el-select>
        </label>
        <label class="td-field">
          <span>截止</span>
          <el-date-picker v-model="form.due_date" class="td-control" type="date" value-format="YYYY-MM-DD" clearable :disabled="!canWrite" @change="save('due_date')" />
        </label>
      </div>

      <section class="td-sec">
        <h4>验收标准</h4>
        <el-input v-model="form.acceptanceText" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" :disabled="!canWrite"
          placeholder="每行一条。二期起 AI 提议完成时会逐条对照" @change="save('acceptance')" />
      </section>

      <section class="td-sec">
        <h4>描述</h4>
        <el-input v-model="form.description" type="textarea" :autosize="{ minRows: 2, maxRows: 10 }" :disabled="!canWrite"
          placeholder="背景、链接、想法都可以写在这里" @change="save('description')" />
      </section>

      <section class="td-sec">
        <h4>
          子任务<span v-if="detail.progress" class="td-count">{{ detail.progress.done }}/{{ detail.progress.total }}</span>
          <el-button v-permission="'task:write'" link type="primary" data-quick-task-trigger @click="emit('add-child', detail, $event)">+ 子任务</el-button>
        </h4>
        <button v-for="c in detail.children" :key="c.id" type="button" class="td-child" @click="emit('open', c.id)">
          <span class="task-code">T-{{ c.id }}</span><span class="td-child-title">{{ c.title }}</span>
          <span class="task-status" :class="`is-${STATUS_META[c.status].tone}`">{{ STATUS_META[c.status].label }}</span>
        </button>
        <p v-if="!detail.children.length" class="td-empty">没有子任务。超过一天的事，拆成子任务更好跟进</p>
      </section>

      <section class="td-sec">
        <h4>关联</h4>
        <div v-for="l in detail.links" :key="l.id" class="td-link">
          <span class="td-kind">{{ LINK_KIND_META[l.kind] }}</span>
          <a v-if="l.kind === 'url'" :href="l.ref" target="_blank" rel="noopener">{{ l.title }}</a>
          <code v-else :title="l.ref">{{ l.ref }}</code>
          <el-button v-permission="'task:write'" link @click="unlink(l)">移除</el-button>
        </div>
        <p v-if="!detail.links.length" class="td-empty">分支和 commit 自动关联在二期上线，现在可以手工挂文档或原型</p>
        <div v-permission="'task:write'" class="td-link-form">
          <el-select v-model="linkForm.kind" class="td-link-kind">
            <el-option v-for="(label, kind) in LINK_KIND_META" :key="kind" :value="kind" :label="label" />
          </el-select>
          <el-input v-model="linkForm.ref" :placeholder="linkForm.kind === 'url' ? 'https://...' : 'docs/requirements/...'" @keyup.enter="link" />
          <GlassButton size="sm" @click="link">添加</GlassButton>
        </div>
      </section>

      <section class="td-sec">
        <h4>时间线</h4>
        <ol class="td-timeline">
          <li v-for="e in detail.events" :key="e.id" :class="{ 'is-ai': e.actor === 'ai' }">
            <time>{{ formatBeijingShortDateTime(e.created_at) }}</time>{{ ACTOR_LABELS[e.actor] || e.actor }} {{ eventText(e) }}
          </li>
        </ol>
      </section>
    </template>

    <template #footer>
      <template v-if="detail">
        <GlassButton v-permission="'task:write'" variant="danger" @click="remove">删除</GlassButton>
        <GlassButton @click="copyBrief">复制代理任务书</GlassButton>
        <GlassButton v-if="detail.status === 'done' || detail.status === 'shelved'" v-permission="'task:write'" @click="emit('status', detail, 'todo')">重开</GlassButton>
        <GlassButton v-else v-permission="'task:write'" variant="primary" @click="emit('status', detail, 'done')">标记完成</GlassButton>
      </template>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { addTaskLink, deleteTask, getTask, moveTask, removeTaskLink, updateTask } from '@/api/task'
import { useAuthStore } from '@/stores/auth'
import { formatBeijingShortDateTime } from '@/utils/datetime'
import { confirmDanger, msgError, msgSuccess } from '@/utils/feedback'
import {
  ACTOR_LABELS, EVENT_LABELS, LINK_KIND_META, PRIORITIES, PRIORITY_META, STATUS_META, userStatusOptions,
} from '../taskLabels.js'
import { flattenForSelect } from '../taskTree.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  taskId: { type: Number, default: null },
  refreshKey: { type: Number, default: 0 },
  modules: { type: Array, default: () => [] },
  tree: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'status', 'changed', 'open', 'add-child'])

const TITLE_STYLE = { fontFamily: 'var(--font-display)', fontSize: '17px', fontWeight: 700 }
const FIELD_LABELS = { title: '标题', description: '描述', acceptance: '验收标准', priority: '重要性', module_key: '关联模块', due_date: '截止' }

const authStore = useAuthStore()
const canWrite = computed(() => authStore.hasPermission('task:write'))
const detail = ref(null)
const loading = ref(false)
const form = reactive({ title: '', priority: 'P2', module_key: null, parent_id: null, due_date: null, acceptanceText: '', description: '' })
// 可选父任务：未结束任务，自己禁选；成环与层数超限由后端校验并提示
const parentOptions = computed(() => flattenForSelect(props.tree))
const linkForm = reactive({ kind: 'doc', ref: '' })

const moduleKeys = computed(() => new Set(props.modules.map(m => m.key)))
const moduleGroups = computed(() => {
  const groups = new Map()
  for (const m of props.modules) {
    if (!groups.has(m.group_title)) groups.set(m.group_title, { title: m.group_title, items: [] })
    groups.get(m.group_title).items.push(m)
  }
  return [...groups.values()]
})

async function load() {
  if (!props.modelValue || !props.taskId) return
  loading.value = true
  try {
    const data = (await getTask(props.taskId)).data
    detail.value = data
    Object.assign(form, {
      title: data.title,
      priority: data.priority,
      module_key: data.module_key,
      parent_id: data.parent_id,
      due_date: data.due_date,
      acceptanceText: (data.acceptance || []).join('\n'),
      description: data.description || '',
    })
  } catch {
    detail.value = null
    emit('update:modelValue', false)
  } finally {
    loading.value = false
  }
}

watch(() => [props.modelValue, props.taskId, props.refreshKey], load)

async function save(field) {
  const value = field === 'acceptance'
    ? form.acceptanceText.split('\n').map(s => s.trim()).filter(Boolean)
    : (form[field] === '' ? null : form[field])
  try {
    await updateTask(detail.value.id, { [field]: value })
    emit('changed')
  } catch {
    await load()   // 拦截器已提示原因；回滚为服务器上的值
  }
}

async function move(parentId) {
  try {
    await moveTask(detail.value.id, parentId ?? null)
    emit('changed')
  } catch {
    await load()
  }
}

async function link() {
  if (!linkForm.ref.trim()) return
  await addTaskLink(detail.value.id, { kind: linkForm.kind, ref: linkForm.ref.trim() })
  linkForm.ref = ''
  await load()
}

async function unlink(item) {
  await removeTaskLink(item.id)
  await load()
}

async function remove() {
  try {
    await confirmDanger('删除', `T-${detail.value.id} ${detail.value.title}`, '子任务会一起进入回收站，可以在回收站恢复。')
  } catch {
    return
  }
  await deleteTask(detail.value.id)
  msgSuccess('删除')
  emit('update:modelValue', false)
  emit('changed')
}

function eventText(e) {
  const p = e.payload || {}
  if (e.type === 'status_changed') {
    const from = STATUS_META[p.from]?.label ?? p.from
    const to = STATUS_META[p.to]?.label ?? p.to
    return `${from} → ${to}${p.reason ? `：${p.reason}` : ''}`
  }
  if (e.type === 'updated') return `修改了${(p.fields || []).map(f => FIELD_LABELS[f] || f).join('、')}`
  if (e.type === 'created' && p.source === 'nav_quick') return '从导航栏悬浮 + 创建'
  if (e.type === 'created' && p.source === 'header_quick') return '从页头「记任务」创建'
  if (e.type === 'linked' || e.type === 'unlinked') return `${EVENT_LABELS[e.type]} ${p.ref}`
  return EVENT_LABELS[e.type] || e.type
}

async function copyBrief() {
  const d = detail.value
  const m = props.modules.find(x => x.key === d.module_key)
  const text = [
    `任务 ${d.code}：${d.title}`,
    `模块：${m ? `${m.group_title} / ${m.title}` : '未关联'}`,
    '验收标准：',
    ...((d.acceptance || []).length ? d.acceptance.map((a, i) => `${i + 1}. ${a}`) : ['（待补）']),
    `分支命名：<tool>/${d.code}-<slug>；commit message 带 ${d.code}。`,
    '完成后提议完成，不要自行标记完成。',
  ].join('\n')
  try {
    await navigator.clipboard.writeText(text)
    msgSuccess('复制代理任务书')
  } catch {
    msgError('浏览器不允许写剪贴板，请在抽屉里手动复制验收标准')
  }
}
</script>

<style scoped>
.td-path { margin: 0 0 6px; font-size: 12px; color: var(--text-muted); }
.td-alert { margin-top: 10px; }
.td-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.td-field { display: grid; gap: 4px; }
.td-field > span { font-size: 11.5px; color: var(--text-muted); }
.td-field--wide { grid-column: 1 / -1; }
.td-control { width: 100%; }
.td-sec { margin-top: 18px; }
.td-sec h4 {
  display: flex; align-items: center; gap: 8px; margin: 0 0 8px;
  font: 700 12px var(--font-display); letter-spacing: 0.06em; color: var(--text-muted);
}
.td-sec h4 .el-button { margin-left: auto; }
.td-count { color: var(--text-secondary); letter-spacing: 0; }
.td-child {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 7px 10px; border: 0; border-radius: 9px;
  background: transparent; text-align: left; cursor: pointer;
}
.td-child:hover { background: var(--color-info-bg); }
.td-child-title { flex: 1; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.td-empty { margin: 0; font-size: 12.5px; color: var(--text-muted); }
.td-link { display: flex; align-items: center; gap: 10px; padding: 8px 10px; margin-bottom: 6px; border: 1px solid var(--border-color); border-radius: 10px; font-size: 12.5px; }
.td-link code, .td-link a { flex: 1; overflow: hidden; font-family: var(--font-mono); text-overflow: ellipsis; white-space: nowrap; }
.td-kind { width: 36px; flex-shrink: 0; font: 700 11px var(--font-display); color: var(--text-muted); }
.td-link-form { display: flex; gap: 8px; margin-top: 8px; }
.td-link-kind { width: 90px; flex-shrink: 0; }
.td-timeline { display: grid; gap: 8px; margin: 0; padding: 0 0 0 14px; border-left: 2px solid var(--border-color); list-style: none; }
.td-timeline li { font-size: 12.5px; color: var(--text-secondary); }
.td-timeline li.is-ai { color: var(--color-warning-text); }
.td-timeline time { margin-right: 6px; font-size: 11.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
@media (max-width: 480px) { .td-fields { grid-template-columns: 1fr; } }
</style>
```

- [ ] **Step 2: 构建与纯函数测试**

Run: `cd frontend && npm run test:task-center && npm run build 2>&1 | tail -4`
Expected: 测试 `# fail 0`；构建成功，并输出 `[nav-manifest] N entries`

Run: `cd .. && $ARK_PY scripts/audit_frontend_ui.py --baseline-ref HEAD`
Expected: `0 failure(s)` 或无输出退出码 0。常见失败与改法：`message_calls`（改用 utils/feedback 或 TaskPromptDialog）、`deep_el_override`（改用容器 CSS 变量 / 组件根 class / 非 scoped 的 task-tags.css）、`table misses border / list-table`、`column uses fixed width`（改 min-width）。**禁止用 `--write-baseline` 抬高基线来过门禁。**

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/task/components/TaskDetailDrawer.vue
git commit -m "feat(task): add task detail drawer"
```

---

### Task 13: 文档同步

**Files:**
- Modify: `docs/api-reference.md`、`docs/database.md`、`docs/module-notes.md`、`docs/handoff.md`、`docs/superpowers/specs/2026-09-30-task-center-design.md`

- [ ] **Step 1: `docs/api-reference.md`** 按文件现有的模块小节格式，新增「任务中心 `/api/task`」一节，列出 Task 7 router 的 17 个端点（方法、路径、权限、一句话说明）。权限列：GET 为 `task:read` 或 `task:write`，其余为 `task:write`。

- [ ] **Step 2: `docs/database.md`** 按现有格式新增 `ark_task_modules`、`ark_task_items`、`ark_task_links`、`ark_task_events`、`ark_task_briefs` 五张表，字段与注释照 Task 1 迁移抄写，并注明迁移 `172_task_center`。

- [ ] **Step 3: `docs/module-notes.md`** 新增「任务中心」一节，写这四条踩坑与约束：
  1. 模块注册表只由构建期 `nav-manifest.json` 同步，只有 `TASK_MODULE_SYNC_ENABLED=true` 的生产环境才写库；浏览器不参与同步。
  2. 模块键 = 前端路由 `name`；改路由 name 会让旧任务的模块引用失效（注册表中置 inactive，任务保留引用）。
  3. `done` 只允许用户写入；AI/MCP 只能提议 `pending_confirm`（二期起用）。
  4. 回收站按 `deleted_at`（微秒）识别同批删除的子树。

- [ ] **Step 4: `docs/handoff.md`** 在当前进度区加一条：任务中心一期代码在分支 `claude/task-center`，待合并；部署时需在生产 `backend/.env` 加 `TASK_MODULE_SYNC_ENABLED=true`，并给亮哥的角色分配 `task:read`、`task:write`。二期（git 上报器）和三期（MCP）未启动。

- [ ] **Step 5: 设计文档**：在 `docs/superpowers/specs/2026-09-30-task-center-design.md` 第 6 节「简报推送到亮哥的钉钉，同时在工作台注册一张卡片」这句后面补一句：「工作台卡片推迟到二期，与 git 推进一起做；一期简报显示在任务中心页顶部」。

- [ ] **Step 6: Commit**

```bash
git add docs/api-reference.md docs/database.md docs/module-notes.md docs/handoff.md docs/superpowers/specs/2026-09-30-task-center-design.md
git commit -m "docs(task): document task center API, tables and phase 1 status"
```

---

### Task 14: 收尾验证

**Files:** 无新增（只修验证中暴露的问题）

- [ ] **Step 1: 后端全部任务测试 + 约定检查**

Run: `cd backend && $ARK_PY -m pytest tests/test_task_models.py tests/test_task_modules.py tests/test_task_service.py tests/test_task_state.py tests/test_task_ai.py tests/test_task_brief.py tests/test_task_api.py -q`
Expected: 全部 passed

Run: `cd .. && $ARK_PY scripts/check_conventions.py; echo exit=$?`
Expected: `exit=0`。该脚本会先跑 `audit_frontend_ui.py --baseline-ref HEAD`，这一关必须通过，不允许改 `scripts/ui_debt_baseline.json` 抬基线。其余黄项逐条判断：不是本次引入的注明「既有」，是本次引入的就修掉。

- [ ] **Step 2: 后端全量回归（SQLite，不连库）**

Run: `cd backend && $ARK_PY -m pytest -q -x --ignore=tests/test_ai_gateway_mysql.py 2>&1 | tail -3`
Expected: 与 main 分支同一命令的结果一致（先在主目录跑一次 main 作基线；凡是连 MySQL 的测试按前置约束 1 一律跳过，不在本分支运行）。

- [ ] **Step 3: 前端测试与构建**

Run: `cd frontend && npm run test:task-center && npm run build 2>&1 | tail -4`
Expected: `# fail 0`；构建成功；`dist/nav-manifest.json` 存在且包含 `TaskCenter`

- [ ] **Step 4: 真机走查**（本地 `start.bat` 启动）

⚠️ 本地后端连的是共享库：建表前页面接口会 500。按前置约束，**不在开发机执行迁移**。走查分两步：
- 开发机只验证不依赖数据的部分：侧栏悬停出现 `+`；点 `+` 浮层从菜单项右侧展开且模块已预填；页头「记任务」在当前页面预填模块；Esc 关闭后焦点回到触发按钮；窄屏（400px）页面不横向溢出。
- 数据流程（创建 → 树形出现 → 抽屉改状态 → 子任务未结束的二次确认 → 看板拖到已完成要确认 → 模块地图跳转筛选 → 删除与回收站恢复 → AI 草稿与降级）放到部署后在生产验收，写进 handoff 的验收清单。

- [ ] **Step 5: 动效自查**

对照 `~/.claude/skills/review-animations/STANDARDS.md` 检查以下几处：浮层起止动效（200ms 进 / 120ms 出，origin-aware，reduced-motion 时去掉位移）、侧栏 `+`（120ms，只动 opacity 和 transform）、看板卡片 hover（仅 `hover: hover` 设备）。发现问题用 Before/After 表格记录并修正。

- [ ] **Step 6: git 巡检**

Run: `cd .. && $ARK_PY scripts/git_sweep.py --no-fetch`
Expected: `claude/task-center` 显示为「未合并」，其他分支没有新增欠账；迁移编号不撞号。

- [ ] **Step 7: 对抗性审查**

派独立 Agent 审查 `git diff main...claude/task-center`，重点看：owner 隔离有没有遗漏（尤其 `remove_link` 和 `restore_task`）、状态机与设计文档的矩阵是否一致、浮层点外关闭与 Element 弹层的交互、导航清单导出失败时的降级。确认的问题修复后单独提交。

- [ ] **Step 8: 汇报**

向亮哥报告：分支名、提交列表、测试与构建结果、未在开发机验证的数据流程清单，以及部署前需要的三件事（生产 `.env` 加开关、角色分配 `task:*` 权限、部署入口执行 `172_task_center` 迁移）。合并和 push 等亮哥授权。
