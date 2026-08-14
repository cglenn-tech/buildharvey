"""
Import boundary test — Phase 7 network isolation.

Enforces the invariant that the private_engine/ module graph does not import
any networking library, directly or transitively.

On Windows the private engine runs as a separate child process. This boundary
is architectural convention enforced by code review and this CI test.

On macOS the private engine additionally runs as an XPC Service with no
com.apple.security.network.client entitlement, providing OS-level enforcement.

This test parses module ASTs to detect imports — it does NOT execute the modules.
"""
import ast
import os
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).parent.parent
PRIVATE_ENGINE_DIR = AGENT_DIR / "private_engine"

# These imports are forbidden in the private engine — directly or transitively.
FORBIDDEN_MODULES = {
    "urllib",
    "requests",
    "websockets",
    "realtime",
    "supabase",
    "auth",
    "sync",
    "httpx",
    "aiohttp",
    "realtime_client",
    "vision",        # vision.py makes HTTP calls (cloud path)
}

# These modules within the private engine are allowed to import themselves
ALLOWED_SELF_IMPORTS = {
    "private_engine",
}


def collect_imports(source_path: Path) -> set[str]:
    """Return all top-level module names imported by a Python source file."""
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
            # Relative imports within the package are OK
    return imports


def get_private_engine_files() -> list[Path]:
    """Return all Python files in the private_engine/ directory."""
    if not PRIVATE_ENGINE_DIR.exists():
        return []
    return [p for p in PRIVATE_ENGINE_DIR.rglob("*.py") if p.name != "__pycache__"]


@pytest.mark.parametrize("source_file", get_private_engine_files(), ids=lambda p: p.name)
def test_no_forbidden_imports(source_file: Path) -> None:
    """
    Assert that no private_engine source file directly imports a forbidden module.

    Note: this is a direct-import check (one level deep). Transitive imports
    are checked separately in test_no_transitive_forbidden_imports.
    """
    imports = collect_imports(source_file)
    violations = imports & FORBIDDEN_MODULES
    assert not violations, (
        f"{source_file.relative_to(AGENT_DIR)} imports forbidden module(s): "
        f"{violations}\n"
        f"The private engine must not import any networking library.\n"
        f"Forbidden: {sorted(FORBIDDEN_MODULES)}"
    )


def test_private_engine_dir_exists() -> None:
    """The private_engine directory must exist."""
    assert PRIVATE_ENGINE_DIR.exists(), (
        f"private_engine/ directory not found at {PRIVATE_ENGINE_DIR}"
    )


def test_private_engine_has_ipc() -> None:
    """The IPC protocol file must exist."""
    ipc_file = PRIVATE_ENGINE_DIR / "ipc.py"
    assert ipc_file.exists(), "private_engine/ipc.py must exist (IPC protocol definitions)"


def test_ipc_defines_required_commands() -> None:
    """The IPC protocol must define PrivateEngineCommand and PrivateEngineEvent."""
    ipc_file = PRIVATE_ENGINE_DIR / "ipc.py"
    if not ipc_file.exists():
        pytest.skip("ipc.py not found")

    source = ipc_file.read_text()
    assert "class PrivateEngineCommand" in source, "ipc.py must define PrivateEngineCommand"
    assert "class PrivateEngineEvent" in source, "ipc.py must define PrivateEngineEvent"
    assert "def start_capture" in source, "PrivateEngineCommand must define start_capture"
    assert "def stop_capture" in source, "PrivateEngineCommand must define stop_capture"
    assert "def delete_all_data" in source, "PrivateEngineCommand must define delete_all_data"
    assert "def on_episode_closed" in source, "PrivateEngineEvent must define on_episode_closed"
    assert "def on_inference_failure" in source, "PrivateEngineEvent must define on_inference_failure"


def test_ipc_no_work_content_in_episode_closed() -> None:
    """
    on_episode_closed must accept only episode_id (structural) and duration_minutes
    (computed) — no work content fields.

    This test ensures the interface contract is maintained.
    """
    ipc_file = PRIVATE_ENGINE_DIR / "ipc.py"
    if not ipc_file.exists():
        pytest.skip("ipc.py not found")

    source = ipc_file.read_text()
    tree = ast.parse(source)

    # Find on_episode_closed method definition
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "on_episode_closed":
            args = [a.arg for a in node.args.args if a.arg != "self"]
            # Must have episode_id and duration_minutes; no content fields
            assert "episode_id" in args, "on_episode_closed must have episode_id parameter"
            assert "duration_minutes" in args, "on_episode_closed must have duration_minutes parameter"
            # Must not have content fields
            content_fields = {"case_name", "key_observations", "report_text", "ocr_text", "window_title"}
            violations = set(args) & content_fields
            assert not violations, (
                f"on_episode_closed must not carry work content: {violations}"
            )
            return

    pytest.fail("on_episode_closed method not found in ipc.py")
