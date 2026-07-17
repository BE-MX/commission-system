"""环境变量配置（Pydantic Settings）"""

from pathlib import Path
from urllib.parse import quote_plus

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


_JWT_DEFAULT_PLACEHOLDER = "change-this-to-a-random-64-char-secret-in-production"
_BACKEND_DIR = Path(__file__).resolve().parents[2]


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

    # ── 对外库存查询（客户官网嵌入页 / 客户系统 API） ─────
    # 逗号分隔的访问 key，可按客户发放与单独吊销；留空 = 端点整体关闭
    PUBLIC_STOCK_KEYS: str = ""

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
        "http://127.0.0.1:8001",
        "http://localhost:8001",
        "http://192.168.100.43:8001",
    ]

    # ── AI 加密 ──────────────────────────────────────────
    ARK_AI_ENCRYPTION_KEY: str = ""  # production 模式下必须显式配置

    # ── 素材存储（治理 B-5：收敛自 os.environ 直读）──────
    ASSET_STORAGE_ROOT: str = "D:\\WORKSOURCE"
    ASSET_SIGN_SECRET: str = "leshine-asset-secret"
    ASSET_UPLOAD_STAGING: str = "D:\\upload_staging"

    # ── 客户售后管理 ─────────────────────────────────────────
    AFTERSALES_STORAGE_ROOT: str = "D:\\WORKSOURCE\\aftersales"
    AFTERSALES_DETAIL_BASE_URL: str = "https://leshine.work/aftersales/cases"

    # ── 色彩趋势 ─────────────────────────────────────────
    XPOZ_TARGET_ACCOUNTS: str = ""  # 逗号分隔的目标账号

    # ── ACCIO WORK 导入接口 ──────────────────────────────
    INSIGHT_IMPORT_API_KEY: str = ""

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

    # ── 生产报工 ──────────────────────────────────────────
    QR_SIGN_SECRET: str = "change-this-to-a-random-32-char-secret"  # 二维码 HMAC 签名密钥
    PRODUCTION_API_KEY: str = ""  # ACCIO WORK 调用报工接口的 API Key

    # ── WhatsApp Connector ───────────────────────────────
    WHATSAPP_CONNECTOR_BASE_URL: str = ""
    WHATSAPP_CONNECTOR_API_KEY: str = ""
    WHATSAPP_CONNECTOR_TIMEOUT_SECONDS: int = 30
    WHATSAPP_AUTO_SYNC_ENABLED: bool = True
    WHATSAPP_AUTO_SYNC_INTERVAL_MINUTES: int = 5
    WHATSAPP_AUTO_SYNC_BATCH_SIZE: int = 100
    WHATSAPP_SYNC_MESSAGES_PER_CHAT: int = 100

    # ── 微信小程序 ────────────────────────────────────────
    WX_MINI_APPID: str = ""  # 微信小程序 AppID
    WX_MINI_SECRET: str = ""  # 微信小程序 AppSecret

    # ── OKKI 开放平台（订单推送，client_credentials 鉴权）─
    OKKI_CLIENT_ID: str = ""
    OKKI_CLIENT_SECRET: str = ""
    OKKI_API_BASE: str = "https://api-sandbox.xiaoman.cn"  # api-sandbox 即正式域名（官方文档确认）

    # ── PM 项目资料协作站 ─────────────────────────────────
    PM_TOKEN_SECRET: str = ""  # HMAC 签名密钥；留空回退 JWT_SECRET_KEY
    PM_TOKEN_TTL_DAYS: int = 30  # 进入 token 有效期（天）
    PM_TOKEN_EPOCH: int = 1  # 全局版本号 salt：+1 即全员重新验证（极端情况兜底）
    PM_FILE_SIGN_TTL_SECONDS: int = 300  # 下载/预览签名 URL 短时效（秒）
    PM_MAX_UPLOAD_MB: int = 50  # 单文件上传上限（frp 隧道带宽是全站稀缺资源）

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

    model_config = {
        "env_file": str(_BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
