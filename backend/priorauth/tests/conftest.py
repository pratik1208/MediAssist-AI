import pytest


@pytest.fixture(autouse=True)
def _no_langsmith_tracing(monkeypatch):
    """Keep test runs out of the real LangSmith project."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture(autouse=True)
def _no_real_ai_calls(monkeypatch):
    """Any unmocked model call fails fast instead of hitting the network.

    Services swallow this via their fallback paths (an AI outage must never
    block a package from reaching ready_for_review, or a raw payer message
    from being interpreted as "still under review" rather than a guessed
    decision); tests that want model output patch priorauth.ai.call_tool
    explicitly, which overrides this.
    """
    def _blocked(*args, **kwargs):
        raise RuntimeError("real AI call attempted in tests")

    monkeypatch.setattr("priorauth.ai.call_tool", _blocked)
