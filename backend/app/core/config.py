"""环境变量配置（Pydantic Settings）"""

from urllib.parse import quote_plus

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 提成系统数据库（读写）
    COMMISSION_DB_HOST: str = "localhost"
    COMMISSION_DB_PORT: int = 3306
    COMMISSION_DB_USER: str = "commission"
    COMMISSION_DB_PASSWORD: str = "changeme"
    COMMISSION_DB_NAME: str = "commission_db"

    # 业务数据库（只读，同一RDS实例，跨库查询）
    BUSINESS_DB_NAME: str = "lsordertest"

    # DHL API
    DHL_API_USERNAME: str = ""
    DHL_API_PASSWORD: str = ""
    DHL_API_ENV: str = "test"

    # FedEx API
    FEDEX_CLIENT_ID: str = ""
    FEDEX_CLIENT_SECRET: str = ""
    FEDEX_SANDBOX: str = "false"

    # 轮询配置
    TRACKING_POLL_BATCH_SIZE: int = 50
    STAGING_SCAN_BATCH_SIZE: int = 100

    # 短链接
    SHORT_LINK_BASE_URL: str = "http://localhost:8001"

    # 设计预约模块
    DESIGN_DEFAULT_DAILY_CAPACITY: int = 3
    DESIGN_REQUEST_NO_PREFIX: str = "DSR"
    DESIGN_TASK_NO_PREFIX: str = "DST"

    # JWT / Auth
    JWT_SECRET_KEY: str = "change-this-to-a-random-64-char-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    LOGIN_MAX_FAIL: int = 5
    LOGIN_LOCK_MINUTES: int = 30
    COOKIE_SECURE: bool = False  # 生产环境设为 True

    # 钉钉 AI 表格 API
    DINGTALK_CLIENT_ID: str = ""
    DINGTALK_CLIENT_SECRET: str = ""

    # 钉钉 Webhook 机器人
    DINGTALK_WEBHOOK_URL: str = ""
    DINGTALK_WEBHOOK_SECRET: str = ""

    # 钉钉企业内部应用（工作通知、审批）
    DINGTALK_APP_KEY: str = ""
    DINGTALK_APP_SECRET: str = ""
    DINGTALK_AGENT_ID: str = ""

    # 钉钉回调
    DINGTALK_CALLBACK_AES_KEY: str = ""
    DINGTALK_CALLBACK_TOKEN: str = ""

    @property
    def commission_db_url(self) -> str:
        password = quote_plus(self.COMMISSION_DB_PASSWORD)
        return (
            f"mysql+pymysql://{self.COMMISSION_DB_USER}:{password}"
            f"@{self.COMMISSION_DB_HOST}:{self.COMMISSION_DB_PORT}/{self.COMMISSION_DB_NAME}"
            "?charset=utf8mb4"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
