# 提成批次计算排序规则修复与发布

2026-10-07，批次 `2026-3` 执行计算误报数据库连接失败。修复已按用户授权合并、推送并部署到办公室和北京后端，真实批次只读验证通过。

## 根因和修复

批次 ID 10、日期范围 2026-07-01 至 2026-09-30，状态为草稿。共享 MySQL 连接正常，旧待计算回款查询报 1267：运费排除条件对 `synced_payment.order_id` 使用 `CAST AS CHAR`，引入连接排序规则 `utf8mb4_0900_ai_ci`，与运费应收订单 ID 列的 `utf8mb4_unicode_ci` 冲突。全局数据库异常处理将它显示为连接失败。

两个字段实际均为 `VARCHAR(64)`、`utf8mb4_unicode_ci`，删除多余转换、直接比较列即可。提成金额规则、运费排除、日期范围及已计算回款去重保持原逻辑，无数据库迁移。

## 验证

- 捕获实际计算查询并按 MySQL 编译的回归测试在旧代码先失败，修复后通过；SQLite 本身不能复现 MySQL 1267。运费排除测试同时确认普通回款仍正确计提，运费不产生明细或已计算标记。
- 提成计算、批次状态机、回款同步隔离测试 **48 passed**，合并后再跑 **48 passed**；独立审查无阻断问题，增量约定和 diff 检查通过。测试仅使用内存 SQLite。
- 办公室和北京实际计算函数源码摘要均匹配候选（归一化 Windows/Linux 换行）。两端真实批次只读诊断均得到待计算回款 **2,045** 条、候选提成明细 **1,125** 条、客户归属不完整跳过 **920** 条、缺快照 **0** 条、计算错误 **0**。
- 诊断通过数据库只读事务和 SQLAlchemy 非 SELECT 拦截，在第一条明细 INSERT 发送前停止，再 rollback。前后复核均为 `draft`、提成明细 **0**、已计算标记 **0**。未发送计算 POST 或替用户提交实际计提。

## 发布证据

应用候选：`77fec60cf2173039bc30732a0b2e969b385bc857`。在 Codex 分支提交并整合最新 main，在主工作树快进合并，推送 origin 后远端完整 SHA 回读一致。

办公室实际安装目录 `D:/commission-system` 的统一入口：

```bat
set DEPLOY_NO_PAUSE=1
deploy\deploy.bat --revision 77fec60cf2173039bc30732a0b2e969b385bc857 --no-pull --prepare-only
deploy\deploy.bat --revision 77fec60cf2173039bc30732a0b2e969b385bc857 --no-pull
```

准备和发布均退出 **0**；release_id=`e377cc72330848fa9beb9c9054cdd6a0`，status=`succeeded`，scope=`office-and-cloud`，`deferred=[]`。两地实际 HEAD 均为候选、工作区干净、health=`ok/connected`；运行 OpenAPI 含 `/api/v1/commission/batch/{batch_id}/calculate` 的 POST。

共享 schema 保持 `173_task_center`，`schema_changed=false`，无 DDL。主站、PM 和客户素材制品未变化，静态传输0字节；两地主站和 PM 共9项公网入口/JS摘要匹配候选清单，含提成批次资源。出库调度原状态 active/enabled 恢复，邮件 Worker 保持 inactive/disabled、MainPID=0。

未配置 DNS/TLS 的 PM 云域名、仓库外 hair/video 和其他未纳管独立服务不计作本次发布。本轮没有启用原已停用服务或发布平板、小程序。

准备/发布日志、两端健康与真实批次诊断、公网文件核验、原23项改动的备份恢复证据位于主目录 `.deploy_state/commission-collation-release/`。仅本任务的源码、测试和文档进入提交；主目录原有改动完整保留。文档收尾提交记录发布事实，生产应用仍为上述固定候选。
