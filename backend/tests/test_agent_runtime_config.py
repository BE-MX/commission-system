import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_profile_flag_requires_dsh_runtime():
    with pytest.raises(ValidationError, match="AGENT_RUNTIME_DSH_ENABLED"):
        Settings(_env_file=None, AGENT_RUNTIME_COPILOT_ENABLED=True)


def test_dsh_runtime_requires_master_control_plane():
    with pytest.raises(ValidationError, match="AGENT_RUNTIME_ENABLED"):
        Settings(_env_file=None, AGENT_RUNTIME_DSH_ENABLED=True)


def test_sales_shadow_requires_controlled_web_search():
    with pytest.raises(ValidationError, match="AGENT_RUNTIME_WEB_SEARCH_ENABLED"):
        Settings(
            _env_file=None,
            AGENT_RUNTIME_ENABLED=True,
            AGENT_RUNTIME_DSH_ENABLED=True,
            AGENT_RUNTIME_SALES_SHADOW_ENABLED=True,
        )


def test_worker_hash_config_rejects_plaintext_token():
    with pytest.raises(ValidationError, match="64 位 SHA-256"):
        Settings(
            _env_file=None,
            AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON='{"dsh-worker-01":"plaintext-token"}',
        )


def test_worker_hash_config_accepts_rotation_list():
    settings = Settings(
        _env_file=None,
        AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON=(
            '{"dsh-worker-01":["' + ('a' * 64) + '","' + ('B' * 64) + '"]}'
        ),
    )
    assert "dsh-worker-01" in settings.AGENT_RUNTIME_WORKER_TOKEN_HASHES_JSON
