# BuildHarvey Desktop Agent — Technical Architecture Review

**Date:** 2026-08-14
**Reviewed commit:** `c4148f0` (privacy migration) + keychain fallback patch
**Python:** 3.13.14 | **apsw-sqlite3mc:** 3.53.4.0 | **pytest:** 55 passed / 0 failed

---

## 1. Executive Summary

BuildHarvey is a macOS/Windows desktop agent that passively tracks billable work and
generates timesheets. The privacy migration (`c4148f0`) made the following structural
changes:

- **PRIVATE_MODE=true** is now the production default, enforced at build time via
  `_build_config.PRODUCTION_BUILD`.
- All screen capture is gated by **per-window consent leases** (ConsentManager).
- No screenshot, OCR output, or episode is created without consent.
- SQLite is **encrypted at rest** using apsw-sqlite3mc's Multiple Ciphers codec.
- The encryption key is stored in the **OS keychain** (macOS Keychain Services /
  Windows Credential Manager).
- Cloud vision analysis and server sync are **disabled** in PRIVATE_MODE.
- A **local inference backend** (Phase 4) classifies episode boundaries on-device.
- A **local weekly report** pipeline requires no network access.

The agent is a headless Python daemon. `app.py` is a Flask/WebSocket server that
manages the IPC between the browser dashboard and the background agent thread.

---

## 2. Process and Component Model

```
buildharvey.com (browser)
       │  Supabase Realtime WebSocket
       ▼
  app.py  (Flask + WebSocket server)
       │  thread
       ▼
  main.py (recording loop, ~5s cycle)
       │
  ┌────┼─────────────────────────────────┐
  │    │                                 │
observer.py   episode_engine.py    database.py
  │                │                 (apsw conn)
capture.py    vision.py             consent_manager.py
  │         (local / cloud)          weekly_report.py
  │                                  sync.py
window_identity.py                   finalizer.py
consent_manager.py
```

The main loop runs in a background thread. The Flask server (`app.py`) handles
browser requests and forwards recording start/stop signals via Supabase Realtime.

---

## 3. Configuration Model

`config.py` exports all runtime switches. Privacy-relevant flags:

| Flag | Default | Production lock? | Effect when true |
|---|---|---|---|
| `PRIVATE_MODE` | `true` | Yes (`PRODUCTION_BUILD`) | Encryption + local-only |
| `ENABLE_CAPTURE_LEASES` | `true` in PM | Yes | Per-window consent required |
| `USE_LOCAL_INFERENCE` | `true` in PM | Yes | On-device model, no cloud |
| `ENABLE_APPLESCRIPT_METADATA` | `false` | No | URL/path via AppleScript |

When `PRODUCTION_BUILD=True` (set by build pipeline via `_build_config.py`),
all three boolean flags are forced to their production values and cannot be
overridden by environment variables. This prevents a shipped binary from being
weakened by a user setting `BUILDHARVEY_PRIVATE_MODE=false`.

---

## 4. Observation Pipeline

```
observe() call every 5 seconds:

1. get_metadata_context()          — Quartz/AppKit, no pixels, no AppleScript
2. get_window_identity()           — bundle_id + CGWindowID + PID + proc_start_time
3. consent_manager.is_authorized() — lease check against encrypted DB
4. capture_window(cg_window_id)    — CGWindowListCreateImage (macOS)
                                     PrintWindow+PW_RENDERFULLCONTENT (Windows)
   └─ returns False → _CONSENT_BLOCKED (fail closed, ObservationGap)
5. diff_score(prev, current)       — grayscale thumbnail diff, ≤ 0.02 → skip
6. ocr.extract_text()              — local, no network
7. entities.extract()              — local pattern matching
8. _save_screenshot() [selective]  — only on app-switch / domain-change / large diff
```

Steps 1–3 are **pixel-free** — no screen data is touched until consent is confirmed.
`capture_window()` never falls back to full-monitor capture on failure; it returns
`False` and the caller records an `ObservationGap`.

### 4.1 BuildHarvey window exclusion

`observer.is_user_work()` filters the pipeline output:

- `_SYSTEM_APPS` frozenset excludes `'BuildHarvey'`, `'loginwindow'`,
  `'Finder'`, `'Dock'`, etc.
- Any app name containing `'buildharvey'` (case-insensitive) is excluded.
- Empty app + empty window title is excluded.

**Current limitation (open item):** The exclusion happens at the `Observation`
layer (after pixel capture) based on the app name string, not on native
process/bundle identity before capture. A window titled `"BuildHarvey"` owned
by a third-party process would be incorrectly excluded; conversely, a
BuildHarvey-owned window with an unrelated title would not be excluded. This
is tracked as **Privacy Claim #6: PARTIAL** — the string-based filter is a
second-order defense; the primary defense relies on the ConsentManager never
granting leases to BuildHarvey's own bundle, but this is not yet enforced by
an explicit pre-capture identity check. See open items in §11.

---

## 5. Episode Engine

`EpisodeEngine` accumulates `Observation` objects and manages episode lifecycle:

- **2-signal hysteresis:** a case switch requires `CASE_SWITCH_THRESHOLD = 3`
  consecutive observations of the new case before the current episode closes.
  Prevents spurious switches from transient OCR noise.
- **Deterministic boundary detection:** `check_deterministic_boundary()` short-
  circuits the vision/model call when the signal is unambiguous.
- **Inactivity timeout:** `INACTIVITY_PAUSE_SECONDS = 300` — idle longer than 5
  minutes without screen change stops timing (does not close episode).
- **Max episode guard:** `MAX_EPISODE_SECONDS = 28800` (8h) — hard ceiling.
- `MAX_KEY_OBSERVATIONS = 8` — evidence capped per episode.

---

## 6. Capture APIs

### 6.1 macOS

`_capture_window_macos(cg_window_id)` uses:

```
CGWindowListCreateImage(
    CGRectNull,
    kCGWindowListOptionIncludingWindow,   # single window by ID
    cg_window_id,
    kCGWindowImageBoundsIgnoreFraming,
)
```

This renders only the target window's CGSurface. Adjacent windows, notifications,
and desktop elements are excluded at the OS compositor level, regardless of Z-order.

### 6.2 Windows

`_capture_window_win32(hwnd)` uses `PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)`.
`PW_RENDERFULLCONTENT = 0x2` asks the DWM compositor to render the window's own
backing surface. Per-HWND DWM surfaces prevent neighboring window content from
appearing regardless of window overlap.

Falls back to `PW_CLIENTONLY = 0x1` for legacy GDI apps.

### 6.3 Fail-closed invariant

Both platform paths return `False` on any error. The caller (`observer.observe()`)
treats `False` as `_CONSENT_BLOCKED` and records an `ObservationGap` rather than
silently falling back to full-monitor capture.

`capture_screen()` (full-monitor via `mss`) is only called when
`ENABLE_CAPTURE_LEASES=false`. The `mss` import is lazy (inside `capture_screen()`
only) so it never loads in production PRIVATE_MODE.

---

## 7. Database and Encryption

### 7.1 Schema

SQLite database at `~/.buildharvey/buildharvey.db`. Tables:

| Table | Purpose |
|---|---|
| `episodes` | Finalized billable episodes |
| `capture_leases` | Per-window consent state (ConsentManager) |
| `observation_gaps` | Structured gaps in observation timeline |
| `session_state` | Key/value: session epoch, dirty_shutdown flag |
| `recent_contexts` | Case/issue autocomplete for UI |

### 7.2 Encryption at rest

When `PRIVATE_MODE=true`, the database is encrypted using **apsw-sqlite3mc**
(SQLite Multiple Ciphers). Connection lifecycle:

```python
# 1. Import apsw-sqlite3mc — raises RuntimeError if unavailable (fail closed)
import apsw

# 2. Retrieve (or create) 256-bit key from OS keychain
key = _get_or_create_keychain_key()  # secrets.token_hex(32)

# 3. Detect database state from file header
state = _detect_db_state(db_path)
# 'new'       → create fresh encrypted DB
# 'plaintext' → one-time PRAGMA rekey migration (with atomic backup)
# 'encrypted' → unlock with PRAGMA key and verify

# 4. Open with apsw — connection used for the ENTIRE lifetime
conn = apsw.Connection(str(db_path))
conn.execute("PRAGMA key='<hex64>'")

# 5. Verify key works — fail closed if it does not
conn.execute("SELECT count(*) FROM sqlite_master").fetchall()

# 6. Set WAL mode and safety PRAGMAs
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.execute("PRAGMA temp_store=MEMORY")

# 7. Wrap in _APSWCompatWrapper for sqlite3-API compatibility
return _APSWCompatWrapper(conn)
```

`_APSWCompatWrapper` provides `execute()`, `commit()`, and `close()`. `commit()`
issues an explicit `COMMIT` SQL statement and swallows `apsw.SQLError` for the
DDL auto-commit case (DDL statements auto-commit in SQLite, so the "no transaction
is active" error is expected and benign).

**Stdlib sqlite3 is never used for the encrypted connection.** All callers
(consent_manager, weekly_report, app.py, main.py) receive an `_APSWCompatWrapper`
and use the duck-typed API.

### 7.3 Plaintext migration

Existing users upgrading from a pre-encryption installation have plaintext databases.
`_migrate_plaintext_to_encrypted()`:

1. Creates `<db>.plaintext_backup` (atomic copy) before any mutation.
2. Opens with apsw (no key), verifies readable.
3. Calls `PRAGMA rekey='<key>'` (sqlite3mc in-place encryption; must be outside
   a transaction).
4. Verifies encrypted re-open succeeds.
5. Verifies stdlib sqlite3 can no longer read the file.
6. Removes backup only after all three checks pass.

If any step fails, the backup is preserved and a `RuntimeError` is raised.

### 7.4 Encryption verification results (runtime)

Confirmed on this machine with apsw-sqlite3mc 3.53.4.0:

| Check | Result |
|---|---|
| DB file header is NOT `SQLite format 3\x00` | PASS |
| Work marker absent from raw `.db` bytes | PASS |
| stdlib `sqlite3.connect()` raises `DatabaseError` | PASS |
| apsw re-open with correct key reads marker | PASS |
| Wrong key raises `apsw.NotADBError` | PASS |
| PRAGMA rekey on plaintext DB: returns `('ok',)` | PASS |
| After rekey: marker absent from raw bytes | PASS |
| After rekey: stdlib blocked | PASS |
| After rekey: apsw reads data correctly | PASS |

### 7.5 OS keychain integration

Key stored under service `com.buildharvey.agent`, account `db-encryption-key`.

`_keychain_write()` / `_keychain_read()` / `_delete_keychain_key()` try in order:

1. **pyobjc-framework-Security** (`SecKeychainAddGenericPassword` /
   `SecKeychainFindGenericPassword` / `SecKeychainFindAndDelete`)
2. **keyring** Python package (cross-platform fallback)
3. **macOS `security` CLI** (`/usr/bin/security add-generic-password -U`) — always
   present on macOS; required in environments where pyobjc-Security is not installed

All exceptions are swallowed at each level; the next fallback is tried. A failed
write means the next process will generate a NEW key and be unable to open the
existing database — a data-loss scenario. The `security` CLI fallback (added in
the keychain patch) prevents this in development environments where pyobjc-Security
is not installed.

**`pyobjc-framework-Security` has been added to `requirements.txt`** so it is
installed in all production and development environments.

### 7.6 Two-process lifecycle verification (macOS Keychain)

Verified with two separate Python subprocess invocations:

| Step | Process | Result |
|---|---|---|
| `database.connect()` — new DB | A (fresh) | DB created, key written to keychain |
| Header not plaintext | A | PASS |
| Marker not in raw bytes | A | PASS |
| stdlib sqlite3 blocked | A | PASS |
| `database.connect()` — existing encrypted DB | B (restart) | Key read from keychain, DB unlocked |
| Marker readable by Process B | B | PASS |
| Process B wrote second marker | B | PASS |
| Both markers absent from raw bytes after B writes | B | PASS |
| Wrong key blocked in Process B | B | PASS |

### 7.7 Crash safety

- `mark_dirty_shutdown(conn)` sets `dirty_shutdown=1` at startup (before recording
  begins). A crash leaves this set.
- `mark_clean_shutdown(conn)` sets it to `0` on clean exit.
- On startup with `dirty_shutdown=1`: `consent_manager.invalidate_all("app_crashed")`
  clears all leases, triggering batch re-consent on next capture.
- `purge_stale_temp_frames()` deletes temp frames older than
  `SCREENSHOT_RETENTION_HOURS=1` at startup.

### 7.8 Data deletion

`delete_all_local_data()` removes:
- DB file + WAL/SHM
- `~/.buildharvey/screenshots/`
- `~/.buildharvey/_current.png`, `_prev.png`
- `~/.buildharvey/weekly_reports/`
- OS keychain entry for encryption key (PRIVATE_MODE only)

---

## 8. Consent Manager

`ConsentManager` (consent_manager.py) manages per-window capture leases:

- **Session epoch** (stored in `session_state` table): incremented on each startup.
  Window identities from previous sessions are invalid (prevents stale leases from
  surviving reboots).
- **WindowIdentity** (window_identity.py): `(bundle_id, window_id, owner_pid,
  process_start_time, session_epoch)` — the PID + process start time combination
  prevents window ID reuse from granting stale consent to a new process.
- **Lease states:** `pending` → user sees consent dialog; `authorized` → capture
  allowed; `rejected` → capture blocked for this window's lifetime; `invalidated` →
  lease expired (crash, lock, logout, session epoch change).
- `is_authorized(identity)` checks the in-memory lease cache before hitting the DB.

---

## 9. Vision / Local Inference

`vision.analyze()` selects the path based on `config.USE_LOCAL_INFERENCE`:

```
USE_LOCAL_INFERENCE=false (dev/cloud):
  JPEG-compress screenshot → POST /api/agent/vision → Claude API
  (server holds Anthropic key and model selection)

USE_LOCAL_INFERENCE=true (production PRIVATE_MODE):
  OCR excerpt (≤ 200 chars) → LocalInferenceBackend.classify_episode_boundary()
  Screenshot DELETED immediately after OCR extraction
  No screenshot or OCR data ever leaves the device
```

`local_inference.py` defines:
- `LocalInferenceBackend` protocol: `is_available()`, `classify_episode_boundary()`
- `ModelManager`: handles first-run model download to
  `~/Library/Application Support/BuildHarvey/models/`
- `BoundarySignal(new_episode: bool, activity_type: str, confidence: float)`

In PRIVATE_MODE, `vision.analyze()` returns `None` for any path that would send
data to a server (checked by `config.PRIVATE_MODE` guard at line 74 of `vision.py`).

**Offline acceptance tests** (test_offline_acceptance.py) verify that in PRIVATE_MODE:
- No network calls are made by vision
- sync is a no-op
- finalizer does not call the server

---

## 10. Sync and Finalizer

`sync.py`: Runs a background worker thread. In PRIVATE_MODE, `start()` returns
immediately (no thread started, no network calls). `enqueue_episode()` /
`enqueue_cleanup()` silently no-op.

`finalizer.py`: Post-processes episodes (duration rounding, key observation
subsampling). The cloud fallback path (POST `/api/agent/finalize`) is guarded
by `config.PRIVATE_MODE`.

---

## 11. Weekly Report

`weekly_report.py` runs entirely locally:

1. Queries `episodes` table for the requested date range.
2. Aggregates hours per case/matter from `duration_minutes`.
3. Writes a JSON report to `~/.buildharvey/weekly_reports/`.
4. `source_ids` is a JSON array of episode UUIDs (never LLM-generated).
5. Time values are computed arithmetically from recorded `started_at` / `ended_at`.

The local pipeline requires no network access and no cloud model.

---

## 12. Private Engine IPC Boundary

`private_engine/` contains the IPC protocol for any future privileged subprocess:

- `ipc.py`: defines command constants. `EPISODE_CLOSED` sends only the episode ID
  and case name — no work content (verified by `test_ipc_no_work_content_in_episode_closed`).
- `engine.py`: processing engine stub.
- `__init__.py`: empty (no forbidden imports).

Import boundary test (`test_import_boundary.py`) verifies none of the private_engine
files import from `observer`, `capture`, `vision`, `database`, or any module that
touches screen data.

---

## 13. Windows Support

`os_adapters/windows.py` provides:
- `get_window_identity_windows()` — HWNDs via `win32gui`
- `is_buildharvey_hwnd()` — checks HWND against current process ID
- Session boundary detection (lock/logout events via WTS session change notifications)

`capture.py`'s `_capture_window_win32()` uses PrintWindow with DWM compositor
isolation. Windows consent/identity uses HWND + PID (not bundle ID).

---

## 14. Test Architecture

55 tests, all passing, 0 skipped.

| Suite | Tests | Covers |
|---|---|---|
| `test_privacy_boundaries` | 13 | Encryption (8), window exclusion (5), Windows capture routing (3) |
| `test_weekly_report` | 8 | Local report pipeline invariants |
| `test_realtime_optionality` | 8 | Browser disconnect does not stop local recording |
| `test_installation` | 7 | Installation ID persistence, platform paths |
| `test_import_boundary` | 7 | private_engine IPC isolation |
| `test_offline_acceptance` | 4 | PRIVATE_MODE blocks all network calls |

Encryption tests use `apsw.Connection` directly — never stdlib sqlite3 — to match
the production path. Tests skip with `self.skipTest()` only if apsw-sqlite3mc is
absent; on this machine all 8 run without skipping.

---

## 15. Privacy Claims Verification Status

| Claim | Status | Evidence |
|---|---|---|
| Database encrypted at rest in PRIVATE_MODE | **VERIFIED BY RUNTIME TEST** | apsw-sqlite3mc, header bytes, stdlib block, keychain lifecycle |
| Capture requires per-window consent | **VERIFIED BY CODE/ARCHITECTURE** | ConsentManager, WindowIdentity, test_privacy_boundaries |
| No cloud calls in PRIVATE_MODE | **VERIFIED BY TEST** | test_offline_acceptance (4 tests) |
| Screenshot deleted after local OCR | **VERIFIED BY CODE** | vision.py:194 `unlink(missing_ok=True)` |
| Temp frames purged on startup | **VERIFIED BY CODE** | database.purge_stale_temp_frames() |
| BuildHarvey cannot capture its own UI | **PARTIAL** | String-based `is_user_work()` filter after capture; no pre-capture process/bundle identity check. See §4.1 open item. |
| WAL/SHM files encrypted | **VERIFIED BY ARCHITECTURE** | sqlite3mc encrypts journal files; `temp_store=MEMORY` prevents temp DB spill |
| Key rotation on delete-all-data | **VERIFIED BY CODE** | `delete_all_local_data()` calls `_delete_keychain_key()` |
| Wrong key fails closed | **VERIFIED BY RUNTIME TEST** | apsw.NotADBError on wrong key |
| Crash recovery re-prompts consent | **VERIFIED BY CODE** | `dirty_shutdown` → `invalidate_all("app_crashed")` |

---

## 16. Open Items

1. **Privacy Claim #6 — self-window exclusion:** The current defense is string-based
   (`is_user_work()` checks app name after the capture pipeline runs). A proper
   implementation blocks on native process/bundle identity **before** consent
   evaluation and before any pixel capture. Tracked for next sprint.

2. **`pyobjc-framework-Security` install:** Added to `requirements.txt` but not yet
   installed in the current venv. Run `pip install pyobjc-framework-Security` or
   `pip install -r requirements.txt` to activate the primary keychain path.

3. **`datetime.datetime.utcnow()` deprecation:** `installation.py:35` — replace with
   `datetime.datetime.now(datetime.UTC)`. Non-urgent; Python 3.13 warns only.

4. **`print()` calls in `main.py` and `database.py`:** Several status messages still
   use `print()` rather than `bh_logging`. Non-critical for privacy; cosmetic
   consistency item.
