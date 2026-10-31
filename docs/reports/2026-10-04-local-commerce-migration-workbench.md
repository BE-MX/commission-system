# 交易历史承接工作台验证

后续补充已完成：原非标聚合身份、pending明确结果处置、旧预售连续履约、真实重启/原命令重放及完整证据矩阵见[候选验收](2026-10-04-local-commerce-candidate.md)。本页其余内容保留当时验证状态；最新head191及结果以候选报告为准。pending实际UI处置100.125克后已领300.125/实存899.875/预占0，期末acknowledge_existing保持流水4/版本4，无二次扣料，证据`tmp/commerce-pending-ui-result.json`、`tmp/commerce-migration-pending.jpg`。

分支`codex/ark-local-commerce`，本地开发中，未提交/推送/合并/发布。本报告记录管理员工作台的实现与实际验证，整体切换候选验收继续。

## 行为

`/commerce-migration`仅允许`commerce_migration:admin`。选择已核验JSON时自动识别目录、整单、资金、历史发货、生产、库存或领料责任；先只读预览再承接。不可变批次身份及命令在结果不确定时保留，只能原参数重试；明确409后废弃旧预览和版本。重复点击不会再次发送。

摘要列表联合精确筛选和分页，显示当前责任状态，不批量下发原始大快照。详情读取原始事实、源文件摘要、核验说明和原承接结果。选择待放行整单/生产后，服务端生成当前版本命令及切换日；页面列出缺失责任，执行时重新锁定复验。

## 实际浏览器

loopback隔离UI库`ark_browser_test_20261003`、后端8007、前端3007，全部合成源事实。UI库以原有浏览器fixture补齐模型列，不能作为完整Alembic迁移证据；完整迁移另见下段。

通过页面依次预览并承接目录、既有完整订单、600历史回款、6件历史发货/600已消费核销及实物期末10件。资金未承接时放行按钮禁用并显示明确缺项；补齐后成功放行为部分出库。同一原Invoice/InvoiceItem/CustomerOrder保留；只读SQL核对合同1000、数量10、历史已发6、当前预占4、实物10、已收600、余额400、已消费600；两条库存流水为期初和当前预占，没有历史再次出库。原600/650/3900回款及检验照片主键/明细ID保留。

记录证据详情在浏览器显示来源租户/原身份/切换日/摘要。证据下载按钮已触发，但IAB下载事件超时，不能宣称文件已落盘；共享下载器的字节、MIME、文件名和URL存续测试通过。照片路径为合成占位，只证明关联身份，不证明真实媒体文件存在。

390×844实测导入、筛选和提示可用，document scrollWidth=clientWidth=390；表格内部横向滚动。1440×1000核验依据按钮正常横排，当前状态正确。截图保存在`tmp/commerce-migration-activated.jpg`、`tmp/commerce-migration-mobile.jpg`、`tmp/commerce-migration-desktop.jpg`；SQL断言结果`tmp/commerce-migration-ui-result.json`。

## 自动验证

- 前端`commerceMigrationCommands`及共享`download`：14项通过，覆盖不确定响应同命令、文件替换阻断、409失效、双点击和下载字节/MIME/文件名。
- 后端`test_commerce_migration_workbench_api`及`test_commerce_order_activation`：6项通过（3.32秒），覆盖普通财务/订单/生产权限拒绝、分页真实计数、摘要/详情分离、只读prepare、真实放行与重放及原订单后续收款/发货闭合。
- 完整真实MySQL8.4.6迁移链及业务场景：15项通过（126.39秒），唯一head190。包括原表逐列保留、190唯一/FK/RESTRICT、RR并发一次预占、旧RR写入口拒绝、历史生产只验收余量及正常收款发货。强化HTTP guard记录所有尝试，吞掉异常也令测试失败；实际承接链镜像查询/HTTP调用均0。
- 迁移结果读回`tmp/local-migration-chain/ark_chain_test_e9304558b09f4b00/result.json`，schema_dropped_after_test/writer_dropped_after_test均true。
- 前端构建19.07秒、122导航条目；独立代理复验命令6项、后端6项，并验证prepare后版本/资金/库存变化拒绝，无新增经济效果。

## 继续工作

非标历史映射、未决原领料动作的核验处置、更多预售历史分批样本和完整R01–R22证据矩阵继续。合成闭环不能替代生产切换前的真实期末对账；实际纸张打印、硬件扫码和外部物流发送未执行。
