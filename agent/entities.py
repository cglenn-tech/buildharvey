"""
Entity extraction — deterministic only. No LLM.

Uses:
  - Regex for structured professional identifiers (claim numbers, invoice IDs, etc.)
  - spaCy NER for PERSON, ORG, PRODUCT, LAW
  - File path stem as document signal
  - Window title as supplementary signal

Entity detection is the primary signal for episode grouping.
"""
import re
from pathlib import Path
from typing import Optional

# spaCy entity types that represent meaningful work subjects
_ENTITY_TYPES = {"PERSON", "ORG", "PRODUCT", "LAW", "WORK_OF_ART", "EVENT"}

# Structured professional identifiers — highest precision
_PATTERNS = [
    r'\bClaim(?:\s+No\.?)?\s+[\w-]{4,}\b',     # Claim 22-18391
    r'\bCLM-\d+\b',                              # CLM-12345
    r'\bINV-\d+\b',                              # INV-1488
    r'\bInvoice\s+#?\s*\d+\b',                  # Invoice #1488
    r'\bCase\s+(?:No\.?\s*)?#?\s*[\w-]{4,}\b',  # Case No. 2024-CV-1234
    r'\bMatter\s+#?\s*[\w-]+\b',                # Matter #12345
    r'\bFile\s+#?\s*[\w-]+\b',                   # File #12345
    r'\bRef(?:erence)?\s*#?\s*[\w-]+\b',         # Reference #12345
    r'\bTicket\s+#?\s*[\w-]+\b',                 # Ticket #12345
    r'\bPolicy\s+#?\s*[\w-]+\b',                 # Policy #ABC-123
    r'\bOrder\s+#?\s*[\w-]+\b',                  # Order #12345
    r'\b[A-Z]{2,6}-\d{3,}\b',                   # JIRA-style ABC-1234
    r'\bv\.\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*',  # Rivera v. Hartfield
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import sys, os, spacy
            if getattr(sys, 'frozen', False):
                # PyInstaller bundle: load from vendored path
                model_path = os.path.join(sys._MEIPASS, 'vendor', 'en_core_web_sm')
                _nlp = spacy.load(model_path)
            else:
                _nlp = spacy.load("en_core_web_sm")
            print("[entities] spaCy model loaded")
        except OSError:
            print("[entities] WARNING: spaCy model missing. Run: python -m spacy download en_core_web_sm")
            _nlp = False
        except ImportError:
            print("[entities] WARNING: spaCy not installed")
            _nlp = False
    return _nlp if _nlp else None


def extract(ocr_text: str, window_title: str = "", file_path: str = "") -> list[str]:
    """
    Extract entities from OCR text and context signals.
    Returns a deduplicated list ordered by specificity:
      1. Structured identifiers (Claim #, Case #, Matter # …) — most reliable
      2. File stem — strong document signal
      3. spaCy NER (ORG, PERSON, PRODUCT …) — least precise
    """
    structured: list[str] = []
    seen: set[str] = set()

    def _add(val: str, bucket: list) -> None:
        v = " ".join(val.split())  # collapse all whitespace including newlines
        if len(v) > 2 and v not in seen:
            seen.add(v)
            bucket.append(v)

    # 1. Structured identifiers — highest precision
    for pattern in _COMPILED:
        for match in pattern.finditer(ocr_text):
            _add(match.group(), structured)

    # 2. File stem — reliable document context
    file_entities: list[str] = []
    if file_path:
        stem = Path(file_path).stem.strip()
        if len(stem) > 3 and not _is_noise(stem):
            _add(stem, file_entities)

    # 3. spaCy NER — least precise, lowest priority
    ner_entities: list[str] = []
    nlp = _get_nlp()
    if nlp and ocr_text.strip():
        doc = nlp(ocr_text[:5000])
        for ent in doc.ents:
            if ent.label_ not in _ENTITY_TYPES:
                continue
            val = " ".join(ent.text.split())
            # PERSON must be at least two words to be a useful case identifier
            if ent.label_ == "PERSON" and len(val.split()) < 2:
                continue
            if not _is_noise(val):
                _add(val, ner_entities)

    return structured + file_entities + ner_entities


def dominant(entity_counts: dict[str, int]) -> Optional[str]:
    """Return the most-seen entity, or None if no entities tracked."""
    if not entity_counts:
        return None
    return max(entity_counts, key=lambda k: entity_counts[k])


# ── Noise filter ──────────────────────────────────────────────────────────────

_NOISE_WORDS = {
    "click", "right", "left", "file", "edit", "view", "help", "home", "menu",
    "tool", "window", "search", "open", "save", "copy", "paste", "undo", "redo",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july", "august",
    "september", "october", "november", "december", "today", "tomorrow",
    "google", "microsoft", "apple", "adobe",  # generic app vendors, not clients
}


def _is_noise(text: str) -> bool:
    if len(text) < 3:
        return True
    if text.lower() in _NOISE_WORDS:
        return True
    # All-caps single words are typically UI chrome (buttons, labels, headings)
    if text.isupper() and " " not in text:
        return True
    # Possessives like "Chas Glenn's" are system strings, not case names
    if text.endswith("'s") or text.endswith("\u2019s"):
        return True
    return False
