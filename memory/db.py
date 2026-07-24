"""
SQLite-backed persistent memory store for JARVIS.

Replaces the flat-file JSON approach with a real database so that
memories survive across sessions, process restarts, and crashes.

Schema:
    memories(category TEXT, key TEXT, value TEXT, updated TEXT,
             PRIMARY KEY(category, key))

The public API mirrors what memory_manager.py expects:
    - load_memory()      → dict matching the old JSON structure
    - save_memory(mem)   → upsert all entries
    - update_memory(upd) → load → merge → save
    - forget(key, cat)   → delete one entry
"""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from threading import Lock

# ── Paths ──────────────────────────────────────────────────────────────────────

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR     = get_base_dir()
DB_PATH      = BASE_DIR / "memory" / "jarvis_memory.db"
JSON_PATH    = BASE_DIR / "memory" / "long_term.json"  # legacy, used for migration
MEDIA_DIR    = BASE_DIR / "memory" / "storage" / "media"

# ── Constants (mirrors memory_manager) ─────────────────────────────────────────

MAX_VALUE_LENGTH = 380
MEMORY_MAX_CHARS = 2200
VALID_CATEGORIES = ("identity", "preferences", "projects", "relationships", "wishes", "notes")

_lock = Lock()


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
    }


# ── Connection helper ──────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    """Open a connection with row factory and foreign keys enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create the schema if it doesn't exist. Called once at startup."""
    with _lock:
        conn = _connect()
        try:
            # ── Legacy textual memory (unchanged from original schema) ──────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    category   TEXT NOT NULL,
                    key        TEXT NOT NULL,
                    value      TEXT NOT NULL,
                    updated    TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (category, key)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_category "
                "ON memories(category)"
            )

            # ── People (face memory) ──────────────────────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS people (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT NOT NULL UNIQUE,
                    first_seen    TEXT NOT NULL,
                    last_seen     TEXT NOT NULL,
                    embedding_dim INTEGER NOT NULL,
                    metadata      TEXT,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_people_name ON people(name)"
            )

            # ── Person embeddings (multiple per person, float32 BLOBs) ────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS person_embeddings (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id  INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    embedding  BLOB NOT NULL,
                    source     TEXT,
                    confidence REAL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pe_person  ON person_embeddings(person_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pe_created ON person_embeddings(created_at)"
            )

            # ── Media files (images, videos, clips, frames) ──────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT NOT NULL,
                    file_path  TEXT NOT NULL,
                    duration   REAL,
                    width      INTEGER,
                    height     INTEGER,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    source     TEXT,
                    sha256     TEXT,
                    metadata   TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_type   ON media(media_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_sha256 ON media(sha256)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_media_created ON media(created_at)"
            )

            # ── Keyframes extracted from videos ──────────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS keyframes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id   INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                    media_time REAL NOT NULL,
                    file_path  TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kf_media ON keyframes(media_id)"
            )

            # ── Detected objects in media/keyframes ──────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS detected_objects (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id    INTEGER REFERENCES media(id) ON DELETE CASCADE,
                    keyframe_id INTEGER REFERENCES keyframes(id) ON DELETE CASCADE,
                    label       TEXT NOT NULL,
                    confidence  REAL,
                    bbox        TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_do_media  ON detected_objects(media_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_do_label  ON detected_objects(label)"
            )

            # ── Detected people in media/keyframes ───────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS detected_people (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id    INTEGER REFERENCES media(id) ON DELETE CASCADE,
                    keyframe_id INTEGER REFERENCES keyframes(id) ON DELETE CASCADE,
                    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    confidence  REAL,
                    bbox        TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dp_media   ON detected_people(media_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dp_person  ON detected_people(person_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dp_created ON detected_people(created_at)"
            )

            # ── OCR text extracted from media ────────────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ocr_text (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id    INTEGER REFERENCES media(id) ON DELETE CASCADE,
                    keyframe_id INTEGER REFERENCES keyframes(id) ON DELETE CASCADE,
                    text        TEXT NOT NULL,
                    bbox        TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ocr_media ON ocr_text(media_id)"
            )

            # ── Scene descriptions ───────────────────────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scene_descriptions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_id    INTEGER REFERENCES media(id) ON DELETE CASCADE,
                    keyframe_id INTEGER REFERENCES keyframes(id) ON DELETE CASCADE,
                    description TEXT NOT NULL,
                    model       TEXT,
                    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sd_media ON scene_descriptions(media_id)"
            )

            # ── Episodic memory events ───────────────────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type    TEXT NOT NULL,
                    title         TEXT NOT NULL,
                    description   TEXT,
                    started_at    TEXT NOT NULL,
                    ended_at      TEXT,
                    location      TEXT,
                    metadata      TEXT,
                    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_type    ON events(event_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_started ON events(started_at)"
            )

            # ── Junction: events ↔ media ─────────────────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_media (
                    event_id  INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    media_id  INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
                    role      TEXT,
                    PRIMARY KEY (event_id, media_id)
                )
                """
            )

            # ── Junction: events ↔ people ────────────────────────────────────
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_people (
                    event_id  INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
                    role      TEXT,
                    PRIMARY KEY (event_id, person_id)
                )
                """
            )

            conn.commit()
        finally:
            conn.close()


# ── Migration: JSON → SQLite (runs once, on first DB startup) ──────────────────

def _migrate_schema_columns(conn: sqlite3.Connection) -> None:
    """
    Add new columns to existing tables if they were created before
    the schema was extended.  Runs on every startup — safe to call
    repeatedly because we check pragma table_info first.
    """
    # memories.created_at
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if "created_at" not in cols:
        # SQLite ALTER TABLE ADD COLUMN doesn't support non-constant defaults,
        # so we add the column NULLable and back-fill existing rows.
        conn.execute("ALTER TABLE memories ADD COLUMN created_at TEXT")
        conn.execute(
            "UPDATE memories SET created_at = datetime('now') WHERE created_at IS NULL"
        )
        print("[Memory] Migrated: added created_at to memories")


def _migrate_from_json() -> bool:
    """
    If the DB is empty but long_term.json exists, import its contents.
    Returns True if migration happened.
    """
    if not JSON_PATH.exists():
        return False

    with _lock:
        conn = _connect()
        try:
            _migrate_schema_columns(conn)

            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            if count > 0:
                return False  # DB already has data — no migration needed

            try:
                data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"[Memory] ⚠️  Migration: could not read JSON: {e}")
                return False

            if not isinstance(data, dict):
                return False

            rows = []
            for cat, items in data.items():
                if cat not in VALID_CATEGORIES:
                    continue
                if not isinstance(items, dict):
                    continue
                for key, entry in items.items():
                    if isinstance(entry, dict) and "value" in entry:
                        rows.append((
                            cat,
                            key,
                            str(entry["value"]),
                            entry.get("updated", datetime.now().strftime("%Y-%m-%d")),
                        ))

            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO memories (category, key, value, updated) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
                conn.commit()
                print(f"[Memory] Migrated {len(rows)} entries from long_term.json")
            return True
        finally:
            conn.close()


# ── Core CRUD operations ───────────────────────────────────────────────────────

def db_load_memory() -> dict:
    """Load all memories from the database into the dict structure."""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT category, key, value, updated FROM memories ORDER BY category, key"
            ).fetchall()
        finally:
            conn.close()

    memory = _empty_memory()
    for row in rows:
        cat = row["category"]
        if cat not in memory:
            continue
        memory[cat][row["key"]] = {
            "value": row["value"],
            "updated": row["updated"],
        }
    return memory


def db_save_memory(memory: dict) -> None:
    """
    Replace all database contents with the given memory dict.
    Called after trimming to enforce size limits.
    """
    if not isinstance(memory, dict):
        return

    with _lock:
        conn = _connect()
        try:
            conn.execute("DELETE FROM memories")
            rows = []
            for cat, items in memory.items():
                if cat not in VALID_CATEGORIES:
                    continue
                if not isinstance(items, dict):
                    continue
                for key, entry in items.items():
                    if isinstance(entry, dict) and "value" in entry:
                        rows.append((
                            cat,
                            key,
                            str(entry["value"]),
                            entry.get("updated", datetime.now().strftime("%Y-%m-%d")),
                        ))
            if rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO memories (category, key, value, updated) "
                    "VALUES (?, ?, ?, ?)",
                    rows,
                )
            conn.commit()
        finally:
            conn.close()


def db_upsert(category: str, key: str, value: str, updated: str) -> None:
    """Insert or update a single memory entry."""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO memories (category, key, value, updated) "
                "VALUES (?, ?, ?, ?)",
                (category, key, value, updated),
            )
            conn.commit()
        finally:
            conn.close()


def db_delete(category: str, key: str) -> bool:
    """Delete a single memory entry. Returns True if a row was deleted."""
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM memories WHERE category = ? AND key = ?",
                (category, key),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def db_count() -> int:
    """Return total number of stored memory entries."""
    with _lock:
        conn = _connect()
        try:
            return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        finally:
            conn.close()


# ── Startup initializer ────────────────────────────────────────────────────────

def ensure_db_ready() -> None:
    """
    Call this at application startup.
    Creates the schema, migrates any legacy JSON data, and ensures
    the media storage directory exists.
    """
    init_db()
    _migrate_from_json()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
