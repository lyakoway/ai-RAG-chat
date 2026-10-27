"""Юнит-тесты compare.py: классификация метрик и вердикты регрессий."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from benchmarks.compare import classify, compare_payloads, flatten_numbers, verdict


class TestFlatten:
    def test_nested_numbers(self):
        data = {"benchmark": "x", "results": [{"metrics": {"recall@1": 0.5, "n": 47}}],
                "rows": [{"skip": "me"}], "env": {"dependencies": {}}}
        flat = flatten_numbers(data)
        assert flat == {"results.0.metrics.recall@1": 0.5, "results.0.metrics.n": 47.0}


class TestClassify:
    def test_quality(self):
        assert classify("results.0.metrics.recall@1") == "QUALITY"
        assert classify("aggregates.correctness_rate") == "QUALITY"
        assert classify("per_model.m.judge_faithfulness_avg") == "QUALITY"

    def test_latency(self):
        assert classify("latency.p50_ms") == "LATENCY"
        assert classify("per_variant.tpot_ms.p95_ms") == "LATENCY"
        assert classify("total_ms") == "LATENCY"

    def test_cost_and_info(self):
        assert classify("per_model.m.cost_usd_mean") == "COST"
        assert classify("n_requests") == "INFO"


class TestVerdict:
    Q_EPS = 0.005
    L_TOL = 0.25

    def test_quality_regression_and_improvement(self):
        assert verdict("QUALITY", 0.872, 0.80, self.Q_EPS, self.L_TOL) == "REGRESSION"
        assert verdict("QUALITY", 0.872, 0.90, self.Q_EPS, self.L_TOL) == "IMPROVED"
        assert verdict("QUALITY", 0.872, 0.870, self.Q_EPS, self.L_TOL) == "OK"  # шум

    def test_latency_tolerance_band(self):
        # +20% — внутри допуска (межпрогонный шум), +30% — регрессия
        assert verdict("LATENCY", 100.0, 120.0, self.Q_EPS, self.L_TOL) == "OK"
        assert verdict("LATENCY", 100.0, 131.0, self.Q_EPS, self.L_TOL) == "REGRESSION"
        assert verdict("LATENCY", 100.0, 60.0, self.Q_EPS, self.L_TOL) == "IMPROVED"

    def test_cost_relative_tolerance(self):
        # COST — относительный допуск: удвоение $0.0002 — регрессия,
        # а дельта 0.001 на базовой 0.5 — шум
        assert verdict("COST", 0.0002, 0.0004, self.Q_EPS, self.L_TOL) == "REGRESSION"
        assert verdict("COST", 0.0002, 0.00021, self.Q_EPS, self.L_TOL) == "OK"
        assert verdict("COST", 0.5, 0.501, self.Q_EPS, self.L_TOL) == "OK"
        assert verdict("COST", 0.0002, 0.0001, self.Q_EPS, self.L_TOL) == "IMPROVED"


class TestComparePayloads:
    def _payload(self, recall: float, p50: float) -> dict:
        return {"benchmark": "retrieval_eval",
                "results": [{"strategy": "hybrid",
                             "metrics": {"recall@1": recall, "mrr@5": 0.9},
                             "latency": {"p50_ms": p50}}]}

    def test_matching_and_missing_keys(self):
        base = self._payload(0.87, 18.0)
        cand = self._payload(0.80, 20.0)
        cand["results"][0]["metrics"]["ndcg@5"] = 0.9  # есть только в candidate
        rows = compare_payloads(base, cand)
        by = {r["metric"]: r for r in rows}
        assert "results.0.metrics.recall@1" in by
        assert by["results.0.metrics.recall@1"]["verdict"] == "REGRESSION"
        assert by["results.0.latency.p50_ms"]["verdict"] == "OK"  # +11% в допуске
        assert not any("ndcg" in r["metric"] for r in rows)  # нет в baseline — не сравнивается

    def test_identical_payloads_all_ok(self):
        rows = compare_payloads(self._payload(0.87, 18.0), self._payload(0.87, 18.0))
        assert rows and all(r["verdict"] == "OK" for r in rows)
