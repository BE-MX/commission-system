# 回款与公告生产发布记录

## 结果与证据

2026-09-17，用户明确授权「正式部署」后，从办公室受管候选 `dab19815d5db8cf5a1e1ae7ae33ac0fd98109330` 调用统一 `deploy/deploy.bat`，指定 `--live-root D:/commission-system --revision <上述SHA> --no-pull`。未手工执行DDL或绕过迁移恢复保护。

| 核验对象 | 实际结果 |
| --- | --- |
| 办公室、北京后端HEAD | 均为dab19815 |
| 生产迁移 | 154→155_announcements→156_receipt_management；schema-writers.json为completed |
| 发布状态 | publish-current.json为succeeded；日志返回MANAGED APPLICATION RELEASE COMPLETED；deferred=[] |
| 两站主前端 | 制品eb4481c2964665b63fad1d4ceae73f751692cca3aec8db9d378edd2bce88d9a3 |
| leshine.cloud实际下载入口 | main-ChCEY2dr.js，包含/invoice/receipts、/announcements及ReceiptManage/AnnouncementList模块 |
| 新API | 匿名GET返回403 Not authenticated，未伪造用户身份读取业务数据 |
| 北京健康 | /health返回status=ok、database=connected |
| 原运行服务恢复 | 办公室CommissionSystem/WhatsAppConnector为Running；北京ark-backend为active；新加坡outbound timer active、shipment-tracking-mcp有存活PID |
| 小满回款发送 | 办公室、北京运行配置RECEIPT_SYNC_ENABLED均False |

独立未纳管的PM域名、hair/video仍按原清单列pending，不表示本次回款/公告发布失败。未制造生产测试回款、公告或群消息；浏览器连接不可用，未完成登录账户菜单及真实业务全链路验收。凭证代理配置和跨入口读取也未在本轮验收。

## 原因与修复

问题发生时两端仍运行2609626f，静态入口main-To7MRazF.js没有两个新页面。9e5cd2dd受管候选已存在，但统一入口prepare-only复现：Database migration pending: verify every office/cloud writer。预检未停服务或执行DDL。

新加坡OKKI出库轮询器已经启用，旧部署器无法暂停其timer并排空正在执行的oneshot，因此writer清单被标记为未验证。修复新增固定systemd_timer控制：只暂停timer，最多120秒等待oneshot inactive且MainPID=0，不强杀正在执行的小满操作；排空失败阻断DDL，按原始基线恢复调度，原先停用的timer不被误启用。

部署前已只读核实五个writer归属及状态；本地deploy/tests为212 passed、11 skipped，独立审查无阻断。修复候选通过bundle导入办公室Git，prepare-only成功后才在用户授权下正式切换。

## 记录位置与后续维护

发布和准备日志归档于主目录 `tmp/receipt-release-evidence/`；原日志仍保留在部署修复worktree。当前进度、分支归属和未完成事项只维护在[交接文档](../handoff.md)。回款接口/金额/凭证规则见[实现说明](../requirements/2026-09-17-receipt-management-implementation.md)，公告启用条件见[公告实现说明](2026-09-17-announcement-implementation.md)。

排障教训：核对实际运行HEAD与线上静态入口，不能只看Git已推送。部署预检在写新journal前失败时，旧completed列表可能仍保留；必须同时检查status和revision，不能把旧目标列表当成本轮发布成功。
