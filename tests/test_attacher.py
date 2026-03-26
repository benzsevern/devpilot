import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest

from devpilot.process.attacher import AttachedProcess


class OKHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass


@pytest.fixture
def running_server():
    server = HTTPServer(("127.0.0.1", 0), OKHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_attach_to_running_process(running_server):
    attached = AttachedProcess.attach(name="test", port=running_server)
    assert attached is not None
    assert attached.pid is not None
    assert attached.is_alive()


def test_attach_to_empty_port_returns_none():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    attached = AttachedProcess.attach(name="test", port=port)
    assert attached is None


def test_attached_process_detects_process_name(running_server):
    attached = AttachedProcess.attach(name="test", port=running_server)
    assert attached is not None
    assert attached.process_name is not None  # Should be "python" or similar
