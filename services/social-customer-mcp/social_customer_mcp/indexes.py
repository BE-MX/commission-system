"""Idempotently add the three lookup indexes required by this service."""

from sqlalchemy import inspect, text

from .query_service import create_db_engine


REQUIRED_INDEXES = {
    "customer_info": (
        "idx_social_mcp_customer_email",
        "ALTER TABLE customer_info ADD INDEX idx_social_mcp_customer_email (email(191)), ALGORITHM=INPLACE, LOCK=NONE",
    ),
    "customer_contacts": (
        "idx_social_mcp_contact_phone",
        "ALTER TABLE customer_contacts ADD INDEX idx_social_mcp_contact_phone (tel), ALGORITHM=INPLACE, LOCK=NONE",
    ),
    "customer_contact_socials": (
        "idx_social_mcp_social_value",
        "ALTER TABLE customer_contact_socials ADD INDEX idx_social_mcp_social_value (value(191)), ALGORITHM=INPLACE, LOCK=NONE",
    ),
}


def apply_indexes() -> None:
    engine = create_db_engine()
    try:
        with engine.begin() as conn:
            inspector = inspect(conn)
            for table_name, (index_name, ddl) in REQUIRED_INDEXES.items():
                existing = {item["name"] for item in inspector.get_indexes(table_name)}
                if index_name in existing:
                    print(f"SKIP {table_name}.{index_name} already exists")
                    continue
                print(f"ADD  {table_name}.{index_name}")
                conn.execute(text(ddl))
    finally:
        engine.dispose()


if __name__ == "__main__":
    apply_indexes()
