"""展会试戴「发色选择 + 场景大片双入口」纯逻辑测试（047 迁移配套）。

覆盖：场景解析、发色 prompt 子句、双模板组图、批次切片边界、GenerateRequest 校验。
不触数据库的部分全部直测；prompt 组装用未落库的 ORM 实例。
"""

import re
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.expo import ai_pipeline, service
from app.core.time import beijing_now
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


def test_color_clause_ignores_swatch_path_stays_text_mode():
    """快照带 swatch_path 也只走文本模板：色板图不再进合成（2026-07-14 亮哥指令，
    色板参考图会把合成结果拽偏）。"""
    clause = ai_pipeline._color_clause(
        {"name": "栗棕", "code": "6", "hex": "#5a3a26", "description": "暖调栗棕",
         "swatch_path": "uploads/expo/hair_colors/swatch_x.png"},
    )
    assert "LAST reference image" not in clause
    assert "栗棕" in clause and "暖调栗棕" in clause and "hex #5a3a26" in clause


def test_color_clause_none_is_empty():
    assert ai_pipeline._color_clause(None) == ""


def test_color_clause_missing_hex_and_description_omitted():
    clause = ai_pipeline._color_clause({"name": "深棕", "code": "2"})
    assert "hex" not in clause
    assert "Color description" not in clause
    assert "深棕" in clause


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


def test_build_prompt_tryon_swatch_image_never_sent(tmp_path):
    """色板图存在也不随图送模型（会把合成拽偏），发色只走文本锚点（名称/色号/hex）。"""
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
    assert "LAST reference image" not in prompt
    assert swatch not in images
    assert len(images) == 1  # 只剩自拍（发型参考图文件不存在）
    assert "栗棕" in prompt and "hex #5a3a26" in prompt


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
    # 三格已回退干净。判据从裸词 "three" 收敛为**布局语义**（2026-08-01）：裸词把
    # "three-dimensional" 这类无关英文也算成三格残留，挡的是正常措辞而不是回归。
    assert "16:9" not in prompt
    assert not re.search(r"three[\s-]+(panels?|images?|variations?|views?)|triptych",
                         prompt, re.I)
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

def test_scene_image_url_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_pipeline, "SCENE_IMAGE_DIR", tmp_path / "empty-scenes")
    assert ai_pipeline.scene_image_url("whitecollar") is None  # 未放图 → 前端退化占位卡


def test_scene_image_url_found_returns_public_path(tmp_path, monkeypatch):
    """约定目录放了 <key>.jpg → 返回 /uploads 开头的公开 URL，带 ?v=mtime 版本号。"""
    scene_dir = tmp_path / "scenes"
    scene_dir.mkdir()
    (scene_dir / "doctor.jpg").write_bytes(b"fake")
    monkeypatch.setattr(ai_pipeline, "SCENE_IMAGE_DIR", scene_dir)
    monkeypatch.setattr(ai_pipeline, "REPO_ROOT", tmp_path)
    url = ai_pipeline.scene_image_url("doctor")
    assert re.fullmatch(r"/scenes/doctor\.jpg\?v=\d+", url)  # 固定名素材靠版本号破缓存
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
    assert url.startswith("/scenes/doctor.png?v=")
    assert (scene_dir / "doctor.png").exists()

    url2 = ai_pipeline.save_scene_image("doctor", _FakeUpload("y.jpg"))
    assert url2.startswith("/scenes/doctor.jpg?v=")
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
    """发色 × 生成场景 组合：色板图不进 images，文本色锚点与场景描述同时在场。"""
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
    assert "LAST reference image" not in prompt
    assert "栗棕" in prompt
    assert "dinner party" in prompt
    assert swatch not in images
    assert len(images) == 1


# ---------------- 穿搭变奏子句（2026-07-21 参考图 look 池版） ----------------

def test_wardrobe_variation_non_uniform_has_look_and_bans():
    clause = ai_pipeline._wardrobe_variation_clause(uniform=False)
    assert "For this shot, dress her in" in clause          # look 注入在场
    assert any(look in clause for look in ai_pipeline._OUTFIT_LOOKS)  # 来自参考图 look 池
    assert "not a plain all-black look" in clause           # 禁纯黑
    assert "heart-shaped pendant" in clause                 # 禁心形坠长项链
    assert "Accessorize with" in clause


def test_wardrobe_variation_uniform_only_jewelry():
    """着装锁定场景（制服/职业装/旗袍/舞蹈装）不得改场景规定着装，只注入首饰变奏。"""
    clause = ai_pipeline._wardrobe_variation_clause(uniform=True)
    assert "For this shot, dress her in" not in clause
    assert "all-black" not in clause
    assert "Accessorize with" in clause
    assert "heart-shaped pendant" in clause


def test_build_prompt_scene_swap_injects_variation_uniform_aware():
    session = _session()
    wig = ExpoWig(model_no="LS-1", name="轻盈波波", wig_description="short bob")
    # 非制服景（白领高管）：完整变奏
    row = ExpoResult(session_id=1, wig_id=1,
                     scene_json={"key": "whitecollar", "label": "白领高管"})
    prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)
    assert "For this shot, dress her in" in prompt
    assert "heart-shaped pendant" in prompt
    # 制服景（医生白大褂）：不动着装，只有首饰
    row_uni = ExpoResult(session_id=1, wig_id=1,
                         scene_json={"key": "doctor", "label": "医生"})
    prompt_uni, _, _ = ai_pipeline._build_prompt(session, row_uni, wig)
    assert "For this shot, dress her in" not in prompt_uni
    assert "Accessorize with" in prompt_uni


def test_build_prompt_scene_prescribed_attire_locked():
    """场景规定装（喜婆婆旗袍/广场舞舞蹈装/晚宴旗袍）不注入 look，只注首饰。"""
    session = _session()
    wig = ExpoWig(model_no="LS-1", name="轻盈波波", wig_description="short bob")
    for key, garment in (("weddinghost", "qipao"), ("squaredance", "activewear")):
        row = ExpoResult(session_id=1, wig_id=1, scene_json={"key": key, "label": key})
        prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)
        assert "For this shot, dress her in" not in prompt
        assert "Accessorize with" in prompt
        assert garment in prompt  # 场景规定装保留
    row = ExpoResult(session_id=1, wig_id=None,
                     scene_json={"key": "banquet", "label": "晚宴礼遇"})
    prompt, _, _ = ai_pipeline._build_prompt(_session(mode="scene"), row, None)
    assert "For this shot, dress her in" not in prompt
    assert "silk qipao" in prompt  # 场景规定装保留


def test_unlocked_scene_prompts_have_no_hardcoded_garments():
    """非锁定景不得写死具体单品词（2026-07-21 起单品由 look 池接管）——防回填回归。"""
    garment = re.compile(
        r"dress|blouse|qipao|polo|slacks|activewear|sheath|suit\b|coat|uniform",
        re.IGNORECASE,
    )
    for s in ai_pipeline.TRYON_SCENES + ai_pipeline.SCENES:
        if s.get("uniform"):
            continue
        m = garment.search(s["prompt"])
        assert not m, f"{s['key']} 泄漏单品词 {m.group() if m else ''}: {s['prompt']}"


def _tryon_scene_prompt(scene_key: str, variant: str = "real") -> str:
    scene = ai_pipeline.resolve_tryon_scene(scene_key)
    session = _session()
    wig = ExpoWig(model_no="LS-FACE", name="身份测试发", wig_description="short bob")
    row = ExpoResult(
        session_id=1,
        wig_id=1,
        scene_json={"key": scene_key, "label": scene["label"]},
    )
    return ai_pipeline._build_prompt(session, row, wig, variant=variant)[0]


class TestLimitedFaceAdaptation:
    def test_customer_photo_is_the_only_face_source(self):
        prompt = _tryon_scene_prompt("doctor")
        assert "sole visual source of truth for her face" in prompt
        assert "stable natural asymmetry, age traits and identifying skin marks" in prompt
        assert "wig references provide hair information only" in prompt

    def test_scene_is_composed_around_the_existing_gaze_first(self):
        prompt = _tryon_scene_prompt("hsrtravel")
        assert "compose the props and interaction around her existing gaze" in prompt
        assert "minimal coordinated adjustment" in prompt
        assert "same head-pose family" in prompt
        assert "same expression category and mouth-open state" in prompt

    def test_scene_no_longer_requires_free_face_reinterpretation(self):
        prompt = _tryon_scene_prompt("doctor")
        assert "Naturally adapt the background, outfit, pose, gesture and facial expression" not in prompt
        assert "locks identity, not expression" not in prompt
        assert "from frontal to profile or profile to frontal" in prompt

    @pytest.mark.parametrize("scene_key", ["doctor", "hsrtravel"])
    def test_identity_sensitive_scenes_do_not_prescribe_a_new_expression(self, scene_key):
        scene_prompt = ai_pipeline.resolve_tryon_scene(scene_key)["prompt"]
        banned = ("expression", "smile", "reassuring", "looking composed", "confident expression")
        assert all(word not in scene_prompt for word in banned)
        assert "compatible with her existing gaze direction" in scene_prompt


def test_scene_swap_framing_is_waist_up_with_both_bounds():
    """构图锚点（2026-07-31）：这条子句已在 07-27 与 07-31 之间来回过一次，
    且回退是静默的——原有 `assert "85mm" in prompt` 挡不住任何回退（85mm 在
    _TRYON_SCENE_CLAUSE 里另有一份）。上下两道边界必须同时在场：
    收太远发丝看不清，放太近就是 07-27 的大头畸变。"""
    session = _session()
    wig = ExpoWig(model_no="LS-9", name="胎毛波波", wig_description="airy bob")
    row = ExpoResult(session_id=1, wig_id=9,
                     scene_json={"key": "whitecollar", "label": "白领高管"})
    prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)

    assert "waist-up" in prompt                      # 下限：收到腰上，发丝可辨
    assert "one third of the frame height" in prompt  # 上限：头占画面高约 1/3
    assert "shoulders and upper torso must stay in frame" in prompt
    assert "no wide-angle facial distortion" in prompt  # 防 07-27 畸变复发
    # 已被证伪的旧口径不得回填
    assert "mid-thigh" not in prompt
    assert "one-seventh" not in prompt
    # 「主体/subject」是摆拍语义，会顶掉 07-09 定稿的抓拍感
    assert "subject of this photograph" not in prompt


def _variant_prompts(variant="real"):
    """三条出图路径各取一份 prompt：换发的两条场景分支 + 场景大片。"""
    wig = ExpoWig(model_no="LS-7", name="空气刘海", wig_description="airy fringe")
    swap = ExpoResult(session_id=1, wig_id=7,
                      scene_json={"key": "whitecollar", "label": "白领高管"})
    keep = ExpoResult(session_id=1, wig_id=7)          # 无 scene_json → 原景保持
    scene = ExpoResult(session_id=1, wig_id=None,
                       scene_json={"key": "banquet", "label": "晚宴礼遇"})
    build = ai_pipeline._build_prompt
    return {
        "场景置换": build(_session(), swap, wig, variant=variant)[0],
        "原景保持": build(_session(), keep, wig, variant=variant)[0],
        "场景大片": build(_session(mode="scene"), scene, None, variant=variant)[0],
    }


class TestPromptVariantSwitch:
    """合成版本（2026-08-01）：客户在甄选页必选，三版差别**只在皮肤怎么处理**。

    用光是三版共有的底座——「真实版」是真实的好照片，不是没打光的照片。
    最要命的失败形态是「一个非法值让展位生不出图」，所以回落而不是抛。
    """

    def test_all_three_variants_light_the_face(self):
        """用光底座三版共有：真实版若不打光，今早那条「脸上没精神」的反馈
        对每个不改默认值的客户就原封不动地留着。"""
        for name in ai_pipeline.PROMPT_VARIANTS:
            clause = ai_pipeline.resolve_prompt_variant(name)
            assert "never flat, dim or muddy" in clause, f"{name} 没打光"
            assert "distinct catchlights" in clause, f"{name} 缺眼神光"

    def test_skin_handling_is_what_actually_differs(self):
        """三版不能是「换了措辞的同一件事」——上一个选择器就是因为假选择被撤的。
        真实/柔光锁死皮肤纹理，美颜明确要求磨皮，这是可断言的实质差异。"""
        real = ai_pipeline.resolve_prompt_variant("real")
        soft = ai_pipeline.resolve_prompt_variant("soft")
        beauty = ai_pipeline.resolve_prompt_variant("beauty")

        for keeps_texture in (real, soft):
            assert "do not smooth, retouch, plump, lighten or rejuvenate" in keeps_texture
            assert "soften fine lines" not in keeps_texture
        assert "soften fine lines and wrinkles" in beauty
        assert "do not smooth, retouch" not in beauty      # 美颜版必须真的放开
        assert soft != real                                 # 柔光≠真实：另有柔光措辞
        assert "softer, more diffused light" in soft

    def test_beauty_variant_protects_the_hair(self):
        """磨皮会连带把发丝磨成塑料感，而发丝正是要卖的东西——美颜版必须显式护发。"""
        beauty = ai_pipeline.resolve_prompt_variant("beauty")
        assert "facial skin ONLY" in beauty
        assert "never soften, blur, smooth or plasticise the hair" in beauty
        # 另两版不需要这句（它们本来就不修皮肤）
        assert "plasticise the hair" not in ai_pipeline.resolve_prompt_variant("real")

    @pytest.mark.parametrize("bad", ["", None, "REAL", "美颜", "v1", "off", "x"])
    def test_blank_or_unknown_falls_back_to_default_without_raising(self, bad):
        """空值是正常情况（085 迁移前的老行、老代码写的行），非法值是笔误——都回落，绝不抛。"""
        assert ai_pipeline.resolve_prompt_variant(bad) ==             ai_pipeline.resolve_prompt_variant(ai_pipeline.DEFAULT_PROMPT_VARIANT)

    def test_default_is_the_first_option_shown_to_customers(self):
        assert ai_pipeline.DEFAULT_PROMPT_VARIANT == ai_pipeline.PROMPT_VARIANTS[0] == "real"

    def test_beauty_prompt_has_no_self_contradiction(self):
        """审查 C1：收尾句排在版本子句之后且是全篇最后一句，位置权重更高。
        美颜版要磨皮，收尾句若仍写 no over-smoothing / visible pores，就是自相矛盾——
        文字看着变了，指令未必活到出图，那是换了形态的假选择。"""
        for name, prompt in _variant_prompts(variant="beauty").items():
            assert "soften fine lines and wrinkles" in prompt, f"{name} 没吃到美颜版"
            # 这两条是矛盾本体，三条路径都不该出现
            assert "no over-smoothing" not in prompt, f"{name} 收尾句仍禁磨皮，与美颜版打架"
            assert "true skin texture with visible pores" not in prompt, f"{name} 收尾句仍要求毛孔"
            if "场景大片" in name:
                continue  # scene 模式不带 tryon 收尾句，它有自己的 _SCENE_TAIL 做 realism 锚
            # 换发两条路径：realism 与发丝保护不能跟着矛盾项一起被摘掉
            assert "individual hair strands with natural sheen" in prompt, f"{name} 丢了发丝要求"
            assert "No plastic skin" in prompt, f"{name} 丢了禁塑料感"

    def test_texture_variants_keep_the_strict_tail(self):
        """真实/柔光两版必须保留原收尾句——它们本来就不修皮肤，禁项与子句一致。"""
        for variant in ("real", "soft"):
            for name, prompt in _variant_prompts(variant=variant).items():
                if "场景大片" in name:
                    continue  # scene 模式本就没有 tryon 收尾句
                assert "no over-smoothing" in prompt, f"{variant}/{name} 丢了禁磨皮"

    def test_variant_reaches_every_output_path(self):
        """三条出图路径都要吃到版本子句——漏一条就是「有的图修了有的没修」。"""
        for name, prompt in _variant_prompts(variant="beauty").items():
            assert "soften fine lines and wrinkles" in prompt, f"{name} 没吃到版本"


class TestPromptVariantWiring:
    """接线覆盖（2026-08-01 对抗性审查 C2）。

    审查做了三个变异——start_composites 不写该字段、start_scene_composites 不写、
    _run_composite 写死 "real"——每一个都等价于「客户点的那一下永远到不了图上」，
    而 1074 条测试**全部照常通过**。当时的测试全压在提示词文本上，接线一根没测。
    这正是 2026-07-31 那个「假选择」档位选择器犯过一次的错，不能再犯第二次。
    """

    @staticmethod
    def _captured_rows(monkeypatch, call):
        """打桩 _start_batch 捕获「构造出来的 result 行」。

        真调 start_composites 会自建 session 并起线程打 AI——测试里不能跑，
        而要防的那两个变异（构造时漏写字段）恰好就发生在打桩点之前。
        """
        seen = []
        monkeypatch.setattr(ai_pipeline, "_start_batch", lambda sid, rows: seen.extend(rows))
        call()
        return seen

    def test_tryon_choice_lands_on_every_row(self, monkeypatch):
        """一次 generate 生成多条 result，每条都要带上客户选的版本。"""
        rows = self._captured_rows(
            monkeypatch,
            lambda: ai_pipeline.start_composites(1, [11, 22], prompt_variant="beauty"),
        )
        assert len(rows) == 2
        assert {r.prompt_variant for r in rows} == {"beauty"}

    def test_scene_choice_lands_on_every_row(self, monkeypatch):
        scenes = [{"key": "cafe", "label": "午后咖啡"}, {"key": "home", "label": "温馨居家"}]
        rows = self._captured_rows(
            monkeypatch,
            lambda: ai_pipeline.start_scene_composites(1, scenes, prompt_variant="soft"),
        )
        assert len(rows) == 2
        assert {r.prompt_variant for r in rows} == {"soft"}

    def test_composite_reads_the_stored_choice(self):
        """_run_composite 必须把 row.prompt_variant 传给 _build_prompt。

        直接锚源码：打桩整条 _run_composite 要 mock 掉 DB/AI/文件系统三层，
        维护成本高于它能挡的风险（同 test_stamp_precedes_display 的既有取舍）。
        写死任何字面量都会让这条挂掉。
        """
        import inspect

        src = inspect.getsource(ai_pipeline._run_composite)
        assert "variant=row.prompt_variant" in src, "合成没有读取落库的版本，选择到不了图上"

    def test_generate_request_accepts_and_rejects_the_right_values(self):
        for good in ai_pipeline.PROMPT_VARIANTS:
            assert GenerateRequest(prompt_variant=good).prompt_variant == good
        assert GenerateRequest().prompt_variant is None  # 老客户端不传 → 后端回落
        for bad in ("REAL", "glam", "美颜", "real "):
            with pytest.raises(ValidationError):
                GenerateRequest(prompt_variant=bad)


class TestLightingBase:
    """三版共有的用光底座（2026-08-01）：补的是用光与眼神。

    真实/柔光两版最容易被后人"顺手优化"成美颜词，那样就跟美颜版没区别了。
    正反两面都锚死。
    """

    def test_present_on_every_output_path(self):
        """脸的用光与场景无关，三条路径都得有——漏一条就是「有的图有神采有的没有」。"""
        for name, prompt in _variant_prompts().items():
            assert "never flat, dim or muddy" in prompt, f"{name} 缺面部用光指令"
            assert "distinct catchlights" in prompt, f"{name} 缺眼神光指令"

    def test_face_geometry_lock_on_every_variant_and_path(self):
        """对称几何锁（2026-08-01 补光上线次日瘦脸客户两颊变胖，2026-08-02 修）：
        锁必须①对称（neither slimmer nor fuller）②正向锚回第一张图③带表情豁免——
        场景置换放开表情且场景文案明写 smile，无豁免的 exact geometry 会僵脸或被无视。
        三版三路径全查——锁在 _LIGHTING_BASE 里，谁把它挪进单个版本就会在这里挂掉。"""
        for variant in ai_pipeline.PROMPT_VARIANTS:
            for name, prompt in _variant_prompts(variant=variant).items():
                assert "neither slimmer nor fuller" in prompt, f"{variant}/{name} 缺对称几何锁"
                assert "same face width, cheek contour and jawline" in prompt, \
                    f"{variant}/{name} 缺脸型几何锚定"
                assert "locks her facial structure, not her expression" in prompt, \
                    f"{variant}/{name} 几何锁缺表情豁免"
        # 美颜版必须在磨皮指令**之后**再锁一次几何（含 eye size——磨皮语境下笑会眯眼）；
        # 位置权重靠后，先锁后磨等于没锁，顺序也锚死
        beauty = ai_pipeline.resolve_prompt_variant("beauty")
        relock = "cheek contour, jawline and eye size"
        assert relock in beauty, "美颜版缺磨皮后几何复锁"
        assert beauty.index("smooth, luminous finish") < beauty.index(relock), \
            "几何复锁必须排在磨皮指令之后"

    def test_one_way_slimming_ban_stays_dead(self):
        """旧措辞回归探测（2026-08-02 病灶三件套）：「do not slim the face」单向禁令、
        「heavy fill / 无上限填光」、「warmth in the cheeks」苹果肌血色意象。
        扫**整段 prompt**而非仅版本子句——加回场景子句或合成模板同样要挂。"""
        for variant in ai_pipeline.PROMPT_VARIANTS:
            for name, prompt in _variant_prompts(variant=variant).items():
                where = f"{variant}/{name}"
                assert "do not slim the face" not in prompt, f"{where} 单向禁令回潮"
                assert "heavy fill" not in prompt, f"{where} 重填光措辞回潮"
                assert "lift the shadow side with gentle fill" not in prompt, \
                    f"{where} 无上限填光措辞回潮"
                assert "warmth in the cheeks" not in prompt, f"{where} 苹果肌血色意象回潮"

    def test_default_variant_keeps_the_anti_retouch_guards(self):
        """默认版（真实）打光不等于放开磨皮：禁项必须与给项同时在场，缺一就会滑向美颜。"""
        for name, prompt in _variant_prompts(variant="real").items():
            assert "do not smooth, retouch, plump, lighten or rejuvenate" in prompt, name
            assert "wrinkle, eye bag and age spot stays exactly as in the original" in prompt, name
            assert "light may model her features, never reshape them" in prompt, name

    def test_only_the_beauty_variant_may_use_retouch_words(self):
        """radiant/glowing/youthful 是美颜滤镜触发词：真实/柔光两版一旦沾上就翻车成磨皮脸。
        美颜版**刻意**放开——那正是它要的效果，所以按版本分别断言，不能一刀切。

        **只扫版本子句、不扫整段 prompt**：场景文案里的 "softly glowing presentation
        screen" 讲的是屏幕发光，与皮肤无关，扫全段会把它误判成美颜词。
        """
        banned = re.compile(r"(radiant|glowing|youthful|flawless|blemish-free|porcelain)",
                            re.I)
        for name in ("real", "soft"):
            hit = banned.search(ai_pipeline.resolve_prompt_variant(name))
            assert not hit, f"{name} 版出现美颜触发词 {hit.group() if hit else ''}"

    def test_no_variant_mentions_age(self):
        """任何一版出现 mature/elderly 都会把人往老里推，正好与诉求相反——三版都不许。"""
        banned = re.compile(r"(elderly|mature|middle-aged|older woman)", re.I)
        for name in ai_pipeline.PROMPT_VARIANTS:
            hit = banned.search(ai_pipeline.resolve_prompt_variant(name))
            assert not hit, f"{name} 版出现年龄描述 {hit.group() if hit else ''}"


def test_keep_bg_path_has_no_framing_clause():
    """原景保持要求构图与客户原照片一致，构图子句注入进去就是自相矛盾。"""
    session = _session()
    wig = ExpoWig(model_no="LS-8", name="轻盈波波", wig_description="short bob")
    row = ExpoResult(session_id=1, wig_id=8)  # 无 scene_json → keep_bg 分支
    prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)
    assert "waist-up" not in prompt
    assert "mid-thigh" not in prompt
    assert "background and framing exactly the same" in prompt


def test_build_prompt_keep_bg_has_no_variation():
    """原景保持路径服装整体锁定：夏装子句与穿搭变奏都不得注入。"""
    session = _session()
    wig = ExpoWig(model_no="LS-1", name="轻盈波波", wig_description="short bob")
    row = ExpoResult(session_id=1, wig_id=1)
    prompt, _, _ = ai_pipeline._build_prompt(session, row, wig)
    assert "It is summer" not in prompt
    assert "Accessorize with" not in prompt
    assert "For this shot, dress her in" not in prompt


def test_build_prompt_scene_mode_injects_variation():
    session = _session(mode="scene")
    row = ExpoResult(session_id=1, wig_id=None, scene_json={"key": "cafe", "label": "午后咖啡"})
    prompt, _, _ = ai_pipeline._build_prompt(session, row, None)
    assert "For this shot, dress her in" in prompt
    assert "heart-shaped pendant" in prompt


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
        updated_at=beijing_now() - timedelta(seconds=secs),
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
