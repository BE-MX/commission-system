# 运费退款发布的出库激活恢复控制器

本次原应用版本 `b817650a69a6865886c9f4d7a0c61bc1ec9ec807`，release ID `6d6683095e704b818c90d3db43b1c57d`。schema 246→247 已执行，两个后端、两个路由及五个静态站已完成，最后出库激活因 `Outbound mode control cannot be confirmed` 失败；迁移日志为 `upgraded`，出库回执为 `installed_paused`，原 timer 基线 active/enabled。

现场只读确认 timer inactive/disabled、service MainPID0，Node/mysql2 读得连接 ID 为 number、命名锁 owner 为 null、mode legacy、schema247。同一原部署 `ModeFence` 后续 ready/check/released 全部通过。这只能证明当前门禁可用，原失败时的锁/协议根因仍未确定。

在既有 `--recover-outbound-activation` 入口增加唯一受审映射：本次完整 revision、release ID、精确原 schema246 和 pending247。计划仍仅接受 revision、release_id、journal_sha256。保留历史204映射，不支持任意版本参数恢复。

恢复前验证原日志摘要、九项已完成记录、真实代码/应用运行参数/健康、schema、五站及办公室静态摘要、全部 writer 暂停状态、原出库制品/模式/数据库指纹及调度基线。原恢复尝试回执存在时拒绝重发。恢复只续行原出库激活与核验、关联 writer、邮件 Worker 和维护调度；不重复 DDL、应用启动、静态切换或退款业务操作，不修改模式或伪造原成功记录。

31 项恢复测试通过，覆盖两个受审检查点及错版本、release 混配、迁移链、已激活状态、缺失阶段和原日志摘要。增量约定与 diff 检查通过；独立审查无阻断。

执行时使用固定新控制器候选的 `deploy/deploy.bat --live-root D:/commission-system --revision <controller SHA> --recover-outbound-activation <plan> --prepare-only`，准备核验后去掉 prepare-only。原应用版本与 release ID 保持不变。实际执行结果及线上金额验收见后续发布报告；本文件不声明恢复已经执行成功。
