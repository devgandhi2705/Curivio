"""
Learning Projects service — CRUD and per-project daily intelligence generation.

Each call to generate_project_insight() produces a *daily package*:
  - N news + educational cards (count driven by daily_core_article_count)
  - 2 curiosity cards

Public API
----------
create_project(...)             -> dict
list_projects()                 -> list[dict]
get_project(project_id)         -> dict | None
update_project(project_id, ...) -> dict | None
delete_project(project_id)      -> bool
confirm_intent(project_id)      -> dict | None

generate_project_insight(project_id)       -> dict
generate_all_projects()                    -> dict
list_project_insights(project_id, limit)   -> list[dict]
get_project_insight(insight_id)            -> dict | None
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
_DATE_FMT     = "%Y-%m-%d"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_DATETIME_FMT)


def _today() -> str:
    return datetime.now(timezone.utc).strftime(_DATE_FMT)


# ─────────────────────────────────────────────────────────────────────────────
# Project CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_project(
    name: str,
    description: str = "",
    keywords: list[str] | None = None,
    difficulty: str = "intermediate",
    color: str = "blue",
    daily_core_article_count: int = 4,
    user_id: str | None = None,
) -> dict:
    from ..utils.db import get_connection
    project_id = str(uuid.uuid4())
    now = _now()
    count = max(2, min(10, int(daily_core_article_count)))
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO learning_projects
               (project_id, name, description, keywords, difficulty, color, daily_core_article_count, created_at, updated_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, name, description,
             json.dumps(keywords or []), difficulty, color,
             count, now, now, user_id),
        )
    project = get_project(project_id)

    # Generate intent profile at creation time (non-fatal — never blocks project creation)
    intent_profile = None
    try:
        from .intent_profile_service import generate_intent_profile, save_intent_profile
        intent_profile = generate_intent_profile(name, description, keywords or [], difficulty)
        save_intent_profile(project_id, intent_profile)
        project["intent_profile"] = intent_profile
    except Exception:
        logger.warning("[project_service] intent profile generation failed for %s (non-fatal)", project_id)

    return project


def list_projects(user_id: str | None = None) -> list[dict]:
    from ..utils.db import get_connection
    with get_connection() as conn:
        if user_id:
            rows = conn.execute(
                """SELECT p.*,
                          COALESCE(MAX(i.day_number), 0) AS insight_count,
                          MAX(i.generated_at) AS last_insight_at
                   FROM learning_projects p
                   LEFT JOIN project_insights i ON i.project_id = p.project_id
                   WHERE p.user_id = ?
                   GROUP BY p.project_id
                   ORDER BY p.updated_at DESC""",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT p.*,
                          COALESCE(MAX(i.day_number), 0) AS insight_count,
                          MAX(i.generated_at) AS last_insight_at
                   FROM learning_projects p
                   LEFT JOIN project_insights i ON i.project_id = p.project_id
                   GROUP BY p.project_id
                   ORDER BY p.updated_at DESC"""
            ).fetchall()
    return [_project_row(r) for r in rows]


def get_project(project_id: str) -> dict | None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            """SELECT p.*,
                      COALESCE(MAX(i.day_number), 0) AS insight_count,
                      MAX(i.generated_at) AS last_insight_at
               FROM learning_projects p
               LEFT JOIN project_insights i ON i.project_id = p.project_id
               WHERE p.project_id = ?
               GROUP BY p.project_id""",
            (project_id,),
        ).fetchone()
    return _project_row(row) if row else None


def update_project(project_id: str, **fields) -> dict | None:
    allowed = {"name", "description", "keywords", "difficulty", "color", "daily_core_article_count"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_project(project_id)
    new_description = updates.get("description")
    new_difficulty  = updates.get("difficulty")
    updates["updated_at"] = _now()
    if "keywords" in updates and isinstance(updates["keywords"], list):
        updates["keywords"] = json.dumps(updates["keywords"])
    if "daily_core_article_count" in updates:
        updates["daily_core_article_count"] = max(2, min(10, int(updates["daily_core_article_count"])))
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.execute(
            f"UPDATE learning_projects SET {set_clause} WHERE project_id = ?",
            [*updates.values(), project_id],
        )
    project = get_project(project_id)

    # Regenerate intent profile if description or difficulty changed (non-fatal, daemon thread)
    if (new_description or new_difficulty) and project:
        try:
            from .intent_profile_service import needs_regeneration as _ip_needs, generate_intent_profile as _ip_gen, save_intent_profile as _ip_save
            _desc = new_description or project.get("description", "")
            _diff = new_difficulty  or project.get("difficulty", "intermediate")
            if _ip_needs(project_id, _desc, _diff):
                import threading as _t
                def _regen_ip():
                    try:
                        _kw  = project.get("keywords") or []
                        _prof = _ip_gen(project["name"], _desc, _kw, _diff)
                        _ip_save(project_id, _prof)
                        logger.info("[project_service] intent profile regenerated for %s", project_id)
                    except Exception as _e:
                        logger.warning("[project_service] intent profile regen failed for %s (non-fatal): %s", project_id, _e)
                _t.Thread(target=_regen_ip, daemon=True, name=f"intent-regen-{project_id[:8]}").start()
        except Exception:
            pass

    return project


def delete_project(project_id: str) -> bool:
    from ..utils.db import get_connection
    with get_connection() as conn:
        r = conn.execute("DELETE FROM learning_projects WHERE project_id = ?", (project_id,))
    return r.rowcount > 0


def confirm_intent(project_id: str) -> dict | None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE learning_projects SET intent_confirmed = 1, updated_at = ? WHERE project_id = ?",
            (_now(), project_id),
        )
    return get_project(project_id)


def _project_row(row) -> dict:
    d = dict(row)
    raw = d.get("keywords")
    if isinstance(raw, str):
        try:
            d["keywords"] = json.loads(raw)
        except Exception:
            d["keywords"] = []
    elif raw is None:
        d["keywords"] = []
    if d.get("daily_core_article_count") is None:
        d["daily_core_article_count"] = 4
    raw_ip = d.get("intent_profile")
    if isinstance(raw_ip, str):
        try:
            d["intent_profile"] = json.loads(raw_ip)
        except Exception:
            d["intent_profile"] = None
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Display label helpers (mirrors frontend computeDisplayLabels / computeNextLabel)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_display_labels(project_id: str) -> dict[int, str]:
    """
    Returns {day_number: display_label} for all existing packages of a project.
    Same logic as the frontend computeDisplayLabels:
      - First package of each calendar date → "Day X"
      - Subsequent packages on same date   → "Day X.1", "Day X.2", …
    """
    from ..utils.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT day_number, DATE(generated_at) AS date_str, insight_json
               FROM project_insights
               WHERE project_id = ?
               ORDER BY day_number ASC""",
            (project_id,),
        ).fetchall()

    labels: dict[int, str] = {}
    calendar_day = 0
    last_date: str | None = None
    sub_count = 0

    for row in rows:
        try:
            pkg = json.loads(row["insight_json"]) if row["insight_json"] else {}
            insights = pkg.get("insights", []) or []
        except Exception:
            insights = []

        if not insights:          # failed package
            labels[row["day_number"]] = "Day 0"
            continue

        d = row["date_str"]
        if d != last_date:
            calendar_day += 1
            sub_count = 0
            last_date = d
            labels[row["day_number"]] = f"Day {calendar_day}"
        else:
            sub_count += 1
            labels[row["day_number"]] = f"Day {calendar_day}.{sub_count}"

    return labels


def _compute_next_display_label(project_id: str) -> tuple[str, str | None]:
    """
    Returns (next_display_label, prev_display_label) for the package about to
    be generated.  prev_display_label is None when no packages exist yet.
    """
    from ..utils.db import get_connection
    today = _today()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT day_number, DATE(generated_at) AS date_str
               FROM project_insights
               WHERE project_id = ? AND status != 'generating'
               ORDER BY day_number ASC""",
            (project_id,),
        ).fetchall()

    if not rows:
        return "Day 1", None

    # Rebuild calendar day counter (skip failed packages for numbering)
    existing_labels = _compute_display_labels(project_id)
    last_row = rows[-1]
    prev_label = existing_labels.get(last_row["day_number"])

    # Determine the highest non-Day-0 calendar day number
    good_labels = [v for v in existing_labels.values() if v != "Day 0"]
    if not good_labels:
        return "Day 1", prev_label

    # Extract the base calendar number from the latest good label
    import re as _re
    base_num = max(
        int(m.group(1))
        for label in good_labels
        if (m := _re.match(r"Day (\d+)", label))
    )

    today_count = sum(1 for r in rows if r["date_str"] == today)
    last_date = last_row["date_str"]

    if last_date == today:
        next_label = f"Day {base_num}.{today_count}"
    else:
        next_label = f"Day {base_num + 1}"

    return next_label, prev_label


# ─────────────────────────────────────────────────────────────────────────────
# Article retrieval — separate pipelines for core learning vs curiosity
# ─────────────────────────────────────────────────────────────────────────────

def _search_articles(query: str) -> list[dict]:
    """Single retrieval call — broad search, no domain restriction. Never raises."""
    try:
        from .retrieval_router import route
        return route(query, mode="feed")
    except Exception as e:
        logger.warning("[project_service] retrieval failed for %r: %s", query, e)
        return []


def _dedup_articles(articles: list[dict]) -> list[dict]:
    """Remove duplicate URLs, preserve order."""
    seen: set[str] = set()
    out: list[dict] = []
    for a in articles:
        url = a.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(a)
        elif not url:
            out.append(a)
    return out


def _fetch_core_articles(
    project_name: str,
    keywords: list[str],
    suggested_next_topics: list[str],
    retrieval_plan: dict | None = None,
) -> list[dict]:
    """Intent-driven retrieval for core learning cards (80% core + 10% adjacent)."""
    if retrieval_plan:
        queries = (retrieval_plan.get("core_queries") or []) + \
                  (retrieval_plan.get("adjacent_queries") or [])
    else:
        kw = " ".join(keywords[:3]) if keywords else project_name
        if suggested_next_topics:
            nt = suggested_next_topics[0]
            queries = [f"{project_name} {nt} 2025 2026", f"{nt} {kw} concepts framework analysis depth"]
        else:
            queries = [f"{project_name} {kw} latest developments 2025 2026",
                       f"{project_name} {kw} concepts framework deep dive"]

    results: list[dict] = []
    for q in queries:
        for art in _search_articles(q):
            art.setdefault("retrieval_query", q)
            results.append(art)
    return _dedup_articles(results)


_CURIOSITY_QUERIES = [
    "{project_name} {kw} biggest failure mistake controversy scandal",
    "{project_name} {kw} history origin invention accident discovery",
    "{project_name} {kw} surprising counterintuitive secret insider",
    "{project_name} {kw} behind the scenes hidden mechanism how it actually works",
    "{project_name} {kw} founder story pivot near failure comeback",
]


def _fetch_curiosity_articles(
    project_name: str,
    keywords: list[str],
    retrieval_plan: dict | None = None,
) -> list[dict]:
    """Serendipity retrieval for curiosity cards (10% surprising territory)."""
    if retrieval_plan and retrieval_plan.get("serendipity_queries"):
        queries = retrieval_plan["serendipity_queries"]
    else:
        kw = " ".join(keywords[:2]) if keywords else project_name
        import random
        angles  = random.sample(_CURIOSITY_QUERIES, k=min(2, len(_CURIOSITY_QUERIES)))
        queries = [a.format(project_name=project_name, kw=kw) for a in angles]

    results: list[dict] = []
    for q in queries:
        for art in _search_articles(q):
            art.setdefault("retrieval_query", q)
            results.append(art)
    return _dedup_articles(results)


# ─────────────────────────────────────────────────────────────────────────────
# Daily package generation
# ─────────────────────────────────────────────────────────────────────────────

# Jargon terms that are too dense for beginner content — each hit adds weight
_BEGINNER_JARGON: list[str] = [
    "value chain", "supply chain fragility", "supply fragility", "dependency risk",
    "competitive dynamics", "market fragmentation", "regulatory pathway",
    "regulatory framework", "operational efficiency", "cost structure",
    "margin compression", "demand elasticity", "vertical integration",
    "horizontal integration", "economies of scale", "first-mover advantage",
    "network effects", "platform economics", "monopsony", "oligopoly",
    "cartelization", "geopolitical", "macroeconomic", "systemic risk",
    "strategic imperative", "value proposition", "market positioning",
    "capital allocation", "risk-adjusted return", "portfolio optimization",
    # Pharma / domain-specific abbreviations (ok in context but jargon-heavy alone)
    " anda ", " nda ", " cmo ", " cro ", " ich ", " cdsco ", " who-gmp ",
]

_BEGINNER_JARGON_THRESHOLD = 18  # total jargon-term occurrences across the package


def _score_beginner_calibration(package: dict) -> int:
    """
    Count jargon-term occurrences across all card text fields.
    Returns total hit count; compare against _BEGINNER_JARGON_THRESHOLD.
    """
    all_cards = (package.get("insights", []) or []) + (package.get("curiosity_insights", []) or [])
    total_hits = 0
    for card in all_cards:
        blocks_text = " ".join(b.get("content", "") for b in (card.get("blocks") or []))
        text = " ".join(filter(None, [
            card.get("summary", ""),
            blocks_text or card.get("educational_explanation", ""),
            blocks_text or card.get("why_it_matters", ""),
        ])).lower()
        for term in _BEGINNER_JARGON:
            total_hits += text.count(term)
    return total_hits


def generate_project_insight(
    project_id: str,
    _stub_id: int | None = None,
    _precomputed_day_number: int | None = None,
) -> dict:
    """
    Generate a progressive daily learning package for a project.

    Package structure:
      - insights[]           → core learning cards (count driven by daily_core_article_count)
      - curiosity_insights[] → exactly 2 curiosity/exploration cards

    Multiple generations per calendar day are allowed and encouraged.
    Same-day packages are labelled Day X.1, X.2 … by the frontend.

    Raises ValueError if the project is not found.
    Returns the saved package dict.
    """
    project = get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id!r} not found")

    if _precomputed_day_number is not None:
        day_number = _precomputed_day_number
    else:
        # Exclude generating stubs — they already occupy their day_number slot.
        from ..utils.db import get_connection as _gc
        with _gc() as _conn:
            _row = _conn.execute(
                "SELECT COALESCE(MAX(day_number), 0) AS max_day FROM project_insights "
                "WHERE project_id = ? AND status != 'generating'",
                (project_id,),
            ).fetchone()
        day_number = (_row["max_day"] if _row else 0) + 1
    display_label, _ = _compute_next_display_label(project_id)
    keywords                 = project.get("keywords") or []
    difficulty               = project.get("difficulty", "intermediate")
    daily_core_article_count = project.get("daily_core_article_count") or 4

    # ── Load learning progression ─────────────────────────────────────────────
    try:
        from .progression_service import get_progression
        progression           = get_progression(project_id)
        suggested_next_topics = progression.get("suggested_next_topics", [])
    except Exception:
        suggested_next_topics = []

    # ── Load learning memory + filter suggestions for semantic novelty ─────────
    learning_memory: dict = {}
    try:
        from .learning_memory_service import get_memory, filter_novel_topics
        learning_memory       = get_memory(project_id)
        if suggested_next_topics:
            suggested_next_topics = filter_novel_topics(
                suggested_next_topics, learning_memory, max_results=6,
            )
    except Exception:
        logger.warning("[project_service] learning memory load failed for %s (non-fatal)", project_id)

    # ── Knowledge state — compressed learning history (replaces package history) ─
    knowledge_state: dict = {}
    try:
        from .knowledge_state_service import get_state
        knowledge_state = get_state(project_id)
    except Exception:
        logger.warning("[project_service] knowledge state load failed for %s (non-fatal)", project_id)

    # ── Intent profile — foundation for editorial decisions ───────────────────
    intent_profile: dict | None = None
    try:
        from .intent_profile_service import get_intent_profile, generate_intent_profile, save_intent_profile
        intent_profile = get_intent_profile(project_id)
        if intent_profile is None:
            # Legacy project or profile generation failed at creation — generate now
            intent_profile = generate_intent_profile(
                project["name"], project.get("description", ""), keywords, difficulty
            )
            save_intent_profile(project_id, intent_profile)
    except Exception:
        logger.warning("[project_service] intent profile load failed for %s (non-fatal)", project_id)

    # ── Phase 4.7: Load quality feedback from previous evaluation ────────────
    quality_feedback: str | None = None
    try:
        from .learning_evaluator import get_quality_feedback_block
        quality_feedback = get_quality_feedback_block(project_id) or None
    except Exception:
        logger.debug("[project_service] quality feedback load failed (non-fatal)")

    # ── Phase 4.5: Feed Intelligence Layer ───────────────────────────────────
    # Determine what to learn next, then retrieve articles that support it.
    # Falls back to keyword-based retrieval when the knowledge graph is empty.
    _stage = learning_memory.get("progression_stage", "foundation") if learning_memory else "foundation"
    intelligence_plan = None
    intelligence_context: str | None = None
    try:
        from .feed_intelligence import build_feed_intelligence
        intelligence_plan = build_feed_intelligence(
            project_id=project_id,
            project=project,
            progression_stage=_stage,
        )
        if intelligence_plan:
            intelligence_context = intelligence_plan.intelligence_summary or None
    except Exception:
        logger.debug("[project_service] feed_intelligence unavailable (non-fatal)")

    # ── Retrieve articles — always via retrieval_planner ─────────────────────
    # The intelligence plan's concept targets feed INTO the planner as enriched
    # knowledge state — they never bypass retrieval_planner.plan().
    retrieval_plan: dict | None = None
    _planner_called    = False
    _queries_generated = 0

    # Enrich knowledge state: prepend concept targets as highest-priority active topics
    _planning_ks = knowledge_state
    if intelligence_plan and intelligence_plan.concept_targets:
        _concept_topics  = [ct.concept for ct in intelligence_plan.concept_targets]
        _planning_ks     = dict(knowledge_state or {})
        _existing_active = list(_planning_ks.get("active_topics") or [])
        _planning_ks["active_topics"] = _concept_topics + [
            t for t in _existing_active if t not in _concept_topics
        ]

    # ── Journey plan — today's focus for retrieval planning (Phase 2b-i) ────────
    today_plan: dict | None = None
    try:
        from .journey_planner_service import get_today_plan as _get_today_plan
        today_plan = _get_today_plan(
            project_id=project_id,
            day_number=day_number,
            intent_profile=intent_profile,
            keywords=keywords,
        )
        logger.info(
            "[project_service] %s day=%d [journey_plan] shape_hint=%s",
            project_id, day_number,
            "fixed_seq" if today_plan and "focus" in today_plan else
            "rotating"  if today_plan and "theme" in today_plan else
            "fallback",
        )
    except Exception:
        logger.warning("[project_service] journey plan load failed for %s (non-fatal)", project_id)

    try:
        from .retrieval_planner import plan as _plan_retrieval
        retrieval_plan = _plan_retrieval(
            intent_profile, _planning_ks, keywords, project["name"],
            today_plan=today_plan,
        )
        _planner_called    = True
        _queries_generated = (
            len(retrieval_plan.get("core_queries",        [])) +
            len(retrieval_plan.get("adjacent_queries",    [])) +
            len(retrieval_plan.get("serendipity_queries", []))
        )
        logger.info(
            "[project_service] %s day=%d [retrieval_planner] core=%d adj=%d serendipity=%d",
            project_id, day_number,
            len(retrieval_plan.get("core_queries",        [])),
            len(retrieval_plan.get("adjacent_queries",    [])),
            len(retrieval_plan.get("serendipity_queries", [])),
        )
        logger.info(
            "[project_service] %s day=%d [retrieval_queries] core=%s",
            project_id, day_number,
            retrieval_plan.get("core_queries", []),
        )
    except Exception:
        logger.warning("[project_service] retrieval_planner failed for %s (non-fatal)", project_id)

    logger.info(
        "[RETRIEVAL PATH] project_id=%s intent_profile_loaded=%s knowledge_state_loaded=%s"
        " planner_called=%s queries_generated=%d",
        project_id,
        intent_profile   is not None,
        knowledge_state  is not None,
        _planner_called,
        _queries_generated,
    )

    core_articles = _fetch_core_articles(
        project["name"], keywords, suggested_next_topics, retrieval_plan,
    )
    curiosity_articles = _fetch_curiosity_articles(project["name"], keywords, retrieval_plan)

    # ── Supplementary trusted-domain search (rotating_theme only) ─────────────
    # Fires 1-2 additional targeted searches restricted to today_plan.trusted_sources
    # and merges results into core_articles BEFORE ranking — actual retrieval step,
    # not a ranking-time bonus.  Skipped for fixed_sequence (no trusted_sources field).
    _tp_trusted = (today_plan.get("trusted_sources") or []) if today_plan else []
    _tp_is_rotating = bool(today_plan and "theme" in today_plan and "focus" not in today_plan)
    if _tp_is_rotating and _tp_trusted:
        try:
            from .tavily_service import _search_raw as _tavily_search_raw, normalize_query as _nq
            _sup_queries = (retrieval_plan.get("core_queries") or [])[:2] if retrieval_plan else [project["name"]]
            _core_seen: set[str] = {a.get("url", "") for a in core_articles}
            _sup_added: list[dict] = []
            for _sq in _sup_queries:
                for _a in _tavily_search_raw(
                    _nq(_sq),
                    max_results=5,
                    search_depth="basic",
                    include_domains=_tp_trusted,
                ):
                    _url = _a.get("url", "")
                    if _url and _url not in _core_seen:
                        _a.setdefault("retrieval_query", _sq)
                        _sup_added.append(_a)
                        _core_seen.add(_url)
            core_articles = core_articles + _sup_added
            logger.info(
                "[project_service] %s day=%d [trusted-domain-search] trusted=%s queries=%d added=%d total_core=%d",
                project_id, day_number, _tp_trusted, len(_sup_queries), len(_sup_added), len(core_articles),
            )
        except Exception as _sup_exc:
            logger.warning(
                "[project_service] supplementary trusted-domain search failed for %s: %s",
                project_id, _sup_exc,
            )

    logger.info(
        "[project_service] %s day=%d [planned retrieval] core=%d curiosity=%d",
        project_id, day_number, len(core_articles), len(curiosity_articles),
    )
    logger.info(
        "[project_service] %s day=%d [core_article_titles] %s",
        project_id, day_number,
        [a.get("title", "")[:70] for a in core_articles[:6]],
    )

    # ── Validate articles — drop off-topic retrievals before prompt ──────────
    _retrieved_core      = len(core_articles)       # captured before validation for metrics
    _retrieved_curiosity = len(curiosity_articles)
    try:
        from .retrieval_validator import filter_articles as _validate_articles
        _proj_name = project.get("name", "")
        _proj_desc = project.get("description", "")
        core_articles      = _validate_articles(
            core_articles, intent_profile, knowledge_state, keywords,
            mode="core", project_id=project_id,
            project_name=_proj_name, project_description=_proj_desc,
            min_required=8,
        )
        curiosity_articles = _validate_articles(
            curiosity_articles, intent_profile, knowledge_state, keywords,
            mode="serendipity", project_id=project_id,
            project_name=_proj_name, project_description=_proj_desc,
            min_required=4,
        )
        logger.info(
            "[project_service] %s day=%d [validator] core %d→%d curiosity %d→%d",
            project_id, day_number,
            _retrieved_core, len(core_articles),
            _retrieved_curiosity, len(curiosity_articles),
        )
    except Exception:
        logger.warning("[project_service] retrieval_validator failed for %s (non-fatal)", project_id)

    # ── Near-duplicate suppression (keeps highest-validated source per story) ──
    try:
        from .similarity_service import deduplicate_ranked as _dedup_ranked
        _pre_core = len(core_articles)
        core_articles      = _dedup_ranked(core_articles)
        curiosity_articles = _dedup_ranked(curiosity_articles)
        if len(core_articles) < _pre_core:
            logger.info(
                "[project_service] %s day=%d [near-dedup] core %d->%d",
                project_id, day_number, _pre_core, len(core_articles),
            )
    except Exception:
        logger.warning("[project_service] deduplicate_ranked failed for %s (non-fatal)", project_id)

    # ── Phase 9.3.1 + 9.3.2: Source Intelligence Layer ───────────────────────
    # Moved BEFORE ranking so signal_density / source_strength are available
    # to the ranker for T4 (quality amplifier) and T5 (tie-breaker) scoring.
    # Deterministic enrichment — no LLM calls. Mutates in-place. Non-fatal.
    import time as _t5_time
    _t5_pre_enrich = _t5_time.monotonic()
    _t5_pre_sample = [
        (a.get("url", "")[:50], a.get("signal_density"), a.get("source_strength"))
        for a in core_articles[:2]
    ]
    logger.info("[PHASE2B-ITEM5] pre_enrich ts=%.3f sample=%s", _t5_pre_enrich, _t5_pre_sample)
    try:
        from .source_intelligence_service import enrich_articles as _enrich_intel
        _enrich_intel(core_articles)
        _enrich_intel(curiosity_articles)
    except Exception:
        logger.warning("[project_service] source_intelligence failed for %s (non-fatal)", project_id)
    _t5_post_enrich = _t5_time.monotonic()
    _t5_post_sample = [
        (a.get("url", "")[:50], a.get("signal_density"), a.get("source_strength"))
        for a in core_articles[:2]
    ]
    logger.info(
        "[PHASE2B-ITEM5] post_enrich ts=%.3f elapsed_ms=%.1f sample=%s",
        _t5_post_enrich, (_t5_post_enrich - _t5_pre_enrich) * 1000, _t5_post_sample,
    )

    # ── Rank articles using learning context (best learning article wins) ────
    _t5_pre_rank = _t5_time.monotonic()
    _t5_rank_input_sample = [
        (a.get("url", "")[:50], a.get("signal_density"), a.get("source_strength"))
        for a in core_articles[:2]
    ]
    logger.info(
        "[PHASE2B-ITEM5] pre_rank ts=%.3f sample=%s",
        _t5_pre_rank, _t5_rank_input_sample,
    )
    try:
        from .source_ranker import rank_articles as _rank_articles
        _recent_sources: dict[str, int] = {}
        try:
            from .article_provenance_service import get_recent_source_usage as _get_recent
            _recent_sources = _get_recent(project_id, window_days=7)
        except Exception:
            pass   # non-fatal — penalty skipped silently

        _lc = {
            "intent_profile":       intent_profile,
            "knowledge_state":      knowledge_state,
            "keywords":             keywords,
            "recent_sources":       _recent_sources,
            "project_description":  (project.get("description") or "").strip(),
            "trusted_sources":      (today_plan.get("trusted_sources") or []) if today_plan else [],
        }
        core_articles      = _rank_articles(core_articles,      query=project["name"],
                                            top_n=8, mode="feed", learning_context=_lc,
                                            min_domains=4)
        curiosity_articles = _rank_articles(curiosity_articles, query=project["name"],
                                            top_n=4, mode="feed", learning_context=_lc,
                                            min_domains=3)
        logger.info(
            "[project_service] %s day=%d [learning_rank] core=%d curiosity=%d",
            project_id, day_number, len(core_articles), len(curiosity_articles),
        )
    except Exception:
        logger.warning("[project_service] learning ranking failed for %s (non-fatal)", project_id)
    logger.info(
        "[PHASE2B-ITEM5] post_rank elapsed_ms=%.1f",
        (_t5_time.monotonic() - _t5_pre_rank) * 1000,
    )

    # ── Persist retrieval provenance before generation ────────────────────────
    _feed_date = datetime.now(timezone.utc).strftime(_DATE_FMT)
    try:
        from .article_provenance_service import persist as _persist_provenance
        _core_qs     = (retrieval_plan.get("core_queries", []) + retrieval_plan.get("adjacent_queries", [])) if retrieval_plan else [project["name"]]
        _serendy_qs  = retrieval_plan.get("serendipity_queries", []) if retrieval_plan else [project["name"]]
        _persist_provenance(project_id, _feed_date, core_articles,      "core",        _core_qs)
        _persist_provenance(project_id, _feed_date, curiosity_articles,  "serendipity", _serendy_qs)
    except Exception:
        logger.warning("[project_service] provenance persist failed for %s (non-fatal)", project_id)

    # ── Enforce minimum source requirement ───────────────────────────────────
    # Core articles are mandatory — feed generation cannot proceed without evidence.
    if not core_articles:
        logger.warning(
            "[project_service] %s day=%d: zero core articles after validation — retrying with keyword fallback",
            project_id, day_number,
        )
        try:
            _rb_kw  = " ".join(keywords[:4]) if keywords else project["name"]
            _rb_qs  = [
                f"{project['name']} {_rb_kw} 2025 2026",
                f"{project['name']} analysis depth overview",
            ]
            _rb: list[dict] = []
            for _q in _rb_qs:
                _rb.extend(_search_articles(_q))
            _rb = _dedup_articles(_rb)
            if _rb:
                from .source_ranker import rank_articles as _rerank
                core_articles = _rerank(
                    _rb, query=project["name"], top_n=8, mode="feed",
                    learning_context={
                        "intent_profile":  intent_profile,
                        "knowledge_state": knowledge_state,
                        "keywords":        keywords,
                    },
                    min_domains=4,
                )
                logger.info(
                    "[project_service] %s day=%d: retry produced %d core articles",
                    project_id, day_number, len(core_articles),
                )
        except Exception as _rbe:
            logger.warning("[project_service] %s core retrieval retry failed: %s", project_id, _rbe)

    if not core_articles:
        raise RuntimeError(
            "No source articles could be retrieved for this project after retry. "
            "Feed generation requires evidence — please try again in a few minutes."
        )

    # Curiosity retry — non-fatal; zero curiosity articles = no curiosity cards.
    if not curiosity_articles:
        logger.info(
            "[project_service] %s day=%d: zero curiosity articles — retrying serendipity queries",
            project_id, day_number,
        )
        try:
            import random as _rand
            _ca = _rand.sample(_CURIOSITY_QUERIES, k=min(2, len(_CURIOSITY_QUERIES)))
            _ckw  = " ".join(keywords[:2]) if keywords else project["name"]
            _cqs  = [q.format(project_name=project["name"], kw=_ckw) for q in _ca]
            _cr: list[dict] = []
            for _q in _cqs:
                _cr.extend(_search_articles(_q))
            curiosity_articles = _dedup_articles(_cr)
            logger.info(
                "[project_service] %s day=%d: curiosity retry produced %d articles",
                project_id, day_number, len(curiosity_articles),
            )
        except Exception:
            pass   # curiosity is best-effort; proceed without

    # ── Curiosity strategy (Phase 4.4) ────────────────────────────────────────
    curiosity_directives: str | None = None
    try:
        from .curiosity_orchestrator import get_curiosity_directives
        curiosity_directives = get_curiosity_directives(project_id) or None
    except Exception:
        logger.debug("[project_service] curiosity_orchestrator unavailable (non-fatal)")

    # ── Story-level duplicate enforcement — before article assignment ────────
    # Groups core articles by retrieval_query (same search = same story) and by
    # title token overlap >= 0.35.  Keeps highest-ranked per cluster so each
    # article slot teaches a distinct concept.
    try:
        from .similarity_service import deduplicate_by_story as _dedup_by_story
        _story_pre = len(core_articles)
        core_articles = _dedup_by_story(core_articles)
        _story_removed = _story_pre - len(core_articles)
        logger.info(
            "[DUPLICATE ENFORCEMENT] project_id=%s candidate_count=%d removed=%d remaining=%d",
            project_id, _story_pre, _story_removed, len(core_articles),
        )
    except Exception:
        logger.warning("[project_service] story dedup failed for %s (non-fatal)", project_id)

    # URLs the LLM is allowed to cite — anything else is an invented/fabricated link.
    _allowed_urls: frozenset[str] = frozenset(
        a.get("url", "").rstrip("/").lower()
        for a in (core_articles + curiosity_articles)
        if a.get("url")
    )

    # ── Article source plans — pre-assign sources before LLM generation ─────────
    _article_plan_block: str | None = None
    _frame_hint:         str | None = None
    try:
        from .article_plan_service import build_article_plans, validate_plans, plans_to_prompt_block
        _plans = build_article_plans(core_articles, daily_core_article_count)
        _ok, _plan_errs = validate_plans(_plans)
        if not _ok:
            logger.warning("[project_service] %s article plan issues: %s", project_id, _plan_errs)
        _assigned_src = sum(len(p.assigned_sources) for p in _plans)
        _backup_src   = sum(len(p.backup_sources)   for p in _plans)
        logger.info(
            "[SOURCE ASSIGNMENT] project_id=%s day=%d slots=%d assigned=%d backup=%d",
            project_id, day_number, len(_plans), _assigned_src, _backup_src,
        )
        _frame_hint = (today_plan.get("frame_hint") or None) if today_plan else None
        _article_plan_block = plans_to_prompt_block(_plans, core_articles, frame_hint=_frame_hint)
    except Exception:
        logger.warning("[project_service] article_plan_service failed for %s (non-fatal)", project_id)

    # ── Build prompt — active budget control via ModelAwareAssembler ─────────
    from ..prompts.project_insight_prompt import make_daily_package_composer
    from ..prompts.model_aware_assembler import ModelAwareAssembler
    from ..config import GROQ_MODEL as _ACTIVE_MODEL

    # Phase 9.3.3B — Calibrated article budget via probe-measured overhead.
    # Overhead is measured from a real (empty-article) composer call — not guessed.
    #
    # _BUDGET_SAFETY_BUFFER: reserved for tokenizer variance, provider jitter,
    #   and future prompt additions. Small fixed margin, not a proxy for overhead.
    # _MIN_ARTICLE_BUDGET: floor — even at maximum overhead, LLM needs some context.
    _BUDGET_SAFETY_BUFFER  = 300
    _MIN_ARTICLE_BUDGET    = 800

    _pre_budget            = 0   # effective model+provider budget (0 = unknown)
    _actual_overhead       = 0   # measured non-article prompt tokens (0 = unknown)
    _article_budget_tokens = _MIN_ARTICLE_BUDGET

    try:
        from ..prompts.budget_allocator import BudgetAllocator as _BA
        from .model_registry import get_model_config as _gmc
        _pre_cfg    = _gmc(_ACTIVE_MODEL)
        _pre_budget = _BA(_pre_cfg).compute_budget(expected_output_tokens=2000)
        _pre_tier   = _pre_cfg.default_provider_tier
        if _pre_tier:
            _pre_tpm = _pre_cfg.tier_limits.get(_pre_tier, {}).get("tpm", 0)
            if _pre_tpm:
                from .model_registry import PROVIDER_SAFETY_FACTOR as _PSF
                _pre_budget = min(_pre_budget, int(_pre_tpm * _PSF))

        # Probe: build composer with empty articles to measure actual non-article overhead.
        # All dynamic sections (knowledge_state, blueprint, intent_profile, article_plan)
        # are passed so their real sizes are captured — overhead varies per request.
        _probe = make_daily_package_composer(
            project_name=project["name"],
            keywords=keywords,
            difficulty=difficulty,
            day_number=day_number,
            display_label=display_label,
            core_articles=[],
            curiosity_articles=[],
            daily_core_article_count=daily_core_article_count,
            curiosity_directives=curiosity_directives,
            intelligence_context=intelligence_context,
            quality_feedback=quality_feedback,
            intent_profile=intent_profile,
            knowledge_state=knowledge_state or None,
            article_plan_block=_article_plan_block,
            article_budget_tokens=0,
        )
        _ARTICLE_SECTION_NAMES = frozenset({"core_articles", "curiosity_articles"})
        _actual_overhead = sum(
            s.tokens for s in _probe._sections
            if s.name not in _ARTICLE_SECTION_NAMES
        )
        _article_budget_tokens = max(
            _MIN_ARTICLE_BUDGET,
            _pre_budget - _actual_overhead - _BUDGET_SAFETY_BUFFER,
        )
    except Exception:
        logger.warning(
            "[project_service] %s budget calibration failed (non-fatal) — using minimum %d",
            project_id, _MIN_ARTICLE_BUDGET,
        )

    # Format articles now — budget is calibrated.
    # Formatting here (not inside the composer) gives us compression meta for logging.
    from ..prompts.article_compressor import ArticleCompressor as _AC_svc
    _svc_compressor   = _AC_svc()
    _core_budget_tok  = int(_article_budget_tokens * 0.70)
    _curio_budget_tok = _article_budget_tokens - _core_budget_tok
    _core_str,  _core_meta  = _svc_compressor.format_intel_batch(
        core_articles, "CORE", _core_budget_tok,
    )
    _curio_str, _curio_meta = _svc_compressor.format_intel_batch(
        curiosity_articles, "CURIOSITY", _curio_budget_tok,
    )

    # Task 6 — Budget calibration observability log (one per package generation).
    _all_compress_meta = _core_meta + _curio_meta
    _level_counts: dict[str, int] = {}
    for _m in _all_compress_meta:
        _lv = _m["level_selected"]
        _level_counts[_lv] = _level_counts.get(_lv, 0) + 1
    _dist_str = " ".join(f"{k}={v}" for k, v in sorted(_level_counts.items()))
    logger.info(
        "[budget_calibration] project=%s day=%d  "
        "effective=%d  overhead=%d  safety=%d  article=%d  "
        "compression=[%s]",
        project_id, day_number,
        _pre_budget, _actual_overhead, _BUDGET_SAFETY_BUFFER, _article_budget_tokens,
        _dist_str or "no_articles",
    )

    # ── Phase 9.3.4C: feature-flag routing — single-call vs multi-call ──────────
    try:
        from ..config import MULTI_CALL_GENERATION as _MULTI_CALL
    except ImportError:
        _MULTI_CALL = False

    if _MULTI_CALL:
        from .generation_orchestrator import run_generation_orchestrator as _run_orch
        try:
            raw = _run_orch(
                project_name             = project["name"],
                keywords                 = keywords,
                difficulty               = difficulty,
                day_number               = day_number,
                display_label            = display_label,
                daily_core_article_count = daily_core_article_count,
                core_articles            = core_articles,
                curiosity_articles       = curiosity_articles,
                article_budget_tokens    = _article_budget_tokens,
                project_id               = project_id,
                intent_profile           = intent_profile,
                knowledge_state          = knowledge_state or None,
                curiosity_directives     = curiosity_directives,
                intelligence_context     = intelligence_context,
                quality_feedback         = quality_feedback,
                article_plan_block       = _article_plan_block,
                frame_hint               = _frame_hint,
            )
        except Exception as _e:
            logger.error("[project_service] multi-call generation failed for %s: %s", project_id, _e)
            raise RuntimeError(str(_e)) from _e
    else:
        _composer = make_daily_package_composer(
            project_name=project["name"],
            keywords=keywords,
            difficulty=difficulty,
            day_number=day_number,
            display_label=display_label,
            core_articles=core_articles,
            curiosity_articles=curiosity_articles,
            daily_core_article_count=daily_core_article_count,
            curiosity_directives=curiosity_directives,
            intelligence_context=intelligence_context,
            quality_feedback=quality_feedback,
            intent_profile=intent_profile,
            knowledge_state=knowledge_state or None,
            article_plan_block=_article_plan_block,
            core_article_text=_core_str,
            curiosity_article_text=_curio_str,
        )

        prompt, _assembly = ModelAwareAssembler.build(
            _composer, _ACTIVE_MODEL, expected_output_tokens=2000
        )

        # ── Task 9: Structured feed-generation budget observability log ───────────
        # One concise structured log per feed generation.  All budget dimensions
        # visible in a single line for easy filtering/alerting.
        from .model_registry import get_model_config as _get_cfg_obs
        _obs_cfg        = _get_cfg_obs(_ACTIVE_MODEL)
        _obs_tier       = _obs_cfg.default_provider_tier or ""
        _obs_tpm        = (_obs_cfg.tier_limits.get(_obs_tier, {}).get("tpm") or 0) if _obs_tier else 0
        _obs_prov_limit = int(_obs_tpm * 0.875) if _obs_tpm else 0
        _repair_steps   = (
            ", ".join(s.step_name for s in _assembly.degradation.steps_applied)
            if _assembly.degraded and _assembly.degradation
            else "none"
        )
        _util_pct = (
            _assembly.final_tokens / _assembly.effective_budget * 100
            if _assembly.effective_budget else 0.0
        )
        logger.info(
            "[feed_budget] op=package_generation/day_%d/%s  "
            "model_limit=%d  provider_limit=%d  effective_limit=%d  "
            "system_reserve=23  output_reserve=2000  "
            "prompt_tokens=%d  repair=%s  final_tokens=%d  util=%.1f%%  fits=%s",
            day_number, project_id[:8],
            _assembly.prompt_budget,    # model context budget (e.g. 92,400)
            _obs_prov_limit,            # provider TPM safe budget (e.g. 10,500)
            _assembly.effective_budget, # enforced ceiling = min(above two)
            _assembly.original_tokens,
            _repair_steps,
            _assembly.final_tokens,
            _util_pct,
            _assembly.fits,
        )
        for _w in _assembly.warnings:
            logger.warning("[feed_budget] %s", _w)

        # Raise if assembler could not fit the prompt after full degradation
        if not _assembly.fits:
            raise RuntimeError(
                f"Prompt exceeds effective budget after full degradation: "
                f"{_assembly.final_tokens:,} tokens > {_assembly.effective_budget:,} available "
                f"(model={_assembly.prompt_budget:,}). "
                "Reduce article count or simplify project keywords."
            )

        try:
            from .writer_provider_router import route_writer_call, format_articles_full
            from ..prompts.project_insight_prompt import PromptContext as _PC, build_batch_prompt as _bbp_sc
            # Build full Gemini prompt: same prompt structure, uncompressed articles
            _full_core_text  = format_articles_full(core_articles,      "CORE")
            _full_curio_text = format_articles_full(curiosity_articles,  "CURIOSITY")
            _full_ctx_sc = _PC(
                project_name             = project["name"],
                keywords                 = keywords,
                difficulty               = difficulty,
                day_number               = day_number,
                display_label            = display_label,
                daily_core_article_count = daily_core_article_count,
                intent_profile           = intent_profile,
                knowledge_state          = knowledge_state,
                curiosity_directives     = curiosity_directives,
                intelligence_context     = intelligence_context,
                quality_feedback         = quality_feedback,
                article_plan_block       = _article_plan_block,
                frame_hint               = _frame_hint,
            )
            _full_comp_sc   = _bbp_sc(_full_ctx_sc, batch_plan=None,
                                      core_article_text=_full_core_text,
                                      curiosity_article_text=_full_curio_text)
            _gemini_prompt_sc = _full_comp_sc.build()
            logger.info(
                "[writer_router] single-call  gemini_prompt_tokens~=%d  groq_prompt_tokens=%d",
                len(_gemini_prompt_sc) // 4, _assembly.final_tokens,
            )
            from .grok_service import ask_grok as _ask_grok_sc
            text, _sc_provider = route_writer_call(
                _gemini_prompt_sc,
                lambda: _ask_grok_sc(prompt, json_mode=True),
                json_mode=True,
            )
            raw  = _extract_json(text)
        except Exception as e:
            logger.error("[project_service] generation failed for %s: %s", project_id, e)
            raise RuntimeError(str(e)) from e

    # Validate that the model returned actual content before saving anything
    if not raw.get("insights"):
        logger.error("[project_service] generation returned no insight cards for %s", project_id)
        raise RuntimeError("Generation produced no insight cards — please try again.")

    # ── Beginner calibration check + single retry ─────────────────────────────
    if difficulty == "beginner" and not _MULTI_CALL:
        jargon_hits = _score_beginner_calibration(raw)
        if jargon_hits > _BEGINNER_JARGON_THRESHOLD:
            logger.warning(
                "[project_service] beginner calibration failed for %s — jargon_hits=%d, retrying",
                project_id, jargon_hits,
            )
            retry_addendum = (
                "\n\n══════════════════════════════════════\n"
                "CALIBRATION RETRY — SIMPLIFY FURTHER\n"
                "══════════════════════════════════════\n"
                "The previous generation was too abstract for beginner level.\n"
                "Apply MAXIMUM conceptual laddering:\n"
                "  • Every technical term needs an immediate plain-English definition.\n"
                "  • Open every summary with a concrete, picturable anchor — not an abstraction.\n"
                "  • Do NOT use: value chain, supply fragility, dependency risk, geopolitical,\n"
                "    competitive dynamics, regulatory framework — without first establishing\n"
                "    the concrete situation in plain language.\n"
                "  • If in doubt, use an analogy first, then name the domain concept."
            )
            # Budget instrumentation for retry (prompt is larger due to addendum)
            try:
                from .token_budget import estimate_total_request, BudgetReport, log_budget_report
                from .model_registry import get_model_config
                from ..config import GROQ_MODEL as _MODEL_R
                _retry_prompt = prompt + retry_addendum
                _cfg_r        = get_model_config(_MODEL_R)
                _retry_tok    = estimate_total_request(prompt=_retry_prompt)
                _od_tpm_r     = _cfg_r.tier_limits.get("on_demand", {}).get("tpm")
                _ret_warn: list[str] = []
                if _od_tpm_r and _retry_tok > _od_tpm_r:
                    _ret_warn.append(
                        f"RETRY EXCEEDS ON_DEMAND TIER LIMIT: {_retry_tok:,} > {_od_tpm_r:,} "
                        f"(delta: +{_retry_tok - _od_tpm_r:,})"
                    )
                log_budget_report(BudgetReport(
                    operation        = f"package_generation_retry/day_{day_number}/{project_id[:8]}",
                    model_name       = _MODEL_R,
                    context_window   = _cfg_r.context_window,
                    safe_budget      = _cfg_r.prompt_budget,
                    output_reserve   = _cfg_r.output_budget,
                    prompt_tokens    = _retry_tok,
                    remaining_budget = _cfg_r.prompt_budget - _retry_tok,
                    utilization_pct  = (_retry_tok / _cfg_r.prompt_budget * 100) if _cfg_r.prompt_budget > 0 else 0.0,
                    sections         = {"prompt_with_addendum": _retry_tok},
                    warnings         = _ret_warn,
                ), logger)
            except Exception:
                logger.debug("[project_service] retry budget instrumentation failed (non-fatal)", exc_info=True)

            try:
                from .grok_service import ask_grok as _ask_grok_retry
                retry_text = _ask_grok_retry(prompt + retry_addendum, json_mode=True)
                retry_raw  = _extract_json(retry_text)
                if retry_raw.get("insights"):
                    raw = retry_raw
                    logger.info("[project_service] beginner calibration retry succeeded for %s", project_id)
                else:
                    logger.warning("[project_service] beginner calibration retry returned no insights — using original")
            except Exception as retry_err:
                logger.warning("[project_service] beginner calibration retry failed for %s: %s (using original)", project_id, retry_err)

    # Guarantee curiosity_insights key exists (older LLM outputs may omit it)
    if "curiosity_insights" not in raw:
        raw["curiosity_insights"] = []

    # Synthesise flat fields from blocks so downstream consumers (chat, export,
    # graph, search) keep working without schema changes.
    for _card in (raw.get("insights") or []) + (raw.get("curiosity_insights") or []):
        _blocks = _card.get("blocks") or []
        if _blocks:
            _card.setdefault("educational_explanation", next(
                (b["content"] for b in _blocks if b.get("type") in ("explanation", "insight")), ""
            ))
            _card.setdefault("why_it_matters", next(
                (b["content"] for b in _blocks if b.get("type") == "mechanism"), ""
            ))

    # ── Source grounding: validate + repair + enforce (parser layer) ─────────
    from .source_grounding_service import ground_package as _ground_package
    _allowed_titles: dict[str, str] = {
        a.get("url", "").rstrip("/").lower(): a.get("title", "")
        for a in (core_articles + curiosity_articles)
        if a.get("url")
    }
    raw, _grounding_violations = _ground_package(
        raw_package    = raw,
        allowed_urls   = _allowed_urls,
        allowed_titles = _allowed_titles,
        project_id     = project_id,
        day_number     = day_number,
    )
    if _grounding_violations:
        logger.warning(
            "[project_service] %s day=%d: %d source grounding violation(s)",
            project_id, day_number, len(_grounding_violations),
        )

    # ── Curiosity hallucination check (pattern-only, no LLM) ─────────────────────
    _curio_cards = raw.get("curiosity_insights") or []
    if _curio_cards and curiosity_articles:
        _cited_curio_urls: set[str] = {
            link.get("url", "")
            for _ccard in _curio_cards
            for link in (_ccard.get("source_links") or [])
            if link.get("url")
        }
        _backup_pool = [
            a for a in curiosity_articles
            if a.get("url") and a["url"] not in _cited_curio_urls
        ]
        _kw_tokens = {w.lower() for kw in (keywords or [])[:5] for w in kw.split() if len(w) > 4}
        for _ccard in _curio_cards:
            _links = _ccard.get("source_links") or []
            if not _links:
                continue
            _cu = (_links[0].get("url") or "").strip()
            _ct = (_links[0].get("title") or "").strip()
            _bare_url   = bool(re.match(r'^https?://[^/]+/?$', _cu))
            _dots_title = "..." in _ct
            _kw_miss    = bool(_kw_tokens) and not any(w in _ct.lower() for w in _kw_tokens)
            if _bare_url or _dots_title or _kw_miss:
                _rescue = next(
                    (a for a in _backup_pool if a.get("url") and a["url"] not in _cited_curio_urls),
                    None,
                )
                if _rescue:
                    _ccard["source_links"] = [{"title": _rescue.get("title", ""), "url": _rescue["url"]}]
                    _cited_curio_urls.add(_rescue["url"])
                    _backup_pool = [a for a in _backup_pool if a.get("url") != _rescue["url"]]
                    logger.warning(
                        "[project_service] %s day=%d curiosity card=%s: hallucination pattern"
                        " (bare=%s dots=%s kw_miss=%s) — rescued url=%s",
                        project_id, day_number, _ccard.get("id", "?"),
                        _bare_url, _dots_title, _kw_miss, _rescue["url"],
                    )
                else:
                    logger.warning(
                        "[project_service] %s day=%d curiosity card=%s: hallucination pattern"
                        " (bare=%s dots=%s kw_miss=%s) — no backup; url=%r title=%r",
                        project_id, day_number, _ccard.get("id", "?"),
                        _bare_url, _dots_title, _kw_miss, _cu, _ct,
                    )

    package = {
        "id":           None,
        "project_id":   project_id,
        "day_number":   day_number,
        "generated_at": _now(),
        **raw,
    }

    pkg_id       = _save_package(project_id, day_number, package, stub_id=_stub_id)
    package["id"] = pkg_id

    # Mark provenance records for URLs that appear in the generated package (non-fatal)
    try:
        from .article_provenance_service import mark_selected as _mark_selected
        _selected_urls = {
            link.get("url", "")
            for card in (package.get("insights", []) + package.get("curiosity_insights", []))
            for link in (card.get("source_links") or [])
            if link.get("url")
        }
        _mark_selected(project_id, pkg_id, list(_selected_urls))
    except Exception:
        logger.warning("[project_service] provenance mark_selected failed for %s (non-fatal)", project_id)

    # Retrieval quality metrics — per-package diagnostics (non-fatal)
    try:
        from .retrieval_metrics_service import (
            compute as _compute_metrics,
            store   as _store_metrics,
            log_metrics as _log_metrics,
            audit   as _audit_metrics,
            log_audit   as _log_audit,
        )
        _metrics = _compute_metrics(
            package,
            retrieved_count=_retrieved_core + _retrieved_curiosity,
            core_articles=core_articles,
            curiosity_articles=curiosity_articles,
        )
        _store_metrics(project_id, pkg_id, _metrics)
        _log_metrics(project_id, pkg_id, _metrics, logger)
        _audit_report = _audit_metrics(package, _allowed_urls, core_articles, curiosity_articles)
        _log_audit(project_id, pkg_id, _audit_report, logger)
    except Exception:
        logger.warning("[project_service] retrieval metrics failed for %s (non-fatal)", project_id)

    # Update knowledge state — compressed continuity (non-fatal)
    try:
        from .knowledge_state_service import update_state as _update_ks
        _update_ks(project_id, package)
    except Exception:
        logger.warning("[project_service] knowledge state update failed for %s (non-fatal)", project_id)

    # Auto-update learning progression (non-fatal)
    try:
        from .progression_service import update_progression_from_package
        update_progression_from_package(project_id, package)
    except Exception:
        logger.warning("[project_service] progression update failed for %s (non-fatal)", project_id)

    # Auto-update learning memory — semantic coverage tracking (non-fatal)
    try:
        from .learning_memory_service import update_from_package as _update_memory
        _update_memory(project_id, package)
    except Exception:
        logger.warning("[project_service] learning memory update failed for %s (non-fatal)", project_id)

    # Phase 4.7: evaluate learning quality and store for next generation (non-fatal)
    try:
        from .learning_evaluator import evaluate as _evaluate, store_evaluation as _store_eval
        _report = _evaluate(project_id, package=package)
        _store_eval(_report)
        logger.info(
            "[project_service] learning quality score for %s day=%d: %.2f",
            project_id, day_number, _report.overall_score,
        )
    except Exception:
        logger.warning("[project_service] quality evaluation failed for %s (non-fatal)", project_id)

    return package


def generate_all_projects() -> dict:
    """
    Run daily generation for every project.  Called by the scheduler.

    Returns a summary dict:
      {"total": int, "generated": int, "skipped": int, "failed": int, "errors": [str]}
    """
    projects = list_projects()
    total = len(projects)
    generated = failed = 0
    errors: list[str] = []

    for proj in projects:
        pid = proj["project_id"]
        try:
            generate_project_insight(pid)
            generated += 1
            logger.info("[project_service] generated package for %s (%s)", pid, proj["name"])
        except Exception as e:
            failed += 1
            msg = f"{proj['name']} ({pid}): {e}"
            errors.append(msg)
            logger.error("[project_service] failed for %s: %s", pid, e)

    return {
        "total":     total,
        "generated": generated,
        "skipped":   0,
        "failed":    failed,
        "errors":    errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Storage helpers
# ─────────────────────────────────────────────────────────────────────────────

def list_project_insights(project_id: str, limit: int = 20) -> list[dict]:
    from ..utils.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT id, project_id, day_number, insight_json, generated_at
               FROM project_insights
               WHERE project_id = ? AND status != 'generating'
               ORDER BY day_number DESC
               LIMIT ?""",
            (project_id, limit),
        ).fetchall()
    return [_pkg_row(r) for r in rows]


def get_project_insight(insight_id: int) -> dict | None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, project_id, day_number, insight_json, generated_at FROM project_insights WHERE id = ?",
            (insight_id,),
        ).fetchone()
    return _pkg_row(row) if row else None


def _save_generating_stub(project_id: str, day_number: int) -> tuple[int, str]:
    from ..utils.db import get_connection
    now = _now()
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO project_insights (project_id, day_number, insight_json, generated_at, status)
               VALUES (?, ?, '{}', ?, 'generating')""",
            (project_id, day_number, now),
        )
        conn.execute(
            "UPDATE learning_projects SET updated_at = ? WHERE project_id = ?",
            (now, project_id),
        )
    return cursor.lastrowid, now


def _set_insight_status(insight_id: int, status: str) -> None:
    from ..utils.db import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE project_insights SET status = ? WHERE id = ?",
            (status, insight_id),
        )


def _generate_insight_background(project_id: str, stub_id: int, day_number: int) -> None:
    try:
        generate_project_insight(
            project_id,
            _stub_id=stub_id,
            _precomputed_day_number=day_number,
        )
    except Exception as exc:
        _set_insight_status(stub_id, "failed")
        logger.error(
            "[project_service] background generation failed project=%s day=%d stub=%d exc=%s: %s",
            project_id, day_number, stub_id, type(exc).__name__, exc,
        )


def _save_package(project_id: str, day_number: int, package: dict, stub_id: int | None = None) -> int:
    from ..utils.db import get_connection
    now = package["generated_at"]
    if stub_id is not None:
        with get_connection() as conn:
            conn.execute(
                """UPDATE project_insights
                   SET insight_json = ?, generated_at = ?, status = 'done'
                   WHERE id = ?""",
                (json.dumps(package), now, stub_id),
            )
            conn.execute(
                "UPDATE learning_projects SET updated_at = ? WHERE project_id = ?",
                (now, project_id),
            )
        return stub_id
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO project_insights (project_id, day_number, insight_json, generated_at, status)
               VALUES (?, ?, ?, ?, 'done')""",
            (project_id, day_number, json.dumps(package), now),
        )
        conn.execute(
            "UPDATE learning_projects SET updated_at = ? WHERE project_id = ?",
            (now, project_id),
        )
    return cursor.lastrowid


def _pkg_row(row) -> dict:
    d = dict(row)
    raw = d.pop("insight_json", "{}")
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}
    return {
        **parsed,
        "id":           d["id"],
        "project_id":   d["project_id"],
        "generated_at": d["generated_at"],
    }


def _extract_json(text: str) -> dict:
    """Extract a JSON object from LLM output using multiple fallback strategies."""
    # Strategy 1: JSON inside a code fence
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Strategy 2: outermost { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    # Strategy 3: raw parse (will raise if not JSON)
    return json.loads(text.strip())


def delete_project_insight(project_id: str, insight_id: int) -> bool:
    from ..utils.db import get_connection
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM project_insights WHERE id = ? AND project_id = ?",
            (insight_id, project_id),
        )
    return cur.rowcount > 0


