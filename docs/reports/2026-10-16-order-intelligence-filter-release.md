# 订单经营决策台筛选遮挡完整发布（2026-10-16）

已合并推送并拉取核对最新 `main`：`1eef7a2e7472588553ed8f7fb011105b9a7b3d32`。实现提交 `e874e5f8`，主目录合并提交 `1eef7a2e`。通过候选 `deploy/deploy.bat --live-root D:/commission-system --revision 1eef7a2e7472588553ed8f7fb011105b9a7b3d32 --no-pull` 先准备、再完整部署；发布身份 `3328c456a56b49ac900bd6c5cd1b7cdc`。应用11项受管步骤完成、deferred为空。原正式任务因D盘满在资源保留阶段exit 1；恢复空间后以同候选受管 `--static-retention-only` 接续并exit 0，三目标收尾完成。

## 用户可见修复

筛选卡使用 `position: relative`，却继承全局吸顶工具栏的导航高度 `top`，使卡片下移、被后续指标看板覆盖。仅在订单经营决策台页面设 `top: auto`，恢复普通文档流。修复前隔离浏览器实测偏移99px、重叠81px；修复后2383/1440/1280/820/390px五种屏宽的收起、展开、滚动、查询及重置事件通过，筛选卡与指标区间距18px。未改筛选逻辑和统计口径。

## 最新 main 与生产核验

办公室与北京均从 `86f1c44e` 更新到固定候选；本次也包含候选中已合入main的实时库存并行优化/填满、客户素材文件夹标签、新版订单录入与包装入口。两地6个相关源码文件摘要及后端新进程启动时间与安装顺序均通过。数据库保持 `196_domestic_commission`，无迁移文件变化、未执行DDL。

办公室直连、leshine.work、leshine.cloud健康读取均HTTP200、database=connected。三个主站入口index、InvoiceManage JS和OrderIntelligence CSS逐文件SHA256与候选构建清单相同；CSS已确认包含scoped `.oi-toolbar { top:auto }`。PM、素材和客户门户index摘要也通过。静态目标共5个，未变化的PM/素材/门户沿用已核验制品。

两地服务和开关与发布前基线一致：办公室Scheduler/WhatsApp自动同步原启用，北京Scheduler原关闭；客户门户写入、发票、通知、邮件、自动出库等开关保留，未开经营开关；北京邮件Worker原inactive/disabled保持，出库timer原active/enabled保持。WhatsApp源码未变、原已核验Node进程保持且健康。独立来源服务、APK安装、小程序审核发布及未开通域名继续遵守platforms.json的未纳管/pending范围，未宣称已更新。

Janny订单1033只读前后快照一致：订单1、产品33、回款1、结算3、资金应用3、出库任务2、审计事件12。授权订单/出库/实时库存GET在办公室及两公网入口均成功，库存响应private,no-store，33行数据均可读；匿名库存GET被拒绝且no-store。本轮没有用商业POST做验收，不据此宣称库存预占或业务已成交。

## Git 与证据

主目录原有50个脏文件已保存原HEAD/index、二进制patch、文件副本及SHA256清单。合并后49个逐字一致，handoff仅在原内容前加入本次记录；原内容保持完整。合并无冲突、index为空，HEAD、origin/main与远端ls-remote相同。此报告及handoff后续发布说明保留本地diff。

本机证据：`.deploy_state/order-intelligence-release-20261016/`。其中`remote-evidence/`保存发布及构建回执；`pre/post-office.json`、`pre/post-beijing.json`和源码摘要记录运行时/开关/业务指纹；`layout-evidence/`、`layout-fixture/`保存隔离浏览器脚本与截图。首次office-prod本机2223端口拒绝连接，用户恢复通道并要求重试后核验干净版本/无发布锁再继续；未绕过统一入口。

线上样式：`assets/OrderIntelligence-BYOopRQy.css`，SHA256 `e26fc619261028bbdb48bbb9db10c4c866b70530eef1244ffc06fc87411fe057`。

## 满盘恢复与最终收尾

首次读取办公室D盘可用空间为0，原正式任务日志在8192字节截断，应用回执已succeeded而资源保留尚未完成；保留原deploy-outcome的exit 1，不以旧retention成功标记冒充本次结果。

将8个明确的旧部署传输缓存包共17,333,067字节转存到办公室 `C:/ArkDeploymentRecovery/order-intelligence-20261016/transfer-cache/`，逐个SHA256读回通过，manifest留在同目录。未迁移业务文件、数据库、uploads、凭据或应用运行目录。转存脚本的末尾汇总因PowerShell FileInfo移动后Length失效报错，写操作未重发；后续按目标文件元数据独立回读并补正清单。随后用户明确告知已清理D盘，现场读回约62.9GiB可用，不能把这部分空间归因于17MB缓存转存。

首次维护调用被clean-source门禁拒绝：候选构建生成的 `backend/app/system/navigation_access_manifest.json` 仅工作区换行状态变化，git diff内容为空。先保留副本，再将该单文件恢复至固定提交；未修改业务运行代码或放宽门禁。第二个独立维护任务 `retention-r2` 通过原deploy.bat完成，exit 0、LastTaskResult=0；原完整发布及首次维护失败回执均保留。

最终资源保留succeeded，office/leshine.work/leshine.cloud三目标完成，当前版本及两份办公室回滚备份保留；发布锁释放，四项本次临时任务已注销。最终磁盘读回约63.0GiB可用。应用没有重发部署、没有重复迁移或重启。完整回执在remote-evidence/finalization.json、final-task-status.json和retention-r2.log。

本任务worktree已归档、本地已合并分支已删除；隔离浏览器证据先复制至本机发布证据目录保留。远端未建立本任务feature分支，无远端删除操作。随后按用户要求只读扫描办公室D盘，扫描报告另行留存。
