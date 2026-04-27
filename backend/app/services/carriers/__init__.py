"""物流商适配器注册"""

from app.core.config import get_settings
from app.services.carriers.base import CarrierAdapter

_settings = get_settings()

CARRIER_ADAPTERS: dict[str, CarrierAdapter] = {}


def _init_adapters():
    from app.services.carriers.dhl import DHLAdapter
    from app.services.carriers.fedex import FedExAdapter

    if _settings.DHL_API_USERNAME:
        CARRIER_ADAPTERS["DHL"] = DHLAdapter(
            username=_settings.DHL_API_USERNAME,
            password=_settings.DHL_API_PASSWORD,
            env=_settings.DHL_API_ENV,
        )
    if _settings.FEDEX_CLIENT_ID:
        CARRIER_ADAPTERS["FEDEX"] = FedExAdapter(
            client_id=_settings.FEDEX_CLIENT_ID,
            client_secret=_settings.FEDEX_CLIENT_SECRET,
            sandbox=_settings.FEDEX_SANDBOX.lower() == "true"
            if isinstance(_settings.FEDEX_SANDBOX, str)
            else bool(_settings.FEDEX_SANDBOX),
        )


def get_adapter(carrier: str) -> CarrierAdapter | None:
    if not CARRIER_ADAPTERS:
        _init_adapters()
    return CARRIER_ADAPTERS.get(carrier.upper())
