# 莱莎方舟平台 项目交接清单

> **版本**：v1.4  
> **最后更新**：2026-07-22  
> **项目状态**：运行中，持续迭代

## 项目概况

- **项目名称**：莱莎方舟平台（LeShine Ark Platform）
- **开发周期**：2026-03 至今（约 4 个月；git 仓库首次提交 2026-04-20）
- **代码规模**：后端 ~25K 行 Python + 前端 ~18K 行 Vue + 微信小程序 ~3K 行
- **数据库表数**：120 张（commission_db，2026-07-13 information_schema 实测）
- **数据库迁移数**：077（Alembic head `077_training_file_meta`，2026-07-21；073/074 发票配件、075 培训速递、076 PM 站、077 培训附件类型/备注）
- **用户数**：~30 人（莱莎员工）
- **日活**：~20 人
- **部署环境**：生产（腾讯云新加坡 Nginx + 本地 Windows Server + 北京云展会实例 2026-07-22 起，拓扑见 docs/architecture.md）

## 已完成功能（2026-07-13 更新）

### 核心业务模块（20 个）

1. ✅ **提成管理**：回款单计算、客户归属快照、批次管理、业务员确认流程（confirming 状态 + 反馈/确认机制）
2. ✅ **订单发票管理**：发票 CRUD、产品级联选择、Excel/PDF/HTML 导出；OKKI 推单闭环（2026-07-13：真实推单 + 幂等编辑 + 非标合并单条通用行 + 企业必填字段部门/订单类型/新成交/包邮/首返 + 同步日志，066/068 迁移）；数据范围权限 `invoice:read_all`（默认只见自己创建的发票，067）；录入自动填充（客户联系人快照复用 + 业务员信息默认当前用户 + 小满标记三开关智能默认）；**配件双类型**（2026-07-18 合入：明细 `product_kind` hair/accessory、配件标准价按真实 product_id+sku_id 唯一、金额 ROUND_HALF_UP 口径、PDF 中文字体预检，073/074 迁移）
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
21. ✅ **PM 项目资料协作站**（2026-07-17，阿里国际站智能体陪跑项目；设计稿 docs/requirements/2026-07-17-pm-material-hub.md）：
    - 独立子站 `pm.leshine.work`（**2026-07-18 已上线**：DNSPod A 记录 + Let's Encrypt 证书 certbot webroot + 云 Nginx `/etc/nginx/conf.d/pm.leshine.conf`，门牌页/API 反代/HTTP 跳转全链路实测通过）：后端 `app/pm/` 领域模块（8 表，076 迁移），前端 `frontend-pm/` 完全独立应用（自研编辑感设计系统，无 Element Plus，与方舟零视觉血缘）
    - 无密码门牌：用户名白名单换 HMAC token（30 天 + epoch 全局重签兜底），每请求回查白名单（移除立即生效），统一失败提示防枚举 + 用户名维度限速；顶栏身份常显可一键切换
    - 35 项材料清单（五分类 × 重要级 × Phase 批次；**2026-07-18 已按顾问原清单《00_索引与缺口清单.md》重灌**，任务清单同步为行动清单 14 条）；版本自动编号只增不复用、软删回落、下载自动重命名 `名称_vN.ext`、凭据类禁传原文；AI 差异概要=本地精确 diff（difflib/openpyxl/docx/pypdf）+ pm_diff preset 转述，pending 看门狗启动回收
    - 轻量看板（四状态 + 受阻必填原因 + 关联资料徽标）、全站动态（审计日志用户侧）；文件存 `backend/data/pm/`（非公开静态），下载/预览 300s 签名 URL
    - 2026-07-18 追加：上传对话框/抽屉 await-emit 修复（真等待+失败留窗）+ 拖拽上传；IP 维度 entry 限速（X-Real-IP，20 次/分）；**Phase 2 之 MD 在线编辑已完成**（`POST /versions/text` + MdEditor 分屏编辑器，基线冲突确认，走上传同一版本通道）
    - **2026-07-19：Phase 2 之版本评论已完成**（合入 main，待部署）：评论挂具体版本、版本卡内展开；单层回复自动拍平、仅作者可删、占位线程可续贴；无版本资料（offline/link）无评论；资料库列表 `❞ N` 角标 + 动态流「评论」筛选；两轮对抗性审查（细节见 module-notes PM 节）
    - **待完成**：生产 `.env` 可选项 `PM_TOKEN_SECRET` 独立随机串（当前回退 JWT_SECRET_KEY，见 runbook PM 节步骤 5，服务器上一条命令+重启，会全员重新进门牌）；Phase 2 之划线锚点评论未启动（anchor 字段已预留且评论表已在用）
22. ✅ **培训速递**（2026-07-18 合入 main）：参训人自助发布 + AI 提炼草稿（粘贴文字/图片多模态/PDF 抽文本 → 结构化分区）+ 4 步强引导向导 + 发布必填分区校验 + 钉钉群 actionCard 推送 + 「有用」轻反馈；`training:read/write/admin` 权限；075 迁移，3 张表
    - **2026-07-21 附件增强**（077 迁移，待部署）：附件类型白名单下拉（默认按扩展名自动识别）+ 批次备注 + 多选上传逐文件进度 + 列表行内改类型/备注（`PATCH /files/{id}`，失败回滚显示值）；存量附件显示「未分类」；公共组件 `AppUpload` 新增 uploadFn onProgress 第二参数与 `show-list` 开关（向后兼容）；编辑器附件区拆 `AttachFilesPanel.vue`

### 基础设施

- ✅ 定时任务（APScheduler，11 个 job）
- ✅ 移动端素材管理（Vue 3 CDN 独立页面，UA 守卫分流）
- ✅ 生产架构（腾讯云 Nginx 静态直出 + frp 内网穿透 API 反代，frpc 挂 NSSM）
- ✅ NSSM 服务托管（CommissionSystem + WhatsAppConnector 双服务）
- ✅ 前端路由 + 菜单单一来源（`navigation.js`）
- ✅ API client 统一（`clients.js` 集中导出，禁止自建 axios）
- ✅ 项目记忆精简协议（`.wolf/cerebrum.md` 唯一教训库；anatomy/memory/buglog 已于 2026-07-03 停用存档）+ `scripts/check_conventions.py` 增量约定检查
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
- **总计 532 tests（2026-07-13 全绿）→ 753 tests（2026-07-18 全绿，培训速递/PM 站/发票配件合入后；PM display_name 断言已随 seed 改名修复为从 MEMBERS_SEED 派生）→ 777 tests（2026-07-19 全绿，PM 版本评论 + expo 夏季衣橱合入后）→ 786 tests（2026-07-21 全绿，培训附件类型/备注合入后）**

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

### P1（重要）

-1. **OKKI 推单收尾**（开发侧 2026-07-13 全部完成：真实推单 + 幂等编辑 + 非标合并 + 企业必填字段 066/068，细节见 docs/module-notes.md invoice 节；首推真单曾被必填字段拒绝，字段已接线待重试）：
   - ①生产服务器 `backend/.env` 加 `OKKI_CLIENT_ID/SECRET` 后部署重启（deploy 不同步 .env）
   - ②运营配置三项：业务员 OKKI 部门（用户管理→编辑用户，Stella 建议「专治不服」——历史 676 单中 675 单归属它）；设置页配置**通用产品**（生产单推单必需，目前未配）；其余业务员绑定补齐
   - ③首推重试（INV20260710-001 已具备条件，差 Stella 部门）：**无沙箱产生真实订单**；推完人工核对订单总额/明细行数/业绩归属/cost_list 计入方式与「运费改 0 重推」语义
   - ④token 明文入库 vs 需求文档"加密"待拍板；代开票场景（业绩归属=创建人且无编辑入口）出现时需先补「指定业务员」能力

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
| [mcp-tracking-integration.md](mcp-tracking-integration.md) | ✅ | MCP 网关物流工具接入说明（051） |
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
