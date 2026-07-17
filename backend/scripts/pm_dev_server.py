"""PM Hub 本地预览服务器（开发工具，不进生产路径）：

  python scripts/pm_dev_server.py [--port 8003]

- SQLite 文件库（backend/data/pm_dev.db），无需 MySQL/.env
- 预置演示数据（35 项材料 + 白名单 + workshop 任务 + 若干版本与动态）
- 静态托管 frontend-pm/dist（先 npm run build）
- /dev-enter?u=<username> 开发专用免跳转门：写 localStorage 后进 dashboard
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.pm import diff_service
from app.pm.auth import issue_pm_token
from app.pm.models import (
    PmActivityLog, PmMaterial, PmMaterialVersion, PmMember, PmProject, PmTask, PmTaskMaterial, bj_now,
)
from app.pm.router import router as pm_router
from app.pm.seed_data import MATERIALS_SEED, MEMBERS_SEED, PROJECT_SEED, TASKS_SEED
from app.pm.service import PM_STORAGE_ROOT

# SQLite 不支持 BIGINT 自增——与 tests/conftest.py 同款编译期替换
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import BigInteger


@compiles(BigInteger, "sqlite")
def _compile_big_int_sqlite(type_, compiler, **kw):
    return "INTEGER"

DB_PATH = BACKEND_DIR / "data" / "pm_dev.db"
DIST_DIR = BACKEND_DIR.parent / "frontend-pm" / "dist"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
DevSession = sessionmaker(bind=engine, autoflush=False)

# 差异管线在预览库里走同一 SQLite（demo 版本直接预置终态，不会真调 AI）
diff_service.SessionLocal = DevSession


def seed_demo() -> None:
    with DevSession() as db:
        if db.query(PmProject).first():
            return
        project = PmProject(**PROJECT_SEED)
        db.add(project)
        db.flush()
        for username, display in MEMBERS_SEED:
            db.add(PmMember(username=username, display_name=display))
        for i, (list_no, name, cat, imp, phase, dt, desc) in enumerate(MATERIALS_SEED):
            db.add(PmMaterial(
                project_id=project.id, list_no=list_no, name=name, category=cat,
                importance=imp, phase=phase, delivery_type=dt, description=desc, sort_order=i,
                owner=MEMBERS_SEED[i % len(MEMBERS_SEED)][0] if i % 3 == 0 else None,
            ))
        db.flush()
        materials = db.query(PmMaterial).all()
        by_no = {m.list_no: m for m in materials}

        # 状态铺开，让总览页有真实感
        status_map = {
            1: "confirmed", 2: "submitted", 3: "submitted", 4: "preparing", 5: "not_started",
            10: "confirmed", 11: "submitted", 12: "preparing", 13: "not_started",
            14: "confirmed", 15: "submitted", 16: "preparing", 17: "not_started", 18: "submitted",
            6: "not_started", 7: "not_started", 8: "preparing", 9: "not_started",
            19: "preparing", 20: "not_started", 21: "not_required",
            22: "not_started", 23: "preparing", 24: "not_started", 25: "not_started",
            26: "not_started", 27: "not_started", 28: "not_started",
        }
        for no, status in status_map.items():
            if no in by_no:
                by_no[no].status = status
        if 24 in by_no:
            by_no[24].external_url = "https://pan.example.com/leshine/videos"

        # 价格体系 3 个版本（含 AI 概要终态）+ 产品目录 1 个 pending 版本
        storage = PM_STORAGE_ROOT
        storage.mkdir(parents=True, exist_ok=True)

        def _write(m, no, content, name, by, note, days_ago, diff_status, summary=None, deleted=False):
            rel = f"{m.id}/demo-v{no}-{name}"
            (storage / str(m.id)).mkdir(parents=True, exist_ok=True)
            (storage / rel).write_bytes(content)
            v = PmMaterialVersion(
                material_id=m.id, version_no=no, file_path=rel, original_name=name,
                file_size=len(content), content_type="text/plain", change_note=note,
                diff_status=diff_status, diff_summary=summary, uploaded_by=by,
                created_at=bj_now() - timedelta(days=days_ago),
                deleted_at=bj_now() if deleted else None,
            )
            db.add(v)
            return v

        price = by_no[2]
        _write(price, 1, b"v1 price", "price-v1.txt", "liang.xz26", "初版", 6, "not_applicable")
        _write(price, 2, b"v2 price", "price-v2.txt", "liang.xz26", "补充样品价", 3, "done",
               "· 新增：全色号样品包价格（$45/套）\n· 修改：L1+ 客户折扣从 8% 调整为 8-12% 区间\n· 删除：已停产的 613# 色号价格行\n\n总评：报价结构更贴近顾问的分层建议")
        _write(price, 3, b"v3 price", "price-v3.txt", "sunzh.qm41", "按评审意见修订", 1, "done",
               "· 修改：天才发帘 20\" 标准价 $128 → $132\n· 新增：满 50 件阶梯优惠说明\n\n总评：小幅调价并补齐批量政策")
        catalog = by_no[1]
        _write(catalog, 1, b"sku list", "sku-v1.txt", "bixz.kd28", None, 2, "not_applicable")
        _write(catalog, 2, b"sku list v2", "sku-v2.txt", "bixz.kd28", "同步最新 SKU", 0, "pending")
        faq = by_no.get(23)
        if faq:
            _write(faq, 1, b"faq v1", "faq-v1.txt", "lijc.rf56", None, 1, "failed", None)

        # workshop 任务 + 演示任务铺开四列
        for title, desc, link_no in TASKS_SEED:
            t = PmTask(project_id=project.id, title=title, description=desc,
                       status="todo", created_by="seed",
                       due_date=date.today() + timedelta(days=7))
            db.add(t)
            db.flush()
            if link_no in by_no:
                db.add(PmTaskMaterial(task_id=t.id, material_id=by_no[link_no].id))
        extras = [
            ("对齐 OKKI 客户字段映射", "in_progress", "sunzh.qm41", 3, 18),
            ("整理历史报价单样本", "in_progress", "lijc.rf56", 5, 25),
            ("确认阿里子账号权限边界", "done", "liang.xz26", -1, 14),
            ("海关数据权限开通申请", "blocked", "yindk.gm82", 2, 21),
        ]
        for title, status, assignee, due_in, link_no in extras:
            t = PmTask(
                project_id=project.id, title=title, status=status, assignee=assignee,
                blocked_reason="等服务商审核企业资质" if status == "blocked" else None,
                due_date=date.today() + timedelta(days=due_in), created_by="liang.xz26",
            )
            db.add(t)
            db.flush()
            if link_no in by_no:
                db.add(PmTaskMaterial(task_id=t.id, material_id=by_no[link_no].id))

        # 演示动态
        acts = [
            ("liang.xz26", "upload_version", "version", "价格体系 v3", 1),
            ("sunzh.qm41", "update_task", "task", "对齐 OKKI 客户字段映射", 1),
            ("bixz.kd28", "upload_version", "version", "产品目录与全量SKU清单 v2", 0),
            ("liang.xz26", "entry", "member", "亮哥", 0),
            ("lijc.rf56", "update_material", "material", "常见询盘问题 FAQ 库", 0),
        ]
        for username, action, otype, oname, days_ago in acts:
            db.add(PmActivityLog(
                project_id=project.id, username=username, action=action, object_type=otype,
                object_name=oname, created_at=bj_now() - timedelta(days=days_ago, hours=2),
            ))
        db.commit()
        print("[pm_dev] seeded demo data", flush=True)


def create_app() -> FastAPI:
    app = FastAPI(title="PM Hub dev preview")

    from fastapi.responses import JSONResponse

    @app.exception_handler(ValueError)
    async def _value_error(request, exc):  # 与 app.main 全局处理同款：业务校验失败一律 400
        return JSONResponse(status_code=400, content={"code": 400, "message": str(exc), "data": None})

    def override_db():
        db = DevSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.include_router(pm_router, prefix="/api/pm")

    @app.get("/dev-enter", response_class=HTMLResponse)
    def dev_enter(u: str = "liang.xz26"):
        """开发专用：免门牌直进（仅本地预览库，不经过白名单校验）。"""
        token = issue_pm_token(u)
        display = dict(MEMBERS_SEED).get(u, u)
        return f"""<!doctype html><meta charset="utf-8"><script>
localStorage.setItem('pm_hub_token', {token!r});
localStorage.setItem('pm_hub_display_name', {display!r});
localStorage.setItem('pm_hub_username', {u!r});
location.replace('/dashboard');
</script>"""

    if DIST_DIR.exists():
        app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="pm-dist")

        @app.exception_handler(404)
        async def spa_fallback(request, exc):
            if request.url.path.startswith("/api/"):
                raise exc
            return FileResponse(str(DIST_DIR / "index.html"))

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8003)
    args = parser.parse_args()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    seed_demo()
    print(f"[pm_dev] http://localhost:{args.port}/dev-enter?u=liang.xz26", flush=True)
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")
