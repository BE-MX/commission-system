# 库存色块图调整台（colorwork-workbench）

库存色块图工作台：调用加程维护的标准母版，标记暂时缺货/正在补货，并生成给客户使用的库存提示 JPG。
2026-09-14 起作为**方舟平台子站点**运行：UI 与业务逻辑保持原样，账号体系移除，入口与三个页面的访问权限由方舟 RBAC 控制。

技术栈：vinext（Next.js 兼容层）+ React 19 + Cloudflare Workers 运行时（workerd）+ D1(SQLite) + R2（本地模拟层）。

## 与方舟平台的集成

```
浏览器 ──► 方舟前端「库存色块图」菜单（3 个页面，各自权限码）
              │  GET /api/colorwork/sso?view=library|inventory|master（需对应页面权限）
              ▼  返回短命 SSO 链接（HS256，120s，claims: sub/name/views）
         iframe ──► 工作台 /api/auth/ark?token=…&view=…
              │  验签 → 自动开通站内账号 → 会话 Cookie（含视图清单）→ 302 /?view=…
              ▼
         工作台三个视图（导航按 views 过滤，API 逐视图 requireView 校验）
              │  「实时库存图修改」快照返回前，服务端回源方舟：
              │  GET {ARK_STATUS_ENDPOINT}?template_id=…  (头 x-colorwork-sync-key)
              ▼  方舟按 lsordertest.okki_inventory.enable_count 实时计算 到货正常/正在补货
         规格状态被 okki 数据覆盖后返回；页面每 30s 静默轮询自动生效
```

### 页面 ↔ 权限码 ↔ 工作台视图

| 方舟菜单 | 权限码 | 工作台视图 | 说明 |
|---|---|---|---|
| 库存图直接下载 | `colorwork_download:read` | `library` | 业务成品图与原始 JPG 下载 |
| 实时库存图修改 | `colorwork_edit:read` | `inventory` | 库存状态维护/导出 JPG（状态以 okki 实时数据为准） |
| 原始库存图文件 | `colorwork_master:read` | `master` | 母版/源文件版本管理 + 首次素材导入（站内 admin） |

权限在方舟「系统管理 → 角色权限」按角色分配；`super_admin` 自动拥有全部三个页面。
工作台内不再维护账号：用户经 SSO 进入时按方舟用户 id 自动开通站内账号（`ark-<id>@ark.local`），
持有 master 视图即站内 admin。审计字段（updatedBy 等）显示方舟显示名。SSO 会话 12 小时有效
（权限撤销最迟次日生效）；未命中的 okki 规格保留站内手动状态作为兜底。

### 环境变量

工作台侧（`.dev.vars`，参考 `.dev.vars.example`；gitignored）：

| 变量 | 说明 |
|---|---|
| `ARK_SSO_SECRET` | SSO 验签密钥，与方舟后端 `COLORWORK_SSO_SECRET` 一致 |
| `ARK_STATUS_ENDPOINT` | 方舟库存状态接口地址，如 `https://<方舟后端>/api/colorwork/inventory-status`；留空则不做 okki 覆盖 |
| `ARK_SYNC_KEY` | 回源共享密钥，与方舟后端 `COLORWORK_SYNC_KEY` 一致 |

方舟后端侧（`backend/.env`）：`COLORWORK_SSO_SECRET` / `COLORWORK_BASE_URL`（工作台外部地址）/
`COLORWORK_SYNC_KEY`，详见 `backend/.env.example`。

## 本地开发

```bash
pnpm install
cp .dev.vars.example .dev.vars   # 填入与方舟后端一致的密钥
pnpm db:local                    # 应用 D1 迁移（含 0008 会话视图列）
pnpm dev --port 8787             # 开发服务器
```

直开 http://localhost:8787 只会看到「请从方舟平台进入」——正常。联调时用方舟后端
`GET /api/colorwork/sso?view=…` 拿链接进入（方舟前端 dev 代理把 `/api` 转给本地后端）。

## 生产部署（办公室服务器，systemd + nginx）

```bash
# 代码就位后（以 /opt/commission-system/colorwork-workbench 为例）
pnpm install --frozen-lockfile
cp .dev.vars.example /etc/ark-colorwork/.dev.vars  # 建议放 /etc 并软链或拷入项目根（gitignored）
pnpm build
# 首次：在生产 state 目录应用 D1 迁移
npx wrangler d1 migrations apply site-creator-d1 --local --config wrangler.prod.jsonc \
  --persist-to /var/lib/colorwork-workbench/state
# systemd / nginx
sudo install -m 644 ../deploy/systemd/colorwork-workbench.service /etc/systemd/system/
sudo systemctl enable --now colorwork-workbench
# nginx 站点：deploy/nginx/colorwork.leshine.work.conf（DNS/证书就绪后启用，先 nginx -t）
```

- 数据持久化：D1 与 R2 都落在 `--persist-to` 目录（systemd 单元用 `/var/lib/colorwork-workbench/state`），
  **该目录需纳入备份**（库存状态、历史成品、源文件全在里面）。
- 首次使用：管理员从方舟「原始库存图文件」页进入，用页内导入器上传首次素材包
  （23 套母版 PSD/JPG + 色块图素材），完成后三个页面对业务开放。
- 反向代理：工作台必须经 HTTPS 子域名访问（iframe Cookie 需要 Secure + 与主站同站）。

## 测试

```bash
pnpm lint                 # oxlint（含 TS 类型规则）
pnpm build                # 产物构建
pnpm qa:admin-guards      # 需先启动本地服务（见脚本头部注释）
```
