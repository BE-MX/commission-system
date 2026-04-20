"""API 路由汇总"""

from app.api.employee import router as employee_router
from app.api.supervisor import router as supervisor_router
from app.api.customer import router as customer_router
from app.api.payment import router as payment_router
from app.api.commission import router as commission_router
from app.api.report import router as report_router

__all__ = [
    "employee_router",
    "supervisor_router",
    "customer_router",
    "payment_router",
    "commission_router",
    "report_router",
]
