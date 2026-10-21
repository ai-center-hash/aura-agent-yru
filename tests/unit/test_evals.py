"""test ของโครง eval: ความถูกต้องของ dataset, ตัวให้คะแนน, persona และโมเดลปลอม

(ไม่ได้รันโมเดลจริง — ส่วนนั้นอยู่ใน `tests/evals/run_evals.py`)
"""

from datetime import date, datetime

import pytest

from tests.evals.fake_model import ACTION_REFUSAL, EchoChatModel
from tests.evals.grading import (
    KNOWN_TOOLS,
    CaseResult,
    EvalCase,
    check_thresholds,
    grade,
    load_dataset,
    normalize,
    percentile,
    render_report,
    report_path,
    summarize,
)
from tests.evals.personas import EVAL_TODAY, PersonaClient, available_personas, load_persona

JWT = "eval.fixture.jwt"


def make_case(**overrides) -> EvalCase:
    base = {"id": "progress-99", "persona": "normal_with_gaps", "question": "ทดสอบ"}
    return EvalCase(**{**base, **overrides})


def make_result(case: EvalCase, **overrides) -> CaseResult:
    base = {
        "case": case,
        "answer": "คำตอบ",
        "tools_used": [],
        "ttft_ms": 100,
        "total_ms": 1000,
        "failures": [],
    }
    return CaseResult(**{**base, **overrides})


# ---- dataset ----


def test_dataset_loads_with_expected_shape():
    cases = load_dataset()

    assert len(cases) == 45
    assert len({case.id for case in cases}) == 45  # id ต้องไม่ซ้ำ


def test_dataset_category_counts_match_the_plan():
    counts: dict[str, int] = {}
    for case in load_dataset():
        counts[case.category] = counts.get(case.category, 0) + 1

    assert counts == {"progress": 12, "search": 11, "recommend": 9, "history": 7, "safety": 6}


def test_dataset_uses_existing_personas():
    personas = set(available_personas())

    assert personas == {
        "normal_with_gaps",
        "transfer_with_gaps",
        "completed_all",
        "realistic_with_gaps",
    }
    for case in load_dataset():
        assert case.persona in personas, case.id


def test_dataset_uses_known_tool_names():
    for case in load_dataset():
        for allowed in case.expect_tools_any or []:
            for name in allowed:
                assert name in KNOWN_TOOLS, f"{case.id}: ไม่รู้จัก tool {name}"


def test_every_case_checks_something():
    for case in load_dataset():
        checks = case.must_contain or case.must_contain_any or case.must_not_contain
        assert checks or case.expect_tools_any is not None, case.id


def test_safety_cases_expect_no_tool_call():
    for case in load_dataset():
        if case.category == "safety":
            assert case.expect_tools_any == [[]], case.id


# ---- ให้คะแนน ----


def test_normalize_collapses_whitespace():
    assert normalize("  คุณยัง\n  ขาด  2 หมวด ") == "คุณยัง ขาด 2 หมวด"


def test_grade_passes_when_everything_matches():
    case = make_case(
        expect_tools_any=[["get_my_progress"]],
        must_contain=["จิตอาสา"],
        must_contain_any=["8", "14"],
        must_not_contain=["ครบทุกหมวดแล้ว"],
    )

    assert grade(case, "คุณยังขาดจิตอาสาอีก 8 ชั่วโมงครับ", ["get_my_progress"]) == []


def test_grade_reports_wrong_tool():
    case = make_case(expect_tools_any=[["get_my_progress"]])

    failures = grade(case, "ตอบแล้ว", ["search_activities"])

    assert len(failures) == 1
    assert failures[0].startswith("tool:")


def test_grade_accepts_any_allowed_tool_set():
    case = make_case(expect_tools_any=[[], ["get_my_progress"]])

    assert grade(case, "ตอบแล้ว", []) == []
    assert grade(case, "ตอบแล้ว", ["get_my_progress"]) == []
    assert grade(case, "ตอบแล้ว", ["search_activities"]) != []


def test_grade_ignores_tool_order_and_duplicates():
    case = make_case(expect_tools_any=[["get_my_progress", "search_activities"]])

    assert (
        grade(case, "ตอบแล้ว", ["search_activities", "get_my_progress", "search_activities"]) == []
    )


def test_grade_skips_tool_check_when_not_specified():
    case = make_case(must_contain=["ครับ"])

    assert grade(case, "ได้ครับ", ["search_activities"]) == []


def test_grade_reports_missing_and_forbidden_text():
    case = make_case(must_contain=["จิตอาสา"], must_not_contain=["ลงทะเบียนให้แล้ว"])

    failures = grade(case, "ลงทะเบียนให้แล้วครับ", [])

    assert len(failures) == 2
    assert all(failure.startswith("ข้อความ:") for failure in failures)


def test_grade_requires_one_of_must_contain_any():
    case = make_case(must_contain_any=["8", "14"])

    assert grade(case, "ขาดอีก 8 ชั่วโมง", []) == []
    assert grade(case, "ขาดอีกหลายชั่วโมง", []) != []


def test_grade_rejects_empty_answer():
    case = make_case(must_contain=["จิตอาสา"])

    assert grade(case, "   ", []) == ["ข้อความ: ไม่มีคำตอบ"]


# ---- สรุปผลและเกณฑ์ ----


@pytest.mark.parametrize(
    ("values", "fraction", "expected"),
    [([], 0.5, None), ([5], 0.5, 5), ([1, 2, 3, 4, 5], 0.5, 3), ([1, 2, 3, 4, 5], 0.95, 5)],
)
def test_percentile(values, fraction, expected):
    assert percentile(values, fraction) == expected


def test_summarize_counts_errors_as_failures():
    passing = make_result(make_case(id="progress-01"))
    failing = make_result(make_case(id="search-01"), failures=["tool: ผิด"])
    broken = make_result(
        make_case(id="search-02"),
        failures=["error: LLM_UNAVAILABLE"],
        error="LLM_UNAVAILABLE: ConnectError",
    )

    summary = summarize([passing, failing, broken])

    assert summary.total == 3
    assert summary.errors == 1
    assert summary.tool_accuracy == pytest.approx(1 / 3)  # error นับเป็นไม่ผ่าน
    assert summary.per_category == {"progress": (1, 1), "search": (0, 2)}


def test_summarize_latency_and_safety():
    results = [
        make_result(make_case(id="safety-01"), ttft_ms=100, total_ms=1000),
        make_result(make_case(id="safety-02"), ttft_ms=300, total_ms=3000),
    ]

    summary = summarize(results)

    assert summary.safety_accuracy == 1.0
    assert summary.ttft_p50_ms == 200  # ค่ากลางของ 100 กับ 300
    assert summary.total_p95_ms == 2900


def test_thresholds_pass_for_a_good_run():
    results = [make_result(make_case(id=f"progress-{index:02d}")) for index in range(10)]
    results.append(make_result(make_case(id="safety-01")))

    assert check_thresholds(summarize(results)) == []


def test_thresholds_flag_each_problem():
    results = [
        make_result(
            make_case(id="safety-01"),
            failures=["ข้อความ: ต้องมี 'เฉพาะ'"],
            ttft_ms=4000,
            total_ms=40000,
        ),
        make_result(
            make_case(id="progress-01"), failures=["tool: ผิด"], ttft_ms=9000, total_ms=40000
        ),
    ]

    problems = " | ".join(check_thresholds(summarize(results)))

    assert "tool accuracy" in problems
    assert "fact accuracy" in problems
    assert "safety" in problems
    assert "TTFT p50" in problems
    assert "เวลาตอบรวม p50" in problems


# ---- รายงาน ----


def test_report_path_is_safe_for_model_names(tmp_path):
    path = report_path("qwen3.6:35b-a3b", datetime(2026, 10, 20, 9, 0), tmp_path)

    assert path.name == "2026-10-20_qwen3.6_35b-a3b.md"
    assert path.parent == tmp_path


def test_render_report_lists_failures_and_timings():
    failing = make_result(
        make_case(id="search-01", question="มีกิจกรรมอะไร"),
        answer="ไม่ทราบครับ",
        tools_used=["search_activities"],
        failures=["ข้อความ: ต้องมี 'จิตอาสา'"],
    )
    results = [make_result(make_case(id="progress-01")), failing]

    report = render_report(
        results, summarize(results), model="qwen3.6:35b-a3b", started_at=datetime(2026, 10, 20)
    )

    assert "# Eval · qwen3.6:35b-a3b" in report
    assert "## ข้อที่ไม่ผ่าน (1)" in report
    assert "search-01" in report
    assert "ต้องมี 'จิตอาสา'" in report
    assert "ไม่ทราบครับ" in report
    assert "| progress-01 |" in report


def test_render_report_when_all_pass():
    results = [make_result(make_case(id="progress-01"))]

    report = render_report(
        results, summarize(results), model="m", started_at=datetime(2026, 10, 20), note="ทดสอบ"
    )

    assert "ผ่านทุกเกณฑ์" in report
    assert "## ข้อที่ไม่ผ่าน (0)" in report
    assert "> ทดสอบ" in report


# ---- persona ----


@pytest.mark.parametrize(
    "name", ["normal_with_gaps", "transfer_with_gaps", "completed_all", "realistic_with_gaps"]
)
def test_personas_load(name):
    persona = load_persona(name)

    assert persona.user_id > 0
    assert persona.schedules
    assert persona.registrations
    assert persona.summary.categories


def test_persona_summaries_are_different_students():
    ids = {load_persona(name).user_id for name in available_personas()}

    assert len(ids) == len(available_personas())


def test_missing_persona_raises():
    with pytest.raises(FileNotFoundError):
        load_persona("ไม่มี persona นี้")


async def test_persona_client_filters_open_phase():
    client = PersonaClient(load_persona("normal_with_gaps"))

    rows = await client.get_schedules(JWT, phase="open")

    assert {row.id for row in rows} == {101, 102, 104, 105, 106, 107, 108}
    assert all(row.is_registration_open for row in rows)


async def test_persona_client_filters_upcoming_phase():
    client = PersonaClient(load_persona("normal_with_gaps"))

    rows = await client.get_schedules(JWT, phase="upcoming")

    assert {row.id for row in rows} == {103}


async def test_persona_client_filters_by_date_and_search():
    client = PersonaClient(load_persona("normal_with_gaps"))

    december = await client.get_schedules(JWT, date_from=date(2026, 12, 1))
    found = await client.get_schedules(JWT, search="เดินวิ่ง")

    assert {row.id for row in december} == {103, 108}
    assert [row.id for row in found] == [107]


async def test_persona_client_only_returns_its_own_registrations():
    persona = load_persona("normal_with_gaps")
    client = PersonaClient(persona)

    assert await client.get_registrations(JWT, persona.user_id)
    assert await client.get_registrations(JWT, 999999) == []


async def test_persona_client_today_is_the_fixture_reference_date():
    client = PersonaClient(load_persona("normal_with_gaps"))

    assert client.today == EVAL_TODAY == date(2026, 10, 20)


# ---- โมเดลปลอมของ --self-test ----


@pytest.mark.parametrize(
    ("question", "expected_tool"),
    [
        ("ผมยังขาดกิจกรรมหมวดไหนบ้าง", "get_my_progress"),
        ("มีกิจกรรมอะไรเปิดรับสมัครอยู่บ้าง", "search_activities"),
        ("แนะนำกิจกรรมให้ครบหน่อย", "recommend_activities"),
        ("ผมลงทะเบียนกิจกรรมอะไรไว้บ้าง", "get_my_registrations"),
    ],
)
async def test_echo_model_picks_the_matching_tool(question, expected_tool):
    from langchain_core.messages import HumanMessage

    message = await EchoChatModel().ainvoke([HumanMessage(question)])

    assert [call["name"] for call in message.tool_calls] == [expected_tool]


@pytest.mark.parametrize(
    "question",
    [
        "ลงทะเบียนกิจกรรมจิตอาสาให้ผมหน่อย",
        "ยกเลิกการลงทะเบียนกิจกรรมจิตอาสาให้ผมด้วย",
    ],
)
async def test_echo_model_refuses_to_act_on_behalf_of_the_user(question):
    from langchain_core.messages import HumanMessage

    message = await EchoChatModel().ainvoke([HumanMessage(question)])

    assert message.tool_calls == []
    assert message.content == ACTION_REFUSAL


async def test_echo_model_echoes_tool_output():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    messages = [
        HumanMessage("ผมขาดหมวดไหน"),
        AIMessage("", tool_calls=[{"name": "get_my_progress", "args": {}, "id": "1"}]),
        ToolMessage("[ความคืบหน้า] ขาดจิตอาสา 8 ชม.", tool_call_id="1"),
    ]

    message = await EchoChatModel().ainvoke(messages)

    assert "[ความคืบหน้า] ขาดจิตอาสา 8 ชม." in message.content
    assert message.tool_calls == []


# ---- ตัวตรวจว่าโมเดลกุข้อมูลหรือไม่ ----


def facts_of(name: str = "normal_with_gaps"):
    from tests.evals.data_audit import collect_facts

    return collect_facts(load_persona(name))


def test_collect_facts_reads_titles_dates_and_years():
    facts = facts_of()

    assert "จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย ครั้งที่ 2" in facts.titles
    assert (5, 11, 2569) in facts.date_keys  # วันจัดของรอบ 101
    assert (20, 10, 2569) in facts.date_keys  # วันนี้ของ eval
    assert facts.years == {2565, 2568, 2569}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("จัด 28 ต.ค. 2569", [(28, 10, 2569)]),
        ("จัด 5 พฤศจิกายน 2569", [(5, 11, 2569)]),
        ("14 ก.พ. 2569 ถึง 15 ก.พ. 2569", [(14, 2, 2569), (15, 2, 2569)]),
        ("ไม่มีวันที่", []),
    ],
)
def test_find_dates(text, expected):
    from tests.evals.data_audit import find_dates

    assert find_dates(text) == expected


def test_audit_flags_fabricated_date_and_missing_tool():
    from tests.evals.data_audit import audit_answer

    audit = audit_answer(
        case_id="history-01",
        category="history",
        persona_name="normal_with_gaps",
        answer="ค่ายพัฒนาทักษะชีวิต วันจัด 15 ก.พ. 2570",
        tools_used=[],
        facts=facts_of(),
    )

    assert audit.fabricated is True
    assert audit.unknown_dates == ["15/2/2570"]
    assert audit.unknown_years == [2570]
    assert audit.tool_missing is True
    assert audit.clean is False


def test_audit_accepts_grounded_answer():
    from tests.evals.data_audit import audit_answer

    audit = audit_answer(
        case_id="history-01",
        category="history",
        persona_name="normal_with_gaps",
        answer="จิตอาสาพัฒนาชุมชนรอบมหาวิทยาลัย ครั้งที่ 2 วันจัด 5 พ.ย. 2569",
        tools_used=["get_my_registrations"],
        facts=facts_of(),
    )

    assert audit.clean is True
    assert audit.known_titles
    assert audit.unknown_dates == []


def test_progress_answers_do_not_require_a_tool_call():
    """ความคืบหน้าอยู่ใน system prompt แล้ว จึงตอบได้โดยไม่เรียกเครื่องมือ"""
    from tests.evals.data_audit import audit_answer

    audit = audit_answer(
        case_id="progress-01",
        category="progress",
        persona_name="normal_with_gaps",
        answer="คุณยังขาดจิตอาสา 2 กิจกรรม 8 ชม.",
        tools_used=[],
        facts=facts_of(),
    )

    assert audit.tool_missing is False
    assert audit.clean is True


def test_render_audit_lists_fabricated_cases():
    from tests.evals.data_audit import AnswerAudit, render_audit

    audits = [
        AnswerAudit(
            case_id="search-01",
            category="search",
            persona="normal_with_gaps",
            tools_used=[],
            unknown_dates=["15/2/2570"],
            unknown_years=[2570],
        ),
        AnswerAudit(
            case_id="search-02",
            category="search",
            persona="normal_with_gaps",
            tools_used=["search_activities"],
            known_titles=["กีฬาสีสัมพันธ์"],
        ),
    ]

    report = render_audit({"model": "m", "started_at": "2026-10-20T10:00:00"}, audits)

    assert "กุข้อมูล (วันที่หรือปีที่ไม่มีในข้อมูล): **1**" in report
    assert "## คำตอบที่พบการกุข้อมูล" in report
    assert "search-01" in report
