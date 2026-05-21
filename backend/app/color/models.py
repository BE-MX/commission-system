"""发色数字化 — SQLAlchemy ORM 模型"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ColorPalette(Base):
    """基础色号表（行业通用 + 莱莎自有）"""

    __tablename__ = "ark_color_palette"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_code = Column(String(20), nullable=False, comment="行业标准色号")
    brand_code = Column(String(50), nullable=True, comment="品牌特有编码")
    display_name = Column(String(100), nullable=False, comment="展示名称")
    display_name_en = Column(String(100), nullable=True, comment="英文名称")
    hex_code = Column(String(7), nullable=False, comment="HEX值")
    rgb_r = Column(SmallInteger, nullable=False)
    rgb_g = Column(SmallInteger, nullable=False)
    rgb_b = Column(SmallInteger, nullable=False)
    lab_l = Column(Numeric(6, 2), nullable=True, comment="LAB L*")
    lab_a = Column(Numeric(6, 2), nullable=True, comment="LAB a*")
    lab_b_val = Column(Numeric(6, 2), nullable=True, comment="LAB b*")
    hsl_h = Column(SmallInteger, nullable=True, comment="HSL色相")
    hsl_s = Column(Numeric(5, 2), nullable=True, comment="HSL饱和度")
    hsl_l = Column(Numeric(5, 2), nullable=True, comment="HSL亮度")
    undertone = Column(String(16), nullable=True, comment="warm/cool/neutral")
    luminance_level = Column(String(16), nullable=True, comment="明度级别")
    color_family = Column(String(16), nullable=False, comment="色族")
    pantone_tcx = Column(String(30), nullable=True, comment="最近Pantone TCX")
    pantone_delta_e = Column(Numeric(4, 2), nullable=True, comment="与Pantone色差")
    source = Column(String(32), nullable=False, default="industry")
    is_leshine_stock = Column(SmallInteger, nullable=False, default=0)
    peak_season = Column(String(64), nullable=True, comment="高峰季节")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("industry_code", "source", name="uk_industry_source"),
        Index("idx_palette_family", "color_family"),
        Index("idx_palette_hex", "hex_code"),
        Index("idx_palette_luminance", "luminance_level"),
    )

    # relationships
    blend_components = relationship("ColorBlendComponent", back_populates="palette", lazy="dynamic")
    swatch_images = relationship("ColorSwatchImage", back_populates="palette", lazy="dynamic")


class ColorBlend(Base):
    """混合色号表（多色混编/渐变/钢琴色）"""

    __tablename__ = "ark_color_blend"

    id = Column(Integer, primary_key=True, autoincrement=True)
    blend_code = Column(String(30), nullable=False, comment="混合编码")
    display_name = Column(String(100), nullable=False)
    display_name_en = Column(String(100), nullable=True)
    blend_type = Column(String(32), nullable=False, comment="piano/ombre/balayage/rooted/tri-blend/multi-blend")
    computed_hex = Column(String(7), nullable=True, comment="加权混合HEX")
    computed_lab_l = Column(Numeric(6, 2), nullable=True)
    computed_lab_a = Column(Numeric(6, 2), nullable=True)
    computed_lab_b = Column(Numeric(6, 2), nullable=True)
    source = Column(String(32), nullable=False)
    brand_name = Column(String(100), nullable=True, comment="品牌命名")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("blend_code", "source", name="uk_blend_source"),
        Index("idx_blend_type", "blend_type"),
    )

    components = relationship("ColorBlendComponent", back_populates="blend", lazy="dynamic",
                              cascade="all, delete-orphan", order_by="ColorBlendComponent.sort_order")
    swatch_images = relationship("ColorSwatchImage", back_populates="blend", lazy="dynamic")


class ColorBlendComponent(Base):
    """混合色成分关联"""

    __tablename__ = "ark_color_blend_component"

    id = Column(Integer, primary_key=True, autoincrement=True)
    blend_id = Column(Integer, ForeignKey("ark_color_blend.id", ondelete="CASCADE"), nullable=False)
    palette_id = Column(Integer, ForeignKey("ark_color_palette.id", ondelete="RESTRICT"), nullable=False)
    position = Column(String(16), nullable=False, default="even",
                      comment="root/mid/end/highlight/even")
    weight = Column(Numeric(4, 2), nullable=False, default=0.50)
    sort_order = Column(SmallInteger, nullable=False, default=0)

    __table_args__ = (
        Index("idx_blend_component_blend", "blend_id"),
    )

    blend = relationship("ColorBlend", back_populates="components")
    palette = relationship("ColorPalette", back_populates="blend_components")


class CompetitorColorWatch(Base):
    """竞品色号监控"""

    __tablename__ = "ark_competitor_color_watch"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand = Column(String(50), nullable=False)
    color_code = Column(String(30), nullable=False)
    color_name = Column(String(100), nullable=True)
    product_url = Column(String(500), nullable=True)
    extracted_hex = Column(String(7), nullable=True)
    extracted_lab_l = Column(Numeric(6, 2), nullable=True)
    extracted_lab_a = Column(Numeric(6, 2), nullable=True)
    extracted_lab_b = Column(Numeric(6, 2), nullable=True)
    nearest_palette_id = Column(Integer, nullable=True)
    match_delta_e = Column(Numeric(4, 2), nullable=True)
    social_mentions_30d = Column(Integer, nullable=False, default=0)
    popularity_score = Column(Numeric(5, 2), nullable=False, default=0)
    first_seen = Column(Date, nullable=False)
    last_seen = Column(Date, nullable=False)
    is_new_launch = Column(SmallInteger, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("brand", "color_code", name="uk_brand_code"),
        Index("idx_comp_color_popularity", "popularity_score"),
        Index("idx_comp_color_first_seen", "first_seen"),
    )


class ColorTrendData(Base):
    """色彩趋势时序数据"""

    __tablename__ = "ark_color_trend_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    color_family = Column(String(16), nullable=False)
    data_source = Column(String(32), nullable=False)
    period_date = Column(Date, nullable=False)
    period_type = Column(String(16), nullable=False, default="weekly")
    raw_value = Column(Numeric(10, 2), nullable=False)
    normalized_score = Column(Numeric(5, 2), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("color_family", "data_source", "period_date", "period_type",
                         name="uk_family_source_date"),
        Index("idx_trend_period", "period_date"),
    )


class ColorSwatchImage(Base):
    """色板图生成记录"""

    __tablename__ = "ark_color_swatch_image"

    id = Column(Integer, primary_key=True, autoincrement=True)
    palette_id = Column(Integer, ForeignKey("ark_color_palette.id", ondelete="SET NULL"), nullable=True)
    blend_id = Column(Integer, ForeignKey("ark_color_blend.id", ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, nullable=False)
    model_used = Column(String(50), nullable=False)
    image_path = Column(String(500), nullable=False)
    image_url = Column(String(500), nullable=True)
    target_hex = Column(String(7), nullable=False)
    actual_hex = Column(String(7), nullable=True)
    delta_e = Column(Numeric(4, 2), nullable=True)
    pass_check = Column(SmallInteger, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    retry_count = Column(SmallInteger, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_swatch_palette", "palette_id"),
        Index("idx_swatch_blend", "blend_id"),
        Index("idx_swatch_status", "status"),
    )

    palette = relationship("ColorPalette", back_populates="swatch_images")
    blend = relationship("ColorBlend", back_populates="swatch_images")


class PantoneReference(Base):
    """Pantone 参考色库"""

    __tablename__ = "ark_pantone_reference"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pantone_code = Column(String(20), nullable=False, unique=True)
    pantone_name = Column(String(100), nullable=True)
    hex_code = Column(String(7), nullable=False)
    rgb_r = Column(SmallInteger, nullable=False)
    rgb_g = Column(SmallInteger, nullable=False)
    rgb_b = Column(SmallInteger, nullable=False)
    lab_l = Column(Numeric(6, 2), nullable=True)
    lab_a = Column(Numeric(6, 2), nullable=True)
    lab_b_val = Column(Numeric(6, 2), nullable=True)
    collection = Column(String(16), nullable=False, default="tcx")

    __table_args__ = (
        Index("idx_pantone_hex", "hex_code"),
    )
