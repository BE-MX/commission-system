"""展会试戴 AI 管线：面容分析 → 效果图合成 → 双轨话术生成。

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


# ---------------- 管线一：面容分析（含匹配） ----------------

_ANALYSIS_INSTRUCTION = """请分析照片中人物的面容特征，只输出 JSON（不要任何解释文字），结构如下：
{"gender":"female|male","age_range":"如 40-50","face_shape":"oval|round|square|heart|long|diamond",
"skin_tone":{"depth":"fair|light|medium|tan","undertone":"cool|warm|neutral"},
"temperament":"知性优雅|减龄轻盈|自然日常|端庄大气|温柔清纯|时尚轻熟","suit_length":"short|bob|shoulder|long",
"display_notes":"一句对顾客友好的正面描述，30字内",
"internal":{"hair_condition":"发量正常|发缝偏稀|头顶稀疏|白发比例高","sales_note":"给销售的一句建议"},
"confidence":0.9}
注意：display_notes 只写正面特征；发量/头皮的判断只写进 internal。"""


def start_analysis(session_id: int) -> None:
    """router 调用入口：后台线程执行分析+匹配。"""
    threading.Thread(target=_run_analysis, args=(session_id,), daemon=True).start()


def _run_analysis(session_id: int) -> None:
    from app.ai.service import chat

    db = SessionLocal()
    try:
        session = db.get(ExpoSession, session_id)
        if not session:
            return
        result = chat(
            db=db,
            preset_name=ANALYSIS_PRESET,
            messages=_image_message(_ANALYSIS_INSTRUCTION, [to_abs(session.photo_path)]),
            caller_module="expo",
        )
        analysis = _parse_json(result.get("content", ""))

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

_COMPOSITE_TEMPLATE = (
    "Replace the person's hair in the first photo with the wig shown in the reference "
    "image(s): {description}. Keep the face, skin tone, expression and background exactly "
    "the same. The hairline transition must look natural, hair should fall with realistic "
    "physics, and lighting direction must match the original photo. {extra}"
)

# 发色注入合成 prompt，来源 ark_expo_hair_colors 快照。
# 有色板图时把它作为最后一张参考图随图送入模型，描述与图互为锚点；无图时退化为纯文本描述
_COLOR_SWATCH_CLAUSE = (
    " The LAST reference image is a hair color swatch. After replacing the hair, "
    "recolor it to exactly match the swatch: {name} (color code {code}{hex_part}). "
    "{description}The color must look like naturally grown human hair with realistic "
    "depth, dimension and shine under the original photo's lighting. Do not change "
    "the hairstyle shape or length, and do not alter the face."
)

_COLOR_TEXT_CLAUSE = (
    " After replacing the hair, recolor it to this exact hair color: {name} "
    "(color code {code}{hex_part}). {description}The color must look like naturally "
    "grown human hair with realistic depth, dimension and shine under the original "
    "photo's lighting. Do not change the hairstyle shape or length, and do not alter "
    "the face."
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


def start_composites(session_id: int, wig_ids: list[int], hair_color: dict | None = None) -> None:
    """tryon 模式：每款一条 result，发色快照随 result 落库并注入 prompt。"""
    rows = [
        ExpoResult(session_id=session_id, wig_id=wig_id, hair_color_json=hair_color, status="generating")
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

    for result_id in result_ids:
        threading.Thread(target=_run_composite, args=(session_id, result_id), daemon=True).start()


def _build_prompt(session: ExpoSession, row: ExpoResult, wig: ExpoWig | None) -> tuple[str, list[Path]]:
    """按 result 形态组装 prompt 与图片：有 scene_json 走场景模板，否则走换发模板。"""
    if row.scene_json:
        scene = next((s for s in SCENES if s["key"] == row.scene_json.get("key")), None)
        prompt = _SCENE_TEMPLATE.format(scene=scene["prompt"] if scene else row.scene_json.get("label", ""))
        return prompt, [to_abs(session.photo_path)]

    refs = [to_abs(p) for p in (wig.angle_photos or [])[:2] if to_abs(p).exists()]
    if not refs and wig.cover_path and to_abs(wig.cover_path).exists():
        refs = [to_abs(wig.cover_path)]
    # 三图合成：自拍 + 发型参考图 + 色板图（色板图固定放末位，与 prompt 的 LAST 指代对齐）
    swatch = _color_swatch_path(row.hair_color_json)
    prompt = _COMPOSITE_TEMPLATE.format(
        description=wig.wig_description or wig.name,
        extra=wig.composite_prompt or "",
    ) + _color_clause(row.hair_color_json, with_swatch=swatch is not None)
    images = [to_abs(session.photo_path), *refs]
    if swatch:
        images.append(swatch)
    return prompt, images


def _run_composite(session_id: int, result_id: int) -> None:
    from app.ai.image_service import edit_image

    db = SessionLocal()
    started = time.monotonic()
    try:
        row = db.get(ExpoResult, result_id)
        session = db.get(ExpoSession, session_id)
        wig = db.get(ExpoWig, row.wig_id) if row.wig_id else None

        prompt, images = _build_prompt(session, row, wig)
        result = edit_image(
            db=db,
            preset_name=COMPOSITE_PRESET,
            prompt=prompt,
            images=[
                {
                    "filename": path.name,
                    "content": path.read_bytes(),
                    "content_type": _image_content_type(path),
                }
                for path in images
            ],
            caller_module="expo",
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
    """所有效果图出结果后，把会话推进到 done 并触发话术生成。"""
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
            # scene 模式无面容分析，话术生成没有输入依据，跳过
            if updated and not session.strategy_json and session.mode != "scene":
                threading.Thread(target=_run_strategy, args=(session_id,), daemon=True).start()
    finally:
        db.close()


# ---------------- 管线三：双轨话术生成 ----------------


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


def _run_strategy(session_id: int) -> None:
    db = SessionLocal()
    try:
        session = db.get(ExpoSession, session_id)
        if not session:
            return
        tags = _audience_tags(session)
        materials = script_service.pick_scripts(db, tags)

        def fmt(items):
            return "\n".join(f"- [{s.title}] {s.content}" for s in items)

        context = (
            f"客户：{session.customer.name}，最关心：{session.customer.primary_need}，"
            f"风格偏好：{session.customer.style_pref}\n"
            f"面容分析：{json.dumps(public_analysis(session.analysis_json), ensure_ascii=False)}\n"
            f"内部发况（仅供话术参考，不得在话术中直说负面）："
            f"{json.dumps((session.analysis_json or {}).get('internal') or {}, ensure_ascii=False)}\n"
            f"客户心动款：{[r.wig.name for r in session.results if r.reaction == 'loved' and r.wig]}\n\n"
            f"可用话术素材：\n开场（情感线）：\n{fmt(materials['openers'])}\n"
            f"逼单（理性/身份线）：\n{fmt(materials['closers'])}\n"
            f"异议应对：\n{fmt(materials['faqs'])}\n\n"
            f"可引用证据（只许用这些事实，不许自编数据）："
            f"{json.dumps(script_service.EVIDENCE_POINTS, ensure_ascii=False)}\n\n"
            '请输出 JSON：{"opener":"情感线开场话术，口语化2-3句","followup":"理性线跟进要点，2-3句",'
            '"objections":[{"q":"客户可能的问题","a":"应对"}]}（恰好 2 条 objections）'
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
    """生成 + 禁用词硬校验：命中即带否定反馈重试一次，仍命中抛出走模板兜底。"""
    from app.ai.service import chat

    messages = [{"role": "user", "content": context}]
    for attempt in range(2):
        result = chat(db=db, preset_name=STRATEGY_PRESET, messages=messages, caller_module="expo")
        strategy = _parse_json(result.get("content", ""))
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
