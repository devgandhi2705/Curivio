# Research Agent

An AI-powered daily learning companion — curates structured intelligence briefs from live web sources, lets you dive deep through conversational AI, and tracks your learning progress over time. Fully responsive for mobile and desktop.

## Features

### Intelligence Feed
- **Daily project packages** — create focused learning projects; each generates a structured daily brief with current-events cards and educational deep-dives tailored to your keywords and difficulty level
- **Onboarding flow** — new users are guided through a 3-step setup: pick topics → choose difficulty → create first project; Day 1 is auto-generated immediately
- **Package history** — scroll through previous days; click any past package to re-read it
- **Read Later queue** — save cards to a read-later list and jump back to the exact card from any session
- **Read tracking + generation lock** — mark cards read individually; the "Generate Next Day" button unlocks only after all core cards are read
- **Notes** — write private notes on any card, persisted per project/package
- **Export** — download any daily package as PDF or Markdown
- **Curiosity Picks** — each package includes optional off-beat cards as side trails

### AI Chat
- **Streaming conversational AI** — multi-turn sessions with NDJSON streaming, auto-extracted session titles, and full persistent history
- **Three chat modes** — Normal (memory only), Web Search (live Tavily retrieval), Deep Research (multi-stage workflow with stage-by-stage progress streaming)
- **Auto intent detection** — automatically upgrades the mode based on message phrasing (comparison, research, analysis queries)
- **Feed → Chat integration** — open any feed card directly in chat; choose Ask About, Continue Research, Explain Simply, or Deep Research
- **Adaptive responses** — adjusts depth to your inferred learning stage (early / developing / proficient)
- **Follow-up recommendations** — suggests next topics, prerequisites, and advanced follow-ups after every answer

### Dashboard
- **Stats strip** — streak, cards read today, total cards, packages, and active projects
- **Learning calendar** — 12-month heatmap of daily reading activity per project
- **Weekly goal ring** — set a weekly card-read target; track progress with an animated SVG ring
- **30-day consistency** — dot-grid and percentage showing how consistent your learning habit is
- **Weekday activity chart** — see which days of the week you learn most

### Search & Navigation
- **Global search** — `Ctrl+K` / `⌘K` overlay searches across feed cards, bookmarks, and chat sessions simultaneously
- **Bookmarks** — save cards from the feed; view and manage them in the Bookmarks tab

### Settings
- **Settings panel** — gear icon in the top-right opens a settings dropdown
- **Day/Night mode** — toggle light/dark theme from the settings panel; preference is persisted

### Mobile
- **Bottom navigation bar** — fixed bottom bar with Feed / Chat / Dashboard / Bookmarks icons (shown only on mobile)
- **Mobile project strip** — horizontal scrollable project selector replaces the desktop sidebar on small screens
- **Mobile package strip** — swipe through package history inline when the desktop sidebar is hidden
- **Compact top bar** — search icon + queue icon + settings icon on mobile; full labels on desktop

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11+ |
| AI / LLM | Groq API (Llama 3.3 70b / 3.1 8b Instant) |
| Web search & retrieval | Tavily API (search, extract, crawl strategies) |
| Retrieval routing | Domain classifier → strategy selector → source ranker |
| Database | SQLite (WAL mode) |
| Frontend | React 18, Vite 5, TailwindCSS 3 |
| Rate limiting | SlowAPI |
| Scheduling | APScheduler |

---

## Project Structure

```
ai-learning-agent/
├── backend/
│   ├── main.py                              # FastAPI app + all endpoints
│   ├── config/
│   │   └── retrieval_config.py              # Per-domain retrieval config, RankingWeights
│   ├── database/
│   │   └── schema.py                        # SQLite table definitions
│   ├── prompts/                             # LLM prompt templates
│   └── services/                           # ~50 service modules
│       ├── chat_service.py                  # Chat orchestration (sync + streaming)
│       ├── project_service.py               # Project CRUD + daily package generation
│       ├── intelligence_service.py          # Daily intelligence brief pipeline
│       ├── deep_research_service.py         # Multi-stage deep research workflow
│       ├── retrieval_router.py              # Domain-aware retrieval plan executor
│       ├── tavily_service.py                # Search / extract / crawl strategies
│       ├── source_ranker.py                 # Domain + mode aware article ranking
│       ├── recommendation_service.py        # Preference scoring + stage inference
│       └── ...                              # Supporting services
├── frontend/
│   └── src/
│       ├── App.jsx                          # Root — nav, mobile bottom bar, settings
│       ├── api/                             # API client modules
│       └── components/
│           ├── chat/                        # ChatWorkspace, messages, sessions
│           ├── feed/                        # ProjectsPage, DailyPackageView, InsightCard
│           │                                # OnboardingModal, ProjectCard, LearningCalendar
│           ├── dashboard/                   # DashboardPage with stats + calendar
│           ├── bookmarks/                   # BookmarksPage
│           └── GlobalSearch.jsx             # Ctrl+K search overlay
├── tests/                                   # pytest test suite
├── data/
│   └── memory.db                            # SQLite database (auto-created)
├── .env                                     # Environment variables (never commit)
├── .env.example                             # Template for required variables
└── requiremnts.txt                          # Python dependencies
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- A [Groq API key](https://console.groq.com)
- A [Tavily API key](https://tavily.com)

### 1. Clone and set up the backend

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

pip install -r requiremnts.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=llama-3.3-70b-versatile

TAVILY_API_KEY=your_tavily_api_key_here

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### 3. Start the backend

```bash
uvicorn backend.main:app --reload --port 8000
```

API available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

App available at `http://localhost:5173`.

---

## Deployment

### Build the frontend

```bash
cd frontend
npm run build
# Output goes to frontend/dist/
```

The Vite build splits vendor chunks (React, React Router) automatically. To preview the production build locally:

```bash
npm run preview
```

### Serve with a reverse proxy

Point your web server (nginx, Caddy, etc.) to:
- `/` → `frontend/dist/` (static files)
- `/api` or port proxy → FastAPI backend on port 8000

Example nginx snippet:

```nginx
location / {
    root /path/to/frontend/dist;
    try_files $uri $uri/ /index.html;
}

location /api/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
}
```

### Run the backend in production

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### Environment checklist

- `GROQ_API_KEY` — required
- `TAVILY_API_KEY` — required
- `CORS_ORIGINS` — set to your production domain (e.g., `https://yourdomain.com`)
- Never commit `.env`; use environment injection from your hosting provider

---

## API Overview

### Chat

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/chat` | Send a message, get a full response + recommendations |
| `POST` | `/chat/stream` | Stream a response as NDJSON chunks |
| `GET` | `/chat/sessions` | List all chat sessions with titles |
| `GET` | `/chat/history/{session_id}` | Retrieve conversation history |
| `DELETE` | `/chat/history/{session_id}` | Clear a session's messages |
| `DELETE` | `/chat/sessions/{session_id}` | Delete a session entirely |
| `PUT` | `/chat/sessions/{session_id}/title` | Rename a session |

The `/chat/stream` endpoint accepts an optional `feed_context` field in the request body to inject feed card context directly into the conversation:

```json
{
  "session_id": "...",
  "message": "Tell me more about: DeepSeek-R1",
  "chat_mode": "normal",
  "feed_context": {
    "action": "ask_about",
    "insight_title": "DeepSeek-R1",
    "insight_summary": "...",
    "why_it_matters": "...",
    "source_urls": ["..."],
    "domain": "ai"
  }
}
```

`action` values: `ask_about` (no retrieval), `continue_research` (web search), `deep_research` (full workflow), `explain_simply` (auto-triggered explanation).

### Learning Projects

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/projects` | Create a learning project |
| `GET` | `/projects` | List all projects |
| `PUT` | `/projects/{id}` | Update a project |
| `DELETE` | `/projects/{id}` | Delete a project |
| `POST` | `/projects/{id}/insights/generate` | Generate today's intelligence package |
| `GET` | `/projects/{id}/insights` | List all packages for a project |
| `GET` | `/projects/{id}/progression` | Get learning progression |
| `PUT` | `/projects/{id}/progression` | Update progression |

### Research

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/deep-research` | Run or retrieve deep research on a topic |
| `POST` | `/topic-expansion` | Get related/prereq/advanced topics |
| `POST` | `/learning-path` | Generate a structured learning path |
| `POST` | `/repos` | Find GitHub repos for a topic |

### Feed & Memory

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/search/global` | Global search across cards, bookmarks, and chat sessions |
| `POST` | `/feedback` | Submit like/dislike/difficulty feedback |
| `GET` | `/memory` | View stored preferences and learning stage |
| `GET` | `/timeline` | Unified intellectual timeline |

---

## Streaming Protocol

`POST /chat/stream` returns NDJSON — one JSON object per line:

```
{"t": "status", "v": "Searching the web…"}
{"t": "title",  "v": "DeepSeek vs GPT-4"}
{"t": "chunk",  "v": "DeepSeek-R1 is a ..."}
{"t": "chunk",  "v": "reasoning model ..."}
{"t": "done",   "message_id": 42, "topic_hint": "DeepSeek", "chat_mode": "web_search", "sources": [...], "recommendations": {...}}
```

For `deep_research` mode, multiple `status` events arrive as each stage completes.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** Groq API key |
| `GROQ_BASE_URL` | — | **Required.** Groq API base URL |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Model for chat and feed generation |
| `TAVILY_API_KEY` | — | **Required.** Tavily search/extract/crawl key |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed frontend origins (comma-separated) |
| `FEED_CACHE_TTL_HOURS` | `24` | Feed cache lifetime in hours |
| `SCHEDULER_JOB_HOUR` | `8` | UTC hour for daily package generation |
| `INSIGHT_GEN_RATE` | `5/minute` | Rate limit for insight package generation |
| `CHAT_RATE_LIMIT` | `20/minute` | Rate limit for chat messages |

---

## Running Tests

```bash
# Unit tests only (no API calls)
pytest tests/ -m "not integration" -q

# Verbose
pytest tests/ -m "not integration" -v

# Integration tests (makes real API calls — uses quota)
pytest tests/ -m integration -q
```
