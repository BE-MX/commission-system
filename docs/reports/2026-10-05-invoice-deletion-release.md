# 订单发票自动删除合并发布

2026-10-05，用户授权“合并推送部署”。已将订单发票一次确认自动删除功能合入 main、推送 origin，并通过统一部署入口完成办公室与已登记云端目标发布。

## 用户行为

管理员在已同步或取消中的订单发票点击“删除/继续删除”，确认一次关联范围后，系统依次处理对应待出库、小满回款、未发送本地回款和小满订单。原发票、回款金额与手续费、凭证、验货、审计资料取消归档保留，不执行退款。

完整范围、权限和确认版本在发送前复核；逐步记录删除意图与结果。部分完成可继续，远端结果未知时只核对、不重复发送。预售或汇总批次、共享出库、已出库、库存预占和其他执行中或未知任务会给出阻碍原因。

本轮没有对 `Rina-KC-1001` 或其他真实业务单据执行删除；生产验证为健康、接口声明和静态资源读取。

## Git 与验证

- 应用候选：`8cbde90d9c4606e0bc1cf3e5116ff5724021e3f6`；功能提交仅包含本需求 14 个文件。在 Codex 工作树提交，在主目录快进 main 后推送，远端 SHA 回读一致。
- 合并后受影响后端联合回归 **89 passed**，前端 Node 回归 **16 passed**；严格增量约定与 diff 检查通过。既有 jose.utcnow 弃用提示未影响结果。
- 实现阶段真实组件浏览器模拟 **5 场景通过**，无页面错误；独立审查发现的 3 项问题均已修复并补回归。最终本地生产构建通过；办公室固定候选主站构建 **20.08s**，PM 制品通过缓存摘要核验。构建仅有既有大 chunk 和混合导入提示。
- API 与生命周期文档同步，本次没有数据库结构迁移。

## 完整生产发布

在办公室实际安装目录 `D:/commission-system` 执行以下统一入口，准备和正式发布均退出 **0**：

```bat
set DEPLOY_NO_PAUSE=1
deploy\deploy.bat --revision 8cbde90d9c4606e0bc1cf3e5116ff5724021e3f6 --no-pull --prepare-only
deploy\deploy.bat --revision 8cbde90d9c4606e0bc1cf3e5116ff5724021e3f6 --no-pull
```

- 发布状态 **succeeded**，release_id=`10690e46a8944b37b9770c52ba89870e`，scope=`office-and-cloud`，`deferred=[]`。办公室应用和静态站、北京后端与色块服务、两地主站、PM 公网/内网站及客户素材完成更新或核验。
- 两地实际 Git HEAD 都是应用候选 SHA，工作区干净；两地 `/health` 均 `status=ok`、`database=connected`。
- 两地运行中的 OpenAPI 都包含 `/api/invoice/invoices/{invoice_id}/deletion` 的 GET 与 POST，确认新版预览和执行接口已注册。
- 从公网读取 `leshine.work`、`leshine.cloud`、`pm.leshine.work` 共 **9 项文件**，包含页面入口、主脚本和 InvoiceManage 资源；全部 SHA256 与候选清单一致。两地主站 artifact=`db64e611c016846437044b00dc5e96e7cc1c9331d81bd1579fe3a45b3636d8fe`；PM 制品保持已验证摘要。
- 共享数据库仍为 `173_task_center`，`schema_changed=false`，无 DDL；PM/Pantone 幂等基础数据检查没有重灌既有资料。
- 出库回执 `verified`，原 timer 的 active/enabled=true 已恢复。部署日志沿用 `singapore-outbound` 完成项名称，实际受管服务归属北京，收尾 systemd 核验为 active/enabled。
- 邮件 Worker 制品更新为应用候选 SHA，但普通发布保留先前停用基线；回执 `running=false`，收尾 systemd 仍 inactive/disabled、MainPID=0。未重新启用邮件请求，也未宣称既有 429 限流已解除。
- 既有 PM 云域名未配置 DNS/TLS、仓库外 hair/video 和未纳管独立服务不计作已发布。

本机证据及恢复材料保存在 `.deploy_state/invoice-deletion-release/`：准备和发布日志、两地版本/健康/API/调度核验 JSON、9 项公网资源摘要、浏览器模拟结果及截图、原主目录 23 项改动备份和 stash SHA。原有改动独立保存，不包含在本次功能或发布文档提交中。文档收尾提交仅更新发布记录与交接状态，生产应用候选仍为上述 SHA。
