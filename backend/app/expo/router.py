"""FastAPI router for the expo AI wig try-on module (/api/expo)."""

import html
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.core.response import ok, page_result
from app.expo import ai_pipeline, script_service, service, upload_service
from app.expo.models import ExpoCustomer, ExpoResult, ExpoScript, ExpoWig
from app.expo.schemas import (
    CustomerRegister,
    FeedbackCreate,
    GenerateRequest,
    HairColorUpsert,
    ReactionRequest,
    ScriptUpsert,
    WigColorImagesUpsert,
    WigUpsert,
)

logger = logging.getLogger("commission.expo")

router = APIRouter()

WIG_PHOTO_DIR = ai_pipeline.UPLOAD_ROOT / "wigs"
SWATCH_DIR = ai_pipeline.UPLOAD_ROOT / "hair_colors"


def _user_id(current_user) -> int | None:
    if isinstance(current_user, dict):
        return current_user.get("id")
    return getattr(current_user, "id", None)


# ---------------- 试戴主流程（展位设备，expo:write） ----------------

@router.post("/register", summary="客户注册（consent 必须为 true）")
def register(
    body: CustomerRegister,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    if not body.consent:
        raise HTTPException(400, "需同意拍照存储方可体验")
    customer = service.register_customer(db, body)
    return ok({"customer_id": customer.id}, code=201)


@router.put("/customers/{customer_id}", summary="更新客户登记信息（kiosk 返回上一步修改，不重复建档）")
def update_customer(
    customer_id: int,
    body: CustomerRegister,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    if not body.consent:
        raise HTTPException(400, "需同意拍照存储方可体验")
    customer = service.update_customer(db, customer_id, body)
    if not customer:
        raise HTTPException(404, "客户不存在")
    return ok({"customer_id": customer.id})


@router.post("/sessions", summary="建会话（tryon=异步分析+匹配 / scene=直接就绪；照片来源：现场拍照 photo / 扫码上传 pending_photo 二选一）")
def create_session(
    customer_id: int = Query(...),
    mode: str = Query("tryon", pattern="^(tryon|scene)$"),
    photo: UploadFile | None = File(None),
    pending_photo: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("expo:write")),
):
    # 空串归一为 None：multipart 表单里「字段在但值为空」很常见（前端条件 append 漏判、
    # 客户端库补空字段），而 `"" is not None` 会骗过 service 的二选一守卫
    pending_photo = (pending_photo or "").strip() or None
    try:
        session = service.create_session(
            db, customer_id, photo, _user_id(current_user),
            mode=mode, pending_name=pending_photo,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    upload_service.sweep_stale()   # 确认路径上的第二次机会式清理
    if mode == "tryon":
        ai_pipeline.start_analysis(session.id)
    return ok({"session_id": session.id}, code=201)


@router.get("/sessions/{session_id}", summary="轮询会话（status+分析+匹配+效果图）")
def get_session(
    session_id: int,
    internal: int = Query(0, ge=0, le=1, description="1=含内部发况与话术（销售面板用）"),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    session = service.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    return ok(service.serialize_session(db, session, include_internal=bool(internal)))


@router.post("/sessions/{session_id}/generate", summary="触发效果图合成（tryon 换发/发色 · scene 场景大片）")
def generate(
    session_id: int,
    body: GenerateRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    session = service.get_session(db, session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    if session.status == "generating":
        raise HTTPException(400, "效果图正在生成中，请稍候")

    if session.mode == "scene":
        scenes = ai_pipeline.resolve_scenes(body.scene_keys)
        if not scenes:
            raise HTTPException(400, "场景选择无效")
        ai_pipeline.start_scene_composites(
            session_id, scenes, quality=body.quality, prompt_variant=body.prompt_variant,
        )
        return ok({"scene_keys": [s["key"] for s in scenes],
                   "prompt_variant": body.prompt_variant})

    if session.status == "pending":
        raise HTTPException(400, "面容分析尚未完成")
    hair_color = None
    if body.hair_color_id:
        try:
            hair_color = service.snapshot_hair_color(db, body.hair_color_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    tryon_scene = None
    if body.scene_key:
        tryon_scene = ai_pipeline.resolve_tryon_scene(body.scene_key)
        if not tryon_scene:
            raise HTTPException(400, "生成场景无效")
    wig_ids = body.wig_ids or service.pick_batch_wig_ids(session, body.batch)
    if not wig_ids:
        raise HTTPException(400, "没有可生成的匹配发型（检查发型库与匹配标签）")
    if body.wig_ids:
        found = {w.id for w in db.query(ExpoWig).filter(ExpoWig.id.in_(wig_ids)).all()}
        missing = [i for i in wig_ids if i not in found]
        if missing:
            raise HTTPException(400, f"发型不存在: {missing}")
    ai_pipeline.start_composites(
        session_id, wig_ids, hair_color=hair_color, scene=tryon_scene, db=db,
        quality=body.quality, prompt_variant=body.prompt_variant,
    )
    return ok({"wig_ids": wig_ids, "prompt_variant": body.prompt_variant})


@router.get("/hair-colors", summary="发色库列表（kiosk 默认只取启用项）")
def list_hair_colors(
    only_active: int = Query(1, ge=0, le=1),
    db: Session = Depends(get_db),
    # expo_hair_color:read=发色库页面码（063 拆分）；保留旧码兼容 kiosk 设备账号
    _user=Depends(require_any_permission("expo_hair_color:read", "expo:read", "expo:write", "expo:admin")),
):
    rows = service.list_hair_colors(db, only_active=bool(only_active))
    return ok([service.serialize_hair_color(r) for r in rows])


@router.get("/scenes", summary="可选场景列表（mode=scene 场景大片 / mode=tryon 试戴生成场景）")
def list_scenes(
    mode: str = Query("scene", pattern="^(scene|tryon)$"),
    # expo_scene:read=场景示意图页面码（063 拆分）；保留旧码兼容 kiosk 设备账号
    _user=Depends(require_any_permission("expo_scene:read", "expo:read", "expo:write", "expo:admin")),
):
    source = ai_pipeline.TRYON_SCENES if mode == "tryon" else ai_pipeline.SCENES
    # tryon 甄选页用滑动图片选择器，附示意图 URL（无图返回 None，前端退化为占位卡）+ 分类
    # （20 景分段展示，前端按 category 分组）；scene 模式仍是文字卡片，不带图/分类
    is_tryon = mode == "tryon"
    return ok([
        {
            "key": s["key"], "label": s["label"], "tagline": s["tagline"],
            "image": ai_pipeline.scene_image_url(s["key"]) if is_tryon else None,
            "category": ai_pipeline.tryon_scene_category(s["key"]) if is_tryon else None,
        }
        for s in source
    ])


@router.post("/scenes/{key}/image", summary="上传/替换场景示意图（存 uploads/expo/scenes/<key>.*）")
def upload_scene_image(
    key: str,
    photo: UploadFile = File(...),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        url = ai_pipeline.save_scene_image(key, photo)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok({"key": key, "url": url}, code=201)


@router.delete("/scenes/{key}/image", summary="删除场景示意图")
def remove_scene_image(
    key: str,
    _user=Depends(require_permission("expo:admin")),
):
    if ai_pipeline.resolve_tryon_scene(key) is None:
        raise HTTPException(404, "场景不存在")
    ai_pipeline.delete_scene_image(key)
    return ok()


@router.post("/results/{result_id}/reaction", summary="客户标记 心动/再看看")
def set_reaction(
    result_id: int,
    body: ReactionRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    row = service.set_reaction(db, result_id, body.reaction)
    if not row:
        raise HTTPException(404, "效果图不存在")
    return ok()


@router.post("/customers/{customer_id}/feedback", summary="销售反馈录入")
def add_feedback(
    customer_id: int,
    body: FeedbackCreate,
    db: Session = Depends(get_db),
    # 调用方是 kiosk 销售面板（useTryOnFlow.submitSales，展位设备账号持 expo:write）；
    # 线索台侧未来录入走 expo_lead:write——两码并存，收紧 expo_lead 不许砍 expo:write
    current_user=Depends(require_any_permission("expo_lead:write", "expo:write")),
):
    try:
        feedback = service.add_feedback(db, customer_id, body, _user_id(current_user) or 0)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return ok({"feedback_id": feedback.id}, code=201)


# ---------------- 分享落地页（无鉴权，短码即凭证） ----------------

@router.get("/share/{short_code}", summary="效果图分享落地页", response_class=HTMLResponse)
def share_page(short_code: str, db: Session = Depends(get_db)):
    row = (
        db.query(ExpoResult)
        .filter(ExpoResult.short_code == short_code, ExpoResult.status == "done")
        .first()
    )
    if not row:
        raise HTTPException(404, "分享不存在或已删除")
    image_url = service._to_url(row.image_path)
    wig_name = row.wig.name if row.wig else (row.scene_json or {}).get("label") or ""
    return HTMLResponse(f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>莱莎健康假发 · 我的试戴效果</title>
<style>body{{margin:0;background:#0c0a08;color:#f3ead9;font-family:"PingFang SC",sans-serif;
text-align:center;padding:32px 20px}}img{{max-width:100%;border-radius:18px;
border:1px solid rgba(232,196,121,.35)}}h1{{font-size:16px;letter-spacing:.3em;color:#e8c479;font-weight:400}}
p{{color:#8d8371;font-size:13px;line-height:1.9}}.nm{{color:#f7e3b0;font-size:15px;margin-top:14px}}</style>
</head><body><h1>莱 莎 · 健 康 假 发</h1>
<img src="{image_url}" alt="试戴效果"/><div class="nm">{wig_name}</div>
<p>戴上那一刻，状态就回来了<br/>久戴如新 · SGS 安全认证</p></body></html>""")


# ---------------- 扫码上传照片（2026-08-01）----------------
# 两个 upload 端点**刻意免鉴权**：客户手机没有也不应有展位账号，令牌即凭证
#（HMAC 绑定 customer_id + 10 分钟过期，见 upload_service）。这是机器对机器
# 白名单之外的第三类豁免，与 /share/{short_code} 同性质。


@router.post("/kiosk/upload-ticket", summary="签发扫码上传令牌（kiosk 拍摄页）")
def create_upload_ticket(
    customer_id: int = Query(...),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    # 密钥停在仓库默认值 = 任何能读代码的人都能离线伪造令牌，往任意客户名下投图。
    # 免登录端点的授权模型全压在这个密钥上，故此处 fail-closed 拒发，逼着部署时配 .env
    #（照 app/domestic/router.py 对 qr_secret_is_default 的处理；Task 1 代码审查 C1）
    if upload_service.secret_is_default():
        raise HTTPException(503, "扫码上传未配置签名密钥，请联系管理员")
    customer = db.get(ExpoCustomer, customer_id)
    if not customer:
        raise HTTPException(404, "客户不存在")
    # 模块内其余落盘路径（create_session）都在 consent_at 前提一致：现场拍照/扫码
    # 确认二选一都得客户已同意才能落盘。这里在 happy path 下永远为真（register
    # 强制 consent 才建档），但发码是"照片落地磁盘、且经 /uploads 公开 URL 可读"
    # 之前的唯一关卡——不能只靠"调用方应该都是先 register 过的"这个假设撑住
    # 隐私红线，补一道显式校验，与模块其余写路径的口径保持一致（I7）。
    if not customer.consent_at:
        raise HTTPException(400, "客户未同意拍照存储，无法生成上传链接")
    upload_service.sweep_stale()   # 机会式清理：云端展会实例无调度器，只能挂在这条路上
    token = upload_service.make_token(customer_id)
    return ok({
        "token": token,
        "path": f"/api/expo/upload/{token}",
        "expires_in": upload_service.TICKET_TTL_SECONDS,
    })


@router.get("/upload/{token}", summary="手机上传页（免鉴权，令牌即凭证）",
            response_class=HTMLResponse)
def upload_page(token: str):
    try:
        # 用 canonical_token 而不是 parse_token：int() 对输入的宽容（前后空白/
        # 全角数字/下划线分组等）意味着一个签名校验通过的合法 token，原始字符串
        # 未必能安全塞进下面 <script> 里的单引号 JS 字面量（见 canonical_token
        # 文档）。这里把重建出的规范 ASCII 形式传给 _upload_html，而不是原样
        # 转发客户端传来的 token 字符串。
        canonical = upload_service.canonical_token(token)
    except ValueError as exc:
        return HTMLResponse(_upload_html(None, str(exc)))
    return HTMLResponse(_upload_html(canonical, None))


@router.post("/upload/{token}", summary="手机上传照片（免鉴权，令牌即凭证）")
def upload_photo(token: str, photo: UploadFile = File(...)):
    try:
        customer_id = upload_service.parse_token(token)
        # 有界读：只省一次内存物化，不是接收侧的真实上限。Starlette 在进入这个
        # 函数体之前就已经把整个 multipart body（含超大文件分片）落地到
        # SpooledTemporaryFile（spool_max_size=1MB 后转存磁盘，本身无上限），
        # 这一步改不了；read(N+1) 只是不再把已经落地的内容再完整拷贝一份到堆
        # 上。真正兜底接收体积的是生产 nginx 的 client_max_body_size（5m，见
        # upload_service.MAX_UPLOAD_BYTES 旁注释），局域网直连后端
        # （192.168.101.193:8001）完全没有这一层防护。
        raw = photo.file.read(upload_service.MAX_UPLOAD_BYTES + 1)
        upload_service.save_pending(customer_id, raw, photo.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok({"uploaded": True})


@router.get("/kiosk/pending-photo", summary="取该客户最新的扫码待取照片")
def get_pending_photo(
    customer_id: int = Query(...),
    _user=Depends(require_permission("expo:write")),
):
    latest = upload_service.latest_pending(customer_id)
    if not latest:
        return ok({"pending": None})
    try:
        # 两处都读磁盘，都可能在 latest_pending 选出这个文件之后、这里构造响应
        # 之前，被另一个线程的 sweep_stale / _prune_pending / create_session
        # 收尾 unlink 抢先删掉——kiosk 轮询这个端点每 2 秒一次，命中这个窗口
        # 不是理论风险（并发探针实测：4 秒并发上传/清理压力下命中上百次）。
        # 两处报错形态还不一样：latest.stat() 对已消失文件抛 FileNotFoundError
        # （OSError 子类）；ai_pipeline.to_rel() 内部 Path.resolve() 对一个
        # 已经不存在的路径在 Windows 上走不同的规范化分支，会让 relative_to()
        # 抛 ValueError（"不在 REPO_ROOT 子路径下"）——同一个竞态窗口的两种
        # 不同报错，一起兜住，缺一个都会让轮询偶发变成 500。
        photo_url = service._to_url(ai_pipeline.to_rel(latest))
        uploaded_at = int(latest.stat().st_mtime)
    except (OSError, ValueError) as exc:
        # 对顾问来说，文件在这个窗口内消失就是"当前没有待取照片"，不该把这个
        # 巧合变成 500（kiosk 的轮询失败计数会把它误判成"现场网络拥堵"）；
        # 但仍要留痕（宪法 6）——这里打日志不只是合规，真出现异常频率过高
        # 说明并发压力超出预期，运维需要看得到。
        msg = f"[expo] pending photo vanished mid-poll customer={customer_id}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        return ok({"pending": None})
    return ok({"pending": {
        "name": latest.name,
        "photo_url": photo_url,
        "uploaded_at": uploaded_at,
    }})


def _upload_html(canonical_token: str | None, error: str | None) -> str:
    """手机扫码上传页：黑金视觉语言与 share_page 一致（同一套客户拍照体验）。

    error 非空时渲染纯说明页（令牌非法/过期），绝不用裸 404 打发客户；
    本页不回显任何客户姓名——二维码由共享屏（kiosk）签发，屏上任何人都能扫，
    在这张陌生人可达的页面上显名是隐私泄露（产品明确决策）。

    canonical_token 必须是 upload_service.canonical_token() 的输出（调用方
    upload_page 已经这么做），不是客户端传来的原始 token 字符串——见该函数
    文档，原始字符串可能带 int() 能容忍但 JS 单引号字面量容不下的内容（裸
    换行等）。error 与 canonical_token 两处都过 html.escape：error 目前只是
    模块内两条固定中文文案，但这层转义不依赖"以后没人会往 ValueError 里塞
    动态内容"这种约定——某天有人写出 `f"上传码 {token} 已过期"` 这种看似无害
    的改动，没有这层转义就是这张免鉴权公开页上的反射型 XSS。
    """
    if error:
        safe_error = html.escape(error)
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>莱莎健康假发 · 上传链接已失效</title>
<style>body{{margin:0;background:#0c0a08;color:#f3ead9;font-family:"PingFang SC",sans-serif;
text-align:center;padding:64px 24px}}h1{{font-size:16px;letter-spacing:.3em;color:#e8c479;
font-weight:400;margin-bottom:26px}}p{{color:#8d8371;font-size:14px;line-height:2}}</style>
</head><body><h1>莱 莎 · 健 康 假 发</h1><p>{safe_error}</p></body></html>"""

    upload_path = html.escape(f"/api/expo/upload/{canonical_token}")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>莱莎健康假发 · 扫码上传照片</title>
<style>
body{{margin:0;background:#0c0a08;color:#f3ead9;font-family:"PingFang SC",sans-serif;
padding:28px 20px 48px;box-sizing:border-box}}
h1{{font-size:15px;letter-spacing:.3em;color:#e8c479;font-weight:400;text-align:center;margin:0 0 26px}}
.lead{{text-align:center;font-size:14px;color:#f7e3b0;margin-bottom:22px}}
.row{{display:flex;gap:12px;margin-bottom:16px}}
.pick{{flex:1;position:relative;border:1px solid rgba(232,196,121,.4);border-radius:14px;
padding:20px 8px;text-align:center;color:#f3ead9;font-size:14px;overflow:hidden}}
.pick input{{position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer}}
#status{{text-align:center;font-size:13px;color:#e8c479;min-height:20px;margin-bottom:22px}}
.tips{{background:rgba(232,196,121,.06);border:1px solid rgba(232,196,121,.2);border-radius:14px;
padding:16px 18px;margin-bottom:22px}}
.tips p{{margin:0 0 8px;color:#8d8371;font-size:12px}}
.tips ul{{margin:0;padding-left:18px;color:#d9c9a0;font-size:12.5px;line-height:1.9}}
.privacy{{color:#8d8371;font-size:12px;line-height:1.8;text-align:center;margin-bottom:20px}}
</style>
</head><body>
<h1>莱 莎 · 健 康 假 发</h1>
<div class="lead">上传一张照片，回到展位屏幕即可查看试戴效果</div>
<div class="row">
<label class="pick">从相册选择<input type="file" accept="image/*" id="fromAlbum"/></label>
<label class="pick">现在拍一张<input type="file" accept="image/*" capture="user" id="fromCamera"/></label>
</div>
<div id="status"></div>
<div class="tips">
<p>拍摄小贴士</p>
<ul>
<li>略微俯拍（镜头稍高于视线，微微抬头，眼神更明亮）</li>
<li>微侧面容（面部带一点角度，露出约四分之三面容）</li>
<li>构图靠上（头部位于画面上三分之一，露出肩颈与上身）</li>
</ul>
</div>
<div class="privacy">照片仅用于本次体验与效果回看，保留 90 天，可随时联系我们删除。</div>
<script>
var MAX_EDGE = 1600;   // 与后端 ai_pipeline.UPLOAD_MAX_EDGE 对齐
var busy = false;      // 并发提交守卫：处理/上传期间忽略新的选图，成败后才放开

function uploadBlob(blob, filename) {{
  var status = document.getElementById('status');
  status.textContent = '上传中…';
  var fd = new FormData();
  fd.append('photo', blob, filename || 'photo.jpg');
  fetch('{upload_path}', {{ method: 'POST', body: fd }})
    .then(function (res) {{
      return res.json().catch(function () {{ return null; }}).then(function (body) {{
        if (!res.ok) {{
          // 后端 HTTPException 的错误体是 {{"detail": "..."}}——过期码会给出
          // "回展位重新获取"而不是笼统的"无效"，这是 parse_token 特意保留的
          // 区分（先查过期、再查签名）；不读这个字段就等于把这份区分白白扔掉，
          // 客户在 10 分钟窗口快到期时翻完相册回来提交，只会被无意义地告知"重试"。
          throw new Error((body && body.detail) || '上传失败，请重试');
        }}
        status.textContent = '上传成功，请回到展位屏幕查看';
      }});
    }})
    .catch(function (err) {{
      status.textContent = (err && err.message) || '上传失败，请重试';
    }})
    .then(function () {{
      busy = false;   // 不管成败都要放开，允许客户重新选图重试
    }});
}}

// 生产 nginx（ark-ip-ssl.conf）client_max_body_size 5m，手机原图常见 3~8MB——
// 传原图会被 nginx 413 挡在 Python 之前，我们精心写的中文提示永远不会触发。
// 这里在浏览器端先压到 1600px 长边，体积落到几百 KB，5m 门槛基本不会再撞到。
//
// 陷阱：手机相册照片自带 EXIF 方向标记，canvas 只画像素、不认 EXIF——若直接
// drawImage 原图再重新编码，输出没有 EXIF 且像素没转正，人像会整张倒下/侧躺。
// createImageBitmap(file, {{imageOrientation:'from-image'}}) 会先按 EXIF 转正
// 再把像素交给我们画，这样重新编码的 JPEG 天生方向正确，不依赖下游再读 EXIF。
//
// 渐进增强：拿不到 createImageBitmap（老式机型/微信内置浏览器）或它中途抛错，
// 一律回退成「原图直传」——宁可传得慢，也不能传一张可能转向错误的压缩图。
function prepareAndUpload(file) {{
  if (!file) return;
  if (busy) {{
    document.getElementById('status').textContent = '仍在处理上一张，请稍候…';
    return;
  }}
  busy = true;
  // 12MP 原图的 createImageBitmap+canvas 处理耗时 1~3 秒，这期间页面若什么都
  // 不显示，客户会以为没反应而再次点击——先给一句"处理中"垫上，比等 uploadBlob
  // 里的"上传中"早得多。
  document.getElementById('status').textContent = '处理中…';
  if (!window.createImageBitmap) {{
    uploadBlob(file, file.name);
    return;
  }}
  createImageBitmap(file, {{ imageOrientation: 'from-image' }}).then(function (bitmap) {{
    try {{
      var scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
      var w = Math.round(bitmap.width * scale);
      var h = Math.round(bitmap.height * scale);
      var canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      var ctx = canvas.getContext('2d');
      ctx.drawImage(bitmap, 0, 0, w, h);
      canvas.toBlob(function (blob) {{
        if (blob) {{
          uploadBlob(blob, 'photo.jpg');
        }} else {{
          uploadBlob(file, file.name);   // toBlob 失败兜底：传原图，不传半成品
        }}
      }}, 'image/jpeg', 0.9);
    }} catch (e) {{
      uploadBlob(file, file.name);
    }}
  }}).catch(function () {{
    uploadBlob(file, file.name);
  }});
}}

function bind(id) {{
  document.getElementById(id).addEventListener('change', function (e) {{
    var file = e.target.files[0];
    e.target.value = '';
    prepareAndUpload(file);
  }});
}}
bind('fromAlbum');
bind('fromCamera');
</script>
</body></html>"""


# ---------------- kiosk 销售面板（展位设备 expo:write，2026-07-13） ----------------
# 与 /leads（expo_lead:*，线索台全量数据）刻意分离：共享屏最小暴露面，
# 手机号服务端脱敏、话术载荷不含 internal 发况与客户照片

@router.get("/kiosk/leads", summary="kiosk 销售面板线索列表（手机号脱敏，姓名/手机关键词检索）")
def kiosk_leads(
    keyword: str | None = Query(None, max_length=64),
    expo_code: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    items, total = service.list_leads(
        db, page=page, page_size=page_size, expo_code=expo_code, keyword=keyword,
    )
    return ok(page_result([service.serialize_kiosk_lead(r) for r in items], total, page, page_size))


@router.get("/kiosk/leads/{customer_id}/strategy", summary="kiosk 销售面板话术（只出话术与试戴款，无 internal 发况）")
def kiosk_lead_strategy(
    customer_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:write")),
):
    payload = service.get_kiosk_strategy(db, customer_id)
    if payload is None:
        raise HTTPException(404, "客户不存在")
    return ok(payload)


# ---------------- 线索台（PC，expo_lead:*，2026-07-12 从 expo:read 拆出） ----------------

@router.get("/leads", summary="展会线索列表")
def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    expo_code: str | None = Query(None),
    intent_level: str | None = Query(None, pattern="^[ABCD]$"),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_lead:read", "expo_lead:write")),
):
    items, total = service.list_leads(
        db, page=page, page_size=page_size,
        expo_code=expo_code, intent_level=intent_level, keyword=keyword,
    )
    return ok(page_result(items, total, page, page_size))


@router.get("/leads/{customer_id}", summary="线索详情（会话回放，含内部发况）")
def lead_detail(
    customer_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo_lead:read", "expo_lead:write")),
):
    detail = service.get_lead_detail(db, customer_id)
    if not detail:
        raise HTTPException(404, "客户不存在")
    return ok(detail)


@router.delete("/customers/{customer_id}", summary="删除客户数据（照片物理删除，隐私合规）")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    if not service.delete_customer(db, customer_id):
        raise HTTPException(404, "客户不存在")
    return ok()


# ---------------- 发型库（PC，expo:read/admin） ----------------

@router.get("/wigs", summary="发型库列表")
def list_wigs(
    only_active: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo:read", "expo:write", "expo:admin")),
):
    wigs = service.list_wigs(db, only_active=bool(only_active))
    return ok([service.serialize_wig(w) for w in wigs])


@router.get("/wigs/picker", summary="kiosk 从发型库选择：启用发型轻量列表")
def wig_picker(
    db: Session = Depends(get_db),
    _user=Depends(require_any_permission("expo:read", "expo:write", "expo:admin")),
):
    wigs = service.list_wigs(db, only_active=True)
    return ok([service.serialize_wig_picker(w) for w in wigs])


@router.post("/wigs", summary="新建发型")
def create_wig(
    body: WigUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        wig = service.upsert_wig(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(service.serialize_wig(wig), code=201)


@router.put("/wigs/{wig_id}", summary="更新发型")
def update_wig(
    wig_id: int,
    body: WigUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        wig = service.upsert_wig(db, body, wig_id=wig_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return ok(service.serialize_wig(wig))


@router.delete("/wigs/{wig_id}", summary="删除发型（已产生试戴记录则拒删，引导停用）")
def delete_wig(
    wig_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        deleted = service.delete_wig(db, wig_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if not deleted:
        raise HTTPException(404, "发型不存在")
    return ok()


@router.post("/wigs/upload-photo", summary="上传发型参考图，返回相对路径")
def upload_wig_photo(
    photo: UploadFile = File(...),
    _user=Depends(require_permission("expo:admin")),
):
    WIG_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(photo.filename or "wig.jpg").suffix.lower() or ".jpg"
    target = WIG_PHOTO_DIR / f"wig_{uuid.uuid4().hex[:10]}{suffix}"
    with open(target, "wb") as f:
        shutil.copyfileobj(photo.file, f)
    # 手机原片 3~8MB，kiosk 匹配屏一次加载 6 张封面且经 frp 隧道回源——落盘即压
    ai_pipeline.downscale_inplace(target)
    # 列表缩略图：甄选页/发型库只显示 76px 见方，原图 1024×1536 PNG 约 2MB，
    # 每次进屏都要解码 150 万像素。失败不阻断上传，序列化侧回退原图
    ai_pipeline.make_thumb_image(target)
    rel = ai_pipeline.to_rel(target)
    return ok({"path": rel, "url": f"/{rel}"}, code=201)


# ---------------- 发型×发色组合参考图（072；kiosk 过滤 + 管理端矩阵） ----------------

@router.get("/wigs/{wig_id}/colors", summary="kiosk：某发型已备图的发色列表（过滤发色选项）")
def list_wig_colors(
    wig_id: int,
    db: Session = Depends(get_db),
    # kiosk 设备账号持 expo:write；管理端预览走 admin
    _user=Depends(require_any_permission("expo:read", "expo:write", "expo:admin")),
):
    return ok(service.list_wig_color_options(db, wig_id))


@router.get("/wigs/{wig_id}/color-images", summary="管理端：某发型的发色×三角度矩阵")
def list_wig_color_images(
    wig_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        return ok(service.list_wig_color_images(db, wig_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.put("/wigs/{wig_id}/color-images/{color_id}", summary="管理端：新建/替换某组合三角度图")
def upsert_wig_color_images(
    wig_id: int,
    color_id: int,
    body: WigColorImagesUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        row = service.upsert_wig_color_images(db, wig_id, color_id, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok({"wig_id": row.wig_id, "hair_color_id": row.hair_color_id})


@router.delete("/wigs/{wig_id}/color-images/{color_id}", summary="管理端：删除某组合图组")
def delete_wig_color_images(
    wig_id: int,
    color_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    if not service.delete_wig_color_images(db, wig_id, color_id):
        raise HTTPException(404, "该发色组合无参考图")
    return ok()


# ---------------- 发色库（PC，expo:admin 管理；列表复用上方 GET /hair-colors） ----------------

@router.post("/hair-colors", summary="新建发色")
def create_hair_color(
    body: HairColorUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        row = service.upsert_hair_color(db, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(service.serialize_hair_color(row), code=201)


@router.put("/hair-colors/{color_id}", summary="更新发色")
def update_hair_color(
    color_id: int,
    body: HairColorUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    try:
        row = service.upsert_hair_color(db, body, color_id=color_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return ok(service.serialize_hair_color(row))


@router.get("/hair-colors/{color_id}/usage", summary="删发色前查影响面：被多少发型备了图")
def hair_color_usage(
    color_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    return ok({"combo_count": service.count_wig_color_combos_by_color(db, color_id)})


@router.delete("/hair-colors/{color_id}", summary="删除发色（效果图存 JSON 快照，删除不影响历史）")
def delete_hair_color(
    color_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    if not service.delete_hair_color(db, color_id):
        raise HTTPException(404, "发色不存在")
    return ok()


@router.post("/hair-colors/upload-swatch", summary="上传色板图，返回相对路径并自动提取主色 hex")
def upload_hair_color_swatch(
    photo: UploadFile = File(...),
    _user=Depends(require_permission("expo:admin")),
):
    SWATCH_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(photo.filename or "swatch.jpg").suffix.lower() or ".jpg"
    target = SWATCH_DIR / f"swatch_{uuid.uuid4().hex[:10]}{suffix}"
    with open(target, "wb") as f:
        shutil.copyfileobj(photo.file, f)
    # 先压后取色：k-means 主色在 1600px 内足够稳，还能省一次大图解码
    ai_pipeline.downscale_inplace(target)
    # 列表缩略图：甄选页/发型库只显示 76px 见方，原图 1024×1536 PNG 约 2MB，
    # 每次进屏都要解码 150 万像素。失败不阻断上传，序列化侧回退原图
    ai_pipeline.make_thumb_image(target)
    rel = ai_pipeline.to_rel(target)

    # 系统承担复杂性：色板图主色自动提取，管理员免手填 hex；失败不阻断上传。
    # k=4 + pick_swatch_hair_hex 跳过白底背景，取真实发色（直接取最大簇会得到白底）
    hex_code = None
    try:
        from app.color.calc_service import extract_dominant_colors

        dominant = extract_dominant_colors(str(target), k=4)
        hex_code = service.pick_swatch_hair_hex(dominant)
    except Exception as exc:
        msg = f"[expo] swatch dominant color extract failed: {exc}"
        logger.warning(msg)
        print(msg, flush=True)

    return ok({"path": rel, "url": f"/{rel}", "hex": hex_code}, code=201)


# ---------------- 话术卡库（PC，expo:read/admin） ----------------

@router.get("/scripts", summary="话术卡列表")
def list_scripts(
    script_type: str | None = Query(None),
    db: Session = Depends(get_db),
    # expo_script:read=话术卡库页面码（063 拆分）；保留旧码兼容线索台/历史调用
    _user=Depends(require_any_permission("expo_script:read", "expo:read", "expo:write", "expo:admin")),
):
    scripts = script_service.list_scripts(db, script_type=script_type, only_active=False)
    return ok([
        {
            "id": s.id,
            "script_type": s.script_type,
            "track": s.track,
            "title": s.title,
            "audience_tags": s.audience_tags or [],
            "content": s.content,
            "evidence_points": s.evidence_points or [],
            "source_version": s.source_version,
            "is_active": s.is_active,
        }
        for s in scripts
    ])


@router.post("/scripts", summary="新建话术卡（含禁用词校验）")
def create_script(
    body: ScriptUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    hit = script_service.check_forbidden(body.content)
    if hit:
        raise HTTPException(400, f"内容包含品牌禁用词：{hit}")
    script = ExpoScript(**body.model_dump())
    db.add(script)
    db.commit()
    db.refresh(script)
    return ok({"id": script.id}, code=201)


@router.put("/scripts/{script_id}", summary="更新话术卡（含禁用词校验）")
def update_script(
    script_id: int,
    body: ScriptUpsert,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    script = db.get(ExpoScript, script_id)
    if not script:
        raise HTTPException(404, "话术卡不存在")
    hit = script_service.check_forbidden(body.content)
    if hit:
        raise HTTPException(400, f"内容包含品牌禁用词：{hit}")
    for field, value in body.model_dump().items():
        setattr(script, field, value)
    db.commit()
    return ok()


@router.post("/scripts/seed", summary="导入营销文档种子话术卡（幂等）")
def seed_scripts(
    db: Session = Depends(get_db),
    _user=Depends(require_permission("expo:admin")),
):
    created = script_service.seed_default_scripts(db)
    return ok({"created": created})


# ---------------- 门店/展位配额管理（2026-08-05）----------------

from app.expo.store_router import router as store_router

router.include_router(store_router, prefix="/stores", tags=["展会门店配额"])
