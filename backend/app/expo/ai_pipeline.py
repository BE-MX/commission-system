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
import os
import random
import re
import shutil
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from app.core.database import SessionLocal
from app.expo import matching, script_service
from app.expo.models import ExpoResult, ExpoSession, ExpoWig, ExpoWigColor

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
    # 送模型前统一走 _prep_image 压缩（最长边 1280 + JPEG q88）：面容分析原本直传 1~2MB
    # 原图，模型处理慢 + 上传慢，叠加上游拥堵撞 60s 超时（2026-07-08 实case）。判脸型不需要
    # 原分辨率，压后与生图路径口径一致；压缩失败回退原始字节不阻断
    content: list[dict] = [{"type": "text", "text": text}]
    for path in image_paths:
        prepped = _prep_image(path)
        b64 = base64.b64encode(prepped["content"]).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{prepped['content_type']};base64,{b64}"},
        })
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


# ── 上传图 / 展示图压缩 ──
# 生产的 /uploads 全部经 frp 隧道回源（云 Nginx → 本地 8002），图片体积直接决定
# 展会现场加载速度，也是隧道拥堵把 kiosk 轮询挤成 Network Error 的主因（2026-07-14）
UPLOAD_MAX_EDGE = 1600          # 素材上传（发型参考图/色板/客户照片）落盘口径
DISPLAY_MAX_EDGE = 1080         # 结果图 kiosk 展示版最长边（展位屏 1080p，够用）
_DISPLAY_JPEG_QUALITY = 85
DISPLAY_SUFFIX = "_disp.jpg"    # 约定式命名：{原图 stem}_disp.jpg 同目录，不入库不迁移


_PIL_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}


def _save_atomic(im, dest: Path, fmt: str, **save_kwargs) -> None:
    """先写临时文件再 os.replace 原子落位：编码/写盘中途失败（磁盘满、进程被杀）
    不会毁掉唯一原图，读侧（StaticFiles / display_rel_for 的 exists 探测）也永远
    看不到半写文件。失败向上抛，由调用方决定是否阻断。"""
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        im.save(tmp, fmt, **save_kwargs)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _flatten_rgb(im):
    """转 RGB 供 JPEG 编码；带透明通道的先铺白底（直接 convert 会把透明像素露成杂色底）。"""
    from PIL import Image

    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return im.convert("RGB")


def downscale_inplace(path: Path, max_edge: int = UPLOAD_MAX_EDGE) -> None:
    """上传图原地降采样重编码（保持文件名与扩展名 → 存库路径/存量引用零变更）。

    尺寸已达标的不动（避免无谓二次有损）；失败静默保留原图，不阻断上传。"""
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as src:
            if max(src.size) <= max_edge:
                return
            im = ImageOps.exif_transpose(src)  # 手机原片靠 EXIF 记录旋转，重编码前先转正
            if im is src:
                im = src.copy()  # 脱离源文件句柄：Windows 上 os.replace 覆盖打开中的文件会失败
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
        suffix = path.suffix.lower()
        fmt = _PIL_FORMATS.get(suffix, "PNG")
        if fmt == "JPEG":
            _save_atomic(_flatten_rgb(im), path, fmt,
                         quality=_DISPLAY_JPEG_QUALITY, optimize=True)
        else:
            _save_atomic(im, path, fmt)
    except Exception as exc:  # noqa: BLE001
        msg = f"[expo] upload downscale skipped ({path.name}): {exc}"
        logger.warning(msg)
        print(msg, flush=True)


def make_display_image(src: Path) -> Path | None:
    """结果原图 → kiosk 展示压缩版（{stem}_disp.jpg，长边 1080 q85）。

    原 PNG 完整保留（分享短链/线索台/打印口径不变），展示版只服务展位屏。
    失败返回 None，serialize 侧回退原图 URL，不阻断合成。"""
    try:
        from PIL import Image

        target = src.with_name(src.stem + DISPLAY_SUFFIX)
        with Image.open(src) as im:
            flat = _flatten_rgb(im)
            if max(flat.size) > DISPLAY_MAX_EDGE:
                flat.thumbnail((DISPLAY_MAX_EDGE, DISPLAY_MAX_EDGE), Image.LANCZOS)
            _save_atomic(flat, target, "JPEG",
                         quality=_DISPLAY_JPEG_QUALITY, optimize=True)
        return target
    except Exception as exc:  # noqa: BLE001
        msg = f"[expo] display image skipped ({src.name}): {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        return None


def display_rel_for(rel: str | None) -> str | None:
    """结果图存库路径 → 展示版相对路径；不存在（历史结果/生成失败）返回 None。"""
    if not rel:
        return None
    src = to_abs(rel)
    disp = src.with_name(src.stem + DISPLAY_SUFFIX)
    return to_rel(disp) if disp.exists() else None


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


# 只重试快速失败的 502/503（与合成同口径）。**504 不重试**：网关等上游超时本质就慢，
# 分析走多模态 chat 单次超时下限 120s、分析看门狗 STALE_PENDING_SECS(240s)，2 次慢速请求即越界，
# 迟到成功会被看门狗判死后覆写、前端已离场——同图片侧看门狗预算论证。
_CHAT_RETRY_STATUS = {502, 503}
_CHAT_MAX_ATTEMPTS = 3  # 首次 + 2 次重试


def _chat_with_transient_retry(db, preset_name: str, messages: list) -> dict:
    """chat 调用对上游 502/503 自动重试（与合成同口径；分析也偶发网关 502，2026-07-16 实证）。
    504/超时/其他错误不重试，按原样抛（守看门狗预算，见上方常量注释）。"""
    import urllib.error
    from app.ai.service import chat

    last_exc: Exception | None = None
    for attempt in range(1, _CHAT_MAX_ATTEMPTS + 1):
        try:
            return chat(db=db, preset_name=preset_name, messages=messages, caller_module="expo")
        except urllib.error.HTTPError as exc:
            if exc.code not in _CHAT_RETRY_STATUS:
                raise
            last_exc = exc
        if attempt < _CHAT_MAX_ATTEMPTS:
            msg = f"[expo] {preset_name} transient {getattr(last_exc,'code','?')}, retry {attempt}/{_CHAT_MAX_ATTEMPTS-1}"
            logger.warning(msg)
            print(msg, flush=True)
            time.sleep(1.5 * attempt)
    raise last_exc


def _chat_json(db, preset_name: str, messages: list, retries: int = 1) -> dict:
    """chat + JSON 解析；解析失败带纠错反馈重试（模型偶发输出非法 JSON，
    如字符串值内未转义双引号——线上 session=9/10 实case）。"""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        result = _chat_with_transient_retry(db, preset_name, messages)
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
    "The FIRST image is the customer's own photo — use it ONLY for the face, body and "
    "pose. The following wig reference image(s) show the EXACT wig to put on the customer, "
    "from multiple angles: {description}. CRITICAL: the customer's hair in the output MUST "
    "come entirely from these wig reference images. COMPLETELY remove and replace the "
    "customer's original hair from the first image — do NOT keep, retain or blend in any "
    "part of the original hairstyle (its length, shape, silhouette, parting, fringe, "
    "volume, texture or color); not a single strand of the original hair may remain. "
    "Reproduce the wig's exact silhouette, length, layering, fringe, volume, parting and "
    "texture precisely as shown in the reference images, even if it looks very different "
    "from the original hair. Keep the customer's face, facial features and skin tone "
    "exactly the same as the first image, with light natural makeup. The hairline "
    "transition must look naturally grown, with realistic fine baby hairs at the "
    "temples. {extra}"
)

# 夏季衣橱子句（2026-07-17 亮哥指令：展会在夏天；2026-07-21 依亮哥提供的两组穿搭参考
# 图重写——法式极简通勤基调取代原「裙装/T恤/POLO/旗袍」四类单一枚举，具体单品由
# _wardrobe_variation_clause 每次随机注入一套完整 look）：凡换装路径（tryon 场景置换 +
# scene 场景大片）统一夏季着装——轻薄短袖/无袖，干净中性色系的分离式单品自由组合。
# **不写具体品牌名**：图像模型见品牌名易生成 logo/花押字（侵权+穿帮），故用风格描述并
# 显式禁 logo。场景明确规定着装（制服/职业装/旗袍/舞蹈装）时着装属性优先，只换轻薄
# 短袖夏季版。原景保持路径锁定原服装，不注入本子句
_SUMMER_WARDROBE_CLAUSE = (
    " It is summer: dress her in lightweight breathable summer clothing with short "
    "sleeves or sleeveless cuts, in a clean French-minimalist everyday-chic register - "
    "effortless mix-and-match separates such as crisp shirts, fine knit tops, flowing "
    "midi skirts, straight or wide-leg trousers and well-cut jeans, in a calm neutral "
    "palette of white, cream, black, navy, light blue, grey, khaki-camel and denim "
    "washes; if the scene description prescribes specific attire (a uniform, a "
    "professional dress code, or a festive or activity-specific outfit), keep that "
    "attire but in a light short-sleeve summer version. The outfit must look "
    "thoughtfully styled, with a refined flattering silhouette that elevates her "
    "presence and the photo's overall quality - understated, timeless, with premium "
    "fabric texture and impeccable relaxed tailoring, and no visible brand logos or "
    "monograms."
)

# 穿搭 look 池（2026-07-21 亮哥指令：从两组穿搭参考图逐套提取，取代原配色×花纹随机
# 组合与「裙装单一描述」——法式极简通勤风，衬衫/针织/半裙/阔腿裤/牛仔裤的完整搭配，
# 中性色系：白/米/黑/藏青/浅蓝/灰/卡其驼/牛仔蓝）。静态 prompt 必然收敛到模型最高
# 概率输出（此前=小黑裙），多样性靠每次合成随机抽一套完整 look 注入；look 具体到
# 单品+颜色+鞋包配饰，锚定权重足以压过场景里的泛化着装词。参考图中的牛仔迷你裙已
# 调整为及膝长度（目标客群为中老年女性）。首饰池保留 2026-07-17 版不动
_OUTFIT_LOOKS = [
    # ── 参考图一（基础款通勤，8 套） ──
    "a light-blue oversized shirt worn open over a white tank top, with white "
    "straight-leg trousers and black loafers",
    "a fitted black short-sleeve tee tucked into a high-waisted khaki-camel flared "
    "midi skirt, with brown loafers",
    "a navy-and-white breton striped top with white straight-leg jeans and black "
    "pointed flats",
    "a crisp white shirt loosely tucked into mid-blue straight-leg jeans, with "
    "black loafers",
    "a cream fine-knit cardigan over a white top, with black high-waisted wide-leg "
    "trousers, a slim black belt and ballet flats",
    "a light-blue shirt with a navy sweater draped over the shoulders, mid-blue "
    "straight-leg jeans and brown loafers",
    "a white shirt worn open over a black tank top, with mid-blue wide-leg jeans "
    "and loafers",
    "an oatmeal-beige short-sleeve knit top tucked into a khaki-camel flared midi "
    "skirt, with brown pointed flats",
    # ── 参考图二（黑白极简实拍，8 套） ──
    "a black puff-sleeve short-sleeve shirt with a white flowy midi skirt, white "
    "socks and black low-profile sneakers",
    "a white elbow-sleeve shirt tucked into navy pleated wide-leg trousers with a "
    "slim brown belt",
    "a white short-sleeve shirt tucked into a white knee-length A-line skirt with "
    "a slim black belt and black loafers",
    "a grey short-sleeve henley knit top with relaxed light-wash wide-leg jeans",
    "a black puff-sleeve short-sleeve shirt with relaxed light-wash wide-leg jeans",
    "a black V-neck button-up vest worn as a top, with a voluminous white maxi skirt",
    "a white short-sleeve shirt tucked into off-white straight-leg jeans with a "
    "slim brown belt and loafers",
    "a white short-sleeve shirt tucked into a dark-indigo denim knee-length skirt "
    "with a slim brown belt, white socks and black loafers",
]
_JEWELRY_OPTIONS = [
    "small pearl stud earrings",
    "a slim jade bangle and simple gold ear studs",
    "delicate gold huggie earrings",
    "a fine gold chain with a tiny mother-of-pearl charm worn close to the collarbone",
    "an elegant patterned silk scarf knotted lightly at the neck",
    "a tasteful vintage brooch on the chest",
    "small celadon-glazed ceramic earrings",
    "a short string of freshwater pearls sitting at the collarbone",
]


def _wardrobe_variation_clause(uniform: bool = False) -> str:
    """每次合成随机抽一套完整穿搭 look，打散模型的默认收敛（小黑裙+心形长项链）。

    着装锁定场景（uniform=True：制服/职业装/旗袍/舞蹈装）服装不动，只注入首饰变奏。"""
    jewelry = random.choice(_JEWELRY_OPTIONS)
    jewelry_part = (
        f" Accessorize with {jewelry} - small, tasteful pieces in quietly luxurious "
        "materials with real texture (pearl, jade, gold, silk, mother-of-pearl). "
        "Never use a long necklace with a heart-shaped pendant."
    )
    if uniform:
        return jewelry_part
    look = random.choice(_OUTFIT_LOOKS)
    return (
        f" For this shot, dress her in {look}, adapted naturally in fit and formality "
        "to suit the scene while keeping these exact garment types and colors - "
        "not a plain all-black look and not a generic dress." + jewelry_part
    )

# 场景子句：默认保持原景（body/背景/景深全锁定）；选场景时置换背景（可换装，
# 85mm 浅景深只在此路径——原景路径不能既要背景原封又要虚化）。prompt 只在服务端
_TRYON_KEEP_BG_CLAUSE = (
    " Keep the facial expression, body, outfit, background and framing exactly the same "
    "as the first image, preserve the original photo's depth of field, and light the new "
    "hair to match the original photo's light direction."
)
# 场景置换（叙事化 · 单人收敛）：放开姿势/手势/表情让人物自然融入场景并呈现自信、投入的
# 神态；但硬锁面部身份与发型发色（与合成锚定一致，保证换脸不换人）；场景里的其他人物只作
# 虚化背景暗示，绝不清晰出镜——单人自拍合成出第二张清晰人脸/手极易崩坏（用户定稿 2026-07-09）
_TRYON_SCENE_CLAUSE = (
    " Recreate the portrait in {scene}. Naturally adapt the background, outfit, pose, "
    "gesture and facial expression to suit this scene with a confident, engaged demeanor "
    "- this refines the earlier same-face note, which locks identity, not expression. "
    "Keep the face's identity, bone structure and skin tone recognizably identical to the "
    "first image, and the hairstyle and hair color exactly as composited. Any other people "
    "may appear only as a soft, blurred, out-of-focus background presence - never in sharp "
    "focus, never with detailed faces or hands. The hair highlights and shadows must follow "
    "the scene's light direction, blending naturally with no cut-and-paste look. Shot like a "
    "candid 85mm documentary snapshot with shallow depth of field focused on the face and "
    "hair - caught naturally mid-action and unposed, as if a third person quietly "
    "photographed her in the moment. Her gaze and head are directed naturally within the "
    "scene (toward what she is doing, looking at or speaking to), not fixed straight at the "
    "camera unless that truly fits the moment, with a relaxed natural micro-expression rather "
    "than a stiff, posed, camera-facing studio look."
) + _SUMMER_WARDROBE_CLAUSE

# 色 + 魂 收尾
_TRYON_STYLE_TAIL = (
    " Photorealistic straight-out-of-camera quality: true skin texture with visible "
    "pores, individual hair strands with natural sheen and realistic physics. No "
    "plastic skin, no over-smoothing, no painterly or illustration look, no wig-cap "
    "artificiality, no heavy filter grading - one real moment of daily life."
)

# 输出规格：6 寸照片，单场景竖版 102×152mm（2:3 → 1024x1536）。size 走 /v1/images/edits
# 请求参数，prompt 内的规格文字只是二重锚定，真正的像素约束靠 size 参数
_SIZE_PORTRAIT = "1024x1536"
_PORTRAIT_SPEC_CLAUSE = (
    " Output exactly one 6-inch portrait photo, 102x152mm, 2:3 vertical aspect ratio."
)

# tryon 生成场景（换发路径）：kiosk 甄选发型页滑动选择、必选一个（原景仅弱网兜底）。
# 每条 prompt 是注入 _TRYON_SCENE_CLAUSE「Recreate the portrait in {scene}」的名词短语——
# 结构=场景空间 + 单人自信动作/姿态 + 主光源方向 + 虚化背景（含仅暗示的第二人物）。
# 职业场景带强动作（演示/讲解/接待/看材料/检查），叙事化但收敛为单人主体（用户定稿 2026-07-09）。
# 光源方向显式声明，发丝受光跟随场景。顺序即卡片顺序，默认选中第一个。
# 2026-07-17：服装全面夏季化（展会在夏天）。2026-07-21：非锁定景的场景内具体单品词
# （sheath dress/silk blouse/summer dress 等）泛化为 lightweight summer outfit——具体
# 单品改由尾部 _wardrobe_variation_clause 随机注入完整 look（亮哥参考图提取），场景内
# 保留 lightweight/summer 定性词继续压 blazer/suit 厚重词；着装锁定景（uniform: True，
# 制服/职业装外扩至旗袍/舞蹈装等场景规定装）单品词保留原样、不注入 look。
# 2026-07-10 扩到 20 景：新增银行/律师/药剂师/财务/社区主任/小区管理员/高铁出差等职场，及喜婆婆/
# 接孙放学/广场舞/老年大学/闺蜜咖啡/晨间公园等长辈生活景。长辈景用 poised/graceful/radiant/refreshed
# 等气质词表达「假发衬得更精致」，靠发型+光营造，不写 younger 以免与身份锁（保脸/保年龄）冲突。
TRYON_SCENES = [
    {"key": "whitecollar", "label": "白领高管", "tagline": "从容主场",
     "prompt": ("a bright modern corporate boardroom during a meeting, she stands "
                "confidently mid-presentation in a chic lightweight summer outfit, one hand gesturing "
                "naturally toward a softly glowing presentation screen, cool daylight "
                "from tall windows on her front-left as the key light, a long conference "
                "table and blurred out-of-focus seated colleagues far behind")},
    {"key": "teacher", "label": "老师", "tagline": "讲台风采",
     "prompt": ("a warm university lecture hall at the podium, she stands poised while "
                "teaching with an engaging open-hand gesture in an elegant lightweight summer outfit, "
                "soft daylight from her front as the key light, a blurred blackboard or "
                "projection behind and out-of-focus students seated far below, suggested "
                "only as soft shapes")},
    {"key": "shopowner", "label": "老板娘", "tagline": "门店主理",
     "prompt": ("an elegant boutique storefront, she stands warmly welcoming a guest "
                "with an inviting open gesture toward tasteful product displays in a "
                "refined lightweight summer outfit, soft warm shop lighting from her front-right as "
                "the key light, blurred shelves of merchandise and a faint out-of-focus "
                "customer beside her")},
    {"key": "civilservant", "label": "公务员", "tagline": "沉稳干练",
     "prompt": ("a composed government office meeting room, she sits in the front row "
                "reviewing documents with a calm attentive expression in a crisp "
                "lightweight summer outfit, even soft ceiling lighting as the key light, a blurred long "
                "table and out-of-focus colleagues seated further back")},
    {"key": "doctor", "label": "医生", "tagline": "专业信赖", "uniform": True,
     "prompt": ("a clean bright clinic consulting room, she stands professionally in a "
                "short-sleeve white coat with a stethoscope, attentive and reassuring as she reviews "
                "a chart, cool clinical daylight from her front as the key light, blurred "
                "medical shelving and a faintly out-of-focus patient seated to the side")},
    {"key": "home", "label": "居家", "tagline": "温馨日常",
     "prompt": ("a cozy living room beside a sofa, warm afternoon window light from "
                "her front-left, blurred green plants and wooden furniture behind")},
    {"key": "gathering", "label": "聚会", "tagline": "晚间光彩",
     "prompt": ("an evening dinner party, warm pendant light overhead as the key "
                "light, golden bokeh of string lights and candles behind")},
    # ── 职场专业（2026-07-10 扩充） ──
    {"key": "lawyer", "label": "律师", "tagline": "庭上锋芒", "uniform": True,
     "prompt": ("a solemn courtroom, she stands confidently delivering her argument with "
                "a composed articulate expression and a measured hand gesture in a sharp "
                "lightweight dark summer suit over a silk short-sleeve blouse, focused "
                "daylight from her front as the key light, blurred "
                "wooden benches and out-of-focus figures seated behind")},
    {"key": "banker", "label": "银行柜员", "tagline": "专业干练", "uniform": True,
     "prompt": ("a bright modern bank hall counter, she stands poised serving a customer "
                "with a courteous professional smile in a tidy short-sleeve summer uniform, cool even ceiling "
                "lighting as the key light, blurred glass partitions and a faint "
                "out-of-focus customer in front of the counter")},
    {"key": "accountant", "label": "公司财务", "tagline": "沉稳可靠",
     "prompt": ("a tidy modern office by a filing cabinet, she stands retrieving a "
                "document with a calm capable expression in an elegant lightweight summer outfit, soft daylight "
                "as the key light, a blurred desk with a monitor and a faint out-of-focus "
                "colleague waiting beside her")},
    {"key": "director", "label": "社区主任", "tagline": "亲切为民",
     "prompt": ("a warm community service center, she sits attentively helping an elderly "
                "resident fill out a form with a kind patient smile, pen in hand, in a smart "
                "lightweight summer outfit, soft daylight from a side window as the key light, blurred "
                "notice boards and a faint out-of-focus elderly resident across the desk")},
    {"key": "pharmacist", "label": "药剂师", "tagline": "专业亲和", "uniform": True,
     "prompt": ("a clean bright pharmacy, she stands filling a prescription at the medicine "
                "shelves with a warm attentive expression in a short-sleeve white pharmacist coat, soft "
                "even lighting from her front as the key light, blurred rows of medicine "
                "drawers and a faint out-of-focus customer waiting at the counter")},
    {"key": "propertymanager", "label": "小区管理员", "tagline": "邻里亲和",
     "prompt": ("a residential compound lobby, she stands chatting warmly with a resident "
                "while holding a notebook, a friendly approachable smile in a neat "
                "lightweight summer outfit, soft daylight from the entrance as the key light, blurred mailboxes "
                "and a faint out-of-focus resident beside her")},
    {"key": "hsrtravel", "label": "高铁出差", "tagline": "出差精致",
     "prompt": ("a high-speed train window seat, she sits looking composed and put-together "
                "with a subtle confident expression in a crisp lightweight summer outfit, a laptop on the tray, "
                "bright daylight streaming through the large train window as the key light, "
                "blurred landscape rushing past outside")},
    # ── 长辈 / 退休生活（发型提升气质，从容优雅，不改脸/年龄） ──
    {"key": "weddinghost", "label": "喜婆婆", "tagline": "喜庆体面", "uniform": True,  # 旗袍是场景规定装
     "prompt": ("an elegant wedding banquet entrance, she stands graciously welcoming guests "
                "with a warm delighted smile in a refined festive short-sleeve silk qipao with tasteful "
                "jewelry, looking poised and radiant, warm golden banquet lighting as the "
                "key light, a blurred floral arch and out-of-focus guests arriving behind")},
    {"key": "schoolpickup", "label": "接孙放学", "tagline": "校门风采",
     "prompt": ("a primary school gate in the afternoon, she stands waiting to pick up her "
                "grandchild with a warm expectant smile, in an elegant breezy summer outfit and "
                "looking notably graceful, soft afternoon daylight as the key light, a "
                "blurred school gate and out-of-focus parents and grandparents around her")},
    {"key": "squaredance", "label": "广场舞领舞", "tagline": "广场C位", "uniform": True,  # 舞蹈活动装是场景规定装
     "prompt": ("a community plaza at dusk, she leads a group dance rehearsal at the front "
                "with an energetic radiant smile mid-gesture in a bright well-cut T-shirt "
                "and comfortable summer activewear, warm low evening light as the key light, blurred plaza trees "
                "and out-of-focus dancers following behind her")},
    {"key": "seniorcollege", "label": "老年大学", "tagline": "老有所乐",
     "prompt": ("a bright senior-university classroom, she sits gracefully learning a "
                "musical instrument among peers with a joyful absorbed expression, holding "
                "the instrument, warm window daylight as the key light, blurred music stands "
                "and out-of-focus classmates around her")},
    {"key": "seniorcafe", "label": "闺蜜咖啡", "tagline": "闺蜜时光",
     "prompt": ("a cozy sunlit cafe, she sits chatting happily over coffee with friends, a "
                "relaxed radiant smile in a tasteful breezy summer outfit, warm afternoon window "
                "light as the key light, a blurred cafe interior and out-of-focus friends "
                "across the small table")},
    {"key": "parkwalk", "label": "晨间公园", "tagline": "晨间从容",
     "prompt": ("a green park path in the morning, she takes a leisurely walk looking "
                "refreshed and at ease with a gentle serene smile in an elegant "
                "lightweight summer outfit, soft golden morning light from her side as the key light, "
                "blurred trees and greenery behind")},
]


def resolve_tryon_scene(key: str | None) -> dict | None:
    return next((s for s in TRYON_SCENES if s["key"] == key), None)


# 场景分类（kiosk 甄选页分段展示，避免 20 景挤成单行长条；2026-07-10）。
# 顺序即 tab 顺序，默认第一类。分类不落库，仅驱动前端分组展示，scene_json 仍只存 key/label。
TRYON_SCENE_CATEGORIES = [
    {"key": "career", "label": "职场专业"},
    {"key": "life", "label": "长辈生活"},
]
_TRYON_LIFE_KEYS = {
    "home", "gathering", "weddinghost", "schoolpickup",
    "squaredance", "seniorcollege", "seniorcafe", "parkwalk",
}


def tryon_scene_category(key: str) -> str:
    """场景 key → 分类 key（不在长辈生活集合里的都归职场专业）。"""
    return "life" if key in _TRYON_LIFE_KEYS else "career"


# 场景示意图（kiosk 滑动选择器用，仅示意、不参与合成）：约定放 uploads/expo/scenes/<key>.<ext>。
# 后台/运营把实拍或 AI 生成图丢进该目录即自动生效，无需改代码；文件不存在则返回 None，
# 前端退化为金线渐变占位卡（用户定稿 2026-07-09：先上占位图，后续替换）。
SCENE_IMAGE_DIR = UPLOAD_ROOT / "scenes"
_SCENE_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


_SCENE_IMG_MAX_EDGE = 1200  # kiosk 一屏加载多张，超边长降采样控体积


def scene_image_url(key: str) -> str | None:
    """场景 key → 示意图公开 URL（/uploads/...），文件不存在返回 None。"""
    for ext in _SCENE_IMAGE_EXTS:
        p = SCENE_IMAGE_DIR / f"{key}{ext}"
        if p.exists():
            return "/" + p.resolve().relative_to(REPO_ROOT).as_posix()
    return None


def delete_scene_image(key: str) -> bool:
    """删除某场景的示意图（各扩展名都清，避免探测歧义）。返回是否删了文件。"""
    removed = False
    for ext in _SCENE_IMAGE_EXTS:
        p = SCENE_IMAGE_DIR / f"{key}{ext}"
        if p.exists():
            p.unlink()
            removed = True
    return removed


def save_scene_image(key: str, upload) -> str:
    """存场景示意图为 uploads/expo/scenes/<key>.<ext>；先删同 key 旧图（各扩展名）避免探测歧义。
    key 必须是 TRYON_SCENES 里的合法场景；扩展名限 jpg/jpeg/png/webp。返回公开 URL。"""
    if resolve_tryon_scene(key) is None:
        raise ValueError("场景不存在")
    suffix = Path(getattr(upload, "filename", "") or "").suffix.lower()
    if suffix not in _SCENE_IMAGE_EXTS:
        raise ValueError("仅支持 jpg / jpeg / png / webp 图片")
    SCENE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    delete_scene_image(key)
    target = SCENE_IMAGE_DIR / f"{key}{suffix}"
    with open(target, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    downscale_inplace(target, _SCENE_IMG_MAX_EDGE)
    return "/" + target.resolve().relative_to(REPO_ROOT).as_posix()


# 发色注入合成 prompt，来源 ark_expo_hair_colors 快照。
# 只用文本锚点（名称/色号/hex），色板图**不再**随图送入模型——实测色板参考图会把
# 合成结果拽偏（构图/人物位置偏移严重），hex 主色在上传色板时已提取（2026-07-14 亮哥指令）
_COLOR_TEXT_CLAUSE = (
    " After replacing the hair, recolor it to this exact hair color: {name} "
    "(color code {code}{hex_part}). {description}The color must look like naturally "
    "grown human hair with realistic depth, dimension and shine under the final "
    "lighting. Do not change the hairstyle shape or length, and do not alter the face."
)

# 组合参考图路径：三角度图本身就是「该发型该发色」实拍，参考图既定发型也既定发色，
# 所以只需让模型连颜色一起照搬，不再有 recolor 指令（2026-07-15 起，取代色板图/文字上色）
_COLOR_FROM_REFERENCE_CLAUSE = (
    " Match the hair color exactly as shown in the wig reference images - reproduce their "
    "hue, depth, tone and highlights faithfully. Do not recolor or shift the color; the "
    "reference images already show the exact target color."
)

# scene 模式：客户佩戴假发实拍 → 保持人与发型不变，置换到场景（prompt 只在服务端）
SCENES = [
    {"key": "business", "label": "商务会议", "tagline": "职场气场 · 从容主导",
     "prompt": ("a bright modern executive boardroom with floor-to-ceiling windows, "
                "she wears a chic lightweight summer outfit and presents with confidence, soft daylight")},
    {"key": "banquet", "label": "晚宴礼遇", "tagline": "高定光影 · 优雅登场", "uniform": True,  # 晚宴旗袍是场景规定装

     "prompt": ("an elegant evening banquet hall with warm golden bokeh lights, "
                "she wears a refined short-sleeve silk qipao, cinematic warm portrait lighting")},
    {"key": "cafe", "label": "午后咖啡", "tagline": "松弛日常 · 精致在线",
     "prompt": ("a sunlit boutique coffee shop by the window, a breezy chic summer outfit, "
                "warm afternoon light with shallow depth of field")},
    {"key": "travel", "label": "户外旅行", "tagline": "自然光下 · 状态满分",
     "prompt": ("an outdoor seaside promenade on a sunny day with a gentle breeze, "
                "a light stylish summer travel outfit with a breezy short-sleeve top, natural golden-hour sunlight")},
    {"key": "home", "label": "温馨居家", "tagline": "舒适自在 · 优雅如常",
     "prompt": ("a cozy warm home living room with soft lamp light, a soft comfortable "
                "summer outfit, relaxed and genuine atmosphere")},
]

_SCENE_TEMPLATE = (
    "The person in the photo is wearing a premium wig as their hairstyle. Keep the "
    "person's face, facial features, hairstyle, hair color and hair length exactly the "
    "same as in the photo. Recreate it as a high-end magazine-quality portrait "
    "photograph set in {scene}. Naturally adapt the background, outfit and lighting to "
    "the scene while keeping the person clearly recognizable and the hair identical."
    + _SUMMER_WARDROBE_CLAUSE +
    " The result must look like a real photograph, not an illustration."
)


def resolve_scenes(keys: list[str] | None) -> list[dict]:
    """场景 key → 场景定义；不传取默认前 3 个，未知 key 丢弃并去重。"""
    if not keys:
        return SCENES[:3]
    by_key = {s["key"]: s for s in SCENES}
    return [by_key[k] for k in dict.fromkeys(keys) if k in by_key]


def _color_clause(color: dict | None) -> str:
    if not color:
        return ""
    hex_val = color.get("hex") or ""
    description = (color.get("description") or "").strip()
    template = _COLOR_TEXT_CLAUSE
    return template.format(
        name=color.get("name_en") or color.get("name") or "",
        code=color.get("code") or "",
        hex_part=f", hex {hex_val}" if hex_val else "",
        description=f"Color description: {description}. " if description else "",
    )


def start_composites(
    session_id: int, wig_ids: list[int],
    hair_color: dict | None = None, scene: dict | None = None, db=None,
) -> None:
    """tryon 模式：每款一条 result，发色/场景快照随 result 落库并注入 prompt。

    发色选定时，按 wig 解析「该发型该发色」的组合三角度图组（ark_expo_wig_colors），
    把路径写进各 result 的 hair_color_json.ref_photos——合成时直接拿这组图当参考、
    连颜色一起照搬，不再文字上色（2026-07-15）。无组合图的 wig 走文字上色兜底。
    """
    scene_snapshot = {"key": scene["key"], "label": scene["label"]} if scene else None
    color_id = (hair_color or {}).get("hair_color_id")
    combo_photos = _resolve_combo_photos(wig_ids, color_id, db) if color_id else {}
    rows = []
    for wig_id in wig_ids:
        snap = hair_color
        if hair_color and combo_photos.get(wig_id):
            snap = {**hair_color, "ref_photos": combo_photos[wig_id]}
        rows.append(ExpoResult(
            session_id=session_id, wig_id=wig_id,
            hair_color_json=snap, scene_json=scene_snapshot,
            status="generating",
        ))
    _start_batch(session_id, rows)


def _resolve_combo_photos(wig_ids: list[int], color_id: int, db=None) -> dict[int, list[str]]:
    """{wig_id: 组合三角度图路径} — 只取启用且有图的组合。

    db 由请求线程传入时直接复用（省一次连接、且测试可见事务内数据）；
    未传时自建短连接（防御性，正常调用链都带 db）。"""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        combos = (
            db.query(ExpoWigColor)
            .filter(
                ExpoWigColor.hair_color_id == color_id,
                ExpoWigColor.wig_id.in_(wig_ids),
                ExpoWigColor.is_active == 1,
            )
            .all()
        )
        return {c.wig_id: list(c.angle_photos) for c in combos if c.angle_photos}
    finally:
        if own:
            db.close()


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
    有发型=tryon 换发（竖版 6 寸），scene_json 是生成场景（弱网未选=原景保持原背景，
    否则置换到 TRYON_SCENES 中选定的职业/生活场景）。
    """
    if row.wig_id is None and row.scene_json:
        scene = next((s for s in SCENES if s["key"] == row.scene_json.get("key")), None)
        prompt = (
            _SCENE_TEMPLATE.format(scene=scene["prompt"] if scene else row.scene_json.get("label", ""))
            # banquet 旗袍属场景规定装（uniform），只注首饰；其余 4 景注入完整 look
            + _wardrobe_variation_clause(uniform=bool(scene and scene.get("uniform")))
        )
        return prompt, [to_abs(session.photo_path)], None

    # 发色优先用「该发型该发色」的组合三角度实拍图（参考图即目标色）；文件在才算数。
    # 缺组合 / 文件丢失 → 回退发型自身多角度图 + 文字上色（原色时文字为空），不留空参考
    color = row.hair_color_json or {}
    combo_refs = [to_abs(p) for p in (color.get("ref_photos") or [])[:3] if to_abs(p).exists()]
    if combo_refs:
        refs = combo_refs
        color_clause = _COLOR_FROM_REFERENCE_CLAUSE  # 连颜色一起照搬，无 recolor
    else:
        refs = [to_abs(p) for p in (wig.angle_photos or [])[:3] if to_abs(p).exists()]
        if not refs and wig.cover_path and to_abs(wig.cover_path).exists():
            refs = [to_abs(wig.cover_path)]
        color_clause = _color_clause(row.hair_color_json)  # 文字上色兜底（原色为空）
    # 随图只送 自拍 + 发型参考图（组合图或原色图），不送色板图（会把合成拽偏）
    images = [to_abs(session.photo_path), *refs]

    tryon_scene = resolve_tryon_scene((row.scene_json or {}).get("key"))
    scene_clause = (
        _TRYON_SCENE_CLAUSE.format(scene=tryon_scene["prompt"])
        + _wardrobe_variation_clause(uniform=bool(tryon_scene.get("uniform")))
        if tryon_scene
        else _TRYON_KEEP_BG_CLAUSE  # 原景保持：服装整体锁定，不注入变奏
    )
    prompt = (
        _COMPOSITE_TEMPLATE.format(
            description=wig.wig_description or wig.name,
            extra=wig.composite_prompt or "",
        )
        + color_clause
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
        make_display_image(image_path)  # kiosk 展示版，失败不阻断（回退原图）

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
