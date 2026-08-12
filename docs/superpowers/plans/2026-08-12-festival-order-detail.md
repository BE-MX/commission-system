# 采购节数据明细 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在订单管理中提供按权限隔离、与采购节大屏同口径的新签/首返/复购订单明细与个人或全公司指标。

**Architecture:** 在现有 `app.festival` 领域增加专用查询服务和登录态路由，复用 `service.py` 的活动常量、标记和参赛名册规则。前端新增独立 API 模块、列表页及 composable；后端统一解析数据范围，汇总与分页列表共享同一过滤条件。

**Tech Stack:** FastAPI、SQLAlchemy text SQL、Pytest、Vue 3、Element Plus、Vitest/Node tests、Vite。

---

### Task 1: 权限元数据与后端数据范围

**Files:**
- Modify: `backend/app/auth/service.py`
- Create: `backend/app/festival/order_service.py`
- Test: `backend/tests/test_festival_order_api.py`

- [ ] 写失败测试：`seed_role_permissions` 生成 `festival_order:read` page 权限与 `festival_order:read_all` data 权限；普通用户从有效 OKKI 绑定解析本人范围，未绑定抛出 422；管理员允许全公司及参赛业务员范围，拒绝非参赛 ID。
- [ ] 运行 `pytest -q backend/tests/test_festival_order_api.py`，确认因权限码和服务函数不存在而失败。
- [ ] 在 `_DATA_KIND_CODES` 注册 `festival_order:read_all`，在权限 seeds 增加两个权限。
- [ ] 在 `order_service.py` 实现 `resolve_scope(db, current_user, requested_user_id)`，只依赖 `ArkUserExternalBinding` 与采购节有效名册。
- [ ] 重跑测试并提交 `feat(festival): add order detail data scope`。

### Task 2: 三类订单查询与汇总

**Files:**
- Modify: `backend/app/festival/order_service.py`
- Test: `backend/tests/test_festival_order_api.py`

- [ ] 写失败测试：固定活动窗口、必选列、参赛排除、关键词、分页、首返回去重客户数、复购客户池及金额。
- [ ] 写失败测试：同一新签客户多订单取最高来源积分，积分归属最早订单，其余为 0 且带说明；列表积分合计等于采购节榜单积分。
- [ ] 运行目标测试确认业务断言失败。
- [ ] 用共享 SQL 片段实现 `get_summary` 与 `list_orders`；客户名称关联 `customer_info`，人员信息关联 `user_rel_team`，所有稳定排序以 `account_date` 和订单 ID/订单号兜底。
- [ ] 重跑测试并提交 `feat(festival): query festival order details`。

### Task 3: 登录态 API

**Files:**
- Modify: `backend/app/festival/router.py`
- Modify: `backend/app/routers.py`（仅在现有 festival prefix 未覆盖时）
- Test: `backend/tests/test_festival_order_api.py`
- Modify: `docs/api-reference.md`

- [ ] 写失败 API 测试：`GET /api/festival/orders/summary` 和 `/orders` 必须要求 `festival_order:read`，普通用户篡改 `user_id` 无效，`read_all` 默认全公司并可筛选。
- [ ] 运行 API 测试确认 404/权限失败。
- [ ] 在现有 `/api/festival` 登录态 router 增加两个 GET 端点，使用统一 `ok()` 信封和 Query 约束。
- [ ] 更新 API 文档，重跑测试并提交 `feat(festival): expose order detail endpoints`。

### Task 4: 前端 API 与页面状态编排

**Files:**
- Create: `frontend/src/api/festivalOrder.js`
- Create: `frontend/src/views/invoice/composables/useFestivalOrderDetail.js`
- Test: `frontend/tests/festivalOrderDetail.test.mjs`

- [ ] 写失败测试：管理员范围切换会刷新 summary 和当前标签列表；业务员没有选择器；标签、搜索、分页参数正确；失败时保留旧 summary。
- [ ] 运行 `node --test frontend/tests/festivalOrderDetail.test.mjs` 确认模块不存在而失败。
- [ ] 用 `createApiClient({ baseURL: '/api/festival' })` 实现两个调用；composable 管理 loading、scope、tab、keyword、pagination，并隔离 summary 与 list 错误更新。
- [ ] 重跑测试并提交 `feat(festival): add order detail page state`。

### Task 5: 页面、导航与权限

**Files:**
- Create: `frontend/src/views/invoice/FestivalOrderDetail.vue`
- Create: `frontend/src/views/invoice/festival-order-detail.css`
- Modify: `frontend/src/config/navigation.js`
- Test: `frontend/tests/festivalOrderDetail.test.mjs`

- [ ] 写失败静态/状态测试：路由 `/invoice/festival-orders`、菜单“采购节数据明细”、权限 `festival_order:read`、三张指标卡、三个标签页、七个必选列与新签积分列存在。
- [ ] 运行测试确认页面和导航缺失。
- [ ] 实现已确认草图：管理员业务员选择器、指标卡、标签页、关键词工具栏、服务端分页表格；使用全局 liquid glass 与 List Page Spec，不增加裸 hex。
- [ ] 增加失败提示，保证失败不清空旧指标；不增加高频位移动画。
- [ ] 重跑测试并提交 `feat(festival): add order detail workspace`。

### Task 6: 完整验证与对抗审查

**Files:**
- Modify only files required by findings.

- [ ] 运行 `pytest` 完整后端套件。
- [ ] 运行前端测试与 `npm run build`。
- [ ] 运行 `python scripts/check_conventions.py --base $(git merge-base main HEAD)` 与 `git diff --check`。
- [ ] 用管理员和普通业务员测试身份请求两个 API，并在开发页面核对权限、筛选、三类合计和新签积分归属。
- [ ] 从边界条件、权限绕过、分页稳定性、口径一致性和前后端契约五个角度独立审查，修复 P1/P2。
- [ ] 运行 `python scripts/git_sweep.py`，提交收尾修复并推送 feature 分支。
