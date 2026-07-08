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

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    industry_code = Column(String(20), nullable=False, comment="行业标准色号，如 #1, #613, #1C/18")
    brand_code = Column(String(50), nullable=True, comment="品牌特有编码，如 Bellami的Vanilla Latte")
    display_name = Column(String(100), nullable=False, comment="展示名称（中英双语）")
    display_name_en = Column(String(100), nullable=True, comment="英文名称")
    hex_code = Column(String(7), nullable=False, comment="HEX值，如 #6B5A52")
    rgb_r = Column(SmallInteger, nullable=False, comment="R 0-255")
    rgb_g = Column(SmallInteger, nullable=False, comment="G 0-255")
    rgb_b = Column(SmallInteger, nullable=False, comment="B 0-255")
    lab_l = Column(Numeric(6, 2), nullable=True, comment="LAB L*（CIE LAB - L* (明度 0-100)）")
    lab_a = Column(Numeric(6, 2), nullable=True, comment="LAB a*（CIE LAB - a* (绿红 -128~127)）")
    lab_b_val = Column(Numeric(6, 2), nullable=True, comment="LAB b*（CIE LAB - b* (蓝黄 -128~127)）")
    hsl_h = Column(SmallInteger, nullable=True, comment="HSL色相 0-360")
    hsl_s = Column(Numeric(5, 2), nullable=True, comment="HSL饱和度 0-100")
    hsl_l = Column(Numeric(5, 2), nullable=True, comment="HSL亮度 0-100")
    undertone = Column(String(16), nullable=True, comment="warm/cool/neutral")
    luminance_level = Column(String(16), nullable=True, comment="明度级别（low/medium-low/medium/medium-high/high/very-high）")
    color_family = Column(String(16), nullable=False, comment="色族（black/brown/blonde/red/silver/vibrant）")
    pantone_tcx = Column(String(30), nullable=True, comment="最近Pantone TCX色号")
    pantone_delta_e = Column(Numeric(4, 2), nullable=True, comment="与Pantone色差（与Pantone的ΔE2000值）")
    source = Column(String(32), nullable=False, default="industry", comment="industry/bellami/luxy/great_lengths/leshine/organic_hair")
    is_leshine_stock = Column(SmallInteger, nullable=False, default=0, comment="0=否,1=是莱莎现有库存色")
    peak_season = Column(String(64), nullable=True, comment="高峰季节（高峰销售季节 spring/summer/autumn/winter 逗号分隔）")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("industry_code", "source", name="uk_industry_source"),
        Index("idx_palette_family", "color_family"),
        Index("idx_palette_hex", "hex_code"),
        Index("idx_palette_luminance", "luminance_level"),
        {"comment": "色板数据库-基础色号表"},
    )

    # relationships
    blend_components = relationship("ColorBlendComponent", back_populates="palette", lazy="dynamic")
    swatch_images = relationship("ColorSwatchImage", back_populates="palette", lazy="dynamic")


class ColorBlend(Base):
    """混合色号表（多色混编/渐变/钢琴色）"""

    __tablename__ = "ark_color_blend"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    blend_code = Column(String(30), nullable=False, comment="混合编码，如 #8/8/60, #1C/18/46")
    display_name = Column(String(100), nullable=False, comment="展示名称")
    display_name_en = Column(String(100), nullable=True, comment="英文名称")
    blend_type = Column(String(32), nullable=False, comment="piano/ombre/balayage/rooted/tri-blend/multi-blend")
    computed_hex = Column(String(7), nullable=True, comment="加权混合HEX（加权混合计算的综合HEX）")
    computed_lab_l = Column(Numeric(6, 2), nullable=True, comment="加权混合色 LAB L*")
    computed_lab_a = Column(Numeric(6, 2), nullable=True, comment="加权混合色 LAB a*")
    computed_lab_b = Column(Numeric(6, 2), nullable=True, comment="加权混合色 LAB b*")
    source = Column(String(32), nullable=False, comment="bellami/luxy/great_lengths/leshine/organic_hair/custom")
    brand_name = Column(String(100), nullable=True, comment="品牌命名，如 Vanilla Latte")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("blend_code", "source", name="uk_blend_source"),
        Index("idx_blend_type", "blend_type"),
        {"comment": "色板数据库-混合色号表"},
    )

    components = relationship("ColorBlendComponent", back_populates="blend", lazy="dynamic",
                              cascade="all, delete-orphan", order_by="ColorBlendComponent.sort_order")
    swatch_images = relationship("ColorSwatchImage", back_populates="blend", lazy="dynamic")


class ColorBlendComponent(Base):
    """混合色成分关联"""

    __tablename__ = "ark_color_blend_component"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    blend_id = Column(Integer, ForeignKey("ark_color_blend.id", ondelete="CASCADE"), nullable=False, comment="关联混合色")
    palette_id = Column(Integer, ForeignKey("ark_color_palette.id", ondelete="RESTRICT"), nullable=False, comment="关联基础色")
    position = Column(String(16), nullable=False, default="even",
                      comment="root/mid/end/highlight/even")
    weight = Column(Numeric(4, 2), nullable=False, default=0.50, comment="混合权重，同一blend总和=1")
    sort_order = Column(SmallInteger, nullable=False, default=0, comment="从发根到发尾排序")

    __table_args__ = (
        Index("idx_blend_component_blend", "blend_id"),
        {"comment": "混合色成分关联"},
    )

    blend = relationship("ColorBlend", back_populates="components")
    palette = relationship("ColorPalette", back_populates="blend_components")


class CompetitorColorWatch(Base):
    """竞品色号监控"""

    __tablename__ = "ark_competitor_color_watch"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    brand = Column(String(50), nullable=False, comment="竞品品牌名")
    color_code = Column(String(30), nullable=False, comment="竞品色号编码")
    color_name = Column(String(100), nullable=True, comment="竞品色号名称")
    product_url = Column(String(500), nullable=True, comment="产品页URL")
    extracted_hex = Column(String(7), nullable=True, comment="OpenCV提取的主色调HEX")
    extracted_lab_l = Column(Numeric(6, 2), nullable=True, comment="提取主色 LAB L*")
    extracted_lab_a = Column(Numeric(6, 2), nullable=True, comment="提取主色 LAB a*")
    extracted_lab_b = Column(Numeric(6, 2), nullable=True, comment="提取主色 LAB b*")
    nearest_palette_id = Column(Integer, nullable=True, comment="莱莎色库最近色号ID")
    match_delta_e = Column(Numeric(4, 2), nullable=True, comment="匹配色差")
    social_mentions_30d = Column(Integer, nullable=False, default=0, comment="近30天社媒提及次数")
    popularity_score = Column(Numeric(5, 2), nullable=False, default=0, comment="综合热度分0-100")
    first_seen = Column(Date, nullable=False, comment="首次发现日期")
    last_seen = Column(Date, nullable=False, comment="最近一次确认在售")
    is_new_launch = Column(SmallInteger, nullable=False, default=0, comment="0=否,1=近期新品")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        UniqueConstraint("brand", "color_code", name="uk_brand_code"),
        Index("idx_comp_color_popularity", "popularity_score"),
        Index("idx_comp_color_first_seen", "first_seen"),
        {"comment": "竞品色号监控"},
    )


class ColorTrendData(Base):
    """色彩趋势时序数据"""

    __tablename__ = "ark_color_trend_data"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    color_family = Column(String(16), nullable=False, comment="black/brown/blonde/red/silver/vibrant")
    data_source = Column(String(32), nullable=False, comment="sales/social_xpoz/google_trends/competitor_launch/pantone")
    period_date = Column(Date, nullable=False, comment="数据日期")
    period_type = Column(String(16), nullable=False, default="weekly", comment="daily/weekly/monthly")
    raw_value = Column(Numeric(10, 2), nullable=False, comment="原始值（销量/提及次数/搜索指数）")
    normalized_score = Column(Numeric(5, 2), nullable=True, comment="归一化分数0-100")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        UniqueConstraint("color_family", "data_source", "period_date", "period_type",
                         name="uk_family_source_date"),
        Index("idx_trend_period", "period_date"),
        {"comment": "色彩趋势时序数据"},
    )


class ColorSwatchImage(Base):
    """色板图生成记录"""

    __tablename__ = "ark_color_swatch_image"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    palette_id = Column(Integer, ForeignKey("ark_color_palette.id", ondelete="SET NULL"), nullable=True, comment="基础色号")
    blend_id = Column(Integer, ForeignKey("ark_color_blend.id", ondelete="SET NULL"), nullable=True, comment="混合色号")
    prompt = Column(Text, nullable=False, comment="生成Prompt")
    model_used = Column(String(50), nullable=False, comment="gpt-image-2/sd-xl/hairdiffusion")
    image_path = Column(String(500), nullable=False, comment="生成图片存储路径")
    image_url = Column(String(500), nullable=True, comment="图片访问URL")
    target_hex = Column(String(7), nullable=False, comment="目标HEX")
    actual_hex = Column(String(7), nullable=True, comment="实际提取主色HEX")
    delta_e = Column(Numeric(4, 2), nullable=True, comment="目标与实际的ΔE2000")
    pass_check = Column(SmallInteger, nullable=True, comment="0=否,1=通过色差校验")
    status = Column(String(32), nullable=False, default="pending", comment="pending/generating/completed/failed/rejected")
    retry_count = Column(SmallInteger, nullable=False, default=0, comment="生成重试次数")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_swatch_palette", "palette_id"),
        Index("idx_swatch_blend", "blend_id"),
        Index("idx_swatch_status", "status"),
        {"comment": "色板图生成记录"},
    )

    palette = relationship("ColorPalette", back_populates="swatch_images")
    blend = relationship("ColorBlend", back_populates="swatch_images")


class PantoneReference(Base):
    """Pantone 参考色库"""

    __tablename__ = "ark_pantone_reference"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键")
    pantone_code = Column(String(20), nullable=False, unique=True, comment="Pantone TCX编码，如 19-4004 TCX")
    pantone_name = Column(String(100), nullable=True, comment="Pantone英文名称")
    hex_code = Column(String(7), nullable=False, comment="HEX色值")
    rgb_r = Column(SmallInteger, nullable=False, comment="RGB R 0-255")
    rgb_g = Column(SmallInteger, nullable=False, comment="RGB G 0-255")
    rgb_b = Column(SmallInteger, nullable=False, comment="RGB B 0-255")
    lab_l = Column(Numeric(6, 2), nullable=True, comment="LAB L*")
    lab_a = Column(Numeric(6, 2), nullable=True, comment="LAB a*")
    lab_b_val = Column(Numeric(6, 2), nullable=True, comment="LAB b*")
    collection = Column(String(16), nullable=False, default="tcx", comment="tcx/tpg/coated/uncoated")

    __table_args__ = (
        Index("idx_pantone_hex", "hex_code"),
        {"comment": "Pantone参考色库"},
    )
