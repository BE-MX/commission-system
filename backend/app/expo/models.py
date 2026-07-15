"""SQLAlchemy models for the expo AI wig try-on module (045 migration)."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class ExpoCustomer(Base):
    """展会试戴客户（注册即建档）。consent_at 非空才允许存照片。"""

    __tablename__ = "ark_expo_customers"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    name = Column(String(64), nullable=False, comment="称呼，如 陈女士")
    phone = Column(String(32), nullable=False, comment="手机号，用于短信补发效果图链接")
    wechat_id = Column(String(64), nullable=True, comment="微信号（可选）")
    primary_need = Column(String(32), nullable=False, default="volume", comment="volume/gray_cover/style_change")
    style_pref = Column(String(32), nullable=True, comment="知性优雅/减龄轻盈/自然日常")
    consent_at = Column(DateTime, nullable=True, comment="拍照存储同意时间，非空才允许存照片")
    expo_code = Column(String(64), nullable=False, default="", comment="届次标记，如 2026-08-hangzhou")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    sessions = relationship("ExpoSession", back_populates="customer", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ark_expo_customers_phone", "phone"),
        Index("idx_ark_expo_customers_expo", "expo_code"),
        {"comment": "展会AI试戴-客户建档表（注册即建档，consent_at 非空才允许存照片）"},
    )


class ExpoWig(Base):
    """发型库。series 驱动至臻锚点规则；fit_tags 驱动匹配引擎。"""

    __tablename__ = "ark_expo_wigs"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    model_no = Column(String(64), nullable=False, unique=True, comment="如 LS-D201")
    name = Column(String(128), nullable=False, comment="如 轻盈波波 · 自然黑")
    series = Column(String(16), nullable=False, default="classic", comment="classic/zhizhen")
    product_id = Column(BigInteger, nullable=True, comment="okki_products.product_id 可空")
    cover_path = Column(String(512), nullable=True, comment="封面图相对路径")
    angle_photos = Column(JSON, nullable=True, comment="多角度参考图路径列表")
    wig_description = Column(Text, nullable=True, comment="喂给合成 prompt 的款式描述")
    composite_prompt = Column(Text, nullable=True, comment="该款个性化合成 prompt 片段")
    fit_tags = Column(JSON, nullable=True, comment="{gender,face_shapes[],skin_depths[],undertones[],age_ranges[],needs[],styles[],length,occupations[],life_scenes[],sell_positions[],not_suitable[]}（后四项销售参考，不参与匹配）")
    selling_points = Column(Text, nullable=True, comment="卖点，话术生成引用")
    evidence_refs = Column(JSON, nullable=True, comment="6个月对比素材路径等证据引用")
    priority = Column(Integer, nullable=False, default=0, comment="人工权重，同评级内小幅折算加分/平手决胜")
    must_recommend = Column(SmallInteger, nullable=False, default=0, comment="1=主推(置顶推荐列表最前,仍按性别过滤);0=否")
    is_active = Column(Integer, nullable=False, default=1, comment="1=启用,0=停用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (Index("idx_ark_expo_wigs_active", "is_active"), {"comment": "展会AI试戴-发型库（fit_tags 驱动匹配引擎）"})


class ExpoHairColor(Base):
    """发色库（048 迁移）。参照发型库独立维护：色板图 + 颜色描述直接喂给合成管线。"""

    __tablename__ = "ark_expo_hair_colors"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    code = Column(String(64), nullable=False, unique=True, comment="色号，如 1B / 613")
    name = Column(String(128), nullable=False, comment="如 自然黑")
    hex_code = Column(String(16), nullable=True, comment="UI 色块展示，可由色板图自动提取")
    swatch_path = Column(String(512), nullable=True, comment="色板图相对路径，随合成请求送入模型")
    color_description = Column(Text, nullable=True, comment="喂给合成 prompt 的颜色描述")
    priority = Column(Integer, nullable=False, default=0, comment="人工权重，kiosk 排序用")
    is_active = Column(Integer, nullable=False, default=1, comment="1=启用,0=停用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (Index("idx_ark_expo_hair_colors_active", "is_active"), {"comment": "展会AI试戴-发色库（色板图+颜色描述喂给合成管线）"})


class ExpoWigColor(Base):
    """发型×发色组合的三角度参考图（072 迁移）。

    一行=一个 (wig_id, hair_color_id) 组合；angle_photos 是该发型该发色的三角度实拍图组，
    合成时按选择匹配到唯一颜色的这组图，参考图本身即目标色（取代文字/色板图上色）。
    稀疏存储：只存备了图的组合；「原色」用发型自身 angle_photos，不在此表。
    """

    __tablename__ = "ark_expo_wig_colors"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    wig_id = Column(BigInteger, ForeignKey("ark_expo_wigs.id", ondelete="CASCADE"), nullable=False, comment="发型 ark_expo_wigs.id")
    hair_color_id = Column(BigInteger, ForeignKey("ark_expo_hair_colors.id", ondelete="CASCADE"), nullable=False, comment="发色 ark_expo_hair_colors.id")
    angle_photos = Column(JSON, nullable=True, comment="该发型该发色的三角度参考图路径列表")
    cover_path = Column(String(512), nullable=True, comment="缩略图相对路径，默认取首张")
    is_active = Column(SmallInteger, nullable=False, default=1, comment="1=启用,0=停用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (
        Index("idx_ark_expo_wig_colors_wig", "wig_id"),
        UniqueConstraint("wig_id", "hair_color_id", name="uq_ark_expo_wig_colors_pair"),
        {"comment": "展会AI试戴-发型×发色组合三角度参考图（合成按选择匹配唯一颜色图组）"},
    )


class ExpoScript(Base):
    """话术卡库 — 内贸营销策略 v2 / 直播话术 v4 的结构化落点。"""

    __tablename__ = "ark_expo_scripts"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    script_type = Column(String(32), nullable=False, comment="opener/demo/objection/closer/faq")
    track = Column(String(16), nullable=False, default="emotional", comment="emotional/rational/identity")
    title = Column(String(128), nullable=False, comment="话术标题")
    audience_tags = Column(JSON, nullable=True, comment="人群标签，如 ['敏感肌','长期佩戴','心动至臻']")
    content = Column(Text, nullable=False, comment="话术正文")
    evidence_points = Column(JSON, nullable=True, comment="可引用的硬证据 key 列表")
    source_version = Column(String(16), nullable=False, default="v4", comment="话术来源版本，如 v4=直播话术v4")
    is_active = Column(Integer, nullable=False, default=1, comment="1=启用,0=停用")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    __table_args__ = (Index("idx_ark_expo_scripts_type", "script_type", "is_active"), {"comment": "展会AI试戴-话术卡库"})


class ExpoSession(Base):
    """一次拍照一个会话。analysis_json.internal 仅销售端可见（隐私红线）。"""

    __tablename__ = "ark_expo_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(BigInteger, ForeignKey("ark_expo_customers.id", ondelete="CASCADE"), nullable=False, comment="关联展会客户ID")
    mode = Column(String(16), nullable=False, default="tryon", comment="tryon=AI换发试戴 / scene=佩戴实拍场景效果图")
    photo_path = Column(String(512), nullable=False, comment="客户原始拍照路径")
    analysis_json = Column(JSON, nullable=True, comment="AI面容分析结果JSON；internal 内部字段（发量/头皮判断等）仅销售端可见，不进客户共享屏")
    matched_wig_ids = Column(JSON, nullable=True, comment="全量排序后的 wig id 列表（换一批取后位）")
    strategy_json = Column(JSON, nullable=True, comment="双轨话术：opener/followup/objections")
    status = Column(String(16), nullable=False, default="pending", comment="pending/analyzed/generating/done/failed")
    error_message = Column(Text, nullable=True, comment="失败错误信息")
    operator_user_id = Column(Integer, nullable=True, comment="展位登录的销售 ark_users.id")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    customer = relationship("ExpoCustomer", back_populates="sessions")
    results = relationship("ExpoResult", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_ark_expo_sessions_customer", "customer_id"),
        Index("idx_ark_expo_sessions_status", "status"),
        {"comment": "展会AI试戴-会话表（一次拍照一个会话）"},
    )


class ExpoResult(Base):
    """一张效果图一条。short_code 供扫码带走。"""

    __tablename__ = "ark_expo_results"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    session_id = Column(BigInteger, ForeignKey("ark_expo_sessions.id", ondelete="CASCADE"), nullable=False, comment="关联会话ID（ark_expo_sessions.id）")
    wig_id = Column(BigInteger, ForeignKey("ark_expo_wigs.id"), nullable=True, comment="scene 模式为空")
    hair_color_json = Column(JSON, nullable=True, comment="发色快照（048 起 hair_color_id/code/name/hex/swatch_path/description；历史行为 palette 旧形态）")
    scene_json = Column(JSON, nullable=True, comment="scene 模式的场景快照（key/label）")
    image_path = Column(String(512), nullable=True, comment="效果图相对路径")
    gen_ms = Column(Integer, nullable=True, comment="生成耗时（毫秒）")
    status = Column(String(16), nullable=False, default="pending", comment="pending/generating/done/failed")
    reaction = Column(String(16), nullable=True, comment="loved/soso")
    short_code = Column(String(16), nullable=True, comment="分享短码")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    session = relationship("ExpoSession", back_populates="results")
    wig = relationship("ExpoWig")

    __table_args__ = (
        Index("idx_ark_expo_results_session", "session_id"),
        Index("idx_ark_expo_results_share", "short_code"),
        {"comment": "展会AI试戴-效果图表（一张效果图一条，short_code 供扫码带走）"},
    )


class ExpoFeedback(Base):
    """销售反馈。intent_level 直通客户机会台分级口径。"""

    __tablename__ = "ark_expo_feedback"

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment="主键")
    customer_id = Column(BigInteger, ForeignKey("ark_expo_customers.id", ondelete="CASCADE"), nullable=False, comment="关联展会客户ID")
    session_id = Column(BigInteger, nullable=True, comment="关联会话ID（可空，未拍照也可反馈）")
    sales_user_id = Column(Integer, nullable=False, comment="反馈销售 ark_users.id")
    intent_level = Column(String(4), nullable=False, comment="A/B/C/D")
    notes = Column(Text, nullable=True, comment="销售备注")
    next_action = Column(String(64), nullable=True, comment="如 约到店复试/加微信跟进")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, comment="创建时间")

    __table_args__ = (
        Index("idx_ark_expo_feedback_customer", "customer_id"),
        Index("idx_ark_expo_feedback_intent", "intent_level"),
        {"comment": "展会AI试戴-销售反馈表（intent_level 直通客户机会台分级口径）"},
    )
