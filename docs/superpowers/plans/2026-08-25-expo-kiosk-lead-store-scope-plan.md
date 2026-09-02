# Kiosk 展会线索门店隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 封堵 Kiosk 销售线索接口的跨门店读取，使其与 PC 线索台共用 `expo_lead:read_all` 数据范围规则。

**Architecture:** 路由层用现有 `_lead_store_scope()` 将认证用户解析为 `None | list[int]`，列表与详情均把该范围传入 service。列表复用 `list_leads(store_ids=...)`；详情在查询客户时直接应用门店条件，越权与不存在统一返回 404。

**Tech Stack:** FastAPI、SQLAlchemy 2.0、pytest、FastAPI TestClient

---

## 文件结构

- Modify: `backend/tests/test_expo_lead_store_scope.py` — 增加 Kiosk 列表和详情的数据范围回归测试。
- Modify: `backend/app/expo/router.py` — Kiosk 端点解析当前用户门店范围并传入 service。
- Modify: `backend/app/expo/service.py` — 详情客户查询支持 `store_ids`，列表注释改为统一口径。
- Modify: `docs/api-reference.md` — 明确 Kiosk 销售面板也按门店隔离。

### Task 1: 锁定 Kiosk 列表数据范围

**Files:**
- Modify: `backend/tests/test_expo_lead_store_scope.py`
- Modify: `backend/app/expo/router.py:589-613`

- [ ] **Step 1: 写失败测试**

在 `TestKioskLeadStoreScope` 中构造门店 A、门店 B、历史 NULL 三条客户数据，验证：普通门店 A 账号只见 A；无绑定账号为空；拥有 `expo_lead:read_all` 的 Kiosk 账号看见全部。响应断言使用 Kiosk 的 `customer_id` 字段，并确认 `phone_masked` 不包含完整手机号。

```python
class TestKioskLeadStoreScope:
    def _seed(self, db):
        store_a = _make_store(db, "Kiosk门店A", "KA001")
        store_b = _make_store(db, "Kiosk门店B", "KB001")
        cust_a = ExpoCustomer(name="甲客", phone="13800000001", store_id=store_a.id)
        cust_b = ExpoCustomer(name="乙客", phone="13800000002", store_id=store_b.id)
        cust_old = ExpoCustomer(name="老客", phone="13800000003", store_id=None)
        db.add_all([cust_a, cust_b, cust_old])
        db.commit()
        return store_a, store_b, cust_a, cust_b, cust_old

    def test_kiosk_bound_user_sees_only_own_store(self, db):
        store_a, _, cust_a, _, _ = self._seed(db)
        user = _make_user(db, "kiosk_guide")
        store_service.bind_user_to_store(db, store_a.id, user.id, is_primary=True)
        db.commit()
        with _client(db, user, PERMS_WRITE) as c:
            resp = c.get("/api/expo/kiosk/leads")
        assert resp.json()["data"]["total"] == 1
        assert resp.json()["data"]["items"][0]["customer_id"] == cust_a.id
        assert resp.json()["data"]["items"][0]["phone_masked"] == "138****0001"

    def test_kiosk_unbound_user_sees_nothing(self, db):
        self._seed(db)
        user = _make_user(db, "kiosk_nobind")
        with _client(db, user, PERMS_WRITE) as c:
            resp = c.get("/api/expo/kiosk/leads")
        assert resp.json()["data"]["total"] == 0

    def test_kiosk_read_all_sees_all_stores(self, db):
        self._seed(db)
        user = _make_user(db, "kiosk_supervisor")
        with _client(db, user, ("expo:write", "expo_lead:read_all")) as c:
            resp = c.get("/api/expo/kiosk/leads")
        assert resp.json()["data"]["total"] == 3
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd backend; pytest tests/test_expo_lead_store_scope.py::TestKioskLeadStoreScope -q`

Expected: 普通账号断言失败，实际返回全部三条线索。

- [ ] **Step 3: 写最小实现**

将 Kiosk 列表端点的 `_user` 改为 `current_user`，并传入数据范围：

```python
current_user=Depends(require_permission("expo:write")),
...
store_ids=_lead_store_scope(db, current_user),
```

- [ ] **Step 4: 运行测试并确认 GREEN**

Run: `cd backend; pytest tests/test_expo_lead_store_scope.py::TestKioskLeadStoreScope -q`

Expected: 列表测试通过；详情测试尚未添加。

- [ ] **Step 5: 提交列表隔离**

```powershell
git add backend/tests/test_expo_lead_store_scope.py backend/app/expo/router.py
git commit -m "fix(expo): scope kiosk lead list by store"
```

### Task 2: 锁定 Kiosk 详情数据范围

**Files:**
- Modify: `backend/tests/test_expo_lead_store_scope.py`
- Modify: `backend/app/expo/router.py:600-613`
- Modify: `backend/app/expo/service.py:755-820`

- [ ] **Step 1: 写失败测试**

```python
    def test_kiosk_cross_store_strategy_returns_404(self, db):
        store_a, _, _, cust_b, _ = self._seed(db)
        user = _make_user(db, "kiosk_detail_guide")
        store_service.bind_user_to_store(db, store_a.id, user.id, is_primary=True)
        db.commit()
        with _client(db, user, PERMS_WRITE) as c:
            resp = c.get(f"/api/expo/kiosk/leads/{cust_b.id}/strategy")
        assert resp.status_code == 404

    def test_kiosk_read_all_can_view_cross_store_strategy(self, db):
        _, _, _, cust_b, _ = self._seed(db)
        user = _make_user(db, "kiosk_detail_supervisor")
        with _client(db, user, ("expo:write", "expo_lead:read_all")) as c:
            resp = c.get(f"/api/expo/kiosk/leads/{cust_b.id}/strategy")
        assert resp.status_code == 200
        payload = resp.json()["data"]
        assert payload["customer"]["customer_id"] == cust_b.id
        assert "store_id" not in payload["customer"]
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `cd backend; pytest tests/test_expo_lead_store_scope.py::TestKioskLeadStoreScope::test_kiosk_cross_store_strategy_returns_404 -q`

Expected: FAIL，实际状态码为 200。

- [ ] **Step 3: 写最小实现**

`service.get_kiosk_strategy()` 增加可选范围并在读取客户时过滤：

```python
def get_kiosk_strategy(
    db: Session, customer_id: int, store_ids: list[int] | None = None,
) -> dict | None:
    if store_ids is not None and not store_ids:
        return None
    q = db.query(ExpoCustomer).filter(ExpoCustomer.id == customer_id)
    if store_ids:
        q = q.filter(ExpoCustomer.store_id.in_(store_ids))
    customer = q.first()
```

路由传入同一范围：

```python
payload = service.get_kiosk_strategy(
    db, customer_id, store_ids=_lead_store_scope(db, current_user),
)
```

- [ ] **Step 4: 运行完整聚焦测试并确认 GREEN**

Run: `cd backend; pytest tests/test_expo_lead_store_scope.py -q`

Expected: 全部测试通过。

- [ ] **Step 5: 提交详情隔离**

```powershell
git add backend/tests/test_expo_lead_store_scope.py backend/app/expo/router.py backend/app/expo/service.py
git commit -m "fix(expo): block cross-store kiosk lead details"
```

### Task 3: 文档与完整验证

**Files:**
- Modify: `docs/api-reference.md:68-69`

- [ ] **Step 1: 更新 API 文档**

在 Kiosk 销售面板端点说明中补充：默认只见账号绑定的启用门店；`expo_lead:read_all` 或超管可跨店；跨店详情返回 404。

- [ ] **Step 2: 运行完整验证**

```powershell
cd backend
pytest -q
cd ..
python scripts/check_conventions.py
git diff --check
```

Expected: pytest 0 failures；约定检查无红项；`git diff --check` 无输出。

- [ ] **Step 3: 提交文档**

```powershell
git add docs/api-reference.md
git commit -m "docs(expo): document kiosk lead store scope"
```

- [ ] **Step 4: 最终审计**

确认 `git status --short` 为空；检查提交只涉及计划列出的四个实施文件和设计/计划文档；不 push、不部署。
