"""
Tests for backend.services.layman_mode_service — domain-aware analogy bank
selection, plus regression coverage for Phase 1's layman-exit fix (the "no
way out" bug: once a session entered sticky layman mode, no code path ever
cleared it, so an explicit "normal" toggle got silently overridden by
chat_service.chat_stream's restore-check on the next turn).

The exit-mode fix itself lives in chat_service.py (_LAYMAN_EXIT_RE /
_requests_layman_exit + the restore-check block), not in this module — it is
covered here, real end-to-end via chat_stream, because that fix previously
had no dedicated test file, only a live session trace pasted into a phase
report. Marked @pytest.mark.integration (real LLM turns, real dev DB) per
this project's convention for live-call tests.
"""
from __future__ import annotations

import uuid

import pytest

from backend.services.layman_mode_service import build_layman_directive


# ─────────────────────────────────────────────────────────────────────────────
# Domain-aware analogy bank selection
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalogyBankSelection:
    def test_pharmaceutical_domain_gets_pharma_bank(self):
        d = build_layman_directive(domain="Pharmaceutical")
        assert "restaurant with a health inspection certificate" in d

    def test_ai_domain_gets_ai_bank(self):
        d = build_layman_directive(domain="Artificial Intelligence")
        assert "hiring 1 million interns" in d

    def test_finance_domain_gets_finance_bank(self):
        d = build_layman_directive(domain="Banking")
        assert "water pressure in a pipe" in d

    def test_technology_domain_gets_technology_bank(self):
        d = build_layman_directive(domain="Software Engineering")
        assert "standardised plug socket" in d

    def test_unclassified_domain_falls_back_to_default_bank(self):
        d = build_layman_directive(domain="Underwater Basket Weaving")
        assert "Match the analogy to the mechanism" in d

    def test_empty_domain_falls_back_to_default_bank(self):
        d = build_layman_directive(domain="")
        assert "Match the analogy to the mechanism" in d

    def test_topic_hint_anchors_the_analogy(self):
        d = build_layman_directive(domain="ai", topic_hint="transformer attention")
        assert 'Anchor the analogy to the specific topic: "transformer attention"' in d

    def test_known_concepts_prepend_anchor_block(self):
        d = build_layman_directive(domain="ai", known_concepts=["neural networks", "backpropagation"])
        assert "KNOWN CONCEPT ANCHORS" in d
        assert "'neural networks'" in d
        assert "'backpropagation'" in d
        # anchor block must come before the rest of the directive
        assert d.index("KNOWN CONCEPT ANCHORS") < d.index("ANALOGY DOMAIN BANK")

    def test_analogy_bank_placeholder_fully_resolved(self):
        # {{ANALOGY_BANK}} must never leak into the final directive
        d = build_layman_directive(domain="finance")
        assert "{{ANALOGY_BANK}}" not in d


# ─────────────────────────────────────────────────────────────────────────────
# Regression: Phase 1 layman-exit fix ("no way out" bug)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestLaymanExitRegression:
    def _run_turn(self, session_id: str, message: str, chat_mode: str) -> None:
        from backend.services import chat_service
        for _ in chat_service.chat_stream(session_id, message, chat_mode=chat_mode, is_test=True):
            pass  # side effect (session_conversation_mode persistence) happens post-stream

    def test_explicit_exit_phrase_clears_sticky_layman_mode(self):
        from backend.services.chat_title_service import get_session_conversation_mode

        session_id = f"test-layman-exit-{uuid.uuid4().hex[:8]}"

        # Turn 1: enter layman mode explicitly
        self._run_turn(session_id, "explain how neural networks work simply", chat_mode="layman")
        assert get_session_conversation_mode(session_id) == "layman"

        # Turn 2: chat_mode defaults back to "normal" (frontend toggle), message
        # contains an explicit exit phrase -> must be treated as a real exit.
        self._run_turn(session_id, "ok, back to normal now, thanks", chat_mode="normal")
        assert get_session_conversation_mode(session_id) == "normal", (
            "explicit exit phrase must clear the sticky layman flag"
        )

    def test_no_way_out_bug_is_fixed_stays_normal_on_next_plain_turn(self):
        """
        The original bug: after exiting, a later bare "normal" turn (no exit
        phrase, nothing special about the message) got silently coerced back
        into layman by the restore-check, because the sticky flag was never
        actually cleared. This reproduces that exact 3rd-turn scenario.
        """
        from backend.services.chat_title_service import get_session_conversation_mode

        session_id = f"test-layman-noexit-{uuid.uuid4().hex[:8]}"

        self._run_turn(session_id, "explain photosynthesis simply", chat_mode="layman")
        assert get_session_conversation_mode(session_id) == "layman"

        self._run_turn(session_id, "exit layman mode please", chat_mode="normal")
        assert get_session_conversation_mode(session_id) == "normal"

        # Plain follow-up, no exit phrase, no explicit mode override -- must
        # NOT fall back into layman now that the flag is genuinely cleared.
        self._run_turn(session_id, "what is the capital of Japan", chat_mode="normal")
        assert get_session_conversation_mode(session_id) == "normal", (
            "session must stay normal on a later plain turn -- this is the exact "
            "'no way out' scenario the fix addresses"
        )
