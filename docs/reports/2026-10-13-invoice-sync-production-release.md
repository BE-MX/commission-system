# 两项发票同步修复合并、推送与生产发布

2026-10-13，用户授权合并推送部署。两项修复已合入 main；业务发布采用固定候选 `f5269d9dff6856e4cab8c0d568f28e4f6f5349c8`，办公室与北京实际 HEAD 一致，后端和数据库健康。发布身份 `90890c88e90c4c2e85043d06f3338aa2`。

## 范围和 Git

- 修复提交 `d08f558c`：普通保存再同步时，根据同订单成功推单历史恢复发货单改号意图；重新验证旧号、当前发票号、原单身份和唯一关联，保留重号、已出库及不确定结果保护。
- 修复提交 `ba87adc1`：首次创建与恢复重复 SKU 分行时，不套用编辑发送的重复新增限制；按完整商业身份回写明细 ID。accepted 先保存事实，再 GET 原单核验，不再 POST。
- 合并 main `55b4c5b7ff562d83f6b61d23e5abf852069c6890` 已推送 origin 并读回一致。主目录 27 个既有修改/未跟踪文件已备份、恢复并验证；未夹带。
- main 包含未上线的 WhatsApp 接入切换、内贸交付及其迁移，且缺生产密码门户迁移历史。本次发布保留已运行的 `c797c45e` 与 `bf31b5f7` 部署恢复保护，再仅挑入两项发票修复。未上线新模块、未切换 WhatsApp 账号；发布候选的 9 个发票/发货相关源码文件与 main 完全一致。
- 生产候选与 main 不应按版本标签混为一体。后续完整 main 发布仍需明确合并生产门户历史及两个迁移分支；不得覆盖生产或 stamp/downgrade。生产候选分支 `codex/invoice-sync-production` 继续保留。

## 实际发布证据

从办公室受管候选启动 `deploy/deploy.bat --live-root D:\commission-system --revision f5269d9dff6856e4cab8c0d568f28e4f6f5349c8 --no-pull`；先 prepare-only 成功，再正式发布。未更改正在运行的部署器或绕过统一入口。

| 项目 | 核验结果 |
| --- | --- |
| 办公室后端 | 实际 HEAD f5269d9d，CommissionSystem SERVICE_RUNNING，127.0.0.1:8001/health 为 200/ok/connected |
| 北京后端 | 实际 HEAD f5269d9d，ark-backend active，127.0.0.1:8001/health 为 ok/connected |
| 公网入口 | 从办公室请求 leshine.work/health、leshine.cloud/health 均 200/ok/connected；开发机直接请求有本地连接错误，未据此判定生产故障 |
| 共享 schema | 186_portal_announcement_merge；候选 pending=[]、schema_changed=false，未运行新迁移；原 schema-writers 恢复记录仍 completed |
| 五个静态目标 | 两地主站、PM、素材、shop 均 unchanged，0 changed files/0 transfer bytes |
| 出库 | 同候选 revision，verified/release_confirmed=true；原 legacy 模式及数据库 fingerprint 保持，timer 回到 active/enabled |
| 邮件 Worker | 保持原 disabled/inactive，核验通过；没有为发布开启发送 |
| 发布日志 | publish-current/publish-success 为 succeeded，deferred=[]；本轮执行最终退出和静态保留结果另见归档回执 |

## 两张历史单

- 1053 `翟 #261022`：本地发票 synced，小满原订单 105851416713325；原发货单 105851418127778 仍为 Ginny-KC-1001、待出库。已部署代码只读计算 desired_serial_id=翟 #261022，下一次执行原发票同步可进入改号核验。本轮未发送改号 POST。
- 1064 `ly1010复购库存单`：仍为 sync_uncertain，原小满订单 105851516280181，原发货单 105851528008411 / XSCK2610130502 保留。本地持久 UID 仍为 0；实际部署代码用实时原单反序明细，在内存匹配 8 个 UID、unassigned=0。本轮未执行“核实原订单更新结果”的生产写入、未创建新订单或发货任务。

## 验证和已知限制

main 整合与固定生产候选分别通过 260 项隔离回归；生产候选 7 项新增实际 MySQL 场景通过；部署来源、迁移计划、办公室恢复、出库与完成协议 102 项通过。独立审查确认生产范围与恢复边界；原单 ID 的商业行错配风险已修复。完整约定门禁仍有 17 项既有发票 UI 债务，未改前端来隐藏问题。

扩展恢复集的 6 个绑定/迟到入口失败已在主分支未修改代码复现，本次仅修复这张已绑定订单的重复行收尾/恢复；不宣称所有恢复入口都已修复。前端本轮没有变化，复用现有制品；健康、版本与只读协议核验不等于真实 UI 点击或单据恢复已完成。

本地证据 `.deploy_state/invoice-sync-release-20261013/`：候选 bundle/源码一致性、27文件保护回执、预检/发布结果、服务与单据读回、发布及 schema 日志。办公室保留同名发布目录、原回滚制品及成功记录；独立候选保留。
