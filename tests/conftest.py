import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with .devpilot/ state dir."""
    state_dir = tmp_path / ".devpilot"
    state_dir.mkdir()
    return tmp_path


@pytest.fixture
def state_file(tmp_project):
    """Return path to a temporary state file."""
    return tmp_project / ".devpilot" / "state.json"
