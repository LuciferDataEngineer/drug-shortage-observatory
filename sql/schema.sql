PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    export_date TEXT NOT NULL,
    raw_rows INTEGER NOT NULL CHECK (raw_rows >= 0),
    accepted INTEGER NOT NULL CHECK (accepted >= 0),
    quarantined INTEGER NOT NULL CHECK (quarantined >= 0),
    CHECK (raw_rows = accepted + quarantined)
);
CREATE INDEX IF NOT EXISTS snapshots_by_date ON snapshots(export_date DESC);

CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    source_url TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    raw_bytes INTEGER NOT NULL CHECK (raw_bytes > 0),
    raw_path TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_by_snapshot
    ON observations(snapshot_id, accessed_at DESC, observation_id DESC);

-- The snapshot ordinal belongs to the first accepted acquisition of that content.
-- A later acquisition with reordered input has a separate observation mapping.
CREATE TABLE IF NOT EXISTS listings (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    raw_row_sha256 TEXT NOT NULL,
    projected_sha256 TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    generic_name TEXT NOT NULL,
    company_name TEXT,
    presentation TEXT,
    package_ndc TEXT,
    dosage_form TEXT,
    status TEXT NOT NULL CHECK (status IN ('Current','Resolved','To Be Discontinued')),
    availability TEXT,
    shortage_reason TEXT,
    initial_posting_date TEXT,
    update_date TEXT,
    discontinued_date TEXT,
    PRIMARY KEY(snapshot_id, ordinal)
);
CREATE INDEX IF NOT EXISTS listings_by_status ON listings(snapshot_id, status);
CREATE INDEX IF NOT EXISTS listings_by_generic ON listings(snapshot_id, generic_name);
CREATE INDEX IF NOT EXISTS listings_by_natural_key ON listings(snapshot_id, natural_key);
CREATE INDEX IF NOT EXISTS listings_by_projection ON listings(snapshot_id, projected_sha256);

CREATE TABLE IF NOT EXISTS categories (
    snapshot_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, ordinal, category),
    FOREIGN KEY(snapshot_id, ordinal) REFERENCES listings(snapshot_id, ordinal)
);
CREATE INDEX IF NOT EXISTS categories_by_name ON categories(snapshot_id, category);

CREATE TABLE IF NOT EXISTS quarantine (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    raw_row_sha256 TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, ordinal)
);

-- Each observed input row is retained by digest, including exact duplicates.
-- This mapping keeps raw ordinals auditable when content arrives in a new order.
CREATE TABLE IF NOT EXISTS observation_rows (
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    raw_row_sha256 TEXT NOT NULL,
    PRIMARY KEY(observation_id, ordinal)
);

CREATE VIEW IF NOT EXISTS current_snapshot AS
WITH observed AS (
    SELECT s.*, o.accessed_at, o.source_url, o.raw_sha256,
           ROW_NUMBER() OVER (
               ORDER BY s.export_date DESC, o.accessed_at DESC,
                        s.snapshot_id DESC, o.observation_id DESC
           ) AS choice
    FROM snapshots s JOIN observations o ON s.snapshot_id = o.snapshot_id
)
SELECT snapshot_id, export_date, raw_rows, accepted, quarantined,
       accessed_at, source_url, raw_sha256
FROM observed WHERE choice = 1;

CREATE VIEW IF NOT EXISTS current_listings AS
SELECT l.* FROM listings l JOIN current_snapshot c ON l.snapshot_id = c.snapshot_id;
