"""
Work description generator.

Converts raw context signals into meaningful, human-readable work descriptions
suitable for an LLM to reconstruct a weekly work report.

No LLM. Fully deterministic.

Examples:
  "Reviewed Appraisal Report"
  "Drafted response letter"
  "Updated Johnson Holdings Q4 spreadsheet"
  "Researched — Supabase documentation"
"""
from pathlib import Path
from typing import Optional

_EDITING_APPS = {
    "Microsoft Word", "Pages", "TextEdit", "Notion",
    "Google Docs", "LibreOffice Writer",
}
_SPREADSHEET_APPS = {
    "Microsoft Excel", "Numbers", "Google Sheets", "LibreOffice Calc",
}
_PDF_APPS = {
    "Preview", "Adobe Acrobat", "Adobe Reader", "Acrobat", "PDF Expert", "Skim",
}
_EMAIL_APPS = {
    "Mail", "Microsoft Outlook", "Mimestream", "Superhuman", "Airmail", "Spark",
}
_BROWSER_APPS = {
    "Safari", "Google Chrome", "Firefox", "Arc",
    "Brave Browser", "Microsoft Edge", "Opera",
}
_PRESENTATION_APPS = {
    "Microsoft PowerPoint", "Keynote", "Google Slides",
}
_TERMINAL_APPS = {
    "Terminal", "iTerm2", "iTerm", "Hyper", "Warp", "Alacritty",
}

_NOISE_DOMAINS = {
    "google.com", "accounts.google.com", "calendar.google.com",
    "login.microsoftonline.com", "microsoftonline.com",
    "apple.com", "icloud.com",
}

_STRIP_SUFFIXES = [
    " - Microsoft Excel", " - Microsoft Word", " - Microsoft PowerPoint",
    " — Safari", " - Google Chrome", " — Chrome", " - Firefox",
    " - Preview", " - TextEdit", " - Pages", " - Numbers", " - Keynote",
    " - Notion", " - Arc",
]
_STRIP_EXTENSIONS = [
    ".xlsx", ".xls", ".docx", ".doc", ".pdf", ".pptx",
    ".pages", ".numbers", ".txt", ".md",
]


def describe(app: str, window_title: str, browser_url: str, file_path: str) -> Optional[str]:
    """
    Generate a meaningful work description from context signals.
    Returns None if the context isn't informative enough to describe.
    """
    if app in _TERMINAL_APPS:
        return None  # terminal output is too noisy to produce useful work descriptions

    if app in _EMAIL_APPS:
        return _email(window_title)

    if app in _EDITING_APPS:
        return _with_doc("Drafted", window_title, file_path, "document")

    if app in _SPREADSHEET_APPS:
        return _with_doc("Updated", window_title, file_path, "spreadsheet")

    if app in _PDF_APPS:
        return _with_doc("Reviewed", window_title, file_path, "document")

    if app in _PRESENTATION_APPS:
        return _with_doc("Prepared", window_title, file_path, "presentation")

    if app in _BROWSER_APPS:
        return _browser(window_title, browser_url, app)

    # Generic: app + cleaned window title
    title = _clean_title(window_title, app)
    if title and len(title) > 2:
        return f"{app} — {title}"

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _email(window_title: str) -> str:
    if _is_compose(window_title):
        return "Drafted email"
    subject = _email_subject(window_title)
    return f"Reviewed email — {subject}" if subject else "Reviewed email"


def _is_compose(title: str) -> bool:
    signals = {"new message", "compose", "forward:", "fwd:", "draft"}
    return any(s in title.lower() for s in signals)


def _email_subject(title: str) -> Optional[str]:
    for suffix in [" - Mail", " — Mail", " - Outlook", " — Outlook",
                   " - Mimestream", " - Superhuman", " - Spark"]:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
    for prefix in ["Re: ", "RE: "]:
        if title.startswith(prefix):
            title = title[len(prefix):]
    return title[:60] if len(title) > 2 else None


def _with_doc(verb: str, window_title: str, file_path: str, fallback: str) -> str:
    name = _docname(file_path) or _clean_title(window_title, "")
    return f"{verb} {name}" if name else f"{verb} {fallback}"


def _browser(window_title: str, browser_url: str, app: str) -> Optional[str]:
    if not browser_url:
        return None
    try:
        from urllib.parse import urlparse
        domain = urlparse(browser_url).netloc.removeprefix("www.")
    except Exception:
        return None
    if not domain or domain in _NOISE_DOMAINS:
        return None
    title = _clean_title(window_title, app)
    if title and len(title) > 3:
        return f"Researched — {title[:70]}"
    return f"Researched via {domain}"


def _docname(file_path: str) -> Optional[str]:
    if not file_path:
        return None
    stem = Path(file_path).stem.strip()
    return stem[:60] if len(stem) > 2 else None


def _clean_title(title: str, app: str) -> str:
    for suffix in _STRIP_SUFFIXES + ([f" - {app}", f" — {app}"] if app else []):
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
            break
    for ext in _STRIP_EXTENSIONS:
        if title.lower().endswith(ext):
            title = title[:-len(ext)].strip()
            break
    return title.strip()
