"""发型×发色组合三角度参考图（072 迁移）测试。

覆盖：
- _build_prompt 组合参考图分支（有组合图→用图组+参考取色子句、无 recolor 文字；
  缺图/无组合→回退发型图+文字上色；原色→发型图无上色）
- start_composites 按 wig 注入 ref_photos
- service：kiosk 发色过滤 / 管理端矩阵 / upsert / delete
"""

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.utils import create_access_token
from app.core.database import get_db
from app.expo import ai_pipeline, service
from app.expo.models import ExpoHairColor, ExpoResult, ExpoSession, ExpoWig, ExpoWigColor
from app.expo.schemas import HairColorUpsert, WigColorImagesUpsert, WigUpsert


@contextmanager
def _client(db, permissions):
    from app.expo.router import router
    app = FastAPI()
    app.include_router(router, prefix="/api/expo")

    def override_db():
        yield db
    app.dependency_overrides[get_db] = override_db
    token = create_access_token({"sub": "1", "username": "u1", "roles": [], "permissions": permissions})
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        yield c


def _session(photo="uploads/expo/photos/x.jpg"):
    return ExpoSession(customer_id=1, photo_path=photo, mode="tryon")


# ---------------- _build_prompt 组合参考图分支 ----------------

def test_build_prompt_uses_combo_photos_no_recolor(tmp_path, monkeypatch):
    """有组合三角度图且文件在 → 用组合图当参考 + 参考取色子句，不出现 recolor 文字。"""
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    photos = []
    for i in range(3):
        p = tmp_path / "uploads" / "expo" / "wigs" / f"combo_{i}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"img")
        photos.append(f"uploads/expo/wigs/combo_{i}.jpg")
    wig = ExpoWig(model_no="LS-1", name="轻盈波波", wig_description="short bob",
                  angle_photos=["uploads/expo/wigs/default.jpg"])
    row = ExpoResult(session_id=1, wig_id=1, hair_color_json={
        "hair_color_id": 5, "name": "栗棕", "code": "6", "hex": "#5a3a26",
        "ref_photos": photos,
    })
    prompt, images, size = ai_pipeline._build_prompt(_session(), row, wig)
    assert "reference images already show the exact target color" in prompt
    assert "recolor it to this exact" not in prompt  # 无文字上色
    assert len(images) == 4  # 自拍 + 3 组合图
    assert str((tmp_path / "uploads/expo/wigs/combo_0.jpg")) in [str(i) for i in images]


def test_build_prompt_combo_missing_files_falls_back_to_text(tmp_path, monkeypatch):
    """组合图路径在快照里但文件已丢 → 回退发型自身图 + 文字上色，不留空参考。"""
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    default = tmp_path / "uploads" / "expo" / "wigs" / "default.jpg"
    default.parent.mkdir(parents=True, exist_ok=True)
    default.write_bytes(b"img")
    wig = ExpoWig(model_no="LS-1", name="波波", wig_description="bob",
                  angle_photos=["uploads/expo/wigs/default.jpg"])
    row = ExpoResult(session_id=1, wig_id=1, hair_color_json={
        "hair_color_id": 5, "name": "栗棕", "code": "6", "hex": "#5a3a26",
        "ref_photos": ["uploads/expo/wigs/gone_0.jpg"],  # 文件不存在
    })
    prompt, images, size = ai_pipeline._build_prompt(_session(), row, wig)
    assert "recolor it to this exact" in prompt  # 文字上色兜底
    assert "reference images already show" not in prompt
    assert len(images) == 2  # 自拍 + 发型默认图


def test_build_prompt_original_color_no_combo(tmp_path, monkeypatch):
    """原色（hair_color_json=None）→ 用发型图，无任何上色子句。"""
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    default = tmp_path / "uploads" / "expo" / "wigs" / "d.jpg"
    default.parent.mkdir(parents=True, exist_ok=True)
    default.write_bytes(b"img")
    wig = ExpoWig(model_no="LS-2", name="短发", wig_description="pixie",
                  angle_photos=["uploads/expo/wigs/d.jpg"])
    row = ExpoResult(session_id=1, wig_id=2, hair_color_json=None)
    prompt, images, _ = ai_pipeline._build_prompt(_session(), row, wig)
    assert "recolor" not in prompt.lower()
    assert "reference images already show" not in prompt
    assert len(images) == 2


def test_build_prompt_color_without_combo_uses_text(tmp_path, monkeypatch):
    """选了色但快照无 ref_photos（该发型该色未备图）→ 文字上色兜底。"""
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    default = tmp_path / "uploads" / "expo" / "wigs" / "d.jpg"
    default.parent.mkdir(parents=True, exist_ok=True)
    default.write_bytes(b"img")
    wig = ExpoWig(model_no="LS-3", name="卷发", wig_description="curly",
                  angle_photos=["uploads/expo/wigs/d.jpg"])
    row = ExpoResult(session_id=1, wig_id=3, hair_color_json={
        "hair_color_id": 5, "name": "亚麻金", "code": "613", "hex": "#d9c08a",
    })
    prompt, _, _ = ai_pipeline._build_prompt(_session(), row, wig)
    assert "亚麻金" in prompt and "recolor it to this exact" in prompt


# ---------------- start_composites 注入 ref_photos ----------------

def _make_wig(db, model_no="LS-A"):
    return service.upsert_wig(db, WigUpsert(
        model_no=model_no, name="波波", angle_photos=["uploads/expo/wigs/base.jpg"],
    ))


def _make_color(db, code="6", name="栗棕"):
    return service.upsert_hair_color(db, HairColorUpsert(code=code, name=name, hex_code="#5a3a26"))


def _make_session(db, wig_id):
    from app.expo.models import ExpoCustomer
    from datetime import datetime
    c = ExpoCustomer(name="客", phone="13800000000", expo_code="t", consent_at=datetime.utcnow())
    db.add(c); db.flush()
    s = ExpoSession(customer_id=c.id, photo_path="uploads/expo/photos/p.jpg", mode="tryon", status="analyzed")
    db.add(s); db.flush()
    return s


def test_start_composites_injects_combo_ref_photos(db, monkeypatch):
    wig = _make_wig(db)
    color = _make_color(db)
    db.add(ExpoWigColor(wig_id=wig.id, hair_color_id=color.id,
                        angle_photos=["uploads/expo/wigs/c0.jpg", "uploads/expo/wigs/c1.jpg"], is_active=1))
    db.commit()
    session = _make_session(db, wig.id)
    snapshot = service.snapshot_hair_color(db, color.id)
    # 不真正起线程：桩掉 _start_batch，抓 rows
    captured = {}
    monkeypatch.setattr(ai_pipeline, "_start_batch", lambda sid, rows: captured.setdefault("rows", rows))
    ai_pipeline.start_composites(session.id, [wig.id], hair_color=snapshot, db=db)
    rows = captured["rows"]
    assert len(rows) == 1
    assert rows[0].hair_color_json["ref_photos"] == ["uploads/expo/wigs/c0.jpg", "uploads/expo/wigs/c1.jpg"]


def test_start_composites_no_combo_leaves_snapshot_plain(db, monkeypatch):
    wig = _make_wig(db, "LS-B")
    color = _make_color(db, "613", "亚麻金")  # 无组合图
    db.commit()
    session = _make_session(db, wig.id)
    snapshot = service.snapshot_hair_color(db, color.id)
    captured = {}
    monkeypatch.setattr(ai_pipeline, "_start_batch", lambda sid, rows: captured.setdefault("rows", rows))
    ai_pipeline.start_composites(session.id, [wig.id], hair_color=snapshot, db=db)
    assert "ref_photos" not in captured["rows"][0].hair_color_json


# ---------------- service：kiosk 过滤 / 管理端矩阵 / CRUD ----------------

def test_list_wig_color_options_only_returns_imaged_active(db):
    wig = _make_wig(db, "LS-C")
    c_imaged = _make_color(db, "6", "栗棕")
    c_empty = _make_color(db, "1B", "自然黑")   # 组合无图
    c_inactive = _make_color(db, "613", "亚麻金")  # 组合有图但停用
    db.add(ExpoWigColor(wig_id=wig.id, hair_color_id=c_imaged.id, angle_photos=["uploads/expo/wigs/a.jpg"], is_active=1))
    db.add(ExpoWigColor(wig_id=wig.id, hair_color_id=c_empty.id, angle_photos=[], is_active=1))
    db.add(ExpoWigColor(wig_id=wig.id, hair_color_id=c_inactive.id, angle_photos=["uploads/expo/wigs/b.jpg"], is_active=0))
    db.commit()
    opts = service.list_wig_color_options(db, wig.id)
    ids = [o["id"] for o in opts]
    assert ids == [c_imaged.id]  # 只有「启用+有图」的入选


def test_list_wig_color_images_matrix_covers_all_active_colors(db):
    wig = _make_wig(db, "LS-D")
    c1 = _make_color(db, "6", "栗棕")
    c2 = _make_color(db, "1B", "自然黑")
    db.add(ExpoWigColor(wig_id=wig.id, hair_color_id=c1.id, angle_photos=["uploads/expo/wigs/a.jpg"], is_active=1))
    db.commit()
    matrix = service.list_wig_color_images(db, wig.id)
    by_id = {m["hair_color_id"]: m for m in matrix}
    assert by_id[c1.id]["has_images"] is True and by_id[c1.id]["angle_photos"] == ["uploads/expo/wigs/a.jpg"]
    assert by_id[c2.id]["has_images"] is False and by_id[c2.id]["angle_photos"] == []


def test_upsert_wig_color_images_replaces_and_cleans(db, tmp_path, monkeypatch):
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    wig = _make_wig(db, "LS-E")
    color = _make_color(db, "6", "栗棕")
    old = tmp_path / "uploads" / "expo" / "wigs" / "old.jpg"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"x")
    service.upsert_wig_color_images(db, wig.id, color.id,
                                    WigColorImagesUpsert(angle_photos=["uploads/expo/wigs/old.jpg"]))
    # 替换为新图组：旧文件应被清理
    service.upsert_wig_color_images(db, wig.id, color.id,
                                    WigColorImagesUpsert(angle_photos=["uploads/expo/wigs/new.jpg"]))
    row = db.query(ExpoWigColor).filter_by(wig_id=wig.id, hair_color_id=color.id).one()
    assert row.angle_photos == ["uploads/expo/wigs/new.jpg"]
    assert not old.exists()  # 被替换掉的旧文件删除


def test_delete_wig_color_images(db):
    wig = _make_wig(db, "LS-F")
    color = _make_color(db, "6", "栗棕")
    db.add(ExpoWigColor(wig_id=wig.id, hair_color_id=color.id, angle_photos=["uploads/expo/wigs/a.jpg"]))
    db.commit()
    assert service.delete_wig_color_images(db, wig.id, color.id) is True
    assert service.delete_wig_color_images(db, wig.id, color.id) is False  # 幂等：再删不存在


def test_delete_hair_color_cleans_combo_files_and_rows(db, tmp_path, monkeypatch):
    """删发色：CASCADE 删组合行 + 手动清各发型对该色的组合图文件（不留孤儿）。"""
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    wig_a = _make_wig(db, "LS-G")
    wig_b = _make_wig(db, "LS-H")
    color = _make_color(db, "6", "栗棕")
    files = []
    for name in ("ga.jpg", "gb.jpg"):
        p = tmp_path / "uploads" / "expo" / "wigs" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        files.append(p)
    db.add(ExpoWigColor(wig_id=wig_a.id, hair_color_id=color.id, angle_photos=["uploads/expo/wigs/ga.jpg"]))
    db.add(ExpoWigColor(wig_id=wig_b.id, hair_color_id=color.id, angle_photos=["uploads/expo/wigs/gb.jpg"]))
    db.commit()
    assert service.count_wig_color_combos_by_color(db, color.id) == 2
    assert service.delete_hair_color(db, color.id) is True
    # 发色行删除 + 组合图文件手动清（组合行由 MySQL FK CASCADE 带走，SQLite 测试环境不校验 FK）
    from app.expo.models import ExpoHairColor as _HC
    assert db.get(_HC, color.id) is None
    assert all(not f.exists() for f in files)


def test_put_color_images_persists_and_reads_back(db):
    """路由级复现：PUT 保存组合图 → GET 矩阵能读回（用户报告『保存成功但没存下来』）。"""
    wig = _make_wig(db, "LS-PUT")
    color = _make_color(db, "6", "栗棕")
    with _client(db, ["expo:admin"]) as c:
        r = c.put(f"/api/expo/wigs/{wig.id}/color-images/{color.id}",
                  json={"angle_photos": ["uploads/expo/wigs/a.jpg", "uploads/expo/wigs/b.jpg"]})
        assert r.status_code == 200, r.text
        g = c.get(f"/api/expo/wigs/{wig.id}/color-images")
        assert g.status_code == 200
        by_id = {m["hair_color_id"]: m for m in g.json()["data"]}
        assert by_id[color.id]["has_images"] is True
        assert by_id[color.id]["angle_photos"] == ["uploads/expo/wigs/a.jpg", "uploads/expo/wigs/b.jpg"]
    # 直查 DB 确认真落库
    assert db.query(ExpoWigColor).filter_by(wig_id=wig.id, hair_color_id=color.id).count() == 1


def test_delete_wig_cleans_combo_files(db, tmp_path, monkeypatch):
    """删发型：清该发型各发色的组合图文件（无试戴记录才可删）。"""
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    wig = _make_wig(db, "LS-I")
    color = _make_color(db, "6", "栗棕")
    p = tmp_path / "uploads" / "expo" / "wigs" / "wi.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    db.add(ExpoWigColor(wig_id=wig.id, hair_color_id=color.id, angle_photos=["uploads/expo/wigs/wi.jpg"]))
    db.commit()
    assert service.delete_wig(db, wig.id) is True
    assert not p.exists()
