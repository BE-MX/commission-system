# 办公室公网入口迁北京（2026-11-13）

## 范围与状态

用户授权将办公室公网入口和隧道迁到北京、统一 `https://leshine.cloud`，保留原新加坡通道回退，同时处理客户端与接口。任务工作区 `D:/MyProgram/commission-system-codex-beijing-office-ingress`，分支 `codex/beijing-office-ingress`，基点 `db8328aa`。本次授权不外推为 GitHub push 或合入 main。

北京隧道、业务路由和 DNS 修复已生效。应用版本 `e868f077039add1611ef564e90fc5e0d4538cd87` 已通过统一发布入口完成两地发布，独立健康检查 28/28 项通过。

## 已落地

- 办公室 `ArkOfficeBeijingTunnel` 自动服务以独立密钥连接北京受限 SSH 用户，仅监听北京 `127.0.0.1:8002`，转至办公室 `127.0.0.1:8001`。实际断开唯一 SSH 子进程后约 12 秒恢复，数据库健康正常。专用账号不能使用 shell、PTY、本地转发或 agent 转发；主机密钥固定，私钥仅存办公室受限 ACL 目录。
- 北京 4 组办公室业务路由（两个 server 块合计 14 个上游）改为新隧道：回款、验货、WhatsApp、设计图片。普通 API 及验货列表/打印例外仍走北京后端；新增通用 `/mcp/`，已有独立 MCP 路由保持优先。
- 新加坡 FRP、`.work` 主站与 PM/hair/video/outreach 独立站保留。数据库、业务文件和 Scheduler 单活归属未搬迁；禁止将未知结果的写请求自动重试到回退通道。
- DNSPod 暂停 `.work` 根域错误的北京 A 记录，保留新加坡 A 记录。权威 DNS 与 1.1.1.1 已读回仅 `119.28.107.92`；TTL600。
- 北京 `RECEIPT_STORAGE_PROXY_URL` 改为 `.cloud`，保存受限备份。两地回款文件当前均由 COS 管理，该参数仅作非 COS 回退；办公室值为空，防环保护保留。
- 主站 MCP、外部发票 API、AI 网关展示地址、发票审核链接和小程序生产地址统一 `.cloud`。销售 Agent 实际运行配置本来已为 `.cloud`，更新安装示例。
- PDA 1.0.6 / versionCode7 默认 `.cloud`，保留设备保存地址及待确认报工；不自动切换存在待确认报工的设备。

## 验证证据

- 部署与路由累计 65 项测试通过；前端地址相关 15 项、集成说明 23 项、发票创建隔离测试 1 项通过。前端构建通过。独立审查发现的 PowerShell 编码/参数、目录 ACL 以及失败回退后重试问题均修复并复核。
- PDA Gradle 构建通过；32 项测试中 31 项通过、1 项网络测试跳过。APK SHA256 `EAC7D47B4CFF0F6296DB7B4D1C677E710EB8346E46E794E00E663E5112F230FA`，为本机 debug 构建，未核验实体设备既有签名或安装。
- 两地登录/二维码密钥及小程序配置仅比较一致性，不输出内容。两地 COS 管理领域一致，微信实际登录尚未验收。
- 新入口匿名鉴权正确拒绝；登录态只读 WhatsApp、设计图片及小程序 token 校验返回 200。通用 MCP initialize 返回 200，未执行业务工具。
- 一份 3676 字节回款凭证完整内容在新旧入口一致且匹配记录摘要；验货照片、小程序参考图与进度码图片各前 65536 字节一致。后三项是范围样本，不能视为完整文件校验。
- 未创建真实回款、报工、验货或发货，未发送 WhatsApp/邮件；真实上传与设备扫码仍需按业务正常使用验收。
- 证据目录 `.deploy_state/office-beijing-ingress/` 保存阶段回执、构建日志、只读文件/API 对照及最终读回；凭据不进报告。

## 终端事项

用户已确认微信后台 request/uploadFile/downloadFile 合法域名包含 `https://leshine.cloud`。开发者工具已登录，用户已打开服务端口；CLI明确对任务worktree执行preview并成功，AppID `wx4dea4f10fe1bda19`、包大小442694字节，源码生产baseUrl为cloud，预览后小程序源码仍干净。二维码位于 `tmp/wechat-preview/preview.png`，手机扫码登录/接口及小程序审核/正式发布尚未完成。PDA APK 已构建，实体设备安装及扫码未完成。旧客户端继续通过 `.work` 原通道工作。

## 回退与维护

具体命令及摘要保护见 [部署说明](../../deploy/office-beijing-ingress.md)。回退入口只在当前 Nginx 与激活候选摘要一致时恢复原新加坡上游；后续合法配置变更需要重新审查差异，不能直接覆盖。回执与受限备份保留，未自动演练生产切回。两地业务数据库无本次新增迁移。

## 发布回执

- release_id `ede451dd85534d59b43d9dc584e3d7cc`，status=succeeded；两地实际版本 `e868f077`、schema `262_invoice_customer_sync_log`，无本次DDL。
- 办公室/北京后端、两地色块路由、五个静态目标完成；两主站静态 artifact `a10040e52dd566d7506888462e4c9cd9630ebb914f72f4133553115bbecea490`。
- 出库 verified、timer active/enabled；邮件 Worker 保持原停用。维护清理按统一入口 deferred，不是应用未完成。
- 北京服务启动于14:17:04，当前 Settings 的回款代理、短链和社媒MCP健康地址均为cloud；新隧道健康数据库connected。
- 正常发布仅调整两server中COLORWORK与MCP块顺序，现Nginx摘要 `50e21f6d5228d329d3b62f26790efb315107b96e0ecb4231805851ef80f89664`。收尾控制器精确识别这一变化，仍验证原候选快照摘要并拒绝其他漂移；16项测试及独立复核通过，现场只读核验 rollback_candidate_matches=true。没有实际切回或重载。
- 新控制器与PDA/文档为后续本地提交，未为此重发服务器应用。回退须从该最新控制提交调用，不能使用生产e868f077旧控制器。
