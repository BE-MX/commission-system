"""环境变量配置（Pydantic Settings）"""

from urllib.parse import quote_plus

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


_JWT_DEFAULT_PLACEHOLDER = "change-this-to-a-random-64-char-secret-in-production"


class Settings(BaseSettings):
    # ── 应用环境 ──────────────────────────────────────────
    APP_ENV: str = "development"  # development / production

    # ── 提成系统数据库（读写）──────────────────────────────
    COMMISSION_DB_HOST: str = "localhost"
    COMMISSION_DB_PORT: int = 3306
    COMMISSION_DB_USER: str = "commission"
    COMMISSION_DB_PASSWORD: str = "changeme"
    COMMISSION_DB_NAME: str = "commission_db"

    # ── 业务数据库（只读，同一RDS实例，跨库查询）────────────
    BUSINESS_DB_NAME: str = "lsordertest"

    # ── DHL API ──────────────────────────────────────────
    DHL_API_USERNAME: str = ""
    DHL_API_PASSWORD: str = ""
    DHL_API_ENV: str = "test"

    # ── FedEx API ────────────────────────────────────────
    FEDEX_CLIENT_ID: str = ""
    FEDEX_CLIENT_SECRET: str = ""
    FEDEX_SANDBOX: str = "false"

    # ── 轮询配置 ─────────────────────────────────────────
    TRACKING_POLL_BATCH_SIZE: int = 50
    STAGING_SCAN_BATCH_SIZE: int = 100

    # ── APScheduler 定时任务 ─────────────────────────────
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "Asia/Shanghai"

    # ── 短链接 ───────────────────────────────────────────
    SHORT_LINK_BASE_URL: str = "https://leshine.work"

    # ── TFT 备货预测微服务 ────────────────────────────────
    TFT_SERVICE_ENABLED: bool = False
    TFT_SERVICE_URL: str = ""

    # ── 设计预约模块 ──────────────────────────────────────
    DESIGN_DEFAULT_DAILY_CAPACITY: int = 3
    DESIGN_REQUEST_NO_PREFIX: str = "DSR"
    DESIGN_TASK_NO_PREFIX: str = "DST"

    # ── JWT / Auth ───────────────────────────────────────
    JWT_SECRET_KEY: str = _JWT_DEFAULT_PLACEHOLDER
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    LOGIN_MAX_FAIL: int = 5
    LOGIN_LOCK_MINUTES: int = 30
    COOKIE_SECURE: bool = False  # production 模式下必须为 True

    # ── CORS ─────────────────────────────────────────────
    # 接受 .env 中的逗号分隔字符串(也接受 JSON 数组)。production 模式下不允许含 localhost。
    CORS_ALLOW_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:8000",
    ]

    # ── AI 加密 ──────────────────────────────────────────
    ARK_AI_ENCRYPTION_KEY: str = ""  # production 模式下必须显式配置

    # ── 钉钉 AI 表格 API ─────────────────────────────────
    DINGTALK_CLIENT_ID: str = ""
    DINGTALK_CLIENT_SECRET: str = ""

    # ── 钉钉 Webhook 机器人 ──────────────────────────────
    DINGTALK_WEBHOOK_URL: str = ""
    DINGTALK_WEBHOOK_SECRET: str = ""

    # ── 钉钉企业内部应用（工作通知、审批）────────────────
    DINGTALK_APP_KEY: str = ""
    DINGTALK_APP_SECRET: str = ""
    DINGTALK_AGENT_ID: str = ""

    # ── 钉钉回调 ─────────────────────────────────────────
    DINGTALK_CALLBACK_AES_KEY: str = ""
    DINGTALK_CALLBACK_TOKEN: str = ""

    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        """支持 .env 逗号分隔字符串 (BaseSettings 默认只接受 JSON 数组)"""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _validate_production(self):
        """production 模式启动前校验关键安全配置"""
        if self.APP_ENV != "production":
            return self
        errors = []
        if self.JWT_SECRET_KEY == _JWT_DEFAULT_PLACEHOLDER:
            errors.append("JWT_SECRET_KEY 不能使用默认占位符,请生成一个长随机串")
        if not self.COOKIE_SECURE:
            errors.append("COOKIE_SECURE 必须为 True (HTTPS 部署下)")
        if not self.CORS_ALLOW_ORIGINS or any("localhost" in o for o in self.CORS_ALLOW_ORIGINS):
            errors.append("CORS_ALLOW_ORIGINS 必须显式配置生产域名,不能含 localhost")
        if not self.ARK_AI_ENCRYPTION_KEY:
            errors.append("ARK_AI_ENCRYPTION_KEY 必须显式配置")
        if errors:
            details = "\n  - ".join(errors)
            raise ValueError(
                f"APP_ENV=production 下配置校验失败:\n  - {details}"
            )
        return self

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
