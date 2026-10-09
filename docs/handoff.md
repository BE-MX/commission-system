# 当前交接与待办

## 2026-10-09 订单发票日常钉钉喜报（Codex，已授权合并推送部署）

- 工作树 `C:/Users/windb/.codex/worktrees/daily-invoice-notifications/commission-system`，分支 `codex/daily-invoice-notifications`，基于 main `7c233166`。新签、下单、大单来袭、超级大单改为日常全年推送，沿用成功同步小满后的触发口径、现有独立群机器人和一分钟调度；活动外不依赖采购节大屏聚合及参赛名册。
- 首次启用只建历史基线，按固定发票 ID 分片防止 MySQL TEXT 超限；旧草稿后来同步成功仍生成一次事件。新签标记为空时读取成功推单中实际发送的业务标记，当前推单执行器仅在成功审计摘要补存该标记，未增加完整请求或敏感内容。新签与下单互斥，大单 USD ≥5,000、超级大单 ≥30,000，金额扣手续费；金额档位互斥，命中订单另有基本喜报。
- 图片与消息改为“方舟订单”；取消中、已取消及未同步成功的发票排除。共用原采购节新签/大单幂等键，编辑重推不重复；采购节首单红包、榜单、目标及17:00日报保留原规则。无数据库迁移、无前端或权限变更。
- 独立 agent 发现的基线容量与当前执行器 NULL 新签证据两个 P2 均已修复并复核，无新增 P1/P2。隔离 SQLite 和模拟钉钉覆盖首启、全年/跨年、阈值扣费、延迟同步、取消、原事件去重、基线分片和真实成功 apply 路径；未连接共享业务库或真实发送群消息。Git 巡检 `--no-fetch` 仅为本地快照。
- 卡片效果已落为动态模板：浅香槟金磨砂玻璃、宽渐变光晕、右侧星光和透明外部；真实采购节头像、业务员姓名、国家/客户名称、金额与日期动态覆盖，不把样例订单或姓名烘焙进底板。名字下方不显示订单号；非美元原币展示，长客户名两行省略。
- 最终验证：日常订单、采购节通知/榜单/状态事件、运行中心和调度注册回归 162 passed；增量约定检查与 `git diff --check` 通过。既有调度测试结束时产生默认本机数据库不可连接的 `staging_scan` 观测日志，测试进程正常退出（exit 0）；隔离测试未运行生产迁移或真实业务任务。动态模板与国家/客户 overlay 契约独立复核无新增 P1/P2；亮哥本轮已授权合并、推送并通过统一入口部署，实际发布结果随后补记。

## 2026-10-09 快速创建任务底部按钮遮挡修复（Codex，已合并推送，未部署）

- 独立 worktree `C:/Users/windb/.codex/worktrees/quick-task-footer/commission-system`，分支 `codex/quick-task-footer`，基于 main `7852719f`；修复提交 `ca5c71ac` 已整合最新 main 后合并推送至 `origin/main`；未部署，主目录原有24项改动保留。
- `QuickTaskPopover.vue` 原按 540px 预估高度定位，却以整个视口设置最大高度，AI 补全后长表单超出屏幕。改为扣除实际 top 和底部留白，显式 border-box；仅正文滚动，页头和创建/重新补全按钮保留，窄屏按钮换行，打开期间随窗口 resize 重新夹定位置。
- 真实 Vue/Element Plus 组件加模拟任务 API 的浏览器验证通过：1440×900、1366×768、1024×600、390×844、390×480、320×568 共六种尺寸，22 组边界检查；覆盖长提醒、重复任务提示、10 条长验收标准、正文滚动、打开时缩小窗口、重新补全、侧栏/页头/居中入口、Ctrl+Enter、Escape 焦点恢复、编辑验收后创建与直接创建。10 次补全、7 次创建均为拦截模拟，无真实 AI 或业务写入，浏览器无运行异常。
- 修复前 900px 高窗口中 footer 底边为 1320px；修复后为 867px，短屏 390×480 中为 447px。生产构建、任务/导航 17 项 Node 测试、增量约定与 diff 检查通过；Git 巡检为 `--no-fetch` 本地快照。浏览器脚本、夹具、测量 JSON 与截图在合并后保存至主目录 `tmp/quick-task-footer-evidence/`，临时工作树在核验整合后清理。

## 2026-10-09 订单发票删除权限独立（Codex，已验收，未部署）

- 工作树 `C:/Users/windb/.codex/worktrees/invoice-delete-permission/commission-system`，分支 `codex/invoice-delete-permission`，基于 main `6bbcabff`；亮哥已授权合并并推送 origin/main，本轮不部署，主目录原有改动单独保护。
- 新增 `invoice:delete`（删除订单发票及关联单据，action 权限），草稿 DELETE、关联删除预览/执行及列表按钮统一要求此权限；旧 lifecycle.remove 在管理权限之外另需删除权，取证前后均检查当前数据库授权。关联删除向服务传当前 principal，不透传 JWT 中已撤销的下游权限。订单/出库/回款范围及下游操作权限不变。
- 启动 seed upsert 登记新权限，不自动从 write/admin 继承、不自动补给普通 admin，已明确授予的链接保留；super_admin 仍按现有规则绕过。需前后端一起发布，角色管理“订单发票 → 删除”明确分配后重新登录。不新增表结构或迁移。
- 验证：隔离 SQLite 后端 117 passed，前端删除/权限矩阵/权限治理 18 passed，生产构建、增量约定检查与 diff 检查通过；独立 agent 审查无新增 P1/P2。MySQL 专用套件因未提供独立 mysqld 配置 45 skipped；既有 invoiceLifecycle.test.mjs 两项缺 useAuthStore 测试桩，在未修改主目录同样失败，未纳入通过数。git_sweep --no-fetch 已执行，仅为本地快照。
- 当前接口参考、单据生命周期、外部发票接入文档和门户契约已同步；历史设计稿/归档保持历史记录。

## 2026-10-09 内贸经营决策台经营口径优化（Codex，已合并推送，未部署）

- 独立工作树 `C:/Users/windb/.codex/worktrees/domestic-decision-metrics/commission-system`，分支 `codex/domestic-decision-metrics`，基点 `7852719f`。功能提交 `46cfdf46`、集成提交 `8be4a8ec` 已合并并推送 `origin/main`；未部署。主目录原有24项未提交内容逐项核验保留。
- 经营总览采用业务下单金额、按有效报工时间的发货出库金额、实际客户充值金额、去重下单客户个数。客户页新增充值/非充值四指标、行为意向证据、持续复购与流失线索；产品页新增商业持续出货观察、毛坯供需/整行入库周期与在制积压。
- 亮哥确认缺成本先显示“缺成本，待核算”；真实库存未知，期间供需差不当作库存余额。无客户生产单要求全量查询及两个域全量权限；报工/价格/充值来源参与快照版本，旧指标快照要求重算。
- 整合最新主线后，后端隔离回归111项、前端11项、构建、严格增量约定、diff检查和独立接缝审查再次通过。桌面/手机、报工与折让原始证据下钻已在合成数据隔离服务核验；临时服务及SQLite已清理。Git巡检仅 `--no-fetch` 本地快照。详见[验收记录](reports/2026-10-09-domestic-decision-metrics.md)。

## 2026-10-09 用户管理账号解锁（Codex，已授权合并推送，未部署）

- 工作树 `C:/Users/windb/.codex/worktrees/account-unlock/commission-system`，分支 `codex/account-unlock`。用户管理新增“登录锁定”状态和 `user:write` 控制的“解锁账号”入口；密码、角色和启用状态不变。
- 迁移 `178_account_unlock` 新增解锁审计表，原登录日志不改；解锁后的新失败继续计数，登录和解锁在目标账号行锁下串行化。本次交付目标为 `origin/main`，用户已授权提交、合并和推送；不部署或升级生产数据库。
- 初次后端及时间测试 25 项、9 类模拟浏览器交互通过；整合远端门户后，解锁/时间/门户上游 46 项测试与前端构建通过，补齐实时权限检查并修复两处远端既有构建错误。额外 78 项前端旧 mock 基线失败已记录；独立审查及增量约定检查通过，迁移单 head，Git 巡检仅本地快照。没有隔离 MySQL 双连接实测，具体证据与上线前条件见[验收记录](reports/2026-10-09-account-unlock.md)。

## 2026-10-08 客户下单门户合并推送（Kimi 执行，已授权）

- 亮哥决定：客户下单门户功能边界止于生成方舟正式 PI，回款/出库/履约由方舟既有模块处理；随后授权合并推送。门户全部成果以未提交状态保存在 `codex/customer-portal-dev-docs` worktree，本次经 `kimi/customer-order-portal-merge`（基点 `54f77438`，提交见 git log）合并入 main 并推送 origin；原 codex worktree 未做任何 git 写操作，其工作区原样保留。
- 迁移撞号处理：门户迁移原编号 172/173 与 main 的 `172_workbench_lifecycle`/`173_task_center` 冲突，按 AGENTS.md 迁移规则重编号；推送前 main 又落地 `175_receipt_recovery`，最终定为 `176_customer_order_portal`（父 `175_receipt_recovery`）与 `177_portal_pi_header`（父 176），代码/测试/文档引用同步更新；下方门户专题记录中历史上的"172/173"均指重编号前的门户迁移文件。
- 范围剥离（专题契约 v1.73）：门户建票不再创建 ReceiptIntent 草稿（`create_invoice` 对 `source_type="portal"` 跳过 `save_draft(new=True)`），回款完全复用方舟既有发票→回款入口；价格写屏障保留但不向回款/出库 writer 扩展；全 writer 协议、回款内核接线、出库执行器切换与发布围栏划入独立加固专项，不阻断门户上线。
- 合并冲突 22 个文件全部人工解决：receipt/service.py 保留门户当前授权架构并迁入 main 已发布的回款修正（invoice_summary 端点、auto 回款编辑费用重算、_receipt_basis 复核、附件顺序保留）；main.py 保留门户 ExitStack 生命周期并补回 main 的 seed_task_modules；ownership_service 同时保留客户转移时的门户访问暂停与工作项委派阻断；前端 7 个文件保留 main 设计体系并叠加门户入口。
- 合并后验证（隔离 worktree 干净检出，无 backend/.env）：后端全量（排除本机缺 mcp/jinja2 依赖的 19 个收集错误模块与需专用 mysqld 的 portal_mysql）7297 passed / 46 failed / 7 errors——失败集是 origin/main(`3c81d687`) 基线的严格子集（无新增失败；另修复了基线自带的 test_start_scheduler_registers_jobs 期望集），错误集与基线逐项一致；门户 SQLite 套件 718 passed / 2 skipped / 0 failed；回款修正、发票生命周期/删除/委派/配件/关联同步等相关套件 189 passed；alembic 单 head `177_portal_pi_header`；`check_conventions --base` 增量无违规（UI 门禁 80 项已清零）。门户 MySQL 套件（ReceiptIntent 断言已同步新边界）与前端双端构建因本机无 mysqld/node 未执行，发布前须在有专用 mysqld 与 Node 的环境补跑。
- 门户开关 PORTAL_ENABLED/PORTAL_WRITES_ENABLED/PORTAL_INVOICE_ENABLED 全部默认关闭，本次不部署。

## 2026-10-09 订单详情加载优化（Codex，已合并推送部署）

- 本次应用候选 `9bdbc5f3d2c0389b8ebaf2a6c00e46ef50a6a1ec` 已合入并推送 main，经办公室 `deploy/deploy.bat` 先预检后发布，两次退出 0；范围 `office-and-cloud`，release_id=`61ca506f06e440b8bbc513ddecf27e66`，deferred=[]。
- 两地版本与健康正常，20 项公网前端制品和 8 个详情后端文件按候选摘要核验一致；数据库保持 `175_receipt_recovery`，无迁移。出库 timer 原 active/enabled 与邮件 Worker inactive/disabled 基线保留。
- 合并同时保留主线 `019e1471` 当前状态异常判断及问题单据入口；合并候选后端 229 项、前端 12 项与构建通过，独立合并审查通过。原主目录 24 项改动已保留。详细证据见[发布记录](reports/2026-10-09-invoice-detail-speed-release.md)。下方 10 月 8 日未部署段落为当时阶段记录，已由本次发布完成。

## 2026-10-08 订单详情加载优化（Codex，本地完成，未部署）

- 工作树 `C:/Users/windb/.codex/worktrees/invoice-detail-speed/commission-system`，分支 `codex/invoice-detail-speed`，基于 main `3c81d687`；改动尚未提交、合并、推送或部署。
- 初次打开回款读取两分钟内已核验后台快照，明确展示时点；手动刷新保留严格实时核验。出库精确读取本地镜像并批量取检验/事件/预售关联状态。刷新保留明细并隐藏旧汇总。
- 按用户新口径，有效检验提交完成即计入已出库；撤回、待补验、同步未确认、镜像与修改证据冲突、越权、重复或超量均有保护。不变更原单状态、资金写入或数据库结构。
- 受影响后端 219 项通过；补充运费边界后详情 47 项全部通过。前端 3 项、构建、独立审查及隔离浏览器首屏/刷新路径已验证。具体证据与限制见[优化验收记录](reports/2026-10-08-invoice-detail-speed.md)。主目录其他代理改动保持不动。

## 2026-10-08 单据叹号只按当前状态判断（Codex，已验收，授权合并推送，未部署）

- 分支 `codex/outbound-anomaly-details`，独立工作树 `C:/Users/windb/.codex/worktrees/outbound-anomaly-details/commission-system`。按亮哥最终口径：订单只判当前 `Invoice.status`；回款只判有效回款当前 `sync_status`；出库与列表共用 `outbound_state` 和正常单据替代待生成条目的规则。历史失败记录、独立同步旧字段、发货结算和应收目标不再额外触发叹号；不调用小满接口，不修改业务状态。
- 出库叹号及页面“问题单据”可打开当前异常清单，显示单号、客户及状态，并跳转定位；重复定位清除冲突筛选，末页数量缩减自动回退，接口失败保留过期提示，账号权限变化清空。出库清单与导航共用同一查询及权限条件。
- 验证：后端关联详情与出库队列共67项隔离回归、前端17项回归、生产构建、增量约定及diff检查通过。独立审查通过；本地浏览器使用合成数据验证异常条目、跳转参数及正常空状态。Git巡检为 `--no-fetch` 本地快照；亮哥已授权提交、合并及推送 `origin/main`，本次不部署。
- 排查时曾把旧自动出库任务和失败操作记录误报成当前出库异常，已向亮哥纠正；最终方案只使用方舟列表当前状态。生产数据未因本次叹号修复改写。API说明已同步；正常单据不应为清理叹号而重建、重试或清除历史记录。

## 2026-10-08 出库单打印状态筛选（Codex，已合并推送部署）

- 分支 `codex/outbound-status-filters`，独立工作树 `C:/Users/windb/.codex/worktrees/outbound-status-filters/commission-system`。出库单打印页新增可清空的「出库单状态」「检验状态」下拉，复用列表状态文案；两个状态与关键词、日期直接展示，订单 ID 移入展开筛选。
- 查询提交条件并回到第一页，翻页/排序保留已提交条件，重置恢复默认。后端新增 `outbound_state` / `inspection_status` 参数并在计数、排序、分页前组合过滤，沿用原数据范围与去重。检验状态不匹配尚未生成单据、检验栏为“—”的本地任务；`retrying` 沿用既有自动重试判定，和最终失败区分。
- 独立 agent 审查未发现阻塞项，确认前后端状态口径、分页前过滤、权限、去重及查询重置契约；MySQL 做静态兼容检查，未执行真实 MySQL 验证。
- 验证：隔离 SQLite 后端状态筛选、出库队列、排序测试 71 项通过；前端筛选、操作与 useListPage 测试 17 项通过；前端构建通过（保留既有分包告警），增量约定/UI 门禁与 `git diff --check` 通过。Git 巡检已运行 `--no-fetch`，为本地远端引用快照。
- 按本轮授权，功能提交 `c5c03bea` 已合并推送 `origin/main`，办公室统一部署入口先准备后发布，范围 `office-and-cloud`，回执 succeeded、deferred=[]，无数据库迁移。两地版本、健康、两个筛选参数枚举与两文件源码摘要一致；11 组生产只读筛选查询及 11 项公网制品核验通过。原主目录 24 项改动保留；浏览器连接不可用，未做登录态界面验收。详见[发布记录](reports/2026-10-08-outbound-status-filters-release.md)。

## 2026-10-08 订单发票关联详情（Codex，已合并推送部署）

- 独立 worktree / 分支 `codex/invoice-detail-prototype`，基于 main `fbb63182`。发票号打开订单/出库/回款三页签只读弹框；顶部原币财务生效与实际出库独立进度，关联单据、检验状态、预售冻结批次与私有回款凭证按各域权限展示。
- 发票号红色静态荧光异常框与对应左侧导航黄色 `!` 复用完整可见范围异常投影；正常等待与已证明可自动重试不误报。核验失败保留明细并隐藏汇总，权限/身份变化清空旧数据；没有新增业务写入接口、权限或迁移。
- 后端相关隔离回归 182 项、前端状态/请求回归 3 项通过；真实组件浏览器验证三页签/异常跳转/搜索/展开/Escape焦点及手机/短屏通过。构建、增量约定、diff 检查与独立审查通过，Git巡检为 `--no-fetch` 本地快照。
- 应用候选 `ddc4a5a5` 已合入推送 main；办公室统一入口 prepare-only 与正式发布均退出 0，release_id=`444e65ef05d5472084a1471ff15567b9`，scope=office-and-cloud、deferred=[]。两地 HEAD 一致、health=ok/connected，四个 GET 端点已注册，前端制品及六个详情源码文件按候选核验。
- 本次统一发布同时包含主线回款恢复迁移 `174→175_receipt_recovery`，共享迁移日志 completed；四列、两表及三索引只读核验通过，原出库 timer 与停用邮件 Worker 基线保留。合并候选后端 182 项、前端 8 项回归和构建再次通过；主目录原 24 项改动逐项保留，证据在 `.deploy_state/invoice-detail-release/`。
- [实现与验收](requirements/2026-10-08-invoice-detail-implementation.md)、[发布记录](reports/2026-10-08-invoice-detail-release.md)及 API/模块笔记已同步。隔离验证没有真实小满或共享库业务写入；发布后仅做版本、接口、结构与制品核验。此前静态原型保留为历史设计参考。

## 2026-10-08 出库单自动重试状态文案（Codex，已验收，授权合并推送，未部署）

- 独立分支 `codex/outbound-retry-label`：出库列表已核实仍会自动重试的 `retrying` 显示“重新生成中”，操作提示改为“系统正在重新生成，请稍后刷新查看”；保留最早重试时间和尝试次数，最终失败仍为“生成失败”，不确定结果仍为“待核对”。仅调整展示文案，不改重试资格和打印保护。
- 已同步接口说明及既有文案断言。出库列表5项Node测试、前端生产构建、严格增量约定与diff检查通过；Git巡检为 `--no-fetch` 本地快照。亮哥已授权提交、合并及推送 `origin/main`，本轮不部署。

## 2026-10-08 回款同步恢复 1/2/4 项（Codex，授权合并推送，未部署）

- 分支 `codex/receipt-sync-recovery`：持久 preparing/sending 阶段和发送摘要、迟到响应证据；发送前临时故障有限退避，已知 ID 自动严格回读和财务生效轮询。历史未知阶段/无 ID 结果不明保持人工核对，不自动改金额或手续费。
- 迁移 `175_receipt_recovery`，父 174：新增恢复字段、发送证据表与共享索引表。独立索引后台使用跨实例数据库租约和原子发布，增量超过 100 条分窗；单笔任务不全量重建，不凭陈旧余额发送。
- 亮哥已授权合并推送；仅隔离测试与离线 DDL 核验，未运行共享库迁移或发布。实现边界和验收见[回款恢复说明](requirements/2026-10-08-receipt-sync-recovery.md)。
- 验收：关联回款、预售、生命周期、删除保护等 339 项隔离测试通过；独立 agent 审查发现的回读乱序、迟到异 ID、证据回滚、持续高增量和核对绕过问题已修复并复审通过。约定检查、diff 检查通过；Git 巡检为 --no-fetch 本地快照。

## 2026-10-08 内贸经营决策台实现（Codex，已验收，授权合并推送，未发布）

- 独立 worktree / 分支 `codex/domestic-decision-prototype`，入口 `/domestic/decision`。七个专题已接入真实业务模型与服务端权限；同明细组合筛选、多维交叉、金额与件数分箱、资金桥接、客户/业务员画像、规则建议、行动实际结果、个人视图、异步事实简报/私有导出/自然语言查询计划已实现。
- 新增迁移 `174_domestic_decision`（父 `173_task_center`）、七张决策表和六项权限。客户归属按实时负责人收窄，资金权限单独裁剪；AI 只能选择已注册假设和程序事实，失败保留规则结论。原客户、订单、明细、账本变更同事务采集必要事件，旧历史不补造。
- 新模块最终隔离回归97项通过；关联内贸回归917项通过、1项跳过。前端锁定依赖构建及31项相关前端测试通过，独立资金/权限/并发/契约审查无遗留P0/P1。浏览器结果见[验收证据](requirements/domestic-decision-evidence/README.md)，全为独立SQLite合成数据。
- 功能与发布边界见[使用及运维说明](domestic-decision.md)和[实施验收](requirements/2026-10-08-domestic-decision-implementation.md)。亮哥已授权合并推送，本次不包含部署，未执行共享库迁移；真实规模性能与MySQL并发压力待发布前核验，可靠预测、历史时点重建、自动订阅仍为P1。

## 2026-10-08 内贸经营决策台高保真原型（Codex，历史阶段）

- 独立分支 `codex/domestic-decision-prototype`，原型及离线版位于[原型目录](requirements/domestic-decision-prototype/README.md)，功能背景见[设计文档](requirements/2026-10-08-domestic-business-decision-workbench.md)。
- 七个专题、组合筛选、画像与证据抽屉、资金桥接、演示简报、浏览器内跟进和导出已可操作；18家门店、353笔订单、502条账本均为虚构演示。
- 浏览器10组检查通过，含1440px桌面/390px手机、离线打开与状态持久化；独立审查的三项指标契约问题已修复并回归。未接入生产、未调用真实AI、未提交推送或部署。

## 2026-10-08 按变更明细补验与历史照片恢复（Codex，合并推送，待部署）

- 用户核对 `翟 #261006` 后要求排除 `Other Items`，并将判定改为仅变更明细补拍。方舟出库修改和外部小满镜像两条路径按稳定远端身份选择性失效，未变产品保留照片；变更/新增实物与整单补拍，删除清理该行未完成要求，费用行不要求产品照片。
- 独立 worktree `C:/Users/windb/.codex/worktrees/inspection-fee-exclusion/commission-system`，分支 `codex/inspection-fee-exclusion`。后端提交同时处理已有 `__all_items__` 和指定费用明细 ID 的待补验状态，无数据迁移；扫码、刷新和验货详情统一下发 `requires_recheck_photo`，共用手机按后端标记排除费用行的缺失提示，费用明细和历史媒体保留。
- 修复版共享库只读核验：审计 `5774` 证明镜像 `93127` / 检验 `447` 仅 `#P2/8` 从24寸改22寸。新规则恢复 #1B、Cookies Cream、#5ATP5A/1006 的6张旧照片；失效仅 `[4057,4081,4082]`（旧整单及P2），要求整单和本地明细 `341639`，已补传的3张新照片覆盖。恢复须通过完整版本/媒体/产品审计证明，读取不写共享库，成功提交才保存恢复及审计。验货仍为草稿，未替用户提交；按用户授权合并推送代码，本轮未部署。
- 验证通过：后端联合190项及随后新增的发票同步端到端、SKU身份核验2项；共用手机23项、同步服务31项；前端生产构建、约定、diff检查和两个独立审查。Node 审查发现的镜像落后时比较基准、删除本地照片关联与纯价格打印授权问题，以及后端连续编辑遇到已失效删除行误退整单重拍问题，均已修复并补回归。Git巡检为 --no-fetch 本地快照；主目录10处修改、14个未跟踪文件保持原状。任务 worktree 使用独立前端依赖，未修改主目录依赖或锁文件。只读核验证据保留于任务目录 `tmp/selective-recheck-verification.json`。

## 2026-10-08 自动出库业务快照校验与重试状态（Codex，授权合并推送，未部署）

- 分支 `codex/outbound-order-guard`，worktree `C:/Users/windb/.codex/worktrees/outbound-order-guard/commission-system`，基点 `6dcc1ed1`。针对「翟 #261014」首次提交前整份 JSON 比较失败、第二次自动成功的现象，将校验改为实际出库业务快照；已知失败时未保留两次快照，不断言本次具体改变字段。更新时间/库存元数据不影响校验，数值格式和行顺序归一化，明细按唯一 ID 保留，同 SKU 多行数量/价格、客户、处理人、币种汇率、单位/名称/型号及订单状态变化仍在提交前拦截。
- 保留有限退避、每轮最新订单/成功同步日志/认领版本核验、实时查重和持久提交意图；加强认领后取消检查。变化日志只记录字段路径与前后摘要，执行端策略刷新保留证据和退避时钟。出库列表及分页前排序共用已核实未提交重试资格，显示“等待自动重试”与最早北京时间/下一次尝试；最终失败、不确定或冻结记录不承诺自动重试，不放开打印/下载。
- Node 执行端/前端相关回归114项通过；后端最新隔离联合回归171项通过。测试全部使用临时目录、mock与内存 SQLite，不写共享数据库；MySQL 分支完成独立静态审查。主站构建通过；严格增量约定、diff检查和独立审查通过。Git 巡检已执行，`--no-fetch` 为本地快照。实现与接口说明同步到 `deploy/okki_outbound_poller.md`、`docs/api-reference.md`。
- 已获亮哥授权提交、合并与推送 origin/main；本轮不部署，无 schema 变更。生产生效需统一发布后端、前端与出库执行端。

## 2026-10-08 首推待核对恢复漏建出库与订单号绑定（Codex，修复已验证，待上线）

- `Jose Majano1008`（发票927）首推超时后人工绑定，旧流程漏登记自动出库意图、且只在 create 成功时入队。用户授权补建6件待出库单后，已通过现有受控恢复入口完成；任务457、审计1206，小满出库 `105839352970493`，实时回读待出库、6件、客户及仓库正确。
- 代码在独立 worktree `C:/Users/windb/.codex/worktrees/invoice-bind-order-no/commission-system`，分支 `codex/invoice-bind-order-no`。发送前随持久发送标记登记出库意图，旧版待核对人工绑定补登记；首次完整同步成功后幂等入队，对账也接受恢复后的成功 update。绑定本身不入队，预售、未登记历史订单、未完成同步和取消订单不追建；已有执行中、完成及未知结果任务不重发，库存收尾失败连同新任务回滚。
- 人工绑定改为填写小满 `order_no`，从订单镜像唯一解析内部 ID，验证客户、订单名称和已有绑定，保存原生订单号并审计；接口字段为 `xiaoman_order_no`，不保留旧 ID 入参兼容。API、数据库说明和生命周期文档同步，无 schema 迁移。
- 后端隔离联合回归404项、补充绑定日志防误入队及失败边界回归通过，前端15项、构建、严格增量约定和 diff 检查通过；独立审查无阻断问题。本地浏览器模拟验证空值拦截、字母与连字符订单号、首尾空格清理及实际新字段请求；证据在主目录 `tmp/invoice-bind-order-no/`。代码验证没有真实业务写入。用户已授权提交、合并并推送 `origin/main`，本轮不部署；主目录原有改动另行备份和恢复，不夹带。Git 巡检为 `--no-fetch` 本地快照。

## 2026-10-08 订单改单后的回款修正（Codex，已合并推送部署）

- 分支 `codex/invoice-receipt-correction`，独立 worktree。订单约定预付款与实际资金分开；编辑页提供未发送普通回款修正、明确重试、补登记、资金汇总和小满变更核对入口。订单未保存/未同步或资金核验异常时普通写入受阻；已同步金额保留，超收只提示核实。
- 发票回显和冻结校验使用当前真实回款，保持生成意图及原单 ID；修正自动手续费按新金额分摊并排除原单，保留版本与审计。截图版本和多凭证顺序同步，预售/批次沿用原流程。无 schema 迁移。
- 应用候选 `45e57ca8` 已合入并推送 main，办公室统一入口准备与正式发布均退出 0，release_id=`d59340745c1c43cc9f49f463ae0f9309`，scope=office-and-cloud、deferred=[]。两地实际 HEAD 一致、health=ok/connected，新回款汇总 GET 路由存在；schema173 无 DDL，三个回款源码文件与候选一致，三域 16 项公网制品摘要匹配。出库 timer 恢复 active/enabled，邮件 Worker 保持 inactive/disabled/MainPID0。
- 合并后后端隔离联合回归 202 项、前端 43 项再次通过；构建、本地模拟页面关键路径、窄屏及独立审查通过，严格增量约定与 diff 检查通过。主目录原 24 项改动恢复并逐项验证；备份和证据在 `.deploy_state/invoice-receipt-correction-release/`。本次未登记真实回款、修改生产订单或执行退款；详见[实现验收](reports/2026-10-08-invoice-receipt-correction.md)与[发布记录](reports/2026-10-08-invoice-receipt-correction-release.md)。Git 巡检为 `--no-fetch` 本地快照。

## 2026-10-08 出库检验照片恢复与镜像修复（Codex，已合并推送部署）

- `Pan260922....`（镜像93076，检验423）10张失联照片已按标签和SKU对应关系恢复，维护审计5687。实际扫码回读45张：12张整单、33张产品、孤立0；序号7/8/11/14/16各2张，检验仍已提交、版本0。
- 原同步删除全部明细再插入导致本地ID改变；现按稳定远端身份更新并同事务处理照片/补验/审计，保留verified远端身份匹配主干上传解锁合同。生产验证发现API关联ID=0落NULL的差异并补齐归一化；暂停期间审计未发现误撤回。142项后端、22项同步、10项部署回归与独立审查通过。
- 主应用 `bcaecb32` 已合入推送并通过办公室统一入口完成两地发布，release_id=702470b8743343ca90a50814b49643fe，schema173无DDL，两地health正常；同步补充源码 `e2b662f0` 同样合入推送，并以制品1d2037ce...完成北京专项激活。真实限定同步后18个本地明细ID、45张照片、已提交状态与原审计全部保持；两地安装源码/扫码回读与下一轮cron（失败0）验证通过。
- 原23项主目录改动保留，证据在 `.deploy_state/shipping-photo-sync-release/`。[恢复发布记录](reports/2026-10-08-shipping-photo-recovery.md)、[专项更新入口](../deploy/okki-sync.md)。

## 2026-10-08 出库照片上传等待刷新误拦截（Codex，修复待部署）

- `翟 #261009`（镜像记录 `93131`，小满出库 `105839152638638`）上传照片提示出库资料正在刷新。共享库只读核验：镜像与已验证快照均为 `2026-10-08 07:10:55`，10 行、10 件和远端明细 ID 已一致。3 行颜色在产品库带 `#`、发票展示不带，费用行产品库尺寸为“其他费用”而发票为空；旧代码混用两种来源比较，导致快照不能退出、照片上传永久等待。
- 独立 worktree `C:/Users/windb/.codex/worktrees/shipping-inspection-refresh/commission-system`，分支 `codex/shipping-inspection-refresh`。改为核对原始出库字段和远端明细 ID，成功后恢复本地明细 ID 验货；原始单头再次查询，避免打印快照覆盖单号/备注后掩盖镜像未追上。无数据库迁移。明细缺失、数量/身份/规格等不同和活动同步仍阻断。
- 回归先失败后通过；修复版对上述真实记录再次只读核验，原始出库一致、快照解除、验货展示使用本地行 ID `341669`–`341678`。相关出库同步、照片上传、撤回版本及工作台隔离回归 139 项通过，独立审查无阻断问题；约定检查与 diff 检查通过，Git 巡检为 --no-fetch 本地快照。未创建验货单或写入生产数据。用户已授权提交、合并及推送 origin/main；线上恢复需按统一部署入口发布本补丁，本轮不执行部署。

## 2026-10-08 Kaila Turpin1004 出库失败提示修正（Codex，未部署）

- 共享库与小满仅做只读核验：发票 ID 899、小满订单 `105839188974693` 的出库任务首次执行于 08:49:49 在提交前检测到订单变化，记录 `failed`；发票后续同步成功，但旧提示把该状态误导为缺少已核实删除的原出库单。
- 原有轮询器第 2 次执行已于 09:00:52 自动完成任务，小满实时关联出库单为 `105839195729997` / `Kaila Turpin1004`，状态待出库。本次没有恢复队列或创建生产单据。
- 用户追加核对 `Makenzie Schmid1005`：发票 ID 901、小满订单 `105839191584720`，同样在首次出库执行于 08:58:16 检测到订单变化、提交前停止；09:02:41 订单更新同步成功。09:06 的实时完整关联扫描为空，两次订单详情回读一致；任务仍 `failed`、attempts=1，按退避谓词 09:08:16 后可再次认领。本次仅核查，未恢复队列或补建单据。
- 分支 `codex/invoice-outbound-failure-message` 按用户确认的逻辑修正：待执行、执行中及仍可自动重试统一提示“出库单正在自动生成，请稍后刷新查看。”；重试耗尽、结果不确定、漏建及原任务已完成但原单缺失分别给出核对入口。保持原队列与防重保护，删除后重建仍需删除核实记录。管理员恢复入口仍为订单“取消 / 恢复”中的“恢复漏建 / 未发送出库”。
- 执行端用 `last_error` JSON 记录失败次数及实际重试上限，每轮认领前刷新历史记录及配置变更；CAS 防止覆盖并发认领/恢复，保留 `updated_at` 及退避。后端不猜测默认上限，未知/无效/次数不匹配的策略记录不承诺自动生成；应用与轮询器需作为同一候选发布，无 schema 迁移。
- 发票出库同步、生命周期和任务队列隔离回归 146 项、执行端 Node 回归 50 项通过，增量约定和 diff 检查通过；独立审查确认策略、CAS、退避计时及防重边界无遗留问题。Git 巡检使用 `--no-fetch`，仅为本地快照。本次交付范围为合并并推送 `origin/main`，不包含部署；应用与轮询器上线仍须统一发布。

## 2026-10-07 提成批次计算排序规则修复（Codex，已合并推送部署）

- 批次 `2026-3`（ID 10，2026-07-01 至 2026-09-30）点击计算提示数据库连接失败。共享库只读复现实际错误为 MySQL 1267：订单 ID 的多余 `CAST AS CHAR` 引入连接排序规则，与运费应收订单 ID 列冲突。直接比较同类型、同排序规则的列即可修复，无数据库迁移，不改提成规则。
- 实现分支 `codex/commission-batch-collation`。MySQL 查询编译回归先失败后通过，提成计算、批次状态、回款同步隔离测试 48 项通过，合并后再验证 48 项通过；独立审查无阻断问题，增量约定和 diff 检查通过。排查说明同步至 `docs/runbook.md`；Git 巡检采用 `--no-fetch`，仅为本地快照。
- 应用候选 `77fec60c` 已合入并推送 main，通过办公室统一入口完成准备和正式发布，均退出0，release_id=`e377cc72330848fa9beb9c9054cdd6a0`。两地实际HEAD一致、health=ok/connected、计算POST路由存在；schema173无DDL，三域9项公网文件摘要匹配。出库timer恢复active/enabled，邮件Worker保持inactive/disabled/MainPID0。
- 两端运行源码摘要与候选一致，真实批次只读验证均得到 2,045 条待计算回款、1,125 条候选明细、920 条归属不完整跳过、计算错误0；第一条写SQL发送前被拦截。批次仍为草稿，明细和已计算标记均为0，可从页面再次执行计算。原23项主目录改动保留，发布及核验证据在 `.deploy_state/commission-collation-release/`；详见[发布记录](reports/2026-10-07-commission-collation-release.md)。

## 2026-10-07 回款软删除核验修复（Codex，已合并推送部署）

- `Rina-KC-1001` 的关联出库已删除，回款 `105824479304117` 也在小满删除列表，但详情仍可读；旧判断把它当成删除结果未知，导致预览和接续同时阻断。现在增加原单绑定、同秒完整有效/删除列表双轮一致和详情回读核验。未知请求只核验，不重发；金额、手续费、凭证保留，无数据库迁移。
- 应用候选 `9e7b3876` 已合入并推送 main，办公室统一入口准备与完整发布均退出0，release_id=`a9f06404f03b497b9452a4f547fb0770`。两地实际HEAD一致、health=ok/connected，schema173无DDL；三域9项公网文件摘要匹配。出库timer恢复active/enabled，邮件Worker仍inactive/disabled/MainPID0。
- 两条先失败后通过的软删除回归及相关联合测试106通过，合并后复验106通过，独立审查及新增17项复验通过，严格约定和diff检查通过。生产真实订单只读预览blockers为空，保留原步骤与账本，未发送任何删除POST；可在订单发票点击“继续删除”接续。详见[发布记录](reports/2026-10-07-receipt-soft-delete-release.md)。
- 生产诊断证据在主目录 `.deploy_state/rina-deletion-debug/`；发布、核验及原23项改动备份恢复材料在 `.deploy_state/receipt-soft-delete-release/`，不夹带入提交。

## 2026-10-07 私海与冻结列发布完成（Codex，已合并推送部署）

- 办公室SSH转发恢复后按用户要求重试，固定应用候选`e12cb42acd8afeb7c64711a05fa554e026828ab2`准备与完整发布均退出0，release_id=`accce2153fc74dac919366034e4afd0c`，scope=office-and-cloud，deferred=[]。两地实际HEAD一致、health=ok/connected，共享schema173，无DDL。
- 三域18项公网入口/JS/CSS摘要匹配，包含发票与出库冻结列资源。Derek在.work与.cloud只读查询均126客户；2432回填客户实时归属及投影核验无异常，42共享客户仍待核对，原有主负责保留。邮件Worker仍inactive/disabled/MainPID0，出库timer恢复active/enabled。
- 原23项主目录改动校验保留。发布证据在`.deploy_state/private-customer-release/`；详见[生产发布报告](reports/2026-10-07-private-customer-release.md)。以下SSH阻塞记录作为历史过程保留，当前已解除。

## 2026-10-07 私海与冻结列发布（Codex，已合并推送，部署待恢复 SSH）

- 用户授权“合并推送部署”。私海修复候选 `e12cb42acd8afeb7c64711a05fa554e026828ab2` 已合入并推送 main，远端回读一致，包含先前冻结列提交 `1c839bbe`。严格增量约定及 diff 检查通过；主目录原23项未提交内容逐文件校验保留。
- 办公室 `office-prod` 本机2223拒绝连接、2233也未监听，未进入统一部署入口，未切换生产或执行DDL。需恢复既有GameViewer办公室22端口转发，随后按固定候选继续prepare/publish；本机启动器与保留证据在 `.deploy_state/private-customer-release/`，任务worktree暂保留。
- 实时只读后检：北京仍运行 `8cbde90d`，health=ok/connected，共享schema173；邮件Worker inactive/disabled、MainPID0，出库timer active/enabled。Derek线上查询126客户。数据修复已生效，冻结列及档案编译代码尚待发布；详见[修复与集成报告](reports/2026-10-07-private-customer-visibility-repair.md)。

## 2026-10-07 业务员私海客户可见性修复（Codex，数据修复完成，代码待集成）

- 分支 `codex/customer-private-visibility-repair`。Derek 原有有效 OKKI 绑定，但 salesperson 缺 `customer:read`，且镜像中 126 个私海客户未进入统一客户域。已只加授该读取权限，保留原 59 项权限，不加 `customer:read_all`；权限审计 ID 71。Derek 126 个客户已完成归属、档案与列表投影回填，实际工作台查询及线上 GET 均确认 126 个，跨业务员访问拒绝。
- 2474 个去重客户已处理：2432 个归属明确客户完成投影、有效主负责及档案/列表编译，42 个共享客户无既有主负责，按用户决定列为待核对，未擅自导入公海或选负责人。6 个业务员缺 OKKI 绑定，不推断外部身份。原 170 个主负责归属全部保留，其中 30 条镜像差异仅列清单、不自动转移；最终 37 个账号查询范围及 2432 个客户核验无异常。
- 回填重用现有受控投影与归属服务，逐客户复核镜像归属、当前绑定和角色，逐客户事务及回执；不回填订单，不建 AI/研究任务，不写镜像、不改表结构、不部署。过程中修复档案编译的 MySQL 字符排序规则冲突、超长行业摘要及产品偏好不应伪造标准标签的问题，完整档案和事实保留。独立审查通过；联合隔离回归141通过、1项缺可销毁MySQL隔离库跳过。本地修复代码尚未合并推送。
- 私有冻结计划、逐客户回执、核验、恢复材料及 `私海客户待核对.xlsx` 在主目录 `backend/tmp/customer-private-visibility-repair/`（忽略文件，不提交客户原数据）。最终回执按执行阶段核对输入集合后归并，保留原始记录；所有批次已结束。收尾报告在 `docs/reports/2026-10-07-private-customer-visibility-repair.md`。

## 2026-10-07 订单发票与出库列表冻结列（Codex，已验证）

- 分支 `codex/invoice-outbound-frozen-columns`，工作树 `C:/Users/windb/.codex/worktrees/invoice-outbound-frozen-columns/commission-system`。订单发票列表固定左侧发票号、客户；出库单打印列表固定现有出库单号、客户名称，移除订单 ID 表格列及列设置项。旧列偏好自动剔除已移除键，保留订单 ID 搜索。
- 固定列沿用原右侧操作列底色并扩展到左侧，防止透明表格横向滚动重影。25 项既有前端检查、前端构建、增量约定与 diff 检查通过；真实 Vue 页面使用拦截 API 的示例数据验证两列保持固定、其余列滚动及旧偏好清理。独立代码审查通过。无后端、打印文档或数据库变更。
- 用户已授权合并并推送 main，本轮不部署。Git 巡检使用 `--no-fetch`，仅为本地快照；浏览器与构建证据交付至主目录 `tmp/invoice-outbound-frozen-columns/`，任务工作树在集成后清理。

## 2026-10-05 订单发票一次确认自动删除（Codex，已合并推送部署）

- 工作树 `C:/Users/windb/.codex/worktrees/invoice-cascade-delete/commission-system`，分支 `codex/invoice-cascade-delete`。订单发票页一次确认关联范围后，自动处理对应待出库、小满回款、未发送本地回款和小满订单；已进入人工取消的普通订单可接续。原发票、回款金额、手续费、凭证、验货与审计资料取消归档保留，不执行退款。
- 完整范围/权限预检、确认版本、发送前关联内容复核、逐步持久意图与恢复；未知结果只核对，不重发。预售/批次、共享出库、已出库、库存预占及其他执行中/未知任务明确阻断。后端隔离联合回归89项、前端Node16项、真实组件浏览器模拟5场景、最终前端构建23.21s、约定与diff检查通过。独立审查3项修复闭环，并独立重跑8项回归；软删除有效列表、父单业务字段变更、陈旧出库镜像跨单影响均已覆盖。API 和生命周期文档同步，无数据库迁移。
- 应用候选 `8cbde90d` 已合入并推送 main，办公室统一入口准备与完整发布均退出0，release_id=`10690e46a8944b37b9770c52ba89870e`。两地实际HEAD一致、健康ok/connected，运行OpenAPI均含删除GET/POST；三域9项公网文件SHA256匹配候选。共享schema仍173，无DDL；出库timer恢复active/enabled，邮件Worker仍inactive/disabled、MainPID=0。见[发布报告](reports/2026-10-05-invoice-deletion-release.md)。
- 浏览器API全部拦截为示例数据，无真实业务写请求；临时Vite已停止。准备/发布日志、生产核验及浏览器证据已保存在主目录 `.deploy_state/invoice-deletion-release/`。依赖复用junction的单独清理曾被工具策略拒绝，未递归删除目标依赖。
- 未对 `Rina-KC-1001` 或其他真实单据执行删除。主目录原有23项改动独立备份恢复，不夹带入提交；no-fetch Git巡检仅为本地快照，不据此处理其他分支。

## 2026-10-04 列表布局与表头排序（Codex，已合并推送部署，邮件暂停）

- 应用候选 `4bcde7c2`。主管关系/客户归属及其他同类筛选栏重叠已修复，174 个 Element Plus 表格与记录型原生/PM 表格补齐排序；分页按完整授权查询结果排序后切页，银行卡按可见掩码排序，树表保留父子结构。原实现工作树已归档，源码在 main。
- DESIGN.md、API 文档同步；主站/PM 构建、真实页面窄屏/桌面/全屏及跨页排序浏览器回归、受影响隔离后端测试、约定与 diff 检查通过。独立审查发现的公告草稿状态、库存中文回退、偏好摘要和分配状态排序已修复。详见 [验收报告](reports/2026-10-04-table-layout-sorting.md)。
- 应用候选已整合 main 悬浮滚动条并推送，合并验证与独立审查通过。首次预检遭邮件平台 429；用户授权先停止持续请求后，邮件 Worker 已优雅停用并取消自启，回执无待提交。随后统一入口完整发布成功：两地实际 HEAD 均 `4bcde7c2`，健康 `ok/connected`，三域 31 项公网文件 SHA256 一致，无数据库迁移，出库 timer 原状态恢复。
- 邮件 Worker 新制品已安装但仍 inactive/disabled、MainPID=0；限流未宣称解除，邮件同步/待发任务暂停，后续需补退避并验证后再授权恢复。主目录原有 23 项改动保留。详见[发布报告](reports/2026-10-04-table-sorting-release.md)。

## 2026-10-04 客户邮件 MVP（Codex，已合并推送部署）

- 分支 `codex/customer-mail-mvp`；主功能及内部试发版本已正式发布，office/cloud 同版、schema 173 无迁移，邮箱 OAuth 与 Worker 健康。时间精度修复 `1542e47e` 已完成正式切换及两端/Worker 同版核验。
- 发件 `leshinehair@agent.qq.com`，仅允许 `86muliang@163.com`。真实 AI 生成、修改、审批、排程、临发授权、回执均已跑通；message=1/revision=3/job=2 为 provider_accepted，sent 查到唯一邮件 `msg_A06MkNfpqfCI-qcLMaPQLqZSnYH3IBdtPmDCsvnuuip4lg`，主题 `[ARK INTERNAL TEST] Ark acceptance 20261003-0922`。
- 首次 job=1 被毫秒/数据库整秒摘要差异安全拦截，未发信，已撤销；修复已补先失败后通过的精度回归。内部收件人 contact=1/point=1 明确非样例客户联系人，发信后已取消可联系标记；内部试发不记客户经营时间线。
- 北京时间 11:00:30 收到用户真实回信“方舟验收收到”，官方邮箱已读信确认；Worker 自动建立 event=1 并关联 job=2，页面人工确认分类后为 human_reply/processed。只读复核没有待发送任务，内部测试未写入客户经营时间线，测试联系人仍不可联系。真实收发闭环验收完成，外部客户发送白名单未开放。
- 2026-10-04 已合并并推送 main，应用提交 `acdec9d9067b91d8bb8ff4ab25daa94f61bd025e` 经统一入口完成办公室与云端发布，release_id=`2cdfa6e9d3e542d68c94f8f965f34841`，deferred 为空。办公室和邮件 Worker 使用本次 revision；北京后端源码未变，部署器复用 `1542e47e`，健康 ok/connected。出库调度保持 active/enabled=true，无数据库迁移。
- 合并后后端邮件 66 项、前端邮件 10 项、Worker 15 项及主站构建通过；两地主站 10 项公网资源摘要匹配候选。原有 23 个未提交/未跟踪文件保留。见 [使用说明](customer-mail-outreach.md)、[验收记录](reports/2026-10-03-customer-mail-mvp-progress.md) 与 [发布记录](reports/2026-10-04-customer-mail-mvp-release.md)。

# 当前交接与待办

## 2026-10-03 客户工作台看板卡片（Codex，已合并，10-04 随 main 部署）

- 分支 `codex/customer-board-style`，独立工作树 `C:/Users/windb/.codex/worktrees/customer-board-style/commission-system`，基点 `b84dc534`。客户事项 4 卡、客户组合 6 卡共用 `OverviewMetricCard.vue`，按订单发票页统一浅色语义渐变、SVG 图标、右下淡水印，并保留筛选/统计口径；根目录 `DESIGN.md` 已加入全局看板卡片规范。
- 主站构建、事项 Node 13/13、Chrome 9 组渲染 + 触屏、键盘筛选、0/缺失/长数字、桌面/900px/390px/320px、约定和 diff 检查通过；浏览器使用拦截样例数据，无真实业务请求。Git 巡检为 no-fetch 本地快照。按 2026-10-03 授权，应用提交 `059302c3` 已无冲突合入 main；合并后事项 13/13 与 `check_conventions.py --base b84dc534` 通过，前端及 DESIGN.md 与已验收版本一致。2026-10-04 已随合并后的 main `acdec9d9` 完成两地主站发布，见[发布记录](reports/2026-10-04-customer-mail-mvp-release.md)。见[验收与预览](reports/2026-10-02-customer-board-style.md)。

## 2026-10-02 顶栏与标签栏毛玻璃（Codex，已合并推送部署）

- 分支 `codex/navigation-glass`，独立工作树 `C:/Users/windb/.codex/worktrees/navigation-glass/commission-system`，基点 `217b11bb`。借鉴 shadcn-admin Header 的半透明 / 模糊 / 轻阴影，两栏共用一个毛玻璃表面，沿用品牌金；设计令牌、DESIGN.md 同步。按用户“看不出效果”反馈，改为正文从导航后方实际滚过，白底 0.58 → 0.38，保留单一 16px 模糊层；首屏 / 滚动定位 / 根滚动吸顶控件同步导航高度偏移，fullscreen 内归零。标签在栏宽变化时立即露出，包含关闭按钮；无模糊支持 / 减少透明偏好使用实色底。
- 导航 Node 10/10、Chrome 桌面 / 390px / 320px、菜单 / 任务浮层 / 标签键盘与关闭 / 侧栏抽屉 / 减少透明及动态检查、主站构建、增量约定与 diff 检查通过；真实正文重叠及开 / 关模糊截图像素变化已验证，吸顶控件与 fullscreen 复核通过；业务网络请求及 JS 异常为 0。巡检为 no-fetch 本地快照。见[验收报告与截图](reports/2026-10-02-navigation-glass.md)。本地预览 `http://127.0.0.1:4334/tmp/navigation-glass/index.html?glass-demo=1`；开发期预览已完成，发布后清理会话。

- 应用 `1c6130853beda46b20390276c8e9bc323f906fc3` 已合入 main 并推送 origin，办公室统一 deploy.bat 固定同 SHA 完成 prepare-only 与正式发布，退出 0；release_id `5edd819e00754ae2964d00781b51389c`，范围 office-and-cloud，deferred 为空。数据库仍 `173_task_center`、无迁移；出库 verified，active/enabled 均 true。额外 50 次 HTTPS 检查确认入口及毛玻璃相关样式 / 页面资源与候选一致，办公室和两地主站健康 ok/connected。原 22 个未提交文件完整保留，任务工作树按合并后约定清理。见[发布记录](reports/2026-10-02-navigation-glass-release.md)。

## 2026-10-02 操作列与按钮一致性（Codex，已合并推送部署）

- 分支 `codex/action-button-consistency`，独立工作树 `C:/Users/windb/.codex/worktrees/action-button-consistency/commission-system`，基点 `6d815065`。DESIGN.md与按钮设计契约同步科技轻快配色、四语义接口、link尺寸和状态规则；主站/PM按钮token完全一致。
- 全量119操作列/272直接按钮及导出复用触发器接入统一规则，补64图标、3操作列实心/描边与分类打印改link、物流删除去内联色、warning tone实现；28处动作语义对齐。共享按钮修复金底文字、hover/active/focus、无阴影/缩放、单个加载图标与触屏44px。43个修改业务模板的脚本/事件/权限/条件/加载绑定核对保留。
- Node定向7/7；浏览器289源提取案例/384样式观察、139状态/对比度观察和窄列/权限/下拉/触屏回归通过；主站113导航构建和PM构建通过；增量约定、diff检查与独立复核通过。巡检为no-fetch本地快照，本地修复验收通过。详见[验收报告](reports/2026-10-02-action-button-consistency.md)与[设计契约](requirements/2026-10-02-action-button-design.md)，截图和源清单随报告保存。

- 应用提交 `b807fdcde6fe70267e74ad8f3082ed5ca1a2f8cd` 已合入main并推送origin。办公室统一deploy.bat固定同SHA完成预检及正式发布，两阶段退出0；`release_id=b1c3804f154d443bab2aadc4fdde5ff5`，范围office-and-cloud，deferred为空。数据库仍173_task_center，无迁移；出库verified、active/enabled均true。34项公网资源摘要匹配候选，办公室及两地主站健康ok/connected，PM统一按钮规范已核验。详见[发布记录](reports/2026-10-02-action-button-release.md)，证据保留于主目录`.deploy_state/action-button-release/`。原22个未提交文件完整保留；任务工作树按合并后约定清理。

## 2026-10-02 中后台按钮配色（Codex，已部署）

- 分支 `codex/button-colors`：GlassButton、Element Plus、PM 共享按钮及登录、聊天、物流、发货、知识工具栏、任务创建等独立操作统一为 Ant Design 蓝色方向；主操作蓝底白字、次操作白底灰边、危险红色。按钮独立 token 不改变品牌/状态/导航配色；13px 蓝底白字采用 `#1668dc` 满足对比度。
- 真实 Chrome 317 项观测通过，包含桌面/390px、hover/active/键盘 focus、disabled/loading、Space 按压、减少动态效果、登录与 PM 入口；独立审查问题已修复，PM ghost 禁用 hover 另有20项定向复核。定向 Node 4/4，主站与 PM 构建、严格约定、UI门禁、diff检查通过；Git巡检为 --no-fetch 本地快照。
- 统一 `deploy/deploy.bat` 固定应用提交 `98eb7c1828d37f5f8004f659513daecf03dfbc8b`，先准备再正式发布，退出0；`release_id=9a04e62e81fd4995aa75c60e7cb95ca8`，范围 `office-and-cloud`，`deferred=[]`。办公室、北京后端、两地主站与已登记 PM/客户素材静态目标完成验证；数据库仍 `173_task_center`，无迁移。出库回执 `verified`，调度保持原状态。额外 24 次 HTTPS 检查确认两地主站及 `pm.leshine.work` 的入口、主脚本/CSS及登录页资源逐项匹配候选 SHA256；三站按钮 token 已验证，两地主站及办公室 health 为 `ok/connected`。详细记录见 [按钮配色报告](reports/2026-10-02-button-colors.md)，预览随报告保存；证据与恢复材料保留于主目录 `.deploy_state/button-colors-delivery/`。

## 2026-10-02 状态标签竖排修复（Codex，已合并推送部署）

- 反馈截图已复现：共享 StatusBadge 任意换行与发票84px窄列共同把中文标签压成逐字竖排。已在独立 worktree、分支 `codex/status-badge-nowrap` 恢复单行与超长省略；发票类型/状态/同步最小列宽调整为110/160/110。按亮哥“其他页面也要修复”扩大检查，调整70个Vue页面/组件中的121个状态列，覆盖售后、工资、邮件、客户、物流、生产、库存和系统等模块；源码审计185处状态列声明，单独核对1处发票动态模板。
- 标签保留全文title，动态插槽变化同步更新，显式title优先；多标签只在标签之间换行，可关闭标签保留按钮空间。独立审查发现的关闭按钮裁切与动态插槽title滞后均已修复并实际复核。
- 桌面与390px实际Chrome回归通过：72个标签含48个真实字典/页面显示映射状态，标签高22.5–24px，选取的登记状态完整展示；窄列原60/96px恢复24px。最终定向Node 17/17、状态列审计、构建（113导航）、严格约定、UI门禁与diff检查通过，债务基线不变。全量Node快照1190项中1184通过，6项为既有loginMapMotion Canvas mock缺save()失败；对应源码与测试未改，不宣称全量绿。最后的字典补漏及2项新增测试已由定向与浏览器验证覆盖。Git巡检为 --no-fetch 本地快照。
- 应用提交 `326f7e0bf55dd6b7d1ee3a7675f55bea0d3c4a94` 已合入main并推送origin。恢复GameViewer转发后，办公室统一deploy.bat固定同SHA先预检再正式发布，退出0，`release_id=1fc8d54b4b7c4a34bee5b5b0ee9f71db`，范围office-and-cloud、deferred为空。办公室、北京后端及两地主站纳管目标验证完成；数据库仍173_task_center，无迁移。出库回执verified、active/enabled均true。额外18次HTTPS检查确认两地主站入口/导航/主JS与CSS/发票及物流页面资源逐项匹配办公室候选SHA256，办公室和两站health均ok/connected。主目录15个无关文件指纹及原handoff内容保持一致；证据与恢复备份保留于主目录`.deploy_state/status-badge-delivery/`，任务工作树按合并后的清理约定处理。详见 `docs/reports/2026-10-02-status-badge-nowrap.md`。

## 2026-10-02 设计规范合并发布（Codex，已部署）

- 应用候选 `6afaf0b47bc43a74a6ab7b70918d1cd9d822b2cf` 已在主worktree合入main并推送origin；其他15个文件指纹不变，原交接文档无关diff已恢复。服务器统一 `deploy/deploy.bat` 先准备再固定同SHA正式发布，退出0，`release_id=77bbe018598147a1867a59b715454681`，范围`office-and-cloud`，`deferred=[]`。
- 办公室、两地主站与已登记色块/出库目标通过入口验证；北京后端内容、PM与客户素材制品无需变化。数据库仍`173_task_center`，无迁移；出库回执`verified`且调度`active/enabled=true`。两站额外12次HTTPS后检确认HTML/导航/主脚本/样例资源一致，health均`ok/connected`。额外Office SSH journal后检banner timeout，保留成功入口stdout；没有重复发布或绕过连接校验。
- [发布记录](reports/2026-10-02-ui-convergence-release.md)。本条是下方“本地完成未提交/发布”的后续交付状态；应用代码固定上述SHA，发布后文档记录另提交。本任务恢复证据已移至主目录`.deploy_state/ui-convergence-delivery/`，任务工作树/分支按合并后的清理约定处理；其他代理成果保留。

## 2026-10-02 设计规范剩余四阶段（Codex，本地完成，未提交/发布）

- 分支 `codex/list-filter-behavior`，工作树 `C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`。第1–13项与主站资源采用、门禁和规范索引已完成本地落地；包括弹窗/表单、状态字典、反馈/空态、金额/校验、分页/响应式详情、表格偏好恢复、语义色/尺寸和可运行组件样例。下方一期的“其余未启动”为当时历史快照，当前以本条为准。
- 远端读取按P/F/B/C/S真实语义分别接入共享或经验证的等价控制器：草稿与应用快照、首次错误/重试、旧数据过期说明、作用域清空/取消、过期响应拒绝；独立辅助资源不被主列表成功掩盖。限量历史明确标注，完整Color选项按合法200页读取且校验总量。保留任务树/生产看板/导入预览布局与原领域计算、权限、确认依据。
- 最后独立审查的生产raw响应假零、战报目录恢复旧选择、旧保存关闭新弹窗三项均已修复并按真实反例复核。相关回归6/6，主仪表盘15资源在非东八区5/5验证。各域报告已晋升到 `docs/requirements/ui-convergence-evidence/`。
- 最终前端全量1185项：1179通过、6项既有登录Canvas mock失败；隔离HEAD同样6失败，源码/测试/地图均未改。构建通过，113导航项；UI门禁、5项门禁负例、严格约定增量、diff检查通过；Git巡检为 `--no-fetch` 本地快照。没有宣称全量绿或所有业务页面生产验收通过。
- 实际组件样例桌面/390px验证了Enter/查询快照/重试/旧数据、列和密度持久化与恢复、视口铺满/Escape、长详情/表单可达和减少动态；修复隐藏overlay阻Escape与全屏边框2px溢出。截图已保留。真实写入型验证均是隔离夹具，没有生产数据库变更。
- [最终验收](requirements/2026-10-02-ui-convergence-acceptance.md)、[资源账本](requirements/2026-10-02-list-resource-coverage.md)、[浏览器证据](requirements/ui-convergence-evidence/browser-showcase.md)。`DESIGN.md`已给第1–13项实现/验收索引；新门禁禁止抬高旧预算，非md按钮19个路径按精确数量登记，PM/专业视图历史弱信号仍冻结。
- 未提交、推送、合并或部署；工作树和依赖链接保留供审阅。后续集成需核对最新main和本任务diff；生产发布另需授权。本轮一次性codemod已清理，交付、截图、stdout、隔离基线与恢复材料保留；其他代理成果未处理。

## 2026-10-01 列表交互优化一期（Codex，本地完成，未提交/发布）

- 仅执行优化清单第 1–4 项，试点为发票、回款、内销订单。分支 `codex/list-filter-behavior`；工作树 `C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`。共享 useListPage 增加首次失败/重试、刷新失败保留旧行与页码、过期请求隔离、草稿与已提交条件、增删改刷新策略；共享 FilterBar 与 ListPageStatus 已接入三页。日期也进入提交快照；Enter 排除输入法/下拉/日期确认；高级收起保留输入。
- 发票/回款新增按倒序排序回第一页，编辑保留有效页，删除末页按服务端 total 修正并重读。内销详情读取失败不再阻断列表刷新；缓存列表收到新单号返回路由后清理旧筛选并定位第一页，普通切回保留页码。错误横幅变化后重新计算内销表格高度。战报适配共享列表读取失败返回 false 的契约。
- 定向 Node 回归 **186/186 通过**（所有 `invoice*.test.mjs`，以及 `listPageComponents`、`listPagePilots`、`useListPage`、`domesticOrderFilters`、`battleReportRace`、`domesticCustomerControls`、`customerWorkspace`、`vueTemplateBindings`）。三个真实控制器集成 6 项、共享组件渲染 3 项包含金融保存成功后读取失败、缓存新单定位、日期/元数据竞争、折叠/Enter/卸载等边界。最终 `npm run build` 通过（3340 modules，113 导航项）；既有大 chunk 与 auth 混合导入警告仍存在。`check_conventions.py --strict`、UI 门禁通过；债务基线仅删除内销筛选器已消除的内联宽度 1 处和深层覆盖 3 处。
- 浏览器挂载三个真实页面，API 使用本地隔离夹具、写方法全部拒绝；核验一次 Enter 查询、草稿翻页仍用提交条件、首次失败与重试、旧行过期提示/恢复、高级折叠保留、生产单条件与标签重置。1280px 桌面三档宽度 160/200/280px；390px 回款六字段均 318×36、页面宽 385px；内销错误后分页仍在 900px 视口。截图与复现夹具保留于 `frontend/tmp/list-filter-verification/`，验收明细见 `docs/requirements/2026-10-01-list-filter-phase-one.md`。
- 独立审查发现的详情刷新阻断、缓存新单无法定位均已修复并复核。`git_sweep.py --no-fetch` 为本地快照：本任务修改未提交，main 另有他人修改，旧分支/stash 均未处理。第 5 项之后及其余旧页面逐批推广未启动；真实生产登录/单据写入验收待以后发布。

## 2026-10-01 任务中心一期（Codex，已合并推送并部署）

- 一期包含个人任务树、看板、模块地图、详情、快速建任务、AI 草稿、构建期导航清单和简版每日简报；二期 git 上报器与三期 MCP 未启动。分支 `codex/task-center-phase1` 经主目录合并为 `d76d743d0842cc804723bfaab33bda6f3392efaa` 并推送 `origin/main`。
- 办公室统一入口固定该提交先完成 `--prepare-only`，再完成办公室与云端完整发布；`release_id=0515c105f5624af287ac14c2c17c35cd`，回执 `MANAGED APPLICATION RELEASE COMPLETED`，`deferred=[]`，共享数据库已迁移到 `173_task_center`。办公室和北京后端、两地主站静态资源、色块路由均在完成清单；出库调度保持启用且回执 `verified`。未纳管的独立服务不在本次发布范围。
- 办公室生产后端已配置 `TASK_MODULE_SYNC_ENABLED=true` 并重启；实查 113 个导航模块处于启用状态，`admin` 角色具有 `task:read`、`task:write`。两站公开 `/health` 均返回 `ok/connected`，匿名请求 `/api/task/modules` 均返回 403。合并后后端定向 86 项、前端 9 项、Vite 生产构建、约定检查与 Alembic 单 head 检查通过；原全量后端基线有独立的 AI Chat 删除失败用例，本次未修改该模块。
- 仍需亮哥登录验收：创建任务并在树形出现；抽屉改状态及父任务未结束子项确认；看板拖拽完成确认；模块地图筛选；删除与回收站恢复；AI 草稿和降级；今日简报与下一次 08:53 钉钉推送。当前只核实了 `admin` 角色权限，其他实际使用角色按需授权。


## 2026-10-01 Ark 列表页规范推广（Codex，合并推送交付，未部署）

- 来源分支 `codex/ark-list-ui`。从主目录当时未提交的列表页改动复制到独立工作树继续收尾；用户已授权合并 main 并推送 origin，集成时保留主目录其他任务的未提交内容，交付后清理本任务工作树与本地分支。本次不部署。
- 通用 `TableTools` 晋升至 `frontend/src/components/`，`useTableView` 按页面键保存列显隐和密度；标准列表页采用筛选区、操作行、表格、分页的卡片结构。补齐发票/回款/库存、设计、客户、素材、生产、系统管理、订单经营客户行动清单、公海背调批次、客户开发信和运行中心等列表页的工具接线，修复前序改动中缺失的模板变量与事件处理。
- 审计 `frontend/src/views` 中 117 个含表格的 Vue 文件：79 个列表视图接入 TableTools；其余 38 个是报表摘要、详情子视图、导入/修复预览、配置编辑表、弹窗或抽屉，保留各自操作语义并沿用通用表格样式。
- 独立审阅发现原生全屏会使卡片外的业务弹窗不可见，已改为视口铺满卡片并保留弹窗层级，Esc 或 KeepAlive 路由停用时退出；节日订单和半成品多标签表格确保当前标签至少保留一列。设计管理页面拆出排期与编辑对话框，补齐原模板未绑定的 `confirmRow`。
- 验证：前端生产构建通过；列表与模板绑定相关 29 项 Node 测试通过；`scripts/check_conventions.py` 与 `git diff --check` 通过，UI 债务基线按本次清理重新生成且相对 HEAD 无新增指标。全量前端 Node 测试 821 项中 815 通过，6 项登录地图动画测试因既有 Canvas mock 缺失 `save()` 等接口失败；该登录页源码与测试不在本次改动范围。公海批次树新增规范类名后，同步调整原有类名断言为检查类是否存在。Git 巡检使用 `--no-fetch` 本地快照；浏览器登录态逐页实机验收尚未执行。

## 2026-09-30 私海客户一键补全（Codex，未部署）

- 工作树 `D:/commission-system/tmp/private-customer-enrichment`，分支 `codex/private-customer-enrichment`，基于 `54f77438`；用户已授权增加单客户入口、为全部私海客户创建补全任务，并随后明确授权合并推送；本轮不部署。合并推送完成后清理该临时工作树和任务分支，交付材料保存在主目录 `tmp/private-customer-enrichment-delivery/`。
- 工作区新增一键补全、15 秒任务状态刷新、研究结果与来源、管理员质量复核；后端 GET/POST `/api/customer-hub/customers/{id}/enrichment`，权限与实时客户范围校验，公海/DNC 拒绝，同客户进行中或待审核任务复用；转属旧任务不复用。
- `private-enrichment-v1` 沿用 full_research 队列，冻结官网、公司业务、公开商业联系方式、主营产品四项重点、可见既有事实/渠道/当前人工修订和来源。候选事实通过历史 Agent Run 永久隔离于正式档案，质量通过不等于采纳，不新增数据库表或迁移。
- 批量脚本增加 `--all-private --enrichment`；2026-09-30 16:48 线上只读预览：170 位私海客户，170 位符合范围，DNC/不可解析均 0，既有本策略任务 0。名单回执在主目录 `tmp/private-customer-enrichment-delivery/enrichment-scope-preview.json`，`task_creation_executed=false`。必须先在所有档案编译实例发布候选隔离代码，再创建该批任务；创建授权已具备，无需重问范围。
- 验证：相关后端 107 passed / 1 skipped（既有环境条件测试）；前端既有工作区 14 项通过，Vite build 通过；Chrome 模拟接口验证单击入队、重复按钮禁用、完成待审、来源链接、质量审核、390px 布局，零页面错误。截图与脚本保存在主目录 `tmp/private-customer-enrichment-delivery/`。截图发现卡片限制抽屉，已加 append-to-body 修复。增量约定检查通过。
- 独立审查的候选隔离、历史 Run、转属任务、人工修订对照问题已处理并有回归。主目录既有 `.pnpm-store/` 和其他工作树未改动。Git sweep 使用 --no-fetch 本地快照。
- 尚未发布、尚未批量入队；北京 Agent 实时状态未确认，使用已有 ark_office 密钥探测被 SSH 主机信任校验阻断，当前用户 known_hosts 没有北京 IP/域名记录，未跳过校验。部署前需取得覆盖两地主站的发布授权并恢复可信部署连接。

## 2026-09-30 客户素材 Product type 顶部筛选（已实现，待部署）

- “客户拍摄素材”的“本批素材”区域新增 Product type 标签筛选；客户素材门户内部预览与外部站点顶部也可按该维度筛选。支持多选同维度标签，并与文件名、媒体类型和组内其他标签筛选共同生效；无可用 Product type 标签时不显示筛选行。
- 分组与预览状态单元测试 10 项、拍摄工作区及客户门户浏览器回归、前端构建、增量约定检查通过。生产部署待进行。

## 2026-09-30 手机出库质检连续扫码沿用操作人（Codex，未部署）

- 分支 `codex/shipping-operator-return`：从出库单照片列表返回主页或提交成功后，结束本单会话但保留本单操作人，下一单可直接扫码；换人仍可在主页点选。刷新/重开页面不恢复人选，人员不在刷新后的候选名单或身份失效时清除默认选择。
- 更新主页和提交反馈文案；定向前端回归 20 项、前端构建、增量约定检查及 `git_sweep.py --no-fetch` 已通过。未部署，未用真实手机和出库单做现场验收。

---

<!-- 以下为客户下单门户专题进度记录：原 codex worktree 交接日志（2026-09-30 至 10-08），按该任务内部版本号组织。 -->

## 客户门户 v1.73 范围剥离：门户边界止于方舟 PI（2026-10-08，Kimi 执行）

- 业务决定（亮哥）：门户功能边界到生成方舟正式 PI 为止；回款、出库与履约完全由方舟既有模块按原有流程处理。ReceiptIntent 创建期草稿移除（完全复用方舟现有发票→回款入口）；v1.96/v1.97 价格写屏障保留、不再向回款/出库 writer 扩展；旧自动回款 generate_ready 主体政策与接入、显式回款内核接线、后台出库执行器切换与发布围栏、全部 writer 共同协议划入独立加固专项，移出门户上线门禁。
- 方案验证（先于改动）：审批链路 approval_service→invoice_adapter→create_invoice 无门户专用 ReceiptIntent 代码，草稿来自 create_invoice 内既有 save_draft(new=True) 钩子；手工回款 create_service 不依赖 intent；guard_edit/guard_delete/describe/preflight/pi_void 均兼容 row is None（同步小满缺回款资料的拦截提示与无 intent 的普通发票一致）；迁移 172/173（合并时重编号为 176/177，最终父版本 175_receipt_recovery）无 ReceiptIntent 结构；双前端无 ReceiptIntent 引用。
- 代码改动（唯一产品改动）：`backend/app/invoice/service.py` create_invoice 对 source_type=="portal" 跳过 save_draft(new=True)；update_invoice 既有 save_draft(new=False) 惰性入口保留（与历史发票同口径）。无迁移、无 schema、无 API 变更。
- 测试更新：tests/portal 三文件（approval/live_browser_trade/pi_void；pi_void 的 intent 阻拦与保留场景改显式 fixture）；tests/portal_mysql 14 文件（审批副作用断言改"无 intent"，需要 intent 的场景改显式 db.add；receipt/shipment 子树经 setup_push/read_app 两处 fixture 覆盖；test_mysql_incomplete_pi_http 的 count==1 因 update_invoice 惰性建 eligible=0 草稿而有意保留）；portal_mysql README 与 pi-writer-inventory.json sources_sha256 同步。
- 文档：README/00 新增 v1.73 顶段；04 建票事务顺序与自动回款门禁框架、03 回款旧入口接入边界、06 T37 与 1.31 链路断言、08 门禁重分类（门户门禁收窄、移出项保留为独立专项）已更新；docs/api-reference.md 审批描述同步；历史 v1.xx 段落保持原时点。
- 验证（本机，解释器 D:/commission-system/tmp/okki-test-venv/Scripts/python.exe，TMPDIR 指向可写目录规避默认 Temp 拒绝）：tests/portal SQLite 717 passed / 1 failed / 2 skipped（唯一失败为既有 test_portal_permission_seed_is_repeatable_and_preserves_kind，失败点在 seed_role_permissions→lock_authority 缺 ark_order_portal_auth_barriers 表，不经过 create_invoice，与本改动无关）；既有回款套件 test_receipt_management/protocol/batches/preflight_fields 129 passed；tests/portal_mysql 收集干净，29 passed / 2705 skipped（本机无 --portal-mysqld，MySQL 用例全部干净 skip，未执行；14 个改动文件 py_compile 通过）。
- 未 commit/push/merge/部署，改动保留在本 worktree 供审阅（AGENTS.md：该 worktree 归属 codex，本轮未做任何 git 写操作）。待办：14 个 MySQL 套件文件需在有专用 mysqld 的环境重跑；收窄后的门户上线门禁（迁移 126 链与 176/177 真实库演练、库存/合同价/SMTP/存储真实联调、边界内 64T、B01–B07、双客户双业务员试点、统一入口发布演练）仍 OPEN；独立加固专项各项原证据保留、不阻断门户发布。

## 客户门户 v1.97 真实 HTTP 改价、客户接受与员工审批的提交顺序（2026-10-07）

本轮为有效进展：新落地 test_mysql_price_commit_race.py，并更新 pi-writer-inventory.json 的该测试 SHA 和限定范围；原业务源码、价格算法及双方前端源码/dist 共2252个已有文件 SHA 不变，不重复构建或改原型。正式测试实际来自本任务 worktree，8个新并发场景 + 88个价格当前权限场景 + 6个库存/价格源变化场景共102collected/completed/passed，420warnings、181.47s；session37177实际terminal0，父进程exit0，原始stdout/stderr仅计数后丢弃。不能把此前不同候选7+2通过相加声称最终8通过；上述102全部执行的是正式最终SHA。

8个场景是accept/approve × price/decision先执行 × commit/rollback。订单/提案准备使用实际业务service与受控镜像fixture，竞争双方使用实际app.main、原JWT/客户cookie、CSRF/If-Match和HTTP路由，无dependency_overrides。仅一个真实客户价规则 -10%→-5%，不是九类价格入口或外部价格生产者全部竞争认证。先执行者在真实标记Session的root before_commit完成flush后暂停，明确排除nested/savepoint；后执行者真正发出authority FOR UPDATE。performance_schema联查requesting/blocking双方实际连接ID、表ark_order_portal_auth_barriers、PRIMARY/RECORD及字符串主键authority，不用任意等待或固定sleep冒充锁证据；独立observer确认16模型完整已提交快照仍不变，之后才释放提交/回滚。

改价先提交，后续接受/审批409 PROPOSAL_CHANGED，未接受或建PI；审批仅增加原设计的失败审计。接受/审批先提交，后续改价可成功，已确认的revision/历史RequestLine/PI均保持原128USD金额，审批只生成一张归属当前员工的PI与draft ReceiptIntent。改价先回滚，等待的决定可按原价成功；决定先回滚，等待改价成功，原决定重试校验新价并409，不复活已回滚的接受/PI。每种回滚均观察真实engine rollback，且无该连接root commit；不是只看HTTP错误。原16模型所有历史行逐列不变，仅明确目标订单状态/version/接受字段、目标revision接受身份/时间和目标价规则的明确字段允许变化，并核验updated_by、accepted_revision_id/当前客户账号、当前状态及唯一PI关联。

早期测试定义问题全部保留有限终态：candidate/session46800实际terminal1，0pass/8fail（误将实际字符串authority主键当成id，尚未执行竞争）；corrected/session52451实际terminal1，2pass/6fail（缺价规则updated_by允许字段及审批HTTP封装断言）；final/session82170实际terminal1，7pass/1fail（仅审批root回滚响应尚未按实际AdminRoute封装）；reviewed/session18697实际terminal0，2pass（-k中的decision也匹配函数名，实际选择了审批两种回滚，不能记成1）。这些不是产品RED。审批注入的HTTPException仍执行真实rollback，再由现有AdminRoute返回409/AUTH_REQUIRED；测试验证实际契约，不改产品错误封装取巧。

独立审查代理返回账户用量限制而终止，本轮按completion-checklist做单独一轮自查，并记录审查不可用，未伪称独立通过。最终2文件SHA、上述102实际测试、139来源SHA/AST/文档链接检查及收尾结果保存在tmp/portal-v197-final-evidence.json、portal-v197-checks-result.json和portal-v197-reverify-result.json。5个自有MySQL运行均先取得真实工具terminal、pytest/父exit一致、Shutdown complete、精确端口停止及绝对路径/无reparse证据后，清理10个data/temp目录；运行日志、runtime、有限报告、来源和回滚备份保留。

整体目标仍未完成，未commit/push/merge/部署/写共享库。下一项本地必要工作仍是可达linked-run的当前员工权限及跨外部I/O的锁边界，不能称剩余均被外部条件阻塞。自动Intent身份政策与既有6失败、真实历史126切换/10类writer实例围栏、实际库存生产者可信SSH或源码及每组件单位/时间、B01–B07业务配置、T54旧构建恢复、全64T/外部接口/SMTP/storage/生产演练仍未证明；本轮8种客户价规则竞争不关闭整体T64或全部writer。

## 客户门户 v1.96 报价源九个写入口的当前权限与永久屏障（2026-10-07）

上一轮v1.95真实验证并接入客户命令崩溃恢复，本轮为有效开发进展，不靠继续追加同类局部测试缩小目标。读取开发总纲W01–W07及T54/T55/T62/T64、实际源码、部署登记和既有有限终态后，独立只读审计找到两个无需等待自动Intent政策的必要缺口：九个价格写入口仍按JWT旧权限直接写库；门户PI可达的linked-run阶段仍缺当前授权/完整锁外取证。本轮完整修复前者，后者明确保留，不假称已经只剩外部阻塞。

正式修改invoice/router.py，新增invoice/price_authority.py与test_mysql_price_authority.py，并刷新pi-writer-inventory.json。配件价upsert/delete沿用invoice_price:write；标准价upsert/delete、工作簿import、颜色分类upsert/delete、客户价规则upsert/delete沿用invoice:admin。JWT只定位员工，首业务查询前要求fresh事务、永久authority屏障和当前DB动作权限，调用者保留原唯一commit。verified pre-portal分支继续原JWT动作语义，不臆造新权限或业务员范围。门户OFF不解除已安装协议。upload先读取本地上传数据再取业务锁，原价格算法、配件精确SKU校验、金额/导入行为不改。价格维护不递增授权版本或直接重写已接受订单/PI；后续交易仍独立校验当前价格。

原产品RED/session77674实际terminal1：9collected/completed/failed，每入口先用有效账号完成合法阳性，再由实际管理员停用员工，旧JWT仍可改价，均在拒绝403断言失败，不是初始无权限或非法body。首候选green/session30254实际terminal0：76passed、360warnings、133.33s，覆盖9×3撤权×ON/OFF两态、9×新grant×两态及4种非fresh调用者。恢复阳性复用原JWT，新grant阳性使用登录时未含动作的新授权；不把新grant挡在旧JWT依赖外。

独立审查指出授权users/roles/permissions查询的SQLAlchemyError会落全局500的P2。已仅授权段窄捕，返回固定安全/private no-store503；logger/stdout普通异常分别保护，不捕硬中断，其他HTTP/锁超时分类保持。reviewed/session80897实际terminal1：88completed、76pass/12fail，12故障用例在前面命中、零价格写、503/no-store断言均通过后错误读取旧HTTPException响应message字段，既有契约实际为detail。修测试为精确整个detail正文，未更改产品错误契约，同时按审查建议明确两个sink各命中一次。final/session60260实际terminal0：12pass、42warnings、41.16s；此为最终故障子集，不与76或88相加为一次整批。

正式/session40365实际terminal0：96collected/completed/pass，0fail/error/skip、407warnings、166.98s。包括最终88价格授权/故障规格、原六库存/价格变化后的submit/accept/approve合法恢复规格，以及两项实际main生命周期规格；在任务worktree执行，不称完整64T。每次拒绝/恢复核验16模型全列，前三个价格模型之外的13类订单/PI/Intent/修订/谱系/审计/outbox保持；auth/login合法写与root已提交的撤权不在商业零变化快照内。故障后原命令合法阳性保持，两个sink精确命中。上游产品/SKU和库存仍为受控数据，非真实导入器/供应商或完整历史FK证据。

最终四目标SHA独立静态复核无新增具体P1/P2，不认证运行。源码清单新增price_authority、price_service、accessory_price_service及本批测试摘要共138项，router AST行/calls同步、九价格phase明确有限范围；原134项其余SHA保持。2249个其他业务源码/测试、两端src及dist逐文件SHA保持。没有UI修改或重复构建，没有commit/push/merge/部署、生产/共享库写或真实外发。原输出仅父进程内存计bytes后丢弃，保留白名单终态/错误帧与分类；候选错误和产品RED分开记录。

五个实际终态owned MySQL经result/parent退出匹配、Shutdown complete、精确端口停止、绝对目录和无reparse守卫，只清理10个data/temp；保留源码、有限结果、日志、runtime和回滚备份。最终证据D:/commission-system/tmp/portal-v196-final-evidence.json，接入回执portal-v196-formal-before/application.json。10篇规范文档仍v1.72、64条T/20条F/18条A及v1.55/v1.58冻结包保持，进度只在本交接维护。

完整目标active。优先后续实施：实际价格写与客户接受/员工审批的两种提交/回滚顺序、exact legacy171行为，然后门户PI可达linked-run的分阶段当前invoice:sync/范围、锁外I/O、原效果事实与未知结果恢复（关联GET expire写同样须保护）。本批仅证明已安装协议ON/OFF及各命令当前授权，不能由源码屏障推断已实际验证竞争或旧制品。自动回款主体政策及六旧失败、126真实维护材料/人类批准、全部writer/兼容旧制品连贯恢复、完整64T/B01–B07经营试点、真实库存生产者/价格/供应商/SMTP/存储/生产恢复继续OPEN；SSH信任缺口未解锁，没有绕过或重复远端尝试。

## 客户门户 v1.95 客户提交与接受方案的进程终止恢复（2026-10-07）

本轮在上一轮审批进程终止证据上，补齐客户submit/accept两命令各自真实commit前、后被kill的四个有限子项。正式新增test_mysql_customer_command_crash.py并扩展approval_crash_worker.py，默认approve路径与12模型SQL gate保持；2248个其他业务源码/测试及双端dist逐文件SHA保持。没有API、模型、迁移、角色、产品逻辑或UI改变，不重复构建；未commit/push/merge/部署、未生产/共享库或真实外发。

新spawn子进程通过既有owned MySQL地址/端口/凭据和socket守卫，调用真实order_service.submit或proposal_decisions.decide，并由调用者执行真实db.commit。提交前检查点在完整flush后、commit前；提交后先完成真实commit再等待。父进程确认检查点、PID与仍存活后直接kill/join，必须实际非零退出、无成功回执消息、精确原数据库连接断开。范围为领域服务与调用者事务边界，不冒称HTTP/router/main实际请求、主机断电或数据库崩溃。

提交前终止要求原14模型全列保持且无半请求/半接受；新进程用原幂等键和原命令恢复，库存/价格/商业写探针必须阳性。提交后终止要求完整自然幂等记录已提交；新进程把库存和价格探针设为不可用仍须回原成功回执。第三个新进程再回放原命令，商业写与库存/价格读取均为零。客户命令真实authenticate会续期当前会话idle_expires_at/updated_at，每次合法回放精确一条PortalSession更新，独立auth_writes计数；其余会话全列和所有商业旧行全列保持，不能把正常会话续期说成商业零写失效，也不能将其默许为其他字段变更。

14模型使用各自真实id列进行全列快照，原12商业模型外加Quote与PortalSession。submit精确新增请求/提交修订/明细/审计/outbox各一，原报价只允许消费状态和updated_at变更；商品3pack×27为81，费用待确认，提交状态version1。accept仅新增命令回执/审计/outbox，指定请求到ready_for_review/version3、指定修订记录当前客户接受；完整128方案与修订hash保持。两命令均无Invoice、ReceiptIntent、Conversion、Publication或PiAmendment新增；后续业务员审批仍需走原入口，不能提前生成PI。

候选/session10556实际terminal0：4collected/completed/pass、0warnings、51.66s，没有失败候选。两目标最终SHA独立静态对抗性复核无新增具体P1/P2，核对默认审批gate、IPC敏感信息不落盘、会话与商业写分离以及14模型增量；静态审查不替代运行或生产认证。正式/session76213实际terminal0：21collected/completed/pass，0fail/error/skip、8warnings、70.1s；范围为新客户4项、此前审批/SQL gate9项、原accept-and-approve响应丢失8项，原规格未删改，不累计候选或称完整64T。

实际pytest与父进程退出均0，stdout/stderr只在父内存计bytes后丢弃。四个客户报告与两个旧审批报告在各自全部断言后生成；旧审批唯一PI/谱系与draft ReceiptIntent断言保持。两个实际终态owned MySQL经result/parent退出匹配、Shutdown complete、精确端口关闭、绝对边界和无reparse守卫，只清理4个data/temp目录；报告、日志、runtime、候选源码、接入回执和回滚备份保留。最终证据D:/commission-system/tmp/portal-v195-final-evidence.json，接入回执portal-v195-formal-before/application.json；专题v1.72、134 writer源及冻结包保持。

完整目标active。客户领域服务四个明确边界及此前审批边界已验证，其他命令/进程、权限撤销竞态、真实外部在途FACT、数据库崩溃和旧制品连续恢复仍未证明。自动回款执行主体政策及旧六失败、126真实停写撤权/人类批准、全writer/完整64T/经营试点、真实库存生产者/价格/供应商/SMTP/存储/生产恢复继续OPEN。SSH主机信任缺口仍未解锁，没有绕过或重复远端尝试。

## 客户门户 v1.94 审批提交前后真实子进程终止与恢复（2026-10-07）

上一轮v1.93完成库存源只读核查/辅助路径P2修订，是有效进展。本轮核对门禁后，补齐不依赖生产接入的T49/T64有限子项：正式新增approval_crash_worker.py与test_mysql_approval_crash.py两个验收文件。2247个其他业务源码/测试及双端dist逐文件SHA保持；无API、模型、迁移、角色、产品逻辑或UI改变，不重复构建。未commit/push/merge/部署、未生产/共享库或真实外发。

新spawn子进程在conftest实际地址/端口/凭据守卫下连接同一owned MySQL，额外socket connect/connect_ex仅允许该回环端口。调用真实approval_service.execute事务入口，库存和部分供应商辅助字段受控，价格仍使用实际标准价/客户规则。提交前检查点在业务完整flush后、真实commit前；提交后先执行真实commit再等待。父进程确认marker/PID/仍存活后直接kill并join，要求实际非零exit、无成功回执消息和精确原连接断开；不是异常替身或受控503，也不是HTTP/main/生产进程认证。

提交前强制终止时独立连接见原12模型全列快照，终止后仍无半PI/谱系；新进程合法执行原命令，首次库存/价格/写探针须阳性。提交后终止时父连接已见完整唯一PI/原成功回执，新进程即使库存和价格探针设为不可用仍返回原回执，DML零增量。两场景均再由第三个新进程回放原命令，只回原结果，12模型全列不变。原请求仅允许status/invoice_id/row_version/updated_at变化，所有其他旧行全列保持、各模型新增数精确；PI128、3pack×27商品81与47费用、当前业务员、同accepted revision/Conversion/Publication、真实invoice fingerprint一致。ReceiptIntent仍draft/无receipt/attempt/lease，Invoice无同步单号、未自动出库。

子进程有限SQL gate覆盖当前服务使用的语句与同库12模型商业写，记录表名计数；不称任意SQL/触发器/UDF沙箱。独立审查发现初版只探测常规INSERT/UPDATE/DELETE会漏REPLACE/INSERT IGNORE的P2，已覆盖修饰语、前导注释、显式schema及拒绝WITH写，加入6个拒绝形式和1个正常ORM/read/固定参数化timeout SET阳性。当前最终两目标SHA独立静态复核无新增具体P1/P2，不认证执行或生产。

候选初版/session4759实际2failed：错误假定快照首列必为id，portal继承列次序导致旧修订错配。修为12明确模型各自真实id列，不放宽字段。corrected/session64963实际2pass；第一DML增强reviewed/session42372实际2pass，均非最后增强证据。增强final/session45993实际6pass/3fail，辅助正则正常UPDATE分支误多要求空格；修后verified/session66252实际7pass/2fail，有限gate拒绝了真实lock_timeout的固定SET。仅放行其完整参数化形式并加阳性，最终ready/session79152实际terminal0：9collected/completed/pass、35.62s。中间失败均测试工具缺口，不冒称产品事务缺陷。

正式/session45894实际terminal0：23collected/completed/pass，0fail/error/skip，0warnings、67.85s。范围为新9项、原proposal_process期限/时区12项、原重复审批竞争2项，加载路径为任务worktree；不累计候选通过或称完整64T。原stdout/stderr仅父内存计bytes后丢弃，保留有限frame/分类/终态。两个crash报告全部断言后落盘，原12期限和两竞争规格未删改。

七个实际终态owned MySQL经result/parent退出匹配、Shutdown complete、精确端口关闭、绝对边界与无reparse守卫，仅清理14个data/temp目录；保留报告、日志、runtime、源码和接入回执。最终证据D:/commission-system/tmp/portal-v194-final-evidence.json，接入回执portal-v194-formal-before/application.json。专题v1.72/134 writer源及冻结包保持。

完整目标active。此次真实终止仅证明审批事务入口在两明确commit边界的恢复；其他命令/进程、数据库崩溃、真实外部在途FACT和旧制品连续恢复仍未证明。自动回款执行主体政策及旧六失败、126真实停写撤权/人类批准、全writer/完整64T/经营试点、真实库存生产者/价格/供应商/SMTP/存储/生产恢复继续OPEN；上一轮SSH主机信任缺口未解锁，不绕过或重复远端尝试。

## 客户门户 v1.93 库存同步器观测时间契约核查（2026-10-07）

上一轮v1.92正式16项通过是有效开发验收进展。本轮只读核查B02生产接入前提，不新增业务代码、测试、接口或部署；2246个既有业务源码/测试/双端dist及v1.92新增规格SHA均保持，不重复运行测试或构建，也不把历史通过数算为本轮结果。

参考站lib/inventory-client.ts按name/enable_count读取数量；app/api/inventory/route.ts中的queried_at在拼装HTTP响应时生成。此字段是查询响应时间，不能证明供应商库存成功观测时间，不能作为门户synced_at的替代。仅静态读取参考源码，未调用公共库存MCP或业务数据库。

当前门户inventory_source.py只接受明确namespace、synced_at、Asia/Shanghai或UTC及逐标准product_id:sku_id单位契约；按标准ID过滤活跃行，合计采用最早有效时间，任一活跃分量数量/时间不合格使整个SKU未知。已有开发契约明确：每次成功获取库存均刷新各行时间，数量不变也刷新；时区、精确数量/单位、重复记录、漏删仓库行及不完整同步须有导入器证据。本轮未证明真实导入器满足这些条件，未扩大默认120秒时效或以请求时间替换观测时间。

仓库部署登记将独立okki-index指向北京ubuntu@154.8.205.162；登记不是当前运行认证。使用现有static_sync.remote_python的BatchMode和StrictHostKeyChecking=yes，只尝试读取已登记路径下index.js；实际SSH exit255、stdout 0bytes、stderr 117bytes，主机密钥校验失败，未收到远端源码。原stderr只在父内存分类后丢弃，未持久化原诊断或源码。没有执行同步器、读取env/凭据、调用供应商或数据库、控制进程、改known_hosts或接受未验证主机密钥。

随后仅只读解析本机SSH配置并查对应known_hosts条目。默认配置为ask，但本次调用显式yes；已解析四个标准known_hosts候选中仅用户主文件存在，登记主机匹配0条，其余文件不存在。首次非提权本地检查因读取该文件被沙箱权限拒绝；经窄范围只读工具审批后检查成功，不是自动审批拒绝或主机已被可信验证。无需也未读取私钥。本轮生产源核查仍未完成，解锁需要可信渠道核验的主机密钥/连接路径，或当前部署同步器源码的本机可读路径；已集中提出该缺失信息请求。

独立静态审查发现只读辅助脚本一处P2：先resolve再仅检查父目录，允许index.js链接到同目录其他文件。实际SSH未执行脚本，无文件读取或泄露证据。已修为固定根路径、O_NOFOLLOW目录相对固定index.js打开、fstat普通文件与上限/读前后大小时间一致检查；辅助脚本仅在本地做语法检查及独立静态复核，不称Linux远端运行验证。未绕过当前主机信任缺口或重复远端尝试。

有限证据D:/commission-system/tmp/portal-v193-producer-audit-evidence.json，含实际失败/本地信任查询结果、八个只读源与三个辅助脚本SHA、既有源码保持证明；不含远端源码、原SSH输出、SQL或参数。专题v1.72及原生产门禁不变。本轮只同步交接，不将“已核查消费者/参考站”写成“已核查生产者”。完整目标active；原旧回款执行主体政策与六项失败、126实际停写撤权/人类批准、全writer恢复、完整验收及真实库存/价格/供应商/SMTP/存储接入仍OPEN。

## 客户门户 v1.92 报价到建票期间源变化与恢复（2026-10-07）

上一轮v1.91是正式库存时间展示/真实隔离镜像SQL进展。本轮按T29/T33/T59补证，正式新增唯一test_mysql_application_inventory_changes.py；2246个其他业务源码/测试及双端dist逐文件SHA保持。无产品代码/接口/模型/迁移/角色/样式改变，不重复构建或状态测试。未commit/push/merge/部署，未生产/共享库或真实外发。

六参数是实际main/OTP/Cookie/员工JWT、自有MySQL镜像和当前标准价/客户规则：submit/accept/approve三个命令前分别提交库存或价格变化。独立importer连接只使用conftest全局地址/端口/凭据守卫允许的同一owned DB，更新确切两条活跃SKU镜像或当前客户一条价格规则；应用engine商业DML fence保持，禁用/其他SKU镜像及其他规则全列不变。源更新在HTTP前提交，属于确定性命令间变化，不称事务内竞争、实时供应商或真实导入器认证。

真实报价81后，库存两行变为合计20g（5g缓冲后不足3pack×20g），三阶段409 STOCK_CHANGED；客户-10%变0，提交409 PRICE_CHANGED，接受/审核409 PROPOSAL_CHANGED。失败边界原十个商业模型和Quote全列不变；审核仅产生准确order.approval_failed安全审计，其他两阶段审计全列不变。恢复库存合计80g后继续合法原命令；价格变化必须新报价或拒绝旧提案/新完整提案并重新客户接受，不静默替换已接受版本。旧接受回执重放只返回原结果和当前awaiting_customer，新提案未接受仍拒绝建票。价格accept/approve两场景原Revision/RequestLine全列保持。

每场景只生成一张当前buyer/标准SKU/当前业务员PI、一Conversion、一Publication、一ReceiptIntent草稿；库存场景总额128、价格场景137（商品81/90加完整47费用）。真实PDF包含该金额，库存和价格再次恶化后PDF完整文本不变。原submit/accept/approve成功命令各回原回执；原商品金额与未知提交总额保留，金融/outbox/审计全列不变。提交价格场景在成功新body后旧body同key409 IDEMPOTENCY_CONFLICT。镜像、客户价规则、标准价和颜色价类SELECT分别计数；正常报价先证明rule/std探针阳性，三成功命令回放均无这些源读取增量。金额/数量/标准SKU/P0无推送、预占、出库和实收保护均保留。

初版/session76822实际6pass、46.44s，不作最终增强证据。独立审查发现价格源未计数的P2验收缺口，已加独立价格探针；又发现Quote全列基线取在正常submit前，把合法consumed变化误当失败。增强/session24680实际2pass/4fail，均116行该基线断言，非产品缺陷。基线移至源更新后、待测HTTP前，内容快照仍保留；corrected/session67698实际6pass。最后report移至TestClient退出、外部/DML守卫及importer.dispose之后，最终reviewed/session78588实际6pass、41warnings、42.42s。一次verified启动器误指旧child，实际exit1/尚未收集或建库；修订使用全新prefix，不重用已终态目录。

正式/session92726实际terminal0：16collected/completed/pass，0fail/error/skip，66warnings、57.3s。十六项是新六场景、原三个价格/地址/数量重新确认、原两个库存浏览器、原两个实际应用API和三个安全诊断；不累计候选/历史通过或称64T全绿。原库存两个浏览器report均pass，新六个有限API report仅在全部本例断言与清理后落盘；运行加载本任务worktree。原stdout/stderr只在父内存计bytes后丢弃，保留有限枚举/frame/结构结果。最终唯一目标独立静态复核无新增具体P1/P2，不代跑认证运行。

五个实际终态MySQL经退出匹配、Shutdown complete、精确端口关闭、绝对边界/无reparse守卫后只删十个data/temp目录，保留报告/日志/runtime/源码及接入回执。最终证据D:/commission-system/tmp/portal-v192-final-evidence.json；接入回执portal-v192-formal-before/application.json。专题v1.72、134 writer源与冻结包保持，新增差异无尾随空白；原handoff两处Markdown硬换行保持。

完整目标active。原六项旧回款失败/执行主体政策、126真实停写撤权与人类批准、全部writer/旧制品恢复、完整64T/经营试点，以及真实导入器时效口径/价格/供应商/SMTP/存储/生产恢复继续OPEN。本轮补强本地现有实现的实际验收证据，不代表生产接入、事务内库存竞争或整体完成。

## 客户门户 v1.91 库存观测时间与真实镜像 SQL（2026-10-07）

正式接入四个目标：CollectionView目录卡片和商品弹窗显示Stock checked完整北京时间；新实际浏览器驱动、新隔离MySQL规格、owned_process精确追加driver栈名。现有beijingTime负责格式化，不改库存/价格/权限/交易算法或持久表。2237个其他源码/测试/员工构建SHA保持；旧客户dist备份，新客户构建34modules/syntax实际exit0且逐文件SHA与候选一致。未commit/push/merge/部署，未生产或共享数据库/真实外发。

最终候选/session49943实际terminal0：3collected/completed/pass、22warnings、35.04s。正式/session50743实际terminal0：11collected/completed/pass、0fail/error/skip、147warnings、114.53s；包含库存fresh/stale两项、原客户拒绝取消/复购/数量错误/鼠标/键盘/长内容各一及三个安全诊断。八份浏览器report均pass，实际模块来自本任务worktree；不累计历史/候选通过数或称64T全绿。formal runner的描述字符串沿用v1.90，版本标签过时；真实11项选集、模块路径与八report证明本轮范围，原JSON保留。候选130/130状态测试为本轮实际执行，正式仅重构建和syntax，不称状态测试又跑一次。

旧bundle/session8000实际2pass/1fail，fresh卡片缺Stock checked形成真实UI缺口RED；stale已通过。初次新bundle/session97948也是2pass/1fail，但下载等待超时；新增实际HTTP响应取证/session65856为PDF 500，不弱化断言。诊断session91025/13829/42492已终态，临时observer有自身定位/生命周期错误，属于测试诊断失败，不称产品Bug或通过。原PDF外壳在发送已生成PDF前要求客户映射v1，新增场景没有此前提。最终在commerce写入fence前通过真实mapping_service.publish建立默认空entries映射v1，之后全列映射快照不变；原PDF保护与外壳不改，所有临时observer移除。测试中的不存在inventory_snapshot/quantity字段修为实际Quote库存证据、RequestLine.qty和unit_weight_grams/金额/canonical ID/hash；独立复核发现qty测试P2，已关闭。最终四目标静态复核无新增具体P1/P2，不认证运行或生产。

新规格直接调用真实inventory_source SQL读取隔离okki_inventory薄镜像，真实当前价格服务读取标准价30和客户-10%得到27。同product/sku有效两行60g+20g，禁用9999g和另一SKU9999g排除；两条有效fresh时刻相差2秒，Quote精确保留最早时间、80g、20g/pack换算及5g安全缓冲。客户以LosAngeles浏览器时区验证完整北京时间，目录/弹窗各1440/390/320布局与遮罩图；真实Tab/Enter核心交易320px完成3pack报价81→提交→员工HTTP完整81提案→当前客户接受→员工HTTP审核→PI和真实PDF下载。PDF实际200/application/pdf，下载全文与真实返回PDF全文相等并含81.00/Unit pack。当前buyer/canonical SKU、revision hash、Quote consumed、唯一ReceiptIntent草稿和无真实外部/非法写守卫均核验。三宽仅目录/商品弹窗布局，不称三宽完整交易或新增员工UI证明。

部分库存行过期5分钟时整个SKUunknown、无观测时间、弹窗Availability pending且不能加入；实际手工quote POST503/INVENTORY_UNAVAILABLE。Quote全列、原九个商业模型全列、镜像所有行和映射全列不变，无PDF。两场景均断言实际镜像SELECT至少两次。主线程查看候选fresh320商品图，时间标注、数量和加入动作可见；全editable遮罩。以上验证真实SQL/计算/订单代码在自有合成镜像上的行为，不认证生产导入器时间字段语义、供应商实时库存、竞争预占或SMTP送达。

八份本轮自有MySQL经实际terminal/parent退出匹配、Shutdown complete、精确端口关闭、绝对边界/无reparse后，仅清理16个data/temp目录；保留日志/runtime、有限失败/报告/遮罩图及源码/旧dist回滚，候选junction未递归删除。最终证据D:/commission-system/tmp/portal-v191-final-evidence.json；四目标接入回执portal-v191-formal-before/application.json。新增差异无尾随空白，整份handoff原两处Markdown硬换行保留。

专题契约v1.72、134 writer源和冻结包保持。原六项旧回款失败、旧worker执行主体、126真实停写/撤权/抑制及人类批准、全部writer/旧制品恢复、完整64T/经营试点和真实库存/价格/供应商/SMTP/存储/生产恢复仍OPEN；P0仅本地PI与ReceiptIntent草稿，无推送、预占或出库。完整实施目标active，本轮是库存时间与实际隔离SQL链路进展，不代表整体完成。

## 客户门户 v1.90 请求修改、取消与移动确认弹窗（2026-10-07）

上一轮v1.89是正式复购实现与验证进展。本轮正式接入五目标：客户decision-dialog标题/关闭按钮CSS、OrdersView关闭回焦可见性、新applicationDecisions驱动及实际MySQL规格、owned_process精确追加driver栈名。产品仅两个UI目标改变，无端点/表/迁移/金额/权限/状态机业务规则变更。2234个其他业务源码、测试及员工构建SHA保持；受影响客户站重新构建34modules、syntax实际exit0，dist逐文件SHA与最终候选一致，并备份旧dist。专题契约v1.72、134 writer源/冻结包保持。未commit/push/merge/部署，未生产/共享库或真实外发。

真实旧bundle/session45085 terminal1：2collected/completed、1pass/1fail、21warnings。关闭按钮geometry在320px left290.27/right321.375/width31.1，390pxwidth36.9；driver33:10几何断言失败，屏外关闭不能忽略。CSS仅让标题min-width0/任意换行和关闭按钮不收缩。第一修订/session80239 terminal1：2项1pass/1fail、21warnings；三宽关闭已44px且在视口内，但调整三宽后关闭再reopen，原button已focused/keyboardVisible却top1392/bottom1440，320x1000视口外。不是回焦目标错误，也不称所有正常关闭都有该问题；不改helper来放宽视口守卫。OrdersView.closed在active且原按钮仍connected时保留focus并nearest/instant滚动，消除不可见的已恢复焦点；无迟到回调或业务动作。

独立静态审查发现测试P2：通知只排除顶层敏感键不足以挡嵌套/改名原因；当前产品没有被证明泄露。修为两通知完整payload严格等值，只允许cancel的request_id与reject的request_id/revision_id。原命令唯一、审计/原因、金融所有列等断言保持；最终五目标静态复核无新增具体P1/P2，不认证运行或生产。最终candidate/session21497 terminal0：2pass、21warnings、31.91s；Node130/130、syntax及34modules构建实际exit0，属于候选，不冒称正式重复执行。

正式actual/session29171 terminal0：9collected/completed/pass、0fail/error/skip、145warnings、105.42s。九例包含新客户拒绝/取消1、原复购1/数量错误1/鼠标1/键盘1/长内容1及原三个安全诊断；六浏览器report均pass，实际加载路径为本任务worktree，不累计候选或历史通过数。原stdout/stderr仅父内存计bytes后丢弃；runner退出/未超时/child_reaped/cleanup均核验。

新规格通过真实main/OTP/Cookie、320px实际Tab/Enter输入完成quote/submit→员工HTTP完整128提案→关闭并可见回焦→500字符必填原因拒绝提案→submitted→500字符原因取消→cancelled。reject/cancel各实际POST1，准确If-Match2/3和响应，取消后无正常取消/PI下载动作。确认两弹窗各1440/390/320仅布局/关闭44px与截图，共六图；核心交易320，不称三宽各完整交易或全无障碍。主线程查看候选320遮罩图，长编号换行、关闭和主要动作在视口内；输入全部遮罩，原因仅固定合成文本。

数据库原Invoice/InvoiceItem/ReceiptIntent/Conversion/Publication五模型所有列不变；当前buyer请求row_version4、空invoice/accepted_revision，两个submitted/proposal修订与标准SKU明细hash有效，81商品金额/未知原总额和128提案保留，两修订均未客户接受。当前buyer仅一条reject_proposal和cancel命令及各一准确审计/原因和最小payload通知；未生成PI/PDF/回款或外部写，财务/非法写守卫为空。员工提案为真实HTTP，非新增中文UI验收；原有受控上游/邮件取证不是生产库存价格或SMTP送达。该顺序规格不替代T34取消/approve并发、旧/新版本和reason回放全部原规格。

四份本轮自有MySQL按实际terminal/parent返回匹配、Shutdown complete、精确port关闭、绝对边界/无reparse守卫后，仅删除八个data/temp目录；保留runtime/logs、有限RED/报告/几何/遮罩图、源和逐文件/旧dist备份，候选两个junction未递归删。最终证据D:/commission-system/tmp/portal-v190-final-evidence.json，接入回执portal-v190-formal-before/application.json。

原六项旧回款失败、旧worker执行主体、126真实停写/撤权/抑制与人类批准、全部writer/旧制品恢复、完整64T/经营试点及真实库存/价格/供应商/SMTP/存储/生产恢复仍OPEN。完整实施目标active，本轮关闭实际移动确认控件/焦点缺陷并补强P0客户负向决策链路；不代表全部验收或生产完成。

v1.90 收尾：strict、10篇专题链接/锚点/JSON、64T/20F/18A、134来源SHA与冻结包、本地git_sweep --no-fetch均实际exit0；本轮五目标与交接增量新增行无空白错误，全历史diff仅保留两处原Markdown硬换行。巡检仅本地快照，不保证远端最新。

## 客户门户 v1.89 真实复购与接口信封修复（2026-10-07）

本轮正式接入五目标：复购router返回值、原HTTP规格仅新增code201断言、新applicationReorder驱动及实际MySQL规格、owned_process精确追加该driver栈名。产品唯一行为差异为reorder_quote的ok(result, code=201)，与既有HTTP201及03契约一致；权限、报价、事务和金额算法保持。2237个其他业务源码、测试及双端构建SHA保持，无UI重构建、表或迁移变更。专题契约v1.72、134 writer源和冻结包保持。未commit/push/merge/部署，未生产/共享库或真实外发。

首个候选session27374实际terminal1：2collected/completed，1pass/1fail、20warnings、36.91s；driver的成功信封code断言失败，原router默认ok code200与HTTP201冲突。源码及失败位置定位，不把未单独持久化的旧响应正文冒称直接取证。修订保持该断言，原HTTP全部断言仅追加code201。candidate/session56482实际terminal0：2pass、22warnings、32.85s；候选隔离SQLite复购模块13pass/0warning，Node syntax实际exit0。独立五目标静态复核无新增具体P1/P2，不认证运行或生产。

正式session43923实际terminal0：8collected/completed/pass、0fail/error/skip、144warnings、98.51s；包括新复购1、原数量恢复1、原鼠标1/键盘1/长内容1及三个原诊断。实际module_paths为本任务worktree。正式隔离SQLite复购13pass/0warning，明确禁止MySQL连接；两批范围不同，不相加称21项完整门户验收。启动器scope旧v1.88标签保留并注明，不能按该文字覆盖真实选中案例或路径。原stdout/stderr只父内存计bytes后丢弃。

新复购使用服务创建的同公司另一采购账号历史单、受控上游价格与映射更新：旧81、新72，旧别名与当前别名/货号有差异。320px实际键盘登录、先建现有清单、历史请求→明确替换同意→一次真实reorder POST→新报价再次同意→新请求→完整提案接受→有权业务员HTTP审核→唯一本地PI/PDF；46个有限键盘步骤，未伪造商业JSON或浏览器商业API拦截。1440/390/320仅复购确认布局三图，核心交易320；主线程查看320遮罩图确认动作在视口内，不称三宽各完整交易或全部无障碍。

数据库原请求、所有Revision和RequestLine全列保持；明确历史账号不同、同access的新账号复购；新Quote归当前账号、空PO、未知总额和新72商品价。新PI使用标准canonical型号/颜色、当前负责人，历史映射不改。新请求关联唯一Invoice/Conversion/Publication；ReceiptIntent仍draft，无receipt/attempt/lease，未自动推送/出库；真实PDF含当前别名/货号和72。外部调用与非法写守卫为空。员工提案/审批为真实HTTP，不能称新增中文UI复购验收；合成价格前置不是生产价格管理或库存变化验证。

三份本轮自有MySQL按实际terminal/parent匹配、Shutdown complete、精确port无监听、绝对边界及无reparse守卫后，仅删除六个data/temp目录；保留日志/runtime、有限RED/报告/遮罩截图/源码和逐文件回滚备份，候选junction未递归删。最终证据D:/commission-system/tmp/portal-v189-final-evidence.json，接入回执portal-v189-formal-before/application.json。

原六项旧回款失败、旧worker执行主体、126真实停写/撤权/抑制与人类批准、全部writer/旧制品恢复、完整64T/经营试点及真实库存/价格/供应商/SMTP/存储/生产恢复仍OPEN。完整实施目标active；本轮修复具体HTTP契约并补强T18有限实际复购证据，不代表全部验收或生产完成。

v1.89 收尾：strict与10篇专题来源/链接/JSON、64T/20F/18A、134源SHA/冻结包检查、本地git_sweep --no-fetch均实际exit0；五个实际浏览器report均pass。本轮增量新增行无空白错误，全历史diff保留两处原Markdown硬换行，不删历史行来报全绿。巡检仅本地快照，不保证远端最新。

## 客户门户 v1.88 数量错误关联与真实键盘修正（2026-10-07）

上一目标轮有实际进展；本轮正式接入四目标：客户CollectionView数量错误体验、新applicationAccessibility驱动及实际MySQL应用规格、owned_process仅精确追加新driver栈名。2004个其他业务源码、原测试/夹具及员工构建SHA保持；只重构建受影响客户站。标准数量算法、金额、权限、数据模型和状态机保持，无新端点/表/时间字段。专题契约v1.72、134 writer来源与冻结包保持。未commit/push/merge/部署、生产/共享库或真实外发。

真实旧客户bundle反例session92289终态1：1fail/20warnings，driver67:9断言数量0缺aria-invalid；原角色alert文案存在。未把未执行的后续焦点断言冒称旧版实际结果。产品增加INVALID_QUANTITY专用aria-invalid和aria-describedby、非空唯一错误ID；nextTick后只在dialog仍打开时返回数量焦点，其他错误聚焦原alert；客户输入时清提示。原checkout.quantityFor验证保留，未放宽零值、MOQ、step或最大数量。320px修订截图视觉确认错误文案和数量输入焦点可见，洋红为隐私遮罩。

新增规格通过真实键盘Tab/Enter和输入完成登录、目录重试、数量0错误→数量3修正→selection。目录首个真实GET先门控，明确Loading/aria-live与六个skeleton后故意network abort；retry经真实应用200、本人SKU阳性后继续，不伪造商业JSON。报告catalogGetAborts=1与businessResponseReplacements=0分开，不能称全商业API拦截0。reduce是真实浏览器媒体条件及有限computed animation/transition0s、scroll auto；不是所有动画或屏幕阅读器验收。

candidate syntax/state tests/build实际exit0：130/130 Node状态用例、34模块客户构建。green/session89767真实terminal0，1pass/20warnings/29.89s。独立四目标静态审查无新增具体P1/P2；没有认证运行，明确未覆盖全部错误类型/屏幕阅读器/动画。新增错误ID必须精确非空，避免两个null值相等造成假绿；所有新增截图使用既有editable遮罩，原输出仅内存计bytes丢弃。

正式实际session84134 terminal0：7collected/completed/pass、0fail/error/skip、142warnings、93.39s；1新错误/键盘恢复、原鼠标1/键盘1/长内容1及原三个安全诊断。正式syntax/build实际exit0，34modules，客户dist逐文件SHA核对；未再运行未改变的Node状态算法或auth/finance全量，不把candidate130称正式重复运行或相加通过数量。全部实际module_paths为本任务worktree。

四浏览器report均pass：新增恢复22个有限键盘步骤，只有320px；原键盘、鼠标交易保留各accept POST1/一次commit后503/原回执GET1、商业回执读无写；原长内容/真实图片200后故障/受控字体回退/PDF财务证据保持。新错误规格没有quote/order/accept POST，原business_snapshot前九模型全列严格不变，OTP outbox允许的身份写明确排除，不宣称全库零DML或全网络隔离。

三份自有MySQL均按真实terminal/parent返回、Shutdown complete、精确port无监听、绝对边界及无reparse守卫后只删除六个data/temp目录；保留runtime/log/有限RED/报告/截图/源与回滚备份。stage junction未递归删。最终证据D:/commission-system/tmp/portal-v188-final-evidence.json，应用回执portal-v188-formal-before。

原六项旧回款生成失败、旧worker主体政策、126真实停写/撤权/抑制与人类批准、全部writer/旧制品回退、完整64T/经营试点及真实库存/价格/供应商/SMTP/存储/生产恢复仍OPEN。P0只本地PI及ReceiptIntent草稿。完整实施目标active，本轮关闭实际数量错误关联缺口并补强T51有限证据，不称完整无障碍/生产完成。

## 客户门户 v1.87 长内容与资源故障实际交易（2026-10-07）

本轮正式接入三个测试目标：applicationSurfaces.browser.mjs、新MySQL application_surfaces规格、owned_process仅增加精确driver栈名。2006个业务源码、原夹具/浏览器交易与既有双端构建文件SHA保持；没有业务UI/API/表/权限变更，不重构建或以旧构建冒称新产物。专题契约仍v1.72，134 writer来源与冻结包保持。未commit/push/merge/部署、生产/共享库或真实外发。

新场景使用合法字段上限：客户型号128、颜色128、货号64、地址200、联系人100、电话40、PO80。实际英文客户登录、方舟HTTP映射发布、报价/提交、完整提案接受及有权业务员审核到唯一本地PI。六个客户页面在1440/390/320px检查整页无横向溢出、主要按钮可用且在视口内，保存18张遮罩截图；这是一条连续交易加三宽布局观察，不称18项独立规格或三宽各完整交易。主线程视觉查看320px商品弹层；长型号自然换行、动作可见，洋红色为测试隐私遮罩。

真实应用先返回已审批本地图片200/JPEG，之后才放开浏览器route故意abort，实际monogram fallback可用。独立审查发现最初图片注入时序P2，修为gate、零abort及已校验标志后放门；修订复核无新增具体P1/P2，仅静态范围。当前客户站没有配置外部字体请求；新FontFace人为不可用并核error/请求数，只证明受控字体回退，不证明生产字体/CDN。图片route只拦GET图片，无商业响应替换；本地资产/合成上游与邮箱取证仍不是生产COS、库存、价格或SMTP送达验证。

候选初次2例1pass/1setup error：图片夹具DML在commerce fence后被拒绝。autouse审批前置又使trade早于boot，后者覆盖authority settings，三个有限诊断轮次仍1pass/1fail；固定状态500及原broker131 KeyError定位配置顺序。最终强制boot→trade/图片→assembled→commerce fence，原fence及夹具不改，不扩大允许写表。临时诊断全部删除。ordered浏览器通过但新DB断言误用API字段display_snapshot出现AttributeError；改为持久customer_display_json，保留原金额、canonical与财务断言。最终candidate/session43798实际terminal0，2pass/24warnings；失败证据保留，不累计各轮。

正式actual session1990 terminal0：6collected/completed/pass、0fail/error/skip、142warnings、90.13s。六例为新长内容交易1、原鼠标1、原键盘1、三个原进程安全诊断；全部实际module_paths为本任务worktree，启动器历史scope文字仍含candidate，不能据该旧标签改变真实加载路径结论。原输出只父内存计bytes后丢弃。三浏览器report均pass、商业响应拦截0；两原交易仍各accept POST1/回执GET1/一次提交后503、商业回执读取无写。新场景没有ACK故障，不替代原丢ACK证明。

新实际PDF全文与真实响应一致，仅去空白后核长字段保留；数据库核唯一PI、金额128、原标准SKU/model/color、当前负责人、接受修订与展示快照、唯一Conversion和Publication，ReceiptIntent仍draft无receipt/attempt/lease，未同步、无自动出库标记或外部订单ID。发布财务图全列相等，外部call/非法写守卫为空。原交易/图片夹具字节保持；保护原测试不以新增绿掩盖旧失败。

八个本轮自有MySQL按真实终态/parent返回一致、Shutdown complete、精确端口关闭、绝对边界与无reparse核验后，只删除16个data/temp目录；日志/runtime/有限诊断/截图/源码与回滚备份保留，stage只读junction未递归删。最终证据D:/commission-system/tmp/portal-v187-final-evidence.json，接入回执portal-v187-formal-before。

原六项旧回款生成失败、旧worker显式执行主体政策、126真实停写/撤权/抑制来源与人类批准、全部writer/旧制品回退、完整64T/经营试点及真实供应商/存储/SMTP/生产恢复仍OPEN。P0只本地PI与ReceiptIntent草稿。完整实施目标active，本轮补强T50有限真实证据，不能说全部验收或生产已完成。

## 客户门户 v1.86 移动端抽屉与真实键盘交易（2026-10-07）

上一轮是实际进展；本轮继续完整实施目标。正式接入四个已审目标：PortalOrders.vue、原applicationTrade.browser.mjs、新keyboardInteraction.mjs及原应用浏览器pytest模块。产品仅订单抽屉样式改变；无新端点/表/权限/时间字段。专题契约v1.72、134条PI writer来源及冻结包保持。未commit/push/merge/部署，未生产/共享库或真实外发。

实际反例：新键盘用例在末尾关闭抽屉失败；焦点确实在按钮，但320px时left340/right372，长request_no把按钮挤出视口。定向诊断session91649实际1fail/77warnings/63.81s，不删该几何断言。修复只给门户订单抽屉限定class，标题min-width0与任意位置换行，关闭按钮不收缩并使用现有金色token的2px焦点轮廓。未修改共享DetailDrawer或其他页面。项目引用的Emil技能文件未找到，按现有DESIGN.md执行局部布局修复，无动效变更。

原76处UI交互统一pointer/keyboard两种策略。keyboard通过真实Tab到达控件、Enter/Space执行、Arrow选择radio/combobox；不以driver focus/click/fill/check代替键盘。原81条后端断言与全部原JS断言行保持、三个原诊断函数AST保持；唯一PI、历史快照/PDF、当前撤权、跨客户/业务员隔离、丢ACK原回执与商业GET无写仍在同一原应用规格验证。driver策略布尔字段明确是静态分支声明，不是独立事件监测计数；截图的程序化滚动也不冒称纯键盘滚动证明。

初启动器session43352路径分隔符替换失误，实际加载正式原4鼠标用例、4pass/80warnings/61.43s，不能记为键盘证据。修正cwd与sys.path后session53936候选5项4pass/1fail/137warnings/99.09s，明确module_paths为stage；上述定向诊断形成屏外按钮证据。初标题修复candidate/session68494实际1pass/78warnings/59.11s，但在截图安全与焦点轮廓补充前；最终safe candidate/session78559实际1pass/78warnings/57.79s，后端/driver/新样式及mask均为最终候选。safe-focus准备脚本初次因默认GBK读UTF8失败；改显式UTF8、保留正确SHA后才新构建与最终受测，不把失败准备后的旧构建当新证明。

独立静态审查发现新增P2：通用失败截图可能在OTP输入后保存验证码；未证明本轮发生泄露。新增截图全部通过captureKeyboardEvidence，mask所有input/textarea/contenteditable，同时保留失败与焦点几何。真实Chrome随机私密输入探针实际exit0：四类editable字段36像素采样均遮盖，故意超宽按钮仍AssertionError；仅证明该合成输入遮罩，不泛称所有页面隐私验收。独立修订复核无新增具体P1/P2，未代运行或认证历史日志。

正式build/session13949实际exit0，3337modules/19.70s；原输出只父内存计数后丢弃，stderr有工具输出，不声称零warning。正式实际app.main+独占MySQL+原鼠标交易/新键盘交易/三原安全诊断，session59384真实terminal0：5collected/completed/pass、0fail/error/skip、138warnings、84.99s；父stdout11218bytes/stderr0丢弃，全部module_paths为正式worktree，fresh dist逐文件SHA复核。没有重跑与该局部样式无关的auth78/finance23或全2581，不把上轮结果冒称本轮运行。

两种交易report均pass、商业API拦截0；各18组原有限场景，不称36项独立规格。各自实际接受commit后一次受控503、accept POST1/回执GET1、商业回执读写0、PDF3；runner真实exit0/未超时/child_reaped true/cleanup_failure false。最终keyboard实际208条交互进度，其中103次控件到达、63次激活、36次输入、2次明确勾选、4次选项选择；核心交易320px，部分身份步骤390/默认1280px，1440/390/320截图只表示布局，不等三宽各完整键盘交易。关闭按钮最终left264/right296、实际2px solid金色outline；主线程视觉复核其截图，不以:focus-visible布尔独自证明可辨。验证截图含隐私遮罩，与真实产品配色无关。

六个本轮独占MySQL均核实际terminal与parent回执一致、Shutdown complete、精确port无监听、datadir边界与无reparse后，只原生删除十二个data/temp目录；日志/runtime/有限报告/截图/逐文件回滚备份保留。候选node_modules只读junction不递归清理。有限最终证据D:/commission-system/tmp/portal-v186-final-evidence.json；接入前备份及receipt为portal-v186-formal-before。

原六项旧回款生成失败仍开放：旧worker直接created_by执行，新显式身份服务存在，业务执行主体政策尚无人类答复，未替业务选择身份或改变旧worker。完整126停写/撤权/抑制来源与批准证据、全部writer/旧制品连续回退、完整64T/经营试点、真实库存/价格/供应商/SMTP/存储及生产恢复门禁继续OPEN。P0仅本地PI与ReceiptIntent草稿，无自动推送/预占/出库。完整目标保持active，本轮关闭实际移动端抽屉缺陷并加强T48的有限证据。

v1.86 收尾检查：项目strict、专题10篇/链接与锚点/JSON/64T/20F/18A、134源码SHA与冻结包、本地git_sweep --no-fetch均实际exit0；四目标及本轮交接增量空白错误0，全历史diff只保留两处原Markdown硬换行。巡检仅本地快照，无远端写入授权。最终证据包括五项终态、两种实际应用报告、bundle SHA、原断言保存、遮罩探针与清理收据；各阶段数量不累计。

## 客户门户 v1.85 正式认证接入与最终证据（2026-10-07）

已完成已审14目标的正式接入，专题契约仍为v1.72。写前确认本任务分支、候选/正式前SHA、广回归真实terminal和父进程回执；逐文件备份与应用回执保存在D:/commission-system/tmp/portal-v185-formal-auth-before。未commit/push/merge/发布，未连接生产或共享数据库、未真实外发。PI writer inventory134条与本批14路径无交集，未改迁移或库存/财务权限规则。

产品修复：登录、退出和刷新都有身份代次及旧传输取消；迟到结果在写入token/用户之前再次检查，旧401不能清理新登录，旧退出不能跳走新账号。App和Login忽略明确的已被取代操作。测试helper保留原有限安全摘要，清除私密输入和异常链；清理失败如实失败，不声称任意失败的进程树都已全部回收。原客户应用3测试函数AST和断言保留，新Cookie规格使用实际172/173 DDL、unsigned用户主键及精确客户负责人外键。

正式验证各自终态，不累计历史：npm run test:request-auth 78/78通过；发票读取/布局23/23通过；正式vite build成功，3336 modules；独占MySQL+真实app.main+原客户应用浏览器+新Cookie suite共10/10通过，116warnings、73.55秒，actual session95694 exit0与parent回执一致。10包含4新Cookie/安全规格、3原诊断参数、1原应用浏览器及2原交易API。源码module_paths均为本任务正式worktree；新构建dist逐文件SHA再次匹配。构建stderr有工具输出，不将其冒称零warnings。

实际英客户/中员工浏览器18组有限场景，1440/390/320三宽、商业API拦截0：邀请激活、标准SKU映射预览发布、服务端报价提交、完整提案接受及当前业务员审核、唯一PI与历史PDF、跨客户/业务员拒绝和当前撤权。实际接受提交后一次受控503，accept POST1/回执GET1，商业回执读取写入0，PDF3；runner exit0、未超时、child_reaped true、cleanup_failure false。身份Cookie另外验证三种迟到传输，loopback HTTP与受控非门户bootstrap/provider仍不是TLS、跨tab、分布式认证或生产证明。

广回归631/session6840终于真实terminal exit1：2581 collected/completed，2574 pass、6 fail、1 skip，6672 warnings、internal/collection errors0、6403.82秒、evidence replace retry1。该执行早于本批正式源码接入。六个原receipt_generation失败涉及当前撤权、真实发票作用域、缺失原执行主体和锁外取证；不删测试、不弱化断言，旧自动回款执行主体政策尚无人类答案，不隐式选择created_by或系统身份。本批定向绿不能覆盖这六项。

独立原历史空库full-chain实际session92959 terminal1：1项失败、0warning、49.51秒；CutoverGuardError停在126加载cutover contract，数据库停125_invoice_integration/240表，尚未进入126删除/重置。原测试、DDL、迁移及安全门禁保持。独立静态复核确认缺真实cutover编排证据，不是门禁缺陷：十类writer逐实例停写/撤权/零事务/维护围栏、OKKI/Alibaba/provider三类权威抑制导出、保留快照/回填及短期人类批准marker缺失。不能伪造空库无writer、停止标记或批准。正确入口customer_domain_cutover.py的preflight→export-suppressions→verify-ready→apply-reset→verify-after需要真实证据；其子进程还须显式绑定独占库，父fixture monkeypatch不会传播。完整126/173历史链继续OPEN。

详细开发入口README及08审查边界已同步正式接入与631终态。两路独立审查为限定范围静态复核，无新具体P1/P2，不等全历史或生产背书。完整64T双端验收、双客户双业务员经营试点、真实库存/价格/供应商/SMTP/存储、旧worker与发布恢复门禁仍OPEN。P0仅本地PI及ReceiptIntent草稿，不自动推送、预占或出库。完整实施目标仍active；开发文档与本轮对抗审查已交付。

v1.85 收尾验证：strict、10篇专题链接/锚点与JSON、64T/20F/18A、134源SHA和冻结包检查、本地git_sweep --no-fetch均实际exit0；本批文档及已接入文件增量无空白错误，全历史diff保留两处原Markdown硬换行。631与formal185实际终态/parent回执、Shutdown complete、精确端口无监听、绝对目录边界和无reparse核验后，只删除四个自有MySQL data/temp目录；runtime、日志、报告、截图、候选junction与逐文件备份保留。有限最终证据D:/commission-system/tmp/portal-v185-final-evidence.json；巡检仅本地快照，不保证远端最新。

## 客户门户 v1.84 完整应用候选兼容与历史主键类型（2026-10-07）

上一目标轮有实际进展：详细文档交付、两路审查和可移植7项终态。本轮继续完整实施goal，在Dtmp候选补共享helper的原完整main调用；正式仓库仅本交接修改，正式auth/产品/测试/dist未变，专题v1.72/冻结包保持。候选14目标只改其中新的auth Cookie测试准备方式；原安全helper、十个认证目标、JS驱动、原customer_application_browser测试正文保持。未commit/push/merge/发布、生产/共享库或真实外发。

stage新增当前frontend-portal源/测试/dist的独立copy共65文件，逐一SHA与正式源匹配，不重构建或复制其node_modules。此前stagefrontend node_modules/dist仍只读junction，不能递归删stage清理。原main/commerce fixtures从stage执行，非非portal bootstrap/jobs/upstream改成真实生产。原应用18组有限场景与三宽来自现有规格，不新增18独立测试或称64T全验收。

初184/session63876实际terminal1：10collected/10completed、7pass/3setupERROR、18warnings；父stdout45898bytes/stderr0只计数后丢弃。三个setup OperationalError指向mysql_schema47、172 migration520 sales_user FK，实际应用业务未执行。源码定位新Cookie测试先通用ORM建signed用户，而历史typed anchor/migration引用unsigned；不伪称已获取原错误正文/SQL或精确MySQL码，不改产品模型/迁移来让夹具通过。

新Cookie测试改显式依赖现有service_schema→migrated；复用真实172/173门户DDL与unsigned用户锚点，合成上游列仍是测试，不等完整126历史迁移。删除抢先ORMcreate_all，检查七张身份表存在；随机账号/角色、复用权限不改变旧授权、精确logout token、独立浏览器、原所有业务断言保持。final/session89058实际terminal0：10pass/116warnings/78.34s，但早于实际类型/FK新守卫。独立定向只读复核无新具体P1/P2，建议Cookie首位→完整应用顺序并核实际类型/FK；未代跑或认证日志。

最后仅加readiness/unsigned=True和精确fk_op_customer_access_sales_user_id→ark_users.id三个只读断言，typed/session97140实际terminal0：10collected/10completed、10pass/0fail/0error/0skip，116warnings、78.51s；父stdout11164bytes/stderr0丢弃。10=4新Cookie/安全规格+3原诊断参数用例+1原完整应用浏览器+2原实际main交易API，不累加此前7/10/Node101。Cookie首位，实际类型及外键守卫在main之前通过；终态app.main/auth router/sharedhelper/两原模块paths均stage。20个原assert AST完整保留、新增3个；另外3定义AST及65门户copy源/distSHA不变，正式14目标beforeSHA仍匹配。

typed浏览器report pass、apiInterceptions0、1440/390/320、原18组有限场景；当前英文客户站与候选中文员工站实际main/OTP/JWT/MySQL完成邀请激活、映射预览发布、服务端quote/submit、完整proposal接受及唯一PI/历史PDF、跨公司/业务员拒绝、账号/当前员工撤权。原接受实际commit后ACK替换一次503，浏览器accept POST1/原回执GET1，商业回执GET writes0，PDF/snapshot原不变量通过。共享新helper真实caller runner-summary exit0/timed_out false/child_reaped true/cleanup_failure false；Node固定stdout1849bytes/stderr0无原输出保存。另新Cookie真实3场景保持loopbackHTTP边界，不证明TLS/跨tab/分布式refresh或全生产进程。

631/session6840本轮同句柄实际live，03:58北京时间快照2581collected/2085completed、2078pass/6fail/0error/1skip、4790warnings/internal0/replace retries1。六个旧receipt_generation拒绝/作用域/原主体/锁外取证失败仍开放，主体政策人类未答，不默认created_by。未终态不清其目录、不重启、不修改它的正式源/dist；候选通过不覆盖这些失败或完整回归。

184/184-final/184-typed全部实际terminal与process匹配、Shutdown complete、精确port无listener、runtime.datadir边界和无reparse后，只原生删除六个自有data/temp目录；保留runtime/logs/报告/截图/pytest目录/源备份，631未动。最终有限证据D:/commission-system/tmp/portal-v184-final-evidence.json，包括各终态/14manifest/65copy/20assert保存及实际main报告；旧失败材料保留。

正式14目标接入脚本portal-v185-formal-auth-apply.py只执行prepare-only、14SHA/own分支验证通过，0正式源修改；未运行apply。脚本需主线程实际确认6840 terminal、pytest与parent终态匹配、收集全部完成/no internal，再校候选和beforeSHA、保存逐文件备份与receipt后才apply；之后仍要正式build/Node/实际Cookie与完整main回归。本轮不以候选证据替代正式接入。完整126/allwriter/旧worker政策、其他兼容差异、真实库存/价格/供应商/SMTP/存储、64T双端经营B01–B07、生产发布恢复继续独立OPEN。目标保持active，下一优先在631真实终态后接入14目标并核正式关键路径。

## 客户门户 v1.83 可移植候选与开发文档对抗审查（2026-10-07）

本轮按用户“生成详细开发文档并进行对抗性审查”交付：README增加专题唯一来源和阅读顺序，08前部明确当前风险、两路独立复核范围及未关闭门禁；本交接保存实际执行证据。专题规范v1.72和历史冻结包保持；本轮正式仓库只改README、08、本交接，不正式接入认证/取证候选，不构建或变更正式受测源码、dist。P0仅本地PI与ReceiptIntent草稿，完整实施goal保持active。

准备14目标的项目相对路径candidate：十个认证目标、新authCookieRace.browser.mjs、新owned_process.py、新test_mysql_auth_cookie_race.py和原customer_application_browser抽取helper。所有候选SHA匹配manifest、正式前SHA不变；原3测试函数与原safe_runner_summary AST保持。无Dtmp/C用户常量或动态AST导入；Node依赖/dist只读junction，不能递归删除stage来清理。没有孤立的要求私密stdin npm快捷命令，新Cookie规格由显式runtime/pytest启用。

portable session89507实际terminal exit0，7collected/7completed/7pass/0fail/0error/0skip，18warnings、22.25s；module_paths确认实际stage auth router及两测试/helper。7是1真实Cookie规格（内含3浏览器场景）+3新安全规格+3原诊断参数用例，不是7个浏览器场景；Node finite3pass/0fail/exit0，child_reaped=true、cleanup_failure=false。实际认证router/service/JWT/独占MySQL与Chrome loopback HTTP/HttpOnly cookie；login/logout实际commit，refresh只读不SetCookie。保留释放旧响应后Cookie/当前身份先查再refresh、cookie全页reload恢复B、旧传输真实disconnect与旧logout精确token撤销。薄auth挂载/7表不是完整main/历史迁移，非TLS/跨tab/分布式认证认证。

同stage Node joint-final实际terminal exit0，101pass/0fail/0skip，stdout19671bytes/stderr0计数后丢弃；101覆盖57微任务+5实际Axios/store+6request+10invite+16invoiceRead+7layout，不同于7个HTTP/诊断规格，不累加历史。没有重复build，仍读取v1.81已构建候选dist，本轮只加可移植测试/helper。driver node --check实际exit0。有限原输出只父内存计bytes，未保留原SQL/密码/headers/异常正文。

两路独立只读复核无新增具体P1/P2。文档路线核对00–06核心和08，未重审全历史附录或候选接入；交易路线核候选SHA/AST和Cookie先检查后修复顺序，未执行服务或认证日志。明确14目标尚未正式接入，正式接入后test:request-auth/newCookie及完整实际main应用浏览器必须重跑；当前7不能替代共享helper完整调用兼容性。

631/session6840在本轮再次同一exec handle实际live；03:42北京时间安全快照2581collected/1767completed、1760pass/6fail/0error/1skip、3965warnings/internal0，evidence_replace_retries1。只有一次替换重试计数，未证明谁持reader或绝对路径因果。六旧receipt generation失败保持OPEN，执行主体政策人类答案尚缺，不默认created_by；未到终态不重启/不清理/不改正式受测源。其余完整126、allwriter、旧制品连续回退、64T双端/经营B01–B07、真实库存/价格/供应商/SMTP/存储、生产发布恢复仍独立OPEN，不把文档或候选局部通过当整体验收。

portable183已核实际terminal/process0匹配、MySQL Shutdown complete、6209无监听、runtime.datadir绝对边界和无reparse，只原生删除自己的data/temp两个目录，保留runtime/logs/有限JSON/复现脚本与stage；631未动。证据D:/commission-system/tmp/portal-v183-final-evidence.json、manifest及portability-check/result/process/cleanup JSON。旧静态checker含过时v1.65中文断言，本轮明确复本改为实际v1.72标题，不删链接、64T/20F/18A/134源码hash或冻结包检查；新checker首跑全部通过，最终文档写后再跑。未生产连接、真实发送、commit/push/merge/部署。

本批收尾实际strict/session93386 terminal exit0；文档静态10篇/118引用锚点/3JSON/64T/20F/18A及134源码SHA匹配、112Python AST通过，v1.55/v1.58冻结包未变。三文件相对本轮备份增量无新增空白错误（git no-index exit1只表示内容不同）；全历史diff仅两处原Markdown硬换行warning、exit2如实保留。03:46北京时间git_sweep --no-fetch exit0，main0修改/1未跟踪、任务104修改/112未跟踪、无upstream；只是本地快照，不认证远端最新。7项/Node101各终态，631仍独立live，本轮未改其正式源或清理其目录。文档交付与有限独立审查完成，完整实施目标仍active。

## 客户门户 v1.82 实际认证HTTP与迟到Cookie验证（2026-10-07）

上一目标轮有实际进展：十个认证候选、微任务57/联合101、编译17DOM及独立写前围栏复核形成。本轮补真实认证传输验证，完整目标仍active、专题契约v1.72。v1.81十候选源与dist字节保持，未正式应用或重复构建；own认证源码和原正式取证helper未改，本轮唯一仓库修改为交接。测试/启动器/安全helper仍Dtmp候选，未commit/push/merge/部署/外发或操作生产/共享库。P0只本地PI与ReceiptIntent草稿，无自动推送、预占或出库。

使用实际Ark auth router/service、真实密码核验/JWT/当前me数据库读取、独占MySQL的七张原认证表及已编译候选Chrome。选定表按实际模型建表，不是全历史迁移；FastAPI仅挂载原auth路由并覆写独占Session提供者，不是全app.main。非auth只读业务返回受控数据，不认证发票/客户scope或商业内容。实际IPv4 loopback HTTP、HttpOnly/path=/api/auth/SameSite=Lax Cookie，测试内COOKIE_SECURE=false，不称TLS/生产Secure配置证明。页面仅阻止非本地origin，非整个浏览器网络沙箱。

响应门先让真实auth路由完成，再暂存原headers/body。login/logout真实变更已提交，旧logout原Cookie对应精确refresh-token行由私有hash对照核已撤销；refresh仅读取并生成access JWT，无commit或Set-Cookie，不能统一称提交后Cookie覆盖。B实际登录后释放旧响应：候选的旧HTTP已真实disconnect，login/logout的迟到Cookie设置/删除没有覆盖B；refresh旧access响应不能把当前身份改回A。先核CookieB及实际fetchMe的当前B身份，再做真实B refresh/me；清空localStorage access token后全页reload仍由B的HttpOnly Cookie恢复B。无Playwright auth响应拦截替换，服务端原Set-Cookie仅响应门延迟；不推断已提交操作被取消回滚，不覆盖跨标签页或分布式并行认证。

初规格实际96262 terminal0：1pass/14warnings/18.64s，Node三个有限场景3pass；仅准备阶段证据。为增强区分力，同一最终driver先释放旧响应，即使基线不取消，也给原Set-Cookie真正送达机会；先查身份再refresh，避免新refresh修复A身份后形成假绿。准备前基线28754实际exit1/browser0pass3fail，分别refresh错身份57:12、logout Cookie消失51:12、login Cookie被替换51:29；候选11005实际exit0/browser3pass。首次safe helper批14048/44582同为RED/通过，但在新增异常链防护之前，不累计这些执行或当最终证据。

独立复核发现并修正两处取证P2：首次subprocess/JSON异常尚未清密码/控制key/原输出，以及refresh被误标提交后。Node只写固定有限JSON，seed先clear、caller finally清私密输入/密码/key，断言与JSON解析在清理之后。复用原consume后又发现继发taskkill故障可通过TimeoutExpired异常链保留私密partial output；精确原helper的合成探针实际terminal0复现该链，child因原context wait已回收、cached stdin已清，不能称发生真实凭据泄露。新候选helper剥离原异常output/stdout/stderr/cmd/doc/args/traceback/context/cause，清理失败fallback并最终核回收/关闭流/清_input；任何清理失败或未回收必返回非零有限摘要，不保证任意无法kill情形下完整进程树回收。新增正常失败/超时两参数及“私密partial output超时→taskkill OSError”反例，不删原Cookie/身份断言。独立定向复核源码闭环、无新增具体P1/P2，不代跑或认证运行；原正式helper的相同清理故障分支仍待整合修订。

最终同driver与三个安全规格：red-safe2/session26670实际terminal1，4collected/4completed、3安全pass/1集成fail、9warnings/18.65s，浏览器0pass3fail；final-safe2/session85227实际terminal0，4pass/0fail/0error/0skip、17warnings/23.26s，Node3pass/0fail/exit0。4是1真实HTTP规格（内含3浏览器场景）+3取证安全规格，不能写7项或累加历史执行。stdout/stderr只父进程内存计bytes后丢弃，Node固定摘要仅37bytes stdout/0stderr；原始pytest RED8446bytes、最终1860bytes均未持久化。七轮14个自有MySQL data/temp目录已逐一核实际终态匹配、Shutdown complete、精确端口无监听、runtime.datadir、绝对边界和无reparse后原生清理，runtime/logs/有限证据/恢复材料保留；631未动。

完整631/session6840本轮同一exec handle再次实际确认live，记录时2581collected、1432completed、1431pass/0fail/0error/1skip、3205warnings、internal0/replace retries0。尚无终态退出码，不称广覆盖通过，不重启、不清理或中途改受测源码。当前候选的有限迟到HTTP/Cookie场景补齐，不等于正式接入、TLS/fullmain/跨标签页/分布式认证认证。旧自动ReceiptIntent六项业务失败与执行主体人类政策、完整126维护停写撤权回填、其他平台兼容候选/两文档冲突、真实库存价格/供应商/SMTP/存储、完整双端64T及生产恢复仍OPEN，不默认created_by。

恢复材料D:/commission-system/tmp/portal-v182-final-evidence.json包括精确driver与规格/helper SHA、各实际终态、基线三个错误反例、异常链合成RED、最终4与3场景、独立审查限制及清理。下一步继续同一6840观察完整终态，再正式接入已审认证与安全helper候选并核正式关键路径；当前完整目标未完成。

## 客户门户 v1.81 认证异步延续与写前围栏候选（2026-10-07）

上一目标轮有实际进展：v1.80候选57项与14DOM终态证据形成，独立发现auth store旧成功延续P2。本轮继续开发实现，完整目标仍active，专题契约保持v1.72。十目标仍仅Dtmp隔离candidate，包括前版六目标及App.vue、LoginPage.vue、auth API和新authTransport.test.mjs；正式own认证源码与新增文件不存在状态保持，本轮唯一仓库修改为交接。未commit/push/merge/部署/外发或操作生产/共享库。P0仍只本地PI与ReceiptIntent草稿，不自动推送、预占或出库。

login/refresh/logout开始新代次并取消前一认证transport；当前Axios/API实际传AbortSignal，取消不弹错误toast。旧login/refresh/me成功或失败均转为固定superseded错误，旧logout静默false；当前logout即使transport失败仍清本地状态并使用原caller target。me另用最新序号。App两层初始化catch与Login识别superseded，阻断旧失败导致新登录的回退、清理、错误反馈或导航。取消只是辅助，不能证明服务端未执行或真实Cookie无副作用。

18原请求规格正文逐字保持，新18异步生命周期/实际App脚本规格组成36项：在精确v1.80候选基线实际20pass/16fail/exit1，初v1.81候选36pass/exit0；初联合75pass已包含36，不累计。五项实际auth API+store、真实Axios与受控adapter验证login/refresh/logout信号取消、忽略abort的adapter仍由Axios拒绝及当前登录401正常反馈，实际5pass/exit0；不是实际HTTP/JWT/cookie或DOM证据。

独立审查发现新P2：currentResult内层已检查，但外层await恢复到真正写token/user之前仍可开始B，A错误提交再前进epoch反而拒绝B。初三规格只有一次微任务，实际39/39全绿；因host Promise→VM adoption桥，B早于内层检查，未击中，不称修前RED。改为每方法0–6次精确微任务调度并把B保持未完成，按B开始时旧提交是否已发生分别验证合法成功和拒绝，实际57项修前54pass/3fail/exit1：login/refresh/me均delay1命中。保存精确auth-before-write-fence.js；外层await后、实际token/user写前同步再查epoch/meSequence，中间无await。相同最终57项实际57pass/exit0；联合101pass/0fail/0skip/exit0含57+transport5+request6+invite10+invoiceRead16+layout7，不累加历史批次。独立定向源码复核该P2在客户端候选范围闭合、无新增具体P1/P2，不代跑或认证日志。

最后围栏修订后隔离Node22 build/session93642实际terminal0、3336modules、stdout32192bytes/stderr10747bytes仅父内存计数丢弃；保留现存诊断，不称零warning。编译候选Chrome/Vue/Pinia/router/session17313实际terminal0：17pass/0fail、stdout3533bytes/stderr0丢弃。原14场景保持，新增旧refresh/logout/login挂起后实际B登录，验证旧promise已取消并返回superseded或false、B用户/token/当前DOM保持。取消后route资源可能disposed，driver只有限释放资源并独立断言产品promise与身份，不把忽略route处置错误当业务成功。其余迟到401/403/ABA仍等待精确XHR完成信号。页面/API/身份全受控、商业write API0；不认证真实JWT/MySQL/供应商、cookie、文件商业内容、全双端64T或全浏览器网络沙箱。

完整631/session6840通过同一exec handle再次实际确认live，记录时2581collected、895completed、894pass/0fail/0error/1skip、1933warnings、internal0/replace retries0。尚无终态退出码，不称广覆盖通过，不重启、不清理或中途改受测源码；当前十候选不覆盖该批正式源文件/dist。旧自动ReceiptIntent六项业务失败与执行身份人类政策、完整126维护停写撤权回填、其他平台兼容候选/两文档冲突、真实库存价格/供应商/SMTP/存储、完整双端64T及生产恢复仍OPEN，不默认created_by。v1.80旧P2已在候选客户端范围补齐；正式接入与真实cookie/服务端并行认证协议仍OPEN。

恢复材料D:/commission-system/tmp/portal-v181-final-evidence.json及portal-v181-auth-candidate，包含十文件SHA、精确修前源、36基线RED、未命中39说明、57微任务RED/最终57/联合101、最终build/17DOM与独立复核限制。下一步继续同一6840等完整终态，再按原范围正式接入并运行正式回归；不将候选通过称正式集成完成。收尾适用约定、文档源引用、当前差异及本地no-fetch检查见安全证据。

## 客户门户 v1.80 登录请求竞争候选与广覆盖取证恢复（2026-10-07）

详细开发总纲及01–08专题仍按v1.72契约阅读；本节记录本轮实现与对抗审查证据，完整目标继续active。英文客户站、中文方舟管理端、当前数据库权限和业务员范围、标准SKU与客户映射快照、完整提案经客户接受同一修订后唯一PI保持。P0只本地PI与ReceiptIntent草稿，无自动供应商推送、预占或出库。本轮六个认证候选均在Dtmp隔离目录，未正式应用；仓库仅增加本交接，未commit/push/merge/部署/外发或操作生产/共享库。

629/session92644已实际terminal exit3：2581collected、180completed/180pass、0fail/0error/0skip、410warnings、1internalError、2401未执行、288.26s。有限摘要只证明pytest内部PermissionError，frames为空，真实异常目标未知；不能断言629由进度JSON替换导致，也不能称旧六项自动回款失败已消失。原始stdout10496bytes/stderr0仅父进程内存计数后丢弃。629自有data/temp两目录在实际终态、Shutdown complete、精确端口无监听、runtime.datadir与边界/无reparse核验后原生清理；日志及安全证据保留。

针对取证记录器的独立合成实验执行原Evidence.save AST：普通Python读句柄可复现replace PermissionError，关闭后恢复；此环境FILE_SHARE_DELETE也未保证替换成功，仅支持可能路径，不认证629根因。候选只对replace PermissionError有限重试25次、每次0.04s、最多0.96s睡眠，不代表总运行时上限；临时文件写入、SQL或业务错误不吞。执行新save AST的合成实验短暂读锁3次重试后成功，持续锁最终重新抛出。独立复核无新增具体P1/P2，仍提示永久锁可令终态记录不完整，必须以真实进程退出及结构证据核对。

新完整631/session6840已实际启动并通过同一exec handle再次确认live，记录时2581collected、277completed/277pass、0fail/0error/0skip、830warnings、internal0、replace retries0。这是运行中快照，尚无终态退出码；不称全绿、不重启或清理631。正式自有产品、测试及dist保持启动时版本，原六项receipt_generation、全部原规格与maxfail25保留；真实own app/JWT和独占MySQL、受控上游/provider，未启用完整126历史回放。629停止不能替代631终态。

认证候选六目标：auth.js、request.js、两份已有测试harness、package显式VM命令及新增requestAuthRace.test.mjs。请求发送时记录实际Authorization与认证epoch，错误返回时只有当前凭据且同代次才清空/跳转；相同token的A→B→A、匿名请求后登录、动态邀请授权、并行失效及旧loading slot均有反例。真实Axios/Vue/Pinia、实际auth/request源码配受控身份API/adapter；不是JWT、真实HTTP/cookie或DOM认证。相同最终18项在精确原源码RED实际7pass/11fail/exit1；最终候选18pass/exit0。联合批57pass/0fail/0skip/exit0已含这18及原request6、invite10、invoiceRead16、layout7，不能累加成75项。初稿候选17pass/1fail系无绑定config无法释放未知loading slot的夹具假设，最终该无绑定场景关闭其自身showLoading，保留原认证断言及独立旧slot规格。隔离Node22 build实际session87510 terminal0、3336modules，stderr10747bytes含现存诊断，不称零warning。精确原2文件RED暂换后已finally恢复候选字节，正式own五源hash与新增文件未存在均核验。

独立对抗复核发现触及auth store的既有P2仍OPEN：A refresh待返回时B登录已完成，A成功续期可把token覆盖回A而user仍为B；A logout晚成功可清空B并跳转。当前epoch保护的是旧请求错误，不等于整个认证生命周期闭合；login/fetchMe及调用方失败后logout也需纳入后续反例。必须补异步成功/失败时序、明确调用方处理并验证后才正式应用六候选，真实refresh cookie竞争尚未验。本轮不把18pass或14DOM当作此P2关闭。

已编译候选实际Chrome/Vue/Pinia/router同批14场景最终session75951实际terminal0：14pass/0fail、父进程stdout2987bytes/stderr0丢弃。原10项读取/权限/导出场景保持；新增实际B登录后旧401/Not-authenticated403、同token A→B→A均保留新账号及当前行，等待精确旧请求ordinal的XHR loadend/下一任务/两RAF完成marker；当前401且两次refresh拒绝后达到匿名login、localStorage token=null阳性保持。两次准备阶段13pass/1fail及源码均保留：先补App.vue两次refresh拒绝并等待initPromise，仍失败；再发现addInitScript每次全页刷新都重新植入合成token，改为每个context只首次植入，最终原null断言通过。HTTP/身份均受控、真实业务写API0；不认证JWT/MySQL/provider、真实cookie、文件商业内容或全双端64T，页面级外部origin拦截也不是全浏览器网络沙箱。

原旧自动ReceiptIntent六项业务失败与人类执行身份政策、完整126维护停写撤权回填、其他平台兼容候选与两文档冲突、真实库存价格/供应商/SMTP/存储、完整双端64T、生产恢复门禁继续OPEN；不默认created_by。恢复材料及终态/候选/未完成边界见D:/commission-system/tmp/portal-v180-final-evidence.json。下一步同一6840等待631真实终态，并先处理auth store旧成功延续P2；当前详细文档可作为实施依据，不能作为生产验收完成证明。

## 客户门户 v1.79 回款远端编号测试准备正式修复（2026-10-07）

上一目标轮为实际进展：正式发票前端九目标接入、23规格/10实际DOM/正式build通过，624已实际终态并清理自有临时库。本轮继续推进完整目标，仍active；专题开发契约保持v1.72、main4428ebc078e7d74158037ec60e0233eeb12294fb未变。未commit/push/merge/部署/外发或操作生产与共享库。

原625/session36516实际terminal exit1：最小两项outbound新grant参数先通过，随后原binding规格setup MySQL1062；3完成/2pass/1error/32warnings/34.66s。对账建唯一索引前真实已提交重复两行，hash6a116b47a793ad25与624的261行重复组相同；原shipment fixture固定编号70001的hash实际匹配。来源为最新mapper观察，不认证每行commit归属；不反推历史605根因已证明。

候选只修测试准备：shipment_app存款和historical_shipment两个子回款编号改为500000000+已生成Receipt.id，受控provider全部引用相同对应值，金额、费用和金融断言不变。receipt_app在任何回款准备前镜像migration156原全局远端映射唯一约束，保留历史行；不改产品/迁移，不删除行/清空编号/放宽索引。独立审查发现初稿按单SHOW INDEX行any判定会接受组合或前缀唯一索引，夹具P2已修：按Key_name分组，仅组len1、序号1、精确xiaoman_receipt_id、Non_unique0且Sub_part None接受。新增七个元数据反例/对照及一项真实MySQL重复commit1062/rollback/原行保持规格。原两模块22测试函数完整AST保持；独立只读复核P2闭环，无新增具体P1/P2，不代跑或认证日志。

初候选626/session62611实际terminal1：11完成/7元数据pass/4setupError/1warning。复制目录未包含126 frozen JSON；直接执行原126导入证明CutoverGuardError由该自有资源缺失FileNotFoundError引起，仅记录有限类型和相对路径。按原字节复制三份alembic资源并确认原126导入成功；不stamp、不执行126 cutover。候选630/session59784实际terminal exit0：11pass/34warnings/34.38s，两个fixture实际路径均为隔离candidate、对账前重复组为空。原626错误摘要有限类型，不能把全部四条原错误链细节说成已直接认证。资源诊断准备脚本初稿漏app导入路径、后续parent尚未生成未启动测试；补路径后才取得上述直接诊断和630执行，不计产品缺陷或业务测试。

候选终态后正式应用三文件：receipt_authority、shipment_create及新receipt_fixture_identity，before备份与逐文件after SHA保留。正式627/session34757由实际exec返回terminal exit0：同一11pass/0fail/0error/0skip/34warnings/35.51s、0remaining/internal0，两个fixture路径实际核为own；对账前重复组为空。11含三原规格（两参数+binding）与新八项，不累计625/626/630/627称更多独立规格。新MySQL集成证据不是完整receipt156历史迁移认证，上游薄schema仍合成，实际app/main/JWT及受控外部读按原夹具运行。

现有源码清单只更新shipment_create一项hash，仍134项，其他分类/字段保持；新两个目标hash在apply receipt。625/626/627/630的8个自有data/temp目录已逐一核实际process终态、Shutdown complete、精确端口无监听、runtime.datadir、边界与无reparse后原生PowerShell清理；日志、runtime与有限证据保留，629未动。

新完整629/session92644已实际启动；同一exec handle本轮再次返回live，落盘快照2581collected/89completed，89pass/0fail/0errors/0skip/75warnings、internal0。尚无真实终态退出码，不称广覆盖通过或14项全已闭合；不重启、不清理629，不中途改受测产品/规格。保留旧receipt_generation六项及maxfail25，显式Node22/mysql2 runtime，未启用full-chain专用历史回放。下一轮通过同一92644继续观察，最终验证原14项以及此前800未执行项是否实际完成。

旧自动ReceiptIntent六项业务失败与人类执行身份政策、完整126维护停写撤权回填、其他平台兼容候选与两文档冲突、真实库存价格/供应商/SMTP/存储、双端完整64T及生产恢复门禁仍OPEN；不默认created_by。P0仅本地PI/ReceiptIntent草稿，无自动推送/预占/出库。本轮无前端/产品改动，不重复已通过的UI构建与23/10测试。

证据D:/commission-system/tmp/portal-v179-final-evidence.json，包含正式apply三SHA/原22AST保持、RED与候选准备失败/修订、正式11、资源与清理、629运行中快照及收尾检查。恢复材料和回滚备份保留；完整目标未完成。

## 客户门户 v1.78 本轮终态与正式发票前端接入（2026-10-07）

本节是下方v1.78早期运行中快照的后续终态，保留原记录不覆盖历史。完整目标仍active，开发契约仍v1.72；自有codex/customer-portal-dev-docs，main4428ebc078e7d74158037ec60e0233eeb12294fb未变化。未commit/push/merge/部署/外发或操作生产与共享库。

完整624/session23047已由同一exec handle实际返回terminal exit1：2573collected、1773completed，1752pass/6fail/14errors/1skip/3965warnings、internal0、800未执行，3512.28s。六项旧receipt_generation业务失败仍OPEN；14项receipt_reconciliation setup错误全部实际诊断为MySQL1062。首次建对账唯一索引前存在一组远端回款编号重复，261条已提交记录，值只保留hash6a116b47a793ad25。测试来源记录为最新mapper观察，不能认证每一行commit来源；此证据解释当前624错误，不证明历史605根因完全相同。必须修订重复ID测试准备并保留唯一约束及业务断言，不能删旧行、清空编号或放宽索引过关。

624实际终态后，已核MySQL Shutdown complete、精确端口无监听、runtime.datadir、绝对目标边界及全子树无reparse，再用原生PowerShell清理该批自有data/temp两目录；日志、runtime与有限诊断保留。不是正在运行，也无需继续轮询原会话。

终态后正式应用九个前端目标：七个已审main发票文件（API、管理页面、概览组件/CSS、composable、页面CSS、布局规格），加永久invoiceRead.test.mjs及package.json显式test:invoice-read命令。永久16项仅改Vue import和相对源路径，保留原断言；命令要求--experimental-vm-modules。七候选逐字节一致，九目标before备份与after SHA保留；后端未改。独立只读复核无新增具体P1/P2，不代跑或认证日志。原validate/sync/resolve/remove金融调用及权限指令保持。

正式own源码Node22验证已实际终态：session96746 build exit0/3336modules，stderr13001bytes有现存构建诊断，不称零warning；同一正式测试批23pass/0fail/0skip（读取16+布局7）exit0。session8589使用正式own frontend/dist、Chrome、实际Vue/Pinia/router完成同一10场景10pass/0fail/exit0。覆盖四指标与列表、403清空、日志关闭、当前权限变化、实际logout/卸载后的迟到Excel/PDF/print零效果，以及当前读者正常下载/开窗。迟到断言等待route.fulfill、response.finished及原XHR loadend经下一任务和两RAF信号；不是任意sleep。HTTP及身份受控，文件是合成字节，不认证真实JWT/MySQL/provider、商业内容、全双端64T或移动端。正式截图portal-v178-invoice-formal-desktop.png已视觉查看，是合成资料的管理端界面。

前述七文件联合128pass+1skip、27候选build/37Node只证明隔离兼容，不与23/10或历史执行累计。其他平台兼容候选、两文档冲突仍未正式整合。旧自动ReceiptIntent六项失败与人类执行身份政策、126维护停写撤权回填、真实库存价格/供应商/SMTP/存储、完整双端64T及生产恢复仍OPEN；不默认created_by。P0仍只本地PI/ReceiptIntent草稿，不自动推送/预占/出库。

恢复材料：D:/commission-system/tmp/portal-v178-final-evidence.json保留early phase并附本节终态证据；九目标回滚备份portal-v178-invoice-before-apply，正式23/build/10结果、624诊断与清理证明分别单独保留。收尾约定、源引用和本地no-fetch检查记录在final checks；完整项目尚未验收完成。

## 客户门户 v1.78 平台兼容候选与原统计规格准备（2026-10-07）

上一目标轮为实际进展：10个已编译候选页面场景与XHR完成信号、独立复核及准确文档入口已形成。本轮继续验证未接入main增量；完整目标仍active，专题开发契约仍v1.72。自有codex/customer-portal-dev-docs，main4428ebc078e7d74158037ec60e0233eeb12294fb未变化。624仍运行，自有产品/规格/双端dist未修改；本轮候选及准备修订均仅Dtmp，交接记录是唯一仓库修改。未commit/push/merge/部署/外发或访问生产/共享库。

独立namespace overlay实际导入9个候选customer/sales_automation模块，逐一核SHA及__file__；未选择的依赖从own fallback解析。保留五份own测试与原conftest、主分支private_enrichment测试。初次实际session94125 terminal exit1：127collected、125 call完成、121pass/4fail/1setupError、5warnings、4次被阻止的connect；原摘要未计setup skip，不能称2项未运行已证明。三项HTTP call和一项setup因标准库socketpair内部loopback被全connect拦截；另一失败为复制目录缺规格引用的138文件，非已证实产品缺陷。

准备修订仅在同线程执行原标准库socket.socketpair的范围中放行AF_INET/IPv6精确loopback连接；finally恢复，其他connect/connect_ex仍拒绝，不称全网络沙箱。复制原138到规格相对路径，未改任何9候选业务模块或原断言。修订后session74692实际terminal exit0：126call通过/1setup skip/2warnings，127terminal cases/0remaining、0外部connect尝试、4内部socketpair连接。既有skip要求显式临时MySQL URL；不伪造或提供生产URL。原migration138只测试SQLite升降与离线MySQL DDL，不等于126历史切换或真实MySQL迁移。

原主分支invoice_summary两项统计规格的准备仍用未提交共享Session和JWT权限列表，不匹配新事务/当前数据库授权。原始两项实际terminal1/2fail；候选只改_client：真实数据库RBAC关系、提交准备、每请求新Session，仍实际签发JWT，仅覆写get_db，不替换授权helper。_invoice及两个测试函数AST精确保持，包含六字段统计、分页1、非USD、历史unknown、日期、代办撤销及403原断言。prepared实际terminal0/2pass；这是SQLite统计准备兼容，不是新产品修复或真实login/admin/MySQL证明。独立只读核SHA/AST，无新增具体P1/P2，不代跑。

最终七文件联合session75363实际terminal exit0：129collected、128call完成且通过、1setup skip/11warnings，129terminal cases/0remaining/internal0；9候选__file__及三个正式own invoice模块路径实际核验。0非socketpair connect尝试、9内部socketpair连接。初次126、单独2及最终128不累计；本轮最强联合证据为128pass+1skip。HTTP客户域授权为依赖覆写；发票统计直接minted identity JWT，但没有真实登录/管理流程。不能取代v1.75正式73MySQL，也不能证明完整main应用或全44候选正式接入。

新独立frontend复制包含27个main候选及已审invoice reader修复，原v1.76/v1.77候选与产物保留。Node22 build/session7049实际terminal exit0/3340模块，stderr11041bytes为构建诊断，不称零warning。四相关Node文件（素材分组、门户状态、扫码、发票布局）实际37pass/0fail/0skip/exit0；不是全部前端测试或真实DOM/API兼容。own源码/产物未覆盖，未重复客户站构建。本轮两类compat候选仍未应用；44候选及两个文档冲突的正式整合门禁仍OPEN。

完整624/session23047本轮反复由同一exec handle确认live；本段快照2573collected/1725completed，1718pass/6fail/0errors/1skip/3798warnings/internal0。尚无终态退出码，不称全绿，不重启，不清理624数据或改变受测源码。仍待完整前序安全诊断解释605两项对账准备错误。旧自动ReceiptIntent六项失败与人类执行身份政策、126维护停写撤权回填、真实外部合同/服务、双端64T及生产恢复继续OPEN，不默认created_by。P0仍只本地PI/ReceiptIntent草稿，不推送/预占/出库。

结构化本轮恢复材料D:/commission-system/tmp/portal-v178-final-evidence.json；包含精确前版、当前manifest、原统计规格与准备SHA/AST、有限结果、build产物与九模块来源。下一步等待624实际终态，再按审过的候选正式接入并核正式关键路径；隔离编译和SQLite兼容不提前关闭门禁。

## 客户门户 v1.77 发票候选真实DOM与导出完成信号（2026-10-07）

上一目标轮为实际进展：本地Node22与84模式规格、16项读取竞态候选、7布局及隔离构建证据已形成。本轮继续补候选UI验收；完整目标仍active，专题开发契约保持v1.72。自有分支codex/customer-portal-dev-docs，main4428ebc078e7d74158037ec60e0233eeb12294fb未变化。完整624仍在运行期间，自有产品、规格和双端dist均未修改；发票7文件候选仍未正式应用。本轮仅写交接，未commit/push/merge/部署/外发或操作生产/共享库。

使用v1.76隔离已编译管理端、实际Chrome、实际Vue/Pinia与router，HTTP接口全为受控合成响应。最终driver/session22275实际terminal exit0：同次10场景10pass/0fail，父包装stdout1931bytes/stderr0，原输出只在内存计数后丢弃；安全结果portal-v177-invoice-browser-result.json。覆盖真实四指标与列表、筛选403后的行与概览清空、已显示日志的403清空及dialog隐藏、实际Pinia权限变化后的DOM清空、实际auth.logout/router卸载后三路径迟到响应无下载或开窗、当前读者Excel/PDF正常下载及print正常开窗阳性。正常导出文件仅合成字节，不认证格式/商业内容；Pinia身份与接口受控，不认证真实JWT、MySQL授权或完整页面。

日志关闭等待实际Element Plus dialog隐藏终态，保留原日志内容清空及dialog消失断言；不是用任意sleep掩盖失败。独立审查发现原8场景迟到导出只等待网络完成+两RAF，证据只为sampled；已保留原8pass结果为before-xhr-fence。最终三个迟到导出先等待真实请求被拦截，执行实际logout与路由卸载，释放响应后等待route.fulfill完成、response.finished、原XHR loadend经下一任务及两RAF的完成marker，再核零download/popup并关闭context。marker只观察有限export endpoint，不替换axios、响应或业务逻辑。独立只读审查不代跑或认证日志。

驱动初稿8项均卡于重复标题strict-mode选择器，明确页面h2后6pass/2fail；两项分别为英文关闭按钮名称与错误print接口路径，按真实组件class与API源码修订后7pass/1fail，剩余为关闭动画尚未隐藏。等待实际dialog终态后8pass；补XHR完成信号与PDF/print阳性后的最终10才是当前验收结果。新marker初稿syntax启动失败，无业务规格执行，修正后node --check实际exit0及22275终态通过。保留有限失败摘要，不把准备错误称产品缺陷，不累计13/16/7/8/10或历史回归为更多独立规格。

页面级route仅对受测页面阻止非本地origin请求，各场景观测1次外部请求被阻止、业务写API0；不能称整个浏览器所有窗口的网络沙箱。正常print阳性只验实际popup事件。稳定截图portal-v177-invoice-desktop.png来自1440×1100、合成测试资料，等待表格与概览loading mask隐藏后截图；已视觉查看LeShine黑金标识、方舟导航与发票概览。该截图是管理端候选，不代表客户站全64T或移动端验收。

完整624/session23047本轮再次通过同一实际exec handle确认live，落盘时收集2573、完成1154，1153pass/0fail/0errors/1skip/2707warnings、internal0；尚无终态退出码，不称广覆盖通过。保持原规格与已知旧自动生成失败，不重启、不清理624数据目录。仍待首次对账前完整前序诊断解释605两项准备错误。

旧自动ReceiptIntent六项失败/当前执行身份政策、历史126维护停写撤权回填、其余44main候选与2文档冲突、真实库存价格/供应商/SMTP/存储、双端64T与生产恢复均OPEN；执行身份无人类答案，不默认created_by。P0仍只本地PI与ReceiptIntent草稿。下一步待624实际终态后正式接入候选并验证正式构建关键路径；当前10场景仅候选，不据此关闭正式集成门禁。

交付链接核验：真实专题路径为docs/requirements/2026-09-30-customer-order-portal/00-development-guide.md与08-current-adversarial-review.md；上一回复误写docs/customer-portal路径，文件入口需按本段纠正，不另建重复文档。结构化本轮证据见D:/commission-system/tmp/portal-v177-final-evidence.json。

## 客户门户 v1.76 本地 Node22 与前端读取竞态候选（2026-10-07）

本轮为实现进展，完整目标仍 active；专题开发契约保持 v1.72。自有分支 codex/customer-portal-dev-docs，main 4428ebc078e7d74158037ec60e0233eeb12294fb 未变化。尚未将本轮发票前端候选应用到自有源码；完整624在运行期间，自有产品、规格和双端构建产物保持启动时版本。未 commit/push/merge/部署/外发或操作生产与共享库。

独立便携 Node v22.23.3 来自 Node 官方 HTTPS archive 与 SHASUMS256，ZIP SHA256匹配，未验证GPG签名；不安装服务或修改PATH。实际双端构建exit0：英文34模块/5产物、中文3334模块/480产物；中文stderr含现存构建诊断，不称零warning。客户Node规格130pass、管理端portal规格43pass，各exit0；这是本轮原源码实际执行，不与历史执行累计。只闭合本地Node22版本子集，不能关闭远端Linux/生产门禁。

623/session77538实际terminal exit0：四原生mode规格文件84pass/1warning/27.33s，使用Node22/mysql2与独占MySQL。覆盖Node进程/数据库权限/模式锁、bootstrap与原lifespan AST；非mode集成被替换，迁移为薄上游与合成head。不是HTTP/JWT/admin、全历史迁移、真实supplier main或systemd/cgroup验收。复制启动器的scope曾错误包含main/JWT/admin，实际终态后只修正scope；原JSON与原scope保留，计数/时长不改。623的2个owned data/temp目录已核terminal、Shutdown complete、精确端口无监听、runtime.datadir与绝对边界、全子树无reparse后native清理；日志/runtime和安全摘要保留。

完整624/session23047尚live，收集2573项；落盘快照完成700项、699pass/0fail/0errors/1skip/1643warnings、internal0。这是运行中快照，没有终态退出码，不称全绿。保留原全部portal_mysql规格与已知旧自动生成失败，maxfail20；显式Node22浏览器和mode runtime。加入有限异常类型/白名单MySQL编号/类型链与首次对账前已提交remote-ID重复组诊断，不记录SQL/参数/原始异常消息。仍未解释605的两项对账准备错误；此前618未复现不能证明消失。只通过同一实际session23047继续等待，不重新启动、清理624库或中途改受测源码。

独立发票前端审查针对尚未整合的main概览候选发现两类P2：403后保留旧行/日志、身份切换或卸载后的迟到数据及下载/打印。实际原composable+真实Vue reactive/watch/effectScope的受控并发规格最终16项中5pass/11fail；API/auth/browser effects受控、mounted回调未实际挂载。候选清空私有读取视图，身份/权限watch和effectScope卸载使代次失效，列表/概览/日志按最新请求序号接收结果，导出/打印在await后再次核身份代次；不改原删除/同步/人工核对金融调用。

初版13项候选全部通过后，独立审查发现第三项P2：旧拒绝晚于新成功会清空新数据。新增列表/概览/日志反向时序规格对初版形成13pass/3fail，精确初版源码与结果保存。先核身份代次和最新请求序号再处理拒绝后，最终同一16项候选16pass/0fail/0skip，原断言保留；独立只读复核确认该反例闭环，无新增具体P1/P2，但不代跑或认证运行。该证据仅源码语义，不是真实HTTP/JWT、DOM或完整页面验收。

在独立frontend复制中叠加7个main发票候选及最终读取修复，Node22 build实际exit0/3336模块；原invoiceLayout 7项pass/exit0。使用既有依赖junction，自有构建产物未覆盖。候选源码hash、精确before、有限JSON与build产物保留于D:/commission-system/tmp/portal-v176-invoice-ui-candidate及portal-v176-invoice-ui-build。尚未正式接入这7文件，也未据此将44未接入main候选或两个文档冲突称已关闭。下一步先观察624真实终态与诊断，再正式接入并验证候选关键UI路径。

旧自动ReceiptIntent生成的六项失败及当前执行身份策略仍开放；人类未回答，不默认created_by，也不修改断言假定策略。完整历史迁移126维护/停写/撤权/回填、全部writer接入、真实库存/价格/供应商/SMTP/存储、双端64T与远端生产恢复仍OPEN。P0只本地PI与ReceiptIntent草稿，不推送/预占/出库。Node22本地进展和16项前端候选不能关闭这些门禁。结构化恢复材料见D:/commission-system/tmp/portal-v176-final-evidence.json。


## 客户门户 v1.75 当前发票读取授权正式接入与对抗回归（2026-10-07）

本轮为实现进展，完整目标继续 active。专题开发契约保持 v1.72；当前执行证据只记本交接。自有分支 codex/customer-portal-dev-docs / HEAD54f77438328e5aa5d3c776ee309914447672d767；main4428ebc078e7d74158037ec60e0233eeb12294fb 未修改。十文件首批与四文件第二批共有11个不同目标，涉及invoice router/service/新read_authority、两处测试准备、四份原生测试及API/源码清单。无新表/迁移/前端改动，未重复双端构建。

605/session35798已实际terminal exit1：2508collected、1696completed、1683pass/10fail/2errors/1skip/3699warnings，internal0，812未执行、3270.45s。三处队列准备1062及PI必填1364/淘汰探针修订后，保留原唯一约束与财务/网络/唯一PI断言；617与622分别包含正式联合回归。六项旧自动回款生成失败仍开放。两项reconciliation准备错误尚无确定根因，不称duplicate已证实或已修复。

首批在605与616实际终态之后应用。616/session85175候选25pass/104warnings/66.96s；617/session17254正式源码联合33pass/104warnings/75.43s，三invoice模块__file__均指自有checkout，未用Dtmp覆盖。包含list6、summary9、fail-closed10与原号码约束/调度/PI8。十项拒绝边界为4项HTTP授权函数错误注入（诊断sink各模式）与6项直接helper事务/非法sub反例，不能冒称十项真实SQL故障。summary保留主分支统计口径及精确全六字段；原金融变更函数AST保持。summary测试首行在617之后仅作文档修正，函数体不变；622重新运行其最终原生源码。

独立审查发现五GET仍用JWT旧权限：详情、日志、Excel/HTML/PDF导出。619/session28998原30探针实际terminal1，30fail/128warnings/84.17s；日志阳性准备不完整，不能把该批全部计为漏洞。补充真实薄上游InvoiceSyncLog表与每对象一行，原serializer/export包装仅观察并执行原函数，不替换输出。620/session57782修正40探针实际terminal1：30fail/10pass/188warnings/118.93s；25撤权/范围与5新grant反例失败，既有10代办/停用owner对照通过。候选621/session31280实际terminal0：40pass/198warnings/117.96s，实际核候选三模块路径。先核全部活动suite终态再应用五GET入口与原生40规格，保留对象404范围及原响应/生成实现。

最终622/session78475实际terminal0：73pass/284warnings/148.62s，0fail/0error/0skip/internal0，三模块均实际从自有工作树加载，无Dtmp product/test override。真实main/JWT/admin撤权及新grant、生效代办/负责人、对象日志与原导出函数均受测；拒绝时生成/序列化/日志包装零调用，阳性执行原函数；11财务/谱系模型及日志全列快照不变。PDF/Excel阳性仅检查格式头、HTML媒体类型、详情200及原函数调用，不认证完整导出商业内容；最终快照也不是全库或所有DML尝试零的证明。73为同一最终运行，不能累加616/617/621称更多独立规格或全2508通过。

五入口首次发票查询前从新事务读取数据库当前active/deleted/role/action/scope，JWT只识别身份。停用或无读取动作403；撤read_all/super_admin后他人404、本人与当前有效代办可读；当前新grant不必重签token。授权库失败503/private no-store、借用已有事务409；普通读不持有写屏障，也不承诺召回在途响应。独立只读复核实际比较72个同步/异步函数，只五GET AST变化，其余金融/异步函数完整保持；API与134源hash/路由定位相符，无本批新增具体P1/P2。该审查不代跑、不认证日志，也不认证其他读取入口或完整writer覆盖。

618/session36631原14文件顺序复现实际terminal1：541complete、535pass/6fail/0error/1439warnings/1037.07s，未跳过旧generate_ready的六项失败。首次对账前真实已提交remote-ID重复组为空，所有对账规格通过，故未复现605两项准备错误；单独前缀不能证明广覆盖根因消失。仍需带前序依赖的有限安全诊断，禁止删除行或放宽remote唯一约束来过关。

完整历史迁移126的维护/停写/写权限撤销/回填证据、全部writer与旧自动ReceiptIntent执行身份/接入、真实库存价格/供应商/SMTP/存储、完整双端64T/Node22与生产恢复仍OPEN。执行身份政策尚未得到人类答案，不默认created_by。47主分支候选只有三invoice模块正式验证，其余44及两个文档语义冲突未关闭。P0仅本地PI与ReceiptIntent草稿，不推送、预占或出库。

收尾源检查实际exit0：10MD/107本地引用锚点/3JSON/64T/20F/18A、134有限hash/112旧AST+11增量AST/4vectors，冻结165/158/155三包不变。strict/session16206实际terminal0，diff --check实际exit0；no-fetch巡检实际exit0，main0修改/1既有untracked、自有98修改/109untracked、无upstream，仅本地快照。strict在本交接新段之前执行；新段落盘后源检查与diff --check再次实际exit0，独立文本复核无新增具体P1/P2。605/616/617与618–621共14个owned data/temp目录已核实际终态、Shutdown complete、精确端口无监听、runtime.datadir、绝对边界及全子树无reparse后native清理；622实际终态后按同一边界再次核验并清理2目录，合计16个owned data/temp目录已移除。日志/runtime/安全JSON/精确before/候选和恢复材料保留。原始pytest输出仅父进程内存计bytes后丢弃，无traceback/SQL/params凭据落盘。无commit/push/merge回main/部署/外发/生产或共享库操作，无auto-review拒绝。

恢复材料：D:/commission-system/tmp/portal-v175-final-evidence.json、current-applied-manifest.json、两批apply-receipt与精确before目录。下一步优先定位广覆盖对账准备错误，随后完成其余主分支候选与当前writer门禁；自动执行主体依赖真实业务政策，历史门禁不可伪造或stamp绕过。

## 客户门户 v1.74 主分支接入核对与当前发票读授权候选（2026-10-06–07）

本轮取得有效进展，完整实现目标仍 active。专题契约保持 v1.72，产品、正式测试源码、双端构建与132项有限产品哈希未变。605广覆盖仍实际运行，不能修改正在受测的源码或把局部计数称全部通过。本轮仅在Dtmp准备/运行候选与独立反例；候选尚未应用到checkout，不称正式产品修复完成。

已核对自有HEAD54f77438328e5aa5d3c776ee309914447672d767和main4428ebc078e7d74158037ec60e0233eeb12294fb。main新增46文件，五处交叉。初次merge-file的全文件冲突受CRLF/LF差异影响；只规范临时输入换行后三份源码router/service/agent_router无文本冲突，api-reference和handoff两文档仍冲突。三源码可归并不是语义或运行验收。46份主分支候选加新read_authority共47份、17Python AST通过；只有invoice router/service/read_authority三个模块得到下述有限运行验证，其余44候选未验证。原manifest记录自动归并时的字节，权限补丁后的当前SHA见manifest-current.json，原证据保留。

独立审查指出本分支既有invoice list依赖JWT旧角色/范围；main新summary沿用同模式，存在同类跨业务员统计风险。606/session12302实际terminal1，六项call失败但安全分类/frame不足，且初始全量等于两ID的断言受共享历史影响，不能把606全部失败称产品漏洞。607/session45566修正初始阳性为包含本例own/foreign、在拒绝断言前核11财务/订单模型快照；实际terminal1，6failed/42warnings/39.94s。真实login与admin提交后，同一旧JWT在disabled/all_roles/invoice action撤销后仍200且own/foreign可见；read_all/super_admin范围撤销仍带foreign；当前新授予read后旧token仍403。所有六例金融快照不变、已拦截外部调用0。607有直接状态/范围反例，证明当前list的P1撤权/隔离缺陷；未运行未应用的旧main summary，不能把源审风险说成旧summary已复现。

候选在查询前从新Session事务读取当前active/deleted/role/permission，以JWT仅识别员工，覆盖旧roles/perms，保留现有可见查询与当前有效代办/负责人规则；普通读只定义首次业务读授权点，不承诺撤权召回在途响应或获取写锁。608/session69214使用Dtmp namespace overlay，实际核router/service/read_authority三个__file__归属，真实main/lifespan/JWT/admin六例actual terminal0：6pass/42warnings/39.07s。包含拒绝撤权、收窄当前范围和同旧token应用新grant。受控上游/邮箱及薄上游表不等于真实供应商、SMTP或完整迁移。

609/session67950 summary九规格actual terminal0，9pass/64warnings/43.98s；独立RV174/P2发现global使用>=6可能放过错误草稿/取消/区间外统计，不能拿该轮认证精确六单。610/session92737加入独立Session直接关联核active/deleted/实际角色权限、撤权五参数独占日期且初始精确2、两代办参数独占2061/2062并恢复global精确6，actual terminal0：9pass/64warnings/44.32s。611/session71324最终扩为global全六字段精确GMV1390/new_sign3/unknown1/count6/average278/nonUSD1，actual terminal0：9pass/64warnings/45.07s。私人5单全字段、撤代办或负责人停用后4单、分页1、九月首末日、草稿/取消过滤、空/反向区间与当前权限 gate均保留。有限源码独立复核确认RV174/P2定义闭环，不代跑认证日志。三轮九项不是27独立通过，list六项也不能合计成广覆盖全绿。

605广覆盖出现的前三队列失败停clone准备207行，另PI规格停原raw库存哨兵INSERT36行。612/session92575原五规格fresh薄表actual terminal1：4pass/1fail/0warnings/32s，PI为OperationalError1364（必填字段），四队列规格能通过。613/session9340按原invoice_number_conflicts先恢复真实invoice_no唯一约束再跑原规格，actual terminal1：8complete/4pass/4fail/0warnings/31.08s；后三队列为准备阶段IntegrityError1062，原helper跨案例重复QUEUE-index；PI仍1364。此有限组合复现说明准备兼容缺陷，不称调度业务错误，不删除/放宽unique约束。

Dtmp准备候选只给helper每例独立QUEUE前缀，将库存/回款哨兵raw INSERT换ORM完整必填字段和北京时间默认值，仍在baseline与副作用探针之前。614/session60959 actual terminal1：7pass/1fail/0warnings/32.66s；已越过1062/1364，随后PI monkeypatch旧receipts.create不存在，candidate60行AttributeError，未到业务断言。定稿将探针更新为当前receipts.new_row，仍raising=True，没有兼容fallback。615/session77741保留原唯一约束、全部真实scheduler分页/20阻断/唯一POST/任务字段，以及PI/原回执重放/全列财务快照/SQL尝试拦截/网络守卫，actual terminal0：8pass/0warnings/32.56s。独立定向复核未发现削弱断言或新增P1/P2；未核验运行时加载路径、不认证日志。固定900001和薄表无完整FK限制仍在；该8项不是广覆盖2508重跑，准备补丁尚未进入正式源码。

605/session35798继续运行同一受保护父进程，截至本次落盘快照：2508collected、1549completed、1544pass/4fail/1skip/3438warnings、internal_errors0、terminal=false。不得终止/重启或清理正在运行的605，不把快照当终态；后续仍以该session/portal-v174-wide-result.json及wide-process.json实际退出为准。安全stdout/stderr只在父进程内存计bytes后丢弃，新增异常诊断仅白名单类型、受控源frame和有限MySQL编号，未保留SQL/params/token/原始traceback。

606–615均已实际terminal，核对Shutdown complete、精确端口无监听、runtime.datadir、绝对边界及全子树无reparse后native清理20个owned data/temp目录；日志/runtime/安全JSON/候选/精确旧源保留。605保持活动且未清理。本轮源检查实际exit0：10MD/107本地引用锚点/3JSON/64T/20F/18A、132有限产品hash/110旧AST+11增量AST/4reasonvectors；冻结165/158/155三包不变。随后检查：strict/session91734实际terminal exit0，diff --check实际exit0；no-fetch巡检实际exit0，main0修改/1既有untracked、自有98修改/108untracked、无upstream，仅本地快照，不认证远端新状态。

下一步：等待605实际终态后，将经复核的两处测试准备修订和invoice当前读授权/summary候选写入自有分支，正式回归需保留统计口径及真实RBAC，用当前路径重新验证，不能以Dtmp候选验证代替正式集成。再完成其他main候选/两个文档语义冲突和未闭环writer。完整历史迁移126、旧自动ReceiptIntent执行主体与接入、真实库存/价格/供应商/SMTP/存储、完整双端64T、Node22与生产恢复门禁仍OPEN。执行身份政策尚无人类答复，不默认created_by；P0仅本地PI与ReceiptIntent草稿，无推送/预占/出库。无commit/push/merge回main/部署/外发/生产或共享库操作，无auto-review拒绝。

605在后续同session观察新增六项旧自动回款失败，累计1646completed/1635pass/10fail/1skip/3516warnings，仍terminal=false。六项定位test_mysql_receipt_generation的当前撤权、实际发票范围、缺原主体及文件IO锁释放断言；实际调用仍是sync_service.generate_ready，不能用显式generation_service内核历史通过替代旧worker接入。这是本轮实际观察，不仅引用历史558；未默认自动执行主体，待当前人类政策答复。候选八项准备回归不会关闭这六项或完整writer门禁。

结构化恢复材料：D:/commission-system/tmp/portal-v174-final-evidence.json，当前候选manifest-current.json；执行契约版本仍v1.72，不覆盖冻结交付包。

## 客户门户 v1.73 通知验收隔离与 Windows 进程启动器（2026-10-06）

本轮是有效进展，完整实现目标继续 active。当前专题开发契约保持 v1.72；执行进度只记本交接。产品 worker/API/模型/状态机/双端构建未修改。本轮仅修改两个测试辅助文件并新增通知队列隔离反例；安全运行器位于 Dtmp，不计产品修复或发布。

598/session8235 实际 terminal exit3：2506 collected、184 completed、174pass/10skip/440warnings、285.5s、internal_errors1，余2322。旧摘要没有内部错误类型/frame，不能确认 UTF8 根因。新安全运行器使用 UTF8、tryfirst 记录 report、白名单内部错误类型/frame；原始 stdout/stderr 仅在父进程内存计 bytes 后丢弃。发现既有本地 mysql2 3.24.4 并实际 require 验证；Node 实际 v24.19.0，不是 Node22 验收。

600/session6183 显式启用 Node/mysql2 模式测试，实际 terminal exit1：2506 collected、594 completed、581pass/12fail/1skip/1347warnings、858.9s、internal_errors0，余1912。12 个失败都在通知 target 准备步骤，尚未进入锁超时或撤权竞争。不能把局部计数或越过旧内部错误位置称全套绿色。

真实 claim 只领取已到 next_attempt_at 的 pending 或已到 lease_until 的 sending。target 原断言错误地要求所有 pending/sending 消失；601/session1154 两个未来 pending/有效 sending 反例实际 terminal exit1：2failed、0warnings、23.86s，均定位原 helper 第85行。修订后断言匹配真实 eligible 条件，保留真实 worker 选择。独立审查还发现后续 +119/+121秒和最长72小时推进可能领取前例遗留任务；trade 在案例开始前记录已有 outbox IDs，finalizer 在测试与依赖夹具结束后仅以现有 close_event 关闭本案例新增 pending/sending。未删除行、改旧行/终态行或在断言前清理，也未改生产选择规则/限流/租约。

602/session64517 实际 terminal exit1：44 completed、33pass/11fail/0warnings、315.51s。11 个失败是 process.py:42 首次等待 started 的 IPC 超时，不能说已收到 started。独立审查发现 P2 安全启动器结构风险：顶层 OUTPUT 断言及 pytest.main 在 Windows spawn 导入 __mp_main__ 时可能重复执行。两者及父进程 Popen/communicate/回执写入均移入 __main__ 保护。603/session44761 在产品/测试源码不变下实际 terminal exit0：13pass、0warnings、82.34s，覆盖11个进程恢复与2个未来队列反例；此结果与启动器风险定位一致，不能倒写602通过。

最终604/session93353 在同一受保护启动器下完整重跑五文件44规格，实际 terminal exit0：44pass、0warnings、97.55s。包括真实 auth HTTP、锁超时、通知撤权提交次序、独立进程 send-ack 丢失恢复、未来队列反例。新反例明确有限 +2min 路径中未来行所有列不变且实际目标通知发出；该未来行在随后本案例 teardown 会关闭，不证明72小时全局生产队列隔离。44项不能与600的581项或历史597的22项相加，也不是2506全部重跑。

独立599/session96698 的空库历史回放实际 terminal exit1：1fail/48.11s。实际初始化及未替换 Alembic env 到125_invoice_integration，chain-result complete=false、240tables；126._load_cutover_contract 缺固定路径 customer_cutover_contract 和真实维护/停写/撤权/suppression/backfill证据，保护拒绝。未 stamp/downgrade/伪造空清单/移除保护，不称126或非空历史迁移通过。

独立三测试差异审查未见新增具体P1/P2；启动器P2已按源码保护修订，不认证运行日志或整体完成。文档引用/JSON/64T/20F/18A、132有限产品hash/旧AST和冻结165/158/155三包保持；三本轮测试文件额外AST通过，strict与diff检查实际exit0。no-fetch Git巡检actual exit0，main0修改/1既有untracked，自有98修改/108untracked、无upstream，仅本地快照。

已核对 HEAD54f77438328e5aa5d3c776ee309914447672d767 与 main4428ebc078e7d74158037ec60e0233eeb12294fb。main新增私海资料完善与 profile 读取，迁移仍171；尚未集成/验证最新平台兼容。本轮没有运行中修改受测源码、commit/push/merge/部署/外发或生产/共享库操作。完整历史迁移、全部writer/旧自动ReceiptIntent执行身份与接入、真实库存/价格/供应商/SMTP/存储、完整双端64T、Node22与生产恢复门禁仍OPEN。自动执行身份问题尚无人类答复，不默认created_by。P0只本地PI与ReceiptIntent草稿，无自动推送、预占或出库。

结构化恢复材料见 D:/commission-system/tmp/portal-v173-final-evidence.json。下一步核对最新main兼容，并继续未闭环的广覆盖/旧writer合同；本轮通知回归44项通过不能关闭这些门禁。

## 客户门户 v1.72 只读恢复、历史请求与广覆盖（2026-10-06）

fresh591/session69862 实际terminal exit0：2 passed、22 warnings、31.89s。两种只读价格能力各6组有限浏览器场景，商业API拦截0；这两项规格不能相加称12项测试或64T全部通过。

实际方舟API配置只读权限后，使用实际main/OTP/独占MySQL和已构建客户站，验证当前目录/价格、正常下单入口隐藏、三宽浏览提示及手工quote POST403。新增模拟key-only恢复参考：实际GET404响应结束、恢复按钮返回及两帧观察后，原参考仍保存、没有恢复POST或重试按钮；这不是已提交请求丢ACK实验。同公司历史请求通过真实domain服务在取证基线之前创建，来自另一有效采购成员；当前只读成员实际打开列表和详情，价格API/DOM按当前权限遮罩，动作为空。十个财务/订单模型全列取证不变。

本轮扩展七个测试/夹具/取证辅助文件；产品Vue、API、模型、角色、CSS/动效和已有构建不变，没有重复构建或将历史Node130结果冒称本轮执行。589实际2failed/22warnings/32.85s，原因是新driver的Request details标题匹配重复；明确level2后590实际2passed/22warnings/31.83s，但590在终态门槛补强前。591才是补强后的两项终态证据。独立定向源码复核不代跑认证日志。

广覆盖592/session8572实际terminal exit1：收集2503项，完成316项，293 passed, 12 failed, 0 errors, 11 skipped, 0 xfailed, 0 xpassed，946 warnings、534.95s，尚余2187项。采用有限maxfail12；原规格保留，因停止门槛本次未执行旧自动回款生成规格，不用历史失败冒充本轮结果。原始stdout/stderr只在父进程内存计bytes后丢弃，保留退出码、白名单结构摘要和失败sourceframe。启动器前两次exit4尚未收集/建DB，安全只读诊断确认缺少backend模块路径，修订后才开始上述实际运行，不能计为业务规格。广覆盖失败明细见安全JSON D:/commission-system/tmp/portal-v172-wide-result.json；没有启用full-chain专用历史回放或缺失Node mysql2的mode runtime，不等同完整迁移或2503项全绿。

上述12项为三类验收代码问题：9项在跨案例共享固定密钥的IP发码桶发生429；1项联系人选择器遇同名员工歧义；2项锁序观测器误把MySQL超时设置读取当作业务SQL。联系人593隔离单跑实际1pass/9warnings/31.21s；594同名员工反例实际1fail/3warnings/29.11s，安全driverframe29:76。同名修订按真实settings GET中员工id求候选顺序，仍通过真实UI选项点击并核对保存的精确actorID。595额度对照初稿IP撞夹具初始login导致2fail/1pass/23.63s，纠正测试IP后596实际2pass/1fail/23.63s：只有第二独立案例首次发码429形成干净RED，不能把595初稿错误称产品缺陷。

每trade只生成一次随机OTP密钥，不删除限流桶，不在登录或second_company再次换密钥，保留同案例共享IP额度、邮箱间隔和验证码绑定。锁序观测仅有限放行精确两条超时SQL，并要求顺序/SET参数；任意其他首SQL即中断，仍要求唯一首业务SQL是AuthorityBarrier FOR UPDATE。597/session75512修订后实际terminal exit0：22 passed、29 warnings、45.98s；包含2只读应用浏览器、1联系人router-only浏览器、6锁序参数、1身份重绑、8两成员拒绝事务、1邮箱HTTP及3真实额度/冷却规格。两个独立案例各30挑战/第31次429、桶count30/无邮件事件；同账户即时重发仍429。22项不是广覆盖2503全部重跑；未执行的2187项及广覆盖中未选入这22项的通过项未在夹具修订后重跑，不累计22+293。独立风险差异源码复核无新增具体P1/P2，不认证运行或整体完成。

完整历史迁移126、全部writer/旧自动ReceiptIntent执行身份与接入、真实库存/价格/供应商/SMTP/存储、完整双端64T、生产发布与恢复门禁仍OPEN。执行身份政策尚未得到人类答复，不默认created_by或接旧worker。P0仅本地PI与ReceiptIntent草稿，无供应商推送、预占或出库。以下章节按各历史时点阅读，不累计历次测试数量。

v1.72收尾实际证据：源检查exit0，10MD/107本地引用锚点/3JSON/64T/20F/18A、132有限hash/110原AST+11增量AST/4reasonvectors；冻结165/158/155不变。产品Vue与原交易/开通测试六份SHA保持v1.71；没有重复构建或Node130。最终strict73588实际terminal0、两JS语法及diff --check exit0。no-fetch巡检首次因写自有tmp看板权限受限失败，按仅写自有tmp的授权重跑实际exit0；main0改动/1既有untracked，自有98修改/108untracked无upstream，为本地快照。589–597的18个data/temp目录已核实际Shutdown complete、精确端口无监听、runtime.datadir、绝对边界与全子树无reparse后native Remove-Item清理，保留日志/runtime/安全JSON/截图/PDF/before。主线程查看591实际320恢复及隐价历史请求图；597安全联系人报告确认同名候选6。两轮独立有限源码与13文档页首复核无新增具体P1/P2，不代跑认证运行。结构化记录D:/commission-system/tmp/portal-v172-final-evidence.json。

继续执行状态（非v1.72已完成结果）：修订后的广覆盖598/session8235已实际启动，新安全摘要D:/commission-system/tmp/portal-v173-wide-result.json已收集2506，terminal=false；父进程终态写portal-v173-wide-process.json。继续maxfail12，真实owned MySQL/受控上游，无full-chain flag和缺失Node mysql2 mode runtime。保持全部原规格及新增3项额度规格，不编辑正在受测源码、不以启动当通过；后续以同session实际终态更新。此批不得现在清理数据，也不得合计本轮22和历史293成总体绿色。执行身份政策待人类答复，goal active，全迁移/writer/外部/64T/生产门禁OPEN。无生产/共享库/部署/commit/push/merge/外发；没有auto-review拒绝或绕过审批。

## 客户门户 v1.71 实际只读权限与操作提示（2026-10-06）

fresh587/session83971实际terminal exit0：11 passed、133 warnings、141.93s；4项实际应用浏览器、2项实际main API回归、2项仅挂载router的能力HTTP回归及3项诊断。两个新增只读参数各4组、开通8组、原交易18组有限浏览器场景，不能相加称34项测试或64T全部通过。

修复只读客户仍显示Selection及直接进入checkout提示添加商品的体验问题。place_order=false时隐藏正常下单导航，目录说明仅可浏览；直达checkout显示Collection access only与返回目录。原receipt/pending恢复分支优先级及Requests保留，隐藏价格和商品不可加入的既有规则不放宽。

本轮三Vue产品修复、独立两参数Python/JS及共用safe runner/seed helper；后端权限/状态机/schema、CSS/动效和中文构建不改。旧构建586/session67791 terminal1：2failed、22warnings、31.79s，frame43:9实际Selection可见。源码确认并修订driver的detail获取（HTTP独立读，不虚构show发GET）与403码ACTION_FORBIDDEN；不计产品缺陷。新客户站build34模块/1.17s、130Node状态测试exit0。

方舟身份/负责人/商品和上游为隔离前提，真实main/JWT/OTP/独占MySQL及已构建Vue受测；只读配置通过实际方舟API，非新增配置UI验收。新只读浏览器未植入恢复marker或打开历史Requests，这两项保护仅定向源码核对，不能冒称已以只读身份做浏览器复验。完整历史迁移126、全部writer/旧自动ReceiptIntent执行主体与接入、真实库存/价格/供应商/SMTP/存储、全部双端64T及生产门禁仍OPEN。自动回款主体政策已集中async提问，尚未答复，不默认created_by或接旧worker。P0仍仅本地PI与ReceiptIntent草稿，无推送、预占或出库。

独立只读三Vue及新增test/helper审查确认恢复分支源码优先、Requests/隐价条件保持，未见新增具体P1/P2；不认证日志。只读每参数四组，开通八组、原交易十八组分开，十一规格中含三诊断/两router-only HTTP，不累计历史数量。严格秘密stdin/清理和有限frame白名单保持。冻结165/158/155不覆盖，无生产/共享库/外部/部署/commit/push/merge/外发，完整goal active。收尾实际终态：sourcechecker exit0，10MD/107本地引用锚点/3JSON/64T/20F/18A、132有限sourcehash/110旧AST+8增量AST/4reasonvectors，冻结165/158/155三包SHA保持。最终strict session11453 terminal0，Node syntax和diff --check实际exit0；本地no-fetch巡检exit0，main0修改/1既有untracked，自有98修改/108untracked无upstream，仅本地快照。586–588实际Shutdown complete、精确端口无监听、runtime.datadir与绝对目标/无reparse核验后六个data/temp目录native Remove-Item已清理；日志/runtime/安全JSON/截图/PDF及精确before保留。主线程查看588实际320只读图并确认页首匹配；非全页面认证。独立定向源码/新文档复核有限，无新增具体P1/P2，保持587与588结果分开，不认证日志。结构化记录D:/commission-system/tmp/portal-v171-final-evidence.json。无auto-review拒绝、未结测试进程或外部操作，完整goal active。

最终页首微调后的有限复验：主线程查看587实际320图后，将仅浏览状态标题/说明改为Your collection及浏览说明；browsingOnly明确排除pending和receipt，不覆盖旧回执或未知提交页首。最终build34模块/561ms实际exit0，fresh588/session88178实际terminal exit0：2 passed、22 warnings、31.86s，两个只读价格参数各三宽新增h1阳性及原API/DOM/财务断言通过。587的11项是页首微调前联合回归；其余9项未在标题微调后重跑，不能合计13项或称最终全11重跑。独立只读复核确认新computed与该证据拆分，不代跑认证日志。

## 客户门户 v1.70 实际恢复登录与320px确认（2026-10-06）

fresh585/session54143已实际terminal exit0：7 passed、131 warnings、135.91s；2项浏览器、2项实际API回归与3项诊断。新开通浏览器8组、原交易18组有限场景，业务API拦截均0；不相加称26项测试或全部64T通过。

商品授权恢复后，英文320px页面实际普通login OTP登录并读取当前唯一SKU，再获取新有效报价。保留原cookie的独立上下文仍对session/catalog返回401；原报价继续expired，新会话/报价保存恢复后的权限版本，没有复活旧会话或旧报价。自然等待实际验证码发送后的61秒，不改时钟、限流、历史挑战或数据库来绕过60秒间隔。

新增仅四测试辅助差异：onboarding Python/JS、共用browser helper和owned_invitation_mailbox；原交易JS字节不变。目标OTP broker只限新onboard已消费邀请建立的active/verified账号/site/customer/assignment/identity/owner/member，挑战issued_version核对；原其他case范围不变。两个会话与新旧报价归属/版本独立SQL核验，原其他客户/商品及六财务订单模型全列不变。

584/session34014 terminal1：1 failed、6 passed、131 warnings、134.64s；新增浏览器report pass/8组，但Python错用不存在Quote.catalog_version。改为authority_versions_json并加强当前/旧access版本及账号/成员一致断言，585完整重跑。独立只读有限源码复核无其他新增确定P1/P2，未认证日志。

开通草稿/目录移除恢复的确认与保存实际320px；英文320px重新登录/唯一商品按钮及页面无横溢出，新截图保留。非完整键盘/无障碍认证。

本轮仅扩展四份测试/取证辅助，产品API、模型、角色及双端构建不变，原交易浏览器字节不变。方舟身份/归属/标准SKU为隔离前置数据；实际门户授权与采购账号来自服务。报价通过实际HTTP，非新增报价UI验收。上游及邮箱取证受控，非SMTP送达或生产认证。完整历史迁移126、全部writer/旧自动ReceiptIntent主体与接入、真实库存/价格/供应商/邮件/存储、完整双端64T与生产门禁仍OPEN。P0仅本地PI和ReceiptIntent草稿，不推送、预占或出库。 自动Intent主体仍待用户回复，126真实门禁不能伪造，冻结165/158/155不覆盖，无生产/共享库/外部/部署/commit/push/merge/外发，完整goal active。独立文档复核RV170/P2发现README把两次OTP读取写成两个挑战消费均被直接验证；已收窄为activate/login两次OTP读取、Invitation已消费及login AuthChallenge已消费。审查方只读确认文字闭环，不称activate挑战消费字段已直接验证，不改测试或冒称重跑业务；不是已复现产品漏洞。 收尾实际终态：sourcechecker exit0，10MD/105引用锚点/3JSON/64T/20F/18A、132有限sourcehash/110旧AST+7增量AST/4reasonvectors，冻结165/158/155三包SHA保持；strict session71740 terminal0、Node syntax及最终diff --check exit0、本地no-fetch巡检exit0。main0修改/1既有untracked，自有98修改/108untracked无upstream，仅本地快照。584/585实际Shutdown complete、精确端口无监听、记录datadir与绝对目标/无reparse核验后四个data/temp目录native Remove-Item已清理；runtime/log/安全JSON/截图/PDF及精确before保留。主线程查看585实际320恢复目录截图，非全页面认证。独立定向源码及新增文档复核不代跑/认证日志；结构化记录D:/commission-system/tmp/portal-v170-final-evidence.json。无auto-review拒绝、未结测试进程或外部操作。

## 客户门户 v1.69 实际新客户开通与商品授权（2026-10-06）

fresh583/session30582已实际terminal exit0：7 passed、132 warnings、77.31s。包括独立新开通浏览器规格1项、原交易浏览器规格1项、实际应用API回归2项及诊断规格3项；两个浏览器分别6组和18组有限场景、商业API拦截均0，不能相加称24项测试或64T全部通过。

本轮新增独立onboarding Python/浏览器两文件，修改原测试fixture、浏览器安全辅助和strict owned_invitation_mailbox三文件，产品API/模型/构建不变，原applicationTrade.browser.mjs不变。有效canonical身份/当前主负责人/商品为独占隔离前提；目标PortalAccess开始不存在，实际UI创建一个绑定草稿及标准SKU授权、明确启用、创建邀请，英文OTP形成已验证账号/成员和会话。缺失身份候选不可创建；独立other_scope_admin参数下另一业务员具有操作权限，自己列表阳性但目标读取/修改404。

实际中文授权移除/恢复后版本和审计正确，已有报价expired、唯一会话revoked；旧会话恢复后仍401。既有Access/Grant、所有CatalogItem及六个财务订单模型所有列不变。原订单/接受回执/映射v1/唯一PI/ReceiptIntent草稿/PDF全文页数独立回归通过。新案例报价用真实HTTP，未增加报价UI；邀请密文严格只读broker不等于SMTP。开通及授权移除/恢复三弹窗1440/390/320截图与宽度有限检查，主线程查看583实际390恢复截图，不称完整移动端或无障碍验收。

582/session18218 terminal1：1 failed、6 passed、119 warnings、75.28s，新报价驱动缺Origin；修正后583/session30582 terminal0，上述七规格通过，原交易十八组、新开通六组，不相加称二十四独立pass。独立只读复核闭环Origin驱动问题；缺canonical_customer_id误判被审查方按当前73行撤回，无产品缺陷或修复登记，有限源码未见新增确定P1/P2，未认证运行日志。

本轮目标客户的方舟身份、有效负责人和标准商品仍为隔离前置数据；门户授权、商品授权、邀请及采购账号由实际服务创建。邮件通过实际加密outbox的严格只读取证代理，不证明SMTP发送/送达。报价创建通过真实HTTP，未新增报价UI验收；恢复商品授权不复活已撤销会话，未证明新OTP登录后的恢复目录。完整历史迁移126、全部writer、旧自动ReceiptIntent执行主体与接入、真实库存/价格/供应商/SMTP/存储、完整双端64T与生产发布仍OPEN。P0只生成本地PI与ReceiptIntent草稿；不推送、预占或出库。 自动Intent执行主体问题仍待用户回答，不默认created_by；126真实停写/撤写/抑制/回填证据不能伪造。冻结165/158/155包保持，无生产/共享库/外部/部署/commit/push/merge/外发，完整goal继续active。收尾实际终态：sourcechecker exit0，10MD/103本地引用锚点/3JSON/64T/20F/18A、132有限sourcehash/110旧AST+7增量AST/4reasonvectors，冻结165/158/155包SHA保持。strict session53071 terminal0；两浏览器Node syntax与最终diff --check exit0；本地no-fetch sweep exit0，main0修改/1既有untracked，自有98修改/108untracked、无upstream，仅本地快照。582/583 MySQL实际Shutdown complete、精确端口无监听、记录datadir与绝对目标/无reparse核对后四个data/temp目录已native Remove-Item清理；runtime、日志、安全JSON、截图、PDF、精确修改前副本保留。独立定向源码/文档审查范围有限，不代跑或认证结果。结构化记录D:/commission-system/tmp/portal-v169-final-evidence.json；无auto-review拒绝、未结测试进程或外部操作。

## 客户门户 v1.68 实际邀请激活与账号撤权（2026-10-06）

上一轮v1.67真实映射与加载阳性分类progress，完整goal继续。本轮仅三测试规格、新专用只读owned_invitation_mailbox.py及关联文档修改；产品API/模型/权限/构建不改。既有客户身份绑定/目录仍为隔离夹具，非本轮开通/商品授权UI真验收。

实际中文root客户详情邀请新邮箱/联系人、确认后POST创建回执（Idempotency-Key），真实服务创建账号/成员/邀请与加密outbox；只读broker限定ctx access/root签发、fixture新邮箱、待邀请/未验证、成员关联/版本/到期、信封AAD/token_hash，无任意邮箱/事件读取或外发。OTP原2login加独立有效外国账号login仅用于分辨回退，以及目标单邀请activate，非任意读取。原stdin/原stdout-stderr安全清理保持；public challenge UUID仅用于DB核验。

hash/query链接GET清地址秘密、零自动API/会话；三次target Account/Membership/Invitation所有列不变，包括错误外公司激活前后。真正邀请邮箱经实际OTP激活一次，专属目录有本人商品可见阳性；同公司成员读取原历史，实际中文按account public id+If-Match+reason确认停用后旧订单GET401/页面退出且原buyer200。最终Invitation已消费、目标已验证后disabled、正确active成员、一有效activate challenge/一个撤销session。

独立RV168-01/P2指出不存在邮箱反例不足区分正确拒绝/退回普通login。新增独立有效、verified、同other_access外国公司账号避免原foreign后续登录60秒限频冲突；不得降限频或睡眠规避。实际拒绝challenge为activate、无account/invitation、无auth_code事件/该账号session；外国Account/Membership所有列与初始相同。该修订是强化证据，未复现产品漏洞，不称产品RED/GREEN。原映射v1全列、财务五模型全列、PDF全文/页数/唯一PI/草稿及原接受POST/回执/撤权断言保持。

579/session45767实际terminalexit1：1failed/2passed/3deselected、48warnings/40.93s，安全frame154:9是错用不存在/auth/me的新增断言；按实际router/client合同改/session而保留401。580/session9395实际terminalexit0：3passed/3deselected、101warnings/62.20s，18组但转发负例仍用不存在邮箱，不能替代加强后反例。fresh581/session70058实际terminalexit0，3passed/3deselected、101既有warnings/62.98s；选中原浏览器交易内核及两项实际应用API回归，浏览器18组有限场景、商业API拦截0。 Cmd沿用v167两文件与-k选择，显式mysqld和全新run581/pytest581、Node/Playwright/Chrome；不加载共享.env。Dtmp/portal-mysql-581.log、browser-evidence/report/runner-summary/server-evidence保留，实际原接受POST1/ACK故障1/receipt1，PDF响应3，业务回执DML0；idle UPDATE不等于成功恢复次数。

新增邀请弹窗1440/390/320、确认前按钮禁用，主线程查看580实际390截图；不称全页面/键盘/无障碍验收。test-only loopbackHTTP/main生命周期与OTP/只读邮箱代理，非portal初始化/调度和上游受控、受控一次已提交ACK503故障，非生产TLS/物理崩溃。原真实邮件/未知HTTP/DML禁止护栏保持。

本轮以隔离的已有客户绑定及目录授权为前提，不称新客户绑定/商品授权页面已完成实际服务验收。邮件仅实际进入加密outbox队列，测试只读取证，不证明SMTP发送或送达。完整历史迁移126、全部writer及旧自动ReceiptIntent主体/接入、真实库存/价格/供应商/SMTP/存储、完整64T与生产门禁继续OPEN；P0仅本地PI和ReceiptIntent草稿，无推送、预占或出库。 126真停写/撤写/抑制/回填证据不伪造；旧Intent主体政策未回答，不默认created_by。冻结165/158/155包不覆盖，无生产/共享库/外部/部署/commit/push/merge/外发。完整goal active，收尾实际终态：sourcechecker exit0，10MD/99本地链接锚点/3JSON/64T/20F/18A、132有限sourcehash/110旧AST+6增量AST/4reasonvectors，冻结165/158/155三ZIP SHA保持；Node syntax及diff --check实际exit0。strict session91517 terminalexit0，UI表格不变量与冻结旧债务通过；本地no-fetch sweep实际exit0，main0modified/1既有untracked，自有98modified/108untracked无upstream，只是本地快照。579–581各MySQL实际Shutdown complete、精确端口无监听，root/datadir/target及无reparse核验后6个data/temp目录native Remove-Item实际exit0；日志/runtime/安全JSON/截图/PDF及代码before和各文档精确before保留。独立最后源码与新顶注只读复核确认RV168-01闭环、无新增具体P1/P2，未代跑或认证日志。结构化记录D:/commission-system/tmp/portal-v168-final-evidence.json；无auto-review拒绝、未结进程或外部操作，完整goal继续active。

## 客户门户 v1.67 实际映射页面及加载阳性验证（2026-10-06）

继续完整实现goal，本轮仅三份测试规格及相关文档修改，不改产品API/模型/角色或静态构建。fixture两个实际隔离业务员角色增加portal_access:read，无read_all/admin；other_access_id、CatalogItem.display_name/color_name通过原私有stdin传递，不持久化凭据。

中文实际客户管理页进入MappingDialog：标准SKU/颜色选项、新别名货号、真实预览、base_version/If-Match/标准item_id检查、未确认禁用、可见确认标签点击、发布v1；建PI后实际更新发布v2。另一业务员列表实际含自己的客户且无目标，映射GET/preview/publish均404 RESOURCE_NOT_FOUND，拒绝后原版本2和row_version保持；另一客户真实catalog仍显示获授权默认名，无目标别名/货号。

独立发现RV167-01/P2加载假绿：原标题/外壳负面断言可在空loading页通过；新增成功真实responses、自身项与可见按钮阳性后再排除他人数据。独立修订复核指出origin重复拼接已修，原MappingRevision/财务五模型/PDF/商业断言未弱化，无其他具体P1/P2；未代跑或认证实际运行。

575/session99758 terminalexit1：1failed/2passed/3deselected、46warnings/69.07s，安全frame73:68为非filterable select隐藏输入。576/session60854 terminalexit1：1failed/2passed/3deselected、46warnings/69.10s，安全frame76:115为select-v2实际使用select命名空间、wrapper class错误；根据真实node_modules源码正常click .el-select__wrapper，不force/不DOM设值。577/session22471 terminalexit1：1failed/2passed/3deselected、82warnings/59.10s，安全frame317:29为期待默认名误取standard_json原始字段；实际projection使用CatalogItem展示字段，修seed保持严格断言。重复同值fixture/seed已去除。第一次Node --check相对路径在backend错误，回项目根后实际exit0；不算业务测试失败。三个失败均为驱动/期待数据修订，不称产品缺陷RED/GREEN。

fresh578/session6544实际terminalexit0，3passed/3deselected、87既有warnings/60.11s：真实英文客户端与中文管理端、实际main/OTP/JWT和独占MySQL；浏览器报告13组场景、商业API拦截0。 命令：owned Python -m pytest tests/portal_mysql/test_mysql_customer_application_browser.py tests/portal_mysql/test_mysql_application_trade.py --confcutdir=tests/portal_mysql -p no:cacheprovider -k 'current_customer_bundle_actual_application_trade_and_receipt_recovery or actual_application'，显式owned mysqld/新workspace及basetemp/Node/Playwright module/Chrome参数（同上一轮路径，仅batch578）。原接受POST1/ACK故障1/成功原回执、3次实际PDF响应和两个下载文件全文页数、Publication/Invoice/InvoiceItem/Conversion/ReceiptIntent五模型所有列不变；新MappingRevision v1所有列保持并严格仅[1,2]。PI/Intent draft/Conversion/Publication各唯一、128.00总额/原Invoice salesperson、canonicalSKU、无供应商自动请求保持。实际main lifecycle finally与owned MySQL shutdown护栏保持，receipt业务DML0；receipt idle UPDATE计数不等于成功恢复次数。

新增映射初次/更新弹窗各1440/390/320；主线程查看577初次1440实际截图，非全后台/键盘/无障碍验收。测试实际API无拦截，上游库存价与非portal初始化/调度受控；loopbackHTTP/OTP broker和已提交ACK替换只用于测试，非生产TLS/崩溃恢复。Dtmp575–578 logs、runtime、safe evidence、截图/PDF及三文件before保留。

这是一条有限链路，三项纯诊断规格未选；64T仍为验收规格，不能称全部通过。完整历史迁移126、全部writer/旧自动ReceiptIntent执行主体及接入、真实库存/价格/供应商/SMTP/存储、生产发布与完整双端验收继续OPEN。P0仍仅本地PI和ReceiptIntent草稿，无供应商推送、预占或出库。 不重跑完整迁移或伪造126空批准清单，不自动选择ReceiptIntent主体。冻结v165/v158/v155包不覆盖；无生产/共享库/真实外部/部署/commit/push/merge/外发。完整goal active。收尾实际终态：sourcechecker exit0，10MD/92本地链接锚点/3JSON/64T/20F/18A、132有限sourcehash/110旧AST+5增量AST/4reasonvectors，冻结三包SHA保持；Node syntax及diff --check实际exit0。strict session74373 terminalexit0，UI表格不变量与冻结旧债务通过；20:26 no-fetch sweep实际exit0，main0modified/1既有untracked，自有98modified/108untracked且无upstream，只是本地快照。575–578各MySQL实际Shutdown complete、精确端口无监听，root/datadir/target及无reparse核验后8个data/temp目录native Remove-Item实际exit0；日志/runtime/安全JSON/截图/PDF及before保留。独立最终源码与新顶注定向复核无新增具体P1/P2，未代跑或认证日志。结构化记录D:/commission-system/tmp/portal-v167-final-evidence.json；没有auto-review拒绝或未结运行，完整goal active。

## 客户门户 v1.66 双端真实应用交易联调（2026-10-06）

上一goal轮完成v1.65详细文档/独立审查与逐字节交付，分类progress。当前继续完整实现目标，不缩为测试子目标。本轮只扩展backend/tests/portal_mysql/test_mysql_customer_application_browser.py及frontend-portal/tests/applicationTrade.browser.mjs，产品API/模型/权限/业务代码不改。

测试Only双构建static壳：/login及/portal选择实际frontend/dist，客户页选实际frontend-portal/dist，resolve/is_relative_to限制根路径；全部/api继续进入真实main。一个实际lifespan/ownedMySQL、真实OTP/客户会话与员工JWT。中文端实际登录、完整提案预览/发送、客户接受后审核及审计；跨业务员页面与GET/POST均拒绝，停用后旧JWT403、刷新无详情行。映射仍员工真实HTTP，root能力撤销/停用仍真实管理员HTTP，不称配置UI已真联调。

实际运行：571/session53241 terminalexit1，1failed/3deselected/23warnings/33.58s，安全frames52:67、117:22定位同名layout/page标题；限定.portal-heading。572/session95653 terminalexit1，1failed/3deselected/25warnings/63.60s，frame129:84为ElementPlus隐藏input .check，改正常可见.el-checkbox标签click+isChecked断言；不force/不DOM设值。573/session58914 terminalexit1，1failed/3deselected/38warnings/71.78s，frame205:78为审计关闭仍英文名，按实际main zhCn locale修为关闭此对话框。均为驱动适配，未宣称产品RED/GREEN或弱化商业断言。

574/session77103实际terminalexit0，1passed/3deselected、45既有warnings/46.85s。完整命令：owned Python -m pytest tests/portal_mysql/test_mysql_customer_application_browser.py --confcutdir=tests/portal_mysql -p no:cacheprovider -k current_customer_bundle_actual_application_trade_and_receipt_recovery；显式mysqld、全新workspace/basetemp、Node/Playwright module/Chrome参数保持。Dtmp/portal-mysql-574.log及portal-mysql-run574/browser-evidence保留。12组有限场景，原客户接受POST1/回执成功观测1、PI/Intent草稿/Conversion/Publication唯一及实际财务归属；PDF3、实际两个文件全文/页数、五模型全列对比不变。GET动作回执2个idle UPDATE包括外公司拒绝读取，不称两次成功恢复；commercialReceiptReadWrites0。实际main生命周期finally线程join、schedulerNone/dispose1仍断言。三个未选纯诊断规格未重跑，不能称本轮4passed或全64通过。

新增中文弹窗proposal/approval/audit各1440/390/320，scrollWidth<=clientWidth+1；主线程查看574 actual-main-employee-approval-1440.png及573手机提案定位图，非全部主页面/键盘/无障碍/视觉认证。原客户三宽及主状态文案断言保持。独立只读两文件与before快照定向审查无新增具体P1/P2，明确几何、映射HTTP、合成upstream边界，未代跑或认证运行。Nonportal seed/jobs受控，loopbackHTTP与OTP broker仅测试，提交后一次503替换非真实断网或崩溃；外部API/SMTP/未知DML护栏保持，无供应商调用。

完整迁移126仍需真实绑定停写/撤写/抑制/回填证据，本轮未新跑或伪造。全部writer/旧automaticIntent执行主体政策、真实库存/合同价/供应商/SMTP/存储、完整双端各页面、生产及64T整体验收继续OPEN；P0仅本地PI+ReceiptIntent草稿，无推送/预占/出库。v1.65/v1.58/v1.55冻结包不覆盖。没有生产/共享库/部署/commit/push/merge/外发；完整goal active。本轮最终结构/strict/diff/no-fetch及owned runtime清理另补精确证据。

v166收尾实际终态：sourcechecker exit0，10MD/86本地链接锚点/3JSON/64T/20F/18A、132有限sourcehash/110旧AST+4增量AST/4reasonvectors，v165/v158/v155冻结ZIP SHA保持；Node syntax与diff --check exit0。strict session29844 terminalexit0、表格不变量及冻结旧债务通过；20:02 no-fetch sweep实际exit0，main0modified/1既有untracked，自有98modified/108untracked无upstream，仅本地快照。四个owned MySQL实际Shutdown complete、fixture wait/poll完成且各精确端口无监听；root/data/temp路径、datadir及无reparse核验后，8个data/temp目录native Remove-Item actualexit0。第一次清理仅PowerShell字符串变量冒号解析错误，整段未执行；修正语法后完成，未跨shell删除或改ACL。保留runtime/日志/三宽截图/实际PDF、before快照与安全证据；最终结构化记录D:/commission-system/tmp/portal-v166-final-evidence.json。独立最终差异/新顶注复核无新增具体P1/P2，未代跑或认证执行。没有auto-review拒绝、生产/共享库/真实外部/部署/commit/push/merge/外发，完整goal继续active。

## v1.65 详细开发文档与两路独立对抗审查交付（2026-10-06）

本轮用户请求为生成详细开发文档并进行对抗审查。仅修订专题README、00开发总纲、08当前审查与本交接；既有01–07详细契约和业务实现保留。两路独立只读复核分别检查当前权限/数据隔离与交易/金额/唯一PI契约，未新增具体P1/P2；不认证历史执行或生产。已登记旧自动generate_ready/执行主体、全部writer、完整历史迁移及真实外部/生产门禁继续OPEN。

本轮未执行Dtmp/portal-v165-dual-ui.py，也未执行新的业务浏览器/MySQL测试。此前准备的中文frontend构建session55618实际terminalexit0、16.45s及既有chunk警告仅作为准备结果，不称双UI业务验收。当前产品与两处实际应用浏览器规格hash与本轮起点一致。客户链路仍按v1.64实际范围阅读，完整目标继续active。

文档结构预检实际exit0：10MD/76本地链接锚点/3JSON/64T/20F/18A、132有限sourcehash及110旧AST+4增量AST、4reasonvectors；仅文档/source检查。约定脚本实际exit0，UI表格不变量通过、原legacy债务冻结；git diff --check实际exit0，只有既有CRLF提示。no-fetch巡检初次生成worktree/tmp看板受sandbox写限制exit1；针对该看板写入的窄授权重跑exit0，未fetch/推送/合并。主目录0modified/1既有untracked，自有98modified/108untracked无upstream，仅本地快照。

交付包将保留当前10专题、writer清单和本交接，附逐文件SHA-256/来源与校验报告。旧v1.58 ui从原冻结ZIP按相同字节复用，仅标为早期合成视觉参考；旧v1.58/v1.55ZIP不覆盖。最终文档/验包结果另记录在交付校验报告。没有生产/共享库/真实供应商/SMTP/部署/commit/push/merge/外发操作。

## 客户门户 v1.64 原回执状态文案修订（2026-10-06）

RV163-02/P2已作局部修订：确认提示把原回执中的状态标为“Request status when checked”，并提示Refresh details；不再称其为持续更新的当前状态，也不无条件声称详情GET已成功刷新。原request_id限定、原回执来源和客户授权保持，普通GET不能据此确认原动作成功。页面当前订单徽标继续取实际详情，允许核对时待审核与当前PI created并存。

新增真实应用浏览器对照：客户接受的已提交ACK由测试外壳一次替换503、刷新核原回执，再由真实员工审核建PI。旧构建569实际1failed/3deselected、27warnings/30.70s，安全摘要指向新增状态断言153:9；修订后构建34模块/578ms通过，fresh570实际1passed/3deselected、32既有warnings/31.76s。保留原八组链路断言，原POST1/成功回执观测1、PI唯一、历史PDF全文/页数/五模型全列不变和当前隔离/撤权仍通过。三项未选纯诊断规格为v1.63既有结果，不相加称本轮4pass或全64通过。

当前bundle原orders浏览器回归实际exit0、36合成API调用，精确PI created/Cancelled状态断言仅更新标签，原交互和三宽保持。真实应用截图1440/390/320及1440主线程视觉检查证明提示时间口径修订；非全无障碍/视觉验收。独立源码/断言定向确认局部修订，无新增具体P1/P2；不认证运行或生产。详情见本节终态记录。

v1.63及更早章节按历史时点阅读，RV163-02当时OPEN由本节局部关闭；完整writer/旧自动Intent、真实供应商/邮件/存储、历史schema/进程/生产及64项整体验收仍OPEN，自动Intent主体政策待用户回答。P0仍仅本地PI和ReceiptIntent草稿，不自动推送、预占或出库。

本轮真实运行：569/exec14122 terminalexit1，570/exec57444 terminalexit0；精确日志D:/commission-system/tmp/portal-mysql-569.log及portal-mysql-570.log，真实570报告/服务端证据/PDF/三宽截图在portal-mysql-run570/browser-evidence。新orders回归tool实际exit0/3.02s、36合成API调用，Dtmp/portal-v164-orders-browser.log；当前bundle使用dist/assets/index-DBO3xErI.js，无后端/表/API/权限/外部行为修改，无生产/共享库/真实供应商/SMTP/部署/commit/push/merge/外发，完整goal保持active。两个新owned MySQL均实际Shutdown complete；本次preview81477 Ctrl-C terminalexit1，后续精确清理/结构/strict/diff/no-fetch记录另补。旧冻结ZIP不覆盖。

收尾实际终态：sourcechecker exit0，10docs/76本地链接锚点/3JSON/64T/20F/18A/132有限sourcehash/110旧AST+4增量AST/4reasonvectors，旧v158/v155ZIP SHA保持；仅结构/source验证。严格约定session58067 terminalexit0，UI table invariant通过、legacy debt743hex/0transition-all/3854lines冻结；standalone diff --check实际exit0仅既有LF/CRLF提示。19:22 no-fetch sweep exit0：main0modified/1既有untracked、自有98modified/108untracked无upstream，仅本地快照。preview81477 terminalexit1（主动Ctrl-C），.NET精确检查3210/4947/13417无监听；pytest fixture两个server实际wait/poll结束，两个mysql.log实际Shutdown complete。四个owned data/temp边界/runtime/非reparse核后native Remove-Item实际exit0，保留日志/runtime/新断言/截图/PDF/build/checker，pytest ACL残留不动。无自动审批拒绝，完整goal未完成/暂停/blocked。

## 客户门户 v1.63 真实客户应用链路与对抗审查（2026-10-06）

本轮补齐当前英文客户构建产物到真实 app.main 路由/生命周期、真实客户 OTP/会话、员工登录 JWT 和独占 MySQL 的定向联调；浏览器不拦截替换商业 API。员工映射发布、完整提案和审核通过实际 HTTP 调用，不能把这些 API 操作称为本轮中文管理页面的 UI 验收。非门户初始化/调度任务、上游库存价格仍为隔离夹具；本地 HTTP 的测试代理及 OTP 取证入口不部署到产品。

客户明确接受后，应用已提交成功回执，再由测试外壳一次替换为503；刷新仅核对原动作 GET 回执，客户接受 POST 两侧均只有一次。随后员工审核和原版本重复审核只产生一个本地 PI、一个 ReceiptIntent 草稿；不同业务员/客户读取拒绝，撤销当前客户权限或停用员工后旧会话/JWT失效。该受控响应故障不是物理断网或进程崩溃。

修改客户别名后，目录显示新别名，历史请求与 PI 保留旧别名。验证比较所有实际 PDF 的完整文本、页数、发布快照及原 Publication/Invoice/InvoiceItem/Conversion/ReceiptIntent 五类模型所有列。真实 ReportLab 实验确认同载荷生成时间会使文件字节变化，所以不以二进制相同替代商业内容不变。

独立审查 RV163-01/P2 指出 Playwright 超时日志可能携带 JWT/Cookie/CSRF。已改为固定安全摘要和受控结构证据，不持久化任意原始子进程输出；敏感输入及原输出限定在执行helper并在失败断言前清理，补合成凭据反例。没有宣称发生真实泄露。当前执行不启用pytest --showlocals；测试fixture仍持有隔离账号资料，本验证不承诺任意调试输出安全。另修测试夹具的精确表单标签、catalog字段和 stdin读取，未削弱商业断言。运行、复核及终态见本节证据索引。

以上仅证明这一有限链路。64项整体验收、全部 writer/旧自动回款 worker、完整历史 schema、真实供应商/邮件/存储、生产 TLS/Nginx 和关标签后的恢复仍 OPEN。自动 ReceiptIntent 执行身份政策仍待业务确认；P0仅生成本地 PI 与草稿，不自动供应商推送、预占或出库。以下历史章节按各自时点阅读。

主线程视觉复核另记录 RV163-02/P2：原回执确认提示中的“Current request status”保留核对时状态，之后刷新已建PI的页面时，仍可能写Awaiting final approval，与当前PI created状态冲突。证据为568的actual-main-confirmed-pi-1440.png。需将提示明确为核对时状态或与当前原单同步更新；本轮尚未修订该文案。后端唯一建票事实已验证，界面状态口径仍OPEN。这是视觉发现，独立runner源码复核未覆盖它。

本轮最终568/exec66128实际exit0：4passed、32既有警告、32.59s；1商务链路、1安全摘要、2合成子进程异常对照，不称4商务场景。原接受POST1、受控ACK故障1、成功回执观测1、会话UPDATE2、商业DML0、实际PDF3。566首跑exit1，1failed/2passed、42warnings/63.91s，浏览器仅精确label夹具超时，原两commerce通过；567中间2pass/31.78s不与最终累加。

证据索引：[运行元数据](D:/commission-system/tmp/portal-v163-final-evidence.json)、[浏览器报告](D:/commission-system/tmp/portal-mysql-run568/browser-evidence/report.json)、[服务端证据](D:/commission-system/tmp/portal-mysql-run568/browser-evidence/server-evidence.json)、[pytest日志](D:/commission-system/tmp/portal-mysql-568.log)。同载荷PDF实际元数据实验保存于D:/commission-system/tmp/portal-application-163-pdf-evidence.json；仅PDF头修订曾被自动审批拒绝且未执行，后以全文/页数/五模型全列守卫安全修订获批准。

独立runner源码及当前文档定向复核确认RV163-01局部闭环，RV163-02视觉状态提示仍OPEN；审查者未运行或认证568/清理。sourcechecker实际exit0：10docs、70本地链接/锚点、3JSON、64T、20F、18A、132有限sourcehash、110旧AST+4增量AST、4理由向量；仅结构与源码校验，旧v158/v155冻结ZIP SHA不变。最终严格约定session87547 terminalexit0（UI invariants pass，legacy debt冻结）；diff --check exit0仅既有LF/CRLF提示。19:07 no-fetch sweep exit0：main0modified/1既有untracked、自有98modified/108untracked无upstream；仅本地缓存，不核远端。

566–568实际Shutdown complete、mysqld无对应进程；六个data/temp路径边界/非reparse核后已删除，保留日志/runtime/PDF/截图，pytest ACL残留不动。无商业产品源码/表/权限新增，无生产/共享DB/真实外部/部署/commit/push/merge/外发。完整goal仍active；自动Intent执行身份政策待用户回答。

## 客户门户 v1.62 原动作回执 GET 与同tab刷新恢复（2026-10-06）

- 本轮完整开发goal继续推进，未整体完成/暂停/blocked；自动Intent执行主体（原创建人/最近同步员工/专用账号）仍待用户回答，未默认选择、未接旧generate_ready。P0本地PI+ReceiptIntent草稿/英文客户中文管理/当前方舟授权/业务员隔离/客户映射和同原修订接受→唯一PI保持。无生产/共享DB/真实供应商/SMTP/COS/部署、commit/push/merge/外发；只自有codex/customer-portal-dev-docs worktree源码与Dtmp测试产物。
- 后台新增action_receipt_queries.py及GET /orders/{request_id}/action-receipt：严格动作/payload_hash与条件revision_id/proposal_hash，余字段/错类型安全422，current客户身份与cancel/accept/reject能力先查，CustomerAccess下原order/同order同kind revision、自然键与payload_hash匹配。auth authority屏障先OrderRequest/Revision/Receipt/PI amendment锁读，单事务当前状态；fresh Session拒原事务/dirty/new/deleted，不触业务动作。允许认证idle续期，不称全DB零DML；商业DML探针与有限商业快照分别验证。same-company另一当前授权联系人沿既有POST回放范围允许查询，foreign404；first_actor未被新增为范围限制，UI只写Original action。PI当前四状态且原回执无status。found=false无receipt、不证明未执行。
- 客户端actionRecovery.mjs新增严格schema=1/current-account/query-only marker，只public IDs/action/exactversion/payloadhash/proposalhash/PI docversion；不存reason、request_no/客户名、地址、PO、价格或凭据。begin同步冻结原正文/锁新动作，WebCrypto hash后核当前scope/再读旧槽，保存并读回原raw后POST。坏槽/读取失败不吞为空；写入/读回失败明确refreshRecovery=false内存模式。restore只unknown/canRetry=false，只GET显式原回执，不重建正文或自动POST。exact command+原receipt字段匹配才确认，foundfalse只可观察当前原单但保持unknown，错command或receipt隐藏内容。仅内存原正文还在时可显式retry原tuple。换身份隐藏迟到数据保留原槽，仅清当前账号完整原raw；App局部捕获错误保留真session/Requests/退出，无存储正文回显。
- 独立审查I139/P2：理由首尾NEL在JS trim与真实Pydantic str_strip_whitespace不同，提交成功后恢复hash不匹配。实际Python ReasonInput.model_dump/content_hash四向量（NEL、混合Unicode空白/非BMP/内部空白、保留1c、中文）先复现25规格24pass/1fail，114.83ms；冻结正文/hash前统一首尾JS whitespace+NEL，内部保持，孤立surrogate在POST前拒绝。独立源码复核包含新端点、当前能力/范围/锁序/PI四态、digest竞态/marker清理与GET-only，定向无新增具体P1/P2，不认证主线程运行或生产。
- 新18恢复规格产品未改实际18failed/0pass109.46ms（portal-decision-162-red.log）；首次全123规格121pass/2fixture时序失败198.11ms，新增异步digest导致旧模拟finish尚未分发，两旧测试只加入等待实际POST信号，不弱化断言。后补跨语言/digest身份变化/已有marker插入/三Storage降级/孤立surrogate，最终130 Node实际exit0/210.98ms（portal-decision-162-node-final.log）；不累计为全T64。实际Vite34模块exit0/574ms（portal-decision-162-build-final.log）。初始沙盒build/preview因esbuild父目录Access denied退出，窄require_escalated后成功，无auto-review拒绝。
- 实际当前bundle Chrome decisionRecovery.browser.mjs最终exit0/2.19s、7场景18合成API调用且1POST：丢已提交响应、reload query-only、foundfalse即便cancelled亦unknown、错payloadhash仍unknown、otheraccount隐藏原槽、原GET匹配才确认、坏槽保留session/Requests/原raw。实际视检320截图，1440/390/320无整页溢出。第一次浏览器因脚本标签Reason for cancellation不符真实Reason for cancelling超时，不是产品失败；修标签及NEL正文夹具后通过。原orders同dist正常exit0/3.16s36calls、wrongrevision exit0/3.36s38calls，保留原11行为，不当22新增业务路径。auth/API/PDF均合成拦截，不是客户端接真实后台/客户/供应商生产联调。
- 真MySQL新增test_mysql_action_receipts.py，选同原decision_recovery/followup_recovery/proposal_binding/company_scope：563/session7921 exit1五fail22.08s，missing endpoint404首先缺no-store断言；563b明确404 vs200再五fail23.17s，不算10新漏洞。564/session25050 exit1，81pass/1fixture非法cap CHECK失败53.31s；can_order仍true时cannot set pricefalse，未将非法fixture称产品缺陷或弱化原拒绝断言。565使用真实admin.update_customer设合法can_order=false、price true/false并实际OTP当前session，old401/new403；最终565/session89253实际82pass/34既有jose warning/53.21s terminal exit0，portal-mysql-565.log。collection-only实际exit0构成49新回执+10decision_recovery+21followup_recovery+1proposal_binding+1company_scope；不累计为全T64。丢ACK后五动作查询原回执、不同摘要无内容、严格组合/余字段/类型422、跨客户/同公司阳性、历史阶段/新写入关闭、命令commit/rollback及授权撤销双方真实锁等待、Pydantic向量/dirtycaller均本批验证；只隔离MySQL8.0.46+真实portal router/HTTP，不是完整main前端联调/历史迁移/全worker。四批mysql.log均实际Shutdown complete，无本轮留存MySQL。
- 文档README/00/03/05/06/07/08、frontendREADME和主API参考同步；旧v1.61内存说明按历史时点，同tab刷新部分明确由v1.62替代。关tab/清存储/Storage不可用、全writer/worker/原自动Intent/真实接口/历史schema/进程/生产/B01–B07仍OPEN，F01–F20/T01–T64/A01–A18未新增、未整体关闭。无新表/迁移。旧v158/v155冻结ZIP字节保持，不创建新冻结包冒充整体交付。
- 收尾portal-v162-source-check actualexit0：10docs/65本地链接锚点/3JSON/64T/20F/18攻击/132有限旧sourcehash/110旧Python AST+本轮3AST/4reasonvectors，冻结v158/v155 SHA保持；只结构/source语法，不是产品执行认证。严格约定实际exit0 tableinvariants pass，legacy743hex/0transition-all/3854lines冻结；diff --check exit0仅既有LF/CRLF提示。18:34no-fetch sweep exit0 main0modified/1既有untracked、自有98modified/108untracked无upstream；本地快照，不核远端。preview1773已Ctrl-C terminalexit1、.NET GetActiveTcpListeners实际exit0证3210无监听。严格约定最终session24342 terminalexit0仍增量无违规；四批owned八个data/temp绝对路径/非reparse/已shutdown核后native Remove-Item实际exit0，复核仅mysql.log/runtime.json，未删pytest ACL残留或其他批；本轮10份一次性writer边界/普通文件核验后安全清理，实际exit0；保留可重跑v162checker。最终文档/source-check和diff再次actualexit0。保留源码/测试、必要日志/runtime元数据/截图/build/checker。

- 上一goal turn v160有真实前端实现/验证进展，本轮继续原完整目标。不接旧自动Intentworker，主体政策仍待用户答案，不把沉默视作批准；其余前端可独立推进。P0仅本地PI+Intent草稿、英文客户/中文管理、方舟当前授权/业务员隔离/客户映射/同修订接受→唯一PI不变；无backend/schema/端点/权限/时间字段或真实外部变化，下一MySQL仍563。
- I138/P2：原send仅request_id及truthy当前状态/version，错误修订/hash/PI绑定版本、非法/舍入version可误成功；原check接受异订单GET为latest。产品改前新增decisionReceipt.test.mjs26规格实际exit1，20failed/6passed/105.28ms（portal-decision-161-red.log）。未声明真实错单/数据串单已经发生。按实际proposal_decisions/order_commands/pi_amendment_service和PI view现有必有字段修前端orderDecision：冻结原hash/PI bound版；取消/普通提案/PI分支、原/当前规范精确整数current>=original；不要求original>submitted If-Match，PI原无status，当前后续状态合法保留。GET仅原对象和规范状态/version，始终非成功回执；send和GET期间scope变化均uncertain=true、迟到私密内容清除。
- 旧Node和orders.browser成功fixture补真实原revision/hash/原row_version/PI invoice_document_version与amendment_state，原断言不删不弱化；不是产品fallback或后端兼容层。修后101 Node实际pass/188.53ms初步。独立建议过期提案拒绝、非法GET版本，另补GET期间scope变化/PI缺绑定先于POST四个对照，仅修后运行，不称旧版RED。最终客户前端105 Node实际exit0/192.64ms，portal-decision-161-node-final.log；Vite33模块实际exit0/569ms，portal-decision-161-build.log。
- 独立交易源码/30定义预审发现两局部P2及合法历史/PI状态边界；修订和4对照定向确认无新增具体P1/P2，未代跑/认证Node/build/Chrome/生产。前端仅现有响应可见字段一致性，未独立证明回执中没返回的actor/动作/原因hash；当前后端授权/自然命令键/完整载荷冲突和原子保存仍真实性来源。当前operation仅内存，刷新/关tab/清存储耐久不据此关闭。
- 同本轮dist实际Chrome/orders.browser：正常实际exit0/3.07s，36合成API请求/原11行为；错revision一次注入实际exit0/2.99s，38合成请求。等待实际回查response.finished才核uncertain/零成功notice/禁止新动作，再原version/hash重试；增强pending1440/390/320截图/溢出后再实际exit0/3.27s/38请求，portal-decision-161-browser-final.log。不累计三个重复运行当33新路径。原proposal三宽亦通过；已实际查看320错回执pending全页截图，未改变动画/样式。
- API/auth/PDF为隔离Chrome拦截的合成数据，不是后端联调、真实客户/供应商或进程崩溃证明；未运行不相关金融MySQL/旧worker。不发布/外发/部署/commit/push/merge、不访问共享DB；旧v158/v155冻结包保持。预览session2685主动Ctrl-C后terminal exit1，3210监听核验收尾；没有本轮MySQL进程。完整writer/worker/真实外部/历史schema/进程/生产/B01–B07及刷新/关tab耐久继续OPEN，整体goal保持active。当前README/00/03/05/06/07/08及客户README同步；结构/hash/strict/diff/sweep最终结果后记。

- 收尾实际portal-v161-source-check exit0：10docs/59本地链接锚点/3JSON/64T/20F/18攻击/132有限后台sourcehash/110PythonAST，v158/v155冻结ZIP SHA保持；不把后台hash检查当本轮前端执行认证。strict/session35021 terminal exit0，table invariants pass/743hex/0transition-all/3854lines既有debt冻结，增量无违规；diff --check实际exit0仅既有LF/CRLF提示。18:10本地no-fetch sweep exit0，main0modified/1既有untracked、自有98modified/108untracked无upstream；未核远端最新。预览2685已terminal，另.NET GetActiveTcpListeners实际exit0确认3210无监听，无重启/遗留预览。删除本轮一次性writer，保留源码/30新规格/浏览器脚本、必要日志截图/构建和v161checker；无auto-review拒绝，未标整体goal完成/暂停/blocked。

## 客户门户 v1.60 原提交恢复记录完整性（2026-10-06）

- 上一goal turn v159为实际实现/验证进展，本轮继续完整开发goal；不连接旧自动Intentworker，原创建人/最近同步人/服务账号政策仍未收到用户答案。不把沉默或默认选项当授权，也不因待答阻断独立前端工作。P0本地PI+ReceiptIntent草稿、英文客户/中文管理、当前方舟授权/业务员隔离/映射/同修订接受→唯一PI保持。
- I137/P2两个实际缺口：savedOperation将损坏/读取失败当不存在；forget盲删同账号槽。新增15初始规格在产品未改前portal-recovery-160-red.log实际exit1，12failed/3passed/112.39ms；无真实重复订单声明。修当前客户submission.mjs、App.vue：固定安全拒绝早于newKey/POST，key-only/同账号/完整原raw清理、写后核验；清理失败保留原槽不盖过已知receipt。App捕获避免authenticated通知冒泡，安全banner保留session/Requests/退出，无存储正文。null storage和确认无旧记录但写失败仍明确内存模式。
- 原write-denied单测夹具补真实getItem返回null（仍保留写入失败及内存恢复原断言）。修后72 Node/192.42ms初步；独立审查补同key不同raw、cleanup读取失败及silentwrite三对照，未冒称旧版RED。最终75 Node实际exit0/200.13ms，portal-recovery-160-node-final.log；Vite33模块实际exit0/691ms，portal-recovery-160-build.log。无后端/schema/权限/时间字段修改，不重跑无关金融MySQL；下一MySQL仍563。
- 独立交易路线只读源码及18新规格，确认原两个P2修订及App局部捕获、同raw/写后核验，定向无新增具体P1/P2；未代跑或认证日志/生产。会话存储仍同tab，不证明跨tab/关闭tab/清存储耐久，也不是服务端授权/锁。新增测试只当前客户端行为；75不累计历史后端/64T。
- 当前dist实际Chrome：submissionRecovery.browser.mjs两场景（损坏/读失败），每场景6合成API请求，零新订单POST、登录保留、Requests实际GET、损坏raw保留、修复原key后只GET回查及清理、无原文回显/页面错误；1440/390/320无整页溢出。初步脚本通过后补原raw断言并将price夹具32.00改正式四位32.0000，增强后实际exit0/2.64s，portal-recovery-160-browser-final.log与report.json；这次增强不计产品失败。已实际查看1440及320初步截图、320最终规范价格截图。
- 同dist原checkout.browser.mjs实际exit0/2.67s，17合成API请求，原9组行为包括samekeyretry/refreshGET/确定拒绝保持可编辑/cross-tablogout及三宽；portal-recovery-160-checkout.log。这里只产品bundle实际Chrome、API/auth拦截合成，非后端联调/真实客户/供应商/生产。预览session98229主动Ctrl-C后终态exit1（中断），3210无监听；无本轮独占MySQL，未停止任何他人服务。
- 真实接口/全writer/完整worker/历史schema/进程/生产/B01–B07及关tab耐久继续OPEN；无commit/push/merge/部署/外发，旧v158/v155冻结包不覆盖。当前源码文档README/00/05/06/07/08与frontendREADME同步；结构/sourcehash/strict/diff/no-fetch实际收尾结果后续记录，不称已全验收。

- 最终portal-v160-source-check实际exit0：10文档/56本地链接锚点/3JSON/64T/20F/18攻击/132有限sourcehash/110PythonAST，冻结v158/v155 ZIP SHA未变；不把后端132hash当本轮前端执行覆盖。strict/session58662终态exit0，table invariants pass/legacy debt743hex/0transition-all/3854lines冻结，增量无违规；最终diff --check实际exit0仅既有LF/CRLF提示。17:52本地no-fetch巡检实际exit0，main0modified/1既有untracked，自有98modified/108untracked无upstream，不核远端最新或授权push。一次性本轮writer完成后删除；代码、18规格/浏览器脚本、日志/report/必要截图、构建及版本化checker保留。完整goal仍active，下一工作需依实际新证据选择，不重复本轮已通过测试。

## 客户门户 v1.59 显式主体回款生成内核（2026-10-06）

本轮继续完整开发目标。新增generation_service.generate(db, invoice_id, actor)显式主体内核：当前receipt:write/实际Invoice财务范围，永久屏障和原PI谱系；冻结Intent、Invoice/行、Allocation、参与回款/日志/批次/附件的全列有限关联，释放业务锁后取余额、费用及文件证据；两份远端ID/金额核一致，最终当前授权/同一原绑定、排除本Intent占用后保留其他回款与原手续费算法，回款/Intent/凭证/日志同事务。converted只当前授权后核原关联回放，不重取证或建第二单，不新增ready条件遮住合法历史。

只改新内核及_make_row纯本地构造；旧new_row保留原费用计算，旧generate_ready与scheduler没有接入新内核。执行主体政策（原创建人/最近同步员工/服务账号）已向用户询问，答案尚未收到；不能为跑绿默认取created_by。I81自动Intent/全writer门禁继续OPEN，旧worker反例仍未关闭。P0仍仅本地PI+ReceiptIntent草稿，不自动转换/外发/预占/出库；无新API/表/权限/前端/生产操作。

独立金融审查发现新内核未最终重验预售首付款净额的P1，已在实际fee计算后、建行前补净额>0且<=当前product_amount；部分首款、商品净额上限合法阳性和stock末笔余费分别验证。运行、夹具错误和局部证据限制只按docs/handoff.md终态，不将旧worker六RED或旧历史数量改称本内核GREEN。

562/session45459 actualexit0 118passed/196warnings/206.98s：54显式内核+64原手工创建同批；旧worker六RED未被选入或替换，不称全面通过。123金融SQLite为另批actualpass/26warnings/20.17s，不累计为全T64。独立源码复核确认预售guard修订及当前差异无新增具体P1/P2，未代跑或认证562/生产；新增Receipt/Log只核主要字段，有限15既有行逐列白名单不称新增行全字段或全DB验证。

557/session86119 actualexit1 1failed+5errors/35.05s；558/session25067 actualexit1 6failed/22warnings/34.03s；559/session64084 actualexit1 1failed45passed/26warnings/91.10s；560/session42125 actualexit1 2failed52deselected/18warnings/28.95s；561/session44783 actualexit1 2failed52deselected/18warnings/28.94s。主体问题仍pending，本轮first blocker不等于goal blocked，无auto-review拒绝。

金融/session88553 actualexit0 123passed26warnings20.17s。562/session45459 actualexit0 118passed/196warnings/206.98s（54core+64原manualcreate），日志portal-authority-562.log；旧worker六例未入GREEN范围。所有runtime/日志是独占loopback MySQL8.0.46、薄上游列与显式request_key/auto_key唯一键、真实当前角色/生成算法；main/ASGI只用于fixture/管理员改权限，core本身不是JWT端点。provider/file伪服务/实际本地文件、有限15、事件ACK非完整schema/供应商/崩溃。当前scope末笔commit事件只覆盖final caller commit，不覆盖capture/token提交。

- 最终独立交易源码复核确认预售actualcharge后净额守卫、合法上限与拒绝反例，未见新增具体P1/P2；新增Receipt/Log仅主要字段，既有15模型逐列白名单不代表新行所有字段。独立文档路线发现D13旧worker时点，已修明确v158静态/v159实际558六RED及旧后台未接线，其他本轮增量一致。两路未运行/认证日志/生产、未全量历史重审。


- 收尾独立文档定向复核确认D13闭环：00/08明确v1.58静态发现、v1.59的558六个实际失败，旧后台未修复/未接线且不被新内核118通过覆盖；当前段落与07/handoff一致，无新增具体P1/P2。仅文本核验，未代跑或认证日志/生产。
- 本轮有限source check实际10docs/53本地链接锚点/3JSON/64T/20F/18攻击路径/132source hashes/110PythonAST通过。strict/session60885实际exit0，UI table invariants pass/legacy debt frozen；diff --check实际exit0，仅既有LF/CRLF提示。no-fetch sweep实际exit0，main0modified/1既有untracked，自有98modified/108untracked无upstream；仅本地快照，不核远端最新。文档收尾后再核source/diff，不重复无新增产品变更的118/123测试。
- 557–562独占MySQL8.0.46均核精确datadir、Shutdown complete和提权CIM无对应MySQL/Python进程。精确清理实际exit0，移除21路径（12数据/temp目录和9一次性writer），6pytest根目录因UnauthorizedAccessException保留，不修改ACL；非auto-review拒绝，不称全部临时产物已清。portal-generation-159-cleanup.json保留逐路径证据；日志、runtime元数据、核心RED重建脚本和可复用runner/checker保留。无生产/共享库/真实供应商/发信/部署/commit/push/merge，完整goal仍active，执行主体政策仍待用户答案。

- 文档收尾后实际复核source10/53/3/64/20/18/132/110通过，git diff --check实际exit0（仅既有换行提示）。v1.58冻结ZIP仍7387032字节、SHA256=40a1bd99e505d99ade41440f76b4dbf9f6fa00638dd53d2e5eaae977b4e6b3f6；其独立verify_delivery.py实际exit0，42冻结文件/10文档/53链接/3JSON/64T/20F/18路径通过。只核冻结字节与结构，不把包装检查称业务验收，也未覆盖旧包。

## 客户门户 v1.58 详细开发文档与独立对抗审查（2026-10-06）

- 按当前用户请求只交付详细开发文档与审查；未继续generate_ready实现、未运行新的MySQL/浏览器/真实服务/生产操作。已确认业务方案及P0、R/W/T/F编号保持；已有完整开发goal仍active，文档交付不等于实现完成。
- 只读源码确认I81现有风险的generate_ready子路径：Invoice/Intent锁内new_row(auto)调用fees.allocate远端取证和attachments.bind物理文件；created_by不重建当前动作/实际Invoice财务范围，失败另写last_error。P1静态风险未运行复现/未修复，不重复增加F/I。00/06/08明确执行身份政策待决、锁外完整证据和最终重验/原子转换/错误状态授权、正反/并发/ACK/队列验收；此路径及全writer继续OPEN。
- 本轮独立文档与交易审查的最终结果、结构/引用/hash/约定/巡检和新冻结交付终态在本节后续记录；旧v1.57/1.56日志和旧v1.55冻结包保持，不说本轮67/68/30重新通过。未改产品、schema、权限、时间字段或前端，不运行无关测试。

- 最终独立交易路线核核心交易及新增文字，无新增具体交易P1/P2，I81静态子项仍OPEN；独立文档路线发现D12/P2（08门禁格将历史浏览器称本轮），已修明确v1.56/本轮未重跑/真实双端与关tab仍OPEN，定向复核确认闭环无新增具体P1/P2。两路不认证业务日志/生产，未逐行重审全部历史附录。
- 本轮source check实际10docs/53本地链接锚点/3JSON/64T/20F/18攻击路径/131source hashes/109PythonAST通过，旧v155 ZIP SHA保持；strict增量检查实际exit0，table invariants pass/legacy debt frozen；diff --check实际exit0，仅既有LF/CRLF提示。no-fetch sweep实际exit0，main0modified/1既有untracked、自有98modified/107untracked无upstream；本地快照，不核远端最新或授权远端动作。
- v1.58冻结交付目录与ZIP独立于旧v155，包内含10篇专题/总纲/当前审查、writer清单、冻结handoff、原型25文件和可复核manifest/verify脚本；实际包字节/结构终态以包内verification.json及外层delivery-v158-result.json为准。源包仅当前文档/历史证据与视觉原型，不含.env/密钥/业务数据库/产品源码，不冒充当前UI复测或源码发布。

## 客户门户 v1.57 后台出库诊断、原事实与后项处理（2026-10-06）

- 上一goal turn v156为progress（实际UI修订/证据与当前文档落地），本轮继续full implementation goal，保持active；自有codex/customer-portal-dev-docs / baseline54f77438328e5aa5d3c776ee309914447672d767。英文客户/中文管理、当前完整提案客户接受→有权员工唯一PI、销售隔离/SKU映射、R01–R06/W01–W07/T64/F20、P0本地PI+ReceiptIntent草稿不自动推送/预占/出库保持。
- I136/P2六实际反例：后台原POST接受后transport ReadTimeout，经实际POST parser分类unknown却被logger/stdout抛错盖过facts.observe；实际回读失败被盖过unknown READ/CHECK；真实20小ID阻断项的首个错误诊断让tick终止，后合法项不执行。555/session49773 actualexit1 6failed/29.45s，portal-authority-555.log；产品未改先跑，不虚构全面旧持久快照/已发生重复出库。旧模块源码备份portal-worker-157-before.py及测试/日志保留。
- 修outbound_worker唯一产品文件的六诊断点。diagnose分别尝试logger/stdout且只catch普通Exception，在Session.info留固定phase/sink/异常类名，无供应商正文/凭证/SQL或异常文本；SystemExit等BaseException传播。不包供应商/数据库/金融，原current actor/Invoice范围、原冻结载荷/lease/START/SEND/FACT/READ/CHECK/FINISH、unknown/409/503与发送规则保持，没有增加重发。无新表/权限/时间字段/前端/生产/共享库/真实provider/SMTP/COS或commit/push/merge/部署。
- 新test_mysql_outbound_worker_diagnostics13：原6实际counterexamples；2原FACT commit错误/503及原单次发送恢复场景；2actualbuilder坏handler409、零START/POST/原snapshot不变；1pure unit双sink独立失败安全info；2pure unit SystemExit传播。复用原真实分页/commit断言，未stub process。后7为修订后补充，不冒充7次旧版RED。纯诊断测试不证完整worker硬中断清理。
- 556/session56876 actualexit0 67passed/94.10s（原worker54+诊断13），portal-authority-556.log。直接actual worker/process/run_once、当前方舟角色/实际Invoice谱系、真实产品builder/HTTP POST parser/实际关联扫描/隔离独占MySQL8.0.46；不是worker员工JWT/ASGI API。HTTP/remote/serial替身、薄上游表FK/UQ限制、原有限商业snapshot、事件ACK非物理崩溃保留。原前端156/金融155不重跑或累计为全T64。
- 独立交易路线只读修订前后worker及新规格，提出双sink/硬中断和原409/503对照已补；当前六调用覆盖、普通诊断与业务分离、原状态/权限/发送不变，未见新增具体P1/P2或明显假绿。仅源码审查，不代跑/认证555/556/生产。相关README/00/06/07/08/MySQLREADME与有限inventory同步1.57；01–05及前端仍是各自最近契约，不机械换版本，旧冻结包保持原字节。
- OPEN：完整worker/自动Intent/rawSQL/allwriter、未持久在途FACT/真正崩溃/逐迟到合法恢复、完整schema历史迁移/真实旧制品deps/config回退、进程排空/单活、真实供应商/SMTP/COS/B01–B07、真实双客户双业务员隔离、关tab/清存储耐久及私有残留。局部67及审查不关闭整体goal、T01–T64或生产门禁。下一MySQL557，仅有新增变更/失败或未解疑点需要时运行。strict/diff/no-fetch/hashAST及准确停机/清理终态收尾另补。

- 独立文档路线定向读本版新增段落，D11/P2指出00:152“本轮补proof/Chrome30”把156既有结果误纳本版。改明确v1.56当时结果/v1.57未重跑，08历史proof/UI行亦标具体版本；不计运行漏洞或增加F20。其余directworker≠ASGI、六旧RED/七修后对照、纯diagnostic硬中断≠全worker清理及OPEN一致。两路均不认证运行/字节/生产。
- strict/session73651 actualexit0 增量无违规，UI table invariants pass/legacy debt frozen；diff --check actualexit0，仅既有LF/CRLF提示。有限source checker actual10docs/46本地链接锚点/3JSON/64T/20F/18攻击/131source hashes/109PythonAST，冻结v155ZIP SHA保持；D11最终文档修订后再核结构。16:39北京时间no-fetch sweep actualexit0：main0modified/1既有untracked，自有98modified/107untracked、无upstream，仅本地缓存，不核远端当前，不推送/合并/删分支。
- 两个owned555/556 runtime8.0.46/scope/精确datadir及mysql.log最后Shutdown complete逐一核对；提权只读CIM matching mysqld/python为0，两个测试session终态，未启动新服务。portal-v157-cleanup.json actualpartial：5精确路径removed（2data+3一次性writer），2tmp原不存在，2pytest根555/556因ACL Access denied保留；无ACL改变，非自动审批拒绝。日志/runtime/旧worker源码备份/可复用source checker/源测试/历史包保留。final一次性文档writer随后删除，不伪称所有临时目录均清。整体goal active，局部工作完成但上述OPEN仍未闭环。

## 客户门户 v1.56 未知原确认恢复、proof和版本围栏（2026-10-06）

- 继续已授权完整实施goal（active），自有codex/customer-portal-dev-docs / baseline54f77438328e5aa5d3c776ee309914447672d767。英文客户/中文管理、完整当前提案客户接受→有权员工唯一PI、SKU映射/业务员隔离、P0本地PI+ReceiptIntent草稿且不自动推送/预占/出库保持。未新增后端产品/表/权限，本轮修改管理端原确认恢复和相应测试/文档；无生产/shared库、真实provider/SMTP/COS、commit/push/merge/部署。
- I134/P2实际Chrome RED：portal-confirmation-browser-156-red/results.json中none/旧resolved两种，POST503+普通GET后确认按钮1而期望0，actualexit1；原RED test-source保留。shipmentConfirmation.js及实际对话框在POST前可靠保存actor/完整原目标/version/reason，未知不被GET解冻；只显式同原目标+安全状态一致+高于原命令及本次提交版本可清槽。关闭重开/刷新/props换单仍授权读取原对象，scope拒绝隐藏保槽、actor/卸载代次拦迟到。错confirm/reconcile/detail/Invoice身份为静态审查修订，未虚构旧版RED。
- I135/P2实际Chrome RED：conflict-red2.log actualexit1 false!=true（未调用新create草稿遮住原确认且关闭禁用）。提前检查原确认槽；只清本组件明确未保存/未调用create的草稿，不丢真实未知提交。conflict-green实际exit0；final3同场景passed、可核原单/可靠关闭，未新增财务create。初expanded/browser3342错误为夹具locale按钮“确定”实际“OK”，不计产品RED；随后准确定位I135。
- backend/tests/portal_mysql/test_mysql_confirmation_recovery.py由26增35：5proof/ORM和4受控HTTP版本围栏。proof独立namespace全部AuditEvent列snapshot；准确actor/basis/目标、commit前后、重复去重、普通GET零DML、锁外追加/改元数据及ORM改名/删除。快照不独立重算所有业务hash语义，不等于全部AuditEvent/全DB/Core/rawSQL。围栏none/旧resolved各capture前/claim前门控threading.Event，核对先commit新版本，再放旧confirm→409，有限21商业图/journal/proof不变、无新增START/POST；非sleep猜竞争，不外推START后/在途未持久FACT。
- MySQL553/session95452 actualexit1 2failed/62passed/389warnings/169.97s：两个共享老状态断言滞后永久proof保护，actualconfirm_uncertain vs expecteduncertain；改准确期待并加强第二次核对仍blocks_confirmation/shipped_regression/noPOST，不弱化。554/session94409 actualexit0 68passed/419warnings/178.07s=35恢复+33共享边界，portal-authority-554.log。actual main/ASGI/JWT/current admin/真实金融/候选，独占8.0.46；薄上游无FK映射/provider/token替身、finite21、事件ACK非完整schema/供应商/物理崩溃。后端产品本轮未变，47金融SQLite为155历史，未重跑或累计。
- Node portal-confirmation-node-156.log实际15passed/0failed/107.1985ms（shipmentConfirmation、shipmentSubmission、shipmentSettlementState三个文件）。build/session60570 actualexit0 15.79s，portal-v156-build.log，既有>500k chunk警告不做无关重构。
- actualChrome final2/session78555 exit0 30记录；独立审查指出late_actor只等60ms假绿窗口。修测试等受控fulfill、response.finished、原XHR loadend之后JS/render marker；final3/session91165 actualexit0 30passed（6完整流程+18摘要状态+5存储/回执/迟到+1槽冲突），portal-confirmation-browser-156-final3.log与results.json/截图。当前1440/390/320无rootoverflow/pageerror/unexpectedAPI；API/auth合成不证明后端scope。旧固定等待那一条不单独当迟到证据；修订不是已确认产品绕过。
- 共享shipmentSubmissionRecovery.browser实际三宽exit0，portal-shipment-browser-156-regression.log/results.json：原body/key/Invoice、unknown/restore/not_found/routeleave/actor/late以及存储零POST保持。shipmentFundingRisk.browser实际三宽exit0，portal-funding-risk-browser-156-regression.log/results.json：null待核对/恢复正常金额、不显示确认或写金融。截图320unknown-none实际检查控件可用，无完整无障碍/设计验收承诺。产品UI未动效重设；tab记录不承诺关闭tab/清存储/崩溃耐久。
- 独立交易路线只读定向审原confirm/UI/proof与围栏定义，提出I135并已实际复现修订；错目标保护及迟到测试证据补强后，定向源码复核无新增具体P1/P2。审查者未运行或认证554/Chrome日志/生产。当前10源文档、API/MySQLREADME及inventory已同步1.56；v155及早期冻结包保持字节，不以静态校验替代业务门禁。最终文档独立复核、strict/diff/no-fetch/sourcehashAST及准确停机/清理另补终态。
- OPEN：完整worker/自动Intent/rawSQL/allwriter、原未持久在途FACT/真正崩溃/逐迟到合法恢复、私有上传残留、完整schema历史迁移和真实旧bytes/deps/config回退、进程排空/单活、真实supplier/SMTP/COS/B01–B07、两个真实客户/业务员交叉隔离和关tab/清存储耐久。局部68/15/30或审查不关闭T01–T64/global goal，也不授权生产。下一MySQL555，仅新变更/失败有必要时才运行。

- 最终独立文档路线阅读00/08全文、八篇当前顶部、API/MySQLREADME与本handoff：无新增具体P1/P2/过度闭环，未认证运行/字节/生产。交易路线定向确认新测试先等原200响应读取、fulfill、XHR loadend→setTimeout→两RAF，随后才断言槽/弹窗、切回原actor、关闭context，原证据窗口消除；只源码结论。
- 最终source checker实际10docs/44本地链接锚点/3JSON/64T/20F/18攻击路径/130source hashes/108PythonAST通过；v155ZIP SHA50205bbba0f035d769fe42b73f30b1472e985da7e55667c311d34cd9ea7a4a80保持。strict/session26958 actualexit0“增量改动无违规”，UI invariant pass/legacy debt frozen；diff --check actualexit0，仅既有LF/CRLF提示。16:22北京时间no-fetch sweep actualexit0：main0modified/1既有untracked，自有98modified/107untracked、无upstream，仅本地缓存，不核远端最新、不授权推送/合并/删分支。
- 自有Vite/session40529 CtrlC主动终态exit1；提权只读CIM准确匹配52356/owned553/554无进程。两个runtime8.0.46/scope/精确datadir及mysql.log最后Shutdown complete逐一核对；portal-v156-cleanup.json actualpartial：15精确路径removed（2data+13一次性writer）、2tmp原不存在、2pytest根553/554因原ACL Access denied保留。无ACL改变，非auto-review拒绝；保留日志/runtime/RED源码/final3截图和结果/可复用source checker/历史包。不是全部临时目录已清。源报告当前可编辑，未生成/覆盖v155冻结交付；局部工作完毕，overall goal保持active和上述OPEN。

## 客户门户 v1.55 详细开发文档与对抗性审查（2026-10-06）

- 当前用户请求为“按以上方案生成详细开发文档并进行对抗性审查”；本轮仅整理总纲、同步八篇当前契约和审查/交付，不追加产品实现或业务运行。英文客户/中文管理、完整提案客户接受→当前员工唯一PI、SKU映射与业务员隔离、P0本地PI草稿不外发保持。自有codex/customer-portal-dev-docs，无commit/push/merge/部署或共享库写。
- 已存在当前分支原恢复/GET安全摘要/UI源码：protocol2原时间及载荷/基线重构，FINISH分类追加，原确认journal+独立永久proof最终全绑定，永久was_shipped守卫先于no-pending；普通GET安全八字段零创建，未知UI冻结/回读。旧sent不足不补猜。此记录同步已发生工作，不称本轮新增运行。
- 读取已有549 actual3fail/36warnings/33.35s（I132）；550 actual3pass/36warnings/33.33s；551 actual2fail/3deselected/33warnings/31.37s（I133）；552 actual77pass/464warnings/202.98s=26恢复+51确认。47金融SQLite日志155为47pass/7.80s，frontend build155为21.28s成功及既有chunk警告；分别记录，不相加为全64通过。供应商/token/薄schema/事件ACK限制保留。
- 独立源码复核确认I133两次status1及late FACT永久保护局部修订；新增proof也参与绑定，普通GET不创建。E155-01：journal辅助未含proof，故原journal不变不是全部AuditEvent不变，proof全字段原子/去重断言仍OPEN。FINISH语义及ID类别是静态修订，不伪造旧版RED。新UIhelper/build已有，新真实浏览器与受影响共享核对完整回归未补，不称端到端通过。
- 新00详细总纲含参考源码对照、身份/角色、商品/映射、完整交易/唯一PI、接口/数据职责、双端设计、W01–W07、B01–B07、验收及发布；08当前18攻击矩阵逐项区分契约/局部证据/开放项。独立文档定向复核、最终静态检查/制品回执收尾另补。
- 整体实施继续OPEN：full worker/自动Intent/绑定、raw SQL/所有writer、未持久在途事实/逐迟到合法恢复、私有上传残留、完整schema历史迁移、真实旧制品/deps/config回退、进程单活/排空、真实供应商/SMTP/存储、B01–B07及关tab/清存储耐久恢复。文档交付不关闭以上门禁；旧v1.54冻结包保留原字节。本轮不做新临时DB或服务，因此不宣称已清理先前ACL拒删残留。

- 收尾两路独立只读全文00/08及源核心定向复核：D10/P2重复SKU歧义已修为前台合并/后端重复item_id或标准SKU直接422，A05补T53；交易路线补确定未提交才整体回滚、未知原命令核对。复核八篇v1.55新顶部无其他新增具体P1/P2；07旧最新导航已指08/v1.55。审查者不认证日志/制品/生产，未逐行重审全部历史附录。
- strict/session80510 actual exit0 增量无违规；git diff --check exit0，既有LF/CRLF提示保留。15:41 no-fetch sweep actual exit0：主main0modified/1既有untracked，自有98modified/105untracked、无upstream，仅本地缓存快照，不核远端当前状态。文档制品最终SHA与结构验证独立回执见visualizations/portal-development-docs/delivery-v155-package-verification.json；制品完整性不作应用/生产验收。

## 客户门户 v1.54 实际确认出库的当前授权与原事实协议（2026-10-06）

- 自有 codex/customer-portal-dev-docs / baseline54f7743；confirm-outbound迁移当前shipment:write/实际Invoice财务范围、永久屏障/原资金谱系/full binding/当前员工映射与仓库，保原require_delivery/ensure_active/presale/主运费0，不新增ready/invoice或receipt write。JWT只身份。新增service/facts复用AuditEvent，无新表/迁移/UI，不改P0/R01–06/W01–07/T64/F20。客户不自行实际出库。
- 短事务current capture→锁外实际原出库/资金/主单/相关候选→current原图验证；真实金融64=44goods含4fee+20freight、有效回款/App/余额及纯candidate算法。START原事件/claim/资金回读commit成功后再取token；每轮current own/持锁freeze/SEND commit成功后才POST原ID/status2/line501/cost12.5。只明确鉴权拒绝可第二轮，再token/current own/SEND；unknown不重发。每个POST仅原FACT可独立保存失权/转交/资金/lease/token变化后效果，当前商业收尾继续拒绝；最终锁外GET再current own，原状态/风险/资金/FINISH同callercommit。
- 544/session28542 actualexit1：4failed/43warnings/39.13s，原旧JWT停用/角色/动作三200及新grant旧empty403是I81/P1再现。此baseline临时stub原资金helper只定位权限，不能认证原金融候选。545/session62190 actualexit1：4failed/34warnings/35.29s全部prepare DDL MySQL3780，薄ArkUser BigInteger与实际binding Integer FK不同；改隔离无FK薄映射表，不改产品FK，不计产品RED。
- 546/session9034 actualexit1：2failed/3passed/28deselected/45warnings/38.12s，I131/P2 logger RuntimeError/stdout BrokenPipe在首次原FACT commit OperationalError后覆盖有限重试；修独立普通Exception诊断，仅db.info受控phase/sink/类名，无私密内容，BaseException传播。另RV154-01原action持久身份防御、RV154-02三阶段OverflowError窄503为静态审查修订，546两expired update已通过，没运行旧TTL RED，不伪造运行复现。POST异常亦安全诊断、不把坏ID parse误类显式rejected。
- 547/session39436 actualexit1：2failed/36passed/223warnings/110.30s；两删除确由原portal.immutability.guard_delete拒绝，测试预期immutable而真实must be retained不符；修准确两类消息断言，保持精确journal零变更，不计删除产品RED。实际坏TTL三phase已通过，此试点采用真实ensure_access_token/fetch_token、只HTTP/内存cache替身，不声称真实持久凭证。
- 548/session3057 actualexit0：51passed/297warnings/138.54s。4当前auth、1完整success/exact payload/no duplicate、8取证竞争、3token竞争、5实际POST late变化、8结果分类、2诊断留证、4ORM改名/删除、3真实helperTTL、6准确同Session commit3/5/8 before/after ACK、2第二token撤权/资金、2actualfinancialscope、3无ready历史。Independent Invoice NOWAIT证实selected GET/token/POST锁外；51定义非全部现网契约/physical stock reservation/全writer，ACK事件非进程故障。
- 失败比较独立已提交finite21商业图，原journal按namespace另读。late成功仅FACT允许而商业图不改；authrejected第二token阻断保原3事件、一POST。before START商业图不变；after START/SEND noPOST保准确checkpoint并旧body409；before final保FACT不伪FINISH，after finalGET真实shipped持久不改。成功目前exact payload/state/journal/duplicate守卫，尚无全成功金融逐列白名单/完整原事实恢复证明。
- 原47金融SQLite/session12610 actualexit0：47passed/7.11s（portal-presale-unit-154.log，复用152runner，仅SQLite Engine/禁PyMySQL和HTTP/无.env/-p no:cacheprovider）。两个legacy confirm单测继续旧helper，不冒充新权限协议认证。本批无UI变更，不重跑无关build/Chrome；前批冻结UI保原字节。
- 独立金融路线只读发现3具体P2，定向修订确认无新增；追加13定义复核commit3/5/8、force token组合、financialscope和no-ready没有明显假绿，不代跑认证548。独立文档路线十处顶部/导航指出D09/P2缺FINISH未知谓词歧义，已明确“每START若无匹配resolvedFINISH（缺失也算）均阻断”；两旧v153导航同步。D09不是源码/运行缺陷，不改历史F20。
- 最终124source hashes/103PythonAST通过；源8docs/31本地链接与锚点/3JSON/64T/F20通过。strict/session31516 actualexit0“增量无违规”，git diff --check actualexit0（既有LF/CRLF提示）。14:59北京时间git_sweep --no-fetch actualexit0：main0修改1既有untracked，自有97修改103untracked且无upstream；仅本地缓存，未核远端最新，不自动推送/合并/删除分支。
- 独立文档定向确认D09修订，全文读新00/08及本节，无新增具体P1/P2或过度闭环；不认证主线程日志/清理/字节。五个owned544–548 runtime8.0.46/scope/精确datadir/Shutdown和提权CIM无对应进程均核对。第一次清理在547pytest根目录Access denied停止；继续不改ACL，另实际移除10精确路径、12已不在（含第一轮已删及原不存在），保留547/548两个pytest根目录并记录portal-v154-cleanup.json status=partial。数据/temp与一次性writer均已清，本轮无后台进程；日志/运行时/源码/可复用工具/历史制品保留，不伪称全部临时目录已清。
- 新v154十篇（00导读/8源快照/08审查）、冻结handoff/源码清单、原型原字节副本的包装与SHA结果单列视觉交付verification/package-verification；旧v153/152/149冻结包不覆盖，不把包装哈希当业务门禁。
- overall goal active，OPEN：原新事实的核对FINISH/未发送或明确拒绝受控恢复/GET风险摘要、旧helper淘汰、全成功金融白名单、持久原谱系全部变化；全freight/outbound worker/自动Intent/rawSQL未登记writer/initiallyOFF、真实旧bytes/deps/config/生产systemd/cgroup/Node/PID单活、历史完整schema迁移、真实supplier/SMTP/COS/B01–B07、关闭tab/清存储耐久恢复。无生产/shared库、真实外部发信或推送、commit/push/merge/部署；下一MySQL549。

## 客户门户 v1.53 出库原单核对、资金风险与对抗修订（2026-10-06）

- 在自有 codex/customer-portal-dev-docs 继续原完整实施goal。新 outbound_reconciliation_service/funding 接入实际 reconcile-outbound，JWT仅身份→永久authority ON/OFF→当前shipment:write/按需shipment:admin→原实际Invoice财务scope→完整当前资金图。release捕获锁后不可变GET详情/活动/回款/主单/运费/完整回款列表；结束token/cache事务，最终授权和full binding优先于业务结果。原Invoice/item/Settlement/App/Receipt/Batch/Intent/Allocation/targets/outbound/logs/events/attachments有限21图，不是所有writer/全DB。
- 无新ready限制，原presale/主运费0保留。原ID/编号/载荷/金额/费用保持，无供应商POST。手工绑定与原核对合为最终一次商业commit，Outbound/Settlement版本各+2，known各+1；原回款accepted readback/log、足额reserved App应用与准确actor/reason事件同提交。status2缺原基线保uncertain；资金有效shipped，否则shipped_unfunded；远端倒回待出库保禁止再次确认。live confirming lease拒绝零取证。无stable key，原body.version失效先GET，不把重复观察当唯一回执。
- 536/session49892 exit1：8failed/68warnings/42.97s，旧JWT撤停用/角色/动作六200、新grant旧empty两403，I81/P1在两模式入口实际反例。537/session1981 exit0：8passed/68warnings/43.14s初步。538/session89628 exit1：16failed/66passed/410warnings/196.15s；16均full funding准备误用32付款helper的22/fee2+10断言，真实64付款44/fee4+20，修真实夹具，不计产品RED。单独539/session76405 exit1：13failed/83warnings/54.26s达到实际业务反例。
- I128/P2（539的12）：empty/blank outbound currency两模式错误409/200；Receipt detail缺/null bank_charge或real_amount两模式错误接受200。修严格技术503/零金融变更，与合法完整mismatch区分；原任意sale_price精度和首次status2无基线分支保留。I129/P2（539的1）：原参与Receipt voided且原status2已核实时describe计算报409使风险回滚；窄shipped_unfunded失效返回balance=null/固定balance_error，GET同表示，无fake0。保留其他activeReceipt原合法回读。UI两个余额待核对、固定风险，不露实际确认入口。
- 540/session85357 exit1：9failed/86passed/511warnings/232.44s；首金融delta用ReceiptLog.actor_id错误，实际字段created_by；后续case复用remoteReceipt ID80001/80002撞之前已接受原单。修夹具准确created_by=None及按实际Receipt/target唯一remote IDs，不计产品缺陷。541/session85958 exit1：2failed/22passed/74deselected/139warnings/76.45s；I130/P2真实logger RuntimeError与stdout BrokenPipe令可靠unfunded风险保存500回滚。修两个普通Exception独立保护，BaseException仍传播；保固定风险/审计，后续增强db.info安全sink/exception类名请求内证据，不含私密正文，不宣称持久诊断。
- 542/session77111 terminal exit0：98passed/527warnings/236.80s=82初始+16审查。之后db.info证据增强、删仅无生产caller的旧 shipment_delivery.bind_exact、原金融unit迁到新纯_read/_apply；原inactive拒绝/remote_id None及active pending_remote不减，增加target/Settlement各+2和金额/费用不变。原worker refresh/confirm保留未认证。543/session83823 terminal exit0：103passed/504warnings/238.29s=33新边界+16审查复验+54原retry。未重跑未受影响82全部，不宣称131在清理后同一轮全绿或相加历史数为全验收。
- 新33：4精确同Session第三commit before/after ACK（含真实资金回读及应用，before全21不变，after完整金融白名单+GET持久一致/旧body409）；2脏caller拒绝保dirty；4invoice_all/receipt_all实际财务scope；6非ready历史；2原单价12.3456；8实际outbound_presence is_active/_scan/_page只替HTTP transport的presence/absence/bad list/count；4已出库/确认状态倒回pending；2首次status2无lineID/costbaseline保uncertain；1live确认lease零IO。独立Invoice NOWAIT和8资金阶段gate撤权/资金变化已在82。没有新增真实InnoDB wait探针或全supplier multipage字段合同证明。
- full21白名单只原target/Settlement版本状态时间、接受Receipt回读/日志、足额App和一条准确事件；原金额/手续费/attempt/lease/载荷/历史记录保持。inactive GET只核21持久快照一致，不宣称SQL DML事件探针零命中；诊断两失败核exactmarker及db.info安全结构。金融阳性用actual创建64付款/真实Receipt匹配/余额算法，provider/token/GET synthetic；部分历史目标直接SQL构造，不证明上游所有合法恢复。
- 原金融47 SQLite/session94564 terminal exit0：47passed/7.51s，runner仅SQLite Engine/禁PyMySQL/HTTP/无.env/-p no:cacheprovider；复用runner目录名152，只将本次真实log153作证，不混作历史运行。前端build/session11798 actualexit0/16.92s，既有auth混合导入/500k chunk警告不扩大修改。真实Chrome风险三宽1440/390/320/session日志153 exit0，恢复有效26.00/0.00与风险null待核对均断言；shared原提交恢复同三宽exit0，Node7pass/83.55ms，均synthetic API/auth，非服务端鉴权/完整无障碍/关闭tab耐久证明。两个Chrome任务终态，自有Vite52531 CtrlC终态exit1主动停止。
- 独立金融源码审发现I128/I129/I130并定向确认当前修订及helper/unit映射无弱化，无新增具体资金/隔离/回滚P1/P2；提出RR stale静态疑点后明确撤回：最终新事务/fullfingerprint挡正常金融变化，无实际RED不登记发现；纯图/current余额改进不冒充bug复现。独立文档审8篇顶部/API/MySQLREADME确认权限、版本、null余额、定义131≠终态与OPEN一致，无新增具体P1/P2。审查者未代跑/认证实际结果或生产。
- 8源契约/README/API/MySQLREADME、121source hashes/100PythonAST已同步实测；静态8docs31links/3JSON/64T/F20通过；strict/session39854 actualexit0增量无违规。新v153独立导读/审查/快照与包装将单列最终回执，旧v152/v149原hash不覆盖。owned536–543准确停机/清理及no-fetch/diff收尾将在完成后补记。日志/runtimes/源码/可复用工具/PNG保留。
- 整体goal active，无生产/shared库、真实供应商/SMTP/COS、commit/push/merge/部署。OPEN：实际出库confirm、完整freight/outbound worker/自动Intent/其他rawSQL未登记writer、initiallyOFF旧路径、未持久在途provider结果/私有残留；I77生产启动、I92/I79/C05真实旧bytes/deps/config/allwriters及合法恢复、I78systemd/cgroup/Node、I80现场all-success/PID单活、126历史迁移、真实服务/B01–B07、逐late合法人工恢复、跨tab/关闭tab/清存储耐久。局部reconcile不关闭全I81/T62/T64/64T或发布门禁，下一实际MySQL544。

- 最终收尾：独立文档再读新00全文/08全文/本handoff当前节，无新增具体P1/P2或证据过度声明；不是日志/字节认证。strict39854、最终diff、121hash/100AST及8docs31links/3JSON/64T/F20均实际通过。14:29北京时间no-fetch sweep实际exit0，main0修改1既有untracked、自有97修改101untracked、无upstream；仅本地缓存，不核远端最新，不自动push/merge或删分支。
- 八个owned536–543的runtime.version8.0.46/scope/精确datadir/Shutdown及提权CIM无对应进程逐一核对后，准确24数据/临时目录与15一次性writer共39路径已删，portal-v153-cleanup.json有真实回执；unit basetemp152不存在，未声称删除它。日志/runtime/源码/复用runtime/runner/checker、Chrome PNG及历史冻结包保留；Vite已停止，无本批后台任务遗留，不改ACL/他人路径。新v153源快照/00/08将独立冻结，完整性及ZIP准确字节/hash由视觉交付目录的verification与package-verification回执保存，不覆盖旧包。整体goal active，下一MySQL544。

## 客户门户 v1.52 详细文档交付及D07/D08独立复核（2026-10-06）

本次用户要求详细开发文档并进行对抗性审查；仅修04锁等待契约、README导航/当前交付、07及本交接，生成新v1.52冻结文档包。继承完整实施goal仍active，既有产品及未完成实现不受改变；未开始v153/reconcile-outbound实现或实际MySQL536。原确认的英文客户站/中文管理、业务员审核正式PI，完整当前提案客户接受、销售隔离、标准SKU映射、R01–R06/W01–W07/T01–T64/F20/P0保持。

两路独立只读审查八篇核心正文、v1.50–v1.52当前增量、交付00/08。交易发现D07/P2：04早期“协议关闭”例外与已安装ON/OFF永久屏障/有限锁等待冲突；统一actualmapper连接永久参与与01严格缺表例外。新增交付08的D08/P2取证期间撤权最终拒绝泛化到普通读，改按两阶段写/核对、普通读、下载/邮件各自授权时点。两项定向复核已消除；未发现其他新增具体P1/P2。两项为文档问题，不增加F/I、不声称运行漏洞复现。身份审提出README“07末尾”导航陈旧，已修。审查者未逐行复核全部历史附录、代跑或认证历史日志/生产。

主线程最终静态源文档实测8篇/31本地链接锚点/3JSON/64T/20F通过；项目strict/session79989最终exit0增量无违规、git diff --check exit0（既有LF/CRLF提示），115源码hash/95AST匹配。13:48北京时间git_sweep --no-fetch实际exit0，主目录0修改1既有untracked、自有97修改98untracked且无upstream，仅本地缓存快照，不核远端最新；不会以这些关闭业务验收。新10篇交付包括00导读、8源快照、08本次12攻击路径，加冻结交接/候选清单和原型原字节副本；包与SHA验证结果在视觉交付verification记录，不改旧v149包。没有新增业务/数据库/浏览器测试、生产连接、真实供应商/SMTP/COS、commit/push/merge或部署；下一安全实现方向仍出库原单核对及确认/worker等OPEN，下一MySQL536。

## 客户门户 v1.52 运费原单核对当前授权与原子绑定（2026-10-06）

- 在自有codex/customer-portal-dev-docs继续完整开发目标，迁移实际POST /api/shipments/{id}/reconcile-freight的手工原ID绑定/已知ID刷新。英文客户站/中文管理、完整当前提案客户接受→唯一PI、销售隔离/标准SKU映射、R01–R06/W01–W07/T01–T64/F20/P0保持；无commit/push/merge/部署、共享库/迁移或真实供应商/SMTP/COS，整体goal active。前一v151是实现、实际测试和文档修订进展，不是无进展或外部等待。
- 新freight_reconciliation_service从fresh boundary永久authority ON/OFF→当前shipment:write（body含remote_id另当前shipment:admin）→原谱系/实际Invoice→原receipt全量或实际业务员财务scope。invoice:read_all不替代，未新增invoice:write/receipt:write；原presale/主运费0保留，不新增ready。原Settlement与完整资金关系current锁读、scoped全字段指纹；不可变FreightTarget原ID/name/customer/currency/amount、FreightEvidence.active/matches放锁GET详情/活动列表，结束token/cache后final当前授权/范围/原version与全部原关联优先于商业mismatch/inactive。期间撤权/转交/资金变化不再写入原目标。
- 原金融算法保持：手工仅原uncertain/verifying/failed且未绑定不同ID，远端合法匹配且活动才绑定原ID/bound，原bind+refresh target version+2合为同最终事务；已知原ID合法匹配/active为bound，否则保ID并uncertain/fixed error，target version+1。Settlement.state/version不改，原金额/费用/编号/载荷/attempt/lease和其他资金关联不改；一条准确当前actor/reason的reconcile_freight事件与目标flush/current describe后由第三caller commit保存，取消原多次商业提交与中间verifying窗口。无remote POST或新金融对象。
- 正常/依赖401/403/404及固定422 private,no-store/Pragma；local坏ID/原version/图变化与手工不匹配409，远端详情/活动列表技术形状错误固定503而非写uncertain，不泄漏provider/SQL。手工mismatch与known合法mismatch隔离有阳性/阴性对照；原未知结果无稳定commandkey，先GET原target ID/status/version及审计，Settlement.version未变不能推断未执行。known刷新本来可重复观察并新增target version/event，不宣称唯一原键回放；手工已成功bound后旧请求409不重绑。
- 530/session37474 actual exit1：8 failed,68 warnings,43.04s；旧JWT停用/撤角色/动作6例仍200，当前grant旧empty token2例仍403，既有I81/P1在该入口两模式的实际反例。531/session67296 actual exit0：8 passed,68 warnings,43.04s初步。532/session37796 actual exit0：135 passed,677 warnings,307.18s=81当时freight+54受影响retry；后续独立审查发现新增ready收紧，不能把初步绿当全部完成。
- I127/P2：新实现误加receipts.ensure_order_ready(current=True)；旧service.get(lock=False)→get_order(writable=False)，原bind_exact/refresh没有该限制。主PI后来sync uncertain/unsynced/pending allocation，已有运费原单无POST核对被409阻断。533/session9275 actual exit1：6 failed,4 passed,85 deselected,68 warnings,47.08s；六历史阳性实际409构成产品RED，修订移除新增ready/unused receipts导入，当前授权/范围/fullgraph保留。四persisted ID零/前导零/Unicode/坏字符串对照原初版已安全409/private/零IO：OkkiApiError继承ValueError，由execute处理，非新增产品缺陷，未创建I128。
- 534/session82225 actual terminal exit0：149 passed,747 warnings,340.58s=95新freight+54原retry。95定义8当前授权+16锁外NOWAIT/主体/归属/资金变化+1最终manual admin撤权+18手工拒绝/known隔离原金融对照+20技术坏形状/错误+4准确同Session第三commit before/after ACK+2脏caller+4实际财务scope+8真实order_active helper只替GET+6合法notready历史恢复+4真实InnoDB Invoice等待/current归属或目标+4坏本地ID。actual data_lock_waits确认阻塞，锁返回后门控并取独立已提交基线，拒绝后全finite21不变。success/afterACK全21逐列白名单只目标remote_id/status/error/version和一条准确actor/reason事件变化，原非空attempt、过期lease和所有金额/费用/关联/Settlement/历史事件保持。
- 同Session第三commit事件故障exact marker命中；before无金融变化，after目标/审计已持久、GET零写且Settlementversion仍原；manual旧body409不新增。event故障非物理故障，history via SQL构造不是完整合法上游恢复，finite21非全DB/allwriter，薄schema五索引非全FK/历史迁移。实际main/ASGI/JWT/admin/portalDDL/生产autoflush=False、随机口令/loopback独占MySQL8.0.46、合成provider/token、真实HTTP禁止/无.env；真实多页/字段合同、在途sender及全worker不由这些规格证明。8/81/135/6/149及历史不累计。
- 534终态后rg确认freight_delivery.bind_exact只剩旧单测无生产调用，已移除废弃函数；deliver→refresh实际worker路径保留待自身协议迁移。原unknown-freight金融unit映射到新纯_read_evidence/_apply，保留inactive拒绝且原ID未绑定/active原IDbound，并增强target version+2/Settlementversion/amount/handling_amount不变断言；不将纯unit当授权证明。独立金融审定向确认删除/映射未弱化，无新增具体P1/P2。新service/route自534开始未变，清理影响的535/session6014 actual exit0：20 passed,75 deselected,122 warnings,70.05s，两个currentgrant+18金融对照；未重跑未受影响其他129或声称清理后149整套新绿。
- 受影响原金融47 SQLite/session74091 actual exit0：47 passed,7.61s，强制仅SQLite Engine.connect、禁PyMySQL/实际HTTP，无.env，使用-p no:cacheprovider避免无关缓存写入，不删/弱化测试或改ACL。MySQL warnings既有依赖未改；本批无前端/UI或表/迁移改变，不新增build/浏览器证明，v150范围不能当本批证据。旧v149-r2冻结包/hash保持。
- 独立金融源审首先提出I127，实际RED修订后定向复核已消除，真实等待/finite21非空租约对照无其他新增具体P1/P2；未代跑/认证534/535。独立文档审最新八篇v152/API/MySQLREADME权限/版本/无key/原历史恢复/95分组与所有OPEN一致，无新增具体P1/P2或过度声明；最终本handoff定向补读与准确owned清理收尾另补。115sourcehash/95PythonAST、8docs31links/3JSON/64T/F20通过；strict/session93055及清理后92191 actual exit0增量无违规，diff无空白错误，既有LF/CRLF提示保留。rg零剩余bind_exact引用exit1是预期无匹配，不是结构检查失败。
- 13:32北京时间no-fetch sweep actualexit0：main0修改1既有untracked、自有97修改98untracked、无upstream，仅本地缓存快照，不核远端最新。不push/merge/清分支/改ACL/他人路径。owned530–535数据/临时目录准确清理待最终确认，日志/runtime、复用工具、历史UI/文档交付保留。整体goal仍active，下一实际MySQL536。
- 整体OPEN：reconcile-outbound/confirm-outbound当前授权执行协议、freight/outbound worker/自动Intent/投递绑定、其他rawSQL/未登记writer、initially OFF旧路径、未持久在途provider结果及私有上传残留；I77完整生产启动、I92/I79/C05实际旧bytes/deps/config/allwriters及合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活、历史迁移126失败、真实provider/SMTP/COS/B01–B07、逐late事实合法人工恢复、跨tab/关闭tab/清存储耐久。局部运费核对不关闭全I81/64T/发布门禁，不标complete/blocked，继续原完整开发目标。

- 收尾独立文档定向补核本handoff与v152契约：149整体95+54、删废弃helper后的20定向与47独立SQLite分别记录，不声称重跑其余129；I127/已安全四badID、当前权/范围、目标版本/无key/finite21与全部OPEN一致，无新增具体P1/P2或过度闭环。审查者不认证实际日志或清理。最终115hash/95AST、8docs31links/3JSON/64T/F20及diff复核通过，产品自535启动后未改，不重复无关测试/构建。
- owned530–535实际runtime8.0.46/scope/精确datadir/Shutdown complete与提权CIM零对应进程后，18准确data/temp/pytest目录及11一次性writer共29路径已清理，portal-v152-cleanup.json记actual回执。portal-presale-unit-152不存在，未声称删除它；日志/runtime/复用runner/checker和历史交付物均保留，无新浏览器/Vite服务，不改ACL/他人路径。整体goal保持active，下一实际MySQL536，可继续原出库核对/确认与投递协议。

## 客户门户 v1.51 明确失败运费/出库重试与对抗修订（2026-10-06）

- 在自有 codex/customer-portal-dev-docs 接入实际 retry-freight/retry-outbound 两路当前授权协议，并同步详细开发文档和对抗审查。英文客户站/中文方舟、完整当前提案客户接受→唯一 PI、销售隔离与标准 SKU 映射、R01–R06/W01–W07/T01–T64/F20/P0 保持。无 commit/push/merge/部署、共享库/迁移或真实供应商/SMTP/COS；整体 goal active，未扩展生产授权。
- JWT 仅身份，fresh boundary 永久 authority ON/OFF→当前 shipment:write→原谱系/实际 Invoice→当前 receipt 全量或实际业务员财务 scope；invoice:read_all 不替代，未新增 invoice:write/receipt:write 要求。捕获完整当前 Settlement/item/App/Receipt/Batch/target/Outbound 与原 Invoice/Intent/Allocation/日志/附件的 scoped 指纹、原不可变 RetryTarget。首 commit 放业务锁，按原名称/serial 只读查重，第二 commit 结束 token/cache，rollback/expire 后最终当前动作/scope/全关联和原版本状态一致，再沿用原状态算法与一条准确 actor/reason 审计；flush/current describe，路由第三 commit 保存商业结果。无 remote POST、新金额/费用/编号/载荷或新金融对象。
- 运费仅明确 failed/未绑定且原 awaiting_payment/awaiting_verification/ready 可 unverified；出库仅明确 failed/未绑定且原 review_required 可 pending+outbound_pending。保留原 active/预售/主运费为零条件，原冻结载荷身份/hash 变化拒绝；uncertain/sending/已有远端 ID 不重试。移除 freight_delivery/shipment_delivery 的废弃 retry_failed（仅原两路调用），无兼容 fallback；其他 worker/helper 不借此声称完整迁移。
- 525/session61039 actual exit1：8 failed,60 warnings,42.97s，原旧 JWT 撤停用/角色/动作六场景仍200，当前新增 grant 两场景仍403，既有 I81/P1 在两路局部实际反例。526/session31920 actual exit0：8 passed,60 warnings,41.01s 初步。527/session50263 actual exit0：36 passed,178 warnings,94.24s 扩展初步；scratch writer 的“42”只是错误打印，不能当验收计数。后续审查发现两个反例并实际补 RED，不把初步绿当全闭环。
- I125/P2：found 原单提前 ValueError，期间停用/转交只返回409而不执行最终当前403/404。I126/P2：实际 freight scanner 缺名称误判空、两个不同完整非匹配列表误判absence，[] 抛未保护 AttributeError、坏 count/ID 误报商业409。528/session60260 actual exit1：13 failed,36 deselected,72 warnings,51.03s，4当前授权优先+8实际scanner坏页+1全图变化准确产品反例；只替 remote.read/使用 ACTUAL_FREIGHT_SCAN，不拿替 whole scanner 的测试冒充解析证据。修订冻结 RetryEvidence.exists，最终当前授权/原图优先后判 found；实际 scanner 两遍完整 canonical 正 ID→有效 name 图一致，合法重排序允许，不完整/重复/观测变化 OkkiApiError 固定503。没有真实服务，不宣称现场重复资金单已发生。
- 529/session43242 actual terminal exit0：54 passed,252 warnings,129.48s。8 当前授权+16 锁外独立 Invoice NOWAIT/原图变化+6 found/技术错误+4精确同 Session 第三 commit before/after ACK+2脏caller+4 found同时撤权/归属变化+8真实scanner坏页+1身份图变化+5合法空/其他/同名/重排/改名对照。成功及afterACK对finite21全模型每列白名单：仅原目标状态/attempt/lease/error/version，出库另 Settlement.state/version/updated_at 和一条原 actor/reason 事件变化；其他金额/费用/关联/历史事件完全保持。beforeACK全图不变，afterACK GET当前状态及原唯一事件，旧请求409不新增；事件故障不等于物理故障。54/36/8/13及历史不累计。
- 原金融单测调整为明确 _read_evidence→_require_absent/_apply，保留 found阻重试、absence原算法及金额/版本断言；151/session44164 actual exit0：47 passed,1 warning,7.62s 初步，final/session22933 actual exit0：47 passed,1 warning,7.78s。运行时强制仅内存SQLite，非SQLite connect/PyMySQL/真实httpx禁止；warning为测试缓存尝试写只读worktree失败，不修改ACL/依赖，不称零warning或MySQL权限证明。
- 独占随机 loopback/口令 MySQL8.0.46、真实 main/ASGI/JWT/admin/portalDDL/生产 autoflush=False，薄上游5唯一索引、合成provider/token和禁止真实HTTP/无.env。finite21不是全DB/allwriter，直接DB构造failed历史不是完整现场发送失败证明；真实分页/字段合同、在途sender崩溃、逐迟到事实合法人工绑定未由本批验证。没有稳定 command key，未知提交先GET原状态/version/审计，旧版本409不能推断未执行，不自动重发或重号。
- 独立金融定向审查先提出 I125/I126，修订后源码复核已确认两个原P2消除，未发现其他新增具体P1/P2，并复核实际scanner合法/故障对照和finite21成功/ACK白名单。只读审查者不运行/认证529。八篇v1.51、API、MySQLREADME与113源hash/93 Python AST已同步；8docs31links/3JSON/64T/F20检查通过，strict/session29783 actual exit0 增量无违规。diff无空白错误、既有LF/CRLF提示保留。本批无frontend变化，无新增build/浏览器验证，v150范围保留不能当本批证据；旧v1.49-r2冻结包原SHA不覆盖。
- 13:06 no-fetch巡检读取本地Git后写HTML因工作树默认写边界PermissionError退出1；按授权提权仅本任务看板写入重试，13:07 actual exit0：main0修改1既有untracked，自有97修改97untracked、无upstream，非远端最新核验。没有自动push/merge/branch清理；独立文档复核、owned525–529关闭/准确临时产物清理收尾另补。
- 整体 OPEN：发货 confirm-outbound/reconcile-freight/reconcile-outbound 与实际投递 worker/自动 Intent/绑定、其他 raw SQL/未登记 writer、initially OFF旧路径、未持久在途供应商结果/私有上传残留；I77生产启动、I92/I79/C05实际旧bytes/deps/config/allwriter及合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活、历史迁移126失败、真实供应商/SMTP/COS/B01–B07、逐late事实合法恢复，以及跨tab/关闭tab/清存储耐久。两路局部重试不关闭整个I81/64T，不标complete/blocked；下一安全方向仍可推进原确认/核对协议。下一实际MySQL530。

- 收尾独立文档定向复核八篇v1.51/API/MySQLREADME/handoff无新增具体P1/P2或过度声明；54分组、当前权限/原财务scope、最终授权优先、实际scanner与无稳定键未知恢复/全部OPEN一致。审查者仅审文字，不运行或认证日志/清理。最终113hash/93AST、8docs31links/3JSON/64T/F20与diff检查通过，产品源码自529启动后未变，不重跑已通过的业务测试或无关前端build。
- owned525–529实际runtime8.0.46/scope/精确datadir/Shutdown complete与提权CIM零对应进程核验后，15个准确data/temp/pytest目录与9一次性writer共24路径已清理；portal-presale-unit-489已不存在，未据此声称删除它。portal-v151-cleanup.json记录actual回执，全部日志/runtime与复用runtime/checker/历史交付物保留。无新浏览器/Vite服务，无改ACL/他人路径。整体goal仍active，下一实际MySQL530。

## 客户门户 v1.50 原发货核对与当前标签页恢复（2026-10-06）

- 在自有codex/customer-portal-dev-docs完成原发货create核对入口与实际Vue恢复局部实现；英文客户站/中文管理、完整提案当前接受→唯一PI、销售隔离/标准SKU映射、R01–R06/W01–W07/T01–T64/F20及P0不扩展。无commit/push/merge/部署、共享库/迁移或真实供应商/SMTP/COS；整体goal仍active。
- POST /api/invoices/{id}/shipment-settlements/submission-status使用完整原ShipmentCreate，当前invoice:write+shipment:write、仅payment另receipt:write，始终原实际Invoice财务scope，invoice:read_all不替代receipt范围；永久authority ON/OFF与原创建_authorize/current replay共用。按原key实际Invoice/actor/hash/quote_hash/URL及历史item/deposit/Batch/App/target/proof关联，原key先于新ready/文件/余额条件。只读DTO、零金融DML/商业commit/外部IO/文件取证，finally rollback；dirty caller在finally外409不flush/rollback其修改。found含原id/key/hash及current describe；not_found不证明未执行、不取消锁外原POST。成功/依赖/固定422均private,no-store/Pragma，SQL/Busy503不降为absence。原创建成功仅新增request_key/quote_hash响应，三阶段金融语义保持。
- Vue发送前save/readback完整原Invoice/body/key，原金额字符串/备注/附件ID保持；每actor当前tab一个未解槽，即使打开另一Invoice先核原目标。unknown编辑冻结，authorized DTO才显示；401/403/404隐藏；auth变化sync generation/Abort/清显示，迟到status/POST不saved，原槽保留。已可靠保存槽可关闭/X/Esc/离页，busy/uploading及无可靠槽未知仍阻；重开/刷新仍先当前授权status。beforeunload警告；slot未加密、非授权来源、不是tab关闭或人工清存储后的耐久journal。
- I123/P2真实Chrome RED：原POST503→核对403且已可靠保存仍不能关闭；修订persisted安全退出与pending编辑冻结分离。I124/P2真实Chrome RED：Storage拒写金融POST=0→restore误当unknown→首次actual409永久保槽；修订mayHaveSubmitted首invoke前设置、alreadyUnknown先捕获；同活组件明确未invoke的新命令首次确定事务拒绝清槽/quote并当前授权restore重新报价，旧槽/重开保守未知，已真实unknown后409仍保持完全原请求。not_found永远不解冻已发送未知。独立金融审定向复核这两条和正反Chrome断言，无其他新增具体P1/P2；只读不认证运行日志。
- backend521/session61717 actualexit1：9failed48warnings43.04s，原status入口缺失，非既有运行auth漏洞证明。522/session28113 actualexit0：9passed57warnings42.01s初步。523/session53392 actualexit0：32passed148warnings86.87s扩展。524/session21294 actualexit0：140passed598warnings299.88s=36新status+82原create+22共享batchstatus，含4准确原第三commit before/after ACK×payment、同Session/stage命中、before无资金图/afterfound原id及完全原key重放唯一；createdhelper加强实际create响应key/hash，原unique/event/items等断言保留。32/9/140及历史不相加。
- 核对每次engine DML探针+21金融模型全字段快照+provider/真实storage-helper禁止；真实main/ASGI/JWT/admin/portalDDL、生产autoflush=False、随机loopback/口令独占MySQL8.0.46、薄上游5unique索引、合成provider/token/quote、禁止真实HTTP/无.env。历史paused/cancelled/shipped直接DB构造只证明原回执读取，不是合法人工状态流转；event故障非物理故障，finite21非全DB/allwriter。新status在原POST锁外receipt_types持有时not_found零写→原放行成功→同keyfound，不声称观察期间持续授权。
- Chrome red-close actualexit1精确closingBlocked断言、red-storage actualexit1精确slot应null却仍存在，均保留日志；早期hidden native checkbox、缺actual global CSS/动画中几何、已勾选checkbox反向取消及手机Tab聚焦select后click关闭为夹具/观测错误，不称产品RED。最终portal-shipment-browser-150-final3 actualexit0：1440/390/320，真实Vue/ElementPlus/global app.css/sharedclient/Pinia/router/sessionStorage/AbortController，API/auth合成。包括safeexit/routeleave/reopen/reload/原Invoice不同props恢复、not_found零financialPOST、原body/key精确重试、trueunknown→409冻结对照、storage0POST→firstactual409清槽再核算/新请求、actor/迟到status+POST真实transport aborted、几何与console/unexpected端点空。实际final3截图/results保留；不是后端权限/真实服务证明。
- Node final2 actualexit0：14passed0failed119.9281ms，含原body字符串冻结、actor/槽冲突、quota/drop/corrupt、非法数据、原完整receipt/精确原item observation、未知分类。Vue latest build/session23082 actualexit0：17.01s，既有chunk>500k warning保留不改无关依赖。前版build17.31s非最新结果。新源码自524启动后未变后端，frontend自final build开始未改产品；后续只是测试辅助定位/文档，未重跑无关全390。
- 八篇v1.50/API/MySQLREADME已同步，旧v1.49-r2冻结包/SHA不覆盖。独立文档审D06/P2：新API“含payment才receipt:write和财务scope”歧义，03/API改始终原scope、只receipt动作条件；04明确此前已有unknown才后续409不可解冻，首invoke前未发的首次拒绝例外保留。历史最新导航修到最新章节；这是文字契约修订，不称新增runtime漏洞/改变产品。最终定向文字复核待收尾记录。
- 当前108 sourcehash/89 Python AST、8docs31links/3JSON/64T/F20通过；strict/session64909 actualexit0增量无违规；API新EOF空白已定向清理，最终diff复核另记。12:44北京时间no-fetch sweep actualexit0：main0modified1既有untracked、自有95modified96untracked、无upstream，仅本地快照不核远端新状态。owned521–524 shutdown/CIM及清理、最终strict/文档复核收尾下补。
- 完整goal OPEN：shipmentconfirm/reconcile/retry、自动Intent/投递绑定、worker/sender/rawSQL与未登记writer、initially OFF旧执行器、未持久在途provider结果/私有上传残留；I77完整生产启动、I92/I79/C05旧bytes/deps/config/allwriter合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活、历史迁移126失败、真实provider/SMTP/COS/B01–B07及逐迟到事实合法人工绑定恢复。当前tab关闭耐久仍OPEN，局部I123/I124修订不关闭整个I81或全64T。不标complete/blocked；下一安全方向仍可推进其余发货实际核对/确认协议。下一实际MySQL525。

- 收尾独立文档定向复核D06/新增handoff已完成：权限条件、未知时点与140/Chrome/Node/build及全部OPEN一致，无其他新增具体P1/P2或过度声明；审查者不认证运行/清理。主线程最终108hash/89AST、8docs31links/3JSON/64T/F20、diff无空白错误，既有换行提示保留；strict/session13921 actualexit0增量无违规。产品源码未再改，不重复无关业务/构建。
- owned521–524实际runtime8.0.46/scope/精确datadir/Shutdown complete与提权CIM零对应mysqld核验后，12准确data/temp/pytest目录及18本任务一次性writer共30路径检查并删除，portal-v150-cleanup.json记录actual回执；日志/runtime/复用runtime/checker与final3截图/results保留。Vite/session24166按Ctrl-C正常停止（terminalexit1）且提权CIM无相应port4187进程；不改ACL或他人目录。旧v1.49-r2 ZIP保留原SHA，整体goal仍active。

## 客户门户 v1.49 详细开发文档/对抗审查与本地发货状态当前授权（2026-10-06）

- 在自有codex/customer-portal-dev-docs继续已授权开发目标，并同步用户详细开发文档和对抗审查请求。cancel/pause/resume JWT仅身份，永久authority在ON/OFF都参与，当前shipment:write及原实际Invoice财务scope；无需新增invoice:write/receipt:write，invoice:read_all不能替代receipt范围。定位结算后永久门户谱系→当前实际Invoice→完整资金关联图，原预售/ready/pending库存/主运费0与原状态算法保持。服务零外部IO/零commit，显式flush后current描述，路由唯一commit保存状态/本App/审计。
- 当前锁读实际Settlement/item/App/Receipt/Target/Batch/Outbound/Log/Event，关联归属/客户/币种/组件/目标及金融值先核后apply。取消仅释放本Settlement的App，不按共享Receipt批量释放，Receipt金额/费用/状态和其他App保持。暂停无新增late_result日志守卫，取消/恢复对未released App持久late事实保守拒绝；自由文本reconciled/synced不能证明逐事实已解决。合法人工绑定但旧late仍在的恢复限制OPEN，未声称完整合法恢复。resume原当前剩余0→awaiting_verification否则awaiting_payment，无新增pause/cancel足额规则。
- 原version/reason没有稳定commandkey；SQL/单commit不明固定503/private,no-store/Pragma，先GET核原版本状态及原审计。beforecommit全图无变更，合法后人工原版本处理；aftercommit已成功丢ACK保原version/event，GET零写，旧version409不能当未提交，无自动幂等重试。依赖401/403、范围404、业务409及安全422均私密不回显输入；脏caller不flush/rollback别人的修改。
- 512/session4919 actual exit1：12failed85warnings49.08s，当前三动作旧JWT停用/撤角色/撤动作九例仍200、当前新增grant三例反403，属于既有I81/P1局部实际反例。513/session24325 exit0：12passed85warnings48.88s初步修订。514/session8725 exit0：89passed443warnings196.25s为扩展初步，但fixture默认autoflush=True不能证明生产取消释放。SQLite presale514/session99878 exit0：47passed7.87s，原金融算法断言由显式financial_state纯helper保留，不是MySQL当前权限证据；原get(lock=True)历史not-ready守卫单测保留，未删除未迁移路径。
- 515/session85145 actual exit1：1failed1passed77deselected26warnings30.14s。新I122/P2生产autoflush=False实际POST取消200、状态/version/event成功但deposit App仍reserved；True对照通过。根因apply后current populate_existing覆盖未flush释放。修订为同一事务先flush再读取，不提前commit或放锁；119新state_app匹配生产False并保显式False/True及持久App40/4/唯一事件对照。516actual exit2：3collection errors1warning0.83s，机械导入误把fixture来源改为state_app，不到MySQL/业务；修正import不改产品/断言，不当产品RED。
- 517/session16002 actual terminal exit0：119passed603warnings259.56s，为12权限+79边界/金融+28并发/故障。随后只补测试证据，不改产品。独立审查指出成功/丢ACK仅局部字段不足以证明完整有限资金无副作用，已加21模型全字段白名单，仅目标Settlement.state/version/updated_at、cancel本App.status和唯一准确action/reason/actor事件变化，Receipt金额/费用/状态、其他App及历史事件精确不变。资金先胜时真实commit后，失败状态Invoice FOR UPDATE返回、_capture/apply前门控外部基线，再核409全21不变及Batch32/2、Receipt/App金额/fee归属。518/session38698 actual exit0：28passed170warnings81.09s补强定向复验，非产品新缺陷。
- 519/session69536 actual terminal exit1及520/session62082 actual exit0：519: 1 failed, 389 passed, 1610 warnings in 812.19s (0:13:32); 520: 2 passed, 26 warnings in 30.07s。519收集119当前三状态+75报价读取+82结算创建+114回款批次创建/核对390项，389通过，唯一status[target]在准备db.commit阶段因两个测试共用invoice:wrong:goods撞唯一键1062，未进入其产品HTTP断言，不是产品RED。随后只改state-boundary[target_key]/status[target]夹具为每例独立uuid非法键，status另核独立Session已持久坏键；保留原409/全有限图零写/noIO断言。520在同一库按原先后顺序实际2项复验通过，未重跑未受影响其他388，不声称补强后的390整套新绿。产品自519启动后无改动；119/28/389/2/89/47及历史数量不相加为全产品通过。warnings为既有依赖，未修改无关库。
- 实際隔离随机loopback/口令MySQL8.0.46，真实main/ASGI/JWT/admin/portalDDL，五薄唯一索引及21有限关联快照；受控seed/jobs/MCP挂载、实际HTTP禁止、无.env。正向current余额等待是维护Receipt/App/Batch汇总的受控直接DB变更，不是所有rawSQLwriter协议证明；共享reserved构造只验关联隔离，不证明该合成历史容量合法。legacy late/reconciled测试是SQL自由文本标记，不是实际合法manual-bind恢复联调。事件故障不是物理故障，有限图不等于全DB/allwriters，薄schema不等于全历史FK/迁移/生产启动。
- 独立金融源审复核当前auth/binding/原金融规则/flush无新增具体P1/P2，并提出上述成功快照缺证，补强后定向复核门基线与白名单无假绿。独立文档审八篇v1.49/API/MySQLREADME无新增具体P1/P2或过度闭环。审查者只读、不运行或认证日志/清理；实际终态由主线程核。101sourcehash/88AST及8docs31links/3JSON/64T/F20通过；strict/session24007 actual exit0增量无违规，diff无空白错误，既有LF/CRLF提示保留。11:56北京时间no-fetch sweep exit0：main0修改1既有untracked，自有93修改92untracked、无upstream；只本地快照，不核远端最新。
- 当前详细文档保持英文客户站/中文管理、完整提案同版本客户接受→当前员工唯一PI，四核心要求、F20历史5P1+15P2、64T、7W、R01–R06和P0边界不变。v1.48旧冻结包不覆盖；本轮v1.49文档冻结交付另记录结构/来源hash与包校验，不拿包校验或原高仿真UI证明真实业务验收。本批UI未改，不重build/冒称新增浏览器通过。无commit/push/merge/部署、共享库/迁移、真实供应商/SMTP/COS或prepare/publish/finalize；main源未改。
- 整体goal仍active：shipment confirm/reconcile/retry、自动Intent/投递绑定、worker/sender/rawSQL及未登记writer、初始OFF旧执行器、未持久在途provider结果/私有上传残留；I77全生产启动、I92/I79/C05确切旧bytes/依赖/config/allwriter及合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活无重复、历史迁移126失败、真实provider/SMTP/COS/B01–B07；逐迟到事实合法人工绑定恢复与发货独立核对API/前端持久未知结果恢复仍OPEN。可继续安全本地工作，不标complete/blocked。下一实际MySQL521。临时owned数据/进程清理及最终文档交付校验收尾后下补。

- 收尾独立文档审仅核新增06/07与本handoff，无新增具体P1/P2或519/520过度整套声明，不认证日志/清理。最终101hash/88AST、8docs31links/3JSON/64T/F20复核通过；strict/session32559 actual exit0增量无违规，diff无空白错误仍既有换行提示。 actual exit0，本地main0修改1既有untracked、自有93修改92untracked、无upstream，未核远端最新。
- owned512–520中516未启动MySQL；其余真实runtime8.0.46/scope/准确datadir/Shutdown complete及提权CIM零对应mysqld核验后，28精确owned目标检查、24存在目录删除（data/temp/pytest及SQLite-only固定basetemp），日志/runtime/复用checker/runtimes/旧包保留；portal-v149-cleanup.json是实际回执。一次性writer按精确scratch路径最终删除另记回执，不改ACL/他人目录。新v1.49详细文档的包装验证和ZIP hash单列在视觉交付目录delivery-v149-package-verification.json，只认证冻结结构/来源/链接/原型原字节，不能认证全64T/allwriters或上线。

- 最终00/08/manifest独立文字审查发现D05/P2历史v1.48段“本次未新增运行或代码修改”与当前v1.49证据时点混淆；已定向改历史标题/限定旧批次，HTTP/MySQL与SQLite金融单测分列。07记录文档修订，无F/I新增、产品/断言/运行结果改变。当前交付审查修订1.49-r2；首轮review-draft zip按原f30ae1…字节保留备查，正式v1.49包按修订文档重建，最终结果单列verification，不把文档审查当业务证明。

## 客户门户 v1.48 详细开发文档冻结交付与独立对抗审查（2026-10-06）

- 用户当前请求为详细开发文档与对抗性审查，本轮只修改自有工作树文档、生成新的 v1.48 冻结交付，不启动 v1.49 业务实现或 MySQL512。八篇源契约、00开发指南、08当前审查、实现证据/源码发现清单与高仿真UI一起包装；原 v1.47 及更早包不覆盖。当前后续开发目标仍开放，不把本次文档完成作为全部实现完成。
- 第一位独立只读审查者发现 D04/P2：history_grants 定义 order_request_id 但约束 order_id。02统一 order_request_id，并明确 order 级请求属于同一 access、request_history 级为NULL。工作树和交付快照定向复核关闭；这是文档字段矛盾，不冒称runtime漏洞/业务代码修复，不增加历史F20或实施I编号。第二位独立交易审查未发现新增具体P1/P2，复核完整提案/当前接受/唯一PI、金额、原回执优先、amendment、迟到事实集合与OPEN门禁。两位均只读，不运行业务测试或认证历史日志。
- 主线程本次读取现存511日志末尾实际271passed/1026warnings/542.94s；保留薄schema、合成provider、有限21模型、普通首查询鉴权及生产未验证边界，不与47金融单测或旧批次数量累加。本次没有新的业务测试或前端构建。八源文档31本地引用/3JSON/64T/F20检查通过；strict/session63681 actual exit0增量无违规；diff无空白错误，13处既有LF/CRLF提示。11:20北京时间no-fetch sweep exit0，main0修改1既有未跟踪，自有93修改91未跟踪、无upstream，仅本地快照，未核远端最新。
- 本次包校验只证明十篇文档、来源hash、链接/JSON/编号与打包完整性；实际结果写入交付verification.json和根目录delivery-v148-package-verification.json，不能作为64T/全writer/上线凭证。发货其他动作与持久提交恢复、全部writer、在途未持久外发、完整历史迁移、真实provider/SMTP/COS、新旧进程切换及合法回退/B01–B07仍OPEN。无commit/push/merge/部署、共享DB或生产操作。后续开发仍可继续，保持下一实际MySQL512。

## 客户门户 v1.48 发货报价/读取当前权限与原业务排序（2026-10-06）

- 前轮v1.47源修订与十篇详细开发文档交付为实际progress；本轮在自有codex/customer-portal-dev-docs继续完整开发goal，接入POST shipment-quotes及GET capabilities/order/detail四路。JWT仅身份，quote保留当前invoice:read OR write，capabilities原invoice read/write、receipt write、shipment read四OR，order/detail原shipment read OR write；原receipt全量/实际业务员范围不变，invoice:read_all不替代。无commit/push/merge/部署、共享DB/迁移或真实供应商/SMTP/COS；完整goal保持active。
- quote从当前永久authority→谱系/实际Invoice→ID锁序item/完整资金图捕获→第一commit放锁→不可变独立订单/历史出库/freight证据→第二commit结束token/cache→最终新事务当前权限/范围/全图一致→原build_quote(current=True)→独立JSON DTO→rollback，无第三商业commit/无新财务目标/不外发POST。共享_capture显式payment/request_key参数：create两次传原属性，quote不虚造key、不把全局NULL-key Batch纳入。脏caller在finally前拒绝，不flush或rollback它。
- 普通三路在首业务读查询当前DB主体/原OR，历史order/detail不新增ready；无供应商IO/商业commit，不承诺整个响应期间持续授权。四路窄ShipmentReadRoute保护成功、依赖403/401与sanitized422，private,no-store/Pragma，不回显非法ID或body。quote技术SQL/provider坏shape固定503，合法资金变化409；原业务金额、报价值表示和hash算法保留。
- 506/session15691 actual terminal exit1：16failed98warnings55.83s，四路停用/撤role/撤动作旧JWT仍200，当前新grant反403，为既有I81/P1读取/报价局部实际反例。507/session54677 exit1：1failed21warnings28.95s，独立源审I121/P2：原Invoice.items sort_order业务顺序而v1.47create按PK重排，合法两行ID与sort反序quote→create实际QUOTE_STALE409。锁继续ID序，业务items恢复sort_order；同值ID stable tie、NULL升序在先。测试与原get_order/build_quote/fetch_evidence全quote字典及hash精确对照，再核实际创建同quote，避免两边同时PK改序假绿。
- 508/session89070 terminal exit0：17passed101warnings57.96s为初步权限/排序修订。509/session68102 exit1：3failed46passed164warnings117.43s，三例metadata共享表固定ID=1准备时撞PK，未到产品请求断言；独立审查已识别，同终态后改每例唯一ID、UPDATE/独立回查同ID，保留阶段hits/持久断言，不称产品RED。510/session26013 exit0：19passed39deselected64warnings59.15s=两stage×before/after4+ON/OFF锁外admin6+新技术/成功9，为定向中间证据。SQLite presale509/session78182 exit0：47passed7.77s，纯金融helper保留原金额断言，非当前员工权限证据。
- 最终511/session78048 actual terminal exit0：271passed1026warnings542.94s=16权限读取+1原序金融对照+49边界+9技术/成功+原196发货create/批次创建状态。源码与测试自511启动后无行为改变；终态后仅删除router三个无调用顶层import，business AST逐字相等，portal-v148-import-clean.json记录，不重跑无新逻辑的整套。1026warnings为既有依赖，未改无关库。271/19/17/47及历史数量分开，不累计为全产品验收。
- 49/9新规格包括全部10个原OR单动作阳性、not-ready历史读、actual all/super撤销且invoice_all不能替代、依赖/422无私密cache、ON/OFF管理员在锁外先commit→最终403/404、Invoice/item/Receipt/Intent/Allocation/lateLog全图变化、两精确commit阶段同Session故障和真实metadataUPDATE/独立持久值、正常同Session恰两个commit+最终rollback+唯一metadataDML+21图不变、dirtycaller、两performance_schema实际Invoice wait且after_cursor得锁后外部基线、无关NULL-key Batch期间变化仍合法200、四路真实ark_users SQL故障命中和四坏provider形状/金额/重复/订单503。
- 实际隔离随机loopback/口令MySQL8.0.46、main/ASGI/JWT/admin/portalDDL，薄上游五唯一索引与21类有限关联快照；受控seed/jobs/MCP挂载、实际HTTP禁止、无.env。供应商/token/active-list/quote事实合成；正常metadataDML是受控token替身，不是实际token/COS/远端联调。事件注入非物理故障、21模型非全DB/rawSQL、五索引不证明全历史FK/迁移、全生产启动或所有writer。ordinary读只承诺首业务读授权，quote最终授权与提交序不扩大为响应期间持续授权。
- 独立金融源审发现I121并复核修订；49规格指出metadata fixture碰撞，9补证/修订复核无新增具体P1/P2或假绿。独立文档审八篇1.48/API/MySQLREADME无版本/权限/两commit/排序/hash/75+196口径矛盾或过度关闭。审查者只读，不运行或认证日志/清理；主线程实际核终态。97hash/84AST、8文档31links/3JSON/64T/F20检查通过；strict/session79154 exit0增量无违规，diff无空白错误、13处LF/CRLF提示。F20历史5P1+15P2、64T、7W、R01–R06保持，整个I81/门户验收不因此关闭。
- 11:03北京时间no-fetch sweep exit0：main0修改1既有未跟踪、自有93修改91未跟踪、无upstream；只是本地快照未核远端最新。UI本批未改，不重build或冒称新增浏览器验收；v1.46批次tab恢复不外推发货提交恢复。旧1.47 zip与视觉原型保持冻结；本批只同步工作树1.48，不重写旧交付包。
- owned506–511实际scope/version8.0.46/准确datadir/Shutdown complete及提权CIM零mysqld已核，19精确data/temp/pytest及本轮重建presale489 unit目录检查删除；runtime.json/mysql.log/成功失败日志、复用runtime/checkers/旧包保留，portal-v148-cleanup.json回执。一次性writer随后按精确路径收尾，不改ACL/他人目录。opt-in test_presale_live_push.py仍是历史direct-sub/旧claims/隔离SQLite+外部探针，未运行、不能作为当前协议联调证据；不为迁移它加入私有金融绕过路径。
- 全goal与剩余入口OPEN：shipment状态pause/resume/cancel、reconcile/retry/confirm、自动Intent/投递绑定、worker/sender/rawSQL及未登记writer、初始OFF旧执行器、未持久在途provider POST/results、私有上传残留；I77全生产启动、I92/I79/C05旧bytes/依赖/config/allwriter合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活无重复、历史迁移126失败、实际provider/SMTP/COS/B01–B07；发货独立只读核对API和前端恢复未实现。安全本地工作可继续，不标complete/blocked；下一MySQL512。

- 收尾两位独立审查者只定向核新增v1.48 handoff，未发现新增具体P1/P2或过度闭环；不认证测试、AST或清理日志。最终strict/session19239 actual terminal exit0增量无违规；97hash/84AST与八文档检查复核通过，diff无错误仍13处换行提示。八个一次性writer已按精确scratch路径删除并记finish_writers_removed；成功失败日志、runtime/checker和旧交付保留。v1.47 zip当前实际SHA256仍02557fba134e0299b7930162790e6c454afbed84213e55cdd36403383021fddd，不覆盖历史包。业务源无新逻辑，后续只静态文档核对，不重跑271。
## 客户门户 v1.47 发货创建当前授权与详细开发文档审查（2026-10-06）

- 本轮在自有codex/customer-portal-dev-docs继续已授权完整开发goal，并按用户详细文档/对抗审查请求同步八篇v1.47、API和MySQLREADME。POST shipment-settlements的JWT仅身份，初始/最终当前invoice:write+shipment:write，含payment才receipt:write；当前原receipt全量或实际业务员范围，invoice:read_all不替代。永久authority→门户谱系→实际Invoice/排序item，开关ON/OFF同协议。无commit/push/merge/发布、共享DB/迁移或真实供应商/SMTP/COS；整体goal保持active。
- 捕获当前完整Receipt/eligible Intent及全局JSON占图/Allocation/所有Settlement与item/outbound/App及关联Receipt/target/Batch/proof/Log/Event，冻结各模型全字段、独立订单及历史freight/出库目标、文件绑定。第一commit放业务锁→只读immutable provider/类型与真实storage-helper→第二commit结束token/cache→最终新事务当前授权与全图一致→原纯本地金融应用→router第三commit。typed FileEvidence不可用skipflag绕过；全引用仅私有_verified及单一调用，无旧公开register_shipment_payment入口。脏caller捕获前409不flush/不rollback其修改。
- 保留原quote值表示/hash与金额算法；current FOR UPDATE行+Python累计已发quantity、sequence及已用deposit，替代普通聚合旧RR快照。末批原预付款金额/手续费只占一次；无嵌入payment不制造Batch。原key先实际Invoice授权、URL/actor/完整body hash及真实历史item/deposit/原Batch children/App/component/target/proofs，合法后续回款不纳入原操作、不遮回执；新ready/余额/文件/预售关闭不遮已有原key；原历史关联缺失409零重建。
- 499/session91647 terminal exit1：6failed42warnings38.00s，实际旧JWT停用/撤roles/三个write动作仍200，当前新增grant反403；为既有I81/P1发货create子反例。500/session42935 exit0：6passed52warnings37.10s仅初步修订。501/session44221 exit1：2failed43deselected30warnings31.08s，I119/P2真实无payment/嵌入payment创建→后续正常Batch回款→原key错误409；已修订原children全局App归属。502/session40890 exit1：10failed2passed45deselected78warnings49.99s，I120/P2十坏provider形状/数量/UID/重复行/历史freight与两个合法对照；并非全部原始500。锁外canonical和有限整数验证，技术503/private,no-store，合法数量差异409，remote.target_snapshot显式形状校验。
- 503/session36253 terminal exit1：1failed56passed268warnings133.37s，仅late_log夹具构造不存在detail字段TypeError，未到产品断言；改实际message保留原assert，不称产品RED。SQLite presale503/session62070 exit0：47passed7.94s，显式pure verified金融helper，非当前员工授权证据。batch-unit504/session74786 exit0：123passed26warnings20.14s，SQLite-only/PyMySQL及实际HTTP守卫、无.env，原回款/批次/截图导入金融规则通过。
- 联合504/session66326实际terminal exit0：196passed769warnings385.09s=57发货core+25新边界+原114批次创建/状态。此启动后产品源码未改。独立审查指出末批samekey只有200/200+DB唯一，缺两响应同id的弱断言；只补该assert，505/session24581 terminal exit0：2passed23deselected26warnings30.00s同/异key定向复验，产品逻辑未改，不以196冒称补强assert已在该旧运行执行。769warnings为既有依赖；不升级无关库。
- 发货规格包括实际main/JWT/admin、三阶段同一Session before/after准确命中和phase2真实metadata UPDATE/独立持久核对、第三commit已持久丢ACK原key唯一回放、same/different key双capture、真实root撤权/owner变化锁外先commit、所有资金图变化、全局Intent draft/armed/ready占图、末批deposit App唯一金额/fee、脏caller、三performance_schema实际Invoice等待及after_cursor已获锁门后外部基线、四ON/OFF业务第三commit/rollback先于实际管理员屏障等待。它们证明局部提交序，不是响应时持续授权承诺。
- 隔离随机loopback/口令MySQL8.0.46、真实main/ASGI/JWT/admin/portalDDL；薄上游五显式唯一索引与21类有限财务/关联模型。受控seed/jobs/MCP挂载，实际HTTP禁止、无.env。linked_outbound_service.find_related与remote.target_snapshot实际reader受测，但其provider/token/active-list及quote事实合成；真实storage-helper阳性文件只本地，不是COS/真实供应商联调。事件故障非物理DB故障；有限模型非全DB/rawSQL、不是全部FK/历史迁移/全生产启动或所有writer。196/2/47/123分开，不累计历史为全产品验收。
- 独立金融源审提出I119/I120并静态复核修订，57与新增25规格无新增产品P1/P2；末批响应id弱断言补强后确认消除。两位独立文档审核八篇/API/MySQLREADME新增v1.47无新增业务P1/P2或过度关闭，D03类07最新入口1.46遗漏已改1.47。审查者只读，不代跑或认证运行/清理；实际终态由主线程核对。F20历史5P1+15P2设计修订、64T、7W和R01–R06保持，局部实现不关闭整个I81或整体验收。
- 91sourcehash/78AST及8文档31links/3JSON/64T/F20检查通过；strict/session99281 actual exit0增量无违规，diff无空白错误、13处已有/本轮触及LF/CRLF提示。10:36北京时间no-fetch sweep exit0：main0修改1既有未跟踪、自有93修改89未跟踪、无upstream；仅本地快照未核远端最新。源/测试无新增逻辑后只文档/包装核对，不重跑无关frontend；本轮UI未改，v1.46tab批次恢复不能外推发货恢复。
- owned499–505的runtime scope/version8.0.46/准确datadir/Shutdown complete与提权CIM零匹配mysqld已核，23精确data/temp/pytest及两个unit目录目标已检查删除，portal-v147-cleanup.json保留；runtime.json/mysql.log/所有成功失败日志、复用runtime/checker/旧交付与视觉证据保留。不改ACL、不删他人目录；一次性writer收尾单列实际回执。
- 完整goal仍OPEN：发货quote/read/state/reconcile/retry/confirm、自动Intent/投递绑定、worker/sender/rawSQL和未登记writer、初始OFF旧执行器、未持久在途provider POST/results、私有上传残留，I77完整生产启动、I92/I79/C05旧bytes/依赖/config/allwriter合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活无重复、历史迁移126失败、真实provider/SMTP/COS/B01–B07。发货新只读核对API和前端恢复未在本批实现。安全本地工作可继续，不标complete/blocked；下一MySQL506。文档交付完成与整体开发goal完成分别管理。

- 收尾两位独立审查者定向核新增handoff及交付00/08，未发现新增具体P1/P2或过度闭环；196原联合与补同id断言后2项复验、47/123独立范围、I119/I120实际RED与503夹具、21有限模型/五索引及全部OPEN条件一致。审查者仅文字核对，不认证测试/清理。最终strict/session45399 terminal exit0增量无违规；91hash/78AST、8文档31links/3JSON/64T/F20及十篇交付/八源快照/42引用/3JSON/64T/F20/12攻击场景检查通过。包装只验证来源/hash/引用，业务源自504未再改；后续交付zip和一次性writer清理有独立JSON回执，旧包保持冻结。
## 客户门户 v1.46 原批次提交恢复与只读核对（2026-10-06）

- 本轮在自有codex/customer-portal-dev-docs继续完整开发goal，局部实现I116当前标签页恢复，并同步详细开发文档。发送前可靠保存原完整body/key；未知结果冻结金额、凭证、分配、balance_version及key，核对与可能创建原操作的完全原请求重试分开。既有新建入口恢复同actor待核对槽；未新增管理页自动弹窗或独立journal。未commit/push/merge/部署，完整goal保持active。
- 新POST /api/receipts/batches/submission-status位于原settlement_router批次路由，独立窄BatchStatusRoute保护成功、依赖及校验错误private,no-store/Pragma；422固定detail不回显财务input。复用当前receipt:write与实际全部Invoice scope、原actor/hash及真实目标/结算关联；不_capture/取证/建目标/commit，finally rollback释放读锁。dirty caller在try外拒绝，不flush或回滚它。not_found是当前观测，原POST可能仍在锁外取证，不证明失败/取消或允许换键；found返回当前原批次request_key。原create成功新增request_key，不改原金融语义。
- Vue真实组件与共享client冻结原请求，当前tab sessionStorage按actor分槽；每次POST前写入读回确认，禁止覆盖另一未解决body/key，存储拒写零发送。恢复先服务端当前授权，换号同步abort/清私密显示与内存，保留原actor槽供其以后重新授权核对；另一账号不显示/重试它。generation/actor/key拒绝迟到响应；已未知后的403/404/409仍冻结。普通首次明确拒绝允许取消/X/Esc，关闭锁与编辑锁分开。原remark/附件ID是原hash必要字段，未加密且不是授权来源；整个tab关闭、浏览器故障或人工清存储后的持久恢复未证明。
- backend494/session81173 terminal exit1：3failed14deselected26warnings30.95s。其中两个真实422缓存缺失为I117/P2产品RED；匿名预期401但实际HTTPBearer403属于fixture错误，未到cache断言，不虚称第三产品RED。495/session84338 terminal exit1：1failed16passed83warnings56.81s仅同匿名fixture。拆匿名403/无效JWT401保留cache/无私密/零财务断言；496/session52763 terminal exit0：4passed14deselected28warnings31.95s，未额外改产品逻辑。
- backend497 terminal exit4/no tests：错误路径test_mysql_receipt_batch_races.py，正确为test_mysql_receipt_batch_create_races.py；无497隔离runtime。最终498/session72506实际terminal exit0：114passed431warnings219.41s=44core+6targets+22races+20presale+22status，源码和后端测试自此启动后未再改。包含真实第二员工JWT及实际admin新增当前scope旧token生效；只改created_by不冒称跨身份HTTP。原POST锁外取证时只读not_found→放行原提交→唯一原Batch found；SQL事件/TransactionBusy固定503而非not_found；有限18模型、engine DML及provider/真实storage-helper禁止探针。
- 114为隔离随机loopback/口令MySQL8.0.46、实际main/ASGI/JWT/admin与portalDDL；上游薄合成schema只复制三唯一索引，seed/jobs/MCP挂载受控，provider/quote合成、实际HTTP transport禁止、无.env。不是全历史FK/迁移、所有writer、实际供应商/存储、物理DB故障或全生产启动。431warnings为既有依赖；SQL事件和busy注入不证明原生1205。只读DML探针与18模型不是全DB/rawSQL沙箱。
- Node原5+新增5状态规格实际10passed/exit0，涵盖原slot可靠保存/不同key-body拒绝、损坏/actor隔离、清槽匹配、完整成功回执和未知分类。此前backend92/本次114、Node10与浏览器分别报告，不累计为全产品验收。
- browser494 terminal exit1实际I118/P2：初始403后取消disabled导致空弹窗无法退出。修订后495/session19631 terminal exit0三宽中间结果；初版迟到只两帧，独立审查指出证据不足。497/session47242实际terminal exit0，真实Chrome/生产Vue/共享API/真实vue-router，1440/390/320全流程；held handler终态和实际requestfailed均等待后再断言迟到私密/saved，不是两帧推断。498/session69911 terminal exit0只320完整流程，额外完整横纵dialog边界；截图疑似裁切未实际越界，无布局修订。两结果consoleErrors/unexpectedEndpoints为空；取消终态与handler fulfil-error计数不同，不能把cancelledTransportCount=0称零请求取消。
- 浏览器身份/API均合成，覆盖初始/余额/初次明确POST拒绝可退出，未知冻结、not_found零金融POST、完全原body/key重试、重开/刷新、换号回原号先核对、存储拒写和迟到清理；不是真实JWT/MySQL/RBAC或全部服务器成功后续证明。ReceiptManage未改；登录页/整个门户高仿真视觉未在本批改变。浏览器证据保留portal-batch-ui-497/498结果与截图。
- frontend build498/session80937 terminal exit0，16.43s；既有>500kB chunk提示，未改无关依赖。首次build494仅中间证据。strict/session45582实际terminal exit0增量无违规，88sourcehash/75AST及8文档31links/3JSON/64T/F20通过，diff无空白错误、八处既有LF/CRLF提示。10:00北京时间no-fetch sweep exit0：main0改动1既有未跟踪，自有93改动88未跟踪、无upstream；仅本地快照，不核远端最新。交接和包装后静态复核单列，不重复无新逻辑的业务回归。
- 两位独立源审提出I117缓存覆盖/I118普通拒绝关闭及迟到终态证据补强，均修订并按影响验证；最终定向源审无新增P1/P2或弱断言。八篇v1.46/API/MySQLREADME定向文档审同样无新增P1/P2或过度闭环；06设计统计措辞歧义已改为F20统计保持与整条实现验收开放。审查者只读，不代跑或认证日志；真实终态由主线程核对。F20历史设计修订与64条T规格不因114局部通过关闭全部实现。
- owned494/495/496/498的实际scope/version/datadir/Shutdown complete及提权CIM无匹配mysqld已核，12精确data/temp/pytest目录与9一次性writer共21目标均存在且已删；runtime.json/mysql.log/成功失败日志、固定runtime/checker和浏览器证据保留，portal-v146-cleanup.json记录。Vite56836 Ctrl-C终止，提权CIM与5260监听均0；不改ACL或他人目录。497误路径无runtime已实际核对；交接/清理writer收尾精确删除另补回执。
- 其他register_shipment_payment/自动Intent和投递绑定、shipment/worker/rawSQL与未注册writer、初始OFF旧执行器、未持久在途provider POST及私有上传残留收敛，I77全生产启动、I92/I79/C05旧bytes/依赖/config/allwriter合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活无重复、历史迁移126失败、实际provider/SMTP/COS/B01–B07保持OPEN。安全本地工作仍可继续；不把完整goal标complete/blocked。无共享DB/迁移、真实建票/供应商/SMTP/COS或prepare/publish/finalize；下一实际MySQL499。

- 收尾定向复核新增handoff与交付00/08，两位独立审查者均未发现新增具体P1/P2、旧版本状态矛盾或过度闭环；仅文字核对，不认证日志/清理。最终strict/session53855 terminal exit0增量无违规；88hash/75AST、8文档31links/3JSON/64T/F20复核通过，diff无空白错误仍八处换行提示。新独立v1.46交付十文档/八源快照/42引用/3JSON/64T/F20/12攻击场景静态校验通过；验证包仅证结构/hash/引用，源码和业务测试无新逻辑修改，不重复业务回归。交接与包装writer最终按精确scratch路径删除并记finish_writers_removed清理回执；源v1.45及更早包按原hash冻结。

## 客户门户详细开发文档与对抗审查交付补充（2026-10-06，v1.45）

- 按当前用户文档请求，交付00开发指南、八篇最新v1.45契约逐字节快照和08当前审查；源07旧最新入口1.43改1.45、README相应段标为历史。只文档变化，没有继续I116产品实现；历史包按原hash保留。
- 两名独立审查者只读核对身份/隔离/映射及交易/唯一PI/并发恢复，随后定向复核新00/08，未发现新增具体P1/P2文档矛盾。7工作包/64T/6R是静态覆盖，F20设计修订与实现、测试、上线分别管理。I114/I115仅既有局部修复记录；I116源码条件反例继续OPEN，本轮未运行该浏览器反例或认证旧92等业务日志。
- 本轮源8篇/31引用锚点/3JSON/64T/F20检查通过；strict会话58810终态exit0增量无违规；diff无空白错误、三处既有LF/CRLF提示。09:26北京时间no-fetch巡检exit0（只本地快照，未核远端）：main0修改1既有未跟踪、自有91修改84未跟踪、无upstream。
- 文档交付范围已完成，整体产品实现和生产门禁不因此关闭；无金融回归、共享DB/迁移、真实建票/供应商/SMTP/COS、commit/push/merge或发布。后续产品目标与开放项维持原进度记录。本包verification.json只证明结构/hash/引用，包装核对不证明业务验收。

## 客户门户 v1.45 批次创建的当前授权、完整资金图与原键恢复（2026-10-06）

- 前轮按用户明确文档请求实际交付v1.44文档审查快照，补S02/P2目标错关联和D02/P2目标缺失验收歧义并独立复核，属于实际progress。本轮继续完整“按照开发文档与方案进行开发实现”goal，在自有codex/customer-portal-dev-docs实现POST /api/receipts/batches当前receipt:write/原全量或业务员财务范围；JWT仅身份。无commit/push/merge/生产发布或共享DB，完整goal保持active。
- 1.44前段484会话60169 terminal exit1：6failed45warnings37.23s，实际旧JWT停用/撤roles/撤write/撤scope和新增当前授权反例；485会话91225 exit0：6passed51warnings36.21s初步修订。486会话33579本轮重获真实终态exit0：44passed181warnings98.22s，原创建current授权/原键/图变化与技术证据范围；不是当时已完成预售/并发/提交故障全部证明。前段unit485会话8703 exit1：1failed122passed26warnings19.89s，余额guard顺序给手续费错误；已将余额/version守卫放在费用计算之前，不改原断言，最终独立123回归见下。
- 新batch_create_service捕获current永久authority→门户谱系→排序真实Invoice→原key Batch/全部成员；全Receipt/eligible Intent及全球JSON凭证占用、Allocation、Settlement、Application/相关Receipt、Receivable、Batch、完整Log与未绑定自有文件全字段冻结。第一commit释放后独立订单/类型、普通费列表与文件真实校验；两列表ID和数值必须相等，摘要保留原合法amount表示；结束token/cache第二commit，再新事务当前授权/全关联核验，纯本地financial应用由router第三commit。此调用不外发POST、不预占/出库。
- 原批次fingerprint仍排除request_key而包含balance_version，区别于单回款create；未知提交必须保留原完整body/key回查。原key先当前授权和实际原Batch全scope、actor/hash、实际子单集合/目标/结算结构，再回原当前state；不以新ready/余额/图文件/预售开关遮回执，不新建丢失原目标。首次预期目标absent合法，最终未变时原算法lazy创建。原费用/预售split最大余数平局货款、尾goods全余费、freight不占goods cap及waiting_target语义保留。
- 独立源审查S02形成I114/P2：同客户同币种A/B，goods key指A但invoice_id=B，旧capture从target反推检查而跳过；原key错stable key同样漏检。487会话21648 terminal exit1：2failed4passed39warnings36.28s，真实HTTP两项200，不是fixture。按请求key→expectedInvoice/kind/settlement及客户/币种/goods remote严格核实际target，replay核stable key；488会话40151 exit0：6passed39warnings35.27s初步对照。首非法capture与回放要求18类有限财务关联模型不变、无新增/重建，真实verify_storage探针拒绝0、阳性执行原helper1次，避免仅c.io无记录冒称零存储IO。
- 489会话52212 terminal exit0：68passed268warnings138.70s，44core+6targets+18races。包含3阶段×before/after同一真实Session的精确事件与phase2真实metadata UPDATE及独立持久核对；末commit已成功丢ACK保唯一Batch/两组件/正确fee/Log，原键回查零IO无重复。samekey双capture→相同原id；differentkey不同合法proof→仅一个批次和资金图，80每单合计160不能被凭证占用假绿替代。三真实Invoice等待由performance_schema观测，target当前SQL返回后after_cursor暂停，再外部已提交基线，防错误写进入baseline。7金额表示实际GET版本；fee IDs/同ID金额两个反例分开并刷新合法版本。
- 490会话67180 terminal exit1：6failed6passed42warnings47.91s，预售财务阳性body夹具对实际GET已含组合version再次digest，导致余额冲突，不是产品反例。只改直接使用实际GET组合version/settlement_id，原货款/运费/fee/assertion保持。491会话52464 exit1：3failed13passed61warnings52.00s，financial合法对照通过；新增真实成功后原Settlement删除、同客改Invoice归属、App.component改freight仍200形成I115/P2。replay current按Settlement→App→Target核存在/归属/组件，保持正确paused/shipped/released/featureOFF历史200，不加新单state/ready/费用限制。
- 492会话26108 terminal exit0：88passed323warnings171.84s，68+20presale为当时整套；新增4围栏尚未收集于492，不将其冒称92。493会话41648实际terminal exit0：92passed343warnings178.88s，为最终44core+6targets+22races+20presale。4项真实ON/OFF业务第三before_commit（已flush新增）先持永久barrier，实际admin disabled请求独立Session由performance_schema确认等待；commit或rollback后才完成管理员，原合法资金图或全18财务无写，之后旧token连原key也403无IO。最终source与tests在493启动后未再修改。
- 20presale实际HTTP与真实GET组合version核partial/full(70含50goods+20freight且goods cap50)、分币tie、最后goods余费、Deposit不重扣、历史goods应用、6错误Settlement/freight关联和4原回放结构拒绝/4状态阳性。feature策略为隔离Settings实际绑定，quote和provider事实合成；不是实际quoteAPI/真实全预售流程。薄上游表只复制Batch.request_key/Receipt.request_key/Receivable.business_key三唯一索引，不是完整FK/历史迁移。
- SQLite-only/MySQL socket与实际HTTP守卫：unit489会话24789 exit0：123passed26warnings21.78s；presale489会话29056 exit0：47passed7.87s。最终replay修订后unit492会话89152 exit0：123passed26warnings21.31s。47依赖的settlement current optional源码其后未改，按影响不重复；92/123/47各自范围，不累计为全产品验收。343warnings既有jose/Pydantic/Starlette等，无关依赖未改。
- 独立源/目标/竞态/20预售/4最终围栏审查无新增具体产品P1/P2/假绿；指出文件观测缺口已补真实helper探针，并明确合法absence及历史状态回查。审查者只读不代跑或认证日志，主线程核每个Session终态。本轮八篇/API/MySQLREADME及79源码hash清单同步，F20/64T/7W/R01–R06保留；v1.44交付快照按hash冻结，不改写当时S02开放状态。当前92为局部批次创建，不是全I81/所有写入口。
- I116/P2 OPEN：源查既有BatchReceiptDialog提交不明后解锁、允许编辑/刷新/关闭；关闭丢原body/key，重开新键。后端原key能力不替代前端恢复；本轮UI未修改/未重build或运行该反例，下一步冻结原请求和未知态，建立合法核对流程。其他register_shipment_payment/自动ReceiptIntent与投递绑定、shipment/worker/raw SQL与未注册writer、初始OFF旧执行器、未持久sender/私有上传残留、I77全生产启动、I92/I79/C05旧bytes/依赖/config/allwriters合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID单活无重复、历史迁移126失败、真实provider/SMTP/COS/B01–B07保持OPEN；安全本地工作仍可继续，不标complete/blocked。
- 79source hash/74AST、8文档31links/3JSON/64T/F20通过；strict会话72085 terminal exit0增量无违规；diff无错误仅三既有LF/CRLF提示。09:12北京时间no-fetch巡检exit0：main0修改1既有未跟踪，自有91修改84未跟踪、无upstream；本地快照未核远端最新。收尾handoff后再静态/约定复核，结果下补。
- 484–493十个独立MySQL8.0.46实际scope/datadir/Shutdown complete及提权CIM无匹配进程核验。34精确scratch目录检查，33存在已删（presale489无basetemp目录），14一次性writers已删。runtime.json/mysql.log全部成功失败日志、固定runtime及可复用checker/unitrunner保留；portal-v145-cleanup.json为清理回执。未改ACL、他人目录或frontend/undefined；本handoff/清理writer会在完成后精确删除并补回执。无live测试进程，下一实际MySQL494。

- 收尾复核79hash/74AST及8文档31引用/3JSON/64T/F20通过；strict会话42953 terminal exit0增量无违规；diff无错误仍仅三处既有换行提示。独立v1.45文档/新增handoff对照无新增具体P1/P2或过度闭环，审查者未认证日志/清理。最后仅交接和清理回执文字变化，source/tests自493启动未再改。handoff、cleanup与收尾三个一次性writer精确删除由portal-v145-cleanup.json的finish_writers_removed核对；不改旧交付包。

## 客户门户 v1.43 批次读取和本地整批作废的实时授权（2026-10-06）

- 前轮开发文档交付完成D01/P2授权时点矛盾修订及独立复核，属于实际progress；本轮继续完整开发goal，在自有codex/customer-portal-dev-docs接入GET /api/receipts/batches/{id}与POST同路径/void-entry。JWT仅身份；GET首业务DB当前receipt:read/write/admin原OR及全批scope，无响应前重鉴权承诺。写当前receipt:admin、force永久authority→谱系→排序Invoice→Batch→全部Receipt，定位/当前锁读完整(id,invoice_id)成员必须一致，原receipt:read_all只为范围，invoice全量不替代。不是batch create或所有writer已迁移。
- 479会话2485 terminal exit1：12failed/66warnings47.05s。真实main/JWT/管理员/MySQL停用/撤角色/撤动作后旧token仍200读或void，撤全量/super后跨范围仍200，当前新grant旧无动作token反而403；实际I81/P1局部反例，不是fixture失败。480会话64575 terminal exit0：12passed/66warnings46.06s，为初步授权对照；481会话95500 terminal exit0：47passed/143warnings107.16s，为扩展中间范围，不能合计历史数量。
- local_batch独立批次identity，不用第一子单替代批次目标。_void_financial排序current FOR UPDATE全部Application、去重Settlement和完整ReceiptLog，先全批验证再apply。结算必须存在并与child Invoice同归属；任何late_result阻止作废，保留I109已持久事实保护。旧sender可能只追加日志，不改Receipt/version；这些坏关联/事实是source反例，本轮未运行旧source复现，不冒称旧runtime红。未持久在途sender窗口继续OPEN。
- 原Batch active/version、无远端ID/任何现存lease、pending/failed/waiting_target、应用非applied及结算awaiting_payment/awaiting_verification/paused保持。released应用不过滤，paused仍paused，原每应用结算version递增保持。金额/手续费/图/原ID不写，不退款、不加PI ready/发送条件。原金融unit两断言转私有算法helper保留，不作授权证明；公开void_entry仅接受identity并进入authority，引用已查。GET及void本批无provider/storage IO，不制造取证commit。
- 482会话24624 terminal exit0：57passed/177warnings126.35s。真实隔离随机loopback/口令MySQL8.0.46、main/MCP/ASGI/JWT/admin及portalDDL；上游Receipt/Batch/Application/Settlement等薄合成schema，seed/jobs/挂载受控，真实HTTPtransport禁止、无.env。不是完整历史FK迁移、真实provider/SMTP/COS/所有writer/物理故障或进程切换证明。177 warnings为既有jose/Pydantic/Starlette等，无关依赖未改。
- 57含12current auth/scope/newgrant、13原金融/坏关联/late_result guard、6原合法状态、6动作范围、5真实Invoice wait current图、2实际ON/OFF撤权先提交、2精确同Session before/after_commit、1双void、6查询SQL故障恢复、4真实HTTP ON/OFF业务commit/rollback先于管理员。17有限金融/关联模型全字段快照，不是全DB/auth/token/cache/SQL；4业务先提交/回滚另核目标字段，不扩为全17模型。performance_schema实际观察Invoice或authority等待，不用sleep冒充竞争。
- 独立审查指出5等待测试在other.commit后才拍基线，目标错误写可能进入baseline而假绿；这是P2证据时序，不是产品运行缺陷。已加目标同connection Invoice FOR UPDATE返回后的after_cursor门，暂停目标→拍外部已提交基线→确认目标未结束→放行；finally释放门/移除两事件。483会话72623 terminal exit0：5passed/52deselected/28warnings34.03s。产品逻辑未因该证据修订改变，其他52不变；不能称57为门控修订后整套，也不合计62。独立源码复核确认该假绿路径消除，未代跑或认证日志。
- unit481会话11677 terminal exit0：123passed/26warnings19.89s，原回款管理/批次/截图导入，SQLite-only、PyMySQL与实际HTTP守卫、无.env。57/修订5/123分别报告，不累加。提交after_commit注入后独立核原批次voided/version2和每子单一日志；GET零金融写，旧version409，不宣称无命令键自动幂等回放；before_commit无变更且合法恢复。SQLA固定503/private,no-store先核原批次，原execute IntegrityError409/TransactionBusy保持；事件不是物理断网/DB故障。
- 独立金融设计/源/57规格无新增具体产品P1/P2；给出已持久事实、完整结算归属及证据门控补强。独立v1.43文档对照同样无新增具体P1/P2或过度闭环，审查者只读不认证日志；八篇/API/MySQLREADME及发现快照同步。F20/64T/7W/R01–R06保持；旧交付v1.41/v1.42包按原hash冻结，不覆盖为当前版本。收尾只去掉router现已无用ReceiptBatch和重复局部import，不改变行为，静态/check复核。
- 73源码hash/68AST、8文档/31引用锚点/3JSON/64T/F20已通过；strict会话20378 exit0增量无违规；diff无错误，仅三处既有LF/CRLF提示。最终收尾与handoff文字后再复核，下项记录实际结果。UI本批未改，不重build。
- MySQL479至483实际scope/8.0.46/datadir/Shutdown complete及提权CIM无相应mysqld已核。16精确scratch目录均存在并已删，6一次性writers已删；runtime.json/mysql.log/成功失败日志、固定runtimes及可复用checker/unit入口保留，portal-v143-cleanup.json记录实际。交接/收尾writer已另行精确删除，finish_writer_removed=true记入清理回执；不改ACL或他人目录/frontend/undefined。
- 收尾strict会话47644 terminal exit0增量无违规；无用导入清理后73hash/68AST、8文档31引用/3JSON/64T/F20复核通过，diff无错误仅三处既有换行提示。08:28北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有90修改/83未跟踪、无upstream，只为本地快照，未核远端最新。独立审查最终仅核新增handoff未发现P1/P2/过度声明，指出旧v1.42标题错位；已恢复新v1.43先、旧v1.42紧接其正文，不混批次证据。审查者未认证日志/终态或清理，实际由主线程核验。
- 无commit/push/merge/部署、生产DB/迁移、真实供应商/SMTP/COS或prepare/publish/finalize；main源未改。批次create、自动/投递绑定、其余shipment/worker/rawSQL及未注册upstreamwriter、初始OFF旧执行器、未持久sender与私有上传残留收敛，I77全生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter及合法恢复、I78真实systemd/cgroup/Node整切换、I80现场all-success/PID/单活/不重复外发、历史迁移126失败、真实服务/B01–B07继续OPEN。安全本地工作可继续，完整goal保持active，不标complete/blocked；下一MySQL484，优先批次创建当前授权、锁外取证与完整最终关联。

## 客户门户 v1.42 远端回款变更的当前授权、全索引与最终重验（2026-10-06）

- 上轮按用户要求实际交付详细文档快照/指南和两路独立审查，属于progress；本轮继续原完整开发goal，在自有codex/customer-portal-dev-docs实现GET/POST remote-change。预览首业务读重建当前receipt:admin、原财务范围和原整批读取权限，普通read不持业务锁跨IO、不承诺响应时撤权。确认两次current完整group，全部成员scope先于batch/presale守卫；冻结原Receipt remoteID/order/currency/before/version及完整Receipt/Invoice/Batch/children/current日志，显式commit放锁GET，再结束token/cache事务，最后current/fullbinding先于纯商业evidence/hash及原金融apply，caller最终同事务提交原版本/remote_change日志。
- 原金额net+本地fee、零远端fee/实到/日期/status、synced/uncertain、非ready/低总额合法保持；无新增ready/余额限制。删除仅remote_deleted，原ID/PNG/金额费用保留，明确不等于退款。不外部POST，不改PI商业版本/Publication。原public evidence/accept签名查引用后替代，SQLite单元显式调用隔离私有金融算法，原断言保持；无skipflag/fallback/旧签名兼容。实际UI请求/按钮未变，不重build或宣称新浏览器验证。
- 472会话56355 terminal exit1：18failed/84warnings58.03s。实际main/JWT/admin/MySQL旧JWT在停用/撤role/admin、撤receipt全量/super_admin和当前新grant反例，错误200或旧claim拒新grant，非fixture错误。473会话40180 exit1：2failed/18deselected/23warnings29.95s，detail缺失但完整索引原ID改关联，旧按order过滤的preview/confirm错误200，confirm实际remote_deleted；I111/P1。修复使用完整receipt_index.verified_rows按原ID核任何order存在，不按原order过滤；坏索引固定503，存在原ID409，真正无ID才删除。
- 474会话56590 exit0：初20passed/89warnings59.91s，仅首授权/全索引范围。475会话32740 exit0：88passed/317warnings183.83s，中间金融/并发/三commit范围，不含后续组合/形状/实际开关绑定。476会话45973 exit1：4failed/90deselected/34warnings35.36s，初分阶段pure_evidence在final current前，实际门控GET期间撤权/撤范围并有合法结构的EUR/原ID仍存在，先409遮住403/404；I112/P2。已改final current/group/fullbinding优先，后pure商业evidence。
- I113/P2为源级发现：bool属于int及空串order可被复用_record当可信关联；没有声称旧分支运行红测。本入口_order明确拒bool/空/空白/非标量（整数需正），detail及完整index新增8shape对照。已知原ID缺关联仅足以拒删除，不能证明不存在。旧source注释Token refresh can commit过时：当前okki_client.ensure_access_token自身只更新settings，由callercommit；不能用该注释证明旧入口自然释放锁。本批真实取证竞争来自显式capture commit，前轮交付08已纠正S02条件反例口径。
- 477会话76109 terminal exit0：108passed/391warnings220.42s。实际随机loopback/口令MySQL8.0.46、main/MCP/ASGI/JWT/admin及portalDDL；上游Receipt/Batch/Allocation/结算薄合成schema，provider detail/global-index/token/proxy/cloud受控，实际HTTPtransport禁止、无.env。非108全生产入口/完整历史FK迁移或真实provider/index/SMTP/COS/物理故障与进程恢复证明。warnings为既有jose/Pydantic/Starlette等提示，未改无关依赖。
- 477当时ON/OFF仅改main Settings，独立审查指出portal.authority已import的get_settings未绑定新对象。其后仅修两个test的精确upstream get_settings并assert PORTAL_ENABLED（没有产品源变更，其他94项不变）。478会话36696 terminal exit0：14passed/94deselected/76warnings51.96s，12锁外撤权＋2业务先commit的实际ON/OFF绑定复验。不能相加为122、不能称108为绑定修订后整套。测试初次误写ORDER_PORTAL_ENABLED已在477前修为真实字段，477后模块绑定进一步收窄证据，无放宽断言。
- SQLite生命周期首次unit475 exit0：34passed/1warning5.49s；修订后加入持久index，最终unit477 exit0：51passed/1warning6.15s（34lifecycle+17index），SQLite-only/PyMySQL/实际HTTP禁用、无.env。原净额0+localfee等合法金融counterexample保持。108、14、51各自范围，不与历史/中间数相加作整体验收。
- 108含18当前auth、2跨orderID、12实际开关/慢GET撤权、20完整绑定、9原状态与batch scope、4原金融/旧body、20详情技术与商业证据、8完整index shape、8双capture/三commit、1真实Invoice等待current日志及6finalauth/业务先提交。15有限模型全字段财务/关联快照，不是全DB/auth/token/cache/SQL零写。六commit故障必须同一实际Session/精确阶段命中，provider阶段真实metadata UPDATE并独立核持久结果；final已commit丢ack独立核amount8/fee2/version2/一审计，GET原单零取证或金融写，旧version409不重复。未commit且仍合法才人工再做；两个confirm无稳定命令键，不宣称自动幂等回放。真实performance_schema观察Invoice等待后只追加late_result日志，被final current读拒绝，非sleep模拟。
- 独立金融源审发现global index、最终顺序、bool/空shape和Settings绑定，修订后源级/定向用例无新增具体产品P1/P2或弱断言；独立v1.42文档对照108分组、两current/fullscope、hash/global index、callercommit及OPEN边界无新增P1/P2或过度声明。审查者未运行测试或认证日志，实际终态由主线程确认。八篇/API/MySQLREADME与72hash清单同步，65AST/8文档/31链接锚点/3JSON/64T/F20通过；F20/64T/7W/R01–R06保持。
- strict会话12933 terminal exit0增量无违规；diff无错误，仅四处既有LF/CRLF提示。no-fetch巡检exit0：main0修改/1既有未跟踪，自有88修改/83未跟踪、无upstream；只是本地快照未核远端最新。产品源自477启动后未变，只有14项Settings夹具绑定及文档/清单变化，不因这些改动重复无关全套。后续新增handoff文字再静态/diff核对。
- owned MySQL472–478的scope/version8.0.46/实际datadir及Shutdown complete已核，提权CIM确认无相应mysqld；受限CIM首读拒绝不当作进程终止证据。23精确scratch目录目标核验、22存在目录删除（首次lifecycle无tmp_path则base原不存在），8一次性writers删除。保留runtime.json/mysql.log/所有成功失败日志、固定runtime与可复用checker/unit脚本，portal-v142-cleanup.json记录实际，不改ACL/他人目录/frontend/undefined；handoff writer收尾单独删除并记回执。
- 无commit/push/merge/部署、生产DB/迁移、真实供应商/SMTP/COS或prepare/publish/finalize，main源未改。自动/投递绑定、batch/worker/rawSQL与未注册upstreamwriter、初始OFF旧执行器、尚未持久sender和私有上传残留收敛，I77全生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter及合法恢复、I78真实systemd/cgroup/Node整切换、I80现场all-success/PID/单活/不重复外发、全历史迁移126失败、真实服务/B01–B07仍OPEN。安全本地工作可继续，完整goal保持active，不标complete/blocked；下一MySQL479，继续其他回款绑定和batch/worker当前授权协议。

## 客户门户 v1.41 回款核对与人工处理的当前权限、锁外证据及迟到结果（2026-10-06）

- 上轮1.40为实际progress，本轮继续完整开发goal接入POST reconcile/resolve。自有codex/customer-portal-dev-docs中JWT仅身份，两阶段当前reconcile receipt:write OR receipt:admin、resolve receipt:admin及整个批次原receipt范围；invoice:read_all不替代。authority.local_group接受显式动作与OR参数，原retry/edit/proof默认write保持；未改变原主体和范围算法。全部goal及剩余writer不因本批缩小。
- capture：永久authority/谱系/排序Invoice/Batch/Receipt，再current FOR UPDATE读完整相关ReceiptLog；冻结全Receipt/Invoice/Batch/children/logs及独立RemoteTarget。无商业写首commit放锁→只读原Receipt订单或详情ID，冻结不可变标量→第二commit仅结束provider token事务，磁盘索引缓存不是DB商业事务→final新事务按同序当前权限/全批范围/完整目标与日志重验→原本地金融应用和审计最后callercommit。不持业务锁跨供应商GET，不发送POST；原gross/net候选、无自动绑定、net/零远端手续费/real amount/原订单/币种/日期及collect_status规则保持，不新增ready/余额限制。原已知ID不可改绑，bind_remote的他行唯一关联改当前锁读并保留原DB唯一约束。旧sync_service公开reconcile/resolve已查全引用并迁私有_reconcile/_resolve；原SQLite金融assert显式helper保留，无废弃兼容层。
- 467会话39128 terminal exit1：18failed/72warnings57.72s，实际main/JWT/admin/MySQL旧claims在停用/撤roles/撤动作、撤全量/super_admin后仍可核对或人工处理，当前新增grant反而403；为I81/P1恢复局部实际反例，没有fixture错误。468会话31706 exit0：18passed/72warnings57.02s为初步授权验证；469会话91878 exit0：83passed/225warnings171.64s，是I110候选验证修订前的中间范围，不能覆盖后来新增12项或冒称当前终态。
- I109/P1为独立source时序风险：原sender被fence拒绝覆盖后可只追加late_result，不改Receipt字段。旧字段绑定可能忽略原远端已创建事实而改pending。当前初始/最终完整current日志集合，已存在late_result拒绝确认未创建，期间仅追加日志亦409；真实独立提交保持，新增两次RR授权快照→Invoice等待→current日志对照。没有运行旧源码复现此P1，不虚称旧runtime红；也不宣称原POST在途且尚未持久化结果窗口已消除，该sender/fact生命周期仍OPEN。
- I110/P1为独立source候选风险：远端索引只验证update_time，初稿reader仅核collection_date为str；坏日期被candidate_matches过滤为不匹配，可能误confirm_not_created。现日期前十位真实日历+canonical roundtrip、非空/trim/长度合法币种前置，六坏日期/币种固定503/no-store保持uncertain；合法不同日期及合法datetime/已生效status阳性保留。没有声称旧源码实际红测；469中间83不含该修复后的12项。provider详情/候选形状、ID、重复ID及数值失败也固定503，无旧缓存降级或未知当不存在。
- 470会话40979 terminal exit1：3failed/381passed/987warnings708.32s。新真实远端ID唯一约束暴露旧共享夹具固定998/999重复：proofs合法uncertain/notready两项及PATCH原remote_id守卫一项在准备DB时IntegrityError，未到产品断言；没有恢复产品失败。三处改按原Receipt.id生成独立ID，保留唯一索引和原money_state/状态拒绝/零写断言，不删测试或弱化约束。
- 最终471会话92988 terminal exit0：384 passed, 990 warnings in 708.43s，95recovery+64create+29upload+39proof+61PATCH+45retry+17read+34authority。真实随机loopback/口令MySQL8.0.46、main/MCP/ASGI/JWT/admin及portalDDL；上游Receipt/Batch/Allocation/结算薄合成schema，本批仅复制xiaoman_receipt_id唯一索引，不证明全历史FK/迁移。seed/jobs/挂载受控，provider/token/index/proxy/cloud替身，实际HTTP transport禁止、无.env；不是384全生产入口或真实供应商/存储/物理故障/进程恢复证明。warnings为既有依赖提示，未改无关库。
- SQLite upload-unit468会话93088 terminal exit0：123passed/26warnings20.88s，原财务/批次/截图导入金融规则在共享bind_remote与私有应用迁移后通过；I110随后仅新增恢复reader及专项，不改该金融算法。预售470会话53923 exit0：47passed8.24s。SQLite-only/PyMySQL/HTTP守卫、无.env，真实当前员工与围栏由MySQL单独覆盖；384/123/47各自范围，不与历史/中间数相加作整体验收。三夹具失败按实际原因修复，无删断言换绿。
- 95项包括18当前JWT/范围/newgrant，原状态/动作OR/完整批次、原Receipt目标及非ready/低余额合法、gross/net无自动绑定、精确原净额证据、锁外真实admin先提交后拒绝、目标/PI/归属/批次/金额/远端ID变化、late_result初始和期间只追加、两个真实performance_schema等待的current日志读取、六同Session三commit故障、三双capture只一应用、坏形状/日期/币种及合法日期对照和唯一绑定。15有限模型全字段业务/关联快照，不是全auth/audit/token/SQL/DB零写。metadata真实UPDATE并独立持久核验，事件必须实际请求Session精确阶段命中；非物理断网/真实数据库故障。
- final已提交丢ack独立核synced/version2/唯一原ID、reconciled+bind_receipt两条原审计；GET核对不写或新增取证，已完成resolve重复409，未提交且仍合法才人工重做。两个接口无稳定命令键，未知结果503/no-store要求先刷新原单核对，不宣称自动回放/幂等；reconcile再次合法调用仍可能增版本，不把新并发200/409证明扩大为所有重试唯一应用。
- 独立金融source/95规格及I110定向复核无新增具体P1/P2或弱断言；独立文档v1.41对照权限/状态/目标/日志/日期/95分组同样无新增具体P1/P2或过度闭环。最初审查时470 live，审查者未运行或认证日志，当前终态由主线程确认；三处唯一ID夹具修订单独定向核对，后续只审新增handoff文字，不重复源审。八篇/API/MySQLREADME与69hash清单同步，F20/64T/7W/R01–R06保持。UI本批未改；只读核既有按钮OR/admin声明与本轮规则一致，不重build或宣称新浏览器验收。
- 69源码hash/60AST、8文档/31本地链接锚点/3JSON/64T/F20通过；strict初会话46118及最终定向检查terminal exit0增量无违规，diff无错误，仅四处既有LF/CRLF提示。471运行的业务逻辑及全部测试至收尾未变；终态后仅删router两处已无调用的import并澄清索引缓存注释，AST核对仅import别名有预期差异、其余AST相同（portal-v141-import-clean.json），不重复整套测试。终态新增handoff文字后静态/diff再核。07:04北京时间no-fetch巡检exit0：main0修改/1既有未跟踪、自有87修改/83未跟踪、无upstream；仅本地快照，未核远端最新。
- owned MySQL467–471的isolated scope/8.0.46/实际datadir及Shutdown complete已核，CIM无对应mysqld；17精确临时目录目标核验，16存在目录已删，presale固定base原不存在；6一次性源/test/docs/夹具 writers已精确删除，交接writer也已精确删除。保留runtime.json/mysql.log/所有成功失败日志、固定runtime及可复用checker/unit入口，portal-v141-cleanup.json记录实际清理，不改ACL或清理他人/frontend/undefined。
- 无commit/push/merge/部署、生产DB/迁移、真实供应商/SMTP/COS或prepare/publish/finalize，main源未改。未完成remote-change/自动与投递绑定/batch/worker/rawSQL及未注册upstream writer、初始OFF旧执行器、在途尚未持久sender结果和私有上传残留收敛；I77全生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter及合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID/单活/不重复外发、全历史迁移126失败、真实服务/B01–B07仍OPEN。安全本地可继续，完整goal保持active，不标complete/blocked；下一实际MySQL472，继续remote-change当前权限/证据和审计事务边界。

- 最终独立复核仅核新增handoff：实际旧JWT18红、I109/I110 source风险与中间83范围、470三准备阶段夹具冲突、471联合384及独立123/47、15有限模型/三提交/未知结果GET核对、17目标16删除6一次性writers与全部OPEN门禁无新增具体P1/P2或过度声明。审查者未运行测试或认证日志/清理回执；其后只同步交接writer实际删除和最终约定检查，源码业务AST与测试未变。strict收尾会话83813终态结果由主线程确认，最终hash/AST/文档/diff再核。

## 客户门户 v1.40 手工回款创建的当前权限、原键回放与锁外证据（2026-10-06）

- 上轮1.39为实际progress；本轮继续完整开发goal，在自有codex/customer-portal-dev-docs迁移POST /api/receipts。JWT仅身份，两阶段current receipt:write及原财务scope；invoice全量读不替代receipt范围。先按request_key实际PI授权，再核真实invoice_id、actor及body hash，balance_version排除出原hash；跨域实际单404先于键冲突409。既有原键回放先于ready/余额/文件IO，void/synced/notready或旧余额版本仍按原回执，不新增日志；最终同键已提交也先回放。源码与完整goal范围不因本批缩小。
- 新单当前Receipt→Intent及Allocation锁读，自动eligible Intent的draft/armed/ready截图显式占图守卫；冻结全Invoice摘要、独立OrderTarget及AttachmentBinding。capture commit释放业务锁，锁外订单/文件取证，第二commit仅结束token/cache；final fresh authority及当前scope/完整目标/当前账本与附件重验，原ready/预售/paytype/余额版本与可用额度规则保持。私有_make_row复用原构造，自动new_row保留原完整验证；手工_create用已验证附件关联，回款/截图/一条created日志最后同事务。原手工bank_charge保持，不套自动分摊；成功本地active/pending，不在此调用发供应商或改变PI版本。旧service.create公开签名已查引用并替代，无任意skipflag。
- 459会话53921 exit1：6failed/39warnings36.09s。真实主应用旧JWT在停用/撤role/撤write、撤全量/super_admin及当前新增grant下表现错误，为既有I81/P1创建子项反例，无fixture错误。460会话62383 exit0：6passed/48warnings35.90s仅初步范围。461无持续session，exit1：57setup errors/1warning0.44s，批量替换误成create_app(create_app)循环夹具；未启动MySQL，两个临时目录不存在。修为create_app(read_app)，不删断言。462会话21132 exit1：1failed/56passed/172warnings130.12s；异键并发误用Intent已占截图，第二方capture409而第一方BrokenBarrier。改用第二张真实独立未绑定合法PNG与metadata，仍要求两方capture、200/409及唯一行/日志。
- I108/P2：共享edit_service._evidence曾将原amount转Decimal后freeze，GET摘要仍用原文本，合法正号/前导零/指数表示可误409。463会话95618 exit0：常见7、数值7、7.0、7.00四项通过（4passed/57deselected/26warnings34.23s），不能说这些复现错误。464会话4513 exit1：新增+7、007.0、7e0三项实际失败（3failed/4passed/57deselected/32warnings36.93s）。现先remote.money校验有限/非负/精度，再freeze原str；未放宽数值约束或改变GET版本算法。该reader共享PATCH，联合回归包含其61项。
- 最终465会话19891 exit0：64passed/186warnings129.36s。最终466会话2583 exit0：289 passed, 759 warnings in 516.99s，64create+29upload+39proof+61PATCH+45retry+17read+34authority。真实随机loopback/口令MySQL8.0.46、main/MCP/ASGI/JWT/admin及portalDDL；上游Receipt/Batch/Allocation/结算薄合成schema，create夹具补实际request_key唯一索引，不证明全历史FK/迁移。seed/jobs/挂载受控，provider/token/proxy/cloud替身，实际HTTP transport禁止，无.env。不是289全生产入口、全历史schema、真实供应商/存储或物理故障证明；warnings为既有依赖提示。
- SQLite upload-unit460会话69779 exit1：1failed/122passed/26warnings20.28s，财务身份替身缺receipt:write动作门，原403断言得到200；替身补动作门，原断言保持。461会话8448 exit0：123passed/26warnings19.75s。最终unit465会话13868 exit0：123passed/26warnings21.34s；预售466会话23160 exit0：47passed7.83s。SQLite-only/PyMySQL/HTTP守卫、无.env，真实current employee与屏障由MySQL单独验证；289/123/47各自范围，不与中间/历史数量相加为整体验收。
- 64创建项覆盖当前撤权/新增grant、隐藏实际key目标及伪造同hash错目标、原键无IO回放、Intent/Allocation/图片归属初始守卫、锁外订单IO期间真实admin可先提交后final403、归属/PI/账本/Intent/文件/Batch/key变化拒绝。三次RR旧快照→Invoice真实等待→独立Receipt/Intent/Allocation提交必须由performance_schema观察锁等待；不是sleep假竞争。15有限模型全字段业务/关联快照，不是全auth/audit/token/SQL或全库零写。7种amount表示用真实GET余额摘要再创建，不用替身常量伪造版本。
- 六capture/token/final before/after_commit必须同一实际Session且精确阶段命中；锁外阶段真实metadata UPDATE、独立核持久结果。final已提交丢回执保留唯一原键、手工费用2、pending及关联图/一条日志；原键恢复零IO不新增，未提交失败沿原键合法恢复。固定503/no-store要求原键核对，禁止换键盲重发；事件不等于物理断网/数据库故障。原execute的IntegrityError409/TransactionBusy处理保持。
- 独立金融源与64用例定向审查指出实际目标校验、Intent占图、最终同键优先回放和表示区分；修订后未发现新增具体P1/P2或弱断言。独立v1.40文档对照同样无新增具体P1/P2/过度闭环；审查当时466 live，不代跑或认证日志，终态由主线程确认。八篇/API/MySQL说明与68hash清单同步，F20/64T/7W/R01–R06不增加；后续仅核新增handoff文字。
- 68源码hash/57AST、8文档/31本地引用锚点/3JSON/64T/F20通过；strict初82074及终73892 exit0增量无违规，diff无错误，四处既有LF/CRLF换行提示。源/test自466启动后未再改；最终handoff文字后静态/diff复核。UI本批未改不重build。06:35北京时间no-fetch巡检exit0：main0修改/1既有未跟踪、自有86修改/82未跟踪、无upstream，只是本地快照，未核远端最新。
- owned MySQL459/460/462/463/464/465/466的scope、8.0.46、实际datadir及Shutdown complete已核，CIM无对应mysqld；461仅夹具setup失败、无runtime且目录原不存在。25精确目录目标核验，22存在目录已删，presale固定base按实际存在情况记录；4一次性源/test/docs writers已精确删除，交接writer也已精确删除。保留runtime.json/mysql.log/全部成功失败日志、固定runtime和可复用checker/unit入口，portal-v140-cleanup.json记录实际清理，不改ACL或清理他人/frontend/undefined。
- 无commit/push/merge/部署、生产DB/迁移、真实供应商/SMTP/COS或prepare/publish/finalize；main源未改。未完成其他自动/投递绑定、remote-change/reconcile/resolve/batch/worker/rawSQL及未注册upstream writer、初始OFF旧执行器；I77全生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter及合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID/单活/不重复外发、全历史迁移126失败、真实供应商/SMTP/COS/B01–B07、私有上传残留收敛继续OPEN。安全本地可推进，完整goal保持active，不标complete/blocked；下一实际MySQL467，优先继续reconcile/resolve当前权限与事务边界。

- 最终独立审查仅核新增handoff文字：原键回放与当前授权、I108实际表示边界、289与独立123/47终态、15有限模型及三提交、25/22临时目录和4一次性writers、其余OPEN门禁无新增具体P1/P2或过度闭环。审查者未运行测试或认证日志/清理回执。其后仅补交接writer实际删除记录，源/test未变；最终静态与diff复核结果由主线程确认。

## 客户门户 v1.39 私有凭证上传的当前权限与最终注册围栏（2026-10-06）

- 上轮1.38是实际progress，完成文档复核/临时环境清理；本轮继续完整开发goal迁移POST /api/receipts/attachments。JWT仅身份，当前receipt:write或invoice:write原OR两阶段校验，super_admin只按当前DB角色，未绑定上传不套订单财务scope。成功只注册当前主体的未绑定ReceiptAttachment，不改Receipt/Intent/金额/日志/队列/PI版本或外发供应商。其他writer与现场门禁不缩范围。
- 454会话4672 terminal exit1：5failed/30warnings34.92s。真实主应用JWT及管理员变更后，停用/撤roles/撤write旧令牌仍200注册，当前新增receipt:write/invoice:write旧令牌反而403，是既有I81/P1上传局部反例，无fixture错误。455会话21854 terminal exit0：初步5passed/30warnings34.05s，不充当完整边界验收。
- 新upload_service在新事务永久authority屏障及current OR授权后首commit释放，再proxy/图片/存储IO；本地冻结UploadData和StoredUpload，存储不接Session。PNG/JPEG/WebP、4000万像素/10MB、文件名255/MIME/SHA256规则保持；本地随机键create-only，COS复用缓存预算/TemporaryDirectory/put_file，托管暂停或云失败不fallback本地。实际本地绝对路径或原COS实例(bucket/prefix/client)冻结供注册前清理。
- 最终fresh屏障和current OR重验，持到register/flush/callercommit。明确拒绝且注册未开始：先rollback再删除本次冻结对象；清理或诊断失败不覆盖原拒绝，保留私有残留待核对。register/flush/commit不明保留图，固定503/private,no-store，不删除可能已注册文件或盲目重传。存储失败可能留私有残留；未实现通用残留收敛任务，无原上传幂等键，不能声称重复上传唯一资源/自动恢复。原execute成功处理IntegrityError409保持。
- proxy只发一次POST，源首鉴权不替代canonical最终当前鉴权，目标必须实际部署相同协议。目标可能已commit后源丢回应只503/no-store，不本地fallback/二次POST。受控transport确实通过真实forward并实际执行相同ASGI目标入口，HOP目标本地存储条件由夹具模拟；不证明真实跨部署目标版本/COS删除/网络或进程宕机恢复。
- 456会话93563 terminal exit1：2failed/27passed/75warnings75.90s，两个proxy用例误捕获read_app已替换的forward、未到目标。修为模块装载保存REAL_FORWARD并断言唯一目标URL/实际receiver状态与行，未弱断言。457会话30959 terminal exit0：29passed/78warnings74.15s，完成该定向范围。
- 新扩大SQLite套件456会话52062 exit1：1failed/122passed/26warnings21.17s，旧批次对象权限用例仅假JWT缺当前员工，403未到原404对象守卫；补真实ArkUser/Role/Permission与关联，457会话53608 exit1：同1failed/122passed/26warnings21.50s因首补漏real_name必填。已补必填，原404断言和全部财务断言保持，非产品缺陷/删测换绿。
- 最终458会话81851 terminal exit0：225passed/591warnings405.87s，29upload+39proof+61PATCH+45retry+17read+34authority。真实随机loopback/口令MySQL8.0.46、main/MCP/ASGI/JWT/admin及portalDDL；上游Receipt/Batch/Allocation/结算薄合成schema，seed/jobs/挂载受控，provider/token/proxy/cloud替身、实际HTTP transport禁止。非225全生产入口或全历史schema/真实服务/物理故障/全网络证明。
- SQLite上传/财务/批次/截图导入458会话55143 terminal exit0：123passed/26warnings19.50s；预售458会话3821 terminal exit0：47passed7.61s。SQLite/MySQL/HTTP守卫、无.env，非主应用身份全流程；225/123/47各自范围，不相加历史或作整体验收。warnings为既有Starlette/jose/Pydantic等，无关依赖未改。
- 29项包括真实先撤权/OR新grant、6本地/受控云存储门控撤权可先提交后final403零注册、冻结位置清理及失败保持拒绝；原格式/名称/摘要/私有对象404和非法图413/409；四capture/final before/after_commit精确同Session命中。最终after_commit丢回执独立查唯一该ID已注册行/原图；before_commit无行但保图待核对。after_flush Session标记避免弱identity-map假门控，performance_schema实际观察管理员等待最终注册屏障：先上传commit再撤权，下一请求403。有限15模型业务/关联快照不是全auth/audit/token/全库零写；事件不是物理数据库故障。
- 独立金融设计/源/29用例审查及夹具定向复核未发现新增具体P1/P2或关键假阳性；独立文档1.39定向复核同样无新增具体P1/P2/过度闭环。审查当时458 live，审查者未跑/认证日志；当前终态主线程确认。新handoff定向只读核对也无新增具体P1/P2，未认证日志或清理回执；不重复源/规格审。README/03/04/06/07/API/MySQL说明与发现快照同步，F20/64T/7W/R01–R06不增加，原公开attachments.upload已全局查引用并分阶段替代。
- 67源码hash/55AST、8文档/31引用锚点/3JSON/64T/F20通过；strict初84230及终40667 exit0增量无违规，diff无错误，仅既有LF/CRLF提示。源/test自联合458启动后未再改，交接文字后67hash/55AST及8文档/31引用/3JSON/64T/F20复核通过，diff exit0，仅换行提示。UI本批未改，不重build。
- 06:07北京时间no-fetch巡检exit0：main0修改/1既有未跟踪、自有86修改/81未跟踪、无upstream，只是本地快照，未核远端最新。owned MySQL454–458各runtime scope/8.0.46/datadir及Shutdown complete已核，CIM无对应mysqld；17精确目录目标核验、16存在目录已删，presale固定base原不存在。6一次性writers已精确删除；保留runtime.json/mysql.log/全部成功失败日志、固定runtime、复用checker与原unit入口及新增portal-upload-unit-run.py。portal-v139-cleanup.json记录实际清理，不改ACL或清理他人/frontend/undefined。
- 无commit/push/merge/部署、生产DB/迁移、实际供应商/SMTP/COS或prepare/publish/finalize；main源未改。未完成create/其他上传绑定/remote-change/reconcile/resolve/batch/worker/rawSQL与未注册upstream writer、初始OFF旧执行器；I77全生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter与合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID/单活/不重复外发、全历史迁移126失败、真实供应商/SMTP/COS/B01–B07继续OPEN。安全本地可推进，完整goal继续active，不标complete/blocked，下一实际MySQL459，优先create当前授权/原幂等与锁外证据。

## 客户门户 v1.38 自动回款截图的当前权限与锁外文件（2026-10-06）

- 上轮1.37为实际progress，本轮继续完整开发goal迁移PUT attachments：JWT仅身份，两阶段local_group当前receipt:write/原财务scope与全批授权、当前converted Intent绑定、完整Receipt/Invoice/Intent与AttachmentBinding身份，文件IO锁外后最终再验。原service.change_proofs公开签名唯一router调用已淘汰为私有_change_proofs，原金额/费用/同步状态/远端ID/租约/token/attempts不写，不新增外发或PI版本变化。
- 452会话41065 terminal exit1，6failed/33warnings35.88s，真实主应用JWT/实际管理员变更后停用/撤role/撤write仍200换图/增版本日志，撤all/super_admin后他单200，旧无动作token当前新grant403。I81既有P1子项实际反例，无fixture错误；修订保持原scope，invoice全量不替代receipt范围。
- 截图guard只拒原manual/非active/batch/syncing/错version与非converted或错receipt_id Intent，synced/uncertain/非readyPI阳性不收紧；不能套PATCH ready/余额/手续费。capture当前group+Intent锁读后冻结全字段摘要及独立文件DTO，无商业变更首commit释放全部业务锁。文件阶段只有verify_storage、无provider/order/types/token/cache或虚构中间commit；清旧事务/ORM，final重入current group/Intent/fullbinding与bind_verified。原有效proxy skip-local保持，不是实际proxy/COS或本地bytes hash全检。
- 相同集合（排序不同）先合法性与文件验证，再no-op，不增Receipt版本/日志或改同步状态；真正替换只Receipt/Intent IDs同时写、Receipt version+1及一条proofs_updated。混合batch404先于合法batch409，原上传人/跨单/Batch/已移除图限制保持。最终提交不能确认只固定503/no-store要求回查原单，不回退/盲重发；已提交旧version409，当前version同集合验证后200不重复。原execute成功处理IntegrityError409、TransactionBusy保持。
- 453会话57266最终terminal exit0：196passed/531warnings352.60s，39proof＋61PATCH＋45retry＋17read＋34authority。真实随机loopback/口令MySQL8.0.46、main/MCP/ASGI/JWT/管理员路径及实际portalDDL；上游Receipt/Batch/Allocation/结算薄合成schema，seed/jobs/挂载受控，provider/token/proxy/cloud替身、实际HTTPtransport禁止。非196全生产入口、全历史schema、真实供应商/token刷新/COS/物理故障/全网络证明。
- unit453会话82140 terminal exit0：71passed/1warning12.64s；presale453会话79360 terminal exit0：47passed7.81s。原财务/converted截图与预售断言全保留，SQLite-only/PyMySQL/HTTP守卫、无.env，身份为子应用替身；196/71/47范围各自、不累加历史或作整体验收。531warnings为既有jose/Pydantic/Starlette/colour等，无关依赖本轮未改。
- 39项含真实撤权/新grant/全scope、八guard零文件/provider、原synced/uncertain/notready与财务执行字段保持、独立AttachmentBinding慢IO期间管理员可提交撤权后final403；Intent/worker/归属/金额/附件/Batch/key变化拒绝且15模型业务关联全字段快照保持外部已提交状态，不当全auth/audit/token/SQL证明。RR授权→真实Invoice锁等待→独立Intent提交后final409，performance_schema必须实际观察等待。
- 四capture/final前后commit事件必须同一实际Session命中；独立DB核换图/Intent/version/log，final已提交丢回执保留图与版本2/log1，旧version409、当前version同集合no-op快照不变。未提交失败原样且能恢复。同版本双请求200/409、一次日志；同集合缺文件/配置/OSError仍503，不提前200。事件不等同物理断网/DB故障，文件无中间token提交。
- 独立金融设计/源及39项用例只读审查无新增具体P1/P2或明显假阳性；文档1.38定向只读复核无新增具体P1/P2，原状态/no-op/两次提交/错误分类与有限证据一致。审查当时453尚live，只审规格未跑/认证日志；当前终态由主线程确认。八篇/API/MySQL说明及发现清单同步，F20/64T/7W/R01–R06不变；新handoff最终定向只读复核同样未发现新增具体P1/P2，未代跑测试或认证日志。
- 63源码hash/51AST、8文档/31引用锚点/3JSON/64T/F20通过；strict18501 terminal exit0增量无违规，diff无错误；LF/CRLF仅为换行提示。源/test最后以来未再改，最终文字后静态/diff再核。无commit/push/merge/部署、生产DB/迁移、实际供应商/SMTP/COS、prepare/publish/finalize；main源未动，UI本轮未改不重build。
- 未完成：create/upload/reconcile/resolve/remote-change/batch/worker/rawSQL与未注册upstream writer、初始OFF旧执行器；I77全生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter与合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID/单活/不重复外发、全历史迁移126失败、真实供应商/SMTP/COS/B01–B07继续OPEN。安全本地仍可推进，完整goal继续active，不标complete/blocked，下一实际MySQL454。

- 最终独立文档审查只核新增handoff：452六红、capture/final两次提交、文件阶段无provider/token提交、196=39+61+45+17+34及独立71/47、15有限模型快照与原OPEN门禁一致，无新增具体P1/P2。终态测试证据由主线程确认，审查者未运行测试或认证日志。
- 05:47北京时间no-fetch巡检exit0：main0修改/1既有未跟踪、自有84修改/80未跟踪、无upstream，仅本地快照，未核远端最新。owned MySQL452/453已核runtime scope/8.0.46/datadir及Shutdown complete，CIM零对应mysqld；8精确目录目标核验、7存在目录已删，presale固定base原不存在。保留runtime.json/mysql.log/全部成功失败日志、固定runtime、复用checker与unit入口，portal-v138-cleanup.json记录实际清理。
- 本批6个一次性writers已精确删除，源/test未变；交接后静态/hash/AST/文档/diff复核，所有本批测试与strict句柄terminal，无本批MySQL遗留，不改ACL或清理他人/frontend/undefined。完整goal继续active，下一实际MySQL454；本批不代表完整门户或生产验收。

## 客户门户 v1.37 回款修改的当前权限与锁外订单/文件证据（2026-10-06）

- 上轮1.36为实际progress；本轮继续完整开发goal，在自有codex/customer-portal-dev-docs迁移PATCH当前DB receipt:write/原财务scope，两阶段完整group授权、锁外独立order/types/file证据，最终完整目标/附件绑定及当前Receipt/Intent/Allocation账本。旧service.change公开签名仅router调用已移私有_change，无无用兼容；local_retry更名local_group供retry与PATCH两阶段共享，旧名无调用。原state/version/batch/presale_deposit/金额/费用/Intent占图/已移除图规则、scope与PI版本不变，修改只failed/version+1/edited，不自动投递。
- 448会话69218 terminal exit1：6failed/33warnings37.02s。真实主应用JWT与管理员变更后旧token停用/撤role/撤write仍200修改金额，撤all/super_admin后他单200，旧无动作当前新grant403；是I81 P1子项实际反例，无fixture错误。实际新调用只经JWT身份，当前授权捕获及最终不信旧claims，原receipt全量scope保留，invoice全量不替代。
- 捕获前当前状态及Allocation和全批scope，冻结全Receipt/Invoice摘要与独立OrderTarget、AttachmentBinding全字段；原Intent占图/附件关系DB检查不写。commit释放authority/Invoice/Receipt/Intent/附件锁，读取不可变OrderEvidence/paytypes并按原origin规则做文件检查、结束token/cache事务；最终fresh当前group权限与完整目标，Allocation及参与Receipt+Intent当前锁读，当前附件/Batch关联与证据身份相等才绑定。current=True路径Intent→附件，老bind默认DB+storage完整验证保持，无任意skipflag。有效proxy仍原跳过本地文件检查，非真实proxy/COS或本地bytes hash全检证据。
- 449会话79543 terminal exit0：154passed/461warnings280.81s（58PATCH＋45retry＋17read＋34authority）为新增P2前中间证据，不能覆盖后发现边界。unit449会话51908 exit0为71passed/1warning12.56s，presale449会话49861 exit0为47passed7.41s。原财务断言全保留，无本轮夹具错误或删除测试换绿。
- 独立金融源审查发现I106/P2：初稿仅local_receipt授权目标后batch409，而原get先全scope。主审I107/P2：实际origin配置HTTP503无no-store越过局部IO错误分类。450会话39387 terminal exit1，2failed/59deselected/20warnings29.00s，实际mixed409应404及503缺Cache-Control均复现。已两阶段先local_group完整批次scope→合法batch才409，锁外IO段HTTPException固定503/no-store，不改初始/最终权限错误。原execute成功处理IntegrityError冲突仍rollback409，受控锁超时TransactionBusy；SQLA不可确认结果503刷新原单，不回退已提交值或盲重发。
- 最终451会话89179 terminal exit0：157passed/464warnings284.79s，61PATCH＋45retry＋17辅助读＋34原回款授权/ON-OFF竞争。真实随机loopback/口令MySQL8.0.46、真实main/MCP/ASGI/JWT/管理员路径及portalDDL；upstream Receipt/Batch/Allocation/结算等薄合成schema，seed/jobs/挂载与provider/token/proxy/cloud受控、实际HTTPtransport禁止。非157完整生产入口、全历史schema或真实供应商/token刷新/COS/物理故障/全网络验证。
- 最终unit451会话53704 terminal exit0：71passed/1warning12.89s；presale451会话91350 exit0：47passed7.63s。SQLite-only/PyMySQL/HTTP守卫、无.env，财务/预售原算法与替身身份子应用保持。157/71/47各自范围，不相加为整体验收或累加中间结果。464warnings为既有jose/Pydantic/Starlette/colour等，本轮不改无关依赖。
- 61新增包括order/types/storage慢IO期间实际管理员撤权提交→final403无商业/关联写，绑定/额度/Intent/Allocation/附件转移/Batch/key变化拒绝，三次真实RR授权快照→Invoice锁等待→独立账本/Intent/Allocation提交后的final409。performance_schema必须真实观察等待，未用sleep假竞争。15模型业务/关联全字段快照不是全auth/audit/token/SQL或全网络零写；图占用门控金额仍有余额，区分截图守卫。保留真实order_snapshot解析的坏详情三例及真实origin校验；本地实际PNG路径/存在检查，不是真实外部IO。
- 六次三阶段before/after commit必须同一实际Session命中，第二阶段metadata真实UPDATE并独立核持久结果；final已提交丢回执保持修正值、version2/edited1，旧version再PATCH409不二次修改，其他失败原财务快照保留且可恢复。双并发同版本200/409，原已有图和合法新图替换阳性。事件注入不等同实际断网/物理DB故障。
- 金融设计/源审查指出完整旧截图规则、当前Intent/Allocation、独立文件DTO与完整batch范围，修订后定向只读复核两P2已闭合、无新增具体P1/P2或弱断言；审查者未运行或核证日志。文档八篇/API/MySQL说明1.37，保留历史1.36，I106/I107实施发现不增加F20/64T/7W/R01–R06。文档文字审查及最终清理补证随后记录。
- 62源码hash/49AST、8文档/31引用锚点/3JSON/64T/F20通过；strict22064 terminal exit0增量无违规，diff无错误；收尾含handoff共四处LF/CRLF提示。最终交接文字后静态/diff再核。无commit/push/merge/部署、生产DB/迁移、真实供应商/SMTP/COS或prepare/publish/finalize；main源未动，UI本轮未改不重build。前端原版本提交/错误提示保留，没有自动重发实现背书。
- 未完成：create/上传绑定/reconcile/resolve/remote-change/batch/worker及rawSQL未注册writer、初始OFF旧执行器；I77全生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter与合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID/单活/不重复外发、完整历史迁移126失败、真实供应商/SMTP/COS/B01–B07继续OPEN。安全本地仍可继续，完整goal保持active，不标complete/blocked；下一实际MySQL452。

- 最终独立文档/新交接只读复核未发现新增具体P1/P2或过度闭环，157=61+45+17+34与71/47各自范围、449中间证据/450两红及15有限模型/OPEN门禁一致；审查不代跑/认证日志。先前451未终态仅是审查当时时点，当前实际terminal证据为主线程记录。
- 05:30北京时间no-fetch巡检exit0：main0修改/1既有未跟踪、自有84修改/79未跟踪、无upstream，仅本地快照，不核远端最新。四个owned MySQL448–451已核runtime scope/8.0.46/datadir及Shutdown complete，升级CIM零对应mysqld；14精确目录目标核验、13存在目录已删，presale固定base原本不存在。保留runtime.json/mysql.log/全部成功失败日志、固定runtime/复用checker与两个unit入口，portal-v137-cleanup.json记录实际清理。
- 本批8个一次性writers已精确删除，源/test未变；最终静态62hash/49AST、8文档/31引用/3JSON/64T/F20及diff收尾再核通过。全部本批test/strict句柄terminal，无本批MySQL遗留，不改ACL或清他人/frontend/undefined；完整goal继续active，下一实际452。

## 客户门户 v1.36 回款重试的当前权限与锁外费用证据（2026-10-06）

- 本轮继续完整实现goal并取得实际progress：公开POST retry改JWT仅身份、当前DB receipt:write与原财务scope；批次先全部Request、全部Conversion、全部Invoice排序锁，再Batch/Receipt当前成员及全scope。原failed/无远端ID状态、金额、比例/余数、净毛额/去重及预售sendable规则保持；只排原单pending，不新外发或改PI商业版本。其他create/PATCH/文件绑定/reconcile/resolve/remote-change/batch/worker/rawSQL仍OPEN，不把本批当全部I81安全。P0客户员工审批无自动push/库存占用/出库保持。
- 自动零费且PI surcharge时，当前授权捕获完整目标/Invoice/Batch成员/结算绑定与独立标量目标，commit释放所有业务锁，读取不可变供应商证据并结束token/cache事务，fresh最终授权/绑定及结算锁读、参与回款populate_existing/FOR UPDATE，原私有算法及callercommit。fees.allocate其他create/delivery原合同保持，旧公开service.retry签名淘汰；原单测改显式私有算法调用，断言全保留。
- 443会话89973 terminal exit1：6failed/20deselected/34warnings36.16s，真实主应用登录/管理员变更后的旧JWT仍停用/撤角色/撤write重试200，撤原全量scope后他单200，旧token当前新增write仍403。实际I81 P1子项反例；不是纯模拟授权服务。
- 444会话50517 terminal exit0：66passed/208warnings132.29s（32retry＋34原回款）中间证据；unit444会话50923 exit1为helper漏导fees导致1failed/70passed，非产品缺陷，已补import且原财务断言保持。445会话44483 exit1为10failed/32deselected/28warnings43.04s，四坏形状与三阶段六故障实际通过TestClient传播TypeError/KeyError/AttributeError/OperationalError及失活Session InvalidRequestError，不能称测得HTTP500。第二阶段真实独占metadata UPDATE，不是假逻辑commit。
- I104/P2修列表/成员/详情字段形状并在真实remote.receipt_info的.get前校验dict；三例保留真实helper只替底层remote.read，实际路径/参数必须命中。I105/P2补retry限定SQLA安全503/no-store、失活/已提交回调事务close，未知结果只要求刷新原单，不重置failed/重发；logger只类名/固定诊断，普通诊断错误内部保留，BaseException不吞。
- 446会话28034 terminal exit1：2failed/91passed/365warnings177.97s，阶段3前/后事件未命中：describe返回scalars后弱identity-map不再持目标Receipt。是测试门控缺陷，首次实际目标匹配标记同Session后沿用计数修复，仍要求精确hits、真实第二阶段写和独立持久结果，未删/弱化用例。unit446会话12229 exit0为71passed/1warning12.84s；presale446会话55224 exit0为47passed7.40s。
- 最终447会话75965 terminal exit0：96passed/370warnings182.91s，45retry＋34原回款授权/ON-OFF竞争＋17辅助读取。真实隔离MySQL8.0.46、随机loopback/口令、真实main/MCP/ASGI/JWT及管理员路径；上游回款/批次/分配/委派/结算为薄合成schema，portalDDL实际、seed/jobs/挂载受控，provider/token/proxy与cloud替身、HTTPtransport拒绝。不是96全生产入口或完整历史schema/真实供应商/token刷新/COS/物理故障/全网络验证。
- 最终unit447会话10344 terminal exit0：71passed/1warning12.83s；SQLite-only guard拒绝MySQL/实际HTTP、无.env，原财务算法和身份替身子应用断言保持。预售47项独立，最后remote/parser修订未改结算代码，96/71/47范围各自记录，不相加为整体验收或累加中间结果。370warnings为既有jose/Pydantic/Starlette/colour等，不改无关依赖。
- 实际门控期间管理员可撤权并提交，最终新动作拒绝；同层批次及结算变更拒绝，17类业务/关联全字段快照包括Application/Shipment两类，非全库零写证明。真实RR→Invoice等待→独立兄弟费用提交通过performance_schema命中，最终0.01正确，不取旧快照。双捕获只200/409并一次费用/版本/日志。最终after_commit回执故障已pending事实保持、再请求409无二次费用，其他提交前失败商业原样且可恢复；注入事件不等同物理断网。
- 独立金融审查发现并推动有序批次/当前RR费/结算绑定、真实详情helper和提交边界补强，最终只读定向源码/用例复核未发现新增具体P1/P2/关键假阳性；审查者未运行或核证日志。八篇文档同步1.36并保留1.35历史，I104/I105实施发现不增加设计F20/64T/7W/R01–R06。最新文字审查、静态strict/diff/sweep及清理随后补证。
- 自有codex/customer-portal-dev-docs工作树，无commit/push/merge/部署、生产DB或迁移、真实供应商/SMTP/COS、prepare/publish/finalize；main源码未动，本批UI未改不重build。I77生产启动、I92/I79/C05旧制品bytes/依赖/config/allwriter与合法恢复、I78真实systemd/cgroup/Node切换、I80现场all-success/PID/单活/不重复外发、历史迁移126失败、供应商/SMTP/COS/B01–B07继续OPEN。安全本地工作仍可推进，完整goal继续active，不标complete/blocked。下一实际MySQL448。

- 最终独立文字审查发现03/API“本retry全部SQLA503”P2分类过宽，原execute的IntegrityError冲突仍rollback→409；已修文档为原完整性冲突保留、其余安全边界内不可确认SQLA503，受控TransactionBusy原规则保持。未改源/test，不扩大六阶段OperationalError注入证据。其余定向文本复核无新增具体P1/P2，审查不代跑/核日志，最终独立定向回看确认分类冲突已消除，无新增具体P1/P2；只读未代跑或核日志。收尾文字及清理后静态与diff再核通过，源/test未变。
- 最终静态8文档/31本地引用锚点/3JSON/64T/F20、59源码hash/45AST通过；strict会话94530 terminal exit0增量无违规，diff无错误，仅三处既有LF/CRLF提示。05:04北京时间no-fetch巡检先因自有worktree看板写权限受限，授权同命令重跑exit0：main0修改/1既有未跟踪，自有82修改/78未跟踪、无upstream，仅本地快照不核远端最新。无自动写远端。
- 五个自有MySQL443–447均runtime scope/version/datadir及Shutdown complete核对、升级CIM零对应mysqld；17个精确data/temp/pytest/SQLite目标核验，其中16个实际存在目录已删除，presale目标本来不存在，记录portal-v136-cleanup.json。保留所有runtime.json/mysql.log/失败与成功日志、固定runtime及复用checker；本批11个一次性writers已按精确路径删除，清单同cleanup.json；复用checker和两个unit入口保持。所有本批测试/strict句柄terminal，没有本批MySQL留活；不改ACL或清他人/frontend/undefined。完整goal保持active，下一实际448。

## 客户门户 v1.35 回款辅助读取的当前权限（2026-10-06）

- 上轮文档交付已完成，本轮继续完整开发goal取得实际实现progress。自有codex/customer-portal-dev-docs接入GET types/order-balance/attachments当前DB主体；原六动作OR/receipt三动作OR、未绑定上传人/Intent发票委派/Receipt财务scope/批次全部子单规则及财务金额/手续费/预售/Intent/摘要不变。read_user允许明确传入原OR集合，默认原三动作保持。main源码未动，无commit/push/merge、生产DB/迁移、实际供应商/SMTP/COS、prepare/publish/finalize或部署；UI本批未改不重build。全目标保持active，不把本批读修复替代其他write或整体验收。
- 440会话10926 terminal exit1：13failed/82warnings47.76s。旧源码在真实员工登录/实际管理员变更后types仍200；撤原read_all/super_admin后他单余额仍200；旧无action token新增合法权限仍403，授权查询事件没命中。首轮assert停在这些入口，不能称每条凭证路径旧泄漏均已HTTP复现；凭证旧claims缺口为源码证据，修订后逐对象真实拒绝与阳性有证据。没有夹具错误导致的本轮失败，未删/弱化原财务测试。
- 441会话72263 terminal exit0：74passed/298warnings113.59s，中间16读＋34回款＋22永久权限＋2主应用交易；独立审查建议单列invoice:write和扩展快照，已补为17读、有限15模型快照（原11＋BatchAttachment/ReceiptBatch/InvoiceAllocation/InvoiceDelegateGrant，按真实PK/全字段）。他人未绑定404/原上传者成功、invoice-only Intent转换Receipt404、委派实际删除/混合批次拒绝及当前scope、新授权六动作OR阳性保留。审查者只读不跑/核日志，补强复核无弱化/新假阳性。
- 442会话65081最终terminal exit0：75passed/316warnings116.55s。实际随机loopback/口令MySQL8.0.46，17辅助读取＋34原回款授权/ON-OFF竞争＋22永久权限边界＋2主应用商业链路。部分真实main/MCP/ASGI/JWT，其他为直接SQL/服务或子应用，不称75全生产入口。upstream回款/批次/分配/委派为薄合成schema，受控种子/jobs/挂载保持；本地真实PNG、路径校验/FileResponse，provider查询与proxy替身、cloud managed=False且HTTP transport拒绝。不是真实供应商/token刷新/COS、完整历史迁移/全部constraints或全网络验证。
- unit441会话65907 terminal exit0：71passed/1warning12.78s。SQLite-only guard拒绝MySQL/HTTP、无.env，原财务算法与子应用身份替身断言全保持。75与71独立，不累加441/440或历史结果。316warnings为既有jose UTC/Pydantic/Starlette弃用等，本批不改无关依赖。
- 新实际查询事件错误必须命中、503/no-store且不泄露驱动字段、15类财务/关联快照不变且无受控IO，移除事件后合法读取。三种慢IO门控期间真实管理员撤权提交200，在途读取200，后续GET403。普通读取授权点是首业务DB读，不拿authority或对象写锁跨IO，也不承诺在途响应时再鉴权；不等同物理DB故障、外部取消、真实proxy或token刷新。
- 八篇契约/API/MySQL说明及独立审查记录同步1.35，F20/64T/7W/R01–R06保持。55源码hash/39AST和8文档/31本地引用/3JSON/64T/20F已通过，最终收尾文字后再查静态/diff。strict51964 terminal exit0增量无违规。04:25北京时间no-fetch巡检exit0：main0修改/1既有未跟踪、自有78修改/77未跟踪、无upstream，仅本地快照不核远端最新。最终cleanup/文字复核证据随后追加；不清他人/frontend/undefined或改ACL。
- 未完成：其他回款create/PATCH/retry/上传绑定/reconcile/resolve/remote-change/batch/worker/rawSQL与未注册upstream writer、初始OFF旧执行器；I77全生产启动、I92/I79/C05受核旧制品bytes/依赖/config/allwriter与合法恢复阳性、I78真实systemd/cgroup/Node22整切换、I80现场all-success/PID/单活/不重复外发、完整历史迁移126失败、真实供应商/SMTP/COS/B01–B07继续OPEN。可安全继续本地实现，完整goal不标complete/blocked。下一实际测试443。

- 最终文字独立复核发现原API回款段“未绑定回款截图按发票编辑权限”P2重复契约歧义，已修为纯未绑定上传人、Intent原receipt范围或invoice动作/委派、Receipt当前关联+receipt动作/财务scope、批次全部子单，最新契约同样明确Intent两路径。源码及原测试不变；文档复核未跑/核日志，75/71范围与全部原门禁保持。
- 清理已核三个自有MySQL440/441/442的runtime scope/版本/datadir与Shutdown complete，升级CIM零对应mysqld确认；10个data/temp/pytest及unit426临时目录实际删除。保留全部runtime.json/mysql.log/失败与成功日志、固定runtime与复用checker；本批一次性writers仅在最终核对后精确清理，记录portal-v135-cleanup.json。所有本批测试与strict句柄terminal，无本批MySQL留活，下一实际443。最终静态8文档/31引用/3JSON/64T/20F与55hash/39AST通过；diff无错误，仅五处既有LF/CRLF提示。完整goal继续active。

- 最终P2修订的独立定向文字复核确认API原段与当前契约四类凭证规则及Intent两条路径一致，冲突已消除，未发现新增具体P1/P2。只读未代跑/核日志；75/71证据范围和所有开放门禁保持。

## 客户门户 v1.34 OFF永久权限屏障与旧版本当前读（2026-10-06）

- 上轮1.33实际修复与验证属于progress。本轮继续完整实现goal，在自有codex/customer-portal-dev-docs修共享authority/lock_timeout/upstream和Receipt安全错误头，新增OFF/旧版本/同连接/身份撤销验收并同步九处文档。main源码未动，无commit/push/merge、生产DB/迁移、真实供应商/SMTP/COS、prepare/publish/finalize或部署，UI未改不重build。8篇/R01–R06/F20/64T/7W不变，完整goal保持active，非整体完成/阻塞。
- I81永久权限子项实际OFF反例：431会话77877 terminal exit1，3failed/1passed/30deselected/23warnings47.66s；False筛选同时选中一个ON回滚阳性。OFF两个void-first(commit/rollback)和一个真实admin-first没有所需等待。共享lock_authority现安装schema在ON/OFF均参与；仅OFF/nonforce且屏障SELECT真实MySQL严格int1146，再同AuthorityBarrier mapper物理Connection FOR UPDATE唯一精确171 parent才legacy。空mode但已装authority仍持锁，缺行/隐藏/未知拒绝。ON/force不降级，不改/stamp schema或提交/回滚/flush caller。
- 同mapper Connection从取得至timeout @@/SET、屏障/head查询；bound_lock_wait新增可选connection而保留原调用形式，实际两bind正反观察同schema/CONNECTION_ID。legacy能力只属原根事务，重验清除，根结束/force失败不继承；suspend/review不按OFF跳过，仍要求首锁并同步暂停access、提升版本、撤session/邀请/quote，重ON不复活。仅共同已接入helper范围，不证明任意跨服务器写原子性或raw SQL/所有旧writer。
- I102/P2新增缺表分支普通parent SELECT信任既有RR旧171；I103/P2连接/timeout在分类外。434会话38398 terminal exit1，3failed/16deselected/1warning16.23s：独立173提交后仍legacy，@@/SET事件1146仍rawSQL错误。现parent当前锁读，窄guard覆盖connection/timeout/barrier且仅barrier阶段可降级；安全PortalError503、诊断只类名/固定文本、普通诊断错误内部group保留、BaseException原传播。公开helper固定no-store，TransactionBusy原handler保持；普通1054仍原OperationalError，T64全rollback/池与savepoint恢复保留。查询事件不是物理DB故障，不称434已经实际HTTP500复现。
- 436会话85491最终terminal exit0，99passed/195warnings117.74s。真实隔离MySQL8.0.46/Python/SQLA/PyMySQL随机loopback：34回款(31原＋3OFF)、22永久权限边界、21限时、4InnoDB竞争、14主应用生命周期、2主应用交易、2旧JWT管理。各fixture范围不同：回款及部分管理经实际main/MCP/ASGI/JWT，其他是直接真实SQL/服务或子应用；非99全生产入口。22包括八种head/ON/force、空mode/缺authority、两bind、明确1142隐藏表/1044连接、OFF身份/session/邀请/quote、运行主应用中精确171员工更新阳性、旧RR/timeout事件/legacy能力。head手工/上游薄schema、受控种子/挂载/jobs与有限spy保持，不代表pre172整体启动/历史迁移/供应商或全network。
- unit436会话13197 terminal exit0，71passed/1warning13.53s，原财务SQLite守卫仅SQLite、拒绝pymysql/实际HTTP transport、无.env；身份依赖替身子应用，原算法断言保持。扩展七个既有上游/身份/绑定/令牌/发票SQLite套件439 terminal exit0，64passed/2warnings5.86s，portal conftest拒绝非SQLite/MySQL并断言无.env。99/71/64范围分开，不相加为整体验收；警告既有jose UTC/Pydantic/Starlette等与两Query.get弃用，不改无关依赖。
- 432会话22995 terminal exit1，4fail46pass150warnings81.28s：低权限无GRANT先1044、trade误当factory、scheduler观测替身在缺表startup读mode，夹具修到明确1142及运行应用真实HTTP阶段（不冒称pre172startup）。433terminal exit2，writer剥加号导致收集SyntaxError/1error0.41s，无MySQL。435会话5437 terminal exit1，4fail95pass195warnings114.57s：两Membership.auth_version误字段、旧OFF=None规格、固定100通知前置队列过小；真实Member.version/永久OFF限时规格修正，原1054/rollback保持；实际owned topics数量+idle有限排空且禁止发送/最终idle保留，不改产品worker。
- 扩展SQLite437 terminal exit1，1fail63pass2warnings6.73s，剩余旧document-OFF无DB规格；员工/文档两条旧规格改当前角色拒绝及版本零写。writer替换范围误删相邻normal/linked HTTP两场景，438虽62pass2warnings5.76s不作为完整证据；主审计数与diff发现立即按原样恢复，439完整64通过，不隐藏或以删测试过关。全部原财务/HTTP断言保留。日志portal-authority-{431–439实际批次}.log、portal-receipt-unit-436.log保留，失败及中间通过不累加。
- 独立设计/源码审查明确同mapper限时、legacy能力和窄guard风险；最终当前源码/夹具复核无新增具体P1/P2或关键假阳性，明确1142及原1054/rollback/禁止发送/idle均保留。审查者只读未跑/核日志，最新九处文字复核随后附证。静态8文档/31本地引用锚点/3JSON/64T/F20通过，55hash匹配/38AST通过；清单仍44路由/38候选、非全writer证明。strict会话84170 terminal exit0增量无违规，diff exit0八处LF/CRLF提示。最终交接文字后重核静态/diff；复用检查器和日志保留。
- 04:07北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有78修改/77未跟踪，无upstream；仅本地快照不核远端最新。五个本任务MySQL431/432/434/435/436各runtime scope/datadir、Shutdown complete及升级CIM零对应mysqld确认，十个data/temp和unit426 basetemp共11目录实际删除；其他本批pytest目录未生成且均确认不存在，433无MySQL。保留mysql.log/runtime.json/结果/固定runtime和复用guard/checker，一次性writers收尾精确清理见portal-v134-cleanup.json，不改ACL、不清他人或frontend/undefined。全部本批测试/检查句柄terminal，下一实际测试440。
- 完成审计：本批已安装OFF权限持续保护、当前版本证据、失败分类、定向回归与文档已落地；整体I81仍有create/PATCH/retry/余额/types/凭证存储绑定/remote/batch/worker/rawSQL/未注册上游writer及初始OFF旧执行器。I77全生产启动、I92/I79/C05受核旧制品字节/依赖/配置/全部writer持续保护与合法恢复、I78真实systemd/cgroup/Node22整切换、I80现场全success/PID/单活/不重复外发、完整历史迁移126失败、真实合同/SMTP/COS与B01–B07继续OPEN。有安全本地进展空间，不能标整体complete/blocked。

- 最终九处文档独立只读复核未发现新增具体P1/P2矛盾或过度闭环，ON/OFF/同连接/legacy/撤销/错误契约一致，历史与当前进度边界明确。未跑/核日志，不能背书全writer/旧制品/生产。最终静态/diff后一次性writer精确删除，回执仍portal-v134-cleanup.json；源码和所有原测试保持，复用检查器/证据/runtime保留。完整goal active，下一实际440。

## 客户门户 v1.33 回款局部授权实现、详细文档及对抗审查（2026-10-06）

- 继续人类既有完整实现goal及此次详细开发文档/对抗审查要求，在自有codex/customer-portal-dev-docs迁移回款选定入口并同步八篇契约。main源码未动，无commit/push/merge、生产DB/迁移、真实供应商/SMTP/COS、prepare/publish/finalize或部署。UI本批未改，不重复build；R01–R06/F20/64T/7W保持。完整开发goal仍active，本批局部交付不关闭整体验收。
- I81回款P1子项实际旧JWT反例：421会话96970 terminal exit1，5failed/1passed，停用/撤角色后读200、仅撤write仍void200、撤read_all/super_admin后异归属详情200。现GET列表/详情/order-options重建当前DB员工/动作/财务scope，POST void公开服务从fresh boundary force authority→永久谱系→Invoice→Receipt，关联及scope末次复核，持至原commit/rollback。原OR、super_admin规则和财务范围保持；原合法pending/failed及不允许状态、金额/手续费/凭证/结算规则保持，不改变PI版本/发布，也不增加客户付款或远端行为。私有_void非内部恶意代码沙箱，旧公开签名不保留fallback。
- I101/P2源码审查发现授权SQL异常500；425会话62303 terminal exit1五个查询故障均500，已仅在授权/定位/取锁phase将SQLAlchemyError分类安全503/no-store。独立复核再发现logger/stdout故障覆盖响应，427会话80682 terminal exit1，2failed/29deselected/22warnings31.99s，两例实际500。分别隔离普通诊断Exception并保留为内部ExceptionGroup cause，BaseException继续传播；七例均要求查询点及diagnostic_hits实际命中、脱敏/headers/独立业务零改和随后合法读/作废。查询事件不是物理DB/socket故障，Receipt点为关联定位而非最终行锁；不改变全局异常处理或吞正常业务/提交错误。
- 430会话81804最终terminal exit0，51passed/219warnings/95.38s，实际MySQL8.0.46/Python/SQLAlchemy/PyMySQL自有随机loopback：31回款主应用专项＋2主应用商业链路＋14主应用生命周期＋2员工scope子应用＋2旧JWT管理子应用；47主应用和4子应用范围准确分开。430包含429及426中间结果，不累加。实际密码登录/JWT/管理员撤权、ON两序data_lock_waits、先void commit/rollback、先撤权提交的等待void403、caller读/dirty/new/flushed拒绝保留、原财务状态/旧全量范围/新授权阳性均有区分对照。上游Receipt/Attachment/Log薄schema、受控种子/jobs/挂载、有限财务快照/transport spy保持限制，不称真实FK/完整历史schema/全SQL或全网络证明。
- unit430会话53657最终terminal exit0，71passed/1warning12.93s，SQLite守卫仅允许SQLite、拒绝pymysql及实际HTTP transport，无backend/.env；原财务算法与身份依赖替身子应用。api_client补真实RBAC/authority行/fresh请求Session；worker前新读而非旧ORM，保留原生成数量及全部原财务断言。71与51不同范围，不合计为全系统认证；警告为现有Starlette/AnyIO、jose UTC、Pydantic/可选colour等，不顺手改依赖。
- 420最初Invoice薄fixture误猜字段，terminal exit1六error；按真实order_type/shipping_fee/internal_accessory修复。unit424六fail/unit425两fail为共享旧Session/JWT夹具、缺barrier及worker旧缓存，修fixture不弱化业务断言。423/428各terminal exit4，仅误选不存在测试文件、无测试/无MySQL，不计产品反例或通过。422/424/426/429中间通过保留历史日志，不累加最终数。实际命令日志portal-receipt-{420–430实际批次}.log与unit-{424,425,426,428,430}.log保留。
- README/03/04/06/07、API-reference、MySQL README同步1.33，1.32源码结论按历史保留且当前说明收窄已迁移入口。独立源码/测试最终只读复核未发现本批新增具体P1/P2或关键假阳性；独立七处文档复核未发现矛盾/过度闭环。两者未运行测试或核证日志。原52hash源码发现仍44变更路由/38候选，不是全writer证明；31AST/八文档/31本地引用锚点/3JSON/64T/F20由最终静态核对；strict末次会话94035 terminal exit0增量无违规。首次strict指出except+pass证据丢弃，两处已保留内部cause；不是删检查或隐去失败。diff exit0八处LF/CRLF提示，不是逻辑错误。
- 03:33北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有78修改/77未跟踪，无upstream，仅本地快照、不核远端最新。全部本批业务/检查句柄terminal，下一实际测试431。九个自有MySQL420/421/422/424/425/426/427/429/430核对runtime scope/datadir、Shutdown complete与升级CIM零对应mysqld；本批数据/temp和生成pytest目录按绝对范围/reparse校验后实际删除，保留mysql.log/runtime.json/测试日志、复用守卫/摘要检查器/固定runtime；详见portal-v133-cleanup.json。423/428未建MySQL确认不存在。一次性writers完成后精确清理，不改ACL、不清他人或frontend/undefined。
- 完成审计：本批选定回款授权修复、详细文档、对抗审查及定向验证已完成；I81其他create/PATCH/retry/余额/types/凭证上传下载绑定/远端reconcile/resolve/remote-change/批次/worker及raw SQL/shared scripts仍OPEN。OFF mutation尚不force authority，本批仅已提交撤权和恢复，不关闭OFF并发围栏，也不证明pre172运行。I77全生产启动、I92/I79/C05旧制品字节/依赖/配置/全部writer持续保护与合法兼容恢复、I78真实systemd/cgroup/Node22整切换、I80所有success现场PID/单活/不重复外发、完整历史迁移126失败、真实外部合同/SMTP/COS与B01–B07全保持OPEN。仍可安全本地推进，不能将本批部分结果当整体完成或blocked。

## 客户门户 v1.32 详细开发文档与回款对抗审查（2026-10-06）

- 本轮按人类“生成详细开发文档并进行对抗性审查”请求交付文档，未继续产品实现；完整开发goal保持active，不因文档交付关闭整体验收。自有codex/customer-portal-dev-docs更新README/03/04/06/07及本交接；产品源码、测试、主工作树源码未改，无commit/push/merge、生产DB/迁移、真实OKKI/SMTP/COS或部署。没有启动新的业务测试/服务/MySQL，本次不声称回款漏洞运行复现，下一实际测试仍420。
- 八篇详细契约、R01–R06/7W/64T/F20保持；README与07入口1.32，核心方案仍英文客户/中文后台、方舟管理账号/实时范围、客户SKU/颜色别名与标准SKU/历史快照、完整提案→客户接受→当前员工唯一PI；P0仅本地PI/ReceiptIntent草稿，无客户在线付款、自动推单、占用或出库。此前1.31的22通过局部证据保留，不累加历史批次或用于关闭回款/全生产门禁。
- I81回款子项具体P1源码发现：auth.dependencies只解析JWT；receipt.access信任历史roles/read_all，receipt.router实际读/写/文件调用未重建当前员工；本地void/retry、外部取证后PI重锁及批次操作仍传同user。停用/撤动作或全量范围后的旧JWT在满足目标状态等条件时可能继续访问或修改回款。独立源码审查确认，非本轮HTTP红测，未修产品，不新增重复F/I发现计数。
- 03补实际动作AND/OR集合、业务权限与财务scope、旧入口/上传下载/批次边界；04补authority→当前员工→永久谱系→Invoice→Receipt/Intent/Batch/分摊的稳定锁序、本地根事务、外部无锁IO及最终重新授权/完整绑定、原执行事实不丢与未知不重发、历史归属和关闭新提交不撤永久保护。保留所有原金额/手续费/租约/结算/凭证/回执规则，不用关闭正常财务业务代替修复。上传invoice:write-only保留原OR，read_all不单独授予动作但有当前动作时按原财务scope。
- 06新增RCP01–RCP08为既有T55/T62/T64子场景，含真实管理撤权/旧JWT、全量范围降权、财务归属/代办、竞争两序、慢远端/关开关、已外发事实、混合批次/凭证、回放与旧普通业务阳性。仅规格，尚未执行；不关闭W02/W05/I81/T55/T62/T64。独立审查发现RCP01将部分撤write误要求全部读写403的P2规格矛盾，已拆OR残余阳性/全部撤除403/AND缺一拒绝；这非新产品漏洞。主审同时收窄03降权403措辞，不误封保留read/write之一的合法接口。
- 两位独立只读审查核心契约及新增五处文档，核心模型/API/身份/映射/商业确认/唯一PI未发现新增具体P1/P2矛盾或过度闭环；交易复核指出并确认RCP01修正与实际动作表，末次建议的凭证上传限定已落实并按原路由主核。审查者未运行业务测试或核证日志。07记录源码风险、规格修正、限制与开放门禁，顶部旧1.27误导航改1.32。
- 主审静态八篇/31本地引用锚点/3JSON/64T/F20通过；复用检查器47源码hash匹配、26Python AST通过，仅辅助核对既有证据范围，不算新业务测试。strict会话1822 terminal exit0增量无违规；最终git diff --check exit0，共4处LF/CRLF提示（本次handoff一处，其余3处既有）。日志portal-v132-{static,source-check,conventions,diff,sweep}.log保留。本次文档收尾后重核内容/引用及diff。
- 02:51北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有75修改/76未跟踪，无upstream，仅本地快照，不核远端最新。所有本批工具句柄terminal，未产生MySQL数据或pytest临时目录；本次七个一次性writers在落地后按精确路径清理，回执portal-v132-writer-cleanup.json；保留复用检查器、独立runtime和证据日志，不清他人产物。
- 完成审计：此次详细开发文档与对抗审查请求已交付；源码P1及新回款规格尚未修复/运行。完整开发目标仍有I77生产种子/job/挂载/schema启动、I92/I79/C05兼容旧制品/allwriter持续协议与合法恢复、I78/I80真实进程切换/单活/不重复外发、I81其他财务/rawSQL/维护writer、完整历史迁移及供应商/SMTP/COS/B01–B07，均继续OPEN。没有批准上线或执行器正式切换。

## 客户门户 v1.31 实际应用两端登录与商业HTTP闭环（2026-10-06）

- 上轮v1.30实际ASGI/清理修订及终态是实质progress；本轮继续完整goal/R01–R06，将实际完整应用验证延伸至两端登录/映射/提案/PI及双主体隔离，没有缩小整体范围。自有codex/customer-portal-dev-docs新增test_mysql_application_trade.py，产品源码本轮未改，主工作树源码未动。README/03/06/07、隔离测试README同步1.31，八篇/F20/64T/7W保持，不增加实施I编号。无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署，未执行真实prepare/publish/finalize；无UI改动不重复build。
- 复用上一轮实际app.main/完整路由/FastMCP/ASGI fixture，无dependency_overrides；员工实际bcrypt密码登录和JWT，两个客户通过真实auth/bootstrap→challenges→verify，错码拒绝后正确码成功。身份/权限/两公司目录由owned fixture开通；OTP只从实际加密Outbox解码，不投递邮件。Settings用owned随机MySQL和随机JWT密钥，凭证repr遮蔽；416旧失败日志两处测试CSRF repr已遮蔽，保留失败证据。独立runtime仍portal-asgi-runtime，真实MySQL8.0.46随机loopback端口。
- 416会话31609 terminal exit1：2failed/19warnings38.24s，夹具提交PO与报价不同，产品正确QUOTE_CHANGED，非产品漏洞。417修一致PO并保留篡改拒绝对照，确认product_id不在standard_json、直接读item.product_id；会话81475 terminal exit0：2passed/39warnings31.00s为中间版。
- 独立审查指出两处证据不足：审批重放仅same receipt/unique invoice可漏回款意图/通知重复；客户隔离只有交叉读取。补首次成功与重放间交易/财务快照相等、成功audit/通知唯一；已有有效proposal awaiting_customer时，另一个客户自己的session/CSRF和正确If-Match2，accept/reject/cancel固定404且每次快照不变，再原客户接受阳性。418会话6162 terminal exit1：1failed/21passed/84warnings48.34s，cancel用{}缺必填ReasonInput.reason，422提前拒绝，非产品越权发现；修有效reason，不弱化404及零变更断言。
- 最终419会话20806 terminal exit0：22passed/91warnings47.51s。范围=2完整应用商业HTTP＋14实际应用生命周期＋2员工范围＋2过期权力JWT＋1PI无副作用＋1提案绑定，六file同批。22包含418/前版相关套件，不累加历史160或2passed。91为既有Starlette/AnyIO/Pydantic/colour可选Matplotlib及python-jose UTC弃用warnings，无本增量新失败；未修改无关SDK/模块。
- 商业阳性：实际员工发布客户SKU/颜色映射，客户目录→quote→PO篡改拒绝→submit同键重放，业务员完整费用/付款条款提案，接受前审批409，客户接受后员工建唯一128.00 PI/审批重放。真实ReportLab/LeShine Logo及Vera测试字体生成PDF，pypdf解析实际bytes核证完整费用/付款条件与别名；映射v2改名后当前目录更新，而历史请求及PDF文本仍旧别名，内部product/model/color标准值不变。不是生产CJK字体或UI/PDF视觉布局验收。
- 隔离阳性：两个业务员各自有request/list/detail，双方交叉404；两个客户交叉detail/PI和他客有效accept/reject/cancel404，交易状态不变。无关业务员虽有write/invoice权限仍不能审核他客；实际/api/auth/users/{id}停用后旧JWT仍携带invoice:write，当前查看/审批403且无交易变更；实际恢复后旧token对原请求合法审批成功，另一个客户请求保持submitted无PI。客户accepted_by独立SQL断言属于原客户。
- 证据边界：上游schema/库存镜像/合同价/试点资料为合成fixture；挂载/业务规则/seed/job注册/持久策略替身、实际scheduler为空，storage任务体受控。DML observer只记录匹配的INSERT/REPLACE/UPDATE/DELETE，允许auth users/login/refreshtoken/PI/items/receipt_intents/portal表；不是任意SQL、触发器、存储过程或全网络沙箱。business_snapshot覆盖请求/版本/行/PI/items/ReceiptIntent/回执/转换/发布/Outbox，不含全部权限/审计/库存；成功audit单独唯一断言。provider推单/出库/队列和HTTP transport/urllib/SMTP.sendmail设拒绝spy，不声称所有SMTP连接已拦或真实供应商验证。旧相关服务套件仍仅子应用/替身边界，不因联合运行变成全main证据。
- 最终独立只读源码/测试复核未发现新增具体P1/P2，确认取消有效payload、跨客户身份/原客户阳性与审批重放补强；未运行或核证419日志。静态8篇/29本地引用锚点/3JSON/64T/20F通过；47源码hash相等、26Python AST通过，发现清单44路由/38候选非全writer证明。strict会话78873 terminal exit0增量无违规；diff exit0仅既有3处LF/CRLF提示。证据portal-v131-{static,source-check,conventions,diff,sweep}.log。
- 02:34北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有75修改/76未跟踪、无upstream，仅本地快照不核远端。416–419 runtime scope/datadir/Shutdown complete及升级CIM零对应mysqld已核证，实际删除8个data/temp目录，4个pytest basetemp未生成且已不存在；证据portal-v131-cleanup.json。保留mysql.log/runtime.json/全部终态日志/独立runtime与复用检查器；本批六个一次性writer已实际移除，portal-v131-writer-cleanup.json保留；不清他人/frontend/undefined或改ACL。所有本批测试/检查句柄terminal，下一实际测试420。
- 完成审计：本批实际两端登录→映射→完整提案/接受→唯一PI/PDF、双主体读写隔离及旧JWT停用恢复的局部证据已补；产品没有新修复，原完整实现尚未完成。I77全种子/job/挂载及完整schema生产启动，I92/I79/C05受核旧制品身份/配置/allwriter持续保护及合法恢复阳性，I78真实systemd/cgroup/Node22整切换，I80现场所有success/单活/无重复外发，I81其他writer/财务维护，完整历史迁移/供应商合同/SMTP/COS/B01–B07仍OPEN，goal active。最终独立只读文字复核无新增具体P1/P2矛盾或过度闭环，未代跑/核证419日志；本收尾writer执行后移除。全部本批测试/检查terminal，无本批MySQL留活，下一实际测试420。

## 客户门户 v1.30 实际ASGI入口与资源清理I97–I100（2026-10-06）

- 继续原完整开发goal与R01–R06，自有codex/customer-portal-dev-docs修改实际main.lifespan与scheduler取得函数，新增正常导入完整应用的测试；D:/commission-system主工作树源码未改。八篇详细开发契约及定向对抗审查已同步1.30，F20/64T/7W保持。无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署，未执行真实prepare/publish/finalize。UI未改不重复build，整体goal active。
- 新建独立portal-asgi-runtime，保留原okki-test-venv；以原已验证依赖约束安装完整backend/requirements.txt，bcrypt4.3.0/pytest8.4.2/python-dotenv1.1.1匹配项目限制，实际FastMCP SDK mcp1.28.1、sse-starlette3.0.3、FastAPI0.115.14/Starlette0.46.2。安装会话9104 terminal exit0，实际pip check无broken requirements。源码requirements未改；无外部MCP业务调用。407会话4492 terminal exit1：2errors/1warning22.10s，旧runtime缺mcp，非产品反例。
- 408会话12454 terminal exit1：1failed/1passed/18既有warnings31.67s。实际app.main/完整路由图/FastMCP/ASGI TestClient正常HTTP阳性；实际空scheduler启动后AI种子失败，原main未进入yield前finally，scheduler.running仍True，I97/P2。独立源码另发现I98/P2：stop_worker错误跳过scheduler、MCP退出错误跳过engine；I99/P2：scheduler.start已完成、get_jobs/日志失败，调用者尚无句柄不能清理。
- main改AsyncExitStack，取得后立即登记，逆序storage→scheduler→MCP→engine；持久mode不删除，scheduler只清本次引用。registry保护start及报告窗口。409会话12847 terminal exit1：4failed/56passed/18warnings38.83s，MCP观测/注入在async with正常尾部及大小写误差，属于测试夹具假阴性；移入finally并统一文本。410收集exit4 no tests ran：文件名选错，未建MySQL。411会话13600 terminal exit1：1failed/141passed/10skipped/18warnings101.63s；误选Node controller且未配置Node路径导致10skip，不能当对应controller通过。
- 412会话40521 terminal exit1：1failed/9deselected/18warnings27.42s，补cause遍历仍只有MCP/TaskGroup/scheduler错误，storage已从隐式异常图丢失，I100/P2。独立审查确认Python ExitStack对独立callback的新context为空时不接旧错误；主lifespan现显式收集同步cleanup BaseException，完整unwind后聚合生命周期错误及全部cleanup错误；没有cleanup错误仍原样raise。实际all断言三种错误及完整顺序未弱化。413会话47264 terminal exit0：156passed/18warnings112.82s，为中间修复，不与最终计数相加。
- 独立文档/源码审查发现I99剩余窗口：except先logger/print，诊断本身失败会跳过shutdown/ref cleanup。414会话76251 terminal exit1：2failed/1passed/11deselected/18warnings28.57s，实际空scheduler报告失败且print/logger诊断失败后仍running。registry移除清理前诊断，先实际owned shutdown/finally只清本次引用，再传播原错误。
- 最终415会话13892 terminal exit0：160passed/18warnings117.63s，14实际整应用＋50模式＋19真实旧队列＋9reader边界＋14Python rollback controller＋54worker，全部同一批actual Python/SQLAlchemy/PyMySQL/随机loopback MySQL8.0.46。14包括原正常客户会话/目录/报价/提交/同键重试、晚启动失败、四清理回执场景、三诊断场景、内部取消、busy、失败后新实例、两晚启动+实际dispose后RuntimeError/KeyboardInterrupt回执组合。此160包含413与旧套件，不累加历史。18 warnings为Starlette/AnyIO alias、Pydantic既有class config及colour缺可选Matplotlib，不修无关模块。
- 证据边界：正常导入真实app.main/完整路由/FastMCP及实际ASGI startup/shutdown，无dependency_overrides；Settings复制owned数据库，文件挂载、规则/种子、job注册/持久策略受控替换，真实scheduler为空。storage是真实线程但run_once=False；客户session由服务fixture建立，目录镜像/合同价受控，不是登录投递或供应商验证。cleanup错误在实际stop/dispose成功后注入，证明继续收尾与错误保留，不证明真实stop/dispose失败后物理终止。CancelledError在lifespan内注入，不是外部task.cancel、kill或cgroup证据。Python controller仍临时Settings/受控queue，worker供应商HTTP/镜像替身；不是完整生产启动或历史迁移。
- 最终独立源码/测试定向复核未发现新增具体P1/P2，确认显式错误聚合、诊断故障修复及未弱化断言；复核者未运行测试或核证415日志。静态8篇/29本地引用锚点/3JSON/64T/20F通过，47源码hash匹配、25Python AST通过；发现清单仍44路由/38候选非全writer证明。strict会话84533 terminal exit0增量无违规，diff exit0仅既有3处LF/CRLF提示。日志portal-v130-{static,source-check,conventions,diff,sweep}.log保留。
- 02:12北京时间no-fetch sweep exit0：main0修改/1既有未跟踪，自有75修改/76未跟踪、无upstream，仅本地快照不核远端。407/408/409/411/412/413/414/415各runtime scope/datadir、Shutdown complete和升级CIM零对应mysqld核证，实际删除19目录，6目标原已不存在；详见portal-v130-cleanup.json。保留全部mysql.log/runtime.json、运行日志、独立ASGI runtime/约束及复用检查器；一次性writers随后清理，不清他人/frontend/undefined或修改ACL。所有测试/检查句柄terminal，下一实际测试416。
- 完成审计：本批实际ASGI局部入口、I97–I100清理/异常保留修订、隔离回归与文档已完成；整体实现尚未完成。I77全种子/job/挂载及完整schema生产启动，I92/I79/C05受核旧制品身份/配置/allwriter持续保护及合法恢复阳性，I78真实systemd/cgroup/Node22整切换，I80现场全部成功入口/单活/无重复外发，I81其他历史writer/财务维护，完整历史迁移/供应商合同/SMTP/COS/B01–B07仍OPEN，goal active。最终独立只读文字复核无新增具体P1/P2或过度闭环，未代跑/核证415日志。12个本批一次性writer/清理脚本已实际删除，日志portal-v130-writer-cleanup.json保留；本收尾writer执行后清理。全部本批测试/检查已terminal，无本批MySQL留活，下一实际测试416。

## 客户门户 v1.29 旧补任务入口I95与业务清理I96（2026-10-06）

- 前轮1.28修复/证据是实质progress；本轮继续完整goal与R01–R06。核对当前回退和writer后发现公开旧补任务可绕过scheduler包装层，先补该持续协议前置；旧制品兼容核验本批尚未实现，不缩小整体目标。自有codex/customer-portal-dev-docs改outbound_task_service/outbound_mode及受影响测试，main未动；无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署，没有真实prepare/publish/finalize。无UI改动不重复build。
- 401会话33082 terminal exit1：1error/16.08s，fixture只有迁移anchor缺outbound_auto_requested，非产品反例。402改完整隔离invoice字段/任务日志表，会话5789 terminal exit1：1failed/21.11s。v1+OFF直接Session服务实际扫描/入队1且未按预期拒绝，finally rollback，没有提交/供应商外发；I95/P2。
- 公开reconcile_missing_outbound_tasks改owned Session factory及严格int limit1–200，内部body改private，由共同reconcile_legacy持锁后新读mode并根commit。已知v1 OFF/ON禁旧body，busy不误放其他owner，fresh限制原样；finally结束业务事务再释放fence，包括中断。旧算法unit改private算法调用，原mode/controller Mock改patch private，不保留旧公有Session兼容层；当前app引用已检索，无其他算法注册入口。内部代码/raw SQL仍可绕过private名，不将其当安全沙箱。
- 403会话54057 terminal exit1：4failed/86passed/1既有colour warning/39.12s，根事件注入误击savepoint；before_commit/after_rollback排除nested后404会话20939 terminal exit0：144passed/1warning/99.68s。403失败是测试门控缺陷，404不是最终新增rollback中断回归范围。
- 独立审查发现I96/P2：rollback_owned只catch Exception。405会话73838 terminal exit1：2failed/17deselected/23.71s，根队列flush/commit故障后rollback自身KeyboardInterrupt/SystemExit，RELEASE前独立PROCESSLIST记录业务socket仍在，观测[(1,0)]。修BaseException→固定安全日志→invalidate→raise保留中断，不依赖外层Session.close晚清理。
- 最终406会话35813 terminal exit0：146passed/1既有colour缺可选Matplotlib warning/99.47s，19实际队列入口＋50模式＋9reader边界＋14Python控制器＋54worker。146含404/历史重用套件不累加；实际Python/SQLAlchemy/PyMySQL/随机loopback MySQL8.0.46。真实队列body与根事件，独立observer先占不同连接，RELEASE前业务ID在PROCESSLIST=0/任务0/全快照不变，后续合法实际queue成功。没有业务进程kill/完整ASGI/真实服务/cgroup/旧制品/完整历史迁移；worker供应商HTTP/镜像及控制器Settings/历史Mock queue body各替身保持，不能扩大。
- 同406 guard单元回归terminal exit0：25passed/5.32s，原test_invoice_outbound_tasks；Engine.connect只许SQLite，pymysql及真实HTTP transport拒绝，无.env；旧算法/其他推单接口替身。25与146不同范围，不相加为整体验收数。日志portal-legacy-{401,402,403,404,405,406}.log和portal-legacy-unit-406.log保留。
- README/02/04/06/07、MySQL README同步1.29，F20/64T/7W不变。最终独立源码/文字复核、摘要/strict/diff/no-fetch及401–406本任务数据清理随后补证。所有业务测试句柄terminal，下一实际测试407。I95/I96仅当前入口及清理范围修复，I92/I79/C05旧制品字节/依赖/配置/所有writer持续保护与兼容恢复阳性、I77全ASGI/I78整切换/I80现场全success/PID无重复外发/I81其他writer及完整历史schema/供应商/SMTP/COS/B01–B07仍OPEN，goal active。


- 最终独立只读源码/测试复核确认根事件/savepoint区分及rollback BaseException物理失效顺序，未发现本增量新增具体P1/P2；独立七处文字复核未发现矛盾或过度闭环。两者均未运行测试或核证406日志。静态8篇/29本地引用锚点/3JSON/64T/20F通过；47源码hash相等、22Python AST通过，发现清单仍44路由/38候选，非全writer证明。strict会话15137 terminal exit0增量无违规；diff exit0仅既有三处LF/CRLF提示；证据portal-v129-{static,source-check,conventions,diff,sweep}.log。
- 01:36北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有75修改/76未跟踪、无upstream，仅本地快照，不核远端最新。401–406各runtime scope/datadir、Shutdown complete及升级CIM零对应mysqld核证；六组data/temp十二目录及403/404/406三个pytest目录实际移除（共15目录），401/402/405和unit406未生成对应basetemp，均已不存在。七个一次性writer不存在，收尾证据writer随后清理；保留源码/测试、mysql.log/runtime.json/日志、复用unit guard/source checker/inventory与固定runtime/store，不改ACL或清理他人/frontend/undefined。
- 完成审计：本轮公开旧补任务入口、释放前业务连接中断清理、实际MySQL/SQLite回归和独立审查/文档已完成；旧制品兼容核验本轮未实现，不能以改名或安全拒绝替代兼容恢复阳性。原完整实现目标仍有I92/I79/C05、I81其他writer及其他全部门禁，尚不满足整体完成证据，goal保持active。所有本轮测试/检查句柄terminal，无本批MySQL留活，下一实际测试407。


## 客户门户 v1.28 Python模式读取I93/I94（2026-10-06）

- 继续完整开发goal/R01–R06和原开放门禁，在自有codex/customer-portal-dev-docs修outbound_mode.read_mode、明确pre172用例head并新增实际MySQL边界测试；main未动。无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署，未执行真实prepare/publish/finalize。UI本轮未改，不重复build。
- 397会话96586 terminal exit1：4failed/2passed/16.14s。模式表缺失且head空/173/未知/多head时实际OFF bootstrap错误返回legacy，I93/P2。两个真实低权限用例原已安全拒绝，仅回归对照。398会话7855 terminal exit0：70passed/1既有colour warning/31.76s；初修直接查询及171检查，但同Session仍可能跨bind，不作为最终证据。
- 独立源码复核发现I94/P2；399会话66500 terminal exit1：2failed/6deselected/16.16s，实际mapper模式库173/默认库171误放行，反向模式库171/默认库173误拒绝。现两查询复用AuthorityBarrier mapper实际Connection，不flush/commit/rollback调用方事务；只严格整数1146进入唯一精确171核验，其他异常安全拒绝。
- 400会话47326 terminal exit0：127passed/1既有colour缺可选Matplotlib warning/100.21s，为最终实际回归：9边界＋50模式＋54worker＋14控制器。127包含此前70及旧相关套件，不累加397–399/历史批次。实际Python/SQLAlchemy/PyMySQL/随机loopback MySQL8.0.46；双bind断言同schema/同CONNECTION_ID并正反对照，缺版本表拒绝；所有临时head/表finally恢复。手写171/head及精简迁移anchor不是完整历史迁移；worker供应商HTTP/镜像、queue body与控制器Settings替身，不是完整ASGI/旧制品/真实service/systemd/业务worker crash。
- 独立只读源码/测试最终复核无本reader增量新增具体P1/P2或关键假阳性，未运行测试/核证400日志。明确executor_fence仍默认bind、生产SessionLocal单bind；reader多bind用例不证明任意多服务器writer/fence原子性。本批不扩展该写协议。I93/I94仅reader反例局部修复，I92/I79/C05旧制品/运行配置/全部writer持续保护与兼容恢复阳性仍OPEN，不以Health200、compat标志或全拒绝代替。
- README/02/04/06/07、隔离测试README同步1.28；8篇契约/F20/64T/7W保持。I77全ASGI、I78实际systemd/cgroup/Node22/整切换、I80全success入口现场PID/无重复外发、I81全writer/财务维护、完整历史schema/外部合同/SMTP/COS/B01–B07继续开放，goal active。静态/摘要/strict/diff/no-fetch、最终文字复核及397–400自有数据清理随后补证。所有业务测试句柄terminal，下一实际测试401。


- 最终独立只读文字复核未发现本增量新增具体P1/P2矛盾或过度闭环，未运行测试/核证日志。静态8篇/29本地引用锚点/3JSON/64T/20F通过；47源码hash逐一匹配、19Python AST通过（检查器另输出此前16项中间结果，不累加）；清单仍是44变更路由/38候选函数的源发现，不是全writer完成证据。strict会话71856 terminal exit0增量无违规；diff exit0，仅既有三处LF/CRLF提示。证据portal-v128-{static,source-check,conventions,diff,sweep}.log。
- 01:12北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有73修改/76未跟踪、无upstream，仅本地快照，不核远端最新。397–400 runtime scope/datadir、各Shutdown complete和升级CIM零对应mysqld均独立确认；四组data/temp八目录实际删除，398/400 pytest basetemp删除，397/399未生成对应目录且已不存在。五个一次性writer已不存在，收尾证据writer随后清理；保留源码/测试、mysql.log/runtime.json、最终日志和复用检查器/runtime/store。不改ACL，不清他人或frontend/undefined。
- 完成审计：本批reader修复、实际回归和文档/独立定向审查完成；原完整实现目标未达成。I92受核旧制品/配置持续协议与I79兼容阳性、I81全writer及其余门禁仍需实现，不能以本批安全拒绝替代原能力。所有测试和检查句柄terminal，无本批MySQL留活，下一实际测试401，goal保持active。


## 客户门户 v1.27 I91实际导入与回退控制器验证（2026-10-06）

- 前一轮1.26详细文档/独立审查是实质progress；本轮继续完整实现goal，保持R01–R06与全部未完成门禁。自有codex/customer-portal-dev-docs修rollback_protocol.py、测试fixture并新增实际控制器MySQL回归；main未动。无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署；不运行真实prepare/publish/finalize。
- 389会话14711实际活跃但子进程启动未返回，无探针child；普通/elevated临时目录访问身份不一致。核实两Python PID后只终止本测试，句柄终态exit-1，不算产品反例/通过；不因观察超时重复启动。390统一身份实际terminal exit1：1failed/2deselected/0.54s，实际绝对复制脚本在无PYTHONPATH临时Settings/SQL环境中失败。修可信__file__候选backend导入、参数化namespace与嵌套finally后391 terminal exit0：10passed/0.24s，入口真实子进程但Settings/SQL替身，相关backend服务效果替身。
- 392会话30072 terminal exit0：13passed/26.56s，实际Python rollback_guard→实际产品main复制字节→实际SQLAlchemy/PyMySQL→自有随机端口MySQL8.0.46；临时Settings受控随机凭据仅子环境、首查询前uuid/port验证，不加载生产app/.env。独立审查发现schema_change测试仅空库，可能缺表即拒绝，不能当指纹证据。393补同型可读空mode表及直接legacy/不同fp观测，会话87840 terminal exit0：13passed/25.57s；不累加392。
- 394补finally重置USE和actual current reconcile_legacy控制锁内busy→释放实际fixture SQL commit→bootstrap v1→disabled零新写，queue body替身。会话58121 terminal exit0：14passed/26.62s，最终原生套件。覆盖busy不释放其他owner、baseline后mode提交、未知/坏/多mode、GET实际取得后ACK、RELEASE前/后ACK/坏值、actual child kill、GET前真实bootstrap竞争、合法legacy异库拒绝；独立IS_USED_LOCK与原表快照。不是完整ASGI/旧制品/真实service readiness/业务worker crash/全writer PI保护。
- 395扩14部署suite，会话42263 terminal exit0：295passed/14.43s；实际隔离Python入口与本地Node静态导入，Git/服务/SSH/DB/外部契约均对应替身，不运行真实发布。295与14属于不同范围，不汇成整体验收数，不累加前版/前次回归。
- I91在实际导入/控制器范围局部修复，I92仍OPEN：未核证旧制品身份/运行配置/所有writer持续保护，不用兼容标志、Health200或block-all代替兼容制品阳性。I79/C05实际兼容回退、I78现场切换、I77全启动/I81全writer、I80全成功入口现场PID与无重复外发、完整历史迁移/供应商合同/SMTP/COS/B01–B07继续开放。完整goal保持active。
- 独立定向源码/测试复核最终结果、文档/摘要/strict/diff/no-fetch及本次测试数据清理随后补充。README/04/06/07、隔离测试README和客户部署指南同步1.27；F20/64T/7W不变。全部本次测试句柄已terminal，下一实际测试编号396。

- 最后只读复核：合法legacy异库区分已闭环，当前callback commit阳性原缺独立断言；追加独立SELECT fixture_legacy_queue.version==1，396会话8050 terminal exit0：14passed/26.67s为最终原生套件。396包含394/393/392，不累加，旧制品/I92仍未因此修复。当前helper/controller定向源码审查未发现新增具体P1/P2，审查者未运行测试或核证日志。
- 源码发现清单新增三个回退源摘要，仍是候选发现清单而非全writer证明；最终文档与静态核证后补。下一实际测试编号397，所有本轮业务测试已terminal。

- 最终独立文字定向复核未发现新增具体P1/P2矛盾或过度闭环，actual main/controller与Settings/queue body替身、14原生与295部署范围准确分开；复核者未运行测试或核证日志。静态8篇/29本地引用锚点/3JSON/64T/20F通过；源码发现44路由/38候选/47hash逐一匹配、16Python AST通过，仅发现清单非全writer证明。strict会话24775 terminal exit0增量无违规；diff exit0，仅四处LF/CRLF提示。证据portal-v127-{static,source-check,conventions,diff,sweep}.log。
- 00:47北京时间no-fetch sweep exit0：main0修改/1既有未跟踪，自有73修改/76未跟踪、无upstream，仅本地快照不证明远端最新。四个自有MySQL392/393/394/396核验runtime scope/datadir、Shutdown complete及CIM零对应进程；各data/temp八目录已实际不存在。首次清理PS路径对误拼为一个不存在的字符串，报错未删MySQL数据（七个pytest目录已删）；纠正列表、ErrorAction Stop并重核绝对范围/reparse后八目录均实际删除，未以首次exit0/输出冒称成功。389按创建身份另清，八个pytest basetemp均已不存在，不改ACL。
- 保留源码/测试、日志/runtime身份、复用检查器与固定runtime/store；本轮一次性writer收尾清理，不清理他人或frontend/undefined。全部本轮业务句柄terminal，下一实际测试397。完整goal active，后续从I92受核旧制品/运行配置持续协议和I79兼容阳性、I81全writer等继续，不能将本轮局部控制器验证当作整体完成。

## 客户门户 v1.26 开发文档与对抗审查（2026-10-06）

- 本轮人类请求为详细开发文档与对抗性审查，仅更新README/04/06/07及交接；没有继续修改产品。保留此前未完成rollback源修改与测试，不回滚他人成果。自有codex/customer-portal-dev-docs，main未动；无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署。完整实施goal仍active，文档交付与实施分别判断。
- 读取既有387红测terminal exit1，2failed/0.16s，及388绿测terminal exit0，2passed/0.09s。两站service/Git/DB observation/rollback guard均替身，仅说明未DDL但模拟mode提交后的旧制品启动阻断；不称真实SQL/脚本/锁/兼容回退或部署回归通过。日志portal-rollback-red-387.log、portal-rollback-388.log。本轮不新增业务测试编号，下一实际仍389。
- 独立只读审查发现I91/P2：绝对rollback_protocol.py脚本未显式加入backend导入路径，普通无PYTHONPATH的changed激活将app导入失败。I92/P2：legacy回退控制锁释放后，未核证旧制品可能不参与后续mode协议；另一合法bootstrap提交v1时旧writer保护无保证。两项源码未修，本轮仅补目标契约及实际隔离入口/释放后竞争验收；源逻辑发现不称实际事故复现。I79/C05兼容制品阳性、legacy实际恢复、模式基线/进程/全writer保护及受影响部署回归均未完成。
- 八篇/R01–R06/W01–W07/T01–T64保持；F01–F20设计统计5P1/15P2不变。独立核心契约复核、定向最终文字、静态/strict/diff/no-fetch及源只读摘要核验结果随后补充。未调用真实prepare/publish/finalize入口。

- 最终独立核心契约与1.26定向复核未发现新增具体P1/P2文档矛盾或过度闭环；交易审查发现的I91/I92明确OPEN，建议同锁保持至commit/rollback已补04。两审查者未代跑测试或核证日志。
- 实际静态exit0：8篇/29本地引用及锚点/3JSON/64T/20F；44既有源码摘要匹配、10Python AST通过，另外四份当前回退源/测试摘要写前后相同且AST通过。strict会话56362终态exit0，增量无违规；diff exit0，三处既有LF/CRLF提示。00:20北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有72修改/76未跟踪、无upstream；仅本地快照，不证明远端最新。证据portal-doc-v126-{static,conventions,diff,source-check,source-boundary,sweep}.log。
- 本轮无业务测试/服务/MySQL启动，无活跃测试句柄；新一次性文档writer清理，保留日志、源摘要、复用检查器和此前未完成实现材料。下一实际测试编号389；完整实现goal继续active。本轮文档交付可供开发，不批准真实协议切换或上线。

## 客户门户 v1.25 C06共同成功凭据与暂停补偿（2026-10-05）

- 继续完整实现goal，原R01–R06及全部整体门禁保留。自有codex/customer-portal-dev-docs修改outbound release/remote、schema resume、publish及两个历史159/160 finalizer，新增共同凭据和actual finalizer execute控制流测试。main未动，无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署；不运行真实prepare/publish/finalize，业务UI/后端未改。
- 当前读取确认上一轮v1.24是实质progress，全部业务句柄terminal。本轮377红测terminal exit1：1failed/0.14s，schema.resume_external在无上下文时未拒绝managed timer（control为Mock，无实际启动）。提取invoke的validate_receipt；verify_completion绑定candidate digest/release/revision/DB/mode/baseline/严格bool/释放资格，实际phase verify再核返回；resume要求上下文，核验后跳过managed timer start。正常publish final核验共用helper。378会话80273 terminal exit0：105passed/12.42s。
- 379接入completion_context及历史159/160 execute：候选字节与已activated receipt核对、fresh prepare target，再在服务恢复/静态效果前verify、success前再verify；timer比mode目标，summary带outbound。旧历史缺凭据拒绝，不fallback，非通用172/173恢复。380会话18075 terminal exit0：150passed+13subtests/12.05s，新增helper与publish伪造回执断言（不是实际finalizer全流程证据）。
- 独立审查I88/I89/P2：fresh MODE floor重置成历史legacy；本地拒绝无法保证暂停。381两个实际红测terminal exit1：2failed/25deselected/0.18s，确实降floor并接受伪造current legacy。现历史/fresh/已有floor取最高MODE，phase也不降低；历史legacy已过期而fresh v1时拒绝直接verify/finalize，需协调freeze/install/activate。I89加pause_registered从当前受信module登记host/固定root发精确pause输入，不采用坏context target，remote只disable/stop TIMER、保留active SERVICE/bytes/mode/业务事实并使已激活journal failed_paused、另记pause-current。382会话87351 terminal exit0：152passed+13subtests/12.04s。
- 383增加actual finalizer execute与pause用例，terminal exit1：135passed/1failed/4.19s，为pipeline colorwork Mock要求source但历史入口实际合法省略source的harness签名错误，不算产品失败。384修替身可选参数并加强state父目录/JSON/.next/lock symlink拒绝；会话9807 terminal exit0：170passed+13subtests/12.43s。新增finalizer两入口均执行实际body/共享guard，SSH/NSSM/HTTP/路由/static/schema/phase全替身、writer清单空，不是现场非空writer恢复。
- 独立审查I90/P2安全暂停分类；暂停登记/脚本IO/remote/parse全部纳入Exception保护，固定inspection错误from None，不输出raw传输/驱动数据，不吞BaseException。385 terminal exit1：142passed/1failed/4.16s，为phase测试误调fixture Mock而无invoke记录；386捕获fixture前REAL_PHASE执行actual函数，并补TimeoutExpired/OSError/RuntimeError及登记故障/阳性pause客户端。386会话92759 terminal exit0：262passed+13subtests/12.96s，12相关suite。262包含此前105/150/152/170，不相加；subtests单列。
- 386包括两个历史execute的prepare-only/完整成功、缺/坏receipt在效果前拒绝、第二verify异DB发生在static之后但无success/schema-completed；正常publish伪造verify无success；managed timer v1/legacy及其他writer恢复对照；模拟remote pause保持PID41/service active/字节不变，候选额外参数拒绝；8条state symlink测试替换is_symlink不是Windows真实链接。相关timer/source/发票schema/recovery151/168替身回归扩展；本地Node静态导入实际，无真实SSH/systemd/数据库或provider。本批未重跑native Node/MySQL，不外推上一批10例范围。
- 暂停确认与排空严格分开：release_confirmed=False/service_drain_confirmed=False。补偿不可确认则报核对，不说timer已停。恢复仍须freeze/drain；不强杀在途，不删mode/事实。I80/C06指定入口本地旁路修复，全部success入口清单、现场单活PID/无重复外发和真实writer仍待验；I79协议兼容回退、I78整体切换、I77/I81全部writer、完整历史schema/供应商合同/SMTP/COS/B01–B07继续开放。整个goal active。
- 源码独立复核和文字定向复核最终结论、静态/strict/diff/no-fetch巡检及本批pytest/writer清理随后补充。README/02/04/06/07与部署接入同步1.25，F20/64T/7W不变。全部本批业务句柄terminal，下一实际测试号387。

- 最终独立源码/测试复核无本轮新增具体P1/P2或关键假阳性；独立定向文字复核无过度闭环，二者均未代跑或核证386日志。静态8篇/29引用锚点/3JSON/64T/20F通过；44源码hash相等、10Python AST通过；strict会话21406 terminal exit0增量无违规，diff exit0仅既有两处LF/CRLF提示。23:58北京时间no-fetch巡检exit0：main0改动/1既有未跟踪，自有70改动/74未跟踪、无upstream，只是本地快照未核远端最新。证据portal-v125-{static,source-check,conventions,sweep}.log。
- 本轮无MySQL启动，全部测试句柄terminal；八个实际pytest basetemp目录及十一个一次性writer已按创建身份删除，所列九个目标路径全部不存在（377未生成目录）。保留源码/测试/证据日志、固定runtime/store与复用检查器，不清理他人或frontend/undefined。完整goal active，下一实际测试号387，继续I79兼容回退/I78真实切换/I80剩余现场门禁与全旧writer等完整目标。

## 客户门户 v1.24 C03模式目标与专用发布fence（2026-10-05）

- 继续完整实现goal，保留R01–R06和全部整体门禁。本任务worktree/分支修改remote/release/mode.mjs及回归，新增真实专用Node/MySQLfence测试；main未动，无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署，未运行真实prepare/publish。
- 370终态exit1：1failed/0.19s，模拟已知v1实际remote仍恢复true/true旧timer。改为mode决定目标，baseline仅审计；独立Node连接读取模式及uuid/schema摘要，legacy取共享锁后新读并保持至timer/目标/checkpoint，已知v1只读不争worker锁。释放结果和owner核对后才写阶段成功；故障销毁专用物理连接。371发布终态exit0：85passed/3.17s；371纯Node四套终态exit0：117passed/345.3203ms（源码无后续MJS改动）。纯Node假SQL/供应商及文件意图不能算真实发布。
- 独立审查I84/I85的372红测终态exit1：4failed/5deselected/0.20s，失败后丢v1下限可回legacy，数字schedule回执被接受。remote common及fence新观测先记独立mode-floor.json，已见v1后同库不可降级；prepare响应未消费也保留。local所有状态严格bool。373首命令引用不存在test_outbound_release_pipeline.py，exit4/no tests，不算证据；373b正确release/pipeline/mode suite终态exit0：89passed/3.12s。
- 374原生测试会话26542终态exit1：7passed/1failed/18.11s。专用child.kill后真实broken stdin flush的OSError覆盖原安全错误；_abort确认owned child终止后只忽略清理pipe的OSError，不授予释放成功。374未完成第9项竞争用例，不把早先7通过算完整套件。
- 独立审查I86/P2：同completed发布整流程重试覆盖baseline。375红测终态exit1：3failed/1passed/12deselected/0.39s，三种非全false基线确实被改false/false。现same coordinated release_id/revision/digest保留原baseline，并核验候选字节；新身份才新采。回执丢失为已完成但调用方未消费状态模拟，不是网络丢包实验。
- 376发布回归终态exit0：96passed/3.47s；为既有release/pipeline及16模式用例，不与85/89相加。systemd与DB观测替身，本地静态Node导入真实；覆盖四组合v1目标、专项拒绝、sticky floor失败/prepare/异库、严格bool、failed release失效、锁内目标/journal及same completed完整重试。
- 376原生会话74431终态exit0：10passed/18.03s。实际Python ModeFence→实际Node v24.19.0/mysql2 3.24.4→独立随机端口MySQL8.0.46；uuid/port与自有配置受控。legacy hold阻实际bootstrap且业务不变，v1保留合法owner，busy旧owner不误释放；GET后ACK丢失、RELEASE前/释放后ACK/坏值物理连接关闭，独立IS_USED_LOCK无残留且正常后续bootstrap对照；实际控制child.kill；GET前门控由实际bootstrap提交v1，取锁后新读mode；实际USE切默认schema后拒绝。除有意mode建立外全表行快照不变。没有运行完整remote.execute/systemd、完整ASGI或供应商poller/creator；bootstrap同进程、kill专用控制child，不是业务worker崩溃；实际172/173仅精简anchors，不是全历史schema。目标Node22未验。
- release失败后failed_paused只确认旧timer disabled/inactive，service_drain_confirmed=False，不声称原service/cgroup已排空；恢复须freeze/drain后安装，不直接activate/verify。阶段enabled字面不意味timer启用/new worker运行。I78实际systemd/cgroup/目标Node/完整切换、I79回退、I80所有success/resume/finalize共同凭据、I77/I81全链路与全writer/财务维护、历史迁移/真实供应商/SMTP/COS/B01–B07继续开放，整个goal active。
- 独立只读源码/测试两轮发现并确认I84–I86修复，最终无本增量新增具体P1/P2或关键假阳性；未代跑或核证日志。README/02/04/06/07及部署/测试接入说明同步1.24；F01–F20/64T/7W不变。静态/strict/diff/no-fetch巡检及本次临时数据清理随后补充；本批业务测试全部终态。下一实际测试号377。

- 最终独立定向文字复核无新增具体P1/P2或过度闭环，未代跑/核证日志。静态8篇/29引用锚点/3JSON/64T/20F通过，44个源码hash相等、4Python AST通过；strict会话40128终态exit0增量无违规；diff exit0仅既有两处LF/CRLF提示。23:25北京时间no-fetch巡检exit0：main0修改/1既有未跟踪，自有67修改/72未跟踪、无upstream，均仅本地快照，未核远端最新。日志portal-v124-{static,source-check,conventions,sweep}.log。
- 374/376 runtime隔离scope/datadir、实际Shutdown complete及升级CIM零对应mysqld已核证；按创建身份移除两data/temp和376 pytest basetemp（374未生成该basetemp），六个本地release pytest目录及九个一次性writer均已实际不存在。保留日志、runtime元数据/固定mysql2 runtime/store、源码/测试及复用检查器；不清理他人或frontend/undefined。全部本批句柄终态，无测试/MySQL服务留活。完整goal仍active，下一实际测试号377，继续I78剩余现场切换、I79/I80与全部原门禁。

## 客户门户 v1.23 Node模式权限边界 I83（2026-10-05）

- 继续既有完整开发goal，保持R01–R06及全部开放门禁。自有codex/customer-portal-dev-docs修Node mode reader、纯Node测试，新增native Node/mysql2探针、隔离权限测试和两个显式runtime选项。main未动，无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge或部署；没有运行真实prepare/publish（可能远端push）。
- 源码/独立设计审查发现I83/P2：metadata COUNT=0既可能缺表也可能无权限。366会话22047终态exit1：1failed/6deselected/16.11s，实际已装mode但低权限Node返回legacy。补强同结果gate和全行快照后，367会话32514终态exit1：1failed/6deselected/16.03s，实际结果('legacy',None,True,None)，metadata_count=0，隔离全表行不变。仅actual reader/gate观测，没有启动完整creator或外发。失败不计通过。
- 产品直接SELECT完整模式命名空间；1142/1044/连接/未知内容失败关闭且不泄露原驱动错误/cause。缺表只有code=ER_NO_SUCH_TABLE、数值errno=1146、sqlState=42S02同时精确匹配，随后同连接alembic_version唯一精确171_customer_tag_display_value才legacy；172/173/未知/空/多head/不可读拒绝。可读空命名空间原初始legacy保留，不改Python reader或其他旧writer。
- 368会话76773终态exit0：15passed/18.95s。实际Node v24.19.0、固定mysql2 3.24.4、隔离MySQL8.0.46，低权限已装/空表、特权已知/初始空表、缺表171/172/173/unknown、未知/坏/多mode、空/多/缺失head和缺表但head无权限均通过；最后一例实际同账号先证1146及1142。每探针核验server_uuid/bind_address/port，所有隔离表行前后相等。实际172/173使用精简上游anchors，迁移head为手工fixture值；不是完整历史回放、目标Node22或完整poller/creator主流程，也不是两个冲突执行器联调。
- 368纯Node四套终态exit0：117passed/348.6166ms；涵盖直接查询、唯一mode/version、缺表三错误标识、head形状/值/SQL失败及脱敏，其他创建/查重/文件意图仍假SQL/供应商边界。该117不与362的100相加。369发布/编排终态exit0：80passed/2.92s，本地实际静态Node导入及远端/systemd/DB替身；不执行真实发布，不证明目标timer已按mode切换。日志portal-node-mode-red-{366,367}.log、portal-node-mode-368.log、portal-node-pure-368.log、portal-release-369.log保留。
- mysql2测试runtime在D:/commission-system/tmp/portal-node-mysql-runtime独立安装，pnpm 11.25.0 --save-exact --ignore-scripts，锁定3.24.4、12包；不改产品依赖、不运行安装脚本。安装会话35537终态exit0，保留runtime/store以便后续实际Node/MySQL测试。
- 独立只读源码/测试复核无新增具体P1/P2或假阳性；确认真实权限边界、同连接兼容和脱敏，强调head合成/非完整业务main及目标Node版本限制；未代跑或核证日志。I83在上述局部模式准入范围完成修复。I78/C03当前源码仍基线恢复timer，模式检查到恢复有竞争，I79回退/I80共同凭据以及I77/I81整体、全旧writer/linked-run/完整历史迁移/真实进程/外部合同/SMTP/COS/B01–B07均继续开放，不能批准正式切换。
- README/02/04/06/07、测试README与两个部署接入说明同步v1.23；8篇/7W/64T/20F保持，inventory重算后仍为源码发现而非全writer证明。最终静态/strict/diff/no-fetch巡检及数据清理证据随后补充。整体goal保持active，下一实际测试号370。

- 最终独立定向文字复核无新增具体P1/P2或过度闭环；静态8篇/29引用锚点/3JSON/64T/20F通过，44个源码hash匹配、两改动Python AST通过；strict会话50592终态exit0增量无违规，diff exit0仅既有两处LF/CRLF提示。22:37北京时间no-fetch巡检exit0，仅本地快照：main0改动/1既有未跟踪，自有67改动/71未跟踪、无upstream，不代表远端最新；日志portal-v123-{static,conventions,sweep}.log。
- 366/367/368均实际Shutdown complete，runtime隔离scope/datadir及CIM零对应mysqld核证；仅删各自data/temp及三pytest basetemp，369由创建身份单独清理，均实际不存在。四个一次性writer已清理，保留源码、测试、日志/runtime及固定mysql2 runtime/store和复用inventory/checker；未清他人或frontend/undefined。全部本批句柄终态，未留MySQL/预览服务。
- 补04的C03待实施原子窗口及06竞争验收：legacy激活在专属同目标连接共享命名锁下新读取mode/DB→timer目标变更→核验/journal，已知v1只读暂停不争合法新worker锁；legacy→v1允许，反向/异DB拒绝，模式错误不写成功。当前remote仍基线恢复，没有由文档新增而完成I78；下一实际测试号370，优先实现该fence/目标schedule及绑定回执，再推进I79/I80和其余完整门禁。

- C03追加独立文字复核无新增具体P1/P2；采纳锁内journal仅待释放确认、释放未知不授予success/finalize资格的细节，06补释放失联后不可凭journal绕过及正常释放阳性。此为待实现条款，不新增I83通过数量。

## 客户门户 v1.22 模式锁与Node保护实施（2026-10-05）

- 前轮1.21文档/审查为有效progress；本轮继续完整实现goal，保持原R01–R06与所有未完成门禁，不以本批局部修复替代整体交付。自有codex/customer-portal-dev-docs修改outbound_mode.py、worker.run_once、Node mode reader及三测试；不连接生产库/真实OKKI/SMTP/COS，不commit/push/merge/部署，未执行实际prepare（其链路可能远端push）。
- 359会话89381实际terminal exit1：1failed/28deselected/16.08s，服务器GET_LOCK确实返回1后注入ACK错误，bootstrap失败而独立查询仍owner9。随后独立observer预先持有物理连接、明确owner ID不同以补强证明；不把失败算通过。日志portal-fence-red-359.log。
- fence取得前读connection/owner，拒池内原同名锁并invalidate；GET/首rollback/结果规范校验同异常保护，仅int0busy、int1执行。释放后检查不再自己持有，允许合法新owner；异常/中断先废弃socket再脱敏报错/保留中断。worker共用helper，释放fence前rollback专属业务Session，失败invalidate业务Session。
- 360会话52653terminal exit0：47passed/1colourwarning/19.88s，模式28项＋6取锁故障＋12释放故障＋1单池两层预持锁。后续补真实中断两个phase、释放后另一连接实际接管、worker真实flush后的rollback失败顺序，最终363会话88378terminal exit0：104passed/1colourwarning/84.26s，mode50＋worker54。104含前47与既有worker53，不相加。真实MySQL8.0.46；mode实际172/173迁移/最小anchor，lifespan为实际AST body加资源stub、旧queue body替身；worker实际服务/token/parser/builder/scanner/当前角色，供应商HTTP/镜像替身。不是完整ASGI/真实进程崩溃/Node双进程/全部历史schema。
- 361 Node红测terminal exit1：19项中7pass/12fail/109.7351ms，观察旧精确code查询/缺version、COUNT证据宽松和错误分类；其中future假SQL原返回未按精确WHERE过滤，后已补模拟旧过滤，不能把该首次错误文案失败写成真实未来mode已漏执行。源码reader改完整命名空间、唯一规范version1、严格表证据及脱敏失败。362 Node四套terminal exit0：100passed/345.9607ms，纯函数/假SQL及本地文件意图，不是真Node/MySQL双进程，实际Node v24.19.0而非目标v22.22.1。
- 364 terminal exit0：5passed/2既有依赖warnings/3.62s，scheduler注册/禁用、GBK错误、旧删除独立job；wrapper对Engine连接仅许SQLite且直连pymysql拒绝。365 terminal exit0：80passed/2.97s，outbound release/pipeline，本地真实Node静态加载及远端/systemd/DB替身，不执行真实发布。无UI变化不重跑build。日志portal-fence-green-360.log、portal-mode-{node-red-361,node-green-362,worker-363}.log、portal-scheduler-364.log、portal-release-365.log。
- 独立两轮源码/测试定向审查未发现本增量新增具体P1/P2，递归锁、BaseException、合法接管和业务rollback顺序已补；审查者不代跑核证。I82上述本地反例完成修复，I77/I81整体门禁仍开放；Node未知mode局部保护已实现，旧delete/directservice/linked-run/所有writer、I78模式目标schedule、I79回退、I80finalize、真实进程/完整历史迁移/外部合同、SMTP/COS及B01–B07仍待完成。完整goal保持active。
- README/02/04/06/07、隔离测试README、poller接入及客户发布指南同步v1.22边界；静态、源码摘要、strict、diff、本地no-fetch巡检与本批临时数据清理结果在本节补充。复用inventory发现清单仍非全writer证明，F20统计不变。

- 最终独立定向文字复核无新增具体P1/P2或过度闭环；8篇/29本地引用锚点/3JSON/64T/20F及44源码hash逐一匹配、四Python AST通过。strict会话54607终态exit0、增量无违规，diff exit0（既有两处LF/CRLF提示）。22:01北京时间no-fetch巡检仅本地快照：main0修改/1既有未跟踪、自有67修改/71未跟踪、无upstream。证据portal-v122-{static,conventions,sweep}.log。
- MySQL359/360/363均核验scope/datadir、Shutdown complete及升级CIM零对应进程；各data/temp和三个pytest临时目录已不存在。首次合并清理因365目录Windows身份ACL拒绝而在预查阶段停止，未误报删除；按创建身份分别清理364/365及MySQL目录后均实际成功，不改ACL。保留源码/日志/runtime/复用检查器及inventory generator，清理本批一次性writer/guard，不清他人或frontend/undefined。
- 后续从I78模式决定目标schedule、I79兼容回退/I80共同凭据及其真实反例继续，再完成全部旧writer、真实进程、完整历史迁移/外部合同及客户B01–B07闭环。无本批测试/服务活句柄，下一实际测试编号366；完整goal未完成且保持active。

## 客户门户 v1.21 开发文档与对抗审查（2026-10-05）

- 本轮人类请求为详细开发文档与对抗性审查。同步README/02/04/06/07及源码发现清单，不继续修改产品。原完整实现goal仍active，文档交付不等于整体开发完成；没有生产迁移、真实OKKI/SMTP/COS、commit/push/merge/部署。
- 接收前批已运行358会话41156终态exit0：28passed/1colour依赖warning/23.30s，日志D:/commission-system/tmp/portal-mode-green-358.log。真实独立MySQL8.0.46、实际172/173迁移和精简上游anchor；真实mode bootstrap/registry/命名锁与事务。lifespan取实际main AST body，其他资源依赖替身，非完整ASGI启动；legacy queue body替身，不是全旧队列或真实Node进程。只记录这28例，不与357四例相加。
- 前批355终态1failed/16.06s为测试AST注解缺FastAPI的harness错误；356终态1failed/16.08s实际进入lifespan后mode缺失，构成启动空窗反例；修订后357终态4passed/16.13s。355–358均已终态，无继续挂起测试。新worker install_mode调用方/旧scheduler单测未在本批重新执行，不把28例写成全部相关回归。
- 28例覆盖ON四开关、首建busy、已有mode/liveowner重启、初始OFF/已有modeOFF、未知/多条/坏版本、提交前/commit后lostACK、DB错误脱敏、精简pre172表不存在、两starter竞争、旧RR快照拒绝、反向旧排队持锁直到commit/rollback、注册/回调mode再核对；没有完整历史迁移、真实进程崩溃或所有锁故障证据。
- 独立交易审查新增I82/P2：executor_fence的GET_LOCK和首个rollback处于异常保护外，取得结果未知可能回池残留named lock。文档补物理连接invalidate、真实取得后故障与独立IS_USED_LOCK断言；当前产品未修，未运行该故障反例。I77及I81注册/回调仅局部进展，I82、Node未知mode、旧delete/direct service、I78模式目标调度、I79回退、I80finalize、全部writer/实际进程/完整历史迁移/真实外部合同及B01–B07仍开放，正式切换不能批准。
- 独立核心契约初轮无新增具体跨文档P1/P2；最终定向复核、静态/strict/diff/本地no-fetch巡检及清理结果在本节补充。F01–F20保持5P1/15P2，I82不混入F统计；8篇/W01–W07/T01–T64保留。

- 最终两位独立定向只读复核未发现新增具体P1/P2文档矛盾或过度闭环；修正06把GET_LOCK(0)误说成原地等待，现明确busy拒绝、旧队列commit/rollback后重试。I82代码未修/故障反例未跑，复核者未核证既有日志。
- 主审静态8篇/29本地引用锚点/3JSON/64T/20F通过；源码发现44变更路由/38候选函数/44hash逐一匹配，仅发现清单非全writer。strict会话3671终态exit0、增量无违规，diff exit0（既有LF/CRLF提示）。21:37北京时间no-fetch sweep exit0：main0修改/1既有未跟踪，自有67修改/71未跟踪、无upstream；仅本地快照，未证明远端最新。证据portal-doc-v121-{static,conventions,sweep}.log。

- 355–358四份runtime均已核验scope/datadir、Shutdown complete、升级CIM零对应mysqld及绝对路径非reparse；各data/temp和pytest临时目录已实际不存在。保留日志/runtime/源码与可复用检查器，清理本批一次性writer，不清理他人产物。完整实现目标保持active。

## 客户门户 v1.20 完整制品与暂停安装实施（2026-10-05）

- 上一轮1.19文档修订是有效progress；本轮继续完整实施goal，自有codex/customer-portal-dev-docs，main未动。修改deploy/okki_outbound_release.py、remote.py、publish.py及两测试；无生产DB/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署。未执行真实prepare入口（其链路可能push远端），仅实际Node本地加载和本地/mock发布测试。
- 发布制品加入okki_outbound_mode.mjs共五文件、摘要逐项核验；仅无.env/.ark-outbound.env的staging对poller/creator/mode进行syntax及真实静态import。真实Node用例拦fs写、子进程、socket/HTTP/fetch并比较process.env，当前模块零这些副作用且无main输出；本机Node v24.19.0，不是目标远端v22.22.1或main动态auth/mysql2验证。
- 协调流程freeze禁用timer、等待原service/MainPID→迁移→五制品install且inactive/disabled→Office/北京后端启动→后续activate/verify。冻结/安装/激活有阶段约束；install必须新schema探测，不延伸allow_pending。安装回执严格revision/release_id/digest及两个布尔false暂停值；installed_paused仅是旧Node安装阶段，不证明数据库mode建立或新worker接管。
- 未知journal/坏baseline拒绝重新采基线；同身份prepare/freeze/install保留原基线与已安装阶段；实际mode字节篡改拒绝恢复。同身份第二文件替换失败保留原备份/暂停/frozen，重试补齐四个剩余文件；安装journal已保存后lostACK保留installed_paused，重新prepare/freeze/install零重复替换。不同身份/候选仍阻断。真实子进程/cgroup排空、多进程/MySQL和崩溃未由模拟systemd关闭。
- 351实际exit1：3failed/61deselected/0.92s，观察mode制品缺失、真实Node syntax通过但缺静态依赖prepare未拒绝、publish无install阶段。产品修订后352实际exit1：33passed/1failed/1.59s，旧编排测试还期待freeze→migrate→backend；同步新阶段期望，未弱化新独立先安装/失败不启动断言。353实际exit0：76passed/2.46s；独立审查指出新列测试最后只测activate，再补独立install缺列拒绝、两个staging配置拒绝及已安装mode篡改反例。
- 最终354实际exit0：164passed/4.66s，七文件：outbound release、pipeline、migration recovery168、timer writer、desktop console、portal release及backend release。systemd/远端/DB及其他进程均为各测试本地替身；真实Node限静态加载。164含前76及相关回归，不相加前轮数。日志D:/commission-system/tmp/portal-release-{red-351,green-352,green-353,final-354}.log；所有命令已终态，无本批MySQL/前端服务启动，不跑无关UI build。
- 两轮独立只读源码/测试及最终文字复核未发现本增量新增具体P1/P2，审查指出的staging配置、动态依赖界限、原基线/安装阶段、部分替换/lostACK和严格receipt均纳入；最后纠正“五字节”笔误为“五制品字节”。审查者未代跑或核证164日志。I76在本地静态制品范围修复，I78只完成安装顺序及暂停恢复部分；I77/bootstrap、I78模式目标调度/专项启用、I79持久协议兼容回退、I80finalize、I81旧调度仍开放。F20统计保持，未因旧测试契约修订制造新finding。
- README/06/07文档1.20、deploy README、源码发现清单同步。inventory44变更路由/38候选函数/41hash（新增三发布源hash），41实际逐一匹配；仅源码发现非全writer证明。五改动Python AST、静态8篇/29引用锚点/3JSON/64T/F20均通过；strict会话73777终态exit0、增量无违规；diff exit0，既有两处LF/CRLF提示保留。日志portal-v120-{static,conventions,diff,sweep}.log。
- 21:06北京时间no-fetch sweep exit0，只是本地快照：main0修改/1既有未跟踪；自有64修改/69未跟踪、无upstream。351–354四个自有pytest临时目录及本轮六个一次性helper已实际按绝对范围、非reparse核对清理成功；保留日志、源测试、复用检查器及inventory generator。没有清理他人目录或既有frontend/undefined。
- 完整goal仍active。下一实质阶段同步mode bootstrap独立worker/SCHED开关、首建共享锁与既有模式/OFF保护；继而mode决定target_schedule、统一恢复凭据/兼容回退、全部旧writer/linked-run/回款维护入口、真实进程/完整历史迁移及外部合同、SMTP/COS和B01–B07试点。下一个实际测试编号355。局部制品/安装通过不代表T54/T62/T64或可上线。

## 客户门户 v1.19 开发文档交付与发布对抗审查（2026-10-05 20:44 北京时间）

- 当前人类请求为“按以上方案生成详细的开发文档并进行对抗性审查”。本轮仅修改README/02/04/06/07五篇目标文档及本交接；未推进产品代码、运行业务写测试、启动新worker或执行发布。自有codex/customer-portal-dev-docs，main未动；没有生产连接/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署。既有完整实现goal仍active，文档交付不等于实现目标完成。下一实际业务测试编号仍351。
- 八篇文档覆盖R01–R06、字段与约束、API/错误码、权限与范围、映射、报价/完整提案/客户接受/业务员建PI、前端和七个工作包/64验收。新增1.19持久模式记录及发布凭据、安全切换时序、兼容回退、恢复统一核验；C01–C06仅细化T54/T64不增64总数，P0客户建PI仍无自动出库。初始OFF且无mode保留legacy兼容；已有mode的OFF不可撤销模式或恢复旧writer。installed_paused与verified_running明确区分。
- 主审实际追踪制品、main/worker/registry、publish/remote/office/finalize源码。新增I76–I81六P2均开放：mode模块漏发/缺实际import、首tick启动空窗、原timer恢复与未更新creator窗口、非DDL持久协议回退不兼容、finalize成功标记旁路、OFF重新注册旧补任务。文档要求已补，产品代码未修，阻断对应正式切换；F01–F20既有设计发现(5P1/15P2)不混入I系列。旧删除对账、linked-run及其他财务/rawSQL writer仍各自开放。
- 两位独立审查先只读核对身份/权限/映射/价格/下载及交易发布源码，后定向重读落地1.19。最终未发现本增量新增具体P1/P2契约矛盾或过度闭环；模式字段与现有AuthorityBarrier兼容、暂停/接管/回退凭据区分一致。两者未运行反例或核证旧测试日志，不以其结论宣称六项源码缺陷已修复。
- 实际静态exit0：8篇/29本地链接及锚点/3JSON/64T/20F。严格check_conventions会话71755已终态exit0，增量无违规；git diff --check exit0，三处既有LF/CRLF提示保留。38个inventory源hash实际逐一匹配，清单仅用于源码发现，不证明全部writer已覆盖。日志D:/commission-system/tmp/portal-v119-{static,conventions,diff,sweep}.log。
- 20:42 no-fetch git_sweep exit0：main0修改/1既有未跟踪；自有61修改/69未跟踪、无upstream，只反映本地快照，未获取远端最新状态。本轮无自有测试/服务进程；本次单次写入helper收尾清理，复用检查器和必要日志保留。入口open_in_codex实际返回queued，未称已显示。
- 实现后续保持完整范围：受管release切换及真实双进程/MySQL争用与崩溃恢复、旧writer与全部PI/回款维护入口、完整历史迁移/兼容旧制品、真实外部合同/SMTP/COS及B01–B07双业务员双客户试点。文档完成不关闭T54/T62/T64或上线门禁。

## 客户门户 v1.18 详细文档与实际自动创建worker对抗审查（2026-10-05）

- 本轮按详细开发文档/对抗性审查请求更新，同时继续既有完整实现goal；自有codex/customer-portal-dev-docs，baseline54f77438328e5aa5d3c776ee309914447672d767。新增outbound_worker/create_plan/create_facts及scheduler；配置当前员工invoice:sync与PI范围，三开关明确登记整单才执行。P0客户建PI仍不自动外发/占库。main未动；无生产DB/迁移/真实OKKI/SMTP/COS、commit/push/merge/部署。
- 当前权限/永久谱系/PI全行/产品/回款与intent/allocation/回款凭据附件/最新及再生成log/任务/删除来源捕获→提交释放→原order/完整关联列表详情/严格占号/目标warehouse stock/双回读→锁外token缓存commit→当前全绑定比较→running+不可变START/STATE原子commit→再次锁外证据→当前owner/完整绑定/nonce/活租约→SEND+sending原子commit→锁外唯一实际POST parser→原authority/request/conversion/PI/START独立FACT→当前捕获冻结事实集合→锁外原GET→READ→当前全绑定/STATE/所有原代次风险比较→task/CHECK或FINISH/审计原子commit。generic mutable默认保留，worker专用只读capture可检查自身running，实际动作必须证原START。未声称捕获shipping inspection/photo全列；shipping全表未变化是零额外写证据，不能代替照片绑定覆盖。
- 默认worker=false/actor=0；scheduler门户true时建立永久mode=outbound-worker-v1。新版Node poller/直接creator与backend共享ark-okki-outbound-poller advisory锁，持久模式禁旧创建，独立.env不能降级。parent owner核对/standalone同锁/失败连接收尾已接；Node测试是纯函数/假SQL，不是实际多进程切换。生产release尚未证明先排空、先建mode、全部旧二进制更新、单活启动；首次30秒tick窗口仍门禁，不得直接恢复旧timer或删mode/事实回退。旧delete reconcile、linked-run、其他writer未由本批迁移。
- 独立源码审查I70–I74/P2：缺货覆盖regenerate、跨代次晚FACT被其他FINISH遮蔽、仓库/handler/汇率漏核验、未知占号选fallback、全库LIMIT20饥饿。修为代次保留/原删除出库ID匹配、same-nonce晚候选+全部原代次风险guard、严格原命令头、完整规范占号明细、固定ID高水位keyset分页拒绝也推进。I75/P2为已知取证不可用误409及外部token TTL OverflowError；worker窄分类503，旧通用token本体和全部其他writer未改变。审查原“常规OkkiApiError中断整tick”因其继承ValueError而撤回，不能登记为事故；独立最终源码未见本增量新增具体P1/P2，未代跑或核证350。最后文字复核纠正02照片捕获过度表述；开发文档1.18、API/tests README、deploy说明和配置示例同步。
- 339 fixture核心门户flag未开403，340/341自身running被generic ensure_mutable拒409（341安全phase日志定位）；修fixture并接worker只读捕获后342实际19passed/42.40s。343错仓库实际done红测：1failed/24deselected/23.14s。344占号null误409、空/非法详情不拒，以及20阻断队列零POST红测：4failed/26deselected/27.23s。修后345实际29passed/1failed/55.93s，末项全库running计数包含前序fixture并非限定20；修为20task全列快照、合法ID大于全部阻断并观察2页后346实际41passed/70.50s。347加入4坏占号、供应商首项、两代次和3offset，实际50passed/78.95s。失败/前版不累加到最终。
- 348联合实际205passed/1failed/223既有josewarnings/266.62s：精简表缺真实(scope,request_id) UQ，worker固定删除701与旧followup fixture冲突。改worker每invoice规范供应商ID，不弱化原业务/删除身份断言。349实际52passed/1failed/85.27s：done-only已实际选入并通过1POST/2FINISH断言，真实run_once处理了其他fixture候选使全库快照改变；修prepare在before快照前仅将有当前HTTP证据的PI登记auto_requested，公平性另建20明确候选。保留实际process/run_once、完整全库快照，未修改产品以过关。
- 最终350会话71699已观察terminal exit0：234passed/252既有josewarnings/299.10s =53worker+47execution+3attribution+80prepare+51followup。日志D:/commission-system/tmp/portal-mysql-350.log。worker直接实际Session、current DB角色、真实MySQL/产品builder/token helper/POST parser/关联scanner；供应商HTTP、remote.read和serial证据替身，不是worker JWT/ASGI API或真实process。其他四套actual JWT/ASGI及其各自替身边界维持前批说明。actual列类型/default精简库不代表全FK/UQ/历史迁移。
- 新53含五窗口×三撤权、独立authority/PI锁可取；POST撤权后仅原FACT追加且全业务/原shipping/验货媒体逐值保持；错/缺仓库handler汇率uncertain零FINISH、完整占号与合法他单阳性、永久删除再生成stock wait恢复；START/SEND/FACT/FINISH八before/lost_ACK，已持久SEND零POST只GET，其他恢复全程一次POST；真实run_once的第21项/不可用首项/共享锁busy/disabled持久mode。两代次A FACT提交失败→原GET FINISH→永久删除/新成功log→B actual POST窗口追加A原FACT→B FACT独立保留但409零新FINISH/第三POST；是迟到持久观察，不是A网络sender线程在途。done-only另例真实late候选选入，GET解决、业务全库不变、原POST仍一次。三个offset到北京午夜是输入租约比较，不是切Windows TZ；actual fetch_token+巨大TTL503零claim/send，直接ApiError脱敏503。自动跨代次恢复/人工工具尚未闭环。
- Node347实际exit0：84passed/0failed/382.7804ms（79既有+5mode/fence纯测试），日志portal-worker-node-347.log；不冒称实际Node/MySQL进程单活。此后JS未改变。六Py AST与三Node syntax实际通过。无本轮前端变更，不重跑build；旧SQLite336证据保持历史，未把它写成本批重跑。
- 文档静态8篇/29本地引用锚点/3JSON/64T/F20（5P1/15P2）通过，新增I70–I75实施发现另列；strict增量无违规，diff exit0既有LF/CRLF提示。inventory44routes/38候选函数/38hash重算，并实际逐一匹配；是发现清单，非全writer证明。日志portal-v118-{static,conventions,diff,sweep}.log。20:17北京时间no-fetch sweep exit0，只是本地快照：main0修改/1既有未跟踪；own61修改/69未跟踪、无upstream。最终文字记录后补静态/差异检查。
- 339–350所有会话已终态；runtime.scope/datadir/Shutdown complete/零对应mysqld/绝对路径与非reparse检查后，data/temp由升级身份原生清理，pytest scratch由创建者默认沙箱身份清理，均实际成功。未更改ACL、清理其他代理或既有frontend/undefined。日志/runtime/源测试/复用generator保留，无本轮自有测试进程遗留。
- 完整goal active，本批实际worker局部落地及文档审查不等于可上线或完成全T62/T64。下一实质阶段：受管release新旧writer切换/真实process故障恢复；旧删除对账、linked-run和所有回款/intent/allocation/allow-print/maintenance/rawSQL/共享脚本writer；自动跨代次人工处置与更多完整绑定竞态、初始OFF/历史active、全schema迁移回退、真实供应商头与异步/幂等合同、SMTP/COS和B01–B07试点。下一执行号351。

## 客户门户 v1.17 原出库发送、事实与当前授权收尾（2026-10-05）

- 继续完整实现goal，自有codex/customer-portal-dev-docs。新增outbound_execution/outbound_facts，enabled/force synchronize委派新协议，原初始OFF路径保留。prepare捕获全永久request/conversion字段；_finish_verified提取本地helper允许不自行commit及当前finisher归属。P0首次建PI仍不自动占库/外发。main未动，无生产DB/迁移/真实OKKI/SMTP/COS、commit/push/merge/部署。
- 短当前授权/全PI行/财务/receipt/intent/照片全列/任务/删除/谱系捕获→提交→锁外token/cache-only commit→当前绑定pending+不可变START原子commit→锁外完整原order/关联scan/outbound/占号/双回读→当前权限/范围/nonce/租约/完整绑定SEND+sending commit→锁外唯一actual POST parser→force原authority/冻结原request/conversion/原PI/START保存原安全FACT→当前捕获冻结完整原链事实→锁外GET→READ→当前授权、全绑定/原event/nonce及取证前集合比较→验货/召回audit/stale/overlay+FINISH原子commit→当前响应授权。原sender撤权/接管/过期仍留原FACT，但不能业务收尾。全部固定private,no-store分类，known401不刷新重发。
- repair只对规范同原目标accepted且请求已返回的原FACT，missing_only完整证据、一条原新增缺UID、原行ID/成本/handler、前步UID已出现且缺行严格减少、新nonce/父START/原plan与repair-before；unknown/无FACT不自动补。历史ACTIVE缺可信START明确409人工核对，无自动mint/legacy盲repair。实际供应商异步/幂等合同仍未验证，不能由合成accepted证明生产处理完成。
- ORM不可变按持久原PK/旧scope拒绝过期改namespace/修改/删除；Core/rawSQL不由此保护。原FACT同nonce同分类/响应指纹重存保留首observed_at。取证冻结完整SEND/FACT/READ，FINISH解决摘要仅SEND/POST FACT；陈旧READ不永久拦新请求，真实晚POST FACT有当前只GET/REVIEW路径。FINISH保存安全result/后绑定，ACK丢失回读不再递增验货或POST。原warehouse要求恢复并集，有限账号补sub；原姓名来自START，当前finisher召回与updated_by独立于原sender。
- 独立只读审查发现I61/P1无终态FACT却过期repair双外发窗口；I62/P2 GET后冻结集合；I63/P2 expired scope ORM逃逸；I64/P2 lateREAD永久卡FINISH；I65/P2 observed_at重试；I66/P2非法响应ID先accepted；均已对应修订，新增区分测试。主审补I67仓库要求继承、I68有限账号sub、I69当前审计归属。均是本批实施发现，不加入F20设计统计；修复前没有实际运行的发现保持源码发现，不外推真实供应商事故。
- 324/325/326均实际POST前503、未观察预期撤权，1failed/2warnings，27.54/27.47/27.51s，不作为“POST后越权”反例；326阶段标记/零POST限定证据。327/328新源aware/naive租约接入409，均1failed/79deselected/2warnings，23.11/23.26s；328安全日志定位expired TypeError，换北京naive后329实际2passed/79deselected/4warnings/24.28s。失败/前版不计入最终通过。
- 330在3pass后新facts计数未限原record把他单算入（1failed/8warnings/27.27s）；331在21pass后普通event阳性误选他单（1failed/47warnings/48.10s）。两者fixture目标修订，不弱化真实全快照/权限断言，不新增产品finding。332联合175passed/242既有josewarnings/223.30s，333补仓库冻结联合176passed/244warnings/223.46s，均实际终态exit0，不累加。334增加真实有限仓库账号与另一当前finisher归属，实际终态exit0：178passed/247既有warnings/227.44s；为最后漏分支修订前证据，不作为当前最终。335补独立复核两漏分支实际2failed/1passed/46deselected/4warnings/26.42s：已FINISH内部False无403、draft updated_by旧sender；保持原断言，修取证前完整capture/可信START权限继承及所有enabled实际验货版本更新归属，336联合实际180passed/250既有warnings/231.45s，exit0；为下一竞态补强前中间证据。337前置commit后另一手动请求完成双请求红测实际200应409，1failed/46deselected/2warnings/23.24s；修前置完整binding传prepare、首次提交/GET前比较，首末统一executing捕获及终态OR防御。最终338会话67688已观察终态exit0：181passed/252既有josewarnings/232.49s =47execution+3attribution+80prepare+51followup；不累加前版。日志D:/commission-system/tmp/portal-mysql-338.log。
- 实际JWT/ASGI/MySQL、当前DB角色与旧JWT、产品builder、token helper/POST parser、独立连接/HTTP请求/全表快照；供应商HTTP与镜像仍合成。仅原prepare/followup既有选择用例保留actual remote.read/_get_json外层替身，不能泛化为每个GET真实helper。精简表复制actualcolumn类型/default，非全部FK/UQ/126历史迁移。三个输入offset租约比较覆盖北京午夜，不宣称切实际服务器TZ。新跨actorfinisher回归是内部服务非公开新actor链。
- 最后独立源码定向复核对前述修订没有新增具体P1/P2，未代跑/核证332；最后三项身份/归属定向复核发现I67终态早返回与I69 draft更新漏分支；实际335红测证实，两项源码修订复核发现I67前置→prepare竞态；已337实际证实并修订，最终定向只读源码与门控复核无该增量新增具体P1/P2；未代跑或核证338。前置竞态A actualJWT/HTTP、B actualSession内部服务，不称双公开HTTP链。最后只读文字复核指出03统一外部未知503过宽，已区分发送前证据缺失/持久提交不可确认503，以及POST后unknown事实在当前授权下sync_uncertain或完整GET确认sync_done；属于表达修订不新增产品finding。v1.17 README/03/04/06/07/API/tests README同步，8篇/7W/64T/F20(5P1/15P2)不变；实施I系列另列，状态只维护本交接。
- SQLite331实际92passed/46既有warnings/16.79s，仅原改号/验货/补缺相关初始OFF回归；334实际92passed/46warnings/17.74s；336再次helper修订后实际92passed/46warnings/17.76s，exit0，为当前该套最终。336已终态；338 MySQL已终态；SQLite336会话10637已终态，日志D:/commission-system/tmp/portal-outbound-execution-unit-336.log；最后修订仅prepare/execution绑定，legacy helper未再改动。最终静态8篇/29链接锚点/3JSON/64T/F20、strict增量无违规、diff exit0（既有LF/CRLF提示），最后结果文字记录后仅补链接/差异核对；证据portal-v117-{static,conventions,diff,sweep}.log。inventory44路由/36候选函数/29hash已重算，已按最终源码重算，29hash由主线程实际逐一匹配；inventory只是发现清单。324–334 data/temp实际清理成功；pytest basetemp首轮以不同升级身份被文件ACL拒绝，删除前停止；检查属创建者sandbox identity后，用默认创建者身份完成324–334 pytest及331/334 SQLite scratch原生清理，未更改ACL或绕过隔离；335–338各终态/runtime.scope+datadir/Shutdown/零对应mysqld及绝对路径/非reparse核验后，data/temp及pytest/SQLite336 scratch亦实际清理；所有本轮句柄终态，无遗留自有测试进程。日志/runtime/source/复用generator保留。19:12北京时间no-fetch sweep exit0，仅本地快照：main0修改/1既有未跟踪、自有58修改/63未跟踪、无upstream，不代表远端最新。
- 完整goal active。本批实际发送/恢复/repair局部协议落地不代表所有writer迁移或上线。下一实质工作：更完整实际外发锁竞争/repair未知结果/真实process恢复，worker及linked-run，其他local receipt/intent/allocation、allow-print/maintenance/rawSQL与共享脚本writer，初始OFF/历史active人工处置/全schema回退、真实供应商/SMTP/COS及B01–B07经营试点。下一新执行号339。

## 客户门户 v1.16 共享出库准备与私有预览（2026-10-05）

- 继续完整实施goal，在自有codex/customer-portal-dev-docs增加outbound_prepare，接enabled共享preview/synchronize准备、ordinary force跟进和手动仓库入口。main未动，无生产DB/迁移/真实OKKI/SMTP/COS、commit/push/merge/部署。P0建PI不自动外发/占库边界不变。
- 当前员工invoice:sync及PI范围；手动入口额外shipping_inspection:write和当前仓库read_all/业务绑定。首读前拒调用方已有事务，短事务全PI/行/财务/receipt/intent/task/delete/inspection/全photo/原事件捕获→commit释放→锁外供应商证据及双回读→force当前授权/对象/全比较→事件写→私有预览提交后当前响应授权。期中OFF保持force。原ACTIVE计划检查同PI同原目标，不进行新GET，不宣称全历史恢复。
- I58/P1：316实际旧JWT停用后preview错误200（1failed/1warning/23.13s）；I59/P2：319新增跟进查询autoflush再commit，HTTP409但调用方未flush修改持久化（1failed/25deselected/23.13s）。修首读前拒已有transaction/new/dirty/deleted，随后只提交自己建立的只读阶段；ordinary冻结引用防expire隐式事务。其他已开Session的legacy调用方需显式迁移，不能宣称全部兼容或全writer完成。
- I60/P2独立源码审查：非空dict/list/bool头误作商业409，修标量形状503再业务409。24坏头两来源/两窗口、合法EUR/status2差异409对照保留。未声称修复前真实外部事故。所有raw UID在builder前校验，serial/number_only及inspection护栏保留。
- 最终323会话82247 exit0：131passed/132既有josewarnings/166.86s =80prepare+51followup；SQLite323会话37749 exit0：92passed/46既有warnings/17.31s。日志D:/commission-system/tmp/portal-mysql-323.log、portal-outbound-prepare-unit-323.log。两套范围分开，不把前版/失败相加。actualJWT/ASGI/MySQL/产品builder及token helper保留；只有慢fetch一例保留actual remote.read/ensure_access_token/_get_json并替外层HTTP，其余supplier/mirror仍合成。相关表复制实际column类型/default，精简库不证明全FK/unique/历史迁移或真实供应商合同。
- 80项含三撤权×五供应商读窗口及独立authority/PI锁可取、九全绑定来源变化、caller六拒绝/fresh阳性、期中OFF、当前仓库隔离、提交后撤权响应、合法实际sync单POST、recheck零POST、坏扫描/回读与头类型、active同PI/目标，以及四提交故障。独立全快照含ShippingOperationEvent/inspection/photo全列，保持其他业务表逐值。实际sync成功对照不证明后续外发并发授权安全。
- capture提交前失败/真实commit后ACK丢失均503且供应商GET/POST零；新sync_idle提交前0或真实commit后ACK丢失唯一1，其他全表相同；后续实际HTTPpreview200复用唯一事件、POST零。只有Session注入的capture/new idle，不覆盖existing recheck/verified提交、真实process crash。
- 中间317(3)/318(25)/321(97)/322(127)均终态通过但不累加；320在38pass后fixture只看db.new漏savepoint已flush事件，门控未触发HTTP200（1failed/37warnings/62.94s），不是产品撤权证据。改identity_map/new限定原request后通过，保留403和全快照断言。SQLite320的92只是中间回归，最终使用323。
- 独立交易只读审查发现I59/I60与门控缺口并定向复核，无该增量新增具体P1/P2；没有代跑或核证日志。v1.16的03/04/06/07、README、API与测试README同步。设计仍8篇、7W、64T、F20(5P1/15P2)，实施I系列另列。当前进度只维护本交接。
- 收尾静态8篇/29本地引用锚点/3JSON/64T/F20通过，strict增量无违规、git diff --check exit0（既有LF/CRLF提示）；inventory44路由/36候选函数/27源码hash已重算。17:57北京时间no-fetch sweep exit0，仅本地快照：main0修改/1既有未跟踪、自有58修改/61未跟踪、无upstream，不代表远端当前状态。证据portal-v116-{static,conventions,diff,sweep}.log。316–323各终态，逐一确认runtime.scope/datadir/Shutdown、零对应mysqld、绝对目标范围及无reparse，实际删除自有data/temp/pytest scratch；保留全部日志/runtime/源测试/复用generator。source inventory只发现候选，不是所有writer证明。
- 最终独立仅文字定向复核03/04/06/07及本节：无该增量具体残余P1/P2或误关闭；正确限定Session注入、新idle、不同批次计数及旧调用方迁移。未代跑、核证323日志或重审源码。入口打开请求queued，不称已显示。
- 完整goal active。下一实质实现：pending/sending claim、锁外POST、不可变原attempt与迟到事实、当前授权验货/repair，再推进worker/linked-run与全财务/rawSQL/脚本writer。初始OFF、真实process恢复、全历史schema/回退、真实供应商/SMTP/COS和B01–B07经营试点保持开放。下一新执行号324。

## 客户门户 v1.15 队列竞争及出库身份审查（2026-10-05）

- 继续完整实施goal，补本轮开发文档与对抗审查；本地Codex自有worktree，main未动，无生产DB/迁移/真实OKKI/SMTP/COS、commit/push/merge/部署。前轮局部107项不是整体完成。
- queue最终取得authority/PI/task后，独立撤权线程exact CONNECTION_ID在actual InnoDB data_lock_waits等待。commit-first队列+audit保留，撤权生效后响应403；rollback-first503全business相同。commit只放行目标task的status/reason/last_error/updated_at及一条outbound_queue audit，其他逐表逐值相同；再次旧JWT403且快照不变。附件/最新日志/原代次/删除事件四来源变化、扫描未完成及订单回读变化拒绝；ShippingOperationEvent独立全列快照，不误称business涵盖它。
- 309会话85934 exit0：51passed/53warnings/80.47s；独立审查发现first全快照及删除事件覆盖缺口，强化后310会话55109 exit0：51passed/53既有josewarnings/79.01s。原43+新8，不累计两批；实际JWT/ASGI/MySQL，供应商依旧合成边界。这些特定queue竞态已补证，关联外部writer仍开放。
- I56/P2纯index('0100')311实际未抛ValueError，1failed/75deselected/1warning/1.29s。规范正整数/ASCII≤64、拒bool/非正/前导零/Unicode/浮点/符号/空白/坏集合及同值重复。312会话51750 exit0完整87passed/41warnings/17.14s（原72+15）；这是前版纯plan局部证据。
- 独立审查又指出原本地UID被builder int洗白和verify int/text误判I57/P2。313终态exit1：3种本地非法UID actual route preview错误200，合法text outbound ID actual sync变sync_uncertain；4failed/87deselected/6warnings/2.10s。仅HTTP断言观察，不外推未执行的后续零写断言或真实provider事故。修_prepare在state.lock/builder前严格原UID并组判重，canonical source_items贯穿_snapshot；verify双侧canonical。
- 314会话9665 exit1：87passed后新测试错误期待400，实际已有router ValueError409契约；1failed/42warnings/16.14s。只改新测试状态码到409，保留builder0/POST0/UID/events不变。315会话49982 exit0：最终92passed/46既有warnings/16.76s；87+3实际预览非法拒绝+1合法同步回查+1missing_only合法混合阳性。原72/87/92不相加。_pc_client注入身份、SQLite及sync_case供应商/产品builder为替身，不宣称真实JWT/MySQL/provider。无前端改动，无额外build。
- 独立最终只读复核确认两快照缺证、原始UID来源及载体比较局部修订闭环，本批无剩余具体P1/P2；未代跑或核证日志。v1.15 README/03/04/06/07/tests README与源码发现清单同步，8篇、7W、64T、F01–F20(5P1/15P2)不变，实施I01–I57另列。
- 本轮日志D:/commission-system/tmp/portal-mysql-{309,310}.log、portal-outbound-identity-red-{311,313}.log、portal-outbound-identity-final-{312,314,315}.log保留；反例/准备错误不计通过。静态、strict、diff及本地no-fetch sweep收尾后记录。
- 收尾静态8篇/29本地引用与锚点/3JSON/64T/20F通过，strict增量无违规、diff exit0（既有CRLF提示保留）；inventory41路由/36候选函数/25hash。17:10北京时间no-fetch sweep exit0，仅本地快照：main0改动/1既有未跟踪、自有57改动/60未跟踪且无upstream，不代表远端当前状态。证据portal-v115-{static,conventions,diff,sweep}.log。最终独立文字定向复核无新增具体P1/P2，未核证日志；补64位限制同样适用于int的精确措辞。309/310及311–315均终态，runtime.scope/datadir/Shutdown和对应进程不存在核验后仅清自有数据/temp与一次性写入脚本；日志/runtime/源测试/复用generator保留，没有其他代理数据或新后台服务残留。
- 总体goal active。关联出库外部POST/验货/实际worker、linked-run及全财务/rawSQL/脚本writer；旧持久plan非法身份/active原发送后恢复、初始OFF、真实process恢复、完整历史schema/迁移回退、真实供应商/SMTP/COS及B01–B07试点保持独立开放。下一实际执行号316，不把局部身份/queue证据当全I52/T62/T64或上线门禁通过。

## 普通同步后续排队授权实施（2026-10-05 13:22 北京时间）

- 前轮1.13详细文档/审查为有效progress。本轮继续完整实现goal，在自有codex/customer-portal-dev-docs实现outbound_followup_execution并接普通enabled推送force_authority=True；默认legacy linked/初始OFF调用方不变。共享原关联出库tail提取_follow_existing，未将其外部writer视为已改造。无前端/迁移改动，main未动，无commit/push/merge/部署或真实外部effects。
- 短事务当前invoice:sync/scope+全PI/行/财务/附件/task/linked/产品/成功原及最新create-update日志/删除事件捕获→提交释放→供应商order/outbound/inventory/回读→rollback/expire→force当前授权及全比较→queue/outbound_queue审计原子commit→当前响应授权。当前403/404/409/503固定/no-store，原普通POST已成功及START/FACT/FINISH保留，不以HTTP失败诱发重发。期中OFF仍force协议。
- 独立交易审查发现I53删除证据关联不足及同PI另一目标generation、I54缺商业字段错误409，修订payload原outbound/订单/task与规范原日志目标验证、shape先503；I55新审计动作17字超String16，经304合法对照失败定位，改14字outbound_queue。regenerate原ID同PI同原target成功create/update，最新也需可信原引用；无引用不猜测。最终源码定向复核未发现本批新增具体P1/P2，审查者未代跑或核证308。
- 实际304会话97871 exit1：9撤权pass后正常齐货失败503，1failed/9passed/10warnings/33.21s；305会话29320 exit0：91passed/103warnings/122.25s；306会话26283 exit0：102passed/114warnings/134.15s；307会话61043 exit1：同PI历史777777代次借给当前970008实际错误200，1failed/38deselected/1warning/23.21s。307在HTTP断言即失败，不推断之后read计数/任务断言通过。失败/前版数字不计入最终通过。
- 最终308会话19600 exit0：107passed/119既有josewarnings/139.44s，43followup+64ordinary。actual JWT/ASGI/MySQL/独立连接及原ReceiptIntent/stock/parser保留，供应商HTTP/fetch、存储/镜像仍替身。43覆盖三权限变化×三读窗口、正常齐货/缺货、商业/UID/task/intent变化、可信删除及generation与非法借用、worker接管、期中OFF、shape503/商业409、锁外authority/PI/task可取；两例恢复actual remote.read/ensure_access_token/_get_json只替外层fetch/httpx.get，含401force刷新撤权；其他read整边界替身，不混同。
- queue before_commit和实际commit后lost_ack故障503：原PI保持synced/原订单；队列+审计同时0或1；直接内部followup恢复后audit仅1、原POST仅1。此为Session注入和内部服务恢复，不是公开HTTP恢复或真实进程崩溃。I52定向撤权反例已有局部修复证据，但最终提交竞争和全链门禁仍开放，不能宣布整I52/T62/T64完成。
- 相关SQLite305会话3030 exit0：现存出库核对72passed/41warnings/14.61s，仅helper提取回归。无UI代码变化，不重跑build；该套不证明new force路径。v1.14 README/03/04/06/07/API/tests README同步，原1.13状态标历史。inventory41路由/36候选函数/24hash，仅发现清单，不是全writer证明。
- static8篇/29本地引用锚点/3JSON/64T/20F通过，strict增量无违规，diff exit0（既有CRLF提示）。13:21 no-fetch sweep exit0，仅本地快照own54修改/60未跟踪、无upstream；main0修改/1既有未跟踪。证据D:/commission-system/tmp/portal-mysql-{304..308}.log、对应runtime.json/mysql.log、portal-followup-unit-305.log、portal-followup-308-{static,conventions,diff,sweep}.log。最终交接记录后补静态及diff核对。
- 最终1.14独立定向文字复核无本项具体P1/P2及过度闭环，未核证日志；主线程检查及实际结果维持上述范围。
- 本轮304–308均终态；ErrorActionPreference Stop、各runtime scope/datadir、Shutdown complete和对应process absence核验后清各data/temp和pytest临时目录/单次生成脚本；保留源测试、日志、runtime、复用generator。没有清理其他代理或既有frontend/undefined。
- 后续完整goal仍active：最终queue先持authority后撤权实际等待及commit/rollback、扫描/回读/附件/delete/generation事实变化；再按阶段改造关联outbound POST/验货/实际worker、linked-run及全部本地财务/rawSQL/脚本writer，初始OFF、真实process恢复、完整历史迁移/回退、真实供应商/SMTP/COS及B01–B07试点。局部107通过不缩小总体范围或当作可上线。

## 客户门户1.13详细开发文档与对抗审查交付（2026-10-05 12:57 北京时间）

- 本轮人类请求为“按以上方案生成详细的开发文档并进行对抗性审查”。仅完善文档与源码发现清单，未修改产品、未新启业务写测试；此前完整实现goal仍未完成，本轮文档交付不等于关闭实现目标。R01–R06、8篇/7工作包/64验收契约保留。
- 读取前批303实际终态exit1：1failed/1既有josewarning/23.16秒。实际JWT/ASGI/独立MySQL，库存GET替身窗口中独立事务撤销员工；原POST已提交一次，最终HTTP403，但waiting_stock→pending业务快照变化。登记I52/P1开放，不称修复，不推断真实外部出库。保留portal-mysql-303.log、runtime.json/mysql.log和源回归用例。
- README/03/04/06/07升级1.13：区分原推单成功、后续履约授权和响应鉴权；队列/reason/error/generation属新动作，短事务全绑定→锁外GET→force当前鉴权及全比较→迁移/审计原子commit；完整代次/删除/财务/原事实守卫，当前拒绝零后续写。已有出库编辑执行器及实际worker协议单独开放，客户P0建PI仍无外部写或自动出库。
- 独立身份审查无新增具体契约P1/P2；独立交易审查指出409验收允许200/manual歧义及重复不POST身份过宽，统一固定403/404/409/503并限定同一已捕获代次/后续恢复。最终定向只读确认闭环，未代跑新测试/核证303。历史20项F设计发现与I52实施发现分开，I52尚无实现修复证据。
- 主审静态8篇/29本地引用与锚点/3JSON/64T/20F通过；strict无新增违规，diff exit0（既有LF/CRLF提示）。inventory41路由/36候选函数/23hash仅发现清单，已加入followup和shipping outbound同步执行器。12:55 no-fetch sweep exit0：own53修改/59未跟踪、无upstream，main0修改/1既有未跟踪；只是本地快照。证据D:/commission-system/tmp/portal-doc-v113-{static,conventions,diff,sweep}.log。最终文档记录后再检查链接/约定/差异。
- 303日志实际Shutdown complete及runtime/datadir归属确认；第一次普通沙箱CIM读取及临时目录删除受限，不能以其输出Removed称清理完成；升级后ErrorActionPreference=Stop实际验证零对应mysqld，303data/testtemp均不存在。保留日志、元数据、回归源及可复用生成器。README打开请求queued，不称已显示。没有生产连接/迁移、真实OKKI/SMTP/COS、commit/push/merge/部署。
- 实现后续：修复并验证I52所有实际队列分支，再按独立阶段完成既有出库POST/验货/worker、linked-run及全财务/rawSQL/脚本writer、真实process恢复、完整迁移回退和B01–B07试点；本轮文档审查通过不关闭整体T62/T64或可上线门禁。

## 原推送安全摘要与迟到 ready 恢复 UI（2026-10-05 12:33 北京时间）

- 前轮普通推送I49–I51修复/验证为有效progress。本轮继续完整goal，只改order_push_facts.summary、lifecycle_router.detail、InvoiceLifecycle.vue及其隔离测试/文档，不改变普通POST/恢复守卫、迁移、价格、库存、公司权限或生产。自有codex/customer-portal-dev-docs，main既有内容未动。
- GET lifecycle enabled分支在当前invoice:admin与对象范围后只SELECT未解决原事实，增加六字段order_push_summary：review_required/pending_attempt_count/last_observed_at/result_class/original_order_id/resolution。规范唯一原已accepted引用才显示，时间+08:00，坏历史字段固定安全分类/日志，无token/载荷/指纹/原正文/事实全文；关闭门户null。resolution只是提示，POST仍完整当前auth/lease/商业/附件/库存/collection保护。
- 现有“更多→取消 / 恢复”可由ready进入；新section/prompt固定服务端原引用与resolution，只填写10–500字依据，旧sync-uncertain/resolve只GET原单不再次推送。未知无引用不提供解除按钮，失败只读原任务；403/404清私密，401统一清token跳转登录。identity签名含id/roles/permissions，同账号角色或动作变化也清drawer/prompt并拒绝旧返回；close/unmount/invoice切换同样。错误焦点、Escape取消返回trigger、成功按钮消失回读按钮；64位原ID窄屏换行，无新动画。沿用现有功能组件与token，未将隔离harness默认Element主题截图当真实品牌页面验收。
- 实际MySQL296：summary+ordinary recovery+ordinary execution三文件，93passed/147既有josewarnings/125.60s，会话4679终态exit0；保留actualJWT/ASGI/独立MySQL、原token helper/parser/ReceiptIntent/stock服务，仅供应商fetch/HTTP及legacy followup边界为替身。10新summary用例含空摘要零外发/全业务不变、bound/unbound原引用与恢复后风险清除、四状态不给resolution、当前停用/动作/范围旧JWT403/404 private/no-store零旧私密响应。该93含既有83，不与前轮171相加；范围与provider/fullschema限制继承。
- 原共享GET授权回归MySQL300选cancellation_refresh的read_lifecycle/read_do_not_keep：6passed/31deselected/12既有warnings/28.96s，会话54036终态exit0。选择含GET/POST当前停用/旧角色/范围断言，不代表整个取消suite重跑或新真实供应商proof。本轮不重复无关SQLite全套。
- 最终实际组件301 reduce /302 no-preference三宽1440/390/320均exit0（会话47734/89100）；各宽19GET/5模拟resolve，strict body/原引用、500字与不足10字零写、unknown不出现核对按钮、503仅GET零自动重发、失败重复焦点、关闭/成功返回焦点、旧POST换actor及旧GET换invoice均等待response.finished后无当前副作用、GET403/404/mutation403清私密、同actor角色清依据、统一client401跳转合成login。最终errors/unknown检查置401后，每宽零pageerror/未知API、页面/抽屉无横溢出。focus/fill+Enter是处理器/焦点验证，不冒称全程Tab可达。
- 原取消UI298三宽每宽11读/2模拟refresh、旧GET/POST隔离、拒绝及prompt清理通过（会话22104exit0）。构建2963330模块/21.52s，handle51979exit0，保留既有auth混合导入/500k chunk警告。源码后续未再改变，只补强浏览器fixture和文档。新截图302/order-push-320.png已实际目视，原ID可换行、控件在drawer正文滚动区可达；不能替代真实页面/字体/生产移动浏览器验收。
- 失败历史保留：295在8pass后撤权夹具误传3实参（1fail/28warning/32.28s，64636exit1），改调用既有demote_admin(editor,codes)，保持实际权限写/断言；296浏览器**/api/**误拦/src/api模块导致空白timeout（38966exit1），改根/api/；297已加载但测试在drawer打开时点遮罩外open而timeout（5433exit1），改使用可见读取按钮，并强化拒绝/旧GET；299三宽通过但末尾pageerror检查早于401，独立审查指出后移断言，301/302是最终强化证据，不累加299。
- 两位独立只读复审：后端当前授权、字段白名单、只读/原恢复守卫；前端捕获原目标、身份/依据/迟到/focus与测试区分力，修复末尾401证据缺口后无新增具体产品P1/P2。未代跑或核证最终日志，不背书fullRBAC/worker。F设计仍20、I实施仍51，不为测试fixture错误新增产品发现。
- 详细契约1.12同步README/03/05/06/07及API/MySQLREADME；仍8篇。inventory41routes/34service candidates/21源码hash，生成器已重算，不作完整writer证明。strict exit0，静态8篇/28引用锚点/3JSON/64T/20F passed，diff check exit0既有换行提示保留。21个最终源码hash实际匹配；12:35 no-fetch巡检exit0，仅本地快照53修改/59未跟踪、无upstream，main0修改/既有1未跟踪不动；不证明远端最新。295/296/300逐一核验runtime/Shutdown/无对应进程及非reparse绝对路径后，owned data/temp/basetemp清理成功，保留日志/runtime；3217无监听，已完成一次性脚本清理，复用inventory生成器及源码/截图/失败和最终日志保留。
- 隔离预览3217只绑定127.0.0.1，createServer禁用backend proxy，所有根/api/响应为合成；初次plain-pipe预览启动后exit0，未把它视为live；重新以TTY获得73538，实际验证均用该实例，发送stop后已终态exit0。所有本轮MySQL/build/browser句柄均已实际终态，不继续poll或重启旧库。
- 后续完整目标仍active：普通legacy followup、linked-run、实际worker、全财务/维护/rawSQL writer、初始OFF、process crash、完整126历史迁移/旧制品回退、T49/T53/T54、完整页面真实API/经营数据、真实供应商/投影/SMTP/COS及B01–B07/双业务员双客户试点。已接通局部ready恢复，不将它当上述门禁全部通过。无生产连接/迁移、真实外部effects/发信、commit/push/merge/部署。下一新库303。

## 普通推送原子 claim、迟到事实核对与删行身份 I49–I51（2026-10-05 12:06 北京时间）

- 继续已授权完整实施目标；上一v1.10详细文档与设计审查为progress。本批仅自有codex/customer-portal-dev-docs worktree，产品新增order_sync_execution/order_push_facts，接入enabled router.sync及sync_recovery，inventory.prepare允许commit=False原子claim；无迁移/前端修改。文档1.11同步03/04/06/07、README、API参考、MySQLREADME与源码候选清单。
- 普通推送先强制当前员工/动作/范围/永久谱系捕获，释放锁获取凭证，最终完整商业/明细/任务/回款/附件/库存绑定比较；claim同事务准备ReceiptIntent、库存reserve、原token/key/lease及START。claim提交不确定零POST。锁外actual POST parser仅known401允许一次刷新、重鉴权后重发；未知不重发。原安全FACT先独立提交，不因旧员工撤权/租约过期/接管丢结果；只有原owned完整绑定才业务收尾，FINISH在真实持久DATETIME精度捕获后保存。凭证cache实际commit并复用；没有authority/PI/stock锁跨凭证I/O。
- accepted先保存已知原订单；UID整组验证或actual stock finalize失败保留uncertain及原预占，不释放为未创建。真实reserve/finalize/release服务与ledger测试保留；既有outbound_followup.safely_run整体边界为替身，未证明该执行器/worker当前授权或供应商effects。
- I49/P1：known accepted禁止人工clear/另绑，JSON重置不能绕过START；REVIEW按当前事实集合身份，FINISH/REVIEW只解决同集合，lateFACT使旧核对失效。I50/P2：迟到ready合法unbound使用detached原引用整组纯验证后镜像bind，bound/unbound均回写canonical UID，严格ready/not_synced或synced/synced，draft及活ReceiptIntent lease拒绝；不自动恢复stock/receipt/worker/publication。GET期间新FACT/当前授权或完整绑定变化409零核对写。
- I51/P2独立审查发现删行快照漏检：正常编辑保留原UID，builder会将0501/全角转换为501 remove。293实际HTTP/MySQL反例得到200（期望409），1failed/54deselected/1warning/23.11s，会话88961已终态exit1。修复prepare在reconcile/token/claim前解析原始list[dict]并canonical校验每个UID及组唯一性；9非法snapshot零token/POST/START/全业务不变，canonical700删除成功单POST清快照对照保留。不是禁用删除或弱化断言换绿色。
- 最终294实际联合MySQL：test_mysql_order_push_execution.py、test_mysql_order_push_recovery.py、test_mysql_sync_recovery.py，171passed/212既有jose弃用warnings/215.45s；会话39274已观察终态exit0。SQLite受影响7模块192passed/26既有warnings/35.89s，会话94971终态exit0。日志portal-mysql-294.log、portal-push-unit-294.log保留。实际bcrypt/JWT/ASGI/独立MySQL、tokenhelper、POST parser、receipt及stock服务；供应商fetch/HTTP及迟到原GET商业证据合成，owned okki_orders为精简表，完整upstream FK/schema与真实供应商合同未证明。
- 额外区分性验证：慢token窗口独立锁/停用/范围/商业/UID/附件/意图/任务变化；POST期间cancel/lease/takeover、in-flight OFF强制SQL锁序及响应撤权；实际commit前失败/真实commit后ack-loss的claim、FACT、FINISH有界恢复零/单POST；重叠capture单claim/POST；真实人工clear/bind后accepted迟到再次核对、GET中新FACT集合拒绝；伪造原actor/inventory/receipt/executiontoken留证拒绝。普通重叠线程测试未声称wait-table证明；原sync_recovery suite的真正InnoDB等待维持其既有范围。
- 中间结果仅历史、不累加或冒充最终：287两项通过，288普通40及SQLite192，289实际合法迟到unbound被错误409（1failed/44passed/71.08s），修detached验证后290联合147/186warnings/186.21s。291在50passed后测试锁序表名误写invoice_conversions而StopIteration，1failed/77.06s；保留断言改真实conversions，292联合161/202warnings/203.18s，均在I51修复前。最终171涵盖旧88，不能再相加。
- 独立交易只读审查提出并定向确认I49–I51源码修订及测试区分力闭环，没有修复后新增具体P1/P2；未代跑/核证最终日志。1.11文档范围复核未夸大全T62/worker/初始OFF/前端ready。F01–F20仍5P1/15P2设计发现；I01–I51实施发现，各具体闭环不关闭全验收。
- 当前inventory 41路由/34候选函数/21源码SHA256，已重算匹配，只是发现材料不是全writer证明。最终静态8篇/28本地引用锚点/3JSON/64T/20F通过，strict及git diff --check exit0，既有LF/CRLF提示保留。12:04 git_sweep --no-fetch exit0，本地快照本任务53修改/58未跟踪、无upstream，main0修改/既有1未跟踪未动，不证明远端最新。证据portal-push-294-{conventions,static,diff,sweep}.log。
- 已核验287–293各终态、isolated runtime.scope/datadir、Shutdown complete、非reparse绝对目标且无对应mysqld进程后，只删owned data/temp/pytest basetemp，保留日志/runtime；294同样已核验终态/Shutdown/runtime路径/无对应进程，data/temp及最终pytest临时目录清理成功；已完成的一次性写入脚本清理，复用inventory生成器保留。所有源码/实际反例/最终测试证据保留。
- 未完成：前端安全摘要及迟到ready恢复入口；普通legacy followup、linked-run、实际worker、所有财务/维护/rawSQL writer、初始OFF、process crash、完整126历史迁移和旧制品回退、T49/T53/T54、真实供应商/投影/SMTP/COS、B01–B07和双业务员双客户试点。无生产连接/迁移、真实OKKI/邮件/文件effects、commit/push/merge/部署。总体goal active，不以本轮局部实现或文档交付标complete；下一新库295。

## 客户门户 v1.10 开发文档与对抗审查交付（2026-10-05 11:20 北京时间）

- 按当前用户详细开发文档与对抗审查请求，本轮仅修改 README/07、源码发现清单与交接，保留产品工作树。8篇文档覆盖架构/权限、数据模型、API、交易状态、双端UI、W01–W07、64条验收及20项设计发现；README补完整业务链路与开发边界，R05统一完整提案→客户接受→有权员工PI。
- 两位独立审查者本轮分别只读复核权限/公司共享/邀请撤权/映射/私密UI及金额/期限/命令回放/竞争/唯一建票/后续发布/迟到事实，未发现新增可复现P1/P2设计矛盾。未运行产品测试或核证历史业务日志；F01–F20的5P1/15P2为设计修订，不关闭实现或生产门禁。
- 当前发现清单按实际源码重新计算41路由/33候选函数/21摘要，包含此前新增order_push_facts/order_sync_execution及semifinished.invoice_service。新普通推送执行分支和恢复钩子尚无本轮测试证据；不得使用strict或文档复核充当业务验证，也不得在无证据情况下称正常sync已收口。继续实现时先审查/验证该批库存、回款意图、原执行事实和外发授权边界，再处理linked-run/worker，不改真实业务库。
- 静态8文档/28本地引用锚点/3JSON/64T/20F passed；strict与diff exit0，既有换行提示保留。11:19 no-fetch巡检最终exit0，本地快照53修改/58未跟踪，无upstream；main既有未跟踪1未动。普通沙箱首次因写自有tmp看板失败，获准后原命令完成。日志D:/commission-system/tmp/portal-doc-v110-{static,conventions,sweep}.log及可复用inventory生成器保留。
- 本轮未修改产品、启动数据库或业务测试、生产操作、真实OKKI/SMTP/COS发送、commit/push/merge/部署。详细文档请求已交付；总体实现goal仍active，正常sync/linked-run/worker、全writer、初始OFF、故障恢复、完整历史迁移/回退、真实供应商及B01–B07试点未完成，不将本轮文档完成标为总体实现完成。

## 客户门户同步核对UID修复与分阶段实际验证（2026-10-05 10:55 北京时间）

- 本轮恢复总体实现goal，上一轮v1.8文档与pure反例为有效progress。先新增有区分力的真实JWT/HTTP/MySQL反例：两条不同product/SKU、无本地UID、全部商业条件匹配、远端501/0501。282会话68480已观察exit1，实际错误200/ready/not_synced而预期409，1failed/46deselected/1warning/23.08s。不是仅假设缺陷；失败断言之后的快照断言未执行，不能推断那次其他断言通过。
- I48/P2：uncertain_recovery新增_canonical_uid，真正int或canonical ASCII正整数文本、无前导零、长度用实际InvoiceItem.xiaoman_unique_id String64；bool/非正/float/指数/空白/符号/Unicode/缺失/超长拒绝。verify_existing纯copy验证全组唯一身份、原UID锚定及完整商业/金额后返回，再交原_assign_unique_ids。规范化不改输入或ORM。非法明细/UID固定409；原订单缺失或order_id身份不可信503，受控错误private/no-store，无上游正文。
- 最终实际MySQL286会话21932已读exit0：88passed/97既有jose弃用warnings/114.23s，完整test_mysql_sync_recovery.py。UID20种非法/重复/别名HTTP全快照零写及合法int/str/mixed规范赋值/重复单次日志；三个resolution初始当前授权和状态/原租约；linked活租约/错误归属/状态/指针；GET期间新增活push/linked lease；业务实际commit后独立连接确认唯一结果再停用/降scope，403/404且原业务不变、无私密响应；两个原单capture只有一次verify；本地bind/clear实际flush→commit门→distinct第二连接performance_schema等待→200/409唯一日志。镜像缺失/错客户/错名称仍拒绝。
- token用例保留actual ensure_access_token和lifecycle_remote.read，仅fetch_token/request供应商边界替身。在慢fetch期独立连接用1秒行锁限制实际取得authority+PI并停用员工，最终403/业务不写；外部阶段rollback使临时token未提交。其他GET仍完整证据替身，owned okki_orders为精简表（actualSHOW/SELECT+schema指向隔离库），没有真实供应商或完整生产schema/唯一约束证明。无外部POST/DELETE，不创建新的F20attempt。
- 失败/准备证据保留、不计通过：283会话18214 exit1，77passed/1failed/84warnings/104.23s，固定901被先前成功PI绑定，postcommit场景尚未进入响应门；改每PI bind_target=900000+id，不弱化duplicate保护/实际镜像查询。284会话88577 exit1，83passed/1failed/91warnings/116.87s，本地恢复不递增文档版本导致旧通用gate不启动；改本次new恢复日志+真实flush状态commit门。285会话51540 exit1，83passed/1failed/92warnings/114.95s，bind savepoint重复after_begin被当第二连接；改先收集第一root/savepoint单一ID，再要求distinct第二ID并保留真实锁等待。最终286另建新库全88通过，不累加前版数量。
- 相关SQLite283会话21762 exit0：132passed/26既有warnings/28.07s，身份纯验证24项及lifecycle/protocol/linked/screenshot相关108项；自该运行后产品代码未再变化，仅测试夹具和文档修正。无前端改动，不重复无关build/浏览器。
- 独立交易只读审查未发现本批新增产品P1/P2，提出版本gate及savepoint观测缺陷并定向确认修订闭环；v1.9最终文字范围无过度结论。审查者未运行或核证MySQL/SQLite日志，终态主线程实际读取。I48只在本批原单核对路径闭环；F01–F20仍5P1/15P2设计发现，I01–I48实施发现，不能据此关闭整条T62。
- 8篇文档README版本1.9，03/04/06/07与API/MySQLREADME同步；当前进度以本交接为准，1.8开放记录保留为历史。候选inventory重新计算41路由/28服务函数/18源码hash，只是源码发现，不是全writer证明。静态8篇/29链接锚点/3JSON/64T/20F passed；strict286 exit0无增量违规；git diff --check exit0，保留既有LF/CRLF提示。
- 证据：D:/commission-system/tmp/portal-mysql-282.log至portal-mysql-286.log，各同号runtime.json/mysql.log；portal-sync-unit-283.log，portal-sync-286-conventions.log/static.log。pure初始281反例脚本/log与最终源测试保留。280/282–286已逐一核验Shutdown complete、runtime datadir+isolated scope、绝对目录/非reparse及无mysqld，只清data/temp；自有280/283 pytest临时目录清理，元数据/失败日志/复用候选generator保留。
- 下一实际风险入口：router.sync_invoice仍先旧get_invoice/visibility后synchronize；sync_coordinator在receipt arm/prepare库存/本地收尾多次commit再invoice锁；xiaoman_service在push_attempt.begin后fence与push_order交错，before_send没有当前员工/完整门户谱系阶段授权。下一批须按真实现有调用链落实捕获/凭证/最终授权claim/锁外POST/原结果事实/响应授权，保留库存及回款语义，不用“初始授权检查”替代整条执行证明。linked-run/outbound worker及所有本地财务/rawSQL/脚本writer同样仍开放。
- 最终10:55 git_sweep --no-fetch exit0，仅本地快照：本任务52修改/56未跟踪、无upstream，main既有未跟踪1未动；不证明远端最新状态。一次性282–286与已替代280生成脚本清理，源代码/源测试、失败及最终日志、runtime、UID纯反例和可复用候选生成器保留。
- 总体未完成：上述正常sync/linked-run/worker，初始OFF、真实提交确认丢失/process crash、全历史126切换材料、T49/T53/T54、真实投影/供应商及B01–B07/SMTP/COS试点。无生产连接/迁移、真实外部effects、发信、commit/push/merge/部署。本轮是实际修复及验证progress，goal保持active，不将局部门禁或文档交付标为整体complete。

## 客户门户v1.8详细开发文档与对抗性审查交付（2026-10-05 10:33 北京时间）

- 当前人类请求为“按以上方案生成详细的开发文档并进行对抗性审查”。本轮修改文档和源码候选证据，不推进产品修复；工作树既有实现修改保留。8篇开发文档涵盖架构/权限、模型、API、交易状态、双端前端、工作包/64验收及对抗记录。README版本1.8，API与测试README同步；02/05已覆盖相应领域，未作无关改写。
- 已确认：英文客户站、中文管理端；客户请求→业务员完整提案→客户接受→有权员工正式PI。登录/权限在方舟配置，客户公司与业务员范围隔离，客户别名只映射稳定标准SKU、服务端价格；经营默认B01–B07依旧需试点负责人填写，不播种原型数据。
- I47/P1记录前批sync_recovery/prepare_recovery的当前授权与锁外confirm_existing接入；bind_order/confirm_not_created为首次未绑定原状态的本地人工核对，无外发。强制authority→身份→永久request/conversion→invoice锁序，捕获/最终完整商业/任务/分摊绑定，业务commit与当前响应授权分开；尚缺证据不能当此入口完整通过。
- I48/P2开放实现缺陷：独立交易审查指出原字符串判重接受501/0501数字等价UID。主线程实际pure verify_existing使用两行无本地UID、不同product/SKU、全部价格数量金额匹配，得到UID_ALIAS_ACCEPTED，未调用数据库/HTTP/供应商。D:/commission-system/tmp/portal-uid-alias-281-proof.py与portal-uid-alias-281.log保留。03/04补canonical ASCII正整数、拒绝前导零/bool/float/Unicode等、仅内存规范化、全验证后写；06补真实HTTP原状态/UID/attempt/linked/分摊/日志零写与不同合法UID成功对照。产品未修复，不因文档修订关闭I48。
- 四类额外缺证保留：初始及期中活sync/linked租约；成功业务commit后响应撤权/降范围不误rollback或回旧私密结果；actual token helper慢窗口；两个重叠confirm_existing及本地bind/clear单次迁移。03固定基本订单身份不可解析503、同原单明细/UID非法或商业不一致409；新增验收禁止宽状态集合掩盖差异，历史测试不倒推符合新契约。
- 续接时核对280终态日志：实际MySQL43passed/46既有warnings/66.03s；相关SQLite108passed/26既有warnings/27.96s，先前会话47073/40038均exit0。不是本轮新跑数据库用例，不累加历史批次。280仅get_db替换，实际bcrypt/JWT/ASGI与独立MySQL；remote.read整个替身且token禁止，仅证明该观察窗口锁外；自有精简okki_orders+实际SHOW/SELECT，仅schema改隔离库，不证明真实经营投影/供应商合同。上述43/108不覆盖I48或四类缺证。
- 两位独立审查者先审旧文档，再定向读落地v1.8。身份/范围/保密及交易/提交/规范UID契约均无本轮剩余具体P1/P2文档矛盾；两者未运行测试或核证日志。F01–F20仍5P1/15P2设计发现，I01–I48是实施发现且I48开放；不称“全部对抗审查通过”。
- PI候选清单已按当前源码重算：41路由、28服务函数候选、18源码hash，新增sync_recovery/edit_authority；只作发现材料，pending精确保留sync-uncertain缺陷/缺证、正常sync/linked-run/worker及财务rawSQL/脚本，非全writer证明。复用生成脚本portal-pi-inventory-281.py保留。
- 本轮最终检查实际exit0：8篇/29本地链接与锚点/3JSON/64T/20F静态通过；strict增量无违规；git diff --check无空白错误（保留既有LF/CRLF提示）。10:33 git_sweep --no-fetch仅本地快照，本任务52修改/55未跟踪、无upstream，main既有未跟踪1未动；不声称远端最新状态。证据portal-docs-281-static.log/conventions.log/sweep.log。仅清本轮已完成一次性文档生成脚本，保留开放I48的复现脚本/log、候选生成器及280恢复材料。
- 文档交付与总体开发goal区分：本次文档和审查请求可交付；正常sync、linked-run、worker、初始OFF、真实进程崩溃恢复、全部财务writer、完整126历史切换材料、T49/T53/T54及B01–B07/SMTP/COS试点仍开放。无生产连接/迁移、真实外部effects、发信、commit/push/merge或部署。整体goal保持active，不能由文档交付更新complete。

## 客户门户出库恢复当前授权与完整绑定（2026-10-05 01:54 北京时间）

- 本批实际进展：新增invoice/outbound_recovery.py，enabled lifecycle.outbound_retry/ack采用当前权限/范围捕获→锁外取证→最终重新授权及完整绑定。初始/最终force authority与永久谱系/PI锁序，拒绝已有事务/待写对象并清提交后的旧缓存；期中OFF不退回旧鉴权。retry只将原明确未发送/漏建任务排队，不新建已创建/删除/uncertain任务或清delete_pending/regenerate标记；ack记录本版本核对，整体manual但出库done时也不能重复覆盖原确认。
- I44/P1旧JWT及持锁取证；I45/P2 legacy hash遗漏币种/总额/UID；I46/P2远端None→500、缺失order_id被当无关联。当前捕获额外remote.invoice_binding、order_type、产品行/UID、完整原task/latest operation及状态/cancellation；Core三门控保持旧hash/portal版本不变仍409。find_related显式形状和可信数字订单引用校验；缺失/null不判无关联，固定503/无正文。共享pure summarize_documents比较算法保留，非新的供应商写入。
- 最终实际MySQL279会话61888 exit0：248passed/370既有jose弃用warnings/291.14秒。八文件：outbound71、remove44、refresh37、lifecycle34、editor54、edit-race/source/download合计8。真实bcrypt/JWT/ASGI+独立MySQL事务，仅get_db替换；外部无真实发送。独立连接在order/outbounds/receipts/token慢窗口实际取得authority/PI后撤权/改版/改绑定/改任务/取消；原请求403/409且快照不变。两重叠capture仅一次queue/ack迁移，in-flight OFF实际SQL观察authority/request/conversion/invoice序。
- token用例保留实际ensure_access_token和首次remote.read，fetch_token/_get_json替身；回款和关联出库观测仍合成。形状用例保留实际find_related扫描，remote.read/_read_details为证据替身。retry另读完整回款，ack不新查回款。token回写在外部阶段结束rollback，临时token没有进入业务结果；供应商合法无关联格式、外部系统时点一致性及实际worker执行未验证。
- 失败及前版证据：274错误把撤权标签字符串传给接受权限list的helper，1failed/2passed/26.16秒；275实际空订单None→500反例1failed/32passed/55.76秒，修为验证一次订单后单独读回款；276错误要求停用账号也有ArkUser FOR UPDATE，1failed/44passed/67.83秒，调整为在authority下当前拒绝且不锁无权PI，成功分支仍完整锁序；277此前范围56passed/78.87秒；278 token设置id1重复插入夹具冲突1failed/57passed/82.44秒，改幂等准备后新库279全通过。失败/准备错误不计通过，前版数字不累计。
- 最终相关SQLite279会话28779 exit0：134passed/1既有Starlette弃用warning/14.38秒，lifecycle/protocol/linked/outbound/receipt protocol。274的91passed与278的134passed为前版回归，不累计。无前端改动，不重跑无关构建/浏览器；上一批实际UI/build证据保留原范围。
- 独立交易定向源码及1.7文档复核：指出I45与未知订单引用边界，修订后无本批剩余具体P1/P2；指出token夹具重复PK后修复，最终文档缩窄token/scanner替身范围及两动作回款差异。审查者未运行MySQL/后端测试，也未核证279日志，主线程实跑终态。F01–F20仍5P1/15P2设计发现，I01–I46为实施发现。8篇v1.7及API/测试README已同步，当前进度仍只在本交接维护。
- 检查：strict会话21330 exit0无违规；8篇/29本地链接与锚点/3JSON/64T/20F静态通过；diff check exit0。inventory41路由/28服务函数候选/16源码hash，只是发现材料。01:52 git_sweep --no-fetch exit0，仅本地快照（本任务50修改/54未跟踪，无upstream），main既有未跟踪1未动。
- 证据：D:/commission-system/tmp/portal-mysql-279.log，portal-mysql-run-279/runtime.json/mysql.log，portal-outbound-unit-279.log，portal-outbound-final-279-conventions.log/sweep.log；274–278失败和前版日志/runtime保留。自有实例274–279 Shutdown、runtime/datadir/isolated scope及无mysqld核验后清理data/temp；pytest临时目录与本批生成脚本清理，保留runtime、最终源测试、生成清单脚本及日志。没有动他人目录/既有undefined。
- 总体未完成：其他sync/uncertain/linked-run、实际outbound worker和全部财务/raw SQL/脚本writer的T62；初始OFF、实际process crash恢复、完整126历史切换材料、T49/T53/T54相关真实环境门禁与B01–B07/SMTP/COS/试点。下一实现应按实际阶段检查sync协调器及worker授权/结果事实，不用本地queue证据背书远端执行。无生产连接/迁移、真实OKKI/SMTP/COS effects、commit/push/merge/部署；goal保持active，本轮为有实际产物及验证证据的progress。

## 客户门户1.6开发文档及remove定向实施复核（2026-10-05 01:23 北京时间）

- 当前：8篇文档同步至1.6，F01–F20维持5P1/15P2设计修订；新增I39–I43实施反例及边界。GET/POST生命周期安全投影、remote remove原执行日志/终态核对已落实；当前进度仅本交接维护，历史各批数字不可相加。整体实现目标active；文档交付完成不等于所有64条或可上线。
- remove：当前授权捕获→锁外预读→最终授权/财务证据→原claim提交→锁外一次DELETE+readback→原事实/状态提交→重新当前授权响应。force屏障/lineage保留in-flight OFF锁序。原START/FACT/RECONCILED/FINISHED复用不可变AuditEvent，无新迁移。旧租约/接管/绑定变化只追加原事实，不覆盖新任务/PI/发布；终态核对集合变化409且零追加。事实三次有界重试；commit实际成功但ACK丢失按FINISHED+当前绑定/状态摘要回原结果，不重复DELETE。原日志防取消JSON重置再次删除/未外发abort；token不返回或进入新同步日志；安全时间+08:00。
- 实际MySQL最终run271会话23568 exit0：177 passed/294既有jose弃用warnings/210.50秒，七文件remove44、refresh37、lifecycle34、editor54、edit-race/source/download合计8。真实bcrypt/JWT/ASGI和独立MySQL连接，get_db覆盖，外部token/OKKI读写替身。run268 20passed、269 75passed、270 174passed为前版范围，不能累计。最初267旧JWT返回200反例1failed保留；最终当前拒绝和零effect/快照断言覆盖。真实process kill和真实OKKI未运行。
- 最终SQLite272会话10818 exit0：962passed/2skipped/14warnings/106.92秒，portal及invoice lifecycle/protocol/linked/outbound/scope/module/amounts、receipt management/protocol受影响回归。skip不计通过；依赖utcnow警告保留。
- InvoiceLifecycle：安全远端摘要与本地状态分别展示；终态待核对只refresh，未知结果禁新写并允许读取，403/404清数据并聚焦固定错误，重复503再聚焦。独立审查I43指出全局原因prompt跨身份/对象遗留，改组件自有dialog，清上下文/原因且确认再验身份。旧GET/POST按actor/invoice/generation拒绝迟到副作用。
- 最终浏览器273会话49440 exit0：真实Chrome1440/390/320全部通过，每宽11模拟读取/2模拟refresh，API未知入口零、pageerror零；身份/对象变化清旧原因、不追加写，旧response.finished+两帧验证迟到无副作用。272已通过但截图处于动画，补等待transform结束及面板viewport边界后273最终几何1440:(840,600)、390:(23.40625,366.59375)、320:(19.203125,300.796875)，320/390最终截图已实际查看。初轮271路由glob误拦/src/api导致blank mount exit1，修仅base/api后通过，不算产品失败。harness为合成身份/合成API，不证明真实RBAC/持久化或全app身份切换。build272会话24013 exit0/18.17秒，既有bundle大块警告保留；dist没有测试harness。
- 独立交易只读源码复核未提出本批剩余具体P1/P2，独立前端最终确认I43闭环，无新增具体P1/P2；两者未代跑MySQL/Chrome/后端回归。1.6文档最终只读复核结果另附下文，不能外推整体T62。
- 最终独立文档定向复核：两处P2文字冲突已修订，04明确claim异常先停止503、后续查证，事实保存不以当前员工权限为前置；06标注历史时点并指向1.6。独立审查者确认这些措辞范围闭环，无剩余具体P1/P2，未运行测试/核证实际日志。
- 证据：D:/commission-system/tmp/portal-mysql-271.log、portal-mysql-run-271/runtime.json/mysql.log、portal-unit-272.log、portal-lifecycle-build-272.log、portal-lifecycle-ui-273.log及同名目录result.json/retained-*/current-*截图；strict portal-final-273-conventions.log、sweep portal-final-273-sweep.log。静态8篇/29链接与锚点/3JSON/64T/20F通过；strict无违规、diff check exit0。inventory刷新41路由候选/27服务函数候选/14源码hash，仅发现清单非全writer证明。01:21 sweep --no-fetch exit0，仅本地快照（49修改/53未跟踪，无upstream），main既有未跟踪1未动。
- 清理：自有MySQL268–271实际Shutdown complete，runtime/datadir/isolated scope及无mysqld核验后只删各data/temp；保留日志与元数据。270/272 pytest临时目录和本次已替代生成脚本清理；保留复用runtime/generator、源测试和最终证据。Vite47964通过Ctrl-C退出，3212实际connect拒绝。既有frontend/undefined未动。
- 未完成：全T62的初始OFF和其他retry/ack/sync/uncertain/linked-run、所有本地财务/raw SQL/脚本writer；真实process crash恢复、完整历史迁移126切换材料、T49/T53真实缓存/经营身份、T54旧制品，以及B01–B07/真实SMTP/COS/试点。无生产连接/迁移、真实外部effects、发信、commit/push/merge/部署。上述不构成本批文档交付阻塞，也不关闭总体开发目标。

## 客户门户v1.5开发文档与对抗审查交付（2026-10-05 00:26 北京时间）

- 当前人类请求为“按以上方案生成详细的开发文档并进行对抗性审查”。本轮仅修订README/02–07与本交接，不推进既有实现goal、不改产品；8篇文档覆盖架构权限、数据模型、API、交易状态、双端前端、工作包及64条验收、审查记录。当前累计F01–F20仍5P1/15P2，设计修订与实施门禁分开。
- 1.5细化F20：AuditEvent.public_id对应逻辑event_id，claim提交不确定先结束原事务并按原attempt查证、不盲DELETE；DELETE响应/readback分别留证；期中关闭门户仍强制完整谱系锁序；事实独立提交再授权私密响应；retained保留安全待核对摘要、当前授权只读refresh追加不可变核对证据、不恢复PI发布。独立交易复核提出核对期间新增事实P2，改为捕获attempt/fact集合、最终变化409/零reconciled追加/风险不清，补观测后提交前与核对后两种迟到验收。
- 两位独立审查者分别只读身份/范围/映射/展示与交易/提交/状态/事实竞争；修订后定向复核无相应剩余具体P1/P2文档矛盾。未跑业务测试、未背书历史结果，不能称实现审查全部通过。
- 读取前批已启动267（session18479）终态exit1：test_stopped_admin_real_jwt_cannot_send_delete实际1failed/2jose既有弃用警告/23.06s，停用管理员旧JWT的remove响应200、remote_deleted而预期403。此为开放P1实现缺口；断言在status即失败，未执行后续调用计数/业务快照断言，不推断其通过或具体模拟调用数。OKKI读写为替身，无真实外部删除。D:/commission-system/tmp/portal-mysql-267.log和portal-mysql-run-267/runtime.json/mysql.log保留；Shutdown complete+无mysqld+datadir归属/绝对边界核验后，仅清该实例data/temp。
- 文档静态8篇/29引用锚点/3JSON/64T/20F、strict和diff通过；00:27 no-fetch巡检exit0，仅本地快照：主目录0修改/1未跟踪，本任务48修改/49未跟踪，无upstream；不作为远端最新状态证明。README在Codex打开请求返回queued，不把queued称已显示。未新启业务测试、生产连接/迁移、真实发信、commit/push/merge或部署。
- 后续实现恢复：从开放remove当前授权、F20原attempt/分项事实/迟到风险与核对集合开始（下一隔离运行编号268），并保留回款writer、其他sync/uncertain/linked-run、T49/T53/T54/T62/T64、完整历史迁移及B01–B07真实试点门禁。现有总体开发goal继续active；本次文档与设计对抗审查交付完成，不将267失败或文档闭环作为实现完成。

## 客户门户通知纯键盘反馈与恢复（2026-10-04 19:21 北京时间）

- I32/P2：243现有构建实际GET503错误出现却未聚焦。NotificationDialog补具名读/发状态、aria-busy、重复反馈聚焦/卸载守卫、申请后具名原因聚焦及原生横向滚动；MappingDialog/PortalOrders补关闭回原按钮的原对象/可见/启用/代次守卫。只改三组件交互，command/notificationDelivery与后端未变，未知命令冻结和原key/body保持。
- 244管理端build3330模块/16.52s通过，保留既有auth/reportCenter混合导入及大chunk警告。248 mapping/no-preference、249 order/reduce、251 order/no-preference、252 mapping/reduce加强版均三宽1440/390/320通过/pageerror0，每宽7模拟POST与6GET。20行/40total、500字原因、重复503/409聚焦、真编辑撤确认/光标移动不撤、手机方向键横滚、unknown/Escape/beforeunload冻结、403/503/wrong scope后原命令相等、匹配回执后当前记录、关闭焦点及父草稿均断言。245–247补强前运行不用于迟到场景、不累加。
- 加强场景实际GET门控→键盘关闭通知→Tab移到父层另一控件→放旧请求并等fulfill+两帧→新焦点不变/读6写7；关闭会abort读取，证明取消/卸载路径，不证明强制不可取消旧响应进入Vue或身份切换。API全合成且未知端点仍默认响应，不作真实RBAC/DB commit-loss/SMTP或严格未知路由拒绝证明。完整弹窗与页脚控件几何通过，390截图已查看。
- 250旧订单通知10场景3模拟写、映射通知12场景4模拟写通过；命令/通知/映射19项Node通过。独立源码及门控补强复核无新增具体P1/P2，审查者未代跑或核证底层结果。日志portal-notification-build-244.log、portal-notification-ui-248/249/251/252.log与各result.json/截图、250三回归日志保留；243反例日志保留。
- 收尾strict/diff通过，8篇/24引用/3JSON/64规格/19设计发现静态检查通过；19:24 git_sweep --no-fetch成功，仅本地快照（任务44修改/48未跟踪，无upstream）。81890预览会话已exit1，由主动Ctrl-C结束，3211 socket连接拒绝确认关闭。最终390/320截图已查看；仅清理245–247补强前重复PNG，保留其日志/result和243反例，最终248/249/251/252截图完整保留。
- README/05/06/07同步I32范围。T48/T50/T51仅补通知流程；其他UI、T49/T53真实身份/代理缓存、T54兼容旧制品、T62全PI入口、T64远端/部署性能、完整历史迁移126切换材料和B01–B07试点仍待证据，整体goal active。无生产连接/迁移、实际发送、push、merge或部署。

## 客户门户行锁超时与整笔回滚（2026-10-04 19:03 北京时间）

- I29–I31：新增lock_timeout.py，只给参与authority的MySQL事务设置PORTAL_LOCK_WAIT_SECONDS（默认5，1..30）；1205转安全TRANSACTION_BUSY/503并标记禁止提交。根提交/回滚/关闭及真实Pool reset恢复原会话值，失败连接失效；外部Connection/savepoint commit守卫先物理rollback，避免SQLAlchemy root失活后跳过实际回滚。main只注册该异常，覆盖上游取得屏障后的UPDATE等待；关闭门户、其他DB/SQL错误与非参与1205不变。
- 242最终六文件真实MySQL：46 passed/41.97s。实际屏障/后续行等待、全rollback、同连接恢复、外层savepoint拒绝提交、raw pool关闭、恢复失败丢弃、客户POST503/原键GET404/201/200唯一单、员工PUT未注册500/注册503、四类邮件prepare超时原事件重试均通过；保留慢SMTP替身/PDF竞争验证。100独立连接创建1/回放99，submit-through-commit P95=929.19ms/P99=958.64ms/max=968.90ms；authority等待P95=761.62ms/P99=789.19ms。证据D:/commission-system/tmp/portal-mysql-242.log与portal-mysql-run-242/duplicate-submit-evidence.json；本地合成上游，不能作为生产SLA。
- 239全门户SQLite714 passed/2 skipped/4既有弃用警告、76.58s；跳过需显式运行的浏览器测试，不算通过。236重复模块fixture导致重复迁移已消除；237系统temp权限用新的自有basetemp解决；238测试默认编码损坏改显式UTF8；240真实30/hour共享测试IP限制改各合成客户独立loopback、限额不改；241初版邮件测试claim先被屏障挡住，改真实claim提交门、prepare实际等待门、释放屏障再finish，242四类成功。232/234产品反例及233观测错误保留日志，失败不计通过。
- 独立交易只读审查及最后定向复核未发现新增具体P1/P2；指出的上游503、真实Pool归还、邮件时序缺口已解决。审查者未运行MySQL；242由主线程实跑。01/03/04/06/07及API/测试README已同步，设计F01–F19计数不变；全局实施状态只在本交接维护。
- 最后独立文档复核新增I29–I31/T64：无具体P1/P2契约矛盾；未代跑或核证日志，不扩大实际验证范围。
- 收尾：strict/diff及8篇/24本地引用与锚点/3JSON/64规格/19设计发现静态核验通过；19:04 git_sweep --no-fetch成功，仅本地快照（本任务44修改/47未跟踪，无upstream）。全部自有mysqld已退出，各232–242存在的mysql.log实际Shutdown complete；经runtime归属/绝对路径核对只清理这些实例data/temp，保留日志、runtime与242负载样本，不影响他人数据。
- 范围：时限仅InnoDB行锁，不是元数据锁/连接池/整请求/网络时限。本地库存为同库镜像，没有远程库存客户端，不能声称实测慢远端库存。仍待其他UI、T49/T53真实经营身份/代理缓存、T54兼容旧制品、T62所有PI入口、完整历史迁移126合法切换材料及B01–B07/真实试点；本组不关闭T64全条或整个目标。无生产连接/迁移、真实发信、push、merge、部署；goal保持active。

## 客户下单门户开发文档交付复核（2026-10-04 18:20）

- 按当前用户“按以上方案生成详细的开发文档并进行对抗性审查”请求，只更新本组文档和交接记录，保留既有产品改动。8篇v1.3包含架构/权限、字段模型、API、交易状态、双端前端、工作包与64条验收、对抗审查；README摘要明确完整提案→客户接受→员工审批生成PI。
- 两位独立审查者分别只读核对身份/范围/映射/前端恢复与交易/回放/PI/通知/回退，均无新增具体P1/P2契约矛盾。累计F01–F19设计发现5P1/14P2维持文档层修订闭环；未运行业务测试或背书历史数量，不作实现/上线保证。
- 本轮静态8文档/24本地引用/3JSON/64T/19F、strict与diff检查通过。未推进T64产品修改；T49/T53/T54/T62/T64、全历史迁移及B01–B07经营/真实试点仍待各自完成证据。文档交付完成，既有开发实现goal继续active；无生产连接/迁移/真实发信/commit/push/merge/部署。

## 客户下单门户统一发布接入准备（2026-10-03）

- publish.py增加portal_install使用pnpm冻结锁/ignore-scripts，build_frontends(include_portal=False)仅活跃static_targets包含frontend-portal时打开；默认不要求pnpm。platforms仅pending，不选实际domain/host；remote_static固定root增加/var/www/ark-static/customer-orders。未激活nginx模板仅客户API、其余API404、TLS/缓存/可信header边界；backend环境模板五开关false、秘密/绑定空。deploy/customer-orders.md记录前置条件，deploy/README、frontend-portal/README、06同步。
- 独立审查发现P2：门户产物误传办公室，旧live无目录时rename失败。修为办公室仅frontend/frontend-pm/pm-lan，门户仅登记云目标，新增旧live缺目录回归；最终53 passed/7.44秒（发布构建/协调/源码）。初轮pytest父目录不存在，创建规定.deploy_state后重跑通过，无业务放宽。独立定向复核P2关闭无新增P1/P2。
- 新backend/tests/portal/test_proxy_peer.py三项真实Uvicorn middleware构造scope测试通过：清XFF保持可信peer、未清导致改peer拒绝、公网直传伪造XReal拒绝；不是Nginx实机联调。router注释同步可关闭中间件或可信入口清头。真实Settings验证环境模板关闭且无秘密。
- 实际pnpm11.25.0在全新.deploy_state/portal-offline-build冻结安装与Vite29模块build通过；离线先因供应链策略元数据缺失失败，再用发布器原命令读取注册表元数据后通过，未关闭策略/未跑依赖脚本/未升级版本。产物.deploy_state/portal-build-artifact与现有客户build文件名一致，保留制品。strict/diff通过，无产品前端构建逻辑变化。
- 未运行发布、SSH、nginx -t/重载、TLS申请、生产迁移或邮件。Nginx只模板，无域名/TLS/后端归属登记，试点三项问题仍待回复；不以此当真实配置授权。此前126历史迁移门禁未解，不重复无证据重跑。整体目标active；剩余实际目标配置、部署候选代理验证、历史基线/切换材料、经营配置及完整试点。

## 客户门户历史迁移链实测与剩余门禁（2026-10-03）

- 新增显式test_mysql_full_chain.py/conftest --portal-full-chain；只允许单独选择该文件，混跑收集时UsageError（实际检查触发），默认15 skipped。自有新库空表断言；仓库database/auth_init.sql 7张及dingtalk_init.sql 2张实际DDL，无账号seed；原Alembic env与command.upgrade，Settings仅改自有连接/库，连接白名单仍生效。没有stamp/downgrade/迁移函数替换。
- run012原空库停020缺ark_users，实际committed019；发现早于Alembic的仓库SQL初始化后加入真实DDL，run013通过122，在123维护要求处停止；独占实例没有应用/worker writer，按其真实前提设置ARK_TIME_MIGRATION_MAINTENANCE=1（pytest恢复），run014通过125_invoice_integration，126缺customer_cutover_contract被原guard拒绝。1 failed/44.96秒，绝不计为全链通过。chain-result.json complete:false保留修订和表清单。
- 独立交易只读审查无新增P1/P2，确认异常传播、只有head+屏障seed通过才complete:true，123条件真实，126未绕过。README/06已同步实际失败、运行方式及范围。当前没有足够证据生成126切换批准，不伪造文件；完整链仍需合规隔离基线/完整切换测试材料，门户172/173与14项服务/UI的独立通过不受影响。
- 已异步询问用户三项试点输入：首批客户/业务员/商品范围；合同价/USD/起订步长/库存安全余量；域名/邮件服务。尚未回复，不据沉默授权真实配置或部署。可继续部署配置准备及剩余隔离交易场景，整体目标active，不满足blocked阈值。
- 本批只增加测试与说明，无产品历史迁移变更、生产连接、发信、push、merge或部署。012–014日志/runtime/chain-result需保留，临时data/temp在确认进程退出后清理。下一次不得重复无证据重跑126，更不能把跳过guard当迁移验证。

## 客户门户真实员工JWT与中文管理端联调（2026-10-03 14:39）

- 新增test_mysql_browser.py/portalLiveEmployee.browser.mjs，MySQL夹具加入真实登录日志/refresh表及显式浏览器参数。实际bcrypt登录、JWT签发/验签、角色权限、中文管理端登录表单和审核弹窗接同一回环后端，仅override get_db；待审核请求通过实际客户/业务服务预置，无API拦截。独立API contexts登录管理员/其他业务员，不替换当前页面refresh cookie。随机测试凭据经stdin，未用生产凭据。
- run010单项9组27.05秒通过；最终run011整体14 passed（28.09秒，13项jose utcnow依赖弃用警告），普通默认14 skipped。真实UI审批128 USD PI、旧命令回放、另一业务员列表0/详情404、篡改JWT401、实际管理员停用员工后旧JWT读取/审批回放403、关闭详情后刷新列表清空并展示权限提示；实际数据库唯一PI/明细/回款草稿/转换/发布/回执及登录日志/refresh记录断言。1440/390/320弹窗无溢出，最终390截图已查看。
- 联调发现PortalOrders只映射AUTH_FORBIDDEN，补真实ACTION_FORBIDDEN中文提示；主站3322模块build通过，保留既有chunk/auth混合导入警告。run008末步关闭按钮使用英文名称错误，修为真实抽屉按钮；run009中文诊断被默认GBK解码破坏，显式UTF-8后可定位/验收，没有放松业务断言。独立审查及最后定向复核无新增P1/P2，注释private detail改为实际验证的private list。
- README/06已同步。strict/diff、静态8篇/23链接/3JSON/64规格/17发现通过，14:39 git_sweep --no-fetch仅本地快照。确认无mysqld，008–011 data/temp及已替代a/b/c截图清理，保留运行日志/runtime和最终live-employee-final截图。无生产迁移/发信/push/merge/部署。
- 范围：本机HTTP不证明生产TLS/Cookie；预置请求不代表该用例完成双端全链路；关闭抽屉后刷新列表不证明自动清除仍打开详情或refresh身份隔离；上游合成约束/库存辅助夹具限制保留。Node正常失败可关闭Chrome，Python强制超时下Chromium子进程树清理未证明。
- 下一步完整历史MySQL迁移链/剩余竞争边界与真实试点配置（B01–B07）；最终完整试点/部署尚未完成，整体目标active。JWT+中文审核UI这一项已取得真实联调证据，不能继续将其泛称未接通。

## 客户门户真实 MySQL 服务并发验证（2026-10-03 14:26）

- 本轮继续实现目标，修正前批服务夹具缺CustomerSourceRecord/CustomerContactRelationship上游表的准备错误，保留真实客户绑定查询，不放松产品鉴权。mysql_service_fixture.py创建真实角色权限并执行auth登录/报价，test_mysql_services.py直接调用实际下单、提案、接受、审批、建票及员工停用。未修改产品业务实现。
- 8项服务并发run-006通过（22.22秒），整套run-007 13 passed（22.48秒）。重复提交/审批均覆盖首事务提交和回滚；客户停用/提交、员工停用/审批各覆盖两个先后顺序，撤权后审批回放拒绝；检查订单、128 USD PI/明细/回款草稿/转换/发布/命令回执/通知各一条。每例通过performance_schema证明第二独立连接真实锁等待，无Python串行锁。默认无参数13 skipped。
- 独立交易审查只读核对：无具体P1/P2，真实RBAC/binding/服务调用与锁等待证据成立。边界：直接调用服务/endpoint函数，未运行JWT/HTTP Depends；撤权只覆盖账号disabled及员工is_active=False，不等同逐项角色/权限撤销全覆盖。上游表合成宽松列结构，未还原全部约束/默认值/历史迁移；库存与部分发票辅助查询为夹具。门户172/173表保留真实迁移约束。README/06同步范围。
- strict/diff及静态8文档/23链接/3JSON/64规格/17发现通过，14:26 git_sweep --no-fetch为本地快照。确认无mysqld进程且007日志Shutdown complete；清理005–007的data/temp，保留日志/runtime.json和可复用8.0.46运行时。无生产连接/迁移/发信/push/merge/部署。
- 下一步真实员工登录JWT与中文管理UI连接同一后端，完整历史迁移链及剩余竞争边界；B01–B07经营配置/试点仍未完成，整体目标active。新MySQL运行必须另建全新目录，不能复用007。

## 客户门户开发文档交付复核（2026-10-03 14:19）

- 本轮用户范围为详细开发文档及对抗性审查。交付docs/requirements/2026-09-30-customer-order-portal下8篇v1.2；独立只读复核F01–F17保持设计闭环，无新增未解决P1/P2。静态8文档/23链接/3JSON/64验收规格/17发现、strict与diff通过；git_sweep --no-fetch通过，仅本地快照。未推进生产变更或扩大为实施完成。
- 恢复时读取了上一批隔离MySQL服务级测试会话19987结果：run-005在首项fixture阶段失败，缺少ark_customer_source_records表，1 error，尚未执行服务并发断言。新增mysql_service_fixture.py/test_mysql_services.py及对应conftest改动保留为未验证工作；不得把其8个用例计入已通过结果。后续实施应补完整隔离上游fixture后另建运行目录重测，不能删减业务绑定检查。此前基础MySQL 5 passed证据不变。此次没有为文档交付继续扩大数据库测试。
- 本次文档任务已交付；实现总体验收、完整MySQL迁移链/业务并发、真实员工JWT与中文管理端联调、B01–B07经营配置及试点仍未完成。无push、merge、真实发信或部署。

# 当前交接与待办

## 客户门户真实 MySQL 隔离验证基础（2026-10-03）

- 新增backend/tests/portal_mysql：只接受已验证mysqld路径和不存在的新目录，自有隐藏进程、--no-defaults、新datadir、127.0.0.1随机端口、MySQLX关闭、随机root凭据，建库前校验实际datadir/port/bind/version；测试结束SHUTDOWN或仅终止自有Popen。显式启用时才装SQLAlchemy/PyMySQL白名单，finally恢复；默认5skipped后同进程SQLite SELECT1成功。拒绝带backend/.env的运行，不使用生产连接或凭据。
- 官方MySQL8.0.46 ZIP MD5 003f527d5df61b663ff191038cd676bd匹配，mysqld Oracle签名Valid。下载跳转页故障后使用其官方CDN直链，运行时放D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/供后续复用，不装系统服务。实际004新实例5 passed（15.14秒），进程退出后查询mysqld计数0。收尾核验路径/归属后清理001–004临时datadir与已解压ZIP，保留runtime.json/mysql.log及可复用程序；runtime中的datadir为历史记录，不可当存活实例。
- 实际172/173 upgrade DDL成功，列名/null、FK/ON DELETE、CHECK名称、UNIQUE列集合与模型一致，既有PI-LEGACY/新增document_version=1保留，barrier初始1。最小五个上游锚点不是完整历史迁移链；未比较所有类型/普通索引/默认值/CHECK表达式，不证明生产schema兼容。
- 两条并发测试各commit/rollback两分支，独立连接、InnoDB REPEATABLE READ，performance_schema.data_lock_waits按第二连接ID观察实际等待。barrier后读取提交的禁用版本/回滚的原版本；唯一命令冲突1062且败方此前Account修改整体回滚，或首事务回滚后等待者提交。没有Python串行锁；仍未证明实际审批/撤权/提交业务的并发端到端，也不是既存旧RR快照恢复测试。
- 初次按ArkUser ORM普通int构造锚点导致FK3780，核对054真实历史迁移后修正为unsigned；不是门户迁移缺陷，生产文件未改。初次fixture被两个测试模块注册，已移到单一mysql_schema/conftest入口。并发测试递增barrier导致后跑种子断言失败，移至迁移刚结束时断言；完整003/004均5 passed。每次使用新datadir，未stamp/downgrade/覆盖部分DDL。脚本直接执行时app导入路径失败后改为backend的python -c runpy验证，未改应用导入。
- 独立只读审查无具体P1/P2，定向复核确认scoped guard恢复/默认skip不影响连接、迁移断言时序及CHECK/UNIQUE新增断言正确。README与06文档同步证据边界；strict、diff通过。无生产迁移/发信/部署/push/merge。没有前端或产品后端改动，不重跑无关构建；此前611服务测试为历史结果。
- 下一步把当前自有MySQL运行时用于真实服务级提交/接受/审批与撤权并发，及完整历史迁移/版本表门禁；真实员工JWT+中文后台联调、B01–B07经营配置和试点仍未完成，目标active。运行004runtime.json位于D:/commission-system/tmp/portal-mysql-run-004/，可据README新建后续运行目录。过去“未发现本机MySQL运行时”已被本批安装的免安装测试运行时取代。


## 客户门户真实交易闭环与长编号布局修复（2026-10-03）

- 新增test_live_browser_trade.py/liveTrade.browser.mjs，与认证测试共享live_browser_server.py。客户真实构建UI选品→报价→提交→接受提案→下载PI；员工提案/审批真实HTTP，员工身份和principal仍为夹具，不是员工JWT/中文管理UI联调。初始会话由真实auth服务夹具创建，经stdin给Node；无API拦截。库存observation、外部flags/等级/编号和末端valid-SKU查询mock，SKU源/价表是隔离SQL，客户binding真实；SQLite列复制/串行锁不证明迁移/并发。
- 交易1 passed（9组检查，最终4.39秒）：27×3=81，加运费45/包装2=128；确认前审批409；重复提交200 replay与重复批准只产生一张PI；其他合成actor读取/批准回放404。实际DB断言1请求/Invoice/InvoiceItem/ReceiptIntent草稿/Conversion/Publication；InvoiceItem标准product/sku/ST/color1和27/81保持，RequestLine和解析PDF保留Silk Collection/Midnight与128。完整认证测试在共享server提取后1 passed（10组，63.46秒），结束时有浏览器关闭引起静态资源ConnectionAbortedError，所有断言和监听器退出检查仍通过。
- 实际生成长编号暴露窄屏溢出：先补换行，视觉复核再将主标题改为Your order request.，完整编号作为small Reference保留；request-number/order-command-notice/session-notice允许换行，无裁剪编号。最终29模块客户站build通过；真实1440/390/320提案、390/320回执及320已发布/命令通知无溢出，390截图已查看。未改产品后端交易逻辑。
- 测试准备曾将重复提交错误期望201，按真实契约修正200；订单查询get_settings未指向夹具导致功能开关默认关闭，修正为同一隔离设置，补actual available_actions断言；未放宽产品权限或绕过验收。独立交易审查无具体P1/P2，建议的实际InvoiceItem断言已补并通过；独立定向复核确认长编号UI修复及实际InvoiceItem断言无新具体问题。
- 普通选择运行两项网络测试2 skipped（需显式运行时参数）；首次在仓库根误跑缺app导入，改在backend按约定运行通过。此前全门户611是上一批历史结果，本轮仅网络与布局变化，不重复全量。strict/diff通过，README/06文档同步边界与命令。无生产连接/迁移/邮件/push/merge/部署。
- 下一步隔离MySQL迁移与双事务竞态、真实员工JWT与管理UI接同一后端、B01–B07经营配置及试点；整体目标active。最终截图/PDF在本任务scratch admin-orders/live-trade-run-f/test_browser_checkout_customer0/，保留作为证据。


## 客户门户真实 HTTPS 认证联调（2026-10-03）

- 新增 opt-in test_live_browser_auth.py + liveAuth.browser.mjs：真实构建客户站、临时 HTTPS 回环代理、真实 Uvicorn/客户路由；代理从独立回环地址进入且覆盖 X-Real-IP，后端不自动采信代理头。没有客户 API 拦截。真实公司/身份/负责人绑定检查，隔离内存 SQLite，测试框架拒绝全部非 SQLite 连接及带 backend/.env 的 checkout。
- 真实浏览器 1 passed（10 组检查，63.41 秒）：Secure/HttpOnly/__Host Cookie、脚本不可读及不落存储、session no-store、伪造代理/Origin/CSRF 拒绝、双标签退出、复放旧 Cookie 被服务端拒绝、重新登录后停用账号失效。OTP 从测试本机加密 outbox 读取，未发 SMTP；停用操作的员工 principal 为夹具。测试 QA 路由只存在 pytest app，生产应用与前端代理无此入口。SQLite 串行锁不证明 MySQL 并发，自签证书不证明部署 TLS 信任链。
- 初次缺 Uvicorn，在现有隔离虚拟环境安装项目要求的 0.34.0；系统 pytest 临时目录权限失败后使用已核验全新的本任务临时目录。第二次登录触发真实60秒冷却，现保留限频并实际等待61秒；补充响应断言初写200，核对实际异步契约修正为202。导入与tmp_path仅在显式opt-in后执行，普通套件可正常跳过。不更改产品鉴权或放松断言。
- 独立只读审查：无新增P1/P2；Python AST/Node语法通过，确认真实路由/绑定与测试入口隔离。常规成功和失败有finally关闭监听器和浏览器；Python强制子进程超时情况下Chromium进程树清理仍属于测试工具边界，本次实际成功结束。frontend-portal/README及06实施文档同步运行方法与证据范围。
- 全门户回归611 passed、1 skipped（该显式opt-in浏览器测试）、2项既有Query.get警告；真实浏览器已另行通过，不重复累计为612条服务测试。strict与diff通过；本批产品前端未改变，沿用本批前已完成的29模块构建。无生产迁移、发信、push、merge或部署。
- 下一步隔离MySQL迁移与双事务竞态，并继续完整客户下单/审核/PI真实后端联调。只读核对PATH、Windows服务、Program Files及本项目tmp未发现mysql/mysqld/docker，不代表全盘无可用运行时；可继续准备隔离环境与验证材料，不以此标blocked。B01–B07真实经营配置与试点尚未完成，整体目标保持active。



## 客户门户上游入口覆盖与MCP凭据竞态修复（2026-10-03）

- 本轮审计实际auth/customer/insight/Agent/Invoice写调用链（含ORM、批量SQL及原始SQL搜索）。发现关键Agent身份写已有authority锁，但mcp/token_admin凭据发放/轮换/撤销未参与，且旧管理JWT可绕当前权限；已在三个写端点首个业务查询前加入begin_employee_authority_write(mcp:admin)。与critical身份写共用锁，凭据变更/屏障版本同事务；无新增提交点、迁移或响应格式变化。门户关闭时维持既有行为。
- 新增test_token_authority.py八例：三入口旧JWT首读前拒绝、三入口当前权限成功与屏障版本同提交、轮换提交失败新凭据/旧凭据/版本一起回滚、撤销后身份写拒绝。加原Agent事务两例共10 passed。通过禁止所有非SQLite连接的运行器运行原MCP接口3 passed（1既有anyio弃用警告）。本轮后端局部验证，不重复全门户；上一批603为历史全量，不包含新增8例。
- 独立授权审查核对角色/权限/启停、客户合并/拆分/归属转交、身份和来源投影链，无新增具体P1/P2，相关37 passed（2既有Query.get警告）。独立交易审查核对普通PI编辑、行替换、取消/同步恢复/回款恢复、永久关联及唯一bulk更新（仅xiaoman_removed_lines同步缓存），生命周期13+作废22=35 passed。补充PDF字段/冻结快照核对及MCP修复定向审查无新问题，token8+下载12=20 passed。各批测试有重叠，不累加成总覆盖数。
- 01权限/04交易/06验收及API参考补入口矩阵、协议配置与证据边界。PDF当前映射/目录不参与已发布内容，抬头/行/金额按冻结快照和指纹复核；模板/Logo/字体仍属于部署资源回归。员工profile/password/avatar旧JWT未检查active/deleted属识别出的既有全平台自服务边界，不把本次门户权限审计扩称全部平台认证已安全收口。
- strict、diff和静态8文档/23链接/3JSON/64规格/17设计发现检查通过；13:10北京时间git_sweep --no-fetch仅本地快照。无前端改动，不重复构建；无push/merge、生产写入/迁移/邮件/部署。
- 下一步启动本机隔离后端与真实浏览器Cookie/Origin/受信代理联调（现有frontend-portal已存在，之前多为模拟API）。随后隔离MySQL迁移与双事务竞态、B01–B07真实经营配置及完整试点。当前PATH未找到mysql/mysqld/docker，不能以SQLite证明MySQL并发；尚有其他本地可推进任务，不标blocked。整体目标active，未上线。



## 客户门户通知追踪与受控恢复（2026-10-03）

- 新增notification_admin_service，GET /orders/{request_id}/notifications按实时read+employee_query订单范围分页，仅业务源事件/business_mail；不返回邮箱、payload、密文、event_key或lease_token。POST /notifications/{event_id}/retry要求write+当前负责人/代办/绑定及read对象范围；read_all不授予写入权，认证OTP/邀请不能进入此通道。受控dead错误白名单、完整状态指纹、原因、UUID命令键；当前鉴权后原成功回放优先于状态/开关校验。新恢复与审计/回执同事务，attempt_count重新开始本轮、旧次数留审计；不改订单/PI或直接发送邮件。
- 新增NotificationDialog/notificationDelivery.mjs，订单详情入口、分页、失败原因、原因+确认恢复；严格校验回执请求/事件/key/状态。未知结果锁编辑/刷新/分页/关闭及站内离开，仅原key/body重放；身份改变清私密数据与迟到回执；权限拒绝清列表/表单但保留未知命令。独立审查发现1项P2：缺beforeunload导致刷新丢内存原命令；已补busy监听、卸载注销，并由独立复核确认关闭及实际浏览器reload/dismiss验证。未新增自定义动效，沿用现有组件与DESIGN。
- 后端新增11项局部测试，独立也11 passed，无新增P1/P2；全门户603 passed（2既有Query.get警告）。前端通知/命令12项Node通过（独立同样12）；最终browser10组/3次模拟POST通过，覆盖断线→原命令→403清私密→再次固定重放、未知态beforeunload、只读、失败列表清空、1440/390/320及手机恢复表单。桌面/手机截图已查看，手机表格沿用项目横向滚动规则。构建3322模块通过（既有chunk/auth混合导入警告）。
- 浏览器初次失败为auth/me夹具错误包装data导致守卫拒绝，按现有合同修正；后续hidden checkbox原生input不可见，改点击可见label并保留isChecked断言。strict首次发现操作列固定width，改min-width后通过。没有强制点击或放宽断言。测试为隔离SQLite/ASGI、模拟员工权限与模拟浏览器API，非真实SMTP/MySQL/权限联调。
- API参考和03/04/05/06开发契约同步；静态文档8篇/23链接/3JSON/64规格/17设计发现通过，strict及diff通过。12:57北京时间git_sweep --no-fetch仅本地快照；主目录原未跟踪内容保持。无push、merge、生产迁移、真实邮件或部署。
- 下一步对整体范围做入口覆盖核查：全部上游授权写入口、PI客户可见编辑入口与屏障/文档版本协议逐一对应；补缺失的实证回归。随后真实Cookie/Origin/backend联调、隔离MySQL迁移并发、B01–B07经营配置和完整试点。通知管理入口已接通，整体目标仍active，不能据603测试宣称已上线。



## 客户门户业务通知与恢复（2026-10-03）

- notification_worker 按业务源事件展开 business_mail 子事件，每个收件人独立租约/尝试/状态；原子 fanout 和唯一事件键防重复展开。员工在投递时解析当前负责人、实时权限和订单范围；客户复核当前成员/账号/验证邮箱/公司绑定。邮件只含请求号、事件摘要和登录链接，无金额、地址、PI 全文或能力 token。
- SMTP 在数据库事务外；120秒租约到期可领取，旧租约不能落结果，最多8次/有界退避。多人部分失败不重送已成功子事件；SMTP前有效期已过则排队重试不记成功。expanded只代表父事件展开，不能当全部发送成功；按子事件统计投递。采用至少一次，SMTP已接受但回执丢失仍可能重复；最终权限检查至实际发送有短暂窗口，不宣称撤权与SMTP原子化。
- PORTAL_NOTIFICATION_ENABLED默认false，需PORTAL_ENABLED/PORTAL_MAIL_ENABLED及受信PORTAL_EMPLOYEE_ORIGIN；scheduler独立每5秒任务。员工 /portal/orders?request=UUID 深链经现有登录/对象范围打开详情；非法UUID忽略、对象拒绝清详情。业务通知不带登录凭据，不扩大权限。
- 此批先前全门户588 passed（2既有Query.get警告）；新增公司绑定变化的员工/客户2例、发送器未发送退避1例、实际推进租约时钟到期后重领1例后，通知/认证邮件/配置局部47 passed。588不包含最后4例，未再次重复全量。先前主站build3319通过（既有chunk/auth混合导入警告），员工订单browser9场景/10模拟API调用通过。后端隔离SQLite与模拟SMTP、浏览器模拟API，非真实邮件/HTTP/MySQL联调。独立审查已验证原43项，无新增P1/P2；新增契约与前三例独立定向复核无P1/P2，独立3 passed；审查明确sender=False不等于实际时钟过期，主审随后补推进121秒用例，证明lease_lost保留sending、后续重领attempt=2成功，已包含47。
- 02数据模型/04交易恢复/06实施文档已同步；静态8篇/23链接/3JSON/64规格/17设计发现通过。12:30北京时间git_sweep --no-fetch仅本地快照，不代表远端最新状态。无推送、合并、生产迁移、真实发信或部署；主目录原有未跟踪内容未动。
- 已查管理路由/页面，尚无业务通知失败查询与恢复入口；下一步补按订单当前范围的投递追踪，并明确dead人工恢复契约，禁止把认证OTP/邀请事件混入普通业务重发。随后完成全部上游授权/PI写入口覆盖、真实Cookie/Origin/backend、隔离MySQL迁移并发、B01–B07配置和完整试点。整体目标active，未上线。


## 客户门户提案选品与价格预览 UI（2026-10-03）

- 新增ProposalCatalogPicker/ProposalPreview/proposalPreparation.mjs并接ReviewDialog/API。可从当前请求客户授权目录搜索分页添加SKU，重复及100行限制；新增行按min/step取合法数量。完整条款/原因先即时预览，展示新旧单价、数量、商品金额/总额、费用及付款。只传SKU/数量与条款，不传客户端价格；预览标明非锁价/锁货及客户仍须确认。
- 任何动作/商品/数量/费用/地址/付款/有效期/备注/原因编辑同步撤销预览和确认；校验预览对象、版本、币种、行ID/数量/金额及nonbinding语义，没有有效预览不得确认发送。正式命令未知时所有编辑、选品和预览冻结，只重放原body/version。
- 独立审查发现并关闭2项P2：迟到目录403原会invalidate清掉未知命令，现catalogDenied仅隐藏敏感详情/目录/预览、保留pending/state和重试；真实身份切换仍清旧命令。原行缺数量规则，后端review新增quantity_rules取当前授权published目录的原行min/step，前端应用并显示；缺规则标失效禁编辑/阻止preview，可移除。新增后端测试证明不读库存、不改历史数量、撤授权后规则消失。
- 验证：31条相关Node passed；后端review/preview/proposals 24 passed；主站build3319模块通过（既有chunk/auth混合导入警告）。新提案browser14组/4次只读preview/2次模拟正式命令（同命令回放），覆盖held目录→POST响应丢失→目录403→隐藏详情→固定回放；原审核browser4场景/4次模拟写通过。1440/390截图已查看、320无溢出。浏览器API为模拟；后端SQLite/ASGI，非真实联调。未重复全门户，上一批574是历史结果。
- 独立定向复核确认2P2均关闭；其独立24后端/7Node及2组件探针通过。前端/API文档同步；strict/diff通过，12:04北京时间git_sweep --no-fetch仅本地快照，主目录不改。没有push/merge/部署/迁移或生产写入。
- 下一步业务通知outbox worker及投递恢复；随后全部上游授权/PI写入口覆盖、真实Cookie/Origin/backend、隔离MySQL迁移并发、B01–B07及完整试点。当前尚未真实上线，整体目标active。


## 客户门户提案授权选品与差异预览后端（2026-10-03）

- 新增proposal_preview_service、GET /orders/{request_id}/proposal-catalog与POST /proposal-preview。managed_request当前write/归属/代办后额外read检查；准备入口限当前可propose未建票请求、站点/客户有效及可查价下单。目录仅该客户当前授权published，literal搜索/分页，返回标准和客户展示、单位步长，不返回库存数量或价格规则。
- proposal_service抽require_proposable/prepare复用原状态/版本/政策/PO/标准SKU/价格/库存验证，create成功持久回执仍优先于prepare。preview完整ProposalInput+If-Match，输出增删/修改/未变行、旧新单价金额费用地址付款、新合计和input_hash/calculated_at；binding=false明确非锁价/锁货，不创建quote/revision/receipt/audit/outbox，不改版本/接受。正式发送仍按当时价格生成新提案并等待客户确认。
- 新增8条隔离测试：价格变化、零业务写入、scope、授权撤销、增删行、过期版本/库存不可用/能力关闭、禁止客户端价格、HTTP If-Match/no-store、预览后再改价与原成功回执回放。全门户574 passed（2既有Query.get警告）。独立审查22项局部测试通过并额外unchanged探针通过，无新增P1/P2；独立22不含主审后补HTTP测试，该测试已包含574。
- API参考与开发契约同步，strict、diff通过；11:48北京时间git_sweep --no-fetch仅本地快照。后端纯增量，未改前端或重复构建。均SQLite/ASGI，真实MySQL/生产联调未验证。无push/merge/迁移/部署/生产写入。
- 下一步必须把proposal-catalog与proposal-preview接ReviewDialog：新增授权SKU、数量步长、即时价差显示，编辑撤预览/确认、未知正式命令仅原内容回放。当前页面仍只能编辑原行/移除，新增商品与预览UI尚未实现。随后业务通知worker、所有授权/PI入口覆盖、真实Cookie/Origin/backend、隔离MySQL迁移并发、B01–B07及完整试点。整体目标active。


## 客户门户归属与身份复核管理 UI（2026-10-03）

- 新增 BindingReviewDialog.vue、bindingReview.mjs，PortalCustomers 的 admin 详情入口在 review_required 仍可进入；接 GET binding-review 及 POST transfer/rebind。展示旧绑定、实际有效候选、订单/PI数量、待办前1000及截断提示，分页逐条选中；历史读取限时给新负责人且仅本次已有未交接订单，旧授权撤销、不涵盖未来。服务端权限/范围仍为权威。
- 提交当前版本与review_fingerprint，转交/重绑payload隔离。回执验证对象/递增版本/状态/requires_enable、影响字段及实际选中交接集合；不完整回执冻结为未知。未知POST不重发，仅GET读取当前复核并放弃草稿，不宣称原成功；401/403/404清空，身份变更隔离迟到响应。完成后暂停或继续复核，不自动启用。表格状态中文化。
- 新增纯逻辑5条含畸形回执不重放；本轮相关前端逻辑共29 passed。主站build3314模块通过，保留既有大chunk和auth混合导入警告。新增browser12组/3模拟写与原账号browser10组/6模拟写通过；1440/390截图已查看、320无溢出。初次browser下拉框输入被placeholder遮挡，改为点击真实el-select容器后原断言全部通过，未强制点击或放宽断言。
- 后端无改动，相关binding/admin/ownership 34 passed；未重跑全门户（上一批566仅历史记录）。独立审查未发现可复现新增P1/P2，独立5条Node也通过；浏览器为模拟HTTP、服务测试为隔离SQLite，真实联调/MySQL并发尚未验证。
- 前端开发契约、API参考同步；strict、diff、8文档/23链接/3JSON/64规格/17发现静态检查通过。11:39北京时间git_sweep --no-fetch仅本地快照，主目录保留原未跟踪内容；无push/merge/部署/迁移/生产写入。
- 下一步：提案新增授权SKU与价格变化预览、业务通知worker；全部上游授权/PI写入口覆盖、真实Cookie/Origin/backend与隔离MySQL迁移并发、B01–B07经营配置和完整试点仍需完成。整体目标active。本轮完成管理UI，不视为整体交付。



## 客户门户转交与身份重绑复核上下文（2026-10-03）

- 新增binding_review_service和GET /customers/{access_id}/binding-review，当前portal_access:admin+当前客户范围；返回有效主负责人、配置来源已验证公司身份、公司现绑定、待交接订单安全摘要、订单及PI数量、review_fingerprint。pending显示前1000且标总数/截断，指纹覆盖全部订单；不返回金额/地址/账号秘密。普通业务员功能权限不能跨范围，归属已变/review_required通常由super_admin处理。
- TransferInput/RebindInput新增必填review_fingerprint，写入在共享屏障/实时鉴权/范围/If-Match后重新计算并比较，再强制选中assignment/identity属于当前review choices；防有效指纹搭配外部namespace对象。指纹包括客户记录/身份状态、有效负责人/身份选项、全部订单ID/状态/版本/服务人/invoice关联。同ID原地改值、新订单、订单状态变化都拒绝旧复核；无业务写入。对象ID加signed BIGINT界限。
- 原转交/重绑流程保留：只转明确选中的未建票请求，重新提案确认；历史归属快照、revision和PI不重写；会话/邀请/旧报价失效；完成后suspended或继续review_required，不自动启用。此批仅后台上下文及写约束，管理UI尚待接入。
- 新增7条测试，范围、安全字段、原地归属/身份变化、新订单/状态变化、伪造跨namespace候选均覆盖。原管理/转交夹具补配置来源并提供真实上下文指纹，初次6失败为夹具缺PORTAL_OKKI_NAMESPACE，修复后原断言保留。相关34 passed，独立审查也34通过；独立跨namespace探针证实成员约束生效，无未关闭P1/P2。最终全门户566 passed（2既有Query.get警告）。SQLite/部分mock员工权限，尚未验证真实HTTP/MySQL并发。
- API参考/开发契约同步，strict约定、diff、8文档/23链接/3JSON/64规格/17设计发现检查通过。11:21北京时间git_sweep --no-fetch本地快照；无前端改动未构建。未推送、合并、部署、迁移或生产操作。
- 下一步接转交/重绑管理UI，需显示旧/新归属、候选真实公司身份、待交接选项、历史读取对象为新负责人及期限、截断处理和后续重新启用说明；发送review_fingerprint，未知POST只读回核对，不自动重发。其余提案新增SKU/报价变化、业务通知、全入口授权/PI覆盖、真实Cookie/backend及隔离MySQL、B01–B07继续。目标active。


## 客户门户商品管理UI（2026-10-03）

- 新增PortalCatalog.vue、CatalogItemDialog.vue、catalogConfiguration.mjs和/portal/catalog，site:admin路线菜单/操作；接通商品搜索/筛选分页、最新详情、来源预览、指纹绑定导入草稿、配置发布/下架、重新导入。来源规范ID字符串，业务换算不推断；预览仅建议名称/颜色，切换ID/类别撤旧预览并清配置。重新预览已有SKU提示转draft/报价失效，重新填换算后提交。
- import/update通过现有非重放mutation控制，按预览/详情版本写入，回执检查产品/SKU/类别/public ID/版本及draft约束。未知结果冻结，仅import-status或detail读回；查无记录保持未知，查到不假报原命令成功。客户旧订单不修改，后端发布继续检查来源/映射。身份变化清草稿和迟到回执。
- 浏览器发现3个来源控件显式disabled=false覆盖ElForm locked，已改locked || !!itemId；独立同类审查再发现Onboarding/AccessAction can_order覆盖表单冻结，均改locked || !can_view_price，新增Onboarding未知态checkbox禁用断言。独立定向复核确认两处关闭。未放宽原browser断言。
- 验证：前端逻辑32 passed；商品browser11组/3mock写，开通11组/5mock写、账号10组/6mock写回归通过；合计32组/14模拟写，非真实联调。1440/390截图已查看并验证320溢出。主站build3310模块通过（既有chunk/auth导入警告）；相关后端27 passed。后端未改，未重复全门户测试，上一批558为历史结果。独立源码/纯测试审查加锁定缺陷定向复核完成。
- 前端设计与API参考同步；strict约定、git diff --check通过，11:10北京时间git_sweep --no-fetch仅本地快照。没有推送、合并、迁移、部署、真实发信或生产操作。
- 下一步转交/身份重绑UI、提案新增授权SKU/价格变化预览、业务通知worker；全部上游授权/PI写入口覆盖、真实Cookie/Origin/backend与隔离MySQL迁移并发、B01–B07和完整试点仍需完成。单位换算真实经营口径不能由演示参数代替。整体目标active。


## 客户门户商品来源预览与导入恢复（2026-10-03）

- 为商品管理UI补齐catalog_admin_service.get_item/inspect_source/lookup_import及列表keyword，新增GET /catalog/source、/catalog/import-status、/catalog/{item_id}。均实时portal_site:admin+当前site/namespace；来源精确规范ID和有效SKU，类别不能偷换；静态路由先于UUID路由。名称/颜色literal contains，product/sku精确搜索，分页同过滤。
- source只读标准快照和existing_item/expected_version，不导入、不猜换算；import-status与详情不依赖镜像，导入响应丢失后即使镜像不可用仍能核对本站当前记录，found不代表原命令回执。无记录也不证明未执行。
- 主审发现预览后同SKU单位变更可能使用旧换算确认，已将CatalogImport.standard_fingerprint设必填，服务重新load_snapshot后立即比较，再创建/更新/失效报价/审计。新反例同ID20g变25g拒绝旧fingerprint，零商品和审计；重新预览后可按对应新指纹导入。现有调用方搜索只有后端路由与fixture，没有遗漏前端消费者。
- 独立读取审查及指纹定向复核均无新增P1/P2，独立26项相关测试通过。主审全门户558 passed（2既有Query.get警告）；其后新增HTTP路由测试，局部27 passed，覆盖路由顺序/no-store/403/缺指纹422。全量558不包含最后新增的1条HTTP测试，未再次跑全量。初次新增指纹时第二SKU fixture误用第一SKU hash导致3失败，已按第二SKU来源预览修正，原断言保留。
- API开发契约与api-reference同步，strict约定、diff和静态文档校验通过；10:55北京时间git_sweep --no-fetch本地快照。纯后端增量无前端构建；测试隔离SQLite/ASGI，未连接真实来源库或证明MySQL并发。未部署、迁移、发信或生产写入。
- 商品管理页面仍未实现。下一步先接来源预览/指纹冻结、草稿导入、配置及发布/下架、未知写入查询；切换源身份应清除旧预览和换算确认。站点经营单位B02仍需真实确认。其余转交重绑UI、提案新增SKU/报价变化、业务通知、全入口授权/PI覆盖、真实Cookie/Origin/backend与隔离MySQL门禁继续，整体目标active。


## 客户门户中文站点设置（2026-10-03）

- 新增PortalSettings.vue、sitePolicy.mjs与/portal/settings菜单路由，均portal_site:admin；接既有GET/PATCH settings，后端无改动。站点初始化version0、启停、报价/提案期限、付款条件及默认项、原因/影响确认完整接通。受信域名/代码/USD/English只读，不提供密钥或域名写入，不默认商业付款条件。
- 纯payload校验与服务端范围一致；定金百分比精确字符串，启用必须付款条件和默认项。任何编辑同步撤销确认。复用非重放mutation控制，未知PATCH冻结，GET明确放弃草稿且不证明原成功；403/404清空配置，身份变化隔离迟到响应，离页保护。
- 独立审查未发现可复现P1/P2并独立3项纯前端测试通过。主审29项前端逻辑通过、既有站点服务11项通过；主站build3304模块成功（既有chunk/auth导入警告）。站点browser10组/3模拟PATCH通过，1440/390截图已查看、320宽度断言通过。无后端变更，未重复全门户测试；上一批553条为历史全量结果。真实环境联调未执行。
- 前端设计与API参考同步。保留原实现，未部署/迁移/真实发信或改生产政策。下一步站点商品导入/配置/发布UI、转交重绑UI、提案新增SKU/价格变化预览、业务通知worker、全部授权/PI写入口覆盖、真实Cookie/backend、隔离MySQL并发和B01–B07。整体目标active。


## 客户门户已有客户商品授权编辑（2026-10-03）

- 新增catalog_access_service与GET/PATCH /customers/{access_id}/catalog，GET当前portal_access:read，PATCH admin+If-Match；双方均共享屏障内重查权限和当前归属范围。安全商品投影包括已下架状态，不含价格/成本/库存数量。CustomerCatalogUpdate只接收完整catalog_item_ids和reason，不修改客户启停/能力，draft可独立调整商品。
- 当前已授予下架项可保留或移除，移除后不能重新授予；新商品只接受同站点published。完整投影校验阻止新增规格引出已发布别名冲突，失败回滚；成功升row/auth版本，集合变化升catalog版本，撤会话、失效valid报价、审计public增删ID。旧CustomerUpdate非空列表仍严格published，本次接口保留语义已文档化。
- CatalogAccessDialog复用CatalogPicker，当前已选/下架标签、搜索选品、新增移除数量、清空全授权警示、原因/确认、版本保存接通。未知PATCH冻结且不重发，GET读回明确丢弃草稿且不证明原保存成功；回查401/403/404立即清除旧数据并退出。身份变更和迟到响应隔离，关闭/离页保护；只读入口隐藏。
- 独立审查无可复现P1/P2并独立跑6后端测试通过；之后主审补充scope丢失清理和对应浏览器反例通过。全门户553 passed（2条既有Query.get警告），Node26 passed，主站build3301模块通过（既有chunk/auth导入警告）。商品授权浏览器10组/4模拟PATCH，复用组件开通回归11组/5模拟POST通过；390截图已查看，1440/390/320宽度断言通过。均隔离SQLite/模拟HTTP，不能证明真实端到端/MySQL并发。
- API参考与开发API/前端契约同步；strict约定、git diff --check、8文档/23链接/3JSON/64规格/17设计发现静态验证通过。10:38北京时间git_sweep --no-fetch仅本地快照，主目录未改；本任务分支无推送、合并、部署、迁移或真实发信。
- 下一步：站点政策/商品配置UI、转交重绑UI、提案新增SKU/价格变化预览、业务通知worker、全部上游授权/PI写入口覆盖、真实Cookie/backend联调、隔离MySQL迁移并发与B01–B07。整体目标active。


## 客户门户开通与初始商品选择（2026-10-03）

- 新增 onboarding_service 三个只读端点，按当前有效 primary 主负责人提供真实客户候选/单客户恢复查询；唯一配置来源的 verified/strong/one_to_one 公司身份才可开通。遵循 external_identity/source_record 逻辑归属，非 super_admin 仅本人范围；缺失、多义、争议或已有授权说明原因，不手填覆盖。商品候选只返回已发布安全规格，无价格/成本/库存数量。
- CustomerCreate 必填 binding_fingerprint，候选生成、UI冻结、授权屏障内重查贯通。即使 identity ID 不变、公司值原地更新也拒绝旧选择；创建前另查重复外部绑定。新增10条服务测试覆盖范围、字面搜索、归属变化、身份强度/来源、多义、两种逻辑归属、公司值原地修改、只创建草稿和安全目录字段。
- OnboardingDialog/CatalogPicker 接入 /portal/customers，选择真实客户、初始商品、查价/下单能力后只创建 draft。跨商品搜索保留选择，取消查价同步取消下单，空目录不默认全量授权；成功进入草稿详情，后续显式启用与邀请。未知创建冻结原body，仅查询或原内容重试；查到现有授权也不宣称原命令成功，查不到不视为未执行。身份变化隔离迟到响应，关闭/离页保护。
- 独立后端复核确认 fingerprint 防原地身份变化及 source_record 归属未引入问题；前端定向源码审查无可复现P1/P2，身份切换挂起响应仅源码核验，尚无该场景浏览器实测。全门户547 passed（2条既有Query.get警告），Node26 passed，主站build3298模块通过（既有chunk/auth混合导入警告）。开通浏览器11组/5次模拟POST、已有账号浏览器10组/6次模拟写通过；1440/390截图已查看，320宽度通过。修正手机空商品提示行距后重建重跑开通测试通过。初次浏览器因测试文案定位不符超时，改为页面准确文案后通过，未放宽业务断言。
- API参考、开发契约与前端文档同步；静态文档8篇/23链接/3JSON/64规格/17设计发现通过，strict约定与git diff --check通过。10:22北京时间git_sweep --no-fetch仅本地快照，主目录原内容未改；独立worktree无推送/合并/部署/迁移/发信。浏览器均模拟HTTP，后端隔离SQLite，尚未证明真实端到端或MySQL并发。
- 下一步仍需已有客户商品授权编辑、站点/商品配置UI、转交与重绑管理UI；提案新增SKU/报价变化预览、业务通知worker、全量授权及PI写入口覆盖、真实Cookie/backend联调、隔离MySQL迁移并发与B01–B07经营配置。完整目标保持active，未将局部通过视为上线验收。

## 客户门户型号颜色映射管理（2026-10-03）

- 延续完整实现目标，上一轮已有账号管理继续保留。本轮新增MappingDialog.vue/mappingDraft.mjs，客户详情入口按portal_mapping:read显示，编辑预览发布按write；需要portal_access:read进入列表。固定标题含公司名。标准来源选择、型号/颜色别名、单SKU型号名/客户货号、失效项主动移除、草稿筛选分页和完整投影对照已接入。
- mapping.analyze_mapping收集全部语义冲突；管理preview新增valid/conflicts（颜色/规格/货号重复），仅当前已授权published IDs，字段或来源非法仍拒绝。project_mapping仍用于客户读取/正式publish，拒绝冲突且不带内部issues；publish不信浏览器预览，重复校验版本/来源。服务测试证明预览不创建版本、正式发布拒绝冲突及跨业务员404。
- 编辑同步取消旧预览/确认，发布冻结已预览body/row_version；未知发布仅GET读回当前版本后核对，明确不能证明原命令成功，不重发。过期版本不会覆盖他人配置，身份变化与迟到请求丢弃，历史订单快照不重写。
- 独立审查无新增具体P1/P2，并独立跑3前端/3后端增量通过。主审全门户537 passed（2条既有Query.get警告）、Node26 passed、主站build3293模块通过（既有chunk/auth导入警告）。映射浏览器10组/8次mock API通过，实际查看1440/390截图并验证320；首次测试因ElementPlus内部输入被placeholder覆盖而超时，按真实可见容器修正定位后通过，未强制点击或放宽断言。标题/按钮排版修改后重建通过，映射10组及已有客户管理10组浏览器回归均通过（合计14次模拟写/预览调用）；更新后390截图已查看。strict约定、文档静态校验与git diff --check通过；09:52北京时间git_sweep --no-fetch为本地快照，主目录原内容未改。
- 仍需新客户开通向导（真实身份/负责人选择）、商品授权/站点配置UI；提案新增SKU/报价变化预览、业务通知worker、全部授权/PI写入口覆盖、真实Cookie/backend联调、隔离MySQL迁移并发与B01–B07。没有部署、迁移、发信或生产写入，目标保持active。


## 客户门户中文账号与访问管理（2026-10-03）

- 继续完整开发目标。新增PortalCustomers.vue、AccessActionDialog.vue、customerAccess.mjs以及API与navigation入口`/portal/customers`。客户搜索/访问状态筛选/分页、详情账号分页、邀请/重邀/撤销、账号停用/恢复、客户访问启停/查价下单能力接通；读写权限与服务端当前归属独立校验。尚不含新客户开通、映射和站点管理页面。
- 后端CustomerUpdate.catalog_item_ids省略/null保留grants，不受已下架商品阻塞；显式[]仍撤销全部，非空仍严格同站点published。保存仍升版本/撤会话；review_required不能绕过，启用仍查绑定。3条新测试证明撤下grant保留且会话撤销、显式清空/禁止重新授予下架商品、越权/复核门禁。
- 邀请未知结果冻结原body/key，重试持久回执；其他PATCH/revoke未知结果只重新读状态核对，不假报成功、不自动重发。独立审查发现邀请GET清键P2已修复：函数和按钮均禁止invite进入该路径，browser明确无GET按钮且两次请求完全一致。独立定向复核关闭。身份变化、离开保护与晚回执隔离已接入。
- 验证：全门户534 passed，2条既有Query.get警告；Node23 passed；主站build3289模块通过（既有chunk/auth导入警告）。新浏览器10组场景、6次模拟写请求通过，390px设置与1440px账号详情截图已查看。均为隔离SQLite/模拟HTTP，未创建真实邀请或账号；真实MySQL/邮件/Origin联调仍未完成。
- 下一步：带当前归属/已验证外部身份选项的新客户开通向导，客户型号颜色映射/发布预览，授权商品与站点设置UI；提案新增SKU/报价变化预览、全部上游授权与PI写入口覆盖、业务通知worker、隔离MySQL门禁和B01–B07仍需完成。目标保持active，未提交/推送/部署/迁移或发信。


## 客户门户开发文档 v1.2 与对抗复核（2026-10-03）

- 本轮按用户要求交付详细开发文档及对抗性审查，只改文档，不继续功能开发；既有实现改动保留。入口为 `docs/requirements/2026-09-30-customer-order-portal/README.md`，8篇覆盖架构/权限、字段模型、API、交易状态、双端前端、64条验收规格与审查记录。
- 独立复核新增F17/P2：void-pi缺少稳定幂等命令定义。已与本地服务核对，统一每请求唯一pi_voided/request_id/local-void，完整版本+reason入hash，成功回执先于新版本/tombstone校验；T41补充响应丢失重放、异载荷冲突、撤权拒绝与不重复审计/outbox。独立定向复核确认关闭。累计17项设计发现（5P1/12P2）已在文档层修订，不代表实现安全验收通过。
- 历史实施批次、目标契约与当前进度已明确分离；迁移编号不构成执行授权，局部测试不能关闭全规格。当前实施状态仍参考本文件相应批次，本文档复核未重跑业务测试。
- 本轮静态校验8篇/23链接/3JSON/64规格/17发现通过；strict约定、git diff --check通过，git_sweep --no-fetch仅为本地快照（首次看板写入受沙箱限制，窄范围提升后成功）。未提交、推送、合并、迁移、发信、建票或部署。


## 客户门户管理端原 PI 操作增量（2026-10-03）

- 新增 GET `/api/portal/admin/v1/orders/{request_id}/pi-review`。复用当前客户负责人及原PI业务员双重can_act_for，另查当前portal_order读写及invoice:write；当前公司身份、原PI业务员、PI文档版本随响应提供。只读当前Invoice/items，不读取实时库存、不创建发票。
- 三份展示独立：current_invoice来自当前方舟PI标准字段；last_published来自已验证历史revision，商业抬头来自同request/invoice最新Publication且校验snapshot_hash；proposal来自仍绑定当前PI的客户修订证据。历史和当前版本分别标识，PI编号/公司/日期/运输/联系方式/包装数完整显示。formatted_address在管理端三个展示组件中支持，避免PI改用完整地址后缺少收货地址。
- PiReviewDialog接入发送修改提案、发布客户已确认版本、作废未流转PI。当前原PI编辑仍通过既有发票管理完成。每次提交携带冻结的request row_version及invoice_document_version；发布额外绑定客户确认revision，不走首次建票接口。复用command.mjs不确定结果原命令重试，离页及关闭保护、身份变化丢弃迟到回执。
- 作废动作提示复用require_local_idle；存在同步/回款/出库/关联处理等业务时显示阻断原因。政策失效只阻止发送/发布，不隐藏本来允许的本地作废。所有POST维持原服务完整验证，UI动作数组仅为提示。已过期确认不可发布，只能重新提案。
- 独立审查P2“历史商业抬头缺失”已修复并复核关闭。新增8项PI审核上下文测试覆盖范围、完整地址、当前/历史金额及抬头分离、篡改快照、有效期边界、作废阻断、功能关闭和库存不可用时只读。全门户531 passed，两条既有SQLAlchemy警告；主站build通过3283 modules，既有chunk-size/auth混合导入警告。
- 新浏览器脚本portalPiReview.browser.mjs：5场景/4模拟POST通过（修改提案、发布响应丢失原命令回放、作废、已有出库阻断、越权拒绝），明确断言If-Match、PI版本、确认revision，当前与历史抬头不混淆，完整地址及390px弹窗无横向溢出；截图已查看。均模拟HTTP，不是真实PI/生产操作；旧管理端浏览器套件回归结果收尾补充。
- 最终收尾：旧列表6组和首次审核4组浏览器场景均回归通过，连同原PI5组共15组（均合成HTTP）；18项Node回归通过。strict conventions、git diff --check、文档静态校验通过。09:04北京时间git_sweep --no-fetch为本地快照，主目录未改。临时图片均留在scratch，没有混入前端源码。
- 下一步：客户账号/邀请/权限、客户型号颜色映射、授权目录/站点策略管理页；提案新增授权商品及价格变化预览；真实Cookie/backend联调、通知worker、全部上游授权/PI写入口、MySQL迁移/并发与B01–B07仍待完成。原PI动作已接入但尚未真实环境验收。完整目标继续，未推送、部署、迁移或发信。


## 客户门户管理端提案与审核增量（2026-10-03）

- 新增 `GET /api/portal/admin/v1/orders/{request_id}/review`：服务端重新读取 portal_order:write 与 read、当前客户绑定及 can_act_for；read_all/super_admin 不替代代办授权。返回当前订单版本、付款政策和可操作动作；无库存远程读取。动作提示不是授权凭证，POST 仍完整复核。
- 员工专属审核摘要新增 customer（方舟ID、OKKI公司ID、公司名、当前业务员ID）和 standard_lines（line_key、标准商品/SKU ID、型号颜色等白名单），与客户显示别名并排核对。客户 detail 白名单保持不变。此项修复独立审查提出的实际建票对象不可辨认 P2。
- 管理端接通发送提案、审核生成正式 PI、拒绝请求；显式选择动作并勾选确认。提案可调整原商品数量/删行、费用、付款条件/期限、地址及备注；PO不可静默修改，不提交客户端价格。新增商品选择、库存/价格变动预览、PI修订/发布/作废操作及客户配置页仍待实现，不宣称完整后台完成。
- 审核窗口展示完整当前商品、费用、付款及地址快照。独立 command.mjs 冻结请求ID/动作/If-Match/请求体；双击只发送一次；网络/5xx/无效回执后锁定原命令，显式同命令重试。409只在首次确定失败时释放编辑，先前不确定的重试失败仍保留不确定；身份变化丢弃迟到响应。刷新/关闭浏览器有离开提示，不持久化地址/条款；跨浏览器重启的回执恢复入口仍需完善。
- 修复实际缺口：approval_service 原未使用 PORTAL_INVOICE_ENABLED。现关闭时阻止新转换；成功回执仍在开关/库存校验前回放。回归证明关闭时 Invoice/Conversion 为0，启用建票后关闭且库存不可用仍回原成功，不重复建票。
- 验证：后端全门户523 passed（两条既有SQLAlchemy Query.get警告）；身份摘要补充后相关19 passed。前端5条命令回归+5条展示回归通过；主站build 3278 modules通过（既有chunk大小及auth混合导入警告）。浏览器模拟API验证结果在本批收尾记录补充；没有生产数据或真实MySQL写入。
- 收尾证据：独立交易复核确认身份/SKU信息不足 P2 已关闭，并独立复跑19项后端测试。最终18项Node测试通过；portalReview.browser.mjs四场景/四次模拟POST通过（审批响应丢失原命令回放、提案、拒绝、对象拒绝），桌面/390px弹窗及横向溢出检查通过；截图已查看。strict conventions、git diff --check、文档静态验证通过。08:44 git_sweep --no-fetch 为本地快照，主目录无本轮修改。
- 下一步：补提案新增授权SKU/报价变化预览、管理端PI修订/发布/作废、账号授权/客户映射/站点配置；真实Cookie与后端联调、全上游授权/PI writer覆盖、独立MySQL迁移/并发以及B01–B07仍待完成。所有修改留在本任务worktree，未推送、部署、迁移或发信。完整目标继续。


## 客户门户中文管理端请求中心增量（2026-10-03）

- 新增 `/portal/orders`，navigation.js 权限 `portal_order:read`；统一 clients.js 注册 `/api/portal/admin/v1`，沿用方舟员工 Bearer、全局权限指令及后端当前范围判定。列表采用 useListPage，支持状态筛选、分页、金额语义与北京时间；详情展示商品客户别名/规格、费用、地址、付款文本及事件。
- 列表刷新先清旧数据；列表与详情都取消前请求并检查序号，关闭抽屉/离页/身份变化清私有状态。当前页面为读取能力；提案、审核建票、发布/拒绝/作废按钮及客户配置页面仍需开发，不宣称管理端完成。
- 独立审查发现并修复两个 P2：PI 生命周期必须区分 current/voided/withdrawn/pending_customer/accepted/rejected；已发布 PI 的历史提案过期不再提示重新确认，但正式建票前仍保留过期约束。商品标题区分未接受提案、已接受提案与历史发布快照。
- 验证：主站 Vite 构建通过（3272 modules，现有 chunk size / auth 混合导入警告）；5 项新展示测试与 8 项既有导航测试通过。浏览器 6 组场景 / 5 次拦截：列表、PI 作废、历史过期、PI 撤回、390px 抽屉、503 刷新清空；1440/390 截图人工查看。测试使用合成 HTTP，与真实后端联调/跨业务员越权测试不同，不据此宣布安全验收。
- 构建依赖从现有 package-lock 导入临时 pnpm lock，安装 --frozen-lockfile --ignore-scripts；临时 lock 已移到 scratch 留存，未改变 package.json/package-lock。预览仅回环地址 127.0.0.1:3211。浏览器测试在 frontend/tests/portalOrders.browser.mjs，通过 PORTAL_PLAYWRIGHT_MODULE / PORTAL_CHROMIUM / PORTAL_QA_OUTPUT 配置。
- 收尾：独立审查定向复核确认本轮两项 P2 均关闭；strict conventions、git diff --check、文档静态检查通过。08:19 北京时间 git_sweep --no-fetch 为本地快照，主目录无本轮修改。
- 下一步继续补管理端写操作及对象动作授权投影、客户授权/映射配置、真实 Cookie/Origin 联调、全部上游授权和 PI 写入口覆盖、独立 MySQL 迁移/并发验证、B01–B07。目标继续进行，未推送、部署、迁移或发信。


## 客户门户复购UI增量（2026-09-30）

- 接通ReorderDialog→checkout.reorder→服务器reorder-quote→新报价确认。历史行多选，已有cart需勾选明确替换，失效行按安全line_key提示并允许取消勾选；不静默丢行或沿用旧价。新alias/length/weight/unit/price和历史差异可见，复制地址/备注、清PO、费用pending/total null，必须再次确认才创建request。原历史快照不改。
- quote_service.view仅新增min_order_qty/step_qty，取自验过摘要的不可变inventory_snapshot，避免复购每SKU另查目录；不暴露源数量、余量、换算或内部身份。测试明确改当前catalog数量规则后读取旧quote仍保留旧规则，提交按已有服务重查。
- 对抗审查P2：关闭弹窗但网络挂起时quoting不释放。已client.reorder转发signal、abort立即递增sequence并释放当前quoting、finally只清自身请求。新增回归覆盖原promise不完成时可立即新报价，旧promise晚完成不能解锁新报价；reviewer定向关闭。失败/晚响应/切账号不覆盖cart，未知提交阻止复购；取消可能留下未消费quote，不产生订单。
- 验证：全门户517 passed / 2既有Query.get警告；前端54 Node通过；Vite29模块构建通过。复购浏览器7组/8拦截通过：替换确认、挂起期间关闭立即解除锁、失效行取消重试、390/320弹窗不溢出、新旧别名/规格/价格对比、PO清空/地址带入/费用待定、单独确认后仅一次提交。其他三套已回归，总36组/82拦截。截图portal-browser-qa/reorder-dialog-320.png与reorder-review-1440.png已查看；均隔离模拟HTTP，不是生产数据或真实MySQL联调。
- 下一步：中文方舟管理端（请求审核/客户账号与授权/客户映射/站点策略），真实客户端Cookie/Origin与后端联调，全上游授权及PI写入口清单、独立MySQL迁移/并发、B01–B07试点经营口径仍待完成。B02库存单位与更新时间语义未确认，保持默认禁用；未推送、部署、迁移或发信。完整目标继续进行。


## 客户门户订单中心与提案/PI页面增量（2026-09-30）

- 本批frontend-portal增加OrdersView、OrderTerms/OrderLine、ProposalDiff、orderPresentation和orderDecision：请求状态筛选/分页/详情、订单完整规格/金额/地址/付款条件/历史、提案差异、客户接受/拒绝/取消、PI后续提案与最后发布版分离、授权PDF下载。App支持/orders、/orders/:id及proposal路径，/cart映射合并购物车页面，提交回执可进入请求详情。
- 决策确认框必须显式勾选完整条款；reason必填且限制500。操作冻结request/revision/hash/version/reason，未知结果GET只展示当前状态，不伪造回执；仅手动重试原命令。状态使用回执current_state，后续PI接受等待发布，不新增PI、不自动开放PDF。Blob仅经当前scope校验后生成，30秒回收及卸载清除；下载失败刷新发布状态。动作内存跨页面保留，身份边界清除，刷新重新读取当前订单；不持久化PI、理由或商业快照。
- 独立审查发现1项P2：全局decision成功/失败提示串到其他订单；按operation.request_id限定提示并带原request_no，切换详情关闭旧dialog，pending操作不清除。审查者定向复核关闭，未扩大为真实后端安全保证。
- 验证：Node47 passed（本批新增9）；Vite28模块构建通过。orders.browser.mjs 11组/36次隔离API调用通过：详情直达、筛选、old/new与1440/390/320、显式确认/焦点、断线跨导航原版本重试、回放current_state、取消reason/If-Match、失败及成功提示不串单、无价格权限、PI接受后等待发布、PDF正常/撤回、跨标签退出。原登录9组/21调用与购物车9组/17调用也回归通过，共29组/74调用。浏览器使用本机Chrome、模拟订单及合成PDF，截图portal-browser-qa/order-proposal-*.png已查看，不代表真实Cookie/Origin/库存/建票链路通过。
- 未完：复购UI、中文方舟管理端、全部上游授权/PI写入口覆盖核对、独立MySQL迁移/并发、真实接口与邮件/代理联调、B01–B07试点输入。B02单位与同步刷新语义未确认仍默认禁用。完整目标保持进行中，无提交、推送、部署或生产变更。


## 客户门户购物车与提交确认增量（2026-09-30）

- 本批仅在 codex/customer-portal-dev-docs worktree 继续实现 frontend-portal：商品详情加购、合并同SKU、MOQ/步长与上限、可编辑购物车/收货信息、服务器报价审核、显式确认、提交回执和断线恢复。报价显示当前长度/重量/单位/四位单价与两位金额；未知费用仍待确认，提交不生成正式PI。
- createCheckout在内存保存草稿；任意编辑失效旧quote/consent，晚到响应按sequence丢弃；会话事件清空cart/address/PO/notes/quote/receipt。createSubmission冻结key/body，unknown状态阻止加购与新key，手动重试原请求，刷新仅account-scoped key + GET回查。真实后端仍按现有权限与幂等事务校验，浏览器显示不构成授权。
- 验证：38项Node通过；Vite构建22模块通过。既有登录/目录9组浏览器21请求通过；新增checkout9组17请求通过，覆盖新旧规格/价格、报价503保留表单和错误焦点、修改后撤销确认、1440/390/320无溢出、提交断线404保持未知、同key重试、刷新GET-only、明确409后可编辑、另一个真实标签退出清空。使用本机Chrome与隔离API拦截，无生产访问、发信或建票；截图在本任务portal-browser-qa/checkout-*.png。
- 独立安全审查发现1项P2：权威报价漏length/weight而左侧仍显示旧选择；已补完整规格和变化提示，浏览器造20in/20g→22in/25g/$35.275反例验证，审查者定向复核关闭。现有动效策略不变：列表/结果即时更新，精细指针按压120ms，reduced-motion无位移。
- 下一步：客户订单/提案比较接受拒绝/PI下载/复购页面，中文方舟管理端；全上游授权与PI写入口覆盖、独立MySQL迁移并发及真实接口联调仍未闭环。B02库存单位/同步口径待业务确认，配置继续禁用，未以测试数据开放真实下单。全目标保持进行中，无提交、推送、部署、生产迁移。



## 2026-09-30 客户门户开发文档 1.1 对抗复核

按用户文档与审查要求复核 `docs/requirements/2026-09-30-customer-order-portal/README.md` 及其余 7 篇。新增 F13–F16（1 P1 / 3 P2），修正转交后建票归属快照、下架映射可用性、取消幂等键与实现状态表述；独立复核全部在设计层关闭。累计 16 项发现、64 条待执行业务验收规格。静态链接/JSON/编号检查、strict 约定检查、diff 检查通过；20:48 本地 Git 巡检无 fetch。本次只改文档，既有未提交实现保持原样；不据此宣称实现、真实权限联调或 MySQL 并发验证完成。

## 2026-09-30 客户下单门户实现（持续开发，未部署）

- 客户站登录与目录页面增量：frontend-portal已成为可独立构建的Vue应用，锁定与主站相同Vue3.5.32/Vite5.4.21/plugin5.2.4；支持真实API的会话恢复、邮箱OTP、邀请fragment立即清理、专属目录搜索/筛选/分页、商品规格dialog、退出失败重试、跨标签失效。私密内容随scope失效卸载，金额字符串精确展示。沿用原Logo和本地参考纹理，仅CSS裁切；商品图暂无真实映射，使用品牌占位。已从Emil官方仓库读取emil-design-eng和review-animations/STANDARDS，之前本机技能缺失不再阻塞UI。独立审查指出成功退出卡在signing-out及同步能力提示被认证清空，均修复；实际worktree离线安装锁文件并构建通过，28项Node测试通过；隔离Chrome拦截API的9组浏览器场景（21请求）通过，覆盖1440/390/320、OTP错误、筛选、native dialog焦点、reduced-motion、退出重试、邀请URL与真实双标签失效。截图在任务scratch/portal-browser-qa。未连接真实后端/Cookie或邮件服务，测试数据不进生产bundle；购物车/checkout/订单PI页面、中文管理端尚待实现，W06不判完成。


- 库存镜像适配增量：inventory_source.py 已替换空观察桩，按已授权目录的 namespace/product_id/sku_id 读取活跃 okki_inventory.enable_count，不含在产/在途；三项来源配置默认空（观察列仅synced_at、源时区、逐SKU源单位）。逐行校验数量/时间，取最早观察，不用MAX掩盖旧行；任一负数/空值/未来/过期/超精度行令该SKU未知，其他SKU保持可读。源数量最多18位整数且精确6位小数，聚合超界拒绝；独立审查复现并关闭高精度舍入虚增P2，下游换算边界无舍入探针通过。45项源/真实SQL报价提交链路测试独立通过，全门户516passed/2条既有Query.get警告。未查询生产库，源单位、字段precision/scale和导入器synced_at完整刷新语义尚待确认，相关配置保持空，不能据此开放真实下单；已异步询问用户enable_count单位，未把无回复视为确认。其余UI、MySQL并发与全部writer门禁保持未完成。


- 英文客户站基础增量：新增 frontend-portal/src/api/client.mjs 与 state/submission.mjs，覆盖真实客户 API 路径/CSRF/同源 Cookie、会话边界取消和晚响应丢弃、跨标签页失效协议、PI Blob 隔离、冻结订单 key/body、失联先回查以及刷新仅保存账号分区 key。验证码与身份写操作串行；登出立即清 UI，失败可用原内存 CSRF 重试。独立审查发现 3 项 P2（在途写丢失未知标记、非 JSON 401 未清会话、登出失败不能重试），均已修正并复核关闭；25 项离线 Node 测试通过。新增模块尚无 Vue 页面/打包入口，未进行 npm build、浏览器 Cookie/Origin 或真实后端联调；不得把模块测试当作客户站完成。项目指定 emil-design-eng 与 review-animations/STANDARDS.md 在常用技能目录/插件缓存中未找到，本轮未实施 UI/动效；继续开发时须恢复该设计依赖或明确替代依据。正式双端页面、真实库存、MySQL 并发、全入口锁协议与部署门禁仍待完成。


- 员工拒绝/本地作废增量：POST admin/orders/{id}/reject和void-pi已接通。未建票拒绝保留修订，版本化命令幂等；本地stock PI作废持当前权限/客户与原票归属及关联锁，阻断远端/未知同步/令牌/回款/出库/库存依赖，保留Invoice/Intent/附件，eligible=0、Conversion永久tombstone、客户下载撤回，状态/回执/双审计/outbox同事务。独立审查指出旧快照可能绕过ORM终态检查，已改为按invoice_id无状态预筛选的SELECT status FOR UPDATE，并检查同事务dirty tombstone；独立22项和过期状态/同事务探针确认代码层修复。全门户471passed/2条既有Query.get警告，严格约定/diff通过。未执行真实MySQL双连接，因此并发验收仍未闭环；Core/bulk及全上游writer统一屏障/锁序、真实库存、正式双端页面、业务通知和生产部署链仍待完成。没有远端调用/生产迁移/发信/推送。


- PI后续修订增量：员工pi-proposals/publish-pi、客户accept/reject按kind分流、详情当前修订/差异与新版PDF已接通；同一Invoice/Conversion，独立PiAmendment状态、过期重提、持久回放及同事务回滚。实际PI金额不重价，付款须匹配配置，flat地址不猜结构。独立审查复现2项P2：跳过定价时漏namespace三方检查、商业头部未展示即可确认；分别补独立来源校验与Revision.invoice_presentation_json（新173迁移，已暂存未执行）。字段入hash、完整对比、发布/PDF只取接受快照，原探针复核两项均关闭。25专项含迁移通过；门户全套449passed/2条既有Query.get警告，随后补100行上限和撤回清active指针，相关38项定向测试通过；文档静态检查通过。尚需本地作废、所有Invoice写入口统一锁序/屏障与request版本联动、真实库存/前端/MySQL隔离并发和部署链。所有生产开关继续关闭。


- 提案差异/复购增量：revision_comparison提供经hash校验的紧邻历史修订对比、客户字段白名单及pending费用null；无查价能力不返回差异。POST客户reorder-quote按当前SKU授权/别名/合同价/库存重新报价，清PO，不新建请求；重复/未知行拒绝，HTTP Origin/CSRF已验证。proposal快照增加sales_user_id，adapter拒绝当前负责人同时改变但旧接受快照未改变的建票。全门户423passed/2条既有Query.get警告，随后固化审查别名探针1passed（合计424例，新增例单独执行）；独立审查28相关测试及别名/归属探针无P1/P2。仅隔离SQLite；真实库存、完整PI后续确认/重新发布、本地作废、真实双端前端和MySQL并发仍未完成。


- PI下载增量：GET客户orders/{id}/pi已接入当前权限/同access对象隔离、发票/明细当前锁读、publication及amendment校验和双摘要验证。渲染前commit释放锁，渲染后重新鉴权及核对发布身份再返回PDF；Core/bulk内容漂移同样拒绝旧发布。模板使用用户原Logo，只输出已确认客户展示快照，ReportLab生成且文本全部escape，新增后端依赖。12项专项测试通过（生产/开发Cookie、ORM/bulk/快照变化、渲染期间撤权、HTTP、长表分页及无链接注解、缺字体安全错误）；另以配置的微软雅黑字体生成25行中英样例，共4页逐页PNG目视通过，文件在scratch/portal-pi-preview.pdf。独立审查发现本地开发cookie硬编码问题已修复并补参数化测试，独立定向3passed确认关闭；门户全套411passed/2条既有Query.get警告，严格约定检查通过；缺摘要旧开发发布须重走受控发布，不能自动补签。后续PI修订确认/重新发布、Core写入口、真实库存、前端及MySQL联调仍未完成。

- PI修改保护增量：注册Session before_flush，只对已永久绑定conversion的portal票处理客户可见字段/明细及取消态；scalar当前版本锁/CAS、整数版本递增、publication撤回、amendment清接受、审计同flush。初建内部autoflush不触发撤回；内部同步字段不撤回。ORM删除/来源伪造/版本手改/跨票重挂行拒绝。独立审查复现过期属性history为空的来源/旧父绕过，以及初建多次flush误升version2；均已用DB原值和永久绑定门槛修复，定向13passed；独立审查者重跑原探针后确认三项关闭。用例已改名test_portal_invoice_lifecycle.py，避免与既有测试模块重名。早一轮全门户396passed/2警告、既有invoice金额/定价/关联同步/生命周期100passed/1警告；真实MySQL并发及Core/bulk写入口仍未覆盖，不能启用生产。

- 最新审核建票增量：approval_service及POST admin/orders/{request_id}/approve已接入；实时双权限/当前归属与代办/客户绑定检查，原成功回执先于交易来源读取。新命令双次校验（建票前及建票后）价格/库存/时效，实际Invoice+明细+ReceiptIntent与永久conversion/publication/PiAmendment/状态/回执/outbox同事务。仅已识别发票号UQ最多3次整事务重试，失败安全审计另提交。先跑全门户385 passed/2条既有警告，随后新增响应丢失回归及重试上限失败审计，审核定向13 passed；严格约定检查通过。独立审查无P1/P2，真实提交后响应丢失且库存失效的重放探针保持全部关联记录各一份。测试使用隔离SQLite，实际发票/ReceiptIntent和价格算法，部分编号/flags/员工权限等上游替身，未证明MySQL并发。客户PI下载、既有Invoice写入口撤回/版本联动及本地作废仍未实现，生产开关保持关闭。

- PI适配独立审查发现P2：含斜杠配件名称在源投影被截短，既有invoice配件投影恢复全名，导致一致性检查拒绝正常商品。已修为accessory使用完整标准名称，hair保持既有系列投影，未放松标准属性比较；新增源和发票领域回归，定向25 passed；独立审查者重跑真实配件定价完整探针通过，原P2关闭。门户全套373 passed / 2条既有Query.get警告；严格约定检查通过。旧草稿标准摘要若受影响须显式重导入，不重写历史订单。

- PI适配基础增量：invoice_adapter只从已接受当前修订生成InvoiceCreate，绑定真实OKKI客户/当前负责人，使用标准SKU属性而非展示别名，包装费作为明确总额internal_accessory；复用既有建票领域服务并逐字段核对返回的金额/实物属性。Invoice schema新增portal来源，服务仅allow_portal_source内部开关允许创建，来源字段验证UUID且禁止混用截图凭证；普通硬删portal发票拒绝。新增9项适配隔离测试通过；既有金额、定价、截图导入83项回归通过（26条既有弃用警告）。尚未注册审核建票HTTP或编排conversion/publication，尚未完成PI编辑撤回/作废/下载生命周期，不能启用生产。

- 最新增量：客户提案accept/reject服务与HTTP接口已接入，首次接受记录确认人/时间并进入ready_for_review，拒绝回submitted；均不建PI。接受重查当前SKU/价格/库存/公司权威版本/有效期，历史成功回放保留当前新提案，不恢复旧指针。新增11项隔离回归通过（含HTTP、撤权、过期、库存未知及原子回滚）；独立审查未发现P1/P2，并额外验证第二账号重放保留首次确认人、旧拒绝不覆盖新提案。审查者早期9项测试中1项fixture违反权限DB约束，主代理已修复并11项重跑通过；真实MySQL并发尚未验证。

- 完整目标继续按[开发文档](requirements/2026-09-30-customer-order-portal/README.md)实施，尚未完成。工作树 `C:/Users/lys-m/.codex/worktrees/customer-portal-dev-docs/commission-system`，分支 `codex/customer-portal-dev-docs`，基线 `54f77438328e5aa5d3c776ee309914447672d767`；无提交、推送或部署。
- 已实现基础：24张门户表模型、76条单列/复合外键、严格输入模型、金额/状态/库存观测/别名规则、CSRF/HMAC/邮件秘密封装、事务授权屏障原语、ORM历史快照保护、默认关闭的Settings、Invoice.portal_document_version。已注册默认关闭的5个客户认证API（bootstrap/challenges/verify/logout/session），屏障尚未接入全部上游写入口，不具备真实下单条件。
- 新迁移 `172_customer_order_portal` 已按项目要求暂存，当前单head；只做MySQL离线SQL生成，不曾执行数据库迁移。隔离MySQL运行时尚未配置，真实DDL与并发验收待补。
- 实际验证：`D:/commission-system/tmp/okki-test-venv/Scripts/python.exe -B -m pytest tests/portal --confcutdir=tests/portal -p no:cacheprovider -q`，backend目录运行，244 passed / exit 0；测试夹具禁止MySQL连接并使用内存SQLite。此244项是基础、认证、审计、管理、交接、映射、站点、邮件、目录价格与上游权限/归属/身份测试，不等于文档T01–T64全流程已通过。strict约定检查与两种diff检查通过。
- 独立实现审查发现并修复：跨域引用缺少复合FK、最终客户型号下的颜色歧义、未知费用跳过负数校验、非ASCII CSRF触发异常、编码不同却使用相同密钥。修订已补反例并定向复核。SQLAlchemy ORM不可变守卫不覆盖直接Core/bulk写，后续服务禁止批量重写业务快照。
- 认证增量：预登录CSRF、加密OTP outbox、共享邮箱/IP限频、失败尝试先提交后401、opaque会话、实时账号/成员/客户版本复查、退出撤销、no-store与安全Cookie、校验错误不回显输入。可信反代IP默认空列表，必须覆盖X-Real-IP且Uvicorn保留TCP peer（--no-proxy-headers）；部署链尚待实测。真实身份SQL谓词14项通过，但夹具仅复制上游类型列，不声称验证MySQL约束。
- 本轮独立认证审查发现OTP仅绑定账号版本的问题，现HMAC包含account/member/access标识和三类版本；成员或访问授权版本变化、相同版本改绑均有拒绝回归。邮件发送及管理配置的后续增量见下；登录审计、上游全入口屏障仍待补。
- 管理增量：默认关闭的6个管理API（客户列表/开通/更新、邀请、撤邀、账号状态）和8个RBAC权限种子；员工JWT仅取sub，事务屏障后实时权限检查。当前归属EXISTS用于列表/总数及对象范围；草稿创建、目录白名单、If-Match、邀请幂等回执、密文outbox、停用撤会话与审计已实现。权限seed写入口已加屏障；尚未执行真实seed。
- 本轮管理独立审查3项已修复并定向复核（5 passed / exit 0）：旧业务员在转交后仍能管理、review_required经suspended绕过、未验证账号停用后恢复死路。恢复invited不授予登录，需重邀并OTP验证。额外实际SQL测试验证当前权限撤销、去除super_admin、权限seed重复执行；HTTP测试验证旧JWT角色不透传、回放和If-Match。新门户代码尚未全面接入员工/客户上游变更屏障，不能启用真实客户。
- 交接增量：已注册客户详情分页账号/邀请摘要、外部身份rebind、显式transfer。管理测试改用真实上游身份SQL（复制类型列，省略无关约束）；身份重绑仅允许原canonical客户的有效身份，撤销旧会话/报价/邀请后保持suspended。转交验证新primary归属；只重指派明确选中pending请求，清当前接受指针、回到submitted，旧revision/归属快照不变。explicit_grant只给新负责人逐单授予交接时已有记录的读取，撤销旧授权，不覆盖未来单。归属和身份同时变化可先完成归属，保持review_required，再重绑身份，最后显式启用。独立有界静态复核无新增可复现缺陷；27项相关测试由主代理实际运行通过，审查者未重跑，不声称MySQL验证。
- 映射增量：已注册GET mapping、POST preview/publish；当前范围+目录白名单校验，MappingInput限制sku专属item_id/customer_sku，双版本CAS，发布重新投影完整目录、保存不可变快照与摘要、失效旧报价并审计。标准SKU/定价源不改写。目录撤销使旧映射源失效时暂停投影；后台仍可读取旧entries与有效sources，移除失效项重新发布后恢复。当前draft=null，编辑草稿由前端内存保存，未实现P1完整回滚UI。11项服务回归通过，独立旧base_version/目录撤权/历史摘要探针exit0，无新增发现。
- 站点增量：GET/PATCH settings已注册，portal_site:admin；首次缺失返回configured=false/row_version=0，PATCH If-Match:"0"原子初始化，后续需实际版本。仅name/status/policy可写；域名取部署Settings，USD/en固定，不接受密钥或任意URL。policy含15分钟报价默认、[24,48]小时提案选项、受控付款条款与默认code；无付款条款不能启用。策略变化提升policy_version并失效旧报价；站点启停撤销会话、预登录和未消费OTP，重开不复活旧凭证。11项测试通过；独立CAS/停用OTP/权限拒绝探针exit0，无新增发现。后续报价服务须读取策略并使用对应版本，不把这一步视为已完成交易联调。
- 邮件增量：新增mail_worker及默认关闭的portal_auth_mail调度，每5秒处理一个邀请/OTP事件；总开关关闭不访问表，仅邮件开关关闭仍清理过期密文。120秒租约、8次有界重试、当前授权/邀请/OTP复查、AES-GCM按事件解封、成功/取消/过期/耗尽清密文；SMTP_SSL在数据库事务外执行，稳定Message-ID，异常仅存安全错误码。新增14项隔离测试，全套185 passed；独立审查者另跑14 passed，无新增可复现缺陷。prepare后撤权不召回在途邮件，供应商回执丢失可重复投递，兑换仍拒绝失效凭证；不是恰好一次发送保证。尚未启动真实调度、发送真实邮件或验证MySQL竞争。
- 上游权限增量：用户创建/编辑/删除/启停/管理员重置密码、角色创建/编辑/删除和发票代办变更共9个HTTP入口，在首DB读取前取得authority屏障，锁后按当前员工权限重新鉴权；代办replace_grants服务也先参与屏障，不改变原commit边界。PORTAL_ENABLED=false不读门户表，保留现有入口行为。14项新增隔离回归覆盖旧super_admin claims拒绝、第一条SQL、自己移除角色/停用后不能恢复、变更回滚、代办撤销。独立审查发现相邻密码重置入口可被撤权旧JWT滥用，已补同样guard与回归。SQLite不能证明MySQL并发，客户归属/身份及其他上游入口尚未全部接入，不声称全局撤权已闭环。
- 客户归属联动：assign_customer/transfer_primary_owner/claim_public_pool_customer及提案执行路由/服务、合并拆分执行器、逻辑归属CAS均先取得authority屏障；实际primary新分配或逻辑归属迁移暂停受影响客户门户，撤销会话/未消费邀请并失效valid报价，保留consumed报价和历史订单证据。重复同负责人/已有分配、协作人增加不暂停；review_required重复处理不反复增加访问版本。11项新增隔离测试验证真实assignment SQL、撤销/回滚、未消费报价及入口屏障优先；客户事件写入在夹具中stub，上游表省略无关约束，不声称完整合并拆分或MySQL并发通过。独立事务审查另跑11 passed，未发现新增可复现阻断问题；确认savepoint外持屏障、异常共同回滚与成功重放不重复暂停。身份确认、同步与归属投影入口仍待逐一接入，总开关保持关闭。
- 身份同步增量：attach_identity_candidate/resolve_business_context/confirm_identity、OKKI客户/联系人投影、Alibaba询盘投影、project_sync_batch及ingest_candidates在首业务读取前取屏障；身份变更后重查已配置binding，合法的名称/置信度/来源证据刷新不撤会话，标识/验证/争议/所属变更导致绑定失效才转review_required。选择范围含access实际引用的identity，修复物理客户A/逻辑客户B时漏复核B的问题。候选Agent鉴权先取屏障；主审发现resolve_token内部usage commit释放锁，新增commit_usage=False供此入口使用，last_used_at随业务事务提交/回滚，其他调用默认行为不变。10项新增隔离回归含真实身份SQL、逻辑归属与真实token ORM事务；确认冲突的仲裁存储在夹具中stub，不声称完整同步或MySQL并发已验证。独立复核关闭逻辑归属漏撤权与鉴权内部commit问题；另跑身份8 passed及真实token/嵌套回滚探针exit0，确认身份恢复不复活旧会话。外部员工账号绑定写入口及其余全局入口覆盖核对仍待完成。
- 绑定/登录审计增量：外部员工绑定create/delete/candidate-bind三个管理入口先锁后实时鉴权，底层三个写服务参加authority事务，不改变原commit边界。新增auth.verified/auth.verify_failed/auth.logout审计，失败actor为system不冒认账号，成功关联实际会话与access；只存公开对象ID、必要内部主体ID、固定动作和关联ID，无OTP/token/邮箱/IP/正文。验证失败的审计与尝试次数由原HTTP路径先提交再401；前置CSRF/预登录/限流拒绝不在这类业务审计范围，不声称全量HTTP拒绝日志。7项新增回归及全套227 passed；原Query.get产生2条弃用警告，无失败。剩余全局入口覆盖核对、真实MySQL及完整链路仍属启用门禁；下一批开始W03目录/报价实现，保留这些未完成项。
- 目录价格增量：新增GET catalog及catalog/{item_id}，真实客户Cookie认证、授权集合、发布状态、分页/搜索/分类/facets及当前别名映射；只按客户展示值搜索，不泄露标准SKU/原始数量/规则。无view_price不计算也不返回价格；hair使用standard_json的product_display/length/price_unit/color，配件使用精确product/sku复用现有定价；缺价/零负价/外币不变成免费。独立审查两项已修订：PORTAL_OKKI_NAMESPACE明确当前Ark价格源，客户/商品/配置三方相同才能读裸company_id规则；配件与hair共用规则ID/type/value/updated_at价格指纹，别名不参与。17项目录回归含真实标准价SQL和HTTP，全套244 passed。load_observations目前显式空，所有真实库存unknown；image_url=null；尚无可信库存源、受控图片解析、标准SKU导入/在售复核及报价写入，不能开放真实下单。
- 标准SKU源适配增量：sku_source.load_snapshot按配置namespace和精确product_id/sku_id读取只读OKKI镜像，要求双方启用、唯一匹配和完整标准字段；拒绝非规范ID、缺启用列、重复行及错配。标准属性/身份形成指纹，revalidate要求显式重新导入发生变化的规格，客户展示别名不参与；配件不虚构发品尺寸/重量。新增15项真实SQLite镜像SQL测试，全套259 passed、2条既有Query.get弃用警告；严格约定检查通过。该适配器尚未接入管理端导入/发布和报价事务，不把底层可用当作完整SKU上线；真实库存观测时效、图片及报价链路仍待实现。
- 商品管理增量：新增管理员GET catalog、POST catalog/import、PATCH catalog/{item_id}；复用portal_site:admin实时授权与首读authority屏障。精确SKU导入草稿、重导入CAS保留public_id且退回draft、发布重新验证标准源；配置明确单位/换算/MOQ/step，不接受客户端标准属性或价格。修改同事务更新有效授权客户catalog/row版本、失效valid报价并写审计，consumed报价与历史快照保留；源不可用仍能下架。18项新增隔离SQL/HTTP测试通过，端点与开发契约同步；真实MySQL并发、单位经营验证、管理UI与报价链路仍待完成。
- 商品管理独立审查修复：下架/重导入某个已映射商品曾阻断客户其他商品，现读取仅应用当前有效源键、历史映射不变；新映射提交仍严格拒绝失效键。发布配置前新增所有有效授权客户完整投影校验，展示歧义导致整事务回滚。新增禁用/重导入后其他商品列表与详情、历史不变、配置冲突回滚回归；商品管理21项及映射11项合计32 passed。早期交接中“撤下后全目录失败关闭”行为已由本修复替代。
- 报价增量：新增POST/GET quotes；创建先检查写开关、真实客户会话/CSRF与下单查价能力，授权目录后精确复核标准SKU、现有合同价、库存观测/MOQ/step/换算。不可变quote保存身份/映射/政策/价格/标准/库存及交付快照，费用pending且total=null，只有创建账号可读；公共响应白名单剔除标准源、规则指纹与原始库存。GET不重算价格；完整证据hash校验，创建审计不记录地址/金额明细。独立审查发现普通MySQL DATETIME丢微秒导致回读hash失效，已将expires_at在hash前统一秒精度并补测试。19项隔离测试通过，含真实SKU/价格SQL、HTTP同源CSRF、同公司他账号拒绝、权限撤销、历史不变、时间边界与共同回滚；库存为测试注入，生产空适配继续拒绝真实报价，未完成可信库存来源、订单提交及真实MySQL链路。
- 订单提交增量：新增POST orders和GET orders/by-key；同键同body回原请求，不同body冲突、同quote换键拒绝；先当前身份和回执查询，再新提交权限/写开关/报价版本/SKU/映射/当前价/库存核验。request、submitted revision、标准与展示明细、quote consumed、审计及引用型order_submitted outbox同事务，未生成PI/占库存/发送通知。成功回放不依赖库存与价格恢复，撤can_order仍可恢复旧结果，撤view_price裁剪金额，停用仍拒绝；唯一冲突恢复只处理请求幂等键。独立审查发现revision摘要仅引用quote，已改为revision_evidence覆盖实际修订及排序明细、固定金额和重量精度，金额读取前验证；新增模拟SQL漂移拒绝。21项订单隔离测试通过，含真实表FK/事务、HTTP201/200与已知唯一冲突恢复、其他异常不吞、同公司第二账号隔离、中途flush故障回滚。真实库存、订单通知worker、订单列表/详情/提案/建票及MySQL并发仍待完成。
- 订单读取增量：客户与员工各新增GET orders及orders/{id}，scope在SQL count/分页前应用；同access有效成员共享，报价/按key回查仍限创建账号。员工需portal_order:read且当前servicing/access/主assignment一致，或有效历史grant/read_all；无隐式团队公海范围。历史grant精确订单，request_history仅严格早于授权时刻不含同秒/未来；read_all不授写。客户撤查价时列表及嵌套详情裁剪金额/币种/费用/付款条件；详情验证revision实际hash，展示/交付白名单与安全事件时间线，无内部SKU/指纹/审计diff。11项隔离服务+双端HTTP测试通过，覆盖跨公司/业务员count和detail、同公司共享、归属改变、历史撤销/过期/时间边界及分页。employee当前权限与上游绑定在fixture中部分mock，不替代真实角色联调；actions为空，取消/提案/PI写流程未接入。
- 取消请求增量：新增POST orders/{id}/cancel，强制同源/CSRF/If-Match、当前客户能力及同access范围，authority后锁order；稳定cancel+request回执先于新动作版本检查，相同reason原回放、不覆盖首次主体，异reason冲突。新动作检查写开关/版本/待处理状态/无invoice及conversion；设置cancelled清接受指针，同事务回执/审计/引用outbox，保留consumed quote、修订和明细。客户详情按当前开关/能力显示cancel，员工读取仍无写动作。11项隔离测试通过，含三种待处理状态、权限撤销、不同命令、终态、回滚、HTTP头/回放、状态错配但已有conversion防护。通知仍仅事件，实际审批及MySQL取消并发未验证。
- 业务员提案增量：新增admin POST orders/{id}/proposals，实时portal_order:write及当前servicing/access/有效binding，复用真实can_act_for本人/代办SQL，read_all不能授写；quote_service抽取build_lines给报价与提案共用标准SKU/合同价/库存规则。提案受控费用/付款/有效期，保留PO，完整实际revision/line hash与公司权限快照，稳定line_key、清接受指针、不建PI。propose+起始版本回执同body回放异body冲突；详情有价权限时展示proposal hash/expiry。审查发现awaiting_customer过期后不能重提，已允许精确到期时生成新revision保留旧证据，未到期仍拒绝。提案10+报价19共29项隔离回归通过，含HTTP、真实代办授权表与回滚；首次测试补齐ArkUser原有joined角色关系表，未mock代办判定。当前权限上层fixture仍mock、库存仍注入；客户接受/拒绝、差异展示、PI和真实MySQL未完成。
- 下一步顺序：W03目录/标准价格/可信库存读适配及映射；W04幂等请求与提案；W05同库建票/本地作废/发布版本；W06英文客户站及中文后台；W07隔离MySQL、浏览器验收、部署制品与回退准备。保持完整范围，不以基础单元测试替代最终验收。
- 接入发现：现有invoice路由部分先锁invoice，需先改锁入口；未同步PI既有取消要求删除，门户必须补本地作废并保留lineage；外部库存读函数没有可信observed_at，缺失时失败关闭，不能用NOW凑时间；客户同步/合并/角色seed均属于屏障覆盖范围。


## 2026-09-30 客户下单门户开发文档与对抗审查（文档完成，尚未实现）

- 分支 `codex/customer-portal-dev-docs`，代码核对基线 `54f77438328e5aa5d3c776ee309914447672d767`。交付[8篇开发文档](requirements/2026-09-30-customer-order-portal/README.md)：英文客户站、中文方舟管理端、邀请登录与隔离、标准SKU映射、客户提案确认、同库幂等建PI及后续版本发布。
- 两条独立对抗审查与主审共记录12项设计缺陷，已修订并定向复核；另列64项待实现测试。文档检查证据见[审查记录](requirements/2026-09-30-customer-order-portal/07-adversarial-review.md)。本次不改业务代码/数据库、不发信、不建票、不部署；B01–B07为试点前经营配置。


## 2026-09-30 出库备注空格误报与单据恢复

- 后续重新同步仍被后端 `outbound_sync_plan.verify` 的严格备注比较卡住（event5152、record93064、sync_uncertain）。按持续数据修复授权，09:34:57备份并核验持久plan、完整invoice edit_version、当前小满订单、出库ID/单号/活动列表、所有明细/成本/其他单头及无验货记录后，仅将event.action/result恢复sync_done及已核验快照；原plan不变、不重发POST。办公室备份 `D:/commission-system/tmp/outbound-recovery-836/20260930-093457-304664-sync5152-before.json`；恢复材料交付保留在主目录 `tmp/outbound-remark-20260930/`；恢复脚本 `repair_outbound_sync_5152.py`。独立审查完成；实际生产 `ensure_printable + apply_header + list_outbound_items` 回滚式调用通过，最新明细10/1/5可打印。
- **永久修复范围已补齐，尚未发布**：JS自动创建/恢复及后端 `outbound_sync_plan.build` 的remark_changed、`verify` 均仅忽略首尾空白；后端新增隔离回归覆盖即时核验与发送/回读异常后的恢复不重发。用户先要求修数据、随后授权合并推送；生产代码未发布。

- 分支 `codex/outbound-remark-trim`，worktree `D:/commission-system-codex-outbound-remark`。`okki_outbound_creator.mjs` 创建回读及持久意图恢复时仅忽略备注首尾空白；原文提交、内部空格/换行、身份/商品/SKU/数量/单价及防重复保护不变。本次交付包含本地修复及用户授权的合并推送；生产服务未发布。
- 整合最新 `origin/main`（5d0c1449）后：出库脚本79/79、后端同步/打印/任务104/104通过，后端在独立源码目录使用SQLite与假小满并禁用MySQL连接；新增22项JS和9项后端场景覆盖创建、回读、异常恢复及内部空白保护。独立 agent 最终审查通过，以origin/main为基点的严格约定检查与diff检查通过。Git 巡检为 `--no-fetch` 本地快照；主目录既有 `.pnpm-store/` 未动。
- 用户授权下，2026-09-30 09:15:38 仅将发票836对应task356（order105822029109439）从误报 `uncertain` 修复为 `done`，清空 `last_error`，尝试次数仍1。原始意图、小满订单、按ID及单号查询的出库详情、有效列表均核验；3行数量10/1/5，金额USD463.25，仅备注末尾空格不同。保持outbound105822029440028待出库，不重建、不调用出库POST、不删除意图。
- 办公室服务器原始数据/意图/实时核验备份：`D:/commission-system/tmp/outbound-recovery-836/20260930-091538-411631-before.json`；本地恢复脚本保留在主目录 `tmp/outbound-remark-20260930/repair_outbound_836.py`，默认只读，不要重复执行 `--apply`。使用现有严格校验连接 `acciowork@127.0.0.1:2233`；北京查询通过办公室现有受信任SSH连接。
- 恢复后发现另一保存发生在09:16:13，发票转 `ready/not_synced`：首款Super改Standard（产品86457574472097/SKU86457574472159）、单价29.55→26；Other Items单价20→55。小满出库仍原版本。用户随后自行重新同步：发票09:21:04 synced，原出库09:21:29已更新到新产品及单价，三行金额USD462.75。

## 2026-09-29 客户素材门户颜色与纹理分行（2026-09-30 已发布）

- 内部“客户素材门户”预览和客户外部查看站（包括拍摄工作区的“客户效果预览”弹框）在 Product type 分组及现有标签筛选之后，按 Color names + Textures type 的组合分别展示素材行；行首突出纹理类型，缺失的颜色或纹理不显示占位文字。
- 使用六张覆盖同组合、不同组合及缺失标签的素材做浏览器回归，两处页面行数、素材归属、筛选收敛与草稿预览均通过；共享分组单元测试 8 项、前端构建和约定检查通过。改动已合并推送 `main`（`bb7ff685`），统一入口固定该提交完成办公室与云端发布（`release_id=d62d6669f71d401796d9a5f304fc6d7b`，`deferred=[]`）；`leshine.cloud`、`leshine.work` 返回新版前端资源，客户外部站正式入口 `media.leshine.cloud/` 返回新版分组脚本与样式。实际登录态下的客户页面仍待人工复验。

## 2026-09-29 客户拍摄素材预览与空标签标题（已发布）

- “客户效果预览”原先直接把 Vue 响应式批次对象通过 `postMessage` 发给外部站 iframe，浏览器抛 `DataCloneError`，页面收不到草稿预览消息。现按外部站实际需要的字段构造普通对象，避免发送内部批次元数据；未设置 Color names / Textures type 时不显示占位标题和多余分隔符。
- 用 `DST-20260723-0003`（task ID 59）的批次与标签做只读样本，本地浏览器注入模拟 API 后，工作区和客户效果预览各显示 18 张素材、无控制台异常或登录页；单元测试、前端构建与浏览器回归通过。修复已合并推送至 `a3b9329e`，统一入口固定该提交完成办公室与云端发布（`release_id=a7a753ded5fb4860b81ebecb2a0d5408`，`deferred=[]`）；两地主站公网均返回新前端制品，客户预览页监听器可访问。实际登录态下的任务页面仍待人工复验。

## 2026-09-29 客户拍摄素材预览 MySQL 1267（已发布，任务页待复验）

- 任务 `DST-20260723-0003`（task ID 59、批次 ID 8）打开“上传素材”时报“数据库连接失败”。线上数据库已在 171，`display_value` 存在；真实原因是批次 `customer_id` 使用 `utf8mb4_unicode_ci`，客户标签绑定表使用 `utf8mb4_0900_ai_ci`，素材标签联结触发 MySQL 1267。该批次当前有 18 张素材；带显式排序规则的只读 SQL 可正常联结，修复代码在共享 MySQL 上只读执行 `_batch_full` 返回 18 张素材、36 条客户标签，无数据库异常。
- 分支 `codex/customer-media-collation-fix` 对内部预览和客户门户两处联结显式使用 `utf8mb4_unicode_ci`，不新增迁移或改业务数据。回归测试先失败后通过；`test_customer_media_tags.py` 16 项通过。`test_customer_media.py` 的目录上传测试因样例未绑定客户标签，在未修改的 main 上同样失败，和本修复无关。
- 修复已随 `0bac2dfb` 发布，并包含在本次 `a3b9329e` 完整发布中；数据库仍为 `171_customer_tag_display_value`，任务页面仍待实际登录态复验。

## 2026-09-28 预售全流程当前租户联调（页面回归修复已完整发布）

- 分支 `codex/presale-full-flow` 已完成方舟创建预售主单、首款发送、独立运费单与运费回款发送、实时资金核验、待出库创建和确认实际出库的当前小满租户真实链路。专用测试单据已按精确 ID 清理：亮哥删除两笔测试回款后，有效回款列表确认消失；出库单、订单和客户也已删除并回读确认。无真实银行转账或实物发货。完整 ID、验证边界和清理证据见[预售全流程验证报告](reports/2026-09-28-presale-full-flow-verification.md)。
- 修复首批出库占用初始化、预售与普通回款派发隔离、待处理队列饥饿和关联出库完整扫描；受影响后端 293 项、前端 21 项及生产构建通过，独立审查未发现新增 P0/P1。真实探针覆盖一件商品、一次最终出库、零手续费；多批次和手续费路径由隔离测试覆盖。
- 已合并推送 `main` 并通过统一入口发布 `de689e3b` 到办公室和北京，`release_id=9d5247df872d4057a14a570fdedc0610`、状态 `succeeded`、迁移仍为 170、出库调度已核验恢复。两站运行配置均启用 `PRESALE_SETTLEMENT_ENABLED`、`PRESALE_DELIVERY_ENABLED`，仓库 ID 为已联调的 `8193514242746`；重启后两站预售能力均返回启用，公网健康均为 `ok/connected`。小满原生销售报表包含独立运费单，方舟已明确标注并从商品统计中排除。
- 页面回归修复 `08bb5f73` 已合并推送 `main`，先经 `--cloud-only` 发布北京后端及 `leshine.cloud` 前端。办公室 SSH 恢复后，统一发布入口固定 `047e90ad` 完成办公室及云端完整发布，回执 `MANAGED APPLICATION RELEASE COMPLETED`、`scope=office-and-cloud`、`deferred=[]`；数据库迁移仍为 170，出库调度已核验恢复。办公室仓库 HEAD 为 `047e90ad`、NSSM 服务运行中，两站公网 `/health` 均返回 `ok/connected`。登录 `leshine.cloud` 与 `leshine.work` 实测“新建预售单”可打开，产品、配件、首笔定金和结算区域均呈现，未再出现 `order_type=presale` 的 422。当前 admin 业务员未绑定 OKKI 且无代办候选，本次未创建或同步新单据。

## 2026-09-28 Windows 远程更新中心（Codex，已授权合并推送，未部署）

- 工作树 `D:/commission-system/tmp/commission-system-deploy-console`，分支 `codex/windows-deploy-console`，已整合远端 main `46a2f171`。交付原生 Windows `ArkDeploy.exe`：操作者电脑经 SSH 控制办公室，办公室复用统一 deploy 入口更新受管环境。
- 已实现办公室/cloud/work 逐项只读自检、固定候选 SHA 与改动文件/迁移展示、真实组件事件进度、更新后检查、失败诊断与报告导出。新加坡到办公室隧道、匿名公网 API 鉴权契约、PM2 正 PID 等避免静态站可达但业务失效的误报。
- SSH 请求无常驻监听服务；后台 worker 使用 breakaway + detached，持久 run id、互斥锁和本轮回执。重复请求不重发；缺失回执、启动陈旧、进程死亡或 PID 复用标为待核实并保留锁；切换连接清除旧报告与准备授权。独立审查发现的问题均已修复。
- 整合 main 后部署全套回归 477 passed、12 skipped、13 subtests passed；唯一失败 `test_storage_routing.py::test_bad_public_route_rolls_back` 的 mock `StopIteration` 在未加入本次改动的 main `46a2f171` 同样复现。新增桌面、发布流水线及迁移168恢复回归通过；原生 EXE 构建与5项窗体自测、以 `46a2f171` 为基点的完整约定检查通过。独立合并审查确认迁移168原发布版本/调度基线保护完整保留。详细使用及验证方法见 `deploy/desktop/README.md`。
- 用户已授权合并推送；未更新生产服务。用户完成 `acciowork@127.0.0.1:2233` 到办公室22端口的公钥授权，本机私钥留在用户 `.ssh/ark_office`。程序已预填账号/地址/端口和本机密钥路径；BatchMode + 严格主机指纹校验已实测成功，办公室 Python 3.12.10。
- 2026-09-28 16:23:51 北京时间，经实际 EXE Transport 执行只读检查39项：34通过、1必要项失败（桌面进度协议缺失）、1告警（旧okki-sync masked/inactive）、3未知（okki-inventory、办公室n8n、okki-shopify-cron最近作业）。办公室后端/连接器/数据库、北京后端/色块/Nginx、两站匿名API与HTTPS、新加坡到办公室隧道、已登记北京PM2及OpenClaw用户服务均通过。报告保存在本任务 `.deploy_state/live-probe.json`，交付包附副本。
- 实机安装仓库 HEAD `9eae9be811dbc7ba052bf557a7e9e94303649b48`，干净且无发布/迁移恢复阻断。本次已整合更新的 main，保留服务迁北京及迁移168保护；不得以旧基点部署器覆盖服务器。PM2只读探针已按现用schema_release固定root HOME/PM2_HOME与sudo上下文，组件名称不再假定出库轮询器仍在新加坡。真实SSH断线后的后台保活演练仍未执行。
- 首次使用前，办公室部署器必须集成 `publish.py` 事件改动及 `desktop_events.py`；客户端会明确检查并阻断旧部署器，不自动覆盖服务器受管源码。原项目未跟踪 `.pnpm-store/` 未改动。

## 2026-09-28 临时战报总览 500（本地已修复，未发布）

- `codex/battle-report-500`：总览读取触发 MySQL 1267。近期加入的运费订单排除条件在 `commission_db.ark_receivables`（`utf8mb4_unicode_ci`）与 `lsordertest.okki_orders`（`utf8mb4_0900_ai_ci`）之间直接比较订单 ID、订单名和客户 ID；回款排除条件有同类问题。只在这些跨库比较的镜像侧显式使用方舟列的排序规则，不改表结构或业务数据。
- 修复前以只读调用复现：战报详情成功、总览抛 1267；三个订单比较和回款订单 ID 比较的 `EXPLAIN` 均报 1267。修复后用共享 MySQL 只读调用验证战报 1 总览返回 22 名成员、异常数 0，回款排除查询 `EXPLAIN` 通过；受影响的 189 项隔离测试通过。增量约定检查无违规，全量检查仍被既有 13 项前端 UI 基线问题拦截。仍需按发布流程合并、部署并用登录页面复验，当前生产应用尚未切换到修复代码。

## 2026-09-27 预售当前租户外部契约联调（开发中，未开放）

- 分支 `codex/presale-full-flow`；亮哥授权在当前租户创建专用测试客户/订单/回款/出库单，测试订单暂用 API 账号默认归属。测试客户及单据均带 `ARK-PRESALE-CONTRACT-20260927-2149` 标识；原始一次性意图与回读回执保留在该任务 worktree 的 `tmp/presale-live-test/`，不要重复提交已有请求。
- 已确认同一小满订单能生成两张各 1 件、不同编号且关联同一订单明细的待出库单；无商品的运费订单能单独收款。**小满也接受第三张使待出库合计超出订单数量**。亮哥授权清理后，四张待出库测试单及两张主测试订单均已按精确 ID 删除，并两轮有效列表确认不再活动；两张主单先从“已完成”改为“草稿”后才被删除。亮哥自行删除测试回款 `105815086705101`，本任务两次有效列表确认已消失；运费订单 `105815085959831` 改草稿后删除并确认不在有效列表；客户 `105815081003965` 从公海删除，详情返回 404 且有效列表无记录。均无实际银行转账或实物出库。
- 完整 ID、金额、读回证据及待处理门槛见[当前租户联调报告](reports/2026-09-27-presale-live-contract.md)。业务已接受小满原生销售报表包含运费订单，须明确标注；亮哥表示已配置预售出库及关联回款写权限仅方舟 API 账号可用，**尚无非授权账号失败的独立验证**。任务分支已加入商品统计排除、运费目标冻结发送、目标级回款、分批待出库与显式确认实际出库、异常核对/明确失败重试。状态 2 回读及确认前现逐笔核验远端有效回款全集及状态 1 明细基线；已出库资金定时复核并公平轮转失败任务，下一批报价校验历史有效回款。40 项预售隔离回归、受影响领域 205 项通过。代码尚未合并/发布，生产预售开关及远端派发固定关闭。2026-09-28 的专用测试单已真实完成状态 1→2 编辑并按 ID 回读，明细 ID/数量/售价/单位/成本均未变化，随后出库单、订单、客户均清理并核验。仍缺方舟执行器端到端联调及非授权账号权限验证；迁移 170 已生成 MySQL 离线 SQL，但未在隔离 MySQL 执行。完成后方可开放按钮。
- 共享只读业务镜像在 2026-09-28 00:00 增量同步后仍留有 18 行远端已删的测试客户/单据/明细，测试回款尚未进入 `synced_payment`。精确 ID 备份、校验和事务清理脚本已准备在本任务忽略目录；`CLAUDE.md` 只允许对业务镜像执行受审计回款日期单列修复，镜像清理须获专门例外授权或由维护方处理。

## 2026-09-26 色卡工作台自动备份保留策略（线上已启用）

- 用户授权调整自动备份策略。已通过 `deploy.bat --colorwork-backup-policy` 在北京安装 `ark-colorwork-backup-retention.timer`，enabled/active；每小时执行、最多5分钟随机延迟，首次手动执行completed且未额外删除（当前两份）。验收时下一次为北京时间19:04:25，主站与工作台公网健康200、数据库connected，磁盘35%，服务器Git tracked diff为空。
- 发布前完整备份保持不变；清理保留最近两份加成功恢复引用。与发布器共用backend.lock，发布中跳过，失败/恢复异常/服务不健康则拒绝删除。检查保留SQLite、R2对象与分片文件存在/大小/分片合计；不等同完整恢复演练。只处理colorwork/backups，不处理data、checkouts、迁移中转和前端版本。
- 安装独立互斥锁、停timer后检查在途oneshot，失败恢复策略文件及timer基线。首次线上执行完成但systemd已回收InvocationID属性，安装验收因无法核实而自动撤回；随后改成安装UUID+脚本SHA+worker InvocationID绑定回执，重新安装验收通过。最终制品SHA256 `8c3e4ffe9724d096522544e891617354235fca51b0f0ffce3aab31bd2129ee41`；执行InvocationID `cc11612738cb4db7aedbd5184a37de27`与journald对应。
- 集成最新 main（基点 `5d954a06`）后部署回归435 passed / 12 skipped / 2 deselected（此前确认的storage mock用例）；最终专项新增旧安装/错误SHA/完成单元GC校验后，policy+retention为22 passed / 1 Windows symlink skipped。Linux隔离六项验证了安装锁、发布锁、symlink、缺失R2 blob、保留两份与重复noop。独立审查通过；约定检查仍有13项既有前端问题，覆盖本次提交的增量检查无违规；社媒服务16项回归通过。
- 维护命令与暂停恢复流程见 [运维手册](runbook.md) 和 [部署说明](../deploy/README.md)。本地非敏感回执 `.deploy_state/colorwork-backup-retention/verified.json`；服务端 `colorwork/maintenance/retention-outcome.json` / `retention-last.json`。本次交付来自 `codex/agent-cloud-migration`，亮哥已授权合并并推送 `origin/main`；已安装策略独立于Git工作树和业务版本切换持续生效。


## 2026-09-26 OpenClaw / Agent 服务迁到北京（线上完成）

- 北京 `leshine.cloud / 154.8.205.162` 已运行原 OpenClaw 2026.6.6、钉钉监听、客户/库存 MCP、物流 MCP、社媒 MCP、中继、OKKI 同步/出库轮询，以及从源 crontab 精确搬迁的 10 项 OKKI/Shopify 任务。飞书通道 running；钉钉 service active 且持有已建立的 Stream TCP 连接，无新启动错误，未发送测试群消息。
- 原 Node 22.22.1、Chrome 146 和全部配置、会话、游标、SQLite、MCP OAuth 状态已迁移。最终镜像在源调度停用、9 个 Node cron 任务空闲并冻结、所有服务 PID 归零后执行；三个 OpenClaw SQLite 与 relay SQLite quick_check 均为 ok。旧 gateway 30 秒停止超时产生 SIGKILL，确认 PID=0 后清除 failed 状态并完成两端数据检查，未把超时当正常停止。
- 北京 `/inventory-mcp/sse`、`/shipment-mcp/sse`、`/mcp/social-customer/`、`/relay/ws` 已经 HTTPS 生效。库存/物流完整握手与实际只读调用成功；社媒五项真实只读查询通过，无/无效 token 返回401。中继新域、旧主域和旧 relay 子域均通过带认证 WebSocket 握手，WebSocket query token 路由禁用 access_log。
- 新加坡旧单元 disable/mask、三项 PM2 注册移除、root Agent cron 为0；只保留旧域名到北京的 TLS 校验转发。北京全部开机启动已 enabled，服务端口仅回环。库存已自动完成两轮同步，出库 oneshot Result=success，Shopify HTTPS 可达（匿名请求401）；未额外触发同步或对外消息。
- 后续 Agent 部署规则已写入北京 OpenClaw 的 AGENTS.md/TOOLS.md 和本分支 CLAUDE.md、platforms.json。发布器与 DDL writer 改为北京 ubuntu SSH + sudo 控制 root 进程；新版出库 `--prepare-only` 线上通过。旧源 mask 会阻断旧发布器复活任务。
- 本次交付来自 `codex/agent-cloud-migration`，包含指向北京的部署器与清单，亮哥已授权合并推送；主应用后续发布使用集成后的版本，不能使用仍指向新加坡的旧发布器。操作与回滚见 [部署说明](../deploy/agent-cloud-migration.md)，非敏感执行回执在该 worktree `.deploy_state/agent-cloud-migration/`，源和目标受限恢复资料在 `/var/lib/ark-agent-migration/`。
- 临时传输公钥授权、源私钥及中断的首次传输目录已清理；保留原始源数据与受限回滚证据。源历史 `okki-sync.service` 也已 mask，防止旧别名复活。
- 部署回归 413 passed / 11 skipped；排除 `test_bad_public_route_rolls_back` 的2个用例（其中1项既有 mock 耗尽失败，相关文件未改，独立复现）。社媒测试16项通过，约定检查仍有13项既有前端问题。独立审查修复历史 restore_152 拓扑误用，旧日志保持原拓扑校验，实际恢复遇迁移后清单则在触碰服务前拒绝。
- 北京迁移后磁盘曾剩余约8.54 GiB（95%已用）。9月26日18:16经用户明确授权，核验当前/成功恢复引用、两份保留备份的10个SQLite、R2结构及进程引用，并持有部署锁后，删除41份色卡工作台旧全量备份；保留最近两份（含当前恢复点），释放103.12 GiB，可用约111.67 GiB，使用率降至35%。主站及工作台公网健康均200、数据库connected，相关服务active。未删除运行数据、候选代码、迁移中转资料、前端历史版本；当次手工清理未修改自动策略，后续策略已上线（见本页上节）。逐目录删除回执在北京 `/var/lib/ark-storage-cleanup/20260926T181626/receipt.json`。

按日期核对各条状态；历史交接另有[2026-09-17 快照](archive/handoff-2026-09-17.md)，本文件保留后续追加在旧条目末尾的记录，避免遗漏未完成事项。

## 2026-09-26 预售本地契约模拟与截图入口隐藏（未上线）

- 分支 `codex/invoice-presale-button`：订单发票页隐藏 AI 识别 OKKI 截图入口；预售按钮不可用的原因是默认关闭的发布开关，后端也会拦截建单。页面现在明确提示预售建单暂未开放。
- 分批出库与独立运费目标已增加不发送的载荷构建器，并用两批次与异常身份/金额 fixture 模拟；没有隔离 OKKI 租户和隔离 MySQL，未进行真实联调，预售开关保持关闭。后续验证与发送器门槛见[本地适配报告](reports/2026-09-26-presale-local-adapter.md)。

## 2026-09-26 结汇助手手机应用（代码交付，未部署）

- 分支 `codex/forex-mobile`，新增 `/fx-settlement` 全屏入口与桌面安装配置；手机采用行情/测算/方案底部导航、触屏表单及方案卡片。桌面原入口保持双栏；复用现有资金计算和权限，无迁移。说明见 [结汇助手](requirements/2026-09-24-fx-settlement-advisor.md)。
- 手机登录及会话过期回跳已补齐，不再误入素材 `/m/`；安装元数据与发货质检统一管理，已回归两个应用之间切换及普通页面恢复。
- 构建、41 项 Node 回归、Chrome 320/390/430/768px 与 1440px 模拟接口流程通过。独立审查发现的折叠无效字段定位问题已修复并通过浏览器回归。截图和构建证据保留于主工作树 `tmp/fx-mobile-integration/`。
- 完整约定检查被 13 项既有未改动页面的 UI 基线问题阻挡；增量规则单独核验。Git 巡检已运行 `--no-fetch`，仅本地快照。本轮按用户授权合并推送至 main；未部署，目标环境发布与真实手机安装验收仍待进行。

## 2026-09-25 main 合并与全平台纳管目标发布

- 已将 `codex/invoice-schema-repair`、`codex/shipping-media-owner`、`codex/project-knowledge-tidy` 合入 main 并推送；统一部署固定提交 `ce465a7241f76b14f0687dcd5155f6d5977a9c78`，发布回执 `release_id=d9d11923d9574fa7a6948458bcd6a838`、`status=succeeded`。办公室与北京后端、两站主前端已更新；PM 和客户素材静态站无文件变化；新加坡出库轮询器制品核验并恢复原启用状态。共享数据库从 168 升至 `169_pcw_customer_workbench`，`schema-writers=completed`；两站 `/health` 返回 `ok/connected`，首页 HTTP 200。
- 发货质检媒体 Nginx 专项入口另经 prepare 后在办公室与北京激活，两个区域均返回 `activated`。普通源码发布不会自动切换该路由。
- 客户工作台已随本次发布；会话 AI 摘要缺少异步消费者且开关默认关闭，前端暂不提供生成入口，API 在无可执行路径时返回 `AI_ANALYSIS_UNAVAILABLE`。待补队列消费者、预设和灰度验收后再开放。PCW 每日评估等门控仍按默认配置，不能将代码上线等同于业务启用。
- `deploy/platforms.json` 所列独立服务（如 deputy-relay、openclaw、n8n）及待开通目标 hair/video、北京 PM 未由统一发布器管理，本次不计作已更新；各自需要明确权威源码和发布入口。

## 2026-09-25 168迁移故障已恢复生产

- 用户授权恢复后，经统一deploy.bat专项入口发布 `8bd7759f7df2bcb132438e68ca3f424b6f44162d`；办公室/北京Git版本一致，schema168，9组客户标签完整回填、缺失0。
- 五个登记writer全部running；出库timer恢复原active/enabled；publish-current=succeeded，schema-writers=completed，原始事故证据保留。办公室本地与leshine.work/leshine.cloud健康接口均HTTP200、ok、connected。
- 本地分支 `codex/migration168-collation` 基于原失败284c399b，仅追加SQL修复与恢复入口；已走生产专用deploy引用，现按用户授权合入本地开发main，包含8bd7759f且保留main已有169迁移；未向origin推送，本轮不再次部署。下次常规发布前需同步发布源，保持生产版本可快进。不要通过reset回退线上版本。
- 103项部署定向测试、4项迁移测试、独立审查通过。全部署测试存在3项旧基线失败，约定检查存在13项既有前端问题。证据和边界见[恢复报告](reports/2026-09-25-migration168-collation.md)。

## 2026-09-25 私海客户工作台 PCW（开发阶段记录；现已合并部署）

- 开发阶段工作树 `D:/MyProgram/commission-system-kimi`，分支 `kimi/private-customer-workbench`（当时基于 main `401a2a42`）。按 `docs/requirements/private-customer-workbench-prototype/` 开发规格/API 契约/数据蓝图实现 PCW-01..06 后端与前端；后续已合并并于本日按上方发布记录部署。
- 后端：迁移 `169_pcw_customer_workbench`（父 168——main 已占用 168_customer_media_customer_tags，合并前必须先 rebase 到最新 main 并验证单 head）；19 张新表 + `ark_customer_actions` 扩展 7 列（事项/行动轮次/原期限）；服务 `pcw_workitem/evaluation/overview/profile/conversation/order/monitor/maintenance_service`（事项跨日去重、结果+后续原子、409 版本前置、幂等回执、DNC/失权 404）；路由 `/api/customer-hub` 扩展 30+ 端点；权限种子 `customer_pcw:read/write`、`customer_profile:write`、`customer_campaign:admin`；调度 `pcw_daily_evaluation`（`PCW_EVALUATION_ENABLED` 门控默认关）。
- 前端：今日工作台概览（四指标/扫描/水位）、客户工作区六页签、跟进日历、customerHubContract 扩展、customerWorkspaceController 纯逻辑。
- 验证：后端 PCW 测试 123 项 + 存量 customer 回归 287 项全过；前端 node:test 14 项全过、`npm run build` 通过；`check_conventions` 仅剩 13 项既有 UI 基线债（本任务文件已清零）。独立审查（B1 迁移撞号、B2 幂等败者副作用、H1-H7 权限/死行动/行锁、M1-M7）已修复并回归。
- 待办：AI 增量分析/监控真实抓取/邮件通知默认关闭（`PCW_AI_ANALYSIS_ENABLED`/`PCW_MONITOR_ENABLED`），需灰度与业务签定规则阈值；`projection_okki_order` 未接 `on_order_projected` 钩子（新单覆盖窗口需投影侧一行接线）。

## 2026-09-24 结汇决策助手（Codex，合并推送，未部署）

- 工作树 `D:/MyProgram/commission-system-codex-fx-settlement`，分支 `codex/fx-settlement-advisor`；现有系统登录页内新增「订单管理 → 结汇决策助手」，`fx_settlement:read/write` 分级授权。无迁移、不保存测算输入、不执行交易。
- 中国银行现汇买入公开参考价与当日变化每分钟刷新，FRED H.10 日度历史提供 5/20 观测日趋势；报价与历史分别显示时间戳和过期状态。现需人民币、美元预留与压力预算由确定性计算约束，AI 只能选服务端候选 ID 与证据 ID。模型缺失或不可用回退规则测算。
- 后端定向测试、前端导航/权限测试及构建通过；Chrome 模拟登录态 1440px/390px 计算、AI、变更提示与无横向溢出通过。目标环境数据源连通性、真实 AI 模型与银行成交价仍需发布前验收。完整约定检查有 13 项未改动页面的既有 UI 基线问题，增量检查无问题。
- 另交付 [过去一年星期汇率 HTML 报告](reports/2026-09-24-usd-cny-weekday.html)：247 个 FRED 观测，原始均值周五最高；40 个完整周的同周比较周一偏高，但控制年度下行后差异很小，不作为固定星期交易信号。HTML 在 Chrome 桌面/390px 离线打开，无脚本错误或横向溢出。接口和口径见 [功能说明](requirements/2026-09-24-fx-settlement-advisor.md) 与 [API](api-reference.md)。本次合并推送仅交付代码，未部署；生产启用需管理员分配权限、确认文本模型预设，并走项目发布入口。

## 2026-09-23 预售分批结算与汇总回款（本地开发，外部闭环阻塞）

- 工作树 `D:/MyProgram/commission-system-codex-presale-settlement`，分支 `codex/presale-settlement`。已授权合并推送，本次不部署，未操作共享数据库。预售迁移顺延为166（父164），避开主目录未提交跟单员迁移165；后者集成时需重接已发布迁移链。
- 已实现预售类型、固定主单金额、首款末批抵扣、结算报价与数量限制、同客户同币种汇总回款、共享凭证及原子分配、前后端权限和生命周期保护。独立审查所发现的余额/并发/凭证/历史读取问题已修复并复核。
- **尚未实现完整出库执行闭环**，小满运费承载、GMV分类、超额控制与未知结果回查缺少隔离租户证据。预售开关默认关闭，外发能力固定关闭，不能开配置视为上线。需隔离小满及 MySQL 环境完成适配、实迁移、并发和浏览器联调。
- API 与数据库文档已同步，测试与限制详见 [实现报告](reports/2026-09-23-presale-implementation.md)。不要将规格中的 ready/shipped 状态当成已实现的实际出库链路。

## 2026-09-23 临时战报海报下午时段调整（本地分支，未部署）

- 分支 `codex/battle-posters-1701` 将海报推送保持在北京时间 13:00，并把下午首次发送改为 17:01；失败重试为 17:06/17:16，避开采购节 17:00 任务。页面、配置 API 和运行中心名称同步更新。
- 同日若已有旧版 17:00 投递记录，下午任务沿用原记录，防止发布当天重复发送；既有数据库迁移和历史记录不改。生产生效需发布后端与前端并重启调度实例。
- 隔离 SQLite/mock 定向测试 `66 passed`，前端 `npm run build` 通过，增量约定检查 `[]`；完整约定脚本仍被 9 项未改动页面的既有 UI 基线差异阻断。`git_sweep.py --no-fetch` 已运行，仅为本地快照。独立审查无阻断；17:01 仅错开启动分钟，采购节 17:00 任务若运行超过一分钟仍可能与实际发送交叠。

## 2026-09-23 临时战报海报白金主题（已授权合并推送，未部署）

- 工作树 `D:/MyProgram/commission-system-codex-battle-poster-light`，分支 `codex/battle-poster-light`。底图改为白金/浅香槟金，保留原标题、口号、奔跑人物和公司标志；数据卡片改暖白底、深棕文字、古金数字，红绿进度使用浅轨道和深填充，白色时间刻度增加深色描边。
- 仅调整版本化底图和海报 CSS；排序、金额、完成率、投递逻辑不变。历史图片缓存保持原图，新渲染使用新主题。用户已确认配色并授权合并 main、推送 origin/main；本轮不部署。
- Chrome 离线渲染团队 4 组、个人 22 人示例，覆盖超额、领先、持平、落后、零进度；无金额/卡片横向溢出，0% 填充仍为零。预览与复现脚本交付至主目录 `tmp/battle-poster-light/`，全部为示例数据，不连接生产、不发送群消息。
- `python -m pytest tests/test_battle_posters.py -q`：40 passed；`git diff --check` 通过。完整约定检查仍被 9 项未改动前端文件的既有 UI 基线过期阻断。已执行 `python scripts/git_sweep.py --no-fetch`，结果仅为本地快照。

## 2026-09-22 生产部署源码分叉修复（Codex，合并推送交付）

- 只读核验办公室 `D:/commission-system`：HEAD为已部署的 `5ae1f07b`，origin/main为 `698dd57f`，ahead 1 / behind 8；工作区干净，两项办公室服务运行。源码准备的快进保护正确阻止覆盖本地出库对账修复，本轮失败未进入服务切换。
- 共享生产库版本为 `163_okki_presence_days`；远端未上线战报迁移也从162分出。候选保留已部署163逐字不变，将战报迁移改为 `164_battle_posters` 并以163为父；部署保护保持不变，不reset/stamp/downgrade。
- 工作树 `D:/MyProgram/commission-system-codex-deploy-source-reconcile`，分支 `codex/deploy-source-reconcile`，合并两边提交并保留交接记录。用户已授权合并main并推送origin/main，本轮不部署、不执行生产迁移。
- 业务与迁移81项、部署源码8项、两站迁移预检12项通过；验证从生产163仅执行164、已有快照证据保留。完整约定仍为9项既有UI基线过期，增量0项；详细现场与发布边界见[修复报告](reports/2026-09-22-deployment-source-divergence.md)。

## 2026-09-22 战报海报与跑赢时间（已授权合并推送，未部署）

- 工作树 `D:/commission-system/tmp/commission-system-posters`，分支 `codex/battle-report-posters`，基于本地 main `2b79cd1e`。入口新增「临时战报 → 战报海报」，管理员配置工作日、预览/下载两图、开关定时推送和查看投递记录。
- 已确认红金主题、原奔跑底图、右下角公司 LOGO；放弃团队 LOGO/头像。海报固定资产+服务端浏览器渲染，数据每次读取当前战报。按精确完成率排序，个人连续编号；总览也接入工作日时间刻度及红绿状态。
- 计时默认用户确认的9/22、23、24、28、29、30，16:00累计16.66个百分点，最后100%。每天13:00/17:30两张海报共用一个冻结快照；明确失败仅重试未成功图，不确定结果不自动重发。专用群机器人，无默认群回退，开关默认关闭。
- 战报迁移在生产分叉修复中顺延为164（父163_okki_presence_days），增量加工作日/开关、独立时段投递表；原实施的SQLite实迁移保留旧数据、MySQL离线DDL验证通过。未执行战报生产迁移或真实发送。上线前需经统一部署入口执行迁移，配置专用群、公网图链和Chrome/Chromium+中文字体，再在已发布的全活动战报中启用。
- 后端80项、前端Node8项通过；生产构建通过（既有大包/混合导入警告）；Chrome真实渲染22人、1绿21红的16:00演示通过，桌面/390px管理组件保存/预览/下载验证通过，无JS错误。图片使用之前授权读取的13:32真实数据快照，仅作渲染验证。
- 独立审查修复MySQL REPEATABLE READ权限复核及最后重试中断的历史状态恢复；定向复核通过。没有进行真实MySQL多连接并发或钉钉实际送达测试。
- 完整约定检查仍为main同样复现的9个既有UI基线过期；增量规则0项，diff空白检查通过。本轮整合远端main `b0dd3a55`，保留表格限高和连续排名；整合后80项后端、8项前端、生产构建与迁移163单head再次通过。用户已授权合并推送，不部署。
- [功能与启用说明](requirements/2026-09-22-battle-posters.md)。渲染图片、UI截图与验证脚本合并后保留于主目录`tmp/battle-report-posters/`，仅包含本地验证证据；源码资产不含业务快照和群凭据。

## 2026-09-22 内贸订单编辑删除明细（Codex，合并推送交付）

- 分支 `codex/domestic-item-delete`，工作树 `D:/MyProgram/commission-system-codex-domestic-item-delete`。补齐编辑窗口缺失的「删除明细」入口和已有 DELETE API 接入；确认/防重、成功刷新和未保存表头保留，复用后端报工历史保护与余额差额结算。
- 前端21项、隔离 SQLite 删除及审核24项、生产构建、Chrome桌面/390px交互通过，独立审查无阻断；增量约定0项，完整约定仍被9项既有UI基线过期阻断。扩展旧回归有69项建单/审核等基线失败，具体范围和证据见[修复报告](reports/2026-09-22-domestic-item-delete.md)。
- 用户已授权合并 main 并推送 origin/main，本轮不部署；无迁移、无生产数据操作。浏览器截图和复现脚本保留到主目录 `tmp/domestic-item-delete/`。

## 2026-09-22 出库单 Word 下载加固（Codex，已授权合并推送，未部署）

- 分支 `codex/outbound-word-download`，工作树 `D:/commission-system/tmp/commission-system-word-download`。共享 `downloadBlob` 保留原 Blob MIME，未带类型时采用响应 Content-Type；临时 URL 延迟60秒释放，避免触发下载后立即销毁。60秒仅是浏览器接管宽限期，不表示写盘完成。
- 出库单显式传入 `出库单-{单号或记录ID}.docx` 兜底；UTF-8文件名解析失败时降级到普通文件名或兜底，去除普通文件名引号及Windows非法字符。现有Excel默认文件名和其他调用接口保持可用。
- `node --test frontend/tests/download.test.mjs frontend/tests/shippingPrintDocs.test.mjs` 17项通过；`pnpm run build`通过（执行现有 `vite build` 脚本，保留既有混合导入和大包警告）。Chrome隔离浏览器实测正常中文、缺失响应文件名、损坏编码三种下载均完成，56460字节与已校验Word样本逐字节一致，无页面JS错误；脚本保留于主目录 `tmp/word-download-browser-check.cjs`，不连接生产。
- 共享下载调用方独立审查通过；增量约定检查0项、`git diff --check`通过。完整约定检查仍为9项已有UI行数基线过期，在未修改主目录复现；未调整基线。`git_sweep.py --no-fetch`已运行，仅本地远端快照。
- 不涉及数据库、权限或后端API改动。此次为前端稳健性加固，未证明用户样本残留 `.crdownload` 的具体原因；本轮按用户授权合并 main 并推送 origin/main，不部署。
- 合并前整合远端 `c0b0e80d`，保留双方交接记录；整合后18项下载/打印测试、Chrome三种下载场景、前端构建再次通过。增量约定0项，完整检查仍为上述9项已有UI基线问题。

## 2026-09-22 出库删除对账快照限流修复（Codex，处理中）

- 生产 `okki_outbound_delete_reconcile` 已写入 `lys-acciowork` 持久暂停策略；旧实例于14:39失败结束，14:50重启 `CommissionSystem` 后策略已由新调度器加载，健康检查恢复为 `ok/database=connected`。故障根因是把候选创建时间作为 `time_type=1` 更新时间下界，全历史双扫198页后又逐张补查约5232个镜像缺口。
- 分支 `codex/okki-delete-reconcile`、Codex managed worktree。改为 `time_type=2` 精确创建日双快照；迁移163持久化日期覆盖、逐单列表版本/订单关联、待补查ID和失败状态。每轮8日、全局16次详情补查且单次15秒，逐张提交进度、跨轮续跑；版本变化只重查对应单，当天补查后再次双扫且只做替代单保护。完整覆盖前不登记删除，覆盖后仅处理本轮新鲜历史日期。
- 待完成：扩大回归、独立审查、统一入口生产迁移/发布、确认任务保持暂停后恢复并观察首轮。

## 2026-09-22 临时战报（已授权合并推送，未部署）

- 工作树 `C:/Users/lys-m/.codex/worktrees/commission-system-battle-report/commission-system`，基于 main `b4e5c04d`。入口「订单管理 → 临时战报」。实现任意周期草稿/发布、个人目标、活动组/个人GMV和进度、每日成交矩阵、订单筛选/分页/单笔明细、归档恢复及修改记录。
- 口径采用订单核算日、USD金额、活动成员小组快照；同一订单集合支撑各层汇总。服务端限制参与人/组长/管理员范围，未填目标不算完成率，异常数据不伪零，金额Decimal、目标版本冲突原子回滚。
- 迁移162（父161）新增配置、成员目标和审计3表；用户外键按既有MySQL `INT UNSIGNED`，SQLite实际建表和MySQL离线DDL断言通过；downgrade拒绝删目标和审计。用户已授权合并main并推送；未连接生产库、未生产迁移或部署。
- 受影响后端回归77项通过；无符号外键补充后战报/迁移27项再通过。Node18项通过，覆盖金额精度、UTC+14/洛杉矶/UTC日历、迟到请求、导航和表格；前端生产构建通过（保留既有大包/混合导入警告）。真实Vue+隔离FastAPI+内存SQLite浏览器联调通过9项链路、36次API请求，无页面JS错误；390px布局和弹窗检查通过，截图/脚本/结果在合并后保留于主目录 `tmp/battle-report/`。
- 独立审查及定向复核完成，修复成员替换唯一键释放、配置使旧目标版本失效、只读权限编辑提示、日历跨时区、迟到错误覆盖等问题。没有进行真实MySQL并发锁或正式环境数据质量验收。
- 增量约定检查0项问题，`git diff --check`通过；完整约定检查仍被9个已有UI行数基线过期拦截（主目录同样复现），未改这些页面或放宽基线。`git_sweep.py --no-fetch`已执行，仅本地远端快照。
- [实现与启用说明](requirements/2026-09-22-battle-report.md)。上线需统一入口迁移162、发布前后端并播种权限：业务员read/write，活动配置者admin，组长在名单内指定。归档不冻结上游订单；源同步时间未知时明确提示，首版手动刷新。
- 本轮使用仓库近期一致的作者身份进行命令级提交，不修改全局Git配置。临时联调服务已停止，临时pnpm锁文件已清理。
- 本轮整合远端main `fadd705f`，仅交接文档冲突并保留双方记录；整合后77项后端、18项前端和生产构建再次通过，迁移162单head，增量约定0问题。既有9项UI基线问题仍保留。

## 2026-09-22 普通发布纳入出库脚本（Codex，合并推送交付）

- 分支 `codex/outbound-release-integration`，工作目录 `D:/MyProgram/commission-system-codex-outbound-release-integration`。解决普通生产发布遗漏新加坡出库 creator/poller，应用成功但独立脚本继续运行旧版本的问题。
- 普通 full/cloud-only 发布从同一候选 revision 准备出库制品；暂停并排空在途任务后再切换应用/schema/static，最后替换出库脚本、恢复 timer 原 active/enabled 状态、核验远端文件摘要。出库验证失败不得写整体成功标记；未纳管服务明确列为 not_deployed。
- 本地和远端 journal 绑定唯一 release_id、revision；本地恢复还绑定 scope。其他机器/范围/版本及专项入口不能接管未完成协调发布。重试保留暂停前基线；首次部署须从含修复的受管候选入口启动，操作见 deploy/README.md。
- 相关部署回归 57 项通过；独立审查发现同版本发布事务串用后已加唯一 release_id 并复核通过。最终完整部署测试为 311 passed / 11 skipped / 1 failed；失败为既有 storage_routing 回滚 Mock 耗尽，已在原主目录独立复现。全量约定检查被 9 项既有 UI 基线陈旧问题阻断，本次增量规则检查 0 findings，diff 检查通过。
- 用户已授权合并 main 并推送 origin/main；本轮不部署。无数据库迁移，无生产操作；保留主工作区他人修改。此前本会话已单独修复0955混单并发布现有最新版worker，本条是新增发布机制的后续代码变更，不能混同为已上线。

## 2026-09-21 小满已删除出库单同步（Codex，待发布）

- 分支 `codex/outbound-delete-reconcile`，独立目录 `commission-system-codex-outbound-delete-reconcile`。修复小满详情仍返回旧 `status=1` 时方舟误判删除未完成：两轮完整有效列表均无原 ID 后登记删除回执，异常/分页不完整/列表变化不判删除。
- 新增每15分钟单活 Scheduler 对账，覆盖直接在小满删除及历史待核对回执。保留镜像、验货及审计资料，阻止已删除订单任务自动重新生成。未进入镜像的替代单补读关联；任务版本快照和行锁保护同秒并发更新。
- 隔离 SQLite + 模拟 HTTP 验证158项通过；独立审查发现的替代单镜像延迟与秒精度问题已修复并复审通过。`git diff --check` 和增量约定函数检查通过；完整 `check_conventions.py` 被9项已有前端行数基线失配阻断。Scheduler 测试结束时出现既有后台 job-run 持久化 OperationalError 日志（无生产配置，未连生产）；业务回归均通过。
- 用户已授权合并推送，已拉取并核对远端 main；本次不部署，也不运行生产删除对账。无新迁移。Git 巡检仅作报告，不清理其他任务。规则与运行机制见 [invoice-lifecycle.md](invoice-lifecycle.md#小满出库删除同步2026-09-21)。

## 2026-09-21 生命周期合并远端更新

- 整合 origin/main 3b2ee9c4 的内贸、净额回款和部署修复；未发布的本任务迁移改为161，串接160_domestic_price_review，避免multiple heads。
- 回款远端变更登记适配新净额规则：保留本地分摊费用，按远端净额加本地费用还原含费登记金额；远端非零手续费阻断核实，不能覆盖本地费用。
- 用户授权合并并推送main；本次不部署、不迁移生产。整合回归303项通过，补充净额边界后的定向回归152项通过，Node48项通过，迁移链单head验证通过；独立复审无剩余阻断。完整约定检查仍为已记录的9项UI行数基线问题。

## 2026-09-21 订单／出库／回款生命周期修复（codex/okki-sync-lifecycle）

- 工作目录 `D:/commission-system/tmp/commission-system-sync-lifecycle`，基于 main f49fe630。实现取消冻结、可靠回读后删除/保留原单取消、订单推送持久执行令牌、结果未知保留库存预占、已绑定更新受理恢复、回款远端删改核实、出库漏建和删除结果恢复，以及按订单行核对与人工资料确认。
- 迁移161增加发票取消审计、发送租约和自动出库登记字段；未合并、未推送、未发布，未连接生产执行写入。操作和协调发布说明见 [单据生命周期](invoice-lifecycle.md)。
- 最终受影响 pytest 294 项通过；Node 出库轮询37项和前端行为11项通过；Vite构建通过（既有大包/混合导入警告）。迁移在隔离SQLite验证可重入、旧数据保留；独立复审已确认本轮范围无剩余阻断项。
- 完整约定检查仍失败：8项已有UI行数基线过期，另本次InvoiceManage.vue为502行，生命周期主体已拆独立组件，未为消除2行门禁机械拆分或放宽基线。新增回款表格list-table问题已修复，git diff --check通过。
- 扩展执行 invoiceSyncGuard.test.mjs 时1项旧源码断言失败：测试要求仅saveAndSyncSubmitting，HEAD实际已使用saveAndSyncSubmitting || linkedBusy；与本次生命周期改动无关，未弱化或删除断言。其余目标行为测试通过。未做真实浏览器视觉验收/MySQL并发锁/真实OKKI写操作验收。
- 已执行 git_sweep.py --no-fetch，仅本地快照；本分支修改保留供审阅。上线需统一入口迁移/发布前后端并协调暂停及更新Singapore poller，禁止旧poller与新冻结状态混跑。
## 2026-09-20 订单管理导航调整（已授权合并推送，未发布）

- `codex/order-shipping-navigation`：出库单打印、验货单列表移到订单管理，紧接订单发票管理，排在回款单管理前；回款导航及页签名称统一为「回款单管理」；订单管理分组补充发货检验权限，保证仅有该权限的用户仍能看到入口。
- 菜单实际配置顺序与分组权限核验通过；前端构建成功，8项导航测试通过。约定检查仍为8项既有前端基线失配，Git巡检已执行。

## 2026-09-20 回款小满净额口径调整（已发布并核验）

- 生产办公室与北京版本 `fea48d6c22937f3064a40546292ea4e03927d2b9`，统一deploy入口发布，schema159不变；两域health 200/database connected。
- 小满amount/real_amount按本笔扣费净额，三项bank_charge均0；本地保留含费金额及分摊费用，余额与分期去重已调整。193项相关测试通过，独立审查完成。
- 18张小满原单按原cash_collection_id更新，1张仅规范化本地已净额登记；共19条审计。最终49张关联单全为净额/零手续费且余额0，目标订单52条远端ID集合未增加。4张无关联ID单保留核对（2张已有人工回款，2张没有远端原单），未重复创建。
- 用户已授权合并推送，本次集成到 `main` 并同步 `origin/main`。约定检查仍被8项既有前端基线失配阻断，本次未改这些文件。详见[核对报告](reports/2026-09-20-receipt-net-amount.md)，私有证据在主目录 `backend/tmp/receipt-net-amount/`。

## 2026-09-20 出库列表排序规则冲突（codex/outbound-collation-fix）

## 2026-09-20 内贸订单优化（Codex，待生产发布）

- 分支 `codex/domestic-order-improvements`，独立工作目录 `commission-system-codex-domestic-order-improvements`。
- 会员问题只读核实：客户 550 黑卡调整于 9/17 17:25:15 通过，2,994 元充值于 17:25:36 通过后重核为非会员。用户确认保留规则，只加强充值及审核提示。
- DO20260919-002 商品原价 1198、系统至尊会员价 960，旧规则误进审核；查询时已生产中。本次修复审核判定、金额详情高亮、整单逐件码打印、样单零价及草稿手工费保存。
- 新增迁移 160（默认价快照 + 样单字典）。用户已授权合并推送；未执行生产迁移或数据修复。验证与限制见 `docs/reports/2026-09-20-domestic-order-improvements.md`。


- 已只读复现：`lsordertest.okki_outbound_records` 可访问（4519条）；单数 `okki_outbound_record` 不存在。列表失败来自删除回执 `request_id` 的 `utf8mb4_unicode_ci` 与 `CAST(outbound_invoice_id AS CHAR)` 继承的连接 `utf8mb4_0900_ai_ci` 比较，MySQL报1267，被统一提示为数据库连接失败。
- 修复删除过滤在MySQL上的字符串比较，显式指定 `utf8mb4_unicode_ci`；列表和详情共用，保留字符串精确ID比较，不改表、不改数据、无迁移。
- 隔离SQLite回归54项通过；修复代码对真实库只读验证列表20条/合并总数4521、详情可读、无归属匹配返回0条。未做生产页面验收；用户已授权本次合并 main 并推送 origin，未授权或执行部署。
- 独立审查无发现，删除回执隐藏和归属权限不变。增量约定检查无违规；完整约定检查仍被8项既有前端UI基线过期阻断；Git巡检已执行 `--no-fetch`，仅为本地快照。

## 2026-09-20 方舟删除小满出库单（codex/outbound-delete）

- 出库单页面新增受 `shipping_inspection:delete` 控制的删除按钮与整单确认；按原归属范围校验，远端实时核对客户和待出库状态。
- 小满删除及回读确认后才隐藏本地过期镜像；复用shipping操作事件的唯一键记录持久删除意图与完成回执，无迁移。不写业务镜像、不删除发票及验货媒体；相关自动出库任务暂停防重建，超时只核对不重发。
- 实现与验证在独立 worktree；此次交付范围为合并 main 并推送 origin，生产发布另行执行，未执行真实业务删除测试。上线需后端启动 seed 并分配删除权限。后端相关101项、前端行为4项通过，前端构建通过；独立审查发现的缺任务防重建与同订单双删除持有冲突已修复并复查通过。增量约定无违规，完整检查被8项既有UI基线过期阻断。浏览器连接不可用，未做实点验收；MySQL实锁竞争和外部仓库并发需上线验证，不把SQLite测试当生产锁证明。

## 2026-09-20 发货扫描网页／小程序功能同步（codex/shipping-scan-parity）

- 小程序补齐整单/明细相册照片、自动压缩失败保留重试/放弃、上传进度；选取/压缩/上传/待重试阶段防止新文件覆盖、刷新和提交，过期回调不回填。
- 后端 mini 照片/视频接受可选 request_id，复用现有事件表实现同文件重试去重；无迁移。先部署后端，再单独上传发布微信小程序。
- 验证：小程序 Node 测试 49 通过；后端媒体/检验/工作站 45 通过（隔离 SQLite）；微信官方 WXML/WXSS 编译通过。约定增量无违规；全量 UI 债务门禁仍有 8 个既有基线过期错误。
- 未合并、未推送、未部署，未做微信/iPhone 真机测试。独立审查已通过；修复并发重试时媒体快照旧读，并断言 MySQL 方言重放查询使用 FOR UPDATE。

## 2026-09-20 出库单混单修复（codex/outbound-order-isolation）

- 数据已修复并通过正常 OKKI 同步刷新：旧出库 64703599253896（本地 91258）仅保留订单 19054 的发帘 4 件，客户按旧订单恢复为 heidrunopitz；新出库 105798528011219（本地 91266）为「张笑浅色库存#0925 [25924]」，仅订单 25924 的贴发 20+40=60 件，日期 2026-09-20。
- 根因：09:19 自动创建请求 serial_id 撞到 2025 年旧单；OKKI push 以同名旧单执行追加，旧的创建成功核验只检查存在目标订单行，漏掉其他订单行。
- 修复前快照、创建/拆分请求及响应保存在新加坡 okki-sync 的受限 `logs/repair-outbound-25924-20260920/`。未删除旧业务单。旧单历史备注无事故前快照，未猜测还原；原 09:19 创建日志保留为事故证据。
- 功能修复：全局单号实时查重，冲突用订单 ID 后缀；创建后全量明细核验；已有混单不能按 existing 放行。代码与专项测试在当前独立 worktree；生产功能发布尚未执行。42 项 Node 测试通过；prepare-only 及真实单据只读核验通过。约定检查受 8 项既有前端 UI 基线陈旧问题阻断；Git 巡检为 --no-fetch 本地快照。

## 2026-09-20 COS 封禁被色块部署误判冲突（Codex，本地修复）

分支 `codex/fix-colorwork-storage-routing`，基于 d0accd9f。用户以 ba79159c 固定候选发布，colorwork prepare 报 Conflicting colorwork routing。只读核实北京两个 server 与新加坡一个 server 的受管 STORAGE PUBLIC 块均有 `/api/colorwork/storage/` 精确404封禁；旧检查仅按路径子串判冲突。修复只在检查副本忽略受管块内精确404规则，输出原样保留，未知代理/其它色块路径/缺失标记/未受管规则仍阻断。

19 项色块路由回归及独立审查通过（新增共存用例先红后绿）；真实两站配置读取后本地 render 成功，3 个 storage 块逐字保留且重复渲染幂等，证据 tmp/routing-evidence/live-render.json。组合 storage 套件共62通过/1失败：test_bad_public_route_rolls_back 的 Mock StopIteration 在未修改 main 同样复现，未顺手修改。未改生产 Nginx、未 reload、未部署。生产旧入口需从含修复的受管候选启动，见 deploy/README.md；本地待合并推送。

## 2026-09-20 订单发票客户等级增加 E（Codex）

分支 `codex/invoice-grade-e`，worktree `D:/MyProgram/commission-system-codex-invoice-grade-e`。订单发票录入/编辑客户等级增加 E，后端创建/编辑校验同步放行；沿用客户默认等级记忆和本单快照，不改变价格规则。现有 String(1) 可直接存储，无需数据库迁移。API 与数据库说明同步更新。

验证：先确认 E 新建/编辑回归在旧校验下失败，再修复并通过后端等级测试 22 项（隔离内存 SQLite）、前端等级测试 7 项、主站 npm run build、git diff --check；增量约定检查无违规。完整 check_conventions 受 8 项既有 UI 行数基线过期阻断，未修改无关页面；git_sweep --no-fetch 已运行，仅本地快照。等级迁移旧测试写死 157 为最新 head，已改为检查单 head 且 157 在迁移链中，保留数据与回滚断言。独立 agent 只读审查通过，无待修问题。本轮未做浏览器人工验收。用户已授权合并并推送 origin/main；不包含生产部署。

## 2026-09-20 发货质检支持相册照片（Codex，本地）

在同一 `codex/shipping-video-activation` 分支继续完善上传入口。整单和产品明细新增独立“相册照片”按钮，使用不带 capture 的 image/* 选择器；原“拍照上传”保留 environment 相机入口，选好一张照片后复用原 photos 上传流程。四个入口按两列排列。沿用上传中/视频待处理禁用与已提交只读规则；不新增后端接口。

Chromium 实际组件 + 模拟 API 验证通过：整单 item_id 为空、产品 IT2 归属正确、相同照片重复选择可触发上传、busy 禁用、submitted 隐藏、320px 无横向溢出与页面错误。主站构建通过。证据 `frontend/tmp/video-check/verify-photo-album.mjs`、`photo-album-320.png`、`tmp/photo-album-build.log`。本轮未合并/推送/部署；原视频自动处理修改一并保留。

## 2026-09-20 Safari 原生拍摄返回后自动压缩（Codex，本地待验证）

用户确认此前首次提示“浏览器未允许视频处理”，点击重试即可成功；进一步明确要求“使用视频后直接自动压缩上传”，不接受把第二次点击设成默认流程。分支 `codex/shipping-video-activation`，基于 `4d17eda7`，worktree `D:/MyProgram/commission-system-codex-video-activation`。改为在拍视频/相册按钮原始 click 内同步预激活空 video 与 AudioContext，返回后把同一实例交给压缩器；默认仍自动上传。此方法依据 WebKit play 的 per-element 激活行为，不能用桌面证据保证 iPhone 相机返回必定保留授权。只有实际 NotAllowedError 才显示普通恢复入口；真实解码错误继续报错。保留文件期间禁新拍摄覆盖/直接提交，可确认放弃；取消 picker、清单结束和卸载释放预备资源。

24 项压缩/工作台/安装回归通过；Chromium 390px 实际按钮→文件选择→自动压缩→模拟上传，正确关联 IT2；模拟 NotAllowed 后恢复按钮正常、无红色失败提示、没有横向溢出或页面错误。真实 3 秒视频输出 289603 字节，H264 1280x720 + AAC，音量 mean -21.1dB，声音保留。独立审查通过（发现的视频覆盖与无取消出口已修复并补回归）。前端构建及增量规则通过；完整门禁 8 项既有 UI 行数基线问题。证据 `frontend/tmp/video-check/` 与 `tmp/video-activation-build.log`。本次未合并/推送/部署，仍需 iPhone Safari 原生相机真机复验。

## 2026-09-20 生产 COS 已切换，办公室与云入口已恢复

已执行用户授权的办公室、leshine.cloud/leshine.work生产更新：两后端/办公室前端为4995759814b5a207f1bc2d6752019112cc800481，数据库159。两域主站artifact c517100b03161b8b41b2d78acbd57827e9351e288a96970806e66b83e58f32fe，PM d70da50938277be7ae36b240826c5c9f4226aea8af5dcf3df7229cd02f4897b6；Singapore OKKI poller同步完成。DDL成功后静态收尾故障通过受控finalize完成，未重复DDL，发布/schema日志已关闭。

COS attempt cos-storage-20260920b已完成configure/register/start，21域启用和managed、两机worker启用，Colorwork改用方舟COS存储接口。事务登记30560素材对象、476检验附件，275条本地客户素材provider改为cos。最终联合清单含客户素材308、设计图1728、内贸87、培训15、售后9、AI聊天3、头像1、名片11、Expo2591、节日1210、tag_images1（明确部署探针）、设计附件22、回款凭证64、PM24、Colorwork262、发型96、视频16；knowledge/insight为空。办公室与北京原件和环境备份均保留；R2未完成24个multipart保留。4个历史素材/缩略图缺失按用户明确例外处理，不制造ready记录。

用户先要求跳过素材逐个校验，随后要求直接切换、不要再校验：中止素材全量重哈希，复用既有完整云回读记录并核对size/mtime；其他域当时已完成最终清单。不宣称本轮重新完整校验123GB素材。未再做全量私有接口/真机上传速度回归。手机检验仍按局域网持久接收+同事务队列+后台COS同步；真实手机Wi-Fi吞吐未实测。

公开文件路由cloud/cloud-ip/work/hair/video已由统一入口激活。新加坡TLS链验证深度修为3（不关闭TLS验证）；Nginx reload短暂等待新worker。切换过程中受管启动、事务与路由入口完成必要readiness，不代表所有业务操作都人工复测。两机后端健康；维护规则已全部恢复。办公室0.0.0.0:8001监听，临时ArkStorageMaintenance8001规则不存在；服务器自身访问http://192.168.100.3:8001/、/health及https://lan.leshine.cloud/均200。用户反馈内网打不开时仍处维护窗口，随后已解除。

恢复证据位于各机.deploy_state/storage-cutover/cos-storage-20260920b及storage-maintenance同名目录；最终回执bundle SHA256 26ccec441881fd6f64eca4d746762a815fa681f7b7235ff33072a8fb2ffc8f85。已有新云写入可能发生，不可简单关COS或回滚本地旧读路径。切换登记首次因ORM关联模型漏导入回滚，补齐auth/design后事务成功；北京环境root-owned，切换器使用限定脚本sudo执行。Colorwork启动首次早于监听，按同一marker重入成功。新切换工具在本任务分支交付，保留受限迁移材料与本地工作树以便后续维护。

## 2026-09-20 COS生产发布预检受阻（已授权，尚未切换）

用户已明确授权办公室、leshine.cloud/leshine.work最新代码发布及COS切换，包含158与159及158配套出库轮询器。office-prod已连通；办公室与北京实际HEAD仍799ebb13，服务健康。已将4d17eda7通过Git bundle传入办公室并在受管候选执行deploy.bat --live-root/--revision/--no-pull/--prepare-only；候选COS依赖、pip check、字体、设计文档渲染及路由导入通过。独立DBA认证预检返回MySQL 1045，已确认凭据格式正确、非应用身份；需要管理员修复办公室.deploy_state/credentials/migration.env中的凭据或当前出口来源授权。未停止服务、未执行DDL、未改生产COS开关/业务引用/Nginx，不把此轮记为发布成功。

等待期间补复制并完整SHA回读21个新增文件，共9,994,942字节：办公室domestic 2/festival 7/receipt-proofs 3，北京domestic 3/expo 6。增量manifest和回执独立保存，不改旧证据。素材数据库仍30,564个唯一引用，无新增/删除，已迁移30,560个原文件size/mtime未变，剩余仍为既定4个缺失；素材目录9,357个非清单文件不能当成新增数据库附件。设计生图2个源文件已不在目录，历史COS回读收据保留，不据此删除云对象或业务引用；后续应按活跃DB引用核验。尚未冻结，正式切换仍须再查最终增量与Colorwork活跃R2数据（本轮仅查导出快照）。

精确缺失例外参数已落地cutover.py，默认不豁免；只允许asset当前实际缺失的引用，不制造ready记录，不豁免尺寸/SHA冲突。15项SQLite回归通过。切换协调还须接入统一入口：独立冻结office/BJ/Colorwork、事务登记、保护env备份及启用、再开流量；普通publish会提前重启，不能直接当作COS冻结事务。Colorwork .dev.vars按prepare时配置生成，同一candidate不可在开关修改后直接复用，须受控生成新配置并验证重启。

## 2026-09-20 LighthouseCOS 代码准备合并（生产尚未切换）

2026-09-20 合并推送结果：main与origin/main已核对为4d17eda745efca74fc0675ab50f11eb2a025e724；COS主体提交69be6574，集成修复4d17eda7。323后端/部署测试、5项Node/workerd、合并后73项关键回归通过，主站与Colorwork构建通过。主目录17个不重叠文件原字节保留、7份重叠文档已对账恢复；密钥与业务回执未提交。生产COS开关、DB引用及Nginx未切换，保留本任务工作树及受限恢复材料供后续生产切换。


用户已授权COS迁移代码合并推送，本次不执行存储生产切换。私有桶leshine-ark-1259007308 / ap-beijing / ark/production；公网北京代理到COS，手机检验局域网持久接收并后台同步。完整覆盖与放行条件见[附件验收](requirements/2026-09-19-attachment-cutover-audit.md)。接口、队列、缓存、各附件域和Colorwork已实现，开关默认关闭；迁移159依赖158，只允许统一部署入口检查并执行，不stamp/downgrade。

初始素材30,560文件/123,568,602,783字节已全部上传、北京内网逐字节SHA256回读，最终回执与原manifest严格匹配。设计生图1718、设计附件22、office展会417、采购节1201及先前PM/回款/检验/客户素材/内贸/售后/培训/AI/头像/纪要已回读；北京展会2392、Colorwork262、新加坡hair96/video16已核验。展会2张冲突旧色板单独归档。密钥、清单、原始业务回执仅保留受限.deploy_state和服务器旁路，源文件未删除。

用户已明确接受素材14158和14159各自原件及缩略图共4个缺失作为迁移例外，不再要求找回；切换校验器仍须接入精确例外白名单，不能全局跳过引用覆盖。旧color swatch仍有空PNG占位实现，不计作真实生成功能完成。

仍待生产切换：冻结写入与最终增量、跨实例manifest并集、159队列ready及客户素材provider受控回填、配套配置、5个公网入口激活、办公室/cloud/work登录态读写与真实手机Wi-Fi上传测速。Colorwork24个未完成R2上传需在冻结时重查。5个候选Nginx此前prepare-only通过，未激活；不是线上COS已可用。上次确认生产应用HEAD799ebb13，DB157，发布前必须重新读取现场版本并明确158的发布范围。

内网换址已完成且单独合并推送d64a56db：DNSPod及办公室网关192.168.100.1均将lan.leshine.cloud解析到192.168.100.3，ArkOfficeHttps监听及防火墙同步更新；默认DNS下HTTPS /health、/shipping/scan、/pm/均200，证书校验正常。原配置受限备份保留。PM地址提示代码已改且构建通过，前端本次未发布。SSH alias office-prod经本机2223连接lys-acciowork，映射曾反复失联，重建后恢复。

已做多轮隔离测试与独立审查；本次合并回归323passed/1skipped，主站及Colorwork构建、TypeScript检查通过；5项Node/workerd测试通过，修复新主分支候选色块替换绕过COS适配的问题并经独立复核。完整规则检查仍有UI行数基线问题，不修改baseline隐藏告警。已基于最新main复验，159为单head，增量约定无违规；COS工作树保留恢复材料直至生产切换完成。

## 2026-09-18 保存并同步关联单据（Codex，待部署）

工作树commission-system-codex-invoice-linked-sync，分支codex/invoice-linked-sync。已接入原订单编辑、持久分步结果、失败续跑、旧编辑内容哈希、任务令牌、回款摘要权限与人工核对结束。迁移158；需配套更新Singapore出库poller再启用。出库自动写回因小满未明确服务端并发保护暂不开放，显示实时关联单据和SKU差异；回款财务事实不改写。171项隔离后端测试、41项Node测试、前端构建与本地模拟界面验证通过，独立审查通过。详细边界见[invoice-linked-sync.md](invoice-linked-sync.md)。生产尚未部署；合并与推送以Git记录为准。完整规则门禁仍为7项既有UI基线问题。

## 2026-09-18 手机 Safari 发货质检视频压缩停滞修复（Codex，本地待集成）

分支 `codex/shipping-video-compression`，worktree `D:/MyProgram/commission-system-codex-shipping-video`。用户反馈 iPhone Safari 产品明细拍摄几秒至十几秒视频后停在压缩、无百分比和上传。代码原先先等待 loadeddata 再 play，且 finally await AudioContext.close；回归模拟了不预解码和关闭 Promise 不结束时的阻塞。改为文件选择/重试点击事件内先请求播放，录制前暂停并定位回开头；10 秒无播放进展报错，音频关闭不阻塞退出，提前创建的音轨也独立停止。明细/整单按钮下显示百分比与错误；失败保留拍摄文件，用户可点击“重试压缩并上传”，网络重试仍复用压缩文件与请求幂等键。

验证：18 项压缩/工作台/安装回归通过（新测试先红后绿）；主站构建通过；Chromium 390px 实际组件+模拟 API 验证带声音 3 秒视频压缩、IT2 明细归属、错误就地反馈及点击重试，两次上传均属于 IT2；输出 290693 字节，ffprobe H264 1280x720 + AAC，音量 mean -21.1dB，非静音。独立审查发现早期失败音轨清理遗漏，已修复并补断言。证据在本 worktree `frontend/tmp/video-check/`，构建日志 `tmp/video-build.log`。未向生产上传业务文件、未修改数据库、未合并/推送/部署；iPhone Safari 原生相机、权限与音画仍待真机验收，桌面模拟不代表现场根因已实测确认。

`git diff --check` 与增量约定检查通过；完整约定门禁被 7 个既有页面 UI 行数基线过期阻断，与本次修改无关。`python scripts/git_sweep.py --no-fetch` 已运行，仅本地快照。

## 2026-09-18 回款归属权限收紧（Codex，本地实现）

分支codex/receipt-owner-permissions：普通回款访问仅按订单sales_user_id，取消代录人范围；独立receipt:read_all保持全量数据范围，与receipt:read页面权限搭配。详情、列表、订单选择、余额和已绑定回款凭证统一校验，invoice:read_all不再通过凭证fallback绕过。未绑定的发票凭证保留代录权限。83项回款/凭证/订单隔离测试通过，独立权限审查通过；增量规则无违规，完整门禁仍为7项既有UI基线问题。未部署或修改生产角色授权。

## 2026-09-18 客户素材门户目录删除按钮修复（Codex）

目录删除按钮修复，尚未部署。目录列表的隐式 Grid 列被长名称撑宽，导致删除按钮超出可见区域；改为 `minmax(0, 1fr)` 并固定操作按钮不收缩。浏览器回归已验证长中英文目录名、1440/900/800 窗口、只读状态、取消删除及确认删除后的列表刷新（全部使用模拟接口，未删除真实素材）。 `npm run build`、`git diff --check` 通过；约定检查被其他 7 个既有页面的 UI 行数基线过期阻断。本地 Git 巡检已完成（`--no-fetch`，仅本地快照）。

## 2026-09-18 回款手续费按比例分摊（Codex，本地待发布）

用户确认回款含手续费、实到账不含手续费，并将部分回款规则最终改为按比例分摊。当前 codex/receipt-pagination 本地修改覆盖净额订单预检、自动分摊、手工留空手续费为0、尾款舍入、旧零费用失败auto原单重试补算，以及远端手续费/净到账严格回读。已接受ID及uncertain禁止重发。存在待处理回款时，订单总额/手续费禁止修改，避免分摊基数改变。生产Tessie回款656尚未更改或重试，本轮未发布、未推送。146项相关隔离回归通过（测试重构后尾款用例单独复验通过），前端构建通过，独立审查通过；增量约定无违规，完整检查仍为7项既有UI基线问题。无schema迁移。

## 2026-09-18 回款并发核验与持久增量索引（Codex）

生产办公室/北京已通过统一 deploy.bat 部署 805d0a1b（含 7b2356c7），无 schema 变更；121 项相关测试及独立审查通过。张笑浅色库存0924 原回款654已同步有效，小满ID105794102302050，USD114.68。全库18352条首次核验后持久保存，办公室后续3次GET/2.09秒，北京3次GET/1.78秒；新进程真实订单余额查询仍只用3次列表GET，总7.98秒。异常完整性核验不通过时重建，网络错误不使用缓存放行。北京凭证存储代理必须保留 https://leshine.work，办公室为空。

Tessie-KC-0913 回款656失败原因已只读确认：方舟367.87与小满350.35差17.52附加费，订单同步排除手续费但回款预检按含费总额比较，尚未修改金额或发送。当前 codex/receipt-pagination 未合并推送，保留工作树待授权集成；详见[验证记录](reports/2026-09-18-receipt-pagination-concurrency-fix.md)。

## 2026-09-18 回款生产部署与单笔验证（Codex）

办公室/北京已通过统一入口部署 `aed61c43`，分支 `codex/receipt-production-enable` 基于实际生产 `dab19815`，用户已授权合并 main 并推送 origin，本轮不追加部署。两站回款 API 固定办公室，单张 10MiB、入口 11MiB，历史凭证已归集；最后校验办公室 28/28 份大小及 SHA256 一致，来源备份保留。原凭证缺失的自动生成阻塞已消除。

小满分页同秒边界重复已修复，18,325 条真实完整只读扫描通过。原单 id=1 重试后成功，远端 ID `105794024173578`，回读 `collect_status=1`（有效）。创建接口权限已证实可用。最后 1 张 synced、16 张 pending，发送总开关仍 False，本轮未批量发送其他单。76 项相关回归通过，独立审查无阻断；增量约定通过，完整门禁仍有生产基点 13 项既有 UI 基线问题，no-fetch 巡检已执行。

未完成项：`.cloud` 10MiB 端到端上传仍受北京至新加坡重传/低速影响；办公室及 `.work` 网关 10MiB 传输已到达鉴权。浏览器连接不可用，未做登录态 UI 验收。详见[验证记录](reports/2026-09-18-receipt-production-verification.md)。保留发布备份和主目录 `tmp/receipt-enable/` 证据；合并推送验证后清理本任务 worktree。

## 2026-09-18 库存不足出库单列表预览（Codex，合并推送交付）

- 分支 `codex/outbound-stock-status`，worktree `D:/MyProgram/commission-system-codex-outbound-stock-status`。复用出库任务表提供只读待出库记录，无 schema 或生产数据写入。库存不足显示“部分库存不足”，可查看商品、需求、可用及缺口；待生成、重试和等待镜像期间保留记录，打印/Word 按钮隐藏，`task:` 标识在服务端拒绝打印/下载/验货读取。
- 正式记录与本地记录在 SQL 中统一筛选、计数和分页。本地按发票业务员有效 OKKI 绑定限定范围；正式单据对当前用户可见时才替换预览，覆盖单头先到、明细及订单镜像未到的同步顺序。预览日期显示创建日期，不冒充已出库日期。
- 前端构建和导出调用防护测试通过；CUA 在真实 Vue 列表配隔离数据验证缺货详情、按钮显隐和待同步状态。生产 MySQL 只读查询成功：“宋皓月浅色库存 0917”已存在正式记录 91212，联合查询仅返回一条正式记录。未改变重试策略或操作库存；用户已授权合并 main 并推送 origin，本轮不部署。
- 相关后端 78 项测试通过，另单跑原列表回归通过。独立审查发现并修复“镜像头先到导致预览过早消失”，补测后复查通过。增量约定与 diff 检查通过；完整门禁仍报 7 项既有前端行数基线告警，未改基线。Git 巡检已执行 `--no-fetch`，合并后清理本任务分支与 worktree，隔离页面夹具转存主目录 `tmp/outbound-stock-status-merge/`。

## 2026-09-18 方舟订单出库单本地归属（Codex，合并推送交付）

- 分支 `codex/outbound-local-owner`，worktree `D:/MyProgram/commission-system-codex-outbound-local-owner`。方舟首推成功订单通过出库明细 order_id 精确关联发票业务员有效 OKKI 绑定，可直接通过出库单/打印/验货记录共用归属检查，不等待订单镜像；原镜像范围保留。要求客户一致及成功 create 日志，排除导入更新、失败首推和同客户无关出库单。
- 隔离 SQLite 新回归先复现不可见，覆盖无订单镜像时的可见性、越权拒绝、两种明细关联、镜像追上后的去重及失效/删除绑定。生产数据只读运行新查询：Ivy 能查到出库记录 91189（罗馨瑜浅色库存0936），总数 1，详情归属通过。该订单镜像在 09:00:08 自然追上，现旧规则也可见；无镜像场景的验证来自隔离回归。未调用生产写入或真实打印 API。
- 相关后端测试 63 项通过，独立权限审查通过。增量约定检查无违规；完整约定检查被 7 项既有前端 UI 基线告警阻挡，未改基线。`git diff --check` 通过，Git 巡检已执行 `--no-fetch`（本地快照）。
- 不涉及 schema、前端或数据修复；用户已授权合并 main 并推送 origin，本轮不部署。合并验证后清理本任务分支与 worktree，主目录他人未提交成果保留。

## 2026-09-18 订单发票录入优化（Codex，合并推送交付）

- 分支 `codex/invoice-entry-ux`，worktree `D:/MyProgram/commission-system-codex-invoice-entry-ux`。回款截图上传区支持拖放与聚焦后 Ctrl+V 粘贴，共用原有上传、预览、10MB/5张限制；普通文本粘贴不拦截，只读状态不显示上传入口。共享 ReceiptProofs 的回款管理同步受益。
- 产品明细复制最后一条产品行时显式保留当前客户成交价（含手改价格）与客户规则参考价，并按复制后的数量、单价、折扣重算金额；清空原行 ID，物料计划保持独立。
- 验证：27项目标回归、前端构建、独立审查、增量约定规则和 diff 检查通过。发票全套93项中91通过，2项客户切换/同步的源码断言在未修改主目录也失败；全局约定检查仍有7项无关行数基线告警。Git巡检为 `--no-fetch` 本地快照。未做真实登录页面的浏览器操作验收；用户已授权合并 main 并推送 origin；本轮不部署。

## 2026-09-18 发货检验扫码明细排序（Codex，合并推送交付）

- 分支 `codex/shipping-item-order`，worktree `D:/MyProgram/commission-system-codex-shipping-item-order`。手机网页、小程序扫码及刷新共用 `scan_payload`，现复用出库打印的规格自然升序、尺寸数值升序；同键稳定排序，明细字段及媒体 item_id 关联不变。无需前端或小程序代码变更。
- 两项新增接口回归先复现失败，修复后通过；相关后端测试 38 项通过。另有既有 `test_audit_beijing_midnight_ignores_server_timezone` 失败，在未修改主目录单独运行同样复现，本次未改该时间测试。小程序视图、手机交互、打印模板共 33 项 Node 测试通过；未做真实扫码浏览器/手机验收。
- 独立审查通过：两端入口无遗漏，前端无二次排序，媒体仍按 item_id 关联。增量约定检查无违规，完整约定检查被 7 项已有前端行数基线告警阻挡；`git diff --check` 通过，Git 巡检已执行 `--no-fetch`（本地快照）。用户已授权合并 main 并推送 origin；本轮不部署，交付后清理本任务分支与 worktree。

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

任务分支 `codex/shipping-notice`，基点16fbb879。扫描单据后顶部增加返回主页，复用结束会话/未保存确认；当时成功后重新选人（2026-09-30 调整见页首），已上传媒体保留。钉钉完成通知OA附带id/version主站链接，打开下载含单头、明细、备注、照片的PDF；旧版本/撤回409，缺少明细/照片503，保留现有查看权限。手机未登录及下载401均保留通知地址回跳。复用既有Pillow/pypdf/中文字体配置，无新增依赖、迁移和真实通知发送。

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

## 2026-09-16 验货照片跨域 404 路由修复

现场核验共享库 73 条媒体全部存在办公室 `D:/commission-system/uploads/shipping-inspection`，北京无对应文件。原因是小程序上传办公室，而 cloud 的照片读取原先指向北京本地。在 `codex/shipping-media-owner` 中将整个出库检验模块路由到办公室：cloud 经 TLS 验证转发，保留 Authorization/URI、大小限制和业务权限；办公室既有 mini/photos 规则逐字保留。该专项路由当时已在两站激活并完成 Nginx 校验与 reload，未迁移文件或数据库；真实登录账号的照片 200 验收仍未完成。本轮将其未合并代码纳入 main，路由现状仍须由发布预检核对。

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

验证：41项Node测试、JavaScript语法、页面显示/隐藏动效状态和图片预览回调检查通过；浏览器按WXML/WXSS渲染确认布局。约定检查仍为4项既有主站UI债务；未执行微信真机验收，未改扫码、上传和提交业务逻辑；用户已授权合并并推送 origin/main，未发布。

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

- 独立 HTTPS `/shipping/scan` 全屏页，保持主站登录返回路径。发货质检名单替代示例图，当时每单必须主动选人（2026-09-30 调整见页首）；姓名大字、短金色发光、选择勾选、扫描按钮实名、顶部固定身份卡；320px 窄屏及减少动画模式已检查。当时每单提交或结束后清空选择。
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

## 2026-09-18 发票客户等级与出库单顶部字段（合并推送交付）

- 工作树：`commission-system-codex-invoice-customer-grade`；分支：`codex/invoice-customer-grade`。用户已确认等级保存到方舟客户资料，不写小满 customer_info 镜像。
- 发票客户信息增加 S/A/B/C/D 下拉；保存更新客户默认等级，后续选客户回填、支持修改和清空。旧发票保留等级快照，未修改等级不会覆盖客户后来的变更；回填防串客户、防覆盖手动编辑，读取失败不清除等级。
- 出库打印/Word：客户名称后新增客户等级、订单金额；已同步发票金额优先，否则用精确订单镜像金额；缺关联不显示部分合计，跨币种分别展示。
- 迁移 `157_invoice_customer_grade` 接 `156_receipt_management`，仅改方舟库。用户已授权合并 main 并推送 origin；本轮不部署、不执行生产迁移，上线须通过既有发布入口执行迁移。合并验证后清理本任务临时分支与 worktree。
- 独立审查提出的 NULL 订单关联和未同步草稿金额问题均已修复并补回归测试。浏览器已核对打印版式；`npm run build` 通过；前端 19 项测试通过；后端受影响回归 90 项通过，随后新增迁移和边界验证也通过（客户等级 15 项、出库等级/金额 11 项）。生产出库 invoice bridge 的打印接口与 Word 一致性已通过隔离 SQLite 测试。
- `check_conventions.py` 被既有 UI 基线阻断：AssetLibrary、TagDimensionManage、DesignManage、KnowledgeWorkbench、KnowledgeEditor、ProductionOrderManage、AIManager 共 7 个文件的 lines_over_500 基线过期，本次未修改这些文件。单独调用 `check('HEAD')` 检查增量规则无违规，完整约定命令仍按失败记录；`git diff --check` 通过。Git 巡检为 `--no-fetch` 本地快照。

- 合并前已整合主线 `6b75d267` 的待出库列表改动，隔离后端回归 113 项、前端 20 项及生产构建通过；无代码冲突。完整约定检查仍为上述 7 项既有基线错误，按该主线基点检查本次增量无违规。


## 2026-09-20 发布中断排查（色块健康检查）

- 故障候选 `d021ece8b5fbe261fe95cb6f48ef87def85fedfc`，迁移160已完成，办公室健康；北京仍停在旧代码 `fea48d6c`，后端与色块服务均停止。
- 根因：旧 `remote_backend.activate_locked` 在后端恢复前启动色块；COS readiness 需要北京后端8001，连续503使发布中断。
- 本地修复：北京后端健康后才启动色块；色块失败不再触发已成功后端回滚。原生产恢复日志和备份保留。
- 用户明确授权后，已通过统一入口专项恢复同一候选 d021ece8，未重复DDL；两端后端、色块健康，五个writer恢复原running基线，静态发布完成。publish-current=succeeded、schema-writers=completed；原始日志与备份保留。
- 验证：相关23项测试通过；部署全套290通过/11跳过/1既有失败（storage routing mock耗尽，在main复现）；约定检查仍有8项既有UI基线过期。独立审查通过。


## 2026-09-21 充值调整审核提醒

- 分支 `codex/recharge-review-notify`：新增按审核列表权限统计的pending数量接口，导航标题右上角数字角标及提交/审批/30秒/窗口激活刷新。
- 新充值、调整申请提交后给当前审核角色的有效钉钉绑定用户发送待审核工作通知；不通知不能自审的普通审核申请人，不重复通知幂等重放。复用既有工作通知接口，发送失败不回滚申请，无表结构变更。
- 未执行生产发布或真实钉钉试发。
- 验证：后端17项、前端11项通过，生产构建通过，独立审查通过。浏览器连接不可用，未完成可视化验收；约定门禁仍为8项既有UI基线过期。


## 2026-09-21 小程序逐件报工阻断后查看记录

- `codex/unit-scan-history`：关闭有效逐件码的不能报工/已完成提示后跳转该件的工序扫描记录；新增只读记录页和按签名、内贸小程序权限访问的接口。
- 每件按实际报工、跳过关联查询，保留撤销历史；不使用整条明细的汇总进度替代单件状态。新扫描会废弃旧扫描响应，网络错误保留重试流程。
- 验证：小程序59项、后端记录及权限16项通过；独立审查通过，补测并修复上一件提交迟到响应影响新扫码的问题。约定检查有9项既有UI基线过期；未做微信开发者工具/真机验收，未发布小程序或后端。

## 2026-09-21 逐件码标签完整编号

- `codex/unit-label-number`：打印模板使用接口已有的完整 `unit_code`，标签显示产品明细号与单件流水号（如 A1-01、A2-01），单明细与整单批量打印共用。二维码内容及编号规则不变。
- 验证：相关现有测试4项通过；直接生成多产品标签核验 A1-01、A1-02、A2-01 的完整显示与顺序；前端生产构建通过。约定检查仍有9项既有UI基线问题。未合并推送或发布。
## 2026-09-23 出库单手动同步订单资料（授权合并推送，未发布）

分支 `codex/outbound-invoice-sync`：出库单列表增加「同步订单」及差异预览，更新唯一关联订单的待出库单产品增删、规格、数量、价格和备注。持久化发送状态防重，回读核验后立即提供打印快照；业务镜像只读。权限复用、无迁移。实现与协议边界见 [outbound-invoice-sync.md](outbound-invoice-sync.md)。用户已授权本次提交、合并与推送 origin/main；不执行生产发布。主目录已有其他任务改动，集成时保留它们。

验证：受影响后端回归 148 项、前端 17 项通过，生产构建通过；本地真实 Vue 页面配模拟 API 验证差异预览、确认和刷新。独立审查发现的恢复并发、打印快照与当前读问题已修复并复核通过。约定检查仍被 9 项既有 UI 基线过期阻断，单独增量检查无违规；`git diff --check` 通过，Git 巡检为 `--no-fetch` 本地快照。未执行新功能的生产写入或 MySQL 双连接并发验收。

- 2026-09-23 单笔生产同步确认：小满删除明细仍校验数量、销售单价、产品和 SKU；仅传 ID/remove 会整体拒绝且回读未改变。补齐原行字段后成功回读验证，已同步修复未发布按钮逻辑；18 项专项回归通过。

- 配件范围补充：手工同步读取全部发票明细（含 accessory），新增真实发票构建器的配件新增/替换/删除专项回归及打印分类断言，21 项专项测试与前端构建通过；弹窗明确发制品及配件范围。已提交或已有验货资料的单据仍阻止普通按钮覆盖；单笔维护例外需核对实物、明确撤回授权并保护照片关联。

## 2026-09-23 发票同步后接续出库（Codex，已合并推送，未发布）

发票普通同步与已关联订单的「保存并同步」在小满订单成功后继续出库核对。缺货任务即时刷新目标仓库缺货状态，齐货后才重新排队给原执行端；唯一现有待出库单复用出库同步的审计与回读。已出库、验货中、分批、权限不足或回款核对暂时失败时独立提示，不影响已成功订单和出库接续。保留出库列表的预览按钮用于单独补同步。实现见 [outbound-invoice-sync.md](outbound-invoice-sync.md)。功能提交 `598e0d44` 已合并推送 main/origin/main，合并后受影响后端回归 103 项与前端构建通过；约定检查仍有 9 项既有 UI 基线过期，前端相关 Node 测试 29 项中 2 项既有断言与当前代码不符。未执行生产发布。

## 2026-09-24 手机发货质检快捷导航（Codex，本地开发）

- 分支 `codex/shipping-station-quick-nav`：扫码进入出库单后增加「顶部 / 刷新 / 明细」悬浮按钮。明细数字按当前出库单产品顺序生成，点击后避让吸顶操作人卡片并定位；刷新复用现有会话 API，按产品锚点恢复屏幕位置，保留未提交备注。
- 模拟真实 Vue 页面覆盖 18 项明细、390px 和 320px 手机宽度：第 08 项刷新前后产品顶部约 148px，刷新使单头增高后仍保持原位置；短屏第 18 项顶部约 140px，高于吸顶卡片底部 124px。前端构建及发货质检/滚动测试通过。已获授权合并推送 main，未部署、未使用真实出库单验证。

## 2026-09-27 私海回填与回款同步预检

- 私海客户工作台功能已在主线；补入 `backend/scripts/sync_okki_private_pool.py`，从 OKKI 业务镜像按业务员归属回填客户、订单与归属，可先用 `--dry-run` 查看范围。订单来源沿用经营分析字段口径，明细按完整快照重放；`--create-research-tasks` 只覆盖本次成功回填的客户。未运行生产回填。
- 发票关联订单同步前，回款金额、日期、付款方式缺失时提示编辑订单并补填；在同步意图变更前阻断，历史无需回款的订单仍按原条件跳过。
- 相关后端回归 154 项通过；`check_conventions.py` 仍被 13 项既有前端 UI 基线错误阻断，本次未修改这些文件。未部署、未执行生产数据写入。

## 2026-10-01 客户工作台 v2（Codex，隔离 worktree 本地开发）

- 分支 `codex/customer-workbench-v2`，工作树 `C:/Users/windb/.codex/worktrees/customer-workbench-v2/commission-system`。依据 [开发契约](requirements/customer-workbench-v2-prototype/DEVELOPMENT.md) 与原型，新增统一客户目录、三视图事项、共享四页签作战卡、来源选择、容量账本、结果证据、行动纠正、受控 Agent 委派、基础反馈、全员最小摘要和客户服务入口登记。旧私海客户能力继续提供真实源数据；具体完成证据及限制见 [实施记录](requirements/customer-workbench-v2-prototype/IMPLEMENTATION.md)。
- 迁移 `172_workbench_lifecycle` 父版本为 171；保留旧事项/行动，旧 resolved 结果按未核验处理。来源事实变更、客户归属变化与委派失效均保留审计；不自动发送、下单或修改源模块专业任务。统一分群规则仍是 candidate，正式 tier 输出 unknown；未对生产历史样本回放定版。普通容量默认 22 为候选值。
- 本地隔离 SQLite 与静态 MySQL DDL 验证；未连接共享/生产 MySQL，未执行生产迁移、提交、推送、合并或部署。代码就绪不代表已有真实 Worker 凭证或长期运行：Agent readiness 缺条件时 blocked；外部副作用 ambiguous 缺原运行回执查询适配器，不自动重试。启用需按项目发布入口核对目标环境、单活调度、迁移与来源覆盖，并完成单人真实闭环/业务口径回放。
- 最终本地验证：后端受影响回归 327 项、前端 67 项通过，生产构建及严格约定检查通过；独立复核交期异常/来源/维护专项 31 项通过。隔离浏览器模拟授权和客户 API 验证事项详情与消息选择，1440px/390px 均无横向溢出或页面异常；`git diff --check` 通过，`git_sweep.py --no-fetch` 通过但仅为本地快照。真实 MySQL、DSH Worker、历史业务回放和单人试点未验证，不能据此启用生产。具体边界见实施记录。

## 2026-10-02 客户组合列表 MySQL 500 修复（Codex，待交付）

- 客户组合的 `GET /api/customer-hub/customers?customer_scope=primary&sort=value` 在真实 MySQL 的 `ONLY_FULL_GROUP_BY` 下报 1055：最近互动查询按含相关子查询的逻辑客户表达式分组，MySQL 不认可 SELECT 中的会话 ID。已改为先按 `CustomerMessage.conversation_id` 聚合，再在客户层归并最近时间；原有逻辑归属、信源归属、可见范围与消息方向条件保留。
- 只读事务复现修复前的 1055，修复后同一业务库列表查询返回 20 行；不记录客户数据。新增 SQL 形状与跨会话最近互动回归测试，客户接口/分群/评估相关 28 项通过。生产部署不在本次合并推送范围内；线上页面仍需按发布流程更新后复验。

<!-- 以下为客户下单门户专题日志（续上） -->

## 2026-10-03 订单审计入口增量（未完成整体 P0）

本轮新增 audit_query_service、员工 GET orders/{request_id}/audit、中文 AuditDialog 和订单详情入口；复用当前员工权限及订单范围，审计 JSON 使用字段/类型白名单；账号变更清理弹窗并阻止旧响应回填。主审及独立审查发现遗漏失败审核/发票撤回/通知重试，已改为按订单、Conversion、Outbox 的数据库关系查询，不能用 JSON request_id 授权。

实际验证：test_audit_query.py + test_order_queries.py 20 passed（2.15s，隔离 SQLite）；管理端 Vite 3325 modules 构建通过（15.83s，既有大包/混合导入警告）；严格约定与 diff 检查通过。新增审计专属测试为 9 项，含 7 个白名单参数案例，不等于 9 条端到端路径。

未完成：关联发票/通知审计、HTTP 参数/缓存、当前权限撤销需补本功能直接回归；实际浏览器审计弹窗及手机布局待验收。因此 I01 暂不关闭。I02 联系人、I03 映射差异、I04 图片接入仍未实现。没有执行生产变更、发信、push/merge/部署。

## 2026-10-03 审计验收与映射差异增量

审计：test_audit_query.py 12 passed，补Conversion/Outbox关联正反例、伪造JSON排除、历史授权撤销、HTTP参数和no-store。隔离MySQL run-016 + 真实Chrome员工JWT流程1 passed / 13组检查 / 27.87s，无API拦截；1440/390/320审计弹窗、跨员工404、真实禁用后403及刷新清空通过。截图保留scratch admin-orders/live-audit-run-016，390预览audit-390-review.png已检查；手机表格容器横向滚动，不挤出弹窗。18条警告来自既有jose.utcnow弃用。测试服务已正常结束。I01新增路径有上述证据，不代表全部门户验收。

映射：mapping_service.preview新增与当前不可变发布快照比较的changes/change_counts，按kind+source_key标识、规范化展示名/货号，返回新增修改删除及前后值；MappingDialog显示版本号和双列差异。mapping+audit 25 passed；前端mapping纯逻辑3 passed。版本冲突/标准SKU/历史快照原约束保留。

独立审查发现预览/发布401/403/404后旧映射残留，已修订为clear并阻止迟到回填；该修订后的浏览器回归尚待执行。portalMapping.browser.mjs模拟接口已更新新增契约，但仍须新增并执行版本差异和拒绝后清理断言。I03保持待UI验收；I02获准业务联系人和I04授权商品图片尚未实现。下轮优先完成映射浏览器检查，再继续两项功能，不应将剩余工作仅归为外部配置。

## 2026-10-03 映射浏览器验收与获准联系人实现

映射：frontend/tests/portalMapping.browser.mjs已更新新响应合同及差异/预览404/发布403清理断言；真实Chrome模拟API回归12场景通过，含1440/390/320布局、并发版本冲突、未知发布只读恢复。复用本机3211既有vite preview（PID30916），本轮未停止该既有进程；新构建的差异表通过断言。I03最小版本差异增量已具备浏览器证据。

联系人：SitePolicy.sales_contacts存于既有policy_json，管理员选择员工并明确批准公开名片；只允许active未删除员工获批，不公开ArkUser私有email/phone。仅名片变动不升商业policy_version。新增GET /sales-contact按实时customer principal选当前负责人，session_view同步同一白名单；客户SalesContact弹窗每次打开/刷新读取，失效清理、焦点恢复和安全固定链接。未新增迁移。

验证：test_sales_contact+site_service+auth_service 40 passed / 1.95s（12联系人专属；HTTP使用真实门户会话，但沿用隔离SQLite上游绑定fixture，非生产身份联调）；portalSitePolicy.test.mjs 4 passed。管理端3325模块构建16.11s通过，客户站31模块610ms通过。frontend-portal/tests/contact.browser.mjs使用真实Chrome/构建产物、模拟全部API，6组检查通过（链接/3屏宽/撤批准/换负责人/Esc焦点/会话失效）；contact-390.png已人工视觉检查。客户预览本轮3219进程已停止，无实际邮件或WhatsApp发送。独立审查未发现新增P1/P2。

仍需：管理员名片配置端到端保存与真实归属变动HTTP补充核验；商品图片授权绑定/投影/UI（I04）尚未实现，接下来应优先开发该缺口。外部域名邮件/试点资料及历史完整迁移门禁仍待相应证据，不能据局部通过宣称整个目标完成。门户完整隔离回归最终640 passed、2 skipped、2 warnings / 65.51s；两条warning来自既有external_binding_service的Query.get，跳过为需显式浏览器运行参数的用例，不把跳过算通过。

## 2026-10-03 商品图片授权链路实现（待浏览器验收）

新增image_service与三个管理API/一个客户图片API；使用现有Asset/AssetPermission和storage.transfers，限制全员可预览可下载的latest受管理栅格图。绑定由portal_site:admin+asset:admin共同批准，使用既有64字符image_asset_id存版本/key/元数据/transfer摘要的SHA256引用，无新迁移。客户图片URL仅含商品公开ID和row_version，实时鉴权前后两次核对，存储IO不持DB锁，输出去元数据受限JPEG，禁止缓存/重定向/暴露源key。

独立审查发现P1“asset:write可换版本绕过门户批准”及P2存储异常未封装，已修复并复核：预览给完整批准reference，绑定须一致，后续版本改变fail closed；StorageError/HTTPException映射受控404/503。新增素材换版、预览后换版、存储异常回归。

UI新增ImageBindingDialog及PortalCatalog入口/API，客户ProductImage消费image_url并失败占位。审查发现取消预览previewing残留及迟到辅助403抹掉保存状态，两项代码已修复并独立复核无新增问题；尚须浏览器慢预览/移除/重读及未知保存断线回归。

实际后端验证：test_product_images.py+test_catalog_admin.py+test_catalog.py共57 passed / 4.57s；含18服务案例加1客户HTTP案例、目录回归。图片用隔离SQLite+真实Pillow本地文件，不冒充MySQL锁或真实云存储验收。客户站33模块构建602ms通过；管理端最后竞态修复后3328模块构建15.54s通过；完整门户隔离回归659 passed、2 skipped、2既有Query.get警告 / 65.97s；跳过项未计为通过。I04实现已接入但验收未关闭。管理员名片保存/真实归属变动端到端、图片浏览器及云存储/真实MySQL验证仍需完成。

## 客户门户开发文档交付复核（2026-10-03 16:14）

本轮范围为详细开发文档及对抗性审查，入口 docs/requirements/2026-09-30-customer-order-portal/README.md。8篇规格与64条验收场景完整；独立复核无剩余具体P1/P2契约矛盾，修正README与历史实施记录的状态混淆。F01–F17仍仅为设计层关闭。静态链接/JSON/编号检查、strict约定和diff检查通过；git_sweep --no-fetch完成，仅本地快照。保留已有实现，本轮未补业务测试、不改变上一批次记录的联系人/图片剩余验收和生产门禁，不实施迁移、推送或部署。
## 门户商品图片浏览器验收（2026-10-03）

新增可重复执行脚本 frontend/tests/portalImages.browser.mjs 和 frontend-portal/tests/images.browser.mjs。参数依次为本机预览origin、Playwright模块路径、Chrome可执行文件、JPEG夹具、截图目录。使用Pillow生成80×60纯色JPEG测试夹具；不是正式产品图片。

真实Chrome+已构建UI、全部API模拟：管理端8组检查通过（实际JPEG预览、1440/390/320屏宽、If-Match及批准引用、Blob URL释放、慢预览取消、保存响应丢失后只读恢复且不重发、拒绝预览清理、asset权限按钮）；客户端5组检查通过（同源图片解码、三屏宽无页面溢出、404占位、任意外链不请求、新版本图片恢复）。主审查看390px双端截图。测试早期定位器误把SVG算图片、尝试直接点击Element Plus隐藏input，均改成具名图片和可见checkbox标签后通过；没有据此修改产品行为。

证据位于本任务visualizations/admin-orders/image-admin-*.png与image-customer-*.png。此次补齐浏览器模拟接口证据，不证明真实MySQL图片授权、云存储、真实客户归属或生产发布；I04仍需相应验收，联系人管理端保存/真实归属变化验证亦待完成。未迁移、发信、推送或部署。
上述图片验收补充纠正：首次客户截图人工检查发现product-art缺少定位容器，绝对定位图片覆盖整页；原无溢出断言不足。因此修改app.css为卡片position:relative并提升图片标签层级，新增逐屏图片边界完全位于卡片内且小于视口高度断言。客户站33模块构建583ms通过，客户浏览器5组场景加卡片边界断言再次通过，重新生成并查看390px截图。以此次修复后结果为准，前段“没有修改产品行为”仅描述此前测试定位器调整，不适用于本项布局修复。
## 图片及联系人真实MySQL补验（2026-10-03）

新增tests/portal_mysql/test_mysql_images.py：隔离MySQL8.0.46运行018，7 passed in 21.98s。真实portal172/173迁移、当前RBAC/客户会话/归属；素材为typed upstream薄表和本地生成PNG。验证批准与JPEG返回、陈旧批准引用拒绝；存储IO期间独立连接提交素材预览撤权、素材指纹变化、目录grant撤销或真实账号禁用，发送前均拒绝；后台预览期间下载撤权/指纹变化亦拒绝。断言两个同时检出连接ID不同、IO时读取事务已释放。未模拟auth/权限判断，不证明云存储或全历史schema链。

首次017因pytest默认临时目录权限拒绝产生7 setup errors，未通过业务断言；改用确认不存在的D:/commission-system/tmp/portal-images-pytest-018后通过，不弱化测试。017/018日志均确认Shutdown complete。

新增tests/portal_mysql/test_mysql_contact.py：隔离019，3 passed in 21.00s。真实MySQL+ASGI HTTP+真实门户会话及实时归属校验，站点服务批准联系人后，客户端指定他人员工ID不能改变投影；另一连接在授权屏障下修改真实CustomerAssignment.user_id、停用ArkUser或通过站点服务撤销公开批准，下一HTTP响应不再包含原联系方式；前两者ASSIGNMENT_CHANGED，撤批返回null。只变名片不改变商业policy_version。该证据覆盖旧联系人不泄露，尚未覆盖完整交接/重新启用/重新登录后新联系人展示，也未完成管理端真实浏览器保存。

运行命令均为python -B -m pytest选定test_mysql文件 --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，加显式mysqld与全新workspace；图片补--basetemp新目录。未使用生产env、未迁移生产、未发信/推送/部署。总体目标继续，图片云存储、联系人管理端及完整转交联调、需求逐项验收和发布门禁仍需完成。
## 联系人管理端真实浏览器保存（2026-10-03）

新增backend/tests/portal_mysql/test_mysql_contact_browser.py及frontend/tests/portalLiveContacts.browser.mjs，隔离MySQL021真实员工登录/JWT、真实API、构建后的中文管理端、真实数据库；无API拦截。1 passed in 25.92s，内部7组检查：登录、选择业务员、批准名片保存、刷新持久回显、1440/390/320宽度、撤销批准再读取、商业policy_version不变。数据库断言现有报价仍valid，批准/撤销恰好两条site_updated审计。主审查看390px名片截图，无页面溢出。7条jose库utcnow弃用警告属依赖现状。

020首轮未通过：脚本点击Element Plus内部combobox被placeholder覆盖；改为可见select容器后用全新021重跑通过，未使用force点击或更改产品权限。021日志确认Shutdown complete。截图交付副本visualizations/admin-orders/live-contacts-390.png；原始三屏宽证据在D:/commission-system/tmp/portal-contact-browser-021。

本项补齐联系人后台真实保存证据。完整客户转交/重新启用/重新登录后新名片链路、图片云存储及全需求验收仍未完成；本轮未迁移生产、发信、提交、推送或部署。
## 完整客户转交与名片重新登录验收（2026-10-03）

扩展backend/tests/portal_mysql/test_mysql_contact.py：真实上游CustomerAssignment结束旧归属并建立已生效新归属；真实binding_review_service给出复核指纹；ownership_service执行交接后授权suspended且旧PortalSession撤销；admin_service明确重新启用；旧Cookie仍401。随后通过真实HTTP bootstrap/challenges(202)/verify取得新Cookie，登录投影与sales-contact仅含新负责人获准名片，传入旧user_id也不改变结果。鉴权/身份/归属/API均未mock。测试仅将auth时钟推进61秒越过合法OTP重发窗口，并从隔离库加密outbox提取验证码，未发送真实邮件。

024全联系人模块4 passed in 21.00s。随后把测试旧归属状态从非规范inactive改为模型正式ended，025最终定向1 passed, 3 deselected in 21.04s。022首轮因即时生效时间精度边界未选到新归属；改为一分钟前已生效夹具。023曾错误期待challenge200，按实际202契约修正。上述失败均不算通过；最终测试未绕过复核指纹、撤销或OTP校验。

联系人配置/撤权及完整交接后新名片链路已有真实MySQL与HTTP证据，后台配置另有021真实Chrome保存证据。此项不证明完整历史订单归属/PI交接全部场景或生产邮件。独立P0功能覆盖复核仍在进行；整体实现未完成，未生产迁移/发信/推送/部署。
## I05只读客户预览实现（2026-10-03）

实现独立POST customers/{access_id}/preview、portal_mapping:read动态路由CustomerPreview.vue、客户详情入口；复用当前归属scope及已发布current_projection，仅展示客户名称/颜色/货号/规格，无客户Cookie、下单或PI下载。读取/身份/路由切换清理、分页20行及Preview标识齐备。独立复核无新增P1/P2，符合所发现最小契约。

tests/portal/test_customer_preview.py及mapping_service回归15 passed in1.28s（SQLite，员工principal夹具；HTTP仅员工认证依赖替换）。首轮错误下架枚举withdrawn触发约束，按正式disabled修正后通过。frontend build3330模块15.99s通过，原有大chunk/混合auth导入警告。portalCustomerPreview.browser.mjs真实Chrome模拟API6组通过：仅mapping:read无access:read/write可进、已发布数据、分页、1440/390/320、不签发客户Cookie/无写入口、范围拒绝清数据；主审查看390截图。真实JWT/MySQL只读预览仍待验证。

独立审查另发现I06购物车下架行无法定位/移除恢复，已记录07，下一实现项。整体目标继续；本轮无生产迁移、发信、推送或部署。
## I06购物车撤下行恢复完成及共享回归（2026-10-03）

quote_service.build_lines对请求与当前授权published集合取差，仅回显提交过的公开item_id和ITEM_UNAVAILABLE；不存在/未授权/下架统一404，不返回内部字段。checkout按本次请求集合过滤issues，保留有效行、地址、PO和备注，代次隔离迟到失败；不可用行提示/禁数量/可移除，移除后重新核价。成功quote清标记，不复用旧quote。独立风险复核未发现新增P1/P2。

验证：报价相关22 passed 2.80s；新增HTTP后专项4 passed 1.11s；前端状态12 passed；客户站33模块构建574ms；真实Chrome模拟API6组（两行、单行失效、禁数量、三屏宽、移除保留地址PO、重新核价）通过，查看390截图。browser脚本首轮错把Selection链接当button，修正定位器后通过。一次从根目录运行pytest导入失败，改正确backend目录后通过。测试脚本frontend-portal/tests/unavailable.browser.mjs、backend/tests/portal/test_cart_unavailable.py，截图本任务visualizations/admin-orders/unavailable-*.png。

由于build_lines供提案/复购共享，完整门户后端隔离回归665 passed, 2 skipped, 2既有Query.get警告 in67.22s；两项浏览器opt-in跳过不算通过。无MySQL/生产连接。主站本次未改；客户站构建和strict约定/diff检查通过。文档03/05/07已同步。I05真实JWT/MySQL只读预览补验、图片云存储验证及全需求/发布门禁继续；整体目标不标完成。未生产迁移、发信、push或部署。
## I05真实JWT/MySQL及受管理图片路径验证（2026-10-03）

新增backend/tests/portal_mysql/test_mysql_customer_preview.py，运行隔离027：1 passed in22.26s，5条既有jose utcnow弃用警告。真实登录签发JWT、实际RBAC仅portal_mapping:read（没有portal_access:read或mapping:write）、真实MySQL和ASGI HTTP：自己的客户已发布映射预览200，其他员工同权限访问404，草稿写预览403；授权屏障下撤销角色权限后旧JWT预览403。成功预览和拒绝操作不增加MappingRevision/Quote/AuditEvent/OutboxEvent/PortalSession记录，不设置Cookie，响应no-store。结合上一批真实Chrome模拟API验证，补足I05后端真实身份范围验证；不当作完整生产联调。

新增backend/tests/portal/test_managed_images.py，使用实际StorageTransfer snapshot/materialize/摘要核验，仅cached_path云下载替换为本地PNG。覆盖异地ready对象JPEG返回、pending503、deleted404、缺记录且非原件主机503、损坏缓存503、批准后digest变化404；存储IO断言无数据库事务。与原图片测试共25 passed in3.07s。是受管理存储契约证据，不是实际COS桶/网络/凭据/生产缓存验证，真实存储门禁仍需环境。

本轮仅新增测试与证据，无业务行为变更；真实MySQL连接守卫限定027测试库，未读取生产env或发送邮件。下一步按原需求与64条验收规格逐项核对覆盖及剩余缺口，不以这些局部成功推断全P0完成。未push/部署。

## 开发文档及64项验收证据审查收口（2026-10-03）

本轮按用户明确请求交付详细开发文档及对抗审查，只改文档。两名独立审查者分别核对T01–T24及T25–T47/T55–T64，主审核对T48–T54。按整条规格，13条具有既有覆盖证据、51条部分覆盖；部分覆盖不等于已证实代码缺陷，本轮没有重跑业务测试。详细反例、最小补验及发布门禁记录在07末节。README修正过时的联系人/图片/I05待验证描述，实施增量统一追溯本文件。设计F01–F17仍为文档层关闭，不能据此声称全部实现完成。

下一实现验证优先级：OTP/邀请/映射真实MySQL竞争，金额边界，接受/取消/审批及全部撤权入口竞争，PI编辑/下载和worker故障恢复；大部分可在隔离环境继续。完整迁移链、真实邮件/COS、域名及经营配置仍单列发布门禁。未提交、推送或部署。

本轮实际静态验证：8篇文档、23处链接/锚点、3个JSON示例、64条验收规格、17项设计发现通过；check_conventions.py --strict与git diff --check均exit 0。17:18北京时间git_sweep.py --no-fetch完成，仅本地快照。未运行本轮业务测试。


## T17映射真实MySQL竞争验收（2026-10-03）

新增backend/tests/portal_mysql/test_mysql_mapping_race.py，真实两个不同员工（均super_admin）、独立MySQL连接、同base_version/row_version、不同客户别名发布。复用compete，在首事务未结束时通过performance_schema.data_lock_waits确认第二连接真实阻塞。提交分支第二发布409；回滚分支第二发布成功。最终仅一MappingRevision和mapping_published审计，版本仅增1，作者/客户投影为胜出内容，旧报价失效。真实业务服务/RBAC/行锁；没有JWT/HTTP，不扩展为普通业务员范围验收。

从backend运行python -B -m pytest tests/portal_mysql/test_mysql_mapping_race.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-028 --basetemp=D:/commission-system/tmp/portal-mapping-race-028：2 passed in21.38s。mysql.log已确认Shutdown complete。独立审查未发现P1/P2或明显假阳性，认可T17覆盖。strict与diff检查通过。

由上一证据审查快照13项完整/51项部分推进为14项完整/50项部分（仅T17变化）。没有业务代码修改，不需要无关前端构建。下一步T02/T05 OTP和邀请真实MySQL竞争；整体实现目标继续，发布门禁未关闭。未读取生产env、发信、推送或部署。

## T02验证码真实MySQL事务竞争（2026-10-03）

新增backend/tests/portal_mysql/test_mysql_otp_race.py，真实require_preauth/verify、独立MySQL连接、performance_schema锁等待，覆盖同码提交/回滚、并发错码累计、5次耗尽及过期码。新challenge在测试时钟推进61秒后发起，遵守重发窗口；验证码只从隔离加密outbox解密，未发信。None结果按HTTP路由语义提交，避免错误计数回滚。

运行python -B -m pytest tests/portal_mysql/test_mysql_otp_race.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-029 --basetemp=D:/commission-system/tmp/portal-otp-race-029：4 passed in22.52s。mysql.log确认Shutdown complete。strict与diff检查通过，独立审查无P1/P2或假阳性。

证据边界：本次是同一进程线程中的独立数据库事务，不是T02原文的两个进程；已消费凭据由require_preauth拒绝，未直接触发challenge.consumed分支。故T02仍为partial，不能把事务竞争通过写成跨进程HTTP通过，总体仍14项完整/50项部分。下一步补跨进程验证及T05邀请链路；未改业务代码，未生产连接/推送/部署。

## T02跨进程OTP验收完成（2026-10-03）

新增otp_process_worker.py/test_mysql_otp_process.py：multiprocessing spawn两个独立Python进程，显式断言两子进程与父进程PID不同、MySQL连接ID不同，以performance_schema确认第二连接实际锁等待。子进程在调用服务前安装PyMySQL/SQLAlchemy连接白名单，仅允许父测试拥有的回环端口/数据库/随机凭据，检查无backend/.env；凭据通过IPC传递不写日志。真实auth.require_preauth/verify与真实MySQL，四分支：正确码提交仅一个session/成功审计；首事务回滚后另一进程成功；两次错码attempts=2；过期码不消费不建session。进程有有界等待和本任务子进程清理。

隔离030运行：python -B -m pytest tests/portal_mysql/test_mysql_otp_process.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-030 --basetemp=D:/commission-system/tmp/portal-otp-process-030；4 passed in34.75s。mysql.log确认Shutdown complete。strict、diff通过。独立审查无P1/P2及假阳性，认可结合029的耗尽/已消费重放测试覆盖T02原文；已消费凭据在preauth层拒绝是正确整体边界，不要求绕过已失效preauth。

T02由partial改为有完整规格证据，当前15项完整/49项部分。证据限隔离真实MySQL与跨进程服务事务，不宣称跨进程HTTP/浏览器或生产联调。整体实现目标仍未完成，下一项T05邀请GET/邮箱绑定/过期及并发消费。未修改业务逻辑、读取生产env、发送邮件、推送或部署。

## T05邀请激活与页面GET验收（2026-10-03）

新增tests/portal_mysql/test_mysql_invitation_race.py：真实admin.invite创建两有效邀请，A令牌不能激活B邮箱且不发OTP；有效OTP签发后邀请过期，独立MySQL连接并发verify均失败；未过期竞争仅一成功会话/成功审计，账号、成员、邀请消费状态一致。隔离031运行3 passed in21.44s。

新增tests/portal_mysql/test_mysql_invitation_landing.py及frontend-portal/tests/invitationLanding.browser.mjs：本地真实服务器提供已有客户站dist和真实API，Chrome无API拦截；fragment/query两种邀请链接均显示YOUR INVITATION并清除地址栏令牌，无自动API请求、无session Cookie；前后Challenge/Session/Outbox/Audit计数不变，邀请未消费，账号/成员仍invited。服务关闭access log，令牌仅stdin传浏览器，失败不输出可能含令牌的浏览器日志。隔离032运行1 passed in23.13s。

命令为backend目录python -B -m pytest对应test_mysql_invitation文件 --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，显式mysqld、全新portal-mysql-run-031/032及对应basetemp；032额外指定Node、Playwright模块及Chrome路径。031/032 mysql.log均确认Shutdown complete。strict/diff通过，独立审查无P1/P2或假阳性，认可T05完整规格。当前16项完整/48项部分。证据不含真实邮件投递、生产代理或生产联调。

本轮只新增验收代码与记录，业务实现无需修复；没有读取生产env、发信、推送或部署。下一步交易核心：T32双会员接受、T34取消/审批竞争，再补T55全部上游撤权入口竞争。整体目标继续，发布门禁保留。

## T32/T34订单决策真实MySQL竞争验收（2026-10-03）

新增backend/tests/portal_mysql/test_mysql_order_decision_races.py。T32第二采购会员经真实邀请及OTP激活取得独立会话，两个会员在独立MySQL连接接受同一提案并交换谁先提交；performance_schema确认锁等待。最终只一接受回执/事件，Revision、CommandReceipt及AuditEvent的actor和接受时间属于先提交者，没有PI副作用。

T34真实取消与真实invoice审批分别先提交，等待者409 VERSION_CONFLICT；最终仅cancelled无PI，或invoice_created且唯一Invoice/Conversion/ReceiptIntent/Publication。取消后旧/新If-Match同reason均回原回执，异reason均IDEMPOTENCY_CONFLICT；审计/outbox不重复；撤can_order后旧回放403。服务行为无mock，外部库存使用现有隔离测试源，不访问生产。

运行python -B -m pytest tests/portal_mysql/test_mysql_order_decision_races.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-033 --basetemp=D:/commission-system/tmp/portal-order-races-033：4 passed in22.41s。mysql.log确认Shutdown complete，strict/diff通过。独立审查无P1/P2或假阳性，认可T32/T34规格。当前18项完整/46项部分；证据仅隔离MySQL服务层，不宣称HTTP竞争、全历史迁移或生产库存通过。

下一步T37两个获准业务员竞争审批及T55其他上游撤权入口竞争。本轮没有业务逻辑修改、生产写入、发信、推送或部署，整体实现继续。

## T37双业务员审批与T55代办撤权竞争（2026-10-03）

新增tests/portal_mysql/test_mysql_delegate_races.py。第二员工为真实active用户与sales角色，通过invoice.delegation_service.replace_grants授予负责人代办范围。T37交换负责人/代办先提交，真实审批服务及InnoDB锁等待，第二请求幂等回放；唯一Invoice/Conversion/ReceiptIntent/Publication，sales_user_id仍原负责人，created_by/首actor/Conversion及审计属于先提交者。

T55新增代办子场景，真实replace_grants清空授权与approve两提交顺序：撤销先提交则404且无PI，审批先提交则唯一PI保留；撤销后原审批回执也404。没有替换can_act_for或员工授权判断；本测试不覆盖管理HTTP入口认证，T55其他角色/权限/归属/外部身份竞争仍待补。

隔离034运行python -B -m pytest tests/portal_mysql/test_mysql_delegate_races.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-034 --basetemp=D:/commission-system/tmp/portal-delegate-races-034：4 passed in22.31s。mysql.log确认Shutdown complete；strict/diff通过。独立审查无P1/P2或假阳性，T37有完整规格证据，T55仍partial。当前19项完整/45项部分。

仅新增验证代码及证据，本轮未修改业务逻辑、读生产env、发信、推送或部署。下一步T55真实角色/权限撤销及归属/外部身份入口竞争；整体实现目标继续。

## T55角色及权限撤销真实竞争（2026-10-03）

新增tests/portal_mysql/test_mysql_rbac_races.py：独立case角色复制有效权限，不修改共享sales角色；真实admin_router.update_user移除角色、update_role移除portal_order:write或invoice:write，各两提交顺序。撤权先分支预持真实authority屏障，观察另一连接InnoDB等待，再由真实router修改并提交；审批先分支让router直接竞争。没有替换实时操作人/审批授权逻辑。

撤权先提交审批403且无PI/Conversion/成功审计；审批先提交保留唯一PI及相关记录，撤权后旧成功回执也403。断言权限真正移除，权限变更ArkPermissionAudit恰一条、removed_codes及操作人正确。审计表仅按真实ORM在隔离库补建，非完整迁移证明。

隔离035运行python -B -m pytest tests/portal_mysql/test_mysql_rbac_races.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-035 --basetemp=D:/commission-system/tmp/portal-rbac-races-035：6 passed in22.32s。mysql.log确认Shutdown complete，strict/diff通过。独立审查无P1/P2或假阳性。证据为直接真实管理入口函数+MySQL竞争，不扩为HTTP依赖或JWT联调。

T55仍partial，剩余归属/外部身份变更竞争；总数保持19项完整/45项部分。未修改业务逻辑、读取生产env、发送邮件、推送或部署。整体实现继续。

## T55客户负责人转交真实竞争（2026-10-03）

新增tests/portal_mysql/test_mysql_assignment_races.py，真实workflow.transfer_primary_owner及append_customer_event，不替换事件函数；薄上游CustomerAction/Opportunity/Event表仅隔离夹具，保留列默认值，非完整上游迁移证明。两顺序核验实际锁等待、旧assignment ended/唯一新负责人、门户review_required且auth_version增1、原门户绑定保留、旧session撤销；审批先提交保留唯一PI及原sales_user_id/servicing_user_id，转交先则无PI/Conversion/成功建票审计。两条真实assignment.changed事件记录管理员操作者，后续原审批不能重放。

036首次2 failed：客户薄夹具profile_input_seq为None，真实事件写入int(None)失败，未通过业务断言。仅在测试setup明确设0，未更改生产业务逻辑。全新037重跑python -B -m pytest tests/portal_mysql/test_mysql_assignment_races.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-037 --basetemp=D:/commission-system/tmp/portal-assignment-races-037：2 passed in21.48s。036/037均Shutdown complete，strict/diff通过。独立审查无P1/P2或明显假阳性。

T55归属子场景通过，仍缺外部身份变更竞争；当前保持19项完整/45项部分。不扩展为机会/行动转交、HTTP鉴权或所有历史快照字段验收。本轮未读生产env、发信、推送或部署，整体目标继续。

## T55外部身份冲突真实竞争（2026-10-03）

新增tests/portal_mysql/test_mysql_identity_races.py：真实identity_service.confirm_identity及默认ResolutionKeyArbiter，不注入仲裁结果；隔离上游resolution薄表保留唯一resolution_key。构造两个公司同一strong one_to_one身份冲突，真实确认与approve在独立MySQL连接竞争，确认先则IDENTITY_REVIEW_REQUIRED且无PI，审批先则唯一PI保持原归属。两种顺序都验证两公司/身份disputed、profile_input_seq各增1、仲裁conflict、门户review_required和auth_version增1、旧session撤销及旧审批回执拒绝。

隔离038命令python -B -m pytest tests/portal_mysql/test_mysql_identity_races.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-038 --basetemp=D:/commission-system/tmp/portal-identity-races-038：2 passed in22.28s。mysql.log确认Shutdown complete，strict/diff通过。证据是身份冲突确认入口与审批的真实事务竞争，不能自行泛化为所有身份改绑、合并拆分入口均已并发验收。

本轮只新增测试，无业务行为变更；没有生产连接、发信、推送或部署。T55整条关闭仍待核对“全部上游入口”证据，暂保持19项完整/45项部分。

### T55身份入口屏障证据补强（同轮）

独立审查038无P1/P2/假阳性，但指出attach_identity_candidate和resolve_business_context不能仅凭源码推断首查询取锁。已新增真实MySQL after_cursor_execute探针：执行真实入口并在第一SQL执行后抛哨兵，断言只有一条SQL且为authority表SELECT FOR UPDATE，随后rollback；不替换lock_authority。039先2探针+2竞争，4 passed in22.38s。

全app调用点检索将resolve_business_context外层对应到projection_okki.project_okki_customer/project_okki_contact、projection_alibaba.project_alibaba_inquiry、sales_automation.ingest_candidates，四个也加入同一首SQL探针。040最终运行test_mysql_identity_races.py（同038命令结构，全新run-040及basetemp）：8 passed in22.35s。039/040均Shutdown complete，strict/diff通过。6个首SQL探针只证明取锁先于业务查询，不冒充同步/获客全业务验收；2个真实身份确认竞争仍保留。

定向独立复核确认六个真实首SQL探针有效，无假阳性；结合员工、角色、权限、代办、归属、外部身份六类提交顺序竞争，T55在当前入口清单及隔离MySQL范围可标完整。当前20项完整/44项部分。此结论不扩大为同步/合并拆分全业务或生产环境验收；下一步补PI编辑与发布/下载竞争（T43/T62）。

## T43真实PI渲染与编辑竞争（2026-10-03）

新增tests/portal_mysql/test_mysql_pi_download_race.py：实际pi_service.download、ReportLab渲染及pypdf解析；隔离测试字体Vera，非正式中文字体验收。下载线程render明确无db事务，Event暂停渲染时独立物理连接编辑Invoice.remark，经真实ORM版本/撤发布钩子。编辑提交则最终capture拒409且不新增成功下载审计；编辑回滚则旧PDF/版本/发布保持；下载先返回后编辑，已交付旧PDF合法，后续capture拒绝。预持独立edit_connection并明确断言不同CONNECTION_ID。

041首次3 failed：下载释放连接后池将同一物理连接复用给编辑，触发独立连接断言；未弱化断言，改为下载前预持编辑连接。全新042：python -B -m pytest tests/portal_mysql/test_mysql_pi_download_race.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-042 --basetemp=D:/commission-system/tmp/portal-pi-download-042，3 passed in23.27s。042 Shutdown complete，strict/diff通过，独立审查无P1/P2或假阳性。

T43在隔离MySQL服务层及真实PDF范围完整，当前21项完整/43项部分；T62各共享编辑/关联/脚本入口及旧hash协议仍partial，不以ORM单路径替代。下一步T62入口核对/竞争。业务代码未改，未读生产env、发信、推送或部署，整体目标继续。

## T62现有发票编辑入口真实竞争（2026-10-03）

新增tests/portal_mysql/test_mysql_invoice_edit_race.py：真实invoice.service.get_invoice(for_update=True)/update_invoice与pi_service.capture，在两条独立MySQL连接按两个提交顺序竞争并观察实际锁等待。编辑先提交拒绝旧PI读取409；读取先成功后编辑递增portal_document_version并撤回Publication。完整编辑请求保留门户来源，semifinished_plan按前端格式归一化为空列表。Receipt、InvoiceAllocation、ShippingOperationEvent、OkkiOutboundTask采用真实模型列的隔离薄表，未替换生命周期或回款守卫，不构成完整上游迁移证据。

043失败为请求构造null列表问题；044失败为隔离库缺少shipping事件依赖表，均未达到业务竞争断言。补齐夹具后045：2 passed in22.30s，MySQL正常关闭。独立审查指出下载审计断言整库计数会受其他订单影响，已限定object_public_id为当前request。随后046将test_mysql_pi_download_race.py与test_mysql_invoice_edit_race.py同批运行，先产生其他订单合法下载：5 passed in23.36s。命令使用pytest --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，全新portal-mysql-run-046与portal-edit-race-046，指定本地mysqld8.0.46。

严格约定检查和diff检查通过；18:29本地git_sweep --no-fetch通过，不代表远端实时状态。T62仍部分：普通编辑入口已有真实服务竞争证据，其余关联/脚本写入口和旧hash协议尚需验证。总体保持21条完整/43条部分，目标继续；未更改业务逻辑、连接生产、发信、推送或部署。
### T62关联保存及旧hash协议（2026-10-03）

扩充test_mysql_invoice_edit_race.py为normal/linked两个真实入口，各自与capture双提交顺序竞争。linked路径真实执行linked_sync_service.create及update_invoice，只将外部remote.order_receipts边界设为合成空镜像；不执行关联同步run或任何远端写。先用错误64字符hash断言拒绝且门户版本不变，再使用当前SHA-256创建，验证before旧hash、after新hash、持久重读hash一致、状态/全部steps pending。普通编辑同时确认内容hash变化，整数portal_document_version仍独立递增并撤回发布。

全新047运行同046隔离pytest参数，目标test_mysql_invoice_edit_race.py：4 passed in22.44s。mysql.log确认Shutdown complete。独立审查无新增P1/P2，确认先前审计计数隔离问题已关闭。针对backend/app、backend/scripts、scripts的Invoice/InvoiceItem直接bulk UPDATE检索只命中xiaoman_service.py清理xiaoman_removed_lines的同步元数据；这一有限模式检索不等于全部写入口证明。T62保持partial，待其余取消/关联执行/脚本入口覆盖；总数仍21完整/43部分。未连接生产或发信、推送、部署。
### T62本地取消开始与PI读取竞争（2026-10-03）

新增test_mysql_invoice_cancel_race.py：真实cancellation_service.begin保留内部commit，不mock取消逻辑。取消先提交用现有router的invoice行锁预持，compete观察客户capture实际等待后finalize调用begin；反向由capture先持锁，begin等待。错误旧hash先拒绝，版本/取消状态/日志无写；正确hash取消后状态cancel_pending、门户版本恰增1、Publication/PiAmendment撤回且accepted清空、Conversion仍created、唯一cancel_step审计记录操作者，后续客户capture拒绝PI_REVISION_PENDING。只设置合成远端order ID，不调用远端读取或删除。薄上游表只用于本地隔离夹具。

048全新隔离MySQL，pytest tests/portal_mysql/test_mysql_invoice_cancel_race.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定mysqld8.0.46、portal-mysql-run-048和portal-cancel-race-048：2 passed in22.33s。mysql.log确认Shutdown complete；strict/diff通过。独立只读审查无P1/P2或假阳性。T62仍partial，不覆盖远端检查/删除/恢复、关联执行或所有写入口；总数21完整/43部分保持。未修改生产业务行为，未发信、推送或部署。
### T62关联执行本地失败与不确定恢复（2026-10-03）

扩充test_mysql_invoice_edit_race.py的linked场景：真实linked.run和sync_coordinator前置校验，在无回款截图时明确failed，后续outbound/receipt步骤仍pending，门户版本及withdrawn保持。随后仅将coordinator结果注入为ok=false/okki_accepted=true，真实ensure_running校验租约；新Session重复run保持uncertain且只调用一次coordinator，close_failed拒绝解除，invoice.linked_sync_id保留、门户版本不变、PI仍撤回且capture409。此注入只验证持久本地恢复政策，不证明真实远端请求或断线行为。

049全新隔离MySQL运行test_mysql_invoice_edit_race.py（沿用047隔离参数，新run-049及portal-edit-recovery-049）：4 passed in22.55s；MySQL Shutdown complete，strict/diff通过。独立复核无具体缺陷。T62仍partial，租约竞争/旧worker恢复/远端成功及其他入口尚无完整证据；当前21完整/43部分不变。没有真实远端发送、生产连接、推送或部署。
## T25百连接重复提交完整回放证据（2026-10-03）

test_mysql_load.py使用100个独立物理连接，在Barrier后以同key/body同时执行真实submit至commit。验证唯一OrderRequest/Revision/RequestLine/order.submitted审计/order_submitted outbox，quote consumed且未生成PI。新增保存100个连接ID、回放标记和原始毫秒样本到隔离运行目录duplicate-submit-evidence.json，不保存凭据或业务载荷。

050首次1 passed in22.30s，P95 737.09/P99 753.09/max772.82ms；独立审查发现“回放原结果”断言仅核对ID/status不足。已补去除replayed后完整响应字典相等，覆盖编号、版本、时间、金额等所有返回字段。全新051重跑：1 passed in22.38s，100独立连接、1创建、99回放，P95 707.79/P99 738.50/max745.93ms。原始证据D:/commission-system/tmp/portal-mysql-run-051/duplicate-submit-evidence.json，实际pytest输出D:/commission-system/tmp/portal-load-051-output.log。命令pytest tests/portal_mysql/test_mysql_load.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q -s --tb=short，指定本地mysqld8.0.46、新run-051及portal-load-051。

根据独立审查的关闭条件补强后，T25在隔离MySQL真实服务提交范围完整；当前22完整/42部分。耗时是本机合成上游服务submit-through-commit，不含HTTP/公网，不构成生产SLA或T64整体完成。仍需其余验收与正式环境门禁；未连接生产、发信、推送或部署。
## T01/T04真实HTTP邮箱登录边界（2026-10-03）

新增test_mysql_auth_http.py，真实portal router/auth服务及MySQL，ASGI HTTP替换仅数据库依赖及隔离配置/时钟。先以有效已验证账号请求challenge，再测未知邮箱，最后同一已绑定账号仅改status=disabled并越过重发冷却。三种响应除随机challenge UUID外完整相等；有效账号新增一条auth_code outbox，未知/禁用零新增。每次均无session Cookie、PortalSession数量不变，catalog及session接口均401，无邮箱回显、no-store。

052首次测试错用/auth/session得到404，修正为真实/session后053通过20.90s。独立审查发现新建disabled账号无Membership可能假阳性，改为已成功发验证码的同一已绑定账号仅状态改变，054重跑1 passed in21.03s。命令pytest tests/portal_mysql/test_mysql_auth_http.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46、新portal-mysql-run-054及portal-auth-http-054。无真实发信。

按独立审查关闭条件补强后，T01/T04在既定HTTP响应及邮件入队范围完整；当前24完整/40部分。不扩展为时间侧信道、浏览器Cookie、SMTP投递或生产代理验收。整体目标继续，未推送或部署。
## T08同站跨公司HTTP资源隔离（2026-10-03）

新增test_mysql_company_scope.py：同站/同业务员两个不同公司，各有有效成员、目录授权和真实OTP会话；第一家由trade开通，第二家真实invite/激活，不称两者都经邀请。双方实际quote/submit/propose/accept/approve生成隔离PI，own详情与quote HTTP200及真实PI capture作为对照。双向foreign order/PI/quote拒404；own order+foreign revision接受/拒绝同样404。与随机不存在ID响应比较仅去trace_id。列表items/total均只本公司一单。八类表OrderRequest/Revision/CommandReceipt/AuditEvent/OutboxEvent/Quote/RequestLine/Publication比较全字段有序快照，证明业务记录没有新增、删除或UPDATE；会话正常活动续期不在此范围。

055首次If-Match未带引号导致422，修复为合法头后056通过22.55s。独立审查要求quote/统计/不存在性/复合键及字段快照，057补读取覆盖通过22.55s，058最终补复合键与全字段快照：1 passed in22.45s；MySQL Shutdown complete，strict/diff通过。运行pytest tests/portal_mysql/test_mysql_company_scope.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，使用本地mysqld8.0.46、新run-058及portal-company-scope-058。仅薄上游夹具/真实门户迁移，非完整历史迁移证明。

独立定向复核确认T08当前接口范围完整，无新增P1/P2；当前25完整/39部分。不泛化员工隔离、时间侧信道或生产验证。未真实发信、操作生产、推送或部署，整体实现继续。
## T09员工归属与read_all不授写（2026-10-03）

新增test_mysql_employee_scope.py，真实员工密码登录/JWT/MySQL即时RBAC。read-only与write-capable两参数，后者含portal_order:write和invoice:write但无客户归属/代办。各自在read_all授予前后使用原JWT：外部订单detail由404变200，列表相应裁剪；四个合法写入口proposal-preview/proposals/approve/reject对只读角色403、对可写但无归属角色404，read_all不改变结果。负责人真实JWT对同一预览请求200，避免无效请求假阳性。

059/060原断言误把审批失败的独立审计判成业务变化；060先错误归因为角色变更审计，随后源码定位approval_service.record_failure。修正为7业务表完整字段不变，历史审计完整字段不变且只新增当前员工/订单的order.approval_failed，对应ACTION_FORBIDDEN或RESOURCE_NOT_FOUND。061只读分支1 passed22.39s。独立审查要求具备写权限的非负责人及owner正向对照，补强后062：2 passed23.26s（30条第三方jose utcnow弃用警告），MySQL Shutdown complete、strict/diff通过。

命令pytest tests/portal_mysql/test_mysql_employee_scope.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46及新portal-mysql-run-062/portal-employee-scope-062。独立定向复核确认T09本轮限定接口范围闭环，无新增P1/P2；当前26完整/38部分。无生产连接、发信、推送或部署，整体目标继续。
## T30未知运费与明确零费用（2026-10-03）

新增test_mysql_zero_fees.py，真实submit→proposal→accept→approve→PI capture和MySQL Numeric回读。未知费用初始修订shipping/total=null，客户读模型total=null，尝试审批CUSTOMER_ACCEPTANCE_REQUIRED且无Invoice/Publication/Conversion；缺失/null shipping的ProposalInput拒绝。明确全0费用提案在客户接受前仍不能建票；接受后实际Invoice shipping/internal_accessory/surcharge为0，商品及总额81.00，客户发布快照shipping为0.00，初始pending修订仍保持null未重写。

063执行pytest tests/portal_mysql/test_mysql_zero_fees.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46及新portal-mysql-run-063/portal-zero-fees-063：1 passed in21.48s；MySQL Shutdown complete，strict/diff通过。独立只读复核无缺口或假阳性，T30隔离MySQL费用与建票契约完整。当前27完整/37部分；不扩大为OKKI外部free_shipping标志、T42全部发票缺项校验或生产验证。未发信、推送或部署，整体目标继续。
## T39真实MySQL1062与有限整事务重试（2026-10-03）

新增test_mysql_invoice_number_conflicts.py，在隔离薄上游Invoice恢复真实invoice_no唯一约束；控制编号分配返回已有PI-LEGACY触发数据库1062，非手工构造IntegrityError。三分支：两次编号冲突后第三次新号唯一PI成功；持续编号冲突三次后409且仅一条INVOICE_NUMBER_CONFLICT失败审计；before_insert故意设已存在PK7触发PRIMARY1062仅尝试一次并抛IntegrityError。记录handle_error真实错误及每次SessionTransaction对象，验证分类、次数及整事务重启。成功用assert_one_pi核验原子建票；失败order仍ready_for_review/version3，无Invoice/Conversion/Publication/建票通知残留，原PI-LEGACY未改。

064运行pytest tests/portal_mysql/test_mysql_invoice_number_conflicts.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46及新portal-mysql-run-064/portal-invoice-conflict-064：3 passed in22.37s；MySQL Shutdown complete，strict/diff通过。独立审查无缺口或假阳性，T39隔离MySQL重试契约完整；当前28完整/36部分。不扩为真实并发选号压力或生产迁移证明。未发信、推送或部署，目标继续。
## T27提交响应丢失后过期恢复（2026-10-03）

新增test_mysql_submission_recovery.py，ASGI transport在真实订单POST路由完成MySQL commit并返回201后读取/丢弃响应，向客户抛ReadError。独立Session确认唯一订单和quote consumed，再将auth/quote/order时钟推进到报价expires_at+1秒。原键GET by-key及同key/body POST均200，完整data等于初次结果仅replayed=true；六类业务表OrderRequest/Revision/RequestLine/Quote/AuditEvent/OutboxEvent所有字段不变。会话正常续期不属于业务快照。

065执行pytest tests/portal_mysql/test_mysql_submission_recovery.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46及新portal-mysql-run-065/portal-submit-recovery-065：1 passed in21.01s；MySQL Shutdown complete，strict/diff通过。独立只读复核无缺口或假阳性，T27完整；当前29完整/35部分。证据为ASGI传输注入+真实MySQL，不称实际网络断连或生产验证。未发信、推送或部署，整体目标继续。
## T33确认后价格/地址/数量再次变化（2026-10-03）

新增test_mysql_reconfirm_changes.py三参数：先真实客户接受，再分别改该客户合同价规则（-10%→0）、地址、数量生成新proposal。修订ID/hash不同，当前accepted清空、状态awaiting_customer；原接受命令回放只返回原回执，不激活旧确认。分别用新旧revision审批都CUSTOMER_ACCEPTANCE_REQUIRED，无PI。再次接受新提案后真实建票，price总137/单价30、address总128/新地址、quantity总155/数量4，唯一PI与发布快照一致；旧Revision和RequestLine全字段保持不变。

066先3 passed22.31s；自行发现revision_id字符串与UUID比较恒不等风险，统一str后067重跑3 passed22.32s。命令pytest tests/portal_mysql/test_mysql_reconfirm_changes.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46及新portal-mysql-run-067/portal-reconfirm-067。MySQL Shutdown complete，strict/diff通过。独立复核无具体缺口，T33隔离MySQL再确认契约完整；当前30完整/34部分。不扩大为前端差异提示或生产验证。未发信、推送或部署，整体目标继续。
## T60建票校验失败后的修订恢复（2026-10-03）

新增test_mysql_approval_repair.py。在适配器最终发票校验阶段注入缺失length，仍执行真实invoice.validate_invoice；初次create_invoice内部ready校验正常执行，注入发生在第二次校验且已获得真实Invoice id。execute错误INVOICE_VALIDATION_FAILED，Invoice/Item/ReceiptIntent/Conversion/Publication/PiAmendment/Outbox/CommandReceipt全字段回到基线，所有历史审计不变且只新增该请求一条失败审计。恢复校验后同request创建修正运费提案，接受前仍禁止审批，客户重新接受后execute及原键回放产生唯一PI、收款草稿、conversion、publication和建票通知，金额108正确可读取。

068故障注入过早被INVOICE_SNAPSHOT_MISMATCH拦截，调整注入阶段；0691 passed21.32s。独立审查要求排除遗留成功回执/成功审计，补全上述快照后0701 passed22.39s。命令pytest tests/portal_mysql/test_mysql_approval_repair.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46及新portal-mysql-run-070/portal-approval-repair-070。MySQL Shutdown complete，strict/diff通过。

按独立审查关闭条件补强后T60隔离MySQL故障恢复契约完整；当前31完整/33部分。明确是校验边界故障注入，不替代T42自然缺项覆盖或真实部署。未发信、推送或部署，目标继续。
## T41本地作废丢响应、永久关联及撤权回放（2026-10-03）

新增test_mysql_void_recovery.py，真实approve后void+MySQL commit再抛ConnectionError模拟服务边界丢响应，新Session验证tombstoned/withdrawn、文档版本2及唯一void回执/审计/outbox。原body在旧/新IfMatch均完整回放，改reason或invoice_document_version均409 IDEMPOTENCY_CONFLICT。Invoice ORM删除被生命周期守卫拒绝，直接删除Conversion被真实迁移FK拒绝。原approve只回原票；新revision审批命令INVOICE_ALREADY_CREATED不能重建；客户PI不可读。多业务表完整字段快照保持不变；真实员工停用后403禁止私密回放。

071首次测试误期待旧approve拒绝，实际合法回放符合契约；修正为分别测试历史回执和新命令。072执行pytest tests/portal_mysql/test_mysql_void_recovery.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46及新portal-mysql-run-072/portal-void-recovery-072：1 passed21.49s；MySQL Shutdown complete、strict/diff通过。独立复核无具体缺口，T41本地作废/永久关联契约完整；当前32完整/32部分。不扩展真实网络断连或其他来源ingest清理，也没有远端删除或生产操作。未发信、推送或部署，目标继续。
## T13目录搜索、筛选和报价授权边界（2026-10-03）

新增test_mysql_catalog_scope.py，真实门户HTTP路由/会话与隔离MySQL。创建四种真实目录记录：published无grant、draft有grant、disabled有grant、published但grant disabled。合法商品详情200与报价201作正向对照；列表只含授权商品，total/category/color facets正确，隐藏型号/颜色搜索均空。隐藏和不存在UUID详情404响应一致；合法+隐藏商品混合报价精确返回404/RESOURCE_NOT_FOUND/ITEM_UNAVAILABLE，内部数字SKU作为public item_id访问/报价均422。Quote/OrderRequest/Revision/CommandReceipt/AuditEvent/OutboxEvent所有字段前后相同，排除拒绝请求的业务残留。隐藏源SKU为合成无效来源，精确错误断言确保不能依靠下游源校验失败蒙混通过；不据此证明真实库存或定价。

073首次失败是测试误读外层code，按真实信封修正为data.error_code。074执行pytest tests/portal_mysql/test_mysql_catalog_scope.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46、新portal-mysql-run-074及portal-catalog-scope-074：1 passed in20.99s。MySQL日志Shutdown complete；check_conventions.py --strict、git diff --check通过。独立只读审查确认无其他P1/P2或阻碍T13关闭的假阳性。

T13当前目录/伪造输入契约完整，当前33完整/31部分。19:50 git_sweep --no-fetch完成，仅本地快照，主目录未改动，本分支无upstream。未连接生产、发信、推送或部署；整体目标继续。
## T58撤销下单能力的旧/新会话HTTP边界（2026-10-03）

新增test_mysql_capability_http.py，真实submit/proposal与admin_service.update_customer撤can_order，保持账号/成员/access启用。旧cookie对accept/reject/cancel均401/AUTH_REQUIRED；实际OTP服务重新签发当前会话后三路均403/ACTION_FORBIDDEN。view_price True/False两参数分别证明仅撤下单能力也拒写，以及订单读取按查价能力保留/隐藏金额、行价格及proposal。合法Origin/CSRF/IfMatch、awaiting_customer状态；七类业务表所有字段快照不变，版本2、accepted指针/接受人/时间均未改变。OTP为真实服务调用，不称浏览器或登录HTTP全链路。

独立审查确认原T58“全部403”混淆撤销会话与有效会话缺能力；已澄清为旧401、新403，不改变业务授权。075失败为测试误写SESSION_REQUIRED，按实际AUTH_REQUIRED修正。076执行pytest tests/portal_mysql/test_mysql_capability_http.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46、新portal-mysql-run-076及portal-capability-076：2 passed in21.04s。strict/diff检查通过；独立只读复核无假阳性或新增P1/P2。

T58契约完整，当前34完整/30部分。未连接生产、发送邮件、推送或部署；整体目标继续。
## T40真实员工HTTP发票来源保护（2026-10-03）

新增test_mysql_invoice_source_http.py，先实际submit/proposal/accept/approve经内部adapter生成合法portal PI，再真实员工密码登录/JWT调用既有发票路由。普通创建及截图创建均拒source_type=portal，客户端allow_portal_source=true不能提升为服务端授权；manual携带source_order_id同样精确400；既有门户票修改source_order_id或去除来源均精确400。十类表Invoice/InvoiceItem/ReceiptIntent/OrderRequest/Revision/CommandReceipt/Conversion/Publication/AuditEvent/OutboxEvent所有字段攻击前后相同。仅数据库依赖、隔离JWT配置及基础夹具外部边界替换，未替换鉴权或发票服务。

077运行pytest tests/portal_mysql/test_mysql_invoice_source_http.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46、新portal-mysql-run-077及portal-invoice-source-077：1 passed in24.20s，5条第三方jose utcnow弃用警告。MySQL Shutdown complete，strict/diff通过。独立只读审查未发现具体缺口或假阳性，T40真实JWT/隔离MySQL手工API边界完整。

当前35完整/29部分。证据不扩展为生产身份或完整上游schema验收；未发信、推送或部署，整体目标继续。
## T23四位单价与负折扣真实金额链路（2026-10-03）

新增test_mysql_money_rounding.py。仅修改本测试客户fixed价格规则+5.2750，真实报价单价35.2750，qty3行额105.83；实际提交/提案/接受/approve建票后MySQL金额一致。通过既有invoice.update_invoice设置折扣-5.00、运费45.00、其他费用0；独立Session回读单价35.2750、折扣-5.00、商品100.83、总145.83，并与门户domain公式比较。旧发布不可下载，真实pi amendment创建→客户接受→发布后同一invoice_id，Invoice/Conversion各1，Publication2；客户详情与PI快照均145.83，初次Revision/RequestLine所有字段保持不变。负折扣由内部PI编辑输入，不宣称初次客户报价允许客户自填折扣。

078失败为测试错误比较total_amount的元组返回值，改读取[1]总额。079运行pytest tests/portal_mysql/test_mysql_money_rounding.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46、新portal-mysql-run-079及portal-money-079：1 passed in22.25s。MySQL Shutdown complete，strict/diff通过；20:06 git_sweep --no-fetch本地巡检完成。独立只读审查确认无具体P1/P2或假阳性，T23按原规格完整；当前36完整/28部分。证据为隔离MySQL薄上游夹具中的实际领域链路，不扩称生产价格配置或PDF视觉验收。未连接生产、发信、推送或部署，整体目标继续。
## T06停用后旧会话敏感路由矩阵（2026-10-03）

新增test_mysql_disabled_http.py，真实会话和已发布PI，先8类读取HTTP200作对照。account/customer/site分别通过实际update_account/update_customer/update_settings停用或暂停；member因P0无独立管理端点，在真实authority屏障中仅改持久member.status。停用后9读（含session、目录/详情/图片、订单列表/详情/原键回查、quote、PI）及6写（quote/submit/cancel/accept/reject/reorder）均精确拒绝：站点503/SERVICE_UNAVAILABLE，其余401/AUTH_REQUIRED，no-store。11业务表所有字段前后不变。PDF只替换render为可计数测试字节，真实下载capture鉴权/二次核验未替换；停用后render无新增调用，不宣称真实PDF视觉或浏览器验证。

080执行pytest tests/portal_mysql/test_mysql_disabled_http.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本地mysqld8.0.46、新portal-mysql-run-080及portal-disabled-080：4 passed in23.44s。MySQL Shutdown complete，strict/diff通过；独立只读审查确认T06按现有规格完整，无P1/P2或假阳性；已收窄测试模块注释，不声称涵盖sales-contact等未测入口。当前37完整/27部分。20:12本地git巡检完成；不扩为并发停用或生产代理验证。未连接生产、发信、推送或部署，整体目标继续。
## T07旧管理员JWT与T10全部客户写路由跨站防护（2026-10-03）

新增test_mysql_stale_admin_jwt.py。原负责人真实密码登录得到含super_admin的JWT，先order detail/preview HTTP200。实际employee_admin.update_user撤为无权限角色或停用，两参数均确认数据库实时授权无super_admin，旧JWT仍含super_admin且未过期；3读（列表/详情/审计）及4写（预览/提案/拒绝/审批）均403/ACTION_FORBIDDEN。7业务表全字段不变，历史审计全字段不变且只新增该请求一次系统order.approval_failed，safe_diff_json准确关联employee_id。081失败是测试误期待系统审计actor_id为员工；按record_failure修正actor_type/system、actor_id/null、安全employee_id引用，未修改业务实现。082执行该模块：2 passed in22.36s，22条第三方jose utcnow弃用警告；新run-082/portal-stale-admin-082，MySQL Shutdown complete。

新增test_mysql_csrf_matrix.py，自动断言测试矩阵与router的全部POST路由集合一致（9个）。每个路由以合法Cookie/body/代理/版本/key测试兄弟子域、null Origin、缺Origin、缺CSRF、错CSRF五类，共45次均403/CSRF_REJECTED/no-store且无Set-Cookie；11业务及认证表所有字段前后不变，包括session/preauth/challenge/rate buckets。真实预登录有效OTP与有效客户会话作凭据；自查后追加合法Origin/CSRF报价201和OTP verify200两个正向对照，排除无效凭据假阳性。083首次1 passed23.74s，补正向对照后084：1 passed22.37s。命令pytest tests/portal_mysql/test_mysql_csrf_matrix.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定mysqld8.0.46、新run-084/portal-csrf-084。

独立审查代理本轮返回usage limit而未完成审查，没有把此结果当作通过。依completion-checklist“审查工具不可用时做独立一轮自查并说明限制”，主线程另核对JWT仅取身份→实时DB授权、真实上游撤权写入口、系统失败审计及两种会话CSRF验证/回滚顺序，未发现具体缺陷。T07/T10在上述真实HTTP/隔离MySQL契约范围已证明，当前39完整/25部分；本批独立agent复核仍待工具恢复，不替代生产审批或全站安全保证。未连接生产、发信、推送或部署，整体目标继续。
## T31同公司提案绑定与T44发布发票绑定（2026-10-03）

新增test_mysql_proposal_binding.py：同access/同会话两笔真实quote→submit→proposal，先确认两单详情有效。A提案经真实客户拒绝后再生成新提案，双向把A/B revision交换接受均404/RESOURCE_NOT_FOUND；A旧未接受提案409/PROPOSAL_SUPERSEDED；正确ID但错hash409/PROPOSAL_CHANGED；B在expires_at精确边界接受409/PROPOSAL_EXPIRED。七类业务表所有字段前后不变，恢复实际时钟后A当前提案HTTP200正常接受、B及旧revision无接受人。到期仅注入交易模块时钟，不当作T56新进程/跨日证明。085夹具有效期1小时不在站点允许列表而422；改24小时后086碰到真实待确认状态禁止直接覆盖，改为真实reject后新提案，未修改业务状态机。

新增test_mysql_publication_binding.py：同公司两单各真实接受/approve得独立PI，ORM改remark升版本并真实amendment提案/接受。真实员工JWT双向publish-pi传另一invoice_id均422/INVALID_INPUT；换另一单accepted_revision_id均404/RESOURCE_NOT_FOUND，十类表全字段不变。尝试实际INSERT requestA+invoiceB publication触发真实MySQL1452复合FK而非重复版本1062，rollback后快照相同。合法A发布HTTP200、PI capture返回A内容及invoice绑定；B保持accepted未误发布。087夹具第二单PO与quote不一致导致QUOTE_CHANGED，已按真实报价保持一致。

088合并运行pytest tests/portal_mysql/test_mysql_proposal_binding.py tests/portal_mysql/test_mysql_publication_binding.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定mysqld8.0.46、新portal-mysql-run-088/portal-binding-088：2 passed in22.49s，5条第三方jose utcnow弃用警告。MySQL Shutdown complete，strict/diff通过。独立agent额度仍受限；主线程另核对状态转移、expiry严格边界、revision_for按request过滤、load_pi核对request/conversion/invoice来源、strict extra forbid及实际migration复合FK，无具体缺陷，不称独立agent通过。

T31/T44当前HTTP及隔离MySQL绑定契约完整；当前41完整/23部分。本批与T07/T10一样保留独立agent复核未完成限制。未连接生产、发信、推送或部署，整体目标继续。
## T14报价异常与T21重复SKU/数量约束（2026-10-03）

新增test_mysql_quote_constraints.py，真实门户HTTP/会话/CSRF与隔离MySQL。T14先真实有效报价201/27.0000，再分别修改真实StdPrice为不匹配长度、零价、负价、EUR；详情200但价格不可用，报价503/PRICE_UNAVAILABLE，七类业务表全部字段保持不变。每种数据库变更finally恢复原源数据。标准价或客户价超过四位小数仅在resolve_price输出边界注入，仍由真实pricing拒绝；MySQL源列本身仅保存四位，不能声称五位价格实际落库。恢复后再次真实报价201/81.00作为对照。

T21真实目录min_qty4/step2，插入同站同namespace/product/sku的第二item被实际MySQL1062/uq_op_catalog_sku拒绝并回滚。HTTP零、bool、浮点、字符串、低于MOQ及不符step均422；数量52超过合成库存上限50精确409/STOCK_CHANGED。两重复item_id各30的拆行请求422，所有失败七类业务表字段不变。唯一行数量50合法201/1350.00。库存镜像1000g与20g转换来自隔离夹具，不代表真实可供量或其他单位。

089运行pytest tests/portal_mysql/test_mysql_quote_constraints.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定mysqld8.0.46、新portal-mysql-run-089/portal-quote-constraints-089：2 passed in20.99s；MySQL日志Shutdown complete。前端实际node --test tests/checkout.test.mjs：12 passed，0 failed，84.6614ms，其中重复添加合并SKU总量并验证MOQ/step/上限。未修改业务代码。

独立代理仍受额度限制，主线程另做一轮源码自查：pricing严格校验正数/USD/四位精度且不回退，QuoteInput严格整数与唯一item_id，build_lines拒绝标准SKU重复，ORM及172迁移一致的唯一约束，购物车先合并再校验总量。未发现具体缺陷；不称独立代理审查通过。核对发现原文将前台合并与服务端校验混写为“服务端归并”，已统一02/03/06契约为前台合并、接口单SKU单行、后端拒重复并验证总量，保留原防拆行/超量/MOQ/step要求，不改变业务行为或以放宽规格关闭条目。

T14/T21在上述价格源边界及唯一SKU数量契约范围完整；当前43完整/21部分。本批与T07/T10/T31/T44一样保留独立代理复核未完成限制，完整历史迁移/真实SMTP与COS/试点发布门禁仍独立存在。未连接生产、发信、推送或部署，整体实现目标继续。
本批收尾检查：verify_portal_docs.py通过（8文档、23本地链接/锚点、3 JSON、64 T规格、17发现）；check_conventions.py --strict通过；git diff --check通过，仅既有LF/CRLF提示。22:11 git_sweep --no-fetch完成，为本地快照；主目录0修改/1未跟踪，本任务worktree42修改/37未跟踪统计项，分支无upstream，未提交/推送/合并。
## T22配件、件/套/克换算及精确SKU完整建票（2026-10-03）

新增test_mysql_accessory_units.py，三参数从真实MySQL薄库存镜像表、inventory_source.load SQL、sku_source、配件标准价和客户-10%规则出发，经真实HTTP目录/报价→submit/proposal/accept/approve→客户PI capture。分别配置piece/piece factor1 stock7 buffer1、set/piece factor3 stock20 buffer2、pack/g factor7.5 stock47 buffer2，合法数量6均67.50商品额、114.50含45+2费用正式PI；数量7均精确409/STOCK_CHANGED且7业务表全字段不变。库存单位映射与目录不一致均503/INVENTORY_UNAVAILABLE，无报价残留。观察量/单位/非未来同步时间从真实源回读核对。

每组建立两种人类名称/型号/颜色完全相同的独立产品SKU，标准价12.5/99，以精确ID得到正确客户单价11.2500，而非按名称命中另一个99价格；错误产品/SKU组合精确409/SKU_UNAVAILABLE。配件标准size/unit为空，目录及客户快照不凭空展示发品重量/长度，PI product_kind保持accessory、全名Tape / replacement不丢slash、price/qty/amount经新Session核验一致。unit_weight_grams仅g库存配置保留7.5，piece/set为null；客户销售单位保持piece/set/pack。

第四用例仅在测试拥有的隔离库临时以无PK同名SKU镜像表制造实际重复源行，真实quote SQL发现多义join后409/SKU_UNAVAILABLE且7业务表全字段不变；finally恢复原镜像表，再真实成功报价81.00作对照。目录/授权为隔离种子，非管理端导入全链路证明；库存与价格是合成数据，不替代实际经营配置、生产单位规则或完整历史迁移。

090首次3 passed/1 failed in22.30s，套装availability unknown；091加入原始库存读回诊断后2 passed/2 failed in22.34s，明确DATETIME(0)将带微秒种子四舍五入至未来整秒，inventory_source按既定规则拒绝未来时间。仅修正测试种子为beijing_now().replace(microsecond=0)，不放宽时效守卫、不改业务代码。092全新隔离重跑：4 passed in22.38s；MySQL Shutdown complete。命令pytest tests/portal_mysql/test_mysql_accessory_units.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定mysqld8.0.46、新portal-mysql-run-092/portal-accessory-units-092。

独立代理额度限制未解除，主线程另做一轮源码自查：实际库存source按显式unit及标准factor换算/安全余量；标准源不猜类别且重复join拒绝；配件定价只用精确product/sku+currency；订单/提案/审批重复核验当前价格库存；adapter传标准类别/规格而非客户别名；真实invoice配件路径再次按ID取价并校验快照。未发现具体缺陷，不称独立代理复核通过。T22现有规格在隔离端到端范围完整，当前44完整/20部分；真实SMTP/COS、历史迁移与试点发布仍未完成。未连接生产、发信、推送或部署，整体实现目标继续。
T22收尾：check_conventions.py --strict、git diff --check、verify_portal_docs.py均通过（8文档/23链接锚点/3 JSON/64规格/17发现）。22:22 git_sweep --no-fetch完成，仅本地快照；主目录0修改/1未跟踪，本分支42修改/37未跟踪统计项，无upstream。无前端变更，未重复无关构建；本次没有业务代码变更、提交、推送、合并或发布。
## T46门户建PI仅本地草稿、无库存/外部回款副作用（2026-10-03）

新增test_mysql_pi_side_effects.py：真实submit/proposal/accept→approval_service.execute实际commit→PI capture→原命令完整回放。10个高层禁入探针覆盖sync_invoice、push_order、push_outbound、出库enqueue、半成品prepare/finalize与write_ledger、Receipt.create/deliver、ReceiptIntent.arm；HTTP/异步HTTP/urllib/SMTP及socket边界拦截外部发送，socket仅允许本次拥有的127.0.0.1 MySQL端口。主动dispose后真实重连作网络探针正向对照；探针被调用即记录并失败，不能因异常被吞而误判成功。

执行期SQL DML监听只允许门户表、Invoice/InvoiceItem/ReceiptIntent写入，其他尝试即记录并失败，补充最终快照无法识别的回滚写入。13类库存占用/流水、出库、推单、关联任务、实收/回款审计与结算表全字段前后一致；以非空历史InventoryBalance及Receipt哨兵检测误更新。薄上游表省略FK且哨兵为测试数据，不作为完整历史迁移证明。

真实唯一PI金额128.00、source portal，internal_received/internal_balance均null、sync_status not_synced、无OKKI订单ID、无出库请求/linked任务/半成品计划。唯一ReceiptIntent仍draft/eligible1，amount/date/receipt_id/lease/token均null、attachments空；eligible仅既有后续流程资格，不等于授权收款或已经收款。建票通知pending入队是允许动作，未启动通知worker，不发真实邮件。真实回放完整original_receipt相同，assert_one_pi再次确认所有本地唯一关联与通知，13类表无变化，禁止调用与禁止SQL均零次。

093首次1 passed in22.49s；另轮自查发现客户端探针尚未覆盖所有socket连接，补仅允许拥有MySQL端口的socket guard和真实重连对照。094全新隔离重跑1 passed in22.39s，MySQL Shutdown complete。命令pytest tests/portal_mysql/test_mysql_pi_side_effects.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定mysqld8.0.46、新portal-mysql-run-094/portal-pi-side-effects-094。

独立代理仍受额度限制，主线程另核对admin_router.approve_order只调用execute、approval→adapter→Invoice.create仅save_draft/flush、没有同步/arm/出库调用，及幂等分支授权后只回原回执。无具体缺陷，不称独立代理通过。本测试证明当前门户建票执行链，不泛化后续员工主动同步、其他业务入口、通知worker或生产环境。T46当前契约完整，当前45完整/19部分；整体实现目标继续。README删除重复进度清单，仅链接本handoff为当前进度唯一来源，保留设计审查结论与证据限制。未连接生产、发信、推送、合并或部署。
T46收尾检查：check_conventions.py --strict、git diff --check通过（仅既有LF/CRLF提示），verify_portal_docs.py通过（8文档/24链接锚点/3 JSON/64规格/17发现）；22:33 git_sweep --no-fetch完成，仅本地快照，主目录0修改/1未跟踪，本分支42修改/37未跟踪统计项、无upstream。没有业务代码或前端变更，本轮只新增回归与同步文档；没有提交、推送、合并或部署。
## T59确认/审批丢响应恢复与T63旧PI确认不误发布新版本（2026-10-03）

新增test_mysql_decision_recovery.py，真实FastAPI客户/员工路由、客户会话/Origin/CSRF、员工密码登录/JWT和隔离MySQL，仅覆盖数据库依赖与隔离配置。LoseResponse在实际路由commit并返回200之后读走成功响应，再抛httpx.ReadError；记录成功data供逐字段比较，非实际公网断线。

T59八参数为accept/approve×expiry/replacement×price/inventory。accept实际提交→提案后HTTP确认丢响应；approve实际客户确认后HTTP建票丢响应。到期仅将proposal_decisions交易模块时钟推进到真实revision.expires_at+1秒，不改变认证时钟或不可变数据库时间，不作为T56新进程/跨日证据。替换分支分别真实新订单提案（45→46运费）或ORM修改原PI→真实B修订提案。依赖503只在pricing.resolve或catalog.load_observations边界注入；先真实fresh quote精确503/PRICE_UNAVAILABLE或INVENTORY_UNAVAILABLE且探针被调用，再清空探针，以原If-Match/原body HTTP重放。恢复200/no-store、完整original_receipt相同、依赖探针零调用，十二类业务表全部字段不变，包括首次actor和接受时间/原回执；正常会话活动续期不在业务快照中。

实际回读确认当前状态/row_version与恢复响应一致、首次accept actor为原客户/approve actor为原员工且成功回执各唯一。替换后旧accept不能复活旧proposal，当前awaiting_customer/accepted null/active新ID且零Invoice；旧approve不能建第二票，原Invoice唯一、B amendment pending_customer/accepted null，客户PI capture409。expiry不延长旧修订或重写接受记录。

T63两参数覆盖A仅接受与A已接受发布：初次真实PI→ORM改A→真实A提案→客户HTTP接受commit后丢响应，已发布参数再HTTP发布A且capture明确PI A。内部改B并真实创建B提案后，用原If-Match重放A接受，返回A完整回执与当前pending_customer/当前row_version；原A发布已成功时仅返回原发布回执，否则旧首次发布409/VERSION_CONFLICT。进一步使用B当前版本头/当前document_version搭配A旧accepted_revision_id或B尚未确认ID，两者均精确409/CUSTOMER_ACCEPTANCE_REQUIRED。十二类业务表全字段不变，B无接受人、无已发布PI，capture409；只有真实B确认→B发布后capture可读PI B，原Invoice仍唯一，Publication数量2或3与A历史发布一致。

095首跑8 passed/2 failed in27.37s，PI首个A提案在配置补入前被SKU_UNAVAILABLE拦截；修正测试隔离配置初始化顺序，无业务变更。096十项通过28.37s/13条jose utcnow弃用警告；另轮自查发现旧If-Match拒绝不足以覆盖当前版本配旧确认，补上述两类精确拒绝及503错误码。097最终全新隔离重跑10 passed in28.36s/17条第三方jose弃用警告；MySQL Shutdown complete。命令pytest tests/portal_mysql/test_mysql_decision_recovery.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定mysqld8.0.46、新portal-mysql-run-097/portal-decision-recovery-097。

独立代理额度限制仍存在，主线程另轮源码核对auth/scope先于回执查询、成功回执先于If-Match/时效/价格库存复验、旧回放无写状态、PI新发布必须同时匹配当前active/accepted/document且有客户接受，异常回滚及原历史接受不可重写。未发现具体缺陷，不称独立代理复核通过。T59/T63在当前HTTP与隔离MySQL契约范围完整；当前47完整/17部分。无业务代码变更、生产连接、真实发信、推送、合并或部署，整体实现目标继续。
T59/T63收尾：check_conventions.py --strict、git diff --check通过（仅既有LF/CRLF提示），verify_portal_docs.py通过（8文档/24链接锚点/3 JSON/64规格/17发现）；22:45 git_sweep --no-fetch完成，仅本地快照，主目录0修改/1未跟踪，本分支42修改/37未跟踪统计项、无upstream。当前未补齐为T11/T12/T19/T36/T42/T47/T48/T49/T50/T51/T52/T53/T54/T56/T61/T62/T64，不以局部证明关闭完整历史迁移或正式试点门禁。
## T12暂停并发与T11业务员交接证明（2026-10-03）

新增test_mysql_customer_handoff.py，T12四参数为submit/approve × 暂停先/业务写先。实际admin_service.update_customer与提交/审批在两个独立MySQL事务竞争，由compete观测真实锁等待控制提交顺序。暂停先则提交401/AUTH_REQUIRED、审批403/ACTION_FORBIDDEN且无业务残留；业务写先则完整请求或唯一PI、审计与outbox保留，随后暂停并撤销旧会话。两种顺序均验证旧客户token不能再写及十二业务表全字段不变。

T11两参数remove/explicit_grant覆盖真实workflow_service.transfer_primary_owner→管理员绑定复核/transfer_customer→重新启用→实际OTP重新登录→新负责人提案/客户确认/审批。归属变化进入review_required、旧会话撤销、未用报价失效；仅选中未建票请求交接，accepted指针清空，旧确认不能审批。旧业务员失去待处理请求访问；新业务员对既有PI按历史策略拒绝或只读。新提案hash包含新负责人，另仅替换sales_user_id验证摘要改变。重新确认后只创建一张归新负责人的PI；原提交归属快照、既有PI/items/publication、旧接受revision和所有既有审计逐字段不变。

098首跑4 passed/2 failed in23.56s，两处失败均是测试把全字段tuple快照当对象读取content_hash；修正为独立scalar取值，并补仅归属变化的hash断言。099全新隔离重跑：6 passed in23.63s。命令pytest tests/portal_mysql/test_mysql_customer_handoff.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定拥有的本地mysqld8.0.46、portal-mysql-run-099与portal-customer-handoff-099。未改业务实现。

独立代理额度限制尚未解除，主线程另轮源码自查：管理暂停和上游转交先锁authority并实时授权；transfer仅选择待处理请求、撤销会话/报价/邀请、清接受指针；历史grant只读；digest绑定authority；建票按当前负责人；历史Invoice不重归属。未发现具体缺陷，不称独立代理复核通过。证据使用隔离MySQL薄上游夹具与真实服务调用，不称登录HTTP/浏览器全链路或完整历史迁移。T12当前规格完整，T11仅业务员交接部分新增证据，合并/拆分/外部身份改绑仍未完整验证。

当前48完整/16部分；未完整为T11/T19/T36/T42/T47/T48/T49/T50/T51/T52/T53/T54/T56/T61/T62/T64。完整指对应规格的已记录隔离验证，不代表生产或全系统验收。详细文档本轮交付与实现进度分别管理；未连接生产、真实发信、推送、合并或部署。
本轮收尾：文档校验通过（8篇、24处本地链接/锚点、3个JSON示例、64条验收规格、17项设计发现）；check_conventions.py --strict和git diff --check均exit 0，仅既有LF/CRLF提示。23:02北京时间git_sweep --no-fetch完成，仅本地快照；主目录0修改/1未跟踪，本任务分支42修改/37未跟踪统计项、无upstream。未提交、推送、合并或发布。

## T11客户合并、拆分与外部身份改绑（2026-10-04）

新增test_mysql_customer_identity_review.py，实际隔离MySQL、已迁移门户表及现有客户/认证/订单/PI服务。四项覆盖合法合并到新规范客户、保留源公司的拆分、不同已验证公司ID合并拒绝、管理员显式外部身份改绑。上游客户表为按ORM列建立的薄夹具，审批提案及证据为合成种子，执行调用真实execute_customer_ownership_change，不替换执行器/授权/归属解析；不宣称完整历史schema、真实人工审批或管理界面全链路。

合并/拆分执行实际重建assignment并更新logical ownership。受影响access进入review_required，auth_version增加，旧会话撤销、未消费邀请撤销、未用报价expired；原access.customer_id保持原锚点，不跟随merged_into别名。合法合并目标没有自动创建门户access，拆分目标原有access必须独立复核、显式启用并实际OTP重新登录。正向对照能读B自己的请求及列表；B读取A订单/PI/quote或盗用A报价提交均404/RESOURCE_NOT_FOUND，列表仅B一单，A旧token报价401。普通启用不能擦掉A复核门禁。全十二业务表在治理执行后不变；后续复核不改任何原Invoice/OrderRequest/Revision字段。

新增负向治理场景：把两家不同verified strong company_id合并，真实上游验证精确OWNERSHIP_EXECUTION_IDENTITY_CONFLICT；门户业务全字段不变，两方授权仍enabled、旧会话未撤销并能真实authenticate。拒绝发生在业务变更之前，不能把该合法保护当测试失败后放宽规则。

显式改绑：同规范公司新verified身份可选；其他公司的identity被IDENTITY_REVIEW_REQUIRED拒绝。管理员读取复核摘要后新增待处理请求，再提交旧摘要精确REVIEW_CHANGED；无业务残留。有效新摘要改绑后access.suspended、未用报价expired、旧会话不能复活；显式启用并实际OTP重新登录只绑定原规范公司。旧已发布PI仍128.00可读，原公司/外部ID快照不改，另一公司仍404；旧已接受待处理单审批PROPOSAL_CHANGED且无PI。实际新quote→submit→proposal→accept→approve创建唯一新PI，customer_id使用新外部身份、总128.00；全体原Invoice/OrderRequest/Revision逐字段保持不变，旧待处理单不自动重绑或建票。

100首跑3 failed in26.57s，均测试夹具/断言错误：重建计划缺user_id、tuple快照按dict索引；依据真实上游身份冲突规则分开合法合并与拒绝场景，不改业务守卫。101修正后4 passed24.78s。补完整新交易闭环后102为3 passed/1 failed24.70s，测试跨关闭Session读取过期PortalSession导致DetachedInstanceError；改为在活跃Session内提取CSRF字符串。103为4 passed24.39s。另轮自查补报价窃用、列表范围、陈旧影响摘要断言；104最终全新隔离执行4 passed in24.64s，MySQL日志Shutdown complete。

最终命令pytest tests/portal_mysql/test_mysql_customer_identity_review.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本次拥有的mysqld8.0.46、portal-mysql-run-104及portal-identity-review-104。所有失败修复仅限测试，未修改业务实现。

独立审查代理既有限额未解除，本轮未取得新的独立代理复核；依completion-checklist另轮源码自查：上游治理先锁authority、验证完整批准分区再写、所有受影响客户暂停；逻辑身份取current overlay且不自动canonical重绑；rebind实时摘要/身份/唯一性检查并保留规范锚点；新建票adapter要求订单身份快照等于当前授权；历史PI按原request/publication读取。未发现具体缺陷，不称独立代理通过。认证走实际OTP服务但没有真实SMTP；此模块未执行浏览器/HTTP路由，相关独立规格不借此关闭。

结合099已通过的业务员转交/重新确认/新归属单PI/历史审计保留证明，T11当前契约完整。当前49完整/15部分；剩余T19/T36/T42/T47/T48/T49/T50/T51/T52/T53/T54/T56/T61/T62/T64。整体实现目标仍未完成，生产/完整迁移/真实SMTP及COS/试点门禁仍独立存在；未连接生产、发送真实邮件、提交、推送、合并或部署。
T11本批收尾：check_conventions.py --strict、git diff --check通过（仅既有LF/CRLF提示），verify_portal_docs.py通过（8文档/24本地链接锚点/3 JSON/64规格/17设计发现）。09:45北京时间git_sweep --no-fetch完成，仅本地快照；主目录0修改/1未跟踪，本任务分支42修改/37未跟踪统计项、无upstream。无前端或业务代码改动，未重复无关构建；没有提交、推送、合并或发布。

## T42缺项PI草稿不得发布、未知费用不得自动确认（2026-10-04）

新增test_mysql_incomplete_pi_http.py，真实员工密码登录/JWT、既有发票PUT、门户员工/客户HTTP路由、客户Cookie/Origin/CSRF与隔离MySQL。三参数contact_name/length/items：实际完整PI先经员工编辑形成A修订、客户实际确认；再通过既有发票编辑接口保存缺收货人、发品长度或空明细草稿。独立Session读回缺项确实落库；发票文档版本递增、旧publication全部withdrawn、amendment.accepted清空。当前版本头/当前invoice_document_version搭配A真实旧确认发布，精确409/CUSTOMER_ACCEPTANCE_REQUIRED；新的缺项PI提案精确409/INVOICE_VALIDATION_FAILED；客户实际下载409/PI_REVISION_PENDING且渲染探针零调用。十二业务表全字段快照在全部拒绝操作前后不变。

实际编辑接口补齐缺项后形成B提案；客户未确认B时仍拒发布，只有真实B确认后员工发布成功、客户HTTP下载200且渲染内容明确Repaired complete PI B、金额128.00/运费45.00。仍仅同一Invoice、Conversion和ReceiptIntent各一，Publication仅初次与B两份；原请求的接受revision/行快照全部字段不改。不把保存草稿或Invoice状态作为已获客户发布授权。

两参数运费null/omitted：客户真实POST /orders成功，但初始Revision.shipping_amount/total_amount为null、fees_status pending，详情准确返回未知总额。员工完整提案接口缺省或null运费均422/INVALID_INPUT；PI下载409且不渲染、十二业务表无变。只有显式三项费用0.00完整提案→实际客户HTTP确认→真实员工HTTP审批建票→客户下载，才得到81.00、shipping_fee0.00；初次未确认费用快照仍为null，不重写历史为0。另在既有发票PUT发送shipping_fee=null精确422且所有业务表不变，遵守真实非空字段契约，没有为制造测试草稿放宽API。

PDF只替换render为可计数测试字节，真实下载capture、授权、版本二次核验与审计未替换；这是发布/读取边界证明，不当作真实PDF排版或T50视觉验收。上游Receipt/Allocation/ShippingOperationEvent/OutboundTask为薄表夹具，门户172/173迁移真实执行；合成价格/库存和隔离JWT配置不代表生产经营配置/完整历史迁移。

105首跑4 failed24.86s，测试误把既有员工登录响应当统一data信封，按实际根access_token修正。106为4 failed25.64s/15条jose警告，三个缺项已被正确校验拒绝但测试误期待管理端缓存头为no-store；实际private, no-store，改按员工/客户路由分别精确断言。另shipping_fee=null真实编辑接口422，分离为正确API拒绝证明及初次未知费用独立两参数，不改业务代码。107为2 passed/3 failed26.45s/34警告，三类缺项已走完修复发布下载，仅备注字段断言误读commercial_header；改读取实际快照顶层remark。

108最终全新隔离联合验证：pytest tests/portal_mysql/test_mysql_incomplete_pi_http.py tests/portal_mysql/test_mysql_approval_repair.py tests/portal_mysql/test_mysql_zero_fees.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本次拥有mysqld8.0.46、portal-mysql-run-108与portal-incomplete-pi-108。7 passed in26.74s，34条第三方jose utcnow弃用警告；MySQL Shutdown complete。联合结果包括真实发票validate_invoice缺项失败、原子回滚、修复提案重新确认后唯一建票的既有T60回归，以及已有未知费用/显式零费用领域链路，未把旧测试记录假作本轮执行。

独立代理既有限额未解除，未取得新的独立代理复核；主线程依completion-checklist另轮源码自查：InvoiceUpdate拒null费用；真实编辑事务提交触发版本/撤回保护；adapter和后续pi_revision_source调用实际validate_invoice并逐项校验费用；publish必须当前active/accepted/document一致并重新校验；下载先capture再渲染后二次capture；失败回滚不会新留修订/回执/outbox。未发现具体缺陷，不称独立代理通过，也不以渲染探针替代生产或PDF视觉验收。

T42当前契约完整，当前50完整/14部分；剩余T19/T36/T47/T48/T49/T50/T51/T52/T53/T54/T56/T61/T62/T64。没有业务实现或前端变更；未连接生产、发真实邮件、提交、推送、合并或部署，整体实现目标仍未完成并继续。
T42收尾：check_conventions.py --strict、git diff --check均通过（仅既有LF/CRLF提示），verify_portal_docs.py通过（8文档/24本地链接锚点/3 JSON/64规格/17设计发现）。09:59北京时间git_sweep --no-fetch完成，仅本地快照；主目录0修改/1未跟踪，本分支42修改/37未跟踪统计项、无upstream。未重复无关前端构建；没有提交、推送、合并或发布。

## T56持久提案跨新进程与北京时间跨日（2026-10-04）

新增proposal_process_worker.py与test_mysql_proposal_process.py。十二参数覆盖新接受/已接受后审批 × 到期前一秒/到期当秒/到期后一秒 × UTC/Los Angeles默认服务器时区。父进程通过实际submit与proposal服务将付款条件、expires_at和内容hash提交至隔离MySQL；审批场景先实际客户接受。提案签发设北京时间23:59:59、有效24小时，到期后一秒恰为次日00:00:00。

每参数spawn独立Python解释器，重新导入实际服务及模型，使用新SQLAlchemy Engine/Session回读已提交订单、行与修订，实际revision_evidence.verify校验hash。子进程PID不同于父进程，回读付款快照prepaid/Payment before shipment/100.00、expires_at、content_hash和接受人逐项等于数据库证据，再实际decide或approve并提交/回滚。到期前动作成功且非回放；审批实际创建唯一128.00 PI。到期当秒和之后精确PROPOSAL_EXPIRED/409，十二类业务表所有字段与基线相同，无PI或新回执/审计/outbox，原接受证据和提案到期时间没有被延长。成功接受准确记录该北京时间和原账号，成功审批不重写已接受修订。

时钟通过app.core.time.datetime的确定性测试实现注入固定UTC瞬间；实际beijing_now仍显式使用Asia/Shanghai，默认无时区调用则模拟UTC或America/Los_Angeles。子进程观测默认服务器日期与跨日北京时间不同。没有改变Windows系统时间/时区，不能据此关闭T52全部请求号/日期/审计或实际异地部署证明。为排除认证过期假阳性，仅在测试拥有库将合成PortalSession有效期延至提案到期后三天；不改生产会话政策，不将此测试当成24小时真实客户登录证明。

109执行pytest tests/portal_mysql/test_mysql_proposal_process.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定本次拥有mysqld8.0.46、portal-mysql-run-109与portal-proposal-process-109。12 passed in45.50s，MySQL日志Shutdown complete。隔离数据库凭据只通过进程IPC传递，不写文件/日志；工作进程重新装载拥有库连接守卫，不读取backend/.env。库存、上游schema/价源及PI编号仍为已注明的合成边界，门户172/173迁移真实执行，不构成完整历史迁移/真实SMTP/真实PDF或浏览器证明。

独立审查代理既有限额仍未解除，本轮未取得新的独立代理复核；主线程另轮核对源码：proposal写入固定付款与到期且hash包含二者；decide与approve先实时鉴权/回执恢复再做新命令校验；revalidate在库存/定价检查前后均检查持久expires_at，审批建票后再复查并同事务提交；拒绝回滚保留原确认。未发现具体缺陷，不称独立代理通过。T56当前契约完整；当前51完整/13部分，剩余T19/T36/T47/T48/T49/T50/T51/T52/T53/T54/T61/T62/T64。整体实现目标仍未完成。当前用户所需详细开发文档与设计对抗审查已经落地，设计修订与实施/生产验收仍分别管理；未连接生产、发送真实邮件、提交、推送、合并或部署。
T56收尾：check_conventions.py --strict与git diff --check均exit 0（仅既有LF/CRLF提示）；verify_portal_docs.py通过，8篇/24处本地链接锚点/3 JSON/64验收规格/17设计发现。10:09北京时间git_sweep --no-fetch首次因沙箱阻止worktree/tmp/git-sweep.html写入而exit 1；仅针对本地看板请求窄范围提权后同命令exit 0。结果为本地快照，主目录0修改/1未跟踪，本分支42修改/37未跟踪统计项、无upstream。未取远端最新状态、未提交/推送/合并/发布。纯测试和交接文档变化，未重复无关前端构建。

## T19真实SQL载荷、存储文本与I07规范化修复（2026-10-04）

本轮上轮分类为进展：T56新增新进程/跨日真实MySQL证据并完成交接，本轮继续未完整T19。新增backend/tests/portal_mysql/test_mysql_input_safety.py与frontend/tests/portalLiveInputSafety.browser.mjs；局部修复app/portal/mapping._label，扩充test_security_mapping.py并同步API/审查文档。

I07实际缺陷：原校验先查半角<>再NFKC，全角＜img…＞和小型﹤script﹥会在发布值中变成标签；只读函数调用回出半角标签，111真实映射预览HTTP返回200而预期422。当前Vue文本输出和PDF转义仍阻止执行，不将该契约绕过夸大为已证实存储型XSS。修复检查规范化后尖括号与长度，原控制字符检查不移除。13项新增回归覆盖model/color/sku显示名与customer_sku × 全角/小型括号/规范化展开超限，以及合法全角拉丁、中文、引号、&和作为文字的公式前缀。没有改权限、标准SKU、金额或历史快照。

SQL测试真实员工密码/JWT、客户Cookie/Origin/CSRF、FastAPI路由与隔离MySQL：客户目录、管理目录、客户列表、所属业务员提案目录四个查询，各有可找到合法记录的正向对照；六个载荷（OR1=1、引号/注释、DROP文本、%、_、反斜线）均准确空列表。执行器监听确认恶意文本不进入SQL语句且OR载荷实际在绑定参数中；客户目录外的非空未授权哨兵仍404。三类对象ID载荷422/INVALID_INPUT，错误不回显原载荷、nosniff有效。半角img/svg/script、全角img/script五类别名分别直接preview/publish均422；十二业务表及CatalogItem/CustomerAccess/MappingRevision/CustomerAccount/Quote全字段不变，排除拒绝后的审计/事件/报价失效残留。P0两组门户路由均无CSV/export入口；不把本证据当成未来P1 CSV公式防护实现。

浏览器真实Chrome：管理端实际管理员密码登录、映射UI编辑→非法预览拒绝且发布禁用→引号/&/javascript:字面货号合法预览和发布；客户使用真实OTP服务创建的会话（通过stdin送入Node并设置__Host Secure Cookie，不替代登录页面规格），经本地HTTPS可信代理读取、选品、输入HTML公司/联系人/地址/备注和SQL city/remark及公式PO→实际报价/提交→提案→客户UI接受；订单处理另用真实所属业务员登录/JWT，管理员读取没有被当作业务员代办。实际中文审核UI建票，审计reason按文字显示；客户下载真实ReportLab PI。12处页面检查包含公司管理、非法映射输入、预览差异、目录、商品弹窗、购物车/服务器复核、请求、员工完整快照、提案差异、最终审核、审计和发布后请求。隔离无凭据对照页img/svg各实际执行，计2；所有应用页counter0、执行属性/javascript链接DOM0、/xss-probe请求0、pageerror0。无API响应拦截或认证/权限替身。

实际MySQL回读订单PO、地址、备注和接受行customer_display_json均精确保留合成输入；唯一PI128.00、业务员为实际owner、行成交单价27及原标准SKU不变，唯一ReceiptIntent/Conversion/Publication。实际PDF解析确认全部载荷为字面文字；无OpenAction、JavaScript Names、AA或链接注释。字体使用本机Arial验证ASCII载荷，不作为正式CJK字体或PDF视觉/T50验收；客户HTTPS采用短期自签测试证书、受信回环代理并改写X-Real-IP，员工入口仅本机HTTP，不宣称生产域名/TLS/代理联调。库仍为薄上游加真实门户172/173迁移，库存/上游flags与PI编号为注明的合成边界，不扩为全历史迁移或真实经营配置。

真实运行记录：110为2 failed29.94s，测试误用管理员处理owner请求、并误期待HTML映射可接受；改为实际owner和纯文本拒绝证明。111为2 failed29.01s/36条jose警告，一项实际I07规范化缺陷、一项测试误期待发布200而API201。局部修复后112为1 passed/1 failed60.07s/39警告，浏览器直接连API缺可信代理X-Real-IP，被既有守卫拒绝；改复用本地HTTPS ingress，不放宽生产守卫。113为1 passed/1 failed36.98s/51警告，全业务链已完成但测试addInitScript向opaque文档写sessionStorage产生3错误；限定仅员工实际origin写welcome测试标志，未过滤错误或削弱断言。114为1 passed/1 failed36.97s/51警告，浏览器12检查和实际PDF已成功，回读误用API字段display_snapshot而ORM列为customer_display_json；只改对应列名并保留内容比较。

115最终全新隔离命令pytest tests/portal_mysql/test_mysql_input_safety.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short，指定拥有的mysqld8.0.46、portal-mysql-run-115、portal-input-safety-115及显式Node/Playwright模块/Chrome路径：2 passed in37.03s，51条第三方jose utcnow弃用警告；MySQL Shutdown complete。截图input-audit.png/input-customer.png与实际input-safety.pdf保留在portal-input-safety-115对应测试子目录。112另进程执行pytest tests/portal/test_security_mapping.py tests/portal/test_mapping_service.py tests/portal/test_mapping_preview_conflicts.py tests/portal/test_pi_download.py --confcutdir=tests/portal -p no:cacheprovider -q --tb=short --basetemp=portal-input-unit-112：61 passed in6.09s，无MySQL连接；两套夹具未交叉加载。

当前源码双端Vite构建均成功，客户33模块1.27s、员工3330模块19.67s；员工仍有既有auth混合静态/动态import与大chunk警告，非本轮新增功能缺陷。未因测试反复重构或删除业务保护。独立代理既有限额未解除，本轮未取得新独立代理复核；主线程另轮核对_label调用覆盖、NFKC长度与控制字符、多语言正向、SQL参数/通配字面语义、Vue插值及安全链接、PI逐字段escape与授权二次捕获、所有失败无写残留。未发现遗留具体缺陷，不称独立代理通过。

T19在当前P0契约范围完整，I07已实现修复并验证；当前52完整/12部分，剩余T36/T47/T48/T49/T50/T51/T52/T53/T54/T61/T62/T64。完整历史迁移、正式B01–B07、真实SMTP/COS与双业务员双客户试点门禁仍独立存在，整体目标继续。无生产连接、真实发信、提交、推送、合并或部署。
T19收尾：check_conventions.py --strict和git diff --check均exit 0，仅既有LF/CRLF提示；verify_portal_docs.py通过（8文档/24本地链接锚点/3 JSON/64规格/17设计发现）。10:39北京时间git_sweep --no-fetch成功，仅本地快照；主目录0修改/1未跟踪，本任务分支42修改/38未跟踪统计项、无upstream。已确认110–114本次拥有MySQL日志Shutdown complete后清理各data/temp与失败浏览器basetemp，保留mysql.log及115最终截图/PDF/隔离数据；115短期自签测试key/crt用完清除。未清理他人路径，未提交、推送、合并或部署。
## 客户门户 v1.3 开发文档与独立对抗审查交付（2026-10-04 10:53）

本轮用户范围是“按以上方案生成详细的开发文档并进行对抗性审查”，未继续通知worker实现。8篇开发文档位于docs/requirements/2026-09-30-customer-order-portal，入口README.md已更新v1.3，包含架构/权限、模型/迁移、API、交易/PI、双端UI、工作包/64项验收及审查记录。

两位新独立只读审查者共同确认F18/P2：T47要求映射outbox恢复，原事件模型/消费者/API却仅定义订单；补mapping_published/mapping_mail、发布同事务入队、当前成员/修订校验、access范围追踪恢复和UI契约，没有删减验收或将其宣称已实现。交易审查确认F19/P2：后续提案/客户拒绝缺稳定命令身份；02/03/04沿现有服务明确pi_proposed用原If-Match、reject_proposal/pi_rejected用revision、完整body/reason入摘要，扩充T59。两位审查者均定向复核闭环，无新增具体P1/P2；累计19项设计发现（5P1/14P2）文档修订。

另统一最终prepare提交为通知授权时点，承认已授权在途窗口，SMTP仍在事务外；T36/T61覆盖两个顺序。proposal/pi_amendment的到期秒精度与hash规则统一到quote，并补T56。v1.3新增断言不得自动继承此前v1.2的完整判定；本轮不运行实现测试或重计覆盖，后续应重新核对T36/T47/T56/T59/T61。之前实现证据仍为对应批次历史记录；原通知/业务代码本轮未改。

实际文档验证8篇/24链接锚点/3JSON/64规格/19发现通过；strict和diff均exit 0，仅既有LF/CRLF提示。10:53 git_sweep --no-fetch成功，为本地快照：主目录0修改/1未跟踪，任务分支42修改/38未跟踪统计项、无upstream。没有获取远端最新状态、生产连接/迁移、真实发信、提交/push/merge或部署。本轮文档与设计审查已交付；整体实施与完整历史迁移、B01–B07、真实SMTP/COS、正式试点和发布仍未完成。

## 客户门户 v1.3 详细开发文档本次交付复核（2026-10-04 11:28）

本次按用户“按以上方案生成详细的开发文档并进行对抗性审查”收口；入口为docs/requirements/2026-09-30-customer-order-portal/README.md。两位独立只读审查者重新核对8篇目标契约，分别确认身份/范围/映射/通知/UI恢复与金额/库存/PI/幂等/恢复无剩余具体P1/P2文档矛盾。F18/F19在文档层闭环；累计19项设计发现（5P1/14P2），不新增或重复计数。

本次实际静态检查：8篇文档/24处链接锚点/3JSON/64规格/19发现通过；check_conventions.py --strict与git diff --check通过，仅既有LF/CRLF提示。本次未继续产品开发或运行业务验收，不改写历史覆盖判定，不关闭T47等剩余验收或生产门禁。已有任务分支实现及未交接的测试工作保留待后续核验，不能从本次文档审查推断已验收；整体开发目标仍未完成。没有连接生产、迁移、真实发信、提交、推送、合并或部署。
本次收尾：11:29北京时间git_sweep.py --no-fetch成功，仅本地快照；主目录0修改/1未跟踪，本任务分支42修改/39未跟踪统计项、无upstream。未获取远端最新状态。

## F18映射通知本地实现与I08对抗修复（2026-10-04 11:42）

上轮目标分类为进展：v1.3文档独立复核及交付记录已落地。本轮继续整体开发目标，收尾此前未交接的映射通知实现，不进行生产迁移/发布。mapping_service.publish在不可变MappingRevision、版本、旧报价失效和审计的同一事务追加mapping_published，稳定revision UUID键；事件入队失败整事务回滚。新mapping_notifications模块按当前有效已验证成员展开唯一mapping_mail，绑定site/access/source/revision，重查当前映射与实际客户授权，旧修订取消。仅发显示名称更新摘要与登录collection链接，无别名、价格、地址或能力凭据；共享有界租约/退避，发送器在DB事务提交并关闭后调用。无需新增表或迁移。

新增GET customers/{access_id}/mapping/notifications与POST同范围/{event_id}/retry，类型/aggregate/payload/revision/source约束先于SQL分页和count；实时mapping读写及客户范围，不沿用订单read_all扩大授权。恢复抽取既有重排逻辑，固定event/UUID key/fingerprint/reason，回执用access_id，原成功回放不再次排队；回滚保持dead和尝试数、审计/回执均无残留，通知不改变映射/订单/PI。worker投递前再次检查成员启停/邮箱验证。

I08/P2独立实现审查发现：人工恢复仅验证源/修订，损坏成员引用、recipient_kind或稳定子键能先写恢复记录，prepare才拒绝。无已证实越权投递。现recipient_for供恢复和prepare共用，检查数字串长度/BIGINT范围、实际site/access、类型与稳定子键。反例覆盖不存在、非法/超界/5000位标识、错误类型/键、真实存在同站另一客户与另一站客户（同时伪造匹配稳定键）；拒绝后dead/attempt8/回执/审计不变。F系列设计发现仍19项，I08为实现发现。

管理映射页新增查看映射通知，NotificationDialog/notificationDelivery/command显式区分access_id与request_id回执，权限按钮分别使用mapping/order指令。未知结果冻结原命令，只原键原body重放；403隐藏详情但保留未知命令，错误scope回执不能解锁。嵌套子弹窗同步busy到父级locked，保护编辑、发布、关闭/Esc、load/重新读取、路由离开和beforeunload，合法回执后保留实际未发布草稿。已有主题和响应式表格沿用，不新增样式/动效体系；Emil两个已知本地路径未找到，本轮不制造替代Skill或新的动画。

两位独立只读实现审查者完成定向复核：此前收件人P2和父级卸载验证点已补齐，未发现剩余具体P1/P2；审查者没有执行测试。主线程源码调用点搜索发现catalog/授权/预览/quote/reorder也使用mapping.publish，因此扩大到实际调用方回归，没有把窄通知测试当全业务证明。

实际验证（独立进程，不交叉加载SQLite/MySQL夹具）：
- 126最终执行pytest tests/portal/test_mapping_notifications.py test_notification_worker.py test_notification_admin.py test_mapping_service.py test_catalog_access_service.py test_catalog_admin.py test_catalog.py test_customer_preview.py test_mapping_preview_conflicts.py test_quotes.py test_reorder_and_comparison.py（后十项同tests/portal前缀），--confcutdir=tests/portal -p no:cacheprovider -q --tb=short --basetemp=D:/commission-system/tmp/portal-mapping-callers-126：144 passed in15.15s。禁止MySQL/真实SMTP；薄上游SQLite且员工授权部分替身，不代表真实JWT。124较窄四模块62 passed7.97s，125未拆同站/跨站前143 passed15.38s，三批存在重叠不可相加。
- 123真实隔离MySQL：pytest tests/portal_mysql/test_mysql_mapping_notifications.py tests/portal_mysql/test_mysql_mapping_race.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short；显式本地mysqld8.0.46、新portal-mysql-run-123及portal-mapping-mysql-123：5 passed22.42s。真实独立连接及performance_schema等待，claim commit/rollback两顺序、展开唯一子事件、JSON范围查询、恢复回滚/回执/原因冲突，以及原发布两竞争。真实RBAC/绑定服务使用root管理员，非员工登录HTTP证明；薄上游+真实172/173 DDL，注入sender禁止真实SMTP。MySQL日志Shutdown complete已核对。不是跨进程或全历史迁移证明。
- frontend/tests/portal*.test.mjs经显式Node --test：43 passed192.52ms，覆盖共享命令及mapping/order回执交叉拒绝。
- 当前中文前端Vite build成功，3330模块/16.06s；既有auth混合import/大chunk警告保留。最新dist本地3211静态preview供真实Chrome模拟API运行：portalMappingNotifications.browser.mjs 12场景/4模拟POST；portalNotifications.browser.mjs 10场景/3POST；portalMapping.browser.mjs 12组场景/9调用，均pass且pageerror为空。包含1440/390/320、Esc与beforeunload实际浏览器提示、父reload/编辑禁用、权限拒绝/错scope/原键原body恢复、未发布草稿不丢、只读mapping与原订单回归。截图portal-mapping-notification-ui-123下1440/390/320三个文件与实际视口对应，并人工查看桌面/390。模拟API不证明真实身份、邮件或端到端后台。preview16302已Ctrl+C且终态，浏览器各自finally关闭。

本批失败定位：117共享requeue抽取后残留actor变量为真实代码错误，改使用已鉴权actor_id；另固定测试时钟排队顺序。118污染pending事件抢占目标为夹具问题，改dead。119先55、120后61相关测试通过。121 MySQL2失败3通过为发布时钟未随worker固定且DATETIME截秒/舍入，补测试mapping_service时钟，122后5通过22.53s，不改生产算法。123新增foreign_member夹具缺contact_name，1失败61通过，补必填字段后通过；124第一次pytest参数拼写错误、123第一次MySQL文件名误用复数均未运行断言/未启动数据库，核对后执行正确命令。浏览器旧dev冷载入失败转最新dist静态preview，未延长断言或屏蔽pageerror。新浏览器截图旧122“390”实际320，123修正按循环width命名，不以旧文件证明390。

API参考、模型/恢复契约、双端UI说明、README及I08审查记录和隔离MySQL说明已同步。当前strict、diff、8篇/24链接锚点/3JSON/64规格/19发现静态校验通过。没有因为本批证明而关闭T47整条：邀请/订单/映射跨进程崩溃恢复与丢发送回执、完整撤权顺序及真实SMTP仍需补证；v1.3扩充T56/T59需重审新断言，历史52完整/12部分不能自动作为当前数量。整体目标仍未完成，下一步优先真实新进程通知恢复，随后UI/缓存/跨日/回退及剩余门禁。

清理：确认121拥有MySQL Shutdown complete后清理其data/temp，保留mysql.log/runtime.json；清除123失败SQLite basetemp和120冷载入失败UI目录、过时生成脚本与测试副本。最终122/123数据库证据、123截图/构建日志、最终126测试材料及仓库测试均保留，不清理他人路径。未连接生产、真实发信、提交、推送、合并或部署。
F18收尾：11:43北京时间git_sweep --no-fetch成功，仅本地快照；主目录0修改/1未跟踪，本任务分支42修改/39未跟踪统计项、无upstream。没有获取远端最新状态或执行远端动作。

## 开发文档交付与通知验收证据续接记录（2026-10-04 12:13）

当前用户请求为详细开发文档与对抗性审查。本次以8篇v1.3文档交付收口，未继续产品实现或补写新的业务测试。此前未交接的通知测试保留，并核验对应测试进程已终止；下列为此前实际运行记录，不能视为本次重新执行或相加得到新的总覆盖数。

- 129：pytest tests/portal_mysql/test_mysql_mapping_notifications.py tests/portal_mysql/test_mysql_mapping_race.py tests/portal_mysql/test_mysql_notification_process.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short -x；拥有的portal-mysql-run-129和portal-notification-process-129。16 passed in68.97s。其中11个实际spawn情景涵盖mapping/order/invitation/auth_code发送接受后终止旧进程、新进程119秒前不抢租约及121秒恢复、稳定Message-ID、撤销/过期/旧修订取消；新租约仍sending时拒绝旧lease finish，31类业务/权限模型全字段不变。注入sender确认不持事务，不连接真实SMTP。独立审查提出的队列污染和弱旧lease断言已修正：排空测试拥有的旧队列并核对源/子身份，恢复时阻塞新发送器验证旧lease拒绝。127首次因RateBucket无id导致快照失败，按真实主键排序修正；128为修正审查意见前的11 passed，不当作最新证明。129的5个旧测试与123重叠，不相加。
- 132：pytest tests/portal_mysql/test_mysql_mapping_notifications_http.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short；拥有的portal-mysql-run-132。1 passed in22.62s，16条既有jose utcnow弃用警告。两名真实密码登录/JWT非管理员业务员各有可读通知正向对照，互访404；read_all不扩大mapping范围；跨类型/异修订/未知event与access恢复拒绝，31模型及outbox全字段无拒绝残留。真实角色关联撤销后旧JWT/原成功命令403，再撤read后读取403。ctx.admin仅用于准备授权数据；ASGI测试不证明浏览器/TCP/TLS，也不证明管理员撤权入口并发。130/131失败分别为测试事件缺next_attempt_at和员工夹具缺real_name，依实际模型/API补齐，未改业务保护；最初Copy路径错误未启动数据库，随后采用绝对目标。
- 133：pytest tests/portal/test_mapping_notifications.py tests/portal/test_notification_worker.py tests/portal/test_mail_worker.py tests/portal/test_notification_admin.py --confcutdir=tests/portal -p no:cacheprovider -q --tb=short --basetemp=D:/commission-system/tmp/portal-notification-unit-133；64 passed in8.30s，进程终态exit0已确认。SQLite局部通知回归，与126存在重叠，不相加；没有真实SMTP或MySQL行锁证明。

新测试源码为backend/tests/portal_mysql/notification_process_worker.py、test_mysql_notification_process.py和test_mysql_mapping_notifications_http.py。MySQL129/132日志均Shutdown complete；保持最终数据库和日志证据，不读取生产.env、不连接生产、不发送真实邮件。独立HTTP审查未发现具体假阳性；独立T47证据审查仍指出多成员并发展开缺口：现测试为单成员或并发claim后串行prepare，需要两个有效成员与两个实际事务竞争同一源/lease prepare，证明各一子事件与原子展开；此项尚未实施，不关闭T47。直接撤销角色关联不替代真实管理员入口并发验证，生产SMTP另属上线门禁。

当前8篇文档/24链接锚点/3JSON/64规格/19设计发现静态检查通过，check_conventions.py --strict和git diff --check通过，仅既有LF/CRLF提示。设计修订闭环与实现完整验收分别记录，v1.3新增T56/T59断言仍需复核，不重用历史52完整/12部分计数。整体开发目标仍未完成；本次文档交付不标记整体目标完成、暂停或阻塞。没有提交、push、merge、部署或生产迁移。
本次最终核验与12:14北京时间git_sweep --no-fetch均exit0；巡检仅本地快照，主目录0修改/1未跟踪，本任务分支42修改/39未跟踪统计项、无upstream。未取远端最新状态或执行远端写入。

## T47双成员通知并发展开与原子回滚（2026-10-04）

上轮目标分类为进展：v1.3开发文档交付、静态核验及129/132/133未交接证据记录已落地。本轮继续整体开发目标，优先填补独立审查指出的T47最后本地证据缺口。仅新增测试与说明，不改产品逻辑或新增表/迁移。

在backend/tests/portal_mysql/test_mysql_mapping_notifications.py新增test_two_member_expansion_is_atomic_and_competing_prepare_is_unique的commit_first True/False两参数。使用真实已验证第二账号/同access活跃成员，实际claim并commit源事件。真实SQLAlchemy before_insert在第二mapping_mail时注入故障，SQL连接确认第一子事件已实际INSERT；rollback后所有outbox字段及31类业务/权限模型均与基线相等，源仍sending/原lease/attempt1且没有子事件。恢复后两个真实Session竞争同source/lease的worker.prepare，performance_schema证明第二连接实际InnoDB等待，第一commit时第二不重复、第一rollback时第二完整重建。精确断言两个成员各一稳定键与完整payload，源expanded清lease，outbox只新增2行，业务/版本不变。实际worker注入sender两次sent后idle，收件人/Message-ID分别匹配两成员/子事件；没有复制客户别名或真实SMTP。

实际134命令：pytest tests/portal_mysql/test_mysql_mapping_notifications.py tests/portal_mysql/test_mysql_mapping_race.py tests/portal_mysql/test_mysql_notification_process.py tests/portal_mysql/test_mysql_mapping_notifications_http.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short -x；显式本地mysqld8.0.46、全新portal-mysql-run-134及portal-notification-fanout-134。19 passed in71.37s，16条既有jose utcnow弃用警告，exit0。与129/132测试有重叠，不相加。MySQL日志Shutdown complete确认，测试未读取backend/.env/连接生产/真实发信。薄上游夹具+真实门户172/173 DDL仍不代表全历史迁移。

独立T47审查只读核对新增反例，未发现假阳性；确认实际联合通过后当前v1.3 T47本地契约完整。此前12:13记录的多成员竞争缺口现已闭环；不新增F/I编号。真实SMTP、部署配置、正式经营数据与试点仍为独立门禁。v1.3新增T56秒精度三类回读和T59后续提案/拒绝命令断言正在重新审计，旧52完整/12部分计数不自动继承。整体实现未完成，下一步补v1.3新增证据，再推进通知撤权提交顺序、UI/缓存/跨日/部署回退及剩余独立验收。没有提交、push、merge、部署或生产迁移。
## T56 v1.3三类微秒快照、MySQL和新进程回读（2026-10-04）

独立证据审查重新核对v1.3 T56/T59：109旧12参数仅整秒proposal创建；097旧恢复仅accept/approve，不能继承v1.3新增断言。本轮先补T56，T59仍部分。未改产品逻辑或存储精度，仅新增test_mysql_snapshot_precision.py与proposal_process_worker.py只读read_snapshots分支。

新增UTC/Los_Angeles两参数，在实际app.core.time.datetime注入654321微秒但不修改宿主时间/时区；实际quote创建→submit→完整proposal→accept→approve唯一PI→真实Invoice修改remark并commit触发版本→pi_amendment创建。期望expires_at明确为原微秒瞬间加有效期后的截秒值，hash取真实返回回执；新Session读取提交MySQL的三类对象、实际quote_service.view与revision_evidence.verify重新核验。不同PID spawn解释器使用新Engine/Session重导入模型及真实服务，在北京时间次日00:00:01、默认UTC/LA时钟日期不同的条件下重读相同三类hash/付款/到期证据。31类业务/权限模型及全部outbox字段在读取前后不变，排除读时修正数据。报价在跨日时可以自然过期，但证据仍正确；新只读分支不替代既有接受/审批到期拒绝场景。

实际135命令：pytest tests/portal_mysql/test_mysql_snapshot_precision.py tests/portal_mysql/test_mysql_proposal_process.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short -x；显式拥有mysqld8.0.46、全新portal-mysql-run-135及portal-snapshot-precision-135。14 passed in49.85s，exit0；MySQL Shutdown complete已确认。包含原12参数到期前/当秒/之后新进程接受与审批及新2参数三类精度；不与109相加。工作进程连接守卫及不读.env保护保留，IPC传递隔离凭据，不输出原始凭据或能力token。

独立只读审查确认新增场景具有区分力、补足当前v1.3 T56，结合135实际联合通过判定T56当前隔离契约完整；审查者未代替主线程执行测试。确定性应用时区、合成库存/编号、薄上游+真实172/173 DDL仍不是实际宿主切换、全部时间规格、全历史迁移或生产证明。没有新增F/I产品缺陷，不重计过时52完整/12部分。

下一步最小T59缺口：pi-proposals、首次客户reject与PI客户reject真实MySQL HTTP成功后丢响应，原If-Match/原body回放；同PI版本新If-Match到期重提；拒绝同/异reason和两个合法会员真实竞争保持首actor。已有accept/approve证明保留，无需为补充重跑全部矩阵。随后继续T36/T61通知最终prepare与撤权两提交顺序以及UI/缓存/跨日/回退等剩余验收，整体目标仍未完成。未连接生产、真实发信、提交/push/merge、迁移或部署。

清理：验证本次拥有127/130/131 MySQL Shutdown complete后仅删除各data/temp，保留mysql.log/runtime.json；仓库测试已落地，清除scratch中三份过时通知测试副本。保留129/132/134/135最终隔离证据、既有133单元证据及测试源码，不清理他人文件。
本批最终strict、git diff --check及文档校验全部exit0（8篇/24链接锚点/3JSON/64规格/19发现，仅既有LF/CRLF提示）。12:26北京时间git_sweep --no-fetch exit0，仅本地快照；主目录0修改/1未跟踪，本任务分支42修改/39未跟踪统计项、无upstream。没有获取远端最新状态。无前端或产品行为修改，不重复无关构建；本轮所有拥有测试进程已终止。

## T59 v1.3后续PI提案与两类拒绝的命令恢复（2026-10-04）

上轮分类为进展：T47多成员展开和T56三类微秒快照完成本地规格证据。本轮继续T59新断言，新增backend/tests/portal_mysql/test_mysql_followup_recovery.py（271行），未改产品逻辑、认证限流、表或迁移。

21新场景：pi-proposals/reject_proposal/pi_rejected × expiry/replacement × price/inventory503共12；两种拒绝 × 两会员首操作顺序 × 第一事务commit/rollback共8；同一PI版本到期后新If-Match合法重提1。复用真实employee登录JWT、真实客户Cookie/Origin/CSRF和LoseResponse：实际路由提交成功200后丢响应，仅原body/If-Match重放。精确503 fresh quote及调用探针证明故障注入生效；回放不查询源、异reason409，12业务模型全字段（含receipt/audit/outbox）不变。旧revision全字段不变；原invoice/item/receiptIntent/conversion/publication集合不变，不增PI，不复活旧修订。替换首次提案后当前awaiting_customer及无接受；替换PI提案后当前pending_customer及无接受。

双会员经实际invite→activation OTP verify获得不同账号/会话；compete用实际Session、独立连接和performance_schema InnoDB等待，第一commit则另一回放、第一rollback则另一新成功；两种会员先后顺序均唯一首actor/receipt/event/audit，拒绝不改原修订或PI。补同PI文档到期场景：当前提案有效时新If-Match拒409；实际模块时钟推进到expires+1，注入合成库存观察同一瞬间，新If-Match/同body生成新revision、新到期，document_version不变。旧、新命令各自回放原回执，current仍新revision，无再查询库存、原旧expires/hash/字段不延长。时钟仅覆盖提案到期和库存边界，真实认证仍按当前时钟；不是24小时生产登录或宿主时钟推进证明。

实际执行：
- 136同库联合test_mysql_followup_recovery.py与test_mysql_decision_recovery.py：22 passed/17条既有jose弃用警告、1 setup error in33.68s，exit1。新21完整通过及旧第1通过；旧第2在trade auth.challenge触发正常RATE_LIMITED429。21个trade登录+8次第二会员activation已消耗共享IP29次，旧首30次，之后被真实每小时30次邮件限制拒绝。这是共享隔离夹具累计，不是业务恢复失败；未放宽限流、删桶、屏蔽错误或更改断言。保留失败记录，不称同库联合通过。
- 137全新拥有MySQL独立执行pytest tests/portal_mysql/test_mysql_followup_recovery.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short -x，显式mysqld8.0.46、portal-mysql-run-137与portal-followup-recovery-137：21 passed in32.70s，17条jose utcnow弃用警告，exit0。
- 138另一全新拥有MySQL独立执行pytest tests/portal_mysql/test_mysql_decision_recovery.py（同confcutdir/参数），portal-mysql-run-138与portal-decision-recovery-138：10 passed in28.35s，17条同依赖警告，exit0。原accept/approve到期/替换/价源503及PI A/B旧接受/发布回放回归通过，和历史097重叠不相加。两组分批真实验证，不冒称一次联合31通过。

所有MySQL日志Shutdown complete、进程终态确认；未读backend/.env或接生产/真实SMTP。ASGITransport仅本地丢响应，不证明公网或跨进程HTTP竞争；真实MySQL双连接、薄上游+真实172/173迁移、合成库存/编号边界保留。测试说明首个运行例子改为明确模块选择，记录共享IP限流导致必须隔离批次。

独立只读审查确认新增21覆盖v1.3 T59剩余断言、未发现具体假阳性；结合137/138实际通过，T59当前本地契约完整。没有新F/I产品缺陷，不重计历史总数；T36/T61最终prepare与撤权两提交顺序仍在独立定位最小补证范围，随后继续UI键盘/缓存/跨日/部署回退/PI编辑入口竞争和性能门禁。整体目标尚未完成，完整历史迁移、B01–B07、真实SMTP/COS、双业务员双客户试点及发布授权仍独立。没有提交、push、merge、生产迁移或部署。
本批收尾：strict、git diff --check与文档验证均exit0，8篇/24链接锚点/3JSON/64规格/19发现；仅既有LF/CRLF提示。12:38北京时间git_sweep --no-fetch exit0，仅本地快照：主目录0修改/1未跟踪，任务分支42修改/39未跟踪统计项、无upstream，没有远端写入。确认136拥有进程Shutdown complete后仅清其data/temp，保留失败log/runtime和137/138最终证据；无前端/产品行为修改，不重复无关构建。

独立T36/T61最小补证审查已返回：复用真实run_once，claim提交后和prepare提交前可控暂停，真实Session竞争authority并观察InnoDB等待；邀请/OTP/订单分别覆盖撤权先提交取消零sender/清密文，prepare先提交在无DB事务的sender等待中撤权可以成功提交、允许既授权在途发送且不增业务授权。T36转交需实际归属/门户复核服务：暂停时取消、完整转交重新启用后尚未prepare的员工通知解析新负责人，不能仅直接改字段。可选真实smtp_sender仅替换SMTP_SSL类并在connect/login/send_message检查Session无事务，避免真实供应商发信。已有129/134恢复/密文/回执丢失证据不需重复。本段记录下一步范围，尚未实现或执行，不据此关闭T36/T61。

## T36/T61最终prepare与撤权/转交真实竞争（2026-10-04）

上轮分类为进展：T59v1.3新增21及旧10独立库全部通过并交接。本轮新增backend/tests/portal_mysql/test_mysql_notification_authority.py（275行），补独立审查指出的T36/T61最小缺口；仅测试和说明修改，不改产品逻辑、表、迁移或真实认证规则。

九场景：invitation/auth_code/order/transfer × prepare_first False/True共8；实际复核转交重新启用后待发员工通知解析新负责人1。实际run_once使用测试Session子类，在真实claim commit后等待，实际prepare完成但提交前等待。独立Session的真实admin.update_account、employee_admin.update_user（自身commit）或customer.workflow.transfer_primary_owner竞争authority屏障，performance_schema证明另一连接实际InnoDB等待。撤权先提交后prepare取消、零SMTP、密文/lease清除；prepare先提交后实际smtp_sender在SMTP_SSL构造钩子阻塞，所有worker Session无事务；真实撤权可先commit，才继续实际SMTP登录/发送逻辑，既授权在途消息完成。没有锁持跨网络窗口，未伪造worker/prepare或跳鉴权。

SMTP_SSL为唯一传输替身，connect/login/send钩子检查两个worker Session均无事务，期望稳定Message-ID；业务通知不含价格/地址/token。真实发送配置为合成smtp-owned.invalid与合成凭据，没有真实SMTP网络。实际时钟固定到当前+2分钟整秒，只为避开同邮箱一分钟发送限制并匹配上游DATETIME精度，不改宿主时钟/真实限流。撤权后的31类业务/授权模型至投递完成全字段不变；原十类订单/发票/明细/回执/转换/发布等模型前后不变。失效事件最终cancelled/AUTHORIZATION_CHANGED或既授权sent，各attempt1、secret/key/lease清理，后续idle。

转交复核场景实际创建新业务员与继承的真实角色；上游workflow结束旧assignment并暂停portal，旧session撤销；binding_review最新指纹→ownership.transfer_customer显式选择待处理请求/history remove→admin.update_customer显式enabled。源和子通知尚pending未prepare，actual run_once/SMTP代码发送给new-representative@example.test，payload不持久化收件邮箱。订单servicing_user_id更新为新负责人，但sales_user_id_snapshot仍旧负责人；除交接允许字段外订单全字段、revision/line全字段及标准金额不变。旧session未恢复，HistoryGrant前后不变，发送不产生新的PI/授权/审计。

实际执行：
- 139初始邀请/OTP/员工停用两顺序六场景：6 passed in23.51s，exit0；不是扩展九场景证明，与141重叠不相加。
- 140扩展首次：3 passed/1 failed in22.62s，exit1，transfer准备新业务员username前缀+32hex超过真实50字符字段。仅缩短测试UUID后缀为16hex，总35字符，未改schema/业务/断言；记录为测试夹具错误，不新增产品缺陷。
- 141全新拥有MySQL实际pytest tests/portal_mysql/test_mysql_notification_authority.py --confcutdir=tests/portal_mysql -p no:cacheprovider -q --tb=short -x；显式本地mysqld8.0.46、portal-mysql-run-141与portal-notification-authority-141：9 passed in23.70s，exit0。139/140/141日志均Shutdown complete确认，worker/revoker线程已join，门在finally释放，无后台服务残留。

独立只读审查确认扩展场景补齐先前最小缺口，未发现具体假阳性或新增P1/P2；主线程141实际通过。结合129/134真实新进程恢复与133既有密文/AAD/过期/错误脱敏，T36/T61当前本地契约完整。真实SMTP供应商可达、经营配置、真实外部收件人、生产和全历史迁移仍独立，不借传输替身关闭。薄上游workflow表与真实172/173门户DDL边界保留，没有新增F/I编号。

v1.3已补的T47/T56/T59/T36/T61状态分别有当前记录，不重用旧52完整/12部分总数。剩余UI键盘/极端内容/可访问性T48/T50/T51、角色与PI缓存T49/T53、业务北京时间T52、隔离回退T54、共享PI编辑入口T62、锁超时/慢IO与统计T64仍继续，完整历史迁移与B01–B07/SMTP/COS/正式试点/发布仍为独立门禁。README入口改为中性的当前证据指针，避免已验证补充继续被误称待实现，又不维护第二份覆盖清单。没有提交、push、merge、生产迁移、真实发信或部署。
本批最终strict、git diff --check与文档静态核验均exit0，8篇/24链接锚点/3JSON/64规格/19发现，仅既有LF/CRLF提示。12:52北京时间git_sweep --no-fetch exit0，仅本地快照：主目录0修改/1未跟踪，任务分支42修改/39未跟踪统计项、无upstream，未取远端最新状态。确认140拥有MySQL Shutdown complete后清理其data/temp，保留log/runtime；141最终隔离证据及测试源码保留。无前端或业务行为修改，不重复无关构建。UI T48/T50/T51独立只读审查已有初步结论：仍为部分覆盖；既有三屏宽、图片失败、OTP/quote503恢复及unknown原命令恢复记录可保留。最小剩余为完整键盘业务路径、有效长色名/长地址按钮边界和字体回退、loading/无货/未知库存语义及代表性reduced-motion交互。详细复用路径待审查回报，未执行或关闭UI条目，不要求生产字体/CDN或实际屏幕阅读器播报。

## T48/T50/T51 客户完整键盘与最长内容证据、I09/I10修复（2026-10-04）

上轮分类为进展：当前v1.3八篇文档独立复核无剩余具体P1/P2契约矛盾，静态检查与13:01本地Git巡检通过；没有推进产品。本轮继续实现验收，新增frontend-portal/tests/customer-keyboard-stress.browser.mjs（实际构建UI+Chrome+截获API），只改LoginView、CollectionView及app.css处理实际复现的I09/I10，不改业务金额、提交接口或数据结构。

142发送验证码后activeElement失败：busy仍true时focus disabled code。Login发送/验证finally先busy=false，await nextTick后再次检查active再focus；错误提示按存在性关联，AUTH_FAILED标aria-invalid。143合法长映射（model/color128，customer_sku64）复现root1596>1440；修复product-caption overflow-wrap:anywhere、product-line首span min-width0、dialog-body minheight0/wrap。增加product-title关联及具名正文tabindex0，允许键盘读下方规格。没有整页overflow hidden掩盖问题。144超时是夹具Country精确label漏e.g.；145异常是夹具误读POST orders.delivery，真实提交只有quote_id/hash/PO/remark。保存成功quoteBody并精确assert真实提交契约，使用其delivery构造详情；没有为了测试改真实API。

实际146初步三宽通过6.25s；147新增PageDown真实scrollTop与弹窗input/button竖向边界后三宽通过6.71s。148进一步要求手机End滚动到底、错误OTP aria-invalid，三宽最终通过6.55s，每宽15次合成API调用、页面error0；重复不相加。证据D:/commission-system/tmp/portal-ui-148/result.json和12张PNG、3份合成PDF；保留142/143失败图及147既有回归证据。完整客户路径全用键盘：登录/错误恢复→三类库存目录→ArrowUp数量→必填拒绝不发quote→quote503保留200地址并聚焦alert→新quote聚焦review→Space确认→发送live状态→View request→提案Esc还原focus→Space明确接受→recording live→模拟员工建票/发布→真实下载事件。正式员工操作未测试，PDF为合成43字节文件，不能称真实PI渲染。手机号/地址等均合成。

长目录/弹窗/报价/订单三宽root无横溢出、主控件水平范围有效；open-dialog全部可见button/input还检查视口竖向边界，正文滚动后再核对。390正文scroll291+client667约等于scroll959，320为535+602约等于1138，允许1px取整，证明键盘已读到底；1440记录0/667/792未单独要求End，不扩大手机滚动断言。图片实际404后fallback；测试覆盖缺失font首选且CDP实际返回Segoe UI/glyph47/isCustomFontfalse，系统字体回退而非真实CDN中断。三个流程均reduced-motion，下载button transition0s。初步截图发现只scrollTop>0不足以证明读到底，因此148加强，不把147当完整底部可读证据。

当前产品构建33modules603ms exit0。受影响既有smoke/checkout/orders三Chrome脚本联合9.10s全部pass（D:/commission-system/tmp/portal-ui-147-regression）；Node六模块共56pass/0fail153ms。独立只读复核产品修订以及标题/正文Tab/PageDown/竖向边界断言未发现具体P1/P2回归或假阳性，不替代主线程实际执行。148 End/ARIA是其后加的更强断言；未再次叠加全量审查。Emil本地指定文件缺失，但frontend-portal README有官方源；本轮通过web只读补读官方emil-design-eng与review-animations/STANDARDS，按表记录Before/After/Why，120ms指针transform、键盘无motion、reduce、性能范围适用核对；无新动画/依赖。

客户侧T48/T50/T51这组证据已落地；三条整体仍部分，下一步最小剩余为中文管理端完整键盘发提案/审批、合法长客户映射与地址/错误/加载状态。再继续T49/T53缓存、T52北京时间、T54隔离回退、T62PI共享入口和T64性能。完整历史迁移、B01–B07、真实SMTP/COS、双业务员双客户试点及发布仍独立门禁。没有生产连接、真实发信、push/merge/部署，整体开发目标保持未完成。本批最终strict、git diff --check及文档静态检查均exit0（8篇/24链接锚点/3JSON/64规格/19设计发现；仅既有LF/CRLF提示）。13:21北京时间本地git_sweep --no-fetch完成；主目录0修改/1未跟踪、本任务42修改/39未跟踪统计项、无upstream，不代表远端最新状态。README更新I01–I10实现修订范围，F设计发现仍19。预览94912已通过Ctrl+C结束exit1，全部浏览器/Node测试进程终态；无残留预览，本轮scratch脚本已移除，保留仓库测试源码与实际失败/通过截图证据。没有产品新修改需重复构建或测试。
## 管理端键盘与极端内容、I11错误恢复（2026-10-04）

用户当前要求详细开发文档与对抗审查。8篇v1.3目标契约保留；本批收尾前一批已进行中的UI改动和审查反例，未扩大为新业务开发。独立权限/映射/通知/UI契约审查未发现剩余具体P1/P2文档矛盾。实现定向复核发现重复同文案不聚焦，实际Chrome153证实后修复。交易文档独立复核及最终静态结果另记下方。

I11：149首次非法费用不聚焦error summary；先nextTick watch error修订后151三宽通过，但独立审查提出25改26重复等值错误，153实际false。改为showError显式errorSequence递增、error赋值、nextTick检查disposed/代次/当前值后focus；所有非空错误入口使用，原清空/请求代次保留。费用/空原因ARIA关联，读取/核价/发送status及catalog loading文字/aria-busy配套补齐，uncertain不标busy。只改ReviewDialog/ProposalCatalogPicker，不改金额、API、状态机、权限和数据结构。

新增frontend/tests/portalKeyboardStress.browser.mjs纯键盘路径：详情→处理→radio→ArrowUp原4到6→授权目录添加MOQ3/step2的新4→费用/500原因/48h→客户端非法费用25及26两次聚焦且零预览API→source503焦点/200地址保留→成功预览377.75→Space显式确认→发送状态→模拟客户接受→核对标准101/201、102/202及352.75/211.65→审核→首请求abort结果未知→Esc/关闭冻结、busy不称loading→原If-Match3/body两次严格相等重试。表单交互只Tab/Shift+Tab、Enter/Space/方向键、keyboard.type，evaluate用于观察，不编程focus/check。

最终证据D:/commission-system/tmp/portal-staff-ui-154/result.json与6PNG：1440/390/320均pass，各14API/pageerror0，128连续model/color、64customerSKU、200地址、500reason、1000remark、80PO/100公司名。root/dialog无横溢出，input/textarea/footer水平inside及footer竖向inside；reducedMotion=reduce全路径。320截图实际查看，表格宽内容按组件内部横滚；不是所有内容无内部滚动。外网字体被阻断，但未CDP证明管理端字体选择，不扩张字体断言。API完全拦截，syntheticJWT/bootstrap、模拟客户接受和PI成功；第一approve abort不模拟真实数据库commit，原命令UI重试不证明唯一建票。此前真实JWT/MySQL证据独立保留。

夹具/执行问题：150把透明native checkbox判不可见，reach改wait attached且仍实际Tab到activeElement/Space；151通过。152编辑时把frontend cwd再拼frontend失败，后续实际运行仍是旧测试并pass，不能冒称新反例通过；ErrorActionPreference=Stop及正确相对路径补反例后153失败。154构建误加Vite --root退出1，修正frontend cwd直接build后155日志portal-staff-build-155.log exit0（3330modules/16.12s），已有auth混合导入及500k chunk提示保留。151/152重复不相加。测试金额/标准line_key夹具已按独立审查修正，并检查实际显示；最初错误保留证据，不改真实API配合夹具。

当前12项Node：node --test tests/portalCommand.test.mjs tests/portalProposalPreparation.test.mjs tests/portalPresentation.test.mjs，12pass/0fail130.62ms。既有portalProposalPreparation.browser.mjs与portalReview.browser.mjs联合exit0，准备14场景声明及审核4场景/4模拟写；不把场景数或模拟attempts计为独立后端测试。新增最终154exit0，screenshots/resultJSON保留。独立只读复核显式showError及重复错误断言未发现具体P1/P2，实际执行由主线程完成。

当前补齐员工发提案/审核键盘和最大内容这组证据，但T48/T50/T51全条仍部分（全站映射/PI后续页面、管理字体和其他状态对应证据未齐）；T49/T53缓存、T52时间、T54回退、T62PI入口与T64性能仍独立待验。没有产品新业务、数据库/迁移、生产连接、真实发信、commit/push/merge或部署。整体开发goal保持原状态，不将文档交付完成替代实现验收。
本次详细开发文档交付收口：两位独立审查者复核当前8篇v1.3均无剩余具体P1/P2，交易回退疑点按CLAUDE schema领先阻断及全入口PI版本保护排除。最终静态8篇/24链接锚点/3JSON/64规格/19发现、strict与git diff --check均exit0；13:45本地Git巡检exit0，主目录0修改/1未跟踪、任务42修改/40未跟踪，无upstream，未fetch。18951预览Ctrl+C终态exit1（主动停止），所有本批构建/浏览器/Node进程终态。当前文档交付完成与开发goal未完成分别记录；完整实施不以文档层闭环替代。删除scratch过时staff-keyboard-stress.browser.mjs副本，保留仓库测试源码及149/150/151/152/153/154失败/通过证据和构建日志。
## 原 PI 键盘与局部布局、I12–I14修订（2026-10-04）

上轮分类为progress：I11管理端重复错误修复和三宽新键盘证据落地，文档交付双人复核完成。继续实施goal，本轮核对剩余T48/T50/T51，新增frontend/tests/portalPiKeyboard.browser.mjs，产品只改PiReviewDialog.vue、PiDocument.vue、PortalOrders.vue，不改后端/表/迁移、价格、PI算法、权限或交易请求体。

真实反例：156空原因已确认提交后error未聚焦，1440当前/历史局部边界此前已通过；157指定390运行确认合法100 surcharge（portal Fees max100，现有Invoice允许128，未宣称覆盖最大128）DT右840.39。修订I12=显式每次showError序号/disposed/nextTick+空原因ARIA、读/发送文字status/实际busy、中文ERR_NETWORK；I13=PiDocument dt45%继承anywhere。阅读完整PI section具名region/tabindex0、focus-visible金色token，无新动画。158把本无tabindex的ElementPlus tabpanel当Tab目标失败；调整为实际条款region。159原生键盘滚动返回前即取几何失败，改waitForFunction观测body到达底部（3000ms上限），不程序滚动。160三宽15组通过，161增加完整propose/void body deepEqual和中文网络错焦点后同15组通过，重复不相加。

按明确T51补关闭返回焦点，162超时；163失败JSON证明active=body。I14因成功changed刷新卸载原触发按钮。PortalOrders reviewed返回已有openDetail Promise，piReviewed保存刷新Promise，closePiReview等待刷新/nextTick后检查disposed/currentfocussequence/原request/详情可见/invoice_created/无其他review，再对仍连接新piTrigger button focus；openPiReview、clearDetail和身份clearPrivateState失效旧恢复。164全部15（含成功/阻断/拒绝关闭返回focus）通过，但未覆盖父详情局部标签。独立审查指出同根父详情漏项，165实测1440返回drawer DT右1525.58。PortalOrders dt同时加45%和anywhere，按I13同根修复，不新增F设计发现。

最终产品构建D:/commission-system/tmp/portal-pi-build-166.log，3330modules/16.06s exit0；既有auth动态静态混合导入和chunk500k提示保留。最终新增166使用当前构建、真实Chrome，D:/commission-system/tmp/portal-pi-ui-166/result.json及9PNG：15scenario pass（1440/390/320 × propose/publish/void/blocked/denied），pageerror全零。全业务交互Tab、Enter/Space、方向键和keyboard.type，不用locator.click/fill/check/focus。model/color128、SKU64、地址两行各200、terms256、remark1000、reason500、company100、fee name100。读PI503聚焦并刷新恢复，两次空原因同错误均聚焦/零POST；有效期ArrowDown48、Space显式确认；三个动作first POST abort、unknown冻结/中文error聚焦/原body+If-Match8完全一致重试；publish含revision，propose/void严格完整body。当前/历史/客户提案tab实际ArrowRight/Left；所有mode关闭返回同一触发按钮，returned drawer DT/DD局部inside。

PageDown/End实际body读到底后按钮仍可达。propose记录1440 1060+759=1819，390 2288+759=3047，320 3342+723=4065；其他mode也逐条断言末端误差<=1px。Google Fonts实际路由阻断，12有效PI场景CDP当前商品ASCII strong实际Microsoft YaHei非custom/glyph258，证明本地阻断条件的系统字体回退。全路径reduced-motion，未新增动画/字体依赖；截图320当前PI网络错误已实际查看。没有模拟实际读屏或声称生产字体供应商故障。测试API完全截获、synthetic员工JWT/bootstrap、合成当前/历史/已接受PI；first abort不模拟真实DBcommit，PI命令成功回执不证明真实发布/作废、标准金额、唯一记录或MySQL事务。163保存整页DOM是合成数据，用于证明body焦点。

既有最终166-regression portalPiReview.browser.mjs（5mode/4模拟write）和portalOrders.browser.mjs（9声明场景/10请求）联合exit0；160/164重跑不相加。10项Node portalCommand.test.mjs+portalPresentation.test.mjs pass/0fail93.48ms，覆盖不可变原命令/迟到身份/PI状态展示，产品逻辑未改无需追加镜像测试。独立只读复核3产品文件无确定P1/P2回归，指出的完整body和父抽屉范围已经实际补验；主线程追加原request/关闭detail焦点保护，交易行为不变。测试/审查不互相代替。

当前T48/T50/T51仍部分：客户+首次提案/审核+原PI本组已补，映射/账号/配置等其他管理流程的完整键盘、最长内容/读写状态仍须分别对齐；不能以15组关闭全站UI。下一步可复用键盘 helper补映射/配置，并继续T49/T53迟到身份/PI缓存、T52北京跨日、T54隔离回退、T62全PI入口竞争和T64锁/慢IO性能。完整历史迁移、B01–B07真实经营配置、SMTP/COS、双客户双业务员试点及发布独立。没有生产连接/迁移、真实发信、commit/push/merge/部署，整体goal仍active。本批收尾：strict、git diff --check及文档静态核验均exit0（8篇/24链接锚点/3JSON/64规格/19设计发现；只保留既有LF/CRLF提示）。14:12北京时间git_sweep --no-fetch exit0，仅本地快照：主目录0修改/1未跟踪，本任务42修改/41未跟踪、无upstream，未fetch或远端写入。34899本地预览已Ctrl+C终态exit1（主动停止），所有拥有的构建/浏览器/Node运行已终态；无MySQL本批服务。仅清理scratch过时pi-keyboard.browser.mjs，保留仓库新测试和156/157/158/159/160/161/162/163/164/165/166实际失败/通过证据、截图、JSON、构建日志。README当前实现发现范围I01–I14，F设计发现仍19；当前工作可恢复，不把文档/局部UI通过当整体goal完成。
## 映射键盘 I15–I17 与 PDF 续体 I18（2026-10-04）

继续已 active 的实施 goal，并把本批结果同步到用户要求的详细开发文档和对抗审查。新测试 frontend/tests/portalMappingKeyboard.browser.mjs、frontend-portal/tests/pdf-scope.browser.mjs；产品只改 MappingDialog.vue、PortalCustomers.vue、OrdersView.vue，不改后端、表、迁移、价格、PI内容或权限规则。README 实施发现指针更新 I01–I18，F 设计发现仍19，v1.3目标契约与64规格保持。

映射167第一次超时是键盘 type('') 未清筛选夹具，改 Control+A/Backspace；168重复添加来源两次，第一次实际 alert 焦点 false，记 I15。每次 showError 递增 errorSequence，nextTick 后检查 disposed/序列/当前值；clear/unmount 取消过时聚焦，预览/恢复摘要也检查 generation/请求代次。读取/预览/发布文字 role=status、实际 busy；ERR_NETWORK 中文。I16 为源码证实的全局 cell nowrap/ellipsis 与完整确认矛盾，局部 normal/anywhere；未声称修订前浏览器复现。I17 源码与 I14 同根：changed 返回实际 loadDetail Promise，closeMapping 等刷新/nextTick，检查原 access/focusSequence/详情可见/其他窗口/按钮 connected；身份清理和详情关闭取消旧恢复。本项也未单独运行修订前失焦。

169当前员工构建3330模块16.03s exit0，portal-mapping-build-169.log（既有混合auth导入和chunk500k提示保留）。169三宽初步通过，171独立复核建议后补已valid且已勾选→编辑→确认消失/发布disabled→重新预览unchecked；最终 D:/commission-system/tmp/portal-mapping-ui-171/result.json 与6PNG，1440/390/320纯键盘均pass。21来源/23映射，model/color/SKU名称128、客户货号64、公司100。实际Tab、Enter/Space/方向键/type完成筛选分页、型号/颜色/SKU编辑、两次同错误聚焦、503保留值、色名冲突聚焦阻发布、有效预览确认失效、409重读、模拟发布已commit但abort、未知冻结/Esc不可关、GET恢复零新增写、最终成功刷新后触发按钮focus；各三次模拟publish。长cell非nowrap/宽度无内部文本横溢出，root/dialog/输入/footer边界；reduced-motion全程。已实际查看169 prepared-320截图，table内容有组件内滚动，不称全部无需滚动。没有管理字体CDP或实际读屏证明。169/171重叠不相加。

受影响既有映射/客户浏览器170先两脚本分别pass（9API、6模拟写）；第三误用 portalNotification.browser.mjs 不存在，整命令exit1，不能冒称联合全部pass。按现有文件名171跑 portalMappingNotifications.browser.mjs 与 portalNotifications.browser.mjs，分别12场景/4模拟写及10场景/3模拟写，exit0。19项Node portalMapping.test.mjs、portalCommand.test.mjs、portalNotification.test.mjs pass/0fail123.18ms。独立只读复核三映射文件未发现具体P1/P2，指出确认后编辑的浏览器缺口已补171；源码 deep synchronous watch 原已清预览，未新增产品bug。

I18独立源码审查指出窄续体窗口后，170真实旧构建 Chrome 在受控广播信号微任务注入下 actual marks=body-ready→scope-clear→blob-url→download-click；created1，卸载revoke1仍已触发旧PDF，exit1。保留 portal-pdf-scope-170/failure-continuation-race.json/PNG。OrdersView 在 await 前捕获真实 api.scopeVersion，await 后创建URL前比较；该比较至点击没有await，保留 active/sequence 导航保护及正常URL计时/卸载释放。受控channel只控制信号输送，真实 App/client clear和Vue卸载仍执行；不把微任务输送当真实跨标签时序证据。

客户171构建33模块805ms exit0，portal-pdf-build-171.log。171四场景pass；172加强 body-return 已发生及race body-return早于scope-clear断言后四场景最终pass3.08s，证据 portal-pdf-scope-172/result.json、4PNG、synthetic.pdf。continuation-race与held-body身份失效/导航中断三负向URL/click/revoke皆0；正常实际download事件、1URL/1click，导航后revoke精确等于created。微任务返回后跨setTimeout任务再取证，不以挂起body的暂时零结果冒充通过。171既有orders浏览器36API、11声明断言pass；25项Node client/browserChannel/orderDecision pass/0fail113.05ms。独立定向复核scope guard和四场景证据无剩余具体P1/P2；172只是更强完成/顺序断言，不叠加全量审查或重构建。171/172不相加。

上述全部新浏览器是截获API、合成员工身份/客户会话和PDF；模拟commit只是夹具状态变化，不证明真实权限、映射持久化、PI内容/金额或服务器缓存策略。既有真实JWT/MySQL契约证据独立保留，本批无后端修改不重跑数据库矩阵。T48/T50/T51全站仍部分（账号/站点配置等流程、对应最长内容/字体/状态未齐）；T49/T53本批仅补PDF消费边界，不关闭新账号已登录、真实跨标签/共享缓存/同域角色全规格。T52北京时间、T54回退、T62全PI编辑入口竞争、T64锁超时/慢IO性能仍待验；完整历史迁移、B01–B07正式经营配置、真实SMTP/COS、双客户双业务员试点及发布仍独立。没有生产连接/迁移、真实发信、commit/push/merge或部署，整体goal仍active。本批收尾：strict、git diff --check、八篇文档静态核验均exit0（8篇/24链接锚点/3JSON/64规格/19设计发现；既有LF/CRLF提示保留）。14:41北京时间 git_sweep --no-fetch exit0，只是本地快照：主目录0修改/1未跟踪，任务分支42修改/42未跟踪统计项、无upstream，未取得远端最新状态。69979员工preview及51317客户preview已Ctrl+C终态exit1（主动停止）；所有本批构建、浏览器和Node过程已终态，没有本批MySQL服务。删除仅本批拥有的过时scratch映射/PDF脚本副本，保留仓库测试、167/168/170反例、169/171/172最终结果、截图与构建日志。详细文档交付与独立对抗复核完成，整体实施goal仍active，未将局部UI和PDF回归通过替代剩余验收。
## T49/T53 原生双标签、A迟到/B保留及同域凭证反例（2026-10-04）

上一 goal turn 属 progress：I15–I18修复与171/172最终验证落地。本轮新增 frontend-portal/tests/account-switch.browser.mjs 和 backend/tests/portal/test_session_surfaces.py，未改产品源码、业务/表/迁移或鉴权规则。继续实现验收，不将文档完成当整体goal完成。

173首次五场景脚本在catalog等待B_PRIVATE_COMPANY exact超时；菜单span同时含small的Private partner access，已真实两次Bverify但body未释放，属于定位夹具错误。改限定 .account-menu > span 后174完整五场景通过。联系人一度观察为等待中，后来同86955句柄确认为exit0并有contact.png/result.json，未擅自重启或将观测超时当终态。175新增heldPrivateA必须true与B目录/条款/报价/联系人/地址完整保留；176再补A价格 USD71.25不可见、B正常下载实际合成PDF字节含B_PRIVATE_PI且无A_PRIVATE_PI，五场景最终通过。D:/commission-system/tmp/portal-account-switch-176/result.json、5PNG及B-synthetic.pdf为最终证据；174/176/177重叠不相加。173失败JSON/截图保留。

真实Chrome同context两页面、真实构建App/client与未替换的原生BroadcastChannel，peer退出→原tab登录页/another-tab通知/弹窗卸载→peer登录B→原tab登录B→peer收到登录页。各A目录/订单/报价/PDF/联系人JSON/Blob的native读取完成，受控后续Promise暂停；fetch wrapper只去掉signal以模拟不合作transport，真实client的scope/controller断言保留。B当前页面和新B报价已建立再release A body，跨宏任务后断言body-return真实发生、held数据含合成A标记、批次DOM未见A、最终DOM/输入/金额无A/旧价。B内容完整仍可用；旧PDFURL/click0、新B实际download事件与字节正确。每模式API14/16/15/17/15；原tabfetch options记录7/9/8/9/8均same-origin/no-store；pageerror0。local/session storage合成私密标记无残留，CacheStorage空、service worker0；不是任意敏感字段/浏览器HTTPcache/CDN缓存证明。1440截图contact已实际查看。本批不是完整键盘/字体/移动端验收，不增加UI条目总数。

177隔离实际pytest tests/portal/test_session_surfaces.py tests/portal/test_customer_preview.py --confcutdir=tests/portal -p no:cacheprovider --basetemp=D:/commission-system/tmp/portal-session-surfaces-177 -q --tb=short -x；日志portal-session-surfaces-177.log，3 passed/2条既有jose.utcnow弃用警告0.83s、exit0。新增凭证表面1项+既有只读预览2项，不计为三项新场景。真实JWT签发/解码、真实客户OTP/opaque会话和binding validate，真实ASGI HTTP/SQLite，客户及员工依赖无override（仅get_db隔离）；employee_principal仍managed权限替身。有效员工JWT先后台列表200/no-store以排除无效token的假反例，再单Bearer客户401、JWT装客户Cookie401、真opaqueCookie客户200、另一super_adminJWT不改变该customer、客户Cookie员工403/AUTH_REQUIRED、opaqueBearer员工401。预览200/private no-store/无Set-Cookie，PortalSession/Quote/MappingRevision/AuditEvent/OutboxEvent计数不增，去Cookie后单JWT客户仍401。未打印合成JWT/OTP/session，也未读.env、连接MySQL/生产或真实发信。

原生BroadcastChannel两标签与合成服务端身份明确分开；HTTP鉴权和真实角色授权分开；客户端no-store参数与真实所测路由no-store响应分开。MutationObserver不能证明所有同批次瞬时DOM或input.value孤立写入，最终值有另验，不扩大承诺。T49/T53本组客户端及路由子契约补证，不宣布整条真实新账号/经营数据/代理共享缓存全通过。其他T48/T50/T51配置UI、T52北京时间、T54回退、T62PI全入口、T64慢IO/锁超时性能及完整迁移/B01–B07/真实SMTP/COS/试点发布保持独立待验。无产品新修改，不重复当前171客户构建或已通过数据库矩阵；整体goal仍active，未commit/push/merge或部署。
本批独立定向复核已完成：账号切换续体/原生两标签/B保留和新增同域凭证/预览测试无剩余具体P1/P2；177实际日志3pass0.83s、176最终五场景结果已核。真实JWT/OTP/binding与managed员工权限替身的边界明确，不能称真实RBAC完整。最终strict、git diff --check、文档静态校验均exit0（8篇/24链接锚点/3JSON/64规格/19设计发现；保留既有LF/CRLF提示）。15:01北京时间 git_sweep --no-fetch exit0，仅本地快照：主目录0修改/1未跟踪，任务42修改/42未跟踪统计项、无upstream，未fetch。91084客户预览Ctrl+C终态exit1（主动停止），173/174/176/177浏览器及177Python均已终态，拥有的Chrome/HTTP/SQLite测试过程已结束，无MySQL或真实外部服务。保留仓库两新测试、173失败、174/175历史与176/177最终证据；本批无过时scratch脚本需清理。整体goal仍active，下一步继续北京时间跨日与隔离回退等尚未满足本地验收，不把本批客户端/路由补证替代生产试点。

## 详细开发文档与对抗审查交付补充（2026-10-04 15:15 北京时间）

按用户“生成详细的开发文档并进行对抗性审查”收口现有8篇v1.3。本轮仅改06验收矩阵/证据要求和07审查记录，补足T52跨午夜不同key、原命令回放、业务日期与HTTP/展示一致及JWT UTC例外；T54真实兼容旧制品版本摘要/新schema保留、关闭不消费任务、新PID恢复和现存PI保护。两者是验收契约细化，不新增F设计缺陷。独立交易复核落地文案未发现具体P1/P2，删除未定义的“受控释放”措辞。文档层仍19项设计发现（5P1/14P2）已修订，实施I与验收完成程度不由该结论推导。

主线程静态8篇/24链接锚点/3JSON/64规格/19F、strict及git diff --check均exit0；15:15 git_sweep --no-fetch exit0，只是本地快照：主目录0修改/1未跟踪，任务42修改/42未跟踪统计项、无upstream，未fetch。本批没有新业务测试运行、构建、生产/外部服务、commit/push/merge或部署。已有backend/tests/portal_mysql/test_mysql_beijing_midnight.py是待整理/执行的T52草稿，未作为通过证据；不得把文件存在或本次文档审查当该测试成功。T54仍缺真实兼容旧制品连贯演练。此前整体开发goal继续active，文档交付完成不替代剩余实现/验收；本批无需清理其他人的或既有证据文件。入口README已通过open_in_codex排队展示。
## T52 北京午夜、原键回放与真实HTTP投影展示（2026-10-04）

上一goal turn为progress：文档T52/T54验收契约补充已落地并独立复核。继续已授权实施，本轮整理backend/tests/portal_mysql/test_mysql_beijing_midnight.py草稿为可执行回归，扩展frontend-portal/tests/presentation.test.mjs，新增frontend-portal/tests/beijing-midnight.browser.mjs；没有产品源码/表/迁移/经营规则修改。

178实际MySQL2pass23.86s，去掉原草稿不可靠的全局mail claim附带断言，不把跨其他fixture取到的事件当本site租约证明。179加真实JWT signature+expiry：对jose协议时钟局部替身，verify_exp保持开启，iat/exp与UTC epoch精确相等，exp+1真实ExpiredSignatureError，2pass22.53s。179实际Chrome12组pass。独立审查发现snapshot为允许idle续期而排除PortalSession整表的证据缺口；改为before/after按PK排序读取全部列，expected只允许ctx.session_id的idle_expires_at=min原absoluteexpiry,after+idleTTL及updated_at=after，其余列与其他session均不变；Membership/Access/Site完整BUSINESS快照仍在。独立定向源码复核该补证无新增具体P1/P2。

最终180：pytest tests/portal_mysql/test_mysql_beijing_midnight.py --confcutdir=tests/portal_mysql -p no:cacheprovider --portal-mysqld=D:/commission-system/tmp/portal-mysql-runtime/mysql-8.0.46-winx64/bin/mysqld.exe --portal-mysql-workspace=D:/commission-system/tmp/portal-mysql-run-180 --basetemp=D:/commission-system/tmp/portal-beijing-midnight-180 -q --tb=short -x。日志D:/commission-system/tmp/portal-beijing-midnight-180.log，2pass22.48s/exit0；owned mysql.log 07:28:28UTC Shutdown complete。仅自有loopback、随机port、生成临时凭证和隔离库，no-defaults/no.env guard，不触及共享数据库。

确定性北京时间2026-10-05 23:59:59→2026-10-06 00:00:01。core.time.datetime无参now模拟UTC/洛杉矶默认日期仍5日，显式北京now/today为6日；MySQL每次checkout实际SET +00:00/-07:00并查询@@session.time_zone。没有改变宿主时钟或真实操作系统时区。实际两单完整POR-YYYYMMDD-UUID编号/提交created时间正确；次日customer GET by-key+POST原key/body回执deepEqual，BUSINESS全部模型（排Session）及outbox全字段和会话单独全字段无额外副作用，原revision publicid/hash/created/expires稳定。后续真实提案/接受/审批给首单建PI，Fresh Session原号/提交5日、四条audit05日首/06日后三、次单audit和两outbox created/next_attempt一致，PI日期按实际建票6日，source_order_name保留首单5日号。UTC helper及实际JWT iat/exp/expiry符合协议；scripts UTC白名单已有auth/utils.py JWT exp/iat。门户mail lease仍北京DATETIME，本批未宣称其他UTC技术租约消费者完整验收。

实际客户ASGI HTTP列表/两详情均200/no-store，submitted_at原naive时间及customer_safe_timeline精确核对；只override get_db接真实隔离MySQL，无客户鉴权override。两case各http-time-evidence.json在D:/commission-system/tmp/portal-beijing-midnight-180/test_requests_replay_audit_and0及and1，只有合成公司资料和客户安全投影，无JWT/OTP/Cookie/credentials。薄上游表、synthetic库存观测、发票建议号/flags等trade fixture边界保留；172/173实际迁移不等同完整历史链。JWT/protocol clock人工冻结，expiry实际签名校验不是把future token拿宿主真实clock验证。

最终客户Chrome D:/commission-system/tmp/portal-beijing-ui-180/result.json、4PNG；12case=2源默认clock×2真实Chrome context时区UTC/LA×3字段编码naive/utc/offset，pageerror全部0、每case5GET。原naive真实HTTP投影直接使用，Z/+08为同instant等价转码。真实App/client/OrdersView读取两单列表、两详情summary及首4/次1timeline，逐项期望05 Oct23:59及06 Oct00:00 (Beijing)；Intl实际timeZone正确且Date.local day仍5，防止仅改label。会话/API输送为拦截；不是live后端/browser Cookie认证。PI日期只由后端证明，UI没有该日期字段。实际查看179 UTC-LA首单PNG，时间线正确；180同实现最终断言与截图保存。178/179/180重叠不相加。测试过程中普通读取pytest tmp ACL拒绝，改在授权隔离测试进程读取；误读src/views/OrdersView.vue不存在后按inventory定位src/components，不扩大“检查通过”范围。

Node --test tests/presentation.test.mjs：4pass0fail94.61ms，其中新增时间测试1项，覆盖naive/+08/Z/-07及UTC/LA/北京，TZ finally恢复；其他3为既有价格/广播回退测试。本批只加测试不改产品，不重复当前171构建。对应MySQL README、客户站README、05/06/07已同步。T52本组隔离核心契约补证，真实部署/全迁移和其他UTC消费者仍按其独立范围；T54尚缺实际兼容旧制品连贯回退。T48/T50/T51剩余账号/配置UI、T49/T53真实经营身份/代理缓存、T62全PI入口及T64性能等保持待验。没有生产/外部SMTP/COS、commit/push/merge或部署，整体goal继续active。
本批最终收尾：strict、git diff --check及8篇文档静态核验均exit0（24链接锚点/3JSON/64规格/19设计发现；既有LF/CRLF提示保留）。15:32北京时间git_sweep --no-fetch exit0，只是本地快照：主目录0修改/1未跟踪，任务42修改/42未跟踪统计项、无upstream，未fetch或远端写入。14895 loopback预览Ctrl+C终态exit1（主动停止）；178/179/180 Python及179/180 Chrome全部终态exit0，三自有MySQL均Shutdown complete；无遗留本批运行服务。本批没有过时scratch脚本需清理，保留仓库源码、各真实运行日志/HTTP JSON/截图及恢复证据。草稿状态已被最终180结果取代，整体goal仍active。
## 客户门户开发文档交付与未完成键盘验证（2026-10-04 15:55）

- 按当前用户要求交付8篇v1.3开发契约与对抗性审查；设计发现F01–F19为5P1/14P2，均在文档层修订。当前静态检查8文档/24引用/3JSON/64规格/19发现与diff通过，不代表实现或上线完成。
- 保留上一实施批次PortalSettings.vue焦点/网络提示/保存拒绝清理、SidebarNavigation.vue键盘入口、navigation.js仅站点管理员父组可见及portalSettingsKeyboard.browser.mjs，未撤销、提交或发布。182构建16.29s，政策/访问Node9通过；183真实Tab揭示工作台menuitem不可达。184最新构建16.55s、导航/政策/访问Node17通过；Chrome exit1，展开客户门户后Tab到站点设置时menuitem不可达。证据D:/commission-system/tmp/portal-settings-ui-181至184相关日志/失败JSON/PNG；184仍须定位，不以局部通过关闭T48/T50/T51。390/320未运行到，后续恢复路径未完成。
- 独立只读实现审查发现两项P2，主审源码核对确认条件：分组.enter.prevent先于target判断，子级外链Enter被取消；collapsed分组handler无动作且Element Plus忽略focus打开。未运行对应浏览器反例、未修复；不要称独立审查通过。下一次先定位184菜单隐藏/焦点问题，再修正事件范围及折叠入口并补真实Tab/Enter/Space/外链验证，下一运行号185。
- 本次未改产品代码、数据库或权限载荷；停止自有localhost3211预览79395（Ctrl+C退出），无MySQL进程。本轮仅文档交付，不标整体实现目标完成；T49/T53/T54/T62/T64、完整历史迁移与B01–B07试点/生产门禁仍按既有记录推进。无push/merge、生产迁移、真实发信或部署。
## 客户门户站点配置与导航键盘闭环（2026-10-04 16:24）

- 前一目标轮完成文档复核及记录最新实现反例，属于progress。本轮继续原实现目标，未缩小验收范围。产品只改PortalSettings.vue、SidebarNavigation.vue及navigation.js父组权限；新portalSettingsKeyboard.browser.mjs。无后端/数据库/交易载荷/权限服务改变。
- I19：错误每次nextTick后聚焦（含同文案），错误代次/identity/disposed防迟到夺焦；读取/保存role=status+aria-busy、成功和核对提示聚焦；ERR_NETWORK中文；save401/403/404同load清私密。unknown仍冻结仅GET核对，编辑同步撤销确认保持。181原焦点失败真实复现，182修订后前段通过。
- I20：183实际工作台menuitem tabindex=-1不可Tab到达；所有现有竖向item支持Tab及Enter/Space原click路径，父组.self.prevent.stop不拦子级外链；公开menu.open/close，折叠打开首项焦点、Escape回分组、Tab离开关闭、折叠具名。portal_site:admin加入父组，只有目录/设置子项可见，未扩scope。191真实折叠首项outline=none，192修为仅ark-navigation-popup下token圈，group圈限定title；实际几何中心命中及solid>=2px轮廓证明可见焦点，截图已查看。
- 实际失败与修订：182 link角色夹具不符，183menuitem确不可达；184当前路由组自动展开却固定Space收起（测试前提），185Tab回group时popup未关闭（产品修订）；191缺传送弹层轮廓（产品）；192过渡中旧popupvisible早于asyncfocus（测试前提），193有界等待真实activeElement并保留后续Tab/关闭断言，不强制focus。独立审查补强最终pageerror时点及Space真实单次click计数，避免同路由URL不变假通过；每DOM元素一次listener可重置计数。
- 最终产品构建192：3330模块，15.90s，exit0；保留既有auth混合导入/500k chunk警告。Node导航/政策/访问17 passed（105.66ms），最终脚本node --check exit0。193 reduce、194 no-preference同192 dist真实Chrome各三宽1440/390/320全部pass；每宽四模拟PATCH、零主页面pageerror、两实际fonts.googleapis.com样式请求abort。合法字段100/64/256/100/254/16/500；quote30/proposal24,168；确认编辑清除、光标移动保留、重复校验焦点、503、409草稿保留、模拟已提交回执丢失、字段冻结、站内leave守卫、真实beforeunload dismiss并无重发、GET核对不当回执、成功焦点、读写403清私密。194最新result及PNG在D:/commission-system/tmp/portal-settings-ui-194/，193 reduce保留；181–192失败与构建日志保留作证据。各批重叠不累加为独立测试数量。
- 187原站点设置10场景/3模拟写pass，189原客户账号10场景/6模拟写pass，用于共享布局回归；均为API截获。独立只读审查已闭环原两P2及click/error/beforeunload证据，无剩余具体P1/P2；193源码/result已由审查者核对，194正常动效结果由主线程实际确认，不把主审运行当独立运行。
- 边界：合成员工身份/配置、API截获不是实际RBAC/持久化联调；409夹具未模拟另一写者递增版本。外链为真实anchor/default Enter，目的地合成静态HTML，不验证采购节产品；pageerror只计主page。字体失败条件可用性不是生产字体服务保证。T48/T50/T51只补站点设置/导航，账号邀请/账号管理/开通等完整纯键盘仍须补；不将此批关闭全部64规格。完整历史迁移126门禁、T49/T53/T54/T62/T64及B01–B07实际试点/生产门禁保留，整体目标active。
- 05 Before/After/Why、06验收范围、07 I19/I20及README序列已同步。收尾strict、静态8文档/24引用/3JSON/64规格/19F及diff均exit0；16:27 git_sweep --no-fetch成功，仅本地快照（main0改动+1未跟踪，自有43改动+43未跟踪，无upstream）。无生产迁移、真实邮件、push/merge或部署。下一运行号195；自有预览15521已Ctrl+C关闭并确认终态，无待运行测试。
## 详细开发文档本次交付、195账号键盘失败保留（2026-10-04）

- 用户本次要求详细开发文档与对抗性审查；交付8篇v1.3及既有19项设计发现修订（5P1/14P2）、64项验收规格。主审核对当前架构/权限、标准SKU映射、交易不变量与实施门禁，未发现新增具体设计矛盾；既有独立审查结论不冒称为本轮新审查。
- 195实际Chrome纯键盘脚本首次exit1：1440邀请空邮箱/联系人校验出现，但activeElement停留确认操作，错误提示未获焦点。日志tmp/portal-accounts-ui-195.log及failure-1440.json/png保留；后续断线/拒绝/恢复、390/320未运行到，不列通过。frontend/tests/portalAccountsKeyboard.browser.mjs保留为未完成验证的恢复材料，未据此关闭T48/T50/T51。
- 本轮只补审查和交接说明，未修改产品、构建、业务接口、权限或数据库；此前实施改动保留。详细文档交付完成不替代active实现goal。T49/T53/T54/T62/T64、全历史迁移与B01–B07/真实邮件/试点仍待对应证据。无生产变更、真实发信、commit/push/merge或部署。- 本次最终静态核验exit0：8篇、24链接/锚点、3JSON、64验收规格、19设计发现；strict与git diff --check均exit0，仅既有LF/CRLF提示。16:44北京时间git_sweep --no-fetch完成，仅本地快照：main0修改/1未跟踪，自有任务43修改/44未跟踪、无upstream；未读取远端最新状态。自有3211预览36410已Ctrl+C停止并终态exit1，195浏览器已失败终态，无本批MySQL或遗留运行服务。验证是静态文档范围，195失败不能称业务测试通过。

## 采购邀请/账号键盘与I21/I22修订（2026-10-04）

- 上轮为progress：文档交付与195错误不聚焦反例落地。继续原实施goal，本批产品只改AccessActionDialog.vue、PortalCustomers.vue，新portalAccountsKeyboard.browser.mjs；没有API/后端/数据库/价格/权限服务改变。现有门户源文件是本任务未跟踪新增文件，git diff不显示它们，不把空diff当源码审查；主审/独立审查直接读取当前源码。
- I21：每次错误nextTick后聚焦（重复文案同样处理），error/generation/disposed约束；ERR_NETWORK中文、发送/读取文字status和实际aria-busy；编辑同步撤销确认；401/403/404遮蔽公司/邮箱/草稿且清空父列表/详情。未知邀请保留createAccessMutation内部原key/body，仅原键重试；普通账号/访问/撤销unknown仍仅GET核对，不重发。真实身份变化/卸载仍清除待处理命令，未削弱未知恢复规则。
- I22：等待成功后列表/详情刷新再定位当前同access/action/account控件，状态变化后回新按钮、撤邀请按钮消失回邀请、拒绝取消回刷新、恢复读取成功回列表管理。独立审查提出父详情关闭后旧刷新夺焦P2；199实际失败证实activeElement为旧管理，用户已Tab搜索并输入NewSearchIntent。clearDetail增加actionFocusSequence递增，200加强回归真实Escape/Tab/typing、暂停GET→释放→加载完成→两帧观察，焦点/值都保留。独立定向源码复核无新增具体P1/P2；实际结果由主线程执行。
- 实际196构建16.25s/3330模块，原强度三宽reduce196/正常197各9模拟写pass；198既有账号10场景/6模拟写pass。新增迟到反例199只1440实际fail，未误称手机通过。200最终构建15.95s/3330模块exit0，保留既有auth混合导入和500k chunk警告；访问Node5pass85.453ms，node --check exit0。最终200 reduce/201 no-preference同200 dist三宽1440/390/320全pass，每宽10模拟写、Map1模拟邀请效果、pageerror0；202既有账号10场景/6模拟写pass。各批重叠不累计为独立业务测试。
- 最终证据D:/commission-system/tmp/portal-accounts-ui-200/和201/result.json及12PNG，日志portal-accounts-ui-200.log/201.log、portal-customers-regression-202.log；195/199失败证据与196/197历史通过保留。最大合法公司100/邮箱254/联系人100/原因500、重复错误、确认失效、unknown冻结/Esc、真实beforeunload dismiss无重发、原邀请三次body/key一致、未知账号只写一次、GET503/404、写403隐藏全部私密内容、未验证邮箱恢复invited、撤邀请、暂停/价格撤销保持catalog、只读入口及迟到刷新焦点均有断言。196的320邀请/访问PNG实际查看；动态toast可能覆盖标题，截图不是实际屏幕阅读器证明。
- 全部业务API/身份截获，Map效果不能证明后端幂等/RBAC/持久化/SMTP。409夹具未递增远端版本；401仅共用源码分支，真正身份切换后释放旧响应未由新UI脚本验证。字体样式请求实际失败，不宣称CDP实际字体选择。此前后端/JWT/MySQL证据保持各自边界。
- 05 Before/After/Why、06范围、07 I21/I22、README I01–I22已同步。T48/T50/T51补账号这一组，客户开通/目录配置/绑定复核等其余管理UI仍要继续；T49/T53真实经营身份/代理缓存、T54真实兼容旧制品连贯回退、T62全PI写入口、T64锁超时/慢IO/性能、全历史迁移与B01–B07/真实SMTP/COS/双业务员双客户试点门禁不据此关闭。没有生产连接、真实发信、commit/push/merge或部署，整体goal保持active。下一运行号203。
- 本批最终strict、文档静态8篇/24链接锚点/3JSON/64规格/19F与git diff --check均exit0；仅既有LF/CRLF提示。17:00北京时间git_sweep --no-fetch exit0，主目录0修改/1未跟踪，自有43修改/45未跟踪统计项、无upstream，仅本地快照。自有3211预览5740已Ctrl+C终态exit1（主动停止）；196/197/198/199/200/201/202浏览器和Node/构建全部终态，199是预期反例失败；无自有MySQL或遗留运行服务。本批无过时临时脚本需清理，保留测试源码、失败/通过日志JSON/截图作为复现与恢复证据。后续先继续开通/目录/绑定管理UI，再按T49/T53/T54/T62/T64剩余本地契约和经营门禁推进，不将账号单组补证替代整体目标。

## 客户开通、共享规格选择与I23–I25（2026-10-04）

- 上轮为progress：采购邀请/账号I21/I22与三宽键盘实际闭环。本轮继续原开发goal，产品只改OnboardingDialog.vue、CatalogPicker.vue、PortalCustomers.vue；新增portalOnboardingKeyboard.browser.mjs，旧portalCatalogAccess.browser.mjs仅旧closeicon定位改新的具名原生移除按钮，empty/body/版本断言保留。未改CatalogAccess/BindingReview产品、API/后端/数据库/权限服务或经营规则。
- I23：203候选503提示已有，但activeElement为body（30s等待后fail）；每次showError/nextTick与错误/身份/卸载代次，候选/商品/创建/查询role=status与真实busy；编辑选择/能力同步撤销确认，筛选/光标不改变选择。商品拒绝父catalogDenied清私密并聚焦公开说明，子卸载不吞反馈；父客户页清私密，成功draft刷新后焦点详情刷新，关闭/身份变更取消迟到恢复。
- I24：独立审查发现商品GET403在create sending后到达会清frozen；206实际1440先放商品403→create abort后查询没有checking，failure JSON显示查询按钮，证明原canonical恢复丢失。hideDenied now sending/uncertain均保留冻结绑定/body，原客户查询与三次原body恢复不变，只清可见草稿。真实身份变更/卸载清除原内容的规则保留。独立审查的另一P2是子拒绝错误被卸载，父反馈已实测idle及sending两种403。
- I25：204初步三宽pass但320截图标准规格截断，外壳检查不够；205手机标签右961.25>容器268实际fail。补tag/content最大宽、min-width0/anywhere，局部cell normal!important覆盖共享nowrap；具名原生移除按钮可真实Tab/Enter且toggle清confirm；Element已装源码支持scrollbarTabindex0，水平滚动键未单独浏览器断言，不扩大该结论。207/209初步普通路径pass后独立审查指出empty cells.every假阳性；先等待精确model/color cell、length>=4、两项文本存在再查wrap/scrollWidth，212/213最终pass。
- 实际204构建3330模块16.20s/初步三宽4POSTpass；205/206反例fail。207最终产品构建3330模块16.05s exit0，保留既有auth混合导入/500k chunk提示；最终212 reduce/213 no-preference默认路径1440/390/320均pass，每宽4模拟POST/0pageerror。208 reduce/210 normal race三宽每宽3模拟POST/0pageerror，race路径不走cell全文分支，其时序不受后补空数组检查影响。211旧onboarding11场景5模拟写、catalog10场景4模拟写、binding12场景3模拟写均pass。204/207/209初步与最终重叠不相加；test node --check实际exit0。
- 证据D:/commission-system/tmp/portal-onboarding-ui-212/、213/、208/、210/result.json/PNG及对应.log；旧回归日志portal-onboarding-regression-211.log、portal-catalog-access-regression-211.log、portal-binding-regression-211.log。203/205/206失败日志JSON/PNG及初步204/207/209保留。204与207的320规格截图已实际查看。最大标准型号/颜色128/128，公司/负责人100/100；tag/content真实水平边界/cell全文与wrap、键盘移除和重授权、重复候选/商品503、idle/sending商品403父摘要及私密消失、已确认选择筛选保持、409重选、unknown字段/Esc冻结、真实beforeunload dismiss不重发、原canonical GET503/未查到/404、三个POSTbody深相等、创建draft后详情刷新焦点/采购账号空/邀请disabled均有断言。
- 全业务API和身份截获，create abort发生在exists=true前，没有模拟初次数据库commit；相同body只证明客户端冻结，不代表后端原键回执或唯一创建。后台接口本来没有创建idempotency-key，不擅改协议；唯一绑定/查询存在边界保留。401和真实身份切换旧响应未单独浏览器测试；字体stylesheet真实abort不证明具体回退字体。没有生产连接、真实发信、commit/push/merge或部署。
- 独立只读审查两P2与cell假阳性修订闭环，读212/213最终result，无新增具体P1/P2；主线程真实运行与独立源码意见分别记录。05 Before/After/Why、06范围、07 I23–I25、README I01–I25已同步；F设计发现仍19。T48/T50/T51只补客户开通和共享规格选择，目录授权/身份复核完整纯键盘、错误/权限拒绝反馈仍须继续，旧回归不代替该验收。T49/T53真实经营身份/代理缓存、T54真实兼容旧制品连续回退、T62全PI入口、T64锁/性能、全历史迁移126门禁及B01–B07/真实SMTP/COS/双业务员双客户试点仍独立；整体goal active，下一运行号214。

- 本批收尾strict、静态8篇/24引用/3JSON/64规格/19F、git diff --check及两浏览器脚本node --check均exit0；文档I23–I25 UTF8原文读取正常，仅既有LF/CRLF提示。17:28北京时间git_sweep --no-fetch exit0，只是本地快照：main0修改/1未跟踪，任务43修改/46未跟踪统计项、无upstream，未fetch。自有3211预览87511已Ctrl+C终态exit1（主动停止）；203/204/205/206/207/208/209/210/211/212/213各构建/浏览器全部终态，203/205/206为真实反例fail，其余实际pass，无本批MySQL/后台服务残留。无过时scratch脚本需清理，保留仓库测试与失败/通过证据。下一步继续CatalogAccess/BindingReview键盘、错误/拒绝清理和焦点，再推进其余本地契约；不以本批局部闭环或文档静态通过宣称完整开发完成。

## 详细开发文档与本轮独立对抗复核（2026-10-04 17:37 北京时间）

按用户本次文档与对抗性审查请求交付8篇v1.3；两位独立审查者本轮分别只读复核身份/权限/映射/前端恢复及交易/PI/幂等/兼容回退，未发现新增具体P1/P2文档矛盾。F01–F19保持5P1/14P2文档层修订，未扩大为实现安全或上线结论。README复核时间与07审查范围已同步。本轮只改README、07及本交接说明，不改产品代码，不运行浏览器/业务/数据库测试；已有实现改动和后续实施目标保留，下一实现运行号仍214。

实际静态核验8篇/24引用/3JSON/64T/19F通过，check_conventions.py --strict及git diff --check exit0（既有LF/CRLF提示）；17:36 git_sweep --no-fetch成功，仅本地快照，主目录0修改/1未跟踪，本任务43修改/46未跟踪且无upstream。独立审查不重新背书历史通过数量，T48/T50/T51剩余目录/绑定键盘与其他实现门禁、全迁移、B01–B07/SMTP/COS/双客户双业务员试点仍独立。本轮没有启动预览/数据库、生产操作、真实发信、commit/push/merge或部署；文档交付完成与整体实施goal active分别记录。


## 商品授权与身份复核 I26–I28（2026-10-04）

- 上轮文档更新/独立审查属于progress。继续原实现goal，本批只改CatalogAccessDialog.vue、BindingReviewDialog.vue、PortalCustomers.vue；新增portalCustomerReviewKeyboard.browser.mjs，旧catalog/binding浏览器回归仅GET拒绝后的隐藏与明确核对恢复流程，body/version/empty/count保持。未改API、后台、迁移、价格、SKU或权限规则。
- I26：214/215实际错误未聚焦失败后，补每次showFeedback/nextTick及反馈/身份/disposed守卫、中文ERR_NETWORK、role=status/aria-busy和表单错误关联。I27：拒绝隐藏公司标题/数据/草稿并清父列表/详情，保留在途/unknown原mutation，仅GET核对。辅助商品403由父反馈，sending时不抹掉原pending。I28：等待refresh后定位同access/当前控件，clearDetail/auth/unmount取消旧返回；223真实fresh review_required后trigger disabled焦点body，224修为详情刷新fallback。没有新动画/依赖。
- 最终224构建3330模块16.29s exit0（既有auth混合导入/500k chunk警告）。225 reduce/226普通catalog三宽各7模拟写、0pageerror；最终补强夹具230 reduce/231普通binding三宽各6模拟写、0pageerror。227/228为补强前binding，217catalog尚无辅助拒绝竞态，219/221为中间版本，不当最终新夹具证据或累加。218空ElSelect.input、220隐藏原生checkbox是观察误判，改可见标签/cell等待，真实键盘路径未替换为点击。214/215/223失败证据保留。
- 商品长标准型号/颜色128/128、公司100、原因500、重复错误、503/409、确认编辑清除与光标保持、unknown/Escape冻结、真实beforeunload dismiss无新增写、GET503/403、公开错误及私密隐藏、原body/version一致、只读恢复非成功回执、成功当前trigger返回、禁用trigger回刷新及父drawer离开后旧刷新不夺搜索焦点均有断言。binding真实1002合成待办，GET只前1000、遗漏两条留在未交接回执；键盘第1/2页显式选order-1/order-21、历史365天、rebind身份独立；手机待办局部ArrowRight实际滚动。225/227的390/320准备PNG已实际查看。
- 229原商品授权10场景4写、绑定12场景3写、客户账号10场景6写及开通11场景5写通过。portalAccess+portalBindingReview共10 Node pass/0fail 97.70ms；第一次误写portalCustomerAccess路径只产生binding5项输出，不用它宣称10项。最终三个browser脚本node --check通过。独立只读审查三源码/脚本无新增具体P1/P2，提出竞态缺证后补证，后续确认截断夹具与225/226result；真实运行由主线程执行。
- 全业务API/身份截获，lost在version++前abort不模拟DBcommit；409没有另一写者递增版本；标准型号/颜色只在catalog展示，不把binding结果元数据当展示证明。合成全量回执不证明后端交接/历史授权数量。401和身份变化后旧响应未单独新增UI覆盖，404由既有catalog回归覆盖；字体stylesheet阻断不证明实际选择字体。没有生产连接、真实发信、commit/push/merge或部署。
- 05 Before/After/Why、06范围、07审查及README I01–I28已同步。T48/T50/T51补两管理组，其他目录配置/通知/预览等管理UI仍要逐项核对；T49/T53实际经营身份/代理缓存、T54真兼容旧制品连贯回退、T62全PI入口、T64锁/性能、完整历史迁移126门禁及B01–B07/SMTP/COS/双客户双业务员试点独立，整体goal active。下一运行号232。自有预览54270已Ctrl+C停止；所有本批构建/浏览器终态，无本批MySQL运行。

- 本批最终静态8篇/24引用/3JSON/64T/19F、strict、git diff --check及三个browser语法均exit0，仅既有LF/CRLF提示。18:06北京时间git_sweep --no-fetch成功，只是本地快照：main0修改/1未跟踪，本任务43修改/47未跟踪且无upstream；未fetch或远端写入。自有54270预览Ctrl+C终态exit1（主动停止）；最终225/226/230/231及229回归、构建和Node全部终态，失败214/215/218/220/223亦终态，未遗留本批MySQL/Chrome测试/预览。无过时scratch脚本需清理；保留仓库测试与失败/通过日志、JSON、截图作复现证据。整体实施目标active，下一运行号232。


## 详细开发文档交付与 PI 编辑对抗复核（2026-10-04 19:53）

本轮用户请求为“按以上方案生成详细的开发文档并进行对抗性审查”，仅更新开发文档，保留原实施goal与既有产品/测试改动。8篇v1.3覆盖架构与授权、模型、API、订单/PI交易、双端UI、工作包/64规格及审查。补01员工PI实时权限/本地恢复、03内部入口既有协议与安全错误、04两短事务锁外远端回款取证、06 T62反例，并明确全局锁序、完整PI/任务版本绑定、最终当前本地回款/分摊/意图/出库及原金额保护；07首页历史审查时点已澄清。

两位独立代理只读定向复核新增身份/范围/映射/接口恢复与交易/锁序/回款契约，均无剩余具体P1/P2文档矛盾。F01–F19仍5P1/14P2设计修订；不新增闭环I编号，不把文档结论替代实现安全。实际静态8篇/28引用锚点/3JSON/64T/19F通过，strict和git diff --check exit0，仅既有LF/CRLF提示；19:53 no-fetch巡检成功，本地main0修改/1未跟踪、自有46修改/49未跟踪、无upstream，未取得远端最新状态。

实施恢复点：253真实JWT普通PI编辑反例是200而非403（1fail/6deselected/23.43s）；255此前版本实际21pass/20jose弃用警告/38.85s，日志已读，不对最新重构复用该通过结论。最新 backend/app/invoice/edit_authority.py 远端预读/最终重鉴权及 linked-close/resolve 守卫在255之后写入，尚未重新测试。独立上轮源码意见两P2（持屏障远端回款、旧JWT本地任务恢复）在文档已明确解决要求，实现仍待慢远端门控、取证期间撤权/改版/任务绑定变化、回款writer竞争、真实恢复任务与整组回归；另外全局request/conversion→invoice锁序须核对实际代码，不能仅凭新文档宣称落实。原21pass前的夹具254共享角色重复授予错误已在测试处理，不能计作产品失败或最终通过。

本轮未改产品、不启动预览/MySQL/Chrome，不执行业务或数据库测试；现有MySQL进程检查为空。后续实现运行号256，253–255自有已停实例残留数据与临时目录尚待按所有权/Shutdown检查清理，运行日志保留。最新未验证源码/测试保留作为恢复材料。整体开发goal active；T62全条、T64全条、完整历史迁移、T54真实旧制品回退、剩余UI/真实身份与缓存、B01–B07经营输入、SMTP/COS与双客户双业务员试点及发布门禁保持各自范围。没有生产连接/迁移、真实发信、commit/push/merge或部署。


## PI 实时授权、锁外回款取证与并发原键回放 I33–I36（2026-10-04 20:16）

上一目标轮为progress：详细契约和独立对抗复核落地。本轮继续既有实现goal，产品涉及invoice/edit_authority.py、router普通PUT/linked-save/close/resolve、linked_sync_service的replay/create、invoice.service及receipt.invoice_link传入已验证回款；无schema/迁移/前端改动。begin_employee_document_write先屏障再当前员工与所有动作权限，fresh对象范围，不提升authority.version；门户关闭保留原内部行为。门户关联行按request/conversion→invoice锁序，localclose/resolve同序，远端run执行协议未套全局长锁。

I33旧JWT反例与I34远端长锁/缓存边界：启用时普通/关联编辑初次只读捕获、释放屏障和PI锁、远端取证、rollback+expire_all、最终重鉴权/范围/PI+旧hash+远端ID+同步状态+task指针/status/token/lease，冲突409、不可用503。原本地意图/回款/分摊/出库与身份/金额限制保留；linked_change原受控回款reconciliation规则未放宽。I35拒绝已开始Session事务及dirty/new/deleted，防已flush/Core写入被初次commit顺带提交；请求测试通过after_begin/Connection观察避免提前SessionSELECT。I36初次及最终_current范围之后优先同key/invoice/actor/hash回放，未命中才取证/绑定比较。

实际最终259：test_mysql_invoice_editor_authority（54项）与既有invoice_edit_race/source_http/pi_download_race，共62pass/72jose弃用警告/81.81s，handle54063终态exit0；SQLite全portal加7份发票/回款相关模块930pass、2skip、14既有弃用警告/106.64s，handle68741终态exit0。日志D:/commission-system/tmp/portal-mysql-259.log、portal-unit-259.log。256旧代码36pass后shared测试admin上一用例inactive未恢复，fixture403失败终态exit1；修复fixtureisolated恢复后257为51pass/70.74s、SQLite930pass/104.84s，258为61pass/80.96s、SQLite930pass/2skip（仅中间通过，时长见其日志），均早于最后并发修订，不代替最终259或累加。253旧JWT P1反例及255历史21pass保留。

新增真实JWT/HTTP撤权先commit/rollback及编辑先持锁对照；旧superadmin作用域失效；取证gate期间另一连接在1秒行锁限制取得屏障+PI，停用/保留动作降范围、商业改版、remoteID、tasktoken/lease、本地回款均在最终拒绝且财务全快照不变。HTTP使用expire_on_commit=False；隔离Core改行不增docversion仍旧hash409。ValueError/OkkiApiError/非list三类证据503、上游私密正文不泄露、远端读仅1次；本地成功close/resolve不动商业hash/版本/远端ID、不恢复publication，activelease409，停用/撤权403/降全局scope404，均零远端。丢响应为真实服务commit后ASGI客户端抛ReadError；恢复原键在remoteoutage零取证、绑定变化同operation、异body409、当前撤权403。双HTTP同key同时capture暂停→Acommit→B恢复，两个200同operation、唯一task、A之后财务快照不变，仅各自一次远端取证。

独立只读审查提出脏已flush事务、对象缓存和回放先后/并发反例，修订后最后定向复核无新增具体P1/P2；审查者未代跑测试或背书生产。1/3/4/6/7、README、API参考及MySQL测试README同步。T62本批只补上述具体入口，其他写路由/脚本/rawSQL及回款writer完整锁序仍要逐条核对，不关闭整条；T64/旧制品回退/完整历史迁移、其他UI/真实身份与缓存、B01–B07经营输入/SMTP/COS/双业务员双客户试点及发布门禁独立。无生产连接/迁移、真实OKKI写入/SMTP、commit/push/merge或部署。整体goal active，后续运行号260。


本批收尾：strict及git diff --check均exit0，文档静态8篇/28引用锚点/3JSON/64T/19F通过；既有LF/CRLF提示保留。20:21北京时间git_sweep --no-fetch exit0，仅本地快照：main0修改/1未跟踪、自有46修改/49未跟踪、无upstream，未fetch。256/257/258/259所有MySQL/SQLite测试句柄均终态（256是fixture失败，其余exit0）；strict32247也终态exit0。253–259 runtime.json/datadir绝对路径与isolated scope逐一核对，mysql.log均Shutdown complete、Get-Process无mysqld后，原生PowerShell只删各自data/temp，保留日志与runtime元数据；257–259 pytest basetemp最初默认沙箱拒绝，狭义升级后路径再次核对并实际删除成功。自有临时写入脚本已清理，源码/测试和反例/最终日志保留，未启动本批预览或遗留后台服务。整体开发目标仍active，下一运行号260。


## v1.4详细开发文档与对抗审查交付（2026-10-04 23:31 北京时间）

本次用户请求为“按以上方案生成详细的开发文档并进行对抗性审查”。只修8篇开发契约及本交接，不新增产品修改或启动业务测试；继承的实现工作与未验证改动保留。01/03/04/06明确本地lifecycle begin/retain/abort当前invoice:admin、validate write OR sync、DELETE write及portal永久lineage保护，GET当前主体；远端refresh/remove/retry/ack/sync/uncertain/linked-run分类，不将全请求包入全局锁。

两位独立审查者分别核对权限/跨客户/业务员/映射/前端私密状态与交易/费用/确认/建票/重放。交易审查新增F20/P2：远端已发生效果但结果迟到/租约过期或被接管，原fencing拒绝覆盖却无留证路径。02复用audit_events目标契约，执行前稳定attempt、迟到结果唯一不可变安全事实；04仅受控执行器追加原事实，不改新状态/发布、不触发重发，当前拥有者核对前不再外发；06增加过期/接管/重复结果断言。进一步排除观测/保存/重试时间及次数出fact指纹，同身份保首次时间。两位独立定向复核，交易审查者最后确认该歧义闭环，无新增具体P1/P2设计矛盾。F总20（5P1/15P2），I实施另列，不将设计关闭当全验收通过。

继承运行的真实结果已读取：260真实旧管理员JWT停用后begin返回200且cancel_pending响应，预期403，P1反例；261 MySQL组合24pass后validate夹具集合joined load Result缺unique()，1failed/24passed/42warning/48.46s，handle84970终态exit1。后续validate/delete及原组合没有该轮完整证据。SQLite261937passed/2skipped/14warning/103.87s，handle49028终态exit0。I37标记未闭环；不能用259的62pass或当前SQLite关闭整条T62。日志D:/commission-system/tmp/portal-mysql-260.log、portal-mysql-261.log、portal-unit-261.log保留。最小实施恢复动作是修真实准备查询的Result.unique()（非放宽业务断言）后用全新262隔离workspace/temp运行，继续逐条writer/回款/外部执行协议验证。本轮文档复核不承担修产品或追加迁移。

实际8篇/28本地引用锚点/3JSON/64T/20F静态通过，strict与git diff --check exit0；23:29 no-fetch巡检exit0，仅本地快照main0修改/1未跟踪、自有47修改/49未跟踪、无upstream，不代表远端最新。最终静态/strict/diff会在最后文档写入后重查。260/261runtime.scope/datadir绝对路径及Shutdown逐一核对、无mysqld；只删自有data/temp与pytest basetemp261，保留日志/元数据/恢复源码。没有预览/Chrome/后台服务残留，没有生产操作、真实OKKI/SMTP发送、commit/push/merge或发布。

本次详细开发文档和设计对抗审查已交付；整体实施goal仍active。T62/T64完整证据、旧制品连续回退、全历史迁移126门禁、其他UI/真实身份与缓存、B01–B07正式配置/真实SMTP/COS/双业务员双客户试点及发布门禁保持独立。下一实现运行号262。

## PI本地生命周期及锁外取消核对 I37/I38（2026-10-04 23:58 北京时间）

上一目标轮为progress：v1.4开发契约与F20独立审查落地。本轮继续既有完整实施goal。I37本地begin/retain/abort、validate（当前write OR sync）、DELETE及启用GET lifecycle首读前屏障/当前员工/动作与范围；门户PI硬删保护和租约/终态守卫保留。两个prepare在拒绝已有事务/待写对象后expire_all，先前已提交但缓存陈旧的Session不能恢复旧PI内容/版本。共享真实JWT夹具移至mysql_editor_fixture、conftest一次登记；未override身份依赖；expire_on_commit=False、after_begin Connection观察、14模型业务快照仍保留。

I38：启用refresh初次当前授权+request/conversion→invoice完整绑定/取消JSON捕获，只读commit；独立复制快照锁外取证；finally rollback/expire_all；最终再次当前授权/范围及绑定，然后Receipt/Intent/Allocation锁定当前读替换预读本地证据和count。pending_delta非零阻塞取消结束；坏远端ValueError/OkkiApiError/非list固定503不泄露正文。有效删除租约与终态不取证，aborted受控409；仅有未发送删除的pending即使远端不存在不擅自宣称删除。最后只加状态拒绝warning/print固定日志，无业务变化。

实际262 MySQL在29pass后普通PI真实create缺CustomerProfile表失败（1fail/47warning/53.05s），fixture补真实表不mock service。263修夹具组合94pass/122warning/115.54s，handle1322exit0；264新增refresh阶段组合120pass/170warning/145.34s，handle52193exit0；264 SQLite全portal及相关invoice/receipt937pass/2skip/14warning/105.92s，handle25929exit0。265补三个动作反向撤权（commit flush后gate）、GET/refresh旧角色与scope、三终态探针、validate/delete read_all不代动作和write不代范围：组合最终133pass/196warning/158.03s，handle12915exit0。补最后安全日志后266只跑实际aborted拒绝：1pass/36deselected/3warning/23.09s，handle36018exit0。日志D:/commission-system/tmp/portal-mysql-262.log至266.log、portal-unit-264.log保留；前轮261/SQLite结果及263/264中间数量不相加，也不代替265完整新断言。

133 = refresh37、local34、editor54及原edit_race/source_http/download8。三处远端替身gate时独立连接在1秒等待限制拿到authority+PI，停用403、商业/远端绑定/cancel token409且财务全快照不变；final concurrent Receipt/armedIntent/allocated/pendingDelta有blocker且正确count；旧admin角色403/保动作无global404，read_all_only无动作403；真实两连接反向撤权在flush后commit前等待authority，动作先提交保状态及审计，后续原JWT403。构造remote_deleted终态只证明零外部短路，不证明真的删远端。真实外部API序列、所有回款writer锁序和远端原子性均未证明。

独立只读审查先指出缓存边界/反向竞争/GET与终态缺证，修订和补强后确认无新增具体P1/P2及对应假阳性；未代跑或背书未终态记录。最新实际结果由主线程确认。01/03/04/06/07、README、API参考及MySQL测试README已同步。pi-writer-inventory.json有41 mutating route候选、25服务字段写入候选、12源码hash；不是完整writer证明，存在配置/receipt/task候选，rawSQL/脚本/其他模块/在线实例仍须查。F设计发现仍20；I37在本批local/GET范围验证闭环，I38本批refresh/缓存边界闭环，不能关闭整个T62。

最终strict与diff exit0，静态8篇/29本地引用锚点/3JSON/64T/20F通过；最终Git巡检已在本交接写入后执行成功，只本地no-fetch；日志portal-pi-266-sweep.log保留，不代表远端最新。262至266各runtime.scope/datadir绝对路径与Shutdown逐一核对、Get-Process无mysqld后，只删自有data/temp和unit basetemp264；日志/元数据保留。未启动预览/Chrome、没有生产连接/迁移、真实OKKI/SMTP外发、commit/push/merge或部署。

完整goal保持active，下一运行号267。下一优先实施远端remove分阶段当前授权与F20原attempt/迟到安全事实唯一存储、接管/租约到期下原事实不丢/不盲重发，再outbound_retry/ack_outbound、sync/uncertain/linked-run及全部回款/脚本writer。T64、全历史迁移126门禁、T54真实兼容旧制品回退、其他UI/真实身份与缓存、B01–B07正式配置/SMTP/COS/双业务员双客户试点及发布门禁仍独立，未以局部通过缩小目标。

本批最终收尾strict及diff均exit0，静态8篇/29引用/3JSON/64T/20F通过，inventory JSON与12源码SHA-256和AST语法实测匹配。2026-10-05 00:01北京时间no-fetch巡检记录main0修改/1未跟踪、本任务48修改/49未跟踪且无upstream（具体统计以看板日志为准）。自有临时写入脚本清理，保留仓库测试、生成候选清单的复现脚本及全部反例/通过日志。所有本批测试和约定检查句柄均终态，无本批预览/MySQL服务残留，goal仍active，下一267。

