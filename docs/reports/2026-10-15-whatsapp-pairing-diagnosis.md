# WhatsApp 手机扫码失败调查与诊断增强

2026-10-15，Codex。分支 `codex/whatsapp-pair-diagnostics`；用户已授权本次诊断增强合并推送，不含生产部署。先前代理与会话生命周期修复已在另一轮发布到 `220632a3`，不是本次待发布变更。

## 当前结论

手机提示“请检查你的网络并重试”不足以区分手机出网、服务器代理和配对协议。本次已经发现 Connector 内部授权链路失败，并确认从未完成凭据注册；仍无证据把手机网络或某个上游缺陷认作唯一根因。

只读现场证据（办公室）：

- 此次关联在北京时间 15:37 建立，15:43:13 自动同步记录失败，随后账号进入 `paused / protected_pause / authorization_unavailable`。
- Connector 加密 SQLite 使用只读连接检查，凭据 `registered=false`、无 `me` 身份，只有初始 `creds` 行，revision=1。没有输出或导出密钥、凭据、二维码或消息。
- 后端对应账号的 133 条授权请求 access log 均为 HTTP 200；未找到对应 403/500，也未找到数据库锁等待、死锁或连接池异常记录。最后一条位于 15:43:02 轮次；15:43:07 轮次随后报错。200 不代表及时响应或 allowed=true；旧日志没有耗时和失败分类，不能据此排除超时/连接中断。
- 该账号 consent 仍 active，Connector 最后错误为 `authorization_unavailable`。代码会把 5 秒超时、传输失败、非 2xx、JSON 异常归并为这一错误，因此它不是已经证实的权限拒绝。
- 已验证服务器经专用 1080 代理取得 WhatsApp WebSocket HTTP 101。它证明当次出网握手成功，不能证明扫码协议、长期连接或历史消息同步成功。
- 实际安装 Baileys 为 `7.0.0-rc14`，socket 源码没有 `companion_reg_refresh` 处理。上游 [issue 2737](https://github.com/WhiskeySockets/Baileys/issues/2737) 与 [PR 2765](https://github.com/WhiskeySockets/Baileys/pull/2765) 讨论了相似的扫码停滞及注册材料刷新处理；本次没有原始配对事件证据，不能确认同因，未升级或套用补丁。

## 本地变更

新增固定白名单结构化诊断，记录北京时间、散列账号标识、断线数字码、配对阶段布尔标志，以及授权请求的失败阶段、类型、HTTP 状态、耗时和允许的传输错误码。保持上游日志 silent；忽略任何调用方额外字段、异常原文和协议节点。

注册刷新监听只观察通知名称，随 socket 脱离一并移除。rc14 的内部 listener 会先修改共享 creds，诊断使用上次布尔快照对照，避免漏记配对变化。输出失败不影响现有授权失败保护。无数据库迁移、HTTP 返回契约变化、授权放宽、自动恢复、凭据重置或发消息行为。

## 验证与下一步

- `node --test --test-concurrency=1 --test-timeout=15000 test/*.test.mjs`：49 项全部通过；`npm run check` 通过。新用例覆盖日志敏感字段丢弃、授权失败分类、上游先修改 creds 的事件顺序、通知监听清理和输出失败保护。
- `TZ=America/Los_Angeles` 下诊断专项 4 项通过，包含北京时间零点跨日。初轮 `npm test` 曾 49 项通过，后续与其他检查并行执行时旧跨进程租约用例失败：其 500ms 租约在第二子进程启动前已过期，预期 `lease_busy` 实际已取得新租约。未修改该用例或缩弱断言；清理本次子进程后，上述串行全套复跑 49 项通过。
- 独立 agent 审查无可证实阻断，并独立执行诊断专项 4 项通过。严格约定检查、`git diff --check` 通过；`git_sweep.py --no-fetch` 完成，仅代表本地远端引用快照，保留现有未提交和旧分支，不自动整合。
- 对生产只做查询；未恢复账号授权、重新建立关联、删除凭据或重启服务。
- 现场根因仍未闭环。诊断候选经授权发布后，由持有人显式重新关联并扫码，对照 `companion_reg_refresh`、`pairing_credentials`、`connection_closed` 和 `authorization_failed`，才能判断是否为协议刷新、代理连接或内部授权请求问题。日志未出现某个事件不能单独证明手机网络故障。
