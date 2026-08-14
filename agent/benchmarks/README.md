# BuildHarvey Local Model Benchmark Harness

Evaluation harness for selecting the local inference model. Run this before
enabling `USE_LOCAL_INFERENCE=true` in production.

**Model selection is not finalized until benchmarks pass all acceptance thresholds
on all required hardware platforms.** See the Architecture plan for full criteria.

## Directory Structure

```
benchmarks/
  fixtures/            Static synthetic episodes (version-controlled)
  results/             Benchmark output JSON (gitignored)
  generate_fixtures.py Creates synthetic evaluation scenarios
  run_benchmark.py     Runs all model candidates, records metrics to JSON
  evaluate_results.py  Human + automated scoring
```

## Acceptance Thresholds

| Metric | Threshold |
|--------|-----------|
| Episode boundary precision | ≥ 0.85 |
| Episode boundary recall | ≥ 0.80 |
| Activity classification accuracy | ≥ 0.80 |
| Summary factual fidelity | ≥ 0.90 |
| Hallucination rate | ≤ 0.05 |
| Weekly report quality (1-5) | ≥ 4.0 |
| Tier 1 latency p50 (M1) | ≤ 300 ms |
| Tier 1 latency p50 (CPU) | ≤ 800 ms |
| Tier 2 latency (M1) | ≤ 10 s |
| Tier 2 latency (CPU) | ≤ 30 s |
| Peak RAM Tier 1 | ≤ 3000 MB |
| Peak RAM Tier 2 | ≤ 8000 MB |

A model that fails on CPU-only Windows does not meet requirements.

## Model Candidates

Tier 1 (≤4B, classification):
- Llama 3.2 1B Instruct (Q8_0, Q4_K_M, Q3_K_M)
- Llama 3.2 3B Instruct (Q8_0, Q4_K_M, Q3_K_M)
- Phi-4 Mini 3.8B Instruct (Q8_0, Q4_K_M, Q3_K_M)
- Qwen2.5 3B Instruct (Q8_0, Q4_K_M, Q3_K_M)
- SmolLM2 1.7B Instruct (Q8_0, Q4_K_M, Q3_K_M)

Tier 2 (≤9B, summarization):
- Llama 3.1 8B Instruct (Q8_0, Q4_K_M, Q3_K_M)
- Mistral 7B Instruct v0.3 (Q8_0, Q4_K_M, Q3_K_M)
- Qwen2.5 7B Instruct (Q8_0, Q4_K_M, Q3_K_M)
- Gemma 2 9B Instruct (Q8_0, Q4_K_M, Q3_K_M)

Select the smallest model that meets all thresholds on all required platforms.

## Usage

```bash
# Generate synthetic fixtures (one-time)
python benchmarks/generate_fixtures.py

# Run benchmark (requires GGUF models downloaded to LOCAL_MODELS_DIR)
python benchmarks/run_benchmark.py --tier 1 --model llama-3.2-3b-q4_k_m.gguf

# Evaluate results
python benchmarks/evaluate_results.py --results benchmarks/results/latest.json
```

## Important

Benchmark fixtures are synthetic — they do not contain real user data.
Shadow validation (comparing local vs cloud output) is prohibited on real user
work data. All evaluation is on fixtures only.
