import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest

from devpilot.health.checker import check_health, HealthResult


class OKHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass  # Suppress output


class ErrorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(500)
        self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture
def http_server():
    server = HTTPServer(("127.0.0.1", 0), OKHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


@pytest.fixture
def error_server():
    server = HTTPServer(("127.0.0.1", 0), ErrorHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


@pytest.fixture
def tcp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    yield port
    sock.close()


def test_http_health_check_healthy(http_server):
    result = check_health(port=http_server, endpoint="/health")
    assert result.healthy is True
    assert result.status_code == 200
    assert result.response_time_ms > 0


def test_http_health_check_error(error_server):
    result = check_health(port=error_server, endpoint="/health")
    assert result.healthy is False
    assert result.status_code == 500


def test_tcp_health_check_healthy(tcp_server):
    result = check_health(port=tcp_server, endpoint=None)
    assert result.healthy is True
    assert result.status_code is None  # TCP has no status code


def test_health_check_unreachable():
    # Use a port that nothing is listening on
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    result = check_health(port=port, endpoint=None, timeout=1)
    assert result.healthy is False


def test_health_result_fields(http_server):
    result = check_health(port=http_server, endpoint="/")
    assert isinstance(result.response_time_ms, float)
    assert result.response_time_ms >= 0
