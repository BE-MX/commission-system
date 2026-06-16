"""Print sanitized database settings used by the backend runtime."""

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    password_state = "empty" if not settings.COMMISSION_DB_PASSWORD else f"{len(settings.COMMISSION_DB_PASSWORD)} chars"
    print(
        "DB config:"
        f" host={settings.COMMISSION_DB_HOST}"
        f" port={settings.COMMISSION_DB_PORT}"
        f" user={settings.COMMISSION_DB_USER}"
        f" database={settings.COMMISSION_DB_NAME}"
        f" password={password_state}"
    )


if __name__ == "__main__":
    main()
