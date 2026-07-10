"""展会试戴「发色选择 + 场景大片双入口」纯逻辑测试（047 迁移配套）。

覆盖：场景解析、发色 prompt 子句、双模板组图、批次切片边界、GenerateRequest 校验。
不触数据库的部分全部直测；prompt 组装用未落库的 ORM 实例。
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.expo import ai_pipeline, service
from app.expo.models import ExpoHairColor, ExpoResult, ExpoSession, ExpoWig
from app.expo.schemas import GenerateRequest, HairColorUpsert, WigUpsert
from app.expo.service import (
    delete_hair_color,
    delete_wig,
    get_session,
    pick_batch_wig_ids,
    snapshot_hair_color,
    upsert_hair_color,
    upsert_wig,
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
    prompt, images, size = ai_pipeline._build_prompt(session, row, None)
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
    prompt, images, size = ai_pipeline._build_prompt(session, row, wig)
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
    prompt, images, size = ai_pipeline._build_prompt(session, row, wig)
    assert "LAST reference image" in prompt
    assert images[-1] == swatch
    assert len(images) == 2  # 自拍 + 色板图（发型参考图文件不存在）


def test_build_prompt_tryon_without_color_has_no_clause():
    session = _session()
    wig = ExpoWig(model_no="LS-2", name="知性短发", wig_description="pixie cut")
    row = ExpoResult(session_id=1, wig_id=2, hair_color_json=None)
    prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)
    assert "recolor" not in prompt.lower()


def test_build_prompt_tryon_default_keeps_background():
    """单场景模板默认原景：锚定图片角色分工 + 保持原背景，无三格残留。"""
    session = _session()
    wig = ExpoWig(model_no="LS-3", name="轻盈波波", wig_description="airy bob")
    row = ExpoResult(session_id=1, wig_id=3, hair_color_json=None)
    prompt, images, size = ai_pipeline._build_prompt(session, row, wig)
    assert "FIRST image is the customer's own photo" in prompt  # 锚：参考图角色分工
    assert "background and framing exactly the same" in prompt   # 场：默认原景全锁定
    assert "85mm" not in prompt  # 浅景深只随场景置换路径（原景不能又锁背景又虚化）
    assert "16:9" not in prompt and "three" not in prompt        # 三格已回退干净
    assert len(images) == 1


def test_build_prompt_tryon_with_scene_swaps_background():
    """选了生成场景 → 场景置换子句替代原景子句（tryon 分支按 wig_id 判定）。"""
    session = _session()
    wig = ExpoWig(model_no="LS-3", name="轻盈波波", wig_description="airy bob")
    row = ExpoResult(
        session_id=1, wig_id=3,
        scene_json={"key": "whitecollar", "label": "白领高管"},
    )
    prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)
    assert "boardroom" in prompt  # whitecollar 场景 prompt 注入
    assert "background and framing exactly the same" not in prompt
    assert "85mm" in prompt  # 场景置换路径带摄像语言
    assert "magazine-quality" not in prompt  # 不能误入 scene 模式模板
    # 叙事化：放开姿势/表情但锁身份，第二人物只作虚化背景（用户定稿 2026-07-09）
    assert "adapt the background, outfit, pose, gesture and facial expression" in prompt
    assert "never with detailed faces or hands" in prompt


def test_resolve_tryon_scene():
    assert ai_pipeline.resolve_tryon_scene("home")["label"] == "居家"
    assert ai_pipeline.resolve_tryon_scene("doctor")["label"] == "医生"
    assert ai_pipeline.resolve_tryon_scene("office") is None  # 办公已移除
    assert ai_pipeline.resolve_tryon_scene("multi") is None   # 多场景合一已移除
    assert ai_pipeline.resolve_tryon_scene("bogus") is None
    assert ai_pipeline.resolve_tryon_scene(None) is None


# ---------------- 输出尺寸（6 寸竖版/横版） ----------------

def test_build_prompt_tryon_single_scene_is_portrait():
    """单场景（原景与置换均是）输出竖版 6 寸，prompt 带规格二重锚定。"""
    session = _session()
    wig = ExpoWig(model_no="LS-3", name="轻盈波波", wig_description="airy bob")
    row = ExpoResult(session_id=1, wig_id=3, hair_color_json=None)
    prompt, _, size = ai_pipeline._build_prompt(session, row, wig)
    assert size == "1024x1536"
    assert "102x152mm" in prompt

    row_scene = ExpoResult(session_id=1, wig_id=3, scene_json={"key": "whitecollar", "label": "白领高管"})
    _, _, size2 = ai_pipeline._build_prompt(session, row_scene, wig)
    assert size2 == "1024x1536"


def test_build_prompt_scene_mode_size_follows_preset():
    session = _session(mode="scene")
    row = ExpoResult(session_id=1, wig_id=None, scene_json={"key": "cafe", "label": "午后咖啡"})
    _, _, size = ai_pipeline._build_prompt(session, row, None)
    assert size is None  # scene 模式不限定，沿用 preset 配置


# ---------------- 场景示意图探测（滑动选择器用，仅示意不参与合成） ----------------

def test_scene_image_url_missing_returns_none():
    assert ai_pipeline.scene_image_url("whitecollar") is None  # 未放图 → 前端退化占位卡


def test_scene_image_url_found_returns_public_path(tmp_path, monkeypatch):
    """约定目录放了 <key>.jpg → 返回 /uploads 开头的公开 URL。"""
    scene_dir = tmp_path / "scenes"
    scene_dir.mkdir()
    (scene_dir / "doctor.jpg").write_bytes(b"fake")
    monkeypatch.setattr(ai_pipeline, "SCENE_IMAGE_DIR", scene_dir)
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    assert ai_pipeline.scene_image_url("doctor") == "/scenes/doctor.jpg"
    assert ai_pipeline.scene_image_url("teacher") is None


class _FakeUpload:
    def __init__(self, filename, data=b"fake"):
        import io
        self.filename = filename
        self.file = io.BytesIO(data)


def test_save_scene_image_writes_replaces_and_deletes(tmp_path, monkeypatch):
    """存图为 <key>.<ext>；换扩展名时清旧图避免探测歧义；delete 清各扩展名。"""
    scene_dir = tmp_path / "scenes"
    monkeypatch.setattr(ai_pipeline, "SCENE_IMAGE_DIR", scene_dir)
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)

    url = ai_pipeline.save_scene_image("doctor", _FakeUpload("x.PNG"))  # 扩展名大小写归一
    assert url == "/scenes/doctor.png"
    assert (scene_dir / "doctor.png").exists()

    url2 = ai_pipeline.save_scene_image("doctor", _FakeUpload("y.jpg"))
    assert url2 == "/scenes/doctor.jpg"
    assert (scene_dir / "doctor.jpg").exists()
    assert not (scene_dir / "doctor.png").exists()  # 旧扩展名已清

    assert ai_pipeline.delete_scene_image("doctor") is True
    assert not (scene_dir / "doctor.jpg").exists()
    assert ai_pipeline.delete_scene_image("doctor") is False  # 已无文件


def test_save_scene_image_rejects_bad_key_and_ext(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_pipeline, "SCENE_IMAGE_DIR", tmp_path / "scenes")
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="场景不存在"):
        ai_pipeline.save_scene_image("bogus", _FakeUpload("x.png"))
    with pytest.raises(ValueError, match="仅支持"):
        ai_pipeline.save_scene_image("doctor", _FakeUpload("x.gif"))


def test_scene_mode_home_key_not_confused_with_tryon_home():
    """SCENES 与 TRYON_SCENES 都有 key=home：wig_id 为空必须命中 scene 模式模板（撞名守卫）。"""
    session = _session(mode="scene")
    row = ExpoResult(session_id=1, wig_id=None, scene_json={"key": "home", "label": "温馨居家"})
    prompt, images, size = ai_pipeline._build_prompt(session, row, None)
    assert "soft lamp light" in prompt      # scene 模式 home 的独有描述
    assert "front-left" not in prompt       # tryon home 的独有描述不得混入
    assert len(images) == 1


def test_build_prompt_color_and_scene_combined(tmp_path):
    """发色（色板图）× 生成场景 组合：LAST 指代仍成立且色板图仍在末位。"""
    swatch = tmp_path / "sw.png"
    swatch.write_bytes(b"fake")
    session = _session()
    wig = ExpoWig(model_no="LS-1", name="轻盈波波", wig_description="short bob")
    row = ExpoResult(
        session_id=1, wig_id=1,
        hair_color_json={"name": "栗棕", "code": "6", "swatch_path": str(swatch)},
        scene_json={"key": "gathering", "label": "聚会"},
    )
    prompt, images, size = ai_pipeline._build_prompt(session, row, wig)
    assert "LAST reference image" in prompt
    assert "dinner party" in prompt
    assert images[-1] == swatch


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


# ---------------- _prep_image：送模型前统一压缩 ----------------

def test_prep_image_downscales_large_image(tmp_path):
    """发型库 2~16MB 原图直传拖垮上游（session=13 实case）：最长边压到 1280 + JPEG 重编码。"""
    import cv2
    import numpy as np

    big = tmp_path / "wig_big.png"
    cv2.imwrite(str(big), np.full((3000, 2000, 3), 128, np.uint8))
    original_size = big.stat().st_size

    out = ai_pipeline._prep_image(big)
    assert out["content_type"] == "image/jpeg"
    assert out["filename"].endswith(".jpg")
    assert len(out["content"]) < original_size
    decoded = cv2.imdecode(np.frombuffer(out["content"], np.uint8), cv2.IMREAD_COLOR)
    assert max(decoded.shape[:2]) == ai_pipeline._MAX_SEND_EDGE


def test_prep_image_fallback_on_unreadable(tmp_path):
    bad = tmp_path / "not_image.png"
    bad.write_bytes(b"definitely not an image")
    out = ai_pipeline._prep_image(bad)
    assert out["content"] == b"definitely not an image"  # 回退原始字节，不阻断合成
    assert out["filename"] == "not_image.png"


def test_image_message_compresses_before_send(tmp_path):
    """面容分析送图前压缩（2026-07-08 超时修复）：大图进 message 时已降采样，
    data URL 里的图远小于 3000x2000 原图。"""
    import base64

    import cv2
    import numpy as np

    big = tmp_path / "face.png"
    cv2.imwrite(str(big), np.full((3000, 2000, 3), 128, np.uint8))

    msgs = ai_pipeline._image_message("分析这张脸", [big])
    blocks = msgs[0]["content"]
    assert blocks[0]["type"] == "text"
    url = blocks[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")  # 压缩后统一 JPEG
    sent_bytes = base64.b64decode(url.split(",", 1)[1])
    decoded = cv2.imdecode(np.frombuffer(sent_bytes, np.uint8), cv2.IMREAD_COLOR)
    assert max(decoded.shape[:2]) == ai_pipeline._MAX_SEND_EDGE  # 最长边压到 1280


# ---------------- _chat_json：非法 JSON 带纠错反馈重试 ----------------

def test_chat_json_retries_malformed_then_succeeds(monkeypatch):
    """线上 session=9/10 实case：模型字符串值内夹未转义双引号 → 重试一次拿到合法 JSON。"""
    calls = []

    def fake_chat(db=None, preset_name=None, messages=None, caller_module=None):
        calls.append(list(messages))
        if len(calls) == 1:
            return {"content": '{"display_notes": "气质"知性"优雅"}'}  # 非法：内嵌未转义双引号
        return {"content": '{"gender": "female"}'}

    import app.ai.service as ai_service
    monkeypatch.setattr(ai_service, "chat", fake_chat)
    out = ai_pipeline._chat_json(None, "expo_face_analysis", [{"role": "user", "content": "hi"}])
    assert out == {"gender": "female"}
    assert len(calls) == 2
    # 第二次请求必须携带纠错反馈
    assert any("不是合法 JSON" in str(m.get("content")) for m in calls[1])


def test_chat_json_raises_after_all_retries(monkeypatch):
    import app.ai.service as ai_service
    monkeypatch.setattr(ai_service, "chat", lambda **kw: {"content": "抱歉，我无法输出"})
    with pytest.raises(ValueError, match="重试后仍失败"):
        ai_pipeline._chat_json(None, "expo_face_analysis", [{"role": "user", "content": "hi"}])


# ---------------- 卡死状态看门狗（轮询读取时自愈） ----------------

def _stale_session(db, status, secs, results=()):
    s = ExpoSession(
        customer_id=1, photo_path="p.jpg", status=status,
        updated_at=datetime.utcnow() - timedelta(seconds=secs),
    )
    db.add(s)
    db.flush()
    for r_status in results:
        db.add(ExpoResult(session_id=s.id, status=r_status))
    db.commit()
    return s.id


def test_watchdog_heals_stale_generating_keeps_done(db):
    from app.expo.service import STALE_GENERATING_SECS
    sid = _stale_session(db, "generating", STALE_GENERATING_SECS + 60, results=("generating", "done"))
    got = get_session(db, sid)
    assert got.status == "done"  # 有成品照常展示
    assert sorted(r.status for r in got.results) == ["done", "failed"]


def test_watchdog_all_stale_marks_failed(db):
    from app.expo.service import STALE_GENERATING_SECS
    sid = _stale_session(db, "generating", STALE_GENERATING_SECS + 60, results=("generating",))
    got = get_session(db, sid)
    assert got.status == "failed"
    assert "watchdog" in (got.error_message or "")


def test_watchdog_skips_fresh_generating(db):
    sid = _stale_session(db, "generating", 30, results=("generating",))
    got = get_session(db, sid)
    assert got.status == "generating"  # 未超阈值不动


def test_watchdog_heals_stale_pending(db):
    sid = _stale_session(db, "pending", 400)
    got = get_session(db, sid)
    assert got.status == "failed"


# ---------------- 色板取色（跳过白底背景）+ 发型 angle_urls ----------------

def test_pick_swatch_hair_hex_skips_white_background():
    """色板白底：最大簇是白背景，必须跳过取真实发色（2026-07-08 实case）。"""
    dominant = [
        {"hex": "#FCFCFC", "rgb": [252, 252, 252], "percentage": 70.0},  # 白底
        {"hex": "#3D070C", "rgb": [61, 7, 12], "percentage": 25.0},       # 暗红发色
        {"hex": "#8A8A8A", "rgb": [138, 138, 138], "percentage": 5.0},
    ]
    assert service.pick_swatch_hair_hex(dominant) == "#3D070C"


def test_pick_swatch_hair_hex_keeps_black_hair():
    """自然黑是有效发色，近黑不能被当背景滤掉。"""
    dominant = [
        {"hex": "#FDFDFD", "rgb": [253, 253, 253], "percentage": 60.0},
        {"hex": "#100D0B", "rgb": [16, 13, 11], "percentage": 40.0},
    ]
    assert service.pick_swatch_hair_hex(dominant) == "#100D0B"


def test_pick_swatch_hair_hex_all_white_falls_back():
    """全是近白（空白色板）→ 回退最大簇，不返回 None 卡流程。"""
    dominant = [
        {"hex": "#FFFFFF", "rgb": [255, 255, 255], "percentage": 90.0},
        {"hex": "#FAFAFA", "rgb": [250, 250, 250], "percentage": 10.0},
    ]
    assert service.pick_swatch_hair_hex(dominant) == "#FFFFFF"


def test_pick_swatch_hair_hex_empty_returns_none():
    assert service.pick_swatch_hair_hex([]) is None


def test_serialize_wig_exposes_angle_urls_with_leading_slash():
    """编辑页预览要可访问 URL：angle_photos 是裸相对路径，angle_urls 加前导 /。"""
    wig = ExpoWig(
        model_no="LS-A", name="多角度款", series="classic",
        cover_path="uploads/expo/wigs/cover.png",
        angle_photos=["uploads/expo/wigs/a1.png", "uploads/expo/wigs/a2.png"],
    )
    s = service.serialize_wig(wig)
    assert s["angle_photos"] == ["uploads/expo/wigs/a1.png", "uploads/expo/wigs/a2.png"]
    assert s["angle_urls"] == ["/uploads/expo/wigs/a1.png", "/uploads/expo/wigs/a2.png"]
    assert s["cover_url"] == "/uploads/expo/wigs/cover.png"  # 与 cover 同口径


def test_serialize_wig_empty_angles_gives_empty_urls():
    wig = ExpoWig(model_no="LS-B", name="无图款", series="classic")
    s = service.serialize_wig(wig)
    assert s["angle_photos"] == []
    assert s["angle_urls"] == []


# ---------------- 发型/发色删除（管货：FK 拦截 + 快照无损） ----------------

def _wig_body(**over):
    base = dict(model_no="LS-DEL", name="待删发型", series="classic")
    base.update(over)
    return WigUpsert(**base)


def test_delete_wig_unused_removes_row(db):
    wig = upsert_wig(db, _wig_body())
    assert delete_wig(db, wig.id) is True
    assert db.get(ExpoWig, wig.id) is None


def test_delete_wig_missing_returns_false(db):
    assert delete_wig(db, 999999) is False


def test_delete_wig_referenced_by_result_blocked(db):
    """已产生试戴记录的发型拒删——保护线索台复盘数据，引导改用停用。"""
    wig = upsert_wig(db, _wig_body())
    s = ExpoSession(customer_id=1, photo_path="p.jpg", status="done")
    db.add(s)
    db.flush()
    db.add(ExpoResult(session_id=s.id, wig_id=wig.id, status="done"))
    db.commit()
    with pytest.raises(ValueError, match="无法删除"):
        delete_wig(db, wig.id)
    assert db.get(ExpoWig, wig.id) is not None  # 拦截后未删


def test_delete_hair_color_removes_row(db):
    row = upsert_hair_color(db, _color_body())
    assert delete_hair_color(db, row.id) is True
    assert db.get(ExpoHairColor, row.id) is None


def test_delete_hair_color_missing_returns_false(db):
    assert delete_hair_color(db, 999999) is False


def test_delete_hair_color_keeps_historical_snapshot(db):
    """发色在效果图里是 JSON 快照，删发色后历史效果图的发色信息不受影响。"""
    row = upsert_hair_color(db, _color_body())
    snap = snapshot_hair_color(db, row.id)
    s = ExpoSession(customer_id=1, photo_path="p.jpg", status="done")
    db.add(s)
    db.flush()
    result = ExpoResult(session_id=s.id, status="done", hair_color_json=snap)
    db.add(result)
    db.commit()
    result_id = result.id

    assert delete_hair_color(db, row.id) is True
    db.expire_all()
    assert db.get(ExpoResult, result_id).hair_color_json["code"] == "1B"  # 快照仍在


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
