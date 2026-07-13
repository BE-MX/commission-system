# LeShine Ark Platform - 莱莎方舟平台

企业内部综合中台（FastAPI + Vue3 单体，~30 日活）。二十大业务模块：提成、订单发票、展会 AI 试戴、物流跟踪、运单上传(OCR)、设计预约、认证 RBAC、AI 接入、方舟洞见（含客户机会台/经营雷达）、素材中台、发色数字化、备货、生产订单、生产报工、报表中心(Stimulsoft)、微信小程序、数据概念治理、WhatsApp 同步、钉钉集成、短链。

**本文件是宪法：只写改变行为的规则。参考资料在指针区按需查阅，不要凭记忆写 API/表结构。**

## 技术栈与环境

- 后端：Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + APScheduler
- 前端：Vue 3 + Element Plus + Vite 5；微信小程序（生产报工）
- 数据库：腾讯云 RDS MySQL 双库——`commission_db`（读写）+ `lsordertest`（业务库只读跨查）；**开发/生产共用同一套库，迁移创建并验证后在开发机直接 `alembic upgrade head`，不等生产部署**（2026-07-12 亮哥指令；迁移必须兼容"老代码 + 新 schema"过渡期）
- 部署：Windows Server + NSSM；生产 = 腾讯云 Nginx 静态直出 + frp 内网穿透反代本地 8002（云端 frps，本地 frpc 挂 NSSM——不是 SSH 隧道，2026-07-10 核实）
- 环境变量：`backend/.env`（不进 git）；配置一律走 `app/core/config.py` 的 Settings，**禁止直读 os.environ**

## 命令与端口

```bash
start.bat                                   # 本地一键启动前后端（venv python，绕过 PATH 污染）
cd backend && pytest                        # 后端测试（asyncio_mode=auto）
cd backend && alembic upgrade head          # 迁移
cd frontend && npm run dev                  # 前端 dev :3000（代理 /api → 8001）
cd frontend && npm run build                # 构建
python scripts/check_conventions.py        # 完工前跑约定检查（见 DoD）
deploy\deploy.bat                           # 服务器部署（拉码→依赖→迁移→构建→SCP→重启双服务）
```

后端 API :8001 / 前端 dev :3000 / 生产 :443（云 Nginx）+ 本地 :8002。服务器上**只能用 deploy.bat**，手动 uvicorn 会抢端口。

## 项目结构（速览）

```
backend/app/
├── core/ bootstrap/ schedulers/ routers.py      # 基建；router 统一在 routers.py 注册
├── api/ services/ models/ schemas/ utils/       # 共享层（提成域老代码）——已冻结，不加新业务
├── auth/ design/ system/ dingtalk/ ai/ insight/ # 领域模块：app/<domain>/ 自包含
│   stock/ tracking/ asset/ color/ production/   #   router.py models.py schemas.py service.py(+子service)
│   report/ governance/ invoice/ expo/ mini/ whatsapp/
frontend/src/
├── config/navigation.js    # 路由+菜单唯一来源
├── api/clients.js          # axios client 唯一来源（auth.js 是唯一例外）
├── views/<domain>/         # 页面按域分目录；大页拆 composables/use*.js
├── composables/ components/ styles/tokens.css   # 共享层；tokens.css 是颜色唯一真相源
miniprogram/  services/whatsapp-connector/  deploy/  docs/  config/
```

## 硬约定（红线，违反即返工）

### 后端

1. **新业务一律领域模块** `app/<domain>/`（router/models/schemas/service 四件套，复杂域拆子 service）；共享层 `app/api|services|models|schemas` 冻结不加新文件
2. **业务逻辑写 service 层**，不写在路由层；router 在 `app/routers.py` 注册
3. **新端点必须**：权限 `Depends(require_permission/require_any_permission)`（super_admin 自动绕过；机器对机器端点白名单需注释说明）+ 统一信封 `from app.core.response import ok`（`{"code","message","data"}`）
4. **session**：请求用 `from app.core.database import get_db`；仅 scheduler / 线程池 / bootstrap 三类场景允许自建 `SessionLocal()`
5. **数据库变更只走 Alembic**：revision ID ≤32 字符；创建后立即 `git add`；FK 类型与目标列完全一致（含 unsigned）；MySQL DDL 不可回滚，迁移前自查
6. **异常不许无声吞**：except 至少 `logger.warning` + `print(flush=True)`（NSSM service.log 只认 print）；批量循环用 savepoint 隔离单条失败，commit 失败后必须 rollback
7. **AI 调用**只走 `from app.ai.service import chat`（preset 后台可配）；多模态 image_url 不传 detail；参数用 max_tokens
8. **新增权限三步**：`auth/service.py` 的 `seed_role_permissions` 加 code（seed 是 **upsert**，元数据每次启动刷新）→ 重启后端 → 角色管理页分配。动作词汇只允许 read/write/delete/admin + 已登记特例（白名单见 scripts/check_conventions.py 的 ALLOWED_PERM_ACTIONS）；数据范围权限（read_all/self_read 类）kind=data，控查询口径不控显隐
9. ORM relationship 默认 `noload`，由查询显式 selectinload/joinedload（主表有 LIMIT 或关联均值 >3 行用 selectinload）

### 前端

10. **navigation.js 是路由+菜单唯一来源**：新页面只加一条 entry（permission/anyPermission 声明，守卫统一拦截）；全屏页（如 /expo/kiosk）例外，在 router/index.js 顶层注册
11. **禁止自建 axios**：API 模块从 `api/clients.js` 取 client 并登记（auth.js 是唯一例外）
12. **单文件 >500 行必须拆** `views/<domain>/composables/use<Page>.js`（全部 state+方法），主文件留薄壳
13. **颜色用 tokens.css 变量**，不写裸 hex；UI 决策以 `DESIGN.md` 为准
13.5 **原型设计 / UI 动效任务强制加载 Emil Kowalski skill 组**：动手前先 `Skill: emil-design-eng`（UI 打磨与动效决策哲学）；动效代码完工后按 `~/.claude/skills/review-animations/STANDARDS.md` 逐条自查（该 skill 限用户 `/review-animations` 手动触发，模型侧读标准文件执行同级审查）；描述不清的动效效果用 `animation-vocabulary` 定位术语
14. **新列表页两个标杆**：标记/样式复制 `system/DictManagement.vue`；分页/搜索/反馈编排照 `views/expo/ExpoLeads.vue`（useListPage + utils/feedback + DetailDrawer；上传用 components/AppUpload）
15. 认证初始化判据是 `!auth.user` 而非 `!isLoggedIn`（accessToken 从 localStorage 预恢复，谨防"半登录态"）；**按钮级权限用全局指令 `v-permission` / `v-any-permission`**（directives/permission.js），新页面不再手写 `v-if="hasPermission(...)"`

### 通用

16. bat 脚本：UTF-8 + 首行 `chcp 65001 >nul`；`set VAR=value` 不带引号
17. 密钥/token/密码不进代码；git push 仅跨设备同步，等用户说才执行
18. **搬移/重命名函数前全局 grep 旧引用**（含函数体内延迟 import）——注册期不报错、运行期才炸
19. **小步提交**：一个功能拆 3~5 个提交（迁移/后端/前端/测试），每个提交可独立回滚
20. 展会试戴(expo)文案禁用词：便宜/划算/性价比/打折/薅羊毛；发量头皮判断只进 internal 字段
21. **移动端 `/m/` 冻结为素材域专用**，不再往里加新领域；新移动端需求走主站响应式或微信小程序两条既有路径

## 完工 DoD（每次改动落地前自查）

1. `python scripts/check_conventions.py` 无红项（查增量 diff：自建 axios / 新增裸 hex / 超 500 行 / 无权限端点 / 吞异常 / 迁移 ID 超长 / 共享层新增）
2. 涉及后端：`pytest` 通过；管钱管货的计算/状态机必须有测试
3. 涉及前端：`npm run build` 通过；UI 对照 DESIGN.md
4. **报告实际跑出的验证证据**，不说"应该没问题"
5. 满足任一条件派独立 agent 对抗性审查：跨 3+ 文件 / 涉提成·发票·回款·库存数量 / 状态机变更 / 迁移脚本（审查视角：边界条件、并发写、幂等、前后端契约）
6. 文档同步：新端点→`docs/api-reference.md`；新表→`docs/database.md`；新模块→auto-memory 建 `project_<domain>.md`
7. 详细清单（含新模块 9 步 checklist）见 `.claude/rules/checklists.md`

## 记忆协议（取代原 OpenWolf 全量协议）

- **生成代码前读 `.wolf/cerebrum.md`**（Do-Not-Repeat 是硬教训清单）
- **被用户纠正 / 踩到新坑 → 立即更新 cerebrum**（含日期）；模块知识 → auto-memory `project_*.md`
- 会话结束沉淀收敛为一条：有教训进 cerebrum，有模块知识进 auto-memory，都没有就不写
- `.wolf/` 的 anatomy.md / memory.md / buglog.json 已停用（2026-07-03 治理），不再读写

## 指针区（参考资料按需查阅，改动时同步更新对应文件——**清单类内容永远不写回本文件**，文档同步类任务如 /neat-freak 同样遵守此分层）

| 要查什么 | 去哪 |
|----------|------|
| API 端点清单（全模块） | `docs/api-reference.md` |
| 数据库表结构清单 | `docs/database.md` |
| 模块专题细节 + 各模块已踩坑（钉钉/报表/OCR/洞见管线/短链等） | `docs/module-notes.md` |
| 系统架构 / 数据流 / 部署拓扑 | `docs/architecture.md` |
| 项目状态 / 待办 / 技术债 | `docs/handoff.md` |
| 部署 / 故障排查 / 备份 | `docs/runbook.md` |
| 架构评估与治理路线图 | `docs/2026-07-03-architecture-assessment.md` |
| 设计系统（颜色/字体/间距/组件） | `DESIGN.md` |
| 历史教训 | `.wolf/cerebrum.md` |
| 需求与原型 | `docs/requirements/` |
