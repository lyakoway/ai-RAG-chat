"""Юнит-тесты llm_bench: расчёт таймингов и агрегатов из сырых измерений."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest

from benchmarks import llm_bench
from benchmarks.llm_bench import _finalize, aggregate


def _mk_rows(n_ok: int = 3, n_err: int = 1) -> list[dict]:
    rows = []
    for i in range(n_ok):
        rows.append({
            "ok": True, "error": None, "retries": 0,
            "time_to_first_chunk_ms": 100.0 + i * 100,
            "time_to_first_content_ms": 200.0 + i * 100,
            "stream_ms": 500.0, "total_ms": 800.0 + i * 100,
            "chunks": 10, "reasoning": None,
            "itl_ms_p50": 50.0, "itl_ms_p95": 90.0,
            "in_tokens": 100, "out_tokens": 50, "tokens_source": "usage",
            "output_tokens_per_sec_stream": 100.0,
            "answer": "x", "answer_chars": 1, "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        })
    for i in range(n_err):
        rows.append({
            "ok": False, "error": "TimeoutError: boom", "retries": 1,
            "time_to_first_chunk_ms": None, "time_to_first_content_ms": None,
            "stream_ms": None, "total_ms": None, "chunks": 0, "reasoning": None,
            "itl_ms_p50": None, "itl_ms_p95": None, "in_tokens": None,
            "out_tokens": None, "tokens_source": None,
            "output_tokens_per_sec_stream": None, "answer": "", "answer_chars": 0, "usage": None,
        })
    return rows


class TestFinalize:
    def test_timings_and_tokens_from_usage(self):
        import time

        now = time.perf_counter()
        t0 = now - 1.0                      # старт секунду назад
        chunk_ts = [t0 + 0.1, t0 + 0.3, t0 + 0.6]
        r = _finalize(
            {"usage": {"prompt_tokens": 42, "completion_tokens": 7}, "retries": 0},
            chunk_ts, "hello world", "sys", "user", t0,
        )
        assert r["chunks"] == 3
        assert r["in_tokens"] == 42 and r["out_tokens"] == 7
        assert r["tokens_source"] == "usage"
        assert r["time_to_first_chunk_ms"] == pytest.approx(100.0, abs=5)
        assert r["time_to_first_content_ms"] == pytest.approx(100.0, abs=5)
        assert r["stream_ms"] == pytest.approx(500.0, abs=5)
        assert r["total_ms"] > r["stream_ms"]

    def test_reasoning_first_chunk_precedes_content(self):
        import time

        base = time.perf_counter()
        reasoning_ts = [base + 0.2]
        chunk_ts = [base + 1.0]
        r = _finalize(
            {"usage": None, "retries": 0}, chunk_ts, "ans", "s", "u", base,
            first_stream_ts=reasoning_ts,
            reasoning_stats={"reasoning_chunks": 5, "reasoning_ms_first_to_last": 700.0},
        )
        assert r["time_to_first_chunk_ms"] == pytest.approx(200.0, abs=5)
        assert r["time_to_first_content_ms"] == pytest.approx(1000.0, abs=5)
        assert r["reasoning"]["reasoning_chunks"] == 5

    def test_token_estimate_fallback(self):
        import time

        base = time.perf_counter()
        r = _finalize({"usage": None, "retries": 0}, [base + 0.05], "hello", "s", "u", base)
        assert r["tokens_source"] == "tiktoken-estimate"
        assert r["out_tokens"] == 1  # "hello" — один токен


class TestAggregate:
    def test_counts_and_percentiles(self):
        agg = aggregate(_mk_rows(n_ok=3, n_err=1))
        assert agg["n_requests"] == 4
        assert agg["n_ok"] == 3
        assert agg["n_errors"] == 1
        assert agg["ttft_summary"]["n"] == 3
        assert agg["e2e_summary"]["p50_ms"] == 900.0
        assert agg["output_tokens_per_sec"]["p50"] == 100.0
        assert agg["tokens_source"] == ["usage"]

    def test_all_errors(self):
        agg = aggregate(_mk_rows(n_ok=0, n_err=2))
        assert agg["n_ok"] == 0
        assert agg["ttft_summary"] == {"n": 0}
        assert agg["errors"]
