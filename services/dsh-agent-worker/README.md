# 方舟 DSH Agent Worker

这是 DSH 的受控执行适配层，不是第二套业务后台。方舟负责 Run 状态机、租约、用户与数据权限、模型凭证、Token 预算、事件账本和成果验收；Worker 每次只领取一个 `runtime=dsh` 的 Run，并把短时 Run Token 同时用于方舟模型网关与 MCP。

## 已实现边界

- 固定 `dsh-v0.1.0-rc.8`（上游 commit `141eb6fef83422698aef7a981029e843e8161534`），启动时校验 Python distribution 版本 `0.1.0rc8`。
- `cordis.safe.yml` 只装 Agent spine、DeepSeek LLM、Ark MCP 与 JSONL session persistence；没有 shell、文件系统、编辑器、jobs、skills、subagent 或 workspace context。
- 模型 API Key 实际是单 Run JWT；真实模型凭证只存在方舟 AI Provider。MCP 使用同一短时 JWT，并由 Profile tool allowlist 与用户当前权限双重收敛。
- DSH 原始流不写方舟：仅上传步骤、Token、工具名、调用参数哈希、成功/失败等规范事件。最终 JSON 通过 Profile schema 和 evidence policy 后才成为草稿成果。
- Worker 租约心跳可发现取消；成果提交网络结果不确定时标记 `ambiguous`，不自动重试。

## 上游 SDK 当前发布状态

截至 2026-08-20，上游仓库文档已经声明 `deepseek-harness-sdk` / `deepseek-harness-runtime-bin`，但 PyPI 尚无可安装发行版，GitHub RC release 也没有 wheel 附件。因此仓库没有伪造一个可解析的 PyPI 依赖；未安装 SDK 时 Worker 会明确 fail-fast，并把 Run 置为失败。

在官方 wheel 发布前，按固定 tag 从源代码构建同版本 wheel：

```bash
git clone --branch dsh-v0.1.0-rc.8 --depth 1 https://github.com/deepseek-ai/deepseek-harness.git
cd deepseek-harness
pnpm install
pnpm exec tsx scripts/build-exe-for-python-sdk.ts --targets=node24-linux-x64
python scripts/build-python-release.py --package sdk --output-dir dist-python
python scripts/build-python-release.py --package runtime \
  --platform linux-x64 \
  --runtime-exe dist-exe/dsh-jsonrpc-agent-pkg-linux-x64 \
  --output-dir dist-python
```

把两只同版本 wheel 放入内部制品库，经 SHA-256 与许可证审查后安装。不要从浮动 `master` 构建生产 Worker。

## 安装与配置

```bash
python -m venv /opt/leshine-ark-dsh/.venv
/opt/leshine-ark-dsh/.venv/bin/pip install -r requirements.txt
/opt/leshine-ark-dsh/.venv/bin/pip install \
  deepseek_harness_sdk-0.1.0rc8-py3-none-any.whl \
  deepseek_harness_runtime_bin-0.1.0rc8-py3-none-linux_x86_64.whl
```

复制本目录的 `.env.example` 为 `/etc/leshine/ark-dsh-worker.env` 并设为 `0600`。Worker 明文 token 要生成独立随机值，后台只配置 SHA-256：

```text
AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON={"dsh-worker-01":["<sha256>"]}
AGENT_RUNTIME_RUN_TOKEN_SECRET=<独立高熵密钥>
```

Worker 环境必须配置 `ARK_BASE_URL`、同源 `ARK_MCP_URL`、`ARK_AGENT_WORKER_ID`、
`ARK_AGENT_WORKER_TOKEN` 和仅 Worker 用户可读的 `ARK_DSH_SESSION_ROOT`。非本机地址拒绝 HTTP，
MCP 与方舟不同源时拒绝启动，避免单 Run 委托令牌被转发。

完成 migration 118、确认三个 `agent_runtime_*` AI Preset 都绑定启用的 `direct/openai` Provider、部署 Worker 后，才依次开启：

```text
AGENT_RUNTIME_ENABLED=true
AGENT_RUNTIME_DSH_ENABLED=true
```

运行：

```bash
PYTHONPATH=services/dsh-agent-worker python -m ark_dsh_worker.main
```

systemd 安装与观测：

```bash
sudo install -m 0644 deploy/systemd/leshine-ark-dsh-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now leshine-ark-dsh-worker
sudo systemctl status leshine-ark-dsh-worker --no-pager
sudo journalctl -u leshine-ark-dsh-worker -n 100 --no-pager
```

紧急止损先关闭业务 Profile flag，阻止新建任务；再关闭 `AGENT_RUNTIME_DSH_ENABLED`，阻止领取排队任务；
最后停止 Worker。不要删除 Run、Event 或 Artifact，执行中失联的 Run 会在租约过期后进入 `ambiguous`，由人工核查。

## 验证

```bash
python -m pytest services/dsh-agent-worker/tests -q
python -m pytest backend/tests/test_agent_runtime.py -q
```

首次灰度只开内部测试账号和 `customer_order_copilot`。确认任务中心能看到连续事件、取消生效、成果保持 `draft` 且模型日志没有原文后，再开定时复购分析。新客户开发仅运行 shadow，不得写正式线索或发送消息。
