"""RAG pipeline: retrieval metadata, hybrid localization, filters, fusion."""
import pytest

from app.core import rag
from app.core.bm25 import bm25_search, rrf_fuse

RU_DOC = "Политика_удалённой_работы.docx"
EN_DOC = "Remote_Work_Policy.docx"


class TestRetrievalMetadata:
    def test_retrieve_returns_hits_with_metadata(self, demo_loaded):
        hits = rag.retrieve(query="сколько дней отпуск", top_k=3)
        assert hits
        for h in hits:
            assert h["document_id"] and h["filename"]
            assert isinstance(h["score"], float)
            assert "text" in h and h["text"].strip()

    def test_retrieve_respects_top_k(self, demo_loaded):
        assert len(rag.retrieve(query="тариф", top_k=2)) <= 2

    def test_category_filter_excludes_others(self, demo_loaded):
        # У демо-пака категория Demo — фильтр по несуществующей даёт пусто.
        assert rag.retrieve(query="тариф", category="Nope") == []

    def test_document_ids_filter(self, demo_loaded):
        hits = rag.retrieve(query="тариф", top_k=5)
        target = hits[0]["document_id"]
        for h in rag.retrieve(query="тариф", top_k=5, document_ids=[target]):
            assert h["document_id"] == target

    def test_wrong_document_ids_returns_empty(self, demo_loaded):
        assert rag.retrieve(query="тариф", document_ids=["nonexistent-id"]) == []


class TestHybridLocalization:
    def test_ru_question_localizes_ru_twin(self, demo_loaded):
        """Двуязычный корпус: RU-вопрос должен поднять RU-документ, а не EN-двойника."""
        hits = rag.retrieve(query="Сколько дней в неделю можно работать удалённо?")
        assert hits[0]["filename"] == RU_DOC

    def test_en_question_localizes_en_twin(self, demo_loaded):
        hits = rag.retrieve(query="How many days per week can employees work remotely?")
        assert hits[0]["filename"] == EN_DOC

    def test_cross_language_query_still_finds_document(self, demo_loaded):
        """EN-вопрос с именем RU-документа — гибрид вытягивает названный документ."""
        hits = rag.retrieve(
            query="How many vacation days does Политика удалённой работы grant?",
            top_k=5,
        )
        assert RU_DOC in [h["filename"] for h in hits[:3]]

    def test_bm25_matches_exact_terms(self, demo_loaded):
        """BM25 достаёт фрагмент по точному термину, который мог потеряться в векторах."""
        res = bm25_search(text="Enterprise", top_k=3)
        assert res  # точный термин найден лексически


class TestRRFFusion:
    def test_rrf_merges_rankings(self):
        fused = rrf_fuse([{"a": 0.9, "b": 0.5}, {"b": 0.9, "c": 0.5}])
        # b — высоко в обоих рейтингах, суммарно должен обгонять одиночные
        assert fused["b"] > fused["a"]
        assert fused["b"] > fused["c"]

    def test_rrf_empty_rankings(self):
        assert rrf_fuse([]) == {}

    def test_rrf_rank_order_matters_not_score(self):
        # RRF учитывает позицию, а не величину score: 0.9 vs 0.001 на одном месте равны.
        fused = rrf_fuse([{"x": 0.9}, {"x": 0.001}])
        assert fused["x"] == 2 * (1.0 / (60 + 1))


class TestPromptBuilding:
    def test_build_context_formats_blocks(self, demo_loaded):
        hits = rag.retrieve(query="сколько дней отпуск", top_k=2)
        context = rag.build_context(hits)
        assert "[1]" in context and "---" in context

    def test_system_prompt_empty_hits(self):
        prompt = rag.build_system_prompt([], "ru")
        assert "нет релевантных фрагментов" in prompt

    def test_system_prompt_lang_en(self, demo_loaded):
        hits = rag.retrieve(query="тариф", top_k=1)
        prompt = rag.build_system_prompt(hits, "en")
        assert "CONTEXT:" in prompt
        assert "Answer IN ENGLISH" in prompt
