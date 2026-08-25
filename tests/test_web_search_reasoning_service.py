"""
Tests for backend.services.web_search_reasoning_service — reasoning-augmented
web search (primary + contradiction query split), and the regression coverage
for the Phase 6/Tier 2a fix to chat_modes_service.format_reasoning_search_note
(the redundant 280-char snippet cut, removed once the shared 2000-char
truncate_at_sentence cap made it dead weight — see that function's inline
comment for the git-blame timeline).

fetch_reasoned_results tests mock _safe_search (this module's own private
wrapper around retrieval_router.route) directly, and stub out
backend.llm.call_logger.write_call_row (the deferred-import source module for
_log_raw_result_set's audit-log write) — per this project's patch-at-source
rule for deferred imports.
"""
from __future__ import annotations

import pytest

from backend.services import web_search_reasoning_service as wsr


@pytest.fixture(autouse=True)
def _no_call_log(monkeypatch):
    # _log_raw_result_set deferred-imports write_call_row from call_logger
    # inside the function body -> patch at that source module.
    import backend.llm.call_logger as call_logger
    monkeypatch.setattr(call_logger, "write_call_row", lambda **kwargs: None)


def _article(url: str, title: str = "t", content: str = "c") -> dict:
    return {"url": url, "title": title, "content": content}


# ─────────────────────────────────────────────────────────────────────────────
# build_search_queries — primary/contradiction split
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildSearchQueries:
    def test_primary_query_is_the_raw_message(self):
        q = wsr.build_search_queries("What is quantum entanglement?")
        assert q["primary_query"] == "What is quantum entanglement?"

    def test_contradiction_query_appends_a_suffix(self):
        q = wsr.build_search_queries("What is quantum entanglement?")
        assert q["contradiction_query"].startswith(q["primary_query"])
        assert q["contradiction_query"] != q["primary_query"]

    def test_intent_specific_suffix_used(self):
        q = wsr.build_search_queries("Why did the merger fail?", intent_profile={"primary_intent": "causal"})
        assert "counterexample" in q["contradiction_query"]

    def test_domain_boost_overrides_generic_intent_suffix(self):
        q = wsr.build_search_queries(
            "Why did the drug trial fail?",
            intent_profile={"primary_intent": "causal"},
            domain="Pharmaceutical",
        )
        assert "FDA warning letter" in q["contradiction_query"]

    def test_recency_language_forces_recent_shift_angle(self):
        q = wsr.build_search_queries("What is the current state of AI regulation?")
        assert "latest news 2024 2025" in q["contradiction_query"]

    def test_labels_present(self):
        q = wsr.build_search_queries("test")
        assert q["primary_label"]
        assert q["contradiction_label"]

    def test_message_truncated_to_150_chars_for_primary(self):
        long_msg = "x" * 300
        q = wsr.build_search_queries(long_msg)
        assert q["primary_query"] == "x" * 150


# ─────────────────────────────────────────────────────────────────────────────
# fetch_reasoned_results — dedup + _PRIMARY_MAX/_CONTRADICTION_MAX slicing
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchReasonedResultsDedupAndSlicing:
    def test_contradiction_dup_of_kept_primary_is_dropped(self, monkeypatch):
        primary_raw = [_article("u1"), _article("u2"), _article("u3")]
        # u2 duplicates a KEPT primary result -> must be dropped from complicating
        contra_raw = [_article("u2"), _article("u4"), _article("u5"), _article("u6")]
        calls = iter([primary_raw, contra_raw])
        monkeypatch.setattr(wsr, "_safe_search", lambda query, meta=None: next(calls))

        result = wsr.fetch_reasoned_results("msg")
        complicating_urls = [a["url"] for a in result["complicating"]]
        assert "u2" not in complicating_urls
        assert complicating_urls == ["u4", "u5", "u6"]

    def test_primary_sliced_to_primary_max(self, monkeypatch):
        primary_raw = [_article(f"p{i}") for i in range(5)]  # 5 > _PRIMARY_MAX (3)
        calls = iter([primary_raw, []])
        monkeypatch.setattr(wsr, "_safe_search", lambda query, meta=None: next(calls))

        result = wsr.fetch_reasoned_results("msg")
        assert len(result["supporting"]) == wsr._PRIMARY_MAX == 3
        assert [a["url"] for a in result["supporting"]] == ["p0", "p1", "p2"]

    def test_complicating_sliced_to_contradiction_max_after_dedup(self, monkeypatch):
        primary_raw = [_article("p1"), _article("p2"), _article("p3")]
        # 5 unique contra results, none overlapping primary -> dedup keeps all 5,
        # then _CONTRADICTION_MAX (3) slicing must still cut it to 3.
        contra_raw = [_article(f"c{i}") for i in range(5)]
        calls = iter([primary_raw, contra_raw])
        monkeypatch.setattr(wsr, "_safe_search", lambda query, meta=None: next(calls))

        result = wsr.fetch_reasoned_results("msg")
        assert len(result["complicating"]) == wsr._CONTRADICTION_MAX == 3
        assert [a["url"] for a in result["complicating"]] == ["c0", "c1", "c2"]

    def test_dedup_only_checks_against_kept_top3_primary_not_full_raw_primary(self, monkeypatch):
        # p4 is real primary result #4 -- beyond the top-3 cutoff, so it is NOT
        # in primary_articles (the kept slice) and dedup can't see it. This
        # documents the real current behavior (dedup is against the trimmed
        # list, not the raw list) rather than an idealized one.
        primary_raw = [_article("p1"), _article("p2"), _article("p3"), _article("p4")]
        contra_raw  = [_article("p4")]  # duplicates the DROPPED 4th primary result
        calls = iter([primary_raw, contra_raw])
        monkeypatch.setattr(wsr, "_safe_search", lambda query, meta=None: next(calls))

        result = wsr.fetch_reasoned_results("msg")
        assert [a["url"] for a in result["complicating"]] == ["p4"]

    def test_angle_tags_set(self, monkeypatch):
        calls = iter([[_article("p1")], [_article("c1")]])
        monkeypatch.setattr(wsr, "_safe_search", lambda query, meta=None: next(calls))

        result = wsr.fetch_reasoned_results("msg")
        assert result["supporting"][0]["_angle"] == "supporting"
        assert result["complicating"][0]["_angle"] == "complicating"
        assert result["has_complicating"] is True

    def test_has_complicating_false_when_all_deduped_away(self, monkeypatch):
        primary_raw = [_article("p1")]
        contra_raw  = [_article("p1")]  # fully duplicates the only primary result
        calls = iter([primary_raw, contra_raw])
        monkeypatch.setattr(wsr, "_safe_search", lambda query, meta=None: next(calls))

        result = wsr.fetch_reasoned_results("msg")
        assert result["complicating"] == []
        assert result["has_complicating"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Regression: Tier 2a fix — format_reasoning_search_note must NOT re-truncate
# content at 280 chars. Locks in the fix so it can't silently regress.
# ─────────────────────────────────────────────────────────────────────────────

class TestReasoningSearchNoteNoTruncation:
    def test_full_content_past_280_chars_reaches_the_model(self):
        from backend.services.chat_modes_service import format_reasoning_search_note

        padding = "This is filler background context with no specific new information. " * 5
        assert len(padding) > 280, "test setup: padding must push the real fact past the old 280-char cut"
        fact = "IMPORTANT SPECIFIC FACT: the badge number on record is XJ-9931."
        content = padding + fact

        note = format_reasoning_search_note({
            "primary_query": "q", "contradiction_query": "cq",
            "supporting": [{"title": "Source A", "content": content, "url": "http://x"}],
            "complicating": [], "has_complicating": False,
        })

        assert content in note, "full content (past char 280) must appear verbatim, uncut"
        assert fact in note

    def test_complicating_content_also_not_truncated(self):
        from backend.services.chat_modes_service import format_reasoning_search_note

        padding = "Generic contextual filler sentence repeated for length purposes only. " * 5
        assert len(padding) > 280
        fact = "The recall affected exactly 14,200 units manufactured in Q3."
        content = padding + fact

        note = format_reasoning_search_note({
            "primary_query": "q", "contradiction_query": "cq",
            "supporting": [],
            "complicating": [{"title": "Source B", "content": content, "url": "http://y"}],
            "has_complicating": True,
        })

        assert content in note
        assert fact in note


# ─────────────────────────────────────────────────────────────────────────────
# Phase M — complexity-scaled selection caps.
#
# The caps only ever change what is KEPT. Every test here feeds a fixed raw
# pool through _safe_search, so the fetch side is held constant by
# construction — which is the point: proving the total moves without the
# number of searches moving.
# ─────────────────────────────────────────────────────────────────────────────

class TestComplexityScaledCaps:
    def _pool(self, monkeypatch, n_primary=5, n_contra=5):
        primary_raw = [_article(f"p{i}") for i in range(n_primary)]
        contra_raw  = [_article(f"c{i}") for i in range(n_contra)]
        calls = iter([primary_raw, contra_raw])
        monkeypatch.setattr(wsr, "_safe_search", lambda query, meta=None: next(calls))

    def test_caps_for_maps_each_tier(self):
        assert wsr._caps_for("simple")  == (2, 2)
        assert wsr._caps_for("complex") == (5, 4)

    @pytest.mark.parametrize("unknown", [None, "", "moderate", "COMPLEX", "unknown"])
    def test_unknown_complexity_falls_back_to_todays_fixed_three_plus_three(self, unknown):
        """
        The router genuinely returns None on failure (30.8% of real logged
        calls), so this fallback is a live path, not a theoretical one.
        Case-sensitive on purpose: only the exact literals the router emits
        change behaviour, anything else is treated as "unknown".
        """
        assert wsr._caps_for(unknown) == (wsr._PRIMARY_MAX, wsr._CONTRADICTION_MAX) == (3, 3)

    def test_simple_keeps_fewer_than_the_old_fixed_six(self, monkeypatch):
        self._pool(monkeypatch)
        r = wsr.fetch_reasoned_results("msg", complexity="simple")
        assert len(r["supporting"]) == 2
        assert len(r["complicating"]) == 2
        assert len(r["all_articles"]) == 4 < 6

    def test_complex_keeps_more_than_the_old_fixed_six(self, monkeypatch):
        self._pool(monkeypatch)
        r = wsr.fetch_reasoned_results("msg", complexity="complex")
        assert len(r["supporting"]) == 5
        assert len(r["complicating"]) == 4
        assert len(r["all_articles"]) == 9 > 6

    def test_no_complexity_argument_is_byte_identical_to_before_this_phase(self, monkeypatch):
        self._pool(monkeypatch)
        r = wsr.fetch_reasoned_results("msg")
        assert len(r["supporting"]) == 3 and len(r["complicating"]) == 3
        assert len(r["all_articles"]) == 6

    def test_complex_under_fills_gracefully_when_the_pool_is_short(self, monkeypatch):
        """
        A thin pool must slice short, never pad, never raise. Real pools do run
        thin: measured complicating availability was as low as 1 after dedup.
        """
        self._pool(monkeypatch, n_primary=2, n_contra=1)
        r = wsr.fetch_reasoned_results("msg", complexity="complex")
        assert len(r["supporting"]) == 2
        assert len(r["complicating"]) == 1
        assert len(r["all_articles"]) == 3

    def test_search_count_is_two_regardless_of_tier(self, monkeypatch):
        """The whole cost argument rests on this: tiers change selection, not fetch."""
        for tier in (None, "simple", "complex"):
            seen: list[str] = []
            primary_raw = [_article(f"p{i}") for i in range(5)]
            contra_raw  = [_article(f"c{i}") for i in range(5)]
            calls = iter([primary_raw, contra_raw])

            def _spy(query, meta=None):
                seen.append(query)
                return next(calls)

            monkeypatch.setattr(wsr, "_safe_search", _spy)
            wsr.fetch_reasoned_results("msg", complexity=tier)
            assert len(seen) == 2, f"tier {tier!r} made {len(seen)} searches, expected 2"


class TestPhaseECitationAlignmentIsCountAgnostic:
    """
    Phase E numbers sources by enumerate(supporting, 1) then
    enumerate(complicating, len(supporting) + 1), and chat_tools builds
    `artifact` from supporting + complicating in that same order. Nothing in
    that mechanism references a count, so artifact[N-1] must be the article
    the note labelled [N] at ANY total — asserted here at the two totals this
    phase actually introduces, plus the degenerate ends.
    """

    @pytest.mark.parametrize("n_sup,n_com", [(2, 2), (5, 4), (1, 0), (0, 3), (5, 5), (3, 3)])
    def test_note_numbering_matches_artifact_index(self, monkeypatch, n_sup, n_com):
        import re
        from backend.services.chat_modes_service import format_reasoning_search_note

        supporting   = [_article(f"s{i}") for i in range(n_sup)]
        complicating = [_article(f"x{i}") for i in range(n_com)]
        reasoning = {
            "primary_query": "q", "contradiction_query": "cq",
            "supporting": supporting, "complicating": complicating,
            "has_complicating": bool(complicating),
        }
        note = format_reasoning_search_note(reasoning)
        artifact = [
            {"title": a.get("title", "").strip(), "url": a.get("url", "")}
            for a in supporting + complicating
        ]

        pairs = re.findall(r"\[(\d+)\][^\n]*\n[^\n]*\n\s+Source: (\S+)", note)
        assert len(pairs) == n_sup + n_com, f"note numbered {len(pairs)}, expected {n_sup + n_com}"
        for num, url in pairs:
            i = int(num)
            assert artifact[i - 1]["url"] == url, f"[{i}] points at {url}, artifact has {artifact[i-1]['url']}"
        # Numbering is contiguous 1..N across BOTH sections, no restart.
        assert [int(n) for n, _ in pairs] == list(range(1, n_sup + n_com + 1))
