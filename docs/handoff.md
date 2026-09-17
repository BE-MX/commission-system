# 当前交接与待办

核对日期：2026-09-17。此文件只维护当前可确认状态和继续工作的入口；历史记录完整保留在[交接快照](archive/handoff-2026-09-17.md)，归档不代表其中全部事项完成。

## 2026-09-17 回款与公告（已正式部署，部署器修复待回主线）

- 功能已合并推送至main的9e5cd2dd；原 `codex/receipt-management` 分支与 `commission-system-codex-receipts` worktree已清理。用户随后授权正式部署，办公室、北京及两站主前端已发布固定候选dab19815。迁移156完成，发布和迁移日志分别为succeeded/completed。证据以[发布记录](reports/2026-09-17-receipt-release-fix.md)为准。
- 原币余额包含小满已生效回款、本地占额与自动意图，同远端ID去重；订单锁+幂等键+余额版本+租约令牌防重复。截图仅方舟留存。`RECEIPT_SYNC_ENABLED=False` 默认不向小满写入，启用前核对待发单及 `collect_status=0` 对既有财务/提成的影响。
- 迁移154→155公告→156回款已在生产执行。凭证固定存储仍是待核验的部署配置：办公室主存储、北京代理至leshine.work的方案已实现，但本次未设置或验证生产代理配置、JWT互认、12m入口限额及跨入口图片读取；不得将页面上线等同于凭证链路验收。
- 530项受影响后端测试通过，前端构建通过，CUA本机虚构数据手工创建/上传/详情、暂停提示及390×844窄屏验证通过。独立审查无遗留阻断项；增量规则及diff检查通过；全局规则仍有11项无关UI基线问题；Git巡检已执行no-fetch。
- 合并最新主线后582项集成回归通过、前端构建通过，补齐调度器任务清单，独立集成审查及迁移单head检查通过。验证记录归档主目录 `tmp/receipt-merge-preserve/evidence/`；主目录原设计草稿备份在其上级，其他未提交成果保留。
- 部署阻断修复dab19815仍只在 `codex/receipt-release-fix` / `D:/MyProgram/commission-system-codex-receipt-release` 及办公室受管候选，尚未合并推送origin。后续经授权将修复回主线，避免发布代码与仓库主线长期不一致；不能删除该分支/worktree。当前main的platforms.json仍有旧的writer验证阻断。
- 未完成项：真实租户回款协议/财务口径、生产跨入口凭证联调，以及登录账户菜单权限验收。公告机器人配置与真实发送验收不在本次发布验证范围；未制造回款、公告或群消息。浏览器本轮连接不可用，已核验线上实际制品、接口鉴权与服务健康。


## 仓库集成与环境边界

- main与origin/main的本地引用均为9e5cd2dd；本次仅做no-fetch巡检，未刷新远端。生产已发布dab19815，详见上面的回款/公告条目。
- `codex/shipping-media-owner` 另有2个未合并提交；用途和验收需由对应任务继续核实，不自动合并或删除。
- analysis-mcp、customer-media-thumbnails、deploy-candidate-runtime、domestic-price-save、receipt-release-fix、shipping-upload-limit等worktree存在未提交或未跟踪成果；主目录也有其它任务文件。未合并代码、stash及部署受管候选全部保留。
- 已合并分支的名字不代表整个目录可删；尤其嵌套部署worktree、未跟踪文件和凭据需单独核对。本轮不清理他人成果、不推送、不合并、不部署。

## 继续工作入口

| 事项 | 维护来源 / 证据 |
| --- | --- |
| 回款真实小满发送、财务口径与凭证联调 | [回款实现说明](requirements/2026-09-17-receipt-management-implementation.md) |
| 公告权限、机器人与真实发送验收 | [公告实现说明](reports/2026-09-17-announcement-implementation.md) |
| 部署writer、迁移与恢复 | [部署说明](../deploy/README.md)、实际服务器部署日志 |
| 全仓文档盘点与整理边界 | [整理记录](reports/2026-09-17-project-knowledge-tidy.md) |
| 历史业务待办与未验证事项 | [完整历史交接](archive/handoff-2026-09-17.md)，用模块名/分支名检索；未经复验不标为完成 |

## 本轮知识整理

全仓Markdown已枚举并做正文、标题、链接及重复内容扫描；重点人工核对规范、部署、架构、记忆和交接入口。已修正共享生产库迁移误导和过时发布步骤，建立[文档目录](document-catalog.md)。不将文档整理等同于全部业务代码审计或生产重验。本轮约定检查仍报13项既有UI问题；上文11项是较早实施阶段的检查结果。2026-09-18按用户要求在codex/project-knowledge-tidy分支提交文档整理；主目录原文件保留，尚未合并或推送。
