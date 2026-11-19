# 2026-10-19 最新 main 全量部署：订单发票缺货筛选

已拉取并固定当时最新 `origin/main`：`ec76a177394488cfe26af20c870e492d1164cc96`，从生产原版本 `e01194d06252d0b1bfe016a731dd986612095990` 经候选自身的 `deploy/deploy.bat --live-root D:/commission-system --revision <SHA> --no-pull` 完成办公室和云端完整受管发布。

- 发布 ID：`8ff2856e81674f82b1613466cb54c15c`；2026-10-19 北京时间 18:41:10 启动正式入口，18:47:32 退出，耗时 381.594 秒（约 6 分 22 秒）。部署任务退出 0，`publish-current` 为 `succeeded`，`publish-success` 与两地实际 Git 均匹配固定 SHA，11 个受管目标完成，发布锁已释放。
- 数据库实时读回为 `198_customer_media_playback`，本次候选无新增迁移且 `schema_changed=false`；未复制、覆盖或降级数据库。
- 办公室 CommissionSystem、WhatsAppConnector、ArkOfficeHttps 正常；北京 ark-backend 正常。Scheduler 办公室 true、北京 false；出库 timer 仍为 active/enabled，发布回执 verified 且保留原基线；邮件 Worker 保留 inactive/disabled。
- 内网主站与五个公网静态入口的 index 摘要均与服务器制品一致，入口脚本核验通过。两地 `/health` 返回 HTTP 200、数据库 connected。
- 两地 OpenAPI 均注册 `/api/invoice/invoices/{invoice_id}/editor-inventory`，实际入口引用的 `InvoiceManage-C4i66TN_.js` 均包含「仅显示库存不足的产品」和缺货行样式类；chunk SHA256 均为 `b1b68879f126731cf49aafe786b24031a3410ff24c21d873e5309175313e44fa`。这证明代码、接口和页面制品已安装；未对真实订单制造保存或出库操作。
- 2 秒探针观测的连续 HTTP 不可用区间：办公室内网约 28.126 秒，北京公网约 12.070 秒；采样保守外框分别约 30.220 / 14.182 秒，不视为毫秒级停机边界。部署完成后办公室 SSH 转发曾不可用；恢复后只读取本轮最终状态，没有再次发布或重启服务。
- 本次一次性任务 `ArkFullMainEc76a17720261019` 已导出定义并移除。资源与候选清理按现有部署机制保持 deferred/pending，未执行历史资源删除。未纳管的 pm.leshine.cloud、hair/video 及终端安装不计作本轮上线目标。
- 开发主目录原有 66 个未提交文件在写本报告前全部 SHA256 核验不变；交接仅在原内容前追加发布记录。本报告和本次交接更新未提交、未推送。

证据目录：`.deploy_state/full-main-release-20261019-ec76a177/`，含 delivery、Office/Beijing evidence、feature-readback、static-verification、measurements、task-cleanup、task-export，以及 `server/full-main-release-20261019-ec76a177/` 中的原始日志、任务结果与连续探针记录。`local-preservation.json` 保存原本地文件保护结果。
