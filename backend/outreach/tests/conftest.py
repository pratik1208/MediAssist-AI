import pytest


@pytest.fixture(autouse=True)
def _no_langsmith_tracing(monkeypatch):
    """Keep test runs out of the real LangSmith project."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture(autouse=True)
def _clear_message_cache():
    """render_message() memoizes bodies per (language, goal) in a module
    global — a real feature, but it leaks state across tests. Clear it
    around every test so each starts cold."""
    import outreach.services as services
    services._MESSAGE_BODY_CACHE.clear()
    yield
    services._MESSAGE_BODY_CACHE.clear()


@pytest.fixture(autouse=True)
def _no_real_ai_calls(monkeypatch):
    """Any unmocked model call fails fast instead of hitting the network.

    Tests that want model output patch outreach.ai.call_tool explicitly,
    which overrides this.
    """
    def _blocked(*args, **kwargs):
        raise RuntimeError("real AI call attempted in tests")

    monkeypatch.setattr("outreach.ai.call_tool", _blocked)
