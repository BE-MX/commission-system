"""Run-token authenticated OpenAI-compatible endpoint consumed by DSH."""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agent_runtime.errors import AgentRuntimeError
from app.agent_runtime.token_service import decode_run_token
from app.ai.service import prepare_agent_chat
from app.core.database import get_db


router = APIRouter()


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = Field(None, max_length=128)
    messages: list[dict[str, Any]] = Field(..., min_length=1, max_length=500)
    tools: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    tool_choice: Any = None
    parallel_tool_calls: bool | None = None
    stream: bool = True


def _claims(authorization: str | None = Header(default=None)) -> dict:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="缺少 Agent Run Bearer Token")
    try:
        return decode_run_token(token)
    except AgentRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/v1/chat/completions")
def agent_chat_completions(
    payload: AgentChatRequest,
    claims: dict = Depends(_claims),
    db: Session = Depends(get_db),
):
    if not payload.stream:
        raise HTTPException(status_code=400, detail="Agent 模型网关仅支持 stream=true")
    try:
        stream, model = prepare_agent_chat(
            db,
            claims=claims,
            messages=payload.messages,
            tools=payload.tools,
            tool_choice=payload.tool_choice,
            parallel_tool_calls=payload.parallel_tool_calls,
        )
    except AgentRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Ark-Agent-Model": model,
        },
    )
