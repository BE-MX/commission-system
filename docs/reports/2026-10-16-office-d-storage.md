# 办公室服务器 D 盘占用分析（2026-10-16）

已完成固定候选 `1eef7a2e` 的应用部署及资源保留恢复；此后只读扫描D盘。总容量 **292.97 GiB**，已用 **229.98 GiB**，可用 **62.99 GiB**。

主要占用是业务素材与部署历史，日志不是大头。可优先核对的三类部署材料合计 **61.69 GiB**，实际可释放量需扣除当前、回滚和恢复计划所需内容。本次分析未继续删除或移动文件。

| 独立目录 | 逻辑大小 | 说明 |
|---|---:|---|
| `D:\WORKSOURCE` | 120.91 GiB | 2026年5月83.74GiB、6月33.44GiB；业务原件。 |
| `D:\commission-system\.deploy_state` | 68.05 GiB | 含源码候选、依赖、构建、暂存，也含数据库备份；不可整目录清空。 |
| `D:\commission-system\uploads` | 17.25 GiB | 其中出库检验媒体15.85GiB、expo约0.60GiB。 |
| `D:\ACCIO WORK BACKUP` | 5.76 GiB | 3份ZIP目录可读；10:00文件疑似未写完整。 |
| `D:\$RECYCLE.BIN` | 4.02 GiB | 恢复需求审核后由所有者决定清空。 |

项目根目录合计约88.63GiB，其中.deploy_state约68.05GiB、uploads约17.25GiB、backend约1.19GiB、logs约0.91GiB。上表deploy与uploads互不包含，避免把项目根目录重复相加。

## 部署目录为何持续增长

- `sources` 至少172个较大历史源码候选，约38.97GiB；候选保留独立依赖。
- `office-next-*` 至少98个较大暂存目录，约16.40 GiB；其中91个主站待切换目录约16.38GiB。
- `builds` 至少107个较大构建目录，约6.33GiB。
- `python-envs` 约2.66GiB、客户门户数据库保护备份约2.44GiB，需保护被服务或恢复计划引用的内容。

源码核对：`deploy/source_release.py`创建并保留固定SHA worktree；`deploy/office_release.py:123`在prepare阶段创建新的office-next目录；`deploy/office_static_retention.py`匹配office-previous回滚目录并管理发布资源，没有覆盖sources/builds/office-next的通用留存。所以正常静态资源保留成功后，这些历史候选、构建与待切换副本仍会累积。只凭命名尚不能判定每个旧目录都可安全删除。

## 业务文件与备份边界

WORKSOURCE在`backend/app/core/config.py`和`deploy/backup-uploads.bat`中登记为素材中台业务资产根目录。其2026年5月约83.74GiB、6月约33.44GiB。uploads中shipping-inspection约15.85GiB，是应保护的检验媒体。不能为了释放空间直接清空这些目录。

ACCIO WORK BACKUP当前共4个ZIP约5.76GiB。07/08/09点三份中央目录可读，内容以accounts和logs为主；未做解压或完整CRC校验。**10:00的ZIP约0.71GiB，无法读取中央目录，文件开头为ZIP本地头，检查时约25分钟未修改，疑似写入中断；不能当作已验证可恢复备份。** 先核对备份任务并重做一份可验证备份，保留前三份。

## 扫描口径与证据

扫描时间：2026-10-16 10:26:01 +08:00，耗时104.5秒；3,343,644个文件、305,399个目录；读取错误0，重解析点不跟随。目录大小使用逻辑字节；卷已用量含文件系统分配/元数据等，和可枚举逻辑总量相差约9.51 GiB，这部分未进一步归因。扫描中服务继续运行，数值是当时快照，不是配额或可释放空间保证。

本机原始扫描及ZIP元数据：`.deploy_state/order-intelligence-release-20261016/storage-analysis/`。办公室原始报告在`C:/ArkDeploymentRecovery/order-intelligence-20261016/storage-analysis/`，没有写入被扫描D盘。部署恢复证据见[发布记录](2026-10-16-order-intelligence-filter-release.md)。交互只读报告见[HTML报告](2026-10-16-office-d-storage.html)。


## 后续清理结果

2026-10-16 12:48:04 +08:00 已按用户授权清理 162 个历史源码候选和 102 个废弃静态副本，逻辑 52.73 GiB；最终 D 盘可用 117.52 GiB。本页以上数字保持 10:26 的清理前快照。见[清理明细与验证](2026-10-16-deployment-history-cleanup.md)。
