# 设计规范四阶段最终验收

更新：2026-10-02。既定第1–13项及主站资源推广、门禁、规范索引已落地；原工作树为 `C:/Users/windb/.codex/worktrees/list-filter-behavior/commission-system`，分支 `codex/list-filter-behavior`。亮哥随后授权合并推送部署，应用版本`6afaf0b4`已发布，见[发布记录](../reports/2026-10-02-ui-convergence-release.md)。下文“未提交/发布”描述实现阶段的历史证据；忽略的验证与恢复材料已保留到主目录`.deploy_state/ui-convergence-delivery/`。

当前资源账本登记277个唯一语义资源：P85 / F74 / B34 / C3 / S81，已知待实施0；另列10类专业交互与范围边界。该计数证明已识别资源的采用与证据状态，不代表所有生产流程均已实机验证。

## 实现与完成证据

| 清单 | 已落地产物与用户影响 | 证据 |
| --- | --- | --- |
| 1 列表读取 | 首错可重试、刷新失败保成功行；旧响应和取消读取不能污染新范围 | useListPage、useAsyncResource、useCursorResource；useListPage及各域资源回归 |
| 2 筛选提交 | 草稿与已提交快照分离，日期/排序/翻页不偷用未提交输入；Enter排除IME/下拉确认 | FilterBar、列表回归；一期三试点及样例浏览器 |
| 3 CRUD刷新 | 新增按业务排序定位、编辑保有效页、末页删除修正；写成功不被后续读失败误报 | 财务/库存/设计/任务等领域测试，保留原金额与状态业务约束 |
| 4 筛选结构 | 轻量共享FilterBar，主字段与高级展开、小屏、pending说明 | listPageComponents/listPagePilots及实际mounted页面 |
| 5 弹窗与表单 | 短表单480/640/760、顶部标签、可达footer；长内容与专业编辑流程保留明确用途 | UI门禁，窄屏样例表单；领域实际挂载 |
| 6 状态 | StatusBadge及域字典单点标签/语义色；未知状态可读 | sharedUi及领域状态测试；静态裸tag度量归零 |
| 7 反馈与空态 | 共享反馈、精确成功文案、原确认依据、错误去重；空态提供恢复动作 | sharedFormats、requestResponse、EmptyState/ListPageStatus；主站裸消息度量0 |
| 8 金额 | formatMoney保币种、精度、负值与缺失值，显示与计算分离 | sharedFormats、financialListResources及原财务精度测试 |
| 9 校验 | validators统一号码/邮箱/金额基础检查；国际/展会/高精度策略保领域含义 | validators回归及公共正则门禁负例 |
| 10 分页与详情 | 真分页默认20、20/50/100；无分页接口保原树/集合/历史；描述列数按容器缩窄 | UI分页门禁；sharedUi；390px实际详情单列 |
| 11 偏好 | 版本化持久化、损坏/旧键容错、已知列交集、动态标签至少一列、恢复默认 | tableView/列表组件回归；实际浏览器刷新恢复 |
| 12 颜色与尺寸 | token语义色、控件36px、按钮md；紧凑用途按精确数量登记 | sharedUi 4.5对比度；audit/exception registry |
| 13 样例 | ComponentShowcase与navigation单一入口；loading/empty/error/readonly/超长/窄屏/键盘/减少动态 | [真实浏览器报告](ui-convergence-evidence/browser-showcase.md) |
| 全站资源采用 | 按语义资源逐项确认P/F/B/C/S，独立失败与作用域隔离；辅助读不被主列表成功掩盖 | [当前资源账本](2026-10-02-list-resource-coverage.md)，不使用组件引用数充当覆盖率 |
| 门禁与规范 | 新增分页/表单/按钮/公共校验规则、精确例外、禁止基线上调；DESIGN实现索引与handoff同步 | scripts/test_audit_frontend_ui.py、audit_frontend_ui.py、check_conventions.py |

## 最终命令结果

- `node --test tests/*.test.mjs`：**1185项，1179通过，6失败**。六项均为既有`loginMapMotion.test.mjs`的Canvas mock缺少`ctx.save()`。已在隔离目录使用HEAD原源码/测试/地图数据复现相同6失败；三个文件未修改。本轮引入的断言失配与缺陷已修复，未删测试或弱化断言。完整stdout：`frontend/tmp/ui-convergence-final-tests.txt`。
- `npm run build`：通过，113项导航清单；既有auth静态/动态混合导入与大chunk警告仍存在。stdout：`frontend/tmp/ui-convergence-final-build.txt`。
- `python scripts/test_audit_frontend_ui.py`：5/5通过，覆盖真实负例、解析与禁止baseline增长。
- `python scripts/audit_frontend_ui.py --baseline-ref HEAD`：通过；表格不变量及新增分页/默认20/表单/GlassButton/公共校验度量均0，受管基线无增长。
- `python scripts/check_conventions.py --strict`：通过，增量无违规。stdout：`tmp/ui-convergence/final-conventions.txt`。
- `git diff --check`：通过；`python scripts/git_sweep.py --no-fetch`：本地快照巡检，不能证明远端当前状态或授权任何远端操作。

全量测试的6项既有失败是明确未解决项，不宣称全量绿。生产数据/权限全流程、实体手机及生产MySQL写入没有在本任务验证；所有写入型测试使用隔离夹具。

## 审查关闭记录

独立审查发现并实际复现的缺陷均已修复并针对原反例复核。最后三项：生产看板真实raw body多解`.data`造成假零；战报慢目录读恢复旧选择；旧战报保存关闭新打开的对话框。现在按endpoint真实raw读取，目录读取检查选择generation，保存固定原id/version/payload并拒绝跨弹窗提交副作用。最新aggregate回归6/6及原raw反例通过。

其他领域重点证据：

- [价格/名片/公告/Operations](ui-convergence-evidence/price-card-announcement-operations-review.md)：27回归、10真实API适配器探针、3实际Vue页面挂载。
- [生产路线](ui-convergence-evidence/production-route-resource-review.md)：步骤/条件规则原子读取、只在实际403按权限降级，dirty/关闭/跨路线保护。
- [历史与门店人员](ui-convergence-evidence/employee-store-child-resources-review.md)；[产品/运单辅助](ui-convergence-evidence/product-tracking-aux-resources-review.md)：独立history/users/candidates/options/detail/stats范围与写入对象捕获。
- [任务/知识/图片库](ui-convergence-evidence/task-knowledge-image-list-adoption-worker.md)：树、成员、审批/修订、预览等独立资源与dirty guard，104组合回归。
- [图片/聊天/客户图片/WhatsApp](ui-convergence-evidence/image-whatsapp-list-adoption-worker.md)：14资源，119组合回归，游标与限量明确。
- [最终已知漏项核对](ui-convergence-evidence/final-coverage-review.md)：历史发现及后续KnowledgeAI修复追加记录；完成状态以当前资源账本为准。
- [主仪表盘](ui-convergence-evidence/dashboard-resource-review.md)：15独立可选读，账号/权限scope，未知值与最近首5边界；非东八区5/5回归。
- [最终父层契约审查](ui-convergence-evidence/final-parent-contract-review.md)：真实响应形状/游标/Color完整页/聚合/门禁；三项最后缺陷复核关闭。

## 业务边界与剩余债务

P资源保真实分页，F资源保完整集合/树，B资源明确首批/最近限量，C保追加游标，S独立处理详情/统计/候选。WhatsApp保首50会话/最新50消息；Chat保最近30；Operations保最近30运行；周公告52版本/投递200；研究批次任务300；其他限量逐项列在账本。Color完整选择集合按合法每页200读取全部页且校验去重后总量，不能用非法1000参数或成功partial代替全量。

主站新增规范已门禁。剩余冻结指标：hex_colors611、small_controls21、inline_width157、empty_text_attr5、bad_drawer_size2、bad_value_format11、deep_el_override266、money_format24；包含PM独立风格、专业图表/预览与领域计算等历史弱信号，不能宣称全站零UI债务。非md按钮19个路径按精确数量与用途登记，新增数量会失败。超过500行已从UI债务移除，只按职责复核，不机械拆文件。

保留交付文档、截图、测试输出、隔离HEAD基线与恢复材料；本轮一次性codemod工具已清理。未动其他代理工作树、未提交、未推送或部署。工作树和node_modules链接保留供审阅/继续集成。
