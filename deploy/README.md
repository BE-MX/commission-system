# 统一部署入口（COS 文件迁移暂缓）

`deploy.bat` 默认在办公室已安装 NSSM 服务的仓库运行。先在候选 worktree 准备源码、依赖、主站和 PM 制品，再切换办公室服务、北京后端和已登记的云静态站。完整目标清单见 `platforms.json`；未纳管服务和未开通域名会明确列出，不计作已更新。

```powershell
deploy\deploy.bat                           # 跟踪分支的最新提交；办公室服务 + 已登记云目标
deploy\deploy.bat --no-pull                 # 使用当前已提交、审查的 HEAD
deploy\deploy.bat --cloud-only --no-pull    # 明确只处理云端，不代表办公室已更新
deploy\deploy.bat --cloud-only --no-pull --prepare-only # 准备并校验，暂不切换
deploy\deploy.bat --revision <full-commit-sha> --migration-credentials <protected-file> --prepare-only
```

## 目录与版本规则

双击或右键「以管理员身份运行」时，发布结束会保留窗口，按任意键关闭；失败时先查看上方 `DEPLOY FAILED` 或 Python 启动错误，再处理具体原因。窗口关闭本身不代表部署成功。入口从 PATH 定位 Git，并优先使用该安装自带的 `usr/bin/ssh.exe`，避免系统 OpenSSH 在非交互 Python 子进程中挂起；无需手动调整 PATH。无人值守调用前设置 `DEPLOY_NO_PAUSE=1`（PowerShell：`$env:DEPLOY_NO_PAUSE='1'`），跳过等待并保留发布程序的退出码。

旧版入口若闪退，可先打开管理员命令提示符，在现有窗口中运行服务器仓库下的 `deploy\deploy.bat`，以保留错误输出。无需先改服务器受 Git 管理的脚本，以免触发下方的干净工作区检查。

- 仓库必须干净；候选源码、构建缓存、依赖、传输包、状态只在 `.deploy_state/`。
- Git 只传缺失对象到北京 `repo.git` 的独立 `deploy/<SHA>` 引用；不会 push origin/main。
- 远程 Python 脚本和 JSON 请求通过 SSH 标准输入传递，命令参数保持短小，避免 Windows SSH 启动链截断长脚本。换机器或更新 Git 后先用 `--prepare-only` 验证连接和制品。
- 默认 fetch 后只接收可快进的新提交；本地已审查提交领先远端时保留本地 HEAD，分叉时停止发布。无需为了部署先推送 main。
- 维护窗口使用 `--revision` 固定审查过的完整 40 位提交 SHA；即使远端有更新也不改变本次候选，拒绝倒退或分叉。`--no-pull` 仅控制是否 fetch。
- 本地源码以内容及 Node 版本计算构建指纹；相同输入复用同一制品。扩展包缓存也复用，避免仅因打包时间变化导致全站重建。
- 每个云目标一次计算 SHA-256 清单，变化文件打成一个包传输。未变文件零传输，不按单文件重复建立 SSH。
- 制品全部校验后才切换。首次发布用 Linux `renameat2` 原子地将原 Nginx 根目录换成受管符号链接；Nginx 原配置与别名仍指向相同路径。
- `assets/` 中历史文件追加保留；同名不同内容阻断，防止破坏仍打开的页面。当前不自动清理历史版本。
- 切换后通过本机 HTTPS、真实域名和证书验证 Nginx 返回的 index.html 摘要；失败恢复旧指针。
- 后端依赖在候选环境中安装；启动失败且 schema 未变化时回退代码/环境。数据库变更后失败保持停止，不能自动将旧代码接回新 schema。

## 数据库

办公室与北京共享 `commission_db`，每次发布都读数据库 revision，并检查发布代码的唯一 head 和迁移链。数据库已到目标则跳过 DDL；未知 revision、数据库领先、分叉均阻断。不会复制、覆盖或 downgrade 数据库。

有待执行迁移时，必须核实 `platforms.json` 中所有 writer 的归属。2026-09-07 已按生产连接与进程核实并登记办公室 `CommissionSystem` / `WhatsAppConnector`、北京 `ark-backend`、新加坡 PM2 `shipment-tracking-mcp`；PM2 只控制该进程，不操作整个 PM2 管理器。新增或迁移写入实例后必须重新核实清单，不能沿用旧确认。数据库 revision 每次读取，不使用历史版本号推断是否有 DDL。

2026-09-05 实施时数据库为 137、当次无需 DDL，见 [实施记录](../docs/requirements/2026-09-05-deployment-adjustment-implementation.md)；这属于历史记录，后续发布必须重新读取实际 revision，与候选代码比较。

迁移使用独立 DBA 身份。默认读取办公室运行仓库下 `.deploy_state/credentials/migration.env`，只含 `COMMISSION_DB_USER` 和 `COMMISSION_DB_PASSWORD` 两项；配置一次后双击入口即可复用。`--migration-credentials` 可以显式覆盖路径，显式文件不存在时直接报错，不偷偷换用默认文件。无 pending 时不需要该文件。

该文件由服务器管理员预先配置，NTFS 权限仅授予部署账号、SYSTEM 和 Administrators；目录禁用权限继承，不复制到候选源码、云服务器或开发机。使用独立、限定办公室来源与 `commission_db` 的迁移账号，仅授予 `SELECT/INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/INDEX/REFERENCES`，不授予账号管理或转授权。账号与文件长期留在该服务器供后续部署使用；轮换时更新受限文件，停用部署能力时撤销账号并删除文件。程序不会创建账号，也不会从应用 `.env` 自动提升为 DBA。

库地址和库名沿用已校验运行配置；停机前检查 DBA 权限。凭据只进入受控迁移子进程，禁止替换运行服务 `.env`，禁止把文件提交 Git。缺少凭据、权限不足、迁移链异常或恢复日志未关闭时，仍在停服务和 DDL 之前阻断。

迁移子进程先取得 MySQL 命名锁，再复核准备阶段的迁移链；停服务前持久化原始状态，停后再次核验全部 writer 已停止，才执行一次 Alembic upgrade。两个后端激活成功后恢复其他原本运行的 writer。DDL 前失败按原始状态恢复；DDL 开始后的失败不自动恢复旧程序，需检查 MySQL 实际结构。

展会分析、生图和话术使用后台 daemon 线程，发布前须冻结两台后端的新试戴提交（含办公室直连入口），以线程栈和数据库状态确认排空，再停服务。会话 `done` 不代表话术线程已结束；历史卡死记录单独核实，不批量改状态来伪造排空。

### 仅执行已审查的 137 → 138 迁移

`deploy\deploy.bat --migrate-only PLAN_JSON --migration-credentials PROTECTED_ENV --prepare-only` 先验证，移除 `--prepare-only` 才执行。此入口只支持已审查的新增表脚本及兼容应用版本，不构建前端、不切换应用代码、不写完整发布成功标记。

计划固定 `live_root`、`.deploy_state/sources/<revision>` 下的候选源码、办公室与北京 `application_revisions`、`nssm` 路径，以及完整 `migration_writers` 和核实标记。仅对本次从运行状态停止的 writer 恢复原状态，再检查两个后端数据库健康。PM2 按明确进程名操作，禁止整组 stop/resurrect 或改写 save 清单。`reviewed_unaffected_events` 只记录已审查为无影响的事件，不代表暂停事件。

状态写入 `.deploy_state/migration-138-current.json`。若上次停留在迁移、验证或恢复阶段（含这些阶段失败），普通重跑会保留原记录并阻断，必须先根据原始 writer 基线检查恢复；不能把服务仍停着的新基线误报为成功。

此历史专项入口仍遵守主线 `.deploy_state/schema-writers.json` 恢复保护：无 pending 也检查未完成记录，恢复与健康核验成功后才标记共享日志完成。候选由计划指定，不能与 `--revision`、`--cloud-only` 或 `--no-pull` 混用；不适用于 138 之后的迁移。

办公室 Windows 自带 OpenSSH 在 Python 子进程内发生过建立连接前卡住；已用同机 Git SSH 验证可运行。执行时可仅在当前进程 PATH 中将 `C:/Program Files/Git/usr/bin` 置于系统 OpenSSH 前，保留非交互认证与严格主机密钥校验，不修改系统 PATH。

## 状态与恢复

优先读取 `.deploy_state/publish-current.json`：本轮 revision、阶段、已成功目标。`publish-success.json` 仅代表最近一次成功，不表示当前运行成功。跨机器发布不是分布式事务：后面的目标失败时，前面已验证的目标可能已更新，脚本返回非零并保留阶段记录。

`--prepare-only` 成功后当前状态为 `prepared`，代表候选已校验但未切换；完整发布成功才更新 `publish-success.json`。

迁移恢复证据在 `.deploy_state/schema-writers.json`。`stopping`、`running-ddl`、`upgraded`、`failed-after-ddl`、`recovery-required` 等未完成阶段都阻断新一轮发布，即使数据库已到 head、没有 pending 也不能绕过。所有发布目标验证完成后才写 `completed`。检查实际结构、原始 writer 基线及当前应用版本后处理恢复记录，不能直接删除日志重跑。

旧 `rollback.bat` 已阻断，不能再消费旧 `dist_backup` 并 SCP 覆盖受管版本。失败激活在 schema 不变时有自动回退。已完成发布的人工回退必须先核对候选旧代码是否认识当前 schema，再按受管后端与静态发布流程执行；不得直接覆盖 `current` 下文件或降级数据库。

## 验证

```powershell
backend\.venv\Scripts\python.exe -m compileall -q deploy
backend\.venv\Scripts\python.exe -m pytest deploy/tests -q
```

从仓库根目录运行；Linux 使用对应虚拟环境的 Python。pytest 同时收集 unittest 类和函数式回归，避免遗漏新增发布流程测试。静态文件语义测试必须在 Linux 临时目录执行（包含原子目录交换和符号链接），不连接生产数据库、不修改站点根目录。Windows 会明确跳过该组；源码准备及数据库阻断测试在 Windows 执行。实际部署完成后，再次运行相同发布命令验证无变化构建/文件传输被跳过。

## 当前边界

- COS 文件迁移暂缓，办公室文件和北京 `/data/customer-media` 保持原位置。
- `pm.leshine.cloud` 尚缺 DNS/TLS，已列为 pending；不得未开通就显示成功。
- hair/video 权威源码仍在本仓库之外；独立 MCP、同步器、中继、OpenClaw、n8n 和终端安装分别列出，不盲目升级 latest。
- 办公室服务器实际远程更新、内网 DNS 和办公室直连北京隧道，需要可用的办公室管理入口才能完成。
- `--cloud-only` 若发现新加坡前端有变化，会等待对应办公室后端发布并列为 deferred；不提前上线依赖旧 API 的新页面。完全一致的页面可核验并接入受管目录。
- `tls_setup.py` 用于已有域名的 ACME 路径与证书路径调整；正式配置切换前先 `nginx -t`，每次备份到服务器受限目录。新发型站配置见 `nginx/hair.leshine.cloud.conf`。
