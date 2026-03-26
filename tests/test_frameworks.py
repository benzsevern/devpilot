from devpilot.frameworks.registry import FrameworkRegistry, FrameworkProfile


def test_detect_fastapi():
    reg = FrameworkRegistry()
    profile = reg.detect("uvicorn app.main:app --reload")
    assert profile.name == "fastapi"
    assert profile.default_port == 8000
    assert len(profile.reload_patterns) > 0


def test_detect_flask():
    reg = FrameworkRegistry()
    profile = reg.detect("flask run --debug")
    assert profile.name == "flask"
    assert profile.default_port == 5000


def test_detect_django():
    reg = FrameworkRegistry()
    profile = reg.detect("python manage.py runserver 0.0.0.0:8000")
    assert profile.name == "django"
    assert profile.default_port == 8000


def test_detect_vite():
    reg = FrameworkRegistry()
    profile = reg.detect("npx vite --port 5173")
    assert profile.name == "vite"
    assert profile.default_port == 5173


def test_detect_nextjs():
    reg = FrameworkRegistry()
    profile = reg.detect("npx next dev")
    assert profile.name == "nextjs"
    assert profile.default_port == 3000


def test_detect_cra():
    reg = FrameworkRegistry()
    profile = reg.detect("npx react-scripts start")
    assert profile.name == "cra"
    assert profile.default_port == 3000


def test_detect_unknown_returns_none():
    reg = FrameworkRegistry()
    profile = reg.detect("some-unknown-command --flag")
    assert profile is None


def test_register_custom_framework():
    reg = FrameworkRegistry()
    reg.register(FrameworkProfile(
        name="streamlit",
        detect_pattern="streamlit run",
        reload_patterns=["Watching for changes"],
        default_port=8501,
        health_check="tcp",
        type="backend",
    ))
    profile = reg.detect("streamlit run app.py")
    assert profile.name == "streamlit"
    assert profile.default_port == 8501


def test_profile_has_type():
    reg = FrameworkRegistry()
    backend = reg.detect("uvicorn app:main")
    frontend = reg.detect("npx vite")
    assert backend.type == "backend"
    assert frontend.type == "frontend"
