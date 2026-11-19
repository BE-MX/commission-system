# 2026-10-19 最新 main 全量生产发布

最终已将 main `7b2e954029d4f541a2499754543baaf4f1504956` 部署至办公室与云端。先发布拉取时最新的 `504e9264`，随后修复其导航清单问题；用户明确授权后完成修复的合并、推送和全量发布。两地实际清单校验通过。本记录不代表客户门户业务验收通过。

## 修复后最终状态（22:10）

- 修复仅修改一个 JSON 文件，远端 main、主工作区 HEAD 及两地安装版本均为 `7b2e954029d4f541a2499754543baaf4f1504956`。
- 修复版发布 ID `d32423c419b34e9ca82f2ade9fe9769f`；统一入口北京时间22:06:13至22:10:32，耗时259秒，22:10:45完成监测收尾。11个受管目标全部成功，无延后目标，退出0，锁释放。历史制品维护仍按入口默认延后；独立未受管服务不属于已更新范围。
- 两地 `load_access_manifest()` 实际运行通过，源摘要与清单摘要同为 `cd0ccf05a66a008482d0bec9f4af846f189e7e764dd065f37735e283f1a0a52a`，120项常用导航策略可加载，开户申请页的页面、菜单及组权限正确，原503校验原因已消除。未写入真实用户偏好；保存行为由前述隔离回归测试覆盖。
- 两地API/数据库健康、六个入口及入口JS摘要通过；数据库保持201，无新增DDL。门户开关和Scheduler单活配置与前轮一致；出库timer恢复原active/enabled，邮件worker保留停止状态。
- Office服务全部Running；北京原有未跟踪环境/业务目录清单与前轮一致，未清理或改写。2秒采样下本机健康失败区间约Office23秒/北京14秒（采样窗口，非精确用户停机时长）。
- 主工作区原有68个文件已完整备份；三份重叠文档用三方合并保留全部本地增量，导航清单原本仅换行差异，采用修复后内容并保留换行风格。其余文件逐字节不变；暂存区和冲突项为空。自建stash核验恢复后已删除；本任务worktree已归档，已合并本地分支已删除。
- 本轮一次性任务 `ArkFullMain7b2e954020261019` 已核验终态、导出XML并移除。最终证据在 `.deploy_state/full-main-release-20261019-7b2e9540/`，包含 final-readback、navigation-verification、portal-readback、static-verification、measurements、task-cleanup 和 task-export。Git保护证据在 `.deploy_state/nav-manifest-integration-20261019/`。

## 首轮发布结果（21:51）

- 前一版本：`ec76a177394488cfe26af20c870e492d1164cc96`。
- 发布 ID：`010d24f68d804026a74d2eba3b804a18`。固定候选使用其自身 `deploy/deploy.bat --live-root D:/commission-system --revision 504e9264e0ef61495228db434290103da2075dfd --no-pull`，11 个受管目标完成，无延后目标，入口退出 0，发布锁已释放。
- 北京时间 21:44:53 至 21:51:02 执行成功重试，入口耗时约 6 分 10 秒；21:51:15 完成回读。两地实际 Git、发布成功回执与候选一致。
- 数据库由 `198_customer_media_playback` 经 199、200 升至 `201_portal_access_requests`，由受管入口统一执行；没有开发机迁移、stamp 或降级。
- 首次尝试在构建阶段因发布机缺少 pnpm 失败，没有完成目标、切换或 DDL。固定安装 pnpm `10.33.2` 于发布机 `.deploy_state/tools/`，仅加入发布子进程 PATH；核对失败回执后才重试相同候选，保留首次失败证据。

## 验证与边界

- 两地 API、数据库健康回读正常，Office 三个服务 Running；Scheduler 保持办公室单活。出库轮询及邮件服务遵守原基线恢复。
- 六个静态入口及入口 JS 摘要一致：办公室 LAN、leshine.work、pm.leshine.work、leshine.cloud、media.leshine.cloud、shop.leshine.cloud。
- 两地 OpenAPI 均注册开户申请、激活、产品族、订货条款端点。数据库确认开户申请、色板、产品族三张新表及 catalog_items.family_id/grade、quotes.fee_estimate_json 新列。门户实际 bundle 含开户申请界面。
- 配置保持原状：办公室 `PORTAL_ENABLED=false`；北京 `PORTAL_ENABLED=true`。两地订单写入、发票、通知、邮件及门户出站 worker 开关均为 false，钉钉未配置。北京开户申请由门户总开关控制，不能把订单写入关闭表述为所有门户写操作关闭。本次未提交真实开户、订单或发信。
- 独立审查核对迁移链与 FK 类型；隔离环境迁移测试 5 项通过。没有使用共享生产配置执行写入型测试。
- 2 秒采样观察到 Office 本机健康失败区间约 43 秒，北京约 58 秒；Office 外网另有短暂探测失败。该数据是采样窗口，不是精确用户停机时长。

## 首轮发现的问题及修复准备（现已上线）

`frontend/src/config/navigation.js` 已更新，但 Git 中的后端导航权限清单仍保留旧 source_sha256。构建会修改候选目录清单，当前部署不把该未提交文件随 Git 安装。因此两地 `load_access_manifest()` 均拒绝旧清单并返回 503，影响所有用户新增常用导航（包括超级管理员）；没有写入真实用户偏好验证。普通菜单和路由、既有常用导航读取及不新增条目的删除/排序不受此处校验影响。

- 生产 source SHA256：`cd0ccf05a66a008482d0bec9f4af846f189e7e764dd065f37735e283f1a0a52a`。
- 生产 manifest source_sha256：`f82121db8ec12b413a36b07afd7fbd04ffd5c94d6019d41c7cb260fda925f836`。
- 本地修复：`codex/portal-nav-manifest-release`，提交 `7b2e954029d4f541a2499754543baaf4f1504956`，仅更新 `backend/app/system/navigation_access_manifest.json`，16 行增加、1 行删除。
- 后端导航偏好测试 13 项、前端常用导航测试 10 项通过；增量严格约定和 diff 检查通过，独立复核确认摘要及新门户权限声明一致。
- 首轮结束时修复尚未合并、推送或部署，等待明确授权。随后用户授权，按上方最终状态完成发布；没有直接修改生产文件掩盖 Git 与安装状态差异。

## 证据与清理

- 首次失败证据：`.deploy_state/full-main-release-20261019-504e9264/`。
- 成功重试证据：`.deploy_state/full-main-release-20261019-504e9264-retry1/`，包含 outcome、publish 回执、两地 evidence、static-verification、portal-readback、navigation-known-issue、measurements 与 task-cleanup。
- 两个本轮一次性计划任务均核对终态与 action 后导出 XML、移除；XML 已下载。没有删除原有服务或计划任务。
- 首轮写交接前，原有67个本地文件逐项SHA256确认未变。首轮记录及交接增量保留未提交；随后授权集成时连同此报告共68个文件纳入保护，最终清理状态见上文。
