"""Tools available to the document research agent."""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import rag
from app.db.models import Document

TOOL_SPECS = [
    {
        "name": "list_documents",
        "description": "List uploaded documents (id, filename, category, pages). Call when you need to know what files exist.",
        "args": {"category": "optional category filter"},
    },
    {
        "name": "search_documents",
        "description": "Semantic search over document chunks. Call before answering. Returns numbered fragments for citations [1], [2], …",
        "args": {"query": "search query in the user's language"},
    },
]


def tools_prompt_block() -> str:
    lines = ["Available tools (reply with a single JSON object):"]
    for t in TOOL_SPECS:
        lines.append(f"- {t['name']}: {t['description']} args={t['args']}")
    lines.append(
        'Tool call: {"tool":"search_documents","args":{"query":"..."}}\n'
        'Final answer: {"final":true,"answer":"markdown with [n] citations"}'
    )
    return "\n".join(lines)


def run_tool(
    name: str,
    args: dict,
    *,
    db: Session,
    category: str | None,
    document_ids: list[str] | None,
    top_k: int | None,
) -> tuple[str, list[dict]]:
    """Execute a tool. Returns (observation_text, retrieval_hits)."""
    args = args or {}
    if name == "list_documents":
        cat = args.get("category") or category
        q = select(Document).where(Document.status == "ready").order_by(Document.created_at.desc())
        if cat:
            q = q.where(Document.category == cat)
        docs = db.scalars(q.limit(50)).all()
        payload = [
            {
                "id": d.id,
                "filename": d.filename,
                "category": d.category,
                "page_count": d.page_count,
                "chunk_count": d.chunk_count,
            }
            for d in docs
        ]
        if not payload:
            return ("No ready documents in the library.", [])
        return (json.dumps(payload, ensure_ascii=False, indent=2), [])

    if name == "search_documents":
        query = (args.get("query") or "").strip()
        if not query:
            return ("Error: args.query is required.", [])
        hits = rag.retrieve(
            query=query,
            top_k=top_k,
            category=category,
            document_ids=document_ids,
        )
        if not hits:
            return ("No relevant fragments found for this query.", [])
        # Number fragments for citations in the final answer.
        text = rag.build_context(hits)
        return (text, hits)

    return (f"Unknown tool: {name}", [])
