"""
Learning progression service — tracks per-project educational state.

Each project has one progression record that accumulates as daily packages
are generated.  Progression is updated automatically by project_service after
every successful generation (concepts extracted from card categories/titles).

Public API
----------
get_progression(project_id)                            -> dict
update_progression(project_id, **fields)               -> dict
add_explored_concepts(project_id, concepts)            -> None
mark_topic_completed(project_id, topic)                -> None
refresh_suggestions(project_id)                        -> list[str]
update_progression_from_package(project_id, package)   -> None   (auto-called)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DATETIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now() -> str:
    return datetime.now(timezone.utc).strftime(_DATETIME_FMT)


# ── Domain-specific topic pools ───────────────────────────────────────────────
# Ordered from foundational → advanced.  The suggestion algorithm walks the
# pool and returns topics not yet in explored_concepts or completed_topics.

_TOPIC_POOLS: dict[str, list[str]] = {
    "manufacturing": [
        "Digital Factory Overview",
        "IoT Sensor Networks",
        "Predictive Maintenance Basics",
        "Anomaly Detection for Equipment",
        "Computer Vision for Quality Control",
        "Digital Twins in Production",
        "Edge AI Deployment",
        "Reinforcement Learning for Process Optimization",
        "Generative AI for Design Engineering",
        "Autonomous Manufacturing Lines",
    ],
    "computer vision": [
        "Image Classification Fundamentals",
        "Object Detection Pipelines",
        "Defect Detection with CNNs",
        "Semantic Segmentation in Industrial Settings",
        "Vision Transformers for Manufacturing",
        "Real-Time Inference on Edge Devices",
    ],
    "pharma": [
        "India Pharma Export Overview",
        "Key Regulatory Bodies (FDA, EMA, CDSCO)",
        "API vs Formulation Exports",
        "GMP Compliance Frameworks",
        "Regulatory Filing Pathways (ANDA, NDA)",
        "Biosimilars and Biologics Market",
        "Contract Manufacturing Organizations",
        "Post-COVID Export Realignment",
        "Specialty Chemicals Supply Chain",
        "Digital Transformation in Pharma QC",
    ],
    "finance": [
        "Modern Portfolio Theory",
        "CAPM and Systematic Risk",
        "Multi-Factor Models (Fama-French)",
        "Options Pricing (Black-Scholes)",
        "Risk Parity and Volatility Targeting",
        "Statistical Arbitrage Strategies",
        "Machine Learning for Alpha Generation",
        "Alternative Data in Systematic Trading",
        "High-Frequency Trading Microstructure",
        "Volatility Surface Modelling",
        "Deep Learning for Price Prediction",
    ],
    "supply chain": [
        "Supply Chain Fundamentals",
        "Demand Sensing and Forecasting",
        "Supplier Evaluation Frameworks",
        "Inventory Optimization Models",
        "Logistics Network Design",
        "Blockchain for Supply Chain Traceability",
        "Digital Twins in Supply Chain",
        "AI-Driven Procurement",
        "Supply Chain Resilience Metrics",
        "Last-Mile Delivery Optimization",
        "Nearshoring and Geopolitical Risk Management",
    ],
    "ai": [
        "Machine Learning Fundamentals",
        "Neural Network Architectures",
        "Transfer Learning",
        "Large Language Models",
        "Agentic AI Systems",
        "AI Safety and Alignment Basics",
        "Multimodal Models",
        "AI Governance and Regulation",
    ],
}


def _pool_for_project(project: dict) -> list[str]:
    """Pick the closest topic pool by keyword-matching project name + keywords."""
    text = " ".join(
        project.get("keywords", []) + [project.get("name", "")]
    ).lower()
    best_key, best_hits = "ai", 0
    for pool_key in _TOPIC_POOLS:
        hits = sum(1 for word in pool_key.split() if word in text)
        if hits > best_hits:
            best_hits = hits
            best_key = pool_key
    return _TOPIC_POOLS[best_key]


def _norm(s: str) -> str:
    return s.lower().strip()


def _suggest(
    pool: list[str],
    explored: list[str],
    completed: list[str],
    limit: int = 4,
) -> list[str]:
    done = {_norm(t) for t in explored + completed}
    return [t for t in pool if _norm(t) not in done][:limit]


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_or_create(project_id: str) -> dict:
    from ..utils.db import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project_progression WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT OR IGNORE INTO project_progression
                   (project_id, current_level, current_focus,
                    explored_concepts, completed_topics, suggested_next_topics,
                    days_completed, updated_at)
                   VALUES (?, 'beginner', NULL, '[]', '[]', '[]', 0, ?)""",
                (project_id, _now()),
            )
            row = conn.execute(
                "SELECT * FROM project_progression WHERE project_id = ?",
                (project_id,),
            ).fetchone()
    return _parse_row(dict(row))


def _parse_row(d: dict) -> dict:
    for field in ("explored_concepts", "completed_topics", "suggested_next_topics"):
        raw = d.get(field, "[]")
        if isinstance(raw, str):
            try:
                d[field] = json.loads(raw)
            except Exception:
                d[field] = []
    return d


def _save(project_id: str, **fields) -> dict:
    from ..utils.db import get_connection
    fields["updated_at"] = _now()
    for lf in ("explored_concepts", "completed_topics", "suggested_next_topics"):
        if lf in fields and isinstance(fields[lf], list):
            fields[lf] = json.dumps(fields[lf])
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE project_progression SET {set_clause} WHERE project_id = ?",
            [*fields.values(), project_id],
        )
    return get_progression(project_id)


# ── Public API ────────────────────────────────────────────────────────────────

def get_progression(project_id: str) -> dict:
    """Return the progression record, creating one if it doesn't exist yet."""
    return _get_or_create(project_id)


def update_progression(project_id: str, **fields) -> dict:
    """Explicitly update any subset of progression fields."""
    allowed = {
        "current_level", "current_focus", "explored_concepts",
        "completed_topics", "suggested_next_topics", "days_completed",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_progression(project_id)
    _get_or_create(project_id)
    return _save(project_id, **updates)


def add_explored_concepts(project_id: str, concepts: list[str]) -> None:
    """Merge new concept strings into explored_concepts (deduped, case-insensitive)."""
    prog = _get_or_create(project_id)
    existing_norms = {_norm(c) for c in prog["explored_concepts"]}
    new_ones = [c for c in concepts if c.strip() and _norm(c) not in existing_norms]
    if not new_ones:
        return
    _save(project_id, explored_concepts=prog["explored_concepts"] + new_ones)


def mark_topic_completed(project_id: str, topic: str) -> None:
    """Add a topic to completed_topics if not already there."""
    prog = _get_or_create(project_id)
    if any(_norm(t) == _norm(topic) for t in prog["completed_topics"]):
        return
    _save(project_id, completed_topics=[*prog["completed_topics"], topic])


def refresh_suggestions(project_id: str) -> list[str]:
    """Recompute and persist suggested_next_topics for this project."""
    prog = _get_or_create(project_id)
    try:
        from .project_service import get_project
        project = get_project(project_id) or {}
    except Exception:
        project = {}
    pool        = _pool_for_project(project)
    suggestions = _suggest(pool, prog["explored_concepts"], prog["completed_topics"])
    _save(project_id, suggested_next_topics=suggestions)
    return suggestions


def update_progression_from_package(project_id: str, package: dict) -> None:
    """
    Called automatically after each daily package generation.

    Extracts concepts from both core insights and curiosity_insights.
    Curiosity concepts are tracked as explored (adjacent knowledge is still knowledge)
    but do not trigger topic completion — they live outside the core curriculum path.
    """
    try:
        core_insights     = package.get("insights", [])
        curiosity_insights = package.get("curiosity_insights", [])
        all_cards         = core_insights + curiosity_insights

        # Extract concept labels: categories + news/educational titles
        categories  = [c["category"] for c in all_cards if c.get("category")]
        core_titles = [
            c["title"] for c in core_insights
            if c.get("content_type") in ("news", "educational") and c.get("title")
        ]
        add_explored_concepts(project_id, categories + core_titles)

        headline = package.get("package_headline", "")
        day_num  = package.get("day_number", 0)
        if headline or day_num:
            prog = _get_or_create(project_id)
            save_kw: dict = {}
            if headline:
                save_kw["current_focus"] = headline
            if day_num:
                save_kw["days_completed"] = max(day_num, prog.get("days_completed", 0))
            _save(project_id, **save_kw)

        refresh_suggestions(project_id)
    except Exception:
        logger.warning(
            "[progression_service] update_progression_from_package failed for %s (non-fatal)",
            project_id,
        )
