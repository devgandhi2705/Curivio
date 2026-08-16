"""
Intent Profile Service — converts project details into a structured learning intent profile.

Runs once at project creation. Regenerates only when description or difficulty changes.
The profile becomes permanent project metadata used by all retrieval and generation layers.

Public API
----------
generate_intent_profile(name, description, keywords, difficulty) -> dict
save_intent_profile(project_id, profile)                        -> None
get_intent_profile(project_id)                                  -> dict | None
needs_regeneration(project_id, description, difficulty)         -> bool
backfill_intent_profiles()                                      -> dict
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from uuid import uuid4

logger = logging.getLogger(__name__)


_SCHEMA_EXAMPLE = """{
  "learning_subject": "Globalization Economics",
  "persona":          "Economics Student",
  "goal":             "Understand globalization for CBSE board exams",
  "industry_context": "Academic",
  "primary_focus":    "Trade theory and policy frameworks",
  "search_lens":      "Educational",
  "intent_summary":   "An economics student building exam-ready understanding of globalization — focused on concepts, definitions, and policy mechanics rather than business applications."
}"""

_VALID_LENSES = frozenset({
    "Educational", "Business Strategy", "Technical",
    "Policy & Regulation", "Investment & Markets",
    "Scientific Research", "Investigative",
})


def _hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def generate_intent_profile(
    name:        str,
    description: str,
    keywords:    list[str],
    difficulty:  str,
    project_id:  str | None = None,
    trace_id:    str | None = None,
) -> dict:
    """Call the LLM to extract a structured intent profile from project details.

    trace_id groups this call with the rest of a daily generation run when the
    caller is generate_project_insight(); standalone callers (project
    creation, backfill_intent_profiles) leave it unset and get a fresh id of
    their own, so every row still lands in a real trace_id group."""
    trace_id = trace_id or uuid4().hex
    kw_str = ", ".join(keywords) if keywords else "(none provided)"

    # < 10 words leaves too little signal for persona/industry_context extraction.
    _THIN_THRESHOLD  = 10
    _desc_word_count = len(description.split())
    if _desc_word_count < _THIN_THRESHOLD:
        logger.warning(
            "[intent_profile] project=%r thin description (%d words, threshold %d) — "
            "persona/industry fields may be generic",
            name, _desc_word_count, _THIN_THRESHOLD,
        )

    prompt = f"""You are an expert learning strategist. Analyze a learner's project and extract their intent profile.

LEARNING SUBJECT — what is being learned (project title):
{name}

LEARNER CONTEXT — who is learning it and why (description):
{description}

Keywords: {kw_str}
Level:    {difficulty}

Extract the following fields:

1. learning_subject — the core topic being studied. Derived ONLY from the project title, not the description.
   Captures the domain and method (e.g. "AI Agents & Marketing Automation", "Globalization Economics", "Transformer Architecture").
2. persona          — who this learner is. Derived from LEARNER CONTEXT. A concise role label (2–3 words).
   Examples: "Economics Student", "Startup Founder", "ML Engineer", "Pharma Marketing Lead".
3. goal             — what they want to achieve. Combines both: "Apply [learning subject] in [their context]".
   Must start with an action verb.
4. industry_context — the sector or setting. Derived from LEARNER CONTEXT, not the title.
   Examples: "Academic", "Pharmaceutical", "Startup", "Finance", "Healthcare".
5. primary_focus    — specific sub-area to go deep on. Derived from LEARNING SUBJECT (title).
   Describes WHAT is being learned, NOT where or why.
   Example: title "AI Agents for Marketing Automation" → "AI agent systems and agentic marketing workflows"
   WRONG: "Digital marketing in pharma" (description bleeding into subject — reject this pattern).
6. search_lens      — editorial angle that best serves finding content ON THE LEARNING SUBJECT.
   Choose exactly one: Educational / Business Strategy / Technical / Policy & Regulation / Investment & Markets / Scientific Research / Investigative.
7. intent_summary   — 1–2 sentence editorial brief. Format: "[persona] learning [learning_subject] through a [industry_context] lens — needs [what kind of content]."

CRITICAL SEPARATION RULES:
- primary_focus and learning_subject come from the TITLE. Description must NOT dilute them.
- industry_context and persona come from the DESCRIPTION.
- If title = "AI Agents for Marketing Automation" and description = "pharma marketing lead":
    learning_subject = "AI Agents & Marketing Automation"           ← from title
    primary_focus    = "Agentic marketing workflows and automation" ← from title
    industry_context = "Pharmaceutical"                            ← from description
    REJECT primary_focus = "Digital marketing in pharma"           ← description contamination

Examples:

LEARNING SUBJECT: Globalization
LEARNER CONTEXT: I am an economics student preparing for CBSE boards
Output:
{{
  "learning_subject": "Globalization Economics",
  "persona":          "Economics Student",
  "goal":             "Understand globalization theory and policy for board exams",
  "industry_context": "Academic",
  "primary_focus":    "Trade theory, comparative advantage, and economic integration",
  "search_lens":      "Educational",
  "intent_summary":   "An economics student building exam-ready understanding of globalization — focused on concepts, definitions, and policy mechanics rather than business applications."
}}

LEARNING SUBJECT: AI Agents for Marketing Automation
LEARNER CONTEXT: Marketing lead at a pharma company selling gynac and orthopedic products
Output:
{{
  "learning_subject": "AI Agents & Marketing Automation",
  "persona":          "Pharma Marketing Lead",
  "goal":             "Apply AI agent systems to automate marketing workflows for pharma products",
  "industry_context": "Pharmaceutical",
  "primary_focus":    "Agentic marketing workflows, campaign automation, and AI-driven outreach",
  "search_lens":      "Business Strategy",
  "intent_summary":   "A pharma marketing lead learning AI agents and marketing automation — needs content on agentic systems and campaign workflows with pharmaceutical industry application examples."
}}

Rules:
- persona must be a role label (2–3 words max), not a sentence
- goal must start with an action verb
- search_lens must be exactly one of the 7 options listed
- intent_summary must be editorial — brief a senior analyst, do not paraphrase the description
- Do not echo the description verbatim

Return ONLY valid JSON matching this schema:
{_SCHEMA_EXAMPLE}"""

    try:
        from ..llm import get_chat_model, extract_text
        _meta = {
            "call_type": "feed_persona", "project_id": project_id,
            "trace_id": trace_id, "surface": "feed_legacy", "agent_name": "persona",
        }
        model = get_chat_model(json_mode=True)
        text  = extract_text(model.invoke(prompt, config={"metadata": _meta}))
        try:
            profile = _extract_json(text)
        except (json.JSONDecodeError, ValueError):
            logger.warning("[intent_profile] project=%r JSON parse failed — retrying once", name)
            text    = extract_text(model.invoke(
                prompt + "\n\nIMPORTANT: Return ONLY valid JSON, no other text.",
                config={"metadata": _meta},
            ))
            profile = _extract_json(text)

        lens = profile.get("search_lens") or ""
        if lens not in _VALID_LENSES:
            lens = "Educational"

        return {
            "learning_subject": profile.get("learning_subject") or name,
            "persona":          profile.get("persona")          or "Learner",
            "goal":             profile.get("goal")             or (description[:120] if description else name),
            "industry_context": profile.get("industry_context") or "",
            "primary_focus":    profile.get("primary_focus")    or name,
            "search_lens":      lens,
            "intent_summary":   profile.get("intent_summary")   or (description[:200] if description else name),
            "_meta":            {"description_hash": _hash(description), "difficulty": difficulty, "thin_input": _desc_word_count < _THIN_THRESHOLD},
        }

    except Exception as e:
        logger.error("[intent_profile] generation failed: %s — returning fallback", e)
        return {
            "learning_subject": name,
            "persona":          "Learner",
            "goal":             description[:120] if description else name,
            "industry_context": "",
            "primary_focus":    name,
            "search_lens":      "Educational",
            "intent_summary":   description[:200] if description else name,
            "_meta":            {"description_hash": _hash(description), "difficulty": difficulty, "thin_input": _desc_word_count < _THIN_THRESHOLD},
        }


def save_intent_profile(project_id: str, profile: dict) -> None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE learning_projects SET intent_profile = ? WHERE project_id = ?",
            (json.dumps(profile), project_id),
        )


def get_intent_profile(project_id: str) -> dict | None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT intent_profile FROM learning_projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    if not row or not row["intent_profile"]:
        return None
    try:
        return json.loads(row["intent_profile"])
    except Exception:
        return None


def needs_regeneration(project_id: str, description: str, difficulty: str) -> bool:
    """Return True if the stored profile was generated with different description or difficulty."""
    profile = get_intent_profile(project_id)
    if not profile:
        return True
    meta = profile.get("_meta") or {}
    return (
        meta.get("description_hash") != _hash(description)
        or meta.get("difficulty") != difficulty
    )


def backfill_intent_profiles() -> dict:
    """
    One-time migration: generate intent profiles for all projects that lack one.
    Safe to call multiple times; skips projects where intent_profile is already set.
    Returns {"total": int, "migrated": int, "failed": int}
    """
    from ..utils.db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT project_id, name, description, keywords, difficulty FROM learning_projects WHERE intent_profile IS NULL",
        ).fetchall()

    if not rows:
        return {"total": 0, "migrated": 0, "failed": 0}

    logger.info("[intent_profile] backfill starting — %d project(s) without profile", len(rows))
    migrated = failed = 0

    for row in rows:
        project_id = row["project_id"]
        try:
            try:
                keywords = json.loads(row["keywords"] or "[]")
            except Exception:
                keywords = []

            profile = generate_intent_profile(
                name=row["name"],
                description=row["description"] or "",
                keywords=keywords,
                difficulty=row["difficulty"] or "intermediate",
                project_id=project_id,
            )

            with get_connection() as conn:
                conn.execute(
                    "UPDATE learning_projects SET intent_profile = ?, intent_confirmed = 1 WHERE project_id = ?",
                    (json.dumps(profile), project_id),
                )

            migrated += 1
            logger.info("[intent_profile] backfilled %s → persona=%s", project_id, profile.get("persona", "?"))
        except Exception as e:
            failed += 1
            logger.warning("[intent_profile] backfill failed for %s: %s", project_id, e)

    logger.info("[intent_profile] backfill complete — migrated=%d failed=%d", migrated, failed)
    return {"total": len(rows), "migrated": migrated, "failed": failed}


def suggest_keywords(name: str, description: str, difficulty: str) -> list[str]:
    """Use the LLM to suggest 8-10 retrieval-anchored keywords for a learning project.

    Internally generates an intent profile first so keyword selection is driven by
    learner persona and goal, not just topic name.
    """
    trace_id = uuid4().hex
    profile = generate_intent_profile(name, description, [], difficulty, trace_id=trace_id)
    persona          = profile.get("persona")          or "Learner"
    goal             = profile.get("goal")             or description[:120]
    search_lens      = profile.get("search_lens")      or "Educational"
    industry_context = profile.get("industry_context") or ""

    learning_subject = profile.get("learning_subject") or name

    prompt = f"""
You are a retrieval strategist for a personalized learning system.

Your task is NOT to brainstorm topics.

Your task is to generate retrieval anchors that will help a search system find the most useful learning material for this specific learner.

LEARNING SUBJECT — what is being learned (from project title):
{learning_subject}

LEARNER CONTEXT — who is learning it and why:
{description}

Learner Level:
{difficulty}

Intent Profile:
Persona: {persona}
Goal: {goal}
Search Lens: {search_lens}
Industry Context: {industry_context}

WEIGHTING RULE:
* Keywords must be about the LEARNING SUBJECT first.
* LEARNER CONTEXT provides the industry lens — it shapes examples and framing, NOT the retrieval topic.
* Title "AI Agents for Marketing Automation" + Context "pharma":
    CORRECT: "AI marketing automation agents", "agentic campaign workflows", "LLM-powered marketing tools"
    WRONG:   "pharma marketing regulations", "drug company digital strategy" (context bleeding into subject)

Generate 8-10 highly specific retrieval keywords.

Rules:

* Prioritize learner intent over topic name.
* Keywords should help retrieve content useful for THIS learner.
* Avoid generic terms.
* Avoid broad categories.
* Avoid duplicate concepts.
* Avoid near-synonyms.
* Prefer search-ready phrases over single words.
* Include both foundational and practical concepts when appropriate.
* Include current developments ONLY if relevant to the learner's goal.
* Think like a search engineer, not a teacher.

Examples:

Topic: Globalization
Persona: Economics Student

Good:

* globalization theory
* WTO and globalization
* trade liberalization examples
* economic integration models

Bad:

* business
* international trade
* economy

---

Topic: Globalization
Persona: Startup Founder

Good:

* international market entry strategy
* export expansion framework
* global supply chain management
* cross-border business regulations

Bad:

* globalization
* trade
* economics

Return ONLY a JSON array of strings.

Example:

[
"international market entry strategy",
"cross-border business regulations",
"global supply chain management",
"export expansion framework",
"trade agreement impact on startups",
"global market localization strategy"
]
"""

    try:
        from ..llm import get_chat_model, extract_text
        import json as _json
        import re as _re
        model = get_chat_model(json_mode=True)
        text  = extract_text(model.invoke(prompt, config={"metadata": {
            "call_type": "feed_persona_keywords",
            "trace_id": trace_id, "surface": "feed_legacy", "agent_name": "persona_keywords",
        }}))
        m = _re.search(r"\[.*?\]", text, _re.DOTALL)
        if m:
            keywords = _json.loads(m.group(0))
            if isinstance(keywords, list):
                return [str(k).strip() for k in keywords if k][:10]
        parsed = _json.loads(text.strip())
        if isinstance(parsed, list):
            return [str(k).strip() for k in parsed if k][:10]
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return [str(k).strip() for k in v if k][:10]
        raise ValueError("No keyword list found in LLM response")
    except Exception as e:
        logger.error("[intent_profile] suggest_keywords failed: %s", e)
        raise


def _extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    return json.loads(text.strip())
