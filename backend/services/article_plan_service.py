"""
Article Plan Service

Creates per-article source assignments BEFORE the LLM generation call so that
every generated card has a designated set of real retrieved sources to draw from.

Pipeline position:
  ranked_articles → build_article_plans() → validate_plans() → plans_to_prompt_block()
                                                                        ↓
                                                              make_daily_package_prompt()
                                                                        ↓
                                                               LLM generation
                                                                        ↓
                                            (existing _valid_source() post-check in project_service)

Phase 9.3.4A additions (planning layer only — no generation changes):
  resolve_package_counts(selected_count)          → (core_count, curiosity_count)
  build_article_plans(..., article_type="core")   → list[ArticlePlan]  (curiosity support)
  build_batch_plans(plans, max_articles_per_batch)→ list[BatchPlan]
  validate_batch_plans(batch_plans)               → tuple[bool, list[str]]

Rules enforced
--------------
1. Article cannot exist without at least MIN_SOURCES assigned source.
2. Dummy URLs prohibited (example.com, placeholders, empty strings).
3. Plans persist as a formatted prompt block until rendering.
4. Post-generation URL validation is handled by project_service._valid_source().
5. (9.3.4A) Supporting sources may only reference URLs within the same batch.
6. (9.3.4A) Primary source URLs must be unique across the entire package.

Public API
----------
resolve_package_counts(selected_count)           → tuple[int, int]
build_article_plans(ranked_articles, count, ...)  → list[ArticlePlan]
validate_plans(plans)                            → tuple[bool, list[str]]
plans_to_prompt_block(plans, core_articles, frame_hint=None) → str
build_batch_plans(plans, max_articles_per_batch) → list[BatchPlan]
validate_batch_plans(batch_plans)                → tuple[bool, list[str]]
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

MIN_SOURCES:    int = 1   # article cannot exist without at least this many sources
MAX_SOURCES:    int = 4   # preferred ceiling; more sources rarely improve LLM output
BACKUP_SOURCES: int = 2   # backup sources held per slot for grounding fallback

# Min duplicate_score for a candidate to qualify as a supporting source.
# Calibrated on real article pairs: 0.054 (clearly adjacent, shared vocabulary)
# vs 0.008 (same sector, different vocabulary) — 0.05 splits that gap cleanly.
# Well below NEAR_DUP_THRESHOLD=0.50 (same-story near-duplicates).
SUPPORTING_COHERENCE_THRESHOLD: float = 0.05

# Phase 9.3.4A: curiosity card count is fixed at 2 per package — single source of truth.
_CURIOSITY_COUNT: int = 2

_TYPE_LABELS: dict[str, str] = {
    "news":            "current reporting",
    "research_paper":  "research evidence",
    "government":      "official data",
    "industry_report": "industry analysis",
    "company_blog":    "practitioner perspective",
    "regulatory":      "regulatory guidance",
    "educational":     "conceptual foundation",
    "market_analysis": "market intelligence",
}

_RANK_PHRASES: dict[str, str] = {
    "authority":    "high-authority source covering",
    "freshness":    "recent source on",
    "intent_match": "directly matched to",
    "novelty":      "unique perspective on",
}

# URL patterns that indicate a fabricated or placeholder source.
_DUMMY_PATTERNS: frozenset[str] = frozenset([
    "example.com", "placeholder", "localhost", "127.0.0.1",
    "yoursite", "yourdomain", "test.com", "fake.com",
    "http://url", "https://url", "example.org", "example.net",
])


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ArticlePlan:
    slot_id:          str               # e.g. "slot-1" (core) or "curiosity-slot-1"
    topic_hint:       str               # short phrase derived from primary article title
    assigned_sources: list[dict]        # ordered: [primary, ...supporting]
    backup_sources:   list[dict] = field(default_factory=list)  # fallback pool if primary fails grounding
    # Phase 9.3.4A — batch metadata (None until build_batch_plans is called)
    batch_id:         int | None = None
    batch_position:   int | None = None
    article_type:     str        = "core"   # "core" | "curiosity"

    @property
    def primary_source(self) -> dict | None:
        return self.assigned_sources[0] if self.assigned_sources else None

    @property
    def source_urls(self) -> list[str]:
        return [s.get("url", "") for s in self.assigned_sources]

    @property
    def all_source_urls(self) -> list[str]:
        return [s.get("url", "") for s in self.assigned_sources + self.backup_sources]


@dataclass
class BatchPlan:
    """
    Phase 9.3.4A — One future writer call.

    Planning layer only: no generation logic, no LLM calls.
    Supporting sources in every member plan are scoped to within this batch
    (i.e. only URL from primary_source_urls appear as supporting sources).
    Backup sources are unscoped — any retrieved URL is valid.
    """
    batch_id:               int
    article_ids:            list[str]    # slot_id values from member plans, in order
    plans:                  list[ArticlePlan]
    primary_source_urls:    list[str]    # one URL per plan, package-globally unique
    supporting_source_urls: list[str]    # deduplicated; all within-batch primaries
    backup_source_urls:     list[str]    # deduplicated; may reference outside-batch URLs


# ── Package count resolution — single source of truth ────────────────────────

def resolve_package_counts(selected_count: int) -> tuple[int, int]:
    """
    Return (core_count, curiosity_count) from the total selected article count.

    Rules:
      selected_count <= 5  →  (selected_count, 2)
      selected_count  > 5  →  (selected_count - 2, 2)

    Examples: 4→(4,2)  5→(5,2)  6→(4,2)  7→(5,2)  10→(8,2)
    """
    if selected_count <= 5:
        return selected_count, _CURIOSITY_COUNT
    return selected_count - _CURIOSITY_COUNT, _CURIOSITY_COUNT


# ── Private helpers ───────────────────────────────────────────────────────────

def _is_dummy_url(url: str) -> bool:
    """True when URL is empty or matches known placeholder patterns."""
    if not url or not url.strip():
        return True
    lower = url.lower()
    return any(p in lower for p in _DUMMY_PATTERNS)


def _derive_topic_hint(article: dict) -> str:
    """Extract a short topic label from an article — first 8 meaningful words of title."""
    title = article.get("title", "") or ""
    words = re.sub(r"[^\w\s-]", "", title).split()
    return " ".join(words[:8]) if words else "Topic"


def _generate_why_used(source: dict, topic_hint: str) -> str:
    """Deterministic ≤25-word rationale using source metadata. No LLM call."""
    rank_phrase = _RANK_PHRASES.get(source.get("_rank_reason") or "", "selected for")
    type_label  = _TYPE_LABELS.get(source.get("source_type") or "", "relevant analysis")
    topic       = topic_hint or source.get("retrieval_query") or "this topic"
    domain      = source.get("domain") or (source.get("url") or "")[:40]

    text  = f"Selected as {rank_phrase} {topic}; provides {type_label} from {domain}."
    words = text.split()
    return " ".join(words[:24]) + "." if len(words) > 25 else text


# ── Public API ────────────────────────────────────────────────────────────────

def build_article_plans(
    ranked_articles: list[dict],
    count:           int,
    article_type:    str = "core",
    project_id:      str = "",
) -> list[ArticlePlan]:
    """
    Build one ArticlePlan per planned article slot.

    Assignment strategy:
      Slot i gets ranked_articles[i] as its primary source.
      Supporting sources: up to MAX_SOURCES-1 next articles in rank order
      (wrapping with modulo so every slot gets at least one supporting source
      when enough articles are available).

    Phase 9.3.4A:
      article_type="curiosity" tags plans for curiosity cards and uses the
      "curiosity-slot-N" slot_id prefix to distinguish from core plans.
      Supporting sources may cross batch boundaries at this stage; call
      build_batch_plans() to scope them to within-batch primaries.

    Articles with dummy or empty URLs are excluded upfront so plans are always
    backed by real retrieved sources.

    Returns fewer plans than `count` if fewer valid sources are available.
    """
    valid = [a for a in ranked_articles if a.get("url") and not _is_dummy_url(a.get("url", ""))]
    if not valid:
        return []

    n_slots     = min(count, len(valid))
    n_valid     = len(valid)
    if n_slots < count:
        logger.warning(
            "[ARTICLE PLAN] project_id=%s type=%s: only %d valid articles for %d requested slots — "
            "returning %d plans",
            project_id, article_type, n_valid, count, n_slots,
        )
    from .similarity_service import duplicate_score as _coherence_score  # local import avoids circular dep

    slot_prefix = "curiosity-slot" if article_type == "curiosity" else "slot"
    plans: list[ArticlePlan] = []

    used_primary_urls: set[str] = set()

    for i in range(n_slots):
        # Skip forward through ranked articles if the natural candidate URL is already claimed.
        primary = valid[i]
        if primary.get("url", "") in used_primary_urls:
            primary = next(
                (v for v in valid if v.get("url", "") and v.get("url") not in used_primary_urls),
                valid[i],  # fallback: reuse if exhausted (supporting filter still guards)
            )
        used_primary_urls.add(primary.get("url", ""))
        topic_hint = _derive_topic_hint(primary)
        supporting: list[dict] = []
        for j in range(1, MAX_SOURCES):
            if len(supporting) >= MAX_SOURCES - 1:
                break
            idx = (i + j) % n_valid
            candidate = valid[idx]
            if candidate.get("url") == primary.get("url"):
                continue
            if _coherence_score(primary, candidate) < SUPPORTING_COHERENCE_THRESHOLD:
                continue
            supporting.append(candidate)

        if not supporting:
            logger.info(
                "[ARTICLE PLAN] project_id=%s type=%s slot=%d: no coherent supporting source found — running primary-only",
                project_id, article_type, i + 1,
            )

        assigned_urls = {url for url in [primary.get("url")] + [s.get("url") for s in supporting] if url}
        backup: list[dict] = []
        for _step in range(n_valid):
            if len(backup) >= BACKUP_SOURCES:
                break
            cand = valid[(i + MAX_SOURCES + _step) % n_valid]
            cand_url = cand.get("url", "")
            if cand_url and cand_url not in assigned_urls:
                backup.append(cand)
                assigned_urls.add(cand_url)

        def _with_why(src: dict, hint: str = topic_hint) -> dict:
            src_copy = dict(src)
            src_copy["why_used"] = _generate_why_used(src_copy, hint)
            return src_copy

        plans.append(ArticlePlan(
            slot_id          = f"{slot_prefix}-{i + 1}",
            topic_hint       = topic_hint,
            assigned_sources = [_with_why(primary)] + [_with_why(s) for s in supporting],
            backup_sources   = backup,
            article_type     = article_type,
        ))

    return plans


def validate_plans(plans: list[ArticlePlan]) -> tuple[bool, list[str]]:
    """
    Validate all article plans.

    Returns (ok, errors). Errors are human-readable strings describing which
    plans fail and why. ok = True means all plans are valid and ready for use.

    Checks:
      - At least one plan exists
      - Each plan has >= MIN_SOURCES assigned sources
      - Each source has a non-empty, non-dummy URL
    """
    errors: list[str] = []

    if not plans:
        errors.append("No article plans generated — no valid sources available")
        return False, errors

    for plan in plans:
        if len(plan.assigned_sources) < MIN_SOURCES:
            errors.append(
                f"{plan.slot_id}: fewer than {MIN_SOURCES} source(s) assigned "
                f"(got {len(plan.assigned_sources)})"
            )
            continue

        for src in plan.assigned_sources:
            url = src.get("url", "")
            if not url:
                errors.append(f"{plan.slot_id}: source '{src.get('title', '?')}' has empty URL")
            elif _is_dummy_url(url):
                errors.append(f"{plan.slot_id}: dummy URL rejected — {url!r}")

    return len(errors) == 0, errors


def plans_to_prompt_block(
    plans:              list[ArticlePlan],
    core_articles:      list[dict] | None = None,
    source_id_prefix:   str = "",
    frame_hint:         str | None = None,
    article_type_label: str = "CORE",
) -> str:
    """
    Render article plans as a prompt block for injection into the LLM context.

    Uses {article_type_label}-N Source-IDs matching the ordering in fmt_articles().

    Phase 9.3.4B: source_id_prefix prepends a batch qualifier to every Source-ID.
      ""        → "CORE-1"           (package mode, unchanged)
      "B1-"     → "B1-CORE-1"       (core batch)
      "B3-"     → "B3-CURIOSITY-1"  (curiosity batch, article_type_label="CURIOSITY")

    Returns an empty string when plans is empty (safe to inject unconditionally).
    """
    if not plans:
        return ""

    # Build URL → {type}-N mapping from core_articles order (same as fmt_articles)
    url_to_id: dict[str, str] = {}
    if core_articles:
        for i, a in enumerate(core_articles[:8], 1):
            url = a.get("url", "")
            if url:
                url_to_id[url] = f"{article_type_label}-{i}"

    def _sid(url: str, fallback: str = "CORE-?") -> str:
        base = url_to_id.get(url, fallback)
        return f"{source_id_prefix}{base}" if source_id_prefix else base

    lines: list[str] = [
        "ARTICLE SOURCE ASSIGNMENTS -- MANDATORY",
        "=" * 38,
        (
            "Each card in Section 1 MUST be written from its assigned sources. "
            "The PRIMARY source drives the `evidence` block (cite its Source-ID). "
            "Supporting sources may inform other blocks. The primary_source URL in your "
            "JSON output MUST be taken from the slot's Primary or Supporting source listed below."
        ),
        "",
    ]

    for plan in plans:
        slot_num = plan.slot_id.split("-")[-1]
        lines.append(f"SLOT {slot_num} -- Topic hint: {plan.topic_hint}")
        if frame_hint:
            lines.append(f"  Narrative shape: {frame_hint}")

        for j, src in enumerate(plan.assigned_sources):
            url   = src.get("url", "")
            title = (src.get("title") or "")[:70]
            label = "Primary:   " if j == 0 else "Supporting:"
            lines.append(f"  {label} [{_sid(url)}] {title}")
            lines.append(f"             URL: {url}")

        if plan.backup_sources:
            n = len(plan.backup_sources)
            lines.append(f"  ({n} backup source{'s' if n != 1 else ''} held in reserve — auto-assigned if primary/supporting citations fail grounding)")

        lines.append("")

    return "\n".join(lines)


# ── Phase 9.3.4A: Batch planning ──────────────────────────────────────────────

def build_batch_plans(
    plans:                  list[ArticlePlan],
    max_articles_per_batch: int = 4,
) -> list[BatchPlan]:
    """
    Partition article plans into batches, scoping supporting sources to batch-local primaries.

    Phase 9.3.4A — planning layer only. Current generation (single-call) is unchanged;
    this prepares the architecture for the multi-call writer introduced in 9.3.4B.

    Partitioning rules:
      - Core plans (article_type="core") are chunked into batches of max_articles_per_batch.
      - Curiosity plans (article_type="curiosity") always form a single final batch,
        regardless of max_articles_per_batch.

    Supporting-source scoping:
      Each plan's assigned_sources[1:] (supporting) is filtered to only include URLs
      that appear as primary sources within the same batch. Cross-batch supporting
      references are silently dropped (the original plan objects are NOT mutated).

    Backup sources are NOT scoped — any retrieved URL is valid as a backup regardless
    of which batch its primary article belongs to.

    batch_id (1-indexed, sequential) and batch_position (0-indexed within batch)
    are stamped onto shallow copies of each plan. Original plans are never mutated.

    Returns an empty list for empty input.
    """
    if not plans:
        return []

    core_plans      = [p for p in plans if p.article_type == "core"]
    curiosity_plans = [p for p in plans if p.article_type == "curiosity"]

    batch_plans: list[BatchPlan] = []
    batch_id = 1

    for i in range(0, len(core_plans), max_articles_per_batch):
        chunk = core_plans[i : i + max_articles_per_batch]
        batch_plans.append(_build_one_batch(chunk, batch_id))
        batch_id += 1

    if curiosity_plans:
        batch_plans.append(_build_one_batch(curiosity_plans, batch_id))

    _log_batch_plans(batch_plans)
    return batch_plans


def _build_one_batch(plans: list[ArticlePlan], batch_id: int) -> BatchPlan:
    """
    Stamp batch metadata and scope supporting sources to within-batch primaries.

    Creates shallow copies of each plan so the original list is never mutated.
    assigned_sources list is replaced (not mutated) on each copy.
    """
    batch_primary_urls: set[str] = set()
    for p in plans:
        if p.primary_source:
            url = p.primary_source.get("url", "")
            if url:
                batch_primary_urls.add(url)

    scoped_plans: list[ArticlePlan] = []
    for pos, plan in enumerate(plans):
        scoped               = copy.copy(plan)
        scoped.batch_id      = batch_id
        scoped.batch_position = pos

        # Re-scope supporting: keep only URLs that are primaries within this batch
        if scoped.assigned_sources:
            primary     = scoped.assigned_sources[0]
            primary_url = primary.get("url", "")
            in_batch    = [
                s for s in scoped.assigned_sources[1:]
                if s.get("url") and s.get("url") in batch_primary_urls
                and s.get("url") != primary_url
            ]
            scoped.assigned_sources = [primary] + in_batch

        scoped_plans.append(scoped)

    primary_urls = [
        p.assigned_sources[0].get("url", "")
        for p in scoped_plans
        if p.assigned_sources
    ]
    supporting_urls = list({
        s.get("url", "")
        for p in scoped_plans
        for s in p.assigned_sources[1:]
        if s.get("url")
    })
    backup_urls = list({
        s.get("url", "")
        for p in scoped_plans
        for s in p.backup_sources
        if s.get("url")
    })

    return BatchPlan(
        batch_id               = batch_id,
        article_ids            = [p.slot_id for p in scoped_plans],
        plans                  = scoped_plans,
        primary_source_urls    = primary_urls,
        supporting_source_urls = supporting_urls,
        backup_source_urls     = backup_urls,
    )


def _log_batch_plans(batch_plans: list[BatchPlan]) -> None:
    """Emit structured [BATCH PLAN] log lines — one summary + one per batch."""
    total       = sum(len(bp.plans) for bp in batch_plans)
    n_core      = sum(len(bp.plans) for bp in batch_plans if bp.plans and bp.plans[0].article_type == "core")
    n_curiosity = total - n_core

    logger.info(
        "[BATCH PLAN] package_size=%d core=%d curiosity=%d batches=%d",
        total, n_core, n_curiosity, len(batch_plans),
    )
    for bp in batch_plans:
        batch_type = "curiosity" if (bp.plans and bp.plans[0].article_type == "curiosity") else "core"
        logger.info(
            "[BATCH PLAN] batch=%d type=%s size=%d primaries=%d supporting=%d backup=%d articles=[%s]",
            bp.batch_id, batch_type, len(bp.plans),
            len(bp.primary_source_urls),
            len(bp.supporting_source_urls),
            len(bp.backup_source_urls),
            " ".join(bp.article_ids),
        )


def validate_batch_plans(batch_plans: list[BatchPlan]) -> tuple[bool, list[str]]:
    """
    Validate a list of BatchPlan objects.

    Checks:
      A. No duplicate primary URLs across the entire package.
      B. Every plan has at least one assigned source.
      C. Every plan has backup sources — only enforced when the batch is large enough
         to supply them (len(batch.plans) >= MAX_SOURCES); small curiosity batches
         with 2 articles cannot provide backups and are exempt from this check.
      D. Supporting sources belong only to the same batch (no cross-batch refs).
      E. No batch is empty (applies to both core and curiosity batches).

    Curiosity plans are subject to all applicable checks — no separate path.

    Returns (ok, errors). errors is a list of human-readable strings.
    """
    errors: list[str] = []

    if not batch_plans:
        errors.append("No batch plans produced")
        return False, errors

    # A: Package-level primary uniqueness
    all_primaries: list[str] = []
    for bp in batch_plans:
        all_primaries.extend(bp.primary_source_urls)
    seen: set[str] = set()
    for url in all_primaries:
        if url in seen:
            errors.append(f"Duplicate primary URL across batches: {url!r}")
        else:
            seen.add(url)

    for bp in batch_plans:
        label = f"batch={bp.batch_id}"

        # E: Empty batch
        if not bp.plans:
            errors.append(f"{label}: empty — no plans")
            continue

        batch_primary_set = set(bp.primary_source_urls)
        # C applies only when the batch is large enough to supply backup sources
        check_backups = len(bp.plans) >= MAX_SOURCES

        for plan in bp.plans:
            slot = f"{label} {plan.slot_id}"

            # B: At least one assigned source
            if not plan.assigned_sources:
                errors.append(f"{slot}: no assigned sources")
                continue

            # C: Backup sources (conditional)
            if check_backups and not plan.backup_sources:
                errors.append(f"{slot}: no backup sources (batch has {len(bp.plans)} plans — backups expected)")

            # D: Supporting sources within batch only
            for src in plan.assigned_sources[1:]:
                url = src.get("url", "")
                if url and url not in batch_primary_set:
                    errors.append(f"{slot}: supporting source not in batch — {url!r}")

    return len(errors) == 0, errors
