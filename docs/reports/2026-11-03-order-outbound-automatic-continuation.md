# 修改订单数量后的出库同步自动续跑

状态：按用户授权提交、合并 main 并推送 origin，未部署。工作区 `D:/MyProgram/commission-system-codex-order-outbound-sync`，分支 `codex/order-outbound-sync`，基点 `6d32cca0`。无新增迁移，未写生产数据。远端只交付本次修复；本地 main 的原有 18 个未推送提交和未提交内容保留。

## 问题与结果

“李宝珠261006”修改数量时暴露三个独立阻塞：自动出库批次长期持有共享库存锁，关联任务先写 running 再因锁忙退出；原出库新增行已受理但未完整返回时自动流程只核对、不补齐；无业务变化的发票审计时间更新也使原出库恢复绑定失配。

修复后的正常路径是：保存当前修改意图 → 获得共享执行锁后更新原订单 → 更新唯一待出库原单 → 必要时安全补齐缺失行 → 回读确认 → 保留或生成补验要求。锁忙仅排队，关闭页面后也由后台继续。

## 关键边界

- 在创建关联发送租约前取得实际库存锁，嵌套订单和出库执行器复用同一锁。自动建单执行器每张释放锁，下一张前尝试处理一个已保存关联意图；原有限定高水位的分页扫描保留，避免前 20 张缺货/运行中单据饿死后续有效订单。该机制不宣称 MySQL 非阻塞锁具有严格公平性。
- 新 `invoice_linked_pending` 定时任务每 15 秒处理最多 10 个当前 pending 意图，单实例、合并错过的运行。按原操作人的当前权限、当前占用指针、保存快照重新授权，不接管任意 failed/manual/uncertain。当前权限被撤销等拒绝只结束 pending 队列元数据，保留业务账本。
- 自动补齐沿用既有受理证明、missing-only、每轮新 nonce 和单调进度保护；循环最多原预期行数，未知结果停止，不重复原 POST。原出库与未删除行 ID 保持原身份。
- 新计划绑定 v2 仅去除 Invoice.updated_at；保留业务值和依赖身份，执行期间完整快照前后比较不变。旧 v1 任务仍严格检查，不自动重写历史绑定。
- 未发送前意外异常只有在本次 token 仍归属、没有新增 START/claim、没有未解决事实时标记 failed 并清除租约。已产生持久化发送责任的异常转 uncertain，保留原账本/claim，后台不重发。
- 数量变化仍使对应旧媒体失效、撤回已提交验货、保留补拍要求；本功能不免验、不自动授予提前打印。单独打印授权仍绑定具体版本。
- 页面 pending/running 时每 3 秒只读刷新；执行/读取中不重叠，隐藏、终态及卸载停止。现有明确失败关闭接口为当前授权返回的 id 补可见性所需 subject，仍使用原客户可见范围核验。

## 验证

- SQLite 组合：`test_outbound_automatic_continuation.py`、`test_outbound_invoice_sync.py`、`test_invoice_linked_sync.py`、`test_outbound_sync_manual_review.py`、`test_scheduler_jobs.py`，185 passed。覆盖接受部分行后的自动补齐、审计时间更新、v1 严格边界、同总量 2+2→3+1 原单更新和旧照片失效/整单补验、不授予打印。
- 真实隔离 MySQL：`test_mysql_linked_execution.py`，29 passed。包含当前权限、执行期间撤权、丢失响应、租约与只读观察、业务绑定和明确失败关闭。
- 真实隔离 MySQL 排队和库存后台组合：`test_mysql_linked_inventory_queue.py` + `test_mysql_outbound_worker.py`，59 passed。覆盖锁忙不占租约、关闭页面后的后台续跑、并发前后台只发送一次、撤权、未发送异常清理、真实持久化 START/claim 后异常保留 uncertain 且不重发，以及逐单释放锁和分页推进。两组 MySQL 共 88 项、后端总计 273 项通过。
- Node：`linkedSyncPolling.test.mjs` + `invoiceLinkedSync.test.mjs`，10 passed。
- `npm run build` 成功（33.23s），保留既有大包提示；构建造成的两份无语义导航文件变动已恢复。
- 本地浏览器运行真实 Vue 组件：首次读取约 3008ms；4200ms 慢读取最大并发 1；pending/running 续读，done/manual/uncertain、隐藏及卸载停止，重新打开恢复。仅模拟异步读取，未请求生产业务接口。证据 `tmp/linked-sync-ui-harness/observed-results.txt`。
- 独立 agent 审查核心状态机和收尾差异通过。约定检查及 `git diff --check` 通过。`git_sweep.py --no-fetch` 完成，为本地远端引用快照，不授权清理他人工作或推送。

MySQL 使用测试自行启动的 MySQL 8.0.46 临时 loopback 服务，逐连接校验地址、端口、凭据；未连接共享数据库。历史 portal 测试夹具按当前模型补齐合成字段/表及合法编辑分组输入，只能证明真实 MySQL 上的服务行为，不作为生产迁移链验收。旧测试中的过期 GET 改为断言只观察 uncertain、持久行不变，符合现有只读契约；分页夹具使用不同订单 ID，保留真实唯一约束。

完整测试输出保存在 `tmp/order-outbound-sqlite-final.log`、`tmp/mysql-linked-final1.log`、`tmp/mysql-queue-worker-final2.log`、`tmp/order-outbound-frontend-build.log`；失败的中间运行保留用于追溯，不作为通过证据。

临时 MySQL 服务均已停止。对本工作区临时库目录执行带路径校验的递归清理时，工具安全策略返回 `blocked by policy` 并在执行前拒绝；没有绕过拦截，测试目录与日志保留。浏览器测试服务和标签已关闭，harness 保留用于复现。

## 发布与验收

后端、前端一起走统一部署入口；没有生产迁移。尚未自动修复或接管历史 uncertain。发布后先确认 `invoice_linked_pending` 作业已注册；对有授权的真实改量单据检查订单回读、原出库数量与 ID、补验和打印状态。当前“李宝珠261006”的已授权数据修复属于此前操作，本地开发验证没有再次改写它。
