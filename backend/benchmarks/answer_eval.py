"""Answer-level evaluation of the RAG pipeline: deterministic checks + LLM-as-judge.

Разделяет метрики генерации от метрик retrieval:

Детерминированные (без LLM, воспроизводимы бит-в-бит):
  correctness        — все группы эталонных фактов (must_contain) присутствуют в ответе
  citation_validity  — каждая ссылка [n] указывает на существующий источник (1..top_k)
  citation_target    — топ-1 источник выдачи — целевой документ вопроса
  refusal_correct    — для negative-вопросов: нет выдуманных фактов (forbidden_terms)
                       и нет ссылок [n] при отсутствии релевантного контекста

LLM-as-judge (документированная субъективная оценка, 1-5):
  faithfulness — факты ответа подтверждаются контекстом
  relevance    — ответ отвечает на заданный вопрос
  citations    — ссылки корректно указывают на источники

Запуск (из backend/, индекс демо-пака строится автоматически):
    .venv/bin/python benchmarks/answer_eval.py --model zai:glm-5.3-flash --judge zai:glm-4.5-flash
    .venv/bin/python benchmarks/answer_eval.py --model mock --no-judge   # пайплайн без сети
    .venv/bin/python benchmarks/answer_eval.py --answers-from ../../results/<local_answers>.json \
        --judge zai:glm-5.3-flash   # оценить готовые ответы локальной модели

Результаты: results/<ts>_answer_eval.json + .csv (по-вопросные ряды для ручного разбора).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

EVAL_DIR = BASE / "data" / "eval"
os.environ.setdefault("UPLOAD_DIR", str(EVAL_DIR / "uploads"))
os.environ.setdefault("CHROMA_DIR", str(EVAL_DIR / "chroma"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{EVAL_DIR / 'app.db'}")

from benchmarks.metrics import command_line, git_commit, iso_utc, save_results  # noqa: E402

CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default="zai:glm-5.3-flash", help="модель-ответчик (id провайдера проекта)")
    p.add_argument("--judge", default="zai:glm-4.5-flash", help="модель-судья")
    p.add_argument("--no-judge", action="store_true", help="только детерминированные проверки")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--answers-from", default=None,
                   help="JSON с готовыми ответами (results/…_local_answers.json) вместо живого вызова --model")
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    return p.parse_args()


# ------------------------------------------------- deterministic checks --

def normalize(text: str) -> str:
    """Нижний регистр, ё→е, NFC, склейка разрядов чисел («2 990» → «2990»)."""
    text = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    text = re.sub(r"(?<=\d)[ \u00a0\u202f]+(?=\d)", "", text)  # разделители тысяч
    return re.sub(r"\s+", " ", text)


def check_must_contain(answer: str, groups: list[list[str]]) -> dict:
    """Все группы должны быть представлены хотя бы одним синонимом из группы."""
    norm = normalize(answer)
    missing: list[str] = []
    for group in groups:
        if not any(normalize(variant) in norm for variant in group):
            missing.append(group[0])
    return {"passed": not missing, "missing": missing}


def check_citations(answer: str, n_sources: int) -> dict:
    """Каждая [n]-ссылка должна указывать на существующий источник; нужна ≥1 ссылка."""
    cites = [int(m) for m in CITATION_RE.findall(answer)]
    invalid = [n for n in cites if not (1 <= n <= n_sources)]
    return {
        "n_citations": len(cites),
        "valid": bool(cites) and not invalid,
        "invalid_refs": sorted(set(invalid)),
    }


def check_citation_precision_recall(answer: str, hits: list[dict],
                                    target_doc: str | None) -> dict:
    """Детерминированные citation precision/recall (для вопросов с эталоном).

    Номер [n] маппится на hits[n-1]['filename'] — порядок цитат совпадает с
    порядком фрагментов в контексте (см. rag.build_context).
    precision — доля всех [n]-ссылок, ведущих на целевой документ;
    recall (coverage) — есть ли хотя бы одна ссылка на целевой документ (0/1).
    Не применимо (нет эталона, контекста или ссылок) — None, из агрегатов исключается.
    """
    cites = [int(m) for m in CITATION_RE.findall(answer)]
    if not target_doc or not hits or not cites:
        return {"applicable": False, "precision": None, "recall": None,
                "n_citations": len(cites), "n_to_target": 0}
    valid = [n for n in cites if 1 <= n <= len(hits)]
    to_target = [n for n in valid if hits[n - 1].get("filename") == target_doc]
    return {
        "applicable": True,
        "precision": round(len(to_target) / len(cites), 4),
        "recall": 1.0 if to_target else 0.0,
        "n_citations": len(cites),
        "n_to_target": len(to_target),
    }


def check_refusal(answer: str, forbidden_terms: list[str]) -> dict:
    """Честный отказ. Основной критерий — нет выдуманных фактов (fact leak).
    Ссылки [n] на «вот что есть в документах вместо» легитимны, поэтому
    strict-вариант (дополнительно без цитат) — отдельное поле, не провал."""
    norm = normalize(answer)
    leaked = [t for t in forbidden_terms if normalize(t) in norm]
    cites = CITATION_RE.findall(answer)
    refusal_markers_ru = ["не нашёл", "не нашла", "не найдено", "не удалось найти", "нет информации",
                          "нет данных", "отсутствуют", "не содержится", "не упоминается"]
    refusal_markers_en = ["couldn't find", "could not find", "no information",
                          "not mentioned", "don't have", "do not have", "no relevant"]
    has_marker = any(m in norm for m in refusal_markers_ru + refusal_markers_en)
    return {
        "no_fact_leak": not leaked,
        "leaked_terms": leaked,
        "no_citations_without_context": not cites,
        "explicit_refusal_marker": has_marker,
        "passed": not leaked,           # основная метрика: не выдумывает
        "passed_strict": not leaked and not cites,
    }


def check_citation_target(retrieved_docs: list[str], target_doc: str | None) -> dict:
    """Топ-1 источник — целевой документ (только для вопросов с эталоном)."""
    if target_doc is None:
        return {"applicable": False, "passed": True}
    return {"applicable": True, "passed": bool(retrieved_docs) and retrieved_docs[0] == target_doc}


def check_should_contain(answer: str, should: list[str]) -> dict:
    """Полнота ответа (мягкая): доля необязательных элементов, попавших в ответ."""
    if not should:
        return {"applicable": False, "coverage": None}
    norm = normalize(answer)
    found = sum(1 for t in should if normalize(t) in norm)
    return {"applicable": True, "coverage": round(found / len(should), 4)}


def check_repetition(answer: str) -> dict:
    """Эвристика зацикливания: доля уникальных 4-грамм среди всех 4-грамм.
    У связного текста она высокая (>0.7); у зацикленного падает (<0.35)."""
    words = normalize(answer).split()
    if len(words) < 12:
        return {"applicable": False, "unique_4gram_ratio": None, "repetition_suspected": False}
    grams = [tuple(words[i:i + 4]) for i in range(len(words) - 3)]
    ratio = round(len(set(grams)) / len(grams), 3)
    return {"applicable": True, "unique_4gram_ratio": ratio, "repetition_suspected": ratio < 0.35}


def judge_agreement(judged_rows: list[dict]) -> dict:
    """Согласованность judge с детерминированными проверками (sanity, не истина).

    Сравниваются бинарные вердикты: judge_citations >= 4 против citations.valid.
    """
    pairs = []
    for r in judged_rows:
        if r.get("judge") and r["judge"].get("citations") and r.get("citations"):
            pairs.append((r["judge"]["citations"] >= 4, r["citations"]["valid"]))
    if not pairs:
        return {"n_pairs": 0, "agreement": None}
    agree = sum(1 for a, b in pairs if a == b)
    return {"n_pairs": len(pairs), "agreement": round(agree / len(pairs), 4)}


# --------------------------------------------------------------- judge --

JUDGE_SYSTEM_RU = (
    "Ты — строгий оценщик качества RAG-ответов. Даны вопрос, контекст (фрагменты "
    "документов, предоставленные модели) и ответ модели. Оцени ответ по шкале 1-5:\n"
    "- faithfulness: все факты ответа подтверждаются контекстом (5 — полностью, 1 — выдуманы)\n"
    "- relevance: ответ отвечает именно на заданный вопрос\n"
    "- citations: ссылки [n] присутствуют и корректно указывают на источники (нет ссылок — 1)\n"
    'Верни ТОЛЬКО JSON без пояснений: {"faithfulness": N, "relevance": N, '
    '"citations": N, "issues": "кратко о проблемах или пустая строка"}'
)


def parse_judge_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None

    def clamp(v):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None
        if v == 0:
            return None  # 0 = «не оценено», не искажаем агрегат единицей
        return max(1, min(5, v))

    out = {axis: clamp(data.get(axis)) for axis in ("faithfulness", "relevance", "citations")}
    out["issues"] = str(data.get("issues", "")).strip()
    return out if any(out[a] for a in ("faithfulness", "relevance", "citations")) else None


async def judge_one(judge_provider, question: str, context: str, answer: str) -> dict | None:
    user = f"Вопрос: {question}\n\nКонтекст:\n{context[:3000]}\n\nОтвет модели: {answer[:1500]}"
    from app.llm.base import ChatMessage

    chunks: list[str] = []
    try:
        async for delta in judge_provider.stream(
            JUDGE_SYSTEM_RU, [ChatMessage(role="user", content=user)], "ru"
        ):
            chunks.append(delta)
    except Exception:  # noqa: BLE001
        return None
    return parse_judge_json("".join(chunks))


# ----------------------------------------------------------------- run --

def ensure_index() -> None:
    from app.core import vectorstore

    if vectorstore._collection().count() == 0:
        print("Индекс пуст — строим демо-пак в data/eval…")
        from benchmarks.retrieval_eval import build_index

        build_index()


async def main_async(args) -> None:
    from app.core import rag
    from app.llm.registry import get_provider

    ensure_index()

    golden = json.loads((BASE / "eval" / "golden_answers.json").read_text(encoding="utf-8"))
    answer_qs = golden["answer_queries"][: args.limit] if args.limit else golden["answer_queries"]
    negative_qs = golden["negative_queries"][: args.limit] if args.limit else golden["negative_queries"]

    answer_provider = None if args.answers_from else get_provider(args.model)
    judge_provider = None if args.no_judge else get_provider(args.judge)

    ready_answers: dict[str, dict] = {}
    if args.answers_from:
        blob = json.loads(Path(args.answers_from).read_text(encoding="utf-8"))
        for row in blob.get("rows", []):
            ready_answers[row["question_id"]] = row
        print(f"Готовые ответы: {len(ready_answers)} из {args.answers_from}")

    rows: list[dict] = []
    for kind, items in (("answer", answer_qs), ("refusal", negative_qs)):
        for item in items:
            qid = item["id"]
            print(f"[{kind}] {item['q'][:60]}")
            if kind == "answer":
                hits = rag.retrieve(query=item["q"], top_k=args.top_k)
                context = rag.build_context(hits)
                system = rag.build_system_prompt(hits, item.get("lang", "ru"))
                retrieved_docs = [h["filename"] for h in hits]
            else:
                hits = rag.retrieve(query=item["q"], top_k=args.top_k)
                context = rag.build_context(hits)
                system = rag.build_system_prompt(hits, item.get("lang", "ru"))
                retrieved_docs = [h["filename"] for h in hits]

            if args.answers_from:
                ready = ready_answers.get(qid)
                answer = (ready or {}).get("answer") or ""
                gen_error = None if ready else "нет готового ответа для вопроса"
            else:
                from app.llm.base import ChatMessage

                t0 = time.perf_counter()
                buf: list[str] = []
                gen_error = None
                try:
                    async for delta in answer_provider.stream(
                        system, [ChatMessage(role="user", content=item["q"])], item.get("lang", "ru")
                    ):
                        buf.append(delta)
                except Exception as exc:  # noqa: BLE001
                    gen_error = str(exc)[:200]
                answer = "".join(buf).strip()
                gen_ms = round((time.perf_counter() - t0) * 1000, 1)

            row = {
                "question_id": qid,
                "kind": kind,
                "category": item.get("category"),
                "question": item["q"],
                "lang": item.get("lang", "ru"),
                "retrieved_docs": retrieved_docs,
                "answer": answer,
                "answer_chars": len(answer),
                "gen_error": gen_error,
                # finish_reason доступен только для готовых ответов (llama.cpp):
                # length = генерация оборвана лимитом токенов, stop — завершена.
                "finish_reason": (ready_answers.get(qid) or {}).get("finish_reason")
                if args.answers_from else None,
            }
            row["repetition"] = check_repetition(answer)
            if kind == "answer":
                row["correctness"] = check_must_contain(answer, item["must_contain"])
                row["completeness"] = check_should_contain(answer, item.get("should_contain", []))
                row["citations"] = check_citations(answer, n_sources=len(hits))
                row["citation_target"] = check_citation_target(retrieved_docs, item.get("doc"))
                row["citation_pr"] = check_citation_precision_recall(answer, hits, item.get("doc"))
            else:
                row["refusal"] = check_refusal(answer, item["forbidden_terms"])

            if judge_provider and not gen_error:
                row["judge"] = await judge_one(judge_provider, item["q"], context, answer)
                await asyncio.sleep(0.3)  # бережно к API
            else:
                row["judge"] = None
            rows.append(row)

    # ---------------------------------------------------------- aggregates
    def rate(subset: list[dict], flag) -> float:
        return round(sum(1 for r in subset if flag(r)) / len(subset), 4) if subset else None

    answer_rows = [r for r in rows if r["kind"] == "answer" and not r["gen_error"]]
    refusal_rows = [r for r in rows if r["kind"] == "refusal" and not r["gen_error"]]
    judged = [r for r in rows if r.get("judge")]

    def judge_avg(axis: str) -> float | None:
        vals = [r["judge"][axis] for r in judged if r["judge"] and r["judge"].get(axis)]
        return round(sum(vals) / len(vals), 2) if vals else None

    aggregates = {
        "n_answer_questions": len(answer_rows),
        "correctness_rate": rate(answer_rows, lambda r: r["correctness"]["passed"]),
        "citation_validity_rate": rate(answer_rows, lambda r: r["citations"]["valid"]),
        "citation_target_top1_rate": rate(answer_rows, lambda r: r["citation_target"]["passed"]),
        "citation_precision_mean": (
            round(sum(r["citation_pr"]["precision"] for r in answer_rows
                      if r["citation_pr"]["applicable"]) /
                  max(sum(1 for r in answer_rows if r["citation_pr"]["applicable"]), 1), 4)
        ),
        "citation_recall_rate": rate(answer_rows, lambda r: r["citation_pr"]["recall"] == 1.0),
        "completeness_coverage_mean": (
            round(sum(r["completeness"]["coverage"] for r in answer_rows
                      if r["completeness"]["applicable"]) /
                  max(sum(1 for r in answer_rows if r["completeness"]["applicable"]), 1), 4)
        ),
        "n_truncated_finish_length": sum(1 for r in rows if r.get("finish_reason") == "length"),
        "n_repetition_suspected": sum(1 for r in rows if r["repetition"].get("repetition_suspected")),
        "n_refusal_questions": len(refusal_rows),
        "refusal_no_hallucination_rate": rate(refusal_rows, lambda r: r["refusal"]["passed"]),
        "refusal_strict_no_citations_rate": rate(refusal_rows, lambda r: r["refusal"]["passed_strict"]),
        "n_judged": len(judged),
        "judge_faithfulness_avg": judge_avg("faithfulness"),
        "judge_relevance_avg": judge_avg("relevance"),
        "judge_citations_avg": judge_avg("citations"),
        "judge_vs_citations_agreement": judge_agreement(judged)["agreement"],
        "judge_agreement_n_pairs": judge_agreement(judged)["n_pairs"],
        "judge_failed_or_skipped": sum(1 for r in rows if r["judge"] is None),
    }

    print("\n=== Агрегаты ===")
    for k, v in aggregates.items():
        print(f"  {k}: {v}")

    weak = [r for r in answer_rows if not r["correctness"]["passed"] or not r["citations"]["valid"]]
    if weak:
        print("\nСпорные примеры (для ручного разбора):")
        for r in weak:
            print(f"  - {r['question_id']}: missing={r['correctness']['missing']} "
                  f"invalid_refs={r['citations']['invalid_refs']}")

    if not args.no_json:
        payload = {
            "benchmark": "answer_eval",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "answer_model": args.model if not args.answers_from else f"from:{args.answers_from}",
            "judge_model": args.judge if judge_provider else None,
            "judge_note": "LLM-as-judge субъективен; same-family судья склонен к завышению. "
                          "Детерминированные проверки — первичны.",
            "deterministic_definitions": {
                "correctness": "все группы must_contain (хотя бы один синоним из группы) в ответе",
                "citation_validity": "все [n] в диапазоне 1..top_k и их ≥1",
                "citation_target": "топ-1 retrieval-документ == целевой документ",
                "refusal_no_hallucination": "нет forbidden_terms в ответе (не выдумывает факты)",
                "refusal_strict": "дополнительно нет [n]-ссылок",
            },
            "aggregates": aggregates,
            "rows": rows,
        }
        label = f"_{args.label}" if args.label else ""
        paths = save_results(payload, f"answer_eval{label}")
        print(f"\nСохранено: {paths}")


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
