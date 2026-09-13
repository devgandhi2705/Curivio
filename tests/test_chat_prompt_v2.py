"""One prompt builder for every chat turn.

The old split (natural vs a mandatory-JSON "structured" prompt for Feed-linked
turns) is gone: the JSON card format had zero real uses since 2026-08-01, and
the split is what let a Feed turn carry both _GUIDELINES ("use bullet points")
and RESPONSE PRINCIPLES ("decide the shape yourself") in the same prompt.

The size ceilings below are the spec's, measured on real logged prompts:
Explain Simply 14.3K -> 8.0K, Ask About 10.6K -> 7.5K, web search 13.4K ->
7.0K, plain chat 9.1K -> 6.5K characters."""
from __future__ import annotations

import pytest

from backend.services.chat_modes_service import build_feed_context_note, format_reasoning_search_note
from backend.services.chat_prompt_service import (
    MAX_HISTORY_TURNS, build_messages, build_response_principles, build_system_prompt,
)

CRISIS_MARKER = "CRISIS AND DISTRESS SUPPORT — ALWAYS IN FORCE:"
JSON_MARKER = "You MUST respond with ONLY a valid JSON object"

MECHANISM = ("Climate shocks act as a hidden variable that shrinks the budget for state-level "
             "maintenance, forcing a move from redundant systems to single points of failure.")

CARD = {
    "action": "explain_simply",
    "insight_title": "The Hidden Climate-Dependency Nobody Prices In",
    "insight_summary": ("When we analyse the long decline of states like the Byzantine Empire, "
                        "climate-induced supply shocks act as a force multiplier for existing "
                        "systemic inefficiencies rather than as a separate cause."),
    "why_it_matters": MECHANISM,
    "mechanism": MECHANISM,
    "blocks": [{"type": "evidence", "content": "B1-CORE-4 shows Byzantine growth tracked climate "
                                               "variability, with agricultural dips matching "
                                               "periods of military and administrative fragility."},
               {"type": "mechanism", "content": MECHANISM},
               {"type": "implication", "content": "If modern supply chains mirror this, today's "
                                                  "lean operations are building the same fragility."}],
    "source_urls": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC9362599/"],
    "source_links": [{"title": "Byzantine Economic Growth and Climate", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9362599/"}],
    "project_name": "B2B Regression Byzantine Empire",
    "progression_stage": "foundation",
    "recent_mechanisms": ["The 1453 collapse that set the rules for imperial resilience",
                          "Why Byzantine machine learning is about trust, not accuracy"],
}

CONTEXT = {
    "user_name": "Dev",
    "conversation_memory": {"message_count": 6, "session_turns": 3,
                            "topics_discussed": ["Byzantine supply chains", "reasoning models"],
                            "last_user_messages": ["What changed in 1453?"]},
    "vector_memory": ("Related past discussion (different session, same user):\n"
                      "  • [Forecasting] Why reasoning models replaced linear regressions"),
    "user_profile": {"learning_stage": "early", "top_interests": ["AI", "history"]},
    "current_message": "Explain this simply.",
}


def _prompt_size(*parts: str) -> int:
    return len("\n".join(p for p in parts if p))


class TestPersonaAndPrinciples:
    def test_one_persona_with_the_user_name(self):
        prompt = build_system_prompt(CONTEXT)
        assert prompt.count("You are Curivio") == 1
        assert "The user's name is Dev." in prompt

    def test_principles_are_present_once(self):
        assert build_system_prompt(CONTEXT).count("RESPONSE PRINCIPLES:") == 1

    def test_simple_tone_variant_drops_the_two_conflicting_rules(self):
        full, simple = build_response_principles(False), build_response_principles(True)
        assert "Decide length and depth" in full and "Decide length and depth" not in simple
        assert "Decide the shape" in full and "Decide the shape" not in simple

    @pytest.mark.parametrize("fragment", [
        "Lead with the actual answer", "Explain WHY, not just WHAT",
        "never invent a source", "change your approach", "Continuity",
    ])
    def test_simple_tone_variant_keeps_every_other_rule(self, fragment):
        assert fragment in build_response_principles(True)

    def test_the_tension_rule_survived_as_a_principle(self):
        assert "open tension" in build_response_principles(False)


class TestSimpleTone:
    def test_directive_only_when_asked_for(self):
        assert "MECHANISM-PRESERVING SIMPLIFICATION" not in build_system_prompt(CONTEXT)
        assert "MECHANISM-PRESERVING SIMPLIFICATION" in build_system_prompt(CONTEXT, simple_tone=True)

    def test_the_five_step_structure_survives(self):
        prompt = build_system_prompt(CONTEXT, simple_tone=True)
        for step in ("THE CORE IDEA", "THE ANALOGY", "THE MECHANISM", "WHY IT EXISTS", "THE INSIGHT"):
            assert step in prompt

    def test_only_one_self_check_remains(self):
        prompt = build_system_prompt(CONTEXT, simple_tone=True)
        assert "ANALOGY QUALITY TEST" not in prompt
        assert "ABSTRACTION SELF-CHECK" not in prompt
        assert "STRATEGIC MEANING TEST" not in prompt
        assert "Check once before finalising" in prompt


class TestCrisisSection:
    def test_absent_when_not_flagged(self):
        assert CRISIS_MARKER not in build_system_prompt(CONTEXT)

    @pytest.mark.parametrize("simple_tone", [False, True])
    def test_present_when_flagged_in_either_tone(self, simple_tone):
        prompt = build_system_prompt({**CONTEXT, "crisis_active": True}, simple_tone=simple_tone)
        assert CRISIS_MARKER in prompt

    def test_it_is_the_last_block(self):
        prompt = build_system_prompt({**CONTEXT, "crisis_active": True})
        assert prompt.index(CRISIS_MARKER) > prompt.index("RESPONSE PRINCIPLES:")
        assert prompt.rstrip().endswith("Help doesn't wait for an answer.")

    def test_locale_still_reaches_it(self):
        prompt = build_system_prompt({**CONTEXT, "crisis_active": True, "client_timezone": "Asia/Kolkata"})
        assert "findahelpline.com/countries/in" in prompt


class TestNoJsonPath:
    @pytest.mark.parametrize("extra", [{}, {"feed_linked": True}, {"response_depth": "research"}])
    def test_no_json_schema_is_ever_emitted(self, extra):
        assert JSON_MARKER not in build_system_prompt({**CONTEXT, **extra})

    def test_attachment_awareness_only_when_something_is_attached(self):
        assert "ATTACHMENT AWARENESS" not in build_system_prompt(CONTEXT)
        assert "ATTACHMENT AWARENESS" in build_system_prompt({**CONTEXT, "has_attachment": True})


class TestFeedNote:
    def test_the_card_mechanism_appears_once(self):
        note = build_feed_context_note(CARD)
        system = build_system_prompt(CONTEXT, simple_tone=True)
        assert (note + system).count(MECHANISM) == 1

    def test_explain_simply_no_longer_forbids_search(self):
        note = build_feed_context_note(CARD)
        assert "Do NOT search the web" not in note
        assert "web_search" not in note

    def test_ask_about_keeps_the_feed_specific_instruction_only(self):
        note = build_feed_context_note({**CARD, "action": "ask_about"})
        assert note.startswith("[FEED INSIGHT — Discussion]")
        assert "Answer THEIR question" in note
        assert "RESPONSE PRINCIPLES" not in note, "the principles are in the system prompt already"

    def test_extracted_text_is_cleaned(self):
        messy = ("![logo](/front/assets/logo.svg)\n"
                 "Get trending papers in your email inbox!\n"
                 "Get trending papers in your email inbox!\n"
                 "[Sign in](/login)\n"
                 "### [Infinite Worlds with Versatile Interactions](/papers/2607.07534)\n"
                 "An advanced world modelling system with extended interaction capabilities.\n"
                 "![avatar](https://cdn.example.com/a.png)\n")
        note = build_feed_context_note({**CARD, "source_contents": {CARD["source_urls"][0]: messy}})
        assert "![" not in note and "/front/assets/logo.svg" not in note
        assert note.count("Get trending papers in your email inbox!") == 1
        assert "Infinite Worlds with Versatile Interactions" in note, "a real title is not noise"
        assert "(/login)" not in note


class TestSearchNote:
    def _note(self, complicating):
        return format_reasoning_search_note({
            "primary_query": "byzantine climate collapse",
            "contradiction_query": "byzantine climate collapse criticism",
            "supporting": [{"title": "A", "content": "Supporting body text.", "url": "https://a"}],
            "complicating": complicating,
            "has_complicating": bool(complicating),
        })

    def test_citation_rules_survive(self):
        note = self._note([])
        assert "[1]" in note and "https://a" in note
        assert "Cite" in note

    def test_the_four_step_ritual_is_gone(self):
        note = self._note([])
        assert "PRIOR POSITION" not in note and "EVIDENCE CHECK" not in note

    def test_the_complicates_section_is_only_asked_for_when_sources_conflict(self):
        assert "What the data complicates" not in self._note([])
        assert "What the data complicates" in self._note(
            [{"title": "B", "content": "Contradicting body.", "url": "https://b"}])


class TestSizeCeilings:
    """The spec's ceilings, measured the way a turn actually assembles: system
    prompt plus the notes injected before the last user message."""

    TITLE_NOTE = ("This is the first message in this conversation. Begin your response with "
                  "exactly one line in this format:\n[TITLE: <4–6 word topic title>]\nThen write "
                  "your complete answer starting on the next line.")

    def test_plain_chat_under_6500(self):
        assert _prompt_size(build_system_prompt(CONTEXT)) <= 6500

    def test_feed_ask_about_under_7500(self):
        size = _prompt_size(build_system_prompt(CONTEXT),
                            build_feed_context_note({**CARD, "action": "ask_about"}),
                            self.TITLE_NOTE)
        assert size <= 7500, size

    def test_feed_explain_simply_under_8000(self):
        size = _prompt_size(build_system_prompt(CONTEXT, simple_tone=True),
                            build_feed_context_note(CARD), self.TITLE_NOTE)
        assert size <= 8000, size

    def test_web_search_turn_under_7000(self):
        note = format_reasoning_search_note({
            "primary_query": "q", "contradiction_query": "q criticism",
            "supporting": [{"title": f"Source {i}", "content": "A short result snippet of the kind "
                                                               "TinyFish returns for a news query.",
                            "url": f"https://example.com/{i}"} for i in range(5)],
            "complicating": [{"title": f"Complication {i}", "content": "A snippet that complicates "
                                                                      "the mainstream reading.",
                              "url": f"https://example.org/{i}"} for i in range(4)],
            "has_complicating": True,
        })
        assert _prompt_size(build_system_prompt(CONTEXT), note, self.TITLE_NOTE) <= 7000


class TestBuildMessages:
    def test_system_first_user_last(self):
        messages = build_messages([], "Hello there", CONTEXT)
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": "Hello there"}

    def test_history_is_truncated(self):
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
                   for i in range(40)]
        messages = build_messages(history, "new", CONTEXT)
        assert len(messages) == 1 + MAX_HISTORY_TURNS * 2 + 1

    def test_attachments_become_content_parts(self):
        messages = build_messages([], "what is this?", CONTEXT,
                                  attachments=[{"uri": "gs://x", "mime_type": "image/png"}])
        assert messages[-1]["content"][0] == {"type": "text", "text": "what is this?"}
        assert messages[-1]["content"][1]["file_uri"] == "gs://x"

    def test_simple_tone_flows_into_the_system_prompt(self):
        messages = build_messages([], "eli5", CONTEXT, simple_tone=True)
        assert "MECHANISM-PRESERVING SIMPLIFICATION" in messages[0]["content"]
