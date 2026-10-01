# 订单洞察独立复核

日期：2026-10-02。目录：`C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`。只读审查 `useOrderIntelligence.js`、`OrderFilters.vue`、`OrderIntelligence.vue`、API/后端及共享 cancel/clear；未改源码、测试、其他代理改动，未访问生产。

## 结论

新分析资源的真实响应适配、已提交筛选、分页、元数据、旧响应保护与概览失败后的明细入口验证通过。新共享 `cancel` / `clear` 未发现破坏现有控制器行为。另实际复现一项已有 AI 简报竞态；主代理随后补 briefVersion，独立新回归6/6通过，已证实初始慢恢复不会覆盖新生成结果。本评审未修改源码。

`loginMapMotion` 当前6失败在 HEAD 隔离基线同样全部失败且相同原因，属于已有测试/Canvas fixture 不匹配。

## 真实接口与适配

| 资源 | 后端形态与业务语义 | 当前调用证据 |
| --- | --- | --- |
| filters/options | `order_intelligence/router.py` /filters -> `ok(get_filter_options(...))`，对象含 can_read_all/teams/users/country_tree/models/colors/source_categories | API 仅解 body.data 一层；loadFilters 使用已提交 date_from/to，选人列表按草稿 team 收窄但不自动提交分析 |
| overview | /overview -> ok(object)，汇总、月趋势、口径、质量等 | 独立 async；失败不阻断 options 或 active detail |
| countries | /countries -> ok({items,total,score_definition}) | 独立 async；不是虚构服务器分页；同资源失败保成功集合 |
| people | /people，dimension=user/team -> ok({items,total,evaluation_note,...}) | dimension 切换 clear 取消旧读；新 dimension 明确应用；旧个人响应不能覆盖团队 |
| profiles | /customer-profiles -> ok({items,total,summary,definitions,...}) | 独立 async，当前提交、首错/stale/retry |
| customer actions | /customers 接收 date_from/as_of、risk_status/country、真实 page/page_size<=100、team/user 与全局数组 -> ok({items,total,page,page_size,risk_definition}) | useListPage，risk_definition 只 isCurrent 写入；日期到 as_of；page size20/50/100；全局提交清旧集合并取消旧请求 |
| AI brief | /ai-brief POST202 -> ok(job)；active/latest/status -> ok(job or null) | generate payload 只使用 baseParams 的 appliedFilters，不把尚未提交的日期/产品/国家草稿带入；任务恢复竞态另列 |

实际运行当前 API adapter（非源码字符串检查）以真实 body envelope `{code:200,data:{items,total}}` 喂四个明细入口；四者返回解析后数据，保持相同 signal、suppressToast 与 paramsSerializer。Axios 实际序列化得到 `/countries?countries=DE&countries=FR&models=A&page=2`，与 FastAPI 的重复键 `list[str]` 参数契约匹配。

## 自动执行结果

1. `node --test tests/orderIntelligenceResources.test.mjs tests/orderIntelligenceFilters.test.mjs tests/useListPage.test.mjs tests/listPageComponents.test.mjs`：**26/26 通过**，退出0。
   - resources 五个行为用例真实执行当前 composable/shared controller：明确 clear 取消旧集合；客户已提交全局+本地筛选；AI 已提交上下文；三聚合 latest/stale；隐藏旧全局 scope 的请求取消；overview/options 独立失败/current choices。
   - Filters 八个用例主要是现有结构/契约检查，不把它们算成浏览器动作。
   - core 十个与组件三个用例包含 reset/sort、first/stale、删除末页、写成功读失败、FilterBar 交互、status retry、unmount abort。
2. 因 cancel 被加入共享 scope helper，额外执行 `listAdoption + stockListAdoption + orderIntelligenceResources`：**67/67 通过**，退出0。覆盖真实桥接/外部 scope、目录/工作台、mail/evidence、库存/半成品详情/ledger/cart/print/categories 的已应用查询、过期取消与挂载首错重试，未发现新 core 破坏。
3. 额外 caller 探针：people 的 user 请求慢读，切 dimension=team 后 team 成功，再返回旧 user，最终仍显示 Team，实际通过。

## 实际 Vue 挂载与 native 事件

编译并挂载当前 `OrderIntelligence.vue`、`OrderFilters.vue`、`FilterBar.vue`、`ListPageStatus.vue`、`GlassButton.vue`，执行真实 `useOrderIntelligence`/useListPage/useAsyncResource；fixture API 有受控错误，未用生产数据。

- 初次 overview 抛 `overview offline`；等待 mounted 请求结束后，概览错误可见，五个 tab 都仍挂载。
- 实际 native button click 触发 page 的 tab-change/activeTab，切国家后 getCountryAnalysis 被调用1次；国家首错 `countries offline` 在实际表格 #empty 的 ListPageStatus 中显示“重试加载”。
- 点击实际 GlassButton 渲染的 native retry；国家读取第2次成功返回 `{items:[],total:0}`，页面显示“暂无分析结果”，不再显示国家错误，overview 错误仍独立存在。

挂载边界：使用项目 custom renderer，无浏览器 DOM；ElementPlus ElAlert 使用实际组件，ElTabs/ElTabPane 与 ElTable 使用 Vue 事件/slot 协议 adapter，charts/表单输入/DetailDrawer 等无关叶组件使用 slot shell。真实 ElTabs 尝试因 ordered-children 需要 `vnode.el.parentNode` 而与该 host 不兼容，不把协议 adapter 结果声称为真实浏览器样式、键盘导航或 loading mask 验证。该验证确实运行真实 page template 与 native retry/tab click，没有仅断言源码存在函数。

## 共享新 clear / cancel 审查

- useListPage.cancel 增加 request sequence、abort 当前 signal、停止 loading；旧 success/error/finally 全受 isCurrent 保护。保留数据与 error 是 cancel 本身的语义，clearListResource 随后明确清 rows/total/page/dataPage/hasLoaded/error。
- scope watcher flush=sync 在新 applied snapshot 后先 clear/cancel，随后 fetch 发新 sequence；当前真实调用方传 useListPage 完整对象，新增 cancel 可用。67项实际 suite 没出现 wrapper 缺 cancel 或 metadata 晚写。
- useAsyncResource.clear 增加 sequence/abort 并恢复 initialData、清 error/loading/hasLoaded。隐藏聚合全局提交时使用 clear；再次切 tab 会传最新 baseParams，保留 lastParams 不导致旧 scope 重试。
- clear 不是副作用隔离器；loader 内额外写仍须 context.isCurrent。customerMeta 当前已保护，晚 risk_definition Probe 与隐藏读取 suite 通过。

## 已有 AI 简报恢复竞态（已修复复验）

实际当前 composable mounted 流程探针：`getActiveOrderAiBrief` 延迟；用户 `generateBrief` 已完成 `new-job/new generated result`；随后初始 active 读回 `old-job/old restored result`。最终 aiBrief.job_id 被覆盖成 old-job，用户的新结果/任务跟踪丢失。

这不是全局筛选草稿泄漏，也不是新 read resource 的竞态：generate 确实使用已提交上下文。主代理修复为 briefVersion：restore/generate 递增并检查版本，poll 同时检查版本与当前 jobId，卸载递增取消晚提交。独立重跑 `orderIntelligenceResources.test.mjs` **6/6 通过**，包含新增 slow restored AI brief regression；与前述26/26和67/67是不同执行快照，不累加为一次总通过。此评审没有修改生产代码。

## loginMapMotion HEAD 隔离基线

HEAD：`80f973f48b271bdde175a04623b273582e76e8a4`。

用 `git show HEAD:frontend/<path>` 原样提取三文件到 `frontend/tmp/order-intelligence-head-baseline/`，保持相对目录，仅包含：

- `tests/loginMapMotion.test.mjs`
- `src/components/WorldMapCanvas.vue`
- `src/assets/world-land.json`

执行当前 `node --test tests/loginMapMotion.test.mjs` 和隔离 `node --test tmp/order-intelligence-head-baseline/tests/loginMapMotion.test.mjs`，两次都 **0通过/6失败、退出1**；六项同为 `TypeError: ctx.save is not a function`，在 drawMap/resize/mountMap 进入。当前 test fixture 缺 Canvas save API，HEAD 原测试同样缺。

三个原路径 git status 无变化；当前文件与 HEAD 提取文件经 CRLF->LF 规范化后逐项文本完全相等。原始字节因仓库 checkout 行尾转换不同，不声称字节相同。没有修改、替换或修补基线源码来获得通过。

隔离目录保留为必要复现证据，主代理可在最终报告摘录后按任务清理规则处理。
