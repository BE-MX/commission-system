"""Preset-owned tunables for existing business retry and image workflows."""

from pydantic import BaseModel, ConfigDict, Field

from app.ai.models import AiPreset


class WorkflowOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    max_attempts: int | None = Field(None, ge=1, le=4)
    retry_backoff_sec: float | None = Field(None, ge=0, le=10)
    json_repair_attempts: int | None = Field(None, ge=0, le=1)
    expo_tryon_size: str | None = Field(None, min_length=1, max_length=64)
    expo_scene_size: str | None = Field(None, min_length=1, max_length=64)


def validate_workflow_options(value):
    return WorkflowOptions.model_validate({} if value is None else value).model_dump(exclude_none=True)


def workflow_options(db, preset_name):
    preset = db.query(AiPreset).filter(
        AiPreset.preset_name == preset_name, AiPreset.deleted_at.is_(None),
    ).first()
    return validate_workflow_options((preset.parameters or {}).get("workflow")) if preset else {}
