# 38色现货选色工具

公开静态站点：`https://color-guide.leshine.cloud/`，北京 `ubuntu@154.8.205.162`，根目录 `/var/www/ark-static/color-guide`。素材来自用户提供的 `LeShine_38色选色站点_完整源码素材_v11_2026-10-27.zip` 的 `dist/`；保留原网站内容、38 色与 76 张使用中的图片。不发布压缩包内说明、检查脚本或 `.openai` 配置。

方舟导航唯一来源 `frontend/src/config/navigation.js`：库存色块图 → **38色现货选色工具**，复用外链组件的新标签页行为，权限沿用该分组任一既有 `colorwork_*:read` 权限。站点本身公开可访问，不承载库存数据库或方舟 API。

## 静态站专项

安全解包到 `.deploy_state/color-guide/source/dist`。计划 JSON 的 `source` 是该目录绝对路径，`files` 是 `static_sync.manifest(source)` 返回的完整路径/SHA256 字典，`archive_sha256` 保存原 ZIP 摘要。源码与计划改变必须重新检查。

```powershell
deploy\deploy.bat --color-guide-site .deploy_state/color-guide/input.json --prepare-only
deploy\deploy.bat --color-guide-site .deploy_state/color-guide/input.json
```

预检固定域名 DNS、已有 Nginx 归属和配置摘要，复用既有 SHA256 增量静态发布。首次正式发布通过既有 Certbot 账户签发该子域名单独证书，写独立 Nginx 配置，语法检查成功后 reload。HTTP 跳转 HTTPS，未知路径、隐藏文件与 `/api/` 返回 404。正式成功须校验 HTTPS 首页摘要与隔离路径。续期沿用服务器 Certbot 调度及共享 `ark-reload-nginx` hook，不覆盖已有 hook。

本地回执在 `.deploy_state/color-guide/site-current.json`；远端配置、备份及中断记录在 `.deploy_state/color-guide-site/`，静态版本在 `/var/www/ark-static/.color-guide-releases/`。证书请求失败或结果不明保留 `certificate-pending.json`，先只读确认真实签发结果，不自动再次申请。配置与静态版本切换失败使用受管备份；发现漂移或 pending 时停止，保留现场供恢复。

## 方舟导航专项

本次限定北京方舟；候选从线上后端和前端共同版本构建，只有导航源、生成权限清单及本次部署支持/文档允许变化。源码固定为干净的本地提交，无需 Git 远端 push。先 `npm ci --prefix frontend`、`npm run build --prefix frontend`，构建会生成对应的权限清单。计划保存 `baseline`（完整线上 SHA）。

```powershell
deploy\deploy.bat --color-guide-navigation .deploy_state/color-guide/navigation-plan.json --prepare-only
deploy\deploy.bat --color-guide-navigation .deploy_state/color-guide/navigation-plan.json
```

预备固定候选、完整静态摘要和权限清单，正式切换拒绝制品或源码漂移。通过 Git bundle 传输候选，不推送远端分支；在现有后端/静态发布锁内检查原版本、切换干净候选、更新静态指针。保留旧 Git 版本和静态恢复引用，不执行数据库迁移、不重启 API，不更改办公室和新加坡部署。普通后续发布仍可按正常入口检查干净生产检出目录。

远端 `.deploy_state/color-guide-navigation/` 保存检查点、备份与成功结果，本地对应 `.deploy_state/color-guide/navigation/`。如果中断导致结果不明，先核对 Git HEAD、两份导航文件摘要、静态 current 指针、pending 和 HTTP 内容，不能删除记录后盲目重发。正式发布范围与验证结果记录于 `docs/handoff.md`。
