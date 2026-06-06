from .prompt_composer import PromptComposer
from .instruction_packs.core_writing_pack import STRICT_URL_RULE as _STRICT_URL_RULE

_PERSONA = """\
You are three professionals simultaneously: an executive intelligence analyst who synthesizes industry signals,
a market researcher who tracks business and technical trends, and a learning architect who designs personalized
curricula. Your output is a personalized daily intelligence brief read by a senior technical professional."""

_WRITING_RULES_INTRO = """\
Writing rules (enforce strictly):
- Be direct and specific — zero filler ("In today's landscape...", "It's worth noting...")
- Name mechanisms, patterns, and trade-offs — not just topics
- Every sentence must move the reader forward; cut anything that doesn't
- Ground insights in the provided articles — do not speculate beyond them"""

_OUTPUT_PREAMBLE = (
    "Generate the intelligence brief as EXACTLY the JSON below. "
    "No markdown, no code fences, no explanation text."
)

_SCHEMA = """\
{
  "intelligence_brief": {
    "headline": "10–15 word headline naming the specific mechanism or shift — not a generic topic",
    "executive_summary": "2–3 sentences: what the most important development is, why it matters now, and what changes for engineers or builders. Synthesize across sources, not just the best article.",
    "key_signals": [
      "One sharp sentence naming signal 1 — specific, mechanism-level",
      "One sharp sentence naming signal 2",
      "One sharp sentence naming signal 3"
    ]
  },
  "sections": [
    {
      "type": "industry_news",
      "title": "Industry & Technology News",
      "items": [
        {
          "title": "Specific item headline",
          "insight": "2 sentences: what changed and the underlying technical mechanism",
          "why_it_matters": "1 sentence: practical impact for engineers or builders",
          "sources": ["url from articles only, or empty array"]
        },
        {
          "title": "Specific item headline",
          "insight": "2 sentences",
          "why_it_matters": "1 sentence",
          "sources": []
        }
      ]
    },
    {
      "type": "market_trends",
      "title": "Market Trends & Business Developments",
      "items": [
        {
          "title": "Specific item headline",
          "insight": "2 sentences: market dynamic or business development with mechanism",
          "why_it_matters": "1 sentence: what this means for builders or investors",
          "sources": []
        },
        {
          "title": "Specific item headline",
          "insight": "2 sentences",
          "why_it_matters": "1 sentence",
          "sources": []
        }
      ]
    },
    {
      "type": "technical_discoveries",
      "title": "Technical Discoveries & Research",
      "items": [
        {
          "title": "Specific research finding or technical breakthrough",
          "insight": "2 sentences: what was discovered and the mechanism that makes it work",
          "why_it_matters": "1 sentence: practical implication for practitioners",
          "sources": []
        },
        {
          "title": "Specific research finding",
          "insight": "2 sentences",
          "why_it_matters": "1 sentence",
          "sources": []
        }
      ]
    }
  ],
  "learning_track": [
    {
      "title": "Topic name — beginner level",
      "reason": "One sentence: what this unlocks and how it connects to what the user already knows",
      "difficulty": "beginner",
      "chat_connection": "One sentence connecting this to the user's recent chat topics, or null if no connection"
    },
    {
      "title": "Topic name — intermediate level",
      "reason": "One sentence",
      "difficulty": "intermediate",
      "chat_connection": null
    },
    {
      "title": "Topic name — intermediate level",
      "reason": "One sentence",
      "difficulty": "intermediate",
      "chat_connection": null
    },
    {
      "title": "Topic name — advanced level",
      "reason": "One sentence",
      "difficulty": "advanced",
      "chat_connection": null
    }
  ],
  "action_items": [
    "Concrete action 1 — specific, startable today, names an exact tool, paper, or implementation target",
    "Concrete action 2",
    "Concrete action 3"
  ],
  "industry_context": "One sentence: the industry lens applied to this brief and why it fits this user's profile"
}"""

_HARD_RULES = """\
Hard rules:
- sections must contain exactly 3 entries with types: industry_news, market_trends, technical_discoveries
- each section must have exactly 2 items
- learning_track must contain exactly 4 items (beginner, intermediate, intermediate, advanced)
- action_items must contain exactly 3 strings
- sources arrays must only contain URLs from the provided articles list
- Do not output any text outside the JSON object"""


def build_intelligence_prompt(
    intelligence_context: str,
    industry: str,
    source_count: int,
    source_analysis: str,
    articles: str,
    interests: str,
) -> str:
    composer = PromptComposer()
    composer.add_section("persona",          _PERSONA,
                         priority=1, required=True,  source_pack="")
    composer.add_section("writing_rules",    f"{_WRITING_RULES_INTRO}\n- {_STRICT_URL_RULE}",
                         priority=2, required=True,  source_pack="core_writing_pack")
    composer.add_section("user_profile",     f"---\nUser Intelligence Profile:\n{intelligence_context}",
                         priority=1, required=True,  source_pack="dynamic")
    composer.add_section("industry_focus",   f"---\nIndustry Focus: {industry}",
                         priority=1, required=True,  source_pack="dynamic")
    composer.add_section("source_analysis",  f"---\nSource Analysis ({source_count} sources):\n{source_analysis}",
                         priority=2, required=True,  source_pack="dynamic")
    composer.add_section("articles",         f"---\nArticles:\n{articles}",
                         priority=1, required=True,  source_pack="dynamic")
    composer.add_section("user_interests",   f"---\nUser Interests: {interests}",
                         priority=1, required=True,  source_pack="dynamic")
    composer.add_section("output_preamble",  f"---\n{_OUTPUT_PREAMBLE}",
                         priority=2, required=True,  source_pack="")
    composer.add_section("schema",           _SCHEMA,
                         priority=1, required=True,  source_pack="")
    composer.add_section("hard_rules",       _HARD_RULES,
                         priority=3, required=True,  source_pack="")
    return composer.build()
