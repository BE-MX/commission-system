# 双路线交易对比运行约定

本模块观察正式操作并在独立数据库中调用真实本地领域服务。对比结果不能变成正式本金、库存、办理权或迁移期初。

## 默认状态与进程边界

`COMMERCE_SHADOW_ENABLED`、`COMMERCE_SHADOW_WORKER_ENABLED` 默认关闭。正式进程只保存观察、outbox、运行与差异。生产使用输入包/回执边界；`worker.run_replay(source, target)` 仅供隔离测试编排，不能作为生产进程内执行器。

独立 worker 入口：

```text
python -m app.commerce_shadow.cli --target-url <candidate-only-url> --input input.json --report report.json
```

该入口在导入领域代码前清空自身继承的环境，不读取 backend/.env，不建立来源数据库 Session；源连接指向不可用主机，外发凭据为空，HTTP 被关闭。MySQL 必须使用仅授权候选 schema 的 `shadow_` 用户；不能带全局权限或授权能力。SQLite 必须是预先准备的独立持久候选文件，临时页只使用内存。返回码 `0` 表示取得候选回执，`2` 表示覆盖不足；其余错误不得自动重新执行正式操作。

## 来源端操作入口

平台操作员先独立准备并核验候选检查点，再使用 `service.create_dataset` 登记其不可变清单与目标指纹。公共 API 不接收检查点、数据库 URL、凭据或领域种子。

1. `POST /api/commerce-shadow/runs` 创建固定数据集/责任闭包/观察水位的运行。
2. `GET /api/commerce-shadow/runs/{id}/input` 导出输入包。需要实时 `commerce_shadow:admin` 和完整订单、客户、财务范围；下载不确认 outbox。输入命令不包含正式 outcome/result，旧订单的聚合总额也从候选输入中排除。
3. 在只有候选库权限的独立进程运行 CLI。传输和文件访问由部署操作员控制，不能把此命令放入携带正式凭据的常驻进程。
4. `POST /api/commerce-shadow/runs/{id}/receipts` 提交 CLI 输出的回执。需要同样的实时操作员和数据范围；服务器自行重导原水位的输入，校验 bundle/目标/命令身份，不接受客户端替换的输入包。只有回执导入持久成功才确认相关 outbox。
5. 业务页面通过 runs/differences 查询覆盖水位与差异。差异复核追加依据，不能把原数字差异或不完整状态改成一致。

回执是受权操作员提交的候选执行证据，不会触发任何正式领域写入。重复投递重用候选数据库内与领域事务一起提交的 `ShadowExecution`；来源 ACK 丢失只重新导入原回执。已有回执的执行身份、实际值和候选结果类别不可更换；重复观察身份、跨运行/目标或输入摘要不符均拒绝。来源已识别的覆盖缺口不能被候选回执抹去。

## 原始旧路线输入映射

- `legacy.order.push`：捕获首次发送前的合同、原始行、费用、真实操作人以及来源租户。客户/SKU 只使用该租户精确且唯一的核验身份；候选实际创建并确认合同，后续真实合同修订实际 amend。before 来自上一份不可变 accepted 原合同，新增行必须同时有 before 中不存在的源行 ID 与本次 pre-send 明确 new 的证据；已存在行缺 typed reference 不能变成新行。旧行 `commercial_kind=NULL` 不猜测补全，缺分类时为 incomplete。
- `legacy.receipt.remote`：捕获原 Receipt/共享 ReceiptBatch 输入、原始推送载荷与银行身份引用。完整银行映射来自真实 `BankIdentity`/账户域或独立核验的 `checkpoint.legacy_bank_map`。候选实际 register、confirm、allocate；同一银行主体/账户/渠道/流水使用稳定请求键，只生成一份本金。只在原回款精确读回且 `collect_status=1` 后记录 accepted；HTTP 接收先保留 unknown。
- `legacy.outbound.remote`：捕获原出库行与稳定 InvoiceItem 关联、外部仓库和原操作意图。候选实际 create 和资金 ready；原 provider 创建响应不能证明实物发货，所以此适配器不会创建检验通过记录或调用 ship。正式任务与独立原详情核验同时存在才记录 accepted。更新操作只通过原 create 的 SendingClaim 与观察事件取得 typed reference，实际取消原未发批次后重新计算并 create/ready；已发批次由真实取消门禁拒绝。

检查点可包含以下**核验输入映射**，不能包含正式财务/库存流水或候选幂等事件：

- `legacy_bank_map["legacy-receipt:<id>" / "legacy-batch:<id>"]`：`subject_key/account_key/channel/bank_account_code/transaction_id/gross_amount/currency/statement_reference`。
- `payment_type_map[<原方式>]`：明确对应 `bank_transfer/cash/card/online`，未知中文或 provider 枚举不能自行猜测。
- `legacy_rate_map[<原银行身份引用>]`：原业务冻结的 `rate_to_cny/rate_to_usd`；与候选核验基础配置不符则阻断，不能按今天的汇率重算。
- `legacy_allocation_plans["legacy-receipt:<id>"]`：多应收目标的 `kind/amount` 分摊，合计必须等于原金额，目标必须唯一。单一目标可直接办理；多目标未提供计划不猜分摊。
- `legacy_warehouse_map["okki:<tenant>:<external_warehouse_id>"]`：`warehouse_id/review_reference`。
- `legacy_order_warehouses["<source_invoice_id>"]`：库存订单确认时的 `warehouse_id/review_reference`。
- `legacy_contract_items["<source_invoice_id>"]`：初始已核验合同的完整旧源行 ID 集合，仅在没有已观察 before 时使用；不能以当前 after 倒推 before。

旧单没有通用业务版本计数器，所以旧订单的对比 `contract_revision` 使用原持久 SendingClaim ID 表示**来源发送代次**；它不是旧单商业版本，也不替代候选自己的 `commerce_version`。原 claim 必须绑定 `order_push` 动作与同一 Invoice，unknown 与终局读回保持同一代次。回款/出库冻结其依赖的最高 accepted 原订单代次，before 也按原代次选择，不能以迟到的投递 ID 覆盖当前合同。没有已观察的原订单代次时保持 `None` 并标明 unavailable，不能从当前 Invoice 猜一个版本。候选同时检查该原代次、epoch 与因果水位。

候选命令检查冻结原操作人的动作权限，规则与正式 HTTP 入口一致；直接调用领域函数不能绕过 `receipt:admin` 等门禁。旧收款的 register/confirm/allocate 复合适配需要原操作人具有 write/admin 权限，否则保留真实拒绝差异；不能凭 provider 财务状态替原操作人补管理员权限。

缺映射、历史汇率不符、共享闭包不齐、缺媒体验证或没有原始合同依赖时，返回明确 incomplete，不能用相同数字 ID 猜映射。没有原 create 引用的旧出库更新、非标准聚合行及预售专属资金方案尚需其明确批次/行/首款契约；在这些输入不足时保持阻断。本地 typed contract、收款确认/退款、核销/冲回、分批发货等命令已有独立领域执行适配；需要真实媒体的操作不会绕过检验门禁。

## 验证证据范围

`test_commerce_shadow*` 使用合成业务输入和独立持久候选数据库，验证来源事务与 outbox 原子性、正式失败 rollback 后诊断、unknown 终局追加、乱序阻断、权限撤销、过程重启/重复投递，以及实际本地合同/资金/核销/结算调用。旧路线集成场景包含真实当前订单 HTTP 执行器、持久发送 claim、回款协议与原回款绑定验证、原出库计划精确核验，再经独立 CLI 重放两次；没有把正式结果导入候选账本。

这些是隔离开发验证，不代表生产启用或真实银行/仓库验收。来源操作之外的小满手工改动仍必须显示 observed-only/覆盖不足；不能把未观察到的改动当作已核验一致。
