"""PM Hub 核心测试：token 生命周期、版本状态机、并发上传唯一约束。

本站的「钱和货」——版本号只增不复用 / 软删后当前版本回落 / 移除名单立即失效。
"""

import io
import time
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.database import get_db
from app.pm import material_service
from app.pm.auth import entry_ip_rate_limiter, entry_rate_limiter, issue_pm_token, verify_pm_token
from app.pm.models import PmMaterial, PmMaterialVersion, PmMember, PmProject
from app.pm.router import router as pm_router
from app.pm.seed_data import MEMBERS_SEED


# ── fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def pm_seed(db, tmp_path, monkeypatch):
    """seed 项目 + 白名单 + 一个文件类资料；存储目录隔离到 tmp。"""
    monkeypatch.setattr("app.pm.service.PM_STORAGE_ROOT", tmp_path)
    monkeypatch.setattr("app.pm.router.run_diff_in_background", lambda vid: None)
    entry_rate_limiter._hits.clear()
    entry_ip_rate_limiter._hits.clear()
    project = PmProject(name="测试项目", code="alibaba-ai-agent")
    db.add(project)
    for username, display in MEMBERS_SEED[:3]:
        db.add(PmMember(username=username, display_name=display))
    db.flush()
    material = PmMaterial(
        project_id=project.id, list_no=2, name="价格体系", category="产品与报价",
        importance="required", phase=1, delivery_type="file",
    )
    db.add(material)
    offline = PmMaterial(
        project_id=project.id, list_no=14, name="阿里国际站 API 授权", category="系统权限与账号",
        importance="required", phase=1, delivery_type="offline",
    )
    db.add(offline)
    db.commit()
    return {"project": project, "material": material, "offline": offline}


@contextmanager
def pm_client(db):
    app = FastAPI()
    app.include_router(pm_router, prefix="/api/pm")

    from fastapi.responses import JSONResponse

    @app.exception_handler(ValueError)
    async def _value_error(request, exc):  # 与 app.main 的全局 400 处理同款
        return JSONResponse(status_code=400, content={"code": 400, "message": str(exc), "data": None})

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client


def _entry(client, username="liang.xz26"):
    resp = client.post("/api/pm/entry", json={"username": username})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _display_name(username):
    """从 MEMBERS_SEED 取期望显示名，避免断言硬编码具体名字。"""
    return next(d for u, d in MEMBERS_SEED if u == username)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _upload(db, material, username="liang.xz26", name="v.txt", content=b"hello"):
    return material_service.upload_version(db, material, username, name, content, "text/plain", None)


# ── token 生命周期 ───────────────────────────────────────────────────

class TestToken:
    def test_entry_ok_and_me(self, db, pm_seed):
        with pm_client(db) as client:
            data = _entry(client)
            assert data["display_name"] == _display_name("liang.xz26")
            resp = client.get("/api/pm/me", headers=_auth(data["token"]))
            assert resp.status_code == 200
            assert resp.json()["data"]["username"] == "liang.xz26"

    def test_entry_unknown_user_uniform_message(self, db, pm_seed):
        with pm_client(db) as client:
            resp = client.post("/api/pm/entry", json={"username": "nobody.here99"})
            assert resp.status_code == 401
            assert resp.json()["detail"] == "无法验证，请联系亮哥"

    def test_entry_rate_limit(self, db, pm_seed):
        with pm_client(db) as client:
            for _ in range(5):
                client.post("/api/pm/entry", json={"username": "bad.actor77"})
            resp = client.post("/api/pm/entry", json={"username": "bad.actor77"})
            assert resp.status_code == 429
            assert resp.json()["detail"] == "无法验证，请联系亮哥"  # 提示仍不区分原因

    def test_entry_ip_rate_limit_rotating_usernames(self, db, pm_seed):
        """轮换用户名绕不过 IP 维度：同一 IP 20 次失败后第 21 个新用户名也被拦。"""
        with pm_client(db) as client:
            for i in range(20):
                client.post("/api/pm/entry", json={"username": f"rotate.{i:02d}"})
            resp = client.post("/api/pm/entry", json={"username": "rotate.fresh"})
            assert resp.status_code == 429
            # 合法用户名同样被同 IP 拦截（预检在白名单查询之前）
            resp = client.post("/api/pm/entry", json={"username": MEMBERS_SEED[0][0]})
            assert resp.status_code == 429

    def test_client_ip_header_priority(self):
        """X-Real-IP（云 Nginx 覆盖式写入）优先；XFF 只信末位；无头落直连地址。"""
        from types import SimpleNamespace

        from app.pm.auth import client_ip

        def _req(headers, host="10.0.0.1"):
            return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))

        assert client_ip(_req({"X-Real-IP": "1.2.3.4", "X-Forwarded-For": "9.9.9.9, 1.2.3.4"})) == "1.2.3.4"
        assert client_ip(_req({"X-Forwarded-For": "attacker-fake, 5.6.7.8"})) == "5.6.7.8"
        assert client_ip(_req({})) == "10.0.0.1"

    def test_expired_token_rejected(self, db, pm_seed):
        settings = get_settings()
        original = settings.PM_TOKEN_TTL_DAYS
        settings.PM_TOKEN_TTL_DAYS = -1  # 签发即过期
        try:
            token = issue_pm_token("liang.xz26")
        finally:
            settings.PM_TOKEN_TTL_DAYS = original
        assert verify_pm_token(token) is None
        with pm_client(db) as client:
            resp = client.get("/api/pm/me", headers=_auth(token))
            assert resp.status_code == 401

    def test_epoch_bump_invalidates_all(self, db, pm_seed):
        token = issue_pm_token("liang.xz26")
        assert verify_pm_token(token) == "liang.xz26"
        settings = get_settings()
        original = settings.PM_TOKEN_EPOCH
        settings.PM_TOKEN_EPOCH = original + 1  # 全局版本号 +1 → 全员重新验证
        try:
            assert verify_pm_token(token) is None
        finally:
            settings.PM_TOKEN_EPOCH = original

    def test_tampered_token_rejected(self, db, pm_seed):
        token = issue_pm_token("liang.xz26")
        assert verify_pm_token(token + "x") is None

    def test_removed_member_fails_immediately(self, db, pm_seed):
        """token 未过期，但人被移出名单 → 下一请求立即 401（不等 token 过期）。"""
        token = issue_pm_token("liang.xz26")
        with pm_client(db) as client:
            assert client.get("/api/pm/me", headers=_auth(token)).status_code == 200
            member = db.query(PmMember).filter(PmMember.username == "liang.xz26").first()
            member.is_active = 0
            db.commit()
            assert client.get("/api/pm/me", headers=_auth(token)).status_code == 401


# ── 版本状态机 ───────────────────────────────────────────────────────

class TestVersionStateMachine:
    def test_upload_v1_not_applicable_v2_pending(self, db, pm_seed):
        m = pm_seed["material"]
        v1 = _upload(db, m, content=b"v1 content")
        assert v1.version_no == 1 and v1.diff_status == "not_applicable"
        v2 = _upload(db, m, content=b"v2 content")
        assert v2.version_no == 2 and v2.diff_status == "pending"

    def test_upload_advances_status_to_submitted(self, db, pm_seed):
        m = pm_seed["material"]
        assert m.status == "not_started"
        _upload(db, m)
        db.refresh(m)
        assert m.status == "submitted"

    def test_current_falls_back_after_delete_and_number_not_reused(self, db, pm_seed):
        """删 v3 后当前版本回落 v2；下一次上传是 v4 而非复用 v3。"""
        m = pm_seed["material"]
        _upload(db, m, content=b"1")
        _upload(db, m, content=b"2")
        v3 = _upload(db, m, content=b"3")
        assert material_service.current_version(db, m.id).version_no == 3
        material_service.delete_version(db, v3, "liang.xz26")
        assert material_service.current_version(db, m.id).version_no == 2
        v4 = _upload(db, m, content=b"4")
        assert v4.version_no == 4
        # v4 的差异对比对象是 v2（未删除的最大前一版）
        assert material_service.previous_version(db, v4).version_no == 2

    def test_offline_material_rejects_upload(self, db, pm_seed):
        with pytest.raises(ValueError, match="禁止上传原文"):
            _upload(db, pm_seed["offline"])

    def test_oversize_rejected(self, db, pm_seed, monkeypatch):
        monkeypatch.setattr(get_settings(), "PM_MAX_UPLOAD_MB", 0)  # 任何文件都超限
        with pytest.raises(ValueError, match="单文件上限"):
            _upload(db, pm_seed["material"])

    def test_unique_constraint_backstop(self, db, pm_seed):
        m = pm_seed["material"]
        _upload(db, m)
        dup = PmMaterialVersion(
            material_id=m.id, version_no=1, file_path="x/y.txt", original_name="y.txt",
            file_size=1, uploaded_by="liang.xz26",
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    def test_concurrent_conflict_retries_with_new_number(self, db, pm_seed, monkeypatch):
        """模拟并发撞号：首次取号返回过期值撞唯一约束，重试取到新号成功。"""
        m = pm_seed["material"]
        _upload(db, m, content=b"existing v1")
        _upload(db, m, content=b"existing v2")
        calls = iter([2, 3])  # 第一次返回 2（与存量 v2 撞），重试返回 3
        monkeypatch.setattr(
            material_service, "_next_version_no", lambda _db, _mid: next(calls)
        )
        v = _upload(db, m, content=b"racy upload")
        assert v.version_no == 3

    def test_deleted_version_download_rejected(self, db, pm_seed):
        m = pm_seed["material"]
        v = _upload(db, m)
        material_service.delete_version(db, v, "liang.xz26")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = client.get(f"/api/pm/versions/{v.id}/file-link", headers=_auth(token))
            assert resp.status_code == 404

    def test_deleted_material_name_freed_and_download_blocked(self, db, pm_seed):
        m = pm_seed["material"]
        v = _upload(db, m)
        material_service.delete_material(db, m, "liang.xz26")
        # 原名被释放，可重建同名条目
        m2 = material_service.create_material(
            db, pm_seed["project"].id, "liang.xz26", {"name": "价格体系", "delivery_type": "file"}
        )
        assert m2.id != m.id
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = client.get(f"/api/pm/versions/{v.id}/file-link", headers=_auth(token))
            assert resp.status_code == 404  # 整条资料删除 → 下载立即拒绝

    def test_duplicate_name_rejected(self, db, pm_seed):
        with pytest.raises(ValueError, match="唯一"):
            material_service.create_material(
                db, pm_seed["project"].id, "liang.xz26", {"name": "价格体系"}
            )


# ── 签名文件 URL ─────────────────────────────────────────────────────

class TestSignedFileUrl:
    def _setup(self, db, pm_seed, name="价格表.txt", content=b"secret"):
        m = pm_seed["material"]
        v = _upload(db, m, name=name, content=content)
        return m, v

    def test_full_flow_download_renamed(self, db, pm_seed):
        m, v = self._setup(db, pm_seed)
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = client.get(f"/api/pm/versions/{v.id}/file-link", headers=_auth(token))
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["download_name"] == "价格体系_v1.txt"
            file_resp = client.get(data["url"])  # 无 Authorization——签名即鉴权
            assert file_resp.status_code == 200
            assert file_resp.content == b"secret"
            from urllib.parse import quote
            assert quote("价格体系_v1.txt") in file_resp.headers["content-disposition"]
            assert file_resp.headers["x-content-type-options"] == "nosniff"

    def test_tampered_token_403(self, db, pm_seed):
        _, v = self._setup(db, pm_seed)
        with pm_client(db) as client:
            resp = client.get(f"/api/pm/files/{v.id}?token=bad&expires={int(time.time()) + 300}")
            assert resp.status_code == 403

    def test_expired_link_403(self, db, pm_seed):
        _, v = self._setup(db, pm_seed)
        from app.pm.service import make_file_sign_token
        expires = int(time.time()) - 10  # 已过期
        token = make_file_sign_token(v.id, expires)
        with pm_client(db) as client:
            resp = client.get(f"/api/pm/files/{v.id}?token={token}&expires={expires}")
            assert resp.status_code == 403

    def test_html_forced_attachment(self, db, pm_seed):
        """HTML 类强制 attachment，不内联渲染（防存储型 XSS）。"""
        _, v = self._setup(db, pm_seed, name="evil.html", content=b"<script>alert(1)</script>")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = client.get(
                f"/api/pm/versions/{v.id}/file-link?disposition=inline", headers=_auth(token)
            )
            url = resp.json()["data"]["url"]
            assert "disposition=attachment" in url  # inline 请求被降级
            file_resp = client.get(url.replace("attachment", "inline"))  # 即使强刷 inline
            assert "attachment" in file_resp.headers["content-disposition"]


# ── API 端到端（路由接线 + 鉴权依赖） ──────────────────────────────────

class TestApiFlow:
    def test_unauthenticated_401(self, db, pm_seed):
        with pm_client(db) as client:
            assert client.get("/api/pm/materials").status_code == 401
            assert client.get("/api/pm/dashboard").status_code == 401
            assert client.get("/api/pm/activity").status_code == 401

    def test_upload_list_dashboard_activity(self, db, pm_seed):
        with pm_client(db) as client:
            token = _entry(client)["token"]
            mid = pm_seed["material"].id
            resp = client.post(
                f"/api/pm/materials/{mid}/versions",
                files={"file": ("价格体系-7月.xlsx", io.BytesIO(b"fake xlsx"), "application/vnd.ms-excel")},
                data={"change_note": "初版"},
                headers=_auth(token),
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["version_no"] == 1

            resp = client.get("/api/pm/materials", headers=_auth(token))
            items = resp.json()["data"]
            target = next(i for i in items if i["id"] == mid)
            assert target["current_version_no"] == 1
            assert target["last_uploaded_by"] == "liang.xz26"

            resp = client.get("/api/pm/dashboard", headers=_auth(token))
            dash = resp.json()["data"]
            assert dash["materials"]["total"] == 2
            assert dash["materials"]["done"] == 1  # 上传后自动转已提交
            assert len(dash["phases"]) == 4

            resp = client.get("/api/pm/activity", headers=_auth(token))
            acts = resp.json()["data"]["items"]
            actions = {a["action"] for a in acts}
            assert "upload_version" in actions and "entry" in actions
            up = next(a for a in acts if a["action"] == "upload_version")
            assert up["display_name"] == _display_name("liang.xz26")
            assert up["object_name"] == "价格体系 v1"

    def test_task_crud_and_blocked_reason_required(self, db, pm_seed):
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = client.post("/api/pm/tasks", json={
                "title": "workshop 定标准", "material_ids": [pm_seed["material"].id],
            }, headers=_auth(token))
            assert resp.status_code == 200
            tid = resp.json()["data"]["id"]

            # blocked 不带原因 → 400
            resp = client.put(f"/api/pm/tasks/{tid}", json={"status": "blocked"}, headers=_auth(token))
            assert resp.status_code == 400
            resp = client.put(f"/api/pm/tasks/{tid}", json={
                "status": "blocked", "blocked_reason": "等顾问给接口权限",
            }, headers=_auth(token))
            assert resp.status_code == 200

            resp = client.get("/api/pm/tasks", headers=_auth(token))
            task = next(t for t in resp.json()["data"] if t["id"] == tid)
            assert task["status"] == "blocked"
            assert task["materials"][0]["name"] == "价格体系"


# ── 在线编辑保存（Phase 2 §6.1）─────────────────────────────────────

class TestTextEdit:
    """编辑与上传共用同一版本通道：版本号只增、状态推进、diff 触发全部一致。"""

    def _save(self, client, token, material_id, content, base_no=None, note=None):
        payload = {"content": content}
        if base_no is not None:
            payload["base_version_no"] = base_no
        if note is not None:
            payload["change_note"] = note
        return client.post(
            f"/api/pm/materials/{material_id}/versions/text",
            json=payload, headers=_auth(token),
        )

    def test_save_text_creates_next_version_same_ext(self, db, pm_seed):
        from app.pm.service import to_abs

        m = pm_seed["material"]
        _upload(db, m, name="说明.md", content="# v1\n".encode("utf-8"))
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = self._save(client, token, m.id, "# v2\n新增一行", base_no=1, note="在线编辑")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["version_no"] == 2
            assert data["ext"] == ".md"
            assert data["diff_status"] == "pending"
        v2 = material_service.get_version_by_no(db, m.id, 2)
        assert to_abs(v2.file_path).read_text(encoding="utf-8") == "# v2\n新增一行"
        assert v2.original_name == "说明.md"  # 文件名承接被编辑版本

    def test_save_text_audited_as_edit_version(self, db, pm_seed):
        from app.pm.models import PmActivityLog

        m = pm_seed["material"]
        _upload(db, m, name="说明.md", content=b"# v1")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            assert self._save(client, token, m.id, "# v2").status_code == 200
        log = db.query(PmActivityLog).filter(PmActivityLog.action == "edit_version").first()
        assert log is not None
        assert '"based_on": 1' in log.detail

    def test_save_text_defaults_to_current_head(self, db, pm_seed):
        m = pm_seed["material"]
        _upload(db, m, name="说明.md", content=b"1")
        _upload(db, m, name="说明.md", content=b"2")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = self._save(client, token, m.id, "基于头版编辑")
            assert resp.json()["data"]["version_no"] == 3

    def test_save_text_on_old_base_still_next_no(self, db, pm_seed):
        """基于旧版编辑不回填旧号：版本号永远 max+1（设计稿基线冲突口径）。"""
        m = pm_seed["material"]
        _upload(db, m, name="说明.md", content=b"1")
        _upload(db, m, name="说明.md", content=b"2")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = self._save(client, token, m.id, "基于 v1 改的", base_no=1)
            assert resp.json()["data"]["version_no"] == 3

    def test_save_text_rejects_non_text_base(self, db, pm_seed):
        m = pm_seed["material"]
        _upload(db, m, name="报价.xlsx", content=b"fake xlsx")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = self._save(client, token, m.id, "improper")
            assert resp.status_code == 400
            assert "在线编辑" in resp.json()["message"]

    def test_save_text_blank_content_rejected(self, db, pm_seed):
        m = pm_seed["material"]
        _upload(db, m, name="说明.md", content=b"# v1")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = self._save(client, token, m.id, "   \n  ")
            assert resp.status_code == 400

    def test_save_text_no_versions_404(self, db, pm_seed):
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = self._save(client, token, pm_seed["material"].id, "无中生有")
            assert resp.status_code == 404


# ── 对抗性审查回归（2026-07-17）─────────────────────────────────────

class TestAdversarialRegression:
    def test_external_url_scheme_rejected(self, db, pm_seed):
        """javascript: 外链是存储型 XSS（本站 token 即身份）——必须拒绝。"""
        with pytest.raises(ValueError, match="http"):
            material_service.create_material(
                db, pm_seed["project"].id, "liang.xz26",
                {"name": "恶意链接", "delivery_type": "link", "external_url": "javascript:alert(1)"},
            )
        # update 路径同样拒绝
        m = pm_seed["material"]
        with pytest.raises(ValueError, match="http"):
            material_service.update_material(db, m, "liang.xz26", {"external_url": "data:text/html,x"})

    def test_link_type_requires_url(self, db, pm_seed):
        with pytest.raises(ValueError, match="链接地址"):
            material_service.create_material(
                db, pm_seed["project"].id, "liang.xz26",
                {"name": "视频库", "delivery_type": "link"},
            )

    def test_update_rename_collision_returns_400_not_500(self, db, pm_seed):
        m2 = material_service.create_material(
            db, pm_seed["project"].id, "liang.xz26", {"name": "另一个条目", "delivery_type": "file"}
        )
        with pytest.raises(ValueError, match="唯一"):
            material_service.update_material(db, m2, "liang.xz26", {"name": "价格体系"})

    def test_blocked_task_partial_update_not_killed(self, db, pm_seed):
        """已 blocked 的任务改负责人（不带 blocked_reason）不应被必填校验误杀。"""
        from app.pm.task_service import create_task, update_task
        task = create_task(db, pm_seed["project"].id, "liang.xz26",
                           {"title": "等权限", "status": "blocked", "blocked_reason": "等顾问"})
        update_task(db, task, "liang.xz26", {"assignee": "sunzh.qm41"})
        db.refresh(task)
        assert task.assignee == "sunzh.qm41"
        assert task.blocked_reason == "等顾问"  # 原因保留

    def test_retry_diff_pending_rejected(self, db, pm_seed):
        m = pm_seed["material"]
        _upload(db, m, content=b"1")
        v2 = _upload(db, m, content=b"2")
        assert v2.diff_status == "pending"
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = client.post(f"/api/pm/versions/{v2.id}/retry-diff", headers=_auth(token))
            assert resp.status_code == 400  # pending 重入会并发重复调 AI

    def test_svg_forced_attachment(self, db, pm_seed):
        m = pm_seed["material"]
        v = _upload(db, m, name="icon.svg", content=b"<svg onload=alert(1)></svg>")
        from app.pm.material_service import inline_disposition_allowed
        assert not inline_disposition_allowed(v)

    def test_delete_material_long_name_no_overflow(self, db, pm_seed):
        m = material_service.create_material(
            db, pm_seed["project"].id, "liang.xz26", {"name": "长" * 250, "delivery_type": "file"}
        )
        material_service.delete_material(db, m, "liang.xz26")
        db.refresh(m)
        assert len(m.name) <= 256
        assert m.name.endswith(f"#del{m.id}")

    def test_success_does_not_consume_rate_limit(self, db, pm_seed):
        """限速只计失败：连续 5 次成功进入后第 6 次仍放行。"""
        with pm_client(db) as client:
            for _ in range(6):
                resp = client.post("/api/pm/entry", json={"username": "liang.xz26"})
                assert resp.status_code == 200


# ── 版本评论 ─────────────────────────────────────────────────────────

class TestComments:
    def test_comment_crud_count_and_activity(self, db, pm_seed):
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            token = _entry(client)["token"]
            resp = client.post(f"/api/pm/versions/{v1.id}/comments",
                               json={"body": "价格矩阵缺 FOB 条款说明"}, headers=_auth(token))
            assert resp.status_code == 200, resp.text
            created = resp.json()["data"]
            assert created["author"] == "liang.xz26"
            assert created["version_no"] == 1  # 评论挂在具体版本上

            items = client.get(f"/api/pm/materials/{material.id}/comments", headers=_auth(token)).json()["data"]
            assert len(items) == 1 and items[0]["body"] == "价格矩阵缺 FOB 条款说明"
            assert items[0]["version_no"] == 1

            detail = client.get(f"/api/pm/materials/{material.id}", headers=_auth(token)).json()["data"]
            assert detail["comment_count"] == 1
            listing = client.get("/api/pm/materials", headers=_auth(token)).json()["data"]
            assert next(m for m in listing if m["id"] == material.id)["comment_count"] == 1

            acts = client.get("/api/pm/activity?object_type=comment", headers=_auth(token)).json()["data"]
            assert acts["total"] == 1
            assert acts["items"][0]["action_label"] == "评论了资料"
            assert acts["items"][0]["object_name"] == "价格体系 v1"

    def test_reply_flattens_to_top_level(self, db, pm_seed):
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            t1 = _entry(client, "liang.xz26")["token"]
            t2 = _entry(client, "sunzh.qm41")["token"]
            top = client.post(f"/api/pm/versions/{v1.id}/comments",
                              json={"body": "顶层"}, headers=_auth(t1)).json()["data"]
            reply = client.post(f"/api/pm/versions/{v1.id}/comments",
                                json={"body": "一层回复", "parent_id": top["id"]},
                                headers=_auth(t2)).json()["data"]
            assert reply["parent_id"] == top["id"]
            # 回复「回复」→ 自动拍平挂到顶层
            nested = client.post(f"/api/pm/versions/{v1.id}/comments",
                                 json={"body": "楼中楼", "parent_id": reply["id"]},
                                 headers=_auth(t1)).json()["data"]
            assert nested["parent_id"] == top["id"]

            items = client.get(f"/api/pm/materials/{material.id}/comments", headers=_auth(t1)).json()["data"]
            assert len(items) == 1
            assert [r["body"] for r in items[0]["replies"]] == ["一层回复", "楼中楼"]

    def test_reply_inherits_thread_version(self, db, pm_seed):
        """新版本卡里回复老线程：回复仍归属线程所在版本，线程不跨卡漂移。"""
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            token = _entry(client)["token"]
            top = client.post(f"/api/pm/versions/{v1.id}/comments",
                              json={"body": "针对 v1"}, headers=_auth(token)).json()["data"]
            v2 = _upload(db, material, name="v2.txt", content=b"hello2")
            reply = client.post(f"/api/pm/versions/{v2.id}/comments",
                                json={"body": "补充", "parent_id": top["id"]},
                                headers=_auth(token)).json()["data"]
            assert reply["version_no"] == 1

    def test_comment_on_deleted_version_rejected(self, db, pm_seed):
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            token = _entry(client)["token"]
            client.post(f"/api/pm/versions/{v1.id}/comments", json={"body": "留档"}, headers=_auth(token))
            client.delete(f"/api/pm/versions/{v1.id}", headers=_auth(token))
            resp = client.post(f"/api/pm/versions/{v1.id}/comments", json={"body": "x"}, headers=_auth(token))
            assert resp.status_code == 404
            # 已删版本上的历史评论仍可见
            items = client.get(f"/api/pm/materials/{material.id}/comments", headers=_auth(token)).json()["data"]
            assert [c["body"] for c in items] == ["留档"]

    def test_delete_author_only(self, db, pm_seed):
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            t1 = _entry(client, "liang.xz26")["token"]
            t2 = _entry(client, "sunzh.qm41")["token"]
            cid = client.post(f"/api/pm/versions/{v1.id}/comments",
                              json={"body": "待删"}, headers=_auth(t1)).json()["data"]["id"]
            assert client.delete(f"/api/pm/comments/{cid}", headers=_auth(t2)).status_code == 403
            assert client.delete(f"/api/pm/comments/{cid}", headers=_auth(t1)).status_code == 200
            # 已删除后再删 → 404；列表不再返回；计数归零
            assert client.delete(f"/api/pm/comments/{cid}", headers=_auth(t1)).status_code == 404
            assert client.get(f"/api/pm/materials/{material.id}/comments", headers=_auth(t1)).json()["data"] == []
            detail = client.get(f"/api/pm/materials/{material.id}", headers=_auth(t1)).json()["data"]
            assert detail["comment_count"] == 0

    def test_deleted_parent_keeps_placeholder_for_alive_replies(self, db, pm_seed):
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            t1 = _entry(client, "liang.xz26")["token"]
            t2 = _entry(client, "sunzh.qm41")["token"]
            top = client.post(f"/api/pm/versions/{v1.id}/comments",
                              json={"body": "顶层"}, headers=_auth(t1)).json()["data"]
            client.post(f"/api/pm/versions/{v1.id}/comments",
                        json={"body": "回复", "parent_id": top["id"]}, headers=_auth(t2))
            client.delete(f"/api/pm/comments/{top['id']}", headers=_auth(t1))

            items = client.get(f"/api/pm/materials/{material.id}/comments", headers=_auth(t1)).json()["data"]
            assert len(items) == 1
            assert items[0]["is_deleted"] is True and items[0]["body"] is None
            assert [r["body"] for r in items[0]["replies"]] == ["回复"]
            # 占位父评论不计数，只计活回复
            detail = client.get(f"/api/pm/materials/{material.id}", headers=_auth(t1)).json()["data"]
            assert detail["comment_count"] == 1

    def test_reply_to_deleted_top_continues_placeholder_thread(self, db, pm_seed):
        """占位线程可续贴：顶层被删后，对其回复不能是死按钮（审查 P1 回归）。"""
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            t1 = _entry(client, "liang.xz26")["token"]
            t2 = _entry(client, "sunzh.qm41")["token"]
            top = client.post(f"/api/pm/versions/{v1.id}/comments",
                              json={"body": "顶层"}, headers=_auth(t1)).json()["data"]
            client.post(f"/api/pm/versions/{v1.id}/comments",
                        json={"body": "回复1", "parent_id": top["id"]}, headers=_auth(t2))
            client.delete(f"/api/pm/comments/{top['id']}", headers=_auth(t1))
            resp = client.post(f"/api/pm/versions/{v1.id}/comments",
                               json={"body": "续贴", "parent_id": top["id"]}, headers=_auth(t2))
            assert resp.status_code == 200, resp.text
            items = client.get(f"/api/pm/materials/{material.id}/comments", headers=_auth(t1)).json()["data"]
            assert items[0]["is_deleted"] is True
            assert [r["body"] for r in items[0]["replies"]] == ["回复1", "续贴"]

    def test_invalid_targets_rejected(self, db, pm_seed):
        material = pm_seed["material"]
        v1 = _upload(db, material)
        # 第二份文件类资料 + 版本（跨资料回复用）
        other = PmMaterial(project_id=pm_seed["project"].id, name="产品目录",
                           category="产品与报价", delivery_type="file")
        db.add(other)
        db.commit()
        v_other = _upload(db, other, name="cat.txt", content=b"catalog")
        with pm_client(db) as client:
            token = _entry(client)["token"]
            assert client.post("/api/pm/versions/999999/comments",
                               json={"body": "x"}, headers=_auth(token)).status_code == 404
            assert client.post(f"/api/pm/versions/{v1.id}/comments",
                               json={"body": "x", "parent_id": 999999},
                               headers=_auth(token)).status_code == 400
            # 跨资料回复：父评论属于另一条资料 → 400
            top = client.post(f"/api/pm/versions/{v1.id}/comments",
                              json={"body": "顶层"}, headers=_auth(token)).json()["data"]
            assert client.post(f"/api/pm/versions/{v_other.id}/comments",
                               json={"body": "x", "parent_id": top["id"]},
                               headers=_auth(token)).status_code == 400
            # 空白正文 → 400（纯空格绕过 schema min_length，由 service 拦）
            assert client.post(f"/api/pm/versions/{v1.id}/comments",
                               json={"body": "   "}, headers=_auth(token)).status_code == 400

    def test_reply_inherits_version_audit_and_deleted_thread_sidedoor(self, db, pm_seed):
        """继承版本的审计锚点是线程版本号；线程所在版本已删则经存活版本续贴也 400。"""
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            token = _entry(client)["token"]
            top = client.post(f"/api/pm/versions/{v1.id}/comments",
                              json={"body": "针对 v1"}, headers=_auth(token)).json()["data"]
            v2 = _upload(db, material, name="v2.txt", content=b"hello2")
            client.post(f"/api/pm/versions/{v2.id}/comments",
                        json={"body": "补充", "parent_id": top["id"]}, headers=_auth(token))
            acts = client.get("/api/pm/activity?object_type=comment", headers=_auth(token)).json()["data"]
            assert acts["items"][0]["object_name"] == "价格体系 v1"  # 回复审计锚点=线程版本

            client.delete(f"/api/pm/versions/{v1.id}", headers=_auth(token))
            resp = client.post(f"/api/pm/versions/{v2.id}/comments",
                               json={"body": "侧门", "parent_id": top["id"]}, headers=_auth(token))
            assert resp.status_code == 400

    def test_comment_on_version_of_deleted_material_rejected(self, db, pm_seed):
        material = pm_seed["material"]
        v1 = _upload(db, material)
        with pm_client(db) as client:
            token = _entry(client)["token"]
            client.delete(f"/api/pm/materials/{material.id}", headers=_auth(token))
            resp = client.post(f"/api/pm/versions/{v1.id}/comments",
                               json={"body": "x"}, headers=_auth(token))
            assert resp.status_code == 404
