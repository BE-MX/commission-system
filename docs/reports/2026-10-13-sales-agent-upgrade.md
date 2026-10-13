# 旧研究任务收尾与专用Agent更新

用户明确授权“同时核验并收尾旧任务，再更新Agent”。固定范围为task251/customer628及北京专用ark-sales-agent；主平台a7d39aaa/schema195保持，不更新原通用Gateway、不开放自动队列或邮件发送。

## 实际任务收尾

现场任务为private-enrichment-v1/full_research，行业门控已接受但industry_relevance=uncertain，Run267与全部客户事实均0，租约已过期。原门控保留了一条未获可靠来源佐证的第三方目录线索，不能据此确认商业主体。已在云端0700目录保存原任务、Run/事件、正式账号/事实/档案版本及模型配置，文件0600；只输出脱敏摘要。

使用原用户90云端token #11，通过现有API一次claim过期任务、一次complete。claim增加generation至3、attempt至3，旧Run267取消并留存，新Run268生成；业务input_snapshot和task_fingerprint保持。完成使用本次新Run/hash/token与原分级，research_gap_v1明确说明现有线索不足，不提交claims或citations。

实际读回：task251 completed/research_gap_v1、result_review_status=not_required、Run268 completed、租约清除；原industry_gate嵌套保留。客户账号/事实/档案版本逐字相同，正式账号SHA256仍8b4ff692fba08e4878f3554e0d6413b6bd475b4081bdc0f52d02a8f02b22ee88，事实0。旧Run266失败和267取消均保留。真实登录读取客户补全接口200，结果为资料不足、无事实，不将其称为成功补全商业档案。

## 专用发布

固定deployer/runtime为3c7448cca2bb9ab6c12c22e358f861e0243cd060，包含最新main业务代码及受审部署修复。统一deploy.bat专用入口依次pause原a9、prepare/configure/verify新版本、model复用云端原配置、activate/verify-active，七阶段及最终退出均0。各阶段有独立意图与结果文件，未知结果只读核验，不自动重发。

修复了两个已发现的入口限制：新controller暂停旧runtime时核验实际unit、旧模型ready/runtime/config/key/地址及heartbeat0m，不拿新版业务制品和旧版作无意义字节比较；其他阶段继续严格制品校验。增加--sales-agent-reuse-model，与私有文件互斥，从暂停前保存的旧ready与云端0600 key恢复原模型，拒绝证明或key漂移。configure的模板模型不能被当成已授权模型；复用后仍执行一次最小健康探针，再写新ready及激活。

原mimo-v2.6-flash、原地址与key摘要均未变；最小模型探针请求/响应型号一致并通过。云key不搬到办公室或开发机。旧token7原本inactive，发布没有再退休；token11及其哈希/标签/状态保持，未另行发放凭据。Gateway实际active/enabled、RPC passed、heartbeat0m；没有自动消费其他研究任务。

## 实际验收

- 部署/来源/边界回归59 passed、1 POSIX项在Windows跳过；MCP/研究契约/策略17 passed；diff检查通过。完整约定仍有原17项发票UI基线问题。
- 独立审查确认租约重领、新hash/Run、严格分级、profile保留和云模型复用边界。探针没有通用未知状态自动恢复，实际只调用一次；异常将保持暂停并只读检查。
- 实际以ark-sales用户运行安装版SDK/stdio MCP，工具列表包含research_gap_v1，真实读取task251 context=completed、gap_contract=research_gap_v1。安装MCP源码归一化SHA256为81212caf8ca8af374c4f970cfba04b5e7c7c00d43b8d4e14aa6841c7c9a4e90b。
- 新配置MCP路径和实际运行版本均3c7448cc；没有90:* running研究任务。主平台与既有邮件禁用状态保持。

证据：主目录与办公室.deploy_state/sales-agent-followup-20261013，包含受管候选、七阶段日志/意图/结果、脱敏任务及最终验收摘要；云端同名目录保存受保护原始快照。没有将云端私有备份或密钥加入仓库。上述部署阶段未推送origin；后续用户明确授权将生产运行代码、195历史及Agent部署修复整合回main并推送，保留主目录已有修改。本次Git交付不重复生产部署或模型探针。

收尾清理：本轮已结束的Windows调度helper已按实际exit0注销，日志及恢复资料保留；云端claim恢复文件中的已结束租约明文已移除，只保留SHA256及原任务/Run身份。原配置私有备份保留用于回滚，不复制到开发机。
