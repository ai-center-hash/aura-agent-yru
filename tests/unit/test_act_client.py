"""test ของ ActClient: parse fixture, แปลง error, retry และ cache

mock HTTP ด้วย respx ทุกเคส ไม่มีการยิง Activity API จริง
"""

from datetime import date

import httpx
import pytest

from aura_agent.data import (
    TokenExpired,
    UpstreamRejected,
    UpstreamSchemaError,
    UpstreamUnavailable,
)
from aura_agent.data.act_client import REGISTRATIONS_PATH, SCHEDULES_PATH, SUMMARY_PATH

from .conftest import BASE_URL, JWT, OTHER_JWT

SUMMARY_URL = f"{BASE_URL}{SUMMARY_PATH}"
SCHEDULES_URL = f"{BASE_URL}{SCHEDULES_PATH}"
REGISTRATIONS_URL = f"{BASE_URL}{REGISTRATIONS_PATH}"


# ---- parse fixture ----


async def test_summary_fixture_parses(client, respx_mock, load_fixture):
    route = respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    summary = await client.get_my_summary(JWT)

    assert summary.user.id == 119231
    assert summary.user.student_status == "normal"
    assert summary.user.faculty == "คณะวิทยาศาสตร์และเทคโนโลยี"
    assert summary.frame is not None
    assert summary.frame.start_date == date(2022, 6, 1)
    assert summary.summary.total_activities == 5
    assert summary.summary.total_hours == 27.5

    categories = {category.category_id: category for category in summary.categories}
    assert set(categories) == {1, 2, 5, 7}

    volunteer = categories[2].frame_items[0]
    assert volunteer.is_passed is False
    assert volunteer.count == 1
    assert volunteer.total_hours == 4.0
    assert volunteer.requirement.normal_hour_min == 12
    assert volunteer.requirement.transfer_hour_min == 6
    assert volunteer.activities[0].attendance_hours == 4.0

    sport = categories[5].frame_items[0]
    assert sport.count == 0
    assert sport.activities == []

    assert route.calls.last.request.headers["authorization"] == f"Bearer {JWT}"
    assert route.calls.last.request.headers["accept"] == "application/json"


async def test_summary_ignores_fields_we_do_not_use(client, respx_mock, load_fixture):
    """ฟิลด์อย่าง email ต้องไม่ถูกเก็บไว้ (ลดข้อมูลส่วนบุคคลที่ค้างในหน่วยความจำ)"""
    respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    summary = await client.get_my_summary(JWT)

    assert not hasattr(summary.user, "email")
    assert "email" not in summary.user.model_dump()


async def test_schedules_fixture_parses(client, respx_mock, load_fixture):
    route = respx_mock.get(SCHEDULES_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("schedules.json"))
    )

    schedules = await client.get_schedules(JWT)

    assert len(schedules) == 9
    by_id = {schedule.id: schedule for schedule in schedules}

    assert by_id[101].category_id == 2
    assert by_id[101].type_label == "กิจกรรมบังคับ"
    assert by_id[101].duration_hours == 6
    assert by_id[101].available_slots == 40
    assert by_id[101].is_registration_open is True
    assert by_id[101].activity is not None
    assert by_id[101].activity.organizer_name == "กองพัฒนานักศึกษา"

    assert by_id[102].is_full is True
    assert by_id[88].is_registration_open is False

    # target_* ที่ส่ง null มาต้องกลายเป็น list ว่าง ไม่ใช่ None
    assert by_id[101].target_faculties == []
    assert by_id[101].target_student_year_prefix == []
    assert by_id[101].target_student_status is None

    # รหัสปีที่ส่งมาเป็นตัวเลขต้องถูกแปลงเป็น string
    assert by_id[108].target_student_year_prefix == ["65"]
    assert by_id[104].target_faculties == ["คณะครุศาสตร์"]
    assert by_id[105].target_student_status == "transfer"

    assert route.called


async def test_registrations_fixture_parses(client, respx_mock, load_fixture):
    respx_mock.get(REGISTRATIONS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("registrations.json"))
    )

    registrations = await client.get_registrations(JWT, 119231)

    assert len(registrations) == 6
    assert [registration.status for registration in registrations] == [1, 4, 5, 5, 6, 5]

    pending = registrations[0]
    assert pending.checkin_at is None
    assert pending.attendance_minutes is None
    assert pending.activity is not None
    assert pending.activity.title.startswith("จิตอาสา")
    assert pending.schedule is not None
    assert pending.schedule.activity_start_date is not None
    assert pending.schedule.activity_start_date.year == 2026

    completed = registrations[2]
    assert completed.attendance_minutes == 690
    assert completed.checkout_at is not None

    # ไม่เก็บชื่อหรือรหัสนักศึกษาที่ติดมากับแต่ละแถว
    assert not hasattr(pending, "user")
    assert not hasattr(pending, "user_name")
    assert not hasattr(pending, "user_code")


# ---- query parameters ----


async def test_schedules_sends_expected_params(client, respx_mock, load_fixture):
    route = respx_mock.get(SCHEDULES_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("schedules.json"))
    )

    await client.get_schedules(
        JWT,
        phase="open",
        date_from=date(2026, 10, 20),
        date_to=date(2026, 12, 31),
        search="  จิตอาสา  ",
    )

    params = route.calls.last.request.url.params
    assert params["paginate"] == "false"
    assert params["is_published"] == "true"
    assert params["sort_by"] == "registration_start_date"
    assert params["sort_order"] == "asc"
    assert params["registration_phase"] == "open"
    assert params["activity_date_from"] == "2026-10-20"
    assert params["activity_date_to"] == "2026-12-31"
    assert params["search"] == "จิตอาสา"


async def test_schedules_skips_empty_search(client, respx_mock, load_fixture):
    route = respx_mock.get(SCHEDULES_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("schedules.json"))
    )

    await client.get_schedules(JWT, search="   ")

    params = route.calls.last.request.url.params
    assert "search" not in params
    assert "registration_phase" not in params


async def test_registrations_filters_by_user_id(client, respx_mock, load_fixture):
    route = respx_mock.get(REGISTRATIONS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("registrations.json"))
    )

    await client.get_registrations(JWT, 119231)

    params = route.calls.last.request.url.params
    assert params["user_id"] == "119231"
    assert params["paginate"] == "false"
    assert params["sort_by"] == "registered_at"
    assert params["sort_order"] == "desc"


# ---- error ----


async def test_401_raises_token_expired_without_retry(client, respx_mock):
    route = respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(401, json={"message": "Unauthenticated."})
    )

    with pytest.raises(TokenExpired) as error:
        await client.get_my_summary(JWT)

    assert error.value.code == "TOKEN_EXPIRED"
    assert route.call_count == 1


@pytest.mark.parametrize("status_code", [403, 404, 422])
async def test_other_4xx_raises_rejected_without_retry(client, respx_mock, status_code):
    route = respx_mock.get(SUMMARY_URL).mock(return_value=httpx.Response(status_code))

    with pytest.raises(UpstreamRejected) as error:
        await client.get_my_summary(JWT)

    assert error.value.code == "UPSTREAM_UNAVAILABLE"
    assert route.call_count == 1


async def test_timeout_retries_once_then_raises(client, respx_mock):
    route = respx_mock.get(SUMMARY_URL).mock(side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(UpstreamUnavailable):
        await client.get_my_summary(JWT)

    assert route.call_count == 2


async def test_connect_error_retries_once_then_raises(client, respx_mock):
    route = respx_mock.get(SUMMARY_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(UpstreamUnavailable):
        await client.get_my_summary(JWT)

    assert route.call_count == 2


async def test_server_error_twice_raises_unavailable(client, respx_mock):
    route = respx_mock.get(SUMMARY_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(UpstreamUnavailable):
        await client.get_my_summary(JWT)

    assert route.call_count == 2


async def test_server_error_then_success(client, respx_mock, load_fixture):
    route = respx_mock.get(SUMMARY_URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json=load_fixture("summary_me.json")),
        ]
    )

    summary = await client.get_my_summary(JWT)

    assert summary.user.id == 119231
    assert route.call_count == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"success": True},
        {"data": []},
        {"data": {"frame": {"id": 3, "title": "กรอบ"}}},
    ],
)
async def test_bad_summary_payload_raises_schema_error(client, respx_mock, payload):
    respx_mock.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=payload))

    with pytest.raises(UpstreamSchemaError) as error:
        await client.get_my_summary(JWT)

    assert error.value.code == "INTERNAL"


async def test_non_json_response_raises_schema_error(client, respx_mock):
    respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, text="<html>502 Bad Gateway</html>")
    )

    with pytest.raises(UpstreamSchemaError):
        await client.get_my_summary(JWT)


async def test_schema_error_keeps_personal_data_out_of_message(client, respx_mock):
    respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"user": {"id": "ไม่ใช่ตัวเลข", "name": "นายทดสอบ ระบบ"}}},
        )
    )

    with pytest.raises(UpstreamSchemaError) as error:
        await client.get_my_summary(JWT)

    message = str(error.value)
    assert "user.id" in message
    assert "นายทดสอบ ระบบ" not in message
    assert "ไม่ใช่ตัวเลข" not in message


async def test_schedules_with_object_data_raises_schema_error(client, respx_mock):
    respx_mock.get(SCHEDULES_URL).mock(return_value=httpx.Response(200, json={"data": {"id": 1}}))

    with pytest.raises(UpstreamSchemaError):
        await client.get_schedules(JWT)


# ---- cache ----


async def test_second_call_within_ttl_uses_cache(client, respx_mock, load_fixture):
    route = respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    first = await client.get_my_summary(JWT)
    second = await client.get_my_summary(JWT)

    assert route.call_count == 1
    assert first.user.id == second.user.id
    assert first is not second  # parse ใหม่ทุกครั้ง ผู้เรียกแก้ object แล้วไม่กระทบ cache


async def test_cache_expires_after_ttl(client, respx_mock, clock, load_fixture):
    route = respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    await client.get_my_summary(JWT)
    clock.advance(119)
    await client.get_my_summary(JWT)
    assert route.call_count == 1

    clock.advance(2)
    await client.get_my_summary(JWT)
    assert route.call_count == 2


async def test_registrations_cache_ttl_is_shorter(client, respx_mock, clock, load_fixture):
    route = respx_mock.get(REGISTRATIONS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("registrations.json"))
    )

    await client.get_registrations(JWT, 119231)
    clock.advance(61)
    await client.get_registrations(JWT, 119231)

    assert route.call_count == 2


async def test_different_jwt_does_not_share_cache(client, respx_mock, load_fixture):
    route = respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    await client.get_my_summary(JWT)
    await client.get_my_summary(OTHER_JWT)

    assert route.call_count == 2


async def test_different_params_do_not_share_cache(client, respx_mock, load_fixture):
    route = respx_mock.get(SCHEDULES_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("schedules.json"))
    )

    await client.get_schedules(JWT, phase="open")
    await client.get_schedules(JWT, phase="upcoming")
    await client.get_schedules(JWT, phase="open")

    assert route.call_count == 2


async def test_failed_call_is_not_cached(client, respx_mock, load_fixture):
    route = respx_mock.get(SUMMARY_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json=load_fixture("summary_me.json")),
        ]
    )

    with pytest.raises(UpstreamUnavailable):
        await client.get_my_summary(JWT)

    summary = await client.get_my_summary(JWT)
    assert summary.user.id == 119231
    assert route.call_count == 3


# ---- health check ----


async def test_ping_true_when_api_answers(client, respx_mock):
    route = respx_mock.get(SCHEDULES_URL).mock(return_value=httpx.Response(200, json={"data": []}))

    assert await client.ping() is True
    assert "authorization" not in route.calls.last.request.headers


async def test_ping_true_on_4xx(client, respx_mock):
    respx_mock.get(SCHEDULES_URL).mock(return_value=httpx.Response(401))

    assert await client.ping() is True


async def test_ping_false_on_server_error(client, respx_mock):
    respx_mock.get(SCHEDULES_URL).mock(return_value=httpx.Response(500))

    assert await client.ping() is False


async def test_ping_false_when_unreachable(client, respx_mock):
    respx_mock.get(SCHEDULES_URL).mock(side_effect=httpx.ConnectError("refused"))

    assert await client.ping() is False


# ---- โหมด passport: ยืนยันตัวตนกับ Passport แล้วเรียกเส้น public ----

from aura_agent.data import ActClient, NoActivityFrame, NotAStudent, PassportClient  # noqa: E402
from aura_agent.data.act_client import SUMMARY_USER_PATH, build_act_client  # noqa: E402
from aura_agent.data.passport import USERINFO_PATH  # noqa: E402

PASSPORT_URL = "https://passport.test"
USERINFO_URL = f"{PASSPORT_URL}{USERINFO_PATH}"
STUDENT_CODE = "406500001"
SUMMARY_USER_URL = f"{BASE_URL}{SUMMARY_USER_PATH}/{STUDENT_CODE}"
PASSPORT_INFO = {
    "sub": 10001,
    "username": STUDENT_CODE,
    "user_type": "student",
    "display_name": "นักศึกษาทดสอบ ระบบ",
    "org_unit_1_name": "คณะวิทยาศาสตร์และเทคโนโลยี",
}
NO_FRAME = {
    "success": True,
    "no_frame": True,
    "message": "ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้",
    "data": None,
}


@pytest.fixture
async def passport_client(cache):
    passport = PassportClient(PASSPORT_URL, timeout_s=1.0, cache=cache, retry_delay_s=0)
    async with ActClient(
        BASE_URL, timeout_s=1.0, cache=cache, passport=passport, retry_delay_s=0
    ) as act_client:
        yield act_client


def mock_passport(respx_mock):
    return respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=PASSPORT_INFO))


async def test_passport_mode_reads_summary_by_student_code(
    passport_client, respx_mock, load_fixture
):
    userinfo = mock_passport(respx_mock)
    summary_route = respx_mock.get(SUMMARY_USER_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    summary = await passport_client.get_my_summary(JWT)

    assert summary.user.id == 119231
    assert userinfo.calls.last.request.headers["authorization"] == f"Bearer {JWT}"
    # token ของ Passport ห้ามหลุดไปถึง Activity API
    assert "authorization" not in summary_route.calls.last.request.headers


async def test_passport_mode_never_forwards_token_to_activity_api(
    passport_client, respx_mock, load_fixture
):
    mock_passport(respx_mock)
    schedules = respx_mock.get(SCHEDULES_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("schedules.json"))
    )
    registrations = respx_mock.get(REGISTRATIONS_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("registrations.json"))
    )

    await passport_client.get_schedules(JWT, phase="open")
    await passport_client.get_registrations(JWT, 119231)

    assert "authorization" not in schedules.calls.last.request.headers
    assert "authorization" not in registrations.calls.last.request.headers


async def test_passport_mode_shares_public_schedule_cache(
    passport_client, respx_mock, load_fixture
):
    """ไม่ส่ง token แล้วข้อมูลรอบกิจกรรมเหมือนกันทุกคน จึงใช้ cache ร่วมกันได้"""
    route = respx_mock.get(SCHEDULES_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("schedules.json"))
    )

    await passport_client.get_schedules(JWT)
    await passport_client.get_schedules(OTHER_JWT)

    assert route.call_count == 1


async def test_no_frame_raises_with_identity(passport_client, respx_mock):
    mock_passport(respx_mock)
    respx_mock.get(SUMMARY_USER_URL).mock(return_value=httpx.Response(200, json=NO_FRAME))

    with pytest.raises(NoActivityFrame) as error:
        await passport_client.get_my_summary(JWT)

    assert error.value.code == "NO_FRAME"
    assert error.value.detail == "ไม่พบกรอบกิจกรรมที่ตรงกับกลุ่มของผู้ใช้"
    assert error.value.identity.student_code == STUDENT_CODE


async def test_staff_summary_raises_without_calling_activity_api(passport_client, respx_mock):
    """username ของบุคลากรไม่ใช่รหัสนักศึกษา ห้ามเอาไปค้น summary/user/{รหัส}"""
    staff = {**PASSPORT_INFO, "user_type": "staff", "username": "somchai.j"}
    respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=staff))
    summary_route = respx_mock.get(url__startswith=f"{BASE_URL}{SUMMARY_USER_PATH}/")

    with pytest.raises(NotAStudent) as error:
        await passport_client.get_my_summary(JWT)

    assert error.value.code == "NOT_STUDENT"
    assert error.value.identity.is_student is False
    assert summary_route.call_count == 0


async def test_staff_has_a_subject_for_chat_history(passport_client, respx_mock):
    staff = {**PASSPORT_INFO, "user_type": "staff", "sub": 77}
    respx_mock.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=staff))

    assert await passport_client.get_subject(JWT) == "passport:77"


async def test_no_frame_in_activity_me_mode_has_no_identity(client, respx_mock):
    respx_mock.get(SUMMARY_URL).mock(return_value=httpx.Response(200, json=NO_FRAME))

    with pytest.raises(NoActivityFrame) as error:
        await client.get_my_summary(JWT)

    assert error.value.identity is None


async def test_subject_in_passport_mode_comes_from_passport_only(passport_client, respx_mock):
    mock_passport(respx_mock)
    summary_route = respx_mock.get(SUMMARY_USER_URL)

    subject = await passport_client.get_subject(JWT)

    assert subject == "passport:10001"
    assert not summary_route.called  # ไม่ต้องมีกรอบกิจกรรมก็แยกประวัติแชทได้


async def test_subject_in_activity_me_mode_is_user_id(client, respx_mock, load_fixture):
    respx_mock.get(SUMMARY_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    assert await client.get_subject(JWT) == "119231"
    assert await client.get_identity(JWT) is None
    assert client.identity_mode == "activity_me"


async def test_student_code_never_appears_in_logs(
    passport_client, respx_mock, load_fixture, caplog
):
    mock_passport(respx_mock)
    respx_mock.get(SUMMARY_USER_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("summary_me.json"))
    )

    with caplog.at_level("DEBUG"):
        await passport_client.get_my_summary(JWT)

    assert STUDENT_CODE not in caplog.text
    assert JWT not in caplog.text
    assert "summary/user/{student}" in caplog.text


@pytest.mark.parametrize(
    ("mode", "expected"), [("passport", "passport"), ("activity_me", "activity_me")]
)
async def test_build_act_client_follows_identity_mode(mode, expected):
    from aura_agent.config import Settings

    settings = Settings(_env_file=None, service_key="x" * 32, identity_mode=mode)

    async with build_act_client(settings) as built:
        assert built.identity_mode == expected


async def test_schedule_schema_reads_target_student_codes(client, respx_mock, load_fixture):
    data = load_fixture("schedules.json")
    data["data"][0]["target_student_codes"] = [406500001, "406500002"]
    data["data"][1]["target_student_codes"] = None
    respx_mock.get(SCHEDULES_URL).mock(return_value=httpx.Response(200, json=data))

    schedules = await client.get_schedules(JWT)

    assert schedules[0].target_student_codes == ["406500001", "406500002"]
    assert schedules[1].target_student_codes == []
