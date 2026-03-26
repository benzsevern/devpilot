import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest

from devpilot.health.verifier import verify_endpoint, VerifyResult


class JSONHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"users": []}')

    def log_message(self, format, *args):
        pass


@pytest.fixture
def json_server():
    server = HTTPServer(("127.0.0.1", 0), JSONHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_verify_get_endpoint(json_server):
    result = verify_endpoint("GET", f"/api/users", port=json_server)
    assert result.status_code == 200
    assert result.response_time_ms > 0


def test_verify_unreachable_endpoint():
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    result = verify_endpoint("GET", "/api/users", port=port, timeout=1)
    assert result.status_code is None
    assert result.error is not None


def test_verify_result_as_dict(json_server):
    result = verify_endpoint("GET", "/api/users", port=json_server)
    d = result.to_dict()
    assert d["endpoint"] == "GET /api/users"
    assert d["status"] == 200
    assert "response_time_ms" in d
