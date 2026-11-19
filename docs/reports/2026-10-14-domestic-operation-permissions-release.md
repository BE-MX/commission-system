# 2026-10-14 内贸代报工与异常跳过权限完整生产发布

- 用户授权：合并、推送及部署。实现提交、本地 main、origin/main、远端 main 与两地实际应用 HEAD 均为 `7f503ca2620ca62345547fce08f17c55aa9b887a`。发布前工作站与办公室重新 fetch，固定该最新 main。
- 统一入口：办公室受管候选 `deploy/deploy.bat --live-root D:/commission-system --revision <上述完整 SHA> --no-pull`，先 prepare-only，再正式发布。发布身份 `d14b39fb2fcf4b5593f53fd9d295319e`；两个阶段 exit_code=0，publish-current/success=succeeded，deferred=[]，发布锁已释放。
- 范围：办公室/北京后端、两地主站、登记的 PM、素材及客户门户目标；两地主站各 210 个变化文件，制品 `e994130400252404f2ec36bf7cb021b724882b190ab79fad3346d2e6d9e38577`。其余三个静态制品不变。出库轮询器完成版本核验、timer active/enabled；邮件 Worker 保持 inactive/disabled。未纳管服务及未开通域名沿用部署清单边界，不冒报升级。
- 数据库实际为 `196_domestic_commission`；本次无新增迁移，schema-writers=completed。新权限由应用启动 seed 登记，无真实报工、人工跳过、订单、收款或角色授权写入。

## 新权限与线上验证

- `domestic_report:write`，权限 ID 2001：主站代报工、代报工选人及撤销报工。
- `domestic_skip:write`，权限 ID 2002：异常跳过、审计记录及撤销跳过。
- 两项均为 domestic/action，普通角色授权关联为空，未给既有 admin 或业务员角色自动补授；super_admin 保留平台豁免。角色管理分别显示“内贸订单代报工”和“内贸订单异常跳过”，显式分配后重新登录刷新权限。小程序报工、原订单数据范围、撤销他人报工的管理约束不变。
- 办公室回环、leshine.work、leshine.cloud 三处 /health 均 200、database=connected；使用数据库实际身份构建五分钟短 token，只执行 GET，不输出 token。两类新权限相关的工人列表/跳过审计接口，super_admin 均 200，未授权的原业务员角色均 403；三处权限目录均返回新码。
- 两地 auth/service、domestic/router、domestic/report_service 三份关键源码与提交逐字规范化匹配。两地主站 index、DomesticOrders、RoleManagement、PermissionMatrixTab 共 8 项公网文件 SHA256 与本轮构建一致；订单按钮和权限矩阵制品包含新码。
- 最终静态保留 status=succeeded，办公室与两主域均完成，保留当前及回滚资源；发布后重复上述只读验证通过。

## 验证、保护及收尾

- 本地隔离 SQLite 联合后端 172 项通过；补充管理员撤销参数后专项 39 项通过（不重复累加）；前端相关 14 项、npm run build、独立审查及覆盖本提交基点的严格约定检查通过。构建保留既有混合导入/大分包提示。
- 主目录 47 个既有修改/未跟踪文件有完整备份及 SHA256 清单；45 个保持原 SHA256，两份重叠文档保留原内容并只加入本次权限说明。index 与未合并路径为空。原保护 stash 已在核验后删除，文件备份仍保留。
- 两个本轮持久部署任务已核验退出并清理，日志及回执保留。临时 worktree 文件及 Git worktree 登记已移除；残留空目录与已合并本地分支的清理命令被自动审批/工具策略拦截（仅返回 blocked by policy），暂保留，没有独有改动。
- 本报告与主目录交接追加为本地生产证据，不自动混入他人未提交文档；实现代码与 API 契约已随 7f503ca2 推送。此前管理员创建发货批次候选为空的问题不在本次权限拆分范围。

证据：`.deploy_state/domestic-permissions-release-20261014/`，包含固定计划、备份清单、准备/正式退出回执、生产只读 readback、两地源码摘要、最终保留状态及任务清理回执。Git 巡检为 --no-fetch 本地快照。主目录全量 diff 检查命中原有 deploy/README.md 文件末尾空行，该文件与保护备份 SHA256 一致；本次交接与 API 文档的局部检查另行通过。
