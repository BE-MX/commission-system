"""Client tag hierarchy and extraction-safe ZIP names (no filesystem writes)."""
from itertools import product
from pathlib import PurePosixPath
import re
import unicodedata


LEVEL_NAMES = (
    {"customerproducttype", "producttypecustomer", "producttype", "产品类型"},
    {"texturestype", "texturetype", "纹理类型"},
    {"colornames", "colorname", "颜色名称"},
)
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f-\x9f]')
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
MAX_NAME_BYTES = 180


def _normalize(value):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def tag_folders(tags, dimensions):
    """Same classification as the portal: all matching combinations, missing levels skipped."""
    levels = []
    for aliases in LEVEL_NAMES:
        dimension = next((dim for dim in dimensions if
                          _normalize(dim["name"]) in aliases or _normalize(dim["label"]) in aliases), None)
        values = list(dict.fromkeys(
            unicodedata.normalize("NFC", tag["value"].strip()) for tag in tags
            if dimension and tag["dimension_id"] == dimension["id"] and tag.get("value", "").strip()
        ))
        if values:
            levels.append(values)
    yield from product(*levels)


def _shorten(value, limit):
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def _safe_name(value):
    value = unicodedata.normalize("NFC", str(value or ""))
    value = _INVALID.sub("_", value).strip().rstrip(".")
    if not value or value in {".", ".."}:
        value = "unnamed"
    if _RESERVED.match(value):
        value = "_" + value
    return value


class ArchiveNames:
    """Reserve directories and files together; also avoid case-insensitive extraction clashes."""

    def __init__(self):
        self.used = set()
        self.directories = {}

    def _reserve(self, parent, name, *, file=False):
        safe = _safe_name(name)
        suffix = PurePosixPath(safe).suffix if file else ""
        # A pathological suffix is not allowed to consume the entire filename budget.
        if len(suffix.encode("utf-8")) > 32:
            suffix = ""
        stem = safe[:-len(suffix)] if suffix else safe
        counter = 1
        while True:
            marker = "" if counter == 1 else f" ({counter})"
            name = _shorten(stem, MAX_NAME_BYTES - len((marker + suffix).encode("utf-8"))).rstrip(". ") + marker + suffix
            path = "/".join((*parent, name))
            key = path.casefold()
            if key not in self.used:
                self.used.add(key)
                return name
            counter += 1

    def file(self, folders, filename):
        parent = ()
        logical = ()
        for folder in folders:
            logical += (folder,)
            if logical not in self.directories:
                self.directories[logical] = (*parent, self._reserve(parent, folder))
            parent = self.directories[logical]
        return "/".join((*parent, self._reserve(parent, filename, file=True)))
