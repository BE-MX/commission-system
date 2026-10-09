# 订单详情加载优化发布记录

2026-10-09 按用户“合并推送部署”授权执行。功能提交 `5f4219f3` 与最新主线 `019e1471` 整合，固定应用候选 `9bdbc5f3d2c0389b8ebaf2a6c00e46ef50a6a1ec` 已合入并推送 `origin/main`，远端回读一致。

## 发布范围

回款首次读取短时完整核验快照，出库精确读取本地镜像并批量获取关联状态，刷新保留单据；有效检验提交完成即计入已出库。保留主线当前状态异常判断与出库问题入口。资金写入、结算与原单状态不变。

办公室 SSH 转发恢复后，在生产安装目录执行 `deploy/deploy.bat --revision <候选> --no-pull --prepare-only`，预检退出 0，再以同一候选正式发布退出 0。`release_id=61ca506f06e440b8bbc513ddecf27e66`，状态 succeeded、范围 office-and-cloud、deferred=[]。主站两地静态制品更新，PM 与客户媒体未变化并复用；数据库仍为 `175_receipt_recovery`，没有 schema 变更。

## 验证

- 合并候选后端相关隔离回归 229 项通过（41.82 秒，14 条既有 JWT UTC 弃用警告），前端相关 12 项通过，构建 3412 模块、19.65 秒；增量约定/UI 门禁和 diff 检查通过。
- 独立 agent 对自动合并的权限、检验进度、当前异常状态与回款刷新契约审查通过，另独立运行 56 项详情回归通过。
- 办公室及北京实际 HEAD 均为固定候选，`health={status:ok,database:connected}`，已注册详情 GET 接口。
- 两地 8 个后端详情源码文件 SHA-256 与候选一致（包括新增镜像与回款快照模块）；20 项公网主站、导航清单、详情及 PM 前端文件摘要一致。
- 出库 timer 保持 active/enabled，邮件 Worker 保持 inactive/disabled/MainPID=0。未纳管及未开通站点沿用部署清单，不将其计为本次更新。

主目录原有 24 项未提交改动已备份并逐项核验保留。预检、发布、office/beijing/public/backend 验证 JSON 与保留核验在 `.deploy_state/invoice-detail-speed-release/`。Git 巡检使用 `--no-fetch` 本地快照。上线后仅做只读版本、健康与制品核验，未制造真实业务单据；功能交互验收使用隔离数据。本文为发布后记录，不改变已验证的应用候选。
