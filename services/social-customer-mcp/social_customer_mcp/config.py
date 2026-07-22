"""Environment-only configuration for the standalone MCP service."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secrets are intentionally required and have no defaults."""

    db_url: SecretStr = Field(description="SQLAlchemy URL for the read-only lsordertest database")
    token: SecretStr = Field(min_length=32, description="Bearer token accepted by the MCP endpoint")
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default=["leshine.work", "www.leshine.work", "127.0.0.1:8100", "localhost:8100"]
    )
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["https://leshine.work", "https://www.leshine.work"]
    )

    model_config = SettingsConfigDict(
        env_prefix="SOCIAL_CUSTOMER_MCP_",
        extra="ignore",
    )

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
