"""Explicit stream cleanup, including disconnect before the first frame."""

import logging

import anyio
from fastapi.responses import StreamingResponse

logger = logging.getLogger("commission.ai_chat")


class ClosingIterator:
    def __init__(self, iterator, cleanup):
        self.iterator = iterator
        self.cleanup = cleanup
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.iterator.close()
        finally:
            self.cleanup()


class ClosingStreamingResponse(StreamingResponse):
    def __init__(self, events, **kwargs):
        self.events = events
        super().__init__(events, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Starlette's sync iterator doesn't close its generator on disconnect.
            # Its shielded next() worker finishes before this cleanup runs, so the
            # request-owned Session is never used by two threads concurrently.
            with anyio.CancelScope(shield=True):
                try:
                    await anyio.to_thread.run_sync(self.events.close)
                except Exception as exc:
                    logger.error("Chat response cleanup failed: %s", type(exc).__name__)
                    print(f"[ai-chat] response cleanup failed: {type(exc).__name__}", flush=True)
