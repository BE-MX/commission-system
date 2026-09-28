"""Public reference quotes with source timestamps, bounded caches and no invented ticks."""

import copy
import csv
import io
import logging
import re
import statistics
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser

import httpx

from app.core.time import beijing_now

logger = logging.getLogger(__name__)
BOC_URL = "https://www.boc.cn/sourcedb/whpj/"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
QUOTE_MAX_AGE_SECONDS = 1800
_lock = threading.Lock()
_cache: dict = {}


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def parse_boc_quotes(html: str, now: datetime) -> list[dict]:
    parser = _Rows()
    parser.feed(html)
    quotes = {}
    for cells in parser.rows:
        if len(cells) < 7 or cells[0] != "美元":
            continue
        stamp = re.search(r"(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})", " ".join(cells[6:]))
        if not stamp:
            raise ValueError("银行报价缺少发布日期或时间")
        as_of = datetime.strptime(" ".join(stamp.groups()), "%Y/%m/%d %H:%M:%S")
        rate = Decimal(cells[1]) / Decimal("100")
        if not Decimal("1") <= rate <= Decimal("20") or as_of > now + timedelta(minutes=5):
            raise ValueError("银行报价数值或时间异常")
        quotes[as_of] = {"rate": float(rate), "as_of": as_of.isoformat()}
    if not quotes:
        raise ValueError("来源中没有可识别的美元现汇买入价")
    return [quotes[key] for key in sorted(quotes, reverse=True)]


def parse_fred_history(text: str, today: date) -> list[dict]:
    result = {}
    for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        raw = row.get("DEXCHUS")
        if raw in {None, "", "."}:
            continue
        day = date.fromisoformat(row["observation_date"])
        rate = float(raw)
        if day > today or day < today - timedelta(days=370):
            continue
        if not 1 <= rate <= 20:
            raise ValueError("历史汇率超出有效范围")
        result[day] = {"date": day.isoformat(), "rate": rate}
    if len(result) < 21:
        raise ValueError("历史有效观测不足 21 条")
    return [result[key] for key in sorted(result)]


def trend_summary(history: list[dict], now: datetime) -> dict | None:
    if len(history) < 21:
        return None
    values = [row["rate"] for row in history]
    age_days = (now.date() - date.fromisoformat(history[-1]["date"])).days
    return {
        "as_of": history[-1]["date"], "lag_days": age_days,
        "usable": 0 <= age_days <= 10,
        "change_5d_pct": round((values[-1] / values[-6] - 1) * 100, 3),
        "change_20d_pct": round((values[-1] / values[-21] - 1) * 100, 3),
        "ma5": round(statistics.mean(values[-5:]), 4),
        "ma20": round(statistics.mean(values[-20:]), 4),
    }


def _fetch(kind: str, now: datetime):
    with httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=True) as client:
        if kind == "quote":
            response = client.get(BOC_URL)
            response.raise_for_status()
            quotes = parse_boc_quotes(response.text, now)
            try:
                older = client.get(BOC_URL + "index_1.html", timeout=6)
                older.raise_for_status()
                quotes.extend(parse_boc_quotes(older.text, now))
            except (httpx.HTTPError, ValueError, ArithmeticError) as exc:
                logger.warning("FX intraday comparison unavailable: %s", type(exc).__name__)
                print(f"[FX] intraday comparison unavailable: {type(exc).__name__}", flush=True)
            unique = {item["as_of"]: item for item in quotes}
            return [unique[key] for key in sorted(unique, reverse=True)]
        response = client.get(FRED_URL, params={
            "id": "DEXCHUS", "cosd": (now.date() - timedelta(days=365)).isoformat(),
            "coed": now.date().isoformat(),
        })
        response.raise_for_status()
        return parse_fred_history(response.text, now.date())


def _get_cached(kind: str, now: datetime) -> tuple[list, str | None]:
    ttl = 60 if kind == "quote" else 3600
    entry = _cache.get(kind, {})
    if time.monotonic() < entry.get("retry_at", 0):
        return entry.get("data", []), entry.get("error")
    try:
        data = _fetch(kind, now)
        _cache[kind] = {"data": data, "retry_at": time.monotonic() + ttl, "error": None}
    except (httpx.HTTPError, ValueError, KeyError, ArithmeticError) as exc:
        logger.warning("FX market source failed: %s %s", kind, type(exc).__name__)
        print(f"[FX] market source failed: {kind} {type(exc).__name__}", flush=True)
        _cache[kind] = {
            "data": entry.get("data", []), "retry_at": time.monotonic() + 60,
            "error": "银行参考报价暂时无法更新" if kind == "quote" else "日度历史暂时无法更新",
        }
    return _cache[kind]["data"], _cache[kind]["error"]


def get_market() -> dict:
    now = beijing_now()
    # Single-flight protects public sources from multi-user refresh bursts.
    with _lock:
        quotes, quote_error = _get_cached("quote", now)
        history, history_error = _get_cached("history", now)
        quotes, history = copy.deepcopy(quotes), copy.deepcopy(history)
    now = beijing_now()
    quote = quotes[0] if quotes else None
    intraday = None
    if quote:
        age = (now - datetime.fromisoformat(quote["as_of"])).total_seconds()
        quote.update({
            "age_seconds": max(0, int(age)),
            "usable": -300 <= age <= QUOTE_MAX_AGE_SECONDS,
            "source": "中国银行美元现汇买入参考价", "source_url": BOC_URL,
            "is_executable": False,
        })
        previous = next((item for item in quotes[1:] if item["as_of"][:10] == quote["as_of"][:10]), None)
        if previous:
            intraday = {"from_at": previous["as_of"], "to_at": quote["as_of"],
                        "change_pct": round((quote["rate"]/previous["rate"]-1)*100, 4)}
    return {
        "checked_at": now.isoformat(), "quote": quote, "intraday": intraday,
        "history": history, "trend": trend_summary(history, now),
        "history_source": "美联储 H.10 / FRED DEXCHUS（按周发布的日度报价）",
        "history_source_url": "https://fred.stlouisfed.org/series/DEXCHUS",
        "warnings": [message for message in (quote_error, history_error) if message],
        "refresh_seconds": 60,
    }
