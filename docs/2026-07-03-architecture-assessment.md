# 莱莎方舟平台 功能架构评估与改进文档

> **评估日期**：2026-07-03
> **评估范围**：后端（backend/app，221 个 .py，42,177 行）、前端（frontend/src，95 个 .vue + 44 个 .js，42,813 行）、提示词/知识管理体系（CLAUDE.md + .wolf/ + docs/）
> **评估方法**：两个独立 agent 对前后端做代码级勘察（文件行数、grep 抽查、一致性对比），主会话核对提示词资产与提交历史，成文后经独立 agent 对抗性审查修订
> **边界约定**：用户 <100 人、日活 ~20 人。不考虑大并发与深度安全加固，聚焦实用性、灵活性、稳定性、一致性、可扩展性，避免过度设计

---

## 一、总体结论

**平台整体是健康的，问题不在架构选型，而在"规范执行衰减"。**

19 个业务模块跑在一套 FastAPI 单体 + Vue 单页上，对 30 人规模是完全正确的架构，不需要任何"升级"（微服务、消息队列、Redis 都不需要）。真正的风险集中在三处：

1. **稳定性盲区**：11 个定时任务没有任何失败告警（全项目 0 处 `EVENT_JOB_ERROR` 监听），后台 job 挂了没人知道；**素材中台（定位是取代钉钉网盘）的文件存储和 uploads/ 目录单机单盘、零备份**；部署脚本是单向流程、无回滚路径。这三项是"本周就该修"的问题。
2. **一致性靠自觉、无检查点**：响应格式三套并行、`_ok()` 复制 8 份、`get_db` 定义 5 处、802 处硬编码颜色、13 个超 500 行未拆分的页面——**每一条都有明文规范，但最新写的代码仍在违反**（SalesCommission.vue 581 行、InvoiceManage.vue 852 行都是本周的新页面）。说明问题不是"缺规范"，而是规范只写在提示词里、没有可执行的检查。
3. **提示词资产超重且半失效**：CLAUDE.md 膨胀到 968 行（约 1.6 万 token 的每会话固定开销），规则被 API 清单淹没；.wolf 体系四个文件中只有 cerebrum.md 真正在产生价值（anatomy.md 覆盖 59/300+ 文件且 hits:0，memory.md 1848 行流水账无人回读）。

**各维度评分**（满分 10，按 <100 人内部平台的合理标准）：

| 维度 | 评分 | 一句话依据 |
|------|------|-----------|
| 功能完整度 | 9 | 19 个模块覆盖数据沉淀/办公自动化/AI 三大目标，功能密度远超同规模团队 |
| 架构选型合理性 | 9 | 单体 + 双库只读跨查 + NSSM，与规模匹配，无过度设计 |
| 后端代码一致性 | 5 | 响应信封 3 套、权限模型 3 套、session 管理 5 处重复定义 |
| 前端 UI 一致性 | 5 | 导航单一来源执行完美；但列表页零骨架复用、token 体系被 802 处硬编码绕过 |
| 稳定性保障 | 3 | 无调度告警、素材/上传文件零备份、部署无回滚、4 处吞异常；但有全局 exception handler 和生产配置校验 |
| 测试保障 | 4 | 71+ 测试集中在提成/设计预约；stock、production、tracking、asset 等零测试 |
| 可扩展性 | 8 | 领域模块模式成熟，invoice 新模块 8 文件即成型；service 层分离为将来 MCP 开放铺好了路 |
| 知识管理/提示词 | 6 | cerebrum Do-Not-Repeat 42 条实战教训是宝藏；但载体超重、四处重复、执行机制缺失 |

---

## 二、功能架构现状评估

### 2.1 对照四个核心目标

**目标 1：数据中台（沉淀业务/库存/询盘/订单/客户/技能/工艺数据）— 达成度 70%**

- 做得好：双库架构（commission_db 读写 + lsordertest 只读）是最务实的"中台"实现——不搬数据、只投影，WhatsApp/钉钉/ACCIO 询盘都采用"外部系统 → 本地投影表"模式，口径统一。67 张表覆盖了目标中列举的全部数据域。
- 缺口：**数据只是"存进来了"，还没有"治理起来"**。governance 模块（概念注册表）已建好但更像一个空壳工具——真正的口径问题（如 tracking 的钉钉昵称 vs 登录名不匹配、`salesperson_attribute` 的日期类型混杂）散落在 cerebrum 的教训里，没有进概念注册表。中台的价值在口径统一，建议把 governance 模块当作"已发现口径问题"的登记簿用起来，而不是等一次性大而全的建模。

**目标 2：办公自动化（一次录入、消灭线下表格）— 达成度 85%**

这是平台价值最高、完成度最好的部分。发票创建、提成批次确认流（confirming 状态 + 业务员反馈）、运单 OCR、生产报工小程序、打印工作台，都体现了"系统承担复杂性"的设计原则。遗留缺口主要在体验一致性（见前端部分）而非功能。

**目标 3：AI 能力接入 — 达成度 80%**

AI Provider/Preset/调用日志的三层设计非常好：业务代码一行 `chat(db, preset_name=...)` 即可调用，模型/密钥/参数全部后台可配，推理模型兼容、密钥加密、日志截断这些坑都已踩平。insight 的"采集库 → 选材 → 生成"分层管线也成型了。缺口：AI 调用全部走同步 `urllib`，个别在调度器事件循环内直接阻塞（见问题 B-S3）。

**目标 4：对外能力开放（MCP 库存服务、生图生视频）— 达成度：架构就绪**

现有"业务逻辑在 service 层"的约定正是为此铺路：将来 MCP server 只需作为一个**独立薄层进程**（或 app 内新领域模块 `app/mcp/`），直接 import 现有 `stock/sku_query.py`、`color/swatch_service.py` 等 service 函数暴露为 MCP tool，不需要动任何现有代码。**唯一前提**：service 层保持"不依赖 request 上下文"（当前基本做到），这一条应写进宪法。

### 2.2 结构性观察

**双轨结构（共享层 vs 领域模块）**：领域模块模式已明显胜出——15 个领域模块自包含、invoice 新模块 8 文件 1060 行即完整成型；共享层只剩提成域（commission/customer/employee/payment/supervisor）+ 两处与领域模块重叠的双份实现（report、short_link）。这不是要"大迁移"的问题，而是要**冻结**的问题（见改进 B-7）。

**单文件膨胀规律**：4 个 router 超千行（insight 1311 / asset 1255 / design 1010 / api/commission 1006）。膨胀原因一致：一个业务域的所有端点挤在一个文件。这在改到之前无害，但改到时是事故温床（cerebrum 里 `_get_user_id` NameError 500 事故就发生在 insight/router.py 的区块间）。

**做得好、应当保持的**（评估不能只挑刺）：

- `navigation.js` 单一来源：62 条路由全量注册、14 分组、权限门控完整、零游离页面——是全项目执行最好的约定
- 全局 exception handler + 生产环境启动校验（`_validate_production`）
- Alembic 迁移链 46 个、线性无分叉
- invoice 后端模块可作为新模块的标杆样板
- AI 调用链、短链服务、外部系统投影模式，抽象层次都恰当

---

## 三、问题清单汇总（按严重度）

### 严重（影响稳定性或正在扩散）

| # | 问题 | 证据 |
|---|------|------|
| S1 | **11 个定时 job 无失败告警**：无 `EVENT_JOB_ERROR` 监听，job 挂掉静默 | `schedulers/registry.py`，全项目 0 处 `add_listener` |
| S2 | **响应格式三套并行**：ResponseModel（约 8 个业务文件）/ 局部 `_ok()`（复制 8 份）/ 裸 dict（invoice、production、mini）。tracking 是手写 `{"code":200,...}` 字面量——格式合规但没用 helper | `ai/router.py:22`、`stock/router.py:45` 等 8 处 `_ok` 定义；`invoice/router.py:75` 裸 dict |
| S3 | **调度器事件循环内同步阻塞**：多个 async 包装的 job 内直接跑同步 HTTP / AI 管线。最重的是 insight 三个 AI 报告 job（分钟级阻塞），且排在 08:30/08:35/08:40 与物流日报、库存日报、拍摄提醒同档期，一次 AI 生成足以把其他 job 推迟甚至 missed | `registry.py:90` → `color/social_extract_service.py:48`；`insight/scheduler.py` 三个 async job 内跑同步 urllib AI 调用 |
| S4 | **前端组件内自建 axios 绕过全部拦截器**（401 跳转/loading/错误提示全失效） | `views/system/ExternalBindings.vue:78` |
| S5 | **设计 token 体系失效**：views 下 802 处硬编码 hex（54 个文件），tokens.css 仅 62 个 token | 热点：ShippingDailyReport(70)、CaseLibraryView(69) |
| S6 | **移动端是平行第二套代码库**：/m/index.html 1333 行，原生 fetch 重写素材域，与主站零复用 | `frontend/public/m/` |
| S7 | **素材存储与上传文件零备份**：runbook 备份策略只覆盖 RDS（腾讯云自动备份）、代码（git）、.env（手动）；`ASSET_STORAGE_ROOT=D:\WORKSOURCE` 的全部素材和 `backend/uploads/`（设计附件/头像/报告 HTML）单机单盘无备份。素材中台定位是"取代钉钉网盘"——盘坏即全量丢失 | `asset_service.py:24`、`docs/runbook.md` 备份章节 |
| S8 | **部署无回滚路径**：deploy.bat 是"拉最新→迁移→构建→重启"单向流程，无部署前留档；alembic 迁移的 downgrade 多数未实现。一次坏部署的恢复方案是空白 | `deploy/deploy.bat`，deploy/ 下 grep 无 rollback 逻辑 |

### 中等（影响可维护性，随迭代修复）

| # | 问题 | 证据 |
|---|------|------|
| M1 | 4 处危险的静默吞异常（`except Exception: pass`）。`polling_service.py:99` 最危险——轮询单票失败直接消失。（`color/social_extract_service.py:108` 的裸 `except:` 只是临时文件清理，无害，不计入） | `asset/asset_service.py:106`、`report/data_service.py:419`、`tracking/polling_service.py:99` 等 |
| M2 | 权限模型三套：`require_permission` / insight 自定义依赖 / dingtalk 仅登录、mini 登录即全通 | `insight/dependencies.py`、`dingtalk/router.py:27` |
| M3 | 配置盲区：`ASSET_*`、`XPOZ_TARGET_ACCOUNTS` 等 9 处直读 `os.environ` 未进 Settings；`ARK_AI_ENCRYPTION_KEY`、`SHORT_LINK_BASE_URL` 双份读取 | `asset/asset_service.py:24,501`、`ai/keyring.py:20`、`asset/router.py:966` |
| M4 | 测试结构性失衡：stock/production/tracking/asset/insight/color/report 零测试；commission 仅算法层 | `backend/tests/` 11 文件（含 conftest）1409 行 |
| M5 | 13 个 >500 行页面未拆 composable，且新页面（InvoiceManage 852、SalesCommissionDetail 732）仍在违反 | AssetUpload.vue 1270 为最 |
| M6 | 列表页零骨架复用：29 页各写分页、40 页各写表格；空态只有 27/40 覆盖；ElMessage 224 处散落无封装 | grep 统计 |
| M7 | `get_db` 重复定义 5 处；19 个文件直接 `SessionLocal()`（其中 3 个 router 两种混用） | `invoice/router.py`、`production/router.py`、`whatsapp/router.py` |
| M8 | report、short_link 两个域在共享层与领域模块各有一份实现 | `api/report.py` vs `app/report/`；`api/short_link.py`+`services/short_link.py` vs `utils/shortlink.py` |

### 轻微（记录在案，改到再顺手治理）

- 分页参数逻辑散落 40+ 文件（PageResponse 存在但没人用）
- 导出（Excel/PDF/HTML）逻辑分散 3 个区域各自实现
- HTTP 客户端 urllib / httpx（sync+async）三种用法并存
- 11 处独立上传实现、9 处独立详情抽屉
- `vuedraggable` 仅 1 处引用；vite 无 manualChunks（全量单包）
- Alembic 编号两个 `002_` 前缀 + 1 个 hash 命名混入
- `clients.js` 未登记 invoice/commission client（削弱可发现性）
- `SalesCommissionDetail.vue` 用 `h()` 内联渲染，与全站模板风格不一致

---

## 四、后端改进方案与实施步骤

> 原则：**止血 → 收口 → 随迭代治理**。不做大迁移、不引入新组件。

### B-1 定时任务失败告警（半天，收益最大，最优先）

问题本质：平台大量价值由后台 job 承载（日报、轮询、采集、同步），但 job 失败无感知——"稳定性"的最大缺口。

实施步骤：
1. `schedulers/registry.py` 中给 scheduler 注册监听。两个已知陷阱必须避开：钉钉 webhook 的实际 API 是 `get_webhook_sender().send_markdown(...)` 且是 **async 函数**（listener 是同步回调，直接调用会产生一个从未 await 的 coroutine，一条告警都发不出去——恰好复刻"静默失败"）；`EVENT_JOB_MISSED` 事件没有 `exception` 属性。参考实现：
   ```python
   import asyncio
   from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
   from app.dingtalk.webhook import get_webhook_sender

   def _on_job_event(event):
       if getattr(event, "exception", None):
           msg = f"⚠️ 定时任务失败: {event.job_id}\n{event.exception}\n{event.traceback}"
       else:
           msg = f"⚠️ 定时任务错过执行(missed): {event.job_id}"
       logger.error(msg)
       print(msg, flush=True)   # NSSM service.log 可见（已知坑：logger 不进 service.log）
       try:
           # AsyncIOScheduler 与主事件循环同环境，把 async 发送排进循环执行
           loop = asyncio.get_event_loop()
           loop.create_task(get_webhook_sender().send_markdown("定时任务告警", msg))
       except Exception:
           logger.exception("job error notify failed")

   scheduler.add_listener(_on_job_event, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
   ```
   落地前跑一次人为失败的 job 验证发送链路（见步骤 3），不要只看代码觉得对。
2. **审一遍全部 async 包装的 job**（不只 color）：`registry.py` 里 async 包装的有 `_scan_staging_job`、`_poll_active_job`、两个 color job，加上 `insight/scheduler.py` 的三个 AI 报告 job——后者在 async 函数内直接跑分钟级的同步 AI 管线，是最重的阻塞源。处理方式二选一：改为**同步函数注册**（APScheduler 自动放线程池），或在 async 包装内 `await loop.run_in_executor(None, sync_fn)`。insight 三个 job 优先。
3. 验证：手动触发一个必失败的临时 job，确认钉钉群收到告警、service.log 有 traceback；再看 08:30 档期各 job 的实际执行时间是否不再互相推迟。

### B-2 清理 5 处静默吞异常（半天）

对 M1 列出的 5 处逐一处理，原则：**吞掉可以，无声不行**——最低限度 `logger.warning("xxx failed: %s", exc)` + `print(flush=True)`（NSSM 环境约定）。`tracking/polling_service.py:99` 这类轮询场景吞异常最危险（单票失败应记录并继续，而不是消失）。

### B-3 响应信封统一（1 天定标准 + 随迭代替换）

不搞一次性全量改造（前端各页已按现状解析，全改必炸）。分三步：

1. **收敛工具**：`schemas/common.py`（或新建 `app/core/response.py`）提供全局 `ok()` 和 `page_result(items, total, page, page_size)`。**签名必须是现有 8 份 `_ok()` 的超集**——其中 4 份（asset/color/stock/report）带 `code` 参数，且全项目有 6 处调用显式传 `code=201`（如 `color/router.py:103`、`stock/router.py:466`），官方版必须是 `ok(data=None, message="ok", code=200)`，否则机械替换会直接 TypeError。
2. **机械替换 8 份 `_ok()`**：各 router 顶部改成 `from app.core.response import ok as _ok`，删除本地定义。签名对齐后行为一致，一次提交完成；替换后跑一遍全量 pytest + 手点 201 场景（创建色号/保存安全库存）验证。
3. **裸 dict 模块只有 invoice/production/mini 三个**（tracking 是手写 `{"code":200,...}` 字面量，格式已合规，只需顺手换成 `ok()`，前端无感知）。裸 dict 换信封必须前后端同一提交内同步改——前端拦截器对无 code 字段的响应是放行的，加信封不会让拦截器报错，**炸的是页面取数路径**（页面按裸结构取值会拿到 undefined）；`/m/` 移动端的原生 fetch 解析同样要查。宪法规定**新端点一律用 `ok()`**，旧端点不专项回改。

### B-4 session/get_db 收敛（半天）

1. 官方版本认定为 `app/core/database.py` 的 `get_db`；`api/deps.py` 改为 re-export（保持旧 import 路径兼容）。
2. 删除 `invoice/router.py`、`production/router.py`、`whatsapp/router.py` 内的本地 `get_db` 定义，改 import。
3. 19 处 `SessionLocal()` 自建**不用动**——scheduler/线程池/bootstrap 场景自建 session 是正确的（cerebrum 已有此认知），只需在宪法写明"仅这三类场景允许自建"。

### B-5 配置收敛进 Settings（半天）

把 `ASSET_STORAGE_ROOT`、`ASSET_SIGN_SECRET`、`ASSET_UPLOAD_STAGING`、`XPOZ_TARGET_ACCOUNTS` 加进 `core/config.py` 的 Settings，9 处 `os.environ` 直读改为 `settings.xxx`；`ai/keyring.py:20` 和 `asset/router.py:966` 的双份读取删掉直读那份。验证：本地启动 + 上传一个素材 + 生成一次短链。

### B-6 权限模型收口（1 天）

1. `insight/dependencies.py` 的 `_require_insight_*` 内部改为调用统一的 `require_permission`（保留函数名，调用方零改动）。
2. `dingtalk/router.py` 手动发送/日志查询端点补 `require_permission("dingtalk:admin")`（需在 seed 中新增权限码，走既有"新增权限三步"流程）。
3. mini 小程序端"登录即全通"**记录为刻意决策**（车间工人扫码场景，细粒度权限无意义），写进 Decision Log 即可，不改代码。

### B-7 双轨结构：冻结而非迁移

- **宪法规则**：`app/api|services|models|schemas` 共享层冻结——不再新增业务文件；提成域改动仍在原地维护（它是最有测试保护的域，迁移风险 > 收益）。
- **两处双份实现择机合并**：short_link 统一到共享层一份（`utils/shortlink.py` 改为薄包装或删除）；report 共享层的 `api/report.py`（报表导出）与 `app/report/`（报表中心）实为两个业务，**改名区分**（如 `api/export.py`）比合并更务实。
- 4 个千行 router **只在下次功能改动涉及时**拆分：按资源拆成 `routers/` 子目录 + 主 router include，一次拆一个域。

### B-8 测试补齐（按风险排序，共约 3 天，可分散执行）

不追求覆盖率数字，追求"**管钱、管货的关键路径有回归保护**"：

1. `stock/sku_query.py` 的库存状态计算（shortage/warning/sufficient 判定 + effective_enable_count 口径）——这是日报和备货决策的依据，纯函数好测
2. `api/commission.py` 批次状态流转（draft→calculated→confirming→confirmed/voided 的非法迁移拒绝）——目前只测了算法层没测状态机
3. `invoice` 金额计算与校验（TotalPrice=Quantity×Price、validate 端点）扩充现有 91 行
4. `tracking/status.py` 的 `normalize_status` 映射表（纯函数，30 分钟）

### B-9 运维稳定性两个空白：备份与回滚（1 天，进第一批）

这两项是对抗性审查补出的缺口，严重度高于响应信封之类的一致性问题——它们对应的是真实事故场景：

1. **素材与上传文件备份**：`D:\WORKSOURCE`（素材中台全部文件）和 `backend/uploads/`（设计附件/头像/报告 HTML）目前单机单盘零备份，而素材中台的定位是"取代钉钉网盘"。最轻方案即可：Windows 计划任务每晚 `robocopy /MIR` 到另一块物理盘或 NAS；有腾讯云 COS 的话用 `coscmd sync` 异地一份更好。同时把备份检查加进 runbook 的定期维护表。
2. **部署回滚路径**：`deploy.bat` 开头加两步——`git tag deploy-%date%` 打部署标记、`dist/` 构建产物留档一份（`xcopy dist dist_backup_%date%`）。回滚 = checkout tag + 恢复 dist + 重启服务，写成 `deploy\rollback.bat` 或 runbook 一节。alembic downgrade 不强求补写（成本高），靠 RDS 自动备份兜底数据层。

---

## 五、前端 UI 改进方案与实施步骤

> 原则：UI 一致性是用户直接感知的（你的最高准则），但治理方式是"**管住新增、热点回改**"，不做全量回刷。

### F-1 立即修复 ExternalBindings.vue（半小时）

删除组件内 `axios.create`，改用 `clients.js` 的 authClient（如无则在 clients.js 新增 `adminClient = createApiClient({ baseURL: '/api/auth' })`）。这是唯一一处违规，且它绕过了 401 自动跳转——token 过期时该页会静默坏掉。验证：登录过期场景下操作该页，确认跳登录页。

### F-2 列表页体验统一：useListPage composable + 标杆模板（2 天，新页强制、旧页随迭代）

29 个列表页各写一遍"搜索栏 + loading + 表格 + 空态 + 分页"，导致空态覆盖只有 27/40、提示文案各说各话。**不建议做重型 `<ListPage>` 大组件**（Element Plus 场景下插槽层层透传，反而僵硬），建议轻方案：

1. 新建 `composables/useListPage.js`：封装 `loading / list / total / page / pageSize / searchForm / fetchList / handleSearch / handleReset / handlePageChange`，接收一个 `fetchFn`。与现有 `useTableSort`、`useTableMaxHeight` 组合使用。
2. **标杆模板升级**：cerebrum 已认定 `system/DictManagement.vue` 为列表页标杆——将它改造为使用 `useListPage` 的版本，并在模板注释头部标注"新列表页复制此文件"。
3. 新建 `utils/feedback.js`：`msgSuccess / msgError / confirmDanger(text)` 三个函数统一提示风格与文案格式（如删除确认统一"确定删除「××」？此操作不可恢复"句式）。
4. 宪法规则：新列表页必须用 useListPage + feedback.js；空态 `el-empty` 必须有。

### F-3 设计 token 治理：管住增量（1 天建机制）

802 处存量硬编码不值得专项回改（工作量 > 收益），但增量必须掐断，否则 tokens.css 永远追不上：

1. **补 token**：统计 views 下 hex 出现频率 Top 20（一条 grep + sort 命令），把高频色提升为 tokens.css 变量并归类命名——62 个 token 太少是硬编码泛滥的部分原因。
2. **检查脚本管增量**（见第六部分 G-5 的 check-conventions 脚本）：检测**本次 diff 中新增的** hex 颜色并报警。
3. 热点页（ShippingDailyReport、CaseLibraryView 等前 5 名）在下次功能改动时顺手替换。

### F-4 大页面拆分：新页硬门槛、旧页随迭代

- 13 个存量超标页**不专项拆**，下次功能改动涉及哪个拆哪个（拆法沿用既有模式：`composables/use<Page>.js` 全量状态 + 薄壳 script setup）。
- 新页面 >500 行为硬性门槛，进 check-conventions 脚本（对 diff 中新增 .vue 文件计行数）。
- `views/invoice/`、`views/commission/` 补建 `composables/` 目录，下次改 InvoiceManage/SalesCommission 时优先拆。

### F-5 移动端止损策略（决策，不动代码）

`/m/` 这套 1333 行的平行实现现在能跑、用户在用，**不重写**。但必须定边界防止扩散：

- 宪法规则：**/m/ 冻结为素材域专用**，不再往里加新领域；新的移动端需求一律评估"主站响应式适配"或"微信小程序"两条既有路径。
- `/m/` 的 API 调用如遇后端响应信封改造（B-3），需同步检查其原生 fetch 解析。

### F-6 共享组件：只抽两个最痛的（各 1 天，新页使用、旧页不回改）

11 处上传、9 处抽屉不必全部归一（场景差异大，强行抽象会做出一个 20 个 props 的怪物）。只抽两个：

1. `components/AppUpload.vue`：覆盖最常见的"图片/文件选择 + 校验 + 进度 + 已传列表"场景，props 控制 accept/maxSize/multiple。
2. `components/DetailDrawer.vue`：仅封装抽屉骨架（标题/宽度/loading/底部操作区插槽），内容完全自由——参考已成功的 `components/design/RequestDetailDrawer.vue` 泛化。

### F-7 构建优化（半天，一次性）

`vite.config.js` 补 `build.rollupOptions.output.manualChunks`：`element-plus`、`echarts` 各拆 vendor chunk。局域网用户无感，但外网首访（腾讯云 Nginx 已开 gzip + 1 年强缓存）改版后缓存命中率会显著提升——vendor 不随业务代码变更失效。顺带评估 `vuedraggable`（仅 1 处引用）是否可用 HTML5 原生拖拽替代。

---

## 六、Vibe Coding 治理：长期稳定的提示词与 skill 体系

> 这是本次评估最重要的部分。前后端问题清单里的"规范执行衰减"（新代码仍违反明文规范），根因就在这一层。

### 核心诊断：三个失效机制

1. **上下文税与注意力稀释**：CLAUDE.md 968 行 ≈ 1.6 万 token，其中 ~600 行是 API 端点清单和数据库表清单。真正的行为规则（约定、红线）被淹没在参考资料里。模型每次会话都读全文，但"参考资料"稀释了"规则"的权重——这正是"规范存在但新页面不守"的机制性解释。
2. **知识四处重复、无单一真相源**：同一条知识（如模块结构、已踩的坑）同时存在于 CLAUDE.md、docs/architecture.md、.wolf/cerebrum.md、auto-memory 四处，更新时靠人肉同步，已出现漂移（handoff.md 说 30 用户，需求描述说 100）。
3. **提示词管不住机械规则**："不要自建 axios""不超 500 行""不要裸 except"这类**机器一行 grep 就能查的规则**，交给概率性的提示词遵守，衰减是必然的。提示词应该管判断（架构决策、交互设计），脚本管硬规则。

### G-1 CLAUDE.md 瘦身为"宪法"（1 天，收益持续）

目标：968 行 → **250 行以内**，只留改变行为的内容：

```
CLAUDE.md（宪法）保留：
├── 项目一句话简介 + 技术栈 + 端口 + 开发/部署命令        （~40 行）
├── 硬约定（红线）：模块结构二选一规则、响应信封 ok()、    （~80 行）
│   权限 Depends 必加、clients.js 唯一、navigation.js 唯一、
│   >500 行拆分、迁移 ID ≤32 字符、bat 编码、新权限三步 等
├── 指针区：详细资料在哪（不展开内容）                     （~20 行）
│   API 清单 → docs/api-reference.md
│   数据库表 → docs/database.md
│   模块专题 → auto-memory 各 project_*.md
│   踩坑记录 → .wolf/cerebrum.md
└── 完工自查（DoD）：跑 scripts/check_conventions.py +     （~20 行）
    测试 + build，涉钱/跨 3 文件改动做对抗性审查

迁出去的内容：
├── ~400 行 API 端点清单 → docs/api-reference.md（按需读）
├── ~150 行数据库表清单 → docs/database.md
└── 各模块专题细节（钉钉/报表/短链/OCR 等）→ 已有 auto-memory 对应条目，删除重复
```

理由（第一性原理）：CLAUDE.md 的本质是"每次会话必读的行为规则"，API 清单的本质是"偶尔查阅的参考资料"。两者混装，规则被稀释、清单还常年过时（每加一个端点都要手动同步一次——当前 CLAUDE.md 就写着"九个 job"而实际是 11 个）。分开后，清单过时的代价从"污染每次会话"降为"查询时才暴露、顺手修正"。

**为什么新指针区不会重蹈 anatomy.md 的覆辙**（anatomy 的失败恰恰证明"指针协议"可能没人遵守）：两者机制不同。anatomy 要求的是**每次读文件前的主动查表协议**——高频、逆直觉（Glob/Grep 更顺手），所以 hits: 0；指针区指向的是**低频参考资料**，AI 找不到端点定义时自然会搜索，指针只是把搜索引向正确文件，不依赖纪律。且 auto-memory 的 MEMORY.md 本来就随会话自动加载，模块知识的召回不走指针。

### G-2 .wolf 体系收敛为一个文件（半天决策 + 执行）

基于覆盖率事实逐项处置：

| 文件 | 现状 | 处置 |
|------|------|------|
| cerebrum.md（139 行） | Do-Not-Repeat 42 条实战教训，真正的资产 | **保留**，作为唯一的"教训库" |
| anatomy.md（588 行） | 仅覆盖 59/300+ 文件，hits: 0，还混入 C:/Users 无关路径 | **停用**。"先查 anatomy 再读文件"协议名存实亡，Glob/Grep 本来就是干这个的 |
| memory.md（1848 行） | 逐操作流水账，只写不读 | **停用**逐条记录；会话结束的有效沉淀应该进 cerebrum 或 auto-memory |
| buglog.json（13 条） | 与 cerebrum Do-Not-Repeat 高度重复，且多为 auto-detected 低价值条目 | **合并进 cerebrum** 后停用 |
| OPENWOLF.md 协议 | 每轮要求查 anatomy/写 memory/写 buglog，纯开销 | 相应精简：只保留"生成代码前读 cerebrum、被纠正后更新 cerebrum"两条 |

**注意：停用必须同步改掉两个指令入口，否则会留下自相矛盾的指令体系**：

1. 项目 `CLAUDE.md` 顶部的 `@.wolf/OPENWOLF.md` import 及"Read and follow ... every session"段落——G-1 瘦身时一并处理；
2. `.claude/rules/openwolf.md`——它独立要求"每次查 anatomy、写 memory、写 buglog"，需同步精简为与新协议一致的两条。

漏掉任何一处，AI 每次会话都会同时收到"必须写 buglog"和"buglog 已停用"两套冲突指令，执行质量反而下降。

cerebrum.md 与 auto-memory 的分工明确化：**cerebrum = 教训（做错过什么）**，**auto-memory = 模块知识（每个模块怎么回事）**，不再交叉。

### G-3 硬规则脚本化：scripts/check_conventions.py（1 天，治理体系的核心抓手）

把"机器可查的规范"从提示词移到可执行检查——这是终结规范衰减的关键一步：

```
检查项（都是本次评估发现的高频违规，各一条 grep/统计逻辑）：
1. 前端：views/**.vue 中出现 axios.create        → 报错（clients.js 之外禁止）
2. 前端：本次 diff 新增行含 6 位 hex 颜色         → 警告（应使用 tokens.css）
3. 前端：新增 .vue 文件 >500 行                   → 警告（应拆 composable）
4. 后端：新增 router 端点无鉴权依赖               → 警告（合法形态白名单：require_permission /
   require_any_permission / get_current_user / _require_* 包装 / mini 与 dingtalk 回调豁免）
5. 后端：新增裸 except: 或 except Exception: pass → 报错
6. 后端：alembic/versions 新文件 revision >32 字符 → 报错
7. 后端：领域模块外新增业务文件（api/services 冻结）→ 警告
```

- 实现为普通 Python 脚本，`git diff` 驱动（只查增量，不翻旧账），红/黄两级输出。
- **误报率是生死线**：噪声大的检查会训练使用者忽略它，直接摧毁整个机制。检查项 4 的白名单必须先配齐（tracking/insight 现有 11 处合法的 `Depends(get_current_user)`、insight 的 `_require_*` 自定义依赖都不能报）；上线首周所有项先设为警告观察误报，收敛后再把 1/5/6 升级为报错。
- 接入方式（按约束力递增）：宪法 DoD 要求 AI 完工必跑 → 挂 pre-commit hook → deploy.bat 前置步骤。建议先做第一档，跑顺后再挂 hook。
- 工作量按 2 天估（diff hunk 解析 + 装饰器跨行匹配 + 三类白名单调试，1 天做不完一个低误报版本）。

### G-4 沉淀三个流程 skill/检查清单（各半天）

放 `.claude/rules/` 或做成项目 skill，AI 与人共用：

**① 新模块 checklist**（每次开新领域模块照此执行，杜绝"漏一步"）：

```
1. alembic 迁移（revision ≤32 字符，创建后立即 git add）
2. app/<domain>/：models → schemas → service → router（每端点带权限 Depends）
3. routers.py 注册 + seed_role_permissions 加权限码
4. 前端：api/<domain>.js（走 createApiClient，clients.js 登记）
5. navigation.js 加 entry（permission 声明，router/菜单自动生成）
6. 列表页复制 DictManagement.vue 标杆 + useListPage
7. 核心计算/状态流转写测试（管钱管货的必须有）
8. 文档：docs/api-reference.md 加端点 + auto-memory 建 project_<domain>.md
9. 跑 check_conventions.py + pytest + npm run build
```

**② 完工 DoD（Definition of Done）**：改动落地前必过——测试/lint/build 通过、check_conventions 无红项、涉及 UI 的对照 DESIGN.md、**报告实际跑出的验证证据而非"应该没问题"**。

**③ 对抗性审查触发标准**（你的全局规则在本项目的落地量化）：满足任一即派独立 agent 审查——跨 3 个以上文件的改动 / 涉及提成、发票、回款、库存数量的逻辑 / 状态机变更 / 迁移脚本。审查 agent 的固定视角：边界条件、并发写、幂等性、前后端契约一致。

### G-5 会话工作习惯（写进宪法的软规则）

1. **小步提交**：仓库 2.5 个月共 243 次提交，对照 19 个模块的产出量，单次提交普遍是"一个完整功能"粒度。vibe coding 的安全网是"每个提交可独立回滚"——建议一个功能拆 3~5 个提交（迁移 / 后端 / 前端 / 测试）。
2. **改造类任务先 grep 后动手**：cerebrum 里三次"函数搬家漏延迟 import"事故的通用解药，固化为规则："搬移/重命名任何函数前，全局 grep 旧引用（含函数体内延迟 import）并在提交说明中贴出 grep 结果"。
3. **每次会话结束的沉淀动作收敛为一条**：有教训 → cerebrum；有新模块知识 → auto-memory；两者都没有 → 不写。取代现在 OpenWolf 要求的四处记录。

---

## 七、实施路线图

| 批次 | 内容 | 工作量 | 验收标准 |
|------|------|--------|----------|
| **第一批：止血**（本周内） | ✅ B-1 调度告警（EVENT_JOB_ERROR/MISSED 监听 + run_coroutine_threadsafe 钉钉推送）+ 阻塞 job 转线程池（insight 3 个 AI job + color 2 个改同步注册）、✅ B-2 三处吞异常留痕（asset 补 logger）、✅ B-9 脚本就绪（deploy.bat [0/7] 快照 + rollback.bat + backup-uploads.bat，**服务器上还差注册 schtasks 计划任务与指定备份盘**）、✅ F-1、✅ B-5 配置收敛（Settings +4 项，9 处 os.environ 直读清零，双份读取删除）——2026-07-03 完成 | ~3 天 | 人为触发失败 job 钉钉可收到告警；素材盘有每晚镜像；rollback.bat 演练一次成功 |
| **第二批：立规**（两周内） | ✅ G-1 CLAUDE.md 瘦身（2026-07-03 完成，968→107 行，拆出 api-reference/database/module-notes 三文档）、✅ G-2 .wolf 收敛（含两个指令入口）、✅ G-3 check_conventions 脚本（当前 diff 实测红 0/黄 93）、✅ G-4 checklists（.claude/rules/checklists.md）、✅ B-3 步骤 2（8 份 `_ok` 归一到 app/core/response，**顺带修复 insight 雷达"添加备注"端点的潜伏 TypeError**——本地 _ok 无 code 参数却被传 code=201）、✅ B-4 get_db 收敛（api/deps 改 re-export，invoice/production/whatsapp 三 router 删本地定义）——2026-07-03 完成 | ~6 天 | CLAUDE.md ≤250 行且无冲突指令残留；脚本对当前 diff 可跑且一周内无误报投诉；8 份 `_ok` 归一 |
| **第三批：体验收口**（一个月内） | ✅ F-1 ExternalBindings 违规修复（adminClient 入 clients.js）、✅ F-2 useListPage+feedback.js+双标杆（DictManagement 管标记、ExpoLeads 管编排）、✅ F-3 token 补齐（62→73，含高频硬编码色提炼）+增量脚本管控、✅ F-5 /m/ 冻结入宪法 21 条、✅ F-6 AppUpload+DetailDrawer 共享组件、✅ F-7 manualChunks（业务入口 1.28MB→36KB，vendor 独立缓存；vuedraggable 仅 ProcessRouteManage 一处使用，暂保留）、✅ B-6 权限收口（insight 9 个自定义依赖改统一工厂；dingtalk 5 端点加 `dingtalk:admin` 权限码；mini 登录即全通记为刻意决策）——以上 2026-07-03 完成 | ~6 天 | 新列表页复制标杆即合规；新增 hex 会被脚本拦截 |
| **第四批：随迭代治理**（长期） | ✅ B-8 测试补齐（2026-07-03：+122 个——tracking 状态映射 57 / stock 状态判定 20 / 提成状态机全矩阵 31 / invoice 金额 14，全量 209 passed）、B-7 双轨冻结（宪法+脚本已管）+择机合并、F-4 大页拆分、M8 双份实现合并、千行 router 拆分 | 分散 | 每次改到相关文件时顺手执行，不专项立项 |

### 明确不做清单（防止过度设计）

- ❌ 微服务化 / 消息队列 / Redis 缓存——30 日活的单体没有这些需求
- ❌ Docker 迁移——NSSM 运行稳定，迁移是纯风险
- ❌ 802 处硬编码颜色全量回改、13 个大页面专项拆分——只管增量和热点
- ❌ 移动端 /m/ 重写——冻结边界即可
- ❌ 共享层提成域迁移为领域模块——测试保护最全的域，动它风险 > 收益
- ❌ APM / 慢查询平台化监控——第一批的钉钉告警 + 全局 handler 日志对当前规模够用；等出现真实的慢查询体感再议

---

## 附：本评估的证据来源与审查过程

- 后端勘察（独立 agent）：221 文件 42,177 行统计、最大 15 文件清单、`_ok()`/`get_db`/`except`/`os.environ` 全量 grep、tests 目录盘点、schedulers 与 alembic 核查
- 前端勘察（独立 agent）：95 vue + 44 js 统计、最大 20 文件清单、axios.create/hex 颜色/el-pagination/ElMessage 全量 grep、navigation.js 62 entry 对照 70 视图核查
- 提示词资产：CLAUDE.md 968 行、.wolf 四文件行数与内容抽查（anatomy hits:0、buglog 13 条）、git 提交节奏统计（2.5 个月 243 commits）
- **对抗性审查**（第三个独立 agent，行号级核验 20+ 项论断）：修正了初稿 4 处事实错误（tracking 误归裸 dict、B-1 示例代码的 async webhook 陷阱、ok() 签名遗漏 code 参数、提交统计口径），补入 2 个初稿遗漏的稳定性缺口（S7 素材备份、S8 部署回滚），并修正了 G-3 误报风险与 G-1/G-2 的指针悖论论证。数字口径说明：hex "802 处"按行计（按出现次数为 932）；页面行数为评估时点快照，个别文件当日仍在变动
