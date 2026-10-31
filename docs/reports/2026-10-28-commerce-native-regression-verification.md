# 原生业务最终集成回归与权限补查

日期：2026-10-28。对象：`codex/commerce-transition` 本地开发工作区；本报告只覆盖下述实现与验证，没有提交、推送或部署。

## 已修复的业务缺陷

| 项目 | 实际失败证据 | 修复与复核 |
| --- | --- | --- |
| 目录主数据撤权后仍可写 | 旧JWT携带catalog:write，数据库仅catalog:read；原产品创建、SKU创建/更新/停用均200并改数据。产品更新首轮请求缺active返回422，补完整有效body后验证授权拒绝，不把它伪称独立红证 | 5个POST/PUT首读前使用native_authority.require_write，GET采用current_reader且保持原任一权限列表；业务service不变。7项真实HTTP正/反例通过，独立代理完成最小diff复核 |
| 提成配置仍信旧JWT | 已撤commission/customer写权限，旧JWT仍可读取pending/policy，并实际写policy或resolve basis；4类原入口均200 | 两个GET、两个POST使用对应原permission的实时读/写授权；保留原提成计算与配置权限合同。4项反例均403、快照和原basis不变；与其他原生HTTP共31项通过，独立diff复核通过 |
| 生产供货候选泄漏旧客户订单 | 实际HTTP先显示1条供货候选；客户转给他人后原员工仍读到total=1 | 在count/page前叠加已有local_invoice_scope，使用production:write和既有invoice:read_all语义；历史sales/delegation条件保留。移交后total=0、items为空，历史Invoice.sales_user_id不改；独立diff复核通过 |

## 测试前置修正

旧候选测试已更新为当前协议，并保留其业务断言：每个HTTP请求使用新事务、用户权限写入真实DB；本地订单正向配置真实super_admin角色，负向仍检查JWT与实时授权；资金管理增加伪JWT管理员不能财务确认的反例。

非USD售后场景现在从首次制单、银行原款登记开始使用CNY，账户币种和canonical银行身份一致。原USD/CNY配置产生冻结USD汇率0.14285714，20元对应2.85714280美元；后续修改配置不会回写原凭证。没有通过改写已确认USD本金来伪造CNY场景。

提成历史快照的created_at、updated_at和operated_at与合成业务日一致；另增加“业务日之后才录入的快照必须待显式resolution”反例，保留小额冲回合计归零。原零主管费率在构造历史快照时冻结，避免测试更新触发今天的onupdate而制造历史倒填。

旧“全局local环境下连policy也不能读”的测试已改为实际安装local_only策略及真实Session：允许读取协调门禁，错路线仍拒绝；交易镜像、provider HTTP和后台旧发送会话均为零。当前订单执行器对本地单直接拒绝，不调用已停用旧预占入口绕过协议。

## 最终证据

- 完整41个文件的唯一集成运行：**433 passed，35 warnings，185.27秒，无skip**。文件清单：`tmp/transition-final-backend-cases.txt`；最终日志：`tmp/native-final-aggregate-v3.log`。警告为既有JWT/Starlette弃用及Query.get兼容提示，未隐去失败。
- 目录权限红/绿：`tmp/catalog-live-authority-red.log`、`tmp/catalog-live-authority-green.log`（7 passed）。
- 生产客户范围红证：`tmp/production-customer-scope-red.log`；HTTP修复合并绿证：`tmp/native-final-http-green.log`（18 passed）。
- 提成权限4类红证：`tmp/commission-live-authority-red.log`；当前HTTP合并绿证：`tmp/native-final-live-http-v2.log`（31 passed）。
- 14个本任务Python文件编译与空白检查通过；Git巡检已执行`--no-fetch`，证据`tmp/native-final-git-sweep.log`，只代表本地引用快照。

上述各测试组重叠，不相加成更大的“总通过数”。433项使用隔离SQLite及合成输入，证明本次领域/接口协议；真实MySQL完整迁移、RR并发、独立子进程验证和浏览器路径由总验收报告分别记录，不用本组结果替代生产业务验收。
