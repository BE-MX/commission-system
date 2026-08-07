"""薪资主数据种子 (职级表/规则参数/部门映射, 幂等)"""

import logging

from app.core.database import SessionLocal

logger = logging.getLogger("commission")


def seed_salary_rules() -> None:
    """启动时初始化薪资主数据种子 (幂等,失败不阻塞启动)"""
    try:
        from app.salary.seed import seed_salary_master_data
        with SessionLocal() as db:
            seed_salary_master_data(db)
            logger.info("Salary master data seeded")
    except Exception as e:
        logger.warning(f"Seed salary rules skipped: {e}")
        print(f"[bootstrap.seed_salary] skipped: {e}", flush=True)
