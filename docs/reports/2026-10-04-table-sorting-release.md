# 表格布局与排序合并发布

2026-10-04，用户授权“合并推送部署”。**已合并推送；部署未完成，停止在准备阶段，未切换线上服务。**

## Git 与验证

- 应用候选：`4bcde7c2a339c7bf878421753ab2e973cdd6c220`。功能提交 `c8db3d82`，整合最新 main `e0978269` 的悬浮横向滚动条后，在主目录快进 main 并推送 origin，远端 SHA 回读一致。
- 59 个文件冲突全部在 Codex 工作树解决；独立审查确认 122 个 Vue 文件与原排序实现经过新版表格规范化后的结果完全一致，排序字段/事件与滚动条均保留。
- 合并后主站/PM 构建、174 表排序巡检（遗漏 0）、严格增量约定、UI 门禁、diff 检查通过。排序定向 10 项、审计 6 项通过，审查另复验排序/树表 7 项与发票 11 项。
- 浏览器重跑桌面 1440/768/390、全屏、跨页排序、组合列、键盘及多层树排序通过，无 JS 错误。完整实现验收与既有 6 项地图测试基线失败见[验收报告](2026-10-04-table-layout-sorting.md)。

## 部署结果与阻塞

- 从办公室 `D:/commission-system/deploy/deploy.bat` 固定同一候选执行两次 `--no-pull --prepare-only`，均退出 1，未进入正式激活。
- 发布范围 `office-and-cloud`，release_id=`5732ce8bb9744a47a5e9885997b3b5bd`；本轮 `publish-current.json` 状态 `failed`，`completed=[]`。旧 `publish-success.json` 不能作为本轮成功证据。
- 办公室服务/依赖、数据库、字体与文档渲染、后端导入预检通过；主站、PM、公网/内网 PM 制品构建成功。北京后端与色块候选准备成功，schema=`173_task_center`、`schema_changed=false`。
- 阻塞发生在北京邮件 Worker OAuth 查询：部署器报 `Mail worker deployment failed: sudo failed with exit 7`。按同一服务账户、工作区及候选 CLI 只读查询确认 `+me` 返回 `ok=false`、错误码 **429**、`Request rate limit exceeded, please retry later`；间隔后再次查询和完整预检仍失败。
- 未删除恢复记录、未绕过账户验证、未冻结出库或邮件服务、未执行共享数据库迁移，也未激活任何云端静态候选。
- 收尾回读：办公室实际 HEAD 仍为 `acdec9d9067b91d8bb8ff4ab25daa94f61bd025e`，北京实际 HEAD 仍为 `1542e47ec8ab8711db9f2c1510bf487cb26449cf`；两地 `/health` 均 `ok/connected`。北京后端、邮件 Worker、出库 timer 均 active；Worker 此时账户认证查询受同一限流影响，不能宣称邮件健康已通过。

## 恢复入口

邮件平台限流解除后，在办公室安装目录继续同一候选与完整范围，保留现有 release_id 与状态：

```bat
set DEPLOY_NO_PAUSE=1
deploy\deploy.bat --revision 4bcde7c2a339c7bf878421753ab2e973cdd6c220 --no-pull --prepare-only
deploy\deploy.bat --revision 4bcde7c2a339c7bf878421753ab2e973cdd6c220 --no-pull
```

先确认准备退出 0，再执行正式发布；发布成功后核验本轮状态 `succeeded`、线上版本、两地主站与 PM 文件摘要。原“合并推送部署”授权持续覆盖同一候选的恢复，不需重复审批。既有未开通的 PM 云域名与仓库外 hair/video 不属于已登记发布目标。

本机证据与恢复材料保存在 `.deploy_state/table-sorting-release/`：原主目录 23 项改动指纹与原始补丁、stash SHA、两次准备日志、当前失败/旧成功记录、候选构建清单、合并验证日志及待发布后运行的公网摘要核验脚本。主目录原有改动另行恢复并校验，不包含在应用提交中。
