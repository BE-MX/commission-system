# 莱莎方舟平台 项目交接清单

> **版本**：v1.0  
> **最后更新**：2026-07-03  
> **项目状态**：运行中，持续迭代

## 项目概况

- **项目名称**：莱莎方舟平台（LeShine Ark Platform）
- **开发周期**：2026-03 至今（约 4 个月；git 仓库首次提交 2026-04-20）
- **代码规模**：后端 ~25K 行 Python + 前端 ~18K 行 Vue + 微信小程序 ~3K 行
- **数据库表数**：120 张（commission_db，2026-07-13 information_schema 实测）
- **数据库迁移数**：066（Alembic，最新 `066_invoice_removed_lines`）
- **用户数**：~30 人（莱莎员工）
- **日活**：~20 人
- **部署环境**：生产（腾讯云 + 本地 Windows Server）

## 已完成功能（2026-07-03）

### 核心业务模块（20 个）

1. ✅ **提成管理**：回款单计算、客户归属快照、批次管理、业务员确认流程（confirming 状态 + 反馈/确认机制）
2. ✅ **订单发票管理**：发票 CRUD、产品级联选择、Excel/PDF/HTML 导出；OKKI 推单 Phase 2 进行中（2026-07-10 鉴权/token 自动续期/订单枚举/设置页/业务员绑定候选同步已上线，推单字段映射待做）
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

### 基础设施

- ✅ 定时任务（APScheduler，11 个 job）
- ✅ 移动端素材管理（Vue 3 CDN 独立页面，UA 守卫分流）
- ✅ 生产架构（腾讯云 Nginx 静态直出 + SSH 隧道 API 反代）
- ✅ NSSM 服务托管（CommissionSystem + WhatsAppConnector 双服务）
- ✅ 前端路由 + 菜单单一来源（`navigation.js`）
- ✅ API client 统一（`clients.js` 集中导出，禁止自建 axios）
- ✅ 项目记忆精简协议（`.wolf/cerebrum.md` 唯一教训库；anatomy/memory/buglog 已于 2026-07-03 停用存档）+ `scripts/check_conventions.py` 增量约定检查
- ✅ 权限矩阵配置（2026-07-03：23×5 矩阵抽屉 + 6 角色模板 + 按导航反查 + 变更审计 + v-permission 指令；81 权限清理为 69 有效）

### 测试覆盖

- ✅ 提成计算单元测试（27 个）
- ✅ 设计预约状态机 + 冲突引擎测试（34 个）
- ✅ Scheduler smoke 测试（10 个）
- ✅ expo 匹配引擎 + 禁用词 + 性别兜底（16 个）+ 发色库/场景/看门狗/JSON重试/图片压缩逻辑测试（39 个，含多场景合一与输出尺寸）+ 话术触发互斥（2 个）——2026-07-07
- ✅ tracking 状态映射（57）/ stock 状态判定（20）/ 提成批次状态机全矩阵（31）/ invoice 金额（14）——2026-07-03 B-8 补齐
- ✅ invoice / whatsapp / payment 等模块测试
- **总计 286 tests（2026-07-07 全绿）**

## 待办事项（优先级递减）

### P0（关键，8 月展会倒排）

1. **展会试戴生图稳定性**（2026-07-07 更新：图像模型已接入并启用，单场景合成实测可用 ~130s，但上游拥堵时段仍会 >300s 被 ELBNT 网关 502/504）：持续观察成功率；不达标则评估自动重试或更换生图 Provider；继续 10 真人照 × 5 假发批量实测
2. ~~ELBNT 账号池 503~~（2026-07-07 已恢复，分析/话术/生图三 preset 均正常出活，留意复发）
3. **展会物料**（依赖市场部）：15~20 款短发多角度实拍图入发型库、6 个月对比素材、10+ 老客户证言
4. **稳定性止血收尾（代码侧已完成 2026-07-03）**：调度告警/回滚脚本/备份脚本已落地，剩服务器上三个动作——①编辑 `deployackup-uploads.bat` 的 BACKUP_ROOT 指向备份盘并注册 schtasks 计划任务；②下次部署后演练一次 `rollback.bat`；③角色管理页给相关角色分配新权限 `dingtalk:admin`

### P1（重要）

-1. **OKKI 推单 Phase 2 收尾**（2026-07-10 地基完成：client_credentials 鉴权实测打通、token 自动续期、orderEnums、设置页 `/invoice/okki-settings`、绑定候选同步 42 人）：
   - ①生产服务器 `backend/.env` 加 `OKKI_CLIENT_ID/SECRET` 后部署重启（deploy 不同步 .env）
   - ②管理员完成业务员绑定（系统管理→外部账号绑定）+ 设置页配置通用产品/默认订单状态
   - ~~③开发推单主体~~（2026-07-13 已完成：真实推单 + 幂等编辑 + unique_id 传承 + 删行 remove + 同步日志，066 迁移；细节见 docs/module-notes.md invoice 节）
   - ④首推联调：**无沙箱，产生真实订单**，需指定测试客户；token 明文入库 vs 需求文档"加密"待拍板

0.5 **展会试戴竖版全身入镜待决策**（2026-07-13）：拍照现为 1:1 中央裁剪，「多露身体」目前只靠取景椭圆上移 + 构图引导在方框内容纳肩颈上身；真竖版全身需改裁剪比例并回归 AI 合成管线（生成尺寸/模板受影响），等亮哥拍板再做

0. **对外库存查询后续**（2026-07-07 一期已上线：`/api/public/stock/products` + `/inventory` 英文嵌入页，key 门禁）：①服务器 `.env` 配置 `PUBLIC_STOCK_KEYS` 并把带 key 链接交付客户；②Shopify 主动推送（Webhook 回写客户店铺库存）待客户确认需求后排期；③观察是否需要限流


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

## 运维交接

### 关键配置文件

| 文件 | 位置 | 说明 |
|------|------|------|
| 后端环境变量 | `backend/.env` | 数据库/JWT/钉钉/微信/WhatsApp 配置 |
| 云端 Nginx | `/etc/nginx/conf.d/leshine.conf` | 静态直出 + API 反代 |
| NSSM 服务配置 | NSSM 注册表 | `nssm edit CommissionSystem` 查看 |
| SSH 隧道 | 手动启动或 NSSM | `ssh -N -R 8888:localhost:8002 root@119.28.107.92` |

### 定期维护（建议频率）

| 任务 | 频率 | 负责人 |
|------|------|--------|
| 数据库备份验证 | 每月 | 运维 |
| uploads/素材盘备份日志抽查（.deploy_stateackup.log） | 每月 | 运维 |
| SSL 证书续期 | 每 60 天 | 运维 |
| API Key 轮换 | 每季度 | 技术负责人 |
| 日志清理 | 每月 | 运维 |
| 依赖安全更新 | 每季度 | 后端开发 |
| 性能报告 | 每季度 | 技术负责人 |

### 紧急联系

- **服务器宕机**：重启 NSSM 服务（`nssm restart CommissionSystem`）
- **数据库连接失败**：检查腾讯云 RDS 白名单 + 密码
- **前端白屏**：检查云端静态文件 + SSH 隧道
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

- **必需**：Windows Server / NSSM / Nginx / SSH
- **次要**：腾讯云 RDS / Let's Encrypt SSL
- **业务**：双服务托管 / SSH 隧道 / 前端 dist 同步

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
| [2026-07-03-architecture-assessment.md](2026-07-03-architecture-assessment.md) | ✅ | 平台架构评估与改进路线图（问题清单 + 四批实施计划） |
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

- 项目记忆用精简版协议（2026-07-03 治理）：`.wolf/cerebrum.md` 是唯一教训库，anatomy/memory/buglog 已停用存档；模块知识在 AI 的 auto-memory
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
