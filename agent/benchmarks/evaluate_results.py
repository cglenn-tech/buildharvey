"""
Benchmark result evaluator.

Presents human + automated scoring for benchmark results from run_benchmark.py.
Summary quality (factual fidelity, hallucination rate, report quality) requires
human evaluation against the ground-truth observations in fixtures/episodes.json.

Usage:
  python benchmarks/evaluate_results.py --results benchmarks/results/tier1_*.json
"""
import argparse
import json
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RESULTS_DIR = Path(__file__).parent / "results"

THRESHOLDS = {
    "boundary_precision": 0.85,
    "boundary_recall": 0.80,
    "activity_accuracy": 0.80,
    "latency_p50_ms": 800,       # CPU baseline
    "peak_ram_mb": 3000,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", nargs="+", required=True, help="JSON result files from run_benchmark.py")
    args = parser.parse_args()

    all_results = []
    for path in args.results:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            all_results.extend(data)
        else:
            all_results.append(data)

    if not all_results:
        print("No results to evaluate.")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("BuildHarvey Local Model Benchmark Results")
    print("=" * 70)

    passing = []
    failing = []

    for r in all_results:
        if "error" in r:
            print(f"\n{r.get('model', '?')}: ERROR — {r['error']}")
            continue

        tier = r.get("tier", "?")
        model = r.get("model", "?")
        passes = True

        print(f"\n[Tier {tier}] {model}")
        print("-" * 50)

        for metric, threshold in THRESHOLDS.items():
            val = r.get(metric)
            if val is None:
                continue
            ok = val >= threshold
            if not ok:
                passes = False
            status = "PASS" if ok else "FAIL"
            print(f"  {metric:35s} {val:8.3f}  threshold={threshold}  [{status}]")

        # Fields without automatic thresholds
        for field in ["n_scenarios", "n_episodes"]:
            if field in r:
                print(f"  {field:35s} {r[field]}")
        if "note" in r:
            print(f"  note: {r['note']}")

        if passes:
            passing.append(model)
        else:
            failing.append(model)

    print("\n" + "=" * 70)
    print(f"PASSING ({len(passing)}): {', '.join(passing) if passing else 'none'}")
    print(f"FAILING ({len(failing)}): {', '.join(failing) if failing else 'none'}")
    print("=" * 70)

    if passing:
        print(
            "\nManual quality evaluation required for passing models:\n"
            "  - Summary factual fidelity ≥ 0.90 (claims supported by observations)\n"
            "  - Hallucination rate ≤ 0.05 (claims not supported by observations)\n"
            "  - Weekly report quality ≥ 4.0 (professional tone, completeness, accuracy)\n"
            "\nCompare generated summaries against fixtures/episodes.json ground truth."
        )
    else:
        print("\nNo models passed all automated thresholds.")
        print("Consider larger quantization (Q8_0) or a different model family.")


if __name__ == "__main__":
    main()
