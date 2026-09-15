# 方舟库存色块图工作台

库存图直接下载、实时库存图修改、原始库存图文件三个页面通过方舟菜单使用。
浏览器页面、静态资源、接口与下载全部位于主站的 `/api/colorwork/workbench/`，**不使用独立域名**。
现有 React/vinext 界面和图像处理逻辑保留；workerd 仅作为方舟内部运行服务监听 `127.0.0.1:8787`。

## 接入与权限

```
方舟三个菜单 → GET /api/colorwork/sso?view=library|inventory|master（两个公网入口均路由北京）
             → 同源 iframe /api/colorwork/workbench/api/auth/ark
             → 方舟后端流式转发 → 内部 workerd
```

方舟按 `colorwork_download:read`、`colorwork_edit:read`、`colorwork_master:read` 签发 120 秒 SSO。
内部会话 HttpOnly、SameSite=Lax，Cookie Path 固定 `/api/colorwork/workbench`（含无尾斜杠根页），有效期 12 小时。
后端不转发方舟 Bearer token 或其他 Cookie。业务 API 保持逐视图鉴权，master 视图映射站内管理员。
局域网入口由办公室后端代理到北京：只有 `/sso` 向北京方舟 API 转发已验证的用户 Bearer；
后续 iframe/API/文件只转模块 Cookie。办公室校验浏览器 Origin 后再转换为北京 Origin。
返回 Cookie 保留 HttpOnly、SameSite=Lax 和模块 Path；Secure 依据浏览器入口的 HTTP/HTTPS 设置，
避免北京 HTTPS 的 Secure Cookie 在局域网 HTTP 上失效。SSO 链接与重定向均保持局域网同源。

`next.config.ts` 的 basePath 与 `lib/workbench-url.ts` 对齐；生成目录和已存储源文件 URL 保持原有相对路径，
仅在浏览器请求、图像加载和下载时补前缀，不迁移或重写已有业务数据。

实时库存仍回源方舟 `/api/colorwork/inventory-status`；23 套模板按 okki 库存口径计算，未改业务规则。

## 库存图直接下载

工作台不再渲染内置顶栏、账号/页面路径栏或移动端底部导航，三个视图通过方舟主站菜单进入。

下载页只列出「库存图JPG」，不再显示业务修改成品列表；历史成品文件继续保留。
每个产品 / Radio 提供「下载原始库存图JPG」和「下载实时库存图JPG」。后者打开模态预览，
复用 `InventoryBoard` 的 LIVE PREVIEW、30 秒刷新及仅下载流程，不创建历史成品。
原图缩略图预览与原图批量 ZIP 下载保留；弹窗支持关闭按钮、Escape 和焦点返回。

只有 library 权限的账号通过 `/api/templates/:id/inventory` 读取共享快照，
通过 `/api/templates/:id/inventory/validate` 在绘图前后校验源版本、母版、库存修订及规格。
这两个入口复用现有快照与校验服务；库存 PATCH 和成品写入仍要求 inventory 权限。
回归运行 `node --test scripts/qa-library-live-download.mjs`。

## 部署

统一入口仍是 `deploy/deploy.bat`。北京后端 prepare/activate 自动调用 `deploy/colorwork_release.py`：

- 准备：下载并校验固定 Node v22.23.2 Linux x64（官方 SHA-256 固定在部署代码），使用 pnpm 10.33.2 和锁文件构建；
  自动根据本机后端 Settings 生成 gitignored、0600 的 `.dev.vars`；迁移只应用到隔离 validation 目录。
- 激活：复核最新迁移历史，停止 `ark-colorwork`，完整备份 D1/R2，再迁移持久目录并启动纳管 unit；
  DB/R2 readiness 通过才记成功。服务由部署入口管理，不需要手工新建域名、证书或 Nginx location。
- 同候选重跑复核构建摘要、不重写在用配置；同成功候选激活仅做健康核验。失败记录阻断普通重试。

运行数据唯一归属北京：`/home/ubuntu/commission-system/.deploy_state/colorwork/data`，
包含 D1、R2 元数据与 blobs，必须整体纳入备份，**不可作为普通构建缓存清理**。
`backups/<revision>-<attempt>` 保留发布前数据；`current.json` 保留失败阶段，`success.json` 记录已应用迁移 checksum。
发现旧 `/var/lib/colorwork-workbench/state` 或旧工作目录 `.wrangler/state` 的数据时阻止新建空库，先明确迁移归属。

恢复先停止 `ark-colorwork`、保留失败现场及数据，核对本轮 unit/备份/迁移记录；向前修复候选并检查现存 schema。
只有核验原始基线与数据兼容性后才能人工恢复记录状态，不能删除日志或拿旧备份覆盖发布后新增业务数据。
该模块失败不会自动降级数据库，也不把恢复旧主站代码当作工作台恢复。

配置项：`COLORWORK_GATEWAY_ORIGIN` 在 Windows 默认 `https://leshine.cloud`，在 Linux 默认空。
非空时，SSO 和工作台请求均由服务器代理北京，不使用本机 8787；显式置空后使用本地工作台（Windows 隔离开发时可用）。
`COLORWORK_INTERNAL_ORIGIN` 仅在本地模式使用，北京默认 `http://127.0.0.1:8787`；
SSO 可显式配置 `COLORWORK_SSO_SECRET`，否则从 JWT_SECRET_KEY 按 SSO 用途派生；回源密钥可显式配置 COLORWORK_SYNC_KEY，
否则以用途隔离的 HMAC 派生。部署自动同步至内部服务，不向浏览器或构建日志公开。
内部模块只在北京运行；`.work` 的整个 `/api/colorwork/` 前缀由新加坡代理北京，SSO 签发也在北京完成，
无需办公室另设工作台 SSO 密钥或数据副本。两后端须能验证同一主站 Bearer，沿用现有跨实例认证约定。
办公室 8787 是 WhatsApp Connector，不能直接用作工作台；局域网直连入口由上述 Windows 网关模式接入。
两站路由的准备、激活和恢复见 `deploy/README.md`。

首次业务使用仍需在「原始库存图文件」导入 87 个工作台素材与 23 组 JPG/PSD。代码仓库只含目录清单，不含真实素材。
未导入时普通用户看到明确的首次设置状态，不把空库当成可生成成品的完整上线。

## 本地验证

```
pnpm install --frozen-lockfile
pnpm lint
pnpm build
node --test scripts/qa-workbench-url.mjs
```

本地用独立测试 `.dev.vars` 和 `--persist-to .wrangler/<test-name>` 运行 wrangler，不连接生产 D1/R2。
方舟开发服务器已有 `/api` 代理，因此无需新增前端代理；后端开发配置把 COLORWORK_INTERNAL_ORIGIN 指向测试服务即可。
浏览器经方舟 `/api/colorwork/workbench/` 访问。后端回归见 `backend/tests/test_colorwork*.py`，发布回归见 `deploy/tests/test_colorwork_release.py`。
