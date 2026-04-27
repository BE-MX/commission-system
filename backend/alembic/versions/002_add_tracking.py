"""add tracking tables

Revision ID: 002_add_tracking
Revises: 001_initial
Create Date: 2026-04-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_add_tracking"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. shipment_staging
    op.create_table(
        "shipment_staging",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("waybill_no", sa.String(50), nullable=False),
        sa.Column("carrier", sa.String(30), nullable=False),
        sa.Column("carrier_name", sa.String(50)),
        sa.Column("sender_name", sa.String(100)),
        sa.Column("sender_company", sa.String(200)),
        sa.Column("receiver_name", sa.String(100)),
        sa.Column("receiver_company", sa.String(200)),
        sa.Column("receiver_country", sa.String(50)),
        sa.Column("receiver_city", sa.String(100)),
        sa.Column("ocr_raw_text", sa.Text),
        sa.Column("source_image_url", sa.String(500)),
        sa.Column("dingtalk_user_id", sa.String(64), nullable=False),
        sa.Column("dingtalk_user_name", sa.String(50), nullable=False),
        sa.Column("processed", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("processed_at", sa.DateTime),
        sa.Column("process_result", sa.String(100)),
        sa.Column("process_note", sa.String(500)),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_staging_processed", "shipment_staging", ["processed", "created_at"])
    op.create_index("idx_staging_waybill", "shipment_staging", ["waybill_no", "carrier"])

    # 2. shipment_tracking
    op.create_table(
        "shipment_tracking",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("waybill_no", sa.String(50), nullable=False),
        sa.Column("carrier", sa.String(30), nullable=False),
        sa.Column("carrier_name", sa.String(50), nullable=False),
        sa.Column("sender_name", sa.String(100)),
        sa.Column("sender_company", sa.String(200)),
        sa.Column("receiver_name", sa.String(100)),
        sa.Column("receiver_company", sa.String(200)),
        sa.Column("receiver_country", sa.String(50)),
        sa.Column("receiver_city", sa.String(100)),
        sa.Column("current_status", sa.String(50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("current_status_text", sa.String(500)),
        sa.Column("current_location", sa.String(200)),
        sa.Column("last_event_time", sa.DateTime),
        sa.Column("shipped_at", sa.DateTime),
        sa.Column("delivered_at", sa.DateTime),
        sa.Column("dingtalk_user_id", sa.String(64), nullable=False),
        sa.Column("dingtalk_user_name", sa.String(50), nullable=False),
        sa.Column("dingtalk_sheet_row_id", sa.String(64)),
        sa.Column("last_synced_at", sa.DateTime),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("poll_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_polled_at", sa.DateTime),
        sa.Column("poll_error", sa.String(500)),
        sa.Column("ocr_raw_text", sa.Text),
        sa.Column("source_image_url", sa.String(500)),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("uk_waybill", "shipment_tracking", ["waybill_no", "carrier"], unique=True)
    op.create_index("idx_tracking_dingtalk_user", "shipment_tracking", ["dingtalk_user_id"])
    op.create_index("idx_tracking_status", "shipment_tracking", ["current_status"])
    op.create_index("idx_tracking_active_poll", "shipment_tracking", ["is_active", "last_polled_at"])
    op.create_index("idx_tracking_created", "shipment_tracking", ["created_at"])

    # 3. tracking_events
    op.create_table(
        "tracking_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("waybill_no", sa.String(50), nullable=False),
        sa.Column("carrier", sa.String(30), nullable=False),
        sa.Column("event_time", sa.DateTime, nullable=False),
        sa.Column("status_code", sa.String(50)),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("location", sa.String(200)),
        sa.Column("location_code", sa.String(20)),
        sa.Column("raw_response", sa.Text),
        sa.Column("synced_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_event_waybill", "tracking_events", ["waybill_no", "carrier"])
    op.create_index("idx_event_time", "tracking_events", ["waybill_no", "event_time"])

    # 4. carrier_config
    op.create_table(
        "carrier_config",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("carrier", sa.String(30), nullable=False, unique=True),
        sa.Column("carrier_name", sa.String(50), nullable=False),
        sa.Column("api_type", sa.String(20), nullable=False),
        sa.Column("api_base_url", sa.String(200), nullable=False),
        sa.Column("api_username", sa.String(100)),
        sa.Column("api_password", sa.String(200)),
        sa.Column("api_key", sa.String(200)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("poll_interval_minutes", sa.Integer, nullable=False, server_default=sa.text("60")),
        sa.Column("max_poll_days", sa.Integer, nullable=False, server_default=sa.text("90")),
        sa.Column("waybill_pattern", sa.String(100)),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # seed carrier_config
    op.execute("""
        INSERT INTO carrier_config (carrier, carrier_name, api_type, api_base_url, poll_interval_minutes, max_poll_days, waybill_pattern)
        VALUES
        ('DHL',   'DHL Express', 'rest', 'https://express.api.dhl.com/mydhlapi', 60, 90, '^[0-9]{10,11}$'),
        ('FEDEX', 'FedEx',       'rest', 'https://apis.fedex.com',               60, 90, '^[0-9]{12,15}$'),
        ('UPS',   'UPS',         'rest', '',                                      60, 90, '^1Z[A-Z0-9]{16}$'),
        ('TNT',   'TNT',         'rest', '',                                      60, 90, NULL)
    """)


def downgrade() -> None:
    op.drop_table("carrier_config")
    op.drop_table("tracking_events")
    op.drop_table("shipment_tracking")
    op.drop_table("shipment_staging")
