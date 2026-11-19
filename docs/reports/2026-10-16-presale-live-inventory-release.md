# 预售出库实时库存完整发布（2026-10-16）

已合并推送并从远端最新 main 固定 `86f1c44e530a27ca80acb3e65ab121c47f1995d3` 完成 `office-and-cloud` 受管全局部署。实现提交 `e0f907d5`，主目录合并提交 `86f1c44e`，发布身份 `84ead947720f4098b8a1e7ca4c04224d`。准备与正式任务退出码均为0，11个受管目标全部完成，deferred为空。

## 用户可见变化

生成出库弹框将“可出库数量”改为“剩余待出库”，后面增加“可用库存”。打开/刷新实时读取预售仓库 `8193514242746` 的启用 `enable_count`；不使用镜像、其他仓库或实物库存代替。本批整数数量上限取剩余待出库与可用库存较小值，同SKU多行合计也校验；报价与首次创建在后端再次读取当前库存。库存未知显示“待核对”并禁填对应行，库存下降刷新保留原填写、清旧报价并要求调整。原提交恢复及已创建请求的幂等查询保持。

## 发布与现场证据

统一入口：候选 `deploy/deploy.bat --live-root D:/commission-system --revision 86f1c44e530a27ca80acb3e65ab121c47f1995d3 --no-pull`，先 prepare-only，后同候选正式运行。办公室从a2673e03更新，北京从1c0d4244更新；两地当前HEAD、8个相关源码摘要及后端进程启动时间均核验通过。数据库仍为 `196_domestic_commission`，无迁移文件变化、无DDL。WhatsApp源码未变，办公室原已核实Node进程保留且健康；后端Python为新启动进程。

办公室直连、`leshine.work`、`leshine.cloud` 的 `/health` 均200/database=connected。两地及两个公网入口的授权库存GET均200/private,no-store；Janny订单1033每次返回33行、33行已知、0行待核对。该读数只证明查询时可读，不代表用户原需求数量均可满足或库存已预占。匿名库存读取被拒绝并no-store。主站本机及两个公网域的index和InvoiceManage JS逐文件SHA-256与候选制品一致，包含新列、实时库存请求、数量校验及既有1120px/内部滚动/紧凑行。PM、素材和客户门户入口的index摘要同样核验。

主站制品摘要：`415f8060041aca10ff4247c9c17da0928504ca17c543549890ffd80685cf5469`。5个静态发布目标已纳入同次发布；未变化制品复用缓存。出库调度回执verified并保留原active/enabled基线；北京邮件worker原inactive/disabled保持，未开经营开关。独立终端/非仓库来源服务的既有pending范围见platforms.json，不将其称为本次已更新。

Janny只读前后快照一致：订单1、产品33、原回款1、结算3、资金应用3、出库任务2、审计事件12。部署未取消/新建业务出库或结算，未修改回款及资金。此次范围是代码发布，未使用真实商业POST做业务验收。

资源保留最终succeeded，office/leshine.work/leshine.cloud三目标完成。发布锁已释放；两项临时任务实际LastTaskResult=0后注销。

## 验证与保留

实现收尾82项SQLite、7项真实JWT/ASGI/隔离MySQL、23项Node通过，实际Chrome库存桌面/手机、取消10场景、恢复3屏幕宽度通过，构建/strict conventions/6项UI gate及独立审查通过。既有嵌入回款helper手续费断言失败已在实现交接中单列，资金逻辑及原断言未改；本次库存专项正向使用无嵌入回款，拒绝仍核对完整财务图。

发布验证脚本首次将未改动的Node进程也要求在本次源码之后重启，产生检查失败。现场核对证实Node PID29512/启动时间与前次已核实回执相同、WhatsApp源码diff为空；改为要求后端新进程并单独证明未变Node原进程与健康，未重启无关服务、未调整产品代码或减弱后端新版本证明。

主目录49个既有脏文件已保存二进制patch、原index、文件副本和SHA-256清单。合并后47个逐字一致，API及handoff两份文档仅加本次内容；发布末再次49文件核验一致。仅当前报告和handoff末尾发布记录为后续有意新增。无冲突、index为空。保留受保护文档stash、发布与回滚证据，不清理此前被阻止删除的隔离测试恢复材料。

证据：本机 `.deploy_state/shipment-inventory-release-20261016/`，其中remote-evidence包含两份完整日志、prepare/deploy退出回执、publish-current/success、资源保留、finalization及真实任务状态；pre/post两地读回和verification-evidence包含接口/源码/进程/业务哈希与浏览器证据。Git巡检使用no-fetch，只作本地快照；远端main另以ls-remote回读。
