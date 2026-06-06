from .prompt_composer import PromptComposer

_PERSONAS = """\
You are three specialists working in parallel on the same investigation:

  RESEARCH ANALYST       — extracts verifiable facts, evidence quality, and knowledge gaps
  STRATEGY CONSULTANT    — identifies strategic implications, tradeoffs, and concrete decisions
  TECHNICAL INVESTIGATOR — explains mechanisms, causal chains, and open debates

Your task: produce a single, unified deep-dive analysis of the topic below.
All three perspectives must inform the output — you are not writing from one viewpoint alone."""

_OUTPUT_PREAMBLE = """\
---
Generate a structured deep-dive analysis in strict JSON.
Output ONLY the JSON object — no markdown, no code fences, no explanation."""

_SCHEMA = """\
{
  "research_summary": "3–4 sentences synthesising the single most important finding, \
why it matters NOW, and what a practitioner must understand. Open with the finding, \
not the topic background. Name mechanisms, not field descriptions. \
Synthesise ACROSS sources — not just the best article.",

  "key_findings": [
    "Finding 1 — Research Analyst: one specific, evidence-backed fact with named mechanism or actor",
    "Finding 2",
    "Finding 3",
    "Finding 4"
  ],

  "viewpoint_comparison": [
    {
      "perspective": "Label for this viewpoint (e.g. 'Academic / Research', 'Industry Practitioners')",
      "stance":      "One sentence: what this perspective argues or emphasises",
      "evidence":    "One sentence: what evidence or signals support this stance",
      "sources":     ["url from articles only, or empty array"]
    },
    {
      "perspective": "Label for second viewpoint",
      "stance":      "One sentence",
      "evidence":    "One sentence",
      "sources":     []
    }
  ],

  "trends_identified": [
    "Trend 1 — specific, named, grounded in at least one source. Name the mechanism driving it.",
    "Trend 2",
    "Trend 3"
  ],

  "tradeoffs": [
    {
      "dimension":  "What is being traded off (e.g. 'Cost vs Resilience', 'Speed vs Accuracy')",
      "option_a":   "One approach or choice — name it specifically",
      "option_b":   "The competing approach — name it specifically",
      "context":    "One sentence: when option A is preferable and the causal reason why",
      "verdict":    "One sentence: what the evidence suggests practitioners should choose and why"
    },
    {
      "dimension":  "Second tradeoff dimension",
      "option_a":   "Option A",
      "option_b":   "Option B",
      "context":    "One sentence with causal reasoning",
      "verdict":    "One sentence"
    }
  ],

  "strategic_implications": [
    "Implication 1 — Strategy Consultant: one CONCRETE strategic decision or shift this creates. Name who must act.",
    "Implication 2",
    "Implication 3"
  ],

  "contrarian_view": "One to two sentences: what is the conventional framing of this topic getting \
wrong or systematically underweighting? What would a sharp contrarian argue?",

  "what_shifts_next": "One to two sentences: what specific force, event, or development will change \
the current equilibrium? Name the mechanism and approximate timeframe.",

  "open_questions": [
    "Question 1 — Technical Investigator: one specific genuinely unresolved question or active expert debate",
    "Question 2",
    "Question 3"
  ],

  "confidence_level": "high | medium | low — based on source diversity and agreement. \
high = 3+ sources agree on mechanism; medium = mixed signals; low = single source or conflicting",

  "related_concepts":       ["concept 1", "concept 2", "concept 3", "concept 4", "concept 5"],
  "implementation_ideas":   ["idea 1", "idea 2", "idea 3", "idea 4"],
  "practical_applications": ["application 1", "application 2", "application 3"],
  "advanced_follow_ups":    ["topic 1", "topic 2", "topic 3", "topic 4"]
}"""

_WRITING_RULES = """\
Writing rules (enforce strictly):
- Be specific — name frameworks, protocols, algorithms, papers, organisations, and tools.
  Generic statements ("many companies do this") are not acceptable.
- Name mechanisms and causality — not "X is important" but "X works because Y, which causes Z"
- Every tradeoff must name a concrete dimension and two real, specific alternatives — never vague "pros and cons"
- Viewpoints must reflect actual differences in the source material — do not invent or extrapolate
- strategic_implications must name WHO must act and WHAT specifically they should do
- open_questions must be genuinely unresolved in current literature — not just gaps in your sources
- contrarian_view must identify what the mainstream analysis systematically underweights or gets wrong
- what_shifts_next must name a specific force or mechanism, not a vague "things may change"
- All urls in sources arrays must come from the provided articles list
- Do not output any text outside the JSON object"""

_SYNTHESIS_RULES = """\
Synthesis quality rules (enforce strictly):
- research_summary must synthesise ACROSS sources — not just summarise the best article
- Identify where sources AGREE (establish foundation), where they CONTRADICT (surface it explicitly),
  and what is UNDERWEIGHTED across all coverage
- key_findings must be evidence-backed specifics — not observations that apply to any topic in the field
- Increase insight density per sentence — if a sentence doesn't add something new, cut it
- The output should feel like a genuine analyst memo, not a structured literature review"""


def build_deep_research_prompt(
    topic: str,
    source_count: int,
    source_analysis: str,
    viewpoint_analysis: str,
    articles: str,
    shared_context: str | None = None,
) -> str:
    composer = PromptComposer()
    composer.add_section("personas",        _PERSONAS,
                         priority=1, required=True,  source_pack="")
    composer.add_section("topic_input",     f"TOPIC: {topic}",
                         priority=1, required=True,  source_pack="dynamic")
    # Phase 4.6: inject project learning context at priority=1 so the research
    # builds on what the user already knows rather than starting from scratch.
    if shared_context:
        composer.add_section("learner_context", shared_context,
                             priority=1, required=False, source_pack="dynamic")
    composer.add_section("source_analysis", (
        f"---\n"
        f"MULTI-SOURCE ANALYSIS ({source_count} articles pre-processed):\n"
        f"{source_analysis}"
    ),                   priority=2, required=True,  source_pack="dynamic")
    composer.add_section("viewpoints",      (
        f"---\n"
        f"MULTI-ANGLE VIEWPOINT REPORT:\n"
        f"{viewpoint_analysis}"
    ),                   priority=2, required=True,  source_pack="dynamic")
    composer.add_section("articles",        (
        f"---\n"
        f"BACKGROUND ARTICLES:\n"
        f"{articles}"
    ),                   priority=1, required=True,  source_pack="dynamic")
    composer.add_section("output_preamble", _OUTPUT_PREAMBLE,
                         priority=2, required=True,  source_pack="")
    composer.add_section("schema",          _SCHEMA,
                         priority=1, required=True,  source_pack="")
    composer.add_section("writing_rules",   _WRITING_RULES,
                         priority=3, required=True,  source_pack="")
    composer.add_section("synthesis_rules", _SYNTHESIS_RULES,
                         priority=3, required=True,  source_pack="")
    return composer.build()
