# 2026-10-15 WhatsApp 二维码与关联恢复

## 现场确认

- 办公室正在运行 `7f503ca2620ca62345547fce08f17c55aa9b887a`；本次涉及的 lifecycle/service/manager/server 四个源文件与任务基点逐文件 SHA256 一致。Connector 健康返回 Baileys，NSSM 回调地址为 `http://127.0.0.1:8001`。
- 北京时间 13:29:09 创建授权，13:29:12 Connector 建立 pending 操作，至 13:29:25 的最后一次查询仍为 `binding/connecting`、无二维码及到期时间。同步拉取正常，没有昨天的授权回调锁超时。
- 办公室 Node 直连 `https://web.whatsapp.com/` 在 10 秒超时；通过本机 HTTP 代理 `127.0.0.1:1080` 返回 HTTPS 200，`/ws/chat` 返回 HTTP 101 / websocket，约 1.28 秒。当前 Connector 未配置代理，socketFactory 未传 agent。探测仅做网络握手，未建立业务号授权、读取聊天或扫码。
- 13:29:30 用户撤销最新账号，账号为 `revoke_pending`、consent `revoked`，但绑定表仍为 `pending`。再次点击关联会优先回查这个旧操作，被实时授权拒绝，产生 `authorization_denied`。这条路径不取决于浏览器使用内网还是云域名。
- 所有数据库核验使用 READ ONLY 事务；未更改生产账号/授权/凭据/配置、未重启或发布。

## 修复

- 新增专用 `WHATSAPP_PROXY_URL`，以固定依赖 `https-proxy-agent@7.0.6` 接入 Baileys 的 agent/fetchAgent，以 `undici@7.30.0` 接入 options.dispatcher，覆盖 WebSocket、上传及历史下载；Ark 授权回调不走该代理。仅支持 HTTP(S) CONNECT，错误信息不包含代理凭据。
- 解绑在外部注销之前关闭 pending/binding 会话并清除二维码。历史停止会话在显式新关联时安全退出队列，不修改旧账号授权；有效但结果未知的原操作仍只读回、不重复 POST。
- 已停止账号的绑定刷新直接返回本地停止状态，避免无效授权回查。Connector 已停止的操作也返回终态，不继续显示 pending。
- 无数据库迁移、无前端改动、无消息正文处理变更。

## 验证与交付

- 原实现新增 8 项后端回归全部失败；修复后绑定恢复、Baileys 同步、ACL、API 契约与同步测试合计 44 项通过，隔离 SQLite。
- Connector 最终全套 45 项通过，包括真实本地 HTTP CONNECT / 已安装 Baileys WebSocketClient 和 getHttpStream 下载传输测试。另通过 npm run check。
- 增量约定检查、git diff --check 通过；git_sweep --no-fetch 完成，仅代表本地快照。独立审查发现历史下载需要额外 dispatcher，已补齐并通过真实下载流测试；独立复审通过、无新增发现。未执行真实 MySQL 并发交错或账号扫码。
- 工作分支 `codex/whatsapp-qr-recovery`；用户随后授权合并推送，本次 Git 交付保留主目录既有修改，不包含生产部署或代理配置。没有恢复用户撤销的账号；真实二维码、扫码、消息同步尚未验收。Git 保护备份与读回证据位于主目录 `.deploy_state/whatsapp-qr-main-20261015/`。

## 上线动作

Git 合并推送已获授权，生产发布及办公室 Connector 代理配置仍需单独授权。保留现有受保护环境项，为办公室服务配置 `WHATSAPP_PROXY_URL=http://127.0.0.1:1080`，通过 `deploy/deploy.bat` 固定候选准备及发布；按现有环境优先级核验配置生效。无需迁移或手工修表。

发布后核验运行版本、Connector 健康和代理 WebSocket；由持有人正常点击关联并扫码。旧账号仍保持已撤销状态，未知注销结果不冒充手机设备已移除。HTTPS 200/101 仅证明网络路径可通，不代表真实账号登录成功。
