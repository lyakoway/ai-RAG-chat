# ADR-001: Hybrid retrieval (BM25 + RRF) instead of dense-only

- **Status:** Accepted
- **Date:** 2025 (initial measurement), re-verified 2026-11 on the 47-query held-out set
- **Deciders:** project maintainer

## Context

The corpus is bilingual (RU/EN twins of the same documents). Dense-only
retrieval (fastembed paraphrase-multilingual-MiniLM) scored **Recall@1 53.2%**
on the 47-query held-out set: a Russian question often surfaced the English
twin document — semantically close, wrong language. Answer quality depends on
the right document at rank 1, so this was the primary blocker.

## Decision

Hybrid retrieval: BM25 (lexical, rank-bm25) fused with dense vector results
via Reciprocal Rank Fusion (k=60). Dense retrieval stays as a component;
BM25 is added on top. No reranker behind the fusion (see ADR-002).

## Consequences

Measured on the same held-out set, same index:

| Metric | Dense-only | Hybrid BM25+RRF |
|---|---|---|
| Recall@1 | 53.2% | **87.2%** (+34.0 p.p.) |
| Recall@3 | 91.5% | **97.9%** |
| MRR@5 | 0.727 | **0.925** |
| nDCG@5 | 0.786 | **0.940** |

Costs: two indexes to maintain (Chroma + in-memory BM25 rebuilt on collection
size change), slightly more complex pipeline. Retrieval latency stays low
(hybrid p50 ≈ 18–40 ms on the demo corpus, see docs/benchmark.md).

## Alternatives considered

- **Dense-only + reranker** — rejected twice over: dense baseline is the
  problem itself, and the reranker adds latency without fixing it (ADR-002).
- **Pure BM25** — rejected: lexical-only loses semantic matches (paraphrase
  category), and dense embeddings remain valuable for paraphrase queries.

## Evidence

- `backend/benchmarks/retrieval_eval.py` (strategy `all`), artifacts
  `results/*retrieval_*.json`; verified across repeated runs — metrics are
  bit-identical (R@1 0.8723, MRR@5 0.9255).
