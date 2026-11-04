"""Stage 3A: тесты citation experiment.

- V0 — точная копия production prompt (регрессия на случайное изменение rag.py);
- V1/V2 — состав и порядок надстроек;
- select_candidate — порядок критериев из ТЗ (качество → затем coverage);
- сохранение/загрузка артефакта эксперимента (save_results + чтение);
- знаменатели citation metrics в summarize_variant.
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest

from app.core import rag
from benchmarks.citation_experiment import (
    build_variants,
    evaluate_answer,
    load_dataset,
    select_candidate,
    summarize_variant,
)

HITS = [
    {"filename": "Policy.docx", "page": 1},
    {"filename": "Pricing.xlsx", "page": 2},
]


class TestPromptVariants:
    def test_v0_is_exact_production_prompt(self):
        """Регрессия: V0 обязан быть точной копией production prompt — иначе
        «baseline» эксперимента измеряет не то, что работает в приложении."""
        variants = build_variants()
        assert variants["V0"] == dict(rag.SYSTEM_PROMPTS)
        assert variants["V0"]["ru"] == rag.SYSTEM_PROMPT_RU
        assert variants["V0"]["en"] == rag.SYSTEM_PROMPT_EN

    def test_v1_adds_fewshot_with_citations(self):
        v1 = build_variants()["V1"]
        assert v1["ru"].startswith(rag.SYSTEM_PROMPT_RU)
        assert "[1]" in v1["ru"] and "[2]" in v1["ru"]

    def test_v2_extends_v1_with_explicit_rules(self):
        v = build_variants()
        assert v["V2"]["ru"].startswith(v["V1"]["ru"])
        assert "[n]" in v["V2"]["ru"]
        assert "неполным" in v["V2"]["ru"]
        assert v["V2"]["en"].startswith(v["V1"]["en"])

    def test_context_placeholder_present_in_all_variants(self):
        """Регрессия на дефект первого прогона: эксперимент подставляет контекст
        через replace('{context}', …) — если placeholder исчезнет из шаблона,
        подстановка молча перестанет работать и модель не увидит контекст."""
        for vid, prompts in build_variants().items():
            for lang, template in prompts.items():
                assert "{context}" in template, f"{vid}/{lang}: нет placeholder {{context}}"

    def test_fewshot_facts_not_from_evaluation_set(self):
        """Few-shot пример не должен содержать фактов из golden-набора
        (отпуск 28, компенсация 3000, тарифы 990/2990/9990, лимит 50)."""
        banned = ("28", "3000", "990", "2990", "9990", "50 МБ", "50 MB",
                  "11:00", "16:00", "отпуск", "отпуск")
        v1 = build_variants()["V1"]
        for lang in ("ru", "en"):
            low = v1[lang].lower()
            for b in banned:
                assert b.lower() not in low, f"few-shot содержит факт из набора: {b}"


class TestSelectCandidate:
    BASE = {"correctness_rate": 1.0, "refusal_pass_rate": 1.0,
            "citation_validity_rate": 1.0, "n_answers_with_citations": 2}

    def _summary(self, vid, correct=1.0, refusal=1.0, validity=1.0, cited=2):
        return {vid: {**self.BASE, "correctness_rate": correct,
                      "refusal_pass_rate": refusal, "citation_validity_rate": validity,
                      "n_answers_with_citations": cited}}

    def test_no_improvement_keeps_baseline(self):
        s = {**self._summary("V0"), **self._summary("V1", cited=2)}
        chosen, reason = select_candidate(s)
        assert chosen == "V0" and "не улучшил" in reason

    def test_quality_regression_rejects_candidate(self):
        s = {**self._summary("V0"), **self._summary("V1", correct=0.9, cited=12)}
        chosen, reason = select_candidate(s)
        assert chosen == "V0"
        assert "correctness деградировал" in reason

    def test_refusal_regression_rejects_candidate(self):
        s = {**self._summary("V0"), **self._summary("V1", refusal=0.6, cited=12)}
        chosen, _ = select_candidate(s)
        assert chosen == "V0"

    def test_formal_citations_reject_candidate(self):
        # validity = доля ответов, где все [n] валидны и их ≥1; падение — формальные цитаты
        s = {**self._summary("V0"), **self._summary("V1", validity=0.5, cited=12)}
        chosen, reason = select_candidate(s)
        assert chosen == "V0" and "validity" in reason

    def test_best_coverage_wins_when_quality_holds(self):
        s = {**self._summary("V0"),
             **self._summary("V1", cited=8),
             **self._summary("V2", cited=11)}
        chosen, reason = select_candidate(s)
        assert chosen == "V2" and "11" in reason

    def test_tie_prefers_earlier_variant(self):
        s = {**self._summary("V0"),
             **self._summary("V1", cited=10),
             **self._summary("V2", cited=10)}
        chosen, _ = select_candidate(s)
        assert chosen == "V1"


class TestSummarizeDenominators:
    def _row(self, qid, kind, *, correct=True, n_cites=0, precision=None, recall=None):
        return {
            "kind": kind, "gen_error": None,
            "eval": {
                "correctness": {"passed": correct, "missing": []},
                "citations": {"n_citations": n_cites, "valid": n_cites > 0, "invalid_refs": []},
                "citation_pr": {"applicable": n_cites > 0, "precision": precision,
                                "recall": recall, "n_citations": n_cites, "n_to_target": n_cites},
                "repetition": {"repetition_suspected": False},
                "refusal": {"passed": True},
            },
            "server_tpot_ms": 50.0, "out_tokens": 40,
        }

    def test_denominators_are_explicit(self):
        rows = [
            {**self._row("a1", "answer", correct=True, n_cites=1, precision=1.0, recall=1.0),
             "variant": "V0"},
            {**self._row("a2", "answer", correct=True, n_cites=0), "variant": "V0"},
            {**self._row("a3", "answer", correct=False, n_cites=2, precision=0.5, recall=0.0),
             "variant": "V0"},
            {**self._row("n1", "refusal"), "variant": "V0"},
        ]
        s = summarize_variant(rows)
        assert s["n_answer"] == 3
        assert s["correctness_rate"] == pytest.approx(round(2 / 3, 4))
        assert s["n_incorrect"] == 1
        assert s["n_answers_with_citations"] == 2
        assert s["n_answers_without_citations"] == 1
        assert s["correct_answer_without_citation_count"] == 1
        assert s["citation_precision_mean"] == pytest.approx(0.75)  # (1.0 + 0.5) / 2 — только cited
        assert s["citation_precision_n"] == 2
        assert s["citation_coverage_rate"] == pytest.approx(round(1 / 3, 4))  # 1 из 3
        assert s["n_refusal"] == 1 and s["refusal_pass_rate"] == 1.0


class TestDatasetLoading:
    def test_dev_v1_shape(self):
        answers, negatives = load_dataset("golden_answers.json")
        assert len(answers) == 12 and len(negatives) == 5

    def test_heldout_v2_shape(self):
        answers, negatives = load_dataset("golden_answers_v2.json")
        assert len(answers) == 8 and len(negatives) == 3
        assert all(not q["expected_abstention"] for q in answers)


class TestEvaluateAnswer:
    def test_eval_uses_answer_eval_checks(self):
        item = {"id": "t1", "doc": "Policy.docx", "must_contain": [["28"]], "should_contain": []}
        ev = evaluate_answer(item, "Отпуск — 28 дней [1].", HITS)
        assert ev["correctness"]["passed"]
        assert ev["citations"]["valid"]
        assert ev["citation_pr"]["precision"] == 1.0

    def test_refusal_eval_uses_forbidden_terms(self):
        from benchmarks.citation_experiment import refusal_eval

        res = refusal_eval("В документах нет информации.", {"forbidden_terms": ["28"]})
        assert res["passed"]


class TestArtifactRoundTrip:
    def test_save_and_load_experiment_payload(self, tmp_path):
        from benchmarks.metrics import save_results

        payload = {"benchmark": "citation_experiment", "chosen_variant": "V1",
                   "prompts": {"V0": {"ru": "x"}}, "summaries": {"V0": {}}, "rows": []}
        paths = save_results(payload, "cite_test", fmt=["json"], out_dir=tmp_path)
        loaded = __import__("json").loads(Path(paths["json"]).read_text("utf-8"))
        assert loaded["chosen_variant"] == "V1"
        assert loaded["prompts"]["V0"]["ru"] == "x"
