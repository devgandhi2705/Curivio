"""
Feed v2 schema — v2-owned tables + their migrations (Phase 3).

v2 owns its own DDL here, kept OUT of backend/database/schema.py so the two
feed generations never share table definitions. Applied via run_v2_migrations()
against the SAME curivio.db (feed_v2/db.get_connection). Every table carries
user_id TEXT NOT NULL, per the phase spec.

NAMING NOTE (flag for the Phase 3 JOIN test, kept from Phase 1):
    day_ref (existing llm_call_log column) and day_number (v2 tables here)
    refer to the SAME concept under different names. The JOIN test in
    tests/test_feed_v2_schema.py maps mas_runs.day_number to a run's child
    llm_call_log rows via trace_id (not via the day column) — day_ref stays
    the legacy name on llm_call_log, day_number is the v2 name on mas_runs.
"""

import sqlite3

# ── Orchestration: one row per multi-agent run ────────────────────────────────
CREATE_MAS_RUNS = """
CREATE TABLE IF NOT EXISTS mas_runs (
    trace_id         TEXT    PRIMARY KEY,
    surface          TEXT    NOT NULL CHECK(surface IN ('feed_v2','feed_legacy','chat')),
    user_id          TEXT    NOT NULL REFERENCES users(user_id),
    project_id       TEXT,
    day_number       INTEGER,
    status           TEXT    NOT NULL CHECK(status IN ('running','done','failed','partial')),
    lease_expires_at TEXT,
    started_at       TEXT    NOT NULL,
    ended_at         TEXT,
    total_calls      INTEGER DEFAULT 0,
    total_in_tokens  INTEGER DEFAULT 0,
    total_out_tokens INTEGER DEFAULT 0,
    degraded_reason  TEXT,
    input_manifest   TEXT,
    error            TEXT
);
"""

# At most one 'running' run per (project_id, day_number) — the lease/idempotency
# guard. Partial index so only running rows are constrained; done/failed/partial
# rows may repeat freely.
CREATE_MAS_RUNS_RUNNING_UNIQUE_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_mas_runs_running_unique
    ON mas_runs (project_id, day_number)
    WHERE status = 'running';
"""

# ── v2 projects ───────────────────────────────────────────────────────────────
CREATE_V2_PROJECTS = """
CREATE TABLE IF NOT EXISTS v2_projects (
    project_id       TEXT    PRIMARY KEY,
    user_id          TEXT    NOT NULL REFERENCES users(user_id),
    name             TEXT    NOT NULL DEFAULT '',
    description      TEXT    NOT NULL DEFAULT '',
    coverage_mode    TEXT,
    material_scope   TEXT,
    intent_confirmed INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# ── Materials (uploaded / linked source documents) ────────────────────────────
CREATE_V2_MATERIALS = """
CREATE TABLE IF NOT EXISTS v2_materials (
    material_id       TEXT    PRIMARY KEY,
    user_id           TEXT    NOT NULL REFERENCES users(user_id),
    project_id        TEXT    REFERENCES v2_projects(project_id),
    type              TEXT,
    filename          TEXT,
    url               TEXT,
    sha256            TEXT,
    extraction_status TEXT    NOT NULL DEFAULT 'pending',
    byte_size         INTEGER,
    created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_V2_MATERIAL_CHUNKS = """
CREATE TABLE IF NOT EXISTS v2_material_chunks (
    chunk_id     TEXT    PRIMARY KEY,
    user_id      TEXT    NOT NULL REFERENCES users(user_id),
    material_id  TEXT    NOT NULL REFERENCES v2_materials(material_id),
    project_id   TEXT,
    chunk_index  INTEGER NOT NULL DEFAULT 0,
    page_no      INTEGER,
    chunk_text   TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# sqlite-vec shadow for chunk embeddings — 3072-dim to match the app's other
# vec0 tables (conversation_memory_vec / document_chunks_vec). Auxiliary (+)
# columns mirror the row's owning ids so a vec search returns them directly.
CREATE_V2_MATERIAL_CHUNKS_VEC = """
CREATE VIRTUAL TABLE IF NOT EXISTS v2_material_chunks_vec USING vec0(
    embedding    float[3072],
    +chunk_id    TEXT,
    +material_id TEXT,
    +project_id  TEXT,
    +user_id     TEXT,
    +chunk_text  TEXT,
    +created_at  TEXT
);
"""

CREATE_V2_MATERIAL_FIGURES = """
CREATE TABLE IF NOT EXISTS v2_material_figures (
    figure_id      TEXT    PRIMARY KEY,
    user_id        TEXT    NOT NULL REFERENCES users(user_id),
    material_id    TEXT    NOT NULL REFERENCES v2_materials(material_id),
    project_id     TEXT,
    page_no        INTEGER,
    caption        TEXT,
    image_key      TEXT,
    embedding_ref  TEXT,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_V2_JOURNEY_PLANS = """
CREATE TABLE IF NOT EXISTS v2_journey_plans (
    plan_id      TEXT    PRIMARY KEY,
    user_id      TEXT    NOT NULL REFERENCES users(user_id),
    project_id   TEXT    NOT NULL REFERENCES v2_projects(project_id),
    day_start    INTEGER,
    day_end      INTEGER,
    plan_content TEXT    NOT NULL DEFAULT '{}',
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# One generated learning package per (project, day). sections holds structured
# JSON; action_completed_at is set when the learner marks the day's action done.
CREATE_V2_PACKAGES = """
CREATE TABLE IF NOT EXISTS v2_packages (
    package_id          TEXT    PRIMARY KEY,
    user_id             TEXT    NOT NULL REFERENCES users(user_id),
    project_id          TEXT    NOT NULL REFERENCES v2_projects(project_id),
    day_number          INTEGER,
    trace_id            TEXT,
    sections            TEXT    NOT NULL DEFAULT '{}',
    status              TEXT    NOT NULL DEFAULT 'draft',
    action_completed_at TEXT,
    created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_V2_PACKAGE_SOURCES = """
CREATE TABLE IF NOT EXISTS v2_package_sources (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT    NOT NULL REFERENCES users(user_id),
    package_id       TEXT    NOT NULL REFERENCES v2_packages(package_id),
    source_id        TEXT    NOT NULL,
    tier             TEXT,
    origin           TEXT,
    cited_in_sections TEXT   NOT NULL DEFAULT '[]',
    rank_score       REAL    NOT NULL DEFAULT 0.0,
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_V2_RETRIEVAL_CHECKS = """
CREATE TABLE IF NOT EXISTS v2_retrieval_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT    NOT NULL REFERENCES users(user_id),
    project_id      TEXT,
    package_id      TEXT    REFERENCES v2_packages(package_id),
    question        TEXT    NOT NULL,
    expected        TEXT,
    user_answer     TEXT,
    user_confidence TEXT,
    correct         INTEGER,
    answered_at     TEXT
);
"""

# Phase 11 — section_writer persists each of its FOUR writer groups the instant that
# group finishes, so a crash after group B does not require re-writing A/B on resume
# (sub-node crash-resume, mirroring Phase 7's node-level property). Keyed by
# (project, day, attempt, group): `attempt` = section_writer_runs+1 at node entry, stable
# across a crash (the crash never persisted the increment) but incremented on a rewrite
# (prior run returned first) — so a resume skips completed groups while a rewrite regenerates
# all four. sections_json holds that group's list of {n,title,beats:[...]} sections.
CREATE_V2_SECTION_DRAFTS = """
CREATE TABLE IF NOT EXISTS v2_section_drafts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       TEXT    NOT NULL REFERENCES users(user_id),
    project_id    TEXT    NOT NULL,
    day_number    INTEGER NOT NULL,
    attempt       INTEGER NOT NULL,
    group_key     TEXT    NOT NULL,
    sections_json TEXT    NOT NULL DEFAULT '[]',
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, day_number, attempt, group_key)
);
"""

CREATE_V2_MASTERY = """
CREATE TABLE IF NOT EXISTS v2_mastery (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        TEXT    NOT NULL REFERENCES users(user_id),
    project_id     TEXT    NOT NULL,
    concept        TEXT    NOT NULL,
    exposure_count INTEGER NOT NULL DEFAULT 0,
    check_results  TEXT    NOT NULL DEFAULT '[]',
    level          TEXT    NOT NULL DEFAULT 'new',
    next_review_at TEXT,
    updated_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, concept, user_id)
);
"""

# Secondary lookup indexes (non-unique) — cheap, help the common per-project reads.
CREATE_V2_PACKAGES_PROJECT_IDX = """
CREATE INDEX IF NOT EXISTS idx_v2_packages_project
    ON v2_packages (project_id, day_number);
"""
CREATE_V2_MATERIALS_PROJECT_IDX = """
CREATE INDEX IF NOT EXISTS idx_v2_materials_project
    ON v2_materials (project_id);
"""
CREATE_MAS_RUNS_USER_IDX = """
CREATE INDEX IF NOT EXISTS idx_mas_runs_user
    ON mas_runs (user_id, started_at DESC);
"""

# Order matters: base tables before the indexes / child tables that reference them.
V2_TABLES: list[str] = [
    CREATE_MAS_RUNS,
    CREATE_MAS_RUNS_RUNNING_UNIQUE_IDX,
    CREATE_MAS_RUNS_USER_IDX,
    CREATE_V2_PROJECTS,
    CREATE_V2_MATERIALS,
    CREATE_V2_MATERIALS_PROJECT_IDX,
    CREATE_V2_MATERIAL_CHUNKS,
    CREATE_V2_MATERIAL_CHUNKS_VEC,
    CREATE_V2_MATERIAL_FIGURES,
    CREATE_V2_JOURNEY_PLANS,
    CREATE_V2_PACKAGES,
    CREATE_V2_PACKAGES_PROJECT_IDX,
    CREATE_V2_PACKAGE_SOURCES,
    CREATE_V2_RETRIEVAL_CHECKS,
    CREATE_V2_SECTION_DRAFTS,
    CREATE_V2_MASTERY,
]

# Additive migrations on v2-owned tables. Phase 4 adds the material-ingestion
# signal columns to v2_materials: the extracted structure as JSON (step 1) plus
# the queryable coverage_mode signals Phase 5's profile agent filters on (step 6)
# — has_structure/section_count/type/count must be columns, not buried in JSON.
# extraction_error carries a corrupt-file failure reason (step 7) without wedging
# the project. All additive + nullable/defaulted.
MIGRATE_V2_MATERIALS_ADD_STRUCTURE_JSON   = "ALTER TABLE v2_materials ADD COLUMN structure_json TEXT"
MIGRATE_V2_MATERIALS_ADD_HAS_STRUCTURE    = "ALTER TABLE v2_materials ADD COLUMN has_structure INTEGER NOT NULL DEFAULT 0"
MIGRATE_V2_MATERIALS_ADD_SECTION_COUNT    = "ALTER TABLE v2_materials ADD COLUMN section_count INTEGER NOT NULL DEFAULT 0"
MIGRATE_V2_MATERIALS_ADD_EXTRACTION_ERROR = "ALTER TABLE v2_materials ADD COLUMN extraction_error TEXT"

# Phase 4b FLAG 2 — file storage is a DISTINCT outcome from text extraction. A
# document whose text extracted fine but whose figure images failed to upload to
# R2 must be queryable ('degraded') separately from full success ('ok'), so a
# lesson never cites a stored asset that isn't actually retrievable. NULL until
# an outcome is known (e.g. extraction failed, so storage was never attempted).
MIGRATE_V2_MATERIALS_ADD_STORAGE_STATUS = "ALTER TABLE v2_materials ADD COLUMN storage_status TEXT"

# Phase 5 — profile agent output on v2_projects. The full persona (legacy's 7
# fields) lives in profile_json; coverage_mode/material_scope already have columns
# (kept queryable so the confirmation screen and downstream retrieval read them
# without parsing JSON). coverage_reasoning is the one-sentence rationale shown to
# the user. profile_status makes a FAILED generation a visible, retryable state
# (NULL=never run, 'ready'=profile written, 'failed'=generation failed and NO fake
# profile was written) — the explicit anti-pattern reversal of legacy's silent
# {"persona":"Learner"} default.
# difficulty is a project input (create shape: name/description/difficulty) the
# profile agent reads and a profile retry must re-read — so it's persisted, not
# passed transiently.
MIGRATE_V2_PROJECTS_ADD_DIFFICULTY          = "ALTER TABLE v2_projects ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'intermediate'"
MIGRATE_V2_PROJECTS_ADD_PROFILE_JSON        = "ALTER TABLE v2_projects ADD COLUMN profile_json TEXT"
MIGRATE_V2_PROJECTS_ADD_COVERAGE_REASONING  = "ALTER TABLE v2_projects ADD COLUMN coverage_reasoning TEXT"
MIGRATE_V2_PROJECTS_ADD_PROFILE_STATUS      = "ALTER TABLE v2_projects ADD COLUMN profile_status TEXT"

# Phase 6 — journey planner. journey_shape is the project-level shape LOCK
# ('fixed_sequence' | 'rotating_theme'); once set it's reused for the next batch
# unless the description changes (same lock mechanism as legacy learning_projects.
# journey_shape). journey_status makes a FAILED planning attempt visible
# (NULL=never planned, 'ready'=a batch was written, 'failed'=attempt failed and NO
# fake plan was written) — same no-silent-fallback reversal as profile_status.
# On v2_journey_plans: shape carries each batch's shape (read per batch, as legacy
# journey_plans.shape did); description_hash powers the shape-lock freshness check.
MIGRATE_V2_PROJECTS_ADD_JOURNEY_SHAPE       = "ALTER TABLE v2_projects ADD COLUMN journey_shape TEXT"
MIGRATE_V2_PROJECTS_ADD_JOURNEY_STATUS      = "ALTER TABLE v2_projects ADD COLUMN journey_status TEXT"
MIGRATE_V2_JOURNEY_PLANS_ADD_SHAPE          = "ALTER TABLE v2_journey_plans ADD COLUMN shape TEXT"
MIGRATE_V2_JOURNEY_PLANS_ADD_DESC_HASH      = "ALTER TABLE v2_journey_plans ADD COLUMN description_hash TEXT"

V2_MIGRATIONS: list[str] = [
    MIGRATE_V2_MATERIALS_ADD_STRUCTURE_JSON,
    MIGRATE_V2_MATERIALS_ADD_HAS_STRUCTURE,
    MIGRATE_V2_MATERIALS_ADD_SECTION_COUNT,
    MIGRATE_V2_MATERIALS_ADD_EXTRACTION_ERROR,
    MIGRATE_V2_MATERIALS_ADD_STORAGE_STATUS,
    MIGRATE_V2_PROJECTS_ADD_DIFFICULTY,
    MIGRATE_V2_PROJECTS_ADD_PROFILE_JSON,
    MIGRATE_V2_PROJECTS_ADD_COVERAGE_REASONING,
    MIGRATE_V2_PROJECTS_ADD_PROFILE_STATUS,
    MIGRATE_V2_PROJECTS_ADD_JOURNEY_SHAPE,
    MIGRATE_V2_PROJECTS_ADD_JOURNEY_STATUS,
    MIGRATE_V2_JOURNEY_PLANS_ADD_SHAPE,
    MIGRATE_V2_JOURNEY_PLANS_ADD_DESC_HASH,
]


def run_v2_migrations(conn) -> None:
    """Create v2-owned tables/indexes then run v2 migrations, on an existing
    connection. Idempotent per-statement: V2_TABLES are CREATE ... IF NOT EXISTS,
    and each V2_MIGRATIONS ALTER swallows the "duplicate column" it raises on a
    re-run — same additive, re-runnable rule (and same guard substrings) as
    backend/database/schema.py's legacy migrations.
    """
    for statement in V2_TABLES:
        conn.execute(statement)
    for migration in V2_MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError as exc:
            if not any(p in str(exc).lower() for p in ("already exists", "duplicate column", "no such column")):
                raise
