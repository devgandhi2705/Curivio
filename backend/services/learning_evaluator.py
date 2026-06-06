"""
Learning Quality Evaluator — Phase 4.7

Measures how well the system is teaching by scoring recent packages across
seven dimensions and producing a composite Learning Quality Score (LQS).

Dimensions (all 0.0–1.0, 1.0 = best)
---------------------------------------
  repetition_score      — 1 = no concept repetition across recent packages
  novelty_score         — 1 = all recent content is genuinely new
  progression_score     — 1 = user is advancing through stages at the right pace
  coverage_score        — 1 = high % of domain knowledge covered (from gap score)
  difficulty_growth     — 1 = difficulty is trending upward over time
  concept_diversity     — 1 = diverse node types in the knowledge graph
  mechanism_diversity   — 1 = many distinct mechanisms explained

LQS composite weights
----------------------
  repetition_score  × 0.20  (penalises re-covering the same ground)
  novelty_score     × 0.20  (rewards introducing fresh content)
  coverage_score    × 0.20  (rewards domain breadth)
  progression_score × 0.15  (rewards advancing depth stages)
  difficulty_growth × 0.10  (rewards escalating challenge)
  concept_diversity × 0.10  (rewards type variety)
  mechanism_diversity × 0.05

Thresholds for issue detection
--------------------------------
  < 0.40 → HIGH issue (must address in next package)
  < 0.60 → MEDIUM issue (should address soon)

Public API
----------
  evaluate(project_id, package=None) -> LearningQualityReport
  store_evaluation(report) -> int           (DB row id)
  get_latest_evaluation(project_id) -> LearningQualityReport | None
  get_quality_feedback_block(project_id) -> str   (for prompt injection)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────────

_STAGES = [
    "foundation", "mechanisms", "dependencies",
    "optimization", "geopolitical", "disruption", "synthesis",
]
_DAYS_PER_STAGE = 3

_DIFFICULTY_MAP = {"beginner": 0.0, "intermediate": 0.5, "advanced": 1.0}

_ISSUE_HIGH   = 0.40
_ISSUE_MEDIUM = 0.60

# LQS composite weights
_WEIGHTS = {
    "repetition":          0.20,
    "novelty":             0.20,
    "coverage":            0.20,
    "progression":         0.15,
    "difficulty_growth":   0.10,
    "concept_diversity":   0.10,
    "mechanism_diversity": 0.05,
}


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    name:       str
    score:      float
    weight:     float
    note:       str    # one-line explanation


@dataclass
class LearningQualityReport:
    project_id:    str
    package_day:   int
    overall_score: float
    dimensions:    list[DimensionScore]
    issues:        list[str]          # high/medium problems detected
    recommendations: list[str]        # actionable for next package
    top_gaps:      list[str]          # gap labels to prioritise
    evaluated_at:  str = ""

    def to_dict(self) -> dict:
        return {
            "project_id":     self.project_id,
            "package_day":    self.package_day,
            "overall_score":  self.overall_score,
            "dimensions":     {d.name: {"score": d.score, "note": d.note} for d in self.dimensions},
            "issues":         self.issues,
            "recommendations": self.recommendations,
            "top_gaps":       self.top_gaps,
        }


# ── Text helpers ───────────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    t = text.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _bigrams(text: str) -> frozenset[str]:
    words = text.split()
    if len(words) < 2:
        return frozenset(words)
    return frozenset(f"{words[i]} {words[i+1]}" for i in range(len(words)-1))


def _jaccard(a: str, b: str) -> float:
    ba, bb = _bigrams(_norm(a)), _bigrams(_norm(b))
    if not ba and not bb:
        return 1.0 if _norm(a) == _norm(b) else 0.0
    if not ba or not bb:
        return 0.0
    u = len(ba | bb)
    return len(ba & bb) / u if u else 0.0


# ── Data loaders ──────────────────────────────────────────────────────────────

def _load_recent_packages(project_id: str, limit: int = 6) -> list[dict]:
    """Load recent packages (with full insight JSON) from the DB."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT day_number, insight_json
                   FROM project_insights
                   WHERE project_id = ?
                   ORDER BY day_number DESC
                   LIMIT ?""",
                (project_id, limit),
            ).fetchall()
        packages = []
        for r in reversed(rows):
            try:
                pkg = json.loads(r["insight_json"])
                pkg["_day_number"] = r["day_number"]
                packages.append(pkg)
            except Exception:
                pass
        return packages
    except Exception:
        return []


def _all_cards(pkg: dict) -> list[dict]:
    return (pkg.get("insights") or []) + (pkg.get("curiosity_insights") or [])


# ── Dimension scorers ─────────────────────────────────────────────────────────

def _score_repetition(packages: list[dict]) -> DimensionScore:
    """
    Measure category repetition across the last 5 packages.
    Low unique/total ratio → high repetition → low score.
    """
    if len(packages) < 2:
        return DimensionScore("repetition", 0.70, _WEIGHTS["repetition"], "Not enough packages to evaluate")

    cats: list[str] = []
    for pkg in packages[-5:]:
        for card in _all_cards(pkg):
            cat = (card.get("category") or "").strip().lower()
            if cat:
                cats.append(cat)

    if not cats:
        return DimensionScore("repetition", 0.70, _WEIGHTS["repetition"], "No category data")

    unique = len(set(cats))
    total  = len(cats)
    score  = round(unique / total, 3)
    note   = f"{unique} unique / {total} total categories in last 5 packages"
    return DimensionScore("repetition", score, _WEIGHTS["repetition"], note)


def _score_novelty(packages: list[dict], covered_concepts: list[str]) -> DimensionScore:
    """
    Fraction of categories in the last 2 packages that were NOT in covered_concepts
    from before those packages (approximated as the oldest items in the list).
    """
    if not packages:
        return DimensionScore("novelty", 0.70, _WEIGHTS["novelty"], "No packages to evaluate")

    # Use categories in last 2 packages
    recent_cats: list[str] = []
    for pkg in packages[-2:]:
        for card in _all_cards(pkg):
            cat = (card.get("category") or "").strip().lower()
            if cat:
                recent_cats.append(cat)

    if not recent_cats:
        return DimensionScore("novelty", 0.50, _WEIGHTS["novelty"], "No category data in recent packages")

    # Compare against covered_concepts from before recent packages
    # (using the earlier portion of the list as "prior" knowledge)
    prior_covered = set(c.lower() for c in covered_concepts[:-len(recent_cats) * 2])
    novel = sum(1 for c in recent_cats if c not in prior_covered)
    score = round(novel / len(recent_cats), 3)
    note  = f"{novel} new / {len(recent_cats)} categories in last 2 packages"
    return DimensionScore("novelty", score, _WEIGHTS["novelty"], note)


def _score_progression(memory: dict, total_packages: int) -> DimensionScore:
    """
    How well is depth advancing relative to the number of packages generated?
    Expected stage = total_packages // DAYS_PER_STAGE (capped at max stage index).
    """
    stage     = memory.get("progression_stage", "foundation")
    days_at   = memory.get("days_at_stage", 0)

    actual_idx   = _STAGES.index(stage) if stage in _STAGES else 0
    expected_idx = min(total_packages // _DAYS_PER_STAGE, len(_STAGES) - 1)

    if expected_idx == 0:
        score = 0.70  # first few packages — no expectation yet
        note  = f"Stage: {stage} (early — no progression benchmark yet)"
    else:
        # Penalise if behind expected stage, reward if ahead
        ratio = actual_idx / expected_idx
        score = round(min(ratio, 1.0), 3)
        note  = f"Stage: {stage} (day {days_at} of {_DAYS_PER_STAGE}), expected >= {_STAGES[expected_idx]}"

    return DimensionScore("progression", score, _WEIGHTS["progression"], note)


def _score_coverage(gap_score: float) -> DimensionScore:
    """Coverage = 1 - gap_score (from knowledge gap detector)."""
    score = round(max(0.0, 1.0 - gap_score), 3)
    note  = f"{round(score * 100)}% of active domain knowledge covered"
    return DimensionScore("coverage", score, _WEIGHTS["coverage"], note)


def _score_difficulty_growth(packages: list[dict]) -> DimensionScore:
    """
    Is difficulty trending upward across packages?
    Maps beginner=0, intermediate=0.5, advanced=1.0 and computes slope.
    """
    if len(packages) < 2:
        return DimensionScore("difficulty_growth", 0.50, _WEIGHTS["difficulty_growth"], "Not enough packages")

    # Average difficulty per package (only core insight cards)
    avgs: list[float] = []
    for pkg in packages[-5:]:
        diffs = [
            _DIFFICULTY_MAP.get((c.get("difficulty") or "").lower(), 0.5)
            for c in (pkg.get("insights") or [])
            if c.get("difficulty")
        ]
        if diffs:
            avgs.append(sum(diffs) / len(diffs))

    if len(avgs) < 2:
        return DimensionScore("difficulty_growth", 0.50, _WEIGHTS["difficulty_growth"], "Insufficient difficulty data")

    # Linear slope: positive = growing, negative = regressing
    slope = (avgs[-1] - avgs[0]) / max(len(avgs) - 1, 1)
    # Map slope to [0,1]: slope=+0.1/pkg → perfect, slope=0 → 0.5, slope=-0.1 → 0.0
    score = round(min(max(0.5 + slope * 5, 0.0), 1.0), 3)
    note  = f"Avg difficulty trend: {[round(a, 2) for a in avgs]} (slope={round(slope, 3)})"
    return DimensionScore("difficulty_growth", score, _WEIGHTS["difficulty_growth"], note)


def _score_concept_diversity(graph: dict) -> DimensionScore:
    """
    Shannon entropy of node types in the knowledge graph, normalised by log2(6).
    High entropy = diverse concept types = good.
    """
    import math
    nodes = graph.get("nodes", [])
    if not nodes:
        return DimensionScore("concept_diversity", 0.50, _WEIGHTS["concept_diversity"], "No graph data")

    type_counts: dict[str, int] = {}
    for n in nodes:
        t = n.get("node_type", "concept")
        type_counts[t] = type_counts.get(t, 0) + 1

    total = sum(type_counts.values())
    if total == 0:
        return DimensionScore("concept_diversity", 0.50, _WEIGHTS["concept_diversity"], "Empty graph")

    entropy = 0.0
    for count in type_counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)

    max_entropy = math.log2(6)  # 6 node types
    score = round(entropy / max_entropy, 3)
    type_summary = ", ".join(f"{k}:{v}" for k, v in sorted(type_counts.items()))
    note  = f"Node distribution: {type_summary}"
    return DimensionScore("concept_diversity", score, _WEIGHTS["concept_diversity"], note)


def _score_mechanism_diversity(covered_mechanisms: list[str]) -> DimensionScore:
    """
    More unique mechanisms = higher score, capped at target of 10.
    """
    n = len(covered_mechanisms)
    target = 10
    score  = round(min(n / target, 1.0), 3)
    note   = f"{n} distinct mechanisms covered (target: {target}+)"
    return DimensionScore("mechanism_diversity", score, _WEIGHTS["mechanism_diversity"], note)


# ── Issue + recommendation generation ────────────────────────────────────────

_ISSUE_TEMPLATES: dict[str, tuple[str, str]] = {
    "repetition": (
        "HIGH REPETITION: recent packages re-cover the same concept categories at the same level.",
        "Rotate away from recently covered categories. Introduce concepts from the gap list.",
    ),
    "novelty": (
        "LOW NOVELTY: most recent content was already in the user's covered list.",
        "Prioritise gap items — at least 60% of today's concepts should be from the gap list.",
    ),
    "coverage": (
        "LOW COVERAGE: large parts of the domain knowledge base have not been touched.",
        "Expand into unexplored topic clusters — avoid repeating covered areas.",
    ),
    "progression": (
        "SLOW PROGRESSION: stage advancement is behind the expected pace.",
        "Advance depth — introduce mechanism-level and strategic content. Reduce foundation re-explanation.",
    ),
    "difficulty_growth": (
        "STAGNANT DIFFICULTY: difficulty has not been trending upward.",
        "Include at least 2 intermediate/advanced cards today. The user is ready to be challenged.",
    ),
    "concept_diversity": (
        "LOW CONCEPT DIVERSITY: too many cards of the same node type.",
        "Mix concept types — include mechanisms, examples/companies, and trend nodes.",
    ),
    "mechanism_diversity": (
        "FEW MECHANISMS EXPLAINED: causal chains are underrepresented.",
        "Add at least 1 educational card that exposes a specific causal mechanism.",
    ),
}


def _build_issues_and_recs(
    dimensions: list[DimensionScore],
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    recs:   list[str] = []
    for d in dimensions:
        if d.score < _ISSUE_HIGH:
            level = "HIGH"
        elif d.score < _ISSUE_MEDIUM:
            level = "MEDIUM"
        else:
            continue
        issue_text, rec_text = _ISSUE_TEMPLATES.get(d.name, ("", ""))
        if issue_text:
            issues.append(f"[{level}] {issue_text}")
            recs.append(rec_text)
    return issues, recs


# ── Composite LQS ────────────────────────────────────────────────────────────

def _composite_lqs(dimensions: list[DimensionScore]) -> float:
    return round(sum(d.score * d.weight for d in dimensions), 3)


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate(project_id: str, package: dict | None = None) -> LearningQualityReport:
    """
    Evaluate learning quality for the project.

    If `package` is supplied, it is appended to the list of recent packages
    (used when called immediately after generation before the package is
    returned from generate_project_insight).

    Non-fatal — returns a neutral report on any error.
    """
    try:
        from .learning_memory_service import get_memory
        from .knowledge_gap_detector import detect_gaps
        from .learning_graph import get_graph

        packages = _load_recent_packages(project_id, limit=6)
        if package:
            packages.append(package)

        memory             = get_memory(project_id)
        covered_concepts   = memory.get("covered_concepts", [])
        covered_mechanisms = memory.get("covered_mechanisms", [])

        gap_report = detect_gaps(project_id)
        graph      = get_graph(project_id)

        total_pkgs = max(len(packages), 1)
        current_day = (package or packages[-1] if packages else {}).get("day_number", 0) if packages or package else 0

        # Score each dimension
        dims = [
            _score_repetition(packages),
            _score_novelty(packages, covered_concepts),
            _score_progression(memory, total_pkgs),
            _score_coverage(gap_report.gap_score),
            _score_difficulty_growth(packages),
            _score_concept_diversity(graph),
            _score_mechanism_diversity(covered_mechanisms),
        ]

        issues, recs = _build_issues_and_recs(dims)
        lqs          = _composite_lqs(dims)

        # Top gaps to address
        top_gaps = [
            g.label
            for g in (gap_report.missing_concepts + gap_report.missing_mechanisms + gap_report.missing_strategic)
            if g.priority == "high"
        ][:5]

        return LearningQualityReport(
            project_id=project_id,
            package_day=current_day,
            overall_score=lqs,
            dimensions=dims,
            issues=issues,
            recommendations=recs,
            top_gaps=top_gaps,
            evaluated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

    except Exception:
        logger.exception("[learning_evaluator] evaluate() failed for %s", project_id)
        return LearningQualityReport(
            project_id=project_id,
            package_day=0,
            overall_score=0.5,
            dimensions=[],
            issues=[],
            recommendations=[],
            top_gaps=[],
            evaluated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )


def store_evaluation(report: LearningQualityReport) -> int:
    """Persist a LearningQualityReport to the DB. Returns the row id."""
    try:
        from ..utils.db import get_connection
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO learning_evaluations
                   (project_id, package_day, overall_score, scores_json, issues_json, recs_json, evaluated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    report.project_id,
                    report.package_day,
                    report.overall_score,
                    json.dumps({d.name: {"score": d.score, "note": d.note} for d in report.dimensions}),
                    json.dumps(report.issues),
                    json.dumps(report.recommendations),
                    now,
                ),
            )
        return cursor.lastrowid or 0
    except Exception:
        logger.exception("[learning_evaluator] store_evaluation failed for %s", report.project_id)
        return 0


def get_latest_evaluation(project_id: str) -> LearningQualityReport | None:
    """Load the most recent stored evaluation for a project."""
    try:
        from ..utils.db import get_connection
        with get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM learning_evaluations
                   WHERE project_id = ?
                   ORDER BY evaluated_at DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        row = dict(row)
        scores  = json.loads(row.get("scores_json", "{}"))
        dims    = [
            DimensionScore(
                name=k,
                score=v.get("score", 0.5),
                weight=_WEIGHTS.get(k, 0.1),
                note=v.get("note", ""),
            )
            for k, v in scores.items()
        ]
        return LearningQualityReport(
            project_id=row["project_id"],
            package_day=row["package_day"],
            overall_score=row["overall_score"],
            dimensions=dims,
            issues=json.loads(row.get("issues_json", "[]")),
            recommendations=json.loads(row.get("recs_json", "[]")),
            top_gaps=[],
            evaluated_at=row.get("evaluated_at", ""),
        )
    except Exception:
        logger.exception("[learning_evaluator] get_latest_evaluation failed for %s", project_id)
        return None


def get_quality_feedback_block(project_id: str) -> str:
    """
    Load the latest stored evaluation and format it as a prompt injection block.
    Returns "" when no evaluation exists or the score is good (>= 0.80).
    """
    try:
        report = get_latest_evaluation(project_id)
        if not report:
            return ""
        if report.overall_score >= 0.80 and not report.issues:
            return ""

        score_pct = round(report.overall_score * 100)
        label = "Excellent" if score_pct >= 80 else "Good" if score_pct >= 65 else "Needs Work"

        lines: list[str] = []
        lines.append("══════════════════════════════════════")
        lines.append("QUALITY FEEDBACK  <- issues from last package evaluation")
        lines.append("══════════════════════════════════════")
        lines.append(f"Score: {score_pct}/100 ({label})  |  Day {report.package_day} evaluation")

        if report.issues:
            lines.append("")
            lines.append("Issues detected (address these in today's package):")
            for issue in report.issues:
                lines.append(f"  {issue}")

        if report.recommendations:
            lines.append("")
            lines.append("Mandatory improvements:")
            for rec in report.recommendations:
                lines.append(f"  • {rec}")

        # Dimension scores for the LLM to read
        if report.dimensions:
            weak = [d for d in report.dimensions if d.score < _ISSUE_MEDIUM]
            if weak:
                lines.append("")
                lines.append("Weak dimensions:")
                for d in weak:
                    lines.append(f"  [{d.name}: {round(d.score*100)}%] {d.note}")

        return "\n".join(lines)

    except Exception:
        logger.exception("[learning_evaluator] get_quality_feedback_block failed for %s", project_id)
        return ""
