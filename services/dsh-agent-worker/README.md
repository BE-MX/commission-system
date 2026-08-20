# 方舟 DSH Agent Worker

这是 DSH 的受控执行适配层，不是第二套业务后台。方舟负责 Run 状态机、租约、用户与数据权限、模型凭证、Token 预算、事件账本和成果验收；Worker 每次只领取一个 `runtime=dsh` 的 Run，并把短时 Run Token 同时用于方舟模型网关与 MCP。

## 已实现边界

- 固定 `dsh-v0.1.0-rc.8`（上游 commit `141eb6fef83422698aef7a981029e843e8161534`），启动时校验 Python distribution 版本 `0.1.0rc8`，版本漂移直接拒绝领取任务。
- `cordis.safe.yml` 只装 Agent spine、DeepSeek LLM、Ark MCP 与 JSONL session persistence；没有 shell、文件系统、编辑器、jobs、skills、subagent 或 workspace context。
- 模型 API Key 实际是单 Run JWT；真实模型凭证只存在方舟 AI Provider。MCP 使用同一短时 JWT，并由 Profile tool allowlist 与用户当前权限双重收敛。
- DSH 原始流不写方舟：仅上传步骤、Token、工具名、调用参数哈希、成功/失败等规范事件。最终 JSON 通过 Profile schema 和 evidence policy 后才成为草稿成果。
- Worker 租约心跳可发现取消；成果提交网络结果不确定时标记 `ambiguous`，不自动重试。

## 上游 SDK 当前发布状态

截至 2026-08-20，PyPI 已发布官方 `0.1.0rc7` SDK/Runtime wheel，但 rc7 的 Runtime 闭包不含 `@deepseek-ai/dsh-mcp-client`，无法承载方舟的受控 MCP 取数；真实 Runtime 回归会明确拒绝把它当作生产基线。`dsh-v0.1.0-rc.8` 已在上游固定 tag 中补齐 MCP Client，但 GitHub Release 暂无 wheel 资产，因此必须从上面的固定 commit 构建两只 rc8 wheel、写入内部制品库并按 SHA-256 安装。不要从浮动 `master` 构建生产 Worker。

仓库脚本会校验 tag 对应 commit、构建当前机器平台的单文件 Runtime 与 SDK wheel，并输出校验和：

```bash
services/dsh-agent-worker/scripts/build_dsh_release.sh /tmp/dsh-rc8-wheels
```

构建机需要 Node 24、pnpm 11、Python 3.10+ 与 `uv`；Linux Runtime 必须在目标架构的 manylinux 2.28 构建环境中生成。升级 DSH 必须作为独立变更重新跑真实 Runtime smoke、权限和事件契约回归。

仓库的 `DSH rc8 manylinux candidate` GitHub Actions 流水线固定 manylinux/Rocky 镜像 digest、Node/pnpm/uv 下载哈希、`@yao-pkg/pkg` 完整传递依赖 lock 和 Actions commit。它先在非特权用户下构建不可变候选，再在独立 Rocky 8（glibc 2.28）Job 中以只读 bundle、非特权用户运行完整 Worker 测试和真实 Runtime+MCP smoke，最后由第三个干净 Job 重新校验并生成 GitHub OIDC provenance。验证器同时检查 wheel RECORD、轮内许可证、SDK 依赖、两个固定 ELF payload/执行位/架构、DT_NEEDED allowlist、glibc 符号和 auditwheel policy。只有三段流水线全绿后才可下载 90 天留存的 `dsh-rc8-manylinux_2_28-x86_64-candidate-<commit>`；构建日志、第一段 untrusted artifact 或单独 wheel 都不是生产制品。

## 安装与配置

```bash
python -m venv /opt/leshine-ark-dsh/.venv
/opt/leshine-ark-dsh/.venv/bin/pip install -r requirements.txt
/opt/leshine-ark-dsh/.venv/bin/pip install \
  deepseek_harness_sdk-0.1.0rc8-py3-none-any.whl \
  deepseek_harness_runtime_bin-0.1.0rc8-py3-none-manylinux_2_28_x86_64.whl
/opt/leshine-ark-dsh/.venv/bin/python -c \
  "from importlib.metadata import version; assert version('deepseek-harness-sdk') == version('deepseek-harness-runtime-bin') == '0.1.0rc8'"
python services/dsh-agent-worker/scripts/verify_dsh_release.py \
  /path/to/release-bundle --source-sha <expected-40-char-git-sha>
```

候选进入内部制品库前还必须执行 `gh attestation verify --repo BE-MX/commission-system <bundle-files>`，确认 signer workflow 为本仓库 `.github/workflows/dsh-manylinux-release.yml`、source ref 为受保护 `main`、source SHA 与上面的 `--source-sha` 相同。功能分支产生的 candidate 只用于兼容性验证，不能晋级生产。

复制本目录的 `.env.example` 为 `/etc/leshine/ark-dsh-worker.env` 并设为 `0600`。Worker 明文 token 要生成独立随机值，后台只配置 SHA-256：

```text
AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON={"dsh-worker-01":["<sha256>"]}
AGENT_RUNTIME_WORKER_RUNTIMES_JSON={"dsh-worker-01":["dsh"]}
AGENT_RUNTIME_RUN_TOKEN_SECRET=<独立高熵密钥>
```

Worker 环境必须配置 `ARK_BASE_URL`、同源 `ARK_MCP_URL`、`ARK_AGENT_WORKER_ID`、
`ARK_AGENT_WORKER_TOKEN` 和仅 Worker 用户可读的 `ARK_DSH_SESSION_ROOT`。非本机地址拒绝 HTTP，
MCP 与方舟不同源时拒绝启动，避免单 Run 委托令牌被转发。本地 `session.jsonl` 默认保留 90 天；
Worker 每日只清理 Session 根目录内过期的常规日志，不跟随符号链接，可用
`ARK_DSH_SESSION_RETENTION_DAYS` 缩短但不能设为 0。

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
RUN_REAL_DSH_SMOKE=1 PYTHONPATH=services/dsh-agent-worker \
  python -m pytest services/dsh-agent-worker/tests/test_real_runtime_integration.py -q
```

首次灰度只开内部测试账号和 `customer_order_copilot`。确认任务中心能看到连续事件、取消生效、成果保持 `draft` 且模型日志没有原文后，再开定时复购分析。新客户开发仅运行 shadow，不得写正式线索或发送消息。
