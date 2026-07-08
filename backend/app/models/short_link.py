"""短链接 ORM 模型"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Index, func

from app.core.database import Base


class ArkShortLink(Base):
    """短链接记录表"""
    __tablename__ = "ark_short_links"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    short_code = Column(String(8), unique=True, nullable=False, comment="短码（6位 MD5 前缀，预留 2 位扩展）")
    original_url = Column(Text, nullable=False, comment="原始 URL")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="生成时间")
    click_count = Column(Integer, nullable=False, server_default="0", comment="点击次数")

    __table_args__ = (
        Index("idx_short_code", "short_code"),
        {"comment": "短链接记录表"},
    )
