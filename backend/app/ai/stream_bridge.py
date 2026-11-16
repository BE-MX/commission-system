"""Bounded network-only producer; the consumer retains sole ownership of the DB."""
from queue import Empty, Full, Queue
from threading import Event, Thread


def network_events(client_factory, parser, api_type, url, headers, params, *, heartbeat_seconds=5):
    queue = Queue(maxsize=32)
    cancelled = Event()
    active = []

    def put(value):
        while not cancelled.is_set():
            try:
                queue.put(value, timeout=0.2)
                return
            except Full:
                continue

    def produce():
        try:
            with client_factory() as client:
                active.append(client)
                if cancelled.is_set():
                    return
                with client.stream('POST', url, headers=headers, json=params) as response:
                    active.append(response)
                    response.raise_for_status()
                    for event in parser(api_type, response.iter_lines()):
                        if cancelled.is_set():
                            return
                        put(event)
        except Exception as exc:
            # Propagate to the consumer's existing sanitized error/logging boundary.
            put(exc)
        finally:
            put(None)

    worker = Thread(target=produce, name='ai-stream-network', daemon=True)
    worker.start()
    try:
        while True:
            try:
                value = queue.get(timeout=heartbeat_seconds)
            except Empty:
                yield {'type': 'heartbeat'}
                continue
            if value is None:
                return
            if isinstance(value, Exception):
                raise value
            yield value
    finally:
        cancelled.set()
        # httpx timeouts bound an in-flight connect; closing the transport also
        # releases an established stream. Never hand a DB session to this thread.
        for resource in reversed(active):
            resource.close()
        worker.join(timeout=0.2)
