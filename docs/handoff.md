## 2026-11-02 工资工作台按钮与考勤同步（Codex，Git 交付，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-salary-attendance`，分支 `codex/salary-attendance`，基点 `b817650a`。修复标签内筛选栏 sticky 遮挡同步/计算按钮；当前操作人钉钉绑定传入假期接口，类型错误明确返回 502，请假分页由 50 改 20，年假按真实额度契约保守解析。
- 未分类或坏请假记录不再被当成零请假/全勤，自动列保持待人工核对，已有人工值不动；摘要显示需核对姓名。无数据库迁移。
- 薪资隔离回归 375 项、前端 9 项、构建及约定检查通过，独立复审通过。浏览器模拟验证滚动与窄屏；真实钉钉只读抽样验证 2026-10 单人考勤/请假/年假取数成功，未执行生产同步写入。详见 [验证记录](reports/2026-11-02-salary-attendance-fix.md)。
- 用户已授权本批提交、合并 main 与推送 origin，最终 Git 引用以回读为准；不部署。主目录其他成果保留。Git 巡检使用 `--no-fetch` 本地快照。预览进程已停，临时预览目录删除曾被自动审批审查阻止，恢复材料及具体路径见验证记录。

## 2026-11-02 退货单运费退款（Codex，本地完成，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-return-freight`，分支 `codex/return-freight`，基点 `a5b144a8`。独立运费贯通填写、预览、保存、编辑、生效与反向更正；现金合计包含运费，商品 GMV 不包含运费，应收与回款同步调整，附加费不退。
- 26008 实时来源只读核验：商品 286.50 + 运费 11.18 = 现金 297.68 美元，剩余运费 36.93，未收减免 0；两种退款方式均通过。只支持证据完整的 USD 现货单笔全额回款运费，其他费用分摊继续阻断。
- 迁移 `247_sales_return_freight` 接 246，五个新增零默认列；旧金额保持，非零运费禁止降级。未对共享生产库执行迁移或退货写入。
- 验证：退货域 220 项取得通过结果（初跑 219/1，补齐既有 mock 新字段后相关 17 项全过）；独立 MySQL 8 项、前端 29 项、构建通过。隔离 Chrome 完成超额拦截、保存回显、生效和冲销及详情分项检查。独立终审无阻断；完整证据、限制与实际命令见[验证记录](reports/2026-11-02-sales-return-freight.md)。
- 用户现已明确授权本批提交、合并、推送与部署；上线后仅预览验证 286.50 + 11.18 = 297.68，不实际生效退款。最终发布和验收状态以回读记录为准。Git 巡检按本地缓存远端引用执行，不代表远端实时状态。
- 自动审批以 `blocked by policy` 拦截停止验收进程、归档临时页面及删除隔离库的收尾命令；未执行清理，具体进程、端口和路径见验证记录。后续 Git 提交排除临时验收入口。

## 2026-11-02 回款列表排序规则冲突与 1030 差额（Codex，本地修复，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-receipt-list-collation`，分支 `codex/receipt-list-collation`，基于 `a5b144a8`。MySQL 1271 的 UNION 文本排序规则冲突导致回款列表显示“数据库连接失败”；仅统一查询文本投影，不迁移、不修改金额或权限。
- 21 项隔离测试通过，新增编译回归先失败后通过；生产强制 READ ONLY 下候选列表、搜索、订单筛选、来源及排序查询通过。待合并部署，业务数据未修改。
- 1030 有效含费 422.15、手续费 13.99、净额 408.16；订单手续费 20.10、净额 402.05，差 6.11。更正前须核实费用事实及生产写入授权。详见 [核对与验证](reports/2026-11-02-receipt-list-collation-and-1030.md)。

## 2026-11-02 退货单订单名称与回款取证（Codex，本地完成，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-return-order-name`，分支 `codex/return-order-name`。原订单选项显示小满订单名称，空名称回退编号；搜索同时匹配名称和编号，保留客户、业务员及实际出库范围。候选与明细提供 `order_name`，用于草稿重开和预填回显；展示名称不参与既有 `binding_hash`。
- 手续费口径已确认：数据库字段注释与小满原始详情一致，`service_fee_amount_usd` 来自 **`order_info.service_fee_amount_usd`**，不是顶层银行手续费。26008 的原始字段明确为 0。镜像缺失时先授权取证、结束只读事务，再 GET 原回款核验嵌套费用；最终事务重验权限、完整回款集合与本地状态指纹。取证失败返回 503，不把 NULL 当 0，不回写镜像；已成功创建/生效请求的幂等重试不依赖远端再次响应。
- 按回款远端 ID、订单、客户及币种精确关联方舟 `remote_deleted/synced` 记录并排除镜像残留。26008 旧回款 `105803338955437`（USD 618.11）在方舟回款 729 已删除，小满 `removed=1` 和详情 `enable_flag=0` 同时确认；当前新回款 `105894882267819`（方舟 1557）为 active/synced、USD 649.02、银行手续费 0、日期 2026-10-30。删除处理中、身份或金额冲突、未明确的远端删除均继续阻断。
- 真实预览还暴露含费回款误作全商品本金：26008 商品 570.00，运费 48.11，附加费 30.91。现仅对证据完整的 USD 现货单笔全额回款分离费用：本地总额、商品/费用分项、镜像净额、全部有效本地回款均严格一致；退货本金为商品 570.00，保留现金本金及提成基数 649.02、非商品款 79.02。部分/多笔/非 USD 或其他无法核验的费用分摊继续阻断，不截断未知超收。
- 验证：退货域隔离 SQLite 回归 196 项通过，之后补充一项 26008 金额组合的真实 service 草稿创建测试，并重跑受影响取证测试 49 项通过；前轮前端 25 项、构建通过。独立终审无代码阻断。MySQL 强制 READ ONLY + 小满 GET 对 26008 实数验收：只保留新回款、交易服务费 0，三行全商品 `return_refund/refund_only` 两种预览均为冲减/退款 570.00，商品余额归零；证据 `tmp/return-order-name/26008-readonly-verification.json`。生产未创建退货单或修改业务数据。
- 用户已明确授权本批修复提交、合并 main、推送并部署；按固定候选执行，最终版本、发布回执和上线验收以读回为准。增量约定、diff 空白检查和 Git 巡检（`--no-fetch`，本地快照）按本次差异执行。

## 2026-11-02 订单发票日期筛选同步列表（Codex，Git 交付，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-invoice-date`，分支 `codex/invoice-board-date-filter`，基于 `bf1ffee4`；主目录既有未提交改动未触碰。
- 顶部日期按同一发票日期闭区间同时筛选概览与列表，首次进入均使用北京时间当月。切换日期回到第一页，保留已应用的搜索、状态、类型及排序，不自动提交尚未搜索的输入；翻页、刷新、保存后刷新和列表筛选重置继续使用顶部日期。概览仍仅统计已同步且未取消订单，列表仍保留原状态范围与权限。
- 列表 API 新增可选 `date_from`/`date_to`，日期过滤在总数和分页前执行；无参数调用保留原行为，反向区间返回 422。接口文档已同步，无迁移及业务数据写入。
- 验证：前端日期联动与竞态 3 项、后端概览及日期边界/分页/权限 3 项、既有权限/代办/列表排序 21 项通过；前端构建、增量约定和 diff 检查通过。使用内存 SQLite，初次系统 Python 缺 reportlab 后切换项目 `.venv` 验证成功。保留现有 auth 混合导入、包体积及第三方 JWT 弃用警告。独立代码审查通过；未做真实浏览器或生产验收。
- 用户已授权本次提交、合并 main 并推送 origin，最终 Git 引用以读回为准；不部署。Git 巡检 `--no-fetch` 已按本地远端引用快照执行，结果不代表远端实时状态。

## 2026-11-02 客户跟进 UI 与截图粘贴（Codex，Git 交付，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-customer-followup`，分支 `codex/customer-followup-ui`，基于 `d4a6d3ff`；主目录既有未提交改动未触碰。
- 客户跟进改用统一 OverviewMetricCard、Liquid Glass 面板、卡片内操作行与带图标的轻量任务操作；我的记录和异常意见接入 TableTools 的刷新、列显示、行密度与全屏。首次加载失败显示错误和重试，刷新失败保留旧数据；空态区分分类无待办与全部完成。
- 沟通截图接入 AppUpload：点击区域后 Ctrl+V、拖拽或选图上传，PNG/JPG/WebP、最多 9 张、每张 10MB；区域内允许带文字格式的截图，文本框继续正常粘贴文字。附件仍由 composer 管理，同步占位防连续上传超过上限，上传失败释放名额并明确反馈，关闭重开后旧响应不进入新记录。
- 验证：跟进/上传及表格视图 24 项测试通过，表格偏好断言通过；前端构建、增量约定和 diff 检查通过。构建保留既有包体积及 auth 静态/动态导入提示。Git 巡检 `--no-fetch` 已运行，仅代表本地远端引用快照。
- 浏览器只验证了模拟数据下的桌面统计筛选、操作栏、待办卡和跟进抽屉。真实 Ctrl+V 验收先遇虚拟剪贴板无数据，随后原生浏览器控制因无法可靠确定 URL 被工具安全检查终止；未绕过。系统剪贴板、窄屏、拖拽及表格工具实点仍未完成；上传和拖拽事件通过组件方法与 composable 组合测试覆盖，不等同于浏览器实测。模拟验收入口备份在下述截图目录的 `recovery/frontend/tmp/followup-preview/`，复验时复制到前端同名 tmp 路径即可；所有 API 为模拟，无真实业务写入。
- 桌面和抽屉截图：`C:/Users/windb/.codex/visualizations/2026/11/02/01a19aaa-65c7-7a92-bce4-03ce443f219b/followup-ui/`。用户已明确授权本次提交、合并到 main 并推送 origin；暂不部署。合并后清理本任务 worktree，保留模拟验收恢复材料与构建日志。

## 2026-11-02 PK海报突出人均新签（Codex，Git交付，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-pk-average`，分支 `codex/pk-average-poster`，基于 `eecd47c8`。用户要求4人对5人时按平均新签优胜，并查看海报如何在总数之外展示平均值。
- 已核对 `award_statistics.pk` 使用人均新签数→人均新签金额→人均月GMV判定，本轮不改业务优胜/奖金规则。在固定底图下方增加人均对比条，保留原总数、目标与进度；显示人数、两位小数的人均值及“总数÷人数”，并解释真实领先/同分破局指标。未再重绘人物底图。
- 183项奖项与PK海报测试通过，新增25/4胜过30/5、24/4与30/5持平、金额/GMV破局、异常/未开赛/已结束显示回归；视觉反馈后定点28项通过。离线覆盖两侧领先、持平、金额破局、异常、未开赛、结束及大数值；使用同一HTML与Node Playwright，不冒充Python截图链路验收。修正已达标状态文案、未开赛人均遮蔽和数字行高。增量约定与diff检查通过，Git巡检--no-fetch完成。模拟图在当前会话visualizations的 `pk-average/`，不含真实经营数据、不外发。
- 用户已授权本次提交、合并与推送，按本需求范围交付Git；最终引用以读回为准。本轮不部署，主目录其他未提交成果保留。

## 2026-11-02 出库单退货退款入口收纳（Codex，Git 交付，未部署）

- 工作区 `D:/MyProgram/commission-system-codex-outbound-return-menu`，分支 `codex/outbound-return-menu`。将出库单列表的“退货退款”移入每行“更多”菜单；保留原单据条件、权限指令和跳转，补齐仅有退货权限时的菜单显示条件。
- 验证：前端构建、增量约定检查及 diff 检查通过；出库列表/队列 13 项与退货 19 项既有回归通过（退货测试须启用 `--experimental-vm-modules`）；菜单结构及 6 种显示场景检查通过。未进行浏览器实点验收。
- Git 巡检 `--no-fetch` 已执行。本轮用户已授权本次调整的提交、合并与推送，并明确确认将 main 的 70 个既有未推送提交一并推送 origin。按钮调整提交 `f032c84a` 已合入本地 main，最终远端状态以 Git 引用读回为准。本次不部署。

## 2026-11-02 commerce-transition 合入后旧流程修复 B/C/D 批（Claude Code，分支 claude/commerce-legacy-fixes，已合入 main，未部署）

- 范围：回款发送人放宽与重试接手、超时锁死的人工解锁（开票/回款/出库同步/补货出库/预售运费与出库/回款删除放弃）、发送 claim 租约（180 秒）、软删除草稿释放发票号与截图、native 菜单按交易阶段显示、冻结订单的运维解冻流程（`docs/runbook.md`「订单办理权冻结」）。
- 已知风险：
  - 订单删除（order_remove）与取消订单（cancel-order）超时未决时，没有「放弃并释放」入口。订单在发出删除前已置为 `cancel_pending`，生产版本里该状态本来就挡住同一订单的推单、回款和出库，所以影响范围与改造前相同：只影响这一张订单，不扩散。需要恢复时按原删除/取消入口继续核验。
  - 预售运费 uncertain 的管理员重试只开放了 API（`POST /api/shipments/{id}/retry-freight`），生产版本里也没有前端入口，目前只能由管理员通过 API 或 Codex 操作。
  - 冻结订单只能按运维手册走维护工单解冻，系统没有解冻入口。
- 状态：已合入本地 main（未推送），未部署。回归基线：`-k "commerce or receipt or invoice or outbound or presale or shipping" --ignore=tests/portal_mysql` 21 failed / 48 errors（portal 测试元数据），均为 main 既有失败，零新增。

## 2026-11-01 战报推送时段与 PK 名单（Codex，名单已保存，代码未部署）

- 用户确认年度奖周一至周五09:00/16:00、PK奖09:01/16:01（北京时间）；刘婷退出PK，一组4人/目标24/基础400。线上战报ID3通过设置保存，版本2→3，22:26:44审计核对其余9人及规则不变；未外发消息。
- 工作区 `D:/MyProgram/commission-system-codex-battle-awards-nov`，分支 `codex/battle-awards-nov`，本轮已获合并与推送授权，仅交付本需求 Git 变更、不部署；最终引用读回为准。实现独立调度及重试、旧账本去重、暂停策略继承、配置文案、4人预设、两张去除刘婷的底图及姓名数字覆盖层；按后续反馈修正罗馨瑜的头型、五官/眼镜比例和过度倾斜。
- 225项奖项/海报测试通过；最终调度及运营中心52项通过，合计277项不同测试；前端构建、增量约定、diff检查通过；独立审查已修复问题。三种完整海报以合成数据离线渲染、9人对位无溢出/外部请求。Python环境缺Playwright，图像验收使用同一HTML+Node Playwright。
- 线上新时间和底图仍待授权发布；办公室入口未登录，cloud页面配置状态不能代表单活调度器。详见 [交付记录](reports/2026-11-01-battle-awards-schedule-roster.md)。

## 2026-10-31 内贸客户跟进一期（Claude Code，待部署）

- 工作区 `D:/MyProgram/commission-system-followup`，分支 `claude/domestic-followup`；迁移 `246_domestic_followup`，接在 `245_commerce_transition` 之后，仅新建 8 张表（见 database.md）并种三个 `sys_dict` type 初值，不改既有表，非破坏性，不需要冻结写实例。部署只走 `deploy\deploy.bat`，由它统一执行迁移；Scheduler 单活，3 个新任务（每日汇总 + 两次补发、紧急异常推送、每日维护）只在办公室 scheduler 实例上跑。
- **部署后亮哥要在后台做的事**：
  - 角色管理页给业务员分配 `domestic_followup:read` / `domestic_followup:write`，给主管分配 `domestic_followup:read_all`，给管理员分配 `domestic_followup:admin`。**已登录用户要退出重新登录**才拿到新权限（权限在登录令牌里）。转交选人只列持有 `domestic_followup:write` 的在职用户（超管视同持有），没分配的人搜不到、也转不过去。
  - 工作台右上「跟进设置」里设置紧急异常接收人（`urgent_receiver_user_ids`）；不设则紧急异常只记日志、不推送。**接收人必须持有 `domestic_followup:read_all`**（或超管），否则保存会被拒——没有全部范围的人点开推送看不到客户。
  - 同一弹窗里配置**兜底负责人**（`fallback_assignee_user_id`）：客户无归属且发货经办人已停用时，收货回访交给他；不设则这类回访只记日志、不生成。
  - 确认生产 `DOMESTIC_REVIEW_NOTICE_BASE_URL` 指向业务员实际使用的站点（推送里的「打开跟进工作台」链接用它拼）。
  - 两个 preset 启动时自动绑定与发票截图导入相同的视觉模型（`TeamRouter-Chat` / `claude-fable-5`，不退回其他 provider）；若该 provider 未启用则不会自动建 preset，需在 AI 管理页手工建并绑定视觉模型。
  - 后台 AI 整理/截图 OCR 走独立线程池，**并发上限 3**；超出的排队，前端最多等约 150 秒，没整理完会提示稍后从「我的草稿」继续。
- **已知未做 / 一期简化**（详见 module-notes.md「内贸客户跟进」专题）：列表与时间线有 N+1 查询；未绑定截图的物理文件不清理；AI 整理中用骨架屏代替分阶段进度文案；时间线不展开 OCR 文本，只给原图按钮；工作台没有搜索与筛选；决策台画像接入、小程序/微信 Agent 录入、历史 Excel 导入三项留到二期。
- **已知测试环境问题（与本分支无关）**：`tests/portal_mysql/conftest.py` 在收集阶段报 `INTERNALERROR`，跑后端全量测试要加 `--ignore=tests/portal_mysql` 绕开，否则整个收集会被拖垮。

## 2026-10-30 外贸退货单（Codex，Git交付，未部署）

- 隔离目录 `D:/MyProgram/commission-system-codex-sales-return-design`，分支 `codex/sales-return-design`，基点 `ecfba4b7`；[设计契约](requirements/2026-10-30-sales-return-order-design.md)、[实施验收记录](reports/2026-10-30-sales-return-implementation.md)。本轮按用户授权提交、合入 main 并推送 origin，不部署、不执行生产迁移；最终 Git 交付状态以引用读回为准。
- 完成客户/已出库外贸订单/精确原产品行选择、退货或仅退款、草稿预览生效、不可变本地负数回款、净应收、当期GMV与原人员原比例提成扣回；实际现金付款证据和反向更正独立保护。用户例1000/实收600整退为GMV-1000、回款-600、未收减免400，零现金不生成假回款。
- 预售按原批次实收本金退款；剩余合法收款和后批发货使用净资金投影，原报价/应用/回款原值保留。后批已用信用与冻结退货来源不能再次退款或不合法冲销。合法先出库零实收支持D>0/R0；超净债权未收预登记必须核对原款。缺历史计提证据待核对，禁止套用现人员。
- 实收及分次续检已实现；**权威入库接口未接通，不自动增加可售库存**，页面明确待权威入库接入。首期无内贸、无小满负回款外发。
- Chrome实际验收已完成整退、统一回款、Q4提成、收货与两次检验、窄屏和保存关闭保护。前端25回归通过、build通过；扩大后端2393通过/18失败/3跳过，18失败在原HEAD独立导出全部复现。最终核心201通过，末次独立复验54通过，真实MySQL并发7通过，独立代码审查无剩余阻断；各组部分重叠，完整口径见验收记录。
- 新迁移214（8表及synced_payment.source）已在独占本地MySQL验证，不对共享RDS执行。严格增量约定及diff检查通过；Git巡检 `--no-fetch` 仅本地快照，其他任务未动。停止旧预览进程和清理本次隔离测试目录被自动审批拦截，均未执行；本地验收使用4323/4324新端口，临时材料保留。

## 2026-10-30 出库单按实际订单业务员过滤（Codex，Git交付，未部署）

- 分支 `codex/outbound-order-scope`，基点 `7b5fdd0b`；本轮按用户授权提交、合入 main 并推送 origin，不部署。无迁移及生产写入，原主工作区未提交改动须保留；实际 Git 交付状态以引用读回为准。
- 移除客户历史订单授予其他出库单访问权的规则；正式单按明细实际关联订单业务员及同客户过滤。订单镜像缺失时保留同一订单的成功首推核验，已有镜像实际归属优先。队列预览同步口径，防止旧本地归属的任务重新冒出。
- 共用范围覆盖出库列表/详情/打印/Word、库存、看板及继承范围的验货/媒体；缺关联不放行、缺关联列报错，全量权限不变。用户案例 93851 通过只读实库候选查询验证：宋化通 0 条且详情拒绝，罗馨瑜及全量范围各 1 条且详情可见。核心回归 79 通过；扩展出库/验货 595 通过、3 项失败均在未修改基线独立复现。独立审查发现并修复旧本地任务再现边界，最终复审通过。约定检查、diff 检查及本地 Git 巡检完成。见[验收记录](reports/2026-10-30-outbound-order-scope.md)。

## 2026-10-30 外贸回款截图改为选填（Codex，Git交付，未部署）

- 用户已授权本次提交、合入main并推送origin，不部署；仅交付本任务改动并保留主目录既有未提交成果。最终Git状态以引用回读为准。工作区 `D:/MyProgram/commission-system-codex-receipt-sync-message`，分支 `codex/receipt-sync-message`。只读核验订单 1528「李宝珠261005」：ready/not_synced，总额 USD 3184.63；回款草稿 USD 2939.48、日期/方式已填、截图为空，无执行令牌、小满订单号、推单日志或回款记录。未修改生产业务数据，未执行推单。
- 用户随后明确取消截图必填：统一放开订单同步、自动回款生成/发送、手工补登记、汇总回款、预售发货附带回款和已生成自动回款截图编辑。前端标注选填，汇总/发货未确认提交恢复记录允许空截图。创建可省略附件，修改必须显式传附件列表，`[]` 才表示清空；原文件与审计保留。非空截图的权限、归属、文件完整性、最多5张和去重校验继续执行；金额、日期、方式、资金占用、执行权和幂等保持原规则，无需迁移。其余明确回款校验继续通过 `ReceiptSyncBlocked` 展示安全提示，未知错误仍脱敏。
- 本轮相关后端 235 项通过，另新增2项修改必须显式选择附件的Schema回归通过；前端36项通过，最终前端构建、增量约定、diff空白检查通过。无图自动生成/投递、手工及汇总幂等、清空截图后旧图403/404边界和金额保留均有隔离验证。Chromium mock验收五场景通过：订单补登记、汇总回款、预售发货附带回款无截图实际POST，以及新版/旧版清空最后截图的实际PUT，截图选填且无必填星号，无页面异常；证据在 `frontend/tmp/optional-receipt-proofs/`，临时Vite已停止。独立审查发现并已修复汇总/发货恢复记录遗留限制和修改省略附件误清图风险，终审无阻断。前一轮扩大到未修改保存校验文件时有4项基线失败（fixture的inspection_requirement=None），以HEAD原业务模块复验确认，与本次无关，未扩大修复。测试均为隔离SQLite/替身，未调用真实Provider。`git_sweep.py --no-fetch`仅核对本地快照，不处理其他任务分支。本轮仅Git交付，不部署；该订单的缺截图拦截需本次规则上线才会解除。

## 2026-10-29 验货单上传物流单改为弹框录入＋自动关联（Claude Code，已提交 main，未推送，未部署）

- 需求：验货单列表操作列直接「上传物流单」，弹框复用运单上传页（OCR/手录/去重），按订单客户预填收件人与国家；保存同时进入物流跟踪并关联验货单。原实现要求先去运单上传页录入，再回抽屉手填运单号+物流商代码，且关联校验依赖 PC 上传从不写入的 `source_image_url`，PC 录入的运单实际关联不上。
- 后端：新增 `app/shipping_inspection/shipment_link_service.py`（预填口径、入库前置校验、录入后关联）与 `GET /records/{id}/shipment-prefill`、`POST /records/{id}/shipment`；原 `PUT /records/{id}/shipment` 保留作「关联已有运单」。去掉关联与客户门户发货可见性中的运单图片门槛（行为变化：员工关联的手录运单会在客户门户展示）。列表返回 `shipment` 简要信息。无新迁移（沿用已上线 212 的 `shipment_tracking_id/shipment_version`）。
- 前端：运单上传表单抽成 `tracking/components/WaybillUploadForm.vue`，独立页与验货单弹框共用；列表新增「物流单号」列和操作列按钮（需 `tracking:write` + 验货单 write/admin），详情抽屉改为展示+同一弹框入口。顺带清掉 `WaybillUpload.vue` 的 UI 债务基线条目。
- 对抗性审查后补：关联已有运单前核对接口 `shipment-candidate`（范围外不给必败按钮、收件信息不一致警告）；关联失败自动刷新版本号；预检/关联放线程池避免行锁等待卡事件循环；补齐路由兜底异常日志与 `upload_service` 吞异常的 print；预填降级不再二次查库；国家不再用档案国家代码。只有 `tracking:read` 的用户失去关联入口，属有意收紧。
- 验证：前端构建、`check_conventions` 增量通过；`test_shipping_shipment_link.py` 16 项 + 验货/物流跟踪相关共 121 项通过，门户 19 项在无 `.env` 的隔离副本通过。未在浏览器里实际点过弹框（本机未起后端，起后端会连共享库）。

## 2026-10-29 目标设置与绩效看板优化（Codex，Git 交付，未部署）

- 分支 `codex/perf-goal-ui-clarity`，工作区 `C:/Users/windb/.codex/worktrees/inspection-board-ui/commission-system`。用户已确认预览效果，授权本次优化提交、合入 main 并推送 origin；仅交付本次相关改动，不部署，保留主目录其他未提交改动。最终 Git 状态与保护文件恢复以引用回读和 SHA256 校验为准。
- 目标页按真实指标筛选战队行，允许有效未设目标成员录入，保留未绑定/归档/权限限制；目标草稿支持取消、放弃及保存后切换，写入中拦截离页。修正月度季度槽位、覆盖值明确清除、拆分预览跨季度合并/参数失效，保留服务端计算与留痕。
- 看板明细继承对象和周期日期，区分当前分析与权限内全员/本队对比；角色默认范围与服务端一致。新增向后兼容只读 `listed_only` 参数，默认 false，仅为公司默认明细收窄到有年度目标人员。修正空信封及比例显示单位，不改金额/人数/百分点计算。
- 首列/表头固定、校验短摘要与差异定位、保存栏可达；时间图及成员明细按需展开，累积/单期切换共用趋势区域；失败和真实空态分离。
- 后续两轮：明确完成率与零/空目标、将 pp 和双重负号改为直白百分点说明，指标口径按需展开；冲刺提醒区分空提示与无法判断。人员本地查找保留全队小计、全量校验/保存/草稿保护，补齐查找键盘定位和排序方向语义；合计差异为提示色，无效输入仍阻止保存；窄屏图例和触控目标收尾。未改后端、指标公式或权限。
- 验证：后续两轮后的 45 项相关前端 Node 测试、构建、严格增量约定、diff 空白检查通过；第一轮的 33 项 SQLite 内存后端测试通过，后续两轮未改后端；Impeccable 本次目标静态检测无发现。保留既有大分包和 SQLite 日期适配弃用警告。独立审查问题均已修复并定点读回；真实组件 Playwright 覆盖草稿三种选择、写入延迟、指标/日期/单位契约、空态错误、admin/captain/sales 权限、1440px/390px、首列固定、保存可达、图表切换与窄屏刻度，无页面运行错误或文档横向溢出。
- 后续两轮浏览器补测：零/缺目标、130% 完成率和负百分点、未知/零工作日进度、未来周期、查找隐藏草稿的保护与全量保存、全队小计不变、查找 Enter/Escape、键盘排序 aria-sort、reader/归档只读、1440px/390px 均通过。截图及实际回归证据以 `frontend/tmp/perf-goal-review/browser/after-rounds-*` 保存；既有 v4/baseline 证据保留。
- 已打开独立可见浏览器窗口的两个预览页签：`http://127.0.0.1:4319/tmp/perf-goal-review/index.html?view=target` / `?view=dashboard`。预览使用合成数据，模拟写入仅存内存，服务端/浏览器阻断真实 API 与外部请求；不代表生产验收。截图/回归脚本保留在忽略目录 `frontend/tmp/perf-goal-review/`。4319 服务 PID 37668，预览控制 PID 52540，用户关闭浏览器窗口后控制进程退出；旧 4317/4318 未动。

## 2026-10-29 Impeccable 按需接入规则（Codex，Git 交付，未部署）

- 将主目录已有的 Impeccable 项目适配规则单独纳入版本管理：`DESIGN.md` 是唯一维护来源，`CLAUDE.md` 13.5 只添加指针；保留已有设计体系、各前端 token 与组件、Emil 动效要求及业务权限边界。
- 按问题选择评审、强化边界或简化方法，复用现有检查和已取得的证据；不默认串联全套命令、初始化档案、重写设计规范、强制评分/追问、自动启用 Hook 或增加审批与 CI 门禁。技能缺失时继续既有流程。
- 用户授权本次独立提交、合入 main 并推送 origin，使后续从最新 main 创建的工作区继承规则；第三方技能仍按用户级安装，不复制进仓库。本次只交付规则和交接记录，不部署，保护主目录其他未提交改动；结果以 Git 引用及恢复校验回读为准。
- 验证按纯文档范围检查规则唯一性、引用锚点、内容边界与严格增量约定；不运行无关构建或业务/数据库操作。

## 2026-10-29 出库筛选恢复与快捷导航（Codex，Git 交付，未部署）

- 工作区 `C:/Users/windb/.codex/worktrees/inspection-board-ui/commission-system`；分支 `codex/list-state-quick-navigation`。用户已确认预览效果，授权本次提交、合入 main 并推送 origin；仅交付本次筛选恢复与快捷导航改动，保护主目录其他未提交内容，不部署。最终状态以 Git 引用回读和保护文件校验为准。
- 出库列表新增已生效条件文字回显、逐项移除及 URL 筛选/分页/排序恢复。未提交草稿不参与分页、刷新或条件移除请求；移除一项保留其他草稿。URL 为历史恢复依据，现有页签沿用完整地址；问题单跳转保留原业务入口。
- 顶栏新增 `Ctrl/⌘ + K` 页面快捷导航，复用现有 Element Plus、导航配置及 route/menu/group 权限交集；侧栏共用同一过滤源，支持实时撤权和点击前再检查。
- 验证：相关 36 项 Node 测试、前端构建、严格增量规范检查、diff 空白检查通过；Impeccable 新增 UI 组件静态检测无发现。独立审查发现的空历史地址被缓存条件覆盖、移除条件丢失其他草稿已修复并加入回归；排序列隐藏后再显示会同步方向，摘要可读且可清除。构建保留既有大分包警告。
- 真实组件 + 隔离模拟 API 浏览器验证覆盖 URL/刷新/前后退/问题链接、草稿隔离与单次请求、快捷键/焦点/实时撤权、错误空态。390px 弹框宽 366px，左右各留 12px；隐藏/恢复排序列不新增请求，移除排序保留草稿且只读一次。预览入口 `http://127.0.0.1:4318/tmp/list-navigation/shipping/outbound`，辅助文件在忽略目录 `frontend/tmp/list-navigation/`；预览已补正式 app.css，页面及模块 HTTP 200；最终样式复看时浏览器控制超时，应用内打开请求排队，尚未确认自动显示。业务写操作与生产验收不在本次范围。Git 巡检已运行 `--no-fetch`，仅本地引用快照。

## 2026-10-29 发货检验看板第一轮视觉简化（Codex，Git 交付，未部署）

- 独立工作区 `C:/Users/windb/.codex/worktrees/inspection-board-ui/commission-system`，分支 `codex/inspection-board-ui`，基点 `53a98a52`。用户已确认本地预览效果并授权本次提交、合入 main 和推送 origin；交付只含看板模板 / 局部 CSS 与对应设计说明，保留主目录其他未提交改动。Git 完成状态以提交和远端引用回读为准，不部署。
- 收敛行装饰：取消侧边色条、持续发光、行入场与随机头像色；保留业务标签和超时 / 大单语义色。顶部统计、今日成果改以读数为主，删除重复环图 / 分段条 / 工作量小格，完成率保留原计算。单号列更宽，表头和数字对齐，长数字自适应字号，长单号 / 姓名保留完整提示。
- 验证：现有看板逻辑 7 项通过；Vue 模板编译与源码对照确认统计 / 金额 / 分页计算、纯逻辑、运行态 composable、七天图表、全局 token 及新签提醒模板保持原样。浏览器用实际组件 + 隔离模拟 API，1366×768 / 1280×720 的常态、长单号 / 姓名、百万件数、三标签、十行、空态、读取失败、新签弹框关闭及轮播置顶通过；1920×1080 只做 DOM / 缩放坐标核对，浏览器截图裁切限制不作为完整截图通过证据。未接入生产数据，不代表仓库远距离业务验收。
- 读取失败提示遮挡顶部部分标题在改版前同样存在，本轮未扩展处理。临时验收夹具在 `frontend/tmp/inspection-board-ui/`，构建和检测证据在 `tmp/inspection-board-ui/`，不进入业务源码；最终前端生产构建、严格约定检查、差异空白检查与 Git 巡检（`--no-fetch`，本地引用快照）通过；Impeccable 定向检测 0 项。构建保留既有大包体提示；本地预览已按用户要求重新打开（仅模拟数据），完整结果在 `tmp/inspection-board-ui/validation.json`。

## 2026-10-29 出库单打印历史单据按已提交展示（DSH，已合入 main 并推送 origin，未部署）

- 需求：出库单打印页中出库日期早于 2026-10-01、当前「未检验」的出库单统一显示「已提交」。用户确认只改显示，不补建验货单记录。
- 生产只读核对：符合条件 5838 张（2025-03-28～2026-09-30；2025 年 65 张、2026 年 5773 张）；13 张草稿、431 张已提交保持真实状态。同日用真实队列查询只读复核：分界前 已提交 6212 / 检验中 12 / 未检验 0，口径生效。
- 实现：`app/shipping_inspection/constants.py` 的 `LEGACY_OUTBOUND_BEFORE` 是唯一分界；列表返回 `status=submitted` 并附 `inspection_legacy=true`；`inspection_status` 筛选和排序同口径（`list_sort_service`）；看板待检队列排除历史单。已有验货单的单据（含草稿）仍返回真实状态。验货单列表/照片/PDF、发票详情实际出库进度不受影响（发票侧仍按 `not_inspected` 计算）。
- 验证：新增 `tests/test_shipping_legacy_inspection.py` 12 项通过；发货检验/出库/发票详情相关共 527 项通过（`test_outbound_invoice_sync.py::test_invoice_sync_followup_rejects_another_users_invoice` 在基线 `53a98a52` 同样失败，与本改动无关）；前端生产构建通过。

## 2026-10-28 仓库发货检验看板（Accio，分支待合并，未部署）

- 分支 `accio/inspection-board`，独立worktree。新增全屏页 `/shipping/board`（菜单：发货检验 → 发货检验看板，沿用 `shipping_inspection:read/write/admin`，数据范围同出库单列表，无 read_all 只看本人绑定客户）与只读接口 `GET /api/shipping-inspection/board`；无迁移、无写操作。
- 待检：最近30天创建、检验未提交的 OKKI 镜像出库单（草稿标「检验中」，本地推单任务不计）；排序新签（最新在上）> S > A > 其余（等待最久在上），优先单固定，普通单10秒翻页。新签/详检/客户等级与出库打印同口径（明细订单精确关联+同客户校验）；客户名前3位脱敏。
- 今日：按北京时间提交日统计出库单/产品件数/客户数，订单金额取 `okki_orders.amount_usd` 按订单去重，缺金额的订单单独计数不猜；近7天柱=单数、线=件数；完成列表为单号-客户-业务员-提交时间-检验员（`submitted_by`=实际操作人）。完成率=今日完成/(今日完成+当前待检)。
- 新签弹框：30秒轮询，新出现的新签单弹全屏框（20秒自动关闭/点击关闭，多单排队）并提示音；已见列表存浏览器 localStorage，首次开机只弹30分钟内生成的。浏览器需允许该站自动播放声音。
- 验证：后端看板6项（含北京00:00跨日、服务器非东八区、拆单金额去重、权限/无绑定422）+发货检验相关共41项通过；前端逻辑7项、生产构建、增量约定检查通过；mock接口驱动真实组件在1920×1080与1366×768截图核对，控制台无错误、无溢出。`git_sweep.py` 需 tzdata，已用后端 venv 运行。

## 2026-10-27 订单明细分组与最新 main 全局发布（Kimi，已部署）

- 分支 `kimi/invoice-item-groups` 提供持久化明细分组、自定义名称、全部/分组视图、当前组新增/复制/Excel 粘贴、跨组移动及空组删除；已加入出库单的行显示出库与部分/实际发货状态。分组仅用于展示，不改变金额、库存、出库、打印导出、门户或 OKKI 同步。功能提交 `e962b982f5d59180660bf6add4ade290eb95d8dc`，迁移文档修正及最终发布版本 `081b7879cbfc489027ac3bafae86c862cb8e6053`，已合入并推送 main。
- 最新主线原有 `206`–`208` 已先集成，本期迁移顺延为 `209_invoice_item_groups`，接 `208_invoice_inspection_photos`；历史产品行按订单与创建日生成稳定分组，配件不归组。办公室统一 `deploy/deploy.bat` 固定候选预检及正式发布均成功，回执 `MANAGED APPLICATION RELEASE COMPLETED`，scope `office-and-cloud`、schema `209_invoice_item_groups`、`deferred=[]`，出库 timer 恢复原 active/enabled；静态与候选保留清理仍按受管维护入口 deferred。
- 验证：本期及迁移链后端 41 项、前端 140 项、生产构建和隔离浏览器全流程通过。合并后较大回归为 867 passed/11 failed，其中 9 个 `inspection_requirement` 失败在干净 `4154ae82` 同样复现，另 1 个为既有 `unique_id="line-1"` 严格回读夹具失败；未将这些主线基线问题夹带为本期修复。
- 生产独立核验：办公室 HEAD `081b7879`、health ok/database connected、`alembic current=209_invoice_item_groups (head)`；北京 health ok/database connected，`ark-backend` 与出库 timer 均 active。`leshine.cloud` 与 `leshine.work` 首页 SHA256 均为 `f4cf006ac33fa0c5c58ddd8d199324bf04b78c0b6c46616c605b446ddf6f3c47`，与本地候选一致；两站主 JS 摘要一致并引用 `InvoiceManage-9DNhVD5B.js`。PM 与客户门户均 HTTP 200。未纳管独立服务、APK、小程序与浏览器扩展安装不属于本次全局应用发布范围。

## 2026-10-27 订单检验要求与出库打印标记（Codex，Git交付，未部署）

- 分支 `codex/invoice-inspection-requirement`，独立工作区；新旧发票录入在小满标记下增加必选单张/明细检验照片，默认随新成交属性、手动修改优先、保存重开保留。出库打印右上角独立加粗大字显示“新签”“拍摄明细照片”，Word同步。
- 新迁移 `208_invoice_inspection_photos`；隔离SQLite验证存量回填、数据保留和单head，未执行共享/生产迁移。旧关联任务快照与原命令恢复保持严格内容/身份校验；历史NULL新签按明确成功推单证据识别。
- 后端117项、前端25项、生产构建、增量约定及差异检查通过；Edge隔离桌面/手机表单、保存回读、键盘和四种打印组合通过，页面异常0。独立审查问题均已修复并复核。用户已授权提交、合入main并推送origin，最终以Git引用回读为准；未部署。主目录无关改动按SHA256备份保护；见[验证与预览](reports/2026-10-27-invoice-inspection-requirement.md)。

## 2026-10-27 验货单查看超时（Codex，Git交付，未部署）

- 分支 `codex/inspection-view-timeout`，独立worktree；用户已授权提交、合入main并推送origin，最终状态以Git引用回读为准；未部署。用户确认所有单据；线上1006/1002详情200，约3MB原图跨办公室/新加坡/北京链路在前端60秒超时前只收到约半张，原照片墙还等待整组下载后才显示。
- 增加同权限媒体预览 `preview=true`（640像素JPEG），3并发逐张显示、单张失败重试；点击才取原图，切单/关闭取消并回收URL。原件、打印/PDF、验货状态及权限不变。大图先缩后校正方向，图库打开时冻结顺序，避免内存放大与当前照片跳变。
- 相关后端回归47项、最终预览7项、前端20项、生产构建及约定检查通过；Edge隔离验证6条交互路径、390px布局及页面异常0，独立复核通过。Git巡检已运行（`--no-fetch`，本地引用快照）。具体证据、环境与交付边界见[报告](reports/2026-10-27-inspection-view-timeout.md)。

## 2026-10-27 内贸发货批次取消（Codex，Git交付，未部署）

- 用户已授权本次提交、合入 main 并推送 origin；主目录无关改动按 SHA256 备份保护，最终交付以 Git 引用回读为准，不部署。
- 分支 `codex/domestic-cancel-batch`：交付对账新增取消批次按钮和确认提示，恢复可发件与原订单状态，保留已取消清单及件号/操作者/北京时间快照，不退订单款；已收货、存在任何核销关联或订单已终止/失效时拒绝取消。
- 确认收货只记交付事实，不扣客户余额；订单正式生效/价格审核通过时扣款，批次调价不修改原订单账本。新增回归验证收货重复请求、取消和重发均不重复记账。
- 迁移 `206_domestic_shipment_cancel` 增加三个可空审计字段，旧批次无回填，单一 head；未执行共享/生产迁移。取消与收款按客户行串行，退款计数不锁批次；原单条发货入口按取消次数换发货周期键，支持倒序取消旧批次后重发。
- 后端相关回归 165 项通过；前端选择测试4项和构建通过。Edge隔离验收覆盖取消确认/保留、历史及汇总恢复、CSV导出、同件重发与390px操作，页面异常为0。独立审查发现的锁顺序与原入口幂等边界已修复并复核通过。验证详情见 [报告](reports/2026-10-27-domestic-shipment-cancel.md)。

## 2026-10-27 内贸创建发货批次列顺序（Codex，Git 交付，未部署）

- 分支 `codex/domestic-shipment-columns`；创建发货批次列表将“本次发、订单单价、本批单价、本次金额”紧接“产品规格”，后接“下单、完工、已发、可发、具体件号”。只移动列声明，保留输入绑定、金额计算、选择和排序逻辑。
- 验证：前端构建、现有发货选择/状态测试 5 项、增量约定检查与差异空白检查通过；模板解析确认 15 列定义和脚本内容均保留，仅列顺序变化。未连接生产创建发货批次。Git 巡检已运行（`--no-fetch`，本地引用快照）。
- 用户已授权本次提交、合入 main 并推送 origin；主目录无关改动按 SHA256 备份保护，最终交付状态以 Git 引用回读为准，不部署。

## 2026-10-27 普通订单同步后的出库延续（Codex，三张生产单已更新；Git交付，未部署）

- 已按授权更新原出库：`Tessie-KC-1003 / 1407`、`Tessie-KC-1004 / 1415`、`田雯261011 / 1379`。每张仅一次实际出库 POST，分别回读后再独立进程全量核验；订单、回款和首次出库任务不变，方舟镜像已更新。田雯单并发上传的三张旧照片保留并失效，验货草稿需要仓库补验。
- 根因：订单 commit 后 ORM 失效，跨阶段读取 `invoice.id` 隐式重开事务，被出库的新事务授权入口拒绝。修复冻结身份及提交回执恢复结果；出库409/503单独返回待核对，401/403/404仍拒绝，返回前重新授权，未知发送不重发。
- 分支 `codex/invoice-outbound-followup`。无新迁移；用户已授权本次提交、合入main并推送origin，最终状态以Git引用回读为准；未部署。独立审查无阻断问题，测试使用独占隔离 MySQL，明细与执行证据见[处理报告](reports/2026-10-27-invoice-outbound-followup.md)。六文件去重274项通过，6项既有规格差异在未修改HEAD上全部复现；新增全链6项及延续权限51项全过，未宣称全量全绿。
- `check_conventions.py`、`git diff --check`通过；`git_sweep.py --no-fetch`已运行，仅表示本地引用快照。自动审批策略拦截已结束测试数据库目录清理；临时数据库、维护备份及日志保留，未绕过拦截。

## 2026-10-27 38色现货选色工具发布完成（Codex，北京专项）

- **已部署版本**：`55d3bc5f60f50c3d116c23985c1a03a626774d1f`，线上 Git 检出干净；方舟主前端制品 `65998d1f1e742ba192c5540852d0674868fc7b63769c3b3bb6609f10834e428c`。`leshine.cloud` 与 `www.leshine.cloud` 首页 SHA256 均匹配候选；公网 JS 含“38色现货选色工具”和正确 URL，服务端/静态权限清单绑定候选并沿用库存色块图分组权限。侧栏原有外链组件使用 `target="_blank"` 和 `rel="noopener"`。
- **选色站已上线**：`https://color-guide.leshine.cloud/`，制品 `977b8678ef72ff13358cabacc9406bca6d95ddea8388e9ffec32b3033c563b67`，86 个文件公网逐一 SHA256 匹配；证书覆盖子域名，有效至北京时间2027-01-25 08:39:29，既有自动续期已启用。原网站内容保持不变。
- **验证**：专项隔离测试34过、既有导航前端测试18过、构建/约定检查通过；Nginx语法通过（保留既有IP站点protocol options警告）。北京API PID `1076912`、启动时间2026-10-26 11:39:27未变，`/health`为ok/database connected。无数据库迁移、无后端重启，办公室/新加坡未发布。
- **浏览器边界**：首页已加载并展示38色；后续计算机工具因无法可靠识别当前浏览器URL而硬性中止，未绕过限制，搜索/选择/导航实际点击不宣称已实测。服务器制品及既有组件的新标签页配置已核验。
- **Git交付**：代码在 `codex/color-guide-site`，已通过受管bundle部署；随后用户授权将本次源码、部署支持与发布记录合并推送。此次Git整合保持上述线上版本，不重复部署；主目录无关改动按SHA256备份保护。
- 证据：本任务 `.deploy_state/color-guide/{site-current.json,public-verification.json,navigation/result.json,navigation/public-readback.json}`，服务器 `.deploy_state/color-guide-{site,navigation}/` 保留配置/源码恢复记录；操作见 [选色工具部署](../deploy/color-guide.md)。

## 2026-10-27 38色选色工具与方舟入口（Codex，静态站已上线；导航候选待切换）

- 用户授权将指定 v11 静态站部署到北京 `color-guide.leshine.cloud`，并在方舟“库存色块图”下新增“38色现货选色工具”，新标签页直开。源 ZIP SHA256：`4292d862ff2efd24d477daf30d411f459f4c0c360a7673c4e6c0d9f7b6e21cef`。
- 已通过 `deploy.bat --color-guide-site` 发布 86 个静态文件、独立 HTTPS 证书与 Nginx 站点；公网逐文件 SHA256 全部匹配，38 个颜色和 76 张使用中的图片完整。HTTP 转 HTTPS；API/隐藏文件/未知路径 404；既有 certbot.timer active/enabled，沿用续期 reload hook。
- 导航候选基于当前北京后端和主前端共同基线 `d6e56d82e6eef2d76744069c22b3a76dcdb26f45`；仅增加外链及生成权限清单，沿用 colorwork 分组任一权限。受管专项采用干净 Git bundle 候选与静态切换，避免生产脏文件阻断后续发布；不迁移数据库、不重启 API，不发布办公室/新加坡或其他本地主分支功能。
- 网站测试 14 项、导航既有前端测试 18 项通过，方舟构建成功；静态发布 Linux 专用单测在 Windows 跳过，不冒充执行通过。部署方法与回执位置见 [选色工具部署](../deploy/color-guide.md)。网站浏览器首页已加载并显示38色；后续点击因计算机工具无法可靠识别浏览器URL而中止，不计为交互验收通过。
- 此准备记录保留为历史；最终导航切换结果见上方发布完成记录。代码整合按随后用户的合并推送授权执行。

## 2026-10-27 客户门户登录页透明白字 LOGO（Codex，Git 交付，未部署）

- 分支 `codex/portal-login-white-logo`；登录页左上角改用仓库现有透明白色 LeShine 图片，复制至门户独立资源目录，保持 144px 显示宽度与原始比例。共享 BrandMark、申请/激活及登录后页面不变。
- `npm --prefix frontend-portal run build`、增量约定检查通过；Git 巡检已运行（`--no-fetch`，本地引用快照）。桌面 1440px / 手机 390px 的构建预览核对白字、透明背景、图片加载、表单和申请入口，无横向溢出或页面异常；仅以拦截的未登录会话响应展示页面，未提交真实登录或申请。
- 预览截图及检查结果保留在本 worktree 的 `tmp/portal-login-white-logo/`。用户已授权本次提交、合入 main 并推送 origin，最终以 Git refs 回读为准；不部署，线上只读核对仍使用原黄底 `logo.webp`。

## 2026-10-26 田雯261011 原单恢复与绑定参数契约（Codex，生产数据恢复；代码未部署）

- 用户授权将发票 `1379` 绑定既有小满订单 `26917 / 105885072282767` 并生成出库。已按完整实时证据恢复原绑定和两行 UID，保留原超时 unknown 事实及审计，未重新 POST 订单。
- 正常出库任务 `896` 已完成，尝试次数 1；回款意图 `439.89 USD / Other` 未改写或发送。原始备份和回读证据在主工作区 `tmp/maintenance/recover-1379-20261026-105450/`。
- `codex/invoice-bind-recovery` 修复门户 ID / 底层订单号参数错配引起的 500，并保留列表入口订单号。新增契约测试通过；相关回归及已核对基线失败见[报告](reports/2026-10-26-invoice-1379-recovery.md)。用户已授权提交、合入 main 并推送，最终以 Git refs 回读为准；本次不部署。
- 已实现自动 GET 原单核对：60 秒调度、新版本库存单首次推送、原租约过期后最多三轮，次数持久化；完整有效列表、原发送时间窗和全部商业/归属资料一致才恢复。原出库意图与当前开关同时允许才入队；回款意图不变。历史缺证据、生产半成品和资料冲突仍待人工核对。此能力尚未部署。

## 2026-10-26 PI导出隐藏中文内部型号（Codex，Git交付，未部署）

- 员工端 `leshine_pi` Excel/PDF 的 Product 列不再附加含中文的整段内部型号（如 `B3天才发帘（帘宽12″）`），保留英文产品名、纯英文型号、卷度、折扣和金额；不改原发票/订单数据，客户已发布PI快照路径不变。
- `tests/test_pi_template_export.py` 15项通过，覆盖两种格式、混合/纯中文型号移除、英文型号保留和源数据不变；独立审查通过。样例及可视核对图在 `tmp/pi-english-model-20261026/`。本次已授权提交、合入main并推送origin；未部署。

## 2026-10-26 内贸数量终止、整单跳过与完成状态（Codex，Git交付，未部署）

- 分支 `codex/domestic-termination-skip`，独立 worktree `C:/Users/windb/.codex/worktrees/domestic-termination-skip/commission-system`；用户已授权本次提交、合入 main 并推送；功能提交 `bce2c594`；集成验证已完成，最终 refs 以交付回读为准。未部署，主目录既有改动按备份与逐文件校验保护。
- 明细终止支持选择未发货数量，按原成交价差额退款；保留真实工时、发货与单件审计。已终止码不可复用，普通加量及整单/单件打印支持非连续编号；有终止记录的明细禁止硬删。网络失败后关闭重开弹窗也保留原请求号。
- 详情新增“一键跳过全部工序”，沿用 `domestic_skip:write`，逐道写人工跳过审计、不生成工资或发货。整单事务、订单级幂等保证重试不影响后来新增明细；无路线则整次回滚。有效跳过参与完成回算，订单状态 2 显示“已完成”，真实全部发货保留状态 3“已发货”；撤销后重新回算。无真实末道报工时不展示整行登记发货按钮。
- 新迁移 `205_domestic_item_termination` 为订单和明细各加 nullable JSON 审计列；集成后单 head，父 revision 为最新主线的 `204_portal_delivery_profile`；未对共享/生产库执行迁移或业务写入。
- 验证：内存 SQLite 后端相关回归 219 passed；最后的可发货信息及打印断言另 2 passed，迁移数据保留/DDL及主线迁移链测试 8 passed。前端定向 19 passed，`npm run build` 通过（既有 chunk 大小与 auth 模块混合导入提示）；增量约定与 diff 检查通过。桌面 1440px/手机 390px 实际 Vue → 拦截 HTTP → FastAPI/SQLite 验证数量、退款、跳过、完成状态及不能凭跳过登记发货；无页面异常/未覆盖 API，测试服务已停止。没有在真实 MySQL 上重现并发，当前读锁语义由 SQL 契约与独立静态审查覆盖。
- 独立审查发现并修复失效码复活、稀疏码漏印、旧快照读、扩大重试范围及审计硬删，最终复核无阻断问题。证据保留 `tmp/domestic-completion-browser/` 和 `tmp/domestic-completion-build.log`；API/数据库/业务说明已同步。Git 巡检使用 `--no-fetch` 本地引用快照，不代表远端实时状态。
## 2026-10-26 Veronika 第二批撤销与保留运费（Codex，本地已实现，生产维护待发布）

- 用户要求先处理已在小满删除的 2026.Veronika赊销1002-02，并允许删除整张出库；已明确保留原121.16美元运费及抵扣，原回款不删。固定对象 invoice981 / settlement7 / outbound6 / remote105879019644375；拟释放10行40件及1415.54商品款应用9/10/11，保留运费应用12和远端运费105878936774347。
- 已完成只读删除核实、原始备份及维修预览，未执行生产业务撤销。旧版取消必须释放全部资金，不能安全保留运费；新终态 cancelled_keep_freight 需完整发布后再定点处理。用户现已明确授权合并、推送、受管部署并立即定点处理；当前发布尚待执行。
- 分支 codex/presale-deleted-cancel 实现新动作、来源/删除证明、事务与执行器锁、运费沿用及前后端终态口径。新增29项SQLite/供应商证明、5项真实MySQL和8场景浏览器验证通过；扩大回归199过、1既有GET隔离失败，构建通过。独立审查未见具体P1/P2。详见 [处理报告](reports/2026-10-26-presale-deleted-outbound-cancellation.md)。

## 2026-10-26 客户门户访问复制、图片与下单资料（Codex，Git交付，未部署）

- 分支 `codex/portal-customer-experience`，独立worktree；本地基于已取得的 `origin/main` 快照5020c97e。客户访问列表新增“复制”：选另一家方舟客户、填邮箱密码，原子复制查价/下单和商品权限并开通账号；不复制订单、专属价格、客户映射或收货资料。
- 线上只读证据确认#2B素材14716绑定正常，swatch `2c4de915-a355-4499-b4a7-a1de3ffa7d3b` 多次因授权锁等待5秒超时返回503，而同素材full随后200。图片改为两并发、主图优先、可视区加载，503只重试一次；服务端16MB缩放缓存保留原件完整性及前后授权检查。
- 侧边购物车可手输数量，沿用最小量/步长/10000上限；“Delivery details”可提前维护账号默认收货资料，空白结算自动填充，保留手改/报价/重购资料。迁移 `204_portal_delivery_profile` 接203，仅新增账号nullable JSON列；未在生产执行。
- 验证结果与路径见[实施报告](reports/2026-10-26-portal-customer-experience.md)。本次已授权提交、主目录合并和推送origin；主目录原有改动须按SHA256备份逐项保留。未部署，生产改善尚待发布后实测。

## 2026-10-26 WhatsApp 扫码后无法关联：rc14 未处理 companion_reg_refresh（Accio，已合并推送 main，未部署）

- 现场（办公室 Connector 诊断日志，只读）：10-26 两次扫码均在扫码后出现 `companion_reg_refresh`，此后无配对成功，`registered=false`，二维码用尽后 408 循环；无授权超时。Baileys `7.0.0-rc14` 未处理该通知，二维码继续携带服务器已作废的 adv secret，手机报关联失败（上游 [#2737](https://github.com/WhiskeySockets/Baileys/issues/2737)，修复 PR #2765 未合并，npm 最新仍为 rc14）。
- 修复（仅 Connector `manager.js`，分支 `accio/whatsapp-qr-refresh`）：按 WA Web/PR #2765 收到含 `companion_reg_refresh` 或 `pair-device-rotate-qr` 子节点的通知时，生成 32 字节新 secret 并在受控租约下持久化，用新 secret 重绘当前 ref，不消耗服务器 ref；之后 rc14 轮换出的二维码也替换为当前 secret。已有 `me`/已注册会话不改。
- 验证：新增 3 项测试（去掉修复后失败）；Connector 60 项通过（跳过既有不稳定跨进程用例）；真实 rc14 socket 离线冒烟确认凭据对象共享、secret 轮换、ref 不变、二维码带新 secret；finish_check 通过。真实扫码需部署后持有人重新关联验收。
- 发布：只需发布 Connector（重启 WhatsAppConnector 服务）。Baileys 发布含此修复的正式版后应升级并移除本补丁。
## 2026-10-23 浏览器标签页 LeShine LOGO（Codex，Git 交付，未部署）

- 分支 `codex/leshine-tab-logo`；主站 `frontend/index.html` 的 favicon 从 Vite 默认图标改为现有 `/logo.webp`，与平台侧栏共用 LeShine 品牌资源，登录和主站路由共用。
- `npm --prefix frontend run build`、约定检查、图标引用与 WebP 解码检查通过；Git 巡检已运行（`--no-fetch`，本地引用快照）。构建仅有既有大 chunk 提示。
- 用户已授权本次提交、合入 main 并推送，最终状态以 Git refs 回读为准；未部署。

## 2026-10-23 预售出库创建中断的原任务恢复（Codex，本地修复，未部署）

- 新增管理员“核实未生成并恢复”：人工确认原请求已终止且未生成，填写核实依据；服务端双次当前授权/完整图与尝试挑战校验、实时原编号GET，并全程共享出库执行器锁直到最终提交。只恢复原任务，保留全部编号、明细、回款与资金分配，命令不发送小满POST。
- 迟到创建成功持久化不可变审计并阻断后续发送；已提交但回执中断安全返回待读回；恢复开始使旧详情请求失效。无迁移。
- 新增算法28项、真实MySQL20项、前端15项与浏览器7场景验证，构建、约定和独立审查收尾结果见[报告](reports/2026-10-23-shipment-absence-recovery.md)。扩展回归1项未隔离小满鉴权的旧测试在干净HEAD同样失败，未改弱断言或使用生产凭据。
- 本地修复已提交，尚未合并、推送或部署；未对Veronika第二批执行恢复、重发或财务变更。当前进度保留在 `codex/shipment-absent-recovery` 独立worktree。Git巡检 `--no-fetch` 于22:17退出0，仅为本地远端引用快照；任务代码无未提交改动，另有未纳入提交的临时UI夹具。
- 临时UI测试服务与隔离MySQL均已停止；测试夹具、基线副本及临时MySQL目录的递归清理被自动审批拒绝（blocked by policy），原目录暂留且不纳入提交；验证摘要与浏览器证据保留在 `tmp/shipment-absence-validation.json`、`tmp/recovery-browser/`。

## 2026-10-23 订单发票与出库体验优化（Codex，Git 交付，未部署）

- 分支 `codex/invoice-outbound-ux`，worktree `C:/Users/windb/.codex/worktrees/invoice-outbound-ux/commission-system`，基点 `569b1fe5`；按评估顺序落地金额命名、关联进度、列表动作、概览紧凑、明细工具、出库菜单、库存展开、结算分组和可选打印预览。
- 保留现有金额计算、资金抵扣、库存及实际出库口径；无后端逻辑、数据库或生产业务写入。独立审查指出的真实状态枚举、历史记录过滤及菜单权限包装已修复。
- 定向回归 119/119、构建通过；扩大回归 305/326，通过 main 同范围复跑确认其余 21 项均为既有夹具／断言失败，无新增失败。实际浏览器核对桌面及 390px 库存抽屉，另验证只读身份无编辑／删除。
- 实现范围、证据和边界见 [优化报告](reports/2026-10-23-invoice-outbound-ux.md)。用户已授权本次提交、合入 main 并推送，最终交付以 Git refs 回读为准；未部署。

## 2026-10-23 客户 PI PDF 字体故障（Codex，Git 交付，未部署）

- 北京现有 Noto CJK 字体为 CFF 轮廓：Pillow 可用，ReportLab 拒绝，导致客户下载报 PDF 服务未配置。现场没有 systemd/进程字体覆盖；有效配置来自 `backend/.env`。
- 共享中文字体预检增加 ReportLab 实际解析，北京受管 prepare 在停服务之前调用；PI 只补异常类型日志，金额、权限和快照选择不变。28 项后端测试、9 项既有部署测试及 1 项新增预检阻断测试通过，独立审查未见 P1/P2。
- 兼容字体已从 Ubuntu 包解压到私有暂存路径。对截图请求的当前已发布快照做只读渲染成功，2 页 PDF，快照哈希未变、业务库写入 0。证据含真实客户 PDF，仅留 `tmp/pi-font-proof/` 与北京私有 `.deploy_state`，不提交。
- 详见 [报告](reports/2026-10-23-portal-pi-font-repair.md)。用户已授权本批与结算高度修改一起提交、合入 main 并推送，以 Git refs 回读为准；本次不部署，线上字体配置与服务仍未切换。上线需先配置兼容字体，再走 `deploy/deploy.bat`，单独部署预检代码不会修复现有字体。

## 2026-10-23 客户结算双栏高度（Codex，Git 交付，未部署）

- `codex/portal-checkout-height`，独立 worktree `C:/Users/windb/.codex/worktrees/portal-checkout-height/commission-system`。桌面结算页收紧导航、标题及页脚，将更多视口高度给左右独立滚动区域；手机布局与业务逻辑不变。
- 1440×900 两栏高度 537→703px，1440×640 为 376→443px；浏览回归含几何、实际滚轮独立性、付款与提交，截图和尺寸在 `tmp/checkout-height/`。说明见 `docs/reports/2026-10-23-portal-checkout-pane-height.md`。
- 用户已授权与 PI 字体修复一起提交、合入 main 并推送；最终状态以 Git refs 回读为准，本次不部署。

## 2026-10-23 客户门户全页 UI 检查与优化（Codex，Git 交付，未部署）

- `codex/portal-oil-ui`；独立 worktree `C:/Users/windb/.codex/worktrees/portal-oil-ui/commission-system`。覆盖公开入口、集合/规格、选购、请求/方案/PI、再次下单、联系弹窗和共享导航。
- 补申请/激活样式、可读性、窄屏布局；修初始激活路由及验证码函数未调用；删高频 500ms 入场、误导性已确认标题及重复说明。无后端、数据库或生产业务写入。
- 与 main 的商品固定操作栏/结算独立滚动整合；横屏复验发现大图吸顶遮挡下一行数量按钮，已按 ≤1180px 布局关闭大图吸顶。
- 一轮独立视觉评审，受影响浏览器场景三轮通过；报告 `docs/reports/2026-10-23-portal-oil-ui.md`，截图对比 `tmp/portal-oil-ui/index.html`。线上只确认公开登录结构，已登录全站视觉检查受浏览器连接阻塞；不能称生产验收。用户已授权本次提交、合并 main 并推送，最终状态以 Git refs 回读为准；未部署。

## 2026-10-23 门户选购布局与 PI 模板导出（Codex，Git 交付，未部署）

- 用户已授权本批提交、合入 main 并推送：商品详情底部固定操作区、结算左右独立滚动、员工 PI 详情核对区及指定 Excel 模板的 Excel/PDF 直接导出。分支 `codex/portal-purchase-dock`，最终交付以 Git refs 回读为准；本次不部署、迁移或写生产业务数据。
- 主目录已有 79 个改动/未跟踪路径按文件副本、原始 HEAD/index、二进制补丁和 SHA256 清单保护；备份与 UI 证据在主目录 `tmp/portal-pi-main-integration-20261023-190956/`。集成仅带入本任务文件，主目录原有文档整理保留为未提交改动。
- 验证与范围见下方实现记录及 [PI 模板报告](reports/2026-10-23-pi-template-export.md)、[PI 详情报告](reports/2026-10-23-portal-pi-detail-ui.md)。既有发票默认导出与客户已发布快照服务保持原路径。

## 2026-10-23 员工 PI 按指定 Excel 模板导出（Codex，本地验证，未部署）

- 用户提供 `发票模板.xlsx` 并要求在处理 PI 详情直接导出 Excel/PDF。两按钮显式传 `template=leshine_pi`；原 Excel 模板随代码纳入 assets，保留原公司抬头、Logo、浮动 Proforma Invoice 标题和八列表格，多商品自动扩展。PDF 使用同一映射与原品牌素材独立分页，续页重复抬头，生产不依赖 Office。
- 实际成交价、折扣、行净额、费用与总额取已存单据值，不沿用样例 5% 公式；替换全部样例身份与旧邮箱链接。无实时 invoice:read 或不在单据范围内拒绝。原发票默认版式、客户发布快照 PDF 与 PI 状态流转未改；不提供 A/B 选择器。
- 61 项隔离后端回归、前端构建、连续三轮各 5 场景的按钮/命令浏览回归、约定与 diff 检查通过，独立风险审查通过；Git 巡检为 no-fetch 本地快照。模板来源、下载入口、测试范围及样例证据见 [报告](reports/2026-10-23-pi-template-export.md)。本次无真实业务写入，未提交、合并、推送或部署。

## 2026-10-23 员工下单请求 PI 详情优化（Codex，本地验证，未部署）

- 使用 oil-ui 沿用 Ark 品牌优化「下单请求 → 详情 → 处理原 PI」：客户/编号/版本/状态/总额前置；商品表格与费用、付款、收货条款保持原值；桌面单据和操作独立滚动，移动端上下排列，技术 ID 与运输联系信息按需展开。
- 顶部新增当前 PI Excel/PDF 导出，复用现有发票导出及 invoice:read；历史/提案页禁用，客户已发布快照下载保持原服务。旧入口在发票管理行「更多」。现有导出是固定版式，preferred_template A/B 尚未接入导出，不能称模板切换已完成。
- 下载改按钮 loading，403 局部提示；防重、关闭后迟到响应丢弃。提案/发布/作废、金额来源与幂等命令未变。最终浏览回归连续 3 次×5 场景通过，键盘/长文 15 场景、200% 等效重排、Node 10 项、构建及约定检查通过；独立代码审查通过。证据与边界见 [报告](reports/2026-10-23-portal-pi-detail-ui.md)。浏览证据使用模拟 API，不代表真实导出或生产验收。
- 与商品底部固定区、结算页独立滚动一起保留本地 diff；尚未提交、合并、推送或部署。

## 2026-10-23 客户结算页左右独立滚动（Codex，本地验证，未部署）

- 延续 `codex/portal-purchase-dock` 分支。桌面宽度 >1000px 时，结算页在视口内固定布局，左侧商品/收货资料与右侧服务端报价各自 overflow-y 滚动；两侧均可键盘聚焦，滚动到边界不带动另一侧或页面。较矮窗口收紧标题与页眉页脚空间；≤1000px 延续上下布局与自然页面滚动。
- 纯前端布局改动，金额、报价、下单、确认和恢复逻辑未改。构建成功；构建产物+内存 API 浏览测试验证 1440×900/640 的实际滚轮独立性、边界滚动及无整页偏移，手机端保持自然滚动，并完成付款切换、复核和提交路径。上一项商品底部固定操作区的四种窗口浏览回归仍通过。截图 `tmp/checkout-scroll-qa/`。
- 与商品底部固定操作区一起保留待审 diff；尚未提交、合并、推送或部署。

## 2026-10-23 客户商品详情底部固定操作区（Codex，本地验证，未部署）

- 分支 `codex/portal-purchase-dock`，worktree `D:/MyProgram/commission-system-codex-portal-dock`。库存状态、数量、Add to selection、单位步长、加入反馈及库存说明固定在视口底部；在动画列外渲染，避免祖先 transform 改变 fixed 定位参照。缺货隐藏加入控件的原逻辑保留。
- ResizeObserver 按实际高度预留页面底部空间，反馈/换行/窗口变化时同步更新，离开详情释放 observer 并清除预留。移动端兼顾 safe-area，短屏最多占半屏，超出部分在操作区内滚动；沿用门户 tokens，无新增动效。
- 门户构建与 142 项 Node 测试通过。构建产物+内存 API 浏览测试覆盖 1440×1000、375×812、320×640、812×375、80 个额外颜色的实际长页滚动、底部定位/页尾不遮挡/数量加选/缺货/离开清理，无页面错误或横向溢出。截图在 `tmp/purchase-dock-qa/`。本次不合并、推送或部署。

## 2026-10-23 客户门户商品大图与详情性能（Codex，Git 交付，未部署）

- 分支 `codex/portal-image-performance`，独立 worktree `D:/MyProgram/commission-system-codex-portal-images`。商品列表封面、详情主图请求 `size=full`（最长边 1200），色号按钮保留 `size=thumb`（96）；详情主图 eager 加载。
- 详情的颜色/标准价/客户规则使用请求内批量 SQL 读取，保留数据库匹配语义、系列歧义拒绝、命名空间和查看价格权限。下单与提交继续使用原权威解析，不复用浏览快照。2/200 个规格夹具的定价相关查询从逐规格增长降为 3 次，库存取证逻辑保持原路径。
- 验证细节见 `docs/reports/2026-10-23-portal-image-performance.md`。用户已授权本次提交、合并 main 并推送，最终状态以 Git refs 回读为准；未部署，无生产业务写入，线上登录态详情耗时需发布后实测。

## 2026-10-23 WhatsApp 绑定与消息同步稳定性加固（Accio，已合并推送 main，未部署）

- 分支 `accio/whatsapp-sync-resilience`。Connector：Ark 授权回调暂时失败（超时/不可达）在租期内容忍一次、持续不可用进入 `authorization_wait` 并按 5s~5min 退避自动重连，status/授权不变；明确拒绝/暂停/撤销仍立即停止并取消自动恢复。重连成功清零重试计数，重连耗尽也走自动恢复。显式重新关联带 `fresh_credentials` 清除旧凭据，强制新二维码。
- Ark：Connector 保护性 `paused` 记为 Ark `protected`，不再被 `owner_enabled` 当作撤销授权而触发 sticky 失效；持有人新增「恢复采集」（`POST /api/whatsapp/accounts/{uid}/resume`）。授权回调与同步批次对角色/权限/账号行改用共享锁（游标行仍排他、先锁游标）。CRM 投影失败独立 savepoint 不丢消息；存储类异常只隔离单条（断线仍整批重试），记 `quarantine_from_sequence`，`POST /accounts/{uid}/replay-quarantined` 回退游标重放。新号关联只复用 10 分钟内的待处理会话；自动同步遇游标并发不记失败，last_error 取最新原因。
- 采集：过滤 `status@broadcast`/`@newsletter`、表情回应、系统 stub、协议/密钥分发消息，拆开阅后即焚等外壳；`@lid` 会话用 `remoteJidAlt` 补 `contact_phone`。写入放大：每事件写一次账号，changes 每实体保留最新一行（新增索引 `changes_entity`），inbox 保留最近约 1000 条，容量检查改为上界缓存、近上限才全表计数。
- 前端：账号状态「保护性暂停」、Connector「等待自动恢复」、恢复采集按钮；重新关联提示会清空正文授权与 AI 外发；扫码状态查询失败自动重试 2 次。
- 验证：Connector 手写测试 57 项中 56 通过，唯一失败为改动前已存在的跨进程租约竞争用例（Windows 时序）；后端 WhatsApp 专项 66 passed，全部涉及 WhatsApp 的后端测试 648 passed / 1 skipped；前端 vite build 通过；finish_check 门禁、check_conventions --strict、diff --check 通过，git_sweep 因本机 Python 缺 tzdata 未运行。无迁移。
- 发布：Connector、后端、前端须同批发布。已被永久撤销授权的旧账号（consent_state=paused）不会自动修复，需持有人在「授权范围」重新保存一次。未做：LID/手机号会话合并、首次全量历史同步的根治、重启缺口自动清除、媒体下载，均需真实账号取证或另立功能。

## 2026-10-23 发票编辑关闭保护与同步完成提示（Codex，Git 交付，未部署）

- 分支 `codex/invoice-close-guard`，用户已授权本次提交、合并 main 并推送；最终交付以 Git refs 回读为准。现代/旧版编辑抽屉的右上角关闭及取消、站内离开、浏览器 beforeunload 共用保存状态；保存/同步/回款处理中阻止误关，未保存内容提供继续编辑或放弃关闭。已保存无改动不重复确认。
- 保存并同步确认成功后显示中心常驻提示“XXX订单号已保存并同步完成”，点击框外消失；关联任务仅 `done` 算成功，处理中/失败/人工结束不冒充完成。空回款初始化和独立保存回款不误报未保存，保存期间新增编辑不被响应覆盖。
- 验证：88 项 Node 相关回归及 14 项布局/旧版入口/同步守卫回归通过；真实 InvoiceManage + 内存 API 的 Edge 无头测试覆盖 1440/390 宽度、顶部关闭、取消/放弃、浏览器原生 beforeunload、同步与常驻提示的框内/框外点击；截图随集成备份保留。前端构建、增量约定检查和 diff 检查通过，保留既有构建 chunk/import 警告。独立审查发现的回款初始化误报已修复。git 巡检仅本地快照。本次无生产写入或部署。

## 2026-10-23 销量备货一览新增现货自由库存（Codex，Git 交付，未部署）

- 分支 `codex/stock-free-inventory`：按用户确认将“自由库存”放在“可用库存(小满)”后，列默认显示并参与列显隐设置。现货口径，不计生产在途；合计启用仓库小满镜像，默认仓库扣除尚未被原生占库承接的待出库保留。
- 复用 `stock_reservations.claims`，不触发外部库存请求。SKU/默认仓库/数量/时间缺失、原生交接后的镜像未更新、running/uncertain 或原生关联未决均显示“待核对”，不冒充零；悬停显示参与计算的最早库存同步时间（北京时间）。新增字段 `free_stock` / `free_stock_synced_at`，仅补充当前页，不改变现有排序、备货状态或建议数量。
- 验证：隔离 SQLite 下库存保留及排序测试 37 passed；增量约定检查通过；独立风险审查通过。实库仅 SELECT，在只读事务内查询 100 行，16.31 秒返回，未修改生产数据。前端生产构建通过（保留既有 chunk/import 警告）；`git diff --check` 通过，`git_sweep --no-fetch` 完成，巡检仅本地远端快照，不操作其他分支。

## 2026-10-23 翟 #261046 生产库存出库恢复及历史占用修复（Codex）

- 已按用户授权完成固定对象生产恢复：invoice 1310 / task 823；重新实时核实历史 invoice 748、786 的有效待出库单后，在共享出库锁下追加 native 占用事实，只唤醒当前库存等待任务。原订单、明细及回款字段回读未变。后台于 08:44:27 完成出库，小满出库 ID `105878558570280`，单号「翟 #261046 生产库存」，待出库、4 行 102 件；独立 GET 已核对订单关联、数量、单价、仓库和备注。未确认实际发货。
- 生产证据保留在主目录 `tmp/invoice-1310-native-recovery/`：前置快照、修改后回读与 `created-outbound-readback.json`；不含凭据。第一次未取得互斥锁，未写入；后续成功一次，没有重复创建。
- 任务分支 `codex/outbound-native-reservation`：Python/Node 出库核验对缺 native 基线的历史已完成任务，仅凭实时有效出库证据抵扣保留；保留未覆盖增量及未决修改，核验后再读实时库存。普通库存列表不触发历史扫描。用户已授权合并推送，主目录原改动以文件副本和 SHA256 备份保留，最终交付以 Git refs 回读为准；本次无部署或迁移。
- 验证：隔离 SQLite 下库存保留/native 核验/任务/关联同步一组 109 passed；新增手工增量回归后，库存保留/native 核验/出库同步一组 161 passed（两组有重叠，不相加）；Node creator/库存/隔离/原单守卫/备注/模式 157 passed。check_conventions 增量无违规、git diff --check 通过，独立审查通过；git_sweep --no-fetch 完成，仅本地远端快照，保留其他 worktree 改动。已有 Python/依赖弃用警告未影响测试。

## 2026-10-22 方舟后台客户下单门户 5 个导航页 UI 规范对齐（Accio，已合并推送 main，未部署）

- 仅 `frontend/src/views/portal`：下单请求、客户访问、账号申请、商品目录（含产品族/色块库子页）、站点设置。页头 17px/700 + 14px 描述且不放按钮；筛选统一 FilterBar 进表格卡片；主操作 + TableTools 进 action-bar；极光底 + 玻璃面板（共享 `portal-page.css`）；状态统一 `portalStatus.js` 字典 + StatusBadge；列补 max-width/tooltip/排序；申请时间按北京时间。
- 验证：管理端 vite build 通过；check_conventions --strict 与 audit_frontend_ui 通过；auditTableSorting 五页无违规；1440 与 390 宽 mock 截图无页面级横向溢出。仓库原有 `tests/portal*.browser.mjs` 在改动前代码上同样失败（环境问题），未作为本次验收依据。
- 未做：账号申请审核仍需手工粘贴授权 ID，需要后端新增授权查询接口后才能改下拉。

## 2026-10-22 客户门户选购页 UI 优化（Accio，oil-ui，已合并推送 main，未部署）

- 仅前端 `frontend-portal`：产品族卡片改为色块实拍满版、名称前置；删除首页旋转印章与 HAIR COLLECTION / YOUR COLLECTION 装饰标签；详情页主图下注明当前组合，色块放大，无货色块灰度加删除线，数量与加入按钮同行，加入提示改绿色；修复 skip link 在手机端露出。
- 验证：客户门户单测 141 通过；vite build 通过；`tests/family.browser.mjs` 桌面与 375px 通过；用素材文件夹真实色块图 + mock API 做前后截图（截图脚本与图片在 worktree 外 `ui-work/`，未入库）。未派独立评审；动效未改；登录、结算、订单页未改。

## 2026-10-21 客户门户受管开放下单与激活邮件调度（Accio，已合并推送 main，未部署）

## 2026-10-21 自由可用与缺货补货同步（Codex，Git 交付，未部署）

- 分支 `codex/outbound-replenishment-reservation`，worktree `C:/Users/windb/.codex/worktrees/outbound-replenishment-reservation/commission-system`，基点 `cb3c7a4a`。用户已授权提交、合并 main 并推送；主目录已有文件以补丁、副本与 SHA256 清单保护，证据在主目录 `tmp/outbound-replenishment-integration-20261021/`。最终远端提交以 Git refs 回读为准。本次无部署、真实小满写入、生产数据库写入、迁移或模式切换。
- 产品明细仅显示「自由可用」：目标仓库原生可用减所有有效本地待出库尚未原生承接的整单 SKU 数量，包含非缺货行、重复 SKU 与其他订单。保留不等于物理库存，本单缺货判断使用内部实际可分配量。已生成原生出库后新增需求继续保留差额，严格核验改量后更新原生快照，未确定结果不释放。历史证据缺失显示待核对。
- 缺货出库行新增「补货同步」，重新核实当前人员权限与可见范围，立即查实时库存并复用原发送事实/详情回读；仍缺货更新摘要，重复点击仅一次外发，超时不自动重发。订单确认、两种后台执行、手动补货与相关增量出库共用命名锁，防止前序保留中途改变。库存查询用独立 product scope，不改共享 invoice token。
- 复用现有事件表保存完整成功代次与原生数量；无结构迁移。Python 应用、`okki_outbound_stock.mjs`、creator/poller/mode 必须经受管入口同批发布。规则见 [requirements](requirements/2026-10-21-outbound-replenishment.md)，API、数据库事件约定、原出库同步及 legacy 部署文档已更新。
- 验证：最新核心 SQLite 147 passed；受影响广回归先前 314 passed、1 个新增测试的零保留映射期望错误，修正后在这 147 项中完整重跑通过。真实新建、随机端口、loopback MySQL 8.0.46：59 passed（5 个手动 HTTP/并发 + 54 个 worker 原协议）。隔离 fixture 为历史门户表补齐当前 ORM 缺列，仅验证服务行为，不代表生产迁移验收；供应商边界全部合成，不访问真实小满。MySQL 08 的日志确认 Shutdown complete，副本在 `tmp/outbound-replenishment-mysql/`。
- 验证：JS legacy/库存/前端逻辑 162 passed；受管发布制品 123 passed；前端生产构建通过（既有 chunk 警告）；真实 Vue 组件浏览器在 1440/390px 均通过，覆盖按钮权限、禁用、防重、缺货/失败/成功反馈、列表刷新及单列显示，截图在 `frontend/tmp/outbound-replenishment/`。独立审查修复 product scope、已有出库交接与订单并发问题后复核，无剩余可证实 P1/P2。约定检查与 diff 检查通过，`git_sweep.py --no-fetch` 已运行，仅本地远端快照，main 落后缓存 origin/main 3 提交；不自动合并他人工作。
- 复跑入口：backend 中 `python -B -m pytest tests/test_outbound_stock_reservations.py tests/test_outbound_invoice_sync.py -q`；MySQL 复跑同名 `tests/portal_mysql/test_mysql_outbound_replenishment.py`、`test_mysql_outbound_worker.py`，按该目录 conftest 提供验证过的 mysqld、全新 workspace 与 `--confcutdir=tests/portal_mysql -p no:cacheprovider`。frontend 中先 `npm run dev -- --host 127.0.0.1 --port 3039 --strictPort`，再用有 Playwright 的 Python 执行 `tests/outboundReplenishment.browser.py --browser <installed Chromium>`。
- 发布后仍需固定订单/SKU 验收小满真实占库、库存不足与补足、另一业务员同型号下单、取消释放；当前静态/隔离证据不能替代真实占库验收。自动审批拒绝本次 MySQL 临时目录递归清理（只返回策略拦截，未给具体原因），目录 `D:/MyProgram/tmp/stock-replenishment-mysql-01` 至 `-08` 及测试证据暂保留，未绕过拦截。

## 2026-10-20 素材库筛选与搜索栏布局修复（Codex，Git 交付，未部署）

- 修复分支 `codex/asset-library-layout`（合并后清理）。素材库的 sticky 重复计入主布局已预留的 101px 导航高度，导致左侧留白及搜索栏盖住首排图片；已取消重复偏移，嵌套 FilterBar 改为普通文档流，搜索与批量操作共用一个吸顶容器。窄屏取消筛选栏相对偏移，按钮按可用宽度换行，侧栏高度含内边距与边框。
- 验证：前端生产构建、增量约定及 diff 检查通过；本机 Chromium + 模拟 API 验证 12 个布局场景（1440/1024/769/768/390px、滚动、批量选择、列表与全屏）及回车查询，无页面异常。主目录 `tmp/asset-layout-evidence/` 保留修复前后截图与坐标记录。
- 按亮哥授权提交、合并 main 并推送 origin/main；不部署，不执行数据库操作。验证证据保留在主目录，临时修复分支与工作区在交付后清理。

## 2026-10-20 库存单回款草稿保存前校验（Codex，代码交付，未部署）

- 工作区 `C:/Users/windb/.codex/worktrees/invoice-receipt-save-validation/commission-system`，分支 `codex/invoice-receipt-save-validation`。针对库存单回款草稿超额却可保存的问题，前端在新增、编辑及保存并同步的请求前拦截，明确展示金额与币种；后端在重新计价后、凭证绑定及草稿修改前兜底。请求省略草稿时仍核验持久金额；拒绝则整次保存回滚。
- 保留零回款、部分及等额回款、预售首款与已提交回款原规则；存量超额草稿可修正后保存，不自动调整任何实际到账或订单金额。同步前校验继续保留。API与使用文档已同步，无迁移。
- 验证：新增保存专项 SQLite 13通过；现有回款/推单/预售147通过、回款纠错14通过、关联同步25通过；前端编辑与结算87通过，构建及严格增量约定检查通过（仅既有大chunk等构建提示）。回归测试在原实现明确复现缺陷；独立资金风险审查未发现阻断项。Git巡检为 `--no-fetch` 本地快照，其他工作区未清理。
- 用户已授权本次提交、合并 main 并推送；生产发布不在本次范围内，未写生产业务数据。需前后端一起发布后线上生效。构建日志 `tmp/invoice-receipt-save-build.log`。

## 2026-10-20 内贸扫码完成状态误提示（Codex，Git 交付，未部署）

- 工作目录 `C:/Users/windb/.codex/worktrees/domestic-scan-result/commission-system`，分支 `codex/domestic-scan-result`，基点 `7b2e9540`。修复本人负责工序已报完时仍提示“上一道未完成”：数量按本人绑定工序有效通过数量，逐件按单件有效通行事实，返回 `OWN_STEPS_DONE`；真正缺上游仍拦截，多绑定、跳过、撤销沿用原规则。小程序完成提示关闭后进入原单件历史，不自动报工。
- 生产 `DO20261010-002` 只读核对：杨森实际做发型 2 件，A4-01 为 10/19 16:13:08，A3-01 为 10/19 17:37:21，A2-01 未报；前序质检均已完成。用户确认截图提示来自 10/20 重新扫码，晚于已成功报工。当前代码读取生产数据复现 A3/A4 的重复扫码误提示，不修订历史记录。
- 专项隔离 SQLite 6 项、小程序相关 Node 23 项通过；扩展回归 170 通过 / 1 个既有发货提示断言失败，已在未改相关代码的主目录复现同样失败。严格约定与 diff 检查通过；Git 巡检已执行 `--no-fetch`，为本地快照。独立状态机/契约审查通过。用户已授权提交、合入 main 并推送；原有改动备份与交付核验保留在 `tmp/domestic-scan-main-integration-20261020/`。没有生产数据写入、迁移、部署或真机验收，小程序标题修改需随小程序发布。详见 [排查与验证记录](reports/2026-10-20-domestic-scan-feedback.md)。

## 2026-10-19 订单发票产品明细缺货筛选（Codex，Git交付，未部署）

- 分支 `codex/invoice-stock-shortage`，工作目录 `C:/Users/windb/.codex/worktrees/invoice-stock-shortage/commission-system`；新版创建/编辑及旧版创建复用产品明细组件，增加「仅显示库存不足的产品」、可用库存/未发货数量对照与浅红缺货整行。筛选默认关闭，先筛选再排序分页，不删除源明细，不影响金额及保存；新增/导入或定位数量错误时恢复全部行。


- 同分支（P3 已提交 `9e15f3da`）。新增迁移 `201_portal_access_requests` 与 `PortalAccessRequest`；公开申请 `POST /access-requests` 只收全名/电话/邮箱，限频、幂等，不创建权限；员工在「客户账号申请」页查看并批准/拒绝，批准必须绑定既有 enabled + can_order 客户授权，复用 invitation outbox 发激活邮件。
- 客户端新增登录页「Request customer portal access」、`/activate#token=...` 激活页；新增 `/auth/challenge` + `/auth/activate`，邮件 token 经验证码校验后设置密码并直接登录。申请、密码、token 不进入回执/日志；钉钉通知复用 dingtalk outbox，申请通知不包含权限或密码。
- 验证：P4 后端专测 13 项通过；后端 compileall 通过；客户门户和主站构建通过。浏览器视觉检查未运行：本地 Vite preview 未监听，且没有可用 CDP endpoint；未发送真实钉钉，未执行 MySQL/生产迁移。

## 2026-10-19 客户下单门户 P3：自动运费、PayPal 手续费、业务一键审核出 PI、钉钉推送（Accio，未部署）

- 同分支（P2 已提交 `e49d524b`）。新增 `fee_policy.py`、`dingtalk_notice.py`、迁移 `200_portal_quote_fee_estimate`；`SitePolicy.auto_fees` 与付款条款 `method_label/surcharge_percent`；客户端点 `/ordering-terms`，`/quotes` 支持 `payment_term_code`。
- 流程：启用后客户在结算页选付款方式，看到总重、运费、手续费、总额；提交即接受 → `ready_for_review`，业务在订单审核框一键「审核并生成正式 PI」（复用 approve，PI 模板 v2 含重量）。>2kg 或重量未知仍走原提案流程。默认关闭，需在后台「客户门户站点设置」开启并配置 PayPal 5.00 / 银行转账 0.00。
- 钉钉：设 `PORTAL_DINGTALK_WEBHOOK_URL/SECRET`（需同时配置 PORTAL_EMPLOYEE_ORIGIN）后注册 `portal_dingtalk_notices` 任务；链接为方舟登录后的订单页，不含公开 PI 下载链接。
- 验证：门户 SQLite 回归 795 通过/1 跳过，1 失败为本机缺 reportlab；P3 新测试 24 项；客户端单测 141、后台单测 13 通过；两端构建通过；`checkoutFees.browser.mjs`、`family.browser.mjs` 在 1440 与 375 宽度通过。既有 `checkout.browser.mjs`/`browser.smoke.mjs` 仍依赖旧 OTP 登录按钮，本就失败，仅补了新接口 mock。PDF 渲染因缺 reportlab 未实测。

## 2026-10-19 客户下单门户 P2：客户端产品族目录与规格选择（Accio，未部署）

- 同分支，P1 已提交（`5f8b7d5b` 方案、`2f17c343` 产品族/色块库）。
- 后端：`family_catalog_service.py` + 客户端点 `/catalog/families*`、`/catalog/swatches/{id}/image`；`catalog_service.projected_items(keep=)` 先缩小行再做库存/价格；新增 `stock_display`（扣阈值后 ≥100 显示 100+）；`image_service` 抽出 `approved_ticket` 并新增色块图授权（须持有该色已发布商品）。
- 客户端：Collection 默认显示产品族卡片（无产品族或接口失败自动回退平铺目录），`/collection/<code>` 详情页按 Ratio→Length→Color（按色型分组的色块）选择，数量步进对齐起订/步长，30 秒库存轮询（页面隐藏不轮询），右侧/底部「Your selection」可加减、显示总克重，Finish selection 进入现有 Checkout。购物车行新增 unit_weight_grams 快照。
- 验证：门户 SQLite 回归 769 通过/1 跳过，1 失败为本机缺 reportlab；客户端单测 137 通过；构建通过；新增 `tests/family.browser.mjs` 在 1440 与 375 宽度通过（无横向溢出）。既有 `tests/browser.smoke.mjs` 仍等待旧 OTP「Continue with email」按钮，在当前密码登录下本就失败，未改动。
- 未做（P3）：确认弹窗、运费阶梯、PayPal 5% 手续费、业务审核后出 PI、钉钉推送。

## 2026-10-19 客户下单门户 P1：产品族与色块库（Accio，已提交 2f17c343，未部署）

- 分支 `accio/optimize-order-portal-integration-ce44d944`（已快进到 main `e01194d0`）。方案与亮哥拍板结论见 [整合方案](requirements/2026-10-19-order-portal-material-integration.md)。
- 新迁移 `199_portal_catalog_families`（父198，只新增）；后端 `app/portal/family_service.py` + 管理端点 `/catalog-families*`、`/color-swatches*`；`catalog_admin_service._invalidate` 抽出批量 `invalidate_items`，`_apply` 对已归族商品强制继承族规则。后台「门户商品目录」拆为 商品SKU / 产品族 / 色块库 三个页签，支持批量归族。
- 验证：门户隔离 SQLite 回归 759 通过/1 跳过，1 失败为本机 venv 缺 reportlab（另 2 个测试文件同因未收集，与本次无关）；新增前端单测 5 项通过；`npm run build` 通过。未在 MySQL 执行迁移；客户端（P2）尚未改动，客户目录展示暂无变化。

## 2026-10-19 内贸发货批次独立单价（Codex，Git交付，未部署）

- 分支 `codex/domestic-batch-pricing`，工作树 `C:/Users/windb/.codex/worktrees/domestic-batch-pricing/commission-system`，基点 `bca7b607`。创建批次可按明细调整本批单价，金额及收款核销使用批次价；订单原价、总额、账户扣款、终止退款与后续批次默认价保持原口径，无迁移。
- 独立资金风险审查通过。专项隔离 SQLite 28 项、前端状态 5 项通过；构建、增量约定、diff 检查通过。Edge 隔离模拟 API 的 1440px/390px 操作验证通过，无页面异常。扩大回归另有 1 个既有旧迁移 head 断言失败，详见 [验证记录](reports/2026-10-19-domestic-batch-pricing.md)。Git 巡检为 `--no-fetch` 本地快照。
- 使用/API 文档已同步。用户已授权本次提交、合并 main 并推送；主目录既有改动经备份和校验保留。无部署、共享库迁移或生产业务数据写入。验证截图及集成恢复材料保留在主目录 `tmp/domestic-batch-main-integration-20261019/`。

## 2026-10-19 Disable new-sign DingTalk notices (Codex, deployment pending)

The event delivery query and database claim now allow only `big_deal` / `super_deal`. Newly detected, queued, retrying and stale-lease `new_sign_order` events cannot be sent. New-sign event detection, history and board rendering remain unchanged, and no rows are deleted or marked as sent. New-sign orders still qualify for one amount notice at the existing USD 5,000 / 30,000 thresholds after surcharge deduction. The daily board report is unchanged.

Validation: six focused assertions failed against the old implementation, then all 89 invoice-notification, festival-notification and event-transition tests passed (one existing Pillow warning). Tests use isolated SQLite and mocked senders; independent review found no blocking issues. No real test messages or deployment performed for this change.

## 2026-10-19 部署等待与停服优化（本地完成，未发布）

- 工作树：Codex 已有 managed worktree；分支 `codex/deployment-availability`，基于 `15d86b35`。本轮只修改 deploy 脚本/测试/说明，无业务、数据库、网络拓扑改动；未 commit、merge、push、SSH 或实际部署。
- 新增安全静态热更新、完整摘要绑定的暂存复用；北京就绪/回滚使用300秒重试预算并核验systemd；出库新fence回执复核不重复暂停timer；只恢复旧服务的readiness入口；默认清理延后并用独立维护回执闭合；切换阶段北京时间留证。
- 故障测试发现并修复回滚分阶段manifest校验错误。独立审查问题均已处理：未完成静态切换阻断所有Office路径、fresh模式下限保存、维护按当前release身份闭合。回滚备份损坏仍保留applying并要求核验恢复。
- 全部署隔离回归931通过/18跳过/3个既有失败，后补pipeline回归59通过；主目录重跑复现同样3个失败（旧迁移head断言2项、路由mock耗尽1项）。约定及差异检查通过。详细说明、证据和部署边界见 [交付记录](reports/2026-10-19-deployment-availability-optimization.md)。
- 默认不自动执行清理且未创建定时任务，维护窗口须用既有受管专项入口或显式inline选项。后端更新仍短暂停服，未启用双实例切流，不能称为零停机或线上已生效。


## 2026-10-19 年度榜表头与金色积分（Codex，Git交付，未部署）

- 在 `codex/battle-order-details` 工作树延续本轮改动：年度榜下方列表表头改为「年度GMV同比增长完成进度」；5个顶部卡片及12行列表积分统一使用金色独立令牌与900字重。只修改海报HTML/CSS和字段样式分类，原底图、数字计算与排序保持不变。
- 验证：年度奖项既有pytest 54项通过。用17人模拟快照生成HTML，在浏览器复用正式 `ANNUAL_FIT_JS` 字号适配，确认17处积分颜色/字重一致、无截断，新表头完整。证据 `tmp/battle-metric-orders/annual-gold-preview.html`、`annual-gold-table.png`。本地venv缺少playwright，未调用完整PNG渲染链成功；浏览器已实际检查模板渲染，截图是模拟数据。
- 资产README已同步。无新增前端应用改动，不重复全站构建。用户已授权本次提交、合并main并推送；生产待后续授权发布，新样式适用于重新生成海报，已缓存历史投递不自动更换。

## 2026-10-19 临时战报统计来源订单明细（Codex，Git交付，未部署）

- 工作树 `C:/Users/windb/.codex/worktrees/battle-order-details/commission-system`，分支 `codex/battle-order-details`，基点 `e4ecc7f1`。新增「新签客户 / 复购客户 / 新签+复购金额」标签及 `GET /api/battle-reports/{id}/metric-orders`；客户、订单名称、核算日期范围与可见业务员筛选，默认日期倒序，全结果排序后分页，默认20条、20/50/100档，表格按视口限高。
- 明细字段为客户名称、订单名称、订单号、下单日期、USD金额和统计归属业务员。下单日期明确沿用战报核算日期；合计展示完整筛选的订单数、去重客户数、金额，不随翻页变化。复用奖项事实清洗/裁定与原新签客户归属；转交后复购仍归原新签人。PK总览新签金额另按订单负责人统计，页面/API明确区别，既有PK规则不变。
- 权限保留业务员本人、组长本组、管理者全活动。新增 `battle_report:read_all`（kind=data），需配合read，需角色管理显式分配；允许非参与人查看已发布/归档战报，不开放草稿、管理动作、审计、海报或他人目标写入。普通范围继续核对有效OKKI绑定。无表结构迁移。
- 验证：隔离SQLite/纯函数后端149项通过；前端22项通过；生产构建通过（既有大chunk/混合动态导入提示）；增量约定检查和git diff检查通过；独立审查提出的PK金额歧义已补显式说明与转交回归。浏览器用62笔模拟数据验证三个标签、客户/订单名称筛选、重置、分页合计和失败重试状态，390px iframe确认筛选换行、表格独立滚动布局。未对真实订单进行生产验收。
- 证据：`tmp/battle-metric-orders/desktop.png`、`mobile.png`、`build.log`；可复用模拟页 `frontend/tests/fixtures/battle-metric-orders/`。Git巡检 `--no-fetch` 是本地快照，其他工作树与旧分支未清理。主目录既有改动未触碰；用户已授权本次提交、合并main并推送；未部署、分配生产权限或写生产数据。

## 2026-10-19 Business notification links default to cloud (Codex, deployment pending)

Business notification image URLs and short links now default to `https://leshine.cloud`. Domestic review, announcement, aftersales, training and shipping inspection detail defaults use the same domain. Tracking daily reports and missing-short-code redirects now use `SHORT_LINK_BASE_URL` instead of hard-coded work links. The shared setting also changes newly generated asset, customer-image invitation and WhatsApp pairing links. Environment overrides remain supported; `.env.example` documents the six defaults.

Read-only production inspection found no explicit overrides for these six settings in either backend `.env`; office battle posters already explicitly use cloud. Existing messages and persisted destinations are not rewritten. Infrastructure proxies, health checks, allowed origins and unrelated public API UI addresses remain outside this notification-link change. Validation: 163 notification/API tests passed; mocked link checks verified defaults, image path, short-code fallback, report date and a custom origin; independent review found no blocking issues. One explicitly authorized cloud-image test was sent to the supplied test group and DingTalk returned HTTP 200 / errcode 0; this confirms acceptance, not client loading speed. No deployment performed.

## 2026-10-19 Beijing unchanged-release checkout verification

A deployment-tool-only release must advance the installed Beijing checkout and backend-success receipt even when no backend restart is needed. The unchanged branch now verifies health and colorwork, advances the pinned checkout, and writes its receipt while preserving the running service. An isolated regression checks the Git/receipt update and absence of systemctl actions. Final delivery must verify both installed Git heads, rather than relying on the overall publish summary.

## 2026-10-19 Windows deployment journal checkpoint recovery

The resumed e4 release verified Office and Beijing without restarting the application, then Windows denied atomic replacement of publish-current.json. Runtime remains healthy and the original outbound/mail baselines remain bound. Journal updates now retry only the same Windows sharing-denied rename with a bounded delay. Recovery accepts only the inspected completed Office/backend prefix at the installed candidate and records each journal checkpoint separately. Complete the original release before the latest-main release; final status must come from live receipts.

## 2026-10-19 Office transient health-probe recovery

Annual amount release b59 completed all 11 managed targets and live amount verification (Zhai USD99,190.47, unchanged GMV/targets/counts). A later deploy-tool-only e4 release stopped at its unchanged-code 8-second health probe without stopping the application. Preflight and unchanged-code checks now use the bounded readiness policy too. Recovery binds an explicitly inspected running/stopped service state; running-service failures preserve it without start/stop. Resume the original pending release identity before publishing this fix. Final production status requires the release receipts and independent readback.

## 2026-10-19 Office cold-start deployment recovery

Annual amount release b59 hit the existing 30-second startup budget, followed by an immediate rollback health check. Both activation and rollback now allow 300 seconds with HTTP/database and NSSM readiness. A fixed-journal no-DDL recovery entry restores the verified old service under the legacy rollback fence, then resumes the original release binding through the full publisher; original outbound/mail baselines are preserved. Production status requires live readback after deployment.

## 2026-10-19 年度新签复购金额包含全部新签订单（Codex，本地验证，未合并部署）

- 用户最新确认：年度金额为所有2026新签客户的新签订单＋首签后2026复购订单合计，未复购客户也计新签金额；复购客户数/订单笔数不增加。工作树 `C:/Users/windb/.codex/worktrees/annual-battle-awards/commission-system`、分支 `codex/annual-battle-awards`，基于当前main `29960250`，保护主目录既有dirty内容。
- 年度 `repeat_amount` 与积分金额项改为合计口径；原新签人归属、订单去重、GMV-only裁定、日期/货品过滤、GMV门槛与11月PK均保留。页面说明及海报页脚同步；新计算带 `amount_rule=annual_new_customer_orders_v1`，旧已持久投递快照保持原金额/积分，不追加新口径解释。
- 同一只读镜像（同步2026-10-19 12:00:09，核查12:44:02，报告2/version6）对比：翟佳盟新签76笔USD22,640.87＋复购128笔USD76,549.60＝USD99,190.47，积分31.585952→34.3028564；复购36客户/128笔不变。17人GMV、目标、进度、新签/复购人数笔数均逐项一致，增量等于各原新签人客户池的新签订单额。
- 验证：旧实现先出现5个预期金额失败、PK保留测试通过；修改后战报/海报/裁定/调度/迁移隔离回归213项通过，Vue组件4项通过，前端构建及增量约定检查通过；构建保留已有动态导入/大chunk提示，独立只读审查无实质问题。
- 本轮无提交、main合并、推送、生产部署、数据库写入或群发送。只读重算证据及204笔翟佳盟订单明细位于主目录 `.deploy_state/battle-awards-adjudication-20261019/新签复购金额口径重算-20261019-124402.json` 和同前缀 `-翟佳盟订单.csv`。生产刷新需后续正式发布，不能把本地重算称为线上已生效。

## 2026-10-19 设计中心素材按业务员隔离（Codex，验证通过，未部署）

- 工作树 `C:/Users/windb/.codex/worktrees/media-sales-scope/commission-system`，分支 `codex/media-sales-scope`，基于 main `21d2c554`；主目录既有改动未触碰。
- 拍摄素材审核沿用预约发起人归属，新增 `customer_media:read_all`；门户保留 `customer_media_portal:read_all`，移除素材 admin 隐式全量；账号页新增 `customer_media_account:read` 与 `customer_media_account:read_all`，默认按 active OKKI 绑定和当前客户归属快照隔离。三种全量范围独立，data 权限不能单独进入页面，也不隐含操作权。
- 内部 API 使用 live RBAC；账号创建、修改、启停和候选查询均检查范围；审核只读全量不会放开他人审核/标签修改，任务详情、标签、跨任务删除亦无素材 admin 隐式旁路。设计师保留分配任务维护权。super_admin 继续按平台约定全量；三个 read_all 从 admin 启动自动补授中排除，发布后须在角色管理显式配置需要的全量范围。现有角色已授的权限保留。
- 账号页只读按钮权限、审核行 can_review、设计中心分组/页面/菜单和生成导航清单已同步。API 与模块说明已更新，无表结构迁移。既有媒体签名 URL 保留原有效期，未新增即时撤销机制。
- 验证：隔离 SQLite 后端 68 项通过（素材范围/状态/标签/目录/COS/导航），前端 11 项通过，`npm run build` 成功（保留既有 chunk 提示），定向独立复核无剩余阻断。旧目录测试 fixture 补齐已有门禁要求的客户标签绑定；未弱化生产校验或测试断言。证据 `tmp/media-sales-scope/`。本次按用户授权提交、合并并推送 main；未执行生产读写、生产角色分配、迁移或部署。

## 2026-10-19 素材门户显示密码按钮（Codex，Git 交付，未部署）

- 分支 `codex/media-password-toggle`。`frontend/public/customer-media/index.html` 与 `hub.css` 为登录密码框增加眼睛图标；默认隐藏，点击或键盘激活可显示/隐藏且保留输入。使用英文可访问名称、44px 点击区域及键盘焦点提示；成功登录或重新显示登录页时恢复隐藏。无 API、数据库或认证契约变更。
- 验证：前端构建通过（既有大 chunk 警告）；素材门户现有测试 3 项通过；增量约定检查与 diff 检查通过。Edge 无头浏览器在 1440px/390px 验证默认隐藏、鼠标/键盘切换、值保留、不误提交、密码框 Enter 提交、登录后清空与隐藏、无横向溢出及无页面错误。使用本地模拟接口，无真实账号操作；手机端既有退出按钮不可见，退出复位检查切回桌面执行。截图与验证脚本位于本工作树 `tmp/media-password/`。
- 用户授权本次提交、合并 main 并推送；不部署，线上状态未改变。主目录原有改动的 SHA256 备份及本次验证材料保存在 `.deploy_state/media-password-integration-20261019/`；Git 巡检使用 `--no-fetch` 本地快照。

## 2026-10-19 订单发票零回款提交（Codex，零回款实现，未部署）

- 分支 `codex/invoice-zero-receipt`，工作树 `C:/Users/windb/.codex/worktrees/invoice-zero-receipt/commission-system`。首次回款金额默认 0、取消预付款自动跟随；零金额/空金额无需日期和凭证即可同步。点击“保存并同步”先提示“当前回款金额为0，是否确认提交？”，取消/关闭不写入，确认后执行原流程；正数回款仍校验真实到账资料。
- 零回款保留同步租约和未知结果防重，不进入回款生成队列，出库沿用原规则。完整同步成功后关闭首次自动回款资格，后续到账使用“补登记回款”；已生成回款保持原状态。独立审查发现并修复零回款后补登记再改首次金额可能重复预占并卡住 ready 的边界。
- 验证结果见本工作树 `tmp/invoice-zero-receipt/`。前端 70 项回归通过，生产构建通过（既有 chunk 体积提示）；后端 217 项回归通过，使用隔离 SQLite 和替代远端接口，覆盖零/空金额、无凭证、出库入队、补登记幂等、未知/失败/过期回调及原有正数回款。约定增量检查、diff 检查通过；独立审查复核无阻断；Git 巡检为 `--no-fetch` 本地快照。
- 交付范围为本次功能的提交、合并与推送；不部署，不执行数据库迁移、生产数据修改或真实外部单据创建。主目录其他未提交改动保留。

## 2026-10-19 年度复购榜按积分统一排名（Codex，验证通过，未部署）

- 补充页面与海报备注：“系数前五且满足对应同比增长率的可参与本奖项的评选。”备注仅补展示说明，不修改计算。
- 工作树 `D:/MyProgram/commission-system-score-ranking`，分支 `codex/annual-score-ranking`，基于main 06b27d7d。年度总榜仅按Decimal积分降序，同分保留名单顺序，取消达标优先和未达标进度排序；页面合为总榜并用overall_rank展示，海报前五席位与表格同步规则。
- 实际GMV低于目标仅进度条标红，达到/超过100%不标红；未知进度保持待核对。未达标的百分比显示不舍入成100%；海报保留原图与进度封顶规则，删除已达/未达连续席位范围说明。原奖励资格、候选边界同分与数据异常保护保留，页面/海报告警明确为“获奖候选边界”。无持久数据结构、客户门户或PK规则变更。
- 隔离年度回归50项、前端排序/进度与既有战报测试11项通过；npm build成功（保留既有chunk/auth混合导入提示）。本地真实浏览器验证桌面/390px页面及海报顺序和红条，合成数据、无API/数据库/外部发信、无pageerror，证据 `tmp/score-ranking/`。独立审查无阻断P1/P2。用户授权本轮合并推送，不执行部署或发送战报；工作树清理前保留验证材料到主目录受限.deploy_state。

## 2026-10-15 11月新签PK双底图版式（Codex，本地样张，未部署）

- 继续在 `codex/annual-battle-awards` 工作树。原样复制亮哥提供的一组/二组领先底图（1672×941），按现有leading状态切换；计数相同沿用人均新签金额、月GMV决胜。按姓名对应10个固定人物，凯丽全名显示别名，两位队长保持中央突出。调换团队/名单顺序不影响数据位置；其他自定义名单保留通用布局，避免固定人物错配。
- 每个人的新签、团队总数/30个目标/完成率与条形、胜队奖金组成和队长询盘均填入底图位置。按既定规则，60:43示例胜队为目标奖550+PK奖500=1,050元，不沿用效果图的2,000元；双方达标后才授PK奖和询盘。结束后未达目标或无PK资格明确未获/不予发放，不继续提示未来达标或待评。
- 未开赛、完全持平及数据异常使用两侧非领先人物的裁切组合+VS隔板，无皇冠；数据异常时个人/团队计数、进度和奖金待填。此次仅交付已确认名单与模拟数值样张，画面和页脚双重标注，无业务库读写。证据在 `tmp/pk-layout-preview/`；高清交付为当前会话visualizations目录 `battle-awards/11月新签PK-一组领先-版式样张.png`、`11月新签PK-二组领先-版式样张.png`（另保留持平样张及HTML/JSON）。
- 受影响战报/海报/迁移/调度隔离回归165通过，包含17项PK底图/姓名映射/奖励/状态回归；Edge 9场景检查通过，10人数值、2队长/团队总数、两条5px进度条无溢出，0网络和pageerror。独立审查修复结束时29:28仍提示待达标，并经专项复核确认；约定与diff检查通过，Git巡检为 `--no-fetch` 本地快照。本轮无前端改动，无commit、merge、push、部署、迁移、生产活动创建或钉钉推送。

## 2026-10-15 年度新签复购业绩榜底图版式（Codex，本地样张，未部署）

- 沿用 `codex/annual-battle-awards` 工作树。年度海报改用亮哥提供的1199×1312底图，原图与仓库资产SHA256一致（`c55b932f132ebfac3b11300391ec43a4aef698fdbdf903541729402d8edcbe4e`）；保持4、2、1、3、5领奖台及06—17表格位置，填入姓名、积分、新签数、复购客户数、USD金额与橙色进度条，底部附来源/分组/规则说明。
- 新总榜规则：达100%者先列、按积分降序；未达100%者按准确GMV/目标比例降序、再按积分降序。Fraction比较精确比例，Decimal计算积分；完全相同保持名单顺序。目标继续直接取Excel I列USD门槛，不引入汇率。前五总榜席位与达标获奖候选区分，第五名边界同分显示待裁定。
- 10/15只读镜像最近同步11:30:03，年度成员相关46笔新成交标记空，其中4笔涉及2026新签客户。亮哥确认先做版式，正式数据等标记核对后填入；新底图数据不完整时全部个人字段留待填，明确席位编号不代表排名。未修业务源、未发送。
- 版式样张全部使用示例姓名和模拟数据，顶部及页脚均明确标注。PNG/HTML/JSON在 `tmp/annual-layout-preview/`；交付PNG为当前会话visualizations目录 `battle-awards/2026新签复购业绩榜-版式样张.png`。原有带告警实绩预览属于10/14历史证据，不是本次正式数据。
- 战报/海报/迁移/调度隔离回归148通过；前端生产构建通过（仅原有体积提示）。实际Edge检查模拟、待填、完整、6人达标、长姓名/百万金额美分/极高进度5种场景，85字段17进度条无溢出、零pageerror和网络请求；过长数值先缩字，仍不适配则阻止出图。独立审查与字体修复专项复审无阻断；约定与diff检查通过，Git巡检为 `--no-fetch` 本地快照。未commit、merge、push、部署、迁移、创建生产活动或开启群推送。

## 2026-10-14 年度新签复购奖与11月PK战报（Codex，本地实现，未部署）

- 分支 `codex/annual-battle-awards`，工作树 `C:/Users/windb/.codex/worktrees/annual-battle-awards/commission-system`。临时战报提供两份模板：附件17人及精确2025基数、两队10人/队长；新增附件美元目标、新签复购客户去重与系数、合格前五、PK人均决胜/奖金/询盘展示、确定性海报和周一三五09:00/16:00。年度推送10/19—12/31，PK11月内；保留旧GMV战报行为。
- 亮哥确认使用现有专用群、PK相同频率、复购成果归原新签人、沿用OKKI镜像并显示同步时间。只读取真实镜像及当前绑定；17位年度与10位PK人员均匹配，凯丽对应凯丽比努尔·阿伍提。亮哥最终确认直接引用Excel I2:I18“评比需满足最低门槛”作为USD目标；取消汇率、分档和目标推算。2026 OKKI USD实绩直接比较附件USD目标。GMV/门槛/复购金额取USD，奖金仍CNY。新签/2026实绩不引用附件缓存。
- 17:00:02镜像快照存在47笔新成交标记空。已保留有效美元GMV并逐人用独立SQL核对17人合计；按附件I列美元目标直接比较，当前5人达GMV门槛、12人未达，但完整系数/排名仍待47笔标记确认。带告警预览已生成，正式调度阻止不完整数据；未修改业务源、未创建生产活动或开启推送。核对CSV及两张预览在本工作树 `tmp/battle-awards-preview/`，交付副本在当前会话visualizations目录。
- 迁移197接196，仅增加award_kind/award_rules，downgrade拒绝删基数。开发机未执行共享生产库迁移。独立审查修复运费抢新签归属、同分小数精度、Vue Proxy复制、PK部分数据误显示完整奖励；专项复查通过。
- 后端战报/海报/迁移/调度隔离测试143通过（含附件直接目标、精度和目标审计回归）；前端构建通过（仅原有分包大小/混合导入提示）；真实Vue夹具验证两模板创建及设置、前五、PK领先/队长/10人、单图预览、桌面/390px，零pageerror。约定与diff检查通过，git_sweep --no-fetch为本地快照。未commit、merge、push或部署。详见[规则与发布说明](requirements/2026-10-14-battle-awards.md)。

## 2026-10-17 部署提速（Codex，本地实施，未发布）

- 分支`codex/deployment-speedup`，基于已发布main `d821f507`。完成静态资源单轮摘要规划、源树扫描去重、Windows主站/PM独立npm快照缓存、跨host有界并行静态准备和线程安全计时/日志。所有准备成功才freeze；迁移、激活及恢复顺序保持。
- 静态规划基准：3366 assets×3份，4.653秒→1.135秒（-75.6%），计划完全相同；摘要读取23565→10101。资产合入3.966→3.704秒。真实181包依赖独立恢复14771文件字节一致，Vite/esbuild通过；本机npm ci14.777秒、缓存命中12.132秒，首次归档另需5.386秒。不能把本地降幅当作线上完整部署收益。
- npm缓存按包/lock、实际Node平台/架构/ABI、npm与有效配置隔离，特殊脚本/链接依赖不用快照；每组件最多3份完整配对缓存、单包512MiB。缓存故障不留半套依赖，目录短暂占用仅在未切换事实已核验时有限重试；同artifact跨host传输包独占，用后清理。
- 独立审查三项P2均修复并定向复核通过；最终受影响回归162通过/4跳过（43.93秒），扩大测试883通过/18跳过/3项既有失败。无生产写入；主工作区其他改动保留。
- [提速方案、基准及边界](reports/2026-10-17-deployment-speedup-plan.md)，发布机制见[部署入口](../deploy/README.md)。本轮尚未合并、推送或部署，线上完整耗时应在下一次授权发布后读回。

## 2026-10-17 部署候选自动清理与耗时检查（Codex，本地完成，未部署）

- 分支 `codex/deployment-retention-audit`。完整发布成功后，在既有发布锁内小批量清理有创建回执且满 7 天的源码/静态暂存候选；当前/两级回滚/执行源码/恢复与运行引用受保护，未知旧目录不接管。每轮最多8项、60秒目标间软预算，已开始项可完成。依赖链接仅解除链接本身，复制配置变化或未知业务数据保留；删除 intent 与独立读回可查，失败不自动重发。
- 新增 `--candidate-retention-only [--prepare-only]`，只做候选维护，预览不覆盖中断回执。已安装版本先于静态维护登记，避免维护失败扰乱回滚顺序。构建缓存、Python环境、业务文件、数据库和现有回滚静态目录不属于新增清理范围。
- 准备和完整发布持久记录逐阶段耗时；依赖/编译/PM内网/各主机资源保留独立计时，绑定实际revision/release_id；北京时间时间戳、单调时钟耗时，计时写盘故障只告警，不改变业务动作结果。
- 历史日志明确：依赖安装48秒，主站编译20.43秒；正式发布三套前端命中缓存，静态传输0 bytes；Office就绪重试6次。代码发现重复准备、静态暂存复制、保留预览/执行重复规划、串行SSH与无变种子检查。旧日志无阶段时间，尚不能精确分摊总耗时。本次办公室SSH握手超时，未刷新生产状态或重跑发布。
- 最终相关回归147通过/4跳过；扩大全套857通过/18跳过/3项既有失败，未修改主目录原样复现。独立风险审查已修复；严格增量约定、diff检查通过，Git巡检为no-fetch快照。详见 [机制检查报告](reports/2026-10-17-deployment-mechanism-audit.md) 和 [部署规则](../deploy/README.md)。未提交、合并、推送或部署，不影响主目录其他未提交工作。

## 2026-10-16 上传素材标签锁定选择（Codex，Git 交付，未部署）

- 分支 `codex/customer-media-tag-lock`。手动选中客户标签后可点击标签旁的锁图标锁定；锁定项在文件夹识别或确认创建新标签后继续选中，与识别结果一起写入各文件的标签快照；未锁定项正常替换，同一标签去重。解锁保留当前选择但允许后续替换，关闭上传窗口（关闭按钮、Esc、遮罩）、离开页面或刷新页面后锁定失效，不保存到客户标签库。
- 标签选择及锁定逻辑提取到 `useCustomerMediaTagSelection.js`；客户标签刷新按 ID 保留锁定，删除值从选择和锁定中清除。单选维度出现冲突时保留锁定项并提示先解锁，不把互斥组合加入上传清单。既有文件的快照不随解锁或关闭窗口修改。锁按钮仅已选标签可用，支持键盘，读取和上传期间禁用；金色闭锁表示已锁定，锁与删除按钮的点击区域分离，不增加切换动效。
- 验证：36 项客户素材 Node 回归通过；真实本地 Chrome 18 项关键路径通过，含已有文件夹识别/预览/筛选、锁定与解锁、匹配和新建标签保留锁定项、`tags_json` 上传参数、清单快照保留、三种关窗方式及页面刷新失效。1440px/390px 下锁按钮至少 28×28px、与删除按钮不重叠，Enter/空格及减少动态模式可用；页面错误为 0。所有业务接口为本地内存替身，无生产数据写入。截图、构建日志和巡检记录保存在主目录 `tmp/customer-media-tag-lock-integration-20261016/verification/`。
- 前端生产构建、严格增量约定及 diff 检查通过，保留既有混合导入/大分包提示；Git 巡检为 `--no-fetch` 本地快照。需求说明同步至 `docs/requirements/2026-08-13-customer-media-portal.md`。用户授权本次提交、合并推送至 main，主目录原有改动备份后保留；生产未部署。

## 2026-10-16 订单经营决策台筛选遮挡修复（Codex，本地修改，未部署）

- 分支 `codex/order-intelligence-filter-layout`。筛选卡使用 `position: relative` 时仍继承全局 `.toolbar` 的导航高度 `top`，造成视觉下移和指标卡覆盖；页面局部设置 `top: auto`，保持原有文档流和层级。
- 本地浏览器使用真实 OrderFilters、FilterBar 和页面 scoped CSS 隔离复现：修复前 99px 偏移造成 81px 重叠；修复后在 2383、1440、1280、820、390px 宽度下，收起/展开、查询/重置事件、滚动及横向溢出检查通过，筛选卡与指标区保持 18px 间距。使用合成数据，无生产请求；证据及复验脚本在本 worktree 的 `tmp/oi-layout/`，夹具位于 `frontend/tmp/oi-layout/`。
- 验证：前端生产构建、严格增量约定检查及 diff 检查通过；构建保留现有混合导入/大分包提示。Git 巡检已执行，为 `--no-fetch` 本地快照。

## 2026-10-16 新版订单发票录入布局与包装费用入口（Codex，Git 交付，未部署）

- 分支 `codex/invoice-entry-packaging`：新建时隐藏币种输入，编辑已有单据保留；订单号/发票号、下单日期和小满标记前移至联系与收货信息上方。单号框沿用备注金色边框，文字增至 16px、金色加粗。
- 物流与备注卡在运费右侧增加包装数量、包装费用录入；右侧结算栏同字段改为灰底只读跟随。保持原字段、保存契约、金额计算、数量不乘费用及预售运费归零规则，未改后端或旧版布局。
- 验证：前端生产构建、94 项相关 Node 回归通过；隔离真实页面在 1440/1280/390px 验证字段顺序、金色样式、新建/编辑币种显隐、包装实时显示、零值/负值截断/小数精度、合计、保存重开与预售边界。测试接口均为本地模拟，无生产请求。证据位于本 worktree 的 `tmp/invoice-entry-browser/`；构建保留既有混合导入及大分包提示。约定增量、diff 检查通过，独立审查无阻断发现；Git 巡检已执行，为 `--no-fetch` 本地快照。

## 2026-10-16 设计素材文件夹自动匹配客户标签（Codex，Git 交付，未部署）

- 分支 `codex/customer-media-folder-tags`。设计管理 → 上传素材：拖入或选择文件夹后，仅取顶层文件夹名称并删除全部空白，与当前客户已有标签匹配；命中后替换所有原选中项，文件夹及子目录内文件仅使用该标签。未命中时提示“发现新标签，是否自动创建并选中？”，确认后通过现有客户标签接口创建并绑定当前客户；取消跳过该文件夹，创建失败不按旧标签加入清单、不自动重发。
- 多个顶层文件夹分别保留对应标签快照；混合拖入的独立文件保留原手动选择。无预选标签也可添加文件夹，匹配期间暂停继续添加、修改标签和上传。仍沿用“加入清单 → 开始上传”的提交方式，不改变送审或发布流程。文件夹处理提取到独立 composable；需求说明同步至 `docs/requirements/2026-08-13-customer-media-portal.md`。
- 验证：26 项客户素材 Node 回归通过；本地 Chrome 浏览器 10 项关键路径通过，覆盖实际 drop 处理、选择文件夹、去空格、替换旧选择、确认/取消/关闭、多根目录及上传 `tags_json`，页面错误为 0；原有草稿预览及分组筛选回归通过。浏览器接口均为内存替身，未请求生产库。夹具补齐正式页面已有的全局 DetailDrawer / StatusBadge 注册。
- 前端 `npm run build` 通过，保留既有混合导入/大分包提示；增量约定和 diff 检查通过。`python scripts/git_sweep.py --no-fetch` 完成，为本地快照；其他 worktree/分支欠账保留。用户授权本次提交、合并推送至 main，主目录原有改动备份后保留；生产未部署。

## 2026-10-15 预售出库弹框加宽与产品区滚动（Codex，本地完成，未合并部署）

- `ShipmentSettlementDialog.vue` 从 760px 加宽至 1120px，沿用视口减 24px 的上限；正常录入和恢复原提交的产品表使用 `max-height=clamp(220px, 42dvh, 420px)`、固定表头、独立滚动和可聚焦滚动容器。产品列可查看溢出提示，数量控件尺寸与提交行为沿用原逻辑。
- 产品表复用 `density-compact`，33 行夹具的实测行高由 59px 降为 51px。用户明确要求的 1120px 宽度通过既有 `ui_component_exceptions.json` 按组件登记一处例外，并同步 DESIGN.md；没有修改宽度通用白名单或抬高债务基线。
- 验证：1440×900、1280×720、390×844 三种屏宽实测无页面横向溢出，产品区高度约 378/302/354px，滚轮及键盘滚动、表头固定、外层位置和首尾产品数量保留均通过；另有桌面/手机共 10 个取消场景和 6 项 UI 门禁回归通过。前端生产构建、严格约定和本次 diff 检查通过，保留既有混合导入/大分包提示。浏览器使用本地真实组件及合成 API，无生产请求；证据在本 worktree 的 `tmp/shipment-layout/`、`tmp/shipment-layout-cancellation/` 和 `tmp/shipment-layout-build.log`。Git 巡检为 `--no-fetch` 本地快照。

## 2026-10-15 预售批次取消入口与暂停提示（Codex，本地实现，未合并发布）

- 分支 `codex/presale-cancel-actions`。修复资金池预占金额被前端误判为实际批次付款、导致取消入口隐藏的问题。批次读取返回后端共用的 `actions` 判定和原因，取消命令继续校验当前权限、版本、资金与出库关联；不放宽实际付款、运费绑定、执行中/不确定或已生成出库单的保护。
- 后续补齐缺货等“明确失败、没有生成小满出库单”的手工取消：`review_required + failed`、无远端 ID/租约/基线、编号及快照完整、无确认历史的任务可从同一取消入口提交。先锁外 GET 精确单号，规范无单后重新授权并比对完整业务绑定，最终一次提交取消结算/任务和释放占用；保留原失败证据及回款，两条审计分别保留完整用户原因和无单核验依据。远端已存在、查不清、版本/权限/资金/确认历史变化均不释放占用；原失败任务不再调度或重试。
- 暂停提示明确保留数量和资金占用；取消按钮显示不可用原因。取消成功后校验回执目标与版本、清除旧报价，刷新可出库数量和当前结算详情；原回款与审计保留，后续报价使用释放后的资金池。数量输入在额度/可用状态变化时重建，避免组件挂载时写入的 ARIA 上限和禁用状态残留。
- 验证入口：`backend/tests/test_shipment_actions.py`、既有预售 runtime/settlement 测试；`frontend/tests/shipmentSettlementState.test.mjs`、`shipmentCancellation.browser.mjs`。浏览器使用真实 Vue 组件和客户端、本地替身 API，覆盖桌面/手机的暂停、取消、重新报价和不可取消原因；不代表线上业务验收。本次未新增生产写入、迁移、合并、推送或部署。
- 最终验证：SQLite 联合回归 144 项、Node 状态/回执/恢复回归 19 项、1440px/390px 两种宽度各五类页面场景通过。独占 MySQL 8.4.6 上新增手工取消专项 15 项全部通过，涵盖真实 JWT/当前权限、锁外查询、最终授权和资金/任务/确认历史变更拒绝、全表变更白名单、取消后新建与阻止旧任务重试；扩大状态回归累计 72 passed 后遇既有手续费断言失败，不能称 MySQL 全套通过。在未修改的 Git `220632a34cea90e054a04bdd1ae71b8d3cfa1a8c` 完整源码快照上独立复现 `test_original_funding_sync_guard[syncing-cancel]` 同一创建阶段失败：`presale_goods.bank_charge` 实际 0.00、旧断言期待 2；未改动费用逻辑或弱化断言。
- 前端生产构建、增量约定和 diff 检查通过，独立审查无阻断。构建保留既有混合导入/大分包提示；Git 巡检为 `--no-fetch` 本地快照。最新浏览器证据在本 worktree 的 `tmp/shipment-failed-cancellation-browser/`，构建日志为 `tmp/presale-failed-cancel-build.log`，原版本复现日志为 `tmp/failed-cancel-baseline-pytest.log`；三个独占 MySQL 实例均正常关闭。测试使用合成业务数据和远端替身，没有生产写入。
- 收尾：Vite 本地预览已停止。自动审批拒绝清理本任务的独占 MySQL 数据目录和原版本源码快照，工具仅返回 `blocked by policy`；未改用其他路径绕过，`tmp/failed-cancel-*-mysql-*`、`tmp/failed-cancel-baseline*` 及日志保留。此限制不影响功能实现，但不能宣称临时目录已清理。

## 2026-10-15 WhatsApp 手机扫码失败调查（Codex，Git 交付，未部署）

- 现场只读确认本次凭据未注册、没有设备身份；15:43:13 发生内部 `authorization_unavailable` 并保护暂停。已记录的 133 次后端授权请求均 HTTP 200，旧日志无失败细分和耗时，不能锁定唯一根因。rc14 缺少上游提及的注册刷新处理，但尚无本次触发证据。
- `codex/whatsapp-pair-diagnostics` 补固定白名单诊断：配对阶段、通知名称、断线码、授权失败类型/耗时；不记录二维码、JID、凭据、正文或异常原文，不改变保护暂停和协议处理。用户授权本次合并推送；未部署或恢复账号，下一步需发布诊断候选后由持有人重新扫码取证。
- 验证：Connector 串行全套 49 项、非东八区诊断 4 项、语法/严格约定/diff 检查通过，独立审查无阻断；并行检查曾触发旧 500ms 租约用例时序失败，未改断言，已串行复验。Git 巡检为 `--no-fetch` 本地快照。
- [调查、证据与验收边界](reports/2026-10-15-whatsapp-pairing-diagnosis.md)。

## 2026-10-15 发票联系信息折叠与运费录入优化（Codex，Git 交付，未部署）

- 分支 `codex/invoice-editor-contact-freight`：新版新建/编辑共用客户资料折叠；联系人、电话、邮箱、收货地址四项全有才默认收起，空白按缺失处理，缺项展开。可手动查看修改，补齐时不抢焦点，编辑回显保留本单快照，客户/联系人异步切换沿用序列保护。
- 运费统一在左侧快递渠道下面录入，右侧只读同步同一字段；保存、合计、包邮标记及预售运费禁用/归零规则沿用原逻辑。折叠使用 `v-show` 保留输入组件，避免地址自动高度计算在卸载后报错；窄屏网格按内容排布，避免两栏退为单栏后互相覆盖。
- 验证：86 项相关 Node 回归、前端生产构建、增量约定检查通过，独立审查无待修问题；实际浏览器 1440px/390px 验证客户完整/缺项、键盘展开、修改、运费只读同步/零值、保存重载及预售禁用。所有业务请求为内存替身，未触达生产库。构建保留既有混合导入/大分包提示；Git 巡检为 `--no-fetch` 本地快照。
- 回归入口：`frontend/tests/invoiceContactFreight.browser.py`，夹具 `frontend/tests/fixtures/invoice-contact-freight/`。本次交付范围为合并推送至 main，不含部署；主目录其他改动备份保留。

## 2026-10-15 WhatsApp 二维码与关联恢复（Codex，Git 交付，未发布）

- 办公室 Connector 直连 WhatsApp 超时，本机 1080 HTTP 代理 HTTPS 200/WebSocket 101；补专用代理接入。解绑后旧绑定仍 pending 导致再次关联 403；修复解绑关闭会话、历史停止会话退出待处理队列、停止状态安全回读。有效未知操作不重复 POST，原撤销授权不恢复。
- 后端隔离回归 44 项、Connector 全套 45 项通过（含真实本地 WebSocket 与历史下载 CONNECT 传输）；独立审查发现的历史下载 dispatcher 缺口已修复，约定检查和本地 Git 巡检完成。用户授权本次合并推送，保留主目录既有修改；不含生产部署或代理配置。真实二维码/扫码尚未验收，上线仍需明确授权。
- [现场证据、修复与上线范围](reports/2026-10-15-whatsapp-qr-recovery.md)。


## 2026-10-15 公告图片点击查看原图（Codex，Git交付，未部署）

- 分支 `codex/announcement-image-preview`：右上角公告通知 → 选择公告 → 点击正文图片，打开原图预览，支持缩放、旋转与适应窗口/原始尺寸切换；关闭预览保留当前公告，焦点回到图片。Enter/空格可打开，Esc 只关闭最上层预览。
- 复用 `KnowledgeImageView.vue` 的鉴权 Blob 与 Element Plus 图片预览，不重新请求图片；同组件的知识文档阅读模式同步支持预览，编辑模式保留原有图片选择和编辑。加载失败图片无预览入口，组件卸载后丢弃迟到的加载结果并释放 Blob URL。
- 验证：公告 Node 回归 9 项、既有图片上传/粘贴/保存/编辑浏览器回归、前端生产构建、约定检查通过；隔离浏览器验证 1280px/390px 的通知入口、阅读状态、1600px 原始图片、缩放、键盘、焦点、公告切换与加载失败状态通过。业务请求全部使用本地替身；构建保留既有混合导入/大分包提示。Git 巡检为 `--no-fetch` 本地快照。
- 本次交付范围为合并推送至 main，不含部署；回归入口 `frontend/tests/announcementPreview.browser.py`，夹具 `frontend/tests/fixtures/announcement-preview/`。

## 2026-10-14 内贸订单详情操作权限拆分（Codex，已授权合并推送部署）

- 分支 `codex/domestic-operation-permissions`：新增 `domestic_report:write`（代报工、选工人、撤销报工）与 `domestic_skip:write`（异常跳过、跳过审计及撤销跳过）；按钮与后端接口同步校验。角色权限矩阵展示两个独立中文选项。
- 既有 `domestic:write`/`domestic:admin` 不替代新权限；seed 不自动补授普通管理员及既有角色，super_admin 保留平台豁免。上线重启后需在角色管理显式分配，重新登录刷新权限；小程序报工与订单阅读范围不变。撤销他人报工仍需管理权限，已发货、下游实际报工、异常原因与幂等保护保留。
- 验证：隔离 SQLite 联合后端 172 项通过；补充管理员撤销边界后权限专项 39 项通过（属于联合测试的扩展，不重复累加）；前端按钮显隐/条件工序/权限矩阵 14 项及 `npm run build` 通过；独立审查无阻断。构建保留既有混合导入/大分包提示；约定增量与 diff 检查通过，Git 巡检为 `--no-fetch` 本地快照。
- 已完成本地实现与验证；用户已授权合并推送及完整生产部署，执行结果另行登记。API 权限说明已同步。先前“管理员创建发货批次明细为空”的原因已定位，本次未改变发货权限。

## 2026-10-14 回款删除与内网 HTTP 修复（Codex，Git交付，未部署）

- 本轮按亮哥“合并推送”授权，将回款删除入口及统一浏览器兼容修复纳入main交付；实现与验证历史保留在以下条目及两份专题报告。摄像头不改，无生产权限修改、业务写入、部署或数据库迁移。
- 主目录未提交改动按SHA256备份并核验，整合时保留既有文档整理与历史；Git交付不代表生产功能已上线。
- 接入最新main后，隔离SQLite后端联合回归221项、Node相关154项、完整前端构建、基点覆盖本次提交的严格约定检查及diff检查通过。此前内网HTTP浏览器与独立审查证据保持有效；原有invoice controller夹具缺依赖单独记录。

## 2026-10-14 内网 HTTP 统一兼容修复（Codex，本地实现，未部署）

- 同 `codex/receipt-delete-entry` 分支：23个随机标识调用文件接入安全随机UUIDv4工具，保留原提交/重试生命周期；9个主站复制调用文件和手机素材页4个入口接入共享复制工具。手机页失败时提供实际链接手动复制，不报成功、不记复制动作；Vite生产输出包含同源码模块。摄像头按要求不改，无生产权限或业务数据写入。
- Node相关151项及回款列表3项通过；真实LAN HTTP复制粘贴、拒绝复制、焦点恢复、手机dev/生产构建、两角色补登记、批量回款与发货结算三宽度恢复测试均通过，业务API均本地替身。构建与独立复审通过。原有invoice controller测试夹具缺少依赖已用HEAD原测试复现，单独记录，未称全文件通过。
- 未合并、推送或部署；[实现及验证记录](reports/2026-10-14-browser-http-compatibility.md)。

## 2026-10-14 内网 HTTP 补登记回款无响应（Codex，本地修复，未部署）

- 对「翟 #261027」只读核验：所属业务员已有 `receipt:write`，生产服务允许访问且无登记阻塞；未修改生产权限或新建回款。
- LAN HTTP 下 `crypto.randomUUID` 缺失，弹窗 setup 抛错且未发起登记请求；相同访问环境下普通业务员和管理员均复现。改用 `crypto.getRandomValues` 生成 UUIDv4，单弹窗固定 request key，保留失败后重试幂等标识。
- 实际 LAN HTTP 浏览器两角色回归通过：打开弹窗、模拟上传、首次503保留资料、同键重试成功，全部业务API本地拦截；UUID格式及两次payload相同断言通过，独立只读复审无阻断。同 `codex/receipt-delete-entry` 分支保留，未合并、推送或部署。详见[验证记录](reports/2026-10-14-receipt-delete-entry.md#内网-http-补登记回款无响应)。

## 2026-10-14 单笔回款删除入口（Codex，本地实现，未部署）

- 分支 `codex/receipt-delete-entry`，独立worktree：订单「实际回款与待收」和回款详情底部新增删除入口，沿用 `receipt:delete` 当前数据库权限及本人订单范围，不自动修改角色授权。普通未发送款本地作废；已同步款最多一次小满删除请求，核实删除后归档，保留金额/手续费/凭证/自动生成意图/审计，不退款、不改订单或出库、不自动重建回款。
- 未知结果显示「删除待核验」，业务员可从原入口继续GET核验；额度继续冻结，后台回读、其他编辑/恢复及整单删除不能覆盖原删除意图。原生成意图保留converted。索引未反映移除时，等待现有后台重建后刷新资金汇总再补登记；无schema变更或手工改索引。
- 隔离SQLite相关联合回归220项、补充删除专项/证据39项、Node 11项、7组实际浏览器交互与最终前端构建通过，独立审查发现的后台回读竞态已修复且独立复现复审通过。审计只存财务证据，不存提供方私有文件URL。约定/diff检查通过，Git巡检为no-fetch本地快照。未合并、推送、部署或再次操作生产回款；详见[实现及验证记录](reports/2026-10-14-receipt-delete-entry.md)。

## 2026-10-14 物流跟踪分页被裁切（Codex，本地修复，未部署）

- 分支 `codex/tracking-pagination`，独立工作区 `C:/Users/windb/.codex/worktrees/tracking-pagination/commission-system`。分页进入表格卡片后，页面仍限制 `100vh - 100px` 高度并隐藏溢出，表格卡片被 flex 压缩，普通滚动无法到达分页；模拟运单在 1440×900 下复现。
- 移除旧页面高度与 flex 限制，让主内容区按内容滚动；CSS 全屏卡片显式允许纵向滚动。只调整物流页布局，不改变查询、分页参数或业务数据。
- `frontend/tests/trackingPagination.browser.mjs` 与真实 MainLayout/TrackingList 隔离测试入口覆盖 1440×900、1366×768、1024×600、390×844：正常翻页、每页100条、全屏翻页均通过，无浏览器运行异常。测试拦截全部 API，不连接业务库；截图和结果保存在 `tmp/tracking-pagination/`。
- 前端 `npm run build`、`python scripts/check_conventions.py` 与 diff 检查通过；构建仅有已有分包大小/混合导入提示。Git 巡检为 `--no-fetch` 本地快照。未提交、合并、推送或部署。

## 2026-10-14 内贸客户提成分配与订单快照（Codex，Git 交付，未部署）

- 分支 `codex/domestic-commission-snapshot`：新客户为保存时归属销售默认配置 4%；客户管理、下单就地建档和导入新客户均覆盖。客户编辑支持 1～2 人直接提成率，新建订单选客后展示分配及合计，配置变动返回 409 更新显示后再提交。
- 首次保存业务单（含草稿）同事务保存人员/姓名/比例快照；客户调整、人员改名/停用、提交/重审、追加明细和幂等重放保留快照。草稿实际换客户重建并审计；生产单不参与，公开进度不返回提成。历史缺快照不根据当前配置回填。
- 新迁移 `196_domestic_commission` 接 `195_main_portal_merge`，只建两张空表。上线前需配置存量客户的分配；未配置阻止新业务单，已有单正常编辑不受影响。生产升级只能走正式部署入口。本次不计算/发放提成，不改共享数据库。
- 独立审查发现并修复 MySQL 旧 read view、旧建单请求指纹兼容和换客快照事件客户归属问题，复审通过；前端构建、3 项展示逻辑与 11 项浏览器交互通过。原始 HEAD `974bfd8a` 已复现一个与本次无关的终止订单发货错误文案断言失败，保留业务行为和原断言。
- 本次按亮哥授权合并 main 并推送 origin，未执行生产部署或迁移。截图随 Git 交付，原始验证与主目录保护材料保留在 `.deploy_state/domestic-commission-main-20261014/`。最终测试及使用边界见 [实现记录](reports/2026-10-14-domestic-commission-snapshot.md)。
- 最终整个内贸域回归 1002 通过、1 个上述原有文案失败、1 个隔离 MySQL 可选测试跳过；严格约定检查与 diff 检查通过，Git 巡检为 `--no-fetch` 本地快照。

## 2026-10-14 WhatsApp业务号关联失败（Codex，已合并推送并部署）

- 北京连接器回环8787指向色块服务（健康404）；办公室唯一Baileys connector健康200。云端关联走错服务，原始创建错误被回查404覆盖。
- 分支 `codex/whatsapp-bind-error`：补云端域路由及原始错误保留；办公室另有同步锁账号后HTTP、connector回调再锁账号的互等路径，已改无锁fetch后锁定当前读验授权/游标，pending回查前释放锁，停止状态不再无限轮询。后端50项、部署99项、前端6项通过，独立审查通过。
- 最近关联13:37创建成功后自动同步两次失败authorization_unavailable、刷新502；13:38用户已发起撤销，现revoke_pending/consent revoked，保持该授权。后端与前端需普通应用发布，路由专项不能替代；并发回归为隔离SQLite，真实扫码与MySQL双事务未验收。
- 完整前端同源码镜像构建通过，临时依赖junction清理被自动审批拒绝并保留；构建证据在tmp/whatsapp-build。
- 用户授权后，修复4242440b接入最新main、合并推送974bfd8a；两地应用受管发布准备/正式均exit0，schema195不变，无迁移，发布身份47c2429b76ce4571b61623d692f86792。静态保留清理结束，发布锁释放。
- 两站WhatsApp路由已受管激活，配置摘要与候选一致。三个入口账号/关联查询均200，已有撤销关联显示revoke_pending且无QR；北京运行环境登录JWT经路由也通过办公室鉴权。原账号授权字段完全保留，两域前端摘要与构建一致；未代重新授权，真实扫码/历史同步仍待持有人验收。证据见主目录.deploy_state/whatsapp-bind-release-20261014/及[修复记录](reports/2026-10-14-whatsapp-bind-error.md)。

## 2026-10-14 出库费用行误触发整单补验（Codex，Git交付；固定单据已纠正，未部署）

- 分支 `codex/shipping-fee-recheck`，独立 worktree `C:/Users/windb/.codex/worktrees/shipping-fee-recheck/commission-system`。只读审计确认“翟 #261023”/记录93362/检验651的实物和发货备注未改；10月13日22:39清理两条重复 `Other Items` 费用行时，同步事件8109误将整单照片5760失效并自动撤回。10月14日已补拍此前缺失的实物明细342498，当时阻塞仅为错误的 `__whole__`。
- 费用行新增/变更/删除与实物变化分开计算，同步预览和完成采用同一判定；不误触发自动撤回/照片失效，实物与费用互换、未知身份、真实实物/备注变化仍需补验，已有待补验/失效证据保留。无数据库迁移或前端改动。
- 原实现新增费用回归先复现失败；最终隔离 SQLite 同步/补验/共用手机/镜像刷新联合回归203项通过，严格约定检查与diff检查通过，Git巡检为 `--no-fetch` 本地快照。独立 agent 审查无阻断问题，建议的 `auto_recall=True` 与同步级已有补验保留覆盖已补齐；仅既有JWT和SQLAlchemy弃用警告。
- 用户明确授权“允许移除整单补拍要求恢复有效性”后，固定对象重新只读预检通过，仅将事件8109的 `stale_media_ids=[5760]` 和 `required_recheck_ids=['__whole__']` 纠正为空；事务内新增维护审计8520。生产独立连接逐字段回读确认其余同步字段、全部检验字段与8张照片完整保留，草稿/版本1不变，未代提交。写入脚本默认dry-run、锁序沿用Invoice→同步事件→检验→媒体，镜像锁之前使用当前锁定读取；写前完整备份先于UPDATE，未知提交结果禁止重跑。
- 恢复材料与预检/回读证据保留在主目录 `.deploy_state/shipping-fee-main-20261014/evidence/`；固定对象脚本为 `repair-261023-fee-recheck.py` 与 `readback-261023-fee-recheck.py`。用户已授权合并main并推送origin，最终提交与保护校验以该目录Git交付回读为准；本轮不执行部署。

## 2026-10-14 出库单查询性能（Codex，Git 交付，未部署）

- 独立分支 `codex/outbound-search-performance`；目标为 leshine.cloud 出库单打印页查询「翟 #261023」。镜像客户归属改为用户客户集合子查询，免逐单检查；首页空结果免重复计数，后续空页仍返回真实总数。
- 北京云端只读、同一事务快照、每组 3 次候选/原代码处理函数对比：目标带归属查询 540→134ms、首次列表 708→151ms、空结果 930→42ms；6 组完整响应 SHA256 相同。未向运行服务写入候选代码，未变更业务数据、权限或 schema；未完整复现用户浏览器近 5 秒端到端等待。
- 105 项受影响回归、独立 agent 审查、严格约定检查和 diff 检查通过；本地 Git 巡检已运行（`--no-fetch`，本地快照）。用户已授权提交、合并 main 并推送 origin，最终结果以远端回读为准；本次不部署。证据与边界见[性能验证记录](reports/2026-10-14-outbound-search-performance.md)。
- 用户补充截图确认实际请求为 `www.leshine.cloud/api/shipping-inspection/outbound-records`，线上整模块经北京→新加坡→办公室转发。未鉴权即时 403：本地直连公网 1.30–1.83s，经截图同端口 MonoCloud 代理 2.29–3.27s；北京本机约 5ms。此前北京处理函数计时未覆盖实际转发链路。已补北京纯列表 exact 本机路由候选，其他子路径/媒体/写入仍办公室；41 项专项路由测试和独立复审通过。两端配置读回的数据库身份、JWT 及相关源文件一致；已基于线上配置仅在本地渲染两处受管块并验证幂等，未执行生产 prepare、激活或部署。后续需应用发布与 `--shipping-video-routing-only` 专项分别生效，并验收真实登录请求。
- 用户进一步要求打印、Word 也在北京处理：已先核对北京运行进程环境、办公室 NSSM 配置覆盖/.env 和早于进程启动的源文件；数据库/JWT、当前与旧版二维码密钥、二维码挑战摘要、小满 base/client 配置和共享 token 全一致。两端使用现有 token 读取固定目标均 200、出库身份/负责人一致，且实际内存生成含二维码 Word 成功；探针无 token 刷新、业务 POST 或 DB 写入。新增窄正则仅放行 print-data/word 到北京，其余上传/媒体/同步/删除继续办公室。43 项路由回归、170 项打印/同步回归通过；两个旧打印测试补齐替身字段/关键字支持，未弱化断言。应用原有打印状态锁和 token 懒刷新提交保留，不能把打印描述为严格无写。配置候选仍未部署。

## 2026-10-14 公告图片外框与比例（Codex，Git 交付，未部署）

- `codex/announcement-image-ratio`：原图保持比例，但 display 高度上限 640px 把 100×2000 长图缩成 32×640；灰底、120px 最小高度及 8px 内边距造成大框。已移除加载成功后的外框/灰底/内边距和高度上限，仅超出正文宽度时等比缩小；选中时描边只围绕图片，说明与删除控件保留。
- 浏览器六组尺寸/桌面与 375px 窄屏验证通过，100×2000/600×1800 长图完整显示，小图保持原尺寸，保存规范属性；选中框不占布局。原文件选择/原生粘贴/失败保护浏览器回归通过；Node 18 项、前端生产构建和严格约定检查通过。
- 本次只改展示，未改上传/COS/持久数据；用户已授权合并 main 并推送 origin，结果以远端回读为准；未部署。证据归档在主目录 `.deploy_state/announcement-image-ratio-main-merge-20261014/evidence/`，规则见 `docs/module-notes.md` 知识库图片段落。

## 2026-10-14 待审核角标静默刷新（Codex，已授权合并推送，未部署）

- 分支 `codex/quiet-review-badge`：内贸待审核数量请求关闭全屏遮罩，轮询改 60 秒；焦点与可见性事件合并，慢请求不重叠，成功操作仍补查更新。
- 失败保留上次数量；首次未知不显示 0。组件退出、账号或权限变化取消旧请求，迟到结果不能覆盖新身份。
- 34 项相关 Node 回归、8 场景真实 Edge 受控接口验证、完整构建、增量约定检查通过；0 真实业务 API 请求。旧鉴权测试替身缺少反馈模块导入，在未修改 HEAD 也复现，单独记录。
- 用户已授权本次提交、合并 main 并推送 origin；以远端回读为准，未部署。详见[修复与验证记录](reports/2026-10-14-quiet-review-badge.md)。

## 2026-10-14 发票明细表 UI 约定修复（Codex，已授权合并推送，未部署）

- 独立分支 `codex/invoice-ui-conventions`；产品/配件表16处固定width改min-width，数字控件用自身类撑满单元格，价格内部样式覆盖回到既有基线1；未改基线或业务计算。
- 69项受影响Node回归、5场景/10组件真实Edge布局与交互验证、原Vite配置同源码完整构建通过，独立审查无阻断项；约定门禁原17项已消除，其他冻结债务保留。0真实API请求。
- 用户已授权本次提交、合并 main 并推送 origin；未部署。验证依赖解析/源码镜像、临时链接清理拦截与证据见[修复记录](reports/2026-10-14-invoice-ui-conventions.md)。主目录既有整理和其他修改保留。

## 2026-10-14 内贸规格默认价（Codex，Git交付，生产数据已修正，代码未部署）

- 分支 `codex/domestic-spec-price`；用户已授权提交、合并main并推送origin，最终结果以远端读回为准，未部署。普通订单修改定价规格后刷新默认价和价格快照，保留成交价；同次改价用新原价校验，真实偏差仍审核，失败完整回滚。锁序与建单一致。
- DO20261013-003/A2（订单255/明细447）默认价已由2530修正为2498；按用户最终确认，保留实际生产中状态及扣款4496。独立全列读回：成交价、A1、订单、钱包和扣款流水不变；目标价格偏差标记false。修正留有备份与审计，不篡改真实审批。
- 新增13项回归通过，原实现9项失败证明缺陷；受影响8组联合验证477 passed、1 skipped，排除1项已在主目录复现的旧迁移head硬编码失败。完整门禁既有17项发票UI失败在主目录同样存在；增量约定无发现，独立审查通过，diff检查与本地Git巡检完成。
- 规则与数据证据见 [修复记录](reports/2026-10-14-domestic-spec-price.md)。主目录未提交文件及其他worktree未动；固定对象脚本与恢复证据保留在主目录 `.deploy_state/domestic-spec-price-repair-20261014/`。

## 2026-10-14 顶栏公告主题色圆点（Codex，Git 交付，未部署）

- 分支 `codex/announcement-unread-dot`。数字角标改为右上角 8px 主题色圆点，未读数 > 0 时才挂载；常亮中心 + 1 秒扩散淡出层，移除旧光晕及左下光点。减少动态偏好保留静态圆点；未读数量仍用于 title/aria-label。
- 控制器 8 项回归、生产构建与真实组件浏览器验证通过；覆盖已读失败/成功、0/1/120 未读、主题色、动画帧、触屏及减少动态。增量约定 0 问题，全量仍有既有 17 项发票 UI 门禁问题。
- 用户已授权合并 main 并推送 origin，结果以远端回读为准；未部署或修改生产已读数据。规则与证据见 [公告提醒验收](requirements/2026-10-10-announcement-inbox.md)。

## 2026-10-14 公告大图上传（Codex，Git 交付，未部署）

- `codex/announcement-large-image`：编辑公告约 2.2M 图片在 30–40 秒失败，与共享图片上传继承 30 秒超时一致。图片请求放宽到 180 秒；大图按 2400px 上限尝试同格式压缩，保留 PNG/WebP 透明背景；错误区分超时、断网、413 与业务信息，无自动重发。
- 线上只读确认北京 `knowledge` 已启用 COS、应用限制 10MiB。浏览器先传业务后端再写 COS；没有逐段耗时证据，不认定 COS 写入慢。
- Node 21 passed；真实浏览器约 34 秒 XHR 一次请求成功，压缩/透明背景及原有图片编辑回归通过，构建通过。约定脚本受既有 17 项发票 UI 问题阻断；差异检查、Git 本地巡检已执行。
- 用户已授权合并 main 并推送 origin，最终结果以远端回读为准；未部署或生产上传。证据及边界见 [大图上传修复](reports/2026-10-14-announcement-large-image.md)。

## 2026-10-14 出库单库存详情（Codex，合并推送交付，未部署）

- 分支 `codex/outbound-stock-details`；用户已授权提交、合并 main 并推送 origin，最终结果以远端 main 回读为准；未授权部署。交付代码与报告保留在主仓库。
- 出库单每行新增「库存详情」抽屉；支持待库存任务与正式单，展示需求、目标仓库可用/实存/不可用数量、缺口、SKU、原单行号及同步时间；缺失资料显示待核对。只读 GET 沿用出库权限/归属，已核实明细快照优先于旧镜像。
- 只读核对「翟 #261025」：invoice 1080 / order 105855231969009 / task 593，目标仓库 8193514242746；第 6 项平型 18/#P2/8/1g（产品 6481），需要 100、可用 40、缺 60、实存 500。小满创建报错序号与库存镜像一致，库存远端查询 scope 不足。没有补库、重发或修改业务数据。
- 后端库存详情/队列 43 passed；独立审查通过。构建通过；项目约定检查仍有 17 项发票编辑 UI 基线问题，本次新增 UI 检查项已修正。完整证据见 [库存详情交付记录](reports/2026-10-14-outbound-inventory-details.md)。

## 2026-10-13 翟 #261023 重复费用修正（Codex）

- 已按授权修正生产订单1067/小满26568及出库单：旧35+81.84费用删除，保留116.84，订单614.02、出库573.98；本地误绑UID已纠正。
- 原回款1147已通过标准重试/发送恢复，小满ID105852674092690；独立GET确认本金614.02已生效，方舟含费644.72及手续费30.70、原凭证不变。
- 五张验货照片保留；正式同步流程撤回原验货，需仓库补拍整单照片并重新提交。未代验货、未外发通知。
- 同商品多行身份匹配及受理待核对保护已在codex/invoice-261023-repair修复，独立审查通过；SQLite200、独占MySQL64通过。全约定检查仍被既有17项UI基线阻断，本次增量规则0问题。
- 用户已授权本次修复合并main并推送origin；代码未部署，Git交付结果以origin/main回读为准。详见[修复记录](reports/2026-10-13-invoice-261023-fee-repair.md)。

## 2026-10-13 生产历史与Agent修复主线交付（Codex）

- 用户明确授权将本次生产保留的迁移历史和Agent部署修复合并回main并推送，保留主目录已有修改。交付包含183/186门户历史、195双父迁移节点、部署恢复与Connector准备预检、旧Agent安全暂停和云端原模型复用；不包含主目录其他未提交工作。
- Git整合前对主目录29项未提交文件逐字备份并保存patch、状态和SHA256清单，暂存区为空。恢复时保留已有文档内容，生产报告由原未跟踪文件纳入版本控制；恢复证据保存在主目录tmp/full-main-integration-backup-20261013。
- 本次只执行Git交付；生产主平台仍a7d39aaa/schema195，专用Agent仍3c7448cc，未重复部署、迁移或模型探针。部署与独立审查证据见两份2026-10-13报告；实际推送结果以origin/main读回为准。

## 2026-10-13 旧研究任务收尾与专用Agent发布完成（Codex）

- 用户追加授权核验收尾task251/customer628并更新Agent。原private enrichment uncertain gate保留，事实0；现有API一次重领、一次完成research_gap_v1。旧Run267取消并保留、新Run268 completed，task completed/not_required，正式账号/事实/档案版本逐字不变，实际客户补全GET200。
- 专用Agent统一deploy.bat七阶段及最终exit0，实际runtime3c7448cc、active/enabled、Gateway RPC passed、原mimo-v2.6-flash及云key/地址不变，token11身份保持，旧7原inactive。heartbeat0m，不自动消费队列、不开邮件；主平台仍a7/schema195。
- 修复新版controller安全暂停旧runtime和云端模型复用入口：精确unit/旧ready检查后暂停，其余制品检查保留；reuse旧模型证明/key，拒绝漂移，最小模型探针仅一次，未知不自动重发。回归59 passed/1 POSIXskip、MCP17通过、独立审查完成，原17项UI基线保留。
- 实际安装版SDK/stdio以ark-sales用户探针通过：工具schema含research_gap_v1、task251 context completed、gap contract正确；没有90:* running研究。源文件摘要与本地一致。受保护原始快照仅云端；脱敏回执/日志.deploy_state/sales-agent-followup-20261013，旧服务配置保留。详情[追加更新记录](reports/2026-10-13-sales-agent-upgrade.md)。代码/195历史保留codex/full-main-production，本轮未推origin。

## 2026-10-13 最新main主平台生产发布（Codex，独立研究Agent待旧任务解锁）

- 用户授权根据远端全部最新合并代码部署。origin/main基点77622edf，生产固定候选a7d39aaaffff6a9d5337ecaac60edb4f3c86fcb2保留f526生产门户/恢复历史并包含全部main。两台实际HEAD一致，deploy.bat完整发布exit0，publish succeeded/deferred=[]；资源保留后检三目标succeeded，服务及两公网health200/connected。
- 共享库实际195_main_portal_merge，五步前向迁移仅186_domestic_delivery/192/193/194/195，八张新表读回存在，schema-writers completed。没有stamp/downgrade。原27处主目录修改逐字备份核验，不纳入发布；此新交接段单独追加。
- 预售批次先出库后回款、导航、内贸交付、WhatsApp/Baileys和助手、编辑器插图、小图喜报及研究资料不足主应用API/UI已发布。新Connector认证health200；旧4账号保持旧provider/pending，消息0，未重绑、未外发聊天或模型请求。出库legacy与timer active/enabled，邮件仍inactive/disabled；两地主站制品一致，其他三个静态目标未变。
- 后端898 passed/2 skipped；部署805 passed/18 skipped/1已在未修改main复现的storage mock失败；最终迁移/环境28 passed，隔离MySQL升级1 passed、前端52、Connector41、真实入口预检4 passed。17项原UI基线问题保留。独立迁移/发布审查完成。
- 独立Agent仍a9f0cd88/active/heartbeat0m，MCP无research_gap_v1。task251/customer628仍running、lease过期；专用发布器要求旧任务先结束，已async询问是否纳入该任务核验收尾，答复前保留事实和服务，不伪造完结。因此Agent端闭环尚未更新。
- 195及生产门户历史在codex/full-main-production，本轮未推origin（仍77622edf）；后续主线发布必须先合入已运行迁移历史，不能用194图覆盖195库。部署及恢复证据.deploy_state/full-main-release-20261013-r2，首个快进准备失败记录单独保留。详见[生产发布记录](reports/2026-10-13-full-main-production-release.md)。

## 2026-10-13 预售按批次先出库后回款（Codex，Git交付，未部署）

- 分支 codex/presale-credit-batches，独立 worktree C:/Users/windb/.codex/worktrees/presale-credit-batches/commission-system；基点c15b1d2c。本轮按用户授权合并main并推送origin；未部署，未写生产/小满或共享库；主目录已有27处修改备份并独立保留，不纳入本次提交。
- 每批冻结 payment_term，默认及历史先付款；信用批保留应收、真实欠款和原回款引用，检验完成仍可后补款，后补款及未发送纠错不回退出库。历史正常欠款允许下一先款批按自身资金规则出库；真实已生效资金失效仍阻断。回款提供历史信用批候选，多候选明确选择并冻结目标版本；一次到账仍每订单选择一批。
- 无新表/列/迁移。运费waiting_target精确绑定、共享预付款多批回读和旧版报价余额读取已覆盖。受影响后端312通过，最终信用/runtime63通过（重叠）；owned MySQL真实权限/并发/陈旧快照6通过；Node27通过；真实Vue/Chrome合成API桌面1440/手机390/320关键路径和生产构建通过；独立复审无阻断项。
- 严格约定检查保留主目录同样的17项产品表UI基线问题；git巡检已跑no-fetch，已有186编号分叉不在本次修改范围。正式小满“先出库后回款”完整顺序尚未联测。详见 [验收记录](reports/2026-10-13-presale-credit-batches.md) 与 [业务规则](requirements/2026-10-13-presale-credit-batches.md)。
- 与main个人收藏导航1eca312a整合后，受影响后端含导航327 passed、Node27 passed、生产构建通过；仅handoff冲突，两项记录均保留。
- 测试进程已停止，无本任务mysqld残留；临时数据库目录清理被工具自动审批拦截（blocked by policy，未提供详细原因），tmp/credit-mysql至credit-mysql-6保留。日志、运行元数据和页面证据已保存。

## 2026-10-13 常用导航（Codex，Git交付，未部署）

- 分支 `codex/favorite-navigation`；worktree `C:/Users/windb/.codex/worktrees/favorite-navigation/commission-system`。侧栏顶部支持添加/移除、拖拽与键盘排序，服务端按当前用户隔离保存，刷新恢复；复用既有菜单权限与路由。
- 新迁移 `194_navigation_preferences -> 193_wa_ai_assistant`，只新增本人配置表，已注册 Alembic metadata；未执行生产/共享库迁移。API、数据库与 DESIGN 文档已同步。
- 用户追加限制已落实：候选同时满足route/menu/group权限，PUT新增以数据库实时权限校验，无权/未知键403，旧JWT不能绕过。构建生成带navigation.js源哈希的后端权限清单（需与源码一并交付）；不依赖独立部署的前端dist，缺失/过期清单拒绝新增503。
- 后端隔离 SQLite 13 passed；前端权限/状态/导航/任务契约 24 passed、异步竞态5 passed；构建和真实侧栏+SQLite浏览器验收通过（含直接伪造无权新增403）。独立审查指出的迁移模型注册及北京清单部署路径已修复；本次增量规则0项，全仓仍有原17项发票UI债务。详见 [验收记录](reports/2026-10-13-favorite-navigation.md)。用户已授权提交、合并main并推送origin；不部署、不执行共享库迁移，保护主目录已有改动。

## 2026-10-13 两项发票同步修复合并推送与生产发布（Codex）

- 普通保存后同步原发货单号、重复SKU首次创建收尾与原单恢复两项修复已合并推送main，代码合并点55b4c5b7。主目录27个原修改/未跟踪文件已保护、恢复并核验。
- 生产使用固定f5269d9d候选，保留c797c45e现役门户及bf31b5f7部署恢复保护；仅挑入两修复，9个相关源码文件与main一致。未部署main的WhatsApp/内贸新模块或迁移，生产仍为186_portal_announcement_merge。后续全main发布必须保留这段生产历史并显式汇合迁移，不得覆盖/stamp/downgrade。
- 统一deploy.bat先准备再完整切换，publish-current/publish-success=succeeded、deferred=[]；办公室/北京实际HEAD均f5269d9d，服务健康，两公网health均200/ok/connected。出库保持原legacy和timer active/enabled；邮件Worker保持原disabled/inactive；五静态目标无变化。最终执行/资源保留回执在本轮归档目录。
- main整合及生产候选分别260回归passed；生产候选新增实际MySQL7 passed，部署协议102 passed。完整约定仍有既有17项发票UI债务。先前扩展恢复6项失败已在未修改主分支复现，未将其伪报通过。
- 两历史单只读核验：1053目标号可识别为翟 #261022，原发货单仍Ginny-KC-1001；1064实时8行UID可在内存正确匹配，但本地持久UID仍空、仍sync_uncertain。未发送改号/恢复业务POST、未重复建单。发布候选分支codex/invoice-sync-production及恢复材料保留。详见[发布报告](reports/2026-10-13-invoice-sync-production-release.md)。

## 2026-10-13 重复 SKU 首次创建收尾与已受理恢复修复（Codex，本地验证，未发布）

- 只读实查发票 1064 `ly1010复购库存单`：原小满订单 105851516280181 已受理，8 行、33 件商业数据一致；本地 8 个 UID 全空，卡在 sync_uncertain。两个同 SKU 的 5×18.20 与 1×18.21 分行在收尾/恢复时被编辑新增限制误拦截。已有原发货单 XSCK2610130502，未写生产数据。
- 分支 `codex/invoice-create-line-recovery`，worktree `C:/Users/windb/.codex/worktrees/invoice-create-line-recovery/commission-system`。仅已有行核对跳过 fresh duplicate 发送限制；重复行匹配数量/价格/金额，既有 UID 商业含义不改绑；accepted 先落事实，再无锁 GET 原单核验，不重发。现有授权、租约、库存、回款及版本保护保留。
- SQLite 117 passed；实际当前授权 MySQL 扩展 81 passed、6 个主分支已有绑定/迟到恢复失败（HEAD 基线同样复现）；最终新增场景独立复跑 4 passed。真实 8 行只读反序验证全部 UID 可在内存匹配，missing=0，线上仍为待核对。独立审查通过，diff/增量约定通过；完整约定仍阻断于既有 17 项发票 UI 债务。未合并、推送或部署。详见 [证据与限制](reports/2026-10-13-invoice-duplicate-line-recovery.md)。

## 2026-10-13 发票改号后原发货单单号同步修复（Codex，本地验证，未发布）

- 只读实查「翟 #261022」发票 1053：小满订单已在 11:25 更新新号；唯一待出库单 105851418127778 实时仍为 `Ginny-KC-1001`，与镜像一致；没有关联同步记录。根因是普通保存后同步未从成功推单历史恢复改号意图，原逻辑仅检查关联同步 before/after。
- 分支 `codex/invoice-outbound-number`、独立 worktree `C:/Users/windb/.codex/worktrees/invoice-outbound-number/commission-system`。新旧号通过同订单成功请求/响应历史确认；每次预览及发送重新检查当前发票号和出库旧号，防止覆盖并发仓库改号；沿用多单/预售/已出库/重号/不确定结果保护。
- 隔离 SQLite 143 passed；本地自有 MySQL 当前授权路径 3 passed；独立审查发现的旧号竞态已修复并复审通过。完整约定门禁仍被既有 17 项发票 UI 债务阻断，增量代码规则 0 项；diff 检查、Git 巡检已执行。诊断与证据见 [报告](reports/2026-10-13-invoice-outbound-number.md)。未合并、推送、部署或修改线上单据。

## 2026-10-13 公告编辑器插图与截图粘贴修复（Codex，已验证并获合并推送授权，未部署）

- 用户反馈编辑公告时截图/本地图片无法粘贴或插入。共享 `KnowledgeEditor` 的上传占位 ID 直接调用 `crypto.randomUUID()`；在缺此 API 的非安全页面环境，操作在上传前抛错。隔离 Edge 基线复现 `crypto.randomUUID is not a function`，上传请求为 0；正常环境的文件插入和原生 Ctrl+V 成功。未以推断替代用户实际访问地址核验。
- 临时占位 ID 改为页内模块级单调序号；仅用于上传结果关联，不作为权限/幂等凭据，不进入保存正文。上传入口检查可编辑状态；公告和知识库共享修复，不改变图片 API、权限、私有存储或规范 `assetId/alt/caption`。分支 `codex/announcement-editor-images`，独立 worktree `C:/Users/windb/.codex/worktrees/announcement-editor-images/commission-system`，不夹带上轮目标群修复候选。
- Node 回归 28 passed，前端生产构建通过（既有混合导入/chunk 警告）。`webapp-testing` 方法的真实 Vue/Tiptap + Edge 隔离适配器验证：选择文件、原生剪贴板图片 Ctrl+V、缺 UUID 情况、保存与重载、图片实际解码、上传中/失败保存阻断、撤销后再粘贴、重叠上传、知识库编辑与只读禁止上传全部通过，无真实业务写入或消息投递。浏览器回归入口 `frontend/tests/announcementImages.browser.py`，证据 `tmp/announcement-images/{before-confirmed,after}/`。
- 独立审查通过，无新增 P1/P2。完整约定检查仍被主分支同样存在的 17 项发票 UI 债务阻断；增量代码规则为 0 项，未弱化门禁。用户已授权将本次修复合并 main 并推送 origin；未授权部署。集成核验及主目录原改动保护回执位于主目录 `.deploy_state/announcement-images-main-merge-20261013/`，修复尚未上线。

## 2026-10-13 销售研究 Agent 与资料不足修复 Git 交付（Codex，已授权合并推送，未发布）

- 用户授权本次合并推送，仍保留“暂不发布”。从最新origin/main整合codex/sales-agent-cloud，交付范围为专用云端Agent配置/部署入口与research_gap_v1 API/MCP/UI修复；不合入独立候选分支中的其他门户历史提交，不执行生产发布、迁移或自动消费。
- 独立生产修复候选a99af84079114d7b73f6de918539ea42c5993e22 / codex/private-research-gap-hotfix继续保留，及其受管worktree、恢复资料和页面证据；运行中的云端Agent仍是2026-10-12已验版本。后续发布需按当时线上版本重新核对差异，并单独同步专用MCP/Skills/HEARTBEAT。
- 主目录他人未提交改动先做文件级备份与Git恢复快照，合并后核验恢复；不夹带其内容提交。实际集成验证与推送结果见本任务最终回执。
- 最新main整合后的隔离SQLite回归153 passed；部署安全20 passed、1项POSIX检查在Windows跳过；MCP/策略14 passed、前端逻辑42 passed，前端构建通过（既有混合导入/chunk警告）。约定检查仍命中main本身的17项发票UI债务，相关两文件与main逐字一致，未扩为本次修复。备份及恢复核验位于主目录.deploy_state/sales-agent-main-merge-20261013。

## 2026-10-12 销售研究 Agent 北京接入（Codex，MiMo 已验证，资料不足修复待发布）

- 独立分支 codex/sales-agent-cloud。专用runtime a9f0cd8856c9a5789c79a9e6a9ffec7424e283c1，deployer89ff4a2d；用户MiMo文件只通过SSH stdin进入私有0600文件。mimo-v2.6-flash真实提供商探针和Gateway回复、RPC/active/enabled读回通过，main heartbeat仍0m。专用profile清理未使用DeepSeek，原通用Gateway保留。
- MCP probe、实际 Parallel Free 搜索、HTTPS task251 context 契约与凭据权限通过；新凭据11有效、旧 Mac 凭据7已吊销，没有扩大90号账号权限。
- Crystal customer628/task251按attempt1做一次CAS重试，旧Run266保留，新Run267/attempt2实际MiMo研究未核实到主体，零事实。用户确认无其他线索。线上完成接口必须有facts/citations，无法正常结束资料不足；任务仍running，未改档案或假标完成。
- 已完成research_gap_v1 API/MCP/UI候选：仅私海full_research、uncertain门控、当前Run零事实；租约/Run/hash绑定仍有效，继承更严格分级，保留旧档案和门控，禁止质量审核/资格/编排采纳。独立审查修复两项风险后通过。原开发分支有线上外业务改动，另从两台后端实读9e16a4e1制作唯一修复提交a99af84079114d7b73f6de918539ea42c5993e22，worktree sales-gap-hotfix / codex/private-research-gap-hotfix；不发布原开发分支。
- 北京邮件 Worker disabled/inactive、冻结和既有数据保留；Mac 历史队列/会话无源快照，未迁移。未发邮件、未推送或合并main；主应用资料不足修复尚未获发布授权。报告 docs/reports/2026-10-12-sales-agent-cloud-preparation.md；运行边界 deploy/sales-agent-cloud.md。发布后受控恢复task251并验收，完成前不启自动消费。

# 当前交接与待办

整理日期：2026-10-31。本次发布仅含整理增量；下文标为“本机材料”的文件仍属于其他任务未跟踪成果，不随本次提交。以下依据仓库中的发布/验收报告与本地源码核对；本轮未连接生产、未刷新远端。部署版本是**最近已有记录**，不能代替操作前的实时核验。API、表结构与操作步骤分别维护在对应参考文档，本页只记录状态、证据与下一步。

## 最近生产发布记录

| 项目 | 最近已有证据 | 范围与出处 |
| --- | --- | --- |
| 主平台 | 2026-10-30 发布 `f79af9499de46f9609c93872648af9b2f519aa09`，release ID `454cbb57b56c4a0ababc34395ec7620c`；办公室与北京实际 HEAD 一致，26 项必需检查通过 | `office-and-cloud`；详见发布报告（本机材料：`reports/2026-10-30-full-main-production-release-f79af949.md`）。没有生产退货/退款验收写入。 |
| 共享数据库 | 标准入口执行 `213_salary_snap_export_cols → 214_sales_return_ledger`；8 张退货表、9 个外键、6 项权限及回款来源列已独立回读 | 仅代表该次发布后的核验；不据此执行降级、stamp 或重复迁移。 |
| 本次功能范围 | 外贸退货与本地负数回款、外贸回款截图选填、出库单按实际订单业务员过滤已包含在该次发布 | 实现记录中的“未部署”是当时状态。退货权威库存入库仍未接通。 |
| 上一轮发布 | 2026-10-29 `7b5fdd0b`：目标设置/绩效看板、验货单物流录入与薪资导出，schema 212→213 | 发布报告（本机材料：`reports/2026-10-29-full-main-production-release-7b5fdd0b.md`）。不把构建和健康检查等同于登录态业务验收。 |
| 客户门户 | 2026-10-28 `c66daee6` 与迁移 212 已发布；随后有真实浏览器验收及修复记录 | 发布（本机材料：`reports/2026-10-28-full-main-production-release.md`） · [验收范围](reports/2026-10-29-portal-live-acceptance.md)。报价阶段验收不等于实际下单、PI 或通知全链验收。 |
| 服务运行基线 | 最近发布保留北京出库 timer active/enabled；邮件 Worker inactive/disabled，新加坡历史 okki-sync inactive/masked | 指独立 Worker/历史服务，不代表所有模块邮件或门户认证邮件都关闭；具体开关与实际发送须分别核验。 |
| 本地 Git | 本地 `main` 与缓存 `origin/main` 均为 `f79af949`，工作区有既有未提交文档和登录页等其他任务成果 | 2026-10-31 本地快照；未 fetch，不能代表远端实时状态。本次文档整理已获提交、合并及推送授权；生产版本不因文档交付而改变。 |

## 仍需处理或取得验收证据

| 事项 | 已有范围与下一步 | 依据 |
| --- | --- | --- |
| 外贸退货库存入库 | 已有退货财务、实收和续检；权威库存写入契约未接通，不能把收货当作已增加可售库存。后续需明确库存系统契约并完成对应验收 | [退货实施记录](reports/2026-10-30-sales-return-implementation.md) |
| 客户门户经营闭环 | 已验收地址、批价保存恢复、库存门槛和登录展示；实际订单提交、新短号、无样本物流入口及通知不能据报价验收推定完成。开展业务验收前核对真实开关、客户与授权范围 | [浏览器验收](reports/2026-10-29-portal-live-acceptance.md) · [发布与验收入口](../deploy/customer-orders.md) |
| 门户首次开放工具的版本限制 | `enable-access` 仍要求 schema 恰好为 183，`prepare` 拒绝已启用门户；对当前更高版本的环境不能照抄首次开放步骤。若需要在更高版本首次开通，先修正并验证版本条件；不影响已开放门户的发布记录，本轮仅修正文档 | [专题适用条件](../deploy/customer-orders.md)；`deploy/customer_portal_config_remote.py` |
| WhatsApp 真实关联和历史覆盖 | Connector 已有发布与多轮扫码修复；账号重新关联、覆盖缺口和 AI 外发授权仍需具体账号证据。10 月 13 日账号数量/状态不沿用为现状；服务健康不等于已登录 | [服务与恢复](../services/whatsapp-connector/README.md) · [扫码恢复记录](reports/2026-10-15-whatsapp-qr-recovery.md) · [10 月完整时间线](archive/handoff-main-2026-10-31.md) |
| Kindle 真机同步 | 207 迁移及后端代码已进入后续主线发布链；PW3 客户端可见和中文排版有历史确认。绑定账号、真实同步、休眠与耗电的端到端证据仍未在当前材料中补齐，不能按旧“未执行迁移”标题重跑迁移 | [设备契约](requirements/2026-10-25-kindle-dashboard.md) · [历史交接](archive/handoff-main-2026-10-31.md) |
| 内贸客户跟进一期 | 主目录保留设计 v2 和一期计划；本地巡检已发现 `claude/domestic-followup` 独立 worktree 有在途改动，不能仅据主目录材料判断实现状态，继续原任务时核对该工作区与验收证据 | 设计（本机材料：`requirements/2026-10-30-domestic-customer-followup.md`） · 计划（本机材料：`superpowers/plans/2026-10-30-domestic-customer-followup-phase1.md`） |
| 客户工作台 v2 与其他独立任务 | 本地实现记录、分支和历史待办保留；业务试点、来源覆盖、各自交付状态仍须查对应证据，不代替其他任务合并或清理 | [v2 实施与剩余证据](requirements/customer-workbench-v2-prototype/IMPLEMENTATION.md) · 本地 Git 巡检 |
| 旧业务验收待办 | 订单 261023 的仓库复核、预售信用批正式业务联测及早期展会/接口/监控待办仍保留线索；没有新的结案证据就不标完成，重新开展前先核查后续记录 | [10 月 14 日待办快照](archive/handoff-main-2026-10-31.md) · [更早待办](archive/handoff-main-2026-10-31.md#待办事项优先级递减) |
| 部署制品维护 | 最近发布将静态/候选清理登记为 deferred 维护，不是应用发布失败；未在本轮执行清理 | [维护入口](../deploy/README.md) |

## 文档整理与已纠正的旧状态

2026-10-31 完成全项目 Markdown 目录与本地引用盘点；本轮整理证据见报告（本机材料：`reports/2026-10-31-project-knowledge-tidy.md`）。重点同步门户密码登录与申请邮件激活的并存契约、补齐绩效目标表与接口索引，并将散落的交付阶段状态移回本页。

- 原“当前交接”中 `4667d0c1 / a7d39aaa / schema 193` 是 10 月 14 日快照，不再作为最新版本。
- 原发票 UI 的 17 项约定错误已有后续修复记录，本轮 `check_conventions.py` 也通过；历史失败证据保留，不能继续当作当前未解决的 17 项。
- 发布版将原主线 5,989 行完整转入[2026-10-31 快照](archive/handoff-main-2026-10-31.md)，保留记录顺序、当时结论和所有未完线索；本机原有未提交交接另保留本地快照，未夹带发布；归档不构成结案，也不延续其中历史操作授权。

## 维护与历史查找

| 信息 | 维护来源 |
| --- | --- |
| 协作、Git 与共享记忆边界 | [AGENTS.md](../AGENTS.md)；技术约定见 [CLAUDE.md](../CLAUDE.md) |
| 发布、迁移与恢复 | [deploy/README.md](../deploy/README.md)；故障依据见 [runbook.md](runbook.md) |
| 接口、表结构与领域知识 | [API 参考](api-reference.md)、[数据库参考](database.md)、[模块笔记](module-notes.md) |
| 全部文档与常用入口 | [完整目录](document-catalog.md)、[文档导航](README.md) |
| 历史进度、技术债与已知问题 | [10 月 31 日快照](archive/handoff-main-2026-10-31.md)、[9 月 17 日快照](archive/handoff-2026-09-17.md) |

后续记录先更新受影响事项及其证据；历史原始过程放日期型报告。生产变更前仍核验实际运行版本、schema、writer 与未完成恢复日志。

## 2026-10-31 交易双路线主线集成（未部署）

- 本次开发提交 `65ff00d0`，在 `codex/commerce-transition` 整合主线 `a77f50ac`，保留验货要求、订单分组、退货退款和主线文档归档。
- 候选迁移227–245下接主线214，已发布208–214保持不变；安装仍为legacy_only、独立对比默认关闭。本次不执行生产迁移或部署。
- 本轮集成冲突处理、复验及Git状态以[集成记录](reports/2026-10-31-commerce-transition-integration.md)为准；原实现与隔离验收证据见[开发报告](reports/2026-10-28-commerce-dual-route-implementation.md)。
- 主目录其他任务的未提交内容另行备份和恢复，不纳入本次开发提交。
