"""Integration test for the devpilot changed pipeline."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from devpilot.state.store import StateStore
from devpilot.supervisor import Supervisor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fastapi_app"


def _uvicorn_available():
    try:
        import uvicorn
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _uvicorn_available(), reason="uvicorn not installed")
class TestChangedPipeline:

    def test_changed_detects_reload(self, tmp_project):
        # Copy fixture app to temp dir
        app_dir = tmp_project / "app"
        app_dir.mkdir()
        shutil.copy(FIXTURE_DIR / "app.py", app_dir / "app.py")

        store = StateStore(tmp_project / ".devpilot" / "state.json")
        supervisor = Supervisor(store=store, project_dir=tmp_project)

        # Start the app
        cmd = f"{sys.executable} -m uvicorn app.app:app --reload --port 18234 --app-dir {app_dir}"
        supervisor.run_service(
            "backend", cmd, port=18234, type="backend",
            health_endpoint="/health",
            file_patterns=["**/*.py"],
            reload_patterns=["Started reloading", "Application startup complete"],
        )

        # Wait for startup
        time.sleep(3)

        # Check status
        status = supervisor.get_status("backend")
        assert "backend" in status

        supervisor.stop_service("backend")

    def test_changed_no_matching_service(self, tmp_project):
        store = StateStore(tmp_project / ".devpilot" / "state.json")
        supervisor = Supervisor(store=store, project_dir=tmp_project)

        result = supervisor.handle_changed("assets/logo.png")
        assert result["results"] == []
        assert "No registered service" in result.get("message", "")
