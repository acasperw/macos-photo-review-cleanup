import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path("data/photo_review.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    uuid TEXT PRIMARY KEY,
    date TEXT,
    date_added TEXT,
    kind TEXT,
    original_filename TEXT,
    uti TEXT,
    width INTEGER,
    height INTEGER,
    filesize INTEGER,
    duration REAL,
    favorite INTEGER,
    hidden INTEGER,
    has_adjustments INTEGER,
    adjustment_editor TEXT,
    adjustment_format_id TEXT,
    user_edited INTEGER,
    screenshot INTEGER,
    screen_recording INTEGER,
    burst INTEGER,
    burst_key TEXT,
    burst_selected INTEGER,
    live_photo INTEGER,
    selfie INTEGER,
    portrait INTEGER,
    imported_by_app TEXT,
    imported_by_bundle TEXT,
    camera_make TEXT,
    camera_model TEXT,
    named_persons TEXT,
    unnamed_faces INTEGER,
    labels TEXT,
    scores TEXT,
    ai_caption TEXT,
    is_missing INTEGER,
    in_cloud INTEGER,
    shared INTEGER,
    syndicated INTEGER,
    original_path TEXT,
    derivative_path TEXT,
    scanned_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_assets_date ON assets(date);

CREATE TABLE IF NOT EXISTS analysis (
    uuid TEXT PRIMARY KEY REFERENCES assets(uuid),
    source_path TEXT,
    phash TEXT,
    brightness REAL,
    sharpness REAL,
    model TEXT,
    embedding BLOB,
    analyzed_at TEXT
);

CREATE TABLE IF NOT EXISTS clusters (
    uuid TEXT PRIMARY KEY REFERENCES assets(uuid),
    cluster_id INTEGER,
    is_keeper INTEGER,
    similarity REAL
);
CREATE INDEX IF NOT EXISTS idx_clusters_cluster ON clusters(cluster_id);

CREATE TABLE IF NOT EXISTS flags (
    uuid TEXT REFERENCES assets(uuid),
    category TEXT,
    confidence REAL,
    reason TEXT,
    PRIMARY KEY (uuid, category)
);

CREATE TABLE IF NOT EXISTS decisions (
    uuid TEXT REFERENCES assets(uuid),
    category TEXT,
    decision TEXT NOT NULL CHECK (decision IN ('remove', 'keep')),
    decided_at TEXT,
    applied_at TEXT,
    PRIMARY KEY (uuid, category)
);
"""


def connect(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, table: str, records: list[dict]) -> None:
    if not records:
        return
    cols = list(records[0])
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "uuid")
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT(uuid) DO UPDATE SET {updates}"
    )
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in records])
    conn.commit()


def prune_missing(
    conn: sqlite3.Connection, found: set[str], from_date: datetime, to_date: datetime | None
) -> list[str]:
    """Remove cached assets in the scanned date range that are no longer in Photos."""
    start = from_date.astimezone()
    end = to_date.astimezone() if to_date else None
    gone = [
        r["uuid"] for r in conn.execute("SELECT uuid, date FROM assets")
        if r["uuid"] not in found
        and start <= datetime.fromisoformat(r["date"]) and (end is None or datetime.fromisoformat(r["date"]) < end)
    ]
    with conn:
        for table in ("flags", "clusters", "decisions", "analysis", "assets"):
            conn.executemany(f"DELETE FROM {table} WHERE uuid = ?", [(u,) for u in gone])
    return gone
