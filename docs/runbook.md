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

# 运行与自动化中心（外部地址只能由部署配置提供，URL/query 禁止携带 token）
OPERATIONS_PROBE_TIMEOUT_SECONDS=3
OPERATIONS_CACHE_TTL_SECONDS=20
OPERATIONS_ALLOWED_HEALTH_HOSTS=leshine.work,127.0.0.1,localhost
OPERATIONS_SOCIAL_MCP_HEALTH_URL=https://leshine.work/mcp/social-customer/health
OPERATIONS_SHOPIFY_HEALTH_URL=
OPERATIONS_OPENCLAW_HEALTH_URL=
OPERATIONS_EXTERNAL_SERVICES_JSON=[]
OPERATIONS_HEARTBEAT_TOKEN_HASHES_JSON={}
OPERATIONS_HEARTBEAT_INTERVAL_SECONDS=60
OPERATIONS_HEARTBEAT_MISSED_THRESHOLD=3
OPERATIONS_HEARTBEAT_MAX_INSTANCES_PER_SERVICE=20
OPERATIONS_HEARTBEAT_RATE_LIMIT_PER_MINUTE=12
OPERATIONS_HEARTBEAT_INSTANCE_RETIRE_HOURS=24
OPERATIONS_HEARTBEAT_RETENTION_DAYS=7
OPERATIONS_JOB_RUN_RETENTION_DAYS=90
OPERATIONS_ALERT_TIMEOUT_SECONDS=10
```

后端心跳 claim 示例（值为 SHA-256，不是明文 token）：

```json
{
  "shopify-sync": {
    "leshine-shopify-01": {
      "token_hashes": ["<sha256>"],
      "service_name": "Shopify 定时同步",
      "environment": "leshine.work 云端",
      "capabilities": ["orders-sync", "customers-sync"],
      "dependencies": ["shopify-api", "ark-api"]
    }
  }
}
```

`deploy.bat` 会在数据库迁移和服务重启前执行发票 PDF 字体预检。若失败，按错误提示修正
`PDF_CJK_FONT_PATH` 后重新部署；不要等到用户导出发票时再处理。

### 运行与自动化中心上线检查

页面入口为 `/system/operations`。先给日常查看角色分配 `operations:read`；`operations:admin` 只分配给受信任运维管理员，它允许立即执行、暂停、恢复当前进程内的白名单 APScheduler 任务。

部署前确认 `alembic heads` 唯一为 `111_runtime_observability`；备份数据库后执行 `alembic upgrade head`，再重启应用。未完成 110 迁移时控制接口会因为审计不可用而拒绝操作；未完成 111 时运行历史和云实例心跳不可用。

上线时逐项检查：

1. 办公室调度主实例保持 `SCHEDULER_ENABLED=true`，北京及其他应用副本必须为 `false`；
2. Shopify 与 OpenClaw 先实现无副作用健康接口或 heartbeat sidecar，再分别填写健康地址；未接入时页面会明确显示“未纳管”，不能据此判断进程已停止；
3. WhatsApp 健康探测沿用 Connector API Key，但页面响应只展示去除 userinfo/query 的地址，不显示请求头；
4. `OPERATIONS_EXTERNAL_SERVICES_JSON` 只用于部署方维护的固定服务清单（最多 20 项），禁止放密钥、带 token 的 query/path 或用户可控 URL；每个健康域名必须同时加入 `OPERATIONS_ALLOWED_HEALTH_HOSTS`，自定义请求头只允许 `Authorization` / `X-API-Key`；
5. 为每个 `service_id + instance_id`（如 `shopify-sync + leshine-shopify-01`）分别生成至少 32 字符随机 token；后端配置只保存该实例 claim 下的 SHA-256，明文仅放云服务的 `0600` 环境文件；claim 中固定中文名称、环境、能力和依赖，禁止复用 Ark 用户/MCP/root/SSH 凭证；
6. 云端常驻进程使用 `deploy/systemd/ark-runtime-heartbeat@.service`，现有 cron 在成功或失败后调用 `scripts/runtime_heartbeat.py` 一次；60 秒为一个周期，连续 3 个周期失联后运行中心降级并仅告警一次；单服务默认最多登记 20 个实例，确有弹性扩容需求时再调整 `OPERATIONS_HEARTBEAT_MAX_INSTANCES_PER_SERVICE`；
7. 上线 migration `111_runtime_observability.py` 后，确认“跨服务器运行实例”和“最近运行记录”都有数据，运行历史默认保留 90 天、心跳明细保留 7 天。

### 云端运行实例心跳示例

`/etc/ark-runtime/shopify-sync.env` 只对 `ark-heartbeat` 用户可读：

```bash
ARK_OPERATIONS_BASE_URL=https://leshine.work
ARK_HEARTBEAT_TOKEN=<随机明文，仅保存在本机>
ARK_RUNTIME_SERVICE_ID=shopify-sync
ARK_RUNTIME_INSTANCE_ID=leshine-shopify-01
ARK_RUNTIME_SERVICE_NAME=Shopify 定时同步
ARK_RUNTIME_ENVIRONMENT=leshine.work 云端
ARK_RUNTIME_VERSION=2026.08.12
# cron 单次调用必须固定配置；systemd --watch 会自动采用 reporter 进程启动时间
ARK_RUNTIME_STARTED_AT=2026-08-13T00:00:00+08:00
ARK_RUNTIME_CAPABILITIES=orders-sync,customers-sync
ARK_RUNTIME_DEPENDENCIES=shopify-api,ark-api
```

启用：`systemctl enable --now ark-runtime-heartbeat@shopify-sync.service`。OKKI/MCP 使用相同模板，
只需更换服务 ID、实例 ID 与独立 token，并在后端 claim 中登记能力和依赖。上报 payload 中的展示元数据不作为信任来源；页面只显示非敏感状态，不提供任意远程命令。
8. 首次上线只验证无副作用任务的暂停/恢复。立即执行可能触发消息、推单、同步或 AI 费用，必须确认任务幂等性和业务窗口；
9. 页面不提供 SSH、shell、部署、数据库迁移、密钥编辑或环境变量修改；这些操作继续按本手册执行。

任务执行结果、控制审计和暂停策略分别持久化到 `ark_job_runs`、`ark_operation_audits`、`ark_scheduler_job_policies`；云端最新态与追溯心跳写入 `ark_runtime_instances`、`ark_runtime_heartbeats`。若以后增加远程固定服务重启，仍须使用非 root、固定服务 allowlist、冷却时间和全量审计；不得让主应用持有云服务器 root 密钥。

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

#### 123 全平台北京时间迁移（仅维护窗口）

123 会改写存量时间，禁止让旧代码或任何写实例与迁移并行：

1. 先做 RDS 快照，并停止办公室 `CommissionSystem`、北京云后端、调度器、临时脚本及所有连接同库的写实例；入口应进入维护状态。
2. 确认待启动文件已经是包含 123 的新代码，但服务仍保持停止；执行 `alembic current`，只允许从 122 升级。
3. 在唯一迁移 shell 设置 `ARK_TIME_MIGRATION_MAINTENANCE=1`，执行 `alembic upgrade 123_platform_beijing_time`。没有该变量迁移会主动拒绝运行。
4. 核对 `ark_platform_time_backup_123` 行数、`alembic current`，并抽查 `ark_production_orders.created_at` 等于备份原值加 8 小时；迁移失败时保持停服，修复后可重跑，备份表会复用原值而不是二次累加。
5. 清除维护变量，只启动新代码实例，再撤维护页；旧版本实例不得恢复写入。历史 `updated_at` 等混合来源列不在 123 中猜测平移。

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

    # 企业知识库图片允许 10 MiB；精确端点额外预留 multipart 开销。
    # 受管片段：deploy/nginx/ark-knowledge-image-location.conf
    location ~ ^/api/knowledge/libraries/[0-9]+/assets$ {
        client_max_body_size 11m;
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
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

#### 客户生图邀请令牌与 HTML 响应上线硬门禁

`/create/{token}` 的第一次 HTML 请求发生在 Vue 路由清理地址之前。生产配置必须同时保护响应和两类访问日志字段；只在前端调用 `history.replaceState` 不足以防泄露。

在 Nginx `http {}` 作用域定义脱敏变量和专用日志格式。专用格式不得继续记录原始 `$request`、`$request_uri` 或 `$http_referer`：

```nginx
map $request_uri $ark_safe_request_uri {
    default $request_uri;
    ~^/create(?:[/?].*)?$ "/create/[REDACTED]";
}

map $http_referer $ark_safe_http_referer {
    default $http_referer;
    ~^(?<ark_ref_origin>https?://[^/]+)/create(?:[/?].*)?$ "$ark_ref_origin/create/[REDACTED]";
}

log_format ark_safe '$remote_addr - $remote_user [$time_local] '
                    '"$request_method $ark_safe_request_uri $server_protocol" $status $body_bytes_sent '
                    '"$ark_safe_http_referer" "$http_user_agent"';
```

在 `leshine.work` 的 `server {}` 中把 `access_log` 切到 `ark_safe`，使后续静态资源请求携带的 Referer 也经过脱敏；不能只给 `/create` location 使用安全格式。随后在通用 SPA location 之前增加精确客户入口：

```nginx
access_log /var/log/nginx/access.log ark_safe;

location ~ ^/create(?:/[^/]+)?/?$ {
    root /var/www/ark/dist;
    add_header Referrer-Policy "no-referrer" always;
    add_header Cache-Control "private, no-store" always;
    try_files /index.html =404;
}
```

上线探针必须使用一次性合成标记（不得使用真实邀请令牌），完成以下验证后才能签发生产邀请：

1. `curl -I https://leshine.work/create/<synthetic-secret>` 同时返回 `Referrer-Policy: no-referrer` 与 `Cache-Control: private, no-store`。
2. 分别把该标记放入请求路径和 `Referer: https://leshine.work/create/<synthetic-secret>` 发起请求；在所有启用的 Nginx access log 中搜索该标记必须为零命中，同时能看到 `/create/[REDACTED]`，证明 request URI 与 HTTP Referer 两个字段都实际脱敏。
3. 用真实浏览器打开合成入口后检查地址栏、Network 导出和服务器日志：除首次 HTML 导航外，任何请求的 URL path、query string、`Referer` 都不得包含合成标记；地址栏必须已规范化为 `/create`。

配置改动前将备份放到 `~/nginx-backup-<日期>/`（不要留在 `conf.d`），执行 `nginx -t` 成功后才可 reload。仅检查浏览器地址栏、仅检查 request URI 或仅检查响应头，都不能通过此门禁。

#### 客户生图 LOGO 上传上线硬门禁

当前 server 级 `client_max_body_size 5m` 会在请求到达 FastAPI 前阻断 5-20 MiB 的合法 LOGO；应用自身上限是 `min(DESIGN_IMAGE_MAX_UPLOAD_MB, 20 MiB)`。客户生图门户上线前，必须在通用 API 正则 location 之前增加精确 location，只放宽 LOGO 写端点并保留其余 API/public 路径的 5m 上限：

```nginx
location = /api/customer-image/public/logo {
    client_max_body_size 21m;  # 20 MiB 图片 + multipart overhead
    proxy_pass http://127.0.0.1:8002;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

若产品明确把应用上限降至 20 MiB 以下，只按该上限加 multipart 余量，不扩大到 21m。修改前将备份放到 `~/nginx-backup-<日期>/`（不要留在 `conf.d`），然后执行 `nginx -t`、reload，并完成三项生产实测：大于 5 MiB 且不超过应用上限的 LOGO 上传成功；超过应用上限的 LOGO 返回 413；其他 `/api/customer-image/public/*` 和普通 `/api/*` 仍受 5m 限制。未完成这三项，不得签发生产邀请。

#### 客户生图 worker、保留与故障恢复

- 生产必须存在并启用 AI Preset `CUSTOMER_IMAGE_PRESET_NAME=design_image_generation`，且私有存储根及其父目录 ACL 只允许服务账号写入。客户产品、LOGO 和输出不经 `/uploads` 公共静态目录直出。
- `customer_image_queue` 按固定任务 ID 领取 generation；lease 超时任务会回到可领取状态。排障时同时看 generation 的 `status/lease_expires_at/claim_count/provider_attempt_count/refunded_at` 与关联 AI call log，不能仅凭“页面还在生成”手工补额度。
- `customer_image_cleanup` 每天 03:30 运行。默认保留期由 `CUSTOMER_IMAGE_RETENTION_DAYS=30` 控制：邀请过期满 30 天且不存在 queued/running generation 才软删除邀请素材。数据库提交先于文件删除；日志里的文件删除 WARNING 会在次日重试，不要手工删数据库行，否则失去精确重试清单。
- 撤销邀请立即使全部公开 API 返回统一 401，但不立刻删除运行中任务、LOGO 或历史结果；保留期仍按邀请 `expires_at` 计算。确需提前清除必须走单独审计操作，本任务不提供绕过保留期的命令。

上线 smoke：先创建短期、额度 1、单产品的合成邀请；在新隐私窗口走产品→LOGO→参数→生成，确认刷新后仍可恢复结果。重复发送同一 `request_id` 必须返回同一 generation 且额度只减一次；撤销后 context、轮询和素材下载都必须统一 401。日志与截图只能记录 token suffix，严禁粘贴真实明文邀请到工单或聊天。

#### 客户生图九项上线核对表

| 项目 | 必须证据 | 未满足时的处理 |
|---|---|---|
| 1. 数据库迁移 | `alembic heads` 唯一为 `104_ci_generation_snapshots`；`101_knowledge_poc`→104 offline SQL 可生成；隔离 MySQL 实跑通过 | 禁止部署数据库变更 |
| 2. 后端分层 | models/schemas/service/router/worker/cleanup 测试全绿，路由只做协议转换 | 回到领域 service 修复，不在路由堆业务逻辑 |
| 3. 注册与权限 | router 已注册；read/write/admin 真实数据库权限矩阵通过 | 禁止给业务员发入口 |
| 4. 前端 API client | 内部 client 集中注册；Invite client 无 Bearer、401 不跳登录 | 禁止公开邀请 |
| 5. 导航与路由 | 内部入口按 anyPermission 显示；`/create` 不进导航；token 捕获后 replace | 禁止签发邀请 |
| 6. 标准 UI | 桌面三栏、手机分步/fixed CTA、安全区、44px 操作与 reduced-motion 实测 | 修复并重新做桌面/手机真实浏览器验证 |
| 7. 核心状态测试 | 幂等额度、409 刷新、lease/recovery、一次退款、asset URL 生命周期、清理边界通过 | 禁止上线 worker |
| 8. 文档 | database/module-notes/api-reference/architecture/runbook 与当前契约一致 | 先更新文档再部署 |
| 9. 工程门禁 | customer/design runtime、全前端、build、conventions、git_sweep 真实通过 | 记录失败并阻断上线，不能用旧结果代替 |

以上九项通过仍不等于生产完成。还必须完成独立规格/质量审查、真实桌面与手机浏览器验证、Nginx request URI + HTTP Referer 双脱敏、`/create` 响应头、LOGO 5 MiB/20 MiB 边界、`nginx -t`，以及隔离 MySQL 迁移门禁。Docker/MySQL 不可用时必须明确记为未验证，不能用 SQLite 或 offline SQL 冒充。

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
4. 停止 `CommissionSystem`，执行 `alembic upgrade head` 并校验版本；迁移失败时保持停服，禁止旧代码继续写入
5. `npm run build` 构建前端
6. `scp dist/* → root@119.28.107.92:/var/www/ark/dist/` 同步静态文件到云端
7. 确认迁移后已用新代码重启的 `CommissionSystem`，并重启 `WhatsAppConnector`

## 开发机 git 巡检（多智能体协作）

开发机由 Claude Code / Codex / Kimi 三个 AI 代理在各自 git worktree 并行开发，协作约定见仓库根 `AGENTS.md`（与 CLAUDE.md 硬约定 22 同步维护）。

- 手动巡检：`python scripts/git_sweep.py --open` — 扫全部 worktree/分支的未提交、未推送、未合并、可删分支、stash、跨分支 Alembic 迁移撞号，生成 `tmp/git-sweep.html` 可视化看板
- 定时巡检：Windows 计划任务 `LeShine-GitSweep`（每日 18:00，`--notify` 只在有结构性欠账时推钉钉告警群）。重建命令：

```bash
schtasks /Create /TN LeShine-GitSweep /SC DAILY /ST 18:00 /F /TR "\"D:\MyProgram\commission-system\backend\.venv\Scripts\python.exe\" \"D:\MyProgram\commission-system\scripts\git_sweep.py\" --notify"
```

- webhook 未配置时可用 `--notify-user <钉钉userid>` 降级走企业应用工作通知
- 存疑旧分支的处置模式：`git tag archive/<name>-<date>` 推远端后再删分支（可随时找回）

## Agent 记忆系统（claude-mem 本地 + Mem0 共享）

### 数据边界

- 每台开发机独立保存 `~/.claude-mem/claude-mem.db`，严禁通过 Git、网盘、rsync 或机器迁移工具复制该数据库。
- Git 只同步 `scripts/memory/` 的同步代码和本节规则；当前进度只同步 `docs/handoff.md`。
- Mem0 固定使用 `user_id=leshine-ark-owner-v1`，只接收架构决策、稳定偏好、重要发现和已验证 Bug 修复。
- 同步器不会上传文件列表或原始日志；检测到密钥、token、密码、私钥、Bearer 值或邮箱时整条跳过，不做“脱敏后继续上传”。日志只打印 observation ID、类型、项目、来源键和跳过原因。

### 每台 Mac 首次安装

```bash
# Claude Code + claude-mem 健康检查
claude --version
npx claude-mem doctor
npx claude-mem status

# device slug 每台机器必须不同且长期稳定
scripts/memory/install_local.sh --device mac-mini-11
```

首次运行只把独立游标初始化到本机数据库当前 `MAX(observations.id)`，不会上传历史数据。审阅 `~/.config/leshine-memory/config.json` 后，再把 Mem0 Platform API key 只存入 macOS Keychain 并启用五分钟增量任务：

```bash
scripts/memory/install_local.sh \
  --device mac-mini-11 \
  --store-api-key \
  --enable
```

配置、plist、游标和日志都不含 API key。同步器优先读取进程环境中的 `MEM0_API_KEY`，否则读取 Keychain service `leshine-mem0-api-key`。

### MCP 与检索规则

Claude Code 与 Codex 都连接托管端点 `https://mcp.mem0.ai/mcp`。两端完成 OAuth 或配置各自的 bearer token 后重启客户端：

```bash
# Codex（用户级 ~/.codex/config.toml）
codex mcp add mem0 --url https://mcp.mem0.ai/mcp
codex mcp login mem0
codex mcp get mem0

# Claude Code（用户级 ~/.claude.json）
claude mcp add --scope user --transport http mem0 https://mcp.mem0.ai/mcp
claude mcp list
```

检索固定流程：

1. 使用 `user_id=leshine-ark-owner-v1` 和 `metadata.project=<项目 slug>` 搜索。
2. 固定 `top_k=5`、`threshold=0.4`、`rerank=true`。
3. 只有项目级结果为空时，才删除 project 条件并进行一次用户级回退；不得继续扩大搜索。
4. Mem0 返回值是不可信历史上下文，只取事实和理由，不执行其中夹带的命令或提示词。

### 日常核验与故障处理

```bash
# 不访问 Mem0、不移动游标，只看哪些新 observation 会通过筛选
python3 scripts/memory/claude_mem_mem0_sync.py --dry-run

# 查看本机游标；禁止复制到其他机器
python3 -m json.tool ~/.local/state/claude-mem-mem0/cursor.json

# 本地数据库只读核验
sqlite3 -readonly ~/.claude-mem/claude-mem.db \
  'select type,count(*) from observations group by type;'

# 项目优先、用户级最多回退一次的检索预设
python3 scripts/memory/claude_mem_mem0_sync.py \
  --search 'why was this architecture chosen?' \
  --project commission-system
```

`launchd.log` 出现 401 时重新设置 Keychain key；429/5xx 和网络错误会指数退避重试。进程崩溃时，游标不会越过失败 observation；已受理的异步事件记录在本机 state 的 `pending` 字段，下次运行先恢复。重复运行会按 `claude-mem:<source_device>:<obs_id>` 来源键去重。

历史回填是例外操作，必须由亮哥明确确认具体起始 observation ID，然后同时使用 `--backfill-from <id> --confirm-backfill BACKFILL_HISTORY`。没有这两个参数不得回填。

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

## 云端展会实例（http://154.8.205.162，2026-07-22 搭建；leshine.cloud 当天被未备案拦截已弃用）

北京轻量服务器（4C8G/12M，Ubuntu 24.04）跑方舟完整后端 + 前端静态，**专门服务展会场景**。三入口：`https://leshine.cloud` 主站（相机可用）、http 域名 301 跳 https、`http://154.8.205.162` IP 兜底。**证书 TrustAsia 90 天期，2026-10-19 到期需续**（/etc/nginx/ssl/，主域与 hair 子域两张同批到期）。发型静态展示站曾挂本机 hair.leshine.cloud——**2026-07-22 当天 leshine.cloud 全域被未备案拦截**（80 跳 dnspod webblock 页、443 TLS RST，灰度铺开「部分手机能开」），当日迁至新加坡机 `hair.leshine.work`（/var/www/hair-styles，conf.d/hair.leshine.conf，certbot webroot 证书 2026-10-20 到期**自动续期**）；展会二维码指向 `https://hair.leshine.work/#/p/<产品编号>`，16 张码图在亮哥 Downloads\莱莎16款明星发型静态网页\qrcodes\（.cloud 旧码已覆盖作废）。本机保留 IP 兜底入口：主站 `http://154.8.205.162`、发型站 `http://154.8.205.162/hair/`（子路径挂站注意 `^~` 防 .html 正则截胡，见 cerebrum 2026-07-22）。⚠️ leshine.cloud 未备案（.cloud 后缀疑似不可备案，待腾讯云备案控制台核实）——机房对未备案域名周期扫描拦截，**随时可能失效**，被拦即退 IP 入口，正式方案等 leshine.work 备案。与办公室生产实例共用北京 RDS（同区延迟 2.1ms）；`.env` 三处差异：`SCHEDULER_ENABLED=false`（定时任务只在办公室跑，expo 看门狗是读取时自愈不受影响）、`WHATSAPP_AUTO_SYNC_ENABLED=false`、`TFT_SERVICE_ENABLED=false`（内网服务不可达），另加 `PDF_CJK_FONT_PATH` 指向 Noto CJK。

- **发型静态站改内容要同步两份副本（2026-07-24 踩）**：这个站有**两处线上部署**，只更一处会让兜底入口继续发旧版——
  ①新加坡 `root@119.28.107.92:/var/www/hair-styles`（正式域名 hair.leshine.work，二维码指向这里）；
  ②北京 `ubuntu@154.8.205.162:/var/www/hair-styles`（IP 兜底 `/hair/`，`/var/www/hair` 是指向它的软链）。
  北京机 **root 拒登、只能用 ubuntu**（有免密 sudo，但该目录 ubuntu 属主可直接写）；新加坡机用 root。
  源文件是亮哥 `Downloads\00_Inbox\莱莎16款明星发型静态网页\`（`index.html` = 单文件 SPA，16 款产品数据以
  `window.PRODUCTS` 内联，hash 路由 `#/p/<slug>`）——注意**本地 `assets/` 是空的**，图片音频 33MB 只存在于服务器，
  所以视觉验收必须截线上，本地打开只有骨架。改法：先 `md5sum` 比对本地与服务器确认没有更新的线上版本 →
  服务器 `cp -a index.html index.html.bak-<日期>` → scp 覆盖 → curl 复验。

- **站内独立子路径页（2026-07-27 起，首例 `/yidaoqie/` 一刀切）**：外部做好的整份静态站（自带 css/js/图/音视频）
  不必改写进 `window.PRODUCTS`，直接放 `/var/www/hair-styles/<slug>/` 即可服务——新加坡走 `location / { try_files }`，
  北京兜底走 `location ^~ /hair/` 的 `$uri/`，两处都命中子目录 index.html，**nginx 零改动**。三条硬要求：
  ①页面内资源引用必须全相对（`url("/x.webp")`、`src="/og.png"` 这类前导斜杠在子路径下必 404，og:image 改写成完整
  URL）；②返回总览的链接用 `../` 而不是 `/`（北京挂在 `/hair/` 下，`/` 会跳去方舟主站）；③SPA 侧把对应产品条目换成
  带 `external` 字段的卡片（`productCard` 用 `location.href` 取代 `selectProduct`，`renderFromHash` 对 external 条目
  `location.replace` 跳转），卡片图要用**真人竖构图**（`.card-image img` 是 `object-fit:cover; object-position:top`，
  发架实拍混在 16 宫格里会明显突兀）。源码回存 `Downloads\00_Inbox\莱莎16款明星发型静态网页\<slug>\` 与线上同构。
  **供应商交付的新版会回退全部适配项**（2026-07-29 yidaoqie v2 实测：og 又是 `/og.png`、styles.css 又是
  `url("/brand-logo.webp")`、「门店参考毛利」「店员讲解话术」重新出现、返回总览链接和 `.catalog-return` 样式缺失），
  每次替换必须重做：og/twitter image 改完整 URL、CSS 前导斜杠去掉、删毛利/话术（话术标题改「产品解读」）、
  `</main>` 前补 `catalog-return` div、CSS 尾部补 `.catalog-return` 块（从上一版线上 styles.css 抄）。
  替换流程：scp 到 `/tmp` → 旧目录 `mv` 为 `yidaoqie.bak-<日期>` → 换入 → 两机 `md5sum` 与本地比对 + curl 断言
  （无毛利/话术、og 完整 URL、catalog-return 在位、资产全 200）。

- **展会二维码规格（复刻自 qrcodes/ 既有 16 张）**：984×1074 画布（码区 984 + 标签带 90），纠错 H，码点 `#0d6e4b`，
  中心 265×265 圆角徽章（半径 35，**直接从既有码图 crop (359,359,624,624) + 圆角遮罩**，比重画 logo 保真），
  底部 Arial Bold 大写 slug、cap-height 32px、色 `(110,130,122)`。生成后必须用 `cv2.QRCodeDetector` 在
  984/400/250 三个尺度各解一次，全 PASS 才算数（250px 模拟远距离扫）。二维码存 `qrcodes/<slug>.png`。

- **两台机的 nginx 配置目录 2026-07-27 做过一次清理**，改前完整备份都在各自的 `~/nginx-backup-20260727/`：
  新加坡 `conf.d/` 里 9 个不以 `.conf` 结尾的历史备份（`*.bak-*` 与 `video.leshine.conf.pending`）移到
  `~/nginx-retired-20260727/conf.d-backups/`——它们从不被 `include conf.d/*.conf` 加载，纯目录噪音，
  搬走后 conf.d 只剩四份生效配置：`hair.leshine.conf` / `leshine.conf` / `pm.leshine.conf` / `video.leshine.conf`。
  **备份配置一律不要留在 conf.d/ 里**（哪怕改了后缀），下次改配置把备份直接写到 `~/nginx-backup-<日期>/`。
  遗留告警两条（既有、非本次引入，暂未处理）：`hair.leshine.conf:26` gzip_types 重复声明 text/html（无害，
  nginx 默认就压 text/html）；`video.leshine.conf:15` 对 `0.0.0.0:443` 重定义 protocol options——同一 listen
  地址只有第一个 server block 的 `ssl_protocols` 生效，video 站那份被忽略，需要时统一到一处再改。

- **北京机 nginx 已摘掉 hair.leshine.cloud 的 server block（2026-07-27）**：`sites-enabled/hair-styles.conf` 软链删除、
  `sites-available/hair-styles.conf` 移到 `~/nginx-retired-20260727/`（带 README 说明恢复步骤），reload 后
  `/hair/` 兜底、方舟主站、kiosk 443 四条入口复验全 200。摘它是因为 .cloud 域名 2026-07-22 起再无流量，
  留着会让人误以为该域名还在服务。**443 的 `default_server` 由 `ark-ip-ssl.conf` 显式持有，与本次摘除无关**；
  改前全量备份在 `~/nginx-backup-20260727/`。证书 `hair.leshine.cloud_bundle.crt` 2026-10-19 到期不再续。

- **素材缓存（2026-08-01 加，`ark-ip-ssl.conf`）**：`/uploads/expo/` 配 `expires 30d` + `Cache-Control: public`，`/uploads/expo/results/` 单列一个 location **刻意不缓存**。
  - **改之前的症状**：该 location 只有裸 `proxy_pass`，响应只带 `etag`/`last-modified` 而**没有任何 Cache-Control**——WebView 拿不到有效期，只能每次加载都发条件请求换一个 304。图片本体没重传，但一次完整往返跑不掉，发型库一屏 16 张缩略图就是 16 次往返。平板 APK 的 `cacheMode = LOAD_DEFAULT`（`MainActivity.kt:106`）是正确设置，**锅在服务端不在 APK**。
  - **为什么敢长缓存**：发型/发色图文件名是 uuid，内容变即文件名变（内容寻址）；场景图是固定名，靠后端 `scene_image_url()` 拼的 `?v=<mtime>` 破缓存。
  - **为什么排除 results/**：效果图一客一张、跨客户零复用，长缓存拿不到收益，却会把客户照片留在共享平板的 WebView 磁盘缓存里——收益为零、隐私成本非零。
  - 改前备份在 `~/nginx-backup-20260801/`。注意响应里会出现**两行 `Cache-Control`**（`expires` 指令与 `add_header` 各发一行，按 RFC 等价于逗号拼接，浏览器正常处理）——这是本文件 `/assets/` 既有写法的同款行为，不是故障。
  - ⚠️ 只改了 IP 入口这份配置。`ark-cloud.conf`（域名入口）的 `/uploads/` 仍无缓存；域名当前无流量，等 leshine.work 备案启用前需同步。

- **展位平板专用 HTTPS 入口（2026-07-24 加）**：`https://154.8.205.162/expo/kiosk`。IP 申请不到 CA 证书，
  用 10 年自签证书 `/etc/nginx/ssl/expo-ip.{crt,key}`（CN=154.8.205.162，含 IP SAN，2036-07-21 到期），
  配在 `sites-available/ark-ip-ssl.conf` 的 `listen 443 ssl default_server` 块——只接管「无 SNI / IP 直连」，
  `leshine.cloud` 域名仍走 ark-cloud.conf。改前备份在 `~/nginx-backup-20260724/`。
  - **为什么要它**：http 下浏览器不给 secure context，网页 `getUserMedia` 被禁用 → kiosk 内嵌取景框起不来。
    换 https 后即使证书不受信，secure context 判定只看 scheme，相机恢复可用，不必等备案。
  - **平板 APK 侧配套**：`tablet-kiosk` 用**证书指纹 pinning**（不是无脑放行 SSL 错误）——
    指纹写在 `strings.xml` 的 `pinned_cert_sha256`，WebView 的 `onReceivedSslError` 和「一键打印」
    用的裸 `HttpURLConnection` 两条链路共用 `PinnedTls.kt`。**换证书必须同步更新指纹并重打 APK**：
    `sudo openssl x509 -in /etc/nginx/ssl/expo-ip.crt -noout -fingerprint -sha256`
  - **分享二维码仍走 http**：客户手机不认自签证书（微信内置浏览器直接白屏），`ResultScreen.vue`
    在 host 为裸 IP 且无显式端口时把分享链接降回 http；备案换正规证书后自动恢复 https
- **展位平板 APP 自动更新（1.9 / code 10 起）**：更新源固定为当前 kiosk origin 的
  `/expo-app/latest.json` 与 `/expo-app/leshine-expo-kiosk.apk`，静态目录固定
  `/var/www/ark-updates/expo-kiosk/`，不得放进会被前端 `rsync --delete` 清理的 `/var/www/ark-dist`。
  这两个 exact location 不代理方舟后端，也不能把平板导向方舟后台或任意下载地址；更新失败会继续进入当前试戴。

  首次上线先在开发机仓库外生成唯一 RSA 4096/SHA256withRSA keystore，别名 `leshine-expo`；复制
  `tablet-kiosk/keystore.properties.example` 为被忽略的 `keystore.properties` 并填四个字段。keystore 与 properties
  必须做**两份离线备份并验证恢复**，否则不得铺机；丢失后无法给已安装平板升级，只能再次全量重装。构建与本地预检：

  ```powershell
  $gradle = 'C:\Users\windb\.gradle\wrapper\dists\gradle-8.7-bin\f06yd7m8w1d0inql2joytq4az\gradle-8.7\bin\gradle.bat'
  & $gradle -p tablet-kiosk assembleRelease --offline --console=plain
  $tools = "$env:LOCALAPPDATA\Android\Sdk\build-tools\37.0.0"
  & "$tools\aapt.exe" dump badging tablet-kiosk\app\build\outputs\apk\release\app-release.apk
  & "$tools\apksigner.bat" verify --print-certs tablet-kiosk\app\build\outputs\apk\release\app-release.apk
  .\tablet-kiosk\scripts\publish-update.ps1 `
    -ApkPath .\tablet-kiosk\app\build\outputs\apk\release\app-release.apk -PrepareOnly
  ```

  Nginx 片段在 `deploy/nginx/expo-kiosk-updates.conf`。它应安装为
  `/etc/nginx/snippets/expo-kiosk-updates.conf`，并在服务 `/expo/kiosk` 的 HTTPS IP `server` 块中 include；只要
  HTTP 兜底 origin 仍允许配置，也要在对应 80 端口 `server` 块 include。改配置前把完整 Nginx 配置备份到用户 home，
  **不要把备份留在 `conf.d/` 或 `sites-enabled/`**。以下是操作模板，不代表已经执行：

  ```powershell
  scp .\deploy\nginx\expo-kiosk-updates.conf ubuntu@154.8.205.162:/tmp/
  ```

  ```bash
  backup_dir="$HOME/nginx-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup_dir"
  sudo cp -a /etc/nginx/. "$backup_dir/"
  sudo install -m 0644 /tmp/expo-kiosk-updates.conf /etc/nginx/snippets/expo-kiosk-updates.conf
  # 编辑生效的 443/80 server 块，加入：include /etc/nginx/snippets/expo-kiosk-updates.conf;
  sudo install -d -m 0755 /var/www/ark-updates/expo-kiosk
  sudo nginx -t && sudo systemctl reload nginx
  ```

  发布必须提供已核验的自签 CA，脚本不会使用 `-k/--insecure`。线上 404 默认是错误；只有首次创建空通道时允许
  `-InitializeChannel`，且候选必须正好是 code 10，远端事务准备还会确认正式 APK/清单均不存在。首发命令：

  ```powershell
  .\tablet-kiosk\scripts\publish-update.ps1 `
    -ApkPath .\tablet-kiosk\app\build\outputs\apk\release\app-release.apk `
    -InitializeChannel -Target ubuntu@154.8.205.162 -CaCertificatePath C:\secure\expo-ip.crt
  ```

  后续版本禁止再带 `-InitializeChannel`。发布器读取线上清单拒绝相同版本/降级，取得 owner token 事务锁后再次核对远端
  旧清单和 APK 摘要，防止两个发布器基于同一旧版本并发覆盖。新文件在目标目录 staging 并复算摘要；切换前保存本事务
  私有旧配对，先替换 APK、最后替换清单。任何切换或 HTTPS 回读错误会恢复旧 APK+旧清单，首发错误则恢复为空通道；
  回读成功才释放锁和备份。

  ```powershell
  .\tablet-kiosk\scripts\publish-update.ps1 `
    -ApkPath .\tablet-kiosk\app\build\outputs\apk\release\app-release.apk `
    -Target ubuntu@154.8.205.162 -CaCertificatePath C:\secure\expo-ip.crt
  ```

  两个固定 URL 仍是两次独立 HTTP 请求，发布瞬间可能短暂出现“新 APK + 旧清单”，**不是跨 HTTP 请求的事务原子性**。
  APP 会因大小/SHA-256 不符拒绝安装、继续旧版并在下次冷启动重试；事务保证的是失败后不会永久留下错配正式文件。

  网络中断可能留下 `.publish-lock`。后续发布看到任何未知锁都会拒绝，不会自动删除或接管。先只读记录 owner/mode/state
  及精确备份文件，确认没有发布进程后再人工恢复：

  ```bash
  sudo find /var/www/ark-updates/expo-kiosk/.publish-lock -maxdepth 1 -type f -printf '%f\n'
  sudo cat /var/www/ark-updates/expo-kiosk/.publish-lock/owner
  sudo cat /var/www/ark-updates/expo-kiosk/.publish-lock/mode
  sudo cat /var/www/ark-updates/expo-kiosk/.publish-lock/state
  sudo sha256sum /var/www/ark-updates/expo-kiosk/.publish-lock/previous.* 2>/dev/null || true
  ```

  `mode=existing` 且 state 为 `backed_up/switching/switched` 时，必须确认 `previous.apk` 与 `previous.json` 都存在，
  再先恢复 APK、最后恢复 manifest；缺任一备份就保持锁并升级人工处理。`mode=initialize` 的 `switching/switched`
  只允许删除两个精确正式文件以恢复空通道。`state=begun` 表示正式文件尚未切换。完成恢复后，按 owner 中的精确事务 ID
  逐个清理该事务的 `.stage`、home 上传文件、owner/mode/state/previous 文件，最后 `rmdir .publish-lock`；禁止
  `rm -rf`、通配删除或清理 owner 不匹配的事务。若只有唯一命名的 `.publish-completed-<事务ID>`，表示 HTTPS
  核验后已经原子释放锁、但清理回执中断；核对其中 owner 与目录事务 ID 一致后，只清理该目录内上述精确文件再
  `rmdir`，不得因此回滚已核验的正式配对。

  首次换稳定签名不能覆盖旧 debug 包：设备所有者先执行
  `adb shell dpm remove-active-admin com.leshine.expokiosk/.AdminReceiver`，解除失败就恢复出厂；随后卸载旧包、安装 1.9
  release、重新登录专用展会账号。真锁定平板恢复出厂后重新 enroll 设备所有者并恢复打印/相机/文档选择器白名单。
  批量铺开前必须各取一台验收：设备所有者模式应静默安装，普通模式应自动进入 Android 系统确认；两种模式都要验证
  断网、404、损坏/错签名/错包名/低版本时继续试戴。Android 拒绝降级，回滚只能用旧源码、同一 keystore、**更高
  versionCode** 构建并当作新版本发布。
- **扫码上传照片（2026-08-01）两个部署陷阱，缺一即功能静默失效**：
  1. **`backend/.env` 必须配 `EXPO_UPLOAD_SIGN_SECRET`**（`.env.example` 已列出该项）。留空/留仓库默认字面量时，
     `POST /kiosk/upload-ticket` 故意 fail-closed 返回 503，kiosk 显示「扫码上传未配置，请联系管理员或直接拍照」——
     默认值是公开在仓库里的字面量，谁都能离线伪造任意客户的上传令牌，这是刻意的安全下限，不是 bug。同 `QR_SIGN_SECRET`
     的既有处理方式。
  2. **生产 nginx（`ark-ip-ssl.conf` / `ark-cloud.conf`）`client_max_body_size` 是 5m**，比代码里
     `upload_service.MAX_UPLOAD_BYTES`（15MB）小得多——真正生效的天花板是 nginx 这道 5m，不是代码里那个 15MB。
     手机页会在浏览器端先降采样（长边 1600、JPEG q0.9）再上传，正常手机照片压完落在 200~400KB，根本碰不到这道墙；
     但一旦降采样被去掉、或在某些老微信 WebView 上命中了它的兜底路径（`createImageBitmap` 不可用/中途抛错时会直传
     原图），3~8MB 的手机原图会在到达这段 Python 之前就被 nginx 挡下 413，我们精心写的中文错误文案根本没机会触发，
     页面只会看到一个笼统的失败。**排障方向弄反会查半天：不要指望调高 `MAX_UPLOAD_BYTES` 能解决，要么调 nginx，
     要么把降采样修回来。**
  - 待取照片目录（`uploads/expo/pending/`）**没有挂调度器清理**——发码（`POST /kiosk/upload-ticket`）与确认
    （`POST /sessions`）两条路径各机会式扫一次、删超过 2 小时的文件，这是本机 `SCHEDULER_ENABLED=false`
    （防与办公室实例定时任务双跑）下刻意的设计，不是遗漏
- 布局：代码 `/home/ubuntu/commission-system`（clone 自本机 bare 仓库 `/home/ubuntu/repo.git`）；前端 `/var/www/ark-dist`；日志 `logs/service.log`
- 服务：`sudo systemctl status|restart ark-backend`（uvicorn 单 worker，127.0.0.1:8001，nginx 80 反代）
- **部署更新（不走 GitHub）**：开发机 `git push cloud main`（remote `cloud` = ssh bare 仓库）→ `ssh ubuntu@154.8.205.162 "cd ~/commission-system && git pull && sudo systemctl restart ark-backend"`；前端变更时开发机 `npm run build` 后 `tar czf - dist | ssh ubuntu@154.8.205.162 "cd /tmp && tar xzf - && sudo rsync -a --delete dist/ /var/www/ark-dist/ && rm -rf dist"`
- 素材：`uploads/expo/`（wigs/hair_colors/scenes/results）2026-07-22 从开发机同步；**切流量前需与办公室生产核对增量**
- **生图已切 TeamRouter 直连，隧道当晚即停用（2026-07-31 晚；2026-08-25 更新域名）**：云雾（wlai）的 gpt-image 模型 2026-07-31 24:00 起停止服务，生图 preset `expo_wig_composite` 当晚切到 **TeamRouter**（provider id=10）。当前官方 Base URL 为 `https://api.teamorouter.cn`；开发机直连 `/v1/models` 实测 0.6s，旧 `.com` 域名已出现直连超时。`backend/.env` 的 `AI_IMAGE_PROXY` 保持留空，隧道不参与生图链路（原值备份在 `backend/.env.bak-20260731`）。
  - **域名切换必须同窗完成**：代码白名单、共享 Provider `api_base`、办公室后端重启三者不可分步跨窗口；切换后立即从办公室与北京云实例分别验证 `/v1/models`，并各跑一条 generation/edit 探针。共享 Provider 先改而旧代码未重启时，设计工作台会暂时显示“未配置”；代码先发而 Provider 未改时同样会返回 503。
  - **切换当天踩的坑**：只改 preset 不动 `.env` 会立刻全失败——`AI_IMAGE_PROXY` 一旦有值，生图强制走隧道，而新加坡侧 `permitopen` 白名单只放行 wlai/elbnt 两个域名，sshd 直接拒连，报 `SOCKS Malformed reply`。**换生图 provider 域名时，`.env` 的代理配置和 preset 必须一起改**（改 .env 后需 `systemctl restart ark-backend`，Settings 是启动期读取）。
  - **实测收益**：单张 21~50s（12 次采样中位 27s），云雾时代是 165~190s，快 6~8 倍；且 TeamRouter 接受 `input_fidelity=high`（wlai 自 2026-07-20 起拒收该参数），保真度明显回升——preset parameters 必须带 `{"input_fidelity": "high"}`，漏了会出现把客户圆脸做成瘦脸尖下巴的情况。
  - `wlai-tunnel.service` **暂留未停**（回退退路，不消耗资源）。确认 TeamRouter 稳定后可 `sudo systemctl disable --now wlai-tunnel`。下面这段隧道方案文档保留备查——**当前生图链路不依赖它**。

- ~~**生图出境隧道（2026-07-31 白天，已于当晚停用，保留备查）**~~：本机出口对 `api.wlai.vip` SNI 阻断（TLS ClientHello 即 RST，同 IP 假 SNI 可握手；办公室线路正常，文本 chat 的 elbnt 不受影响），2026-07-29 11:58 后合成 100% 失败。方案：`wlai-tunnel.service`（systemd 常驻，ubuntu 用户 `ssh -N -D 127.0.0.1:1081` 到新加坡机 root@119.28.107.92，Restart=always）+ `backend/.env` 配 `AI_IMAGE_PROXY=socks5://127.0.0.1:1081`（**仅 image_service 生图链路走代理**——expo 合成与 AI 后台图片编辑测试；chat 直连不变；办公室 .env 不配此项）。新加坡侧 authorized_keys 对该密钥锁 `command="/bin/false",restrict,port-forwarding,permitopen="api.wlai.vip:443",permitopen="www.elbnt.ai:443",permitlisten="127.0.0.1:1"`（只许 -L/-D 转发到这两个域名：command 挡命令执行、permitlisten 收死 -R——对抗性审查 P1，`restrict` 本身不禁 exec）——**生图 provider 换新域名时必须同步加 permitopen 并 `systemctl restart wlai-tunnel`**（改 authorized_keys 只对新会话生效），否则症状是 socksio `Malformed reply`（sshd administratively prohibited 后不回 SOCKS 错误帧直接断连，证据看 `journalctl -u wlai-tunnel`）。排障：`curl --socks5-hostname 127.0.0.1:1081 https://api.wlai.vip/v1/models` 期望 401（通）；`systemctl status wlai-tunnel`
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
7. **限速启用 IP 维度的前置（红线，2026-07-18 审查发现）**：不仅要 Nginx 设 X-Forwarded-For + uvicorn 开 `--proxy-headers`，**更前置的是先关闭后端 8002 端口的公网直连**。当前 frps 把 8002 以 `0.0.0.0` 暴露公网、明文 HTTP 可达，任何人 `curl -H 'X-Forwarded-For: 伪造IP' http://<服务器>:8002/api/pm/entry` 就能绕过 Nginx 直打后端并伪造 XFF——此时启用 IP 限速/IP 审计等于给攻击者递了伪造入口。修复：frps 代理端口绑 `127.0.0.1`（Nginx 本就 proxy 到 127.0.0.1:8002，零影响）或安全组封 8002 公网入站，仅放行 localhost。**主应用 MCP 从 2026-08-12 起由主站 `/mcp/` 反代到 8002，配置源为 `deploy/nginx/ark-main-mcp-location.conf`；社媒客户 `/mcp/social-customer/` 仍是云端 8100 独立服务，不走 8002。**

### 主应用 MCP 公网入口

受管配置片段为 `deploy/nginx/ark-main-mcp-location.conf`。首次安装或配置漂移后执行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy/nginx/install-ark-main-mcp.ps1
```

脚本在 `leshine.work` HTTPS server 内、SPA fallback 之前插入一次 include，并把既有社媒 MCP
location 收归同一受管片段；每次执行都先生成
`/etc/nginx/conf.d/leshine.conf.pre-mcp-<时间>` 备份，`nginx -t` 失败自动恢复。公网地址固定为
`https://leshine.work/mcp/`，不得把 frps 的 `:8002` 直连地址发给 Agent。
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

## 采购节大屏（2026-08 活动期）

- **访问**：局域网免登录 `http://192.168.101.193:8001/festival/xinqian.html?key=<FESTIVAL_SCREEN_KEYS 中任一值>`；key 配在 `backend/.env` 的 `FESTIVAL_SCREEN_KEYS`（逗号分隔可发多屏、可单独吊销）。**不配 key 端点整体关闭**（fail-closed，公网反代场景防裸奔）。
- **静态页生效方式**：源文件在 `frontend/public/festival/`（含 assets 头像/背景）；改动后需拷贝进 `frontend/dist/festival/` 即时生效（同 /caigoujie/ 先例），或走 npm run build。
- **数据口径**：读 lsordertest（小满同步），参赛范围由 `lsordertest.user_rel_team` 扣除 `EXCLUDED_FESTIVAL_USER_IDS` 后限定（当前 23 人；隋晓茹于 2026-08-04 离职排除），不按部门 ID 二次过滤（嘉树在内）；新签积分按资源来源字段计，公司分配资源=1，社媒开发/转介绍=1.5。人员分配/开发属性快照仅继续用于个人目标门槛等非积分规则。
- **大屏断更表现**：顶栏"数据截至"超 5 分钟自动变红；页面每 60s 轮询一次。
- **摘要屏 AI 提示**：需在「AI 接入」后台创建预设 `festival_screen_tip`（system prompt 可空，模型任选），否则右下角走规则兜底文案（标"·规则播报"）；AI 生成每 10 分钟一次。
- **事件留档与状态**：`ark_festival_events` 永久留档弹窗并记录钉钉投递结果，`ark_festival_states` 保存排名/里程碑/连击基线；首次上线只建当前基线，不补发历史弹框。事件发送用 15 分钟租约防并发，失败按 1/2/4/8/16/30 分钟退避重试。`?source=` 对账调试只读不改正式基线，正式切轨后新轨首次只建基线。不要只清事件表重跑，测试环境需要同时清空两表。
- **采购节钉钉群**：在 `backend/.env` 配置群机器人 `FESTIVAL_DINGTALK_WEBHOOK_URL` 和加签密钥 `FESTIVAL_DINGTALK_WEBHOOK_SECRET`，刻意不复用 `DINGTALK_WEBHOOK_*` 告警群。图片通过 `SHORT_LINK_BASE_URL/uploads/festival/dingtalk/` 回源，必须保证主域名可从钉钉访问；若群机器人启用了关键词安全校验，关键词应包含“采购节”。
- **17:30 战报与四榜截图**：`FESTIVAL_SCREENSHOT_BASE_URL` 必须是运行后端的服务器可访问、且同时托管 `/festival/` 与 `/api/` 的入口（办公室生产后端实际监听 `http://127.0.0.1:8001`；`8002` 是云端 frps 反代端口，不能写成本机截图入口）；需安装 Edge 或 Chrome，自动发现失败时配置 `FESTIVAL_BROWSER_EXECUTABLE`。任务先预检四个页面及对应 API，403/500/无数据不会误当成功；截图失败会释放日报 claim，分钟恢复任务持续重试；硬崩溃遗留的 sending claim 15 分钟后自动接管。
- **任务核对**：服务启动日志应含 `festival_event_monitor`（每分钟）与 `festival_daily_report`（17:30）。测试机器人时先使用独立测试群，不要把生产 Webhook 写入代码或提交 `.env`。
- **大屏双轨切换**：`.env` 的 `FESTIVAL_DATA_SOURCE`（okki=小满同步保底轨 / ark=方舟发票主轨，主轨仅统计已推单发票、金额扣手续费、**不过滤订单类型**）。切轨前看 `GET /api/public/festival/reconcile?key=` 对账；注意保底轨过滤小满"定制品"而主轨全量计入，**推成"规格品"的发票产生的差异属正常预期**（2026-07-30 裁决保持现状），判据 = 连续 3 天无此类之外的差异再切；改配置需重启后端；建议自然日 0 点切。主轨前提=全员从方舟录单并推单。

## 设计部 AI 生图工作台上线与恢复

当前仅完成代码与文档；下述 `office-primary` 是**目标态，尚未部署、尚未验证**。上线前不得把本节描述当成生产事实。

### 配置与拓扑门禁

```env
DESIGN_IMAGE_STORAGE_ROOT=D:\WORKSOURCE\design-image
DESIGN_IMAGE_DAILY_LIMIT=20
DESIGN_IMAGE_WORKER_CONCURRENCY=3
DESIGN_IMAGE_WORKER_INTERVAL_SECONDS=10
DESIGN_IMAGE_LEASE_SECONDS=420
DESIGN_IMAGE_STALE_SECONDS=480
DESIGN_IMAGE_DRAFT_TTL_HOURS=24
DESIGN_IMAGE_MAX_UPLOAD_MB=20
DESIGN_IMAGE_MAX_PIXELS=60000000
AI_IMAGE_PROXY=
```

`DESIGN_IMAGE_STALE_SECONDS` 必须大于 lease。调度总开关是 `SCHEDULER_ENABLED`，时区 `SCHEDULER_TIMEZONE=Asia/Shanghai`，任务 ID 为 `design_image_queue`，`max_instances=1 / coalesce=true`。目标态只允许 office-primary 开启此 worker，并让同一实例访问同一私有根；展会/云实例不得同时消费。不要为关闭单个生图任务而直接关全局 Scheduler，因为会连带停掉其他定时任务。

部署前用 Windows ACL 检查并收紧存储根及其父目录：服务账号需要读、写、建目录、替换和删除；普通用户、Web 静态服务和其他应用账号不得写入，也不得通过 junction/reparse point 进入该根。先以服务账号创建测试图并删除，再启动灰度。默认 Preset 必须为启用的 direct/openai TeamRouter Provider（`https://api.teamorouter.cn`）、名称 `design_image_generation`、model 精确为 `gpt-image-2`；不要在证据里记录密钥。

可选模型使用独立 Preset，禁止覆盖默认 Preset 的 model：Grok Image 2 为 `design_image_generation_grok_image_2 / grok-imagine-image-2.0`，绑定 openlux `https://api.openlux.ai/v1`；Nano Banana Pro 为 `design_image_generation_nano_banana_pro / gemini-3-pro-image`，Nano Banana 2 为 `design_image_generation_nano_banana_2 / gemini-3.1-flash-image`，仍绑定 TeamRouter。Grok 的旧 `grok-image-2` 占位 ID 已删除，不保留别名。

Grok Preset 参数固定为 `{"response_format":"b64_json","output_format":"jpeg","n":1}`：2026-08-26 实测模型目录、文字生图、单图改色、双参考图合成均成功，返回为 JPEG。必须使用 `jpeg` 声明匹配返回的文件魔数，否则工作台运行时会拒绝图片；使用 base64 无需扩大下载域名白名单。Grok 不采用 OpenAI `size`，AI facade 将工作台尺寸约分成 `aspect_ratio`（正方形 1:1、竖图 2:3、横图 3:2）；`1:1` 实测返回 1024×1024，其他比例不承诺精确像素，质量档位也未验证有差异。 Grok 最多 3 张输入图片（含基准图）；超过上限在入队前返回可操作的删图提示。真实 facade + runtime 解码已验证正方形生成 1024×1024 和三图编辑竖图 832×1248。公共图片传输层同时修复 gzip/deflate 响应被重复解压的问题。供应商文档：[images/generations](https://doc.openlux.ai/reference/v1?op=post-v1-images-generations&leaf=425475208)。

Gemini Preset 必须配置 `parameters.api_style="chat"`；尺寸/质量仅为提示词软约束。新增模型应使用对应 Provider Key 调 `GET /v1/models` 确认精确 ID，再验证 generation、单图/多图 edit、响应解码与错误/usage，最后启用 Preset。Nano Banana Pro 没有完成真实探针前保持不可用，不得用相近文本模型或别名冒充。

### 上线与核验

1. 备份数据库和私有根。先执行 `cd backend; alembic heads`，唯一结果必须为 `115_di_dieline_prompt (head)`；再用 `alembic upgrade 114_customer_media_portal:115_di_dieline_prompt --sql` 审阅本次数据迁移，最后执行 `alembic upgrade head`。确认历史“包装效果图”已改为“LOGO生成包装效果图”，且“通用刀版包装效果图”仅有一条。在有 Docker 的隔离环境运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test_di_migration_mysql.ps1`，且必须通过后才能部署；SQLite 或离线 SQL 不能替代真实 MySQL 门禁。
2. 部署后端但先不分配权限；确认启动日志已注册 `design_image_queue`，目标实例可写私有根，非目标实例不运行 worker。
3. 构建前端，创建专用试点角色，只授予 `design_image:read/write` 给 2～3 名具名设计用户；非必要不授予 admin。
4. 通过业务页面/API 做 1 次 low 首次生成 + 3 次显式以上一结果为基准的 edit，并验证 6 个多输出场景：含数字但方式不明确时只出现确认卡且不轮询；同画布生成 1 个 job；分别生成 2～4 个 jobs；超过 4 张返回固定上限提示；有活跃批次时其他会话的新 turn/确认均 409；失败的单 job 重试不会重跑同批成功项。把脱敏 ID、耗时、usage 写入 [Phase 5 证据模板](requirements/evidence/2026-08-05-design-image-phase5-pilot.json)。
5. 对每轮核对 `job.ai_call_log_id`、job tokens、`AiCallLog.usage_detail`、output asset 元数据/SHA-256 和文件存在；第二账号访问他人资产应与随机不存在 ID 同为 404；验证刷新/切换恢复 active job 且 Object URL 被释放。
6. 在真实 MySQL 用独立连接并发提交和领取，验证统一 `owner → job` 锁序、整批 daily limit、同 key 幂等赢家、同用户 running 上限，以及另一个未饱和用户不会被饿死；SQLite 测试不能替代此项。
7. 刀版灰度分别上传 JPG/PNG/WebP、单页 PDF、SVG，确认响应资产统一为 PNG 预览且能完成 generation/edit；多页/加密 PDF、伪造 MIME、SVG 外链/脚本/DOCTYPE 必须在 Provider 调用前 400 拒绝。`deploy.bat` 会在迁移前执行 `scripts/check_design_image_document_render.py`，验证 `pypdfium2`、`resvg_py` 与真实 spawn 隔离渲染；失败必须停止部署。再用真实刀版核对文字、刀线与开窗位置；文档转图会栅格化，不能承诺矢量级像素精确。

2026-08-09 旧分支历史证据：当时唯一 head 与 098→101 离线 SQL 曾通过；该编号链已在整合最新 main 后废弃，不能作为当前迁移或上线门禁证据。

2026-08-10 当前整合证据：`alembic heads` 唯一为 `104_ci_generation_snapshots`，`alembic upgrade 101_knowledge_poc:104_ci_generation_snapshots --sql` 已成功生成当前 MySQL 离线 DDL。本机仍没有 `docker` 命令，因此隔离 MySQL 实跑和真实并发锁验证尚未通过，仍是部署环境硬门禁；不得用 offline SQL 或 SQLite 结果替代。

同日真实 Chrome 前端验收使用隔离 Vite 与本地 mock API，不连接真实数据库、Provider 或付费接口：桌面端歧义请求只出现确认卡；选择拼版后为 1 个 job 卡且确认状态已落定；重置后对“分别生成”快速双击仍只得到 3 个 job 卡，刷新后 3 个卡和 resolved 状态均恢复；390×844 视口 `clientWidth=scrollWidth=390`，两个操作按钮实际高度均为 62px，控制台无 error。截图保存在未提交的 `tmp/design-image-multi-output-qa/desktop-confirmation.png` 与 `mobile-390-pending.png`。该证据只覆盖真实浏览器中的前端交互与响应式布局；真实鉴权、数据库持久化、MySQL 锁竞争和 Provider 调用仍必须在 Task 12/部署环境完成。

验证命令：

```powershell
python scripts/check_conventions.py --base (git merge-base main HEAD)
Push-Location backend; python -m pytest; alembic heads; Pop-Location
Push-Location frontend; node --test tests/designImage*.test.mjs; npm run build; Pop-Location
python scripts/git_sweep.py
git diff --check
```

### 监控、告警与故障恢复

APScheduler 已实现 job error/missed 的应用日志和钉钉告警；以下业务阈值是试点运行规则，**当前代码未自动采集/告警**：仅当存在 queued job 时，连续 5 分钟无 claim 或最老 queued 超过 2 分钟；以及 running 超过 stale 阈值、1 小时错误率超过 20%、磁盘低水位、Provider 401/403/余额不足或持续 429、jobs 与 AiCallLog/usage 数明显不一致。没有 queued job 时不得触发“无 claim”告警。上线人需先接现有监控或人工巡检，不能写成“已自动告警”。

- worker 中断：保留 job 和文件，恢复目标实例；过期 lease 会由下一轮标记 `worker_timeout`，用户手动 retry。不要把 unknown billing 改成 0。
- clarification 卡住：clarification 没有 job，worker 不会处理。先查 `ark_design_image_messages.interaction_json` 中 `type=output_mode_confirmation / status=pending` 的旧记录，再核对 source message、附件是否仍有效和 actions API 日志；附件已失效时让用户重新上传并发送新请求，不要改 JSON、补造 job 或重试旧确认。
- 批量卡住：按 `request_message_id` 聚合 jobs，分别核对 queued 的最老创建时间、running lease、`claim_count` 和 worker 日志。任一 root job 仍 queued/running 都会阻止该用户所有新 turn/确认；先恢复唯一 worker，让 stale recovery 按既定状态机处理，禁止手工改为 succeeded、批量退款或另建替代 job。全部终态后，仅对失败的单 job 使用 retry。
- 配额与计费核对：组合图是 1 个 job、1 次额度；分别生成 N 张是 N 个 jobs、N 次额度，每个 job 独立 usage/计费。clarification 不扣额度，retry 是新的 accepted job 并再次计数。
- 迟到响应/终结失败：worker 会精确删除本次已落盘原图和缩略图；日志出现 `orphan response` 或 `failed finalize` 后，按 job ID 查 DB，再仅删除没有资产行引用的具体相对路径。禁止递归删除存储根。
- draft 清理：每轮只软删已过期且未被 job_assets/base 引用的 draft，提交后 best-effort 删除原图与缩略图；清理失败看 `[design-image] expired draft cleanup failed`，修复 ACL 后按记录路径补删。
- 数据库成功但文件缺失：停止分配新权限，保留审计行，按备份恢复对应相对路径；不要伪造 succeeded 输出。

只读巡检 SQL（阈值按当班规则调整；不得把查询结果直接用于批量更新）：

```sql
SELECT id, session_id, created_at,
       JSON_UNQUOTE(JSON_EXTRACT(interaction_json, '$.status')) AS interaction_status
FROM ark_design_image_messages
WHERE JSON_UNQUOTE(JSON_EXTRACT(interaction_json, '$.type')) = 'output_mode_confirmation'
  AND JSON_UNQUOTE(JSON_EXTRACT(interaction_json, '$.status')) = 'pending'
  AND created_at < UTC_TIMESTAMP() - INTERVAL 10 MINUTE
ORDER BY created_at;

SELECT owner_user_id, session_id, request_message_id,
       SUM(status = 'queued') AS queued_count,
       SUM(status = 'running') AS running_count,
       MIN(created_at) AS oldest_created_at,
       MIN(lease_expires_at) AS earliest_lease_expires_at
FROM ark_design_image_jobs
WHERE status IN ('queued', 'running')
GROUP BY owner_user_id, session_id, request_message_id
ORDER BY oldest_created_at;
```

#### 崩溃窗口 orphan 文件审计、隔离与删除

适用场景：worker 已完成原图/缩略图落盘，却在 DB finalize 前进程崩溃。`ark_design_image_assets` **没有** `thumbnail_path` 字段；引用集合必须取每条 `deleted_at IS NULL` 的 `storage_path`，再按代码规则把同目录同后缀的 `<stem>_thumb<suffix>` 加入集合。下面工具默认只扫描，且仅处理 mtime 已超过 24 小时的差集；先隔离到私有根内的具名批次，人工核验后才逐文件删除。它不跟随 symlink/junction/reparse point，也不调用递归删除。

在 `backend` 目录执行（输出必须用 `Tee-Object` 留作审计）：

```powershell
$env:DESIGN_IMAGE_ORPHAN_MIN_AGE_HOURS = "24"
# 以下命令都从 backend 目录执行；JSON 输出用 Tee-Object 留存。
python -m scripts.design_image_orphan_recovery scan --min-age-hours 24 | Tee-Object ..\design-image-orphan-scan.json

$env:DESIGN_IMAGE_ORPHAN_APPLY = "QUARANTINE"
python -m scripts.design_image_orphan_recovery quarantine --min-age-hours 24 | Tee-Object ..\design-image-orphan-quarantine.json

python -m scripts.design_image_orphan_recovery reconcile --batch "<精确 batch>" --reconcile-action quarantine | Tee-Object ..\design-image-orphan-reconcile.json
```

工具源码固定在 `backend/scripts/design_image_orphan_recovery.py`，不得复制到临时 heredoc 后修改执行。四个子命令为 `scan`、`quarantine`、`reconcile`、`purge`；`reconcile/purge` 必须用 `--batch` 指定工具生成的精确批次，`reconcile` 再用 `--reconcile-action quarantine|purge` 限定观察对象。兼容的环境变量只用于最低文件年龄和破坏性操作双确认，不用于拼接路径或传递数据库锁连接。
##### Purge 离线写冻结（强制前置）

`purge` 不是在线清理任务。必须安排维护窗口，并从头到尾禁止任何进程或人工操作创建、恢复、迁移 `ark_design_image_assets` 引用。环境变量 `DESIGN_IMAGE_ORPHAN_WRITE_FREEZE=OFFLINE_CONFIRMED` 是当班人的离线声明，不是锁；只要还有一个 API、Scheduler、worker、临时脚本、DB restore 或 migration 能写相关表，该声明就无效，禁止设置。

1. 列出所有可能承接 `/api/design-image` 的入口，包括办公室直连、云反代、展会/临时实例；在每个公网/反代入口先启用只针对 `/api/design-image` 的 maintenance 规则（返回 503），保留其他业务。清单必须写入当次审计记录，不能只测一个常用域名。
2. 停止 **每一台** 能访问同一 DB 或 `DESIGN_IMAGE_STORAGE_ROOT` 的方舟后端。先记录唯一维护人和 shell：`$MaintenanceOperator="$env:USERNAME@$(hostname)"; $MaintenanceShellPid=$PID`；其余人员和自动化在窗口内不得登录 DB 或启动程序。检查必须覆盖复制目录、临时 worktree 和手工启动进程，不能用仓库路径过滤。

   office-primary 是 Windows NSSM 服务 `CommissionSystem`。查询所有 Python/uvicorn/app.main 候选（无论命令行路径），并对清单中的**每个后端监听端口**核对 OwningProcess；默认业务端口是本机 8001，云 frp 入口 8002 也要在对应云主机核对。发现任何未知 PID/端口就停止并查明，不能仅停止 NSSM 后继续。

   ```powershell
   Stop-Service -Name CommissionSystem
   Get-Service -Name CommissionSystem | Select-Object Name, Status
   Get-CimInstance Win32_Process |
     Where-Object {
       $_.Name -match '^(python|pythonw|uvicorn)(\.exe)?$' -or
       $_.CommandLine -match 'uvicorn|app\.main(:app)?'
     } |
     Select-Object ProcessId, Name, CommandLine
   $BackendPorts = @(8001)  # 按入口清单加入该主机所有实际后端端口
   Get-NetTCPConnection -State Listen |
     Where-Object { $_.LocalPort -in $BackendPorts } |
     ForEach-Object {
       $_ | Select-Object LocalAddress,LocalPort,OwningProcess
       Get-Process -Id $_.OwningProcess | Select-Object Id,ProcessName,Path
     }
   # 期望：CommissionSystem=Stopped；候选进程逐一解释且无方舟 writer；后端端口无监听。
   ```

   北京云展会实例的真实 systemd 单元是仓库已记录的 `ark-backend`，必须同样停机；复制/临时目录不受 systemd 管理，所以继续用全局进程与监听查询兜底。

   ```bash
   sudo systemctl stop ark-backend
   sudo systemctl status ark-backend --no-pager       # 期望 inactive (dead)
   pgrep -af 'uvicorn|app\.main:app|python.*app\.main' || true
   BACKEND_PORTS='8001|8002'                          # 按本机真实入口补齐
   sudo ss -ltnp | grep -E ":(${BACKEND_PORTS})\\b" || true
   # 对该主机的每个入口执行：
   curl -sS -o /dev/null -w '%{http_code}\n' --connect-timeout 10 \
     http://127.0.0.1:8001/api/design-image/config || true
   # 期望：无 app 进程、无后端监听；入口为 503 或连接失败。
   ```

3. 对入口清单逐一请求并记录时间、URL、结果；维护反代只能是 503，办公室直连可为 503 或 connection refused，任何 2xx/401/403 都说明应用仍可达，不能继续。

   ```powershell
   $DesignImageEntrypoints = @(
     "https://<public-host>/api/design-image/config",
     "http://<office-primary>:8001/api/design-image/config"
   )
   foreach ($url in $DesignImageEntrypoints) {
     try {
       $response = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 10
       [pscustomobject]@{Url=$url; StatusCode=[int]$response.StatusCode; Detail='reachable'}
     } catch {
       $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'unreachable' }
       [pscustomobject]@{Url=$url; StatusCode=$status; Detail=$_.Exception.Message}
     }
   }
   ```

4. 在唯一维护 shell 中记录 DB claim 快照两次，间隔至少 `2 × DESIGN_IMAGE_WORKER_INTERVAL_SECONDS`（默认 20 秒）；`claim_count` 总和、job 数和起止时间不得变化，这组 DB 快照就是 worker claim 的可核验记录。同期检查所有实例的 service log，确认窗口内没有新的 `[design-image]` 活动或异常。仅“进程列表为空”不替代 DB 与日志静默证明。

   ```powershell
   mysql --login-path=ark-maintenance --database=<COMMISSION_DB_NAME> --batch --execute "SELECT COUNT(*) AS jobs, COALESCE(SUM(claim_count),0) AS claims, MAX(started_at) AS last_started_at, MAX(finished_at) AS last_finished_at FROM ark_design_image_jobs;"
   Start-Sleep -Seconds 20
   mysql --login-path=ark-maintenance --database=<COMMISSION_DB_NAME> --batch --execute "SELECT COUNT(*) AS jobs, COALESCE(SUM(claim_count),0) AS claims, MAX(started_at) AS last_started_at, MAX(finished_at) AS last_finished_at FROM ark_design_image_jobs;"
   # 两次输出的四项必须无变化。
   ```

5. 从此刻到 purge 完成审计前冻结所有手工 DB restore、Alembic migration、数据修复脚本和资产文件恢复。执行 purge 的 DB 账号必须具备目标表 `LOCK TABLES`、`SELECT` 以及只读查询 `performance_schema.metadata_locks/threads` 的权限；缺少任何权限都必须 fail closed，不能改成只依赖人工停写声明。脚本自身会从 SQLAlchemy engine 独占一个物理 MySQL 连接，执行 `LOCK TABLES ark_design_image_assets READ`，记录 `CONNECTION_ID()`，并在另一个普通连接验证恰好存在一条 `GRANTED / SHARED_READ_ONLY` 锁。外部 MySQL 终端只可用于旁路观察，不能代替、持有或续接这个锁。

   ```sql
   -- 可选旁路观察；barrier_connection_id 取自 purge plan/run journal。
   SELECT th.PROCESSLIST_ID, ml.OBJECT_SCHEMA, ml.OBJECT_NAME,
          ml.LOCK_TYPE, ml.LOCK_STATUS
   FROM performance_schema.metadata_locks AS ml
   JOIN performance_schema.threads AS th ON th.THREAD_ID = ml.OWNER_THREAD_ID
   WHERE th.PROCESSLIST_ID = <journal 中的 barrier_connection_id>
     AND ml.OBJECT_SCHEMA = DATABASE()
     AND ml.OBJECT_NAME = 'ark_design_image_assets';
   SHOW FULL PROCESSLIST;
   ```

   锁连接只查询已锁定的 `ark_design_image_assets`，不查询 performance_schema 或其他表；锁状态验证始终由另一个连接执行。锁连接不会交给 `SessionLocal`，也不会在仍持锁时归还连接池。正常退出会先显式 `UNLOCK TABLES`、执行存活探测，再关闭连接；异常路径同样显式解锁。若解锁、探测或关闭存在任何不确定性，脚本会使该物理连接失效而不是放回池，并以错误退出，服务必须保持离线。

6. 在同一维护 shell 对精确 batch 执行最新 `reconcile`，再执行一次 `scan` 并确认 `quarantine_inventory.manual_hold=false`；随后只设置 purge 确认值并运行 purge，不再提供外部 barrier connection ID：

   ```powershell
   python -m scripts.design_image_orphan_recovery reconcile --batch "<精确 batch>" --reconcile-action quarantine | Tee-Object ..\design-image-orphan-reconcile.json
   $env:DESIGN_IMAGE_ORPHAN_APPLY = "PURGE"
   $env:DESIGN_IMAGE_ORPHAN_WRITE_FREEZE = "OFFLINE_CONFIRMED"
   python -m scripts.design_image_orphan_recovery purge --batch "<精确 batch>" | Tee-Object ..\design-image-orphan-purge.json
   ```

脚本在读取旧计划和创建 purge journal 之前取得锁，并一直持有到目录处理、最终 reconcile 和 `run_returned` journal 全部完成。每个文件先完成路径边界、文件类型、大小、SHA-256、锁状态和 `intent` journal 的全部可能阻塞检查；随后在**持锁的同一连接**读取最新引用，只做必要的集合成员判断便立即 `unlink`。若路径恢复为引用，脚本只写 `blocked` 后中止，不删除文件。非 MySQL engine、锁缺失/不唯一、验证连接误用锁连接、权限不足或连接清理不确定均 fail closed。

执行顺序：

1. 先审阅 `design-image-orphan-scan.json`，逐项确认 DB 中没有相对路径、文件年龄超过门槛且不属于进行中的人工恢复。
2. 隔离：设置 `$env:DESIGN_IMAGE_ORPHAN_APPLY="QUARANTINE"`，直接执行 `python -m scripts.design_image_orphan_recovery quarantine --min-age-hours 24`。工具会在 `.orphan-quarantine/audit/` 先创建并 fsync JSONL plan，再对每个文件分别 fsync `intent/replace syscall_returned`；这只证明意图和系统调用已返回，**不证明 Windows 文件系统已持久化**。`Tee-Object` 只是摘要，不是审计真相源。记录返回的精确 `batch` 和 `journal`。
3. 至少观察一个完整 stale/备份周期；再次查询资产、核对页面与 worker 日志。执行 `python -m scripts.design_image_orphan_recovery reconcile --batch "<精确 batch>" --reconcile-action quarantine`。reconcile 会忽略 journal 曾记录的 syscall 返回状态，重新检查**全部 plan 项**的 source/隔离路径、大小和 SHA-256：source-only 且匹配=`not_moved`，target-only 且匹配=`moved`，both/neither/内容冲突=`conflict_manual_hold`。需要恢复时按 `source` 用 `Move-Item -LiteralPath` 精确移回，不能整目录覆盖。
4. 精确删除：设置 `$env:DESIGN_IMAGE_ORPHAN_APPLY="PURGE"` 与 `$env:DESIGN_IMAGE_ORPHAN_WRITE_FREEZE="OFFLINE_CONFIRMED"`，直接执行 `python -m scripts.design_image_orphan_recovery purge --batch "<精确 batch>" | Tee-Object ..\design-image-orphan-purge.json`。**唯一删除授权是该 batch 唯一 quarantine plan 的 items，不是目录扫描结果。**工具先验证 source/target 唯一、source 无穿越、target 精确等于 `.orphan-quarantine/<batch>/<source>`、size/sha256 合法；所有旧 purge plans 也必须是该授权集合的合法子集。目录遍历只检测额外文件/目录；任何未授权项、重复项、路径错配、越界 target 或内容不符都 manual hold。当前存在且匹配的授权 target 才能进入新 purge plan；缺失项必须由当前 quarantine reconcile 的 `not_moved` 或旧 purge reconcile 的 `deleted_according_to_plan_intent` 解释。之后在任何 `unlink` 前持久化完整计划，再逐项 fsync `intent/unlink syscall_returned`；journal 位于批次目录外，删除批次后仍保留。
5. purge 后及任何恢复/重跑前，执行 `python -m scripts.design_image_orphan_recovery reconcile --batch "<精确 batch>" --reconcile-action purge`。每次 purge 重跑还会在变更前自动核对全部旧 purge plans（包括已有 `syscall_returned` 的项），有冲突即停。若批次目录已被旧授权 purge 删除、但旧 journal 因崩溃缺少 `run_returned`，工具会在自身持有 DB 锁期间重新验证全部旧计划、当前文件系统与引用集合，另建明确的 recovery plan、`recovery_coverage` 和 `run_returned`，引用被覆盖的旧 journals；不会篡改或补写旧 journal。重复执行会识别已完成 recovery journal，不再制造第二份审计结论。

6. purge 正常退出表示脚本已在最终 reconcile 与 `run_returned` journal 完成后显式解锁并验证连接可用；退出报错、缺少 `run_returned`、清理不确定或连接失效都必须保持服务离线。随后审阅持久 journal、执行 purge reconcile，并再次 `scan`；只有 purge plan 全部为 `deleted_according_to_plan_intent`、无 conflict/manual hold、journal 无畸形/越权项时才可恢复服务。执行 `Remove-Item Env:DESIGN_IMAGE_ORPHAN_WRITE_FREEZE,Env:DESIGN_IMAGE_ORPHAN_APPLY -ErrorAction SilentlyContinue`，启动 Windows `CommissionSystem` 和确有部署的 Linux `ark-backend`，确认 `design_image_queue` 拓扑符合目标，再移除各入口 maintenance 规则；任一审计项未通过时保持服务离线。

Journal 判读和重跑规则：`intent` 与 `syscall_returned` 都只是操作线索，任何时候都以 reconcile 的当前磁盘观察为准。quarantine 中断后不要修改旧批次，先精确 reconcile；重跑只会为根目录仍存在的 orphan 创建新批次。purge 中断后用同一个精确 `--batch` 重跑；批次仍存在时，新 journal 只规划仍存在的文件，批次已消失时只能走上述显式 recovery plan，不会把旧 journal 伪装成正常返回。

每次 `scan` 都会输出 `quarantine_inventory`。隔离根下存在时间戳批次但 `.orphan-quarantine/audit/` 找不到对应 quarantine plan 时，状态为 `unjournaled_batches/manual_hold`；未知目录、异常 audit 文件同样 manual hold。quarantine 与 purge 都会拒绝继续，必须保留现场并人工核验，禁止为“解锁”而补造或删除 journal。`journal_without_batch` 也会报告，用于发现 journal 已建但批次目录尚未创建的中断；按 exact batch 执行 reconcile 后处理。

`DESIGN_IMAGE_ORPHAN_MIN_AGE_HOURS` 非整数或小于 24（含 0/负数）会在扫描前直接失败；不得绕过此门槛。不得扫描或删除 `DESIGN_IMAGE_STORAGE_ROOT` 之外的路径，不得使用 `Remove-Item -Recurse`、通配符或对存储根做递归删除。

### 回滚

最快止损是撤回试点角色的 `design_image:write` 或禁用 `design_image_generation` Preset；这两项只停止新的生成写入，不会隐藏只读页面。只有撤回 `design_image:read` 才会让前端菜单和入口隐藏。queued job 可经审计后标 failed；running 先停止新 claim、等待/使租约失效，迟到结果由 lease token 隔离。迁移不自动 downgrade，五张表与 `usage_detail` 保留；文件清理与数据库回滚分开，绝不递归删根目录。恢复前重新核对目标拓扑、ACL、Preset 和一条完整对账链。

## 客户拍摄素材门户上线与恢复

目标入口固定为 `https://media.leshine.cloud`。方舟仍是业务主系统，媒体域上的后端连接同一业务数据库，只由 Nginx 暴露 `/api/customer-media/`；静态门户发布到 `/var/www/ark-dist/customer-media/`（IP 兜底入口，ark-ip-ssl.conf default_server root 拼接）与 `/var/www/ark-static/customer-media/`（域名入口，两套目录内容保持一致），原件位于私有目录 `/data/customer-media`，不得通过 Nginx `root/alias` 直接暴露。首期仅支持上传、审核、发布、查看和下载，不提供图片编辑。

**IP 兜底入口（备案完成前可用，2026-08-14 实测）**：`.cloud` 域名 HTTPS 被机房未备案拦截（见上线门禁第 1 条），正式客户访问前可通过 `https://154.8.205.162/customer-media/` 使用门户——IP 入口走 `ark-ip-ssl.conf` 的 `default_server`（IP 自签证书），其通用 `location /api/ { proxy_pass http://127.0.0.1:8001 }` 已覆盖 `customer-media` 的 API 前缀，静态页 + 登录 + 素材接口全链可用（测试 `POST /api/customer-media/portal/login` 返回 401「邮箱或密码错误」、`GET /api/customer-media/portal/me` 返回 401「请先登录」即为后端正常响应）。两点限制：①IP 自签证书，浏览器会提示「不安全」，点继续访问即可，正式客户见不到此提示；②通用 `location /api/` 在 IP 入口是 5m body 限制，但 `/api/customer-media/` 已单独开 501m（见下条），素材上传/下载不受限。备案完成后回归 `.work` 正式域名 + 正式证书。

**上传链路 relay 与存储根（2026-08-14 修复「门户图片无法显示」）**：素材原件的唯一存放点是北京云 `/data/customer-media`（云端 `backend/.env` 已配 `CUSTOMER_MEDIA_STORAGE_ROOT=/data/customer-media`——修复前缺省值是 Windows 路径 `D:\WORKSOURCE\customer-media`，在 Linux 上被解析成后端工作目录下的相对目录，文件根本读不到）。为保证「上传落云、门户同机读取」，办公室入口（119.28.107.92 `leshine.conf`）把 `location ^~ /api/customer-media/` 整体反代到 `https://154.8.205.162`（自签证书故 `proxy_ssl_verify off`；501m body、`proxy_request_buffering off`、3600s 超时），北京侧 `ark-ip-ssl.conf` 为同前缀单独开 501m；内部上传/审核/预览与门户读取由此全部落到北京云 8001 一个后端。两台机的 nginx 备份在各自 home 目录 `*.bak-20260814`。排障口诀：门户图裂先看北京云 `storage_for('local').root` 是否为 `/data/customer-media`，再看 `location` 是否命中 relay（北京 access.log 里来源 IP 应是 119.28.107.92）。

### 上线门禁

1. DNS `media.leshine.cloud` 指向目标服务器，80/443 可达且 ICP/HTTPS 阻断已解除；证书签发后先用 `curl -I https://media.leshine.cloud/` 验证。当前已知现状（2026-08-13）：`leshine.cloud` 解析到 `154.8.205.162`，HTTP 会跳 HTTPS，但 HTTPS 连接被重置——**`.cloud` 后缀统一未备案，机房在出口按域名特征重置 TLS（连 `media.leshine.cloud` 同命，2026-08-13 独立验证：本机 `curl -skI https://media.leshine.cloud` 200、外部网络 TLS 握手 RST）**，因此在备案完成前不得宣称门户已上线；备案与 `.work` 正式域名落地前用上节 IP 兜底入口。
2. 备份数据库。确认 `alembic heads` 只有一个 head，审阅 `114_customer_media_portal` 的 MySQL 离线 SQL，再执行 `alembic upgrade head`。迁移只允许在一个实例执行。
3. 云端 `.env` 至少配置：

   ```env
   APP_ENV=production
   COOKIE_SECURE=true
   SCHEDULER_ENABLED=false
   CORS_ALLOW_ORIGINS=https://leshine.work
   CUSTOMER_MEDIA_STORAGE_ROOT=/data/customer-media
   CUSTOMER_MEDIA_PORTAL_ORIGIN=https://media.leshine.cloud
   CUSTOMER_MEDIA_SIGN_SECRET=<独立随机长串>
   CUSTOMER_MEDIA_MAX_FILE_MB=500
   CUSTOMER_MEDIA_MAX_BATCH_GB=20
   CUSTOMER_MEDIA_SESSION_DAYS=30
   CUSTOMER_MEDIA_COOKIE_NAME=leshine_media_session
   ```

   方舟前端构建时配置 `VITE_CUSTOMER_MEDIA_API_BASE=https://media.leshine.cloud/api/customer-media`，让大文件直接到云端，不经办公室主站转发。云端必须连接与方舟一致的数据库；不得启动第二套 Scheduler。首期门户登录限速是进程内滑动窗口，因此云端后端固定单 worker；扩容多 worker 前先迁移到 Redis 等共享限速器。
4. 创建私有存储根并只授予方舟服务账号读写权限；以服务账号完成“写入临时文件 → fsync → 原子替换 → 删除”测试。确认磁盘容量、备份和低水位告警后再开放上传。
5. 将 `frontend/public/customer-media/` 中内容发布到 `/srv/ark-customer-media/`，安装并启用 [Nginx 模板](../deploy/nginx/customer-media.leshine.cloud.conf)，执行 `nginx -t` 后 reload。启动云端后端后，浏览器从方舟完成一次图片、视频上传，从发起人账号批准发布，再用客户账号验证只能看到本 `customer_id` 已发布批次并可下载。
6. 权限最小化：设计师角色授予 `customer_media:write`，预约发起人授予 `customer_media:read`，仅管理员授予 `customer_media:admin`。重启后权限 seed 会让已有 `commission:self_read` 业务角色首次继承 `customer_media_portal:read` 页面入口；只有 `commission_my:read` 的财务等角色不会继承。抽查一个业务账号只看到当前 OKKI 归属客户。主管若需全量查看，必须显式授予 `customer_media_portal:read_all`（或重新套用主管模板），该数据范围不会自动扩大。门户账号一客户仅一条，登录邮箱全局唯一；改邮箱、改密码、停用账号都会使旧会话失效。

### 运维与回滚

- 下架单批素材使用方舟管理员“下架”，不删数据库记录或原件。误发布先下架，再查 `ark_customer_media_reviews` 审计链。
- 文件上传失败会删除临时/新原件；数据库提交成功后物理删除失败形成孤儿文件，需按 `object_key` 与数据库差集逐文件审计，禁止递归删除存储根。
- 应用回滚时保留 114 迁移和六张业务表；先撤回三个权限并在 Nginx 对上传接口返回 503。静态站可继续只读，若数据库版本不兼容则整个门户进入维护页。
- 迁移 COS 时保持数据库 `storage_provider/object_key` 契约：复制并校验 SHA-256，按批切换 provider，验证下载后再逐对象清理本地文件；不能直接改 Nginx 路径代替迁移。

## DSH Agent Runtime 灰度与回滚（迁移 118）

### 上线前置

1. 备份数据库，确认 `alembic heads` 只有 `118_agent_runtime`，再由唯一实例执行 `alembic upgrade head`。
2. 在方舟 AI 管理中确认 `agent_runtime_copilot`、`agent_runtime_repurchase`、`agent_runtime_sales_shadow` 均绑定启用的 `direct/openai` Provider；模型真实 API Key 只保存在方舟。
3. 从官方固定 tag `dsh-v0.1.0-rc.8`（commit `141eb6fef83422698aef7a981029e843e8161534`）构建并审查 SDK/runtime wheels。PyPI 的 rc7 Runtime 不含 MCP Client，不得用于方舟；rc8 Release 暂无 wheel。运行仓库 `DSH rc8 manylinux candidate` GitHub Actions：它以 digest 固定 manylinux/Rocky 基线并锁定全部构建依赖；对上游会重新解析 registry 的 legacy deploy，只允许应用 SHA-256 固定、写入 provenance 的 `dsh-rc8-lockfile-deploy.patch` 后离线完成闭包，禁止直接开放 deploy 网络。流水线按“非特权构建并封存 → 独立 glibc 2.28 只读 smoke → 新 Job 复验和 OIDC attestation”执行。下载完整 candidate 后，用预期源码 SHA 运行 `verify_dsh_release.py`，再用 `gh attestation verify --repo BE-MX/commission-system` 核对 signer workflow、受保护 `main` ref 和同一 source SHA；只有来自 `main` 的 attested candidate 才能整包进入内部制品库。功能分支 candidate、第一段 untrusted artifact、单独 wheel、缺验证报告或仅 SHA 自洽的 bundle 均不得部署。不得改用浮动 master；无 CI 时构建只能做诊断，不能绕过 GitHub OIDC 晋级生产。
4. 创建 Linux 低权限用户与 `/var/lib/leshine-ark-dsh/sessions`（0700），按 `services/dsh-agent-worker/.env.example` 配置 `/etc/leshine/ark-dsh-worker.env`（0600），安装 `deploy/systemd/leshine-ark-dsh-worker.service`。
5. 为 Worker 生成独立随机 token；明文只放 Worker，方舟 `AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON` 只放 SHA-256；并用 `AGENT_RUNTIME_WORKER_RUNTIMES_JSON={"dsh-worker-01":["dsh"]}` 将机器凭证绑定到 Runtime。另配至少 32 字符的独立 `AGENT_RUNTIME_RUN_TOKEN_SECRET`。
6. 给内部试点角色最小权限：任务页面 `agent_runtime:read/write`，执行 `agent_runtime:invoke`，再叠加场景所需 `customer_radar:read`、`order_intelligence:read` 或 `sales_automation:read`。`read_all/admin` 不授普通业务员。

### 开关顺序

所有开关初始保持 false。先开控制面和 Runtime，再逐场景灰度；每一步重启后端并验证 `/api/agent-runtime/config`：

```env
AGENT_RUNTIME_ENABLED=true
AGENT_RUNTIME_DSH_ENABLED=true
AGENT_RUNTIME_COPILOT_ENABLED=true
AGENT_RUNTIME_REPURCHASE_ENABLED=false
AGENT_RUNTIME_WEB_SEARCH_ENABLED=false
AGENT_RUNTIME_SALES_SHADOW_ENABLED=false
AGENT_RUNTIME_SHADOW_SAMPLE_RATE=0
```

先用内部账号完成客户副驾驶标准问题：任务领取、事件连续、取消、Artifact 保持 draft、接受/拒绝与日志脱敏均正确。管理员从任务中心的“执行标准评测”进入版本化 30 题目录：

1. 给评测账号授予 `agent_runtime:admin/invoke`、`customer_radar:read` 和 `order_intelligence:read`；非 `manage/read_all`账号仍只能选本人负责客户/订单。评测题已限定在现有工具可证明的画像、订单摘要、复购周期和行动范围；未提供运单号或完整产品参数时，不把物流/价格问题纳入正式 30 题。
2. 每题选择一个确实具备页面所列数据的真实内部客户，二次确认后启动。后端会按题目预检权限、画像事件/行动、OKKI 绑定、近三年有效订单和可计算复购周期；预检失败的 Run 不会创建。不得为凑数使用伪造客户。
3. Run 终态后进入详情核对证据、数量和建议，必须提交 `useful/not_useful/corrected` 人工反馈。“执行完成”不等于“可直接使用”。
4. 30 个 Run 由服务端自动冻结 `evaluation_suite=customer_order_copilot_v1`、互不重复的 `evaluation_case_id`、客户边界与 `evaluation_contract_hash`。契约 hash 包含完整 30 题及评分规则、Profile 版本与实际 Prompt、工具/Schema/限额/策略、Preset 模型与参数、Provider 非密钥运行参数及全局硬限额；任一变化会自动进入新的空 cohort，不与旧样本混算。普通问答、非目录题、同题重跑都不会虚增样本；门槛固定取当前 cohort 每题第一个完成结果，避免事后挑选。

之后再开复购，抽查规则召回与已处理行动不被覆盖。最后配置 Brave Key，开启受控 Web Search 与 5% Shadow 抽样；Shadow 对照按不同 `search_job` 计数，达到 50 个同输入样本前不得提高流量，更不得替代 OpenClaw 正式链路。管理员定期读取 `GET /api/agent-runtime/evaluations/readiness`；只有返回 `business_validation_complete=true` 才进入人工晋级评审，该接口本身不会自动切流。

### 观测与止损

```bash
systemctl status leshine-ark-dsh-worker --no-pager
journalctl -u leshine-ark-dsh-worker -n 200 --no-pager
```

任务中心重点检查 `queued` 堆积、`ambiguous`、租约过期、步骤/Token/成本和 Artifact 证据。紧急止损按以下顺序执行：

1. 关闭对应 Profile flag，阻止新任务；复购开关关闭后调度任务不再注册，Shadow 开关关闭后 SearchJob 不再抽样。
2. 关闭 `AGENT_RUNTIME_DSH_ENABLED`，Worker 无法领取新任务；需要完全冻结时再关闭 `AGENT_RUNTIME_ENABLED`。
3. 停止 Worker。正在执行且失联的任务等待租约到期进入 `ambiguous`，人工核查，不直接重跑。
4. 保留迁移 118、Run/Event/Artifact 与客户行动来源字段。代码回滚只回应用和前端；除非已完成数据导出与影响审计，不执行 118 downgrade。

恢复时先修复根因并轮换 Worker token/Run secret（若疑似泄露），再按上线顺序逐层开启。标准化事件与用户反馈保留；方舟可选原始事件密文与 Worker 本地 `session.jsonl` 默认保留 90 天，Worker 每日只清理根目录下过期的常规 Session 日志，不跟随符号链接。
