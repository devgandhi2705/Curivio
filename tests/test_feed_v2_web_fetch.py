"""
Feed v2 Phase 9b — web_researcher fetches full page content before claim extraction.

Proves the depth fix: extraction now reads FETCHED full page content, not the ~150-char
search snippet (shown against the old snippet baseline), that fetch batches at TinyFish's
10-URL cap, and that a fetch failure degrades cleanly to the snippet. One live test
(skipif no TinyFish key) does a real search+fetch and reports the batch count.
"""
import json
import os
import sqlite3

import pytest
import sqlite_vec

from backend.database.schema import ALL_TABLES, MIGRATIONS
from backend.services.feed_v2 import db as v2db
from backend.services.feed_v2.schema import run_v2_migrations
from backend.services.feed_v2.agents import web_researcher as W


_HAS_TINYFISH = bool(os.getenv("TINYFISH_API_KEY"))


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "webfetch.db")
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
    for s in ALL_TABLES:
        conn.execute(s)
    for m in MIGRATIONS:
        try:
            conn.execute(m) if not isinstance(m, (list, tuple)) else [conn.execute(x) for x in m]
        except sqlite3.OperationalError as e:
            if not any(k in str(e).lower() for k in ("already exists", "duplicate column", "no such column")):
                raise
    run_v2_migrations(conn)
    conn.commit(); conn.close()
    monkeypatch.setattr(v2db, "DB_PATH", path)
    return path

# A short search snippet vs the richer full page a fetch returns for the same url.
_SNIPPET = "Backprop is used in neural nets."
_FULL = ("Backpropagation applies the chain rule to propagate the loss gradient from the "
         "output layer back through each hidden layer, updating weights by gradient descent. "
         "It relies on the derivative of each activation function and is the foundation of "
         "modern deep learning optimisation.")   # phrases NOT present in the snippet


def _candidate_search(q):
    return [{"title": "Backprop", "url": "https://deep.com/backprop", "snippet": _SNIPPET}]


def _capture_call_agent(sink):
    """call_agent stub: records the extraction prompt, returns a fixed selection."""
    def fake(agent, messages, system="", **k):
        content = messages[0]["content"]
        if "WEB RESULTS" in content:
            sink.append(content)
            return {"passages": [{"index": 0, "claim": "backprop uses the chain rule", "why_relevant": "core"}]}
        return {"queries": ["backpropagation chain rule"]}
    return fake


# ── 1. extraction reads full content, not the snippet (with the old baseline) ─
def test_extraction_reads_full_content_not_snippet(monkeypatch, capsys):
    monkeypatch.setattr(W, "_search", _candidate_search)
    monkeypatch.setattr(W, "_material_text", lambda pid, limit=12: "")
    monkeypatch.setattr(W, "_user_link_urls", lambda pid: set())

    # OLD baseline: fetch returns nothing → extraction sees only the snippet.
    old_prompts: list[str] = []
    monkeypatch.setattr(W, "_fetch", lambda urls: {})
    monkeypatch.setattr(W, "call_agent", _capture_call_agent(old_prompts))
    W.run_web_research(project_id="p", journey_entry={"focus": "backprop"}, coverage_mode="open")

    # NEW: fetch returns full page content → extraction sees it.
    new_prompts: list[str] = []
    monkeypatch.setattr(W, "_fetch", lambda urls: {u: _FULL for u in urls})
    monkeypatch.setattr(W, "call_agent", _capture_call_agent(new_prompts))
    W.run_web_research(project_id="p", journey_entry={"focus": "backprop"}, coverage_mode="open")

    with capsys.disabled():
        print("\nOLD (snippet) extraction input has full-content phrase:", "gradient descent" in old_prompts[0])
        print("NEW (fetched)  extraction input has full-content phrase:", "gradient descent" in new_prompts[0])
    # the depth improvement, shown against the baseline:
    assert "gradient descent" not in old_prompts[0]     # snippet lacked the detail
    assert "gradient descent" in new_prompts[0]          # fetched full content carries it
    assert "hidden layer" in new_prompts[0]


# ── 2. fetch batches at TinyFish's 10-URL cap ─────────────────────────────────
def test_fetch_batches_at_ten(monkeypatch, capsys):
    monkeypatch.setenv("TINYFISH_API_KEY", "fake-key")
    monkeypatch.setattr(W, "_MOCK", False)
    batch_sizes: list[int] = []

    class _Resp:
        def __init__(self, urls): self._urls = urls
        def raise_for_status(self): pass
        def json(self): return {"results": [{"url": u, "text": f"content {u}"} for u in self._urls]}

    def fake_post(url, headers=None, json=None, timeout=None):
        urls = json["urls"]
        batch_sizes.append(len(urls))
        return _Resp(urls)
    monkeypatch.setattr(W.requests, "post", fake_post)

    urls = [f"https://x.com/{i}" for i in range(12)]     # 12 urls -> 2 batches (10 + 2)
    out = W._fetch(urls)
    with capsys.disabled():
        print(f"\n12 urls -> POST batch sizes {batch_sizes}; fetched {len(out)}")
    assert batch_sizes == [10, 2]                        # batched at the 10-cap, remainder in a 2nd call
    assert len(out) == 12 and all(out[u] for u in urls)


# ── 3. fetch failure degrades cleanly to the snippet (non-fatal) ──────────────
def test_fetch_failure_falls_back_to_snippet(monkeypatch, capsys):
    monkeypatch.setattr(W, "_search", lambda q: [
        {"title": "Fetched", "url": "https://ok.com/1", "snippet": "snippet-1"},
        {"title": "Unfetched", "url": "https://bad.com/2", "snippet": "snippet-2 fallback text"}])
    monkeypatch.setattr(W, "_material_text", lambda pid, limit=12: "")
    monkeypatch.setattr(W, "_user_link_urls", lambda pid: set())
    monkeypatch.setattr(W, "_fetch", lambda urls: {"https://ok.com/1": "FULL content for one only"})

    prompts: list[str] = []
    monkeypatch.setattr(W, "call_agent", _capture_call_agent(prompts))
    out = W.run_web_research(project_id="p", journey_entry={"focus": "t"}, coverage_mode="open")

    with capsys.disabled():
        print("\nprompt has fetched full:", "FULL content for one only" in prompts[0],
              "| has snippet fallback:", "snippet-2 fallback text" in prompts[0])
    assert "FULL content for one only" in prompts[0]     # fetched url uses full content
    assert "snippet-2 fallback text" in prompts[0]       # failed-fetch url falls back to its snippet
    assert out["web_findings"]                            # still produced findings, no error


# ── live: real search + real fetch, report batch count ────────────────────────
@pytest.mark.integration
@pytest.mark.skipif(not _HAS_TINYFISH, reason="no TinyFish API key")
def test_real_search_fetch_extraction_reports_batches(db, capsys):
    import logging
    records: list[str] = []

    class _H(logging.Handler):
        def emit(self, r): records.append(r.getMessage())
    lg = logging.getLogger("backend.services.feed_v2.agents.web_researcher")
    lg.setLevel(logging.INFO); lg.addHandler(_H())   # INFO: the batch-count line is logged at INFO

    out = W.run_web_research(project_id="p-none",
                             journey_entry={"focus": "how backpropagation trains neural networks"},
                             coverage_mode="open", keywords=["chain rule", "gradient descent"])
    batch_lines = [m for m in records if "in " in m and "batch(es)" in m]
    with capsys.disabled():
        print(f"\nLIVE fetch: {batch_lines}")
        print(f"findings ({len(out['web_findings'])}), sample claim:",
              out["web_findings"][0]["text"] if out["web_findings"] else "(none)")
    assert out["web_findings"], "real search+fetch produced no findings"
    assert batch_lines, "expected a fetch-batch log line"


# ══ Phase 9c: retain full page in state; own-code dedup (no LLM), not summarize ══

def test_dedup_normal_page_untouched():
    """A normal-sized page (under threshold) is returned byte-for-byte — never altered."""
    page = "Intro paragraph.\n\nSecond paragraph with detail.\nThird line."
    assert W._dedup_content(page) == page          # under _DEDUP_THRESHOLD_TOKENS → identity
    assert W._dedup_content("") == ""


def test_dedup_removes_boilerplate_keeps_all_unique(monkeypatch, capsys):
    """Oversized repetitive page: exact-duplicate boilerplate lines collapse to one,
    every unique line survives, order preserved. Shows size before vs after."""
    # threshold sits ABOVE the deduped size (~200 tok) but BELOW the boilerplate-bloated
    # original (~650 tok): dedup fires, the hard-cap does not, so we test dedup in isolation.
    monkeypatch.setattr(W, "_DEDUP_THRESHOLD_TOKENS", 300)
    boiler = ["Home", "About", "Login", "Footer © 2026"]   # repeated nav/footer on a scraped page
    unique = [f"Unique fact number {i} about the topic." for i in range(20)]
    # heavy boilerplate around the unique content, as a real scraped page would carry
    page = "\n".join(boiler * 30 + unique + boiler * 30)
    out = W._dedup_content(page)

    before, after = len(page), len(out)
    with capsys.disabled():
        print(f"\ndedup: {before} chars -> {after} chars ({before - after} removed)")
    assert after < before                                  # it shrank
    for u in unique:
        assert u in out                                    # NO unique content lost
    for b in boiler:
        assert out.count(b) == 1                           # each boiler line kept exactly once
    # exact character-set of unique lines is fully preserved (only dups removed)
    assert set(l for l in page.split("\n") if l) == set(l for l in out.split("\n") if l)


def test_dedup_hard_cap_last_resort(monkeypatch):
    """A genuinely long, all-UNIQUE page can't be shrunk by dedup → hard-capped to the
    threshold as a last resort (stated fallback, not the common path)."""
    monkeypatch.setattr(W, "_DEDUP_THRESHOLD_TOKENS", 20)
    page = "\n".join(f"Distinct sentence {i} carrying its own idea." for i in range(200))
    out = W._dedup_content(page)
    assert len(out) <= 20 * 4                               # capped to threshold tokens * 4 chars/token
    assert len(out) < len(page)


def test_full_content_retained_in_state(monkeypatch, capsys):
    """The finding now carries the FULL fetched page (`content`), not only the claim (`text`)."""
    full = ("Backpropagation applies the chain rule across layers. " * 8).strip()
    monkeypatch.setattr(W, "_search", lambda q: [
        {"title": "Backprop", "url": "https://deep.com/bp", "snippet": "short snippet"}])
    monkeypatch.setattr(W, "_material_text", lambda pid, limit=12: "")
    monkeypatch.setattr(W, "_user_link_urls", lambda pid: set())
    monkeypatch.setattr(W, "_fetch", lambda urls: {u: full for u in urls})
    monkeypatch.setattr(W, "call_agent", _capture_call_agent([]))

    out = W.run_web_research(project_id="p", journey_entry={"focus": "backprop"}, coverage_mode="open")
    f = out["web_findings"][0]
    with capsys.disabled():
        print(f"\nfinding: claim={f['text']!r} | content len={len(f['content'])}")
    assert f["content"] == full                             # full page retained in state
    assert f["text"] == "backprop uses the chain rule"      # claim still present (cheap summary)
    assert len(f["content"]) > len(f["text"])               # content is the richer field


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_TINYFISH, reason="no TinyFish API key")
def test_real_page_dedup_before_after(monkeypatch, capsys):
    """Fetch a REAL page, run dedup on it, show before/after, prove no unique line lost.

    Threshold is pinned to the deduped size so the DEDUP path runs (not the hard-cap),
    letting us assert the output equals an independent exact-line dedup of the real page —
    i.e. only duplicate lines were removed, every unique line survived."""
    fetched = W._fetch(["https://en.wikipedia.org/wiki/Backpropagation"])
    assert fetched, "real fetch returned nothing"
    raw = next(iter(fetched.values()))

    # independent reference: same exact-line dedup, keeping first occurrence + order
    seen, ref = set(), []
    for line in raw.split("\n"):
        k = line.strip()
        if k and k in seen:
            continue
        if k:
            seen.add(k)
        ref.append(line)
    reference = "\n".join(ref)

    monkeypatch.setattr(W, "_DEDUP_THRESHOLD_TOKENS", W.count_tokens(reference))  # dedup path, no hard-cap
    out = W._dedup_content(raw)

    dup_lines = raw.count("\n") + 1 - (reference.count("\n") + 1)
    with capsys.disabled():
        print(f"\nLIVE dedup: {len(raw)} -> {len(out)} chars; removed {dup_lines} duplicate line(s)")
    assert out == reference                                 # only exact-dup lines removed, unique kept
    raw_unique = {l.strip() for l in raw.split("\n") if l.strip()}
    out_unique = {l.strip() for l in out.split("\n") if l.strip()}
    assert out_unique == raw_unique                         # every unique line preserved
