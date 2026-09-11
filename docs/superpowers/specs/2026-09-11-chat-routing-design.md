# Chat Routing v2 — Design Spec

- **Date:** 2026-09-11
- **Branch:** `chat-routing-v2`
- **Status:** Sections 1–4 approved in chat; this document awaits review before the implementation plan.
- **Scope:** the chat surface (`/chat/stream`, Feed "Ask About" / "Explain Simply" chats, the select-to-explain popover). `feed_v2` is out of scope.

## Goal

One routing path for chat that is easy to read in code and in the admin log:

1. A classifier runs on every turn.
2. Its answer, combined with the user's toggles, becomes a turn plan.
3. The plan picks a model list from one plain config file.
4. One retry/skip policy handles provider errors.
5. Every log row records which list was used and why.

Alongside that: smaller prompts that answer at least as well, and safe removal of the duplicate and dead routing code.

## Evidence this design is based on

All numbers come from `data/curivio.db` (`llm_call_log`, `is_test = 0`), filtered to real users (traces with a `user_id`), unless noted.

| Finding | Number |
|---|---|
| Real chat turns since 2026-08-12 | 77 |
| Turns with at least one failed model call | 54% |
| Turn wall time | median 13.0 s, p90 29.7 s |
| OpenRouter nemotron | `402 PaymentRequired` — both keys have `total_credits = 0` (balances about −$0.20 and −$0.05) |
| gemini-2.5-flash free tier | 20 requests/day and 5 requests/minute per key (1,174 logged 429s) |
| Groq gpt-oss-20b | 8,000 tokens/minute, shared today by the classifier and simple answers in the same turn |
| Classifier failures on Groq | `400 Tool choice is required, but model did not call a tool` (tool-calling structured output) |
| Web-search turns | 2 answer LLM calls each (13 of 13); the two TinyFish searches run one after the other (~4.2–4.8 s) |
| Crisis section (~1.2K tokens) | present in 34 of 77 real turns, mostly because the classifier failed or was skipped |
| Feed JSON card prompt | 0 real uses since 2026-08-01 |
| Test traffic in the log | 649 of 795 plain `chat_turn` rows since 2026-08-01 are pytest runs: message "hi", no user, no system prompt, logged as non-test. The shape matches tests that mock the retired `grok_service.ask_grok_chat_stream` instead of the current stream function (`tests/test_chat_quickstarters.py:161-163`, `tests/test_chat_intent_service.py:344-345`), so they make real LLM calls |
| "Continue Research" | no button in the UI; only backend leftovers remain |
| Deep research | generator already removed; stored rows expired (TTL 48 h, newest row 2026-08-21) |
| Ox Alpha | stealth name for Z.ai GLM-5.3-Flash; free window ended; now $0.15 / $0.50 per million tokens; OpenRouter refuses a real-size call at zero credit (`402 … can only afford 87 tokens`) |

## Decisions

1. The classifier runs on every turn. The answering model gets no client-side tools.
2. **Toggles are overrides (option A).** "Web Search" forces a search; "Explain Simply" forces simple tone. The classifier decides everything else.
3. Feed buttons never block search.
4. **OpenRouter is excluded from every chat list.** The account cannot be prepaid now; the test budget cap was $0.50 and $0 was spent. The loader keeps `openrouter` as a valid provider so GLM can be added by a config edit once the account is funded.
5. The Feed JSON card output format is dropped. New Feed answers render as markdown; previously saved JSON answers still render.
6. `feed_v2` is not touched.

---

## Section 1 — How a turn works

```
1. Load session history (unchanged).
2. Classifier (every turn, JSON output), started concurrently with context loading.
3. plan_turn(): merge classifier output with user toggles and Feed action -> TurnPlan.
4. If plan.search: run TinyFish (1 query for simple, 2 queries in parallel for complex).
5. Build the prompt (Section 2).
6. Stream the answer through the model list for plan.route (Section 3).
7. Log route + route_step on every model-call row.
```

### Classifier

- Lives in `backend/llm/chat_router.py` (rewritten in place).
- Input: classifier system prompt, the same recent history window the answer uses (`MAX_HISTORY_TURNS`), the message, and — when the chat is Feed-linked — the card title (from `feed_context` on the first turn, from the session's Feed link on later turns), so the classifier knows source material is already present.
- Output schema (validated with Pydantic; produced through JSON-schema structured output, never tool calling):

```python
class RoutingDecision(BaseModel):
    needs_web_search: bool
    search_query: str                  # "" when no search is needed
    complexity: Literal["simple", "complex"]
    needs_code_execution: bool         # the answer requires running code
    wants_simple_explanation: bool     # user asked for a simple / ELI5 explanation
    crisis: bool
```

- If a model returns invalid JSON or errors, the next model in `[classifier]` is tried. If all fail, `plan_turn` receives `None`.

### Turn plan

```python
@dataclass
class TurnPlan:
    route: str          # "simple" | "complex" | "code" | "image"
    reason: str         # e.g. "classifier", "classifier_failed", "classifier+toggle:web_search"
    search: bool
    search_query: str
    simple_tone: bool
    crisis: bool
    complexity: str     # "simple" | "complex"
```

Merge rules in `plan_turn()`:

| Field | Rule |
|---|---|
| `search` | Web Search toggle **or** `decision.needs_web_search` |
| `search_query` | `decision.search_query` if non-empty, else the user's message |
| `simple_tone` | Explain Simply toggle **or** Feed action `explain_simply` **or** session is in sticky simple mode (existing behaviour, including the exit phrases) **or** `decision.wants_simple_explanation` |
| `crisis` | `decision.crisis`; `True` when the classifier failed (fail-safe kept). The existing 5-turn carry-over window is kept unchanged |
| `route` | `image` if an image is attached; else `code` if `needs_code_execution`; else `complex` if `complexity == "complex"`; else `simple` |
| classifier failed | `route` = `image` or `simple`; `search` only if toggled; `crisis = True`; `reason = "classifier_failed"` |
| `reason` | base `classifier` / `classifier_failed`, plus `+toggle:web_search`, `+toggle:explain_simply`, `+feed:explain_simply` when an override set the value |

### Web search (code-run, no tool)

- Runs through the existing `web_search_reasoning_service` → `retrieval_router` → TinyFish path.
- `complexity == "simple"`: primary query only. `complex`: primary and contradiction queries run concurrently.
- Results are injected as a system note before the last user message.
- `chat_service` emits the same NDJSON `status` events (`tool="web_search"`, `query`, then `sources`) and persists the same `tool_call` block, so the frontend's live search block and `[N]` citations keep working unchanged.

### Answer streaming

- `backend/llm/chat_agent.py` is rewritten as a plain fallback loop (no LangGraph agent, no middleware):
  - for each `(model, key)` in the route's list that is not currently skipped: start streaming;
  - an error **before the first chunk** → `classify_error` → skip rule → next model;
  - an error **after the first chunk** → the error is surfaced to the user (no duplicated partial answers).
- Gemini chat legs keep visible thinking (`include_thoughts=True`). The `code` route's Gemini 3 leg binds the built-in `{"code_execution": {}}` tool.
- All existing stream event shapes are kept: `text`, `thinking`, `thinking_gap`, `code`, `code_output`, `code_execution_gap`.
- The `image` route uses the first Gemini key only (Files API scope, unchanged) and keeps the existing "Vision is temporarily unavailable" error.

### Removed from the turn

Regex action router, the `web_search` LLM tool and its second LLM call, the `[MODE HINT]` note, the duplicated image gates, `map_to_task_type`, `resolve_tools_and_hint`.

---

## Section 2 — Prompts

**Rule:** every behaviour rule stays. Only duplicates, dead sections and wasted text are removed. The crisis text is not edited. Changes merge only after the side-by-side check in Section 4.4 is approved.

One prompt builder serves all chat turns (the natural/structured split is removed).

### System prompt order

1. Persona (single version, the current natural persona, with the user's name).
2. Response principles (single copy).
3. Simple-tone directive — only when `plan.simple_tone`.
4. Memory, profile, Feed entry anchor, attachment awareness — only when present.
5. Crisis section — only when `plan.crisis` or the carry-over window is active; always the last block of the system prompt (same position as today).

Separate system notes before the last user message (as today): Feed card note, document excerpts, search results, title note. Static text first keeps the prefix cacheable by providers.

### Block changes

| Block | Today | After |
|---|---|---|
| Persona | two versions (`_PERSONA`, `_PERSONA_NATURAL`) | one |
| Response principles | 4,141 chars; second 2,495-char copy for simple tone | same rules with overlapping bullets merged (length / shape / structure; the two continuity bullets) → ~2,800 chars; the simple-tone variant is derived from the same text, not a second copy |
| Simple-tone directive | ~3,400 chars with three overlapping self-checks | keep the 5-step structure, simplify / never-simplify lists, one BAD/GOOD example and the domain analogy seed; merge the three checks into one → ~1,800 chars |
| Ask About instruction | 1,753 chars; about half repeats the principles verbatim | Feed-specific lines only (answer their question; the card is grounding, not the subject; use its specifics; don't restate the summary) → ~700 chars |
| Card mechanism sentence | up to 4 copies per prompt | once. "Do NOT search the web" and "call web_search on the source URLs" removed |
| Web search results note | ~2K chars of instructions incl. a 4-step internal ritual, a mandatory "What the data complicates" section, and "2024 2025" hardcoded in the contradiction query | keep numbered citation rules and "surface genuine conflicts between sources"; the complicates section only when sources genuinely conflict; year taken from the current date |
| Tension directive | ~1,500 chars; its examples repeat other blocks | one line added to the principles ("end on the open tension, not a summary"); block deleted |
| Crisis section | verbatim text in 44% of real turns | same text; only on a real signal, classifier failure, or the carry-over window |
| Feed JSON card format, `_GUIDELINES`, and the JSON-only sections (research, session, exploration breadth, preferences, explanation/domain/format directives, continuity, learning system, action result) | 0 real uses since 2026-08-01 | deleted |
| Feed source "Extracted text" | raw page markdown (images, repeated nav lines) | markdown image lines and link-only lines stripped, duplicate lines collapsed |
| "Related past discussion" | repeated identical entries | de-duplicated |
| Title note | — | unchanged |

### Size targets (measured on the real sample prompts)

| Turn type | Today | Target |
|---|---|---|
| Feed Explain Simply | 14.3K chars | ≤ 8.0K |
| Feed Ask About | 10.6K | ≤ 7.5K |
| Web-search turn | 13.4K | ≤ 7.0K |
| Plain chat | 9.1K | ≤ 6.5K |

---

## Section 3 — Model config, retry/skip policy, logging

### 3a. `backend/llm/chat_models.toml`

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

**Loader** (~30 lines in `backend/llm/model_provider.py`, keeping one LLM entry point):

- Reads the file once at startup; fails loudly on: unknown provider, empty list, `code` list not starting with a Gemini 3 model, `image` list containing a non-Gemini model, missing `[retry]` values.
- "Image uses the first Gemini key only" stays in code (a technical constraint, not a preference).
- `reasoning` is mapped per provider in one function:

| Provider / model | `low` | `off` |
|---|---|---|
| Gemini 3.x | `thinking_level="low"` | `thinking_level="low"` (no off) |
| Gemini 2.5 | `thinking_budget=1024` | `thinking_budget=0` |
| Groq gpt-oss | `reasoning_effort="low"` | `reasoning_effort="low"` (no off) |
| OpenRouter | `reasoning={"effort": "low"}` | `reasoning={"enabled": False}` |

Gemini chat legs use `include_thoughts=True`; classifier and explain legs do not.

**Replaces:** `backend/llm/model_priority.py`; `GROQ_FAST_MODEL`, `GEMINI_LITE_MODEL`, `OPENROUTER_NEMOTRON_MODEL`, `GROQ_UNPACK_MODEL`, `GEMINI_UNPACK_MODEL` in `app_config.py`. `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GROQ_FALLBACK_MODEL` stay for old Feed callers of `get_chat_model`; chat stops reading them.

### 3b. `backend/llm/rate_limits.py` (~80 lines)

```python
def classify_error(exc: BaseException) -> str:
    """"rate_limit" | "daily_quota" | "no_credit" | "transient" | "fatal"."""

def skip(provider: str, model: str | None, key_index: int | None, kind: str) -> None:
    """Park a model+key (or a whole provider when model/key are None) for the [retry] duration of `kind`."""

def is_skipped(provider: str, model: str, key_index: int) -> bool: ...
```

- In-memory, per process; cleared on restart.
- `no_credit` skips the whole provider; `rate_limit` and `daily_quota` skip the model+key; `transient` is retried `retries_per_model` times, then the next model; `fatal` moves to the next model without skipping.
- **Used by:** the chat answer loop, the classifier, explain, the old Feed `get_chat_model` chain (its retry predicate), `writer_provider_router`, and the embeddings rate-limit check.
- **Replaces:** `_is_daily_quota_exhausted`, the `_QuotaAwareRetry` predicate, chat_agent `_retry_on`, the Groq-400 special retry, `writer_provider_router._is_quota_error`, `unpack_service._is_quota_error`, `embeddings._is_rate_limit_error`.
- **Not touched:** inbound request limits (slowapi values in `app_config.py`), `feed_v2`, `ask_grok`.

| Error | Today | New |
|---|---|---|
| 429 per-minute | backoff, retry up to 3×, then next model | next model immediately; skip model+key 30 s |
| Daily quota | next model, paid again every turn | next model; skip model+key 1 h |
| 402 no credit | generic error, paid every turn | skip whole provider 10 min |
| Network / 5xx | backoff, retry up to 3× | retry once, then next model |
| Classifier invalid JSON | special Groq retry | next model |

### 3c. Logging

- Two new `llm_call_log` columns, added with the existing `MIGRATE_ADD_LLM_CALL_LOG_*` pattern in `backend/database/schema.py`:
  - `route TEXT` — e.g. `simple ← classifier`, `complex ← classifier+toggle:web_search`, `simple ← classifier_failed · skipped groq/openai/gpt-oss-120b (rate_limit)`, `classifier`, `explain`.
  - `route_step INTEGER` — 1-based position in the list of the model that made this call.
- Passed through call metadata; written by `LLMCallLogger` and `write_call_row`.
- Shown in the admin row detail and included in exports (`admin_service` row columns, `AdminPage.jsx`).
- The classifier's decision JSON is already in its own row's output.
- The budget preflight evaluates against the first model of the chosen list instead of a hardcoded `GEMINI_MODEL`.

---

## Section 4 — Deletions, safety, tests, rollout

### 4.0 Clean base (done)

Pre-existing tracked changes were committed as-is on `chat-routing-v2` (commit `aa1a550`) before any refactor work. `main` is untouched. Untracked files were left alone.

### 4.1 Deletion list

| Delete | Non-test callers today | Replaced by |
|---|---|---|
| `backend/llm/model_priority.py` | model_provider, chat_agent | `chat_models.toml` |
| `backend/llm/chat_tools.py` | chat_agent | code-run TinyFish search |
| chat_agent.py: LangGraph agent, `CodeExecutionToolMiddleware`, `ModelFallbackMiddleware`/`ModelRetryMiddleware` wiring, `resolve_tools_and_hint`, `build_mode_hint`, agent cache | chat_service | streaming fallback loop (`_split_content_chunks` kept) |
| model_provider.py: `_build_pooled_leg`, `build_pooled_legs`, `get_chat_model_for_task`, `_build_structured_legs`, `get_structured_chat_model_for_task`, `get_structured_chat_model_legs_for_task`, Groq-400 retry, `_is_daily_quota_exhausted`, unreachable `return pairs` | chat_agent, chat_router, one smoke script | TOML loader + `rate_limits.py` |
| chat_router.py: tool-calling classifier, `map_to_task_type` | chat_service | JSON classifier + `plan_turn` |
| `backend/services/action_router_service.py` (+ `tests/test_action_router.py`) | chat_service | classifier + search |
| `grok_service.ask_grok_chat_stream` | none | — |
| chat_prompt_service.py: `_build_structured_prompt` and its section builders, `_PERSONA`, `_GUIDELINES`, `_STRUCTURED_FORMAT_DIRECTIVE`, `_FORMAT_DIRECTIVES`, tension hook, `detect_depth` (only if no other reader remains) | chat_service | single prompt builder |
| `backend/services/learning_system_context_service.py` | JSON prompt path only | — |
| tension_engine.py: `build_tension_directive` and helpers only it uses (`score_tension` kept) | chat_prompt_service | one principles line |
| "Continue Research" leftovers: chat_service mapping, chat_modes_service branch and label, learning-system line | — | — |
| unpack_service.py: raw Groq/Gemini clients, `_is_quota_error` | explain route | model_provider `[explain]` |
| `writer_provider_router._is_quota_error`, `embeddings._is_rate_limit_error` | internal | `rate_limits.classify_error` |
| app_config.py: `GROQ_FAST_MODEL`, `GEMINI_LITE_MODEL`, `OPENROUTER_NEMOTRON_MODEL`, `GROQ_UNPACK_MODEL`, `GEMINI_UNPACK_MODEL` | model_priority, unpack | TOML |
| `scripts/smoke_test_model_pool_rotation.py`, `scripts/smoke_test_chat_router.py` | test deleted code | one new smoke script |
| Frontend `ACTION_LABELS` + `ActionBadge` (`ChatMessage.jsx`) and `action` in the stream `done` event | action_router | — |

**Kept on purpose:** `get_chat_model` / `_build_raw_models` and their env model settings (old Feed callers); `ask_grok` (old Feed); memory/context loading and post-turn recommendations / continuity (still read); the expired deep-research reader inside the context loader (follow-up, not this work); `StructuredResponseRenderer` (old saved answers); the `continue_research` value in the DB CHECK constraint; `feed_v2`.

### 4.2 Safety method (every deletion)

1. **Baseline:** after the test isolation guard lands, run the full non-integration suite and record pre-existing failures. They are not fixed unless this work caused them.
2. For each item: search `backend/`, `scripts/`, `tests/` and `frontend/` for every reference → remove callers → delete → rerun the suite.
3. Delete only at zero non-test references. Anything ambiguous is listed for the user, not deleted.
4. Tests for deleted code are deleted with it; tests for changed behaviour are rewritten.

### 4.3 Tests

- **Isolation guard** (`tests/conftest.py`, autouse): any real network request to Gemini, Groq, OpenRouter or TinyFish from a test not marked `integration` raises. Constructing clients stays allowed, so offline tests that build models without calling them keep working. This stops real provider calls and fake log rows from pytest.
- **Stale mock targets fixed** in `test_chat_quickstarters.py`, `test_chat_intent_service.py`, `test_streaming.py` (and any others the guard exposes).
- **New tests:**
  - TOML loader validation (each failure case);
  - `plan_turn` merge rules (each toggle, Feed action, sticky simple mode, classifier failure fail-safe);
  - `classify_error` against real error shapes (Gemini daily/minute 429, Groq TPM 429, OpenRouter 402, 5xx, timeout);
  - skip expiry and provider-wide skip;
  - answer loop: failure before first chunk falls through, failure after first chunk raises, skipped legs are not called;
  - prompt builder: crisis only when flagged, mechanism sentence once, no JSON schema, size ceilings per turn type.

### 4.4 Prompt "same or better" check

- A script replays ~12 real logged turns (plain, Ask About, Explain Simply, web search, code, follow-up).
- Each turn runs twice on the same free model (Groq gpt-oss-120b, then Gemini flash-lite): old prompt (built from the pre-refactor commit) vs new prompt.
- Output: a side-by-side markdown file with prompt token counts and answers.
- The user reviews it; the prompt changes merge only after approval. Cost: $0 (free tiers).

### 4.5 Live smoke (`is_test=True`)

One turn each: plain chat, automatic web search, Web Search toggle, Explain Simply toggle, Feed Ask About, Feed Explain Simply, code with execution, image, crisis message, explain popover.

Checked: streaming, thinking and code blocks render; search block and citations render; every model-call row has `route` and `route_step`; zero OpenRouter calls.

### 4.6 Rollout

Work on `chat-routing-v2` → user tries it in the app → merge. Rollback is reverting the merge commit. No feature flag.

### Build order

0. Clean base (done).
1. Test isolation guard + baseline suite run.
2. Spikes: plain streaming keeps Gemini thinking and code-execution parts; classifier JSON-schema reliability on ~30 logged messages.
3. `chat_models.toml` + loader + `rate_limits.py`.
4. Classifier + `plan_turn` + search pre-fetch.
5. Answer streaming loop.
6. Prompt changes + side-by-side check (user approval gate).
7. Deletions (Section 4.1, with the Section 4.2 method).
8. Logging columns + admin display.
9. Explain popover onto model_provider.
10. Live smoke.

---

## Success criteria

- Non-integration pytest passes, except pre-existing failures recorded at baseline.
- Pytest makes zero real provider calls.
- Live smoke: all 10 turn types pass; every chat, classifier and explain model-call row has `route` set; zero OpenRouter calls from chat.
- Prompt sizes at or under the Section 2 targets; side-by-side check approved by the user.
- Every deleted symbol has zero non-test references.
- Post-merge watch (not a merge gate): share of real turns with at least one failed model call, target under 20% (baseline 54%).

## Risks

| Risk | Mitigation |
|---|---|
| Plain LangChain streaming may not surface Gemini thinking / code-execution parts the way the LangGraph path did | Spike in build step 2 before any rewrite; if it fails, keep a minimal wrapper only for the affected legs |
| Groq JSON-schema output may still be unreliable for the classifier, or `max_tokens = 400` may be too tight with reasoning on | Spike on ~30 logged messages; adjust `max_tokens` / order in TOML; invalid JSON already falls through to the next model |
| Free-tier limits for gpt-oss-120b and gemini-3.1-flash-lite are unknown (no 429s logged yet) | Skip policy plus `route` logging make hits visible; reorder in TOML |
| Prompt trims could lower answer quality | Side-by-side check is a merge gate |

## Out of scope

`feed_v2`; old Feed `get_chat_model` callers and `ask_grok`; memory/context loader cleanup (including the expired deep-research reader); the DB CHECK constraint value for `continue_research`; OpenRouter/GLM until the account is funded; inbound slowapi limits.
