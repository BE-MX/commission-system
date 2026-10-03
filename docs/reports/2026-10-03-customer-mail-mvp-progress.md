# 客户邮件 MVP 验收进度

状态：正式发布完成，真实 AI 生成业务校验待排障；主站收发闭环未完成。

## 发布与范围

- 正式候选 `af6ed58ad4ced486a4acf4da0b556c2d15a42abc`；用户已完成北京邮箱 OAuth。办公室受管候选的统一 deploy.bat 完成 prepare-only 与完整发布，成功回执为 `.deploy_state/publish-success.json`；日志在 `.deploy_state/mail-worker-transfer/authorized-prepare.log`、`authorized-publish.log`。
- office/cloud 同版，schema `173_task_center` 无迁移，deferred 为空；出库调度原状态保留；邮件 Worker 已运行并通过身份、授权和健康核验。
- 绑定 id=1，owner=1，邮箱 `leshinehair@agent.qq.com`，identity/workspace 均为 `ark-mail-beijing`。两端发送开启但白名单仅 `86muliang@163.com`，没有授权向真实外部客户发送。
- 本机通道烟测在 sent 查到 `msg_qwSDabvobnoChUvAayV4mC-1B_G1CPVKPtGB23IZcgfncw`；这不是主站队列验收证据，也不代表收件人收到。

## 当前验证

- 既有后端邮件及客户事实/获客回归 183 passed；来源权限与配额补丁另跑 34 passed。前端 46 passed；部署相关 57 passed；Node Worker 15 passed；构建成功。
- 线上 UI 已确认发送限制、邮箱 active、Worker ready、心跳与监听正常。
- 真实 AI 请求返回 HTTP 200，草稿业务 API 返回 400：`AI 输出缺少主题或正文，草稿未生成`。没有落空草稿或发送任务。模型未就绪且返回空正文时，修复为向用户保留缺项原因；页面显示服务端安全错误。新增回归先失败后通过，生成测试共 15 passed。
- customer=25（已有背调样例 haircare.group）的 contact=1 标记为“牟亮亮（方舟内部验收，非客户联系人）”，来源核实说明明确不代表任职或采购关系。其 buying_role=unknown，不能伪造采购角色绕过生成校验。结束验收后通过收件人维护 API 将 contact_allowed 改为 false。

## 尚待完成

1. 发布生成反馈修复后核验模型的实际缺项，补齐真实依据或提供符合语义的内部测试路径；不得弱化生产资格门禁。
2. 在主站生成并审阅草稿，审批一次仅发向验收地址的任务；核验队列唯一、通道接受与 sent 对账。
3. 用户回复实际测试邮件后验证收件事件关联、人工分类和后续停发。
4. 清理本次内部测试联系资格，同步最终结果。

未推送 origin、未合并 main。保留任务工作树、受管候选、发布回执、配置备份和构建证据供继续。
