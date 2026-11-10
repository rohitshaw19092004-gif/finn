"""Model router behaviour under the failure modes seen in the first live run (no network, fake Gemini)."""
import dataclasses
import json

import httpx
import pytest

from finn import config, llm

KEY = "AIzaFAKE-test-key-0123456789"


def gemini_ok(payload, model="m"):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]},
                                                     "finishReason": "STOP"}],
                                     "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})


class Fake:
    """Programmable Gemini: per-model queue of responses (callables or Responses); records requests."""

    def __init__(self, script: dict[str, list]):
        self.script = {m: list(v) for m, v in script.items()}
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        model = request.url.path.split("/models/")[1].split(":")[0]
        body = json.loads(request.content)
        self.calls.append((model, body))
        q = self.script.get(model) or [gemini_ok({"ok": True})]
        r = q.pop(0) if len(q) > 1 else q[0]
        return r(request) if callable(r) else r

    def models(self):
        return [m for m, _ in self.calls]


@pytest.fixture
def router(monkeypatch, tmp_path):
    def make(script, **limits):
        lim = dataclasses.replace(config.LLMLimits(), timeout_s=5, retries=2, budget_min=30, breaker=3,
                                  cooldown_s=600, flash_cap=15, rpm_lite=1e6, rpm_flash=1e6, thinking="low")
        lim = dataclasses.replace(lim, **limits)
        st = dataclasses.replace(config.settings, gemini_key=KEY, openai_compat_key=None,
                                 models=config.ModelTiers(bulk="gemini-flash-lite-latest", extract="gemini-flash-lite-latest",
                                                          reason="gemini-flash-latest", fallback="gemini-flash-lite-latest"),
                                 limits=lim)
        monkeypatch.setattr(llm, "settings", st)
        monkeypatch.setattr(llm, "_DB", tmp_path / "llm.sqlite")
        monkeypatch.setattr(llm.time, "sleep", lambda s: None)
        fake = Fake(script)
        client = httpx.Client(transport=httpx.MockTransport(fake))
        monkeypatch.setattr(llm.http, "client", lambda: client)
        llm.start_run()
        return fake
    yield make
    llm.start_run()


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def test_503_twice_then_success_stays_on_model(router):
    fake = router({"gemini-flash-latest": [httpx.Response(503, json={"error": {"message": "overloaded"}}),
                                           httpx.Response(503, json={"error": {"message": "overloaded"}}),
                                           gemini_ok({"ok": True})]})
    r = llm.run("reason", "sys", "p1", SCHEMA)
    assert r.status == "ok" and r.model == "gemini-flash-latest" and r.attempts == 3
    assert fake.models() == ["gemini-flash-latest"] * 3


def test_persistent_503_falls_back_to_lite(router):
    fake = router({"gemini-flash-latest": [httpx.Response(503, json={"error": {"message": "overloaded"}})],
                   "gemini-flash-lite-latest": [gemini_ok({"ok": True})]})
    r = llm.run("reason", "sys", "p2", SCHEMA)
    assert r.ok and r.model == "gemini-flash-lite-latest"
    assert fake.models() == ["gemini-flash-latest"] * 3 + ["gemini-flash-lite-latest"]
    assert any(e["kind"] == "http_503" for e in llm.EVENTS)


def test_timeout_is_bounded_and_falls_back(router):
    def hang(req):
        raise httpx.ReadTimeout("timed out", request=req)
    fake = router({"gemini-flash-latest": [hang], "gemini-flash-lite-latest": [gemini_ok({"ok": True})]})
    r = llm.run("reason", "sys", "p3", SCHEMA)
    assert r.ok and r.model == "gemini-flash-lite-latest"
    assert fake.models().count("gemini-flash-latest") == 3          # 1 + 2 retries, never more


def test_daily_quota_retires_model_for_the_run(router):
    quota = httpx.Response(429, json={"error": {"code": 429, "message": "Quota exceeded for metric: "
                                                "generate_content_free_tier_requests, limit: 20",
                                                "details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
    fake = router({"gemini-flash-latest": [quota], "gemini-flash-lite-latest": [gemini_ok({"ok": True})]})
    assert llm.run("reason", "sys", "a", SCHEMA).model == "gemini-flash-lite-latest"
    assert llm.run("reason", "sys", "b", SCHEMA).model == "gemini-flash-lite-latest"
    assert fake.models().count("gemini-flash-latest") == 1            # not asked again after the daily 429
    assert llm.usage_report()["models"]["gemini-flash-latest"]["retired"]
    assert llm.available()                                            # other models still usable


def test_per_minute_429_honours_retry_delay(router, monkeypatch):
    slept = []
    rl = httpx.Response(429, text='{"error":{"code":429,"details":[{"@type":"type.googleapis.com/google.rpc.RetryInfo",'
                                  '"retryDelay":"7s"}]}}')
    fake = router({"gemini-flash-lite-latest": [rl, gemini_ok({"ok": True})]})
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    r = llm.run("extract", "sys", "p", SCHEMA)
    assert r.ok and 7.0 in slept and fake.models() == ["gemini-flash-lite-latest"] * 2


def test_thinking_config_dropped_when_model_rejects_it(router):
    bad = httpx.Response(400, json={"error": {"message": "Thinking level is not supported for this model."}})
    fake = router({"gemini-flash-lite-latest": [bad, gemini_ok({"ok": True})]})
    assert llm.run("extract", "sys", "x", SCHEMA).ok
    assert llm.run("extract", "sys", "y", SCHEMA).ok
    sent = [b["generationConfig"].get("thinkingConfig") for _, b in fake.calls]
    assert sent == [{"thinkingLevel": "low"}, None, None]


def test_budget_exhausted_defers_without_calling(router):
    fake = router({}, budget_min=0)
    r = llm.run("extract", "sys", "p", SCHEMA)
    assert r.status == "deferred" and not r.ok and fake.calls == []
    assert llm.call("extract", "sys", "p", SCHEMA) is None            # legacy wrapper: None, never fake data


def test_success_is_cached_and_failure_is_not(router):
    fake = router({"gemini-flash-lite-latest": [httpx.Response(500), httpx.Response(500), httpx.Response(500),
                                                gemini_ok({"ok": True})]})
    assert llm.run("extract", "sys", "same", SCHEMA).status == "failed"
    assert llm.run("extract", "sys", "same", SCHEMA).status == "ok"   # failure was not cached
    n = len(fake.calls)
    again = llm.run("extract", "sys", "same", SCHEMA)
    assert again.status == "cached" and again.model == "gemini-flash-lite-latest" and len(fake.calls) == n


def test_breaker_opens_after_consecutive_failures(router):
    fake = router({"gemini-flash-lite-latest": [httpx.Response(503)]}, retries=0)
    for i in range(3):
        assert llm.run("bulk", "sys", f"p{i}", SCHEMA).status == "failed"
    n = len(fake.calls)
    r = llm.run("bulk", "sys", "p4", SCHEMA)
    assert r.status == "failed" and "cooling down" in r.error and len(fake.calls) == n


def test_bad_json_moves_to_fallback(router):
    junk = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
    fake = router({"gemini-flash-latest": [junk], "gemini-flash-lite-latest": [gemini_ok({"ok": True})]})
    r = llm.run("reason", "sys", "j", SCHEMA)
    assert r.ok and r.model == "gemini-flash-lite-latest"


def test_flash_cap_protects_daily_quota(router):
    fake = router({}, flash_cap=2)
    for i in range(4):
        llm.run("reason", "sys", f"c{i}", SCHEMA)
    assert fake.models().count("gemini-flash-latest") == 2
    assert fake.models().count("gemini-flash-lite-latest") == 2


def test_bad_key_stops_all_calls_and_says_so(router):
    fake = router({"gemini-flash-lite-latest": [httpx.Response(401, json={"error": {"message": "API key not valid"}})]})
    r = llm.run("extract", "sys", "k", SCHEMA)
    assert r.status == "failed" and "GEMINI_API_KEY" in r.error
    assert not llm.available()
    assert llm.run("extract", "sys", "k2", SCHEMA).status == "unavailable" and len(fake.calls) == 1


def test_api_key_never_leaks(router):
    echo = httpx.Response(400, json={"error": {"message": f"bad request for key={KEY} ({KEY})"}})
    fake = router({"gemini-flash-lite-latest": [echo]})
    llm.run("extract", "sys", "leak", SCHEMA)
    blob = json.dumps(llm.usage_report())
    assert KEY not in blob and "[redacted]" in blob
    req_urls = [m for m, _ in fake.calls]
    assert all(KEY not in u for u in req_urls)                       # key goes in a header, not the URL
