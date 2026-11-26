from types import SimpleNamespace as NS

from conftest import APP_KEY, EXAMPLE_CONFIG, Harness
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
    # Blank paths: the automatic addresses, $io_state.<app key>.<point id>.
    await app.on_message_create(io_state(**{APP_KEY: {"forward": 1, "reverse": 0}}))
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


async def test_deployment_publishes_settings(harness):
    app = await harness.app()
    await app.on_deployment(None)
    channel, data, _kwargs = harness.api.aggregates[-1]
    assert channel == "control_settings" and APP_KEY in data
    assert harness.notifications.sent == []


async def test_angle_from_gps_and_centre_without_angle_tag(harness):
    harness.config.update(pivot_centre_lat=-22.551015, pivot_centre_lon=149.060910)
    harness.tag_values["gps_tracker_1"] = {
        "latitude": -22.548267,
        "longitude": 149.057164,
    }
    app = await harness.app()
    event = NS(
        channel=NS(name="tag_values"),
        request_data=NS(data={"gps_tracker_1": {"latitude": -22.548267}}),
    )
    await app.on_aggregate_update(event)
    assert app.tags.angle_deg.value == 308.5
    assert app.tags.heading.value.endswith("NW")


async def test_angle_tag_wins_over_gps(harness):
    harness.config.update(pivot_centre_lat=-22.551015, pivot_centre_lon=149.060910)
    harness.tag_values["gps_tracker_1"] = {
        "bearing_deg": 12.0,
        "latitude": -22.548267,
        "longitude": 149.057164,
    }
    app = await harness.app()
    await app.on_schedule(None)
    assert app.tags.angle_deg.value == 12.0


async def test_no_gps_angle_without_centre_or_in_location_mode(harness):
    harness.tag_values["gps_tracker_1"] = {
        "latitude": -22.548267,
        "longitude": 149.057164,
    }
    app = await harness.app()
    await app.on_schedule(None)
    assert app.tags.angle_deg.value is None  # no centre configured

    harness.config.update(
        pivot_centre_lat=-22.551015,
        pivot_centre_lon=149.060910,
        position_source="Location channel",
    )
    app = await harness.app()
    await app.on_schedule(None)
    assert app.tags.angle_deg.value is None


async def test_unrelated_tag_updates_are_skipped(harness):
    app = await harness.app()
    event = NS(
        channel=NS(name="tag_values"),
        request_data=NS(data={APP_KEY: {"status": "Stopped"}}),
    )
    await app.on_aggregate_update(event)
    assert app.tags.status.value == "No reading yet"  # not evaluated


async def test_angle_shown_with_gps_and_centre_only():
    h = Harness(config={"APP_KEY": APP_KEY})
    app = await h.app()
    assert app.ui.angle.hidden is True
    h = Harness(
        config={
            "APP_KEY": APP_KEY,
            "pivot_centre_lat": -22.5,
            "pivot_centre_lon": 149.0,
        }
    )
    app = await h.app()
    assert app.ui.angle.hidden is False


# --------------------------------------------------------------------------- supply pump

PUMP_DEVICE = "123456789012345678"
PUMP_CONFIG = dict(
    EXAMPLE_CONFIG,
    supply_pump_device=PUMP_DEVICE,
    supply_pump_app_key="pump_control_2",
    supply_pump_target="pump_start",
    supply_pump_lead_s=30,
    supply_pump_run_on_s=60,
)
DEVICE_MAP = {PUMP_DEVICE: {"id": PUMP_DEVICE, "display_name": "Eastern Pump"}}


def pump_tags(**fields):
    return {f"p_pump_start_{k}": v for k, v in fields.items()}


async def pump_app(h):
    app = await h.app()
    app.received_deployment_config = {"DEVICE_MAP": DEVICE_MAP}
    return app


async def test_no_supply_pump_configured():
    h = Harness()
    app = await h.app()
    await app.on_deployment(None)
    assert app.ui.supply_pump.hidden is True
    assert [f for f in h.api.fetched if f[0] is not None] == []  # no other device read
    settings = h.api.aggregates[-1][1][APP_KEY]
    assert settings["supply_pump"] is None
    await app.on_start(None, None)
    assert "supply_pump" not in h.api.messages[-1][1]["params"]


async def test_supply_pump_state_shown():
    h = Harness(config=PUMP_CONFIG)
    h.api.remote[(int(PUMP_DEVICE), "tag_values")] = {
        "pump_control_2": pump_tags(
            running=True, name="Diesel Pump", last_started=1795000000000
        )
    }
    app = await pump_app(h)
    assert app.ui.supply_pump.hidden is False
    await app.on_deployment(None)
    assert app.tags.supply_pump_name.value == "Eastern Pump: Diesel Pump"
    assert app.tags.supply_pump_state.value == "Running"
    assert app.tags.supply_pump_running.value is True
    assert app.tags.supply_pump_last_started.value == 1795000000000
    assert app.tags.supply_pump_mode.value == (
        "Starts with the pivot, 30 s lead, 60 s run-on"
    )
    assert app.tags.supply_pump_checked.value is not None
    assert app.tags.supply_pump_warning_hidden.value is True

    settings = h.api.aggregates[-1][1][APP_KEY]
    assert settings["supply_pump"] == {
        "device_id": PUMP_DEVICE,
        "app_key": "pump_control_2",
        "target": "pump_start",
        "start_with_pivot": True,
        "lead_s": 30,
        "run_on_s": 60,
    }

    # Stopped, on the next schedule tick.
    h.api.remote[(int(PUMP_DEVICE), "tag_values")]["pump_control_2"].update(
        pump_tags(running=False, last_stopped=1795000600000)
    )
    app = await pump_app(h)
    await app.on_schedule(None)
    assert app.tags.supply_pump_state.value == "Stopped"
    assert app.tags.supply_pump_last_stopped.value == 1795000600000


async def test_supply_pump_unreadable_or_unreported_is_unknown():
    h = Harness(config=PUMP_CONFIG)
    app = await pump_app(h)
    await app.on_schedule(None)  # no permission on the pump's device
    assert app.tags.supply_pump_state.value == "Unknown"
    assert app.tags.supply_pump_running.value is None
    assert "add it under Devices" in app.tags.supply_pump_warning.value
    assert app.tags.supply_pump_warning_hidden.value is False
    assert h.notifications.sent == []

    h.api.remote[(int(PUMP_DEVICE), "tag_values")] = {"other_app": {"x": 1}}
    app = await pump_app(h)
    await app.on_schedule(None)  # readable, but the pump app hasn't reported
    assert app.tags.supply_pump_state.value == "Unknown"
    assert "reported nothing yet" in app.tags.supply_pump_warning.value
    assert app.tags.supply_pump_name.value == "Eastern Pump: pump_start"


async def test_incomplete_supply_pump_link_warns_and_is_not_commanded():
    config = dict(EXAMPLE_CONFIG, supply_pump_device=PUMP_DEVICE)
    h = Harness(config=config)
    app = await pump_app(h)
    await app.on_deployment(None)
    assert [f for f in h.api.fetched if f[0] is not None] == []  # pump not read
    assert "Supply Pump App Key" in app.tags.supply_pump_warning.value
    assert app.tags.supply_pump_state.value == "Unknown"
    await app.on_start(None, None)
    assert "supply_pump" not in h.api.messages[-1][1]["params"]


async def test_start_and_stop_carry_the_supply_pump():
    h = Harness(config=PUMP_CONFIG)
    app = await pump_app(h)
    await app.on_start(None, None)
    cmd = h.api.messages[-1][1]
    assert cmd["command"] == "start"
    assert cmd["params"]["supply_pump"]["target"] == "pump_start"
    assert cmd["params"]["supply_pump"]["lead_s"] == 30
    assert cmd["params"]["direction"] == "forward"
    assert model.command_label(cmd) == "Start Forward at 50 %"

    app = await pump_app(h)
    await app.on_stop(None, None)
    cmd = h.api.messages[-1][1]
    assert cmd["command"] == "stop"
    assert cmd["params"]["supply_pump"]["run_on_s"] == 60


async def test_pump_not_started_with_pivot_stays_out_of_commands():
    h = Harness(config=dict(PUMP_CONFIG, supply_pump_with_pivot=False))
    app = await pump_app(h)
    await app.on_deployment(None)
    assert app.tags.supply_pump_mode.value == "Not started with the pivot"
    assert h.api.aggregates[-1][1][APP_KEY]["supply_pump"]["start_with_pivot"] is False
    await app.on_start(None, None)
    assert "supply_pump" not in h.api.messages[-1][1]["params"]
