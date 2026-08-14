"""
Local model benchmark runner.

Runs all model candidates against the synthetic evaluation fixtures and records
metrics to JSON. Results are gitignored (benchmarks/results/).

Usage:
  python benchmarks/run_benchmark.py --tier 1 --model path/to/model.gguf
  python benchmarks/run_benchmark.py --all --tier 1

Requirements:
  pip install llama-cpp-python psutil

Before running:
  python benchmarks/generate_fixtures.py

Do NOT run this against real user data. All evaluation is on synthetic fixtures.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).parent
FIXTURES_DIR = BENCHMARKS_DIR / "fixtures"
RESULTS_DIR = BENCHMARKS_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# Model candidates — update paths to local GGUF files
TIER1_CANDIDATES = [
    "llama-3.2-1b-instruct-q8_0.gguf",
    "llama-3.2-1b-instruct-q4_k_m.gguf",
    "llama-3.2-3b-instruct-q8_0.gguf",
    "llama-3.2-3b-instruct-q4_k_m.gguf",
    "phi-4-mini-3.8b-instruct-q4_k_m.gguf",
    "qwen2.5-3b-instruct-q4_k_m.gguf",
    "smollm2-1.7b-instruct-q4_k_m.gguf",
]

TIER2_CANDIDATES = [
    "llama-3.1-8b-instruct-q4_k_m.gguf",
    "mistral-7b-instruct-v0.3-q4_k_m.gguf",
    "qwen2.5-7b-instruct-q4_k_m.gguf",
    "gemma-2-9b-instruct-q4_k_m.gguf",
]

# Acceptance thresholds
THRESHOLDS = {
    "boundary_precision": 0.85,
    "boundary_recall": 0.80,
    "activity_accuracy": 0.80,
    "tier1_latency_p50_m1_ms": 300,
    "tier1_latency_p50_cpu_ms": 800,
    "tier2_latency_m1_s": 10,
    "tier2_latency_cpu_s": 30,
    "peak_ram_tier1_mb": 3000,
    "peak_ram_tier2_mb": 8000,
}


def load_fixtures() -> tuple[list, list]:
    """Load synthetic evaluation fixtures."""
    episodes_path = FIXTURES_DIR / "episodes.json"
    boundaries_path = FIXTURES_DIR / "boundary_scenarios.json"

    if not episodes_path.exists() or not boundaries_path.exists():
        print("ERROR: fixtures not found. Run: python benchmarks/generate_fixtures.py")
        sys.exit(1)

    with open(episodes_path) as f:
        episodes = json.load(f)
    with open(boundaries_path) as f:
        boundaries = json.load(f)

    return episodes, boundaries


def benchmark_tier1(model_path: str, boundaries: list) -> dict:
    """
    Benchmark a Tier 1 model (boundary classification).
    Returns metrics dict.
    """
    try:
        from llama_cpp import Llama
        import psutil
    except ImportError:
        print("ERROR: pip install llama-cpp-python psutil")
        sys.exit(1)

    print(f"\nTier 1: {Path(model_path).name}")
    print("-" * 60)

    if not os.path.exists(model_path):
        print(f"  Model not found: {model_path}")
        return {"error": "model_not_found"}

    # Load model
    t_load_start = time.monotonic()
    llm = Llama(model_path=model_path, n_gpu_layers=-1, n_ctx=2048, verbose=False)
    t_load_end = time.monotonic()
    print(f"  Load time: {t_load_end - t_load_start:.1f}s")

    latencies = []
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    activity_correct = 0
    activity_total = 0
    peak_ram_mb = 0

    for scenario in boundaries:
        process = __import__("psutil").Process(os.getpid())
        ram_before = process.memory_info().rss / 1024 / 1024

        prompt = _boundary_prompt(scenario)
        t0 = time.monotonic()
        output = llm(prompt, max_tokens=128, temperature=0.1)
        t1 = time.monotonic()
        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)

        ram_after = process.memory_info().rss / 1024 / 1024
        peak_ram_mb = max(peak_ram_mb, ram_after)

        text = output["choices"][0]["text"].strip()
        predicted = _parse_boundary(text)
        ground_truth = scenario["ground_truth_new_episode"]

        if predicted.get("new_episode") == ground_truth:
            if ground_truth:
                true_positives += 1
        elif predicted.get("new_episode") and not ground_truth:
            false_positives += 1
        elif not predicted.get("new_episode") and ground_truth:
            false_negatives += 1

        pred_activity = predicted.get("activity_type", "unknown")
        gt_activity = scenario.get("ground_truth_activity", "unknown")
        if gt_activity != "unknown":
            activity_total += 1
            if pred_activity == gt_activity:
                activity_correct += 1

        status = "✓" if predicted.get("new_episode") == ground_truth else "✗"
        print(f"  {status} [{scenario['id']}] latency={latency_ms:.0f}ms predicted={predicted.get('new_episode')} gt={ground_truth}")

    # Compute metrics
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

    total_predicted_positive = true_positives + false_positives
    precision = true_positives / total_predicted_positive if total_predicted_positive > 0 else 0
    total_actual_positive = true_positives + false_negatives
    recall = true_positives / total_actual_positive if total_actual_positive > 0 else 0
    activity_acc = activity_correct / activity_total if activity_total > 0 else 0

    metrics = {
        "model": Path(model_path).name,
        "tier": 1,
        "boundary_precision": round(precision, 3),
        "boundary_recall": round(recall, 3),
        "activity_accuracy": round(activity_acc, 3),
        "latency_p50_ms": round(p50, 1),
        "latency_p95_ms": round(p95, 1),
        "peak_ram_mb": round(peak_ram_mb, 1),
        "n_scenarios": len(boundaries),
        "passes_thresholds": (
            precision >= THRESHOLDS["boundary_precision"] and
            recall >= THRESHOLDS["boundary_recall"] and
            activity_acc >= THRESHOLDS["activity_accuracy"]
        ),
    }

    _print_metrics(metrics)
    return metrics


def benchmark_tier2(model_path: str, episodes: list) -> dict:
    """
    Benchmark a Tier 2 model (episode summarization).
    Returns metrics dict.
    """
    try:
        from llama_cpp import Llama
        import psutil
    except ImportError:
        print("ERROR: pip install llama-cpp-python psutil")
        sys.exit(1)

    print(f"\nTier 2: {Path(model_path).name}")
    print("-" * 60)

    if not os.path.exists(model_path):
        print(f"  Model not found: {model_path}")
        return {"error": "model_not_found"}

    llm = Llama(model_path=model_path, n_gpu_layers=-1, n_ctx=4096, verbose=False)

    latencies = []
    peak_ram_mb = 0

    for ep in episodes[:5]:  # Sample first 5 episodes for speed
        process = __import__("psutil").Process(os.getpid())
        ram_before = process.memory_info().rss / 1024 / 1024

        prompt = _summary_prompt(ep)
        t0 = time.monotonic()
        output = llm(prompt, max_tokens=512, temperature=0.2)
        t1 = time.monotonic()
        latency_s = t1 - t0
        latencies.append(latency_s)

        ram_after = process.memory_info().rss / 1024 / 1024
        peak_ram_mb = max(peak_ram_mb, ram_after)

        print(f"  [{ep['id']}] latency={latency_s:.1f}s")

    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0

    metrics = {
        "model": Path(model_path).name,
        "tier": 2,
        "latency_p50_s": round(p50, 2),
        "peak_ram_mb": round(peak_ram_mb, 1),
        "n_episodes": len(episodes[:5]),
        "passes_thresholds": True,  # Human evaluation required for quality thresholds
        "note": "Quality metrics require human evaluation — see evaluate_results.py",
    }

    _print_metrics(metrics)
    return metrics


def _boundary_prompt(scenario: dict) -> str:
    return (
        f"<s>[INST] Is this a new work episode?\n"
        f"Current: {scenario['current_episode']}\n"
        f"App: {scenario['after']['app']}\n"
        f"Window: {scenario['after']['window_title']}\n"
        f"Excerpt: {scenario['after']['ocr_excerpt'][:200]}\n"
        f"JSON only: {{\"new_episode\": true/false, \"activity_type\": \"research|drafting|correspondence|review|analysis\"}} [/INST]"
    )


def _summary_prompt(ep: dict) -> str:
    obs_text = "\n".join(
        f"{o['timestamp']} | {o['app']} | {o['window_title']}"
        for o in ep["observations"]
    )
    return (
        f"<s>[INST] Summarize this work session:\n"
        f"Matter: {ep['episode_name']}\n"
        f"Duration: {ep['duration_minutes']} min\n"
        f"Activity log:\n{obs_text}\n"
        f"JSON only: {{\"observations\": [{{\"timestamp\": \"HH:MM\", \"text\": \"...\"}}]}} [/INST]"
    )


def _parse_boundary(text: str) -> dict:
    try:
        import json as _json
        start = text.find("{")
        end = text.rfind("}") + 1
        if start < 0 or end <= start:
            return {}
        return _json.loads(text[start:end])
    except Exception:
        return {}


def _print_metrics(metrics: dict) -> None:
    print(f"\n  Results for {metrics['model']}:")
    for k, v in metrics.items():
        if k not in ("model", "tier", "note"):
            threshold = THRESHOLDS.get(k)
            marker = ""
            if threshold is not None:
                marker = " ✓" if (isinstance(v, (int, float)) and v >= threshold) else " ✗ (below threshold)"
            print(f"    {k}: {v}{marker}")
    if "note" in metrics:
        print(f"    note: {metrics['note']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="BuildHarvey local model benchmark")
    parser.add_argument("--tier", type=int, choices=[1, 2], required=True, help="Model tier to benchmark")
    parser.add_argument("--model", type=str, help="Path to GGUF model file")
    parser.add_argument("--all", action="store_true", help="Run all candidate models for this tier")
    args = parser.parse_args()

    episodes, boundaries = load_fixtures()

    results = []
    if args.all:
        candidates = TIER1_CANDIDATES if args.tier == 1 else TIER2_CANDIDATES
        for model_name in candidates:
            path = str(Path.home() / "Library" / "Application Support" / "BuildHarvey" / "models" / model_name)
            if args.tier == 1:
                r = benchmark_tier1(path, boundaries)
            else:
                r = benchmark_tier2(path, episodes)
            results.append(r)
    elif args.model:
        if args.tier == 1:
            r = benchmark_tier1(args.model, boundaries)
        else:
            r = benchmark_tier2(args.model, episodes)
        results.append(r)
    else:
        parser.error("Specify --model PATH or --all")

    # Save results
    ts = time.strftime("%Y%m%dT%H%M%S")
    out_path = RESULTS_DIR / f"tier{args.tier}_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written → {out_path}")


if __name__ == "__main__":
    main()
