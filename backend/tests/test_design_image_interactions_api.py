"""Structured Design Image message interaction contract tests."""

from datetime import datetime
import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.design_image import router, schemas


def _message(interaction_json=None):
    return SimpleNamespace(
        id=7,
        session_id=3,
        role="assistant",
        content="请选择输出方式",
        status="normal",
        interaction_json=interaction_json,
        created_at=datetime(2026, 8, 9, 12, 30),
    )


def test_old_message_serializes_null_interaction():
    assert hasattr(router, "serialize_message")
    assert router.serialize_message(_message())["interaction"] is None


def test_message_serializes_only_public_output_mode_confirmation_fields():
    row = _message({
        "type": "output_mode_confirmation",
        "status": "pending",
        "source_message_id": 6,
        "request_id": "turn-client-uuid",
        "count": 3,
        "item_kind": "angle",
        "labels": ["正面", "左侧 45°", "右侧 45°"],
        "request": {
            "base_asset_id": None,
            "reference_asset_ids": [11],
            "model": "gpt-image-2",
            "size": "1024x1024",
            "quality": "medium",
            "prompt_snapshot": "never expose this",
            "provider_options": {"secret": True},
        },
        "selected_mode": None,
        "prompt_snapshot": "never expose this either",
        "internal_error": "private stack trace",
    })

    assert hasattr(router, "serialize_message")
    body = router.serialize_message(row)

    assert body["interaction"] == {
        "type": "output_mode_confirmation",
        "status": "pending",
        "source_message_id": 6,
        "request_id": "turn-client-uuid",
        "count": 3,
        "item_kind": "angle",
        "labels": ["正面", "左侧 45°", "右侧 45°"],
        "request": {
            "base_asset_id": None,
            "reference_asset_ids": [11],
            "model": "gpt-image-2",
            "size": "1024x1024",
            "quality": "medium",
        },
        "selected_mode": None,
        "resolved_at": None,
    }
    serialized = json.dumps(body, ensure_ascii=False)
    assert "prompt_snapshot" not in serialized
    assert "provider_options" not in serialized
    assert "internal_error" not in serialized


@pytest.mark.parametrize(
    "interaction_json",
    [
        {"type": "unknown_interaction"},
        {
            "type": "output_mode_confirmation",
            "status": "pending",
            "source_message_id": 6,
            "request_id": "turn-client-uuid",
            "count": 5,
            "labels": ["a", "b", "c", "d", "e"],
            "request": {
                "base_asset_id": None,
                "reference_asset_ids": [],
                "size": "1024x1024",
                "quality": "medium",
            },
            "selected_mode": None,
        },
    ],
)
def test_malformed_stored_interaction_is_omitted_and_logged(
    interaction_json,
    caplog,
):
    with caplog.at_level(logging.WARNING, logger="app.design_image.router"):
        assert hasattr(router, "serialize_message")
        body = router.serialize_message(_message(interaction_json))

    assert body["interaction"] is None
    assert "invalid stored design image interaction" in caplog.text


def test_message_action_request_is_strict_and_bounded():
    assert hasattr(schemas, "MessageActionRequest")
    MessageActionRequest = schemas.MessageActionRequest
    body = MessageActionRequest(
        request_id="resolve_123",
        action="choose_output_mode",
        mode="separate",
    )
    assert body.mode == "separate"

    with pytest.raises(ValidationError):
        MessageActionRequest(
            request_id="resolve_123",
            action="choose_output_mode",
            mode="separate",
            hidden=True,
        )
    with pytest.raises(ValidationError):
        MessageActionRequest(
            request_id="x" * 65,
            action="choose_output_mode",
            mode="separate",
        )
    with pytest.raises(ValidationError):
        MessageActionRequest(
            request_id="resolve_123",
            action="choose_output_mode",
            mode="other",
        )


def test_output_mode_confirmation_requires_item_kind():
    with pytest.raises(ValidationError):
        schemas.OutputModeConfirmationInteraction.model_validate({
            "type": "output_mode_confirmation",
            "status": "pending",
            "source_message_id": 6,
            "request_id": "turn-client-uuid",
            "count": 2,
            "labels": ["独立变体 1/2", "独立变体 2/2"],
            "request": {
                "base_asset_id": None,
                "reference_asset_ids": [],
                "size": "1024x1024",
                "quality": "medium",
            },
        })
