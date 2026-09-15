"""Add expo photo preprocessing and beautify prompt versions."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from datetime import datetime


revision = "146_expo_beautify_prompt"
down_revision = "145_domestic_order_guest"
branch_labels = None
depends_on = None


INITIAL_PROMPT = """请以我上传的客户原始照片为基础，进行“强美颜·焕颜级”人像精修，输出一张真实摄影质感的照片。

【人物保真】
保持原人物身份和辨识度，保留本人的主要五官特征和成熟气质。保持原图的表情、姿势、发型、服装、饰品、背景、拍摄角度和构图。

【皮肤精修】
进行较强力度的磨皮与祛瑕，淡化痘印、色斑和肤色不均，同时保留细微皮肤纹理。
提亮肤色，使肤色通透、均匀、自然，脸部与颈部肤色协调。
减轻额头和鼻部油光，保留柔和自然的皮肤光泽。
明显淡化黑眼圈、眼袋、抬头纹、眼周细纹和法令纹，保留必要的表情结构。

【脸型修饰】
明显收窄脸颊，适度瘦脸，修顺下颌线，让面部轮廓更加紧致流畅。
适度修饰下巴，保持自然比例，避免过尖下巴、夸张V脸和不自然的面部凹陷。

【五官美化】
适度放大并提亮双眼，保留原本眼型，使眼神更清晰有神。
整理眉形，保留自然眉毛质感；轻微增强睫毛。
精细修饰鼻部轮廓和明暗，让鼻形更精致，同时保留原有特征。
柔化唇纹，均匀唇色，呈现自然精致的玫瑰色双唇。
加入适量自然腮红和柔和高光，提升气色和立体感。

【整体效果】
美颜程度要明显，呈现光洁、明亮、紧致、精致的专业人像修图效果。
保持真实皮肤质感与人物辨识度，避免塑料皮肤、蜡像感、过度美白、夸张大眼、网红模板脸，以及变成另一个人。
不要改变服装花纹、饰品或背景，不要添加文字、水印、边框。

当美颜强度与人物辨识度发生冲突时，以人物辨识度、主要五官特征和成熟气质为优先，降低局部修饰幅度。保持眼距及主要五官的相对位置，不改变表情。不得通过改变发际线、头发体积、饰品形状或背景线条来实现瘦脸。保留具有辨识度的个人特征，不把人物重塑为统一模板脸。"""


def upgrade():
    op.create_table(
        "ark_expo_beautify_prompt_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(80), nullable=False, comment="美颜提示词版本名称"),
        sa.Column("prompt_text", mysql.LONGTEXT(), nullable=False, comment="美颜图片编辑提示词"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft", comment="draft/published/archived"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1", comment="乐观锁修订号"),
        sa.Column("published_slot", sa.Integer(), nullable=True, comment="当前发布版本为1，其余NULL"),
        sa.Column("updated_by", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=True),
        sa.Column("published_by", mysql.INTEGER(unsigned=True), sa.ForeignKey("ark_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_expo_beautify_prompt_name"),
        sa.UniqueConstraint("published_slot", name="uq_expo_beautify_published"),
        comment="展会AI试戴-美颜预处理提示词版本",
    )
    op.create_index("idx_expo_beautify_prompt_status", "ark_expo_beautify_prompt_versions", ["status"])

    op.add_column("ark_expo_sessions", sa.Column(
        "photo_processing_mode", sa.String(16), nullable=False, server_default="original",
        comment="original=原照片 / beauty=先美颜",
    ))
    op.add_column("ark_expo_sessions", sa.Column("client_request_id", sa.String(64), nullable=True, comment="客户端建会话幂等键"))
    op.add_column("ark_expo_sessions", sa.Column("request_hash", sa.String(64), nullable=True, comment="建会话请求内容摘要"))
    op.create_unique_constraint(
        "uq_expo_session_customer_request", "ark_expo_sessions", ["customer_id", "client_request_id"],
    )
    op.add_column("ark_expo_sessions", sa.Column(
        "beautify_status", sa.String(16), nullable=False, server_default="skipped",
        comment="skipped/pending/processing/ready/failed",
    ))
    op.add_column("ark_expo_sessions", sa.Column("beautified_photo_path", sa.String(512), nullable=True))
    op.add_column("ark_expo_sessions", sa.Column("beautify_snapshot", sa.JSON(), nullable=True))
    op.add_column("ark_expo_sessions", sa.Column("beautify_error_message", sa.Text(), nullable=True))
    op.add_column("ark_expo_sessions", sa.Column("beautify_attempt", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ark_expo_sessions", sa.Column("beautify_token", sa.String(32), nullable=True))
    op.add_column("ark_expo_sessions", sa.Column("beautify_queued_at", sa.DateTime(), nullable=True))
    op.add_column("ark_expo_sessions", sa.Column("beautify_started_at", sa.DateTime(), nullable=True))
    op.add_column("ark_expo_sessions", sa.Column("beautify_finished_at", sa.DateTime(), nullable=True))

    table = sa.table(
        "ark_expo_beautify_prompt_versions",
        sa.column("name", sa.String), sa.column("prompt_text", sa.Text), sa.column("status", sa.String),
        sa.column("revision", sa.Integer), sa.column("published_slot", sa.Integer),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime), sa.column("published_at", sa.DateTime),
    )
    seeded_at = datetime(2026, 9, 12, 14, 0, 0)
    op.bulk_insert(table, [{
        "name": "强美颜·焕颜级 V1", "prompt_text": INITIAL_PROMPT, "status": "published",
        "revision": 1, "published_slot": 1,
        "created_at": seeded_at, "updated_at": seeded_at, "published_at": seeded_at,
    }])


def downgrade():
    op.drop_constraint("uq_expo_session_customer_request", "ark_expo_sessions", type_="unique")
    for name in (
        "beautify_finished_at", "beautify_started_at", "beautify_queued_at", "beautify_token", "beautify_attempt",
        "beautify_error_message", "beautify_snapshot", "beautified_photo_path", "beautify_status",
        "request_hash", "client_request_id", "photo_processing_mode",
    ):
        op.drop_column("ark_expo_sessions", name)
    op.drop_index("idx_expo_beautify_prompt_status", table_name="ark_expo_beautify_prompt_versions")
    op.drop_table("ark_expo_beautify_prompt_versions")
