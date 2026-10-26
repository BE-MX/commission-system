# 客户门户访问复制、图片与下单资料

2026-10-26；分支 `codex/portal-customer-experience`。Git交付：按亮哥本次授权提交、合入main并推送origin；未部署。基于本地取得的 `origin/main` 快照 `5020c97e`，主目录原有改动保留。

## 操作变化

- 方舟「客户下单门户 → 客户访问」列表新增“复制”。选择已启用的源客户，再选另一家已验证的方舟客户，输入新邮箱和密码，即创建独立客户访问与采购账号。继承查价/下单能力及已发布商品授权；原客户订单、专属价格、别名映射和收货资料不复制。目标身份/负责人仍实时检查，已下架商品阻断复制。原子事务、源记录/目录版本及原操作标识保护重复点击和断线重试。
- 门户侧边购物车数量可直接输入，保留加减按钮、最小量、步长和10000上限；非法输入显示错误并恢复原数量。
- 顶部“Delivery details”可在选品前维护联系人、电话和收货地址。资料保存到当前采购账号，刷新/重新登录后可读取；进入结算时只填入未编辑的空白表单。手填、已报价及重购的地址保留，历史订单不改。

## 图片线上只读诊断

对 `shop.leshine.cloud` 对应北京实例、素材绑定与服务日志只读检查：

- 生产代码当时为 `6fbf8a8c5c`。Nginx 和 PortalRoute 均强制图片 no-store；浏览器不会持久复用先前下载的图。服务端每次重新读取、解码、缩放，尚无缩放结果缓存。
- #2B 色卡 `2c4de915-a355-4499-b4a7-a1de3ffa7d3b`（version2）绑定素材14716，原件485080字节，已云同步，素材状态与对外预览/下载权限正常；#60/#8同样有有效绑定。实际原因不是缺少#2B图片。
- `logs/service.log` 中同一#2B thumbnail多次503，邻接日志为 `Portal transaction row-lock wait timed out after 5 seconds`，同素材full请求随后200。多个色号并发请求都存在此现象。失败后旧组件只保留LS占位，不再恢复。

修复为可视区触发、全局最多2个图片请求、主图优先，只有503允许一次GET重试；不重试404/401。Blob仅在当前组件内使用，源变化和卸载时取消请求并撤销。服务端增加16MB内存缩放缓存；仍逐次检查当前授权、存储状态与原件完整性，缓存不保存客户权限。云缓存摘要校验后按登记摘要复用；本地原件按文件状态失效。商品图片端点新增96px的thumb参数，未单独绑定色卡但有商品图时也可显示对应缩略图。

隔离2400×1800 PNG处理样本：首轮缩放66.38ms，后续5轮缓存命中中位数0.43ms。此数字只代表本机处理，不是线上首屏、网络或数据库延迟。图片并发限制减少同页授权锁争用；其他业务长事务仍可能引发503，发布后需观察实际负载。

## 持久化和发布边界

迁移 `204_portal_delivery_profile` 接当前主线 `203_perf_goals`，仅给 `ark_order_portal_accounts` 新增nullable `delivery_json`。旧账号为NULL；保存使用账号row_version与客户CSRF，不改变auth_version。隔离SQLite验证已有账号保留；未执行生产DDL。

新接口、字段和错误恢复契约已同步 `docs/api-reference.md`、`docs/database.md` 与 `docs/handoff.md`。没有生产账号创建、权限变更、订单提交、素材修改或配置写入。发布仍需用户授权并走项目统一部署入口。

## 验证证据

- 后端完整门户回归：`python -m pytest --confcutdir=tests/portal tests/portal -q`，**854 passed, 2 skipped**。全部使用无.env隔离worktree和SQLite，MySQL连接被测试fixture禁止。含复制HTTP与幂等重放、跨客户/员工范围、目标冲突回滚、CSRF、资料并发、迁移保留原账号、缓存损坏与撤权复查。
- 门户单元测试：**146 passed**；后台门户单元测试：**49 passed**。两个前端构建通过；后台保留既有大包和混合动态import警告。
- `frontend-portal/tests/customerExperience.browser.mjs`：1440/375宽度通过。包含#2B缩略图503后恰好重试一次、主图优先、实际图片并发≤2、商品图缩略图回退、手输12数量和非法0回退、提前保存/刷新带出、PUT回执丢失后GET核对、结算自动填充及手改地址保留。
- `frontend-portal/tests/family.browser.mjs`：1440/375/320及横屏812×375通过，覆盖原有选品/色号/缺货/购物车/结算入口；适配可视区加载后，检查先滚动目标图片进入视口。
- `frontend/tests/portalAccessCopy.browser.mjs`：1440/390/320宽度通过；验证独立客户身份、源版本、只填邮箱密码、未知结果冻结、先查询后用完全相同key/body重试。全部为构建产物与内存API，没有真实业务写入。
- 独立审查发现的复制请求迟到覆盖、已登记本地原件缓存失效问题已修复并复核。没有新增动效。
- 约定检查、差异空白检查与 `git_sweep.py --no-fetch` 已执行；巡检仅本地远端快照，不处理其他分支/工作区。

日志：`tmp/portal-pytest.log`、`tmp/portal-admin-tests.log`、`tmp/frontend-build.log`。浏览器截图：`tmp/portal-customer-experience/customer/`、`tmp/portal-customer-experience/admin/`。本地验收不等于生产改善；发布后仍需真实客户登录态验证首屏速度与图片503情况。
