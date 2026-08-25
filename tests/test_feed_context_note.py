from backend.services.chat_modes_service import build_feed_context_note


def test_feed_context_note_preserves_complete_card_content_and_sources():
    note = build_feed_context_note({
        "action": "ask_about",
        "insight_title": "Forecasting models",
        "insight_summary": "A complete summary that must not be truncated.",
        "why_it_matters": "The mechanism explains the non-linear tradeoff.",
        "educational_explanation": "A longer explanation of how the models adapt.",
        "blocks": [{"type": "evidence", "content": "The evidence block is retained."}],
        "source_urls": ["https://example.com/paper"],
        "source_links": [{"title": "Paper", "url": "https://example.com/paper"}],
    })

    assert "Summary: A complete summary that must not be truncated." in note
    assert "Why it matters: The mechanism explains the non-linear tradeoff." in note
    assert "Educational explanation: A longer explanation of how the models adapt." in note
    assert "[evidence] The evidence block is retained." in note
    assert "Paper: https://example.com/paper" in note
    assert "do NOT search the web" not in note
    assert "use web search" in note
    assert "inspect the provided source URLs" in note