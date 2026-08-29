"""
DDL for all database tables.
Import this module to get the SQL strings; execution is handled by db.py.
"""

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY,
    email      TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL DEFAULT '',
    hashed_pw  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_USERS_EMAIL_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email);
"""

CREATE_USER_PREFERENCES = """
CREATE TABLE IF NOT EXISTS user_preferences (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    topic                TEXT    NOT NULL UNIQUE,
    preference_score     REAL    NOT NULL DEFAULT 0.0,
    times_recommended    INTEGER NOT NULL DEFAULT 0,
    times_liked          INTEGER NOT NULL DEFAULT 0,
    times_disliked       INTEGER NOT NULL DEFAULT 0,
    difficulty_preference TEXT   CHECK(difficulty_preference IN ('beginner', 'intermediate', 'advanced')) DEFAULT NULL,
    last_updated         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_GENERATED_FEEDS = """
CREATE TABLE IF NOT EXISTS generated_feeds (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    interests      TEXT    NOT NULL,
    feed_json      TEXT    NOT NULL,
    insight_title  TEXT,
    learning_stage TEXT,
    difficulty     TEXT,
    source         TEXT    NOT NULL DEFAULT 'scheduler'
                           CHECK(source IN ('scheduler', 'user')),
    generated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_DAILY_DIGESTS = """
CREATE TABLE IF NOT EXISTS daily_digests (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    news_title           TEXT      NOT NULL,
    news_summary         TEXT      NOT NULL,
    why_it_matters       TEXT      NOT NULL,
    learning_topics_json TEXT      NOT NULL,
    next_step            TEXT      NOT NULL,
    source_links_json    TEXT      NOT NULL DEFAULT '[]',
    source               TEXT      NOT NULL DEFAULT 'scheduler'
                                   CHECK(source IN ('scheduler', 'user'))
);
"""

CREATE_DAILY_DIGESTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_daily_digests_date
    ON daily_digests (DATE(generated_at));
"""

CREATE_FEED_CACHE = """
CREATE TABLE IF NOT EXISTS feed_cache (
    cache_key    TEXT      PRIMARY KEY,
    interests    TEXT      NOT NULL,
    feed_json    TEXT      NOT NULL,
    hit_count    INTEGER   NOT NULL DEFAULT 0,
    generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_SEARCH_CACHE = """
CREATE TABLE IF NOT EXISTS search_cache (
    cache_key    TEXT      PRIMARY KEY,
    query        TEXT      NOT NULL,
    results_json TEXT      NOT NULL,
    hit_count    INTEGER   NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_API_USAGE_LOG = """
CREATE TABLE IF NOT EXISTS api_usage_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    service            TEXT    NOT NULL,
    operation          TEXT    NOT NULL,
    model              TEXT,
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    duration_ms        INTEGER,
    cache_hit          INTEGER NOT NULL DEFAULT 0,
    query_hint         TEXT,
    estimated_cost_usd REAL,
    created_at         TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_API_USAGE_LOG_IDX = """
CREATE INDEX IF NOT EXISTS idx_api_usage_log_created_at
    ON api_usage_log (created_at);
"""

CREATE_DEEP_RESEARCH = """
CREATE TABLE IF NOT EXISTS deep_research (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    topic         TEXT    NOT NULL,
    topic_key     TEXT    NOT NULL UNIQUE,
    research_json TEXT    NOT NULL,
    generated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_DEEP_RESEARCH_IDX = """
CREATE INDEX IF NOT EXISTS idx_deep_research_generated
    ON deep_research (generated_at DESC);
"""

CREATE_TOPIC_EXPANSIONS = """
CREATE TABLE IF NOT EXISTS topic_expansions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    topic          TEXT    NOT NULL,
    topic_key      TEXT    NOT NULL UNIQUE,
    expansion_json TEXT    NOT NULL,
    generated_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_TOPIC_EXPANSIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_topic_expansions_generated
    ON topic_expansions (generated_at DESC);
"""

CREATE_LEARNING_PATHS = """
CREATE TABLE IF NOT EXISTS learning_paths (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    topic          TEXT    NOT NULL,
    topic_key      TEXT    NOT NULL UNIQUE,
    learning_stage TEXT    NOT NULL DEFAULT 'beginner',
    path_json      TEXT    NOT NULL,
    generated_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_LEARNING_PATHS_IDX = """
CREATE INDEX IF NOT EXISTS idx_learning_paths_generated
    ON learning_paths (generated_at DESC);
"""

CREATE_GITHUB_REPOS = """
CREATE TABLE IF NOT EXISTS github_repos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT    NOT NULL,
    topic_key   TEXT    NOT NULL UNIQUE,
    repos_json  TEXT    NOT NULL,
    fetched_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_GITHUB_REPOS_IDX = """
CREATE INDEX IF NOT EXISTS idx_github_repos_fetched
    ON github_repos (fetched_at DESC);
"""

CREATE_RESEARCH_SESSIONS = """
CREATE TABLE IF NOT EXISTS research_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT    NOT NULL,
    topic_key   TEXT    NOT NULL,
    activity    TEXT    NOT NULL
                        CHECK(activity IN ('deep_research','learning_path','topic_expansion','github_repos')),
    recorded_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_RESEARCH_SESSIONS_TOPIC_IDX = """
CREATE INDEX IF NOT EXISTS idx_research_sessions_topic_key
    ON research_sessions (topic_key, activity);
"""

CREATE_RESEARCH_SESSIONS_TIME_IDX = """
CREATE INDEX IF NOT EXISTS idx_research_sessions_recorded
    ON research_sessions (recorded_at DESC);
"""

CREATE_CHAT_SESSIONS = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    title      TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CHAT_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    role         TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
    content      TEXT    NOT NULL,
    topic_hint   TEXT,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attachments  TEXT,
    thinking     TEXT,
    blocks       TEXT
);
"""

CREATE_CHAT_MESSAGES_IDX = """
CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, created_at);
"""

# JSON-encoded list of {uri, mime_type, filename, size_bytes, expires_at} — the
# Gemini Files API URI only, never the file bytes. NULL/absent for plain-text turns.
MIGRATE_ADD_CHAT_MESSAGES_ATTACHMENTS = (
    "ALTER TABLE chat_messages ADD COLUMN attachments TEXT"
)

# Assistant's raw reasoning text (Chat-R10c) — NULL for user messages, gap turns,
# and legs that never streamed thinking. Never fed back as LLM context, see
# _load_history_messages, only surfaced to the API/frontend via get_history.
MIGRATE_ADD_CHAT_MESSAGES_THINKING = (
    "ALTER TABLE chat_messages ADD COLUMN thinking TEXT"
)

# JSON-encoded ordered list of {type: "thinking"|"tool_call"|"text", ...}
# segments (Chat-R10d) — coexists with the flat `thinking` column above
# (still populated unchanged for existing consumers), NULL for user messages
# and turns with no segments. Same exclusion as `thinking`: never fed back
# as LLM context, see _load_history_messages.
MIGRATE_ADD_CHAT_MESSAGES_BLOCKS = (
    "ALTER TABLE chat_messages ADD COLUMN blocks TEXT"
)

CREATE_CONCEPT_MEMORY = """
CREATE TABLE IF NOT EXISTS concept_memory (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    concept            TEXT    NOT NULL,
    concept_key        TEXT    NOT NULL,
    topic              TEXT,
    topic_key          TEXT,
    session_id         TEXT,
    times_explained    INTEGER NOT NULL DEFAULT 1,
    first_explained_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_explained_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CONCEPT_MEMORY_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_memory_key
    ON concept_memory (concept_key);
"""

CREATE_CONCEPT_MEMORY_TOPIC_IDX = """
CREATE INDEX IF NOT EXISTS idx_concept_memory_topic
    ON concept_memory (topic_key);
"""

CREATE_PRIOR_RECOMMENDATIONS = """
CREATE TABLE IF NOT EXISTS prior_recommendations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    topic           TEXT    NOT NULL,
    topic_key       TEXT    NOT NULL,
    rec_type        TEXT    NOT NULL
                            CHECK(rec_type IN ('next_topic', 'prerequisite', 'advanced')),
    recommended     TEXT    NOT NULL,
    recommended_key TEXT    NOT NULL,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (topic_key, recommended_key)
);
"""

CREATE_PRIOR_RECOMMENDATIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_prior_recs_topic
    ON prior_recommendations (topic_key);
"""

CREATE_LEARNING_PROJECTS = """
CREATE TABLE IF NOT EXISTS learning_projects (
    project_id               TEXT    NOT NULL PRIMARY KEY,
    name                     TEXT    NOT NULL,
    description              TEXT    NOT NULL DEFAULT '',
    keywords                 TEXT    NOT NULL DEFAULT '[]',
    difficulty               TEXT    NOT NULL DEFAULT 'intermediate'
                                     CHECK(difficulty IN ('beginner', 'intermediate', 'advanced')),
    color                    TEXT    NOT NULL DEFAULT 'blue',
    daily_core_article_count INTEGER NOT NULL DEFAULT 4,
    intent_profile           TEXT             DEFAULT NULL,
    intent_confirmed         INTEGER NOT NULL DEFAULT 0,
    created_at               TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATE_ADD_DAILY_CORE_ARTICLE_COUNT = (
    "ALTER TABLE learning_projects ADD COLUMN daily_core_article_count INTEGER NOT NULL DEFAULT 4"
)

# Drop deprecated columns from existing databases (SQLite 3.35+).
# These run with try/except so they fail silently on fresh databases that never had the columns.
MIGRATE_DROP_FOCUS_AREAS = (
    "ALTER TABLE learning_projects DROP COLUMN focus_areas"
)

MIGRATE_DROP_PREFERRED_SOURCES = (
    "ALTER TABLE learning_projects DROP COLUMN preferred_sources"
)

MIGRATE_DROP_IGNORED_SOURCES = (
    "ALTER TABLE learning_projects DROP COLUMN ignored_sources"
)

CREATE_PROJECT_INSIGHTS = """
CREATE TABLE IF NOT EXISTS project_insights (
    id           INTEGER   PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT      NOT NULL REFERENCES learning_projects(project_id) ON DELETE CASCADE,
    day_number   INTEGER   NOT NULL DEFAULT 1,
    insight_json TEXT      NOT NULL DEFAULT '{}',
    generated_at TEXT      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status       TEXT      NOT NULL DEFAULT 'done'
                           CHECK(status IN ('generating', 'done', 'failed'))
);
"""

CREATE_PROJECT_INSIGHTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_project_insights_project
    ON project_insights (project_id, day_number DESC);
"""

CREATE_PROJECT_PROGRESSION = """
CREATE TABLE IF NOT EXISTS project_progression (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id            TEXT    NOT NULL UNIQUE
                                  REFERENCES learning_projects(project_id) ON DELETE CASCADE,
    current_level         TEXT    NOT NULL DEFAULT 'beginner'
                                  CHECK(current_level IN ('beginner', 'intermediate', 'advanced')),
    current_focus         TEXT,
    explored_concepts     TEXT    NOT NULL DEFAULT '[]',
    completed_topics      TEXT    NOT NULL DEFAULT '[]',
    suggested_next_topics TEXT    NOT NULL DEFAULT '[]',
    days_completed        INTEGER NOT NULL DEFAULT 0,
    updated_at            TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PROJECT_PROGRESSION_IDX = """
CREATE INDEX IF NOT EXISTS idx_project_progression_project
    ON project_progression (project_id);
"""

CREATE_INTELLIGENCE_FEEDS = """
CREATE TABLE IF NOT EXISTS intelligence_feeds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    interests    TEXT    NOT NULL,
    industry     TEXT,
    feed_json    TEXT    NOT NULL,
    source       TEXT    NOT NULL DEFAULT 'user'
                         CHECK(source IN ('scheduler', 'user')),
    generated_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_INTELLIGENCE_FEEDS_IDX = """
CREATE INDEX IF NOT EXISTS idx_intelligence_feeds_generated
    ON intelligence_feeds (generated_at DESC);
"""

CREATE_FEED_ARTICLE_READS = """
CREATE TABLE IF NOT EXISTS feed_article_reads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT    NOT NULL,
    insight_id    INTEGER NOT NULL,
    article_key   TEXT    NOT NULL,
    article_title TEXT    NOT NULL DEFAULT '',
    read_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, insight_id, article_key)
);
"""

CREATE_FEED_ARTICLE_READS_IDX = """
CREATE INDEX IF NOT EXISTS idx_feed_article_reads_insight
    ON feed_article_reads (project_id, insight_id);
"""

CREATE_FEED_CHAT_LINKS = """
CREATE TABLE IF NOT EXISTS feed_chat_links (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL,
    project_id       TEXT    NOT NULL,
    insight_id       INTEGER,
    article_key      TEXT    NOT NULL,
    article_title    TEXT    NOT NULL DEFAULT '',
    interaction_type TEXT    NOT NULL DEFAULT 'ask_about'
                             CHECK(interaction_type IN ('ask_about', 'explain_simply', 'continue_research', 'deep_research')),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_FEED_CHAT_LINKS_IDX = """
CREATE INDEX IF NOT EXISTS idx_feed_chat_links_article
    ON feed_chat_links (project_id, article_key);
"""

CREATE_FEED_CHAT_LINKS_SESSION_IDX = """
CREATE INDEX IF NOT EXISTS idx_feed_chat_links_session
    ON feed_chat_links (session_id);
"""

CREATE_BOOKMARK_COLLECTIONS = """
CREATE TABLE IF NOT EXISTS bookmark_collections (
    collection_id   TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    color           TEXT DEFAULT 'blue',
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_BOOKMARKS = """
CREATE TABLE IF NOT EXISTS bookmarks (
    bookmark_id              TEXT PRIMARY KEY,
    collection_id            TEXT NOT NULL REFERENCES bookmark_collections(collection_id) ON DELETE CASCADE,
    title                    TEXT NOT NULL,
    summary                  TEXT DEFAULT '',
    content_type             TEXT NOT NULL,
    source_url               TEXT DEFAULT '',
    project_id               TEXT DEFAULT '',
    project_name             TEXT DEFAULT '',
    tags                     TEXT DEFAULT '[]',
    saved_at                 TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ai_generated_notes       TEXT DEFAULT '',
    retrieval_metadata       TEXT DEFAULT '{}',
    related_topics           TEXT DEFAULT '[]',
    source_type              TEXT DEFAULT 'feed',
    conversation_reference   TEXT DEFAULT '',
    deep_research_reference  TEXT DEFAULT '',
    content_snapshot         TEXT DEFAULT ''
);
"""

CREATE_BOOKMARKS_COLLECTION_IDX = """
CREATE INDEX IF NOT EXISTS idx_bookmarks_collection
    ON bookmarks (collection_id, saved_at DESC);
"""

CREATE_BOOKMARKS_TYPE_IDX = """
CREATE INDEX IF NOT EXISTS idx_bookmarks_type
    ON bookmarks (content_type, saved_at DESC);
"""

CREATE_READ_LATER_ITEMS = """
CREATE TABLE IF NOT EXISTS read_later_items (
    user_id       TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    article_key   TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    summary       TEXT DEFAULT '',
    category      TEXT,
    content_type  TEXT DEFAULT 'news',
    project_id    TEXT DEFAULT '',
    project_name  TEXT DEFAULT '',
    insight_id    TEXT DEFAULT '',
    queued_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, article_key)
);
"""

CREATE_READ_LATER_ITEMS_IDX = """
CREATE INDEX IF NOT EXISTS idx_read_later_user
    ON read_later_items (user_id, queued_at DESC);
"""

# One row per LLM call made through backend/llm/model_provider.py's
# get_chat_model()/get_structured_chat_model() — written by
# backend/llm/call_logger.py's LangChain callback. No FKs (log table —
# rows must survive deletion of the user/project/insight they reference).
CREATE_LLM_CALL_LOG = """
CREATE TABLE IF NOT EXISTS llm_call_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL UNIQUE,
    parent_run_id   TEXT,
    timestamp_start TEXT    NOT NULL,
    timestamp_end   TEXT    NOT NULL,
    latency_ms      INTEGER NOT NULL,
    provider        TEXT    NOT NULL,
    model_requested TEXT,
    model_used      TEXT,
    call_type       TEXT,
    user_id         TEXT,
    project_id      TEXT,
    day_ref         INTEGER,
    input           TEXT    NOT NULL DEFAULT '',
    output          TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER,
    success         INTEGER NOT NULL,
    error_type      TEXT,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_LLM_CALL_LOG_IDX = """
CREATE INDEX IF NOT EXISTS idx_llm_call_log_created
    ON llm_call_log (created_at DESC);
"""

CREATE_PASSWORD_RESET_TOKENS = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT    NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    code_hash  TEXT    NOT NULL UNIQUE,
    expires_at TEXT    NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Security hardening phase: the reset code used to be stored as plaintext in
# `token`; existing installs need the column renamed to match — new installs
# get code_hash straight from CREATE_PASSWORD_RESET_TOKENS above, so this is
# a no-op there ("no such column: token", caught by init_db's migration
# runner same as any other fresh-DB skip). Any reset code mid-flight at
# upgrade time is orphaned (its row keeps the old plaintext under a column
# name the app no longer queries) — acceptable, codes are single-digit-
# minutes-lived; the user just requests a new one.
MIGRATE_RESET_TOKENS_TOKEN_TO_CODE_HASH = (
    "ALTER TABLE password_reset_tokens RENAME COLUMN token TO code_hash"
)

CREATE_VERIFICATION_LOCKOUTS = """
CREATE TABLE IF NOT EXISTS verification_lockouts (
    email        TEXT    NOT NULL,
    purpose      TEXT    NOT NULL CHECK(purpose IN ('reset', 'signup')),
    fail_count   INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    updated_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (email, purpose)
);
"""

CREATE_RESEND_COOLDOWNS = """
CREATE TABLE IF NOT EXISTS resend_cooldowns (
    email        TEXT NOT NULL,
    purpose      TEXT NOT NULL CHECK(purpose IN ('reset', 'signup')),
    last_sent_at TEXT NOT NULL,
    PRIMARY KEY (email, purpose)
);
"""

CREATE_PENDING_SIGNUPS = """
CREATE TABLE IF NOT EXISTS pending_signups (
    email      TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    hashed_pw  TEXT NOT NULL,
    code_hash  TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_REVOKED_TOKENS = """
CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        TEXT PRIMARY KEY,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CARD_NOTES = """
CREATE TABLE IF NOT EXISTS card_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT    NOT NULL,
    insight_id  INTEGER NOT NULL,
    card_id     TEXT    NOT NULL,
    content     TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, insight_id, card_id)
);
"""

CREATE_CARD_NOTES_IDX = """
CREATE INDEX IF NOT EXISTS idx_card_notes_insight
    ON card_notes (project_id, insight_id);
"""

CREATE_CONVERSATION_KNOWLEDGE_STATE = """
CREATE TABLE IF NOT EXISTS conversation_knowledge_state (
    session_id TEXT    PRIMARY KEY,
    state_json TEXT    NOT NULL,
    updated_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PROJECT_LEARNING_STATE = """
CREATE TABLE IF NOT EXISTS project_learning_state (
    project_id       TEXT NOT NULL PRIMARY KEY
                         REFERENCES learning_projects(project_id) ON DELETE CASCADE,
    covered_topics   TEXT NOT NULL DEFAULT '[]',
    active_topics    TEXT NOT NULL DEFAULT '[]',
    knowledge_gaps   TEXT NOT NULL DEFAULT '[]',
    recent_topics    TEXT NOT NULL DEFAULT '[]',
    covered_entities TEXT NOT NULL DEFAULT '[]',
    covered_keywords TEXT NOT NULL DEFAULT '[]',
    updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PROJECT_LEARNING_MEMORY = """
CREATE TABLE IF NOT EXISTS project_learning_memory (
    project_id         TEXT    NOT NULL PRIMARY KEY
                               REFERENCES learning_projects(project_id) ON DELETE CASCADE,
    covered_concepts   TEXT    NOT NULL DEFAULT '[]',
    covered_mechanisms TEXT    NOT NULL DEFAULT '[]',
    covered_industries TEXT    NOT NULL DEFAULT '[]',
    covered_examples   TEXT    NOT NULL DEFAULT '[]',
    covered_geographies TEXT   NOT NULL DEFAULT '[]',
    covered_narratives TEXT    NOT NULL DEFAULT '[]',
    curiosity_angles   TEXT    NOT NULL DEFAULT '[]',
    progression_stage  TEXT    NOT NULL DEFAULT 'foundation',
    days_at_stage      INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PROJECT_LEARNING_MEMORY_IDX = """
CREATE INDEX IF NOT EXISTS idx_project_learning_memory_project
    ON project_learning_memory (project_id);
"""

# Add conversation_mode column to chat_sessions (tracks layman / normal session type)
MIGRATE_ADD_CHAT_SESSION_CONVERSATION_MODE = (
    "ALTER TABLE chat_sessions ADD COLUMN conversation_mode TEXT NOT NULL DEFAULT 'normal'"
)

# Extend feed_chat_links.interaction_type CHECK to include 'explain_simply'.
# SQLite requires a full table-recreation to change a CHECK constraint, so this
# migration is a list of statements executed in order inside the same connection.
MIGRATE_FEED_CHAT_LINKS_ADD_EXPLAIN_SIMPLY = [
    "PRAGMA foreign_keys=OFF",
    """CREATE TABLE IF NOT EXISTS feed_chat_links_v2 (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id       TEXT    NOT NULL,
        project_id       TEXT    NOT NULL,
        insight_id       INTEGER,
        article_key      TEXT    NOT NULL,
        article_title    TEXT    NOT NULL DEFAULT '',
        interaction_type TEXT    NOT NULL DEFAULT 'ask_about'
                                 CHECK(interaction_type IN ('ask_about','continue_research','deep_research','explain_simply')),
        created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    "INSERT OR IGNORE INTO feed_chat_links_v2 SELECT * FROM feed_chat_links",
    "DROP TABLE IF EXISTS feed_chat_links",
    "ALTER TABLE feed_chat_links_v2 RENAME TO feed_chat_links",
    "CREATE INDEX IF NOT EXISTS idx_feed_chat_links_article ON feed_chat_links (project_id, article_key)",
    "CREATE INDEX IF NOT EXISTS idx_feed_chat_links_session ON feed_chat_links (session_id)",
    "PRAGMA foreign_keys=ON",
]

# ── Multi-user migrations ─────────────────────────────────────────────────────
# Add user_id to all user-owned tables. Nullable so existing rows keep working.
MIGRATE_ADD_USER_ID_PROJECTS = (
    "ALTER TABLE learning_projects ADD COLUMN user_id TEXT REFERENCES users(user_id)"
)
MIGRATE_ADD_USER_ID_CHAT_SESSIONS = (
    "ALTER TABLE chat_sessions ADD COLUMN user_id TEXT REFERENCES users(user_id)"
)
MIGRATE_ADD_USER_ID_BOOKMARK_COLLECTIONS = (
    "ALTER TABLE bookmark_collections ADD COLUMN user_id TEXT REFERENCES users(user_id)"
)
MIGRATE_ADD_USER_ID_PREFERENCES = (
    "ALTER TABLE user_preferences ADD COLUMN user_id TEXT REFERENCES users(user_id)"
)
MIGRATE_ADD_USER_ID_CONCEPT_MEMORY = (
    "ALTER TABLE concept_memory ADD COLUMN user_id TEXT REFERENCES users(user_id)"
)
MIGRATE_ADD_USER_ID_PRIOR_RECS = (
    "ALTER TABLE prior_recommendations ADD COLUMN user_id TEXT REFERENCES users(user_id)"
)

MIGRATE_ADD_TITLE_PATTERNS_USED = (
    "ALTER TABLE project_learning_memory ADD COLUMN title_patterns_used TEXT NOT NULL DEFAULT '[]'"
)
MIGRATE_ADD_OPENING_HOOKS_USED = (
    "ALTER TABLE project_learning_memory ADD COLUMN opening_hooks_used TEXT NOT NULL DEFAULT '[]'"
)

MIGRATE_ADD_INTENT_PROFILE = (
    "ALTER TABLE learning_projects ADD COLUMN intent_profile TEXT DEFAULT NULL"
)

MIGRATE_ADD_INTENT_CONFIRMED = (
    "ALTER TABLE learning_projects ADD COLUMN intent_confirmed INTEGER NOT NULL DEFAULT 0"
)

MIGRATE_DROP_LEARNING_BLUEPRINT = (
    "ALTER TABLE learning_projects DROP COLUMN learning_blueprint"
)

CREATE_KNOWLEDGE_GRAPH_NODES = """
CREATE TABLE IF NOT EXISTS knowledge_graph_nodes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT    NOT NULL,
    node_key    TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    node_type   TEXT    NOT NULL,
    weight      INTEGER NOT NULL DEFAULT 1,
    first_seen  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, node_key)
);
"""

CREATE_KNOWLEDGE_GRAPH_NODES_IDX = """
CREATE INDEX IF NOT EXISTS idx_kgn_project
    ON knowledge_graph_nodes (project_id, node_type);
"""

CREATE_KNOWLEDGE_GRAPH_EDGES = """
CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT    NOT NULL,
    from_key    TEXT    NOT NULL,
    to_key      TEXT    NOT NULL,
    relation    TEXT    NOT NULL,
    weight      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, from_key, to_key, relation)
);
"""

CREATE_KNOWLEDGE_GRAPH_EDGES_IDX = """
CREATE INDEX IF NOT EXISTS idx_kge_project_from
    ON knowledge_graph_edges (project_id, from_key);
"""

CREATE_KNOWLEDGE_GRAPH_EDGES_TO_IDX = """
CREATE INDEX IF NOT EXISTS idx_kge_project_to
    ON knowledge_graph_edges (project_id, to_key);
"""

CREATE_LEARNING_EVALUATIONS = """
CREATE TABLE IF NOT EXISTS learning_evaluations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     TEXT    NOT NULL,
    package_day    INTEGER NOT NULL DEFAULT 0,
    overall_score  REAL    NOT NULL DEFAULT 0.0,
    scores_json    TEXT    NOT NULL DEFAULT '{}',
    issues_json    TEXT    NOT NULL DEFAULT '[]',
    recs_json      TEXT    NOT NULL DEFAULT '[]',
    top_gaps_json  TEXT    NOT NULL DEFAULT '[]',
    evaluated_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATE_ADD_TOP_GAPS_JSON = (
    "ALTER TABLE learning_evaluations ADD COLUMN top_gaps_json TEXT NOT NULL DEFAULT '[]'"
)

CREATE_LEARNING_EVALUATIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_learning_evaluations_project
    ON learning_evaluations (project_id, evaluated_at DESC);
"""

CREATE_ARTICLE_PROVENANCE = """
CREATE TABLE IF NOT EXISTS article_provenance (
    id              TEXT    PRIMARY KEY,
    project_id      TEXT    NOT NULL,
    insight_id      INTEGER,
    feed_date       TEXT    NOT NULL,
    title           TEXT    NOT NULL DEFAULT '',
    url             TEXT    NOT NULL DEFAULT '',
    domain          TEXT    NOT NULL DEFAULT '',
    publisher       TEXT    NOT NULL DEFAULT '',
    source_type     TEXT    NOT NULL DEFAULT '',
    query_used      TEXT    NOT NULL DEFAULT '',
    retrieval_score REAL    NOT NULL DEFAULT 0.0,
    ranking_score   REAL    NOT NULL DEFAULT 0.0,
    ranking_reason  TEXT    NOT NULL DEFAULT '',
    selected        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_ARTICLE_PROVENANCE_DATE_IDX = """
CREATE INDEX IF NOT EXISTS idx_article_provenance_project_date
    ON article_provenance (project_id, feed_date);
"""

CREATE_ARTICLE_PROVENANCE_URL_IDX = """
CREATE INDEX IF NOT EXISTS idx_article_provenance_project_url
    ON article_provenance (project_id, url);
"""

CREATE_RETRIEVAL_METRICS = """
CREATE TABLE IF NOT EXISTS retrieval_metrics (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id               TEXT    NOT NULL,
    insight_id               INTEGER NOT NULL,
    computed_at              TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    retrieved_count          INTEGER NOT NULL DEFAULT 0,
    validated_count          INTEGER NOT NULL DEFAULT 0,
    rejected_count           INTEGER NOT NULL DEFAULT 0,
    avg_relevance            REAL    NOT NULL DEFAULT 0.0,
    unique_domains           INTEGER NOT NULL DEFAULT 0,
    unique_publishers        INTEGER NOT NULL DEFAULT 0,
    source_reuse_rate        REAL    NOT NULL DEFAULT 0.0,
    primary_source_collisions INTEGER NOT NULL DEFAULT 0,
    domain_concentration     REAL    NOT NULL DEFAULT 0.0,
    articles_without_sources INTEGER NOT NULL DEFAULT 0,
    UNIQUE (project_id, insight_id)
);
"""

CREATE_RETRIEVAL_METRICS_IDX = """
CREATE INDEX IF NOT EXISTS idx_retrieval_metrics_project
    ON retrieval_metrics (project_id, computed_at DESC);
"""

CREATE_JOURNEY_PLANS = """
CREATE TABLE IF NOT EXISTS journey_plans (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       TEXT    NOT NULL REFERENCES learning_projects(project_id) ON DELETE CASCADE,
    shape            TEXT    NOT NULL CHECK(shape IN ('fixed_sequence', 'rotating_theme')),
    day_start        INTEGER NOT NULL,
    day_end          INTEGER NOT NULL,
    plan_content     TEXT    NOT NULL,
    description_hash TEXT    NOT NULL DEFAULT '',
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_JOURNEY_PLANS_IDX = """
CREATE INDEX IF NOT EXISTS idx_journey_plans_project_days
    ON journey_plans (project_id, day_start, day_end);
"""

CREATE_UNPACK_CACHE = """
CREATE TABLE IF NOT EXISTS unpack_cache (
    cache_key       TEXT      PRIMARY KEY,
    term            TEXT      NOT NULL,
    target_language TEXT      NOT NULL DEFAULT '',
    response_json   TEXT      NOT NULL,
    hit_count       INTEGER   NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATE_ADD_JOURNEY_SHAPE = (
    "ALTER TABLE learning_projects ADD COLUMN journey_shape TEXT DEFAULT NULL"
)

MIGRATE_ADD_INSIGHT_STATUS = (
    "ALTER TABLE project_insights ADD COLUMN status TEXT NOT NULL DEFAULT 'done'"
)

CREATE_SHARE_LINKS = """
CREATE TABLE IF NOT EXISTS share_links (
    id          TEXT      PRIMARY KEY,
    type        TEXT      NOT NULL CHECK(type IN ('feed', 'chat', 'dashboard')),
    resource_id TEXT      NOT NULL,
    created_by  TEXT      NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_SHARE_LINKS_LOOKUP_IDX = """
CREATE INDEX IF NOT EXISTS idx_share_links_lookup
    ON share_links (type, resource_id, created_by);
"""

MIGRATE_ADD_CHAT_SESSIONS_FORKED_FROM = (
    "ALTER TABLE chat_sessions ADD COLUMN forked_from TEXT DEFAULT NULL"
)

# Phase U: turn-count expiry for "this session had a crisis turn recently".
# NULL = no active window. A turn number (history_turns + 1 the way
# chat_service.py counts them), not a timestamp — decay is "next N turns",
# not wall-clock time, so a long pause mid-conversation doesn't silently
# expire it, and it can't drift on a slow reply either.
MIGRATE_ADD_CHAT_SESSIONS_CRISIS_EXPIRES = (
    "ALTER TABLE chat_sessions ADD COLUMN crisis_expires_at_turn INTEGER DEFAULT NULL"
)

# Extend share_links.type CHECK to include 'dashboard'.
# SQLite requires a full table-recreation to change a CHECK constraint.
MIGRATE_SHARE_LINKS_ADD_DASHBOARD_TYPE = [
    "PRAGMA foreign_keys=OFF",
    """CREATE TABLE IF NOT EXISTS share_links_v2 (
        id          TEXT      PRIMARY KEY,
        type        TEXT      NOT NULL CHECK(type IN ('feed', 'chat', 'dashboard')),
        resource_id TEXT      NOT NULL,
        created_by  TEXT      NOT NULL,
        created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""",
    "INSERT OR IGNORE INTO share_links_v2 SELECT * FROM share_links",
    "DROP TABLE IF EXISTS share_links",
    "ALTER TABLE share_links_v2 RENAME TO share_links",
    "CREATE INDEX IF NOT EXISTS idx_share_links_lookup ON share_links (type, resource_id, created_by)",
    "PRAGMA foreign_keys=ON",
]

# Chat-R7a — user_preferences and research_sessions were never scoped by
# user_id: reads had no WHERE clause, writes never populated the column.
# Confirmed live: a brand-new user_id got back another user's
# interests_count/total_topics_explored via memory_injection_service's chain.
#
# user_preferences additionally has UNIQUE(topic) alone — adding a WHERE
# user_id=? filter on top of that as-is would still let two different users'
# INSERT ... ON CONFLICT(topic) collide on the same row (silently merging
# their preference signals), so this needs UNIQUE(topic, user_id), which
# SQLite can only apply via table recreation (same pattern as
# MIGRATE_SHARE_LINKS_ADD_DASHBOARD_TYPE above).
MIGRATE_USER_PREFERENCES_ADD_USER_ID_SCOPE = [
    "PRAGMA foreign_keys=OFF",
    """CREATE TABLE IF NOT EXISTS user_preferences_v2 (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        topic                  TEXT    NOT NULL,
        user_id                TEXT    REFERENCES users(user_id),
        preference_score       REAL    NOT NULL DEFAULT 0.0,
        times_recommended      INTEGER NOT NULL DEFAULT 0,
        times_liked            INTEGER NOT NULL DEFAULT 0,
        times_disliked         INTEGER NOT NULL DEFAULT 0,
        difficulty_preference  TEXT    CHECK(difficulty_preference IN ('beginner', 'intermediate', 'advanced')) DEFAULT NULL,
        last_updated           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(topic, user_id)
    )""",
    """INSERT OR IGNORE INTO user_preferences_v2
           (id, topic, preference_score, times_recommended, times_liked,
            times_disliked, difficulty_preference, last_updated)
       SELECT id, topic, preference_score, times_recommended, times_liked,
              times_disliked, difficulty_preference, last_updated
       FROM   user_preferences""",
    "DROP TABLE IF EXISTS user_preferences",
    "ALTER TABLE user_preferences_v2 RENAME TO user_preferences",
    "PRAGMA foreign_keys=ON",
]

# research_sessions has no such uniqueness constraint — a plain ADD COLUMN
# covers the personal-breadth-signal queries (build_exploration_breadth,
# adaptive_explanation_service). Topic-keyed "has this been researched"
# lookups (get_research_context/get_topic_memory) stay unscoped by design —
# same shared-by-topic cache category as deep_research/learning_paths content.
MIGRATE_ADD_USER_ID_RESEARCH_SESSIONS = (
    "ALTER TABLE research_sessions ADD COLUMN user_id TEXT REFERENCES users(user_id)"
)

# Feed v2 (Phase 1) — per-user toggle between the legacy feed and Feed v2.
# Lives on `users` (one row per user, user_id PK), NOT user_preferences: that
# table is keyed (topic, user_id) and holds zero rows for every current user,
# so it can't store a per-user singleton. Additive/nullable-safe: NOT NULL with
# a 'legacy' default so all 36 existing rows keep working unchanged.
MIGRATE_ADD_USER_FEED_VERSION = (
    "ALTER TABLE users ADD COLUMN feed_version TEXT NOT NULL DEFAULT 'legacy' "
    "CHECK(feed_version IN ('legacy','v2'))"
)

# Feed v2 (Phase 3) — trace_id/agent_name/step_index/surface on llm_call_log so
# a v2 multi-agent run's child calls can be grouped by trace_id and every row
# tagged with its surface. Additive + nullable — legacy call_logger never sets
# them, so its writes keep working untouched (see Phase 3 regression). This is
# the ONLY existing table Phase 3 alters.
MIGRATE_ADD_LLM_CALL_LOG_TRACE_ID   = "ALTER TABLE llm_call_log ADD COLUMN trace_id TEXT"
MIGRATE_ADD_LLM_CALL_LOG_AGENT_NAME = "ALTER TABLE llm_call_log ADD COLUMN agent_name TEXT"
MIGRATE_ADD_LLM_CALL_LOG_STEP_INDEX = "ALTER TABLE llm_call_log ADD COLUMN step_index INTEGER"
MIGRATE_ADD_LLM_CALL_LOG_SURFACE    = "ALTER TABLE llm_call_log ADD COLUMN surface TEXT"

# One-time backfill of the new surface column on existing rows. Guarded by
# `surface IS NULL` so it only touches un-backfilled rows — idempotent and cheap
# on every re-run after the first. feed_% call_types are legacy Feed; chat%
# call_types are chat; everything else (smoke/verify/test/None) stays NULL.
MIGRATE_BACKFILL_SURFACE_FEED = (
    "UPDATE llm_call_log SET surface = 'feed_legacy' "
    "WHERE surface IS NULL AND call_type LIKE 'feed_%'"
)
MIGRATE_BACKFILL_SURFACE_CHAT = (
    "UPDATE llm_call_log SET surface = 'chat' "
    "WHERE surface IS NULL AND call_type LIKE 'chat%'"
)

# Index the new trace_id — the v2 run -> child-calls JOIN is a hot path. Placed
# in MIGRATIONS (not ALL_TABLES) because it references a column that only exists
# after the ADD COLUMN above runs; ALL_TABLES runs before MIGRATIONS.
MIGRATE_INDEX_LLM_CALL_LOG_TRACE_ID = (
    "CREATE INDEX IF NOT EXISTS idx_llm_call_log_trace_id ON llm_call_log (trace_id)"
)

# Phase B1 (Admin-7) — real is_test flag, replacing the call_type-prefix naming
# convention (_TEST_DATA_EXCLUSION) as the mechanism going forward. Every writer
# (legacy call_logger, v2 call_logger, chat tool logging, explain/translate/tts)
# now sets this explicitly; the admin query layer switching over to it is B2's
# job, not this migration's.
MIGRATE_ADD_LLM_CALL_LOG_IS_TEST = (
    "ALTER TABLE llm_call_log ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0"
)

# One-time best-effort classification of PAST rows using the CURRENT
# call_type-prefix heuristic (admin_service._TEST_DATA_EXCLUSION's inverse) —
# NULL call_type or a 'smoke_test%' call_type. Deliberately not smarter than
# that heuristic (e.g. the r4_/r5_/chat6_/verify_/smoke_r3_ ad-hoc dev
# call_types Phase A found slipping past it stay is_test=0) — going forward,
# real scripts set the flag themselves instead of leaning on naming.
MIGRATE_BACKFILL_LLM_CALL_LOG_IS_TEST = (
    "UPDATE llm_call_log SET is_test = 1 "
    "WHERE call_type IS NULL OR call_type LIKE 'smoke_test%'"
)

# Phase B2 — translate_service previously only embedded target_language inside
# the free-text `input` column (f"term={term!r} target_language={lang!r}"),
# which the admin filter API can't query cleanly. Real column, nullable —
# only translate's writer sets it; every other surface leaves it NULL.
MIGRATE_ADD_LLM_CALL_LOG_TARGET_LANGUAGE = (
    "ALTER TABLE llm_call_log ADD COLUMN target_language TEXT"
)

CREATE_CONVERSATION_MEMORY_VEC = """
CREATE VIRTUAL TABLE IF NOT EXISTS conversation_memory_vec USING vec0(
    embedding   float[3072],
    +user_id    TEXT,
    +session_id TEXT,
    +topic      TEXT,
    +entry_text TEXT,
    +created_at TEXT
);
"""

# Chat-R6a — document text chunks for uploaded PDF/docx/csv/text/code attachments.
# Scoped by attachment_id (minted at /chat/upload time), not session_id: the
# upload endpoint runs before the message is sent, so session_id isn't known yet.
CREATE_DOCUMENT_CHUNKS_VEC = """
CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_vec USING vec0(
    embedding      float[3072],
    +attachment_id TEXT,
    +filename      TEXT,
    +chunk_index   TEXT,
    +page_no       INTEGER,
    +chunk_text    TEXT,
    +created_at    TEXT
);
"""

# Chat citation grounding (same fix pattern as feed_v2 Phase 8b, applied
# independently on chat's side): page_no is nullable/additive — NULL for
# chunks from documents with no real page concept (docx/txt/code) and for
# every chunk stored before this migration ran (no fabricated precision).
#
# vec0 virtual tables have no ALTER TABLE ADD COLUMN support (see
# CREATE_DOCUMENT_ATTACHMENT_SESSIONS' comment above), so this is a real
# rebuild, not a one-line ADD COLUMN. Live-verified (real sqlite-vec
# in-memory DB): ALTER TABLE RENAME on a vec0 table corrupts it — it leaves
# the internal shadow tables (e.g. `<name>_rowids`) under the OLD name,
# breaking every query against the renamed table. So this never renames —
# it drops the old table and CREATEs a fresh one under the same final name,
# round-tripping data through a temp table in between (also live-verified:
# embeddings round-trip exactly, self-distance stays ~0 after the copy).
#
# Idempotency: unlike every ADD-COLUMN migration in this file, a naive
# re-run of a drop+recreate wouldn't fail loudly (CREATE succeeds again,
# nothing here would raise "already exists") — it would just silently
# re-run and, worse, wipe any real page_no values populated since the first
# run (the copy step hardcodes NULL because it assumes the pre-migration
# shape). The bare CREATE TABLE sentinel below (no IF NOT EXISTS) is the
# fix: it raises "already exists" on any run after the first, which the
# runner's existing whitelist (init_db in utils/db.py) catches and skips —
# the same skip-on-"already exists" idempotency every other migration here
# already relies on, just made explicit since vec0 can't give it for free.
MIGRATE_DOCUMENT_CHUNKS_VEC_ADD_PAGE_NO = [
    "CREATE TABLE document_chunks_vec_page_no_migrated (id INTEGER PRIMARY KEY)",
    """CREATE VIRTUAL TABLE document_chunks_vec_tmp USING vec0(
        embedding      float[3072],
        +attachment_id TEXT,
        +filename      TEXT,
        +chunk_index   TEXT,
        +page_no       INTEGER,
        +chunk_text    TEXT,
        +created_at    TEXT
    )""",
    """INSERT INTO document_chunks_vec_tmp
           (embedding, attachment_id, filename, chunk_index, page_no, chunk_text, created_at)
       SELECT embedding, attachment_id, filename, chunk_index, NULL, chunk_text, created_at
       FROM   document_chunks_vec""",
    "DROP TABLE document_chunks_vec",
    """CREATE VIRTUAL TABLE document_chunks_vec USING vec0(
        embedding      float[3072],
        +attachment_id TEXT,
        +filename      TEXT,
        +chunk_index   TEXT,
        +page_no       INTEGER,
        +chunk_text    TEXT,
        +created_at    TEXT
    )""",
    """INSERT INTO document_chunks_vec
           (embedding, attachment_id, filename, chunk_index, page_no, chunk_text, created_at)
       SELECT embedding, attachment_id, filename, chunk_index, page_no, chunk_text, created_at
       FROM   document_chunks_vec_tmp""",
    "DROP TABLE document_chunks_vec_tmp",
]

# Chat-R15c — permanent attachment_id -> session_id record for document (doc://)
# attachments, written once at message-save time (chat_service._save_message,
# the first point session_id and attachments co-occur). Exists because
# chat_messages.attachments JSON is NOT permanent for this attachment type —
# sweep_expired_attachments drops the whole entry once the original file
# expires — while document_chunks_vec's extracted text (and therefore its
# owner's access to it) must survive forever per R13. A plain table, not a
# vec0 column: vec0 virtual tables have no ALTER TABLE support.
CREATE_DOCUMENT_ATTACHMENT_SESSIONS = """
CREATE TABLE IF NOT EXISTS document_attachment_sessions (
    attachment_id TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL
);
"""

# ── Backup / restore bookkeeping (see backend/services/backup_service.py) ─────

# Makes a repeated restore of the same snapshot a no-op. Necessary because
# INSERT OR IGNORE only actually dedupes tables that carry their own UNIQUE
# constraint — plain history tables (chat_messages, api_usage_log, ...) have
# none, so without this a second restore of the same file silently inserts
# every row a second time. `scope` is '*' for a whole-db restore or the
# user_id for a per-user one, so the two never mask each other.
CREATE_RESTORE_LOG = """
CREATE TABLE IF NOT EXISTS restore_log (
    filename      TEXT    NOT NULL,
    table_name    TEXT    NOT NULL,
    scope         TEXT    NOT NULL DEFAULT '*',
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    restored_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (filename, table_name, scope)
);
"""

# A user reporting their own data missing. Admin resolves it from the Backups
# panel by running a per-user restore; the request row records who/when so a
# report can't get silently lost in a support inbox.
CREATE_DATA_LOSS_REQUESTS = """
CREATE TABLE IF NOT EXISTS data_loss_requests (
    request_id  TEXT NOT NULL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open'
                     CHECK(status IN ('open', 'resolved', 'rejected')),
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    admin_note  TEXT NOT NULL DEFAULT ''
);
"""

CREATE_DATA_LOSS_REQUESTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_data_loss_requests_status
    ON data_loss_requests (status, created_at DESC);
"""

MIGRATIONS = [
    MIGRATE_ADD_DAILY_CORE_ARTICLE_COUNT,
    MIGRATE_DROP_FOCUS_AREAS,
    MIGRATE_DROP_PREFERRED_SOURCES,
    MIGRATE_DROP_IGNORED_SOURCES,
    MIGRATE_ADD_CHAT_SESSION_CONVERSATION_MODE,
    MIGRATE_FEED_CHAT_LINKS_ADD_EXPLAIN_SIMPLY,
    MIGRATE_ADD_USER_ID_PROJECTS,
    MIGRATE_ADD_USER_ID_CHAT_SESSIONS,
    MIGRATE_ADD_USER_ID_BOOKMARK_COLLECTIONS,
    MIGRATE_ADD_USER_ID_PREFERENCES,
    MIGRATE_ADD_USER_ID_CONCEPT_MEMORY,
    MIGRATE_ADD_USER_ID_PRIOR_RECS,
    CREATE_PROJECT_LEARNING_MEMORY,
    CREATE_PROJECT_LEARNING_MEMORY_IDX,
    MIGRATE_ADD_TITLE_PATTERNS_USED,
    MIGRATE_ADD_OPENING_HOOKS_USED,
    MIGRATE_ADD_INTENT_PROFILE,
    MIGRATE_ADD_INTENT_CONFIRMED,
    MIGRATE_DROP_LEARNING_BLUEPRINT,
    MIGRATE_ADD_JOURNEY_SHAPE,
    MIGRATE_ADD_TOP_GAPS_JSON,
    MIGRATE_ADD_INSIGHT_STATUS,
    MIGRATE_ADD_CHAT_SESSIONS_FORKED_FROM,
    MIGRATE_ADD_CHAT_SESSIONS_CRISIS_EXPIRES,
    MIGRATE_SHARE_LINKS_ADD_DASHBOARD_TYPE,
    MIGRATE_ADD_CHAT_MESSAGES_ATTACHMENTS,
    MIGRATE_USER_PREFERENCES_ADD_USER_ID_SCOPE,
    MIGRATE_ADD_USER_ID_RESEARCH_SESSIONS,
    MIGRATE_ADD_CHAT_MESSAGES_THINKING,
    MIGRATE_ADD_CHAT_MESSAGES_BLOCKS,
    MIGRATE_ADD_USER_FEED_VERSION,
    MIGRATE_ADD_LLM_CALL_LOG_TRACE_ID,
    MIGRATE_ADD_LLM_CALL_LOG_AGENT_NAME,
    MIGRATE_ADD_LLM_CALL_LOG_STEP_INDEX,
    MIGRATE_ADD_LLM_CALL_LOG_SURFACE,
    MIGRATE_BACKFILL_SURFACE_FEED,
    MIGRATE_BACKFILL_SURFACE_CHAT,
    MIGRATE_INDEX_LLM_CALL_LOG_TRACE_ID,
    MIGRATE_ADD_LLM_CALL_LOG_IS_TEST,
    MIGRATE_BACKFILL_LLM_CALL_LOG_IS_TEST,
    MIGRATE_ADD_LLM_CALL_LOG_TARGET_LANGUAGE,
    MIGRATE_DOCUMENT_CHUNKS_VEC_ADD_PAGE_NO,
    MIGRATE_RESET_TOKENS_TOKEN_TO_CODE_HASH,
]

ALL_TABLES = [
    CREATE_USERS,
    CREATE_USERS_EMAIL_IDX,
    CREATE_USER_PREFERENCES,
    CREATE_GENERATED_FEEDS,
    CREATE_DAILY_DIGESTS,
    CREATE_DAILY_DIGESTS_IDX,
    CREATE_FEED_CACHE,
    CREATE_SEARCH_CACHE,
    CREATE_API_USAGE_LOG,
    CREATE_API_USAGE_LOG_IDX,
    CREATE_DEEP_RESEARCH,
    CREATE_DEEP_RESEARCH_IDX,
    CREATE_TOPIC_EXPANSIONS,
    CREATE_TOPIC_EXPANSIONS_IDX,
    CREATE_LEARNING_PATHS,
    CREATE_LEARNING_PATHS_IDX,
    CREATE_GITHUB_REPOS,
    CREATE_GITHUB_REPOS_IDX,
    CREATE_RESEARCH_SESSIONS,
    CREATE_RESEARCH_SESSIONS_TOPIC_IDX,
    CREATE_RESEARCH_SESSIONS_TIME_IDX,
    CREATE_CHAT_SESSIONS,
    CREATE_CHAT_MESSAGES,
    CREATE_CHAT_MESSAGES_IDX,
    CREATE_CONCEPT_MEMORY,
    CREATE_CONCEPT_MEMORY_IDX,
    CREATE_CONCEPT_MEMORY_TOPIC_IDX,
    CREATE_PRIOR_RECOMMENDATIONS,
    CREATE_PRIOR_RECOMMENDATIONS_IDX,
    CREATE_LEARNING_PROJECTS,
    CREATE_PROJECT_LEARNING_STATE,
    CREATE_PROJECT_INSIGHTS,
    CREATE_PROJECT_INSIGHTS_IDX,
    CREATE_PROJECT_PROGRESSION,
    CREATE_PROJECT_PROGRESSION_IDX,
    CREATE_INTELLIGENCE_FEEDS,
    CREATE_INTELLIGENCE_FEEDS_IDX,
    CREATE_FEED_ARTICLE_READS,
    CREATE_FEED_ARTICLE_READS_IDX,
    CREATE_FEED_CHAT_LINKS,
    CREATE_FEED_CHAT_LINKS_IDX,
    CREATE_FEED_CHAT_LINKS_SESSION_IDX,
    CREATE_BOOKMARK_COLLECTIONS,
    CREATE_BOOKMARKS,
    CREATE_BOOKMARKS_COLLECTION_IDX,
    CREATE_BOOKMARKS_TYPE_IDX,
    CREATE_CARD_NOTES,
    CREATE_CARD_NOTES_IDX,
    CREATE_PASSWORD_RESET_TOKENS,
    CREATE_VERIFICATION_LOCKOUTS,
    CREATE_RESEND_COOLDOWNS,
    CREATE_PENDING_SIGNUPS,
    CREATE_REVOKED_TOKENS,
    CREATE_CONVERSATION_KNOWLEDGE_STATE,
    CREATE_PROJECT_LEARNING_MEMORY,
    CREATE_PROJECT_LEARNING_MEMORY_IDX,
    CREATE_KNOWLEDGE_GRAPH_NODES,
    CREATE_KNOWLEDGE_GRAPH_NODES_IDX,
    CREATE_KNOWLEDGE_GRAPH_EDGES,
    CREATE_KNOWLEDGE_GRAPH_EDGES_IDX,
    CREATE_KNOWLEDGE_GRAPH_EDGES_TO_IDX,
    CREATE_LEARNING_EVALUATIONS,
    CREATE_LEARNING_EVALUATIONS_IDX,
    CREATE_ARTICLE_PROVENANCE,
    CREATE_ARTICLE_PROVENANCE_DATE_IDX,
    CREATE_ARTICLE_PROVENANCE_URL_IDX,
    CREATE_RETRIEVAL_METRICS,
    CREATE_RETRIEVAL_METRICS_IDX,
    CREATE_JOURNEY_PLANS,
    CREATE_JOURNEY_PLANS_IDX,
    CREATE_UNPACK_CACHE,
    CREATE_SHARE_LINKS,
    CREATE_SHARE_LINKS_LOOKUP_IDX,
    CREATE_READ_LATER_ITEMS,
    CREATE_READ_LATER_ITEMS_IDX,
    CREATE_LLM_CALL_LOG,
    CREATE_LLM_CALL_LOG_IDX,
    CREATE_CONVERSATION_MEMORY_VEC,
    CREATE_DOCUMENT_CHUNKS_VEC,
    CREATE_DOCUMENT_ATTACHMENT_SESSIONS,
    CREATE_RESTORE_LOG,
    CREATE_DATA_LOSS_REQUESTS,
    CREATE_DATA_LOSS_REQUESTS_IDX,
]
