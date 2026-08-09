# 内部生图多输出确认设计

## 1. 目标

内部 AI 生图工作台需要正确处理“请生成 3 个角度的人像图”这类带数量、但没有说明输出载体的请求。

系统不能擅自决定把多个角度拼在一张图里，也不能直接创建多张图片并产生额外成本。只有语义明确时才直接执行；存在歧义时，在当前对话中用两个明确选项让用户确认。

本功能仅用于内部 `design_image` 工作台，不改变客户门户 `customer_image` 的单次生成语义。

## 2. 已确认的产品规则

### 2.1 数量边界

- 单次独立输出最少 2 张、最多 4 张。
- 支持阿拉伯数字 `2` 至 `4` 和中文数字“二/两/三/四”。
- 用户要求超过 4 张时不创建任务，提示拆分为多轮请求。
- 一张拼版图始终只创建一个 job；分别生成 N 张创建 N 个独立 job。

### 2.2 何时直接执行

以下表达视为明确要求一张拼版图：

- 一张图、同一张图、拼版、拼图、三视图、四视图、九宫格、排版展示。

以下表达视为明确要求多张独立图片：

- 分别生成、各生成一张、每个角度一张、独立图片、单独出图、生成 N 张。

明确模式不再弹确认卡片，直接创建对应任务。

### 2.3 何时要求确认

当请求同时满足以下条件时返回确认卡片：

1. 包含 2 至 4 的数量；
2. 包含“角度、视角、方向、张、款、版本、方案”等多输出语义；
3. 没有明确拼版词，也没有明确独立输出词。

确认前只保存用户消息和 assistant 确认消息，不创建 job，不占用并发，不调用 Provider。

### 2.4 标准角度

用户未指定具体角度时采用：

| 数量 | 标准角度 |
|---|---|
| 2 | 正面、侧面 45° |
| 3 | 正面、左侧 45°、右侧 45° |
| 4 | 正面、左侧 45°、右侧 45°、背面 |

用户明确列出角度且数量一致时，以用户角度为准。数量与列出的角度不一致时，确认卡片明确展示系统将使用的标准角度，避免静默猜测。

非角度类的“3 个方案/3 个版本”在选择独立输出后创建三个独立变体，提示词分别加入“独立变体 1/3、2/3、3/3，需与同组其他结果有可见差异”，但不虚构用户未指定的场景或属性。

## 3. 用户交互

确认消息直接出现在消息流中，不使用模态弹窗：

> 你希望如何生成这 3 个角度？
>
> 标准角度：正面、左侧 45°、右侧 45°

两个操作按钮：

- `一张三视图拼版`：副文案“3 个角度放在同一张图中 · 消耗 1 次”。
- `分别生成 3 张`：副文案“每个角度独立生成 · 消耗 3 次”。

交互约束：

- 按钮不预选，避免误产生额外成本。
- 点击后立即进入 submitting 状态，阻止重复点击。
- 服务端确认成功后，卡片显示已选择模式并锁定按钮。
- 刷新页面后确认卡片及已选择状态仍可恢复。
- 同一次确认不能改选；用户需要改变模式时重新发送一条消息。
- 多图批次或确认 action 只在该用户没有 queued/running 任务时接受；同一批 2–4 张在一个事务内整体入队，再由 worker 按每用户运行并发上限逐步执行。普通单图继续遵守现有“每 session 单活跃 + 每用户最大活跃数”规则，不把并发能力降成 1。
- 只做 160–200ms 的 opacity/transform 淡入；无装饰性逐项动画；`prefers-reduced-motion` 下取消位移。

## 4. 意图识别

新增纯函数模块 `backend/app/design_image/multi_output_intent.py`，不调用大模型。

输出契约：

```python
@dataclass(frozen=True, slots=True)
class MultiOutputIntent:
    mode: Literal["single", "composite", "separate", "clarify", "reject"]
    count: int
    labels: tuple[str, ...]
```

确定性解析便于测试、解释和审计。无法可靠识别时保持现有单图行为，不能因为出现任意数字就拦截请求，例如“1024×1024”“年龄 3 岁”“参考图 2”。

## 5. 数据与 API

### 5.1 消息交互数据

为 `ark_design_image_messages` 增加：

- 可空字符串 `client_request_id`：只写在 user message，用于没有 job 的 clarification turn 及多 job turn 幂等；同一 session 内唯一。
- 可空 JSON `interaction_json`：只保存结构化 UI 交互，不把 JSON 嵌进 `content`。

```json
{
  "type": "output_mode_confirmation",
  "status": "pending",
  "source_message_id": 101,
  "request_id": "turn-client-uuid",
  "count": 3,
  "labels": ["正面", "左侧 45°", "右侧 45°"],
  "request": {
    "base_asset_id": 12,
    "reference_asset_ids": [13, 14],
    "size": "1536x1024",
    "quality": "high"
  },
  "selected_mode": null
}
```

`request` 是确认后重建原 turn 所需的最小输入快照。创建 clarification 时即在同一事务内把引用资产写成 `message_id=user_message.id, status=draft`，保留原 `expires_at`，但不创建 job、不扣额度。`delete_draft_asset` 必须拒绝删除 `message_id` 非空的 draft；到期清理仍删除这种被放弃或长期未确认的附件。确认 action 成功创建全部 jobs 后才把资产置为 `attached` 并清空 `expires_at`。这样刷新后附件不会重新回流到 composer，也不能被草稿删除接口误删，同时废弃确认不会永久占用存储。解析与序列化只允许已定义字段；不得把提示词快照、Provider 参数或内部错误放入交互 JSON。

所有 turn 在创建消息前先按 `(session_id, client_request_id)` 查找已有 user message：已有 clarification 返回原确认消息，已有 jobs 返回该消息下全部 jobs。这样明确多图和歧义确认都不依赖“碰巧找到第一个 job”实现幂等。

### 5.2 创建 turn

现有 `POST /api/design-image/sessions/{session_id}/turns` 保留：

- 普通或明确拼版：返回 `mode=jobs` 和一个 job。
- 明确独立输出：返回 `mode=jobs` 和 2 至 4 个 jobs。
- 歧义：返回 `mode=clarification`、用户消息和 assistant 确认消息，`jobs=[]`。
- 超过 4 张：返回可行动的 400，不保存半成品消息。

响应由单个 `job` 改为 `jobs`；不保留旧字段兼容层，前后端同一提交升级。

### 5.3 确认 action

新增：

```text
POST /api/design-image/sessions/{session_id}/messages/{message_id}/actions
```

请求：

```json
{
  "action": "choose_output_mode",
  "mode": "composite",
  "request_id": "client-generated-uuid"
}
```

服务端在事务中：

1. 校验 session owner；
2. `SELECT ... FOR UPDATE` 锁定 assistant 确认消息；
3. 校验 interaction 仍为 pending；
4. 读取原 user message 和冻结的附件/尺寸/质量；
5. 创建一个或 N 个 jobs；
6. 写入 `selected_mode`、`resolved_at` 并提交。

同一 `request_id` 重试必须返回原任务，不得重复创建；确认已完成后改选返回 409。

## 6. 多任务执行

- 多个 jobs 继续属于同一个 session 和同一条 `request_message_id`。
- 不新增 job group 表；消息本身就是本轮结果分组，现有前端已经能按消息聚合多张 GenerationCard。
- 每个 job 冻结独立 prompt snapshot。角度任务在原提示后追加明确角度，并要求人物身份、服装、发型、背景与参考图一致。
- 拼版 job 的 prompt snapshot 也必须写入确认卡展示的全部标准角度，并明确要求在同一画布中排版；不能只把原始“生成 N 个角度”原样发送给 Provider。
- 多个 jobs 先全部进入 queued；`DESIGN_IMAGE_MAX_ACTIVE_PER_USER` 解释为每用户 running 上限，不再把同一批 queued 数量当成拒绝条件。
- 多图 HTTP 服务在 owner 锁下确认该用户没有任何 queued/running job，随后原子创建最多 4 个 queued jobs；普通单图维持现有活跃数规则。新的 turn 或确认在多图批次未结束前禁止提交。
- “多图批次仍活跃”由服务端查询判定：只要存在 queued/running job，且其 `request_message_id` 关联的根 jobs（`retry_of_job_id IS NULL`）总数大于 1，就阻止该用户在任何 session 创建普通 turn；即使 4 个根 jobs 已有 3 个终态、只剩 1 个 active，也必须等最后一个终态后才解除。普通单图失败后的 retry 与原 job 共用消息，但只有 1 个根 job，不得被误判成多图批次。
- 所有并发路径采用唯一锁序 `owner → job`。worker 先非锁定选择有 queued job 的候选 owner，再以 `FOR UPDATE SKIP LOCKED` 锁 owner，重新统计 running 数量，最后锁并领取该 owner 最早的 queued job；达到上限则跳过该用户。多个 worker 及 worker/HTTP 并发不得超限或死锁。
- 每个 job 独立成功、失败和重试；某张失败不回滚其他结果。
- 现有每日额度按每个独立 job 消耗；拼版只消耗一次。创建批次前必须原子校验整批额度足够，不能只创建部分任务。

## 7. 前端状态

- `MessageThread` 渲染 `interaction_json.type=output_mode_confirmation` 的确认卡片。
- `useImageStudio` 统一处理 create/resolve/retry 的 `mode=clarification|jobs` 响应，把 `jobs` 合并进现有 Map 并复用轮询；单任务 retry 也返回 `jobs:[retriedJob]`，不保留旧 `job` 字段。
- 确认提交期间只锁当前卡片，不锁侧栏、历史查看和下载。
- 当前 session 存在 pending/running 批次时，composer 继续保持禁用；确认卡片按钮仍可用于尚未创建任务的 pending clarification。
- API 失败时按钮恢复，并给出可行动提示；409 刷新 session，以服务端最终状态为准。

## 8. 错误与边界

- 数量超过 4：稳定错误码 `multi_output_limit`，安全消息 `一次最多生成 4 张，请拆成多轮请求。`，元数据含 `max_outputs=4`。
- 整批额度不足：稳定错误码 `daily_limit_exceeded`，不创建任何 job，安全元数据含 `remaining`。
- 附件在确认前失效或被删除：稳定错误码 `attachment_unavailable`，不创建 job，提示重新上传后发送新请求。
- 前端只透传上述白名单业务错误的安全消息和元数据；其他 400/422/429 继续使用通用文案，避免泄露内部异常。
- 重复确认：同 request ID 幂等返回；不同 request ID 改选返回 409。
- 解析器只决定输出形式，不重写用户业务要求。
- `n` 参数仍不用于多图；每张图片保持一个 Provider 请求和一个结果资产。

## 9. 验证标准

后端必须覆盖：

- 数字与中文数字、明确拼版、明确独立、歧义、误判保护、超过 4 张。
- 歧义 turn 不创建 job、不消耗额度、不调用 Provider。
- 确认事务、并发双击、幂等重试、改选冲突。
- 同一消息创建 2/3/4 个 jobs，角度 prompt 与额度正确。
- 64 字符 request ID 与不同 session 复用同一 request ID 时，派生 job key 仍为固定 64 字符且不冲突。
- 多 worker 并发领取不会突破每用户 running 上限。
- clarification draft 覆盖绑定后禁止手删、到期清理、成功确认转正和废弃确认不泄漏四条生命周期。
- 整批额度不足时零创建。
- 多 job 独立完成、失败和重试，不互相覆盖 assistant message 或资产。

前端必须覆盖：

- 确认卡片文案、标准角度、成本提示和按钮锁定。
- 刷新恢复 pending/resolved 状态。
- clarification 不启动 job polling；确认后多个 jobs 都进入轮询。
- retry 的统一 `jobs` 响应、白名单业务错误、409 刷新、失败恢复、reduced motion。

真实浏览器必须验证：

1. “生成 3 个角度的人像图”只出现确认卡，不生图；
2. 选择拼版后只出现一个任务；
3. 重新发同一请求并选择分别生成后出现三个独立任务；
4. 刷新页面状态不丢；
5. 快速双击只创建一批任务；
6. 手机宽度下按钮不溢出且可触控。

## 10. 非目标

- 不使用 LLM 做意图分类。
- 不支持一次超过 4 张。
- 不增加整组取消、整组重试或 job group 管理页。
- 不改变客户门户的生成次数和额度语义。
- 不通过 OpenAI `n` 参数一次取多张结果。
