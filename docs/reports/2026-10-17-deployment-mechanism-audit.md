# 部署机制与耗时检查（2026-10-17）

本次加入办公室候选清理和逐阶段计时，尚未合并、推送或部署。审计代码基于本地 main `3d78366c6f6966da4fd37217de3cecb694ae5085`，历史日志来自 2026-10-16 的 `1eef7a2e` 发布。本次办公室 SSH 在 localhost:2223 的 banner 握手超时，没有刷新生产运行状态，也未为测速重启或重发业务部署。

## 已有证据说明了什么

| 环节 | 证据 | 结论与边界 |
|---|---|---|
| 主站依赖安装 | prepare.log：181 packages，48s | 新源码 worktree 缺少 node_modules，即便锁文件没变，需重建时也会 npm ci；这次安装比编译更慢 |
| 主站前端构建 | prepare.log：built in 20.43s | 是本次编译实测值，不能据此归因全部部署时长 |
| 正式部署构建 | deploy.log：frontend、frontend-pm、frontend-portal 均 unchanged/build skipped | 缓存已生效；这次不能把正式部署等待归因为三套前端全量构建 |
| 静态传输 | 准备阶段两个主站各 212 文件、1,234,430 bytes；正式阶段 transfer_bytes=0 | 约 2.35 MiB 的新包已在准备阶段上传，正式阶段无重复新包传输；SSH往返/校验仍存在 |
| 办公室启动 | deploy.log：6 次 readiness retry；代码每次失败 sleep(2) | 明确存在至少 12 秒主动等待，另加 HTTP 探测时间；不是完整启动时长 |
| 资源保留 | retention-r2：办公室保留 4,401 个 assets，删除 622 个路径、补拷贝 420 个文件 | 资源历史会影响磁盘扫描和校验工作量；缺少阶段时间，尚不能量化其部署占比 |
| 磁盘故障恢复 | 应用 11 项完成，原部署退出 1；后续 static-retention-only 成功 | 上次总历时包含磁盘故障和人工恢复，不能当作正常部署基准 |

历史日志没有每步时间戳，无法可靠还原“完整部署耗时多少、哪一步占百分之几”。旧静态目录的单个并行哈希基准（573 文件、约 60 MiB、0.109 秒）样本过小，也不能代表真实串行保留流程或整个 D 盘速度。

本地保存证据位于主工作区 `.deploy_state/order-intelligence-release-20261016/remote-evidence/` 的 `prepare.log`、`deploy.log`、`publish-success.json`、`retention-r2.log`、`finalization.json`；清理基准为 `.deploy_state/deployment-cleanup-20261016/hash-benchmark.py-combined.txt`。这些文件是历史快照，下载文件时间不作为远端阶段起止时间。

## 代码确认的重复开销

1. **准备后再正式部署会再次跑大部分准备链。** `publish.py` 未直接消费一个已验证且仍有效的准备快照；Office 服务/字体/渲染/路由导入检查、共享 schema 预检、北京 prepare、路由与各静态目标准备再执行。复核漂移是必要的，但源码编译/制品检查与运行环境复核尚未分开缓存。
2. **办公室静态暂存重复复制且累计旧 assets。** `office_release.stage_static` 每次用新时间戳建目录，先复制当前构建，再把正式目录的旧 assets 合入。`--prepare-only` 的暂存不会直接被随后正式部署复用；旧主站资源越多，读取/复制越多。本次自动清理控制过期副本积累，尚未改变这条复制语义。
3. **依赖安装按候选目录存在与否触发。** 构建缓存命中可跳过安装；新版本需要编译时，新的 worktree 没有 node_modules，仍要安装。可考虑按 lockfile + Node/工具链的受管依赖缓存，但不能直接共享可写 node_modules，否则不同候选互相污染。
4. **静态保留预览和执行各做一次完整规划。** `static_retention_release` 先 Office 和两台云端预览，再逐个执行；每次内部又校验保留清单、历史文件、删改目录。Office 的旧备份还可能按 index 摘要去构建缓存中重建来源。优化应复用同一次锁内已验证计划，保留真正必要的执行前漂移检查，不能删掉安全校验来换时间。
5. **全环境目标串行，未变目标仍有网络和健康检查。** 主站两地、PM、客户媒体、客户门户共五个静态目标；后端、色块、出库、邮件也依次准备/激活/核验。未变传输为零，不等于无 SSH 成本。可并行独立准备，但冻结、DDL、激活和恢复仍须按一致性顺序执行。
6. **每次完整办公室发布仍执行两项种子程序。** 最近日志 PM/Pantone 都发现已存在并跳过写入，但进程启动、import 和数据库检查仍发生。可按版本/输入标记跳过无变种子，不过真实占比需新计时确认。

## 本次落地与后续优化顺序

- 已落地：成功发布后清理有创建回执、满 7 天的源码/静态暂存；保留当前与两级回滚、恢复/运行引用；最多 8 项、60 秒目标间软预算；未知旧目录不接管。支持独立预览/执行，失败不重复删除。规则见 `deploy/README.md`。
- 已落地：每次准备/部署的持久耗时文件；新增依赖、编译、PM 内网构建、静态保留各主机子阶段。父子阶段不可重复累加；磁盘满时计时失败不会改变部署结果。
- **优先优化静态暂存复用和同锁内保留计划复用**：代码已确认存在重复工作，修改前应以新计时确认收益，并绑定 revision、构建清单及正式目录状态防止复用过期制品。
- **其次评估依赖缓存和独立目标并行准备**：安装48秒是已有证据；远端网络耗时尚无分段数据。须维持候选隔离和当前故障恢复协议。
- 保留启动健康、数据库/协议、出库及邮件排空检查。它们保障资金、出库和迁移一致性，不能只为缩短界面等待而取消。

本轮没有声称已提速多少；清理防止再次积累，精确计时为下一次正常发布提供可比基准。

## 验证

- 最终相关回归：`python -m pytest deploy/tests/test_candidate_retention.py deploy/tests/test_pipeline_contract.py deploy/tests/test_source_release.py deploy/tests/test_desktop_console.py deploy/tests/test_static_retention.py deploy/tests/test_deploy_launcher.py -q`：**147 passed，4 skipped**。覆盖真实临时 worktree、未知数据/配置修改保护、Windows junction 外部 sentinel、引用变化、时限进度、中断不重试、只读预览、回滚历史落后与计时写盘故障。
- 扩大部署全套检查：**857 passed，18 skipped，3 failed**。在未修改主目录单独复验，原样重现 3 项基线失败：`test_merge_migration_plan.py` 两项仍期待195而实际为196；`test_storage_routing.py::test_bad_public_route_rolls_back` 的 mock side_effect 次数不足产生 StopIteration。本次不改迁移或无关路由断言。
- 独立 agent 审查及修复完成：外部恢复脚本引用、命令路径解析、候选预算饥饿、依赖链接/复制配置白名单、计时故障隔离、专项清理回滚顺序。成功版本在静态维护之前登记，维护失败不会丢掉正确的两级回滚顺序。
- 本机 Windows 进程/服务/NSSM配置/任务的只读引用枚举实际通过，只输出引用数量；不把本机结果当作办公室验证。
- `python scripts/check_conventions.py --strict`、`git diff --check` 通过；`python scripts/git_sweep.py --no-fetch` 完成，为本地远端快照。其他 worktree、未提交改动和 stash 保留。

测试仅使用临时 Git 仓库、临时目录和模拟服务；生产未写入。代码保留在 `codex/deployment-retention-audit`，未提交、合并、推送或部署。
