import json
import os
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from . import config as cfg

import logging
from contextlib import asynccontextmanager
from botocore.exceptions import ClientError
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator, model_validator
from typing import Literal, Optional

logger = logging.getLogger(__name__)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .services.curator_service import generate_learning_feed
from .services.intelligence_service import (
    generate_intelligence_feed,
    get_recent_intelligence_feeds,
)
from .services.topic_cluster import assign_category
from .services.tavily_service import search_articles
from .services.feedback_service import process_feedback
from .services.api_usage_service import (
    get_usage_stats,
    get_daily_summary,
    get_recent_calls,
)
from .services.deep_research_service import (
    is_important_topic,
    get_stored_research,
    list_research_topics,
    run_deep_research,
)
from .services.topic_expansion_service import (
    expand_topic,
    get_stored_expansion,
    list_expansions,
)
from .services.learning_path_service import (
    get_learning_path,
    get_stored_path,
    list_learning_paths,
)
from .services.github_service import (
    get_topic_repos,
    list_repo_topics,
    _get_stored_repos,
)
from .services.resource_categorizer import (
    categorize_resources,
)
from .services.exploration_trigger_service import (
    evaluate_exploration,
)
from .services.session_memory_service import record_activity
from .services.auth_service import (
    register_user,
    login_user,
    update_profile,
    change_password,
    delete_account,
    get_current_user,
    get_current_admin_user,
    check_current_password,
    create_reset_token,
    verify_reset_code,
    consume_reset_token,
    create_signup_verification,
    complete_signup_verification,
)
from .services.chat_service import (
    chat_stream as chat_stream_generator,
    get_history as get_chat_history,
    clear_history as clear_chat_history,
    list_sessions as list_chat_sessions,
)
from .utils.db import init_db, DB_PATH
from .services.digest_storage_service import (
    get_latest_digest,
    get_digest_by_id,
    get_digests_by_date,
    list_digests,
)
from .services.unpack_service import explain_stream
from .services.translate_service import translate_term
from .services.tts_service import synthesize_speech
from .services import document_extraction_service, document_memory_service

# --- Rate limits (edit in backend/config.py) ---
GENERATE_FEED_RATE_LIMIT = cfg.GENERATE_FEED_RATE_LIMIT
SEARCH_RATE_LIMIT        = cfg.SEARCH_RATE_LIMIT
FEEDBACK_RATE_LIMIT      = cfg.FEEDBACK_RATE_LIMIT
MEMORY_RATE_LIMIT        = cfg.MEMORY_RATE_LIMIT
UNPACK_RATE_LIMIT        = cfg.UNPACK_RATE_LIMIT
CHAT_UPLOAD_RATE_LIMIT   = cfg.CHAT_UPLOAD_RATE_LIMIT
AUTH_STRICT_RATE_LIMIT   = cfg.AUTH_STRICT_RATE_LIMIT
AUTH_LOOSE_RATE_LIMIT    = cfg.AUTH_LOOSE_RATE_LIMIT

limiter = Limiter(key_func=get_remote_address)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Warn about missing API keys but don't block startup
    _missing = [k for k in ("GROQ_API_KEY", "TAVILY_API_KEY") if not os.getenv(k)]
    if _missing:
        logger.warning("[startup] Missing env vars: %s — some features will not work", _missing)

    # Ensure temp and data directories exist
    Path("/tmp/curivio").mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # One-time migration: rename legacy memory.db → curivio.db (same /data dir)
    _legacy_db = DB_PATH.parent / "memory.db"
    if _legacy_db.exists() and not DB_PATH.exists() and _legacy_db != DB_PATH:
        import shutil
        shutil.copy2(_legacy_db, DB_PATH)
        logger.info("[db] Migrated existing DB: %s → %s", _legacy_db, DB_PATH)

    # Log DB state before init so issues are visible in HF Spaces logs
    _db_existed = DB_PATH.exists()
    _db_size    = DB_PATH.stat().st_size if _db_existed else 0
    logger.info("[db] path=%s  pre-exists=%s  size=%d bytes", DB_PATH, _db_existed, _db_size)
    if str(DB_PATH).startswith("/data"):
        logger.info("[db] Persistent storage confirmed — data will survive container restarts")
    else:
        logger.warning("[db] DB is NOT under /data — data will be LOST on rebuild/restart! "
                       "Set DB_PATH=/data/curivio.db in HF Spaces variables.")

    init_db()

    _db_size_after = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    logger.info("[db] init_db() complete — size now %d bytes", _db_size_after)

    # Backfill intent profiles for existing projects that pre-date the intent architecture.
    # Runs in a daemon thread so startup is not blocked.
    import threading as _threading
    def _backfill():
        try:
            from .services.intent_profile_service import backfill_intent_profiles
            result = backfill_intent_profiles()
            if result["total"] > 0:
                logger.info("[startup] intent profile backfill: %s", result)
        except Exception as _exc:
            logger.warning("[startup] intent profile backfill failed (non-fatal): %s", _exc)
    _threading.Thread(target=_backfill, daemon=True, name="intent-backfill").start()

    yield

app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- CORS (edit APP_URL / CORS_ORIGINS in backend/config.py or as env vars) ---
CORS_ORIGINS = [o.strip() for o in cfg.CORS_ORIGINS.split(",") if o.strip()]
print(f"[CORS] allow_origins resolved to: {CORS_ORIGINS}", flush=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _debug_cors(request: Request, call_next):
    if request.method == "OPTIONS":
        print(f"[CORS DEBUG] origin={request.headers.get('origin')!r} path={request.url.path}", flush=True)
    response = await call_next(request)
    if request.method == "OPTIONS":
        print(f"[CORS DEBUG] response status={response.status_code}", flush=True)
    return response


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


from .routes.admin import router as admin_router
app.include_router(admin_router)


# --- Request models ---

class UserInput(BaseModel):
    interests: str


class UnpackExplainRequest(BaseModel):
    term: str
    sentence: str = ""
    prev_sentence: str = ""
    next_sentence: str = ""


class UnpackTranslateRequest(BaseModel):
    term: str
    target_language: Literal["hi", "gu", "fr", "de"]


class UnpackReadAloudRequest(BaseModel):
    term: str


# --- Feed models ---

class NewsInsight(BaseModel):
    title: str
    summary: str
    why_it_matters: str
    sources: list[str]

class LearningTopic(BaseModel):
    title: str
    reason: str
    difficulty: Literal["beginner", "intermediate", "advanced"]
    category: str = "General ML"   # computed post-LLM; not generated by the model

class Perspectives(BaseModel):
    common_themes: list[str]
    synthesis: str
    notable_tension: str | None = None

class LearningFeed(BaseModel):
    news_insight: NewsInsight
    perspectives: Perspectives | None = None
    learning_topics: list[LearningTopic]
    next_step: str

    @field_validator("learning_topics")
    @classmethod
    def must_have_four_topics(cls, v):
        if len(v) != 4:
            raise ValueError(f"Expected 4 learning topics, got {len(v)}")
        return v


# --- Intelligence Feed models ---

class IntelligenceItem(BaseModel):
    title:          str
    insight:        str
    why_it_matters: str
    sources:        list[str] = []


class IntelligenceSection(BaseModel):
    type:  str
    title: str
    items: list[IntelligenceItem]


class IntelligenceBriefModel(BaseModel):
    headline:          str
    executive_summary: str
    key_signals:       list[str]


class LearningTrackItem(BaseModel):
    title:           str
    reason:          str
    difficulty:      Literal["beginner", "intermediate", "advanced"]
    chat_connection: str | None = None
    category:        str = "General ML"


class IntelligenceFeedResponse(BaseModel):
    # New intelligence fields
    intelligence_brief: IntelligenceBriefModel
    sections:           list[IntelligenceSection]
    learning_track:     list[LearningTrackItem]
    action_items:       list[str]
    industry_context:   str = ""
    # Backward-compat fields (populated by _add_compat_fields in intelligence_service)
    news_insight:    NewsInsight     | None = None
    perspectives:    Perspectives    | None = None
    learning_topics: list[LearningTopic]   = []
    next_step:       str                   = ""


# --- Feedback models ---

class FeedbackRequest(BaseModel):
    topic: str
    feedback: Literal["liked", "disliked", "too_advanced", "too_basic"]

class FeedbackResponse(BaseModel):
    topic: str
    feedback: str
    message: str
    preference_score: float
    difficulty_preference: str | None
    times_liked: int
    times_disliked: int
    times_recommended: int
    last_updated: str


# --- Search models ---

class SearchRequest(BaseModel):
    query: str

class SearchResult(BaseModel):
    title: str
    url: str
    content: str

class SearchResponse(BaseModel):
    results: list[SearchResult]


# --- API usage models ---

class ApiUsageSummary(BaseModel):
    period_days: int
    total_calls: int
    cache_hits: int
    cache_hit_rate: float
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    by_service: dict
    daily: list[dict]
    recent_calls: list[dict]


# --- Deep research models ---

class DeepResearchRequest(BaseModel):
    topic: str

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("topic must not be blank")
        return v.strip()

class DeepResearchResult(BaseModel):
    topic: str
    related_concepts: list[str]
    implementation_ideas: list[str]
    practical_applications: list[str]
    advanced_follow_ups: list[str]
    research_summary: str
    sources: list[str]
    generated_at: str

class DeepResearchSummary(BaseModel):
    id: int
    topic: str
    generated_at: str


# --- Routes ---

@app.get("/")
def home():
    return {"message": "AI Learning Agent Running"}


# ─────────────────────────────────────────────────────────────────────────────
# Auth endpoints
# ─────────────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    name:  str
    password: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name is required")
        return v.strip()


class LoginRequest(BaseModel):
    email:    str
    password: str


class UpdateProfileRequest(BaseModel):
    name:  Optional[str] = None
    email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password:     str


class DeleteAccountRequest(BaseModel):
    password: str


class VerifyPasswordRequest(BaseModel):
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class VerifyResetCodeRequest(BaseModel):
    email: str
    code:  str


class ResetPasswordRequest(BaseModel):
    email:        str
    code:         str
    new_password: str


class SendVerifyEmailRequest(BaseModel):
    email:    str
    name:     str
    password: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name is required")
        return v.strip()


class CompleteSignupRequest(BaseModel):
    email: str
    code:  str


@app.post("/auth/register", status_code=201)
@limiter.limit(AUTH_LOOSE_RATE_LIMIT)
async def auth_register(request: Request, data: RegisterRequest):
    return register_user(data.email, data.name, data.password)


@app.post("/auth/login")
@limiter.limit(AUTH_STRICT_RATE_LIMIT)
async def auth_login(request: Request, data: LoginRequest):
    return login_user(data.email, data.password)


@app.get("/auth/me")
async def auth_me(current_user: dict = Depends(get_current_user)):
    return current_user


@app.put("/auth/me")
async def auth_update_profile(
    data: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
):
    return update_profile(current_user["user_id"], data.name, data.email)


@app.put("/auth/me/password")
async def auth_change_password(
    data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    change_password(current_user["user_id"], data.current_password, data.new_password)
    return {"ok": True}


@app.post("/auth/me/delete")
async def auth_delete_account(
    data: DeleteAccountRequest,
    current_user: dict = Depends(get_current_user),
):
    delete_account(current_user["user_id"], data.password)
    return {"ok": True}


@app.post("/auth/verify-password")
async def auth_verify_password(
    data: VerifyPasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    if not check_current_password(current_user["user_id"], data.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    return {"valid": True}


@app.post("/auth/forgot-password")
@limiter.limit(AUTH_LOOSE_RATE_LIMIT)
async def auth_forgot_password(request: Request, data: ForgotPasswordRequest):
    create_reset_token(data.email)
    return {"ok": True}


@app.post("/auth/verify-reset-code")
@limiter.limit(AUTH_STRICT_RATE_LIMIT)
async def auth_verify_reset_code(request: Request, data: VerifyResetCodeRequest):
    verify_reset_code(data.email, data.code)
    return {"ok": True}


@app.post("/auth/reset-password")
@limiter.limit(AUTH_STRICT_RATE_LIMIT)
async def auth_reset_password(request: Request, data: ResetPasswordRequest):
    consume_reset_token(data.email, data.code, data.new_password)
    return {"ok": True}


@app.post("/auth/send-verify-email")
@limiter.limit(AUTH_LOOSE_RATE_LIMIT)
async def auth_send_verify_email(request: Request, data: SendVerifyEmailRequest):
    create_signup_verification(data.email, data.name, data.password)
    return {"ok": True}


@app.post("/auth/complete-signup", status_code=201)
@limiter.limit(AUTH_STRICT_RATE_LIMIT)
async def auth_complete_signup(request: Request, data: CompleteSignupRequest):
    return complete_signup_verification(data.email, data.code)


@app.post("/generate-feed", response_model=IntelligenceFeedResponse)
@limiter.limit(GENERATE_FEED_RATE_LIMIT)
async def generate_feed(request: Request, data: UserInput):
    result = generate_intelligence_feed(data.interests)
    for topic in result.get("learning_track", []):
        topic["category"] = assign_category(topic.get("title", ""))
    for topic in result.get("learning_topics", []):
        topic["category"] = assign_category(topic.get("title", ""))
    return IntelligenceFeedResponse(**result)


@app.get("/intelligence-feeds")
@limiter.limit(MEMORY_RATE_LIMIT)
async def list_intelligence_feeds(request: Request, limit: int = 20):
    """Return metadata for recent intelligence feed generations."""
    return get_recent_intelligence_feeds(limit=limit)


def _auto_research(topic: str, user_id: str) -> None:
    """Background task wrapper — errors are logged, never re-raised."""
    try:
        run_deep_research(topic)
        try:
            record_activity(topic, "deep_research", user_id)
        except Exception:
            logger.warning("[session_memory] record failed for deep_research %r", topic)
    except Exception:
        logger.exception("[deep_research] background task failed for topic %r", topic)


@app.post("/feedback", response_model=FeedbackResponse)
@limiter.limit(FEEDBACK_RATE_LIMIT)
async def feedback(
    request: Request, data: FeedbackRequest, background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    result = process_feedback(data.topic, data.feedback, current_user["user_id"])
    decision = evaluate_exploration(data.topic)
    if decision.should_explore:
        background_tasks.add_task(_auto_research, data.topic, current_user["user_id"])
    return FeedbackResponse(**result)


@app.post("/search", response_model=SearchResponse)
@limiter.limit(SEARCH_RATE_LIMIT)
async def search(request: Request, data: SearchRequest):
    raw = search_articles(data.query)
    return SearchResponse(results=[SearchResult(**r) for r in raw])


@app.get("/search/global")
@limiter.limit(SEARCH_RATE_LIMIT)
async def global_search_endpoint(
    request: Request,
    q: str = "",
    limit: int = 5,
    current_user: dict = Depends(get_current_user),
):
    """
    Search across project insight cards, bookmarks, and chat messages in one shot.
    Returns up to `limit` results per section (max 10).
    """
    from .services.search_service import global_search
    return global_search(q, limit_per_section=min(max(limit, 1), 10), user_id=current_user["user_id"])


@app.get("/api-usage", response_model=ApiUsageSummary)
@limiter.limit(MEMORY_RATE_LIMIT)
async def api_usage_stats(request: Request, days: int = 7):
    stats  = get_usage_stats(days=days)
    daily  = get_daily_summary(days=days)
    recent = get_recent_calls(limit=20)
    return ApiUsageSummary(period_days=days, **stats, daily=daily, recent_calls=recent)


# --- Deep research routes (list before /{topic} so exact path wins) ---

@app.get("/deep-research", response_model=list[DeepResearchSummary])
@limiter.limit(MEMORY_RATE_LIMIT)
async def list_deep_research(request: Request, limit: int = 20):
    return [DeepResearchSummary(**r) for r in list_research_topics(limit=limit)]


@app.post("/deep-research", response_model=DeepResearchResult)
@limiter.limit(FEEDBACK_RATE_LIMIT)
async def trigger_deep_research(
    request: Request, data: DeepResearchRequest,
    current_user: dict = Depends(get_current_user),
):
    cached = get_stored_research(data.topic)
    if cached:
        return DeepResearchResult(**cached)
    result = run_deep_research(data.topic)
    try:
        record_activity(data.topic, "deep_research", current_user["user_id"])
    except Exception:
        logger.warning("[session_memory] record failed for deep_research %r", data.topic)
    return DeepResearchResult(**result)


@app.get("/deep-research/{topic}", response_model=DeepResearchResult)
@limiter.limit(MEMORY_RATE_LIMIT)
async def get_deep_research(request: Request, topic: str):
    result = get_stored_research(topic)
    if result is None:
        raise HTTPException(status_code=404, detail="No deep research found for this topic")
    return DeepResearchResult(**result)


# --- Topic selection models ---

class TopicSelectionRequest(BaseModel):
    topics: list[str]

    @field_validator("topics")
    @classmethod
    def validate_count(cls, v):
        if not v:
            raise ValueError("Select at least 1 topic.")
        if len(v) > 2:
            raise ValueError("Cannot select more than 2 topics.")
        if len(v) != len(set(v)):
            raise ValueError("Duplicate topics are not allowed.")
        return v

class TopicSelectionResult(BaseModel):
    topic: str
    preference_score: float
    times_liked: int
    times_recommended: int
    difficulty_preference: str | None

class TopicSelectionResponse(BaseModel):
    selected: list[TopicSelectionResult]
    message: str


# --- Topic selection route ---

@app.post("/select-topics", response_model=TopicSelectionResponse)
@limiter.limit(FEEDBACK_RATE_LIMIT)
async def select_topics(
    request: Request, data: TopicSelectionRequest,
    current_user: dict = Depends(get_current_user),
):
    results = []
    for topic in data.topics:
        updated = process_feedback(topic, "liked", current_user["user_id"])
        results.append(TopicSelectionResult(
            topic=updated["topic"],
            preference_score=updated["preference_score"],
            times_liked=updated["times_liked"],
            times_recommended=updated["times_recommended"],
            difficulty_preference=updated["difficulty_preference"],
        ))
    return TopicSelectionResponse(
        selected=results,
        message=f"{len(results)} topic{'s' if len(results) > 1 else ''} added to your learning plan.",
    )


# --- Digest models ---

class DigestTopic(BaseModel):
    title: str
    reason: str
    difficulty: Literal["beginner", "intermediate", "advanced"]

class DigestResponse(BaseModel):
    id: int
    generated_at: str
    news_title: str
    news_summary: str
    why_it_matters: str
    learning_topics: list[DigestTopic]
    next_step: str
    source_links: list[str]
    source: str

class DigestSummary(BaseModel):
    id: int
    generated_at: str
    news_title: str
    source: str


def _digest_to_response(d: dict) -> DigestResponse:
    return DigestResponse(
        id=d["id"],
        generated_at=d["generated_at"],
        news_title=d["news_title"],
        news_summary=d["news_summary"],
        why_it_matters=d["why_it_matters"],
        learning_topics=[DigestTopic(**t) for t in d["learning_topics"]],
        next_step=d["next_step"],
        source_links=d["source_links"],
        source=d["source"],
    )


# --- Digest routes ---

@app.get("/digests/latest", response_model=DigestResponse | None)
@limiter.limit(MEMORY_RATE_LIMIT)
async def digests_latest(request: Request):
    d = get_latest_digest()
    return _digest_to_response(d) if d else None


@app.get("/digests/{digest_id}", response_model=DigestResponse)
@limiter.limit(MEMORY_RATE_LIMIT)
async def digest_by_id(request: Request, digest_id: int):
    from fastapi import HTTPException
    d = get_digest_by_id(digest_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Digest not found")
    return _digest_to_response(d)


@app.get("/digests", response_model=list[DigestResponse])
@limiter.limit(MEMORY_RATE_LIMIT)
async def digests_list(request: Request, date: str | None = None, limit: int = 20):
    if date:
        rows = get_digests_by_date(date)
    else:
        rows = list_digests(limit=limit)
    return [_digest_to_response(d) for d in rows]


# --- Topic expansion models ---

class TopicExpansionRequest(BaseModel):
    topic: str

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("topic must not be blank")
        return v.strip()

class TopicExpansionResult(BaseModel):
    topic: str
    prerequisites: list[str]
    related_topics: list[str]
    advanced_follow_ups: list[str]
    learning_progression: list[str]
    progression_rationale: str
    generated_at: str

class TopicExpansionSummary(BaseModel):
    id: int
    topic: str
    generated_at: str


# --- Topic expansion routes (list before /{topic} so exact path wins) ---

@app.get("/topic-expansion", response_model=list[TopicExpansionSummary])
@limiter.limit(MEMORY_RATE_LIMIT)
async def list_topic_expansions(request: Request, limit: int = 20):
    return [TopicExpansionSummary(**r) for r in list_expansions(limit=limit)]


@app.post("/topic-expansion", response_model=TopicExpansionResult)
@limiter.limit(FEEDBACK_RATE_LIMIT)
async def trigger_topic_expansion(
    request: Request, data: TopicExpansionRequest,
    current_user: dict = Depends(get_current_user),
):
    result = expand_topic(data.topic)
    try:
        record_activity(data.topic, "topic_expansion", current_user["user_id"])
    except Exception:
        logger.warning("[session_memory] record failed for topic_expansion %r", data.topic)
    return TopicExpansionResult(**result)


@app.get("/topic-expansion/{topic}", response_model=TopicExpansionResult)
@limiter.limit(MEMORY_RATE_LIMIT)
async def get_topic_expansion(request: Request, topic: str):
    result = get_stored_expansion(topic)
    if result is None:
        raise HTTPException(status_code=404, detail="No expansion found for this topic")
    return TopicExpansionResult(**result)


# --- Repo discovery models ---

class RepoResult(BaseModel):
    name: str
    description: str
    stars: int
    url: str
    language: str | None = None
    topics: list[str] = []

class RepoDiscoveryRequest(BaseModel):
    topic: str

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("topic must not be blank")
        return v.strip()

class RepoDiscoveryResponse(BaseModel):
    topic: str
    repositories: list[RepoResult]

class RepoTopicSummary(BaseModel):
    id: int
    topic: str
    fetched_at: str


# --- Learning path models ---

class LearningPathRequest(BaseModel):
    topic: str

    @field_validator("topic")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("topic must not be blank")
        return v.strip()

class LearningStep(BaseModel):
    concept: str
    explanation: str
    why_it_matters: str
    resources: list[str]

class LearningPathResult(BaseModel):
    topic: str
    learning_stage: str
    beginner: list[LearningStep]
    intermediate: list[LearningStep]
    advanced: list[LearningStep]
    repositories: list[RepoResult] = []
    generated_at: str

class LearningPathSummary(BaseModel):
    id: int
    topic: str
    learning_stage: str
    generated_at: str


# --- Repo discovery routes (list before /{topic}) ---

@app.get("/repos", response_model=list[RepoTopicSummary])
@limiter.limit(MEMORY_RATE_LIMIT)
async def list_repo_topics_endpoint(request: Request, limit: int = 20):
    return [RepoTopicSummary(**r) for r in list_repo_topics(limit=limit)]


@app.post("/repos", response_model=RepoDiscoveryResponse)
@limiter.limit(FEEDBACK_RATE_LIMIT)
async def discover_repos(
    request: Request, data: RepoDiscoveryRequest,
    current_user: dict = Depends(get_current_user),
):
    repos = get_topic_repos(data.topic)
    try:
        record_activity(data.topic, "github_repos", current_user["user_id"])
    except Exception:
        logger.warning("[session_memory] record failed for github_repos %r", data.topic)
    return RepoDiscoveryResponse(topic=data.topic, repositories=[RepoResult(**r) for r in repos])


@app.get("/repos/{topic}", response_model=RepoDiscoveryResponse)
@limiter.limit(MEMORY_RATE_LIMIT)
async def get_repos_by_topic(request: Request, topic: str):
    repos = _get_stored_repos(topic)
    if repos is None:
        raise HTTPException(status_code=404, detail="No cached repos found for this topic")
    return RepoDiscoveryResponse(topic=topic, repositories=[RepoResult(**r) for r in repos])


# --- Learning path routes (list before /{topic} so exact path wins) ---

@app.get("/learning-path", response_model=list[LearningPathSummary])
@limiter.limit(MEMORY_RATE_LIMIT)
async def list_paths(request: Request, limit: int = 20):
    return [LearningPathSummary(**r) for r in list_learning_paths(limit=limit)]


@app.post("/learning-path", response_model=LearningPathResult)
@limiter.limit(FEEDBACK_RATE_LIMIT)
async def trigger_learning_path(
    request: Request, data: LearningPathRequest,
    current_user: dict = Depends(get_current_user),
):
    result = get_learning_path(data.topic)
    try:
        result["repositories"] = get_topic_repos(data.topic)
    except Exception:
        logger.warning("[learning_path] repo fetch failed for topic %r", data.topic)
        result.setdefault("repositories", [])
    try:
        record_activity(data.topic, "learning_path", current_user["user_id"])
    except Exception:
        logger.warning("[session_memory] record failed for learning_path %r", data.topic)
    return LearningPathResult(**result)


@app.get("/learning-path/{topic}", response_model=LearningPathResult)
@limiter.limit(MEMORY_RATE_LIMIT)
async def get_path_by_topic(request: Request, topic: str):
    result = get_stored_path(topic)
    if result is None:
        raise HTTPException(status_code=404, detail="No learning path found for this topic")
    result.setdefault("repositories", [])
    return LearningPathResult(**result)


# --- Categorization models ---

class CategorizedResource(BaseModel):
    resource: str
    category: Literal[
        "tutorial", "research_paper", "github_repository",
        "documentation", "blog_post", "video",
    ]
    confidence: float

class CategorizationRequest(BaseModel):
    resources: list[str]

    @field_validator("resources")
    @classmethod
    def must_not_be_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("resources list must not be empty")
        return v

class CategorizationResponse(BaseModel):
    results: list[CategorizedResource]
    summary: dict[str, int]


# --- Categorization route ---

@app.post("/categorize", response_model=CategorizationResponse)
@limiter.limit(MEMORY_RATE_LIMIT)
async def categorize(request: Request, data: CategorizationRequest):
    from collections import Counter
    raw = categorize_resources(data.resources)
    return CategorizationResponse(
        results=[CategorizedResource(**r) for r in raw],
        summary=dict(Counter(r["category"] for r in raw)),
    )


# --- Exploration trigger models ---

class ExplorationSignalResult(BaseModel):
    name:   str
    score:  float
    fired:  bool
    reason: str

class ExplorationDecisionResult(BaseModel):
    topic:               str
    should_explore:      bool
    total_score:         float
    signals:             list[ExplorationSignalResult]
    recommended_actions: list[str]
    cooldown_active:     bool
    reason:              str


# --- Exploration inspection endpoint ---

@app.get("/explore/{topic}", response_model=ExplorationDecisionResult)
@limiter.limit(MEMORY_RATE_LIMIT)
async def inspect_exploration(request: Request, topic: str):
    decision = evaluate_exploration(topic)
    return ExplorationDecisionResult(
        topic=decision.topic,
        should_explore=decision.should_explore,
        total_score=decision.total_score,
        signals=[
            ExplorationSignalResult(
                name=s.name, score=s.score, fired=s.fired, reason=s.reason
            )
            for s in decision.signals
        ],
        recommended_actions=decision.recommended_actions,
        cooldown_active=decision.cooldown_active,
        reason=decision.reason,
    )


# --- Chat models ---

CHAT_RATE_LIMIT = cfg.CHAT_RATE_LIMIT


class FeedContext(BaseModel):
    """
    Context injected when a user opens a feed insight card in chat.

    Carries the pre-curated content from the insight card so the chat
    service can skip redundant retrieval and answer from known context.
    """
    action:           str             # "ask_about" | "continue_research" | "deep_research"
    insight_title:    str
    insight_summary:  str             = ""
    why_it_matters:   str             = ""
    source_urls:      list[str]       = []
    project_name:     str             = ""
    project_keywords: list[str]       = []
    project_id:       str             = ""
    category:         str | None      = None
    content_type:     str             = "news"   # "news" | "educational"
    domain:           str             = "default"


# Matches ChatInput.jsx's MAX_ATTACHMENTS=4 (client-side only until now).
_CHAT_ATTACHMENTS_MAX = 4


class ChatAttachment(BaseModel):
    """
    An upload reference — never the file bytes. See /chat/upload.

    Images: a Gemini Files API uri (uploaded there directly) — uri/expires_at
    are Gemini's own (real 48h expiry, checked by chat_service._attachment_is_live
    to decide whether to resend a media part on later turns). Chat-R14a: ALSO
    dual-written to R2 for persistent preview/download past that 48h window —
    r2_attachment_id/r2_expires_at are that separate clock/id, deliberately not
    reusing uri/expires_at so Gemini's own liveness check is untouched.

    Documents (pdf/docx/csv/text/code, Chat-R6a): a "doc://<attachment_id>" uri
    referencing extracted+embedded text in document_chunks_vec, PLUS the R2-
    stored original bytes (Chat-R13) at the same attachment_id.

    Other files (Chat-R14a): any type that's neither an image nor a known
    document extension — a "file://<attachment_id>" uri, R2-stored original
    bytes only, no extraction attempted, no document_chunks_vec entry,
    download-only.

    mime_type.startswith("image/") is the discriminator used everywhere
    (chat_service, chat_prompt_service, frontend ChatMessage.jsx).
    """
    uri:        str
    mime_type:  str
    filename:   str
    size_bytes: int | None = None
    expires_at: str | None = None
    r2_attachment_id: str | None = None
    r2_expires_at:    str | None = None


class SessionAttachment(ChatAttachment):
    """Chat-R16 files panel: a ChatAttachment plus the owning message's
    created_at, so the panel can render/sort without a second lookup."""
    created_at: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    topic_hint:   str | None        = None
    chat_mode:    str               = "normal"
    feed_context: FeedContext | None = None
    attachments:  list[ChatAttachment] | None = None
    extended_thinking: bool         = False

    @field_validator("chat_mode")
    @classmethod
    def chat_mode_valid(cls, v: str) -> str:
        if v not in ("normal", "web_search", "deep_research", "layman"):
            raise ValueError("chat_mode must be 'normal', 'web_search', 'deep_research', or 'layman'")
        return v

    @field_validator("session_id")
    @classmethod
    def session_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("session_id must not be blank")
        return v.strip()

    @field_validator("message")
    @classmethod
    def message_strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def message_or_attachments_required(self):
        # An attachment-only turn (image/PDF, no typed text) is valid — the
        # bare message string just can't be empty with nothing else attached.
        if not self.message and not self.attachments:
            raise ValueError("message must not be blank")
        return self

    @field_validator("attachments")
    @classmethod
    def attachments_within_cap(cls, v: list[ChatAttachment] | None) -> list[ChatAttachment] | None:
        # Matches ChatInput.jsx's existing MAX_ATTACHMENTS=4 client-side cap —
        # was enforced only in the UI, never server-side (any other client
        # could send an unbounded list).
        if v and len(v) > _CHAT_ATTACHMENTS_MAX:
            raise ValueError(f"Too many attachments: {len(v)} (max {_CHAT_ATTACHMENTS_MAX} per message)")
        return v


class ChatMessageRecord(BaseModel):
    id:          int
    session_id:  str
    role:        str
    content:     str
    topic_hint:  str | None
    created_at:  str
    attachments: list[ChatAttachment] | None = None
    thinking:    str | None = None
    blocks:      list[dict] | None = None


class ChatSessionSummary(BaseModel):
    session_id:       str
    message_count:    int
    last_active_at:   str
    first_topic_hint: str | None
    title:            str | None = None


class RenameSessionRequest(BaseModel):
    title: str


# --- Chat endpoints ---

def _require_owner(owner: str | None, user_id: str, not_found_detail: str) -> None:
    """
    Chat-R10d/R10e: shared shape for every by-id ownership gate in this file.
    404s when owner is set and doesn't match user_id. A None owner (resource
    not found, OR found but legacy/unclaimed — predates per-resource
    ownership tracking) is allowed through: real data shows this is common,
    not hypothetical (see get_session_owner / get_project_owner /
    get_collection_owner / get_bookmark_owner docstrings for real counts). A
    strict block would lock real users out of their own pre-auth data with
    no way to reclaim it — matches the original migrations' stated intent
    ("nullable so existing rows keep working"). Same 404-not-403 convention
    throughout: reveal nothing about whether a resource exists at all.
    """
    if owner is not None and owner != user_id:
        raise HTTPException(status_code=404, detail=not_found_detail)


def _require_session_access(session_id: str, user_id: str) -> None:
    from .services.chat_title_service import get_session_owner
    _require_owner(get_session_owner(session_id), user_id, "Session not found")


def _require_project_access(project_id: str, user_id: str) -> None:
    from .services.project_service import get_project_owner
    _require_owner(get_project_owner(project_id), user_id, "Project not found")


def _require_collection_access(collection_id: str, user_id: str) -> None:
    from .services.bookmark_service import get_collection_owner
    _require_owner(get_collection_owner(collection_id), user_id, "Collection not found")


def _require_bookmark_access(bookmark_id: str, user_id: str) -> None:
    from .services.bookmark_service import get_bookmark_owner
    _require_owner(get_bookmark_owner(bookmark_id), user_id, "Bookmark not found")


@app.post("/chat/stream")
@limiter.limit(CHAT_RATE_LIMIT)
async def chat_stream_endpoint(
    request: Request,
    data: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Stream the AI response as NDJSON.

    Each line is a JSON object:
      {"t":"chunk",   "v":"<text>", "seq":int, "block_id":int}       — incremental AI text (Chat-R10d ordering)
      {"t":"thinking","v":"<text>", "seq":int, "block_id":int}       — incremental Gemini reasoning (Chat-6)
      {"t":"thinking_gap","v":"<text>"}   — reasoning ran but can't stream on this leg (Chat-6 followup)
      {"t":"done", <metadata>}            — final metadata (same shape as /chat)
      {"t":"error","message":"<reason>"}  — unrecoverable error
    """
    _require_session_access(data.session_id, current_user["user_id"])
    from .services.chat_title_service import ensure_session_owner
    ensure_session_owner(data.session_id, current_user["user_id"])

    def generator():
        yield from chat_stream_generator(
            session_id   = data.session_id,
            message      = data.message,
            topic_hint   = data.topic_hint,
            chat_mode    = data.chat_mode,
            feed_context = data.feed_context.model_dump() if data.feed_context else None,
            user_id      = current_user["user_id"],
            attachments  = [a.model_dump() for a in data.attachments] if data.attachments else None,
            extended_thinking = data.extended_thinking,
        )

    return StreamingResponse(
        generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control":     "no-cache",
        },
    )


_CHAT_UPLOAD_IMAGE_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
# What chat_attachment_file_endpoint will ever serve inline (no Content-Disposition) —
# every other type is forced to attachment+octet-stream. See that endpoint's
# Security docstring note.
_INLINE_PREVIEW_MIME_TYPES = _CHAT_UPLOAD_IMAGE_MIME | {"application/pdf"}


def _r2_upload_or_none(data: bytes, key: str, content_type: str | None, attachment_id: str) -> bool:
    """True on success. Logs and returns False on failure instead of raising
    — chat_upload_endpoint's NDJSON generator can't raise HTTPException mid-
    stream (the 200 response has already started), so it turns a False here
    into a clean {"t":"error"} stream line instead."""
    from .services import r2_storage_service
    try:
        r2_storage_service.upload(data, key, content_type=content_type)
        return True
    except Exception as exc:
        logger.warning("[chat] R2 upload failed for attachment %s: %s", attachment_id, exc)
        return False


@app.post("/chat/upload")
@limiter.limit(CHAT_UPLOAD_RATE_LIMIT)
async def chat_upload_endpoint(
    request: Request,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Chat-R19c: streamed as NDJSON, same shape as chat_stream_endpoint above.
    Each line is a JSON object:
      {"t":"stage", "stage":"embedding",    "batch":int, "total_batches":int}
          One per embedding batch, document uploads only (real sub-progress
          exists nowhere else — extraction/chunking/R2-upload/image/other-
          file are each a single atomic call, so they stay silent).
      {"t":"stage", "stage":"rate_limited", "batch":int, "total_batches":int}
          Only when that batch's embedding call retried due to Gemini's
          RESOURCE_EXHAUSTED ceiling (R19b) — distinct from a generic
          transient retry, which stays invisible.
      {"t":"done", <ChatAttachment fields>}  — final payload, same fields
          /chat/upload returned directly before this phase.
      {"t":"error", "message":"<reason>"}    — unrecoverable error.

    Images: uploaded to Gemini's Files API (primary key only — see
    model_provider.upload_attachment), unchanged. Chat-R14a: ALSO dual-written
    to R2 (r2_attachment_id/r2_expires_at) so preview/download survives past
    Gemini's real 48h expiry — see ChatAttachment's docstring for why this
    isn't just reusing uri/expires_at.

    Documents (pdf/docx/csv/text/code, Chat-R6a): text is extracted here
    (document_extraction_service) and stored as embedded chunks
    (document_memory_service), keyed by a new attachment_id — never uploaded
    to Gemini's vision/Files API. Routed by file extension, not content_type:
    browsers send unreliable/missing MIME types for code files (verified live
    via mimetypes.guess_type as a proxy). A scanned/image-only PDF returns a
    clear, specific error — no OCR attempt (R6b, separate/unresolved phase).
    Original bytes also go to R2 (Chat-R13).

    Other files (Chat-R14a): anything that's neither an image nor a known
    document extension. No extraction attempted (no document_chunks_vec
    entry) — original bytes go straight to R2, download-only. Nothing is
    rejected outright anymore; only truly-broken uploads (extraction errors,
    upstream failures) fail.
    """
    from datetime import datetime, timedelta, timezone
    from pathlib import PurePosixPath

    ext = PurePosixPath(file.filename or "").suffix.lower()
    filename = file.filename or "upload"
    content_type = file.content_type
    is_image = content_type in _CHAT_UPLOAD_IMAGE_MIME

    data = await file.read()
    if len(data) > cfg.CHAT_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large ({cfg.CHAT_UPLOAD_MAX_BYTES // (1024 * 1024)}MB limit).")

    def generator():
        now = datetime.now(timezone.utc)
        retention = timedelta(days=cfg.ATTACHMENT_RETENTION_DAYS)
        upload_failed = json.dumps({"t": "error", "message": "Upload failed — please try again."}) + "\n"

        try:
            if is_image:
                from .llm.model_provider import upload_attachment
                try:
                    result = upload_attachment(data, content_type, filename)
                except Exception as exc:
                    logger.warning("[chat] attachment upload failed: %s", exc)
                    yield upload_failed
                    return

                r2_attachment_id = uuid.uuid4().hex
                if not _r2_upload_or_none(data, f"chat-attachments/{r2_attachment_id}{ext}", content_type, r2_attachment_id):
                    yield upload_failed
                    return
                result["r2_attachment_id"] = r2_attachment_id
                result["r2_expires_at"] = (now + retention).isoformat()
                attachment = ChatAttachment(**result)
                yield json.dumps({"t": "done", **attachment.model_dump()}) + "\n"
                return

            if ext in document_extraction_service.DOCUMENT_EXTENSIONS:
                text, error = document_extraction_service.extract_document_text(data, filename, ext)
                if error:
                    yield json.dumps({"t": "error", "message": error}) + "\n"
                    return
                attachment_id = None
                try:
                    for event in document_memory_service.store_document_stream(filename, text):
                        if event["stage"] == "done":
                            attachment_id = event["attachment_id"]
                        else:
                            yield json.dumps({"t": "stage", **event}) + "\n"
                except Exception as exc:
                    logger.warning("[chat] document processing failed: %s", exc)
                    yield upload_failed
                    return
                uri = f"doc://{attachment_id}"
            else:
                attachment_id = uuid.uuid4().hex
                uri = f"file://{attachment_id}"

            if not _r2_upload_or_none(data, f"chat-attachments/{attachment_id}{ext}", content_type, attachment_id):
                yield upload_failed
                return

            attachment = ChatAttachment(
                uri=uri,
                mime_type=content_type or "application/octet-stream",
                filename=filename,
                size_bytes=len(data),
                expires_at=(now + retention).isoformat(),
            )
            yield json.dumps({"t": "done", **attachment.model_dump()}) + "\n"
        except Exception:
            logger.exception("[chat] upload stream failed unexpectedly")
            yield upload_failed

    return StreamingResponse(
        generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control":     "no-cache",
        },
    )


def _get_document_text_or_404(attachment_id: str) -> dict:
    """
    Chat-R15b: shared text-extraction core for document attachment previews —
    reused by chat_attachment_document_endpoint and the share-scoped
    share_attachment_document_endpoint. Zero authorization logic here by
    design, same split as _stream_r2_attachment below.
    """
    text = document_memory_service.get_full_text(attachment_id)
    if text is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"text": text}


@app.get("/chat/attachment/document/{attachment_id}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def chat_attachment_document_endpoint(
    request: Request,
    attachment_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Full extracted text for a document attachment — Chat-R10's text preview
    pane specifically (e.g. docx's text-based preview). Chat-R14a: no longer
    used for download of any type — see /chat/attachment/file/{attachment_id}/
    {filename} for real original-bytes serving. Permanent, no expiry check —
    unlike images, this text lives in our own DB, not a third-party file store
    with a retention clock (see ChatAttachment's docstring).

    Chat-R15c: real session-ownership check, closing the same bug class
    R7a/R10c already closed elsewhere (login-only was never enough —
    document_chunks_vec carries no user_id/session_id itself, see schema.py's
    CREATE_DOCUMENT_CHUNKS_VEC comment). Resolved via
    chat_service.get_document_owner_session — a permanent record written at
    message-save time, NOT attachment_belongs_to_session's JSON-liveness scan
    (that would incorrectly 404 the owner's own text once the original file
    is swept, breaking R13's permanent-access guarantee). Same
    _require_owner/get_session_owner primitives R7a/R10c already use
    elsewhere, reused verbatim. Always 404, never 403.

    See /share/{token}/attachment/document/{attachment_id} (Chat-R15b) for
    the separate share-token-scoped path — untouched by this change, no
    shared authorization code with it.
    """
    from .services.chat_service import get_document_owner_session
    from .services.chat_title_service import get_session_owner

    session_id = get_document_owner_session(attachment_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    _require_owner(get_session_owner(session_id), current_user["user_id"], "Document not found.")

    return _get_document_text_or_404(attachment_id)


async def _stream_r2_attachment(attachment_id: str, filename: str) -> StreamingResponse:
    """
    Chat-R14a/R15a: shared R2-streaming core for attachment file serving —
    reconstructs the upload-time key (chat-attachments/<attachment_id><ext>),
    streams the object (r2_storage_service.download_stream, never full-
    buffers), and applies the inline-vs-download Content-Type/Disposition
    security policy. Zero authorization logic lives here by design — callers
    (chat_attachment_file_endpoint, share_attachment_file_endpoint) each gate
    access their own way before calling this, and share none of that gating
    with each other.

    Security: "other" files (Chat-R14a) accept genuinely any extension, and
    neither caller's ownership check is a content-type guarantee — so serving
    a guessed mime_type inline is a real stored-XSS vector (a user-uploaded
    evil.html/evil.svg would execute script in this app's own origin for
    whoever's browser opens the URL). Only the exact types this app already
    trusts for native inline rendering (images + PDF, matching
    _CHAT_UPLOAD_IMAGE_MIME + the PDF preview this exists for) are ever sent
    with their real Content-Type and no disposition. Everything else — every
    document/"other" type, always meant to be download-only per Chat-R14a's
    own design — is forced to application/octet-stream + Content-Disposition:
    attachment, so a browser can never render it inline regardless of what
    the filename claims.
    """
    import mimetypes
    from pathlib import PurePosixPath
    from .services import r2_storage_service

    ext = PurePosixPath(filename).suffix.lower()
    key = f"chat-attachments/{attachment_id}{ext}"
    try:
        chunks, content_length = r2_storage_service.download_stream(key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            raise HTTPException(status_code=404, detail="Attachment not found.")
        logger.warning("[chat] attachment file fetch failed for %s: %s", key, exc)
        raise HTTPException(status_code=502, detail="Could not fetch attachment — please try again.")

    headers = {"X-Content-Type-Options": "nosniff"}
    if content_length is not None:
        headers["Content-Length"] = str(content_length)

    guessed_mime = mimetypes.guess_type(filename)[0]
    if guessed_mime in _INLINE_PREVIEW_MIME_TYPES:
        return StreamingResponse(chunks, media_type=guessed_mime, headers=headers)

    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    headers["Content-Disposition"] = f'attachment; filename="{safe_filename}"'
    return StreamingResponse(chunks, media_type="application/octet-stream", headers=headers)


@app.get("/chat/attachment/file/{attachment_id}/{filename}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def chat_attachment_file_endpoint(
    request: Request,
    attachment_id: str,
    filename: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Chat-R14a: real original-bytes serving for every R2-backed attachment type
    (image dual-write, document, "other" file) — one endpoint, no per-type
    branching. filename is supplied by the caller (already has it from the
    ChatAttachment JSON) purely to reconstruct the exact upload-time R2 key
    (chat-attachments/<attachment_id><ext>) and to give browsers a sane
    default save-as name — it isn't looked up anywhere server-side.

    No Content-Disposition toggle: the frontend's existing blob-fetch-then-
    anchor-download pattern (ChatMessage.jsx's downloadUrl, already used for
    R6a's text download) does "save as filename" entirely client-side via the
    anchor's download attribute, regardless of what header this endpoint
    sends. Content-Type alone (stdlib mimetypes, not client-supplied) is
    enough for both inline preview (<img>/<iframe> src=) and download.

    404 if the object is gone (expired + swept, or never existed). Trust
    boundary: login required, unguessable id is the only scope — see
    /share/{token}/attachment/... (Chat-R15a) for the separate, share-token-
    scoped path with a real ownership join. This endpoint's own auth/scope is
    unchanged by that addition; only the streaming core below is shared.
    """
    return await _stream_r2_attachment(attachment_id, filename)


@app.post("/unpack/explain")
@limiter.limit(UNPACK_RATE_LIMIT)
async def unpack_explain_endpoint(
    request: Request,
    data: UnpackExplainRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Stream an Unpack "Explain" result as NDJSON.

    Each line is a JSON object:
      {"t":"chunk","v":"<text>"}                       — incremental meaning_in_context text
      {"t":"done", term, definition_general,
       meaning_in_context, confidence,
       source, provider}                                — final result
      {"t":"error","message":"<reason>"}                 — unrecoverable error
    """
    def generator():
        yield from explain_stream(
            term          = data.term,
            sentence      = data.sentence,
            prev_sentence = data.prev_sentence,
            next_sentence = data.next_sentence,
        )

    return StreamingResponse(
        generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control":     "no-cache",
        },
    )


@app.post("/unpack/translate")
@limiter.limit(UNPACK_RATE_LIMIT)
async def unpack_translate_endpoint(
    request: Request,
    data: UnpackTranslateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Translate a selected term via Google Cloud Translation API. Plain JSON — no streaming."""
    try:
        return translate_term(data.term, data.target_language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning("[unpack] translate failed: %s", exc)
        raise HTTPException(status_code=502, detail="Translation is temporarily unavailable.")


@app.post("/unpack/read-aloud")
@limiter.limit(UNPACK_RATE_LIMIT)
async def unpack_read_aloud_endpoint(
    request: Request,
    data: UnpackReadAloudRequest,
    current_user: dict = Depends(get_current_user),
):
    """Synthesize speech for a selected term/phrase via Google Cloud TTS. Plain JSON — no streaming."""
    try:
        return synthesize_speech(data.term)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning("[unpack] read-aloud failed: %s", exc)
        raise HTTPException(status_code=502, detail="Read aloud is temporarily unavailable.")


@app.get("/chat/sessions", response_model=list[ChatSessionSummary])
@limiter.limit(MEMORY_RATE_LIMIT)
async def list_sessions_endpoint(
    request: Request,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    return [ChatSessionSummary(**s) for s in list_chat_sessions(limit=limit, user_id=current_user["user_id"])]


@app.get("/chat/sessions/search")
@limiter.limit(MEMORY_RATE_LIMIT)
async def search_sessions_endpoint(
    request: Request,
    q: str = "",
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    from .services.chat_title_service import search_sessions
    return search_sessions(q, limit=min(max(limit, 1), 50), user_id=current_user["user_id"])


@app.put("/chat/sessions/{session_id}/title")
@limiter.limit(MEMORY_RATE_LIMIT)
async def rename_session_endpoint(
    request: Request,
    session_id: str,
    data: RenameSessionRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_session_access(session_id, current_user["user_id"])
    from .services.chat_title_service import rename_session
    rename_session(session_id, data.title)
    return {"session_id": session_id, "title": data.title.strip()[:100]}


@app.get("/chat/history/{session_id}", response_model=list[ChatMessageRecord])
@limiter.limit(MEMORY_RATE_LIMIT)
async def chat_history_endpoint(
    request: Request,
    session_id: str,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    _require_session_access(session_id, current_user["user_id"])
    return [ChatMessageRecord(**m) for m in get_chat_history(session_id, limit=limit)]


@app.get("/chat/attachments/{session_id}", response_model=list[SessionAttachment])
@limiter.limit(MEMORY_RATE_LIMIT)
async def chat_attachments_endpoint(
    request: Request,
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Chat-R16 files panel: every attachment across the whole session,
    unbounded — deliberately NOT /chat/history/{session_id}, which caps at
    `limit` messages and would pull full content/thinking/blocks just to
    extract a small field.
    """
    _require_session_access(session_id, current_user["user_id"])
    from .services.chat_service import list_session_attachments
    return [SessionAttachment(**a) for a in list_session_attachments(session_id)]


@app.delete("/chat/history/{session_id}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def delete_chat_history(
    request: Request,
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_session_access(session_id, current_user["user_id"])
    deleted = clear_chat_history(session_id)
    return {"session_id": session_id, "deleted_count": deleted}


@app.delete("/chat/sessions/{session_id}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def delete_session_endpoint(
    request: Request,
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_session_access(session_id, current_user["user_id"])
    from .utils.db import get_connection as _gc
    with _gc() as conn:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_sessions  WHERE session_id = ?", (session_id,))
        conn.execute(
            "UPDATE bookmarks SET conversation_reference = '' WHERE conversation_reference = ?",
            (session_id,),
        )
    return {"session_id": session_id, "deleted": True}


@app.delete("/chat/sessions/{session_id}/last_turn")
@limiter.limit(MEMORY_RATE_LIMIT)
async def delete_last_turn_endpoint(
    request: Request,
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_session_access(session_id, current_user["user_id"])
    from .utils.db import get_connection as _gc
    with _gc() as conn:
        rows = conn.execute(
            "SELECT id FROM chat_messages WHERE session_id = ? ORDER BY id DESC LIMIT 2",
            (session_id,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM chat_messages WHERE id IN ({placeholders})", ids)
    return {"session_id": session_id, "deleted": len(ids)}


# ─────────────────────────────────────────────────────────────────────────────
# Learning Projects
# ─────────────────────────────────────────────────────────────────────────────

PROJECTS_RATE_LIMIT = cfg.PROJECTS_RATE_LIMIT
INSIGHT_GEN_RATE    = cfg.INSIGHT_GEN_RATE


class CreateProjectRequest(BaseModel):
    name:                     str
    description:              str
    keywords:                 list[str] = []
    difficulty:               Literal["beginner", "intermediate", "advanced"] = "intermediate"
    color:                    str = "blue"
    daily_core_article_count: int = 4

    @field_validator("description")
    @classmethod
    def description_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Description is required.")
        return v


class UpdateProjectRequest(BaseModel):
    name:                     str | None = None
    description:              str | None = None
    keywords:                 list[str] | None = None
    difficulty:               Literal["beginner", "intermediate", "advanced"] | None = None
    color:                    str | None = None
    daily_core_article_count: int | None = None


@app.post("/projects")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def create_project_endpoint(
    request: Request,
    data: CreateProjectRequest,
    current_user: dict = Depends(get_current_user),
):
    from .services.project_service import create_project
    return create_project(
        name=data.name,
        description=data.description,
        keywords=data.keywords,
        difficulty=data.difficulty,
        color=data.color,
        daily_core_article_count=data.daily_core_article_count,
        user_id=current_user["user_id"],
    )


@app.get("/projects")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def list_projects_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    from .services.project_service import list_projects
    return list_projects(user_id=current_user["user_id"])


class SuggestKeywordsRequest(BaseModel):
    name:        str
    description: str
    difficulty:  Literal["beginner", "intermediate", "advanced"] = "intermediate"


@app.post("/projects/suggest-keywords")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def suggest_keywords_endpoint(
    request: Request,
    data: SuggestKeywordsRequest,
    current_user: dict = Depends(get_current_user),
):
    from .services.intent_profile_service import suggest_keywords
    keywords = suggest_keywords(data.name.strip(), data.description.strip(), data.difficulty)
    return {"keywords": keywords}


@app.get("/projects/{project_id}")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def get_project_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.project_service import get_project
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.put("/projects/{project_id}")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def update_project_endpoint(
    request: Request,
    project_id: str,
    data: UpdateProjectRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.project_service import update_project
    updated = update_project(project_id, **{k: v for k, v in data.model_dump().items() if v is not None})
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated


class UpdateIntentProfileRequest(BaseModel):
    learning_subject: str = ""
    persona:          str = ""
    goal:             str = ""
    industry_context: str = ""
    primary_focus:    str = ""
    search_lens:      str = ""
    intent_summary:   str = ""


@app.put("/projects/{project_id}/intent-profile")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def update_intent_profile_endpoint(
    request:      Request,
    project_id:   str,
    data:         UpdateIntentProfileRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    import datetime
    from .services.intent_profile_service import get_intent_profile, save_intent_profile
    existing = get_intent_profile(project_id) or {}
    meta = existing.get("_meta") or {}
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    updated = {
        **existing,
        "learning_subject": data.learning_subject or existing.get("learning_subject", ""),
        "persona":          data.persona          or existing.get("persona", ""),
        "goal":             data.goal             or existing.get("goal", ""),
        "industry_context": data.industry_context or existing.get("industry_context", ""),
        "primary_focus":    data.primary_focus    or existing.get("primary_focus", ""),
        "search_lens":      data.search_lens      or existing.get("search_lens", "Educational"),
        "intent_summary":   data.intent_summary   or existing.get("intent_summary", ""),
        "_meta": {
            **meta,
            "generated_by_ai":  True,
            "persona_version":  (meta.get("persona_version") or 0) + 1,
            "last_user_edit_at": now_iso,
            "last_confirmed_at": now_iso,
        },
    }
    save_intent_profile(project_id, updated)
    return {"ok": True, "intent_profile": updated}


@app.post("/projects/{project_id}/confirm-intent")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def confirm_intent_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.project_service import confirm_intent
    project = confirm_intent(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.delete("/projects/{project_id}")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def delete_project_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.project_service import delete_project
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "deleted": True}


@app.get("/projects/{project_id}/journey-preview")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def journey_preview_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Read-only journey preview. Never triggers plan_journey or any LLM call."""
    _require_project_access(project_id, current_user["user_id"])
    import json as _json
    from .utils.db import get_connection

    with get_connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(day_number), 0) AS max_day FROM project_insights "
            "WHERE project_id = ? AND status != 'generating'",
            (project_id,),
        ).fetchone()
        day_number = (row["max_day"] if row else 0) + 1

        batch_row = conn.execute(
            """SELECT * FROM journey_plans
               WHERE project_id = ? AND day_start <= ? AND day_end >= ?
               ORDER BY created_at DESC LIMIT 1""",
            (project_id, day_number, day_number),
        ).fetchone()

    if batch_row is None:
        return {"planned": False}

    batch = _json.loads(batch_row["plan_content"])
    shape = batch_row["shape"]

    if shape == "rotating_theme":
        return {
            "planned":         True,
            "shape":           "rotating_theme",
            "display_summary": batch.get("display_summary", ""),
        }

    # fixed_sequence — expose day_number + display_title only
    days = batch.get("days") or []
    today_entry = None
    future_entries = []
    past_today = False
    for entry in days:
        dn = entry.get("day_number")
        if dn == day_number:
            today_entry = {"day_number": dn, "display_title": entry.get("display_title", "")}
            past_today = True
        elif past_today:
            future_entries.append({"day_number": dn, "display_title": entry.get("display_title", "")})

    if today_entry is None:
        return {"planned": False}

    return {
        "planned":         True,
        "shape":           "fixed_sequence",
        "today":           today_entry,
        "upcoming":        future_entries[:4],
        "remaining_count": max(0, len(future_entries) - 4),
    }


@app.post("/projects/{project_id}/insights/generate")
@limiter.limit(INSIGHT_GEN_RATE)
async def generate_insight_endpoint(
    request: Request,
    project_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.project_service import (
        get_project,
        _save_generating_stub,
        _generate_insight_background,
    )
    from .utils.db import get_connection as _gc

    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id!r} not found")

    with _gc() as _conn:
        _gen = _conn.execute(
            "SELECT id, day_number, generated_at FROM project_insights "
            "WHERE project_id = ? AND status = 'generating' ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    if _gen:
        return {
            "id":           _gen["id"],
            "project_id":   project_id,
            "day_number":   _gen["day_number"],
            "generated_at": _gen["generated_at"],
            "status":       "generating",
        }

    with _gc() as _conn:
        _row = _conn.execute(
            "SELECT COALESCE(MAX(day_number), 0) AS max_day FROM project_insights "
            "WHERE project_id = ? AND status != 'generating'",
            (project_id,),
        ).fetchone()
    day_number = (_row["max_day"] if _row else 0) + 1

    stub_id, generated_at = _save_generating_stub(project_id, day_number)
    background_tasks.add_task(_generate_insight_background, project_id, stub_id, day_number)

    return {
        "id":           stub_id,
        "project_id":   project_id,
        "day_number":   day_number,
        "generated_at": generated_at,
        "status":       "generating",
    }


@app.get("/projects/{project_id}/insights/{insight_id}/status")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def get_insight_status_endpoint(
    request: Request,
    project_id: str,
    insight_id: int,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .utils.db import get_connection as _gc
    with _gc() as _conn:
        row = _conn.execute(
            "SELECT status FROM project_insights WHERE id = ? AND project_id = ?",
            (insight_id, project_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Insight not found")
    return {"status": row["status"]}


@app.delete("/projects/{project_id}/insights/{insight_id}")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def delete_insight_endpoint(
    request: Request,
    project_id: str,
    insight_id: int,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.project_service import delete_project_insight
    if not delete_project_insight(project_id, insight_id):
        raise HTTPException(status_code=404, detail="Insight not found")
    return {"deleted": True}


@app.get("/projects/{project_id}/insights")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def list_insights_endpoint(
    request: Request,
    project_id: str,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.project_service import list_project_insights
    return list_project_insights(project_id, limit=limit)


@app.post("/projects/generate-all")
@limiter.limit(cfg.TRIGGER_ALL_PROJECTS_RATE)
async def trigger_all_projects_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_admin_user),
):
    """Manually trigger daily package generation for every project. Admin-only."""
    from .services.project_service import generate_all_projects
    return generate_all_projects()


@app.post("/admin/attachments/sweep")
@limiter.limit(cfg.TRIGGER_ALL_PROJECTS_RATE)
async def sweep_expired_attachments_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_admin_user),
):
    """
    Delete R2 objects (original bytes) for document attachments past their
    ATTACHMENT_RETENTION_DAYS window and clear their chat_messages.attachments
    reference. Extracted text/embeddings are never touched. Admin-only.
    """
    from .services.chat_service import sweep_expired_attachments
    return sweep_expired_attachments()


class UpdateProgressionRequest(BaseModel):
    current_level:         Literal["beginner", "intermediate", "advanced"] | None = None
    current_focus:         str | None = None
    explored_concepts:     list[str] | None = None
    completed_topics:      list[str] | None = None
    suggested_next_topics: list[str] | None = None


@app.get("/projects/{project_id}/progression")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def get_progression_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.progression_service import get_progression
    return get_progression(project_id)


@app.put("/projects/{project_id}/progression")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def update_progression_endpoint(
    request: Request,
    project_id: str,
    data: UpdateProgressionRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.progression_service import update_progression
    return update_progression(project_id, **{k: v for k, v in data.model_dump().items() if v is not None})


# ─────────────────────────────────────────────────────────────────────────────
# Feed read-tracking endpoints
# ─────────────────────────────────────────────────────────────────────────────

class MarkReadRequest(BaseModel):
    article_title: str = ""


@app.post("/projects/{project_id}/insights/{insight_id}/cards/{article_key}/read")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def mark_card_read(
    request: Request,
    project_id: str,
    insight_id: int,
    article_key: str,
    data: MarkReadRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.feed_read_service import mark_read
    return mark_read(project_id, insight_id, article_key, data.article_title)


@app.delete("/projects/{project_id}/insights/{insight_id}/cards/{article_key}/read")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def mark_card_unread(
    request: Request,
    project_id: str,
    insight_id: int,
    article_key: str,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.feed_read_service import mark_unread
    deleted = mark_unread(project_id, insight_id, article_key)
    return {"deleted": deleted}


@app.get("/projects/{project_id}/insights/{insight_id}/reads")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def get_insight_reads(
    request: Request,
    project_id: str,
    insight_id: int,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.feed_read_service import get_reads_for_insight
    records = get_reads_for_insight(project_id, insight_id)
    return {
        "insight_id": insight_id,
        "read_keys": [r["article_key"] for r in records],
        "records":   records,
    }


@app.get("/stats/reading")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def reading_stats_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Aggregate reading stats for the current user:
    streak, total cards read, packages generated, active projects.

    Notes/note_count are added here (owner-only endpoint) rather than inside
    get_reading_stats() itself, because the public share resolver also calls
    get_reading_stats() for shared dashboards and must never see note data.
    """
    from .services.feed_read_service import get_reading_stats
    from .services.card_notes_service import get_all_notes_for_user

    stats = get_reading_stats(user_id=current_user["user_id"])
    notes = get_all_notes_for_user(current_user["user_id"])
    stats["notes"] = notes
    stats["note_count"] = len(notes)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Feed → Chat link endpoints
# ─────────────────────────────────────────────────────────────────────────────

class CreateFeedChatLinkRequest(BaseModel):
    session_id:       str
    project_id:       str
    article_key:      str
    article_title:    str        = ""
    interaction_type: str        = "ask_about"
    insight_id:       int | None = None


@app.post("/feed-chat-links")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def create_feed_chat_link(
    request: Request,
    data: CreateFeedChatLinkRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(data.project_id, current_user["user_id"])
    from .services.feed_chat_link_service import create_link
    return create_link(
        session_id=data.session_id,
        project_id=data.project_id,
        article_key=data.article_key,
        article_title=data.article_title,
        interaction_type=data.interaction_type,
        insight_id=data.insight_id,
    )


@app.get("/feed-chat-links")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def get_feed_chat_links(
    request: Request,
    project_id: str,
    article_key: str,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.feed_chat_link_service import get_links_for_article
    return get_links_for_article(project_id, article_key)


# ── Package export ────────────────────────────────────────────────────────────

@app.get("/projects/{project_id}/insights/{insight_id}/export")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def export_insight_endpoint(
    request: Request,
    project_id: str,
    insight_id: int,
    format: str = "md",
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.export_service import insight_to_markdown
    from fastapi.responses import Response

    md = insight_to_markdown(project_id, insight_id)
    if not md:
        raise HTTPException(status_code=404, detail="Package not found")

    filename = f"day-package-{insight_id}.md"
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Activity calendar ─────────────────────────────────────────────────────────

@app.get("/activity/all")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def all_projects_activity_endpoint(
    request: Request,
    days: int = 365,
    current_user: dict = Depends(get_current_user),
):
    from .services.activity_service import get_all_projects_activity
    days = min(max(days, 7), 365)
    return get_all_projects_activity(current_user["user_id"], days)


@app.get("/projects/{project_id}/activity")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def project_activity_endpoint(
    request: Request,
    project_id: str,
    days: int = 365,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.activity_service import get_project_activity
    days = min(max(days, 7), 365)
    return get_project_activity(project_id, days)


# ── Card Notes ────────────────────────────────────────────────────────────────

class CardNoteBody(BaseModel):
    content: str = ""


@app.put("/projects/{project_id}/insights/{insight_id}/cards/{card_id}/note")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def upsert_card_note(
    request: Request,
    project_id: str,
    insight_id: int,
    card_id: str,
    body: CardNoteBody,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.card_notes_service import upsert_note
    return upsert_note(project_id, insight_id, card_id, body.content)


@app.delete("/projects/{project_id}/insights/{insight_id}/cards/{card_id}/note")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def delete_card_note(
    request: Request,
    project_id: str,
    insight_id: int,
    card_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.card_notes_service import delete_note
    return {"deleted": delete_note(project_id, insight_id, card_id)}


@app.get("/projects/{project_id}/insights/{insight_id}/notes")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def get_insight_notes(
    request: Request,
    project_id: str,
    insight_id: int,
    current_user: dict = Depends(get_current_user),
):
    _require_project_access(project_id, current_user["user_id"])
    from .services.card_notes_service import get_notes_for_insight
    return get_notes_for_insight(project_id, insight_id)


# ── Bookmarks ─────────────────────────────────────────────────────────────────

from .services.bookmark_service import (
    list_collections,
    create_collection,
    update_collection,
    delete_collection,
    list_bookmarks,
    create_bookmark,
    get_bookmark,
    update_bookmark,
    delete_bookmark,
)

BOOKMARKS_RATE_LIMIT = cfg.BOOKMARKS_RATE_LIMIT


class CreateCollectionRequest(BaseModel):
    name:        str
    description: str = ""
    color:       str = "blue"


class UpdateCollectionRequest(BaseModel):
    name:        str | None = None
    description: str | None = None
    color:       str | None = None


class CreateBookmarkRequest(BaseModel):
    collection_id:           str
    title:                   str
    summary:                 str  = ""
    content_type:            str  = "feed_article"
    source_url:              str  = ""
    project_id:              str  = ""
    project_name:            str  = ""
    tags:                    list = []
    ai_generated_notes:      str  = ""
    retrieval_metadata:      dict = {}
    related_topics:          list = []
    source_type:             str  = "feed"
    conversation_reference:  str  = ""
    deep_research_reference: str  = ""
    content_snapshot:        str  = ""


class UpdateBookmarkRequest(BaseModel):
    tags:               list | None = None
    ai_generated_notes: str  | None = None
    collection_id:      str  | None = None


@app.get("/bookmarks/collections")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_list_collections(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return list_collections(user_id=current_user["user_id"])


@app.post("/bookmarks/collections")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_create_collection(
    request: Request,
    data: CreateCollectionRequest,
    current_user: dict = Depends(get_current_user),
):
    return create_collection(data.name, data.description, data.color, user_id=current_user["user_id"])


@app.put("/bookmarks/collections/{collection_id}")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_update_collection(
    request: Request,
    collection_id: str,
    data: UpdateCollectionRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_collection_access(collection_id, current_user["user_id"])
    result = update_collection(collection_id, data.name, data.description, data.color)
    if not result:
        raise HTTPException(status_code=404, detail="Collection not found")
    return result


@app.delete("/bookmarks/collections/{collection_id}")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_delete_collection(
    request: Request,
    collection_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_collection_access(collection_id, current_user["user_id"])
    if not delete_collection(collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"ok": True}


@app.get("/bookmarks")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_list_bookmarks(
    request:       Request,
    collection_id: str | None = None,
    content_type:  str | None = None,
    source_type:   str | None = None,
    project_id:    str | None = None,
    search:        str | None = None,
    limit:         int        = 100,
    current_user: dict = Depends(get_current_user),
):
    return list_bookmarks(collection_id, content_type, source_type, project_id, search, limit, user_id=current_user["user_id"])


@app.post("/bookmarks")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_create_bookmark(
    request: Request,
    data: CreateBookmarkRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_collection_access(data.collection_id, current_user["user_id"])
    result = create_bookmark(
        collection_id=data.collection_id,
        title=data.title,
        summary=data.summary,
        content_type=data.content_type,
        source_url=data.source_url,
        project_id=data.project_id,
        project_name=data.project_name,
        tags=data.tags,
        ai_generated_notes=data.ai_generated_notes,
        retrieval_metadata=data.retrieval_metadata,
        related_topics=data.related_topics,
        source_type=data.source_type,
        conversation_reference=data.conversation_reference,
        deep_research_reference=data.deep_research_reference,
        content_snapshot=data.content_snapshot,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Collection not found")
    return result


@app.get("/bookmarks/{bookmark_id}")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_get_bookmark(
    request: Request,
    bookmark_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_bookmark_access(bookmark_id, current_user["user_id"])
    result = get_bookmark(bookmark_id)
    if not result:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return result


@app.put("/bookmarks/{bookmark_id}")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_update_bookmark(
    request: Request,
    bookmark_id: str,
    data: UpdateBookmarkRequest,
    current_user: dict = Depends(get_current_user),
):
    _require_bookmark_access(bookmark_id, current_user["user_id"])
    if data.collection_id is not None:
        # Moving the bookmark to a different collection — must own the
        # destination too, or this becomes a write primitive into someone
        # else's collection.
        _require_collection_access(data.collection_id, current_user["user_id"])
    result = update_bookmark(bookmark_id, data.tags, data.ai_generated_notes, data.collection_id)
    if not result:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return result


@app.delete("/bookmarks/{bookmark_id}")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_delete_bookmark(
    request: Request,
    bookmark_id: str,
    current_user: dict = Depends(get_current_user),
):
    _require_bookmark_access(bookmark_id, current_user["user_id"])
    if not delete_bookmark(bookmark_id):
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"ok": True}


# ── Read Later ────────────────────────────────────────────────────────────────

from .services.read_later_service import (
    list_queue as list_read_later,
    add_item as add_read_later_item,
    remove_item as remove_read_later_item,
    clear_queue as clear_read_later_queue,
)


class AddReadLaterItemRequest(BaseModel):
    articleKey:   str
    title:        str = ""
    summary:      str = ""
    category:     str | None = None
    content_type: str = "news"
    projectId:    str = ""
    projectName:  str = ""
    insightId:    str | int | None = None


@app.get("/read-later")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_list_read_later(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    return list_read_later(user_id=current_user["user_id"])


@app.post("/read-later")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_add_read_later(
    request: Request,
    data: AddReadLaterItemRequest,
    current_user: dict = Depends(get_current_user),
):
    return add_read_later_item(
        user_id=current_user["user_id"],
        article_key=data.articleKey,
        title=data.title,
        summary=data.summary,
        category=data.category,
        content_type=data.content_type,
        project_id=data.projectId,
        project_name=data.projectName,
        insight_id=data.insightId,
    )


@app.delete("/read-later/{article_key}")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_remove_read_later(
    request: Request,
    article_key: str,
    current_user: dict = Depends(get_current_user),
):
    remove_read_later_item(current_user["user_id"], article_key)
    return {"ok": True}


@app.delete("/read-later")
@limiter.limit(BOOKMARKS_RATE_LIMIT)
async def api_clear_read_later(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    clear_read_later_queue(current_user["user_id"])
    return {"ok": True}


# ── Share links ───────────────────────────────────────────────────────────────

class CreateShareLinkRequest(BaseModel):
    type: str
    resource_id: str


@app.get("/share/{token}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def resolve_share_link_endpoint(request: Request, token: str):
    from .services.share_service import resolve_share_link
    result = resolve_share_link(token)
    if result is None:
        raise HTTPException(status_code=404, detail="This link is no longer available.")
    return result


@app.get("/share/{token}/attachment/document/{attachment_id}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def share_attachment_document_endpoint(request: Request, token: str, attachment_id: str):
    """
    Chat-R15b: share-scoped text-extraction access for document attachment
    previews — mirrors share_attachment_file_endpoint's ownership join
    verbatim (same resolve_chat_session_id + attachment_belongs_to_session
    calls, same always-404 semantics). No login, no shared authorization code
    with chat_attachment_document_endpoint — only _get_document_text_or_404
    is shared between the two.

    Registration order matters: this route's literal "document" segment sits
    in the same position as share_attachment_file_endpoint's {attachment_id}
    wildcard below, so it MUST be declared first — Starlette matches routes
    in declaration order, not by specificity, and the wildcard route would
    otherwise swallow every /share/{token}/attachment/document/... request
    (capturing "document" itself as attachment_id) before this one is ever tried.
    """
    from .services.share_service import resolve_chat_session_id
    from .services.chat_service import attachment_belongs_to_session

    session_id = resolve_chat_session_id(token)
    if session_id is None or not attachment_belongs_to_session(session_id, attachment_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    return _get_document_text_or_404(attachment_id)


@app.get("/share/{token}/attachment/{attachment_id}/{filename}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def share_attachment_file_endpoint(request: Request, token: str, attachment_id: str, filename: str):
    """
    Chat-R15a: share-scoped attachment access — no login, a valid share token
    is the only credential. Deliberately a separate route from
    chat_attachment_file_endpoint (no Depends(get_current_user), no shared
    authorization code between the two) — only the R2-streaming core
    (_stream_r2_attachment) is shared.

    Ownership join, always-404 (never 403), matching this app's established
    convention (_require_owner et al, never revealing whether a resource
    exists but isn't yours): token must resolve to a real chat share link ->
    attachment_id must genuinely appear somewhere in that session's own
    messages (chat_service.attachment_belongs_to_session — same
    id-extraction shape as sweep_expired_attachments) -> only then is the
    object streamed. Any failure — bad/non-chat token, attachment real but
    from a different session, or the object itself expired/swept — surfaces
    identically as 404. This closes the skeleton-key risk R15 recon flagged:
    a valid token for session A must not unlock an attachment from session B.

    Expiry needs no separate check here: an expired attachment's R2 object is
    already gone once swept (sweep_expired_attachments), so
    _stream_r2_attachment 404s for a share viewer exactly as it would for the
    owner — same honest "no longer available" outcome, no extra logic.

    Declared AFTER share_attachment_document_endpoint above — see that
    route's docstring for why the order is load-bearing.
    """
    from .services.share_service import resolve_chat_session_id
    from .services.chat_service import attachment_belongs_to_session

    session_id = resolve_chat_session_id(token)
    if session_id is None or not attachment_belongs_to_session(session_id, attachment_id):
        raise HTTPException(status_code=404, detail="Attachment not found.")

    return await _stream_r2_attachment(attachment_id, filename)


@app.post("/share/create")
@limiter.limit(MEMORY_RATE_LIMIT)
async def create_share_link_endpoint(
    request: Request,
    data: CreateShareLinkRequest,
    current_user: dict = Depends(get_current_user),
):
    if data.type not in ("feed", "chat", "dashboard"):
        raise HTTPException(status_code=400, detail="type must be 'feed', 'chat', or 'dashboard'")

    # Chat-R10e: minting a link makes resource_id PUBLIC (GET /share/{token}
    # has no auth) — must confirm the caller actually owns what they're
    # about to publish. Resolution/fork stay untouched: consuming a share
    # is deliberately cross-user, only creation needed the gate.
    if data.type == "chat":
        _require_session_access(data.resource_id, current_user["user_id"])
    elif data.type == "feed":
        # resource_id is "{projectId}/{day}" or "{projectId}/{day}/{articleIdx}"
        project_id = data.resource_id.split("/")[0]
        _require_project_access(project_id, current_user["user_id"])
    elif data.type == "dashboard":
        # resource_id IS a user_id here (see share_service._dashboard_snapshot)
        # — you can only publish your own dashboard, no NULL-owner case exists.
        if data.resource_id != current_user["user_id"]:
            raise HTTPException(status_code=404, detail="Dashboard not found")

    from .services.share_service import create_share_link
    return create_share_link(
        data.type, data.resource_id, current_user["user_id"],
        request.url.scheme, request.url.netloc,
    )


@app.post("/share/chat/{token}/fork")
@limiter.limit(MEMORY_RATE_LIMIT)
async def fork_chat_endpoint(
    request: Request,
    token: str,
    current_user: dict = Depends(get_current_user),
):
    from .services.share_service import fork_chat
    new_chat_id = fork_chat(token, current_user["user_id"])
    if new_chat_id is None:
        raise HTTPException(status_code=404, detail="Share link not found")
    return {"new_chat_id": new_chat_id}


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """
    Liveness probe for container orchestration and HF Spaces.
    Returns 200 when healthy, 503 when degraded.
    """
    checks: dict = {}

    # Database
    try:
        from .utils.db import get_connection
        with get_connection() as conn:
            conn.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"

    # API keys present (not validated, just present)
    checks["groq"]   = "configured" if os.getenv("GROQ_API_KEY")   else "missing"
    checks["tavily"] = "configured" if os.getenv("TAVILY_API_KEY") else "missing"

    healthy = checks["db"] == "ok"
    checks["status"] = "ok" if healthy else "degraded"

    return JSONResponse(
        status_code=200 if healthy else 503,
        content=checks,
    )
