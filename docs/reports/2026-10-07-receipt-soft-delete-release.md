# 回款软删除核验修复与发布

2026-10-07，用户要求优化 `Rina-KC-1001` 的删除核验逻辑并合并推送部署。修复已上线办公室与已登记云端目标，真实订单的只读删除预览阻碍为空。

## 根因与修复

订单 ID 869、原小满订单 `105824479044988` 的出库已完成删除，回款 `105824479304117` 已在小满 `removed=1` 列表，有效列表不存在，但详情接口仍返回原单。旧实现要求详情消失，误将该回款标为删除结果未知；预览又因详情与有效列表不一致阻止接续。

新增回款删除证据核验：详情仍可读时，以其更新时间查询同秒完整有效/删除窗口，两轮结果须一致，原 ID 仅在删除列表中，并匹配原订单、币种和更新时间；最后回读详情确认核验期间没有变化。超过100条、缺字段、重复ID、窗口范围错误、列表变化、关联变化或网络错误均不能证明删除。明确 Not Found 仍需有效索引无原ID。财务 `collect_status/enable_flag` 不作为删除状态。

预览、未知步骤接续和本地账本归档均使用这一证据。已发送的未知请求只核验、不重发；原金额、手续费、附件、远端ID与审计保留，没有新表或迁移。未扩展回款页独立“核实远端删改”流程。

## 验证与 Git

- 应用候选：`9e7b3876c1a44861f1ab6db57bf3e32981245c8d`。在 Codex 分支提交，在主目录快进 main，推送 origin 后远端 SHA 回读一致。本需求仅改7个文件。
- 两条完整软删除回归先在旧实现失败，再随修复通过：正常删除后详情仍可读，以及原未知步骤接续不重复 POST。
- 相关删除联合隔离测试 **106 passed**，合并后再跑 **106 passed**；独立审查无阻断问题，另复验新增两个文件 **17 passed**。严格增量约定及 diff 检查通过；既有 jose.utcnow 弃用提示不影响结果。
- 候选 helper 发布前对真实回款只读核验通过；没有生产业务写请求。本次无前端改动，部署器核验并复用主站/PM缓存摘要。

## 生产发布与收尾

在办公室实际安装目录 `D:/commission-system` 使用统一入口，准备和正式发布均退出 **0**：

```bat
set DEPLOY_NO_PAUSE=1
deploy\deploy.bat --revision 9e7b3876c1a44861f1ab6db57bf3e32981245c8d --no-pull --prepare-only
deploy\deploy.bat --revision 9e7b3876c1a44861f1ab6db57bf3e32981245c8d --no-pull
```

- 发布状态 **succeeded**，release_id=`a9f06404f03b497b9452a4f547fb0770`，scope=`office-and-cloud`，`deferred=[]`。两地实际 HEAD 均为候选 SHA、工作区干净，`/health` 均 `ok/connected`；运行 OpenAPI 保留删除 GET/POST。
- 共享数据库仍为 `173_task_center`，`schema_changed=false`，没有 DDL。两地主站、PM和客户素材制品未变化、零静态传输；三域9项公网文件SHA256与候选清单匹配。PM/Pantone基础数据检查没有重灌既有资料。
- 出库回执 verified，原 timer active/enabled 已恢复。邮件 Worker 制品更新至候选，但保持 inactive/disabled、MainPID=0，未恢复持续邮件请求。
- 北京执行真实 `Rina-KC-1001` 的删除领域预览，使用原操作人当前数据库授权、原范围与状态保护，诊断进程限制 SQL 为 SELECT 并回滚临时事务；没有执行删除 POST 或业务写入。结果：`blockers=[]`，有效出库/回款均为空，保留一条原本地账本和步骤 `outbound:105824479447228=done`、`receipt:105824479304117=uncertain`。主订单尚未删除，可从订单发票“继续删除”确认后接续。
- 未配置 DNS/TLS 的 PM 云域名、仓库外 hair/video 及未纳管独立服务不计作已发布。

生产核验、prepare/publish日志、原23项改动备份与恢复材料位于主目录 `.deploy_state/receipt-soft-delete-release/`；原始诊断和候选只读证据在 `.deploy_state/rina-deletion-debug/`。主目录原有改动独立恢复和逐文件校验，不夹带提交。文档收尾提交仅记录发布事实，生产应用版本保持上述候选。
