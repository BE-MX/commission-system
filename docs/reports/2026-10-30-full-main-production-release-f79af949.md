# 2026-10-30 最新 main 生产发布

已部署版本：`f79af9499de46f9609c93872648af9b2f519aa09`。发布 ID：`454cbb57b56c4a0ababc34395ec7620c`。范围：`office-and-cloud`。用户明确授权最新 main 部署和标准迁移。

## 发布结果

- 办公室固定入口 `D:/commission-system/deploy/deploy.bat --revision f79af9499de46f9609c93872648af9b2f519aa09 --no-pull`，先 `--prepare-only`，成功后同一候选正式激活。部署器、迁移协调和服务控制均走标准流程，没有开发机直连升级数据库、手动启动后端、stamp、downgrade或覆盖数据库。
- prepare：441.48秒；activate：224.81秒，均退出0。办公室和北京后端实际HEAD独立读回一致；publish-current=succeeded，schema-writers=completed，受管目标deferred=[]。
- 本轮包含退货及本地负数回款/GMV/提成扣减、外贸回款截图选填、出库按实际订单业务员过滤。发布前生产为7b5fdd0b，最新origin/main固定为f79af949。
- 办公室和北京后端、色块服务/路由、五个登记静态站、出库轮询器与邮件Worker的标准受管发布完成；未变化的组件复用并校验制品。

## 数据库与退货结构

标准迁移协调器执行 `213_salary_snap_export_cols → 214_sales_return_ledger`。待迁移时独立DBA凭据检查通过，按登记清单暂停并排空writer；迁移只由办公室入口统一执行一次，两地共享同一commission_db。正式激活恢复原运行基线，日志完成后无待恢复迁移。

独立只读SELECT/metadata回读确认：

- 唯一Alembic版本为214；8张退货领域表存在，116列的列名集合及可空性与模型一致。
- 9个外键数量与模型一致，子列/父列都是匹配的signed bigint；原ark_invoices.id在发布前已核实为bigint。
- `synced_payment.source` 为 `varchar(24) NOT NULL DEFAULT 'okki'`。
- 6项退货权限元数据已由标准启动种子建立；未在验收中给人员扩大权限。
- 两站 `/api/sales-returns` 未登录请求返回JSON 403，鉴权生效；没有在生产创建验收退货单、负数回款、提成批次或执行付款。

实物收货和检验已发布；权威库存入库接口仍未接通，界面保留“待权威入库接入”，不自动增加库存。上述结构/运行验收不冒充登录态生产业务提交测试。

## 健康与原状态

- 26项必需部署后检查全部通过。
- leshine.work、leshine.cloud、pm.leshine.work、media.leshine.cloud、shop.leshine.cloud均HTTPS 200；两地主站首页SHA256均为 `678a60feb04a920854e629b3ac6f03752e7e7616dc10affb12081558f0facebd`。
- 办公室CommissionSystem/WhatsAppConnector、北京ark-backend和shipment-tracking-mcp恢复运行；出库timer恢复原active/enabled。
- 邮件Worker保持原inactive/disabled，新加坡历史okki-sync保持inactive/masked，没有因发布擅自启用。
- 未登记探针的独立服务和外部终端不计入本次成功范围。静态/候选清理按标准流程登记deferred维护，不额外执行删除。

## 验证与证据

- 合并后隔离核心回归202 passed、前端25 passed；前轮真实MySQL迁移/并发7 passed。此次发布协调器相关隔离测试25 passed；标准候选主站构建成功，PM与门户未变制品复核复用。
- 初次并行只读检查发生在本轮prepare持锁期间，唯一必需失败是“发布锁存在”；确认是本轮发布器PID，无删锁或重发。正式发布后全部26项通过。
- 本地106个原有待保留文件在文档更新前SHA256均一致。之后只补本报告及对应状态链接，原有无关改动保留，未额外提交/推送文档。
- 证据目录：`.deploy_state/full-main-release-20261030-f79af949/`，含candidate/preflight/schema_precheck、prepare/activate-readback、postcheck、readback、final-receipt、local-preservation及deploy-checks.log。完整prepare.log/activate.log保留在办公室同名目录。
- 当前生产入口：[退货单管理](https://leshine.cloud/invoice/sales-returns)。

收尾复查：102个无关文件中101个仍与发布前哈希一致；`docs/superpowers/plans/2026-10-30-domestic-customer-followup-phase1.md` 期间出现并行更新，本次未写入或回退该文件。Git巡检以本地快照执行，结果留存在证据目录git-sweep.log。
