# 莱莎方舟平台 项目交接清单

> **版本**：v1.8
> **最后更新**：2026-09-02
> **项目状态**：运行中，持续迭代
>
> ⚠️ **发布状态提醒（2026-09-01 核实）**：生产数据库已到唯一 head `127_domestic_route_rules`；办公室 `CommissionSystem`、北京 `ark-backend`、新加坡 `okki-sync` 和 `social-customer-mcp` 均已恢复运行。北京后端与社媒 MCP 健康检查返回 200；办公室后端直连主库成功。办公室登录初次失败的根因不是网络或密码，而是低权限账号缺少跨库读权限；已为 `ark_app@%` 固定 `commission_db.*` DML + `lsordertest.*` SELECT，并从运行中北京实例实际读取 `lsordertest.user_rel_team` 通过。为保留既有管理员回款日期修复能力，另授予 `okki_receipts.collection_date` 列级 `UPDATE`，不扩大为业务库 DML。`root` 仍只用于受控迁移，不进入生产 `.env`。**「已合入 main」不等于「已上线」**，未在本页明确标注生产验证的功能仍不能当作已发布。

> 🚧 **内贸会员与优惠价（2026-09-02，功能分支开发完成待最终验收/合并）**：分支 `codex/domestic-membership-pricing` 实现最近一次充值派生银卡/黑卡/至尊会员、共享原价维护、截图 131 条原价种子、固定会员价与等级立减、服务端权威批量报价、建单/草稿提交/换客户的报价确认与持久幂等、订单价格快照及 Excel 原价/优惠价导出。数据库采用 130 兼容回填 + 131 最终约束两阶段迁移；生产仍在 127，尚未执行 129/130/131，也未做真实 MySQL 停写演练，因此不能视为线上可用。发布必须先在隔离 MySQL 完整演练升降级和并发门禁，再停止所有内贸 writer、等待在途事务排空后执行迁移、部署新版并核对会员/原价/订单快照。

> ✅ **内贸条件工序（2026-09-01，生产已切换）**：`main` 已实现内贸 `required / decision / optional` 三类规则、按具体单件的分流与自动/人工跳过审计、全后序撤销保护，以及 Web/小程序/PDA 共用的 outcomes 契约；真实 MySQL 已执行并验收 `127_domestic_route_rules`。生产路线 ID 8“头套网帽（递针）”与 ID 10“发片网底（递针）”均为启用状态、18 道工序，各写入相同的三个 decision 和一个 optional 条件契约；稳定编码/跳过目标分别为 `dandong → 李晓宏手钩+递针`、`lixiaohong → 丹东收货+发货`、`needle → 不跳过`、`no_needle → 李晓宏递针`、`qualified → 毛坯维修`、`repair → 不跳过`。生产 apply 已把 cap 的 5 条工艺映射/3 个产品全部绑定路线 8，把 piece 的 5 条工艺映射/4 个产品全部绑定路线 10，错绑均为 0；无需补建映射。既有 cap/piece 各 4 条订单明细仍全部保留在旧通用路线 ID 7，未删除、未重建。此次按亮哥明确指令在服务保持运行、相关工艺无业务写入的窗口在线执行；默认运维规则仍是停止全部内贸及路线配置写入后再 apply，不能把本次特批当作常规操作。

> ✅ **统一客户经营重构（2026-08-31，生产已切换）**：迁移 126 及客户主档、身份解析、事实证据、档案版本、Agent 上下文、公海背调、搜索任务、客户池、机会台、经营雷达、受控提案、MCP 只读工具和五个前端入口已合入 `main` 并部署。方舟是唯一真相源；公司名可空且不作身份键；外部来源经 Agent 事实化后进入方舟，消费 Agent 只读方舟。旧 `ark_sales_companies/contacts/research_*`、旧公海任务和旧客户画像运行时已退役。迁移冻结 39 张表、778 个字段，隔离 MySQL 8.4.11 严格模式与生产物理契约均通过，表/字段空备注为 0。生产切换库存哈希为 `74fa675c283fb105c6b113c502495b2b0c5c23605b377e2e00631c2c4fb65df7`；执行中暴露并修复了 canonical float 证据反序列化与 MySQL DATETIME 秒精度两项门禁缺陷，中间态经完整物理契约、Agent 闭包、目标画像、空抑制名单和 writer 权限恢复审计后晋级 `126`，恢复回执 SHA-256 为 `b24b81e8180e80423d6f904f78c81a027bf500e35e6e61d9786c208eeeecfdea`。办公室与北京实例均使用低权限 `ark_app`；完整权限边界是 `commission_db.*` DML + `lsordertest.*` SELECT，仅给主库 DML 会使登录在读取 `user_rel_team` 时失败。北京 `/health`、`/docs`、`/openapi.json` 返回 200，办公室标准部署已完成。

> 🚧 **外部站点订单发票接入（2026-08-26）**：功能分支 `codex/invoice-integration` 已完成 Phase 1/2 代码，包括迁移 125、Integration App 凭证管理、`/api/integrations/v1` 五个 REST 端点、严格金额校验、客户/产品解析、App 级幂等创建与结果恢复、后台「系统管理 → 站点接入凭证」以及 OpenAPI/TypeScript/Codex 接入材料。当前**尚未合入 main、尚未部署，迁移 125 尚未应用到真实 MySQL**，不能视为线上可用。后端全量已实跑 `3092 passed, 1 skipped`，前端接入专项 `39 passed` 且生产构建通过；这只证明当前代码与测试契约通过，不代表生产联调。下一步依次是：真实 MySQL 执行并核对唯一 head、两表/唯一约束/FK；重启 seed 后给管理员角色分配 `integration:admin`；签发一枚临时试点凭证；用脱敏样例验证 validate/create、相同内容幂等重放、改内容 409、超时后按 external_order_id 恢复以及全程不产生 OKKI 同步；最后吊销试点凭证并保留带明确试点标记的发票作为幂等审计记录。外部 REST API 不提供发票更新（update）、删除（delete）、作废（void）端点或提成（commission）字段；方舟内部删除需 `invoice:write` 且符合现有发票可见范围；已有 `xiaoman_order_id`、`sync_status=synced`/`sync_status=sync_uncertain` 或未恢复半成品库存时拒绝；允许时同一事务删除 ingest 与发票，释放 App + `external_order_id`，独立站同订单重新 POST，按首次创建返回 HTTP 201 并建立新的幂等记录。

> 🚧 **当前开发（2026-08-25）**：`codex/invoice-screenshot-import` 已实现 OKKI 订单截图 AI 字段提取、确定性客户/业务员/产品/SKU/来源订单核对、人工预览填入、签名预览凭证、同图/同订单防重和重复推送禁用；迁移为 `119_invoice_screenshot_src`。独立对抗审查已完成，其发现的预览来源可伪造、上传整体读入、无候选时定制产品入口不可达、非 USD 订单误关联和 OCR 订单名不一致问题均已加固；专项后端 54 例、前端专项测试和 Vite 构建通过。迁移 119 已在合并前改接 118，需重跑 `alembic heads/upgrade` 确认唯一 head。

> ✅ **功能分支完成（2026-08-25）**：`codex/semifinished-inventory` 已实现迁移 120/121 的半成品列表、产品解析关联与人工组成修正、按 g 下单/分批入库、实存/占用/可用/在制库存、生产购物车同步下单及生产发票的 OKKI 同步预占—出库—补偿恢复。线上迁移已到 121，产品同步结果为 794 个关联、233 个半成品、429 个待审核关联；待审核项不会自动下单或领料。详细规则见 `docs/requirements/2026-08-25-semifinished-orders-inventory.md`；尚未合入 main、发布前端或重启后端。

## 2026-08-26 AI 方案对话 · 四种对话方式

- **实现分支**：`codex/ai-chat-modes-20260826`。将旧四入口替换为深度思考、天赋挖掘、未知领域引导、寓言讲概念；规则文件化，点击不覆盖草稿、不自动发送。Skill 显示服务端确认的加载状态并可折叠预览；内置规则不占附件名额。历史方式固定，另开会话换方式；草稿、刷新、停止/重试与只读模式均保留对应边界。
- **安全与上下文**：首次发送在会话行锁事务内保存 SHA-256 规则快照。普通上传文件仍是数据；未知领域使用明确标注的网页适配版，原始 Skill 留作来源。模式上下文不受最近20条窗口影响，但超过200条/120,000正文字符或附件被截断时明确失败；重试不会读到原问题之后的消息。长度终止原因透传，报告被截断时明确提示回复“继续”。
- **数据库已应用**：开发/生产共用数据库已执行 `124_ai_chat_modes`，`alembic current` 为唯一 head；已核查 `ark_ai_chat_sessions.mode_snapshot` 是可空 JSON。原会话 NULL，不会被自动改成某种方式。
- **验证**：后端全量 `2974 passed, 1 skipped`（268.65秒；已有 warnings），ai_chat专项 `158 passed, 1 skipped`；前端 `aiChatState.test.mjs` 30项通过，Vite build通过，约定检查/差异空白检查通过。后端单独测试需预先导入 `app.invoice.models`，因现有 conftest 的半成品FK注册依赖；未为绕过问题修改生产代码。
- **独立审查**：修复普通请求幂等重放忽略模式、早期附件截断、历史重试读未来消息、旧会话加载覆盖新草稿、切新会话loading卡住、409版本冲突无法重载等问题，均有回归测试。
- **真实模型冒烟**：现有 `customer_ai_chat`/`claude-fable-5` 调用，四种方式分别成功返回（AI日志2421–2424）；深度思考先论证再问关键问题，天赋先介绍流程并进入第一轮，未知领域给盲区和候选问题，寓言给故事/解析/检验问题。全部为虚构验收素材，无真实个人访谈数据；未把万字最终报告效果当作已完整验证。
- **页面验收**：实际构建页面 + 真实ai_chat路由，使用内存SQLite、虚构用户和模拟模型完成四入口、草稿、文件预览/加载失败/重试、历史刷新、天赋免输入启动、长度提示、只读和移动端检查。检查平台真实导航/页签后修复高度计算与输入框裁切；390×844/390×500仅为响应式与键盘高度模拟，尚非实体手机键盘实测。临时脚本/截图在本分支 `tmp/qa-chat-*`，不发布到生产。
- **已合入并推送，服务器尚未部署**：2026-08-26 已同步远端更新，将功能重放到最新 main 并推送 `71597610`；重放后后端 service/router 50项、前端30项、Vite build与约定检查通过。办公室实例 `/api/ai-chat/modes` 实测仍返回404，证明服务仍是旧代码。服务器22/5985端口不可达，本机也没有 `D:\commission-system` 或 `CommissionSystem` 服务，无法远程执行生产脚本；需在办公室服务器运行 `D:\commission-system\deploy\deploy.bat`，再验证该端点、Skill快照预览、真实会话与手机键盘。
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
