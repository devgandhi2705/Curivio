import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

from . import config as cfg

import logging
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator
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
    check_current_password,
    create_reset_token,
    verify_reset_code,
    consume_reset_token,
    create_signup_verification,
    complete_signup_verification,
)
from .services.chat_service import (
    chat as chat_with_ai,
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

# --- Rate limits (edit in backend/config.py) ---
GENERATE_FEED_RATE_LIMIT = cfg.GENERATE_FEED_RATE_LIMIT
SEARCH_RATE_LIMIT        = cfg.SEARCH_RATE_LIMIT
FEEDBACK_RATE_LIMIT      = cfg.FEEDBACK_RATE_LIMIT
MEMORY_RATE_LIMIT        = cfg.MEMORY_RATE_LIMIT

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

    yield

app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- CORS (edit APP_URL / CORS_ORIGINS in backend/config.py or as env vars) ---
CORS_ORIGINS = [o.strip() for o in cfg.CORS_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# --- Request models ---

class UserInput(BaseModel):
    interests: str


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
async def auth_register(data: RegisterRequest):
    return register_user(data.email, data.name, data.password)


@app.post("/auth/login")
async def auth_login(data: LoginRequest):
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
async def auth_forgot_password(data: ForgotPasswordRequest):
    create_reset_token(data.email)
    return {"ok": True}


@app.post("/auth/verify-reset-code")
async def auth_verify_reset_code(data: VerifyResetCodeRequest):
    verify_reset_code(data.email, data.code)
    return {"ok": True}


@app.post("/auth/reset-password")
async def auth_reset_password(data: ResetPasswordRequest):
    consume_reset_token(data.email, data.code, data.new_password)
    return {"ok": True}


@app.post("/auth/send-verify-email")
async def auth_send_verify_email(data: SendVerifyEmailRequest):
    create_signup_verification(data.email, data.name, data.password)
    return {"ok": True}


@app.post("/auth/complete-signup", status_code=201)
async def auth_complete_signup(data: CompleteSignupRequest):
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


def _auto_research(topic: str) -> None:
    """Background task wrapper — errors are logged, never re-raised."""
    try:
        run_deep_research(topic)
        try:
            record_activity(topic, "deep_research")
        except Exception:
            logger.warning("[session_memory] record failed for deep_research %r", topic)
    except Exception:
        logger.exception("[deep_research] background task failed for topic %r", topic)


@app.post("/feedback", response_model=FeedbackResponse)
@limiter.limit(FEEDBACK_RATE_LIMIT)
async def feedback(request: Request, data: FeedbackRequest, background_tasks: BackgroundTasks):
    result = process_feedback(data.topic, data.feedback)
    decision = evaluate_exploration(data.topic)
    if decision.should_explore:
        background_tasks.add_task(_auto_research, data.topic)
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
async def trigger_deep_research(request: Request, data: DeepResearchRequest):
    cached = get_stored_research(data.topic)
    if cached:
        return DeepResearchResult(**cached)
    result = run_deep_research(data.topic)
    try:
        record_activity(data.topic, "deep_research")
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
async def select_topics(request: Request, data: TopicSelectionRequest):
    results = []
    for topic in data.topics:
        updated = process_feedback(topic, "liked")
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
async def trigger_topic_expansion(request: Request, data: TopicExpansionRequest):
    result = expand_topic(data.topic)
    try:
        record_activity(data.topic, "topic_expansion")
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
async def discover_repos(request: Request, data: RepoDiscoveryRequest):
    repos = get_topic_repos(data.topic)
    try:
        record_activity(data.topic, "github_repos")
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
async def trigger_learning_path(request: Request, data: LearningPathRequest):
    result = get_learning_path(data.topic)
    try:
        result["repositories"] = get_topic_repos(data.topic)
    except Exception:
        logger.warning("[learning_path] repo fetch failed for topic %r", data.topic)
        result.setdefault("repositories", [])
    try:
        record_activity(data.topic, "learning_path")
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
    category:         str | None      = None
    content_type:     str             = "news"   # "news" | "educational"
    domain:           str             = "default"


class ChatRequest(BaseModel):
    session_id: str
    message: str
    topic_hint:   str | None        = None
    chat_mode:    str               = "normal"
    feed_context: FeedContext | None = None

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
    def message_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v.strip()


class ChatContextUsed(BaseModel):
    has_deep_research:      bool
    has_learning_path:      bool
    has_topic_expansion:    bool
    has_github_repos:       bool
    interests_count:        int
    history_turns:          int
    topics_in_session:      int = 0
    total_topics_explored:  int = 0


class RecommendationItem(BaseModel):
    topic:  str
    reason: str


class ChatRecommendations(BaseModel):
    based_on_topic:  str | None
    source:          str               # "stored" | "empty"
    next_topics:     list[RecommendationItem]
    prerequisites:   list[RecommendationItem]
    advanced_topics: list[RecommendationItem]


class ChatResponse(BaseModel):
    session_id:      str
    message_id:      int
    response:        str
    topic_hint:      str | None
    action:          str | None = None   # detected action, e.g. "show_repos"
    recommendations: ChatRecommendations | None = None
    context_used:    ChatContextUsed
    created_at:      str


class ChatMessageRecord(BaseModel):
    id:          int
    session_id:  str
    role:        str
    content:     str
    topic_hint:  str | None
    created_at:  str


class ChatSessionSummary(BaseModel):
    session_id:       str
    message_count:    int
    last_active_at:   str
    first_topic_hint: str | None
    title:            str | None = None


class RenameSessionRequest(BaseModel):
    title: str


# --- Chat endpoints ---

@app.post("/chat", response_model=ChatResponse)
@limiter.limit(CHAT_RATE_LIMIT)
async def chat_endpoint(
    request: Request,
    data: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    from .services.chat_title_service import ensure_session_owner
    result = chat_with_ai(
        session_id=data.session_id,
        message=data.message,
        topic_hint=data.topic_hint,
        chat_mode=data.chat_mode,
        feed_context=data.feed_context.model_dump() if data.feed_context else None,
    )
    ensure_session_owner(data.session_id, current_user["user_id"])
    raw_rec = result.get("recommendations")
    recommendations = ChatRecommendations(**raw_rec) if raw_rec else None

    return ChatResponse(
        session_id=result["session_id"],
        message_id=result["message_id"],
        response=result["response"],
        topic_hint=result["topic_hint"],
        action=result.get("action"),
        recommendations=recommendations,
        context_used=ChatContextUsed(**result["context_used"]),
        created_at=result["created_at"],
    )


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
      {"t":"chunk","v":"<text>"}          — incremental AI text
      {"t":"done", <metadata>}            — final metadata (same shape as /chat)
      {"t":"error","message":"<reason>"}  — unrecoverable error
    """
    from .services.chat_title_service import ensure_session_owner
    ensure_session_owner(data.session_id, current_user["user_id"])

    def generator():
        yield from chat_stream_generator(
            session_id   = data.session_id,
            message      = data.message,
            topic_hint   = data.topic_hint,
            chat_mode    = data.chat_mode,
            feed_context = data.feed_context.model_dump() if data.feed_context else None,
        )

    return StreamingResponse(
        generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control":     "no-cache",
        },
    )


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
    return [ChatMessageRecord(**m) for m in get_chat_history(session_id, limit=limit)]


@app.delete("/chat/history/{session_id}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def delete_chat_history(
    request: Request,
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    deleted = clear_chat_history(session_id)
    return {"session_id": session_id, "deleted_count": deleted}


@app.delete("/chat/sessions/{session_id}")
@limiter.limit(MEMORY_RATE_LIMIT)
async def delete_session_endpoint(
    request: Request,
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
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
    description:              str = ""
    keywords:                 list[str] = []
    difficulty:               Literal["beginner", "intermediate", "advanced"] = "intermediate"
    focus_areas:              list[str] = []
    color:                    str = "blue"
    preferred_sources:        list[str] = []
    ignored_sources:          list[str] = []
    daily_core_article_count: int = 4


class UpdateProjectRequest(BaseModel):
    name:                     str | None = None
    description:              str | None = None
    keywords:                 list[str] | None = None
    difficulty:               Literal["beginner", "intermediate", "advanced"] | None = None
    focus_areas:              list[str] | None = None
    color:                    str | None = None
    preferred_sources:        list[str] | None = None
    ignored_sources:          list[str] | None = None
    daily_core_article_count: int | None = None


class CheckSourceRelevanceRequest(BaseModel):
    domain:       str
    project_name: str
    keywords:     list[str] = []


@app.post("/projects/check-source-relevance")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def check_source_relevance_endpoint(
    request: Request,
    data: CheckSourceRelevanceRequest,
    current_user: dict = Depends(get_current_user),
):
    from .services.project_service import check_source_relevance
    return check_source_relevance(data.domain, data.project_name, data.keywords)


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
        focus_areas=data.focus_areas,
        color=data.color,
        preferred_sources=data.preferred_sources,
        ignored_sources=data.ignored_sources,
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


@app.get("/projects/{project_id}")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def get_project_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
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
    from .services.project_service import update_project
    updated = update_project(project_id, **{k: v for k, v in data.model_dump().items() if v is not None})
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated


@app.delete("/projects/{project_id}")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def delete_project_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    from .services.project_service import delete_project
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": project_id, "deleted": True}


@app.post("/projects/{project_id}/insights/generate")
@limiter.limit(INSIGHT_GEN_RATE)
async def generate_insight_endpoint(
    request: Request,
    project_id: str,
    current_user: dict = Depends(get_current_user),
):
    from .services.project_service import generate_project_insight
    try:
        return generate_project_insight(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/projects/{project_id}/insights/{insight_id}")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def delete_insight_endpoint(
    request: Request,
    project_id: str,
    insight_id: int,
    current_user: dict = Depends(get_current_user),
):
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
    from .services.project_service import list_project_insights
    return list_project_insights(project_id, limit=limit)


@app.post("/projects/generate-all")
@limiter.limit(cfg.TRIGGER_ALL_PROJECTS_RATE)
async def trigger_all_projects_endpoint(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Manually trigger daily package generation for every project."""
    from .services.project_service import generate_all_projects
    return generate_all_projects()


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
    """
    from .services.feed_read_service import get_reading_stats
    return get_reading_stats(user_id=current_user["user_id"])


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

@app.get("/projects/{project_id}/activity")
@limiter.limit(PROJECTS_RATE_LIMIT)
async def project_activity_endpoint(
    request: Request,
    project_id: str,
    days: int = 365,
    current_user: dict = Depends(get_current_user),
):
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
    if not delete_bookmark(bookmark_id):
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"ok": True}


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
