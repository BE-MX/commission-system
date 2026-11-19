# 私海助理生产部署与关闭状态核验

2026-11-04，按用户授权部署已合入 main 的私海助理，功能保持关闭。

## 发布结果

提交 `59f93e79e3d20f8217799cfbf0f200e32c93e45c` 已通过办公室统一 `deploy/deploy.bat` 完成 office-and-cloud 发布。沿用已在运行的同版本发布任务，发布 ID `9f5e677aa9f7499f801f30c505708242`。准备与正式发布均结束，`publish-current.json` 为 succeeded，成功回执指向同一提交及 `250_client_desk`，26 项必需后检通过。

准备期间办公室维护通道曾断开。重新使用 Computer Use 核对既有 UU 映射及本机监听，通道恢复后读取原任务持久状态，再继续跟踪同一发布。未另起重复发布。

## 独立只读核验

| 对象 | 实际读回 |
|---|---|
| 办公室版本 | `59f93e79e3d20f8217799cfbf0f200e32c93e45c` |
| 北京版本 | 同上 |
| 两地 `/health` | status=ok，database=connected |
| 办公室 CommissionSystem / WhatsAppConnector | 均 RUNNING |
| 北京 ark-backend | active |
| 北京出库 timer | 已恢复 active，原发布回执 completed |
| Scheduler | 办公室开启，北京关闭；私海任务未注册 |
| 私海助理 | 两地 CLIENT_DESK_ENABLED=false；试点用户数0、模型供应商白名单数0；未发现服务环境额外启用覆盖 |
| 数据库迁移 | alembic_version 仅 `250_client_desk`，迁移 writer 恢复记录 completed |

四张新表 `ark_client_desk_states`、`ark_client_desk_followups`、`ark_client_desk_suggestions`、`ark_client_desk_wa_links` 均存在，核验时记录数均为0。`active_slot` 为 VIRTUAL GENERATED 列，唯一索引 `uq_client_desk_active_link(account_uid,conversation_uid,active_slot)` 存在。

北京邮件 worker 为既有 inactive/disabled，新加坡旧同步为既有 inactive/masked，后检将两者列为非必需提示。其他未纳管服务沿用发布清单的核验范围。此次未验证实际试点、模型建议质量或真实钉钉早报使用。

## 证据位置

* 独立核验脚本 `.deploy_state/private-sea-production-verification-59f93e79.py`，前后读回位于同名目录 `before.json`、`latest.json`。
* 完整发布、runtime-verified、writer-readback 与 postcheck 证据位于 `.deploy_state/full-main-release-20261104-59f93e79/`。postcheck 的 ready=true，26 项 required 均通过。
* 上述信息为服务器实际配置、服务、版本及只读数据库结果。四表业务流程仍按试点验收手册逐阶段开通。
