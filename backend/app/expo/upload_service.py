"""展会扫码上传：令牌签发/校验 + 待取照片读写（2026-08-01）。

刻意不落库：令牌的两个职责——绑定到哪个客户、什么时候作废——都能用密码学表达。
若另立 ticket 表，「照片有没有传上来」就有两份真相（表里的 status 与磁盘上的文件），
必须保持同步；本项目已在这类不同步上栽过（素材域 folder_upload 静默失败）。
代价是令牌在有效期内可重复使用，靠 10 分钟短有效期 + kiosk 顾问预览兜住。

本模块不碰数据库，只处理令牌与文件，可脱离 DB 单测。
"""

import hashlib
import hmac
import logging
import re
import time
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.expo import ai_pipeline

logger = logging.getLogger("commission.expo")

TICKET_TTL_SECONDS = 600          # 10 分钟：够客户翻相册，又限制二维码被拍走后的滥用窗口
PENDING_DIR = ai_pipeline.UPLOAD_ROOT / "pending"
STALE_AFTER_SECONDS = 2 * 3600    # 待取照片留存上界
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# 免登录端点统一话术：不区分「格式错」与「签名错」——对客户来说都只有一个可行动作
# （回去重新扫码），暴露更细的原因没有意义，只会多一处需要翻译/维护的文案。
_INVALID_TOKEN_MSG = "上传链接无效，请回到展位屏幕重新扫码"
_SIGNATURE_RE = re.compile(r"[0-9a-f]{16}")


def _sign(customer_id: int, exp: int) -> str:
    secret = get_settings().EXPO_UPLOAD_SIGN_SECRET
    msg = f"{customer_id}:{exp}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]


def secret_is_default() -> bool:
    """密钥还是仓库里的默认字面量 = 任何能读代码的人都能离线伪造上传令牌。

    上传页完全免登录，整个授权模型压在这个密钥上，默认值等于没锁。照 domestic
    的 qr_secret_is_default 办（app/domestic/report_service.py）：由调用方在发码
    端点上拒绝服务，逼着部署时配好 .env——而不是像 ASSET_SIGN_SECRET 那样
    留一句注释，然后一直跑在默认值上。
    """
    from app.core.config import Settings

    return get_settings().EXPO_UPLOAD_SIGN_SECRET == Settings.model_fields[
        "EXPO_UPLOAD_SIGN_SECRET"].default


def make_token(customer_id: int, ttl_seconds: int = TICKET_TTL_SECONDS) -> str:
    """签发上传令牌：{customer_id}-{过期时间戳}-{签名}。"""
    exp = int(time.time()) + ttl_seconds
    return f"{customer_id}-{exp}-{_sign(customer_id, exp)}"


def parse_token(token: str | None) -> int:
    """校验令牌并返回 customer_id；非法或过期抛 ValueError（文案直接面向客户）。

    从右往左只切两刀（customer_id 允许负数，本身可能带 "-"）；签名段先做
    形状校验再进 hmac.compare_digest —— 后者只接受可比较的 ASCII 字节串，
    非法字符（如中文、emoji）传进去会抛 TypeError 而不是 ValueError，在一个
    连鉴权都没有的公开端点上，这种未捕获的类型错误会变成 500。
    """
    parts = (token or "").rsplit("-", 2)
    if len(parts) != 3 or not _SIGNATURE_RE.fullmatch(parts[2]):
        raise ValueError(_INVALID_TOKEN_MSG)
    try:
        customer_id, exp = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(_INVALID_TOKEN_MSG) from None
    # 过期先于签名校验：不是防泄密（exp 是攻击者自己拼的明文，顺序换了也不会
    # 多泄露什么）——是体验取舍。一个确实过期的码，值得「回展位重新获取」这句
    # 能对症下药的提示，不该被更笼统的「链接无效」盖掉。
    if exp < time.time():
        raise ValueError("上传码已过期，请回到展位屏幕重新获取")
    if not hmac.compare_digest(parts[2], _sign(customer_id, exp)):
        raise ValueError(_INVALID_TOKEN_MSG)
    return customer_id


def _pending_dir() -> Path:
    """每次现取而不是模块级缓存：测试用 monkeypatch 换 PENDING_DIR 才能生效。"""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    return PENDING_DIR


def photo_filename(customer_id: int, suffix: str) -> str:
    """待取目录（pending/）与正式目录（photos/）共用的落盘命名规则。

    三处调用点（这里的 save_pending、app/expo/service.py 的 create_session 两个分支）
    曾各写各的，导致同一条规则漂在三个地方——resolve_pending 的路径穿越防线明确
    依赖这条规则在两个目录间保持字面一致（见该函数文档），三份拷贝里漏改一处就是
    悄悄松动安全假设，抽成单一函数让这份依赖可 grep。
    """
    return f"c{customer_id}_{uuid.uuid4().hex[:10]}{suffix}"


def save_pending(customer_id: int, raw: bytes, filename: str | None) -> str:
    """落一张待取照片，返回纯文件名。非图片 / 超限抛 ValueError。

    免鉴权端点，体积与内容双重校验：Content-Type 可以伪造，能不能被 Pillow 解析不能。
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError(f"照片过大，请压缩后重试（上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB）")

    import io

    from PIL import Image

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()          # verify 后对象不可再用，仅作有效性探针
    except Exception:
        raise ValueError("上传的文件不是有效的图片") from None

    suffix = Path(filename or "photo.jpg").suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    target = _pending_dir() / photo_filename(customer_id, suffix)
    target.write_bytes(raw)
    # 手机原片动辄 3~5MB，落盘即压：这张图要经隧道回源到展位屏做「佩戴前」对比
    ai_pipeline.downscale_inplace(target)
    return target.name


def latest_pending(customer_id: int) -> Path | None:
    """该客户最新的待取照片；没有则 None。客户可能连传多张，取最后一张。"""
    if not PENDING_DIR.exists():
        return None
    files = [p for p in PENDING_DIR.glob(f"c{customer_id}_*") if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def resolve_pending(customer_id: int, name: str) -> Path:
    """待取文件名 → 绝对路径，三道校验：路径穿越、归属、存在性。

    纯查找，不建目录：直接 resolve PENDING_DIR 而不经 _pending_dir()，一次读取
    请求没有理由在磁盘上留下副作用（目录不存在时会自然落到"不存在"分支）。

    三道校验里，**只有第一道（路径穿越）是真正的防线**。展会的永久试戴照片
    （app/expo/service.py 的 create_session 落盘时）与待取照片走的是同一个
    photo_filename() 命名函数（本模块），且落在 UPLOAD_ROOT 下的平级目录
    （photos/ 与 pending/）。这意味着 "../photos/c42_<真实uuid>.jpg" 这样的
    payload 能直接通过归属校验（前缀对得上）和存在性校验（文件真实存在）——
    挡住它的只有 candidate.parent != root。归属/存在性校验只对"pending 目录内
    文件名被篡改/文件已被清走"这类良性场景有意义，绝不能指望它们防穿越。
    """
    root = PENDING_DIR.resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise ValueError("待取照片名非法")
    if not candidate.name.startswith(f"c{customer_id}_"):
        raise ValueError("待取照片不属于该客户")
    if not candidate.is_file():
        raise ValueError("待取照片不存在或已被清理")
    return candidate


def sweep_stale(now: float | None = None) -> int:
    """删除超过 STALE_AFTER_SECONDS 的待取照片，返回删除条数。

    **不能挂定时任务**：云端展会实例 SCHEDULER_ENABLED=false（防与办公室实例双跑），
    而那台正是跑展会的机器。改为发码与确认两个路径上机会式触发，残留上界由此有保证。
    绝不抛异常——它挂在发码路径上，抛了就发不出码。

    因此 glob() 本身也纳入 try/except：目录列举途中被并发删除、AV 锁库等都会
    从这里冒出 OSError，若只包住循环体内部、不包住迭代器本身，这类异常会直接
    穿透函数边界，砸掉发码路径。
    """
    # 显式判断只是快路径/自文档，不是安全依赖：当前 pathlib 对不存在目录调用
    # glob() 直接返回空迭代器（已验证），且下面 try 已经把迭代本身纳入保护，
    # 即便未来某个 Python/OS 组合让 glob() 在此抛 FileNotFoundError，也会被
    # 下面的 except OSError 兜住而不传播，不依赖这行提前 return。
    if not PENDING_DIR.exists():
        return 0
    deadline = (now or time.time()) - STALE_AFTER_SECONDS
    removed = 0
    try:
        for path in PENDING_DIR.glob("c*"):
            try:
                if path.is_file() and path.stat().st_mtime < deadline:
                    path.unlink()
                    removed += 1
            except OSError as exc:
                msg = f"[expo] pending sweep skipped {path.name}: {exc}"
                logger.warning(msg)
                print(msg, flush=True)
    except OSError as exc:
        msg = f"[expo] pending sweep listing failed: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
    return removed
