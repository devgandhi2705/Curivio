---
title: Curivio
emoji: 📖
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
app_port: 7860
---

# Curivio

**An AI-powered daily learning companion.**

Curivio curates structured intelligence briefs from live web sources, lets you explore each card through conversational AI at three levels of depth, and tracks your learning progression across sessions — so every day builds on the last.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Authentication](#authentication)
- [API Reference](#api-reference)
- [Streaming Protocol](#streaming-protocol)
- [Key Systems In Depth](#key-systems-in-depth)
- [Database Schema](#database-schema)
- [Running Tests](#running-tests)
- [Deployment](#deployment)

---

## Features

### Intelligence Feed

- **Learning projects** — create focused projects with keywords, difficulty level, and focus areas; each generates a structured daily brief with current-events cards and evergreen educational deep-dives
- **Progressive curriculum** — 7 learning stages (Foundation → Mechanisms → Dependencies → Optimization → Geopolitical → Disruption → Synthesis); the system deepens content automatically as you read more
- **Inter-article continuity** — each new package explicitly references prior insights by name, so every day feels like it builds on the last rather than starting from scratch
- **Tension-scored curiosity picks** — 2 companion cards per package scored across 4 dimensions (novelty, contradiction, emotional surprise, narrative tension); minimum 7/12 threshold
- **Beginner calibration** — jargon-density scoring with a single automatic retry if content is too abstract for the selected difficulty
- **Read tracking + generation lock** — cards are individually marked as read; the next-day button only unlocks after all core cards are consumed
- **Notes** — write private notes on any card, persisted per project/package
- **Export** — download any daily package as PDF or Markdown
- **Read Later queue** — save cards to a read-later list and jump back to the exact card from any session

### AI Chat

- **Streaming multi-turn sessions** — NDJSON token streaming with auto-extracted session titles and full persistent history
- **Four chat modes:**
  - `normal` — memory + context only, fastest, no external retrieval
  - `web_search` — Tavily retrieval with reasoning-augmented dual-query (primary + contradiction angle)
  - `layman` — mechanism-preserving simplification; domain-specific analogy bank
- **Feed → Chat integration** — open any card in chat with one of three zoom levels: Ask About, Explain Simply, or Continue Research; each mode receives the card's extracted mechanism as its seed query
- **Auto intent detection** — regex fast-path + 9-dimension semantic scoring upgrades mode automatically for research/comparison/analysis phrasing
- **Cognitive tension directive** — tension engine scores the conversation and injects friction directives to prevent flat informational responses
- **Dynamic narrative rhythm** — rotates response structure (analytical, narrative, Socratic, comparative) across turns to prevent homogeneity
- **Adaptive depth** — classifies each message as quick / standard / detailed / research and calibrates verbosity accordingly
- **Follow-up intelligence** — suggests next topics, prerequisites, and advanced follow-ups using per-session and cross-session context

### Dashboard

- **Stats strip** — streak, cards read today, total cards, packages, and active projects
- **Learning calendar** — 12-month heatmap of daily reading activity per project
- **Weekly goal ring** — set a weekly card-read target; animated SVG ring tracks progress
- **30-day consistency** — dot-grid and percentage showing habit consistency
- **Weekday activity chart** — see which days of the week you learn most

### Search & Bookmarks

- **Global search** — `Ctrl+K` / `⌘K` overlay searches across feed cards, bookmarks, and chat sessions simultaneously
- **Bookmarks** — save and manage cards in the Bookmarks tab

### Mobile

- **Bottom navigation bar** — Feed / Chat / Dashboard / Bookmarks icons on small screens
- **Mobile project strip** — horizontal scrollable project selector replaces the desktop sidebar
- **Compact top bar** — search, queue, and settings icons on mobile; full labels on desktop

---

## Architecture Overview

```
User
 │
 ├─ Frontend (React + Vite)
 │   ├─ AuthContext         JWT session management, global 401 handler
 │   ├─ Feed components     Project cards, daily packages, InsightCard
 │   └─ Chat workspace      Stream consumer, mode selector, session list
 │
 └─ Backend (FastAPI)
     │
     ├─ Auth layer          JWT (HS256) + bcrypt + email verification (Brevo)
     │
     ├─ Feed pipeline
     │   ├─ project_service.py      Orchestrates daily package generation
     │   ├─ project_insight_prompt  Editorial prompt (9 title styles, 10 narrative
     │   │                          frames, tension scoring, beginner calibration)
     │   ├─ learning_memory_service Progression stages, semantic novelty gate
     │   │                          (bigram-Jaccard similarity), coverage tracking
     │   └─ retrieval_router        Domain-aware search → article blending
     │
     ├─ Chat pipeline
     │   ├─ chat_service.py         Turn orchestration (sync + streaming)
     │   ├─ chat_modes_service      Mode routing, mechanism-targeted queries
     │   ├─ chat_prompt_service     System prompt assembly (12+ context sections)
     │   ├─ chat_intent_service     Regex fast-path + semantic intent scoring
     │   ├─ tension_engine          Cognitive friction scoring + directive injection
     │   ├─ narrative_rhythm_service Response structure rotation
     │   └─ layman_mode_service     Domain-specific analogy banks + simplification
     │
     ├─ Memory layer
     │   ├─ memory_injection_service    Assembles context dict for every turn
     │   ├─ conversation_state_service  Tracks mechanisms + unresolved questions
     │   ├─ learning_system_context     Depth hierarchy framing (Discover→Master)
     │   └─ continuity_service          Cross-session concept persistence
     │
     └─ Storage
         └─ SQLite (WAL mode)   Single file, persistent under /data on HF Spaces
```

### Feed Generation Pipeline (per day)

```
1. Load project settings + learning memory + progression stage
2. Filter suggested topics through bigram-Jaccard novelty gate (threshold 0.45)
3. Parallel article retrieval:
   a. Core articles    — progression query + broader development query
   b. Curiosity articles — 2 randomly-sampled curiosity angles
4. Build prompt:
   - Inject progression stage mandate + coverage memory (covered_concepts,
     mechanisms, industries, geographies, title_patterns_used)
   - Inject inter-article continuity block (prior insights + open threads)
   - Apply beginner calibration section if difficulty == "beginner"
   - Inject tension-scored curiosity pick framework
5. LLM call (Groq) → JSON package
6. Beginner jargon check — if score > 18, single retry with addendum
7. Save package → update learning memory → update progression
```

### Chat Turn Pipeline (streaming)

```
1. Enrich feed_context: extract mechanism, load project memory
2. Detect intent (regex fast-path → semantic scoring)
3. Inject context: memory, conversation knowledge, domain, learner profile
4. Mode routing:
   - explain_simply  → layman mode + mechanism-preservation directive
   - web_search      → mechanism-anchored dual query (Tavily)
5. Assemble system prompt (12+ sections: persona, depth, format, tension,
   narrative rhythm, continuity, knowledge state, layman directive)
6. Stream tokens → persist messages → enrich recommendations
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend framework | FastAPI 0.136 + Uvicorn |
| AI / LLM | Groq API (Llama 3.3 70b / 3.1 8b Instant) |
| Web retrieval | Tavily API (search, extract, crawl strategies) |
| Email | Brevo (Sendinblue) SMTP — verification codes + password reset |
| Auth | Custom JWT (HS256) via `python-jose` + `bcrypt` |
| Database | SQLite with WAL mode (`python-jose`, custom migration system) |
| Rate limiting | SlowAPI |
| Scheduling | APScheduler (daily package generation) |
| Frontend | React 18, Vite 5, TailwindCSS 3 |
| Frontend build | Vite with automatic vendor chunk splitting |
| Testing | pytest with integration and unit test markers |
| Containerization | Docker + nginx reverse proxy |

---

## Project Structure

```
ai-learning-agent/
│
├── backend/
│   ├── main.py                          # FastAPI app, all endpoints, rate limiting,
│   │                                    # lifespan (DB init + migrations)
│   ├── config/
│   │   ├── app_config.py                # Global settings: rate limits, JWT expiry,
│   │   │                                # scheduler hour, CORS origins
│   │   └── retrieval_config.py          # Per-domain retrieval config, RankingWeights
│   │
│   ├── database/
│   │   └── schema.py                    # All CREATE TABLE statements + additive
│   │                                    # MIGRATIONS list (ALTER TABLE safe to re-run)
│   │
│   ├── prompts/
│   │   ├── project_insight_prompt.py    # Feed generation mega-prompt: 9 title styles,
│   │   │                                # 10 narrative frames, curiosity tension scoring,
│   │   │                                # beginner calibration, inter-article continuity
│   │   ├── learning_path_prompt.py      # Structured learning path generation
│   │   └── topic_expansion_prompt.py    # Related/prereq/advanced topic generation
│   │
│   └── services/
│       │
│       ├── ── Feed & Projects ──
│       ├── project_service.py           # Project CRUD, daily package generation,
│       │                                # beginner calibration, memory references
│       ├── learning_memory_service.py   # Per-project semantic coverage tracking:
│       │                                # progression stages, bigram-Jaccard novelty
│       │                                # gate, title pattern tracking, hook dedup
│       ├── progression_service.py       # Explored concepts + suggested next topics
│       ├── feed_cache_service.py        # Feed caching layer
│       ├── feed_read_service.py         # Card read state tracking
│       │
│       ├── ── Chat & Intelligence ──
│       ├── chat_service.py              # Chat turn orchestration (sync + streaming),
│       │                                # feed context enrichment, mode routing
│       ├── chat_prompt_service.py       # System prompt assembly (12+ sections),
│       │                                # depth detection, format directives
│       ├── chat_modes_service.py        # Mode context prep, mechanism-targeted queries,
│       │                                # feed context note, research progress streaming
│       ├── chat_intent_service.py       # Regex fast-path intent detection +
│       │                                # semantic scoring integration
│       ├── semantic_intent_service.py   # 9-dimension semantic intent scoring,
│       │                                # blended format directives
│       ├── web_search_reasoning_service.py # Dual-query reasoning search (supporting
│       │                                   # + complicating evidence separation)
│       ├── intelligence_service.py      # Daily intelligence brief pipeline
│       │
│       ├── ── Memory & Context ──
│       ├── memory_injection_service.py  # Assembles the full context dict per turn:
│       │                                # user profile, research, session, conversation
│       │                                # memory, exploration breadth, learner profile
│       ├── conversation_state_service.py # Tracks mechanisms, unresolved questions,
│       │                                # active domain per session
│       ├── learning_system_context_service.py # Depth hierarchy framing section:
│       │                                # Discover→Understand→Explore→Validate→Master
│       ├── continuity_service.py        # Cross-session concept persistence +
│       │                                # recommendation history
│       │
│       ├── ── Response Quality ──
│       ├── tension_engine.py            # Cognitive friction scoring + directive
│       │                                # injection; prevents flat informational tone
│       ├── narrative_rhythm_service.py  # Response structure rotation across turns:
│       │                                # analytical, narrative, Socratic, comparative
│       ├── layman_mode_service.py       # Domain-specific analogy banks +
│       │                                # mechanism-preserving simplification
│       ├── adaptive_explanation_service.py # Learner stage inference → explanation style
│       ├── follow_up_intelligence_service.py # Thread-aware follow-up recommendations
│       │
│       ├── ── Retrieval ──
│       ├── retrieval_router.py          # Domain-aware retrieval plan executor:
│       │                                # routes to search/extract/crawl strategies
│       ├── tavily_service.py            # Tavily search, extract, and crawl wrappers
│       ├── domain_classifier_service.py # Classifies query domain → selects directive
│       │
│       ├── ── Auth & User ──
│       ├── auth_service.py              # JWT creation/validation, bcrypt hashing,
│       │                                # email verification, password reset
│       ├── grok_service.py              # Groq API client (chat + feed + streaming)
│       │
│       └── ── Supporting ──
│           ├── bookmark_service.py
│           ├── feedback_service.py
│           ├── export_service.py
│           ├── recommendation_service.py
│           ├── activity_service.py
│           └── ...
│
├── frontend/
│   └── src/
│       ├── App.jsx                      # Root component: routing, auth gate,
│       │                                # sidebar, mobile bottom bar, settings
│       ├── contexts/
│       │   └── AuthContext.jsx          # JWT session state, global 401 handler,
│       │                                # multi-tab logout sync
│       ├── api/                         # API client modules per domain
│       │   ├── auth.js                  # Login, register, password reset, token mgmt
│       │   ├── chat.js                  # Chat + streaming consumer
│       │   └── ...
│       └── components/
│           ├── feed/
│           │   ├── ProjectsPage.jsx     # Project list + selector
│           │   ├── DailyPackageView.jsx # Package display + read tracking
│           │   ├── InsightCard.jsx      # Card renderer (all types)
│           │   └── OnboardingModal.jsx  # 3-step new user setup
│           ├── chat/
│           │   ├── ChatWorkspace.jsx    # Main chat interface + stream consumer
│           │   └── ...
│           ├── dashboard/
│           │   └── DashboardPage.jsx    # Stats, heatmap, goal ring
│           ├── bookmarks/
│           │   └── BookmarksPage.jsx
│           ├── landing/
│           │   └── LandingPage.jsx      # Public landing page
│           ├── auth/
│           │   └── AuthPage.jsx         # Login / signup / password reset UI
│           └── GlobalSearch.jsx         # Ctrl+K search overlay
│
├── tests/                               # pytest suite (unit + integration markers)
├── data/
│   └── curivio.db                       # SQLite database (auto-created on first run)
├── Dockerfile                           # Single-container Docker build
├── nginx.conf                           # Reverse proxy config for production
├── start.sh                             # Container entrypoint
├── .env.example                         # All required env var keys with comments
├── pytest.ini                           # Test configuration
└── requiremnts.txt                      # Python dependencies
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Groq API key](https://console.groq.com) — LLM for feed generation and chat
- [Tavily API key](https://tavily.com) — web retrieval for chat modes
- [Brevo account](https://brevo.com) — transactional email for auth (signup verification + password reset)

### 1. Clone the repository

```bash
git clone https://github.com/your-username/ai-learning-agent.git
cd ai-learning-agent
```

### 2. Set up the backend

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requiremnts.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your keys (see [Environment Variables](#environment-variables) for the full table).

Minimum required to run locally:

```env
GROQ_API_KEY=your_groq_api_key
TAVILY_API_KEY=your_tavily_api_key
AUTH_SECRET_KEY=any_32_char_random_string
```

### 4. Start the backend

```bash
uvicorn backend.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.  
Interactive API docs (Swagger UI) are at `http://localhost:8000/docs`.

### 5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The app will be available at `http://localhost:5173`.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | ✅ | — | Groq API key for LLM calls |
| `GROQ_BASE_URL` | ✅ | — | Groq API base URL (e.g. `https://api.groq.com/openai/v1`) |
| `GROQ_MODEL` | | `llama-3.3-70b-versatile` | Model for feed generation + chat |
| `TAVILY_API_KEY` | ✅ | — | Tavily key for web search + extraction |
| `AUTH_SECRET_KEY` | ✅ | — | HS256 secret for JWT signing (32+ chars) |
| `BREVO_API_KEY` | | — | Brevo SMTP API key for transactional email |
| `BREVO_FROM` | | — | Sender address for auth emails |
| `CORS_ORIGINS` | | `http://localhost:5173` | Comma-separated allowed frontend origins |
| `DB_PATH` | | `data/curivio.db` | SQLite file path (set to `/data/curivio.db` on HF Spaces) |
| `HF_TOKEN` | | — | Write-scoped Hugging Face access token, so automatic DB backups can be pushed off-volume to a private HF Hub dataset repo (see [Key Systems In Depth](#key-systems-in-depth)) |
| `BACKUP_HF_REPO_ID` | | — | Target private dataset repo for off-volume backups, e.g. `your-username/curivio-backups` (auto-created on first push) |
| `BACKUP_LOCAL_MAX_SNAPSHOTS` | | `2` | Local snapshots kept in `BACKUP_DIR` — a fast restore path, not the safety net |
| `BACKUP_REMOTE_MAX_SNAPSHOTS` | | `20` | Snapshots kept in the off-volume mirror — the real retention window |
| `BACKUP_INTERVAL_SECONDS` | | `172800` (2 days) | How often the automatic snapshot loop runs |
| `BACKUP_MIN_GAP_SECONDS` | | `3600` | Minimum time since the last snapshot before another automatic one is taken — skips redundant snapshots on a Space that restarts often |
| `BACKUP_QUARANTINE_MAX_FILES` | | `1` | Quarantined `curivio.corrupt-*` files (db.py's corruption self-heal) kept before pruning the oldest |
| `FEED_CACHE_TTL_HOURS` | | `24` | Feed cache lifetime in hours |
| `SCHEDULER_JOB_HOUR` | | `8` | UTC hour for scheduled daily package generation |
| `INSIGHT_GEN_RATE` | | `5/minute` | Rate limit for insight package generation |
| `CHAT_RATE_LIMIT` | | `20/minute` | Rate limit for chat messages |

> **Never commit `.env`.** Use environment injection from your hosting provider in production.

---

## Authentication

Curivio uses a custom JWT-based authentication system — no third-party auth provider.

### How it works

| Concern | Implementation |
|---|---|
| Token format | JWT (HS256) via `python-jose`, 30-day expiry |
| Password storage | `bcrypt` hash — never stored in plain text |
| Token location | Browser `localStorage` (`ra_token` + `ra_user`) |
| Request auth | `Authorization: Bearer <token>` header on every protected request |
| Backend guard | FastAPI `Depends(get_current_user)` on all protected endpoints |
| 401 handling | Global interceptor in `AuthContext.jsx` clears session on any 401 |
| Multi-tab logout | `storage` event listener synchronises logout across tabs |

### Registration flow (two-step)

```
1. POST /auth/send-verify-email  →  6-digit code sent via Brevo (15-min expiry)
2. POST /auth/complete-signup    →  account created, JWT returned
```

### Password reset flow

```
1. POST /auth/forgot-password    →  6-digit reset code sent to email
2. POST /auth/reset-password     →  code validated, password updated, token consumed
```

### Auth endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | — | Direct registration (returns token) |
| `POST` | `/auth/login` | — | Email + password login |
| `GET` | `/auth/me` | ✅ | Returns current user |
| `PUT` | `/auth/me` | ✅ | Update name / email |
| `PUT` | `/auth/me/password` | ✅ | Change password |
| `POST` | `/auth/me/delete` | ✅ | Delete account (cascades all data) |
| `POST` | `/auth/verify-password` | ✅ | Verify current password |
| `POST` | `/auth/forgot-password` | — | Send password reset code |
| `POST` | `/auth/verify-reset-code` | — | Validate reset code |
| `POST` | `/auth/reset-password` | — | Consume code + set new password |
| `POST` | `/auth/send-verify-email` | — | Send signup verification code |
| `POST` | `/auth/complete-signup` | — | Finalise signup after verification |

---

## API Reference

All endpoints are prefixed with the backend URL (default `http://localhost:8000`).  
Protected endpoints (`✅`) require `Authorization: Bearer <token>`.

### Chat

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/chat` | ✅ | Send a message, get full response + recommendations |
| `POST` | `/chat/stream` | ✅ | Stream a response as NDJSON (see [Streaming Protocol](#streaming-protocol)) |
| `GET` | `/chat/sessions` | ✅ | List all sessions with titles |
| `GET` | `/chat/history/{session_id}` | ✅ | Retrieve conversation history |
| `DELETE` | `/chat/history/{session_id}` | ✅ | Clear a session's messages |
| `DELETE` | `/chat/sessions/{session_id}` | ✅ | Delete a session entirely |
| `PUT` | `/chat/sessions/{session_id}/title` | ✅ | Rename a session |

**`/chat/stream` request body:**

```json
{
  "session_id": "abc-123",
  "message": "How does FDA approval create export leverage?",
  "chat_mode": "web_search",
  "feed_context": {
    "action": "continue_research",
    "insight_title": "FDA Approval as Global Trust Certificate",
    "insight_summary": "...",
    "why_it_matters": "...",
    "source_urls": ["https://..."],
    "project_name": "Indian Pharma",
    "project_id": "uuid",
    "current_day": "Day 3",
    "difficulty_level": "intermediate",
    "domain": "pharmaceutical"
  }
}
```

`chat_mode` values: `normal` | `web_search` | `layman`

`feed_context.action` values:

| Value | Effect |
|---|---|
| `ask_about` | No retrieval — card context is sufficient |
| `explain_simply` | Layman mode; mechanism-preservation directive injected |
| `continue_research` | Web search anchored to card's extracted mechanism |

### Learning Projects

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/projects` | ✅ | Create a learning project |
| `GET` | `/projects` | ✅ | List all projects for the current user |
| `GET` | `/projects/{id}` | ✅ | Get a single project |
| `PUT` | `/projects/{id}` | ✅ | Update project settings |
| `DELETE` | `/projects/{id}` | ✅ | Delete project and all its data |
| `POST` | `/projects/{id}/insights/generate` | ✅ | Generate today's intelligence package |
| `GET` | `/projects/{id}/insights` | ✅ | List all packages for a project |
| `GET` | `/projects/{id}/insights/{insight_id}` | ✅ | Get a single package |
| `GET` | `/projects/{id}/progression` | ✅ | Get learning progression state |
| `PUT` | `/projects/{id}/progression` | ✅ | Update progression |

### Research

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/topic-expansion` | ✅ | Get related / prerequisite / advanced topics |
| `POST` | `/learning-path` | ✅ | Generate a structured learning path |
| `POST` | `/repos` | ✅ | Find GitHub repos for a topic |

### Feed & Memory

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/search/global` | ✅ | Search across cards, bookmarks, and sessions |
| `POST` | `/feedback` | ✅ | Submit like / dislike / difficulty feedback |
| `GET` | `/memory` | ✅ | View stored preferences and inferred learning stage |
| `POST` | `/bookmarks` | ✅ | Save a card to bookmarks |
| `GET` | `/bookmarks` | ✅ | List bookmark collections |
| `GET` | `/timeline` | ✅ | Unified intellectual timeline |

---

## Streaming Protocol

`POST /chat/stream` returns NDJSON — one JSON object per line, in this order:

```jsonl
{"t": "status", "v": "Searching the web…"}
{"t": "status", "v": "Ranking results…"}
{"t": "title",  "v": "FDA Approval as Global Trust Signal"}
{"t": "chunk",  "v": "The mechanism behind FDA approval's "}
{"t": "chunk",  "v": "export leverage is not regulatory — it's reputational."}
{"t": "done",   "message_id": 42, "topic_hint": "FDA approval", "chat_mode": "web_search", "sources": [{"title": "...", "url": "..."}], "recommendations": {...}, "tension_scores": {...}}
```

| Event type | When | Key fields |
|---|---|---|
| `status` | Before and during retrieval | `v` — human-readable stage description |
| `title` | First turn of a new session | `v` — extracted session title |
| `chunk` | During token streaming | `v` — incremental text |
| `done` | After stream ends | `message_id`, `chat_mode`, `sources`, `recommendations`, `context_used` |
| `error` | On unrecoverable failure | `message` — error description |

---

## Key Systems In Depth

### Learning Memory & Progression

Every project maintains a `project_learning_memory` record that tracks 9 dimensions across all generated packages:

| Dimension | What it tracks |
|---|---|
| `covered_concepts` | Category/topic labels from all cards (capped at 200) |
| `covered_mechanisms` | Educational card titles — mechanism-level descriptors (100) |
| `covered_industries` | Industries identified in card text (50) |
| `covered_examples` | Proper noun examples: companies, events, people (150) |
| `covered_geographies` | Countries and regions mentioned (50) |
| `covered_narratives` | Narrative frames used across cards (60) |
| `curiosity_angles` | Curiosity card category types used (50) |
| `title_patterns_used` | Rolling 9-category title style history (80) |
| `opening_hooks_used` | First-10-word fingerprints of card summaries (60) |

**Progression stages** advance every 3 packages:  
`foundation` → `mechanisms` → `dependencies` → `optimization` → `geopolitical` → `disruption` → `synthesis`

**Novelty gate**: candidate next topics are filtered through bigram-Jaccard similarity at threshold 0.45 (≈ sentence-embedding cosine 0.82 for short domain phrases) before being passed to the prompt.

### Inter-Article Continuity

Before each package is generated, the system extracts `memory_references` from the last 3 packages:

```python
{
  "priorInsights":        [{"day": "Day 2", "title": "...", "insight": "first sentence of why_it_matters"}],
  "unresolvedQuestions":  [{"day": "Day 1", "question": "curiosity card title"}],
  "nextProgressionGoals": ["stage-specific mandate strings"]
}
```

The prompt mandates that at least one card per package explicitly uses a named callback phrase:  
`"Day 2 established FDA approval as a global trust certificate. Today's pattern shows what happens when that certificate is revoked mid-export."`

### Chat Mode Intelligence

When a feed card is opened in chat, `_enrich_feed_context()` runs before any retrieval:

1. Extracts the card's `mechanism` — first sentence of `why_it_matters`
2. If `project_id` is present, loads project learning memory to get `progression_stage` and `recent_mechanisms`

Each chat mode then uses the mechanism differently:

| Mode | Query strategy |
|---|---|
| `explain_simply` | Mechanism injected into layman directive: "PRESERVE THIS SPECIFIC MECHANISM: …" |
| `web_search` | Query = `"{mechanism} {project} evidence current 2025 examples"` |

### Beginner Calibration

After generating a package for a `beginner`-level project, the system scores jargon density across all card text:

- 28 tracked jargon terms (e.g. "value chain", "regulatory pathway", "competitive dynamics")
- If total occurrences exceed 18, one automatic retry is triggered with a simplification addendum
- Retry falls back to the original if it returns no insight cards

---

## Database Schema

Key tables (SQLite, WAL mode):

```sql
-- User accounts
users (user_id TEXT PK, email TEXT UNIQUE, name TEXT, hashed_pw TEXT, created_at TEXT)

-- Auth tokens
password_reset_tokens (user_id → users, token TEXT UNIQUE, expires_at TEXT, used INTEGER)

-- Learning projects
learning_projects (project_id TEXT PK, user_id → users, name, keywords JSON,
                   difficulty, focus_areas JSON, daily_core_article_count INTEGER, ...)

-- Generated packages (full JSON blob)
project_insights (id INTEGER PK, project_id → learning_projects, day_number INTEGER,
                  insight_json TEXT, generated_at TEXT)

-- Per-project semantic memory
project_learning_memory (project_id PK → learning_projects, covered_concepts JSON,
                         covered_mechanisms JSON, covered_industries JSON,
                         covered_examples JSON, covered_geographies JSON,
                         covered_narratives JSON, curiosity_angles JSON,
                         title_patterns_used JSON, opening_hooks_used JSON,
                         progression_stage TEXT, days_at_stage INTEGER)

-- Chat
chat_messages (id INTEGER PK, session_id TEXT, role TEXT, content TEXT,
               topic_hint TEXT, created_at TEXT)
chat_sessions (session_id TEXT PK, user_id → users, title TEXT,
               conversation_mode TEXT, created_at TEXT)

-- Bookmarks
bookmark_collections (id INTEGER PK, user_id → users, name TEXT, ...)
bookmarks (id INTEGER PK, collection_id → bookmark_collections, card_json TEXT, ...)

-- Learning state
user_preferences (user_id → users, topic TEXT, preference_score REAL, ...)
concept_memory (id INTEGER PK, topic TEXT, session_id TEXT, concepts JSON, ...)
```

Migrations are managed as a `MIGRATIONS` list of `ALTER TABLE ADD COLUMN` statements in [schema.py](backend/database/schema.py). They are idempotent — errors are silently ignored so the list is safe to grow without manual migration tooling.

---

## Running Tests

```bash
# Unit tests only — no external API calls, fast
pytest tests/ -m "not integration" -q

# Verbose output
pytest tests/ -m "not integration" -v

# Integration tests — makes real API calls, uses quota
pytest tests/ -m integration -q

# All tests
pytest tests/ -q
```

---

## Deployment

### Docker (recommended)

```bash
docker build -t curivio .
docker run -p 7860:7860 \
  -e GROQ_API_KEY=... \
  -e TAVILY_API_KEY=... \
  -e AUTH_SECRET_KEY=... \
  -e BREVO_API_KEY=... \
  -e BREVO_FROM=... \
  -e CORS_ORIGINS=https://yourdomain.com \
  -v /your/data/dir:/data \
  curivio
```

The `Dockerfile` builds the frontend and serves everything from a single container via nginx.  
Mount a `/data` volume to persist the SQLite database across restarts.

### Manual deployment

**1. Build the frontend:**

```bash
cd frontend
npm run build
# Output in frontend/dist/
```

**2. Serve with nginx:**

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # Serve the React SPA
    location / {
        root /path/to/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # Proxy API requests to FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**3. Run the backend:**

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### Hugging Face Spaces

Set these Space secrets:

```
GROQ_API_KEY
TAVILY_API_KEY
AUTH_SECRET_KEY
BREVO_API_KEY
BREVO_FROM
DB_PATH=/data/curivio.db
CORS_ORIGINS=https://your-space.hf.space
HF_TOKEN
BACKUP_HF_REPO_ID=your-username/curivio-backups
```

Set `DB_PATH=/data/curivio.db` so the database is stored on the persistent `/data` volume. Without this, the database is recreated on every container restart.

`HF_TOKEN` + `BACKUP_HF_REPO_ID` are optional but strongly recommended: without them, automatic snapshots still work but stay on the same `/data` volume as the live database, so a full loss of that volume takes every backup out with it. `HF_TOKEN` needs write access; `BACKUP_HF_REPO_ID` is created automatically as a private dataset repo on first push.

### Production environment checklist

- [ ] `GROQ_API_KEY` set
- [ ] `TAVILY_API_KEY` set
- [ ] `AUTH_SECRET_KEY` is a strong random string (not a default)
- [ ] `BREVO_API_KEY` + `BREVO_FROM` set (required for user signup + password reset)
- [ ] `CORS_ORIGINS` set to your production domain only
- [ ] `DB_PATH` points to a persistent volume
- [ ] `HF_TOKEN` + `BACKUP_HF_REPO_ID` set (off-volume backups — see above)
- [ ] `.env` is never committed to the repository
