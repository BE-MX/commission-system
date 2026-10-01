# Final parent contract review

独立只读审查，2026-10-02。范围严格限于父代理最后指定的 WorkspaceConversations/useCursorResource/AgentRunDetail、Color options、BattleReports及新增ReportSettings participants、售后/生产聚合、UI audit/exception registry、tableView相关修复。未展开全站扫漏；未改源码、门禁或台账；fixture探针不访问生产。

## 结论

指定范围最终复核通过，当前没有剩余确定缺口。初轮复跑指定Node回归18/18、Python门禁负例5/5，UI audit --baseline-ref HEAD通过，实际baseline相对HEAD的受管metric增长为0。独立探针发现三项确定缺陷后父代理已修复；本代理重新读取三处最新源码、复跑aggregateResourceBoundaries 6/6并重跑原生产raw反例，全部通过。真实后端边界与cursor/color取消规则一致，专业布局保持。第1节保留发现时反例与修复建议供审计，最新修复验收见第5节。

## 1. 确定问题与最小复现

### [P1] Production dashboard successful raw body becomes empty successful aggregate

- backend/app/production/router.py:25-31直接return dashboard_service.get_dashboard_data(db)；dashboard_service返回raw `{orders,kpi,process_stats,today_completions}`，不是ok(data)。frontend/api/request.js拦截器return response.data，api/production.getDashboardData无额外包装。
- 新 useDashboardData loader只取`(await getDashboardData(config)).data`，真实值undefined。原HEAD读`res.data ?? res`；新aggregateResourceBoundaries测试fixture用`{data:{...}}`掩盖了真实contract。
- 最小fixture：actual composable、mock API返回raw orders id7/kpi transit_count7；调用refresh后实际`hasLoaded=true, orders=[], kpi=0, error=''`。用户会看到成功加载的零看板，而非真实生产订单。
- 最小修复：按此endpoint已确认的raw body读取，保留shared async error/current；测试必须用真实raw envelope，同时保latest/stale与quiet/interactive loading断言。不要改backend业务聚合或用空值fallback伪装成功。

### [P2] Battle selector completion resets a selection made during its request

- BattleReports.loadReports(preferred=selectedId.value)在调用时捕获旧preferred。selector成功后没有检查选中report/scope是否已在等待期间改变，按旧preferred重新赋selectedId并changeReport。
- 最小fixture：初始目录含id1/id2并选id1；第二次loadReports目录GET挂起；用户selectedId=2且changeReport成功，当前2/2；旧目录返回仍含两项；实际变1/1。
- 用户刚切换的战报被目录重试切回旧项。detailResource自身latest只保证最新detail提交，阻止不了调用层主动重选旧ID。
- 最小修复：await selector后同时检查selection/scope generation，不覆盖等待期间用户已提交的选择；archive真实范围切换仍允许首次选择新范围有效首项。增加该真实caller路径回归，不能只测旧detail晚回。

### [P2] ReportSettings old successful save closes a newly opened report dialog

- participants读取已latest/cancel，但save仅guard loading/error，无open/report submission generation。POST等待期间关闭report1并打开report2，旧结果仍emit saved(1)和update:modelValue(false)。
- 最小fixture：设置report1载入候选后save挂起；close、换report2、open且候选成功；旧update回`{id:1}`。实际事件为保存设置、saved1、关闭false。父的settingsSaved会重新选旧报告，且新dialog被关闭。
- 最小修复：开始写时snapshot reportId/version/open generation，关闭/换report/卸载作废UI副作用；写已完成的事实保留，新dialog不被旧reply修改。读取门禁与既有roster补入规则保持，真实deferred POST回归验旧成功不关新dialog。

最小fixture直接执行当前真实SFC/composable script与shared hooks，stdout：frontend/tmp/final-parent-contract-probes.txt。上面三项不是静态猜测，也不是生产请求。

## 2. 按指定资源核对

| 资源 | 真实API与边界 | 核对结果/具体证据 |
| --- | --- | --- |
| hub.conversations | P /customers/:id/conversations items/total，backend page20、max100 | 独立useListPage，20/50/100；customer prop sync scope先clear/cancel+selection reset，失败保同scope；不制造editable筛选；真实controller独立pending失败、分页scope通过 |
| hub.pending-bindings | P /conversation-bindings/pending，page20/max100，全局资源 | 不随customerId伪造过滤或清旧，和conversation不同resource；binding原payload/idempotency/evidence保持；写成功后局部read失败boolean不当write错；晚旧customer写不关闭新customerdialogfixture通过 |
| hub.messages | C conversationId/cursor/limit20，backend(sent_at,id)ASC，next_cursor/has_more | useCursorResource失败保items/cursor，成功后才Map去重追加；selectConversation与customer switch先clear/abort；old response不能回填；首错retry，继续页无偏移跳页 |
| useCursorResource | 共享C控制器，外部caller负责scope clear | 使用previous成功nextCursor，busy拒重入；failed resource.load返回false，cursor不变；clear中止并清旧；Map key去重。泛用load不自动判断scope，当前两个caller均明确clear；不是普通page模型 |
| agent.run/artifacts | S /runs/:id返回run/artifacts | 独立runResource，route runId sync clear，detail错误可retry；cancel/accept/reject/feedback在confirmation后校验scope，写成功读失败不误报；unmount disposed阻再arm timer |
| agent.events | C /runs/:id/events after_sequence，backend max500、ASC/visibility | initial0、key sequence_no、next=max序号、满500可loadMore；实际500=>next500，第二块失败保500历史，retry仍500并到501；无需固定首500裁掉后续；run switch清，run与events失败分离 |
| color.palette/filter-options | S 完整维度对象 | body.data与真实_ok一致；独立resource first/stale/retry，失败不吞palette主列表；controller实际envelope通过 |
| color.blend/filter-options | S 完整维度对象 | 和基础palette独立，filter失败不阻catalog，stale/latest实际fixture |
| color.blend/selectable-colors | S 选择器聚合真实P全部页 | getAllColorsForSelection按page_size200合法页同AbortSignal；backendmax200、稳定color_family/id排序，Map dedup；总401实际3页200/200/1；空缺页与去重后unique小于total均throw，成功partial不可展示 |
| color.swatch/selectable-colors | S 同完整聚合 | 没有原1000非法请求；独立error/retry，failed initial不判空，同scope失败保成功options；实际controller通过；生成表单布局不改成列表筛选 |
| battle.selector | F backend.all、archived显式范围 | shared first/stale/retry；archive change清旧report/overview；晚目录覆盖选择已用scopeVersion修复并通过真实调用路径回归，见第5节 |
| battle.detail | S get(reportId) | 和overview分别load，可一成一败；selected change先clear，原members/version业务保留；existingdetail late test通过 |
| battle.overview | S reportId+team聚合 | independentcurrent/stale/retry；team为专业即时分类，不硬套FilterBar；每日复盘/目标/海报布局保持；detail成功不被overview失败吞 |
| battle.audits | P reportId+page/size，backendmax100 | 已独立useListPage与applied scope watcher，关闭null scope清cancel，20/50/100 handlers对应；此轮重点为三主资源，不用它们代替audit数据 |
| battle.participants | F 有效外部绑定完整items | ReportSettings asyncsnapshot existingmembers，API config带signal/suppressToast；open/report变化clear，close cancel，已有名单缺候选补入；loading/error/unloaded阻save；旧POST不再emit/关闭新dialog，A-B-A实际回归通过 |
| aftersales.summary | S ok(data)聚合，by_product/by_batch真实各top20 | summaryResource body.data正确，first retry与stale retained summary；专业bar/rank/trend布局保留，无伪page；实际summary错误/stale/计算fixture通过 |
| production.dashboard | S raw聚合全部active orders+kpi/process/today | 专业Donut/Timeline/OrderProgress/Wip与local modal保持；60s quiet定时及unmountcancel保留；loader直接采用真实raw body，无多余data或fallback，最新raw fixture/current/stale及原反例均通过 |

Color补充只读反例：两页reportedTotal201，首200distinct、第二页非空但重复ID1。最新helper确实throw“色号选项未完整读取，请重试”，没有返回200项假全量。该行为已实际执行，首次未捕获stack是探针写法，现stdout只保有效结果；未改helper。

## 3. UI audit、exception registry与table viewport

- 实际`python -m unittest discover -s scripts -p test_audit_frontend_ui.py -v`：5/5，通过布局/sizes/default20负例、form顶部labels、GlassButton非法size/非md、sharedimplementation路径限定、exception cap、newbaseline growth禁止、quoted比较tag parser。
- 实际`python scripts/audit_frontend_ui.py --baseline-ref HEAD`退出0；stdout frontend/tmp/final-parent-ui-gate.txt。受管新metric bad_pagination_sizes/bad_page_default/form_label_position/bad_glass_button_size/non_md_glass_button/inline_public_validator均0；未忽略新增非标准表格规则。
- 独立JSON比对baseline_increases(current,gitshowHEAD)为0。--write-baseline路径先scan与growth拒绝后才write；本审阅没有执行write-baseline。已登记19个exception路径仅non_md_glass_button，各含count+业务reason，scan要求当前原始count精确匹配并扣固定数，增加一个同类按钮仍失败；不是整文件忽略。
- 专业紧凑card/upload/生成器/详情按钮是计数例外；PM六个新增main-site metric按独立规范不强套主站，但原PM债务仍冻结。门禁是静态规则，不证明选择器变量runtime值或真实几何；现pagination变量binding允许语义审阅是源码明确设计，literal数组严格20/50/100。
- `.table-card--fullscreen`已box-sizing:border-box，因此100vw/100dvh不再把border额外算到2px宽；Escape仅visibleOverlay rect>0且visibility非hidden阻退出，ElementPlus display:none旧overlay不再误拦；tableView实际两测试通过，包括open overlay/Escape、scroll restore与单一active fullscreen。
- 父提供浏览器sample已修Escape隐藏overlay和2px溢出；本审查只核对对应源码与回归，没有重新操作浏览器，不把其sample升级为全站几何验证。

## 4. 执行记录与交付边界

Node：node --test tests/cursorCollectionResources.test.mjs tests/systemCandidateResources.test.mjs tests/colorOptionResources.test.mjs tests/aggregateResourceBoundaries.test.mjs tests/tableView.test.mjs，18/18通过，0skip，stdout frontend/tmp/final-parent-contract-tests.txt。

本次复跑指定systemCandidate三个既有回归作组合gate证据，不重复其实现审查或扩大新用户候选scope。Resource行为证据是controller/fixture与源码/backend交叉，不是live浏览器或真实POST。未运行fullbuild/commit/push/deploy，未修改父/其它代理源码。下列三项修复复核只读取父修后的对应源码与实际测试，没有扩大扫描。

## 5. 三项修复最终复核

- Production raw：loader直接return getDashboardData({signal,suppressToast:true})；没有兼容fallback。最新aggregate fixture采用真实raw `{orders,kpi,process_stats,today_completions}`并断言四类数据、signal、latest与stale。另重跑原id7/kpi7反例，实际 `hasLoaded=true, orders=[7], kpi=7, process='Sewing', completed=9, error=''`，原零看板问题关闭。
- Battle selector：archive范围重置后捕获scopeVersion；等待期间changeReport增加version，目录完成后可保留同archive的新目录，但不再restore旧preferred或重读旧detail。实际慢目录pending后切2，结果仍selectedId2/report2；archive清旧与detail迟到反例同样通过。
- ReportSettings：open/report ID watch采用flush sync，关闭/切report递增scopeVersion并clear participants；写前固定原report/id/version/payload，异scope成功保留写成功提示但不emit saved/close，旧错误不污染新form。实际save1挂起，close/open2/close/reopen1的A-B-A回归保持原写payload/version/reason/members，不emit并保留重新打开草稿。
- 实际再次执行 `node --test tests/aggregateResourceBoundaries.test.mjs`：6/6通过，0skip。最终定向stdout：frontend/tmp/final-parent-contract-fix-tests.txt。初轮18项和Python/UI gate结果来自第4节记录；三项最终修复不涉及门禁或其他已核对资源，未重复无关检查。

三项均关闭；指定审查范围内无剩余确定缺口。此结论限于源码/backend及真实controller fixture证据，不宣称全站浏览器或生产数据验证。
