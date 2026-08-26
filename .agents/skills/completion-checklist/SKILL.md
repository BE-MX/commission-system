---
name: completion-checklist
description: 开新领域模块、或改动收尾自查时使用。给出新模块 9 步 checklist（迁移→四件套→权限→前端→导航→标杆页→测试→文档）、完工 DoD 验收项、以及对抗性审查的触发标准与固定审查视角。
---

# 流程检查清单（2026-07-03 治理落地，配合 AGENTS.md 宪法使用）

## 新模块 Checklist（开新领域模块照此走完，漏一步都算未完成）

1. Alembic 迁移（revision ≤32 字符，创建后立即 `git add`）
2. `app/<domain>/`：models → schemas → service → router（每端点权限 Depends + `ok()` 信封）
3. `app/routers.py` 注册 + `seed_role_permissions` 加权限码（read/write/admin 三档起步）
4. 前端 `api/<domain>.js`（走 createApiClient，clients.js 登记）
5. `navigation.js` 加 entry（permission 声明；全屏页在 router/index.js 顶层注册）
6. 列表页复制 `system/DictManagement.vue` 标杆
7. 核心计算 / 状态流转写测试（管钱管货的必须有）
8. 文档三处：`docs/api-reference.md` 加端点、`docs/database.md` 加表、auto-memory 建 `project_<domain>.md`
9. 跑 `python scripts/check_conventions.py` + `pytest` + `npm run build`

## 完工 DoD

- check_conventions 无红项；测试/构建通过并**贴出实际输出**
- 涉及 UI 对照 DESIGN.md；新增文件 <500 行或已拆 composable
- 上传/文件路径锚定 REPO_ROOT（cerebrum 2026-07-03 条目）
- 新增或修改时间字段时，业务时间必须经后端 `app.core.time`、主站 `utils/datetime.js`、PM 站/小程序各自的北京时间工具统一读写；技术性 UTC 例外必须登记到 `scripts/check_conventions.py` 白名单，并补非东八区运行环境和北京零点边界测试

## 对抗性审查触发标准（满足任一即派独立 agent）

- 跨 3 个以上文件的改动
- 涉及提成、发票、回款、库存数量的逻辑
- 状态机变更（batch 状态流 / 订单状态 / 会话状态等）
- 迁移脚本

审查 agent 固定视角：边界条件、并发写、幂等性、前后端契约一致、被修改函数的全部调用方。
