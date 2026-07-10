import pytest


@pytest.fixture(autouse=True)
def _no_langsmith_tracing(monkeypatch):
    """Keep test runs out of the real LangSmith project."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture(autouse=True)
def _no_real_ai_calls(monkeypatch):
    """Any unmocked model call fails fast instead of hitting the network.

    escalate() swallows this via its fallback path (by design — an AI outage
    must never block an emergency alert); tests that want model output patch
    triage.ai.call_tool explicitly, which overrides this.
    """
    def _blocked(*args, **kwargs):
        raise RuntimeError("real AI call attempted in tests")

    monkeypatch.setattr("triage.ai.call_tool", _blocked)
