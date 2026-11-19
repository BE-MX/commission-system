# 2026-10-15 最新 main 完整生产发布

## 发布结果

用户授权“拉取全局最新代码并部署生产”。工作站和办公室重新 fetch 后，将候选固定为 `220632a34cea90e054a04bdd1ae71b8d3cfa1a8c`，通过 `deploy/deploy.bat --live-root D:/commission-system --revision <完整 SHA> --no-pull` 完成办公室与云端受管发布。生产原版本均为 `7f503ca2`；本次包含 WhatsApp 代理与绑定恢复、发票关联保存修复、公告原图预览，共 22 个文件差异，无迁移文件变化。

准备任务 exit_code=0。首次正式任务在两地后端更新后，保存 `publish-current.next → publish-current.json` 时发生 Windows WinError 5，退出码 1；两地应用仍健康，出库保持 installed_paused，原 active/enabled 基线完整保留。核实无运行中的发布进程、状态目录替换探针通过后，从同一目录、同一候选、同一发布身份接续。接续任务 exit_code=0，未再次重启已更新应用。

最终发布身份 `78d176623bed404d9e94a523dbb317ae`；publish-current 为 succeeded，完整 11 项完成，deferred=[]。办公室、北京后端、两项既有受管路由、五个静态站点、出库轮询器与邮件 Worker 均完成核验。资源清理 succeeded，office、leshine.work、leshine.cloud 全部完成，发布锁已释放。

## WhatsApp 修复生效

- 办公室 NSSM `WhatsAppConnector` 增加 `WHATSAPP_PROXY_URL=http://127.0.0.1:1080`，其余环境项顺序和 SHA256 均保留；随受管发布重启，未安装第二个 Connector。
- 真实安装依赖为 Baileys `7.0.0-rc14`、https-proxy-agent `7.0.6`、undici `7.30.0`。候选与安装后代码均分别通过代理完成真实 WebSocket 握手与 HTTPS 200；未建立业务账号授权或读取聊天。
- 办公室回环、leshine.work、leshine.cloud 的账号列表和最新已撤销关联查询均为 200，状态 revoke_pending、QR 为空。状态查询分别约 0.844 / 1.516 / 2.188 秒。北京运行环境签发的 JWT 经云端路由也通过办公室鉴权。
- 三个 Baileys 账号的 status/provider/generation/consent version/CRM 共享/AI 外发字段与发布前完全一致。已撤销授权未恢复；真实二维码、扫码及消息同步仍需持有人正常重新关联验收。
- 北京 Scheduler 和 WhatsApp 自动同步保持关闭，办公室保持开启。云端 WhatsApp API 继续使用现有新加坡至办公室的路由，本轮未迁移 Connector 或新增北京至办公室通道。

## 独立读回

- 办公室和北京实际 HEAD 均为固定候选；10 个关键源文件逐项规范化 SHA256 一致。两地运行进程均在源码安装后启动，办公室两个 NSSM 服务、北京 ark-backend 与 ark-colorwork 均正常运行。
- 共享数据库仍为 `196_domestic_commission`；无需迁移，没有 stamp/downgrade 或手工修表。
- 办公室回环及两主域 /health 均为 200、database=connected，Connector 受保护健康接口为 200/provider=baileys。
- 两地主站制品为 `09abfea997cf86d283b94ce71e2558a753243ccbc23c9cea57c003b5f7980613`。独立下载办公室及两域 index、WhatsAppConnector、AnnouncementDialog、AnnouncementList 脚本，SHA256 与构建一致。PM、素材、客户门户 HTTPS index 也与各自构建一致。
- 出库 timer 恢复 active/enabled，回执 verified、release_confirmed=true；邮件 Worker 保留 inactive/disabled。北京 8 项运行开关与发布前一致，门户访问开启，门户经营写入/PI/通知/邮件/门户出库门禁保持关闭。
- 既有独立服务仅做运行状态核验：北京中继、钉钉监听、社媒 MCP、隧道、研究 Agent、备份 timer、OpenClaw 均 active；三个登记 PM2 服务 online；新加坡 frps active、旧 okki-sync masked。未把这些服务或终端安装声称为本次新版本发布。

## 验证、清理与证据

本轮额外执行隔离 SQLite 发票关联同步回归 25 项通过；同一候选在 Git 交付前的 WhatsApp 后端 44 项、Connector 45 项及独立复审均通过。本轮受管前端构建、Connector 隔离启动及语法检查通过。构建保留既有分包/混合导入提示和 colour 可选 Matplotlib 警告；不影响已验证发布。未进行真实发票提交、账号扫码或消息外发。

主目录原有 48 个改动文件在文档同步前全部 SHA256 一致，未夹带提交或覆盖。文档仅追加本轮状态及更新本任务的发布说明，不自动 commit/push。三个本次一次性计划任务在读取真实退出结果后已删除；日志、候选、回滚材料和首次中断证据保留。

工作站与办公室证据目录为 `.deploy_state/full-main-release-20261015/`，包含固定计划、发布前基线、代理配置前后记录、三次任务结果、首次失败 journal、代理网络探针、办公室及北京独立 readback、静态制品与最终完成回执。北京独立脚本及结果保存在其安装目录的同名状态目录。

未开通的 pm.leshine.cloud、外部权威源码的 hair/video、手机和浏览器终端安装仍遵守 deploy/platforms.json 的既有边界；本次成功指完整受管应用发布及上述验证范围。
