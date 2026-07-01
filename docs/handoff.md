# 莱莎方舟平台 项目交接清单

> **版本**：v1.0  
> **最后更新**：2026-07-01  
> **项目状态**：运行中，持续迭代

## 项目概况

- **项目名称**：莱莎方舟平台（LeShine Ark Platform）
- **开发周期**：2024-Q3 至今（约 15 个月）
- **代码规模**：后端 ~25K 行 Python + 前端 ~18K 行 Vue + 微信小程序 ~3K 行
- **数据库表数**：64 张（commission_db）
- **数据库迁移数**：039 个（Alembic）
- **用户数**：~30 人（莱莎员工）
- **日活**：~20 人
- **部署环境**：生产（腾讯云 + 本地 Windows Server）

## 已完成功能（2026-07-01）

### 核心业务模块（18 个）

1. ✅ **提成管理**：回款单计算、客户归属快照、批次管理
2. ✅ **物流跟踪**：DHL/FedEx 自动轮询、关键状态推送、物流日报
3. ✅ **运单上传**：图片 OCR（AI 多模态）+ 手动录入
4. ✅ **设计预约**：申请/审批/排期、冲突检测、附件上传、钉钉通知
5. ✅ **认证与 RBAC**：用户/角色/权限、JWT + Refresh Token Cookie
6. ✅ **AI 接入**：Provider/Preset 管理、调用日志、API Key 加密存储
7. ✅ **方舟洞见**：
   - 信源配置（13 种 source_type）
   - 情报采集库（结构化条目 + 可信度标记）
   - 行业情报速览（AI 6 部分生成）
   - 行业情报日报 + AI 工具速递
   - 案例库（AI 整理 + 用户修正）
   - 周会纪要（AI 整理 + 任务跟踪）
   - **客户机会台**（ACCIO 询盘导入 + 归属解析 + 机会卡 + 话术）
   - **客户经营雷达**（活画像 + 事件流 + 6 线索分组 + 行动推荐）
8. ✅ **素材管理**：标签化中台、AI 打标签、版本迭代、收藏分享、移动端独立页面
9. ✅ **发色数字化**：色板数据库、混合色管理、色彩趋势、AI 色板图生成
10. ✅ **备货管理**：安全库存设置、销量备货一览、库存日报、低库存钉钉推送
11. ✅ **生产订单**：购物车 → 批量下单 → 订单跟踪 → 入库录入
12. ✅ **生产报工**：工序管理 → 路线配置 → 产品绑定 → 扫码报工 → 生产看板
13. ✅ **报表中心**：Stimulsoft Reports.JS（DOM 挂载 Viewer/Designer + 后端 JSON 数据 API）
14. ✅ **微信小程序**：扫码报工 / 报工历史 / 报工总览 / 登录绑定
15. ✅ **数据概念治理**：概念注册表 / 8 分区编辑器 / 关联关系 / 全景图谱 / 变更历史
16. ✅ **WhatsApp 同步**：扫码绑定 / 会话消息拉取 / 附件投影 / 自动定时同步
17. ✅ **钉钉集成**：工作通知（设计预约 + 物流状态）+ Webhook 推送 + 审批回调
18. ✅ **短链服务**：统一短链生成（`/s/{code}` 双查找路由）

### 基础设施

- ✅ 定时任务（APScheduler，11 个 job）
- ✅ 移动端素材管理（Vue 3 CDN 独立页面，UA 守卫分流）
- ✅ 生产架构（腾讯云 Nginx 静态直出 + SSH 隧道 API 反代）
- ✅ NSSM 服务托管（CommissionSystem + WhatsAppConnector 双服务）
- ✅ 前端路由 + 菜单单一来源（`navigation.js`）
- ✅ API client 统一（`clients.js` 集中导出，禁止自建 axios）
- ✅ OpenWolf 项目管理（`.wolf/` 目录，anatomy/cerebrum/memory）

### 测试覆盖

- ✅ 提成计算单元测试（27 个）
- ✅ 设计预约状态机 + 冲突引擎测试（34 个）
- ✅ Scheduler smoke 测试（10 个）
- **总计 71 tests**

## 待办事项（优先级递减）

### P0（关键）

无当前 P0 任务，系统运行稳定。

### P1（重要）

1. **补全测试覆盖**：
   - tracking 轮询逻辑单元测试
   - insight 完整链路集成测试
   - stock 计算单元测试
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
| 测试覆盖不足 | 回归测试信心 | P1 | 5 天 |
| 批量循环服务 import 检查 | folder_upload / 类似批量逻辑 | P2 | 1 天 |
| 前端大页面拆分 | 可维护性 | P2 | 3 天 |
| 移动端全模块适配 | 用户体验 | P2 | 10 天 |

## 已知问题（非阻塞）

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
| [integration-guide.md](integration-guide.md) | ✅ | API 接入指南、认证方式、错误码、示例代码 |
| [runbook.md](runbook.md) | ✅ | 部署步骤、运维命令、故障排查、环境变量清单 |
| [handoff.md](handoff.md) | ✅ | 项目状态、已完成功能、待办清单、技术债务 |
| [accio-work-integration-spec.md](accio-work-integration-spec.md) | ✅ | ACCIO WORK 集成规范（客户机会台） |
| [requirements/2026-06-16-whatsapp-connector-contract.md](requirements/2026-06-16-whatsapp-connector-contract.md) | ✅ | WhatsApp Connector 契约 |
| [../CLAUDE.md](../CLAUDE.md) | ✅ | AI 协作说明（930 行，项目根目录） |
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

- 本项目使用 OpenWolf 管理（`.wolf/` 目录），AI 协作时会自动读取项目记忆
- 所有 UI 决策以 `DESIGN.md` 为准
- 新增权限需修改 `seed_role_permissions()` 并重启后端
- 数据库变更必须通过 Alembic migration
- 生产环境 `.env` 强校验（见 `config.py` 的 `_validate_production`）

---

**交接人**：亮哥  
**交接日期**：待定  
**接手人**：待定
