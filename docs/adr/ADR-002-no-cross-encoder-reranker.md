# ADR-002: No cross-encoder reranker

- **Status:** Rejected (measured, not adopted)
- **Date:** measured early in the project; recorded in README Measurements
- **Deciders:** project maintainer

## Context

After switching to hybrid retrieval (ADR-001), a cross-encoder reranker
(BAAI/bge-reranker-base via fastembed, ~1 GB ONNX model) was evaluated as a
candidate to further improve top-k precision: rerank fused candidates, keep
top-k.

## Decision

**Do not adopt the reranker.** Hybrid BM25 + RRF without a reranker is the
production configuration.

## Consequences

- No extra latency or model download on the serving path.
- The reranker promotes **language twins**: the cross-encoder scores semantic
  relevance, and a RU/EN twin of the correct document scores as high as the
  correct language — it actively hurts the bilingual use case.

## Alternatives considered

| Option | Recall@1 | MRR@5 | Latency | Outcome |
|---|---|---|---|---|
| Hybrid (no reranker) | **87.2%** | **0.925** | p50 ≈ 18–40 ms | **kept** |
| Hybrid + cross-encoder reranker | 61.7% | 0.683 | rerank p50 ≈ 6.7 s (ONNX CPU) | **rejected** (−25.5 p.p. Recall@1 vs hybrid, +~6.7 s rerank latency) |

> Re-measured 2026-11-09 on the same 47-query held-out set with
> fastembed `TextCrossEncoder` (BAAI/bge-reranker-base, ONNX), candidates =
> hybrid top-20, artifact `results/*reranker_47q.json`. The early measurement
> (41.7% Recall@1, −45.5 p.p.) was not preserved as an artifact; the
> re-measurement confirms the same direction (reranker degrades Recall@1 and
> adds seconds of latency) with a smaller gap.
>
> Latency config: re-measured on CPU (no GPU), fastembed TextCrossEncoder,
> BAAI/bge-reranker-base ONNX (~1 GB), candidates = hybrid top-20 → rerank →
> top-5, batch as in `benchmarks/reranker_eval.py`. The early ~2.9 s figure
> was a different config (not preserved); on CPU ONNX rerank p50 ≈ 6.7 s.

## Evidence

Measured on the same 47-query held-out set, same index (README Measurements
table "Retrieval quality"); the reranker promoted the language twin over the
correct-language document. Re-testing with a better reranker on a larger
corpus is future work — the rejection is specific to this measured setup,
not a universal claim.
