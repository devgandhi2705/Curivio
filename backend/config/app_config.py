"""
Application configuration — edit this file to tune non-secret settings.
Secrets (API keys, passwords) must stay in .env / HF Spaces secrets only.
"""

import os

# ── AI Model ──────────────────────────────────────────────────────────────────
GROQ_MODEL    = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Unpack (select-to-explain). Groq primary, Gemini fallback — see
# unpack-feature-spec.md. Groq's free-tier lineup churns; re-check
# https://console.groq.com/docs/deprecations before changing GROQ_UNPACK_MODEL.
GROQ_UNPACK_MODEL   = "openai/gpt-oss-120b"
# Was "models/gemini-2.5-flash-lite" — confirmed live 404 "no longer available
# to new users" for at least one pooled key/project (real, per-project access
# restriction, not a universal deprecation — model metadata still resolves
# fine). "-latest" confirmed live-reachable across all 3 pooled keys.
GEMINI_UNPACK_MODEL = "models/gemini-flash-lite-latest"

# ── LangChain provider layer (backend/llm/) ─────────────────────────────────────
# Additive, parallel to the existing hand-rolled Groq/Gemini call sites above —
# not read by grok_service.py / journey_planner_service.py / writer_provider_router.py.
GEMINI_MODEL          = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "models/gemini-3.1-flash-lite")
# Same model as GROQ_MODEL today; decoupled so this leg can change independently.
GROQ_FALLBACK_MODEL   = os.getenv("GROQ_FALLBACK_MODEL", GROQ_MODEL)
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")

# Task-based model priority registry (backend/llm/model_priority.py, Chat-R3).
# Lightweight Gemini tier for high-volume/low-stakes tasks (routing) — same
# model family as GEMINI_UNPACK_MODEL but a separate knob so routing and
# unpack can be tuned independently.
# Was "models/gemini-2.5-flash-lite" — confirmed live 404 "no longer available
# to new users" for at least one pooled key/project (see GEMINI_UNPACK_MODEL
# above, same underlying issue). "-latest" confirmed live-reachable.
GEMINI_LITE_MODEL = os.getenv("GEMINI_LITE_MODEL", "models/gemini-flash-lite-latest")
# Groq's fastest/cheapest on-demand model — 20,000 tpm vs 12,000 tpm for
# llama-3.3-70b-versatile (see backend/services/model_registry.py tier_limits).
GROQ_FAST_MODEL       = os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant")

# ── Attachment storage (Chat-R13/R14a) ───────────────────────────────────────
# Original-bytes retention window for R2-backed chat attachments (raw file
# bytes only — extracted text/embeddings in document_chunks_vec are permanent
# and untouched by this). One knob for every type, editable here or via env,
# no R2 dashboard/lifecycle-rule dependency (R12: this credential can't manage
# lifecycle config anyway — see r2_storage_service.py).
ATTACHMENT_RETENTION_DAYS = int(os.getenv("ATTACHMENT_RETENTION_DAYS", "30"))

# App-level cap on /chat/upload, well under Gemini's own 2GB Files API ceiling
# (that ceiling only applies to images anyway — R2-backed types have no such
# limit). Raised from a hardcoded 20MB (R6a/R12) to int-from-env so it's a
# one-line change without a redeploy.
CHAT_UPLOAD_MAX_BYTES = int(os.getenv("CHAT_UPLOAD_MAX_BYTES", str(50 * 1024 * 1024)))

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
UNPACK_RATE_LIMIT         = "30/minute"
CHAT_UPLOAD_RATE_LIMIT    = "10/minute"
# Credential/code-guessing endpoints (login, code verification) — same tier as
# GENERATE_FEED/INSIGHT_GEN, the app's existing strictest bucket.
AUTH_STRICT_RATE_LIMIT    = "5/minute"
# Initiate-only auth endpoints (register, forgot-password, send-verify-email) —
# bounded against spam/enumeration without blocking normal use.
AUTH_LOOSE_RATE_LIMIT     = "10/minute"

# ── Cache TTLs (hours) ────────────────────────────────────────────────────────
FEED_CACHE_TTL_HOURS       = 24
SEARCH_CACHE_TTL_HOURS     = 6
DEEP_RESEARCH_TTL_HOURS    = 48
TOPIC_EXPANSION_TTL_HOURS  = 72
INDUSTRY_BRIEF_TTL_HOURS   = 12
LEARNING_PATH_TTL_HOURS    = 48
GITHUB_REPOS_TTL_HOURS     = 24
UNPACK_CACHE_TTL_HOURS     = 720  # 30 days — definitions/translations don't go stale like news

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
# Comma-separated allowlist of admin emails. Same shape as CORS_ORIGINS below.
ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "")

# ── Feature flags ────────────────────────────────────────────────────────────
# Phase 9.3.4C: replace single LLM call with N writer calls + merge.
# Default False — single-call path unchanged until explicitly enabled.
MULTI_CALL_GENERATION: bool = True

# Phase 9.3.4F: cross-batch validation & grounding integrity audit.
# Audit-only — failures log warnings but never block package generation.
PACKAGE_VALIDATION_ENABLED: bool = True

# ── Deployment-specific ───────────────────────────────────────────────────────
# These differ between local dev and production — override via environment variable.
# HF Spaces: set APP_URL and CORS_ORIGINS in the Spaces settings (not as secrets).
APP_URL      = os.getenv("APP_URL",      "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS") or "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
