"""Shared fixtures: a fake Gemini that behaves like a real model would on FINN's prompts, including
the bad behaviour we must defend against (fabricated quotes, unevidenced verdicts, invented numbers)."""
import dataclasses
import json
import re
import sys

import httpx
import pytest

from finn import config, llm

KEY = "AIzaFAKE-test-key-0123456789"
FABRICATED = "we will triple revenue next year and become completely debt free by march"


def _ok(payload):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
                                     "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50}})


class SmartGemini:
    def __init__(self, fail_periods=(), fail_all=False, fail_models=()):
        self.fail_periods, self.fail_all, self.fail_models = set(fail_periods), fail_all, set(fail_models)
        self.calls = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        model = req.url.path.split("/models/")[1].split(":")[0]
        body = json.loads(req.content)
        system = body["systemInstruction"]["parts"][0]["text"]
        prompt = body["contents"][0]["parts"][0]["text"]
        self.calls.append((model, prompt[:60]))
        if self.fail_all or model in self.fail_models:
            return httpx.Response(503, json={"error": {"message": "The model is overloaded."}})
        if prompt.startswith("Call: "):
            period = prompt.split("\n", 1)[0][6:].strip()
            if period in self.fail_periods:
                return httpx.Response(503, json={"error": {"message": "The model is overloaded."}})
            ex = re.findall(r"^\[p(\d+)\] ([^:\n]+): (.+)$", prompt, re.M)
            items = []
            for page, spk, text in ex[:2]:
                words = text.split()
                items.append({"metric": "other", "statement": "management outlook", "target": "-", "horizon": "FY27",
                              "quote": " ".join(words[:14]), "speaker": spk, "page": int(page), "kind": "directional"})
            items.append({"metric": "revenue growth", "statement": "triple revenue", "target": "3x", "horizon": "FY27",
                          "quote": FABRICATED, "speaker": "CEO", "page": 1, "kind": "explicit"})
            return _ok({"items": items})
        if "Reported quarterly numbers" in prompt:
            first = re.search(r"^[^:\n]+: [^=\n]+=(-?[\d.]+)", prompt.split("Reported quarterly numbers:\n", 1)[1], re.M)
            n = first.group(1) if first else "1"
            return _ok({"promises": [
                {"said_in": "x", "metric": "other", "promise": "p0", "outcome": "came through", "evidence": f"Sales {n}",
                 "verdict": "delivered", "ref": 0},
                {"said_in": "x", "metric": "other", "promise": "invented", "outcome": "?", "evidence": "123",
                 "verdict": "missed", "ref": 99},
                {"said_in": "x", "metric": "other", "promise": "p1", "outcome": "unclear", "evidence": "",
                 "verdict": "missed", "ref": 1}],
                "narrative_vs_numbers": [], "credibility": "mixed"})
        if prompt.startswith("Company: ") and "\nFacts:\n" in prompt:
            facts = prompt.split("\nFacts:\n", 1)[1]
            num = (re.findall(r"\d+(?:\.\d+)?", facts) or ["1"])[0]
            return _ok({"bull": [f"ROCE of {num}% is solid"], "bear": ["Margins could fall to 4.2% next year"]})
        if "business segments" in system:
            return _ok({"what_it_does": "Makes chemicals.", "segments": [{"name": "A", "share_pct": 60}]})
        if "list each person" in system:
            return _ok({"people": [{"name": "Imaginary Person", "event": {"role": "CEO"}, "career": []}]})
        return _ok([])          # classification / summaries: model skips everything


def _patch_settings(monkeypatch, st):
    original = config.settings
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("finn") and getattr(mod, "settings", None) is original:
            monkeypatch.setattr(mod, "settings", st)


@pytest.fixture
def fake_gemini(monkeypatch, tmp_path):
    import finn.intel.research  # noqa: F401  (make sure every module holding `settings` is imported)
    import finn.snapshot  # noqa: F401

    def make(offline=True, budget_min=30, **kw):
        lim = dataclasses.replace(config.LLMLimits(), timeout_s=5, retries=1, budget_min=budget_min,
                                  rpm_lite=1e6, rpm_flash=1e6)
        st = dataclasses.replace(config.settings, gemini_key=KEY, openai_compat_key=None, offline=offline,
                                 models=config.ModelTiers(bulk="gemini-flash-lite-latest", extract="gemini-flash-lite-latest",
                                                          reason="gemini-flash-latest", fallback="gemini-flash-lite-latest"),
                                 limits=lim)
        _patch_settings(monkeypatch, st)
        monkeypatch.setattr(llm, "_DB", tmp_path / "llm.sqlite")
        monkeypatch.setattr(llm.time, "sleep", lambda s: None)
        fake = SmartGemini(**kw)
        client = httpx.Client(transport=httpx.MockTransport(fake))
        monkeypatch.setattr(llm.http, "client", lambda: client)
        llm.start_run()
        return fake
    yield make
    llm.start_run()
