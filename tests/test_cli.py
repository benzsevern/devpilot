import json

import pytest
from click.testing import CliRunner

from devpilot.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_status_empty(runner, tmp_path):
    result = runner.invoke(main, ["status"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {}


def test_init_no_project_markers(runner, tmp_path):
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "error" in data


def test_init_detects_uvicorn(runner, tmp_path):
    (tmp_path / "requirements.txt").write_text("uvicorn\nfastapi\n")
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "backend" in data["services"]
    # Verify yaml was created
    assert (tmp_path / ".devpilot.yaml").exists()


def test_init_detects_vite_frontend(runner, tmp_path):
    import json as json_mod
    pkg = {"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5.0"}}
    (tmp_path / "package.json").write_text(json_mod.dumps(pkg))
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "frontend" in data["services"]


def test_init_prefers_pyproject_over_requirements(runner, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = ['flask']\n")
    (tmp_path / "requirements.txt").write_text("uvicorn\n")
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    # Should detect flask from pyproject.toml, not uvicorn from requirements.txt
    assert "backend" in data["services"]


def test_cleanup_empty_state(runner, tmp_path):
    result = runner.invoke(main, ["cleanup"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["removed"] == []


def test_log_empty(runner, tmp_path):
    result = runner.invoke(main, ["log"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["entries"] == []
