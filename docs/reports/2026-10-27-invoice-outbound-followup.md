# 2026-10-27 订单修改后的出库同步故障

## 三张生产出库单的定点处理

用户授权先更新三张原出库单，再排查并修复同步机制。维护通过北京已安装应用的出库预览、当前权限、库存校验、持久发送事实和回读流程执行；未发布应用代码、未重新推送订单或回款、未创建第二张出库单。

| 方舟发票 | 发票 ID | 原小满出库 ID | 已核对的最新出库内容 | 数量 / 商品金额 USD |
| --- | --- | --- | --- | --- |
| Tessie-KC-1003 | 1407 | 105885394123608 | 22寸 #1B 4件及 #8 3件改为 Super Double Drawn | 26 / 1648.96 |
| Tessie-KC-1004 | 1415 | 105887382968299 | 22寸 #8TP18/60 从15件改为7件，新增24寸8件；同步最新包装备注 | 70 / 2964.49 |
| 田雯261011 | 1379 | 105885103437734 | Standard 16寸 #8TP18/60 从10件改为3件，新增 Super 7件 | 20 / 390.32 |

以上是商品金额，不是包含运费、手续费等的订单总额。三张均保持原单号、原出库 ID、待出库状态；原有明细身份由正常编辑协议保持，新行由小满分配身份。

每张写后独立会话读回，再用新进程对三张再次 GET 核验：SKU、产品、订单行身份、数量、单价、产品资料、单头和备注与计划一致；本地订单、明细、回款、回款意图、半成品分配、首次出库任务与维护前快照一致，远端订单未变。方舟镜像分别在北京时间10:21:02、10:22:02、10:26:03收到了更新。

田雯单首次执行在发送前因仓库新上传验货照片被拒绝。重新读取证明原出库未变化、没有发送事实，随后使用新预览按“同步并重验”流程更新。三张旧照片保留并标为失效，验货仍为草稿，需要补验；未用重复发送或清锁绕过并发保护。

完整固定对象备份、预览、发送意图、服务回执及独立回读位于本任务 worktree `tmp/maintenance/outbound-repair-20261027-01a17b1f/`，同名原始证据保留在北京应用 `tmp/maintenance/`。维护脚本与执行日志在本任务 `tmp/maintenance/`；不包含认证凭据。

## 根因与验证边界

生产日志显示三张订单的 `/v1/invoices/order/push` 已成功受理，方舟后续 `/sync` 却返回409。直接 GET 小满订单与出库详情确认订单为新明细、出库为旧明细，排除了仅页面缓存或镜像延迟。

`SessionLocal` 使用 SQLAlchemy 默认的 `expire_on_commit=True`。普通订单执行器提交成功事务后，把已失效的 ORM 发票交给出库延续步骤；读取 `invoice.id` 会隐式 SELECT 并开启事务，紧接着当前授权入口拒绝这个非空事务，报“发票核对必须从新事务开始”。错误出现在出库更新发送之前。

同类问题还存在于成功事实的提交回执恢复分支：commit 后读取 ORM JSON 结果会重开事务。两处都应在提交前提取必要的普通数据，跨阶段传递固定身份或结果快照；不关闭生产对象失效、不放宽当前权限和新事务门禁。

原员工端 MySQL 测试夹具使用 `expire_on_commit=False`，与生产会话行为不同。改为生产默认失效与 `autoflush=False` 后，既有两个出库延续阳性测试在修复前均稳定复现同一409。隔离测试使用独占 loopback MySQL，未连接共享生产库；门户测试迁移夹具同步到现有199/200/201/204增量，仅用于自有测试库，不执行生产迁移。

## 本地修复

- 普通推单成功提交前冻结发票身份；提交回执恢复分支在 commit 前复制 JSON 结果。保持生产默认对象失效、新事务校验和当前权限门禁。
- 强制当前权限的出库延续同样进入异常隔离：订单已成功而出库409/503时，返回订单成功及独立的出库待核对原因。401/403/404仍抛出；调用方返回前再次核验权限。rollback只清理本阶段未提交事务，不清除已经落盘的发送事实。
- 测试会话改为生产一致的提交失效行为，阻止真实供应商 HTTP 外发；补齐当前库存读取与镜像行对应关系的测试替身。
- 新增实际 JWT/事务/发送认领/回读的订单到原出库全链测试，覆盖更换产品、拆分数量新增 SKU、删旧增新；外部 HTTP、镜像为替身，未把隔离测试当作线上发布验收。

独立代码审查确认权限仍失败关闭、原发送与未知结果事实不被清除，提交 ACK 丢失时仍区分已提交与未提交。生产数据定点更新已完成，机制代码来自 `codex/invoice-outbound-followup`。用户随后授权本次提交、合入main并推送origin，最终状态以Git引用回读为准；未部署，没有新增生产迁移。

## 验证证据

- 修复前：生产一致的 `expire_on_commit=True` 隔离 MySQL 会话下，两个既有阳性延续场景都复现409。
- 新增完整链路：换产品等级、拆分并新增SKU、删旧增新三项通过；出库预览409/503、真实出库POST超时并再次只读核对三项通过。最后一项验证订单/出库各一次POST、原 `unknown` 事实保留、状态持续 `sync_uncertain`，没有把待核对变成成功。
- 六文件扩展回归首次运行：239 passed、5 failed，达到 `--maxfail=5` 后停止；不是全量通过。1项为新增独立库存令牌的旧计数断言，已按当前实际读取路径修正；4项旧规格见下。
- 在子进程内加载 `git show HEAD` 的两个未修改产品模块，保留相同隔离数据库/测试输入，四项均复现同样失败。基线为 `3e1f168ff3df212d1e486519c46ea8a8349ac7c5`；对照代码和pytest插件保留在 `tmp/baseline-followup/`，没有替换工作区源文件。

六项既有规格差异（首轮四项，尾部回归补充两项）：

| 用例 | 当前既有行为及来源 |
| --- | --- |
| `test_receipt_preflight_failure_rolls_back_proof_binding_and_claim[missing_amount]` | 旧断言期待409；提交 `4d0495b0` 已允许零回款同步，实际200、回款保持draft、不生成回款。本次不改变该已批准规则。 |
| `test_two_real_overlapping_token_windows_only_claim_and_send_once` | 旧用例要求两个请求同时进入令牌窗口；`a00d7222` 已加全局库存互斥，第二请求先409，因此等待条件不可达。 |
| `test_concurrent_late_read_cannot_permanently_block_finished_original` | 首请求仍持库存互斥锁时，第二核对请求按既有规则409；旧断言要求并发返回200。 |
| `test_expired_sender_without_terminal_fact_does_not_authorize_new_repair_post` | 发送者持有库存互斥锁，租约过期不释放命名锁；并发恢复先409，旧断言要求200。 |
| `test_manual_finish_between_preflight_and_prepare_invalidates_old_requirement` | 同一库存互斥锁阻止核对请求期间的第二个发送请求，旧断言要求并发发送200。 |
| `test_current_read_expires_only_linked_lease_without_sending` | `836876349` 已明确只把过期租约展示为uncertain，不修改持久任务；旧断言要求GET把数据库running写成uncertain。 |

上述六项保留原断言并列为基线问题，没有为了测试通过放宽锁或调整回款业务。本任务仍完成受影响的新事务、独立出库结果和未知发送保护验证。

`python scripts/check_conventions.py` 与 `git diff --check` 通过；`python scripts/git_sweep.py --no-fetch` 完成，结果只反映本地引用快照。已结束隔离 MySQL 的数据目录清理被自动审批策略拦截（blocked by policy）；未绕过，临时数据和维护备份/日志均保留。

### 最终结果

- 修正库存令牌计数后，出库延续权限全文件及未跑尾部回归：82 passed、2 failed；这两项随后用相同HEAD产品模块对照，2项均复现失败。尾部回归没有改变产品代码。
- 六文件最终收集280项；结合三轮实际执行，去重后274项通过，6项既有规格差异均完成HEAD对照复现。不能将它描述为280项全绿。出库延续权限文件51项全部通过；新增全链6项全部通过。
- 独立审查通过。所有本任务启动的隔离MySQL进程均已退出；只剩被自动审批策略拦截清理的临时目录。维护备份及业务回读证据继续保留。

复跑命令在本任务 `backend` 目录执行（同一workspace参数每次必须换成不存在的新目录）：

```powershell
D:/MyProgram/commission-system/backend/.venv/Scripts/python.exe -B -m pytest tests/portal_mysql/test_mysql_order_outbound_chain.py tests/portal_mysql/test_mysql_outbound_followup_authority.py tests/portal_mysql/test_mysql_order_push_execution.py tests/portal_mysql/test_mysql_outbound_prepare.py tests/portal_mysql/test_mysql_outbound_execution.py tests/portal_mysql/test_mysql_linked_execution.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=C:/Users/windb/.codex/worktrees/outbound-replenishment-reservation/commission-system/.deploy_state/tools/mysql/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=C:/Users/windb/.codex/worktrees/invoice-outbound-followup/commission-system/tmp/mysql-review-new
```
