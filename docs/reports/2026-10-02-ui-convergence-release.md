# 设计规范四阶段合并与发布

日期：2026-10-02。亮哥明确授权“合并推送部署”。本次发布应用候选为 `6afaf0b47bc43a74a6ab7b70918d1cd9d822b2cf`（`feat(ui): converge list resources and shared design contracts`），由 `codex/list-filter-behavior` 在主worktree快进合入main并推送origin。应用版本固定于该SHA；本页及交接状态是发布后的纯文档记录，不另作应用切换。

## 合并与保护

- 合并前fetch确认main与origin/main同为`80f973f4`，没有额外分叉；任务分支已独立审查并完成前端验收。
- 主目录其他15个文件的SHA256保持完全一致；唯一重叠的`docs/handoff.md`先用独立stash保存，合并后3-way恢复成功，仍保持原`25新增/2删除`的无关diff。恢复备份和指纹保存在主目录`.deploy_state/ui-convergence-delivery/`，没有夹带其他任务内容提交。
- 合并后的主目录生产构建通过，113项导航；`check_conventions.py --strict --base 80f973f4`通过。任务最终全量1185项中1179通过、6项既有登录Canvas mock失败，隔离HEAD复现相同6失败；未删测试或宣称全量绿。

## 统一入口结果

通过已配置`office-prod` SSH在服务器`D:/commission-system`调用正常入口，先执行`deploy/deploy.bat --revision <上述SHA> --prepare-only`，预检成功后执行同SHA正式发布。未使用旧`git push cloud`发布流程，没有手工启动业务进程、修改部署器或绕过迁移/锁保护。

- 最终进程退出0，回执为 **MANAGED APPLICATION RELEASE COMPLETED**。
- `release_id`：`77bbe018598147a1867a59b715454681`；范围`office-and-cloud`，`deferred=[]`。
- 共享数据库仍为`173_task_center`，schema未变化、迁移跳过。PM与Pantone幂等初始化均确认已有数据并跳过。
- 北京出库轮询器回执`status=verified`，调度`active=true / enabled=true`，恢复原运行状态。
- 准备期两地主站各350个变化文件，增量2,247,210bytes；正式激活复用已准备制品，额外传输0。两地主站制品摘要均为`ba876dc982cc0a01aa55316d15d13208d293b734703e97b3b85df9cc649b4a10`。

| 目标 | 实际结果 |
| --- | --- |
| 办公室应用及局域网静态站 | 已更新并由入口验证服务/HTTP/数据库健康 |
| 北京后端 | 后端内容无需变化；候选及共享schema检查通过 |
| 新加坡`leshine.work`主站 | 新静态制品激活、入口HTTPS摘要校验通过 |
| 北京`leshine.cloud`主站 | 同一新静态制品激活、入口HTTPS摘要校验通过 |
| PM站与客户素材静态站 | 制品未变化，完整发布核验通过 |
| 色块模块与两地路由 | 候选准备/激活检查与路由验证按正常入口完成 |
| 已登记出库轮询器 | 固定候选摘要验证通过，调度恢复为启用/运行 |

独立MCP、Agent、OpenClaw、n8n等非本次纳管应用更新对象未盲目升级；`pm.leshine.cloud`缺DNS/TLS、hair/video权威源码等既有pending目标保持原边界，没有列作已更新。

## 发布后公开核验

额外执行12次公开HTTPS读取，覆盖两个域名各自的HTML、导航清单、主脚本、ComponentShowcase JS/CSS及health：

- 两个域名各文件SHA256完全一致，主脚本和样例文件名对应办公室固定候选构建日志；导航清单和样例CSS字节亦与本地已提交源码构建一致。
- 两站HTML摘要均为`afc661669beb62e983670b998ad884e454f52f246a878f0510f64da7c9f5c983`，实际主脚本`assets/main-B6IrZ4qA.js`；样例JS含“组件与交互样例”。
- 两站`/health`均返回`status=ok, database=connected`；`.work`按已验证拓扑核验办公室后端，`.cloud`核验北京后端。
- 发布器已经按其候选摘要验证HTTPS。额外后检的本地Python TLS客户端出现EOF，改用保持证书校验的Windows curl完成公开核验；没有关闭TLS或SSH主机密钥校验。
- 发布成功后新的办公室SSH连接出现banner timeout，额外的手动journal读取未完成。没有重复发布、重置隧道或删除锁；保留成功发布的真实stdout及公开健康证据，不把此管理连接问题伪称为应用失败或已修复。

原始本地证据：`.deploy_state/ui-convergence-delivery/prepare.txt`、`deploy.txt`、`public-verification.json`、合并/构建/约定输出及原文件指纹。实现验收和截图已受Git管理，见[最终验收](../requirements/2026-10-02-ui-convergence-acceptance.md)与[资源账本](../requirements/2026-10-02-list-resource-coverage.md)。未执行生产业务写入型UI验收；发布成功不替代所有角色/实体手机的人工验收。

## 交付与清理

发布记录从本任务所属分支提交，再在主目录合并推送；其他未提交文件保持原样。已将本任务忽略的夹具、测试输出、截图、隔离HEAD基线和恢复材料保留到主目录`.deploy_state/ui-convergence-delivery/`；本任务合并后工作树与本地分支按项目约定清理，旧工作树、旧stash及其他代理成果未处理。
