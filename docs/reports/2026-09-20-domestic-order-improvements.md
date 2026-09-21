# 内贸订单优化交付记录

状态：实现、回归与独立审查完成；用户已授权合并推送，本次交付不含生产发布。
分支：`codex/domestic-order-improvements`。

## 业务结果

- 会员调整不是未生效：只读查询确认“扬州假发王国新”（客户 550）黑卡调整申请 20 在 2026-09-17 17:25:15 通过，随后充值申请 22（2,994 元）于 17:25:36 通过，按单笔充值规则降为非会员。用户确认保留规则；充值弹窗、申请列表和审批确认增加覆盖人工等级的提示及充值后等级预览。未修改客户等级。
- DO20260919-002：原价 1198、系统至尊会员价 960，规则为 `member_fixed`，并非手工改价；查询时已为生产中。新建/草稿提交改为仅实际商品价偏离默认会员价才审核，正常会员优惠直接结算。未重写历史订单状态或扣款。
- 订单详情显示总金额、数量、默认优惠价、实际优惠价、手工费和明细金额。待审核明细的实际价偏离默认价时，两处金额用荧光黄色标记。默认价保存独立快照。
- 订单列表每行新增“批量打印逐件码”，弹窗按产品序号及单件顺序生成全单标签；每批 200 件，跨批不截断，数量变动或任何批次失败则不提供部分打印。所有打印模式阻止旧请求覆盖新窗口。
- 新增 `sample=样单`。样单普货优惠价允许 0，创建、草稿编辑、追加和提交均保留显式零值；零价仍按默认价差异审核。禁止在制单直接追加或改成零价，零价样单不能直接改为普通类型。
- 同链路修复草稿手工费丢失：保存成交价包含手工费，提交报价快照不包含手工费。

## 验证

- 隔离 SQLite：`test_domestic_order_improvements.py`、`test_domestic_review_flow.py`、`test_domestic_member_pricing.py`、`test_domestic_customer_order_controls.py`、`test_domestic_attribute_cutover.py` 联合运行 **422 passed, 1 skipped**。之后新增的零价编辑/追加/审批边界 **2 passed**，合计覆盖 424 个通过用例；跳过项为原有可选测试。
- 前端 Node：订单改进、会员价格、打印、订单编辑、建单状态五组，**33 passed**。
- `npm run build` 通过；保留已有 chunk 大小和混合动态/静态导入警告。
- Edge 无头浏览器、真实 Vue 组件、模拟 API：详情总金额正确，改价明细有 2 处荧光金额；跨两个产品、跨 200 件分页完整生成 203 张标签；无 pageerror。未向物理打印机发送任务。
- Alembic 单 head 为 `160_domestic_price_review`，MySQL 离线 SQL 编译通过。未连接生产执行迁移。
- 独立 agent 审查已完成；已修复其指出的草稿参数传错、手工费、零价绕过及打印旧请求覆盖问题。
- `git diff --check` 通过。`check_conventions.py` 被原有 8 处 UI 行数基线过期阻挡，涉及 AssetLibrary、TagDimensionManage、DesignManage、CaseLibraryView、KnowledgeWorkbench、KnowledgeEditor、ProductionOrderManage、AIManager；本次均未修改。另执行该脚本的增量 `check('HEAD')`，无发现，不等同于完整门禁通过。
- `git_sweep.py --no-fetch` 已运行，结果为本地远端引用快照；未自动推送、合并或清理其他任务分支。

## 发布与证据

- 发布需经项目统一部署入口运行迁移 160：新增 nullable `default_discount_price`，登记样单字典。迁移不改历史金额、状态或会员等级。
- 历史系统定价直接作为默认价；历史手工价缺新快照时按已保存原价、会员等级和属性恢复对照。本次定价算法版本不变。
- 截图：工作目录 `tmp/domestic-review-ui.png`、`tmp/domestic-batch-print-ui.png`。浏览器模拟脚本与页面保存在 `tmp/domestic-ui.cjs`、`tmp/domestic-qa.html`；运行时将页面暂放 frontend 根目录，启动本地 3189 Vite，全部业务 API 均由脚本模拟。
