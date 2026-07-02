#!/usr/bin/env python3
"""
tools/gemini_eval/run_eval.py

Standalone evaluation harness — NOT wired into the production app.
Runs 8 test cases against 3 Gemini models with persistent state,
concurrent dispatch per test case, 429-aware retry, automatic scoring
via Groq, and a markdown report.

State survives across runs (state.json). Cells already marked "done"
are skipped. Models that quota-exhaust in a run are skipped for the
rest of that run but retried next run.

Usage:
    python tools/gemini_eval/run_eval.py
    python tools/gemini_eval/run_eval.py --collect-only
    python tools/gemini_eval/run_eval.py --score-only
    python tools/gemini_eval/run_eval.py --report-only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR   = Path(__file__).resolve().parent
ROOT        = TOOLS_DIR.parents[1]   # repo root (tools/gemini_eval/ → tools/ → repo/)
STATE_FILE  = TOOLS_DIR / "state.json"
REPORT_FILE = TOOLS_DIR / "report.md"

sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(dotenv_path=ROOT / ".env")

from backend.services.journey_planner_service import _build_prompt, _extract_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Models ────────────────────────────────────────────────────────────────────
MODELS = {
    "gemini-2.5-flash":      "models/gemini-2.5-flash",
    # gemini-3.5-flash removed: disqualified for reproducible JSON corruption on certain prompts, found during evaluation.
    "gemini-3.1-flash-lite": "models/gemini-3.1-flash-lite",
}

# ── Test cases ────────────────────────────────────────────────────────────────
TEST_CASES: list[dict] = [
    {
        "id": 1, "label": "DSA for interviews",
        "description": "Teach me data structures and algorithms from scratch, I want to be ready for technical interviews.",
        "expected_shape": "fixed_sequence",
        "intent_profile": {
            "learning_subject": "Data Structures and Algorithms", "persona": "Student",
            "goal": "Learn DSA from scratch, ready for technical interviews",
            "search_lens": "Educational",
            "primary_focus": "algorithms, data structures, computational complexity",
            "intent_summary": "A student learning DSA from scratch to prepare for technical interviews.",
        },
        "keywords": ["data structures", "algorithms", "Big-O", "arrays", "trees", "graphs", "dynamic programming"],
        "checklist": [
            "Big-O / complexity analysis", "arrays & strings", "recursion", "sorting algorithms",
            "linked lists", "stacks & queues", "hashing / hash tables", "trees (incl. BST)",
            "graphs (BFS/DFS)", "dynamic programming",
        ],
        "must_reach": ["graphs", "dynamic programming"],
        "expected_sources": None,
        "diagnostic": False,
    },
    {
        "id": 2, "label": "Immune system & vaccines",
        "description": "Explain how the human immune system works, from the basics to how vaccines train it.",
        "expected_shape": "fixed_sequence",
        "intent_profile": {
            "learning_subject": "Human Immune System", "persona": "Learner",
            "goal": "Understand how the human immune system works, from basics to vaccines",
            "search_lens": "Educational",
            "primary_focus": "immunology, vaccines, immune response, lymphocytes",
            "intent_summary": "A learner exploring how the human immune system works from basics through vaccine mechanism.",
        },
        "keywords": ["immune system", "innate immunity", "adaptive immunity", "antibodies", "vaccines", "lymphocytes"],
        "checklist": [
            "innate immunity", "adaptive immunity", "lymphocytes (T cells / B cells)",
            "antibodies / antigens", "immune memory", "how vaccines work", "real disease / application example",
        ],
        "must_reach": ["how vaccines work"],
        "expected_sources": None,
        "diagnostic": False,
    },
    {
        "id": 3, "label": "Startup funding & VC",
        "description": "I want to stay updated on startup funding, venture capital, and the startup ecosystem.",
        "expected_shape": "rotating_theme",
        "intent_profile": {
            "learning_subject": "Startup Funding and Venture Capital", "persona": "Entrepreneur",
            "goal": "Stay updated on startup funding, VC, and the startup ecosystem",
            "search_lens": "Business Strategy",
            "primary_focus": "venture capital, startup funding rounds, exits, founder stories",
            "intent_summary": "An entrepreneur staying current on startup funding, VC activity, and the startup ecosystem.",
        },
        "keywords": ["venture capital", "startup funding", "seed rounds", "M&A", "exits", "founder stories"],
        "checklist": ["funding rounds / VC activity", "M&A / exits", "founder stories", "specific verticals", "macro conditions"],
        "must_reach": None,
        "expected_sources": ["techcrunch.com", "theinformation.com", "crunchbase.com", "pitchbook.com"],
        "diagnostic": False,
    },
    {
        "id": 4, "label": "Pharma industry",
        "description": "Keep me updated on the pharmaceutical industry — drug approvals, clinical trials, and major deals.",
        "expected_shape": "rotating_theme",
        "intent_profile": {
            "learning_subject": "Pharmaceutical Industry", "persona": "Healthcare Professional",
            "goal": "Stay updated on drug approvals, clinical trials, and major pharmaceutical deals",
            "search_lens": "Industry News",
            "primary_focus": "FDA approvals, clinical trials, drug pipeline, pharma M&A",
            "intent_summary": "A professional staying current on pharmaceutical approvals, trials, and major deals.",
        },
        "keywords": ["FDA approval", "clinical trials", "drug pipeline", "pharma M&A", "drug pricing", "biotech"],
        "checklist": [
            "FDA / regulatory approvals", "clinical trial results", "M&A / licensing deals",
            "pricing & policy", "R&D breakthroughs",
        ],
        "must_reach": None,
        "expected_sources": ["fiercepharma.com", "endpts.com", "statnews.com", "fda.gov"],
        "diagnostic": False,
    },
    {
        "id": 5, "label": "Latest AI trends",
        "description": "I want to learn about latest AI trends.",
        "expected_shape": "rotating_theme",
        "intent_profile": {
            "learning_subject": "Latest AI Trends", "persona": "Tech Enthusiast",
            "goal": "Stay current on the latest developments in AI",
            "search_lens": "Business Strategy",
            "primary_focus": "AI industry news and model releases",
            "intent_summary": "A tech enthusiast staying current on AI news and trends.",
        },
        "keywords": ["AI trends", "LLMs", "AI news", "foundation models", "AI industry"],
        "checklist": ["model releases / research", "industry / funding", "regulation", "enterprise adoption"],
        "must_reach": None,
        "expected_sources": ["arxiv.org", "venturebeat.com", "techcrunch.com"],
        "diagnostic": False,
    },
    {
        "id": 6, "label": "World news & current events",
        "description": "Help me stay informed about world news and current events.",
        "expected_shape": "rotating_theme",
        "intent_profile": {
            "learning_subject": "World News and Current Events", "persona": "Informed Citizen",
            "goal": "Stay informed about world news and current events",
            "search_lens": "News",
            "primary_focus": "geopolitics, economics, politics, global issues",
            "intent_summary": "An informed citizen staying current on world news and global events.",
        },
        "keywords": ["world news", "geopolitics", "politics", "economy", "international affairs", "current events"],
        "checklist": ["geopolitics", "domestic politics / policy", "economy / markets", "one major ongoing global issue"],
        "must_reach": None,
        "expected_sources": ["reuters.com", "apnews.com", "bbc.com"],
        "diagnostic": False,
    },
    {
        "id": 7, "label": "Chess beginner to intermediate",
        "description": "Teach me how to play chess, from beginner to a strong intermediate level.",
        "expected_shape": "fixed_sequence",
        "intent_profile": {
            "learning_subject": "Chess", "persona": "Beginner",
            "goal": "Learn chess from beginner to strong intermediate level",
            "search_lens": "Educational",
            "primary_focus": "chess rules, tactics, strategy, openings, endgames",
            "intent_summary": "A beginner learning chess progressively from piece movement to intermediate strategy.",
        },
        "keywords": ["chess", "chess openings", "chess tactics", "endgames", "positional play", "piece movement"],
        "checklist": [
            "piece movement / rules", "opening principles", "tactics (forks / pins / skewers)",
            "basic endgames", "positional strategy", "reviewing your own games",
        ],
        "must_reach": ["tactics", "endgames"],
        "expected_sources": None,
        "diagnostic": False,
    },
    {
        "id": 8, "label": "ML fundamentals + research (diagnostic)",
        "description": "I want to deeply understand machine learning fundamentals while also following the latest ML research as it happens.",
        "expected_shape": None,  # diagnostic — document ambiguity handling, do not score shape
        "intent_profile": {
            "learning_subject": "Machine Learning Fundamentals and Research", "persona": "ML Engineer",
            "goal": "Deeply understand ML fundamentals while following latest ML research",
            "search_lens": "Educational",
            "primary_focus": "machine learning, neural networks, ML research fundamentals",
            "intent_summary": "An ML engineer seeking deep ML fundamentals understanding and current ML research tracking.",
        },
        "keywords": ["machine learning", "neural networks", "deep learning", "ML research", "fundamentals"],
        "checklist": None,
        "must_reach": None,
        "expected_sources": None,
        "diagnostic": True,
    },
]

# ── State management ───────────────────────────────────────────────────────────
_state_lock = threading.Lock()

def _key(case_id: int, slug: str) -> str:
    return f"case{case_id}__{slug}"

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    cells: dict = {}
    for case in TEST_CASES:
        for slug in MODELS:
            cells[_key(case["id"], slug)] = {
                "status": "pending", "raw_output": None, "parsed_output": None,
                "latency_ms": None, "timestamp": None, "retried": False, "scores": None,
            }
    state = {"cells": cells}
    save_state(state)
    return state

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

_SYM = {"done": "✓", "skipped-quota-exhausted": "Q", "pending": "·"}

def print_progress(state: dict) -> None:
    slugs = list(MODELS)
    abbr  = {"gemini-2.5-flash": "2.5F", "gemini-3.1-flash-lite": "3.1L"}
    print("\n── Progress ──────────────────────────────────────────────────────")
    print(f"  {'':>4}  {'Label':<34}  " + "  ".join(abbr[s] for s in slugs))
    for case in TEST_CASES:
        syms = [_SYM.get(state["cells"].get(_key(case["id"], s), {}).get("status", "pending"), "?")
                for s in slugs]
        print(f"  {case['id']:>3}.  {case['label']:<34}  {'   '.join(syms)}")
    totals = {s: sum(1 for c in state["cells"].values() if c.get("status") == s)
              for s in ("done", "skipped-quota-exhausted", "pending")}
    print(f"\n  done={totals['done']}  quota-skipped={totals['skipped-quota-exhausted']}  pending={totals['pending']}")
    print()

# ── Gemini API ─────────────────────────────────────────────────────────────────
_gclient = None
_gclient_lock = threading.Lock()

def _get_gclient():
    global _gclient
    with _gclient_lock:
        if _gclient is None:
            from openai import OpenAI
            key = os.getenv("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY not set in .env")
            _gclient = OpenAI(
                api_key=key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                timeout=120.0,
            )
    return _gclient

def _is_quota(exc: Exception) -> bool:
    s = str(exc)
    return "429" in s or "RESOURCE_EXHAUSTED" in s

def _retry_after(exc: Exception) -> int:
    try:
        h = getattr(getattr(exc, "response", None), "headers", {}) or {}
        return int(h.get("retry-after") or h.get("Retry-After") or 45)
    except Exception:
        return 45

def _single_call(model_str: str, prompt: str) -> tuple[str, int]:
    t0 = time.monotonic()
    r  = _get_gclient().chat.completions.create(
        model=model_str,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return r.choices[0].message.content, int((time.monotonic() - t0) * 1000)

def call_with_retry(
    slug: str, model_str: str, prompt: str, exhausted: set
) -> tuple[str | None, int, str, bool]:
    """Returns (content|None, latency_ms, status, retried)."""
    if slug in exhausted:
        return None, 0, "skipped-quota-exhausted", False
    try:
        content, ms = _single_call(model_str, prompt)
        return content, ms, "done", False
    except Exception as e1:
        if not _is_quota(e1):
            raise
        wait = _retry_after(e1)
        log.warning("%s → 429; sleeping %ds then retrying once", slug, wait)
        time.sleep(wait)
        try:
            content, ms = _single_call(model_str, prompt)
            return content, ms, "done", True
        except Exception as e2:
            if _is_quota(e2):
                log.warning("%s quota exhausted after retry — skipping rest of this run", slug)
                exhausted.add(slug)
                return None, 0, "skipped-quota-exhausted", True
            raise

# ── Collection ─────────────────────────────────────────────────────────────────
def collect_all(state: dict) -> dict:
    exhausted: set[str] = set()

    for case in TEST_CASES:
        pending = [
            (slug, model_str) for slug, model_str in MODELS.items()
            if state["cells"][_key(case["id"], slug)]["status"] == "pending"
            and slug not in exhausted
        ]
        if not pending:
            log.info("Case %d: all cells done/skipped", case["id"])
            continue

        prompt = _build_prompt(case["intent_profile"], case["keywords"], None, 1)
        log.info("Case %d (%s): dispatching %d model(s) concurrently",
                 case["id"], case["label"], len(pending))

        def run_cell(pair: tuple, p: str = prompt, cid: int = case["id"]) -> tuple:
            slug, model_str = pair
            try:
                content, ms, status, retried = call_with_retry(slug, model_str, p, exhausted)
            except Exception as exc:
                log.error("Case %d / %s hard error: %s", cid, slug, exc)
                return slug, None, 0, "pending", False, None
            parsed = None
            if content:
                try:
                    parsed = _extract_json(content)
                except Exception:
                    pass  # technical_reliability will reflect the parse failure
            return slug, content, ms, status, retried, parsed

        with ThreadPoolExecutor(max_workers=len(pending)) as pool:
            futs = {pool.submit(run_cell, pair): pair for pair in pending}
            for fut in as_completed(futs):
                try:
                    slug, content, ms, status, retried, parsed = fut.result()
                except Exception as exc:
                    log.error("Thread error: %s", exc)
                    continue
                key = _key(case["id"], slug)
                with _state_lock:
                    state["cells"][key].update({
                        "status":        status,
                        "raw_output":    content,
                        "parsed_output": parsed,
                        "latency_ms":    ms,
                        "timestamp":     datetime.now(timezone.utc).isoformat(),
                        "retried":       retried,
                    })
                    save_state(state)
                log.info("  %-25s → %-30s  %dms", slug, status, ms)

        if len(exhausted) == len(MODELS):
            log.warning("All models quota-exhausted — stopping collection for this run")
            break
        time.sleep(2)  # small gap between cases to avoid RPM spikes

    return state

# ── Scoring ─────────────────────────────────────────────────────────────────────
GROQ_SCORE_MODEL = "llama-3.3-70b-versatile"

def _score_objective(case: dict, cell: dict) -> dict:
    """Compute objective dimensions without calling any LLM."""
    parsed   = cell.get("parsed_output") or {}
    shape    = parsed.get("shape", "")
    is_diag  = case.get("diagnostic", False)
    scores: dict = {}

    # shape_correctness
    if is_diag:
        scores["shape_correctness"] = {"score": None, "na": True, "evidence": "Case 8 diagnostic — not scored"}
    else:
        exp = case["expected_shape"]
        scores["shape_correctness"] = {
            "score": 3 if shape == exp else 0,
            "evidence": f"output shape={shape!r}, expected={exp!r}",
        }

    # technical_reliability
    if cell.get("status") == "skipped-quota-exhausted":
        scores["technical_reliability"] = {"score": None, "na": True, "evidence": "No output (quota exhausted)"}
    elif not cell.get("parsed_output"):
        scores["technical_reliability"] = {"score": 0, "evidence": "JSON parse failed"}
    elif cell.get("retried"):
        scores["technical_reliability"] = {"score": 1, "evidence": "Parsed after retry"}
    else:
        scores["technical_reliability"] = {"score": 2, "evidence": "Clean JSON, first try"}

    # frame_hint_variety — only meaningful for fixed_sequence
    if is_diag:
        scores["frame_hint_variety"] = {"score": None, "na": True, "evidence": "Case 8 diagnostic — not scored"}
    elif shape == "fixed_sequence":
        days  = parsed.get("days") or []
        hints = list({d.get("frame_hint") for d in days if d.get("frame_hint")})
        n     = len(hints)
        scores["frame_hint_variety"] = {
            "score": 3 if n >= 3 else 2 if n == 2 else 1 if n == 1 else 0,
            "evidence": f"Distinct frame_hint values ({n}): {hints}",
        }
    else:  # rotating_theme — no day entries
        scores["frame_hint_variety"] = {
            "score": None, "na": True,
            "evidence": "rotating_theme — no day entries, frame_hint N/A",
        }

    return scores

def _groq_score(case: dict, cell: dict) -> dict:
    """Call Groq to score the subjective rubric dimensions."""
    from groq import Groq
    gc     = Groq(api_key=os.getenv("GROQ_API_KEY"))
    parsed = cell.get("parsed_output") or {}
    is_diag    = case.get("diagnostic", False)
    is_fixed   = case.get("expected_shape") == "fixed_sequence"
    is_rotating = case.get("expected_shape") == "rotating_theme"

    plan_str      = json.dumps(parsed, indent=2)
    checklist_str = json.dumps(case.get("checklist") or [])
    sources_str   = json.dumps(case.get("expected_sources") or [])

    if is_diag:
        prompt = (
            "You are evaluating an AI journey planning output for ambiguity handling.\n\n"
            f"Test prompt: {case['description']}\n\n"
            "The prompt has DUAL intent: 'deeply understand fundamentals' (implies fixed_sequence) "
            "AND 'following the latest research as it happens' (implies rotating_theme).\n\n"
            f"Model output:\n{plan_str}\n\n"
            "In 3-5 sentences, describe: Did the model pick one shape cleanly? Did it try to blend both? "
            "Did it note the tension? Was the result coherent? What shape did it pick and does it reflect "
            "the stronger intent signal in the prompt?\n\n"
            'Return ONLY this JSON: {"case_8_analysis": "your analysis here"}'
        )
    else:
        seq_block = (
            "sequencing_soundness: Does each concept build on prior ones with no prerequisite skipped? "
            "3=no slips. 2=one minor slip. 1=multiple/serious slips. 0=no discernible order."
            if is_fixed
            else
            'Do NOT score sequencing_soundness. Set: "sequencing_soundness": {"score": null, "na": true, "evidence": "rotating_theme"}'
        )
        theme_block = (
            "theme_distinctiveness: Are themes distinct and jointly covering the domain? "
            "3=distinct+comprehensive. 2=minor overlap. 1=real redundancy. 0=vague/interchangeable."
            if is_rotating
            else
            'Do NOT score theme_distinctiveness. Set: "theme_distinctiveness": {"score": null, "na": true, "evidence": "fixed_sequence"}'
        )
        source_block = (
            f"source_quality: Do the trusted_sources match the expected domain-specific outlets {sources_str}? "
            "3=domain-specific match. 2=mostly relevant, one generic. 1=mixed. 0=generic/irrelevant. "
            "Score 0 if none of the expected outlets (or close equivalents) appear."
            if is_rotating
            else
            'Do NOT score source_quality. Set: "source_quality": {"score": null, "na": true, "evidence": "fixed_sequence"}'
        )

        prompt = (
            "You are a judge scoring an AI-generated learning journey plan. Return ONLY a valid JSON object.\n\n"
            f"Test: {case['label']}\n"
            f"Prompt: {case['description']}\n"
            f"Expected shape: {case['expected_shape']}\n"
            f"Checklist: {checklist_str}\n\n"
            f"Plan output:\n{plan_str}\n\n"
            "Score these dimensions:\n\n"
            "coverage_completeness: Check day titles, focus descriptions, rationale for checklist items. "
            "3=~90%+ of checklist hit AND reaches a natural endpoint. 2=most items but stops noticeably short or misses 2+. "
            "1=major gaps. 0=barely engages. List which checklist items appear (hit) and which don't (missed).\n\n"
            f"{seq_block}\n\n"
            f"{theme_block}\n\n"
            f"{source_block}\n\n"
            "user_facing_polish: Do display_title / display_summary fields read naturally? "
            "2=natural and engaging. 1=functional but robotic. 0=awkward or unclear.\n\n"
            "Return this JSON:\n"
            "{\n"
            '  "coverage_completeness": {"score": 0-3, "evidence": "one sentence", "hit": ["..."], "missed": ["..."]},\n'
            '  "sequencing_soundness": {"score": null_or_int, "na": true_or_false, "evidence": "..."},\n'
            '  "theme_distinctiveness": {"score": null_or_int, "na": true_or_false, "evidence": "..."},\n'
            '  "source_quality": {"score": null_or_int, "na": true_or_false, "evidence": "..."},\n'
            '  "user_facing_polish": {"score": 0-2, "evidence": "..."},\n'
            '  "case_8_analysis": null\n'
            "}"
        )

    resp = gc.chat.completions.create(
        model=GROQ_SCORE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)

_NULL_SUBJ: dict = {
    "coverage_completeness":  {"score": None, "na": True, "evidence": "No output"},
    "sequencing_soundness":   {"score": None, "na": True, "evidence": "No output"},
    "theme_distinctiveness":  {"score": None, "na": True, "evidence": "No output"},
    "source_quality":         {"score": None, "na": True, "evidence": "No output"},
    "user_facing_polish":     {"score": None, "evidence": "No output"},
    "case_8_analysis":        None,
}

def score_all(state: dict) -> dict:
    for case in TEST_CASES:
        for slug in MODELS:
            key  = _key(case["id"], slug)
            cell = state["cells"][key]
            if cell["status"] != "done":
                continue
            if cell.get("scores") is not None:
                continue  # already scored
            log.info("Scoring case %d / %s", case["id"], slug)
            try:
                obj  = _score_objective(case, cell)
                subj = _groq_score(case, cell) if cell.get("parsed_output") else _NULL_SUBJ
                cell["scores"] = {**obj, **subj}
                with _state_lock:
                    save_state(state)
            except Exception as exc:
                log.error("Scoring failed case %d / %s: %s", case["id"], slug, exc)
    return state

# ── Normalized score ───────────────────────────────────────────────────────────
_DIM_MAX = {
    "shape_correctness": 3, "coverage_completeness": 3,
    "sequencing_soundness": 3,                   # fixed_sequence only
    "theme_distinctiveness": 3, "source_quality": 3,  # rotating_theme only
    "frame_hint_variety": 3,
    "user_facing_polish": 2, "technical_reliability": 2,
}
_FIXED_ONLY    = {"sequencing_soundness"}
_ROTATING_ONLY = {"theme_distinctiveness", "source_quality"}

def norm_score(case: dict, cell: dict) -> float | None:
    if case.get("diagnostic"):
        return None
    s = cell.get("scores")
    if not s:
        return None
    is_fixed    = case.get("expected_shape") == "fixed_sequence"
    is_rotating = case.get("expected_shape") == "rotating_theme"
    total = maxv = 0
    for dim, mx in _DIM_MAX.items():
        if dim in _FIXED_ONLY    and not is_fixed:    continue
        if dim in _ROTATING_ONLY and not is_rotating: continue
        entry = s.get(dim) or {}
        v     = entry.get("score")
        if v is None or entry.get("na"):
            continue
        total += v
        maxv  += mx
    return round(100 * total / maxv, 1) if maxv else None

# ── Report ─────────────────────────────────────────────────────────────────────
_DIM_ORDER = [
    "shape_correctness", "coverage_completeness", "sequencing_soundness",
    "theme_distinctiveness", "source_quality", "frame_hint_variety",
    "user_facing_polish", "technical_reliability",
]

def generate_report(state: dict) -> str:
    out: list[str] = [
        "# Gemini Model Evaluation Report",
        f"\nGenerated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC\n",
        "Models: gemini-2.5-flash · gemini-3.1-flash-lite  ",
        "Cases 1–7 scored. Case 8 qualitative only.\n",
    ]

    # ── Summary table ──────────────────────────────────────────────────────────
    out.append("## Summary Table\n")
    out.append("| Model | " + " | ".join(f"C{c['id']}" for c in TEST_CASES) + " | Avg C1–C7 |")
    out.append("|" + "---|" * (len(TEST_CASES) + 2))
    for slug in MODELS:
        row_vals: list[str] = []
        scored: list[float] = []
        for case in TEST_CASES:
            cell = state["cells"][_key(case["id"], slug)]
            if case.get("diagnostic"):
                row_vals.append("*diag*")
            else:
                ns = norm_score(case, cell)
                if ns is not None:
                    row_vals.append(f"{ns}%")
                    scored.append(ns)
                else:
                    st = cell.get("status", "pending")
                    row_vals.append("Q" if "quota" in st else "…")
        avg = f"{round(sum(scored)/len(scored), 1)}%" if scored else "—"
        out.append(f"| {slug} | " + " | ".join(row_vals) + f" | {avg} |")
    out.append("")

    # ── Per-case detail ────────────────────────────────────────────────────────
    out.append("---\n\n## Per-Case Detail\n")
    for case in TEST_CASES:
        out.append(f"### Case {case['id']}: {case['label']}\n")
        out.append(f"**Prompt:** _{case['description']}_\n")
        if case.get("diagnostic"):
            out.append("**Type:** Diagnostic — ambiguity test. Not scored.\n")
        else:
            out.append(f"**Expected shape:** `{case['expected_shape']}`  ")
            if case.get("checklist"):
                out.append(f"**Checklist:** {', '.join(case['checklist'])}\n")

        for slug in MODELS:
            key    = _key(case["id"], slug)
            cell   = state["cells"][key]
            status = cell.get("status", "pending")
            lat    = f"{cell.get('latency_ms') or '—'}ms"
            retry  = "  *(retried)*" if cell.get("retried") else ""
            out.append(f"\n#### {slug}")
            out.append(f"- **Status:** {status}  |  **Latency:** {lat}{retry}")

            if status == "skipped-quota-exhausted":
                out.append("\n*Quota exhausted — no output available.*\n")
                continue
            if status == "pending":
                out.append("\n*Pending — not yet collected.*\n")
                continue

            parsed = cell.get("parsed_output")
            if parsed:
                out.append("\n**Raw output:**")
                out.append("```json")
                out.append(json.dumps(parsed, indent=2))
                out.append("```")
            else:
                raw = cell.get("raw_output") or ""
                out.append(f"\n*Output present but JSON parse failed. Raw (first 300 chars):*\n```\n{raw[:300]}\n```")

            scores = cell.get("scores")
            if not scores:
                out.append("\n*Scoring pending.*\n")
                continue

            if case.get("diagnostic"):
                ana = scores.get("case_8_analysis") or "*(analysis pending)*"
                out.append(f"\n**Ambiguity handling:**\n{ana}\n")
            else:
                ns = norm_score(case, cell)
                ns_str = f"{ns}%" if ns is not None else "N/A"
                out.append(f"\n**Normalized score: {ns_str}**\n")
                out.append("| Dimension | Score | Evidence |")
                out.append("|---|---|---|")
                for dim in _DIM_ORDER:
                    entry = scores.get(dim) or {}
                    v     = entry.get("score")
                    na    = entry.get("na", False)
                    mx    = _DIM_MAX.get(dim, "?")
                    s_str = "N/A" if (v is None or na) else f"{v}/{mx}"
                    ev    = str(entry.get("evidence", ""))
                    if dim == "coverage_completeness":
                        hit    = entry.get("hit", [])
                        missed = entry.get("missed", [])
                        if hit or missed:
                            ev += f" — Hit: {hit}; Missed: {missed}"
                    ev = ev.replace("|", "\\|").replace("\n", " ")[:280]
                    out.append(f"| {dim} | {s_str} | {ev} |")
                out.append("")
        out.append("")

    return "\n".join(out)

# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Gemini model evaluation harness")
    ap.add_argument("--collect-only", action="store_true", help="Only collect model outputs")
    ap.add_argument("--score-only",   action="store_true", help="Only score existing outputs")
    ap.add_argument("--report-only",  action="store_true", help="Only regenerate report from state")
    args = ap.parse_args()

    state = load_state()
    print_progress(state)

    if not args.score_only and not args.report_only:
        state = collect_all(state)

    if not args.collect_only and not args.report_only:
        state = score_all(state)

    report = generate_report(state)
    REPORT_FILE.write_text(report, encoding="utf-8")
    log.info("Report written → %s", REPORT_FILE)

    print_progress(state)
    done  = sum(1 for c in state["cells"].values() if c["status"] == "done")
    quota = sum(1 for c in state["cells"].values() if c["status"] == "skipped-quota-exhausted")
    pend  = sum(1 for c in state["cells"].values() if c["status"] == "pending")
    print(f"Cells: {len(state['cells'])} total  |  done={done}  quota-skipped={quota}  pending={pend}")
    print(f"Report: {REPORT_FILE}\n")

if __name__ == "__main__":
    main()
