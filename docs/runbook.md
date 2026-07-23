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

    # 上传体积上限（2026-07-17：默认 1m 导致 expo kiosk 相册原图上传 413，调至 5m；
    # 改前备份 leshine.conf.bak-20260717）
    client_max_body_size 5m;

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

frpc 必须注册成服务开机自启（2026-07-09 断电事故：frpc 是手动启动的裸进程，重启后无人拉起，全站 502 一晚）。

**生产实况（2026-07-22 核实）：服务名是 `frpc`，不是本文档此前写的 `FrpcTunnel`**，由 `C:\frp\frpc-service.exe` 包装，配置在 `C:\frp\frpc.toml`。
按错名字操作会得到"找不到服务"，白绕一圈。查真名不要靠记忆，按二进制路径反查：

```powershell
Get-CimInstance Win32_Service | Where-Object { $_.PathName -like "*frp*" } | Select-Object Name,State,PathName
Restart-Service frpc          # NSSM/包装器注册的就是普通 Windows 服务，不需要 nssm 在 PATH
```

首次注册（若服务不存在）：

```bat
nssm install frpc "<frpc.exe 路径>"
nssm set frpc AppParameters "-c <frpc.toml 路径>"
nssm set frpc AppDirectory "<frp 目录>"
nssm set frpc Start SERVICE_AUTO_START
nssm set frpc AppExit Default Restart
nssm set frpc AppRestartDelay 5000
nssm start frpc
```

**frpc.toml 四项必需配置**（2026-07-23 修订，poolCount 与保活项是当天踩坑后改的）：

```toml
loginFailExit = false                # 断电重启时网络比服务起得慢，没这行 frpc 首连失败即退出，隧道不自愈
transport.tcpMux = false             # 关闭多路复用，见下方说明；必须与 frps.toml 同值，配不齐客户端登录直接失败
transport.dialServerKeepalive = 20   # 秒。frpc 拨向 frps 的所有连接（含 work 连接）开 TCP 保活，
                                     # 默认 7200 等于没有——跨境 NAT 十几分钟就静默丢映射，见下方「空闲连接黑洞」
transport.poolCount = 0              # 不预建空闲工作连接。关 mux 后预热连接确实能省一个跨境往返，
                                     # 但空闲久了会变质，代价是 120 秒黑洞，不划算；并发请求的拨号本身会重叠
```

**字段名坑**：保活项在 TOML 格式里叫 `dialServerKeepalive`，不是老 ini 的 `tcpKeepalive`——写错了 `frpc verify` 会直接报
`json: unknown field "tcpKeepalive"`（frp 对未知字段是严格拒绝的，所以配错不会带着上线，改完必须 verify）。

**为什么关 tcpMux（2026-07-22）**：开启时控制连接与全部业务连接复用同一条 TCP，大 body 灌满这条又慢又抖的跨境链路
→ yamux 心跳写超时 → frpc 判会话已死重连 → **全站 API 与 n8n 一起 502 约 10 秒**。实测对照：关闭前 1MB 推送必失败且必断隧道，
关闭后 1MB/2MB 均正常返回（59s/166s，慢但成功），全程 `client exit` 为 0。详见 Q9。

改配置的正确姿势——两端都能用二进制自验语法，别直接重启赌：

```bash
/opt/frp/frps verify -c /opt/frp/frps.toml     # 云端
.\frpc.exe verify -c .\frpc.toml               # Windows（PowerShell 必须带 .\）
```

两端 `tcpMux` 必须同值，改动顺序：先改 frpc.toml（不重启）→ 改 frps.toml 并 `systemctl restart frps` → 立即 `Restart-Service frpc`。
中断窗口 10~30 秒。回滚 = 两端各删该行、按同样顺序重启（云端备份 `frps.toml.bak-20260722`）。
`dialServerKeepalive` / `poolCount` 是**客户端本地参数，不需要两端同值**，只重启 frpc 即可（`Restart-Service frpc` 要管理员
PowerShell，否则报"无法打开计算机上的 frpc 服务"——那是权限不足，不是服务名错）。

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
3. 检查 frp 穿透：`ssh root@119.28.107.92 "ss -tlnp | grep 8002"`（云端 frps 是否在听）+ 本地 `Get-Service frpc`
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

# 2. 生产 Windows Server 上恢复（服务名是 frpc，不是 FrpcTunnel——2026-07-22 核实）：
Restart-Service frpc
# 报"找不到服务"先按二进制路径反查真名：
#   Get-CimInstance Win32_Service | Where-Object { $_.PathName -like "*frp*" } | Select-Object Name,State,PathName
# 确实查无此服务才说明 frpc 是裸进程，按「配置内网穿透」一节注册

# 3. 恢复验证（任意机器）：
curl https://leshine.work/health
```

穿透断的常见诱因：断电/重启后 frpc 未自启（必须挂 NSSM 自启）、frpc 首连失败退出（必须配 `loginFailExit = false`）、**外网大文件上传把整条会话灌死（见 Q9）**。

### Q9：外网上传文件 502/504，且上传瞬间全站 API 抖一下（2026-07-22 实测定位）

**根因是链路物理上限，不是代码。** 主站云服务器在**腾讯云新加坡**（`lh-1259007308-lhins-qcp19s2v`，S5.MEDIUM4，`ap-singapore`），
用户传的文件必须由新加坡再经 frp 推回济南办公室的后端，而**新加坡→中国方向**这一跳实测只有 15~120 KB/s：

| 链路 | 实测吞吐 |
|------|----------|
| 新加坡云 → Cloudflare（国际方向） | 8.2 MB/s 上行 / 76 MB/s 下行 |
| 中国 → 新加坡云（入站方向） | 276 KB/s |
| **新加坡云 → 办公室（隧道推送）** | **5~120 KB/s，5MB 推 92 秒未完成** |
| 新加坡云 → 国内客户端（HTTPS 静态） | 81 KB/s（scp 5MB 用了 6 分 40 秒）|

云主机本身带宽富余，烂的只有回中国这一段。两个可观测后果：

1. **~20 秒的硬墙**：推不完就被切。云端直推实测 256KB ✓ / 512KB ✓ / 1MB ✗；走完整公网路径 50KB ✓ / 100KB ✓ / 300KB ✗
2. **一次大上传打死整条隧道**：frpc 默认 `transport.tcpMux = true`，控制连接与全部业务连接复用同一条 TCP。
   大 body 灌进这条又慢又抖的跨境连接 → 心跳挤不出去 → frpc 判定会话已死 → 重连。
   frps 日志签名是 `client exit success` + 约 8 秒后 `client login info`。**隧道一断，leshine.work 全站 API 和 n8n 一起 502 约 10 秒**

已做的缓解（2026-07-22）：

- 云 nginx `pm.leshine.conf` 的 `/api/` `client_max_body_size` 60m → **1m**，超限秒回 413 不进隧道（备份 `pm.leshine.conf.bak-20260722`）
- 前端 `frontend-pm/src/utils/uploadLimit.js` 按入口分档：公网构建 **256KB**、内网构建（`--base=/pm/`）仍 50MB；
  后端 `PM_MAX_UPLOAD_MB` **保持 50 不动**——它是全局的，压低会连带废掉健康的内网入口（20MB 实测 3.3 秒）
- PM 前端 api client 对 413/502/504 给可执行文案（引导内网入口 / 外部链接）

**已根治：关闭 tcpMux（2026-07-22 16:22 生效）**

两端同时置 `transport.tcpMux = false`（frpc 另加 `poolCount = 5` 抵消握手延迟、补回缺失的 `loginFailExit = false`），
业务连接各走各的 TCP，控制通道不再被大 body 堵死。**该 `poolCount = 5` 次日就被证明是错的，见 Q10。**
**改动前后同条件对照**：

| 载荷（云端直推 8002） | 关 mux 前 | 关 mux 后 |
|---|---|---|
| 1MB | 失败，隧道被打死 | **422 正常返回**（59s） |
| 2MB | 失败 | **422 正常返回**（166s） |
| 300KB（走完整公网路径） | 502 | **401 正常返回**（19~28s） |
| frps `client exit` | 每次失败必断 | **全程 0** |

上面第 1 条"~20 秒硬墙"随之消失——证实那就是 yamux 会话被写超时打死。**带宽约束依然存在**（1MB 仍需 59s），
所以外网入口的 256KB 闸门保持不动；现在的区别是超限只失败它自己，不再连累全站。

剩余根治（按优先级）：

1. **PM 文件走国内 COS 直传直下**：浏览器 ↔ COS（广州），后端只存 key，文件字节彻底离开跨境链路和 frp
2. **主站迁回国内**（需 ICP 备案）：现状是国内用户访问 leshine.work 的每个字节都以 ~0.5Mbps 从新加坡回传，慢的不止上传

排障命令：

```bash
# 看隧道是否被大上传打死（client exit + 秒级重登 = 中招）
ssh root@119.28.107.92 "journalctl -u frps --since today | grep -E 'client login|client exit'"
# 量一次云→办公室的推送吞吐（会短暂抖隧道，慎用；256KB 以内相对安全）
ssh root@119.28.107.92 "head -c 262144 /dev/zero > /tmp/t.bin; curl -s -o /dev/null -w 'http=%{http_code} time=%{time_total}s up=%{speed_upload}B/s\n' --max-time 120 -H 'Content-Type: application/json' --data-binary @/tmp/t.bin http://127.0.0.1:8002/api/pm/entry; rm -f /tmp/t.bin"
```

### Q10：闲置一段时间后头几个请求卡满 120 秒 504（2026-07-23，关 tcpMux 的副作用）

**症状**：pm.leshine.work 打开特别慢，静态页秒开，`/api/*` 前几个请求进黑洞，nginx 打满 `proxy_read_timeout 120s` 回 504；
再刷新反而正常。云端直接压隧道也能复现：闲置后头两次 `curl http://127.0.0.1:8002/health` 卡满 30 秒超时，第三次 1.3 秒返回 200。

**根因**：Q9 关 mux 时配的 `poolCount = 5` 让 frpc 预建 5 条**空闲**跨境 TCP 连接挂在 frps 手里等着。
这些连接十几分钟不发包就被沿途 NAT/防火墙静默丢掉，**两端都不知道**；frps 照样把用户请求配给一条死连接，数据发进去无人接收，
只能等 nginx 超时。frp 默认 `dialServerKeepalive = 7200`（2 小时）等于没有保活，撑不住跨境链路的空闲回收。

开 mux 时不存在这个问题：只有一条长连接且有心跳，死了立刻重连。

**修法**（只改 frpc.toml，云端不动）：`transport.dialServerKeepalive = 20` + `transport.poolCount = 0`，`Restart-Service frpc`。

**实测对照**（当天 11:36 重启为界，同一份 nginx 日志）：

| | 502 | 504 | 闲置后首个请求 |
|---|---|---|---|
| 修复前（00:00–11:36） | 2 | 6 | 30s / 120s 打满超时 |
| 修复后（11:36–22:28，112 个 /api 请求） | **0** | **0** | 1.2~1.3s（最差一次 6s，丢包 RTO） |

冷态首屏实测（闲置 16 分钟后 3 个 API 并发）wall = **0.65 秒**——并发请求的拨号互相重叠，所以 `poolCount = 0` 的代价远小于单条串行探测看到的数字。
隧道真实 RTT 约 **0.2 秒**（`/health` 带一次数据库探活，会多算 0.1 秒，别拿它当 RTT 基准）。

**为什么不留 `poolCount = 5` + 保活**：理论上保活能让池子里的连接不变质，但收益只有零点几秒（还被并发摊薄），
赌注是 120 秒黑洞——不划算。空闲连接池在这条链路上就是负资产。

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

### 云 Nginx expo 素材代理缓存（2026-07-22）

素材（发型封面/发色卡/场景图/结果展示图）经 frp 隧道回源每请求 ~2s。云 Nginx 对
`location /uploads/expo/` 开了代理缓存（`/etc/nginx/conf.d/leshine.conf`，缓存目录
`/var/cache/nginx/expo_uploads`，TTL 30 天，`use_stale` 隧道断连时仍出已缓存素材）。
实测同一素材 MISS 1.06s → HIT 0.015s。响应头 `X-Cache-Status` 可判命中。

**缓存更新机制**：素材除场景示意图外全部 uuid 命名——换素材=新 URL，天然不脏。
场景示意图（`uploads/expo/scenes/<key>.<ext>` 固定名覆盖式替换）由后端
`scene_image_url()` 拼 `?v=<mtime>` 版本号破缓存（cache key 含 query string）。

**注意**：`?v=` 版本号随 2026-07-22 后端代码生效——该版本部署前若替换过场景示意图，
需手动清一次缓存：

```bash
ssh root@119.28.107.92 "rm -rf /var/cache/nginx/expo_uploads/* && systemctl reload nginx"
```

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

## 云端展会实例（https://leshine.cloud → 154.8.205.162，2026-07-22 搭建）

北京轻量服务器（4C8G/12M，Ubuntu 24.04）跑方舟完整后端 + 前端静态，**专门服务展会场景**。三入口：`https://leshine.cloud` 主站（相机可用）、http 域名 301 跳 https、`http://154.8.205.162` IP 兜底。**证书 TrustAsia 90 天期，2026-10-19 到期需续**（/etc/nginx/ssl/，主域与 hair 子域两张同批到期）。发型静态展示站曾挂本机 hair.leshine.cloud——**2026-07-22 当天 leshine.cloud 全域被未备案拦截**（80 跳 dnspod webblock 页、443 TLS RST，灰度铺开「部分手机能开」），当日迁至新加坡机 `hair.leshine.work`（/var/www/hair-styles，conf.d/hair.leshine.conf，certbot webroot 证书 2026-10-20 到期**自动续期**）；展会二维码指向 `https://hair.leshine.work/#/p/<产品编号>`，16 张码图在亮哥 Downloads\莱莎16款明星发型静态网页\qrcodes\（.cloud 旧码已覆盖作废）。本机保留 IP 兜底入口：主站 `http://154.8.205.162`、发型站 `http://154.8.205.162/hair/`（子路径挂站注意 `^~` 防 .html 正则截胡，见 cerebrum 2026-07-22）。⚠️ leshine.cloud 未备案（.cloud 后缀疑似不可备案，待腾讯云备案控制台核实）——机房对未备案域名周期扫描拦截，**随时可能失效**，被拦即退 IP 入口，正式方案等 leshine.work 备案。与办公室生产实例共用北京 RDS（同区延迟 2.1ms）；`.env` 三处差异：`SCHEDULER_ENABLED=false`（定时任务只在办公室跑，expo 看门狗是读取时自愈不受影响）、`WHATSAPP_AUTO_SYNC_ENABLED=false`、`TFT_SERVICE_ENABLED=false`（内网服务不可达），另加 `PDF_CJK_FONT_PATH` 指向 Noto CJK。

- 布局：代码 `/home/ubuntu/commission-system`（clone 自本机 bare 仓库 `/home/ubuntu/repo.git`）；前端 `/var/www/ark-dist`；日志 `logs/service.log`
- 服务：`sudo systemctl status|restart ark-backend`（uvicorn 单 worker，127.0.0.1:8001，nginx 80 反代）
- **部署更新（不走 GitHub）**：开发机 `git push cloud main`（remote `cloud` = ssh bare 仓库）→ `ssh ubuntu@154.8.205.162 "cd ~/commission-system && git pull && sudo systemctl restart ark-backend"`；前端变更时开发机 `npm run build` 后 `tar czf - dist | ssh ubuntu@154.8.205.162 "cd /tmp && tar xzf - && sudo rsync -a --delete dist/ /var/www/ark-dist/ && rm -rf dist"`
- 素材：`uploads/expo/`（wigs/hair_colors/scenes/results）2026-07-22 从开发机同步；**切流量前需与办公室生产核对增量**
- 安全：仅密钥登录（密码/root 已禁）；8001 不对外；系统防火墙无 ufw，靠腾讯云控制台防火墙（默认 22/80/443）
- Linux 跨平台备忘：OpenCV 需 `libgl1 libglib2.0-0`；PDF 导出需 `fonts-noto-cjk`（缺了这些 pytest 挂 invoice/expo 图像用例）

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
           client_max_body_size 1m;             # 2026-07-22 由 60m 降下来，理由见 Q9——外网入口传不动文件，
                                                # 超限在 nginx 秒回 413，绝不能让大 body 进隧道
       }
       location / {
           try_files $uri $uri/ /index.html;    # SPA 回退
       }
   }
   ```
4. **数据库**：`alembic upgrade head`（073_pm_hub；若 codex 073/074 先合入，先把本迁移 down_revision 改指 074）→ `python scripts/seed_pm.py` 预置项目/白名单/35 项材料/5 条 workshop 任务
5. **.env 可选配置**：`PM_TOKEN_SECRET`（留空回退 JWT_SECRET_KEY，生产建议独立随机串）、`PM_TOKEN_EPOCH`（默认 1，+1 全员重签）、`PM_MAX_UPLOAD_MB`（默认 50）、`PM_FILE_SIGN_TTL_SECONDS`（默认 300）
6. **部署**：deploy.bat 已含 frontend-pm 构建 + SCP（/var/www/pm/dist，marker 增量，失败留标重试）；资料文件备份已由 backup-uploads.bat 覆盖（backend/data → backend_data）。2026-07-21 起同段额外产出**内网入口构建** `frontend-pm/dist-lan`（`--base=/pm/`），由本机后端托管在 `/pm/`——内网访问 `http://192.168.101.193:8001/pm/`，大文件上传直连后端绕开 frp 隧道；两份构建同步产出，PM_CHANGED 跳过时两边一致陈旧不漂移。注意 bat 里 `--base=/pm/` 只能在 cmd 环境跑，Git Bash 会把 `/pm/` 改写成 MSYS 路径
7. **限速启用 IP 维度的前置（红线，2026-07-18 审查发现）**：不仅要 Nginx 设 X-Forwarded-For + uvicorn 开 `--proxy-headers`，**更前置的是先关闭后端 8002 端口的公网直连**。当前 frps 把 8002 以 `0.0.0.0` 暴露公网、明文 HTTP 可达，任何人 `curl -H 'X-Forwarded-For: 伪造IP' http://<服务器>:8002/api/pm/entry` 就能绕过 Nginx 直打后端并伪造 XFF——此时启用 IP 限速/IP 审计等于给攻击者递了伪造入口。修复：frps 代理端口绑 `127.0.0.1`（Nginx 本就 proxy 到 127.0.0.1:8002，零影响）或安全组封 8002 公网入站，仅放行 localhost。**主应用物流 MCP 仍 mount 在 `/mcp` 且未由主站/PM Nginx 反代；2026-07-22 新增的 `/mcp/social-customer/` 是云端 8100 独立服务，不走 8002。**
8. **下线**：摘 server block + DNS 记录即可，后端模块留存不影响平台

## 社媒客户查询 MCP（云端独立服务）

- 公网：`https://leshine.work/mcp/social-customer/`
- systemd：`social-customer-mcp.service`
- 安装目录：`/opt/social-customer-mcp`
- 本机健康检查：`curl -fsS http://127.0.0.1:8100/health`
- 日志：`journalctl -u social-customer-mcp -n 100 --no-pager`
- 重启：`systemctl restart social-customer-mcp`
- Nginx：主站 `/etc/nginx/conf.d/leshine.conf` 内独立 location，30 请求/分钟/IP；修改前必须备份并先测候选配置
- RDS：独立 `social_customer_mcp` 账号，只授予四张 `lsordertest` 表的 SELECT
- 完整部署、token 轮换和客户端示例：`docs/social-customer-mcp.md`
