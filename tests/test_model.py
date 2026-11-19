import pytest

from pivot_control import model


def test_parse_message_path():
    assert model.parse_message_path("$io_state.forward") == ("io_state", ["forward"])
    assert model.parse_message_path("$io_state:a.b") == ("io_state", ["a", "b"])
    assert model.parse_message_path("") is None
    assert model.parse_message_path(None) is None
    assert model.parse_message_path("io_state.forward") is None
    assert model.parse_message_path("$io_state") is None


def test_extract_and_coerce():
    data = {"a": {"b": [0, 5]}}
    assert model.extract_path_value(data, ["a", "b", "1"]) == 5
    assert model.extract_path_value(data, ["a", "x"]) is None
    assert model.coerce_bool(True) is True
    assert model.coerce_bool(0) is False
    assert model.coerce_bool("on") is True
    assert model.coerce_bool("0") is False
    assert model.coerce_bool("junk") is None
    assert model.coerce_number(None) is None


@pytest.mark.parametrize(
    "forward, reverse, expected",
    [
        (True, False, (model.RUNNING, model.FORWARD)),
        (False, True, (model.RUNNING, model.REVERSE)),
        (False, False, (model.STOPPED, None)),
        (True, True, (model.UNKNOWN, None)),
        (None, False, (model.UNKNOWN, None)),
    ],
)
def test_derive_state(forward, reverse, expected):
    assert model.derive_state(forward, reverse) == expected


def test_status_text():
    assert model.status_text(model.RUNNING, model.REVERSE, True) == "Running Reverse"
    assert model.status_text(model.STOPPED, None, True) == "Stopped"
    assert model.status_text(model.UNKNOWN, None, True) == "Unknown"
    assert model.status_text(None, None, False) == "No reading yet"


def test_scale_pressure():
    assert model.scale_pressure(4.0, 4, 20, 0, 87) == 0
    assert model.scale_pressure(20.0, 4, 20, 0, 87) == 87
    assert model.scale_pressure(12.0, 4, 20, 0, 87) == pytest.approx(43.5)
    assert model.scale_pressure(3.5, 4, 20, 0, 87) == 0  # just under: the minimum
    assert model.scale_pressure(0.2, 4, 20, 0, 87) is None  # dead loop
    assert model.scale_pressure(None, 4, 20, 0, 87) is None


def test_angle_and_heading():
    assert model.normalise_angle(370) == 10
    assert model.normalise_angle(-90) == 270
    assert model.normalise_angle("x") is None
    assert model.heading_text(0) == "0° N"
    assert model.heading_text(93.4) == "93° E"
    assert model.heading_text(350) == "350° N"
    assert model.heading_text(None) is None


def test_start_request():
    params, duration = model.start_request(
        "reverse", 40, model.END_AT_ANGLE, 180, None, default_speed=50, max_hours=0
    )
    assert params == {
        "direction": "reverse",
        "speed_percent": 40.0,
        "stop_angle_deg": 180.0,
    }
    assert duration is None

    params, duration = model.start_request(
        None, None, model.END_AFTER_TIME, None, 2.5, default_speed=60, max_hours=0
    )
    assert params == {
        "direction": "forward",
        "speed_percent": 60.0,
        "stop_angle_deg": None,
    }
    assert duration == 9000

    params, duration = model.start_request(
        "forward", 100, None, None, None, default_speed=50, max_hours=0
    )
    assert duration is None and params["stop_angle_deg"] is None


@pytest.mark.parametrize(
    "args",
    [
        ("sideways", 50, model.END_UNTIL_STOPPED, None, None),
        ("forward", 0, model.END_UNTIL_STOPPED, None, None),
        ("forward", 101, model.END_UNTIL_STOPPED, None, None),
        ("forward", 50, model.END_AT_ANGLE, None, None),
        ("forward", 50, model.END_AT_ANGLE, 400, None),
        ("forward", 50, model.END_AFTER_TIME, None, 0),
        ("forward", 50, model.END_AFTER_TIME, None, 30),  # over the 24 h max
    ],
)
def test_start_request_rejects(args):
    with pytest.raises(ValueError):
        model.start_request(*args, default_speed=50, max_hours=24)


def test_build_command_shape():
    cmd = model.build_command(
        "start",
        "run",
        "pivot_control_1",
        params={"direction": "forward"},
        duration_s=None,
        ts=5,
    )
    assert set(cmd) == {
        "command",
        "target",
        "duration_s",
        "params",
        "request_id",
        "app_key",
        "app",
        "ts",
    }
    assert (
        cmd["app"] == "pivot_control"
        and cmd["ts"] == 5
        and len(cmd["request_id"]) == 36
    )


def test_schedules_roundtrip():
    schedules = model.normalise_schedules(None, 50)
    assert [s["slot"] for s in schedules] == [1, 2, 3, 4]
    s = schedules[0]
    s = model.apply_schedule_edit(s, "enabled", True)
    assert model.schedule_problem(s) == "no start time"
    # 2026-11-20 06:00 in Brisbane (UTC+10) = 2026-11-19 20:00 UTC
    start = 1795118400000
    s = model.apply_schedule_edit(s, "start", start)
    s = model.apply_schedule_edit(s, "direction", "reverse")
    s = model.apply_schedule_edit(s, "speed", 70)
    s = model.apply_schedule_edit(s, "end", model.END_AFTER_TIME)
    assert model.schedule_problem(s) == "no run time"
    s = model.apply_schedule_edit(s, "hours", 12)
    assert (
        model.schedule_summary(s, "Australia/Brisbane", now=0)
        == "Fri 20 Nov 06:00, Reverse 70 %, 12 h"
    )
    assert model.schedule_summary(s, "Australia/Brisbane", now=start + 1).endswith(
        "(past)"
    )

    edge = model.schedule_for_edge(s, "Australia/Brisbane", max_hours=10)
    assert edge == {
        "slot": 1,
        "enabled": True,
        "start_ts": start,
        "start_local": "2026-11-20T06:00:00+10:00",
        "direction": "reverse",
        "speed_percent": 70.0,
        "stop_angle_deg": None,
        "duration_s": 36000,  # capped at max run hours
    }

    with pytest.raises(ValueError):
        model.apply_schedule_edit(s, "speed", 0)
    with pytest.raises(ValueError):
        model.apply_schedule_edit(s, "direction", "up")


def test_incomplete_schedule_is_sent_disabled():
    s = model.apply_schedule_edit(model.empty_schedule(2, 50), "enabled", True)
    assert model.schedule_for_edge(s, "Australia/Brisbane", 0)["enabled"] is False
    assert model.schedule_summary(s, "Australia/Brisbane") == "Not set: no start time"


def test_settings_payload():
    payload = model.settings_payload(
        targets={"run": "run", "forward": "forward", "reverse": "reverse"},
        cycle_s=60,
        default_speed=50,
        max_run_hours=0,
        tz_name="Australia/Brisbane",
        schedules=model.normalise_schedules([], 50),
        ts=1,
    )
    assert payload["app"] == "pivot_control" and payload["schema"] == 1
    assert payload["max_run_s"] is None
    assert len(payload["schedules"]) == 4
    assert all(not s["enabled"] for s in payload["schedules"])
