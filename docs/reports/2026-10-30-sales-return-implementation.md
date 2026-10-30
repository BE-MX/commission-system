# 外贸退货单本地实施与验收

日期：2026-10-30。分支 `codex/sales-return-design`，基点 `ecfba4b7f0f13f880bf5fd63375cd33e4f216742`。工作区 `D:/MyProgram/commission-system-codex-sales-return-design`。开发与验收已完成；本轮用户追加授权提交、合并并推送 origin/main，不部署、不执行生产迁移。Git 结果以提交和远端引用读回为准。

## 交付行为

- 「订单管理 → 退货单管理」支持范围内客户、真实已出库外贸订单、精确原产品行、数量、货款冲减、实际退款、原因及退货退款/仅退款。发票与出库单均可带原单进入。历史没有方舟 PI 的外贸订单在来源可核验时同样支持。
- 生效事务同时保存不可变的货款冲减、原回款分摊、本地负数回款和计提输入。回款统一列表分页筛选包含本地退款，明确“仅方舟记账”；不会投递小满或自动银行转账。实际付款和资金收回单独登记证据。
- 货款冲减 D、现金退款 R、未收减免 W=D-R 分开。1000 美元订单实收600整退：GMV -1000、回款 -600、未收减免400。R=0不生成零额回款；仅退款不扣实物数量，纯实物收回不能重复退款。分次数量与金额独立累计；分钱尾差仅从此前按全额定价退回的数量吸收，不把协商少退金额转给下一件。
- GMV按退货生效当期形成独立负数事实，接入日报、业绩目标、战报/奖励、年度/节日统计与订单洞察；不制造负订单数或新签数。原订单资格、人员和部门归属冻结；各报表分类仍按原订单核算身份裁定。
- 提成按原款实际计提本金、原人员及各角色实际计提金额累计扣回，手续费与现金本金分离。跨期扣本期，已结算历史保留；当前客户换人或改比例不改变原受益人。缺历史依据显示待核对并阻止确认，不能悄悄套用当前配置。提成确认与退货生效共享互斥，晚到退款在下一合法批次补计。
- 预售使用精确原出库批次与原款分配，退款不能借用其他批次本金。原回款/原报价/原应用金额保留，后续收款和发货按净债权、净现金和可证明的原款信用计算。已消费的信用不能二次退款，仍被引用的退货来源不能直接冲销。原未收预登记款超过净债权时必须核对、更正原款，不会当成实收退款或按旧金额继续收款。
- 分批实收、合格/不合格/待检及后续检验已实现。后续检验只分类原待检量，不重复增加实收。已有实物收货或实际付款未收回时，整单冲销被保护。

## 明确边界

1. 首期只覆盖外贸已出库订单，内贸未接入。负数回款只在方舟。
2. **权威退货入库接口尚未接通。** 已实现实际收货和检验；合格货显示“已检验 · 待权威入库接入”，不增加可售库存。现有入库镜像没有可证明的写入契约，stock端点明确409，不以手填单号伪造成功。
3. 外部修改了原已退明细身份/数量/金额、原款本金/币种或原订单核算归属时，阻断再次生效并要求核对；已入账历史不会跟随重写。
4. 实际支付退款、外部发货以及真实仓库入库均未执行。本轮没有生产写入。

## 验证证据

### 浏览器实际操作

使用独立 Chrome（Terra xhigh）访问 loopback 隔离服务。登录外壳和基础订单为合成数据，退货、回款、GMV、提成、收货和检验走真实 FastAPI 路由与业务服务，内存SQLite不连接生产。

- 整单 `TH202610308D3DD4893BD5`：10件、D1000/R600/W400；统一回款-600、Q4 GMV-1000。
- 实际触发本期提成计算：原业务员70扣12、原主管oldS扣6，错误列表为空；新归属人员不受影响。
- 实收10后先检验4合格/1不合格，再检验剩余5：最终合格9、不合格1、待检0，实收仍10。页面显示待权威入库接入。
- PI-101搜索、统一回款查看链接和390×844窄屏检查通过；表格保留横向浏览。
- 保存后误报未保存问题已修复：新建、编辑保存直接进入详情；已保存无改动可关闭，真正未保存的修改仍受保护。
- 浏览器没有error；有既有 `ElTableColumn` 重复注册warning。原链路未提前启用请求级捕获，不宣称已取得网络请求追踪。

证据在 `tmp/sales-return-browser/`：`05-receipt-list.png`、`08-inspected.png`、`12-commission-detail.png`、`13-unsaved-guard.png`、`14-new-saved.png`、`15-edit-saved.png`、`16-clean-close.png`。

### 自动化与数据库

- 前端两组行为回归：25 passed；新增保存关闭保护用例在修复前明确失败，修复后通过。`npm run build`通过，日志 `tmp/sales-return-final-frontend-build.log`。
- 扩大后端回归：2393 passed、18 failed、3 skipped。将相同18个失败节点在未修改基点导出的独立副本重跑，18个全部同样失败，清单完全一致；包括历史迁移head硬编码、旧fixture缺检验要求、外部调用缺mock和旧出库行为断言。本轮不修改这些无关基线测试，也不宣称全仓绿。日志 `tmp/sales-return-backend-regression.log`、`tmp/sales-return-baseline-regression.log`，比较证据 `tmp/sales-return-baseline-comparison.json`。
- 最终核心回归：`test_sales_return_*` + `test_commission_calculator.py` + `test_presale_runtime.py`，201 passed in 54.02s，日志 `tmp/sales-return-final-core.log`。之后资金分摊新增最后一条 A/B 信用复用选款案例，该文件18 passed；独立审查对最终 `policy + funding + presale_adjustments` 复验54 passed in 9.91s，覆盖末次增量。另预售/先发后收/汇总回款/回款管理关联回归131 passed。各组有重叠，不相加充作独立用例数。
- 独占本地 MySQL8.0.46：7 passed。迁移214重复运行、单head、FK类型核验；真实RR隔离行锁等待、争用最后额度、相同提交键/未知应答、事务失败回滚及提成确认与退货两种竞争顺序均有验证。基于performance_schema的实际锁等待，不用固定sleep猜测。最终复验7 passed in 9.97s，日志 `tmp/sales-return-final-mysql.log`；证据 `tmp/mysql-sales-return-final-7c72459579704f3185212df5e7d65245/runtime.json` 与 `mysql.log`；实例已正常停止。
- 独立代码审查通过：当前审查范围无剩余阻断。修复了原款信用复用后的回读/重放歧义、已消费信用二次退款、余额足够但冻结来源被冲销、零退款报价身份及仓库响应财务字段泄露等具体问题，均有有区分力回归。
- `python scripts/check_conventions.py --strict`、`git diff --check`、`git diff --cached --check`通过；日志 `tmp/sales-return-final-conventions.log`。`python scripts/git_sweep.py --no-fetch` 已执行，只是本地快照；未推送/合并/清理其他任务。

## 本地验收入口

- 已生效整链例证：<http://127.0.0.1:4323/invoice/sales-returns?order_id=101>
- 对应回款：<http://127.0.0.1:4323/invoice/receipts>
- GMV与提成事实：<http://127.0.0.1:4323/tmp/sales-return-acceptance.html>
- 可继续编辑的独立草稿：<http://127.0.0.1:4324/invoice/sales-returns?order_id=101>，本实例与上例互不共享数据。

仅监听127.0.0.1；后端分别8432/8433。启动脚本与隔离保护见 `tmp/sales-return-acceptance/README.md`。数据库为内存，重启会清空合成案例；保留截图和日志为证。

停止旧8431预览后端的操作曾被自动审批以“blocked by policy”拦截，未执行；未通过其他方式重试。旧进程保持闲置，验收使用新端口。后续清理本次隔离MySQL临时数据与基线副本也被同一自动审批以“blocked by policy”拦截，删除未执行；临时目录、日志与证据均保留。此限制不涉及生产环境。

## 迁移和权限

新迁移 `214_sales_return_ledger` 继承213，8张领域表和 `synced_payment.source`。拒绝破坏性降级，不删除财务历史。正式迁移必须走既有部署入口，本轮仅本机隔离库验证。

新增权限：`sales_return:read/write/delete/admin/read_all`、`sales_return_receiving:write`；后端启动upsert元数据，不自动给正式用户扩大权限。仓库写响应剔除财务快照。API与表清单已同步到 `docs/api-reference.md`、`docs/database.md`。
