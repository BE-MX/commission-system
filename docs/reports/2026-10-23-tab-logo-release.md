# 方舟浏览器标签页 LeShine LOGO 发布

2026-10-23，按用户“部署”授权，fetch 后固定远端最新 main `6fbf8a8c5cf9fe88e2abdff81577e6caef93763a`，通过候选自身的 `deploy/deploy.bat --live-root D:/commission-system --revision <完整 SHA> --no-pull` 完成完整受管发布。

- 发布 ID：`be9a6811e4d3465abe6815a10b2c40eb`；入口北京时间23:45:13–23:51:39，退出0。11个受管目标完成、`deferred=[]`；发布锁已释放。
- 主站 favicon 从 `/vite.svg` 改为现有 `/logo.webp`，登录和主站各路由共用。公网 `leshine.cloud`、`www.leshine.cloud`、`leshine.work` 的HTML均声明新图标；图标HTTP200、Content-Type为image/webp，SHA256均为 `16631c74765b6517d72033b3a888f4232048da636b0adf73776be8fd20574d2e`，与源图一致。旧标签页如保留图标缓存，可关闭后重新打开。
- Office与北京实际Git HEAD均为候选；办公室工作区干净，北京受管checkout及backend-success已回读。公网三入口HTTP/数据库健康正常，北京实际数据库版本仍为 `202_presale_order_revision`，无DDL。
- 办公室CommissionSystem、WhatsAppConnector、ArkOfficeHttps均Running。出库调度active/enabled恢复true原基线；邮件Worker保持不运行。未纳管服务及pending站点不计为已更新。
- 发布器依默认协议将静态/候选制品清理登记为后续维护，本次未另行删除生产制品。一次性发布任务在终态核验并导出后已移除。
- 原有82个本地修改文件在写入本记录前逐一SHA256核对相同；未夹带进发布候选。本次仅新增此报告及前置交接记录，留未提交差异。

证据：`.deploy_state/tab-logo-release-20261023-6fbf8a8c/`，包括生产预检、完整入口日志、两地版本及schema回读、独立健康探针、图标摘要、任务清理回执。此验证确认资源和服务已上线，未操作业务订单、资金或发送消息。
