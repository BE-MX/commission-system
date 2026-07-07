# 角色权限管理重设计方案

> **文档日期**：2026-07-03
> **配套原型**：`2026-07-03-permission-redesign-prototype.html`（浏览器直接打开）
> **性质**：设计方案 → **2026-07-03 已全量实施**（046 迁移 + seed upsert + 矩阵抽屉/导航反查/用户权限预览 + v-permission 指令 + 变更审计；实测 81 总量/12 legacy/69 有效，209 tests 全绿，无头浏览器截图验收）。待决问题三项均按建议版落地：模板用建议集（可在 config/roleTemplates.js 调）、审计已做（查看 UI 留待后续）、role:* 已随 upsert 归位 module=user

## 一、现状诊断（全部经代码/数据库核实）

| 问题 | 实锤证据 |
|------|----------|
| 权限码两代并存 | `commission` 9 个码里 `read_own/read_all/settle/export`（旧）与 `read/write/self_read`（新）并存；`design` 8 个里 `submit/read_own/read_all/approve`（旧）与 `read/write/audit/manage`（新）并存；`system` 有疑似零引用的 `config/logs/backup` |
| 模块归属不一致 | `role:read/write/delete` 挂在 module=`system` 下，而 `user:*` 挂在 module=`user`——同是账号体系，分了两个家 |
| 动作词汇失控 | 22 个模块的 action 词汇表有 read/write/delete/admin/manage/audit/approve/submit/sync/print/invoke/import/settle/export/config/logs/backup/design/self_read/read_own/read_all/internal_read/daily_report/assign_role——**24 种**，新人无法推断"编辑"该用哪个词 |
| 配置 UI 滚动过长 | `RoleManagement.vue` 用弹窗 + 22 组扁平 checkbox 纵向堆叠，81 个权限全靠滚动；无模块全选、无搜索、无模板 |
| 按钮级权限无统一机制 | 约 20 个页面各自手写 `v-if="authStore.hasPermission(...)"`，无全局指令；粒度与写法全靠自觉 |
| 配置视角单一 | 只能"按权限配"，不能"按页面反查"——配置者不知道勾掉某个权限会导致哪些菜单消失 |

**做得对、要保持的**：`module:action` 命名结构、导航可见性由 navigation.js 从权限**派生**（不存在第二套菜单配置）、super_admin 全局绕过、后端每端点 Depends 校验。

## 二、设计原则（三条，定生死）

1. **不重命名任何现有权限码**。81 个 code 散布在后端 Depends 与前端判断里，重命名 = 全量回归风险。治理手段是**元数据分层 + 死码下架**，不是改名。
2. **三层权限模型，导航永远是派生物**：模块（导航分组显隐）→ 页面（菜单/路由可见）→ 操作（按钮/端点）。任何时候不引入独立的"菜单权限"配置——菜单可见 = 拥有该页面 anyPermission，单一事实源不动摇。
3. **动作词汇表收口**：新权限只允许 `read / write / delete / admin` 四个标准动作 + 显式登记的特例（数据范围类如 `read_all/self_read`、业务动作类如 `sync/print/audit`）。词汇表进宪法，`check_conventions.py` 加一条校验（seed 新增行的 action 不在白名单 → 黄色警告）。

## 三、权限模型细化（迁移 046）

`ark_permissions` 增加三列元数据（**只加不改**，现有行为零影响）：

| 新列 | 含义 | 示例 |
|------|------|------|
| `kind` | `page`=控制页面/菜单可见 · `action`=按钮/操作级 · `data`=数据范围 | `commission:read`=page，`commission:write`=action，`tracking:read_all`=data |
| `is_legacy` | 1=已下架（UI 不再展示，端点暂保留兼容） | 死码核实后置 1 |
| `sort` | 模块内展示顺序 | — |

（对抗性审查后删除了原设计的 `page_key` 列：一码控多页是常态——`stock:read` 控 3 页、`production:read` 控 4 页，单值列装不下现实。权限↔页面的映射**不落库**，「按导航查看」运行时从 navigation.js 反推。）

**⚠ seed 机制必须先改造（对抗性审查发现的方案前提错误）**：现行 `seed_role_permissions` 是 **insert-only**（`if not existing` 才插入），元数据"启动幂等刷新"照现状实施会让 69 条已存在行的新列永远为空。实施时三件事一起做：
1. seed 循环改 upsert：存在时 UPDATE module/label/kind/is_legacy/sort（code 不变）——这同时修复 DB 里 `user:*` 挂错 module 的历史漂移
2. 12 条只存在于 DB、不在现行 seed 里的遗留死码，回填进 seed 并带 `is_legacy=1`（否则无处标记）
3. seed 末尾的"admin 角色自动授权"循环跳过 `is_legacy=1` 行

**死码核清结果（2026-07-03 已 grep 验证）**：`commission:read_own/read_all/settle/export`、`design:submit/read_own/read_all/approve`、`system:config/logs/backup`、`user:assign_role` 全部零引用（`commission:read_all` 仅出现在 dependencies.py 的 docstring 示例里，下架时顺手改掉该示例）。`customer_opportunity:import` 同样无 Depends 使用（ACCIO 导入走 API Key），但它在现行 seed 中，标 legacy 需改 seed 行。预期 **81 → 69 条有效，UI 只展示非 legacy**。

**动作词汇白名单**（进宪法与 check 脚本）：标准 `read/write/delete/admin`；登记特例 `manage`（≡admin，历史用词）与特殊类 10 个——`commission:self_read`、`tracking:read_all`、`tracking:daily_report`、`design:audit`、`ai:invoke`、`insight:internal_read`、`production:print`、`invoice:sync`、`report:design`、`customer_opportunity:import`。

## 四、配置 UI 重设计（核心交付）

### 4.1 权限矩阵（替代扁平 checkbox 长列表）

弹窗改为**全宽抽屉（90%）内的矩阵表**——69 个有效权限从"一维长列表"折叠成"23 行 × 5 列"，一屏尽收：

```
行   = 权限前缀（23 行：按 code 冒号前缀分行，payment/user/role 独立成行——
        它们的 module 列与他人复用（payment 挂 commission、user/role 挂 system），
        按 module 分行会导致一个格子挤两个码；按前缀分行保证 单元格=一个权限=一个 checkbox）
列   = 查看 · 编辑 · 删除 · 管理 + 特殊（该模块的 data/特例权限以 chip 呈现）
单元格 = checkbox（无此权限的格子显示 —）
行头  = 三态全选（本模块全给/全收）
列头  = 三态全选（如"所有模块的查看权限"一键给）
```

配套交互（每一条都针对一个现状痛点）：

1. **角色模板**：顶部下拉——业务员 / 主管 / 设计部 / 车间 / 财务 / 管理员 六个预设，一键套用后**差异高亮**（模板外多勾的格子标金边），防止"从零勾 81 个"。模板定义为前端常量（`config/roleTemplates.js`），不入库，改模板不用动数据库。
2. **搜索过滤**：输入"发票"只显示 invoice 行；输入权限码同样命中。
3. **变更差异条**：底部常驻"本次 +N −M"，保存前确认弹层列出具体增减明细——权限变更是敏感操作，必须先看清再提交。
4. **legacy 不展示**：`is_legacy=1` 的权限从矩阵消失（已勾选的旧码在差异条提示"含 N 个已下架权限，保存后自动移除"）。

### 4.2 「按导航查看」视角（第二个 tab）

同一抽屉内切换 tab：以 navigation.js 的分组 → 页面树呈现，每个页面节点显示"可见所需权限"与当前角色是否满足（✓/✗）。**只读反查视角**，点击权限 chip 跳回矩阵对应格子。解决"勾掉一个权限不知道哪些菜单会消失"。

数据来源：navigation.js 已有 NAV_ENTRIES（permission/anyPermission 就在 entry 上），前端直接消费，**后端零改动**。另需一份 NAV_ENTRIES 之外的权限入口豁免登记（当前两处：`/expo/kiosk` 顶层路由需 `expo:write`、移动端 `/m/*` 依赖 `asset:read`），否则反查视角对这两处是盲区——勾掉 expo:write 看不到菜单变化但展位 iPad 会被拦。

### 4.3 用户视角预览

用户管理页的用户详情增加"有效权限"折叠面板：多角色并集后的最终权限，按矩阵同款布局只读展示。回答管理员最常问的"这个人到底能干什么"。

## 五、按钮级权限统一机制

1. **全局指令** `v-permission` / `v-any-permission`（`directives/permission.js`，main.js 注册）：

```html
<el-button v-permission="'commission:write'">确认批次</el-button>
<GlassButton v-any-permission="['expo:admin']">编辑发型</GlassButton>
```

  指令内部走 authStore.hasPermission（super_admin 自动绕过），无权限时 `display:none`（不用 `el.remove()`——移除不可逆，且打在 GlassButton 这类组件上时删根元素会让 Vue patch 报错）。**新页面强制用指令**（宪法追加一条），存量 20 处 `v-if="hasPermission(...)"` 随迭代替换不专项回改。

2. **kind=data 的权限不控显隐、只控查询口径**（tracking:read_all 已是范例）：页面无切换控件，后端按权限自动决定数据范围——此模式写入设计原则，商机台/提成 self_read 等已有场景对齐。

## 六、实施步骤（拍板后执行，估 3~4 天）

| 步骤 | 内容 | 工作量 |
|------|------|--------|
| ① 死码核清 | 已于 2026-07-03 完成（第三节核清结果），剩 docstring 示例顺手修正 | 已完成 |
| ② 迁移 046 + seed 改造 | ark_permissions 加 kind/is_legacy/sort 三列；**seed 改 upsert**（含 module 漂移修复、遗留死码回填标 legacy、admin 自动授权跳过 legacy）；补齐全量元数据 | 1 天 |
| ③ 矩阵 UI | RoleManagement 权限区重写为矩阵抽屉（含模板/搜索/差异条）；「按导航查看」tab；用户有效权限预览 | 1.5 天 |
| ④ v-permission 指令 | 指令 + 宪法条款 + check_conventions 动作词汇校验 | 0.5 天 |

依赖与风险：全程不改权限 code、不动后端 Depends——**后端零回归风险**；矩阵 UI 是纯前端重写，旧弹窗保留到新版验收通过再删。

## 七、待决问题（2026-07-03 已全部按建议落地，见文档头部实施记录）

1. 角色模板的六个预设权限集需要你按实际岗位口径确认（原型里给了我的建议版）
2. 权限变更审计日志（谁在何时给哪个角色加/减了什么）——建议做，一张表 + 保存钩子半天工作量，要不要进本期？
3. `role:*` 归属模块从 system 挪到 user（纯元数据 module 字段调整，不改 code）——建议随步骤②的 seed upsert 改造一并做（前提是 upsert 先落地，insert-only 的现状下改了 seed 也刷不进 DB）
