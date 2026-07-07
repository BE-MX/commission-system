"""展会试戴 AI 管线：面容分析 → 效果图合成 ∥ 双轨话术生成（话术随合成启动并行，供顾问等图期间沟通）。

约定（cerebrum 已踩坑规避）：
- 线程内自建 SessionLocal，不复用请求 session
- image_url 不传 detail 字段；preset parameters 用 max_tokens
- 诊断信息 logger + print(flush=True) 双写（NSSM service.log 只认 print）
- AI 返回 JSON 需清洗 markdown 围栏；字段值不可直接信任
"""

import base64
import json
import logging
import re
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.expo import matching, script_service
from app.expo.models import ExpoResult, ExpoSession, ExpoWig

logger = logging.getLogger("commission.expo")

# 锚定仓库根：/uploads 静态挂载指向 REPO_ROOT/uploads（见 bootstrap/static_files.py），
# 不能用相对路径（CWD 是 backend/，会写错目录导致 URL 404）
REPO_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_ROOT = REPO_ROOT / "uploads" / "expo"
PHOTO_DIR = UPLOAD_ROOT / "photos"
RESULT_DIR = UPLOAD_ROOT / "results"


def to_rel(path: Path) -> str:
    """绝对路径 → 存库用的相对路径（uploads/expo/...，正斜杠）。"""
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def to_abs(rel: str | None) -> Path:
    """存库相对路径 → 读文件用的绝对路径（兼容历史绝对路径）。"""
    p = Path(rel or "")
    return p if p.is_absolute() else REPO_ROOT / p

ANALYSIS_PRESET = "expo_face_analysis"
COMPOSITE_PRESET = "expo_wig_composite"
STRATEGY_PRESET = "expo_sales_strategy"

# 客户屏允许展示的正面字段白名单（隐私红线：internal 只进销售端）
PUBLIC_ANALYSIS_FIELDS = (
    "gender", "age_range", "face_shape", "skin_tone",
    "temperament", "suit_length", "display_notes", "confidence",
)


def ensure_dirs() -> None:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)


def public_analysis(analysis: dict | None) -> dict | None:
    """剥掉 internal 等内部字段，供客户屏渲染。"""
    if not analysis:
        return None
    return {k: v for k, v in analysis.items() if k in PUBLIC_ANALYSIS_FIELDS}


def _log_fail(stage: str, session_id: int, exc: Exception) -> None:
    msg = f"[expo] {stage} failed session={session_id} err={type(exc).__name__}: {exc}"
    logger.exception(msg)
    print(msg, flush=True)


def _image_message(text: str, image_paths: list[Path]) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": text}]
    for path in image_paths:
        suffix = path.suffix.lower().lstrip(".") or "jpeg"
        media = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        b64 = base64.b64encode(path.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/{media};base64,{b64}"}})
    return [{"role": "user", "content": content}]


def _image_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


# 送模型前的统一压缩口径：发型库存在 2~16MB 原图，3 张参考图直传会把
# 上游生成拖过 300s 网关红线（2026-07-07 session=13 实case）
_MAX_SEND_EDGE = 1280
_SEND_JPEG_QUALITY = 88


def _prep_image(path: Path) -> dict:
    """随请求发送的图片统一降采样重编码；失败回退原始字节，不因压缩阻断合成。"""
    try:
        import cv2

        img = cv2.imread(str(path))
        if img is None:
            raise ValueError("unreadable image")
        h, w = img.shape[:2]
        scale = _MAX_SEND_EDGE / max(h, w)
        # 已达标的小 JPEG 原样发送，避免无谓的二次有损编码（自拍就是这形态）
        if scale >= 1 and path.suffix.lower() in (".jpg", ".jpeg") and path.stat().st_size <= 400 * 1024:
            return {"filename": path.name, "content": path.read_bytes(), "content_type": "image/jpeg"}
        if scale < 1:
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), _SEND_JPEG_QUALITY])
        if not ok:
            raise ValueError("jpeg encode failed")
        return {"filename": f"{path.stem}.jpg", "content": buf.tobytes(), "content_type": "image/jpeg"}
    except Exception as exc:
        msg = f"[expo] image prep fallback for {path.name}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        return {"filename": path.name, "content": path.read_bytes(), "content_type": _image_content_type(path)}


def _parse_json(content: str) -> dict:
    """清洗 markdown 围栏后解析 JSON；失败再尝试提取首个 {...} 块。"""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"AI 返回内容无法解析为 JSON: {text[:200]}")


def _chat_json(db, preset_name: str, messages: list, retries: int = 1) -> dict:
    """chat + JSON 解析；解析失败带纠错反馈重试（模型偶发输出非法 JSON，
    如字符串值内未转义双引号——线上 session=9/10 实case）。"""
    from app.ai.service import chat

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        result = chat(db=db, preset_name=preset_name, messages=messages, caller_module="expo")
        content = result.get("content", "")
        try:
            return _parse_json(content)
        except (ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            msg = f"[expo] {preset_name} json parse failed attempt={attempt} err={exc} content[:300]={content[:300]!r}"
            logger.warning(msg)
            print(msg, flush=True)
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": (
                    f"你的输出不是合法 JSON（解析错误：{exc}）。请重新输出：只输出一个严格合法的 "
                    "JSON 对象，不要任何解释文字或代码围栏；字符串值内部禁止出现英文双引号，"
                    "需要引用词语时用中文引号「」。"
                )},
            ]
    raise ValueError(f"AI JSON 解析重试后仍失败: {last_exc}")


# ---------------- 管线一：面容分析（含匹配） ----------------

_ANALYSIS_INSTRUCTION = """请分析照片中人物的面容特征，只输出 JSON（不要任何解释文字），结构如下：
{"gender":"female|male","age_range":"如 40-50","face_shape":"oval|round|square|heart|long|diamond",
"face_features":"脸型特征客观描述，40字内",
"skin_tone":{"depth":"fair|light|medium|tan","undertone":"cool|warm|neutral"},
"temperament":"知性优雅|减龄轻盈|自然日常|端庄大气|温柔清纯|时尚轻熟","suit_length":"short|bob|shoulder|long",
"display_notes":"一句对顾客友好的正面描述，30字内",
"internal":{"hair_condition":"发量正常|发缝偏稀|头顶稀疏|白发比例高","sales_note":"给销售的一句建议"},
"confidence":0.9}

face_shape 判定流程：先观察三个量——①脸长与脸宽的比例 ②额头/颧骨/下颌三段的宽度关系 ③下颌线走向与下巴形状，再按下列标准归类：
- oval 鹅蛋脸：脸长约为脸宽 1.3~1.5 倍，额头略宽于下颌，下巴圆润自然收窄
- round 圆脸：脸长与脸宽接近，脸颊饱满，下颌线圆滑无棱角，下巴短圆
- square 方脸：额头与下颌接近等宽，下颌角外扩明显，下颌线平直硬朗
- heart 瓜子脸：额头与颧骨明显宽于下颌，脸部线条向下收拢，下巴尖细
- long 长脸：脸长明显超过脸宽 1.5 倍，中庭偏长，两颊线条平直
- diamond 菱形脸：颧骨是全脸最宽点，额头与下巴均偏窄，太阳穴略显凹陷
介于两型之间时选更接近的一型，并在 face_features 中说明（如「偏鹅蛋的轻微长脸」）。
face_features 用客观中性措辞按「长宽比例→额头→颧骨→下颌线→下巴」的顺序描述观察到的事实
（如「脸长约为宽的1.4倍，额头适中，颧骨略高，下颌线平缓，下巴圆润」），
它是发型推荐与销售话术的依据，只描述不评价、不写建议。
注意：display_notes 只写正面特征；发量/头皮的判断只写进 internal；face_features 不在客户屏展示，如实描述即可。
输出必须是严格合法 JSON：字符串值内部禁止英文双引号，需要引用词语用中文引号「」。"""


def start_analysis(session_id: int) -> None:
    """router 调用入口：后台线程执行分析+匹配。"""
    threading.Thread(target=_run_analysis, args=(session_id,), daemon=True).start()


def _run_analysis(session_id: int) -> None:
    db = SessionLocal()
    try:
        session = db.get(ExpoSession, session_id)
        if not session:
            return
        analysis = _chat_json(
            db,
            ANALYSIS_PRESET,
            _image_message(_ANALYSIS_INSTRUCTION, [to_abs(session.photo_path)]),
        )

        reg = {
            "primary_need": session.customer.primary_need,
            "style_pref": session.customer.style_pref,
        }
        wigs = db.query(ExpoWig).filter(ExpoWig.is_active == 1).all()
        ranking = matching.match_wigs(wigs, analysis, reg)

        session.analysis_json = analysis
        session.matched_wig_ids = ranking
        session.status = "analyzed"
        session.updated_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        _log_fail("analysis", session_id, exc)
        session = db.get(ExpoSession, session_id)
        if session:
            session.status = "failed"
            session.error_message = f"analysis: {exc}"
            db.commit()
    finally:
        db.close()


# ---------------- 管线二：效果图合成（多款并行，双模式） ----------------

# tryon 合成模板（锚场色机魂结构；2026-07-07 从三格回退单场景——三格单图 200~300s+
# 撞上游网关 504 结构性走不通，场景改为用户单选，见 TRYON_SCENES）。
# 组装顺序：锚（主体锁定） + 发色子句 + 场景子句（原景/置换二选一） + 色机魂收尾。
_COMPOSITE_TEMPLATE = (
    "The FIRST image is the customer's own photo. The following wig reference image(s) "
    "show the exact wig to use, from multiple angles: {description}. Replace the "
    "customer's hair with this wig, matching its length, layering, fringe and volume "
    "exactly. Keep the customer's face, facial features, expression and skin tone "
    "exactly the same as the first image, with light natural makeup. The hairline "
    "transition must look naturally grown, with realistic fine baby hairs at the "
    "temples. {extra}"
)

# 场景子句：默认保持原景（body/背景/景深全锁定）；选场景时置换背景（可换装，
# 85mm 浅景深只在此路径——原景路径不能既要背景原封又要虚化）。prompt 只在服务端
_TRYON_KEEP_BG_CLAUSE = (
    " Keep the body, outfit, background and framing exactly the same as the first "
    "image, preserve the original photo's depth of field, and light the new hair to "
    "match the original photo's light direction."
)
_TRYON_SCENE_CLAUSE = (
    " Recreate the portrait in {scene}. Naturally adapt the background, outfit and "
    "lighting to the scene while keeping the person clearly recognizable; the hair "
    "highlights and shadows must follow the scene's light direction, blending naturally "
    "with no cut-and-paste look. Shot like a candid 85mm portrait with shallow depth "
    "of field focused on the face and hair."
)

# 色 + 魂 收尾
_TRYON_STYLE_TAIL = (
    " Photorealistic straight-out-of-camera quality: true skin texture with visible "
    "pores, individual hair strands with natural sheen and realistic physics. No "
    "plastic skin, no over-smoothing, no painterly or illustration look, no wig-cap "
    "artificiality, no heavy filter grading - one real moment of daily life."
)

# 输出规格：6 寸照片。单场景竖版 102×152mm（2:3 → 1024x1536）；
# 多场景合一横版 152×102mm（3:2 → 1536x1024）。size 走 /v1/images/edits 请求参数，
# prompt 内的规格文字只是二重锚定，真正的像素约束靠 size 参数
_SIZE_PORTRAIT = "1024x1536"
_SIZE_LANDSCAPE = "1536x1024"
_PORTRAIT_SPEC_CLAUSE = (
    " Output exactly one 6-inch portrait photo, 102x152mm, 2:3 vertical aspect ratio."
)

TRYON_SCENE_MULTI_KEY = "multi"

# tryon 可选生成场景（不选=原景）；光源方向显式声明，发丝受光跟随场景。
# multi=多场景合一：一张横版三联图（2026-07-07 重新引入——早先三格因 ELBNT 网关
# 504 回退，现 Provider 已切换且为可选项，单图慢不阻塞主路径）
TRYON_SCENES = [
    {"key": "home", "label": "居家", "tagline": "温馨日常",
     "prompt": ("a cozy living room beside a sofa, warm afternoon window light from "
                "her front-left, blurred green plants and wooden furniture behind")},
    {"key": "office", "label": "办公", "tagline": "职场利落",
     "prompt": ("a bright modern workspace, soft overhead daylight panels as the key "
                "light with a faint laptop-screen fill, blurred glass partitions behind")},
    {"key": "gathering", "label": "聚会", "tagline": "晚间光彩",
     "prompt": ("an evening dinner party, warm pendant light overhead as the key "
                "light, golden bokeh of string lights and candles behind")},
    {"key": TRYON_SCENE_MULTI_KEY, "label": "多场景合一", "tagline": "居家·办公·聚会 三景同框",
     "prompt": ""},  # multi 走 _build_multi_scene_prompt 整体替换，不用子句
]


def resolve_tryon_scene(key: str | None) -> dict | None:
    return next((s for s in TRYON_SCENES if s["key"] == key), None)


# 多场景合一：完整替换式 prompt（用户定稿 2026-07-07，锚场色机魂结构）。
# {subject_anchor}/{color_anchor} 按实际参考图与色板动态拼装，其余文字保持定稿原文
_MULTI_SCENE_PROMPT = """【输出规格 · 总纲】
仅生成一张6寸152*102mm横版图片。这是一次性的单张生成任务，不是多张图片的组合：在同一画布上采用三联式构图，从左至右划分为三个等宽区域，各占画面宽度的 1/3。区域之间无边框、无分割线，仅靠各区域场景本身的明暗与色温过渡自然区分。

【锚 · 主体锁定】
{subject_anchor}{color_anchor}人物的面部轮廓、五官、肤色与图1完全一致，一眼可辨认是同一人，不做任何美化改变；但绝不沿用图1中的表情、姿势、服装与配饰——这四项必须按各区域的场景重新设计，与场景完全匹配。妆容为自然淡妆。发际线过渡自然逼真，鬓角与颈后碎发有真实的生长感。画面内三个区域中出现的均为同一人物，其身份、发型、发色、妆容在整张图中严格统一；而表情、姿势、服装、配饰在三个区域中各不相同。

【场 · 场景空间】
在这一张图的三个区域中，同一人物依次置身于三个生活场景，每个区域的穿着、动作与神态由该场景决定：
① 左侧 1/3 区域 · 居家场景 —— 客厅沙发旁，人物穿舒适的浅色针织家居服，倚坐在沙发边双手捧一杯热饮，神情放松、带着惬意的浅笑；午后窗光从人物左前方射入，暖白色调，背景有绿植与木质家具的柔和虚化；
② 中间 1/3 区域 · 办公场景 —— 明亮办公室工位或会议区，人物穿干练的衬衫或轻西装外套，身体微侧坐在办公桌前、一手轻搭在笔记本旁，眼神专注、职业化的从容微笑；顶部柔和日光灯为主光源，人物面前笔记本屏幕有微弱补光，背景是虚化的玻璃隔断与同事身影；
③ 右侧 1/3 区域 · 聚会场景 —— 傍晚餐厅或朋友聚会包间，人物穿精致的连衣裙、佩戴简约耳饰，举杯回眸或正与镜头外的友人交谈，笑容明媚开怀；头顶暖色吊灯为主光源，背景有串灯与烛光形成的金色光斑虚化，氛围热闹松弛。
每个区域中人物的发丝受光方向必须与该区域光源方向一致，发丝有真实的高光与阴影层次；服装、动作、表情、配饰与该区域场景的气氛完全匹配、毫无违和感，人物与环境自然融合，无贴图感、无出画感。

【色 · 视觉风格】
高清写实的原相机直出照片质感：皮肤有真实毛孔与细腻纹理，发丝根根分明、光泽自然；色彩还原真实，白平衡随各区域光源自然变化但肤色在整张图中始终统一。
排除：过度磨皮、塑料感皮肤、油画感、插画感、AI 生成痕迹、发际线生硬、假发头套感、脱离环境光的悬浮感、过度饱和的滤镜调色、区域间生硬的直线拼缝感、三个区域服装姿势表情雷同只换背景的复制粘贴感。

【机 · 摄像语言】
85mm 人像镜头视角，三个区域均为胸部以上半身构图，浅景深背景虚化，对焦锁定人物面部与发丝；三个区域机位高度一致、人物占比一致，但人物朝向与取景角度各不相同（如正面、微侧、回眸），如同一位摄影师在三个场合为同一人随手拍下的生活照，无摆拍感。

【魂 · 创作目标】
同一位顾客戴上这款假发后，自然走进她生活里的三个日常瞬间——让她看到"这就是我明天的样子"，真实、自信、毫不违和。"""


def _build_multi_scene_prompt(
    wig: ExpoWig, refs_count: int, color: dict | None, with_swatch: bool,
) -> str:
    """多场景合一 prompt：定稿模板 + 按实际送图数量/色板有无动态拼装锚点句。"""
    swatch_note = "，最后一张为发色色板图" if with_swatch else ""
    if refs_count > 0:
        angles = "正面、左45度3/4侧面、右侧视角" if refs_count == 3 else "多角度"
        ref_span = "图2" if refs_count == 1 else f"图2-{refs_count + 1}"
        subject_anchor = (
            f"图1为顾客本人照片，{ref_span}为假发发型参考图（{angles}）{swatch_note}。"
            "将图1人物的头发替换为参考图中模特佩戴的假发款式，发型的长度、层次、刘海形态、"
            "蓬松度与参考图完全一致；"
        )
    else:
        subject_anchor = (
            f"图1为顾客本人照片{swatch_note}。将图1人物的头发替换为这款假发"
            f"（无参考图，严格按以下描述执行）：{wig.wig_description or wig.name}。"
            "发型的长度、层次、刘海形态、蓬松度与描述完全一致；"
        )

    if with_swatch:
        color_anchor = "发色以色板图为唯一基准。"
    elif color:
        desc = (color.get("description") or "").strip()
        color_anchor = (
            f"发色为「{color.get('name') or ''}」（色号 {color.get('code') or ''}）"
            + (f"：{desc}。" if desc else "。")
        )
    else:
        color_anchor = "发色与假发款式的原本颜色保持一致。"

    return _MULTI_SCENE_PROMPT.format(subject_anchor=subject_anchor, color_anchor=color_anchor)

# 发色注入合成 prompt，来源 ark_expo_hair_colors 快照。
# 有色板图时把它作为最后一张参考图随图送入模型，描述与图互为锚点；无图时退化为纯文本描述
_COLOR_SWATCH_CLAUSE = (
    " The LAST reference image is a hair color swatch. After replacing the hair, "
    "recolor it to exactly match the swatch: {name} (color code {code}{hex_part}). "
    "{description}The color must look like naturally grown human hair with realistic "
    "depth, dimension and shine under the final lighting. Do not change the "
    "hairstyle shape or length, and do not alter the face."
)

_COLOR_TEXT_CLAUSE = (
    " After replacing the hair, recolor it to this exact hair color: {name} "
    "(color code {code}{hex_part}). {description}The color must look like naturally "
    "grown human hair with realistic depth, dimension and shine under the final "
    "lighting. Do not change the hairstyle shape or length, and do not alter the face."
)

# scene 模式：客户佩戴假发实拍 → 保持人与发型不变，置换到场景（prompt 只在服务端）
SCENES = [
    {"key": "business", "label": "商务会议", "tagline": "职场气场 · 从容主导",
     "prompt": ("a bright modern executive boardroom with floor-to-ceiling windows, "
                "she wears elegant business attire and presents with confidence, soft daylight")},
    {"key": "banquet", "label": "晚宴礼遇", "tagline": "高定光影 · 优雅登场",
     "prompt": ("an elegant evening banquet hall with warm golden bokeh lights, "
                "she wears a refined evening dress, cinematic warm portrait lighting")},
    {"key": "cafe", "label": "午后咖啡", "tagline": "松弛日常 · 精致在线",
     "prompt": ("a sunlit boutique coffee shop by the window, casual chic outfit, "
                "warm afternoon light with shallow depth of field")},
    {"key": "travel", "label": "户外旅行", "tagline": "自然光下 · 状态满分",
     "prompt": ("an outdoor seaside promenade on a sunny day with a gentle breeze, "
                "light stylish travel outfit, natural golden-hour sunlight")},
    {"key": "home", "label": "温馨居家", "tagline": "舒适自在 · 优雅如常",
     "prompt": ("a cozy warm home living room with soft lamp light, comfortable "
                "premium knitwear, relaxed and genuine atmosphere")},
]

_SCENE_TEMPLATE = (
    "The person in the photo is wearing a premium wig as their hairstyle. Keep the "
    "person's face, facial features, hairstyle, hair color and hair length exactly the "
    "same as in the photo. Recreate it as a high-end magazine-quality portrait "
    "photograph set in {scene}. Naturally adapt the background, outfit and lighting to "
    "the scene while keeping the person clearly recognizable and the hair identical. "
    "The result must look like a real photograph, not an illustration."
)


def resolve_scenes(keys: list[str] | None) -> list[dict]:
    """场景 key → 场景定义；不传取默认前 3 个，未知 key 丢弃并去重。"""
    if not keys:
        return SCENES[:3]
    by_key = {s["key"]: s for s in SCENES}
    return [by_key[k] for k in dict.fromkeys(keys) if k in by_key]


def _color_swatch_path(color: dict | None) -> Path | None:
    """快照里的色板图 → 存在才作为参考图送入模型。"""
    if not color or not color.get("swatch_path"):
        return None
    path = to_abs(color["swatch_path"])
    return path if path.exists() else None


def _color_clause(color: dict | None, with_swatch: bool = False) -> str:
    if not color:
        return ""
    hex_val = color.get("hex") or ""
    description = (color.get("description") or "").strip()
    template = _COLOR_SWATCH_CLAUSE if with_swatch else _COLOR_TEXT_CLAUSE
    return template.format(
        name=color.get("name_en") or color.get("name") or "",
        code=color.get("code") or "",
        hex_part=f", hex {hex_val}" if hex_val else "",
        description=f"Color description: {description}. " if description else "",
    )


def start_composites(
    session_id: int, wig_ids: list[int],
    hair_color: dict | None = None, scene: dict | None = None,
) -> None:
    """tryon 模式：每款一条 result，发色/场景快照随 result 落库并注入 prompt。"""
    scene_snapshot = {"key": scene["key"], "label": scene["label"]} if scene else None
    rows = [
        ExpoResult(
            session_id=session_id, wig_id=wig_id,
            hair_color_json=hair_color, scene_json=scene_snapshot,
            status="generating",
        )
        for wig_id in wig_ids
    ]
    _start_batch(session_id, rows)


def start_scene_composites(session_id: int, scenes: list[dict]) -> None:
    """scene 模式：每个场景一条 result（wig_id 为空，场景快照落库）。"""
    rows = [
        ExpoResult(
            session_id=session_id, wig_id=None,
            scene_json={"key": scene["key"], "label": scene["label"]},
            status="generating",
        )
        for scene in scenes
    ]
    _start_batch(session_id, rows)


def _start_batch(session_id: int, rows: list[ExpoResult]) -> None:
    """状态置位 + 插行合并为一个事务；失败回滚并把会话标 failed（不许无声吞）。"""
    db = SessionLocal()
    result_ids: list[int] = []
    start_strategy = False
    try:
        session = db.get(ExpoSession, session_id)
        if not session:
            return
        session.status = "generating"
        for row in rows:
            db.add(row)
            db.flush()
            result_ids.append(row.id)
        db.commit()
        # 话术前置：合成等待的 1~5 分钟正是顾问的沟通窗口，话术在此刻并行生成，
        # 顾问在试戴线索台（自己的手机/电脑）立即可见；scene 模式无面容分析不生成
        start_strategy = session.mode != "scene" and not session.strategy_json
    except Exception as exc:
        db.rollback()
        _log_fail("composite-start", session_id, exc)
        result_ids = []
        session = db.get(ExpoSession, session_id)
        if session:
            session.status = "failed"
            session.error_message = f"composite-start: {exc}"
            db.commit()
    finally:
        db.close()

    if result_ids and start_strategy:
        _start_strategy_once(session_id)
    for result_id in result_ids:
        threading.Thread(target=_run_composite, args=(session_id, result_id), daemon=True).start()


def _build_prompt(
    session: ExpoSession, row: ExpoResult, wig: ExpoWig | None,
) -> tuple[str, list[Path], str | None]:
    """按 result 形态组装 (prompt, 图片, 输出尺寸)。

    分支按 wig_id 判定：无发型=scene 模式（佩戴实拍置换场景，尺寸沿用 preset 默认）；
    有发型=tryon 换发（竖版 6 寸），scene_json 是可选生成场景（原景/居家/办公/聚会/
    多场景合一——multi 为完整替换式 prompt，输出横版 6 寸三联图）。
    """
    if row.wig_id is None and row.scene_json:
        scene = next((s for s in SCENES if s["key"] == row.scene_json.get("key")), None)
        prompt = _SCENE_TEMPLATE.format(scene=scene["prompt"] if scene else row.scene_json.get("label", ""))
        return prompt, [to_abs(session.photo_path)], None

    # 多角度参考图取前 3 张（正面/45度/侧面），与模板的 multiple angles 声明对应
    refs = [to_abs(p) for p in (wig.angle_photos or [])[:3] if to_abs(p).exists()]
    if not refs and wig.cover_path and to_abs(wig.cover_path).exists():
        refs = [to_abs(wig.cover_path)]
    # 三图合成：自拍 + 发型参考图 + 色板图（色板图固定放末位，与 prompt 的 LAST/最后一张 指代对齐）
    swatch = _color_swatch_path(row.hair_color_json)
    images = [to_abs(session.photo_path), *refs]
    if swatch:
        images.append(swatch)

    tryon_scene = resolve_tryon_scene((row.scene_json or {}).get("key"))
    if tryon_scene and tryon_scene["key"] == TRYON_SCENE_MULTI_KEY:
        prompt = _build_multi_scene_prompt(
            wig, len(refs), row.hair_color_json, with_swatch=swatch is not None,
        )
        return prompt, images, _SIZE_LANDSCAPE

    scene_clause = (
        _TRYON_SCENE_CLAUSE.format(scene=tryon_scene["prompt"]) if tryon_scene
        else _TRYON_KEEP_BG_CLAUSE
    )
    prompt = (
        _COMPOSITE_TEMPLATE.format(
            description=wig.wig_description or wig.name,
            extra=wig.composite_prompt or "",
        )
        + _color_clause(row.hair_color_json, with_swatch=swatch is not None)
        + scene_clause
        + _TRYON_STYLE_TAIL
        + _PORTRAIT_SPEC_CLAUSE
    )
    return prompt, images, _SIZE_PORTRAIT


def _run_composite(session_id: int, result_id: int) -> None:
    from app.ai.image_service import edit_image

    db = SessionLocal()
    started = time.monotonic()
    try:
        row = db.get(ExpoResult, result_id)
        session = db.get(ExpoSession, session_id)
        wig = db.get(ExpoWig, row.wig_id) if row.wig_id else None

        prompt, images, size = _build_prompt(session, row, wig)
        result = edit_image(
            db=db,
            preset_name=COMPOSITE_PRESET,
            prompt=prompt,
            images=[_prep_image(path) for path in images],
            caller_module="expo",
            size=size,
        )
        image_path = _save_result_image(result, result_id)

        row.image_path = to_rel(image_path)
        row.gen_ms = int((time.monotonic() - started) * 1000)
        row.status = "done"
        row.short_code = _make_share_code(result_id)
        db.commit()
    except Exception as exc:
        db.rollback()
        _log_fail("composite", session_id, exc)
        row = db.get(ExpoResult, result_id)
        if row:
            row.status = "failed"
            row.gen_ms = int((time.monotonic() - started) * 1000)
            # 失败原因落会话（销售面板/线索台可见），免得排障只能翻 AI 调用日志
            session = db.get(ExpoSession, session_id)
            if session:
                session.error_message = f"composite#{result_id}: {exc}"
            db.commit()
    finally:
        _refresh_session_status(session_id)
        db.close()


def _save_result_image(ai_result: dict, result_id: int) -> Path:
    """从 AI 响应提取图片：data URL / 裸 base64 / http URL 三种形态。"""
    ensure_dirs()
    content = ai_result.get("content", "") or ""
    filename = f"expo_{result_id}_{uuid.uuid4().hex[:8]}.png"
    target = RESULT_DIR / filename

    data_match = re.search(r"data:image/\w+;base64,([A-Za-z0-9+/=]+)", content)
    if data_match:
        target.write_bytes(base64.b64decode(data_match.group(1)))
        return target

    url_match = re.search(r"https?://\S+?\.(?:png|jpe?g|webp)\S*", content)
    if url_match:
        req = urllib.request.Request(url_match.group(0), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            target.write_bytes(resp.read())
        return target

    stripped = content.strip()
    if len(stripped) > 1000 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", stripped[:2000] or " "):
        target.write_bytes(base64.b64decode(re.sub(r"\s", "", stripped)))
        return target

    raise ValueError(f"AI 响应中未找到图片数据（前 120 字符: {content[:120]}）")


def _make_share_code(result_id: int) -> str:
    return f"{result_id:x}{uuid.uuid4().hex[:6]}"


def _refresh_session_status(session_id: int) -> None:
    """所有效果图出结果后，把会话推进到 done；话术兜底补生成（正常路径已在合成启动时前置）。"""
    db = SessionLocal()
    try:
        session = db.get(ExpoSession, session_id)
        if not session or session.status != "generating":
            return
        rows = db.query(ExpoResult).filter(ExpoResult.session_id == session_id).all()
        if rows and all(r.status in ("done", "failed") for r in rows):
            # 条件 UPDATE 做互斥：多个 composite 线程同时收尾时只有一个赢家推进状态并触发话术
            updated = (
                db.query(ExpoSession)
                .filter(ExpoSession.id == session_id, ExpoSession.status == "generating")
                .update({"status": "done"}, synchronize_session=False)
            )
            db.commit()
            # 兜底：合成启动时的前置话术若失败/未跑，这里补一次（scene 模式无分析依据，跳过）
            if updated and not session.strategy_json and session.mode != "scene":
                _start_strategy_once(session_id)
    finally:
        db.close()


# ---------------- 管线三：双轨话术生成 ----------------

# 前置触发（合成启动）与兜底触发（合成完成）可能并发，同一会话只允许一个生成线程
_strategy_inflight: set[int] = set()
_strategy_lock = threading.Lock()


def _start_strategy_once(session_id: int) -> None:
    with _strategy_lock:
        if session_id in _strategy_inflight:
            return
        _strategy_inflight.add(session_id)

    def run() -> None:
        try:
            _run_strategy(session_id)
        finally:
            with _strategy_lock:
                _strategy_inflight.discard(session_id)

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception as exc:
        with _strategy_lock:
            _strategy_inflight.discard(session_id)
        msg = f"[expo] strategy thread start failed session={session_id}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)


def _audience_tags(session: ExpoSession) -> list[str]:
    analysis = session.analysis_json or {}
    internal = analysis.get("internal") or {}
    tags = ["通用"]
    need_map = {"volume": "长期佩戴", "gray_cover": "长期佩戴", "style_change": "打理时间敏感"}
    tags.append(need_map.get(session.customer.primary_need, "通用"))
    if "敏感" in (internal.get("sensitivity_hint") or ""):
        tags.append("敏感肌")
    if (analysis.get("suit_length") or "") in ("short", "bob"):
        tags.append("短发")
    loved_series = {
        r.wig.series
        for r in session.results
        if r.reaction == "loved" and r.wig is not None
    }
    if "zhizhen" in loved_series:
        tags.append("心动至臻")
    return tags


def _tried_wigs_block(session: ExpoSession) -> str:
    """本次试戴发型的真实特征清单——话术生成的唯一事实来源。

    特征/卖点来自发型库，匹配理由来自规则引擎，三者都可解释可追溯；
    没进清单的细节话术一律不许提，防止模型给发型编造不存在的特征。
    """
    reason_map = {
        item.get("wig_id"): item.get("reason") or ""
        for item in (session.matched_wig_ids or [])
        if isinstance(item, dict)
    }
    lines, seen = [], set()
    for r in session.results:
        wig = r.wig
        if wig is None or wig.id in seen:
            continue
        seen.add(wig.id)
        mark = "【客户心动】" if r.reaction == "loved" else ""
        line = f"- {mark}{wig.name}：特征={wig.wig_description or '无'}；卖点={wig.selling_points or '无'}"
        if reason_map.get(wig.id):
            line += f"；匹配理由={reason_map[wig.id]}"
        lines.append(line)
    return "\n".join(lines)


def _run_strategy(session_id: int) -> None:
    db = SessionLocal()
    try:
        session = db.get(ExpoSession, session_id)
        # strategy 已存在即跳过：把"前置/兜底不会双生成"从时序论证变成显式不变量
        if not session or session.strategy_json:
            return
        tags = _audience_tags(session)
        materials = script_service.pick_scripts(db, tags)

        def fmt(items):
            return "\n".join(f"- [{s.title}] {s.content}" for s in items)

        analysis = session.analysis_json or {}
        face_label = matching.FACE_SHAPE_LABELS.get(
            analysis.get("face_shape"), analysis.get("face_shape") or "未知"
        )
        context = (
            f"客户：{session.customer.name}，最关心：{session.customer.primary_need}，"
            f"风格偏好：{session.customer.style_pref}\n"
            f"客户脸型：{face_label}；脸型特征：{analysis.get('face_features') or '无补充描述'}\n"
            f"面容分析：{json.dumps(public_analysis(session.analysis_json), ensure_ascii=False)}\n"
            f"内部发况（仅供话术参考，不得在话术中直说负面）："
            f"{json.dumps(analysis.get('internal') or {}, ensure_ascii=False)}\n"
            f"本次试戴的推荐发型（话术的唯一事实来源）：\n{_tried_wigs_block(session) or '- 无'}\n"
            f"客户心动款：{[r.wig.name for r in session.results if r.reaction == 'loved' and r.wig]}\n\n"
            f"可用话术素材：\n开场（情感线）：\n{fmt(materials['openers'])}\n"
            f"逼单（理性/身份线）：\n{fmt(materials['closers'])}\n"
            f"异议应对：\n{fmt(materials['faqs'])}\n\n"
            f"可引用证据（只许用这些事实，不许自编数据）："
            f"{json.dumps(script_service.EVIDENCE_POINTS, ensure_ascii=False)}\n\n"
            '请输出 JSON：{"opener":"情感线开场话术，口语化2-3句","followup":"理性线跟进要点，2-3句",'
            '"objections":[{"q":"客户可能的问题","a":"应对"}]}（恰好 2 条 objections）\n'
            "硬性要求：\n"
            "1. opener 必须点名一款推荐发型（有心动款优先选心动款），并把该发型的具体特征与客户脸型"
            "特征做因果挂钩，讲清「这个特征为什么修饰这种脸型」（例：内扣发尾贴合下颌线，刚好柔化圆脸轮廓）；\n"
            "2. followup 围绕所点名发型的特征、卖点与可引用证据展开，不写与发型无关的泛泛赞美；\n"
            "3. 发型细节只能引用上面「推荐发型」清单里明确写到的内容——清单没提刘海就不许说刘海，"
            "没提发色就不许说发色，禁止杜撰发型不具备的特征。"
        )
        strategy = _generate_checked_strategy(db, context)
        session.strategy_json = strategy
        db.commit()
    except Exception as exc:
        db.rollback()
        _log_fail("strategy", session_id, exc)
        _fallback_strategy(session_id)
    finally:
        db.close()


def _generate_checked_strategy(db, context: str) -> dict:
    """生成 + 禁用词硬校验：命中即带否定反馈重试一次，仍命中抛出走模板兜底。
    JSON 解析失败的重试由 _chat_json 内部处理。"""
    messages = [{"role": "user", "content": context}]
    for attempt in range(2):
        strategy = _chat_json(db, STRATEGY_PRESET, messages)
        text_blob = json.dumps(strategy, ensure_ascii=False)
        hit = script_service.check_forbidden(text_blob)
        if not hit:
            return strategy
        messages.append({"role": "assistant", "content": text_blob})
        messages.append({
            "role": "user",
            "content": f"你的输出包含品牌禁用词 {hit}，这些词拉低高端定位。请重写，绝对不要出现这些词。",
        })
    raise ValueError(f"话术生成两次均命中禁用词: {hit}")


def _fallback_strategy(session_id: int) -> None:
    """AI 失败兜底：直接给话术卡库原文，销售端永远有内容。"""
    db = SessionLocal()
    try:
        session = db.get(ExpoSession, session_id)
        if not session:
            return
        materials = script_service.pick_scripts(db, _audience_tags(session))
        session.strategy_json = {
            "opener": materials["openers"][0].content if materials["openers"] else "",
            "followup": materials["closers"][0].content if materials["closers"] else "",
            "objections": [{"q": s.title, "a": s.content} for s in materials["faqs"]],
            "fallback": True,
        }
        db.commit()
    except Exception as exc:
        _log_fail("strategy-fallback", session_id, exc)
    finally:
        db.close()
