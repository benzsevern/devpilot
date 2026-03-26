from pathlib import Path, PurePosixPath

import pytest

from devpilot.watch.file_watcher import match_file_to_services


def test_match_python_file_to_backend():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "frontend": {"file_patterns": ["src/**/*.tsx"]},
    }
    matches = match_file_to_services("app/routes/users.py", services)
    assert matches == ["backend"]


def test_match_tsx_file_to_frontend():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "frontend": {"file_patterns": ["src/**/*.tsx", "src/**/*.ts"]},
    }
    matches = match_file_to_services("src/components/Header.tsx", services)
    assert matches == ["frontend"]


def test_match_no_service():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "frontend": {"file_patterns": ["src/**/*.tsx"]},
    }
    matches = match_file_to_services("assets/logo.png", services)
    assert matches == []


def test_match_multiple_services():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "shared": {"file_patterns": ["**/*.py", "**/*.ts"]},
    }
    matches = match_file_to_services("lib/utils.py", services)
    assert "backend" in matches
    assert "shared" in matches


def test_match_css_file():
    services = {
        "frontend": {"file_patterns": ["src/**/*.tsx", "src/**/*.css"]},
    }
    matches = match_file_to_services("src/styles/main.css", services)
    assert matches == ["frontend"]
