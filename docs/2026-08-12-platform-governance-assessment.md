# 莱莎方舟平台全面梳理与治理评估

> 评估日期：2026-08-12
>
> 评估范围：主站前后端、RBAC、APScheduler、独立 MCP/Connector/Agent、云端同步任务与 UI 设计一致性
> 本轮已落地：运行与自动化中心、权限矩阵中文归组、全局表格/按钮设计基线、P1 列表规范门禁、任务运行历史与云实例主动心跳

## 一、结论摘要

平台业务能力已经覆盖经营、订单、售后、生产、营销、设计、知识与系统治理等主要场景，领域拆分和权限三层防线总体成熟；但系统已经从“一个 FastAPI + Vue 后台”演进为跨办公室 Windows、新加坡云、北京云、SaaS 和 Agent 进程的分布式运行面，原有依赖 runbook、SSH、NSSM/systemd 和日志排查的管理方式已经不足。

本次评估结论如下：

1. **必须建设可视化运行中心，且已完成第一阶段开发。** 第一阶段以可观测和安全边界为主：集中展示当前实例、定时任务、MCP、OKKI、Shopify、OpenClaw、WhatsApp 等运行单元；只允许管理员控制当前进程内的白名单 APScheduler 任务，不提供任意 SSH/shell/环境变量编辑能力。
2. **权限中英文混杂属于结构性问题，已修复当前缺口。** 原因不是数据库中文 label 缺失，而是权限矩阵另维护一份前缀中文名和分组，近期开出的 6 个领域未同步，导致进入“其他”分组并显示英文兜底。本轮补齐中文归属、中文动作名和分组回归测试。
3. **UI 设计系统的列表规范已形成可执行门禁。** 106 张 Element Plus 表格已统一 `list-table + border`、移除 stripe/居中内容/固定内容列/小号按钮；业务视图层 `transition: all` 已清零。裸色值和超长页面按文件生成只能下降的基线，独立主题保留可审计例外。
4. **云端服务已具备统一事实源协议。** `ark_runtime_instances/heartbeats` 接收 Shopify、OpenClaw、MCP 等实例级机器凭证心跳；OpenClaw 侧车和通用 systemd/cron 上报器已实现。生产实例需在部署时分别下发 token 才会出现在页面，主应用不持有 root/SSH 权限。
5. **系统整体可继续迭代，但发布前必须完成运行中心部署配置、权限 seed 刷新与云端健康接入。** 第一阶段控制面已经具备代码基础；第二阶段重点不是继续增加“重启按钮”，而是建立统一心跳、执行记录、告警和责任人制度。

## 二、功能与运行面清单

### 2.1 前端功能域

主站当前有 30 个一级视图目录、179 个 Vue 页面/子组件，主要领域如下：

| 领域 | 主要能力 | 运行特征 |
|---|---|---|
| 工作台 | 个性化指标、待办、快捷入口 | 主应用 |
| 人员/客户/提成 | 员工属性、主管关系、客户归属、提成批次、回款 | 主应用，核心经营数据 |
| 智能获客 | 获客模型、搜索任务、公海背调、客户池 | 主应用 + OpenClaw/Agent |
| 订单/售后 | 发票、价格、OKKI 推单、采购节明细、经营决策、售后单/SOP/分析 | 主应用 + OKKI |
| 物流/备货/生产 | 运单、OCR、日报、安全库存、生产订单、工序路线、报工 | 主应用 + 多个 scheduler |
| 内贸/薪资 | 内贸订单全流程、薪资档案/规则/月度批次 | 主应用，高敏数据 |
| 展会/名片 | AI 试戴、门店/额度、线索、名片、采购节大屏 | 主应用 + 北京展会实例 + 静态站 |
| 洞见/培训 | 情报采集/日报/速览、案例、周会、客户机会/雷达、培训 | 主应用 + AI + scheduler |
| 设计/客户生图 | 设计预约、甘特图、AI 生图、AI 对话、客户效果图门户 | 主应用 + 队列 worker |
| 素材/色彩 | 素材库、收藏、统计、标签、色板、混色、趋势 | 主应用 + MCP + scheduler |
| 知识/报表/治理 | 企业知识库、报表中心、概念治理 | 主应用 + MCP |
| 系统管理 | 用户、角色、字典、AI、MCP token、外部绑定、WhatsApp、运行中心 | 主应用 |

另有独立 PM 协作站、微信小程序、展会 kiosk、客户生图公开门户、采购节静态大屏等非标准 MainLayout 表面，应保留各自设计语言，不强行套用主站列表模板。

### 2.2 后端领域与后台任务

后端 `app/` 有 40 个一级目录。APScheduler 注册目录定义了 20 个稳定任务 ID，覆盖原 18 项业务任务以及：

- 设计拍摄提醒；
- 物流日报、暂存扫描、在途轮询；
- 售后通知重试；
- 采购节事件监控与日报；
- 设计生图、客户生图与客户生图清理；
- 行业情报日报、AI 工具速递、情报速览；
- 安全库存日报；
- 社媒发色采集、发色销量聚合；
- WhatsApp 自动同步（可选）；
- 智能获客公海日批次（可选）。
- 云端实例心跳巡检；
- 运行历史保留期清理。

现有优点：固定 job id、主实例开关、时区、失败/错过钉钉告警、`max_instances/coalesce` 等基础设施已经具备。原缺口：没有页面状态、没有上次执行结果快照、没有责任归属、可选任务未注册时不可见、运维只能查服务日志。

### 2.3 分布式运行单元

| 运行单元 | 当前管理方式 | 本轮状态 | 目标纳管方式 |
|---|---|---|---|
| 方舟主应用 / MCP 网关 | Windows NSSM + FastAPI | 平台管理 | 运行中心直接读取 |
| APScheduler 20 项 | 主应用 + 数据库 | 已集中纳管 | 实时状态 + 有界控制 + 90 天执行历史 |
| WhatsApp Connector | 独立 Node 进程 | 可配置健康探测 | `/health` + 账号同步指标 |
| 社媒客户 MCP | 新加坡 systemd | 公网 `/health` 实测 200 | 健康、版本、依赖更新时间 |
| OKKI | 外部 SaaS | 当前只能判断配置完整性 | 增加无副作用 API 探测与最近同步记录 |
| Shopify 同步 | leshine.work 云端任务 | 当前仓库无运行定义，标记未纳管 | 迁入仓库或加 heartbeat sidecar |
| OpenClaw 销售 Agent | stdio MCP/外部执行器 | 心跳代码与部署接入已完成 | Agent 注册、心跳、当前版本、最近任务 |
| 北京展会实例 | systemd，scheduler 关闭 | 应显示应用副本 | 实例心跳，明确禁止调度双跑 |
| 新加坡 Nginx/frps/静态站 | systemd/Nginx | 本轮只读 SSH 不可用 | node agent/HTTP heartbeat，不依赖开发机 SSH |

## 三、问题清单与优先级

### P0 / 必须执行

#### P0-1 缺少统一运行与自动化控制面 — 已完成第一阶段

影响：无法快速回答“哪个实例在跑 scheduler、某任务是否注册、上次是否失败、Shopify/OpenClaw 是否纳管”；多实例场景存在任务双跑或无人运行风险。

已落地：

- `/api/operations/overview`：实例、scheduler、任务和服务清单；
- `/api/operations/jobs/{job_id}/{run|pause|resume}`：当前进程、白名单任务、有独立管理员权限的有界控制；
- 任务运行事件内存快照：开始、完成、失败、错过、并发跳过与并发实例数；
- 外部服务并发健康探测，超时 3 秒，20 秒单飞缓存，展示地址仅保留 origin，探测主机受 allowlist 约束；
- `/system/operations` 响应式可视化页面，30 秒自动刷新；
- `operations:read` / `operations:admin` 权限拆分；
- 任务领域与责任人目录。

安全边界：没有远程 shell、SSH、任意 URL 输入、密钥展示或环境变量在线编辑；所有控制需二次确认并持久审计。“立即执行”直接提交一次运行，不改变周期任务锚点；暂停策略跨重启保持。

#### P0-2 权限归组漂移与英文兜底 — 已修复

量化证据：161 个当前/历史 seed code 中，权限矩阵缺少 `ai_chat`、`festival_order`、`knowledge`、`order_intelligence`、`salary`、`system/operations` 等近期前缀；未知前缀直接显示英文。

已落地：

- 补齐中文名称和业务分组；
- `read_all/self_read/sync/review/audit/print/recharge/invoke` 中文显示；
- 系统分组更名为“系统 · 接入与运维”；
- 新增回归测试，锁定近期领域不得重新掉入英文兜底。

后续建议：将 `display_module/module_group/action_label` 作为后端权限元数据输出，前端只消费，彻底消除双份配置。

#### P0-3 全局 UI 基线与设计规范冲突 — 已修复

修复前：全局表头 12px + uppercase + 字距、内容 12px；按钮 8px 圆角、`transition: all`。规范要求表头/内容 13px、非 uppercase，工具栏按钮 36px/12px 圆角，动效只过渡必要属性。

已修复：全局表头/单元格 13px、取消大写和字距；默认按钮 12px；精准过渡；补 `prefers-reduced-motion` 降级；裸颜色替换为 token。

### P1 / 一个月内治理

#### P1-1 历史列表页统一 — 已完成

修正早期会误把 `min-width` 计为固定宽度的扫描口径后，识别出业务视图及共享组件中的 106 张表。现已统一全部表格的 class/border，固定内容列改为 min-width，移除居中、stripe 与小号按钮；门禁范围覆盖两个前端的完整 `src`，不再只扫描 views。

`scripts/audit_frontend_ui.py` 已接入 `check_conventions.py`，任何回退都会阻断门禁；`normalize_list_tables.py` 作为幂等修复工具保留。桌面/窄屏仍需在每个业务迭代中用真实数据回归溢出、固定列重影、分页和空态。

#### P1-2 设计 token 增量治理 — 门禁完成、存量冻结

两个前端完整 Vue 源码现有 1027 处裸 hex、7 处共享组件 `transition: all` 与 5589 行超长文件债务，均按文件写入 `scripts/ui_debt_baseline.json`，只能下降、不能新增；业务视图层错误的 `transition: all` 已从 19 处清零。订单经营、发票、售后、薪资等高风险模块无新增裸色值；展会 kiosk、登录/成功动效等独立主题保留现状并受基线约束。

后续按模块把裸色值映射到 `tokens.css` 并拆分超长页面，每次降低 baseline；不得通过提高 baseline 绕过门禁。

#### P1-3 任务执行结果持久历史 — 已完成

新增 `ark_job_runs`，按 instance/job/planned_at 的哈希键幂等写入开始、成功、失败、错过和并发跳过；异常仅保存类型摘要，不保存异常消息/traceback。页面显示最近 30 次并可筛选失败状态，默认保留 90 天。

#### P1-4 云端服务主动心跳 — 已完成代码与部署模板

所有独立运行单元使用同一最小契约：

```json
{
  "service_id": "openclaw-sales-agent",
  "instance_id": "...",
  "version": "git-sha",
  "status": "healthy",
  "started_at": "...",
  "last_activity_at": "...",
  "capabilities": ["sales_search"],
  "dependencies": ["ark-api"]
}
```

已落地绑定 `service_id + instance_id` claim 的 Bearer token SHA-256 白名单、实例级限流与数量上限、每 60 秒上报、连续 3 个周期降级、24 小时自动退役、单次钉钉告警和 7 天心跳保留期，以及 OpenClaw 原生上报和通用 Python/systemd 模板。服务名、环境、能力与依赖以服务端 claim 为准，客户端不能伪造；页面不能直接持有云服务器 root 权限。

### P2 / 随迭代治理

- 前端构建仍有三个 900KB~1.1MB vendor chunk，影响弱网首屏；应拆 Element/ECharts/Stimulsoft 加载路径并用真实产物分析器验证。
- 全局设计系统与特殊主题边界需要文档化：主站列表、Liquid Glass、登录页、expo kiosk、客户门户、PM 子站各自允许的 token 范围。
- `README` 功能模块数量与 `CLAUDE.md`/实际代码存在时间差，应由导航/路由扫描自动生成附录，减少人工维护漂移。
- 仓库规范引用的 `.claude/rules/checklists.md` 和 `.wolf/cerebrum.md` 在当前版本不存在，应决定恢复还是清理指针。

## 四、统一管理目标架构

### 4.1 分层原则

1. **事实层**：每个实例/服务/任务有稳定 ID、版本、环境、责任人、健康与最后活动时间。
2. **观测层**：HTTP health/heartbeat + scheduler listener + 统一执行历史；密钥不入响应。
3. **控制层**：只提供预定义动作，不接收 shell；本进程任务可直接控制，远程服务由受限 agent 执行 allowlist 动作。
4. **审计层**：谁在何时对哪个运行单元执行什么动作、结果如何，必须持久化。
5. **告警层**：健康状态变化触发钉钉，页面只作为查看与处置入口，不能依赖人一直盯屏。

### 4.2 第二阶段完成项与后续建议

- 已新增 `ark_runtime_instances`、`ark_runtime_heartbeats`、`ark_job_runs`；`ark_operation_audits` 与 `ark_scheduler_job_policies` 已在第一阶段完成；
- 已完成 OpenClaw 稳定 instance id、进程启动后与每分钟上报；停止状态由连续心跳缺失判定；
- 已提供 Shopify/OKKI/MCP 通用心跳 sidecar；后续把同步任务统一包成 job runner，补充 checkpoint/affected_count；
- 已提供最小权限 systemd 心跳单元；是否增加固定服务 `status/restart` 代理须经后续安全评审，当前页面不开放远程控制；
- 已完成实例清单、最近失败和运行耗时；告警确认、趋势图和 runbook 深链列入后续迭代；
- 远程重启必须 `operations:admin` + 二次确认 + 审计 + 冷却时间，数据库迁移、部署、环境变量修改继续走 deploy/runbook，不进入页面。

## 五、已完成变更与验证

### 已完成

- 运行与自动化中心后端领域、API、权限、导航与前端页面；
- 20 个任务中文目录、责任归属、注册/未注册状态、90 天运行历史、持久控制审计与暂停策略；
- 社媒 MCP、WhatsApp、OKKI、Shopify、OpenClaw 等服务清单；
- 权限矩阵近期模块中文化、业务归组与动作中文化；
- 全局表格/按钮设计基线修复；
- 106 张表格统一与 UI 存量债务只能下降门禁；
- OpenClaw 与通用云 cron/systemd 主动心跳；
- 后端与前端回归测试。

### 验证证据

- 生产公开健康：`https://leshine.work/health` 返回应用 ok、数据库 connected；
- 社媒 MCP：`https://leshine.work/mcp/social-customer/health` 实测 HTTP 200；MCP 根路径匿名访问 401，主 MCP 入口非协议请求 406；
- 运行中心桌面 1280×720：无页面级横向溢出，5 个服务卡/任务表正常；
- 运行中心窄屏 390×844：指标与服务卡单列，无页面级横向溢出；
- 计算样式：表头 13px、非 uppercase、字距 normal；按钮 36px、12px 圆角；
- 浏览器控制台：零 error/warn；
- 前端全量 Node 测试：279/279 通过；
- 前端 production build：通过（保留既有 vendor chunk 体积告警）；
- 增量约定检查：通过；
- 后端针对性测试：50/50 通过（operations、调度注册、心跳脚本与权限）；OpenClaw 13/13 通过；
- 后端全量测试：2522 passed、2 skipped、7 failed。7 项均为当前 macOS 对仓库既有 Windows 专用前提的环境差异：Windows 盘符逃逸判断 1 项、采购节浏览器/字体 4 项、发票 Windows 字体/PDF 2 项；本轮 operations 与调度注册用例无失败。部署到 Windows 前仍须按 runbook 做字体预检，不能把这 7 项记为产品回归通过。

## 六、上线操作

1. 合并代码，确认 `alembic heads` 唯一为 `111_runtime_observability`，备份后执行 `alembic upgrade head`，再按标准部署流程重启后端，使权限 upsert seed 生效；
2. 在角色权限页分配 `operations:read`，只向受信任运维管理员分配 `operations:admin`；
3. 办公室主实例保持 `SCHEDULER_ENABLED=true`，北京/其他副本保持 false；
4. 配置健康地址，并为 Shopify、OpenClaw、MCP 等每个实例分别生成心跳 token；后端按 `service_id + instance_id` claim 写入 `OPERATIONS_HEARTBEAT_TOKEN_HASHES_JSON` 的 SHA-256 与固定展示元数据，明文按 runbook 下发到云实例；
5. 上线后验证运行中心中主实例显示“调度主实例”、副本显示“应用副本”，任务注册数与启动日志一致；
6. 使用无副作用测试任务验证一次暂停/恢复；“立即执行”需选择可安全重复的幂等任务，不在首次上线时触发发消息、推单或 AI 付费任务。

## 七、评估边界

- 本轮没有读取任何服务器环境变量、密钥、业务数据或账号信息；
- 新加坡 SSH 因公钥不可用、北京 SSH 因主机指纹未建立而没有完成实时 systemd/cron 清点，未绕过校验；相关运行单元按仓库的 systemd 脚本、runbook 与公开健康接口评估；
- 未对生产执行同步、暂停、恢复、重启、权限修改或数据写入；
- UI 债务数据来自静态扫描，表示候选问题规模，不代表每一处都是缺陷；独立主题和业务必要固定列需人工复核。
