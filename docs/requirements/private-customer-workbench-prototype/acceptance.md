# 验收与评审记录

范围：`codex/private-customer-workbench`，基线 `401a2a42`。交付目录 `docs/requirements/private-customer-workbench-prototype`。仅新增本任务文档和静态原型；没有改生产应用、迁移或部署。

CWC：已完成真实连接验证、MCP 定向读代码和 PLAN；原始规划保存在 `review/cwc-plan.txt`。本页初版为本地执行回执，第一轮 CWC 返回有限修正 R1–R5（review/cwc-review-1.txt），已完成修正，第二轮返回 STATE: DONE / ACCEPTED_FOR_SPEC_AND_PROTOTYPE。最终回执保存在 review/cwc-final-review.txt。

## 需求追踪

| 需求 | 可体验路径 | 本轮证据 | 未来生产验收 |
|---|---|---|---|
| PCW-01 每日优先行动 | 首页客户范围、指标、筛选/搜索；依据、登记结果/后续、延后、忽略、模拟扫描 | Node 去重/幂等/未解决后续/延后测试；浏览器完成/空态/延后 | 全量扫描覆盖、真实水位、归属切换、单活补偿、并发唯一键 |
| PCW-02 档案 | 编辑、原始背调、采纳/编辑采纳/驳回/稍后、历史；Velvet 并发冲突 | Node 版本/候选失效/治理白名单/转义；浏览器v4采纳、409演示修复后v5 | 事实注册、输入版本、管理流程隔离、私人备注ACL |
| PCW-03 沟通 | 渠道/联系人筛选、消息引用、绑定/再分析、源失权、草稿 | Node 未绑定/失权拒绝；浏览器 Solace 绑定→stale→v1；Lumière 隔离 | WhatsApp持续投影、真实增量覆盖、撤回/重绑/撤权依赖失效 |
| PCW-04 订单 | 类别/币种/单位/日期/产品维度与值；明细、结构、周期、新单覆盖 | Node 中位数30、混币单位、覆盖率、筛选、新单去重；浏览器A05关闭窗口 | Decimal、真实批次/退货/拆单、映射质量、历史口径版本 |
| PCW-05 监控 | 添加渠道/暂停恢复、模拟首采、失败、事件来源与确认/忽略 | Node基线/去重/正确证据/DNC原子；浏览器事件确认与首采 | 真实采集、每跳URL/IP检查、跨来源事件归并、告警质量 |
| PCW-06 日常维护 | 手动计划、生日/节日、活动预览、发货/签收/未测试改约 | Node计划DNC、改约同步、完成不可复活；浏览器日历09.29及名单排除 | 物流多对多关联、实际测试反馈、时区DST、投递幂等 |

## 实际执行结果

- 原型状态测试：`node --test tests/domain.test.cjs`，32 项通过；原始输出 `review/domain-tests.txt`。
- JavaScript：data/domain/views/app 的 `node --check` 通过。
- 浏览器：六类主流程已验证，记录在 `review/browser-checks.txt`；390、1024、1440px 对五个客户页面逐一检查，首页补充三个宽度，未见页面整体横向溢出。桌面/手机截图分别为 `review/desktop.png`、`review/mobile.png`，已实际查看。
- 弹层：首次发现原生 dialog 的 Shift+Tab 可逸出；增加明确焦点循环后，Tab/Shift+Tab、Escape、关闭回到触发按钮通过。减少动态设置下 transitionDuration=0s。控制台 error/warn 查询为空。
- 文档/范围：`git diff --check` 无错误；任务为新增未跟踪文件，该命令不覆盖全部新增正文，另做 UTF-8/文件引用与 HTML 本地资源检查。
- 仓库规则：`python scripts/check_conventions.py` 返回1，报告13项既有前端 UI 债务（invoice、asset、design、insight、knowledge、stock、system文件，均未改动），详见 `review/conventions.txt`。不能称全仓库检查通过，本任务未扩大范围清理基线债务。
- Git 巡检：`python scripts/git_sweep.py --no-fetch` 已运行，报告为本地快照，记录于 `review/git-sweep.txt`；没有 push、合并、删分支或处理其他代理改动。
- 未运行生产前端 build 或后端测试：本轮没有修改生产 Vue/Python；独立原型无构建步骤。没有数据库连接、迁移、真实AI/采集/发信验证。
- 自动化浏览器安全策略禁止 `file:` 导航，直接打开本地文件的方式未自动验证；使用已成功验证的 HTTP 本地预览。没有绕过策略。

## 独立风险审查与修复

项目 completion-checklist 要求跨模块契约/状态风险独立审查，本轮使用只读 agent 核查方案及原型，6项已修复并复验：

| 发现 | 修复与证据 |
|---|---|
| 等待回复却无后续 | 非resolved结果必须填写下一步；失败不改变状态 |
| 样品改约复活done任务 | 已结束任务拒绝改约，提示建立后续；计划与任务均不变 |
| 页面seq与持久回执键冲突 | 每次新的完成操作使用UUID，同一表单重试复用 |
| 监控建议跳无关消息 | 保存sourceType/sourceId，打开对应事件证据 |
| DNC后确认事件部分写入 | 前置检查及任务创建成功后再确认事件；失败无副作用 |
| 人工修订可被旧建议覆盖 | 同字段待处理建议标stale，禁止再采纳 |

独立 agent 复验结论：6项通过，无剩余阻断；验证限源码和 Node 内存场景，不是生产安全证明。

## UI 与动效自查

| Before | After | Why |
|---|---|---|
| 原生弹层焦点循环未显式约束 | 明确Tab首尾循环、Escape及焦点恢复 | 保证键盘用户能完成并退出操作 |
| 高频列表/筛选可引入延迟 | 直接更新，无入场动画 | 保持每天多次操作响应及时 |
| 普通按压反馈 | 140ms transform反馈；reduced-motion关闭 | 有反馈且不强迫动画 |
| 可能的大面积实时玻璃模糊 | 静态暖色背景、边框、低阴影 | 避免滚动时昂贵重采样 |

本原型固定演示时间、单用户本地存储、同步模拟AI；不是后台任务队列/多用户ACL/跨标签并发实现。URL检查仅是输入体验，不构成真实抓取SSRF防护，后端要求见开发规格。来源链接和客户均为合成数据。

## CWC 第一轮 R1–R5 修正与第二轮证据

| 问题 | 修复 | 本次实际验证 |
|---|---|---|
| R1 绑定/分析建议与引用 | 稳定客户+渠道消息集合、binding/analysis版本依赖；两种采纳共用校验 | Solace绑定后无可采纳入口；新分析后编辑采纳到v4；Novelle两渠道原文/摘要一致；Node旧版本/来源负面路径 |
| R2 后续任务与日历 | 稳定issueId+attempt；plan当前任务/日期随后续原子更新；完成历史、sample状态分开；未来snooze不主动推荐 | t3完成待回复→task-7/09.26→改约09.29；旧t3始终done；重放不新增 |
| R3 调度与采集健康混淆 | enabled与采集status独立；领域函数控制切换/采集 | Instagram暂停恢复仍失败且水位09.22；显式模拟采集后09.24成功；首采无历史事件 |
| R4 订单质量及窗口归属 | 缺值未知、双覆盖率；产品族周期+计算窗口；明确关联取消；极差/中位数>0.6降级 | U01发束新单不关发块任务且金额未知；A05覆盖后仅对应旧任务取消，计算窗口10.16–10.30；不同族/样品/不规则负面测试 |
| R5 当前模型衔接 | 行动结果/事项状态分开；注册偏好键+Annotation v2投影；私人备注复用Annotation；版本矩阵/活动与样品入口/六类payload/事项与多轮行动约束 | 只读独立agent核查现有contracts/workflow/profile编译器；文档逐项映射，未改生产代码 |
| 保存后焦点丢失 | 以data-action+data-id定位重渲染后的控件 | 保存/取消分别验证，均回edit-field/market；操作消失才回main |

第二轮完整浏览器操作与数值记录 `review/browser-checks-2.txt`，32项Node完整输出 `review/domain-tests.txt`。保留原21用例，增加11项负面/跨状态回归。修改后五个客户页面在390/1024/1440逐页无文档横向溢出，三个宽度演示指南弹层边界正常；reduced-motion=0s；控制台warn/error为空。原型schema升为2，重新加载从新的合成状态开始，避免旧状态缺字段。

CWC通过MCP读取源码与日志；无法独立查看截图，不能把执行端视觉检查写成CWC视觉复核。首轮13项全仓规范基线失败仍保留披露，本轮未改其涉及文件。

## 最终交付状态

CWC task c2c_pcw24，iteration 2：DONE，接受规格与交互原型，R1–R5及保存焦点全部关闭。其复核基于当轮14份完整快照和执行证据；原快照封存 `review/cwc-reviewed-iteration-2.zip`。

最终收口另做两处文档澄清，已由独立agent逐项复验：维护实例键改约不变；关联维护实例的完成请求必须带 expected_occurrence_version。未改变原型源码，无需重跑状态测试。最终manifest列的是收口后文件哈希，不混同于CWC当轮快照哈希。

交付仅方案与原型。没有生产修改、提交、push、合并、数据库迁移或部署；后续按A/B/C/D阶段实施。原型预览恢复初始合成数据。
