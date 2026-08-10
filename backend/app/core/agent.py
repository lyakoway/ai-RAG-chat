"""Document research agent: ReAct-style loop with JSON tool calls over any LLM provider."""
from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.orm import Session

from app.core import agent_tools, rag
from app.llm.base import ChatMessage, LLMProvider

MAX_STEPS = 5

AGENT_SYSTEM_RU = """Ты — исследовательский AI-агент по загруженным документам.
Ты НЕ отвечаешь сразу: сначала вызываешь инструменты, потом даёшь финальный ответ.

{tools}

Правила:
- Перед ответом обязательно вызови search_documents хотя бы один раз (можно с разными запросами).
- При необходимости сначала list_documents.
- Отвечай ТОЛЬКО одним JSON-объектом за ход (без markdown-ограждений, без текста вокруг).
- Финальный ответ — на русском, кратко, со ссылками [1], [2] на фрагменты из результатов search_documents.
- Если данных нет — честно скажи об этом в final.answer.
"""

AGENT_SYSTEM_EN = """You are a research AI agent over the user's uploaded documents.
Do NOT answer immediately: call tools first, then give a final answer.

{tools}

Rules:
- Call search_documents at least once before the final answer (you may refine the query).
- Use list_documents when you need to see which files exist.
- Each turn reply with EXACTLY one JSON object (no markdown fences, no extra text).
- Final answer in English, concise, with [1], [2] citations from search_documents fragments.
- If nothing relevant is found, say so in final.answer.
"""


async def _collect(
    provider: LLMProvider, system: str, messages: list[ChatMessage], lang: str
) -> str:
    parts: list[str] = []
    async for delta in provider.stream(system, messages, lang):
        parts.append(delta)
    return "".join(parts).strip()


def _parse_action(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    # Prefer first JSON object in the reply.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _dedupe_hits(all_hits: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for h in all_hits:
        key = (h.get("document_id"), h.get("chunk_index"), h.get("page"))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


async def run_agent(
    *,
    provider: LLMProvider,
    history: list[ChatMessage],
    lang: str,
    db: Session,
    category: str | None,
    document_ids: list[str] | None,
    top_k: int | None,
    user_message: str,
) -> AsyncIterator[tuple[str, dict]]:
    """Yield SSE-ready (event, data) pairs: agent_step, sources, token."""

    # Demo provider: deterministic multi-step flow (always works offline).
    if getattr(provider, "provider", None) == "mock":
        async for item in _mock_agent(
            provider=provider,
            history=history,
            lang=lang,
            db=db,
            category=category,
            document_ids=document_ids,
            top_k=top_k,
            user_message=user_message,
        ):
            yield item
        return

    system = (AGENT_SYSTEM_RU if lang != "en" else AGENT_SYSTEM_EN).format(
        tools=agent_tools.tools_prompt_block()
    )
    messages = list(history)
    accumulated_hits: list[dict] = []
    steps: list[dict] = []
    step_no = 0

    for _ in range(MAX_STEPS):
        raw = await _collect(provider, system, messages, lang)
        action = _parse_action(raw)

        if action and action.get("final") is True:
            answer = str(action.get("answer") or "").strip()
            if not answer:
                answer = (
                    "Не удалось сформировать ответ."
                    if lang != "en"
                    else "Could not form an answer."
                )
            sources = rag.to_sources(_dedupe_hits(accumulated_hits))
            yield (
                "sources",
                {"sources": [s.model_dump() for s in sources]},
            )
            for token in _chunk_text(answer):
                yield ("token", {"delta": token})
            yield ("agent_meta", {"steps": steps})
            return

        if action and action.get("tool"):
            tool_name = str(action["tool"])
            args = action.get("args") if isinstance(action.get("args"), dict) else {}
            step_no += 1
            observation, hits = agent_tools.run_tool(
                tool_name,
                args,
                db=db,
                category=category,
                document_ids=document_ids,
                top_k=top_k,
            )
            if hits:
                accumulated_hits.extend(hits)
            step = {
                "index": step_no,
                "type": "tool",
                "name": tool_name,
                "args": args,
                "ok": not observation.startswith("Error"),
                "detail": _step_detail(tool_name, args, observation, hits, lang),
            }
            steps.append(step)
            yield ("agent_step", step)

            messages = messages + [
                ChatMessage(role="assistant", content=json.dumps(action, ensure_ascii=False)),
                ChatMessage(
                    role="user",
                    content=f"TOOL_RESULT ({tool_name}):\n{observation}",
                ),
            ]
            continue

        # Model drifted — nudge once, then force a search + answer path.
        messages = messages + [
            ChatMessage(role="assistant", content=raw or ""),
            ChatMessage(
                role="user",
                content=(
                    "Invalid format. Reply with JSON only: "
                    '{"tool":"search_documents","args":{"query":"..."}} '
                    'or {"final":true,"answer":"..."}'
                ),
            ),
        ]

    # Fallback: one search + grounded answer like classic RAG.
    hits = rag.retrieve(
        query=user_message,
        top_k=top_k,
        category=category,
        document_ids=document_ids,
    )
    accumulated_hits.extend(hits)
    step_no += 1
    step = {
        "index": step_no,
        "type": "tool",
        "name": "search_documents",
        "args": {"query": user_message},
        "ok": True,
        "detail": _step_detail(
            "search_documents", {"query": user_message}, "", hits, lang
        ),
    }
    steps.append(step)
    yield ("agent_step", step)

    sources = rag.to_sources(_dedupe_hits(accumulated_hits))
    yield ("sources", {"sources": [s.model_dump() for s in sources]})
    system_rag = rag.build_system_prompt(hits, lang)
    async for delta in provider.stream(system_rag, history, lang):
        yield ("token", {"delta": delta})
    yield ("agent_meta", {"steps": steps})


async def _mock_agent(
    *,
    provider: LLMProvider,
    history: list[ChatMessage],
    lang: str,
    db: Session,
    category: str | None,
    document_ids: list[str] | None,
    top_k: int | None,
    user_message: str,
) -> AsyncIterator[tuple[str, dict]]:
    """Offline demo: list → search → answer, with visible agent steps."""
    steps: list[dict] = []

    obs_list, _ = agent_tools.run_tool(
        "list_documents",
        {},
        db=db,
        category=category,
        document_ids=document_ids,
        top_k=top_k,
    )
    step1 = {
        "index": 1,
        "type": "tool",
        "name": "list_documents",
        "args": {},
        "ok": True,
        "detail": _step_detail("list_documents", {}, obs_list, [], lang),
    }
    steps.append(step1)
    yield ("agent_step", step1)

    obs_search, hits = agent_tools.run_tool(
        "search_documents",
        {"query": user_message},
        db=db,
        category=category,
        document_ids=document_ids,
        top_k=top_k,
    )
    step2 = {
        "index": 2,
        "type": "tool",
        "name": "search_documents",
        "args": {"query": user_message},
        "ok": True,
        "detail": _step_detail(
            "search_documents", {"query": user_message}, obs_search, hits, lang
        ),
    }
    steps.append(step2)
    yield ("agent_step", step2)

    sources = rag.to_sources(hits)
    yield ("sources", {"sources": [s.model_dump() for s in sources]})

    system = rag.build_system_prompt(hits, lang)
    async for delta in provider.stream(system, history, lang):
        yield ("token", {"delta": delta})
    yield ("agent_meta", {"steps": steps})


def _step_detail(
    tool: str,
    args: dict,
    observation: str,
    hits: list[dict],
    lang: str,
) -> str:
    if tool == "list_documents":
        try:
            docs = json.loads(observation)
            n = len(docs) if isinstance(docs, list) else 0
        except json.JSONDecodeError:
            n = 0
        return (
            f"Найдено документов: {n}"
            if lang != "en"
            else f"Documents found: {n}"
        )
    if tool == "search_documents":
        q = args.get("query") or ""
        n = len(hits)
        if lang != "en":
            return f"Запрос: «{q}» → фрагментов: {n}"
        return f"Query: “{q}” → fragments: {n}"
    return observation[:160]


def _chunk_text(text: str, size: int = 24) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
