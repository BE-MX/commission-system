## 2026-09-18 六处旧按钮尺寸修复（合并推送交付）

分支 `codex/fix-small-buttons`，worktree `D:/MyProgram/commission-system-codex-small-buttons`。仅移除CustomerMediaReview的编辑标签、AssetTagEditor的清除、CustomerMediaTagPicker的清除/新建/取消/新建标签共6处el-button的small尺寸，沿用默认尺寸；输入框、标签、选择控件及事件逻辑保持原样。`npm run build`、`git diff --check`通过；约定检查的6项legacy small告警消失，仍有7项既有行数基线告警，未修改基线。未做登录页面浏览器验收。用户已授权合并main并推送origin；本轮不部署，完成交付后清理本任务分支及worktree。

## 2026-09-17 库存单自动回款与回款管理（Codex，合并推送交付，未部署）

- worktree `D:/MyProgram/commission-system-codex-receipts`，分支 `codex/receipt-management`。库存单截图必填同步校验、完整同步后唯一自动建回款、手工回款、列表/详情/私有凭证、失败重试与未知结果核对已落地。
- 原币余额包含小满已生效回款、本地占额与自动意图，同远端ID去重；订单锁+幂等键+余额版本+租约令牌防重复。截图仅方舟留存。`RECEIPT_SYNC_ENABLED=False` 默认不向小满写入，启用前核对待发单及 `collect_status=0` 对既有财务/提成的影响。
- 迁移已串联154→155公告→156回款，确认单head。办公室为凭证固定存储，北京配置 `RECEIPT_STORAGE_PROXY_URL=https://leshine.work`；部署验收包括JWT互认、12m入口上传限额、持久目录备份与连通性。
- 530项受影响后端测试通过，前端构建通过，CUA本机虚构数据手工创建/上传/详情、暂停提示及390×844窄屏验证通过。独立审查无遗留阻断项；增量规则及diff检查通过；全局规则仍有11项无关UI基线问题；Git巡检已执行no-fetch。
- 合并最新主线后582项集成回归通过、前端构建通过，补齐调度器任务清单，独立集成审查及迁移单head检查通过。验证记录归档主目录 `tmp/receipt-merge-preserve/evidence/`；主目录原设计草稿备份在其上级，其他未提交成果保留。
- 用户已授权合并main并推送origin；集成已保留公告模块及其它主线成果，交付后清理本任务临时worktree。未部署、未执行生产数据库迁移或真实小满回款写入。详见[实现与验收说明](requirements/2026-09-17-receipt-management-implementation.md)；设计及可交互原型一并保留。

## 2026-09-17 Excel 导入 Model 回填（合并交付，未部署）

任务 `codex/invoice-import-model`，worktree `D:/MyProgram/commission-system-codex-invoice-import-model`。根因是 `load_okki_rows` SQL 未选 model，导入产品索引也未向候选/唯一匹配结果传 model；前端原本已经读取 `matched_product.model`。两处补全，型号取匹配产品目录，不根据 Excel 文本猜测，也不改变匹配、SKU、价格或数量规则。

两个新增后端回归先以缺少 model 失败，再修复通过，分别覆盖唯一匹配和歧义候选；后端粘贴/截图导入及 SKU 目录86项测试、前端导入16项测试通过。浏览器模拟API走编辑→Excel粘贴→校验→加入，Model立即显示GW-MODEL，导入成交价34.0000保留，未保存真实订单；证据保留在主目录 `tmp/invoice-import-model/`。独立审查未发现阻断问题；增量规则与diff检查通过，全局约定检查仍被10项主线既有UI债务阻挡，Git巡检为no-fetch本地快照。用户随后授权合并并推送 origin/main；本轮不部署，交付后清理本任务分支与 worktree。

## 2026-09-17 设计管理列表备注编辑（Codex，合并推送交付）

- 分支 `codex/design-remark-dialog`，worktree `D:/MyProgram/commission-system-codex-design-remark`。排期任务列表的排期备注、预约备注各自可点击弹框修改；空值展示“添加备注”，弹框明确类型。待确认列表沿用预约备注入口并改为支持键盘的按钮。
- 任务备注走新增 `PUT /api/design/tasks/{task_id}/remark`，预约备注沿用预约接口，按 task/request ID 分开保存，支持清空。成功更新当前行并刷新当前列表，失败保留草稿，重复提交有保护。无迁移、无生产写入。
- 验证：6 项隔离 SQLite/后端测试、5 项前端 composable 交互测试、`npm run build`、独立静态审查通过。测试覆盖 ID 分流、备注互不覆盖、清空、失败保留草稿、重复提交、无效/已删除任务及回滚。未做真实登录页面浏览器验收。
- `check_conventions.py` 完整检查报 11 项 UI 债务：主线已有 10 项，本次 DesignManage.vue 增加 10 行触发行数基线不匹配（762→772行）。页面已有独立 composable，本次为现有备注列的小范围扩展，不为行数机械拆分或抬高基线；底层增量规则检查无违规，`git diff --check` 通过。构建日志保留于主目录 `tmp/design-remark/`，Git 巡检为 `--no-fetch` 本地快照。用户已授权合并并推送 origin/main；本轮不部署，交付后清理本任务分支与 worktree。

## 2026-09-17 出库单打印与 Word 客户名称遮罩（Codex）

- 来源分支 `codex/outbound-customer-mask`；用户已授权合并推送到 `origin/main`，完成后清理本任务分支与 worktree；本轮不部署。
- 两个文档模板仅输出客户名称前三个字符 + `***`（如 `Inessa Wassiljev` → `Ine***`）；空名称保持空白，短名称追加星号。列表、扫码、验货单及原始数据不变。
- 验证：打印模板 Node 测试 9 项通过；Word/打印排序 pytest 4 项通过（内存 SQLite）；前端构建通过；`git diff --check` 通过。约定检查受 10 项既有 UI 债务阻断，均在本次改动之外；Git 巡检已执行 `--no-fetch`，只代表本地快照。

## 2026-09-17 全平台列表操作列防遮挡（Codex）

- 分支 `codex/table-actions-wrap`：主站 AST 扫描覆盖 77 个 Vue 文件中的 103 个操作/处理列，统一接入 `table-action-column`；按钮组统一 `table-actions`。修复全局 list-table 单行省略导致尾部按钮裁切，以及发票、内贸客户、备货等局部 nowrap 布局。普通文本列仍保留省略，权限、事件和业务接口未改。
- `frontend/src/styles/table-actions.css` 统一换行、间距、长文字与行高；表格容器/视口 ≤768px 取消左右固定以免相互覆盖，横向滚动访问全部列。PM 任务列表补操作表头、按钮换行与独立横向滚动。
- 验证：103 列接入扫描与9项既有内贸编辑测试通过；主站与PM生产构建通过。隔离浏览器验证覆盖1440/768/390px视口、320px窄容器，多按钮/100px长文字/64px图标/普通按钮/禁用/加载/权限变化/下拉菜单/确认弹层；所测按钮均在单元格内，手机页面无横向溢出，实际点击提交/生产下单及菜单项成功。模拟旧版时269px单元格内容达329/390px并裁切，新版换行消除。浏览器测试页在 `frontend/tests/fixtures/table-actions/`，不操作生产数据；不是逐个登录103个真实列表进行业务验收。
- 独立代码审查通过。完整 `check_conventions.py` 仍被main已有10项UI债务阻断（已对照主目录确认）；本次增量检查无违规，未为通过检查改动基线。
- 用户已授权合并并推送 origin/main；本轮不部署，交付后清理本任务分支与 worktree，验证日志保留于主目录 `tmp/table-actions/`。原 DO20260917-002 第三条改价“点击没反应”仍未复现，本次操作列修复不宣称解决该保存问题。

## 2026-09-17 产品明细复制与空行（合并交付，未部署）

任务 `codex/invoice-row-actions`，worktree `D:/MyProgram/commission-system-codex-invoice-row-actions`。库存单/生产单产品区将「添加明细」拆成「复制一行」和「添加空行」：复制最后一条产品明细、排除配件行并清除数据库行ID，无产品时禁用；空行不带入产品、规格、价格、数量、折扣或半成品计划，新单首行同样为空。复制空行保留空数量/折扣。Excel导入仍识别并移除全空占位行。

验证：23项前端专项测试、生产构建和独立审查通过；增量规则/diff检查通过，全局约定检查仍被主线既有10项UI债务阻挡。Git巡检为no-fetch本地快照。浏览器模拟API覆盖两类订单按钮、空值展示、全部删除后按钮禁用/新增、复制最后产品行（跳过配件）、半成品计划独立以及空行不继承内容，未保存真实订单。截图和脚本保留在主目录 `tmp/invoice-row-actions/`。用户随后授权合并并推送 origin/main；本轮不部署，交付后清理本任务分支与 worktree。

## 2026-09-17 出库打印检验状态文案

- `codex/inspection-status-label`：出库单打印列表 `draft` 展示名由“草稿”改为“检验中”；状态值、颜色与业务流程不变。
- `npm --prefix frontend run build`通过；完整约定检查仍被10项既有UI问题阻断，差异检查通过；用户已授权合并推送；本轮不部署。

## 2026-09-17 9月新签大屏（合并推送交付，不部署）

- 亮哥已确认设计、实现与嘉树LOGO，并明确授权「合并推送」。本轮交付到main，不部署；来源任务分支`codex/september-screen-prototype`。合并后清理本任务分支与worktree，其他代理改动保留。
- 方案：`docs/requirements/2026-09-17-september-new-sign-screen.md`；交互原型：`docs/requirements/september-new-sign-prototype/index.html`，截图与验证记录同目录。
- 已实现`GET /api/public/festival/september-new-sign?key=`与`/festival/september.html`，新屏进入旧5屏轮播链路；Vite新增HTML入口，复用tokens和北京时间工具。固定读取OKKI，不改8月窗口/143目标/积分。无迁移、生产写入及新通知。
- 嘉树LOGO已按用户提供的「露露-嘉树.png」原图接入，资源为`frontend/public/festival/assets/team-logos/jiashu.png`；正式屏与原型同步替换文字占位。
- 规则：7队108 + 嘉树5 = 113，只展示目标/完成/完成率和第一团队；≥2人且100%达标、精确完成率优先、同率比有效新签金额、仍同则并列，嘉树不入评选。名册只读核对匹配；客户跨组冲突等异常暂停总进度和第一评选。月底默认待复核，Settings.FESTIVAL_SEPTEMBER_FINALIZED默认false。
- 66项后端相关回归、7项前端测试、生产构建、4视口和六频道浏览器检查通过；独立审查3项发现（历史标签漏排/历史冲销/BFCache恢复）修复复核通过。完整规范检查仍被基点既有10项UI债务阻断，本次增量无违规。Git巡检为no-fetch本地快照。
- 验证证据归档主目录`.deploy_state/september-screen-20260917/implementation/`（原`tmp/september-implementation/`），原型检查脚本存同级`prototype/`：构建日志、浏览器结果、实际快照和截图、只读核对脚本；09-17 13:16北京时间快照总69/113=61.1%，无名20/10=200%为第一，数据质量正常。原设计原型仍为演示数据。
- 后续若授权上线，需合并后通过项目部署入口发布后端及完整前端构建；不能只复制源HTML到public。本轮仅执行已授权的合并推送，不部署。

## 2026-09-17 自动出库等待库存（Codex）

- 分支 `codex/outbound-stock-wait`；实现明确库存不足 → waiting_stock → 每15分钟目标仓库可用库存复查 → 防重复核 → 补建。不限等待次数，其他不确定提交继续隔离。
- 库存拒绝意图保留证据，后续提交独占 `.retry-N` 意图，库存查询异常不创建。
- 历史问题单457（翟 #260943）/任务31已按用户授权转为生产 `waiting_stock`。持有轮询锁，核验人工补建审计中的明确库存拒绝、实时无关联出库单，保留旧意图与任务快照后标注 stock_rejected；线上 dry-run 返回 waiting_stock，SKU5726需5件、目标仓库可用0件。未创建出库单，后续每15分钟复查。
- 代码0631c29f已合并并推送 origin/main。使用 `deploy/deploy.bat --okki-outbound-only` 先预检再发布新加坡轮询服务，digest `f77a7ac81840b5824f401c2539966b37972af229ee206f65a831db176d89f04f`；两份线上JS SHA-256与发布源码一致，timer active。本次无数据库结构变更，不发布其他应用。
- 验证：`node --test deploy/tests/test_okki_outbound.mjs` 32项通过（含最新主线备注功能）；增量约定扫描无违规，完整约定检查被主分支同样存在的10项前端UI基线问题阻断；`git diff --check`通过，Git巡检为 no-fetch 本地快照。

## 2026-09-17 出库检验改进集成

用户授权合并推送本轮返回主页、钉钉PDF、验货查询和发票备注映射。基于远端main 16fbb879，在codex/shipping-notice集成689a5265；冲突仅为文档新增章节，全部保留。候选67项相关测试通过、增量约定检查无违规；合并期间主线新增9bee0369发票SKU修复，已保留，42项Python（含SKU专项）与34项Node回归及前端生产构建通过。随后主线新增8d85170f统一客户搜索，已继续保留集成，最终47项Python、38项Node测试和生产构建通过。验证后在主目录合并并推送main；不部署，不改生产数据。测试截图、PDF样张和浏览器脚本收尾保存到主目录 `.deploy_state/shipping-improvements-20260917/`。

局域网上传诊断（只读配置＋无鉴权拒收测速）：用户实际用leshine.cloud，现场该模块走北京→新加坡→办公室；lan.leshine.cloud解析192.168.101.193，Caddy直连办公室8001。内网5MiB测试约0.8秒，work约12秒，cloud写入超时；测试并非真实登录业务上传。已告知公司Wi-Fi使用https://lan.leshine.cloud/shipping/scan。视频前置实时重编码仍会按视频时长等待，未在本轮改压缩策略。

## 2026-09-17 移动出库检验主页查询入口

在 `codex/shipping-notice` 延续已提交ca445a5d的相关页面工作。人员选择主页新增“查询验货单”，支持单号/客户、提交人、提交日期起止、关联订单业务员组合查询，手机结果为卡片，可查看详情和下载PDF，并返回主页。沿用登录账号原验货查看范围；业务员取具体订单归属，不取制单人或客户其他订单。两个口径曾异步询问，未收到答复，已向用户说明按较保守默认实现，未扩大权限。

14项相关Python测试、14项Node测试通过；前端生产构建通过；390px Chrome模拟查询入口→组合筛选→详情→重置→返回主页通过，截图/脚本在tmp/shipping-notice/query-*。独立审查通过，并补同单多订单去重、中文绑定姓名检索测试。默认规范门禁仍为main既有10项UI债务，增量无违规。用户随后已授权本轮合并推送，出库备注修复689a5265已纳入同一集成候选；未授权生产发布。

## 2026-09-17 扫描页返回主页与钉钉验货 PDF

任务分支 `codex/shipping-notice`，基点16fbb879。扫描单据后顶部增加返回主页，复用结束会话/未保存确认；成功后重新选人，已上传媒体保留。钉钉完成通知OA附带id/version主站链接，打开下载含单头、明细、备注、照片的PDF；旧版本/撤回409，缺少明细/照片503，保留现有查看权限。手机未登录及下载401均保留通知地址回跳。复用既有Pillow/pypdf/中文字体配置，无新增依赖、迁移和真实通知发送。

验证：27项相关Python、13项Node回归通过；前端生产构建通过；Chrome手机390px模拟未登录通知→登录→带版本PDF下载、下载401回跳、扫码详情返回选择人员通过；模拟PDF两页中文照片渲染已检查。独立审查发现并修复MySQL RR照片旧快照、移动登录/401丢回跳问题，最终复核通过。默认规范检查仍有main既有10项UI债务，本次增量无违规。证据在本任务 `tmp/shipping-notice/`（仅测试数据）。用户随后已授权合并推送，本轮不执行生产发布；新接手客户业务员的既有历史订单查看范围限制见module-notes。

## 2026-09-17 自动出库备注缺失修复

任务 `codex/outbound-invoice-remark` 基于16fbb879。根因是受管creator只取方舟发票号、创建payload无remark；已补同一任务关联发票的remark读取与传递，保留换行和空格，创建后回读核对，失败uncertain不重发。已有出库单保持跳过，不补填历史数据。20项Node测试通过（新增映射/真实创建参数/备注截断3项先红后绿，另加发票查询边界），增量约定无违规，默认约定检查仍有main既有10项UI债务。

用户随后已授权与返回主页、钉钉PDF及查询一起合并推送；本轮不部署，历史缺失备注未回填。

## 2026-09-17 发票客户/联系人统一搜索（合并交付）

任务分支 `codex/invoice-unified-search`，worktree `D:/MyProgram/commission-system-codex-invoice-unified-search`。库存单/生产单两个搜索框合为一个，同时查客户名称/ID和联系人姓名；单一私海开关、类型和所属公司标签、分页总数及加载更多。客户切换保持默认资料/价格刷新；同公司换联系人保留手改地址，联系人显式选择优先于默认快照。新增只读 `/customers/options`，数据库分页、最新overlay归属和跨库collation统一，无迁移。

原问题实库只读证据：owner 56046345有126客户，旧接口默认20条。新SQL实测分页50/50/26、126个不同客户；含联系人搜索和有效overlay分支在真实MySQL通过。浏览器模拟API验证库存单/生产单、完整分页、客户/联系人搜索与回填、编辑回显、390px布局、同公司地址保留、快速切换联系人仍刷新价格和不同客户竞态；未创建真实订单。证据保留在主目录 `tmp/invoice-customer-search/`。验证：后端34项、前端12项专项回归通过，前端生产构建通过；约定检查被主线既有10项UI债务阻挡，单独运行增量规则无违规，diff检查通过，Git巡检为no-fetch本地快照。独立审查指出的地址覆盖/价格漏刷已修正。用户随后已授权合并并推送 main；本轮不部署。集成同期主线 SKU 修复，仅交接文档冲突且保留两项记录；合并结果118项后端、24项前端回归和生产构建通过，增量规则无违规。推送后核对 origin/main，清理本任务分支与 worktree。

## 2026-09-17 发票 SKU 目录匹配与非阻断库存提示（合并交付，未部署）

来源任务分支 `codex/invoice-sku-catalog`（合并后清理临时 worktree）。产品 105767890099971（编号6583）的 SKU 105767890100162 在 `okki_product_skus` 已启用，但没有 `okki_inventory` 行，原匹配误返回空 SKU。页面、属性匹配、粘贴/截图导入、保存校验及通用产品解析改查产品 SKU 表，保留停用与归属校验。

亮哥明确：无实际库存只提示，不能限制下单，包括 Excel 导入。按 SKU 汇总未停用仓库 `real_count`，无记录或合计不大于0返回非阻断 `stock_warning`；页面及Excel预览展示“可继续下单，请确认交期”，Excel追加保留提示，换产品清空旧提示。无库存、零库存、负库存、跨仓合计零均有真实服务创建发票的 SQLite 回归；真实业务库只读核验正确返回该 SKU 和库存提示，未写业务数据、未调用外部推单。

验证：发票全组+integration API `406 passed`；前端导入/布局 `16 passed`；Vite生产构建通过。独立审查发现并修正换产品旧提示残留，其他核心链路无阻塞发现。`git diff --check`通过；增量后端规则无违规，但 `check_conventions.py` 被10项既有前端UI门禁阻断（素材/设计页旧small按钮、4个无关页面行数baseline过期），未修改无关文件或弱化规则。Git巡检使用 `--no-fetch`，仅本地快照。亮哥随后明确授权合并并推送 `origin/main`，本轮按该范围交付，不部署；另有 `codex/invoice-unified-search` 同域任务，后续集成需核对重叠差异。

## 2026-09-17 出库默认编号与打印负责人补充

用户明确要求出库单号默认等于发票号、打印负责人显示Eva。受管creator从任务关联ark_invoices取得invoice_no，显式传serial_id，缺号或回执号不一致停止并标记待核对。现有5张本轮自动出库单已通过OKKI编辑接口改为对应发票号；逐张保存受限before/after快照，验证处理人、行ID、数量、价格、币种、仓库、状态均不变，同时更新本地台账和任务回执编号。ly914订单出库ID仍为105791346765650，单号已由XSCK2609170495改成ly914首返出库单，6行52件待出库，handler=Eva，creator=Rainy。

打印修复从真实handler_info.nickname取负责人，制单账号不再进入打印负责人；HTML和Word共用，保留已有中文名匹配。实际详情接口失败则502提示重试，不打印错误负责人；惰性刷新token成功后提交保存。源码提交5cbfbc60已通过统一入口完成办公室与北京后端发布，publish-current=succeeded，无迁移、前端0字节变更、无origin写入。正式安装目录实库生成打印数据和Word双重核验：负责人Eva（刘也）、单号ly914首返出库单、6行52件；办公室健康接口ok/database connected。19项Python与16项Node测试通过，独立复审通过。最终轮询器digest b27845d4a94882470e816e3eabe903eef19748d7da5c9317afb09c5e438b60a8，timer active/enabled且空队列轮询成功。证据和Word预览收尾保留至主目录 `.deploy_state/outbound-20260917/`。用户随后已授权合并推送；本轮集成主线运单剪贴板更新，42项相关回归通过、增量约定检查无违规，线上已发布版本无需重复部署。

## 2026-09-17 OKKI 出库轮询器已部署启用

任务分支 `codex/outbound-poller-deploy`，用户授权部署启用。根因：后端已入队，新加坡未安装轮询器/service/timer；原独立 create-outbound.js 仅有本地台账且失败可能 exit 0。已通过统一入口 `deploy.bat --okki-outbound-only` 部署受管 creator 与轮询器，使用实际 Node v22.22.1 路径，timer enabled，每轮退出60秒后继续。未发布其他应用、无数据库迁移。远端凭据仅存 root 600 的 `.ark-outbound.env`，不入 Git。

实时判重读取镜像关联ID后核对 OKKI 详情；无命中则按订单创建日以来的全部更新出库单逐页查明细 order_id。人工待出库单存在时，订单 to_outbound_count/task_outbound_count 仍可能为0；官方列表不支持order_id参数。任一已有关联单（含部分出库）跳过，不自动补量。受管worker使用MySQL锁、逐笔认领与attempt版本回写；提交前独占持久意图，结果不明确进uncertain不重发；GET可重试一次，POST不自动重试。人工/旧脚本与受管worker在查询和创建间仍可能外部竞态。

09:19实库验收：26任务中done=5、skipped=21（20单已有出库＋1单非标），无pending/running/failed/uncertain。早期task1 GET超时，使用新代码只读预演确认恢复且无提交意图后单笔重新入队，保留attempts，第二次成功。目标方舟invoice450 / OKKI order105791310195199（ly914首返出库单）于09:17:22创建XSCK2609170495，outbound_invoice_id=105791346765650；实时API核验status1待出库、6行52件、本地台账仅1条。其余新建XSCK2609170492/0493/0494/0496。

远端部署digest `85f4830ecdb9f5a7ab0570ac38d10ea804e5130fc3aab76d7ec1ac6442830362`；脚本SHA256 poller `071e61f4939bc4fd5961be3991bf641e3dbff30eadc4d2c7331e83f0d9d1418b`、creator `bca8ef531595ff42a464bca3cca04956ec8fe53ffcc6c0fb4c4ffa540780748a`。证据在任务worktree `.deploy_state/outbound/`，服务器staging/backup保留必要恢复材料。14项Node回归通过，独立审查已完成，Python编译与增量约定检查无违规；默认约定检查仍被main既有10项UI债务阻断。Git巡检已按本地快照运行，无远端写入。

本候选新增服务已登记platforms.json；当前迁移器无法安全冻结timer+在途oneshot，因此候选将migration_writers_verified=false，已验证无DDL发布仍允许、带DDL发布在停服务/执行DDL前阻断。后续需先补齐停timer、排空service、验证无写入和恢复原调度状态支持，不能直接改回true。用户随后已授权将该源码与保护合并推送 main；后续主线发布须保留此 DDL 保护。

## 2026-09-17 运单图片剪贴板粘贴

任务 `codex/waybill-clipboard`，基于 `3263d406`，用户已授权本轮合并推送 main，合并后运行专项回归并核对远端；本轮不部署。运单上传页支持 Ctrl+V / ⌘V 粘贴图片，复用选图上传的预览、JPG/PNG/WEBP 与 10MB 校验和 OCR 流程。输入框及富文本保留原生粘贴；手录模式、识别中、提交中、成功弹窗期间不接收图片；多图只取第一张并提示。选图与粘贴共用忙碌保护，识别/提交中禁用删除，替换图片与页面卸载释放预览 URL，卸载移除粘贴监听。

验证：`node --test tests/waybillClipboard.test.mjs` 7 项通过，`npm run build` 通过；Chrome 原生剪贴板 Ctrl+V、预览回填、输入框隔离和文件选择回归通过，桌面/390px 截图及脚本在 `tmp/waybill-clipboard/`。浏览器 OCR API 为模拟响应，未调用真实识别或提交业务数据。默认约定检查仍有 10 项既有 UI 债务，本次增量检查无违规；`git diff --check` 通过，Git 巡检使用 `--no-fetch` 本地快照。

## 2026-09-17 出库检验完成钉钉通知

任务codex/inspection-notify，基于d3160fe5。用户确认按客户当前业务员（非制单人）发通知。只读生产核验：当前OKKI客户归属在业务镜像customer_info.owner_user_ids；统一客户强身份仅public_web/website_domain91条，无OKKI company_id，active primary assignment为0，因此本模块采用实际运行的OKKI归属源。

同BUSINESS_DB_NAME内出库记录company_id精确关联customer_info，按发票模块现有规则叠加InvoiceCustomerOverlay最新手动同步归属（镜像时间追平则取镜像，时间不可比则取overlay）；通过有效OKKI external_account_id绑定找到有效方舟账号的dingtalk_id。多个当前负责人去重发送；任一负责人外部绑定缺失/歧义时本条整体跳过并记录，公海不发送；不按姓名/历史订单归属推断。ISO时区及epoch统一北京解释。

小程序与共用手机网页在检验提交事务成功后发OA工作通知，正文“客户【客户名称】的【出库单号】出库单已出库检验完成，请及时验货。”只有本次draft→submitted转换触发，重复提交/回执重放不重发，撤回重提会再次通知当前业务员。发送上限10秒，失败/缺绑定不回滚检验；无表结构变更。提交后尽力发送，无持久重试队列；进程中断或钉钉异常可能漏发，不确定结果不自动重发。测试模拟发送，无真实推送。

新增通知19项通过，扩展回归60通过/1项既有失败；既有test_audit_beijing_midnight_ignores_server_timezone固定2026-09-16时钟导致JWT日期相关失败，未修改main亦复现。增量约定无违规，默认UI门禁10项既有债务；独立复审通过，无阻断。实现提交06c7cb92；用户已授权本轮合并推送main，合并后运行通知回归并核对远端。本轮不部署。

## 2026-09-16 出库检验直接拍视频与自动压缩

任务 codex/shipping-video-capture，基于3799bda6。网页/小程序整单与明细增加直接拍视频入口，保留相册；拍摄确认后自动压缩上传。网页本地Canvas/MediaRecorder转1280最长边、24fps、目标1.8Mbps视频/96kbps音频MP4，保留声音；小程序wx.compressVideo medium，压缩完成后校验100MB限额。网页输出更大时保留已足够小的原MP4/MOV；不支持压缩或失败时提示重试，不静默跳过处理。未新增后端端点/依赖/迁移。网页压缩按视频时长近实时进行，必须保持前台；不承诺固定压缩率或自动保存一份到手机相册。

压缩/上传期间锁定单据操作；网络重试复用压缩结果和原request_id，网页卸载中止处理；小程序卸载作废回调，避免离开后上传。18项流程/安装回归通过，主站构建通过。Chrome真实3秒带声音1080p测试视频4368514字节压到249051字节；ffprobe确认H264 1280x720+AAC，音量检测非静音。320px真实组件验证拍摄capture/相册选择/上传事件无横向溢出，证据任务tmp/video-capture。未代替iPhone真机原生相机、Safari音画及微信实际压缩验收。独立审查发现的卸载后继续上传已补防护和测试。默认约定门禁10项既有UI债务，本次增量另验。实现提交4ef80423；用户已授权本轮合并推送main，合并后验证并核对远端。不执行生产部署或上传小程序版本。

## 2026-09-16 出库检验桌面 Web App（授权合并交付）

任务 codex/shipping-web-app，基于8857f844。已按用户方案补齐扫码/专用登录页manifest、180/192/512图标、standalone显示、安装指引及iPhone安全区。Logo通过内置imagegen生成黄色黑字＋扫描勾选变体并保存工程。根scope仅容纳登录，不改变权限或操作人记录；无Service Worker、离线提交或后台上传。普通路由清理专用元数据；查询/hash参数的登录返回路径已补回归。原扫码、上传与人员选择逻辑未改。

验证：9项Node测试通过；主站构建通过；Chrome模拟iPhone的真实Vue页面验证匿名登录返回扫码、安装指引开合、320/390布局、选人、桌面模式隐藏引导和普通页面元数据清理。独立审查通过，默认UI门禁仍有10项既有问题、增量约定无违规。截图和模拟脚本在任务tmp目录；不代表iPhone真机安装/摄像头/实际文件上传已验收。实现提交 e8e1c49d，用户已授权合并推送 main；本轮不执行服务器部署。

## 2026-09-16 出库打印负责人英文名匹配修复

用户反馈更新后中文姓名仍未显示。只读生产核验：出库单 create_user_name 为英文，方舟 username 对应英文，但 OKKI external_display_name 大多中文，原实现仅匹配后者导致漏显。在 codex/shipping-owner-match 修改打印共用转换：方舟 username 或有效 OKKI display_name 忽略大小写及首尾空格精确匹配，合并去重后只接受唯一未删除人员，跨字段重名保留原文。HTML 与 Word 使用同一结果，不修改业务数据、账号或权限。

先新增测试复现3处失败，再修复；负责人/排序/Word与撤回媒体相关隔离测试18项通过，独立审查无阻断。只读姓名覆盖核查：34种负责人中31种可匹配方舟用户名；Olivia、Tina、Linda 当前没有未删除的同名方舟账号，不猜测中文名。增量约定无违规，默认UI门禁仍有10项既有问题。修复提交 ec35aece，用户已授权本轮合并推送 main；本轮不执行部署，生产仍为前次恢复的554b06f1。

## 2026-09-16 151 事故恢复发布完成

用户授权合并推送并完成恢复更新。修复代码 ae7d904e，生产候选为 main 合并 554b06f108f3df6f1f81ecd5eaf63d2f72d4d90f，已推送 origin/main。办公室从受管候选 deploy/deploy.bat 加 --live-root、固定 --revision、--recover-migration-151 先 prepare-only 后正式发布，两次均成功。151 unsigned 外键修复完成，数据库真实迁移 152→151→153→154；没有 stamp、downgrade 或删除事故日志。

办公室和北京 checkout 均为 554b06f1，数据库为 154_okki_outbound_tasks；CommissionSystem、WhatsAppConnector、ark-backend、shipment-tracking-mcp 四个 writer 均运行。办公室 .deploy_state/publish-current.json=succeeded、schema-writers.json=completed，完整保留 recovery_original 的 failed-after-ddl 现场及四 writer 基线。四个登记静态站全部激活，无 deferred；内网 ArkOfficeHttps 服务仍运行。随后通过已更新安装的 deploy.bat --shipping-video-routing-only 先准备再激活两站专用照片/视频上传路由，保留各站原配置备份。

验证：专项恢复测试28项、其他部署/迁移回归104项，共132项通过，独立审查无阻断；增量约定检查无违规，默认 UI 门禁仍有10项既有问题。公网 leshine.cloud、leshine.work 的 /health=200/database connected，/login 与 /shipping/scan=200，匿名 station/operators=403、空登录请求=422（无502）；办公室后端 OpenAPI 确认 station、Word、recall 接口已加载。办公室服务器验证 lan.leshine.cloud 的受信 HTTPS /health 与 /shipping/scan 均200；开发机当前 DNS 无法解析该内网域名，未改变其 DNS。未使用真实账号登录，未替代手机拍照/扫码/视频及 Word 客户端实际验收。

后续常规更新在办公室 D:/commission-system 运行 deploy\deploy.bat 即可，不再使用恢复参数。新 shipping_inspection:inspection_read_all 权限已随启动登记，需由管理员按业务授予；专用手机登录账号需 shipping_station:write。该次应用发布不代替微信小程序平台上传审核。pm.leshine.cloud DNS/TLS、仓库外 hair/video 独立站仍为发布器已列明的既有 pending，非本次故障恢复范围。下方旧阶段“未合并/待部署”为历史记录。

## 2026-09-16 502 故障恢复：151 外键类型不匹配

用户报告更新后 leshine.cloud 登录502。现场：办公室与北京运行代码仍 ba491dfe，候选 e0987b0b，schema-writers 为 failed-after-ddl，原四writer全running并已stop，数据库版本152。只读核实151已增加tag_scope VARCHAR16 NOT NULL DEFAULT internal和idx_tag_dim_scope，关联表/153/154新表未创建，customer_general种子不存在；ark_tag_dimensions.id、ark_tag_values.id实为unsigned INT，151关联列原signed导致外键失败。没有继续DDL、stamp或删除失败日志。

在 codex/recover-152 开发专项 deploy.bat --restore-pre151 PLAN [--prepare-only]，仅允许已审查版本、journal SHA与实际schema白名单，取得原发布锁和数据库锁，核实两端服务目录、代码干净、writer原始基线；北京两份历史.env备份及两个业务存储前缀只读豁免，不删文件。脚本暂存办公室 .deploy_state/recovery-152/deploy，plan锁定原journal摘要。prepare-only通过；执行前办公室主服务已自行恢复健康，专项入口保留它，仅启动WhatsAppConnector、北京ark-backend、新加坡shipment-tracking-mcp，四writer最终running。恢复记录 .deploy_state/restore-152.json=restored-compatible-152；原schema-writers文件逐字保留failed-after-ddl，普通发布仍被阻断，避免用户再次撞同一DDL。

验证公网https://leshine.cloud/health=200且database connected，/api/auth/me匿名403，/api/auth/login空JSON返回422参数校验，已无502。未使用用户密码登录；本轮恢复旧版本，不宣称新出库功能已上线。修复151迁移列类型与已有部分结构校验，9项隔离测试通过；恢复/部署入口测试通过，独立审查通过。后续须合并修复，再增加/审查保留原writer基线的151迁移继续方案，不直接清日志重跑。本轮未合并推送。

## 2026-09-16 部署源分叉修复准备

用户反馈 Deployment source is not a fast-forward。已知办公室原运行 ba491dfe（部署器候选入口修复），而 main 未包含该祖先。本地在 codex/deploy-reconcile 将 ba491dfe 完整合并进当前 main 基点，保留部署修复及两边文档；不 cherry-pick，不关闭 fast-forward 保护，不改生产 checkout。SSH office-prod 的 127.0.0.1:2223 连接被拒绝，服务器当前状态仍待现场核对。31 项部署回归通过，独立审查通过；与新 HTTPS 入口集成时显式禁止 --live-root 配合 --office-lan-https。增量约定无违规，默认 UI 门禁仍有 10 项既有问题。用户已授权将本修复合并推送 main；本轮不执行生产部署。修复提交保留 ba491dfe 与 5d8037c2 双祖先，31 项部署测试及独立审查通过；服务器现场仍须恢复 SSH 后核验。

## 2026-09-16 验货单按业务员归属控制

worktree commission-system-codex-inspection-scope / codex/inspection-scope，基于 fa0f6117。验货单与出库单共用客户→OKKI 业务员归属 SQL 规则，列表计数/分页、详情/打印、撤回、照片视频读取全部受限。新数据权限 shipping_inspection:inspection_read_all 独立于出库单 read_all；启动 seed 登记，人工授予，不自动补授 admin；不改小程序和共用手机作业入口。无 schema 迁移，无生产数据/权限修改。用户已授权本轮合并推送 main，本轮不部署。回归 53 项通过。独立审查发现 uploads 静态直链可绕过权限，已在两个公共上传挂载按文件实际路径屏蔽配置的验货存储目录和历史 shipping-inspection 目录，文件未移动/删除；新增默认/自定义/嵌套 assets 路径的 GET/HEAD/视频直链回归及现有 SPA 共 8 项通过。静态修复独立复审通过，无剩余阻断问题，共 61 项相关测试通过；增量检查无违规，默认 UI 门禁有 10 项既有问题。

## 2026-09-16 出库单负责人中文姓名

任务 worktree commission-system-codex-shipping-owner / codex/shipping-owner。出库单打印数据与 Word 共同通过有效 OKKI 绑定 external_display_name 精确匹配（忽略首尾空格和英文大小写），读取唯一人员 real_name，显示英文名（中文姓名）。无匹配、多人员重名、无中文姓名或原名已有中文时保留原文；不修改账号、绑定、出库原始记录或扫码人员。新增隔离测试覆盖重名、重复绑定、失效/删除绑定、原文保留及打印/Word 一致性。后端 37 项、前端打印 8 项测试通过，增量约定检查无违规；全局 UI 门禁仍有 10 项既有问题。Git 巡检已执行。用户已授权本轮合并推送 main，本轮不部署。

## 2026-09-16 出库单规格强调与排序

任务分支 codex/shipping-spec-sort，工作区 commission-system-codex-shipping-spec-sort。出库单 HTML 与 Word 中 B1/B3 独立放大加粗（16px / 12pt），不匹配 B10、AB1。打印数据接口与 Word 共用 print_service 排序：规格自然升序（Unicode 中文顺序，天才先于平行），同规格尺寸数值升序，缺失/无效尺寸末尾，同键稳定保留原序。优先产品 size；缺失时识别产品名称首个斜杠后的独立尺寸段，避免将色号或克重当尺寸。不改变扫描/验货明细顺序。用户已授权本轮合并推送 main；本轮不部署。验证：后端 34 项、前端 8 项通过，主站构建通过，浏览器预览确认强调字体与原列宽/数量居中/斑马纹。Word 通过文档解析校验各段字号、粗体和行序，未做 Word 客户端实机打印。约定增量检查无违规，默认 UI 门禁仍为 main 的 10 项既有问题；Git 巡检已执行（未 fetch）。

## 2026-09-16 内网 HTTPS 脚本合并交付

用户已授权将 codex/office-lan-https 合并推送 main。本次仅提交安装脚本、专项部署入口、隔离测试和文档，不含证书、私钥或服务器状态文件，不触发应用部署。16 项检查通过，增量约定无违规；默认 UI 门禁仍有 10 项既有问题。现场验证证据保留在主目录 .deploy_state/office-lan-https-delivery；下方“未授权推送”为历史阶段记录。

## 2026-09-16 办公室内网 HTTPS 已启用

用户完成 DNSPod TXT 验证后，通过既有 certbot 账号签发 lan.leshine.cloud 公共信任证书，到期北京时间 2026-12-15 08:21:48。私钥仅经 SSH 进程内转送至办公室受限目录，未写入开发机磁盘、Git 或日志。办公室 `D:/commission-system/.deploy_state/office-lan-https` 权限限管理员/SYSTEM，证书在其 certs 子目录。

专项 deploy.bat 先 prepare-only 后激活成功，随后重跑归属与线上证书检查返回 verified。独立 NSSM `ArkOfficeHttps`（Caddy 2.11.4，官方包SHA-512固定）自动启动，绑定 192.168.101.193:443，防火墙只允许 192.168.100.0/23，代理127.0.0.1:8001。CommissionSystem 未重启、现有8001未改，无生产应用/数据库迁移、无账号权限变更、无Git推送。执行源码暂存服务器 .deploy_state/office-lan-https/deployer，不覆盖其独有的发布器修复。

服务器和开发机直连校验CA/SNI/叶证书一致，/health和/login均200，/api/auth/me匿名403。Codex内嵌浏览器返回连接关闭，开发机禁用请求代理后直连HTTPS正常，未修改系统代理；不能声称手机浏览器已验收。证据 .deploy_state/office-lan-https/verification.json。新扫码接口仍未部署（办公室运行 ba491dfe，无station路由），/shipping/scan返回200仅是SPA壳，不能作为新页面上线证据。后续新功能发布须保留办公室独有提交、核对共享库迁移与writer状态，不能直接覆盖或回退。

手动DNS-01不会自动续期；应在12月15日前重新验证并安排独立HTTPS服务证书切换，原业务后端无需重启。源码在 codex/office-lan-https，本轮未授权合并推送。16项隔离测试通过；独立审查的配置漂移、回滚残留和证书续期误报已修复。默认约定门禁仍有main的10项既有UI问题，增量检查另行核验。

## 2026-09-16 办公室内网 HTTPS（等待 DNS 验证）

用户授权通过现有端口映射配置 lan.leshine.cloud 的 HTTPS 和网站入口，未授权本轮合并推送。任务 worktree `commission-system-codex-office-lan-https` / `codex/office-lan-https`。

已通过本机 SSH alias office-prod（127.0.0.1:2223，现有密钥与严格主机密钥校验）连接 lys-acciowork。办公室运行根 D:/commission-system，IPv4 192.168.101.193/23，NSSM CommissionSystem 的 8001 /health 正常；80/443 未监听。域名目前可解析到内网地址，DNSPod 负责公共 DNS。办公室源码 ba491dfe，生产 OpenAPI 尚无 station 接口；不要把 HTTPS 入口完成等同新质检功能已部署，不直接回退或覆盖办公室独有发布器修复。

用户选择手动 DNS 验证。北京既有 certbot 账号已启动 lan.leshine.cloud 申请，等待 TXT `_acme-challenge.lan`；具体挑战及 exec session 保存在本工作区 .deploy_state/office-lan-https/pending.json。未签发、未搬运私钥、未安装服务或改防火墙。用户添加后先核对权威 DNS，再继续 certbot；若会话丢失需核实申请状态，不能盲用旧挑战。

已准备独立 deploy.bat --office-lan-https PLAN [--prepare-only] 入口，固定官方 Caddy 2.11.4/SHA-512，证书SAN/密钥/有效期、Windows安装归属、单独443绑定、仅局域网防火墙、真实SNI/CA及线上叶证书一致验证；独立审查发现的服务漂移、失败恢复和续期误报已修复。16 项隔离测试通过。手动 DNS 续期须人工更新验证记录，不能宣称自动续期。后续先完成证书及独立HTTPS入口，再依据已审查发布状态处理新扫码功能部署依赖，不运行无关全平台更新。

## 2026-09-15 共用手机质检：授权合并推送

本次包含独立扫描页、按单选人和审计、照片/视频及提交重试、紧凑三列名单。集成 origin/main `43c2f43a`，迁移 153 改为接续其 151_customer_media_tags，保持唯一 head；未改生产数据库、账号、权限或网络。本轮仅合并推送 origin/main，不部署、不配置内网 HTTPS。下文未合并状态为历史阶段记录。

集成验证：后端隔离库 45 项、前端/小程序 40 项、部署路由及迁移计划 29 项通过，主站构建通过。本次增量约定无违规；最新 main 的 UI 基线门禁有 10 项存量问题（包含新合入素材模块），未修改无关代码。证据与原方案备份保留至主目录 tmp/shipping-station-20260915；临时工作区在完成推送后清理。

## 2026-09-15 共用手机名单紧凑化

按用户反馈，人员网格由两列大卡改为三列紧凑按钮，常规卡高 52px、间距 8px，17 人网格约 358px 高（减少约 65%）。保留大字当前身份、短光晕、金色描边及勾选，重名次行与搜索不变。320px/390px 浏览器检查无横向溢出、搜索及选中正确，构建通过。预览 `tmp/station-compact-preview.png`；未合并推送或部署。

## 2026-09-15 出库单 Word、撤回编辑与相册视频（合并交付）

分支 `codex/shipping-word-recall-video`，基点 `1d2ba329`。用户已授权合并 main 并推送 origin；本轮不部署，生产数据库及 Nginx 未改动。集成远端 `5f0e35c2`，迁移改为 152 避开主目录另一任务未提交的 151；152 同时接续远端已有的 150 与 146_expo_beautify_prompt 两个 head，恢复提交版本的单 head。其他任务的 151 尚未纳入本次交付，后续合并须接续当时最新 head；主目录与其他任务的未提交修改未触碰。

- PC 出库列表「下载 Word」生成可编辑 DOCX，沿用 A4/6mm 左右边距、规格在颜色前、现有列宽、类别小字/明细加粗、数量居中、灰纹、空白批次号与二维码。
- 验货列表「撤回编辑」限 write/admin；保留所有媒体与备注，submitted → draft，重新提交后回到列表。迁移 152 增加编辑版本及撤回审计字段；上传/删除/提交携带版本，旧页面不能误改新轮次；小程序扫码页提供刷新并恢复已存备注。照片计数在主表锁后使用 MySQL 当前读。
- 小程序整单/明细旁新增相册视频上传，MP4/MOV/M4V、单文件 100 MiB，支持预览和删除。PC 详情按需加载视频；视频私有鉴权、不计入必传照片数、不进入验货单打印。迁移 152 给历史媒体默认 image。发布配置见 `deploy/README.md`，新增视频专用路由入口（101m/300s），普通应用发布不会自动启用。

验证：后端隔离 SQLite/temp 文件测试 45 passed；小程序 Node 测试 42 passed；打印测试 7 passed；部署路由/入口测试 43 passed；主站构建通过。独立审查发现的 MySQL RR 计数、Nginx 5MB、旧页面刷新、非 JSON 删除错误及视频超时均修复。实际 Vue 页面用模拟 API 验证 Word 下载触发、撤回确认/列表刷新及只读账号隐藏撤回。DOCX OOXML 校验通过，样例 `tmp/outbound-word-preview.docx`；截图与测试日志留在 tmp。未进行手机微信真机上传、Word/WPS 实际排版及生产 MySQL 双连接并发验收。

集成复核：后端 45 项及主站构建再次通过，Alembic 离线检查唯一 head=152。独立审查发现发布器默认遍历遗漏合并节点的兄弟迁移，已对预检和执行前复核统一启用 implicit_base；补真实迁移图计划测试，确保从 150、146_expo、145 或当前 head 出发，预检清单与 Alembic 实际升级计划一致。未执行数据库迁移。

约定检查仍被 4 项既有 UI 问题阻断；单独增量检查无红项，7 个小程序端点鉴权黄项为脚本未识别 `require_mini_entry`，已有路由依赖回归测试覆盖。Git 巡检为 `--no-fetch` 本地快照。临时前端页面已删除、测试服务已停止；交付样例与验证证据在合并后保留到主目录 `tmp/shipping-media-20260915`。

## 2026-09-15 参考图上传 500 复发（17:45 恢复两站目录权限）

北京17:42:15 `POST /api/domestic/images` 在 Nginx 写 body 临时文件时 Permission denied；新加坡订单导出也在 proxy 临时目录失败。两站 worker 为 www-data，五目录属主再次为 nobody。北京17:12:46的 `/etc/nginx/.ark-backups/colorwork/cloud-syntax.conf` 仍是未隔离临时目录的旧配置，mtime与目录ctime一致；新加坡目录17:12:51变化。该次预检查发生在防复发修复 `1d2ba329` 合入main之前，不能将代码推送等同于所有执行端已更新。

沿用同一故障此前明确恢复授权，17:45按相同校验恢复两站五目录 uid=www-data，gid=root、模式0700保持不变；无递归改权限、无重启、无业务数据写入。原元数据保存在北京 `/etc/nginx/.ark-backups/temp-owner-recovery/20260915T094547301372Z.json` 与新加坡同目录 `20260915T094553114598Z.json`。

验证：`www.leshine.work` 与 `www.leshine.cloud` 的 `/api/domestic/images` 64KiB、1MiB匿名POST均到达后端鉴权并返回403 JSON，不再出现500；各耗时0.53/0.60/1.71/2.20秒。此验证只证明上传通道恢复，不替代真实登录后参考图落盘与订单保存验收。未代用户上传业务参考图。后续路由预检查必须使用main的 `1d2ba329` 或更新版本；本轮未切换服务器应用代码。恢复记录在独立任务目录维护，未修改其他代理的未提交文件。

## 2026-09-15 内贸充值上传 500（两站权限已恢复；防复发代码交付）

任务分支 `codex/domestic-recharge-fix`，工作目录 `commission-system-codex-recharge-fix`。新加坡 Nginx 日志确认 15:31–15:39 客户45的充值请求在写 `/var/lib/nginx/body` 时 Permission denied，尚未到达业务 API；内贸图片上传也受影响。北京同样复现，worker 为 www-data，而五种临时目录使用 nobody/root、700。根因是凭证/色块路由的 root 最小配置 `nginx -t -c` 未隔离默认 temp paths，省略 user 后可将正式目录改属 nobody；无变化激活直接返回，无法恢复。

修复两个 standalone remote 脚本：预检查显式隔离 client_body/proxy/fastcgi/uwsgi/scgi 临时路径、pid 和日志到各自 syntax 工作目录。保留业务路由、充值审核与账本逻辑。部署说明记录 nginx -t/-T 的权限副作用和排障方式。

验证：新增4项回归修复前失败、修复后通过；部署全套121 passed/11 skipped（Windows平台相关跳过）；北京 Linux 对4份真实路由片段执行隔离 nginx -t 全部通过，正式五目录 uid/gid/mode/ctime_ns 均未改变。独立审查通过；补充 -e stderr 隔离启动期日志，并让参数化测试使用对应站点片段后，29项针对性测试及4份Linux配置实测再次通过。约定检查受4项既有前端UI问题阻断（AssetTagEditor、AssetLibrary、ProductionOrderManage、AIManager）；git diff --check 通过，Git巡检为 --no-fetch 本地快照。

现场状态：排查新加坡时执行 nginx -T 意外触发正式配置的目录属主校正，已向用户明确说明；15:43目录恢复 www-data/root 700。用户随后明确授权北京恢复；16:52重新核对 worker、五目录真实路径/属主/模式后，仅将五目录 uid 从65534改为33，gid和0700保持不变，未递归修改、未重启。原元数据保存在北京 `.deploy_state/nginx-temp-owner-recovery-20260915T085213384296Z.json`。两域名64KiB匿名POST均返回后端403，.work的1MiB也通过；.cloud首次1MiB在30秒超时，改用120秒预算从北京复测，40.01秒返回后端403；上传权限故障已消除，但该链路传输较慢。未修改充值/账务数据，真实登录提交及审核未验证。用户已授权将防复发代码合并 main 并推送 origin；本轮只集成代码，不执行生产部署。

## 2026-09-15 出库单打印版式优化


出库单产品名称在首个斜杠处分为「产品类别」与「颜色/尺寸/克重」，保留后半段顺序和复合颜色中的斜杠；类别 12px，明细 14px 加粗，规格列移至颜色/尺寸/克重前，从 17% 加宽为 32.5%，数量及其表头居中。左右边距从 12mm 缩至 6mm，末列改为空白批次号，分配 15.5% 表宽（约 31mm，为首次调整的一半），行高至少 12mm 便于手写；偶数明细行浅灰斑马纹，打印保留底色。验货单版式不变。

验证：7 项打印测试与主站构建通过；浏览器样例及 print 媒体检查确认字号、灰纹、左右边距、规格列顺序、批次号减半及数量居中，示例规格为单行，单元格无横向溢出。主工作区 `tmp/outbound-print-columns-20260915/outbound-print-preview.html` 与同名 PNG 保留预览证据；未做物理打印机验收。约定检查仍被 AssetTagEditor small 按钮及 AssetLibrary/ProductionOrderManage/AIManager 三项既有行数基线问题阻断；Git 巡检使用 `--no-fetch` 本地快照。用户已授权合并 main 并推送 origin；本轮不部署。

## 2026-09-15 库存图直接下载与实时预览（代码交付，未发布）

任务分支 `codex/colorwork-live-download`。按后续截图要求去掉工作台深色顶栏与下方账号/页面路径栏，移动端底部内置导航及其留白同步移除；三个页面由方舟菜单进入；方舟「库存色块图」分组图标右下角增加 `BY 加程` 金色角标（由 navigation.js 配置）。下载页移除业务修改图列表，保留原始图缩略图与批量 ZIP；栏目改为「库存图JPG」，逐模板提供「下载原始库存图JPG」及「下载实时库存图JPG」。实时按钮打开模态弹窗，直接复用 InventoryBoard 的 LIVE PREVIEW、30 秒自动刷新、JPG 绘制与前后两次版本校验；只下载，不创建历史成品。

为仅有下载页面权限的账号增加 library 鉴权的模板 inventory 快照与 validate 路由，复用现有服务，不放开 inventory PATCH 或成品写入权限。原始库存数据、历史成品与 OKKI 状态判断规则保留。

验证：主站与工作台构建、TypeScript 检查、8 项导航回归及 7 项下载权限/界面事件/共享导出/URL 回归通过，独立审查未发现阻断问题。全仓约定检查仍受 AssetTagEditor small 按钮及 AssetLibrary、ProductionOrderManage、AIManager 三项既有基线问题阻断。Git 巡检使用 --no-fetch 本地快照。浏览器连接不可用，尚未执行真实浏览器视觉验收；用户已授权合并 main 并推送 origin，本次不执行生产发布。

## 2026-09-15 库存色块局域网 401（补齐代码交付，未部署办公室）

分支 `codex/colorwork-lan`。用户反馈 `.cloud` 已正常、局域网仍401；只读再次确认办公室隧道工作台健康路径返回 WhatsApp Connector 的 Express 401，而 `.cloud` 返回200。上轮只覆盖公网 Nginx，未覆盖局域网直连办公室。本轮沿用同一故障的合并推送授权交付代码，不执行生产部署。

Windows Settings 默认 `COLORWORK_GATEWAY_ORIGIN=https://leshine.cloud`，办公室 `/sso` 先校验用户和视图权限，再携 Bearer 请求北京签发 SSO；iframe/API/文件由办公室代理北京，只转模块 Cookie，不转主站 Bearer。检查局域网写请求 Origin 后转换上游 Origin；HTTP 局域网 Cookie 移除 Secure，HTTPS 保留，均保留 HttpOnly/SameSite=Lax/模块 Path。绝对北京重定向转相对路径，浏览器始终留在局域网地址。Linux 默认空网关保持本地 workerd；显式空值供 Windows 隔离开发，办公室生产不能置空。代理标记阻断配置回环，不复制数据库、素材或 SSO 密钥。

验证：修复前5个回归失败（办公室签发错误来源的SSO、上传/退出继续收到401），修复后色块与配置回归37 passed；独立审查无 P0/P1/P2。当前修复代码以 HTTP 局域网 Origin 实际代理北京健康端点，返回200及精确 colorwork JSON；这次只读检查未创建生产会话。完整约定检查仍受4项现有主站UI债务阻断，增量无违规；差异检查通过，Git 巡检使用 --no-fetch 本地快照。

上线需要通过统一 `deploy.bat` 更新办公室后端；只更新北京或 Nginx 不会修复局域网。北京现有本地工作台无需为 LAN 单独改配置。发布后用实际账号验收三个入口、刷新、上传、退出，并确认办公室 JWT 可由北京验证；健康端点200及模拟凭据测试不能替代真实SSO验收。本轮尚未部署办公室，不能报告局域网生产故障已解除。

## 2026-09-15 库存色块生产 401（代码交付，未部署）

修复分支 `codex/colorwork-prod-routing`，用户已授权合并 main 并推送 origin；本轮不部署。只读复现：新加坡经办公室隧道请求 `/api/colorwork/workbench/api/health` 返回 `401 {"code":401,"message":"unauthorized"}`，响应带 `x-powered-by: Express`；该响应来自 WhatsApp Connector，办公室与工作台默认端口同为 8787。北京运行代码为 `7015e3625`，`ark-colorwork` 为 not-found/inactive、8787 无监听、没有 colorwork/current.json。用户所述“已部署”未覆盖北京内部模块。

修复在部署入口纳管两个公网入口 `/api/colorwork/` 整段：新加坡经证书校验的 TLS 转北京，SSO 签发、会话、文件均落同一北京实例；已知 `.work` Origin 转换成上游 Origin，其余保留由后端拒绝。工作台健康后先切北京再切新加坡；配置摘要漂移阻断，语法/reload/真实域名 readiness 失败恢复原配置。外部 writer 在路由激活前恢复。提供 `--colorwork-routing-only` 专项（要求已有健康模块）并接入普通发布。没有改办公室 WhatsApp 服务、数据库或业务数据。办公室直连入口不属于本次公网路由覆盖。

验证：发布回归 117 passed / 11 skipped（Windows 跳过现有 Linux 静态发布用例）；独立审查未发现 P0/P1/P2。经 `deploy.bat --colorwork-routing-only --prepare-only` 在两机生成候选并通过 Nginx 语法检查，未修改活动配置、未 reload/启停服务；准备状态在 `.deploy_state/colorwork-routing.json`，服务器候选在 `/etc/nginx/.ark-backups/colorwork/`，保留用于正式发布前核验。增量约定检查无违规、diff 格式检查通过；完整约定检查仍被 AssetTagEditor small 按钮及 AssetLibrary/ProductionOrderManage/AIManager 三项行数基线阻断。Git 巡检为 --no-fetch 本地快照。

未完成：生产发布未获本轮授权；需通过统一入口先部署北京工作台，再激活两站路由。办公室 SSH 的本机 2223 通道当前拒绝连接；跨实例 JWT 一致性、真实账号三个入口与文件访问必须在发布后验收，readiness 不代表 SSO 成功。首次素材导入要求仍见工作台 README。不得将当前修复准备状态报告为线上已恢复。

## 2026-09-15 发货检验扫描引导（合并推送，未发布）

用户要求扫描按钮采用外贸报工同款动效，并加入提供的出库单示例图。发货检验待扫码页现有旋转光圈、二维码点阵和往返扫描线，下方示例突出右上角二维码，可点击调用微信图片预览。隐藏页面暂停动效，减少动态偏好关闭连续动画。示例原图原样存于 `miniprogram/assets/shipping-scan-example.png`。

验证：37项Node测试、JavaScript语法、页面显示/隐藏动效状态和图片预览回调检查通过；浏览器按WXML/WXSS渲染确认布局。约定检查仍为4项既有主站UI债务；未执行微信真机验收，未改扫码、上传和提交业务逻辑；用户已授权合并并推送 origin/main，未发布。

## 2026-09-15 小程序工作台导航（合并推送，未发布）

用户确认两列导航按钮原型，外贸使用黑金主题/金色 LOGO，内贸使用品牌绿/白色 LOGO，订单速查和出库检验保持浅色工具按钮。入口统一登记在 `miniprogram/utils/navigation.js`，首页每次显示刷新权限，加载失败可重试、无权限显示联系管理员。底部切换及跨模块扫码同步限制；后端按当前数据库授权拒绝越权，公开签名进度码不受影响。

新增 `mini_export:write`、`mini_domestic:write`、`mini_lookup:read`、`mini_shipping:write` 四项独立权限，在角色管理「小程序 · 功能入口」分组配置。超级管理员全部可见；其他角色（包括普通 admin）必须明确分配，不能按工序身份或主站权限猜测授权。内贸数量/逐件模式权限保持独立，工序分配和报工业务校验仍生效。内贸报工的订单记录页面共享内贸/速查权限，提交仍要求内贸报工权限。

上线顺序：先部署后端登记权限并给实际使用角色分配，再上传小程序。未分配时旧客户端相关接口也将返回403，应安排同一维护窗口完成。用户已授权将本次实现合并并推送 origin/main；未改生产权限，未发布。

验证：37 项 Node 测试和57项隔离SQLite后端测试通过（含公开进度码13项），主站前端构建通过；独立审查无阻断，跨模块扫码无权限提示及过时注释已修正。真实微信开发者工具编译与真机验收待执行；浏览器展示仅为WXML/WXSS渲染预览，不替代真机。约定检查受4项既有主站UI债务阻挡。

## 2026-09-15 工作目录整理

- 已核对所有旧worktree：原有已提交历史均在main；本轮将DHL错误提示、凭证路由工具和WhatsApp测试标记/语言中文标签三个已验证补丁集成至本地main。用户本轮授权合并和清理，未新增远端推送或部署。
- 集成复验：DHL/凭证路由16项，WhatsApp扩展313项测试及构建通过；凭证路由独立审查无阻断。约定检查仍受已记录的4项既有UI问题阻挡。
- 已完成的临时worktree清理；原有配置、上传材料、验证/部署记录集中保留在 `tmp/worktree-cleanup-20260915/`（仅本机，不入Git）。
- 小程序送审准备代码按用户授权集成至本地 main，清理 `commission-system-codex-miniprogram-review` 与本地分支；移除未完成页面入口及上传内容，30 项 Node 测试通过。本机私有配置已备份，不纳入提交；微信真机验收、上传和审核仍未执行。
- 保留 `commission-system-codex-shipping-upload`（真实上传超时仍待排查）。
- 保留 `commission-system-codex-deployment-plan` 及其两个发布源快照（部署状态与回滚引用），保留 `commission-system-kimi`（固定工作区含本地配置/数据）。
- `commission-system-codex-colorwork-entry-fix` Git登记已移除，但Git删除途中遇Windows长路径错误，部分文件残留。后续递归删除命令被执行策略拒绝（blocked by policy），未重试绕过；本机日志没有更细拒绝理由。其配置/部署记录已先保留到上述目录。

## 2026-09-11 WhatsApp v1.6.7 语言中文标记（代码集成）

沿用codex/whatsapp-testing-label，包含未合并的测试中按钮标记。语言选择器统一为中文在前、原文括注，覆盖聊天工具栏、话术及扩展弹窗。仅显示名称调整，无后端变更；构建283单测及语言选择/窄屏2条浏览器路径通过，约定检查剩素材库两项既有问题；未合并推送。

## 2026-09-11 WhatsApp v1.6.6 按钮测试标记（本地修改）

分支codex/whatsapp-testing-label，基点23e4c994。自动接管入口改为“自动接管（测试中）”，同步初始渲染、停止后恢复文案及既有浏览器用例。开启后仍显示“停止接管”。仅扩展文案变更，无后端变更；构建283单测及窄屏/开关2条浏览器路径通过。目录整理时复验283单测和构建通过并集成至本地main；未推送发布。

## 2026-09-15 充值凭证统一办公室路由（已发布，历史凭证待登录验证）

分支 `codex/voucher-office`，目录 `D:/MyProgram/commission-system-codex-voucher-office`。新加坡和北京增加仅匹配充值提交/凭证读取的 Nginx 片段；北京经证书验证 HTTPS 到新加坡，沿原8002隧道访问办公室。原用户 Authorization、接口权限和凭证归属校验保留；两级21MiB请求体、禁缓存、禁自动重试，其余业务API不变。新增 `deploy.bat --voucher-routing-only [--prepare-only]`，具有两机先准备、当前配置摘要检查、单机失败回滚和独立状态记录，不发布应用或迁移数据。

验证：部署测试100 passed/11 skipped（原有外部集成测试）；内存SQLite充值审核回归12 passed；独立agent审查无必修项；两机实际 `--prepare-only` 成功，片段 Nginx 语法及真实配置锚点通过，未修改线上路由或reload。全局约定检查被4个已有UI门禁项阻挡（AssetTagEditor旧small按钮、AssetLibrary/ProductionOrderManage/AIManager行数基线过期），本任务未改这些前端文件。Git本地巡检已运行，未fetch，不代表远端最新状态。

现场只读证据：北京仍使用 `D:\WORKSOURCE\domestic` 默认存储，解析为Linux工作目录内的同名字面目录且不存在；数据库仅发现申请id1有凭证路径，北京无对应文件。办公室SSH本机2223通道不可用，未核实办公室原件或跨实例JWT一致性。匿名403不能代替登录后端到端成功；须用真实账号检查原申请在两入口可读。如原件不在办公室，须先找到来源，不能通过伪造文件或改账务记录消除404。代码未提交、未合并、未推送，历史凭证未迁移。

用户明确授权「发布」后，通过 `deploy.bat --voucher-routing-only` 完成两机激活；发布状态 `.deploy_state/voucher-routing.json` 两项均为 activated。09:20–09:21（北京时间）对两域名各发送无凭据的 GET 凭证/POST 充值请求，均返回403 JSON `Not authenticated` 和 `private, no-store`，未创建充值申请。新加坡访问日志记录北京IP发来的两条对应请求，确认转发实际生效。两机完整 `nginx -t` 均通过（保留其他站点既有警告），北京公网 `/health` 为 ok/database=connected。备份：新加坡 `/etc/nginx/.ark-backups/domestic-voucher/office-41354855288b4ecfb3f7a3ef68730dcc.conf`；北京 `/etc/nginx/.ark-backups/domestic-voucher/cloud-332d7097f59f4dce8f7d83148ad088fd.conf`。未执行其他应用发布、数据库写入或审批操作。

## 2026-09-15 内贸明细顾客与进度码（代码交付，待部署）

- 开发分支 `codex/domestic-item-progress`；功能、迁移和测试随代码一并交付。
- 顾客下单日期：业务建单/草稿追加/明细编辑支持选填 `guest_order_date`（DATE），扫码与主站详情只显示年月日，不含时分秒；历史留空，字段并入尚未发布的150迁移。日期修正后后端28项、前端18项通过。
- 业务建单、草稿追加和明细编辑按产品录入顾客；详情及导出按明细显示。订单头旧顾客列只保留历史数据。
- 进度码和图片接口只取签名对应明细；展示明细顾客、属性、备注及公开工序完成情况，隐藏件数、金额、路线和未配路线提示。主站详情同步隐藏明细件数、金额、未配路线提示，属性备注放大；业务报价录入和生产操作保持原口径。
- 新迁移 `150_domestic_item_guest` 从 149 延续，历史订单顾客复制至已有明细，不覆盖已填写的明细顾客。仅隔离 SQLite 验证，未执行生产迁移或部署。
- 验证：顾客/扫码 22 项、条件工序 77 项通过；更广会员报价/订单大类/导出检查已执行，导出改动后 33 项定向复验通过。前端定向 37 项及生产构建通过，独立审查发现的旧追加幂等指纹问题已修复。
- 既有基线：前端全组 1 项测试仍检查已移动的筛选代码；check_conventions 的 4 项失败均来自素材、生产订单、AI 管理页面，main 同样复现。git_sweep 使用本地快照完成。未做微信真机扫码，需发布前后按环境验收。

## 2026-09-15 小程序空关联与退出回登录（合并交付，未发布）

分支 `codex/mini-auth-session`，目录 `D:/MyProgram/commission-system-codex-mini-auth-session`。办公室生产只读确认 wanghong（id=67）的 wx_id 为长度 0 的空字符串，线上绑定路由包含 commit。复现旧登录失败后仍可空 openId 绑定的代码路径；没有历史请求体证据，不能断定该账号当时必然走此路径。现前端仅拿到微信身份后才显示/允许绑定，后端拒绝空或纯空白 OpenID。主动退出通过持久化标记阻止登录页立即自动登录及重开自动登录，点击微信登录成功后恢复；保留已有关联并修正文案。

验证：小程序 Node 测试 30 项通过，新增覆盖退出/重开/主动登录、失败重试、空身份阻断及重复绑定点击；后端 9 项隔离 SQLite 测试通过，验证空身份拒绝、跨会话持久化及历史空值重新绑定。JavaScript 语法检查与增量约定 check(HEAD) 无违规。独立 agent 审查无阻断，复跑新增 Node 用例 5/5 通过。约定检查被 4 项既有主站 UI 债务阻断（AssetTagEditor small 按钮，AssetLibrary/ProductionOrderManage/AIManager 基线过期），未修改这些页面。Git 巡检已运行 --no-fetch，仅本地快照。亮哥已授权本轮合并 main 并推送 origin/main；fetch 核对 main 与 origin/main 均为 b8b0ba3c。未发布后端/小程序，未修改生产账号；wanghong 需通过真实微信重新绑定以填充 OpenID。

## 2026-09-14 生产订单列表操作栏与导出（合并交付，未部署）

分支 `codex/production-export`，目录 `D:/MyProgram/commission-system-codex-production-export`。订单维度操作列最小宽度调整为260，按钮使用 flex 换行，避免全局单元格 nowrap 裁切后续操作；后面的“打印订单”改为“导出”，复用既有 Word 导出接口，保留单号和当前审核人参数。原有报表打印下拉保留。

验证：Chrome 隔离页面使用实际组件与全局样式、mock 订单 API，1440/1024/768/390 四档屏宽及横向滚动两端，六个按钮均完整可见且中心可点击；打印菜单及导出参数编码通过，页面错误0。未连接生产库，未验证真实订单文档生成。前端构建通过。约定检查仍报素材组件旧 small 按钮、AssetLibrary/AIManager 既有超长基线，以及本页原有大组件增加4行导致基线过期；新增内容是局部布局，无独立职责，不为行数拆分或修改基线。已运行本地 Git 巡检（--no-fetch），不代表远端最新状态。浏览器验证脚本、fixture、截图和构建日志归档到主目录 `tmp/production-export-evidence/`。用户已授权合并 main 并推送 origin；fetch 确认 main 与 origin/main 均为基点 `578481a9`，无上游差异。本轮不部署。

## 2026-09-14 客户素材上传目录与预览修复（合并交付，未部署）

来源分支 `codex/customer-media-folders`，基点 `6ed74c5f`。客户门户弹窗拖入/选择文件夹按顶层名称自动创建或复用目录，散文件固定使用入队时选中目录。内部预览返回相对签名 URL，前端按素材 API origin 解析，兼容同源与云端直传；大图查看器 teleport 到弹窗外。

左侧增加目录删除及跨批次素材总数确认。目录为客户级共享，服务端在同一事务校验所有相关任务写权限及可编辑状态，软删除全部关联图片/视频并移除目录，提交后清理原件。目录→客户批次→素材采用锁内当前读，上传最后校验也刷新批次状态，处理 MySQL 快照和 ORM 缓存竞态。独立审查发现的两处问题均已修复并复核通过；没有真实 MySQL 并发测试，不涉及迁移或生产数据。

验证：`pytest tests/test_customer_media.py tests/test_customer_media_directory_delete.py -q` 15 passed；Node 文件夹/门户测试 5 passed；Chrome 隔离浏览器测试 `frontend/tests/customerMediaDirectory.browser.py` 5 条关键路径通过、无页面错误（Vite 3077，fixture 位于 `frontend/tests/fixtures/customer-media-qa.html`，全部素材 API mock）；`npm run build` 通过，保留既有 chunk 提示。`check_conventions.py` 被无关的 AssetTagEditor 小按钮及 AssetLibrary/AIManager 过期 UI 基线共 3 项阻挡，本次增量代码 `check('HEAD')` 无违规，`git diff --check` 通过。用户已授权合并 main 并推送 origin；fetch 确认 main 与 origin/main 均为基点 `6ed74c5f`，无上游差异。本轮不部署。

## 2026-09-14 站点网关公网配置与复制修复（合并交付）

分支 `codex/gateway-public-config`。站点密钥配置改为固定公网入口 `https://leshine.work/api/ai-gateway`，不再使用管理员当前浏览器 origin，避免局域网地址外发。配置采用只读文本框；优先 Clipboard API，不可用或权限拒绝时在弹窗内选择复制，两种方式均受限则保持全选并提示键盘复制。关闭密钥弹窗仍清空密钥。

浏览器 mock 回归覆盖公网地址、现代复制、无 Clipboard API、权限拒绝、复制全部被阻止、密钥关闭清空，以及原有创建/重置/编辑/启停/核查/窄屏路径；前端构建通过。仅修改前端及回归脚本，无数据库迁移。用户已授权合并 main 并推送 origin；集成前 main 与 origin/main 均为 `e43071ac`。本轮不部署。

## 2026-09-14 业务员站点 AI 网关（合并交付，未部署）

任务分支 `codex/ai-site-gateway`，目录 `D:/MyProgram/commission-system-codex-ai-site-gateway`，基点 `794b2499`。按 `docs/requirements/2026-09-11-ai-site-gateway.md` 实现三表迁移146、每站密钥、文本 Preset 授权、MySQL 原子准入、日/分钟/并发上限、未知用量与审计解除、AI 管理站点页签、后端接入示例及 Nginx 候选片段。未触碰主目录其他未跟踪文档。

验证：72 项后端/示例测试通过，含隔离 MySQL 8.4.6 的9项迁移及20并发门禁；浏览器实际页面+mock API 验证创建、编辑、直接重置、一次性密钥、启停、核查解除及窄屏；前端构建通过。独立风险审查所列问题已修复。增量代码约定红0黄0；完整 UI 门禁仍报告两个素材模块原有问题，以及 AIManager 既有超长组件因新增页签增加4行（新业务为独立组件，未改基线规避）。

交付入口：开发规格第13节、`examples/ai-site-gateway/README.md`、`scripts/test_ai_gateway_ui.py`。API/数据库/专题/运维文档已同步。用户已授权合并 main 并推送 origin；集成前 fetch 确认 main 与 origin/main 均为基点 `794b2499`，无上游差异。本轮不部署。后续获环境发布授权后由指定入口应用迁移146并核对 Nginx 路径和真实供应商连通性；生产数据、实际计费和跨云延迟尚未验证。

收尾：测试 MySQL 和 Vite 已停止，临时 MySQL 目录清理被自动审批以 `blocked by policy` 拒绝；任务 `tmp/ai-gateway-mysql/` 及 UI 初始探针文件保留，不进入 Git/发布制品。数据库测试自己创建的随机测试 schema 均已由 fixture 清理，保留的是已停机的隔离实例目录。

## 2026-09-11 内贸客户筛选与业务订单顾客（合并交付）

分支 `codex/domestic-guest`，工作目录 `D:/MyProgram/commission-system-codex-domestic-guest`，基点 `23e4c994`。客户列表新增客户等级、归属销售组合筛选；业务订单新增选填顾客（120 字），贯通录入、编辑/清空、详情及两版 Excel。新增迁移 `145_domestic_order_guest`（可空列，历史数据保留）；空顾客不改变旧建单请求哈希，保留跨版本重试。生产单不使用该字段。

验证：后端 107 项、前端状态/交互 23 项通过，前端构建通过；迁移在内存 SQLite 验证旧记录保留，并确认单 head。独立审查问题已修复并复核通过。`check_conventions.py` 被素材库既有两项 UI 门禁阻断（AssetTagEditor 旧 small 按钮、AssetLibrary 行数基线过期，main 同样复现）；单独执行其增量代码检查无违规。`git diff --check` 通过，已运行 `git_sweep.py --no-fetch`，仅为本地远端引用快照。未连接生产库或进行浏览器实机验收。用户已授权合并 main 并推送 origin；fetch 确认 main 与 origin/main 均为基点 23e4c994，无上游差异。本轮不部署；发布时由正式入口应用迁移。

## 2026-09-11 WhatsApp v1.6.5 事实与产品目录（合并交付）

沿用codex/whatsapp-result-recovery，基点ce7270dd，包含1.6.4恢复改动。生产只读元数据确认近期成功请求仅350/351/398约束无FAQ；默认随发布加载21项审核profile，并保留显式section覆盖。新检索只读确认341/5/6/7进入输入。生成前增加有权限的有限产品目录投影，实查14英寸无记录（不能推断不销售），相关长度16/18/20/22/24。目录权限生成前后/缓存重验；不查价格库存、不写生产、不调用真实模型。后端121通过，补边界42/6专项通过，扩展构建283单测通过；浏览器27通过/1项询盘截图时序失败，该项独立3次通过；独立审查闭环。用户已授权合并推送，fetch确认main与origin/main均为ce7270dd，无上游差异；本轮不部署。详见 [事实与规格查询](requirements/2026-09-11-whatsapp-facts-catalog.md)。

## 2026-09-11 WhatsApp v1.6.4 自动接管结果恢复（已纳入1.6.5）

分支codex/whatsapp-result-recovery，基点ce7270dd。复现缺重复reply_text、段数/长度与UTF16计数引起的整轮拒绝，改为无损整理；不明确动作或无法分段时handoff保全文，扩展展示但不发送。明确wait/handoff不转reply，未增加模型调用。构建283单测通过，后端92通过/时限单独复核1通过，浏览器首轮27通过/手动恢复1项失败，随后该项连续3次通过；独立审查通过。未验证真实模型输出，未合并推送部署。详见 [恢复规则与验证](requirements/2026-09-11-whatsapp-result-recovery.md)。

## 2026-09-11 WhatsApp v1.6.3 发送与完整回复（合并交付）

分支 codex/whatsapp-send-and-coverage，基点70969c12。实机只读确认发送按钮为中文 aria-label + wds-ic-send-filled，旧选择器0匹配、新选择器1匹配，未读正文或试发。修复控件识别并补边界测试；完整回复预览保留未发送段落和来源提示，后端强调多问题先覆盖已知事实。构建及282单测、后端契约22项、完整浏览器27项通过，独立审查通过；实机模型输出与办公室运行时配置未验证。用户已授权合并推送，fetch确认main与origin/main均为70969c12，无上游差异；本轮不部署。详见 [修复与使用](requirements/2026-09-11-whatsapp-send-coverage.md)。

## 2026-09-11 WhatsApp FAQ 召回与直接回答（合并交付）

只读核验FAQ文档341/revision363，修复酸处理section5漏绑、英文虚词/子串重复计分及最新问题无优先级导致硅油答案未入选。修复后本轮问题同时命中5/7/6章节；生成要求已知直接回答、未知单独澄清，保留限定。94项受影响回归通过，补强2项专项通过，独立审查通过；素材库两项既有约定问题保留。无真实模型调用，未改生产或知识文档。需部署后端并应用已准备的source-bindings配置，扩展无需更新；分支codex/whatsapp-faq-retrieval，基点2a2e7d47。用户已授权合并推送；fetch确认main与origin/main仍为该基点，无上游差异，保留主目录其他任务未提交改动。详见 [诊断与生效方式](requirements/2026-09-11-whatsapp-faq-retrieval.md)。

## 2026-09-11 WhatsApp v1.6.2 完整性误判（合并交付）

排除居中系统通知误记未知消息；历史未知占位交Agent判断，最新未读取消息仍交人工。拆分完整性错误提示，新增无法识别发送方的内部标志并覆盖缓存、恢复、临发复核。269单测、25浏览器路径通过，独立审查闭环，构建打包通过；素材库两项既有约定问题保留。包含1.6.1修改；用户已授权合并推送，集成前main与origin/main均为3e9393ea，无上游差异。保留主目录其他任务未提交修改。本轮不部署，实机未确认。详见 [修复与验收](requirements/2026-09-11-whatsapp-auto-context-fix.md)。

## 2026-09-11 WhatsApp v1.6.1 自动接管误停修复（本地交付）

修复填入后发送按钮尚未渲染、图片表情导致草稿内容核对不一致、历史虚拟列表暂空即判为断连这三项可复现缺陷。按钮最多等2秒、空窗额外等4次，持续核对聊天/取消/尾消息/草稿，仍只点击一次且不重试不确定发送。261条单测路径覆盖（全量260通过后补1条、adapter专项31通过），完整24条浏览器回归、构建打包和独立审查通过。约定检查仍有素材库两项既有问题。仅升级扩展并刷新页面，不需改1.6.0配套后端；实机浏览器连接不可用，未向真实客户试发。分支 codex/whatsapp-takeover-fixes，基于3e9393ea；未合并推送部署。详见 [复现和交付说明](requirements/2026-09-11-whatsapp-takeover-fixes.md)。

## 2026-09-11 WhatsApp v1.6.0 自动接管（合并交付）

用户授权当前聊天主动开启后自动生成并发送。话术旁新增开关，沿用后台生成预设，模型选择回复/等待/交人工，最多3段短消息。当前前台一对一聊天生效；人工输入、切聊天/后台、发送不确定等停止；浏览器同站点单实例锁。独立审查发现的采集自失效、其他设备抢先回复、发送不确定被新消息覆盖、待开启竞态和最新边界检查均补回归。合并后后端100通过/1跳过，既有超时用例批量运行受初始化时限影响失败、单独复核1通过；扩展250单测、完整23条合成浏览器路径通过，安装和确定性打包通过。约定检查仍有素材库两项既有基线问题；真实WhatsApp和真实模型未测。必须配套更新后端auto_reply_enabled契约，无迁移。用户已授权合并推送，已集成 main 的 a3fa3a45 内贸筛选变更；本轮不部署生产。详见 [使用和边界](requirements/2026-09-11-whatsapp-auto-takeover.md)。

## 2026-09-11 WhatsApp v1.5.3 话术面板排版（本地交付）

在同一worktree保留1.5.1/1.5.2修复，新增建议回复/聊天上下文/询盘与接管三标签。正文与中文含义优先，设置折叠，固定底部填入/重新生成操作。231单测、19浏览器回归通过，桌面/窄屏合成预览已检查，无动画。无需更新后端，本轮未合并推送。详见 [布局与安装说明](requirements/2026-09-11-whatsapp-reply-ui.md)。

## 2026-09-11 WhatsApp v1.5.2 增量历史采集（本地交付）

包含未合并的1.5.1修复。同聊天成功采集历史保存在页面内存；后续生成从当前DOM可靠重叠追加，在底部不滚动，不在底部只向下补齐。聊天/整体消息区切换清缓存，编辑/删除尾部/缺少重叠时重采，不持久化正文。删除尾部的底部和中间起点问题经独立审查发现并修复；类型检查、构建、230单测通过。详细行为与安装说明见 [历史复用](requirements/2026-09-11-whatsapp-history-cache.md)。本轮未合并推送，不需后端变更。

## 2026-09-11 WhatsApp v1.5.1 能力字段修复（本地交付）

用户更新 1.5.0 和生产后端后仍提示后端未支持长历史。确定根因在扩展：background 的 boundedReplyCapabilities 检查 history_enabled 后返回对象丢失该字段，content 再次检查必然失败。返回值现保留已确认的 true；缺字段/false 仍拒绝，并将明确更新提示加入安全错误码列表。

新增 API→background dispatch→content 二次校验回归，修改前失败、修改后通过；补缺字段/false 用例。构建、225 单测、确定性打包通过；本次无后端修改，不需为此缺陷再次部署后端。用户需换 1.5.1 扩展并刷新 WhatsApp 页面。未验证用户实机，未合并推送。
## 2026-09-11 内贸订单客户查询与高级查询（Codex，合并交付）

分支 `codex/domestic-order-filters`，基点 `051e6d04`。常用查询保留订单号、客户名称、订单状态，下单动作单列在查询区标题右侧；下单日期、订单类别/类型/渠道、客户来源收进双列高级查询弹框，窄屏单列。高级查询编辑使用独立草稿，应用后才刷新，取消不变；已选条件显示数量和可移除标签，移除条件重置分页；重置清空查询但保留当前订单大类。查询区整体接入既有表格高度观察，标签和响应式换行后重新计算列表窗口。

新增 `GET /api/domestic/orders?customer_name=`，按当前客户店名包含匹配，与其他条件取交集且在分页前过滤，原创建人范围不变；特殊字符按字面量查询，最多200字符，无数据库迁移。生产订单保留客户、状态、日期查询，清除不适用的业务分类条件。API 说明已同步 `docs/api-reference.md`。

验证：后端客户查询/订单渠道/客户订单权限专项70 passed；补接口参数/长度校验后客户查询专项3 passed；前端筛选状态与订单大类9 passed；最终前端构建通过。Edge 模拟接口完整页面验证客户名+订单号、五项高级条件组合、回车查询、取消、应用、标签移除、分页、生产页签、重置以及1366/1024/768/390宽度，页面异常为0，证据在本 worktree `tmp/order-filters/`。测试仅用内存SQLite和模拟API。约定检查仍被 AssetTagEditor small 按钮及 AssetLibrary 行数基线两项既有问题阻挡；未改相关文件。亮哥已授权合并推送；集成前 fetch 确认 main 与 origin/main 均为 `051e6d04`，无上游代码差异。验证证据归档至主目录 `tmp/domestic-order-filters-delivery/`，主目录其他任务的未提交改动保持原样。本轮不部署应用。Git巡检使用 `--no-fetch` 本地快照。

## 2026-09-11 客户邮件触达 P1（本地实现，未提交待审阅）

在主 worktree 直接实现（基线 main `915837f6`），按设计文档 [docs/2026-09-11-mail-outreach-auto-send-design.md](2026-09-11-mail-outreach-auto-send-design.md) 完成 P1 阶段；亮哥已授权合并推送，直接提交 main 并推 origin（推送前 fetch 核对远端无分歧）。约定检查初跑拦下本任务新增表格 11 处固定列宽，已全部改 min-width 清零；剩余 AssetTagEditor/AssetLibrary 两项为既有基线问题，干净 main 同样复现。交付：迁移 `144_mail_outreach_core`（8 表，编号已核对全分支最大 143；downgrade 按约定抛错）；新域 `backend/app/mail_outreach/`（触达快照/资格/生成/审批/队列/排程客户端 + 14 个人类 JWT 端点，注册 `/api/mail-outreach`；审批哈希锁定 + 同事务建 job + 版本失效 + `_require_human`）；权限 seeds `mail_outreach:read/write/admin/worker`；settings 总开关 `MAIL_OUTREACH_SEND_ENABLED=false`；AI preset `mail_outreach_generate`（方法源与 ark-email-outreach SKILL 双向断言）；前端客户详情「邮件触达」Tab、审核抽屉（照 QualificationPanel 幂等范式）、`/mail-outreach` 队列工作台；Node 排程侧车 `mail-schedule-service.mjs`（复用 outreach-schedule 唯一算法源，Bearer 鉴权，本机 Node v26.3.0）。

验证：后端 54 passed（新增 30：资格/审批/生成/preset）+ 客户与调度回归无影响；侧车 21 passed、整包 69 pass/1 skipped（既有条件跳过）；前端 build 通过、导航布局回归 fail 0；迁移 143→144 离线 `--sql` 渲染 MySQL DDL 正常；`git_sweep --no-fetch` 与增量约定检查均已跑（本地快照）。前后端契约已抽检对齐（context contacts[].points、详情 current_revision、jobs 序列化字段）。

边界：未连真实数据库执行迁移（隔离开发库未确认）；未接真实 Agent Mail CLI/邮箱；发送链路（worker claim/send-authorize/临发复查/收件回流）属 P2/P3 未开工；P0 外部准入（腾讯条款、自有邮箱 PoC、常驻节点）未定。约定检查除素材库两项既有基线问题（干净 main 复现）外无新增红项。

分支 `codex/whatsapp-full-history`，基于 main `915837f6`。按用户方案移除话术内容拒绝校验、直接生成 Agent；默认自动滚动采集聊天 JSON，支持下载，最多 2,000 条/120,000 字符，超过 32,000 字符明确分块摘要。记忆失败不阻断可用草稿。权限、知识撤权、幂等、错聊天和未发送边界保留，无迁移。

后端 93 passed/1 skipped；扩展构建与 222 单测通过；18 项合成 Chromium/Lexical 路径通过（长历史计数起点修正后单独复测）。覆盖 100 条自动加载、120 条虚拟化、160 条后端完整上下文。独立审查闭环。真实 WhatsApp 浏览器连接失败，真实 DOM 加载与模型质量待实测，不能将合成验证视为实机完成。

交付 ZIP v1.5.0，44,029 字节，SHA-256 `03f0ad98bccfee2fe0b7d3cf331fba8e9feb29e0c45dbb9e9d731c6fea291dd8`。后端须同步更新 history_enabled 能力，显式旧 .env 容量/期限及已有 generator 输出预算须核对；亮哥已授权合并推送；集成 main `3a944d1d`，仅交接文档新增记录冲突，已保留双方内容。业务代码与已验证版本一致。本轮未修改生产配置、不部署。详见 [实现、启用与验证说明](requirements/2026-09-11-whatsapp-full-history.md)。


约定检查被未修改的资产 UI 两项既有基线问题阻挡：AssetTagEditor.vue small 按钮、AssetLibrary.vue 行数基线失配；main 同样复现。本任务 diff 空白检查与 Git 巡检通过，未处理其他工作树。

## 2026-09-11 内贸客户列表 UI 优化（Codex，合并交付）

分支 `codex/domestic-customer-ui`，基点 `915837f6`。客户列表沿用内贸订单页的紧凑单元格、筛选栏换行和 `useOrderTableHeight` 窗口高度控制，滚动条常显、分页置于表格外。客户店名移到首列并冻结，左右冻结列补齐悬停背景；操作改为单行“编辑 / 流水 / 更多”，其余五项操作收入下拉菜单，权限与归属条件保持原口径。最近充值金额和时间拆为两列，消除双行内容撑高。

验证：前端构建通过；既有客户权限/筛选测试 2 passed；Edge 无头浏览器模拟数据验证紧凑行高（预览实测 30px）、横向滚动冻结店名、菜单五项、编辑/充值/流水入口、窗口缩放和仅写权限菜单显隐，无页面异常。权限指令挂在菜单项的实际 DOM 外层，避免 Element Plus 菜单项组件不承接指令导致显隐失效。截图与验证脚本保留于本 worktree `tmp/customer-ui/`，未访问真实客户写接口。约定检查仍被素材库两项既有问题阻挡（AssetTagEditor small 按钮、AssetLibrary 行数基线过期），主目录同样复现。亮哥已授权合并推送；集成前 fetch 确认 main 与 origin/main 均为 `915837f6`，无上游差异。验证证据归档至主目录 `tmp/domestic-customer-ui-delivery/`。Git 巡检使用 `--no-fetch`。本轮不部署应用。

## 2026-09-11 背调资格队列修复合并交付

亮哥已授权合并推送。本次集成最新 main `ac7d35eb`，只处理交接文档新增记录冲突并保留双方内容，业务修复与已验证版本一致；合并后资格队列/客户工作流/公海研究专项 96 passed。约定检查被 AssetTagEditor.vue 既有 small 按钮和 AssetLibrary.vue 行数债务基线失配阻挡，干净 main 同样复现，本次未改资产前端。独立审查本轮完成，无阻断问题：三个排序规则修正不改变资格筛选、归属校验、去重或复核状态条件。此次不部署应用，也不重复执行 9 月 9 日的任务激活。

## 2026-09-09 失败背调任务重新激活一次（已执行）

亮哥明确要求将背调中心全部失败任务重新激活一次。生产读取锁定当时失败名单 #1–10、#12–28，共 27 条；逐项调用既有 `requeue_failed_task`，用原 `attempt_count=1` 和行锁核验，不直接绕过状态流转。27 条均重新入队为 `pending`，gate/review 重置 pending，原尝试次数、租约代次及历史错误保留；非目标记录（含已完成 #11）核验未变。新连接验证 27 条均 pending，这仅表示等待执行，不能写成背调已完成。重试防重/权限专项 3 passed；写前快照、逐项回执和写后快照保留在主目录 `backend/tmp/research-reactivate-20260909/`。本次未部署上一轮资格队列修复。

## 2026-09-09 背调资格队列排序规则修复（Codex，待集成发布）

分支 `codex/qualification-collation`，基点 `b0d58ea6`。北京线上日志确认研究任务 11 的 `result-review` 返回 200，随后刷新 `qualification-queue` 返回 500；提示“数据库连接失败”实际是 MySQL 1267。连接采用 `utf8mb4_0900_ai_ci`，持久表采用 `utf8mb4_unicode_ci`；来源 ID 的 CAST 及开发范围的 CASE 在联表时冲突。仅在该查询的 MySQL 表达式上显式使用表的排序规则，不修改 schema、业务数据、审核状态或连接全局配置。

验证：原查询在 `SET TRANSACTION READ ONLY` 连接复现 1267；修复后相同连接配置下列表返回 1 条、详情读取成功（按现有公海权限脱敏，`can_review=false`）、无匹配关键词返回 0。新增 MySQL SQL 回归先失败后通过，资格队列/客户工作流/公海研究专项 `96 passed`；增量约定检查通过，`git_sweep.py --no-fetch` 已运行，仅代表本地远端快照。独立审查代理因模型容量不足启动失败，已另行自查确认权限、队列筛选、分组排序和状态写入逻辑未变，仍缺独立审查结论。未执行生产复核写入，未合并、推送或部署。

## 2026-09-11 WhatsApp 第一、第二阶段集成交付

亮哥已授权合并推送。实现提交 `8c25bbcd`，集成最新 main `d081e1a1`，业务代码及迁移无冲突，仅交接文档保留双方内容。原有144项后端、214项扩展及17项浏览器验证对应的业务实现未变；本次集成后后端144 passed / 1 skipped、扩展构建通过，Alembic单head为143。规范检查在本分支和未修改main均复现素材库两项既有UI失败（AssetTagEditor小按钮、AssetLibrary基线过期）；本任务未改相关素材库代码或弱化检查。迁移143、知识配置和Planner预算仍随后续正式部署启用，本轮不部署。

## 2026-09-08 WhatsApp 话术第一、第二阶段（Codex，本地实现待发布）

分支 `codex/whatsapp-reply-continuity`，基点 `060cef69`。Planner 增加具体动作、未回应请求、已问问题与消息证据；Generator 优先回应客户当前诉求。知识配置增加8段已核对的公开FAQ，方法/政策不能当作对客事实；资料只输出授权FAQ片段，尚未接入实际目录/PDF或业务工具。

新增询盘复盘、承诺台账、人工纠正和内部接管。用户/配对设备隔离，默认保留30天，切换聊天后需预览确认恢复；不按姓名自动关联。生成只产生候选，独立提交采用缓存证据、版本和实例UUID的原子条件，人工纠正及删除重建不能被旧响应覆盖。新增迁移143，只在隔离SQLite验证；线上未迁移、未修改配置或知识正文。

验证：话术后端全套144 passed / 1 skipped（真实模型测试未启用）；扩展214 passed，浏览器17 passed，构建及1.4.0打包成功。独立审查发现的人工优先、异步写回及删除重建并发问题已修复并复查通过。迁移测试核验SQLite保留数据/拒绝有损回退及MySQL unsigned FK DDL；未做真实MySQL并发和实际WhatsApp线上验证。知识20个绑定的ACL/版本/hash及4类检索已用只读事务核验。

交付说明见 `docs/requirements/2026-09-08-whatsapp-reply-continuity.md`。安装包及配置片段在用户工作区 `outputs/whatsapp-reply-phase12/`。后续上线须通过统一部署入口执行143，应用审核后的绑定配置并核对已有Planner预设预算3200；安装新扩展不能替代后端发布。本轮未合并、push或部署。
## 2026-09-09 逐件标签与 Excel 双表集成交付

亮哥已授权将 `f1f0e1f3` 逐件标签规格/序号排版和 `a11a0786` Excel 正常/无价格双表合并推送 main。核验业务代码与已验证版本一致后交付；验证材料归档至主目录 `tmp/domestic-label-export-delivery/evidence/`，远端核验后清理本任务 worktree 和已合并本地分支。本轮不含应用部署。

## 2026-09-09 内贸 Excel 正常/无价格双表（Codex，合并交付）

在 `codex/domestic-label-layout` 接续逐件标签改版：订单导出固定两张工作表，正常表保留原价格、手工费和历史结算摘要，新增“（无价格）”表不写价格列、金额/余额摘要或金额说明。两表都显示客户名称，生产未选客户时显示公司备货，生产两表仍无销售金额。参考图片分别嵌入；完整要求附页改到两表各自末尾，保留全文并扩展打印范围。

验证：业务/生产、关联客户、价格隔离、图片锚点、长要求完整性、历史财务及公式注入防护共 15 passed。独立审查发现附区续行标签行高不足，用 601 字短尾段先复现再修复，最终无剩余阻塞项。实际服务生成样例 xlsx，经 artifact-tool 导入渲染业务/生产的两表，核对客户头、无价格列、文字续区。规范检查通过；无 schema 或真实数据修改。证据在本任务 tmp/two-sheets-*.log 与 export-*.xlsx/png；按本轮授权合并推送，未部署。

## 2026-09-09 逐件标签规格与序号排版（Codex，合并交付）

分支 `codex/domestic-label-layout`，基点 `060cef69`。按亮哥参考图去掉逐件标签 LOGO，左侧自上而下为头套尺码/发长（发片显示工艺）、实际单件序号（01/02，100 以上不截断）、客户名称、系统订单号、下单日期。读取已有 `item.attrs` 与 `units[].unit_no`，分段打印不从 01 重新编号，未改变后端 API、数据库或单件二维码身份。左侧按物理尺寸划分五个区域，长文本调整字号并换行，规格/序号/客户突出，保持日期 2mm 加粗、二维码 16.8mm 和 30×20mm 标签。

隔离浏览器验证头套/发片、缺失规格提示、转义字符、120 字客户名和 64 字编号、真实序号 01/102；屏幕/打印模式均核对字段边界、无区域重叠和标签/二维码尺寸，预览截图已检查。前端构建 18.16s、严格规范检查通过；证据在本任务 tmp/unit-layout-ui.cjs、unit-layout-*.png、unit-layout-build.log。未实际纸张打印；按本轮授权合并推送，未部署。

## 2026-09-09 内贸逐件码跨实例签名修复（配置已生效，手机复扫待确认）

亮哥报告 DO20260908-003 的逐件码无效，提供逐件码原文及微信截图。只读核实该单 item 57 / unit 479 有效、5 道工序完整，38 张在产订单无单件数量缺失；该单创建于 9 月 8 日，不在 9 月 7 日工序快照修复范围。实际原因有两层：北京打印实例仍用旧默认 QR 签名，办公室报工实例用非默认密钥且无 legacy；截图文案则来自客户端格式识别，旧小程序源码只认 ARK-D，当前源码可识别 ARK-DU。用同一原文执行两版扫码函数，旧版精确复现截图、当前版转入 unit 479。

用户授权修复并恢复 office-prod SSH 后，先给办公室增加 QR_SIGN_SECRET_LEGACY，再将北京 QR_SIGN_SECRET 统一到办公室现用值并保留原值为 legacy；未改办公室当前密钥。只改这两个配置字段，配置原子替换并保持原 owner/ACL，其他配置解析值不变。先备份、CAS、独立审查，再通过已有受管服务控制重载，核实服务进程身份变化及两端 health=ok/database=connected；没有代码切换、schema 迁移或订单/工序/报工修复写入。首次尝试分别遇到 Windows ACL 的 AI 元数据差异、北京 root 文件归属，均先确认原配置摘要未变，针对原因修正后继续，未重复执行不确定写入。

新连接复核：两端新二维码完全相同，原 unit 479 签名均有效；ARK-DU/D/P/I 的新旧签名均有效、篡改签名拒绝。北京打印日志涉及 7 张订单、9 条明细、424 个单件：在产 DO20260907-005/007、DO20260908-002/003、DP20260908-003 共 384 件；另 DP20260908-001/002 的 40 件属于已终止订单，状态未改。该范围旧签名全部通过，日志仅证明取过打印数据，不证明每张纸均已打印。两端真实 HTTP 进度接口以当前签名返回 200 与 DO20260908-003，以旧签名返回 403；原二维码的实际手机登录扫码尚待用户复扫确认，不能将此进度接口检查写成手机扫码已完成。浏览器验证工具因 debugger unattached/超时不可用，未取得已登录页面验证。小程序既有测试 24 passed；新旧格式函数复现记录已保存。

一次性脚本与非敏感验证证据在主工作区 `.deploy_state/qr-config-repair/`，两台服务器各自 `.deploy_state/qr-config-repair-20260909/before.json` 保留受限备份（含敏感旧配置，只留原服务器，不提交或输出）。恢复前比较当前两字段与备份 after，仅恢复备份 before 的值/原存在性，不覆盖其他配置，随后受管重载和复核。legacy 是已打印标签过渡配置，现有实现覆盖内贸、外贸及出库单的登录扫码；待这些旧标签消化完、确认所有打印入口均使用统一新签名后再移除，不按日期自动删除。免登录进度码始终只认当前密钥；北京旧默认期间官方进度码生成/验证本就锁定。小程序需使用含逐件扫码的版本，本轮没有上传、审核或发布小程序。本次 Git 交付只包含修复记录；一次性运维脚本和验证证据留在本地恢复目录。

## 2026-09-08 WhatsApp 生成依据契约（Codex，合并交付）

## 小程序提审准备（2026-09-09）

分支 `codex/miniprogram-review`，目录 `D:/MyProgram/commission-system-codex-miniprogram-review`。截图反馈拍照板块无法体验核实；本地 photo 页仅选图预览，识别未实现，原实现只隐藏入口但仍注册页面。现移除 photo/assistant 的页面、tabBar 注册及菜单入口，上传配置排除两个占位目录和 tests，出库检验拍照保留。

24 项 Node 测试、增量约定检查与 diff 空白检查通过；Git 巡检为 --no-fetch 本地快照。未做微信编译/真机验收，未上传、未提交审核。浏览器控制 Transport closed；开发者工具 CLI 因服务端口关闭而阻断，未开启该设置。拟上传版本 2026.09.09.1。

下一步：开发者工具导入本任务目录下 miniprogram 并编译上传，公众平台重新提审。需核对审核测试账号权限、可用测试二维码及体验路径，不使用真实业务数据完成测试。

提审说明草稿：本次移除了尚未完成的独立“拍照上传（AI 识别）”和“生产助手”页面及导航入口；保留已实现的出库检验拍照留档功能。请使用提供的测试账号和对应测试单二维码体验。账号、二维码及具体步骤须在提审前补齐核实。


分支 `codex/whatsapp-reply-evidence-contract`，基点 `cda42155`。针对仅有 method/constraint 时模型仍尝试引用而触发依据校验：生成输入显式携带原始来源编号及可引用事实编号，动态 schema 限定允许编号、无事实时要求空 claims；提示词区分方法、约束与对客事实。不改 guard、不剥除引用、不自动重试，不涉及数字校验或启动权限自动授予问题。

新增生成契约回归先失败后通过，覆盖无事实、混合来源原始编号、违规引用仍拒绝及 schema 请求隔离。话术离线回归 107 passed / 1 failed；失败为本地慢流超时测试请求未到达服务器，在未修改主分支单测同样复现，未改测试断言。独立静态审查无阻塞。亮哥随后授权合并推送，先集成远端 `6a6fb225`，仅交接文档冲突并保留双方记录，业务代码无冲突；未调用真实模型或部署，`.env` 无需调整，线上效果需发布后验证。

## 2026-09-08 0908 生产重跑：事实契约缺口

- Validation: 197 related backend tests (in-memory SQLite), 63 Node tests and conventions checks passed. Independent review passed after enforcing source-only layers.
- Task 11 remains running until lease expiry: the original MCP process ended and a follow-up could not fail without its lease. Do not guess credentials; updated local MCP preflight will prevent claims against the old fact contract. Tasks 12-28 remain failed.

- 管理员浏览器通过 retry API 成功重新入队 task 11；本机 OpenClaw 创建实际 Run 1，attempt 2，行业 gate passed。
- 真实公开搜索完成后，推断 provenance 缺失触发 422；修正后未登记的 fact_key 连续触发 400。无事实入库，无有效结果完成；其余 17 条仍未重新入队。
- 分支 codex/research-facts-contract 补充受限的公开公司研究事实登记及动态 fact_contract；MCP 在领取前检查该契约，防止旧后端消费任务。需要部署此补丁及更新本机 MCP 后再单条验证，不可把本轮 CLI status=ok 当作业务成功。

### OpenClaw 背调补丁合并（2026-09-08）

亮哥已明确授权合并并推送 PR #2。此次合并外部背调 Run/证据回执闭环、MCP 自动注入 Run ID 与停止后续领取保护、具备客户范围权限的人工重试接口。本机新版已经安装，生产后端仍待统一部署；18 条任务 #11–28 尚未重新入队。本次仅合并推送，不代表部署或背调完成。

### OpenClaw 0908 背调 Run 闭环修复（2026-09-08，后端待部署）

任务 #6「0908」搜索已完成20条，背调 #11–28 共18条failed，均attempt_count=1/agent_run_id=NULL；最先facts 409为无匹配Run，后续无有效fact回执仍提交complete，最后#18–28被批量领取后标failed。此次修复：Agent claim与外部running Run/客户范围/created、started事件同事务；事实与规范tool.requested/succeeded回执同事务并返回tool_call_id；旧租约/跨任务/替代Run继续拒绝，结束/跳过/重领关闭Run。native重审保持兼容。新增人工retry端点，管理权限+客户范围+expected_attempt_count CAS，不向MCP开放重试能力。

MCP自动保存并注入Run ID，不再让模型填写；旧后端preflight在领取前阻断。单任务限制、claim丢响应和任务fail后停止新领取，恢复后需重启MCP；知识搜索数组改为structuredContent对象。公司研究、公海研究Skill与heartbeat规则同步。

验证：相关后端152通过，Node61通过；覆盖真实HTTP领取→事实→引用→完成闭环、写入回滚、旧Run隔离、native重审、retry权限403/404/200、领取丢响应和旧后端零领取。独立审查三项问题均已修正并复审通过，约定检查通过。使用隔离SQLite（autoflush=False）；未跑真实MySQL并发。尝试额外customer_api全路由收集因测试环境缺jinja2而中止；相关路由自身权限与请求测试已通过，未将其记作全量通过。

本机安装目录 `~/.openclaw-ark-sales/runtime/research-run-b01b19e5`，MCP配置、双工作区Skill/HEARTBEAT同步，私有备份 `backups/research-run-b01b19e5`。本机已重启，后端尚未部署，未重新入队或改动18条生产任务。当前SSH配置仅有github.com，`office-prod`无法解析，已向用户询问当前部署入口；用户询问是否本机执行，已解释本机负责搜索与研究、后端负责执行记录和证据校验。恢复部署通道后走统一deploy.bat固定此分支修订，核实execution_contract，再仅重试#11–28（expected_attempt_count=1），先验证一条完整成功再按单任务heartbeat处理其余，遇系统错误停止。

## 2026-09-08 列表密度与标签日期集成交付

亮哥已授权合并并推送 main，包含 `d27d0c98` 内贸列表密度优化及 `9259091c` 逐件码日期放大。开发基点为 `b61e1a4f`；交付时 main 已进入 PDA 修复 `21962ff9`，先在任务分支合并最新 main，交接文档保留双方记录，业务代码互不重叠。核验两侧代码各自保持已验证版本后集成推送。证据归档至主目录 `tmp/domestic-density-date-delivery/evidence/`，远端核验后清理本任务 worktree 和已合并本地分支。本轮不含应用部署。

## 2026-09-08 逐件码日期放大（Codex，合并交付）

接续 `codex/domestic-list-density`：日期字号由 1.25mm 调至 2mm、字重 600，年份与月日分组，窄列按组居中换行。略缩 LOGO 高度并增加文字间距，保留 30×20mm 标签、16.8mm 二维码尺寸与单件身份。隔离浏览器以普通/长客户名、120 字名称、64 字长编号、转义字符和生产用途，验证屏幕及打印边界、元素不重叠和日期分组；前端构建及规范检查通过。未实际纸张打印，证据在 tmp/date-size-ui.cjs 与标签预览截图。

## 2026-09-08 内贸列表显示密度（Codex，合并交付）

分支 `codex/domestic-list-density`，基点 `b61e1a4f`。下单按钮与全部查询条件合并为一个自适应工具栏，缩小卡片留白；去除表格单元格内外重复横向 padding，使普通系统编号单行完整显示，数据行上下 padding 减为 4px，保持 13px 字体、长号换行和前两列冻结。筛选高度观察同时支持原生元素，切换生产标签后表格重新利用剩余高度。

隔离浏览器相同 20 行含系统号与客户订单号数据：1366×768 完整可见行数 2→7，1440×900 为 4→10，1024×700 为 1→6；样例行高 90→49px。验证业务/生产标签、总数、横滚冻结、长号换行、完整日期、表头提示、搜索/状态筛选及两个下单入口通过，页面异常 0；390px 视口适配检查通过。前端构建与严格约定检查通过，无后端、业务数据或 schema 修改。证据归档至主目录 tmp/domestic-density-date-delivery/evidence/；按本轮授权合并推送，不含部署。

## 2026-09-08 PDA Android 6.0.1 HTTPS 修复（Codex，合并交付；待真机验证）

`codex/pda-android6-tls` 基于 `ea4eb3bb`，针对 PDA 登录“检查 Wi-Fi 和服务器地址”：用户确认设备为 Android 6.0.1；线上 `www.leshine.cloud` 的 HTTPS、健康检查和登录参数校验正常，证书为 9 月 5 日替换的 Let's Encrypt。客户端原来只依赖系统根证书，旧安卓缺少 ISRG Root X1。

PDA 1.0.5（versionCode 6）仅对 Android API 23–25 的 cloud/work 四个精确主机名追加官方 ISRG Root X1，保留系统根证书和默认域名校验；按证书、DNS、超时、拒绝连接细分错误。报工契约和默认/已保存地址不变。亮哥已授权合并并推送 main，本次不含后端部署。

验证：32 项 JVM 测试通过（包含显式开启的线上只读 TLS 测试），模拟移除 ISRG 根证书时复现握手失败、补根后 cloud/www cloud/work 的鉴权端点返回预期 403；APK 构建、Android 6 所需 v1 签名和最低 API 23 核验通过。新包签名与主目录现存旧 PDA APK 一致，可覆盖该旧包升级。约定检查通过；Git 巡检已运行 `--no-fetch`。APK 和失败/通过测试证据已保留到主目录 `tmp/pda-android6-tls-delivery/pda-tls-evidence/`。尚无连接的真机，需 PDA 覆盖安装后确认登录和扫描；不要卸载以免清除待确认报工。

## 2026-09-08 草稿追加与生产客户集成交付

亮哥已授权合并并推送 main，包含 `073c179e` 保存后草稿追加明细及 `d594c970` 生产单可选客户、逐件标签编号换行和下单日期。从 `ea4eb3bb` 快进集成，核验业务代码与已验证版本一致后推送；远端核验后清理本任务 worktree 与已合并本地分支。迁移 142 随后续部署入口执行，本轮不部署、不对真实数据库执行迁移。
## 2026-09-08 生产单可选客户与逐件标签日期（Codex，合并交付）

在 `codex/domestic-draft-items` 接续草稿追加明细：生产单新建、编辑支持选取已有客户，也可留空或清空；列表、详情、导出及打印显示关联客户。生产金额保持零，不产生资金流水，也不计入客户购买次数、复购或公海保留期限。逐件标签长系统编号居中换行，下方显示下单日期；二维码身份及尺寸不变。

新增迁移 142 仅放松生产客户必须为空的 CHECK，保留零金额及业务客户必填约束；不修改历史订单数据，已有客户关联时拒绝有损回退。尚未对真实数据库执行迁移，需随部署执行。

验证：后端内贸 683 passed / 1 skipped，前端 56 passed，构建通过。隔离迁移测试验证数据保留、约束及回退保护；浏览器验证新建选客、编辑换客/清空、列表显示、长编号居中换行和日期，以及长客户名/编号的标签边界，页面异常 0。独立审查发现的客户公海口径问题已用失败回归复现并修复。证据归档至主目录 tmp/domestic-draft-customer-delivery/evidence/；本轮按授权合并推送，不含部署。
## 2026-09-08 保存后的草稿继续添加明细（Codex，合并交付）

分支 `codex/domestic-draft-items`，基点 `ea4eb3bb`。编辑本人草稿，在产品明细旁点击“添加明细”，支持普单报价/优惠价/手工费、特单销售价和生产备货规格及图文。独立保存后刷新明细，可再次打开继续添加。新增保留草稿、不扣余额，提交统一结算；后端 draft_only 锁内检查阻止订单已提交后的意外追加，成功请求仍可幂等重放。

验证：会员报价与订单大类测试 344 passed / 1 skipped，包含草稿追加不扣款、提交含新明细、提交后原追加请求重放不重复扣款、非草稿拒绝。隔离浏览器覆盖三种订单新增、价格 payload、重新打开持久显示、取消保留/放弃输入及 1024/390px 短窗口保存按钮。独立审查通过；无真实业务数据写入或迁移。

## 2026-09-08 内贸四轮改动集成交付

亮哥已授权合并并推送 main，包含 `e1ce12c2` 打印按钮、`087debe0` 台账总数与滚动、`a4111e17` 草稿删除与末道完工回算、`27858eea` 逐件标签客户名称。基点 `05bd1bb6`，以已验证代码快进集成；不含应用部署。验证材料归档至主目录 `tmp/domestic-print-ledger-delivery/evidence/`。核验远端后清理本任务 worktree 与已合并分支。

## 2026-09-08 逐件标签客户名称（Codex，合并交付）

在同一任务分支将逐件码标签原 A1-01 文字替换为客户名称，自动换行；生产单显示公司备货。接口补充客户名和订单大类，二维码仍为每件独立签名身份。接口测试确认客户名及两个不同二维码，浏览器检查普通/长名称、特殊字符转义、生产用途及屏幕/30×20mm 打印边界通过。

## 2026-09-08 草稿删除与末道完工回算（Codex，合并交付）

继续在 `codex/domestic-print-footer` 完成：普通业务员可删除自己的草稿；非草稿管理权限和创建人限制保留。明细只看末道实际报工的有效单件数；全部明细完成后整单自动完成。修复生产 autoflush=False 下明细/整单聚合读取旧状态，以及末道撤销后未回退的问题。报工流程与顺序权限不变，无迁移或真实数据写入。

回归先复现自动完成、上游独立和普通草稿删除失败，独立审查发现真实撤销路径同源问题后补测试修复。浏览器验证本人草稿删除确认/取消、删除后刷新、非草稿及他人草稿无入口，页面异常 0；前端构建通过。内贸回归 676 passed / 1 skipped，审查后受影响报工、条件路线、订单大类及权限测试 211 passed；约定检查通过。

## 2026-09-08 内贸订单总数与台账布局（Codex，合并交付）

在 `codex/domestic-print-footer` 上继续完成：列表状态前增加产品总数、详情按所有明细数量求和；客户/用途移到第二列，与编号共同冻结左侧，长编号换行；紧凑列间距、完整日期、表头悬浮提示；表格按窗口剩余高度显示并常驻横向滚动条。业务和生产 Excel 空白人工列改为出库数量并同步说明。无迁移、无真实数据写入。

验证：前端构建通过；导出及财务相关测试 13 passed；隔离浏览器在 1440×900、1024×700 下覆盖业务/生产页签、列表与详情总数、横滚冻结、长编号换行、完整日期、滚动区底部位置及表头提示，页面异常为 0。此分支还包含前轮逐件码/流转卡打印按钮修复。

### 内贸打印弹框按钮遮挡（2026-09-08，合并交付）

分支 `codex/domestic-print-footer`，基点 `05bd1bb6`。共享打印弹框（详情流转卡、逐件码和进度码）改为挂载到 body，顶部留 16px 与全局视口高度限制一致；底部范围/份数独占一行，提示和打印动作允许换行、动作不压缩，逐件范围输入宽度限制为 90px，修复 520px 标签弹框中一行内容过宽导致打印按钮裁切。打印文档和 iframe 打印逻辑保持原样。

隔离浏览器全部 API mock，从订单详情分别打开逐件码和流转卡，在 1440/1024/390px（含 600px 短视口）验证打印按钮位于视口内、点击中心未遮挡，并通过替换 iframe.print 的计数验证点击确实调用目标 iframe；未实际发起纸张打印。页面错误为 0，前端内贸 55 项测试、构建及规范检查通过。脚本和截图保留任务 `tmp/`；无需后端或数据变更。

### 内贸列表标签与客户操作列（2026-09-07，合并交付）

接续 `codex/domestic-order-channel-source`：订单大类单选按钮改为列表面板顶部的「全部订单 / 业务订单 / 生产订单」标签页，沿用原筛选与重置行为；下单入口留在筛选区上方。客户列表固定操作列的按钮用 flex 自动换行并清除相邻外边距，解决最多 7 个操作挤在单行被裁切的问题，不改权限和动作。

隔离浏览器 API mock 实测三个标签的请求参数与选中态、客户 7 个按钮在 1440/1024/390px 下全部位于单元格范围且中心点击命中、编辑弹窗可打开，页面错误为 0。前端内贸 55 项通过，构建及规范检查通过；本次仅 UI 排版，无后端或真实数据变更。亮哥已授权将本轮与上一轮内贸改动一起合并推送 `origin/main`，不含应用部署。功能提交 `0488cbd5`、`9b359a43` 从基点 `e3f4f117` 快进集成，业务代码与验证版本一致；验证材料归档至主目录 `tmp/domestic-channel-source-delivery/evidence/`，推送核验后清理临时分支和 worktree。最终 UI 构建耗时 18.82s。

### 内贸选填订单号、渠道和客户来源（2026-09-07，代码已验证，历史数据已转换）

分支 `codex/domestic-order-channel-source`，基点 `e3f4f117`。业务下单和编辑允许空客户订单号，统一存空串并保持请求幂等；新渠道为充值扣账/现金结账，按所选客户结算方式预选，可手动修改；订单列表客户/用途后增加客户来源列与来源筛选，复用客户档案字段，保留创建人范围和分页口径。没有 schema 变更。

亮哥本轮明确要求转换历史业务订单：已在 `commission_db` 执行受指纹/行锁/备份保护的数据转换，31 张业务单全部完成，20 张 recharge（prepay）、11 张 cash（credit）；旧渠道字典停用，新增两个启用选项。只改渠道与更新时间，事务内核验订单其他字段未变；没有改变余额结算行为、客户属性、生产订单或工序。独立新连接复核 `changed_orders=0`。备份在主目录 `tmp/domestic-order-channel-conversion/before.json`，预检指纹 `6d1f8f67390311fd9a31da2876ca9b2018884c6b5b2a771010edd0bc3c547b50`，提交后指纹 `b131a9d4ae99d6176b6eb12370b7f95b643b5b3300bc4d3f9d33e1a2a55a2636`。脚本 `backend/scripts/domestic_order_channel_cutover.py` 默认只预览，不要重复 apply 覆盖未来用户手工调整的渠道。

验证：后端内贸 `662 passed, 1 skipped, 724 warnings in 95.81s`；前端内贸 `55 passed / 0 failed`；Vite `built in 20.71s`；规范检查通过。隔离浏览器全部 API mock，验证空号新建、清空订单号编辑、来源列顺序和请求筛选参数，以及新增/复制保价、图片编辑、差额确认和手机布局，`errors=0`。独立审查指出的非法订单号类型和空值幂等边界已修复，最终无剩余已发现阻塞项。应用代码现按本轮授权合并推送，未执行应用部署；历史渠道及字典已在真实数据中生效，旧页面需刷新选项。

### 工作区存量改动集成（2026-09-07，授权合并推送，未部署）

亮哥先授权本地提交，再明确要求合并推送。文档提交 `470609c8` 与迁移工具提交 `1f136ba9` 在 Codex 任务分支整合；以远端 `fbea64b1` 为基点，保留主线全部后续部署修复、PM2 状态核验、四类 writer 清单、默认受限凭据和共享恢复日志。专项 137→138 入口补传 schema、成功恢复后关闭共享日志、无 pending 时仍检查未完成恢复，并拒绝与 `--revision` 混用。旧迁移记录仅描述当时结果，不代表本次执行生产迁移。

集成验证：部署测试 `63 passed, 11 skipped`（Windows 跳过 Linux 文件系统语义）；新增两项共享日志回归先失败后通过，编译与覆盖 `fbea64b1` 的约定检查通过。独立审查因额度限制不可用，按完工清单补一轮自查，未声称独立审查通过。本轮仅 Git 合并推送，不部署、不执行数据库操作；旧 stash 与原迁移工作区中的恢复材料保留。

### WhatsApp 话术助手（2026-09-07，1.3.0 合并交付，未部署、待模型验收）

**授权集成**：亮哥在获知模型基线未通过后明确要求合并推送。本轮交付为把功能 `1f89f00a` / JSON 模式修复 `3f0a7960` 整合至 GitHub `origin/main`，不包含发布或新增付费调用。任务分支已整合主线 `f9a0c313` 与最新远端 `3ff473f7`；仅交接记录冲突，双方内容完整保留，话术业务代码与已验证版本一致。合并后相关后端 **271 passed, 1 skipped**（24.98s），Alembic 唯一 head 为 `141_whatsapp_reply_requests`；约定检查 0 红/1 已核验的设备鉴权黄项。扩展代码未变，沿用 198 单测/14 浏览器测试及构建证据。主目录 6 份原有修改单独保留，不夹带提交；生成包和验证材料归档到主目录 `tmp/whatsapp-reply-delivery/`，推送核验后清理本任务 worktree。下方“本地、未推送”为此前验证阶段记录；模型验收未通过的结论不因合并改变。

**真实模型验收更新**：亮哥随后允许 30 条合成对话、最多 60 次调用，实际执行 59 次、103,410 tokens（`deepseek-v4-flash`，关闭思考，全部隔离内存数据）。初轮 30 条均在 planner 结构校验失败，1 次诊断确认 JSON 被 Markdown 围栏包裹；已为独立话术 OpenAI 预设默认补 `response_format=json_object`，严格解析/安全规则未放宽，不改翻译或已有管理员配置。修复后 14 条端到端复测为 5 ready / 6 needs_confirmation / 3 安全拦截，中位 9.094s、P95 18.688s，**尚未达到上线验收**。3 条拦截未返回草稿，因未保存正文不能判定正确拦截或误拦；已加测试专用的规则类别诊断。剩余 1 次不足正常两阶段验证，未再调用。完整元数据见 [模型基线](requirements/2026-09-07-whatsapp-reply-model-baseline.md)。以下 268/198/14 为此前离线交付证据，不替代模型质量/时延验收。

在 `codex/whatsapp-reply-design` / `commission-system-codex-whatsapp-reply-design` 实现确认的方案和 SOUL。吸收谈单助手的客户复盘、阶段与活跃度分离、买方动作证据、按阻塞选择推进方式；不引入阿里记录提取。扩展新增话术入口、双方已加载 20/40 条上下文、一条回复预览及中文含义/理由、选用草稿意图和目标、语言/风格调整、安全填入和恢复，绝不发送。当前代码和包均为 1.3.0，后端默认关闭，现有翻译预设和线上配置未改。

后端新增 `/api/whatsapp-translation/reply-suggestions`、独立 `whatsapp_reply:write` 与两个关闭的预设。每次请求通过真实设备所属员工的实时 ACL 读取发布知识，来源用途绑定修订/章节哈希/政策版本；必需政策缺失只作安全澄清。最多两次 AI facade 调用，30 秒整体期限会关闭在途传输；不持久化正文、草稿、回复或检索词。141 迁移仅存跨 worker 幂等、配额和耗时元数据；相同请求结果丢失不自动再计费。

验证：后端话术/翻译/知识库/AI 调用相关 **268 passed, 1 skipped**；跳过的是尚无付费授权的真实模型基线。扩展 **198 单测 / 14 Chromium+Lexical 浏览器测试**、构建/确定性打包通过。独立规格与代码审查发现的关闭后恢复误写、自动识别语言未失效、原文换行丢失、慢分块绕过总期限、服务端字符上限未接入共 5 项已修复并回归，最终审查通过。约定检查 0 红/1 黄（已核验设备鉴权豁免，路由注释及服务实时授权测试齐全）。迁移证据为 SQLite 上下行保留历史行和 MySQL unsigned DDL 编译；尚未真实 MySQL 执行 141，也未验证生产多 worker 争用。

本地包 `extensions/whatsapp-translation/release/whatsapp-translation-1.3.0.zip`，36,078 bytes，SHA256 `6ef76643c4bbe89e1ff501c8a4eb2f43b2c71a287d381f5412b56ed1698b944c`。源码与文档保留在独立 worktree；不提交生成 ZIP。未合并、推送、部署或写生产知识/权限。相关源码、API、数据库、模块说明已同步。

仍待：完成修复后的完整 30 条模型复测（新付费调用需另行授权）、安全拦截诊断、性能优化、业务负责人语义盲评和实际 WhatsApp 1.3.0 冒烟；启用前核验供应商保留策略、来源对外用途与冲突政策，再另行授权部署。只读检查没有将“已发布”自动当作“允许对客披露”。入口见 [验收记录](requirements/2026-09-07-whatsapp-reply-implementation.md) / [启用说明](requirements/2026-09-07-whatsapp-reply-activation.md)。不能将离线绿色测试称为销售质量验收。

### 展会 AI 试戴 A 私享沙龙（2026-09-07，合并交付，未部署）

亮哥从三版高保真方案中选择 A 并授权实现。本轮分支 `codex/expo-private-atelier-20260907` 基于 `55d8a21a`，迎宾、登记、拍摄、分析、选款、场景、结果、顾问和合作弹窗统一为奶油白、深咖与香槟棕的私享沙龙视觉，加入摄影展开、错峰入场、柔光等待及实际成图加载后的镜面揭晓。主题限定 `.xk-root`；API、鉴权路由、数据库及流程 composables 未修改，保留最新后台动态出图版本、额度、推荐、扫码、分享和原图打印。设计与复跑说明见 `docs/requirements/2026-09-07-expo-private-atelier.md`，生成主视觉的来源记录在 `frontend/src/assets/expo/README.md`。

验证：主站生产构建通过；Expo 专项 25 项测试通过；真实 Vue 页面配合合成 API fixture 的浏览器验证通过，覆盖六种尺寸、试戴与场景两条流程、相机/相册/扫码入口、推荐/自选、颜色及动态版本请求、拖动/键盘对比、反馈、二维码、打印桥、顾问、额度为零、退出确认和减少动态效果。异常补测覆盖生成失败重选，以及展示版、原图和仅原图历史结果的加载失败与恢复；浏览器未捕获运行错误。独立审查发现的横屏触区遮挡、失败提示遮挡及图片错误回退问题均已修复并复核，无剩余阻断项。

截图和机器可读证据保留本任务目录 `tmp/expo-atelier/`；测试只使用合成资料与生成的示意人物，未提交真实客户或调用付费 AI 生成。物理 Android/iPad 相机与打印机仍需设备验收。亮哥已授权合并并推送 `origin/main`，本轮不含生产部署。集成最新主线 `f9a0c313` 时仅交接记录发生冲突，两项记录均完整保留，功能代码未改写。

### 当前业务订单路线批量更新（2026-09-07，真实数据已完成）

亮哥明确要求所有当前业务订单按头套/发片切换为「业务普单 · 头套网帽（递针）」/「业务普单 · 发片网底（递针）」。已在 `commission_db`（revision `140_domestic_order_kinds`）单事务完成：31 张未删除业务单、43 条明细，35 条头套对应 route 13、8 条发片对应 route 15；42 条实际调整，1 条原已正确。范围包含 3 张特单、1 张终止单及草稿，保留类别和状态；不改变未来特单选路规则，不修改生产订单。

写前及锁内均确认所有目标无报工、跳过或逐件历史，全部工序完成数为 0。按订单→明细锁顺序与在线写者串行，保存旧路线/工序快照后移除 756 个多余空进度、补齐 35 个缺少的目标工序，共同工序保留原 ID。所有明细现为毛坯出库→三次毛坯质检→做发型→发型检验→发货完成，共 215 个进度行。订单所有字段及明细除 route_id/updated_at 之外的字段摘要在事务内一致，未改数量、金额和财务流水；独立审查无阻断，实际 SQL 已在隔离 SQLite 合成数据验证三类旧快照。提交后另开只读连接复核 `changed=0/remove_empty_steps=0/add_empty_steps=0`。

一次性脚本保留 `tmp/refresh-domestic-business-routes.py`，备份与执行/复核结果保留 `tmp/domestic-business-route-refresh/`。恢复前必须核验执行后是否新增报工，不可盲目恢复旧进度；当前脚本重复 apply 会因备份存在而拒绝。此为已授权业务数据维护，没有 schema 迁移或应用发布。本条保留为当前工作区文档更新，未夹带原有未提交修改做 commit/push。

### 内贸订单编辑、报价缓存与 Excel（2026-09-07，合并交付）

本轮在 `codex/domestic-order-edit-export`（独立 worktree `commission-system-codex-domestic-order-edit-export`）完成亮哥 7 项优化：业务 Excel 仅客户编码、对应产品单元格嵌入参考图、真实余额前后及本单金额、原价/减免额/优惠后商品单价/手工费/小计、数量后空白入库数量；新增或复制行保留其他行手工价；保存成功清空 KeepAlive 新建表单；提交后可由创建人独立编辑订单头、明细数量/成交价/图文。草稿标记预计余额，已调整订单区分当前总额与实际补扣/退回，生产单保持无销售金额。未新增迁移，未修改真实业务数据。

编辑成交单价包含手工费，优惠额计算先减手工费；已发货/终止及报工数量限制沿用服务端。仅发送实际变化字段；历史零价明细仍可改备注、图片和数量。独立审查指出的短多行图文重叠、历史零价编辑校验与金额浮点上界误拦已修复并加回归，最终复核无剩余已发现阻塞项。

验证：后端内贸 `655 passed, 1 skipped, 714 warnings in 87.85s`；前端内贸 `54 passed / 0 failed`；Vite `built in 18.01s`；`check_conventions --strict` 增量无违规。隔离浏览器（所有 API 为合成 mock）实测新增/复制保价、保存草稿后重新新建、正式订单头修改、明细数量/含手工费价格/图片上传、补扣确认以及 390px 布局，`errors=0`；不是生产后端端到端验证。Excel 真实文件的媒体、锚点、单元格和财务快照测试通过，合成示例与页面证据保留本 worktree `tmp/`。没有可用 Excel/LibreOffice，未声称完成原生 Office 打印验收。

亮哥已授权本轮合并并推送 `origin/main`，不包含生产部署。功能提交 `c9aed860` 已通过上述验证；集成从 `55d8a21a` 快进，不改写功能代码。主目录原有六份未提交修改单独保留；验证材料和合成 Excel 归档到主目录 `tmp/domestic-order-edit-export-delivery/evidence/`，临时任务 worktree 在推送核验后清理。Git 巡检使用 `--no-fetch`，不自动处理他人分支。

### 默认双击部署与 140 迁移（2026-09-07，已发布并无参数复跑）

用户再次运行默认 `deploy.bat` 时，main 已包含 140，而上一轮只固定发布 139；要求每次传 `--migration-credentials` 导致双击入口继续报错。修复 `8b4556fa` 使默认调用读取办公室运行仓库 `.deploy_state/credentials/migration.env`，显式参数仍可覆盖，指定文件缺失不会静默回退。服务器已配置限定办公室来源及 `commission_db` 的独立迁移账号（九项 DDL/DML 权限，无账号管理/转授权），文件及目录 NTFS ACL 仅部署账号、SYSTEM、Administrators。该账号和文件长期保留供后续部署使用，不再随一次发布清理；没有复制到开发机、候选或云服务器，应用 `.env` SHA-256 未变。

BAT 从 PATH 定位 Git，优先使用其自带 SSH，已验证含空格/括号的安装路径，不再依赖临时手改 PATH。`--prepare-only` 成功状态修正为 `prepared`。Windows 部署回归 53 passed、11 Linux-only skipped；独立审查通过。未修改 140 业务迁移本身：补充真实库只读预检确认全部旧单满足新约束、两旧 CHECK 存在、没有部分 140 结构，两源路线启用且四计划为 18/5/18/5 步和 4/0/4/0 条规则。用真实 139 表定义在随机新 MySQL 库造合成数据，实际 upgrade、历史字段保留、新路线/规则、合法与非法生产字段、拒绝有生产单时 downgrade、回滚合成新行后 downgrade/re-upgrade 均通过；没有复制客户数据，三次演练创建的随机库全部删除。

服务器先快进仅工具补丁 `4fa5dc4c`，随后以默认目标准备并**两次实际执行无参数 `deploy/deploy.bat`**，未传 revision、migration-credentials 或手设 SSH PATH（仅 `DEPLOY_NO_PAUSE=1` 用于无人值守收集退出码）。两次均退出 0，发布版本 `40c4a46ab79212c0b1ef3c859a83f29645cf71e9`，覆盖当时 main 的 140 与此前未上线代码。首次经统一入口停止全部四个 writer，执行 `139_expo_prompt_versions → 140_domestic_order_kinds` 并完成双后端/云静态切换；第二次构建跳过、四目标零变化/零传输，无服务重启，`publish-current.json=succeeded`、`schema-writers.json=completed`。

维护窗口冻结新加坡/北京各主站、PM 和北京 IP API 入口及办公室 8001 直连，两后端线程栈无 Expo 任务后才切换。迁移后 19 张相关表的全部旧字段摘要一致，包括 30 张订单、42 条明细、931 条进度、540 个客户和 72 条资金流水；只按计划新增四条路线及其步骤/规则。四个 writer 均恢复，Nginx 配置按原摘要还原，临时防火墙规则撤销。两主站及 PM/素材首页 HTTP 200，两主站健康检查为 `ok/database=connected`，内贸接口匿名为 403。原有 Matplotlib 可选依赖和 Nginx 配置警告非本次阻断，未为消除警告改依赖或无关站点。

交付证据保留主目录 `.deploy_state/default-migration-delivery/`，服务器保留本轮日志、摘要及维护回滚备份；临时诊断工具清理。部署账号后续轮换/撤销按 `deploy/README.md`，不要改运行 `.env` 或删除迁移保护。未纳管独立服务和小程序/浏览器扩展的终端安装仍按部署清单单独处理；这里的无参数成功指已登记的办公室与云应用发布。

### OpenClaw 获客修复合并（2026-09-07）

亮哥已授权将 PR #1 的候选契约、主要身份唯一约束冲突及原批次超时重试修复合并并推送 main。本机 OpenClaw 已安装并验证；本次为代码合并，不执行生产发布或任务重新入队。最新部署交接已记录办公室可用入口 `office-prod`，下方“没有部署通道”为修复当时的历史记录。

### 数据库 139 全平台发布（2026-09-07，已完成）

亮哥授权合并、推送并更新服务器，随后提供办公室 `backend/.env` 作为迁移管理凭据来源。通过统一 `deploy/deploy.bat` 固定发布 `bf36a2e13b8b3f736932bc3982ebde0bd8a386dc`：办公室和北京后端均到同一版本，新加坡/北京主站制品摘要一致；PM 与客户素材门户内容未变且 HTTP 摘要核验通过。正式发布退出码 0，`publish-success.json` 指向该版本，迁移 writer 日志为 `completed`。本次只发布已演练的 139，未包含 main 后续新增的 140 内贸迁移、物流展示和 OpenClaw 改动；下次发布仍须按实际 pending 迁移检查，不能直接用 main 代替本次候选。

现场依次解决陈旧 `publish.lock`、writer 清单/PM2 控制缺失，以及 Windows Git SSH 长命令约 12 KB 时的引号截断。SSH 现统一使用短 bootstrap，经 stdin 顺序传递源码和 JSON；系统 OpenSSH 在非交互 Python 子进程中挂起，因此本次部署进程 PATH 前置已安装 Git `usr/bin`。工具补丁通过保留祖先关系的 bootstrap 提交快进到服务器，未在运行目录手改受管文件。

迁移前冻结新加坡主站/PM、北京域名/HTTP IP/HTTPS IP 的 Expo API，并临时阻断办公室直连 8001 入站；五个公网入口实测 503，两台后端线程栈均无 Expo 任务。四个原本运行的 writer（办公室两 NSSM、北京 systemd 后端、新加坡 PM2 物流进程）由迁移入口停止并复核后，只执行一次 `138_public_pool_rules → 139_expo_prompt_versions`。随后四服务全部恢复，维护配置按原文件摘要还原，临时防火墙规则撤销。历史 737 条试戴结果、377 条会话所有原字段摘要一致；新增历史字段全为 NULL，三个种子与冻结 JSON 完全一致，默认项、外键和索引验证通过。

运行 `.env` SHA-256 前后相同。迁移使用单独创建、限定办公室来源和 `commission_db` 的临时账号；完成后账号与凭据文件均已删除。没有对真实客户发起 AI 生图测试。公网两主站、PM、素材门户首页均 200，两主站健康检查为 `ok/database=connected`；新增版本接口匿名访问为 403，权限边界保留。办公室仓库干净；北京保留两份原有未跟踪 `.env.bak-*`，未复制或清理。

验证：最终 Windows 部署测试 48 passed、11 skipped；Linux 临时目录补跑 11 项静态语义及 2 项传输测试全部通过；提示词专项 97 passed，独立审查无剩余阻断。真实 MySQL 隔离 schema 上下行演练通过，两次临时 schema 均删除。准备阶段每台主站传输 741,927 字节，正式切换复用候选、传输为零。非敏感交付证据归档在主目录 `.deploy_state/migration139-delivery/`，服务器保留本次发布/迁移日志与配置回滚备份。

收尾再次以同一 SHA 执行 `--no-pull --prepare-only`（无 DBA 文件）退出 0，后端 `changed=false/schema_changed=false`，构建跳过，四个静态目标零变化/零传输。该检查不切换服务；当前发布器会把 `publish-current.json` 留为这次检查的 `preparing`，应结合 `noop-result.json` 的 0 退出码及 `noop.log` 最后 `Prepared and verified` 判断，而非误判正式发布未完成。

### 数据库 139 发布准备（2026-09-07，以下为发布前记录）

窗口修复后确认正式发布被迁移保护拦截：数据库为 `138_public_pool_rules`，候选新增 `139_expo_prompt_versions`，尚未执行 DDL 或停服务。现场重新核实了办公室两个 NSSM、北京后端和新加坡 PM2 物流写入者，PM2 控制能力从 138 任务中独立纳入本任务，并增加停止后复核。保留独立 DBA、命名锁和失败恢复边界；新增持久化原始 writer 状态、迁移链复核、跨重跑恢复保护及固定完整 SHA 的发布参数。

验证：部署测试 45 passed、11 skipped（Linux 文件系统语义），提示词配置专项 97 passed。使用新建的隔离 MySQL schema 实跑 139，三个种子、外键/索引及历史行保留通过；回退演练发现先删索引会被外键拒绝，已调整先删外键，第二次上下行演练全部通过。两次临时 schema 均已清理，未在共享业务库执行测试 DDL。独立审查的无 pending 绕过恢复日志及遗漏 PM2 writer 两项意见已修复并加回归。生产发布需先准备制品，再冻结新 Expo 提交、确认后台线程排空，最后通过统一入口迁移和切换。

### 发货检验型号、规格与发货备注（2026-09-07，合并交付，未部署）

亮哥已授权将任务分支 `codex/shipment-product-display` 合并到 `main` 并推送 GitHub `origin/main`，本轮不含部署。小程序明细首行改用 `okki_products.model` 深绿色 40rpx/800 显示，第二行 32rpx 显示 `size / color`，不再显示产品名称和 SKU；型号缺失显示“未维护型号”。扫码单头新增 `okki_outbound_records.remark`，底部输入明确标为“检验备注”，两种备注独立。PC 出库单打印增加发货备注并移除 SKU 列，验货单打印保持原样。

独立 agent 只读审查未发现可行动缺陷，重点检查 LEFT JOIN、invoice 桥、字段契约、备注分离和打印转义。首次本地交付时临时构建目录清理被策略拦截；此次授权集成后按根目录 AGENTS 清理本任务 worktree，验证材料先归档并校验。

后端按明细 `product_id` 左连 `okki_products.product_id`，保留原有 `outbound_invoice_id` 单头关联以及产品未匹配的明细数量、照片归属。无迁移。实库只读核对三张表列定义，并使用修改后的查询读取最新一单，返回 1 条明细与源表计数一致、型号非空、备注字段存在；未写业务数据。

验证：18 项 SQLite 后端测试、19 项小程序/打印 Node 测试通过；主站构建、增量约定检查、diff 空白检查通过（构建仍有既有大包/混合导入提示）。Chromium 核对 A4 打印五列、备注换行及无横向溢出；使用真实 WXML 片段/WXSS 的浏览器静态映射检查 320/390px 排版，型号深绿加粗、字号大于规格、无横向溢出。该静态检查不代表微信开发者工具或真机验收。验证材料归档位置为主目录 `tmp/shipment-display/`；Git 巡检使用 `--no-fetch` 本地快照，不处理其他任务分支。

### 内贸业务订单与生产订单分流（2026-09-07，合并交付，未部署）

任务分支 `codex/domestic-production-orders`，工作目录 `commission-system-codex-domestic-production`，基于 `50956fb6`。新增“生产订单下单”入口和独立 DP 编号，业务入口使用 DO 编号。生产单没有客户档案、销售类别/类型/渠道/要求发货、报价和发型字段；头套不选发型系列，发片保留工艺/尺寸和发长，仍可填颜色与通用图文备注。草稿、追加、改数量、终止等生命周期均不产生客户资金流水；生产单入库完成即已完工，不登记发货。列表、详情、小程序、流转卡和 Excel 已同步区分大类。

路线由订单大类、业务类别和产品类型固定匹配，独立于共享 SKU 的产品档案路线。140 迁移从“头套网帽（递针）”“发片网底（递针）”各克隆生产和普单两条路线：生产为确认下单至入库，普单为毛坯出库至发货完成，特单沿用原始完整路线。原有订单及报工快照不重建，业务单保存后不能改普货/特单类别。真实库只读预检得到生产各 18 步/4 条条件规则、普单各 5 步/0 条规则；MySQL DDL 编译验证通过。迁移未在共享库执行。

验证：内贸后端全量 `645 passed, 1 skipped`；随后新增 MySQL DDL 编译测试，所在文件 `18 passed`（共新增 18 项测试）。主站内贸 `44 passed`，小程序相关 `10 passed`；主站生产构建通过（既有大包警告）。真实前端 + 隔离 API 浏览器验证头套/发片生产单提交、无客户/报价请求、列表大类筛选、390px 手机无横向溢出及业务普单/特单切换，页面运行错误为 0；不代表真实后端端到端或小程序真机验收。约定检查、diff 空白检查和独立对抗性审查通过；Alembic 只有 `140_domestic_order_kinds` 一个 head。Git 巡检使用 `--no-fetch` 本地快照，其他任务的未提交修改、未推送分支和 stash 均保留。验证日志、脚本与截图保留在本任务 `tmp/`。

发布需走统一部署入口处理 140 迁移，并协调全部应用切换：旧应用不认识生产单的 NULL 客户，切换完成前不开放该入口；不得在开发机直接升级共享库。API、数据库、模块说明和领域记忆已同步。亮哥已授权将实现 `36eda235` 合并至 `main` 并推送 GitHub `origin/main`，本轮不含生产部署。集成仅与部署入口修复的交接记录发生冲突，两个记录均保留；业务代码与此前验证版本一致。验证材料归档到主目录 `tmp/domestic-production-orders/`。

### WhatsApp Cloud 路由（2026-09-07，1.2.6）

`codex/whatsapp-cloud-validation` 基于 `204cd788` 准备并实测 `1.2.6-cloud-test`，亮哥授权合并推送后去掉测试显示标识，作为 `1.2.6` 集成：扩展 API 与唯一 host permission 改为 `leshine.cloud`，稳定扩展 ID、设备存储、work 配对确认页校验及 WhatsApp 页面行为不变。北京后端的 `SHORT_LINK_BASE_URL=https://leshine.work` 已只读核实。测试流程见 `extensions/whatsapp-translation/CLOUD-VALIDATION.md`。本次范围仅源码合并推送，不包含后端部署、下载站发布或替换已安装插件。

验证：原版基线 152 tests passed；cloud URL 断言在改代码前出现 2 项预期失败，改后及去掉测试标识后均为 152 tests passed，TypeScript/Vite 构建与打包通过，约定检查通过。改前后 `content.js` SHA-256 均为 `7bab776db7d0d3897ee311c5a7accfc3dab746f6b92c05563e0176e7ee6790f8`。测试 ZIP SHA-256 `fac1d245755016396ac9099a0927475c4694ba84ec762d75779361e47ae68c2f`，27965 bytes；1.2.6 去标识 ZIP SHA-256 `789738ce38077ee6c459cfac8443dfcad30e6fe88dad33d326cad3b5b73b220f`，27930 bytes。npm ci 使用现有锁文件，报告 5 项存量依赖审计告警，本次未升级依赖。

用户于 2026-09-07 自行加载测试包，15:30 合成文本实测报告约 3 秒返回。后台只读核对：设备版本 1.2.6 且有效；北京 Nginx 的 session/translate 返回 200；最新对应发译 AI 日志 5554 成功，模型耗时 1692 ms。已验证一次正常设备认证下的 cloud 实际请求链路；约 3 秒来自用户观察，未做浏览器精确打点或独立译文质量检查。浏览器 URL 安全策略禁止扩展管理页自动化，因此加载由用户完成，没有绕过限制或导出 token。未改线上后端或系统代理。

补测：从本交接新记录找到并验证 `office-prod` 后，在办公室与北京服务器后端目录各运行 3 次同配置、同请求摘要的合成模型调用，全部成功。办公室中位 3.475 秒，北京中位 1.221 秒。仅远程独立诊断进程，不是运行中 HTTP 服务或已配对插件的端到端数据；未写生产数据库。

### 部署入口闪退（2026-09-07，已合并推送，办公室入口已更新）

`codex/deploy-launcher-fix` 修复 `deploy/deploy.bat` 在发布程序结束后直接退出、右键管理员运行看不到错误的问题。现在保留窗口直到按键；无人值守通过 `DEPLOY_NO_PAUSE=1` 跳过等待，原退出码与参数传递保持不变。Python 发布器已按脚本位置定位仓库，隔离测试从 System32 启动验证路径正确，不额外修改发布流程。

验证：部署测试 27 passed、11 skipped（Linux 文件系统语义），其中 4 项新增原生 Windows cmd 回归覆盖成功/失败、真实等待按键、无人值守退出、带空格参数及括号路径；旧入口在两项交互用例失败。仅使用临时目录和无副作用的替代发布器，未连接生产服务或数据库。服务器导致提前结束的实际错误尚未取得；旧入口可从已打开的管理员命令提示符运行以保留输出，不直接编辑服务器脚本，避免干净工作区检查阻断。

亮哥授权合并、推送并更新服务器。修复 `5760c2fe` 已合入 `main` 并推送 GitHub。办公室通过本机 SSH 别名 `office-prod` 连接（主机 `LYS-ACCIOWORK`），服务仓库为 `D:\commission-system`、HTTP 端口 8001；原内网地址的 SSH/WinRM 超时不代表该隧道不可用。

生产仓库原在 `639f3f78`，为仅更新入口，基于该版本制作只含 4 行 BAT 修复的 `232b4d67`，通过 `643b9014` 将其祖先关系合入 `main` 并推送后，生产仓库快进到该补丁。只改 `deploy/deploy.bat`，工作区干净；后续正常发布仍能快进到 `origin/main`。业务代码、数据库和服务进程未切换，不代表最新业务版本已发布。

生产实测：真实入口的 `--help` 与无效参数分别返回 0/2，交互模式确实等到按键，无人值守直接返回，四项均通过；脚本 SHA-256 与本地一致（`229a77f28b1a3e9b5cf1c303fb1561620657c4ca1ddbf9fb18d9c8eafd9bed3d`）。`CommissionSystem`、`WhatsAppConnector` 均 Running，`/health` 为 `ok/database=connected`。生产验证脚本保存在 `.deploy_state/launcher-fix-20260907/`，仅测试参数解析和窗口停留，未发起真实业务发布。若后续默认发布报错，窗口现在会保留其实际错误。

### OpenClaw 0907-1 重复提交 500 修复（2026-09-07，待后端部署）

本机已安装 `~/.openclaw-ark-sales/runtime/search-contract-79b4d1ef`，配置与双工作区 Skill 已同步，私有备份位于同 profile 的 `backups/search-contract-79b4d1ef`。Gateway 重启、RPC 读探针、MCP doctor 通过，cron 和 triggers 均 enabled。修复见 PR #1；办公室后端仍待发布。

用户日志确认任务 #5 首批 10 条已经提交成功但响应超时，后续换批次重复提交触发 `uq_ark_customer_external_identities_primary_identity_slot`。根因为弱官网身份按 source_record_id 保留证据，但每条新证据均请求 is_primary。现在在主体行锁内按主体+身份类型（跨 namespace）保留唯一活动主身份，新来源保存为非主证据；旧身份恢复活动时也不能抢占当前主槽。联系人路径补行锁。无迁移，不删除或改写线上历史记录。

客户端候选提交对 transport timeout/network error 自动原样重试一次，发送前固定完整 JSON 快照；明确 HTTP 错误不重试，其他写操作不重试。仍无回执时明确返回结果未确认，禁止换 key/改分/拆批。Skill 与说明同步。任务 #5 已留存 10 位客户、10 条结果、10 个研究任务；尚未重新入队，也未宣称目标 20 条完成。

验证：SQLite 补等效 MySQL 活动主身份唯一约束，修复前三项回归复现唯一冲突；修复后相关后端 255 通过、2 跳过（含真实 MySQL 并发测试），Node 54 通过，MCP→实际 CandidateBatch 的 7+20 条离线契约通过；两轮独立审查无阻断。真实 MySQL 并发尚未实测。代码已同步 origin/main；后端必须通过办公室统一部署入口发布，本轮没有办公室部署通道，没有推送 main。

### 展会生图提示词配置与版本（2026-09-07，合并交付，未部署）

- 实现提交 `d46d86ba`，亮哥已授权合并至 `main` 并推送 GitHub `origin/main`。已实现管理页、动态版本选择、原子快照、版本修订冲突保护与管理员历史快照查看；本轮不含生产发布。
- 139 迁移新增版本表及结果快照。真实/柔光/美颜完整迁移，78 个历史生成组合文本哈希一致。生产尚未迁移或发布；线上仍为此前回滚版本。
- 验证：最终直接运行全部 test_expo_*.py，425 项通过（含版本专项 97 项）；前端动态版本、kiosk 隔离与导航回归 30 项通过。前端生产构建和增量约定检查通过。验证材料归档于主目录 `tmp/expo-prompt-config/`。管理页浏览器验证创建、未保存预览、保存、生效列表及 390px 布局，X/Escape/遮罩取消放弃保留草稿，保存中阻止关闭。独立审查发现的关闭保护与历史快照入口已处理。
- 发布前必须停止接收新生成并排空旧线程，由指定部署入口统一执行 schema 139，再同步前后端并刷新设备。只有 SQLite 迁移与业务实测，MySQL 锁并发未实测。生产发布需另有明确授权。
### OpenClaw 获客候选提交 422 修复（2026-09-07）

`codex/openclaw-search-contract-20260907` 修复主研究代理候选提交契约：MCP 保留 `name` 输入并转换成后端 `company_name`；自动生成稳定来源页 SHA-256 ID 和官网 host 上下文 ID（超长 host 改用 SHA-256）；新增必填、有来源理由的 `score/score_reasons`，不设置默认高分。422 返回字段路径和校验类型，不回显原始输入、错误上下文或租约。工具列表仅支持 claimable；空列表不再被描述成失败/完成状态查询。Skill/API 文档同步。

验证：51 项 Node 测试通过；7 条和 20 条离线样本经过 MCP → ArkClient → 仓库真实 Pydantic `CandidateBatch` 校验，共 27 条通过，无网络或数据库写入；约定检查和 diff 检查通过。独立审查发现的超长域名边界已修复，复审无阻断项。

本机已安装独立运行目录 `~/.openclaw-ark-sales/runtime/search-contract-7df86d13`，MCP 配置指向此目录，避免依赖临时 worktree。主代理与默认工作区的获客 Skill 已同步；旧配置和 Skill 备份在 `~/.openclaw-ark-sales/backups/search-contract-7df86d13`（不入库）。Gateway 重启成功，RPC 与 MCP doctor 通过，cron/触发器启用；实际 MCP 工具 schema 已确认必填 score/score_reasons，方舟只读队列查询成功。没有改后端、数据库或 main；代码已备份到 feature 分支。

任务 #3「0903-2」与 #4「0907」之前已终结为 failed，本轮未重新入队；方舟网页登录页没有可用登录会话，尚未做线上成功入库验收。登录后通过正常获客页面重新入队，由恢复的 heartbeat 按最早任务优先执行。不要把 claimable 空队列或模型 HTTP 200 当作业务完成证据。

### 展会合成提示词回滚（2026-09-07）

亮哥反馈 `639f3f78` 版本人物失真，且未达到激发购买意向的效果，明确要求回滚。任务 `codex/expo-rollback` 撤销该版本的提示词、对应测试、版本说明和模块规则，恢复至 `a28bbf4e` 的展会逻辑：真实/柔光保留原皮肤处理，美颜使用此前规则；移除本次购买意向子句。后续试验需要先验证本人相似度与真实出图效果，不能以提示词字符串测试通过代替效果验收。

回滚提交 `917280c0` 已合入 `main` 并推送 GitHub，2026-09-07 13:13 北京线上通过 `deploy/deploy.bat --cloud-only --no-pull` 完成切换。服务 active，`/health` 返回 `status=ok/database=connected`；线上提示词与前端版本说明均与 `a28bbf4e` 一致，公开 HTTPS 首页摘要及 kiosk 旧版说明验证通过。数据库仍为 `138_public_pool_rules`，无迁移，不修改上传照片或历史生成结果。

验证：92 项后端测试、7 项前端接线测试、约定检查通过，统一发布入口的主站/PM 构建及扩展 152 项测试通过。新加坡主站按部署规则延后，办公室未纳入本次北京回滚；PM 和客户素材门户制品未变。本次没有重新生成收费图片。部署日志、状态与制品校验证据归档于主目录 `tmp/expo-rollback-release/`；主目录原有六处未提交修改完整保留。此后的交付记录提交不改变线上运行代码。
### WhatsApp 话术助手设计提案（2026-09-07，未实现）

亮哥要求比较方舟直连知识库与已有 Accio Work Agent 服务化，并补充现有 Agent 仅 SOUL、无 Skill、知识来自方舟。本轮推荐扩展统一调用方舟轻量销售回复 Agent，复用知识 ACL、已发布版本与 AI facade，不将 Accio 桌面桥接作为首版依赖。设计与来源证据见 [功能设计](requirements/2026-09-07-whatsapp-reply-assistant-design.md)，角色规则见 [SOUL 草案](requirements/2026-09-07-whatsapp-reply-agent-soul.md)。

已只读核验 4 库 61 篇已发布知识的规模、销售方法和模板冲突，明确双方有限上下文、语言判定、知识依据/中文释义、人工填入、日志隐私与权限边界；未安装 Work CLI、未调用个人 Accio Agent、未新增收费模型测试。仅本地设计文档，未创建线上 Agent、未改代码或生产配置，也未提交/推送/部署。后续先做来源用途配置与合成质量验证，再实现最小闭环；不能把该设计记录当成功能已上线。

独立设计审查的两项意见已处理：可外发用途绑定发布修订与章节内容；单次 POST 只展示本地可观察的读取/生成状态。文档链接、编码、diff 与约定检查通过；设计 worktree 保留未提交文档，Git 巡检未操作其他分支或主目录改动。

后续按亮哥要求分析本地「谈单助手0826」：仅阅读 SKILL 与分析、知识使用、报告业务契约三份参考，排除阿里询盘提取及所有运行流程。已吸收当前片段复盘、阶段与活跃度分离、买方行动/承诺信号、策略适用条件、下一步完成信号和反馈分支，补入功能设计 §4.3、SOUL 与合成验收场景。保留默认一条回复、两次模型调用与有限上下文；不照搬三篇话术/完整报告、知识后置冻结话术或“卖方说过即有效”的规则。未改原 Skill、业务代码、权限或线上配置；未执行抓取、真实客户分析、模型调用或发布。

### WhatsApp v1.2.5 集成与翻译配置（2026-09-07）

亮哥授权合并本任务修复至 `main`、推送 GitHub `origin/main`，并关闭翻译插件 DeepSeek 的深度思考；不包含代码部署或其他业务模型调整。交付包含 v1.2.4 本地化时间解析、v1.2.5 英文界面识别及本页术语库记录，下方旧版「未合并/推送」描述保留为当时验证记录。

共享配置已于北京时间 11:20 更新：`whatsapp_text_translation`（来信）与 `whatsapp_outgoing_translation`（发送前）两个 `deepseek-v4-flash` 预设均添加 `thinking: {type: disabled}`。模型、提示词、原有温度/输出上限及回译功能不变；其他业务预设未修改。按 DeepSeek 官方 thinking mode 文档设置顶层参数，现有 AI facade 直接将预设参数合入请求体；逐请求读取配置，无需部署或重装扩展即可使用新参数。已在加行锁事务中备份和更新，独立连接回读验证，其他预设字段哈希一致。本轮未发起收费模型测试。

验证：重新安装锁文件依赖后，152 项扩展单元测试、6 项真实浏览器编辑交互测试、类型检查和构建通过。此前 12 次合成 A/B 测试的五组成功配对耗时中位降幅为 69.4%，但德语长句仍观察到产品类型偏差；此结果不是本次配置修改后的速度或质量保证，专业长句仍应结合回译核对。新中英术语库已启用，不等于德语术语覆盖。依赖审计仍提示 5 项既有漏洞，本轮未改锁文件依赖版本。

回滚备份、导入脚本、测试报告与安装包归档到主目录 `tmp/whatsapp-translation-20260907-archive/`；安装包另保留在主目录 `extensions/whatsapp-translation/release/`，便于任务 worktree 清理后继续使用。配置恢复须按备份中的两项预设/原参数有范围地执行，不回滚整个数据库；产品词库备份同样只覆盖英语词条。本次未发布后端代码，扩展 v1.2.5 的页面识别修复仍需用户安装新版 ZIP 并刷新 WhatsApp。

### WhatsApp 英文界面识别 v1.2.5（2026-09-07，本地修复包，未合并/推送）

Mac 同事的英文网页中私聊按钮标识为 `Profile details`，原选择器只接受中文，导致整个会话被判为 unknown，输入框工具栏和自动翻译同时关闭。现在在相同会话头部、button 角色和非空标题约束下接受中英文两种精确标识；不按通用 header 或模糊文本识别私聊。群聊、未知标签、缺角色/标题、头部外的同名按钮仍被排除。保留 v1.2.4 本地化时间修复，不涉及后端或权限变更。

验证：旧版两项英文行为测试失败，修复后 152 项测试、类型检查、构建打包通过。未修改英文标签的 Mac 存档内存重放确认 direct、工具栏挂载成功；存档缺配套样式，对明确 tail-in 行仅补齐排列样式后识别出 3 条纯文字来信。真实聊天内容未保存进仓库，未运行存档脚本或访问生产服务；真实 Mac 安装验收尚未完成。

安装包：`extensions/whatsapp-translation/release/whatsapp-translation-1.2.5.zip`，SHA-256 `3c6b5d52378d2f0e8425fe77462b9a4013ac54e59fbac316493c2d103b4d8095`。在当前任务 worktree 保留；更新扩展后刷新 WhatsApp，无需切换界面语言，也无需部署后端。旧 v1.2.4 安装包保留。

### WhatsApp 本地化时间识别 v1.2.4（2026-09-07，本地修复包，未合并/推送）

同事电脑能翻译发送框、来信没有译文。用户提供的页面存档验证了本地化时间与隐藏占位相等，但旧解析器限定两位小时 24 小时格式，导致纯文字消息被未知结构保护拦截。现在只接受与唯一、非空的已识别时间栏完全相同的隐藏 SPAN 占位；仍要求其位于 metadata 内且不在正文内，不放宽媒体、未知节点、群聊或发信边界。不改变账号权限或开关，不改后端。

验证：142 项扩展测试、构建打包与约定检查通过。合成回归覆盖单数字小时、中文时段、AM/PM、非拉丁数字及未知/媒体/方向保护，并确认打开已有聊天时自动发起来信翻译；存档没有配套 CSS，仅在明确 tail-in 的来信行补齐排列样式进行内存隔离重放，旧版识别 0 条、新版 5 条，图片仍排除。原始存档/聊天未复制进仓库或测试。实际同事电脑安装后验收尚未完成。

交付物：`extensions/whatsapp-translation/release/whatsapp-translation-1.2.4.zip`，SHA-256 `a3fbbd5f2e9d7bbd29feacf33312df4f999077f35032eb6d93bdc92040724b75`。在任务 worktree `commission-system-codex-whatsapp-localized-time` 保留，需更新扩展并刷新 WhatsApp 页面；本次修复无需后端部署。主目录已有未提交文档与规则修改均未触碰。
### 生产数据库迁移完成（2026-09-07，仅数据库）

亮哥授权执行迁移。共享 `commission_db` 已从 `137_domestic_labor_fee` 升至 `138_public_pool_rules`；新增 `ark_public_pool_rule_configs` 六个字段、主键、外键和单例 CHECK 均实查通过，当前 0 行。运行 `.env` 摘要未变。办公室保持 `59b2ff1f`，北京保持 `05e3da57`，本次没有发布应用代码或静态资源。

按现场清单暂停并恢复了办公室 `CommissionSystem` / `WhatsAppConnector`、北京 `ark-backend`、新加坡 PM2 `shipment-tracking-mcp`；四项恢复运行，两个后端 `/health` 均为 `ok` / `database=connected`。唯一数据库事件只更新物流表且无关联触发器，经过审查不影响新增表，保留启用并核验定义摘要未变。未停止整个 PM2，避免其旧保存清单复活已退役任务。

迁移通过统一 `deploy.bat --migrate-only` 入口、固定候选 `eaa914fa26cbd9025a81ced74192ddf8e4ab79f5` 执行。生产制品目录 `.deploy_state/migration138-tools-a0dda8a8064c/` 含计划及逐文件 SHA-256 清单；状态为 `.deploy_state/migration-138-current.json` 的 `succeeded`，结构与清理记录位于 `.deploy_state/migration138-20260907/`。临时 DBA 只获该库迁移权限，验收后账号与凭据文件均已删除。

本地部署工具补充了仅迁移入口、PM2 单进程控制和失败重跑保护，保留在 `codex/migration-138` 工作区供交付，不自动合并或推送。已有部署测试 `31 passed, 11 skipped`，新增 PM2 隔离测试 `4 passed`，约定检查通过；独立复核无剩余阻塞。生产预检曾因 Windows OpenSSH 的 Python 子进程卡顿停止，未执行 DDL；改用同机 Git SSH 后预检与正式执行均通过。

### 平台前后端、服务与 UI 审查（2026-09-06，已合入 main，未部署）

代码提交 `cc54bfbd` 和集成记录 `eaa914fa` 已快进合入 `main` 并推送 GitHub `origin/main`，远端提交已核验为 `eaa914fa`；未执行生产部署。合并结果与已验证代码一致，按原基点 `7cf596fb` 执行约定检查通过；主目录三份已有规则修改经 SHA-256 核验完整保留。579 份验证材料已复制并逐文件核验，保留在主目录 `tmp/platform-audit/`；本任务 `codex/platform-audit` 分支及临时 worktree 已清理。完整发现、改动和限制见 [平台审查报告](requirements/2026-09-06-platform-audit.md)，目录和页面明细见 [覆盖清单](requirements/2026-09-06-platform-audit-coverage.md)。

后续工作区检查：6 个 worktree 与 4 个本地分支均无尚未合入 `main` / `origin/main` 的提交，无 stash；其他旧 worktree 保留。本轮文档整理保留原有三份规则修改，修正 DoD 维护来源、部署入口、测试命令及交付状态，留未提交差异供审阅。下方旧记录中的约定检查阻断已由本轮平台修复解决，历史验证结果保留。

已修复工艺路线 DELETE 缺失及内外贸引用保护，列表 20 条 SELECT 从 42 次降为 4 次；中央请求加载槽/取消/序列化异常、运维页缓存轮询/加载状态、WhatsApp 缺密钥匿名放行、OpenClaw 正文超时、SSH 连接重试。前端统一登记 client，删除 19 个无引用旧洞见 API；共享按钮、加载层、手机导航、主站/PM 弹窗与多页手机布局完成调整。样式按已有模式放在应用级和领域 CSS，债务门禁没有扩额。

验证：后端全量 **4577 passed, 4 skipped**；主站 **551/551**；发布 **23 passed, 11 skipped**（Linux 文件系统语义）；OpenClaw **47 passed, 1 skipped**；WhatsApp **2/2**；主站与 PM 构建通过。116 主站路由双视口、58 独立入口/PM 视口用例已到访；成功态表单/工艺删除/短屏页尾和嵌套焦点单独验证。全局约定检查通过，Git 巡检使用 `--no-fetch` 本地快照。证据保留 `tmp/platform-audit/`。

不等于生产验收：真实 MySQL 并发、大数据量/真实角色业务流、外部 AI/OCR/OKKI/钉钉/WhatsApp、小程序真机及实际部署未验。上线本轮代码前需核对 Connector 非空密钥及监听地址；默认仅 `127.0.0.1`。旧未注册 sales_automation 页面仍有 18 个 API 扫描候选、主站 vendor/ECharts 大包及历史颜色技术债保留在报告中，现役客户经营走 customer-hub。

### 登录页航行主题优化（2026-09-06，已合入 main，未部署）

代码提交 `2e2e8516`。本次交付范围为合入 `main` 并推送 `origin/main`，未执行生产部署。登录页采用真实海岸线地图、金色点阵和经纬线；标题位于地图中部，以轻微浮动、左向渐变粒子尾迹形成航行意象。青岛主节点放大，并增加暖金光晕、呼吸和双层扩散环。黑金登录卡使用静态渐变；入场 280ms，手机及减少动态模式保留静态地图。地图静态层仅在缩放时重绘，动画按时间运行且后台暂停，卸载清理事件和帧请求。自然地理数据来源与处理记录在 `DESIGN.md`。

文案按当前功能归纳：定位“AI 驱动的企业协同平台”；总结“贯通业务 · 沉淀知识 · 智能协同”；能力“客户经营 · 产销履约 · 业绩核算 · 创意设计 · 知识洞察”。修正密码按钮白底、选项间距，勾选框及密码显隐支持键盘操作和可访问标签。认证接口与登录后跳转未改。

合并候选基于客户经营功能合入后的 `a7d0f8a2` 验证：地图 6 项与备案 3 项回归全部通过，前端构建通过（既有大包/混合导入警告），增量规则扫描 0 项违规。全局约定检查仍被未修改的 `DomesticOrders.vue` 行数债务基线失配阻断，主分支可复现，不扩大本次基线。浏览器已检查桌面、平板、手机和短屏：标题/地图/表单无横向溢出，备案不遮挡表单；空提交反馈、密码显隐与勾选交互通过。未启动后端，真实账号登录未验；开发预览 refresh 请求的 500 源于本地后端不可用。主目录已有的三份规则文档未提交改动保持不变。

# 莱莎方舟平台 项目交接清单

### 客户经营集成完成（2026-09-06，待部署）

亮哥已授权合并推送。main 已快进集成经营流程 `a887df05`、公海规则配置 `ba663917`、UI 修复 `1693d2a8`；本轮同步目标为 GitHub `origin/main`。合并无冲突，主目录三份既有规范文件的未提交内容已通过 SHA256 核对保留。业务代码与此前验收版本完全一致，验证证据见下方记录；未执行生产迁移或部署。以下各阶段「待合并/未推送」文字为当时的交付记录，当前状态以本节为准。任务分支完成同步后清理；必要本地验收材料保存在主目录 `tmp/customer-operations-archive/`。

### WhatsApp 产品术语库已更新（2026-09-07）

亮哥明确要求将已整理的产品术语对照表写入翻译插件。已更新共享库 `sys_dict` 中的 `whatsapp_glossary_en`，80 条中英对照拆为 107 条独立匹配词条：新增 102 条、更新 5 条，英语词库共 131 条启用项。更新项为色号、顺发、贴片、接发、长度，纠正 `贴片 → clip-in` 为 `贴片 → tape tab`；其他既有商务词条完整保留。仅术语配置变更，无代码发布、数据库结构变更或模型参数调整。

入库值采用单一明确译名，部位组合分别映射，中文别名分别入库；资料中的等级比例、工艺温度、寿命等不作为词条内容。来源版本与使用边界保存在字典备注供维护人员查看；现有匹配接口仅向模型注入 code/label，不应声称备注中的约束已被模型强制执行。中译英和英语来信可使用本次词库，未为德语等其他语言编造对照。

验证：导入前隔离 SQLite 的 10 项中英匹配检查通过；事务内重复核验并在提交后独立连接回读所有目标值，确认非目标词条未改动。无额外收费模型调用，不将匹配检查等同于实机译文质量验收。服务端逐请求读取术语，不需重装插件；同文本缓存最长约 5 分钟。可复现脚本及本次修改前后快照归档在主目录 `tmp/whatsapp-translation-20260907-archive/`，用于核验和有范围的恢复，不应直接重复执行写入。

### 客户经营 UI 统一检查完成（2026-09-06，待合并部署）

本轮基于 `ba663917`，继续使用 `codex/customer-operations-phase1`。已统一五页及其弹窗/抽屉字体与按钮，修复顶部装饰层遮挡按钮、固定操作列透明叠字与宽度不足、长表单保存区超出视口；研究复核操作固定到底部。手机取消右固定列并扩大按钮触控尺寸，长客户名与表格容器同步规范。样式仅限客户经营域，无业务/API/数据变更。

真实 Vue + 本地合成 API 的 UI 验证覆盖 1280×720、390×844 及 768×600；长配置、机会证据、待办、客户详情、公海规则与资格审核操作区均在屏幕内。44 项相关前端测试通过，构建 3063 模块通过；独立审查发现并关闭抽屉层级问题，最终复核无阻断项。完整约定检查仍由 DomesticOrders.vue 既有基线失配阻挡，本次增量检查 `[]`；git_sweep --no-fetch 已执行。详见 [UI 检查记录](requirements/2026-09-06-customer-hub-ui-review.md)。未合并、push 或部署。


### 公海规则：可视化配置与JSON双向编辑完成（2026-09-06，待合并部署）

继续使用 `codex/customer-operations-phase1` / `D:/MyProgram/commission-system-codex-customer-operations`，本轮基于客户经营一期 `a887df05`。背调中心新增「公海筛选规则与批次」抽屉：成交三路OR、13国家、IG优先/FB/电话、Genius Weft/Flat Tip/贴发、180天无下单与30天无跟进、配额均可在表单编辑；高级JSON双向同步，预览分原因统计，保存CAS版本后创建批次。调度使用已保存规则，历史批次保持快照。迁移138新增单例配置表，无客户数据回填；生产尚未执行迁移、未合并/push/部署。

验证：13个相关后端模块204通过（17条既有警告），最后规则专项28通过；前端52通过（默认时区及America/Los_Angeles），构建3062模块通过（既有分包警告）。隔离内存SQLite+真实Vue页面验证4客户→2入选、日期缺失与近期订单分别排除、JSON错误保留/有效回填、保存/刷新恢复、重复创建只生成2任务；最终事务修复后再次保存与建批次成功。桌面与390×844手机布局、底部配额操作通过，页面控制台无error。迁移独立SQLite上下行与MySQL离线DDL通过。日志保留在 `tmp/public-pool-rules/`。

独立审查发现并修复：归一化为空的产品词、筛选后被领取窗口、转属任务被错误复用、已flush修改被错误回滚。执行入口现在拒绝既有事务，编排明确结束prepare读视图，v2根客户按ID加锁至提交；预览无写锁。MySQL真实锁等待/大公海吞吐尚未实测，勿拿SQLite结果替代引擎验证。全量约定检查仍由未改动的DomesticOrders.vue既有UI基线失配拦截，本轮增量检查无违规；git_sweep --no-fetch已执行，仅本地快照。


### 客户经营第一期：本地实现与隔离验收完成（2026-09-06）

分支 `codex/customer-operations-phase1`，worktree `D:/MyProgram/commission-system-codex-customer-operations`，基于 `59b2ff1f`。今日工作台、独立开发资格待审、中文研究摘要及来源证据、客户详情就地处理、机会证据选择、带日期且同负责人的后续待办已完成。复用现有表，无迁移；不包含 OpenClaw、邮件发送或完整策略编辑器。API 和模块说明已同步，完整范围及验收证据见 [客户经营第一期](requirements/2026-09-05-customer-operations-phase1.md)。

验证：后端相关回归 178 通过，前端及导航 42 通过（包括非东八区环境），生产构建通过；隔离 Chrome 完成工作台→详情→后续行动、资格通过/暂缓、机会证据推进和桌面/390 像素窄屏、空态/错误恢复。独立审查有效发现已修复。约定检查仅被未改动的 `DomesticOrders.vue` 既有 UI 基线失配拦截；本任务增量规则无违规。Git 巡检已执行 `--no-fetch`，未据此修改他人分支。

代码尚未合并、push 或部署，生产行为未变。资格决定已设置请求级 MySQL SERIALIZABLE 事务和死锁重试提示；当前只完成入口单元测试与隔离 SQLite 跨会话验证，未实测 MySQL 锁竞争/吞吐。后续集成时保留这一区别，并在独立 MySQL 环境补引擎并发验证；不要使用生产业务库跑回归测试。

### 部署调整：云端部分已上线，COS 文件迁移暂缓（2026-09-05）

北京应用发布为 `05e3da57`，共享库 `137_domestic_labor_fee`，本次无 DDL。北京主站和客户素材门户完成增量发布；新加坡 PM 与制品一致并接入受管目录。重复发布已验证构建跳过、静态传输 0 字节、北京后端不重启。hair.cloud、两主域、media.cloud 与 relay.work 的证书已修复并接入自动续期；素材跨云代理最终启用证书校验，独立云服务状态正常。

统一入口实现候选准备、一次数据库协调、NSSM 切换/恢复、SHA-256 增量传输、真实 HTTPS 摘要验证与阶段记录。新加坡新版主站因依赖办公室 API 暂缓切换。办公室管理地址待提供；内网 DNS、直连北京隧道、新 PM/video DNS 及全部独立服务源码纳管尚未完成。当前浏览器 DNS 控制反复超时，两个历史 hair 源码路径也未找到。详细已完成/阻断和继续顺序见 [实施记录](requirements/2026-09-05-deployment-adjustment-implementation.md)，命令见 [部署说明](../deploy/README.md)。不能把本次 cloud-only 成功报告为全平台部署完成。


### 内贸客户独立操作权限与公私海标签页（2026-09-05，待部署）

新增 `domestic_customer:admin`，角色权限矩阵「内贸客户管理 → 管理」显示「管理员可以显示所有客户的操作按钮」。该权限允许操作其他销售名下及公海客户，仍须具备原有编辑/充值/删除动作权限；普通 admin 不自动补授，super_admin 沿用全权限。前后端同步检查，资金流水保留实际操作者，重复请求不重复入账。私海/公海改为列表顶部标签页，默认私海，切换保留搜索和地区条件并重置分页。

验证：内贸客户/余额/会员回归 407 passed、1 skipped；前端权限和列表测试 10 passed；前端 build 通过；真实 Edge 浏览器使用模拟 API 验证两种授权状态下的标签切换、行按钮和编辑弹窗，无页面 JS 错误；独立对抗审查无阻断项。规范脚本被未修改的 `DomesticOrders.vue` 旧行数基线错误阻挡（baseline=46、actual=91），干净主目录同样复现；单独执行增量检查结果为空。

部署时按项目命令重启后端以登记新权限，再到角色管理为需要跨归属操作的角色勾选该权限，并刷新登录权限。未推送、未部署、未修改线上角色配置。

### WhatsApp 翻译超时调整 v1.2.3（2026-09-05，待部署及安装）

按用户要求将模型超时默认值从 15 秒改为 40 秒，`.env.example` 同步为 `WHATSAPP_TRANSLATION_AI_TIMEOUT_SECONDS=40`。翻译网络请求总预算（含一次瞬时连接重试）为 45 秒，页面桥接等待 50 秒；会话/配对请求仍为 20 秒。重复请求等候原任务的预算随模型配置增加 5 秒，避免模型未完成就提前返回不可用。没有切换模型、撤销设备授权或改变单条消息按钮。

翻译请求等待期间按 Chrome 官方长操作模式每 25 秒调用一次 `runtime.getPlatformInfo`，请求成功/失败/超时均在 finally 清理，避免 MV3 后台在长等待期间休眠；不新增权限或持久化数据。40 秒是模型网络阶段超时，不承诺严格端到端耗时。

生效需要部署后端并安装扩展 1.2.3；如果生产 `.env` 显式设置旧的 `WHATSAPP_TRANSLATION_AI_TIMEOUT_SECONDS`，须改为 40 后使用项目部署命令重启。此条记录不代表已推送、部署或线上验收。

验证：翻译后端 79 项、扩展单测 122 项、真实 Chromium 输入框回归 6 项通过；构建、打包及独立审查通过。41 秒响应和 45/50 秒超时边界由合成请求与假时钟覆盖，真实安装扩展的超 30 秒线上响应待验收。全仓规范检查仍被内贸 `DomesticOrders.vue` 既有 baseline 陈旧告警阻挡，干净 main 同样复现，未修改该文件。

### WhatsApp 实时翻译 v1.2.2（2026-09-05，修复包完成，待重载验收）

用户反馈安装 `1.2.1` 后鼠标替换仍失败。实页核对安装版本与内容脚本哈希一致；实际扩展 Alt+T 成功、鼠标失败。根因是失焦后 WhatsApp 恢复旧光标，与扩展全文选区竞争。`1.2.2` 对工具栏主鼠标按钮保留输入框焦点；输入框原先失焦时先等待光标恢复，再设置全文选区；写入前复核选区、焦点、原稿、聊天与 generation，避免错误位置写入。语言下拉框仍可正常获得焦点。

入站同时修复中性 DIV/SPAN、气泡装饰、正文 emoji、空布局与隐藏时间占位的识别；隐藏时间必须匹配同条消息已识别的可见时间，不进入正文。媒体、未知文本、未知标记及群聊继续拒绝。启动主动首扫，不再等下一次 DOM 变化。真实页面只读调用新版解析器识别 `3/3` 条消息，未存储原始聊天或页面结构。

验证：重新 `npm ci` 后类型检查、构建、119/119 单元测试、6/6 独立 Chromium + 真实 Lexical 浏览器测试及确定性打包通过，独立对抗审查无阻断项。浏览器测试覆盖 closed shadow / isolated world 的鼠标、快捷键、失焦起点、恢复后继续输入与语言菜单聚焦；默认 Lexical 本来就能接受旧写入序列，确定的红绿回归是鼠标保焦，不将模拟等同 WhatsApp 完整验收。实页临时保焦后实际扩展鼠标替换/恢复通过；新版编译 adapter 在实页失焦起点写入/恢复均通过且原稿保持。诊断监听已清理，未发送消息。全局约定检查仍仅被未改动的 `DomesticOrders.vue` 既有行数基线失配拦截，干净 main 同样失败。

发布包：`whatsapp-translation-1.2.2.zip`，27,876 字节，SHA-256 `281f6f31301619a0ed09e9f108370323ca41a341436f2233dcabb4334beeef00`，扩展 ID 不变。用户表示生产后端已更新；本轮未改后端，不需要为此修复重新 deploy。仍需用户安装此包、刷新扩展并刷新所有 WhatsApp Web 页面后，完成实际新版扩展端到端验收；不能把临时诊断或本地构建当作已安装生效。未自动推送或更新生产下载入口。

### WhatsApp 实时翻译 v1.2（2026-09-05，发布候选完成）

扩展 `1.2.0` 已完成：连续消息采用稳定本地键与最多 3 路并发队列，每段消息都有独立“译此消息/重试”入口；德语、荷兰语、西班牙语、瑞典语可识别并自动切换该聊天的发送语言；输入框预览替换会回读确认，聊天或目标语言变化会废弃旧异步结果；图标使用黄色 LeShine 品牌底、WhatsApp 绿色气泡、`LeShine` 与“译”，插件主题同步品牌色。

稳定性收口：浏览器与 Provider 的瞬时错误只在同一 20/15 秒总预算内重试，结构化 502/503/504 也能进入补偿；相同请求成功结果先走幂等缓存再限流，失败结果不缓存，手动重试会真实重跑；授权/额度触发全局暂停时所有并发任务都会结束 loading 并可在恢复后重新入队。输入上限、每日字符与每分钟次数只读取 `WHATSAPP_TRANSLATION_MAX_TEXT_CHARS`、`WHATSAPP_TRANSLATION_DAILY_INPUT_CHARS`、`WHATSAPP_TRANSLATION_RATE_PER_MINUTE`，修改生产 `.env` 后必须重启服务。

验证：扩展 86/86（含类型检查、Vite 构建、确定性打包）通过；后端全量 4468 通过、4 跳过、0 失败；独立对抗审查发现的消息键漂移、打包目录误删、失败缓存、限流/幂等顺序、语言/聊天异步串台、unknown DOM 放宽及浅色对比度问题均已加回归测试。发布包 `whatsapp-translation-1.2.0.zip` SHA-256 为 `f91057e26c2004eb6a6ef6536c0e479ea19b4fa0f23dbbeac5a8e4446c532093`，大小 26,914 字节，扩展 ID 保持 `bnkecbkoidckffckbefjjcbchmngjobi`。全局约定检查仅被未修改的 `DomesticOrders.vue` 既有 UI 基线失配拦截，干净 main 同样复现。

生产仍待办公室 Windows Server 执行 `D:\commission-system\deploy\deploy.bat`；当前开发机没有该部署目录/服务，也没有 SSH、SMB 或 WinRM 通道，不能把合并推送视为已上线。部署后需验证 `/api/whatsapp-translation/health`、授权恢复、长德语文本、逐条重试、输入框替换，以及 Chrome/Edge 实机；员工推广前仍需完成 macOS Chrome 验收。

### WhatsApp 实时翻译（2026-09-03）

开发代码已完成：后端独立域和迁移 136、扩展、Ark 授权/管理页、确定性打包和运行文档均已落地。自动化验证已完成：后端全量 4425 通过、4 跳过；扩展 43/43 通过，前端授权/管理 helper 8/8、导航布局 8/8 通过。已知全量套件存在 1 个与本功能无关的历史失败：`test_agent_runtime.py::test_artifact_rejects_not_yet_effective_or_unavailable_ark_evidence[future_fact]`。发布 ZIP SHA-256 与实际文件一致，包内容仅含构建产物。

未完成的是实机验收和上线：Windows Chrome、Windows Edge、macOS Chrome 的三平台人工验收尚未执行，未做生产部署，也未向员工推广。上线前必须按 Task 16 完成语言、内容和安全矩阵，并核对 ZIP SHA-256 与扩展 ID。

> **版本**：v1.9
> **最后更新**：2026-09-02（工作区与发布状态核对）
> **项目状态**：运行中，持续迭代
>
> ⚠️ **发布状态提醒（2026-09-02 复核）**：共享库（CynosDB `commission_db`）`alembic current` 已为唯一 head `132_domestic_manual_price`（2026-09-01 核实时为 127；129–132 是否经过隔离演练与停写窗口未在本页留痕，待亮哥确认）；办公室 `CommissionSystem`、北京 `ark-backend`、新加坡 `okki-sync` 和 `social-customer-mcp` 均已恢复运行。北京后端与社媒 MCP 健康检查返回 200；办公室后端直连主库成功。办公室登录初次失败的根因不是网络或密码，而是低权限账号缺少跨库读权限；已为 `ark_app@%` 固定 `commission_db.*` DML + `lsordertest.*` SELECT，并从运行中北京实例实际读取 `lsordertest.user_rel_team` 通过。为保留既有管理员回款日期修复能力，另授予 `okki_receipts.collection_date` 列级 `UPDATE`，不扩大为业务库 DML。`root` 仍只用于受控迁移，不进入生产 `.env`。**「已合入 main」不等于「已上线」**，未在本页明确标注生产验证的功能仍不能当作已发布。

> ✅ **展会 kiosk 线索门店隔离（2026-09-02，北京展会实例已上线）**：修复 kiosk 销售面板 `GET /kiosk/leads` 与 `/kiosk/leads/{id}/strategy` 不做门店隔离的问题（绑定门店的账号如 MD01 登录可见全量线索）；两 endpoint 现与 PC 线索台共用 `_lead_store_scope`——按操作账号绑定的启用门店过滤，`expo_lead:read_all`/超管不限，无绑定=空集，strategy 跨店 404。main 已推送 `82dd4f3d`（含 5 个新测试用例，expo 全量 378 通过）。⚠️ 北京 `154.8.205.162` 部署方式特殊：`ark_app` 在 CynosDB `commission_db` 仅有 DML 无 DDL，130/131 迁移跑不了，故采用 cherry-pick 部署（`bf75b675` + 本地 `cf82d4eb`，不含内贸会员定价代码），后端已重启验证（403 鉴权正常、启动日志干净）。**北京仓库现与 main 分叉**：下次全量部署必须先由 root 受控通道在 CynosDB 执行 130/131 迁移，再 `git reset --hard origin/main`（或处理 cherry-pick 合并）后重启；切勿直接 pull 最新 main 就重启——内贸代码会引用尚未建的列/表，打挂内贸模块。

> ✅ **内贸会员与优惠价（2026-09-02，已合入 main；办公室后端已探测到新路由）**：分支 `codex/domestic-membership-pricing` 实现最近一次充值派生银卡/黑卡/至尊会员、共享原价维护、截图 131 条原价种子、固定会员价与等级立减、服务端权威批量报价、建单/草稿提交/换客户的报价确认与持久幂等、订单价格快照及 Excel 原价/优惠价导出，验收收尾后已以 merge `b1d46587` 合入 main 并清理分支。数据库采用 130 兼容回填 + 131 最终约束两阶段迁移。2026-09-02 复核：共享库已到 132；leshine.work 后端对 `POST /api/domestic/customers/{id}/initialize|adjust`、`PUT /api/domestic/items/{id}` 均返回 403（需登录）而非 404，说明办公室后端已部署 132 时代代码；线上前端全部 172 个 JS chunk 中命中 `manual_discount_price`、`level_adjust`、「期初初始化」，前端也已同步（2026-09-02）。原定的隔离 MySQL 演练与停写窗口执行记录本页没有，会员/原价/订单快照的线上业务核对也未做，不能把「路由存在」当作业务验收。验收收尾（提交 `5bb51dd9`）已补齐：报价变动摘要含原价/优惠价/规则文案、建单幂等键按 payload 指纹复用、共享原价保存/删除前强制影响范围预检、充值成功明示会员等级变化、缺价明细可一键跳到已过滤的产品清单、草稿提交按行防连点。

> ✅ **内贸手工改价（2026-09-02，已合入 main：merge `6f1f4f5b` + `f55109b2`，分支已清理）**：优惠价允许人工修改但只走显式契约——建单每行可附 `manual_discount_price`（>0 且不高于当前原价，计入幂等 hash，409 确认重试不丢）；已保存明细经 `PUT /items/{id}` 传 `unit_price` 改价（不高于原价快照，已发货明细与已发货/已终止订单拒绝），改后该行 `pricing_rule=manual_override`；非草稿订单差额立即与客户余额多退少补，草稿不动余额。手工价是绝对金额：草稿提交/换客户重算时该行不参与报价漂移比较，仅当原价被调到手工价之下才拒绝提交。下单页优惠价变为可编辑输入框（带恢复系统报价），订单详情抽屉新增「改价」入口。迁移 132 仅放宽 `ck_dom_item_pricing_rule` CHECK，随 129-131 一同演练发布。内贸后端 337 项、前端会员定价 12 项测试全绿。同一分支继续叠加了客户等级余额入口：`POST /customers/{id}/initialize` 期初写入余额+等级（仅无流水客户可用，幂等键 `init:{id}`），`POST /customers/{id}/adjust` 临时调整（有符号余额记 `adjust` 流水、等级覆盖记零金额 `level_adjust` 审计行，均按 `request_id` 幂等），两入口需 `domestic:recharge` 或 `domestic:admin`（内贸业务员角色已持有 `domestic:recharge`，无需额外配数）；等级覆盖是临时的，下次充值仍按金额重新核定。客户管理页新增「初始化」「调整」按钮与弹窗，流水类型同步展示。

> ✅ **内贸条件工序（2026-09-01，生产已切换）**：`main` 已实现内贸 `required / decision / optional` 三类规则、按具体单件的分流与自动/人工跳过审计、全后序撤销保护，以及 Web/小程序/PDA 共用的 outcomes 契约；真实 MySQL 已执行并验收 `127_domestic_route_rules`。生产路线 ID 8“头套网帽（递针）”与 ID 10“发片网底（递针）”均为启用状态、18 道工序，各写入相同的三个 decision 和一个 optional 条件契约；稳定编码/跳过目标分别为 `dandong → 李晓宏手钩+递针`、`lixiaohong → 丹东收货+发货`、`needle → 不跳过`、`no_needle → 李晓宏递针`、`qualified → 毛坯维修`、`repair → 不跳过`。生产 apply 已把 cap 的 5 条工艺映射/3 个产品全部绑定路线 8，把 piece 的 5 条工艺映射/4 个产品全部绑定路线 10，错绑均为 0；无需补建映射。既有 cap/piece 各 4 条订单明细仍全部保留在旧通用路线 ID 7，未删除、未重建。此次按亮哥明确指令在服务保持运行、相关工艺无业务写入的窗口在线执行；默认运维规则仍是停止全部内贸及路线配置写入后再 apply，不能把本次特批当作常规操作。

> ✅ **统一客户经营重构（2026-08-31，生产已切换）**：迁移 126 及客户主档、身份解析、事实证据、档案版本、Agent 上下文、公海背调、搜索任务、客户池、机会台、经营雷达、受控提案、MCP 只读工具和五个前端入口已合入 `main` 并部署。方舟是唯一真相源；公司名可空且不作身份键；外部来源经 Agent 事实化后进入方舟，消费 Agent 只读方舟。旧 `ark_sales_companies/contacts/research_*`、旧公海任务和旧客户画像运行时已退役。迁移冻结 39 张表、778 个字段，隔离 MySQL 8.4.11 严格模式与生产物理契约均通过，表/字段空备注为 0。生产切换库存哈希为 `74fa675c283fb105c6b113c502495b2b0c5c23605b377e2e00631c2c4fb65df7`；执行中暴露并修复了 canonical float 证据反序列化与 MySQL DATETIME 秒精度两项门禁缺陷，中间态经完整物理契约、Agent 闭包、目标画像、空抑制名单和 writer 权限恢复审计后晋级 `126`，恢复回执 SHA-256 为 `b24b81e8180e80423d6f904f78c81a027bf500e35e6e61d9786c208eeeecfdea`。办公室与北京实例均使用低权限 `ark_app`；完整权限边界是 `commission_db.*` DML + `lsordertest.*` SELECT，仅给主库 DML 会使登录在读取 `user_rel_team` 时失败。北京 `/health`、`/docs`、`/openapi.json` 返回 200，办公室标准部署已完成。

> 🚧 **外部站点订单发票接入（2026-08-26）**：功能分支 `codex/invoice-integration` 已完成 Phase 1/2 代码，包括迁移 125、Integration App 凭证管理、`/api/integrations/v1` 五个 REST 端点、严格金额校验、客户/产品解析、App 级幂等创建与结果恢复、后台「系统管理 → 站点接入凭证」以及 OpenAPI/TypeScript/Codex 接入材料。2026-09-02 复核：已合入 main（merge `75e1b03a`），迁移 125 已随共享库升到 132 一并应用；leshine.work 上 `POST /api/integrations/v1/invoices/validate` 返回 401 接入鉴权、`GET /api/integrations/admin/apps` 返回 403，说明公开端与管理端都已上线（注意该 router 对错误 HTTP 方法返回 404 JSON，GET 探测不作数）。COEDEX 站点凭证已签发，试点联调与吊销/审计闭环是否完成本页无记录。后端全量已实跑 `3092 passed, 1 skipped`，前端接入专项 `39 passed` 且生产构建通过；这只证明当前代码与测试契约通过，不代表生产联调。下一步依次是：真实 MySQL 执行并核对唯一 head、两表/唯一约束/FK；重启 seed 后给管理员角色分配 `integration:admin`；签发一枚临时试点凭证；用脱敏样例验证 validate/create、相同内容幂等重放、改内容 409、超时后按 external_order_id 恢复以及全程不产生 OKKI 同步；最后吊销试点凭证并保留带明确试点标记的发票作为幂等审计记录。外部 REST API 不提供发票更新（update）、删除（delete）、作废（void）端点或提成（commission）字段；方舟内部删除需 `invoice:write` 且符合现有发票可见范围；已有 `xiaoman_order_id`、`sync_status=synced`/`sync_status=sync_uncertain` 或未恢复半成品库存时拒绝；允许时同一事务删除 ingest 与发票，释放 App + `external_order_id`，独立站同订单重新 POST，按首次创建返回 HTTP 201 并建立新的幂等记录。

> ✅ **OKKI 截图导入（2026-08-25 开发，已合入 main 并上线）**：`codex/invoice-screenshot-import` 已实现 OKKI 订单截图 AI 字段提取、确定性客户/业务员/产品/SKU/来源订单核对、人工预览填入、签名预览凭证、同图/同订单防重和重复推送禁用；迁移为 `119_invoice_screenshot_src`。独立对抗审查已完成，其发现的预览来源可伪造、上传整体读入、无候选时定制产品入口不可达、非 USD 订单误关联和 OCR 订单名不一致问题均已加固；专项后端 54 例、前端专项测试和 Vite 构建通过。迁移 119 已在合并前改接 118；2026-09-02 复核共享库唯一 head 为 132，leshine.work `POST /api/invoice/import/screenshot/preview` 返回 403（需登录），后端已部署。

> ✅ **功能分支完成（2026-08-25）**：`codex/semifinished-inventory` 已实现迁移 120/121 的半成品列表、产品解析关联与人工组成修正、按 g 下单/分批入库、实存/占用/可用/在制库存、生产购物车同步下单及生产发票的 OKKI 同步预占—出库—补偿恢复。线上迁移已到 121，产品同步结果为 794 个关联、233 个半成品、429 个待审核关联；待审核项不会自动下单或领料。详细规则见 `docs/requirements/2026-08-25-semifinished-orders-inventory.md`；已合入 main（merge `712b3882`），2026-09-02 复核 leshine.work `GET /api/semifinished/orders` 返回 403（需登录），后端已部署。

> 🧹 **工作区与发布核对（2026-09-02）**：本地只剩 `main`（与 `origin/main` 一致）且单一 worktree；6 个已等价合入 main 的 codex 分支（含 `ai-chat-modes-20260826`、`expo-kiosk-lead-scope`，后者的 superpowers 设计/计划稿已补进 main）与 4 个远端孤儿分支中的 2 个已删除。远端 `codex/fix-sales-candidate-submit-500`（修的 `identity_candidates` UNION 已在 2026-08-31 统一客户重构中退役）与 `codex/mobile-web-reporting`（内贸手机浏览器扫码报工，未合入，被 PDA 原生 + 小程序路线取代）已按亮哥指令于 2026-09-02 删除，origin 只剩 `main`；`cloud` 远端残留的 `codex/unified-customer-profile`（内容已全在 main）也已于 2026-09-02 删除，北京仓库 HEAD 仍在 main `82dd4f3d`（cherry-pick 分叉状态未变）。stash `codex-pre-merge-knowledge-20260810` 按亮哥指令保留。线上探测口径：leshine.work 后端返回 403/401 = 路由已部署；GET 探测到 404 不能下结论，要用真实 HTTP 方法；前端以首页 `index-*.js` 引用的全部 chunk 为准 grep 特征字符串。本机无法直连办公室 8001 与服务器 SSH，未核对 deploy marker 与服务重启日志。
### WhatsApp 实时翻译 v1.1（2026-09-04，开发完成）

分支 `claude/whatsapp-translation-v2`。交互修复：发出方向目标语言接通（原先恒为 zh-CN 原样返回）、恢复预览-替换-恢复原文流程、工具条挂到 footer 首子节点、全中文文案并按错误码给下一步、弹窗显示员工姓名与默认发送语言（默认 English）、发送语言按聊天记忆（沿用哈希键）、「启用翻译」开关在后台 fail-closed。译文质量：收发拆两个 preset（收件端忠实/发件端商务聊天语域，发件带回译 `back_translation`）、外贸术语表复用 `sys_dict` 类型 `whatsapp_glossary_<lang>`（启动幂等种子 + 运行时只注入命中项，管理端在数据字典维护）、可识别源语言从 constants 运行时注入不写死在 prompt。扩展 1.0.3 → 1.1.0，后端最低扩展版本保持 1.0.0。

验证：后端翻译专项 33 通过；扩展 62 通过（typecheck + vitest + Vite 构建通过）。未做：对抗性审查、检查约定脚本、实机三平台验收、合并推送。第 3 部分（知识库回复建议）未启动。

## 2026-08-26 AI 方案对话 · 四种对话方式

- **实现分支**：`codex/ai-chat-modes-20260826`。将旧四入口替换为深度思考、天赋挖掘、未知领域引导、寓言讲概念；规则文件化，点击不覆盖草稿、不自动发送。Skill 显示服务端确认的加载状态并可折叠预览；内置规则不占附件名额。历史方式固定，另开会话换方式；草稿、刷新、停止/重试与只读模式均保留对应边界。
- **安全与上下文**：首次发送在会话行锁事务内保存 SHA-256 规则快照。普通上传文件仍是数据；未知领域使用明确标注的网页适配版，原始 Skill 留作来源。模式上下文不受最近20条窗口影响，但超过200条/120,000正文字符或附件被截断时明确失败；重试不会读到原问题之后的消息。长度终止原因透传，报告被截断时明确提示回复“继续”。
- **数据库已应用**：开发/生产共用数据库已执行 `124_ai_chat_modes`，`alembic current` 为唯一 head；已核查 `ark_ai_chat_sessions.mode_snapshot` 是可空 JSON。原会话 NULL，不会被自动改成某种方式。
- **验证**：后端全量 `2974 passed, 1 skipped`（268.65秒；已有 warnings），ai_chat专项 `158 passed, 1 skipped`；前端 `aiChatState.test.mjs` 30项通过，Vite build通过，约定检查/差异空白检查通过。后端单独测试需预先导入 `app.invoice.models`，因现有 conftest 的半成品FK注册依赖；未为绕过问题修改生产代码。
- **独立审查**：修复普通请求幂等重放忽略模式、早期附件截断、历史重试读未来消息、旧会话加载覆盖新草稿、切新会话loading卡住、409版本冲突无法重载等问题，均有回归测试。
- **真实模型冒烟**：现有 `customer_ai_chat`/`claude-fable-5` 调用，四种方式分别成功返回（AI日志2421–2424）；深度思考先论证再问关键问题，天赋先介绍流程并进入第一轮，未知领域给盲区和候选问题，寓言给故事/解析/检验问题。全部为虚构验收素材，无真实个人访谈数据；未把万字最终报告效果当作已完整验证。
- **页面验收**：实际构建页面 + 真实ai_chat路由，使用内存SQLite、虚构用户和模拟模型完成四入口、草稿、文件预览/加载失败/重试、历史刷新、天赋免输入启动、长度提示、只读和移动端检查。检查平台真实导航/页签后修复高度计算与输入框裁切；390×844/390×500仅为响应式与键盘高度模拟，尚非实体手机键盘实测。临时脚本/截图在本分支 `tmp/qa-chat-*`，不发布到生产。
- **已合入并上线（2026-09-02 复核 leshine.work `GET /api/ai-chat/modes` 返回 403 需登录，后端已部署；线上前端 chunk 含 `ChatModeBar` 与 `/modes` 调用，前端已同步；四种方式的名称来自服务端规则文件，不在前端包内；分支 `codex/ai-chat-modes-20260826` 与远端同名分支已于 2026-09-02 退役）**。以下为 2026-08-26 当时记录：已同步远端更新，将功能重放到最新 main 并推送 `71597610`；重放后后端 service/router 50项、前端30项、Vite build与约定检查通过。办公室实例 `/api/ai-chat/modes` 实测仍返回404，证明服务仍是旧代码。服务器22/5985端口不可达，本机也没有 `D:\commission-system` 或 `CommissionSystem` 服务，无法远程执行生产脚本；需在办公室服务器运行 `D:\commission-system\deploy\deploy.bat`，再验证该端点、Skill快照预览、真实会话与手机键盘。
- **补充核对**：原始 Skill 副本与用户来源文件正文一致，四份运行规则均能从仓库资源加载，部署通过 git pull 带入，不依赖 Downloads。详情抽屉取消默认300ms过渡，满足键盘与减少动态效果要求；真实构建页面先复现减少效果下仍有0.3秒过渡，再修复为0秒并重跑整组页面验收、30项前端测试与构建。
- 设计与契约：`docs/requirements/2026-08-26-ai-chat-modes.md`、`docs/api-reference.md`、`docs/database.md`、`docs/module-notes.md`。

## 2026-08-26 openlux Grok Image 2 接入

- 已用现有 openlux Provider #7 完成鉴权及实时目录校验，创建 Preset #28 `design_image_generation_grok_image_2`，实际模型 `grok-imagine-image-2.0`，参数 `response_format=b64_json / output_format=jpeg / n=1`；未修改其他 Provider/Preset。开发与生产共用数据库，因此配置已经保存。
- 工作台显示名仍为 Grok Image 2；替换未配置的旧占位 ID，限定 openlux HTTPS API 地址，其他模型继续限定 TeamRouter。Grok 请求 size 转 aspect_ratio，输入最多 3 张（含基准图），超限入队前提示删图。修复公共图片传输层 gzip/deflate 二次解压错误。
- 实测：原始接口文字/单图/双图通过；统一 facade + runtime 正方形生成成功（log #2414，52.964 秒，1024×1024 JPEG）、三图竖版编辑成功（log #2416，14.643 秒，832×1248 JPEG）。5 图探针明确被上游拒绝，已落实 3 图限制。尺寸只承诺比例，质量档位差异未验证；不配置未经核实的费率。
- 验证：535 项后端相关测试、27 项前端状态测试、Vite build 通过；独立对抗审查无阻断项，`git diff --check` 通过。`check_conventions.py` 被既有 `InvoiceManage.vue` 的 lines_over_500 基线失配拦截（未改动的 main 同样失败）；独立执行增量代码检查结果为空，未重置基线或修改发票页面。
- **待部署**：2026-08-26 亮哥已授权合并、推送 main；已合并远端最新北京时间与 GMV 等更新并复验 Grok 接入，办公室服务器尚未部署。此前 `http://192.168.101.193:8001` 实测仍返回旧 Grok ID / `available=false`；仅保存 Preset 不会自动更新目录代码。main 推送完成后，办公室 `D:\commission-system\deploy\deploy.bat` 发布后端与前端，再验证 `/api/design-image/config` 出现新 ID / `available=true` 及真实工作台生成。当前机器能访问办公室 API，但 SSH/WinRM 均不可达，没有可用的远程部署通道。
## 2026-08-26 客户产品模板图片预览修复（待生产部署）

- 编辑器图片逐张加载、单张失败隔离、失败提示与单图重试，切换产品/关闭弹窗会取消旧请求并回收预览 URL；邀请链接复制在 Clipboard API 被拒绝时自动降级到传统复制通道，两种方式都失败才提示手动复制并保留一次性链接。
- 现场故障有两层：编辑器原先用 `Promise.all` 一张失败使全部预览不显示；先前批量创建的产品记录写入共享数据库，但 56 份图片仅落在开发机私有素材盘，尚未核实办公室生产盘。用户后来上传的封面 73/74 与原示例资产 6/12 不在开发机，不应覆盖。
- 本地一次性恢复包位于 Codex worktree 的 `tmp/customer-image-repair-20260826/`（不入 Git）：包含 56 份与数据库 SHA-256 一致的图片及只补缺失、不覆盖的恢复程序。已完成本机只读预检；未在生产执行，不能标记图片恢复完成。
- 待办：获得办公室服务器 `192.168.101.193` 的操作入口，在服务器 backend 环境执行恢复包预检/补齐；按 `deploy/deploy.bat` 部署前端并验证真实编辑页。SSH/SMB/WinRM 探测不可用，Chrome 控制接管超时，没有改动服务器或绕过认证。
- 全局规范检查被主分支既有 `InvoiceManage.vue` 的 UI 行数基线过期阻断，在未修改的 main 上同样复现；本次不改无关发票模块。

## 2026-08-20 DSH Agent Runtime 交接

- 开发分支 `codex/agent-runtime-phase1` 已实现迁移 118、统一 Agent 控制面、受控模型/MCP 网关、隔离 DSH Worker、客户经营副驾驶、复购行动卡、获客 Shadow、任务中心和运行时间线；Feature Flag 全部默认关闭，尚未合入 main 或部署生产。
- Worker 固定 DSH `0.1.0rc8`；PyPI rc7 Runtime 不含 MCP Client，不能用于方舟。除本地 macOS arm64 真实 Runtime E2E 外，2026-08-25 已由 GitHub Actions run `32798681826` 从固定 upstream commit `141eb6f` 构建 Linux x86_64 候选：manylinux 2.28 构建与严格封包校验通过，Rocky 8.9 全新容器以非特权用户完成真实 DSH 冒烟，第三个全新 job 复验后生成 GitHub OIDC/SLSA provenance。reviewed artifact 为 `dsh-rc8-manylinux_2_28-x86_64-candidate-3b9a2e2c413ec479ef9cac179df261354d57a54d`，保留 90 天；Runtime wheel SHA-256 为 `ead23bd2a1802c96be35e7dcb14267ea7df99ea930c2de210b8b071e0d73bc1d`。本机下载后 `SHA256SUMS` 与 attestation subjects 均 7/7 复验通过。该结果只证明 feature-branch 候选可安装，不代表已合入 main 或已部署生产。
- 上线必须按 `docs/runbook.md` 的“DSH Agent Runtime 灰度与回滚”执行：唯一实例迁移、三只 AI Preset、机器 token hash、Run secret、最小角色权限、内部副驾驶、复购、5% 获客 Shadow 逐层开启。
- 不改变现有 OpenClaw 正式获客和邮件链路。DSH Shadow 只产生 Artifact；复购成果只有人工接受且原行动仍 pending 才投影。止损优先关 Profile/Runtime flag，保留 118 数据结构和审计记录。
- 2026-08-20 对抗性复审已清除 P0/P1：Run Token 绑定 attempt/lease、Worker runtime 绑定、独立租约回收、递归成果 Schema 与本 Run evidence ledger、客户委托范围、跨 owner 写权限、硬步骤/时长/Token 预算、无 usage/断流保守计费、Shadow best-effort 以及复购刷新去重均有回归测试。后续又补齐多成果决策锁、Web peer fail-close、角色快照、工具结果哈希、MCP `ok:false` 业务失败不得进入成功证据账本、定量结论逐条引用和本地 Session 90 天留存清理。
- 管理员可在任务中心使用版本化 30 题目录，从自身客户数据范围选真实客户并启动正式评测；后端按题校验客户雷达/订单权限及真实数据，Session+Run 原子创建，题目/客户/契约 cohort 冻结并去重统计。Profile 或模型 Preset 变更后不混算旧样本。`/api/agent-runtime/evaluations/readiness` 汇总 30/200/50 业务门槛；当前没有生产样本，必须保持 Shadow，不能把真实 Runtime E2E 通过等同于业务灰度完成。
- 最终验证：Agent Runtime/调度器定向 70 项、DSH Worker 本地回归 22 项通过（1 项平台条件跳过）及本地真实 rc8 Runtime E2E 1 项通过；Linux 候选的 auditwheel policy 为 `manylinux_2_28_x86_64`，2 个 ELF 已核对且最高 GLIBC 符号为 2.28，GitHub 双容器构建/冒烟/OIDC 证明全绿。前端生产构建与后端 864 路由导入通过；后端全量 2,789 通过、8 项既有环境/基线失败，前端全量 328 通过、7 项既有断言失败。Alembic 唯一 head 为 `118_agent_runtime`；当前环境没有 MySQL/Docker，真实 InnoDB 双连接并发仍列为上线前验证项。Feature Flag 仍全关，未合入 main、未安装生产 wheel、未做 30/200/50 真实业务灰度。

## 项目概况

- **项目名称**：莱莎方舟平台（LeShine Ark Platform）
- **开发周期**：2026-03 至今（约 4 个月；git 仓库首次提交 2026-04-20）
- **代码规模**：后端 ~25K 行 Python + 前端 ~18K 行 Vue + 微信小程序 ~3K 行
- **数据库表数**：120 张（commission_db，2026-07-13 information_schema 实测；此后 079~104 迁移续有新表，未重新实测总数）
- **数据库迁移数**：104（Alembic head `104_ci_generation_snapshots`，2026-08-10 唯一 head；近期 099 智能获客、100 AI 方案对话、101 企业知识库六表、102 客户生图门户、103 洞见消息互动、104 生图快照）。**迁移门禁**：隔离 MySQL 实跑尚未通过（本机无 docker），见 runbook「数据库迁移」节
- **用户数**：~30 人（莱莎员工）
- **日活**：~20 人
- **部署环境**：生产（腾讯云新加坡 Nginx + 本地 Windows Server + 北京云展会实例 2026-07-22 起，拓扑见 docs/architecture.md）

## 已完成功能（2026-08-01 更新）

### 核心业务模块（1~22 项 2026-08-01 更新，23~31 项见下一节）

1. ✅ **提成管理**：回款单计算、客户归属快照、批次管理、业务员确认流程（confirming 状态 + 反馈/确认机制）
2. ✅ **订单发票管理**：发票 CRUD、产品级联选择、Excel/PDF/HTML 导出；OKKI 推单闭环（2026-07-13：真实推单 + 幂等编辑 + 非标合并单条通用行 + 企业必填字段部门/订单类型/新成交/包邮/首返 + 同步日志，066/068 迁移）；数据范围权限 `invoice:read_all`（默认只见自己创建的发票，067）；录入自动填充（客户联系人快照复用 + 业务员信息默认当前用户 + 小满标记三开关智能默认）；**配件双类型**（2026-07-18 合入：明细 `product_kind` hair/accessory、配件标准价按真实 product_id+sku_id 唯一、金额 ROUND_HALF_UP 口径、PDF 中文字体预检，073/074 迁移）；2026-07-23 修复三项：粘贴导入支持非整数克重（37.5g / 0.0375kg，尾零规范化）、编辑器页脚「保存并校验」改为「保存并同步」（校验+推单一步走，走同一 `validateThenSync`）、OKKI 推单订单名只用发票号不再拼客户名
3. ✅ **物流跟踪**：DHL/FedEx 自动轮询、关键状态推送、物流日报
4. ✅ **运单上传**：图片 OCR（AI 多模态）+ 手动录入
5. ✅ **设计预约**：申请/审批/排期、冲突检测、附件上传、钉钉通知
6. ✅ **认证与 RBAC**：用户/角色/权限、JWT + Refresh Token Cookie
7. ✅ **AI 接入**：Provider/Preset 管理、调用日志、API Key 加密存储
8. ✅ **方舟洞见**：
   - 信源配置（13 种 source_type）
   - 情报采集库（结构化条目 + 可信度标记）
   - 行业情报速览（AI 6 部分生成）
   - 行业情报日报 + AI 工具速递
   - 案例库（AI 整理 + 用户修正）
   - 周会纪要（AI 整理 + 任务跟踪）
   - **客户机会台**（ACCIO 询盘导入 + 归属解析 + 机会卡 + 话术）
   - **客户经营雷达**（活画像 + 事件流 + 6 线索分组 + 行动推荐）
9. ✅ **素材管理**：标签化中台、AI 打标签、版本迭代、收藏分享、移动端独立页面
   - **标签体系 v2**（2026-07-22 切换 + 同日退役旧维度，078 迁移）：11 维正交体系取代文件夹平移来的 5 维老体系；`is_visible` 作为并存/切换/退役开关；体系定义唯一真相源 `taxonomy_def.py`，AI 值域运行时注入（不再硬编码进 prompt）；前端分组渐进筛选（常用展开/高级折叠）；迁移脚本链 `backend/scripts/tag_taxonomy/`（含设计部日常用的上传目录骨架生成器）。退役实测：删 39,556 关联行/412 值/4 维度，零素材失标；**备份表已于 2026-07-24 清理**（DROP 前后各复查一次，回滚 SQL 导出在 `backend/tmp/asset_taxonomy_backup_2026-07-24.sql`）。踩坑与运维见 `docs/module-notes.md` 素材节
   - **MCP 素材工具**（2026-07-22）：`list_asset_taxonomy` + `search_assets`，业务员在自己的 agent 里直接检索素材并拿 24h 签名下载链接
10. ✅ **发色数字化**：色板数据库、混合色管理、色彩趋势、AI 色板图生成
11. ✅ **备货管理**：安全库存设置、销量备货一览、库存日报、低库存钉钉推送
12. ✅ **生产订单**：购物车 → 批量下单 → 订单跟踪 → 入库录入
13. ✅ **生产报工**：工序管理 → 路线配置 → 产品绑定 → 扫码报工 → 生产看板
14. ✅ **报表中心**：Stimulsoft Reports.JS（DOM 挂载 Viewer/Designer + 后端 JSON 数据 API）
15. ✅ **微信小程序**：扫码报工 / 报工历史 / 报工总览 / 登录绑定
16. ✅ **数据概念治理**：概念注册表 / 8 分区编辑器 / 关联关系 / 全景图谱 / 变更历史
17. ✅ **WhatsApp 同步**：扫码绑定 / 会话消息拉取 / 附件投影 / 自动定时同步
18. ✅ **钉钉集成**：工作通知（设计预约 + 物流状态）+ Webhook 推送 + 审批回调
19. ✅ **短链服务**：统一短链生成（`/s/{code}` 双查找路由）
20. ✅ **展会 AI 试戴**（2026-07-03，内贸品牌「莱莎健康假发」，8 月展会用）：
    - H5 kiosk（`/expo/kiosk` 全屏路由，展位 iPad 全天运行）：注册→拍照→AI 面容分析→规则匹配（至臻锚点）→效果图合成→前后对比滑块→销售双轨话术接力
    - PC 端：试戴发型库 / 话术卡库（19 张种子卡已导入）/ 展会线索台
    - 品牌视觉 2026-07-03 依《内贸品牌图》定稿：祖母绿×瓷白×樱粉（原型 v2-green 为准；kiosk 实现侧换肤待做）
    - 合成双入口 + 发色选择（2026-07-04，047 迁移）：mode=tryon（换发）/ mode=scene（佩戴实拍直接生成商务/晚宴/咖啡/旅行/居家场景大片，跳过分析与话术）；含独立 agent 对抗性审查后的失败路径加固（整批失败重试出口、分析失败退回拍摄、生成中幂等挡板）
    - 2026-07-07 全链路实测迭代：**图像模型已接入**（`expo_wig_composite` 启用，Provider 当日从 ELBNT 切云雾 api.wlai.vip/gpt-image-2，单场景实测 41~135s）；发色库独立表（048，色板图+描述，三图合成）；匹配屏单选发型+可选生成场景（原景/居家/办公/聚会/**多场景合一**横版三联图）+ AI 面容解读展示；输出尺寸限定（单场景 6 寸竖版 1024x1536 / 多场景 6 寸横版 1536x1024，走生图 API size 参数）；魔法镜框动效 + 黑金 LOGO + 新广告语；结果页二维码卡片化+手动返回（不自动清场）+ 查看大图灯箱；稳定性四件套——性别过滤全灭兜底、卡死看门狗（pending>180s/generating>420s 自愈）、AI 非法 JSON 纠错重试、参考图送模型前统一压缩（16MB→155KB）；生图超时下限 300s
    - 2026-07-07 话术链路重设计（用户纠正驱动）：话术随合成启动**并行生成**（等图期间即顾问沟通窗口，完成后触发保留为兜底，互斥防重）；**kiosk（客户共享屏）不再展示话术与 internal 发况**，唯一展示面为试戴线索台（详情抽屉静默轮询自动出话术）；话术严格锚定"客户脸型特征 × 试戴发型真实特征"（prompt 注入发型特征清单+防杜撰硬约束）；面容分析加脸型判定标准与 face_features 字段；发型库从分析表 Excel 导入 12 款新发型（现 16 款）
    - 2026-07-13 推荐与拍照体验：**主推置顶**（must_recommend 语义升级——置顶推荐列表最前，多主推按匹配分排序，至臻锚点只换第一批非主推位；065 迁移同步列注释；管理列表与 kiosk 从库选择同步置顶）；kiosk 拍照页「三步拍出高级感」引导浮层（略俯拍/微侧面容/构图靠上，SVG 金线示意图 ×2，首次进屏自动弹、失败回退不重弹）+ 取景椭圆上移（头部落上三分之一）
    - **待完成**：云雾 Provider 偶发 500 与多场景合一成功率观察；**12 款新发型无参考图/封面**（multi 与单场景合成均退化为文字描述，还原度打折，待市场部实拍图）；心动款 reaction 不进前置话术（如需"点心动后重生成话术"再加）；kiosk 品牌绿换肤待做
21. ✅ **PM 项目资料协作站**（2026-07-17，阿里国际站智能体陪跑项目；设计稿 docs/requirements/2026-07-17-pm-material-hub.md）：
    - 独立子站 `pm.leshine.work`（**2026-07-18 已上线**：DNSPod A 记录 + Let's Encrypt 证书 certbot webroot + 云 Nginx `/etc/nginx/conf.d/pm.leshine.conf`，门牌页/API 反代/HTTP 跳转全链路实测通过）：后端 `app/pm/` 领域模块（8 表，076 迁移），前端 `frontend-pm/` 完全独立应用（自研编辑感设计系统，无 Element Plus，与方舟零视觉血缘）
    - 无密码门牌：用户名白名单换 HMAC token（30 天 + epoch 全局重签兜底），每请求回查白名单（移除立即生效），统一失败提示防枚举 + 用户名维度限速；顶栏身份常显可一键切换
    - 35 项材料清单（五分类 × 重要级 × Phase 批次；**2026-07-18 已按顾问原清单《00_索引与缺口清单.md》重灌**，任务清单同步为行动清单 14 条）；版本自动编号只增不复用、软删回落、下载自动重命名 `名称_vN.ext`、凭据类禁传原文；AI 差异概要=本地精确 diff（difflib/openpyxl/docx/pypdf）+ pm_diff preset 转述，pending 看门狗启动回收
    - 轻量看板（四状态 + 受阻必填原因 + 关联资料徽标）、全站动态（审计日志用户侧）；文件存 `backend/data/pm/`（非公开静态），下载/预览 300s 签名 URL
    - 2026-07-18 追加：上传对话框/抽屉 await-emit 修复（真等待+失败留窗）+ 拖拽上传；IP 维度 entry 限速（X-Real-IP，20 次/分）；**Phase 2 之 MD 在线编辑已完成**（`POST /versions/text` + MdEditor 分屏编辑器，基线冲突确认，走上传同一版本通道）
    - **2026-07-19：Phase 2 之版本评论已完成**（合入 main，待部署）：评论挂具体版本、版本卡内展开；单层回复自动拍平、仅作者可删、占位线程可续贴；无版本资料（offline/link）无评论；资料库列表 `❞ N` 角标 + 动态流「评论」筛选；两轮对抗性审查（细节见 module-notes PM 节）
    - **待完成**：生产 `.env` 可选项 `PM_TOKEN_SECRET` 独立随机串（当前回退 JWT_SECRET_KEY，见 runbook PM 节步骤 5，服务器上一条命令+重启，会全员重新进门牌）；Phase 2 之划线锚点评论未启动（anchor 字段已预留且评论表已在用）
22. ✅ **培训速递**（2026-07-18 合入 main）：参训人自助发布 + AI 提炼草稿（粘贴文字/图片多模态/PDF 抽文本 → 结构化分区）+ 4 步强引导向导 + 发布必填分区校验 + 钉钉群 actionCard 推送 + 「有用」轻反馈；`training:read/write/admin` 权限；075 迁移，3 张表
    - **2026-07-23 列表删除动作接线**（✅ 已 push origin，⏳ 待生产 deploy.bat）：`deleteDigest` API 与后端端点早就存在但前端从没调用过（操作列只有查看/编辑）；行级可见性镜像后端规则（作者本人或 `training:admin`，已发布行仅 admin），避免点进去吃 403。2026-07-24 已推到 origin/main，线上仍无「删除」是因为**生产服务器还没跑 deploy.bat**（deploy 只能在办公室 Windows Server 的 D:\commission-system 上跑，开发机跑不了）——下次部署即生效
    - **2026-07-21 附件增强**（077 迁移，**2026-07-24 核实已上生产**：线上 TrainingEditor 包含「自动识别」）：附件类型白名单下拉（默认按扩展名自动识别）+ 批次备注 + 多选上传逐文件进度 + 列表行内改类型/备注（`PATCH /files/{id}`，失败回滚显示值）；存量附件显示「未分类」；公共组件 `AppUpload` 新增 uploadFn onProgress 第二参数与 `show-list` 开关（向后兼容）；编辑器附件区拆 `AttachFilesPanel.vue`

### 2026-08 新增模块（⚠️ 均为本地 main 已提交，**尚未 push origin、尚未部署生产**）

以下模块的路由已在 `backend/app/routers.py` 注册、菜单已进 `navigation.js`，本地 8001 可用；生产 404。细节见 `docs/module-notes.md` 对应节与 `docs/superpowers/{specs,plans}/`。

23. ✅ **客户售后管理**：`app/aftersales/`，售后工单与处理流转
24. ✅ **薪资计算**：`app/salary/`，工日来源 / 钉钉考勤唯一约束 / 计算开关 / 请假来源（095~098 迁移）
25. ✅ **采购节大屏**：`app/festival/`，公开层 `/api/public/festival` + 管理端；积分按客户资源来源逐客户计分（口径见 cerebrum 2026-08-04）
26. ✅ **名片管家**：`app/card/`，管理端 + 公开层；`leshine.work/card/<slug>/` 四页已线上验证（静态主页独立上云，不随后端部署）
27. ✅ **AI 生图工作台**：`app/design_image/`，设计部生图；2026-08-10 起 Pantone Solid Coated 色库
28. ✅ **客户生图门户**：`app/customer_image/`，邀请制 + 公开层（102/104 迁移）；素材保留 `CUSTOMER_IMAGE_RETENTION_DAYS` 默认 30，每日 03:30 清理 job
29. ✅ **AI 方案对话**：`app/ai_chat/`（100 迁移），附件不可信数据口径与文件边界见 module-notes
30. ✅ **智能获客**：`app/sales_automation/`（099 迁移），含 Agent 专用路由
31. ✅ **企业知识库**（101 迁移，六张 `ark_knowledge_*` 表）：库级 ACL（viewer/editor/reviewer/admin）+ 不可变 revision + 发布审批 + 软删除（库/目录递归，同时取消关联待审批）；HTTP 与 MCP `search_knowledge`/`get_knowledge_document` 共用同一 service 层 ACL，无资源权限统一 404；本期无附件/导出/下载
    - 2026-08-10 编辑器 P0：Tiptap 3.29 工具栏 + slash 菜单 + 大纲 + 保存态标签；脏态导航拦截
    - 2026-08-10 删除与并发：库行锁串行化新建/保存/提交/审批/软删除，获锁后重校验，避免孤儿节点与残留待审批
    - 2026-08-11 UI 交互打磨：搜索 loading、状态提示、键盘提示、列表与编辑器反馈；按高频交互原则移除 Slash 菜单和文本选区工具栏的装饰性入场动画
    - 2026-08-13（`codex/knowledge-editor-ai`，迁移 112，待合并/部署）：私有图片选择/拖放/粘贴、修订级图片 ACL 与临时图清理；AI 智能排版和知识增强异步任务、配置/提示词/来源库页面、来源冻结与引用证据、生成后独立语义审计、差异预览、基准冲突保护、跨库审批确认。部署需先升级迁移、配置 `KNOWLEDGE_STORAGE_ROOT` 和 direct 文本 AI Preset、安装知识图片 11m 精确 Nginx location，再分配 `knowledge_ai:write/admin`。

### 基础设施

- ✅ 定时任务（APScheduler，11 个 job）
- ✅ 移动端素材管理（Vue 3 CDN 独立页面，UA 守卫分流）
- ✅ 生产架构（腾讯云 Nginx 静态直出 + frp 内网穿透 API 反代，frpc 挂 NSSM）
- ✅ NSSM 服务托管（CommissionSystem + WhatsAppConnector 双服务）
- ✅ 前端路由 + 菜单单一来源（`navigation.js`）
- ✅ API client 统一（`clients.js` 集中导出，禁止自建 axios）
- 🚧 **Agent 记忆系统换代**（2026-08-14，分支 `codex/claude-mem-mem0`）：旧 `.wolf` hooks 保持退役；本机已安装 Claude Code 2.1.232、claude-mem 13.15.0、Bun 1.3.14、uv 0.12.4，worker/SQLite 健康且 telemetry 已关闭；新增 `scripts/memory/` 白名单增量同步器（独立游标、文件锁、来源键去重、失败重试/异步恢复、dry-run、敏感信息整条排除、默认不回填）和双 Agent 检索协议。稳定 `user_id=leshine-ark-owner-v1`，本机 `source_device=mac-mini-11`，游标已在空库 `max(id)=0` 初始化。**待完成**：Claude/Mem0 账户授权、Keychain API key、真实新会话 observation、本地/跨 Agent/跨机器盲测；未经亮哥确认不得历史回填。
- ✅ 权限矩阵配置（2026-07-03：23×5 矩阵抽屉 + 6 角色模板 + 按导航反查 + 变更审计 + v-permission 指令；81 权限清理为 69 有效）
- ✅ **多智能体 Git 协作治理**（2026-07-18）：`AGENTS.md` 约定（分支 `<tool>/<topic>`、每代理独立 worktree、feature 分支随时推 / main push 等指令、合并只在主 worktree）+ `scripts/git_sweep.py` 巡检看板（六类欠账含跨分支 Alembic 撞号检测）+ Windows 计划任务 `LeShine-GitSweep` 每日 18:00 推钉钉；同日发现并修复 `DINGTALK_WEBHOOK_URL` 长期为空——定时任务告警/培训推送/巡检通知三条管道此前全部静默失效

### 测试覆盖

- ✅ 提成计算单元测试（27 个）
- ✅ 设计预约状态机 + 冲突引擎测试（34 个）
- ✅ Scheduler smoke 测试（10 个）
- ✅ expo 匹配引擎 + 禁用词 + 性别兜底（16 个）+ 发色库/场景/看门狗/JSON重试/图片压缩逻辑测试（39 个，含多场景合一与输出尺寸）+ 话术触发互斥（2 个）——2026-07-07
- ✅ tracking 状态映射（57）/ stock 状态判定（20）/ 提成批次状态机全矩阵（31）/ invoice 金额（14）——2026-07-03 B-8 补齐
- ✅ invoice / whatsapp / payment 等模块测试
- ✅ invoice OKKI 推单专项（payload 映射/状态机/unique_id 传承/非标合并/必填字段）+ 数据范围 scope + 录入自动填充——2026-07-13 补齐
- ✅ 素材标签体系 v2 专项（`test_asset_taxonomy.py`：维度可见性口径 / 按维度合并语义 / 单选校验 / folder_upload 子集合并 / 色系派生规则）——2026-07-22
- **总计 532 tests（2026-07-13 全绿）→ 753 tests（2026-07-18 全绿，培训速递/PM 站/发票配件合入后；PM display_name 断言已随 seed 改名修复为从 MEMBERS_SEED 派生）→ 777 tests（2026-07-19 全绿，PM 版本评论 + expo 夏季衣橱合入后）→ 786 tests（2026-07-21 全绿，培训附件类型/备注合入后）→ 825 tests（2026-07-24 实测全绿，素材标签体系 v2 + 发票粘贴导入/推单修复合入后）→ **827 backend tests + 70 frontend node tests（2026-07-24 晚，多代理分支收拢后全绿）**：修了 origin/main 上 2 个陈旧断言（`test_customer_contact_defaults_latest_snapshot` 缺 last_order_date 键 / `invoiceAccessories` 断言了被有意移除的"请求开始清空选项"旧行为，非逻辑 bug）；前端 node 测试跑法 `cd frontend && node --test tests/<file>.test.mjs`（7 个 invoice/aftersales 测试文件）**

23. ✅ **内贸订单管理**（2026-07-27 合入 main 并已上生产；需求稿 docs/requirements/2026-07-27-domestic-orders.md）：
    - 与外贸「生产订单 + 生产报工」**平行的一套**，不共用订单/产品/进度表——外贸报工是整行 0/1 流转，内贸要按数量拆批，进度表结构不同；只共用 `process` / `process_route` / `process_route_step` / `user_process_binding` 四类全局资产
    - 主站：下单（选属性 → find-or-create 产品 → 按「工艺→路线」映射自动配路线）、订单跟踪（逐明细逐工序数量进度）、产品与工艺映射、客户管理、流转卡与 30×20mm 二维码标签打印
    - 小程序：登录后落在模块选择页（外贸报工 / 内贸报工 / 订单速查），内贸报工并入 tabBar 第 2 项；扫码按数量报工可拆批，报工流水可撤销
    - Android PDA：`pda-reporting/` 原生客户端直接接扫描头（键盘模拟 + 常见广播），复用 `/api/auth/login` 与全部 `/api/mini/domestic/*` 后端；数量码确认/拆批、键盘逐件码可自动报 1 件（广播须确认），弱网/进程重启沿用持久化幂等号；仅连 HTTPS，不申请相机权限
    - 081/082 迁移，7 张表 + 报工幂等键；`domestic:read/write/admin` 权限
    - **上线后仍需人工配置**：角色管理页分配 `domestic:*` 权限 → 「产品与工艺」页配好「工艺→路线」映射 → 给内贸工人绑工序。**不配映射的单能下但开不了工**


## 待办事项（优先级递减）

### 安全（2026-07-18 PM 上线对抗性审查发现，均为既有架构问题，非 PM 引入）

- ✅ **frps 面板 7500 + 后端 8002 公网暴露已封（2026-07-18 iptables 解决）**：两端口经 `iptables ! -i lo -j DROP` 只允许 loopback（nginx 127.0.0.1、SSH 转发）访问，公网直连超时不可达；nginx→8002 走 lo 不受影响，实测主站/PM 全绿；**零重启零中断**（未动 frps/frpc/auth.token）。持久化 = `/usr/local/sbin/frp-fw-lockdown.sh`（幂等）+ `/etc/cron.d/frp-fw-lockdown`（@reboot 恢复 + 每 15 分钟重放）。详见 runbook「frps 端口封禁」节。
  - 剩余（已从 P0 降级——公网攻击面已消除）：①dashboard 弱口令与 `auth.token`（`Cola…2026!` 规律）仍是内网/纵深风险，换需改 `/opt/frp/frps.toml`，其中 `auth.token` 必须同步本地 frpc.toml 否则隧道断，择低峰一起做；②建议在腾讯云安全组也封 7500/8002 公网入站（云层纵深，防 iptables 被云镜 flush）；③启用 IP 维度限速前确认 XFF 信任链（8002 已封，公网伪造入口已堵）

### P0（关键，8 月展会倒排）

1. **展会试戴生图稳定性**（2026-07-07 更新：图像模型已接入并启用，单场景合成实测可用 ~130s，但上游拥堵时段仍会 >300s 被 ELBNT 网关 502/504）：持续观察成功率；不达标则评估自动重试或更换生图 Provider；继续 10 真人照 × 5 假发批量实测
2. ~~ELBNT 账号池 503~~（2026-07-07 已恢复，分析/话术/生图三 preset 均正常出活，留意复发）
3. **展会基建（2026-07-22 已就位）**：北京云展会实例 `http://154.8.205.162`（方舟全量，定时任务关闭防双跑，办公室实例不动）；16 款发型静态站+16 张品牌二维码落 `hair.leshine.work`（新加坡，certbot 自动续期，扫码验收通过）；leshine.cloud 当天遭未备案拦截弃用；**leshine.work 备案推进中**——批复后展会实例上正式域名（kiosk 相机原生可用），另备展会现场局域网直连兜底；展会后计划以北京机为基础全量迁移上云（素材库上 COS，评估记录见会话 2026-07-22）
4. **展会物料**（依赖市场部）：15~20 款短发多角度实拍图入发型库、6 个月对比素材、10+ 老客户证言
5. **稳定性止血收尾（代码侧已完成 2026-07-03）**：调度告警/回滚脚本/备份脚本已落地，剩服务器上三个动作——①编辑 `deploy\backup-uploads.bat` 的 BACKUP_ROOT 指向备份盘并注册 schtasks 计划任务；②下次部署后演练一次 `rollback.bat`；③角色管理页给相关角色分配新权限 `dingtalk:admin`
5. **展会夏季衣橱 + 反转镜头**（2026-07-18 开发，**2026-07-19 已合入 main 并推送**）：夏季着装提示词子句（换装/场景路径统一夏装、禁品牌 logo）+ kiosk 拍照页前/后置切换；剩余动作=部署 + 展会前真机实测（生图效果 + 前后置切换）

6. **展会试戴 2026-08-01 一轮改动（均已合入 main 并部署到北京云实例，剩现场实测）**：
   - **扫码上传照片**：客户扫拍摄页二维码用自己手机传相册照或现拍（签名 HMAC 令牌 10 分钟、无迁移无新表）。⚠️ **办公室生产实例的 `backend/.env` 缺 `EXPO_UPLOAD_SIGN_SECRET`**——不配则发码端点 fail-closed 返回 503（刻意设计），那台上该功能不可用，需补一条随机串（与云端用不同值）。
   - **合成版本三选一**（真实/柔光/美颜，085 迁移已执行）：客户在甄选页必选、默认真实。三版差别只在皮肤处理，用光是共有底座。
   - **水印去底 + 深色自适应**：底板与外发光全部废弃，素材本身也去了白底；落点深色时换纯白单色版。
   - **客户手机号 11 位归一校验**（前后端两处同源）。
   - **列表缩略图 + 素材缓存头**：`{stem}_thumb.jpg` 长边 400（实测封面 205MB→2.3MB、解码 65MP→4.4MP）；云端 nginx `/uploads/expo/` 加 30 天缓存、`results/` 刻意排除。**存量脚本 `python -m scripts.build_expo_thumbs` 尚未在办公室生产实例跑过**（不跑功能正常，只是不快）。
   - **两项现场实测未做，是最大残余未知**：①微信内置浏览器下的扫码上传（手机页 JS 只在桌面 Chrome 用 Playwright 验过 EXIF 旋转，而展会扫码几乎全走微信）；②三版出图差异是否肉眼可分——上一个出图档位选择器就是因为「看着有选择、实际没差别」被撤的，**三版分不出来就说明它还是个假选择**。

7. **业务员名片套件（2026-08-01 夜交付，086 迁移已执行，静态主页已上云）**：印刷 PDF 在 `scripts/card_suite/out/print/`（名片×4 双面 94×58 含 2mm 出血 + 海报 A1 含 3mm 出血）；`leshine.work/card/<slug>/` 四页已线上验证。剩余动作：
   - ①**生产 office 后端未部署**：`/api/card` 口令解锁与询盘要等 push + deploy.bat 后才通（静态主页不受影响，公开层照常打开）；main push 等亮哥指令。
   - ②WhatsApp 号 + 店铺/独立站链接到齐 → 改 `scripts/card_suite/data.json` → 重跑 `build_pages.py`（主页）与 `render_print.py`（如需名片上版）→ scp 上云。
   - ③FAQ 真实内容替换页面里的 SAMPLE 条目（改 `page_template.html` 或后续做成后台配置）；海报展位号手填或改模板重出。
   - ④角色管理页给相关角色分配 `card:read` / `card:write`（seed 已入，重启即出现在权限矩阵）。

### P1（重要）

-1. **OKKI 推单收尾**（开发侧 2026-07-13 全部完成：真实推单 + 幂等编辑 + 非标合并 + 企业必填字段 066/068，细节见 docs/module-notes.md invoice 节；首推真单曾被必填字段拒绝，字段已接线待重试）：
   - ①生产服务器 `backend/.env` 加 `OKKI_CLIENT_ID/SECRET` 后部署重启（deploy 不同步 .env）
   - ②运营配置三项：业务员 OKKI 部门（用户管理→编辑用户，Stella 建议「专治不服」——历史 676 单中 675 单归属它）；设置页配置**通用产品**（生产单推单必需，目前未配）；其余业务员绑定补齐
   - ③首推重试（INV20260710-001 已具备条件，差 Stella 部门）：**无沙箱产生真实订单**；推完人工核对订单总额/明细行数/业绩归属/cost_list 计入方式与「运费改 0 重推」语义
   - ④token 明文入库 vs 需求文档"加密"待拍板；代开票场景（业绩归属=创建人且无编辑入口）出现时需先补「指定业务员」能力

0.5 **展会试戴竖版全身入镜待决策**（2026-07-13）：拍照现为 1:1 中央裁剪，「多露身体」目前只靠取景椭圆上移 + 构图引导在方框内容纳肩颈上身；真竖版全身需改裁剪比例并回归 AI 合成管线（生成尺寸/模板受影响），等亮哥拍板再做

0. **对外库存查询后续**（2026-07-07 一期上线；**2026-08-19 二期完成**：`/inventory` 改为全公开免 key 英文查询站，列收敛为类型/尺寸/颜色/克重/有货标识，API 同步免 key 且不再出具体数量，`PUBLIC_STOCK_KEYS` 废弃）：①Shopify 主动推送（Webhook 回写客户店铺库存）待客户确认需求后排期；②观察是否需要限流


1. **补全测试覆盖**（2026-07-03 已补 122 个，剩余缺口）：
   - tracking 轮询编排逻辑（poll_single 状态推进；状态映射已覆盖）
   - insight 完整链路集成测试
   - stock 跨库 SQL 聚合（状态判定纯函数已覆盖，SQL 需真实 MySQL）
   - design router 端到端测试
   - 目标：覆盖率 70%+

2. **性能监控**：
   - 接入 APM（如 Sentry / 腾讯云 APM）
   - 数据库慢查询告警（>1s）
   - API 响应时间监控（P95 <500ms）

3. **文档完善**：
   - API 参数示例（Swagger 补充）
   - 错误码文档完整性检查
   - Runbook 故障排查流程图

### P2（次要）

1. **技术债务**：
   - ORM relationship 全局审查（lazy 策略）
   - 批量循环服务 import 检查（防静默失败）
   - 前端大页面拆分（>500 行的 .vue 文件）

2. **用户体验**：
   - 移动端全模块适配（当前仅素材管理 + 微信小程序）
   - 表格加载骨架屏
   - 操作反馈优化（loading 状态 + toast 提示）

3. **安全加固**：
   - API Key 定期轮换机制
   - 操作审计日志（敏感操作记录）
   - 登录失败限流

### P3（待定）

1. **功能扩展**：
   - WhatsApp 消息代发（当前仅查看）
   - 客户经营雷达 AI 自动刷新（当前手动触发）
   - 报表中心模板市场（预置常用模板）

2. **架构优化**：
   - 迁移到 Docker 部署（替代 NSSM）
   - Redis 缓存层（频繁查询的字典表）
   - 消息队列（异步任务解耦）

## 技术债务清单

| 债务项 | 影响范围 | 优先级 | 预计工时 |
|--------|----------|--------|----------|
| ORM relationship lazy 策略审查 | 全局（潜在 N+1 风险） | P1 | 2 天 |
| 测试覆盖（剩余：轮询编排/insight 链路/design e2e） | 回归测试信心 | P2 | 2 天 |
| 批量循环服务 import 检查 | folder_upload / 类似批量逻辑 | P2 | 1 天 |
| 前端大页面拆分 | 可维护性 | P2 | 3 天 |
| 移动端全模块适配 | 用户体验 | P2 | 10 天 |

## 已知问题（非阻塞）

0. **提成模块三个疑点**（2026-07-03 B-8 测试补齐时发现，测试已按现状固化，改行为前先改测试）：
   - `confirm_batch` 的明细 update 不带 `status != "voided"` 过滤，理论上会把曾作废的明细改回 confirmed（当前整批作废场景下影响面小）
   - `send_confirm` 中 `business_schema` 赋值后未使用（死代码）
   - 状态机允许 calculated 跳过 confirming 直接 confirm（现状即设计；若要求必须先发业务员确认需收紧）

1. **ACCIO 推送运单钉钉昵称不匹配**：暂存表 `dingtalk_user_name` 存中文昵称，与系统登录名不匹配，导致 `tracking:read` 用户看不到这类运单。建议：给提交人匹配加二级匹配 `dingtalk_user_id`。
2. **TFT 微服务依赖外部**：`TFT_SERVICE_ENABLED=false` 时走公式兜底，预测准确率下降。建议：TFT 服务稳定后默认开启。
3. **物流轮询频率固定**：每 3 小时轮询全部活跃运单，高峰期可能延迟。建议：按运单状态分级轮询（派送中 1h / 运输中 6h）。
4. **发票明细 schema 必填字段不拦空字符串**：`InvoiceItemPayload` 的 color/product_display 标必填但无 `min_length`，整行空值可过校验存库。2026-07-30 已在前端 Excel 导入路径移除预置空行堵住主入口，手工路径理论上仍可存出空行。建议：补 `min_length=1`，动手前先核查存量数据无空值行，避免老单编辑保存被新校验拦住。

## 运维交接

### 关键配置文件

| 文件 | 位置 | 说明 |
|------|------|------|
| 后端环境变量 | `backend/.env` | 数据库/JWT/钉钉/微信/WhatsApp 配置 |
| 云端 Nginx | `/etc/nginx/conf.d/leshine.conf` | 静态直出 + API 反代 |
| NSSM 服务配置 | NSSM 注册表 | `nssm edit CommissionSystem` 查看 |
| frp 内网穿透 | 本地 Windows 服务 `frpc`（C:rprpc-service.exe）+ 云端 systemd frps | 云端 `/opt/frp/frps.toml`（:7000，Dashboard :7500）；本地 frpc 代理 ark-backend(:8002)+n8n(:5678)，详见 runbook「配置内网穿透」 |

### 定期维护（建议频率）

| 任务 | 频率 | 负责人 |
|------|------|--------|
| 数据库备份验证 | 每月 | 运维 |
| uploads/素材盘备份日志抽查（.deploy_state\backup.log） | 每月 | 运维 |
| SSL 证书续期 | 每 60 天 | 运维 |
| API Key 轮换 | 每季度 | 技术负责人 |
| 日志清理 | 每月 | 运维 |
| 依赖安全更新 | 每季度 | 后端开发 |
| 性能报告 | 每季度 | 技术负责人 |

### 紧急联系

- **服务器宕机**：重启 NSSM 服务（`nssm restart CommissionSystem`）
- **数据库连接失败**：检查腾讯云 RDS 白名单 + 密码
- **前端白屏**：检查云端静态文件 + frp 穿透（本地 `Get-Service frpc`）
- **定时任务未执行**：检查 `SCHEDULER_ENABLED` + 查看日志

## 团队能力要求

### 后端开发

- **必需**：Python 3.10+ / FastAPI / SQLAlchemy 2.0
- **次要**：Alembic 迁移 / APScheduler / colour-science
- **业务**：提成计算逻辑 / 物流轮询 / AI 接入

### 前端开发

- **必需**：Vue 3 Composition API / Element Plus / Vite
- **次要**：Pinia / Vue Router / Axios
- **业务**：RBAC 权限控制 / 表格排序分页 / 移动端适配

### 运维

- **必需**：Windows Server / NSSM / Nginx / frp / SSH
- **次要**：腾讯云 RDS / Let's Encrypt SSL
- **业务**：双服务托管 / frp 穿透 / 前端 dist 同步

## 文档清单

| 文档 | 状态 | 说明 |
|------|------|------|
| [architecture.md](architecture.md) | ✅ | 系统架构、数据库表结构、核心模块说明 |
| [api-reference.md](api-reference.md) | ✅ | 全模块 API 端点清单（自 CLAUDE.md 拆出，新端点同步更新） |
| [database.md](database.md) | ✅ | 数据库表结构清单（自 CLAUDE.md 拆出，新表同步更新） |
| [module-notes.md](module-notes.md) | ✅ | 模块专题笔记 + 各模块已踩坑（钉钉/报表/OCR/洞见管线等） |
| [integration-guide.md](integration-guide.md) | ✅ | API 接入指南、认证方式、错误码、示例代码 |
| [runbook.md](runbook.md) | ✅ | 部署步骤、运维命令、故障排查、环境变量清单 |
| [handoff.md](handoff.md) | ✅ | 项目状态、已完成功能、待办清单、技术债务 |
| [accio-work-integration-spec.md](accio-work-integration-spec.md) | ✅ | ACCIO WORK 集成规范（客户机会台） |
| [requirements/2026-06-16-whatsapp-connector-contract.md](requirements/2026-06-16-whatsapp-connector-contract.md) | ✅ | WhatsApp Connector 契约 |
| [requirements/2026-07-02-order-invoice-management.md](requirements/2026-07-02-order-invoice-management.md) | ✅ | 订单发票管理需求文档 |
| [requirements/2026-07-03-expo-ai-wig-tryon.md](requirements/2026-07-03-expo-ai-wig-tryon.md) | ✅ | 展会 AI 试戴设计开发文档（配套原型以品牌绿版 v2 为准） |
| [requirements/2026-07-03-permission-redesign.md](requirements/2026-07-03-permission-redesign.md) | ✅ | 角色权限重设计方案（2026-07-03 已实施：046 迁移+矩阵 UI+审计） |
| [requirements/2026-07-07-invoice-order-pricing-okki-v2.md](requirements/2026-07-07-invoice-order-pricing-okki-v2.md) | ✅ | 发票 V2：双类型/价格矩阵/OKKI 推单设计（决策 D1-D4） |
| [requirements/2026-07-12-permission-refinement.md](requirements/2026-07-12-permission-refinement.md) | ✅ | 权限细化与逐页页面码方案（061/063/064 已实施） |
| [requirements/2026-07-17-training-digest.md](requirements/2026-07-17-training-digest.md) | ✅ | 培训速递需求（075/077 已实施） |
| [requirements/2026-07-17-pm-material-hub.md](requirements/2026-07-17-pm-material-hub.md) | ✅ | PM 资料协作站设计稿（076 已实施） |
| [requirements/2026-07-21-salary-module.md](requirements/2026-07-21-salary-module.md) | 📝 | 薪资计算模块设计草案（**未开工**，12 个开放问题待拍板，2026-03 工资表复算为验收标准） |
| [requirements/2026-07-22-asset-tag-taxonomy.md](requirements/2026-07-22-asset-tag-taxonomy.md) | ✅ | 素材标签体系 v2 重构方案（078 已实施并完成切换/退役） |
| [requirements/2026-07-10-customer-after-sales-management.md](requirements/2026-07-10-customer-after-sales-management.md) | 📝 | 客户售后管理需求 + 实施计划（模块笔记见 module-notes 售后节） |
| [mcp-tracking-integration.md](mcp-tracking-integration.md) | ✅ | 方舟 MCP 网关接入说明：物流 3 工具（051）+ 素材 2 工具（2026-07-22） |
| [social-customer-mcp.md](social-customer-mcp.md) | ✅ | 社媒客户查询 MCP（云端独立服务，与方舟网关不是同一套） |
| [codex-social-customer-mcp-auto-setup.md](codex-social-customer-mcp-auto-setup.md) | ✅ | Windows/macOS Codex 自动接入社媒客户 MCP |
| [expo-kiosk-tablet-setup.md](expo-kiosk-tablet-setup.md) | ✅ | 展会 kiosk 平板现场配置 |
| [README.md](README.md) | ✅ | docs 目录导航（按读者角色分流） |
| [2026-07-03-architecture-assessment.md](2026-07-03-architecture-assessment.md) | ✅ | 平台架构评估与改进路线图（问题清单 + 四批实施计划） |
| [2026-07-08-db-naming-assessment.md](2026-07-08-db-naming-assessment.md) | ✅ | 数据库命名评估（命名宪法依据） |
| [../CLAUDE.md](../CLAUDE.md) | ✅ | AI 协作说明（项目根目录） |
| [../README.md](../README.md) | ✅ | 项目简介、快速开始、技术栈 |

## 交接确认清单

- [ ] 服务器账号密码交接（Windows Server / 腾讯云 RDS / 腾讯云 SSH）
- [ ] `.env` 文件交接（数据库密码 / JWT 密钥 / API Key）
- [ ] Git 仓库权限开通
- [ ] 钉钉企业内部应用管理员权限
- [ ] 微信小程序管理员权限
- [ ] 腾讯云账号（RDS / SSL 证书 / Nginx 服务器）
- [ ] ACCIO WORK 联系人交接
- [ ] WhatsApp Connector 维护交接
- [ ] 运维手册现场演示（部署 / 重启 / 故障排查）
- [ ] 代码结构讲解（后端领域模块 / 前端组织方式）
- [ ] 定时任务机制讲解（APScheduler 11 个 job）

## 备注

- 项目记忆已切换为“claude-mem 单机捕获 + Mem0 跨 Agent/跨机器精选共享”；旧 `.wolf` 文件仅作历史只读材料，退役 hooks 不得复挂。代码走 Git、进度走本文件、为什么/怎么做走 Mem0。
- CLAUDE.md 已瘦身为 ~110 行宪法；API 清单在 `docs/api-reference.md`、表结构在 `docs/database.md`、模块专题在 `docs/module-notes.md`
- 完工前跑 `python scripts/check_conventions.py`（增量约定检查，红=必须修）
- 所有 UI 决策以 `DESIGN.md` 为准
- 新增权限需修改 `seed_role_permissions()` 并重启后端
- 数据库变更必须通过 Alembic migration
- 生产环境 `.env` 强校验（见 `config.py` 的 `_validate_production`）

---

**交接人**：亮哥  
**交接日期**：待定  
**接手人**：待定
## 2026-09-09 DHL 刷新鉴权排查（代码已集成，线上凭据待核实）

分支 `codex/tracking-auth`。用户报刷新返回 DHL 原始 Unauthorized JSON。本机 Settings 中 DHL 凭据已填写、无首尾空格、环境为 production；使用占位运单号做只读查询，test/prod 均返回 HTTP 401。尚未核验线上实例配置，不能认定凭据已过期或已撤销；需 DHL 负责人核实有效凭据与接口访问权限，线上恢复仍未完成。

补丁将 DHL 401/403 转为明确中文提示，保留环境及安全格式的 msgId；刷新服务商失败改为信封业务码 502，缺失运单仍为 404，准确区分运单不存在与服务商查询失败。独立审查无阻塞，约定检查通过，Git 巡检基于本地快照。新增回归先失败后通过，相关测试 77 passed，均无生产库写入。目录整理时将补丁集成至本地 main，6项定向回归通过；未改凭据、未推送、未部署。

## 2026-09-14 迁移 149 超长编号故障修复（合并交付，待生产恢复）

分支 `codex/migration-149-recovery`，基点 `15dcd7a9`。生产用户提供 `.deploy_state/schema-writers.json`：原始147→148→旧149，`failed-after-ddl`，办公室 CommissionSystem/WhatsAppConnector、北京 ark-backend、新加坡 shipment-tracking-mcp 原本运行且均记录为 stopped。当前服务状态尚待服务器确认。

本轮通过现有配置只读查询共享库：版本为148；149的三个列（reviewed_by unsigned int nullable、reviewed_at datetime nullable、review_remark varchar500 nullable）与 reviewed_by→ark_users.id 外键全部存在；版本列为 varchar32。旧 revision `149_domestic_order_review_columns` 长33，是 DDL落地但版本写入失败的根因。未执行生产DDL/DML、未修改恢复记录、未启停服务。

迁移编号缩短为 `149_dom_order_review_columns`；兼容已有结构则复用，仅补缺项，异常结构拒绝，不stamp。新增仅针对该事故的 `--recover-migration-149 --revision <full-sha>` 发布参数，保留原始运行基线，核验DB148/新149及四个writer清单，准备模式只读验证，正式恢复沿统一DB锁/Alembic/应用激活/健康验证链路，成功才关闭journal。重试即使DB已到新149仍恢复完整发布；失败不重启旧代码。使用方法与脚本更新前提见 deploy/README.md。

验证：部署测试80 passed、11项Linux文件系统测试在Windows跳过；迁移隔离测试34 passed；实库`validate_existing(require_complete=True)`只读验证通过；独立审查无阻断项，补了提交后重读版本、当前148/新149完整性、prepare-only和固定候选测试。项目约定全量检查仍被4项无关UI旧债阻挡，增量代码检查无违规；git diff --check通过，git_sweep --no-fetch已执行（远端仅本地引用快照）。用户已授权将本次修复合并 main 并推送 origin；fetch 确认 main 与 origin/main 均为基点15dcd7a9，无上游差异。本轮不执行生产恢复，服务状态仍需服务器核验。
## 2026-09-14 库存色块工作台同源集成（合并交付，未部署）

分支 `codex/colorwork-entry-fix`，目录 `D:/MyProgram/commission-system-codex-colorwork-entry-fix`。用户明确改为方舟内部使用、不要独立域名。此前北京只读核实工作台 URL/密钥未设、8787 无监听，主站部署未包括工作台；本轮又核实服务账号 PATH 无 Node。现改为固定相对 SSO URL `/api/colorwork/workbench/api/auth/ark`，所有 HTML/JS/CSS/API/文件经方舟后端流式同源代理；不转发主站 Bearer 与其他 Cookie，保留逐视图鉴权，Cookie 限定模块路径。

工作台保留 React/vinext 与 D1/R2 格式，basePath、浏览器 fetch、图片/Canvas/PSD、下载与退出均补同源路径；不改已有持久 URL 和库存计算。独立域名 Nginx/systemd 旧模板删除。统一 deploy.bat 的北京后端流程纳管内部服务 ark-colorwork，自动下载并校验固定 Node v22.23.2、锁定 pnpm，准备期使用隔离 D1，激活先停服务、每次独立备份 D1/R2 再迁移，readiness 后记成功。同 SHA 重跑校验制品并跳过在用配置写入/成功激活；未知或改写迁移、旧数据待迁移、失败记录均阻断。SSO 与回源密钥分别派生，运行服务不持主站原始 JWT 密钥。

验证：后端 SSO/代理/权限 19 passed，发布回归 90 passed / 11 skipped（现有 Linux 专属静态发布用例在 Windows 跳过），Node URL 单测 2 passed；工作台 pnpm lint/build 通过。真实隔离 workerd + FastAPI 代理实测三个 SSO 视图、两种尾斜杠刷新、登录退出、全部引用的 JS/CSS、无权限403；浏览器确认 master 首次导入页与普通账号首次设置页，同源会话保持正常。输出在 `.deploy_state/colorwork-test/results.json`，不连接生产库；测试服务与浏览器已关闭。自动审批以 blocked by policy 拒绝临时目录清理，隔离测试 SQLite/R2 和仅含测试密钥的 .dev.vars 保留，未进入 Git。真实素材包不在仓库，成品生成和真实素材下载仍需导入后验收。独立审查发现的 Cookie 边界、流中断清理、激活迁移复核及旧候选回退备份均修复并有回归。

项目完整约定检查仍阻于四项现有 UI 基线：AssetTagEditor small 按钮、AssetLibrary / ProductionOrderManage / AIManager 行数；包含新增文件的增量检查无违规，diff 格式检查通过。Git 巡检为 --no-fetch 本地快照。2026-09-15 用户授权合并 main 并推送 origin；集成前 fetch 确认 main 与 origin/main 均为 a8283637，无上游差异。本轮不部署。北京运行环境安装与 systemd 激活尚未在真实生产执行；素材与 D1/R2 唯一数据归属北京，不为办公室另建数据副本。完整接入及恢复规则见 `colorwork-workbench/README.md`。
## 2026-09-15 共用手机发货质检网页（本地开发完成）

工作目录 `commission-system-codex-shipping-station`，分支 `codex/shipping-shared-phone`，基点 `7efe0cf0`。本轮按“开始开发”实现已批准方案，保留本地 diff；未合并推送、创建专用账号、授予生产权限、执行生产迁移或部署。主目录其他任务的修改未触碰。

- 独立 HTTPS `/shipping/scan` 全屏页，保持主站登录返回路径。发货质检名单替代示例图，每单必须主动选人；姓名大字、短金色发光、选择勾选、扫描按钮实名、顶部固定身份卡；320px 窄屏及减少动画模式已检查。每单提交或结束后清空选择。
- 服务端会话绑定登录人、实际操作人和出库单，业务媒体/提交归属所选人，登录账号仅鉴权和审计。现场只读核验角色 28 / fhqc（发货质检，17 名成员），候选实时过滤停用/删除账号并排除登录账号。新增 `shipping_station:write` 权限但未对生产账号授权。上传前后检查角色，防止上传过程中撤销权限后继续落业务记录。
- 复用现有检验服务、照片/视频和撤回版本；扫码只记事件，不制造空检验单。session 请求幂等；不确定提交保留原请求并锁定编辑，明确版本拒绝释放待确认状态允许刷新。PC 详情可折叠查看最近 200 条审计，一般用户只见业务操作人，管理员另见登录账号。
- 迁移 153 接续 152，新增会话/审计表，支持中断重入、结构校验、禁止删除历史式降级；离线唯一 head 为 153。专用上传部署入口增加 station 照片 21m、视频 101m 代理路由；环境配置、API、数据库及部署文档已同步。

验证证据在本目录 `tmp/station-*`：受影响后端隔离库回归、前端/小程序 40 项相关测试、部署路由与真实迁移计划 25 项均通过，主站最终构建通过（既有大包警告）。实际 Vue 组件在模拟 API/人员/相机下，通过 jsQR 识别测试二维码，完成选人→扫码→照片上传→提交清空→另一人扫描只读预览；390px/320px 无横向溢出、减少动画模式有效、控制台无错误。独立审查问题均修复，确定性提交拒绝补回归。尚未进行物理手机扫码/相册视频与生产 MySQL 双连接并发验收。

约定检查增量无红黄项；默认门禁仍报告 4 项已有 UI 基线问题（AssetTagEditor 小按钮以及 AssetLibrary / ProductionOrderManage / AIManager 行数基线），未修改无关文件。Git 巡检已运行 `--no-fetch`，仅代表本地快照。未清理其他代理分支/工作区。

# 展会美颜部署入口恢复（2026-09-16）

生产安装目录仍为 520c22ca，9/15 18:46 发布候选 7efe0cf0 失败且 completed 为空。只读实测数据库仍为 150，美颜版本表及146/152新增列均不存在；schema-writers 为 restored-before-ddl，writers/stopped 为空。根因为父部署进程继续加载安装目录旧 remote_backend.schema_check（未启用 implicit_base），候选 migration_runner 已修复，计划分别是 [152] 与 [146_expo,152]。候选的真实 Alembic 升级计划与新预检一致。

分支 codex/deploy-candidate-runtime 基于当次已审查候选7efe，只新增部署器 --live-root 启动支持、测试与说明，不纳入后来151/153业务迁移。允许从受管固定候选调用原 deploy.bat，部署模块统一取候选，安装目录/状态/锁/服务/DBA保护保持原归属。无生产迁移、业务切换或 origin 写入；生产发布由亮哥执行。验证及服务器候选准备结果见本任务交付说明。


### 2026-09-17 · 9月新签加入钉钉日报与截图

任务分支 `codex/september-dingtalk`，基点 `f95a9076`。每日采购节战报加入9月业务部113目标、八组完成情况、第一团队及并列/待复核状态，不显示奖金；旧新签数据标明8月。截图增加9月频道，并校验模块页面身份、有效数据和全部团队LOGO就绪。沿用原发送时间、专用群、幂等和重试，不触发额外发送。截图和月进度均标明取数时间，补发不冒充历史日终快照。

验证：相关后端58项、前端7项测试通过；前端生产构建及独立契约审查通过；实际Chrome运行生产截图命令，完成9月截图并验证嘉树LOGO缺失会阻止发送。浏览器使用本地模拟接口和历史快照测试数据，不连接生产库或发送真实钉钉消息。证据保留任务目录 `tmp/september-dingtalk/`。约定检查受11项既有UI债务阻挡，增量约定检查无违规；Git巡检为 `--no-fetch` 本地快照。亮哥已授权合并并推送 origin/main，本轮不部署。


## 2026-09-17 公告管理实现（codex/announcements）

本地开发与验证完成；用户已授权合并 main 并推送 origin。本轮不部署、不发送真实钉钉消息。

实现独立列表/编辑审核/撤回/置顶、知识库目录和修订映射、私有图片推送 outbox、管理员投递核实、周一定时 AI 周报和手动预览。迁移 155_announcements，复用知识库并阻止从知识库绕过公告发布。独立审查发现的旧快照、失效租约、草稿标题泄露、切群纠错、历史投递结案、恢复覆盖和队列饥饿问题均修复并回归。

验证详情与启用步骤见 docs/reports/2026-09-17-announcement-implementation.md。尚未执行真实 MySQL 迁移和钉钉通道测试；上线前需按项目发布流程完成。UI 门禁有 11 项已有失败，以及本次共享编辑器/工作台集成新增的 2 项行数阈值提示（503/502 行），未改基线或机械拆分掩盖。

## 2026-09-17 原始库存图源文件规则优化

任务分支 `codex/colorwork-source-rules`，基于线上 `80996982` 准备仅含本任务改动的发布候选。新版 PSD/JPG 相互等尺寸但可改变 S1；服务端读取 PSD 头核对实际宽高，缩放旧动态区域仅作参考。S1 长度集合不随新版扩展，候选异常长度提示并由启用接口硬校验；新色号提取候选色块且必须人工确认。结构合成问题合并，装饰越界不作为业务色块，明确色号越界仍阻止。删除尺寸也列入 removed；历史库存/母版/导出保留，未人工启用时继续 S1。

已验证：真实浏览器解析专项、隔离 D1/R2 接口场景 13 项（包括历史状态保留及回退、旧成品摘要不变、尺寸伪造/越界拒绝、服务端生成新颜色/超长提醒、勾选不能绕过长度校验）、类型检查与构建。独立审查发现 Decorative 1 装饰名误判，已修正并补回归。本次变更文件 lint 通过；全量 lint 有 10 项其他文件已有问题，项目约定检查有 11 项主站已有 UI 债务，未扩大修改。未操作任何线上源 Sx 启用。

发布：经 `deploy/deploy.bat --cloud-only --no-pull --revision ba475d55af2ae6371b15899db42751cc3605b32f`（先 prepare-only）完成。发布日志和北京 colorwork/current.json 均 succeeded；主站后端 changed=false、schema_changed=false，其他静态站零变化。两个公网入口健康200。前后只读摘要一致：23套当前源仍全为S1，869条inventory_states、23个master_versions和1个artifact未变；验证证据在任务 worktree 的 colorwork-workbench/outputs。独立复核已通过装饰修复。发布基点上的约定检查为10项已有主站UI债务，直接增量 check(80996982) 无违规。

用户已授权合并 main 并推送 origin，本轮整合仅同步已发布修复，不重复发布站点。两个本地隔离测试目录 .wrangler/source-rules-test 和 source-rules-final 的清理被自动审批以 blocked by policy 拒绝，未绕过；保留测试目录及发布恢复材料，不影响生产。
