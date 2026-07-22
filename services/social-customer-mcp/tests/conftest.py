"""Test environment must be set before importing the application module."""

import os

os.environ.setdefault("SOCIAL_CUSTOMER_MCP_DB_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOCIAL_CUSTOMER_MCP_TOKEN", "test-token-that-is-at-least-32-characters")
os.environ.setdefault("SOCIAL_CUSTOMER_MCP_ALLOWED_HOSTS", "localhost:8100,testserver")
os.environ.setdefault("SOCIAL_CUSTOMER_MCP_ALLOWED_ORIGINS", "https://leshine.work")
