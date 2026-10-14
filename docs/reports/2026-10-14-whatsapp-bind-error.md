# 2026-10-14 WhatsApp 业务号关联失败修复

## 原因及只读证据

关联创建的ConnectorError被后续GET404覆盖为“连接器确认关联操作未建立，请重新点击关联”，隐藏了创建失败的原始原因。

本轮核验北京后端WHATSAPP_CONNECTOR_BASE_URL=http://127.0.0.1:8787，该端口属于色块服务，携带Bearer的GET /health返回404和非JSON。办公室office-prod（lys-acciowork）D:/commission-system的8787才是唯一WhatsApp connector：健康200，provider=baileys，storage=sqlite-single-host；回调127.0.0.1:8001，共享key匹配。两域匿名账号列表均403，只证明入口鉴权。

云端关联因此访问错误服务。未创建真实关联、扫码、重发原关联或修改生产授权记录。真实账号关联及历史同步仍未验收。

## 候选修复

- 完整 /api/whatsapp 域API统一由办公室后端执行。北京经TLS校验的新加坡入口透传原URI及用户Authorization至办公室隧道，避免在北京启动第二个connector。
- 匹配 /api/whatsapp(?:/|$)，保留独立whatsapp-translation和色块服务；关闭代理自动重试、缓存及访问日志。
- deploy/deploy.bat --whatsapp-routing-only复用受管路由准备、摘要漂移检测、备份及失败恢复，只可与 --prepare-only共用。无数据库变更。
- 单次POST失败且同操作GET404时保留首次ConnectorError；GET不可用仍保留pending，下次点击先GET，不重复POST。

## 验证及交付状态

原实现的错误保留回归和原renderer的新feature回归均失败。修复后后端4组30 passed，部署路由/CLI/pipeline共99 passed。独立agent发现的混合入口及旧regex冲突识别问题已修复并复核通过。约定检查通过，Git巡检使用 --no-fetch，属于本地快照。

两站 --whatsapp-routing-only --prepare-only通过Nginx语法检查，返回prepared、completed=[]，未reload或切换流量。候选保留在服务器 /etc/nginx/.ark-backups/whatsapp/，本地状态 .deploy_state/whatsapp-routing.json。正式切换需用户授权，再走同一deploy.bat入口并核验实际路由与原服务状态。后端错误提示修复另需普通应用发布。

当前分支codex/whatsapp-bind-error，未提交、合并、推送或部署。办公室健康检查不代表真实扫码或历史同步成功，补充排查见下节。

## 办公室二维码查询失败的独立原因

用户补充办公室端仍无法刷新二维码。本轮固定最近关联对象只读核验：13:37:12关联POST200；13:37:21首次刷新200，同时自动同步失败；13:37:30自动同步再次失败，账号记录authorization_unavailable，后续刷新502。13:38:17持有人已发起撤销，当前为revoke_pending/consent revoked；没有恢复或改写该授权。

event_sync先锁账号再HTTP拉取feed，而connector读取feed前回调authorization_snapshot，同样锁账号。此互等路径使回调超时后connector保护暂停并清除QR，符合生产时序。pending rebind的owned_account锁后GET也有同类路径。

候选改为无锁fetch，返回后通过锁定当前读复核owner、generation、consent、员工权限及游标，再原子应用。并发推进游标时拒绝旧批次，授权改变时不应用消息。pending回查前释放锁，不重发POST。查询403时只回读安全账号metadata，显示停止状态并清QR；过期代次不能改变当前绑定。前端blocked/revoking/revoke_pending均停止自动轮询。

新增后端锁顺序、授权变化、游标推进及停止状态回归；原实现4项失败，另一个pending持锁回归原实现失败。前端真实composable合成API/timer验证原实现3项失败、修复6通过。后端5组50 passed，既有部署测试99 passed，独立审查通过。并发测试为隔离SQLite/同Session模拟，MySQL REPEATABLE READ通过代码审查，未执行真实MySQL双事务测试。

后端和前端修复尚未生产发布；路由专项不能替代本次应用修复。已撤销授权保持原样，真实二维码、扫码及历史同步需发布后持有人重新授权并验收。

完整前端构建通过（3517 modules、118 navigation entries）。主目录依赖不完整，使用tmp/whatsapp-build中的同源码镜像及隔离npm ci；修改composable的SHA256与任务源码相同。临时frontend/node_modules依赖junction的删除被自动审批以blocked by policy拒绝，链接已保留，未绕过拦截；构建目录与制品保留作为验证恢复材料。
