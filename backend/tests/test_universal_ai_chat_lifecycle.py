"""Persist stream cleanup and regeneration invariants on disposable SQLite."""
import asyncio

import anyio
import pytest
from starlette.requests import ClientDisconnect

from app.ai_chat import router, service, workspace_service as workspace
from app.ai_chat.models import AiChatMessage
from app.ai_chat.schemas import RetryStreamRequest
from app.ai_chat.stream_response import ClosingStreamingResponse
from tests.test_ai_chat_stream_cleanup import _turn


@pytest.mark.parametrize('spec', ['2.3', '2.4'])
@pytest.mark.parametrize('cut_after', [0, 1, 2])
def test_asgi_early_disconnect_releases_conversation(db, monkeypatch, spec, cut_after):
    owner, session, assistant_id = _turn(db, f'asgi-{spec.replace(".", "_")}-{cut_after}')
    calls = []
    monkeypatch.setattr(router, 'chat_stream', lambda *args, **kwargs: calls.append(True))
    events = router.stream_assistant_events(db, owner, session, db.get(AiChatMessage, assistant_id), reused=False)
    response = ClosingStreamingResponse(events, media_type='text/event-stream')

    async def run():
        disconnected = anyio.Event()
        count = 0
        async def send(message):
            nonlocal count
            if message['type'] == 'http.response.body':
                count += 1
            if count == cut_after:
                if spec == '2.4':
                    raise OSError('synthetic disconnect')
                disconnected.set()
                await anyio.sleep_forever()
        async def receive():
            await disconnected.wait()
            return {'type': 'http.disconnect'}
        try:
            await response({'type': 'http', 'asgi': {'spec_version': spec}}, receive, send)
        except ClientDisconnect:
            assert spec == '2.4'
    asyncio.run(run())
    assert calls == []
    assert db.get(AiChatMessage, assistant_id).status == 'stopped'
    workspace.delete_session(db, owner, session)


def test_late_disconnect_cannot_replace_a_completed_answer(db):
    owner, _, assistant_id = _turn(db, 'completed-terminal')
    service.finish_turn(db, owner, assistant_id, 'complete answer')
    service.stop_turn(db, owner, assistant_id, 'partial answer')
    db.expire_all()
    saved = db.get(AiChatMessage, assistant_id)
    assert (saved.status, saved.content) == ('completed', 'complete answer')


def test_empty_regeneration_preserves_previous_usable_answer_in_context(db):
    owner, session, assistant_id = _turn(db, 'empty-regeneration')
    service.finish_turn(db, owner, assistant_id, 'usable answer')
    retry = service.begin_retry(db, owner, assistant_id, RetryStreamRequest(request_id='empty_regeneration'))
    service.stop_turn(db, owner, retry.assistant_message.id, '')
    context = service.build_context(db, owner, session)
    assert [item['content'] for item in context if item['role'] == 'assistant'] == ['usable answer']
