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
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CHAT_MESSAGES_IDX = """
CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages (session_id, created_at);
"""

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
    focus_areas              TEXT    NOT NULL DEFAULT '[]',
    color                    TEXT    NOT NULL DEFAULT 'blue',
    preferred_sources        TEXT    NOT NULL DEFAULT '[]',
    ignored_sources          TEXT    NOT NULL DEFAULT '[]',
    daily_core_article_count INTEGER NOT NULL DEFAULT 4,
    created_at               TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# Migration: add preferred_sources to existing databases that pre-date this column.
# db.py runs these with try/except so duplicate-column errors are silently ignored.
MIGRATE_ADD_PREFERRED_SOURCES = (
    "ALTER TABLE learning_projects ADD COLUMN preferred_sources TEXT NOT NULL DEFAULT '[]'"
)

MIGRATE_ADD_DAILY_CORE_ARTICLE_COUNT = (
    "ALTER TABLE learning_projects ADD COLUMN daily_core_article_count INTEGER NOT NULL DEFAULT 4"
)

MIGRATE_ADD_IGNORED_SOURCES = (
    "ALTER TABLE learning_projects ADD COLUMN ignored_sources TEXT NOT NULL DEFAULT '[]'"
)

CREATE_PROJECT_INSIGHTS = """
CREATE TABLE IF NOT EXISTS project_insights (
    id           INTEGER   PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT      NOT NULL REFERENCES learning_projects(project_id) ON DELETE CASCADE,
    day_number   INTEGER   NOT NULL DEFAULT 1,
    insight_json TEXT      NOT NULL,
    generated_at TEXT      NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                             CHECK(interaction_type IN ('ask_about', 'continue_research', 'deep_research')),
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

CREATE_PASSWORD_RESET_TOKENS = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT    NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    token      TEXT    NOT NULL UNIQUE,
    expires_at TEXT    NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT    NOT NULL,
    package_day   INTEGER NOT NULL DEFAULT 0,
    overall_score REAL    NOT NULL DEFAULT 0.0,
    scores_json   TEXT    NOT NULL DEFAULT '{}',
    issues_json   TEXT    NOT NULL DEFAULT '[]',
    recs_json     TEXT    NOT NULL DEFAULT '[]',
    evaluated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_LEARNING_EVALUATIONS_IDX = """
CREATE INDEX IF NOT EXISTS idx_learning_evaluations_project
    ON learning_evaluations (project_id, evaluated_at DESC);
"""

MIGRATIONS = [
    MIGRATE_ADD_PREFERRED_SOURCES,
    MIGRATE_ADD_DAILY_CORE_ARTICLE_COUNT,
    MIGRATE_ADD_IGNORED_SOURCES,
    MIGRATE_ADD_CHAT_SESSION_CONVERSATION_MODE,
    MIGRATE_FEED_CHAT_LINKS_ADD_EXPLAIN_SIMPLY,
    MIGRATE_ADD_USER_ID_PROJECTS,
    MIGRATE_ADD_USER_ID_CHAT_SESSIONS,
    MIGRATE_ADD_USER_ID_BOOKMARK_COLLECTIONS,
    MIGRATE_ADD_USER_ID_PREFERENCES,
    MIGRATE_ADD_USER_ID_CONCEPT_MEMORY,
    MIGRATE_ADD_USER_ID_PRIOR_RECS,
    MIGRATE_ADD_TITLE_PATTERNS_USED,
    MIGRATE_ADD_OPENING_HOOKS_USED,
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
]
