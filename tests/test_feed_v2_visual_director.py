"""
Feed v2 visual_director (Phase 12, Task 1) — decides per beat whether a visual
would help and what kind. Offline/deterministic: the one decision call is
mocked so index-join + filtering are asserted without a key. Fallback test
exercises the real routing (gemini-3-flash-preview primary -> nemotron-nano-30b
fallback), same standard as every other real agent in this pipeline.
"""
import json

from backend.services.feed_v2.agents import visual_director as VD

_DRAFTS = [
    {"n": 1, "title": "Why today", "beats": [
        {"heading": "Context", "body": "Plain framing, no visual needed.", "visual": None, "citations": []},
        {"heading": "The process", "body": "Step one, then step two, then step three.",
         "visual": "a process diagram", "citations": ["s1"]},
    ]},
    {"n": 2, "title": "Core", "beats": [
        {"heading": "Comparison", "body": "Old approach vs new approach differ in X and Y.",
         "citations": ["s2", "s3"]},
    ]},
]


# ── 1. zero beats -> clean no-op, no LLM call ──────────────────────────────────
def test_no_beats_is_a_noop(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("call_agent must not be called for an empty draft")
    monkeypatch.setattr(VD, "call_agent", boom)

    out = VD.run_visual_director(section_drafts=[])
    with capsys.disabled():
        print(f"\nempty draft -> {out}")
    assert out == {"visual_specs": []}


# ── 2. index-join: model decisions map back to the REAL (section_n, beat_index) ──
def test_specs_join_back_to_real_beats(monkeypatch, capsys):
    seen_prompt = {}

    def fake_call(agent, messages, system="", schema=None, meta=None):
        seen_prompt["content"] = messages[0]["content"]
        return {"specs": [
            {"index": 0, "needs_visual": False},
            {"index": 1, "needs_visual": True, "visual_type": "process", "topic": "the three steps"},
            {"index": 2, "needs_visual": True, "visual_type": "comparison", "topic": "old vs new"},
        ]}
    monkeypatch.setattr(VD, "call_agent", fake_call)

    out = VD.run_visual_director(section_drafts=_DRAFTS)
    with capsys.disabled():
        print(f"\nvisual_specs: {json.dumps(out['visual_specs'], indent=2)}")
    assert out["visual_specs"] == [
        {"section_n": 1, "beat_index": 1, "visual_type": "process", "topic": "the three steps",
         "citations": ["s1"]},
        {"section_n": 2, "beat_index": 0, "visual_type": "comparison", "topic": "old vs new",
         "citations": ["s2", "s3"]},
    ]
    assert "The process" in seen_prompt["content"]   # real beat content reached the prompt


# ── 3. malformed model output (bad index, bad enum) is dropped, not trusted ────
def test_malformed_specs_are_dropped(monkeypatch, capsys):
    def fake_call(agent, messages, system="", schema=None, meta=None):
        return {"specs": [
            {"index": 99, "needs_visual": True, "visual_type": "process"},        # out of range
            {"index": 0, "needs_visual": True, "visual_type": "not-a-real-type"},  # bad enum
            {"index": 1, "needs_visual": True},                                    # missing visual_type
        ]}
    monkeypatch.setattr(VD, "call_agent", fake_call)

    out = VD.run_visual_director(section_drafts=_DRAFTS)
    with capsys.disabled():
        print(f"\nmalformed input -> {out}")
    assert out["visual_specs"] == []


# ── 4. topic falls back to the writer's own hint, then the heading ─────────────
def test_topic_falls_back_to_writer_hint(monkeypatch, capsys):
    def fake_call(agent, messages, system="", schema=None, meta=None):
        return {"specs": [{"index": 1, "needs_visual": True, "visual_type": "process"}]}  # no topic
    monkeypatch.setattr(VD, "call_agent", fake_call)

    out = VD.run_visual_director(section_drafts=_DRAFTS)
    with capsys.disabled():
        print(f"\ntopic fallback -> {out['visual_specs']}")
    assert out["visual_specs"][0]["topic"] == "a process diagram"   # the writer's own hint, not the heading


# ── 5. fallback leg serves (gemini primary down -> nemotron-nano-30b fallback) ─
def test_fallback_leg_serves(monkeypatch, capsys):
    from backend.services.feed_v2.llm import provider
    fallback_id = provider.MODEL_REGISTRY[provider.AGENT_ROUTING["visual_director"][1]][1]
    served: list[str] = []
    ceilings: list[int | None] = []
    monkeypatch.setattr(provider, "_keys_for_provider", lambda p: ["fake-key"])

    def fake_google(api_model_id, *a, **k):
        raise RuntimeError("simulated primary (gemini) outage")

    def fake_openrouter(api_model_id, messages, system, schema, key, images=None, max_tokens=None):
        served.append(api_model_id)
        ceilings.append(max_tokens)
        body = {"specs": [{"index": 0, "needs_visual": True, "visual_type": "process", "topic": "t"}]}
        return {"text": json.dumps(body), "in_tokens": 1, "out_tokens": 1,
                "latency_ms": 1, "model_used": api_model_id}

    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "google", fake_google)
    monkeypatch.setitem(provider._SDK_FOR_PROVIDER, "openrouter", fake_openrouter)
    monkeypatch.setattr(provider.call_logger, "write_call_row", lambda **k: None)

    out = provider.call_agent("visual_director",
                              [{"role": "user", "content": "[0] heading\nbody"}],
                              system="sys", schema=VD._SPECS_SCHEMA)
    with capsys.disabled():
        print(f"\nfallback: primary gemini-3-flash-preview failed -> served {served}")
    assert served == [fallback_id] == ["nvidia/nemotron-3-super-120b-a12b:free"]
    assert ceilings == [provider.OPENROUTER_MAX_TOKENS["visual_director"]]   # ceiling reaches the OpenRouter leg
    assert out["specs"][0]["needs_visual"] is True
