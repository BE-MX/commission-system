# 生产更新：源码分叉与迁移链修复

## 现场证据（只读）

办公室安装目录 `D:/commission-system` 的 main 为 `5ae1f07bc01cc9d51979acaf4fe643a5071e154d`，上游为 `698dd57f4590a4c5992e43f8544eb636c6d5a053`，ahead 1 / behind 8，工作区干净。独有提交为出库删除对账快照限流修复。最近成功发布记录同样指向5ae1f07b，办公室 CommissionSystem / WhatsAppConnector 均运行。

`deploy/source_release.py` 的 `merge-base` 判断正确检测到两边不是祖先关系，因此源码准备失败；本次报错未到服务切换或数据库迁移。已拉到远端 Git 对象不代表生产代码已更新。

共享数据库 `alembic_version` 为 `163_okki_presence_days`；战报投递表不存在，work_dates / poster_push_enabled 列也不存在。schema-writers 恢复记录为 completed。远端战报功能有另一条以162为父的163，因此仅解决Git分叉仍会触发multiple heads。

## 本地候选

- 从远端698dd57f真实合并5ae1f07b，保留双方提交祖先及代码。不能cherry-pick后丢失生产祖先，不能reset生产HEAD。
- 已部署 `163_okki_presence_days` 和出库对账业务代码逐字保留。
- 尚未上线的 `163_battle_posters` 顺延为 `164_battle_posters`，父版本改为 `163_okki_presence_days`；原战报DDL不变。更新测试及文档引用。
- fast-forward、干净工作区、单迁移头、writer冻结及统一发布入口的检查保持不变。

## 验证

- 新回归在修复前复现两个迁移头；修复后唯一head为164，从生产163只执行164，从162依次执行163和164。
- 内存SQLite实际执行待迁移脚本后，已有出库快照记录逐列完全一致，战报投递表新增成功；保留原战报数据测试及MySQL离线DDL验证。
- `backend/tests/test_battle_poster_migration.py`、`test_outbound_presence_migration.py`、`test_outbound_delete_presence.py`、`test_battle_posters.py`：81通过。
- `deploy/tests/test_source_release.py`：8通过；`test_merge_migration_plan.py`：12通过，覆盖办公室/北京两条预检路径从已部署163仅规划164。
- 独立只读审查未发现阻断问题：已部署出库代码与迁移逐字保留，战报实际DDL只改版本标识及父版本；不放宽部署保护、不stamp。
- 增量约定检查0项，完整门禁仍是9项既有UI行数基线过期；不调整无关基线。无前端代码改动。

## 发布边界

用户已授权将修复合并到主目录main并推送origin/main，本轮不部署。生产上只执行了Git/服务/状态读取和数据库SELECT/结构查询，未写入数据、停启服务或执行迁移。修复提交 `467f4ef1` 同时包含生产 `5ae1f07b` 和远端 `698dd57f` 两个祖先；合入并推送后，服务器可重跑原 `deploy/deploy.bat`，由统一入口完成准备、164迁移和切换；不能用 `--no-pull` 来假装更新，也不能删除发布状态记录或stamp数据库。
