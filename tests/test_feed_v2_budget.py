"""
Phase 3 budget test: the HARD RULE — a section_writer call must allocate >= 60%
of its input budget to source content.
"""
from backend.services.feed_v2 import budget


def test_section_writer_sources_at_least_60pct_of_input_budget():
    for model in ("gemini-3-flash-preview", "nemotron-super-120b"):
        ib = budget.input_budget(model)
        floor = budget.section_writer_source_floor(model)
        assert floor >= 0.60 * ib

        # Ample source material -> packing fills to the floor.
        big = "token " * 200_000
        sources = [
            {"tier": "primary", "rank_score": 9.0, "full_text": big},
            {"tier": "mid", "rank_score": 5.0, "key_passages": big},
            {"tier": "tail", "rank_score": 1.0, "title": "t", "abstract": "a"},
        ]
        packed = budget.pack_section_writer_sources(model, sources)
        assert packed["tokens"] >= 0.60 * ib, (model, packed["tokens"], 0.60 * ib)


def test_input_budget_formula():
    # min(context - max_output, tpm_ceiling) * margin
    b = budget.MODEL_BUDGETS["nemotron-nano-30b"]
    expected = int(min(b.context_window - b.max_output, b.tpm_ceiling) * b.safety_margin)
    assert budget.input_budget("nemotron-nano-30b") == expected


def test_rank_ordered_truncation_prefers_primary():
    # Small budget: only the primary's full extract should make it in.
    sources = [
        {"tier": "tail", "rank_score": 1.0, "title": "tail", "abstract": "z"},
        {"tier": "primary", "rank_score": 9.0, "full_text": "PRIMARY " * 10},
        {"tier": "mid", "rank_score": 5.0, "key_passages": "MID " * 10},
    ]
    packed = budget.pack_sources(sources, token_budget=12)
    assert packed["text"].startswith("PRIMARY")
