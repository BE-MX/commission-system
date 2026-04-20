"""环境变量配置（Pydantic Settings）"""

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

    @property
    def commission_db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.COMMISSION_DB_USER}:{self.COMMISSION_DB_PASSWORD}"
            f"@{self.COMMISSION_DB_HOST}:{self.COMMISSION_DB_PORT}/{self.COMMISSION_DB_NAME}"
            "?charset=utf8mb4"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
