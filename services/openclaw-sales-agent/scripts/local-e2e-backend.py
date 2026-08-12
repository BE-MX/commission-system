#!/usr/bin/env python3
"""Run the real Ark sales API against an isolated SQLite database for local E2E.

This harness mounts the production Agent router and production token resolver.
It never imports the full Ark application lifespan, schedulers, or MySQL engine.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.auth.models import (  # noqa: E402
    ArkPermission,
    ArkRole,
    ArkRolePermission,
    ArkUser,
    ArkUserRole,
)
from app.auth.utils import hash_token  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.mcp.models import MCPToken  # noqa: E402
from app.sales_automation import agent_router, models, service  # noqa: E402


@compiles(BigInteger, "sqlite")
def _sqlite_bigint_as_integer(_type, _compiler, **_kwargs):
    """Preserve MySQL BIGINT auto-increment behavior in the SQLite harness."""
    return "INTEGER"


PROFILE = {
    "company_name": "Leshine Industrial Export Demo",
    "company_website": "https://leshine.work",
    "products": [
        "industrial automation equipment",
        "industrial networking",
        "control components",
    ],
    "advantages": ["small MOQ", "export support"],
    "target_countries": ["Mexico"],
    "target_industries": ["industrial automation distributor"],
    "target_roles": ["owner", "purchasing manager"],
    "exclusions": ["consumer electronics only"],
    "default_language": "en",
}

JOB = {
    "name": "Mexico industrial automation distributors - local E2E",
    "target_count": 2,
    "keywords": ["industrial automation distributor Mexico"],
    "countries": ["Mexico"],
    "industries": ["industrial automation distributor"],
    "idempotency_key": "openclaw-local-e2e-v1",
}

TABLES = [
    ArkUser.__table__,
    ArkRole.__table__,
    ArkPermission.__table__,
    ArkUserRole.__table__,
    ArkRolePermission.__table__,
    MCPToken.__table__,
    models.AcquisitionProfile.__table__,
    models.SearchJob.__table__,
    models.LeadCompany.__table__,
    models.SearchResult.__table__,
    models.LeadContact.__table__,
    models.ResearchRun.__table__,
    models.ResearchFact.__table__,
]


def _private_token(path: Path) -> str:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("E2E token path must be a regular non-symlink file")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise RuntimeError("E2E token file must be owned by the current user with mode 0600")
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("E2E token must contain at least 32 characters")
    return token


def _engine(database: Path):
    return create_engine(
        f"sqlite:///{database}",
        connect_args={"check_same_thread": False},
        hide_parameters=True,
    )


def _seed(session_factory, token: str) -> int:
    with session_factory() as db:
        user = ArkUser(
            id=17001,
            username="openclaw_e2e_agent",
            password_hash="not-a-login-account",
            real_name="OpenClaw E2E Agent",
            is_active=True,
        )
        role = ArkRole(
            id=17001,
            name="openclaw_e2e_invoke_only",
            label="OpenClaw E2E invoke only",
        )
        permission = ArkPermission(
            id=17001,
            code="sales_automation:invoke",
            module="sales_automation",
            action="invoke",
            label="Agent invokes intelligent acquisition",
        )
        db.add_all([user, role, permission])
        db.flush()
        db.add(ArkUserRole(user_id=user.id, role_id=role.id))
        db.add(ArkRolePermission(role_id=role.id, permission_id=permission.id))
        db.add(MCPToken(
            id=17001,
            token_hash=hash_token(token),
            user_id=user.id,
            label="openclaw-local-e2e",
            is_active=True,
        ))
        db.commit()
        service.upsert_profile(db, PROFILE, actor_id=user.id)
        job = service.create_search_job(db, JOB, actor_id=user.id)
        return int(job.id)


def create_app(database: Path, token_file: Path) -> FastAPI:
    if database.exists():
        raise RuntimeError(f"Refusing to reuse existing E2E database: {database}")
    database.parent.mkdir(parents=True, exist_ok=True)
    engine = _engine(database)
    Base.metadata.create_all(engine, tables=TABLES)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    job_id = _seed(session_factory, _private_token(token_file))

    app = FastAPI(title="Ark Sales OpenClaw Local E2E")
    app.include_router(agent_router.router, prefix="/api/sales-automation")

    def session_dependency():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = session_dependency

    @app.get("/health")
    def health():
        return {"status": "ok", "job_id": job_id}

    return app


def report(database: Path) -> dict:
    engine = _engine(database)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    with session_factory() as db:
        jobs = db.query(models.SearchJob).order_by(models.SearchJob.id).all()
        companies = db.query(models.LeadCompany).order_by(models.LeadCompany.id).all()
        results = db.query(models.SearchResult).order_by(models.SearchResult.id).all()
        return {
            "jobs": [{
                "id": row.id,
                "status": row.status,
                "target_count": row.target_count,
                "result_count": row.result_count,
                "created_count": row.created_count,
                "deduplicated_count": row.deduplicated_count,
                "attempt_count": row.attempt_count,
                "error_message": row.error_message,
            } for row in jobs],
            "companies": [{
                "id": row.id,
                "name": row.name,
                "domain": row.normalized_domain,
                "website": row.website,
                "country": row.country,
                "industry": row.industry,
                "match_score": row.match_score,
                "score_reasons": row.score_reasons,
            } for row in companies],
            "evidence": [{
                "job_id": row.job_id,
                "company_id": row.company_id,
                "request_key": row.request_key,
                "source_provider": row.source_provider,
                "source_url": row.source_url,
                "captured_at": row.captured_at.isoformat(),
                "score": row.score,
            } for row in results],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--port", type=int, default=18881)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    database = args.database.expanduser().resolve()
    if args.report:
        print(json.dumps(report(database), ensure_ascii=False, indent=2))
        return
    if args.token_file is None:
        parser.error("--token-file is required unless --report is used")
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")

    import uvicorn

    app = create_app(database, args.token_file.expanduser().resolve())
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
