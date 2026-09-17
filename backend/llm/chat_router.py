"""The one classifier and the one turn plan.

Every chat turn asks one small model the same six questions as JSON — search?
how complex? run code? simple tone? crisis? — and plan_turn() merges that
answer with the user's toggles into the TurnPlan the rest of the turn reads.

Toggles are overrides, not modes: "Web Search" forces a search and "Explain
Simply" forces simple tone; the classifier decides everything else, including
on those turns. A Feed card never blocks a search.

JSON-schema structured output, never tool calling: the tool-calling classifier
failed on Groq with "Tool choice is required, but model did not call a tool"
and with stringified booleans, and those failures cost a whole extra leg each.
An invalid answer here just falls through to the next model in [classifier].

If every classifier model fails, plan_turn gets None and the turn still runs:
simple route, search only if the user asked for one, and crisis ON. That
fail-safe is code, never something the model has to reason its way to.

Public API
----------
RoutingDecision                                  the JSON the classifier fills
TurnPlan                                         what the rest of the turn reads
classify_message(message, *, history, card_title, has_image, metadata) -> RoutingDecision | None
plan_turn(decision, *, message, ...) -> TurnPlan
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from .call_logger import LLMCallLogger
from .model_provider import AllLegsFailed, InvalidOutputError, build_leg, route_label, run_route

logger = logging.getLogger(__name__)

_CALL_TYPE = "chat_router_classify"

# The crisis paragraph is carried over verbatim from the previous classifier:
# it is the wording that produced the crisis field this app's safety path
# depends on, and it is not up for casual rewording.
_SYSTEM_PROMPT = (
    "You route one chat turn for a learning assistant. Read the conversation and the user's "
    "latest message, then fill in every field.\n\n"
    "needs_web_search: true when a good answer needs something you cannot be sure of — a recent "
    "event, a current price or statistic, a release or version, someone's current status, "
    "anything after your training data, or a claim the user wants verified. False for "
    "explanations, opinions, code, maths, and anything the conversation or an attached card "
    "already answers.\n"
    "search_query: a short search-engine query for exactly what needs looking up; empty string "
    "when needs_web_search is false.\n"
    "complexity: \"complex\" when the answer needs multi-step reasoning, comparison, synthesis, "
    "or the user asked for depth; \"simple\" for a direct factual or conversational answer.\n"
    "needs_code_execution: true only when answering requires actually RUNNING code — computing a "
    "result, checking what a snippet outputs. False when the user only wants code written or "
    "explained.\n"
    "wants_simple_explanation: true when the user asks for a simple, beginner, plain-English or "
    "ELI5 explanation.\n"
    "crisis: true if the message signals the person is thinking about suicide, self-harm, or not "
    "wanting to be alive — recognize it however it's phrased: plainly, sideways, hypothetically, "
    "bitterly, as a threat, as a joke, or as leverage in an argument they're losing. You cannot "
    "always tell whether they mean it — treat it as real regardless. False for everything else, "
    "including ordinary frustration, dark humor with nothing behind it, or a message that "
    "discusses crisis/mental health as a topic rather than as a personal signal."
)


class RoutingDecision(BaseModel):
    needs_web_search: bool = Field(description="True if answering needs live web data")
    search_query: str = Field(description="Search-ready query; empty string when no search is needed")
    complexity: Literal["simple", "complex"] = Field(
        description="'simple' = direct answer; 'complex' = multi-step reasoning or synthesis")
    needs_code_execution: bool = Field(
        description="True only if the answer requires running code, not just writing it")
    wants_simple_explanation: bool = Field(
        description="True if the user asked for a simple/beginner/ELI5 explanation")
    crisis: bool = Field(
        description="True if the message signals real personal distress (suicide, self-harm, "
                    "not wanting to be alive), however phrased")


@dataclass(frozen=True)
class TurnPlan:
    """What one turn does. Everything downstream reads this and nothing else."""
    route: str          # "simple" | "complex" | "code" | "image" — which model list answers
    reason: str         # "classifier" / "classifier_failed", plus any override that changed it
    search: bool
    search_query: str
    simple_tone: bool
    crisis: bool
    complexity: str     # "simple" | "complex" — also sizes the search


def _history_text(turn: dict) -> str:
    """History can carry multipart content (text plus a Gemini media part on an
    image turn). The classifier only ever needs the text: an image tells it
    nothing about routing, and a file_uri means nothing to another provider."""
    content = turn.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and part.get("type") == "text")
    return ""


_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _drop_stale_years(query: str, said: str) -> str:
    """Remove years older than this one that nobody in the conversation wrote.

    The classifier's training data ends before today, so it tends to pin
    "latest"-style queries to what it thinks the current year is. A past year
    only belongs in the query when the user (or the chat so far) brought it up."""
    this_year = datetime.now(timezone.utc).year
    mentioned = set(_YEAR_RE.findall(said))

    def keep(m: re.Match) -> str:
        year = m.group(0)
        return year if int(year) >= this_year or year in mentioned else ""

    return " ".join(_YEAR_RE.sub(keep, query).split())


def classify_message(
    message: str, *, history: list[dict] | None = None,
    card_title: str = "", has_image: bool = False, metadata: dict | None = None,
) -> RoutingDecision | None:
    """Classify one turn. Returns None (never raises) when every model in the
    [classifier] list fails — the caller treats that as crisis=True."""
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "system", "content": (
            f"Today's date is {datetime.now(timezone.utc):%Y-%m-%d}. Your training data is older "
            "than that, so what you think of as the latest year or version may be out of date. "
            "Never put a year in search_query unless the user asked about that year; for "
            "anything current, describe it (\"latest\", \"current\") instead of dating it.")},
    ]
    if card_title:
        messages.append({"role": "system", "content": (
            f'This chat is about a Feed card titled "{card_title}". Its text is already in front '
            "of the answering model, so seeing the card itself is not a reason to search.")})
    if has_image:
        messages.append({"role": "system", "content": (
            "An image is attached to this turn and the answering model can see it. The image "
            "itself is not a reason to search.")})
    for turn in history or []:
        text = _history_text(turn)
        if text:
            messages.append({"role": turn.get("role", "user"), "content": text})
    messages.append({"role": "user", "content": message})

    notes: list[str] = []
    base_meta = {"call_type": _CALL_TYPE, **(metadata or {})}

    def attempt(spec):
        structured = build_leg(spec).with_structured_output(
            RoutingDecision, method="json_schema", include_raw=True)
        result = structured.invoke(messages, config={
            "callbacks": [LLMCallLogger()],
            "metadata": {**base_meta,
                         "route": route_label("classifier", "", notes),
                         "route_step": spec.step},
        })
        parsed = result.get("parsed") if isinstance(result, dict) else result
        if not isinstance(parsed, RoutingDecision):
            error = result.get("parsing_error") if isinstance(result, dict) else None
            raise InvalidOutputError(f"no valid RoutingDecision (parsing_error={error!r})")
        yield parsed

    try:
        _, results = run_route("classifier", attempt, notes=notes)
        decision = next(iter(results))
    except AllLegsFailed:
        logger.warning("[chat_router] no classifier model answered (%s) — safe plan applies",
                       "; ".join(notes))
        return None

    said = "\n".join([message, *(_history_text(t) for t in history or [])])
    query = _drop_stale_years(decision.search_query, said)
    if query != decision.search_query:
        decision = decision.model_copy(update={"search_query": query})
    return decision


def plan_turn(
    decision: RoutingDecision | None, *, message: str, has_image: bool = False,
    toggle_web_search: bool = False, toggle_simple: bool = False,
    feed_action: str | None = None, sticky_simple: bool = False,
) -> TurnPlan:
    """Merge the classifier's answer with the user's overrides.

    search       Web Search toggle OR decision.needs_web_search
    search_query decision.search_query when it has one, else the user's message
    simple_tone  Explain Simply toggle OR Feed explain_simply OR sticky session
                 OR decision.wants_simple_explanation
    crisis       decision.crisis — and True whenever the classifier failed
    route        image if an image is attached; else code, complex, or simple
    reason       the base plus every override that applied, for the admin log
    """
    overrides: list[str] = []
    if toggle_web_search:
        overrides.append("+toggle:web_search")
    if toggle_simple:
        overrides.append("+toggle:explain_simply")
    if feed_action == "explain_simply":
        overrides.append("+feed:explain_simply")
    if sticky_simple and not toggle_simple:
        overrides.append("+sticky:explain_simply")

    forced_simple = toggle_simple or feed_action == "explain_simply" or sticky_simple

    if decision is None:
        return TurnPlan(
            route="image" if has_image else "simple",
            reason="".join(["classifier_failed", *overrides]),
            search=toggle_web_search,
            search_query=message,
            simple_tone=forced_simple,
            crisis=True,
            complexity="simple",
        )

    if has_image:
        route = "image"
    elif decision.needs_code_execution:
        route = "code"
    elif decision.complexity == "complex":
        route = "complex"
    else:
        route = "simple"

    return TurnPlan(
        route=route,
        reason="".join(["classifier", *overrides]),
        search=toggle_web_search or decision.needs_web_search,
        search_query=(decision.search_query or "").strip() or message,
        simple_tone=forced_simple or decision.wants_simple_explanation,
        crisis=decision.crisis,
        complexity=decision.complexity,
    )
