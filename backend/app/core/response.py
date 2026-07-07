"""统一响应信封 — 架构治理 B-3 的官方实现。

新模块（expo 起）一律使用本模块的 ok()/page_result()；
既有各 router 的本地 _ok() 后续逐个收敛到这里（保持超集签名兼容）。
"""

from typing import Any


def ok(data: Any = None, message: str = "ok", code: int = 200) -> dict:
    return {"code": code, "message": message, "data": data}


def page_result(items: list, total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}
