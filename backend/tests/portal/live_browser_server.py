"""Loopback-only HTTPS/ASGI harness shared by opt-in portal browser tests."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import mimetypes
import socket
import threading
import time
from urllib.parse import urlsplit, unquote

from datetime import timedelta
import ipaddress
import ssl
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from app.core.time import utc_now


def certificate(directory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Portal isolated browser test')])
    now = utc_now()
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(key, hashes.SHA256()))
    private = directory / 'test-only.key'; public = directory / 'test-only.crt'
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(public, private)
    return context



@contextmanager
def running_portal(app, ctx, dist, tmp_path):
    import uvicorn
    sock = socket.socket(); sock.bind(('127.0.0.1', 0))
    backend_port = sock.getsockname()[1]
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *args): pass  # Avoid printing auth request data.
        def do_POST(self): self.forward()
        def do_GET(self):
            if urlsplit(self.path).path.startswith('/api/'):
                return self.forward()
            relative = unquote(urlsplit(self.path).path).lstrip('/')
            target = (dist / relative).resolve()
            if not target.is_relative_to(dist.resolve()):
                return self.send_error(404)
            if not target.is_file(): target = dist / 'index.html'
            body = target.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def forward(self):
            if not urlsplit(self.path).path.startswith('/api/portal/v1/'):
                return self.send_error(404)
            headers = {key: value for key, value in self.headers.items()
                if key.lower() not in {'host', 'connection', 'x-real-ip', 'x-forwarded-for', 'forwarded'}}
            headers['X-Real-IP'] = self.client_address[0]
            conn = http.client.HTTPConnection('127.0.0.1', backend_port, source_address=('127.0.0.2', 0), timeout=10)
            try:
                conn.request(self.command, self.path, self.rfile.read(int(self.headers.get('Content-Length', 0))), headers)
                response = conn.getresponse(); body = response.read()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {'transfer-encoding', 'connection', 'content-length'}: self.send_header(key, value)
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            finally: conn.close()
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    proxy.socket = certificate(tmp_path).wrap_socket(proxy.socket, server_side=True)
    origin = f'https://127.0.0.1:{proxy.server_port}'
    ctx.settings.PORTAL_ORIGIN = origin; ctx.site.allowed_origin = origin; ctx.db.commit()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', log_level='warning', access_log=False,
                                         proxy_headers=False, lifespan='off'))
    backend_thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    backend_thread.start(); proxy_thread.start()
    try:
        for _ in range(500):
            if server.started: break
            time.sleep(.01)
        assert server.started
        yield origin, f'http://127.0.0.1:{backend_port}'
    finally:
        proxy.shutdown(); proxy.server_close(); server.should_exit = True
        backend_thread.join(5); proxy_thread.join(5); sock.close()
        assert not backend_thread.is_alive() and not proxy_thread.is_alive()
