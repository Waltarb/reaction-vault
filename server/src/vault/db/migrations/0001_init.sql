-- Reaction Vault initial schema.
-- Every change to items, tags or collections bumps meta.rev so clients can sync with ?since=<rev>.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO meta (key, value) VALUES ('rev', '0');

CREATE TABLE items (
    id          INTEGER PRIMARY KEY,
    sha256      TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL CHECK (kind IN ('image', 'animated', 'video')),
    mime        TEXT NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    duration_ms INTEGER,
    frame_count INTEGER,
    has_alpha   INTEGER NOT NULL DEFAULT 0,
    has_audio   INTEGER NOT NULL DEFAULT 0,
    bytes       INTEGER NOT NULL,
    phash       INTEGER,
    favorite    INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'upload',
    source_id   TEXT,
    source_url  TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at  TEXT,
    rev         INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX items_source ON items (source, source_id) WHERE source_id IS NOT NULL;
CREATE INDEX items_created ON items (created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX items_rev ON items (rev);
CREATE INDEX items_phash ON items (phash) WHERE phash IS NOT NULL;

CREATE TABLE tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE item_tags (
    item_id INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    origin  TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual', 'auto', 'source')),
    score   REAL,
    PRIMARY KEY (item_id, tag_id)
);
CREATE INDEX item_tags_tag ON item_tags (tag_id);

CREATE TABLE collections (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color      TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deleted_at TEXT,
    rev        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    item_id       INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    added_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (collection_id, item_id)
);
CREATE INDEX collection_items_item ON collection_items (item_id);

-- Derived files: thumb and preview (webp), send formats (mp4, gif). Sizes feed the "Send as" row.
CREATE TABLE renditions (
    item_id INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    kind    TEXT NOT NULL CHECK (kind IN ('thumb', 'preview', 'mp4', 'gif')),
    bytes   INTEGER,
    width   INTEGER,
    height  INTEGER,
    status  TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'failed')),
    PRIMARY KEY (item_id, kind)
);

-- One vec0 table per embedding model is created at runtime, named vec_<model key with '-' as '_'>.
CREATE TABLE embedding_models (
    key    TEXT PRIMARY KEY,
    dim    INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE items_fts USING fts5 (
    title,
    tags,
    source,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE jobs (
    id        INTEGER PRIMARY KEY,
    type      TEXT NOT NULL,
    item_id   INTEGER REFERENCES items (id) ON DELETE CASCADE,
    status    TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    attempts  INTEGER NOT NULL DEFAULT 0,
    error     TEXT,
    run_after TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX jobs_pending ON jobs (status, run_after);

CREATE TABLE devices (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen  TEXT
);

-- Files uploaded for the Save sheet and not yet committed.
CREATE TABLE staged (
    id         TEXT PRIMARY KEY,
    sha256     TEXT NOT NULL,
    meta_json  TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at TEXT NOT NULL
);
