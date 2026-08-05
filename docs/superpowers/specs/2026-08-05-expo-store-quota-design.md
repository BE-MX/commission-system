# 展会 AI 试戴门店化：额度、权限与前端显示优化方案

**日期：** 2026-08-05  
**状态：** 设计已确认，待写实现计划  
**相关模块：** `backend/app/expo/`, `frontend/src/views/expo/`, `backend/app/auth/`

---

## 背景

展会 AI 试戴程序将从展会场景延伸到门店日常使用。门店侧的核心诉求是：

1. 每个门店拥有独立账号与额度；
2. 后台可给门店充值生图张数，并查看充值/消耗历史；
3. 线索台按门店权限隔离；
4. 试戴界面实时显示剩余可用生图张数。

当前系统没有「门店」实体，额度与线索数据范围均为空白，需要新增模型、权限、API 与前端展示。

---

## 目标与非目标

**目标：**

- 建立门店实体，支持一个门店绑定多个系统账号；
- 实现按门店维度的生图额度（终身累计、充值叠加）；
- 实现额度充值与消耗的历史记录；
- 实现线索台按门店隔离 + 跨店查看权限；
- 在 Kiosk 与 PC 线索台显示剩余额度，余额为 0 时服务端硬阻断生成。

**非目标：**

- 不实现额度周期重置/基础包（本次采用终身累计模型）；
- 不实现充值审批流；
- 不追溯旧 session/customer 的门店归属；
- 不把展示版 `_disp.jpg`、缩略图 `_thumb.jpg` 单独计费。

---

## 关键设计决策

| 决策项 | 结论 | 理由 |
|---|---|---|
| 门店模型 | 独立实体 `ark_expo_stores`，可挂多个 `ArkUser` | 满足店长/多导购/多设备场景 |
| 额度模型 | 终身累计，`total_quota`/`used_quota` | 简单直接，符合充值即加额需求 |
| 历史记录 | 独立流水表 `ark_expo_quota_records` | 不可变流水，对账清晰 |
| 扣减时机 | 每成功一张最终效果图扣一张 | 失败由系统承担，用户体验最好 |
| 线索隔离 | 按 `customer.store_id` 过滤 | 门店内所有账号共享线索 |
| 跨店查看 | 数据范围权限 `expo_lead:read_all` | 复用现有 RBAC 模式 |
| 额度显示 | Kiosk + PC 线索台同时显示 | 两端都需要感知余额 |
| 余额为 0 | 服务端硬阻断生成 | 防绕过，前端只做展示 |

---

## 数据模型与迁移

### 新增表

#### `ark_expo_stores`（门店表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `name` | str(128) | 门店名称，如「广州美博城店」 |
| `code` | str(64) unique | 门店编码，如 `GZMB001` |
| `status` | int | 1=启用，0=禁用 |
| `total_quota` | int | 累计充值总额度 |
| `used_quota` | int | 已用额度 |
| `contact_name` | str(64) nullable | 联系人 |
| `contact_phone` | str(32) nullable | 联系电话 |
| `created_at` | datetime | |
| `updated_at` | datetime | |

#### `ark_expo_store_users`（门店-用户绑定）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `store_id` | int FK → `ark_expo_stores.id` | |
| `user_id` | int FK → `ark_users.id` | |
| `is_primary` | bool | 是否主账号（店长） |
| `created_at` | datetime | |

#### `ark_expo_quota_records`（额度流水）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `store_id` | int FK → `ark_expo_stores.id` | |
| `type` | str(16) | `recharge` / `deduct` |
| `amount` | int | 正数；充值为 +N，消耗为 -N |
| `balance_before` | int | 变动前余额 |
| `balance_after` | int | 变动后余额 |
| `related_id` | int nullable | 关联业务 ID |
| `related_type` | str(32) nullable | 当前仅 `expo_result` |
| `operator_user_id` | int FK → `ark_users.id` | 操作人 |
| `remark` | str(255) nullable | 备注 |
| `created_at` | datetime | |

### 既有表改动

- `ark_expo_sessions` 增加 `store_id: int FK nullable`；
- `ark_expo_customers` 增加 `store_id: int FK nullable`；
- 旧数据允许 `null`，新数据写入时根据当前操作用户所属门店填充。

### 新增权限 code

- `expo_store:admin` — 创建/编辑/禁用门店、绑定用户
- `expo_store:recharge` — 给门店充值、查看充值历史
- `expo_lead:read_all` — 数据范围权限，查看所有门店线索

---

## 后端 API 设计

### 门店管理

```http
GET    /api/expo/stores                    # 门店列表（分页/搜索）
POST   /api/expo/stores                    # 创建门店（expo_store:admin）
GET    /api/expo/stores/{id}               # 详情
PUT    /api/expo/stores/{id}               # 编辑（expo_store:admin）
POST   /api/expo/stores/{id}/toggle        # 启用/禁用（expo_store:admin）

GET    /api/expo/stores/{id}/users                        # 已绑定用户
POST   /api/expo/stores/{id}/users                        # 绑定用户（expo_store:admin）
DELETE /api/expo/stores/{id}/users/{user_id}              # 解绑用户（expo_store:admin）
```

### 额度

```http
GET    /api/expo/stores/{id}/quota           # 查询余额
POST   /api/expo/stores/{id}/quota/recharge  # 充值（expo_store:recharge）
GET    /api/expo/stores/{id}/quota/records   # 额度流水
```

充值请求体：

```json
{
  "amount": 100,
  "remark": "7月充值"
}
```

### 生图 API 改造

`POST /api/expo/sessions/{id}/generate`：

1. 根据当前用户获取所属启用门店；
2. 计算本次计划生成张数（`len(matched_wigs)`）；
3. 校验 `remaining >= planned_count`，否则返回 `400` + 「门店额度不足」；
4. 写入 `session.store_id`；
5. 逐张调用 AI 生图；
6. 每张成功保存 `result` 后，批量扣减额度并写流水；
7. 失败不扣额，记录日志。

### 线索台 API 改造

`GET /api/expo/leads`：

- 默认按当前用户所属门店过滤（`customer.store_id IN user_store_ids`）；
- 若用户有 `expo_lead:read_all`，则不过滤；
- 增加可选参数 `?store_id=`（仅 `read_all` 时生效）。

---

## 额度扣减流程

```python
store = get_active_store_by_user(current_user.id)
if not store:
    raise BizError("当前账号未绑定有效门店")

planned_count = len(matched_wigs)
if store.total_quota - store.used_quota < planned_count:
    raise BizError("门店剩余额度不足，请联系运营充值")

session.store_id = store.id

successful_results = []
for wig in matched_wigs:
    try:
        image_path = await generate_image(...)
        result = create_result(session_id=session.id, wig_id=wig.id,
                               image_path=image_path, store_id=store.id)
        successful_results.append(result)
    except Exception:
        logger.exception("生成失败，不扣额")
        continue

if successful_results:
    deduct_quota(
        store_id=store.id,
        amount=len(successful_results),
        result_ids=[r.id for r in successful_results],
        operator_user_id=current_user.id
    )
```

### 并发控制

- 使用 `SELECT ... FOR UPDATE` 锁定门店行后再更新 `used_quota`；
- 额度扣减与流水写入必须在同一数据库事务内完成。

---

## 线索台权限隔离

### 数据归属

- 新客户注册时：`customer.store_id = operator_user.store_id`；
- 新拍照会话时：`session.store_id = operator_user.store_id`；
- 线索台聚合查询以 `customer.store_id` 为过滤条件。

### 查询口径

```python
if not has_permission(current_user, "expo_lead:read_all"):
    user_store_ids = [u.store_id for u in current_user.stores]
    query = query.where(ExpoCustomer.store_id.in_(user_store_ids))
```

### 门店选择器

- PC 线索台顶部增加「门店筛选」下拉；
- 无 `expo_lead:read_all` 权限时不显示筛选，默认只看本店；
- 有 `expo_lead:read_all` 时可选「全部门店」或指定门店。

---

## 前端改动

### 后台：门店管理页

- 路径：`/expo/stores`
- 权限：`expo_store:admin`
- 内容：门店列表、新增、编辑、启用/禁用、绑定用户、额度流水 Tab

### 后台：门店额度充值/历史

- 在门店详情抽屉中以 Tab 形式展示；
- 充值按钮受 `expo_store:recharge` 控制；
- 流水列表：时间、类型、金额、余额、操作人、备注。

### PC 线索台额度显示

- 工具栏右侧显示「剩余 N 张」；
- ≤ 10 张时变 warning；
- 0 张时禁用生成入口并提示充值。

### Kiosk 额度显示

- 顶部状态栏固定显示「剩余 N 张」；
- 0 张时变红 + 居中提示「额度已用完，请联系门店管理员充值」；
- 禁用拍照/生成按钮。

### API 封装（`frontend/src/api/expo.js`）

```js
export const getStoreQuota = () => api.get('/stores/quota')
export const rechargeQuota = (storeId, data) =>
  api.post(`/stores/${storeId}/quota/recharge`, data)
export const listQuotaRecords = (storeId, params) =>
  api.get(`/stores/${storeId}/quota/records`, { params })
```

---

## 权限矩阵

| 角色 | `expo_store:admin` | `expo_store:recharge` | `expo_lead:read` | `expo_lead:read_all` |
|---|---|---|---|---|
| 超管 | ✓ | ✓ | ✓ | ✓ |
| 运营/渠道 | ✓ | - | - | - |
| 财务 | - | ✓ | - | - |
| 门店导购 | - | - | ✓ | - |
| 督导/大区 | - | - | ✓ | ✓ |

---

## 测试策略

### 后端

1. 充值后 `total_quota` 与流水正确；
2. 生成 N 张成功图后 `used_quota` 增加 N；
3. 生成失败不扣额；
4. 并发下不超额扣减；
5. 余额不足返回 400；
6. 普通用户只能看本店线索，`read_all` 可看全部；
7. 无 `expo_store:recharge` 调用充值接口返回 403。

### 前端

1. `npm run build` 通过；
2. Kiosk 余额为 0 时禁用生成；
3. 后台菜单/按钮按权限显隐正确。

### 迁移

1. 新字段 nullable，不影响既有数据；
2. Alembic 迁移在开发库验证通过后执行。

---

## 风险与注意事项

1. **旧数据不追溯**：历史 session/customer 的 `store_id` 为 null，不参与新权限过滤；
2. **并发扣额**：必须用数据库锁或事务避免超卖；
3. **Kiosk 账号归属**：一个 Kiosk 设备应登录固定门店账号，否则线索归属会乱；
4. **AI 调用失败**：失败不扣额，但需监控失败率避免被薅。

---

## 下一步

设计确认后，编写实现计划 `docs/superpowers/plans/2026-08-05-expo-store-quota-plan.md`，按子任务逐步落地。
