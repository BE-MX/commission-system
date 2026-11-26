# B 轨（未绑定线索）实施状态

> 更新：2026-11-26 · 对应设计：[design.md](design.md)（v1.1）· 状态：**代码已实现，待部署，功能开关默认关闭**

## 已完成

| 范围 | 位置 | 验证 |
|---|---|---|
| 数据模型（3 表，线索表含水位与跟进字段） | `backend/app/client_desk/models.py` 末尾 | 随测试 SQLite 建表 |
| 迁移 | `backend/alembic/versions/282_client_desk_unlinked.py`（接 `281_followup_recordings`） | 隔离 MySQL 验证，见「Codex 审查修复」 |
| 纯规则（水位、资料包转义、结果校验、弱匹配） | `backend/app/client_desk/unlinked/core.py` | 单测 |
| 线索同步、入队、租约队列、模型调用、写回、周梳理 | `backend/app/client_desk/unlinked/worker.py` | 单测（替身模型与授权） |
| 用户动作（已处理、不是客户、撤销、潜客、绑定、周报读取） | `backend/app/client_desk/unlinked/service.py` | 单测 |
| HTTP 接口，挂载 `/api/client-desk/unlinked` | `backend/app/client_desk/unlinked/router.py`、`backend/app/routers.py` | 导入检查 |
| 调度任务（默认不注册） | `backend/app/schedulers/client_desk.py`、`registry.py` | 导入检查 |
| 开关（默认全关，TM 独立于全局 feed 开关，即 U-D5） | `backend/app/core/config.py` | — |
| 闸门（TM，本人归属 + 无客户关联 + 当前快照） | `backend/app/alibaba_feed/business_service.py::unlinked_lead_item` | 正常试点、真实入库、撤权与角色权限均经真实 Feed 夹具测试 |
| 协议文档 | `backend/app/client_desk/protocol/unlinked_{daily,weekly}_v1.md` | — |
| 前端「未绑定线索」Tab（TM，三子视图） | `frontend/src/views/client_desk/Unlinked*.vue`、`useUnlinkedLeads.js`、`unlinkedLeadsModel.js` | 构建通过，私海测试 32 项通过 |
| 运行态修复：`state_dto` 返回复核字段（P0-4） | `backend/app/client_desk/service.py` | 相关回归 |

后端私海与阿里 Feed 共 319 项通过。前端私海与 TM 共 44 项通过，构建与增量约定检查通过。

## 审查修复记录

第一轮独立审查（新上下文的 Claude 代理，**非设计要求的 Codex 交叉审查**）发现 16 项问题，其中授权与写回、周报状态、周报次数、租约、水位、消息撤回、关联解除等均已修复，并补了对应回归测试（见测试文件中 `review regressions` 段）。**修复后未再做第二轮审查。**

## 2026-11-26 Codex 审查修复

- TM 试点启用后，由管理员单独确认未绑定线索的 AI 授权。授权后立即同步已有合格线索并按当日配额排队。非试点用户、撤权或权限失效的业务员无法读取、操作或触发分析。无 OKKI 绑定的试点仍可处理 TM 新客。
- 日分析和周报用消息证据及当前授权验证输出。普通追加消息保留旧证据，修订或撤回使相关旧内容失效。「不是客户」会清空内容，也会拦下在途周报的总览。
- 绑定与线索状态原子提交。解除后可立即再次绑定同一客户。正常卖家回复不改变「已处理」状态。生成周报后页面重新读取正文，「去处理」可找到待处理线索和未建档潜客。
- Claude 独立复核指出的即时同步、即时解绑、失效提示、周报写回和锁序问题已纳入修复。周报总览在部分证据失效时隐藏，下方保留依赖仍有效的行动条目。
- 迁移与 API 细节见 [数据库文档](../../database.md) 和 [API 文档](../../api-reference.md)。

## 未完成

| 项 | 说明 |
|---|---|
| WhatsApp（B3） | 未实现。`ark_whatsapp_accounts.unlinked_ai_allowed` 列与 WA 筛选未做，按设计 B3 视试点意愿再开 |
| 分析预设 `client_desk_unlinked` | 代码通过 `CLIENT_DESK_UNLINKED_PRESET_NAME` 引用，需在 AI 预设后台创建并配置 `max_tokens`（建议 1200），属于生产配置，未做 |
| 前端细节 | 「恢复」「重新分析」无入口；卡片当地时间依赖后端 `local_timezone`，目前为 null |
| 设计偏差 | 水位以 JSON 数对存储（设计写为分列）；处理接口为 `POST /prospect`（设计写为 PATCH）；无 `GET /threads/{id}`；TM 线程并发为串行（设计写并发 2）；绑定仅弱匹配（公司名），邮箱强匹配未做 |
| P0-1 / P0-2 / P1 | 生产预设 1800 → 4000 与发布 11-16 修复未动；埋点未做；P1 露出项未做（A 轨） |

## 上线前必须

1. 当前 Codex 工作树基于 `origin/main` 的 `281_followup_recordings`。发布前核对目标版本的迁移头。
2. 核对线上 `ark_users.id` 的实际列类型，与模型中 `mysql.INTEGER(unsigned=True)` 一致。
3. 隔离 MySQL 8.4 已核对离线升级 SQL、升降级、仅存周报时拒绝回退和空库重新升级。生产迁移只随部署入口执行。
4. 配置 AI 预设后，先开 `CLIENT_DESK_UNLINKED_ENABLED` 与 `CLIENT_DESK_UNLINKED_TM_ENABLED`，由管理员授权试点未绑定分析，再以试点账号跑一轮手动分析验收。
