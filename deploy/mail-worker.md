# 北京邮件 Worker

受限 Worker 每分钟向 `https://leshine.cloud/api/mail-outreach/worker` 请求本人绑定邮箱，一轮最多认领一封已批准任务。只使用主站返回的固定收件人、主题和正文，后台与 Worker 双重限制验收收件人为 `86muliang@163.com`。仅 `+me` / 收件列表允许有限重试；`+send` 绝不重试。`queued=true` 是通道接受，不能显示为送达。

## 路径与固定依赖

- 北京 `ubuntu@154.8.205.162`，systemd `ark-mail-outreach`，系统用户 `ark-mail`。
- 候选 `/opt/ark-mail-outreach/releases/<SHA>`；独立 Node `v22.23.2` 官方 SHA-256 校验，CLI `@tencent-qqmail/agently-cli@1.0.18` 用随版本提交的 npm lock/integrity 安装。Worker 不使用智能排程包，因此不要求 Node 24。
- OAuth HOME `/var/lib/ark-mail-outreach/home`；`AGENTLY_WORKSPACE=ark-mail-beijing`。所有 OAuth 凭据仅留北京，不复制 Windows DPAPI 文件。
- 发件日志/收件游标 `/var/lib/ark-mail-outreach`；服务文件锁禁止同机双实例；该目录不可随代码发布覆盖、复制、清空。
- 健康 `127.0.0.1:7911/health`，不公开 Nginx 入口。包含代码 revision、授权绑定数、在途状态及待补回执标志，不含令牌/正文。

## 初次准备

先提交并审查完整候选；从办公室受管 `.deploy_state/sources/<SHA>/deploy/deploy.bat` 执行，固定 `--live-root D:/commission-system --revision <SHA> --no-pull`。专项阶段不切换两台应用，也不启动邮件服务：

```text
deploy.bat --live-root D:/commission-system --revision <SHA> --no-pull --mail-worker-stage prepare
deploy.bat --live-root D:/commission-system --revision <SHA> --no-pull --mail-worker-stage provision
deploy.bat --live-root D:/commission-system --revision <SHA> --no-pull --mail-worker-stage configure
deploy.bat --live-root D:/commission-system --revision <SHA> --no-pull --mail-worker-stage oauth
```

OAuth 入口输出的原始授权 URL 交由操作者打开，等待成功；失败/超时不自动重跑。业务邮箱管理中绑定 `worker_identity=ark-mail-beijing`、`cli_workspace=ark-mail-beijing`、发件人 `leshinehair@agent.qq.com`。

准备/OAuth 阶段保持发送关闭。实际闭环验收前，只有在本轮已授权发送的范围内，显式执行 `--mail-worker-stage enable-sending`（仍固定上述 live-root/revision/no-pull）。此阶段复验北京 OAuth，沿用原受限 plan/Token，只接受两端 configured-false 或已完成的 desired-true 配置，CAS 改为发送开启并保留备份/独立回执；收件白名单仍只有 `86muliang@163.com`。它不重启服务，随后通过正常完整发布激活配置。普通发布不会自动打开发送，也不应再次运行 configure 来覆盖启用状态。

运行配置为 root-only `/etc/leshine/ark-mail-outreach.env`，内容如下（没有明文 Token）：

```text
ARK_BASE_URL=https://leshine.cloud
MAIL_WORKER_TOKEN_FILE=/etc/leshine/ark-mail-outreach.token
MAIL_OUTREACH_ALLOWED_RECIPIENTS=86muliang@163.com
```

`configure` 只从办公室安装根运行，在受限 `.deploy_state/credentials/mail-worker` 生成随机 Token 与耐久计划，CAS 核对两端环境文件摘要，保存原始备份，再同步配置；重跑沿用相同 Token/attempt，不重新生成。Token 保存到北京上述文件，owner root、group ark-mail、0640；两台应用配置相同 SHA-256 的 `MAIL_OUTREACH_WORKER_TOKENS_JSON={"ark-mail-beijing":"<SHA256>"}`，验收收件白名单同步、发送总开关保持 false，不重启任何服务。北京原环境/配置备份留在 root-only `/opt/ark-mail-outreach/configuration/<attempt>`；原环境文件 owner/mode/ACL 保留。配置摘要变化即拒绝覆盖。不得把 Token 写进命令、Git、发布回执或日志。Worker 只能收发已绑定邮箱，不能批准内容。

## 完整发布与恢复

正常 `deploy.bat --revision <SHA> --no-pull --prepare-only` 会校验配置、OAuth、依赖和候选摘要；准备阶段不停止服务。去掉 `--prepare-only` 后，发布器在 schema/应用切换前冻结邮件领取并等待发送结束；先补交耐久回执，再继续原统一发布流程。北京后端及静态站完成后，才更新邮件 unit 并核对实际代码 revision 和 OAuth 绑定健康。

发送前先 fsync 一份 `unknown` 日志，发送完成后 fsync `accepted/failed_safe/unknown`。进程重启只重传同一 job+fencing 的结果；后端按相同结果幂等处理，进程不能再次启动 CLI 发送。发送超时、非零退出、JSON 不完整都记未知，只有确认 CLI 未启动才安全失败。临时正文是受限目录内的相对文件，正常退出会清理。

冻结时留下 `freeze.json`，停止/故障恢复期间即使进程重新启动也只补回执，不领取新任务。`release-current.json` 保存原 running/enabled 基线；未完成发布必须使用相同 revision/release_id 继续，不能覆盖日志或直接启动旧 Worker。原来停用的服务保持停用，首次安装在全部预检完成后才启用。回执无法核对时阻断发布，保留日志供核查；不要删除 `pending.json` 来清障。

服务激活失败保持恢复证据，不恢复可能与新 schema 不兼容的旧程序。`active` 或健康端口可达不能替代真实邮件闭环验收；必须从主站人工审批、唯一验收地址发送、记录通道回执，并核对收件事件。
