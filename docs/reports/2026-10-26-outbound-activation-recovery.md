# 出库调度激活检查点恢复

应用版本 d6e56d82、release_id a173e5bbeaf34c54939f59d733ded0bc 已完成两后端、两路由及五静态，schema202→203_perf_goals→204_portal_delivery_profile 已完成。最后 outbound-activate 的 ModeFence 未确认，发布保留 failed；原轮询器正向核验 installed_paused、timer disabled/inactive、service MainPID0。故障原因尚未确定，未将命名锁后续空闲当作故障根因证据。

用户已授权完整发布及定点数据维护。先在部署互斥锁与共享出库锁下，核实两端新接口及运行版本、schema、全部静态、模式/数据库指纹、原轮询器暂停排空，随后单次撤销订单981第二批7/任务6。独立新连接确认40件与1415.54美元商品款释放、121.16运费及四笔原回款/第一批不变，未改变原发布失败事实。

本次控制器只补固定恢复入口：

```powershell
deploy\deploy.bat --recover-outbound-activation <reviewed-plan.json> --prepare-only
# 同一固定控制候选、原应用revision/release_id/journal SHA核验后正式执行。
```

计划仅接受 revision、release_id、journal_sha256。检查原九项完成记录、精确迁移链、实际源代码/运行参数/健康、原writer暂停状态、全部静态摘要、原出库制品/模式/指纹及基线。恢复只激活原已安装的出库制品，核验后恢复原writer、邮件worker和维护任务；不重跑DDL、应用启动、静态切换或业务出库请求。原始检查点先归档，已存在尝试回执拒绝重发；失败应查实际阶段后决定下一步。
