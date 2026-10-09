# 用户管理账号解锁验收

实现及验证完成。用户已授权提交、合并到 `main` 并推送 `origin/main`，本次不部署和升级生产数据库。原开发分支为 `codex/account-unlock`。

用户管理状态列显示“登录锁定”，操作列增加“解锁账号”。沿用 `user:write` 权限、GlassButton 和确认反馈；未锁定、禁用账号按钮不可用，只读用户没有入口。成功后刷新当前列表，请求处理中阻止重复点击；失败保持锁定状态并反馈错误。解锁不改密码、角色或启用状态。

原登录日志保持不变；`ark_account_unlock_audits` 保存操作人、账号、失败次数、日志 ID 边界及北京时间。窗口内仅计入边界之后的新失败；同秒失败不依赖时间精度区分。重复解锁未锁定账号不写审计、不清空未达阈值的失败。登录和管理员解锁先锁定目标用户行，之后读取失败计数。

验证证据：

- `python -m pytest tests/test_account_unlock.py tests/test_platform_timezone.py -q`：25 项通过。覆盖真实 HTTP 登录→锁定→解锁→成功、重新锁定、权限、禁用/删除、日志完整保留、旧未知用户名记录、窗口跨北京时间零点、提交失败回滚；迁移在内存 SQLite 执行，并离线生成 MySQL DDL 验证 unsigned 外键。
- `npm run build`：成功，既有大 chunk 与静态/动态 import 提示保留。
- Playwright 对本地构建预览执行 9 类检查：锁定状态、按钮可用性、正常/禁用账号不可解锁、取消无请求、忙碌状态阻止重复、成功刷新、失败保留锁定、430px 窄屏横向滚动后可点击并取消、只读用户入口隐藏。全部通过，无浏览器运行异常；使用合成数据，API 请求全部拦截，不访问生产 API。证据已保存在主目录 `tmp/account-unlock-20261009-merge/`。
- 独立 agent 审查通过；根据审查把用户名 COLLATE 放到参数/比较右侧，避免目标行锁查询因列侧表达式扩大扫描。已只读核验当前共享数据库两张表的用户名 collation 为 `utf8mb4_unicode_ci`。
- 约定检查无违规；`alembic heads` 仅 `178_account_unlock`；`git diff --check` 通过；Git 巡检 `--no-fetch` 为本地快照，不触发其他分支操作。

上线前需经项目发布入口执行 `178_account_unlock` 迁移并同步后端、前端。无隔离 MySQL 双连接验证环境；SQLite 和离线 DDL 不代表已实测 InnoDB 并发等待行为。生产迁移及部署未获本次请求授权，未执行。

## 远端整合与交付

- 基点 `7852719f`，初次功能提交 `dc16facf`；整合远端 `50a85983` 的门户功能后，迁移顺延为 `178_account_unlock`，父 `177_portal_pi_header`，单 head。
- 解锁事务按授权屏障当前读、目标用户行锁、实时角色/权限检查、失败计数的顺序运行，拒绝过期 JWT 的历史超级管理员角色及已禁用操作人；解锁不递增门户授权版本。动态导入避免循环依赖，403/503 带 no-store；忙碌异常保留专用处理器。
- 整合测试：`pytest tests/test_account_unlock.py tests/test_platform_timezone.py tests/portal/test_upstream_authority.py -q` 共 46 项通过。主站生产构建通过，保留已有大 chunk 提示。
- 远端原版本存在两处阻断构建的语法错误：重复声明 `getInvoiceSummary`、发票样式选择器组多余开括号。仅删除重复声明与错误行，保留配置参数及原四个内容区域的样式；独立复审通过。
- 额外执行 `node --experimental-vm-modules --test tests/authTransport.test.mjs tests/invoiceRead.test.mjs tests/requestAuthRace.test.mjs`，78 项因测试 mock 未适配反馈等模块依赖而失败。已核对测试与全部被测源码逐文件和 `origin/main` 相同，属于远端既有基线问题；没有修改断言或宣称其通过。
- 主目录原有 24 项修改先完整备份，集成提交不夹带这些修改。验证日志与恢复材料保存在主目录 `tmp/account-unlock-20261009-merge/` 及个人临时目录。
