"""
SQLite persistence. Source of truth for finalized episodes.

Schema additions (Phase 1):
  - capture_leases: per-window consent state
  - observation_gaps: structured gaps in observation history
  - session_state: key/value store for epoch and dirty-shutdown flag

Schema additions (Phase 2):
  - episodes.activity_classification
  - episodes.classification_confidence
  - episodes.has_inference_failure

Schema additions (Phase 6 — encryption):
  - When PRIVATE_MODE=true, database is encrypted at rest using apsw-sqlite3mc.
  - Key is stored in the OS keychain (macOS Keychain / Windows Credential Manager).
  - Fails closed: if apsw unavailable in PRIVATE_MODE → RuntimeError (no plaintext fallback).
"""
import json
import platform
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional

import config
from episode import Episode, KeyObservation

# Service name used for keychain storage
_KEYCHAIN_SERVICE = "com.buildharvey.agent"
_KEYCHAIN_ACCOUNT = "db-encryption-key"


_SQLITE_PLAINTEXT_HEADER = b'SQLite format 3\x00'


class _APSWCompatWrapper:
    """
    Wraps apsw.Connection to expose the sqlite3.Connection API subset used by
    database.py and all callers: consent_manager, weekly_report, main, app.

    The APSW connection is the actual encrypted connection for its entire lifetime —
    stdlib sqlite3 is never used when PRIVATE_MODE=true.

    commit() translates to an explicit COMMIT statement.  DDL auto-commits in
    SQLite so the resulting apsw.SQLError ('cannot commit — no transaction is
    active') is swallowed; it is not an error condition.
    """

    def __init__(self, apsw_conn) -> None:
        self._conn = apsw_conn

    def execute(self, sql: str, parameters=()):
        if parameters:
            return self._conn.execute(sql, parameters)
        return self._conn.execute(sql)

    def commit(self) -> None:
        try:
            self._conn.execute("COMMIT")
        except Exception:
            pass  # no active transaction (DDL auto-committed) — expected

    def close(self) -> None:
        self._conn.close()


def _detect_db_state(db_path) -> str:
    """
    Returns 'new', 'plaintext', or 'encrypted'.

    'new'       — file absent or zero-length; safe to create a fresh encrypted DB
    'plaintext' — file starts with the SQLite3 plaintext magic; needs rekey migration
    'encrypted' — file exists, non-empty, header is NOT the plaintext SQLite3 magic
    """
    path = Path(str(db_path))
    if not path.exists() or path.stat().st_size == 0:
        return 'new'
    with open(path, 'rb') as f:
        header = f.read(16)
    if header == _SQLITE_PLAINTEXT_HEADER:
        return 'plaintext'
    return 'encrypted'


def _migrate_plaintext_to_encrypted(db_path: Path, key: str) -> None:
    """
    One-time in-place encryption of an existing plaintext BuildHarvey database.

    Safety contract:
    - An atomic backup is created before any mutation.
    - The backup is removed only after the full encrypt + verify + stdlib-block
      chain succeeds.
    - Raises RuntimeError on any failure; backup is preserved for manual recovery.
    - PRAGMA rekey must not execute inside a transaction (SQLite3MC requirement);
      this function opens a fresh connection with no prior statements.
    """
    import apsw as _apsw
    import sqlite3 as _sqlite3

    backup_path = db_path.with_suffix(db_path.suffix + '.plaintext_backup')
    shutil.copy2(str(db_path), str(backup_path))

    try:
        # Step 1: Open plaintext, verify readable, apply rekey.
        conn = _apsw.Connection(str(db_path))
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchall()
        except Exception as exc:
            conn.close()
            raise RuntimeError(
                f"Plaintext migration: cannot read existing database: {exc}"
            ) from exc

        result = list(conn.execute(f"PRAGMA rekey='{key}'"))
        conn.close()

        if result and result[0][0] != 'ok':
            raise RuntimeError(
                f"Plaintext migration: PRAGMA rekey returned unexpected result: {result}"
            )

        # Step 2: Verify encrypted re-open succeeds.
        conn2 = _apsw.Connection(str(db_path))
        conn2.execute(f"PRAGMA key='{key}'")
        try:
            conn2.execute("SELECT count(*) FROM sqlite_master").fetchall()
        except Exception as exc:
            conn2.close()
            raise RuntimeError(
                f"Plaintext migration: encrypted re-open failed: {exc}"
            ) from exc
        conn2.close()

        # Step 3: Verify stdlib sqlite3 can no longer read the database.
        try:
            plain = _sqlite3.connect(str(db_path))
            plain.execute("SELECT * FROM sqlite_master").fetchall()
            plain.close()
            raise RuntimeError(
                "Plaintext migration: database still readable without key — "
                "encryption did not take effect. Backup preserved."
            )
        except _sqlite3.DatabaseError:
            pass  # expected: "file is not a database"

        # Step 4: All checks passed — remove backup.
        backup_path.unlink(missing_ok=True)

    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"Plaintext encryption migration failed: {exc}"
        ) from exc


def connect():
    """Return a database connection.  In PRIVATE_MODE returns an _APSWCompatWrapper
    (apsw-backed, encrypted); otherwise returns a plain sqlite3.Connection."""
    if config.PRIVATE_MODE:
        return _connect_encrypted()
    conn = sqlite3.connect(str(config.DB_PATH))
    # WAL mode: allows concurrent reads while writing, survives crashes cleanly.
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    _migrate(conn)
    return conn


def _connect_encrypted() -> '_APSWCompatWrapper':
    """
    Open (or create) an encrypted SQLite database using apsw-sqlite3mc.

    The APSW connection is kept for the entire lifetime of the returned wrapper.
    stdlib sqlite3 is NEVER used for the encrypted connection.

    State machine:
      new       → create fresh encrypted DB (PRAGMA key on empty file)
      plaintext → one-time PRAGMA rekey migration, then open encrypted
      encrypted → open with PRAGMA key, verify readable

    Raises RuntimeError:
      - if apsw-sqlite3mc is unavailable (Private Mode requires encryption)
      - if key application or verification fails
      - if plaintext migration fails (backup preserved at <db>.plaintext_backup)
    """
    try:
        import apsw as _apsw  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "apsw-sqlite3mc is required when PRIVATE_MODE=true but is not installed. "
            "Install it with: pip install apsw-sqlite3mc"
        ) from exc

    key = _get_or_create_keychain_key()
    db_path = Path(str(config.DB_PATH))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    state = _detect_db_state(db_path)

    if state == 'plaintext':
        _migrate_plaintext_to_encrypted(db_path, key)

    # Open (or create) the encrypted database via apsw-sqlite3mc.
    conn = _apsw.Connection(str(db_path))
    conn.execute(f"PRAGMA key='{key}'")

    # Verify the key works before proceeding — fail closed if it does not.
    try:
        conn.execute("SELECT count(*) FROM sqlite_master").fetchall()
    except Exception as exc:
        conn.close()
        raise RuntimeError(
            "Unable to unlock encrypted BuildHarvey database. "
            "The key may be incorrect or the database may be corrupted."
        ) from exc

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")

    wrapper = _APSWCompatWrapper(conn)
    _migrate(wrapper)
    return wrapper


def _get_or_create_keychain_key() -> str:
    """
    Retrieve the database encryption key from the OS keychain.
    Creates a new random key and stores it if none exists.
    Returns the key as a hex string.
    """
    existing = _keychain_read()
    if existing:
        return existing
    import secrets
    key = secrets.token_hex(32)   # 256-bit key
    _keychain_write(key)
    return key


def _keychain_read() -> Optional[str]:
    """Read the encryption key from the OS keychain. Returns None if not found."""
    if platform.system() == "Darwin":
        try:
            import Security  # type: ignore[import]  # pyobjc-framework-Security
            status, item, data = Security.SecKeychainFindGenericPassword(
                None, len(_KEYCHAIN_SERVICE), _KEYCHAIN_SERVICE,
                len(_KEYCHAIN_ACCOUNT), _KEYCHAIN_ACCOUNT,
            )
            if status == 0 and data:
                return data.decode("utf-8")
        except Exception:
            pass
        # Fallback: use keyring if Security framework unavailable
        try:
            import keyring
            return keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT) or None
        except Exception:
            pass
        # Final fallback: use the macOS `security` CLI (always available on macOS)
        try:
            import subprocess
            result = subprocess.run(
                ["security", "find-generic-password",
                 "-s", _KEYCHAIN_SERVICE, "-a", _KEYCHAIN_ACCOUNT, "-w"],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None
    elif platform.system() == "Windows":
        try:
            import win32cred  # type: ignore[import]
            cred = win32cred.CredRead(
                TargetName=f"{_KEYCHAIN_SERVICE}/{_KEYCHAIN_ACCOUNT}",
                Type=win32cred.CRED_TYPE_GENERIC,
            )
            return cred["CredentialBlob"].decode("utf-8")
        except Exception:
            return None
    else:
        try:
            import keyring
            return keyring.get_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT) or None
        except Exception:
            return None


def _keychain_write(key: str) -> None:
    """Write the encryption key to the OS keychain."""
    if platform.system() == "Darwin":
        try:
            import Security  # type: ignore[import]
            Security.SecKeychainAddGenericPassword(
                None, len(_KEYCHAIN_SERVICE), _KEYCHAIN_SERVICE,
                len(_KEYCHAIN_ACCOUNT), _KEYCHAIN_ACCOUNT,
                len(key), key.encode("utf-8"),
            )
            return
        except Exception:
            pass
        try:
            import keyring
            keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT, key)
            return
        except Exception:
            pass
        # Final fallback: use the macOS `security` CLI (always available on macOS)
        # -U updates an existing entry rather than failing if it already exists.
        try:
            import subprocess
            subprocess.run(
                ["security", "add-generic-password",
                 "-s", _KEYCHAIN_SERVICE, "-a", _KEYCHAIN_ACCOUNT,
                 "-w", key, "-U"],
                check=True, capture_output=True,
            )
            return
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            import win32cred  # type: ignore[import]
            win32cred.CredWrite({
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": f"{_KEYCHAIN_SERVICE}/{_KEYCHAIN_ACCOUNT}",
                "CredentialBlob": key.encode("utf-8"),
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            }, 0)
        except Exception:
            pass
    else:
        try:
            import keyring
            keyring.set_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT, key)
        except Exception:
            pass


def _delete_keychain_key() -> None:
    """Remove the encryption key from the OS keychain (used during delete_all_local_data)."""
    if platform.system() == "Darwin":
        try:
            import Security  # type: ignore[import]
            Security.SecKeychainFindAndDelete(
                None, len(_KEYCHAIN_SERVICE), _KEYCHAIN_SERVICE,
                len(_KEYCHAIN_ACCOUNT), _KEYCHAIN_ACCOUNT,
            )
            return
        except Exception:
            pass
        try:
            import keyring
            keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
            return
        except Exception:
            pass
        # Final fallback: use the macOS `security` CLI
        try:
            import subprocess
            subprocess.run(
                ["security", "delete-generic-password",
                 "-s", _KEYCHAIN_SERVICE, "-a", _KEYCHAIN_ACCOUNT],
                capture_output=True,
            )
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            import win32cred  # type: ignore[import]
            win32cred.CredDelete(
                TargetName=f"{_KEYCHAIN_SERVICE}/{_KEYCHAIN_ACCOUNT}",
                Type=win32cred.CRED_TYPE_GENERIC,
            )
        except Exception:
            pass
    else:
        try:
            import keyring
            keyring.delete_password(_KEYCHAIN_SERVICE, _KEYCHAIN_ACCOUNT)
        except Exception:
            pass


def save_episode(
    conn: sqlite3.Connection,
    episode: Episode,
    activity_classification: Optional[str] = None,
    classification_confidence: Optional[float] = None,
    has_inference_failure: bool = False,
) -> None:
    d = episode.to_dict()
    conn.execute("""
        INSERT INTO episodes
            (id, case_name, issue_worked_on, work_type, started_at, ended_at,
             duration_minutes, active_seconds, key_observations, created_at, is_reportable,
             activity_classification, classification_confidence, has_inference_failure)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            case_name                = excluded.case_name,
            issue_worked_on          = excluded.issue_worked_on,
            work_type                = excluded.work_type,
            ended_at                 = excluded.ended_at,
            duration_minutes         = excluded.duration_minutes,
            active_seconds           = excluded.active_seconds,
            key_observations         = excluded.key_observations,
            activity_classification  = excluded.activity_classification,
            classification_confidence = excluded.classification_confidence,
            has_inference_failure    = excluded.has_inference_failure
    """, (
        d["id"], d["case_name"], d.get("issue_worked_on"), d.get("work_type", "project"),
        d["started_at"], d["ended_at"],
        d["duration_minutes"], d.get("active_seconds"),
        json.dumps(d["key_observations"]), d["created_at"],
        activity_classification, classification_confidence,
        1 if has_inference_failure else 0,
    ))
    conn.commit()

    # Update recent contexts for autocomplete
    if d.get("case_name"):
        upsert_recent_context(conn, d["case_name"], d.get("issue_worked_on"), d.get("work_type", "project"))


def mark_synced(conn: sqlite3.Connection, episode_id: str) -> None:
    conn.execute(
        "UPDATE episodes SET synced_at = ? WHERE id = ?",
        (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), episode_id),
    )
    conn.commit()


def mark_invalid_episodes(conn: sqlite3.Connection) -> list[str]:
    """
    Mark (not delete) episodes that fail validity checks.
    Logs each affected record before updating. Returns list of affected IDs.
    Administrative episodes are NOT marked invalid — they are valid when evidence exists.
    """
    invalid_conditions = """
        TRIM(case_name) = '' OR case_name IS NULL
        OR key_observations = '[]' OR key_observations IS NULL
        OR duration_minutes IS NULL
        OR (duration_minutes < 0.5 AND (key_observations = '[]' OR key_observations IS NULL))
        OR LOWER(TRIM(case_name)) IN (
            'optional','file edit','sql editor','new tab',
            'file path','matter of','case reset','case requests',
            'summarizing timeline','new yo','active session',
            '• instagram d','quenlin blackwell •'
        )
    """
    rows = conn.execute(
        f"SELECT id, case_name, duration_minutes FROM episodes WHERE {invalid_conditions}"
    ).fetchall()

    if not rows:
        return []

    ids = [r[0] for r in rows]
    for r in rows:
        dur = r[2] if r[2] is not None else 0
        print(f"[db] marking invalid: '{r[1]}' ({dur:.1f}min) id={r[0][:8]}")

    placeholders = ",".join("?" * len(ids))
    conn.execute(
        f"UPDATE episodes SET is_reportable = 0 WHERE id IN ({placeholders})",
        ids,
    )
    conn.commit()
    return ids


def get_invalid_ids(conn: sqlite3.Connection) -> list[str]:
    """Return IDs of all episodes marked is_reportable=0."""
    rows = conn.execute(
        "SELECT id FROM episodes WHERE is_reportable = 0"
    ).fetchall()
    return [r[0] for r in rows]


# ── Recent contexts (for UI autocomplete) ─────────────────────────────────────

def get_recent_cases(conn: sqlite3.Connection) -> list[str]:
    """Return case names ordered by most recently used."""
    rows = conn.execute(
        "SELECT case_name FROM recent_contexts ORDER BY last_used DESC LIMIT 50"
    ).fetchall()
    return [r[0] for r in rows]


def get_recent_issues(conn: sqlite3.Connection, case_name: str) -> list[str]:
    """Return issue names for a given case, ordered by most recently used."""
    rows = conn.execute(
        "SELECT issue FROM recent_contexts WHERE case_name = ? AND issue != '' "
        "ORDER BY last_used DESC LIMIT 20",
        (case_name,),
    ).fetchall()
    return [r[0] for r in rows]


def upsert_recent_context(
    conn: sqlite3.Connection,
    case_name: str,
    issue: Optional[str],
    work_type: str,
) -> None:
    """Insert or update a recent context record for autocomplete."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Use empty string as sentinel for NULL issue so the UNIQUE(case_name, issue) works.
    issue_key = issue or ""
    conn.execute("""
        INSERT INTO recent_contexts (case_name, issue, work_type, last_used, use_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(case_name, issue) DO UPDATE SET
            last_used = excluded.last_used,
            use_count = use_count + 1
    """, (case_name, issue_key, work_type, now))
    conn.commit()


# ── Observation gaps ──────────────────────────────────────────────────────────

def open_gap(
    conn: sqlite3.Connection,
    cause: str,
    prev_episode_id: Optional[str] = None,
) -> str:
    """
    Record the start of an observation gap. Returns the gap ID.

    cause values:
      'device_locked' | 'user_logged_out' | 'session_switched'
      'app_restarted' | 'app_crashed' | 'permission_revoked'
      'window_not_consented' | 'capture_api_failed' | 'inference_failed'
      'observer_paused' | 'user_paused'
    """
    gap_id = _new_id()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        INSERT INTO observation_gaps
            (id, started_at, ended_at, cause, prev_episode_id, next_episode_id,
             resolution, user_note, created_at)
        VALUES (?, ?, NULL, ?, ?, NULL, 'unresolved', NULL, ?)
        """,
        (gap_id, now, cause, prev_episode_id, now),
    )
    conn.commit()
    return gap_id


def close_gap(
    conn: sqlite3.Connection,
    gap_id: str,
    next_episode_id: Optional[str] = None,
    resolution: str = "accepted_gap",
) -> None:
    """Mark an open gap as closed."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    conn.execute(
        """
        UPDATE observation_gaps
        SET ended_at = ?, next_episode_id = ?, resolution = ?
        WHERE id = ?
        """,
        (now, next_episode_id, resolution, gap_id),
    )
    conn.commit()


def mark_dirty_shutdown(conn: sqlite3.Connection) -> None:
    """
    Set dirty_shutdown=1 in session_state.
    Called at startup (before any recording begins) so a crash leaves this set.
    """
    conn.execute(
        "INSERT INTO session_state (key, value) VALUES ('dirty_shutdown', '1')"
        " ON CONFLICT(key) DO UPDATE SET value = '1'",
    )
    conn.commit()


def mark_clean_shutdown(conn: sqlite3.Connection) -> None:
    """Set dirty_shutdown=0. Called on clean exit."""
    conn.execute(
        "INSERT INTO session_state (key, value) VALUES ('dirty_shutdown', '0')"
        " ON CONFLICT(key) DO UPDATE SET value = '0'",
    )
    conn.commit()


def check_dirty_shutdown(conn: sqlite3.Connection) -> bool:
    """Return True if the previous session crashed (dirty_shutdown=1)."""
    row = conn.execute(
        "SELECT value FROM session_state WHERE key = 'dirty_shutdown'"
    ).fetchone()
    return row is not None and row[0] == "1"


def annotate_gap(conn: sqlite3.Connection, gap_id: str, note: str) -> None:
    """
    Attach a user note to a gap. Notes are metadata only — they never create
    or modify Episode records. Historical evidence that never existed cannot
    be retroactively inserted.
    """
    conn.execute(
        "UPDATE observation_gaps SET resolution = 'user_annotated', user_note = ? WHERE id = ?",
        (note, gap_id),
    )
    conn.commit()


# ── Data deletion (Phase 2) ───────────────────────────────────────────────────

def delete_all_local_data(conn: sqlite3.Connection) -> None:
    """
    Irreversibly delete all BuildHarvey local data.

    Covers:
      - SQLite DB + WAL/SHM files
      - ~/.buildharvey/screenshots/ tree
      - ~/.buildharvey/_current.png, _prev.png
      - ~/.buildharvey/weekly_reports/ directory
      - OS keychain entry for encryption key (Private Mode only)

    Caller is responsible for exiting the application after this call.
    Cloud data does not exist in Private Mode (by construction); no remote
    deletion is needed or possible from this function.
    """
    try:
        conn.close()
    except Exception:
        pass

    db_path = Path(str(config.DB_PATH))
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass
        # WAL and SHM files
        for suffix in ("-wal", "-shm"):
            p = db_path.with_suffix(db_path.suffix + suffix)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    screenshots_dir = Path(str(config.SCREENSHOTS_DIR))
    if screenshots_dir.exists():
        try:
            shutil.rmtree(str(screenshots_dir))
        except Exception:
            pass

    for temp_path in (config.TEMP_FRAME_PATH, config.PREV_FRAME_PATH):
        p = Path(str(temp_path))
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    # Weekly reports directory
    weekly_reports_dir = config.BASE_DIR / "weekly_reports"
    if weekly_reports_dir.exists():
        try:
            shutil.rmtree(str(weekly_reports_dir))
        except Exception:
            pass

    # OS keychain entry for database encryption key (Private Mode only)
    if config.PRIVATE_MODE:
        try:
            _delete_keychain_key()
        except Exception:
            pass


# ── Startup retention enforcement (Phase 2) ───────────────────────────────────

def purge_stale_temp_frames() -> None:
    """
    Delete temp frames older than SCREENSHOT_RETENTION_HOURS.
    Run at startup as a crash safety net — frames that survived a crash
    are deleted before the new session begins.
    """
    import os
    cutoff = time.time() - config.SCREENSHOT_RETENTION_HOURS * 3600
    for p in (config.TEMP_FRAME_PATH, config.PREV_FRAME_PATH):
        path = Path(str(p))
        if path.exists():
            try:
                if os.path.getmtime(str(path)) < cutoff:
                    path.unlink()
            except Exception:
                pass

    screenshots_dir = Path(str(config.SCREENSHOTS_DIR))
    if screenshots_dir.exists():
        for f in screenshots_dir.iterdir():
            if f.is_file():
                try:
                    if os.path.getmtime(str(f)) < cutoff:
                        f.unlink()
                except Exception:
                    pass


# ── Schema management ─────────────────────────────────────────────────────────

def _migrate(conn: sqlite3.Connection) -> None:
    """Create or migrate all tables to the current schema."""
    _migrate_episodes(conn)
    _migrate_phase1_tables(conn)


def _migrate_episodes(conn: sqlite3.Connection) -> None:
    """Create or migrate the episodes table."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(episodes)").fetchall()}

    # Recreate if table is missing, has old v1 schema, or has stale screenshots column
    needs_recreate = cols and ("case_name" not in cols or "screenshots" in cols)
    if needs_recreate:
        print("[db] migrating episodes table to current schema")
        conn.execute("DROP TABLE IF EXISTS episodes")
        cols = set()

    if not cols:
        conn.execute("""
            CREATE TABLE episodes (
                id                       TEXT PRIMARY KEY,
                case_name                TEXT NOT NULL,
                issue_worked_on          TEXT,
                work_type                TEXT NOT NULL DEFAULT 'project',
                started_at               TEXT NOT NULL,
                ended_at                 TEXT,
                duration_minutes         REAL,
                active_seconds           REAL,
                key_observations         TEXT NOT NULL DEFAULT '[]',
                created_at               TEXT NOT NULL,
                synced_at                TEXT,
                is_reportable            INTEGER NOT NULL DEFAULT 1,
                activity_classification  TEXT,
                classification_confidence REAL,
                has_inference_failure    INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()
    else:
        # Add missing columns to existing installations
        for col, ddl in [
            ("is_reportable",            "ALTER TABLE episodes ADD COLUMN is_reportable INTEGER NOT NULL DEFAULT 1"),
            ("issue_worked_on",          "ALTER TABLE episodes ADD COLUMN issue_worked_on TEXT"),
            ("work_type",                "ALTER TABLE episodes ADD COLUMN work_type TEXT NOT NULL DEFAULT 'project'"),
            ("active_seconds",           "ALTER TABLE episodes ADD COLUMN active_seconds REAL"),
            ("activity_classification",  "ALTER TABLE episodes ADD COLUMN activity_classification TEXT"),
            ("classification_confidence","ALTER TABLE episodes ADD COLUMN classification_confidence REAL"),
            ("has_inference_failure",    "ALTER TABLE episodes ADD COLUMN has_inference_failure INTEGER NOT NULL DEFAULT 0"),
        ]:
            if col not in cols:
                print(f"[db] adding column: {col}")
                conn.execute(ddl)
        conn.commit()

    # Create recent_contexts table for UI autocomplete.
    # issue uses '' as sentinel for "no issue" so UNIQUE(case_name, issue) works
    # across all SQLite versions (COALESCE in UNIQUE is only in SQLite 3.38+).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recent_contexts (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            case_name TEXT NOT NULL,
            issue     TEXT NOT NULL DEFAULT '',
            work_type TEXT NOT NULL DEFAULT 'project',
            last_used TEXT NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 1,
            UNIQUE(case_name, issue)
        )
    """)
    conn.commit()


def _migrate_phase1_tables(conn: sqlite3.Connection) -> None:
    """Create Phase 1 tables: capture_leases, observation_gaps, session_state."""

    # Per-window consent leases
    conn.execute("""
        CREATE TABLE IF NOT EXISTS capture_leases (
            id                  TEXT PRIMARY KEY,
            bundle_id           TEXT NOT NULL,
            window_id           INTEGER NOT NULL,
            owner_pid           INTEGER NOT NULL,
            process_start_time  REAL NOT NULL,
            session_epoch       INTEGER NOT NULL,
            app_name            TEXT NOT NULL DEFAULT '',
            window_title        TEXT NOT NULL DEFAULT '',
            state               TEXT NOT NULL,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        )
    """)

    # Structured gaps in observation history
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observation_gaps (
            id              TEXT PRIMARY KEY,
            started_at      TEXT NOT NULL,
            ended_at        TEXT,
            cause           TEXT NOT NULL,
            prev_episode_id TEXT REFERENCES episodes(id),
            next_episode_id TEXT REFERENCES episodes(id),
            resolution      TEXT NOT NULL DEFAULT 'unresolved',
            user_note       TEXT,
            created_at      TEXT NOT NULL
        )
    """)

    # Key/value store for session epoch and dirty-shutdown flag
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    conn.commit()


def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())
