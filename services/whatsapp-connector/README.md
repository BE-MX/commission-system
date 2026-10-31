# Ark WhatsApp Connector — Baileys candidate

本服务负责公司专用业务账号的关联设备连接、会话/消息采集和持久化增量回放。Ark 决定账号归属、有效同意和正文访问权限；凭据与 Signal 密钥始终留在 connector。`baileys` 固定为 `7.0.0-rc14`，运行入口不依赖 WhatsApp Web、Puppeteer 或浏览器。

## 本地启动与验证

要求 Node.js **≥22.13.0**（内置 `node:sqlite`），建议使用当前受支持的 Node LTS。复制 `.env.example`，设置内网共享 Bearer key、Ark 回调地址，以及来自外部秘密管理器的 **32 字节标准 base64** 加密主密钥。不能把主密钥与数据库/备份一起存放。

```powershell
npm ci
npm run check
npm test
npm start
```

缺失 Bearer key、加密 key、Ark 地址或配置其他 provider 会阻断启动。默认仅监听 `127.0.0.1:8787`，`/health` 也要 Bearer；跨主机内网访问须显式配置 host 并使用受控网络/TLS。所有接口返回 `Cache-Control: no-store`。

测试只生成临时目录中的合成账户、凭据与事件；注入假 socket，不连接 WhatsApp。包含真实双进程争抢、进程崩溃/租约到期/接管、BufferJSON 与 protobuf 还原、SQLite 事务回滚、CAS、防旧写入、分页回放、编辑/撤回/延迟历史、授权失效、队列/磁盘保护和实际 Rust/WASM bridge 执行。通过本地测试不代表已经验证真实账号登录、网络故障恢复或生产吞吐量。

## 状态与单活边界

- SQLite `connector.sqlite` 位于 `WHATSAPP_DATA_DIR`，WAL + `synchronous=FULL`。仅支持**一台主机的本地持久磁盘**。推荐一个服务进程；同机竞争者共享同一个 SQLite 文件，健康租约被占用时返回 `lease_busy`。管理请求必须落到持有 socket 的进程。
- 每账号使用 SQLite 引擎时钟、单调 fencing token、holder、generation 与 consent 检查。租约默认 30 秒，10 秒重新检查 Ark 授权并续租。事务提交前再次验 fence；旧进程不能写凭据、投影、覆盖状态或事件。崩溃接管记录 `lease_takeover_gap`；恢复启动记录 `connector_restart_gap`。
- **不能把 SQLite 复制到多个主机各自运行**；不能使用网络共享文件系统假装分布式互斥。需要多主机时必须先改成共享数据库/分布式协调，当前实现不提供这种保证。
- 凭据和所有 Signal category 使用 auth 域 AES-256-GCM；消息、会话、联系人、账户/绑定元数据使用独立 data 域。两域密钥从外部主密钥经 HKDF 派生，AAD 绑定域、key version、账户和对象。索引仅保存合成 ID/哈希、owner/generation/consent 和控制字段，不存正文、电话/JID。
- `keys.set` 原子写入、支持 null 删除和 revision CAS；删除保留加密 null revision 防止 ABA。creds 更新同步提交后才返回。`app-state-sync-key` 经 protobuf `fromObject` 还原。损坏/错误 key 不会被当成空状态重新生成身份。
- `WHATSAPP_KEY_VERSION` 会标记并核验每条密文；**没有自动密钥轮换**。换 key/version 前需停掉所有 writer，在独立维护流程中重加密并验证备份。数据库自身不代替磁盘权限、备份访问控制或秘密管理器。

## Ark 回调及 HTTP 契约

所有请求带 `Authorization: Bearer WHATSAPP_CONNECTOR_API_KEY`。常规响应 `{code:200,data:...}`，错误 `{code:<HTTP status>,message:<safe error code>}`；不会返回异常原文。

Ark **先提交稳定 account UID、原 owner、provider、consent 与 generation 授权**，然后 POST：

```json
{"ark_user_id":7,"account_uid":"wa_acc_example","bind_session_uid":"bind_operation_example","provider":"baileys","consent_version":"1"}
```

`POST /internal/v1/bind-sessions` 创建绑定操作。`bind_session_uid` 可由 Ark 提供作为幂等键；结果不确定时用 `GET /internal/v1/bind-sessions/:uid` 正向查询，不盲目重发。绑定操作的安全元数据持久化，二维码仅在内存保留 60 秒，重启后不会从数据库恢复二维码。复用账号拒绝 owner 变化、旧 generation 和绑定操作跨授权版本复用。

每次初建/重连 socket 前、运行中每 10 秒以及读取正文 feed 前，connector GET：

```text
{ARK_API_BASE_URL}/api/whatsapp/internal/accounts/{account_uid}/authorization
```

响应必须是 `{code:200,data:{allowed:true,provider:"baileys",ark_user_id:7,consent_version:"1",session_generation:1,crm_shared:false}}`，与保存的 owner/generation/consent 一致。未登记、不允许、未知 provider、超时、回调错误和授权变化均拒绝连接/读取并关闭现有 socket。这里不读取 Ark JWT，也不假定管理员可以使采集继续。

| 接口 | 返回/用途 |
|---|---|
| `GET /internal/v2/accounts/:uid` | 安全元数据，可检查 paused/revoked 状态，无凭据/二维码/正文 |
| `POST /internal/v2/accounts/:uid/pause` | 停止采集、定时器、监听器与 socket，保留合法凭据 |
| `POST /internal/v2/accounts/:uid/reauthorize` | 根据最新 Ark 回调更新同意并恢复正常连接；保留有效已注册凭据。缺凭据返回 `rebind_required`，由用户显式重新绑定 |
| `POST /internal/v1/accounts/:uid/revoke` | 先停止业务事件和授权轮询，再使用受控 socket 尝试 logout，之后清除本地凭据 |
| `GET /internal/v2/changes?account_uid=&cursor=&limit=` | `{items:[{sequence,kind,payload,session_generation,consent_version}],next_cursor,has_more,account}` |
| `GET /internal/v1/conversations?account_uid=&cursor=&limit=` | 持久化会话变更页，items 是规范化会话对象 |
| `GET /internal/v1/messages?account_uid=&cursor=&limit=&chat_id=` | 持久化消息变更页，可按会话过滤；items 是规范化消息对象 |

limit 为 1–500；cursor 是十进制持久序列，**不是 WhatsApp 时间戳**。翻到末页保留已到达的 cursor，不回到 0。连接离线但授权仍有效时可回放已持久化数据；paused/revoking/revoked 与 Ark 拒绝授权时禁止正文 feed。

事件 receipt/inbox、会话、消息、account coverage 和 change log 在同一事务提交。change log 保存对象指针，不保存被编辑/撤回的旧正文副本；回放旧 sequence 也返回该对象当前投影。相应 payload 带 `source_revision`、`session_generation`、字符串 `consent_version`。重新授权会用当前授权版本重新发布合法缓存，消费端仍需校验它们。

rc14 的 `logout()` 只等待 socket 写入，没有远端 ACK，且没有 `creds.me.id` 时可能根本不发送设备删除请求。因此即使 Promise 成功，本实现也返回 `revoke_state=remote_unconfirmed`、status `paused`、needs_user_action=true，清除本地凭据后才标记 `local_credentials_cleared=true`。有身份且 logout 返回时 `logout_state=request_sent`；无身份、离线或失败分别记录 `not_sent_no_identity`、`not_attempted_offline`、`request_uncertain`。用户必须在手机关联设备中确认/移除设备；明确的所有者确认由 Ark 管理，本服务不把本地请求完成当成远端注销证明。`pause` 与设备注销请求是不同动作。

## 采集、覆盖信息与恢复

采集全部已授权账号会话（含群组），处理 `messages.upsert` 的整个 notify/append 数组、`messaging-history.set` 的所有 chats/contacts/messages、chats/contacts 更新以及消息 edit/delete。canonical UID 是有界 SHA-256 ID；保留完整 source key 的 remoteJid/id/fromMe/participant 与 PN/LID/username 替代地址。不从群组或 LID 推断手机号。

未知消息保存安全占位 `unsupported`；媒体只保存类型/文件名元数据，未下载附件。编辑替换当前正文，包含 rc14 的 `editedMessage.message` 包装；撤回清空正文和会话预览。墓碑阻止延迟历史重新填回已删除消息。删除整个会话后允许新的 notify 消息 ID 恢复后续会话；首次有效新消息建立持久的重新打开时间边界，其后的 append/history 继续同步。旧墓碑 ID 不恢复，无法证明晚于边界的历史和未知旧编辑不恢复正文，并明确记录 `deleted_chat_history_ambiguous` gap；已知新消息仍可编辑。读取型状态/送达回执不自动当成撤回。

account 包含 provider、session_generation、consent_version、status、connection_state、sync_state、history_state、last_error_code、needs_user_action、revoke_state；`coverage` 包含 earliest_message_at/latest_message_at/last_ingest_at/gap_reason。`isLatest`、progress=100 或 `messaging-history.status=complete` 只表示某个批次/阶段结束，**不证明取到了账号全部历史**，history_state 保持 partial。

队列上限 64 个事件、合计 16 MiB、单事件 8 MiB；超过限额、磁盘/记录上限、存储失败都会关闭 socket，记录 protected pause 和明确 gap，不能静默丢弃后继续声称同步完整。磁盘上限默认 1 GiB；提交前读取事务内 page_count/page_size，保守预留 WAL frame 与 checkpoint 扩展空间，不只检查尚未提交的文件大小；关闭 cache_spill 防止失败批次先溢写到 WAL。可用正文容量会小于磁盘上限，需预留维护空间。记录上限覆盖 change/inbox/entity/auth，达到上限不自动删除旧业务数据。需要操作员按批准的保留政策维护或扩容；当前版本没有自动 retention 工具。

临时断线和 restartRequired 采用有抖动的有界重连；loggedOut 清除无效凭据并要求 rebind；connectionReplaced 进入 blocked；未知原因、auth/CAS 失败保护暂停。正常重启加载已有注册凭据，不强迫重新扫码。暂停/撤销/关闭会取消重连和授权 timers，移除旧 socket listeners。

本应用不调用发送业务消息、readMessages、chatModify 或主动 presence API。配置 `markOnlineOnConnect:false`。**已核对 rc14 源码：上游仍会在连接打开时发送协议级 `unavailable` presence，并进行连接/密钥/历史同步等协议请求；不能宣称网络上完全没有 presence 或写报文。** 应用日志只记录安全错误码，不记录正文、二维码、JID、凭据或原始事件。

### 扫码与授权诊断

结构化日志以 `source=whatsapp_connector` 标记，时间固定北京时间并带 `+08:00`；`account` 为 account UID 的 SHA256 前 16 位，供同一关联过程对照。日志仅使用固定事件和字段白名单：socket 建立、二维码就绪、注册刷新通知、凭据注册/身份存在标志、连接成功、断线数字码/分类、保护暂停，以及授权失败的阶段/类型/HTTP 状态/耗时/允许的传输错误码。不会输出 URL、HTTP 头、异常原文、协议节点、二维码、手机号、JID、凭据或正文；上游 logger 继续 silent。

`authorization_failed` 区分 `timeout`、`transport`、`http_error`、`invalid_response`、`denied`；这些只解释失败，不改变 5 秒超时及现有拒绝/保护暂停规则。`companion_reg_refresh` 仅观察上游通知的事件名称，不发送 ACK、不修改配对材料、不实现上游未合并补丁。`pairing_credentials` 只证明凭据阶段变化，必须见到 `connection_open` 并经实际业务验收后才能确认关联可用。排障结论与本地验证见 [扫码失败调查](../../docs/reports/2026-10-15-whatsapp-pairing-diagnosis.md)。

## 迁移与发布边界

### 办公室出网与关联恢复

`WHATSAPP_PROXY_URL` 可配置 HTTP(S) CONNECT 代理，例如办公室已验证的 `http://127.0.0.1:1080`。仅 WhatsApp WebSocket 和媒体请求使用该代理，Ark 授权回调仍走原地址；不依赖交互用户的系统代理，也不读取通用 `HTTPS_PROXY` 作为隐式回退。无此配置保持直连，非法协议/路径阻断启动且不输出配置内容。服务环境优先于 `.env`，发布准备与 NSSM 实际启动保持同一优先级。

创建关联时先提交授权，再连接 WhatsApp；返回 `pending` 仅代表操作建立，不表示二维码已经生成。受保护暂停、撤销或要求重连时，绑定查询返回相应终态，停止等待二维码。Ark 解绑先关闭尚未结束的绑定会话；历史残留的已停止会话在用户明确发起关联时退出待处理队列，不恢复原账号授权。连接结果仍未知且授权有效的操作继续按原 UID 查询，不自动重复 POST。

2026-10-15 故障证据和未发布修复见 [二维码与关联恢复报告](../../docs/reports/2026-10-15-whatsapp-qr-recovery.md)。HTTPS/WebSocket 网络验证不能代替持有人扫码验收。

不会读取、转换或导入 `.wwebjs_auth`、旧 session 文件或旧正文库。旧账户只通过 Ark 已批准的稳定 UID/owner metadata 重新登记，再建立 Baileys 连接；旧设备 logout 与新设备 rebind 的顺序由发布流程控制，不能让旧 whatsapp-web.js 与新 Baileys 同时采集同一账号。

备份/恢复必须停掉所有本机 writer，用一致的 SQLite 备份保留数据库，并在独立秘密管理系统保存密钥。旧发布回滚需要原有依赖/原有状态；不能把 Baileys 凭据交给旧实现。生产只通过项目 `deploy/deploy.bat` 与登记的北京 Agent 服务入口执行；当前发布与真实账号验收见[项目交接](../../docs/handoff.md)，服务运行不等于账号已重新关联或历史已完整同步。

协议参考：[Baileys documentation](https://baileys.wiki/)、[Baileys rc14 release](https://github.com/WhiskeySockets/Baileys/releases/tag/v7.0.0-rc14)、[Node SQLite](https://nodejs.org/api/sqlite.html)。实际实现/验收以 lockfile 安装的 rc14 `lib/Types/Events.d.ts`、`lib/Utils/use-multi-file-auth-state.js` 和 `lib/Socket/chats.js` 为准。
