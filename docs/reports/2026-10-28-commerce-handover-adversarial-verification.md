# 双路线开发：原责任交接与出库、回款独立审查

日期：2026-10-28。范围：当前 `codex/commerce-transition` 工作区的开发实现与隔离验收。下列来源、银行款、审批及客户均为测试构造，不代表生产数据已迁移或业务已验收。

## 已发现并关闭的问题

| 级别 | 攻击序列及原缺陷 | 当前处理 | 直接证据 |
| --- | --- | --- | --- |
| P1 | 原独立银行款 100，核销已冲回 40，无实际退款凭证；结清接口仅比对原额与币种，仍允许退休旧责任 | 独立旧回款须为有效已收且无冲回；旧批次有效占款须有实际收款事实，退款仍须不可变凭证，不能用审核引用代替 | `test_commerce_handover_review.py::test_reversed_standalone_original_cash_without_refund_evidence_cannot_retire` 先红后绿 |
| P1 | 已划本地试点的 SKU 仍可由旧出库创建、更新、预售出库获取发送 claim | 共享 claim 入口按当前 OKKI namespace 精确映射外部商品和 SKU，拒绝本地或冻结范围。没有真实远端仓库映射时，不以两个数字仓库 ID 证明实物隔离；该 SKU 整体排除旧路线。存在试点时，未映射或歧义 SKU 同样拒绝 | 同文件三种实际 `legacy_sending.start` 入口红绿测试、namespace/歧义拒绝与合法旧 SKU 正例 |
| P1 | 原旧出库 claim 已在途或 unknown，管理员仍可用“已清理责任”字典建立新本地实物范围 | 新本地范围查询真实原出库 claim、后台出库任务及同步状态；未决时等待原请求收尾。审核引用不能覆盖已知 unknown | 同文件 `test_original_outbound_inflight_cannot_be_overridden_by_new_pilot_attestation` 的 sending/unknown 两例 |
| P1 | 原物料已存在 pending、待扣差量、原操作键或 pending 时间，登记本地资源仅检查审核字典即可越过 | 对实际 material ID 做 current read；任一未决字段存在即拒绝新增本地范围。未映射或非规范 key 不能证明排除已知 pending。保留原未决事实，待原结果核清后再承接；精确既有范围的幂等重读仍可返回 | 同文件 `test_material_pending_source_cannot_be_reclassified_by_pilot_review` 八个红绿反例、原已结清物料正例、既有范围重读反例 |
| P1 | 回款已排队，原创建人随后停用、撤权或丢失订单范围；旧后台仍可发送；取证期间撤权同样可穿透 | 新发送 capture 与原 claim 事务均重读原创建人的 live `receipt:write` 和既有 `receipt.access` 范围，发前丢弃旧 RR 读快照；已有远端身份、unknown 和晚到原结果不被解释成新发送 | `test_receipt_sender_authority.py`：四种撤权 POST 0、晚到成功保留原身份、非 pending 三例不重获发送权 |
| P2 | 旧报表 owner/account_date 与发票销售/日期不同，冻结交接只使发票维度失效，旧报表误显示数据完整 | 未完成交接同时使原 CustomerOrder 和当前 Invoice 的范围失效，包括尚未挂本地 ID 的 waiting 准备 | `test_commerce_handover_review.py::test_handover_invalidates_previous_customer_order_owner_and_account_date` 先红后绿 |
| P2 | MySQL RR 旧 Session 先读质检，另一 Session 完成历史出库承接；旧写入口未看到新本地关联而回查交易镜像 | 先持有 policy 串行锁，再以 current locking JOIN 定位原发票与出库；同一事务复用已锁定本地关联，完成或取消的本地出库禁止修改质检 | 完整 MySQL 链中 recall、submit、add_photo、delete_photo 四个旧快照入口全部拒绝，镜像查询与 HTTP 均为 0 |
| P2 | 门户关闭时出库 HTTP 路由先查 scope，再调用要求新事务的执行器，正常同步错误 409 | 出库 preview/synchronize 始终直接从 current 执行器授权，门户状态不改变原交易门禁 | 实际 TestClient 出库同步回归 |
| P2 | 发前库存明确不足留下假 `sync_pending`；确定鉴权拒绝被误归 unknown 并破坏旧打印快照；原 claim 提交后 mutable nonce 被换仍发送 | 无 SEND/claim 的原准备明确收尾 not_sent；auth_rejected 核对原 FACT+failed claim 后收尾并保留旧 overlay；POST 前重验原 mutable 任务、原 START、scope、epoch 和 lease，再释放 SQL 锁执行 | `test_outbound_invoice_sync.py` 对应真实执行器回归，含原 sender POST 0 |

## 真实 MySQL 证据

命令在工作区根目录执行：

```powershell
backend/.venv/Scripts/python.exe tmp/run_transition_mysql_tests.py tests/test_local_migration_chain_mysql.py -q --disable-warnings --maxfail=1
```

结果：15 个测试通过，1 个 warning，256.95 秒。日志为 `tmp/shipping-handover-mysql-full-chain-v4.log`。其中完整业务链从随机空库实际升级到 `226_commerce_transition`，不是以 `create_all` 或 `stamp` 替代迁移；其余测试包含交易镜像拒绝规则及旧单例 DDL 合法性。

完整链的机器结果为 `tmp/local-migration-chain/ark_chain_test_3ae88cb3b5594bc2/result.json`，包括：

- 原发票、明细、客户、售后媒体和缩放汇率历史记录保留；原整单 1,000、已发 6、后续发 4，最终余额 0。
- 历史媒体 ID 保留；四种旧 RR 质检 mutation 被拒绝；旧生产扫码不得绕回旧流程；并发 activation 返回同一结果。
- 原整单和定制折叠明细的后续回款、出库与库存守恒；定制真实数量为 4、6，投影数量合计 10，历史 alias 不重计。
- 预售原首款 300，其中历史消费 100、后续消费 200；原两批运费 11、13，后续运费 5、12；总收 1,041、合同 1,000、余额 0，跨批运费错配被拒绝。
- 新旧物料并发、相同幂等请求及净零旧 RR 快照校验；完整链的原责任承接阶段交易镜像查询与外部 HTTP 均为 0。
- 测试生成的 schema 与 writer 均执行 DROP 后独立查回确认不存在。

Fixture 修正保留真实门禁：承接后的请求读取实际 authority epoch；旧共享付款先构造原 ReceiptBatch、Receipt 和唯一银行身份，再由承接复用；激活使用 prepare 返回的完整命令；原生专用银行账户不被改成混用账户。

## 聚焦验收

- `tmp/shipping-inspection-final.log`：质检、媒体、站点、原预售完成及本地发货六套，92 passed。
- `tmp/shipping-handover-regression-final.log`：原履约、预售、交接、混合消费者及本地发货六套，63 passed。
- `tmp/shipping-resource-review-final.log`：物理范围与旧持久发送协议，50 passed。
- `tmp/receipt-resource-gates-final.log`：新回款 live sender、独立审查、库存期初、原订单激活、旧持久发送及原生门禁六套，84 passed。
- `tmp/material-pilot-review-final.log`：物料未决范围、精确范围幂等重读、独立审查、物料/库存期初及办理权六套，88 passed。
- `tmp/receipt-live-sender-legacy-regression.log`：原回款管理、恢复与 HTTP 协议三套，151 passed。金融算法 fixture 补真实 DB 权限、慢读过期 fixture 补实际销售归属，未替换新 sender 门禁。

各组存在重复测试，不能简单相加成独立测试总数。本报告只证明当前工作区、隔离合成数据及对应执行路径；生产 writer 清单、真实资源盘点、银行全量对照和用户角色业务验收仍应以正式上线记录为准。
