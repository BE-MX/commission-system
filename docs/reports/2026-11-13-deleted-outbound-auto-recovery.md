# 小满旧出库删除后的发票自动恢复

## 状态与范围

- 用户要求：今后在小满删除旧出库单后，重新同步发票能自动核对并按最新版重建，不再手工修改数据。
- 独立工作区：`D:/MyProgram/commission-system-codex-deleted-outbound-auto-recovery`；分支 `codex/deleted-outbound-auto-recovery`，基点 `c4e89879`。实现阶段无新的生产业务写入。亮哥后续明确授权合并推送、拉取最新 Git 并全局部署；实际交付与发布以随后核验记录为准。
- 此前「翟1133」已在独立授权下定点恢复并回读验证；现场处理不等于本功能已发布。

## 实现

- `deleted_outbound_recovery.before_sync` 接普通同步和保存并同步；普通编辑与读取不触发恢复。复用共享出库执行锁，外部 GET 期间不持有业务事务，取证后重新锁定并比较完整快照。
- 只选择唯一未隐藏、待出库、全部明细关联当前订单、客户一致的原镜像，要求原自动任务已完成。预售、分批、多订单、已出库和明确失败的旧删除审计保留原流程。
- 精确 ID 缺失，或保留的软删除详情及有效列表证明缺失；校验软删除详情的状态、客户、每条关联，再查当前订单完整有效关联，最后复读旧单。不能把列表异常、权限错误、一般 HTTP 404 或空值当作删除。
- 已接受但回读未完成的出库更新链必须租约结束、所有发送事实明确接受、成功凭证身份一致。原事实和 claim 不改写，追加 FINISH 与删除核验记录；原状态、镜像隐藏审计和任务 `skipped/deleted:<ID>` 同事务提交。
- 最新订单推送成功后，原 follow-up 才重新排队。重建沿用原查重、仓库库存、冻结请求、发送账本及回读验证。库存不足仍等待，未知结果不重发。
- 重建比较成功 `create/update` 日志，排除普通成功审计；记录删除前最后成功日志 ID，处理 MySQL DATETIME 同秒精度。Python worker 核对本地镜像 ID 与小满 ID 的映射，不再要求两者相等。
- 原回款、验货和照片不修改；新单依原检验流程办理。没有新增表、迁移、权限或前端界面。

## 验证

- 隔离 SQLite：`pytest tests/test_deleted_outbound_recovery.py tests/test_invoice_linked_sync.py tests/test_invoice_outbound_tasks.py tests/test_outbound_invoice_sync.py tests/test_outbound_delete.py -q --tb=short`，273 项通过；最终补充历史删除失败及真实排队链路后，专项 `test_deleted_outbound_recovery.py` 30 项通过。累计 274 个不同相关用例。测试使用供应商替身，不调用真实小满写接口。
- Node：`node --test deploy/tests/test_okki_outbound_order_guard.mjs` 28 项；`node --test deploy/tests/test_okki_outbound.mjs deploy/tests/test_okki_outbound_isolation.mjs deploy/tests/test_okki_outbound_mode.mjs deploy/tests/test_okki_outbound_remarks.mjs deploy/tests/test_okki_outbound_stock.mjs` 129 项，合计 157 项通过。
- 独立审查发现的软删除详情、关联返回类型、历史删除失败误拦问题均已修复并复核；最终无阻断项。覆盖过期版本、权限撤回、发送租约、重复请求、期间数据变化、提交回滚、同秒新代次、真实排队及 worker 读取。
- `python scripts/check_conventions.py --strict` 和 `git diff --check` 通过。`python scripts/git_sweep.py --no-fetch` 完成，仅本地快照；其他工作区欠账未动。无前端改动，不做无关构建或浏览器验收。
- MySQL 8.0.46 独占回环临时进程已启动验证；`test_mysql_order_push_execution.py` 首个创建用例返回 500。打开测试 ASGI 异常后确定为旧合成夹具缺少 `ark_commerce_sending_claims`，错误发生在原发送 `begin_send`。在未修改 `c4e89879` 临时 worktree 上运行同一用例得到相同缺表错误（1 failed），并非本次新增路径；未修改旧夹具，不能宣称 MySQL 集成通过，也未继续执行 worker 用例。基线日志在本任务 `backend/tmp/mysql-baseline.log`，运行元数据及 MySQL 日志在 `backend/tmp/mysql-recovery-*`。测试进程均已关闭；清理合成数据库 data/temp 的命令被自动审批以 `blocked by policy` 拒绝，未改用其他工具绕过，目录暂留。
- 保留既有 jose `utcnow()` 弃用警告。本轮未验证正式 MySQL 并发或真实供应商端到端流程。

## 发布注意

候选同时涉及后端和 Node 自动出库程序；正式发布时应走项目统一入口并包含对应 Node 文件。此轮没有执行发布，生产仍运行原版本；上线后真实删除重建的耗时与端到端业务验收尚未进行。
