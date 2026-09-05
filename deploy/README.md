# 统一部署入口（COS 文件迁移暂缓）

`deploy.bat` 默认在办公室已安装 NSSM 服务的仓库运行。先在候选 worktree 准备源码、依赖、主站和 PM 制品，再切换办公室服务、北京后端和已登记的云静态站。完整目标清单见 `platforms.json`；未纳管服务和未开通域名会明确列出，不计作已更新。

```powershell
deploy\deploy.bat                           # 跟踪分支的最新提交；办公室服务 + 已登记云目标
deploy\deploy.bat --no-pull                 # 使用当前已提交、审查的 HEAD
deploy\deploy.bat --cloud-only --no-pull    # 明确只处理云端，不代表办公室已更新
deploy\deploy.bat --cloud-only --no-pull --prepare-only # 准备并校验，暂不切换
```

## 目录与版本规则

- 仓库必须干净；候选源码、构建缓存、依赖、传输包、状态只在 `.deploy_state/`。
- Git 只传缺失对象到北京 `repo.git` 的独立 `deploy/<SHA>` 引用；不会 push origin/main。
- 默认 fetch 后只接收可快进的新提交；本地已审查提交领先远端时保留本地 HEAD，分叉时停止发布。无需为了部署先推送 main。
- 本地源码以内容及 Node 版本计算构建指纹；相同输入复用同一制品。扩展包缓存也复用，避免仅因打包时间变化导致全站重建。
- 每个云目标一次计算 SHA-256 清单，变化文件打成一个包传输。未变文件零传输，不按单文件重复建立 SSH。
- 制品全部校验后才切换。首次发布用 Linux `renameat2` 原子地将原 Nginx 根目录换成受管符号链接；Nginx 原配置与别名仍指向相同路径。
- `assets/` 中历史文件追加保留；同名不同内容阻断，防止破坏仍打开的页面。当前不自动清理历史版本。
- 切换后通过本机 HTTPS、真实域名和证书验证 Nginx 返回的 index.html 摘要；失败恢复旧指针。
- 后端依赖在候选环境中安装；启动失败且 schema 未变化时回退代码/环境。数据库变更后失败保持停止，不能自动将旧代码接回新 schema。

## 数据库

办公室与北京共享 `commission_db`，每次发布都读数据库 revision，并检查发布代码的唯一 head 和迁移链。数据库已到目标则跳过 DDL；未知 revision、数据库领先、分叉均阻断。不会复制、覆盖或 downgrade 数据库。

有待执行迁移时，必须先核实 `platforms.json` 中所有 writer 的归属，登记 `migration_writers` 并将 `migration_writers_verified` 设为 true。当前办公室远程管理和独立任务清单尚未核实，因此保持 false；这次已知数据库 137，无需执行 DDL。

迁移使用独立 DBA 身份：通过 `--migration-credentials` 指定一个受保护文件，只含 `COMMISSION_DB_USER` 和 `COMMISSION_DB_PASSWORD` 两项。库地址和库名沿用已校验运行配置；停机前检查 DBA 权限。凭据只进入受控迁移子进程，禁止替换运行服务 `.env`，禁止把文件提交 Git。

迁移子进程先取得 MySQL 命名锁，再停登记 writer，只运行一次 Alembic upgrade，随后核对唯一 head。两个后端激活成功后恢复其他 writer。DDL 失败不自动恢复旧程序，需先检查 MySQL 实际结构。

## 状态与恢复

优先读取 `.deploy_state/publish-current.json`：本轮 revision、阶段、已成功目标。`publish-success.json` 仅代表最近一次成功，不表示当前运行成功。跨机器发布不是分布式事务：后面的目标失败时，前面已验证的目标可能已更新，脚本返回非零并保留阶段记录。

旧 `rollback.bat` 已阻断，不能再消费旧 `dist_backup` 并 SCP 覆盖受管版本。失败激活在 schema 不变时有自动回退。已完成发布的人工回退必须先核对候选旧代码是否认识当前 schema，再按受管后端与静态发布流程执行；不得直接覆盖 `current` 下文件或降级数据库。

## 验证

```powershell
python -m compileall -q deploy
python -m unittest discover -s deploy/tests -v
```

静态文件语义测试必须在 Linux 临时目录执行（包含原子目录交换和符号链接），不连接生产数据库、不修改站点根目录。Windows 会明确跳过该组；源码准备及数据库阻断测试在 Windows 执行。部署后再运行同一命令验证无变化构建/文件传输被跳过。

## 当前边界

- COS 文件迁移暂缓，办公室文件和北京 `/data/customer-media` 保持原位置。
- `pm.leshine.cloud` 尚缺 DNS/TLS，已列为 pending；不得未开通就显示成功。
- hair/video 权威源码仍在本仓库之外；独立 MCP、同步器、中继、OpenClaw、n8n 和终端安装分别列出，不盲目升级 latest。
- 办公室服务器实际远程更新、内网 DNS 和办公室直连北京隧道，需要可用的办公室管理入口才能完成。
- `--cloud-only` 若发现新加坡前端有变化，会等待对应办公室后端发布并列为 deferred；不提前上线依赖旧 API 的新页面。完全一致的页面可核验并接入受管目录。
- `tls_setup.py` 用于已有域名的 ACME 路径与证书路径调整；正式配置切换前先 `nginx -t`，每次备份到服务器受限目录。新发型站配置见 `nginx/hair.leshine.cloud.conf`。
