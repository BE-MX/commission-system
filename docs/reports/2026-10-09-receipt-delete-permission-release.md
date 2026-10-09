# 订单关联回款删除权限发布记录

## 行为与配置

“翟 #261015”及末尾带句点的同名订单已有订单和出库删除权，但关联有效回款，原流程要求 `receipt:admin`，因此出现权限不足。新增 `receipt:delete` 后，整单删除只要求对应的回款删除动作及原财务范围，不授予回款异常管理能力。

生产权限已登记为 ID 2000，名称“删除订单关联回款单”。角色管理位于“回款单 → 删除”；启动 seed 不自动授予普通 admin 或已有 write/admin 角色，发布核验时授予角色为空。管理员刷新权限目录、明确配置后，业务员重新登录。`invoice:delete`、`shipping_inspection:delete`、订单归属、预售/批次/已出库等业务守卫保持原规则。

本轮只读检查订单状态，未执行订单删除或修改业务员角色权限。原发票、回款金额、手续费、凭证及审计仍保留；删除单据不执行退款。

## 版本与发布

- 应用提交：`60e408d4e1538a4e2613cb85bad685e76f80584b`，已合并并推送 `origin/main`，远端引用核验一致。
- 办公室统一 `deploy/deploy.bat` 固定同提交，先准备后正式发布，均 exit 0；release ID `ec45c9bc99cc43228471912b387db62c`，scope `office-and-cloud`，journal `succeeded`，deferred `[]`。
- 首次 SSH 转发连接重置，预检以 OSError 结束，completed 为空、两地仍为旧版本。确认原进程退出后，从同一候选恢复准备；日志落办公室 `.deploy_state/receipt-delete-permission/`，正式发布也按该目录的退出回执核验。未绕过部署锁、迁移或服务切换协议。
- 两地实际 HEAD 与应用候选一致；权限 seed 和关联删除 service 的规范化源码 SHA256 与 Git 内容一致。办公室与北京 health 均为 `ok/database=connected`。
- 共享 schema 保持 `180_settlement_funding_amendment`，无 DDL。出库轮询恢复原 active/enabled，邮件 Worker 保持原 inactive 基线；其他未纳管服务未更新。
- `leshine.work`、`leshine.cloud` 的入口、导航清单、主 JS/CSS、角色管理与权限矩阵 JS/CSS 共 16 个公网资源摘要匹配办公室候选。

## 验证与保护

隔离 SQLite、模拟远端的受影响回归 213 passed；合并后权限专项 83 passed。覆盖删除独立授权、当前 DB 权限与旧 token、回款归属、无回款、本地未发送回款、超级管理员、关联变化及未知删除不重发。前端权限/导航 12 passed、生产构建和约定检查通过；独立 agent 审查未发现 P1/P2。

主目录原 24 项修改/未跟踪内容保留：22 个无关文件逐项摘要不变，两个重叠文档通过备份和三方合并保留原内容。临时开发工作树按整合后的归属规则清理；部署退出回执、源码摘要、权限元数据、订单状态及公网摘要保存在主目录 `.deploy_state/receipt-delete-permission/verification-summary.json` 与同目录证据。
