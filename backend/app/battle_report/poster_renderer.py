"""Deterministic HTML screenshots using the approved art, no per-run AI calls."""
import base64
import logging
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import get_settings

ASSETS = Path(__file__).resolve().parent / "assets"
_RENDER_SLOTS = BoundedSemaphore(1)
logger = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def asset_uri(name):
    return "data:image/png;base64," + base64.b64encode((ASSETS / name).read_bytes()).decode("ascii")


def render_html(snapshot, kind):
    if kind not in ("team", "personal"):
        raise ValueError("Unknown poster kind")
    env = Environment(loader=FileSystemLoader(ASSETS), autoescape=select_autoescape(["html"]))
    env.filters["money"] = lambda value: format(Decimal(value), ",.2f")
    env.filters["stamp"] = lambda value: value.replace("T", " ")[:19]
    css = (ASSETS / "poster.css").read_text(encoding="utf-8").replace("battle-poster-art-v2.png", asset_uri("background.png"))
    css += ".hero.generic{background-position:center center}.generic-title{position:absolute;top:115px;width:100%;text-align:center;font-size:100px}.name{white-space:normal;overflow-wrap:anywhere}.team-tag{overflow-wrap:anywhere}.percentage{font-size:50px}.metric-value{font-size:44px}.details b{font-size:30px}.details{font-size:24px}.pace-row{font-size:23px}.report-name{overflow-wrap:anywhere}"
    css += ".details{display:grid;grid-template-columns:1fr 1px 1fr;gap:20px}.details>span{min-width:0;display:flex;align-items:baseline;gap:8px}.details b{display:block;flex:1;min-width:0;margin-left:0}.details>span:last-child b{text-align:right}.percentage{width:190px;min-width:0;flex-shrink:0}"
    rows = []
    for row in snapshot["teams" if kind == "team" else "people"]:
        delta = Decimal(row["pace_delta"])
        pace_label = "与时间持平" if delta == 0 else ("领先 " if row["ahead_of_time"] else "落后 ") + f"{abs(delta):.2f} 个百分点"
        exact_delta = Decimal(row["gmv"]) * 100 / Decimal(row["target"]) - Decimal(str(snapshot["workday_progress"]["percent"]))
        if delta == 0 and exact_delta:
            pace_label = ("领先" if exact_delta > 0 else "落后") + "不足 0.01 个百分点"
        rows.append({**row, "label": row["team"] if kind == "team" else row["user_name"],
                     "fill": str(min(Decimal(100), Decimal(row["gmv"]) * 100 / Decimal(row["target"]))),
                     "pace_label": pace_label})
    target = Decimal(snapshot["summary"]["target"])
    target_display = f"{target / 10000:,.2f}万" if target >= 10000 else f"{target:,.2f}"
    return env.get_template("poster.html").render(**snapshot, rows=rows, kind=kind, css=css,
        month=int(snapshot["report"]["start_date"][5:7]), logo=asset_uri("company-logo.png"), target_display=target_display)


def render_posters(snapshot, kinds=("team", "personal")):
    """Must run in a sync worker thread (Windows subprocess support included)."""
    from playwright.sync_api import sync_playwright
    if not _RENDER_SLOTS.acquire(timeout=30):
        raise RuntimeError("海报生成繁忙，请稍后重试")
    try:
        settings = get_settings()
        with sync_playwright() as playwright:
            options = {"headless": True}
            if settings.BATTLE_REPORT_BROWSER_PATH:
                options["executable_path"] = settings.BATTLE_REPORT_BROWSER_PATH
            browser = playwright.chromium.launch(**options)
            try:
                page = browser.new_page(viewport={"width": 1080, "height": 1800}, device_scale_factor=1)
                page.set_default_timeout(30000)
                # Template and assets are local. A name/label cannot trigger a network request.
                page.route("**/*", lambda route: route.abort())
                result = {}
                for kind in kinds:
                    page.set_content(render_html(snapshot, kind), wait_until="load")
                    page.evaluate("async () => { await document.fonts.ready; await Promise.all([...document.images].map(i=>i.decode())); }")
                    # Fit long amounts without silently clipping valid business data.
                    page.evaluate("""() => {for(const el of document.querySelectorAll('.metric-value,.details b,.percentage')) {
                      let size=parseFloat(getComputedStyle(el).fontSize);
                      while(el.scrollWidth>el.clientWidth+1 && size>20) el.style.fontSize=(--size)+'px';
                    }}""")
                    result[kind] = page.screenshot(full_page=True, type="png", timeout=60000)
                return result
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("Battle poster rendering failed: %s", type(exc).__name__)
        print(f"Battle poster rendering failed: {type(exc).__name__}", flush=True)
        raise RuntimeError("海报生成失败，请检查 Chrome/Chromium 和中文字体配置") from None
    finally:
        _RENDER_SLOTS.release()
