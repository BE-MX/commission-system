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
import os
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
# 单个有效令牌在 10 分钟窗口内可反复上传（TTL 内可重放，见模块文档），而二维码
# 贴在共享展位屏上——"有人拿着有效令牌"对每一个路过的人都成立，这是设计上的
# 常态而非攻击。latest_pending 只读最新一张，留着更多纯属浪费磁盘；不裁剪的话，
# 一个善意的客户端重试循环、或恶意脚本，都能在 10 分钟窗口内把云端展会实例
# （方舟全量部署）的磁盘写满，殃及其余 22 个模块。只留最新 K 张把**稳态**持有量
# 钉死在 K × MAX_UPLOAD_BYTES，不需要额外的限流基建（C1）——注意这只是稳态
# 上界，不是绝对峰值：N 个并发请求各自先落盘一个完整文件、再各自裁剪，瞬时
# 峰值可以到 N × MAX_UPLOAD_BYTES，裁剪追不上并发写入的瞬时峰值（Minor 2）。
PENDING_KEEP_PER_CUSTOMER = 3
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# 这个上限不是实际生效的天花板：生产 nginx（ark-ip-ssl.conf / ark-cloud.conf）
# client_max_body_size 都是 5m，比这里小得多——超过 ~5MB 的请求在到达这段 Python
# 之前就被 nginx 挡下、直接 413，本模块的报错文案根本没有机会触发。下次从这里
# 查半天查不出问题时，先去看 nginx 配置，不要以为 15MB 是真的能传到这么大
# （手机端已在 router.py 的 _upload_html 里落盘前先压到 1600px，正常情况下
# 传上来的文件远小于这两个上限）。

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


def _parse_token_parts(token: str | None) -> tuple[int, int, str]:
    """校验令牌，返回规范化的 (customer_id, exp, 签名) 三元组；非法或过期抛
    ValueError（文案直接面向客户）。parse_token / canonical_token 共用本函数，
    校验逻辑只有一份。

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
    return customer_id, exp, parts[2]


def parse_token(token: str | None) -> int:
    """校验令牌并返回 customer_id；非法或过期抛 ValueError。见 _parse_token_parts。"""
    return _parse_token_parts(token)[0]


def canonical_token(token: str) -> str:
    """校验令牌并返回其规范 ASCII 形式；非法或过期抛 ValueError。

    存在原因：上传页要把 token 拼进 <script> 里的 JS 字符串字面量。而
    `int()` 对输入的宽容——接受前后空白（含裸换行）、"+" 前缀、下划线分组、
    全角数字——意味着一个"签名校验通过"的合法令牌，原始字符串未必是能安全
    塞进单引号 JS 字面量的规范 ASCII：比如客户号前缀一个裸换行，`int()` 照单
    全收（数值不变，签名自然对得上），但原样嵌进 `fetch('.../upload/\n42-...')`
    会提前截断整个 JS 字符串字面量，砸掉整个 <script> 块——页面看起来正常，
    两个按钮却悄无声息地失效。

    重建用的是 _parse_token_parts 解析出的 int 值（str(int) 恒定输出规范
    ASCII 十进制），签名段本身已被 _SIGNATURE_RE 钉死成 16 位小写十六进制、
    天然只含 ASCII——重建结果安全性来自结构本身，不依赖"网关不会转发出格式
    古怪的 token"这种侥幸。
    """
    customer_id, exp, sig = _parse_token_parts(token)
    return f"{customer_id}-{exp}-{sig}"


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


def _write_pending_atomic(target: Path, raw: bytes) -> None:
    """先写临时文件、再 os.replace 原子落位（同 ai_pipeline._save_atomic 的道理；
    这里操作的是裸字节而非 PIL Image，不能直接复用那个函数，故单独实现）。

    写盘中途失败（磁盘满——见 C1、AV 锁库）不这样做的话，会在**最终文件名**上
    留下半截文件：那个文件名会被 latest_pending 的 glob 认作"这个客户最新的
    待取照片"、被 resolve_pending 的三道校验全部放行，kiosk 顾问会看到一张
    损坏图。失败向上抛 OSError，由调用方（save_pending）决定如何转译。

    临时文件命名刻意不是"最终名 + .tmp 后缀"：latest_pending 的 glob 是
    "c{cid}_*"、sweep_stale 的 glob 是 "c*"，若临时文件叫 "c42_xxx.jpg.tmp"
    会同时命中这两个 glob——原子写失败后残留的半截 .tmp 文件会被误当正式
    待取照片提供给 kiosk、也会被 sweep_stale 当普通照片计入清理判断。前缀
    点号（.tmp_）让文件名第一个字符就不是 "c"，结构性地避开这两处 glob，
    不依赖"没人凑巧扫描到它"这种侥幸。
    """
    tmp = target.with_name(f".tmp_{target.name}")
    try:
        tmp.write_bytes(raw)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _mtime(path: Path) -> float:
    """带并发防护的 mtime 读取：文件在 stat() 那一刻被并发删掉（另一个线程的
    _prune_pending / sweep_stale / create_session 收尾 unlink）会抛
    FileNotFoundError——是 OSError 的子类，不是 ValueError。

    这不是理论风险：多个线程同时给同一客户 save_pending 时，各自独立 glob 出
    的候选文件列表会互相重叠，线程 A 正在 unlink 某个"多余"文件的同时，线程 B
    排序时对同一个文件调 stat() 就会撞见它消失了。sweep_stale 自己的文档已经
    为同样的理由把 glob() 也包进了 try/except（"目录列举途中被并发删除"），
    但排序用的两个 key 函数（本函数取代之前的 lambda）当时漏了同一道防线——
    在 2 秒轮询、发码必扫、建会话后必删的真实并发下，被删的文件不是边界情况，
    是每一次请求都可能撞见的常态。实测：120 个线程并发上传同一客户，未加防护
    前 88/120 次调用带着裸 FileNotFoundError 从 save_pending 逃逸。

    返回 -1 让"消失的文件"在排序中稳定垫底——它已经不存在了，被当作"最新"
    没有意义，也不该让这一次查询/清理因此变成 500。
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return -1


def _prune_pending(customer_id: int, keep: int = PENDING_KEEP_PER_CUSTOMER) -> None:
    """只留该客户最新 keep 张待取照片，多余的直接删（C1）。

    latest_pending 只读最新一张，留着旧的纯属浪费磁盘；不裁剪的话，免鉴权端点
    配合展位公开二维码，一个善意的客户端重试循环或恶意脚本都能在 10 分钟令牌
    窗口内无限占盘。裁剪后**稳态**下单个令牌的持有量钉死在 keep 张——注意这
    只是稳态上界，不是绝对峰值：N 个并发请求各自先落盘一个完整文件、再各自
    裁剪，峰值可以短暂到达 N × MAX_UPLOAD_BYTES，裁剪追不上并发写入的瞬时峰值
    （C1 review Minor 2）。删除失败只记日志不抛——这是成功上传后的收尾清理，
    不该把一次已经落盘成功的上传顶成失败响应。
    """
    files = sorted(
        (p for p in PENDING_DIR.glob(f"c{customer_id}_*") if p.is_file()),
        key=_mtime,
        reverse=True,
    )
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError as exc:
            msg = f"[expo] pending prune skipped {stale.name}: {exc}"
            logger.warning(msg)
            print(msg, flush=True)


def purge_pending(customer_id: int) -> None:
    """删除该客户全部待取照片（隐私合规调用点，I3）。

    待取目录（uploads/expo/pending/）是与 photos/、results/ 平级、且同样经
    /uploads 公开挂载可读的第二个照片仓库。service.delete_customer 物理删除
    客户全部数据时，原逻辑只走 customer.sessions 的 photo_path/image_path，
    够不着这里——待取照片本靠 sweep_stale 兜底在 2 小时窗口内清理，不算无限期
    泄露，但"客户已经要求删除"和"最多再等 2 小时才真的删干净"之间的落差，与
    上传页上「可随时联系我们删除」这句承诺不符。就是 _prune_pending(keep=0)。
    """
    _prune_pending(customer_id, keep=0)


# 60MP：手机拍照上传经浏览器 canvas 先压到 1600px 长边才会到这里（router.py
# 的 _upload_html），正常路径的文件远小于这个数；触达这里的都是"浏览器端压缩
# 失败/不支持，原图直传"的兜底路径。60MP comfortably clears 常见旗舰机 48MP
# 主摄（约 8000×6000）留出余量，同时挡住"体积过关但像素炸弹"的攻击：一张
# 9000×9000（81MP）PNG 只有 247KB（远低于生产 nginx 5m 上限），81MP 又在
# Pillow 默认炸弹阈值（约 89.5MP，Image.MAX_IMAGE_PIXELS）之下，probe.verify()
# 会放行，随后 downscale_inplace 因为"看起来没超过 1600px 判定阈值以外的检查"
# 而完整解码——实测：接受，0.28 秒，每次请求约 243MB 像素缓冲区，且是免鉴权
# 端点、跑在挂全部 23 个模块的机器上。
MAX_UPLOAD_PIXELS = 60_000_000


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
            # 像素预算先于 verify()：verify() 只探测"这是不是一张合法图片"，
            # 不管分辨率——一张体积很小但像素巨大的图（长宽都很大、压缩率高）
            # 能在体积上钻进 MAX_UPLOAD_BYTES/nginx 5m 的空子，但解码后的内存
            # 占用只看像素数，不看文件字节数（Minor 1）。
            if probe.width * probe.height > MAX_UPLOAD_PIXELS:
                raise ValueError(
                    f"照片分辨率过高，请压缩后重试（上限约 {MAX_UPLOAD_PIXELS // 1_000_000}MP）"
                )
            probe.verify()          # verify 后对象不可再用，仅作有效性探针
    except ValueError:
        raise
    except Exception:
        raise ValueError("上传的文件不是有效的图片") from None

    suffix = Path(filename or "photo.jpg").suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    target = _pending_dir() / photo_filename(customer_id, suffix)
    try:
        _write_pending_atomic(target, raw)
    except OSError as exc:
        msg = f"[expo] pending photo write failed customer={customer_id}: {exc}"
        logger.warning(msg)
        print(msg, flush=True)
        raise ValueError("照片保存失败，请重试") from None
    # 手机原片动辄 3~5MB，落盘即压：这张图要经隧道回源到展位屏做「佩戴前」对比
    ai_pipeline.downscale_inplace(target)
    _prune_pending(customer_id)
    return target.name


def latest_pending(customer_id: int) -> Path | None:
    """该客户最新的待取照片；没有则 None。客户可能连传多张，取最后一张。

    并发下 max() 拿到的这个文件本身也可能在函数返回后才被别的线程删掉——那是
    调用方（get_pending_photo）自己再 stat() 一次时要处理的窗口，这里只保证
    "排序取最新"这一步不会因为候选文件之一被并发删除就抛出去（见 _mtime）。
    """
    if not PENDING_DIR.exists():
        return None
    files = [p for p in PENDING_DIR.glob(f"c{customer_id}_*") if p.is_file()]
    if not files:
        return None
    return max(files, key=_mtime)


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
    try:
        candidate = (root / name).resolve()
    except ValueError:
        # 空字节（\x00）等会让 Path.resolve() 直接抛 ValueError，报文是英文技术
        # 细节（"stat: embedded null character in path"），不是面向客户的中文——
        # 这里统一收敛成与其他"名字不合法"场景一致的提示（Minor 3）。这个入口
        # 是已鉴权端点（POST /sessions 的 pending_photo 字段），不是免鉴权公开
        # 页面，纯属顺手修，不是安全修复。
        raise ValueError("待取照片名非法") from None
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
