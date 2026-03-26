import sys
import time
from pathlib import Path

import pytest

from devpilot.supervisor import Supervisor
from devpilot.state.store import StateStore


@pytest.fixture
def supervisor(tmp_project):
    store = StateStore(tmp_project / ".devpilot" / "state.json")
    return Supervisor(store=store, project_dir=tmp_project)


def test_run_service_registers_in_state(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("test_svc", cmd, port=0, type="backend")
    time.sleep(0.3)

    state = supervisor.store.read()
    assert "test_svc" in state["services"]
    assert state["services"]["test_svc"]["status"] == "registered"
    assert state["services"]["test_svc"]["mode"] == "managed"

    supervisor.stop_service("test_svc")


def test_stop_service_removes_process(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("test_svc", cmd, port=0, type="backend")
    time.sleep(0.3)

    supervisor.stop_service("test_svc")
    time.sleep(0.3)

    assert not supervisor.is_running("test_svc")


def test_status_returns_all_services(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("svc1", cmd, port=0, type="backend")
    supervisor.run_service("svc2", cmd, port=0, type="frontend")
    time.sleep(0.3)

    status = supervisor.get_status()
    assert len(status) == 2
    assert "svc1" in status
    assert "svc2" in status

    supervisor.stop_all()


def test_stop_all_stops_everything(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("svc1", cmd, port=0, type="backend")
    supervisor.run_service("svc2", cmd, port=0, type="frontend")
    time.sleep(0.3)

    supervisor.stop_all()
    time.sleep(0.3)

    assert not supervisor.is_running("svc1")
    assert not supervisor.is_running("svc2")
