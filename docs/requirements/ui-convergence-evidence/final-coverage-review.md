# Final resource coverage review

> 主代理收尾注：本报告第1–4节是发现时快照，后续KnowledgeAI修复见第5节。Color选项、员工/主管历史、门店人员与候选、产品辅助/运单统计、售后聚合、生产看板及主仪表盘的已知缺项亦已分别完成并有专项回归；当前完成与限量状态以 `../2026-10-02-list-resource-coverage.md` 和最终验收为准，不将早期“未完成”文字视为当前状态。原审阅证据保留。

审阅时间：2026-10-02。工作树：C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system。

## 结论与证据范围

最新台账中的 task/knowledge/image/admin/chat/WhatsApp 相关 pending 行主要是未同步交付证据，下面给出可逐行替换的状态；主集合之外的成员、冻结审批、候选、缩略图与副集合也单列。两份报告及最终stdout已重新读取，当前源码共享控制器、status位置、scope clear和真实backend上限也只读核对。

首次只读审阅阶段只写此报告与fixture探针stdout，没有修改资源台账或生产代码；随后新增授权的Knowledge AI修复见第5节。未重复 ProductionRoute、既有三个用户候选、会话详情、Agent详情审查。先前组合测试104/104、119/119与SFC编译是已实际执行的专项结果；本次没有重复全站gate、浏览器或真实后端业务操作，不把计数当完成证明。

## 1. 台账现有 pending 行的准确更新

| 台账资源ID | 实际类型/边界 | 准确新状态与证据 |
| --- | --- | --- |
| task.tree | F 完整嵌套任务树 | 已接入treeResource；keyword/module/priority/hideClosed四字段draft/applied+成对FilterBar，本地祖先保留；同scope失败保树，actor变化clear/abort；真实controller层级/草稿/晚响应回归 |
| task.trash | F 完整回收站 | 独立trashResource与popover首次失败/重试；restore后tree/trash分别读、读失败不误报恢复失败；成功空才判空 |
| task.modules | F 内建+个人分类 | 独立modulesResource；分类导航保持本地层级，分类增删读取失败可retry，actor清旧分类 |
| knowledge.libraries | F 权限过滤的完整可访问库 | librariesResource首次/stale/retry；库移除后reconcile tree/document，强制actor/权限变化清旧库；非ordinary导航不绕过原dirty guard |
| knowledge.library-tree | F 完整folder/document数组 | treeResource保parent_id/nestedTree；普通换库先dirty确认，确认后clear/abort；晚旧库响应不能覆盖，dirty取消fixture |
| knowledge.approvals | F 完整可访问审批队列 | approvalsResource独立；先打开drawer再读，首次错误可retry，实际mounted queue点击重试回归；不能代表冻结revision详情完成，另见第2节 |
| image.reference-library | F public/private完整items | 独立listResource，换scope先清items/selection/URL；同scope失败stale，旧scope上传完成不prepend当前；缩略图独立资源见第2节 |
| image.prompt-templates | F includeInactive完整模板管理集合 | worker名image.prompt-template-manager，指同一资源；listResource+draft/applied inactive开关，成对查询重置；reset=true保禁用管理；save成功read失败不误报；actualmounted及controller |
| image.prompt-library | F active完整模板 | 独立listResource；分类chip为即时专业导航例外；读成功才按最新metadata/category恢复选择；关闭/actor clear；Pantone另资源 |
| image.sessions | C items/next_cursor，backend默认batch20 | useImageSessionList+asyncResource，追加ID去重/current merge、加载锁、失败保成功历史、精确cursor retry；actor清scope/cancel；实际初错/追加错/重复key/旧actor晚回/创建晚回回归 |
| chat.sessions | B 最近30，即使backend支持cursor | 独立async资源，exact limit30、首次/stale/retry；sidebar明确最多30条；actor清历史与内存draft并abort；mounted初错retry/stale行可见 |
| image-admin.products | F 完整产品array | productsResource独立，read错误保成功产品；actor clear；写成功后read失败不改写结论；封面另资源不能随产品表自动计完成 |
| image-admin.invites | P items/total，default20，20/50/100 | useListPage；page/size重试与dataPage正确；create回page1，后续read失败保一次plaintext URL；revoke保持原位update并cancel早先列表读，防旧read擦掉成功撤销；实际controller |
| image-admin.generations | P items/total，default20，20/50/100 | 独立useListPage；首次/stale/retry，与product/invite失败互不覆盖；真实page/size fixture及既有领域回归 |
| whatsapp.accounts | F 完整账号array | accountsResource独立初错/stale/retry；当前结果reconcile选中账号，移除时清子集合；auth/role强制变化clear全部资源 |
| whatsapp.conversations | B account+page1/size50 | 独立async/current total；account变化先清conversation/messages，失败新scope不露旧账号；明确前50+total，不称全量；exact retry/晚响应fixtures |
| whatsapp.messages | B account+conversation+page1/size50，最新50 | 独立async/current total；换thread先clear；同thread失败保成功消息；backendDESC+原display reverse保持；明确最新50+total；exact query/晚旧thread回归 |

对应专项证据：frontend/tmp/task-knowledge-image-list-adoption-worker.md、task-knowledge-image-final-test-output.txt（104/104，19新增真实controller/API/URL/mounted）；frontend/tmp/image-whatsapp-list-adoption-worker.md、image-whatsapp-final-tests.txt（119/119，15新增真实controller/API/mounted）。两批分别10/11个SFC compileScript+compileTemplate 0错误。source/API实际optional configs带signal/suppressToast，默认协议未变；只有真实分页资源接useListPage。

## 2. 主表之外必须补入台账的已完成资源

这些是已实施的资源，不只是泛称附件/详情例外；类型按主台账P/F/B/C/S映射，worker报告的D blob统一记S。

| 建议独立ID | 实际类型/边界 | 状态/具体保护/已验证证据 |
| --- | --- | --- |
| task.stats | S GET stats独立counts | statsResource，失败不吞树，初错统计显示em dash；独立失败fixture |
| task.brief | S GET brief/today，原90s timeout | briefResource独立stale/retry；摘要不制造page；read API保timeout |
| task.detail.children/events/links | S GET items/:id包含三个related arrays | detailResource按taskId，switch/close clear+abort，先开drawer，current-only表单hydrate；真实ID晚响应fixture |
| knowledge.document | S 当前editor详情 | documentResource按library+doc；普通切换dirty确认，内置同docreload不重复discard；编辑/保存机制不改 |
| knowledge.approval-review | S GET approvals/:id冻结revision | reviewResource独立ID，先开dialog；旧revision晚响应拒绝，失败/loading不能审批；实际fixture |
| knowledge.members | F 指定library完整editable成员 | membersResource独立初错/重试/close abort，unloaded/loading/error禁止replacement，invalid member/protected admin规则保留；真实member library race |
| knowledge.member-candidates | B 指定library+q，真实limit20 | candidatesResource，新query/library clear，重复q失败保stale；retry用last submitted，close abort；与其它三用户候选不同，已真实fixture |
| knowledge.search | B q，真实limit20 | searchResource+appliedSearchQuery，pairedquery/reset；retry不提交draft，stale matches保留；真实controller |
| image.reference-thumbnails | S 每libraryAsset authenticated thumbnail blob | thumbnailResource批次error/retry+URL helpergeneration/AbortController；scope/close不能创建晚URL；实际URL生命周期fixture |
| image.pantone-library | F 完整颜色items，本地渲染cap240 | pantoneResource独立error/retry/cache；本地picker即时搜索专业选择例外，显示实际total与渲染边界，不算server page；fixture |
| image-admin.product-covers | S 每product+cover版本blob | 独立errors/loading/row retry，pending abort+version/desired guard；URL replacement/clear revoke；晚URL与retry实际fixture |
| image-admin.customer-options | B remote term backend max20 | term快照，换term/空/close clear，重复term失败stale；inline retry，不改变invite plaintext业务 |
| image-admin.product-assets | F productId完整array | editor assetsResource独立，product/open/reset/close清取消；asset写成功load失败不抛write错；真实controller |
| image-admin.library-assets | F public/private合并items | editor libraryResource独立stale/retry，copy对话框scope/close clear；不造page；真实controller |
| image-admin.product-asset-previews | S productId+assetId blob | 既有versioned blob controller保signal/current与独立retry；对应领域实际blob测试通过 |
| image-admin.library-previews | S libraryAsset blob | current blob controller与批量失败preview retry，selection按钮外避免嵌套按钮；close/invalidate晚URL拒绝；领域blobtests |

## 3. 全站只读抽查发现的确定遗漏/缺口

以下是主清单没有独立列出的真实业务集合，不能以其它主表已接入替代。只读fixture探针直接执行当前函数体，不是mounted全流程；stdout保留frontend/tmp/final-coverage-probes.txt。父已收到发现并分配实现，审阅时尚未将修复写为完成。

| 建议独立ID/源码 | 真实API/类型/边界 | 当前确定缺口及证据 | 责任/最小验收 |
| --- | --- | --- | --- |
| knowledge.ai-profiles — KnowledgeAiSettings.vue:183 | F GET /ai-profiles；backend service query.all | 已注册/knowledge/ai-settings；与preset/library Promise.all共失败，无独立inline retry/current guard；profiles初错看起来空，不能由Workbench八资源代表 | 本worker下一实施；独立first/stale/retry/actor scope；配置写成功read失败分离 |
| knowledge.ai-preset-options — 同load | F GET /ai-profiles/preset-candidates，全array .all | 独立选择器被绑定至profiles读取，任一失败阻其它成功提交；无独立retry | 本worker；保可用direct preset业务限制与APIconfig |
| knowledge.ai-library-options — 同load | F GET /ai-profiles/library-candidates，全active库array | 同上；配置target/source权限与可用库边界保留 | 本worker；独立scope/read/retry，不改写payload |
| knowledge.ai-profile-logs — KnowledgeAiSettings.vue:244 | B GET /ai-profiles/:id/logs，backend cap100最近 | drawer先await后开，无错误retry/clear/current；只读探针选profile2却呈profile1日志，确切跨scope覆盖；UI无100边界 | 本worker；先开，profile/close cancel，stale/read retry，最近100说明 |
| knowledge.optimization-profiles — AiOptimizationDrawer.vue:173 | F GET /ai-profiles?target_library_id，library权限过滤 | 内KnowledgeEditor真实使用；无latest/abort，library变化晚read可覆候选；仅loading无独立read retry | 本worker；library scope snapshot/clear/cancel/retry，保优化配置规则 |
| knowledge.optimization-history — AiOptimizationDrawer.vue:180 | B GET /documents/:id/ai-jobs，backend cap30最近 | 仅从最近30找queued/running/completed恢复job；doc切换虽然清job，旧restore晚回仍覆盖；实际doc2呈doc1 job探针；无独立恢复error/retry/30边界 | 本worker；doc/open/close generation，独立retry，保优化生成/费用/权限与poll流程 |
| color.blend-filter-options — BlendView.vue:302; color.palette-filter-options — PaletteView.vue:214 | S 完整筛选维度 | catch ignore，无可见retry；主blend/palette分页完成不代表维度已验 | 父；选项独立error/current/retry |
| color.blend-palette-options — BlendView.vue:309; color.swatch-color-options — SwatchGenerator.vue:188 | S 配色选择器来源GET colors真实P | 请求page_size1000，backend color/router.py:52合法max200 => 请求422且catch ignore；不是可用首1000。不能声明完整option集合 | 父；<=200合法页聚合全部或明示限量，current/abort/first/stale/retry |
| employee.attribute-history — EmployeeAttribute.vue:232 | F GET /attribute/history employee_id | catch清空且无read status/retry；探针选员工2却呈员工1history | 另agent；employee/close clear+abort,current,首次失败可见 |
| expo.store-users — StoreManagement.vue:262 | F GET /stores/:id/users完整已绑定array | 主stores页不代表成员完成；无scope abort，换store不先清旧；探针store2却呈store1binding | 另agent；store/close guard，独立retry，写成功read失败分离 |

Chat还应新增完整覆盖记录 chat.mode-catalog：F `/modes`固定服务catalog，与sessions资源不同。当前useChatModes.loadCatalog已经有catalogError/可见retry并保原items，mode详情另有generation guard；backend返回固定catalog()，可登记为专业静态方式选择器例外。此次未新增其mounted/并发验收，不将它计入session15tests完成；未发现应修改模式业务的确定缺陷。

AfterSalesAnalytics.vue当前聚合读也未被独立列名（只在generic dashboards例外中笼统描述）；它是S `/analytics` 聚合对象，不是普通主分页，现fetchData仅finally。建议台账明确该专业报表布局例外与读取验证状态，不宣称已具备独立inline retry。本次没有执行其controller或实后端探针，故只报告覆盖账本缺项，不列确定竞态结果。

其它此次快速扫描命中的门户kiosk/公共customer portal、本地编辑items、下载blob与dashboard摘要已存在明确总类例外；没有把它们硬套page或扩为本次全部验证。全站抽查不是穷举无缺口证明；本次明确存在以上未完成子集合，因此不能报告“全站无缺口”。

## 4. 后续同步与审阅边界

父代理同步上面第1/2节至docs台账；本worker已实施第3节六个knowledge AI资源，更新结果见第5节。父修color，其它agent修employee/store-users。此审阅未触碰这些其它代理文件，不修改被保护生成/流式/计费业务。主站task/Workbench/素材库/admin/会话列表既有交付有效；KnowledgeAISettings与优化抽屉是新发现的独立遗漏，不应削弱既有测试或用总数覆盖。


## 5. 后续实际修复验收：Knowledge AI 补漏已完成

第3节记录保留为发现时证据。随后按父代理授权已实现全部六个knowledge AI集合，并将当前job读取单列第七个S资源；当前不再把它们列为未修复。

| 资源 | 当前实际完成状态 | 实际回归证据 |
| --- | --- | --- |
| knowledge.ai-profiles | F独立profilesResource，first/stale/retry，actor/role clear+abort；成功空才显示暂无；summary初错用em dash；没有普通筛选，不造FilterBar/page | profiles与其它options失败独立；实际mounted首错retry及stale行保留 |
| knowledge.ai-preset-options | F独立presetsResource，主页面与配置字段均有单独error/retry，保存原direct/text preset与完整payload | preset失败不阻profiles/library成功数组；actual API signal/suppressToast |
| knowledge.ai-library-options | F独立librariesResource，来源/目标完整选项范围保持，单独error/retry，强制actor清旧 | 同上；save/delete成功但三GET失败resolve、原成功反馈保留 |
| knowledge.ai-profile-logs | B最近100，先开drawer，profile change清旧/cancel，close清/cancel，同profile失败stale，retry当前已选profile | 原跨profile反例已回归：旧profile aborted/late ignored；close late ignored；首错可重试 |
| knowledge.optimization-profiles | F按libraryId完整可用profile，profilesResource独立首次/stale/retry，current-only选择reconcile，open/close/library/doc/actor统一清旧 | doc/library同时switch旧两个请求abort；新profileId保22，旧11不回填 |
| knowledge.optimization-history | B按docId最近30，historyResource独立错误/retry，scope+jobVersion守恢复副作用；显式最近30说明 | 旧doc历史晚回不恢复其job；first history error阻止重复create，retry exact doc后可创建；mounted真实retry/bound |
| knowledge.optimization-job | S当前jobId详情/poll，jobResource独立error/retry，scope+jobVersion+ID guard，失败保成功job；close/reset/cancel/apply中止旧read | poll错误保running；retry同ID；旧poll不得覆盖cancelled；cancel写失败保持原active polling，不引入停滞；apply保原applied event/result |

优化开始之前若候选或最近任务历史尚未成功读取/正在读取/失败，会暂禁用按钮和handler，避免在无法确认已有任务时重复创建。已成功的生成任务、现有计费/后端权限/idempotency payload、格式/增强模式、取消/应用协议都保持。配置页save/delete已用独立boolean读取契约，成功POST不会被后续GET失败误标；旧actor成功写回复也不刷新新actor私有页。配置测试/检索预览只增加selected-profile generation保护，没有改其业务参数。

API只读追加可选config：listAiProfiles(targetLibraryId,config)、listAiPresetCandidates(config)、listAiLibraryCandidates(config)、listAiProfileLogs(id,config)、listDocumentAiJobs(id,config)、getDocumentAiJob(id,config)。原SILENT/default参数保持，真实wrapper回归断言signal/suppressToast/showLoading与target_library_id，所有写API保持。

实际验证：`node --test tests/knowledgeAiResources.test.mjs tests/knowledgeEditor.test.mjs tests/knowledgeState.test.mjs tests/knowledgeSidebar.test.mjs` **52/52通过**（12新增真实controller/API/mounted +40原领域），stdout `frontend/tmp/knowledge-ai-final-tests.txt`；两SFC compileScript+compileTemplate **0错误**；四个局部路径 `git diff --check` **退出0**。不是浏览器/live backend/provider运行。新增测试未跳过、不弱化原断言；生产业务数据未触碰。

修复文件：frontend/src/views/knowledge/KnowledgeAiSettings.vue、frontend/src/views/knowledge/components/AiOptimizationDrawer.vue、frontend/src/api/knowledge.js、frontend/tests/knowledgeAiResources.test.mjs。没有编辑台账、color、employee、StoreManagement、其它代理改动，也没有commit/push/build全站。

收尾最新只读抽查已见父/其它agent在color Blend选项、Employee history与Store users落入共享资源。这里不重新执行它们的测试或断言其交付已验，父以各责任人的专项结果更新第3节。此前四个只读race探针stdout是发现时源码结果，不应用于声称当前仍有同一bug。AfterSalesAnalytics聚合资源的独立台账边界、chat.mode-catalog专业选择器例外仍须父明确记录；本worker不报告全站无遗漏。原授权两批33资源及本次knowledge六集合+job读取的实现/聚焦验收闭环完成。
