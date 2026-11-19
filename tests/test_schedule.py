"""Schedules: validation, the progress estimate and the RPCs the Schedule widget calls."""

from types import SimpleNamespace as NS

import pytest
from conftest import APP_KEY, EXAMPLE_CONFIG, Harness
from pydoover.rpc import RPCError

from pivot_control import model

T0 = 1795100000000
MIN = 60_000
HOUR = 3_600_000


def step(**kw):
    base = {
        "direction": "forward",
        "wet": True,
        "speed_percent": 50,
        "end": "angle",
        "stop_angle_deg": 180,
        "run_hours": None,
        "delay_min": None,
    }
    base.update(kw)
    return base


def validate(payload, max_hours=0.0):
    return model.validate_schedule(
        payload, default_speed=40, simple_wet=False, max_hours=max_hours
    )


# --------------------------------------------------------------------------- validation


def test_detailed_schedule_validates_and_cleans():
    mode, steps = validate(
        {
            "mode": "detailed",
            "steps": [
                step(stop_angle_deg="360"),
                step(
                    direction="reverse",
                    wet=False,
                    end="time",
                    run_hours="1.5",
                    delay_min=15,
                ),
            ],
        }
    )
    assert mode == "detailed"
    assert steps == [
        {
            "direction": "forward",
            "wet": True,
            "speed_percent": 50.0,
            "end": "angle",
            "stop_angle_deg": 0.0,
            "run_hours": None,
            "delay_min": 0.0,
        },
        {
            "direction": "reverse",
            "wet": False,
            "speed_percent": 50.0,
            "end": "time",
            "stop_angle_deg": None,
            "run_hours": 1.5,
            "delay_min": 15.0,
        },
    ]


def test_every_bad_step_is_reported():
    with pytest.raises(model.ScheduleInvalid) as e:
        validate(
            {
                "mode": "detailed",
                "steps": [
                    step(),
                    step(stop_angle_deg=None),
                    step(speed_percent=0, stop_angle_deg=400),
                    step(end="time", run_hours=0),
                    step(end="time", run_hours=10, delay_min=-1),
                    step(end=None, direction=None),
                ],
            },
            max_hours=8,
        )
    assert e.value.errors == [
        "Step 2: choose a stop angle or a run time",
        "Step 3: speed must be 1–100 %",
        "Step 3: stop angle must be 0–360°",
        "Step 4: run time must be more than 0",
        "Step 5: run time can't be over the 8 h maximum",
        "Step 5: start delay can't be negative",
        "Step 6: choose a direction (forward or reverse)",
        "Step 6: choose a stop angle or a run time",
    ]


def test_simple_schedule_takes_speed_and_wet_from_config():
    mode, steps = validate(
        {
            "mode": "simple",
            "steps": [step(speed_percent=99, wet=True, stop_angle_deg=90)],
        }
    )
    assert mode == "simple"
    assert steps[0]["speed_percent"] == 40.0 and steps[0]["wet"] is False
    with pytest.raises(model.ScheduleInvalid) as e:
        validate({"mode": "simple", "steps": [{"direction": "reverse"}]})
    assert e.value.errors == [
        "Choose a stop angle or a run time"
    ]  # no "Step 1:" prefix


@pytest.mark.parametrize(
    "payload, error",
    [
        ({"mode": "weekly", "steps": [step()]}, "Unknown schedule type"),
        ({"mode": "detailed", "steps": []}, "Add at least one step"),
        (None, "Unknown schedule type"),
        (
            {"mode": "detailed", "steps": [step(speed_percent="fast")]},
            "speed must be 1–100 %",
        ),
    ],
)
def test_schedule_rejected(payload, error):
    with pytest.raises(model.ScheduleInvalid) as e:
        validate(payload)
    assert error in e.value.errors[0]


# --------------------------------------------------------------------------- progress


def schedule(*steps, now=T0):
    return model.new_schedule("detailed", list(steps), now=now)


def clean(**kw):
    return model.clean_step(model.normalise_step(step(**kw)))


def test_angle_steps_follow_the_arm_through_north():
    s = schedule(
        clean(stop_angle_deg=10), clean(direction="reverse", stop_angle_deg=300)
    )
    p, done = model.estimate_progress(s, None, 350.0, T0)
    assert p["step_index"] == 0 and p["remaining_deg"] == 20.0 and not done
    p, done = model.estimate_progress(s, p, 355.0, T0 + MIN)
    assert p["fraction"] == pytest.approx(0.25)
    p, done = model.estimate_progress(s, p, 353.0, T0 + 2 * MIN)  # GPS jitter backwards
    assert p["turned_deg"] == 3.0
    p, done = model.estimate_progress(s, p, 5.0, T0 + 3 * MIN)  # through North
    assert p["step_index"] == 0 and p["remaining_deg"] == 5.0
    p, done = model.estimate_progress(
        s, p, 9.5, T0 + 4 * MIN
    )  # within tolerance: next step
    assert p["step_index"] == 1 and p["start_angle_deg"] == 9.5 and not done
    # Reverse from 9.5° to 300°: 69.5° anticlockwise.
    p, done = model.estimate_progress(s, p, 330.0, T0 + 5 * MIN)
    assert p["remaining_deg"] == 30.0
    p, done = model.estimate_progress(s, p, 300.2, T0 + 6 * MIN)
    assert done


def test_time_steps_delay_and_pause():
    s = schedule(
        clean(end="time", run_hours=1, delay_min=10), clean(end="time", run_hours=0.5)
    )
    p, done = model.estimate_progress(s, None, None, T0 + 5 * MIN)
    assert p["waiting"] is True and p["remaining_s"] == 300
    p, done = model.estimate_progress(s, p, None, T0 + 40 * MIN)
    assert p["waiting"] is False and p["fraction"] == pytest.approx(0.5)

    # Paused for an hour: no progress while paused, and the hour doesn't count.
    s = model.pause_schedule(s, T0 + 40 * MIN)
    p2, _ = model.estimate_progress(s, p, None, T0 + 90 * MIN)
    assert p2["fraction"] == pytest.approx(0.5)
    s = model.resume_schedule(s, T0 + 100 * MIN)
    assert s["paused_ms"] == 60 * MIN and s["status"] == "running"
    p, done = model.estimate_progress(s, p, None, T0 + 110 * MIN)
    assert p["step_index"] == 0 and p["fraction"] == pytest.approx(2 / 3)
    # Step 1 ends at T0+130 min; step 2 runs 30 min from then.
    p, done = model.estimate_progress(s, p, None, T0 + 145 * MIN)
    assert p["step_index"] == 1 and p["fraction"] == pytest.approx(0.5)
    p, done = model.estimate_progress(s, p, None, T0 + 161 * MIN)
    assert done


def test_edge_reported_progress_wins():
    s = schedule(clean())
    assert model.edge_progress(None, s, T0) is None
    assert model.edge_progress({"schedule_id": "other", "step_index": 0}, s, T0) is None
    p, status = model.edge_progress(
        {
            "schedule_id": s["id"],
            "step_index": 0,
            "step_progress": 0.4,
            "status": "running",
        },
        s,
        T0,
    )
    assert p["estimated"] is False and p["fraction"] == 0.4 and status == "running"


def test_history_keeps_five_newest_first():
    history = []
    for n in range(7):
        history = model.push_history(history, dict(schedule(clean()), id=str(n)))
    assert [h["id"] for h in history] == ["6", "5", "4", "3", "2"]


def test_settings_translate_wet_into_the_supply_pump():
    s = schedule(clean(), clean(wet=False, end="time", run_hours=2, delay_min=5))
    link = model.supply_pump_link(
        "1", "pump_control_1", "pump_1", with_pivot=True, lead_s=0, run_on_s=0
    )
    payload = model.settings_payload(
        targets={},
        cycle_s=60,
        default_speed=50,
        max_run_hours=0,
        tz_name="Australia/Brisbane",
        schedule=s,
        history=[],
        supply_pump=link,
    )
    steps = payload["schedule"]["steps"]
    assert steps[0] == {
        "direction": "forward",
        "speed_percent": 50.0,
        "stop_angle_deg": 180.0,
        "duration_s": None,
        "delay_s": 0,
        "wet": True,
        "supply_pump_on": True,
    }
    assert steps[1]["supply_pump_on"] is False
    assert steps[1]["duration_s"] == 7200 and steps[1]["delay_s"] == 300
    # No pump linked: wet steps still say wet, but nothing to switch.
    payload = model.settings_payload(
        targets={},
        cycle_s=60,
        default_speed=50,
        max_run_hours=0,
        tz_name="Australia/Brisbane",
        schedule=s,
        history=[],
        supply_pump=None,
    )
    assert payload["schedule"]["steps"][0]["supply_pump_on"] is False


# --------------------------------------------------------------------------- RPCs


def ctx(**data):
    return NS(message=NS(data={"actor": {"name": "Sam"}, **data}))


TWO_STEPS = {
    "mode": "detailed",
    "steps": [
        step(stop_angle_deg=120),
        step(direction="reverse", wet=False, end="time", run_hours=1),
    ],
}


async def test_start_pause_resume_end(harness):
    harness.tag_values["gps_tracker_1"] = {"bearing_deg": 100.0}
    app = await harness.app()
    result = await app.on_schedule_start(ctx(), TWO_STEPS)
    await app.on_schedule(None)
    sid = result["schedule_id"]

    active = app.tags.schedule_active.value
    assert (
        active["id"] == sid
        and active["status"] == "running"
        and active["started_by"] == "Sam"
    )
    assert (
        active["progress"]["step_index"] == 0
        and active["progress"]["remaining_deg"] == 20.0
    )
    settings = harness.api.settings()
    assert settings["schedule"]["id"] == sid and settings["schedule"]["paused"] is False
    assert settings["schedule_state"]["active"]["id"] == sid
    cmd = harness.api.commands()[-1]
    assert cmd["command"] == "schedule_start" and cmd["params"]["schedule_id"] == sid
    assert len(cmd["params"]["schedule"]["steps"]) == 2
    assert app.tags.pending_command.value is None  # not tracked as a start / stop

    # A second start is refused while one runs.
    app = await harness.app()
    with pytest.raises(RPCError) as e:
        await app.on_schedule_start(ctx(), TWO_STEPS)
    assert "already running" in e.value.message

    app = await harness.app()
    await app.on_schedule_pause(ctx(), {"schedule_id": sid})
    assert harness.api.settings()["schedule"]["paused"] is True
    assert app.tags.schedule_active.value["status"] == "paused"
    assert harness.api.commands()[-1]["command"] == "schedule_pause"

    app = await harness.app()
    await app.on_schedule_resume(ctx(), {"schedule_id": sid})
    assert harness.api.settings()["schedule"]["status"] == "running"
    assert harness.api.commands()[-1]["command"] == "schedule_resume"

    app = await harness.app()
    await app.on_schedule_end(ctx(), {"schedule_id": sid})
    assert app.tags.schedule_active.value is None
    history = app.tags.schedule_history.value
    assert history[0]["id"] == sid and history[0]["status"] == "ended"
    assert history[0]["ended_ts"] is not None
    assert harness.api.settings()["schedule"] is None
    assert harness.api.commands()[-1] == {
        **harness.api.commands()[-1],
        "command": "schedule_end",
        "params": {"schedule_id": sid},
        "app_key": APP_KEY,
    }

    # Acting on a finished schedule is refused.
    app = await harness.app()
    with pytest.raises(RPCError):
        await app.on_schedule_pause(ctx(), {"schedule_id": sid})


async def test_bad_schedule_refused_with_every_message(harness):
    app = await harness.app()
    with pytest.raises(RPCError) as e:
        await app.on_schedule_start(
            ctx(),
            {
                "mode": "detailed",
                "steps": [step(), step(stop_angle_deg=None, speed_percent=101)],
            },
        )
    assert e.value.message == (
        "Step 2: speed must be 1–100 %\nStep 2: choose a stop angle or a run time"
    )
    assert harness.api.commands() == []
    assert app.tags.schedule_active.value is None


async def test_schedule_completes_into_history(harness):
    harness.tag_values["gps_tracker_1"] = {"bearing_deg": 100.0}
    app = await harness.app()
    await app.on_schedule_start(
        ctx(),
        {"mode": "simple", "steps": [{"direction": "forward", "stop_angle_deg": 110}]},
    )
    harness.tag_values["gps_tracker_1"] = {"bearing_deg": 105.0}
    app = await harness.app()
    await app.on_schedule(None)
    assert app.tags.schedule_active.value["progress"]["fraction"] == pytest.approx(0.5)
    harness.tag_values["gps_tracker_1"] = {"bearing_deg": 109.5}
    app = await harness.app()
    await app.on_schedule(None)
    assert app.tags.schedule_active.value is None
    assert app.tags.schedule_history.value[0]["status"] == "completed"
    assert app.tags.last_command.value == "Schedule completed"


async def test_stale_tags_are_put_right_from_settings(harness):
    app = await harness.app()
    result = await app.on_schedule_start(ctx(), TWO_STEPS)
    # A concurrent invocation that began before the start wrote the old (empty) tags back.
    harness.tag_values[APP_KEY]["schedule_active"] = None
    app = await harness.app()
    await app.on_schedule(None)
    assert app.tags.schedule_active.value["id"] == result["schedule_id"]


async def test_deployment_clears_the_old_slot_tags(harness):
    harness.tag_values[APP_KEY] = {"schedules": [{"slot": 1}], "sched_1_summary": "Off"}
    app = await harness.app()
    await app.on_deployment(None)
    assert app.tag_manager.get_tag("schedules") is None
    assert app.tag_manager.get_tag("sched_1_summary") is None
    assert harness.api.settings()["schedule"] is None


async def test_demo_simulated_controller_reports_progress_as_actual():
    h = Harness(config=dict(EXAMPLE_CONFIG, demo_simulate_controller=True))
    h.tag_values["gps_tracker_1"] = {"bearing_deg": 100.0}
    app = await h.app()
    await app.on_schedule_start(ctx(), TWO_STEPS)
    assert app.tags.schedule_active.value["progress"]["estimated"] is False
    app = await h.app()
    await app.on_schedule(None)
    assert app.tags.schedule_active.value["progress"]["estimated"] is False
    assert app.tags.pending_command.value is None
    assert app.tags.command_warning_hidden.value is True
