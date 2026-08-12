# 采购节数据明细页设计

## 目标

在“订单管理”下新增“采购节数据明细”页面，让业务员解释并核对采购节看板数字，让管理员查看全公司并下钻到指定参赛业务员。页面直接读取 `lsordertest.okki_orders`，与采购节大屏共享业务口径，不建立第二套统计规则。

## 范围与固定口径

- 三个标签页：新签订单、首返订单、复购订单。
- 新签窗口固定为 2026-08-01 至 2026-08-31。
- 首返与复购窗口固定为 2026-08-01 至 2026-09-30。
- 全部统计仅包含采购节有效参赛名册，继续使用采购节现有离职排除规则。
- 必选列：`order_no`、`account_date`、`amount_usd`、`company_name`、`user_name`、所属团队、所属阵营。
- 页面顶部显示新签客户完成进度、首返客户数、复购金额。
- 新签完成进度以“去重新签客户数 / `user_rel_team.newclient_t` 目标数”为准；积分只作为辅助值，不用积分除以客户目标。

## 数据关联

- 订单事实：`lsordertest.okki_orders`。
- 客户名称：`okki_orders.company_id = customer_info.company_id`。
- 业务员、团队、阵营和个人目标：`okki_orders.user_id = user_rel_team.user_id`。
- 登录用户到 OKKI 业务员：`ark_user_external_bindings` 中 `provider='okki'`、有效且未删除的绑定。
- 所有关联使用稳定 ID，不使用人员姓名或公司名称匹配。

## 业务规则

### 新签

- 复用采购节 `NEW_SIGN_MARK` 与通用订单过滤条件。
- 标签页保留窗口内全部有效新签订单。
- 同一 `company_id` 只计一次积分，取该客户所有新签订单中的最高来源积分。
- 该客户的积分展示在最早一笔新签订单上；按 `account_date`、稳定订单主键排序决定最早订单。
- 同客户其余订单显示积分 0 和“同客户已计分”，保证列表积分求和与看板一致。

### 首返

- 复用采购节 `FIRST_RETURN_MARK` 与通用订单过滤条件。
- 标签页保留全部符合首返标记的订单。
- 顶部首返客户数按 `company_id` 去重。

### 复购

- 复用采购节 `RE_MARK` 和客户池规则：当前复购客户从 2025-01-01 起必须存在相同 `company_id` 的有效新签订单。
- 标签页保留全部符合规则的复购订单。
- 顶部复购金额为这些订单的 `amount_usd` 合计。

## 权限与数据范围

- `festival_order:read`：页面和接口读取权限。
- `festival_order:read_all`：全公司数据范围权限，权限元数据 `kind=data`。
- `super_admin` 等同拥有 `read_all`。
- 普通业务员后端强制使用其 OKKI 绑定；客户端传入 `user_id` 必须被忽略。
- 普通业务员没有有效 OKKI 绑定时返回明确业务错误，引导至“系统管理 → 外部账号绑定”，不得返回伪装成 0 的空统计。
- 管理员默认查看全公司，可选择有效参赛业务员；任意非参赛 `user_id` 均被拒绝。
- 管理员查看全公司不要求自身存在 OKKI 绑定。

## API

### `GET /api/festival/orders/summary`

参数：可选 `user_id`，仅 `read_all` 或 `super_admin` 生效。

返回：

- `scope`: `self | all | user`
- `selected_user_id`、`selected_user_name`
- `can_read_all`
- `users`: 管理员可选的有效参赛业务员列表
- `new_sign`: `count`、`target`、`progress_percent`、`points`
- `first_return_count`
- `repurchase_amount`
- 三类固定窗口

### `GET /api/festival/orders`

参数：

- `type=new_sign|first_return|repurchase`
- `page`、`page_size`
- 可选 `keyword`，只匹配订单号或客户名称
- 可选 `user_id`，数据范围规则同汇总接口

返回标准分页结构：`items`、`total`、`page`、`page_size`。新签行额外包含 `points` 和 `points_note`。

## 页面设计

- 路由：`/invoice/festival-orders`，菜单归属“订单管理”。
- 管理员右上角显示业务员选择器，默认“全公司”；普通业务员不显示选择器。
- 三张指标卡位于表格上方；切换管理员范围时同步刷新指标和当前标签列表。
- 三个标签页共用关键词搜索、分页和加载状态。
- 表格使用项目 List Page Spec：`.table-card`、`.list-table`、`border`、无斑马纹、列左对齐、`min-width/max-width`。
- 请求失败保留当前标签与筛选条件，不把旧指标清零；显示可执行的错误信息。
- 高频标签切换不添加位移动画，只使用现有 Element Plus 状态反馈和短颜色过渡。

## 错误处理

- 未绑定 OKKI：422，明确告知配置路径。
- 无页面权限：403。
- 非 `read_all` 传 `user_id`：忽略并锁定本人。
- 管理员传入非参赛用户：422。
- 非法标签类型：FastAPI 参数校验返回 422。
- 查询失败由统一 API 错误处理呈现，前端不以空数据掩盖故障。

## 测试与验收

- 普通业务员只能看到本人；篡改 `user_id` 无效。
- `festival_order:read_all` 与 `super_admin` 可看全公司和指定参赛业务员。
- 未绑定账号、非参赛筛选、离职排除均有测试。
- 新签同客户多订单只计一次最高积分并归到最早订单。
- 三类明细聚合与现有采购节统计口径一致。
- 搜索、分页、空数据和非法类型正确。
- 前端覆盖权限决定的筛选器可见性、范围切换、标签切换、分页搜索和错误不清零。
- 完工执行完整后端测试、前端测试、前端构建、`scripts/check_conventions.py`，并用普通业务员与管理员两种身份做开发环境验证。
