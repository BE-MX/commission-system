# WhatsApp 同步授权回调超时修复

## 现场结论

2026-11-13 办公室代理恢复后，连接器在 16:29:34 生成二维码、16:31:58 建立登录连接。随后手动同步返回 `HTTP 503 - authorization_unavailable`。连接器诊断记录为 Ark 授权回调 5 秒超时，而非账号拒绝授权或 WhatsApp 出网失败。

只读核对办公室运行提交 `e868f077039add1611ef564e90fc5e0d4538cd87`；运行 `event_sync.py`、`access.py` 与修复前 main 文件摘要一致。MySQL `innodb_trx` / `performance_schema.data_locks` / `data_lock_waits` 显示历史同步事务在账号主键同时持有共享锁和排他锁，授权回调的共享锁等待该事务。现场同步事务持续数分钟；后端也记录 MySQL 1205，连接器进入 `authorization_wait`。

问题在于逐条消息处理时修改 `account.last_message_at`，之后的显式 `flush()` / 保存点把共享锁升级为排他锁，锁持续到整批提交。只把查询改成共享锁不足以解决这一点。

## 修改范围

- `backend/app/whatsapp/event_sync.py`：消息处理期间用局部变量累计最后消息时间；只在事件保存点成功退出后纳入该时间。整批处理结束并完成实时授权复查后，再更新账号元数据及时间。
- 元数据刷新后取原账号时间、成功消息时间和连接器时间的最大值，避免旧元数据或乱序消息让时间回退；隔离失败事件不推进账号时间。
- 保留批次原子提交、游标串行锁、账号及权限实时锁定检查、撤权保护和正文范围。不延长授权超时、不跳过授权、不丢弃历史消息。
- 无迁移、前端或 Connector 代码变更；没有修改生产账号、授权、服务或配置。

## 验证

- 新 SQLite 回归在原实现上确认 2 个失败：消息循环提前 UPDATE 账号；旧 Connector 元数据覆盖较新的账号时间。
- 修复后受影响测试 57 项通过：`test_whatsapp_sync_authorization_lock.py`、`test_whatsapp_baileys_sync.py`、`test_whatsapp_binding_recovery.py`、`test_whatsapp_access_regression.py`、`test_whatsapp_api_contract.py`、`test_whatsapp_sync.py`。
- 独立本机 MySQL 8.4.6，绑定 `127.0.0.1:14389`，全新任务数据目录及随机测试 schema。真实两个连接在第一条消息已经 flush、第二条开始处理前调用 `authorization_snapshot`：修复后 1 项通过；在内存加载原实现运行相同测试，确切复现 MySQL 1205 / `FOR SHARE` 锁等待失败。测试还验证撤权提交后回调拒绝。
- MySQL 测试仅替换外部 Connector feed 和无绑定的 CRM 投影；账号授权和消息落库使用实际代码。不冒充生产 HTTP 链路验收或完整历史覆盖验收。
- 独立审查无需要修改的问题；约定检查和 `git diff --check` 通过。Git 巡检 `--no-fetch` 仅代表本地快照。
- 独立 MySQL 已通过自身管理命令关闭；随机测试 schema 已由 fixture 清理。删除任务临时数据目录的命令被自动审批策略拒绝，`tmp/whatsapp-mysql/` 保留合成测试实例文件与诊断日志，未绕过拦截。

## 交付与上线边界

任务分支 `codex/whatsapp-auth-lock-fix`，独立 worktree `D:/MyProgram/commission-system-codex-whatsapp-auth-lock-fix`。用户在验证完成后明确授权合并推送；本次 Git 交付保留主目录既有未提交改动，不包含生产部署。合并校验证据保存在主目录 `.deploy_state/whatsapp-auth-lock-integration-20261113/`。本任务 worktree 已合并后按项目约定清理；之前被策略拦截的测试实例文件保留在该证据目录，不重试删除。

最后只读核对时，生产已有 875 条消息、142 个会话；有效账号仍显示 `authorization_wait`，新同步事务仍在处理。该数字仅是当时已提交投影数量，不代表全部历史已同步。

待用户授权后，经 `deploy/deploy.bat` 受管入口发布修复。准备候选时须重新核对最新生产版本和迁移状态，只纳入本修复及保留当前生产历史，不把开发 main 中其他待发布变更附带上线。上线后确认手动同步返回成功、连续授权回调不超时、游标持续推进；已有登录凭据和授权应保留，无需为此重新扫码。
