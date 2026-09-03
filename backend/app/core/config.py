"""环境变量配置（Pydantic Settings）"""

import json
import re
from pathlib import Path
import string
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from functools import lru_cache


_JWT_DEFAULT_PLACEHOLDER = "change-this-to-a-random-64-char-secret-in-production"
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PositiveInt = Annotated[int, Field(gt=0)]
_PublicPoolQuota = Annotated[int, Field(gt=0, le=100)]


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

    # ── 智能获客公海背调批次 ─────────────────────────────
    # 默认关闭，完成 105 迁移并确认业务库只读账号可查询后再开启。
    SALES_PUBLIC_POOL_AUTO_BATCH_ENABLED: bool = False
    SALES_PUBLIC_POOL_BATCH_HOUR: int = 7
    SALES_PUBLIC_POOL_BATCH_MINUTE: int = 30
    SALES_PUBLIC_POOL_QUOTA_PER_TIER: _PublicPoolQuota = 20

    # ── 短链接 ───────────────────────────────────────────
    SHORT_LINK_BASE_URL: str = "https://leshine.work"

    # ── TFT 备货预测微服务 ────────────────────────────────
    TFT_SERVICE_ENABLED: bool = False
    TFT_SERVICE_URL: str = ""

    # ── 对外库存查询（客户公开查询页 / 客户系统 API） ─────
    # 2026-08-19 二期起端点全公开免 key，本配置废弃（保留字段兼容存量 .env）
    PUBLIC_STOCK_KEYS: str = ""

    # ── 采购节大屏（免登录局域网大屏取数） ─────────────────
    # 逗号分隔访问 key；留空 = 端点整体关闭（fail-closed）。
    # 第一个 key 由 /api/festival/screen-key 发给登录用户；改动后需重启后端生效
    FESTIVAL_SCREEN_KEYS: str = ""
    # 取数轨道：okki=保底轨(lsordertest 小满同步) / ark=主轨(方舟发票域，仅 synced)
    # 切轨策略见 data-layer 文档 §6.3：并跑对账连续 3 天零差异后切 ark
    FESTIVAL_DATA_SOURCE: str = "okki"
    # 采购节群使用独立机器人，禁止回退全局告警群，避免赛事实时消息发错群。
    FESTIVAL_DINGTALK_WEBHOOK_URL: str = ""
    FESTIVAL_DINGTALK_WEBHOOK_SECRET: str = ""
    # 定时截图从本机生产入口读取；端口/浏览器路径可按服务器实际安装覆盖。
    FESTIVAL_SCREENSHOT_BASE_URL: str = "http://127.0.0.1:8001"
    FESTIVAL_BROWSER_EXECUTABLE: str = ""

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

    # ── 薪资 PII 加密 ─────────────────────────────────────
    # 身份证/银行卡：AES-256-GCM 存储密文 + HMAC-SHA256 存哈希（哈希列才能做唯一约束与导入匹配）。
    # 与 AI key 用不同密钥：泄露面隔离，且轮换节奏不同（AI key 可随时换，薪资密钥换了要重算全表哈希）。
    ARK_SALARY_ENCRYPTION_KEY: str = ""  # base64(32 bytes)，production 必填
    ARK_SALARY_HASH_KEY: str = ""  # HMAC 密钥，production 必填

    # ── AI 生图工作台 ─────────────────────────────────────
    DESIGN_IMAGE_STORAGE_ROOT: str = r"D:\WORKSOURCE\design-image"
    DESIGN_IMAGE_DAILY_LIMIT: _PositiveInt = 20
    # 同一用户允许同时在途的生成任务数（会话级仍限 1 个）；总量仍受日额度约束
    DESIGN_IMAGE_MAX_ACTIVE_PER_USER: _PositiveInt = 2
    DESIGN_IMAGE_WORKER_CONCURRENCY: _PositiveInt = 3
    DESIGN_IMAGE_WORKER_INTERVAL_SECONDS: _PositiveInt = 10
    DESIGN_IMAGE_LEASE_SECONDS: _PositiveInt = 420
    DESIGN_IMAGE_STALE_SECONDS: _PositiveInt = 480
    DESIGN_IMAGE_DRAFT_TTL_HOURS: _PositiveInt = 24
    DESIGN_IMAGE_MAX_UPLOAD_MB: _PositiveInt = 20
    DESIGN_IMAGE_MAX_PIXELS: _PositiveInt = 60_000_000

    # Customer image portal reuses the design-image storage and upload limits.
    CUSTOMER_IMAGE_PRESET_NAME: str = "design_image_generation"
    CUSTOMER_IMAGE_WORKER_CONCURRENCY: _PositiveInt = 2
    CUSTOMER_IMAGE_LEASE_SECONDS: _PositiveInt = 420
    CUSTOMER_IMAGE_STALE_SECONDS: _PositiveInt = 480
    CUSTOMER_IMAGE_RETENTION_DAYS: _PositiveInt = 30
    CUSTOMER_IMAGE_PUBLIC_RATE_PER_MINUTE: _PositiveInt = 30
    CUSTOMER_IMAGE_MAX_REQUIREMENT_CHARS: _PositiveInt = 500

    # ── AI 方案对话 ───────────────────────────────────────
    AI_CHAT_STORAGE_ROOT: str = r"D:\WORKSOURCE\ai-chat"
    AI_CHAT_MAX_UPLOAD_BYTES: _PositiveInt = 4 * 1024 * 1024
    AI_CHAT_MAX_ATTACHMENTS: _PositiveInt = 5
    AI_CHAT_MAX_ATTACHMENT_CHARS: _PositiveInt = 60_000
    AI_CHAT_MAX_TURN_ATTACHMENT_CHARS: _PositiveInt = 120_000

    # ── 企业知识库图片与 AI 优化 ───────────────────────────
    # 默认锚定 backend/data 私有目录；生产可覆盖为独立绝对路径。
    KNOWLEDGE_STORAGE_ROOT: str = str(_BACKEND_DIR / "data" / "knowledge")
    KNOWLEDGE_IMAGE_MAX_UPLOAD_MB: _PositiveInt = 10
    KNOWLEDGE_IMAGE_DRAFT_TTL_HOURS: _PositiveInt = 24
    KNOWLEDGE_AI_WORKER_INTERVAL_SECONDS: _PositiveInt = 10
    KNOWLEDGE_AI_LEASE_SECONDS: _PositiveInt = 180

    # ── AI 生图代理（可选，仅 image_service 生图链路走；文本 chat 不受影响）──
    # 北京展会实例出口对 api.wlai.vip 存在 SNI 阻断（2026-07-31 实证），该实例配
    # socks5://127.0.0.1:1081 借 SSH 隧道从新加坡机出境；办公室生产留空=直连。
    # socks5 依赖 httpx[socks]；隧道运维见 runbook「云端展会实例」节。
    AI_IMAGE_PROXY: str = ""

    # ── 素材存储（治理 B-5：收敛自 os.environ 直读）──────
    ASSET_STORAGE_ROOT: str = "D:\\WORKSOURCE"
    ASSET_SIGN_SECRET: str = "leshine-asset-secret"
    ASSET_UPLOAD_STAGING: str = "D:\\upload_staging"

    # ── 展会扫码上传（2026-08-01）────────────────────────────
    # 手机上传页免鉴权，令牌即凭证。生产环境须在 backend/.env 覆盖为随机串
    EXPO_UPLOAD_SIGN_SECRET: str = "leshine-expo-upload-secret"

    # ── 客户售后管理 ─────────────────────────────────────────
    AFTERSALES_STORAGE_ROOT: str = "D:\\WORKSOURCE\\aftersales"
    AFTERSALES_DETAIL_BASE_URL: str = "https://leshine.work/aftersales/cases"

    # ── 培训速递 ─────────────────────────────────────────
    TRAINING_STORAGE_ROOT: str = "D:\\WORKSOURCE\\training"
    TRAINING_DETAIL_BASE_URL: str = "https://leshine.work/training/digests"

    # ── 内贸订单（明细图文要求的参考图）────────────────────
    DOMESTIC_STORAGE_ROOT: str = "D:\\WORKSOURCE\\domestic"

    # ── 发货检验（验货照片）────────────────────────────────
    SHIPPING_INSPECTION_STORAGE_ROOT: str = str(_BACKEND_DIR.parent / "uploads" / "shipping-inspection")

    # ── 客户拍摄素材门户 ──────────────────────────────────
    CUSTOMER_MEDIA_STORAGE_ROOT: str = "D:\\WORKSOURCE\\customer-media"
    CUSTOMER_MEDIA_PORTAL_ORIGIN: str = "https://media.leshine.cloud"
    CUSTOMER_MEDIA_MAX_FILE_MB: _PositiveInt = 500
    CUSTOMER_MEDIA_MAX_BATCH_GB: _PositiveInt = 20
    CUSTOMER_MEDIA_SESSION_DAYS: _PositiveInt = 30
    CUSTOMER_MEDIA_COOKIE_NAME: str = "leshine_media_session"
    # 内部预览链接 HMAC 密钥；留空时回退 JWT_SECRET_KEY，生产建议单独配置随机串。
    CUSTOMER_MEDIA_SIGN_SECRET: str = ""

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
    # 密钥轮换过渡期的旧密钥：报工扫码（外贸 ARK-P / 内贸 ARK-D，都在登录后端点）
    # 用当前密钥验不过时拿它兜底，让换钥前已打印的卡继续有效；
    # 免登录的进度码（ARK-DT）永远只认当前密钥。在制订单消化完后删除此配置即关闭兜底。
    QR_SIGN_SECRET_LEGACY: str = ""
    PRODUCTION_API_KEY: str = ""  # ACCIO WORK 调用报工接口的 API Key

    # ── WhatsApp Connector ───────────────────────────────
    WHATSAPP_CONNECTOR_BASE_URL: str = ""
    WHATSAPP_CONNECTOR_API_KEY: str = ""
    WHATSAPP_CONNECTOR_TIMEOUT_SECONDS: int = 30
    WHATSAPP_AUTO_SYNC_ENABLED: bool = True
    WHATSAPP_AUTO_SYNC_INTERVAL_MINUTES: int = 5
    WHATSAPP_AUTO_SYNC_BATCH_SIZE: int = 100
    WHATSAPP_SYNC_MESSAGES_PER_CHAT: int = 100

    # ── WhatsApp 实时翻译扩展（与 WhatsApp connector 完全隔离）──
    WHATSAPP_TRANSLATION_EXTENSION_ORIGIN: str = "chrome-extension://bnkecbkoidckffckbefjjcbchmngjobi"
    WHATSAPP_TRANSLATION_PRESET_NAME: str = "whatsapp_text_translation"
    WHATSAPP_TRANSLATION_PAIRING_TTL_MINUTES: _PositiveInt = 10
    WHATSAPP_TRANSLATION_DEVICE_TTL_DAYS: _PositiveInt = 180
    WHATSAPP_TRANSLATION_MAX_DEVICES_PER_USER: _PositiveInt = 5
    WHATSAPP_TRANSLATION_RATE_PER_MINUTE: _PositiveInt = 30
    WHATSAPP_TRANSLATION_DAILY_INPUT_CHARS: _PositiveInt = 200_000
    WHATSAPP_TRANSLATION_MAX_TEXT_CHARS: _PositiveInt = 4_000
    WHATSAPP_TRANSLATION_AI_TIMEOUT_SECONDS: _PositiveInt = 15
    WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION: str = "1.0.0"
    # ── 运行与自动化中心（健康检查仅允许由部署环境配置，不接受网页输入）────
    OPERATIONS_PROBE_TIMEOUT_SECONDS: float = 3.0
    OPERATIONS_CACHE_TTL_SECONDS: float = 20.0
    OPERATIONS_ALLOWED_HEALTH_HOSTS: str = "leshine.work,127.0.0.1,localhost"
    OPERATIONS_SOCIAL_MCP_HEALTH_URL: str = "https://leshine.work/mcp/social-customer/health"
    OPERATIONS_SHOPIFY_HEALTH_URL: str = ""
    OPERATIONS_OPENCLAW_HEALTH_URL: str = ""
    # JSON 数组：[{"id","name","category","environment","owner","management","health_url"}]
    # 只放无敏感参数的健康地址；展示时会自动去掉 query/userinfo。
    OPERATIONS_EXTERNAL_SERVICES_JSON: str = ""
    # {"shopify-sync":{"instance-01":{"token_hashes":"<sha256>","service_name":"..."}}}
    OPERATIONS_HEARTBEAT_TOKEN_HASHES_JSON: str = ""
    OPERATIONS_HEARTBEAT_INTERVAL_SECONDS: int = 60
    OPERATIONS_HEARTBEAT_MISSED_THRESHOLD: int = 3
    OPERATIONS_HEARTBEAT_MAX_INSTANCES_PER_SERVICE: int = 20
    OPERATIONS_HEARTBEAT_RATE_LIMIT_PER_MINUTE: int = 12
    OPERATIONS_HEARTBEAT_INSTANCE_RETIRE_HOURS: int = 24
    OPERATIONS_HEARTBEAT_RETENTION_DAYS: int = 7
    OPERATIONS_JOB_RUN_RETENTION_DAYS: int = 90
    OPERATIONS_ALERT_TIMEOUT_SECONDS: float = 10.0

    # ── Agent Runtime 控制面 / DSH Worker ─────────────────
    # 首次部署默认关闭；完成迁移、Worker 凭证与模型网关配置后按 Profile 灰度开启。
    AGENT_RUNTIME_ENABLED: bool = False
    AGENT_RUNTIME_DSH_ENABLED: bool = False
    AGENT_RUNTIME_COPILOT_ENABLED: bool = False
    AGENT_RUNTIME_REPURCHASE_ENABLED: bool = False
    AGENT_RUNTIME_SALES_SHADOW_ENABLED: bool = False
    AGENT_RUNTIME_REPURCHASE_BATCH_SIZE: _PositiveInt = 20
    AGENT_RUNTIME_WEB_SEARCH_ENABLED: bool = False
    AGENT_RUNTIME_BRAVE_SEARCH_API_KEY: str = ""
    AGENT_RUNTIME_PUBLIC_FETCH_MAX_BYTES: _PositiveInt = 1_000_000
    AGENT_RUNTIME_WORKER_LEASE_SECONDS: _PositiveInt = 180
    AGENT_RUNTIME_MAX_ACTIVE_PER_USER: _PositiveInt = 2
    AGENT_RUNTIME_MAX_STEPS_PER_RUN: _PositiveInt = 20
    AGENT_RUNTIME_RUN_TIMEOUT_SECONDS: _PositiveInt = 600
    AGENT_RUNTIME_RAW_EVENT_RETENTION_DAYS: _PositiveInt = 90
    AGENT_RUNTIME_SHADOW_SAMPLE_RATE: float = 0.0
    AGENT_RUNTIME_DAILY_TOKEN_BUDGET: _PositiveInt = 200_000
    # JSON: {"worker-instance-id": ["<sha256-of-bearer-token>"]}
    AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON: str = ""
    AGENT_RUNTIME_WORKER_RUNTIMES_JSON: str = ""
    # Run 委托 JWT 独立密钥；开发留空时回退 JWT_SECRET_KEY，生产必须显式配置。
    AGENT_RUNTIME_RUN_TOKEN_SECRET: str = ""

    # ── 微信小程序 ────────────────────────────────────────
    WX_MINI_APPID: str = ""  # 微信小程序 AppID
    WX_MINI_SECRET: str = ""  # 微信小程序 AppSecret
    # 小程序码指向的版本：release / trial / develop。
    # 正式版发布前设 trial（仅体验成员能扫开），发布后删掉此配置回落 release
    WX_MINI_ENV_VERSION: str = "release"

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
    # 发票 PDF 中文字体：部署/启动时强制预检，避免用户导出时才失败。
    PDF_CJK_FONT_PATH: str = "C:\\Windows\\Fonts\\msyh.ttc"


    @field_validator("WHATSAPP_TRANSLATION_EXTENSION_ORIGIN")
    @classmethod
    def _validate_whatsapp_translation_origin(cls, value: str) -> str:
        if not re.fullmatch(r"chrome-extension://[a-p]{32}", value):
            raise ValueError("WHATSAPP_TRANSLATION_EXTENSION_ORIGIN 必须是稳定的 32 位扩展 ID")
        return value

    @field_validator("WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION")
    @classmethod
    def _validate_whatsapp_translation_version(cls, value: str) -> str:
        segments = value.split(".")
        if len(segments) != 3 or any(not segment.isdigit() for segment in segments):
            raise ValueError("WHATSAPP_TRANSLATION_MIN_EXTENSION_VERSION 必须是三段数字版本号")
        return value
    @field_validator("CORS_ALLOW_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v):
        """支持 .env 逗号分隔字符串 (BaseSettings 默认只接受 JSON 数组)"""
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("AGENT_RUNTIME_SHADOW_SAMPLE_RATE")
    @classmethod
    def _validate_agent_shadow_rate(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("AGENT_RUNTIME_SHADOW_SAMPLE_RATE 必须在 0 到 1 之间")
        return value

    @field_validator("AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON")
    @classmethod
    def _validate_agent_worker_hashes(cls, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON 必须是 JSON 对象") from exc
        if not isinstance(mapping, dict):
            raise ValueError("AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON 必须是 JSON 对象")
        for worker_id, hashes in mapping.items():
            values = hashes if isinstance(hashes, list) else [hashes]
            if not worker_id or not values or any(
                not isinstance(item, str)
                or len(item) != 64
                or any(char not in string.hexdigits for char in item)
                for item in values
            ):
                raise ValueError("Worker token hash 必须是 64 位 SHA-256 十六进制字符串")
        return raw

    @field_validator("AGENT_RUNTIME_WORKER_RUNTIMES_JSON")
    @classmethod
    def _validate_agent_worker_runtimes(cls, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            mapping = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("AGENT_RUNTIME_WORKER_RUNTIMES_JSON 必须是 JSON 对象") from exc
        allowed = {"dsh", "openclaw", "native"}
        if not isinstance(mapping, dict) or any(
            not worker_id or not isinstance(runtimes, list) or not runtimes
            or any(item not in allowed for item in runtimes)
            for worker_id, runtimes in mapping.items()
        ):
            raise ValueError("Worker runtime 映射必须是非空 dsh/openclaw/native 数组")
        return raw

    @model_validator(mode="after")
    def _validate_production(self):
        """production 模式启动前校验关键安全配置"""
        if self.DESIGN_IMAGE_STALE_SECONDS <= self.DESIGN_IMAGE_LEASE_SECONDS:
            raise ValueError(
                "DESIGN_IMAGE_STALE_SECONDS 必须大于 DESIGN_IMAGE_LEASE_SECONDS"
            )
        if self.CUSTOMER_IMAGE_STALE_SECONDS <= self.CUSTOMER_IMAGE_LEASE_SECONDS:
            raise ValueError(
                "CUSTOMER_IMAGE_STALE_SECONDS must be greater than "
                "CUSTOMER_IMAGE_LEASE_SECONDS"
            )
        agent_profiles_enabled = any((
            self.AGENT_RUNTIME_COPILOT_ENABLED,
            self.AGENT_RUNTIME_REPURCHASE_ENABLED,
            self.AGENT_RUNTIME_SALES_SHADOW_ENABLED,
        ))
        if self.AGENT_RUNTIME_DSH_ENABLED and not self.AGENT_RUNTIME_ENABLED:
            raise ValueError("启用 DSH Runtime 前必须启用 AGENT_RUNTIME_ENABLED")
        if agent_profiles_enabled and not self.AGENT_RUNTIME_DSH_ENABLED:
            raise ValueError("启用首期 Agent Profile 前必须启用 AGENT_RUNTIME_DSH_ENABLED")
        if self.AGENT_RUNTIME_SALES_SHADOW_ENABLED and not self.AGENT_RUNTIME_WEB_SEARCH_ENABLED:
            raise ValueError("启用获客 Shadow 前必须启用 AGENT_RUNTIME_WEB_SEARCH_ENABLED")
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
        if not self.ARK_SALARY_ENCRYPTION_KEY:
            errors.append("ARK_SALARY_ENCRYPTION_KEY 必须显式配置（薪资身份证/银行卡加密）")
        if not self.ARK_SALARY_HASH_KEY:
            errors.append("ARK_SALARY_HASH_KEY 必须显式配置（薪资 PII 哈希匹配）")
        if self.AGENT_RUNTIME_ENABLED and len(self.AGENT_RUNTIME_RUN_TOKEN_SECRET) < 32:
            errors.append("启用 AGENT_RUNTIME 时必须配置至少 32 字符的独立 AGENT_RUNTIME_RUN_TOKEN_SECRET")
        if self.AGENT_RUNTIME_DSH_ENABLED and self.AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON in {"", "{}"}:
            errors.append("启用 DSH Runtime 时必须配置 AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON")
        if self.AGENT_RUNTIME_DSH_ENABLED and self.AGENT_RUNTIME_WORKER_RUNTIMES_JSON in {"", "{}"}:
            errors.append("启用 DSH Runtime 时必须配置 AGENT_RUNTIME_WORKER_RUNTIMES_JSON")
        if self.AGENT_RUNTIME_SALES_SHADOW_ENABLED and not self.AGENT_RUNTIME_BRAVE_SEARCH_API_KEY:
            errors.append("启用获客 Shadow 时必须配置 AGENT_RUNTIME_BRAVE_SEARCH_API_KEY")
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
