# 方舟交易主系统本地候选验收

分支 `codex/ark-local-commerce`，基点 `d9266945`，唯一Alembic head `191_customer_item_aliases`。目标是将产品、订单、生产、库存、收款、履约及相关消费者落到方舟主账，保留小满客户维护与客户/联系人/归属同步。当前结果为本地实现及合成业务验收；未提交、推送、合并或部署，也未执行生产停写和真实期初对账。

工作树 `C:/Users/windb/.codex/worktrees/ark-local-commerce/commission-system`。P0–P9实现及R01–R22本地验收已完成，逐项证据与现场边界见下表。所有真实数据库写验证使用本工作树MySQL8.4.6、loopback33079和独占测试schema；没有连接生产库或发送实际邮件/钉钉/承运商/小满交易请求。完整迁移库按原始bootstrap和Alembic建立；UI库为模型fixture，两类证据分别记录。

## 本轮核心结果

- 原通用非标经营行数量1、金额1000及原身份/时间/引用完整保留为历史别名；两条真实明细4+6按原InvoiceItem主键接续，活动统计数量10/金额1000。原远端UID可相同，真实来源行键独立。原名称200字符、产品族256字符、经营编号100字符均不截断。
- 四种已核验领料结果（正/负delta × 明确受理/未受理）精确处理到0.001克。实际MySQL两个旧RR事务并发只生效一次；新库存后的重放不回写。未知结果、原预占凭证缺失、成功日志矛盾及活跃取消/同步阻断。
- 历史预售合同1000、首款300，历史已抵100、已发6件、原运费11/13；新分批1+3件、运费5/12，末批只抵剩余200。总收1041、商品合同1000、余额0，原已消费款不能重用；跨批运费对应错误直接拒绝。
- 实际页面承接明确成功的pending100.125克，然后核验期末：已领300.125、实存899.875、预占0、版本4/流水4，流水重算等于实存。期末acknowledge_existing无新运动。
- 后端真实停止/重启后，原记录9/10及以上数量保持；同请求重放没有额外运动。启动当前库时误配legacy，实际uvicorn启动退出3，未监听8017；local正常启动。此保护不等于能识别已被旧备份覆盖的数据库。

## R01–R22证据矩阵

以下“通过”均指本地可验证范围，不替代最后一列的现场事实。测试路径均相对backend/tests。

| ID | 本地实现与证据 | 现场/外部边界 |
| --- | --- | --- |
| R01 | 完整base→125、126受控证据链/复验→173→191；原Invoice/Item/Customer/售后/媒体及原聚合行逐列保留，4产品族列与FK/CHECK核验。`test_local_migration_chain_mysql.py`15通过 | 生产当前revision/备份/停写授权单独核对；合成126标记不是生产批准 |
| R02 | local模式客户来源、联系人、归属与手动客户同步回归；`test_customer_source_projection.py`、`test_invoice_customer_sync.py`；`test_trade_local.py`改名/合并/停用保留交易快照 | 真实客户身份冲突必须核验，不能按数值或同名匹配 |
| R03 | 本地目录/规格/配件/价格；目录页面及API；`test_catalog_inventory_api.py`、`test_catalog_native_consumers.py`、`test_accessory_native_mysql.py`；非标别名、真实完整行和长产品族另有真实MySQL连续履约 | 真实源引用及非标组关联完整性须对账 |
| R04 | 现货/生产/预售制单、确认、变更、取消、单据；`test_invoice_commerce.py`、`test_local_amendment.py`、实际现货/预售UI | 原合同、调整、编号须显式核验 |
| R05 | 库存桶、预占、可售与生产在途分开；`test_stock_reservations_mysql.py`及`test_inventory_mysql.py`并发当前锁/幂等，真实完整链一次放行预占 | 真实各仓库与质量桶盘点 |
| R06 | 原生入库、出库、退回、盘点、调整、调拨、冲销；库存UI，`test_inventory_local.py`/MySQL和期初与普通收货/调整竞争；流水＝余额 | 实际单据与盘点签核 |
| R07 | 完工与验收入库分开、供货与分批验收；生产UI/购物车/工序/打印卡，`test_production_local.py`、`test_production_mysql_regressions.py`、`test_production_native_cart_mysql.py`；原完工进度保留，旧6新4仅后者入库 | 现场在产/已验收原始记录及纸质卡 |
| R08 | 原生领退料/损耗；已扣量承接无再扣；`test_commerce_material_opening.py`、`test_commerce_material_pending.py`及真实pending/期末UI/SQL | uncertain未取得明确结果不能放行 |
| R09 | 付款主记录/纯预收/多订单分配、凭证权限；`test_finance_api.py`、`test_native_form_queries.py`、`test_finance_mysql.py`及真实资金UI | 实际银行流水/凭证核验 |
| R10 | 实际银行费与客户附加费分开、冻结汇率、到期账龄/对账；`test_finance_local.py`和真实资金UI400/费5/净395；原650缩放值保留 | 实际银行费和原汇率口径不能推测 |
| R11 | 确认、退款、贷项、释放/重分配、关闭期间与不可变事件；资金和售后金额/并发回归、真实UI冲回4/退款20，历史后续退款不重置 | 实际银行退款仅由授权人员执行 |
| R12 | 预售纯算法、新首末批UI、历史首款部分已消费连续履约；`test_commerce_presale_continuity.py`和真实MySQL完整链上述300/100/200样本 | 真实各批独立运费和原资金占用 |
| R13 | 本地出库、实际图片上传/检验提交、Word ZIP/XML、旧检验/媒体主键保留；打印/扫码协议和小程序工序服务回归；local显式媒体撤回/物流MCP联合30通过 | 实际纸张打印、硬件扫码、微信设备及承运商外发未执行；占位原照片不证明真实文件存在 |
| R14 | 退货进入隔离库存、补发按批准方案创建0应收普通履约单、退款/贷项关联执行；`test_aftersales_local.py`、`test_aftersales_money.py`及MySQL，完整链实际FK退货 | 原审批及客户退货/退款证据 |
| R15 | 原已付提成身份保留、新核销一次计入、退款关联原USD/RMB剩余；`test_commission_local.py`/MySQL、`test_commission_opening.py`，原7.01保留 | 真实已付批次/逐笔冲回核验 |
| R16 | 经营/复购/采购节/战报/日报统一本地事实与水位、取消退货投影；`test_trade_local.py`/MySQL、`test_pcw_order_analytics.py`、`test_gmv_native.py`、`test_battle_native.py`；历史别名统计不双计 | 真实统计区间/名单及历史映射对照 |
| R17 | 公开库存、色块、MCP隐私及价格契约、外部接入与既有内贸；`test_catalog_native_consumers.py`、`test_color_native.py`、`test_integration_api.py`/native；local客户/内贸独立417通过 | 独立第三方MCP/n8n实例须现场升级/配置，不能由本仓库测试代表 |
| R18 | 归档→完整原合同→资金/履约/生产/库存/物料→联合放行；不可变来源认领、二次导入无新增经济效果，工作台实际预览/承接/缺项阻断/放行 | 真实全量源清单、摘要和同日责任齐全性 |
| R19 | 完整实际MySQL链监听并最终断言交易镜像/HTTP访问尝试0；本地新业务和原责任接续均完成；公开/库存/MCP另有拒绝镜像契约 | 客户同步使用保留的CRM权限；无需恢复交易镜像 |
| R20 | 旧入口先拒绝；实际local注册29个job包含本地投影且不含3旧交易job；独立Node脚本受保护文件拒绝，82测试通过；部署停用/失败恢复16测试通过 | 部署测试模拟systemctl；线上全部实例/外发权限/在途请求仍须实际清点停写回执 |
| R21 | 原子失败回滚/旧RR并发/同键重试；真实停止重启保留原账本并原命令重放；误配legacy实际拒绝，7项磁盘重开＋旧CRM/archive例外回归；[恢复协议](../runbook.md)禁止旧整库覆盖 | 启动保护只识别当前库已有事实；备份/WAL/线上灾备及未升级进程由运维协议保护 |
| R22 | 原生目录/库存/订单/资金/生产/迁移页面、桌面与390px移动检查、真实角色/权限/API、46前端专项、Vite build；北京时间零点/非UTC+8/偏移拒绝 | 设备和真实人员角色上线抽验 |

## 实际验证与可复现证据

- 最新分支新增/修改后端测试59文件：**615 passed、67 skipped，141.53秒**。未提供专用MySQL连接的该轮主动skip真实MySQL项；不能把skip记为通过。日志`tmp/commerce-complete-branch-tests.log`。补发fixture使用明确审批业务日，冻结126对后续183/189/191逐项声明字段差异，未改冻结合同或削弱约束。
- 完整真实迁移链：**15 passed，129.51秒**；结果`tmp/local-migration-chain/ark_chain_test_b1643a452ff14a0c/result.json`，head191，schema_dropped_after_test/writer_dropped_after_test=true；包括非标、pending及预售连续场景，HTTP/镜像均0。
- 分支全部新增/修改MySQL专项13文件：**64 passed、0 skipped，292.82秒**。日志`tmp/commerce-final-all-mysql.log`，文件清单`tmp/commerce-final-mysql-file-list.txt`。包括真实库存、资金、履约、售后、提成、投影、配件、生产与备货并发。发现的旧客户前置表、189冻结人民币字段及固定业务日夹具漂移已补齐；备货调用真实RC投影建立水位，原断言和业务时序保护均保留。定向前置表不冒充完整迁移约束；完整结构由上一条全链证据承担。
- 生产真实MySQL扫描/验收专项：**7 passed，24.96秒**。日志`tmp/commerce-final-production-mysql.log`；工序完成不增加可售，撤回/权限/幂等保持真实约束。
- local模式客户/内贸独立联合回归：**417 passed、1 skipped，49秒**，唯一skip为既有内贸专用MySQL锁测试；原生分支其他核验与此有重叠，不相加冒充独立总数。
- local显式媒体撤回/物流MCP联合回归：**30 passed，7.38秒**。实际承运商、微信设备及硬件操作未执行。
- 前端相关命令/下载/打印：**46 passed**；构建**19.53秒，122导航条目**。独立外发脚本**82 passed**、部署模拟**16 passed**。日志`tmp/commerce-final-frontend-tests.log`、`commerce-final-build.log`、`commerce-final-writer-node.log`、`commerce-final-writer-deploy.log`。
- 随后按分支新增/修改文件收集全部前端测试：**67 passed，681.95毫秒**，包含原库存页面接管、请求隔离、错误保留/重试和分页；与46专项重叠。日志`tmp/commerce-complete-frontend-tests.log`。
- 实际UI/SQL：`tmp/commerce-pending-ui-result.json`、`commerce-recovery-result.json`、`commerce-legacy-restart-refused.log`和`commerce-migration-pending.jpg`。已有真实现货/资金/两批预售/生产/迁移截图与SQL证据见各增量报告。
- 当前独立复核已覆盖资金、库存竞争、完整迁移、非标映射、权限及恢复边界；发现的问题已修复并定向复验。生产256字符产品族、长经营窗口、原发票独立编号无新增阻断项。
- 最终`check_conventions.py --base d9266945 --strict`、Python改动编译、工作区/暂存区`git diff --check`均通过；`alembic heads`只有191。2026-10-04 05:11 `git_sweep.py --no-fetch`已完成，结果为本地远端引用快照，没有fetch/push/合并/清理其他分支。日志`tmp/commerce-final-conventions.log`、`commerce-final-git-sweep.log`。真实数据库读回剩余一次性`ark_inventory_test_*`/`ark_chain_test_*` schema数量为0。

所有SQL测试目标校验必须保留loopback及独占schema限制；日志只保留结论和非敏感事实，不保存连接凭据。保留本地运行环境、合成样本和验收证据，已清理本次安装下载压缩包。

### 核心复验命令

在上述工作树根目录使用本工作树Python虚拟环境；`COMMERCE_TEST_MYSQL_URL`由本地隔离环境提供，只允许loopback、无数据库名/查询覆盖，每项测试创建并清理自己的schema。禁止使用生产连接。完整链与并发专项分别执行，不把缺连接时的skip算作通过。

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_local_migration_chain_mysql.py -q
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_finance_mysql.py backend/tests/test_local_fulfillment_mysql.py backend/tests/test_aftersales_local_mysql.py backend/tests/test_aftersales_money_mysql.py backend/tests/test_commission_local_mysql.py backend/tests/test_replenishment_native_mysql.py -q
backend/.venv/Scripts/python.exe scripts/check_conventions.py --base d9266945 --strict
backend/.venv/Scripts/python.exe scripts/git_sweep.py --no-fetch
```

## 切换前仍须取得的现场事实

真实合同及所有未结责任的全量对账、媒体文件实际存在/可读、各独立writer停写和写权限撤销、受保护配置与全部应用版本一致、硬件/微信/外部物流验收，以及生产发布授权。此处是可供审阅的本地候选，不把上述未执行事项称为完成；不自动关闭整个客户同步、不自动发送消息或发布。

早期增量报告中的“仍需开发/平台用量限制”记录当时状态；后续实现以本报告和docs/handoff最新条目为准，早期验证的实际边界不改变。
