"""SQLAlchemy 引擎、Session 配置"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.commission_db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
    # SQLAlchemy 的 IntegrityError/DataError 文案里**默认带完整的 INSERT 参数元组**，
    # 而项目里到处是 `except ... logger.warning(..., exc)` + `print(flush=True)`（红线 6）。
    # 薪资模块一条 INSERT 就带着身份证密文和 HMAC 哈希，一旦某行触发 MySQL 1406
    # （部门名超 VARCHAR(64)）这些值就明文躺进 NSSM 的 service.log。
    # 身份证号空间小、哈希密钥全库共用，哈希落进明文日志同样算泄漏。
    # echo=False 挡不住异常文案，只有这个开关能。（2026-08-07 对抗性审查实测）
    hide_parameters=True,
)


@event.listens_for(engine, "connect")
def _set_mysql_session_timezone(dbapi_connection, _connection_record) -> None:
    """每个连接都固定为北京时区，保证 NOW()/CURRENT_TIMESTAMP 口径一致。"""
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SET time_zone = '+08:00'")

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖注入：获取数据库 Session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
