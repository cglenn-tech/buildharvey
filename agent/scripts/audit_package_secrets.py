#!/usr/bin/env python3
"""
agent/scripts/audit_package_secrets.py

Scans the packaged agent source tree for hardcoded credentials.

Usage:
  python audit_package_secrets.py [scan-root]

  scan-root defaults to the current directory.

Exit codes:
  0  clean — no credentials found
  1  findings — one or more potential secrets detected
  2  error — audit could not run (bad arguments, unreadable scan root, etc.)
"""
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Patterns that indicate a hardcoded credential value (not just a name).
# These match on the literal value, not on env-var references.
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Anthropic API key literal: sk-ant-api0N-...
    ("anthropic_key_literal", re.compile(r"sk-ant-api0[3-9]-[A-Za-z0-9_\-]{10,}")),
    # Assignment of a literal sk- value to ANTHROPIC_API_KEY
    ("anthropic_key_assignment", re.compile(r"ANTHROPIC_API_KEY\s*=\s*[\"']sk-")),
    # Supabase service-role JWT (HS256 JWT header — only appears in actual tokens)
    ("supabase_service_role_jwt", re.compile(r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.")),
]

# ---------------------------------------------------------------------------
# Allowlist: lines that merely reference an env-var name are harmless.
# e.g.  os.environ.get("ANTHROPIC_API_KEY")
#        os.getenv("ANTHROPIC_API_KEY")
# ---------------------------------------------------------------------------
_HARMLESS_REFERENCE = re.compile(
    r'os\.environ(?:\.get)?\s*\(\s*["\']ANTHROPIC_API_KEY["\']'
    r"|os\.getenv\s*\(\s*[\"']ANTHROPIC_API_KEY[\"']"
)


def check_anthropic_absent() -> list[str]:
    """Return a finding if anthropic is importable in the current Python environment."""
    try:
        import anthropic  # noqa: F401
        return ["anthropic package is importable in the active Python environment — must be removed from venv"]
    except ImportError:
        return []


def scan_directory(root: Path) -> list[str]:
    """Return a list of finding strings; empty list means clean."""
    findings: list[str] = []

    py_files = sorted(root.rglob("*.py"))
    for py_file in py_files:
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(f"[read error] {py_file}: {exc}")
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            # Skip lines that only reference the env-var name (not a literal value)
            if _HARMLESS_REFERENCE.search(line):
                continue
            for label, pattern in _PATTERNS:
                if pattern.search(line):
                    try:
                        rel = py_file.relative_to(root)
                    except ValueError:
                        rel = py_file
                    findings.append(
                        f"{rel}:{lineno}: [{label}] matched /{pattern.pattern}/"
                    )

    return findings


def main() -> None:
    if len(sys.argv) > 2:
        print(f"Usage: {sys.argv[0]} [scan-root]", file=sys.stderr)
        sys.exit(2)

    scan_root_arg = sys.argv[1] if len(sys.argv) == 2 else "."
    scan_root = Path(scan_root_arg)

    if not scan_root.exists():
        print(
            f"[audit] ERROR: scan root does not exist: {scan_root.resolve()}",
            file=sys.stderr,
        )
        sys.exit(2)

    if not scan_root.is_dir():
        print(
            f"[audit] ERROR: scan root is not a directory: {scan_root.resolve()}",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        findings = check_anthropic_absent() + scan_directory(scan_root)
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] ERROR: unexpected failure during scan: {exc}", file=sys.stderr)
        sys.exit(2)

    if findings:
        print("[audit] SECRET AUDIT FAILURES:")
        for f in findings:
            print(f"  - {f}")
        print(f"[audit] {len(findings)} finding(s) — build aborted")
        sys.exit(1)

    print("[audit] Secret audit: CLEAN")
    sys.exit(0)


if __name__ == "__main__":
    main()
