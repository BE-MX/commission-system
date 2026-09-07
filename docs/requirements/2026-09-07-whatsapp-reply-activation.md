# WhatsApp 话术助手：验收与启用

本地实现版本 1.3.0。默认关闭，尚未生产启用；本文是后续操作说明，不构成部署、付费模型调用或外发事实授权。

## 已准备的配置

| 配置 | 默认值及作用 |
| --- | --- |
| `WHATSAPP_REPLY_ENABLED` | `false`，总开关 |
| `WHATSAPP_REPLY_PLANNER_PRESET` | `whatsapp_reply_planner`，复盘/检索规划 |
| `WHATSAPP_REPLY_GENERATOR_PRESET` | `whatsapp_reply_generator`，受知识约束生成 |
| `WHATSAPP_REPLY_TIMEOUT_SECONDS` | 30，整体上限不高于 30 秒 |
| `WHATSAPP_REPLY_MAX_CONTEXT_CHARS` | 12000，可降低；扩展获取后按完整最近消息截断 |
| `WHATSAPP_REPLY_RATE_PER_MINUTE` / `WHATSAPP_REPLY_DAILY_REQUESTS` | 6 / 100，与翻译独立 |
| `WHATSAPP_REPLY_SOURCE_BINDINGS` | 空列表；无已核验必需政策时只返回安全澄清 |

启动 bootstrap 会从当前收件翻译 direct 预设准备两个**关闭**的独立预设，planner/generator 分别设置 1,400/1,800 输出 token 上限。不会改翻译，不覆盖已有或被管理员删除的同名配置。预设的 messages/tools/stream/model 等保留参数禁止覆盖，`n` 只能为 1。

部署授权后按项目统一入口处理迁移 141，再启动应用准备权限和关闭的预设。管理员给试用员工分配 `whatsapp_reply:write`，同时保留设备所需的翻译权限及实际知识库读取权限。不要在开发机启动带共享生产配置的写入流程或直接执行 `alembic upgrade`。

## 准备知识用途（先审内容，再配置）

从 backend 运行只读检查，可使用已有环境文件，但不得复制或输出其中的密钥：

```powershell
python -m scripts.inspect_whatsapp_reply_sources --env-file PATH_TO_EXISTING_ENV --user-id EMPLOYEE_ID --document-id DOCUMENT_ID
```

默认只输出修订、章节哈希、长度等元数据，每项用途均为 `blocked`。`--show-text` 只用于查看该真实员工当前有权读取的已发布知识，不上传客户聊天。检查连接使用 `SET SESSION TRANSACTION READ ONLY`，不修改知识或日志。

2026-09-07 只读预检可见设计相关文档 349/350/351/388/398，对应发布修订 373/374/378/434/488。它们只是当时的可读事实，不是外发批准；启用时必须重新检查。优先核验样品费、抵扣/退款、交期及历史承诺冲突，方法章节只标为 method，不必重整整个知识库。

每个绑定只保留以下字段，检查输出的 `version_no/chars/within_budget` 不属于配置字段：

```json
{
  "document_id": 123,
  "revision_id": 456,
  "section_index": 0,
  "content_hash": "64-character-sha256-from-inspection",
  "policy_version": "approved-policy-version",
  "purpose": "blocked",
  "mandatory": false
}
```

以上为格式示例，不能原样启用。内容负责人核验后：方法论标 `method`；确实允许对客户披露的稳定事实标 `public_fact`；承诺边界标 `constraint`。`mandatory=true` 仅适用于必需 constraint。每段须不超过 1,200 字符，所有必需政策须同时装入最多 6 段/6,000 字符预算，并为匹配事实留空间；不截掉条件或把全部方法文档设为必需。不能无条件沿用过去卖方说过的价格、退款或交期。

发布修订/章节改动后旧绑定失效；未经重新核验不能继承 public_fact。必需来源不可读、变版或超预算时，不继续自由生成商务承诺。

## 合成验收入口

普通离线回归不会调用模型。`scripts/whatsapp_reply_cases.py` 有 30 条原创合成用例（英语/德语各 15），逐项列出业务判据；禁止替换成真实 WhatsApp 文本。

取得单次付费测试授权后才运行：

```powershell
python -m pytest -p scripts.whatsapp_reply_evaluation tests/test_whatsapp_reply_model_evaluation.py --reply-eval-paid --reply-eval-env PATH_TO_EXISTING_ENV -s -q
```

每次最多 30 场景/60 次文本模型调用，无自动重试；只读复制现有 provider/model 配置到测试进程内存，所有设备、知识、调用日志和请求记录写隔离内存 SQLite。真实调用仍通过话术服务和 AI facade，输出仅 case ID、状态、耗时、token 聚合，不打印正文或密钥。正常测试默认跳过此项。

此入口证明结构、服务行为和时延，**不证明销售语义可用**。后续业务负责人应在不落聊天/草稿日志的试用预览中盲评“直接可用/轻改/退回”，记录分类及失败类别；严重错误必须为 0。目标中位耗时 ≤8 秒、P95 ≤15 秒，未达到须如实报告。实际产品知识召回仍需用已核验来源配置验证，不能用合成知识结果代替。

## 开放试用前仍需完成

1. 授权并完成真实模型基线与业务语义盲评；确认供应商对发送文本的数据保留设置。
2. 内容负责人核验来源用途和冲突政策，管理员配置独立模型/权限；141 迁移需目标环境的统一部署验证。
3. 获得目标环境部署/试用授权后开启总开关，安装 1.3.0。小范围实际预览只确认业务可用性，不让扩展发送消息。

当前没有执行以上付费调用、生产配置、生产迁移或发布。仅安装扩展不会使尚未启用的后端话术功能可用；原有翻译保持可用。
