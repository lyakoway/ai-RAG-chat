"""Agent loop: tool calls, self-correction формата, лимит шагов, дедуп хитов.

Используется FakeProvider со сценариями ответов — детерминированно, без сети.
"""
import asyncio
import io

import pytest
from docx import Document as DocxBuilder

from app.core.agent import MAX_STEPS, _dedupe_hits, _parse_action, run_agent
from app.db.session import SessionLocal


class FakeProvider:
    """Отвечает заготовленными репликами по очереди (последняя повторяется)."""

    provider = "fake"
    model = "fake-1"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def available(self):
        return True

    async def stream(self, system, messages, lang="ru"):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        yield reply


def _collect(provider, user_message="вопрос по документам"):
    events = []

    async def run():
        db = SessionLocal()
        try:
            async for event, data in run_agent(
                provider=provider,
                history=[],
                lang="ru",
                db=db,
                category=None,
                document_ids=None,
                top_k=5,
                user_message=user_message,
            ):
                events.append((event, data))
        finally:
            db.close()

    asyncio.run(run())
    return events


class TestAgentFlow:
    def test_tool_call_then_final_answer(self, demo_loaded):
        provider = FakeProvider([
            '{"tool":"search_documents","args":{"query":"тариф Старт"}}',
            '{"final":true,"answer":"Старт стоит 990 руб./мес. [1]"}',
        ])
        events = _collect(provider)
        kinds = [e for e, _ in events]

        assert "agent_step" in kinds
        assert "sources" in kinds
        assert "token" in kinds
        assert "agent_meta" in kinds

        step = next(d for e, d in events if e == "agent_step")
        assert step["ok"] is True
        answer = "".join(d.get("delta", "") for e, d in events if e == "token")
        assert "990" in answer and "[1]" in answer

    def test_unknown_tool_does_not_crash(self, demo_loaded):
        provider = FakeProvider([
            '{"tool":"delete_everything"}',
            '{"final":true,"answer":"Не нашёл такого инструмента."}',
        ])
        events = _collect(provider)
        step = next(d for e, d in events if e == "agent_step")
        assert step["name"] == "delete_everything"
        # цикл жив: финальный ответ пришёл
        assert any(e == "token" for e, _ in events)

    def test_tool_error_marks_step_failed(self, demo_loaded):
        provider = FakeProvider([
            '{"tool":"search_documents","args":{}}',  # пустой query → ошибка
            '{"final":true,"answer":"Нет результатов поиска."}',
        ])
        events = _collect(provider)
        step = next(d for e, d in events if e == "agent_step")
        assert step["ok"] is False
        assert "Error" in provider.replies[0] or step["detail"]

    def test_invalid_format_recovers_via_nudge(self, demo_loaded):
        provider = FakeProvider([
            "Привет! Я отвечу прямо сейчас, без инструментов.",
            '{"final":true,"answer":"Вот корректный ответ. [1]"}',
        ])
        events = _collect(provider)
        kinds = [e for e, _ in events]
        assert "token" in kinds  # агент дожал корректный ответ

    def test_tool_loop_capped_at_max_steps(self, demo_loaded):
        """Модель зациклилась на tool-calls — лимит шагов останавливает цикл."""
        provider = FakeProvider(['{"tool":"search_documents","args":{"query":"а"}}'])
        events = _collect(provider)
        steps = next(d for e, d in events if e == "agent_meta")
        assert len(steps) <= MAX_STEPS
        # после лимита — fallback: sources + ответ всё равно приходят
        assert any(e == "sources" for e, _ in events)

    def test_demo_loaded_provider_loop_never_hangs(self, demo_loaded):
        """Пустые реплики: fallback-путь не зависает и отдаёт sources."""
        provider = FakeProvider([""])
        events = _collect(provider)
        assert any(e == "sources" for e, _ in events)


class TestAgentHelpers:
    def test_parse_action_accepts_markdown_fences(self):
        raw = '```json\n{"tool":"search_documents","args":{"query":"тест"}}\n```'
        action = _parse_action(raw)
        assert action["tool"] == "search_documents"
        assert action["args"]["query"] == "тест"

    def test_parse_action_garbage_returns_none(self):
        assert _parse_action("совсем не json") is None
        assert _parse_action("") is None

    def test_dedupe_hits_by_doc_chunk_page(self):
        hit = {"document_id": "d1", "chunk_index": 0, "page": 1}
        dup = dict(hit)
        other = {"document_id": "d1", "chunk_index": 1, "page": 1}
        out = _dedupe_hits([hit, dup, other])
        assert len(out) == 2
