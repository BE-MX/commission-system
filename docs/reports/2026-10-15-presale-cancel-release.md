# 2026-10-15 预售结算手工取消与最新 main 生产发布

## 版本与范围

用户授权“合并推送然后拉取远端的全局最新代码进行部署更新”。`codex/presale-cancel-actions` 提交 `a0e0f434`，接入远端最新 main 后，在主 worktree 合并为 `1c0d424423227b469fe959a13c26a17d3cf7d6f9`，已推送 origin/main。重新 fetch/pull 后本地与远端一致。办公室再次 fetch 后固定同一候选，经候选目录中的 `deploy/deploy.bat --live-root D:/commission-system --revision <完整 SHA> --no-pull` 执行完整受管发布。

生产原版本为 `220632a3`；本次同时包含 main 已有的发票联系信息/运费录入优化、WhatsApp 安全诊断和结算取消功能。没有新增迁移，生产 schema 仍为 `196_domestic_commission`。发布身份为 `8a3a1e0fbf6c449dbf4f8605fddef5d8`。

准备与正式发布均 exit_code=0，完整 11 项完成、deferred=[]。办公室、北京后端、两项既有受管路由及五个静态目标均完成核验，出库轮询器和邮件 Worker 恢复原基线。资源保留清理三处 succeeded，发布锁已释放；两项临时执行任务经真实退出码核验后已删除，日志、候选与回滚材料保留。

## 使用与保护

在订单发票的分批出库/结算窗口选择原失败批次，点击“取消本批次”并填写原因。对于缺货等明确失败且没有远端出库身份、租约、基线或确认历史的批次，服务端先 GET 查询精确原编号；仅规范查无单后，再重新授权并核对原版本、资金和任务绑定，最终一次事务取消结算/任务并释放占用。查到远端单据或查询不确定时保持原状态，不能强制释放。

原回款、失败证据和审计保留。取消成功后刷新可用数量与资金池，再由用户调整产品数量、重新创建下一批。暂停继续保留占用，不能用暂停替代取消。实际付款、已绑定运费、执行中、结果不确定或已出库的保护保留。

## 独立验证

- 办公室和北京实际 HEAD、发布涉及的 13 个应用源文件规范化 SHA256 与固定候选一致；应用进程在源码安装后启动。办公室两个 NSSM 服务正常，北京 ark-backend/ark-colorwork active。
- 办公室回环、leshine.work、leshine.cloud 的健康检查均 HTTP 200/database=connected，三入口鉴权读取 Janny 结算均成功。最新失败批次 ID 5/version 3/state=review_required 返回 `actions.cancel.allowed=true` 和 `requires_remote_check=true`；历史 ID 3/4 保持 cancelled。本轮未提交取消或新建出库命令。
- Janny-KC-1001 的发票、33 行明细、1 笔回款、3 个结算、3 条资金应用、2 个出库任务和 10 条审计的全字段指纹与发布前一致。没有改变订单金额、原回款或现有批次。
- 办公室及两域主站的 index 和 InvoiceManage 脚本均与本次构建 SHA256 一致；PM、素材、客户门户的公开 index 与各自构建一致。主站制品 `932f8c53ffaab4ebabaf4436c9f8ebddbd39b693c9f751751eb47a1c5b4a7df1`。
- 办公室 Scheduler/WhatsApp 自动同步开启，北京关闭；门户经营写入、PI、通知、邮件和门户出库门禁保持原值。北京出库 timer 恢复 active/enabled，回执 verified/release_confirmed=true；邮件 Worker 保持 inactive/disabled。Connector 健康检查 HTTP 200/provider=baileys；没有建立账号授权或发送消息。

## 回归与边界

实现阶段 SQLite 联合回归 144 项、Node 回归 19 项、桌面/手机共 10 个浏览器场景、前端构建及独立审查通过。新增实际 MySQL 取消专项 15 项全部通过；扩大状态回归遇到旧手续费断言，在未修改的 `220632a3` 独占实例上复现同一创建阶段失败（bank_charge 实际 0、旧断言期待 2），未弱化断言或修改无关费用逻辑。接入最新 main 后补跑后端专项 24 项和 Node 19 项通过，覆盖本次提交的严格约定检查通过。

主目录原有 47 个文件先备份再合并，除两份重叠文档保留原内容并插入本次说明外，逐文件 SHA256 一致。交付后仅同步本次 API/交接与发布记录，未夹带其他修改。原 `deploy/README.md` 末尾空行导致未提交工作区整体 diff 检查提示，属于已保留的既有修改；本次提交差异检查通过。

完整证据位于工作站及办公室 `.deploy_state/presale-cancel-release-20261015/`，包括原始 main 补丁/文件副本/SHA256 清单、候选、两地基线/运行读回、准备/发布日志和最终回执。专项测试的 MySQL 数据目录和原版本源码快照因前一轮自动审批拒绝删除而保留，未改用其他工具绕过；本任务 worktree 保留这些恢复材料。

完整受管发布覆盖登记目标；未登记的 pm.leshine.cloud、外部权威源码的 hair/video 和各终端安装沿用 `deploy/platforms.json` 的边界。独立 Agent/MCP 服务没有在本次被声称为新版本发布。真实手工取消和重建的业务验收仍由用户操作完成。

发布后 API、交接和本报告在主目录同步，保留未提交 diff，未将其他人的文档整理夹带进本次推送。
