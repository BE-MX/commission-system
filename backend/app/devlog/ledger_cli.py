"""部署器在办公室调用的账本写入入口：python -m app.devlog.ledger_cli < {"revision","release_id","scope"}

属 bootstrap 类一次性进程（红线 4 允许自建 SessionLocal）；时间取本进程 beijing_now()，即验收通过时刻。
"""
import json
import logging
import sys

from app.core.database import SessionLocal
from app.core.time import beijing_now
from app.devlog.release_service import record_release
from app.devlog.schemas import ReleaseIn

logger = logging.getLogger(__name__)


def main() -> int:
    try:
        request = json.loads(sys.stdin.read(65537))
        release = ReleaseIn.model_validate({**request, "released_at": beijing_now()})
    except Exception as exc:
        logger.warning("devlog ledger input invalid: %s", type(exc).__name__)
        print(f"[devlog] ledger input invalid: {type(exc).__name__}", flush=True)
        return 1
    db = SessionLocal()
    try:
        recorded = record_release(db, revision=release.revision, release_id=release.release_id, scope=release.scope,
                                  released_at=release.released_at, source="deployer")
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("devlog ledger write failed: %s", type(exc).__name__)
        print(f"[devlog] ledger write failed: {type(exc).__name__}", flush=True)
        return 1
    finally:
        db.close()
    print(json.dumps({"recorded": recorded}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
