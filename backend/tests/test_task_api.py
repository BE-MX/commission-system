"""HTTP 层：权限、信封、错误码映射、owner 隔离。"""
from app.task import module_service
from tests.task_helpers import make_user, task_client


def _setup(db):
    module_service.seed_default_modules(db)
    return make_user(db, "api_owner")


def test_create_list_detail_roundtrip(db):
    owner = _setup(db)
    with task_client(db, owner) as c:
        r = c.post("/api/task/items", json={"title": "写汇报", "module_key": "custom.report", "priority": "P1"})
        assert r.status_code == 200 and r.json()["code"] == 200
        tid = r.json()["data"]["id"]
        kid = c.post("/api/task/items", json={"title": "收集数据", "parent_id": tid}).json()["data"]
        tree = c.get("/api/task/items").json()["data"]
        assert tree[0]["id"] == tid and tree[0]["children"][0]["id"] == kid["id"]
        detail = c.get(f"/api/task/items/{tid}").json()["data"]
        assert detail["code"] == f"T-{tid}" and detail["events"][0]["type"] == "created"


def test_read_only_permission_cannot_write(db):
    owner = _setup(db)
    with task_client(db, owner, permissions=("task:read",)) as c:
        assert c.get("/api/task/items").status_code == 200
        assert c.post("/api/task/items", json={"title": "x"}).status_code == 403


def test_no_permission_forbidden(db):
    owner = _setup(db)
    with task_client(db, owner, permissions=()) as c:
        assert c.get("/api/task/items").status_code == 403


def test_other_owner_gets_404(db):
    owner = _setup(db)
    other = make_user(db, "api_other")
    with task_client(db, owner) as c:
        tid = c.post("/api/task/items", json={"title": "mine"}).json()["data"]["id"]
    with task_client(db, other) as c:
        assert c.get(f"/api/task/items/{tid}").status_code == 404
        assert c.patch(f"/api/task/items/{tid}", json={"title": "hack"}).status_code == 404
        assert c.get("/api/task/items").json()["data"] == []


def test_status_conflict_carries_code(db):
    owner = _setup(db)
    with task_client(db, owner) as c:
        pid = c.post("/api/task/items", json={"title": "p"}).json()["data"]["id"]
        c.post("/api/task/items", json={"title": "c", "parent_id": pid})
        r = c.post(f"/api/task/items/{pid}/status", json={"status": "done"})
        assert r.status_code == 409
        assert r.json()["detail"] == {"message": "还有 1 个子任务没结束", "code": "open_children", "open_children": 1}
        r = c.post(f"/api/task/items/{pid}/status", json={"status": "done", "confirm_open_children": True})
        assert r.json()["data"]["status"] == "done"


def test_modules_stats_trash_and_links(db):
    owner = _setup(db)
    with task_client(db, owner) as c:
        keys = {m["key"] for m in c.get("/api/task/modules").json()["data"]}
        assert "custom.report" in keys
        key = c.post("/api/task/modules/custom", json={"title": "副业"}).json()["data"]["key"]
        assert key.startswith("custom.u")
        tid = c.post("/api/task/items", json={"title": "t", "due_date": "2000-01-01"}).json()["data"]["id"]
        assert c.get("/api/task/stats").json()["data"]["overdue"] == 1
        link = c.post(f"/api/task/items/{tid}/links", json={"kind": "doc", "ref": "docs/a.md"}).json()["data"]
        assert c.delete(f"/api/task/links/{link['id']}").status_code == 200
        c.delete(f"/api/task/items/{tid}")
        assert [t["id"] for t in c.get("/api/task/trash").json()["data"]] == [tid]
        c.post(f"/api/task/items/{tid}/restore")
        assert c.get("/api/task/trash").json()["data"] == []


def test_ai_draft_endpoint_degrades(db, monkeypatch):
    owner = _setup(db)

    def boom(**kwargs):
        raise RuntimeError("down")
    monkeypatch.setattr("app.ai.service.chat", boom)
    with task_client(db, owner) as c:
        r = c.post("/api/task/ai/draft", json={"text": "写汇报", "module_key": "custom.report"})
        assert r.json()["data"]["degraded"] is True


def test_brief_today_endpoint(db, monkeypatch):
    owner = _setup(db)
    monkeypatch.setattr("app.ai.service.chat", lambda **kw: {"content": "{}"})
    with task_client(db, owner) as c:
        c.post("/api/task/items", json={"title": "紧急", "priority": "P0"})
        data = c.get("/api/task/brief/today").json()["data"]
        assert data["top"][0]["title"] == "紧急" and data["source"] == "template"
