# 回款同步恢复（1 / 2 / 4 项）

本次实现发送阶段持久化、分类自动恢复、独立后台索引。费用口径改造和界面状态重设计不在本次范围。代码位于 `codex/receipt-sync-recovery`，迁移 `175_receipt_recovery`，本地实现，尚未部署。

## 发送边界

领取原回款时同事务保存 `preparing` 和唯一任务令牌；所有远端查询、余额与凭证核验均在这个阶段完成。真正 POST 前，按订单→回款锁顺序重读订单、回款版本与应收绑定，保存发送内容 SHA256 和 `sending`，提交后才调用小满。鉴权明确拒绝后的刷新仍校验相同摘要和租约。

`preparing` 过期可确认没有越过 POST 边界，按有限退避恢复原单。`sending` 过期、POST 超时、服务端错误或不完整响应一律待核对，禁止自动再次创建。旧记录 `send_phase=NULL` 不推测历史是否发送，过期仍待核对。

发送标记提交与网络调用之间仍存在无法消除的中断窗口；小满没有已验证的远端幂等保证，这类记录必须保留结果未知。不能凭没有候选或一张同日同额回款认定未创建/自动绑定。

小满返回 ID/编号先独立提交到 `ark_receipt_attempts`，再接纳到回款主记录；因此唯一映射冲突不会回滚远端身份。旧任务迟到不覆盖当前状态，后台处理未消费的准确 ID 证据。异 ID 或已被其他回款绑定时冻结人工核对，同 ID 重复结果幂等处理。已消费的冲突身份仍是永久保护证据：普通核对、管理员绑定、自动回读和远端变更接受都不能仅凭当前 ID 匹配解除冻结；多 ID 冲突须专项审计处理全部原单。

## 分类恢复

| 类型 | 自动动作 | 终止条件 |
| --- | --- | --- |
| 尚未发送的网络故障、索引暂未就绪、准备任务中断 | 原单退避重试，间隔 60/120/240/480 秒 | 连续第 5 次失败后 exhausted，人工检查并重试 |
| 小满已返回 ID，详情读取失败 | 直接 GET 原回款详情；不查全量索引，不再次 POST | 连续第 8 次失败后 exhausted |
| 详情严格匹配但 collect_status=0 | 每 30 分钟回读财务状态 | collect_status=1 停止；读取失败另受 8 次预算约束 |
| 金额、手续费、实到账、币种、订单或日期不匹配 | uncertain/blocked，保留余额占用 | 人工处理原单 |
| POST 结果不明且没有已取得的确切 ID | uncertain/unknown，不自动重发/猜测绑定 | 人工核对 |
| 历史 failed 无分类证据 | 保持原状态 | 人工处理，不批量自动重试 |

回读成功的 `synced` 和财务 `collect_status` 分开保存。失败和待核对仍占余额。已知 ID 的只读恢复在新发送开关关闭时仍运行。修改回款会清理自动恢复计划，必须显式重试；自动恢复不修改财务金额或手续费。

## 索引

`receipt_index_refresh` 独立每 30 秒运行；`ark_receipt_index_states` 以接口租户摘要为主键，保存最小字段快照和校验摘要。数据库租约协调各实例，逐窗续租，只有仍拥有有效令牌的任务能原子发布完整快照。失败保留上一份完整快照，不移动水位。

单笔发送和其他余额调用方不全量扫描：先读取共享快照，再进行实时增量核验。增量超过 100 条按时间分窗；消费端每轮最多 32 次窗口请求，后台最多 128 次，每轮扫描复读比对并检查当前总数和最新更新时间。删除/迁移导致基线不完整时只由后台全量重建。缺索引、网络失败、跨窗变化或超出预算均禁止凭陈旧余额发送。

接口不能完整枚举同一秒超过 100 条时仍拒绝放行；不能截取前 100 条。远端手工回款在核验与 POST 之间新增的竞态无法由本地锁彻底消除。

## 发布与验收

迁移只新增字段和两张证据/索引表，不改历史金额、手续费、财务状态或历史发送阶段；禁止 downgrade 删除财务证据。隔离 SQLite 验证旧记录保存、完整模型字段、默认值及单 head；MySQL DDL/FK 类型离线编译验证。生产升级仅通过统一部署入口，在获得发布授权后执行。

回归覆盖：准备/发送/未知阶段中断、有限退避及跨北京时间零点、发送租约失效、POST 结果不明、已知 ID 自动回读、财务生效轮询、回读乱序、重复映射、迟到异 ID、回款编辑取消自动发送、发送开关关闭、缺失/损坏索引、增量分窗、同数删除新增、租约失效不能发布、失败快照不移动水位。关联回款批次、预售、生命周期和删除保护继续验证。

2026-10-08 验证结果：339 项隔离测试通过（53.31 秒）；迁移 SQLite 保留历史事实、MySQL DDL/FK 编译及单 head 检查包含在内。独立 agent 审查通过，`scripts/check_conventions.py` 与 `git diff --check` 通过，`scripts/git_sweep.py --no-fetch` 完成（本地快照，未刷新远端）。未做生产迁移、真实小满写入或真实 MySQL 并发压力测试。

复现命令（在本工作树 backend 目录，使用已有 Python 虚拟环境）：

```powershell
& D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe -m pytest tests/test_receipt_management.py tests/test_receipt_protocol.py tests/test_receipt_index.py tests/test_receipt_recovery.py tests/test_receipt_recovery_migration.py tests/test_receipt_migration.py tests/test_receipt_batches.py tests/test_receipt_deletion_evidence.py tests/test_receipt_preflight_fields.py tests/test_receipt_repair.py tests/test_receipt_storage.py tests/test_presale_settlement.py tests/test_invoice_lifecycle.py tests/test_invoice_deletion.py tests/test_invoice_soft_deleted_receipt.py tests/test_invoice_receipt_correction.py -q
```
