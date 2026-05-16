"""APScheduler 集中注册"""

from app.schedulers.registry import start_scheduler, shutdown_scheduler

__all__ = ["start_scheduler", "shutdown_scheduler"]
