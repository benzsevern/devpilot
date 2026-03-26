from pathlib import Path

import pytest
import yaml

from devpilot.config import load_config, DevPilotConfig, ServiceConfig


def test_load_valid_config(tmp_path):
    config_data = {
        "services": {
            "backend": {
                "cmd": "uvicorn app.main:app --reload",
                "type": "backend",
                "port": 8000,
                "health": "/health",
                "file_patterns": ["**/*.py"],
                "reload_patterns": ["Started reloading"],
            },
            "frontend": {
                "cmd": "npm run dev",
                "type": "frontend",
                "port": 3000,
                "file_patterns": ["src/**/*.tsx"],
            },
        },
        "recovery": {
            "max_retries": 3,
            "backoff_seconds": [1, 3, 5],
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert len(config.services) == 2
    assert config.services["backend"].port == 8000
    assert config.services["frontend"].type == "frontend"
    assert config.recovery.max_retries == 3


def test_load_missing_config_returns_none(tmp_path):
    config = load_config(tmp_path)
    assert config is None


def test_service_inherits_framework_defaults(tmp_path):
    config_data = {
        "services": {
            "backend": {
                "cmd": "uvicorn app:main --reload",
                # No port, type, health — should come from framework detection
            },
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    svc = config.services["backend"]
    assert svc.port == 8000  # from fastapi profile
    assert svc.type == "backend"  # from fastapi profile


def test_explicit_config_overrides_framework_defaults(tmp_path):
    config_data = {
        "services": {
            "backend": {
                "cmd": "uvicorn app:main --reload",
                "port": 9000,  # Override fastapi default of 8000
            },
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert config.services["backend"].port == 9000


def test_custom_frameworks_in_config(tmp_path):
    config_data = {
        "services": {
            "app": {
                "cmd": "streamlit run app.py",
            },
        },
        "custom_frameworks": {
            "streamlit": {
                "detect": "streamlit run",
                "reload_patterns": ["Watching for changes"],
                "default_port": 8501,
                "health": "tcp",
            },
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert config.services["app"].port == 8501


def test_recovery_defaults(tmp_path):
    config_data = {"services": {"b": {"cmd": "uvicorn app:main"}}}
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert config.recovery.max_retries == 3
    assert config.recovery.backoff_seconds == [1, 3, 5]
