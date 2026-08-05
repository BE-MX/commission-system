# 设计部 AI 生图工作台：Phase 0 能力冻结记录

> 状态：**完成**
> 验证日期：2026-08-05（Asia/Shanghai）
> 目标 Preset：`design_image_generation`
> 目标 Provider：TeamRouter（ID 10）
> 模型：`gpt-image-2`

## 1. 冻结结论

1. TeamRouter 的 `/v1/images/generations` 与 `/v1/images/edits` 均支持 `gpt-image-2`。
2. `/v1/images/edits` 支持 multipart 中重复两个 `image` 字段。
3. `low / medium / high` 均被 TeamRouter 接受，并显著改变输出 token 预算和耗时，不是完全忽略参数；本轮没有保存图片做盲评，不能据此宣称视觉质量按档位必然提高。V1 可保留三档，默认 `medium`，灰度期补设计师盲评。
4. `1024x1024`、`1024x1536`、`1536x1024` 三种标准尺寸全部返回正确像素。
5. generation 与 edit 均返回 `b64_json`；V1 优先实现 base64 落私有文件路径。
6. `usage` 有完整的文本/图片输入输出细分字段，可用于成本估算和审计。
7. 独立 Preset 已创建，参数只有 `{"output_format": "png"}`，未配置或发送 `input_fidelity`。
8. `expo_wig_composite` 保持原配置，仍含 `input_fidelity=high`，Phase 0 未改写其行为。
9. 正式入口固定到办公室生产主实例；北京展会实例不得运行本模块 Worker。
10. TeamRouter 未公开可核验的价格表，模型元数据也没有价格字段。不能声称其账单等于 OpenAI 官方价格。

完整请求 ID、耗时、usage 和脱敏响应见：
`docs/requirements/evidence/2026-08-05-design-image-provider-probe.json`。

## 2. Preset 现网状态

| Preset | ID | Provider | model | parameters | 结论 |
|---|---:|---|---|---|---|
| `design_image_generation` | 19 | TeamRouter / 10 | `gpt-image-2` | `{"output_format":"png"}` | 新建且启用 |
| `expo_wig_composite` | 13 | TeamRouter / 10 | `gpt-image-2` | `{"max_tokens":4096,"input_fidelity":"high"}` | 未修改 |

创建操作幂等：同名有效 Preset 再执行只校验，不覆盖管理员配置；并发首次创建发生唯一键竞争时回滚并读取胜出记录；同名记录已软删除时明确拒绝，不自动复活管理员删除的配置。若出现错误模型、禁用 Provider 或 `input_fidelity`，探针立即拒绝继续。

## 3. Provider 实测

### 3.1 模型发现

- `GET /v1/models`：HTTP 200；
- request ID：`2ba11561-1eac-480d-861f-17734424a430`；
- 耗时：371ms；
- 返回 31 个模型，包含 `gpt-image-2`；
- `gpt-image-2` 元数据仅有 `id/object/owned_by`，没有价格。

### 3.2 generation

| quality | size | HTTP | 耗时 | input | output | total | 实际像素 |
|---|---|---:|---:|---:|---:|---:|---|
| low | 1024x1024 | 200 | 30,022ms | 35 | 196 | 231 | 1024x1024 |
| medium | 1024x1024 | 200 | 44,896ms | 35 | 1,756 | 1,791 | 1024x1024 |
| high | 1024x1024 | 200 | 118,835ms | 35 | 7,024 | 7,059 | 1024x1024 |
| low | 1024x1536 | 200 | 25,164ms | 35 | 158 | 193 | 1024x1536 |
| low | 1536x1024 | 200 | 16,433ms | 35 | 158 | 193 | 1536x1024 |

三档质量的输出图片 token 差异约为 `196 → 1,756 → 7,024`，同时耗时显著增加，证明 Provider 至少接受该参数并改变了生成预算。每档只有一次随机样本，且出于脱敏要求没有保存画面，因此不能证明视觉质量一定提高，也不能证明稳定延迟；后续必须用非敏感代表性任务做设计师盲评，并用生产分位数监控延迟，不把本表当 SLA。

### 3.3 多图 edit

第一次使用仓库品牌 Logo 作为两张输入图，上游返回 HTTP 400 / `moderation_blocked`。这证明 multipart 已到达模型侧，但不能证明编辑成功，因此更换为内存生成的无文字、无品牌几何图再次验证：

- repeated fields：`image`, `image`；
- HTTP 200；
- request ID：`05776846-c01e-40d0-bb0d-d9b43334cab9`；
- 耗时：21,345ms；
- 输入：2,092 tokens，其中 image 2,048、text 44；
- 输出：196 image tokens；
- 总计：2,288 tokens；
- 返回：`b64_json`，PNG 1024x1024。

## 4. 错误契约

本次在目标 Provider 上真实观察到：

| 场景 | HTTP / code | 脱敏错误体结论 | 产品处理 |
|---|---|---|---|
| 无效模型 | 400 / `model_not_available` | 返回模型不可用与 trace ID | 配置错误，管理员处理，不向设计师暴露模型名 |
| 安全策略拦截 | 400 / `moderation_blocked` | 返回 safety rejection 与 request ID | 告知用户调整图片或描述，可手动重试 |

本次没有自然出现 429、502、503、504 或 ReadTimeout。Phase 0 不通过压测、断网或长请求故障注入刻意制造这些状态，避免无意义计费和影响共享 Provider。冻结处理策略如下：

- 429：不自动重试，展示稍后手动重试；
- 502/503：复用现有快速失败重试策略；
- 504/ReadTimeout：不自动重试，避免叠加请求和重复计费；
- 记录 HTTP 状态、Provider request/trace ID、脱敏错误体和耗时；
- 后续生产首次自然出现上述错误时，把真实错误体补入本记录。

历史 `AiCallLog` 中存在其他 Provider 的 502/503/连接重置证据，但不能冒充 TeamRouter 当前错误契约，故不写入目标 Provider 结论。

## 5. 价格与成本口径

2026-08-05 OpenAI 官方公开标准价：

- image input：$8 / 1M tokens；cached image input：$2 / 1M tokens；
- image output：$30 / 1M tokens；
- text input：$5 / 1M tokens。

来源：<https://developers.openai.com/api/docs/pricing>。

TeamRouter 公网页面未找到计价表，`GET /v1/models` 也不返回价格，本次 API 响应仅返回 usage、不返回金额。因此：

- 业务表保存 Provider 原始 usage 明细；
- 页面额度首期按任务次数治理，不显示未经供应商确认的人民币金额；
- 管理端可显示“OpenAI 官方等价成本（估算）”，必须明确标注非 TeamRouter 账单；
- 实际结算以 TeamRouter 后台账单或供应商书面报价为准；拿到账单后再冻结人民币成本公式。

按官方标准价粗算，本次 1024x1024 generation 的主要 image output 成本约为：low $0.00588、medium $0.05268、high $0.21072，尚未计入少量文本输入。该估算只用于理解档位数量级。

## 6. 上传与部署拓扑

### 6.1 现网证据

新加坡主站 Nginx 的当前配置：

- `server_name leshine.work www.leshine.work`；
- server 级 `client_max_body_size 5m`；
- `location /api/` 全部 `proxy_pass http://127.0.0.1:8002`；
- `8002` 是 frp 回办公室生产后端的唯一入口。

办公室生产实例按 runbook 为 `192.168.101.193:8001`，`SCHEDULER_ENABLED=true`；北京展会实例明确 `SCHEDULER_ENABLED=false`，只与办公室实例共享数据库，不共享本地磁盘。

### 6.2 冻结方案

- `/api/design-image/*`、任务 Worker、`DESIGN_IMAGE_STORAGE_ROOT` 全部部署在办公室生产实例；
- 北京展会实例不得注册或领取 design image job；
- 主站继续经现有 `/api/` → frp `8002` 到办公室实例，不新增第二文件落点；
- 若未来将该路由切到北京实例，必须先迁移为共享 SMB/对象存储，不能只共享数据库；
- 当前 Nginx 5MB 与原方案“单图 20MB”冲突。V1 冻结为：浏览器可选择较大原图，但发送前自动归一化到单次 multipart 请求不超过 4MB；服务端仍校验真实格式、像素和解码安全；无法归一化时给出明确提示，不让请求静默 413；
- 若业务实测证明 4MB 归一化损害参考图质量，再为 `/api/design-image/` 单独提高 Nginx 上限，不扩大全站 `/api/` 上限。

## 7. Phase 1 输入

Phase 1 按以下已冻结契约实现：

- Preset：`design_image_generation`；
- model：`gpt-image-2`；
- 支持尺寸：正方形、竖版、横版三种标准尺寸；
- 支持质量：low/medium/high，默认 medium；
- 响应优先路径：`b64_json`；
- usage 必须保留 `input_tokens_details` 与 `output_tokens_details`；
- 不发送 `input_fidelity`；
- 单次上传传输体目标 ≤4MB；
- 正式 Worker 只能运行在办公室生产主实例。

## 8. 复现命令

探针不会输出密钥或保存生成图片。开发机从独立 worktree 执行时，需要显式指向主目录 `.env`：

```powershell
$env:PYTHONPATH='D:\MyProgram\commission-system-codex-design-image-phase0\backend'
$env:ARK_PROBE_ENV_FILE='D:\MyProgram\commission-system\backend\.env'
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe `
  D:\MyProgram\commission-system-codex-design-image-phase0\backend\scripts\design_image_provider_probe.py `
  --run
```

完整探针与单独 edit 探针都使用无品牌的内存几何图。只验证多图端点时执行：

```powershell
D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe `
  D:\MyProgram\commission-system-codex-design-image-phase0\backend\scripts\design_image_provider_probe.py `
  --edit-only
```
