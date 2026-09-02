# Kiosk 展会线索门店隔离设计

日期：2026-08-25

## 问题与目标

PC 端展会线索台已经按门店隔离，但 Kiosk 的销售模式仍通过独立接口读取全部线索，导致普通门店账号可以绕过 PC 端限制查看其他门店客户。

本次目标是让 PC 与 Kiosk 使用同一数据范围规则：

- 普通账号只能查看其绑定的启用门店所创建的展会线索；
- 未绑定启用门店的账号看不到任何线索；
- 只有 `expo_lead:read_all` 权限或 `super_admin` 角色可以查看所有门店；
- 跨店直接访问详情统一返回 404，不暴露客户是否存在。

## 范围

本次修改以下 Kiosk 端点：

- `GET /api/expo/kiosk/leads`
- `GET /api/expo/kiosk/leads/{customer_id}/strategy`

PC 端 `/api/expo/leads` 与 `/api/expo/leads/{customer_id}` 的现有行为保持不变。前端界面与数据库结构不变。

## 设计

### 统一数据范围

复用 `backend/app/expo/router.py` 中现有 `_lead_store_scope(db, current_user)`：

- 返回 `None`：拥有 `expo_lead:read_all` 或 `super_admin`，查询不限制门店；
- 返回门店 ID 列表：普通账号只能查询这些启用门店；
- 返回空列表：账号无有效门店绑定，查询结果为空。

Kiosk 路由不再丢弃认证用户对象，而是将当前用户传给该数据范围函数。

### 列表接口

`GET /kiosk/leads` 将 `store_ids` 传入现有 `service.list_leads()`。服务层已有 `customer.store_id IN store_ids` 查询能力，因此不新增重复过滤逻辑。

`store_ids=[]` 必须产生空结果，不能退化为不加过滤。

### 详情接口

`GET /kiosk/leads/{customer_id}/strategy` 将 `store_ids` 传给 `service.get_kiosk_strategy()`。服务层在读取客户时直接附加门店条件，避免先加载跨店客户及照片数据：

- 全量权限：允许读取；
- 普通账号且客户属于账号门店：允许读取；
- 其他情况：服务返回 `None`，路由统一返回 404。

响应载荷不增加 `store_id`，维持现有 Kiosk 最小暴露面。

## 权限语义

Kiosk 入口仍要求 `expo:write`，不改变页面访问权限。`expo_lead:read_all` 是独立的数据范围权限，只决定是否能跨店查看；普通 `expo:write` 不再隐含全门店读取能力。

## 测试

先添加失败测试，再写最小实现：

1. 绑定门店 A 的 Kiosk 账号列表只返回门店 A 线索；
2. 未绑定门店的 Kiosk 账号列表返回空集；
3. Kiosk 账号传入或访问门店 B 的客户详情时返回 404；
4. 同时拥有 `expo:write` 与 `expo_lead:read_all` 的账号可查看全部列表及任意门店详情；
5. 保留手机号脱敏、无内部发况等现有 Kiosk 最小暴露面。

验证命令：

```powershell
cd backend
pytest tests/test_expo_lead_store_scope.py -q
pytest -q
cd ..
python scripts/check_conventions.py
```

## 风险与边界

- 账号绑定多个启用门店时，可查看这些门店的线索，符合现有 PC 口径。
- 停用门店不进入普通账号数据范围；历史 `store_id IS NULL` 线索仅全量权限可见。
- 本次不调整客户删除端点；删除仍由 `expo:admin` 管理，属于独立操作权限。
- 不在前端做安全过滤，所有隔离由后端强制执行。
