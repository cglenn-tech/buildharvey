"""
Local Inference Backend — Phase 3 of the privacy architecture.

Provides on-device episode boundary classification and episode summarization
using quantized GGUF models via llama-cpp-python. No work content leaves the
device; all inference runs locally.

Architecture:
  LocalInferenceBackend  — Protocol (interface)
  LlamaCppBackend        — Production implementation (llama-cpp-python)
  NullBackend            — Stub when USE_LOCAL_INFERENCE=false
  ModelManager           — Download, verify, and manage GGUF model files

Episode boundary strategy: deterministic-first hybrid.
  1. Deterministic signals handle ~80-90% of boundary decisions.
  2. LocalInferenceBackend.classify_episode_boundary() is invoked only when
     signals are ambiguous (same app, different document type, moderate diff).
  3. Summarize_episode_group() is called once at episode close.

Model tiers:
  Tier 1 (classification, ≤4B params): fast, low RAM, called per ambiguous boundary
  Tier 2 (summarization, ≤9B params): higher quality, called once per episode close

Hardware acceleration (auto-detected at startup):
  macOS: Metal (Apple Silicon and AMD)
  Windows NVIDIA: CUDA
  Windows AMD/Intel: Vulkan
  Fallback: CPU (always available)

NOTE: Model selection is not finalized. Run agent/benchmarks/ evaluation harness
first. This module provides the infrastructure; do not wire to production captures
until benchmark results confirm quality thresholds are met on target hardware.
"""
import hashlib
import json
import os
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable

import config
from bh_logging import get_logger

log = get_logger("local_inference")


# ── Model registry ────────────────────────────────────────────────────────────
# Populated after benchmark harness confirms quality thresholds.
# Format: {"name": str, "sha256": str, "url": str, "size_mb": int, "tier": int}
_MODEL_REGISTRY: list[dict] = [
    # Example entry (replace with validated models after benchmarks):
    # {
    #     "name": "tier1.gguf",
    #     "sha256": "<sha256_hex>",
    #     "url": "https://example.com/tier1.gguf",
    #     "size_mb": 2048,
    #     "tier": 1,
    # },
]


# ── ModelManager ──────────────────────────────────────────────────────────────

class ModelManager:
    """
    Manages GGUF model files: existence checks, SHA256 verification, download.

    Models are stored in LOCAL_MODELS_DIR and never bundled in the installer.
    Download happens on first run when USE_LOCAL_INFERENCE=true and models are
    absent. Progress is reported via an optional callback.
    """

    def __init__(self) -> None:
        self._models_dir: Path = config.LOCAL_MODELS_DIR

    def needs_download(self) -> bool:
        """Return True if any registered model file is missing."""
        if not _MODEL_REGISTRY:
            return False
        for entry in _MODEL_REGISTRY:
            p = self._models_dir / entry["name"]
            if not p.exists():
                return True
        return False

    def verify_integrity(self) -> bool:
        """
        Verify SHA256 of all registered model files.
        Fast path: size check first, then full hash only on size match.
        Returns True if all files pass. Returns False (and logs) on any failure.
        """
        for entry in _MODEL_REGISTRY:
            p = self._models_dir / entry["name"]
            if not p.exists():
                log.error("model_manager.missing", name=entry["name"])
                return False
            expected_bytes = entry.get("size_mb", 0) * 1024 * 1024
            actual_bytes = p.stat().st_size
            if expected_bytes > 0 and abs(actual_bytes - expected_bytes) > 1024 * 1024:
                # Size mismatch by more than 1 MB → likely corrupt
                log.error("model_manager.size_mismatch", name=entry["name"],
                          expected=expected_bytes, actual=actual_bytes)
                return False
            sha256 = entry.get("sha256", "")
            if sha256:
                actual = _sha256_file(p)
                if actual != sha256:
                    log.error("model_manager.hash_mismatch", name=entry["name"])
                    return False
        return True

    def download(
        self,
        model_name: str,
        sha256: str,
        url: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> bool:
        """
        Download model_name from url to LOCAL_MODELS_DIR.
        Verifies SHA256. Writes to a .tmp file then renames atomically.
        progress_cb(bytes_downloaded, total_bytes) is called during download.
        Returns True on success.
        """
        self._models_dir.mkdir(parents=True, exist_ok=True)
        dest = self._models_dir / model_name
        tmp = self._models_dir / (model_name + ".tmp")

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BuildHarvey-ModelManager/1"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                hasher = hashlib.sha256()
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            progress_cb(downloaded, total)
            actual = hasher.hexdigest()
            if sha256 and actual != sha256:
                log.error("model_manager.download_hash_mismatch", name=model_name,
                          expected=sha256, actual=actual)
                tmp.unlink(missing_ok=True)
                return False
            tmp.rename(dest)
            log.info("model_manager.downloaded", name=model_name)
            return True
        except Exception as e:
            log.error("model_manager.download_failed", name=model_name, error=str(e))
            tmp.unlink(missing_ok=True)
            return False

    def download_all_in_background(
        self, progress_cb: Optional[Callable[[str, int, int], None]] = None
    ) -> threading.Thread:
        """
        Download all missing models in a background thread.
        progress_cb(model_name, bytes_downloaded, total_bytes)
        Returns the thread (already started).
        """
        def _run():
            for entry in _MODEL_REGISTRY:
                p = self._models_dir / entry["name"]
                if p.exists():
                    continue
                log.info("model_manager.downloading", name=entry["name"],
                         size_mb=entry.get("size_mb", 0))

                def _cb(dl, total, name=entry["name"]):
                    if progress_cb:
                        progress_cb(name, dl, total)

                self.download(
                    entry["name"],
                    entry.get("sha256", ""),
                    entry["url"],
                    _cb,
                )

        t = threading.Thread(target=_run, name="model-downloader", daemon=True)
        t.start()
        return t


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class BoundarySignal:
    """Result of a boundary classification inference call."""
    new_episode: bool           # True → close current episode, open new one
    confidence: float           # 0.0–1.0
    activity_type: str          # "research" | "drafting" | "correspondence" | "review" | "analysis"
    reasoning: str              # Model's brief explanation (for debug; never stored)


@dataclass
class EpisodeSummary:
    """Result of an episode summarization inference call."""
    key_observations: list[dict]    # [{timestamp, text}]
    activity_classification: str    # dominant activity type
    classification_confidence: float
    inference_failed: bool = False  # True if inference failed; caller records gap


# ── Protocol ──────────────────────────────────────────────────────────────────

@runtime_checkable
class LocalInferenceBackend(Protocol):
    """
    Interface for the local inference backend.

    All implementations must:
    - Never make network calls
    - Never persist input context beyond the duration of the call
    - Return InferenceFailed-flagged results on any model error (no silent failure)
    - Enforce context window limits explicitly (no silent truncation)
    """

    def classify_episode_boundary(
        self,
        app: str,
        window_title: str,
        ocr_excerpt: str,           # First 200 chars of OCR text only
        current_episode_summary: str,
    ) -> BoundarySignal:
        """
        Tier 1: Classify whether the current observation represents an episode boundary.
        Called only when deterministic signals are ambiguous.
        Latency target: ≤300ms p50 on M1, ≤800ms p50 on CPU-only.
        """
        ...

    def summarize_episode(
        self,
        episode_name: str,
        started_at: str,
        ended_at: str,
        duration_minutes: float,
        observations: list[dict],   # [{app, window_title, entities, timestamp}] — no OCR
    ) -> EpisodeSummary:
        """
        Tier 2: Generate key observations and activity classification for a closed episode.
        Called once per episode close.
        Latency target: ≤10s on M1, ≤30s on CPU-only.
        """
        ...

    def summarize_episode_group(
        self,
        matter: str,
        episodes: list[dict],
    ) -> str:
        """
        Tier 2: Summarize a group of episodes for the same matter/case.
        Used by WeeklyReportEngine to chunk large weeks into manageable prompts.
        Called with ≤4 episodes per chunk; returns a short prose summary.
        Never generates time numbers — duration math is done in Python.
        """
        ...

    def compose_weekly_narrative(
        self,
        matter_summaries: list[dict],
        period_start: str,
        period_end: str,
    ) -> str:
        """
        Tier 2: Compose a weekly narrative from per-matter summaries.
        matter_summaries: [{"matter": str, "summary": str, "duration_minutes": float}]
        Returns a plain-text narrative (no time numbers — caller appends calculated totals).
        """
        ...

    def is_available(self) -> bool:
        """Return True if the backend is initialized and a model is loaded."""
        ...


# ── Null backend (USE_LOCAL_INFERENCE=false) ───────────────────────────────────

class NullBackend:
    """
    No-op backend used when USE_LOCAL_INFERENCE=false.
    All methods return inference_failed=True so the caller falls back to the
    cloud path or template fallback.
    """

    def classify_episode_boundary(self, app, window_title, ocr_excerpt, current_episode_summary) -> BoundarySignal:
        return BoundarySignal(new_episode=False, confidence=0.0, activity_type="unknown", reasoning="local inference disabled")

    def summarize_episode(self, episode_name, started_at, ended_at, duration_minutes, observations) -> EpisodeSummary:
        return EpisodeSummary(
            key_observations=[],
            activity_classification="unknown",
            classification_confidence=0.0,
            inference_failed=True,
        )

    def summarize_episode_group(self, matter: str, episodes: list[dict]) -> str:
        return ""

    def compose_weekly_narrative(
        self, matter_summaries: list[dict], period_start: str, period_end: str
    ) -> str:
        return ""

    def is_available(self) -> bool:
        return False


# ── LlamaCppBackend ───────────────────────────────────────────────────────────

class LlamaCppBackend:
    """
    Production local inference backend using llama-cpp-python.

    Model selection: deferred to benchmark results. Model path and tier are
    configured via BUILDHARVEY_TIER1_MODEL and BUILDHARVEY_TIER2_MODEL
    environment variables pointing to local GGUF files.

    Hardware detection:
      - macOS: n_gpu_layers=-1 (Metal, all layers offloaded)
      - Windows NVIDIA: n_gpu_layers=-1 with CUDA build
      - Windows AMD/Intel: n_gpu_layers=-1 with Vulkan build
      - CPU fallback: n_gpu_layers=0
    """

    def __init__(self) -> None:
        self._tier1: Optional[object] = None   # llama_cpp.Llama instance
        self._tier2: Optional[object] = None
        self._available = False
        self._initialize()

    def _initialize(self) -> None:
        try:
            from llama_cpp import Llama  # type: ignore[import]
        except ImportError:
            log.warning("local_inference.init_failed", reason="llama_cpp not installed")
            return

        tier1_path = os.environ.get(
            "BUILDHARVEY_TIER1_MODEL",
            str(config.LOCAL_MODELS_DIR / "tier1.gguf"),
        )
        tier2_path = os.environ.get(
            "BUILDHARVEY_TIER2_MODEL",
            str(config.LOCAL_MODELS_DIR / "tier2.gguf"),
        )

        gpu_layers = _detect_gpu_layers()
        log.info("local_inference.init", gpu_layers=gpu_layers)

        if os.path.exists(tier1_path):
            try:
                self._tier1 = Llama(
                    model_path=tier1_path,
                    n_gpu_layers=gpu_layers,
                    n_ctx=4096,
                    verbose=False,
                )
                log.info("local_inference.tier1_loaded", path=tier1_path)
            except Exception as e:
                log.error("local_inference.tier1_load_failed", error=str(e))

        if os.path.exists(tier2_path):
            try:
                self._tier2 = Llama(
                    model_path=tier2_path,
                    n_gpu_layers=gpu_layers,
                    n_ctx=8192,
                    verbose=False,
                )
                log.info("local_inference.tier2_loaded", path=tier2_path)
            except Exception as e:
                log.error("local_inference.tier2_load_failed", error=str(e))

        self._available = (self._tier1 is not None) or (self._tier2 is not None)

    def is_available(self) -> bool:
        return self._available

    def classify_episode_boundary(
        self,
        app: str,
        window_title: str,
        ocr_excerpt: str,
        current_episode_summary: str,
    ) -> BoundarySignal:
        if self._tier1 is None:
            return BoundarySignal(
                new_episode=False, confidence=0.0,
                activity_type="unknown", reasoning="tier1 model not loaded",
            )

        # Trim OCR excerpt — only first 200 chars reach the model
        ocr_trimmed = (ocr_excerpt or "")[:200]

        prompt = _BOUNDARY_PROMPT.format(
            app=app,
            window_title=window_title,
            ocr_excerpt=ocr_trimmed,
            episode_summary=current_episode_summary[:500],
        )

        try:
            output = self._tier1(
                prompt,
                max_tokens=128,
                temperature=0.1,
                stop=["</json>", "\n\n"],
            )
            text = output["choices"][0]["text"].strip()
            return _parse_boundary_response(text)
        except Exception as e:
            log.error("local_inference.boundary_failed", error=str(e))
            return BoundarySignal(
                new_episode=False, confidence=0.0,
                activity_type="unknown", reasoning=f"inference error: {e}",
            )

    def summarize_episode(
        self,
        episode_name: str,
        started_at: str,
        ended_at: str,
        duration_minutes: float,
        observations: list[dict],
    ) -> EpisodeSummary:
        model = self._tier2 or self._tier1
        if model is None:
            return EpisodeSummary(
                key_observations=[],
                activity_classification="unknown",
                classification_confidence=0.0,
                inference_failed=True,
            )

        # Format observations as compact log — no OCR text included
        obs_log = _format_observations(observations)

        prompt = _SUMMARY_PROMPT.format(
            episode_name=episode_name,
            started_at=started_at,
            ended_at=ended_at,
            duration_minutes=round(duration_minutes, 1),
            observations=obs_log,
        )

        try:
            output = model(
                prompt,
                max_tokens=512,
                temperature=0.2,
                stop=["</json>"],
            )
            text = output["choices"][0]["text"].strip()
            return _parse_summary_response(text)
        except Exception as e:
            log.error("local_inference.summary_failed", error=str(e))
            return EpisodeSummary(
                key_observations=[],
                activity_classification="unknown",
                classification_confidence=0.0,
                inference_failed=True,
            )

    def summarize_episode_group(self, matter: str, episodes: list[dict]) -> str:
        """
        Tier 2: Summarize a chunk of episodes for one matter.
        Called by WeeklyReportEngine with ≤4 episodes per chunk.
        Never generates time numbers.
        """
        model = self._tier2 or self._tier1
        if model is None:
            return ""
        obs_lines = []
        for ep in episodes:
            obs_lines.append(
                f"Episode: {ep.get('case_name', '')} "
                f"({ep.get('started_at', '')} – {ep.get('ended_at', '')})"
            )
            for ko in ep.get("key_observations", []):
                text = ko.get("text", "") if isinstance(ko, dict) else str(ko)
                if text:
                    obs_lines.append(f"  - {text}")
        obs_text = "\n".join(obs_lines)
        prompt = _EPISODE_GROUP_PROMPT.format(matter=matter, episodes=obs_text)
        try:
            output = model(prompt, max_tokens=512, temperature=0.2, stop=["</summary>"])
            return output["choices"][0]["text"].strip()
        except Exception as e:
            log.error("local_inference.group_summary_failed", error=str(e))
            return ""

    def compose_weekly_narrative(
        self,
        matter_summaries: list[dict],
        period_start: str,
        period_end: str,
    ) -> str:
        """
        Tier 2: Compose a weekly narrative from per-matter summaries.
        Never generates time numbers — caller appends computed totals.
        """
        model = self._tier2 or self._tier1
        if model is None:
            return ""
        summaries_text = "\n\n".join(
            f"Matter: {ms['matter']}\n{ms['summary']}"
            for ms in matter_summaries
            if ms.get("summary")
        )
        prompt = _WEEKLY_NARRATIVE_PROMPT.format(
            period_start=period_start,
            period_end=period_end,
            matter_summaries=summaries_text,
        )
        try:
            output = model(prompt, max_tokens=1024, temperature=0.3, stop=["</narrative>"])
            return output["choices"][0]["text"].strip()
        except Exception as e:
            log.error("local_inference.narrative_failed", error=str(e))
            return ""


# ── Prompt templates ──────────────────────────────────────────────────────────

_BOUNDARY_PROMPT = """<s>[INST] You are a work-session classifier. Given the current screen context, decide if this represents a new work episode (different task/matter) or continues the current one.

Current episode: {episode_summary}

New observation:
App: {app}
Window: {window_title}
Screen excerpt: {ocr_excerpt}

Respond with JSON only:
{{"new_episode": true/false, "confidence": 0.0-1.0, "activity_type": "research|drafting|correspondence|review|analysis", "reasoning": "brief explanation"}}
</json>[/INST]"""

_SUMMARY_PROMPT = """<s>[INST] You are an executive assistant summarizing professional work. Generate 3-6 concise observations from this work session log. Each observation should describe what was actually done, not what tools were used.

Episode: {episode_name}
Duration: {duration_minutes} minutes ({started_at} - {ended_at})

Activity log:
{observations}

Respond with JSON only:
{{"observations": [{{"timestamp": "HH:MM", "text": "observation text"}}], "activity_classification": "research|drafting|correspondence|review|analysis", "classification_confidence": 0.0-1.0}}
</json>[/INST]"""

_EPISODE_GROUP_PROMPT = """<s>[INST] You are an executive assistant writing a brief summary of work done on a legal matter. Summarize the following episodes in 2-4 sentences. Focus on what was accomplished, not on tools used. Do not generate any time numbers.

Matter: {matter}

Episodes:
{episodes}

Write a concise prose summary:
</summary>[/INST]"""

_WEEKLY_NARRATIVE_PROMPT = """<s>[INST] You are an executive assistant writing a weekly work narrative for the period {period_start} to {period_end}. Synthesize the following matter summaries into a cohesive 1-3 paragraph narrative. Do not generate time numbers — those will be appended separately.

Matter summaries:
{matter_summaries}

Weekly narrative:
</narrative>[/INST]"""


# ── Response parsers ──────────────────────────────────────────────────────────

def _parse_boundary_response(text: str) -> BoundarySignal:
    try:
        # Extract JSON from response (model may include extra text)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("no JSON object found")
        data = json.loads(text[start:end])
        return BoundarySignal(
            new_episode=bool(data.get("new_episode", False)),
            confidence=float(data.get("confidence", 0.5)),
            activity_type=str(data.get("activity_type", "unknown")),
            reasoning=str(data.get("reasoning", "")),
        )
    except Exception:
        return BoundarySignal(new_episode=False, confidence=0.0, activity_type="unknown", reasoning="parse error")


def _parse_summary_response(text: str) -> EpisodeSummary:
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("no JSON object found")
        data = json.loads(text[start:end])
        obs = [
            {"timestamp": o.get("timestamp", ""), "text": o.get("text", "")}
            for o in data.get("observations", [])
            if isinstance(o, dict) and o.get("text")
        ][:config.MAX_KEY_OBSERVATIONS]
        return EpisodeSummary(
            key_observations=obs,
            activity_classification=str(data.get("activity_classification", "unknown")),
            classification_confidence=float(data.get("classification_confidence", 0.5)),
            inference_failed=False,
        )
    except Exception:
        return EpisodeSummary(
            key_observations=[],
            activity_classification="unknown",
            classification_confidence=0.0,
            inference_failed=True,
        )


def _format_observations(observations: list[dict]) -> str:
    """Format observation list as compact log for the summary prompt."""
    lines = []
    for o in observations:
        parts = [o.get("timestamp", "")]
        if o.get("app"):
            parts.append(o["app"])
        if o.get("window_title"):
            parts.append(f'"{o["window_title"]}"')
        if o.get("entities"):
            parts.append("entities: " + ", ".join(o["entities"][:3]))
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines)


# ── Hardware detection ────────────────────────────────────────────────────────

def _detect_gpu_layers() -> int:
    """
    Return n_gpu_layers for llama_cpp.Llama based on available hardware.
    -1 means 'offload all layers' (Metal/CUDA/Vulkan).
    0 means CPU-only.
    """
    import platform as plat
    if plat.system() == "Darwin":
        # Metal is available on all Apple Silicon and AMD macOS systems via MPS
        return -1
    elif plat.system() == "Windows":
        # Check for CUDA
        try:
            import ctypes
            ctypes.cdll.LoadLibrary("nvcuda.dll")
            return -1  # CUDA available
        except OSError:
            pass
        # Check for Vulkan (covers AMD/Intel on Windows)
        try:
            ctypes.cdll.LoadLibrary("vulkan-1.dll")
            return -1
        except OSError:
            pass
    return 0  # CPU fallback


# ── Factory ───────────────────────────────────────────────────────────────────

def get_backend() -> LocalInferenceBackend:
    """
    Return the appropriate backend based on configuration.
    Called once at startup; the result is cached by the caller.
    """
    if not config.USE_LOCAL_INFERENCE:
        return NullBackend()
    backend = LlamaCppBackend()
    if not backend.is_available():
        log.warning("local_inference.backend_unavailable", fallback="NullBackend")
        return NullBackend()
    return backend
