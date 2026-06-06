"""
PromptComposer — centralized prompt assembly for all Curivio prompt builders.

Every prompt builder composes its output through PromptComposer instead of
manual string concatenation.  This gives a single place to:
  - add or remove named sections at runtime
  - estimate token usage before sending
  - generate a per-section token report for budget debugging

Usage
-----
    from .prompt_composer import PromptComposer

    composer = PromptComposer()
    composer.add_section("persona", "You are...", priority=1, required=True)
    composer.add_section("context", f"Topic: {topic}", priority=1, source_pack="dynamic")
    composer.add_section("schema", OUTPUT_SCHEMA, priority=2)
    return composer.build()

Priority scale
--------------
  1  Core identity / persona, primary output schema, essential user input
  2  Supporting context (articles, profile, analysis), task structure
  3  Writing / quality rules, personalization, editorial standards
  4  Philosophy, narrative guidance, style libraries
  5  Optional / lower-priority enhancements (default)

source_pack values
------------------
  ""                    Prompt-local static content (not from a shared pack)
  "dynamic"             Assembled at runtime from user / system data
  "core_writing_pack"   instruction_packs/core_writing_pack.py
  "core_reasoning_pack" instruction_packs/core_reasoning_pack.py
  "core_learning_pack"  instruction_packs/core_learning_pack.py
  "package_editorial_pack"  instruction_packs/package_editorial_pack.py
  "package_narrative_pack"  instruction_packs/package_narrative_pack.py
  "package_curiosity_pack"  instruction_packs/package_curiosity_pack.py
  "package_action_pack"     instruction_packs/package_action_pack.py
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════════
# Section metadata
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PromptSection:
    """
    A named prompt block with content and budget/priority metadata.

    Fields
    ------
    name            Unique identifier used for add/remove operations.
    content         The actual text injected into the final prompt.
    priority        Integer priority (1 = highest). Used by future budget-aware
                    assembly to decide which sections survive trimming.
    required        If True, this section must always be present.
                    If False, it may be omitted under tight budgets.
    source_pack     Which instruction pack this content originates from, or
                    "dynamic" for runtime-assembled content, or "" for
                    prompt-local static text.
    estimated_tokens  Manual token override for pre-planning.  0 means
                    auto-compute from content length at runtime.
    """

    name: str
    content: str
    priority: int = 5
    required: bool = True
    source_pack: str = ""
    estimated_tokens: int = 0

    @property
    def tokens(self) -> int:
        """Token estimate: uses estimated_tokens override when set, else 4-char heuristic."""
        if self.estimated_tokens > 0:
            return self.estimated_tokens
        return max(1, len(self.content) // 4)


# ═══════════════════════════════════════════════════════════════════════════════
# Composer
# ═══════════════════════════════════════════════════════════════════════════════

class PromptComposer:
    """
    Assembles a prompt from named PromptSection objects joined by a separator.

    Sections with empty or whitespace-only content are silently skipped so
    optional blocks (e.g. beginner calibration, memory callbacks) don't leave
    blank lines in the final prompt.
    """

    def __init__(self, separator: str = "\n\n") -> None:
        self._sections: list[PromptSection] = []
        self._separator = separator

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add_section(
        self,
        name: str,
        content: str,
        *,
        priority: int = 5,
        required: bool = True,
        source_pack: str = "",
        estimated_tokens: int = 0,
    ) -> "PromptComposer":
        """
        Append a named section with optional metadata.

        Skips empty / whitespace-only content so optional blocks don't add
        blank separators to the final prompt.

        Parameters
        ----------
        name              Section identifier (used by remove_section).
        content           Text to inject. Stripped of leading/trailing whitespace.
        priority          1 = highest priority (default 5).
        required          Whether the section must always be present (default True).
        source_pack       Origin pack name, "dynamic", or "" (default "").
        estimated_tokens  Manual token override for pre-planning (0 = auto).
        """
        text = str(content).strip() if content is not None else ""
        if not text:
            return self
        self._sections.append(PromptSection(
            name=name,
            content=text,
            priority=priority,
            required=required,
            source_pack=source_pack,
            estimated_tokens=estimated_tokens,
        ))
        return self

    def remove_section(self, name: str) -> "PromptComposer":
        """Remove all sections with the given name."""
        self._sections = [s for s in self._sections if s.name != name]
        return self

    # ── Estimation ────────────────────────────────────────────────────────────

    def estimate_tokens(self) -> int:
        """
        Estimate total prompt tokens using the 4-chars-per-token heuristic.

        Accounts for separator characters between sections.
        """
        total_chars = sum(len(s.content) for s in self._sections)
        if len(self._sections) > 1:
            total_chars += len(self._separator) * (len(self._sections) - 1)
        return max(1, total_chars // 4)

    def generate_report(self) -> dict:
        """
        Return a per-section breakdown including content metrics and metadata.

        Example output::

            {
                "section_count": 5,
                "sections": {
                    "persona": {
                        "chars": 240, "tokens": 60,
                        "priority": 1, "required": True,
                        "source_pack": "",
                    },
                    "articles": {
                        "chars": 3200, "tokens": 800,
                        "priority": 2, "required": True,
                        "source_pack": "dynamic",
                    },
                    ...
                },
                "total_tokens": 1200,
                "total_chars":  4800,
            }
        """
        sections = {
            s.name: {
                "chars":       len(s.content),
                "tokens":      s.tokens,
                "priority":    s.priority,
                "required":    s.required,
                "source_pack": s.source_pack,
            }
            for s in self._sections
        }
        return {
            "section_count": len(self._sections),
            "sections":      sections,
            "total_tokens":  self.estimate_tokens(),
            "total_chars":   sum(len(s.content) for s in self._sections),
        }

    # ── Assembly ──────────────────────────────────────────────────────────────

    def build(self) -> str:
        """Join all non-empty sections with the separator and return the prompt."""
        return self._separator.join(s.content for s in self._sections)
