from .prompt_composer import PromptComposer

_PERSONA = (
    "You are a curriculum designer and technical educator. Your task is to map the "
    "knowledge graph around a technical topic so a learner knows exactly what to study "
    "before, alongside, and after it."
)

_SCHEMA_INTRO = (
    "Generate a structured knowledge expansion in strict JSON. "
    "Output ONLY the JSON object — no markdown, no code fences, no explanation."
)

_SCHEMA = """\
{
  "prerequisites":       [string, ...],
  "related_topics":      [string, ...],
  "advanced_follow_ups": [string, ...],
  "learning_progression": [string, ...],
  "progression_rationale": string
}"""

_FIELD_REQUIREMENTS = """\
Field requirements:
- prerequisites        (2–4 items): concepts a learner MUST understand before tackling \
this topic — order from most to least foundational; name real algorithms, data structures, \
or standards (e.g. "cosine similarity", not "math")
- related_topics       (3–5 items): peer-level topics at the same difficulty tier that \
complement this one from a different angle — avoid duplicating prerequisites or follow-ups
- advanced_follow_ups  (3–5 items): topics that become accessible after mastering this \
one — order nearest to furthest; name concrete systems or techniques
- learning_progression (4–8 items): the complete logical learning path from the earliest \
prerequisite to the most advanced follow-up; the topic itself MUST appear at the correct \
position in the list; no duplicates
- progression_rationale: 1–2 sentences explaining the sequencing logic and what skill \
each major stage unlocks for the learner"""

_RULES = """\
Rules:
- Be specific: name real frameworks, algorithms, and protocols — never vague categories
- Every item must be a concrete, nameable topic ("HNSW indexing", not "indexing concepts")
- No item should appear in more than one field
- Ordering matters: prerequisites most-to-least foundational; follow-ups nearest-to-furthest"""


def build_topic_expansion_prompt(topic: str) -> str:
    composer = PromptComposer()
    composer.add_section("persona",            _PERSONA,
                         priority=1, required=True,  source_pack="")
    composer.add_section("topic_input",        f"TOPIC: {topic.strip()}",
                         priority=1, required=True,  source_pack="dynamic")
    composer.add_section("schema_intro",       _SCHEMA_INTRO,
                         priority=2, required=True,  source_pack="")
    composer.add_section("schema",             _SCHEMA,
                         priority=2, required=True,  source_pack="")
    composer.add_section("field_requirements", _FIELD_REQUIREMENTS,
                         priority=3, required=True,  source_pack="")
    composer.add_section("rules",              _RULES,
                         priority=3, required=True,  source_pack="")
    return composer.build()
