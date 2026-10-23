"""Юнит-тесты детерминированных проверок answer_eval (без LLM и без сети)."""
from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from benchmarks.answer_eval import (
    check_citations,
    check_citation_target,
    check_must_contain,
    check_repetition,
    check_refusal,
    check_should_contain,
    judge_agreement,
    normalize,
    parse_judge_json,
)


class TestNormalize:
    def test_case_and_yo(self):
        assert normalize("Ёлка Отпуск") == "елка отпуск"

    def test_whitespace(self):
        assert normalize("a  b\n\tc") == "a b c"


class TestMustContain:
    def test_all_groups_present(self):
        res = check_must_contain("Отпуск — 28 календарных дней", [["28"]])
        assert res["passed"] and res["missing"] == []

    def test_synonym_group(self):
        res = check_must_contain("3000 RUB в месяц", [["3000"], ["руб", "RUB", "₽"]])
        assert res["passed"]

    def test_missing_group_fails(self):
        res = check_must_contain("Отпуск — 28 дней", [["28"], ["14"]])
        assert not res["passed"] and res["missing"] == ["14"]

    def test_thousand_separator_matched(self):
        # «3 000» — та же цена, что и «3000»: разделители разрядов склеиваются.
        assert check_must_contain("До 3 000 руб.", [["3000"]])["passed"] is True


class TestCitations:
    def test_valid_citation(self):
        res = check_citations("Отпуск 28 дней [1].", n_sources=5)
        assert res["valid"] and res["n_citations"] == 1

    def test_no_citations_invalid(self):
        assert check_citations("Ответ без ссылок.", 5)["valid"] is False

    def test_out_of_range(self):
        res = check_citations("Ответ [7] и [2].", n_sources=5)
        assert not res["valid"] and res["invalid_refs"] == [7]

    def test_multi_digit_ok(self):
        assert check_citations("[10] [11]", n_sources=12)["valid"] is True


class TestRefusal:
    def test_honest_refusal(self):
        res = check_refusal("В документах нет информации о больничных.", ["28", "3000"])
        assert res["passed"] and res["no_fact_leak"]
        assert res["passed_strict"]

    def test_fact_leak_detected(self):
        res = check_refusal("Больничный — 28 дней.", ["28", "3000"])
        assert not res["no_fact_leak"] and not res["passed"]

    def test_citation_with_refusal_is_not_a_hallucination(self):
        """Модель может честно отказать и перечислить, что есть в контексте [1] —
        это легитимно; strict-вариант ловит, основная метрика — нет."""
        res = check_refusal("Не нашёл. Контекст содержит только тарифы [1].", ["28"])
        assert res["passed"] and not res["passed_strict"]

    def test_thousand_separator_normalized(self):
        assert check_must_contain("Цена: 2 990 руб/мес", [["2990"]])["passed"]
        assert check_must_contain("Цена: 9 990 руб./мес", [["9990"]])["passed"]


class TestCitationTarget:
    def test_top1_matches(self):
        assert check_citation_target(["a.docx", "b.pdf"], "a.docx")["passed"]

    def test_top1_differs(self):
        assert not check_citation_target(["b.pdf", "a.docx"], "a.docx")["passed"]

    def test_not_applicable(self):
        res = check_citation_target([], None)
        assert not res["applicable"] and res["passed"]


class TestParseJudgeJson:
    def test_valid(self):
        res = parse_judge_json('{"faithfulness": 5, "relevance": 4, "citations": 3, "issues": "нет цитат"}')
        assert res["faithfulness"] == 5 and res["citations"] == 3

    def test_surrounding_text(self):
        res = parse_judge_json('Вердикт: {"faithfulness": 5, "relevance": 5, "citations": 5} — готово')
        assert res["relevance"] == 5

    def test_out_of_range_clamped(self):
        res = parse_judge_json('{"faithfulness": 9, "relevance": 0, "citations": 3}')
        assert res["faithfulness"] == 5 and res["relevance"] is None

    def test_garbage_returns_none(self):
        assert parse_judge_json("no json here") is None


class TestCompleteness:
    def test_coverage_full(self):
        res = check_should_contain("Отпуск 28 дней, заявление за 14 дней", ["28", "14"])
        assert res["applicable"] and res["coverage"] == 1.0

    def test_coverage_partial(self):
        res = check_should_contain("Отпуск 28 дней", ["28", "14"])
        assert res["coverage"] == 0.5

    def test_not_applicable(self):
        assert check_should_contain("Ответ", [])["applicable"] is False


class TestRepetition:
    def test_connected_text_not_flagged(self):
        text = ("Ежегодный оплачиваемый отпуск составляет двадцать восемь календарных дней. "
                "Заявление подаётся не позднее чем за четырнадцать дней до его начала. "
                "Полностью удалённый формат согласуется с директором департамента.")
        res = check_repetition(text)
        assert res["applicable"] and not res["repetition_suspected"]

    def test_looping_text_flagged(self):
        text = " " .join(["тариф стоит девятьсот девяносто"] * 8)
        res = check_repetition(text)
        assert res["repetition_suspected"]

    def test_short_text_not_applicable(self):
        assert check_repetition("Короткий ответ")["applicable"] is False


class TestJudgeAgreement:
    def test_full_agreement(self):
        rows = [
            {"judge": {"citations": 5}, "citations": {"valid": True}},
            {"judge": {"citations": 2}, "citations": {"valid": False}},
        ]
        res = judge_agreement(rows)
        assert res["n_pairs"] == 2 and res["agreement"] == 1.0

    def test_disagreement(self):
        rows = [{"judge": {"citations": 5}, "citations": {"valid": False}}]
        assert judge_agreement(rows)["agreement"] == 0.0

    def test_no_pairs(self):
        assert judge_agreement([{"judge": None, "citations": None}])["agreement"] is None
