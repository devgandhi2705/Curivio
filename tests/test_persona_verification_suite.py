"""
Phase 6.5 — Persona Verification Suite

Verifies that same-topic projects with different learner personas retrieve
meaningfully different content. Uses hardcoded intent profiles (representative
of LLM output) and a shared per-domain article pool.

Covers the five cases from the spec:
  Test 1 — Globalization / CBSE Economics Student
  Test 2 — Globalization / Startup Founder
  Test 3 — Artificial Intelligence / AIML Undergraduate
  Test 4 — Artificial Intelligence / CTO
  Test 5 — Supply Chain / Manufacturing CEO

All assertions run in standard pytest mode.
For the human-readable report:
    pytest tests/test_persona_verification_suite.py -v -s
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.retrieval_validator import filter_articles
from backend.services.source_ranker import _learning_score_article
from backend.services.retrieval_planner import _keyword_fallback


# ── Article pool ──────────────────────────────────────────────────────────────

# 7 economics articles — 4 student-aligned, 3 founder-aligned
ECONOMICS_ARTICLES: list[dict] = [
    {
        "title":   "WTO Trade Agreements Explained for Economics Students",
        "content": (
            "The World Trade Organization coordinates international trade agreements. "
            "Trade theory including comparative advantage explains why nations specialize. "
            "Economic policy shapes tariff and quota systems for student understanding."
        ),
        "url":    "https://edu.example.com/wto-trade-explained",
        "domain": "edu.example.com",
        "_tag":   "student",
    },
    {
        "title":   "Comparative Advantage Theory CBSE Economics Guide",
        "content": (
            "Comparative advantage theory in CBSE economics curriculum: when one country "
            "produces a good at lower opportunity cost, both nations benefit from specialization "
            "and trade. David Ricardo's theory forms the basis of international trade policy."
        ),
        "url":    "https://cbse.example.com/comparative-advantage",
        "domain": "cbse.example.com",
        "_tag":   "student",
    },
    {
        "title":   "History of Globalization Economic Origins Trade Routes",
        "content": (
            "The economic history of globalization traces back to colonial trade routes and "
            "mercantilism. Industrial revolution accelerated global economic integration. "
            "Trade patterns and economic theory evolved through distinct historical periods."
        ),
        "url":    "https://history.example.com/globalization-origins",
        "domain": "history.example.com",
        "_tag":   "student",
    },
    {
        "title":   "International Trade Policy Frameworks WTO Analysis",
        "content": (
            "International trade policy frameworks include free trade agreements, protectionism "
            "mechanisms, and regional trade blocs. Trade theory underpins policy formation. "
            "WTO trade policy coordination reduces global trade barriers and tariffs."
        ),
        "url":    "https://policy.example.com/trade-policy",
        "domain": "policy.example.com",
        "_tag":   "student",
    },
    {
        "title":   "Startup International Market Entry Strategy Guide",
        "content": (
            "Startup founders expanding internationally must evaluate market entry modes. "
            "Export strategy, joint ventures, and direct investment carry different regulatory "
            "risk profiles. Cross-border market entry requires understanding local business rules."
        ),
        "url":    "https://startup.example.com/market-entry",
        "domain": "startup.example.com",
        "_tag":   "founder",
    },
    {
        "title":   "Export Strategy for Early Stage Companies Global Expansion",
        "content": (
            "Export strategy for startups: identify target markets, evaluate trade barriers, "
            "assess currency risk. International expansion requires regulatory compliance. "
            "Market entry via exports minimises upfront investment while testing demand."
        ),
        "url":    "https://biz.example.com/export-strategy",
        "domain": "biz.example.com",
        "_tag":   "founder",
    },
    {
        "title":   "Cross-Border Regulatory Risk Trade Barriers International Expansion",
        "content": (
            "Cross-border regulatory compliance for startups expanding internationally: "
            "trade barriers, tariff schedules, customs compliance, and market access restrictions. "
            "International market entry requires regulatory risk assessment before expansion."
        ),
        "url":    "https://legal.example.com/regulatory-risk",
        "domain": "legal.example.com",
        "_tag":   "founder",
    },
]

# 6 AI articles — 3 student-aligned, 3 CTO-aligned
AI_ARTICLES: list[dict] = [
    {
        "title":   "Machine Learning Mathematical Foundations Neural Networks",
        "content": (
            "Machine learning foundations: linear algebra, calculus, and probability theory "
            "underpin all ML algorithms. Neural network architecture requires understanding "
            "matrix multiplication and gradient descent. Mathematical foundations are essential "
            "for understanding deep learning models."
        ),
        "url":    "https://ml.example.com/math-foundations",
        "domain": "ml.example.com",
        "_tag":   "student",
    },
    {
        "title":   "Deep Learning Transformers Architecture BERT GPT Explained",
        "content": (
            "Transformers architecture revolutionised deep learning. Self-attention mechanisms "
            "enable BERT and GPT language models. Understanding transformer architecture requires "
            "mathematical intuition about attention heads, embeddings, and positional encoding."
        ),
        "url":    "https://dl.example.com/transformers",
        "domain": "dl.example.com",
        "_tag":   "student",
    },
    {
        "title":   "Backpropagation Neural Networks Tutorial Undergraduate Learning",
        "content": (
            "Backpropagation algorithm enables neural network training. Chain rule calculus "
            "propagates gradients through layers. Understanding backpropagation is foundational "
            "for deep learning practitioners and undergraduate ML students learning fundamentals."
        ),
        "url":    "https://tutorial.example.com/backprop",
        "domain": "tutorial.example.com",
        "_tag":   "student",
    },
    {
        "title":   "AI ROI Measurement Enterprise Adoption Framework CTO Guide",
        "content": (
            "Measuring AI return on investment for enterprise leaders: ROI metrics, productivity "
            "benchmarks, and cost reduction tracking. AI adoption strategy requires board-level "
            "governance and executive decision-making frameworks. CTO guide to AI business value."
        ),
        "url":    "https://enterprise.example.com/ai-roi",
        "domain": "enterprise.example.com",
        "_tag":   "cto",
    },
    {
        "title":   "AI Governance Ethics Corporate Strategy Executive Board",
        "content": (
            "AI governance frameworks for corporate adoption: risk management, ethics policy, "
            "regulatory compliance, and board oversight. Executive AI strategy requires governance "
            "structure before deployment. Corporate AI adoption accountability and oversight."
        ),
        "url":    "https://corp.example.com/ai-governance",
        "domain": "corp.example.com",
        "_tag":   "cto",
    },
    {
        "title":   "LLM Production Deployment Strategy Enterprise Infrastructure Decision",
        "content": (
            "Enterprise LLM deployment decisions: build vs buy, cloud vs on-premise, vendor "
            "evaluation, and infrastructure strategy. CTO guide to production AI deployment. "
            "Total cost of ownership analysis for enterprise AI infrastructure adoption."
        ),
        "url":    "https://infra.example.com/llm-deployment",
        "domain": "infra.example.com",
        "_tag":   "cto",
    },
]

# 4 supply chain articles — all manufacturing-aligned
SUPPLY_CHAIN_ARTICLES: list[dict] = [
    {
        "title":   "Inventory Management Demand Forecasting Manufacturing Operations",
        "content": (
            "Inventory management and demand forecasting for manufacturing operations. "
            "Safety stock calculations, reorder points, and EOQ models reduce working capital. "
            "Demand forecasting accuracy improves procurement planning and reduces inventory costs."
        ),
        "url":    "https://ops.example.com/inventory",
        "domain": "ops.example.com",
        "_tag":   "manufacturing",
    },
    {
        "title":   "Logistics Optimisation Supply Chain Network Operations Efficiency",
        "content": (
            "Logistics optimisation reduces supply chain cost and lead time. Route optimisation, "
            "warehouse management, and carrier selection improve operational efficiency. "
            "Supply chain network design balances inventory, transportation, and facility costs."
        ),
        "url":    "https://logistics.example.com/optimisation",
        "domain": "logistics.example.com",
        "_tag":   "manufacturing",
    },
    {
        "title":   "Procurement Strategy Vendor Management Manufacturing Spend",
        "content": (
            "Procurement strategy for manufacturing: vendor evaluation, supplier qualification, "
            "contract negotiation, and spend management. Strategic procurement reduces total cost "
            "of ownership. Supplier relationship management improves supply chain resilience."
        ),
        "url":    "https://procurement.example.com/strategy",
        "domain": "procurement.example.com",
        "_tag":   "manufacturing",
    },
    {
        "title":   "Supply Chain Disruption Risk Management Resilience Planning",
        "content": (
            "Supply chain risk management: disruption scenarios, resilience strategies, and "
            "contingency planning for manufacturing operations. Multi-sourcing, safety stock, "
            "and near-shoring reduce supply chain disruption risk for manufacturers."
        ),
        "url":    "https://risk.example.com/supply-chain",
        "domain": "risk.example.com",
        "_tag":   "manufacturing",
    },
]


# ── Intent profiles ───────────────────────────────────────────────────────────

_STUDENT_ECON = {
    "persona":          "CBSE Economics Student",
    "goal":             "Master trade theory and economic concepts for board examinations",
    "industry_context": "Academic",
    "primary_focus":    "Trade theory, economic policy, and globalization history",
    "search_lens":      "Educational",
    "intent_summary":   "A CBSE student preparing for Class 12 economics board exams. Needs concept-level understanding of trade and globalization theories.",
}

_FOUNDER = {
    "persona":          "Startup Founder",
    "goal":             "Successfully expand startup operations into international markets",
    "industry_context": "Startup",
    "primary_focus":    "Market entry strategy, export frameworks, and cross-border regulatory compliance",
    "search_lens":      "Business Strategy",
    "intent_summary":   "A startup founder navigating international expansion. Needs actionable market entry intelligence and trade barrier awareness.",
}

_AIML_STUDENT = {
    "persona":          "AIML Undergraduate Student",
    "goal":             "Build strong mathematical and algorithmic foundations in machine learning",
    "industry_context": "Academic",
    "primary_focus":    "Deep learning architectures, mathematical foundations, and ML algorithms",
    "search_lens":      "Educational",
    "intent_summary":   "An undergraduate student building ML/DL foundations. Needs theory-first content on transformers, neural networks, and mathematics.",
}

_CTO = {
    "persona":          "Chief Technology Officer",
    "goal":             "Evaluate and implement AI adoption strategy across the organisation",
    "industry_context": "Enterprise",
    "primary_focus":    "AI governance, ROI measurement, deployment strategy, and executive decision-making",
    "search_lens":      "Business Strategy",
    "intent_summary":   "A CTO evaluating enterprise AI adoption. Needs ROI analysis, governance frameworks, and deployment risk assessment.",
}

_MANUFACTURING = {
    "persona":          "Manufacturing Company CEO",
    "goal":             "Optimise supply chain operations and reduce procurement costs",
    "industry_context": "Manufacturing",
    "primary_focus":    "Inventory management, demand forecasting, procurement strategy, and logistics efficiency",
    "search_lens":      "Business Strategy",
    "intent_summary":   "A manufacturing executive optimising operations. Needs demand forecasting, logistics optimisation, and procurement tools.",
}


# ── Pipeline helper ───────────────────────────────────────────────────────────

def _run_pipeline(
    profile:      dict,
    keywords:     list[str],
    topic:        str,
    domain:       str,
    articles:     list[dict],
    project_name: str = "",
    project_desc: str = "",
) -> tuple[list[dict], list[tuple[dict, dict]]]:
    """
    Filter articles through the validator, then score and rank survivors.
    Returns (passing_articles, sorted [(article, score_breakdown)] descending).
    """
    passing = filter_articles(
        articles, profile, None, keywords,
        mode="core",
        project_name=project_name,
        project_description=project_desc,
    )
    learning_ctx = {
        "intent_profile":  profile,
        "knowledge_state": None,
        "keywords":        keywords,
    }
    scored: list[tuple[dict, dict]] = []
    for article in passing:
        breakdown = _learning_score_article(article, topic, domain, learning_ctx)
        scored.append((article, breakdown))
    scored.sort(key=lambda x: x[1]["total"], reverse=True)
    return passing, scored


# ── Report helpers ────────────────────────────────────────────────────────────

_W = 66   # report width


def _hr(char: str = "=") -> str:
    return char * _W


def _row(text: str) -> str:
    return f"  {text}"


def _section(label: str) -> str:
    return f"\n  -- {label} {'-' * max(0, _W - len(label) - 6)}"


def _themes_in_top_n(
    scored:  list[tuple[dict, dict]],
    themes:  list[str],
    n:       int = 3,
) -> dict[str, bool]:
    """Return {theme: True/False} indicating presence in top-n titles."""
    top_text = " ".join(a["title"].lower() for a, _ in scored[:n])
    return {t: t.lower() in top_text for t in themes}


def _tags_in_top_n(scored: list[tuple[dict, dict]], tag: str, n: int = 3) -> list[str]:
    return [a["title"] for a, _ in scored[:n] if a.get("_tag") == tag]


def _print_report(
    test_num:        int,
    project_title:   str,
    project_desc:    str,
    profile:         dict,
    keywords:        list[str],
    articles:        list[dict],
    passing:         list[dict],
    scored:          list[tuple[dict, dict]],
    expected_themes: list[str],
    forbidden_tag:   str | None,
    passed:          bool,
) -> None:
    sep = _hr()
    print(f"\n{sep}")
    print(f"  TEST {test_num}  --  {project_title}  /  {profile['persona']}")
    print(sep)

    print(_section("INTENT PROFILE"))
    print(_row(f"Persona:       {profile['persona']}"))
    print(_row(f"Goal:          {profile['goal']}"))
    print(_row(f"Primary focus: {profile['primary_focus']}"))
    print(_row(f"Search lens:   {profile['search_lens']}"))

    queries = _keyword_fallback(profile, keywords, project_title)
    print(_section("TOP QUERIES  (keyword fallback — deterministic)"))
    for q in queries["core_queries"]:
        print(_row(f"  core  -> {q}"))
    for q in queries["adjacent_queries"]:
        print(_row(f"  adj   -> {q}"))
    for q in queries["serendipity_queries"]:
        print(_row(f"  sera  -> {q}"))

    discarded = [a for a in articles if a not in passing]
    print(_section(f"VALIDATION  ({len(passing)}/{len(articles)} articles passed alignment)"))
    if discarded:
        for a in discarded:
            print(_row(f"  [X]  {a['title'][:55]}"))
    else:
        print(_row("  all articles passed alignment check"))

    print(_section("TOP RANKED SOURCES"))
    for rank, (article, bd) in enumerate(scored[:5], 1):
        tag   = article.get("_tag", "?")
        score = bd["total"]
        intent = bd["intent_match"]
        title = article["title"][:52]
        print(_row(f"  #{rank}  [{score:.2f}  intent={intent:.2f}]  [{tag:12s}]  {title}"))

    print(_section("CHECKS"))
    theme_hits = _themes_in_top_n(scored, expected_themes)
    for theme, hit in theme_hits.items():
        icon = "[PASS]" if hit else "[FAIL]"
        print(_row(f"  {icon}  '{theme}' in top 3"))

    if forbidden_tag:
        bad = _tags_in_top_n(scored, forbidden_tag)
        icon = "[PASS]" if not bad else "[FAIL]"
        msg  = "none in top 3" if not bad else f"{len(bad)} in top 3: {bad[0][:40]}"
        print(_row(f"  {icon}  '{forbidden_tag}' content: {msg}"))

    print(_hr())
    status = "PASS" if passed else "FAIL"
    print(f"  RESULT: {status}")
    print(_hr())


# ── Test 1: Globalization — CBSE Economics Student ────────────────────────────

class TestGlobalizationStudent:
    PROFILE      = _STUDENT_ECON
    KEYWORDS     = ["globalization", "trade", "WTO", "economic history"]
    TOPIC        = "trade theory"
    DOMAIN       = "economics"
    PROJ_NAME    = "Globalization"
    PROJ_DESC    = "I am a CBSE economics student preparing for exams."
    EXPECTED     = ["trade", "WTO", "economic", "history"]
    FORBIDDEN    = "founder"

    def _run(self):
        return _run_pipeline(
            self.PROFILE, self.KEYWORDS, self.TOPIC, self.DOMAIN,
            ECONOMICS_ARTICLES, self.PROJ_NAME, self.PROJ_DESC,
        )

    def test_student_articles_pass_validation(self):
        passing, _ = self._run()
        student_passing = [a for a in passing if a.get("_tag") == "student"]
        assert len(student_passing) >= 3, (
            f"Expected ≥3 student articles to pass; got {len(student_passing)}"
        )

    def test_founder_articles_filtered_out(self):
        passing, _ = self._run()
        founder_passing = [a for a in passing if a.get("_tag") == "founder"]
        assert len(founder_passing) == 0, (
            f"Founder articles should not pass for CBSE Student; got: "
            f"{[a['title'] for a in founder_passing]}"
        )

    def test_expected_themes_in_top_3(self):
        _, scored = self._run()
        assert len(scored) >= 1, "No articles survived validation"
        hits = _themes_in_top_n(scored, self.EXPECTED)
        missing = [t for t, hit in hits.items() if not hit]
        assert len(missing) <= 1, (
            f"Expected themes missing from top 3: {missing}. "
            f"Top titles: {[a['title'] for a, _ in scored[:3]]}"
        )

    def test_founder_content_not_in_top_3(self):
        _, scored = self._run()
        bad = _tags_in_top_n(scored, "founder")
        assert not bad, f"Founder articles in top 3: {bad}"

    def test_report(self, capsys):
        passing, scored = self._run()
        hits   = _themes_in_top_n(scored, self.EXPECTED)
        passed = (
            len([a for a in passing if a.get("_tag") == "founder"]) == 0
            and sum(hits.values()) >= len(self.EXPECTED) - 1
        )
        _print_report(
            1, self.PROJ_NAME, self.PROJ_DESC, self.PROFILE, self.KEYWORDS,
            ECONOMICS_ARTICLES, passing, scored, self.EXPECTED, self.FORBIDDEN, passed,
        )
        with capsys.disabled():
            pass   # report goes to stdout when running with -s


# ── Test 2: Globalization — Startup Founder ───────────────────────────────────

class TestGlobalizationFounder:
    PROFILE   = _FOUNDER
    KEYWORDS  = ["globalization", "market entry", "exports", "international expansion"]
    TOPIC     = "market entry strategy"
    DOMAIN    = "startup"
    PROJ_NAME = "Globalization"
    PROJ_DESC = "I am a startup founder expanding internationally."
    EXPECTED  = ["market", "export", "regulatory", "international"]
    FORBIDDEN = "student"

    def _run(self):
        return _run_pipeline(
            self.PROFILE, self.KEYWORDS, self.TOPIC, self.DOMAIN,
            ECONOMICS_ARTICLES, self.PROJ_NAME, self.PROJ_DESC,
        )

    def test_founder_articles_pass_validation(self):
        passing, _ = self._run()
        founder_passing = [a for a in passing if a.get("_tag") == "founder"]
        assert len(founder_passing) >= 2, (
            f"Expected ≥2 founder articles to pass; got {len(founder_passing)}"
        )

    def test_cbse_content_not_in_top_3(self):
        """
        The CBSE-specific article may survive alignment (it mentions 'international
        trade policy', sharing one token with the Founder's goal) but must not
        outrank the three explicitly founder-aligned articles.
        """
        _, scored = self._run()
        cbse_in_top3 = [a for a, _ in scored[:3] if "cbse" in a["url"]]
        assert not cbse_in_top3, (
            f"CBSE article appeared in top 3 for Startup Founder: "
            f"{[a['title'] for a in cbse_in_top3]}"
        )

    def test_expected_themes_in_top_3(self):
        _, scored = self._run()
        assert len(scored) >= 1, "No articles survived validation"
        hits = _themes_in_top_n(scored, self.EXPECTED)
        missing = [t for t, hit in hits.items() if not hit]
        assert len(missing) <= 1, (
            f"Expected themes missing from top 3: {missing}. "
            f"Top titles: {[a['title'] for a, _ in scored[:3]]}"
        )

    def test_founder_content_outranks_student_content(self):
        """Any student articles that survived must rank below founder articles."""
        _, scored = self._run()
        tags = [a.get("_tag") for a, _ in scored]
        if "student" in tags and "founder" in tags:
            first_founder = tags.index("founder")
            first_student = tags.index("student")
            assert first_founder < first_student, (
                f"Founder content ({first_founder}) should outrank student ({first_student})"
            )

    def test_report(self, capsys):
        passing, scored = self._run()
        hits   = _themes_in_top_n(scored, self.EXPECTED)
        cbse_t3 = [a for a, _ in scored[:3] if "cbse" in a["url"]]
        passed = (not cbse_t3 and sum(hits.values()) >= len(self.EXPECTED) - 1)
        _print_report(
            2, self.PROJ_NAME, self.PROJ_DESC, self.PROFILE, self.KEYWORDS,
            ECONOMICS_ARTICLES, passing, scored, self.EXPECTED, self.FORBIDDEN, passed,
        )
        with capsys.disabled():
            pass


# ── Test 3: Artificial Intelligence — AIML Undergraduate ─────────────────────

class TestAIStudent:
    PROFILE   = _AIML_STUDENT
    KEYWORDS  = ["machine learning", "deep learning", "transformers", "neural networks"]
    TOPIC     = "machine learning"
    DOMAIN    = "computer science"
    PROJ_NAME = "Artificial Intelligence"
    PROJ_DESC = "I am an AIML undergraduate learning foundations."
    EXPECTED  = ["machine learning", "deep learning", "transformers", "neural"]
    FORBIDDEN = "cto"

    def _run(self):
        return _run_pipeline(
            self.PROFILE, self.KEYWORDS, self.TOPIC, self.DOMAIN,
            AI_ARTICLES, self.PROJ_NAME, self.PROJ_DESC,
        )

    def test_student_articles_pass_validation(self):
        passing, _ = self._run()
        student_passing = [a for a in passing if a.get("_tag") == "student"]
        assert len(student_passing) >= 2, (
            f"Expected ≥2 student articles to pass; got {len(student_passing)}"
        )

    def test_cto_articles_filtered_or_ranked_low(self):
        """CTO-specific articles either filtered or below rank 3."""
        passing, scored = self._run()
        cto_in_top3 = _tags_in_top_n(scored, "cto")
        assert not cto_in_top3, f"CTO articles in top 3 for AIML Student: {cto_in_top3}"

    def test_expected_themes_in_top_3(self):
        _, scored = self._run()
        assert len(scored) >= 1, "No articles survived validation"
        hits = _themes_in_top_n(scored, self.EXPECTED)
        missing = [t for t, hit in hits.items() if not hit]
        assert len(missing) <= 1, (
            f"Expected themes missing from top 3: {missing}. "
            f"Top titles: {[a['title'] for a, _ in scored[:3]]}"
        )

    def test_report(self, capsys):
        passing, scored = self._run()
        hits   = _themes_in_top_n(scored, self.EXPECTED)
        cto_t3 = _tags_in_top_n(scored, "cto")
        passed = (not cto_t3 and sum(hits.values()) >= len(self.EXPECTED) - 1)
        _print_report(
            3, self.PROJ_NAME, self.PROJ_DESC, self.PROFILE, self.KEYWORDS,
            AI_ARTICLES, passing, scored, self.EXPECTED, self.FORBIDDEN, passed,
        )
        with capsys.disabled():
            pass


# ── Test 4: Artificial Intelligence — CTO ────────────────────────────────────

class TestAICTO:
    PROFILE   = _CTO
    KEYWORDS  = ["AI strategy", "governance", "ROI", "enterprise deployment"]
    TOPIC     = "AI adoption"
    DOMAIN    = "enterprise"
    PROJ_NAME = "Artificial Intelligence"
    PROJ_DESC = "I am a CTO evaluating AI adoption."
    EXPECTED  = ["ROI", "governance", "deployment", "enterprise"]
    FORBIDDEN = "student"

    def _run(self):
        return _run_pipeline(
            self.PROFILE, self.KEYWORDS, self.TOPIC, self.DOMAIN,
            AI_ARTICLES, self.PROJ_NAME, self.PROJ_DESC,
        )

    def test_cto_articles_pass_validation(self):
        passing, _ = self._run()
        cto_passing = [a for a in passing if a.get("_tag") == "cto"]
        assert len(cto_passing) >= 2, (
            f"Expected ≥2 CTO articles to pass; got {len(cto_passing)}"
        )

    def test_student_articles_filtered_or_ranked_low(self):
        _, scored = self._run()
        student_in_top3 = _tags_in_top_n(scored, "student")
        assert not student_in_top3, f"Student articles in top 3 for CTO: {student_in_top3}"

    def test_expected_themes_in_top_3(self):
        _, scored = self._run()
        assert len(scored) >= 1, "No articles survived validation"
        hits = _themes_in_top_n(scored, self.EXPECTED)
        missing = [t for t, hit in hits.items() if not hit]
        assert len(missing) <= 1, (
            f"Expected themes missing from top 3: {missing}. "
            f"Top titles: {[a['title'] for a, _ in scored[:3]]}"
        )

    def test_cto_outranks_student(self):
        _, scored = self._run()
        tags = [a.get("_tag") for a, _ in scored]
        if "student" in tags and "cto" in tags:
            first_cto     = tags.index("cto")
            first_student = tags.index("student")
            assert first_cto < first_student, (
                f"CTO content ({first_cto}) should outrank student ({first_student})"
            )

    def test_report(self, capsys):
        passing, scored = self._run()
        hits       = _themes_in_top_n(scored, self.EXPECTED)
        student_t3 = _tags_in_top_n(scored, "student")
        passed     = (not student_t3 and sum(hits.values()) >= len(self.EXPECTED) - 1)
        _print_report(
            4, self.PROJ_NAME, self.PROJ_DESC, self.PROFILE, self.KEYWORDS,
            AI_ARTICLES, passing, scored, self.EXPECTED, self.FORBIDDEN, passed,
        )
        with capsys.disabled():
            pass


# ── Test 5: Supply Chain — Manufacturing CEO ──────────────────────────────────

class TestSupplyChainManufacturing:
    PROFILE   = _MANUFACTURING
    KEYWORDS  = ["inventory", "forecasting", "logistics", "procurement", "manufacturing"]
    TOPIC     = "supply chain operations"
    DOMAIN    = "manufacturing"
    PROJ_NAME = "Supply Chain"
    PROJ_DESC = "I run a manufacturing company."
    EXPECTED  = ["inventory", "logistics", "procurement", "supply chain"]

    def _run(self):
        return _run_pipeline(
            self.PROFILE, self.KEYWORDS, self.TOPIC, self.DOMAIN,
            SUPPLY_CHAIN_ARTICLES, self.PROJ_NAME, self.PROJ_DESC,
        )

    def test_all_supply_chain_articles_pass_validation(self):
        passing, _ = self._run()
        assert len(passing) >= 3, (
            f"Expected ≥3 supply chain articles to pass; got {len(passing)}"
        )

    def test_expected_themes_in_top_3(self):
        _, scored = self._run()
        assert len(scored) >= 1, "No articles survived validation"
        hits = _themes_in_top_n(scored, self.EXPECTED)
        missing = [t for t, hit in hits.items() if not hit]
        assert len(missing) <= 1, (
            f"Expected themes missing from top 3: {missing}. "
            f"Top titles: {[a['title'] for a, _ in scored[:3]]}"
        )

    def test_all_ranked_articles_are_manufacturing(self):
        _, scored = self._run()
        non_mfg = [a["title"] for a, _ in scored if a.get("_tag") != "manufacturing"]
        assert not non_mfg, f"Non-manufacturing articles survived: {non_mfg}"

    def test_report(self, capsys):
        passing, scored = self._run()
        hits   = _themes_in_top_n(scored, self.EXPECTED)
        passed = len(passing) >= 3 and sum(hits.values()) >= len(self.EXPECTED) - 1
        _print_report(
            5, self.PROJ_NAME, self.PROJ_DESC, self.PROFILE, self.KEYWORDS,
            SUPPLY_CHAIN_ARTICLES, passing, scored, self.EXPECTED, None, passed,
        )
        with capsys.disabled():
            pass


# ── Cross-persona differentiation — same topic, two personas ─────────────────

class TestPersonaDifferentiation:
    """
    Verifies the core requirement: same project title + topic but different
    descriptions must produce meaningfully different ranked results.
    """

    def test_globalization_student_vs_founder_top3_differ(self):
        _, student_scored = _run_pipeline(
            _STUDENT_ECON, ["globalization", "trade", "WTO"], "trade theory", "economics",
            ECONOMICS_ARTICLES,
        )
        _, founder_scored = _run_pipeline(
            _FOUNDER, ["globalization", "market entry", "exports"], "market entry", "startup",
            ECONOMICS_ARTICLES,
        )
        student_top3 = {a["url"] for a, _ in student_scored[:3]}
        founder_top3 = {a["url"] for a, _ in founder_scored[:3]}
        overlap = student_top3 & founder_top3
        assert len(overlap) < 2, (
            f"Student and Founder top-3 overlap too much ({len(overlap)}/3 shared): "
            f"{[a['title'] for a, _ in student_scored[:3]]} vs "
            f"{[a['title'] for a, _ in founder_scored[:3]]}"
        )

    def test_ai_student_vs_cto_top3_differ(self):
        _, student_scored = _run_pipeline(
            _AIML_STUDENT, ["machine learning", "deep learning", "transformers"],
            "machine learning", "computer science", AI_ARTICLES,
        )
        _, cto_scored = _run_pipeline(
            _CTO, ["AI strategy", "governance", "ROI", "enterprise"],
            "AI adoption", "enterprise", AI_ARTICLES,
        )
        student_top3 = {a["url"] for a, _ in student_scored[:3]}
        cto_top3     = {a["url"] for a, _ in cto_scored[:3]}
        overlap      = student_top3 & cto_top3
        assert len(overlap) < 2, (
            f"AIML Student and CTO top-3 overlap too much ({len(overlap)}/3 shared)"
        )

    def test_student_top3_are_student_tagged(self):
        _, scored = _run_pipeline(
            _STUDENT_ECON, ["globalization", "trade", "WTO"], "trade theory", "economics",
            ECONOMICS_ARTICLES,
        )
        tags_top3 = [a.get("_tag") for a, _ in scored[:3]]
        assert all(t == "student" for t in tags_top3), (
            f"Student top-3 not all student-tagged: {tags_top3}"
        )

    def test_founder_top3_are_founder_tagged(self):
        _, scored = _run_pipeline(
            _FOUNDER, ["globalization", "market entry", "exports"], "market entry", "startup",
            ECONOMICS_ARTICLES,
        )
        tags_top3 = [a.get("_tag") for a, _ in scored[:3]]
        assert all(t == "founder" for t in tags_top3), (
            f"Founder top-3 not all founder-tagged: {tags_top3}"
        )
