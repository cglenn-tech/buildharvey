"""
BuildHarvey Private Engine — Phase 7: Network Isolation.

This package implements the private work engine that handles all capture,
inference, and storage. It is architecturally isolated from all networking.

IMPORT BOUNDARY INVARIANT:
  No module in this package may import from the following (directly or transitively):
    urllib, requests, websockets, realtime, supabase, auth, sync, httpx, aiohttp

This invariant is enforced by:
  1. CI static analysis test (tests/test_import_boundary.py)
  2. Code review requirement
  3. macOS: XPC Service entitlement (no com.apple.security.network.client)
  4. Windows: architectural convention enforced by code review and tests

On macOS, the full Private Engine runs as BuildHarveyPrivateEngine.xpc with no
network entitlement. The app shell (BuildHarvey.app) communicates with it via
NSXPCConnection carrying only the IPC interface defined in ipc.py.

On Windows, the Private Engine runs as a child process communicating with the
app shell via a Windows named pipe (see ipc.PIPE_NAME_WINDOWS). The import
boundary is enforced by static analysis (tests/test_import_boundary.py).
"""
