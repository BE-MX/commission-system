# 2026-10-14 物流跟踪分页修复发布

用户授权合并 main、推送并部署。发现最新 main 含此前内贸提成迁移 196，生产仍为 195、569 个存量客户尚无提成配置表；独立审查确认完整升级会要求存量客户先配置提成才能创建新业务订单。用户随后明确选择仅上线分页，暂不发布内贸提成。

## Git 与发布范围

- 修复提交 `b08912f1b959636752c78d1334ecf667e366159f` 已合并推送；从生产 `974bfd8a36fc2e12697fe8780a550b6e704fee96` 创建仅改 `frontend/src/views/tracking/tracking-list.css` 的发布提交 `3e5e7ad6c4592a3ce7d4fe142c60aa7e1ef900f7`。
- 发布历史合入 main 并推送，main/origin/main 均为 `d009b2c95a691a60b89fad7c5131cb0362551d38`，包含上述两项提交。后续完整 main 升级可以正常快进，本次没有删除已合并的内贸功能。
- 主目录原有 43 个未提交文件已保存状态、二进制 diff、文件副本与 SHA256 清单；除交接文档保留全部原内容并追加本任务记录外，逐文件摘要相同，index 与冲突路径为空。
- 初始完整 main 只执行 prepare-only，未激活、未迁移。正式操作固定仅分页候选，通过办公室受管 `deploy/deploy.bat --live-root D:/commission-system --revision <3e5e7ad6完整SHA> --no-pull`，准备与激活采用同一发布身份 `d2d10f998f814637a7ac0a6d7b79bd1c`。

## 验证

- 生产基线上的实际 MainLayout/TrackingList 模拟运单回归：1440×900、1366×768、1024×600、390×844 全部通过，覆盖普通翻页、每页100条与全屏翻页。严格约定检查、构建与 diff 检查通过；构建只有已有分包/混合导入提示。此前 main 候选的内贸提成隔离 SQLite 回归24项、Node回归3项通过，不等于本次发布内贸功能。
- 两站实际线上静态制品浏览器回归：1366×768、390×844，普通翻页、每页100条、全屏各通过，无页面异常。全部 API 被拦截为模拟数据，不执行真实订单操作；首次 cloud 的 load 等待超时，经 HEAD 200 及 DOMContentLoaded 条件复核后通过。
- 办公室及两主域健康均200、database=connected；同一有效身份的物流列表只读 GET 均200，第一页返回20条。两域 index、TrackingList CSS、JS共六项SHA256均与发布制品匹配。
- 共享数据库仍为 `195_main_portal_merge`，两张内贸提成表仍不存在，客户计数仍569；没有执行迁移196、历史提成回填或业务单据写入。
- 办公室实际 HEAD 为3e5e7ad6，两个NSSM服务运行；北京后端代码未变，实际HEAD保留974bfd8a且服务active。出库timer仍active/enabled，邮件Worker仍inactive/disabled。PM、素材、门户制品未变。固定静态页面、独立服务与终端沿用部署清单的既有边界。

## 发布退出回执

仅分页候选的准备与正式部署均 exit_code=0；publish-current/success 绑定本轮 revision 与 release_id，deferred=[]。静态资源保留 status=succeeded，office、leshine.work、leshine.cloud 全部完成；发布锁已释放，持久任务回到 Ready。

证据与恢复材料：主目录 `.deploy_state/tracking-pagination-main-20261014/`（保护备份、Git、候选传输、浏览器与只读核验），办公室 `.deploy_state/tracking-pagination-release-20261014/`（准备/正式日志、发布退出回执与readback）。
