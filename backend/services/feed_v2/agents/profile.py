"""
Feed v2 profile agent (Phase 5).

Turns a project's title + description + its ingested materials into the persona
(legacy's 7 fields) PLUS three new coverage fields — material_scope, coverage_mode,
coverage_reasoning — that the whole downstream journey depends on.

TWO deliberate departures from legacy intent_profile_service, both required by the
Phase 5 design:

  1. PROMPT RULE REVERSED. Legacy's hard rule was "primary_focus and
     learning_subject come from the TITLE... description must NOT dilute them"
     (intent_profile_service.py:96-104). Here the TITLE and the MATERIAL together
     inform learning_subject/primary_focus, and the MATERIAL WINS when the title is
     thin (e.g. "ML course" + a real syllabus → the subject comes from the
     syllabus, not the two-word title). This is the exact case the legacy rule
     broke on. Stated in the prompt itself so a future reader doesn't assume it
     mirrors legacy.

  2. NO SILENT FALLBACK. Legacy swallowed a generation failure into a hardcoded
     {"persona":"Learner", "industry_context":"", ...} with no signal to the user
     (intent_profile_service.py:173-184). This module does NOT. If every provider
     leg fails, provider.call_agent raises AllLegsFailed and we let it propagate —
     the caller marks the project profile_status='failed' (visible + retryable) and
     writes NO fake profile.

coverage_mode is a REAL inference the LLM makes from the QUERYABLE Phase-4 signal
columns (has_structure / section_count / type / material count) that we hand it
per material — not a hardcoded if/else here, and not the agent re-deriving
structure from raw text.

Isolation: imports only ..llm.provider (feed_v2's own SDK-direct provider), never
backend.services.* / backend.llm.*.
"""
from __future__ import annotations

import json
import logging

from ..llm.provider import AllLegsFailed, call_agent  # noqa: F401  (AllLegsFailed re-exported for callers)

logger = logging.getLogger(__name__)

_VALID_COVERAGE = {"material_bound", "material_anchored", "open"}
_VALID_LENSES = {
    "Educational", "Business Strategy", "Technical",
    "Policy & Regulation", "Investment & Markets",
    "Scientific Research", "Investigative",
}

_SYSTEM = (
    "You are an expert learning strategist. From a learner's project and the "
    "material they uploaded, extract a structured learning intent profile AND "
    "decide how tightly the uploaded material should bound their learning journey. "
    "Return ONLY a JSON object — no prose, no markdown fences."
)


def _material_block(materials: list[dict]) -> str:
    """One line per material, exposing the QUERYABLE Phase-4 signal columns
    (type / has_structure / section_count) plus section titles + a short excerpt so
    the agent can describe scope — it must NOT re-derive structure from raw text."""
    if not materials:
        return "(none — the learner uploaded no material)"
    lines = []
    for i, m in enumerate(materials, 1):
        titles = ", ".join(m.get("section_titles") or []) or "(no detected sections)"
        excerpt = (m.get("excerpt") or "").strip().replace("\n", " ")
        if len(excerpt) > 400:
            excerpt = excerpt[:400] + "…"
        lines.append(
            f"{i}. type={m.get('type')} | label={m.get('label') or '?'} | "
            f"has_structure={m.get('has_structure')} | section_count={m.get('section_count')}\n"
            f"   sections: {titles}\n"
            f"   excerpt: {excerpt or '(none)'}"
        )
    return "\n".join(lines)


def _prompt(name: str, description: str, keywords: list[str], difficulty: str,
            materials: list[dict]) -> str:
    kw = ", ".join(keywords) if keywords else "(none provided)"
    doc_count = sum(1 for m in materials if m.get("type") == "document")
    structured = sum(1 for m in materials if m.get("has_structure"))
    return f"""PROJECT TITLE (what is being learned):
{name or '(untitled)'}

LEARNER CONTEXT (who is learning it and why — the description):
{description or '(none provided)'}

Keywords: {kw}
Level: {difficulty}

UPLOADED MATERIAL ({len(materials)} item(s); {doc_count} document(s), {structured} with detected structure):
{_material_block(materials)}

Extract these fields:

1. learning_subject — the core topic. Informed by BOTH the title and the material.
   MATERIAL WINS WHEN THE TITLE IS THIN: if the title is generic/short (e.g. "ML
   course", "notes") and the material is specific, take the subject from the
   material's actual content and structure, not the thin title. (This REVERSES the
   old rule that the subject must come from the title alone.)
2. persona — who this learner is. A 2-3 word role label from LEARNER CONTEXT
   (e.g. "Economics Student", "Startup Founder"). Description owns this, not material.
3. goal — what they want to achieve. Starts with an action verb.
4. industry_context — the sector/setting, from LEARNER CONTEXT (e.g. "Academic",
   "Pharmaceutical", "Startup"). Description owns this, not material.
5. primary_focus — the specific sub-area to go deep on. Title + material inform it;
   material wins when the title is thin. Describes WHAT is learned.
6. search_lens — exactly one of: Educational / Business Strategy / Technical /
   Policy & Regulation / Investment & Markets / Scientific Research / Investigative.
7. intent_summary — a 1-2 sentence editorial brief.
8. material_scope — what the uploaded material actually COVERS and where it STOPS,
   derived from the section titles and structure signals above. If there is no
   material, say so plainly (e.g. "No material uploaded — open topic").
9. coverage_mode — how tightly the material should bound the journey. Choose ONE:
   - "material_bound": the material is the syllabus. Signals: description uses
     course/exam/syllabus/chapter language; a material is a syllabus/textbook/
     lecture-notes type; ONE large STRUCTURED document (has_structure true, a
     meaningful section_count) rather than several small unstructured ones.
   - "material_anchored": the material seeds the journey but doesn't bound it.
     Signals: small UNSTRUCTURED documents/links (has_structure false, low/zero
     section_count); description language like "want to learn" / "getting into".
   - "open": no material at all — the journey is driven by the title/description.
   Base this on the has_structure / section_count / type / count signals above,
   not on re-reading the raw text.
10. coverage_reasoning — ONE sentence explaining the coverage_mode choice, shown to
    the learner on the confirmation screen.

Return ONLY valid JSON with exactly these keys:
{{"learning_subject": "...", "persona": "...", "goal": "...",
  "industry_context": "...", "primary_focus": "...", "search_lens": "...",
  "intent_summary": "...", "material_scope": "...",
  "coverage_mode": "material_bound|material_anchored|open",
  "coverage_reasoning": "..."}}"""


def run_profile(*, name: str, description: str, keywords: list[str],
                difficulty: str, materials: list[dict], meta: dict | None = None) -> dict:
    """Run the profile agent. Returns the profile dict on success.

    Raises AllLegsFailed (from provider.call_agent) if every provider leg fails —
    NO silent fallback profile. The caller turns that into a visible, retryable
    profile_status='failed' state.
    """
    prompt = _prompt(name, description, keywords or [], difficulty or "intermediate", materials or [])
    call_meta = {"call_type": "feed_v2_profile", "surface": "feed_v2", "agent_name": "profile"}
    call_meta.update(meta or {})

    obj = call_agent("profile", [{"role": "user", "content": prompt}],
                     system=_SYSTEM, meta=call_meta)

    # Normalize the two constrained fields; everything else is passed through as the
    # agent returned it. (call_agent already validated required keys + the schema.)
    coverage = str(obj.get("coverage_mode") or "").strip()
    if coverage not in _VALID_COVERAGE:
        # If materials exist the agent should have picked bound/anchored; with none,
        # the only sensible value is open. Default the odd-value case toward the
        # material-present reality rather than inventing a persona.
        coverage = "open" if not materials else "material_anchored"
    lens = obj.get("search_lens") or "Educational"
    if lens not in _VALID_LENSES:
        lens = "Educational"

    return {
        "learning_subject":   obj.get("learning_subject") or name,
        "persona":            obj.get("persona") or "",
        "goal":               obj.get("goal") or "",
        "industry_context":   obj.get("industry_context") or "",
        "primary_focus":      obj.get("primary_focus") or name,
        "search_lens":        lens,
        "intent_summary":     obj.get("intent_summary") or "",
        "material_scope":     obj.get("material_scope") or "",
        "coverage_mode":      coverage,
        "coverage_reasoning": obj.get("coverage_reasoning") or "",
    }


def _demo() -> None:
    """ponytail self-check: prompt wiring is exercised without a network call."""
    p = _prompt("ML course", "I want to get into ML", [], "beginner",
                [{"type": "document", "label": "syllabus.md", "has_structure": 1,
                  "section_count": 4, "section_titles": ["Week 1", "Week 2"],
                  "excerpt": "course outline"}])
    assert "MATERIAL WINS WHEN THE TITLE IS THIN" in p
    assert "has_structure=1" in p and "section_count=4" in p  # queryable signals reach the prompt
    assert "coverage_mode" in p
    empty = _prompt("Quantum", "learn quantum", [], "beginner", [])
    assert "no material" in empty
    print("profile._demo OK")


if __name__ == "__main__":
    _demo()
