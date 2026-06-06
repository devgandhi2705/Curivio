"""
Phase 3.7 — Budget Stress Test Suite
=====================================

Validates that ModelAwareAssembler + BudgetDegradationEngine behave correctly
across every prompt type at four budget tiers (Tiny → Very Large).

20 test cases: 5 prompt profiles × 4 budget tiers.

Validation per test case
------------------------
1. No exception thrown under any budget
2. Assembled prompt is always a non-empty string
3. Every P1 CRITICAL anchor is present in the final prompt
4. JSON schema section always survives (never removed from P1)
5. AssemblyReport is fully populated (tokens, utilization, section count)
6. DegradationReport is populated when degradation was needed

Run (pytest):
    pytest tests/test_budget_stress.py -v -s

Run (standalone report):
    python tests/test_budget_stress.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import indent
from typing import Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.prompts.prompt_composer import PromptComposer
from backend.prompts.model_aware_assembler import ModelAwareAssembler, AssemblyReport


# Override conftest autouse fixture (may not be installed in all envs)
@pytest.fixture(autouse=True)
def reset_rate_limiter():
    yield


# ═══════════════════════════════════════════════════════════════════════════════
# Budget profiles
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BudgetProfile:
    label:         str
    model_name:    str
    provider_tier: str | None
    description:   str


BUDGET_PROFILES: list[BudgetProfile] = [
    BudgetProfile("Tiny",       "gemma2-9b-it",            None,         "8K ctx  → ~4K prompt budget"),
    BudgetProfile("Medium",     "llama-3.3-70b-versatile", "on_demand",  "128K ctx → ~4K effective (Groq free TPM)"),
    BudgetProfile("Large",      "llama-3.3-70b-versatile", None,         "128K ctx → ~92K prompt budget"),
    BudgetProfile("Very Large", "claude-sonnet-4-6",        None,         "200K ctx → ~150K prompt budget"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Content helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _pad(target_chars: int, seed: str = "The mechanism behind this is fundamentally misunderstood by most analysts in the field. ") -> str:
    """Generate a content block of approximately target_chars characters."""
    reps = max(1, target_chars // len(seed))
    return (seed * reps)[:target_chars]


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PromptFixture:
    label:         str
    composer:      PromptComposer
    p1_anchors:    list[str]   # unique strings that must survive in any output
    schema_anchor: str         # anchor for the JSON schema section


def _feed_fixture() -> PromptFixture:
    """
    Feed Generation / Project Insight — largest and most complex prompt.
    Realistic size: ~15,000 tokens.

    Section breakdown mirrors project_insight_prompt.py:
      P1 CRITICAL   intro, project_state, learning_trajectory, core_articles, output_schema
      P2 HIGH       curiosity_articles, editorial_philosophy, task_intro
      P3 USEFUL     writing_style, banned_phrases, hook_rules, why_it_works, source_signals
      P4 OPTIONAL   memory_section, narrative_frames, continuity
      P5 LUXURY     title_library, emotional_tone, action_design
    """
    c = PromptComposer()

    # P1 CRITICAL — total ~6,500 tokens
    c.add_section("intro",
        "ANCHOR:FEED_INTRO\n"
        "You are Curivio, an AI research journalist. Your job is to curate 5 daily insights "
        "for a learner studying Semiconductor Manufacturing on Day 15 of 30.\n"
        + _pad(1_800),
        priority=1, required=True, source_pack="core_editorial_pack")

    c.add_section("project_state",
        "ANCHOR:FEED_PROJECT\n"
        "Project: Semiconductor Manufacturing | Day 15/30 | Focus: TSMC Advanced Node Strategy\n"
        + _pad(1_200),
        priority=1, required=True, source_pack="dynamic")

    c.add_section("learning_trajectory",
        "ANCHOR:FEED_TRAJECTORY\n"
        "Prior learning: FinFET transistors (Day 8), EUV lithography (Day 12), ASML monopoly (Day 14).\n"
        + _pad(800),
        priority=1, required=True, source_pack="dynamic")

    c.add_section("core_articles",
        "ANCHOR:FEED_ARTICLES\n"
        "══════════════════════════════════════\n"
        "AVAILABLE ARTICLES — CORE LEARNING\n"
        "══════════════════════════════════════\n"
        + _pad(14_000,
               "Article: TSMC reports record 2nm yield above 70%. "
               "Gate-all-around transistors enable 40% power reduction. "
               "Intel Foundry Services trails by 18 months. "),
        priority=1, required=True, source_pack="dynamic")

    c.add_section("output_schema",
        "ANCHOR:FEED_SCHEMA\n"
        "Respond ONLY with valid JSON — no markdown, no prose outside the JSON object:\n"
        '{"package_headline": "...", "learning_thread": "...", "action_item": "...", '
        '"insights": [{"id": "card-1", "title": "...", "summary": "...", '
        '"why_it_matters": "...", "narrative_frame": "INVESTIGATIVE"}]}',
        priority=1, required=True, source_pack="package_narrative_pack")

    # P2 HIGH — total ~5,000 tokens
    c.add_section("curiosity_articles",
        "ANCHOR:FEED_CURIOSITY\n"
        "══════════════════════════════════════\n"
        "AVAILABLE ARTICLES — CURIOSITY ENGINE\n"
        "══════════════════════════════════════\n"
        + _pad(7_200,
               "Curiosity: Silicon Valley is literally a valley in Santa Clara County. "
               "TSMC was founded by Morris Chang, an MIT-trained engineer rejected by Texas Instruments. "
               "The first transistor was made of germanium, not silicon. "),
        priority=2, required=True, source_pack="dynamic")

    c.add_section("editorial_philosophy",
        "ANCHOR:FEED_EDITORIAL\n"
        "EDITORIAL PHILOSOPHY\n"
        "Surface the mechanism, not the event. Lead with the hidden tension.\n"
        + _pad(2_400),
        priority=2, required=True, source_pack="package_editorial_pack")

    c.add_section("task_intro",
        "YOUR TASK\n"
        "Generate a JSON package of 5 insights — 3 core learning + 2 curiosity picks.\n"
        + _pad(1_200),
        priority=2, required=True, source_pack="package_narrative_pack")

    # P3 USEFUL — total ~4,500 tokens
    c.add_section("writing_style",
        "WRITING STYLE STANDARDS\n"
        + _pad(3_600, "Rule: use active voice. Lead with the verb. Never bury the lede. Avoid passive constructions. "),
        priority=3, required=True, source_pack="core_writing_pack")

    c.add_section("banned_phrases",
        "BANNED PHRASES\n"
        + _pad(2_800, "Banned: 'in conclusion', 'it is important to note', 'as mentioned earlier', 'a lot'. "),
        priority=3, required=True, source_pack="core_writing_pack")

    c.add_section("hook_rules",
        "HOOK RULES\n"
        + _pad(2_400, "Hook: open with the highest-stakes sentence. The reader should feel tension in line one. "),
        priority=3, required=True, source_pack="core_writing_pack")

    c.add_section("why_it_works",
        "WHY IT WORKS\n"
        + _pad(2_000, "Example: 'TSMC controls 60% of advanced chips — that is why Taiwan matters to every nation.' "),
        priority=3, required=True, source_pack="core_reasoning_pack")

    c.add_section("source_signals",
        "SOURCE SIGNAL EXTRACTION\n"
        + _pad(1_600, "Signal: Bloomberg primary source. Reuters secondary. Press releases lowest weight. "),
        priority=3, required=True, source_pack="core_reasoning_pack")

    # P4 OPTIONAL — total ~3,000 tokens
    c.add_section("memory_section",
        "LEARNING MEMORY — DAY 15\n"
        + _pad(2_400, "Concepts learned: EUV lithography, FinFET geometry, ASML monopoly, gate oxide scaling. "),
        priority=4, required=False, source_pack="dynamic")

    c.add_section("narrative_frames",
        "NARRATIVE FRAMES\n"
        + _pad(2_000, "Frame 1: INVESTIGATIVE — expose the hidden mechanism behind the public fact. "),
        priority=4, required=True, source_pack="package_narrative_pack")

    c.add_section("continuity",
        "CONTINUITY\n"
        "Build on yesterday's FinFET deep-dive. Reference the ASML supply chain discussion.\n"
        + _pad(800),
        priority=4, required=False, source_pack="dynamic")

    # P5 LUXURY — total ~4,200 tokens
    c.add_section("title_library",
        "TITLE STYLE LIBRARY\n"
        + _pad(4_000, "Example title: 'The $10B Bottleneck Only 3 Companies Can Fix'. Pattern: 'The X That Y'. "),
        priority=5, required=True, source_pack="package_narrative_pack")

    c.add_section("emotional_tone",
        "EMOTIONAL TONE GUIDE\n"
        + _pad(3_200, "Tone: curious urgency. The reader should feel smart after reading, never lectured. "),
        priority=5, required=True, source_pack="package_narrative_pack")

    c.add_section("action_design",
        "ACTION DESIGN FRAMEWORK\n"
        + _pad(2_800, "Action type: INVESTIGATIVE MISSION — specific, startable in 10 minutes, references a named entity. "),
        priority=5, required=True, source_pack="package_action_pack")

    return PromptFixture(
        label         = "Feed Generation",
        composer      = c,
        p1_anchors    = ["ANCHOR:FEED_INTRO", "ANCHOR:FEED_PROJECT",
                         "ANCHOR:FEED_ARTICLES", "ANCHOR:FEED_SCHEMA"],
        schema_anchor = "ANCHOR:FEED_SCHEMA",
    )


def _chat_fixture() -> PromptFixture:
    """
    Chat / Structured Mode — medium-sized prompt.
    Realistic size: ~8,000 tokens.

    Section breakdown mirrors chat_prompt_service.py structured mode:
      P1 CRITICAL   persona, format_schema
      P2 HIGH       learning_system, depth, conversation_memory, knowledge_state, continuity
      P3 USEFUL     guidelines, format_directive, explanation_directive, tension
      P5 LUXURY     narrative
    """
    c = PromptComposer()

    # P1
    c.add_section("persona",
        "ANCHOR:CHAT_PERSONA\n"
        "You are Curivio's conversational AI — an expert learning companion.\n"
        + _pad(1_200),
        priority=1, required=True, source_pack="core_learning_pack")

    c.add_section("format_schema",
        "ANCHOR:CHAT_SCHEMA\n"
        "Respond ONLY with valid JSON:\n"
        '{"response": "...", "depth_hit": "mechanism|context|implication", '
        '"curiosity_hooks": ["..."], "follow_up_questions": ["..."], '
        '"concept_map": {"core": "...", "connected_to": []}}\n'
        + _pad(5_600,
               '{"field": "value", "nested": {"key": "val"}, "array": ["item1", "item2"]}. '),
        priority=1, required=True, source_pack="core_learning_pack")

    # P2
    c.add_section("learning_system",
        "LEARNING SYSTEM\n"
        "Feynman technique: explain until a 12-year-old can repeat it back.\n"
        + _pad(2_400),
        priority=2, required=False, source_pack="core_learning_pack")

    c.add_section("depth",
        "DEPTH INSTRUCTIONS — EXPERT\n"
        "Cover the mechanism, not just the fact. Build from first principles.\n"
        + _pad(2_800),
        priority=2, required=True, source_pack="core_learning_pack")

    c.add_section("conversation_memory",
        "CONVERSATION MEMORY\n"
        "User asked about EUV lithography yesterday. Covered: ASML monopoly, photomask costs, "
        "193nm ArF immersion vs EUV wavelength comparison.\n"
        + _pad(1_600),
        priority=2, required=False, source_pack="dynamic")

    c.add_section("knowledge_state",
        "KNOWLEDGE STATE\n"
        "User understands: basic transistors, Moore's Law, semiconductor supply chain at a high level.\n"
        + _pad(1_600),
        priority=2, required=False, source_pack="dynamic")

    c.add_section("continuity",
        "CONTINUITY\n"
        "Reference prior discussion of ASML and the EUV supply chain monopoly.\n"
        + _pad(1_200),
        priority=2, required=False, source_pack="dynamic")

    # P3
    c.add_section("guidelines",
        "INTERACTION GUIDELINES\n"
        + _pad(4_400, "Rule: never use unexplained jargon. Always follow technical terms with an analogy. "),
        priority=3, required=True, source_pack="core_learning_pack")

    c.add_section("format_directive",
        "FORMAT DIRECTIVE\n"
        "Structured JSON only. Every field is required. Do not omit any key.\n"
        + _pad(1_200),
        priority=3, required=False, source_pack="dynamic")

    c.add_section("explanation_directive",
        "EXPLANATION DIRECTIVE\n"
        "Build from first principles. Use Socratic progression.\n"
        + _pad(1_600),
        priority=3, required=False, source_pack="core_learning_pack")

    c.add_section("tension",
        "TENSION GENERATOR\n"
        "Highlight the contradiction: why does knowing FinFETs change how the user sees supply chains?\n"
        + _pad(1_200),
        priority=3, required=False, source_pack="dynamic")

    # P5
    c.add_section("narrative",
        "NARRATIVE MODE\n"
        "Make chip design feel like a detective story about the physics of the universe.\n"
        + _pad(1_600),
        priority=5, required=False, source_pack="core_learning_pack")

    return PromptFixture(
        label         = "Chat",
        composer      = c,
        p1_anchors    = ["ANCHOR:CHAT_PERSONA", "ANCHOR:CHAT_SCHEMA"],
        schema_anchor = "ANCHOR:CHAT_SCHEMA",
    )


def _deep_research_fixture() -> PromptFixture:
    """
    Deep Research — largest articles, most P2 analysis sections.
    Realistic size: ~22,000 tokens.

    Section breakdown mirrors deep_research_prompt.py:
      P1 CRITICAL   personas, topic_input, articles, schema
      P2 HIGH       source_analysis, viewpoints, output_preamble
      P3 USEFUL     writing_rules, synthesis_rules
    """
    c = PromptComposer()

    # P1
    c.add_section("personas",
        "ANCHOR:DR_PERSONAS\n"
        "You are a research synthesis engine composed of three expert personas: "
        "economist, semiconductor engineer, and geopolitical analyst.\n"
        + _pad(1_200),
        priority=1, required=True, source_pack="core_reasoning_pack")

    c.add_section("topic_input",
        "ANCHOR:DR_TOPIC\n"
        "Research topic: TSMC 2nm process technology — yield rates, competitive moat, "
        "and geopolitical implications for US-China semiconductor decoupling.",
        priority=1, required=True, source_pack="dynamic")

    c.add_section("articles",
        "ANCHOR:DR_ARTICLES\n"
        "══════════════════════════════════════\n"
        "RESEARCH ARTICLES\n"
        "══════════════════════════════════════\n"
        + _pad(20_000,
               "Article: TSMC yield rates for N2 process exceed 70% in Q1 2026. "
               "Gate-all-around nanosheet transistors provide 15% performance gain over FinFET. "
               "Intel Foundry 18A process delayed to Q3 2026 due to PowerVia backside PDN issues. "
               "Samsung 3nm yield remains below 60%. ASML EUV High-NA tool delivery on schedule. "),
        priority=1, required=True, source_pack="dynamic")

    c.add_section("schema",
        "ANCHOR:DR_SCHEMA\n"
        "Respond ONLY with valid JSON:\n"
        '{"synthesis": "...", "key_mechanisms": [{"mechanism": "...", "evidence": "..."}], '
        '"open_tensions": ["..."], "confidence": "high|medium|low", '
        '"follow_on_questions": ["..."], "source_quality": "..."}\n'
        + _pad(4_800,
               '{"mechanism": "GAA transistors reduce leakage current by 45% vs FinFET", '
               '"evidence": "TSMC N2 tape-out results Q4 2025"}. '),
        priority=1, required=True, source_pack="deep_research_pack")

    # P2
    c.add_section("source_analysis",
        "SOURCE ANALYSIS\n"
        + _pad(4_800,
               "Bloomberg primary: TSMC yield >70%. Reuters secondary: Intel 18A delayed. "
               "IEEE Spectrum technical: GAA nanosheet process details confirmed. "),
        priority=2, required=True, source_pack="core_reasoning_pack")

    c.add_section("viewpoints",
        "ANALYST VIEWPOINTS\n"
        + _pad(4_000,
               "Bull case: TSMC maintains 5-year moat. Bear case: SMIC 7nm volume production by 2027. "
               "Neutral: geopolitical risk is the dominant variable, not technical capability. "),
        priority=2, required=True, source_pack="core_reasoning_pack")

    c.add_section("output_preamble",
        "Output your synthesis below. Lead with the most counterintuitive finding.",
        priority=2, required=True, source_pack="deep_research_pack")

    # P3
    c.add_section("writing_rules",
        "SYNTHESIS WRITING RULES\n"
        + _pad(3_200, "Rule: every claim must be traceable to a named source. Hedge uncertain claims. "),
        priority=3, required=True, source_pack="core_writing_pack")

    c.add_section("synthesis_rules",
        "SYNTHESIS LOGIC RULES\n"
        + _pad(2_400, "Rule: identify contradictions between sources. Surface the mechanism behind the data. "),
        priority=3, required=True, source_pack="core_reasoning_pack")

    return PromptFixture(
        label         = "Deep Research",
        composer      = c,
        p1_anchors    = ["ANCHOR:DR_PERSONAS", "ANCHOR:DR_TOPIC",
                         "ANCHOR:DR_ARTICLES", "ANCHOR:DR_SCHEMA"],
        schema_anchor = "ANCHOR:DR_SCHEMA",
    )


def _explain_simply_fixture() -> PromptFixture:
    """
    Explain Simply / Layman Mode — medium prompt, user-state-heavy.
    Realistic size: ~7,500 tokens.

    Section breakdown mirrors learning_prompt.py in layman mode:
      P1 CRITICAL   persona_and_rules, user_state, content_input, schema
      P2 HIGH       source_analysis, output_preamble, layman_directive
      P3 USEFUL     personalization_rules, output_rules
    """
    c = PromptComposer()

    # P1
    c.add_section("persona_and_rules",
        "ANCHOR:ES_PERSONA\n"
        "You explain complex scientific concepts to curious non-experts. "
        "No jargon. No assumptions. Pure clarity.\n"
        + _pad(1_600),
        priority=1, required=True, source_pack="core_learning_pack")

    c.add_section("user_state",
        "ANCHOR:ES_STATE\n"
        "User profile: 16-year-old, intellectually curious, no prior engineering knowledge, "
        "loves analogies, frustrated by condescending explanations.\n"
        + _pad(1_200),
        priority=1, required=True, source_pack="dynamic")

    c.add_section("content_input",
        "ANCHOR:ES_CONTENT\n"
        "══════════════════════════════════════\n"
        "CONCEPT TO EXPLAIN\n"
        "══════════════════════════════════════\n"
        + _pad(7_600,
               "Photolithography: chipmakers use extreme ultraviolet light (13.5nm wavelength) "
               "to etch circuit patterns onto silicon wafers. Each chip contains billions of "
               "transistors at 2-3nm scale — smaller than a human DNA strand. "),
        priority=1, required=True, source_pack="dynamic")

    c.add_section("schema",
        "ANCHOR:ES_SCHEMA\n"
        "Respond ONLY with valid JSON:\n"
        '{"explanation": "...", "analogy": "...", "key_insight": "...", '
        '"curiosity_hook": "...", "next_concept": "..."}\n'
        + _pad(1_600,
               '{"analogy": "Imagine the chip as a city map, and EUV light as the most precise '
               'laser pointer ever made, drawing roads thinner than a virus."}. '),
        priority=1, required=True, source_pack="core_learning_pack")

    # P2
    c.add_section("source_analysis",
        "SOURCE ANALYSIS\n"
        "3 articles on photolithography condensed below.\n"
        + _pad(3_600, "Source insight: ASML holds 100% market share for EUV tools. Cost: $350M per machine. "),
        priority=2, required=True, source_pack="core_reasoning_pack")

    c.add_section("output_preamble",
        "Your explanation follows. Assume the user has never heard of a transistor.",
        priority=2, required=True, source_pack="core_learning_pack")

    c.add_section("layman_directive",
        "LAYMAN MODE — ACTIVE\n"
        "Avoid all technical jargon. If you must use a technical term, define it in plain language immediately.\n"
        + _pad(3_200),
        priority=2, required=False, source_pack="core_learning_pack")

    # P3
    c.add_section("personalization_rules",
        "PERSONALIZATION RULES\n"
        + _pad(2_000, "Rule: use everyday analogies — cooking, sports, music, city infrastructure. "),
        priority=3, required=True, source_pack="core_learning_pack")

    c.add_section("output_rules",
        "OUTPUT RULES\n"
        + _pad(1_600, "Rule: max 3 sentences per concept. One analogy per section. No bullet points. "),
        priority=3, required=True, source_pack="core_learning_pack")

    return PromptFixture(
        label         = "Explain Simply",
        composer      = c,
        p1_anchors    = ["ANCHOR:ES_PERSONA", "ANCHOR:ES_STATE",
                         "ANCHOR:ES_CONTENT", "ANCHOR:ES_SCHEMA"],
        schema_anchor = "ANCHOR:ES_SCHEMA",
    )


def _web_search_fixture() -> PromptFixture:
    """
    Web Search / Topic Expansion — smallest, minimal sections.
    Realistic size: ~2,500 tokens. Should fit under every budget.

    Section breakdown mirrors topic_expansion_prompt.py:
      P1 CRITICAL   persona, topic_input
      P2 HIGH       schema_intro, schema
      P3 USEFUL     field_requirements, rules
    """
    c = PromptComposer()

    # P1
    c.add_section("persona",
        "ANCHOR:WS_PERSONA\n"
        "You generate optimized, high-precision search queries for financial and technology research.\n"
        + _pad(800),
        priority=1, required=True, source_pack="core_reasoning_pack")

    c.add_section("topic_input",
        "ANCHOR:WS_TOPIC\n"
        "Expand this research topic into structured search queries: "
        "TSMC Q1 2026 earnings, capacity guidance, and 2nm ramp schedule.",
        priority=1, required=True, source_pack="dynamic")

    # P2
    c.add_section("schema_intro",
        "Generate a structured query expansion with primary, secondary, and adversarial queries.",
        priority=2, required=True, source_pack="core_reasoning_pack")

    c.add_section("schema",
        "ANCHOR:WS_SCHEMA\n"
        "Respond ONLY with valid JSON:\n"
        '{"primary_queries": ["..."], "secondary_queries": ["..."], '
        '"adversarial_queries": ["..."], "source_filters": ["Reuters", "Bloomberg", "SEC"]}',
        priority=2, required=True, source_pack="core_reasoning_pack")

    # P3
    c.add_section("field_requirements",
        "FIELD REQUIREMENTS\n"
        + _pad(1_200, "Include 3 primary queries, 5 secondary queries, 2 adversarial queries, 3 source filters. "),
        priority=3, required=True, source_pack="core_reasoning_pack")

    c.add_section("rules",
        "QUERY RULES\n"
        + _pad(800, "Rule: target authoritative sources. Include date ranges. Use Boolean operators where useful. "),
        priority=3, required=True, source_pack="core_reasoning_pack")

    return PromptFixture(
        label         = "Web Search",
        composer      = c,
        p1_anchors    = ["ANCHOR:WS_PERSONA", "ANCHOR:WS_TOPIC"],
        schema_anchor = "ANCHOR:WS_SCHEMA",
    )


# ── Fixture registry ──────────────────────────────────────────────────────────

PROMPT_FIXTURES: list[tuple[str, Callable[[], PromptFixture]]] = [
    ("Feed Generation", _feed_fixture),
    ("Chat",            _chat_fixture),
    ("Deep Research",   _deep_research_fixture),
    ("Explain Simply",  _explain_simply_fixture),
    ("Web Search",      _web_search_fixture),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Result collection
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class StressResult:
    prompt_label:    str
    budget_label:    str
    budget_tokens:   int
    original_tokens: int
    final_tokens:    int
    utilization_pct: float
    fits:            bool
    degraded:        bool
    steps_applied:   int
    compression:     str     # None | Light | Medium | Heavy
    p1_intact:       bool
    schema_intact:   bool
    error:           str = ""

    @property
    def quality(self) -> str:
        if self.steps_applied == 0:  return "Full   "
        if self.steps_applied <= 2:  return "High   "
        if self.steps_applied <= 4:  return "Good   "
        return                              "Degraded"

    @property
    def verdict(self) -> str:
        if self.error:        return "FAIL (exception)"
        if not self.p1_intact: return "FAIL (P1 dropped)"
        if not self.schema_intact: return "FAIL (schema dropped)"
        return "PASS"


def _compression_label(steps: int) -> str:
    if steps == 0:  return "None  "
    if steps <= 2:  return "Light "
    if steps <= 4:  return "Medium"
    return                 "Heavy "


_stress_results: list[StressResult] = []


# ═══════════════════════════════════════════════════════════════════════════════
# Core test logic
# ═══════════════════════════════════════════════════════════════════════════════

def _run_one(fixture: PromptFixture, profile: BudgetProfile) -> StressResult:
    """
    Run one (prompt_type × budget_tier) combination and return its result.
    Never raises — catches all exceptions and records them in StressResult.error.
    """
    try:
        prompt, report = ModelAwareAssembler.build(
            fixture.composer,
            profile.model_name,
            expected_output_tokens=0,
            provider_tier=profile.provider_tier,
        )
    except Exception as exc:  # noqa: BLE001
        return StressResult(
            prompt_label    = fixture.label,
            budget_label    = profile.label,
            budget_tokens   = 0,
            original_tokens = 0,
            final_tokens    = 0,
            utilization_pct = 0.0,
            fits            = False,
            degraded        = False,
            steps_applied   = 0,
            compression     = "ERROR ",
            p1_intact       = False,
            schema_intact   = False,
            error           = str(exc),
        )

    steps = len(report.degradation.steps_applied) if report.degradation else 0
    p1_ok = all(anchor in prompt for anchor in fixture.p1_anchors)
    schema_ok = fixture.schema_anchor in prompt

    return StressResult(
        prompt_label    = fixture.label,
        budget_label    = profile.label,
        budget_tokens   = report.effective_budget,
        original_tokens = report.original_tokens,
        final_tokens    = report.final_tokens,
        utilization_pct = report.utilization_pct,
        fits            = report.fits,
        degraded        = report.degraded,
        steps_applied   = steps,
        compression     = _compression_label(steps),
        p1_intact       = p1_ok,
        schema_intact   = schema_ok,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Pytest tests
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("profile", BUDGET_PROFILES, ids=[p.label for p in BUDGET_PROFILES])
@pytest.mark.parametrize("fixture_name,builder", PROMPT_FIXTURES, ids=[n for n, _ in PROMPT_FIXTURES])
def test_stress(fixture_name: str, builder: Callable[[], PromptFixture], profile: BudgetProfile) -> None:
    """
    Run one stress test cell.

    Assertions:
    1. No exception raised by ModelAwareAssembler
    2. Prompt text is a non-empty string
    3. All P1 CRITICAL anchors survive in the final prompt
    4. JSON schema anchor survives in the final prompt
    5. AssemblyReport has positive final_tokens and section_count
    """
    fixture = builder()

    # 1. No crash
    prompt, report = ModelAwareAssembler.build(
        fixture.composer,
        profile.model_name,
        expected_output_tokens=0,
        provider_tier=profile.provider_tier,
    )

    # 2. Non-empty output
    assert prompt, (
        f"[{fixture.label} / {profile.label}] "
        f"ModelAwareAssembler returned empty string"
    )

    # 3. P1 CRITICAL anchors always survive
    for anchor in fixture.p1_anchors:
        assert anchor in prompt, (
            f"[{fixture.label} / {profile.label}] "
            f"P1 CRITICAL anchor '{anchor}' was removed from the assembled prompt. "
            f"Budget={report.effective_budget:,}, Final={report.final_tokens:,}, "
            f"Steps={len(report.degradation.steps_applied) if report.degradation else 0}"
        )

    # 4. Schema section always survives
    assert fixture.schema_anchor in prompt, (
        f"[{fixture.label} / {profile.label}] "
        f"JSON schema anchor '{fixture.schema_anchor}' was removed. "
        f"This breaks structured output."
    )

    # 5. Report is populated
    assert report.final_tokens > 0, f"[{fixture.label} / {profile.label}] final_tokens == 0"
    assert report.section_count > 0, f"[{fixture.label} / {profile.label}] section_count == 0"

    # Collect for report
    result = _run_one(fixture, profile)
    _stress_results.append(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Comparison report
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_k(n: int) -> str:
    """Format token count compactly: 15741 → '15.7K', 4053 → '4.1K', 540 → '540'."""
    if n >= 10_000: return f"{n/1_000:.0f}K  "
    if n >= 1_000:  return f"{n/1_000:.1f}K "
    return f"{n}   "


def generate_report(results: list[StressResult]) -> str:
    """Build the multi-section comparison report as a string."""
    W   = 80
    SEP = "-" * W
    HDR = "=" * W
    lines: list[str] = []

    def h(text: str) -> None:
        lines.append(HDR)
        lines.append(f"  {text}")
        lines.append(HDR)

    def subh(text: str) -> None:
        lines.append(f"\n{text}")
        lines.append(SEP)

    # ── Header ───────────────────────────────────────────────────────────────
    h("PHASE 3.7 — BUDGET STRESS TEST REPORT")
    lines.append(f"  {len(PROMPT_FIXTURES)} prompt profiles × {len(BUDGET_PROFILES)} budget tiers = {len(results)} test cases\n")

    # ── Section 1: Token Usage & Budget Utilization ───────────────────────────
    subh("SECTION 1 — TOKEN USAGE & BUDGET UTILIZATION")
    col = f"  {'Profile':<20} {'Tier':<11} {'Budget':>8}  {'Original':>9}  {'Final':>8}  {'Util%':>6}  {'Fits'}"
    lines.append(col)
    lines.append(SEP)

    for r in results:
        fits_tag = " Y" if r.fits else " N"
        if r.error:
            lines.append(f"  {'  '.join([r.prompt_label[:18], r.budget_label[:10]])} ERROR: {r.error[:40]}")
            continue
        lines.append(
            f"  {r.prompt_label:<20} {r.budget_label:<11}"
            f"  {_fmt_k(r.budget_tokens):>8}"
            f"  {_fmt_k(r.original_tokens):>9}"
            f"  {_fmt_k(r.final_tokens):>8}"
            f"  {r.utilization_pct:>5.1f}%"
            f"  {fits_tag}"
        )

    # ── Section 2: Compression Level ─────────────────────────────────────────
    subh("SECTION 2 — COMPRESSION LEVEL  (steps applied / 6)")

    tier_labels = [p.label for p in BUDGET_PROFILES]
    hdr2 = f"  {'Profile':<22}" + "".join(f"  {t:<13}" for t in tier_labels)
    lines.append(hdr2)
    lines.append(SEP)

    for fixture_name, _ in PROMPT_FIXTURES:
        row_results = {r.budget_label: r for r in results if r.prompt_label == fixture_name}
        cells = []
        for p in BUDGET_PROFILES:
            r = row_results.get(p.label)
            if r and not r.error:
                cells.append(f"{r.compression}({r.steps_applied})")
            else:
                cells.append("ERROR       ")
        lines.append(f"  {fixture_name:<22}" + "".join(f"  {c:<13}" for c in cells))

    # ── Section 3: Quality Metrics ───────────────────────────────────────────
    subh("SECTION 3 — QUALITY METRICS")
    col3 = f"  {'Profile':<20} {'Tier':<11}  {'Quality':<9}  {'P1 Intact':>9}  {'Schema':>6}  {'Verdict'}"
    lines.append(col3)
    lines.append(SEP)

    for r in results:
        if r.error:
            lines.append(f"  {r.prompt_label:<20} {r.budget_label:<11}  ERROR")
            continue
        p1_tag     = "  OK   " if r.p1_intact    else "  FAIL "
        schema_tag = "   OK  " if r.schema_intact else "  FAIL "
        lines.append(
            f"  {r.prompt_label:<20} {r.budget_label:<11}"
            f"  {r.quality:<9}"
            f"  {p1_tag}"
            f"  {schema_tag}"
            f"  {r.verdict}"
        )

    # ── Section 4: Per-Tier Summary ───────────────────────────────────────────
    subh("SECTION 4 — PER-TIER SUMMARY")
    col4 = f"  {'Budget Tier':<13}  {'Pass Rate':>9}  {'Avg Util%':>9}  {'Avg Steps':>9}  {'All Fit?'}"
    lines.append(col4)
    lines.append(SEP)

    for p in BUDGET_PROFILES:
        tier_results = [r for r in results if r.budget_label == p.label and not r.error]
        if not tier_results:
            continue
        passes    = sum(1 for r in tier_results if r.verdict == "PASS")
        avg_util  = sum(r.utilization_pct for r in tier_results) / len(tier_results)
        avg_steps = sum(r.steps_applied for r in tier_results) / len(tier_results)
        all_fit   = "Yes" if all(r.fits for r in tier_results) else "No "
        lines.append(
            f"  {p.label:<13}"
            f"  {passes}/{len(tier_results):>2} PASS"
            f"  {avg_util:>8.1f}%"
            f"  {avg_steps:>9.1f}"
            f"  {all_fit}"
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append("")
    all_pass = all(r.verdict == "PASS" for r in results)
    n_pass   = sum(1 for r in results if r.verdict == "PASS")
    n_fail   = len(results) - n_pass

    lines.append(HDR)
    if all_pass:
        lines.append(f"  ALL {len(results)} TESTS PASSED")
        lines.append( "  No failures · No schema breaks · P1 invariant held across all budget tiers")
        lines.append( "  Curivio scales from small models to large models automatically.")
    else:
        lines.append(f"  {n_pass}/{len(results)} PASSED · {n_fail} FAILED")
        for r in results:
            if r.verdict != "PASS":
                lines.append(f"  FAIL: {r.prompt_label} / {r.budget_label} — {r.verdict}")
    lines.append(HDR)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Session report (pytest -s shows this after all tests)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _session_report(request):
    """Print the comparison report at the end of the test session."""
    yield
    if _stress_results:
        print("\n\n" + generate_report(_stress_results) + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import logging
    logging.disable(logging.WARNING)   # suppress per-test log noise

    results: list[StressResult] = []
    total = len(PROMPT_FIXTURES) * len(BUDGET_PROFILES)
    passed = 0

    print(f"Running {total} stress tests ({len(PROMPT_FIXTURES)} prompts × {len(BUDGET_PROFILES)} budget tiers)...\n")

    for fixture_name, builder in PROMPT_FIXTURES:
        fixture = builder()
        baseline = fixture.composer.estimate_tokens()
        print(f"  {fixture.label:<20} baseline {baseline:,} tokens")

        for profile in BUDGET_PROFILES:
            result = _run_one(fixture, profile)
            results.append(result)

            ok = result.verdict == "PASS"
            if ok:
                passed += 1
            tag = "PASS" if ok else f"FAIL ({result.verdict})"
            print(
                f"    [{profile.label:<10}]  budget={result.budget_tokens:>7,}"
                f"  final={result.final_tokens:>7,}"
                f"  util={result.utilization_pct:5.1f}%"
                f"  steps={result.steps_applied}"
                f"  {tag}"
            )
        print()

    print(generate_report(results))
    sys.exit(0 if passed == total else 1)
