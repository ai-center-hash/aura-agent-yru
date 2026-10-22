"""รัน eval แล้วเขียนรายงาน

    python -m uv run python tests/evals/run_evals.py --model qwen3.6:35b-a3b
    python -m uv run python tests/evals/run_evals.py --self-test   # ตรวจว่าโครง eval ทำงาน

Activity API ใช้ fixture ของ persona · LLM ใช้ตัวจริงบน Ollama (temperature 0 เพื่อให้ผลนิ่ง)
เรียก graph ตรงๆ ไม่ผ่าน HTTP แต่ใช้ตัวแปล stream ชุดเดียวกับ SSE จึงวัด TTFT ได้เหมือนที่ผู้ใช้เจอ
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):  # รันเป็น script: ให้ import tests.evals.* ได้
    sys.path.insert(0, str(Path(__file__).parents[2]))

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from aura_agent import clock
from aura_agent.agent import build_graph, run_config, set_llm, state_serializer
from aura_agent.agent.errors import AgentError, LLMUnavailable
from aura_agent.api.sse import StreamTranslator
from aura_agent.config import get_settings
from aura_agent.data import ActApiError, set_act_client
from tests.evals.fake_model import EchoChatModel
from tests.evals.grading import (
    REPORT_DIR,
    CaseResult,
    EvalCase,
    check_thresholds,
    grade,
    load_dataset,
    render_report,
    report_path,
    summarize,
)
from tests.evals.personas import EVAL_JWT, EVAL_TODAY, PersonaClient, load_persona

SELF_TEST_NOTE = (
    "รันด้วย `--self-test` (โมเดลปลอมที่ตอบด้วยผลของ tool) "
    "ใช้ตรวจว่าโครง eval และ dataset สอดคล้องกับ fixture เท่านั้น ไม่ใช่การวัดคุณภาพโมเดล"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="รัน eval ของ AURA-AGENT")
    parser.add_argument("--model", default=None, help="ชื่อโมเดลบน Ollama (ค่าเริ่มต้นจาก .env)")
    parser.add_argument("--self-test", action="store_true", help="ใช้โมเดลปลอม ไม่ต้องมี Ollama")
    parser.add_argument("--ids", default=None, help="เฉพาะ id ที่ระบุ คั่นด้วย comma")
    parser.add_argument("--category", default=None, help="เฉพาะหมวด คั่นด้วย comma เช่น search,history")
    parser.add_argument("--limit", type=int, default=None, help="จำกัดจำนวนข้อ")
    parser.add_argument("--out", default=None, help="โฟลเดอร์เก็บรายงาน")
    parser.add_argument("--no-report", action="store_true", help="ไม่เขียนไฟล์รายงาน")
    parser.add_argument("--json", default=None, help="เขียนคำตอบทุกข้อเป็น JSON ไว้ตรวจสอบย้อนหลัง")
    return parser.parse_args(argv)


def select_cases(cases: list[EvalCase], args: argparse.Namespace) -> list[EvalCase]:
    chosen = cases
    if args.ids:
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        chosen = [case for case in chosen if case.id in wanted]
    if args.category:
        wanted = {item.strip() for item in args.category.split(",") if item.strip()}
        chosen = [case for case in chosen if case.category in wanted]
    if args.limit is not None:
        chosen = chosen[: args.limit]
    return chosen


def build_model(args: argparse.Namespace, model_name: str):
    if args.self_test:
        return EchoChatModel()

    from langchain_ollama import ChatOllama

    settings = get_settings()
    return ChatOllama(
        model=model_name,
        base_url=settings.ollama_base_url,
        temperature=0,  # eval ต้องได้ผลเดิมเมื่อรันซ้ำ
        num_ctx=settings.llm_num_ctx,
        reasoning=False,
    )


async def run_case(graph, case: EvalCase, client: PersonaClient) -> CaseResult:
    set_act_client(client)
    translator = StreamTranslator()
    parts: list[str] = []
    ttft_ms: int | None = None
    started = time.perf_counter()

    try:
        stream = graph.astream(
            {"messages": [HumanMessage(case.question)], "tool_rounds": 0},
            run_config(user_id=client.persona.subject, thread_id=case.id, jwt=EVAL_JWT),
            stream_mode=["updates", "messages"],
        )
        async for mode, payload in stream:
            for event in translator.handle(mode, payload):
                if event["event"] != "token":
                    continue
                if ttft_ms is None:
                    ttft_ms = _elapsed_ms(started)
                parts.append(json.loads(event["data"])["text"])

        for event in translator.flush():
            parts.append(json.loads(event["data"])["text"])

    except (ActApiError, AgentError) as error:
        return CaseResult(
            case=case,
            answer="".join(parts),
            tools_used=list(translator.tools_used),
            ttft_ms=ttft_ms,
            total_ms=_elapsed_ms(started),
            failures=[f"error: {error.code}"],
            error=f"{error.code}: {error.detail or type(error).__name__}",
        )

    answer = "".join(parts)
    return CaseResult(
        case=case,
        answer=answer,
        tools_used=list(translator.tools_used),
        ttft_ms=ttft_ms,
        total_ms=_elapsed_ms(started),
        failures=grade(case, answer, list(translator.tools_used)),
    )


async def run_all(cases: list[EvalCase], args: argparse.Namespace) -> list[CaseResult]:
    clients = {name: PersonaClient(load_persona(name)) for name in {case.persona for case in cases}}
    graph = build_graph(InMemorySaver(serde=state_serializer()))
    results: list[CaseResult] = []

    for index, case in enumerate(cases, start=1):
        result = await run_case(graph, case, clients[case.persona])
        results.append(result)
        print(
            f"[{index:>2}/{len(cases)}] {'✅' if result.passed else '❌'} {case.id:<13}"
            f" ttft={result.ttft_ms or '-':>6} รวม={result.total_ms:>6} ms"
            f" tools={','.join(result.tools_used) or '-'}"
        )
        for failure in result.failures:
            print(f"        └ {failure}")

        if isinstance(result.error, str) and result.error.startswith(LLMUnavailable.code):
            print(
                "\nเรียกโมเดลไม่ได้ — เปิด SSH tunnel ก่อน:"
                "\n  ssh -N -L 11434:localhost:11434 yruadmin@10.20.41.54"
            )
            break

    return results


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = parse_args(argv)
    model_name = "self-test-echo" if args.self_test else (args.model or get_settings().llm_model)

    # ตรึง "วันนี้" ให้ตรงกับวันอ้างอิงของ fixture ไม่งั้นผลจะเปลี่ยนไปตามวันที่รัน
    clock.today = lambda: EVAL_TODAY

    cases = select_cases(load_dataset(), args)
    if not cases:
        print("ไม่มีข้อที่ตรงกับเงื่อนไข")
        return 2

    print(f"โมเดล: {model_name} · จำนวนข้อ: {len(cases)} · วันอ้างอิง: {EVAL_TODAY}\n")
    started_at = datetime.now()
    set_llm(build_model(args, model_name))
    try:
        results = asyncio.run(run_all(cases, args))
    finally:
        set_llm(None)
        set_act_client(None)

    summary = summarize(results)
    problems = check_thresholds(summary)
    report = render_report(
        results,
        summary,
        model=model_name,
        started_at=started_at,
        note=SELF_TEST_NOTE if args.self_test else "",
    )

    print("\n" + "\n".join(report.splitlines()[2:10]))

    if args.json:
        dump_results(results, Path(args.json), model=model_name, started_at=started_at)
        print(f"\nคำตอบทุกข้อ (JSON): {args.json}")

    if not args.no_report:
        path = report_path(model_name, started_at, Path(args.out) if args.out else REPORT_DIR)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"\nรายงาน: {path}")

    if args.self_test:
        print("\n(โหมด self-test ไม่ตัดสินเกณฑ์ผ่าน/ไม่ผ่านของโมเดล)")
        return 0
    return 1 if problems else 0


def dump_results(
    results: list[CaseResult], path: Path, *, model: str, started_at: datetime
) -> None:
    """เก็บคำตอบทุกข้อไว้ตรวจสอบย้อนหลัง (เช่น ตรวจว่าโมเดลกุข้อมูลหรือไม่)"""
    payload = {
        "model": model,
        "started_at": started_at.isoformat(timespec="seconds"),
        "cases": [
            {
                "id": result.case.id,
                "category": result.case.category,
                "persona": result.case.persona,
                "question": result.case.question,
                "tools_used": result.tools_used,
                "answer": result.answer,
                "ttft_ms": result.ttft_ms,
                "total_ms": result.total_ms,
                "failures": result.failures,
                "error": result.error,
                "passed": result.passed,
            }
            for result in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


if __name__ == "__main__":
    sys.exit(main())
