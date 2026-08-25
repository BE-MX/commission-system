# 方舟 Agent Runtime 第一阶段实施规格

日期：2026-08-20（2026-08-25 更新）
状态：开发、真实 DSH Runtime E2E、Linux 候选构建/冒烟/OIDC 证明完成；待生产安装与 30/200/50 业务灰度验收
范围：统一 Agent 控制面、客户与订单副驾驶、复购行动卡、DSH 获客影子任务、AI 任务中心

## 1. 目标

第一阶段建立不绑定单一 Agent 内核的方舟控制面，并用 DeepSeek Harness（DSH）完成三个业务试点。
系统必须形成以下闭环：

1. 方舟以当前登录用户身份创建 Agent 任务并冻结业务上下文。
2. Runtime 只能使用 Profile 白名单与用户数据权限交集内的工具。
3. Agent 过程以追加事件记录，能够解释每个成果来自哪些模型与工具事件。
4. Agent 只提交结构化成果；业务写入由方舟校验、授权并执行。
5. 用户的接受、拒绝、修改和业务结果进入反馈事件。

## 2. 非目标

- 第一阶段不替换生产中的 OpenClaw 智能获客与邮件流程。
- 不向公网开放 DSH Web。
- 不允许 Agent 自动发邮件、承诺价格/库存/交期或修改客户归属。
- 不把 AI Chat 历史会话迁移为 Agent Session。
- Agent 事件不是业务表的事件溯源；业务数据库仍是业务事实来源。

## 3. 系统边界

### 3.1 方舟控制面

方舟负责用户身份、RBAC、数据范围、任务状态、租约、预算、工具授权、成果校验、反馈与审计。
新增领域模块为 `backend/app/agent_runtime/`。

### 3.2 Runtime

Runtime 通过统一 Ark Agent Contract 接入。第一阶段支持：

- `dsh`：交互副驾驶、行动卡分析、获客影子任务。
- `openclaw`：Contract 预留。首期正式智能获客仍走现有链路，以 SearchJob 作为同输入关联键，不伪装成已完成 Runtime 事件桥接。
- `native`：后续方舟内置确定性或单次模型任务预留。

DSH Worker 部署在独立 Linux 服务，主动领取任务，不连接方舟数据库，不持有长期模型密钥。

## 4. 核心概念

- Profile：不可变版本的 Agent 配置，包括 Runtime、模型路由、Prompt/Skill 哈希、工具白名单、预算和输出 Schema。
- Session：某用户围绕一个业务对象持续交互的上下文。
- Run：一次可独立完成、取消、失败和计量的 Agent 任务。
- Event：一次追加式运行事实，具有单调递增序号和幂等事件 ID。
- Artifact：通过 Schema 和证据校验后可供业务消费的成果。

## 5. Ark Agent Contract

### 5.1 状态机

允许的状态迁移：

```text
queued -> leased -> running -> waiting_input -> completed
  |          |         |              |             
  +----------+---------+--------------+-> cancelled
             +---------+--------------+-> failed
                       +--------------+-> ambiguous
```

规则：

- 每个用户最多同时运行配置数量的 Run。
- 一个 Session 第一阶段最多一个非终态 Run。
- 领取任务必须原子更新状态并返回一次性明文租约令牌，数据库只存 SHA-256。
- 心跳、追加事件、完成和失败都必须验证 worker、租约令牌和过期时间。
- 过期 Worker 不能写入终态。
- 模型请求已发出但结果不确定时进入 `ambiguous`，不得盲目自动重试。
- 业务成果以 `(run_id, artifact_type, content_sha256)` 幂等。

### 5.2 标准事件

首期事件类型：

- `run.created`、`run.claimed`、`run.requeued`、`run.started`
- `model.requested`、`model.responded`
- `plan.updated`
- `tool.requested`、`tool.succeeded`、`tool.failed`
- `artifact.created`、`artifact.validated`
- `user.feedback`
- `run.completed`、`run.failed`、`run.cancelled`、`run.ambiguous`

每条事件必须包含 `event_id`、`run_id`、`sequence_no`、`event_type`、`schema_version`、
`actor_type`、`visibility`、`payload`、`payload_sha256` 和时间。

### 5.3 权限

有效能力为：

```text
当前用户权限 ∩ Profile 工具白名单 ∩ 工具要求权限 ∩ Run 委托范围
```

Worker 使用单独机器身份领取任务。领取后获得短期 Run Token；Run Token 只能访问该 Run、该用户、
该 Profile 与白名单工具，且不能换取长期用户 Token。

## 6. 首期 Profile

### 6.1 `customer_order_copilot`

Runtime 为 DSH，模式为 interactive。只读工具：客户画像、订单时间线、复购分析、订单智能快照、
客户行动、知识检索、物流查询、产品价格查询。输出固定为：总结、关键发现、风险、建议行动、证据、待确认问题。

### 6.2 `repurchase_risk_analyst`

Runtime 为 DSH，模式为 scheduled。候选客户由确定性规则召回，Agent 只负责基于证据解释和生成行动草案。
成果经方舟校验后投影到 `ark_customer_actions`。

### 6.3 `sales_discovery_shadow`

Runtime 为 DSH，模式为 shadow。与正式 OpenClaw SearchJob 使用同一冻结输入，但成果只进入 Agent Artifact，
禁止写入正式公司、联系人、研究和邮件表。

## 7. API

业务 API：

- `GET /api/agent-runtime/profiles`
- `POST /api/agent-runtime/sessions`
- `GET /api/agent-runtime/sessions`
- `GET /api/agent-runtime/sessions/{id}`
- `POST /api/agent-runtime/sessions/{id}/runs`
- `GET /api/agent-runtime/runs/{id}`
- `POST /api/agent-runtime/runs/{id}/cancel`
- `GET /api/agent-runtime/runs/{id}/events`
- `GET /api/agent-runtime/runs/{id}/stream`
- `GET /api/agent-runtime/tasks`
- `POST /api/agent-runtime/artifacts/{id}/accept`
- `POST /api/agent-runtime/artifacts/{id}/reject`
- `POST /api/agent-runtime/runs/{id}/feedback`

Worker API：

- `POST /api/agent-runtime/worker/runs/claim`
- `POST /api/agent-runtime/worker/runs/{id}/heartbeat`
- `GET /api/agent-runtime/worker/runs/{id}/context`
- `POST /api/agent-runtime/worker/runs/{id}/events`
- `POST /api/agent-runtime/worker/runs/{id}/complete`
- `POST /api/agent-runtime/worker/runs/{id}/fail`

## 8. 业务不变量

### 8.1 客户与订单副驾驶

- 页面只提交客户 ID、服务器可验证的筛选器和用户问题，不提交整批业务数据。
- 所有定量结论必须引用工具输出证据。
- 保存跟进行动必须由当前用户显式确认。

### 8.2 复购行动卡

- 规则负责召回，DSH 不决定客户归属。
- 每个行动使用稳定 `source_fingerprint` 幂等。
- 已完成、已忽略和已延后行动不能被每日刷新覆盖。

### 8.3 获客影子任务

- Shadow Run 不能调用任何正式写入工具。
- 与 OpenClaw 的比较使用同一输入快照和盲评口径。
- 未通过质量、证据、重复率与成本门槛前不得切生产流量。

## 9. 安全与留存

- DSH Profile 禁止 shell、任意文件写入和无限制出网。
- 受控搜索工具必须限制协议、重定向、私网地址和响应体大小。
- 普通用户只能读取脱敏事件；原始事件使用现有 AI 加密能力加密。
- 原始事件默认保留 90 天，标准化事件与业务反馈按审计策略保留。
- Profile、Runtime、模型和影子抽样均有独立 Feature Flag。

## 10. 验收门槛

- 并发领取只有一个 Worker 成功，过期 Worker 无法提交。
- 事件重复提交零重复，事件序号无间隙。
- 数据权限、工具白名单和委托范围越权测试全部拒绝。
- 订单副驾驶 30 个标准问题中，可直接使用率达到 80%，定量证据绑定率 100%。
- 复购行动卡不少于 200 条，证据有效率不低于 95%，刷新不丢失任何用户状态。
- DSH 与 OpenClaw 完成不少于 50 个同输入影子对照任务，未达晋级门槛时保持影子模式。

## 11. 实施状态与外部阻塞

控制面、五表迁移、状态机、租约、短时委托令牌、模型/工具治理、三个 Profile、业务编排、
任务中心、运行时间线、部署模板、灰度开关和自动化测试均已实现。Feature Flag 默认关闭。

上游 PyPI 已发布 `0.1.0rc7` SDK/runtime wheel，但 rc7 Runtime 闭包不含 MCP Client，不能满足方舟受控取数边界。
仓库固定 `dsh-v0.1.0-rc.8` / `141eb6fef83422698aef7a981029e843e8161534`。除 macOS arm64 本地真实二进制
E2E 外，GitHub Actions run `32798681826` 已在 digest 固定的 manylinux 2.28 x86_64 构建器中完成 Linux 候选，
在 digest 固定的 Rocky 8.9 全新容器内以非特权用户完成真实 Runtime 冒烟，并在第三个全新 job 中复验后生成
GitHub OIDC/SLSA provenance。最终 reviewed artifact 为
`dsh-rc8-manylinux_2_28-x86_64-candidate-3b9a2e2c413ec479ef9cac179df261354d57a54d`；Runtime wheel
SHA-256 为 `ead23bd2a1802c96be35e7dcb14267ea7df99ea930c2de210b8b071e0d73bc1d`，auditwheel policy 为
`manylinux_2_28_x86_64`，2 个 ELF 的最高 GLIBC 符号为 2.28。本机下载后清单 7/7、OIDC attestation subjects 7/7
复验通过，签名限定 GitHub 托管 runner、同一 workflow、分支与 source SHA。候选仍位于 feature branch，尚未合入
main、安装生产或开放 Feature Flag，不能将“制品可安装”写成“生产已发布”。任务中心已提供版本化 30 题目录、按账号数据范围选择真实客户、权限/数据预检、二次确认启动和执行进度。正式题只使用当前工具可证明的画像、订单摘要、复购周期和行动数据；契约 hash 固定完整题库与评分规则、Profile/实际 Prompt/工具/Schema/限额、模型 Preset、Provider 非密钥运行参数及全局硬限额，变更后自动切换空 cohort 并拒绝旧 Run 继续调用模型。`GET /api/agent-runtime/evaluations/readiness` 以保守口径汇总 30/200/50 门槛：副驾驶只统计
`customer_order_copilot_v1` 当前 cohort 内不同 `evaluation_case_id`，影子对照只统计不同 `search_job`；业务样本未达标时
固定保持 Shadow，不得把“开发完成”标记成“业务灰度完成”。
