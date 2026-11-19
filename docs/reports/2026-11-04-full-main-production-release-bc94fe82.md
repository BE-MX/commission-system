# 2026-11-04 最新 main 全局生产发布

用户授权“拉取最新的git代码，全局部署到生产”。本轮从origin拉取并固定最新main `bc94fe8242570b2f9ec04dba6f762818810389c0`，通过办公室项目统一入口 `deploy/deploy.bat` 完成 `office-and-cloud` 发布。

## 发布结果

- 原办公室及北京版本 `09ea5c2aaf48850c769450cdf069f69287ea1a31`；最终两地Git HEAD均独立读回为 `bc94fe8242570b2f9ec04dba6f762818810389c0`。
- 发布ID `917451dce3ea4e7fab95581fb472338d`，publish-current状态 `succeeded`，必需目标 `deferred=[]`。
- prepare退出0，628.75秒；activate退出0，244.28秒。时间包含完整准备、验证、传输与切换，不是停服时长。主站构建19.20秒；PM与客户门户内容未变化，由部署器校验复用。
- schema由唯一head `248_navigation_config` 升至唯一head `249_followup_revisions`。部署器统一冻结登记writer、执行迁移并恢复原状态，schema-writers最终 `completed`。独立只读确认历史表存在，archived_at/send_claimed_at均为nullable datetime；没有手工stamp、downgrade或重跑迁移。
- 独立后检26项必需检查全部通过：两地应用/数据库、办公室转发、公网API鉴权、Nginx与受管服务，以及五站HTTPS/证书。

## 本轮上线内容

相对原生产版本包含122文件的已合并变更：

- 出库报价先连续分页枚举、再读取详情、最终核验完整ID集合；已知列表并发变化返回明确409重取报价，技术坏数据仍503，不自动重发。
- 订单改量与已保存同步任务自动续跑、共享库存锁排队、原出库安全补齐及页面只读观察，未知发送继续保留原责任。
- 9610快递渠道及付款方式双向校验；内贸参考图粘贴上传。
- 客户跟进管理总览、潜在客户筛选、已提交编辑/不可变历史、截图归档及发送租约；迁移249为本模块新增结构。
- 导航源图标、快捷任务悬停反馈及玻璃材质角标修复。

没有夹带本地main独有测试提交及主目录未提交内容。没有为了验收创建、取消、重发订单/出库，或登记回款、提交检验、发布导航配置。

## 验证证据

- 固定干净候选的后端相关回归454 passed；Node前端17个相关文件212 passed；真实独占MySQL92 passed，共758项。
- MySQL包括真实249迁移与并发编辑、订单续跑、库存排队及后台worker。测试先构造相应领域前置结构，不冒充完整历史迁移链重放；本次实际生产迁移仍由发布器检查248→249并执行。
- Node首次在候选缺依赖、缺experimental-vm-modules参数时失败；安装锁定依赖并使用项目测试所需参数后全部通过。中间日志保留，未削弱测试或修改产品代码。
- 跨生产基点的严格约定检查与diff检查通过。独立发布审查确认249为纯新增结构、无业务数据回填/删除/改型，要求迁移先于新ORM启动，两地整体切换。
- 两地四个风险相关源码文件按LF归一化的SHA256与固定候选一致。办公室最新启动日志确认 `invoice_linked_pending` 已注册；办公室Scheduler启用、北京关闭，保持原单活。
- `leshine.work`、`leshine.cloud`、`pm.leshine.work`、`media.leshine.cloud`、`shop.leshine.cloud` 均HTTPS 200，证书校验通过。
- 北京出库回执verified、release_confirmed=true、legacy模式、active/enabled，恢复发布前基线。邮件Worker保持inactive/disabled，新加坡旧okki-sync保持inactive/masked。

## 登录态浏览器验收

使用专用Chrome验收标签查看办公室生产入口，用户原标签未改动：

- 订单列表正常载入；侧栏图标外观有区分，悬停工作台导航行时行高亮、快捷任务+可见，没有点击新建任务。
- Veronika第05批结算主状态仍显示“出库待同步”，其中出库状态为“待提交检验”；欠款0.00，404.57美元关联回款已生效。没有取消、重建、重发或提交检验。
- 客户跟进页面和管理总览可加载，勾选“仅潜在客户”后列表载入29条；没有编辑真实记录。
- 导航管理可加载，显示V0草稿已保存、尚未发布；没有编辑草稿或发布配置。
- 打开未保存的新库存单表单，确认DHL普货、FEDEX普货、DHL9610、FEDEX9610可选；未选择真实客户，已放弃并关闭。

页面未显示服务端失败提示；未读取原始网络响应，不能把截图当作零网络错误的证据。截图位于本轮证据目录 `browser/`：invoice.png、sidebar-hover.png、batch05.png、followups.png、navigation.png、carriers.png。此只读验收未重新创建真实发货批次；报价修复上线另有源码摘要和隔离回归证据。

## 范围与保留

- 项目未纳管的独立服务、终端安装和既有待办不冒称完成：pm.leshine.cloud仍缺DNS/TLS；hair/video权威源码与COS迁移原边界保留；无探针的独立同步/代理服务不计入本轮更新成功。
- 静态历史和候选清理由统一部署器登记deferred，未额外清理服务器业务数据。
- 办公室维护SSH最初不可达，使用UU远程“公司WINDWOS服务器”恢复既有2223→远端127.0.0.1:22映射，hostname核实lys-acciowork；未新增认证或网络映射。
- 发布后追加本报告前，主目录129个原修改/未跟踪文件逐一SHA256未变。交接文档随后只前置本次发布记录，原内容保留；报告与交接留本地未提交。
- 本机证据 `.deploy_state/full-main-release-20261104-bc94fe82/`：请求、改动保护、preflight、prepare/activate日志读回、后检、runtime-verified、758项测试日志和独立MySQL关闭日志。办公室同名目录保留完整运行日志与退出码。临时MySQL已Shutdown complete，验证恢复材料保留。
