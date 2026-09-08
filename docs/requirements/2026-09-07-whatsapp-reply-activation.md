# WhatsApp 话术助手：验收与启用

扩展实现版本 1.3.0，配置默认关闭。2026-09-08 已按授权配置预设及 admin 试用权限，北京后端重启后确认启用；完整模型基线仍未达标。本文的操作说明不构成新增部署、付费模型调用或外发事实授权。

## 生成依据契约（2026-09-08，修复待部署）

生成输入为每段来源附上原始 `source_index`，另提供仅包含 `public_fact` 的 `allowed_fact_source_indices`；动态输出 schema 将引用编号限制在该列表。有来源不等于必须引用，不对过滤后的来源重新编号。

没有可对客事实时，生成指令与 schema 要求 `claims: []`，只作安全回应、复述客户已确认需求或最小澄清；方法与内部约束不能充当产品事实引用。schema 随提示词传入，当前仍为 JSON mode，不是供应商强制 schema 校验。独立输出 guard 保持不变，模型违反约束仍拒绝，不自动重试或剥除错误引用。

本地离线回归 107 项通过；另 1 项慢流超时测试在任务分支和未修改主分支均因请求未到达本地服务器而失败。本轮未调用真实模型、未部署；生效无需新增 `.env` 配置。当前只有方法与约束的试用知识配置不因此获得新的事实披露许可。

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

启动 bootstrap 会从当前收件翻译 direct 预设准备两个**关闭**的独立预设，planner/generator 分别设置 1,400/1,800 输出 token 上限；OpenAI 协议固定 `response_format={"type":"json_object"}`，不继承翻译专用 schema。不会改翻译，不覆盖已有或被管理员删除的同名配置；已存在的话术预设需管理员在启用前核对 JSON mode，重启不会自动修改它。预设的 messages/tools/stream/model 等保留参数禁止覆盖，`n` 只能为 1。

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

可重复传 `--reply-eval-case CASE_ID` 进行小样本诊断，重复 ID 不增加调用，未知 ID 在调用前拒绝。先做小样本结构验证，再在获批预算内扩大；诊断只打印结构/规则类别，不打印模型值或命中文本。

2026-09-07 获授权的首轮用了 59 次调用：修复 JSON mode 后复测 14 条，11 条返回建议、3 条安全拦截，中位 9.094 秒/P95 18.688 秒，**尚未达标**。完整结果见 [模型基线](2026-09-07-whatsapp-reply-model-baseline.md)。

## 开放试用前仍需完成

1. 授权并完成真实模型基线与业务语义盲评；确认供应商对发送文本的数据保留设置。
2. 内容负责人核验来源用途和冲突政策，管理员配置独立模型/权限；141 迁移需目标环境的统一部署验证。
3. 获得目标环境部署/试用授权后开启总开关，安装 1.3.0。小范围实际预览只确认业务可用性，不让扩展发送消息。

2026-09-07 首轮仅执行获授权的合成付费基线，未通过完整验收；当时未执行生产配置、生产迁移或发布。2026-09-08 已开放 admin 小范围试用，不代表完整验收通过；原有翻译保持可用。重启时权限 bootstrap 会重新授予共享 admin 角色话术权限，当前已收回该共享授权，后续重启需核验范围；本次生成修复不包含该独立权限问题。
