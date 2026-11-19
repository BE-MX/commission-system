# 2026-11-04 最新 main 全局生产发布

用户授权“拉取最新git代码，进行全局生产部署”。最终固定并发布最新远端 main `59f93e79e3d20f8217799cfbf0f200e32c93e45c`，办公室与北京均已独立读回一致；结束前再次查询 origin/main 仍为该版本。

## 最终结果

- 统一入口：办公室 `deploy/deploy.bat`，范围 `office-and-cloud`。发布ID `9f5e677aa9f7499f801f30c505708242`，publish-current为succeeded，必需目标deferred=[]。
- prepare与activate退出码均0，耗时分别445.80/244.34秒；这些是阶段耗时，不是停服时长。办公室主站正式构建20.87秒，PM/门户内容未变化，校验复用。
- 部署器按已登记writer清单冻结写入，由受限迁移身份执行一次249→250，最终schema-writers=completed，唯一head为`250_client_desk`。独立读回四张新表均存在且0行；未手工迁移、stamp或downgrade。
- 两地每处8份关键源码LF归一化SHA256均匹配固定候选。独立26项必需后检全部通过，`leshine.work`、`leshine.cloud`、`pm.leshine.work`、`media.leshine.cloud`、`shop.leshine.cloud`均HTTPS200且证书校验通过；公网API正确拒绝未登录请求。
- Scheduler办公室启用、北京关闭，保持单活。出库timer已恢复active/enabled，持久回执completed、API回执verified，同revision/release_id且release_confirmed=true、protocol2。邮件Worker仍inactive/disabled，新加坡旧okki-sync仍inactive/masked。

## 本轮上线与开关边界

先成功发布`7b1248d8`的充值凭证粘贴和Kubai导航图标。准备收尾时远端合入私海助理`59f93e79`，继续纳入同一“最新代码”目标，完成第二个固定候选发布，过程没有混用release身份。

私海助理代码、路由、权限及四表结构已发布，**保持关闭**。办公室与北京的候选配置及上线后实际Settings均为CLIENT_DESK_ENABLED=false，试点用户数0、供应商白名单数0；办公室最新启动日志未注册本模块自动任务。四张新表0行，本轮没有开通试点、模型调用、早报发送或旧入口下架。真实五日评测、两周试点及模型/钉钉经营验收仍依原实施边界另行执行。

## 验证

- 新增版本定向后端35项，加共享WhatsApp权限与Scheduler回归19项，共54项通过；数据库变量指向哨兵地址，测试使用隔离SQLite，不连接生产写入。
- 前端12个相关文件64项通过，覆盖私海controller、充值凭证、导航图标/权限/布局及校验；跨7b基点strict conventions和diff检查通过。首轮Node因依赖链接放错目录而未加载Vue，纠正链接后完整64项通过，失败日志保留。
- 独立只读审查确认Alembic唯一head250、父249；迁移仅新增四表/索引/FK，无既有业务表DML或回填删除。四表MySQL dialect DDL离线编译通过，用户外键unsigned一致，active_slot生成列/唯一索引正确生成。已有开发阶段真实隔离MySQL验证见私海助理实现记录，不冒充本轮重新执行。
- 迁移前独立检查四张目标表均不存在；迁移后独立检查四表存在且为空、schema250和关闭配置。源码默认值未被当作生产配置证据。
- 本轮未人工创建订单、充值、审批、检验、私海分析或发送消息。统一入口的迁移与常规bootstrap按既有部署流程执行。

## 限制、并发和恢复证据

- Computer Use的node_repl与mcp__cua_repl均Transport closed，无法进行生产登录态页面验收或截图。生产版本、关键源码、制品摘要和独立健康后检已验证；隔离浏览器结果不冒充生产登录态验收。
- 办公室原有2223维护映射两度中断。用户恢复后先读回同一服务器/原后台任务状态，没有重发prepare或迁移，未放宽SSH认证与主机指纹。
- 主目录发布期间发生其他任务并发提交/编辑，较首次快照有文件内容变化，已记录于local-preservation-final.json并保留当前内容；没有回滚这些变化，也未把未提交文件打进发布候选。仅更新本次发布报告与交接，文档留本地未提交。
- 未纳管服务、未配置域名、独立终端安装仍按deploy/platforms.json边界，不计入本次已更新成功。静态历史/候选维护保持部署器deferred，未额外清理业务数据。
- 证据 `.deploy_state/full-main-release-20261104-59f93e79/`：固定请求、独立审查路线、54项后端/64项前端、preflight、候选开关/schema-before、prepare/activate/readback、postcheck、runtime-verified、writer-readback和final-summary。第一阶段证据在7b目录；办公室同名目录保留完整运行日志及退出码。
