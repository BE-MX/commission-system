"""物流商适配器注册"""

from app.core.config import get_settings
from app.services.carriers.base import CarrierAdapter

CARRIER_ADAPTERS: dict[str, CarrierAdapter] = {}


def _init_adapters():
    from app.services.carriers.dhl import DHLAdapter
    from app.services.carriers.fedex import FedExAdapter

    settings = get_settings()  # 在初始化时获取配置，确保环境变量已加载

    if settings.DHL_API_USERNAME:
        CARRIER_ADAPTERS["DHL"] = DHLAdapter(
            username=settings.DHL_API_USERNAME,
            password=settings.DHL_API_PASSWORD,
            env=settings.DHL_API_ENV,
        )
    if settings.FEDEX_CLIENT_ID:
        CARRIER_ADAPTERS["FEDEX"] = FedExAdapter(
            client_id=settings.FEDEX_CLIENT_ID,
            client_secret=settings.FEDEX_CLIENT_SECRET,
            sandbox=settings.FEDEX_SANDBOX.lower() == "true"
            if isinstance(settings.FEDEX_SANDBOX, str)
            else bool(settings.FEDEX_SANDBOX),
        )


def get_adapter(carrier: str) -> CarrierAdapter | None:
    if not CARRIER_ADAPTERS:
        _init_adapters()
    return CARRIER_ADAPTERS.get(carrier.upper())
