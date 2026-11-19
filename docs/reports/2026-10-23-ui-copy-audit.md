# 方舟平台 UI 文案审查与优化方案

日期：2026-10-23（北京时间）
规则提交：`684e24615cefe804a64df32a2093f8eb7cf3139f`，已推送 `origin/main`。
审查准则：`DESIGN.md`「UI 文案基本规则」——让布局解释界面，让文案补充必要信息。

## 结论

优先删除列表页头的功能复述、工作台入口的同义描述和页面中的开发阶段承诺；对资金、库存、权限、AI 证据与提交结果的提示，重点调整位置和表达，不以字数为目标删减。客户门户的交易页面可以比品牌入口更克制；产品介绍、知识正文、会议纪要和真实业务描述不属于应批量删除的辅助文案。

本轮交付优化方案及源码证据，未修改业务 UI。Git 推送仅包含新增设计规则，不包含方案和证据文件，也没有生产发布。

## 覆盖与证据边界

- 对 **503 个 Vue/WXML/HTML 页面及组件文件**建立文本清单，共抽取 **14,287 条模板文本/属性记录**。其中主站 Vue 428 个、主站静态 HTML 18 个、PM 22 个、客户门户 17 个、小程序 18 个。文件数不等于页面数。
- 登记 **190 条入口记录**：主站导航 142 条（含采购节外链），独立路由 5 条，PM 6 条，客户门户 8 条路由/界面状态，小程序注册页面 11 条，静态 HTML 18 条。部分入口指向同一组件，静态入口与导航也有重合，不当作独立页面总数。
- 补查 PDA 和平板壳 **48 个 Kotlin/XML 源文件**，另核对工作台动态入口配置、客户效果图中英文字典及其渲染位置。
- 辅助文案候选提取使用 HTMLParser、节点类型和样式名，仅用于定位。1,397 条候选包含业务正文、标签与条件分支，**不是 1,397 个问题**。对本报告提出的条目已核对具体源码；全量自动扫描不等于每个节点均人工判定通过。
- 浏览器可列出方舟内网标签页，但第一次连接超时、第二次返回 `Debugger unattached`，未取得有效截图。线上各角色、设备尺寸、弹窗及异步状态尚未验证；本报告是源码文案审查，不是在线视觉或可用性验收。
- 库存色块图三条路由仅能检查 `ColorworkFrame.vue` 外壳；SSO 子应用内部、服务端生成的报表 HTML、数据库配置/用户输入的文案与图片内文字不在本轮完整覆盖范围。生产实际版本未与本地构建逐项比对。
- `miniprogram/pages/photo/photo.wxml` 有源码但未列入当前 app.json；保留为未注册页面，不误算在 11 个现役页面中。静态演示页面的“示例数据”标识必须保留。

## 优先级与执行顺序

| 批次 | 目标 | 实施范围 | 验收重点 |
| --- | --- | --- | --- |
| P1 状态文案校准 | 消除错误预期 | “尚未接通”、P2/二期、相对上线时间 | 当前功能状态有依据，未开放明确说明，无虚假工期 |
| P2-A 简单删减 | 首屏更直接 | 页面副标题、装饰性眉题、功能列表式说明 | 删除整段对应空白容器；标题、按钮和表单标签完整，桌面与窄屏无残余空白 |
| P2-B 按需说明 | 信息在需要时出现 | 表单规则、同步解释、统计口径、快捷入口 | 将必要提示放到字段、状态或决策动作旁；关键后果不能只放 hover tooltip |
| P3 跨端收敛 | 高频操作更简洁 | 小程序/PDA 扫码、静态门户、客户效果图中英文字典 | 保留身份、扫码对象、提交进度、失败恢复；键盘/触屏/屏幕阅读器可辨识控件 |

先改页面自身的静态冗余，再改共用组件配置。不要全局隐藏 `.subtitle`、`.hint`、`description`，也不要把所有说明统一塞进问号。共用组件的帮助内容应可选；如当前组件已支持空值，不额外建设新的文案框架。

## 已定位的优化项

每行只表示对应位置的建议。标记 P1 的条目是信息可信度问题，需核对功能事实；其余删除/改写应在 UI 渲染复核后实施。

| ID / 优先级 | 位置 | Before | After | 为什么 |
| --- | --- | --- | --- | --- |
| C01 / P2 | [AnnouncementList.vue](../../frontend/src/views/announcement/AnnouncementList.vue#L13):13 | 发布通知、沉淀知识，重要信息及时送达。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C02 / P2 | [InvoiceManage.vue](../../frontend/src/views/invoice/InvoiceManage.vue#L13):13 | 客户发票、产品明细、价格管控、导出与小满同步集中处理。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C03 / P2 | [InvoicePriceConfig.vue](../../frontend/src/views/invoice/InvoicePriceConfig.vue#L13):13 | 标准参考价矩阵、色型映射、客户价格规则与生产单沉淀产品管理。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C04 / P2 | [ReceiptManage.vue](../../frontend/src/views/receipt/ReceiptManage.vue#L13):13 | 每笔回款关联订单，凭证与同步结果集中查看。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C05 / P2 | [BattleReports.vue](../../frontend/src/views/battle-report/BattleReports.vue#L3):3 | 目标有方向，业绩有依据，复盘到每一笔订单。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C06 / P2 | [AfterSalesAnalytics.vue](../../frontend/src/views/aftersales/AfterSalesAnalytics.vue#L9):9 | 从问题、状态和赔偿成本识别需要优先复盘的产品与流程。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C07 / P2 | [AgentTaskCenter.vue](../../frontend/src/views/agent-runtime/AgentTaskCenter.vue#L12):12 | 统一查看 DSH 等受控运行时的任务、过程、成本、证据与人工决策。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C08 / P2 | [CustomerImageAdmin.vue](../../frontend/src/views/customer-image/admin/CustomerImageAdmin.vue#L7):7 | 维护客户可选产品、发放专属邀请，并追踪生成额度与结果状态。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C09 / P2 | [CustomerWorkbench.vue](../../frontend/src/views/customer_hub/CustomerWorkbench.vue#L1):1 | 围绕客户目标推进事项、核验准备结果，再登记真实行动与业务结果。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C10 / P2 | [DomesticDecision.vue](../../frontend/src/views/domestic_decision/DomesticDecision.vue#L4):4 | 从真实订单与客户记录出发，找到值得核对的变化，把判断落到行动。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C11 / P2 | [OrderIntelligence.vue](../../frontend/src/views/order_intelligence/OrderIntelligence.vue#L13):13 | 从订单事实识别市场机会、团队能力与客户下一步行动，所有建议均附证据与口径。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C12 / P2 | [IntelligenceLibrary.vue](../../frontend/src/views/insight/IntelligenceLibrary.vue#L13):13 | RSS / XPOZ / 竞品监控 / 手工上传的情报条目，支持精选与归档。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C13 / P2 | [IntelligenceOverview.vue](../../frontend/src/views/insight/IntelligenceOverview.vue#L13):13 | 按日期范围汇总行业情报条目，支持定时生成与置顶查看。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C14 / P2 | [PortalSettings.vue](../../frontend/src/views/portal/PortalSettings.vue#L86):86 | 统一维护客户站入口状态、报价期限与可选付款条件。 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C15 / P2 | [ImageStudio.vue](../../frontend/src/views/design/image-studio/ImageStudio.vue#L39):39 | 用自然语言生成，并从任意结果继续修改 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C16 / P2 | [DashboardView.vue](../../frontend-pm/src/views/DashboardView.vue#L6):6 | 打开 3 秒看懂「项目推进到哪了、材料备齐了多少」 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C17 / P2 | [ActivityView.vue](../../frontend-pm/src/views/ActivityView.vue#L6):6 | 谁、何时、做了什么——出了问题能追，平时当项目日报看 | 删除该段副标题；保留页面标题、筛选、操作、状态及数据口径。 | 重复介绍当前页面功能，未提供操作决策所需信息。 |
| C18 / P1 | [OkkiSyncSettings.vue](../../frontend/src/views/invoice/OkkiSyncSettings.vue#L13):13 | 推单接口尚未接通，配置先行生效于同步前校验。 | 核实当前环境的推单可用状态后移除这句历史阶段说明；若功能不可用，显示实际原因及处理入口。 | 源码已有推单与 linked-sync 路由，静态“尚未接通”可能误导管理员；不能仅凭源码断言线上可用。 |
| C19 / P1 | [TrendView.vue](../../frontend/src/views/color/TrendView.vue#L18):18 | 预计 P2 阶段实现（1-2 周后） | 删除阶段编号与相对工期；保留“色彩趋势暂未开放”及可用入口。 | 开发计划不是面向使用者的状态保证。 |
| C20 / P1 | [TaskDetailDrawer.vue](../../frontend/src/views/task/components/TaskDetailDrawer.vue#L81):81 | 分支和 commit 自动关联在二期上线，现在可以手工挂文档或原型 | 尚无关联资料。可添加文档或原型链接。 | 移除未经当前进度验证的上线承诺，保留恢复动作。 |
| C21 / P1 | [TaskDetailDrawer.vue](../../frontend/src/views/task/components/TaskDetailDrawer.vue#L52):52 | 每行一条。二期起 AI 提议完成时会逐条对照 | 每行填写一条验收标准 | 占位符只解释输入格式。 |
| C22 / P2 | [cards.js](../../frontend/src/views/dashboard/cards.js#L80):80 | name: '用户管理', desc: '管理系统用户' | 工作台入口默认只显示名称；“用户管理”等重复说明删除。少数含不同业务含义的入口单独保留说明。 | ActionsGrid.vue:32 统一渲染 card.desc；应逐条审定配置，不能整块隐藏全部说明。 |
| C23 / P2 | [FavoriteNavigation.vue](../../frontend/src/views/layout/FavoriteNavigation.vue#L41):41 | 勾选即可添加，取消勾选即可移除。返回导航栏拖拽调整顺序。 | 选择后自动保存。排序提示保留在导航拖拽手柄的可访问名称和提示中。 | 勾选行为已由控件表达；自动保存与调整位置仍需可发现。 |
| C24 / P2 | [AssetLibrary.vue](../../frontend/src/views/asset/AssetLibrary.vue#L166):166 | 在左侧选择标签即可查看对应素材。标签集会随你的选择自动收窄，越选越精准。 | 保留空态标题“选择标签，开始检索”；删除介绍段和重复搜索指引。标签逐层收窄机制放首次帮助。 | 标题、标签区和搜索控件已说明下一步；“左上角”在窄屏不可靠。 |
| C25 / P2 | [InvoiceSummaryCard.vue](../../frontend/src/views/invoice/components/InvoiceSummaryCard.vue#L2):2 | 随明细实时联动 | 删除；实时金额更新由数据变化表达。 | 与汇总组件行为重复，不提供新的金额口径。 |
| C26 / P2 | [InvoiceHairTable.vue](../../frontend/src/views/invoice/components/InvoiceHairTable.vue#L7):7 | 四个关键词选择完整后自动匹配唯一 Product_name。 | 选齐规格后自动匹配产品 | 移除内部字段名，保留自动匹配的触发条件。 |
| C27 / P2 | [InvoiceReceiptFields.vue](../../frontend/src/views/invoice/components/InvoiceReceiptFields.vue#L7):7 | 小满回款方式默认按 Other 提交（小满侧非必填），无需选择。 | 常规收款界面删除；若业务需要核对映射，在同步详情显示“小满回款方式：Other”。 | 用户无需选择的实现默认值不应占据表单说明区。 |
| C28 / P2 | [PortalOrders.vue](../../frontend/src/views/portal/PortalOrders.vue#L133):133 | 核对客户需求，跟进确认与正式 PI。当前列表仅包含服务端授权的请求。 | 删除该副标题；状态列与操作名称继续表达审核流程。 | 功能复述及服务端授权实现说明不会帮助当前列表操作。 |
| C29 / P2 | [PortalCustomers.vue](../../frontend/src/views/portal/PortalCustomers.vue#L158):158 | 管理客户查价、下单和登录资格，变更按方舟当前客户归属生效。 | 页头删除；权限变更弹窗保留“按当前客户归属生效”。 | 功能介绍与生效边界应拆开，把后者放在发生变更的位置。 |
| C30 / P2 | [CustomerHubWorkspace.vue](../../frontend/src/views/customer_hub/CustomerHubWorkspace.vue#L34):34 | 按最近更新时间排序 · 权限范围由方舟统一控制 | 保留排序控件或“最近更新”排序标识，移除权限机制说明；两个出现位置一并处理。 | 排序需可识别，泛化权限说明无须反复展示。 |
| C31 / P2 | [SubmitRequest.vue](../../frontend/src/views/design/SubmitRequest.vue#L16):16 | 填写拍摄需求信息，日期无冲突时直接进入排期，有冲突时进入审批流程 | 删除“填写拍摄需求信息”；排期分流说明移至日期检查结果：“无冲突，将直接排期”/“存在冲突，提交后进入审批”。 | 把通用介绍替换成与当前输入相关的结果反馈。 |
| C32 / P2 | [CustomerMediaWorkspace.vue](../../frontend/src/views/design/CustomerMediaWorkspace.vue#L83):83 | 文件还未上传。每行显示的是加入清单时选中的客户标签。 | 保留“文件尚未上传”；标签绑定说明放在列表标题或标签修改入口。 | 上传状态必须保留；重复解释每行布局的文字可移位。 |
| C33 / P2 | [OrderIntelligence.vue](../../frontend/src/views/order_intelligence/OrderIntelligence.vue#L73):73 | 复购订单数按订单计数，复购金额使用订单 amount_usd | 复购订单数按订单统计；金额为订单美元金额。完整口径放指标帮助。 | 保留统计含义，删除程序字段名。 |
| C34 / P2 | [SalaryWorkbench.vue](../../frontend/src/views/salary/SalaryWorkbench.vue#L333):333 | 还有必须处理的异常。带着它们往下走，算出来的工资是错的—— 而少扣的钱不会有人来投诉。 | 请先处理阻断异常，再计算工资。 | 保留阻断原因与下一步，删除训诫式、情绪化解释。 |
| C35 / P2 | [OperationsCenter.vue](../../frontend/src/views/system/OperationsCenter.vue#L73):73 | 当前实例与跨服务器运行单元的集中清单 | 删除该区块副标题；保留实例名称、运行状态、探测时间和故障信息。 | 表格本身表达清单用途。 |
| C36 / P2 | [InspectionEvents.vue](../../frontend/src/views/shipping/components/InspectionEvents.vue#L4):4 | 暂无操作记录，历史记录不补造。 | 暂无操作记录 | “历史记录不补造”是实现约束；如确有历史覆盖缺口，用可核实起始日期说明。 |
| C37 / P2 | [StationQuickNav.vue](../../frontend/src/views/shipping/components/StationQuickNav.vue#L15):15 | 点击序号，直达对应产品明细 | 控件名称足够明确时删除；为序号按钮提供“跳至第 N 项产品”的可访问名称。 | 去掉点击教学，同时确保图形控件仍有名称。 |
| C38 / P2 | [CollectionView.vue](../../frontend-portal/src/components/CollectionView.vue#L64):64 | Explore your collection, in the names and shades you know. | 删除；保留客户名称、商品名称、规格与筛选。 | 交易工作区的装饰性介绍与主任务无关。 |
| C39 / P2 | [OrdersView.vue](../../frontend-portal/src/components/OrdersView.vue#L89):89 | Every request, every detail, in one place. | 删除；保留 Requests 标题、状态和查询入口。 | 重复概括列表功能。 |
| C40 / P2 | [CheckoutView.vue](../../frontend-portal/src/components/CheckoutView.vue#L56):56 | YOUR NEXT CHAPTER | 移除交易页装饰性眉题；保留 Checkout / Request received 等实际步骤与状态名称。 | 装饰文字与操作状态争夺注意力。 |
| C41 / P2 | [SelectionPanel.vue](../../frontend-portal/src/components/SelectionPanel.vue#L22):22 | Products you add appear here. Adjust quantities before you finish. | 仅空选择时显示“Your selection is empty.”并提供返回目录入口；非空时删除说明。 | 已有商品与数量控件足以表达操作。 |
| C42 / P2 | [CheckoutView.vue](../../frontend-portal/src/components/CheckoutView.vue#L88):88 | Current product names, pricing and delivery details returned by the server. Review any changes before submitting. | Review current products, prices and delivery details before submitting. | 保留提交前核对，去掉 server 实现细节。 |
| C43 / P2 | [i18n.js](../../frontend/src/views/customer-image/i18n.js#L38):38 | Upload your brand logo to quickly preview it on this product. | 缺少商品真实描述时不渲染 fallback 段落；上传操作指引只在上传区保留，中英文同步。 | 每张商品卡重复同一段操作说明，挤占真实商品信息。 |
| C44 / P2 | [index.html](../../frontend/public/customer-media/index.html#L70):70 | Browse and download your product photos and videos by tag and delivery batch. | 删除列表功能介绍；保留批次、标签、文件名与下载控件。 | 筛选和下载动作已经由布局与控件说明。 |
| C45 / P2 | [login.html](../../frontend/public/m/login.html#L104):104 | 请输入您的账号信息 | 删除；保留账号和密码标签、登录按钮、验证错误。 | 与登录表单重复。 |
| C46 / P3 | [scan.wxml](../../miniprogram/pages/scan/scan.wxml#L47):47 | 点击扫描工艺流转卡 | 与空态“扫描工艺流转卡开始报工”合并为一处；保留扫描按钮和卡片类型。内贸扫描页同样处理。 | 高频扫描页无须重复教同一个动作，且不能丢掉卡片类型区别。 |
| C47 / P3 | [LoginScreen.kt](../../pda-reporting/app/src/main/java/com/leshine/pdareporting/LoginScreen.kt#L53):53 | 使用方舟账号登录，报工记录仍归入本人 | 使用方舟账号登录；报工人身份在登录后页头持续显示。输入项补持久标签。 | 登录说明可缩短；字段当前依赖 hint，不能继续删减身份与控件辨识信息。 |
| C48 / P3 | [index.html](../../frontend/public/6010/index.html#L432):432 | 这里汇集顾客常见问题、价格信息、洗护售后和店员讲解话术。 | 删除页面目录式说明，保留产品特点；语音按钮命名“听产品介绍”。 | 产品正文是内容，页面布局复述才是冗余；不得一起删掉产品事实。 |
| C49 / P2 | [TaskCenter.vue](../../frontend/src/views/task/TaskCenter.vue#L12):12 | 方舟开发需求与个人事项 · 仅本人可见 · 导航栏悬停 + 可随手记 | 保留“仅本人可见”；功能介绍删除，快捷入口说明放到入口自身。 | 隐私范围有用，页面功能和布局说明可拆除。 |
| C50 / P2 | [TrainingEditor.vue](../../frontend/src/views/training/TrainingEditor.vue#L59):59 | 把手头材料全丢进来——现场拍的 PPT 照片、PDF 讲义、钉钉闪记转写的文字、自己的零散笔记。AI 按模板起草，你只负责下一步校对。 | 上传照片、PDF 或笔记，生成培训初稿。保留后续人工校对要求和格式限制。 | 长段鼓励性教学可缩为操作目的，不能删除 AI 草稿需核对的责任边界。 |

## 必须保留的内容与可缩短方式

| 范围 | 必须保留 | 合理的优化方式 |
| --- | --- | --- |
| 共用列表反馈 | FilterBar 的条件未生效、ListPageStatus 的旧数据/失败重试 | 只在对应状态出现；不能删后让用户误认已刷新成功 |
| 订单/回款/发货 | 商品款与运费口径、预付款与定金用途、实际到账与登记中、结果不确定先核对原单 | 放在金额或提交动作旁；只压缩重复背景，不改变金额含义和恢复路径 |
| 库存 | 镜像时间、未知映射、已占用/已扣减的库存边界 | 状态标签加一句当前原因；“待核对”不能改成“0”或被隐藏 |
| 薪资/战报/经营分析 | 参数差异、统计周期、分母、样本门槛、不可跨组相加、待核对 | 指标名包含币种/单位；完整算法放可点击展开的口径区；阻断和覆盖不足持续可见 |
| 客户与 Agent | 草稿/候选/已采纳、资料不足、来源证据、人工审核、没有对外发送 | 避免抽象实现词，保留真实状态；不要用一句“已完成”抹平区别 |
| 门户权限与站点配置 | 下单能力、账号变更生效范围、会话撤销、报价失效、客户将看到的内容 | 放到变更确认处，摘要与完整条款都可读；重要后果不能仅悬浮出现 |
| 客户下单 | 报价有效期、库存未预留、费用未确认、提交结果不明及原请求编号 | 与提交/恢复操作同屏显示；装饰眉题可以删，交易条件不删 |
| 上传/AI | 格式、大小、数量限制、数据将传第三方、成本/额度、内容需校对 | 一处简短限制行；异常时再展开具体原因，不重复三遍上传指引 |
| 表单/控件 | 表单 label、按钮名称、单位、必填、aria-label 与焦点可见性 | 占位符只举例，不代替标签；图标操作保留可访问名称和触屏可理解入口 |
| 静态名片/试戴营销页 | 商品描述、FAQ、条款、洗护、试戴非真实效果、示例数据标识 | 不将全部段落视为辅助文案；只删“此页包含哪些区域”和重复点击教学 |

## 各业务域的处理方向

主站的每个导航入口都在 `pages.csv` 中；下表按域说明处理方向。未单列优化项的域仅表示本次未确认可直接删的高置信冗余，不代表在线各状态通过。

| 域 | 处理方向 |
| --- | --- |
| 工作台 / 公告 / 个人任务 | 删除入口和页头同义解释；保留未读、自动保存、隐私范围 |
| 人员 / 主管 / 客户归属 / 提成 / 回款同步 | 保留身份、导入条件、归属及核算口径；不因文字少而删字段名 |
| 客户经营 / 智能获客 / Agent | 删泛化目标宣言；分清研究结果、候选档案、真实行动和外发状态 |
| 订单 / 价格 / 回款 / 发货检验 | 先删页头与实现字段名；同步和资金异常说明作为保护项保留 |
| 内贸 / 半成品 / 生产 / 库存 | 单位、SKU/逐件/批次区分、调整后果保留；教学句靠近对应操作 |
| 售后 / 薪资 / 战报 / 订单情报 | 删除口号，压缩情绪化描述；审批、赔付与统计口径不能丢 |
| 素材 / 设计预约 / 客户素材 / 生图 / AI 对话 | 空态只保留明确下一步；格式限制、公开范围、费用、人工校对按需出现 |
| 洞见 / 知识 / 培训 | 页面功能说明可删；文章、报告、培训正文是内容，不属于冗余微文案 |
| 物流 / 备货 / 结汇 | 保留数据时间、预测/测算边界、失败恢复和操作主体；不删到暗示保证结果 |
| 系统 / 权限 / 集成 / 报表 / 治理 | 技术词仅保留管理员确实需要的字段；密钥及授权后果不可隐藏 |
| 色彩 / 库存色块图 | 移除未兑现工期；SSO 内部页面另行核验 |
| PM 协作站 | 删除“3 秒看懂”等设计自评；保留版本行为、凭据禁传和任务阻塞原因 |
| 客户门户 / 公开库存 / 静态客户素材 | 精简交易页口号和功能复述；保留 SKU 信息、库存时间、条款及动作回执 |
| 小程序 / PDA / 平板壳 | 高频扫描指引只留一处；保留身份、网络/提交状态和撤销后果；设备上另做触控验收 |

## 实施验收清单

1. 每项变更检查“删后是否仍知道是什么、怎么操作、结果如何”；不要设统一减字比例。
2. 逐入口核对普通、空、加载、读取失败、无权限、表单错误、提交中与结果不确定状态。文案按状态显示，不用长段常驻教程覆盖所有情况。
3. 桌面与窄屏各复核首屏：删除文案后同步删除空容器间距；标题与主要操作保持相邻，控件名称仍完整。
4. 触屏和键盘必须可读取必要说明；重要条件、费用、数据披露和不可逆后果不依赖 hover。
5. 普通文案改动用受影响前端构建和页面回看。若改变条件展示或错误/恢复分支，补有区分力的状态回归测试，尤其是资金、库存和请求去重保护。
6. 当前只交付方案。实际修改和部署分开核验；源码已改不能写成生产已优化。

## 证据文件

- [逐入口覆盖清单](assets/2026-10-23-ui-copy-audit/pages.csv)：所有登记入口、源码、直接命中的优化项和验证边界。
- [文件清单](assets/2026-10-23-ui-copy-audit/files.csv)：扫描文件、节点数、候选数、SHA256。
- [具体优化项](assets/2026-10-23-ui-copy-audit/findings.csv)：位置、原文、建议与原因，可用于后续实施分批。
- [完整模板文本索引](assets/2026-10-23-ui-copy-audit/text.csv)：包括必要标签；只能作为索引，不是批量删除列表。
- [原生端文案索引](assets/2026-10-23-ui-copy-audit/native-copy.csv)：PDA/平板壳的源码线索。

验证：所有优化项原文与本地源码匹配；所有入口文件存在；规则提交已独立核对远端 main。保留原主目录 69 个脏文件的 SHA256 备份，并逐一确认内容未变。在线截图、全角色验证、设备验收以及外部子应用内容尚未完成。
