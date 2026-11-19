# 办公室历史部署材料清理（2026-10-16）

已清理 **162 个历史源码候选、102 个废弃静态暂存副本**，删除逻辑文件合计 **52.73 GiB**。完成核验时间：2026-10-16 12:48:04 +08:00；办公室服务器 D 盘可用 **117.52 GiB**，总容量 292.97 GiB。

## 实际结果

| 对象 | 删除数量 | 删除逻辑大小 | 保留内容 |
|---|---:|---:|---|
| `.deploy_state/sources/<sha>` | 162 | 36.34 GiB | 当前、两级回滚及恢复/配置引用，共 10 个候选，2.63 GiB |
| `.deploy_state/office-next-*` | 102 | 16.40 GiB | 此类废弃暂存目录剩余 0；`office-previous-*` 回滚目录未纳入删除 |
| `.deploy_state/builds` | 0 | 0 | 保留构建缓存，6.33 GiB |

本次清理执行前可用 61.15 GiB，最终可用 117.52 GiB，卷可用量净增加 56.37 GiB。逻辑删除量与卷净变化采用不同口径；卷净变化还受到文件系统分配、元数据及同期正常写入影响。此前 10:26 的存储报告是更早快照，不作为本次清理前基线。

## 如何判定未使用

源码候选逐项检查 Git worktree 注册、分离 HEAD、目录 SHA 一致、属于当前版本祖先、无独有改动或未知忽略文件；业务目录只含 Git 已追踪文件或为空。通过 Git 正式移除 worktree，同时清除注册信息。依赖链接只解除链接本身，不跟随到其他目录。

静态目录均为已完成发布之前产生的 `office-next-(frontend|frontend-pm|pm-lan)-<timestamp>` 暂存目录。正式服务指向 `frontend/dist` 和 `frontend-pm/dist-lan`，HTTPS 代理回源后端；激活流程将暂存目录重命名到正式位置，回滚保存到 `office-previous-*`。检查进程、服务、启用计划任务、部署控制文件及历史元数据，没有候选目录引用；当前发布、资源保留与 schema 状态允许清理，发布锁内再次核验。

33 个静态副本的全部文件与保留构建缓存一致；其余 69 个包含旧版累积资源，按“已废弃且不被服务/恢复引用”的依据清理。删除前保留逐文件 SHA256 和大小清单，并在执行时重新校验；未将“构建缓存未包含旧文件”等同于仍在使用。

## 完成验证与范围

- 两阶段执行回执均 `succeeded`，任务退出码均为 0；全部 264 个目标路径消失，源码注册清理完成。源码剩余 10 个，静态暂存剩余 0。
- 后端与 WhatsApp 服务持续运行，业务监听进程 PID 与清理前相同；数据库健康为 connected。HTTP 主站和内网 PM 返回 200，index SHA256 与正式文件一致。
- 当前/回滚静态摘要、关键环境配置摘要、发布控制记录、Git 分支和远端引用均通过前后核对。没有再次部署或重启业务服务。
- 清理未涉及 WORKSOURCE 业务素材、uploads、数据库备份、Python 服务环境、构建缓存、回滚静态目录或其他代理工作树。
- 发布锁已释放，本次产生的五个临时计划任务已注销，失败尝试和最终成功回执保留。早期执行器错误均发生在删除前，未重复发送不确定的删除动作。
- 本地增量约定检查与文档 diff 检查通过。`python scripts/git_sweep.py --no-fetch` 完成，main 与本地 origin/main 快照同步；既有其他分支、stash 和未提交改动保留，没有借清理动作处理其他代理成果。

## 保留源码及依据

| SHA | 保留依据 |
|---|---|
| `1eef7a2e7472588553ed8f7fb011105b9a7b3d32` | live release |
| `284c399b41b2570d91b778ad0a0c114eaa1fecc0` | recovery/config control: recovery-168-original-publish.json |
| `491f5a621d037a411e8821d46b469b1ab3d1919c` | recovery/config control: invoice-schema-repair-plan.json |
| `86f1c44e530a27ca80acb3e65ab121c47f1995d3` | immediate rollback |
| `8939da1be6fc794a2fe0739f3550c4e92db8315c` | recovery/config control: invoice-schema-repair-plan.json |
| `9e16a4e10e6a06a3a94bccc88ba6c30d59ffb389` | recovery/config control: customer-portal-config.json |
| `a2673e03ccc08b7439b327fd1a4cf62a7f5408f5` | second verified rollback |
| `ba491dfece056ca14e0e6cf1a848eacfcfca1ef2` | recovery/config control: restore-152.json |
| `bfb54fb63b64da7de5d56ab5e3c54225835f4938` | explicit plan reference: invoice-schema-repair-plan.json; recovery/config control: invoice-schema-repair-plan.json |
| `eaa914fa26cbd9025a81ced74192ddf8e4ab79f5` | explicit plan reference: migration138-tools-a0dda8a8064c\plan.json |

## 证据

本机与办公室均保留 `.deploy_state/deployment-cleanup-20261016/`；办公室根目录为 `D:/commission-system`，本机为 `D:/MyProgram/commission-system`。包含固定目标计划、运行引用检查、逐文件静态清单、安全测试、分项删除日志及最终独立读回。

- [最终读回](../../.deploy_state/deployment-cleanup-20261016/final-readback.json)
- [源码清理结果](../../.deploy_state/deployment-cleanup-20261016/sources-phase/cleanup-outcome.json)
- [静态清理结果](../../.deploy_state/deployment-cleanup-20261016/static-phase/cleanup-outcome.json)
- [清理前存储快照](2026-10-16-office-d-storage.md)

本次仅按用户授权清理历史部署材料，未提交、合并或推送本机其他改动。自动留存机制未在本次修改，后续发布仍可能继续累积候选。
