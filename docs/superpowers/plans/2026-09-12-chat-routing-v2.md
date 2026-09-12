# Chat Routing v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace chat's duplicated routing (LLM classifier -> task_type -> model_priority -> LangGraph agent + regex action router + model-invoked search tool) with one traceable path: classifier -> TurnPlan -> one TOML model list -> plain streaming fallback loop, with one retry/skip policy and `route`/`route_step` on every log row.

**Architecture:** A JSON classifier runs on every turn concurrently with context prep. `plan_turn()` merges its answer with the user's toggles into a `TurnPlan` (route, search, simple tone, crisis). If the plan says search, `chat_service` runs TinyFish itself and injects the results as a system note. The answer streams through `run_route()`, which walks the route's model list from `backend/llm/chat_models.toml`, skipping models parked by `backend/llm/rate_limits.py`. No LangGraph, no client-side tools, no `model_priority.py`.

**Tech Stack:** Python 3.11 (stdlib `tomllib`), LangChain core runnables (`.stream()` / `.invoke()`, no `create_agent`), langchain-google-genai 4.2.6, langchain-groq 1.1.3, langchain-openrouter 0.2.8 (config-only, no models listed), Pydantic v2, SQLite, pytest, React (frontend touch-ups).

**Spec:** `docs/superpowers/specs/2026-09-11-chat-routing-design.md` — read it alongside this plan; every task argues from it.

## Global Constraints

- Branch `chat-routing-v2`. `main` is untouched. Pre-existing WIP was committed as `aa1a550`; the spec is `d733bfd`.
- **No OpenRouter model appears in any chat list.** `openrouter` stays a valid provider in the loader so GLM can be added by a config edit once the account is funded. Never spend money on OpenRouter in this work.
- **Crisis text is never edited.** `backend/services/crisis_support_service.py` is read-only in this plan. The section stays the last block of the system prompt.
- **Every behaviour rule in the prompts survives.** Only duplicates, dead sections and wasted text are removed. Prompt changes merge only after the Task 6 side-by-side check is approved by the user.
- Prompt size ceilings (whole prompt: system prompt + injected notes, measured in characters): Feed Explain Simply <= 8000, Feed Ask About <= 7500, web-search turn <= 7000, plain chat <= 6500.
- `feed_v2` is out of scope — do not edit anything under `backend/services/feed_v2/`.
- Old Feed callers stay working: `get_chat_model`, `get_structured_chat_model`, `_build_raw_models`, `ask_grok`, and the env models `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` / `GROQ_FALLBACK_MODEL`.
- Deletion rule: delete only at zero non-test references (`backend/`, `scripts/`, `tests/`, `frontend/`, including comments). Anything ambiguous is reported to the user, not deleted.
- Tests: `.venv/Scripts/python.exe -m pytest` (Windows). `pytest.ini` already excludes `-m integration`. Non-integration tests must make zero real provider calls.
- Every task ends with its own commit. Commit messages end with:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `backend/llm/chat_models.toml` | The editable model lists, one per route, plus the retry/skip durations. No code. |
| `backend/llm/rate_limits.py` | `classify_error` + the in-memory skip table. The only place a provider error is named. |
| `tests/test_model_routing.py` | TOML loader validation, leg order, and the fallback loop. |
| `tests/test_rate_limits.py` | Error classification against real error shapes; skip/expiry. |
| `tests/test_network_isolation_guard.py` | The guard itself blocks provider hosts in non-integration tests. |
| `tests/test_turn_plan.py` | `plan_turn` merge rules and the classifier's JSON parsing. |
| `tests/test_chat_answer_stream.py` | The answer loop: fall-through, mid-stream failure, skipped legs, route labels. |
| `tests/test_chat_prompt_v2.py` | Single prompt builder: crisis gating, one mechanism sentence, no JSON schema, size ceilings. |
| `tests/test_unpack_service.py` | Explain popover on the shared provider layer. |
| `tests/test_call_log_route.py` | `route` / `route_step` reach the log and the admin rows. |
| `scripts/ab_prompt_check.py` | Replays real logged turns through the old and new prompt builders and writes the side-by-side report. |
| `scripts/smoke_test_chat_routing_v2.py` | The live 10-turn smoke (`is_test=True`). |

**Modified**

| File | Change |
|---|---|
| `tests/conftest.py` | Autouse network isolation guard. |
| `backend/llm/model_provider.py` | TOML loader, `route_legs`/`build_leg`/`run_route`; delete the task-based pool helpers. |
| `backend/llm/chat_router.py` | Rewritten: JSON classifier + `plan_turn`. |
| `backend/llm/chat_agent.py` | Rewritten: plain streaming fallback loop (keeps `_split_content_chunks`). |
| `backend/llm/call_logger.py` | `route` / `route_step` columns. |
| `backend/llm/embeddings.py` | Rate-limit check via `classify_error`. |
| `backend/database/schema.py` | Two `ALTER TABLE llm_call_log` migrations. |
| `backend/services/chat_service.py` | One turn flow: classifier -> plan -> search -> prompt -> stream; block/seq numbering. |
| `backend/services/chat_prompt_service.py` | One prompt builder; the structured/JSON path and its section builders go. |
| `backend/services/chat_modes_service.py` | Trimmed Feed note + compact search note + extracted-text cleaning. |
| `backend/services/web_search_reasoning_service.py` | `run_chat_search`, parallel queries, year from the clock. |
| `backend/services/vector_memory_service.py` | De-duplicate "Related past discussion" entries. |
| `backend/services/layman_mode_service.py`, `backend/prompts/instruction_packs/core_learning_pack.py` | Trimmed simple-tone directive. |
| `backend/services/unpack_service.py` | Explain popover runs on `model_provider`. |
| `backend/services/writer_provider_router.py` | Quota check via `classify_error`. |
| `backend/services/model_registry.py` | Register the two Gemini flash-lite models. |
| `backend/services/admin_service.py` | `route` / `route_step` in the row columns. |
| `backend/services/grok_service.py` | Delete `ask_grok_chat_stream`. |
| `backend/config/app_config.py` | Delete the five model constants the TOML replaces. |
| `backend/main.py` | Validate `chat_models.toml` at startup; FeedContext comment. |
| `frontend/src/components/chat/ChatMessage.jsx`, `ChatWorkspace.jsx` | Delete `ACTION_LABELS` / `ActionBadge` / the `action` field. |
| `frontend/src/components/admin/AdminPage.jsx` | Show `route` in the row detail and exports. |

**Deleted**

`backend/llm/model_priority.py`, `backend/llm/chat_tools.py`, `backend/services/action_router_service.py`, `backend/services/learning_system_context_service.py`, `tests/test_model_priority.py`, `tests/test_action_router.py`, `tests/test_chat_agent_code_execution_middleware.py`, `tests/test_chat_router.py`, `scripts/smoke_test_model_pool_rotation.py`, `scripts/smoke_test_chat_router.py`, `scripts/smoke_test_prompt_adaptive_format.py`.

---

### Task 1: Test isolation guard + stale mock targets + baseline

Today `tests/test_streaming.py` mocks the retired `grok_service.ask_grok_chat_stream` and lets the real `chat_agent.ask_chat_stream` run — that is where the 649 fake "hi" rows in `llm_call_log` come from. Nothing else in this plan is trustworthy until pytest can no longer reach a provider.

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_network_isolation_guard.py`
- Modify: `tests/test_streaming.py:74-95`, `tests/test_streaming.py:254-272`, `tests/test_chat_quickstarters.py:155-166`, `tests/test_chat_intent_service.py:338-349`, `tests/test_chat_title_service.py:323`
- Create: `docs/superpowers/plans/2026-09-12-chat-routing-v2-baseline.md`

**Interfaces:**
- Produces: `tests.conftest.RealNetworkCallBlocked` (exception), `tests.conftest.blocked_host(url) -> str | None`, autouse fixture `block_provider_network`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_network_isolation_guard.py`:

```python
"""The guard that stops pytest from reaching a real provider.

Non-integration tests must never call Gemini, Groq, OpenRouter or TinyFish:
real calls cost quota, make the suite flaky, and write fake production-looking
rows into llm_call_log (649 of them before this guard landed). Constructing a
client stays legal - only sending a request is blocked.
"""
from __future__ import annotations

import httpx
import pytest
import requests

from tests.conftest import RealNetworkCallBlocked, blocked_host


class TestBlockedHostMatching:
    @pytest.mark.parametrize("url", [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent",
        "https://api.groq.com/openai/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
        "https://api.search.tinyfish.ai/search",
    ])
    def test_provider_urls_are_matched(self, url):
        assert blocked_host(url) is not None

    def test_unrelated_url_is_not_matched(self):
        assert blocked_host("https://example.com/anything") is None


class TestGuardBlocksRealRequests:
    def test_httpx_request_to_groq_is_blocked(self):
        with pytest.raises(RealNetworkCallBlocked):
            httpx.Client().get("https://api.groq.com/openai/v1/models")

    def test_requests_call_to_tinyfish_is_blocked(self):
        with pytest.raises(RealNetworkCallBlocked):
            requests.get("https://api.search.tinyfish.ai/search", timeout=5)

    def test_building_a_client_is_still_allowed(self):
        from langchain_groq import ChatGroq
        model = ChatGroq(model="openai/gpt-oss-20b", api_key="test-key")
        assert model.model_name == "openai/gpt-oss-20b"

    def test_invoking_a_model_is_blocked(self):
        from langchain_groq import ChatGroq
        model = ChatGroq(model="openai/gpt-oss-20b", api_key="test-key", max_retries=0)
        with pytest.raises(Exception) as exc_info:
            model.invoke("hi")
        assert "isolation guard" in str(exc_info.value)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_isolation_guard.py -v`
Expected: FAIL — `ImportError: cannot import name 'RealNetworkCallBlocked' from 'tests.conftest'`.

- [ ] **Step 3: Add the guard to `tests/conftest.py`**

Append to `tests/conftest.py`, keeping the existing `sqlite3.connect` patch and `reset_rate_limiter` fixture unchanged:

```python
# -- Network isolation --------------------------------------------------------
# Every provider SDK in this stack sends over httpx (google-genai, groq,
# openrouter, openai) except TinyFish, which uses requests. Patching the two
# transport entry points covers all of them without knowing each SDK's shape,
# and leaves client construction untouched - offline tests that build a model
# and never call it keep working.
from urllib.parse import urlparse

_BLOCKED_HOSTS = (
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "openrouter.ai",
    "tinyfish.ai",
)


class RealNetworkCallBlocked(RuntimeError):
    """A non-integration test tried to call a real provider."""


def blocked_host(url) -> str | None:
    """The blocked host this URL belongs to, or None. Accepts str or httpx.URL."""
    host = getattr(url, "host", None) or urlparse(str(url)).hostname or ""
    return next((h for h in _BLOCKED_HOSTS if host == h or host.endswith("." + h)), None)


@pytest.fixture(autouse=True)
def block_provider_network(request, monkeypatch):
    """Raise instead of sending a request to a provider, unless the test is
    marked `integration` (those are excluded by pytest.ini's default addopts
    and are the only tests allowed to spend real quota)."""
    if request.node.get_closest_marker("integration"):
        yield
        return

    import httpx
    import requests as _requests

    def _wrap(real_send):
        def _guarded(self, request_obj, *args, **kwargs):
            host = blocked_host(getattr(request_obj, "url", ""))
            if host:
                raise RealNetworkCallBlocked(
                    f"Real request to {host} blocked by the test isolation guard. "
                    "Mock the provider call, or mark the test @pytest.mark.integration."
                )
            return real_send(self, request_obj, *args, **kwargs)
        return _guarded

    monkeypatch.setattr(httpx.Client, "send", _wrap(httpx.Client.send))
    monkeypatch.setattr(httpx.AsyncClient, "send", _wrap(httpx.AsyncClient.send))
    monkeypatch.setattr(_requests.Session, "send", _wrap(_requests.Session.send))
    yield
```

- [ ] **Step 4: Run the guard test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_network_isolation_guard.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Fix the stale mock targets the guard exposes**

In `tests/test_streaming.py`, inside the `patched_chat_stream` fixture, delete the `import backend.services.grok_service as gs` line and its `monkeypatch.setattr(gs, "ask_grok_chat_stream", ...)` line, and add:

```python
    import backend.llm.chat_agent  as chat_agent
    import backend.llm.chat_router as chat_router

    monkeypatch.setattr(
        chat_agent, "ask_chat_stream",
        lambda *a, **kw: iter([
            {"type": "text", "text": "Hello"}, {"type": "text", "text": ", "},
            {"type": "text", "text": "world"}, {"type": "text", "text": "!"},
        ]),
    )
    monkeypatch.setattr(chat_router, "classify_message", lambda *a, **kw: None)
```

Replace the two failure-path tests in the same file:

```python
    def test_error_on_ai_failure_after_no_chunks(self, monkeypatch, patched_chat_stream):
        import backend.llm.chat_agent as chat_agent
        def boom(*a, **kw):
            raise RuntimeError("model unavailable")
        monkeypatch.setattr(chat_agent, "ask_chat_stream", boom)
        events = self._collect("sess1", "Hello")
        assert events[-1]["t"] == "error"

    def test_partial_chunks_then_error(self, monkeypatch, patched_chat_stream):
        import backend.llm.chat_agent as chat_agent
        def partial_stream(*a, **kw):
            yield {"type": "text", "text": "Partial"}
            raise RuntimeError("Disconnected mid-stream")
        monkeypatch.setattr(chat_agent, "ask_chat_stream", partial_stream)
        events = self._collect("sess1", "Hello")
        types = [e["t"] for e in events]
        assert "chunk" in types
        assert types[-1] == "error"
        assert "done" not in types
```

In `tests/test_chat_quickstarters.py:163` and `tests/test_chat_intent_service.py:345`, replace the
`patch("backend.services.grok_service.ask_grok_chat_stream", ...)` line with:

```python
             patch("backend.llm.chat_agent.ask_chat_stream",
                   return_value=iter([{"type": "text", "text": "ok"}])), \
             patch("backend.llm.chat_router.classify_message", return_value=None), \
```

In `tests/test_chat_title_service.py:323`, widen the fake's signature and stub the classifier:

```python
        def fake_ask_chat_stream(messages, *args, **kwargs):
```

plus `patch("backend.llm.chat_router.classify_message", return_value=None), \` in that `with` block.

- [ ] **Step 6: Run the full suite and record the baseline**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -40`

Write `docs/superpowers/plans/2026-09-12-chat-routing-v2-baseline.md` containing: the command, the date, the summary line (`N passed, M failed`), and one bullet per failing test id with a one-line reason. These are **pre-existing failures** — later tasks do not fix them unless they delete or rewrite that test. Expect at least: `test_streaming.py::TestAskGrokChatStream::*` (patches a `gs.client` attribute that does not exist), `test_crisis_support.py::TestSectionIsUnconditional::*` (asserts the crisis block is unconditional, which Phase U already gated), `test_feed_context_note.py` (asserts note wording that already changed).

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py tests/test_network_isolation_guard.py tests/test_streaming.py tests/test_chat_quickstarters.py tests/test_chat_intent_service.py tests/test_chat_title_service.py docs/superpowers/plans/2026-09-12-chat-routing-v2-baseline.md
git commit -m "test: block real provider calls in non-integration tests

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Spikes — streaming parts and classifier JSON reliability

Two unknowns can invalidate the design (spec Risks). Answer both before rewriting anything. The output is an answer, not code: the scripts are throwaway and are deleted at the end of the task. Nothing is committed.

**Files:**
- Create (throwaway): `scripts/spikes/spike_stream_parts.py`, `scripts/spikes/spike_classifier_json.py`

- [ ] **Step 1: Write the streaming spike**

`scripts/spikes/spike_stream_parts.py`:

```python
"""Throwaway spike: does plain .stream() still surface Gemini thinking and
code-execution parts when an LLMCallLogger callback is passed per call?
The LangGraph path needed the callback baked onto the agent; chat routing v2
drops LangGraph, so this has to hold for bare models."""
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from langchain_google_genai import ChatGoogleGenerativeAI
from backend.llm.call_logger import LLMCallLogger

KEY = (os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")).split(",")[0].strip()
CFG = {"callbacks": [LLMCallLogger()],
       "metadata": {"call_type": "spike_stream", "is_test": True, "surface": "chat"}}


def kinds(model, prompt):
    seen = {}
    for chunk in model.stream([{"role": "user", "content": prompt}], config=CFG):
        content = chunk.content
        items = content if isinstance(content, list) else [content]
        for item in items:
            key = item.get("type") if isinstance(item, dict) else "str"
            seen[key] = seen.get(key, 0) + 1
    return seen


print("2.5-flash (thinking_budget):", kinds(
    ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=KEY, streaming=True,
                           thinking_budget=1024, include_thoughts=True, max_output_tokens=512),
    "Think it through, then answer: why does a heavier flywheel smooth engine output?"))

code_model = ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite", api_key=KEY, streaming=True,
    thinking_level="low", include_thoughts=True, max_output_tokens=1024,
).bind_tools([{"code_execution": {}}])
print("3.1-flash-lite (code_execution):", kinds(
    code_model, "Compute the 200th Fibonacci number by running python code, then state the value."))
```

- [ ] **Step 2: Run it and read the result**

Run: `.venv/Scripts/python.exe scripts/spikes/spike_stream_parts.py`
Expected: the 2.5 line shows a `thinking` (or `reasoning`) key with a non-zero count next to `text`; the 3.1 line shows `executable_code` and `code_execution_result`.

**GATE:** if the 2.5 line has no thinking key, or the 3.1 line has no code keys, STOP and report the exact output to the user. The fallback (a minimal wrapper for those legs) is a design change only the user can approve.

- [ ] **Step 3: Write the classifier spike**

`scripts/spikes/spike_classifier_json.py`:

```python
"""Throwaway spike: how often does the [classifier] list produce a valid
RoutingDecision through JSON-schema structured output at max_tokens=400 with
reasoning on? The tool-calling classifier failed on Groq with 'Tool choice is
required, but model did not call a tool' - this measures the replacement."""
import os, re, sqlite3, sys, time
from pathlib import Path
from typing import Literal
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI


class RoutingDecision(BaseModel):
    needs_web_search: bool = Field(description="True if answering needs live web data")
    search_query: str = Field(description="Search-ready query, empty string when no search is needed")
    complexity: Literal["simple", "complex"]
    needs_code_execution: bool
    wants_simple_explanation: bool
    crisis: bool


SYSTEM = "Classify the user's last message for routing. Fill every field."

rows = sqlite3.connect("data/curivio.db").execute(
    "SELECT input FROM llm_call_log WHERE call_type='chat_turn' AND is_test=0 "
    "AND user_id IS NOT NULL AND input LIKE '%human:%' ORDER BY id DESC LIMIT 60"
).fetchall()
messages, seen = [], set()
for (text,) in rows:
    parts = re.split(r"(?m)^human: ", text)
    if len(parts) < 2:
        continue
    msg = parts[-1].split("\nai: ")[0].strip()[:500]
    if msg and msg not in seen:
        seen.add(msg)
        messages.append(msg)
messages = messages[:30]
print(f"{len(messages)} real user messages")


def probe(label, model, sample):
    structured = model.with_structured_output(RoutingDecision, method="json_schema", include_raw=True)
    ok, latencies = 0, []
    for msg in sample:
        t0 = time.monotonic()
        try:
            result = structured.invoke(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}])
            parsed = result.get("parsed")
        except Exception as exc:
            print(f"  ERROR {type(exc).__name__}: {str(exc)[:140]}")
            parsed = None
        latencies.append(time.monotonic() - t0)
        ok += parsed is not None
    latencies.sort()
    print(f"{label}: {ok}/{len(sample)} valid, median {latencies[len(latencies)//2]:.2f}s")


groq_key = (os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY")).split(",")[0].strip()
probe("groq/openai/gpt-oss-20b", ChatGroq(
    model="openai/gpt-oss-20b", api_key=groq_key, temperature=0.7, max_retries=0,
    max_tokens=400, reasoning_effort="low"), messages)

gem_key = (os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")).split(",")[0].strip()
probe("gemini/gemini-3.1-flash-lite", ChatGoogleGenerativeAI(
    model="gemini-3.1-flash-lite", api_key=gem_key, temperature=0.7, max_retries=0,
    max_output_tokens=400, thinking_level="low"), messages[:10])  # free tier: 20 req/day/key
```

- [ ] **Step 4: Run it and read the result**

Run: `.venv/Scripts/python.exe scripts/spikes/spike_classifier_json.py`
Expected: Groq >= 27/30 valid with a median under ~1.5s; Gemini >= 9/10.

**GATE:** below 90% valid on the Groq leg, raise its `max_tokens` to 800 and re-run that leg once. Still below 90% — put `gemini/gemini-3.1-flash-lite` first in the `[classifier]` list in Task 3 and record the measured numbers in that file's comment. Report the real numbers either way.

- [ ] **Step 5: Delete the spikes and report**

```bash
rm -rf scripts/spikes
```

Report three lines to the user: which content-part kinds streamed, the classifier valid-JSON rate per model, and any `[classifier]` ordering or `max_tokens` change Task 3 must carry.

---

### Task 3: `chat_models.toml`, its loader, and `rate_limits.py`

The single place a model list is chosen and the single place a provider error is named. Nothing routes through them yet — Tasks 4, 5 and 9 plug in.

**Files:**
- Create: `backend/llm/chat_models.toml`, `backend/llm/rate_limits.py`
- Create: `tests/test_model_routing.py`, `tests/test_rate_limits.py`
- Modify: `backend/llm/model_provider.py`, `backend/services/model_registry.py:250-262`, `backend/services/writer_provider_router.py:43-46`, `backend/llm/embeddings.py:73-85`, `backend/main.py` (lifespan)

**Interfaces:**
- Produces (from `backend/llm/model_provider.py`): `ChatModelsConfigError`, `ModelRef(provider, model)`, `RouteConfig(name, models, max_tokens, reasoning, timeout_seconds)`, `RetryConfig(retries_per_model, skip_after_rate_limit_sec, skip_after_daily_quota_sec, skip_after_no_credit_sec)`, `ChatModelsConfig(routes, retry)`, `load_chat_models(path) -> ChatModelsConfig`, `chat_models() -> ChatModelsConfig`, `LegSpec(route, step, provider, model, key_index)`, `route_legs(route) -> list[LegSpec]`, `build_leg(spec, *, streaming, thinking, temperature)`, `reasoning_kwargs(provider, model, reasoning) -> dict`, `registry_model_name(spec) -> str`, `run_route(route, attempt, *, notes, legs=None) -> (LegSpec, Iterator)`, `route_label(route, reason, notes) -> str`, `AllLegsFailed(route, notes)`, `PromptTooLargeError`, `InvalidOutputError`.
- Produces (from `backend/llm/rate_limits.py`): `classify_error(exc) -> str`, `skip(provider, model, key_index, kind)`, `record_failure(provider, model, key_index, kind)`, `is_skipped(provider, model, key_index) -> str | None`, `clear()`.
- Consumes: `model_provider._keys_for_provider`, `_is_gemini_3_plus`, `_TEMPERATURE` (all already in the file).

- [ ] **Step 1: Write the failing loader tests**

Create `tests/test_model_routing.py`:

```python
"""chat_models.toml is the one file a human edits to change chat models, so a
typo in it must fail loudly at load time rather than at 2am in a chat turn."""
from __future__ import annotations

import pytest

from backend.llm import model_provider as mp
from backend.llm.model_provider import ChatModelsConfigError, load_chat_models

GOOD = """
[classifier]
models     = ["groq/openai/gpt-oss-20b", "gemini/gemini-3.1-flash-lite"]
max_tokens = 400
reasoning  = "low"
[simple]
models     = ["groq/openai/gpt-oss-120b"]
max_tokens = 8192
reasoning  = "low"
[complex]
models     = ["gemini/gemini-2.5-flash"]
max_tokens = 8192
reasoning  = "low"
[code]
models     = ["gemini/gemini-3.1-flash-lite", "groq/openai/gpt-oss-120b"]
max_tokens = 8192
reasoning  = "low"
[image]
models     = ["gemini/gemini-2.5-flash"]
max_tokens = 8192
reasoning  = "low"
[explain]
models          = ["groq/openai/gpt-oss-120b"]
max_tokens      = 200
timeout_seconds = 5
[retry]
retries_per_model          = 1
skip_after_rate_limit_sec  = 30
skip_after_daily_quota_sec = 3600
skip_after_no_credit_sec   = 600
"""


def _write(tmp_path, text):
    path = tmp_path / "chat_models.toml"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoaderAcceptsAGoodFile:
    def test_routes_and_order_survive(self, tmp_path):
        cfg = load_chat_models(_write(tmp_path, GOOD))
        assert [str(m) for m in cfg.routes["classifier"].models] == [
            "groq/openai/gpt-oss-20b", "gemini/gemini-3.1-flash-lite"]
        assert cfg.routes["classifier"].max_tokens == 400
        assert cfg.routes["explain"].timeout_seconds == 5
        assert cfg.routes["simple"].reasoning == "low"
        assert cfg.retry.skip_after_daily_quota_sec == 3600

    def test_reasoning_defaults_to_off_when_absent(self, tmp_path):
        cfg = load_chat_models(_write(tmp_path, GOOD))
        assert cfg.routes["explain"].reasoning == "off"


class TestLoaderRejects:
    @pytest.mark.parametrize("bad,message", [
        (GOOD.replace('"groq/openai/gpt-oss-20b"', '"claude/opus"'), "unknown provider"),
        (GOOD.replace('models     = ["groq/openai/gpt-oss-120b"]\nmax_tokens = 8192\nreasoning  = "low"\n[complex]',
                      'models     = []\nmax_tokens = 8192\nreasoning  = "low"\n[complex]'), "non-empty models"),
        (GOOD.replace('[code]\nmodels     = ["gemini/gemini-3.1-flash-lite"',
                      '[code]\nmodels     = ["gemini/gemini-2.5-flash"'), "Gemini 3"),
        (GOOD.replace('[image]\nmodels     = ["gemini/gemini-2.5-flash"]',
                      '[image]\nmodels     = ["groq/openai/gpt-oss-120b"]'), "Gemini"),
        (GOOD.replace("skip_after_no_credit_sec   = 600", ""), "skip_after_no_credit_sec"),
        (GOOD.replace("max_tokens = 400", "max_tokens = 0"), "positive integer"),
        (GOOD.replace('reasoning  = "low"', 'reasoning  = "high"', 1), "low"),
        (GOOD + '\n[turbo]\nmodels = ["groq/x"]\nmax_tokens = 10\n', "unknown section"),
        (GOOD.replace("[retry]", "[retryy]"), "missing section"),
    ])
    def test_bad_file_fails_loudly(self, tmp_path, bad, message):
        with pytest.raises(ChatModelsConfigError, match=message):
            load_chat_models(_write(tmp_path, bad))

    def test_missing_file_fails_loudly(self, tmp_path):
        with pytest.raises(ChatModelsConfigError, match="missing"):
            load_chat_models(tmp_path / "nope.toml")


class TestShippedFile:
    def test_the_real_file_loads_and_has_no_openrouter_model(self):
        cfg = mp.chat_models()
        listed = [str(m) for route in cfg.routes.values() for m in route.models]
        assert listed, "chat_models.toml lists no models"
        assert not [m for m in listed if m.startswith("openrouter/")], (
            f"OpenRouter is excluded from chat until the account is funded: {listed}")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model_routing.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChatModelsConfigError'`.

- [ ] **Step 3: Write `backend/llm/chat_models.toml`**

Exactly this file (apply any ordering/`max_tokens` change Task 2's spike called for, and record the measured reason in the comment above that list):

```toml
# Curivio chat models. Each list is tried top to bottom.
# Format "provider/model-id": provider = gemini | groq | openrouter.
# Everything after the first "/" is the model id.
# Each model is tried on every API key of its provider before the next model.
# Edit, then restart the server.

[classifier]      # every turn: search? simple tone? code? crisis?
models     = ["groq/openai/gpt-oss-20b", "gemini/gemini-3.1-flash-lite"]
max_tokens = 400
reasoning  = "low"          # low | off (ignored where unsupported)

[simple]
models     = ["groq/openai/gpt-oss-120b", "gemini/gemini-3.1-flash-lite", "gemini/gemini-2.5-flash"]
max_tokens = 8192
reasoning  = "low"

[complex]
models     = ["gemini/gemini-2.5-flash", "groq/openai/gpt-oss-120b", "gemini/gemini-3.1-flash-lite"]
max_tokens = 8192
reasoning  = "low"

[code]            # first model must be Gemini 3.x (only one that can run code)
models     = ["gemini/gemini-3.1-flash-lite", "gemini/gemini-2.5-flash", "groq/openai/gpt-oss-120b"]
max_tokens = 8192
reasoning  = "low"

[image]           # Gemini only
models     = ["gemini/gemini-2.5-flash", "gemini/gemini-3.1-flash-lite"]
max_tokens = 8192
reasoning  = "low"

[explain]         # select-to-explain popover
models          = ["groq/openai/gpt-oss-120b", "gemini/gemini-flash-lite-latest"]
max_tokens      = 200
timeout_seconds = 5

[retry]
retries_per_model          = 1     # only network / server errors are retried
skip_after_rate_limit_sec  = 30    # 429 per-minute limit -> skip that model+key
skip_after_daily_quota_sec = 3600  # "per day" quota -> skip that model+key for 1 hour
skip_after_no_credit_sec   = 600   # 402 no credit -> skip the whole provider
```

- [ ] **Step 4: Add the loader to `backend/llm/model_provider.py`**

Add `import itertools`, `import tomllib`, `from dataclasses import dataclass`, `from functools import lru_cache`, and `from . import rate_limits` to the imports, then insert this section directly after `_thinking_kwargs` (before `_build_raw_models`):

```python
# ── chat_models.toml — the editable chat model lists ──────────────────────────
# The one file a human edits to change which models chat uses. Parsed once per
# process and validated loudly: an unknown provider, an empty list or a code
# list that does not start with a Gemini 3.x model is a configuration bug that
# must surface at startup, not as a 400 mid-turn.

_CHAT_MODELS_PATH = Path(__file__).with_name("chat_models.toml")
_PROVIDERS = ("gemini", "groq", "openrouter")
_ROUTES = ("classifier", "simple", "complex", "code", "image", "explain")
_RETRY_FIELDS = ("retries_per_model", "skip_after_rate_limit_sec",
                 "skip_after_daily_quota_sec", "skip_after_no_credit_sec")


class ChatModelsConfigError(ValueError):
    """chat_models.toml is missing, malformed, or names something unusable."""


@dataclass(frozen=True)
class ModelRef:
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True)
class RouteConfig:
    name: str
    models: tuple[ModelRef, ...]
    max_tokens: int
    reasoning: str                    # "low" | "off"
    timeout_seconds: float | None


@dataclass(frozen=True)
class RetryConfig:
    retries_per_model: int
    skip_after_rate_limit_sec: int
    skip_after_daily_quota_sec: int
    skip_after_no_credit_sec: int


@dataclass(frozen=True)
class ChatModelsConfig:
    routes: dict[str, RouteConfig]
    retry: RetryConfig


def _parse_model_ref(raw, route: str) -> ModelRef:
    if not isinstance(raw, str) or "/" not in raw:
        raise ChatModelsConfigError(f"[{route}] model {raw!r} must look like 'provider/model-id'")
    provider, model = raw.split("/", 1)
    if provider not in _PROVIDERS:
        raise ChatModelsConfigError(
            f"[{route}] unknown provider {provider!r} in {raw!r} — known: {', '.join(_PROVIDERS)}")
    if not model.strip():
        raise ChatModelsConfigError(f"[{route}] model id missing in {raw!r}")
    return ModelRef(provider, model.strip())


def _parse_route(name: str, table: dict) -> RouteConfig:
    models = table.get("models")
    if not isinstance(models, list) or not models:
        raise ChatModelsConfigError(f"[{name}] needs a non-empty models list")
    refs = tuple(_parse_model_ref(m, name) for m in models)

    max_tokens = table.get("max_tokens")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise ChatModelsConfigError(f"[{name}] max_tokens must be a positive integer")

    reasoning = table.get("reasoning", "off")
    if reasoning not in ("low", "off"):
        raise ChatModelsConfigError(f'[{name}] reasoning must be "low" or "off", got {reasoning!r}')

    timeout = table.get("timeout_seconds")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise ChatModelsConfigError(f"[{name}] timeout_seconds must be a positive number")

    if name == "code" and not (refs[0].provider == "gemini" and _is_gemini_3_plus(refs[0].model)):
        raise ChatModelsConfigError(
            "[code] the first model must be a Gemini 3.x model — it is the only one that runs code")
    if name == "image" and any(ref.provider != "gemini" for ref in refs):
        raise ChatModelsConfigError("[image] only Gemini can read an attached image")

    return RouteConfig(name=name, models=refs, max_tokens=max_tokens, reasoning=reasoning,
                       timeout_seconds=float(timeout) if timeout else None)


def load_chat_models(path: Path = _CHAT_MODELS_PATH) -> ChatModelsConfig:
    """Parse and validate chat_models.toml. Raises ChatModelsConfigError on
    anything a running server could not act on."""
    try:
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChatModelsConfigError(f"{path} is missing") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ChatModelsConfigError(f"{path} is not valid TOML: {exc}") from exc

    unknown = sorted(set(raw) - set(_ROUTES) - {"retry"})
    if unknown:
        raise ChatModelsConfigError(
            f"unknown section(s) {unknown} — expected {list(_ROUTES) + ['retry']}")
    missing = [name for name in (*_ROUTES, "retry") if name not in raw]
    if missing:
        raise ChatModelsConfigError(f"missing section(s) {missing}")

    retry_table = raw["retry"]
    for field_name in _RETRY_FIELDS:
        value = retry_table.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ChatModelsConfigError(f"[retry] {field_name} must be a non-negative integer")

    return ChatModelsConfig(
        routes={name: _parse_route(name, raw[name]) for name in _ROUTES},
        retry=RetryConfig(**{field_name: retry_table[field_name] for field_name in _RETRY_FIELDS}),
    )


@lru_cache(maxsize=1)
def chat_models() -> ChatModelsConfig:
    """The parsed chat_models.toml, read once per process — edit the file, restart."""
    return load_chat_models()
```

- [ ] **Step 5: Run the loader tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model_routing.py -v`
Expected: PASS (13 tests).

- [ ] **Step 6: Write the failing rate-limit tests**

Create `tests/test_rate_limits.py`. Every error below is built from the real provider class, with message text copied from real `llm_call_log` rows:

```python
"""classify_error is the only place a provider error gets a name, so it is
tested against the real exception classes with real logged message text.
Counts from llm_call_log since 2026-08-01: 640 Gemini 429s, 467 OpenRouter
402s, 79 Groq TPM 429s, 136 Groq 404s, 53 Gemini ConnectErrors, 21 Gemini 503s."""
from __future__ import annotations

from types import SimpleNamespace

import groq
import httpx
import pytest
from google.genai import errors as genai_errors
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError
from openrouter import errors as openrouter_errors

from backend.llm import rate_limits


@pytest.fixture(autouse=True)
def _clean_skips():
    rate_limits.clear()
    yield
    rate_limits.clear()


def _groq_error(cls, status, message):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return cls(message, response=httpx.Response(status, request=request), body=None)


def _gemini_quota(quota_id):
    return genai_errors.ClientError(429, {"error": {
        "code": 429, "status": "RESOURCE_EXHAUSTED",
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "details": [{"violations": [{"quotaId": quota_id, "quotaValue": "20"}]}],
    }})


def _wrapped(inner, message):
    try:
        raise ChatGoogleGenerativeAIError(message) from inner
    except ChatGoogleGenerativeAIError as exc:
        return exc


class TestClassifyError:
    def test_gemini_daily_quota(self):
        assert rate_limits.classify_error(
            _gemini_quota("GenerateRequestsPerDayPerProjectPerModel-FreeTier")) == "daily_quota"

    def test_gemini_per_minute_quota(self):
        assert rate_limits.classify_error(
            _gemini_quota("GenerateRequestsPerMinutePerProjectPerModel-FreeTier")) == "rate_limit"

    def test_gemini_daily_quota_through_the_langchain_wrapper(self):
        wrapped = _wrapped(_gemini_quota("GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
                           "Error calling model (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED.")
        assert rate_limits.classify_error(wrapped) == "daily_quota"

    def test_groq_tokens_per_minute(self):
        exc = _groq_error(groq.RateLimitError, 429, (
            "Error code: 429 - Rate limit reached for model openai/gpt-oss-20b on tokens per "
            "minute (TPM): Limit 8000, Used 6451, Requested 1588. Please try again in 292.5ms."))
        assert rate_limits.classify_error(exc) == "rate_limit"

    def test_groq_requests_per_day(self):
        exc = _groq_error(groq.RateLimitError, 429, (
            "Error code: 429 - Rate limit reached for model openai/gpt-oss-120b on requests "
            "per day (RPD): Limit 1000, Used 1000."))
        assert rate_limits.classify_error(exc) == "daily_quota"

    def test_openrouter_no_credit(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        exc = openrouter_errors.PaymentRequiredResponseError(
            data=SimpleNamespace(error=SimpleNamespace(message=(
                "This request requires more credits, or fewer max_tokens. You requested up to "
                "8192 tokens, but can only afford 183."))),
            raw_response=httpx.Response(402, request=request),
        )
        assert rate_limits.classify_error(exc) == "no_credit"

    def test_gemini_503_is_transient(self):
        exc = genai_errors.ServerError(503, {"error": {
            "code": 503, "status": "UNAVAILABLE",
            "message": "This model is currently experiencing high demand."}})
        assert rate_limits.classify_error(exc) == "transient"

    @pytest.mark.parametrize("exc", [
        httpx.ReadTimeout("The read operation timed out"),
        httpx.ConnectError("[Errno 11001] getaddrinfo failed"),
        groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com/x")),
    ])
    def test_network_failures_are_transient(self, exc):
        assert rate_limits.classify_error(exc) == "transient"

    @pytest.mark.parametrize("status,cls,message", [
        (404, groq.NotFoundError, "Error code: 404 - The model does not exist, code model_not_found"),
        (400, groq.BadRequestError, "Error code: 400 - Tool choice is required, but model did not call a tool"),
        (401, groq.AuthenticationError, "Error code: 401 - Invalid API Key, code invalid_api_key"),
    ])
    def test_client_errors_are_fatal(self, status, cls, message):
        assert rate_limits.classify_error(_groq_error(cls, status, message)) == "fatal"

    def test_our_own_errors_carry_their_own_kind(self):
        from backend.llm.model_provider import InvalidOutputError, PromptTooLargeError
        assert rate_limits.classify_error(InvalidOutputError("no json")) == "invalid_output"
        assert rate_limits.classify_error(PromptTooLargeError("9000 > 7000")) == "budget"


class TestSkipTable:
    def test_unknown_leg_is_not_skipped(self):
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) is None

    def test_rate_limit_parks_only_that_model_and_key(self):
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "rate_limit")
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) == "rate_limit"
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 1) is None
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-20b", 0) is None

    def test_no_credit_parks_the_whole_provider(self):
        rate_limits.record_failure("openrouter", "z-ai/glm-5.3-flash", 0, "no_credit")
        assert rate_limits.is_skipped("openrouter", "z-ai/glm-5.3-flash", 1) == "no_credit"
        assert rate_limits.is_skipped("openrouter", "any/other-model", 0) == "no_credit"
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) is None

    def test_transient_and_fatal_park_nothing(self):
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "transient")
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "fatal")
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) is None

    def test_skip_expires(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(rate_limits, "_now", lambda: now[0])
        rate_limits.record_failure("gemini", "gemini-2.5-flash", 0, "rate_limit")
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) == "rate_limit"
        now[0] += 31          # skip_after_rate_limit_sec = 30
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) is None

    def test_daily_quota_parks_for_an_hour(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(rate_limits, "_now", lambda: now[0])
        rate_limits.record_failure("gemini", "gemini-2.5-flash", 0, "daily_quota")
        now[0] += 120
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) == "daily_quota"
        now[0] += 3600
        assert rate_limits.is_skipped("gemini", "gemini-2.5-flash", 0) is None
```

- [ ] **Step 7: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rate_limits.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.llm.rate_limits'`.

- [ ] **Step 8: Write `backend/llm/rate_limits.py`**

```python
"""One place that names a provider error, one place that parks a model.

Replaces: model_provider._is_daily_quota_exhausted and its retry predicate,
chat_agent._retry_on, the Groq-400 special retry, writer_provider_router.
_is_quota_error, unpack_service._is_quota_error, embeddings._is_rate_limit_error.

Five kinds, and what each one means for the caller:
  rate_limit   a per-minute ceiling      -> next model now; park this model+key briefly
  daily_quota  a per-day ceiling         -> next model now; park this model+key for an hour
  no_credit    402, the account is empty -> next model now; park the whole provider
  transient    network / 5xx / timeout   -> retry this model, then the next one
  fatal        400/401/404 and friends   -> next model, park nothing

The table is in memory, per process, and is cleared by a restart: a skip is a
short-lived hint, never state anything else depends on.

Public API
----------
classify_error(exc) -> str
skip(provider, model, key_index, kind)              park a model+key, or a provider
record_failure(provider, model, key_index, kind)    apply the rule for that kind
is_skipped(provider, model, key_index) -> str | None
clear()                                             forget everything (tests)
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

# (provider, model | None, key_index | None) -> (expires_at_monotonic, kind).
# model/key None means the whole provider is parked.
_skips: dict[tuple[str, str | None, int | None], tuple[float, str]] = {}
_lock = threading.Lock()

# Google names the window in quotaId ("...PerDay..." / "...PerMinute..."); Groq
# spells it out in the message ("requests per day (RPD)", "tokens per minute").
_DAILY_MARKERS = ("perday", "per day", "(rpd)", "(tpd)")
_TRANSIENT_NAMES = ("timeout", "connect", "connection", "protocol", "readerror", "writeerror")


def _now() -> float:
    """Monotonic clock, indirected so tests can move time without sleeping."""
    return time.monotonic()


def _chain(exc: BaseException):
    """The exception and everything it was raised from — LangChain wraps the
    provider's real error (ChatGoogleGenerativeAIError ... from ClientError),
    so the status code and quota id live on __cause__, not the top exception."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _status_code(exc: BaseException) -> int | None:
    for err in _chain(exc):
        for attr in ("status_code", "code"):
            value = getattr(err, attr, None)
            if isinstance(value, int) and 100 <= value < 600:
                return value
        for attr in ("response", "raw_response"):
            value = getattr(getattr(err, attr, None), "status_code", None)
            if isinstance(value, int):
                return value
    return None


def classify_error(exc: BaseException) -> str:
    """"rate_limit" | "daily_quota" | "no_credit" | "transient" | "fatal"."""
    own_kind = getattr(exc, "kind", None)      # our own errors label themselves
    if isinstance(own_kind, str):
        return own_kind

    text = " ".join(str(err) for err in _chain(exc)).lower()
    names = " ".join(type(err).__name__ for err in _chain(exc)).lower()
    code = _status_code(exc)

    if code == 402 or "paymentrequired" in names or "more credits" in text:
        return "no_credit"
    if code == 429 or "resource_exhausted" in text or "ratelimit" in names or "toomanyrequests" in names:
        return "daily_quota" if any(marker in text for marker in _DAILY_MARKERS) else "rate_limit"
    if (code is not None and code >= 500) or "unavailable" in text or any(n in names for n in _TRANSIENT_NAMES):
        return "transient"
    return "fatal"


def _durations() -> dict[str, int]:
    # Imported here, not at module scope: model_provider imports this module.
    from .model_provider import chat_models
    retry = chat_models().retry
    return {
        "rate_limit":  retry.skip_after_rate_limit_sec,
        "daily_quota": retry.skip_after_daily_quota_sec,
        "no_credit":   retry.skip_after_no_credit_sec,
    }


def skip(provider: str, model: str | None, key_index: int | None, kind: str) -> None:
    """Park a model+key — or the whole provider when model/key_index are None —
    for the [retry] duration of `kind`."""
    seconds = _durations().get(kind)
    if not seconds:
        return
    with _lock:
        _skips[(provider, model, key_index)] = (_now() + seconds, kind)
    logger.info("[rate_limits] parked %s/%s key#%s for %ss (%s)",
                provider, model or "*", "*" if key_index is None else key_index, seconds, kind)


def record_failure(provider: str, model: str, key_index: int, kind: str) -> None:
    """Apply the skip rule for one failure kind. transient and fatal park nothing:
    a transient error is worth retrying, and a fatal one (bad request, missing
    model) says nothing about the model's availability a minute from now."""
    if kind == "no_credit":
        skip(provider, None, None, kind)
    elif kind in ("rate_limit", "daily_quota"):
        skip(provider, model, key_index, kind)


def is_skipped(provider: str, model: str, key_index: int) -> str | None:
    """The kind this leg is parked for, or None. Truthy means 'do not call it'."""
    now = _now()
    with _lock:
        for key in ((provider, None, None), (provider, model, key_index)):
            entry = _skips.get(key)
            if entry is None:
                continue
            expires_at, kind = entry
            if expires_at > now:
                return kind
            del _skips[key]
    return None


def clear() -> None:
    with _lock:
        _skips.clear()
```

- [ ] **Step 9: Run the rate-limit tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rate_limits.py -v`
Expected: PASS (18 tests).

- [ ] **Step 10: Write the failing leg/fallback tests**

Append to `tests/test_model_routing.py`:

```python
class TestRouteLegs:
    """Keys within a model before the next model: a model is only dropped once
    every key of its provider has had a turn."""

    @pytest.fixture(autouse=True)
    def _two_keys(self, monkeypatch):
        monkeypatch.setattr(mp, "_keys_for_provider",
                            lambda provider: {"groq": ["g1", "g2"], "gemini": ["k1", "k2"],
                                              "openrouter": ["o1"]}[provider])

    def test_keys_come_before_the_next_model(self):
        legs = mp.route_legs("simple")
        assert [(leg.step, leg.provider, leg.key_index) for leg in legs[:3]] == [
            (1, "groq", 0), (1, "groq", 1), (2, "gemini", 0)]

    def test_step_is_the_position_in_the_configured_list(self):
        steps = {leg.model: leg.step for leg in mp.route_legs("simple")}
        assert steps["openai/gpt-oss-120b"] == 1
        assert steps["gemini-2.5-flash"] == 3

    def test_image_route_uses_the_first_gemini_key_only(self):
        legs = mp.route_legs("image")
        assert {leg.key_index for leg in legs} == {0}, "Files API scopes an upload to one key"


class TestRunRoute:
    """The fallback loop: what falls through, what propagates, what gets parked."""

    @pytest.fixture(autouse=True)
    def _one_key_clean_skips(self, monkeypatch):
        from backend.llm import rate_limits
        rate_limits.clear()
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["only-key"])
        yield
        rate_limits.clear()

    def _boom(self, exc):
        def attempt(spec):
            raise exc
            yield  # pragma: no cover - makes this a generator
        return attempt

    def test_first_working_leg_wins(self):
        notes = []
        def attempt(spec):
            yield f"answer from {spec.model}"
        spec, items = mp.run_route("simple", attempt, notes=notes)
        assert spec.step == 1 and list(items) == ["answer from openai/gpt-oss-120b"]
        assert notes == []

    def test_failure_before_the_first_item_falls_through(self):
        import groq, httpx
        bad = groq.BadRequestError("Error code: 400 - nope", response=httpx.Response(
            400, request=httpx.Request("POST", "https://api.groq.com/x")), body=None)
        notes, seen = [], []
        def attempt(spec):
            seen.append(spec.model)
            if spec.step == 1:
                raise bad
            yield "second leg answer"
        spec, items = mp.run_route("simple", attempt, notes=notes)
        assert spec.step == 2 and list(items) == ["second leg answer"]
        assert notes == ["skipped groq/openai/gpt-oss-120b (fatal)"]

    def test_failure_after_the_first_item_propagates(self):
        notes = []
        def attempt(spec):
            yield "partial"
            raise RuntimeError("dropped mid-stream")
        spec, items = mp.run_route("simple", attempt, notes=notes)
        with pytest.raises(RuntimeError, match="dropped mid-stream"):
            list(items)
        assert notes == [], "a half-streamed answer must not be replaced by another leg"

    def test_transient_error_is_retried_on_the_same_leg(self):
        import httpx
        attempts = []
        def attempt(spec):
            attempts.append(spec.step)
            if len(attempts) == 1:
                raise httpx.ReadTimeout("The read operation timed out")
            yield "recovered"
        spec, items = mp.run_route("simple", attempt, notes=[])
        assert attempts == [1, 1] and spec.step == 1 and list(items) == ["recovered"]

    def test_rate_limited_leg_is_parked_for_the_next_turn(self):
        import groq, httpx
        limited = groq.RateLimitError(
            "Error code: 429 - tokens per minute (TPM): Limit 8000",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/x")),
            body=None)
        def attempt(spec):
            if spec.provider == "groq":
                raise limited
            yield "gemini answer"
        first_notes = []
        mp.run_route("simple", attempt, notes=first_notes)
        assert first_notes == ["skipped groq/openai/gpt-oss-120b (rate_limit)"]

        called = []
        def attempt2(spec):
            called.append(spec.model)
            yield "gemini answer"
        second_notes = []
        mp.run_route("simple", attempt2, notes=second_notes)
        assert "openai/gpt-oss-120b" not in called, "parked leg must not be called again"
        assert second_notes == ["skipped groq/openai/gpt-oss-120b (rate_limit)"]

    def test_every_leg_failing_raises_with_the_notes(self):
        notes = []
        with pytest.raises(mp.AllLegsFailed) as exc_info:
            mp.run_route("simple", self._boom(RuntimeError("bad request")), notes=notes)
        assert len(notes) == 3
        assert "every model failed" in str(exc_info.value)

    def test_caller_can_resume_at_the_next_leg(self):
        legs = iter(mp.route_legs("simple"))
        def attempt(spec):
            yield spec.model
        first, _ = mp.run_route("simple", attempt, notes=[], legs=legs)
        second, _ = mp.run_route("simple", attempt, notes=[], legs=legs)
        assert first.step == 1 and second.step == 2


class TestRouteLabel:
    def test_plain_label(self):
        assert mp.route_label("simple", "classifier", []) == "simple ← classifier"

    def test_label_carries_what_it_fell_past(self):
        label = mp.route_label("simple", "classifier_failed",
                               ["skipped groq/openai/gpt-oss-120b (rate_limit)"])
        assert label == "simple ← classifier_failed · skipped groq/openai/gpt-oss-120b (rate_limit)"


class TestReasoningMapping:
    @pytest.mark.parametrize("provider,model,reasoning,expected", [
        ("gemini", "gemini-3.1-flash-lite", "low", {"thinking_level": "low"}),
        ("gemini", "gemini-3.1-flash-lite", "off", {"thinking_level": "low"}),
        ("gemini", "gemini-2.5-flash", "low", {"thinking_budget": 1024}),
        ("gemini", "gemini-2.5-flash", "off", {"thinking_budget": 0}),
        ("groq", "openai/gpt-oss-120b", "low", {"reasoning_effort": "low"}),
        ("groq", "llama-3.3-70b", "low", {}),
        ("openrouter", "z-ai/glm-5.3-flash", "low", {"reasoning": {"effort": "low"}}),
        ("openrouter", "z-ai/glm-5.3-flash", "off", {"reasoning": {"enabled": False}}),
    ])
    def test_reasoning_kwargs(self, provider, model, reasoning, expected):
        assert mp.reasoning_kwargs(provider, model, reasoning) == expected


class TestBuildLeg:
    def test_gemini_chat_leg_carries_thinking_and_the_token_ceiling(self, monkeypatch):
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k1"])
        spec = mp.LegSpec("complex", 1, "gemini", "gemini-2.5-flash", 0)
        model = mp.build_leg(spec, streaming=True, thinking=True)
        assert model.max_output_tokens == 8192
        assert model.include_thoughts is True
        assert model.thinking_budget == 1024

    def test_explain_leg_gets_the_timeout_and_no_thinking(self, monkeypatch):
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k1"])
        spec = mp.LegSpec("explain", 1, "groq", "openai/gpt-oss-120b", 0)
        model = mp.build_leg(spec, streaming=True, temperature=0.3)
        assert model.max_tokens == 200
        assert model.request_timeout == 5
        assert model.temperature == 0.3
```

- [ ] **Step 11: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model_routing.py -v`
Expected: FAIL — `AttributeError: module 'backend.llm.model_provider' has no attribute 'route_legs'`.

- [ ] **Step 12: Add the leg builder and the fallback loop to `model_provider.py`**

Append after the loader section:

```python
# ── Legs and the fallback loop ────────────────────────────────────────────────
# Every chat call (classifier, answer, explain) walks a route's list the same
# way, so the walking lives here once: skip parked legs, retry a transient
# error, park what failed, move on. Callers only say what one attempt does.

@dataclass(frozen=True)
class LegSpec:
    """One (model, API key) attempt inside a route's list."""
    route: str
    step: int                 # 1-based position of this model in the route's list
    provider: str
    model: str
    key_index: int

    def __str__(self) -> str:
        return f"{self.provider}/{self.model}"


class AllLegsFailed(RuntimeError):
    """Every model in a route's list failed or was already parked."""

    def __init__(self, route: str, notes: list[str]) -> None:
        self.route = route
        self.notes = list(notes)
        super().__init__(f"[{route}] every model failed: {'; '.join(notes) or 'no models available'}")


class PromptTooLargeError(RuntimeError):
    """This prompt cannot fit this leg's budget — try the next leg, don't call it."""
    kind = "budget"


class InvalidOutputError(RuntimeError):
    """The model answered, but not in the shape the caller needs (classifier JSON)."""
    kind = "invalid_output"


def route_legs(route: str) -> list[LegSpec]:
    """Every (model, key) pair for a route, in try order: a model is tried on
    every key of its provider before the next model contributes a leg."""
    config = chat_models().routes[route]
    legs: list[LegSpec] = []
    for step, ref in enumerate(config.models, 1):
        key_count = len(_keys_for_provider(ref.provider))
        if route == "image":
            key_count = 1     # Gemini's Files API scopes an upload to the key that made it
        legs.extend(LegSpec(route, step, ref.provider, ref.model, index) for index in range(key_count))
    return legs


def reasoning_kwargs(provider: str, model: str, reasoning: str) -> dict:
    """The TOML's low/off mapped onto each provider's own parameter — the only
    place this mapping exists. Gemini 3.x and Groq gpt-oss have no off switch."""
    if provider == "gemini":
        if _is_gemini_3_plus(model):
            return {"thinking_level": "low"}
        return {"thinking_budget": 1024 if reasoning == "low" else 0}
    if provider == "groq":
        return {"reasoning_effort": "low"} if "gpt-oss" in model else {}
    if provider == "openrouter":
        return {"reasoning": {"effort": "low"} if reasoning == "low" else {"enabled": False}}
    return {}


def registry_model_name(spec: LegSpec) -> str:
    """The model_registry key for this leg — Gemini entries carry the models/ prefix."""
    if spec.provider == "gemini" and not spec.model.startswith("models/"):
        return f"models/{spec.model}"
    return spec.model


def build_leg(spec: LegSpec, *, streaming: bool = False, thinking: bool = False,
              temperature: float = _TEMPERATURE):
    """One bare chat model for this leg. Bare on purpose: callers attach
    LLMCallLogger per call, because a callback baked onto the model collapses
    per-token streaming (verified live, see this module's history)."""
    config = chat_models().routes[spec.route]
    key = _keys_for_provider(spec.provider)[spec.key_index]
    kwargs: dict = dict(model=spec.model, temperature=temperature, max_retries=0, streaming=streaming)
    kwargs.update(reasoning_kwargs(spec.provider, spec.model, config.reasoning))

    if spec.provider == "gemini":
        kwargs.update(api_key=key, max_output_tokens=config.max_tokens)
        if thinking:
            kwargs["include_thoughts"] = True
        if config.timeout_seconds:
            kwargs["timeout"] = config.timeout_seconds
        return ChatGoogleGenerativeAI(**kwargs)

    if spec.provider == "groq":
        kwargs.update(api_key=key, max_tokens=config.max_tokens)
        if config.timeout_seconds:
            kwargs["request_timeout"] = config.timeout_seconds
        return ChatGroq(**kwargs)

    kwargs.update(openrouter_api_key=key, max_tokens=config.max_tokens)
    if config.timeout_seconds:
        kwargs["request_timeout"] = config.timeout_seconds
    return ChatOpenRouter(**kwargs)


def route_label(route: str, reason: str, notes: list[str]) -> str:
    """The llm_call_log `route` value: what was chosen, why, and what it fell past."""
    label = f"{route} ← {reason}" if reason else route
    return f"{label} · {'; '.join(notes)}" if notes else label


def run_route(route: str, attempt, *, notes: list[str], legs=None):
    """Walk a route's list until one leg starts producing output.

    `attempt(spec)` returns an iterator — a .stream() generator, or a generator
    yielding one parsed result. A failure BEFORE its first item falls through to
    the next leg; a failure after it propagates to the caller, because a
    half-streamed answer must never be silently replaced by a second one.

    `legs` lets a caller keep its own position across calls (the explain popover
    resumes at the next leg after an unparseable answer).

    Returns (spec, iterator) with the first item put back, and appends one note
    per leg it gave up on so the caller can log why it landed where it did.
    """
    retries = chat_models().retry.retries_per_model
    last_exc: BaseException | None = None

    for spec in (legs if legs is not None else iter(route_legs(route))):
        parked = rate_limits.is_skipped(spec.provider, spec.model, spec.key_index)
        if parked:
            notes.append(f"skipped {spec} ({parked})")
            continue
        for try_number in range(retries + 1):
            try:
                iterator = iter(attempt(spec))
                first = next(iterator)
            except StopIteration:
                return spec, iter(())
            except Exception as exc:
                last_exc = exc
                kind = rate_limits.classify_error(exc)
                if kind == "transient" and try_number < retries:
                    logger.warning("[llm] %s leg %s transient (%s) — retrying", route, spec, exc)
                    continue
                rate_limits.record_failure(spec.provider, spec.model, spec.key_index, kind)
                notes.append(f"skipped {spec} ({kind})")
                logger.warning("[llm] %s leg %s failed (%s): %s", route, spec, kind, exc)
                break
            return spec, itertools.chain([first], iterator)

    raise AllLegsFailed(route, notes) from last_exc
```

- [ ] **Step 13: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_model_routing.py tests/test_rate_limits.py -v`
Expected: PASS (all).

- [ ] **Step 14: Register the two Gemini flash-lite models**

`backend/services/model_registry.py` — add next to `"models/gemini-2.5-flash"` (line 254). Without these, every budget check on those legs falls to the 32K `_DEFAULT_CONFIG` and logs a warning per call, which would make the per-leg budget check in Task 5 reject prompts the model handles fine:

```python
    # Same 1M-context flash family as gemini-2.5-flash above; keyed with the
    # literal "models/" prefix, which is what registry_model_name() passes.
    "models/gemini-3.1-flash-lite": ModelConfig(
        model_name       = "models/gemini-3.1-flash-lite",
        provider         = "google",
        context_window   = 1_000_000,
        safe_utilization = 0.80,
        output_reserve   = 4_000,
        safety_buffer    = 2_000,
    ),
    "models/gemini-flash-lite-latest": ModelConfig(
        model_name       = "models/gemini-flash-lite-latest",
        provider         = "google",
        context_window   = 1_000_000,
        safe_utilization = 0.80,
        output_reserve   = 4_000,
        safety_buffer    = 2_000,
    ),
```

- [ ] **Step 15: Point the existing quota checks at `classify_error`**

Three call sites stop hand-rolling their own string matching. Behaviour is the same or better in each case; no new behaviour.

`backend/llm/model_provider.py` — `_QuotaAwareRetry._kwargs_retrying` (line ~315):

```python
        def _should_retry(exc: BaseException) -> bool:
            # Only a genuinely transient failure is worth a backoff sleep: a
            # daily cap cannot recover inside one, an empty account never will,
            # and a 400 will fail identically on every attempt.
            return isinstance(exc, retry_types) and rate_limits.classify_error(exc) in ("rate_limit", "transient")
```

(Leave `_is_daily_quota_exhausted` in place for now — `chat_agent.py` still imports it until Task 5.)

`backend/services/writer_provider_router.py:43-46`:

```python
def _is_quota_error(exc: Exception) -> bool:
    """Gemini pool exhausted (per-minute or per-day) — the only case that earns
    the Groq fallback. See backend/llm/rate_limits.py for the classification."""
    from ..llm.rate_limits import classify_error
    return classify_error(exc) in ("rate_limit", "daily_quota")
```

`backend/llm/embeddings.py:73-85` — replace `_is_rate_limit_error`'s body:

```python
def _is_rate_limit_error(exc: BaseException) -> bool:
    """Gemini's RESOURCE_EXHAUSTED (the free tier's 100 req/min ceiling).
    classify_error walks __cause__, which is where langchain_google_genai keeps
    the real ClientError after wrapping it in GoogleGenerativeAIError."""
    from .rate_limits import classify_error
    return classify_error(exc) in ("rate_limit", "daily_quota")
```

- [ ] **Step 16: Fail loudly at startup on a broken TOML**

`backend/main.py`, at the top of the `lifespan` body (before the backup snapshot, so a typo stops boot immediately rather than after a 30s snapshot):

```python
    # chat_models.toml drives every chat model choice — a typo in it must stop
    # the process here, not surface as a 400 in someone's chat turn.
    from .llm.model_provider import chat_models
    _routes = chat_models().routes
    logger.info("[startup] chat models loaded: %s",
                {name: [str(m) for m in route.models] for name, route in _routes.items()})
```

`Dockerfile` needs no change: `COPY backend/ ./backend/` already ships the TOML.

- [ ] **Step 17: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20`
Expected: the Task 1 baseline failures and nothing new.

- [ ] **Step 18: Commit**

```bash
git add backend/llm/chat_models.toml backend/llm/rate_limits.py backend/llm/model_provider.py backend/llm/embeddings.py backend/services/model_registry.py backend/services/writer_provider_router.py backend/main.py tests/test_model_routing.py tests/test_rate_limits.py
git commit -m "feat(llm): add chat_models.toml, its loader, and one rate-limit policy

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Classifier, turn plan, and the code-run search

The classifier stops emitting a `task_type` and starts answering the six questions the turn actually needs; `plan_turn` merges it with the toggles; the search stops being a model-invoked tool and becomes something `chat_service` runs itself. At the end of this task chat still answers through the old agent (one temporary adapter line), which Task 5 removes.

**Files:**
- Rewrite: `backend/llm/chat_router.py`
- Modify: `backend/services/web_search_reasoning_service.py`, `backend/services/chat_service.py`
- Create: `tests/test_turn_plan.py`
- Modify: `tests/test_web_search_reasoning_service.py`, `tests/test_chat_mode_mapping.py`

**Interfaces:**
- Consumes: `model_provider.run_route / build_leg / route_label / InvalidOutputError / AllLegsFailed`, `call_logger.LLMCallLogger`.
- Produces: `chat_router.RoutingDecision`, `chat_router.TurnPlan`, `chat_router.classify_message(message, *, history=None, card_title="", metadata=None) -> RoutingDecision | None`, `chat_router.plan_turn(decision, *, message, has_image=False, toggle_web_search=False, toggle_simple=False, feed_action=None, sticky_simple=False) -> TurnPlan`, `web_search_reasoning_service.run_chat_search(query, *, complexity=None, meta=None) -> (note, sources)`.

- [ ] **Step 1: Write the failing classifier/plan tests**

Create `tests/test_turn_plan.py`:

```python
"""plan_turn is the whole routing decision in one pure function: classifier
answer + user overrides -> what runs. Toggles are overrides, not modes
(design decision A), and a failed classifier must still produce a safe turn."""
from __future__ import annotations

import pytest

from backend.llm import model_provider as mp
from backend.llm.chat_router import RoutingDecision, TurnPlan, classify_message, plan_turn


def _decision(**over) -> RoutingDecision:
    base = dict(needs_web_search=False, search_query="", complexity="simple",
                needs_code_execution=False, wants_simple_explanation=False, crisis=False)
    base.update(over)
    return RoutingDecision(**base)


class TestRouteChoice:
    def test_simple_by_default(self):
        assert plan_turn(_decision(), message="hi").route == "simple"

    def test_complex_when_the_classifier_says_so(self):
        assert plan_turn(_decision(complexity="complex"), message="compare X and Y").route == "complex"

    def test_code_beats_complexity(self):
        plan = plan_turn(_decision(complexity="complex", needs_code_execution=True), message="run this")
        assert plan.route == "code"

    def test_image_beats_everything(self):
        plan = plan_turn(_decision(needs_code_execution=True, complexity="complex"),
                         message="what is in this picture", has_image=True)
        assert plan.route == "image"


class TestSearch:
    def test_classifier_asks_for_a_search(self):
        plan = plan_turn(_decision(needs_web_search=True, search_query="ipl 2026 winner"),
                         message="who won")
        assert plan.search is True and plan.search_query == "ipl 2026 winner"
        assert plan.reason == "classifier"

    def test_toggle_forces_a_search_the_classifier_did_not_want(self):
        plan = plan_turn(_decision(needs_web_search=False), message="explain attention",
                         toggle_web_search=True)
        assert plan.search is True
        assert plan.search_query == "explain attention", "falls back to the message"
        assert plan.reason == "classifier+toggle:web_search"

    def test_feed_action_never_blocks_a_search(self):
        plan = plan_turn(_decision(needs_web_search=True, search_query="q"),
                         message="is this still true?", feed_action="explain_simply")
        assert plan.search is True


class TestSimpleTone:
    def test_toggle_forces_it(self):
        plan = plan_turn(_decision(), message="explain attention", toggle_simple=True)
        assert plan.simple_tone is True and "+toggle:explain_simply" in plan.reason

    def test_feed_explain_simply_forces_it(self):
        plan = plan_turn(_decision(), message="Explain this simply.", feed_action="explain_simply")
        assert plan.simple_tone is True and "+feed:explain_simply" in plan.reason

    def test_sticky_session_keeps_it(self):
        plan = plan_turn(_decision(), message="and what about scaling?", sticky_simple=True)
        assert plan.simple_tone is True and "+sticky:explain_simply" in plan.reason

    def test_classifier_can_ask_for_it_on_a_plain_turn(self):
        plan = plan_turn(_decision(wants_simple_explanation=True), message="eli5 transformers")
        assert plan.simple_tone is True and plan.reason == "classifier"

    def test_off_by_default(self):
        assert plan_turn(_decision(), message="explain attention").simple_tone is False


class TestCrisis:
    def test_classifier_says_yes(self):
        assert plan_turn(_decision(crisis=True), message="i want to die").crisis is True

    def test_classifier_says_no(self):
        assert plan_turn(_decision(crisis=False), message="hi").crisis is False

    def test_classifier_failure_turns_it_on(self):
        assert plan_turn(None, message="hi").crisis is True


class TestClassifierFailure:
    def test_safe_plan(self):
        plan = plan_turn(None, message="what happened at the summit?")
        assert (plan.route, plan.search, plan.complexity) == ("simple", False, "simple")
        assert plan.search_query == "what happened at the summit?"
        assert plan.reason == "classifier_failed"

    def test_toggles_still_apply(self):
        plan = plan_turn(None, message="latest news", has_image=False,
                         toggle_web_search=True, toggle_simple=True)
        assert plan.search is True and plan.simple_tone is True
        assert plan.reason == "classifier_failed+toggle:web_search+toggle:explain_simply"

    def test_image_turn_still_routes_to_image(self):
        assert plan_turn(None, message="what is this", has_image=True).route == "image"


class _FakeStructured:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def invoke(self, messages, config=None):
        self.calls.append((messages, config))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeModel:
    def __init__(self, result):
        self.structured = _FakeStructured(result)

    def with_structured_output(self, schema, method=None, include_raw=False):
        assert method == "json_schema", "tool calling is what failed on Groq — JSON schema only"
        assert include_raw is True, "parsed=None must be visible, not swallowed"
        return self.structured


class TestClassifyMessage:
    @pytest.fixture(autouse=True)
    def _one_key(self, monkeypatch):
        from backend.llm import rate_limits
        rate_limits.clear()
        monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k"])
        yield
        rate_limits.clear()

    def test_returns_the_parsed_decision(self, monkeypatch):
        decision = _decision(needs_web_search=True, search_query="q")
        model = _FakeModel({"parsed": decision, "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        assert classify_message("who won?") is decision

    def test_card_title_is_given_to_the_classifier(self, monkeypatch):
        model = _FakeModel({"parsed": _decision(), "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        classify_message("explain", card_title="Why Audit AI Needs Blueprints")
        sent = "\n".join(m["content"] for m in model.structured.calls[0][0])
        assert "Why Audit AI Needs Blueprints" in sent

    def test_invalid_json_falls_through_to_the_next_model(self, monkeypatch):
        good = _decision(complexity="complex")
        models = [_FakeModel({"parsed": None, "raw": None, "parsing_error": "not json"}),
                  _FakeModel({"parsed": good, "raw": None, "parsing_error": None})]
        used = iter(models)
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: next(used))
        assert classify_message("hi") is good

    def test_every_model_failing_returns_none(self, monkeypatch):
        def boom(spec, **kw):
            raise RuntimeError("Error code: 400 - bad request")
        monkeypatch.setattr("backend.llm.chat_router.build_leg", boom)
        assert classify_message("hi") is None

    def test_history_multipart_content_is_flattened_to_text(self, monkeypatch):
        model = _FakeModel({"parsed": _decision(), "raw": None, "parsing_error": None})
        monkeypatch.setattr("backend.llm.chat_router.build_leg", lambda spec, **kw: model)
        classify_message("and this one?", history=[
            {"role": "user", "content": [{"type": "text", "text": "look at this"},
                                         {"type": "media", "file_uri": "gs://x", "mime_type": "image/png"}]},
            {"role": "assistant", "content": "It is a red square."},
        ])
        sent = model.structured.calls[0][0]
        assert all(isinstance(m["content"], str) for m in sent)
        assert any("look at this" in m["content"] for m in sent)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_turn_plan.py -v`
Expected: FAIL — `ImportError: cannot import name 'TurnPlan' from 'backend.llm.chat_router'`.

- [ ] **Step 3: Rewrite `backend/llm/chat_router.py`**

Replace the whole file:

```python
"""The one classifier and the one turn plan.

Every chat turn asks one small model the same six questions as JSON — search?
how complex? run code? simple tone? crisis? — and plan_turn() merges that
answer with the user's toggles into the TurnPlan the rest of the turn reads.

Toggles are overrides, not modes: "Web Search" forces a search and "Explain
Simply" forces simple tone; the classifier decides everything else, including
on those turns. A Feed card never blocks a search.

JSON-schema structured output, never tool calling: the tool-calling classifier
failed on Groq with "Tool choice is required, but model did not call a tool"
and with stringified booleans, and those failures cost a whole extra leg each.
An invalid answer here just falls through to the next model in [classifier].

If every classifier model fails, plan_turn gets None and the turn still runs:
simple route, search only if the user asked for one, and crisis ON. That
fail-safe is code, never something the model has to reason its way to.

Public API
----------
RoutingDecision                                  the JSON the classifier fills
TurnPlan                                         what the rest of the turn reads
classify_message(message, *, history, card_title, metadata) -> RoutingDecision | None
plan_turn(decision, *, message, ...) -> TurnPlan
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .call_logger import LLMCallLogger
from .model_provider import AllLegsFailed, InvalidOutputError, build_leg, route_label, run_route

logger = logging.getLogger(__name__)

_CALL_TYPE = "chat_router_classify"

# The crisis paragraph is carried over verbatim from the previous classifier:
# it is the wording that produced the crisis field this app's safety path
# depends on, and it is not up for casual rewording.
_SYSTEM_PROMPT = (
    "You route one chat turn for a learning assistant. Read the conversation and the user's "
    "latest message, then fill in every field.\n\n"
    "needs_web_search: true when a good answer needs something you cannot be sure of — a recent "
    "event, a current price or statistic, a release or version, someone's current status, "
    "anything after your training data, or a claim the user wants verified. False for "
    "explanations, opinions, code, maths, and anything the conversation or an attached card "
    "already answers.\n"
    "search_query: a short search-engine query for exactly what needs looking up; empty string "
    "when needs_web_search is false.\n"
    "complexity: \"complex\" when the answer needs multi-step reasoning, comparison, synthesis, "
    "or the user asked for depth; \"simple\" for a direct factual or conversational answer.\n"
    "needs_code_execution: true only when answering requires actually RUNNING code — computing a "
    "result, checking what a snippet outputs. False when the user only wants code written or "
    "explained.\n"
    "wants_simple_explanation: true when the user asks for a simple, beginner, plain-English or "
    "ELI5 explanation.\n"
    "crisis: true if the message signals the person is thinking about suicide, self-harm, or not "
    "wanting to be alive — recognize it however it's phrased: plainly, sideways, hypothetically, "
    "bitterly, as a threat, as a joke, or as leverage in an argument they're losing. You cannot "
    "always tell whether they mean it — treat it as real regardless. False for everything else, "
    "including ordinary frustration, dark humor with nothing behind it, or a message that "
    "discusses crisis/mental health as a topic rather than as a personal signal."
)


class RoutingDecision(BaseModel):
    needs_web_search: bool = Field(description="True if answering needs live web data")
    search_query: str = Field(description="Search-ready query; empty string when no search is needed")
    complexity: Literal["simple", "complex"] = Field(
        description="'simple' = direct answer; 'complex' = multi-step reasoning or synthesis")
    needs_code_execution: bool = Field(
        description="True only if the answer requires running code, not just writing it")
    wants_simple_explanation: bool = Field(
        description="True if the user asked for a simple/beginner/ELI5 explanation")
    crisis: bool = Field(
        description="True if the message signals real personal distress (suicide, self-harm, "
                    "not wanting to be alive), however phrased")


@dataclass(frozen=True)
class TurnPlan:
    """What one turn does. Everything downstream reads this and nothing else."""
    route: str          # "simple" | "complex" | "code" | "image" — which model list answers
    reason: str         # "classifier" / "classifier_failed", plus any override that changed it
    search: bool
    search_query: str
    simple_tone: bool
    crisis: bool
    complexity: str     # "simple" | "complex" — also sizes the search


def _history_text(turn: dict) -> str:
    """History can carry multipart content (text plus a Gemini media part on an
    image turn). The classifier only ever needs the text: an image tells it
    nothing about routing, and a file_uri means nothing to another provider."""
    content = turn.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and part.get("type") == "text")
    return ""


def classify_message(
    message: str, *, history: list[dict] | None = None,
    card_title: str = "", metadata: dict | None = None,
) -> RoutingDecision | None:
    """Classify one turn. Returns None (never raises) when every model in the
    [classifier] list fails — the caller treats that as crisis=True."""
    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if card_title:
        messages.append({"role": "system", "content": (
            f'This chat is about a Feed card titled "{card_title}". Its text is already in front '
            "of the answering model, so seeing the card itself is not a reason to search.")})
    for turn in history or []:
        text = _history_text(turn)
        if text:
            messages.append({"role": turn.get("role", "user"), "content": text})
    messages.append({"role": "user", "content": message})

    notes: list[str] = []
    base_meta = {"call_type": _CALL_TYPE, **(metadata or {})}

    def attempt(spec):
        structured = build_leg(spec).with_structured_output(
            RoutingDecision, method="json_schema", include_raw=True)
        result = structured.invoke(messages, config={
            "callbacks": [LLMCallLogger()],
            "metadata": {**base_meta,
                         "route": route_label("classifier", "", notes),
                         "route_step": spec.step},
        })
        parsed = result.get("parsed") if isinstance(result, dict) else result
        if not isinstance(parsed, RoutingDecision):
            error = result.get("parsing_error") if isinstance(result, dict) else None
            raise InvalidOutputError(f"no valid RoutingDecision (parsing_error={error!r})")
        yield parsed

    try:
        _, results = run_route("classifier", attempt, notes=notes)
        return next(iter(results))
    except AllLegsFailed:
        logger.warning("[chat_router] no classifier model answered (%s) — safe plan applies",
                       "; ".join(notes))
        return None


def plan_turn(
    decision: RoutingDecision | None, *, message: str, has_image: bool = False,
    toggle_web_search: bool = False, toggle_simple: bool = False,
    feed_action: str | None = None, sticky_simple: bool = False,
) -> TurnPlan:
    """Merge the classifier's answer with the user's overrides.

    search       Web Search toggle OR decision.needs_web_search
    search_query decision.search_query when it has one, else the user's message
    simple_tone  Explain Simply toggle OR Feed explain_simply OR sticky session
                 OR decision.wants_simple_explanation
    crisis       decision.crisis — and True whenever the classifier failed
    route        image if an image is attached; else code, complex, or simple
    reason       the base plus every override that applied, for the admin log
    """
    overrides: list[str] = []
    if toggle_web_search:
        overrides.append("+toggle:web_search")
    if toggle_simple:
        overrides.append("+toggle:explain_simply")
    if feed_action == "explain_simply":
        overrides.append("+feed:explain_simply")
    if sticky_simple and not toggle_simple:
        overrides.append("+sticky:explain_simply")

    forced_simple = toggle_simple or feed_action == "explain_simply" or sticky_simple

    if decision is None:
        return TurnPlan(
            route="image" if has_image else "simple",
            reason="".join(["classifier_failed", *overrides]),
            search=toggle_web_search,
            search_query=message,
            simple_tone=forced_simple,
            crisis=True,
            complexity="simple",
        )

    if has_image:
        route = "image"
    elif decision.needs_code_execution:
        route = "code"
    elif decision.complexity == "complex":
        route = "complex"
    else:
        route = "simple"

    return TurnPlan(
        route=route,
        reason="".join(["classifier", *overrides]),
        search=toggle_web_search or decision.needs_web_search,
        search_query=(decision.search_query or "").strip() or message,
        simple_tone=forced_simple or decision.wants_simple_explanation,
        crisis=decision.crisis,
        complexity=decision.complexity,
    )
```

- [ ] **Step 4: Run the classifier/plan tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_turn_plan.py -v`
Expected: PASS (24 tests).

- [ ] **Step 5: Update the search tests**

`tests/test_web_search_reasoning_service.py` — the two searches now run concurrently, so a fake that hands out results in call order is no longer deterministic. Replace the `calls = iter([...])` pattern everywhere with a query-keyed fake. Add this helper near `_article` and use it in every test in `TestFetchReasonedResultsDedupAndSlicing` and `TestComplexityScaledCaps` (the primary query is the raw message; the contradiction query is the message plus a suffix):

```python
def _fake_search(monkeypatch, message, primary_raw, contra_raw, seen=None):
    """Query-keyed, not call-ordered: the two searches can now run in parallel."""
    def _search(query, meta=None):
        if seen is not None:
            seen.append(query)
        return list(primary_raw) if query == message else list(contra_raw)
    monkeypatch.setattr(wsr, "_safe_search", _search)
```

Replace the recency test with one that reads the clock:

```python
    def test_recency_language_forces_a_recent_shift_angle_with_this_year(self):
        from datetime import datetime
        year = datetime.now().year
        q = wsr.build_search_queries("What is the current state of AI regulation?")
        assert f"latest news {year - 1} {year}" in q["contradiction_query"]
```

Replace `TestComplexityScaledCaps` cap/search-count expectations:

```python
    def test_caps_for_maps_each_tier(self):
        assert wsr._caps_for("simple")  == (4, 0)
        assert wsr._caps_for("complex") == (5, 4)

    def test_simple_runs_one_search(self, monkeypatch):
        seen = []
        _fake_search(monkeypatch, "msg", [_article(f"p{i}") for i in range(5)],
                     [_article(f"c{i}") for i in range(5)], seen)
        result = wsr.fetch_reasoned_results("msg", complexity="simple")
        assert seen == ["msg"], "a simple turn does not pay for a contradiction search"
        assert len(result["supporting"]) == 4
        assert result["complicating"] == [] and result["has_complicating"] is False

    def test_complex_runs_both_searches(self, monkeypatch):
        seen = []
        _fake_search(monkeypatch, "msg", [_article(f"p{i}") for i in range(5)],
                     [_article(f"c{i}") for i in range(5)], seen)
        result = wsr.fetch_reasoned_results("msg", complexity="complex")
        assert len(seen) == 2
        assert len(result["supporting"]) == 5 and len(result["complicating"]) == 4

    def test_unknown_complexity_keeps_the_old_three_plus_three(self, monkeypatch):
        _fake_search(monkeypatch, "msg", [_article(f"p{i}") for i in range(5)],
                     [_article(f"c{i}") for i in range(5)])
        result = wsr.fetch_reasoned_results("msg")
        assert len(result["supporting"]) == 3 and len(result["complicating"]) == 3
```

Add the new public entry point's tests:

```python
class TestRunChatSearch:
    """The chat turn's whole search step: fetch, note, sources. Replaces the
    model-invoked chat_tools.web_search tool (and its extra LLM round-trip)."""

    def test_note_and_sources_line_up(self, monkeypatch):
        _fake_search(monkeypatch, "q", [_article("https://a", "A")], [_article("https://b", "B")])
        note, sources = wsr.run_chat_search("q", complexity="complex")
        assert "[1]" in note and "https://a" in note
        assert sources == [{"title": "A", "url": "https://a"}, {"title": "B", "url": "https://b"}]

    def test_url_less_results_never_shift_the_numbering(self, monkeypatch):
        good, bad = _article("https://a", "A"), {"title": "no url", "content": "c"}
        _fake_search(monkeypatch, "q", [bad, good], [])
        note, sources = wsr.run_chat_search("q", complexity="simple")
        assert [s["url"] for s in sources] == ["https://a"]
        assert "[2]" not in note

    def test_no_results_gives_an_honest_note(self, monkeypatch):
        _fake_search(monkeypatch, "q", [], [])
        note, sources = wsr.run_chat_search("q", complexity="simple")
        assert "No results" in note and sources == []

    def test_a_search_failure_is_not_fatal(self, monkeypatch):
        def _boom(query, meta=None):
            raise RuntimeError("tinyfish down")
        monkeypatch.setattr(wsr, "_safe_search", _boom)
        monkeypatch.setattr(wsr, "fetch_reasoned_results",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("tinyfish down")))
        note, sources = wsr.run_chat_search("q", complexity="simple")
        assert note == "" and sources == []
```

- [ ] **Step 6: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_search_reasoning_service.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'run_chat_search'`, plus the cap assertions.

- [ ] **Step 7: Update `backend/services/web_search_reasoning_service.py`**

Add `from concurrent.futures import ThreadPoolExecutor` and `from datetime import datetime` to the imports, then:

Replace `_TIER_CAPS` (line 59) and add the year helper:

```python
# The tier now decides how many SEARCHES run, not just how many results survive.
#   simple  = one query, 4 results. A simple turn ("capital of Japan", "who is
#             the CEO of X") does not need a contradiction angle, and skipping
#             that second search takes ~2s off the turn; 4 primary results keep
#             the same source count the old 2+2 delivered.
#   complex = both queries, run concurrently, 5 + 4 kept. 5 is the hard ceiling
#             on primary (tinyfish_service slices each search to 5) and 4 sits
#             just above the measured 3.71 mean of genuinely new complicating
#             results, so it fills on most turns without asking for air.
# Anything else (including None) keeps the old fixed 3+3, two searches.
_TIER_CAPS: dict[str, tuple[int, int]] = {
    "simple":  (4, 0),
    "complex": (5, 4),
}


def _recent_years() -> str:
    """This year and last, from the clock. The old suffix hardcoded "2024 2025"
    and silently aged into a stale recency filter."""
    year = datetime.now().year
    return f"{year - 1} {year}"
```

In `_INTENT_CONTRADICTION_SUFFIXES`, change the `historical` entry to `"reversal setback recent shift {years}"`.

In `build_search_queries`, replace the recency block (lines 158-165) with:

```python
    suffix = suffix.replace("{years}", _recent_years())

    # For recency-flagged messages, force a recent-shift angle.
    if re.search(r"\b(current|today|now|recent|latest|modern|this year|(?:19|20)\d{2})\b", message, re.I):
        suffix = f"latest news {_recent_years()} problems challenges reversal"
```

In `fetch_reasoned_results`, replace the two sequential `_safe_search` calls (lines 218-226) with:

```python
    primary_cap, contra_cap = _caps_for(complexity)

    t0 = time.monotonic()
    if contra_cap == 0:
        # Simple turn: one query, no contradiction angle to pay for.
        raw_primary_articles, raw_contra_articles = _safe_search(p_query, meta=meta), []
        c_query = ""
    else:
        # Both queries at once: they are independent network calls, and running
        # them back to back cost a measured 4.2-4.8s of the turn.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-search") as pool:
            primary_job = pool.submit(_safe_search, p_query, meta)
            contra_job = pool.submit(_safe_search, c_query, meta)
            raw_primary_articles, raw_contra_articles = primary_job.result(), contra_job.result()

    _log_raw_result_set(p_query, c_query, raw_primary_articles, raw_contra_articles, t0, meta)

    primary_articles = raw_primary_articles[:primary_cap]
    contra_articles = raw_contra_articles
```

Add the new public function after `fetch_reasoned_results`:

```python
def run_chat_search(query: str, *, complexity: str | None = None,
                    meta: dict | None = None) -> tuple[str, list[dict]]:
    """One chat turn's whole search step: fetch, build the note the model reads,
    and return the [{title, url}] list the frontend resolves [N] citations
    against. Moved here from the retired chat_tools.web_search tool — same
    formatter, same log row, minus the extra LLM round-trip a tool call cost.

    Filtering url-less articles ONCE, before the note and the source list are
    built, is what keeps citation [N] pointing at sources[N-1]. Never raises: a
    dead search degrades the turn, it does not fail it.
    """
    from .chat_modes_service import format_reasoning_search_note

    t0 = time.monotonic()
    try:
        reasoning = fetch_reasoned_results(query, meta=meta, complexity=complexity)
    except Exception as exc:
        logger.warning("[web_search] chat search failed for %r", query[:60], exc_info=True)
        _log_chat_search(query, "", t0, meta, success=False, error=exc)
        return "", []

    supporting = [a for a in reasoning.get("supporting", []) if a.get("url")]
    complicating = [a for a in reasoning.get("complicating", []) if a.get("url")]
    if not supporting and not complicating:
        note = "[WEB SEARCH]: No results retrieved for this query."
        _log_chat_search(query, note, t0, meta, success=True)
        return note, []

    note = format_reasoning_search_note(
        {**reasoning, "supporting": supporting, "complicating": complicating})
    sources = [{"title": (a.get("title") or "").strip(), "url": a.get("url", "")}
               for a in supporting + complicating]
    _log_chat_search(query, note, t0, meta, success=True)
    return note, sources


def _log_chat_search(query: str, output: str, t0: float, meta: dict | None,
                     *, success: bool, error: Exception | None = None) -> None:
    """One llm_call_log row per chat search — same shape chat_tools.web_search
    wrote, so the admin panel's existing chat_web_search rows stay continuous.
    provider="none": this is retrieval, not a model completion. Never raises."""
    from datetime import timezone
    from uuid import uuid4
    from ..llm.call_logger import write_call_row

    meta = meta or {}
    now = datetime.now(timezone.utc).isoformat()
    write_call_row(
        run_id=uuid4().hex,
        parent_run_id=None,
        timestamp_start=now,
        timestamp_end=now,
        latency_ms=int((time.monotonic() - t0) * 1000),
        provider="none",
        call_type="chat_web_search",
        user_id=meta.get("user_id"),
        input_text=query,
        output=output,
        success=success,
        error_type=type(error).__name__ if error else None,
        error_message=str(error) if error else None,
        trace_id=meta.get("trace_id"),
        agent_name="web_search",
        surface=meta.get("surface", "chat"),
        is_test=bool(meta.get("is_test", False)),
    )
```

(Task 8 adds `route="web_search"` to this call once `write_call_row` has that keyword.)

- [ ] **Step 8: Run the search tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_web_search_reasoning_service.py -v`
Expected: PASS.

- [ ] **Step 9: Rewire `backend/services/chat_service.chat_stream`**

Nine edits, top to bottom. Line numbers are from the pre-task file.

**(a)** Delete `_FEED_ACTION_TO_MODE` (lines 56-60) — a Feed action no longer maps to a mode; `plan_turn` reads the action itself.

**(b)** Replace the feed-context / agent-name / layman-restore block (lines 158-210) with:

```python
        # Feed context: enrich, and resolve the card this chat is anchored to
        feed_action = None
        if feed_context:
            _enrich_feed_context(feed_context)
            if topic_hint is None:
                topic_hint = feed_context.get("insight_title") or _detect_topic_hint(message)
            feed_action = feed_context.get("action") or "ask_about"
        elif topic_hint is None:
            topic_hint = _detect_topic_hint(message)

        # feed_context carries the card on turn 1; the feed_chat_links row (written
        # only after that turn completes) carries it on every turn after. Together:
        # no gap. Used for the admin-log tag and for the classifier's card title.
        link_row = None
        if not feed_context:
            try:
                from .feed_chat_link_service import get_link_for_session
                link_row = get_link_for_session(session_id)
            except Exception:
                logger.debug("[chat_service] feed link lookup failed (non-fatal)")
        if feed_context:
            feed_agent_name = f"feed_{feed_action}"
        elif link_row:
            feed_agent_name = f"feed_{link_row.get('interaction_type') or 'ask_about'}"
        else:
            feed_agent_name = None
        card_title = ((feed_context or {}).get("insight_title")
                      or (link_row or {}).get("article_title") or "")

        # Toggles are overrides, not modes: the request's chat_mode only says
        # whether the user pressed Web Search or Explain Simply. Everything else
        # about this turn is the classifier's call.
        toggle_web_search = chat_mode == "web_search"
        toggle_simple     = chat_mode == "layman"
        sticky_simple     = False
        try:
            from .chat_title_service import get_session_conversation_mode, set_session_conversation_mode
            if toggle_web_search:
                # An explicit tool toggle is never ambiguous — clear stale simple-mode
                # stickiness now, so a later plain turn cannot silently inherit it.
                set_session_conversation_mode(session_id, "normal")
            elif not toggle_simple and get_session_conversation_mode(session_id) == "layman":
                if _requests_layman_exit(message):
                    set_session_conversation_mode(session_id, "normal")
                else:
                    sticky_simple = True
        except Exception:
            logger.debug("[chat_service] conversation-mode lookup failed (non-fatal)")
```

**(c)** Replace the router submission block (lines 212-250) with:

```python
        history       = _load_history_messages(session_id, limit=50)
        history_turns = len(history) // 2

        # The classifier is a real 1-8s round trip whose only inputs are the
        # message, the recent turns and the card title — start it here so it
        # overlaps the context work below, and join it just before the prompt is
        # built (its crisis field decides whether a prompt section goes in).
        from ..llm.chat_router import classify_message, plan_turn
        from .chat_prompt_service import MAX_HISTORY_TURNS
        _router_metadata = {"trace_id": trace_id, "surface": "chat", "is_test": is_test}
        if user_id:
            _router_metadata["user_id"] = user_id
        if feed_agent_name:
            _router_metadata["agent_name"] = feed_agent_name
        router_future = _ROUTER_EXECUTOR.submit(
            classify_message, message,
            history=history[-(MAX_HISTORY_TURNS * 2):],
            card_title=card_title,
            metadata=_router_metadata,
        )
```

**(d)** In the intent block (lines 252-266) drop the `format_intent` lines — nothing reads them once the JSON prompt is gone. Keep `detect_intent` itself: `intent_profile` still feeds the post-turn recommendation enrichment.

```python
        from .chat_intent_service import detect_intent as _detect_intent
        intent = _detect_intent(message)

        from .memory_injection_service import inject_memory as _inject
        context = _inject(session_id, topic_hint, user_id=user_id)
        context["intent_profile"]  = intent.get("intent_profile", {})
        context["current_message"] = message
```

**(e)** Delete the layman-context block (lines 297-302), the action-router call (lines 310-313), the depth detection (lines 315-317) and the shared-learning-context block (lines 319-328) — the first three feed only deleted prompt sections, and the fourth moves below the plan so it can ask for the tone this turn actually uses.

**(f)** Delete the `feed_linked` / `feed_action` / `feed_topic` block (lines 354-376). Keep the `feed_entry_anchor` lookup above it.

**(g)** Replace the router join and crisis block (lines 378-423) with:

```python
        decision = router_future.result()
        plan = plan_turn(
            decision,
            message=message,
            has_image=bool(image_attachments),
            toggle_web_search=toggle_web_search,
            toggle_simple=toggle_simple,
            feed_action=feed_action,
            sticky_simple=sticky_simple,
        )

        # Phase U: a crisis turn keeps the section alive for the next few turns
        # even when a follow-up ("fuck you", a topic swerve) would not classify as
        # crisis on its own — that is one of the ordinary shapes distress comes
        # back in. Turn-count decay, not wall-clock: a long pause mid-conversation
        # must not silently expire it.
        from .chat_title_service import get_session_crisis_expiry, set_session_crisis_expiry
        turn_number = history_turns + 1
        persisted_expiry = get_session_crisis_expiry(session_id)
        persisted_active = persisted_expiry is not None and turn_number <= persisted_expiry
        context["crisis_active"] = plan.crisis or persisted_active
        if context["crisis_active"]:
            set_session_crisis_expiry(session_id, turn_number + _CRISIS_WINDOW_TURNS)

        # Phase 4.6 shared learning context — asked for in the tone this turn
        # actually answers in, not the request's raw chat_mode.
        _project_id = (feed_context or {}).get("project_id", "") if feed_context else ""
        if _project_id:
            try:
                from .shared_learning_context import get_shared_prompt_block as _shared_block
                _block = _shared_block(_project_id, mode="layman" if plan.simple_tone else "normal")
                if _block:
                    context["shared_learning_context"] = _block
            except Exception:
                logger.debug("[chat_service] shared learning context failed (non-fatal)")

        from .chat_prompt_service import build_messages as _build
        messages_payload = _build(history, message, context,
                                  simple_tone=plan.simple_tone,
                                  attachments=image_attachments or None)
```

**(h)** Replace the tool-policy and task-type blocks (lines 507-547, everything between the context `except` and `is_new_session = len(history) == 0`) with the numbering helper and the search step:

```python
    # ── Block / sequence numbering ────────────────────────────────────────────
    # seq is a flat per-turn counter; block_id groups contiguous same-kind events
    # into one logical block, and a search's start/end pair shares one. Assigned
    # here, in one place, because the turn now emits events from two sources (the
    # search step and the answer stream) whose numbering must not collide.
    _ids = {"seq": 0, "block": -1, "kind": None}

    def _next_ids(kind: str, same_block: bool = False) -> tuple[int, int]:
        _ids["seq"] += 1
        if not same_block and (kind != _ids["kind"] or kind == "tool_call"):
            _ids["block"] += 1
        _ids["kind"] = kind
        return _ids["seq"], _ids["block"]

    blocks:  list[dict] = []
    sources: list[dict] = []
    searched = False

    # ── Web search: run here, not by the model ────────────────────────────────
    # Same NDJSON status events and same persisted tool_call block the tool used
    # to produce, so the frontend's live search block and [N] citations are
    # unchanged — without the second LLM round-trip a tool call cost.
    if plan.search:
        seq, block_id = _next_ids("tool_call")
        yield json.dumps({
            "t": "status", "v": "Searching the web…", "seq": seq, "block_id": block_id,
            "tool": "web_search", "query": plan.search_query,
        }) + "\n"
        search_block = {"type": "tool_call", "tool": "web_search",
                        "query": plan.search_query, "sources": []}
        blocks.append(search_block)
        try:
            from .web_search_reasoning_service import run_chat_search
            _search_meta = {"trace_id": trace_id, "surface": "chat", "is_test": is_test}
            if user_id:
                _search_meta["user_id"] = user_id
            search_note, sources = run_chat_search(
                plan.search_query, complexity=plan.complexity, meta=_search_meta)
        except Exception:
            logger.exception("chat_stream: web search failed (non-fatal)")
            search_note, sources = "", []
        if search_note:
            messages_payload = _inject_mode_note(messages_payload, search_note)
        search_block["sources"] = sources
        searched = True
        seq, block_id = _next_ids("tool_call", same_block=True)
        yield json.dumps({
            "t": "status", "v": "Reviewing results…", "seq": seq, "block_id": block_id,
            "tool": "web_search", "sources": sources,
        }) + "\n"
```

**(i)** Replace the stream section (lines 588-737, from `from .chat_title_service import stream_extract_state` down to the `except Exception as exc` that yields the error) with:

```python
    from .chat_title_service import stream_extract_state, advance_stream_state
    title_state     = stream_extract_state() if is_new_session else None
    collected:       list[str] = []
    thinking_chunks: list[str] = []
    extracted_title: str | None = None
    _block_index: dict[int, int] = {}

    def _block_entry(block_id: int, factory):
        if block_id in _block_index:
            return blocks[_block_index[block_id]]
        _block_index[block_id] = len(blocks)
        entry = factory()
        blocks.append(entry)
        return entry

    try:
        from ..llm.chat_agent import ask_chat_stream
        _call_metadata: dict = {
            "call_type": "chat_turn",
            "trace_id": trace_id, "surface": "chat", "is_test": is_test,
        }
        if user_id:
            _call_metadata["user_id"] = user_id
        if feed_agent_name:
            _call_metadata["agent_name"] = feed_agent_name

        # TEMPORARY (removed in Task 5): the old agent still answers, but driven
        # by the plan instead of chat_mode, and with tools off — the search above
        # already ran. Task 5 replaces this call with
        # ask_chat_stream(messages_payload, route=plan.route,
        #                 route_reason=plan.reason, metadata=_call_metadata).
        _LEGACY_TASK_TYPE = {"simple": "simple_qa", "complex": "complex_reasoning", "code": "coding"}
        for event in ask_chat_stream(
            messages_payload, metadata=_call_metadata, tools_enabled=False,
            has_attachments=bool(image_attachments),
            task_type=None if plan.route == "image" else _LEGACY_TASK_TYPE[plan.route],
        ):
            kind = event["type"]
            if kind == "status":
                yield json.dumps({"t": "status", "v": event.get("text") or "Working…"}) + "\n"
                continue
            if kind in ("thinking_gap", "code_execution_gap"):
                yield json.dumps({"t": kind, "v": event["text"]}) + "\n"
                continue

            seq, block_id = _next_ids(kind)
            if kind == "thinking":
                # Bypasses title extraction: that parser only ever needs answer text.
                thinking_chunks.append(event["text"])
                entry = _block_entry(block_id, lambda: {"type": "thinking", "text": ""})
                entry["text"] += event["text"]
                yield json.dumps({"t": "thinking", "v": event["text"],
                                  "seq": seq, "block_id": block_id}) + "\n"
                continue
            if kind == "code":
                yield json.dumps({"t": "code", "v": event["text"],
                                  "language": event.get("language", "python")}) + "\n"
                continue
            if kind == "code_output":
                yield json.dumps({"t": "code_output", "v": event["text"],
                                  "success": event.get("success", True)}) + "\n"
                continue

            chunk = event["text"]
            if title_state is not None:
                result = advance_stream_state(title_state, chunk)
                if result["title"] and not extracted_title:
                    extracted_title = result["title"]
                    yield json.dumps({"t": "title", "v": extracted_title}) + "\n"
                if result["forward"] is None:
                    continue
                chunk = result["forward"]
            collected.append(chunk)
            entry = _block_entry(block_id, lambda: {"type": "text", "text": ""})
            entry["text"] += chunk
            yield json.dumps({"t": "chunk", "v": chunk, "seq": seq, "block_id": block_id}) + "\n"
    except Exception as exc:
        logger.exception("chat_stream: AI generation failed")
        yield json.dumps({"t": "error", "message": str(exc)}) + "\n"
        return
```

**(j)** Replace the resolved-mode lines (749-752), the layman persistence block (780-786) and the `"action"` key in the done event (861):

```python
    # What actually happened this turn, not what was pre-selected.
    resolved_mode = "web_search" if searched else ("layman" if plan.simple_tone else "normal")
    auto_mode     = searched and not toggle_web_search
```

```python
    # Sticky simple mode only when the USER asked for it (toggle, Feed card, or an
    # already-sticky session). A classifier-detected "explain simply" answers this
    # turn in that tone without silently pinning the rest of the session to it.
    if toggle_simple or feed_action == "explain_simply" or sticky_simple:
        try:
            from .chat_title_service import set_session_conversation_mode
            set_session_conversation_mode(session_id, "layman")
        except Exception:
            logger.exception("chat_stream: simple-mode persistence failed (non-fatal)")
```

Delete the `"action": action_result.get("action") if action_result else None,` line from the done event.

- [ ] **Step 10: Update the turn-level tests**

In `tests/test_chat_mode_mapping.py`, replace `TestStreamReflectsActualToolUse` (the class docstring's premise — the model decides to call a tool — is what this work removes):

```python
class TestStreamReflectsThePlan:
    """chat_mode/auto_mode/sources in the done event now report what the TURN
    PLAN did: the search is run by chat_service, never by the model."""

    def _run(self, message, chat_mode, decision, search=("note", [{"title": "T", "url": "https://example.com"}])):
        from backend.llm.chat_router import RoutingDecision
        from backend.services.chat_service import chat_stream

        def fake_ask_chat_stream(messages, *args, **kwargs):
            yield {"type": "text", "text": "answer"}

        events = []
        with patch("backend.services.chat_service._detect_topic_hint", return_value=None), \
             patch("backend.services.chat_service._load_history_messages", return_value=[]), \
             patch("backend.services.chat_service._save_message", return_value=1), \
             patch("backend.services.memory_injection_service.inject_memory", return_value={}), \
             patch("backend.services.domain_classifier_service.get_domain_context", return_value={}), \
             patch("backend.services.chat_prompt_service.build_messages",
                   return_value=[{"role": "user", "content": message}]), \
             patch("backend.llm.chat_router.classify_message",
                   return_value=None if decision is None else RoutingDecision(**decision)), \
             patch("backend.services.web_search_reasoning_service.run_chat_search",
                   return_value=search), \
             patch("backend.services.follow_up_service.get_recommendations",
                   return_value={"based_on_topic": None, "source": "empty",
                                 "next_topics": [], "prerequisites": [], "advanced_topics": []}), \
             patch("backend.llm.chat_agent.ask_chat_stream", side_effect=fake_ask_chat_stream):
            for line in chat_stream("sess", message, chat_mode=chat_mode):
                if line.strip():
                    events.append(json.loads(line))
        return events, next(e for e in events if e["t"] == "done")

    _NO_SEARCH = dict(needs_web_search=False, search_query="", complexity="simple",
                      needs_code_execution=False, wants_simple_explanation=False, crisis=False)

    def test_classifier_search_marks_the_turn_as_web_search(self):
        events, done = self._run("who won yesterday", "normal",
                                 {**self._NO_SEARCH, "needs_web_search": True, "search_query": "q"})
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is True
        assert done["sources"] == [{"title": "T", "url": "https://example.com"}]
        statuses = [e["v"] for e in events if e["t"] == "status"]
        assert "Searching the web…" in statuses

    def test_toggle_searches_even_when_the_classifier_would_not(self):
        _, done = self._run("explain attention", "web_search", self._NO_SEARCH)
        assert done["chat_mode"] == "web_search"
        assert done["auto_mode"] is False, "the user asked for it, so it is not automatic"

    def test_plain_turn_runs_no_search(self):
        events, done = self._run("what is attention?", "normal", self._NO_SEARCH)
        assert done["chat_mode"] == "normal" and done["sources"] == []
        assert not [e for e in events if e["t"] == "status" and e.get("tool")]

    def test_simple_tone_turn_reports_layman(self):
        _, done = self._run("eli5 attention", "layman", self._NO_SEARCH)
        assert done["chat_mode"] == "layman"

    def test_classifier_failure_still_answers(self):
        _, done = self._run("hello", "normal", None)
        assert done["chat_mode"] == "normal"

    def test_search_block_and_text_do_not_share_a_block_id(self):
        events, _ = self._run("who won yesterday", "normal",
                              {**self._NO_SEARCH, "needs_web_search": True, "search_query": "q"})
        search_ids = {e["block_id"] for e in events if e["t"] == "status" and e.get("tool")}
        chunk_ids = {e["block_id"] for e in events if e["t"] == "chunk"}
        assert len(search_ids) == 1 and search_ids.isdisjoint(chunk_ids)
```

Also delete the now-meaningless `patch("backend.services.action_router_service.route", ...)` lines from `tests/test_chat_title_service.py`, `tests/test_chat_quickstarters.py` and `tests/test_chat_intent_service.py` (chat_service no longer calls it), and delete `TestResolveToolsAndHint` from `tests/test_chat_mode_mapping.py` (that function goes in Task 5).

- [ ] **Step 11: Run the suite**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20`
Expected: baseline failures only. `tests/test_streaming.py::TestChatStreamGenerator::test_done_event_action_from_route` now fails (the `action` key is gone) — delete that test here; its subject is removed in Task 7.

- [ ] **Step 12: Commit**

```bash
git add backend/llm/chat_router.py backend/services/chat_service.py backend/services/web_search_reasoning_service.py tests/test_turn_plan.py tests/test_web_search_reasoning_service.py tests/test_chat_mode_mapping.py tests/test_chat_title_service.py tests/test_chat_quickstarters.py tests/test_chat_intent_service.py tests/test_streaming.py
git commit -m "feat(chat): one classifier, one turn plan, code-run web search

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The answer streaming loop

`chat_agent.py` stops being a LangGraph agent and becomes ~120 lines: pick the route's legs, stream, fall through on a failure before the first chunk, surface anything after it.

**Files:**
- Rewrite: `backend/llm/chat_agent.py`
- Modify: `backend/services/chat_service.py` (the temporary adapter from Task 4), `backend/llm/model_provider.py` (drop `_is_daily_quota_exhausted`)
- Create: `tests/test_chat_answer_stream.py`
- Delete: `tests/test_chat_agent_code_execution_middleware.py`

**Interfaces:**
- Consumes: `model_provider.run_route / build_leg / route_label / registry_model_name / PromptTooLargeError / AllLegsFailed / _is_gemini_3_plus`, `call_logger.LLMCallLogger`, `chat_router.TurnPlan` (via chat_service).
- Produces: `chat_agent.ask_chat_stream(messages, *, route, route_reason="", metadata=None) -> Iterator[dict]`, `chat_agent.VisionUnavailableError`, `chat_agent._split_content_chunks` (kept as-is).

- [ ] **Step 1: Write the failing answer-loop tests**

Create `tests/test_chat_answer_stream.py`:

```python
"""The answer loop: which leg answers, what falls through, what reaches the user.

No agent, no middleware — a failure before the first chunk tries the next
model, a failure after it is the user's problem to see rather than a second
answer silently replacing a half-written one."""
from __future__ import annotations

import pytest

from backend.llm import chat_agent, model_provider as mp
from backend.llm import rate_limits


class _Chunk:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    """Stands in for a built leg: records the config it was streamed with."""

    def __init__(self, script, spec):
        self._script, self.spec = script, spec
        self.configs = []
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def stream(self, messages, config=None):
        self.configs.append(config)
        for item in self._script:
            if isinstance(item, Exception):
                raise item
            yield _Chunk(item)


def _legs(monkeypatch, script_by_step, route="simple"):
    """Build a fake leg per step; returns the models actually constructed."""
    rate_limits.clear()
    monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["only-key"])
    built = []

    def _build(spec, **kwargs):
        model = _FakeModel(script_by_step.get(spec.step, ["text"]), spec)
        built.append(model)
        return model

    monkeypatch.setattr(chat_agent, "build_leg", _build)
    monkeypatch.setattr(chat_agent, "_check_budget", lambda spec, messages: None)
    return built


MESSAGES = [{"role": "user", "content": "hi"}]


class TestHappyPath:
    def test_text_chunks_reach_the_caller(self, monkeypatch):
        _legs(monkeypatch, {1: ["Hel", "lo"]})
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["Hel", "lo"]

    def test_route_and_step_are_logged_on_the_call(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["ok"]})
        list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier",
                                        metadata={"call_type": "chat_turn"}))
        meta = built[0].configs[0]["metadata"]
        assert meta["route"] == "simple ← classifier"
        assert meta["route_step"] == 1
        assert meta["call_type"] == "chat_turn"
        assert built[0].configs[0]["callbacks"], "logger must be passed per call, not baked on"

    def test_gemini_thinking_and_code_parts_are_split_out(self, monkeypatch):
        _legs(monkeypatch, {1: [[
            {"type": "thinking", "thinking": "weighing it up"},
            {"type": "text", "text": "answer"},
            {"type": "executable_code", "executable_code": "print(2)", "language": "PYTHON"},
            {"type": "code_execution_result", "code_execution_result": "2", "outcome": 1},
        ]]})
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple"))
        kinds = [e["type"] for e in events]
        assert kinds == ["thinking", "text", "code", "code_output"]
        assert events[2]["language"] == "python"
        assert events[3]["success"] is True


class TestFallback:
    def test_failure_before_the_first_chunk_tries_the_next_model(self, monkeypatch):
        built = _legs(monkeypatch, {1: [RuntimeError("Error code: 400 - bad request")], 2: ["second"]})
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["second"]
        assert built[1].configs[0]["metadata"]["route"] == (
            "simple ← classifier · skipped groq/openai/gpt-oss-120b (fatal)")
        assert built[1].configs[0]["metadata"]["route_step"] == 2

    def test_failure_after_the_first_chunk_reaches_the_user(self, monkeypatch):
        _legs(monkeypatch, {1: ["half an ", RuntimeError("connection dropped")], 2: ["never used"]})
        stream = chat_agent.ask_chat_stream(MESSAGES, route="simple")
        assert next(stream)["text"] == "half an "
        with pytest.raises(RuntimeError, match="connection dropped"):
            list(stream)

    def test_over_budget_leg_is_skipped_without_being_called(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["never"], 2: ["fits"]})
        monkeypatch.setattr(chat_agent, "_check_budget", lambda spec, messages: (
            (_ for _ in ()).throw(mp.PromptTooLargeError("9000 > 7000")) if spec.step == 1 else None))
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["fits"]
        assert "(budget)" in built[1].configs[0]["metadata"]["route"]

    def test_every_leg_failing_raises(self, monkeypatch):
        _legs(monkeypatch, {step: [RuntimeError("Error code: 400 - nope")] for step in (1, 2, 3)})
        with pytest.raises(mp.AllLegsFailed):
            list(chat_agent.ask_chat_stream(MESSAGES, route="simple"))


class TestRouteSpecificBehaviour:
    def test_code_route_binds_gemini_code_execution_on_a_gemini_3_leg(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["ok"]}, route="code")
        list(chat_agent.ask_chat_stream(MESSAGES, route="code"))
        assert built[0].bound_tools == [{"code_execution": {}}]

    def test_code_route_warns_once_when_the_answering_leg_cannot_run_code(self, monkeypatch):
        built = _legs(monkeypatch, {1: [RuntimeError("Error code: 400 - nope")],
                                    2: [RuntimeError("Error code: 400 - nope")], 3: ["prose"]},
                      route="code")
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="code"))
        assert events[0]["type"] == "code_execution_gap"
        assert built[2].bound_tools is None

    def test_gemini_3_leg_says_thinking_will_not_stream(self, monkeypatch):
        _legs(monkeypatch, {1: ["ok"]}, route="code")   # code's first leg is gemini 3.1-flash-lite
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="code"))
        assert events[0]["type"] == "thinking_gap"

    def test_image_route_announces_itself_and_fails_clearly(self, monkeypatch):
        _legs(monkeypatch, {step: [RuntimeError("Error code: 400 - nope")] for step in (1, 2)},
              route="image")
        stream = chat_agent.ask_chat_stream(MESSAGES, route="image")
        assert next(stream) == {"type": "status", "text": "Reading attachment…"}
        with pytest.raises(chat_agent.VisionUnavailableError, match="temporarily unavailable"):
            list(stream)

    def test_parked_leg_is_not_called_at_all(self, monkeypatch):
        built = _legs(monkeypatch, {1: ["never"], 2: ["used"]})
        rate_limits.record_failure("groq", "openai/gpt-oss-120b", 0, "daily_quota")
        events = list(chat_agent.ask_chat_stream(MESSAGES, route="simple", route_reason="classifier"))
        assert [e["text"] for e in events if e["type"] == "text"] == ["used"]
        assert "(daily_quota)" in built[0].configs[0]["metadata"]["route"]
        rate_limits.clear()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chat_answer_stream.py -v`
Expected: FAIL — `TypeError: ask_chat_stream() got an unexpected keyword argument 'route'`.

- [ ] **Step 3: Rewrite `backend/llm/chat_agent.py`**

Replace the whole file. `_split_content_chunks` is copied over **verbatim** from the old file (docstring included) — it is the part that still earns its place.

```python
"""Chat's answer stream: one model list, tried top to bottom, no agent.

Replaces the LangGraph create_agent stack (ModelFallbackMiddleware +
ModelRetryMiddleware + CodeExecutionToolMiddleware + a web_search tool). What
that stack bought is now: model_provider.run_route for fallback and retry, a
bare model's .stream() for per-token output, and one bind_tools call for
Gemini's own code execution. The search runs in chat_service before the answer
starts, so no client-side tool is bound at all.

Rules carried over, each verified live when it was found:
  - Callbacks are passed PER CALL, never baked onto the model: a model built
    with callbacks collapses per-token streaming into one chunk per turn.
  - Gemini 3.x never streams its thinking (reproduced against google-genai's
    raw SDK, so not a LangChain bug) - say so once instead of showing a panel
    that never fills.
  - code_execution is a Gemini-3-only capability. On any other leg the model
    still writes code, it just cannot run it: a soft degrade with one note.
  - An image turn uses the primary Gemini key only - a file uploaded with key
    #1 is 403 for key #2 - and fails with a clear message rather than falling
    through legs that structurally cannot see it. route_legs() enforces the
    key; VisionUnavailableError carries the message.

Event shapes (unchanged; chat_service adds seq/block_id):
  {"type": "text",        "text": str}
  {"type": "thinking",    "text": str}
  {"type": "code",        "text": str, "language": str}
  {"type": "code_output", "text": str, "success": bool}
  {"type": "status" | "thinking_gap" | "code_execution_gap", "text": str}

Public API
----------
ask_chat_stream(messages, *, route, route_reason="", metadata=None) -> Iterator[dict]
VisionUnavailableError
"""
from __future__ import annotations

import logging

from .call_logger import LLMCallLogger
from .model_provider import (
    AllLegsFailed,
    PromptTooLargeError,
    _is_gemini_3_plus,
    build_leg,
    registry_model_name,
    route_label,
    run_route,
)

logger = logging.getLogger(__name__)


class VisionUnavailableError(RuntimeError):
    """Every Gemini leg failed on a turn carrying an image. Deliberately not
    retried anywhere else: Groq has no vision model in this stack, and a second
    Gemini key cannot read a file the first one uploaded."""


_THINKING_GAP_TEXT = (
    "Extended reasoning ran but isn't visible for this response — a known "
    "streaming limitation on this model tier. It still happened (and was "
    "billed), it just can't be shown."
)

_CODE_EXECUTION_GAP_TEXT = (
    "Code execution wasn't available for this response — the model wrote "
    "code but couldn't run it. The code below is unexecuted."
)


def _check_budget(spec, messages: list[dict]) -> None:
    """Skip a leg this prompt cannot fit instead of paying for a guaranteed 413.
    Matters because the free Groq legs are capped by tokens-per-minute (8K), not
    by context window. Estimation failures are non-fatal: a broken estimate must
    never block a turn that would have worked."""
    from ..services.model_registry import get_model_config
    from ..services.token_budget import BudgetStatus, estimate_total_request, evaluate, log_budget_plan

    try:
        name = registry_model_name(spec)
        tokens = estimate_total_request(messages=messages)
        plan = evaluate(tokens, name, provider_tier=get_model_config(name).default_provider_tier)
        log_budget_plan(plan, logger)
    except Exception:
        logger.debug("[chat_agent] budget pre-check failed (non-fatal)", exc_info=True)
        return
    if plan.status == BudgetStatus.OVER_LIMIT:
        raise PromptTooLargeError(
            f"{plan.current_prompt_tokens:,} prompt tokens > "
            f"{plan.available_input_budget:,} effective budget for {name}")


def _split_content_chunks(content):
    <<COPY VERBATIM from the pre-task backend/llm/chat_agent.py, lines 453-497,
      including its docstring: the "thinking"/"reasoning", "executable_code" and
      "code_execution_result" handling is live-verified behaviour and must not be
      retyped from memory.>>


def ask_chat_stream(messages: list[dict], *, route: str, route_reason: str = "",
                    metadata: dict | None = None):
    """Stream one chat turn through `route`'s model list.

    `route` / `route_reason` come from the TurnPlan and are written to every
    llm_call_log row this turn makes, so the admin log says which list answered
    and what it fell past.
    """
    notes: list[str] = []
    base_meta = dict(metadata or {})

    def attempt(spec):
        _check_budget(spec, messages)
        model = build_leg(spec, streaming=True, thinking=True)
        if route == "code" and spec.provider == "gemini" and _is_gemini_3_plus(spec.model):
            # Gemini's own server-side tool. No tool_config flag needed now that
            # chat binds no function-calling tool alongside it.
            model = model.bind_tools([{"code_execution": {}}])
        return model.stream(messages, config={
            "callbacks": [LLMCallLogger()],
            "metadata": {**base_meta,
                         "route": route_label(route, route_reason, notes),
                         "route_step": spec.step},
        })

    if route == "image":
        yield {"type": "status", "text": "Reading attachment…"}

    try:
        spec, chunks = run_route(route, attempt, notes=notes)
    except AllLegsFailed as exc:
        if route == "image":
            raise VisionUnavailableError(
                "Vision is temporarily unavailable — please try again in a moment.") from exc
        raise

    answered_on_gemini_3 = spec.provider == "gemini" and _is_gemini_3_plus(spec.model)
    if answered_on_gemini_3:
        yield {"type": "thinking_gap", "text": _THINKING_GAP_TEXT}
    if route == "code" and not answered_on_gemini_3:
        yield {"type": "code_execution_gap", "text": _CODE_EXECUTION_GAP_TEXT}

    for chunk in chunks:
        for kind, text, meta in _split_content_chunks(getattr(chunk, "content", "")):
            event = {"type": kind, "text": text}
            if meta:
                event.update(meta)
            yield event
```

- [ ] **Step 4: Run the answer-loop tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chat_answer_stream.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Drop the temporary adapter in `chat_service`**

Replace the `_LEGACY_TASK_TYPE` block from Task 4 (edit (i)) with the real call:

```python
        for event in ask_chat_stream(messages_payload, route=plan.route,
                                     route_reason=plan.reason, metadata=_call_metadata):
```

- [ ] **Step 6: Remove the now-unused quota helper**

`backend/llm/model_provider.py`: delete `_is_daily_quota_exhausted` (the last importer was the old `chat_agent._retry_on`; `_QuotaAwareRetry` moved to `classify_error` in Task 3). Confirm zero references first:

```bash
grep -rn "_is_daily_quota_exhausted" backend/ tests/ scripts/
```

- [ ] **Step 7: Delete the middleware test**

```bash
git rm tests/test_chat_agent_code_execution_middleware.py
```

Its subject (`CodeExecutionToolMiddleware`) no longer exists; `test_chat_answer_stream.py::TestRouteSpecificBehaviour` is the replacement coverage.

- [ ] **Step 8: Run the suite**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20`
Expected: baseline failures only.

- [ ] **Step 9: Commit**

```bash
git add backend/llm/chat_agent.py backend/llm/model_provider.py backend/services/chat_service.py tests/test_chat_answer_stream.py
git commit -m "feat(chat): stream answers through a plain model fallback loop

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Prompts — one builder, smaller, same rules

**Rule for this whole task: every behaviour rule survives.** What goes is duplication (two personas, two principle copies, the card mechanism repeated up to four times), dead weight (the JSON card schema with 0 real uses since 2026-08-01, its section builders, the tension block whose examples repeat the principles) and waste (raw page markdown, repeated memory lines). The crisis text is not edited. **Nothing merges until the user approves the side-by-side check in Step 12.**

**Files:**
- Modify: `backend/services/chat_prompt_service.py` (large rewrite), `backend/services/chat_modes_service.py`, `backend/prompts/instruction_packs/core_learning_pack.py`, `backend/services/layman_mode_service.py`, `backend/services/vector_memory_service.py:155-170`
- Create: `tests/test_chat_prompt_v2.py`, `scripts/ab_prompt_check.py`
- Modify: `tests/test_feed_context_note.py`, `tests/test_feed_action_routing.py`, `tests/test_crisis_support.py`, `tests/test_layman_mode_service.py`, `tests/test_phase2_regression.py`, `tests/test_chat.py`, `tests/test_memory_injection.py`, `tests/test_continuity.py`, `tests/test_adaptive_explanation.py`

**Interfaces:**
- Produces: `chat_prompt_service.build_response_principles(simple_tone) -> str`, `build_system_prompt(context, simple_tone=False) -> str`, `build_messages(history, user_message, context, simple_tone=False, attachments=None)`, `MAX_HISTORY_TURNS = 8`; `chat_modes_service.build_feed_context_note(feed_context) -> str`, `format_reasoning_search_note(reasoning) -> str`.
- Consumes: `crisis_support_service.build_crisis_support_section(client_timezone)` (unchanged), `layman_mode_service.build_layman_directive(domain, topic_hint, known_concepts)`.

- [ ] **Step 1: Write the failing prompt tests**

Create `tests/test_chat_prompt_v2.py`:

```python
"""One prompt builder for every chat turn.

The old split (natural vs a mandatory-JSON "structured" prompt for Feed-linked
turns) is gone: the JSON card format had zero real uses since 2026-08-01, and
the split is what let a Feed turn carry both _GUIDELINES ("use bullet points")
and RESPONSE PRINCIPLES ("decide the shape yourself") in the same prompt.

The size ceilings below are the spec's, measured on real logged prompts:
Explain Simply 14.3K -> 8.0K, Ask About 10.6K -> 7.5K, web search 13.4K ->
7.0K, plain chat 9.1K -> 6.5K characters."""
from __future__ import annotations

import pytest

from backend.services.chat_modes_service import build_feed_context_note, format_reasoning_search_note
from backend.services.chat_prompt_service import (
    MAX_HISTORY_TURNS, build_messages, build_response_principles, build_system_prompt,
)

CRISIS_MARKER = "CRISIS AND DISTRESS SUPPORT — ALWAYS IN FORCE:"
JSON_MARKER = "You MUST respond with ONLY a valid JSON object"

MECHANISM = ("Climate shocks act as a hidden variable that shrinks the budget for state-level "
             "maintenance, forcing a move from redundant systems to single points of failure.")

CARD = {
    "action": "explain_simply",
    "insight_title": "The Hidden Climate-Dependency Nobody Prices In",
    "insight_summary": ("When we analyse the long decline of states like the Byzantine Empire, "
                        "climate-induced supply shocks act as a force multiplier for existing "
                        "systemic inefficiencies rather than as a separate cause."),
    "why_it_matters": MECHANISM,
    "mechanism": MECHANISM,
    "blocks": [{"type": "evidence", "content": "B1-CORE-4 shows Byzantine growth tracked climate "
                                               "variability, with agricultural dips matching "
                                               "periods of military and administrative fragility."},
               {"type": "mechanism", "content": MECHANISM},
               {"type": "implication", "content": "If modern supply chains mirror this, today's "
                                                  "lean operations are building the same fragility."}],
    "source_urls": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC9362599/"],
    "source_links": [{"title": "Byzantine Economic Growth and Climate", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9362599/"}],
    "project_name": "B2B Regression Byzantine Empire",
    "progression_stage": "foundation",
    "recent_mechanisms": ["The 1453 collapse that set the rules for imperial resilience",
                          "Why Byzantine machine learning is about trust, not accuracy"],
}

CONTEXT = {
    "user_name": "Dev",
    "conversation_memory": {"message_count": 6, "session_turns": 3,
                            "topics_discussed": ["Byzantine supply chains", "reasoning models"],
                            "last_user_messages": ["What changed in 1453?"]},
    "vector_memory": ("Related past discussion (different session, same user):\n"
                      "  • [Forecasting] Why reasoning models replaced linear regressions"),
    "user_profile": {"learning_stage": "early", "top_interests": ["AI", "history"]},
    "current_message": "Explain this simply.",
}


def _prompt_size(*parts: str) -> int:
    return len("\n".join(p for p in parts if p))


class TestPersonaAndPrinciples:
    def test_one_persona_with_the_user_name(self):
        prompt = build_system_prompt(CONTEXT)
        assert prompt.count("You are Curivio") == 1
        assert "The user's name is Dev." in prompt

    def test_principles_are_present_once(self):
        assert build_system_prompt(CONTEXT).count("RESPONSE PRINCIPLES:") == 1

    def test_simple_tone_variant_drops_the_two_conflicting_rules(self):
        full, simple = build_response_principles(False), build_response_principles(True)
        assert "Decide length and depth" in full and "Decide length and depth" not in simple
        assert "Decide the shape" in full and "Decide the shape" not in simple

    @pytest.mark.parametrize("fragment", [
        "Lead with the actual answer", "Explain WHY, not just WHAT",
        "never invent a source", "change your approach", "Continuity",
    ])
    def test_simple_tone_variant_keeps_every_other_rule(self, fragment):
        assert fragment in build_response_principles(True)

    def test_the_tension_rule_survived_as_a_principle(self):
        assert "open tension" in build_response_principles(False)


class TestSimpleTone:
    def test_directive_only_when_asked_for(self):
        assert "MECHANISM-PRESERVING SIMPLIFICATION" not in build_system_prompt(CONTEXT)
        assert "MECHANISM-PRESERVING SIMPLIFICATION" in build_system_prompt(CONTEXT, simple_tone=True)

    def test_the_five_step_structure_survives(self):
        prompt = build_system_prompt(CONTEXT, simple_tone=True)
        for step in ("THE CORE IDEA", "THE ANALOGY", "THE MECHANISM", "WHY IT EXISTS", "THE INSIGHT"):
            assert step in prompt

    def test_only_one_self_check_remains(self):
        prompt = build_system_prompt(CONTEXT, simple_tone=True)
        assert "ANALOGY QUALITY TEST" not in prompt
        assert "ABSTRACTION SELF-CHECK" not in prompt
        assert "STRATEGIC MEANING TEST" not in prompt
        assert "Check once before finalising" in prompt


class TestCrisisSection:
    def test_absent_when_not_flagged(self):
        assert CRISIS_MARKER not in build_system_prompt(CONTEXT)

    @pytest.mark.parametrize("simple_tone", [False, True])
    def test_present_when_flagged_in_either_tone(self, simple_tone):
        prompt = build_system_prompt({**CONTEXT, "crisis_active": True}, simple_tone=simple_tone)
        assert CRISIS_MARKER in prompt

    def test_it_is_the_last_block(self):
        prompt = build_system_prompt({**CONTEXT, "crisis_active": True})
        assert prompt.index(CRISIS_MARKER) > prompt.index("RESPONSE PRINCIPLES:")
        assert prompt.rstrip().endswith("Help doesn't wait for an answer.")

    def test_locale_still_reaches_it(self):
        prompt = build_system_prompt({**CONTEXT, "crisis_active": True, "client_timezone": "Asia/Kolkata"})
        assert "findahelpline.com/countries/in" in prompt


class TestNoJsonPath:
    @pytest.mark.parametrize("extra", [{}, {"feed_linked": True}, {"response_depth": "research"}])
    def test_no_json_schema_is_ever_emitted(self, extra):
        assert JSON_MARKER not in build_system_prompt({**CONTEXT, **extra})

    def test_attachment_awareness_only_when_something_is_attached(self):
        assert "ATTACHMENT AWARENESS" not in build_system_prompt(CONTEXT)
        assert "ATTACHMENT AWARENESS" in build_system_prompt({**CONTEXT, "has_attachment": True})


class TestFeedNote:
    def test_the_card_mechanism_appears_once(self):
        note = build_feed_context_note(CARD)
        system = build_system_prompt(CONTEXT, simple_tone=True)
        assert (note + system).count(MECHANISM) == 1

    def test_explain_simply_no_longer_forbids_search(self):
        note = build_feed_context_note(CARD)
        assert "Do NOT search the web" not in note
        assert "web_search" not in note

    def test_ask_about_keeps_the_feed_specific_instruction_only(self):
        note = build_feed_context_note({**CARD, "action": "ask_about"})
        assert note.startswith("[FEED INSIGHT — Discussion]")
        assert "Answer THEIR question" in note
        assert "RESPONSE PRINCIPLES" not in note, "the principles are in the system prompt already"

    def test_extracted_text_is_cleaned(self):
        messy = ("![logo](/front/assets/logo.svg)\n"
                 "Get trending papers in your email inbox!\n"
                 "Get trending papers in your email inbox!\n"
                 "[Sign in](/login)\n"
                 "### [Infinite Worlds with Versatile Interactions](/papers/2607.07534)\n"
                 "An advanced world modelling system with extended interaction capabilities.\n"
                 "![avatar](https://cdn.example.com/a.png)\n")
        note = build_feed_context_note({**CARD, "source_contents": {CARD["source_urls"][0]: messy}})
        assert "![" not in note and "/front/assets/logo.svg" not in note
        assert note.count("Get trending papers in your email inbox!") == 1
        assert "Infinite Worlds with Versatile Interactions" in note, "a real title is not noise"
        assert "(/login)" not in note


class TestSearchNote:
    def _note(self, complicating):
        return format_reasoning_search_note({
            "primary_query": "byzantine climate collapse",
            "contradiction_query": "byzantine climate collapse criticism",
            "supporting": [{"title": "A", "content": "Supporting body text.", "url": "https://a"}],
            "complicating": complicating,
            "has_complicating": bool(complicating),
        })

    def test_citation_rules_survive(self):
        note = self._note([])
        assert "[1]" in note and "https://a" in note
        assert "Cite" in note

    def test_the_four_step_ritual_is_gone(self):
        note = self._note([])
        assert "PRIOR POSITION" not in note and "EVIDENCE CHECK" not in note

    def test_the_complicates_section_is_only_asked_for_when_sources_conflict(self):
        assert "What the data complicates" not in self._note([])
        assert "What the data complicates" in self._note(
            [{"title": "B", "content": "Contradicting body.", "url": "https://b"}])


class TestSizeCeilings:
    """The spec's ceilings, measured the way a turn actually assembles: system
    prompt plus the notes injected before the last user message."""

    TITLE_NOTE = ("This is the first message in this conversation. Begin your response with "
                  "exactly one line in this format:\n[TITLE: <4–6 word topic title>]\nThen write "
                  "your complete answer starting on the next line.")

    def test_plain_chat_under_6500(self):
        assert _prompt_size(build_system_prompt(CONTEXT)) <= 6500

    def test_feed_ask_about_under_7500(self):
        size = _prompt_size(build_system_prompt(CONTEXT),
                            build_feed_context_note({**CARD, "action": "ask_about"}),
                            self.TITLE_NOTE)
        assert size <= 7500, size

    def test_feed_explain_simply_under_8000(self):
        size = _prompt_size(build_system_prompt(CONTEXT, simple_tone=True),
                            build_feed_context_note(CARD), self.TITLE_NOTE)
        assert size <= 8000, size

    def test_web_search_turn_under_7000(self):
        note = format_reasoning_search_note({
            "primary_query": "q", "contradiction_query": "q criticism",
            "supporting": [{"title": f"Source {i}", "content": "A short result snippet of the kind "
                                                               "TinyFish returns for a news query.",
                            "url": f"https://example.com/{i}"} for i in range(5)],
            "complicating": [{"title": f"Complication {i}", "content": "A snippet that complicates "
                                                                      "the mainstream reading.",
                              "url": f"https://example.org/{i}"} for i in range(4)],
            "has_complicating": True,
        })
        assert _prompt_size(build_system_prompt(CONTEXT), note, self.TITLE_NOTE) <= 7000


class TestBuildMessages:
    def test_system_first_user_last(self):
        messages = build_messages([], "Hello there", CONTEXT)
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": "Hello there"}

    def test_history_is_truncated(self):
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
                   for i in range(40)]
        messages = build_messages(history, "new", CONTEXT)
        assert len(messages) == 1 + MAX_HISTORY_TURNS * 2 + 1

    def test_attachments_become_content_parts(self):
        messages = build_messages([], "what is this?", CONTEXT,
                                  attachments=[{"uri": "gs://x", "mime_type": "image/png"}])
        assert messages[-1]["content"][0] == {"type": "text", "text": "what is this?"}
        assert messages[-1]["content"][1]["file_uri"] == "gs://x"

    def test_simple_tone_flows_into_the_system_prompt(self):
        messages = build_messages([], "eli5", CONTEXT, simple_tone=True)
        assert "MECHANISM-PRESERVING SIMPLIFICATION" in messages[0]["content"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chat_prompt_v2.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_response_principles'`.

- [ ] **Step 3: Rewrite `backend/services/chat_prompt_service.py`**

The file keeps five helpers verbatim and loses everything the JSON path fed. New file:

```python
"""The chat system prompt — one builder for every turn.

There used to be two: a "natural" prompt and a Feed-linked "structured" one
that forced a JSON card schema. The JSON format had zero real uses since
2026-08-01, and the split let one prompt carry both _GUIDELINES ("use bullet
points") and RESPONSE PRINCIPLES ("decide the shape yourself") — a real logged
Feed turn carried both against a 6-token question and the model resolved the
contradiction by doing neither. One builder, one set of rules.

Order (static text first, so a provider can cache the prefix):
  1. Persona (with the user's name when known)
  2. Response principles — one copy; the simple-tone variant is the same list
     minus the two rules that contradict a mandated structure
  3. Simple-tone directive — only when the turn answers in that tone
  4. Memory, profile, Feed anchor, attachment awareness — only when present
  5. Crisis support — only when flagged, and always last, because it is the one
     block allowed to override everything above it

Public API
----------
build_response_principles(simple_tone) -> str
build_system_prompt(context, simple_tone=False) -> str
build_messages(history, user_message, context, simple_tone=False, attachments=None) -> list[dict]
MAX_HISTORY_TURNS
"""

from __future__ import annotations

from ..prompts.prompt_composer import PromptComposer
# Imported at module scope on purpose: a swallowed ImportError here would
# silently strip crisis support out of every prompt.
from .crisis_support_service import build_crisis_support_section

# Real data (665 turns): an average turn pair is ~439 tokens and a p95 assistant
# reply ~1200. The smallest prompt budget in the pool is ~16-17.5K tokens, so
# ~10K left for history is ~8 turns without risking the weakest leg.
MAX_HISTORY_TURNS = 8

_PERSONA = """\
You are Curivio — an intelligent research and learning companion.
Help the user understand ideas, explore topics, and think more clearly.
Be direct, thoughtful, and conversational. Match your depth to what the user needs.

You're a learning companion this person comes back to, not a one-off chatbot — lean on
what you know about how they think and what they've explored before, the way someone
who's worked with them for a while would. When you know their name, use it where it
feels human — greeting them by name when a conversation opens, or in a genuinely warm
or personal moment — not stapled onto the start of every reply."""

# One list, two renderings. `keep_when_simple=False` marks the two rules that
# structurally contradict the simple-tone directive's mandated 5-step shape
# ("decide the length yourself", "decide the shape yourself") — the old code
# kept a second 2,495-char copy of the whole block just to drop those two.
# Every other rule applies in both tones, so it exists once.
_PRINCIPLES: tuple[tuple[bool, str], ...] = (
    (True, 'Lead with the actual answer — not a definition, not throat-clearing, not "great question." '
           "Don't open by naming yourself."),
    (False, 'Decide length and depth from what this question needs. A quick factual question gets a few '
            'sentences; a real "explain this" gets the full teach-through, reasoned FROM any real material '
            'in front of you (prior discussion, a document, extracted source text) rather than staying '
            'generic. Depth means more real content — a named example, a concrete number, one more step of '
            'mechanism, a tension between sources — never longer sentences about the same thing, and never '
            'a restatement of what the user already has.'),
    (True, "Explain WHY, not just WHAT. Name specifics and surface the non-obvious — the company, the "
           "event, the mechanism, the second-order effect — rather than restating what they likely "
           "already know."),
    (False, "Decide the shape the same way: a genuine comparison can be a table, a process numbered, a set "
            "of options bulleted, a short answer plain prose. When an answer is long enough to need "
            "structure, open with the sentence that answers the question and give list-like material "
            "bullets with bolded lead-ins. A wall of undifferentiated paragraphs is the common failure; "
            "bulleting what is really one idea is the opposite one."),
    (True, "End on the open tension — the second-order effect, the thing that breaks, the reason a "
           "practitioner would care — never on a summary of what you just said."),
    (True, "Write code when it is genuinely the clearest answer, whatever the subject, and never tack it "
           "on as a bonus. Always fence it with a language tag (unfenced Python loses its indentation). "
           "Give it a sentence or two of framing unless the user asked for code only or it is one "
           "self-explanatory line."),
    (True, 'Say plainly what you are sure of. When you are inferring or working from memory, say so ("as '
           'far as I know", "I\'d want to check this"), and never invent a source or citation.'),
    (True, "If the user says your last answer missed the mark, change your approach — don't apologise and "
           "repeat it with more words."),
    (True, "Continuity: build on what this conversation already covered instead of re-explaining it. When "
           "a short or fragmentary message could plausibly extend the current thread, answer it as part of "
           "that thread; treat it as standalone only when the wording clearly changes the subject."),
)

_ATTACHMENT_AWARENESS = """\
<<COPY VERBATIM from the pre-task backend/services/chat_prompt_service.py, lines 596-604>>"""


def build_response_principles(simple_tone: bool = False) -> str:
    """The principles block. Simple tone drops the two rules that contradict the
    directive's mandated structure and keeps every other one, unreworded."""
    lines = [f"- {text}" for keep_when_simple, text in _PRINCIPLES
             if keep_when_simple or not simple_tone]
    return "RESPONSE PRINCIPLES:\n" + "\n".join(lines)


def _build_persona_section(user_name: str = "") -> str:
    if user_name:
        return f"{_PERSONA}\n\nThe user's name is {user_name}."
    return _PERSONA


def _build_simple_tone_section(context: dict) -> str:
    """The mechanism-preserving simplification directive, with a domain-tailored
    analogy bank. The card's own mechanism sentence is NOT repeated here — it is
    already in the Feed note, and it used to appear up to four times per prompt."""
    from .layman_mode_service import build_layman_directive
    return build_layman_directive(
        domain=context.get("domain_context", {}).get("domain", ""),
        topic_hint=context.get("research", {}).get("topic") or None,
    )


def build_system_prompt(context: dict, simple_tone: bool = False) -> str:
    composer = PromptComposer()
    composer.add_section("persona", _build_persona_section(context.get("user_name", "")),
                         priority=1, required=True, source_pack="")
    composer.add_section("response_principles", build_response_principles(simple_tone),
                         priority=1, required=True, source_pack="")

    if simple_tone:
        composer.add_section("simple_tone", _build_simple_tone_section(context),
                             priority=2, required=False, source_pack="core_learning_pack")
        # Phase 4.6: concept anchors so a simplification can bridge from what
        # this user already learned in this project.
        shared = context.get("shared_learning_context", "")
        if shared and "ANALOGY ANCHORS" in shared:
            composer.add_section("simple_tone_anchors", shared,
                                 priority=2, required=False, source_pack="dynamic")

    # Continuity context — aggregated across the session, so genuinely additive
    # to the last-N-turns array build_messages sends alongside this prompt.
    composer.add_section("conversation_memory", _build_conversation_memory_section(
        context.get("conversation_memory", {}), include_recency=False),
        priority=2, required=False, source_pack="dynamic")
    composer.add_section("knowledge_state", _build_knowledge_state_section(
        context.get("conversation_knowledge", {})),
        priority=2, required=False, source_pack="dynamic")
    composer.add_section("vector_memory", context.get("vector_memory", ""),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("feed_entry_anchor", context.get("feed_entry_anchor", ""),
                         priority=2, required=False, source_pack="dynamic")
    composer.add_section("user_profile", _build_compact_profile(context),
                         priority=3, required=False, source_pack="dynamic")

    if context.get("has_attachment"):
        composer.add_section("attachment_awareness", _ATTACHMENT_AWARENESS,
                             priority=3, required=True, source_pack="")

    # Gated on the classifier's crisis field with a code-level fail-safe and a
    # few-turn carry-forward (chat_service). Deliberately last: it is the one
    # block allowed to override what precedes it — specifically the principle
    # that pushback means "change your approach", which is what turned a real
    # crisis follow-up into an apology and a retraction.
    if context.get("crisis_active"):
        composer.add_section("crisis_support",
                             build_crisis_support_section(context.get("client_timezone")),
                             priority=1, required=True, source_pack="")
    return composer.build()


def build_messages(history: list[dict], user_message: str, context: dict,
                   simple_tone: bool = False, attachments: list[dict] | None = None) -> list[dict]:
    """System prompt + the last MAX_HISTORY_TURNS turns + this message.

    `attachments` (images only): the final user message becomes a list of parts
    (text + Gemini "media" file_uri parts), the real SDK content-block format.
    """
    messages = [{"role": "system", "content": build_system_prompt(context, simple_tone=simple_tone)}]
    max_messages = MAX_HISTORY_TURNS * 2
    messages.extend(history[-max_messages:] if len(history) > max_messages else history)

    if attachments:
        parts = [{"type": "text", "text": user_message}] if user_message else []
        parts += [{"type": "media", "file_uri": a["uri"], "mime_type": a["mime_type"]}
                  for a in attachments]
        messages.append({"role": "user", "content": parts})
    else:
        messages.append({"role": "user", "content": user_message})
    return messages


def resolve_user_level(context: dict) -> str:
    <<COPY VERBATIM from the pre-task backend/services/chat_prompt_service.py, lines 719-740>>


def _build_compact_profile(context: dict) -> str:
    <<COPY VERBATIM from the pre-task backend/services/chat_prompt_service.py, lines 743-757>>


def _build_conversation_memory_section(conv: dict, include_recency: bool = True) -> str:
    <<COPY VERBATIM from the pre-task backend/services/chat_prompt_service.py, lines 822-860>>


def _build_knowledge_state_section(knowledge: dict) -> str:
    <<COPY VERBATIM from the pre-task backend/services/chat_prompt_service.py, lines 1008-1022>>
```

Everything else in the old file goes: `detect_depth` and its trigger tables, `_FORMAT_DIRECTIVES`, `_build_format_directive_section`, `_build_natural_prompt`, `_build_structured_prompt`, `_PERSONA` (the structured one), `_RESPONSE_PRINCIPLES`, `_RESPONSE_PRINCIPLES_LAYMAN`, `_GUIDELINES`, `_STRUCTURED_FORMAT_DIRECTIVE`, `_build_profile_section`, `_build_research_section`, `_build_session_section`, `_build_exploration_breadth_section`, `_build_preference_snapshot_section`, `_build_explanation_directive_section`, `_build_action_result_section`, `_build_domain_directive_section`, `_build_learning_system_section`, `_build_layman_mode_section`, `_build_tension_section`, `_build_continuity_section`, and the `LAYMAN_SIMPLIFICATION_SIMPLE` import.

- [ ] **Step 4: Trim the simple-tone directive**

`backend/prompts/instruction_packs/core_learning_pack.py` — replace `LAYMAN_SIMPLIFICATION_DIRECTIVE` (and the `.replace()` chain under it) with the version below: same rule, same 5 steps, same BAD/GOOD example, three overlapping self-checks merged into one. ~3,400 rendered chars -> ~1,800.

```python
LAYMAN_SIMPLIFICATION_DIRECTIVE: str = """\
ACTIVE RESPONSE MODE — MECHANISM-PRESERVING SIMPLIFICATION:
Simplify vocabulary, abstraction and jargon. NEVER simplify the underlying mechanism. The user is smart but new to this domain: give them the full idea in words they already know.

Simplify: jargon into plain English (define an unavoidable term inline, in parentheses); abbreviations into full names on first use; abstract structure into concrete analogies.
Never simplify: causal logic (WHY A caused B), incentives (WHY actors chose what they chose), the strategic insight, or the hidden mechanism behind a surprising result.

BAD:  "FDA helps exports because countries trust approved medicines."
GOOD: "FDA approval works like a global trust certificate — buyers assume a company that passed strict inspections is less likely to fail them, and that assumption is worth more than a marketing budget because scrutiny earned it, money didn't."

Structure your response in this sequence:
1. THE CORE IDEA — one plain sentence: what is this, in the simplest honest terms?
2. THE ANALOGY — carry the mechanism, not just the shape, then bridge back: "In the same way, [concept] works by [mechanism]…"
3. THE MECHANISM — every step of the causal chain, in plain language.
4. WHY IT EXISTS — what was broken or missing before it?
5. THE INSIGHT — the one non-obvious thing that would surprise someone who just learned the basics. Never skip it.

{{ANALOGY_BANK}}

Check once before finalising: every sentence reads without stopping; the analogy explains the mechanism — who benefits, who pays, and why — rather than just resembling it; the causal logic and the insight survived the simplification.

Tone: speak like a brilliant friend explaining over coffee — direct, warm, not condescending. Never open with a definition."""
```

`LAYMAN_SIMPLIFICATION_SIMPLE` and the standalone `ANALOGY_QUALITY_TEST` / `ABSTRACTION_SELF_CHECK` / `STRATEGIC_MEANING_TEST` / `MECHANISM_PRESERVATION_RULE` / `VOCABULARY_MECHANISM_SPLIT` constants lose their last reader here — leave them in place for now and list them in the Task 7 deletion sweep (they are a shared instruction pack, so check `grep -rn` there rather than assuming).

`backend/services/layman_mode_service.py` — `_format_bank` keeps the seed and the topic anchor and drops the "Draw from" list and the "Mechanism caution" line (the merged self-check above covers the caution, and the seed already names a domain):

```python
def _format_bank(bank: dict, topic_hint: str | None) -> str:
    lines = ["ANALOGY DOMAIN BANK:", f"- Seed example: {bank.get('seed', '')}"]
    if topic_hint:
        lines.append(
            f'- Anchor the analogy to the specific topic: "{topic_hint}" — '
            "a specific analogy sticks far better than a general one.")
    return "\n".join(lines)
```

`tests/test_layman_mode_service.py::TestAnalogyBankSelection` keeps working (it asserts seed text and the anchor line), except `test_unclassified_domain_falls_back_to_default_bank` / `test_empty_domain_falls_back_to_default_bank`, which assert the default bank's seed — that string still ships, so they pass unchanged.

- [ ] **Step 5: De-duplicate the memory recall lines**

`backend/services/vector_memory_service.py:155-170` — real prompts carried the same entry twice:

```python
def format_for_prompt(entries: list[dict], max_items: int = 3) -> str:
    """Format search() results into a compact, clearly-labeled prompt section.
    Identical lines are dropped: the same entry can come back from two different
    sessions, and paying for it twice in the prompt buys nothing."""
    if not entries:
        return ""
    lines = ["Related past discussion (different session, same user):"]
    seen: set[str] = set()
    for entry in entries:
        topic, text = entry.get("topic") or "", entry.get("entry_text") or ""
        line = f"  • [{topic}] {text}" if topic else f"  • {text}"
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(seen) >= max_items:
            break
    return "\n".join(lines) if len(lines) > 1 else ""
```

- [ ] **Step 6: Rewrite the Feed note and the search note**

`backend/services/chat_modes_service.py`. Replace `_ASK_ABOUT_INSTRUCTION` (lines 34-63, 1,753 chars of which about half restates the principles) with the Feed-specific part only:

```python
_ASK_ABOUT_INSTRUCTION = (
    "The user opened this card from their feed and asked the question below. Answer THEIR "
    "question: the card is grounding, not the subject, so don't summarise it unless that is what "
    'they asked. A narrow question gets a narrow, exact answer; an open one ("explain this") gets '
    "the full teach-through. The blocks above are compressed notes — use their specifics (the "
    "named company, the mechanism, the number, the failure mode) instead of restating the summary "
    "in more general words."
)
```

Add the extracted-text cleaner (imports: `re`):

```python
_MD_IMAGE_RE     = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_ONLY_RE = re.compile(r"^\s*[-*]?\s*\[[^\]]*\]\([^)]*\)\s*$")
_MD_LINK_RE      = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BARE_URL_RE     = re.compile(r"^\s*https?://\S+\s*$")


def _clean_extracted_text(text: str) -> str:
    """Page markdown as retrieved is mostly furniture. A real sample: 1.9K chars
    whose first 700 were a logo, a newsletter prompt repeated twice, and avatar
    images. Images and link-only nav lines go; a heading's link TEXT stays
    (that is usually the article title); repeated lines are kept once."""
    kept: list[str] = []
    seen: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = _MD_IMAGE_RE.sub("", raw_line).rstrip()
        if not line.strip() or _MD_LINK_ONLY_RE.match(line) or _BARE_URL_RE.match(line):
            continue
        line = _MD_LINK_RE.sub(r"\1", line).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        kept.append(line)
    return "\n".join(kept)
```

In `build_feed_context_note`:
- drop `"continue_research": "Extended Research"` from `_ACTION_LABELS` and delete the whole `else:  # continue_research` branch (lines 203-217) — there is no button for it and no mode left to map it to;
- render source bodies through the cleaner: `body = _clean_extracted_text(contents.get(url) or "")`;
- skip a content block that just repeats the summary or the "Why it matters" line — real cards carry
  the mechanism in both, which is two of the up-to-four copies this task removes:

```python
    if blocks:
        already_said = {(summary or "").strip(), (why or "").strip()}
        block_lines = [f"  [{b.get('type', 'content')}] {b.get('content', '')}"
                       for b in blocks
                       if isinstance(b, dict) and b.get("content")
                       and b["content"].strip() not in already_said]
        if block_lines:
            parts.append("Card content blocks:")
            parts.extend(block_lines)
```
- replace the sources footnote with `f"({len(contents)} of {len(sources)} sources include their extracted text above — quote and reason from that text, not from the card summary.)"` (the old one told the model to `web_search` the missing ones, and there is no such tool now);
- replace the `explain_simply` branch (lines 187-202) with one instruction that points at the mechanism instead of repeating it:

```python
    elif action == "explain_simply":
        # The mechanism sentence itself is already above (it IS the card's "Why
        # it matters" line, or the first line of its summary). It used to be
        # pasted again here AND again in the system prompt — up to four copies
        # of the same sentence in one prompt.
        anchor = "the “Why it matters” line" if why else "the summary above"
        parts.append(
            "The user wants this card explained in the simplest, most intuitive terms. Keep its "
            f"core mechanism — {anchor} — intact: simplify the vocabulary, not the logic."
        )
```

Replace `format_reasoning_search_note` (lines 250-349) with:

```python
def format_reasoning_search_note(reasoning: dict) -> str:
    """The system note that carries search results into the turn.

    Was ~2K chars of instruction: a four-step internal ritual (PRIOR POSITION /
    EVIDENCE CHECK / POSITION UPDATE / OPEN QUESTIONS), a MANDATORY "What the
    data complicates" section on every search turn whether or not anything
    conflicted, and rules the system prompt already carries. What stays is what
    the citations and the frontend depend on: one contiguous 1..N numbering
    across both result sets (so [N] resolves to sources[N-1]) and the rules
    specific to reading search results.
    """
    supporting   = reasoning.get("supporting", [])
    complicating = reasoning.get("complicating", [])
    queries = [q for q in (reasoning.get("primary_query"), reasoning.get("contradiction_query")) if q]

    lines = ["[WEB SEARCH RESULTS]"]
    if queries:
        lines.append("Searched: " + " · ".join(f'"{q[:120]}"' for q in queries))

    for index, article in enumerate(supporting + complicating, 1):
        marker  = " ⚑" if index > len(supporting) else ""
        title   = (article.get("title") or "").strip()
        content = (article.get("content") or "").strip()
        lines.append(f"\n  [{index}]{marker} {title}\n      {content}\n      Source: {article.get('url', '')}")

    lines.append(
        "\nHow to use these results:"
        "\n- Open with the substantive finding, not with what was searched. Draw patterns across "
        "sources rather than summarising them one by one."
        '\n- Cite claims with the bracketed source number, e.g. "the market grew 5% [1]"; stack '
        'numbers when several sources support a claim ("[1][3]"). Cite only what that source '
        "genuinely supports, and leave your own synthesis uncited."
    )
    if complicating:
        lines.append(
            "- Results marked ⚑ came from a deliberately contradicting search. Where they genuinely "
            "conflict with the rest, say what each claims and what the conflict means for the "
            'conclusion, under a short "What the data complicates" heading.'
        )
    else:
        lines.append("- If two sources contradict each other, surface the disagreement explicitly.")
    return "\n".join(lines)
```

- [ ] **Step 7: Run the new prompt tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_chat_prompt_v2.py -v`
Expected: PASS. If a size ceiling fails, the failure message prints the real size — trim the block that grew, never the ceiling.

- [ ] **Step 8: Update the suites that tested the deleted prompt paths**

- `tests/test_feed_context_note.py`: the note no longer mentions web search at all. Replace the last three assertions with `assert "web search" not in note.lower()`; keep the card-content assertions.
- `tests/test_feed_action_routing.py`: keep `TestInteractionTypePersistence` untouched. Replace `TestLaymanEscapesTheStructuredPrompt` with two tests: `build_system_prompt(ctx, simple_tone=True)` contains `MECHANISM-PRESERVING SIMPLIFICATION` and no JSON marker, and `build_system_prompt(ctx)` (Feed-linked, not simple) also has no JSON marker. In `TestFeedContextNote`, replace the `"Do NOT search the web" in note` assertion with `assert "Keep its core mechanism" in note`.
- `tests/test_crisis_support.py`: rename `TestSectionIsUnconditional` to `TestSectionIsGatedOnTheClassifier` and change its body: the marker is present when `{"crisis_active": True}` and absent otherwise, in both tones. Keep the locale tests (add `crisis_active: True` to their contexts), keep `test_chat_stream_threads_client_timezone_into_context`, keep the whole `@pytest.mark.integration` class unchanged. The parametrised "present regardless of what the user said" tests become one test asserting the section is present for any message **when the classifier flagged it**, which is what the fail-safe now guarantees.
- `tests/test_phase2_regression.py`: delete `TestCompareMode`, `TestTrendAnalysis`, `TestDetectDepth` and `TestTokenEfficiency::test_chat_structured_within_reasonable_budget` (all test removed code paths). Update the remaining `build_system_prompt(ctx, mode=...)` calls to `build_system_prompt(ctx)` / `build_system_prompt(ctx, simple_tone=True)`.
- `tests/test_chat.py`: in `TestChatPromptService`, delete `test_build_system_prompt_includes_research_summary` and `test_build_system_prompt_includes_session_memory` (research/session dumps are gone), and update the remaining calls to the new signature.
- `tests/test_memory_injection.py`: delete the `_build_exploration_breadth_section` and `_build_preference_snapshot_section` imports and their two test classes; keep the conversation-memory ones and update `test_full_prompt_includes_conv_section` to the new signature.
- `tests/test_adaptive_explanation.py`: delete the `_build_explanation_directive_section` import, its four tests, and the three `build_system_prompt` directive tests. Everything testing `adaptive_explanation_service` itself stays.
- `tests/test_continuity.py`: delete `TestContinuityPromptSection` and `TestContinuityInSystemPrompt`.

- [ ] **Step 9: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20`
Expected: baseline failures only (minus the ones deleted above).

- [ ] **Step 10: Write the side-by-side check script**

Create `scripts/ab_prompt_check.py`:

```python
"""Side-by-side prompt check: does the trimmed prompt answer at least as well?

Takes real logged turns, rebuilds each one's prompt with the NEW builder, and
answers both the old and the new prompt with the same free model. Output is one
markdown file to read.

What is compared: persona, principles, directives, the Feed note, the search
note and the format rules — everything this refactor touched. The dynamic
memory blocks are copied from the old prompt into the new one verbatim, so the
two differ only by the parts that changed.

Cost: $0 (Groq free tier). No writes: it reads llm_call_log and never calls
chat_service.

    python scripts/ab_prompt_check.py --limit 12 --out docs/superpowers/plans/ab-prompt-check.md
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_ROLE_RE = re.compile(r"(?m)^(system|human|ai|tool): ")
_SOURCE_RE = re.compile(r"^\s+\[(\d+)\]\s*⚑?\s*(.*?)\n\s+(.*?)\n\s+Source: (\S+)", re.M)
_MEMORY_HEADS = ("This conversation:", "Related past discussion", "What you know about this user:")


def _messages_from_log(text: str) -> list[dict]:
    parts = _ROLE_RE.split(text)
    roles = {"human": "user", "ai": "assistant"}
    return [{"role": roles.get(role, role), "content": body.strip("\n")}
            for role, body in zip(parts[1::2], parts[2::2])]


def _card_from_note(note: str) -> dict:
    """Rebuild the feed_context dict from the old [FEED INSIGHT ...] note."""
    def _field(label):
        match = re.search(rf"^{label}: (.*)$", note, re.M)
        return match.group(1).strip() if match else ""

    blocks = [{"type": block_type, "content": content}
              for block_type, content in re.findall(r"^  \[(\w+)\] (.*)$", note, re.M)]
    urls, links, contents = [], [], {}
    for line in note.splitlines():
        source = re.match(r"^  • (?:(.*?): )?(https?://\S+)$", line)
        if source:
            title, url = source.group(1) or "", source.group(2)
            urls.append(url)
            links.append({"title": title, "url": url})
    for url, body in re.findall(r"^  • .*?(https?://\S+)\n    Extracted text: (.*?)(?=\n  •|\n\n|\Z)",
                                note, re.M | re.S):
        contents[url] = body
    return {
        "action": "explain_simply" if "Simple Explanation" in note.splitlines()[0] else "ask_about",
        "insight_title": _field("Card"), "insight_summary": _field("Summary"),
        "why_it_matters": _field("Why it matters"),
        "educational_explanation": _field("Educational explanation"),
        "blocks": blocks, "source_urls": urls, "source_links": links,
        "source_contents": contents, "project_name": "", "domain": "default",
    }


def _case_from_messages(messages: list[dict]) -> dict:
    systems = [m["content"] for m in messages if m["role"] == "system"]
    tools = [m["content"] for m in messages if m["role"] == "tool"]
    feed_note = next((s for s in systems if s.startswith("[FEED INSIGHT")), "")
    search_note = next((s for s in systems + tools if "WEB SEARCH" in s[:60]), "")
    memory = "\n\n".join(block for s in systems for block in s.split("\n\n")
                         if block.startswith(_MEMORY_HEADS))
    name = re.search(r"^The user's name is (.*)\.$", systems[0] if systems else "", re.M)
    articles = [{"title": title, "content": content, "url": url}
                for _, title, content, url in _SOURCE_RE.findall(search_note)]
    return {
        "message": next((m["content"] for m in reversed(messages) if m["role"] == "user"), ""),
        "history": [m for m in messages if m["role"] in ("user", "assistant")][:-1],
        "user_name": name.group(1) if name else "",
        "feed_context": _card_from_note(feed_note) if feed_note else None,
        "articles": articles,
        "memory": memory,
        "simple_tone": "MECHANISM-PRESERVING SIMPLIFICATION" in (systems[0] if systems else "")
                       or "ACTIVE RESPONSE MODE" in (systems[0] if systems else ""),
        "old_messages": messages,
    }


def _new_messages(case: dict) -> list[dict]:
    from backend.services.chat_modes_service import build_feed_context_note, format_reasoning_search_note
    from backend.services.chat_prompt_service import build_messages

    context = {"user_name": case["user_name"], "vector_memory": case["memory"]}
    messages = build_messages(case["history"], case["message"], context,
                              simple_tone=case["simple_tone"])
    notes = []
    if case["feed_context"]:
        notes.append(build_feed_context_note(case["feed_context"]))
    if case["articles"]:
        half = len(case["articles"]) // 2 or len(case["articles"])
        notes.append(format_reasoning_search_note({
            "primary_query": "", "contradiction_query": "",
            "supporting": case["articles"][:half], "complicating": case["articles"][half:],
            "has_complicating": len(case["articles"]) > half,
        }))
    for note in notes:
        messages.insert(len(messages) - 1, {"role": "system", "content": note})
    return messages


def _answer(messages: list[dict]) -> str:
    from langchain_groq import ChatGroq
    key = (os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY")).split(",")[0].strip()
    model = ChatGroq(model="openai/gpt-oss-120b", api_key=key, temperature=0.7,
                     max_retries=0, max_tokens=1200)
    payload = [m for m in messages if m["role"] != "tool"]
    return str(model.invoke(payload).content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--db", default=str(REPO / "data" / "curivio.db"))
    parser.add_argument("--out", default=str(REPO / "docs/superpowers/plans/ab-prompt-check.md"))
    args = parser.parse_args()

    rows = sqlite3.connect(args.db).execute(
        "SELECT input FROM llm_call_log WHERE call_type='chat_turn' AND is_test=0 "
        "AND user_id IS NOT NULL AND success=1 AND length(input) > 800 "
        "ORDER BY id DESC LIMIT ?", (args.limit * 3,)).fetchall()

    report = ["# Prompt side-by-side check", "",
              "Old = the prompt exactly as it was sent in that real turn. New = the same turn "
              "rebuilt by the new builder, with the dynamic memory blocks copied across so only "
              "the changed parts differ. Same model for both: groq/openai/gpt-oss-120b.", ""]
    seen: set[str] = set()
    kept = 0
    for (text,) in rows:
        if kept >= args.limit:
            break
        case = _case_from_messages(_messages_from_log(text))
        if not case["message"] or case["message"] in seen:
            continue
        seen.add(case["message"])
        kept += 1

        old_messages, new_messages = case["old_messages"], _new_messages(case)
        old_chars = sum(len(m["content"]) for m in old_messages if m["role"] == "system")
        new_chars = sum(len(m["content"]) for m in new_messages if m["role"] == "system")
        label = ("Feed " + case["feed_context"]["action"] if case["feed_context"]
                 else "web search" if case["articles"] else "simple tone" if case["simple_tone"] else "plain")
        report += [f"## {kept}. {label} — {case['message'][:80]!r}", "",
                   f"System prompt: **{old_chars} -> {new_chars} chars** "
                   f"({(new_chars - old_chars) / max(old_chars, 1):+.0%})", "",
                   "### Old answer", "", _answer(old_messages), "",
                   "### New answer", "", _answer(new_messages), "", "---", ""]
        print(f"[{kept}/{args.limit}] {label}: {old_chars} -> {new_chars}")

    Path(args.out).write_text("\n".join(report), encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
```

- [ ] **Step 11: Run the check**

Run: `.venv/Scripts/python.exe scripts/ab_prompt_check.py --limit 12`
Expected: 12 sections in `docs/superpowers/plans/ab-prompt-check.md`, each showing the size change and both answers. Cost: $0.

- [ ] **Step 12: USER APPROVAL GATE**

Send the user: the per-turn size changes, the four ceilings versus their targets, and the path to the report. Ask them to read it and say whether the new answers are as good or better. **Do not start Task 7 until they say yes.** If they want changes, edit the prompts, re-run Step 11, and ask again.

- [ ] **Step 13: Commit**

```bash
git add backend/services/chat_prompt_service.py backend/services/chat_modes_service.py backend/services/layman_mode_service.py backend/services/vector_memory_service.py backend/prompts/instruction_packs/core_learning_pack.py scripts/ab_prompt_check.py tests/
git commit -m "refactor(chat): one prompt builder, same rules, smaller

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Deletions

Nothing new is built here. Every item below is dead once Tasks 4-6 landed. **Method for each one:** `grep -rn "<symbol>" backend/ scripts/ tests/ frontend/src/` first, remove the callers the grep finds, delete, then run the suite. **Delete only at zero non-test references.** Anything ambiguous goes on the report to the user instead of being deleted.

**Kept on purpose:** `get_chat_model` / `get_structured_chat_model` / `_build_raw_models` and their env models (old Feed callers), `ask_grok` (old Feed), `score_tension` (the done event still scores answers), `_parse_structured_response` and the frontend's `StructuredResponseRenderer` (old saved JSON answers must still render), the `continue_research` value in the DB CHECK constraint and in `feed_chat_link_service._INTERACTION_TYPES` (existing rows), `feed_v2`.

**Files:** see each step.

- [ ] **Step 1: Delete the four dead modules**

```bash
grep -rn "model_priority\|chat_tools\|action_router_service\|learning_system_context_service" backend/ scripts/ tests/ frontend/src/
```

Expected remaining references: `tests/test_model_priority.py`, `tests/test_action_router.py`, the action-router test sections in three service test files, `scripts/smoke_test_model_pool_rotation.py`, and comments in `deep_research_service.py:9`, `industry_intelligence_service.py:233`, `domain_resource_service.py:287`, `chat_modes_service.py` (module docstring), `frontend/src/components/shared/MarkdownText.jsx:38`. Update those comments to name what replaced them (`chat_service`'s code-run search, `chat_router`'s classifier), then:

```bash
git rm backend/llm/model_priority.py backend/llm/chat_tools.py \
       backend/services/action_router_service.py backend/services/learning_system_context_service.py \
       tests/test_model_priority.py tests/test_action_router.py tests/test_chat_router.py \
       scripts/smoke_test_model_pool_rotation.py scripts/smoke_test_chat_router.py \
       scripts/smoke_test_prompt_adaptive_format.py
```

(`tests/test_chat_router.py` tested `map_to_task_type` and the live tool-calling classifier; `tests/test_turn_plan.py` is its replacement. `scripts/smoke_test_prompt_adaptive_format.py` drives the JSON card path and `detect_depth`, both removed — it is in this list even though the spec's table missed it; say so in the task report.)

- [ ] **Step 2: Remove the action-router test sections**

Delete `TestActionRouterIntegration` from `tests/test_research_report_service.py` (lines 548-612), the `_route` helper and its tests in `tests/test_domain_resource_service.py` (the class using `action_router_service.route`), and the three `action_router_service.route` tests in `tests/test_industry_intelligence_service.py`. Everything testing the services themselves stays.

Then check whether those services still have real callers and **report, do not delete**:

```bash
grep -rn "industry_intelligence_service\|research_report_service\|domain_resource_service" backend/ --include=*.py | grep -v "^backend/services/\(industry_intelligence\|research_report\|domain_resource\)_service.py"
```

- [ ] **Step 3: Delete the task-pool helpers from `model_provider.py`**

```bash
grep -rn "build_pooled_legs\|get_chat_model_for_task\|get_structured_chat_model_for_task\|get_structured_chat_model_legs_for_task\|_build_pooled_leg\|_build_structured_legs\|_is_gemini_leg\|_thinking_kwargs" backend/ scripts/ tests/
```

Expected: zero outside `model_provider.py` itself. Delete `_build_pooled_leg`, `build_pooled_legs`, `get_chat_model_for_task`, `_GROQ_BAD_REQUEST_RETRY_ATTEMPTS`, `_build_structured_legs`, `get_structured_chat_model_for_task`, `get_structured_chat_model_legs_for_task`, `_is_gemini_leg`, `_thinking_kwargs`, the `thinking` parameter of `_build_raw_models` (and its `if thinking:` branch — no caller passes it now), the unreachable `return pairs` after `extract_text` (line 270), and the now-unused `GroqBadRequestError` / `TooManyRequestsResponseError` imports.

Keep: `get_chat_model`, `get_structured_chat_model`, `_build_raw_models`, `_with_retry`, `_QuotaAwareRetry`, `extract_text`, `upload_attachment`, `_gemini_keys`, `_groq_keys`, `_groq_key`, `_openrouter_keys`, `_keys_for_provider`, `_is_gemini_3_plus` — the Feed pipeline and the new routing layer both depend on them.

Rewrite the module docstring's "Public API" section to list what is actually there now (the chat-config loader, legs, `run_route`, and the old Feed chain).

- [ ] **Step 4: Delete `grok_service.ask_grok_chat_stream`**

```bash
grep -rn "ask_grok_chat_stream" backend/ scripts/ tests/
```

Expected: only `backend/services/grok_service.py:120` and `tests/test_streaming.py::TestAskGrokChatStream`. Delete the function (lines 120-179) and that whole test class (it patches a `gs.client` attribute that has not existed since the module switched to `_get_client()`, which is why it is in the Task 1 baseline). `ask_grok` stays — the old Feed still calls it.

- [ ] **Step 5: Delete the tension directive**

`backend/services/tension_engine.py` — delete `build_tension_directive` and everything only it used: `_TENSION_DIRECTIVES`, `_DOMAIN_HINTS`, `_OPEN_LOOP_ENDINGS`, `_FRAMING_RULES`, `_OPEN_LOOP_HEADER`, `_INTENT_TENSION_MAP`, `_PRIORITY_ORDER`, `_GREETING_TOKENS`, `_select_tension_types`, `_is_trivial`, `_build_message_hook`, `_build_open_loop_instruction`, `_build_short_version`, `_normalise_domain`. **Keep** `score_tension`, its four regexes and `_zero_scores`: `chat_service` still scores every answer for the done event. Update the module docstring to say the directive moved into one RESPONSE PRINCIPLES line.

```bash
grep -rn "build_tension_directive\|_FRAMING_RULES\|_INTENT_TENSION_MAP" backend/ scripts/ tests/
```

- [ ] **Step 6: Delete the replaced config constants**

`backend/config/app_config.py`: delete `GROQ_FAST_MODEL`, `GEMINI_LITE_MODEL`, `OPENROUTER_NEMOTRON_MODEL` and their comment blocks (lines 47-64). `GROQ_UNPACK_MODEL` / `GEMINI_UNPACK_MODEL` stay until Task 9 deletes them with their last reader. `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GROQ_FALLBACK_MODEL`, `GROQ_MODEL` stay: the old Feed chain and `ask_grok` read them.

```bash
grep -rn "GROQ_FAST_MODEL\|GEMINI_LITE_MODEL\|OPENROUTER_NEMOTRON_MODEL" backend/ scripts/ tests/
```

- [ ] **Step 7: Drop the leftover action-result plumbing in `chat_service`**

In `_extract_concepts_from_context` (line ~1362) delete the `action_result` branch — nothing sets that key any more — keeping the deep-research branch. Delete the matching tests in `tests/test_continuity.py::TestExtractConceptsFromContext` (`test_extracts_from_action_result_data`, `test_extracts_beginner_steps_from_action`, and the action half of `test_deduplicates_case_insensitive`).

- [ ] **Step 8: Delete the frontend action badge**

- `frontend/src/components/chat/ChatMessage.jsx`: delete `ACTION_LABELS` (lines 73-80) and `ActionBadge` (lines 405-414); at line 1353 replace `{!message.streaming && message.action && <ActionBadge action={message.action} />}` with nothing and simplify the wrapper `<div className={!message.streaming && message.action ? "mt-2" : ""}>` to `<div>`.
- `frontend/src/components/chat/ChatWorkspace.jsx`: delete the `action:` field from the three message objects (lines 55, 191, 213) and `action: meta.action ?? null,` (line 376).
- `frontend/src/components/shared/MarkdownText.jsx:38`: update the comment to name `web_search_reasoning_service.run_chat_search` / `format_reasoning_search_note`.

```bash
grep -rn "ActionBadge\|ACTION_LABELS\|message.action\|meta.action" frontend/src/
cd frontend && npm run build
```

Expected: the grep finds nothing (the Feed card's own `INTERACTION_LABELS` in `InsightCard.jsx` is a different thing and stays), and the build passes.

- [ ] **Step 9: Update the document-upload smoke script**

`scripts/smoke_test_document_upload.py:210-227` spies on `has_attachments` / `task_type`, neither of which exists now:

```python
    captured = {}
    orig_ask = chat_agent.ask_chat_stream

    def _spy(*args, **kwargs):
        captured["route"] = kwargs.get("route")
        return orig_ask(*args, **kwargs)

    # the existing `with patch.object(chat_agent, "ask_chat_stream", side_effect=_spy):`
    # block and the turn it runs stay exactly as they are
    assert captured.get("route") == "image", "an image attachment must still route to the image list"
```

- [ ] **Step 10: Run everything**

```bash
.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20
grep -rn "model_priority\|chat_tools\|action_router\|map_to_task_type\|resolve_tools_and_hint\|build_mode_hint\|task_type" backend/ scripts/ frontend/src/
```

Expected: baseline failures only, and the grep finds nothing outside comments you have already rewritten.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "refactor(chat): delete the routing code the new path replaced

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Report to the user: every symbol deleted, plus anything the orphan checks in Step 2 surfaced that was left alone.

---

### Task 8: `route` and `route_step` in the log

Every chat, classifier and explain row records which list answered and why, so the admin panel shows one traceable path per turn.

**Files:**
- Modify: `backend/database/schema.py`, `backend/llm/call_logger.py`, `backend/services/admin_service.py:71-80`, `backend/services/web_search_reasoning_service.py` (`_log_chat_search`), `frontend/src/components/admin/AdminPage.jsx`
- Create: `tests/test_call_log_route.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_call_log_route.py`:

```python
"""route / route_step turn a turn's rows into a readable trail: which list
answered, why that list, what it fell past on the way."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from backend.database.schema import ALL_TABLES, MIGRATIONS


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for statement in ALL_TABLES:
        conn.execute(statement)
    for migration in MIGRATIONS:
        for statement in (migration if isinstance(migration, (list, tuple)) else [migration]):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass
    conn.commit()

    @contextmanager
    def _get_conn():
        yield conn
        conn.commit()

    monkeypatch.setattr("backend.utils.db.get_connection", _get_conn)
    return conn


def test_write_call_row_persists_route_and_step(db):
    from backend.llm.call_logger import write_call_row
    write_call_row(run_id="r1", parent_run_id=None, timestamp_start="t", timestamp_end="t",
                   latency_ms=1, provider="groq", call_type="chat_turn",
                   route="simple ← classifier+toggle:web_search", route_step=2)
    row = db.execute("SELECT route, route_step FROM llm_call_log WHERE run_id='r1'").fetchone()
    assert row["route"] == "simple ← classifier+toggle:web_search"
    assert row["route_step"] == 2


def test_logger_reads_route_off_the_call_metadata(db):
    from uuid import uuid4
    from langchain_core.outputs import ChatGeneration, LLMResult
    from langchain_core.messages import AIMessage
    from backend.llm.call_logger import LLMCallLogger

    handler, run_id = LLMCallLogger(), uuid4()
    handler.on_chat_model_start(
        {}, [[AIMessage(content="hi")]], run_id=run_id,
        metadata={"call_type": "chat_turn", "ls_provider": "groq", "ls_model_name": "openai/gpt-oss-120b",
                  "route": "complex ← classifier", "route_step": 1})
    handler.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage(content="answer"))]]),
                       run_id=run_id)
    row = db.execute("SELECT route, route_step, provider FROM llm_call_log").fetchone()
    assert (row["route"], row["route_step"], row["provider"]) == ("complex ← classifier", 1, "groq")


def test_admin_rows_expose_route(db):
    from backend.services import admin_service
    assert "l.route" in admin_service._ROW_COLUMNS
    assert "l.route_step" in admin_service._ROW_COLUMNS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_call_log_route.py -v`
Expected: FAIL — `TypeError: write_call_row() got an unexpected keyword argument 'route'`.

- [ ] **Step 3: Add the columns**

`backend/database/schema.py`, next to the other `MIGRATE_ADD_LLM_CALL_LOG_*` statements:

```python
# Chat routing v2 — which model list answered this call and why, plus that
# model's 1-based position in the list. Additive and nullable: every existing
# writer (feed_v2's logger included) keeps working untouched.
MIGRATE_ADD_LLM_CALL_LOG_ROUTE      = "ALTER TABLE llm_call_log ADD COLUMN route TEXT"
MIGRATE_ADD_LLM_CALL_LOG_ROUTE_STEP = "ALTER TABLE llm_call_log ADD COLUMN route_step INTEGER"
```

and append both to `MIGRATIONS` after `MIGRATE_ADD_LLM_CALL_LOG_TARGET_LANGUAGE`.

- [ ] **Step 4: Write them**

`backend/llm/call_logger.py`:
- `write_call_row`: add `route: str | None = None, route_step: int | None = None` to the signature, both column names to the INSERT list, two more `?` placeholders, and the two values to the tuple.
- `LLMCallLogger.on_chat_model_start`: store `"route": meta.get("route")` and `"route_step": meta.get("route_step")`.
- `LLMCallLogger._write_row`: pass `route=start["route"], route_step=start["route_step"]`.
- Module docstring: name the two new fields in the metadata list.

`backend/services/web_search_reasoning_service.py`: add `route="web_search",` to `_log_chat_search`'s `write_call_row` call (the line Task 4 deferred).

- [ ] **Step 5: Show it in the admin panel**

`backend/services/admin_service.py:71-80` — add `l.route, l.route_step,` to `_ROW_COLUMNS` (all four queries share it).

`frontend/src/components/admin/AdminPage.jsx`:
- `DetailPanel`'s metadata grid (~line 621): add a fifth cell after Provider / Model, rendered only when `row.route`:

```jsx
            {row.route && (
              <div className="col-span-2">
                <p className="text-[9px] uppercase tracking-widest text-slate-600 mb-0.5">Route</p>
                <p className="text-xs text-slate-300 truncate" title={row.route}>
                  {row.route}{row.route_step != null ? ` · step ${row.route_step}` : ""}
                </p>
              </div>
            )}
```
- `exportMeta` (line 164): add `["Route", row.route ? `${row.route}${row.route_step != null ? ` (step ${row.route_step})` : ""}` : "—"],`
- `CSV_COLUMNS` (line 284): add `["route", r => r.route],` and `["route_step", r => r.route_step],` after `agent_name`.

- [ ] **Step 6: Run the tests and the build**

```bash
.venv/Scripts/python.exe -m pytest tests/test_call_log_route.py -v
.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20
cd frontend && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add backend/database/schema.py backend/llm/call_logger.py backend/services/admin_service.py backend/services/web_search_reasoning_service.py frontend/src/components/admin/AdminPage.jsx tests/test_call_log_route.py
git commit -m "feat(admin): record which model list answered each call

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The explain popover moves onto the shared provider layer

The select-to-explain popover is the last place with its own hand-rolled OpenAI-SDK clients, its own quota check and its own model constants. It gets the `[explain]` list, the shared skip policy, and its rows get a `route` like everything else.

**Files:**
- Modify: `backend/services/unpack_service.py`, `backend/config/app_config.py:28-36`
- Create: `tests/test_unpack_service.py`

**Interfaces:**
- Consumes: `model_provider.route_legs / build_leg / run_route / route_label / extract_text / AllLegsFailed`, `call_logger.LLMCallLogger`.
- Produces: `unpack_service.explain_stream(term, user_id, sentence, prev_sentence, next_sentence)` — unchanged NDJSON contract (`chunk` / `done` / `error`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_unpack_service.py`. Deferred imports are patched at their source module (`backend.llm.model_provider`), per this project's patching rule:

```python
"""The explain popover on the shared provider layer: same NDJSON contract, same
5s budget, but the [explain] model list, the shared skip policy and a route on
every row instead of two hand-rolled OpenAI clients."""
from __future__ import annotations

import json

import pytest

from backend.llm import model_provider as mp
from backend.llm import rate_limits
from backend.services import unpack_service

VALID = json.dumps({"term": "latency", "definition_general": "delay before a transfer begins",
                    "meaning_in_context": "the wait before the first token arrives",
                    "confidence": "high"})


class _Chunk:
    def __init__(self, content):
        self.content = content


class _FakeModel:
    def __init__(self, script):
        self._script = script
        self.configs = []

    def bind(self, **kwargs):
        return self

    def stream(self, messages, config=None):
        self.configs.append(config)
        for item in self._script:
            if isinstance(item, Exception):
                raise item
            yield _Chunk(item)

    def invoke(self, messages, config=None):
        self.configs.append(config)
        item = self._script[-1]
        if isinstance(item, Exception):
            raise item
        return _Chunk(item)


@pytest.fixture(autouse=True)
def _no_cache_no_skips(monkeypatch):
    rate_limits.clear()
    monkeypatch.setattr(mp, "_keys_for_provider", lambda provider: ["k"])
    monkeypatch.setattr(unpack_service, "get_cached_unpack", lambda key: None)
    monkeypatch.setattr(unpack_service, "cache_unpack", lambda *a, **kw: None)
    monkeypatch.setattr(unpack_service, "_log_explain", lambda *a, **kw: None)
    yield
    rate_limits.clear()


def _events(term="latency", **kwargs):
    return [json.loads(line) for line in unpack_service.explain_stream(term, "user-1", **kwargs)]


def _legs(monkeypatch, scripts):
    built = []
    def _build(spec, **kw):
        model = _FakeModel(scripts[spec.step - 1])
        built.append((spec, model))
        return model
    monkeypatch.setattr(mp, "build_leg", _build)
    return built


class TestExplainStream:
    def test_streams_the_meaning_then_a_done_event(self, monkeypatch):
        _legs(monkeypatch, [[VALID[:60], VALID[60:]]])
        events = _events()
        assert events[-1]["t"] == "done"
        assert events[-1]["meaning_in_context"] == "the wait before the first token arrives"
        assert events[-1]["provider"] == "groq"
        assert any(e["t"] == "chunk" for e in events)

    def test_route_is_logged_on_the_call(self, monkeypatch):
        built = _legs(monkeypatch, [[VALID]])
        _events()
        meta = built[0][1].configs[0]["metadata"]
        assert meta["route"].startswith("explain") and meta["route_step"] == 1
        assert meta["call_type"] == "explain" and meta["surface"] == "explain"

    def test_unparseable_answer_retries_strictly_then_moves_on(self, monkeypatch):
        built = _legs(monkeypatch, [["not json at all", "still not json"], [VALID]])
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["provider"] == "gemini"
        assert len(built) == 2

    def test_a_rate_limited_leg_falls_through(self, monkeypatch):
        import groq, httpx
        limited = groq.RateLimitError(
            "Error code: 429 - tokens per minute (TPM): Limit 8000",
            response=httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com/x")),
            body=None)
        _legs(monkeypatch, [[limited], [VALID]])
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["provider"] == "gemini"
        assert rate_limits.is_skipped("groq", "openai/gpt-oss-120b", 0) == "rate_limit"

    def test_total_failure_degrades_to_the_dictionary(self, monkeypatch):
        _legs(monkeypatch, [[RuntimeError("Error code: 400 - nope")],
                            [RuntimeError("Error code: 400 - nope")]])
        monkeypatch.setattr(unpack_service, "is_dictionary_fast_path_eligible", lambda term: True)
        monkeypatch.setattr(unpack_service, "dictionary_lookup", lambda term: {
            "term": term, "definition_general": "a delay", "meaning_in_context": None,
            "confidence": "low"})
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["source"] == "dictionary_fallback"

    def test_no_dictionary_entry_still_answers_honestly(self, monkeypatch):
        _legs(monkeypatch, [[RuntimeError("Error code: 400 - nope")],
                            [RuntimeError("Error code: 400 - nope")]])
        monkeypatch.setattr(unpack_service, "is_dictionary_fast_path_eligible", lambda term: False)
        events = _events()
        assert events[-1]["t"] == "done" and events[-1]["source"] == "unavailable"

    def test_empty_term_is_an_error(self):
        assert _events(term="  ")[0]["t"] == "error"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_unpack_service.py -v`
Expected: FAIL — the current module builds raw `OpenAI` clients, so `build_leg` is never called.

- [ ] **Step 3: Rewrite the LLM half of `backend/services/unpack_service.py`**

Delete `_GEMINI_API_URL`, `_LLM_TIMEOUT_S`, `_groq_client`, `_gemini_client`, `_get_groq_client`, `_get_gemini_client`, `_is_quota_error`, `_stream_groq`, `_call_groq_once`, `_call_gemini`, and the `GROQ_BASE_URL, GROQ_UNPACK_MODEL, GEMINI_UNPACK_MODEL` import. Keep the cache, `_parse_response`, `_extract_partial_meaning`, `_line`, `_done_line`, `_fmt_messages`, `_log_explain` (still the writer for the cache and dictionary rows) and the dictionary degrade. Add:

```python
# The popover has a ~5s budget and a 200-token answer; both live in
# chat_models.toml's [explain] list, not here. 0.3 keeps the JSON shape stable
# (the chat default of 0.7 is tuned for prose, not for a small strict schema).
_TEMPERATURE = 0.3
_CALL_TYPE = "explain"


def _stream_leg(spec, messages, strict_messages, base_meta, notes):
    """One [explain] leg: stream the JSON, reveal meaning_in_context as it
    arrives, then parse. A model that answers in the wrong shape gets one
    stricter, non-streaming retry on the same leg — that is a formatting slip,
    not an unavailable model. Yields ("chunk", text), then ("done", parsed) or
    ("invalid", raw)."""
    from ..llm.model_provider import build_leg, extract_text, route_label

    def _model(streaming: bool):
        model = build_leg(spec, streaming=streaming, temperature=_TEMPERATURE)
        # Gemini honours an OpenAI-style json_object request; Groq streams the
        # JSON as plain text, which _extract_partial_meaning already reads.
        return model.bind(response_format={"type": "json_object"}) if spec.provider == "gemini" else model

    config = {"callbacks": [LLMCallLogger()],
              "metadata": {**base_meta, "agent_name": "explain_stream",
                           "route": route_label("explain", "", notes), "route_step": spec.step}}

    buffer, sent = "", 0
    for chunk in _model(True).stream(messages, config=config):
        buffer += extract_text(chunk)
        partial = _extract_partial_meaning(buffer)
        if partial and len(partial) > sent:
            yield "chunk", partial[sent:]
            sent = len(partial)

    parsed = _parse_response(buffer)
    if parsed is None:
        retry_config = {**config, "metadata": {**config["metadata"], "agent_name": "explain_strict_retry"}}
        parsed = _parse_response(extract_text(_model(False).invoke(strict_messages, config=retry_config)))
    if parsed is None:
        yield "invalid", buffer
        return
    yield "done", parsed
```

and replace the LLM section of `explain_stream` (everything between the cache hit and the dictionary degrade) with:

```python
    # ── LLM path: the [explain] list, top to bottom ────────────────────────
    messages = build_unpack_messages(term, sentence, prev_sentence, next_sentence)
    strict_messages = build_unpack_messages(term, sentence, prev_sentence, next_sentence, strict=True)
    base_meta = {"call_type": _CALL_TYPE, "surface": "explain", "trace_id": trace_id,
                 "user_id": user_id}

    from ..llm.model_provider import AllLegsFailed, route_legs, run_route
    legs = iter(route_legs("explain"))     # shared: each attempt resumes where the last stopped
    notes: list[str] = []
    result: dict | None = None
    provider_used: str | None = None

    while result is None:
        try:
            spec, events = run_route(
                "explain", lambda s: _stream_leg(s, messages, strict_messages, base_meta, notes),
                notes=notes, legs=legs)
        except AllLegsFailed:
            break
        try:
            for kind, payload in events:
                if kind == "chunk":
                    yield _line("chunk", v=payload)
                elif kind == "done":
                    result, provider_used = payload, spec.provider
                elif kind == "invalid":
                    notes.append(f"skipped {spec} (invalid_output)")
        except Exception:
            # A failure after the first chunk: the next leg answers instead.
            logger.warning("[unpack] %s failed mid-stream — trying the next leg", spec, exc_info=True)
```

Add `from ..llm.call_logger import LLMCallLogger` to the module imports.

- [ ] **Step 4: Delete the two model constants**

`backend/config/app_config.py`: delete `GROQ_UNPACK_MODEL` and `GEMINI_UNPACK_MODEL` (lines 28-36) — the `[explain]` list in `chat_models.toml` replaces them. Confirm first:

```bash
grep -rn "GROQ_UNPACK_MODEL\|GEMINI_UNPACK_MODEL" backend/ tests/ scripts/
```

- [ ] **Step 5: Run the tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_unpack_service.py -v
.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -20
```

- [ ] **Step 6: Commit**

```bash
git add backend/services/unpack_service.py backend/config/app_config.py tests/test_unpack_service.py
git commit -m "refactor(explain): run the popover on the shared model layer

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Live smoke

Ten real turns through the real path, flagged `is_test=True`, then the log is checked. This is the last gate before the user tries the branch in the app.

**Files:**
- Create: `scripts/smoke_test_chat_routing_v2.py`

- [ ] **Step 1: Write the smoke script**

```python
"""Live smoke for chat routing v2 — real providers, real DB, is_test=True.

Ten turn types, then the log check the spec asks for: every chat/classifier/
explain row carries a route, and nothing called OpenRouter.

    python scripts/smoke_test_chat_routing_v2.py
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import chat_service, unpack_service
from backend.utils.db import DB_PATH, init_db

CARD = {
    "action": "ask_about",
    "insight_title": "Why Small Reasoning Models Beat Big Ones on Cost",
    "insight_summary": "A 150M-parameter reasoning model set a new cost-accuracy frontier on "
                       "ARC-AGI-1, which cuts against the assumption that capability tracks size.",
    "why_it_matters": "Recurrent latent reasoning lets a small model re-use its own intermediate "
                      "state, so it buys depth with time instead of parameters.",
    "blocks": [{"type": "mechanism", "content": "Latent recurrence trades parameter count for "
                                                "sequential compute at inference."}],
    "source_urls": ["https://paperswithcode.com/sota"],
    "source_links": [{"title": "Trending Papers", "url": "https://paperswithcode.com/sota"}],
    "project_name": "Model Efficiency", "domain": "ai", "content_type": "news",
}


def run_turn(label, message, *, chat_mode="normal", feed_context=None, attachments=None):
    session_id = f"smoke-{uuid.uuid4().hex[:8]}"
    kinds, text, sources, error = {}, [], [], None
    for line in chat_service.chat_stream(
        session_id, message, chat_mode=chat_mode, feed_context=feed_context,
        attachments=attachments, is_test=True, client_timezone="Asia/Kolkata",
    ):
        event = json.loads(line)
        kinds[event["t"]] = kinds.get(event["t"], 0) + 1
        if event["t"] == "chunk":
            text.append(event["v"])
        elif event["t"] == "done":
            sources = event.get("sources") or []
        elif event["t"] == "error":
            error = event["message"]
    answer = "".join(text)
    print(f"\n=== {label} ===")
    print("events:", kinds, "| sources:", len(sources), "| chars:", len(answer))
    print("answer:", answer[:220].replace("\n", " "))
    if error:
        print("ERROR:", error)
    return {"label": label, "session_id": session_id, "kinds": kinds,
            "answer": answer, "sources": sources, "error": error}


def main() -> None:
    init_db()
    results = []

    results.append(run_turn("1 plain", "What is attention in transformers?"))
    results.append(run_turn("2 automatic search", "What were the biggest AI releases this week?"))
    results.append(run_turn("3 search toggle", "How does retrieval-augmented generation work?",
                            chat_mode="web_search"))
    results.append(run_turn("4 explain-simply toggle", "Explain vector databases", chat_mode="layman"))
    results.append(run_turn("5 feed ask about", "Why does the small model win on cost?",
                            feed_context=dict(CARD)))
    results.append(run_turn("6 feed explain simply", "Explain this simply.",
                            feed_context={**CARD, "action": "explain_simply"}))
    results.append(run_turn("7 code execution",
                            "Compute the 30th Fibonacci number by running python code."))

    from PIL import Image, ImageDraw
    from backend.llm.model_provider import upload_attachment
    image = Image.new("RGB", (200, 200), color=(255, 255, 255))
    ImageDraw.Draw(image).rectangle([40, 40, 160, 160], fill=(220, 20, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    upload = upload_attachment(buffer.getvalue(), "image/png", "square.png")
    results.append(run_turn("8 image", "What colour is the shape in this image?",
                            attachments=[upload]))

    results.append(run_turn("9 crisis", "than I will do suicide"))

    print("\n=== 10 explain popover ===")
    explain = [json.loads(line) for line in unpack_service.explain_stream(
        "latent recurrence", "smoke-user",
        sentence="Latent recurrence trades parameter count for sequential compute.")]
    print("events:", [e["t"] for e in explain])
    print("meaning:", (explain[-1].get("meaning_in_context") or "")[:160])

    # ── Log checks ────────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT call_type, provider, route, route_step, success, error_type FROM llm_call_log "
        "WHERE is_test = 1 AND created_at >= datetime('now', '-30 minutes')").fetchall()
    routed = [r for r in rows if r["call_type"] in ("chat_turn", "chat_router_classify", "explain")]
    missing_route = [dict(r) for r in routed if not r["route"]]
    openrouter = [dict(r) for r in rows if r["provider"] == "openrouter"]
    failures = [dict(r) for r in rows if not r["success"]]

    print("\n=== log ===")
    print(f"rows: {len(rows)} | routed: {len(routed)} | missing route: {len(missing_route)} "
          f"| openrouter: {len(openrouter)} | failed calls: {len(failures)}")
    for row in routed[:12]:
        print(f"  {row['call_type']:<22} {row['provider']:<10} step {row['route_step']} :: {row['route']}")
    for row in failures:
        print("  FAILED:", row["call_type"], row["error_type"], row["route"])

    problems = [r for r in results if r["error"] or not r["answer"].strip()]
    print("\n=== verdict ===")
    print("turns without an answer:", [p["label"] for p in problems] or "none")
    assert not missing_route, f"rows without a route: {missing_route}"
    assert not openrouter, f"OpenRouter was called: {openrouter}"
    assert not problems, "some turns produced no answer"
    print("PASS")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python.exe scripts/smoke_test_chat_routing_v2.py`

Check by eye, against the spec's list:
- turns 1-9 each produced an answer, and turn 9 offered a real helpline for `Asia/Kolkata`;
- turn 2 and turn 3 show `status` events and non-zero `sources`;
- turn 6's answer is in simple-explanation shape;
- turn 7 shows `code` / `code_output` events (or one `code_execution_gap` note if a non-Gemini-3 leg answered);
- turn 8 names the colour;
- every printed row has a route like `simple ← classifier`, `classifier`, `explain`;
- `openrouter: 0`.

Anything that fails here is a real defect: fix it, re-run, and only then move on.

- [ ] **Step 3: Commit and hand over**

```bash
git add scripts/smoke_test_chat_routing_v2.py
git commit -m "test: live smoke for the chat routing v2 path

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Then tell the user: the branch is ready to try in the app, what the smoke printed (routes per turn type, failure count, OpenRouter count), and that merging is their call. Rollback is reverting the merge commit.

---

## Success criteria

- Non-integration pytest passes, except the failures recorded in the Task 1 baseline.
- Pytest makes zero real provider calls (the Task 1 guard, still green at the end).
- `grep -rn` finds no references to `model_priority`, `chat_tools`, `action_router_service`, `learning_system_context_service`, `map_to_task_type`, `resolve_tools_and_hint`, `build_mode_hint`, `task_type` outside history.
- Prompt sizes at or under the Section 2 ceilings, and the side-by-side check approved by the user.
- Live smoke: all ten turn types answer; every chat, classifier and explain row has `route`; zero OpenRouter calls.
- Post-merge watch (not a merge gate): share of real turns with at least one failed model call, target under 20% against the 54% baseline. Query:

```sql
SELECT ROUND(100.0 * SUM(failed > 0) / COUNT(*), 1) AS pct_turns_with_a_failure
FROM (SELECT trace_id, SUM(success = 0) AS failed FROM llm_call_log
      WHERE is_test = 0 AND surface = 'chat' AND user_id IS NOT NULL
        AND created_at >= '<merge date>' GROUP BY trace_id);
```

## Risks carried into the build

| Risk | Where it is handled |
|---|---|
| Plain streaming may not surface Gemini thinking / code-execution parts | Task 2 spike, with a hard stop before any rewrite |
| Groq JSON-schema output may be unreliable for the classifier, or 400 tokens too tight with reasoning on | Task 2 spike; the fix is a `max_tokens` or ordering change in the TOML, and an invalid answer already falls through |
| Free-tier ceilings for gpt-oss-120b and gemini-3.1-flash-lite are unmeasured | `route` logging makes hits visible; reordering is a config edit |
| Prompt trims could cost answer quality | Task 6 Step 12 is a user gate, not a checkbox |
| A Groq-first route rejects a long prompt (8K TPM) | Per-leg budget check skips that leg instead of failing the turn (Task 5) |

## Deviations from the spec, and why

1. **Per-leg budget check** instead of "evaluate against the first model of the chosen list" (spec 3c). Evaluating only the first model would abort a whole turn when a Groq leg's 8K TPM ceiling is too small for a long prompt, even though the Gemini leg behind it has a 1M window. Per-leg, an over-budget leg is skipped and logged as `(budget)`.
2. **`simple` tier searches once** with a cap of 4 primary results (spec kept 2+2 for the simple tier while saying simple runs one query). Same source count as before, one fewer round trip.
3. **`scripts/smoke_test_prompt_adaptive_format.py` is deleted** (Task 7). The spec's table missed it; it drives the JSON card path and `detect_depth`, both of which this work removes.
4. **`+sticky:explain_simply`** is recorded in `TurnPlan.reason` alongside the three overrides the spec lists — sticky simple mode is a real reason a turn answered in that tone, and the admin log should say so.
5. **Two Gemini flash-lite models are registered** in `model_registry.py` (Task 3) so the per-leg budget check and the chat budget log stop falling back to the 32K default.
