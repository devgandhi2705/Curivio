from .prompt_composer import PromptComposer

_PERSONA = """\
You are a senior engineering educator designing a practical, opinionated learning path.
Your goal: give a practitioner the shortest path from zero to production-ready on a topic."""

_SCHEMA_INTRO = (
    "Generate a structured learning path in strict JSON. "
    "Output ONLY the JSON object — no markdown, no code fences, no explanation."
)

_SCHEMA = """\
{
  "beginner": [
    {
      "concept":        string,
      "explanation":    string,
      "why_it_matters": string,
      "resources":      [string, ...]
    }
  ],
  "intermediate": [...],
  "advanced":     [...]
}"""

_TIER_REQUIREMENTS = """\
Tier requirements:
- beginner     (2–3 items): foundational concepts — what it is, core mechanics, \
mental models; assume no prior knowledge of the topic
- intermediate (2–3 items): applied engineering — how to build with it, \
common patterns, performance trade-offs
- advanced     (2–4 items): specialist depth — internals, cutting-edge techniques, \
production failure modes, research frontiers"""

_PER_CONCEPT = """\
Per concept:
- concept        : short, precise name — name the specific technique or system \
("HNSW Indexing", not "indexing concepts")
- explanation    : 2–3 sentences on how it works mechanically — name data structures, \
algorithms, or protocols; no vague summaries
- why_it_matters : 1–2 sentences on engineering or career impact — what breaks \
without this knowledge, or what it unlocks
- resources      : 2–3 items — real, verifiable titles prefixed by type:
                   "Book: Title by Author (Year)"
                   "Course: Name — Platform"
                   "Paper: Title (Authors, Year)"
                   "Docs: Description — URL pattern (e.g. docs.example.com/…)"
                   "Repo: Description — github.com/owner/repo\""""

_PERSONALIZATION_RULES = """\
Personalization rules:
- learner stage "beginner"    : write beginner concepts accessibly; \
keep advanced dense and forward-pointing
- learner stage "intermediate": expand intermediate tier with production detail; \
beginner concepts can be concise
- learner stage "advanced"    : keep beginner/intermediate concise; \
expand advanced with internals and research depth
- difficulty_preference "beginner"   : favor intuition and analogies in explanations
- difficulty_preference "advanced"   : favor formal descriptions and edge cases"""

_ENGINEERING_RULES = """\
Engineering rules:
- Every concept must be actionable in under one week of focused study
- Resources must be real; do not invent titles
- Name real frameworks (FAISS, Weaviate, LangChain), papers \
(with author surnames), and standards (RFC numbers, POSIX)
- No filler phrases ("In today's world…", "It is important to note…")
- Prioritize depth over breadth — one mastered concept beats three half-understood ones"""


def build_learning_path_prompt(
    topic: str,
    learning_stage: str,
    difficulty_preference: str,
) -> str:
    learner_profile = (
        f"TOPIC: {topic}\n\n"
        f"LEARNER PROFILE:\n"
        f"  Current stage    : {learning_stage}   (beginner / intermediate / advanced)\n"
        f"  Difficulty pref  : {difficulty_preference}"
    )
    composer = PromptComposer()
    composer.add_section("persona",              _PERSONA,
                         priority=1, required=True, source_pack="")
    composer.add_section("learner_profile",      learner_profile,
                         priority=1, required=True, source_pack="dynamic")
    composer.add_section("schema_intro",         _SCHEMA_INTRO,
                         priority=2, required=True, source_pack="")
    composer.add_section("schema",               _SCHEMA,
                         priority=2, required=True, source_pack="")
    composer.add_section("tier_requirements",    _TIER_REQUIREMENTS,
                         priority=3, required=True, source_pack="")
    composer.add_section("per_concept",          _PER_CONCEPT,
                         priority=3, required=True, source_pack="")
    composer.add_section("personalization_rules", _PERSONALIZATION_RULES,
                         priority=3, required=True, source_pack="")
    composer.add_section("engineering_rules",    _ENGINEERING_RULES,
                         priority=4, required=True, source_pack="")
    return composer.build()
