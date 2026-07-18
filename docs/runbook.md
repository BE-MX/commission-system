# 莱莎方舟平台 运维手册

> **版本**：v1.0  
> **最后更新**：2026-07-03  
> **目标读者**：运维人员、项目交接人员

## 环境准备

### 服务器环境

- **操作系统**：Windows Server 2019+
- **Python**：3.12（建议用 venv 虚拟环境）
- **Node.js**：18+ (LTS)（WhatsApp Connector 用）
- **Git**：2.40+
- **NSSM**：2.24+（服务托管）
- **数据库**：腾讯云 RDS MySQL 8.0（外网访问需配置白名单）

### 必需环境变量

在 `backend/.env` 配置以下变量：

```bash
# 数据库
DB_HOST=xxx.mysql.rds.tencentcdb.com
DB_PORT=3306
DB_USER=root
DB_PASSWORD=<密码>
DB_NAME=commission_db

# JWT
JWT_SECRET_KEY=<生产环境必须改>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Cookie
COOKIE_SECURE=true  # 生产环境必须 true
COOKIE_SAMESITE=lax

# CORS
CORS_ALLOW_ORIGINS=https://leshine.work

# 短链
SHORT_LINK_BASE_URL=https://leshine.work

# AI 加密
ARK_AI_ENCRYPTION_KEY=<32字节hex>

# 钉钉
DINGTALK_APP_KEY=<企业内部应用 Key>
DINGTALK_APP_SECRET=<企业内部应用 Secret>
DINGTALK_AGENT_ID=<Agent ID>
# 告警群自定义机器人（加签模式）——定时任务告警 / 培训速递推送 / git 巡检通知三条管道共用。
# 2026-07-18 前此两项为空导致三条管道全部静默失效；配置后必须手动验证一次
#（python scripts/git_sweep.py --notify 应看到「已发送」）
DINGTALK_WEBHOOK_URL=<告警群机器人 Webhook URL>
DINGTALK_WEBHOOK_SECRET=<机器人加签 Secret>

# 微信小程序
WX_MINI_APPID=wx4dea4f10fe1bda19
WX_MINI_SECRET=<小程序 Secret>
QR_SIGN_SECRET=<二维码签名密钥>

# WhatsApp Connector（可选）
WHATSAPP_CONNECTOR_BASE_URL=http://localhost:3100
WHATSAPP_CONNECTOR_API_KEY=<密钥>
WHATSAPP_AUTO_SYNC_ENABLED=true

# TFT 微服务（可选）
TFT_SERVICE_ENABLED=false
TFT_SERVICE_URL=http://192.168.101.47:8003/predict

# OKKI 开放平台（订单推送；deploy.bat 不同步 .env，生产服务器需手动配置后重启）
OKKI_CLIENT_ID=<OKKI 企业管理→外部对接→API对接>
OKKI_CLIENT_SECRET=<同上>
# OKKI_API_BASE 默认 https://api-sandbox.xiaoman.cn（即正式域名），一般不用配

# 发票 PDF 中文字体（部署与应用启动都会预检；默认值适用于 Windows Server）
PDF_CJK_FONT_PATH=C:\Windows\Fonts\msyh.ttc

# 素材存储（可选，2026-07-03 起走 Settings 统一管理，默认值即当前生产值）
ASSET_STORAGE_ROOT=D:\WORKSOURCE
ASSET_SIGN_SECRET=<签名密钥>
ASSET_UPLOAD_STAGING=D:\upload_staging
XPOZ_TARGET_ACCOUNTS=<逗号分隔账号，色彩趋势采集用>

# 调度器
SCHEDULER_ENABLED=true
```

`deploy.bat` 会在数据库迁移和服务重启前执行发票 PDF 字体预检。若失败，按错误提示修正
`PDF_CJK_FONT_PATH` 后重新部署；不要等到用户导出发票时再处理。

## 首次部署

### 1. 克隆代码

```bash
cd D:\MyProgram
git clone <仓库地址> commission-system
cd commission-system
```

### 2. 安装后端依赖

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 安装前端依赖

```bash
cd frontend
npm install
npm run build
```

### 4. 安装 WhatsApp Connector 依赖

```bash
cd services\whatsapp-connector
npm install
```

### 5. 数据库迁移

```bash
cd backend
alembic upgrade head
```

### 6. 配置 NSSM 服务

```bash
# 运行部署脚本（自动配置 CommissionSystem + WhatsAppConnector 双服务）
deploy\setup-server.bat
```

手动配置（若脚本失败）：

```bash
# 方舟主服务
nssm install CommissionSystem "D:\MyProgram\commission-system\backend\venv\Scripts\python.exe"
nssm set CommissionSystem AppDirectory "D:\MyProgram\commission-system\backend"
nssm set CommissionSystem AppParameters "-m uvicorn app.main:app --host 0.0.0.0 --port 8001"
nssm set CommissionSystem DisplayName "莱莎方舟平台"
nssm set CommissionSystem Description "莱莎方舟平台后端服务"
nssm set CommissionSystem Start SERVICE_AUTO_START
nssm set CommissionSystem AppStdout "D:\MyProgram\commission-system\logs\service.log"
nssm set CommissionSystem AppStderr "D:\MyProgram\commission-system\logs\service-error.log"
nssm start CommissionSystem

# WhatsApp Connector 服务
nssm install WhatsAppConnector "C:\Program Files\nodejs\node.exe"
nssm set WhatsAppConnector AppDirectory "D:\MyProgram\commission-system\services\whatsapp-connector"
nssm set WhatsAppConnector AppParameters "src/index.js"
nssm set WhatsAppConnector DisplayName "WhatsApp Connector"
nssm set WhatsAppConnector Start SERVICE_AUTO_START
nssm set WhatsAppConnector AppStdout "D:\MyProgram\commission-system\services\whatsapp-connector\logs\connector.log"
nssm set WhatsAppConnector AppStderr "D:\MyProgram\commission-system\services\whatsapp-connector\logs\connector-error.log"
nssm start WhatsAppConnector
```

### 7. 配置腾讯云 Nginx（前端静态文件）

SSH 登录云服务器 `root@119.28.107.92`，编辑 `/etc/nginx/conf.d/leshine.conf`：

```nginx
server {
    listen 443 ssl http2;
    server_name leshine.work;

    ssl_certificate /etc/nginx/ssl/leshine.work.crt;
    ssl_certificate_key /etc/nginx/ssl/leshine.work.key;

    gzip on;
    gzip_comp_level 6;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

    location /assets/ {
        root /var/www/ark/dist;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        root /var/www/ark/dist;
        try_files $uri $uri/ /index.html;
    }

    location ~ ^/(api|uploads|s|health) {
        proxy_pass http://127.0.0.1:8002;  # frp 穿透端口（2026-07-10 与云端 /etc/nginx/conf.d/leshine.conf 实况核对，旧文档误写 8888）
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

重启 Nginx：
```bash
nginx -t
systemctl reload nginx
```

### 8. 配置内网穿透（本地 → 云端，frp 方案）

**2026-05 起穿透方案是 frp，不是 SSH 隧道**（旧文档的 ssh -R 方案已废弃）。拓扑：

- 云端：`frps 0.61.2`（`/opt/frp/frps.toml`，systemd 服务 `frps`，bindPort 7000，Dashboard :7500，token/密码见服务器上的 toml 文件——**不写进文档**）
- 本地 Windows Server：`frpc` 客户端，注册两个代理：`ark-backend`（远程 8002 → 本地方舟后端）、`n8n`（远程 5678）

frpc 必须注册成 NSSM 服务开机自启（2026-07-09 断电事故：frpc 是手动启动的裸进程，重启后无人拉起，全站 502 一晚）：

```bat
nssm install FrpcTunnel "<frpc.exe 路径>"
nssm set FrpcTunnel AppParameters "-c <frpc.toml 路径>"
nssm set FrpcTunnel AppDirectory "<frp 目录>"
nssm set FrpcTunnel Start SERVICE_AUTO_START
nssm set FrpcTunnel AppExit Default Restart
nssm set FrpcTunnel AppRestartDelay 5000
nssm start FrpcTunnel
```

⚠️ frpc.toml 必须有 `loginFailExit = false`：断电重启时网络比服务起得慢，没这行 frpc 首连失败即退出，隧道不会自愈。

#### frps 端口封禁（2026-07-18 安全加固）

对抗性审查发现 frps 面板 7500（弱口令可公网登入看内网拓扑）与后端隧道端口 8002（公网明文可达、XFF 可伪造绕过 nginx）暴露公网。用 iptables 只放行 loopback 解决，**零重启零中断**（未动 frps/frpc/auth.token）：

```bash
# 幂等脚本（先删后插到 INPUT 最前），已落 /usr/local/sbin/frp-fw-lockdown.sh
for p in 7500 8002; do
  iptables -D INPUT -p tcp --dport $p ! -i lo -j DROP 2>/dev/null
  iptables -I INPUT 1 -p tcp --dport $p ! -i lo -j DROP
done
```

- 原理：云服务器 eth0 是内网 IP（10.3.0.14，公网经腾讯云 NAT），无独立公网网卡，故按 `! -i lo` 区分——nginx 走 `127.0.0.1:8002`(loopback) 与 SSH 转发到 7500 都走 lo 放行，一切经 eth0 进来的公网/内网直连 DROP。7000（frpc 建隧道用）与 22/80/443 不动。
- 持久化：`/etc/cron.d/frp-fw-lockdown`（`@reboot` 恢复 + `*/15` 重放，防被云镜等 flush 后长期消失）。无 netfilter-persistent，靠 cron 幂等重放。
- 验证：**必须从外部机器**测 `curl --connect-timeout 6 http://119.28.107.92:8002/`（应 000 超时）——服务器本机 curl 自己 eth0 IP 会走 lo 放行，测不出封禁效果。
- 剩余纵深项：dashboard 口令与 `auth.token`（`Cola…2026!` 规律）仍弱，换 `auth.token` 必须同步本地 frpc.toml 否则隧道永久断；建议腾讯云安全组也封 7500/8002（云层）。

## 日常更新

运行 `deploy\deploy.bat`，自动执行：

1. `git pull` 拉取最新代码
2. `pip install -r requirements.txt` 更新后端依赖
3. `npm install` 更新 Connector 依赖
4. `alembic upgrade head` 数据库迁移
5. `npm run build` 构建前端
6. `scp dist/* → root@119.28.107.92:/var/www/ark/dist/` 同步静态文件到云端
7. `nssm restart CommissionSystem` + `nssm restart WhatsAppConnector` 重启双服务

## 开发机 git 巡检（多智能体协作）

开发机由 Claude Code / Codex / Kimi 三个 AI 代理在各自 git worktree 并行开发，协作约定见仓库根 `AGENTS.md`（与 CLAUDE.md 硬约定 22 同步维护）。

- 手动巡检：`python scripts/git_sweep.py --open` — 扫全部 worktree/分支的未提交、未推送、未合并、可删分支、stash、跨分支 Alembic 迁移撞号，生成 `tmp/git-sweep.html` 可视化看板
- 定时巡检：Windows 计划任务 `LeShine-GitSweep`（每日 18:00，`--notify` 只在有结构性欠账时推钉钉告警群）。重建命令：

```bash
schtasks /Create /TN LeShine-GitSweep /SC DAILY /ST 18:00 /F /TR "\"D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe\" \"D:\MyProgram\commission-system\scripts\git_sweep.py\" --notify"
```

- webhook 未配置时可用 `--notify-user <钉钉userid>` 降级走企业应用工作通知
- 存疑旧分支的处置模式：`git tag archive/<name>-<date>` 推远端后再删分支（可随时找回）

## 健康检查

```bash
# 检查后端服务
curl http://localhost:8001/health

# 检查前端（生产）
curl https://leshine.work

# 检查数据库连接
curl http://localhost:8001/health | jq .data.database

# 检查 NSSM 服务状态
nssm status CommissionSystem
nssm status WhatsAppConnector

# 查看日志
tail -f D:\MyProgram\commission-system\logs\service.log
```

响应示例：
```json
{
  "status": "healthy",
  "timestamp": "2026-07-01T10:00:00",
  "database": "connected",
  "scheduler": "running"
}
```

## 常见问题排查

### Q1：端口被占用（8001）

```bash
# 找占用进程
netstat -ano | findstr :8001

# 杀掉进程
taskkill /PID <PID> /F

# 重启服务
nssm restart CommissionSystem
```

**红线**：服务器上不要手动 `python -m uvicorn` 启动后端，会和 NSSM 服务抢端口。

### Q2：数据库连接失败

检查清单：
1. `.env` 中 `DB_HOST` / `DB_PASSWORD` 是否正确
2. 腾讯云 RDS 白名单是否包含服务器公网 IP
3. `telnet <DB_HOST> 3306` 测试连通性

### Q3：前端 404 或白屏

1. 检查云端静态文件：`ssh root@119.28.107.92 "ls -lh /var/www/ark/dist/"`
2. 检查 Nginx 配置：`ssh root@119.28.107.92 "nginx -t"`
3. 检查 frp 穿透：`ssh root@119.28.107.92 "ss -tlnp | grep 8002"`（云端 frps 是否在听）+ 本地 `nssm status FrpcTunnel`
4. 重新同步：`deploy\deploy.bat`

### Q3.5：部署成功但页面还是旧版（2026-07-13 实case）

**先别重跑 deploy，八成云端已经是新的，是客户端缓存。** 判定方法（开发机可做）：

1. `curl -sI https://leshine.work/ | findstr Last-Modified` — 时间是不是刚部署的时刻
2. 拉云端 chunk 验证代码内容：`curl -s https://leshine.work/` 找到 `assets/index-*.js` → 下载后搜其中的懒加载 chunk 名 → 下载目标 chunk 用 `grep` 搜本次改动的特征字符串（比对内容，不要比对 hash——本地构建与服务器构建可能差一个提交）
3. 若云端确认是新的 → 测试设备强刷（PC Ctrl+F5 / iPad Safari 清除历史与网站数据）

根治已落地（2026-07-13）：云端 nginx 对所有 `.html` 返回 `Cache-Control: no-cache`（每次 ETag 回源验证，未变 304），`/etc/nginx/conf.d/leshine.conf`（改前备份 `leshine.conf.bak-20260713`）；带 hash 的 `/assets/` 维持一年 immutable 缓存。此后部署即刻全员生效，不再需要用户清缓存。

另：deploy.bat 的 assets 增量上传循环**每传一个文件打一行进度**（2026-07-13 加固前全程静默数分钟，曾被误判卡死而手动中断）；所有 ssh/scp 带 `BatchMode=yes -o ConnectTimeout=10`，网络/密钥问题会立即报错而不是无限假死。若报 BatchMode 相关错误 = SSH 免密失效，在服务器上手动 `ssh root@119.28.107.92 "echo ok"` 按提示修复后重跑。

### Q4：定时任务未执行

1. 检查 `SCHEDULER_ENABLED=true`（`.env`）
2. 查看日志：`grep "APScheduler" logs\service.log`
3. 手动触发测试：
   ```bash
   curl -X POST http://localhost:8001/api/insight/reports/generate/industry_daily \
     -H "Authorization: Bearer <token>"
   ```

### Q5：WhatsApp 同步失败

1. 检查 Connector 服务状态：`nssm status WhatsAppConnector`
2. 检查 Connector 日志：`services\whatsapp-connector\logs\connector.log`
3. 检查环境变量：`WHATSAPP_CONNECTOR_BASE_URL` / `WHATSAPP_CONNECTOR_API_KEY`
4. 重启 Connector：`nssm restart WhatsAppConnector`

### Q6：AI 调用失败

1. 检查 AI Provider 配置（「系统管理 → AI 接入管理」）
2. 测试连通性：Provider 列表 → 点击「测试连接」
3. 查看调用日志：AI 接入管理 → 调用日志
4. 检查 API Key 是否过期或配额不足
5. ELBNT-AI 返回 `503 No available accounts` = 该账号池当前无可用后端（配额问题），查 ELBNT 控制台，与本地配置无关

### Q7：展会试戴（/expo/kiosk）异常

1. **不出分析/话术**：按 Q6 排查 `expo_face_analysis` / `expo_sales_strategy` 两个 preset；话术生成失败会自动回落话术卡库原文，展台不冷场。**话术只在「试戴线索台」展示**（2026-07-07 起 kiosk 销售面板不再显示，客户看得到那块屏）；话术随合成启动并行生成，顾问等图期间打开线索台详情即可看到（详情抽屉会自动刷新）
2. **不出效果图**：失败原因看 `ark_expo_sessions.error_message` 或 AI 调用日志（`ark_ai_call_logs`，preset=expo_wig_composite）。生图 Provider 在「AI 接入管理」后台可切（2026-07-07 已从 ELBNT 切云雾 api.wlai.vip / gpt-image-2，单场景实测 41~135s）。常见：上游偶发 500/502/504（重试或换 Provider）；「多场景合一」三联图耗时更长但仍在 300s 超时与 420s 看门狗余量内；卡在"生成中"超 7 分钟会被看门狗自动标失败并给出重试入口
3. **提示权限不足**：确认账号有 `expo:write`；若右上角显示占位"用户"，硬刷新（Ctrl+F5）重新拉取登录态
4. 客户照片与效果图存 `uploads/expo/`（photos/results/wigs/hair_colors 四个子目录），属 `/uploads` 备份范围；客户数据删除走线索台「删除」（物理删除照片）；发型/色板图上传不限体积（送模型前管线自动压缩）

### Q8：全站 /api 一律 502（前端静态页正常）

前端 200 但所有 API 502 = 云 Nginx 找不到上游 = **frp 穿透断了**（2026-07-09 断电事故：frpc 断了一晚无人知）。定位链路：

```bash
# 1. 云端确认（开发机可直接跑）：8002 无监听 = 穿透断
ssh root@119.28.107.92 "ss -tlnp | grep 8002"
ssh root@119.28.107.92 "journalctl -u frps -n 20"   # 看 ark-backend 代理何时 client exit / 有无重连

# 2. 生产 Windows Server 上恢复：
nssm restart FrpcTunnel
# 服务不存在说明 frpc 还是裸进程，按「配置内网穿透」一节注册 NSSM 服务

# 3. 恢复验证（任意机器）：
curl https://leshine.work/health
```

穿透断的常见诱因：断电/重启后 frpc 未自启（必须挂 NSSM 自启）、frpc 首连失败退出（必须配 `loginFailExit = false`）。

## 日志位置

| 日志类型 | 路径 |
|----------|------|
| 后端服务 | `logs/service.log` |
| 后端错误 | `logs/service-error.log` |
| WhatsApp Connector | `services/whatsapp-connector/logs/connector.log` |
| Nginx 访问日志 | `/var/log/nginx/access.log`（云端） |
| Nginx 错误日志 | `/var/log/nginx/error.log`（云端） |

## 备份策略

### 数据库备份

腾讯云 RDS 自动备份：
- 每日凌晨 2:00 全量备份
- 保留 7 天
- 恢复方式：腾讯云控制台 → RDS → 备份恢复

### 素材与上传文件备份（2026-07-03 新增，架构评估 S7）

`uploads/`（设计附件/头像/报告 HTML/expo 客户照片）与 `D:\WORKSOURCE`（素材中台全部文件）此前**零备份**——盘坏即全量丢失。备份脚本：`deploy\backup-uploads.bat`（robocopy /MIR 镜像到另一块盘）。

客户售后证据和 SOP 原件位于 `D:\WORKSOURCE\aftersales`，已包含在上述 `D:\WORKSOURCE` 整体镜像范围内。恢复时先恢复数据库，再将备份中的 `WORKSOURCE\aftersales` 原路径回写，并抽查一张售后单的图片/视频下载。

**服务器上一次性注册每晚计划任务（管理员 cmd）**：
```
schtasks /create /tn ArkUploadsBackup /tr "D:\commission-system\deploy\backup-uploads.bat" /sc daily /st 02:30 /ru SYSTEM
```
⚠️ 使用前编辑脚本中 `BACKUP_ROOT`（默认 `E:\ark_backup`）指向**另一块物理盘或 NAS**；备份日志在 `.deploy_state\backup.log`，每月抽查一次。

### 部署回滚（2026-07-03 新增，架构评估 S8）

`deploy.bat` 现在每次部署前自动打快照（`[0/7]`：git tag `deploy-last` + dist 产物留档到 `.deploy_state\`）。一次坏部署的恢复：

```
deploy\rollback.bat     # 代码回到上次部署 commit + 恢复 dist + 同步云端 + 重启服务
```
数据库迁移不自动回滚（RDS 自动备份兜底）；若新版本跑过不兼容迁移，先查 `alembic current` 再人工评估。恢复到最新代码：`git checkout main` 后重跑 deploy.bat。

### 代码备份

Git 仓库即备份，每次部署前确保本地无未提交变更：

```bash
git status
git add .
git commit -m "update: xxx"
git push
```

### 环境变量备份

`.env` 文件不进 git，手动备份到安全位置：

```bash
copy backend\.env D:\Backup\ark-env-2026-07-01.txt
```

## 性能监控

### 数据库慢查询

腾讯云控制台 → RDS → 性能优化 → 慢查询日志

关注指标：
- 查询时间 > 1s 的 SQL
- `shipment_tracking` 表轮询查询
- `ark_assets` 列表查询（已优化，但需持续关注）

### APScheduler 任务耗时

查看日志中的 `duration_ms` 字段：

```bash
grep "job completed" logs\service.log | tail -20
```

关注任务：
- `insight_industry_daily`（外部信源抓取 + AI 整理）
- `tracking_poll_active`（批量轮询运单）
- `whatsapp_auto_sync`（增量拉取会话 + 消息）

## 权限管理

### 新增用户

1. 「系统管理 → 用户管理」→ 新建用户
2. 分配角色（角色关联权限）
3. （可选）绑定钉钉 ID（点击「同步钉钉」通过手机号自动匹配）
4. （可选）绑定微信 ID（扫码报工用，「生产管理 → 工序管理」设置）

### 新增权限

1. 修改 `backend/app/auth/service.py` 的 `seed_role_permissions()` 函数
2. 重启后端：`nssm restart CommissionSystem`
3. 「系统管理 → 角色管理」→ 重新分配权限

### 外部账号绑定（客户机会台用）

1. 「系统管理 → 用户管理」→ 选择用户 → 「外部账号」Tab
2. 添加绑定：`provider=alibaba_icbu`, `external_account_id=<阿里子账号ID>`
3. ACCIO WORK 推送询盘时自动匹配归属

## 安全注意事项

1. **生产环境 `.env` 必须配置**：
   - `JWT_SECRET_KEY` 非默认值
   - `COOKIE_SECURE=true`
   - `CORS_ALLOW_ORIGINS` 不含 localhost
   - `ARK_AI_ENCRYPTION_KEY` 显式配置

2. **数据库密码定期更换**（建议 90 天）

3. **SSL 证书到期前 30 天续期**（Let's Encrypt 证书有效期 90 天）

4. **API Key 定期轮换**（ACCIO WORK / WhatsApp Connector / 钉钉）

5. **日志定期清理**（`logs/` 目录，建议保留 30 天）

## 联系方式

- **项目负责人**：亮哥
- **技术支持**：内部技术支持群
- **紧急联系**：<电话>

## PM 项目资料协作站（pm.leshine.work）部署

后端复用现有 frp 链路（本地 8002），**零新增进程/NSSM 服务**；前端独立静态站点。上线 checklist：

1. **DNS**：`pm.leshine.work` A 记录 → 腾讯云服务器 IP（DNSPod，权威 NS 为 source/daffodil.dnspod.net）
2. **证书**：主站用的是腾讯云证书（`/etc/nginx/ssl/leshine.work_bundle.crt`），**不覆盖子域名**；PM 站用 Let's Encrypt（certbot 2.9.0 已装，2026-07-18），webroot 模式签发：
   ```bash
   certbot certonly --webroot -w /var/www/letsencrypt -d pm.leshine.work \
     --non-interactive --agree-tos -m <邮箱>
   ```
   续期靠 certbot systemd timer 自动跑，依赖 80 端口的 `/.well-known/acme-challenge/` → `/var/www/letsencrypt` 通道，**该 location 不可删**
3. **云 Nginx server block**：`/etc/nginx/conf.d/pm.leshine.conf`（2026-07-18 已部署，静态直出 + /api 走既有 frp 隧道；对抗性审查后加安全头/http2/正则收口）。安全头抽到 `snippets/pm-headers.conf` 统一维护，规避 `add_header` 不跨含 add_header 的子 location 继承的坑：

   `/etc/nginx/snippets/pm-headers.conf`：
   ```nginx
   add_header Strict-Transport-Security "max-age=31536000" always;   # 不含 includeSubDomains，不波及父域
   add_header X-Content-Type-Options "nosniff" always;
   add_header X-Frame-Options "SAMEORIGIN" always;                   # 同源——PDF 预览用同源 iframe，DENY 会拦掉
   add_header X-Robots-Tag "noindex, nofollow" always;               # 内部站防收录（设计稿 §8.4）
   ```

   `/etc/nginx/conf.d/pm.leshine.conf`：
   ```nginx
   server {
       listen 80;
       server_name pm.leshine.work;
       location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }   # ACME 通道，不可删
       location / { return 301 https://$host$request_uri; }
   }
   server {
       listen 443 ssl http2;   # nginx 1.24 用 listen 内联式；独立 `http2 on;` 指令要 1.25.1+，1.24 写会 nginx -t 报 unknown directive
       server_name pm.leshine.work;
       ssl_certificate     /etc/letsencrypt/live/pm.leshine.work/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/pm.leshine.work/privkey.pem;
       ssl_protocols TLSv1.2 TLSv1.3;
       ssl_ciphers HIGH:!aNULL:!MD5;
       server_tokens off;

       root /var/www/pm/dist;
       index index.html;

       include snippets/pm-headers.conf;   # server 级；无自身 add_header 的子块（/、^~ /api/）自动继承

       location /assets/ {
           expires 1y;
           add_header Cache-Control "public, immutable";
           include snippets/pm-headers.conf;   # 本块有 add_header，必须重新 include 补头
       }
       location ~* \.html$ {
           add_header Cache-Control "no-cache";
           include snippets/pm-headers.conf;
       }
       # ^~ 提升前缀优先级压过上面 \.html$ 正则，确保 /api/**.html 也反代到后端而非被正则截胡成静态 404
       location ^~ /api/ {
           proxy_pass http://127.0.0.1:8002;   # 与主站同一 frp 反代通道（云端监听 8002，不是 8001）
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_read_timeout 120s;
           client_max_body_size 60m;            # 略大于 PM_MAX_UPLOAD_MB=50
       }
       location / {
           try_files $uri $uri/ /index.html;    # SPA 回退
       }
   }
   ```
4. **数据库**：`alembic upgrade head`（073_pm_hub；若 codex 073/074 先合入，先把本迁移 down_revision 改指 074）→ `python scripts/seed_pm.py` 预置项目/白名单/35 项材料/5 条 workshop 任务
5. **.env 可选配置**：`PM_TOKEN_SECRET`（留空回退 JWT_SECRET_KEY，生产建议独立随机串）、`PM_TOKEN_EPOCH`（默认 1，+1 全员重签）、`PM_MAX_UPLOAD_MB`（默认 50）、`PM_FILE_SIGN_TTL_SECONDS`（默认 300）
6. **部署**：deploy.bat 已含 frontend-pm 构建 + SCP（/var/www/pm/dist，marker 增量，失败留标重试）；资料文件备份已由 backup-uploads.bat 覆盖（backend/data → backend_data）
7. **限速启用 IP 维度的前置（红线，2026-07-18 审查发现）**：不仅要 Nginx 设 X-Forwarded-For + uvicorn 开 `--proxy-headers`，**更前置的是先关闭后端 8002 端口的公网直连**。当前 frps 把 8002 以 `0.0.0.0` 暴露公网、明文 HTTP 可达，任何人 `curl -H 'X-Forwarded-For: 伪造IP' http://<服务器>:8002/api/pm/entry` 就能绕过 Nginx 直打后端并伪造 XFF——此时启用 IP 限速/IP 审计等于给攻击者递了伪造入口。修复：frps 代理端口绑 `127.0.0.1`（Nginx 本就 proxy 到 127.0.0.1:8002，零影响）或安全组封 8002 公网入站，仅放行 localhost。**注意 MCP 网关 mount 在 `/mcp`，主站/PM 的 Nginx 都不反代它**——封 8002 前先确认没有 MCP 客户端靠直连 8002 使用（若有需另开受控入口）
8. **下线**：摘 server block + DNS 记录即可，后端模块留存不影响平台
