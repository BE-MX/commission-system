# 内贸客户提成配置与订单快照

实现分支为 `codex/domestic-commission-snapshot`，本次经用户授权合并 main 并推送 origin；生产部署和迁移未执行。只实现分配配置与归属快照，不计算或发放提成金额。

## 用户行为

1. 新建客户默认给保存时的归属销售配置 4%，无需手工添加。客户管理创建、下单输入店名就地建档、Excel 新建客户均覆盖；已有客户导入更新不覆盖原配置。
2. 编辑客户可维护 1～2 名业务员的直接提成率，例如 3%＋1% 或 2%＋2%。默认合计 4%，其他正比例合计允许到 100%。更换归属销售不会自动覆盖配置，提成名单不改变权限。
3. 新建业务订单选择客户后，客户名称后展示分配及合计。未配置时阻止新单；就地创建的新客户自动 4%。如果选客后配置改变，提交返回 409，更新显示并要求重新点击提交。
4. 首次保存订单（包括草稿）冻结人员、姓名和比例。客户改配置、人员改名/停用、改订单金额、提交/重审、追加明细不重取。订单详情显示本单快照。草稿实际更换客户作为例外，同事务重建快照并留痕。
5. 历史订单不回填当前配置，显示“未记录提成分配”；已有订单编辑不因缺配置阻断。生产单不参与；公开进度不泄漏提成。

## 数据与并发

- 两张新表：`ark_domestic_customer_commissions`、`ark_domestic_order_commissions`；比例 `NUMERIC(5,4)`，0.03=3%，姓名快照 50 字符。用户 FK 与 `ark_users.id` 同为 INT UNSIGNED，RESTRICT 避免人员硬删损失证据。
- 迁移 `196_domestic_commission` 接 `195_main_portal_merge`，仅创建空表，无历史归属猜测、金额/账本回填或生产库操作。生产升级走统一部署入口。
- 配置维护与建单都先锁客户；锁定配置、配置替换删除及草稿快照替换均使用 MySQL 当前读并刷新 ORM，避免 REPEATABLE READ 旧 read view。订单与快照同事务提交，失败一起回滚。
- 姓名/比例变更使用现有内贸分析事件审计。草稿换客先持久化新客户身份，再生成快照事件。建单幂等重放读取原订单，不从当前客户重建快照；expected 字段为空时保持旧请求指纹。

## 验证

- 先新增两条默认配置回归，在原实现失败于缺少配置返回字段，再实现使其通过。
- 默认配置、快照冻结、配置变动、草稿换客、幂等、旧指纹、公开信息边界、权限、回滚、导入、北京时间零点、隔离 SQLite 迁移与 MySQL DDL 均有回归覆盖。
- 前端 `npm run build` 通过；只有现有大 chunk / auth 动静态混合导入提示。
- `node --test frontend/tests/domesticCommission.test.mjs`：3 项通过。
- 浏览器使用实际 Vue 页面、合成 SQLite 生成的数据及截获的本地 API；11 项通过，含选客切换、3%＋1%/4%/未配置显示、409 阻止首次提交、第二次提交采用新比例及新幂等键、客户编辑保存、默认提示、390px 展示。证据在本工作区 `tmp/commission-qa/`，不触碰业务数据库。
- 独立 agent 审查提出并修复旧读视图、旧指纹和换客审计归属三项 P2；复审通过。真实 MySQL 双事务未运行，本次提供 SQLite 回归、MySQL 当前读 SQL 断言及 DDL 编译证据。
- 最终整个内贸域：1002 项通过、1 个已复现的原有文案断言失败、1 个显式要求 `DOMESTIC_TEST_MYSQL_URL` 的隔离 MySQL 可选测试跳过；耗时 187.31 秒。命令为 PowerShell 枚举 `backend/tests/test_domestic*.py` 后执行 `python -m pytest ... -q --disable-warnings --tb=short`，完整输出保留在 `tmp/commission-qa/domestic-tests.txt`。其中本次提成测试包含 MySQL DDL 编译及单 head 断言。
- `python scripts/check_conventions.py --strict` 通过（红/黄均无），`git diff --check` 通过；`python scripts/git_sweep.py --no-fetch` 已执行，仅代表本地 refs 快照，无远端写入或分支清理。
- UI 检查按 Emil 设计工程原则及项目 DESIGN.md 保持高频表单即时反馈，不新增动效；新增颜色使用既有令牌。[桌面选客](assets/domestic-commission-snapshot/order-selected-desktop.png)、[客户分配编辑](assets/domestic-commission-snapshot/customer-edit-desktop.png)、[窄屏选客](assets/domestic-commission-snapshot/order-selected-mobile.png)。
- 临时原始源码验证副本/ZIP 与调试截图的清理被自动审批拦截（返回 `blocked by policy`，未给出更细原因），已保留在 `tmp/commission-qa/`；未绕过拦截。开发验证服务器已停止，正式交付文件不受影响。

## 已确认的原有测试问题

`test_domestic_reporting.py::test_terminated_order_blocks_shipping` 在原始 HEAD `974bfd8a` 的隔离源码快照中同样失败：系统拒绝已终止订单发货，但异常文案为“只能选择同一客户名下处于生产中的有效业务订单”，测试期待“订单已终止”。本次不修改无关发货逻辑或弱化该断言。
