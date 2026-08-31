# 统一客户经营 · 项目记忆

最后核实：2026-08-31

## 不可变决策

- 客户主档是公司/商业账户，唯一主键为方舟 `customer_id`。
- `company_name` 必须作为可版本化属性保存，但允许为空，不是身份唯一键。
- 个人邮箱、个人姓名或社媒账号先归联系人/触点；只能用公开商业证据反查任职公司，证据不足保持 provisional，禁止私人关系调查。
- 方舟是唯一真相源。阿里、OKKI、Google、官网、独立站、LinkedIn 和其他社媒只作为来源；生产 Agent 将信息事实化后写入方舟，消费 Agent 只读方舟。
- 客户档案采用来源 → 身份 → 事实/冲突 → 档案版本 → Agent 上下文的分层结构。事实必须有证据、置信度、方法版本、分类和可见范围。
- 一个客户同一时刻最多一个有效主负责人；无负责人表示公海，但可领取状态需要实时校验资格、DNC、冲突、冷却、团队和额度。
- 合并、拆分、归属变更、DNC 和重大风险确认是高影响动作，必须走版本绑定、人工审批、实时权限复核和幂等执行。
- 本期包含订单与订单明细；不包含回款、物流、售后和展会。

## 实现入口

- 设计：`docs/requirements/2026-08-28-unified-customer-profile-design.md`
- 实施计划：`docs/superpowers/plans/2026-08-29-unified-customer-profile.md`
- 数据模型与服务：`backend/app/customer/`
- 获客与 Agent 任务：`backend/app/sales_automation/`
- MCP 只读客户工具：`backend/app/mcp/agent_tools.py`
- 人工 API：`/api/customer-hub`
- Agent API：`/api/sales-automation/agent`
- 前端：`frontend/src/views/customer_hub/`、`frontend/src/api/customerHub.js`
- 迁移：`backend/alembic/versions/126_unified_customer_domain.py`
- 冻结物理契约：`backend/alembic/versions/126_unified_customer_domain_schema.json`
- 切换工具：`scripts/customer_domain_cutover.py`

## 数据库事实

- 迁移 126 创建/重建 39 张客户域表，共 778 个字段；所有表和字段都必须有 MySQL COMMENT。
- 物理契约 SHA-256：`64c40261e7012542affe5ff060c521d80d3ffe28ee3cfa4f77dfec964a027d5d`。
- 2026-08-31 使用官方 MySQL 8.4.11、`ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION` 完成隔离 DDL 演练和反射校验；39 表、778 字段、空表备注 0、空字段备注 0。
- 全历史从空库迁移仍依赖部署前置的 `ark_users`、`ark_permissions` 等认证基础表；这属于仓库既有部署假设，不应为迁移 126 修改历史迁移。
- 迁移 126 无 downgrade。旧客户业务数据允许清空，但 suppression/DNC 必须通过 HMAC 清单保留并回放。

## 上线状态与红线

- 2026-08-31 已在 RDS 快照、空抑制名单授权、全部 writer 停止和在途事务排空的维护窗口完成生产切换，并晋级 Alembic `126`。
- 生产切换库存 SHA-256 为 `74fa675c283fb105c6b113c502495b2b0c5c23605b377e2e00631c2c4fb65df7`；中间态恢复回执 SHA-256 为 `b24b81e8180e80423d6f904f78c81a027bf500e35e6e61d9786c208eeeecfdea`。
- 执行中暴露的 canonical float 证据反序列化和 MySQL `DATETIME` 秒精度问题已修复；39 表、778 字段、Agent 闭包、目标画像、空抑制名单和 writer 权限恢复已验收。
- 办公室与北京后端日常使用 `ark_app`：对 `commission_db.*` 仅有 DML，对 `lsordertest.*` 仅有 `SELECT`；`root` 只用于受控迁移/维护。
- 迁移 126 仍无 downgrade。新环境重建不得绕过 `scripts/customer_domain_cutover.py apply-reset`，失败后必须保留 contract、DDL proof 和 receipt，不得手工补表或复用 nonce。
