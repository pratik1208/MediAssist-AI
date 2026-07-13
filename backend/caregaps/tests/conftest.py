import pytest


@pytest.fixture(autouse=True)
def _no_langsmith_tracing(monkeypatch):
    """Keep test runs out of the real LangSmith project."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture(autouse=True)
def _no_real_ai_calls(monkeypatch):
    """Any unmocked model call fails fast instead of hitting the network.

    Tests that want model output patch caregaps.ai.call_tool explicitly,
    which overrides this; the live_model suite restores the real one.
    """
    def _blocked(*args, **kwargs):
        raise RuntimeError("real AI call attempted in tests")

    monkeypatch.setattr("caregaps.ai.call_tool", _blocked)
