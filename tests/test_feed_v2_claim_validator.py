"""
Feed v2 Phase 13: claim_validator, offline.

Two checks per run:
  1. zero-cost citation check: every [sN] a beat cites must be a source that beat's
     writer group was actually shown (the writer's own _assign_ids/_route/_pack). No LLM.
  2. one LLM call per writer group, over only the sources cited in that group. Verdict per
     claim: supported/unsupported (Job 1, surfaced in degraded_reason), evidence_weak (Job 2)
     and conflict (Job 3), both computed and logged, neither wired to the graph yet.

The LLM boundary (call_agent) is mocked here; the real calls are in the Phase 13 report.
"""
import json

import pytest

from backend.services.feed_v2 import graph as G
from backend.services.feed_v2.agents import claim_validator as CV
from backend.services.feed_v2.agents import section_writer as SW
from backend.services.feed_v2.llm.provider import AGENT_SCHEMAS, AllLegsFailed

# 8 ranked web sources: s1..s8. _route: A = s1,s2 | B/C = s1..s6 | D = s7,s8.
RANKED = [{"src": "web", "content": f"page {i} text", "url": f"https://x/{i}", "rank_score": 1 - i / 10}
          for i in range(1, 9)]


def _beat(body, cites):
    return {"heading": "h", "body": body, "visual": None, "citations": cites}


def _drafts(**beats_by_group):
    n = {"A": 1, "B": 4, "C": 6, "D": 8}
    return [{"n": n[g], "title": "t", "group": g, "beats": beats} for g, beats in beats_by_group.items()]


class _FakeLLM:
    """Records every call; answers each claim beat with the verdict given for it."""
    def __init__(self, verdict="supported", evidence_weak=False, conflict=False, fail=False):
        self.calls, self.v, self.ew, self.cf, self.fail = [], verdict, evidence_weak, conflict, fail

    def __call__(self, agent, messages, system="", *, schema=None, meta=None, images=None):
        self.calls.append({"agent": agent, "prompt": messages[0]["content"], "meta": meta})
        if self.fail:
            raise AllLegsFailed("agent claim_validator: gemini: 503 | nemotron: 429")
        ids = [ln.split("]")[0][1:] for ln in messages[0]["content"].splitlines() if ln.startswith("[B")]
        return {"verdicts": [{"beat": b, "claim": f"claim in {b}", "cited": ["s1"], "verdict": self.v,
                              "evidence_weak": self.ew, "conflict": self.cf, "reason": "r"} for b in ids]}


def test_schema_declares_item_shape_for_gemini():
    """The Phase 3 placeholder had a bare {"type": "array"}; Gemini 400s on it
    ('response_schema.properties[verdicts].items: missing field')."""
    items = AGENT_SCHEMAS["claim_validator"]["properties"]["verdicts"]["items"]
    assert items["properties"]["verdict"]["enum"] == ["supported", "unsupported"]
    assert {"evidence_weak", "conflict"} <= set(items["required"])


def test_invented_citation_is_caught_with_no_llm_call(monkeypatch, capsys):
    """Group A was shown s1,s2 only. s7 exists (group D saw it) and s99 doesn't exist at all:
    both are invented FOR GROUP A. The beat has no valid citation, so nothing goes to the LLM."""
    llm = _FakeLLM()
    monkeypatch.setattr(CV, "call_agent", llm)
    out = CV.run_claim_validator(section_drafts=_drafts(A=[_beat("x [s7] y [s99]", ["s7", "s99"])]),
                                 ranked_sources=RANKED)
    with capsys.disabled():
        print("\ninvented:", json.dumps(out["verdicts"]), "| LLM calls:", len(llm.calls),
              "| degraded_reason:", out.get("degraded_reason"))
    assert llm.calls == []
    assert out["verdicts"] == [{"kind": "invented_citation", "group": "A", "section": 1, "beat": 0,
                                "heading": "h", "ids": ["s7", "s99"]}]
    assert "invented_citations=1" in out["degraded_reason"]


def test_citation_check_reads_inline_markers_too(monkeypatch):
    """A marker in the body that the beat's citations list omits is still a citation."""
    monkeypatch.setattr(CV, "call_agent", _FakeLLM())
    out = CV.run_claim_validator(section_drafts=_drafts(D=[_beat("fact [s1]", [])]), ranked_sources=RANKED)
    assert [v["ids"] for v in out["verdicts"] if v["kind"] == "invented_citation"] == [["s1"]]


def test_one_call_per_group_scoped_to_that_groups_cited_sources(monkeypatch):
    llm = _FakeLLM()
    monkeypatch.setattr(CV, "call_agent", llm)
    CV.run_claim_validator(section_drafts=_drafts(A=[_beat("a [s2]", ["s2"])],
                                                  B=[_beat("b [s3]", ["s3"]), _beat("b2 [s5]", ["s5"])],
                                                  C=[_beat("no citation here", [])],
                                                  D=[_beat("d [s8]", ["s8"])]),
                           ranked_sources=RANKED)
    assert [c["meta"]["call_type"] for c in llm.calls] == ["feed_v2_claims_a", "feed_v2_claims_b", "feed_v2_claims_d"]
    b_prompt = llm.calls[1]["prompt"]
    assert "[s3]" in b_prompt and "[s5]" in b_prompt and "page 3 text" in b_prompt
    assert "page 1 text" not in b_prompt and "page 8 text" not in b_prompt   # only what B cited


def test_unsupported_claim_lands_in_verdicts_and_degraded_reason(monkeypatch):
    monkeypatch.setattr(CV, "call_agent", _FakeLLM(verdict="unsupported"))
    out = CV.run_claim_validator(section_drafts=_drafts(B=[_beat("b [s3]", ["s3"])]), ranked_sources=RANKED)
    claim = [v for v in out["verdicts"] if v["kind"] == "claim"]
    assert claim[0]["verdict"] == "unsupported" and claim[0]["section"] == 4 and claim[0]["beat"] == 0
    assert "unsupported=1 [B:4.0]" in out["degraded_reason"]


def test_supported_run_is_clean(monkeypatch):
    monkeypatch.setattr(CV, "call_agent", _FakeLLM(verdict="supported"))
    out = CV.run_claim_validator(section_drafts=_drafts(B=[_beat("b [s3]", ["s3"])]), ranked_sources=RANKED)
    assert "degraded_reason" not in out
    assert [v["verdict"] for v in out["verdicts"]] == ["supported"]


def test_jobs_2_and_3_are_computed_but_never_flip_the_loops(monkeypatch):
    monkeypatch.setattr(CV, "call_agent", _FakeLLM(verdict="unsupported", evidence_weak=True, conflict=True))
    out = CV.run_claim_validator(section_drafts=_drafts(B=[_beat("b [s3]", ["s3"])]), ranked_sources=RANKED)
    v = out["verdicts"][0]
    assert v["evidence_weak"] is True and v["conflict"] is True
    assert out["writing_weak"] is False and out["evidence_weak"] is False


def test_llm_outage_degrades_the_group_instead_of_failing_the_run(monkeypatch):
    monkeypatch.setattr(CV, "call_agent", _FakeLLM(fail=True))
    out = CV.run_claim_validator(section_drafts=_drafts(B=[_beat("b [s3]", ["s3"])]), ranked_sources=RANKED)
    assert out["verdicts"][0]["kind"] == "unchecked" and out["verdicts"][0]["group"] == "B"
    assert "unchecked_groups=B" in out["degraded_reason"]


def test_unsupported_against_a_source_dropped_by_packing_is_unchecked_not_unsupported(monkeypatch):
    """Packing to the fallback's input budget can drop a cited source; the model never saw it,
    so 'unsupported' there is not a real verdict."""
    monkeypatch.setattr(CV, "call_agent", _FakeLLM(verdict="unsupported"))
    monkeypatch.setattr(CV, "_SOURCE_BUDGET_TOKENS", 1)          # keeps only the first source
    out = CV.run_claim_validator(section_drafts=_drafts(B=[_beat("b [s3]", ["s3"]), _beat("c [s5]", ["s5"])]),
                                 ranked_sources=RANKED)
    by_beat = {v["beat"]: v["verdict"] for v in out["verdicts"]}
    assert by_beat == {0: "unsupported", 1: "unchecked"}


def test_shown_ids_are_the_writers_own_routing():
    """Same _assign_ids -> _route -> _pack the writer ran, not a reimplementation."""
    _, shown = CV._shown_ids(RANKED)
    routed = SW._route(SW._assign_ids(RANKED))
    assert shown == {g: {s["source_id"] for s in SW._pack(routed[g], SW._call_budget())} for g in SW.GROUPS}


# ── graph wiring ──────────────────────────────────────────────────────────────
def _base():
    return {"trace_id": "t", "user_id": "u1", "project_id": "p", "day_number": 1, "profile": {},
            "coverage_mode": "open", "journey_entry": {"focus": "x"}, "web_findings": [],
            "corpus_findings": [], "web_research_iters": 0, "section_writer_runs": 0,
            "rewrite_iters": 0, "research_reentry_iters": 0}


@pytest.fixture(autouse=True)
def _rig():
    G._reset_rig()
    G.USE_REAL_SOURCE_RANKER = False
    yield
    G._reset_rig()


def test_real_node_in_the_graph_flags_but_never_loops(monkeypatch):
    """Real claim_validator in the full graph: an unsupported claim and an invented citation
    reach degraded_reason (appended to the ranker's), the run still ends in the assembler,
    and neither loop fires."""
    G.USE_REAL_CLAIM_VALIDATOR = True
    drafts = _drafts(A=[_beat("a [s9]", ["s9"])], B=[_beat("b [s1]", ["s1"])])

    def writer(state):
        G._EXEC_LOG.append("section_writer")
        return {"section_drafts": drafts, "section_writer_runs": 1, "rewrite_iters": 0}
    monkeypatch.setattr(G, "section_writer", writer)
    monkeypatch.setattr(G, "source_ranker", lambda s: {"ranked_sources": RANKED, "degraded_reason": "ranker: thin"})
    monkeypatch.setattr(CV, "call_agent", _FakeLLM(verdict="unsupported", evidence_weak=True))
    final = G.compile_graph().invoke(_base())
    assert G._EXEC_LOG[-2:] == ["claim_validator", "assembler"]
    assert G._EXEC_LOG.count("section_writer") == 1 and "research_reentry" not in G._EXEC_LOG
    assert final["writing_weak"] is False and final["evidence_weak"] is False
    assert final["degraded_reason"].startswith("ranker: thin; claim_validator: ")
    assert "unsupported=1" in final["degraded_reason"] and "invented_citations=1" in final["degraded_reason"]


def test_fallback_ceiling_plus_max_input_fits_the_fallback_context():
    """The ceiling is capped by the :free model's 128k window: the largest input this agent
    can send (sources packed to _SOURCE_BUDGET_TOKENS + the 8k reserve) plus max_tokens must fit."""
    from backend.services.feed_v2.budget import MODEL_BUDGETS, input_budget
    from backend.services.feed_v2.llm.provider import AGENT_ROUTING, OPENROUTER_MAX_TOKENS
    fallback = AGENT_ROUTING["claim_validator"][1]
    assert input_budget(fallback) + OPENROUTER_MAX_TOKENS["claim_validator"] <= MODEL_BUDGETS[fallback].context_window
