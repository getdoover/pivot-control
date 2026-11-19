from types import SimpleNamespace as NS

from conftest import APP_KEY, Harness
from pydoover.models import AggregateUpdateEvent

from pivot_control import model


def io_state(**data):
    return NS(channel=NS(name="io_state"), message=NS(data=data))


def message(channel, data):
    return NS(channel=NS(name=channel), message=NS(data=data))


async def test_no_data_renders_cleanly_and_fires_nothing(harness):
    app = await harness.app()
    await app.on_schedule(None)
    await app.on_message_create(io_state(unrelated=3))
    assert harness.notifications.sent == []
    assert harness.api.messages == []
    assert app.tags.status.value == "No reading yet"
    assert app.tags.state.value is None
    assert app.tags.safety_ok.value is None
    assert app.tags.pressure.value is None
    assert app.tags.angle_deg.value is None


async def test_empty_config_does_not_raise():
    h = Harness(config={"APP_KEY": APP_KEY})
    app = await h.app()
    await app.on_message_create(io_state(forward=1, reverse=0))
    assert app.tags.status.value == "Running Forward"
    assert app.tags.safety_ok.value is None  # no safety input configured
    await app.on_deployment(None)
    assert h.notifications.sent == []


async def test_reported_state_and_angle(harness):
    harness.tag_values["gps_tracker_1"] = {"bearing_deg": 271.6}
    app = await harness.app()
    await app.on_message_create(
        io_state(forward=0, reverse=1, run=1, safety=1, water_pressure=12.0)
    )
    assert app.tags.status.value == "Running Reverse"
    assert app.tags.direction.value == "reverse"
    assert app.tags.angle_deg.value == 271.6
    assert app.tags.heading.value == "272° W"
    assert app.tags.safety_text.value == "OK"
    assert app.tags.pressure.value == 43.5
    assert app.tags.last_started.value is None  # first reading: start time unknown

    app = await harness.app()
    await app.on_message_create(io_state(forward=0, reverse=0))
    assert app.tags.status.value == "Stopped"
    assert app.tags.last_stopped.value is not None

    app = await harness.app()
    await app.on_message_create(io_state(forward=1))  # partial message: reverse kept
    assert app.tags.status.value == "Running Forward"
    assert app.tags.last_started.value is not None


async def test_angle_follows_source_tag_updates(harness):
    harness.tag_values["gps_tracker_1"] = {"bearing_deg": 10.0}
    app = await harness.app()
    event = NS(
        channel=NS(name="tag_values"),
        request_data=NS(data={"gps_tracker_1": {"bearing_deg": 10.0}}),
    )
    await app.on_aggregate_update(event)
    assert app.tags.angle_deg.value == 10.0


async def test_aggregate_updates_filtered_to_tag_values(harness):
    app = await harness.app()
    ui_cmds = object.__new__(AggregateUpdateEvent)
    ui_cmds.channel = NS(name="ui_cmds")
    assert await app.pre_hook_filter(ui_cmds) is False
    ui_cmds.channel = NS(name="tag_values")
    assert await app.pre_hook_filter(ui_cmds) is True


async def test_start_command_and_confirmation():
    h = Harness(
        ui_values={
            "start_direction": "reverse",
            "start_speed": 35,
            "start_end": "stop_at_angle",
            "start_stop_angle": 90,
        }
    )
    app = await h.app()
    await app.on_message_create(io_state(forward=0, reverse=0))
    result = await app.on_start(None, None)
    assert result["sent"] is True
    channel, cmd = h.api.messages[-1]
    assert channel == "io_commands"
    assert (
        cmd["command"] == "start"
        and cmd["target"] == "run"
        and cmd["duration_s"] is None
    )
    assert cmd["params"] == {
        "direction": "reverse",
        "speed_percent": 35.0,
        "stop_angle_deg": 90.0,
    }
    assert cmd["app_key"] == APP_KEY and cmd["app"] == "pivot_control"
    assert app.tags.command_warning_hidden.value is False
    assert "waiting" in app.tags.command_message.value

    app = await h.app()
    await app.on_message_create(io_state(reverse=1))
    assert app.tags.pending_command.value is None
    assert app.tags.command_warning_hidden.value is True
    assert app.tags.last_command.value.endswith("confirmed")
    assert app.tags.speed_percent.value == 35.0
    assert h.notifications.sent == []


async def test_start_with_bad_input_is_not_sent():
    h = Harness(ui_values={"start_end": "run_for_hours"})  # no run time
    app = await h.app()
    result = await app.on_start(None, None)
    assert result["sent"] is False
    assert h.api.messages == []
    assert app.tags.last_command.value.startswith("Start not sent")


async def test_unconfirmed_command_notifies_once(harness):
    app = await harness.app()
    await app.on_message_create(io_state(forward=0, reverse=0))
    await app.on_start(None, None)
    pending = dict(app.tags.pending_command.value)
    pending["ts"] -= 10 * 60 * 1000  # sent 10 min ago
    await app.tags.pending_command.set(pending)

    app = await harness.app()
    await app.on_schedule(None)
    assert [n for n, _ in harness.notifications.sent] == ["command_not_confirmed"]
    assert app.tags.command_warning_hidden.value is False
    assert "not confirmed" in app.tags.command_message.value

    app = await harness.app()
    await app.on_schedule(None)
    assert len(harness.notifications.sent) == 1

    app = await harness.app()
    await app.on_message_create(io_state(forward=1))  # it did start, late
    assert app.tags.command_warning_hidden.value is True


async def test_controller_refusal_shown(harness):
    app = await harness.app()
    await app.on_stop(None, None)
    request_id = harness.api.messages[-1][1]["request_id"]
    app = await harness.app()
    await app.on_message_create(
        message(
            "io_commands",
            {"request_id": request_id, "ok": False, "error": "panel in local"},
        )
    )
    assert app.tags.pending_command.value is None
    assert "refused" in app.tags.command_message.value
    assert "panel in local" in app.tags.last_command.value


async def test_safety_trip_while_running_notifies_once(harness):
    app = await harness.app()
    await app.on_message_create(io_state(forward=1, reverse=0, safety=1))
    app = await harness.app()
    await app.on_message_create(io_state(safety=0))
    assert [n for n, _ in harness.notifications.sent] == ["safety_tripped"]
    assert app.tags.safety_warning_hidden.value is False
    app = await harness.app()
    await app.on_message_create(io_state(safety=0, forward=0))
    assert len(harness.notifications.sent) == 1


async def test_safety_trip_while_stopped_long_ago_is_quiet(harness):
    app = await harness.app()
    await app.on_message_create(io_state(forward=0, reverse=0, safety=1))
    app = await harness.app()
    await app.on_message_create(io_state(safety=0))
    assert harness.notifications.sent == []
    assert app.tags.safety_text.value == "Tripped"


async def test_low_pressure_after_start_delay(harness):
    app = await harness.app()
    await app.on_message_create(io_state(forward=0, reverse=0, water_pressure=4.0))
    app = await harness.app()
    await app.on_message_create(io_state(forward=1, water_pressure=4.5))
    assert harness.notifications.sent == []  # within the start delay
    await app.tags.running_since.set(model.now_ms() - 10 * 60 * 1000)
    app = await harness.app()
    await app.on_message_create(io_state(water_pressure=4.5))
    assert [n for n, _ in harness.notifications.sent] == ["low_pressure"]
    app = await harness.app()
    await app.on_message_create(io_state(water_pressure=4.6))
    assert len(harness.notifications.sent) == 1


async def test_schedule_edit_publishes_settings(harness):
    app = await harness.app()
    ctx = NS(method="sched_2_enabled")
    await app.on_schedule_edit(ctx, True)
    channel, data, kwargs = harness.api.aggregates[-1]
    assert channel == "control_settings"
    assert kwargs["replace_keys"] == [APP_KEY]
    settings = data[APP_KEY]
    assert settings["app"] == "pivot_control"
    assert settings["targets"] == {
        "run": "run",
        "forward": "forward",
        "reverse": "reverse",
    }
    assert settings["percent_timer_cycle_s"] == 60
    assert settings["schedules"][1]["enabled"] is False  # no start time yet
    assert app.tags.sched_2_summary.value == "Not set: no start time"

    app = await harness.app()
    await app.on_schedule_edit(NS(method="sched_2_start"), 1795118400000)
    settings = harness.api.aggregates[-1][1][APP_KEY]
    assert settings["schedules"][1]["enabled"] is True
    assert settings["schedules"][1]["start_local"] == "2026-11-20T06:00:00+10:00"


async def test_deployment_publishes_settings(harness):
    app = await harness.app()
    await app.on_deployment(None)
    channel, data, _kwargs = harness.api.aggregates[-1]
    assert channel == "control_settings" and APP_KEY in data
    assert harness.notifications.sent == []
