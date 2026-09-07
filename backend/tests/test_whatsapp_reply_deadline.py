"""Exercise real cancellation against a local synthetic slow-chunk server."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.ai.http_client import post_json


def test_reply_total_deadline_stops_slow_drip_response():
    disconnected = threading.Event()
    received = threading.Event()
    body = b'{"reply":"' + b'x' * 300 + b'"}'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            return

        def do_POST(self):
            received.set()
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                for byte in body:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            post_json(f"http://127.0.0.1:{server.server_port}", headers={}, body={"synthetic": True}, timeout_sec=2, enforce_total_timeout=True)
        assert time.monotonic() - started < 3
        assert received.is_set(), "test must exercise an in-flight response, not only client initialization"
        assert disconnected.wait(2), "deadline must close the transport, not leave it consuming chunks"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
