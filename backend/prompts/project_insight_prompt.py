"""
Progressive learning package prompt — Editorial Intelligence Edition.

Two-section architecture:
  SECTION 1 — Core Learning Feed (configurable count, news + educational)
               Insight-first, editorially framed cards with narrative hooks.
               Accelerating depth: each day goes deeper, wider, or more applied
               than the last — never the same surface level twice.

  SECTION 2 — Curiosity Engine (exactly 2 cards, content_type="curiosity")
               Intellectual rabbit holes. Surprising, strange, counterintuitive.
               Feels like a discovery, not a mini-lesson.

Static instruction sections are owned by instruction_packs/package_*.py.
Dynamic project/article content is assembled here at generation time.

Phase 9.3.4B additions:
  PromptMode         — PACKAGE | BATCH | SYNTHESIS
  PromptContext      — structured input to build_batch_prompt()
  build_batch_prompt — core prompt builder; package mode = batch_plan=None
  make_daily_package_composer — backward-compat wrapper (unchanged call signature)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services.article_plan_service import BatchPlan

from .prompt_composer import PromptComposer
from .instruction_packs.core_writing_pack   import WRITING_STYLE_STANDARDS, BANNED_PHRASES
from .instruction_packs.core_reasoning_pack import SOURCE_SIGNAL_EXTRACTION, REAL_WORLD_TENSION
from .instruction_packs.package_editorial_pack import (
    EDITORIAL_PHILOSOPHY, HOOK_FIRST_RULES,
)
from .instruction_packs.package_narrative_pack import (
    EMOTIONAL_TONE_PALETTE, TITLE_STYLE_LIBRARY,
    EDITORIAL_ROLES, PACKAGE_COMPOSITION, ARTICLE_MIX, SECTION_1_INSTRUCTIONS,
)
from .instruction_packs.package_curiosity_pack import (
    CURIOSITY_TARGET, TENSION_SCORING, TENSION_CATEGORIES,
    CURIOSITY_TITLE_RULES, CURIOSITY_SUMMARY_RULES, CURIOSITY_CARD_RULES,
)
from .instruction_packs.package_action_pack import ACTION_DESIGN

logger = logging.getLogger(__name__)


# ── Prompt mode ───────────────────────────────────────────────────────────────

class PromptMode(str, Enum):
    PACKAGE   = "package"    # all articles in one prompt (current single-call behavior)
    BATCH     = "batch"      # one batch of articles per prompt (multi-call, Phase 9.3.4C+)
    SYNTHESIS = "synthesis"  # cross-batch synthesis call (future)


# ── Prompt context ────────────────────────────────────────────────────────────

@dataclass
class PromptContext:
    """
    Structured input to build_batch_prompt().

    Holds all project/learner context. Pre-formatted article text is passed
    separately to build_batch_prompt() because budget computation
    (ArticleCompressor) happens outside the prompt builder.
    """
    project_name:             str
    keywords:                 list[str]
    difficulty:               str
    day_number:               int
    display_label:            str
    daily_core_article_count: int         = 4
    intent_profile:           dict | None = None
    knowledge_state:          dict | None = None
    curiosity_directives:     str | None  = None
    intelligence_context:     str | None  = None
    quality_feedback:         str | None  = None
    # PACKAGE mode: pre-built article plan string from article_plan_service
    article_plan_block:       str | None  = None
    # Used by the make_daily_package_composer wrapper for its internal formatting fallback
    article_budget_tokens:    int         = 0
    mode:                     PromptMode  = PromptMode.PACKAGE
    frame_hint:               str | None  = None


# ── Token breakdown section categories ───────────────────────────────────────

_INSTRUCTION_SECTIONS: frozenset[str] = frozenset({
    "editorial_philosophy", "emotional_tone",
    "hook_rules", "writing_style", "banned_phrases", "title_library",
    "source_signals", "real_world_tension", "action_design", "task_intro",
    "section1_instructions", "curiosity_instructions", "curiosity_strategy",
    "beginner_calibration",
})
_SOURCE_SECTIONS: frozenset[str] = frozenset({
    "core_articles", "curiosity_articles", "article_source_assignments",
})
_SCHEMA_SECTIONS: frozenset[str] = frozenset({
    "output_schema", "source_grounding",
})


def _log_prompt_breakdown(
    composer:  PromptComposer,
    mode:      PromptMode,
    batch_id:  int | None,
) -> None:
    """Emit [PROMPT BREAKDOWN] log — token totals by section category."""
    instr_tok = sum(
        s.tokens for s in composer._sections if s.name in _INSTRUCTION_SECTIONS
    )
    source_tok = sum(
        s.tokens for s in composer._sections if s.name in _SOURCE_SECTIONS
    )
    schema_tok = sum(
        s.tokens for s in composer._sections if s.name in _SCHEMA_SECTIONS
    )
    knowledge_tok = sum(
        s.tokens for s in composer._sections
        if s.name not in _INSTRUCTION_SECTIONS | _SOURCE_SECTIONS | _SCHEMA_SECTIONS
    )
    total_tok = sum(s.tokens for s in composer._sections)
    logger.info(
        "[PROMPT BREAKDOWN] mode=%s batch=%s  "
        "instruction=%d  source=%d  schema=%d  knowledge=%d  total=%d",
        mode.value,
        str(batch_id) if batch_id is not None else "pkg",
        instr_tok, source_tok, schema_tok, knowledge_tok, total_tok,
    )


def _build_editorial_roles_mix(knowledge_state: dict | None) -> str:
    """
    Build a short editorial-roles + article-mix instruction based on knowledge_state.
    Falls back to the static EDITORIAL_ROLES + ARTICLE_MIX strings when knowledge_state
    is empty or unavailable (e.g. day 1, failed load).
    """
    ks     = knowledge_state or {}
    gaps   = [g for g in ks.get("knowledge_gaps",  []) if g][:4]
    active = [a for a in ks.get("active_topics",   []) if a][:3]

    if not gaps and not active:
        return f"{EDITORIAL_ROLES}\n\n{ARTICLE_MIX}"

    roles_line = (
        "Before writing any card, assign each an editorial role "
        "(CENTERPIECE, PRACTICAL INTEL, FAST SIGNAL, FUTURE PREDICTION, STRATEGIC SHIFT, WILD CARD) "
        "and an emotional tone from the palette above."
    )

    if gaps:
        gap_str    = ", ".join(gaps[:3])
        active_str = ", ".join(active) if active else "any recently covered topic"
        return (
            f"{roles_line}\n"
            f"Today's knowledge gaps to address: {gap_str}. "
            f"Assign at least one CENTERPIECE or STRATEGIC SHIFT card to the largest gap.\n\n"
            f"ARTICLE MIX (today — gaps present):\n"
            f"  • 1–2 cards closing gaps: {gap_str}\n"
            f"  • 1–2 cards advancing active topics at deeper depth: {active_str}\n"
            f"  • 1 real-world/news card, 1 practical/case-study card"
        )

    active_str = ", ".join(active)
    return (
        f"{roles_line}\n"
        f"Active topics to advance at deeper depth: {active_str}.\n\n"
        f"ARTICLE MIX (today — active topics present):\n"
        f"  • 2–3 progression cards building further on: {active_str}\n"
        f"  • 1–2 cards introducing adjacent ideas or new concepts\n"
        f"  • 1 real-world/news card, 1 practical/case-study card"
    )


# ── Core prompt builder ───────────────────────────────────────────────────────

def build_batch_prompt(
    context:               PromptContext,
    batch_plan:            BatchPlan | None = None,
    core_article_text:     str = "",
    curiosity_article_text: str = "",
) -> PromptComposer:
    """
    Build a PromptComposer from a PromptContext and optional BatchPlan.

    PACKAGE mode (batch_plan=None):
      Identical behavior to the old make_daily_package_composer().
      Source IDs: CORE-N / CURIOSITY-N (unchanged).
      context.article_plan_block used for source assignments.
      Curiosity section included.

    BATCH mode (batch_plan is not None):
      Prompt scoped to the batch's articles only.
      Source IDs prefixed: B{batch_id}-CORE-N (e.g. B1-CORE-1, B2-CORE-3).
      Article plan block generated from batch_plan.plans.
      No separate curiosity section (curiosity lives in its own batch).

    Pre-formatted article text must always be passed by the caller.
    No internal ArticleCompressor call. See make_daily_package_composer() for
    the wrapper that handles the optional-text backward-compat path.

    Emits [PROMPT BREAKDOWN] log (instruction / source / schema / knowledge / total tokens).
    """
    kw_str = ", ".join(context.keywords) if context.keywords else context.project_name

    # Per-batch slot count — 0 in PACKAGE mode (batch_plan is None)
    _n_batch = len(batch_plan.plans) if batch_plan is not None else 0

    count = max(2, min(10, int(context.daily_core_article_count)))
    if count <= 3:
        intensity_label    = "Light"
        intensity_guidance = (
            f"Generate {count} high-quality cards. Go deep on 1–2 concepts — "
            "depth over breadth. Every card must earn its place."
        )
    elif count <= 5:
        intensity_label    = "Standard"
        intensity_guidance = (
            f"Generate {count} cards: a balanced mix of depth and breadth. "
            "1–2 reinforcement cards, 2–3 new progression concepts, "
            "1 real-world/news card, 1 practical/case-study card."
        )
    else:
        intensity_label    = "Intensive"
        intensity_guidance = (
            f"Generate {count} cards with wide coverage. "
            "2 reinforcement/evolution cards, 2–3 new progression concepts, "
            "1 current/news card, 1 practical/case-study card. "
            "Introduce cross-domain connections and adjacent ideas."
        )

    # BATCH mode: override intensity_guidance to reflect THIS batch's slot count,
    # not the full daily count.  The model must not see a count that contradicts
    # the hard-count instruction in task_intro.
    if _n_batch > 0:
        if _n_batch <= 3:
            intensity_guidance = (
                f"Generate {_n_batch} high-quality cards. Go deep on 1–2 concepts — "
                "depth over breadth. Every card must earn its place."
            )
        elif _n_batch <= 5:
            intensity_guidance = (
                f"Generate {_n_batch} cards: a balanced mix of depth and breadth. "
                "1–2 reinforcement cards, 2–3 new progression concepts, "
                "1 real-world/news card, 1 practical/case-study card."
            )
        else:
            intensity_guidance = (
                f"Generate {_n_batch} cards with wide coverage. "
                "2 reinforcement/evolution cards, 2–3 new progression concepts, "
                "1 current/news card, 1 practical/case-study card. "
                "Introduce cross-domain connections and adjacent ideas."
            )

    if context.difficulty == "beginner":
        beginner_section_str = f"""══════════════════════════════════════
BEGINNER CALIBRATION — MANDATORY OVERRIDES
══════════════════════════════════════
Learner level is BEGINNER. All content MUST follow CONCEPTUAL LADDERING — no exceptions.

CONCEPTUAL LADDERING RULE:
  Every advanced idea must travel this path before the abstract framing appears:

  STEP 1 — CONCRETE ANCHOR: one tangible thing the reader can picture right now
  STEP 2 — MECHANISM: how the domain concept connects to that anchor
  STEP 3 — IMPLICATION: the strategic/systemic consequence, now grounded

  BAD (abstract first):
    "API dependency creates pharmaceutical supply chain fragility at scale."
  GOOD (concrete first):
    "Most of the raw ingredients in Indian-made medicines come from factories in China.
     When those factories slow down or a port closes, Indian drug companies run out of
     the chemicals they need — even if every Indian factory is working perfectly."
  THEN add the implication:
    "This is why Indian pharma companies are racing to build domestic ingredient
     manufacturing — not because it's cheaper, but because one political decision
     in Beijing can stop their entire production line."

JARGON RULE — every technical term needs an immediate plain-English definition on first use:
  BAD:  "APIs constitute the upstream input in the pharmaceutical value chain."
  GOOD: "APIs — the active chemical compounds that make medicines actually work — come
         mostly from a handful of factories in China."

FORBIDDEN IN BEGINNER MODE:
  × Opening a summary with the abstract concept before the concrete anchor
  × Stacking two or more domain-specific concepts without grounding each one
  × Geopolitical analysis without first establishing the basic economic stakes in one sentence
  × Phrases: "value chain", "supply fragility", "dependency risk" — unless explained immediately
  × Strategic framing in the first two sentences before the mechanism is grounded
  × "competitive dynamics", "market fragmentation", "regulatory pathway" without plain-English context
  × Assuming knowledge of acronyms (API, CMO, ANDA, EMA, CDSCO) without one-phrase explanations

ANALOGY REQUIREMENT:
  At least 1 card per package must use a cross-domain analogy to explain a mechanism.
  Useful bridges: logistics → medicine delivery; phone hardware → drug ingredients;
  restaurant supply chain → pharma raw materials; copyright law → drug patents.

CARD LENGTH FOR BEGINNER:
  Summaries: 2–3 sentences max. Concrete hook → plain-language mechanism. No compression.
  Educational explanation: build up one idea fully before introducing the next.
  No multi-clause sentences that require domain knowledge to parse.

SELF-CHECK before writing each card — ask yourself:
  "Could a smart 18-year-old who has never studied {context.project_name} understand the first sentence?"
  If NO → rewrite it. Concrete first. Abstract second. Always."""
    else:
        beginner_section_str = ""

    # ── Batch vs package configuration ────────────────────────────────────────
    is_batch    = batch_plan is not None
    _sid_prefix = f"B{batch_plan.batch_id}-" if is_batch else ""
    _batch_type = (
        (batch_plan.plans[0].article_type.upper() if batch_plan.plans else "CORE")
        if is_batch else "CORE"
    )

    # Article plan block
    if is_batch:
        from ..services.article_plan_service import plans_to_prompt_block as _p2pb
        _batch_articles = [
            {"url": p.primary_source.get("url", ""), "title": p.primary_source.get("title", "")}
            for p in batch_plan.plans
            if p.primary_source
        ]
        _plan_block = _p2pb(
            batch_plan.plans, _batch_articles,
            source_id_prefix=_sid_prefix,
            frame_hint=context.frame_hint,
            article_type_label=_batch_type,
        )
    else:
        _plan_block = context.article_plan_block

    # Article section content strings
    if is_batch:
        _core_section_content = (
            f"══════════════════════════════════════\n"
            f"AVAILABLE ARTICLES — BATCH {batch_plan.batch_id} ({_batch_type})\n"
            f"══════════════════════════════════════\n"
            f"{core_article_text}"
        )
    else:
        _core_section_content = (
            f"══════════════════════════════════════\n"
            f"AVAILABLE ARTICLES — CORE LEARNING\n"
            f"══════════════════════════════════════\n"
            f"{core_article_text}"
        )

    _curio_section_content = (
        f"══════════════════════════════════════\n"
        f"AVAILABLE ARTICLES — CURIOSITY ENGINE\n"
        f"══════════════════════════════════════\n"
        f"{curiosity_article_text}"
    )

    # Format templated pack sections with runtime values
    hook_section    = HOOK_FIRST_RULES.format(domain=context.project_name)
    pkg_composition = PACKAGE_COMPOSITION.format(count=count)
    section1        = SECTION_1_INSTRUCTIONS.format(
                          count=(_n_batch or count), project_name=context.project_name,
                          difficulty=context.difficulty,
                      )
    curiosity_rules = CURIOSITY_CARD_RULES.format(project_name=context.project_name)

    # ── Global sections ───────────────────────────────────────────────────────
    composer = PromptComposer()

    composer.add_section("intro", (
        f"You are the editorial intelligence behind Curivio — a premium daily learning briefing system.\n"
        f"Your role: surface the most important signals, hidden implications, and insight-rich ideas from the {context.project_name} domain.\n\n"
        f"You are NOT summarizing topics for a textbook.\n"
        f"You ARE curating intelligence the way a brilliant analyst friend would — with judgment, narrative, and editorial intentionality."
    ),                   priority=1, required=True,  source_pack="")

    composer.add_section("project_state", (
        f"══════════════════════════════════════\n"
        f"PROJECT STATE\n"
        f"══════════════════════════════════════\n"
        f"Project:       {context.project_name}\n"
        f"Keywords:      {kw_str}\n"
        f"Learner level: {context.difficulty}\n"
        f"Today:         {context.display_label}\n"
        f"Intensity:     {intensity_label} ({_n_batch or count} cards) — {intensity_guidance}"
    ),                   priority=1, required=True,  source_pack="dynamic")

    if context.intent_profile:
        composer.add_section("intent_profile", (
            f"LEARNER INTENT PROFILE\n"
            f"Persona:          {context.intent_profile.get('persona', 'Learner')}\n"
            f"Goal:             {context.intent_profile.get('goal', '')}\n"
            f"Industry context: {context.intent_profile.get('industry_context', '')}\n"
            f"Primary focus:    {context.intent_profile.get('primary_focus', context.project_name)}\n"
            f"Search lens:      {context.intent_profile.get('search_lens', 'Educational')}\n"
            f"\n"
            f"{context.intent_profile.get('intent_summary', '')}\n"
            f"\n"
            f"Every card must speak directly to this persona's goal. "
            f"Frame content through the '{context.intent_profile.get('search_lens', 'Educational')}' lens "
            f"for a '{context.intent_profile.get('persona', 'learner')}' focused on "
            f"'{context.intent_profile.get('primary_focus', context.project_name)}'."
        ),               priority=1, required=False, source_pack="dynamic")

    _gaps = (context.knowledge_state or {}).get("knowledge_gaps", [])
    _next_guidance = (
        "Priority gaps to address: " + ", ".join(_gaps[:5])
        if _gaps else
        "Follow the knowledge state above — go deeper on active topics and bridge identified gaps."
    )
    composer.add_section("learning_trajectory", (
        f"══════════════════════════════════════\n"
        f"LEARNING TRAJECTORY\n"
        f"══════════════════════════════════════\n"
        f"Build strictly on the Knowledge State below — go deeper or wider, never re-introduce\n"
        f"covered concepts at the same level.\n\n"
        f"{_next_guidance}"
    ),                   priority=1, required=True,  source_pack="dynamic")

    if context.knowledge_state:
        covered_str  = ", ".join(context.knowledge_state.get("covered_topics",   [])[-20:]) or "—"
        active_str   = ", ".join(context.knowledge_state.get("active_topics",    [])[:8])   or "—"
        recent_str   = ", ".join(context.knowledge_state.get("recent_topics",    [])[:8])   or "—"
        gaps_str     = ", ".join(context.knowledge_state.get("knowledge_gaps",   [])[:10])  or "none identified"
        entities_str = ", ".join(context.knowledge_state.get("covered_entities", [])[-15:]) or "—"
        keywords_str = ", ".join(context.knowledge_state.get("covered_keywords", [])[-20:]) or "—"
        composer.add_section("knowledge_state", (
            f"══════════════════════════════════════\n"
            f"KNOWLEDGE STATE\n"
            f"══════════════════════════════════════\n"
            f"Topics covered:    {covered_str}\n"
            f"Currently active:  {active_str}\n"
            f"Recent coverage:   {recent_str}\n"
            f"Known gaps:        {gaps_str}\n"
            f"Entities seen:     {entities_str}\n"
            f"Keywords used:     {keywords_str}\n"
            f"\n"
            f"Prioritise at least one known gap per package. Anchor new ideas to known entities and keywords."
        ),               priority=1, required=False, source_pack="dynamic")

    if context.intelligence_context:
        composer.add_section(
            "feed_intelligence",
            context.intelligence_context,
            priority=1, required=False, source_pack="dynamic",
        )

    if context.quality_feedback:
        composer.add_section(
            "quality_feedback",
            context.quality_feedback,
            priority=1, required=False, source_pack="dynamic",
        )

    composer.add_section("editorial_philosophy",    EDITORIAL_PHILOSOPHY,
                         priority=2, required=True,  source_pack="package_editorial_pack")
    composer.add_section("beginner_calibration",    beginner_section_str,
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("emotional_tone",          EMOTIONAL_TONE_PALETTE,
                         priority=5, required=True,  source_pack="package_narrative_pack")
    composer.add_section("hook_rules",              hook_section,
                         priority=3, required=True,  source_pack="package_editorial_pack")
    composer.add_section("writing_style",           WRITING_STYLE_STANDARDS,
                         priority=3, required=True,  source_pack="core_writing_pack")
    composer.add_section("banned_phrases",          BANNED_PHRASES,
                         priority=3, required=True,  source_pack="core_writing_pack")
    composer.add_section("title_library",           TITLE_STYLE_LIBRARY,
                         priority=5, required=True,  source_pack="package_narrative_pack")
    composer.add_section("source_signals",          SOURCE_SIGNAL_EXTRACTION,
                         priority=3, required=True,  source_pack="core_reasoning_pack")
    composer.add_section("real_world_tension",      REAL_WORLD_TENSION,
                         priority=3, required=True,  source_pack="core_reasoning_pack")

    # ── Source/batch sections ─────────────────────────────────────────────────
    composer.add_section("core_articles",     _core_section_content,
                         priority=1, required=True,  source_pack="dynamic")

    # Curiosity section: present in PACKAGE mode; omitted in BATCH mode
    # (curiosity articles are planned in their own batch and arrive via their own call)
    if not is_batch:
        composer.add_section("curiosity_articles", _curio_section_content,
                             priority=2, required=True, source_pack="dynamic")

    if _plan_block:
        _angle_nudge = (
            "Vary the editorial angle across cards "
            "(e.g. investigative, future-focused, story-driven, comparative).\n"
            "\"Narrative shape\" per slot below describes how the SOURCE MATERIAL is structured "
            "(timeline / comparison / single-discovery-story). "
            "\"narrative_frame\" in your output is the editorial VOICE telling the story — "
            "these are independent: any narrative_frame can be applied to any narrative shape.\n\n"
        )
        composer.add_section(
            "article_source_assignments",
            _angle_nudge + _plan_block,
            priority=1, required=False, source_pack="dynamic",
        )

    # ── Task / output sections ────────────────────────────────────────────────
    if is_batch:
        _n_cards = len(batch_plan.plans)
        _task_intro_content = (
            f"══════════════════════════════════════\n"
            f"YOUR TASK — BATCH {batch_plan.batch_id} ({_batch_type})\n"
            f"══════════════════════════════════════\n\n"
            f"Generate EXACTLY {_n_cards} insight card(s) — one card per article slot in this batch.\n"
            f"EXACTLY {_n_cards} is a hard count: not a minimum, not a suggestion.\n"
            f"Any count mentioned elsewhere in these instructions describes the full multi-batch package — ignore those counts for this batch.\n"
            f"Apply all editorial, narrative, and writing guidelines above.\n"
            f"Every card MUST cite its assigned source (ARTICLE SOURCE ASSIGNMENTS).\n"
            f"Respond with JSON batch result exactly as specified below."
        )
    else:
        _roles_mix = _build_editorial_roles_mix(context.knowledge_state)
        _task_intro_content = (
            f"══════════════════════════════════════\n"
            f"YOUR TASK\n"
            f"══════════════════════════════════════\n\n"
            f"{_roles_mix}\n\n"
            f"{pkg_composition}\n\n"
            f"Generate a JSON package with TWO sections:"
        )
    composer.add_section("task_intro", _task_intro_content,
                         priority=2, required=True,  source_pack="package_narrative_pack")

    # section1 describes core "insights" array — skip for curiosity-only batches
    if not is_batch or _batch_type != "CURIOSITY":
        composer.add_section("section1_instructions", section1,
                             priority=2, required=True, source_pack="package_narrative_pack")

    if context.curiosity_directives:
        composer.add_section(
            "curiosity_strategy",
            context.curiosity_directives,
            priority=1, required=False, source_pack="dynamic",
        )

    # curiosity_instructions: PACKAGE mode always; BATCH mode only for curiosity batch
    if not is_batch or _batch_type == "CURIOSITY":
        composer.add_section("curiosity_instructions", (
            f"{CURIOSITY_TARGET}\n"
            f"{TENSION_SCORING}\n"
            f"{TENSION_CATEGORIES}\n"
            f"{CURIOSITY_TITLE_RULES}\n"
            f"{CURIOSITY_SUMMARY_RULES}\n"
            f"{curiosity_rules}"
        ),                   priority=2, required=True, source_pack="package_curiosity_pack")

    composer.add_section("action_design",           ACTION_DESIGN,
                         priority=5, required=True,  source_pack="package_action_pack")

    composer.add_section("source_grounding", (
        f"SOURCE GROUNDING — MANDATORY\n"
        f"ALLOWED: explain, simplify, connect, derive from retrieved sources.\n"
        f"FORBIDDEN: invent facts, fabricate statistics or quotes, assert unsupported claims.\n"
        f"Every card MUST include at least one `evidence` block that cites the Source-ID "
        f"(e.g. '{_sid_prefix}{_batch_type}-1 reports ...').\n"
        f"primary_source = the article that most directly grounds the evidence block. "
        f"If no source supports a claim, omit the claim."
    ),                   priority=1, required=True,  source_pack="")

    if is_batch:
        # Writer schema — cards only (no package_headline / learning_thread / action_item).
        # Package-level metadata is stubbed in merge_batch_results() and replaced in 9.3.4D.
        _is_curiosity_batch = _batch_type == "CURIOSITY"
        _primary_array = "curiosity_insights" if _is_curiosity_batch else "insights"
        _empty_array   = "insights" if _is_curiosity_batch else "curiosity_insights"
        _card_id_ex    = "curiosity-1" if _is_curiosity_batch else "card-1"
        _ctype_ex      = "curiosity"   if _is_curiosity_batch else "news"
        composer.add_section("output_schema", (
            f"SOURCE PROVENANCE RULES — MANDATORY:\n"
            f"Every card MUST have a primary_source: the ONE article that most directly supports it.\n"
            f"supporting_sources: additional retrieved articles that inform the card (0 or more).\n"
            f"UNIQUENESS: each primary_source URL used as primary_source for AT MOST ONE card.\n"
            f"  If a URL is already used as primary_source in an earlier card, use it as supporting_source only.\n"
            f"ALL URLs must be taken verbatim from AVAILABLE ARTICLES above — never invent, guess, or fabricate.\n"
            f"NEVER use example.com, placeholder URLs, or any URL not present in the AVAILABLE ARTICLES sections.\n\n"
            f"BLOCK SELECTION PROCESS — run this reasoning for EACH card before choosing blocks:\n"
            f"  1. SOURCE TYPE: Check the `Source type:` field in AVAILABLE ARTICLES for the primary source.\n"
            f"  2. ARTICLE OBJECTIVE: What must the reader understand or be able to do after reading this card?\n"
            f"  3. USER CONTEXT: Given this learner's intent profile and knowledge state, what structure serves them best?\n"
            f"SOURCE TYPE → BLOCK PATTERNS (heuristics, not rules — override when content demands it):\n"
            f"  government / regulatory  → timeline, evidence, implication, warning\n"
            f"  research_paper           → explanation, evidence, mechanism, counterpoint\n"
            f"  industry_report          → comparison, evidence, insight, implication\n"
            f"  market_analysis          → key_takeaway, comparison, evidence, implication\n"
            f"  news                     → key_takeaway, evidence, counterpoint, implication\n"
            f"  educational              → explanation, example, evidence, step_list or mechanism\n"
            f"  company_blog             → example or step_list, evidence, insight, warning\n"
            f"  (unknown / mixed)        → infer from content: methodology → step_list; concept → mechanism; event → implication\n\n"
            f"AVAILABLE BLOCK TYPES:\n"
            f"  key_takeaway  — single most important insight (1–2 sentences)\n"
            f"  evidence      — SOURCE BASIS: cite Source-IDs (e.g. '{_sid_prefix}{_batch_type}-N reports ...'); REQUIRED in every card\n"
            f"  explanation   — explain, simplify, connect, or derive from source evidence (3–4 sentences max)\n"
            f"  mechanism     — hidden causal chain or invisible incentive (max 50 words)\n"
            f"  example       — concrete real-world instance that illustrates the concept (2–3 sentences)\n"
            f"  timeline      — sequential events or progression; one item per line using \\n\n"
            f"  comparison    — contrast between two approaches or outcomes; one item per line using \\n\n"
            f"  step_list     — ordered procedure; one step per line using \\n, strip prose intro\n"
            f"  warning       — risk, caveat, or common misunderstanding (2–3 sentences)\n"
            f"  counterpoint  — opposing view or tension worth knowing (1–2 sentences)\n"
            f"  insight       — non-obvious implication that rewards careful thinking (1–2 sentences)\n"
            f"  implication   — forward-looking consequence for the learner's domain (1–2 sentences)\n"
            f"  reflection    — metacognitive closing observation (1–2 sentences)\n"
            f"  headline      — sub-heading to organise longer cards (title case, ≤6 words)\n"
            f"  image         — a real image URL, ONLY when the source explicitly lists one under "
            f"'Images available for <Source-ID>' in AVAILABLE ARTICLES; content = the exact URL, verbatim; "
            f"NEVER invent, guess, or reuse a URL from a different source\n\n"
            f"SOURCE_ID (optional, per block): any block may add \"source_id\": \"<Source-ID>\" "
            f"(e.g. '{_sid_prefix}{_batch_type}-1') when a specific fact, number, or quote in that block "
            f"is clearly attributable to ONE source. Omit it when the block synthesises across sources or "
            f"isn't a specific attributable fact. Most useful on key_takeaway, evidence, mechanism, example, "
            f"timeline, and comparison blocks.\n\n"
            f"ACTION_ITEM (optional, per card, rarely needed): the package-level action_item is synthesized "
            f"separately after all cards are written — cards normally don't need their own. If a card does "
            f"include an \"action_item\" key, its value MUST be a plain string, never an object.\n\n"
            f"BLOCK RULES:\n"
            f"  • Every card must have exactly one `evidence` block (with Source-ID citation).\n"
            f"  • Choose 4–5 blocks per card — prefer more short blocks over fewer long blocks.\n"
            f"  • Every block: max 4–5 rendered lines. If content exceeds this, split into two blocks.\n"
            f"  • Every card must contain at least one of: example, comparison, timeline, warning, step_list.\n"
            f"  • Block selection must vary across cards — let source nature drive it, not card label.\n\n"
            f"Respond ONLY with valid JSON — no markdown, no prose outside the JSON object:\n\n"
            f"{{\n"
            f"  \"batch_id\": {batch_plan.batch_id},\n"
            f"  \"{_primary_array}\": [\n"
            f"    {{\n"
            f"      \"id\": \"{_card_id_ex}\",\n"
            f"      \"content_type\": \"{_ctype_ex}\",\n"
            f"      \"narrative_frame\": \"INVESTIGATIVE\",\n"
            f"      \"category\": \"specific topic area within {context.project_name}\",\n"
            f"      \"title\": \"Specific, compelling title ≤ 12 words — never generic\",\n"
            f"      \"summary\": \"HOOK: 1–2 sentences — tension or signal that makes this worth reading.\",\n"
            f"      \"blocks\": [\n"
            f"        {{\"type\": \"evidence\",    \"content\": \"SOURCE BASIS — {_sid_prefix}{_batch_type}-N reports ...\", \"source_id\": \"{_sid_prefix}{_batch_type}-N\"}},\n"
            f"        {{\"type\": \"implication\", \"content\": \"What this means for the learner's domain.\"}}\n"
            f"      ],\n"
            f"      \"primary_source\": {{\"title\": \"exact title from AVAILABLE ARTICLES\", \"url\": \"exact URL — never invent\"}},\n"
            f"      \"supporting_sources\": [{{\"title\": \"exact title\", \"url\": \"exact URL from AVAILABLE ARTICLES\"}}],\n"
            f"      \"difficulty\": \"{context.difficulty}\",\n"
            f"      \"estimated_read_time\": \"X min\"\n"
            f"    }}\n"
            f"  ],\n"
            f"  \"{_empty_array}\": []\n"
            f"}}"
        ),               priority=1, required=True, source_pack="")
    else:
        composer.add_section("output_schema", (
            f"SOURCE PROVENANCE RULES — MANDATORY:\n"
            f"Every card MUST have a primary_source: the ONE article that most directly supports it.\n"
            f"supporting_sources: additional retrieved articles that inform the card (0 or more).\n"
            f"UNIQUENESS: each primary_source URL must be used as primary_source for AT MOST ONE card.\n"
            f"  If a URL is already used as primary_source in an earlier card, use it as supporting_source only.\n"
            f"ALL URLs must be taken verbatim from AVAILABLE ARTICLES above — never invent, guess, or fabricate.\n"
            f"NEVER use example.com, placeholder URLs, or any URL not present in the AVAILABLE ARTICLES sections.\n\n"
            f"Respond ONLY with valid JSON — no markdown, no prose outside the JSON object:\n\n"
            f"{{\n"
            f"  \"package_headline\": \"Compelling, specific 10-word headline capturing today's editorial theme\",\n"
            f"  \"content_mix\": \"e.g. '2 news · 3 educational + 2 curiosity picks'\",\n"
            f"  \"learning_thread\": \"1–2 sentences: NAME the specific prior insight or mechanism being built on "
            f"(not generic 'continues from Day X') — then state where today's content advances it and what question it leaves open next.\",\n"
            f"  \"action_item\": \"INVESTIGATIVE MISSION: one specific, startable-in-10-minutes action using one of the 8 types above "
            f"— references a named mechanism, company, or claim from today's cards "
            f"— ends with a concrete thing to find, verify, compare, or build.\",\n"
            f"BLOCK SELECTION PROCESS — run this reasoning for EACH card before choosing blocks:\n"
            f"  1. SOURCE TYPE: Check the `Source type:` field in AVAILABLE ARTICLES for the primary source.\n"
            f"     Use it as the first signal for block selection.\n"
            f"  2. ARTICLE OBJECTIVE: What must the reader understand or be able to do after reading this specific card?\n"
            f"  3. USER CONTEXT: Given this learner's intent profile and knowledge state, what structure serves them best?\n"
            f"SOURCE TYPE → BLOCK PATTERNS (heuristics, not rules — override when content demands it):\n"
            f"  government / regulatory  → timeline (what changed and when), evidence, implication, warning\n"
            f"  research_paper           → explanation (build the model), evidence, mechanism, counterpoint\n"
            f"  industry_report          → comparison (sector vs sector), evidence, insight, implication\n"
            f"  market_analysis          → key_takeaway, comparison, evidence, implication\n"
            f"  news                     → key_takeaway, evidence, counterpoint, implication\n"
            f"  educational              → explanation, example, evidence, step_list or mechanism\n"
            f"  company_blog             → example or step_list, evidence, insight, warning\n"
            f"  (unknown / mixed)        → infer from content: methodology → step_list; concept → mechanism; event → implication\n\n"
            f"AVAILABLE BLOCK TYPES:\n"
            f"  key_takeaway  — single most important insight (1–2 sentences)\n"
            f"  evidence      — SOURCE BASIS: cite Source-IDs (e.g. '{_sid_prefix}CORE-1 reports ...'); REQUIRED in every card\n"
            f"  explanation   — explain, simplify, connect, or derive from source evidence (3–4 sentences max; split into two blocks if content is dense)\n"
            f"  mechanism     — hidden causal chain or invisible incentive (max 50 words — tight, no padding)\n"
            f"  example       — concrete real-world instance that illustrates the concept (2–3 sentences)\n"
            f"  timeline      — sequential events or progression; one item per line using \\n\n"
            f"  comparison    — contrast between two approaches or outcomes; one item per line using \\n\n"
            f"  step_list     — ordered procedure; one step per line using \\n, strip prose intro\n"
            f"  warning       — risk, caveat, or common misunderstanding (2–3 sentences)\n"
            f"  counterpoint  — opposing view or tension worth knowing (1–2 sentences)\n"
            f"  insight       — non-obvious implication that rewards careful thinking (1–2 sentences)\n"
            f"  implication   — forward-looking consequence for the learner's domain (1–2 sentences)\n"
            f"  reflection    — metacognitive closing observation (1–2 sentences)\n"
            f"  headline      — sub-heading to organise longer cards (title case, ≤6 words)\n\n"
            f"ACTION_ITEM (optional, per card, rarely needed): the package-level action_item above is the "
            f"real one — cards normally don't need their own. If a card does include an \"action_item\" key, "
            f"its value MUST be a plain string, never an object.\n\n"
            f"BLOCK RULES:\n"
            f"  • Every card must have exactly one `evidence` block (with Source-ID citation).\n"
            f"  • Choose 4–5 blocks per card — prefer more short blocks over fewer long blocks.\n"
            f"  • Every block: max 4–5 rendered lines. If content exceeds this, split into two blocks.\n"
            f"  • Every card must contain at least one of: example, comparison, timeline, warning, step_list.\n"
            f"  • Block selection must vary across cards — let source nature drive it, not card label.\n\n"
            f"  \"insights\": [\n"
            f"    {{\n"
            f"      \"id\": \"card-1\",\n"
            f"      \"content_type\": \"news\",\n"
            f"      \"narrative_frame\": \"INVESTIGATIVE\",\n"
            f"      \"category\": \"specific topic area within {context.project_name}\",\n"
            f"      \"title\": \"Specific, compelling title ≤ 12 words — never generic\",\n"
            f"      \"summary\": \"HOOK: 1–2 sentences — tension or signal that makes this worth reading. No definition openings.\",\n"
            f"      \"blocks\": [\n"
            f"        {{\"type\": \"timeline\",    \"content\": \"Concrete sequence: what changed and when.\"}},\n"
            f"        {{\"type\": \"evidence\",    \"content\": \"SOURCE BASIS — {_sid_prefix}CORE-N reports ...\"}},\n"
            f"        {{\"type\": \"implication\", \"content\": \"What this means for the learner's domain.\"}}\n"
            f"      ],\n"
            f"      \"primary_source\": {{\"title\": \"exact title from AVAILABLE ARTICLES\", \"url\": \"exact URL — never invent\"}},\n"
            f"      \"supporting_sources\": [{{\"title\": \"exact title\", \"url\": \"exact URL from AVAILABLE ARTICLES\"}}],\n"
            f"      \"difficulty\": \"{context.difficulty}\",\n"
            f"      \"estimated_read_time\": \"X min\"\n"
            f"    }}\n"
            f"  ],\n"
            f"  \"curiosity_insights\": [\n"
            f"    {{\n"
            f"      \"id\": \"curiosity-1\",\n"
            f"      \"content_type\": \"curiosity\",\n"
            f"      \"category\": \"e.g. 'Hidden Mechanism' or 'Origin Myth Shattered'\",\n"
            f"      \"title\": \"Story-driven, intriguing title ≤ 12 words\",\n"
            f"      \"summary\": \"Hook: 2–3 sentences starting with what's strange or counterintuitive — make the reader say 'wait, really?'\",\n"
            f"      \"blocks\": [\n"
            f"        {{\"type\": \"insight\",      \"content\": \"The non-obvious thing the source reveals.\"}},\n"
            f"        {{\"type\": \"evidence\",     \"content\": \"SOURCE BASIS — {_sid_prefix}CORE-N reports ...\"}},\n"
            f"        {{\"type\": \"counterpoint\", \"content\": \"The tension that makes this surprising.\"}},\n"
            f"        {{\"type\": \"reflection\",   \"content\": \"What this changes about how to think about the topic.\"}}\n"
            f"      ],\n"
            f"      \"primary_source\": {{\"title\": \"exact title from AVAILABLE ARTICLES\", \"url\": \"exact URL — never invent\"}},\n"
            f"      \"supporting_sources\": [],\n"
            f"      \"difficulty\": \"intermediate\",\n"
            f"      \"estimated_read_time\": \"3 min\"\n"
            f"    }}\n"
            f"  ]\n"
            f"}}\nRepeat curiosity card structure for every curiosity article."
        ),               priority=1, required=True,  source_pack="")

    _log_prompt_breakdown(
        composer,
        PromptMode.BATCH if is_batch else PromptMode.PACKAGE,
        batch_plan.batch_id if is_batch else None,
    )
    return composer


# ── Backward-compatible package wrapper ──────────────────────────────────────

def make_daily_package_composer(
    project_name: str,
    keywords: list[str],
    difficulty: str,
    day_number: int,
    display_label: str,
    core_articles: list[dict],
    curiosity_articles: list[dict],
    daily_core_article_count: int = 4,
    curiosity_directives: str | None = None,
    intelligence_context: str | None = None,
    quality_feedback: str | None = None,
    intent_profile: dict | None = None,
    knowledge_state: dict | None = None,
    article_plan_block: str | None = None,
    article_budget_tokens: int = 0,
    core_article_text: str | None = None,
    curiosity_article_text: str | None = None,
) -> PromptComposer:
    """
    Backward-compatible entry point — call signature unchanged from pre-9.3.4B.

    Wraps build_batch_prompt() in PACKAGE mode (batch_plan=None).
    Handles optional article text: when core_article_text is not supplied,
    formats core_articles / curiosity_articles internally using ArticleCompressor.
    Callers that pre-format (e.g. project_service after 9.3.3B budget calibration)
    pass core_article_text / curiosity_article_text directly.
    """
    if core_article_text is None:
        _total         = article_budget_tokens or 3000
        _core_budget   = int(_total * 0.70)
        _curio_budget  = _total - _core_budget
        from .article_compressor import ArticleCompressor as _AC
        _ac = _AC()
        core_article_text,     _ = _ac.format_intel_batch(core_articles,      "CORE",      _core_budget)
        curiosity_article_text, _ = _ac.format_intel_batch(curiosity_articles, "CURIOSITY", _curio_budget)

    ctx = PromptContext(
        project_name             = project_name,
        keywords                 = keywords,
        difficulty               = difficulty,
        day_number               = day_number,
        display_label            = display_label,
        daily_core_article_count = daily_core_article_count,
        intent_profile           = intent_profile,
        knowledge_state          = knowledge_state,
        curiosity_directives     = curiosity_directives,
        intelligence_context     = intelligence_context,
        quality_feedback         = quality_feedback,
        article_plan_block       = article_plan_block,
        article_budget_tokens    = article_budget_tokens,
    )

    return build_batch_prompt(
        ctx,
        batch_plan             = None,
        core_article_text      = core_article_text or "",
        curiosity_article_text = curiosity_article_text or "",
    )
