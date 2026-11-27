"""Turn a submitted account (URL, handle, phone, email) into one comparable key.

The same normalisation runs on the caller's input and on every stored
``customer_contact_socials.value`` candidate, so ``https://www.instagram.com/Foo/?hl=en``,
``instagram.com/foo`` and ``@foo`` all become ``foo``. Stored data (2026-11-27 profile of
29k rows) is mostly full URLs with assorted hosts, query strings and trailing slashes,
plus bare handles and phone numbers in many punctuation styles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

EMAIL = "email"

# family -> stored ``platform`` values searched for that family
PLATFORM_STORED = {
    "instagram": ("instagram",),
    "facebook": ("facebook", "messenger"),
    "whatsapp": ("whatsapp",),
    "wechat": ("wechat",),
    "linkedin": ("linkedin",),
    "pinterest": ("pinterest",),
    "tiktok": ("tiktok",),
    "x": ("x", "twitter"),
    "yelp": ("yelp",),
    "youtube": ("youtube",),
}

PLATFORM_LABELS = {
    "instagram": "Instagram", "facebook": "Facebook", "whatsapp": "WhatsApp",
    "wechat": "微信", "linkedin": "LinkedIn", "pinterest": "Pinterest", "tiktok": "TikTok",
    "x": "X（Twitter）", "yelp": "Yelp", "youtube": "YouTube", EMAIL: "邮箱",
}

_ALIASES = {
    "instagram": "instagram", "ins": "instagram", "ig": "instagram",
    "facebook": "facebook", "fb": "facebook", "messenger": "facebook",
    "whatsapp": "whatsapp", "wa": "whatsapp", "whats app": "whatsapp",
    "wechat": "wechat", "weixin": "wechat", "微信": "wechat",
    "linkedin": "linkedin", "领英": "linkedin",
    "pinterest": "pinterest",
    "tiktok": "tiktok", "tik tok": "tiktok",
    "x": "x", "twitter": "x",
    "yelp": "yelp",
    "youtube": "youtube", "yt": "youtube",
    "email": "email", "e-mail": "email", "mail": "email", "邮箱": "email",
}

_EMAIL_RE = re.compile(r"^[^@\s/:]+@[^@\s/:]+\.[^@\s/:]+$")
_PHONE_RE = re.compile(r"^\+?[\d\s().\-]{6,}$")
_NUMBERISH_RE = re.compile(r"^\+?[\d\s().\-]+$")
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.I)
# Country sites only: pinterest.com, uk.pinterest.com, pinterest.com.au, pinterest.co.uk, pinterest.de …
_PINTEREST_HOST = re.compile(r"(^|\.)pinterest\.(com|[a-z]{2}|com\.[a-z]{2}|co\.[a-z]{2})$")
_YELP_HOST = re.compile(r"(^|\.)yelp\.(com|[a-z]{2}|com\.[a-z]{2}|co\.[a-z]{2})$")
_MIN_NEEDLE = 3


class DedupInputError(ValueError):
    """The submitted account cannot be classified; message is shown to the caller."""


@dataclass(frozen=True)
class Lookup:
    platform: str  # family key, or "email"
    key: str  # primary normalised key (audited and returned)
    needle: str  # lowercase substring every matching stored value must contain
    keys: tuple[str, ...] = ()  # all keys a stored value may equal (bare handles are ambiguous)
    phone_intl: bool = False  # phone input written with "+"/"00" or as a wa.me/send link

    @property
    def match_keys(self) -> tuple[str, ...]:
        return self.keys or (self.key,)

    @property
    def is_phone(self) -> bool:
        return self.key.startswith("tel:")


def canonical_platform(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    family = _ALIASES.get(str(value).strip().lower())
    if family is None:
        supported = "、".join(PLATFORM_LABELS[k] for k in (*PLATFORM_STORED, EMAIL))
        raise DedupInputError(f"不支持的平台「{value}」，可选：{supported}")
    return family


def _host_family(host: str) -> str | None:
    host = host.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]

    def is_(domain: str) -> bool:
        return host == domain or host.endswith("." + domain)

    if is_("instagram.com") or is_("instagr.am"):
        return "instagram"
    if is_("facebook.com") or is_("fb.com") or is_("fb.me") or host == "m.me":
        return "facebook"
    if is_("wa.me") or is_("whatsapp.com"):
        return "whatsapp"
    if is_("tiktok.com"):
        return "tiktok"
    if is_("twitter.com") or is_("x.com"):
        return "x"
    if is_("linkedin.com"):
        return "linkedin"
    if _PINTEREST_HOST.search(host) or host == "pin.it":
        return "pinterest"
    if is_("youtube.com") or host == "youtu.be":
        return "youtube"
    if _YELP_HOST.search(host):
        return "yelp"
    if is_("weixin.qq.com") or is_("wechat.com"):
        return "wechat"
    return None


def _as_url(raw: str):
    """Parse ``raw`` as a URL when it has a scheme or starts with a known social host."""
    if _SCHEME_RE.match(raw):
        return urlsplit(raw)
    head = raw.split("/", 1)[0]
    if "." in head and "@" not in head and _host_family(head):
        return urlsplit("https://" + raw)
    return None


def _digits(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return digits[2:] if digits.startswith("00") else digits


def _segments(path: str) -> list[str]:
    return [unquote(s) for s in path.split("/") if s]


def _handle(value: str) -> str:
    return value.strip().lstrip("@").strip().rstrip("/").lower()


def _fallback(url) -> str:
    """Key for a link we do not understand: host without www + path, lowercase."""
    host = url.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    path = "/".join(_segments(url.path)).lower()
    return f"url:{host}/{path}" if path else f"url:{host}"


def _first_query(url, name: str) -> str:
    values = parse_qs(url.query).get(name) or [""]
    return values[0].strip()


def _key_instagram(url) -> str:
    segs = _segments(url.path)
    if not segs:
        return _fallback(url)
    head = segs[0].lower()
    if head in {"p", "reel", "reels", "tv"} and len(segs) > 1:
        return f"post:{segs[1]}"
    if head == "stories" and len(segs) > 1:
        return _handle(segs[1])
    if head in {"explore", "accounts", "direct"}:
        return _fallback(url)
    return _handle(segs[0])


def _key_facebook(url) -> str:
    host = url.netloc.lower()
    segs = _segments(url.path)
    if host == "m.me" or host.endswith(".m.me"):
        return _handle(segs[0]) if segs else _fallback(url)
    profile_id = _first_query(url, "id")
    if segs and segs[0].lower() in {"profile.php", "permalink.php", "story.php"} and profile_id.isdigit():
        return f"id:{profile_id}"
    if not segs:
        return _fallback(url)
    head = segs[0].lower()
    if head in {"people", "pages", "pg"} and len(segs) > 1:
        numeric = next((s for s in reversed(segs[1:]) if s.isdigit()), None)
        if numeric:
            return f"id:{numeric}"
        return _handle(segs[1])
    if head == "p" and len(segs) > 1:
        tail = re.search(r"(\d{8,})$", segs[1])
        return f"id:{tail.group(1)}" if tail else _handle(segs[1])
    if head == "groups" and len(segs) > 1:
        return f"group:{segs[1].lower()}"
    if head == "share" and len(segs) > 1:
        return f"share:{segs[-1]}"
    if head.isdigit():
        return f"id:{head}"
    return _handle(segs[0])


def _key_whatsapp(url) -> str:
    segs = _segments(url.path)
    phone = _first_query(url, "phone")
    if phone:
        return f"tel:{_digits(phone)}"
    if segs and segs[0].lower() == "message" and len(segs) > 1:
        return f"wamsg:{segs[1]}"
    if segs and _digits(segs[0]) and _PHONE_RE.match(segs[0]):
        return f"tel:{_digits(segs[0])}"
    if segs and url.netloc.lower().startswith("chat."):
        return f"wagroup:{segs[0]}"
    return _fallback(url)


def _key_tiktok(url) -> str:
    segs = _segments(url.path)
    if not segs:
        return _fallback(url)
    if url.netloc.lower().startswith(("vm.", "vt.")):
        return f"short:{segs[0]}"
    at = next((s for s in segs if s.startswith("@")), None)
    if at:
        return _handle(at)
    if segs[0].lower() in {"video", "t", "discover", "tag", "music"}:
        return _fallback(url)
    return _handle(segs[0])


def _key_x(url) -> str:
    segs = _segments(url.path)
    if not segs or segs[0].lower() in {"intent", "share", "i", "home", "search", "hashtag", "explore"}:
        return _fallback(url)
    return _handle(segs[0])


def _key_linkedin(url) -> str:
    segs = _segments(url.path)
    if len(segs) >= 2 and segs[0].lower() in {"in", "company", "school", "showcase"}:
        return f"{segs[0].lower()}:{segs[1].lower()}"
    if len(segs) >= 2 and segs[0].lower() == "pub":
        return "pub:" + "/".join(segs[1:]).lower()
    return _fallback(url)


def _key_pinterest(url) -> str:
    segs = _segments(url.path)
    if not segs or segs[0].lower() in {"pin", "search", "ideas"}:
        return _fallback(url)
    if url.netloc.lower() == "pin.it":
        return f"short:{segs[0]}"
    return _handle(segs[0])


def _key_youtube(url) -> str:
    segs = _segments(url.path)
    if url.netloc.lower() == "youtu.be" or not segs:
        return _fallback(url)
    head = segs[0]
    lowered = head.lower()
    if head.startswith("@"):
        return "@" + _handle(head)
    if lowered == "channel" and len(segs) > 1:
        return f"channel:{segs[1]}"
    if lowered == "user" and len(segs) > 1:
        return f"user:{segs[1].lower()}"
    if lowered == "c" and len(segs) > 1:
        return f"c:{segs[1].lower()}"
    if lowered in {"watch", "shorts", "playlist", "results", "embed"}:
        return _fallback(url)
    return f"c:{lowered}"


def _key_yelp(url) -> str:
    segs = _segments(url.path)
    if len(segs) >= 2 and segs[0].lower() == "biz":
        return f"biz:{segs[1].lower()}"
    return _fallback(url)


def _key_wechat(url) -> str:
    return _fallback(url)


_URL_KEYS = {
    "instagram": _key_instagram, "facebook": _key_facebook, "whatsapp": _key_whatsapp,
    "tiktok": _key_tiktok, "x": _key_x, "linkedin": _key_linkedin,
    "pinterest": _key_pinterest, "youtube": _key_youtube, "yelp": _key_yelp,
    "wechat": _key_wechat,
}


def _bare_key(family: str, raw: str) -> str:
    """Key for a value that is not a link (handle, phone number, WeChat ID)."""
    if family == "whatsapp":
        digits = _digits(raw)
        return f"tel:{digits}" if digits and _NUMBERISH_RE.match(raw) else _handle(raw)
    if family == "wechat":
        if _PHONE_RE.match(raw) and len(_digits(raw)) >= 7:
            return f"tel:{_digits(raw)}"
        return raw.strip().lower()
    if family == "youtube":
        handle = _handle(raw)
        return "@" + handle if raw.strip().startswith("@") else f"c:{handle}"
    if family == "yelp":
        return f"biz:{_handle(raw)}"
    if family == "linkedin":
        return f"in:{_handle(raw)}"
    if family == "facebook" and _handle(raw).isdigit():
        return f"id:{_handle(raw)}"
    return _handle(raw)


def key_for(family: str, raw: str) -> str:
    """Normalise a value already known to belong to ``family`` (input or stored)."""
    value = (raw or "").replace(" ", " ").strip()
    if not value:
        return ""
    url = _as_url(value)
    if url is not None and url.netloc:
        if _host_family(url.netloc) == family:
            return _URL_KEYS[family](url)
        return _fallback(url)
    return _bare_key(family, value)


def _needle(key: str) -> str:
    """Substring every stored value with this key must contain (lowercase)."""
    if key.startswith("tel:"):
        return key[4:]
    body = key[4:] if key.startswith("url:") else (key.split(":", 1)[1] if ":" in key else key)
    # Stored values may be percent-encoded ("The%20Golden%20Hair"), so filter on the
    # longest plain run only; the exact comparison happens on the normalised key.
    runs = re.findall(r"[a-z0-9_.\-]+", body.lower())
    return max(runs, key=len) if runs else body.lower()


def build_lookup(account: str, platform: str | None = None) -> Lookup:
    raw = (account or "").replace(" ", " ").strip()
    if raw.lower().startswith("mailto:"):
        raw = raw[7:].split("?", 1)[0].strip()
    if not raw:
        raise DedupInputError("请提供要查重的账号或邮箱")
    if len(raw) > 500:
        raise DedupInputError("账号过长，请只提交账号或主页链接")
    family = canonical_platform(platform)

    if family == EMAIL or (family is None and _EMAIL_RE.match(raw)):
        email = raw.lower()
        if not _EMAIL_RE.match(email):
            raise DedupInputError("邮箱格式不正确")
        return Lookup(EMAIL, email, email)

    url = _as_url(raw)
    if url is not None and url.netloc:
        detected = _host_family(url.netloc)
        if family is None:
            if detected is None:
                raise DedupInputError("无法从链接识别平台，请同时提供 platform 参数")
            family = detected
        elif detected is not None and detected != family:
            raise DedupInputError(
                f"链接属于 {PLATFORM_LABELS[detected]}，与指定的平台 {PLATFORM_LABELS[family]} 不一致"
            )
    elif family is None:
        if _PHONE_RE.match(raw) and len(_digits(raw)) >= 7:
            family = "whatsapp"
        else:
            raise DedupInputError("无法判断账号所属平台，请同时提供 platform 参数（如 instagram、tiktok）")

    key = key_for(family, raw)
    if key.startswith("url:"):
        raise DedupInputError("这个链接不是个人或公司主页，请提交主页链接或账号名")
    if key.startswith("tel:") and len(key) - 4 < 7:
        raise DedupInputError("电话号码位数太少，请提交完整号码（含国家区号）")
    needle = _needle(key)
    if len(needle) < _MIN_NEEDLE:
        raise DedupInputError("账号太短，无法查重，请提交完整账号或主页链接")
    bare = url is None or not url.netloc
    keys: tuple[str, ...] = ()
    if bare and family == "youtube":
        # @handle and custom /c/ names share a namespace; legacy /user/ names do not.
        handle = key.split(":", 1)[-1].lstrip("@")
        keys = (key, *(k for k in (f"@{handle}", f"c:{handle}") if k != key))
    elif bare and family == "linkedin":
        handle = key.split(":", 1)[-1]
        kinds = ("in", "company", "school", "showcase")
        first, _, rest = handle.partition("/")
        if first in kinds and rest:  # "in/jane-doe" typed without the host
            key, keys = f"{first}:{rest.strip('/')}", ()
            needle = _needle(key)
        else:
            keys = tuple(f"{kind}:{handle}" for kind in kinds)
    phone_intl = key.startswith("tel:") and (
        raw.lstrip().startswith(("+", "00")) or (url is not None and bool(url.netloc))
    )
    return Lookup(family, key, needle, keys, phone_intl)


def _is_national_form(short: str, full: str) -> bool:
    """``short`` = ``full`` minus a 1–3 digit country code, optionally with one trunk ``0``
    (UK ``07911…`` ≙ ``447911…``); the national part keeps at least 9 digits."""
    national = short[1:] if short.startswith("0") else short
    if len(national) < 9 or not full.endswith(national):
        return False
    return 1 <= len(full) - len(national) <= 3


def phones_match(query: str, stored: str, *, query_is_international: bool = False) -> bool:
    """Same digits, or one side is the national form of the other.

    When the caller wrote the country code ("+"/"00"/wa.me link), only a stored number
    lacking a country code may match by suffix, so ``+1 202…`` never matches a longer
    ``+44 1202…``. Without a country code the input itself is ambiguous across countries.
    """
    if query == stored:
        return True
    if query_is_international:
        return len(stored) < len(query) and _is_national_form(stored, query)
    short, full = sorted((query, stored), key=len)
    return _is_national_form(short, full)
