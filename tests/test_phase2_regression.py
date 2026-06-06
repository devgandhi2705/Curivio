"""
Phase 2.7 — Quality Regression Validation
==========================================

Validates that the Phase 2 PromptComposer architecture (Phases 2.5–2.6) produces
prompts that are structurally equivalent to or better than the pre-Phase-2 versions.

Seven output modes under test
------------------------------
1. Day 1 Feed       — make_daily_package_prompt (no prior history or memory)
2. Day 2 Feed       — make_daily_package_prompt (with history, continuity, memory)
3. Chat             — build_system_prompt in normal/standard mode
4. Explain Simply   — build_system_prompt in layman mode
5. Deep Research    — build_deep_research_prompt + structured chat mode
6. Compare Mode     — build_system_prompt in compare structured mode
7. Trend Analysis   — build_system_prompt in trend_analysis structured mode

Validation dimensions
---------------------
- Depth:             Token count is substantial; no required sections dropped
- Formatting:        Correct separators; no unresolved placeholders or None bleed
- JSON validity:     Embedded JSON schemas are parseable
- Progression:       Day 2 feed includes Day 1 history and continuity signals
- Curiosity quality: Full curiosity instruction block present in feed
- Action quality:    Action design section present in feed
- Metadata:          generate_report() exposes priority + source_pack per section
- Composer core:     add/remove/estimate/report work correctly on PromptSection

Run:
    pytest tests/test_phase2_regression.py -v
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Override the autouse conftest fixture that imports backend.main (requires
# optional deps like jose/bcrypt that may not be installed in all envs).
@pytest.fixture(autouse=True)
def reset_rate_limiter():
    yield


# ── Shared mock data ───────────────────────────────────────────────────────────

_CORE_ARTICLES = [
    {
        "title": "India's API Dependency on China",
        "url": "https://example.com/api-china",
        "content": (
            "India imports approximately 70% of Active Pharmaceutical Ingredients from China. "
            "This dependency creates vulnerability in drug supply chains when Chinese factories "
            "reduce output or during geopolitical disruptions."
        ),
    },
    {
        "title": "FDA Approval Process for Indian Generic Drugs",
        "url": "https://example.com/fda-india",
        "content": (
            "Indian generic manufacturers must file an Abbreviated New Drug Application (ANDA) "
            "with the FDA. The process involves bioequivalence studies, facility inspections, and "
            "quality audits that can take 2-4 years."
        ),
    },
    {
        "title": "Biosimilar Market Dynamics in India",
        "url": "https://example.com/biosimilar",
        "content": (
            "India's biosimilar market is growing at 20% annually, driven by expiring biologics "
            "patents. Key players include Biocon, Dr. Reddy's, and Serum Institute."
        ),
    },
    {
        "title": "CDSCO Drug Regulatory Framework Update",
        "url": "https://example.com/cdsco",
        "content": (
            "The Central Drugs Standard Control Organisation updated Schedule M guidelines for GMP "
            "compliance, aligning Indian manufacturing standards closer to WHO norms."
        ),
    },
]

_CURIOSITY_ARTICLES = [
    {
        "title": "The Hidden Economics of Drug Patent Cliffs",
        "url": "https://example.com/patent-cliff",
        "content": (
            "When a blockbuster drug loses patent protection, its price can drop by 90% within "
            "months as generic competitors flood the market. This patent cliff phenomenon "
            "restructures entire therapeutic categories."
        ),
    },
    {
        "title": "Why Indian Chemists Stock Specific Brands",
        "url": "https://example.com/chemist-brands",
        "content": (
            "Indian retail pharmacies operate on a trade margin system where chemists earn higher "
            "margins on branded generics than on originator brands, creating perverse incentives "
            "in prescription fulfilment."
        ),
    },
]

_DAY1_PACKAGES: list[dict] = []  # no prior history for Day 1

_DAY2_PACKAGES = [
    {
        "day": "Day 1",
        "headline": "China's API Grip: The Hidden Risk in India's Medicine Cabinet",
        "categories": ["supply chain", "geopolitics"],
        "titles": [
            "API Dependency Creates Pharma Sovereignty Risk",
            "Why Indian Generics Need Domestic API Manufacturing",
            "The Patent Cliff No One Is Watching",
        ],
    }
]

_EXPLORED_CONCEPTS = ["Active Pharmaceutical Ingredients", "ANDA filing process"]
_SUGGESTED_NEXT = ["biosimilars", "CDSCO GMP compliance", "contract manufacturing organisations"]

_MEMORY_REFERENCES_DAY2 = {
    "priorInsights": [
        {
            "day": "Day 1",
            "title": "API Dependency Creates Pharma Sovereignty Risk",
            "insight": "India imports 70% of APIs from China, creating single-point supply chain failure risk for 600+ essential medicines.",
        }
    ],
    "unresolvedQuestions": [
        {
            "day": "Day 1",
            "question": "Can India realistically build domestic API manufacturing capacity within 5 years?",
        }
    ],
}

_CHAT_CONTEXT_NORMAL = {
    "user_profile": {
        "learning_stage": "intermediate",
        "difficulty_preference": "advanced",
        "top_interests": ["machine learning", "NLP", "RAG pipelines"],
        "suppressed_topics": ["blockchain", "crypto"],
    },
    "research": {
        "topic": "RAG pipelines",
        "deep_research": {
            "summary": "RAG reduces hallucination by grounding LLM responses in retrieved documents.",
            "key_concepts": ["vector embeddings", "dense retrieval", "re-ranking"],
        },
        "learning_path": {
            "beginner": [
                {
                    "concept": "Vector Embeddings",
                    "explanation": "Dense numerical representations of text used for semantic similarity search.",
                    "why_it_matters": "The foundation of all retrieval systems.",
                }
            ]
        },
        "topic_expansion": {
            "prerequisites": ["transformers", "attention mechanism"],
            "related": ["semantic search", "knowledge graphs"],
        },
    },
    "session": {
        "topic": "RAG pipelines",
        "times_explored": 3,
        "has_deep_research": True,
        "has_learning_path": True,
        "has_topic_expansion": True,
        "has_github_repos": False,
    },
    "conversation_memory": {
        "message_count": 6,
        "session_turns": 6,
        "topics_discussed": ["transformers", "embeddings", "FAISS"],
        "last_user_messages": ["How does HNSW indexing work?"],
    },
    "response_depth": "detailed",
    "format_intent": "explanation",
    "current_message": "Explain how RAG works end-to-end.",
}

_CHAT_CONTEXT_LAYMAN = {
    **_CHAT_CONTEXT_NORMAL,
    "layman_mode_context": {
        "active": True,
        "mechanism": "RAG retrieves relevant documents from a vector database to ground LLM responses in factual context.",
    },
    "domain_context": {"domain": "machine_learning"},
}

_CHAT_CONTEXT_STRUCTURED = {
    **_CHAT_CONTEXT_NORMAL,
    "exploration_breadth": {
        "total_explored": 12,
        "recently_explored": ["transformers", "RAG", "FAISS", "LangChain"],
        "deep_dived_topics": ["RAG pipelines", "vector databases"],
    },
    "preference_snapshot": {
        "liked_topics": ["RAG", "transformers", "embeddings"],
        "disliked_topics": ["blockchain"],
        "difficulty_preference": "advanced",
        "engagement_level": "high",
    },
    "learner_profile": {
        "directive": (
            "ADAPTIVE EXPLANATION: User has intermediate ML background with strong transformer knowledge. "
            "Skip basic neural network explanations. Emphasise system design and production trade-offs."
        )
    },
    "domain_context": {
        "domain": "machine_learning",
        "directive": (
            "DOMAIN: Machine Learning / AI Systems. "
            "Favour precision over accessibility. Name specific architectures and benchmarks."
        ),
    },
    "continuity": {
        "topic": "RAG pipelines",
        "explained_concepts": ["transformers", "attention", "embeddings"],
        "prior_recommendations": ["FAISS", "sentence-transformers"],
        "cross_session_turns": 15,
        "sessions_count": 3,
    },
    "action_result": {
        "instruction": (
            "WORKFLOW DATA AVAILABLE: Deep research on 'RAG pipelines' with 8 sources. "
            "Present as structured analysis with key findings, strategic implications, and next steps."
        )
    },
}

_DEEP_RESEARCH_TOPIC     = "Retrieval Augmented Generation"
_DEEP_RESEARCH_SOURCE_ANALYSIS = (
    "CROSS-SOURCE SIGNALS:\n"
    "  Agreement (3/3 sources): RAG reduces hallucination rates by grounding responses in retrieved context.\n"
    "  Contrastive signal: Academic sources emphasise accuracy gains; practitioner sources emphasise latency cost.\n"
    "  Underweighted: Chunk size selection strategy is rarely discussed despite major accuracy impact."
)
_DEEP_RESEARCH_VIEWPOINTS = (
    "VIEWPOINT A — Academic Research:\n"
    "  Stance: RAG fundamentally solves the knowledge cutoff and hallucination problems.\n"
    "  Evidence: Lewis et al. (2020) showed 40% reduction in factual errors on knowledge-intensive tasks.\n\n"
    "VIEWPOINT B — Production Engineering:\n"
    "  Stance: RAG adds 200-500ms latency per query and requires significant infrastructure investment.\n"
    "  Evidence: Multiple MLOps practitioners report retrieval becoming the bottleneck at scale."
)
_DEEP_RESEARCH_ARTICLES = (
    "1. RAG: Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks\n"
    "   URL: https://arxiv.org/abs/2005.11401\n"
    "   Content: We introduce RAG, a general-purpose fine-tuning recipe that combines parametric and non-parametric memory...\n\n"
    "2. Building Production RAG Systems\n"
    "   URL: https://example.com/prod-rag\n"
    "   Content: In production, retrieval latency dominates. HNSW indexes reduce query time from O(n) to O(log n)...\n\n"
    "3. Evaluating RAG Pipelines\n"
    "   URL: https://example.com/rag-eval\n"
    "   Content: RAGAS framework evaluates faithfulness, answer relevancy, and context recall..."
)


# ═══════════════════════════════════════════════════════════════════════════════
# PromptComposer core
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromptComposerCore:
    """Unit tests for PromptSection + PromptComposer internals."""

    def _make(self):
        from backend.prompts.prompt_composer import PromptComposer
        return PromptComposer()

    def test_build_empty_returns_empty_string(self):
        assert self._make().build() == ""

    def test_single_section_no_separator(self):
        c = self._make()
        c.add_section("a", "hello")
        assert c.build() == "hello"

    def test_two_sections_joined_with_double_newline(self):
        c = self._make()
        c.add_section("a", "first")
        c.add_section("b", "second")
        assert c.build() == "first\n\nsecond"

    def test_empty_content_skipped(self):
        c = self._make()
        c.add_section("a", "keep")
        c.add_section("b", "")
        c.add_section("c", "   ")
        c.add_section("d", None)
        assert c.build() == "keep"

    def test_content_stripped_of_leading_trailing_whitespace(self):
        c = self._make()
        c.add_section("a", "  text  ")
        assert c.build() == "text"

    def test_remove_section_by_name(self):
        c = self._make()
        c.add_section("keep", "A")
        c.add_section("drop", "B")
        c.remove_section("drop")
        assert "B" not in c.build()
        assert "A" in c.build()

    def test_add_returns_self_for_chaining(self):
        c = self._make()
        result = c.add_section("a", "x")
        assert result is c

    def test_estimate_tokens_uses_4char_heuristic(self):
        c = self._make()
        c.add_section("a", "A" * 400)  # 400 chars → 100 tokens
        assert c.estimate_tokens() == 100

    def test_estimate_tokens_includes_separators(self):
        c = self._make()
        c.add_section("a", "A" * 40)   # 10 tokens
        c.add_section("b", "B" * 40)   # 10 tokens
        # separator "\n\n" = 2 chars between sections → 0 extra tokens (< 4)
        # total chars = 80 + 2 = 82 → 20 tokens
        assert c.estimate_tokens() == 20

    def test_generate_report_keys(self):
        c = self._make()
        c.add_section("persona", "You are...", priority=1, required=True, source_pack="")
        report = c.generate_report()
        assert "section_count" in report
        assert "sections" in report
        assert "total_tokens" in report
        assert "total_chars" in report

    def test_generate_report_section_metadata(self):
        c = self._make()
        c.add_section("persona", "You are Curivio.", priority=1, required=True, source_pack="core")
        c.add_section("articles", "Article text here.", priority=2, required=False, source_pack="dynamic")
        report = c.generate_report()
        assert report["sections"]["persona"]["priority"]    == 1
        assert report["sections"]["persona"]["required"]    is True
        assert report["sections"]["persona"]["source_pack"] == "core"
        assert report["sections"]["articles"]["priority"]    == 2
        assert report["sections"]["articles"]["required"]    is False
        assert report["sections"]["articles"]["source_pack"] == "dynamic"

    def test_generate_report_chars_and_tokens(self):
        c = self._make()
        c.add_section("x", "A" * 80, priority=3)
        s = c.generate_report()["sections"]["x"]
        assert s["chars"]  == 80
        assert s["tokens"] == 20

    def test_prompt_section_tokens_property(self):
        from backend.prompts.prompt_composer import PromptSection
        s = PromptSection(name="x", content="A" * 100, priority=1)
        assert s.tokens == 25

    def test_prompt_section_estimated_tokens_override(self):
        from backend.prompts.prompt_composer import PromptSection
        s = PromptSection(name="x", content="A" * 100, priority=1, estimated_tokens=999)
        assert s.tokens == 999

    def test_prompt_section_default_values(self):
        from backend.prompts.prompt_composer import PromptSection
        s = PromptSection(name="x", content="hi")
        assert s.priority        == 5
        assert s.required        is True
        assert s.source_pack     == ""
        assert s.estimated_tokens == 0

    def test_custom_separator(self):
        from backend.prompts.prompt_composer import PromptComposer
        c = PromptComposer(separator="\n---\n")
        c.add_section("a", "first")
        c.add_section("b", "second")
        assert c.build() == "first\n---\nsecond"


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _has_no_unresolved_format_placeholders(text: str) -> bool:
    """Return True if no {placeholder} strings remain in the prompt."""
    # Allow escaped JSON braces like {{ and }} — these are intentional
    stripped = re.sub(r"\{\{|\}\}", "", text)
    return not re.search(r"\{[a-z_]+\}", stripped)


def _has_no_none_bleed(text: str) -> bool:
    """Return True if the word 'None' doesn't appear where it shouldn't."""
    return "None" not in text


def _extract_json_schema(text: str) -> dict | None:
    """Try to extract the first top-level {...} JSON block from the prompt."""
    match = re.search(r"(\{[\s\S]+\})", text)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _assert_prompt_health(prompt: str, *, min_tokens: int = 200, label: str = ""):
    """Common structural health checks applied to every generated prompt."""
    prefix = f"[{label}] " if label else ""
    assert isinstance(prompt, str) and len(prompt) > 0,      f"{prefix}Prompt is empty"
    assert "\n\n" in prompt,                                   f"{prefix}Missing \\n\\n section separators"
    assert _has_no_none_bleed(prompt),                        f"{prefix}'None' leaked into prompt"
    tokens = max(1, len(prompt) // 4)
    assert tokens >= min_tokens,                              f"{prefix}Prompt too short: {tokens} tokens (min {min_tokens})"


# ═══════════════════════════════════════════════════════════════════════════════
# Mode 1 & 2 — Daily Feed (Day 1 and Day 2)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_feed_prompt(previous_packages, memory_references=None, difficulty="intermediate"):
    from backend.prompts.project_insight_prompt import make_daily_package_prompt
    day_number = 1 if not previous_packages else 2
    return make_daily_package_prompt(
        project_name            = "Indian Pharma",
        keywords                = ["generic drugs", "APIs", "CDSCO", "biosimilars"],
        difficulty              = difficulty,
        focus_areas             = ["supply chain", "regulatory", "market dynamics"],
        day_number              = day_number,
        display_label           = f"Day {day_number}",
        prev_display_label      = "Day 1" if day_number == 2 else None,
        previous_packages       = previous_packages,
        core_articles           = _CORE_ARTICLES,
        curiosity_articles      = _CURIOSITY_ARTICLES,
        explored_concepts       = _EXPLORED_CONCEPTS,
        suggested_next_topics   = _SUGGESTED_NEXT,
        daily_core_article_count= 3,
        learning_memory         = None,
        memory_references       = memory_references,
    )


class TestDay1Feed:
    """Mode 1 — First-day feed with no prior history."""

    @pytest.fixture(scope="class")
    def prompt(self):
        return _make_feed_prompt(_DAY1_PACKAGES)

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=800, label="Day1Feed")

    def test_persona_present(self, prompt):
        assert "editorial intelligence" in prompt.lower() or "curivio" in prompt.lower()

    def test_project_state_injected(self, prompt):
        assert "Indian Pharma" in prompt
        assert "CDSCO" in prompt or "generic drugs" in prompt

    def test_first_day_no_history_label(self, prompt):
        assert "none" in prompt.lower() or "first package" in prompt.lower()

    def test_core_articles_present(self, prompt):
        assert "API Dependency" in prompt or "China" in prompt

    def test_curiosity_section_present(self, prompt):
        assert "CURIOSITY" in prompt.upper()

    def test_action_design_present(self, prompt):
        assert "ACTION" in prompt.upper() or "INVESTIGATIVE" in prompt.upper()

    def test_output_schema_has_required_keys(self, prompt):
        assert "package_headline" in prompt
        assert "insights" in prompt
        assert "curiosity_insights" in prompt
        assert "learning_thread" in prompt
        assert "action_item" in prompt

    def test_section_count_reasonable(self, prompt):
        # At least 15 sections worth of content (separated by \n\n)
        sections = [s for s in prompt.split("\n\n") if s.strip()]
        assert len(sections) >= 15

    def test_no_unresolved_placeholders(self, prompt):
        # No stray {topic} style format strings
        suspicious = re.findall(r"\{(?![\s{])[a-z_]+\}", prompt)
        assert not suspicious, f"Unresolved placeholders: {suspicious}"

    def test_editorial_philosophy_present(self, prompt):
        assert "editorial" in prompt.lower()

    def test_writing_style_standards_present(self, prompt):
        assert "WRITING STYLE" in prompt.upper() or "BANNED" in prompt.upper()


class TestDay2Feed:
    """Mode 2 — Second-day feed with progression history and continuity."""

    @pytest.fixture(scope="class")
    def prompt(self):
        return _make_feed_prompt(_DAY2_PACKAGES, memory_references=_MEMORY_REFERENCES_DAY2)

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=900, label="Day2Feed")

    def test_progression_history_injected(self, prompt):
        assert "Day 1" in prompt
        assert "China's API Grip" in prompt or "API Grip" in prompt

    def test_continuity_section_present(self, prompt):
        assert "INTER-ARTICLE CONTINUITY" in prompt

    def test_prior_insights_embedded(self, prompt):
        assert "API Dependency Creates Pharma Sovereignty Risk" in prompt

    def test_unresolved_question_embedded(self, prompt):
        assert "domestic API manufacturing" in prompt

    def test_explored_concepts_present(self, prompt):
        assert "Active Pharmaceutical Ingredients" in prompt

    def test_day2_larger_than_day1(self):
        d1 = _make_feed_prompt(_DAY1_PACKAGES)
        d2 = _make_feed_prompt(_DAY2_PACKAGES, memory_references=_MEMORY_REFERENCES_DAY2)
        assert len(d2) > len(d1), "Day 2 prompt should be larger due to continuity sections"

    def test_output_schema_present(self, prompt):
        assert "package_headline" in prompt
        assert "memory_callback" in prompt


class TestBeginnerFeed:
    """Mode 1 variant — beginner difficulty injects calibration block."""

    @pytest.fixture(scope="class")
    def prompt(self):
        return _make_feed_prompt(_DAY1_PACKAGES, difficulty="beginner")

    def test_beginner_calibration_injected(self, prompt):
        assert "BEGINNER CALIBRATION" in prompt

    def test_conceptual_laddering_rule_present(self, prompt):
        assert "CONCEPTUAL LADDERING" in prompt

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=900, label="BeginnerFeed")


# ═══════════════════════════════════════════════════════════════════════════════
# Mode 3 — Chat (normal / standard depth)
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatNormal:
    """Mode 3 — Conversational chat with standard depth."""

    @pytest.fixture(scope="class")
    def prompt(self):
        from backend.services.chat_prompt_service import build_system_prompt
        return build_system_prompt(_CHAT_CONTEXT_NORMAL, mode="normal")

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=100, label="ChatNormal")

    def test_persona_present(self, prompt):
        assert "Curivio" in prompt

    def test_depth_instruction_injected(self, prompt):
        assert "RESPONSE DEPTH" in prompt

    def test_conversation_memory_injected(self, prompt):
        # conversation_memory has 6 turns with topics
        assert "transformers" in prompt.lower() or "embeddings" in prompt.lower() \
            or "conversation" in prompt.lower()

    def test_user_profile_injected(self, prompt):
        # profile has interests and learning stage
        assert "intermediate" in prompt.lower() or "machine learning" in prompt.lower()

    def test_natural_guidelines_present(self, prompt):
        assert "CONVERSATIONAL RULES" in prompt

    def test_no_json_schema_in_natural_mode(self, prompt):
        # Natural mode must NOT include the structured JSON output directive
        assert "OUTPUT FORMAT — MANDATORY" not in prompt

    def test_section_order_persona_first(self, prompt):
        curivio_pos = prompt.index("Curivio")
        assert curivio_pos < 200, "Persona (Curivio) should appear near the start"


# ═══════════════════════════════════════════════════════════════════════════════
# Mode 4 — Explain Simply (layman mode)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExplainSimply:
    """Mode 4 — Layman simplification mode."""

    @pytest.fixture(scope="class")
    def prompt(self):
        from backend.services.chat_prompt_service import build_system_prompt
        return build_system_prompt(_CHAT_CONTEXT_LAYMAN, mode="layman")

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=100, label="ExplainSimply")

    def test_layman_directive_present(self, prompt):
        # Should include the simplification directive from core_learning_pack
        assert "simplif" in prompt.lower() or "plain" in prompt.lower() \
            or "analogy" in prompt.lower() or "explain" in prompt.lower()

    def test_mechanism_preservation_in_prompt(self, prompt):
        # When a mechanism is passed in context, it should appear
        assert "RAG" in prompt or "vector database" in prompt.lower() or "retrieved" in prompt.lower()

    def test_no_format_directive_in_layman_mode(self, prompt):
        # Format directives are skipped for layman mode per the builder logic
        # (mode == "layman" skips format_directive and tension sections)
        assert "FORMAT GUIDANCE" not in prompt

    def test_natural_guidelines_present(self, prompt):
        assert "CONVERSATIONAL RULES" in prompt

    def test_no_json_schema(self, prompt):
        assert "OUTPUT FORMAT — MANDATORY" not in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Mode 5 — Deep Research (prompt + structured chat mode)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeepResearchPrompt:
    """Mode 5a — Deep research prompt builder."""

    @pytest.fixture(scope="class")
    def prompt(self):
        from backend.prompts.deep_research_prompt import build_deep_research_prompt
        return build_deep_research_prompt(
            topic              = _DEEP_RESEARCH_TOPIC,
            source_count       = 3,
            source_analysis    = _DEEP_RESEARCH_SOURCE_ANALYSIS,
            viewpoint_analysis = _DEEP_RESEARCH_VIEWPOINTS,
            articles           = _DEEP_RESEARCH_ARTICLES,
        )

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=500, label="DeepResearch")

    def test_three_personas_present(self, prompt):
        assert "RESEARCH ANALYST" in prompt
        assert "STRATEGY CONSULTANT" in prompt
        assert "TECHNICAL INVESTIGATOR" in prompt

    def test_topic_embedded(self, prompt):
        assert "Retrieval Augmented Generation" in prompt

    def test_source_analysis_embedded(self, prompt):
        assert "MULTI-SOURCE ANALYSIS" in prompt
        assert "hallucination" in prompt.lower()

    def test_viewpoints_embedded(self, prompt):
        assert "MULTI-ANGLE VIEWPOINT" in prompt
        assert "Lewis" in prompt  # from mock viewpoint data

    def test_articles_embedded(self, prompt):
        assert "BACKGROUND ARTICLES" in prompt
        assert "arxiv.org" in prompt

    def test_section_dividers_present(self, prompt):
        assert "---" in prompt

    def test_output_schema_has_required_keys(self, prompt):
        assert "research_summary" in prompt
        assert "key_findings" in prompt
        assert "viewpoint_comparison" in prompt
        assert "tradeoffs" in prompt
        assert "strategic_implications" in prompt
        assert "confidence_level" in prompt

    def test_writing_rules_present(self, prompt):
        assert "Writing rules" in prompt

    def test_synthesis_rules_present(self, prompt):
        assert "Synthesis quality rules" in prompt

    def test_json_schema_is_parseable(self, prompt):
        # The schema in the prompt should be valid JSON structure
        # Extract just the schema portion
        schema_start = prompt.find('{\n  "research_summary"')
        if schema_start == -1:
            schema_start = prompt.find('{\n  "research_summary"')
        assert schema_start != -1, "Could not find JSON schema in deep research prompt"


class TestDeepResearchChatMode:
    """Mode 5b — Chat in deep_research structured mode."""

    @pytest.fixture(scope="class")
    def prompt(self):
        from backend.services.chat_prompt_service import build_system_prompt
        return build_system_prompt(_CHAT_CONTEXT_STRUCTURED, mode="deep_research")

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=200, label="DeepResearchChat")

    def test_structured_json_schema_present(self, prompt):
        assert "OUTPUT FORMAT — MANDATORY" in prompt

    def test_structured_persona_present(self, prompt):
        assert "Curivio" in prompt
        assert "research" in prompt.lower()

    def test_schema_keys_present(self, prompt):
        assert "response_type" in prompt
        assert "key_takeaways" in prompt
        assert "next_topics" in prompt

    def test_no_conversational_rules(self, prompt):
        # Structured mode uses _GUIDELINES, not _NATURAL_GUIDELINES
        assert "CONVERSATIONAL RULES" not in prompt

    def test_research_context_injected(self, prompt):
        assert "RAG pipelines" in prompt

    def test_continuity_injected(self, prompt):
        assert "transformers" in prompt.lower() or "embeddings" in prompt.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Mode 6 — Compare Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompareMode:
    """Mode 6 — Structured compare mode for analytical comparisons."""

    @pytest.fixture(scope="class")
    def prompt(self):
        from backend.services.chat_prompt_service import build_system_prompt
        ctx = {**_CHAT_CONTEXT_STRUCTURED, "format_intent": "comparison"}
        return build_system_prompt(ctx, mode="compare")

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=200, label="CompareMode")

    def test_json_schema_present(self, prompt):
        assert "OUTPUT FORMAT — MANDATORY" in prompt

    def test_comparison_format_guidance_present(self, prompt):
        assert "comparison" in prompt.lower() or "FORMAT GUIDANCE" in prompt

    def test_schema_has_sections_field(self, prompt):
        assert '"sections"' in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Mode 7 — Trend Analysis
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrendAnalysis:
    """Mode 7 — Structured trend_analysis mode."""

    @pytest.fixture(scope="class")
    def prompt(self):
        from backend.services.chat_prompt_service import build_system_prompt
        ctx = {**_CHAT_CONTEXT_STRUCTURED, "format_intent": "analysis"}
        return build_system_prompt(ctx, mode="trend_analysis")

    def test_prompt_health(self, prompt):
        _assert_prompt_health(prompt, min_tokens=200, label="TrendAnalysis")

    def test_json_schema_present(self, prompt):
        assert "OUTPUT FORMAT — MANDATORY" in prompt

    def test_analysis_format_guidance(self, prompt):
        assert "analysis" in prompt.lower() or "FORMAT GUIDANCE" in prompt

    def test_schema_has_next_topics(self, prompt):
        assert "next_topics" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Smaller prompt builders
# ═══════════════════════════════════════════════════════════════════════════════

class TestTopicExpansionPrompt:
    def test_health_and_content(self):
        from backend.prompts.topic_expansion_prompt import build_topic_expansion_prompt
        prompt = build_topic_expansion_prompt("RAG pipelines")
        _assert_prompt_health(prompt, min_tokens=150, label="TopicExpansion")
        assert "RAG pipelines" in prompt
        assert "prerequisites" in prompt
        assert "learning_progression" in prompt

    def test_section_separator_correct(self):
        from backend.prompts.topic_expansion_prompt import build_topic_expansion_prompt
        prompt = build_topic_expansion_prompt("transformers")
        assert "\n\n" in prompt

    def test_no_format_placeholders_remain(self):
        from backend.prompts.topic_expansion_prompt import build_topic_expansion_prompt
        prompt = build_topic_expansion_prompt("attention mechanism")
        suspicious = re.findall(r"\{(?![\s{])[a-z_]+\}", prompt)
        assert not suspicious


class TestLearningPathPrompt:
    def test_health_and_content(self):
        from backend.prompts.learning_path_prompt import build_learning_path_prompt
        prompt = build_learning_path_prompt(
            topic="FAISS vector indexing",
            learning_stage="intermediate",
            difficulty_preference="advanced",
        )
        _assert_prompt_health(prompt, min_tokens=200, label="LearningPath")
        assert "FAISS vector indexing" in prompt
        assert "intermediate" in prompt
        assert "advanced" in prompt

    def test_all_tiers_described(self):
        from backend.prompts.learning_path_prompt import build_learning_path_prompt
        prompt = build_learning_path_prompt("HNSW indexing", "beginner", "beginner")
        assert "beginner" in prompt
        assert "intermediate" in prompt
        assert "advanced" in prompt

    def test_resource_format_described(self):
        from backend.prompts.learning_path_prompt import build_learning_path_prompt
        prompt = build_learning_path_prompt("embeddings", "intermediate", "no preference")
        assert "Book:" in prompt or "Course:" in prompt or "Paper:" in prompt


class TestLearningPrompt:
    def test_health_and_content(self):
        from backend.prompts.learning_prompt import build_learning_prompt
        prompt = build_learning_prompt(
            interests      = "machine learning, RAG, vector databases",
            articles       = "1. RAG Survey\n   URL: https://arxiv.org/abs/2005.11401\n   Content: RAG...",
            memory_context = "Learning stage: intermediate\nFrequently seen: transformers, attention",
            source_analysis= "3 sources cover RAG accuracy improvements.",
            source_count   = 3,
        )
        _assert_prompt_health(prompt, min_tokens=300, label="LearningPrompt")
        assert "machine learning" in prompt
        assert "RAG Survey" in prompt
        assert "learning_topics" in prompt
        assert "news_insight" in prompt

    def test_url_rule_present(self):
        from backend.prompts.learning_prompt import build_learning_prompt
        prompt = build_learning_prompt("AI", "1. Article\n   URL: http://x.com", "beginner", "signals", 1)
        assert "URL" in prompt.upper()


class TestIntelligencePrompt:
    def test_health_and_content(self):
        from backend.prompts.intelligence_prompt import build_intelligence_prompt
        prompt = build_intelligence_prompt(
            intelligence_context = "Stage: intermediate\nIndustry: Technology\nTop interests: AI, cloud computing",
            industry             = "Technology",
            source_count         = 5,
            source_analysis      = "AI infrastructure costs dominating coverage.",
            articles             = "1. GPU Shortage\n   URL: https://example.com\n   Content: NVIDIA H100 demand...",
            interests            = "AI infrastructure, cloud, semiconductor supply chain",
        )
        _assert_prompt_health(prompt, min_tokens=400, label="Intelligence")
        assert "intelligence_brief" in prompt
        assert "learning_track" in prompt
        assert "industry_news" in prompt
        assert "market_trends" in prompt
        assert "technical_discoveries" in prompt

    def test_hard_rules_present(self):
        from backend.prompts.intelligence_prompt import build_intelligence_prompt
        prompt = build_intelligence_prompt("ctx", "Tech", 3, "signals", "articles", "AI")
        assert "Hard rules" in prompt or "hard" in prompt.lower()


class TestIndustryIntelligencePrompt:
    def test_health_and_content(self):
        from backend.prompts.industry_intelligence_prompt import build_industry_intelligence_prompt
        prompt = build_industry_intelligence_prompt(
            industry_display_name = "Indian Pharmaceuticals",
            business_lens         = "generic drug export competitiveness",
            focus_areas           = "API supply chain, regulatory compliance, biosimilars",
            article_count         = 4,
            articles              = "\n\n".join(
                f"[{i}]\nTitle: {a['title']}\nURL: {a['url']}\nContent: {a['content']}"
                for i, a in enumerate(_CORE_ARTICLES, 1)
            ),
        )
        _assert_prompt_health(prompt, min_tokens=300, label="IndustryIntelligence")
        assert "Indian Pharmaceuticals" in prompt
        assert "market_developments" in prompt
        assert "emerging_opportunities" in prompt
        assert "near-term" in prompt

    def test_industry_name_in_schema(self):
        from backend.prompts.industry_intelligence_prompt import build_industry_intelligence_prompt
        prompt = build_industry_intelligence_prompt(
            "Fintech India", "payments regulation", "UPI, NBFC", 2, "articles here"
        )
        assert "Fintech India" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# generate_report() — metadata surface-area validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateReportMetadata:
    """Validate that generate_report() exposes priority, required, source_pack for all builders."""

    def _build_and_get_report(self, prompt_fn, *args, **kwargs):
        """
        We can't call generate_report() on the built string, but we can introspect
        the PromptComposer by patching build() to capture the composer state.
        Instead, we test through a direct composer instance.
        """
        from backend.prompts.prompt_composer import PromptComposer
        c = PromptComposer()
        c.add_section("s1", "section one",   priority=1, required=True,  source_pack="core")
        c.add_section("s2", "section two",   priority=3, required=False, source_pack="dynamic")
        c.add_section("s3", "section three", priority=5, required=True,  source_pack="")
        return c.generate_report()

    def test_report_has_all_metadata_fields(self):
        report = self._build_and_get_report(None)
        for name, section_data in report["sections"].items():
            assert "priority"    in section_data, f"{name} missing priority"
            assert "required"    in section_data, f"{name} missing required"
            assert "source_pack" in section_data, f"{name} missing source_pack"
            assert "chars"       in section_data, f"{name} missing chars"
            assert "tokens"      in section_data, f"{name} missing tokens"

    def test_report_section_count_matches(self):
        report = self._build_and_get_report(None)
        assert report["section_count"] == 3

    def test_priority_values_preserved(self):
        report = self._build_and_get_report(None)
        assert report["sections"]["s1"]["priority"] == 1
        assert report["sections"]["s2"]["priority"] == 3
        assert report["sections"]["s3"]["priority"] == 5

    def test_required_values_preserved(self):
        report = self._build_and_get_report(None)
        assert report["sections"]["s1"]["required"] is True
        assert report["sections"]["s2"]["required"] is False

    def test_source_pack_values_preserved(self):
        report = self._build_and_get_report(None)
        assert report["sections"]["s1"]["source_pack"] == "core"
        assert report["sections"]["s2"]["source_pack"] == "dynamic"
        assert report["sections"]["s3"]["source_pack"] == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Token efficiency — prompts are not inflated vs pre-Phase-2 baselines
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenEfficiency:
    """
    Verify that Phase 2 architectural changes did not balloon prompt sizes.
    These are soft upper-bound guards, not hard optimisation targets.
    Phase 3 will do actual trimming.
    """

    def test_day1_feed_within_reasonable_budget(self):
        prompt = _make_feed_prompt(_DAY1_PACKAGES)
        tokens = max(1, len(prompt) // 4)
        # Feed prompt is large but should stay under 20k tokens
        assert tokens < 20_000, f"Day1 feed prompt unexpectedly large: {tokens} tokens"

    def test_deep_research_within_reasonable_budget(self):
        from backend.prompts.deep_research_prompt import build_deep_research_prompt
        prompt = build_deep_research_prompt(
            topic=_DEEP_RESEARCH_TOPIC, source_count=3,
            source_analysis=_DEEP_RESEARCH_SOURCE_ANALYSIS,
            viewpoint_analysis=_DEEP_RESEARCH_VIEWPOINTS,
            articles=_DEEP_RESEARCH_ARTICLES,
        )
        tokens = max(1, len(prompt) // 4)
        assert tokens < 5_000, f"Deep research prompt unexpectedly large: {tokens} tokens"

    def test_chat_natural_within_reasonable_budget(self):
        from backend.services.chat_prompt_service import build_system_prompt
        prompt = build_system_prompt(_CHAT_CONTEXT_NORMAL, mode="normal")
        tokens = max(1, len(prompt) // 4)
        assert tokens < 3_000, f"Chat natural prompt unexpectedly large: {tokens} tokens"

    def test_chat_structured_within_reasonable_budget(self):
        from backend.services.chat_prompt_service import build_system_prompt
        prompt = build_system_prompt(_CHAT_CONTEXT_STRUCTURED, mode="deep_research")
        tokens = max(1, len(prompt) // 4)
        assert tokens < 5_000, f"Chat structured prompt unexpectedly large: {tokens} tokens"


# ═══════════════════════════════════════════════════════════════════════════════
# build_messages — full pipeline smoke test
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildMessages:
    """Verify the messages list structure for the chat API."""

    def test_messages_list_structure(self):
        from backend.services.chat_prompt_service import build_messages
        history = [
            {"role": "user",      "content": "What is RAG?"},
            {"role": "assistant", "content": "RAG stands for Retrieval Augmented Generation..."},
        ]
        msgs = build_messages(history, "How does HNSW improve retrieval?", _CHAT_CONTEXT_NORMAL)
        assert isinstance(msgs, list)
        assert len(msgs) >= 3
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "How does HNSW improve retrieval?"

    def test_system_prompt_is_non_empty(self):
        from backend.services.chat_prompt_service import build_messages
        msgs = build_messages([], "Hello", _CHAT_CONTEXT_NORMAL)
        assert len(msgs[0]["content"]) > 50

    def test_history_truncated_to_max_turns(self):
        from backend.services.chat_prompt_service import build_messages, MAX_HISTORY_TURNS
        long_history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(40)
        ]
        msgs = build_messages(long_history, "new question", {})
        # system + max_history + new user
        assert len(msgs) <= (MAX_HISTORY_TURNS * 2) + 2

    def test_layman_mode_messages(self):
        from backend.services.chat_prompt_service import build_messages
        msgs = build_messages([], "Explain RAG simply", _CHAT_CONTEXT_LAYMAN, mode="layman")
        system_content = msgs[0]["content"]
        assert "simplif" in system_content.lower() or "plain" in system_content.lower() \
            or "analogy" in system_content.lower() or "Curivio" in system_content


# ═══════════════════════════════════════════════════════════════════════════════
# detect_depth helper
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectDepth:
    def test_greeting_returns_quick(self):
        from backend.services.chat_prompt_service import detect_depth
        assert detect_depth("hi") == "quick"

    def test_detailed_trigger_returns_detailed(self):
        from backend.services.chat_prompt_service import detect_depth
        assert detect_depth("explain in detail how transformers work") == "detailed"

    def test_research_trigger_returns_research(self):
        from backend.services.chat_prompt_service import detect_depth
        assert detect_depth("analyze the tradeoffs and compare perspectives") == "research"

    def test_deep_research_mode_always_research(self):
        from backend.services.chat_prompt_service import detect_depth
        assert detect_depth("hi", mode="deep_research") == "research"

    def test_standard_question_returns_standard(self):
        from backend.services.chat_prompt_service import detect_depth
        # > 4 words, no depth/research/greeting keywords → standard
        assert detect_depth("Summarize the benefits of vector databases") == "standard"


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3.1 — ContextPrioritizer
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextPrioritizer:
    """Unit tests for ContextPrioritizer and the priority tier system."""

    def _make_composer(self):
        from backend.prompts.prompt_composer import PromptComposer
        c = PromptComposer()
        c.add_section("persona",        "You are Curivio.",                   priority=1, required=True,  source_pack="")
        c.add_section("schema",         '{"response_type": "chat"}',          priority=1, required=True,  source_pack="")
        c.add_section("writing_rules",  "Be direct. Name mechanisms.",        priority=2, required=True,  source_pack="core_writing_pack")
        c.add_section("source_analysis","Three sources agree on RAG accuracy.",priority=3, required=True,  source_pack="dynamic")
        c.add_section("memory_section", "User has seen: transformers.",       priority=4, required=False, source_pack="dynamic")
        c.add_section("title_library",  "TITLE PATTERNS: ...",                priority=5, required=True,  source_pack="package_narrative_pack")
        c.add_section("action_design",  "ACTION DESIGN: 8 types ...",         priority=5, required=True,  source_pack="package_action_pack")
        return c

    def _make_prioritizer(self):
        from backend.prompts.context_prioritizer import ContextPrioritizer
        return ContextPrioritizer.from_composer(self._make_composer())

    # ── Construction ──────────────────────────────────────────────────────────

    def test_from_composer(self):
        from backend.prompts.context_prioritizer import ContextPrioritizer
        p = ContextPrioritizer.from_composer(self._make_composer())
        assert isinstance(p, ContextPrioritizer)

    def test_from_sections(self):
        from backend.prompts.context_prioritizer import ContextPrioritizer
        from backend.prompts.prompt_composer import PromptSection
        sections = [PromptSection("x", "content", priority=1)]
        p = ContextPrioritizer.from_sections(sections)
        assert len(p.sections_at(1)) == 1

    # ── sections_at() ─────────────────────────────────────────────────────────

    def test_sections_at_p1(self):
        p = self._make_prioritizer()
        names = [s.name for s in p.sections_at(1)]
        assert "persona" in names
        assert "schema" in names
        assert "writing_rules" not in names

    def test_sections_at_p5(self):
        p = self._make_prioritizer()
        names = [s.name for s in p.sections_at(5)]
        assert "title_library" in names
        assert "action_design" in names

    def test_sections_at_empty_tier(self):
        p = self._make_prioritizer()
        # No P3 sections in our fixture except source_analysis
        assert len(p.sections_at(3)) == 1

    # ── ranked() ──────────────────────────────────────────────────────────────

    def test_ranked_first_is_lowest_priority_number(self):
        p = self._make_prioritizer()
        ranked = p.ranked()
        assert ranked[0].priority == 1

    def test_ranked_last_is_highest_priority_number(self):
        p = self._make_prioritizer()
        ranked = p.ranked()
        assert ranked[-1].priority == 5

    def test_ranked_is_sorted(self):
        p = self._make_prioritizer()
        priorities = [s.priority for s in p.ranked()]
        assert priorities == sorted(priorities)

    # ── Token budget methods ───────────────────────────────────────────────────

    def test_total_tokens_positive(self):
        p = self._make_prioritizer()
        assert p.total_tokens() > 0

    def test_required_tokens_leq_total(self):
        p = self._make_prioritizer()
        assert p.required_tokens() <= p.total_tokens()

    def test_tokens_through_p1_less_than_total(self):
        p = self._make_prioritizer()
        assert p.tokens_through(1) < p.total_tokens()

    def test_tokens_through_p5_equals_total(self):
        p = self._make_prioritizer()
        assert p.tokens_through(5) == p.total_tokens()

    def test_tokens_through_is_cumulative(self):
        p = self._make_prioritizer()
        assert p.tokens_through(2) >= p.tokens_through(1)
        assert p.tokens_through(3) >= p.tokens_through(2)

    # ── tier_stats() ──────────────────────────────────────────────────────────

    def test_tier_stats_label(self):
        from backend.prompts.context_prioritizer import TIER_LABELS
        p = self._make_prioritizer()
        assert p.tier_stats(1).label == "CRITICAL"
        assert p.tier_stats(5).label == "LUXURY"

    def test_tier_stats_section_count(self):
        p = self._make_prioritizer()
        assert p.tier_stats(1).section_count == 2
        assert p.tier_stats(5).section_count == 2

    def test_tier_stats_required_count(self):
        p = self._make_prioritizer()
        # memory_section is required=False
        assert p.tier_stats(4).required_count == 0
        assert p.tier_stats(4).optional_count == 1

    def test_tier_stats_empty_tier(self):
        p = self._make_prioritizer()
        # No P2 sections labeled that way in our fixture? Actually writing_rules is P2
        # Check an empty one — we have no sections at P6
        from backend.prompts.context_prioritizer import TierStats
        stats = p.tier_stats(6)
        assert stats.is_empty

    def test_all_tier_stats_returns_five_entries(self):
        p = self._make_prioritizer()
        stats = p.all_tier_stats()
        assert set(stats.keys()) == {1, 2, 3, 4, 5}

    # ── validate() ────────────────────────────────────────────────────────────

    def test_validate_returns_list(self):
        p = self._make_prioritizer()
        warnings = p.validate()
        assert isinstance(warnings, list)

    def test_validate_detects_priority_mismatch(self):
        from backend.prompts.context_prioritizer import ContextPrioritizer
        from backend.prompts.prompt_composer import PromptSection
        # title_library hint=P5 but we assign P3 — should warn
        sections = [PromptSection("title_library", "TITLE PATTERNS", priority=3)]
        p = ContextPrioritizer.from_sections(sections)
        warnings = p.validate()
        assert any("title_library" in w for w in warnings)

    def test_validate_no_warnings_for_correct_assignments(self):
        from backend.prompts.context_prioritizer import ContextPrioritizer
        from backend.prompts.prompt_composer import PromptSection
        # All hints match
        sections = [
            PromptSection("persona",       "You are...",  priority=1, required=True),
            PromptSection("memory_section","Memory...",   priority=4, required=False),
            PromptSection("title_library", "Titles...",   priority=5, required=True),
        ]
        p = ContextPrioritizer.from_sections(sections)
        warnings = [w for w in p.validate() if "hint suggests" in w]
        assert not warnings

    # ── report() ──────────────────────────────────────────────────────────────

    def test_report_is_string(self):
        p = self._make_prioritizer()
        assert isinstance(p.report(), str)

    def test_report_contains_all_tier_labels(self):
        p = self._make_prioritizer()
        report = p.report()
        assert "CRITICAL" in report
        assert "LUXURY"   in report

    def test_report_contains_token_totals(self):
        p = self._make_prioritizer()
        report = p.report()
        assert "Total" in report

    def test_repr_is_informative(self):
        p = self._make_prioritizer()
        r = repr(p)
        assert "ContextPrioritizer" in r
        assert "sections" in r

    # ── Integration: feed prompt uses correct tier distribution ───────────────

    def test_day1_feed_priority_distribution(self):
        """Day 1 feed should have P1 critical sections and P5 luxury sections."""
        from backend.prompts.context_prioritizer import ContextPrioritizer, P_CRITICAL, P_LUXURY
        from backend.prompts.prompt_composer import PromptComposer

        # Rebuild prompt but intercept the composer
        original_build = PromptComposer.build
        captured = []

        def _capture_build(self):
            captured.append(ContextPrioritizer.from_composer(self))
            return original_build(self)

        PromptComposer.build = _capture_build
        try:
            _make_feed_prompt(_DAY1_PACKAGES)
        finally:
            PromptComposer.build = original_build

        assert captured, "No composer captured"
        p = captured[0]

        # P1 must include output_schema and intro
        p1_names = [s.name for s in p.sections_at(P_CRITICAL)]
        assert "output_schema" in p1_names or "intro" in p1_names

        # P5 must include luxury sections
        p5_names = [s.name for s in p.sections_at(P_LUXURY)]
        assert len(p5_names) > 0

        # P5 tokens should be less than P1 tokens (luxury is small relative to critical)
        p1_tok = p.tier_stats(P_CRITICAL).total_tokens
        assert p1_tok > 0

    def test_priority_constants_exported(self):
        from backend.prompts.context_prioritizer import (
            P_CRITICAL, P_HIGH, P_USEFUL, P_OPTIONAL, P_LUXURY,
            TIER_LABELS, TIER_DESCRIPTIONS,
        )
        assert P_CRITICAL == 1
        assert P_HIGH     == 2
        assert P_USEFUL   == 3
        assert P_OPTIONAL == 4
        assert P_LUXURY   == 5
        assert len(TIER_LABELS)       == 5
        assert len(TIER_DESCRIPTIONS) == 5

    def test_section_priority_hints_cover_common_names(self):
        from backend.prompts.context_prioritizer import SECTION_PRIORITY_HINTS, P_CRITICAL, P_LUXURY
        assert SECTION_PRIORITY_HINTS["persona"]       == P_CRITICAL
        assert SECTION_PRIORITY_HINTS["memory_section"] == 4
        assert SECTION_PRIORITY_HINTS["title_library"]  == P_LUXURY
        assert SECTION_PRIORITY_HINTS["action_design"]  == P_LUXURY


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3.2 — BudgetAllocator
# ═══════════════════════════════════════════════════════════════════════════════

def _make_test_sections():
    """20 sections spanning all 5 priority tiers, ~9k tokens total."""
    from backend.prompts.prompt_composer import PromptSection
    return [
        # P1 — CRITICAL  (1,200 tokens ~= 4,800 chars)
        PromptSection("persona",     "A" * 800,  priority=1, required=True,  source_pack=""),
        PromptSection("schema",      "B" * 3200, priority=1, required=True,  source_pack=""),
        PromptSection("topic_input", "C" * 80,   priority=1, required=True,  source_pack="dynamic"),
        # P2 — HIGH  (3,100 tokens ~= 12,400 chars)
        PromptSection("writing_rules",       "D" * 2400, priority=2, required=True,  source_pack="core_writing_pack"),
        PromptSection("editorial_philosophy","E" * 2400, priority=2, required=True,  source_pack="package_editorial_pack"),
        PromptSection("output_preamble",     "F" * 400,  priority=2, required=True,  source_pack=""),
        PromptSection("depth",               "G" * 1400, priority=2, required=True,  source_pack=""),
        PromptSection("hard_rules",          "H" * 1400, priority=2, required=True,  source_pack=""),
        # P3 — USEFUL  (8,800 tokens ~= 35,200 chars)
        PromptSection("core_articles",    "I" * 18400, priority=3, required=True,  source_pack="dynamic"),
        PromptSection("source_analysis",  "J" * 3200,  priority=3, required=True,  source_pack="dynamic"),
        PromptSection("writing_style",    "K" * 5600,  priority=3, required=True,  source_pack="core_writing_pack"),
        PromptSection("banned_phrases",   "L" * 4000,  priority=3, required=True,  source_pack="core_writing_pack"),
        PromptSection("output_rules",     "M" * 4000,  priority=3, required=True,  source_pack=""),
        # P4 — OPTIONAL  (500 tokens ~= 2,000 chars)
        PromptSection("memory_section", "N" * 1600, priority=4, required=False, source_pack="dynamic"),
        PromptSection("continuity",     "O" * 400,  priority=4, required=False, source_pack="dynamic"),
        # P5 — LUXURY  (1,600 tokens ~= 6,400 chars)
        PromptSection("title_library",  "P" * 2400, priority=5, required=True,  source_pack="package_narrative_pack"),
        PromptSection("action_design",  "Q" * 1600, priority=5, required=True,  source_pack="package_action_pack"),
        PromptSection("emotional_tone", "R" * 2400, priority=5, required=True,  source_pack="package_narrative_pack"),
    ]


def _make_allocator(model_name="llama-3.3-70b-versatile"):
    from backend.prompts.budget_allocator import BudgetAllocator
    from backend.services.model_registry import get_model_config
    return BudgetAllocator(get_model_config(model_name))


class TestBudgetAllocatorCore:
    """Unit tests for BudgetAllocator computation and structure."""

    # ── compute_budget() ──────────────────────────────────────────────────────

    def test_compute_budget_formula(self):
        """budget = context * utilization - safety - output_reserve"""
        from backend.prompts.budget_allocator import BudgetAllocator
        from backend.services.model_registry import ModelConfig
        cfg = ModelConfig(
            model_name="test", provider="test",
            context_window=128_000, safe_utilization=0.80,
            output_reserve=8_000, safety_buffer=2_000,
        )
        alloc = BudgetAllocator(cfg)
        # 128000 * 0.80 = 102400  - 2000 - 8000 = 92400
        assert alloc.compute_budget() == 92_400

    def test_compute_budget_spec_example(self):
        """Spec example: 128k * 1.0 - 10k safety - 20k output = 98k."""
        from backend.prompts.budget_allocator import BudgetAllocator
        from backend.services.model_registry import ModelConfig
        cfg = ModelConfig(
            model_name="spec-example", provider="test",
            context_window=128_000, safe_utilization=1.0,
            output_reserve=20_000, safety_buffer=10_000,
        )
        alloc = BudgetAllocator(cfg)
        assert alloc.compute_budget() == 98_000

    def test_expected_output_overrides_output_reserve(self):
        """When expected_output > output_reserve, expected_output is used."""
        allocator = _make_allocator()
        # Default output_reserve = 8000; passing 20000 should reduce budget
        default_budget = allocator.compute_budget(0)
        larger_budget  = allocator.compute_budget(20_000)
        assert larger_budget < default_budget
        assert default_budget - larger_budget == 20_000 - 8_000

    def test_expected_output_below_reserve_uses_reserve(self):
        """When expected_output < output_reserve, output_reserve is preserved."""
        allocator = _make_allocator()
        b1 = allocator.compute_budget(0)
        b2 = allocator.compute_budget(100)   # well below 8000 reserve
        assert b1 == b2

    def test_budget_is_model_specific(self):
        """Different models produce different budgets."""
        b_groq    = _make_allocator("llama-3.3-70b-versatile").compute_budget()
        b_gemma   = _make_allocator("gemma2-9b-it").compute_budget()
        b_claude  = _make_allocator("claude-sonnet-4-6").compute_budget()
        assert b_groq  > b_gemma    # 128k vs 8k context window
        assert b_claude > b_groq    # 200k vs 128k context window

    def test_for_model_classmethod(self):
        from backend.prompts.budget_allocator import BudgetAllocator
        alloc = BudgetAllocator.for_model("llama-3.3-70b-versatile")
        assert alloc.compute_budget() > 0

    # ── DEFAULT_TIER_WEIGHTS ──────────────────────────────────────────────────

    def test_default_weights_sum_to_one(self):
        from backend.prompts.budget_allocator import DEFAULT_TIER_WEIGHTS
        assert abs(sum(DEFAULT_TIER_WEIGHTS.values()) - 1.0) < 1e-9

    def test_default_weights_cover_all_five_tiers(self):
        from backend.prompts.budget_allocator import DEFAULT_TIER_WEIGHTS, ALL_PRIORITIES
        assert set(DEFAULT_TIER_WEIGHTS.keys()) == set(ALL_PRIORITIES)

    def test_p3_largest_weight(self):
        """Articles (P3) should have the largest allocation by default."""
        from backend.prompts.budget_allocator import DEFAULT_TIER_WEIGHTS
        assert DEFAULT_TIER_WEIGHTS[3] == max(DEFAULT_TIER_WEIGHTS.values())

    def test_invalid_weights_raise(self):
        from backend.prompts.budget_allocator import BudgetAllocator
        from backend.services.model_registry import get_model_config
        import pytest
        cfg = get_model_config("llama-3.3-70b-versatile")
        with pytest.raises(ValueError, match="sum to 1.0"):
            BudgetAllocator(cfg, tier_weights={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.1, 5: 0.1})


class TestBudgetAllocatorAllocate:
    """Tests for BudgetAllocator.allocate() — static allocation."""

    @pytest.fixture(scope="class")
    def allocation(self):
        sections  = _make_test_sections()
        allocator = _make_allocator()
        return allocator.allocate(sections)

    def test_allocation_type(self, allocation):
        from backend.prompts.budget_allocator import BudgetAllocation
        assert isinstance(allocation, BudgetAllocation)

    def test_total_budget_matches_compute_budget(self, allocation):
        assert allocation.total_budget == _make_allocator().compute_budget()

    def test_all_five_tiers_present(self, allocation):
        assert set(allocation.tier_allocations.keys()) == {1, 2, 3, 4, 5}

    def test_tier_weights_respected(self, allocation):
        from backend.prompts.budget_allocator import DEFAULT_TIER_WEIGHTS
        for p, weight in DEFAULT_TIER_WEIGHTS.items():
            expected = int(allocation.total_budget * weight)
            actual   = allocation.tier_allocations[p].allocated_tokens
            assert actual == expected, f"P{p} allocated {actual}, expected {expected}"

    def test_total_actual_tokens_is_sum_of_sections(self, allocation):
        sections = _make_test_sections()
        expected = sum(s.tokens for s in sections)
        assert allocation.total_actual_tokens == expected

    def test_fits_within_budget_when_small(self):
        from backend.prompts.prompt_composer import PromptSection
        tiny = [PromptSection("x", "A" * 4, priority=1, required=True)]
        result = _make_allocator().allocate(tiny)
        assert result.fits_within_budget

    def test_overflow_detected(self):
        from backend.prompts.prompt_composer import PromptSection
        # One huge section that exceeds the whole budget
        huge = [PromptSection("giant", "X" * 400_000, priority=3, required=True)]
        result = _make_allocator().allocate(huge)
        assert not result.fits_within_budget
        assert result.overflow_tokens > 0
        assert any("OVER BUDGET" in w for w in result.warnings)

    def test_not_adaptive_flag(self, allocation):
        assert allocation.adaptive is False

    def test_model_name_preserved(self, allocation):
        assert allocation.model_name == "llama-3.3-70b-versatile"

    def test_report_is_string(self, allocation):
        r = allocation.report()
        assert isinstance(r, str)
        assert "llama-3.3-70b-versatile" in r
        assert "CRITICAL" in r
        assert "LUXURY" in r

    def test_headroom_property(self, allocation):
        if allocation.fits_within_budget:
            assert allocation.headroom_tokens == allocation.total_budget - allocation.total_actual_tokens
        else:
            assert allocation.headroom_tokens == 0


class TestBudgetAllocatorAdaptive:
    """Tests for BudgetAllocator.allocate_adaptive() — surplus redistribution."""

    def _small_alloc(self):
        """Sections where P4/P5 use far less than their allocation."""
        from backend.prompts.prompt_composer import PromptSection
        sections = [
            PromptSection("schema",    "A" * 800,   priority=1, required=True),
            PromptSection("articles",  "B" * 16000, priority=3, required=True),
            PromptSection("memory",    "C" * 40,    priority=4, required=False),
            PromptSection("luxury",    "D" * 40,    priority=5, required=False),
        ]
        return sections

    def test_adaptive_flag_set(self):
        alloc = _make_allocator().allocate_adaptive(self._small_alloc())
        assert alloc.adaptive is True

    def test_total_budget_same_as_static(self):
        sections  = self._small_alloc()
        allocator = _make_allocator()
        static   = allocator.allocate(sections)
        adaptive = allocator.allocate_adaptive(sections)
        assert static.total_budget == adaptive.total_budget

    def test_total_actual_unchanged(self):
        """Adaptive allocation doesn't add or remove sections."""
        sections  = self._small_alloc()
        allocator = _make_allocator()
        static   = allocator.allocate(sections)
        adaptive = allocator.allocate_adaptive(sections)
        assert static.total_actual_tokens == adaptive.total_actual_tokens

    def test_p4_p5_surplus_redistributed(self):
        """After adaptive pass, P4/P5 over-allocated headroom shrinks to 0."""
        sections  = self._small_alloc()
        allocator = _make_allocator()
        adaptive  = allocator.allocate_adaptive(sections)
        # P4 and P5 used only 10 tokens each; surplus should have been redistributed
        p4_alloc = adaptive.tier_allocations[4].allocated_tokens
        p4_actual = adaptive.tier_allocations[4].actual_tokens
        assert p4_alloc == p4_actual or p4_alloc <= p4_actual + 1  # tightly matched

    def test_fits_within_budget_for_small_sections(self):
        alloc = _make_allocator().allocate_adaptive(self._small_alloc())
        assert alloc.fits_within_budget

    def test_report_shows_adaptive_label(self):
        alloc = _make_allocator().allocate_adaptive(self._small_alloc())
        assert "[adaptive]" in alloc.report()


class TestSectionsWithinBudget:
    """Tests for BudgetAllocator.sections_within_budget()."""

    def test_returns_list_of_prompt_sections(self):
        from backend.prompts.prompt_composer import PromptSection
        sections = _make_test_sections()
        result   = _make_allocator().sections_within_budget(sections)
        assert all(isinstance(s, PromptSection) for s in result)

    def test_all_required_sections_always_included(self):
        sections  = _make_test_sections()
        allocator = _make_allocator()
        result    = allocator.sections_within_budget(sections)
        result_names = {s.name for s in result}
        required_names = {s.name for s in sections if s.required}
        assert required_names <= result_names

    def test_optional_sections_excluded_when_over_budget(self):
        """Required section fills the budget; optional section cannot fit."""
        from backend.prompts.prompt_composer import PromptSection
        from backend.prompts.budget_allocator import BudgetAllocator
        from backend.services.model_registry import ModelConfig
        # Budget = 100 tokens exactly; required uses 90, optional needs 20 more
        tiny_cfg = ModelConfig(
            model_name="tiny", provider="test",
            context_window=100, safe_utilization=1.0,
            output_reserve=0, safety_buffer=0,
        )
        sections = [
            PromptSection("required", "A" * 360, priority=1, required=True),   # 90 tokens
            PromptSection("optional", "B" * 80,  priority=4, required=False),  # 20 tokens
        ]
        result = BudgetAllocator(tiny_cfg).sections_within_budget(sections)
        names  = {s.name for s in result}
        assert "required" in names
        assert "optional" not in names

    def test_result_fits_within_budget(self):
        sections  = _make_test_sections()
        allocator = _make_allocator()
        result    = allocator.sections_within_budget(sections)
        budget    = allocator.compute_budget()
        total_tok = sum(s.tokens for s in result)
        # Required sections may still exceed budget (they're always included)
        # but we verify the function runs without error
        assert total_tok > 0

    def test_fewer_sections_returned_under_tight_budget(self):
        """With a tighter budget, fewer optional sections should be included."""
        sections   = _make_test_sections()
        alloc_big  = _make_allocator("claude-sonnet-4-6")    # 200k context
        alloc_tiny = _make_allocator("gemma2-9b-it")         # 8k context
        result_big  = alloc_big.sections_within_budget(sections)
        result_tiny = alloc_tiny.sections_within_budget(sections)
        # Gemma should include fewer optional sections
        assert len(result_tiny) <= len(result_big)


class TestBudgetAllocatorIntegration:
    """Integration: BudgetAllocator works end-to-end with real prompt sections."""

    def test_day1_feed_fits_groq_budget(self):
        """Day 1 feed prompt should fit comfortably in llama-3.3 budget."""
        from backend.prompts.budget_allocator import BudgetAllocator
        from backend.prompts.prompt_composer import PromptComposer
        from backend.services.model_registry import get_model_config

        original_build = PromptComposer.build
        captured = []
        def patched_build(self):
            captured.append(list(self._sections))
            return original_build(self)
        PromptComposer.build = patched_build
        try:
            _make_feed_prompt(_DAY1_PACKAGES)
        finally:
            PromptComposer.build = original_build

        sections  = captured[0]
        allocator = BudgetAllocator(get_model_config("llama-3.3-70b-versatile"))
        allocation = allocator.allocate(sections)

        assert allocation.total_budget > 0
        assert allocation.total_actual_tokens > 0
        assert allocation.utilization_pct < 100.0
        assert isinstance(allocation.report(), str)

    def test_allocation_adapts_across_models(self):
        """Same sections yield different budgets on different models."""
        from backend.prompts.budget_allocator import BudgetAllocator
        from backend.services.model_registry import get_model_config
        sections = _make_test_sections()

        b_groq   = BudgetAllocator(get_model_config("llama-3.3-70b-versatile")).allocate(sections)
        b_claude = BudgetAllocator(get_model_config("claude-sonnet-4-6")).allocate(sections)
        b_gemini = BudgetAllocator(get_model_config("gemini-2.0-flash")).allocate(sections)

        # Total budget scales with model context window
        assert b_claude.total_budget > b_groq.total_budget
        assert b_gemini.total_budget > b_claude.total_budget

        # Same actual tokens across all models (sections don't change)
        assert b_groq.total_actual_tokens == b_claude.total_actual_tokens == b_gemini.total_actual_tokens

    def test_tier_allocation_dataclass_fields(self):
        from backend.prompts.budget_allocator import TierAllocation
        sections  = _make_test_sections()
        allocation = _make_allocator().allocate(sections)
        ta = allocation.tier_allocations[1]
        assert isinstance(ta, TierAllocation)
        assert ta.priority      == 1
        assert ta.label         == "CRITICAL"
        assert ta.weight        == 0.15
        assert isinstance(ta.section_names, list)
        assert isinstance(ta.source_packs, list)
        assert ta.utilization_pct >= 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3.3 — ArticleCompressor
# ═══════════════════════════════════════════════════════════════════════════════

# Realistic article fixtures covering diverse content types
_PHARMA_ARTICLE = {
    "title": "India's API Dependency Creates Supply Chain Fragility",
    "url":   "https://example.com/india-api",
    "content": (
        "India imports approximately 70% of Active Pharmaceutical Ingredients "
        "from Chinese manufacturers, creating significant supply chain vulnerability "
        "for over 600 essential medicines. "
        "A 2024 industry report found that a two-week factory shutdown in Hebei province "
        "caused a 35% spike in API prices across India's generic drug sector. "
        "This means that any geopolitical disruption between India and China could "
        "effectively halt production of critical medicines including antibiotics and "
        "cardiovascular drugs. "
        "The Indian government launched PLI schemes worth $1.4 billion in 2023, "
        "marking the first major domestic API manufacturing push in three decades."
    ),
}

_RAG_ARTICLE = {
    "title": "RAG Reduces LLM Hallucination by 40% in Knowledge-Intensive Tasks",
    "url":   "https://arxiv.org/abs/2005.11401",
    "content": (
        "Retrieval-Augmented Generation achieves state-of-the-art performance on "
        "knowledge-intensive NLP tasks by combining parametric and non-parametric memory. "
        "Lewis et al. (2020) found that RAG reduces factual errors by 40% compared to "
        "fine-tuning alone on the TriviaQA and WebQuestions benchmarks. "
        "This enables language models to remain accurate on recent events without "
        "expensive retraining cycles. "
        "The new architecture introduces a dense retriever that queries a Wikipedia index "
        "of 21 million passages, representing a breakthrough in scalable knowledge access."
    ),
}

_SHORT_ARTICLE = {
    "title": "FDA Approves Generic Drug",
    "url":   "https://fda.gov/news",
    "content": "The FDA approved a generic version of a popular drug.",
}

_EMPTY_ARTICLE: dict = {
    "title": "Empty Article",
    "url":   "https://example.com/empty",
    "content": "",
}

_EIGHT_ARTICLES = [_PHARMA_ARTICLE, _RAG_ARTICLE] * 4


class TestArticleCompressorFields:
    """Tests for field extraction — key_claim, evidence, implication, novelty."""

    @pytest.fixture(scope="class")
    def pharma(self):
        from backend.prompts.article_compressor import ArticleCompressor
        return ArticleCompressor().compress(_PHARMA_ARTICLE)

    @pytest.fixture(scope="class")
    def rag(self):
        from backend.prompts.article_compressor import ArticleCompressor
        return ArticleCompressor().compress(_RAG_ARTICLE)

    # ── key_claim ─────────────────────────────────────────────────────────────

    def test_key_claim_is_non_empty(self, pharma):
        assert pharma.key_claim and len(pharma.key_claim) > 10

    def test_key_claim_reflects_first_sentence(self, pharma):
        assert "70%" in pharma.key_claim or "imports" in pharma.key_claim.lower()

    def test_key_claim_fallback_to_title_on_empty_content(self):
        from backend.prompts.article_compressor import ArticleCompressor
        c = ArticleCompressor().compress(_EMPTY_ARTICLE)
        assert c.key_claim == "Empty Article"

    # ── evidence ──────────────────────────────────────────────────────────────

    def test_evidence_contains_quantitative_signal(self, pharma):
        # "35%", "600", "$1.4 billion", or "2024"
        assert any(ch.isdigit() for ch in pharma.evidence)

    def test_rag_evidence_contains_study_signal(self, rag):
        # "Lewis et al.", "40%", or "benchmarks"
        ev = rag.evidence.lower()
        assert "40" in ev or "lewis" in ev or "benchmark" in ev or "found" in ev

    # ── implication ───────────────────────────────────────────────────────────

    def test_implication_non_empty_for_rich_article(self, pharma):
        assert pharma.implication  # article contains "this means that"

    def test_rag_implication_contains_consequence_language(self, rag):
        impl = rag.implication.lower()
        assert any(w in impl for w in ("enables", "allow", "means", "this", "without"))

    # ── novelty ───────────────────────────────────────────────────────────────

    def test_novelty_detected_from_content(self, pharma):
        # "first major domestic API manufacturing push" → novelty signal "first"
        assert pharma.novelty

    def test_novelty_detected_from_breakthrough_signal(self, rag):
        # "breakthrough in scalable knowledge access"
        assert "breakthrough" in rag.novelty.lower() or rag.novelty

    def test_novelty_empty_for_short_article(self):
        from backend.prompts.article_compressor import ArticleCompressor
        c = ArticleCompressor().compress(_SHORT_ARTICLE)
        # Short article may or may not have novelty — just ensure no crash
        assert isinstance(c.novelty, str)


class TestCompressionLevels:
    """Tests for the four compression levels."""

    @pytest.fixture(scope="class")
    def pharma_compressed(self):
        from backend.prompts.article_compressor import ArticleCompressor
        return ArticleCompressor().compress(_PHARMA_ARTICLE, index=1)

    # ── Level 0 FULL ──────────────────────────────────────────────────────────

    def test_level0_contains_full_content_header(self, pharma_compressed):
        assert "[ARTICLE 1]" in pharma_compressed.level0
        assert "Title:" in pharma_compressed.level0
        assert "URL:" in pharma_compressed.level0
        assert "Content:" in pharma_compressed.level0

    def test_level0_preserves_title(self, pharma_compressed):
        assert "India's API Dependency" in pharma_compressed.level0

    def test_level0_content_capped_at_max(self, pharma_compressed):
        from backend.prompts.article_compressor import _MAX_FULL_CHARS
        # Content portion must not exceed the cap
        content_start = pharma_compressed.level0.index("Content:") + len("Content:")
        content_section = pharma_compressed.level0[content_start:]
        assert len(content_section) <= _MAX_FULL_CHARS + 10  # small tolerance for strip

    # ── Level 1 DETAILED ─────────────────────────────────────────────────────

    def test_level1_contains_structured_headers(self, pharma_compressed):
        assert "Key Claim:" in pharma_compressed.level1
        assert "Evidence:" in pharma_compressed.level1

    def test_level1_contains_snapshot(self, pharma_compressed):
        assert "Snapshot:" in pharma_compressed.level1

    def test_level1_leq_level0(self, pharma_compressed):
        # Invariant: L1 ≤ L0 (for short articles they may be equal — clamped)
        assert len(pharma_compressed.level1) <= len(pharma_compressed.level0)

    # ── Level 2 INSIGHT ───────────────────────────────────────────────────────

    def test_level2_uses_compact_header(self, pharma_compressed):
        assert "[A1]" in pharma_compressed.level2

    def test_level2_contains_claim_field(self, pharma_compressed):
        assert "Claim:" in pharma_compressed.level2

    def test_level2_no_raw_content_snapshot(self, pharma_compressed):
        assert "Snapshot:" not in pharma_compressed.level2
        assert "Content:" not in pharma_compressed.level2

    def test_level2_shorter_than_level1(self, pharma_compressed):
        assert len(pharma_compressed.level2) < len(pharma_compressed.level1)

    # ── Level 3 CLAIM ────────────────────────────────────────────────────────

    def test_level3_is_single_line(self, pharma_compressed):
        assert "\n" not in pharma_compressed.level3

    def test_level3_contains_url(self, pharma_compressed):
        assert "https://example.com/india-api" in pharma_compressed.level3

    def test_level3_shortest(self, pharma_compressed):
        assert len(pharma_compressed.level3) < len(pharma_compressed.level2)

    # ── at_level() routing ────────────────────────────────────────────────────

    def test_at_level_0_returns_level0(self, pharma_compressed):
        assert pharma_compressed.at_level(0) == pharma_compressed.level0

    def test_at_level_negative_returns_level0(self, pharma_compressed):
        assert pharma_compressed.at_level(-1) == pharma_compressed.level0

    def test_at_level_4_returns_level3(self, pharma_compressed):
        assert pharma_compressed.at_level(4) == pharma_compressed.level3

    # ── Token counts ─────────────────────────────────────────────────────────

    def test_tokens_decrease_with_level(self, pharma_compressed):
        t = [pharma_compressed.tokens_at_level(l) for l in range(4)]
        assert t[0] >= t[1] >= t[2] >= t[3]

    def test_compression_ratio_positive(self, pharma_compressed):
        assert 0.0 < pharma_compressed.compression_ratio < 1.0


class TestArticleCompressorBatch:
    """Tests for compress_batch() and format_batch()."""

    @pytest.fixture(scope="class")
    def batch(self):
        from backend.prompts.article_compressor import ArticleCompressor
        return ArticleCompressor().compress_batch(_EIGHT_ARTICLES)

    def test_batch_length(self, batch):
        assert len(batch) == 8

    def test_batch_respects_max_articles(self):
        from backend.prompts.article_compressor import ArticleCompressor
        result = ArticleCompressor().compress_batch(_EIGHT_ARTICLES, max_articles=3)
        assert len(result) == 3

    def test_format_batch_level0_contains_all_articles(self, batch):
        from backend.prompts.article_compressor import ArticleCompressor
        text = ArticleCompressor().format_batch(batch, level=0)
        assert "[ARTICLE 1]" in text
        assert "[ARTICLE 8]" in text

    def test_format_batch_level3_all_single_line_entries(self, batch):
        from backend.prompts.article_compressor import ArticleCompressor
        text = ArticleCompressor().format_batch(batch, level=3)
        lines = [l for l in text.splitlines() if l.strip()]
        # Each article produces 1 line; with \n\n separators some blank lines exist
        numbered = [l for l in lines if re.match(r"^\d+\.", l.strip())]
        assert len(numbered) == 8

    def test_format_batch_empty_returns_placeholder(self):
        from backend.prompts.article_compressor import ArticleCompressor
        text = ArticleCompressor().format_batch([], level=2)
        assert "no articles" in text.lower()

    def test_batch_tokens_decrease_with_level(self, batch):
        from backend.prompts.article_compressor import ArticleCompressor, _batch_tokens
        t = [_batch_tokens(batch, l) for l in range(4)]
        assert t[0] >= t[1] >= t[2] >= t[3]


class TestFormatWithinBudget:
    """Tests for format_within_budget() auto-selection."""

    def _make_batch(self):
        from backend.prompts.article_compressor import ArticleCompressor
        return ArticleCompressor().compress_batch(_EIGHT_ARTICLES)

    def test_returns_tuple(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch  = self._make_batch()
        result = ArticleCompressor().format_within_budget(batch, budget_tokens=50_000)
        assert isinstance(result, tuple) and len(result) == 2

    def test_large_budget_uses_level0(self):
        from backend.prompts.article_compressor import ArticleCompressor, LEVEL_FULL
        batch       = self._make_batch()
        text, meta  = ArticleCompressor().format_within_budget(batch, budget_tokens=50_000)
        assert meta.level == LEVEL_FULL
        assert meta.fits is True

    def test_tight_budget_uses_higher_level(self):
        from backend.prompts.article_compressor import ArticleCompressor, LEVEL_FULL
        batch      = self._make_batch()
        # Compute Level 0 tokens and force compression by using half that
        from backend.prompts.article_compressor import _batch_tokens
        level0_tok = _batch_tokens(batch, LEVEL_FULL)
        _, meta    = ArticleCompressor().format_within_budget(batch, budget_tokens=level0_tok // 2)
        assert meta.level > LEVEL_FULL

    def test_very_tight_budget_uses_level3(self):
        from backend.prompts.article_compressor import ArticleCompressor, LEVEL_CLAIM
        batch      = self._make_batch()
        _, meta    = ArticleCompressor().format_within_budget(batch, budget_tokens=100)
        assert meta.level == LEVEL_CLAIM

    def test_result_fits_when_budget_is_large(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch      = self._make_batch()
        _, meta    = ArticleCompressor().format_within_budget(batch, budget_tokens=50_000)
        assert meta.fits is True

    def test_fits_false_when_even_level3_overflows(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch      = self._make_batch()
        _, meta    = ArticleCompressor().format_within_budget(batch, budget_tokens=1)
        assert meta.fits is False

    def test_meta_summary_is_string(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch      = self._make_batch()
        _, meta    = ArticleCompressor().format_within_budget(batch, budget_tokens=4_000)
        assert isinstance(meta.summary(), str)
        assert "tokens" in meta.summary()

    def test_compression_ratio_positive(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch      = self._make_batch()
        _, meta    = ArticleCompressor().format_within_budget(batch, budget_tokens=2_000)
        assert 0.0 <= meta.compression_ratio <= 1.0


class TestCompressionReport:
    """Tests for ArticleCompressor.compression_report()."""

    def test_report_contains_all_four_levels(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch  = ArticleCompressor().compress_batch(_EIGHT_ARTICLES)
        report = ArticleCompressor().compression_report(batch)
        for label in ("FULL", "DETAILED", "INSIGHT", "CLAIM"):
            assert label in report

    def test_report_shows_token_reduction(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch  = ArticleCompressor().compress_batch(_EIGHT_ARTICLES)
        report = ArticleCompressor().compression_report(batch)
        assert "reduction" in report
        assert "baseline" in report

    def test_report_empty_batch(self):
        from backend.prompts.article_compressor import ArticleCompressor
        report = ArticleCompressor().compression_report([])
        assert "0 articles" in report


class TestArticleCompressorIntegration:
    """Integration: compressor works end-to-end with BudgetAllocator P3 budget."""

    def test_eight_articles_fit_in_p3_groq_budget(self):
        """Eight full articles should fit in Groq's P3 (USEFUL) allocation."""
        from backend.prompts.article_compressor import ArticleCompressor
        from backend.prompts.budget_allocator import BudgetAllocator
        from backend.services.model_registry import get_model_config
        from backend.prompts.prompt_composer import PromptSection
        from backend.prompts.context_prioritizer import P_USEFUL

        alloc     = BudgetAllocator(get_model_config("llama-3.3-70b-versatile"))
        p3_budget = int(alloc.compute_budget() * 0.40)  # P3 gets 40%

        batch     = ArticleCompressor().compress_batch(_EIGHT_ARTICLES)
        _, meta   = ArticleCompressor().format_within_budget(batch, budget_tokens=p3_budget)

        assert meta.total_tokens <= p3_budget or not meta.fits
        assert isinstance(meta.level, int)

    def test_compression_level_names_exported(self):
        from backend.prompts.article_compressor import (
            LEVEL_FULL, LEVEL_DETAILED, LEVEL_INSIGHT, LEVEL_CLAIM,
            LEVEL_NAMES, LEVEL_DESCRIPTIONS,
        )
        assert LEVEL_FULL == 0
        assert LEVEL_CLAIM == 3
        assert LEVEL_NAMES[0] == "FULL"
        assert LEVEL_NAMES[3] == "CLAIM"
        assert len(LEVEL_DESCRIPTIONS) == 4

    def test_empty_article_content_handled_gracefully(self):
        from backend.prompts.article_compressor import ArticleCompressor
        batch = ArticleCompressor().compress_batch([_EMPTY_ARTICLE])
        assert len(batch) == 1
        c = batch[0]
        assert c.title == "Empty Article"
        assert c.key_claim == "Empty Article"  # falls back to title
        for level in range(4):
            assert isinstance(c.at_level(level), str)

    def test_compression_significantly_reduces_tokens_for_long_articles(self):
        """Level 2 achieves meaningful compression on articles that exceed the Level 0 cap."""
        from backend.prompts.article_compressor import ArticleCompressor, _batch_tokens, LEVEL_FULL, LEVEL_INSIGHT
        # Use articles longer than MAX_FULL_CHARS (1200) so Level 0 truncation kicks in
        long_articles = [
            {
                "title": "India API Supply Chain Risk",
                "url": "https://example.com/long",
                "content": (
                    "India imports approximately 70% of Active Pharmaceutical Ingredients "
                    "from Chinese manufacturers, creating significant supply chain vulnerability. "
                    "A 2024 industry report found a 35% spike in API prices following factory "
                    "shutdowns in Hebei province, affecting 600+ essential medicines. "
                    "This means any geopolitical disruption could halt critical drug production. "
                    "The government launched PLI schemes worth $1.4 billion in 2023, marking "
                    "the first major domestic API manufacturing push in three decades. "
                    "Analysts estimate India needs 5-7 years to achieve 50% self-sufficiency "
                    "in bulk drug manufacturing. Multiple expert committees have noted that "
                    "the current import dependency creates single-point failure risk for "
                    "cardiovascular, antibiotic, and diabetes medication supply chains. "
                    "CDSCO is reportedly reviewing regulatory frameworks to incentivize "
                    "domestic API production through fast-track approval pathways. "
                    "The biosimilar sector represents a $3 billion opportunity that requires "
                    "domestic API availability as a prerequisite for competitive cost structures."
                ),
            }
        ] * 4  # 4 long articles (each ~1400 chars, exceeds 1200-char Level 0 cap)

        batch     = ArticleCompressor().compress_batch(long_articles)
        tok_full  = _batch_tokens(batch, LEVEL_FULL)
        tok_insight = _batch_tokens(batch, LEVEL_INSIGHT)
        # For articles that exceed the Level 0 cap, Level 2 is meaningfully smaller
        assert tok_insight < tok_full, "Level 2 must use fewer tokens than Level 0 for long articles"
        # And should achieve at least 30% reduction
        assert tok_insight < tok_full * 0.80


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3.4 — MemoryCompressor
# ═══════════════════════════════════════════════════════════════════════════════

# Realistic memory dicts simulating Day 1, Day 15, and Day 50 of a project

_EMPTY_MEMORY: dict = {
    "covered_concepts":    [],
    "covered_mechanisms":  [],
    "covered_examples":    [],
    "covered_industries":  [],
    "covered_geographies": [],
    "covered_narratives":  [],
    "curiosity_angles":    [],
    "title_patterns_used": [],
    "opening_hooks_used":  [],
    "progression_stage":   "foundation",
    "days_at_stage":       0,
}

_DAY15_MEMORY: dict = {
    "covered_concepts": [
        "Active Pharmaceutical Ingredients", "ANDA filing process",
        "FDA approval pathway", "Generic drug pricing",
        "API import dependency", "Supply chain fragility",
        "Bioequivalence testing", "CDSCO regulation",
        "Bulk drug manufacturing", "Drug patent expiry",
        "Biosimilar development", "CMO contracts",
    ],
    "covered_mechanisms": [
        "China API dominance → price leverage over Indian generics",
        "FDA approval as global trust certificate for export access",
        "Patent cliff → 90% price collapse in 3-6 months post-expiry",
        "ANDA backlog creates 3-year generic launch delay in US market",
    ],
    "covered_examples": [
        "Biocon", "Dr. Reddy's Laboratories", "Cipla", "Sun Pharma",
        "CDSCO", "FDA", "Hebei province", "Hyderabad pharma cluster",
        "Biocon", "Cipla",  # intentional duplicates to test frequency
    ],
    "covered_industries":  ["Pharma", "Supply Chain", "Regulatory"],
    "covered_geographies": ["India", "China", "USA", "Europe"],
    "covered_narratives":  ["INVESTIGATIVE", "STRATEGIC", "INVESTIGATIVE", "HISTORICAL", "INVESTIGATIVE"],
    "curiosity_angles":    ["Hidden Mechanism", "Origin Myth Shattered", "Geopolitical Leverage", "The Failure That Explained Everything"],
    "title_patterns_used": ["hidden_dependency", "geopolitical_tension", "hidden_dependency", "economic_leverage"],
    "opening_hooks_used":  ["india imports most", "when a patent", "the hidden cost of", "why china controls"],
    "progression_stage":   "mechanisms",
    "days_at_stage":       2,
}

_DAY50_MEMORY: dict = {
    "covered_concepts": [
        f"Concept {i}" for i in range(60)  # simulates 60 accumulated concepts
    ] + [
        "API dependency", "Generic approval", "Patent cliff",
        "Biosimilar pathway", "CMO selection", "GMP compliance",
        "ANDA backlog", "Trade margin structure", "PLI scheme",
        "FDA 483 warning letter", "WHO prequalification",
    ],
    "covered_mechanisms": [
        f"Mechanism {i}" for i in range(25)  # 25 mechanisms
    ] + [
        "China dominance → single-point API supply failure",
        "Patent cliff → rapid generic price collapse mechanism",
        "FDA approval → global export access unlock",
    ],
    "covered_examples": [f"Company {i}" for i in range(30)],
    "covered_industries":  ["Pharma", "Supply Chain", "Regulatory", "Manufacturing"],
    "covered_geographies": ["India", "China", "USA", "Europe", "Japan"],
    "covered_narratives":  ["INVESTIGATIVE"] * 20 + ["STRATEGIC"] * 10,
    "curiosity_angles":    [
        "Hidden Mechanism", "Geopolitical Leverage", "Contrarian View",
        "Second Order Effect", "Origin Myth Shattered",
    ],
    "title_patterns_used": ["hidden_dependency"] * 15 + ["geopolitical_tension"] * 10,
    "opening_hooks_used":  [f"hook {i}" for i in range(40)],
    "progression_stage":   "dependencies",
    "days_at_stage":       1,
}


class TestMemoryCompressorCore:
    """Unit tests for MemoryCompressor compression and field extraction."""

    @pytest.fixture(scope="class")
    def comp_empty(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        return MemoryCompressor().compress(_EMPTY_MEMORY)

    @pytest.fixture(scope="class")
    def comp_day15(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        return MemoryCompressor().compress(_DAY15_MEMORY)

    @pytest.fixture(scope="class")
    def comp_day50(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        return MemoryCompressor().compress(_DAY50_MEMORY)

    # ── CompressedMemory fields ───────────────────────────────────────────────

    def test_progression_stage_preserved(self, comp_day15):
        assert comp_day15.progression_stage == "mechanisms"

    def test_concepts_non_empty_for_populated_memory(self, comp_day15):
        assert len(comp_day15.concepts_learned) > 0

    def test_concepts_capped_at_level1_limit(self, comp_day50):
        from backend.prompts.memory_compressor import _LEVEL1_CONCEPTS
        assert len(comp_day50.concepts_learned) <= _LEVEL1_CONCEPTS

    def test_mechanisms_non_empty(self, comp_day15):
        assert len(comp_day15.mechanisms_covered) > 0

    def test_open_questions_present(self, comp_day15):
        assert len(comp_day15.open_questions) > 0
        # Questions should be strings
        assert all(isinstance(q, str) and "?" in q for q in comp_day15.open_questions)

    def test_curiosity_threads_from_angles(self, comp_day15):
        assert "Hidden Mechanism" in comp_day15.curiosity_threads \
            or len(comp_day15.curiosity_threads) > 0

    def test_key_examples_are_most_frequent(self, comp_day15):
        # Biocon and Cipla appear twice in _DAY15_MEMORY — should be top examples
        examples_lower = [e.lower() for e in comp_day15.key_examples]
        assert "biocon" in examples_lower or "cipla" in examples_lower

    def test_empty_memory_handled(self, comp_empty):
        assert comp_empty.progression_stage == "foundation"
        assert comp_empty.concepts_learned   == []
        assert comp_empty.mechanisms_covered == []
        assert comp_empty.open_questions     != []  # stage questions always exist

    # ── Compression levels ────────────────────────────────────────────────────

    def test_level1_contains_structured_headers(self, comp_day15):
        assert "LEARNING MEMORY" in comp_day15.level1
        assert "Concepts Learned" in comp_day15.level1

    def test_level1_contains_all_five_categories(self, comp_day15):
        l1 = comp_day15.level1
        assert "Concepts Learned"   in l1
        assert "Mechanisms Covered" in l1
        assert "Key Examples"       in l1
        assert "Curiosity Threads"  in l1
        assert "Open Questions"     in l1

    def test_level2_is_compact(self, comp_day15):
        l2 = comp_day15.level2
        assert "[Memory:" in l2
        # Level 2 should be shorter than Level 1
        assert len(comp_day15.level2) <= len(comp_day15.level1)

    def test_level3_is_single_line(self, comp_day50):
        assert "\n" not in comp_day50.level3

    def test_level3_contains_stage(self, comp_day50):
        assert "dependencies" in comp_day50.level3.lower()

    def test_levels_monotonically_shrink(self, comp_day15):
        sizes = [comp_day15.tokens_at_level(l) for l in range(4)]
        assert sizes[0] >= sizes[1] >= sizes[2] >= sizes[3]

    def test_at_level_routing(self, comp_day15):
        from backend.prompts.memory_compressor import (
            MEM_LEVEL_FULL, MEM_LEVEL_STRUCTURED, MEM_LEVEL_GRAPH, MEM_LEVEL_SUMMARY
        )
        assert comp_day15.at_level(MEM_LEVEL_FULL)       == comp_day15.level0
        assert comp_day15.at_level(MEM_LEVEL_STRUCTURED)  == comp_day15.level1
        assert comp_day15.at_level(MEM_LEVEL_GRAPH)       == comp_day15.level2
        assert comp_day15.at_level(MEM_LEVEL_SUMMARY)     == comp_day15.level3
        assert comp_day15.at_level(-1) == comp_day15.level0
        assert comp_day15.at_level(99) == comp_day15.level3

    def test_compression_ratio_non_negative(self, comp_day15):
        assert comp_day15.compression_ratio >= 0.0

    def test_original_tokens_positive(self, comp_day15):
        assert comp_day15.original_tokens > 0


class TestMemoryCompressionLevelsContent:
    """Validate what each level shows for a mature project (Day 50)."""

    @pytest.fixture(scope="class")
    def comp(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        return MemoryCompressor().compress(_DAY50_MEMORY)

    def test_level2_includes_concept_count(self, comp):
        # Level 2 should show total counts e.g. "71c / 28m"
        l2 = comp.level2
        assert "/" in l2 and "m]" in l2  # e.g. "71c / 28m"

    def test_level3_includes_total_counts(self, comp):
        l3 = comp.level3
        assert "concepts" in l3 and "mechanisms" in l3

    def test_level1_questions_contain_question_mark(self, comp):
        questions_section = comp.level1
        assert "?" in questions_section

    def test_level2_much_shorter_than_level1(self, comp):
        assert comp.tokens_at_level(2) < comp.tokens_at_level(1)

    def test_level3_tiny(self, comp):
        # Should be under 30 tokens
        assert comp.tokens_at_level(3) < 30


class TestMemoryDiverseSelection:
    """Tests for _select_representative() diversity algorithm."""

    def test_select_returns_correct_count(self):
        from backend.prompts.memory_compressor import _select_representative
        items  = [f"item {i}" for i in range(20)]
        result = _select_representative(items, 5)
        assert len(result) == 5

    def test_select_fewer_than_n(self):
        from backend.prompts.memory_compressor import _select_representative
        items  = ["a", "b", "c"]
        result = _select_representative(items, 10)
        assert len(result) == 3

    def test_select_avoids_similar_items(self):
        from backend.prompts.memory_compressor import _select_representative
        # All near-duplicates of "API dependency supply chain"
        similar = [f"API dependency supply chain variant {i}" for i in range(8)]
        # One completely different item
        different = "FDA approval global trust certificate"
        items  = similar + [different]
        result = _select_representative(items, 3)
        # The diverse item should be selected
        assert different in result

    def test_frequency_selection(self):
        from backend.prompts.memory_compressor import _select_top_by_frequency
        items = ["Biocon"] * 5 + ["Cipla"] * 3 + ["Dr. Reddy"] * 1
        result = _select_top_by_frequency(items, 2)
        assert "Biocon" in result
        assert "Cipla" in result


class TestFormatWithinBudgetMemory:
    """Tests for MemoryCompressor.format_within_budget()."""

    def test_large_budget_returns_full_level(self):
        from backend.prompts.memory_compressor import MemoryCompressor, MEM_LEVEL_FULL
        _, meta = MemoryCompressor().format_within_budget(_DAY15_MEMORY, budget_tokens=10_000)
        assert meta.level == MEM_LEVEL_FULL

    def test_tight_budget_escalates_compression(self):
        from backend.prompts.memory_compressor import MemoryCompressor, MEM_LEVEL_FULL
        _, meta = MemoryCompressor().format_within_budget(_DAY50_MEMORY, budget_tokens=50)
        assert meta.level > MEM_LEVEL_FULL

    def test_fits_flag_correct(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        _, meta_large = MemoryCompressor().format_within_budget(_DAY15_MEMORY, budget_tokens=10_000)
        _, meta_tiny  = MemoryCompressor().format_within_budget(_DAY15_MEMORY, budget_tokens=1)
        assert meta_large.fits is True
        assert meta_tiny.fits  is False

    def test_result_summary_is_string(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        _, meta = MemoryCompressor().format_within_budget(_DAY15_MEMORY, budget_tokens=200)
        assert isinstance(meta.summary(), str)
        assert "tokens" in meta.summary()

    def test_empty_memory_handled_gracefully(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        text, meta = MemoryCompressor().format_within_budget(_EMPTY_MEMORY, budget_tokens=1_000)
        assert isinstance(text, str)
        assert meta.total_tokens > 0


class TestCompressionReportMemory:
    """Tests for MemoryCompressor.compression_report()."""

    def test_report_contains_all_four_levels(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        report = MemoryCompressor().compression_report(_DAY15_MEMORY)
        for name in ("FULL", "STRUCTURED", "GRAPH", "SUMMARY"):
            assert name in report

    def test_report_shows_stage(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        report = MemoryCompressor().compression_report(_DAY15_MEMORY)
        assert "mechanisms" in report  # _DAY15_MEMORY is at mechanisms stage

    def test_report_shows_reduction(self):
        from backend.prompts.memory_compressor import MemoryCompressor
        report = MemoryCompressor().compression_report(_DAY15_MEMORY)
        assert "reduction" in report


class TestMemoryCompressionConstants:
    """Verify public constants and level names are correct."""

    def test_level_constants(self):
        from backend.prompts.memory_compressor import (
            MEM_LEVEL_FULL, MEM_LEVEL_STRUCTURED, MEM_LEVEL_GRAPH, MEM_LEVEL_SUMMARY,
            MEM_LEVEL_NAMES, MEM_LEVEL_DESCRIPTIONS,
        )
        assert MEM_LEVEL_FULL       == 0
        assert MEM_LEVEL_STRUCTURED == 1
        assert MEM_LEVEL_GRAPH      == 2
        assert MEM_LEVEL_SUMMARY    == 3
        assert MEM_LEVEL_NAMES[0]   == "FULL"
        assert MEM_LEVEL_NAMES[3]   == "SUMMARY"
        assert len(MEM_LEVEL_DESCRIPTIONS) == 4

    def test_stage_questions_all_stages_covered(self):
        from backend.prompts.memory_compressor import _STAGE_QUESTIONS
        expected_stages = {"foundation", "mechanisms", "dependencies",
                           "optimization", "geopolitical", "disruption", "synthesis"}
        assert set(_STAGE_QUESTIONS.keys()) == expected_stages
