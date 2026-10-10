# 订单发票点击编辑时的交易繁忙修复

2026-10-10，分支 `codex/invoice-edit-busy`，基于 main `e26d5c23`。本文记录独立 worktree 的修复与验收；亮哥随后授权合并、推送，本轮不部署。未连接共享业务数据库或调用真实小满服务。

## 原因与修改

`openEdit` 在显示编辑抽屉前依次读取订单和关联同步任务。`GET /api/invoice/invoices/{id}/linked-sync` 原先复用写授权入口，取得全局授权屏障和订单写锁；有历史任务时还调用 `expire` 锁任务并可能写状态。另一连接持锁时，仅打开编辑器就会返回 `TRANSACTION_BUSY`。

隔离 MySQL 8.4.6 中，门户关闭、独立连接持有授权屏障的旧代码用例实际返回 503 和相同错误码。此证据复现代码路径，不替代生产请求或当前线上锁持有者的核验。

读取接口现在使用新事务中的实时员工角色与权限，接受 read/write/sync 任一动作，保留订单归属及回款摘要脱敏。查询不申请写锁、不修改任务，成功响应带 private/no-store。过期或缺失租约的 running 任务只在响应中显示 uncertain，原执行令牌和订单占用保留。

管理员人工核对入口允许在原写授权和单据锁内结束已过期的 running，无需 GET 先改状态。原任务绑定、未过期租约、待恢复库存检查仍保留；结束后旧 runner 不能再发送或完成原任务。保存、校验、同步、重试和结束仍使用原写授权与并发保护，无数据库迁移。

## 验证

- 真实 MySQL 组合：`test_mysql_invoice_linked_reads.py test_mysql_invoice_editor_authority.py test_mysql_invoice_edit_off.py`，108 passed，176.45 秒。隔离回环 mysqld 和随机独立凭据，真实登录/JWT/HTTP；未接入共享数据库。
- 最终新增边界定向：`test_mysql_invoice_linked_reads.py -k 'projects_expiry or direct_expired_resolution'`，5 passed，32.21 秒；其中 3 项为复验、2 项为新增。新增只读套件共 20 个用例均已覆盖，不重复累计通过数。
- 覆盖授权、订单、任务三种独立持锁，以及门户 ON/OFF；断言读取 SQL 无 FOR UPDATE 或商业写入、业务快照不变。覆盖空任务、完成/失败任务、live 权限撤销、停用、归属变更和旧 super_admin JWT。
- 直接结束过期运行任务时，新任务换绑或 pending 库存返回 409，原任务及库存不变；有效租约拒绝结束，过期/缺失租约允许结束，旧 runner 随后被拒绝。
- SQLite：`test_invoice_linked_sync.py test_invoice_scope.py`，31 passed，7.39 秒。独立审查另运行关联同步 25 passed，不累计入主代理数量。
- Node：`node --test tests/invoiceLinkedSync.test.mjs`，4 passed，包含丢响应后读原结果、原幂等键恢复和刷新。
- `scripts/check_conventions.py --strict`、`git diff --check` 通过；`scripts/git_sweep.py --no-fetch` 已执行，仅本地远端引用快照。
- 独立 agent 审查权限、资金脱敏、过期任务与旧 runner 边界，无 P1/P2 发现；建议增加的两项边界已补测并复核。

扩大尝试的既有 `invoiceRead.test.mjs` 16 项因 VM harness 缺少当前列表代码的导入测试桩，在 module link 阶段失败。将两个文件从未修改的 HEAD 导出到独立基线目录后同样失败；未算作通过，也未修改无关前端代码。首轮复用的前端依赖不完整，已在本 worktree 独立安装依赖后复核上述基线问题。后端 JWT 库保留既有 UTC 弃用警告。

## 交付边界

接口与关联同步说明已同步，主目录其他未提交内容受独立备份保护。修复已验收，按用户授权合并并推送 main；实际 Git 交付以提交及远端回读为准。线上需获得具体发布授权后通过 `deploy/deploy.bat` 发布；未清生产锁、自动重发、变更业务状态或登记真实资金。

本任务五次隔离 mysqld 均由 fixture 正常关闭，停机日志保留在 worktree 的 `tmp/mysql-*/mysql.log`。自动安全策略拒绝删除这些目录的临时 data/temp，未提供具体原因，数据与证据暂保留，未绕过拦截。
