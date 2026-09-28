# 168 客户标签迁移失败诊断与本地修复

## 现场（2026-09-25，只读核查）

- 失败候选：`284c399b41b2570d91b778ad0a0c114eaa1fecc0`。
- 办公室 `schema-writers.json`：数据库167，pending仅168，`failed-after-ddl`；四个原本运行的writer已记录停止，出库timer由发布协调器预先暂停。
- `publish-current.json`：`failed`，`outbound.status=frozen`，原出库调度active/enabled均true。办公室CommissionSystem、WhatsAppConnector实查Stopped。
- 数据库版本仍为 `167_invoice_merchandiser`；`ark_customer_media_customer_tags` 已存在，行数0。
- 新表customer_id排序规则为`utf8mb4_0900_ai_ci`，源`ark_customer_media_batches.customer_id`为`utf8mb4_unicode_ci`。
- 原回填SELECT的只读EXPLAIN复现MySQL1267：Illegal mix of collations for operation '='。未执行INSERT、DDL、stamp、downgrade或重启。

## 修复与验证

- 只在168回填SQL的MySQL客户编号比较中显式使用两端`COLLATE utf8mb4_unicode_ci`，保持源字段比较语义；保留已创建表及数据，无新增revision、无删除操作。
- 修复后的实际迁移通过只读适配器执行EXPLAIN验证成功；数据库版本仍167，新表仍0行。
- 隔离SQLite测试4项通过：新建表/已有表 × 普通比较/MySQL比较分支；验证排除已删除素材、回填、重复执行幂等。SQLite注册collation仅验证执行路径，不声称模拟了真实MySQL的全部排序语义。
- `git diff --check`通过；约定检查被13项既有前端UI基线问题阻断，未修改这些前端文件。`git_sweep.py --no-fetch`完成，远端状态仅本地快照。

## 生产恢复边界（尚未执行）

本地修复基于失败候选隔离创建，避免夹带随后main上的169及其他功能。没有提交、推送、合并或发布。

普通发布会被failed-after-ddl日志阻断；不能删除/改写事故日志、手工stamp或直接启动旧writer。现有149/151/色块专项恢复入口不适用于168。

后续需要经授权的168恢复发布：保留原始事故日志，固定修复候选，重新核实版本、完整表结构/约束、writer原始状态和当前状态；在共享发布锁内经deploy.bat恢复入口完成回填与168版本登记，再按协调器顺序激活候选应用、验证健康、恢复外部writer及原出库调度，最后关闭恢复记录。已实现--recover-migration-168专项恢复入口，103项定向测试通过；真实表结构只读验证通过。用户已授权恢复，准备固定候选执行预检，尚未执行生产升级。全部署测试333通过、11跳过、3失败（旧测试固定head164两项、未改动storage_routing的Mock耗尽一项），不据此声称全套通过。


## 最终恢复结果（2026-09-25）

用户明确授权“继续帮我恢复”。修复提交 `8bd7759f7df2bcb132438e68ca3f424b6f44162d` 已通过git bundle传入办公室，通过统一deploy.bat的--recover-migration-168入口先prepare-only成功、再完整发布成功。仅生产专用deploy引用写入北京仓库；没有向origin推送或合并开发main。

- 办公室和北京实际Git HEAD均为上述修复提交。
- 数据库版本168_customer_media_customer_tags；目标表9行，有效源标签缺失数0。
- CommissionSystem、WhatsAppConnector、ark-backend、shipment-tracking-mcp、ark-okki-outbound-poller全部running。
- 出库工件digest c9fbf02bdab9d7f0501e467934179bc59276e2f6ab2cb1e63b23c9406d24be4f核验通过；原active=true、enabled=true恢复；仅此不变工件保留原284c399b事务revision。
- publish-current=succeeded；schema-writers=completed且保留recovery_original；recovery-168-original-publish.json保留原发布事故。
- 办公室127.0.0.1:8001/health、https://leshine.work/health、https://leshine.cloud/health全部HTTP200、status=ok、database=connected。
- 两地主站静态制品均8da886441049f74500e731d63e81329424f6e43ecb161b5d32ce11e953cf7634；客户素材静态站更新成功，PM静态站未变化；本轮复用原已上传制品，传输0字节。
- 103项定向部署测试及4项隔离迁移测试通过；独立审查P2断点已修复并复核。部署全套既有3项失败与前端约定13项问题未扩展修改。

生产恢复完成。后续正常发布前需经授权将该分支合入开发main并同步发布源，保持从生产8bd7759f快进；不要在生产reset或再次执行本事故恢复开关。

## 开发主线合入（2026-09-25）

用户随后授权“合入”，本修复与生产恢复记录合入本地main；保留main已有169迁移及其他任务的未提交文件。本轮不向origin推送、不再次部署；发布源同步仍需另行授权。
