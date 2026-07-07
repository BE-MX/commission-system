"""展会试戴「发色选择 + 场景大片双入口」纯逻辑测试（047 迁移配套）。

覆盖：场景解析、发色 prompt 子句、双模板组图、批次切片边界、GenerateRequest 校验。
不触数据库的部分全部直测；prompt 组装用未落库的 ORM 实例。
"""

import pytest
from pydantic import ValidationError

from app.expo import ai_pipeline
from app.expo.models import ExpoResult, ExpoSession, ExpoWig
from app.expo.schemas import GenerateRequest, HairColorUpsert
from app.expo.service import (
    pick_batch_wig_ids,
    snapshot_hair_color,
    upsert_hair_color,
)


# ---------------- resolve_scenes ----------------

def test_resolve_scenes_default_top3():
    scenes = ai_pipeline.resolve_scenes(None)
    assert [s["key"] for s in scenes] == [s["key"] for s in ai_pipeline.SCENES[:3]]


def test_resolve_scenes_dedupe_and_drop_invalid():
    scenes = ai_pipeline.resolve_scenes(["cafe", "cafe", "bogus", "home"])
    assert [s["key"] for s in scenes] == ["cafe", "home"]


def test_resolve_scenes_all_invalid_returns_empty():
    assert ai_pipeline.resolve_scenes(["nope", "nada"]) == []


# ---------------- 发色 prompt 子句（048 发色库快照形态） ----------------

def test_color_clause_text_mode_carries_description():
    clause = ai_pipeline._color_clause({
        "name": "自然黑", "code": "1B", "hex": "#1a1110",
        "description": "深邃自然黑，光下泛冷调蓝黑光泽",
    })
    assert "自然黑" in clause
    assert "1B" in clause and "hex #1a1110" in clause
    assert "深邃自然黑" in clause
    assert "LAST reference image" not in clause  # 无色板图走纯文本模板


def test_color_clause_swatch_mode_references_last_image():
    clause = ai_pipeline._color_clause(
        {"name": "栗棕", "code": "6", "hex": "#5a3a26", "description": "暖调栗棕"},
        with_swatch=True,
    )
    assert "LAST reference image" in clause
    assert "栗棕" in clause and "暖调栗棕" in clause


def test_color_clause_none_is_empty():
    assert ai_pipeline._color_clause(None) == ""


def test_color_clause_missing_hex_and_description_omitted():
    clause = ai_pipeline._color_clause({"name": "深棕", "code": "2"})
    assert "hex" not in clause
    assert "Color description" not in clause
    assert "深棕" in clause


def test_color_swatch_path_missing_file_returns_none():
    assert ai_pipeline._color_swatch_path({"swatch_path": "uploads/expo/hair_colors/nope.png"}) is None
    assert ai_pipeline._color_swatch_path(None) is None
    assert ai_pipeline._color_swatch_path({"name": "x"}) is None


# ---------------- _build_prompt 双模板 ----------------

def _session(photo="uploads/expo/photos/x.jpg", mode="tryon"):
    return ExpoSession(customer_id=1, photo_path=photo, mode=mode)


def test_build_prompt_scene_uses_scene_template_and_single_image():
    session = _session(mode="scene")
    row = ExpoResult(session_id=1, wig_id=None, scene_json={"key": "cafe", "label": "午后咖啡"})
    prompt, images = ai_pipeline._build_prompt(session, row, None)
    assert "coffee shop" in prompt
    assert "magazine-quality" in prompt
    assert len(images) == 1  # 只有客户实拍，不带发型参考图


def test_build_prompt_tryon_appends_color_clause():
    session = _session()
    wig = ExpoWig(model_no="LS-1", name="轻盈波波", wig_description="short bob")
    row = ExpoResult(
        session_id=1, wig_id=1,
        hair_color_json={"name": "栗棕", "code": "6", "hex": "#5a3a26", "description": "暖调栗棕"},
    )
    prompt, images = ai_pipeline._build_prompt(session, row, wig)
    assert "short bob" in prompt
    assert "栗棕" in prompt and "#5a3a26" in prompt
    assert "LAST reference image" not in prompt  # 色板图不存在 → 纯文本子句
    assert len(images) == 1  # 参考图文件不存在时只剩客户照片


def test_build_prompt_tryon_swatch_image_appended_last(tmp_path):
    """三图合成：自拍 + 发型参考图 + 色板图，色板图必须在末位且 prompt 用 LAST 指代。"""
    swatch = tmp_path / "swatch_6.png"
    swatch.write_bytes(b"fake-png")
    session = _session()
    wig = ExpoWig(model_no="LS-1", name="轻盈波波", wig_description="short bob")
    row = ExpoResult(
        session_id=1, wig_id=1,
        hair_color_json={
            "name": "栗棕", "code": "6", "hex": "#5a3a26",
            "description": "暖调栗棕", "swatch_path": str(swatch),
        },
    )
    prompt, images = ai_pipeline._build_prompt(session, row, wig)
    assert "LAST reference image" in prompt
    assert images[-1] == swatch
    assert len(images) == 2  # 自拍 + 色板图（发型参考图文件不存在）


def test_build_prompt_tryon_without_color_has_no_clause():
    session = _session()
    wig = ExpoWig(model_no="LS-2", name="知性短发", wig_description="pixie cut")
    row = ExpoResult(session_id=1, wig_id=2, hair_color_json=None)
    prompt, _ = ai_pipeline._build_prompt(session, row, wig)
    assert "recolor" not in prompt.lower()


def test_build_prompt_tryon_triptych_structure():
    """三格模板核心约束：图片角色分工 + 三场景 + 16:9 拼接 + 三格一致性声明。"""
    session = _session()
    wig = ExpoWig(model_no="LS-3", name="轻盈波波", wig_description="airy bob")
    row = ExpoResult(session_id=1, wig_id=3, hair_color_json=None)
    prompt, _ = ai_pipeline._build_prompt(session, row, wig)
    assert "FIRST image is the customer's own photo" in prompt  # 锚：参考图角色分工
    assert "HOME" in prompt and "OFFICE" in prompt and "GATHERING" in prompt  # 场：三格
    assert "16:9" in prompt and "one third" in prompt  # 输出规格
    assert "identical in all three panels" in prompt  # 魂：三格身份一致性


# ---------------- 批次切片边界（换一批上界） ----------------

def test_pick_batch_beyond_ranking_returns_empty():
    session = _session()
    session.matched_wig_ids = [{"wig_id": i, "score": 90 - i} for i in range(1, 7)]  # 共 6 款
    assert pick_batch_wig_ids(session, 0) == [1, 2, 3]
    assert pick_batch_wig_ids(session, 1) == [4, 5, 6]
    assert pick_batch_wig_ids(session, 2) == []


# ---------------- 发色库 upsert / 快照（048） ----------------

def _color_body(**over):
    base = dict(
        code="1B", name="自然黑", hex_code="#1a1110",
        swatch_path="uploads/expo/hair_colors/sw.png",
        color_description="深邃自然黑", priority=10, is_active=1,
    )
    base.update(over)
    return HairColorUpsert(**base)


def test_upsert_hair_color_create_and_snapshot(db):
    row = upsert_hair_color(db, _color_body())
    snap = snapshot_hair_color(db, row.id)
    assert snap == {
        "hair_color_id": row.id, "code": "1B", "name": "自然黑",
        "hex": "#1a1110", "swatch_path": "uploads/expo/hair_colors/sw.png",
        "description": "深邃自然黑",
    }


def test_upsert_hair_color_duplicate_code_rejected(db):
    upsert_hair_color(db, _color_body())
    with pytest.raises(ValueError, match="已存在"):
        upsert_hair_color(db, _color_body(name="另一个"))


def test_upsert_hair_color_empty_strings_stored_as_null(db):
    row = upsert_hair_color(db, _color_body(hex_code="", swatch_path="  ", color_description=""))
    assert row.hex_code is None
    assert row.swatch_path is None
    assert row.color_description is None


def test_upsert_hair_color_update_missing_raises(db):
    with pytest.raises(ValueError, match="不存在"):
        upsert_hair_color(db, _color_body(), color_id=999)


def test_snapshot_inactive_color_rejected(db):
    row = upsert_hair_color(db, _color_body(is_active=0))
    with pytest.raises(ValueError, match="不存在或已停用"):
        snapshot_hair_color(db, row.id)
    with pytest.raises(ValueError, match="不存在或已停用"):
        snapshot_hair_color(db, 12345)


# ---------------- GenerateRequest 校验 ----------------

def test_generate_request_batch_upper_bound():
    with pytest.raises(ValidationError):
        GenerateRequest(batch=4)


def test_generate_request_scene_keys_max_length():
    with pytest.raises(ValidationError):
        GenerateRequest(scene_keys=["a"] * 7)


def test_generate_request_defaults():
    req = GenerateRequest()
    assert req.batch == 0
    assert req.hair_color_id is None
    assert req.scene_keys is None
