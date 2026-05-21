"""
Application configuration — edit this file to tune non-secret settings.
Secrets (API keys, passwords) must stay in .env / HF Spaces secrets only.
"""

import os

# ── AI Model ──────────────────────────────────────────────────────────────────
GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# ── Rate limits ───────────────────────────────────────────────────────────────
# Format: "count/period"  — period: second, minute, hour, day
GENERATE_FEED_RATE_LIMIT  = "5/minute"
SEARCH_RATE_LIMIT         = "3/minute"
FEEDBACK_RATE_LIMIT       = "10/minute"
MEMORY_RATE_LIMIT         = "30/minute"
CHAT_RATE_LIMIT           = "20/minute"
PROJECTS_RATE_LIMIT       = "30/minute"
INSIGHT_GEN_RATE          = "5/minute"
BOOKMARKS_RATE_LIMIT      = "60/minute"
TRIGGER_ALL_PROJECTS_RATE = "2/minute"

# ── Cache TTLs (hours) ────────────────────────────────────────────────────────
FEED_CACHE_TTL_HOURS       = 24
SEARCH_CACHE_TTL_HOURS     = 6
DEEP_RESEARCH_TTL_HOURS    = 48
TOPIC_EXPANSION_TTL_HOURS  = 72
INDUSTRY_BRIEF_TTL_HOURS   = 12
LEARNING_PATH_TTL_HOURS    = 48
GITHUB_REPOS_TTL_HOURS     = 24

# ── Deep research ─────────────────────────────────────────────────────────────
DEEP_RESEARCH_SEARCH_COUNT        = 4
DEEP_RESEARCH_LIKE_THRESHOLD      = 1
DEEP_RESEARCH_SCORE_THRESHOLD     = 0.5
DEEP_RESEARCH_RECOMMEND_THRESHOLD = 3

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_MAX_REPOS = 25
GITHUB_MIN_STARS = 50

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_TOKEN_EXPIRE_DAYS = 30

# ── Deployment-specific ───────────────────────────────────────────────────────
# These differ between local dev and production — override via environment variable.
# HF Spaces: set APP_URL and CORS_ORIGINS in the Spaces settings (not as secrets).
APP_URL      = os.getenv("APP_URL",      "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
