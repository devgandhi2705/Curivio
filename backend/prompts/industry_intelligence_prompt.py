from .prompt_composer import PromptComposer
from .instruction_packs.core_writing_pack import STRICT_URL_RULE as _STRICT_URL_RULE

_PERSONA = """\
You are a senior industry intelligence analyst producing a structured brief for a
senior professional who needs decision-ready insights, not summaries of headlines."""

_WRITING_RULES_INTRO = """\
Writing rules (enforce strictly):
- Name mechanisms and causality — not just events ("X caused Y because Z" not "X happened")
- Every sentence must move the reader forward; cut filler, hedges, and restatements
- Ground all claims in the provided articles; do not speculate beyond them
- Business impact must be concrete — name who is affected and how
- Opportunities must be specific — name the gap, the enabler, and the window"""

_SCHEMA = """\
{
  "industry": "INDUSTRY_PLACEHOLDER",
  "trend_summary": "2–3 sentences: the single most important structural shift underway, why it is happening now, and what it resets for practitioners in this industry.",
  "market_developments": [
    {
      "title": "Specific development headline — names mechanism not topic",
      "insight": "2 sentences: what changed and the causal mechanism driving it",
      "business_impact": "1 sentence: who is affected, how, and by how much if quantifiable",
      "sources": ["url from articles only, or empty array"]
    },
    {
      "title": "Specific development headline",
      "insight": "2 sentences",
      "business_impact": "1 sentence",
      "sources": []
    },
    {
      "title": "Specific development headline",
      "insight": "2 sentences",
      "business_impact": "1 sentence",
      "sources": []
    }
  ],
  "emerging_opportunities": [
    {
      "opportunity": "Specific opportunity name — names the gap and the enabler",
      "rationale": "2 sentences: why this window exists now and what makes it actionable",
      "time_horizon": "near-term"
    },
    {
      "opportunity": "Specific opportunity name",
      "rationale": "2 sentences",
      "time_horizon": "mid-term"
    },
    {
      "opportunity": "Specific opportunity name",
      "rationale": "2 sentences",
      "time_horizon": "long-term"
    }
  ],
  "key_signals": [
    "One sharp sentence naming a specific, observable signal — not a trend label",
    "One sharp sentence naming signal 2",
    "One sharp sentence naming signal 3"
  ],
  "action_items": [
    "Concrete action — names an exact tool, report, metric, or decision to make today",
    "Concrete action 2",
    "Concrete action 3"
  ]
}"""

_HARD_RULES = """\
Hard rules:
- market_developments must contain exactly 3 items
- emerging_opportunities must contain exactly 3 items with time_horizon values near-term, mid-term, long-term (one each)
- key_signals must contain exactly 3 strings
- action_items must contain exactly 3 strings
- sources arrays must only contain URLs from the provided articles list
- Do not output any text outside the JSON object"""


def build_industry_intelligence_prompt(
    industry_display_name: str,
    business_lens: str,
    focus_areas: str,
    article_count: int,
    articles: str,
) -> str:
    schema = _SCHEMA.replace("INDUSTRY_PLACEHOLDER", industry_display_name)
    composer = PromptComposer()
    composer.add_section("persona",         _PERSONA,
                         priority=1, required=True,  source_pack="")
    composer.add_section("writing_rules",   f"{_WRITING_RULES_INTRO}\n- {_STRICT_URL_RULE}",
                         priority=2, required=True,  source_pack="core_writing_pack")
    composer.add_section("context_input",   (
        f"---\n"
        f"Industry: {industry_display_name}\n"
        f"Business lens: {business_lens}\n"
        f"Focus areas: {focus_areas}"
    ),                   priority=1, required=True,  source_pack="dynamic")
    composer.add_section("articles",        f"---\nArticles ({article_count} sources):\n{articles}",
                         priority=1, required=True,  source_pack="dynamic")
    composer.add_section("output_preamble", (
        "---\nGenerate EXACTLY the JSON below. "
        "No markdown, no code fences, no text outside the JSON."
    ),                   priority=2, required=True,  source_pack="")
    composer.add_section("schema",          schema,
                         priority=1, required=True,  source_pack="")
    composer.add_section("hard_rules",      _HARD_RULES,
                         priority=3, required=True,  source_pack="")
    return composer.build()
