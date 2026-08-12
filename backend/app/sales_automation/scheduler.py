"""公海客户每日分档抽样任务。"""

import logging
from datetime import date

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.sales_automation.public_pool_service import generate_batch


logger = logging.getLogger("commission.sales_public_pool.scheduler")


def generate_public_pool_daily_batch() -> None:
    """每天生成 T1/T2/T3 背调任务；同日同策略调用具有幂等性。"""
    settings = get_settings()
    with SessionLocal() as db:
        try:
            batch = generate_batch(
                db,
                {
                    "batch_date": date.today(),
                    "quota_per_tier": settings.SALES_PUBLIC_POOL_QUOTA_PER_TIER,
                    "policy_version": "v1",
                },
                actor_id=None,
            )
            logger.info(
                "public pool daily batch ready: id=%s date=%s status=%s counts=%s",
                batch.id, batch.batch_date, batch.status, batch.result_counts,
            )
        except Exception as exc:
            logger.exception("public pool daily batch failed")
            print(f"public pool daily batch failed: {type(exc).__name__}", flush=True)
            raise
