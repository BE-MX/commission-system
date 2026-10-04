# 表格布局与排序合并发布

2026-10-04，用户授权“合并推送部署”，随后明确要求“先停止持续请求，完成生产环境部署”。**已合并推送并完成办公室与已登记云端目标发布；邮件 Worker 按授权保持停用。**

## Git 与验证

- 应用候选：`4bcde7c2a339c7bf878421753ab2e973cdd6c220`。功能提交 `c8db3d82`，整合最新 main `e0978269` 的悬浮横向滚动条后，在主目录快进 main 并推送 origin，远端 SHA 回读一致。
- 59 个文件冲突全部在 Codex 工作树解决；独立审查确认 122 个 Vue 文件与原排序实现经过新版表格规范化后的结果完全一致，排序字段/事件与滚动条均保留。
- 合并后主站/PM 构建、174 表排序巡检（遗漏 0）、严格增量约定、UI 门禁、diff 检查通过。排序定向 10 项、审计 6 项通过，审查另复验排序/树表 7 项与发票 11 项。
- 浏览器重跑桌面 1440/768/390、全屏、跨页排序、组合列、键盘及多层树排序通过，无 JS 错误。完整实现验收与既有 6 项地图测试基线失败见[验收报告](2026-10-04-table-layout-sorting.md)。

## 首次预检记录

- 从办公室 `D:/commission-system/deploy/deploy.bat` 固定同一候选执行两次 `--no-pull --prepare-only`，均退出 1，未进入正式激活。
- 发布范围 `office-and-cloud`，release_id=`5732ce8bb9744a47a5e9885997b3b5bd`；本轮 `publish-current.json` 状态 `failed`，`completed=[]`。旧 `publish-success.json` 不能作为本轮成功证据。
- 办公室服务/依赖、数据库、字体与文档渲染、后端导入预检通过；主站、PM、公网/内网 PM 制品构建成功。北京后端与色块候选准备成功，schema=`173_task_center`、`schema_changed=false`。
- 阻塞发生在北京邮件 Worker OAuth 查询：部署器报 `Mail worker deployment failed: sudo failed with exit 7`。按同一服务账户、工作区及候选 CLI 只读查询确认 `+me` 返回 `ok=false`、错误码 **429**、`Request rate limit exceeded, please retry later`；间隔后再次查询和完整预检仍失败。
- 未删除恢复记录、未绕过账户验证、未冻结出库或邮件服务、未执行共享数据库迁移，也未激活任何云端静态候选。
- 首次停止发布时回读：办公室实际 HEAD 为 `acdec9d9067b91d8bb8ff4ab25daa94f61bd025e`，北京实际 HEAD 为 `1542e47ec8ab8711db9f2c1510bf487cb26449cf`；两地 `/health` 均 `ok/connected`。当时邮件 Worker 仍 active，账户查询受同一限流影响。

## 按授权暂停请求并完成发布

- 已保存原邮件服务状态（active/enabled）后执行 `systemctl disable --now ark-mail-outreach`，优雅停止并取消开机自启。停用后 `MainPID=0`、`ActiveState=inactive`、`UnitFileState=disabled`，`pending_receipt=false`；没有删除待发任务、邮箱数据、OAuth 或回执。
- 在办公室安装目录继续同一候选、同一 release_id 与完整范围，以下准备和发布均退出 0：

```bat
set DEPLOY_NO_PAUSE=1
deploy\deploy.bat --revision 4bcde7c2a339c7bf878421753ab2e973cdd6c220 --no-pull --prepare-only
deploy\deploy.bat --revision 4bcde7c2a339c7bf878421753ab2e973cdd6c220 --no-pull
```

- 本轮 `publish-current.json` 为 **succeeded**，revision=`4bcde7c2a339c7bf878421753ab2e973cdd6c220`，release_id=`5732ce8bb9744a47a5e9885997b3b5bd`，scope=`office-and-cloud`，`deferred=[]`。办公室、北京后端与色块、两地主站、PM 公网/内网站及客户素材均按登记目标完成更新或核验；不是仅准备成功。
- 办公室与北京实际 Git HEAD 都是应用候选 SHA，两地 `/health` 均 `ok/connected`。两地运行中的 OpenAPI 确认主管关系、客户归属接口均声明 `sort_field` 与 `sort_order`。
- 两地主站静态制品 artifact=`72126aba6a285d2d965c7b57bf5f7e21865457cf788c513f9700510477af45dd`；PM artifact=`41a70e1c7c810e7f2ee2065d0876917148215edfb47e66335b8ecbcb4188a112`。从公网核验 `leshine.work`、`leshine.cloud`、`pm.leshine.work` 共 **31 项文件 SHA256** 与固定候选清单完全一致，包含入口及主管关系/客户归属/PM 任务资源。
- 共享数据库仍为 `173_task_center`，无 DDL；PM/Pantone 幂等基础数据步骤没有重灌既有资料。出库回执 verified，原 timer active/enabled=true 已恢复。
- 邮件 Worker 新制品与 unit 已更新为应用候选 SHA，部署入口按既有规则保留停用基线，最终回执 `status=verify`、`running=false`；收尾另查 systemd 仍 inactive/disabled、MainPID=0。没有把邮件账户限流声明为已解除，也没有重新启用持续请求。
- 既有未开通 DNS/TLS 的 PM 云域名、仓库外 hair/video 和未纳管独立服务不计作已更新。

## 后续邮件运行状态

邮件轮询、同步和待发任务目前暂停。恢复前需修复 429 退避和账号总调用预算，再按平台返回的等待时间做单次账户验证；目前 CLI 未返回恢复时间。后续恢复服务需要覆盖该动作的授权，不能因下一次普通部署自动启用已停用的 Worker。

本机证据与恢复材料保存在 `.deploy_state/table-sorting-release/`：原主目录 23 项改动指纹与原始补丁、stash SHA、首次失败记录、停用前后状态、`prepare-paused-mail.log`、`publish-paused-mail.log`、本轮成功回执、两地 HEAD/健康/API 契约及 `public-file-verification.json`。主目录原有改动另行保存、恢复并校验，不包含在应用或发布文档提交中。
