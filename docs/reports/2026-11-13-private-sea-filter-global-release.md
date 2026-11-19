# 私海筛选栏修复与最新主分支全局发布

用户明确授权拉取最新 Git 代码并全局部署。本次已通过统一 `deploy/deploy.bat` 入口发布完成；主目录其他任务的未提交代码未进入发布候选。

## 发布结果

- 最新主分支及已部署提交：`24d2cb6fc7b1050ca8bfa579599e1a73d24cb6f9`。开始时 `git pull --ff-only origin main` 确认已是最新，结束时远端 main 再次读回相同提交。
- 原生产版本：`e868f077039add1611ef564e90fc5e0d4538cd87`；办公室和北京实际 Git HEAD 均已读回新提交。
- release_id：`df90230b56fd474399b2430617455c7e`；发布回执 `status=succeeded`，执行退出码 0。
- 共享数据库仍为 `262_invoice_customer_sync_log`，本次无新增迁移。
- 完成办公室与北京后端、两地色块路由及五个登记静态目标：新加坡主站、北京主站、新加坡 PM、北京客户素材、北京客户下单门户。未变化制品由发布器验证后复用。
- 出库轮询器回执 `verified`，timer 为 active/enabled；邮件 Worker 保留原 inactive/disabled 基线。

本次除私海筛选栏修复外，也包含已提交的 WhatsApp 同步授权锁修复、跟进结果必填与统计口径调整、过去日期跟进录入修复。PDA/小程序终端安装或发布、未登记站点及独立服务升级不属于本次服务器发布结果。

## 验证

- 发布前后共享迁移恢复记录无未完成事故；候选在独立受管源码中准备，未把开发目录未提交修改复制到生产。
- 暂停两地公网与办公室直连的相关生成入口后，复查两台后端线程栈均无活动图片生成任务；设计图片队列无 queued/running。展会的一条 7 月旧 generating 记录保持原样，没有为发布篡改业务状态。
- 办公室 Caddy、防火墙临时规则及北京/新加坡 Nginx 入口均已恢复；三处配置摘要与发布前基线一致，临时防火墙规则已确认不存在。
- 发布后独立检查 **28/28 必需项通过**，涵盖实际源码、服务、数据库、两条办公室业务隧道、公网 API 鉴权及登记站点。
- 办公室、`leshine.cloud`、`leshine.work` 均返回 `/assets/main-BFa2MOUe.js`。三处 `ClientDesk-2DuYyKx0.css` 摘要一致，且包含 `position:static;top:auto;z-index:auto`，证实筛选栏修复制品已上线。
- CSS SHA256：`40f7666b669d1de79757785fe73b611e521e53e555716f7abe863d913e2fceb2`。两公网主站健康接口均返回 `status=ok/database=connected`。
- 桌面与窄屏的真实组件模拟数据滚动验收及 22 项私海前端测试已在修复阶段通过；生产阶段验证版本、制品和服务，没有代做业务写入。

## 运维边界与证据

- 发布器按默认策略将历史静态/候选清理登记为 deferred；没有执行另需维护授权的历史资源删除。办公室静态预备校验耗时约 7 分 42 秒，准备期间原服务持续运行；不能将此耗时当作停服时长。
- 邮件 Worker、project-radar-bot、旧新加坡 okki-sync 的停用/缺失状态及无探针的独立服务仅作为现状报告，没有自动启用或冒充更新成功。
- 本次两个一次性部署计划任务已删除。发布回执、日志、还原证据和截图验收材料保留，不清理其他任务产物。
- 发布证据：主目录 `.deploy_state/global-release-24d2cb6f-20261113/`，含 `final-publish.json`、`final-success.json`、`postcheck.json`、`public-frontend-proof.json`、`office-final-proof.log`、各入口恢复日志和部署日志。修复阶段材料：`tmp/private-sea-filter-scroll-check/`。
