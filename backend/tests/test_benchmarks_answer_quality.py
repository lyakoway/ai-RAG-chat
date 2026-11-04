"""Stage 2: тесты answer-quality контура.

- citation precision/recall: формулы, знаменатели, не-applicable кейсы;
- loading схемы v2 (expected_abstention → refusal-ветка);
- целостность golden_answers_v2.json (уникальность id, согласованность сплитов,
  запрет маркеров, ловящих легитимные факты корпуса — регрессия на найденный
  дефект разметки n8);
- whitespace-only docx отвергается парсером (класс отказа, ранее не покрытый).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pytest

from benchmarks.answer_eval import check_citation_precision_recall
from benchmarks.metrics import golden_set_hash

HITS = [
    {"filename": "A.docx", "page": 1},
    {"filename": "B.pdf", "page": 2},
    {"filename": "A.docx", "page": 3},
]


class TestCitationPrecisionRecall:
    def test_all_citations_to_target(self):
        res = check_citation_precision_recall("Факт [1] и ещё [3].", HITS, "A.docx")
        assert res["applicable"] and res["precision"] == 1.0 and res["recall"] == 1.0

    def test_mixed_citations(self):
        res = check_citation_precision_recall("Верно [1], но и это [2].", HITS, "A.docx")
        assert res["precision"] == 0.5 and res["recall"] == 1.0

    def test_all_wrong_document(self):
        res = check_citation_precision_recall("См. [2].", HITS, "A.docx")
        assert res["precision"] == 0.0 and res["recall"] == 0.0

    def test_out_of_range_lowers_precision(self):
        # [7] не существует: не может поддержать утверждение → precision < 1
        res = check_citation_precision_recall("Факт [1] и [7].", HITS, "A.docx")
        assert res["precision"] == 0.5 and res["recall"] == 1.0

    def test_no_citations_not_applicable(self):
        res = check_citation_precision_recall("Ответ без ссылок.", HITS, "A.docx")
        assert not res["applicable"] and res["precision"] is None

    def test_no_target_not_applicable(self):
        res = check_citation_precision_recall("[1]", HITS, None)
        assert not res["applicable"]

    def test_denominator_is_all_citations(self):
        # Знаменатель precision — ВСЕ ссылки (включая нецелевые), а не только валидные
        res = check_citation_precision_recall("[1] [2] [3] [2]", HITS, "A.docx")
        assert res["n_citations"] == 4 and res["n_to_target"] == 2
        assert res["precision"] == 0.5


class TestGoldenV2Schema:
    @pytest.fixture()
    def v2(self):
        return json.loads((BASE / "eval" / "golden_answers_v2.json").read_text("utf-8"))

    def test_unique_ids_and_split_labels(self, v2):
        ids = [q["id"] for q in v2["queries"]]
        assert len(ids) == len(set(ids)), "id должны быть уникальны"
        for q in v2["queries"]:
            assert q["dev_or_heldout"] in ("dev", "heldout")

    def test_heldout_only_new_ids(self, v2):
        """Held-out не пересекается с dev-набором (a1-a12, n1-n5) — иначе оценка
        не безпристрастна (регрессия на смешение сплитов)."""
        dev_ids = {f"a{i}" for i in range(1, 13)} | {f"n{i}" for i in range(1, 6)}
        held = {q["id"] for q in v2["queries"] if q["dev_or_heldout"] == "heldout"}
        assert held and not (held & dev_ids)

    def test_supported_vs_abstention_consistency(self, v2):
        for q in v2["queries"]:
            assert q["expected_abstention"] == (not q["supported"])
            if q["expected_abstention"] and not q["forbidden_terms"]:
                # пустой запрет допустим только с объяснением (выдумка неперечислима)
                assert q.get("markup_note"), f"{q['id']}: пустой forbidden_terms без note"
            if not q["expected_abstention"]:
                assert q["must_contain"], "answer-вопрос требует эталонных фактов"

    def test_forbidden_terms_do_not_overlap_corpus_facts(self, v2):
        """Регрессия на дефект разметки n8: маркер '3' ловил легитимный факт
        «до 3 дней в неделю». Однозначные числовые маркеры запрещены, если
        это число встречается в демо-корпусе (make_samples facts)."""
        corpus_facts = {"3", "8", "28", "14", "990", "2990", "9990", "3000",
                        "50", "30", "20", "11:00", "16:00", "5"}
        for q in v2["queries"]:
            if q["expected_abstention"]:
                for t in q["forbidden_terms"]:
                    assert t not in corpus_facts, (
                        f"{q['id']}: маркер {t!r} входит в корпусные факты — "
                        f"ловит легитимное перечисление (дефект n8)")


class TestGoldenV2Loading:
    def test_answer_eval_loads_v2_schema(self, monkeypatch, tmp_path):
        """Ветка --golden v2: expected_abstention разделяет queries на answer/refusal."""
        from benchmarks import answer_eval

        v2 = json.loads((BASE / "eval" / "golden_answers_v2.json").read_text("utf-8"))
        answer_qs = [q for q in v2["queries"] if not q.get("expected_abstention")]
        neg_qs = [q for q in v2["queries"] if q.get("expected_abstention")]
        assert len(answer_qs) == 8 and len(neg_qs) == 3
        assert all(q["doc"] is None for q in neg_qs)


class TestWhitespaceDocxRejected:
    def test_whitespace_only_docx_is_parse_error(self, tmp_path):
        """Валидный docx из одних пробелов должен быть отвергнут с осмысленной
        ошибкой (класс отказа, найденный robustness-прогоном)."""
        from docx import Document

        from app.parsers.base import ParseError, parse_document

        doc = Document()
        for _ in range(5):
            doc.add_paragraph("   \n\t  ")
        p = tmp_path / "whitespace.docx"
        doc.save(str(p))
        with pytest.raises(ParseError):
            parse_document(p, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


class TestEnvBlockInArtifacts:
    def test_save_results_writes_env_block(self, tmp_path):
        from benchmarks.metrics import save_results

        paths = save_results({"benchmark": "t", "rows": [{"a": 1}]}, "env_test",
                             fmt=["json"], out_dir=tmp_path)
        saved = json.loads(Path(paths["json"]).read_text("utf-8"))
        assert "env" in saved
        assert "golden_retrieval.json" in saved["env"]["golden_set_sha256"]
        assert "python" in saved["env"]["dependencies"]
        assert saved["env"]["dependencies"]["fastembed"]
