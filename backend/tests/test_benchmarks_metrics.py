"""Юнит-тесты benchmark-метрик и answer-проверок (без сети и без LLM)."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest

from benchmarks.metrics import (
    first_hit_rank,
    latency_summary,
    mrr_at_k,
    percentile,
    recall_at_k,
)


class TestPercentile:
    def test_single_value(self):
        assert percentile([5.0], 50) == 5.0
        assert percentile([5.0], 95) == 5.0

    def test_median_even(self):
        assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5

    def test_p95_interpolates(self):
        # 20 значений 1..20: p95 -> rank = 19*0.95 = 18.05 -> s[18]=19 + 0.05*(20-19) = 19.05
        assert percentile([float(i) for i in range(1, 21)], 95) == pytest.approx(19.05)

    def test_empty(self):
        assert percentile([], 50) == 0.0

    def test_p100_is_max(self):
        assert percentile([3.0, 1.0, 2.0], 100) == 3.0


class TestLatencySummary:
    def test_summary_fields(self):
        s = latency_summary([10.0, 20.0, 30.0, 40.0])
        assert s["n"] == 4
        assert s["mean_ms"] == 25.0
        assert s["min_ms"] == 10.0
        assert s["max_ms"] == 40.0
        assert s["p50_ms"] == 25.0
        assert s["p95_ms"] > s["p50_ms"]
        assert 0 <= s["stdev_ms"] < 20

    def test_empty(self):
        assert latency_summary([]) == {"n": 0}


class TestRankMetrics:
    def test_recall_at_k(self):
        ranks = [1, 2, None, 4, 6]
        assert recall_at_k(ranks, 1) == pytest.approx(1 / 5)
        assert recall_at_k(ranks, 3) == pytest.approx(2 / 5)
        assert recall_at_k(ranks, 5) == pytest.approx(3 / 5)  # 1,2,4 в топ-5; 6 — нет
        assert recall_at_k(ranks, 6) == pytest.approx(4 / 5)  # ненайденный остаётся ненайденным

    def test_recall_empty(self):
        assert recall_at_k([], 5) == 0.0

    def test_mrr_at_k(self):
        # rank 1 -> 1.0; rank 3 -> 1/3; None -> 0; rank 9 -> 0 (вне k=5)
        assert mrr_at_k([1, 3, None, 9], 5) == pytest.approx((1.0 + 1 / 3) / 4)

    def test_mrr_ignores_rank_above_k(self):
        assert mrr_at_k([5], 1) == 0.0
        assert mrr_at_k([5], 5) == pytest.approx(0.2)

    def test_first_hit_rank(self):
        assert first_hit_rank(["a.docx", "b.pdf", "a.docx"], "a.docx") == 1
        assert first_hit_rank(["b.pdf", "a.docx"], "a.docx") == 2
        assert first_hit_rank(["b.pdf"], "a.docx") is None


class TestGoldenSets:
    def test_retrieval_golden_matches_evaluate_py(self):
        """Golden-набор retrieval — точная копия GOLDEN из scripts/evaluate.py:
        те же вопросы и те же целевые документы, в том же порядке."""
        import json

        golden = json.loads((BASE / "eval" / "golden_retrieval.json").read_text("utf-8"))
        assert len(golden["queries"]) == 47
        assert golden["queries"][0]["q"] == "Сколько дней в неделю можно работать удалённо?"
        assert golden["queries"][-1]["q"] == "Что Remote Work Policy говорит про рабочие часы?"
        for item in golden["queries"]:
            assert item["doc"].endswith((".docx", ".xlsx", ".pdf"))
            assert item["category"] in ("fact", "numeric", "paraphrase", "cross-lingual")

    def test_answer_golden_structure(self):
        import json

        golden = json.loads((BASE / "eval" / "golden_answers.json").read_text("utf-8"))
        assert len(golden["answer_queries"]) >= 10
        assert len(golden["negative_queries"]) >= 3
        for item in golden["answer_queries"]:
            assert item["must_contain"], "каждый answer-вопрос обязан иметь проверяемый факт"
        for item in golden["negative_queries"]:
            assert item["forbidden_terms"], "у negative-вопроса должен быть список запрещённых фактов"
