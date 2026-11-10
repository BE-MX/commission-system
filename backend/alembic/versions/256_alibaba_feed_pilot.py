"""Persist one disabled-by-default Alibaba Feed pilot configuration."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "256_alibaba_feed_pilot"
down_revision = "255_followup_collaboration"
branch_labels = None
depends_on = None

TABLE = "ark_alibaba_feed_pilot"


def _create_table():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False, comment="试点单例主键"),
        sa.Column("source_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                  sa.ForeignKey("ark_alibaba_feed_sources.id"), nullable=True, comment="试点店铺来源"),
        sa.Column("user_id", sa.Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql"),
                  sa.ForeignKey("ark_users.id", ondelete="SET NULL"), nullable=True, comment="试点方舟业务员"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false(), comment="管理员手动启用状态"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="试点配置并发版本"),
        sa.CheckConstraint("id = 1", name="ck_alibaba_feed_pilot_singleton"),
    )


def upgrade():
    pilot = sa.table(TABLE, sa.column("id", sa.Integer()), sa.column("enabled", sa.Boolean()),
                     sa.column("version", sa.Integer()))
    if op.get_context().as_sql:
        _create_table()
        op.bulk_insert(pilot, [{"id": 1, "enabled": False, "version": 1}])
        return
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table(TABLE):
        _create_table()
    else:
        # On MySQL a crash after CREATE TABLE can leave the table without its
        # seed row. Confirm it is ours before resuming the interrupted revision.
        columns = {column["name"] for column in inspector.get_columns(TABLE)}
        foreign_keys = {(tuple(fk["constrained_columns"]), fk["referred_table"])
                        for fk in inspector.get_foreign_keys(TABLE)}
        if (columns != {"id", "source_id", "user_id", "enabled", "version"}
                or inspector.get_pk_constraint(TABLE)["constrained_columns"] != ["id"]
                or foreign_keys != {(("source_id",), "ark_alibaba_feed_sources"), (("user_id",), "ark_users")}
                or "ck_alibaba_feed_pilot_singleton" not in {ck["name"] for ck in inspector.get_check_constraints(TABLE)}):
            raise RuntimeError("Alibaba Feed pilot migration found an incompatible table")
    ids = connection.execute(sa.select(pilot.c.id)).scalars().all()
    if not ids:
        op.bulk_insert(pilot, [{"id": 1, "enabled": False, "version": 1}])
    elif ids != [1]:
        raise RuntimeError("Alibaba Feed pilot table violates the singleton constraint")


def downgrade():
    op.drop_table(TABLE)
