# 统一部署入口

`deploy.bat` 默认在办公室已安装 NSSM 服务的仓库运行。先在候选 worktree 准备源码、依赖、主站和 PM 制品，再切换办公室服务、北京后端和已登记的云静态站。完整目标清单见 `platforms.json`；未纳管服务和未开通域名会明确列出，不计作已更新。

```powershell
deploy\deploy.bat                           # 跟踪分支的最新提交；办公室服务 + 已登记云目标
deploy\deploy.bat --no-pull                 # 使用当前已提交、审查的 HEAD
deploy\deploy.bat --cloud-only --no-pull    # 明确只处理云端，不代表办公室已更新
deploy\deploy.bat --cloud-only --no-pull --prepare-only # 准备并校验，暂不切换
deploy\deploy.bat --revision <full-commit-sha> --migration-credentials <protected-file> --prepare-only
```

## COS 公网文件路由

`deploy.bat --storage-routing-only <probes.json> --prepare-only` 仅准备五个入口的Nginx候选（两主域、北京平板IP、hair、video）并验证语法，不改变线上流量。去掉prepare-only前必须完成应用、schema、历史引用和域配置切换；探针JSON为各公开命名空间的真实已迁移文件URL相对路径列表，空列表仅允许准备。切换失败按站回滚，跨站已完成记录保留在`.deploy_state/storage-routing.json`。该入口只调整公开文件和封闭色块机器网关，办公室业务API、LAN上传归属与Scheduler保持原配置。

源码发布制品仍不包含uploads或其他业务数据。用户授权的COS历史迁移使用独立清单及SHA256回执；代码发布成功不等于数据迁移和实际手机验收完成。

## OKKI 出库轮询器专项

`deploy\deploy.bat --okki-outbound-only --prepare-only` 预检，去掉 `--prepare-only` 部署并启用新加坡出库轮询器。仅更新该服务，无应用发布或迁移；运行配置、已有单跳过与不确定提交处置见 [轮询器说明](okki_outbound_poller.md)。

## 目录与版本规则

### 出库检验视频（迁移 152）

发布时先通过上述统一入口部署包含迁移 152 的后端与 PC 制品，再启用两站视频上传路由并更新小程序。旧小程序默认编辑版本为 0，无法编辑已撤回单据，应使用新版后再启用撤回操作。

```powershell
deploy\deploy.bat --shipping-video-routing-only --prepare-only
deploy\deploy.bat --shipping-video-routing-only
```

该专用入口只接受可选的 `--prepare-only`，普通应用发布不会自动执行它。它在新加坡/北京现有站点增加视频上传精确路径：Nginx 请求上限 101m（含表单开销），应用单视频上限 100 MiB，上传超时 300 秒。保留各站现有后端归属及凭证/色块路由；视频依旧存于各后端私有存储，不迁移媒体或扩大其他 API 的限制。使用独立 shipping-video 状态目录和日志，候选检查隔离 Nginx 临时目录，激活前校验配置摘要，失败自动恢复配置。路由准备和激活属于生产操作，须按本次目标环境取得部署授权；本轮仅交付代码，未执行生产操作。

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

2026-09-17 回款/公告补发：新加坡 `ark-okki-outbound-poller.timer` 已作为 `systemd_timer` writer 纳管。迁移前只停止计时器，等待对应 oneshot 为 inactive 且 MainPID=0（最多120秒），不强杀正在提交小满的任务；排空失败阻断DDL并按原基线恢复计时器。原来未运行的计时器不自动启用。迁移后仅恢复本次暂停的调度；原应用/PM2 writer 检查照常执行。配置中的外部出库轮询器存在时，遗漏此writer会直接阻断。

生产菜单缺失排障先核对实际运行HEAD和静态入口；`publish-current.json` 的 failed 可能沿用此前版本/完成列表（预检在写新journal之前失败），不能据其中 completed 认定新版本已上线。9e5cd2dd 发布预检已复现旧writer清单不完整，办公室和北京仍为2609626f，schema最近成功记录154；修复后的候选需重新prepare再经授权完整发布155/156。

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

### 候选已含部署器修复，但安装目录仍在运行旧部署器

2026-09-15 的 `520c22ca` 安装目录启动部署 `7efe0cf0` 时，旧进程的预检只算出 152，候选迁移 runner 则正确算出美颜分支 146 + 152。记录为 `failed` / `restored-before-ddl`、writers 与 stopped 均为空；取到新源码不等于当前 Python 进程已加载新部署器。

这种情况可从已审查、固定版本的受管候选启动同一个 `deploy.bat`，显式传 `--live-root`。候选必须位于 `<live>/.deploy_state/sources/<完整 SHA>`，且 SHA 与 `--revision` 一致；仅支持普通完整发布及其 `--prepare-only`，不用于部分发布或迁移事故恢复。全部部署模块取自候选，服务目录、状态、锁和 DBA 凭据仍使用安装目录。不要先更新正在运行的业务 checkout，也不要删除迁移日志。

```powershell
# 候选提交须已安全传入本机 Git 并准备为受管 worktree。
$releaseRoot = 'D:\commission-system'
$releaseRevision = '<reviewed-full-commit-sha>'
$env:PATH = "$releaseRoot\backend\.venv\Scripts;$env:PATH"
& "$releaseRoot\.deploy_state\sources\$releaseRevision\deploy\deploy.bat" --live-root $releaseRoot --revision $releaseRevision --no-pull --prepare-only
# 准备成功后，同一命令去掉 --prepare-only 才开始生产切换。
```

正常入口的命令不变；修复版本完整部署成功后，安装目录本身也具备新部署器，可继续双击原入口。固定候选分支后续仍需按 Git 授权规则集成到 main，避免与将来的发布来源分叉。

优先读取 `.deploy_state/publish-current.json`：本轮 revision、阶段、已成功目标。`publish-success.json` 仅代表最近一次成功，不表示当前运行成功。跨机器发布不是分布式事务：后面的目标失败时，前面已验证的目标可能已更新，脚本返回非零并保留阶段记录。

`--prepare-only` 成功后当前状态为 `prepared`，代表候选已校验但未切换；完整发布成功才更新 `publish-success.json`。

迁移恢复证据在 `.deploy_state/schema-writers.json`。`stopping`、`running-ddl`、`upgraded`、`failed-after-ddl`、`recovery-required` 等未完成阶段都阻断新一轮发布，即使数据库已到 head、没有 pending 也不能绕过。所有发布目标验证完成后才写 `completed`。检查实际结构、原始 writer 基线及当前应用版本后处理恢复记录，不能直接删除日志重跑。

### 2026-09-14：149 版本编号超长的专项恢复

旧 revision `149_domestic_order_review_columns` 长 33 字符，超过 `alembic_version.version_num` 的 32 字符。已只读确认的现场是版本停在 148，而 149 的三个审核字段与外键都已存在。修正版使用 `149_dom_order_review_columns`（27 字符）；迁移先严格校验已有列类型、可空性及外键，复用兼容对象，只补缺项，不 stamp、不删除字段。

此专项入口只接受原始 `failed-after-ddl`、147→148→旧149 的完整日志，四个 writer 原本均 running 且有完整停止证据。原始日志保存在 `recovery_original` 中；当前清单必须完全一致。当前数据库必须为 148 或修正版149，代码唯一 head 必须为修正版149。其他事故仍阻断，不能把此开关当通用强制发布。

在生产恢复获得授权、服务器已具备本次修复的部署脚本后，使用经审查的完整提交 SHA 固定候选。先执行只准备命令，检查通过后再执行完整恢复：

```powershell
deploy\deploy.bat --recover-migration-149 --revision <reviewed-full-commit-sha> --prepare-only
deploy\deploy.bat --recover-migration-149 --revision <reviewed-full-commit-sha>
```

仍使用原有受限 DBA 凭据，可按需加 `--migration-credentials`。只准备阶段不启停服务、不执行 DDL、不改迁移日志；办公室服务若因原事故仍停止，允许准备。正式恢复重新取得数据库发布锁、核验结构及四个 writer，保持原始运行基线，确认全部停止后由 Alembic 完成迁移版本登记。随后沿正常入口激活办公室/北京后端及静态站，恢复原本运行的附属 writer，全部成功才关闭恢复记录。任何恢复失败保留记录，不自动启动旧代码；后续仍须使用同一固定候选和专项入口核验后重试。

此入口要求完整办公室/云发布，不支持 `--cloud-only`、`--migrate-only` 或未固定 `--revision`。部署脚本自身不会在运行中切换到新版本；如果服务器启动入口仍是旧代码，应在维护窗口核对办公室服务已停止后，将服务器 checkout 快进到经审查的修复提交，再运行新入口。不能从未安装服务的候选 worktree 直接启动完整发布，也不能删除日志以绕过旧入口。

旧 `rollback.bat` 已阻断，不能再消费旧 `dist_backup` 并 SCP 覆盖受管版本。失败激活在 schema 不变时有自动回退。已完成发布的人工回退必须先核对候选旧代码是否认识当前 schema，再按受管后端与静态发布流程执行；不得直接覆盖 `current` 下文件或降级数据库。

## 验证

```powershell
backend\.venv\Scripts\python.exe -m compileall -q deploy
backend\.venv\Scripts\python.exe -m pytest deploy/tests -q
```

从仓库根目录运行；Linux 使用对应虚拟环境的 Python。pytest 同时收集 unittest 类和函数式回归，避免遗漏新增发布流程测试。静态文件语义测试必须在 Linux 临时目录执行（包含原子目录交换和符号链接），不连接生产数据库、不修改站点根目录。Windows 会明确跳过该组；源码准备及数据库阻断测试在 Windows 执行。实际部署完成后，再次运行相同发布命令验证无变化构建/文件传输被跳过。

## 当前边界

### 充值凭证统一办公室存储


#### 上传 500 与预检查临时目录隔离

若充值/图片上传在 Nginx 错误日志出现 `/var/lib/nginx/body/... Permission denied`，先核对运行 worker 的账号及临时目录属主。请求此时尚未到达业务 API，不能据此修改充值申请或余额。

`voucher_routing_remote.py` 与 `colorwork_routing_remote.py` 的语法预检查必须显式指定五种临时路径（client_body/proxy/fastcgi/uwsgi/scgi），以及 pid、error_log、access_log，并通过 `-e stderr` 隔离配置解析前的启动日志；路径仅落各自备份目录内的区域 syntax 子目录。仅指定 `-c` 或 `-p` 不足以隔离编译时的绝对默认路径。root 执行 `nginx -t/-T` 会创建或调整临时目录属主：最小配置省略 user 时可能改成 nobody，使正式 www-data worker 无法写入；即使没有 reload、候选无变化或准备后停止也会影响线上。

生产排障先直接读取配置文件、worker 账号、目录元数据及日志，不把 `nginx -T` 当成无副作用读取。恢复目录权限属于生产操作，先获得授权、记录原属主/模式并核对实际路径和 worker；不递归修改业务目录，不使用 777。用超过缓冲区大小的匿名请求检查传输层时，预期到达后端并返回鉴权失败，不能将其当作真实充值审核成功。


`deploy\deploy.bat --voucher-routing-only --prepare-only` 仅准备新加坡、北京的两个凭证路由并执行独立 Nginx 语法检查，不切换流量。经授权后移除 `--prepare-only` 应用；不与普通应用发布、迁移、`--revision` 或 `--cloud-only` 混用。此专项使用当前工作目录中的路由脚本及配置，执行前必须完成 diff 审查。

- 新加坡 `/api/domestic/customers/{id}/recharges` 和 `/api/domestic/customer-requests/{id}/voucher` 走原有办公室 `127.0.0.1:8002` 隧道；北京同路径经证书校验的 HTTPS 转发到新加坡 `leshine.work`。北京主域 HTTPS 和既有 IP 入口都覆盖。
- 转发完整原始 URI、表单和用户 Authorization，仍由办公室后端执行归属/审核权限、文件类型与大小检查。文件存储使用办公室 `DOMESTIC_STORAGE_ROOT`（默认 `D:\WORKSOURCE\domestic`）。其他内贸 API 不变；不迁移 COS、不复制数据库或文件。
- 两级网关请求体限额为 21MiB（后端文件上限20MiB），凭证禁止缓存，充值禁止 upstream 自动重试。办公室隧道不可用时请求失败，不回退北京落盘。
- 两机都准备成功后，先切新加坡再切北京；激活前核对当前配置摘要，漂移则阻断。每台切换前备份至该机 `/etc/nginx/.ark-backups/domestic-voucher/`；全局 `nginx -t` 或 reload 失败恢复原文件。状态写在本地 `.deploy_state/voucher-routing.json`。北京失败时新加坡可能已经生效，查 `completed`，不要误报两机都成功。
- 准备检查只验证片段语法和目标文件结构；完整运行配置在激活时检查。发布后需用真实申请分别在 `.work`、`.cloud` 查看图片/PDF，并核实同一笔申请、权限及文件内容。没有凭证的记录保持404；禁止为了验证制造充值或审批。
- 历史凭证先按数据库相对路径核对办公室原文件；若文件在其他实例，只能在确认来源和目标、核对摘要并保留原件后另行迁移。修改路由不会自动找回缺失文件。

- COS 文件迁移暂缓，办公室文件和北京 `/data/customer-media` 保持原位置。
- `pm.leshine.cloud` 尚缺 DNS/TLS，已列为 pending；不得未开通就显示成功。
- hair/video 权威源码仍在本仓库之外；独立 MCP、同步器、中继、OpenClaw、n8n 和终端安装分别列出，不盲目升级 latest。
- 办公室服务器实际远程更新、内网 DNS 和办公室直连北京隧道，需要可用的办公室管理入口才能完成。
- `--cloud-only` 若发现新加坡前端有变化，会等待对应办公室后端发布并列为 deferred；不提前上线依赖旧 API 的新页面。完全一致的页面可核验并接入受管目录。
- `tls_setup.py` 用于已有域名的 ACME 路径与证书路径调整；正式配置切换前先 `nginx -t`，每次备份到服务器受限目录。新发型站配置见 `nginx/hair.leshine.cloud.conf`。

## 库存色块内部模块

北京后端发布同时纳管 colorwork-workbench：浏览器使用方舟 `/api/colorwork/workbench/`，不使用子域名。
完整发布和 `--cloud-only` 均准备两站 `/api/colorwork/` 路由；北京模块激活并通过 readiness 后，
先切北京再切新加坡，使 `.work` 的 SSO、会话、文件全部落北京。办公室 8787 属于 WhatsApp Connector，
不得用它承接色块工作台。两个入口仍使用既有方舟 Bearer 鉴权，工作台使用路径受限 Cookie。
局域网直连办公室不会经过这两条 Nginx 路由，需更新办公室后端代码：Windows 默认使用
`COLORWORK_GATEWAY_ORIGIN=https://leshine.cloud` 代理 SSO 与工作台，Linux 默认使用本地运行服务。
无需为办公室复制工作台密钥或数据；显式空网关表示本地模式，办公室生产环境不得设为空。
`--cloud-only` 不更新办公室后端，因此不能用它验收局域网修复。发布后须通过局域网 HTTP
验证三个入口、刷新、上传与退出，确认 Cookie 仍为局域网模块路径。
新加坡到北京校验 TLS；仅将两个合法 `.work` Origin 转为北京 Origin，其他 Origin 保留给后端拒绝。
26MiB 请求上限覆盖 25MiB JPG 和 8MiB PSD 分片；禁用 upstream 重试与缓存，SSO 请求不写访问日志。

已有健康北京模块时，可用 `deploy\deploy.bat --colorwork-routing-only --prepare-only` 单独准备路由，
正式应用去掉 `--prepare-only`。此入口不安装模块，不支持与普通发布参数混用；北京模块未就绪时在改配置前阻断。
准备期只生成候选并检查 Nginx 语法，不 reload；正式切换前复核原配置摘要，失败恢复原文件并重载。
路由备份在各服务器 `/etc/nginx/.ark-backups/colorwork/`，专项状态在本地 `.deploy_state/colorwork-routing.json`。
每站激活后核验真实域名 readiness；新加坡失败时北京可能已切换，按 `completed` 查看实际完成范围。

`remote_backend.py` 依次调用 `colorwork_release.py` prepare/activate，自动准备固定 Node/pnpm、构建、受限运行配置、
隔离 D1 验证、正式 D1/R2 整体备份与迁移、回环运行服务 `ark-colorwork` 及 readiness 检查。
`--prepare-only` 不启动服务、不改正式 D1/R2。同候选复用校验后的制品，同成功候选重跑不重启模块。

数据位于北京 `.deploy_state/colorwork/data`，**此子目录是业务持久存储，不可清理**。
失败时 `current.json` 和本轮 `backups/<revision>-<attempt>` 必须保留；普通重试会阻断，先按
`colorwork-workbench/README.md` 核验失败现场、备份及 schema。北京原先没有 Node 时由准备阶段下载官方固定版本并校验摘要，
不要求手工全局安装。首次使用的真实 PSD/JPG 素材包需单独导入，不能通过代码发布复制业务数据。
# 共用手机发货质检发布补充（2026-09-15）

入口为方舟同域名 HTTPS `/shipping/scan`，手机登录后返回该页面。摄像头使用浏览器 API，HTTP 普通局域网地址不能代替 HTTPS 验收。

上线依赖：备份并按标准发布流程应用迁移 `153_shipping_station`，更新实际承接请求的后端、前端与小程序刷新接口。迁移不创建账号或授予权限；管理员需给专用登录账号配置 `shipping_station:write`，不要将其作为实际操作人员。候选角色由 `SHIPPING_STATION_ROLE_ID` 指定，当前安装已只读核验为 28（fhqc，发货质检）；异库部署必须核对。空闲/最长会话分别配置 `SHIPPING_STATION_IDLE_MINUTES=15`、`SHIPPING_STATION_MAX_HOURS=8`。

现有 `--shipping-video-routing-only` 专用入口同时纳管 station 会话照片、视频路径：照片请求上限 21m、视频 101m，300 秒上传超时；普通 API 限制和各站后端归属保持原值。仍先 prepare-only 检查，再在取得目标环境发布授权后激活。主站代码发布不会自动执行此专项入口。

真机验收需覆盖 Android Chrome / iPhone Safari：扫码授权与后置摄像头、相册视频、弱网重试、多人交接、PC 撤回后继续编辑；当前已完成本地组件/模拟摄像头识别和隔离数据库验收，未代替真实手机或生产 MySQL 并发验收。
# 办公室内网 HTTPS 专项入口

`deploy.bat --office-lan-https PLAN_JSON --prepare-only` 校验指定办公室安装、健康、证书和 Caddy 配置；移除 `--prepare-only` 才安装独立 `ArkOfficeHttps` NSSM 服务。此入口不发布应用、不运行迁移、不触碰其他服务。

计划包含 `live_root`、`address`、`subnet`、`backend_port`；当前已核验分别为 `D:/commission-system`、`192.168.100.3`、`192.168.100.0/23`、`8001`。入口固定 `lan.leshine.cloud`。证书放运行根目录 `.deploy_state/office-lan-https/certs/fullchain.pem` 和 `privkey.pem`，目录权限仅管理员和 SYSTEM；不得提交或作为代码制品传输。证书应覆盖域名、密钥匹配且有效，最终使用系统 CA 和真实 SNI 校验线上证书及本地 PEM 一致。

使用固定 Caddy 2.11.4 官方 Windows 包及 SHA-512 校验，只绑定指定内网地址 443；防火墙仅允许指定局域网，反向代理本机 8001。保留现有 HTTP 入口。首次安装失败清理本次服务与规则并核验残留，已有服务配置漂移则拒绝覆盖。

手动 DNS-01 证书不支持无人值守续期。续期需要重新完成 DNS 验证、受限传输新证书，保留旧证书后安排独立 HTTPS 服务重启；原方舟后端不需重启。普通重跑会核对线上叶证书，旧证书未重载时拒绝报告新证书已上线。切换到 DNS API 自动续期应另外提供最小权限凭据。


## 2026-09-16：151 外键失败后的兼容服务恢复

仅针对数据库仍在 `152_shipping_media_recall`、151只添加 `tag_scope` 及普通索引，关联表和153/154表均不存在、两端应用保持 `ba491dfe` 的已核实现场。使用 `deploy.bat --restore-pre151 PLAN --prepare-only` 验证；去掉 `--prepare-only` 才恢复原本运行的四个 writer。PLAN含 `live_root` 与原 `schema-writers.json` 的 SHA-256 `journal_sha256`。入口在安装目录发布锁及共享数据库锁内重新核实应用、服务归属、schema和原writer基线；不执行DDL，不移动业务文件，不更新应用代码。

已运行的兼容旧服务保持运行，只启动停止的服务。恢复结果写入安装目录 `.deploy_state/restore-152.json`，原失败迁移日志保持不变，普通发布继续阻断。此操作恢复旧版可用性，不代表迁移或新版本发布完成。后续继续迁移需要另行审查原始日志与当前writer状态，禁止删除日志或手工stamp。此入口不能与 `--live-root`、普通发布、HTTPS、其他专项发布参数组合。


### 继续完成 151 → 153 → 154 的恢复发布

`--recover-migration-151` 仅用于 2026-09-16 的外键符号类型不匹配事故：原日志为数据库152、目标154、pending151/153/154，四个原writer均running且有完整停机证据。恢复完整保留 `recovery_original`，重新核对当前数据库结构和迁移链；无stamp/downgrade/清日志操作。

必须固定经审查的完整 `--revision`，执行完整办公室+云发布。先带 `--prepare-only` 验证；去掉该参数才停止writers、执行迁移并切换两端应用和静态站，最终完成健康验证后关闭事故日志。旧安装目录缺少该入口时，可从 `.deploy_state/sources/<revision>/deploy/deploy.bat` 加 `--live-root <安装目录>` 启动候选部署器；服务和状态始终归安装目录。数据库已完成部分revision时重新校验；不完整的未知结构或缺失原始writer证据仍阻断。中途失败不得启动不兼容旧程序。

## 回款固定办公室入口

`deploy/deploy.bat --receipt-routing-only --prepare-only`预检，去掉`--prepare-only`正式应用。两站`/api/receipts`及其子路径统一到办公室，保留用户鉴权、关闭缓存和上游重试；北京使用校验证书的HTTPS连接新加坡入口。网关11MiB覆盖multipart开销，后端仍严格限制每张10MiB。先归集并核对历史凭证SHA256，保留来源备份，切换后再核对新增文件。此模式通过入口路由固定存储，但北京订单保存仍须配置 `RECEIPT_STORAGE_PROXY_URL=https://leshine.work`，办公室保持空并负责真实文件校验；局域网入口须直达办公室。


回款核验私有索引位于 `backend/data/receipt-index`，与凭证一样不作为代码制品覆盖或复制。首次全量核验后后续请求增量刷新，重启保留。办公室该目录仅授予SYSTEM、Administrators、服务维护账户访问；云端文件权限0600。损坏可自动重建，但重建耗时数分钟；部署不得通过清空业务data目录来更新代码。应用与小满时间须保持同步（增量重叠60秒）。

### 158 关联单据同步发布约束

此版本同时修改后端、前端及Singapore的okki_outbound_poller.js。发布关联同步前暂停旧poller，经统一deploy.bat完成158迁移和相关实例更新后才恢复，避免旧执行器绕过ark_invoices.linked_sync_id。若候选入口将poller列为deferred，关联同步功能不得启用，需将Singapore执行器更新纳入本次发布。参见[关联同步说明](../docs/invoice-linked-sync.md)。

换址时可额外指定 `previous_address`，必须匹配已安装地址且处于原子网。入口核验旧配置、归属、防火墙与新网卡，备份后仅重启 ArkOfficeHttps，HTTPS 校验成功才更新 marker；失败恢复原配置，但旧 IP 已移除时无法保证旧地址可访问。


## COS 生产切换入口

`deploy.bat --storage-maintenance PLAN [--prepare-only]` 独立记录 API 与办公室 LAN 维护状态；计划包含 attempt、action（freeze/restore）。恢复只移除本轮维护规则，保留期间新增的路由。

`deploy.bat --storage-cutover PLAN [--prepare-only]` 分 prepare、stop、configure、register、start 五步，固定实际发布 revision 与维护 attempt。配置和共享引用登记前，两机文件写入服务必须停止；最终回执 SHA 和域/来源矩阵固定证据。register 只由办公室在一个数据库事务中执行；start 要求登记完成记录、运行配置及 Colorwork 配置一致。保留原件、受限环境备份和 R2 未完成分片；不可删除状态日志强行重跑，产生新云文件后不可直接改回本地存储。

`storage_snapshot.py` 只复制文件，默认计算当前原件 SHA 后复用匹配的云回读收据；缺少源目录需显式空源审计。用户明确同意时可指定 `--reuse-asset-receipts`，对大小/mtime 未变的素材复用原回执，不能把该模式称为新一轮完整内容校验。

`--storage-routing-only` 切换公开文件与上传入口，新加坡到北京仍启用 TLS 校验，链深度为3。Nginx reload 后短暂等待新 worker 接管。办公室原件保留，局域网上传先持久化原件与队列，再由后台同步 COS。

`--finalize-release PLAN` 仅恢复已经完成办公室/北京后端激活与 schema 升级、但后续静态发布失败的已记录发布；重新核对日志、revision、tracked 状态及受管候选，不重复DDL。
