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
    # Phase 6 integration drives outreach's wave dispatch (which renders
    # message bodies through outreach.ai) — block that side too.
    monkeypatch.setattr("outreach.ai.call_tool", _blocked)


@pytest.fixture(autouse=True)
def _clear_outreach_message_cache():
    """dispatch_wave memoizes bodies per (language, goal) in an outreach
    module global; clear it so cross-test state never leaks."""
    import outreach.services as outreach_services
    outreach_services._MESSAGE_BODY_CACHE.clear()
    yield
    outreach_services._MESSAGE_BODY_CACHE.clear()
