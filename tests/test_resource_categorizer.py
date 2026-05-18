"""
Tests for the rule-based resource categorizer.

Test levels
-----------
1.  PrefixRules          — "Book:", "Course:", "Paper:", "Docs:", "Repo:", "Video:"
2.  UrlDomainRules        — github.com, arxiv.org, youtube.com, readthedocs.io,
                            medium.com, coursera.org, and other known platforms
3.  UrlPathHeuristics     — /docs/, /blog/, /papers/, /watch/ in unrecognised URLs
4.  KeywordRules          — plain-text keyword matching
5.  DefaultFallback       — unknown resources → blog_post
6.  ConfidenceOrdering    — prefix (1.0) > domain (0.85–0.95) > keyword (0.6–0.7) > default (0.3)
7.  EdgeCases             — empty string, whitespace, URLs with query params and fragments
8.  BatchCategorization   — categorize_resources returns one result per input
9.  SummaryCount          — category count dict is accurate
10. EndpointCategorize    — POST /categorize HTTP shape and 422 validation

No DB, no mocking required for pure-logic tests.
Endpoint tests patch at backend.main.* level.

Run:
    pytest tests/test_resource_categorizer.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.resource_categorizer import (
    _classify,
    categorize_resource,
    categorize_resources,
)


# ── Shared assertion helpers ───────────────────────────────────────────────────

def _assert_category(resource: str, expected: str):
    result = categorize_resource(resource)
    assert result["category"] == expected, (
        f"Expected {expected!r} for {resource!r}, got {result['category']!r}"
    )

def _assert_confidence_gte(resource: str, min_conf: float):
    result = categorize_resource(resource)
    assert result["confidence"] >= min_conf, (
        f"Expected confidence >= {min_conf} for {resource!r}, got {result['confidence']}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PrefixRules
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrefixRules:
    def test_repo_prefix(self):
        _assert_category("Repo: facebookresearch/faiss — github.com/facebookresearch/faiss",
                         "github_repository")

    def test_paper_prefix(self):
        _assert_category("Paper: Attention is All You Need (Vaswani et al., 2017)",
                         "research_paper")

    def test_docs_prefix(self):
        _assert_category("Docs: PyTorch Documentation — pytorch.org/docs",
                         "documentation")

    def test_documentation_prefix(self):
        _assert_category("Documentation: LangChain API Reference", "documentation")

    def test_course_prefix(self):
        _assert_category("Course: Fast.ai Practical Deep Learning — fast.ai",
                         "tutorial")

    def test_tutorial_prefix(self):
        _assert_category("Tutorial: Building RAG with LlamaIndex", "tutorial")

    def test_video_prefix(self):
        _assert_category("Video: Andrej Karpathy — Let's build GPT",
                         "video")

    def test_book_prefix_maps_to_tutorial(self):
        _assert_category("Book: Mathematics for Machine Learning by Deisenroth (2020)",
                         "tutorial")

    def test_blog_prefix(self):
        _assert_category("Blog: The Illustrated Transformer — Jay Alammar",
                         "blog_post")

    def test_prefix_case_insensitive(self):
        _assert_category("PAPER: BERT: Pre-training of Deep Bidirectional Transformers",
                         "research_paper")
        _assert_category("repo: openai/openai-python",
                         "github_repository")

    def test_prefix_confidence_is_high(self):
        _assert_confidence_gte("Repo: anything", 0.9)
        _assert_confidence_gte("Paper: anything", 0.9)
        _assert_confidence_gte("Docs: anything", 0.9)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. UrlDomainRules
# ═══════════════════════════════════════════════════════════════════════════════

class TestUrlDomainRules:
    # GitHub
    def test_github_com(self):
        _assert_category("https://github.com/facebookresearch/faiss", "github_repository")

    def test_github_com_with_path(self):
        _assert_category("https://github.com/openai/openai-python/tree/main/src",
                         "github_repository")

    def test_github_io_is_documentation(self):
        _assert_category("https://langchain-ai.github.io/langgraph/", "documentation")

    # Research papers
    def test_arxiv(self):
        _assert_category("https://arxiv.org/abs/1706.03762", "research_paper")

    def test_arxiv_pdf(self):
        _assert_category("https://arxiv.org/pdf/2005.11401", "research_paper")

    def test_openreview(self):
        _assert_category("https://openreview.net/forum?id=abc123", "research_paper")

    def test_aclanthology(self):
        _assert_category("https://aclanthology.org/2023.acl-long.1/", "research_paper")

    def test_semanticscholar(self):
        _assert_category("https://www.semanticscholar.org/paper/abc/123", "research_paper")

    # Video
    def test_youtube_watch(self):
        _assert_category("https://www.youtube.com/watch?v=abc123", "video")

    def test_youtube_short(self):
        _assert_category("https://youtu.be/dQw4w9WgXcQ", "video")

    def test_vimeo(self):
        _assert_category("https://vimeo.com/123456789", "video")

    def test_loom(self):
        _assert_category("https://www.loom.com/share/abc123", "video")

    # Documentation
    def test_readthedocs_io(self):
        _assert_category("https://langchain.readthedocs.io/en/latest/", "documentation")

    def test_docs_subdomain(self):
        _assert_category("https://docs.python.org/3/library/pathlib.html", "documentation")

    def test_developer_subdomain(self):
        _assert_category("https://developer.mozilla.org/en-US/docs/Web/API",
                         "documentation")

    # Tutorial platforms
    def test_coursera(self):
        _assert_category("https://www.coursera.org/learn/machine-learning", "tutorial")

    def test_udemy(self):
        _assert_category("https://www.udemy.com/course/pytorch-deep-learning/", "tutorial")

    def test_fast_ai(self):
        _assert_category("https://course.fast.ai/", "tutorial")

    def test_deeplearning_ai(self):
        _assert_category("https://www.deeplearning.ai/courses/", "tutorial")

    def test_edx(self):
        _assert_category("https://www.edx.org/course/introduction-to-python", "tutorial")

    def test_datacamp(self):
        _assert_category("https://www.datacamp.com/courses/intro-to-sql", "tutorial")

    # Blog / article
    def test_medium(self):
        _assert_category("https://medium.com/@user/my-article-abc", "blog_post")

    def test_towardsdatascience(self):
        _assert_category("https://towardsdatascience.com/understanding-bert-abc123",
                         "blog_post")

    def test_substack(self):
        _assert_category("https://newsletter.example.substack.com/p/issue-42", "blog_post")

    def test_devto(self):
        _assert_category("https://dev.to/user/my-post", "blog_post")

    def test_distill_pub(self):
        _assert_category("https://distill.pub/2016/augmented-rnns/", "blog_post")

    def test_domain_confidence_is_high(self):
        _assert_confidence_gte("https://github.com/openai/openai-python", 0.85)
        _assert_confidence_gte("https://arxiv.org/abs/1234.5678", 0.85)
        _assert_confidence_gte("https://www.youtube.com/watch?v=x", 0.85)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. UrlPathHeuristics
# ═══════════════════════════════════════════════════════════════════════════════

class TestUrlPathHeuristics:
    def test_docs_in_path(self):
        _assert_category("https://unknownsite.io/docs/getting-started", "documentation")

    def test_api_in_path(self):
        _assert_category("https://unknownsite.io/api/reference", "documentation")

    def test_blog_in_path(self):
        _assert_category("https://unknownsite.io/blog/my-post", "blog_post")

    def test_papers_in_path(self):
        _assert_category("https://unknownsite.io/papers/2024/attention", "research_paper")

    def test_tutorial_in_path(self):
        _assert_category("https://unknownsite.io/tutorial/step-1", "tutorial")

    def test_watch_in_path(self):
        _assert_category("https://unknownsite.io/watch/lecture-3", "video")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. KeywordRules
# ═══════════════════════════════════════════════════════════════════════════════

class TestKeywordRules:
    def test_arxiv_keyword(self):
        _assert_category("The arxiv paper on transformers is foundational.", "research_paper")

    def test_proceedings_keyword(self):
        _assert_category("Published in NeurIPS proceedings 2022.", "research_paper")

    def test_paper_keyword(self):
        _assert_category("This paper introduces a novel architecture.", "research_paper")

    def test_tutorial_keyword(self):
        _assert_category("A step-by-step tutorial for beginners.", "tutorial")

    def test_guide_keyword(self):
        _assert_category("Beginner's guide to PyTorch.", "tutorial")

    def test_course_keyword(self):
        _assert_category("Online course for data scientists.", "tutorial")

    def test_documentation_keyword(self):
        _assert_category("Official documentation for the library.", "documentation")

    def test_readme_keyword(self):
        _assert_category("README file with usage examples.", "documentation")

    def test_video_keyword(self):
        _assert_category("Lecture video from Stanford CS229.", "video")

    def test_talk_keyword(self):
        _assert_category("Recorded talk from NeurIPS 2023.", "video")

    def test_blog_keyword(self):
        _assert_category("An interesting blog post about LLMs.", "blog_post")

    def test_article_keyword(self):
        _assert_category("Article explaining transformer attention.", "blog_post")

    def test_github_keyword(self):
        _assert_category("A GitHub repository with example code.", "github_repository")

    def test_repo_keyword(self):
        _assert_category("This open-source repo contains the implementation.", "github_repository")

    def test_keyword_confidence_lower_than_domain(self):
        keyword_conf = categorize_resource("A tutorial on embeddings.")["confidence"]
        domain_conf  = categorize_resource("https://www.udemy.com/course/x")["confidence"]
        assert keyword_conf < domain_conf


# ═══════════════════════════════════════════════════════════════════════════════
# 5. DefaultFallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaultFallback:
    def test_unknown_url_defaults_to_blog_post(self):
        _assert_category("https://www.somerandomblogsite.xyz/post/thing", "blog_post")

    def test_plain_text_no_keywords_defaults_to_blog_post(self):
        _assert_category("This is a resource about machine learning.", "blog_post")

    def test_default_confidence_is_low(self):
        result = categorize_resource("https://totally-unknown-random-site.example.com/xyz")
        assert result["confidence"] <= 0.40


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ConfidenceOrdering
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfidenceOrdering:
    def test_prefix_beats_domain(self):
        # "Docs:" prefix (conf=1.0) on a YouTube URL → documentation, not video
        result = categorize_resource("Docs: https://www.youtube.com/watch?v=x")
        assert result["category"] == "documentation"
        assert result["confidence"] == 1.0

    def test_prefix_beats_keyword(self):
        # "Repo:" prefix → github_repository even if text says "blog"
        result = categorize_resource("Repo: great blog-style repo for learning")
        assert result["category"] == "github_repository"

    def test_domain_beats_keyword(self):
        # arxiv.org URL → research_paper even if text says "tutorial"
        result = categorize_resource("https://arxiv.org/abs/1234 — a tutorial paper")
        assert result["category"] == "research_paper"
        assert result["confidence"] >= 0.9

    def test_prefix_confidence_is_highest(self):
        prefix_conf  = categorize_resource("Paper: anything")["confidence"]
        domain_conf  = categorize_resource("https://arxiv.org/abs/x")["confidence"]
        keyword_conf = categorize_resource("This is a paper about X.")["confidence"]
        default_conf = categorize_resource("https://unrecognized.example.com/x")["confidence"]
        assert prefix_conf >= domain_conf >= keyword_conf >= default_conf


# ═══════════════════════════════════════════════════════════════════════════════
# 7. EdgeCases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_string(self):
        result = categorize_resource("")
        assert result["category"] == "blog_post"
        assert result["confidence"] == 0.30

    def test_whitespace_only(self):
        result = categorize_resource("   ")
        assert result["category"] == "blog_post"

    def test_url_with_query_params(self):
        _assert_category("https://arxiv.org/search/?query=transformer&searchtype=all",
                         "research_paper")

    def test_url_with_fragment(self):
        _assert_category("https://docs.python.org/3/library/pathlib.html#pathlib.Path",
                         "documentation")

    def test_resource_stripped_of_whitespace(self):
        result = categorize_resource("  Repo: openai/openai-python  ")
        assert result["resource"] == "Repo: openai/openai-python"
        assert result["category"] == "github_repository"

    def test_result_contains_all_fields(self):
        result = categorize_resource("https://arxiv.org/abs/1706.03762")
        assert "resource" in result
        assert "category" in result
        assert "confidence" in result

    def test_confidence_is_rounded_to_two_decimals(self):
        result = categorize_resource("Paper: some title")
        assert result["confidence"] == round(result["confidence"], 2)

    def test_non_http_url_falls_through_to_keyword(self):
        # ftp:// URLs are not parsed as HTTP; should fall through to keyword/default
        result = categorize_resource("ftp://some-archive.org/papers/file.pdf")
        # "papers" keyword in path won't be parsed (not http), might match keyword "paper"
        # The important thing is it doesn't crash and returns a valid category
        assert result["category"] in (
            "tutorial", "research_paper", "github_repository",
            "documentation", "blog_post", "video",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 8. BatchCategorization
# ═══════════════════════════════════════════════════════════════════════════════

class TestBatchCategorization:
    def test_returns_one_result_per_input(self):
        resources = [
            "https://arxiv.org/abs/1706.03762",
            "https://github.com/openai/openai-python",
            "Course: Fast.ai Part 1",
        ]
        results = categorize_resources(resources)
        assert len(results) == 3

    def test_preserves_order(self):
        resources = [
            "Paper: Attention is All You Need",
            "https://www.youtube.com/watch?v=x",
            "Repo: torvalds/linux",
        ]
        results = categorize_resources(resources)
        assert results[0]["category"] == "research_paper"
        assert results[1]["category"] == "video"
        assert results[2]["category"] == "github_repository"

    def test_empty_list_returns_empty(self):
        assert categorize_resources([]) == []

    def test_mixed_categories(self):
        resources = [
            "https://medium.com/@user/article",
            "https://docs.python.org/3/",
            "https://www.youtube.com/watch?v=abc",
        ]
        results = categorize_resources(resources)
        categories = {r["category"] for r in results}
        assert "blog_post" in categories
        assert "documentation" in categories
        assert "video" in categories

    def test_each_result_has_required_fields(self):
        results = categorize_resources(["https://arxiv.org/abs/1234"])
        assert all("resource" in r and "category" in r and "confidence" in r
                   for r in results)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. SummaryCount
# ═══════════════════════════════════════════════════════════════════════════════

class TestSummaryCount:
    def test_summary_via_endpoint(self):
        """Summary counts match actual result categories."""
        resources = [
            "https://arxiv.org/abs/1706",          # research_paper
            "https://arxiv.org/abs/9999",          # research_paper
            "https://github.com/openai/gpt",       # github_repository
            "https://www.youtube.com/watch?v=x",   # video
        ]
        from collections import Counter
        from backend.services.resource_categorizer import categorize_resources as cr
        results = cr(resources)
        counts = dict(Counter(r["category"] for r in results))
        assert counts.get("research_paper", 0) == 2
        assert counts.get("github_repository", 0) == 1
        assert counts.get("video", 0) == 1

    def test_summary_keys_are_valid_categories(self):
        from collections import Counter
        from backend.services.resource_categorizer import categorize_resources as cr
        valid = {"tutorial", "research_paper", "github_repository",
                 "documentation", "blog_post", "video"}
        results = cr(["Paper: X", "Repo: Y", "Video: Z", "Docs: W"])
        counts  = dict(Counter(r["category"] for r in results))
        assert all(k in valid for k in counts)


# ═══════════════════════════════════════════════════════════════════════════════
# 10. EndpointCategorize
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndpointCategorize:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        return TestClient(app)

    def test_returns_200(self, client):
        resp = client.post("/categorize", json={"resources": ["https://arxiv.org/abs/1234"]})
        assert resp.status_code == 200

    def test_empty_resources_returns_422(self, client):
        resp = client.post("/categorize", json={"resources": []})
        assert resp.status_code == 422

    def test_missing_resources_returns_422(self, client):
        resp = client.post("/categorize", json={})
        assert resp.status_code == 422

    def test_response_has_results_and_summary(self, client):
        resp = client.post("/categorize", json={"resources": ["Paper: Transformers"]})
        body = resp.json()
        assert "results" in body and "summary" in body

    def test_results_count_matches_input(self, client):
        resources = ["https://arxiv.org/abs/1", "https://github.com/x/y",
                     "https://www.youtube.com/watch?v=z"]
        resp  = client.post("/categorize", json={"resources": resources})
        assert len(resp.json()["results"]) == 3

    def test_each_result_has_category_and_confidence(self, client):
        resp = client.post("/categorize", json={"resources": ["https://arxiv.org/abs/1"]})
        item = resp.json()["results"][0]
        assert "category" in item and "confidence" in item and "resource" in item

    def test_summary_is_dict(self, client):
        resp = client.post("/categorize",
                           json={"resources": ["Paper: X", "Repo: Y"]})
        assert isinstance(resp.json()["summary"], dict)

    def test_summary_counts_correct(self, client):
        resources = [
            "https://arxiv.org/abs/111",   # research_paper
            "https://arxiv.org/abs/222",   # research_paper
            "https://github.com/a/b",      # github_repository
        ]
        resp    = client.post("/categorize", json={"resources": resources})
        summary = resp.json()["summary"]
        assert summary.get("research_paper") == 2
        assert summary.get("github_repository") == 1

    def test_github_url_categorized_as_github_repository(self, client):
        resp = client.post("/categorize",
                           json={"resources": ["https://github.com/openai/openai-python"]})
        assert resp.json()["results"][0]["category"] == "github_repository"

    def test_youtube_url_categorized_as_video(self, client):
        resp = client.post("/categorize",
                           json={"resources": ["https://www.youtube.com/watch?v=abc"]})
        assert resp.json()["results"][0]["category"] == "video"
