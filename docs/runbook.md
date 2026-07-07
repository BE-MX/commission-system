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

# 素材存储（可选，2026-07-03 起走 Settings 统一管理，默认值即当前生产值）
ASSET_STORAGE_ROOT=D:\WORKSOURCE
ASSET_SIGN_SECRET=<签名密钥>
ASSET_UPLOAD_STAGING=D:\upload_staging
XPOZ_TARGET_ACCOUNTS=<逗号分隔账号，色彩趋势采集用>

# 调度器
SCHEDULER_ENABLED=true
```

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
        proxy_pass http://127.0.0.1:8888;  # SSH 隧道端口
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

### 8. 配置 SSH 隧道（本地 → 云端）

在本地 Windows Server 运行（保持前台）：

```bash
ssh -N -R 8888:localhost:8002 root@119.28.107.92
```

或配置成 NSSM 服务（推荐）：

```bash
nssm install SSHTunnel "C:\Windows\System32\OpenSSH\ssh.exe"
nssm set SSHTunnel AppParameters "-N -R 8888:localhost:8002 root@119.28.107.92"
nssm start SSHTunnel
```

## 日常更新

运行 `deploy\deploy.bat`，自动执行：

1. `git pull` 拉取最新代码
2. `pip install -r requirements.txt` 更新后端依赖
3. `npm install` 更新 Connector 依赖
4. `alembic upgrade head` 数据库迁移
5. `npm run build` 构建前端
6. `scp dist/* → root@119.28.107.92:/var/www/ark/dist/` 同步静态文件到云端
7. `nssm restart CommissionSystem` + `nssm restart WhatsAppConnector` 重启双服务

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
3. 检查 SSH 隧道：`ssh root@119.28.107.92 "netstat -tlnp | grep 8888"`
4. 重新同步：`deploy\deploy.bat`

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

1. **不出分析/话术**：按 Q6 排查 `expo_face_analysis` / `expo_sales_strategy` 两个 preset；话术生成失败会自动回落话术卡库原文（销售面板仍有内容），展台不冷场
2. **不出效果图**（2026-07-07 起生图已接入 ELBNT `/v1/images/edits`）：失败原因看 `ark_expo_sessions.error_message` 或 AI 调用日志（`ark_ai_call_logs`，preset=expo_wig_composite）。常见：上游拥堵 502/504（单图 >300s 被 ELBNT 网关掐断，等低峰重试或换 Provider）；卡在"生成中"超 7 分钟会被看门狗自动标失败并给出重试入口
3. **提示权限不足**：确认账号有 `expo:write`；若右上角显示占位"用户"，硬刷新（Ctrl+F5）重新拉取登录态
4. 客户照片与效果图存 `uploads/expo/`（photos/results/wigs/hair_colors 四个子目录），属 `/uploads` 备份范围；客户数据删除走线索台「删除」（物理删除照片）；发型/色板图上传不限体积（送模型前管线自动压缩）

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
