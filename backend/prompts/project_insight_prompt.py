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
"""

from .prompt_composer import PromptComposer
from .instruction_packs.core_writing_pack   import WRITING_STYLE_STANDARDS, BANNED_PHRASES
from .instruction_packs.core_reasoning_pack import SOURCE_SIGNAL_EXTRACTION, REAL_WORLD_TENSION
from .instruction_packs.package_editorial_pack import (
    EDITORIAL_PHILOSOPHY, ACCELERATION_PHILOSOPHY, HOOK_FIRST_RULES, WHY_IT_WORKS_RULES,
)
from .instruction_packs.package_narrative_pack import (
    NARRATIVE_FRAMES, EMOTIONAL_TONE_PALETTE, TITLE_STYLE_LIBRARY,
    EDITORIAL_ROLES, PACKAGE_COMPOSITION, ARTICLE_MIX, SECTION_1_INSTRUCTIONS,
)
from .instruction_packs.package_curiosity_pack import (
    CURIOSITY_TARGET, TENSION_SCORING, TENSION_CATEGORIES,
    CURIOSITY_TITLE_RULES, CURIOSITY_SUMMARY_RULES, CURIOSITY_CARD_RULES,
)
from .instruction_packs.package_action_pack import ACTION_DESIGN


def make_daily_package_prompt(
    project_name: str,
    keywords: list[str],
    difficulty: str,
    focus_areas: list[str],
    day_number: int,
    display_label: str,
    prev_display_label: str | None,
    previous_packages: list[dict],
    core_articles: list[dict],
    curiosity_articles: list[dict],
    explored_concepts: list[str],
    suggested_next_topics: list[str],
    daily_core_article_count: int = 4,
    learning_memory: dict | None = None,
    memory_references: dict | None = None,
    curiosity_directives: str | None = None,
    intelligence_context: str | None = None,
    quality_feedback: str | None = None,
) -> str:
    kw_str    = ", ".join(keywords) if keywords else project_name
    focus_str = ", ".join(focus_areas) if focus_areas else "general developments"

    count = max(2, min(10, int(daily_core_article_count)))
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

    # Learning history + recently used titles for pattern avoidance
    if previous_packages:
        history_lines = []
        all_recent_titles: list[str] = []
        for p in previous_packages:
            cats = ", ".join(p.get("categories", [])) or "general"
            history_lines.append(f"  {p['day']}: {p['headline']}  [covered: {cats}]")
            all_recent_titles.extend(p.get("titles", []))
        history_str = "\n".join(history_lines)
    else:
        history_str = f"  (none — this is {display_label}, introduce accessible but intellectually sharp foundations)"
        all_recent_titles = []

    if all_recent_titles:
        recent_titles_str = "\n".join(f"  — {t}" for t in all_recent_titles[-12:])
    else:
        recent_titles_str = "  (none — first package)"

    # Explored concepts
    if explored_concepts:
        ec_lines = "\n".join(f"  • {c}" for c in explored_concepts[-20:])
        ec_block = (
            "Concepts already explored — REINFORCE WITH INCREASING DEPTH, never repeat at same level:\n"
            + ec_lines
        )
    else:
        ec_block = "Concepts explored: none yet — begin with accessible, intellectually engaging foundations."

    # Suggested next topics
    nt_str = ", ".join(suggested_next_topics[:4]) if suggested_next_topics else "follow natural curriculum progression"

    # Beginner calibration section (only injected when difficulty == "beginner")
    if difficulty == "beginner":
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
  "Could a smart 18-year-old who has never studied {project_name} understand the first sentence?"
  If NO → rewrite it. Concrete first. Abstract second. Always."""
    else:
        beginner_section_str = ""

    # Learning memory section (progression stage + coverage avoidance)
    # Budget-capped via MemoryCompressor: mature projects auto-compress to L1/L2
    # rather than growing the prompt linearly with project age.
    memory_section_str = ""
    if learning_memory:
        try:
            from .memory_compressor import MemoryCompressor
            memory_section_str, _ = MemoryCompressor().format_within_budget(
                learning_memory, budget_tokens=400
            )
        except Exception:
            pass

    # Inter-article continuity section (prior insights + unresolved threads)
    continuity_str = ""
    if memory_references:
        prior_insights_list = memory_references.get("priorInsights") or []
        unresolved_list     = memory_references.get("unresolvedQuestions") or []
        if prior_insights_list or unresolved_list:
            lines: list[str] = []
            lines.append("══════════════════════════════════════")
            lines.append("INTER-ARTICLE CONTINUITY — MANDATORY")
            lines.append("══════════════════════════════════════")
            lines.append("The reader has been learning across multiple sessions. They carry prior insights.")
            lines.append("The feed must feel CUMULATIVE — not a fresh slate each day.")
            lines.append("")
            lines.append("AT LEAST 1 core card per package MUST open with or include a callback to a prior insight.")
            lines.append("Use one of these callback phrase forms (verbatim or close variant):")
            lines.append('  "As we established in {Day}, [prior mechanism]..."')
            lines.append('  "Building on {Day}\'s insight about [topic]: here is the next layer."')
            lines.append('  "{Day} showed that [X]. Today\'s pattern confirms / contradicts that:"')
            lines.append('  "Recall [title] from {Day}? This is what happens next:"')
            lines.append('  "The [mechanism from {Day}] now explains why [today\'s development]:"')
            lines.append("")
            lines.append("WHAT MAKES A GOOD CALLBACK:")
            lines.append("  GOOD: \"Day 2 established FDA approval as a global trust certificate.")
            lines.append("         Today's pattern shows what happens when that certificate is revoked mid-export.\"")
            lines.append("  BAD:  \"Building on our previous discussion...\"  (too vague — name the mechanism)")
            lines.append("  BAD:  \"As mentioned before...\"  (never say this — be specific)")
            lines.append("")
            if prior_insights_list:
                lines.append("PRIOR INSIGHTS AVAILABLE FOR CALLBACKS:")
                for pi in prior_insights_list:
                    lines.append(f'  [{pi["day"]}] "{pi["title"]}"')
                    if pi.get("insight"):
                        lines.append(f'        Mechanism: {pi["insight"]}')
            if unresolved_list:
                lines.append("")
                lines.append("OPEN THREADS (curiosity cards that surfaced questions — deepen or resolve if relevant today):")
                for uq in unresolved_list:
                    lines.append(f'  [{uq["day"]}] {uq["question"]}')
            lines.append("")
            lines.append("CONTINUITY MANDATE:")
            lines.append("  • At least 1 card summary or educational_explanation must contain a named callback")
            lines.append("    to a prior session insight — using the card's title or mechanism, not generic phrasing.")
            lines.append("  • learning_thread MUST reference specific prior content by concept name or card title —")
            lines.append("    not vague 'continues the journey' language.")
            lines.append("  • If an open thread directly connects to today's content, reference it by title.")
            continuity_str = "\n".join(lines)

    def fmt_articles(articles: list[dict], tag: str) -> str:
        if not articles:
            return f"({tag}: none retrieved — synthesise from domain knowledge)"
        parts = []
        for i, a in enumerate(articles[:8], 1):
            parts.append(
                f"[{tag} {i}]\n"
                f"Title: {a.get('title', '').strip()}\n"
                f"URL:   {a.get('url', '')}\n"
                f"Content: {(a.get('content') or '')[:700].strip()}"
            )
        return "\n\n".join(parts)

    core_str      = fmt_articles(core_articles,      "CORE")
    curiosity_str = fmt_articles(curiosity_articles, "CURIOSITY")

    # Format templated pack sections with runtime values
    hook_section      = HOOK_FIRST_RULES.format(domain=project_name)
    pkg_composition   = PACKAGE_COMPOSITION.format(count=count)
    section1          = SECTION_1_INSTRUCTIONS.format(
                            count=count, project_name=project_name, difficulty=difficulty
                        )
    curiosity_rules   = CURIOSITY_CARD_RULES.format(project_name=project_name)

    # ── Assemble prompt via PromptComposer ────────────────────────────────────
    composer = PromptComposer()

    composer.add_section("intro", (
        f"You are the editorial intelligence behind Curivio — a premium daily learning briefing system.\n"
        f"Your role: surface the most important signals, hidden implications, and insight-rich ideas from the {project_name} domain.\n\n"
        f"You are NOT summarizing topics for a textbook.\n"
        f"You ARE curating intelligence the way a brilliant analyst friend would — with judgment, narrative, and editorial intentionality."
    ),                   priority=1, required=True,  source_pack="")

    composer.add_section("project_state", (
        f"══════════════════════════════════════\n"
        f"PROJECT STATE\n"
        f"══════════════════════════════════════\n"
        f"Project:       {project_name}\n"
        f"Keywords:      {kw_str}\n"
        f"Focus areas:   {focus_str}\n"
        f"Learner level: {difficulty}\n"
        f"Today:         {display_label}\n"
        f"Intensity:     {intensity_label} ({count} core articles) — {intensity_guidance}"
    ),                   priority=1, required=True,  source_pack="dynamic")

    composer.add_section("learning_trajectory", (
        f"══════════════════════════════════════\n"
        f"LEARNING TRAJECTORY\n"
        f"══════════════════════════════════════\n"
        f"{ec_block}\n\n"
        f"Suggested next topics (introduce 1–2 that fit naturally):\n"
        f"  {nt_str}\n\n"
        f"Recent learning history:\n"
        f"{history_str}\n\n"
        f"Recent card titles — DO NOT produce structurally similar titles or reuse these phrasings:\n"
        f"{recent_titles_str}"
    ),                   priority=1, required=True,  source_pack="dynamic")

    # Feed intelligence (Phase 4.5): what this feed is meant to teach.
    # Priority=1 so the LLM sees this before articles, editorial philosophy, etc.
    if intelligence_context:
        composer.add_section(
            "feed_intelligence",
            intelligence_context,
            priority=1, required=False, source_pack="dynamic",
        )

    # Quality feedback (Phase 4.7): issues from previous package evaluation.
    # Priority=1 — the LLM reads this before generating, treating it as mandatory corrections.
    if quality_feedback:
        composer.add_section(
            "quality_feedback",
            quality_feedback,
            priority=1, required=False, source_pack="dynamic",
        )

    composer.add_section("memory_section",          memory_section_str,
                         priority=4, required=False, source_pack="dynamic")
    composer.add_section("continuity",              continuity_str,
                         priority=4, required=False, source_pack="dynamic")
    composer.add_section("editorial_philosophy",    EDITORIAL_PHILOSOPHY,
                         priority=2, required=True,  source_pack="package_editorial_pack")
    composer.add_section("beginner_calibration",    beginner_section_str,
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("acceleration_philosophy", ACCELERATION_PHILOSOPHY,
                         priority=3, required=True,  source_pack="package_editorial_pack")
    composer.add_section("narrative_frames",        NARRATIVE_FRAMES,
                         priority=4, required=True,  source_pack="package_narrative_pack")
    composer.add_section("emotional_tone",          EMOTIONAL_TONE_PALETTE,
                         priority=5, required=True,  source_pack="package_narrative_pack")
    composer.add_section("hook_rules",              hook_section,
                         priority=3, required=True,  source_pack="package_editorial_pack")
    composer.add_section("why_it_works",            WHY_IT_WORKS_RULES,
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

    composer.add_section("core_articles", (
        f"══════════════════════════════════════\n"
        f"AVAILABLE ARTICLES — CORE LEARNING\n"
        f"══════════════════════════════════════\n"
        f"{core_str}"
    ),                   priority=1, required=True,  source_pack="dynamic")

    composer.add_section("curiosity_articles", (
        f"══════════════════════════════════════\n"
        f"AVAILABLE ARTICLES — CURIOSITY ENGINE\n"
        f"══════════════════════════════════════\n"
        f"{curiosity_str}"
    ),                   priority=2, required=True,  source_pack="dynamic")

    composer.add_section("task_intro", (
        f"══════════════════════════════════════\n"
        f"YOUR TASK\n"
        f"══════════════════════════════════════\n\n"
        f"{EDITORIAL_ROLES}\n\n"
        f"{pkg_composition}\n\n"
        f"{ARTICLE_MIX}\n\n"
        f"Generate a JSON package with TWO sections:"
    ),                   priority=2, required=True,  source_pack="package_narrative_pack")

    composer.add_section("section1_instructions",   section1,
                         priority=2, required=True,  source_pack="package_narrative_pack")

    # Strategic curiosity directives (Phase 4.4): injected at priority=1 so they
    # prepend the generic tension scoring — the LLM sees them first and uses them
    # as the specific target for each card slot.
    if curiosity_directives:
        composer.add_section(
            "curiosity_strategy",
            curiosity_directives,
            priority=1, required=False, source_pack="dynamic",
        )

    composer.add_section("curiosity_instructions", (
        f"{CURIOSITY_TARGET}\n"
        f"{TENSION_SCORING}\n"
        f"{TENSION_CATEGORIES}\n"
        f"{CURIOSITY_TITLE_RULES}\n"
        f"{CURIOSITY_SUMMARY_RULES}\n"
        f"{curiosity_rules}"
    ),                   priority=2, required=True,  source_pack="package_curiosity_pack")

    composer.add_section("action_design",           ACTION_DESIGN,
                         priority=5, required=True,  source_pack="package_action_pack")

    composer.add_section("output_schema", (
        f"Respond ONLY with valid JSON — no markdown, no prose outside the JSON object:\n\n"
        f"{{\n"
        f"  \"package_headline\": \"Compelling, specific 10-word headline capturing today's editorial theme\",\n"
        f"  \"content_mix\": \"e.g. '2 news · 3 educational + 2 curiosity picks'\",\n"
        f"  \"learning_thread\": \"1–2 sentences: NAME the specific prior insight or mechanism being built on (not generic 'continues from Day X') — then state where today's content advances it and what question it leaves open next.\",\n"
        f"  \"action_item\": \"INVESTIGATIVE MISSION: one specific, startable-in-10-minutes action using one of the 8 types above — references a named mechanism, company, or claim from today's cards — ends with a concrete thing to find, verify, compare, or build.\",\n"
        f"  \"insights\": [\n"
        f"    {{\n"
        f"      \"id\": \"card-1\",\n"
        f"      \"content_type\": \"news\",\n"
        f"      \"narrative_frame\": \"INVESTIGATIVE\",\n"
        f"      \"category\": \"specific topic area within {project_name}\",\n"
        f"      \"title\": \"Specific, compelling title ≤ 12 words — never generic\",\n"
        f"      \"summary\": \"HOOK: 2–3 sentences — curiosity tension first, then the core insight. No definition openings.\",\n"
        f"      \"educational_explanation\": \"INSIGHT → EVIDENCE → IMPLICATION: 4–6 sentences assuming user knows the basics. Surface what's non-obvious, name a specific example, and state what it means for the domain.\",\n"
        f"      \"why_it_matters\": \"HIDDEN MECHANISM: 90–120 words. Expose the underlying causal chain, invisible incentive, or system behavior that produces this outcome. Must answer 'What hidden mechanism causes this?' NOT a topic summary. NOT a restatement of the article. See WHY THIS WORKS rules above.\",\n"
        f"      \"memory_callback\": \"ONLY if this card explicitly references a prior session insight — include the callback phrase used (1 sentence). Omit entirely if this card does not reference prior learning.\",\n"
        f"      \"source_links\": [{{\"title\": \"source title\", \"url\": \"https://...\"}}],\n"
        f"      \"difficulty\": \"{difficulty}\",\n"
        f"      \"estimated_read_time\": \"X min\"\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"curiosity_insights\": [\n"
        f"    {{\n"
        f"      \"id\": \"curiosity-1\",\n"
        f"      \"content_type\": \"curiosity\",\n"
        f"      \"category\": \"e.g. 'Hidden Mechanism' or 'Origin Myth Shattered' or 'The Failure That Explained Everything'\",\n"
        f"      \"title\": \"Story-driven, intriguing title ≤ 12 words — something you'd click at 11pm\",\n"
        f"      \"summary\": \"The hook: 2–3 sentences starting with what's strange, counterintuitive, or dramatic — not background. Make the reader say 'wait, really?'\",\n"
        f"      \"educational_explanation\": \"The payoff: 3–5 sentences revealing what this discovery exposes about {project_name}. Should feel like 'oh — that explains everything.'\",\n"
        f"      \"why_it_matters\": \"HIDDEN MECHANISM: 90–120 words. Expose what this discovery reveals about how {project_name} actually works — the structural behavior, hidden incentive, or causal chain the surface story conceals. NOT a restatement of the discovery.\",\n"
        f"      \"source_links\": [{{\"title\": \"...\", \"url\": \"...\"}}],\n"
        f"      \"difficulty\": \"intermediate\",\n"
        f"      \"estimated_read_time\": \"3 min\"\n"
        f"    }},\n"
        f"    {{\n"
        f"      \"id\": \"curiosity-2\",\n"
        f"      \"content_type\": \"curiosity\",\n"
        f"      \"category\": \"...\",\n"
        f"      \"title\": \"...\",\n"
        f"      \"summary\": \"...\",\n"
        f"      \"educational_explanation\": \"...\",\n"
        f"      \"why_it_matters\": \"HIDDEN MECHANISM: 90–120 words — see rules above.\",\n"
        f"      \"source_links\": [],\n"
        f"      \"difficulty\": \"intermediate\",\n"
        f"      \"estimated_read_time\": \"3 min\"\n"
        f"    }}\n"
        f"  ]\n"
        f"}}"
    ),                   priority=1, required=True,  source_pack="")

    return composer.build()
