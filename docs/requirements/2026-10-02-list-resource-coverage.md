# 主站列表与独立读取资源覆盖账本

更新：2026-10-02。工作目录：`C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`。本账本记录本轮已经逐项识别、实现与复核的主站资源；包括主列表、独立标签页、抽屉子集合、固定首批、游标历史和独立辅助读取。公开库存另有1条已迁移资源；外部客户门户、kiosk及独立`frontend-pm`的专用流程不纳入主站普通列表计数。

**当前账本：277个唯一语义资源，P 85 / F 74 / B 34 / C 3 / S 81。已知待实施项0。** 每一行给出实际类型与读取边界；“已接入”不等于真实生产和所有浏览器流程已验证。代码最终统一验收见[DESIGN.md](../../DESIGN.md)和[handoff.md](../handoff.md)，本页不把测试总数或组件数量作为全站业务完成证明。

## 判定与证据边界

- **P**：界面真实使用后端page/page_size或offset/limit及items/total；普通主列表保留分页和已提交筛选/排序。
- **F**：按指定业务范围返回完整数组、树或配置集合；保留全量/本地筛选语义，不制造服务器分页。
- **B**：界面消费固定首批、最近N条或远程候选；必须明示实际数量/时间边界，不能称为完整集合。即使后端有total，未翻页的消费方式仍记B。
- **C**：游标或序列追加历史；成功才推进cursor、按身份去重，失败保已成功历史，切scope清旧。
- **S**：详情、汇总、完整目录组合、文件预览及工作流状态。消费分页接口的total/最新row也按摘要S记录，不冒充完整列表。
- **语义资源**按独立读取、查询范围与错误/提交所有权记一行：同endpoint不同页面scope可以分别计数；共享桥本身不计；同响应metadata/嵌入数组不多计；按行并发的同类Blob/categories记一个资源类别。
- 普通列表使用`useListPage`；完整/辅助资源使用`useAsyncResource`或已有等价控制器；专业游标、逐行请求、URL与任务轮询保留对应控制方式。只有实际测试列出的first/stale/late/query/CRUD路径才称为验证过。
- 读错误进入资源状态；同scope失败保成功数据，换客户/用户/route/字典类型先清旧并取消；metadata只有当前响应提交。创建回首页面、更新保有效页、删除末页回退；读取失败不倒转已完成写入的事实。
- `useAsyncResource.load`返回boolean；loader之外的编辑器hydrate、选择恢复、URL与timer等副作用另有current/version校验。筛选草稿不会被分页、排序、刷新、轮询或写后读自动提交。
- 第7节列10类专业/外部流程边界。它们说明适用的交互规则与验证范围，不是整文件门禁豁免；静态门禁的非md GlassButton例外仍是19个路径的精确计数登记。

## 1. 财务与首阶段分页资源

| 资源 ID / 页面或控制器 | 类型 / API 与真实边界 | 查询、作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| invoice.rows — invoice/composables/useInvoiceManagePage.js | P，发票列表，items/total | 日期、业务筛选、排序、发票权限；编辑金额行属于本地表单 | 第一阶段已接入；listPagePilots；金额编辑表不改为远端列表 |
| receipt.rows — receipt/useReceipts.js | P，收款列表，items/total | 查询/排序与收款范围；余额/分配仍是业务逻辑 | 第一阶段已接入；listPagePilots；写入与读刷新分离 |
| domestic.orders — domestic/composables/useDomesticOrders.js | P，内贸订单列表，items/total | 路由查询仅在 DomesticOrders 激活时应用；同名路由恢复；detail 独立读取 | 第一阶段已接入；路由 create 返回/独立详情失败回归通过 |
| commission.batches — commission/CommissionBatch.vue | P，getBatchList，data.items/total | status、排序；创建先页1，计算/确认/作废等刷新当前有效页 | 已接入；financialListResources 验证写成功读失败与草稿隔离 |
| commission.details — commission/CommissionDetail.vue | P，getBatchDetails(batchId)，data.items/total | batchId、keyword、排序；批次变更清旧数据 | 已接入；summary 独立资源；financialListResources |
| commission.summary — commission/CommissionDetail.vue | S，getBatchSummary(batchId)，data 对象 | 独立批次范围，失败不阻断明细 | 已接入 useAsyncResource；financialListResources |
| commission.self-batches — commission/SalesCommission.vue | P，getMyCommissionBatches，data.items/total | 用户、status/role/month/keyword；切用户清列表及选中批次；当前响应才恢复选择 | 已接入；financialListResources；用户与详情竞态属于重点 |
| payment.synced — payment/PaymentSync.vue | P，getSyncedPayments，data.items/total | 已提交 dateRange -> date_start/end，keyword、排序；重置保留同步日期上下文 | 已接入；financialListResources；汇率保留独立精度 |
| customer.snapshots — customer/CustomerSnapshot.vue | P，getSnapshotList，data.items/total | keyword、salesperson_keyword、is_complete=all/true/false、排序 | 已接入；financialListResources 保留三值边界与页语义 |

## 2. 原有分页与桥接业务资源

| 资源 ID / 页面或控制器 | 类型 / API 与真实边界 | 查询、作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| outreach.queue — mail_outreach/MailOutreachQueue.vue | P，mail jobs，items/total | 取消是更新；信箱选项独立 | 已接入；controller/compile；实际权限/选项待浏览器 |
| hub.timeline — customer_hub/workspace/WorkspaceTimeline.vue | P，客户时间线，items/total | customerId，切客户清旧；无编辑筛选不造 FilterBar | 已接入；controller+mounted 重试 |
| hub.customers — useCustomerHub.js | P，客户集合，items/total | 创建回页1、修改保有效页 | 已桥接；详情流程待验 |
| hub.acquisition — useCustomerHub.js | P，获客任务，items/total | status；保留 polling/create remount | 已桥接；polling 生命周期待验 |
| hub.research — useCustomerHub.js | P，研究集合，items/total | quality；批量创建语义 | 已桥接；权限待验 |
| hub.opportunities — useCustomerHub.js | P，商机集合，items/total | 无可编辑筛选；状态转换仍领域所有 | 已桥接；状态转换待验 |
| hub.radar — useCustomerHub.js | P，雷达集合，items/total | 无可编辑筛选 | 已桥接；领域转换待验 |
| hub.directory — customer_hub/CustomerDirectory.vue | P，客户目录，items/total+metadata | c_ URL、四主筛选+高级；summary/current guard | 已接入；mounted 首错重试；URL 导航待验 |
| hub.workbench — customer_hub/WorkbenchList.vue | P，工作队列，items/total+capacity | w_ URL、客户/ownership scope；容量独立元数据 | 已接入；controller race；准入流程待验 |
| hub.qualifications — QualificationPanel | P，operations bridge | 客户/决定范围，修改刷新 | 已桥接；抽屉待浏览器 |
| hub.evidence — EvidencePicker | P，operations bridge | customer/kind/opportunity/target_status；跨范围清选择 | 已桥接；scope/reset controller；多选 UI 待验 |
| hub.mail-drafts — MailOutreachPanel | P，drafts bridge | customerId；创建回页1 | 已桥接；双范围 controller；整抽屉待验 |
| hub.mail-jobs — MailOutreachPanel | P，jobs bridge | customerId；保存按更新 | 已桥接；双范围 controller；整抽屉待验 |
| agent.tasks — agent-runtime/AgentTaskCenter.vue | P，tasks，items/total | task filters；评估操作不归列表 | 已接入；controller/compile |
| aftersales.cases — aftersales/AfterSalesList.vue | P，cases，items/total | reviewMode 路由、日期；四主+高级 | 已接入；scope/controller；审核权限待验 |
| announcement.documents — announcement/AnnouncementList.vue | P，文档，items/total | editor saved event 标明 created | 已接入；创建/改/删语义；保存事件待 UI |
| battle.order-review — battle-report/components/ReportDaily.vue | P，order review，items/total+metadata | report/team/member/day；矩阵/详情独立 | 已接入；4 个现有 race 用例；矩阵不算列表迁移 |
| training.digests — training/TrainingList.vue | P，digests，items/total | mine 纳入 submitted；删除回退 | 已接入；mine/page/reset controller |
| card.customers — card/composables/useCardButler.js | P，客户页，items/total | card entry 更新影响客户页 | 已接入；controller；salespersons/entries 另列 |
| card.inquiries — card/composables/useCardButler.js | P，询盘页，items/total | 分派/处理按更新 | 已接入；controller；权限待验 |
| domestic.customers — domestic/composables/useDomesticCustomers.js | P，客户页，items/total | owner scope；province draft cascade；reset 保范围 | 已接入；controller+6 个 controls；ledger 另列 |
| domestic.customer-requests — useDomesticCustomerRequests.js | P，客户申请，items/total | review 更新；voucher 独立 | 已接入；controller |
| domestic.products — domestic/DomesticProducts.vue | P，products，items/total | price/route 更新；craft mapping 另列 | 已接入；controller |
| expo.stores — expo/StoreManagement.vue | P，stores，offset/limit -> items/total | 创建/编辑分流；users/quota 独立 | 已接入；offset controller |
| expo.leads — expo/ExpoLeads.vue | P，leads，items/total | detail polling；delete remove | 已接入；controller；polling UI 待验 |
| expo.prompts — expo/PromptVersions.vue | P，versions，items/total | keyword/status；create/edit/default | 已接入；controller；preview 另读 |
| expo.beautify-prompts — expo/BeautifyPromptVersions.vue | P，versions，items/total | keyword/status；publish/archive 更新 | 已接入；controller；preview 另读 |
| sales.search-jobs — sales_automation/SearchJobs.vue | P，jobs，items/total | polling；create/requeue 生命周期 | 已接入；controller；polling UI 待验 |
| sales.research-batches — PublicPoolResearch.vue | P，batches，items/total | pageSize10；任务 keyword/tier 是本地批内筛选 | 已接入；controller |
| sales.research-tasks — PublicPoolResearch.vue | B，每批任务集合，固定 cap300 | 批 ID 独立取消/错误/重试；全批动作不能变当前页动作 | 已接入等价 current/cancel/error/retry 控制器；保留 cap300 批内操作；listAdoption |
| ai.gateway-apps — system/components/AiGatewayApps.vue | P，apps，items/total | create/edit/rotation/toggle | 已接入；controller；真实 keys 待验 |
| ai.gateway-requests — AiGatewayApps.vue | P，requests，items/total | selected app scope；切 app 清旧；reset 保 app | 已接入；scope controller |
| salary.profiles — salary/composables/useSalaryProfiles.js | P，profiles，items/total | submitted sort；新建/编辑分流 | 已接入；sort/create/update controller |
| shipping.outbounds — shipping/composables/useOutboundRecords.js | P，outbounds，items/total | 参数转换、delete/remove、allow/recovery/update | 已接入；领域 controller；print/download 独立 |
| shipping.inspections — useInspectionRecords.js | P，inspections，items/total | 四主+高级日期；recall/update | 已接入；PDF 边界；print 独立 |
| color.palette — color/PaletteView.vue | P，colors，body.data.items/total | 四筛选、写语义；共享 client 已解 Axios 一层 | 已接入；真实 envelope controller；detail 待验 |
| color.blends — color/BlendView.vue | P，blends，body.data.items/total | sort/snapshot；配色约束仍业务 | 已接入；envelope controller |
| color.swatches — color/SwatchGenerator.vue | P，swatch history，body.data.items/total | 无列表筛选；generator 表单不是筛选；完成后 create refresh | 已接入；envelope controller；polling 待验 |
| insight.reports — insight/IntelligenceOverview.vue | P，reports，body.data.items/total | 无列表筛选；create/remove/pin | 已接入；envelope controller；调度/生成另读 |

## 3. 已迁移分页资源

| 资源 ID / 页面或控制器 | 类型 / API 与真实边界 | 查询、作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| stock.overview — stock/StockOverview.vue | P，getStockOverview，items/total/summary | status/models/types/sizes/colors/weights 数组逗号 join；server sort；stock_items 内嵌 | 已接入；stock 专项 current summary/snapshot/retry |
| stock.safety — stock/SafetyConfig.vue | P，getSafetyList，items/total | 同上加 has_in_transit/has_safety_stock；suggested_qty/dirty/_ai 不改计算 | 已接入；stock 专项 math/late AI/save update |
| stock.orders — stock/ProductionOrderManage.vue | P，getProductionOrders，items/total | status/keyword/sort；visible-page statusCounts | 已接入；独立于生产 item 页 |
| stock.order-items — ProductionOrderManage.vue | P，getProductionOrderItems，items/total | 独立 filters/page/sort；修改后订单汇总也刷新 | 已接入；stock 专项 |
| stock.print-orders — ProductionOrderPrint.vue | P，getProductionPrintOrders，items/total | status=0 有效；print_state；默认 created_at desc；_categories 不可串行写错行 | 已接入；stock 专项 category race；真实打印待验 |
| semifinished.orders — semifinished/OrderManage.vue | P，getSemifinishedOrders，直接 items/total | create/page1；receive/terminate/current；详情失败不误报已收货 | 已接入；stock 专项 |
| semifinished.materials — MaterialManage.vue | P，getMaterials，直接 items/total | resource discriminator=materials；keyword/review_only；切资源清选择 | 已接入；stock 专项 |
| semifinished.mappings — MaterialManage.vue | P，getMappings，直接 items/total | discriminator=mappings；retry 不读取草稿 tab | 已接入；stock 专项 scope |
| semifinished.inventory — InventoryManage.vue | P，getSemifinishedInventory，直接 items/total | keyword；调整后当前 query | 已接入；stock 专项 |
| semifinished.ledger — InventoryManage.vue | P，ledger，items/total | materialId；原固定首100，现独立页20/50/100；抽屉 material 与 adjustment 分开 | 已接入；stock 专项 ledger race/paging |
| production.products — production/ProductManage.vue | P，getProducts，直接 items/total | model/route_bound/show_disabled；server sort | 已接入；manualListAdoption |
| production.processes — production/ProcessManage.vue | P，getProcesses，直接 items/total | name/status；disabled 的0不得被 truthy 丢掉 | 已接入；manualListAdoption；创建失败读与末页删回归 |
| employee.attributes — employee/EmployeeAttribute.vue | P，getEmployeeList，data.items/total | keyword/sort | 已接入；manualListAdoption |
| supervisor.relations — supervisor/SupervisorRelation.vue | P，getSupervisorList，data.items/total | keyword/sort | 已接入；manualListAdoption |
| system.users — system/UserManagement.vue | P，getUserList，data.items/total（auth API wrapper 返回 body） | keyword/sort；用户权限不变 | 已接入；manualListAdoption |
| tracking.shipments — tracking/TrackingList.vue | P，getShipmentList，data.items/total | keyword/status/carrier/is_active/sort；kanban 是明确提交动作 | 已接入；manualListAdoption kanban/reset |
| design.my-requests — design/MyRequests.vue | P，getRequests，data.items/total | keyword/status 数组 join；self/强制 salesperson=auth user；expect date/sort | 已接入；designListAdoption 实际 controller/挂载验证，强制 self 与 actor scope 保留 |
| design.audit — design/AuditQueue.vue | P，getRequests，data.items/total+stats | pending_audit/operator supervisor；附件计数另 async collection | 已接入；分页 metadata 当前提交，附件计数独立错误；designListAdoption |
| design.pending — design/composables/useDesignManage.js | P，getRequests，data.items/total | expect_start/end/designer/operator；独立 page/sort | 已接入独立分页/日期与排序快照；designListAdoption |
| design.scheduled — useDesignManage.js | P，getTaskList，data.items/total | plan_start/end/designer；独立 page/sort | 已接入独立分页；开始按更新、取消按删除语义；designListAdoption |
| design.completed — useDesignManage.js | P，getTaskList，data.items/total | completed 范围与日期；独立 page/sort | 已接入独立分页；完成后创建刷新；designListAdoption |
| assets.library — asset/AssetLibrary.vue | P，getAssetList，items/total+available tag IDs | tag_filters JSON；keyword/sort；维度父子/分组 sidebar 是专业筛选 | 已接入真实分页/当前 facet/草稿快照；assetExpoListAdoption 与挂载首错重试通过；专业 sidebar 保留 |
| insight.library — insight/IntelligenceLibrary.vue | P，listItems，body.data.items/total | source_types/credibility_labels join；start_date/end_date；sort | 已接入；真实 body.data 信封、snapshot/stale/current；insightGovernanceAdoption |
| governance.concepts — governance/ConceptRegistry.vue | P，listConcepts，body.data.items/total | filters/sort；statsResource 独立 | 已接入；分页与独立统计；insightGovernanceAdoption |
| governance.change-log — governance/ChangeLog.vue | P，listChangeLogs，body.data.items/total | filters/page；审核按 update | 已接入；分页快照、审核后 update；insightGovernanceAdoption |
| ai.logs — system/composables/useAiManager.js | P，getLogs，body.data.items/total+summary | module/status/dates -> caller_module/date_from/date_to；submitted sort/page；current summary | 当前 logState 已接入；aiManagerResources 实际 snapshot/stale/late summary 通过 |
| invoice.festival-orders — invoice/composables/useFestivalOrderDetail.js | P，listFestivalOrders，items/total | type/user/keyword；summary 与列表独立资源；身份约束保留 | 已接入独立分页，summary 独立失败；scopedLedgerResources |
| orders.customer-actions — order_intelligence/composables/useOrderIntelligence.js | P，getCustomerActions，items/total | base date/team/countries/models/colors/sources + as_of/risk/country | 已接入真实分页；全局/客户已提交快照、隐藏标签取消；orderIntelligenceResources |
| hub.customer-orders — customer_hub/workspace/WorkspaceOrders.vue | P，getCustomerOrders，items/total | customerId；换客户清旧，analytics 独立 | 已接入 customer scope 分页；切客户先清/取消，同 scope 保成功行；scopedLedgerResources |
| hub.acquisition-results — customer_hub/AcquisitionTasks.vue | P，listSearchJobResults，items/total | jobId；换 job 清旧，同 job 失败保成功行 | 已接入 job scope 分页；首错重试/同 job stale/换 job 清；scopedLedgerResources |
| expo.quota-records — expo/StoreQuotaDrawer.vue | P，records，items/total | storeId；offset=(page-1)*size，limit；recharge 写后独立读 | 已接入 store scope 分页与 20/50/100 offset；读错不倒转充值成功；scopedLedgerResources |
| domestic.customer-ledger — useDomesticCustomers.js/loadLedger | P，ledger，items/total | customerId；固定 page_size20 | 已接入独立 customer scope 分页，首错/stale/重试/晚响应；scopedLedgerResources |
| battle.audits — battle-report/BattleReports.vue | P，audits，items/total | reportId；实际 page_size 与 size handler 一致 | 已接入真实 report scope 分页；20/50/100 与 handlers 对应；scopedLedgerResources |
| image-admin.invites — customer-image/admin/composables/useCustomerImageAdmin.js | P，invites，items/total | 独立分页；创建后一次性 invite URL 不因读失败丢失 | 已接入真实分页/首错与 stale 重试；create 后读错保一次性 URL；imageWhatsappListAdoption |
| image-admin.generations — useCustomerImageAdmin.js | P，generations，items/total | 独立分页；与产品/邀请使用不同读取状态 | 已接入独立真实分页/快照/当前 metadata；imageWhatsappListAdoption |
| stock.public-inventory — stock/PublicInventory.vue | P，真实items/total服务器分页 | 公开客户英语品牌；原生English Search/Reset/error/retry，20/50/100 | 已接入共享控制器；stockListAdoption；外部文案例外 |

## 4. 完整、限量与管理集合

| 资源 ID / 页面或控制器 | 类型 / API 与真实边界 | 查询、作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| production.routes — production/ProcessRouteManage.vue | B，getProcessRoutes 首200 items | route 编辑步骤/dirty/选中 route 保留；不能读失败清用户编辑 | 已接入首200路线资源；详情组合/工序独立资源见第6节；productionRouteResources、manualListAdoption |
| insight.cases — insight/composables/useCaseLibrary.js | P，listCases，items/total；原首60 | q/tag/sort；detail 独立 async | 已接入真实分页与独立详情；insightGovernanceAdoption 15/15，删除末页与写成功读失败覆盖 |
| insight.ai-tools — insight/AIToolsView.vue | B，listReports(ai_tools) 首30 + getReport 聚合 | 工具展示集合；本地搜索提交 | 已接入聚合资源及本地草稿/已应用；首30条明确限量；单详情失败保成功目录；专项回归通过 |
| insight.industry-daily — IndustryDailyView.vue | B，listReports(industry_daily) 首200 | HTML detail 独立；selectedId 当前范围 | 已接入列表/HTML独立资源；首200条边界；同ID失败保正文、换ID清旧；实际refreshAll回归通过 |
| insight.internal-reports — InternalReportsView.vue | B，三 report types join 查询合计首200 | total 存在；HTML detail | 已接入列表/HTML独立资源；首200条边界；同ID失败保正文、换ID清旧；实际refreshAll回归通过 |
| insight.minutes — MeetingMinutesView.vue | B，listMinutes 首50 | upload/task updates 触发刷新；detail 独立 | 已接入集合/详情独立资源；首50条边界；旧详情晚回保护；专项回归通过 |
| whatsapp.conversations — system/WhatsAppConnector.vue | B，account+page1/size50 | 切 account/选中 conversation；messages 另读 | 已接入 account scope 独立资源；明示前50及 total；切账号清/取消；imageWhatsappListAdoption |
| whatsapp.messages — WhatsAppConnector.vue | B，account+conversation/page1/size50 | 消息历史语义 | 已接入 account+conversation 独立资源；明示最近50，保持 DESC/反转显示；imageWhatsappListAdoption |
| operations.job-runs — system/composables/useOperationsCenter.js | B，status+limit30 | 已有 seq/polling；运行列表 | 已接入独立限量资源与 submitted status；30秒 quiet polling/停用取消；remainingCollectionResources、operationsLifecycle |
| agent.events — agent-runtime/AgentRunDetail.vue | C，runId/after_seq0/limit500 | runId/after_sequence/limit500；ASC 序列可继续读取 | 已接入 useCursorResource；after_sequence 起0、每块最多500，满块可继续；失败保历史/同游标重试；cursorCollectionResources |
| salary.imports.insurance — salary/composables/useSalaryWorkbench.js | S，insurance limit500 | private period/import 范围 | 已接入独立摘要资源；请求最多500行，UI只消费完整SQL聚合总数/金额；不声明items全量 |
| salary.imports.fund — useSalaryWorkbench.js | S，fund limit500 | private period/import 范围 | 已接入独立摘要资源；和社保独立失败；只呈现完整SQL聚合摘要；实际回归通过 |
| assets.favorite-folders — asset/AssetFavorites.vue | F，getFavoriteFolders | folder 导航是资源范围 | 已接入独立完整数组资源；actor/scope清旧，选中folder仅当前数据恢复；worker实际回归通过 |
| assets.favorite-items — AssetFavorites.vue | F，getFavoriteItems(folderId) | 选 folder -> 清旧 items；用户操作 | 已接入folder scope资源；换folder清旧/同folder失败保行/旧响应拒绝；worker实际回归通过 |
| assets.tag-dimensions — asset/TagDimensionManage.vue | F，getTagDimensions(true,scope) | 树/维度结构 | 已接入scope树资源；include_hidden=true、层级、局部标签搜索保留；worker回归通过 |
| expo.wigs — expo/WigLibrary.vue | F，getWigs | full array+local filters | 已接入完整集合/本地已提交keyword及matrix独立scope；实际挂载首错重试通过 |
| expo.hair-colors — expo/HairColorLibrary.vue | F，getHairColors(only_active=0) | 禁用项用于管理 | 已接入完整集合/本地已提交keyword；only_active=0保留；worker回归通过 |
| expo.scripts — expo/ScriptLibrary.vue | F，getScripts | 全量管理集合 | 已接入完整集合/本地已提交type；inactive管理保留；worker回归通过 |
| expo.scene-images — expo/SceneImages.vue | F，getScenes(mode=tryon) | 模式范围/图片展示 | 已接入完整mode=tryon集合；图片分类/上传语义保留；worker回归通过 |
| card.salespersons — card/composables/useCardButler.js | F，fetchSalespersons | 全量分派/销售员集合 | 已接入完整集合/首错/stale/重试；保存成功后读失败保成功；remainingCollectionResources |
| card.entries — useCardButler.js | F，refreshEntries(customerId) | 客户 scope；写卡片入口 | 已接入 customer scope 完整集合；多附件写捕获原客户/表单，旧写不清新草稿；remainingCollectionResources |
| image-admin.products — useCustomerImageAdmin.js | F，loadProducts | 已有 seq；封面 async hydrate | 已接入完整产品集合；actor/role 清旧、封面独立；imageWhatsappListAdoption |
| design.media-accounts — design/CustomerMediaAccounts.vue | F，getPortalAccounts(search) | 客户媒体账号管理；submittedSearch 独立；候选搜索独立 | 已接入账号与候选客户独立资源，已提交搜索与scope；designListAdoption组合40/40通过 |
| design.media-reviews — design/CustomerMediaReview.vue | F，getMediaReviews | 客户媒体审核；actor scope；标签维度/当前客户 tags 独立 | 已接入审核、维度、客户tags独立scope；designListAdoption组合40/40通过 |
| design.designers — design/composables/useDesignManage.js | F，getDesigners，data array | CRUD tab 全量；不是 page resource | 已接入完整设计师集合；designListAdoption组合40/40通过 |
| ai.providers — system/composables/useAiManager.js | F，getProviders -> body.data.items+local filters | Provider 管理，不可用服务仍显示；draft/applied | 已接入完整集合/本地snapshot；false禁用与undefined/null清除已分别回归；aiManagerResources通过 |
| ai.presets — useAiManager.js | F，getPresets -> body.data.items | 默认/配置写入；draft/applied | 已接入完整集合/本地snapshot；首错/stale/current与写成功读失败通过 |
| system.roles — system/RoleManagement.vue | F，getRoleList -> body.data array | 无筛选；权限矩阵是独立详情 | 已接入 useAsyncResource；adminResourceAdoption 首错/重试/stale 通过 |
| system.dict-types — system/DictManagement.vue | F，getDictTypes -> body.data array | navigation/required classification，默认首类型 | 已接入 useAsyncResource；类型失败独立 retry |
| system.dict-items — DictManagement.vue | F，getDictItems(type,false) -> body.data array | 分类切换立即应用、清旧；不能跨类型保成功行 | 已接入 useAsyncResource；late former-type probe 通过 |
| system.integration-apps — IntegrationAppManagement.vue | F，listIntegrationApps -> body.data.items | 本地 keyword/status 已提交；有效/过期/吊销；一次性密钥 | 已接入 useAsyncResource；写成功读失败仍保 secret 的实际 controller 通过 |
| system.mcp-tokens — McpTokenManagement.vue | F，listMcpTokens -> body.data.items | 本地 keyword/status 已提交；知识权限与 membership；一次性 token | 已接入 useAsyncResource；admin 首错/stale +领域契约通过；issue read-failure 另可补覆盖 |
| system.external-bindings — ExternalBindings.vue | F，GET /external-binding-candidates -> body.data array | status 是服务端筛选；绑定/忽略/sync 按更新；不设假分页 | 已接入 useListPage array adapter；submitted status/reset controller 通过 |
| whatsapp.accounts — system/WhatsAppConnector.vue | F，accounts array | account scope driver | 已接入完整账号集合；当前响应 reconcile，actor/role 切换清三资源；imageWhatsappListAdoption |
| report.templates — report/ReportCenter.vue | F，getReportTemplates | 模板资源；原 catch -> empty | 已接入模板完整集合、版本/设计器独立scope；异步startup迟到清理；worker回归通过 |
| insight.sources — insight/SourcesAdminView.vue | F，listSources -> body.data array | CRUD sources；不强制分页 | 已接入完整数组资源；首错/重试/stale/current 实际controller通过 |
| insight.schedule-rules — insight/IntelligenceOverview.vue | F，listScheduleRules -> body.data array | insight:admin；toggle 写后独立刷新；规则状态为 ENABLED_STATUS | 已接入独立完整规则集合；首错/stale/current 与写后读失败；insightGovernanceAdoption |
| aftersales.sop-versions — aftersales/SopManagement.vue | F，fetchVersions items | 发布/归档版本 | 已接入完整版本集合；发布/归档/上传写成功读失败分离；worker回归通过 |
| salary.periods — salary/composables/useSalaryPeriods.js | B，listPeriods(status)，默认最近60 | 薪资期是业务 scope | 已接入限定最近60批次资源，FilterBar草稿/提交；salaryCollectionResources实际回归通过 |
| salary.records — salary/composables/useSalaryRecords.js | B，默认首500，period+keyword -> items/total/totals/truncated | 没有 pager；silent/version；截断应明确呈现 | 已接入独立资源/已提交keyword；truncated提示保留；row_version/null/0和原precision回归通过 |
| salary.attendance — salary/composables/useSalaryWorkbench.js | B，默认首500，period/keyword/only_pending -> items/total/pending/unbound | refreshAll 内写成功后读错误不可混为写失败 | 已接入独立资源/已提交keyword与pending；truncated提示；变化字段/null/0/version核验通过 |
| salary.anomalies — useSalaryWorkbench.js | S，anomalies array | period scope；返回前置/记录级异常聚合对象 | 已接入独立批次聚合对象；当前 scope/首错/stale/重试；保留前置及记录级异常分流；salaryCollectionResources |
| salary.events — useSalaryWorkbench.js | B，events最近200数组 | period scope | 已接入最近200事件资源；明确显示边界；跨批次清旧和晚回保护回归通过 |
| task.tree — task/composables/useTaskCenter.js | F，listTasks tree+stats | 树/本地筛选/任务事件；PM 前端入口另目录 | 已接入完整 treeResource；四字段 draft/applied，本地保祖先；actor scope/晚响应；taskKnowledgeImageListAdoption |
| task.trash — useTaskCenter.js | F，trash | restore/delete 语义 | 已接入完整独立回收站；popover 首错重试/恢复写后独立读；taskKnowledgeImageListAdoption |
| task.modules — useTaskCenter.js | F，modules | 模块管理/导航 | 已接入完整内建与个人分类；首错/stale/重试/actor 清旧；taskKnowledgeImageListAdoption |
| knowledge.libraries — knowledge/KnowledgeWorkbench.vue | F，libraries | 库访问权限 | 已接入完整可访问库；actor/role 清旧、当前 reconcile；taskKnowledgeImageListAdoption |
| knowledge.library-tree — KnowledgeWorkbench.vue | F，library tree | dirty guard；切库不可丢编辑 | 已接入完整树；普通换库遵守 dirty guard，换库清/取消；taskKnowledgeImageListAdoption |
| knowledge.approvals — KnowledgeWorkbench.vue | F，approvals array | 审批权限/状态 | 已接入完整审批队列；先开抽屉、首错可重试；taskKnowledgeImageListAdoption |
| invoice.standard-prices — invoice/InvoicePriceConfig.vue | F，std prices(series_grade) | 等级范围/金额编辑 | 已接入完整数组资源、本地已提交series；选项来自完整集合；价格原值保留；invoicePriceResources通过 |
| invoice.color-types — InvoicePriceConfig.vue | F，color types | 价目配置管理集合 | 已接入独立完整数组资源；首错/重试/stale/current实际回归通过 |
| invoice.price-rules — InvoicePriceConfig.vue | F，rules(keyword) | 全量配置与排序 | 已接入完整数组资源/已提交keyword；候选客户独立current/close保护；金额payload回归通过 |
| invoice.custom-prices — InvoicePriceConfig.vue | B，custom(keyword)首200 items | 最近200符合条件沉淀产品；不是全量报价集合 | 已接入首200资源/已提交keyword；UI限量说明；对账成功后read失败独立；实际回归通过 |
| invoice.accessory-prices — invoice/components/AccessoryPriceConfig.vue | F，createLatestAccessorySearch 返回 rows | 已有 current guard/clearOnError=false | 已接入等价latest/abort/error控制器；草稿快照与首错/stale/retry；SKU/toFixed(2)payload保持；17/17组合通过 |
| announcement.weekly — announcement/AnnouncementWeekly.vue | B，GET /weekly 最近52版本 | 周范围；生成成功后的 load 失败原会阻断成功反馈 | 已接入最新52版本资源/明确限量；排队成功后读失败保成功；remainingCollectionResources |
| announcement.categories — announcement/AnnouncementSettings.vue | F，GET /categories 完整数组 | 分类管理；和 config/members 独立 | 已接入完整独立资源；remainingCollectionResources |
| announcement.members — announcement/AnnouncementSettings.vue | F，GET /members 完整数组 | 整体 replace 写前必须可靠读成功 | 已接入独立资源；未加载/错误禁写，写成功读失败分离；remainingCollectionResources |
| announcement.deliveries — AnnouncementSettings.vue | B，deliveries最近200记录 | 投递记录 | 已接入最新200投递资源/明确限量；首错/stale/重试；remainingCollectionResources |
| hub.conversations — customer_hub/workspace/WorkspaceConversations.vue | P，conversations(customerId) items/total | customer scope；pending bindings 全局独立 | 已接入 customer scope 独立分页；20/50/100，换客户清/取消；cursorCollectionResources |
| hub.pending-bindings — WorkspaceConversations.vue | P，pendingBindings items/total | 全局绑定候选 | 已接入全局独立分页；不伪造 customer filter，写后读失败分离；cursorCollectionResources |
| image.reference-library — design/image-studio/components/ReferenceLibraryDialog.vue | F，fetchItems(scope)+URL hydrate | 引用多选/素材范围 | 已接入 public/private 完整集合；scope 清选择/URL、同scope stale；taskKnowledgeImageListAdoption |
| image.prompt-templates — PromptTemplateManagerDialog.vue | F，includeInactive templates | 管理必须含 inactive | 已接入完整模板管理集合；includeInactive draft/applied、reset=true；taskKnowledgeImageListAdoption |
| image.prompt-library — PromptLibraryDialog.vue | F，templates+local filters | 选择/编辑 prompt | 已接入 active 完整模板；专业分类即时选择，当前 reconcile；taskKnowledgeImageListAdoption |

## 5. 游标与最近会话

| 资源 ID / 页面或控制器 | 类型 / API 与真实边界 | 查询、作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| hub.messages — customer_hub/workspace/WorkspaceConversations.vue/loadMoreMessages | C，conversationId/cursor/limit20 -> messages/next_cursor/has_more | 保持 prepend/append 和游标；切 conversation 取消旧读取；重试不重复追加 | 已接入游标资源；limit20，成功才追加/去重，失败保 cursor，切会话清/取消；cursorCollectionResources |
| image.sessions — design/image-studio/composables/useImageStudio.js | C，listSessions(cursor)，合并+load lock | 保留已成功会话；首错与加载更多错分开；scope/取消；去重 | 已接入游标 session 资源；默认块20、load lock/去重/actor 清/取消；imageWhatsappListAdoption |
| chat.sessions — design/ai-chat/composables/useAiChat.js | B，loadSessions(limit30) | 固定最近历史集合；是否更多由接口/产品契约决定 | 已接入最近30独立资源；明示边界/actor 清私人 draft/首错与 stale 重试；imageWhatsappListAdoption |

## 6. 独立辅助、选择、详情与工作流资源

下列读取与主集合分别拥有错误、重试或当前请求范围。完整数组记 F；固定数量候选记 B；聚合对象、详情、组合目录与工作流状态记 S。一个原子配置组合可以包含多个API，但只按一个提交/错误边界计数；同响应的facet、stats与内嵌数组在所属资源行说明，不重复计数。

### 库存、半成品与素材工作流

| 资源 ID / 消费者 | 类型 / 真实读取边界 | 作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| stock.filter-options — stock/StockOverview.vue | S，完整维度对象 | 主分页独立；选项失败可重试 | 已接入；stockListAdoption |
| stock.progress — StockOverview.vue | S，itemId 生产进度 | 换项目清旧；只有真实404允许初始化 | 已接入独立错误/重试；stockListAdoption |
| stock.safety-filter-options — stock/SafetyConfig.vue | S，完整维度对象 | 安全库存分页独立 | 已接入；stockListAdoption |
| stock.safety-progress — SafetyConfig.vue | S，itemId 生产进度 | 换项目清旧；404与network/5xx区分 | 已接入；stockListAdoption |
| stock.safety-ai — SafetyConfig.vue | S，行/页面建议结果 | 原数量公式与当前行/页面所有权 | 已有 sequence/current 隔离；迟到 AI 不覆盖换页；stockListAdoption |
| stock.cart — stock/composables/useProductionCart.js | F，按用户完整购物车 | 失败保购物车；当前结果才 reconcile 选中ID | 已接入；stockListAdoption |
| stock.order-detail — ProductionOrderManage.vue | S，orderId 详情及内嵌items | 先开详情、换单清/取消 | 已接入；stockListAdoption |
| stock.order-progress — ProductionOrderManage.vue | S，itemId 进度/缓存 | 同一活动资源；current才写cache | 已接入；stockListAdoption |
| stock.print-categories — ProductionOrderPrint.vue | F，每行完整categories | 可并发；行身份+AbortController；替换主行取消旧展开 | 已接入等价逐行控制器；stockListAdoption |
| stock.daily-report — stock/DailyReport.vue | S，date/latest 报告对象 | shortage/warning内嵌；原本地SKU排序；404空与network错误区分 | 已接入日期提交/重试；stockListAdoption |
| semifinished.sync-preview — MaterialManage.vue | S，同步预览/examples | 先开抽屉、关闭/换范围拒绝旧回包 | 已接入；stockListAdoption |
| semifinished.mapping-options — MaterialManage.vue | S，材料目录全页聚合 | 合法每页100，聚合完整目录；重试不清映射编辑 | 已接入 current/取消/重试；stockListAdoption |
| semifinished.create-options — OrderManage.vue | S，材料目录全页聚合 | 每页100完整聚合；保数量 | 已接入；stockListAdoption |
| semifinished.order-detail — OrderManage.vue | S，orderId 详情及items | 换单清旧；旧收货成功不刷新新单详情 | 已接入；stockListAdoption |
| stock.production-quote — stock/components/ProductionOrderDialog.vue | S，product/quantity 报价 | debounce/enable/close/version；不改报价解析 | 已接入 retry/current；stockListAdoption |
| stock.semifinished-plan — ProductionOrderDialog.vue | S，product/quantity 半成品计划 | 与quote分别读取；submit读取中禁用 | 已接入 current invalidation；stockListAdoption |
| assets.sidebar — asset/AssetLibrary.vue | F，完整维度/值树 | 专业父子级联即时分类；不提交keyword草稿 | 已接入独立资源；assetExpoListAdoption |
| assets.favorite-chooser — AssetLibrary.vue | F，完整收藏夹 | 先开dialog、首错重试 | 已接入；assetExpoListAdoption |
| assets.preview-ai — AssetLibrary.vue | S，当前preview分析结果 | preview/actor切换失效；旧建议不写新素材 | 已接入 current/错误/重试；assetExpoListAdoption |
| assets.upload-tags — asset/AssetUpload.vue | F，完整tag维度/值 | 当前成功才初始化；读中/错误禁止submit | 已接入；assetExpoListAdoption |
| assets.upload-ai — AssetUpload.vue | S，文件名分析结果 | 文件快照；换文件clear/cancel | 已接入；assetExpoListAdoption |
| assets.folder-validation — asset/composables/useFolderUpload.js | S，匹配/歧义/未匹配验证结果 | reset/close取消；保原resolution字段 | 已接入；assetExpoListAdoption |
| assets.folder-preview — useFolderUpload.js | S，准备上传预览 | 失败重试该步骤，reset前保成功预览 | 已接入；assetExpoListAdoption |
| assets.folder-job — useFolderUpload.js | S，jobId 状态/结果轮询 | 不是追加游标；保原三次失败/reconnect规则，close取消 | 已接入等价 current/取消控制器；assetExpoListAdoption |
| assets.stats — asset/AssetStats.vue | S，统计对象 | 同响应内含top10、14日trend；嵌入集合不另计读资源 | 已接入首错/stale/重试；assetExpoListAdoption |
| expo.wig-matrix — expo/WigLibrary.vue | F，wigId 完整颜色matrix | 换wig/close清旧，dirty/photos/upsert保留 | 已接入；assetExpoListAdoption |
| report.versions — report/ReportCenter.vue | F，report_code完整历史 | code/open/close清/取消 | 已接入；assetExpoListAdoption |
| report.designer-content — ReportCenter.vue | S，report_code内容+外部designer startup | 异步启动后仍核对scope；旧实例dispose | 已接入；assetExpoListAdoption |

### 设计、财务与业务辅助读取

| 资源 ID / 消费者 | 类型 / 真实读取边界 | 作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| design.my-attachments — design/MyRequests.vue | F，当前request完整附件 | request/actor/close清取消 | 已接入独立资源；designListAdoption |
| design.my-audit-logs — MyRequests.vue | F，当前request完整审计日志 | request/actor范围 | 已接入；designListAdoption |
| design.audit-attachment-counts — design/AuditQueue.vue | S，当前页row IDs的附件计数 | 失败保持未知；旧页不覆新页count | 已接入；designListAdoption |
| design.audit-attachments — AuditQueue.vue | F，当前request完整附件 | 换request先清、actor清旧 | 已接入；designListAdoption |
| design.media-customer-options — design/CustomerMediaAccounts.vue | F，后端完整客户搜索数组 | 实际无固定20上限；blank/new/create/actor清取消 | 已接入；designListAdoption |
| design.media-tag-dimensions — design/CustomerMediaReview.vue | F，完整标签维度 | actor scope；和review独立 | 已接入；designListAdoption |
| design.media-customer-tags — CustomerMediaReview.vue | F，当前batch客户完整tags | batch/asset/actor快照，旧write不改新context | 已接入；designListAdoption |
| design.request-detail — design/components/RequestDetailDrawer.vue | S，requestId详情 | open和ID都watch；close清取消 | 已接入；designListAdoption |
| design.request-attachments — RequestDetailDrawer.vue | F，requestId完整附件 | 独立失败/重试/晚回保护 | 已接入；designListAdoption |
| design.request-audit-logs — RequestDetailDrawer.vue | F，requestId完整日志 | 独立失败/重试 | 已接入；designListAdoption |
| design.request-metadata — RequestDetailDrawer.vue | S，shoot/props/客户等级dict+designers组合 | 一次组合资源；close/switch失效 | 已接入；designListAdoption |
| commission.self-detail — commission/SalesCommission.vue | S，选中batch详情 | user/batch作用域，切用户清旧 | 已接入；financialListResources |
| domestic.order-detail — domestic/composables/useDomesticOrders.js | S，orderId详情 | 路由scope/独立详情错误 | 已接入；domesticOrderImprovements / domesticOrderCreateState |
| invoice.festival-summary — invoice/composables/useFestivalOrderDetail.js | S，type/user汇总 | 与festival rows独立，不互相吞成功 | 已接入；scopedLedgerResources |
| invoice.customer-options — invoice/InvoicePriceConfig.vue | B，远程q，默认20/最大50 | query/close current与取消 | 已接入；invoicePriceResources |
| invoice.accessory-candidates — invoice/components/AccessoryPriceConfig.vue | B，活跃product/SKU最多50 | latest search；close/reopen/unmount失效 | 已接入等价控制器；invoiceAccessoryPriceBehavior |
| hub.order-analytics — customer_hub/workspace/WorkspaceOrders.vue | S，customerId分析 | 独立于订单分页；换客户清旧 | 已接入；scopedLedgerResources |
| expo.quota-summary — expo/StoreQuotaDrawer.vue | S，storeId余额/额度 | 余额与records独立失败，旧充值不写新店 | 已接入；scopedLedgerResources |

### 情报、治理、工资与系统权限

| 资源 ID / 消费者 | 类型 / 真实读取边界 | 作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| insight.industry-html — insight/IndustryDailyView.vue | S，reportId HTML文本 | 同ID失败保正文，换ID清旧；不多取data | 已接入；insightGovernanceAdoption调用层回归 |
| insight.internal-html — insight/InternalReportsView.vue | S，reportId HTML文本 | 同IDstale与换IDclear区分 | 已接入；insightGovernanceAdoption |
| insight.minutes-detail — insight/MeetingMinutesView.vue | S，minuteId详情 | 换minute清取消 | 已接入；insightGovernanceAdoption |
| insight.case-detail — insight/composables/useCaseLibrary.js | S，caseId详情 | 与case页独立范围 | 已接入；insightGovernanceAdoption |
| governance.stats — governance/ConceptRegistry.vue | S，完整统计对象 | 失败不阻concept页，不伪造0 | 已接入；insightGovernanceAdoption |
| governance.graph — governance/ConceptGraph.vue | S，nodes/edges聚合 | 专业图布局；状态tooltip按治理字典 | 已接入当前读取/重试；insightGovernanceAdoption |
| orders.options — order_intelligence/composables/useOrderIntelligence.js | S，完整分析选项 | 和业务数据独立；全局query scope | 已接入；orderIntelligenceResources |
| orders.overview — useOrderIntelligence.js | S，概览聚合 | 全局applied快照；分页/刷新不提交draft | 已接入；orderIntelligenceResources |
| orders.countries — useOrderIntelligence.js | S，国家分析聚合 | 专业分类保留；独立首错/retry/current | 已接入；orderIntelligenceResources |
| orders.people — useOrderIntelligence.js | S，人员分析聚合 | 当前响应才写risk_definition等metadata | 已接入；orderIntelligenceResources |
| orders.profiles — useOrderIntelligence.js | S，客群分析聚合 | 换全局范围取消隐藏tab请求 | 已接入；orderIntelligenceResources |
| orders.ai-brief — useOrderIntelligence.js | S，当前brief/job恢复与轮询 | briefVersion+jobId守恢复/生成/晚poll | 已接入等价版本控制；orderIntelligenceResources |
| salary.period-detail — salary/composables/useSalaryWorkbench.js | S，periodId快照 | 可靠loaded/error/version决定写门禁；confirmed只读仍可unlock | 已接入；salaryCollectionResources |
| system.permission-definitions — system/RoleManagement.vue、UserPermissionDrawer.vue | F，完整permission矩阵定义 | 复用定义资源；Role当前row初始化与preview分别守scope | 已接入；permissionMatrix/adminResourceAdoption及实际matrix慢读探针 |
| system.user-permission-preview — system/components/UserPermissionDrawer.vue | S，user snapshot/roles/有效权限组合 | user/open generation；旧用户不覆新选择，close清角色 | 已接入；实际真实matrix慢读/关闭探针 |
| system.integration-user-options — system/IntegrationAppManagement.vue | B，q/limit20候选用户 | 新query/close clear+abort；同q失败stale/独立retry | 已接入；systemCandidateResources |
| system.mcp-user-options — system/McpTokenManagement.vue | B，q/limit20候选用户 | 不冒充完整用户列表；原token权限保留 | 已接入；systemCandidateResources |
| system.binding-user-options — system/ExternalBindings.vue | B，q/limit20候选用户 | query/dialog generation，旧候选不回填 | 已接入；systemCandidateResources |
| operations.overview — system/composables/useOperationsCenter.js | S，scheduler/services/runtime/summary对象 | 首错不造0；与runs独立，quiet轮询与停用取消 | 已接入；remainingCollectionResources/operationsLifecycle |
| announcement.config — announcement/AnnouncementSettings.vue | S，initialized/config对象 | 读错不能等同initialized=false，成员replace读门禁 | 已接入；remainingCollectionResources及实际挂载 |
| announcement.member-candidates — AnnouncementSettings.vue | B，q候选上限20 | latest query/signal/独立retry | 已接入；remainingCollectionResources |

### 任务、知识、图像与会话辅助资源

| 资源 ID / 消费者 | 类型 / 真实读取边界 | 作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| task.stats — task/composables/useTaskCenter.js | S，独立counts | 首错显示—，不擦成功任务树 | 已接入；taskKnowledgeImageListAdoption |
| task.brief — useTaskCenter.js | S，brief/today，原90秒timeout | 独立stale/retry；不造page | 已接入；taskKnowledgeImageListAdoption |
| task.detail — task/components/TaskDetailDrawer.vue | S，taskId详情及children/events/links | 内嵌数组属于同一次read；ID/close清取消/current-only hydrate | 已接入；taskKnowledgeImageListAdoption |
| knowledge.document — knowledge/KnowledgeWorkbench.vue | S，library/doc编辑详情 | 普通切换dirty guard，同docreload不重复discard | 已接入；taskKnowledgeImageListAdoption |
| knowledge.approval-review — knowledge/KnowledgeWorkbench.vue | S，approvalId冻结revision | 独立ID，先开dialog；错误/读中禁审批 | 已接入；taskKnowledgeImageListAdoption |
| knowledge.members — knowledge/components/KnowledgeMemberDialog.vue | F，libraryId完整成员集合 | 未加载/错误/读中禁止replace；保护admin规则 | 已接入；taskKnowledgeImageListAdoption |
| knowledge.member-candidates — KnowledgeMemberDialog.vue | B，libraryId+q，limit20 | new/close clear；同q失败stale，retry已提交q | 已接入；taskKnowledgeImageListAdoption |
| knowledge.search — knowledge/KnowledgeWorkbench.vue | B，q/limit20 | draft/applied+Query/Reset，retry不提交draft | 已接入；taskKnowledgeImageListAdoption |
| knowledge.ai-profiles — knowledge/KnowledgeAiSettings.vue | F，完整profile数组 | actor/role清旧，三资源独立成功/失败 | 已接入；knowledgeAiResources |
| knowledge.ai-preset-options — KnowledgeAiSettings.vue | F，完整可用direct/text preset候选 | 独立error/retry；原配置payload | 已接入；knowledgeAiResources |
| knowledge.ai-library-options — KnowledgeAiSettings.vue | F，完整active库候选 | source/target权限保持，独立retry | 已接入；knowledgeAiResources |
| knowledge.ai-profile-logs — KnowledgeAiSettings.vue | B，profileId最近100 | 先开drawer，profile/close清取消，明示100 | 已接入；knowledgeAiResources |
| knowledge.optimization-profiles — knowledge/components/AiOptimizationDrawer.vue | F，libraryId完整可用profiles | doc/library/open/close/actor清旧，current-only选择 | 已接入；knowledgeAiResources |
| knowledge.optimization-history — AiOptimizationDrawer.vue | B，docId最近30任务 | history首错阻重复create；jobVersion保护恢复，明示30 | 已接入；knowledgeAiResources |
| knowledge.optimization-job — AiOptimizationDrawer.vue | S，jobId详情/poll | scope+jobVersion+ID；失败保job，取消/apply不被旧poll覆写 | 已接入；knowledgeAiResources |
| image.reference-thumbnails — design/image-studio/components/ReferenceLibraryDialog.vue | S，libraryAsset authenticated thumbnail Blob | batch错误/retry；generation/abort；scope/close不创建晚URL | 已接入等价URL控制器；taskKnowledgeImageListAdoption |
| image.pantone-library — design/image-studio/components/PromptLibraryDialog.vue | F，完整pantone色号items | 本地专业即时搜索；只渲染前240并显示真实total，不是server cap | 已接入独立错误/retry/cache；taskKnowledgeImageListAdoption |
| image-admin.product-covers — customer-image/admin/composables/useCustomerImageAdmin.js | S，product+cover版本Blob | 逐行error/retry、signal/version、URL替换撤销 | 已接入；imageWhatsAppListAdoption |
| image-admin.customer-options — useCustomerImageAdmin.js | B，term候选，后端max20 | new/blank/close清取消，同term stale | 已接入；imageWhatsAppListAdoption |
| image-admin.product-assets — customer-image/admin/ProductTemplateEditor.vue | F，productId完整array | reset/open/close scope；写成功read失败分离 | 已接入；imageWhatsAppListAdoption |
| image-admin.library-assets — ProductTemplateEditor.vue | F，public/private完整items | copy dialog独立stale/retry，关闭取消 | 已接入；imageWhatsAppListAdoption |
| image-admin.product-asset-previews — ProductTemplateEditor.vue | S，productId+assetId Blob | versioned current controller/独立retry | 已接入等价Blob控制器；领域Blob回归 |
| image-admin.library-previews — ProductTemplateEditor.vue | S，libraryAsset Blob | batch失败retry，close拒晚URL | 已接入等价Blob控制器；领域Blob回归 |
| chat.mode-catalog — design/ai-chat/composables/useChatModes.js | F，后端固定完整catalog | 专业模式选择；已有catalogError/retry、保items、detail generation | 已有等价控制器；源码/后端catalog核对；未新增mounted并发测试 |
| agent.run — agent-runtime/AgentRunDetail.vue | S，runId详情与内嵌artifacts | route scope清/取消，旧确认/写不刷新新run，unmount阻timer | 已接入；cursorCollectionResources |

### 生产、员工、门店、物流、色号与战报

| 资源 ID / 消费者 | 类型 / 真实读取边界 | 作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| production.route-detail — production/ProcessRouteManage.vue | S，routeId步骤+内贸规则配置组合 | 两API作为原子编辑快照；仅无domestic:admin编辑者规则403可降级；network/5xx阻保存 | 已接入独立retry/ready/current/selectionVersion；productionRouteResources |
| production.route-processes — ProcessRouteManage.vue | F，完整active processes数组 | 与route详情独立失败；可靠读取才可新增工序 | 已接入；productionRouteResources |
| production.product-filter-options — production/ProductManage.vue | S，完整distinct筛选维度 | 独立首错/stale/retry，不吞product分页 | 已接入；productTrackingAuxResources |
| production.product-active-routes — ProductManage.vue | F，完整active routes数组 | 绑定弹窗独立资源；失败禁绑定 | 已接入；productTrackingAuxResources |
| production.product-route-preview — ProductManage.vue | F，所选route完整步骤数组 | product/route/open/close清取消；绑定捕获原product/route/批量IDs | 已接入；productTrackingAuxResources |
| production.dashboard — production/composables/useDashboardData.js | S，raw orders/kpi/process_stats/today_completions聚合 | 直接raw body；60秒quiet刷新/unmount取消；专业Donut/Timeline保留 | 已接入；aggregateResourceBoundaries及真实raw反例复跑 |
| employee.attribute-history — employee/EmployeeAttribute.vue | F，employeeId完整历史数组 | 独立historyEmployee，不与编辑currentRow共scope；close清取消 | 已接入；employeeStoreChildResources/实际挂载retry |
| supervisor.relation-history — supervisor/SupervisorRelation.vue | F，salespersonId完整历史数组 | 独立historyRow；换人/close清取消/晚读隔离 | 已接入；employeeStoreChildResources/实际挂载retry |
| expo.store-users — expo/StoreManagement.vue | F，storeId完整已绑定用户数组 | usersStore独立于quota；旧bind/unbind确认/写不清新表单 | 已接入；employeeStoreChildResources/实际挂载retry |
| expo.store-user-options — StoreManagement.vue | B，keyword/page1/size20 | 候选搜索属于用户抽屉scope；换店/close取消 | 已接入；employeeStoreChildResources |
| tracking.stats — tracking/TrackingList.vue | S，current_user data_scope全量聚合 | stats+updatedAt仅current提交，auth/roles/perms变化清旧 | 已接入；productTrackingAuxResources/实际挂载retry |
| color.palette-filter-options — color/PaletteView.vue | S，完整维度对象body.data | 独立当前读取/首错/stale/retry | 已接入；colorOptionResources |
| color.blend-filter-options — color/BlendView.vue | S，完整维度对象body.data | 和palette/catalog分别settle | 已接入；colorOptionResources |
| color.blend-palette-options — BlendView.vue | S，完整色号选择目录 | 真实P合法每页200聚合，Map去重；缺页/unique少于total抛错，不显示partial | 已接入；colorOptionResources及401=200/200/1与重复页探针 |
| color.swatch-color-options — color/SwatchGenerator.vue | S，同完整色号聚合目录 | 同signal，全页完整才提交；初错不判空 | 已接入；colorOptionResources |
| battle.selector — battle-report/BattleReports.vue | F，archived范围完整report目录 | scopeVersion防慢目录重选旧report；换archive清旧 | 已接入；aggregateResourceBoundaries真实caller回归 |
| battle.detail — BattleReports.vue | S，reportId详情 | 和overview独立settle；切report清/取消 | 已接入；aggregateResourceBoundaries |
| battle.overview — BattleReports.vue | S，reportId+team聚合 | 专业即时team分类/矩阵布局保留 | 已接入；aggregateResourceBoundaries |
| battle.participants — battle-report/components/ReportSettings.vue | F，完整有效外部绑定候选 | 原名单缺候选补入；open/report清取消/读门禁；旧POST不关新dialog | 已接入；aggregateResourceBoundaries A→B→A/迟到write回归 |
| aftersales.summary — aftersales/AfterSalesAnalytics.vue | S，body.data聚合；product/batch各top20 | 专业bar/rank/trend；首错/stale/retry，不造page | 已接入；aggregateResourceBoundaries |

### MainDashboard 独立摘要与最近记录

| 资源 ID / 消费者 | 类型 / 真实读取边界 | 作用域与业务约束 | 当前实现 / 实际证据 |
| --- | --- | --- | --- |
| dashboard.customer-work — dashboard/composables/useDashboardData.js | S，SQL total+最早5个action | todo提示前5；按现有customer权限 | 已接入独立key/customerWork；dashboardResources |
| dashboard.incomplete — useDashboardData.js | S，snapshot is_complete=false page1/size1 | UI消费server total，不称列表全量 | 已接入独立key/incomplete；dashboardResources |
| dashboard.commission-count — useDashboardData.js | S，commission page1/size1 | total+最新row，commission权限 | 已接入独立key/batches；dashboardResources |
| dashboard.recent-commissions — useDashboardData.js | B，commission page1/size5，最多展示3 | 保最近活动优先级与导航 | 已接入独立key/recentCommissions；dashboardResources |
| dashboard.employee-count — useDashboardData.js | S，employee page1/size1 | 只用server total，employee权限 | 已接入独立key/employees；dashboardResources |
| dashboard.tracking-count — useDashboardData.js | S，shipments page1/size1 | 只用server total，tracking权限 | 已接入独立key/trackingCount；dashboardResources |
| dashboard.tracking-stats — useDashboardData.js | S，tracking完整聚合 | 异常count/alert/donut | 已接入独立key/trackingStats；dashboardResources |
| dashboard.recent-trackings — useDashboardData.js | B，shipments page1/size5，最多展示3 | 保最近活动优先级 | 已接入独立key/recentTrackings；dashboardResources |
| dashboard.recent-shipments — useDashboardData.js | B，active/updated desc page1/size5 | 物流卡明确最近5条 | 已接入独立key/recentShipments；dashboardResources |
| dashboard.design-task-count — useDashboardData.js | S，design tasks page1/size1 | 用server total，原指标业务含义保留 | 已接入独立key/designTasks；dashboardResources |
| dashboard.approval-count — useDashboardData.js | S，pending_audit requests page1/size1 | 用server total，design:audit权限 | 已接入独立key/approvals；dashboardResources |
| dashboard.design-stats — useDashboardData.js | S，当前北京时间月份完整aggregate | tracking无distribution时donut fallback | 已接入独立key/designStats；dashboardResources |
| dashboard.recent-designs — useDashboardData.js | B，requests page1/size5，最多展示3 | 原identity scope | 已接入独立key/recentDesigns；dashboardResources |
| dashboard.latest-payment — useDashboardData.js | S，北京时间过去30天page1/size1 | 最新支付metric；原payment权限 | 已接入独立key/latestPayment；dashboardResources |
| dashboard.recent-payments — useDashboardData.js | B，同30天page1/size5，最多展示3 | 原活动导航与优先级 | 已接入独立key/recentPayments；dashboardResources |

## 7. 专业交互与范围边界（10类）

| 类别 | 保留的业务方式 / 验收边界 |
| --- | --- |
| 1. 任务与知识层级 | 完整树、祖先保留、分类导航和dirty guard；不转平面分页。远端树/详情/成员/审批已经分别列资源。 |
| 2. 素材与维度导航 | sidebar父子级联、分组/局部搜索是即时专业分类；顶层keyword仍草稿/提交。facet属于同一页响应。 |
| 3. 图、分析、看板与排程 | ConceptGraph、OrderIntelligence、售后/生产/MainDashboard及Gantt等保专业图/矩阵/时间线；已识别独立读取列S，不能由普通列表的分页测试证明其全部业务和几何。 |
| 4. 战报/设计专业工作区 | ReportDaily矩阵、目标、海报和设计容量/日历/生成表单保专业布局；普通order-review页与战报选择/详情/总览/participants分别登记。其余专业写入流程不由本账本资源计数证明。 |
| 5. Pantone与远程候选 | Pantone为完整读取、本地即时选择及前240渲染，展示真实total；用户/成员/客户/SKU候选保20/50等实际限量，不增加假分页。 |
| 6. 本地可编辑行 | Invoice HairTable/AccessoryTable、上传队列、已选素材与编辑items来自表单状态；不计远端资源。金额/数量原值、增删行与payload验证保留。 |
| 7. 上传与任务工作流 | validation/preview/job状态保匹配与reconnect规则；S状态轮询不同于C追加历史，不以出现limit就强套page。优化生成/费用/idempotency业务不改。 |
| 8. 文件与URL | authenticated Blob、缩略图、封面、下载和附件保signal/current/version/URL撤销；逐类资源记账，未逐个文件访问生产。 |
| 9. 外部品牌与独立入口 | PublicInventory真实分页已迁移且单列；英语品牌、customer-image portal、expo kiosk及frontend-pm使用各自文案/控件/规范，不能用本页主站计数声明其全流程验收。 |
| 10. 外部报表运行时 | ReportCenter异步designer启动有scope/dispose保护；Stimulsoft真实打印、文件上传下载和运行时集成不由fixture挂载或SFC compile证明。 |

上述10类是文档中的业务边界分组；其中资源已经按P/F/B/C/S计入表格。没有把例外类别数量累加到277个语义资源中。静态规则的19个路径/精确button count以[ui_component_exceptions.json](../../scripts/ui_component_exceptions.json)与门禁源码为准。

## 8. 实际证据与完成边界

以下是本轮已经执行的专项证据。各组合有重叠，**不相加作为唯一测试总数**。测试使用当前真实SFC/composable/API adapter及共享控制器，确定性fixture模拟错误与晚响应；挂载测试用Vue renderer与组件slot协议壳，不能替代全部Element Plus浏览器E2E或真实后端写入。

| 资源分组 | 持久回归与实际执行证据 |
| --- | --- |
| 首阶段/财务/原有桥接 | [listPagePilots](../../frontend/tests/listPagePilots.test.mjs)、[financialListResources](../../frontend/tests/financialListResources.test.mjs)、[listAdoption](../../frontend/tests/listAdoption.test.mjs)。原有adoption专项36项、领域18项及组合108项；实际snapshot/CRUD/首错/stale/mounted检查。 |
| 库存/半成品 | [stockListAdoption](../../frontend/tests/stockListAdoption.test.mjs)：26项专项，组合72/72；10个SFC编译。实际材料全目录聚合、ledger分页、404-only进度初始化、逐行categories/quote/current回归。 |
| 设计 | [designListAdoption](../../frontend/tests/designListAdoption.test.mjs)：19项专项、组合40/40，6个SFC编译；主页与attachments/counts/metadata/actor独立scope。 |
| 素材/Expo/Report/SOP | [assetExpoListAdoption](../../frontend/tests/assetExpoListAdoption.test.mjs)：23项专项、组合36/36，12个SFC编译；Wig真实挂载首错/重试、facet当前所有权与designer晚启动dispose。 |
| 主站task/Knowledge/图像库 | [taskKnowledgeImageListAdoption](../../frontend/tests/taskKnowledgeImageListAdoption.test.mjs)：19项专项、组合104/104，10个SFC编译；tree/dirty/frozen review/members/URL/scope与实际popover/dialog retry。 |
| Image/admin/Chat/WhatsApp | [imageWhatsAppListAdoption](../../frontend/tests/imageWhatsAppListAdoption.test.mjs)：15项专项、组合119/119，11个SFC编译；游标/最近30/前50/最近50/Blob/一次性URL。chat.mode-catalog仅核对已有专用状态与后端固定catalog，不声称新增mounted并发覆盖。 |
| Knowledge AI补漏 | [knowledgeAiResources](../../frontend/tests/knowledgeAiResources.test.mjs)：12项新回归、组合52/52，2个SFC编译；日志100/history30/当前job、首错禁重复create、scope/close/poll/apply/cancel与配置写成功读失败。 |
| 管理与情报/治理 | [adminResourceAdoption](../../frontend/tests/adminResourceAdoption.test.mjs)、[insightGovernanceAdoption](../../frontend/tests/insightGovernanceAdoption.test.mjs)、[aiManagerResources](../../frontend/tests/aiManagerResources.test.mjs)、[systemCandidateResources](../../frontend/tests/systemCandidateResources.test.mjs)。21/21管理组合、26/26情报/AI/permission组合及3项候选；另有真实permission matrix旧role/user慢读探针。 |
| 工资/价格/Card/公告/Operations | [salaryCollectionResources](../../frontend/tests/salaryCollectionResources.test.mjs)：9项专项、组合14/14；[invoicePriceResources](../../frontend/tests/invoicePriceResources.test.mjs)/配件精度组合17/17；[remainingCollectionResources](../../frontend/tests/remainingCollectionResources.test.mjs)/operations/announcement/price组合27/27。实际跨批次零write、0/null/version原payload、成员replace门禁、多附件客户快照、quiet/停用取消及三个页面挂载。 |
| 客户订单/额度/台账/游标/色号/聚合 | [scopedLedgerResources](../../frontend/tests/scopedLedgerResources.test.mjs)、[orderIntelligenceResources](../../frontend/tests/orderIntelligenceResources.test.mjs)6项、[cursorCollectionResources](../../frontend/tests/cursorCollectionResources.test.mjs)、[colorOptionResources](../../frontend/tests/colorOptionResources.test.mjs)、[aggregateResourceBoundaries](../../frontend/tests/aggregateResourceBoundaries.test.mjs)最终6/6。真实接口信封、序列500→501/失败重试、色号401全页与重复缺项抛错、Production raw body反例已重跑通过。 |
| 路线详情与漏项子集合 | [productionRouteResources](../../frontend/tests/productionRouteResources.test.mjs)10项/组合28/28；[employeeStoreChildResources](../../frontend/tests/employeeStoreChildResources.test.mjs)21项（含实际API）；[productTrackingAuxResources](../../frontend/tests/productTrackingAuxResources.test.mjs)15项；与主列表组合91/91。路线/员工/主管/门店/Product/Tracking实际挂载首错及独立retry，API signal/信封探针、scope晚读/迟到write。 |
| MainDashboard | [dashboardResources](../../frontend/tests/dashboardResources.test.mjs)最终5/5，`TZ=America/Los_Angeles`；15个独立key，首错不造0、同scope保成功、账号/权限清旧、物流卡挂载及北京时间月/30日边界。 |

先前审查确认的clearable Provider、同ID HTML刷新、mutation重复反馈、Graph英文tooltip、候选晚回、路线/员工/主管/门店/Product/Tracking范围、生产raw body、战报目录重选与settings旧write问题已修复，并有对应实际反例或回归重跑。历史发现记录不能继续作为当前待实施项，也不能用“未发现问题”代替验证。

最终统一结果：1185项Node测试中1179通过；6项未改动loginMapMotion在隔离HEAD同样因`ctx.save` mock缺失失败，已保留复现证据。frontend build、严格约定检查、UI audit及diff check通过；Git巡检为`--no-fetch`本地快照。这些最终结果以DESIGN/handoff为执行记录，不声称全部测试通过。

浏览器样例只证明实际走过的样例及viewport/overlay修复；未执行生产数据库业务写入、真实外部消息/报表/AI费用或部署。当前账本已知待实施项为0；上述浏览器/生产边界是证据范围，不隐藏成“全站E2E全通过”。
