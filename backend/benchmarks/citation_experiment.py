"""Citation experiment: повышение citation coverage локальной 3B-модели.

Сравнивает три варианта system prompt на dev-наборе (a1–a12, n1–n5) через
один и тот же llama.cpp Q4_K_M и одинаковый retrieval/context:

  V0 — baseline: текущий SYSTEM_PROMPTS из app/core/rag.py (точная копия);
  V1 — baseline + few-shot пример формата ответа с [1]/[2] (вымышленный
       домен «командировки», факты НЕ из evaluation-набора);
  V2 — V1 + явное требование цитировать каждое фактическое утверждение.

Production app/core/rag.py НЕ меняется. Retrieval/context строится один раз
на вопрос — идентично для всех вариантов. Оценка — те же детерминированные
check_* функции, что в answer_eval (переиспользование, без дублирования).

Latency в этом окружении невалидна (глубокий swap) — сохраняется в артефакт,
но НЕ используется для выбора prompt.

Запуск (из backend/):
    .venv/bin/python benchmarks/citation_experiment.py                # dev, V0/V1/V2
    .venv/bin/python benchmarks/citation_experiment.py --limit 2      # smoke
    .venv/bin/python benchmarks/citation_experiment.py --heldout      # V0+кандидат на v2
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE))

from app.core import rag  # noqa: E402
from benchmarks.answer_eval import (  # noqa: E402
    check_citation_precision_recall,
    check_citations,
    check_citation_target,
    check_must_contain,
    check_refusal,
    check_repetition,
    check_should_contain,
)

# --- варианты промпта -------------------------------------------------------

# Few-shot пример: вымышленный домен (командировки), факты не из evaluation-набора.
FEWSHOT_RU = """
Пример ответа с цитатами:
«Суточные в командировке составляют 5000 руб. в день [1]. Оформление поездки выполняется через личный кабинет [2].»
Каждое фактическое утверждение из примера сопровождено ссылкой на фрагмент.
"""
FEWSHOT_EN = """
Example of a cited answer:
"The per-diem rate is 5,000 RUB per day [1]. Trip booking is done via the self-service portal [2]."
Every factual statement in this example carries a citation to its fragment.
"""

EXPLICIT_RU = """
Обязательные требования к цитированию:
- Каждое фактическое утверждение в ответе должно сопровождаться ссылкой [n] на использованный фрагмент.
- Не включай утверждение, если ни один фрагмент его не подтверждает.
- Если документов недостаточно для ответа — используй штатное поведение: честно скажи, что информации нет.
- Ответ, содержащий фактические утверждения без ссылок [n], считается неполным.
"""
EXPLICIT_EN = """
Mandatory citation rules:
- Every factual statement in the answer must carry a citation [n] to the fragment it came from.
- Do not include a statement that no fragment confirms.
- If the documents are insufficient, use the standard behaviour: honestly say the information is missing.
- An answer with factual statements but no [n] citations is considered incomplete.
"""


def build_variants() -> dict[str, dict[str, str]]:
    """V0 — точная копия production prompt; V1/V2 — надстройки. rag.py не меняется."""
    variants: dict[str, dict[str, str]] = {"V0": dict(rag.SYSTEM_PROMPTS)}
    for lang, fewshot, explicit in (("ru", FEWSHOT_RU, EXPLICIT_RU), ("en", FEWSHOT_EN, EXPLICIT_EN)):
        base = rag.SYSTEM_PROMPTS[lang]
        variants.setdefault("V1", {})[lang] = base + fewshot
        variants.setdefault("V2", {})[lang] = base + fewshot + explicit
    return variants


# --- загрузка dev/heldout ---------------------------------------------------

def load_dataset(name: str) -> tuple[list[dict], list[dict]]:
    if "v2" in name.lower():
        blob = json.loads((BASE / "eval" / name).read_text(encoding="utf-8"))
        answers = [q for q in blob["queries"] if not q.get("expected_abstention")]
        negatives = [q for q in blob["queries"] if q.get("expected_abstention")]
    else:
        blob = json.loads((BASE / "eval" / name).read_text(encoding="utf-8"))
        answers, negatives = blob["answer_queries"], blob["negative_queries"]
    for q in (*answers, *negatives):
        q.setdefault("doc", None)
    return answers, negatives


# --- оценка (переиспользование check_* из answer_eval) ------------------------

def evaluate_answer(row_items: dict, answer: str, hits: list[dict]) -> dict:
    must = row_items.get("must_contain") or []
    should = row_items.get("should_contain") or []
    out = {
        "correctness": check_must_contain(answer, must) if must else None,
        "completeness": check_should_contain(answer, should) if should else None,
        "citations": check_citations(answer, n_sources=len(hits)),
        "citation_pr": check_citation_precision_recall(answer, hits, row_items.get("doc")),
        "repetition": check_repetition(answer),
        "finish_reason": None,
    }
    if must:
        out["citation_target"] = check_citation_target([h["filename"] for h in hits], row_items.get("doc"))
    return out


def refusal_eval(answer: str, item: dict) -> dict:
    return check_refusal(answer, item.get("forbidden_terms") or [])


def summarize_variant(rows: list[dict]) -> dict:
    """Агрегаты с явными знаменателями (как в answer_eval)."""
    ans = [r for r in rows if r["kind"] == "answer" and not r.get("gen_error")]
    neg = [r for r in rows if r["kind"] == "refusal" and not r.get("gen_error")]

    def rate(subset, flag):
        return round(sum(1 for r in subset if flag(r)) / len(subset), 4) if subset else None

    precisions = [r["eval"]["citation_pr"]["precision"] for r in ans
                  if r["eval"]["citation_pr"]["applicable"]]
    tps = [r["server_tpot_ms"] for r in ans if r.get("server_tpot_ms")]
    return {
        "n_answer": len(ans),
        "correctness_rate": rate(ans, lambda r: r["eval"]["correctness"]["passed"]),
        "n_incorrect": sum(1 for r in ans if not r["eval"]["correctness"]["passed"]),
        "citation_validity_rate": rate(ans, lambda r: r["eval"]["citations"]["valid"]),
        "citation_precision_mean": round(statistics.fmean(precisions), 4) if precisions else None,
        "citation_precision_n": len(precisions),
        "citation_coverage_rate": rate(ans, lambda r: r["eval"]["citation_pr"]["recall"] == 1.0),
        "n_answers_with_citations": sum(1 for r in ans if r["eval"]["citation_pr"]["n_citations"] > 0),
        "n_answers_without_citations": sum(1 for r in ans if r["eval"]["citation_pr"]["n_citations"] == 0),
        "correct_answer_without_citation_count": sum(
            1 for r in ans if r["eval"]["correctness"]["passed"]
            and r["eval"]["citation_pr"]["n_citations"] == 0),
        "n_refusal": len(neg),
        "refusal_pass_rate": rate(neg, lambda r: r["eval"]["refusal"]["passed"]),
        "n_repetition_suspected": sum(1 for r in rows
                                      if r["eval"].get("repetition", {}).get("repetition_suspected")),
        "out_tokens_mean": round(statistics.fmean([r["out_tokens"] for r in ans if r.get("out_tokens")]), 1)
        if any(r.get("out_tokens") for r in ans) else None,
        "tpot_ms_p50": round(statistics.median(tps), 1) if tps else None,
    }


def select_candidate(summary: dict[str, dict], order: tuple[str, ...] = ("V0", "V1", "V2"),
                     quality_eps: float = 0.0) -> tuple[str, str]:
    """Выбор кандидата по критерию из ТЗ (порядок проверок важен):
    1) correctness не хуже baseline (V0);
    2) refusal_pass_rate не хуже baseline;
    3) citation validity не хуже baseline (нет формальных/неверных цитат сверх baseline);
    4) только среди прошедших — максимум citation coverage;
    5) при равенстве coverage — минимальный вариант по порядку (V0 приоритетен).
    Возвращает (variant_id, причина) или ("V0", "ни один вариант не улучшил").
    """
    base = summary["V0"]
    passed: list[tuple[str, float]] = []
    reasons: dict[str, str] = {}
    for vid in order[1:]:
        if vid not in summary:
            continue  # тесты/частичные прогоны могут передавать не все варианты
        s = summary[vid]
        if (s["correctness_rate"] or 0) < (base["correctness_rate"] or 0) - quality_eps:
            reasons[vid] = f"correctness деградировал: {s['correctness_rate']} < {base['correctness_rate']}"
            continue
        if (s["refusal_pass_rate"] or 0) < (base["refusal_pass_rate"] or 0) - quality_eps:
            reasons[vid] = f"refusal деградировал: {s['refusal_pass_rate']} < {base['refusal_pass_rate']}"
            continue
        if (s["citation_validity_rate"] or 0) < (base["citation_validity_rate"] or 0) - quality_eps:
            reasons[vid] = f"citation validity деградировал: {s['citation_validity_rate']} < {base['citation_validity_rate']}"
            continue
        cov = s["n_answers_with_citations"]
        passed.append((vid, float(cov)))
    # Равный с baseline coverage — НЕ улучшение: кандидат обязан строго превосходить.
    better = [(vid, cov) for vid, cov in passed
              if cov > base["n_answers_with_citations"]]
    if not better:
        if reasons:
            detail = "; ".join(f"{vid}: {reasons[vid]}" for vid in order[1:] if vid in reasons)
            return "V0", f"ни один вариант не улучшил citation coverage ({detail})"
        return "V0", "ни один вариант не улучшил citation coverage без деградации качества"
    best_cov = max(cov for _, cov in better)
    best = [vid for vid, cov in better if cov == best_cov]
    winner = min(best, key=order.index)
    others = ", ".join(
        f"{vid}: {reasons[vid]}" if vid in reasons
        else f"{vid}: coverage={summary[vid]['n_answers_with_citations']}"
        for vid in order[1:] if vid in summary)
    return (winner,
            f"coverage {best_cov}/{base['n_answers_with_citations']} без деградации "
            f"correctness/refusal/validity; {others}")


# --- генерация ----------------------------------------------------------------

def run_variant(vid: str, prompts: dict[str, str], items: list[dict], kinds: list[str],
                srv, args) -> list[dict]:
    rows: list[dict] = []
    for item, kind in zip(items, kinds):
        hits = srv_retrieve(item["q"], args.top_k)
        # Подстановка retrieval-контекста в шаблон варианта: prompt = шаблон + CONTEXT.
        # Контекст одинаков для всех вариантов (retrieval детерминирован на вопрос).
        from app.core.rag import build_context

        system = (prompts["ru"] if item.get("lang", "ru") == "ru" else prompts["en"]).replace(
            "{context}", build_context(hits))
        t0 = time.perf_counter()
        try:
            r = srv.complete(system, item["q"], args.max_tokens)
            answer, err = r["answer"], None
        except Exception as exc:  # noqa: BLE001
            answer, err = "", f"{type(exc).__name__}: {exc}"[:160]
        wall = round((time.perf_counter() - t0) * 1000, 1)
        if kind == "answer":
            ev = evaluate_answer(item, answer, hits)
        else:
            ev = {"refusal": refusal_eval(answer, item)}
        rows.append({
            "variant": vid, "question_id": item["id"], "kind": kind,
            "question": item["q"], "lang": item.get("lang", "ru"),
            "retrieved_docs": [h["filename"] for h in hits],
            "answer": answer, "answer_chars": len(answer),
            "gen_error": err, "wall_ms": wall,
            "out_tokens": r.get("completion_tokens") if not err else None,
            "server_tpot_ms": r.get("server_tpot_ms"),
            "server_prompt_ms": r.get("server_prompt_ms"),
            "finish_reason": r.get("finish_reason") if not err else None,
            "eval": ev,
        })
        tag = "ok" if not err else f"FAIL {err[:50]}"
        print(f"  [{vid}][{item['id']}] {len(answer)}ch {r.get('completion_tokens')}tok "
              f"{wall}ms {tag}", flush=True)
    return rows


def srv_retrieve(query: str, top_k: int) -> list[dict]:
    from app.core import rag

    return rag.retrieve(query=query, top_k=top_k, workspace_id="default")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dataset", default="golden_answers.json", help="dev-набор (v1)")
    p.add_argument("--variants", nargs="+", default=["V0", "V1", "V2"], choices=["V0", "V1", "V2"])
    p.add_argument("--limit", type=int, default=0, help="ограничить число вопросов (smoke)")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--ngl", type=int, default=0)
    p.add_argument("--ctx", type=int, default=4096)
    p.add_argument("--port", type=int, default=8127)
    p.add_argument("--heldout", action="store_true",
                   help="финальный прогон: V0 + выбранный кандидат на held-out v2 (без выбора по нему)")
    p.add_argument("--label", default="")
    p.add_argument("--no-json", action="store_true")
    args = p.parse_args()

    variants = build_variants()
    from benchmarks.local_llamacpp import LlamaServer, MODELS_DIR

    gguf = MODELS_DIR / "Llama-3.2-3B-Instruct-Q4_K_M.gguf"

    if args.heldout:
        # Выбор кандидата берётся из последнего dev-артефакта (не по held-out).
        import glob

        runs = sorted(glob.glob(str(BASE.parent / "results" / "*citation_experiment*.json")))
        if not runs:
            sys.exit("Нет dev-артефакта citation_experiment — сначала выполните dev-прогон")
        dev = json.loads(Path(runs[-1]).read_text(encoding="utf-8"))
        chosen = dev["chosen_variant"]
        print(f"Held-out прогон: V0 + кандидат {chosen} (выбор из {Path(runs[-1]).name})")
        answers, negatives = load_dataset("golden_answers_v2.json")
        all_variants = {v: variants[v] for v in ("V0", chosen)}
        run_rows, summaries = [], {}
        with LlamaServer(gguf, ngl=args.ngl, ctx=args.ctx, port=args.port) as srv:
            srv.complete("You are helpful.", "Warm-up: say OK.", 8)
            for vid, prompts in all_variants.items():
                print(f"=== held-out {vid} ===")
                rows = run_variant(vid, prompts, answers + negatives,
                                   ["answer"] * len(answers) + ["refusal"] * len(negatives),
                                   srv, args)
                run_rows.extend(rows)
                summaries[vid] = summarize_variant(rows)
        _finish(dev_payload=None, summaries=summaries, rows=run_rows,
                variants={v: {"ru": prompts["ru"], "en": prompts["en"]}
                          for v, prompts in all_variants.items()},
                dataset="golden_answers_v2.json", chosen=chosen,
                args=args, heldout=True)
        return

    # Протокол: чистый индекс пересобирается с нуля (robustness/прошлые прогоны
    # могут оставить загрязнённый корпус — первый dev-прогон попал именно на него).
    from benchmarks.retrieval_eval import build_index

    print("Пересборка чистого индекса демо-пака…")
    build_index()
    answers, negatives = load_dataset(args.dataset)
    if args.limit:
        answers, negatives = answers[: args.limit], negatives[: args.limit]
    kinds = ["answer"] * len(answers) + ["refusal"] * len(negatives)
    items = answers + negatives
    print(f"Dev: {len(answers)} answer + {len(negatives)} refusal | варианты: {args.variants}")

    all_rows: list[dict] = []
    summaries: dict[str, dict] = {}
    with LlamaServer(gguf, ngl=args.ngl, ctx=args.ctx, port=args.port) as srv:
        srv.complete("You are helpful.", "Warm-up: say OK.", 8)
        for vid in args.variants:
            print(f"=== {vid} ===")
            rows = run_variant(vid, variants[vid], items, kinds, srv, args)
            all_rows.extend(rows)
            summaries[vid] = summarize_variant(rows)

    chosen, reason = select_candidate(summaries, tuple(args.variants))
    print(f"\nВыбранный вариант: {chosen} — {reason}")
    _finish(None, summaries, all_rows, variants, args.dataset, chosen, args,
            heldout=False, reason=reason)


def _finish(dev_payload, summaries, rows, variants, dataset, chosen, args,
            heldout: bool, reason: str = "") -> None:
    from benchmarks.metrics import command_line, git_commit, iso_utc, save_results

    if heldout:
        print(f"\n=== Held-out сравнение ({dataset}) — ПРЕДВАРИТЕЛЬНО, выборка мала ===")
    else:
        print("\n=== Сравнение вариантов (dev) ===")
    head = ("variant", "correct", "incorrect", "cited", "uncited",
            "cov%", "P_mean(P_n)", "refusal", "out_tok")
    print("{:<8} {:>8} {:>9} {:>6} {:>8} {:>6} {:>12} {:>8} {:>8}".format(*head))
    for vid, s in summaries.items():
        print("{:<8} {:>8} {:>9} {:>6} {:>8} {:>6} {:>12} {:>8} {:>8}".format(
            vid,
            f"{s['correctness_rate']:.0%}" if s["correctness_rate"] is not None else "—",
            s["n_incorrect"],
            s["n_answers_with_citations"],
            s["n_answers_without_citations"],
            f"{s['citation_coverage_rate']:.0%}" if s["citation_coverage_rate"] is not None else "—",
            f"{s['citation_precision_mean']} ({s['citation_precision_n']})",
            f"{s['refusal_pass_rate']:.0%}" if s["refusal_pass_rate"] is not None else "—",
            s["out_tokens_mean"] if s["out_tokens_mean"] is not None else "—",
        ))
    if not heldout:
        print(f"\nКандидат: {chosen} ({reason})")

    if not args.no_json:
        payload = {
            "benchmark": "citation_experiment",
            "date_utc": iso_utc(),
            "git_commit": git_commit(),
            "command": command_line(),
            "phase": "heldout" if heldout else "dev_selection",
            "dataset": dataset,
            "model": "meta-llama/Llama-3.2-3B-Instruct Q4_K_M (GGUF, bartowski)",
            "runtime": "llama.cpp b11826 (llama-server), CPU -ngl 0",
            "generation": {"max_tokens": args.max_tokens, "temperature": 0.2},
            "latency_note": "окружение в глубоком swap — latency/timings сохраняются, "
                            "но НЕ используются для выбора prompt и не характеризуют модель",
            "prompts": {vid: dict(prompts) for vid, prompts in variants.items()},
            "chosen_variant": chosen,
            "selection_reason": reason,
            "summaries": summaries,
            "rows": rows,
        }
        label = f"_{args.label}" if args.label else ""
        name = f"citation_experiment{'_heldout' if heldout else ''}{label}"
        paths = save_results(payload, name)
        print(f"\nСохранено: {paths}")


if __name__ == "__main__":
    main()
