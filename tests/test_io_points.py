"""Automatic input addresses ($io_state.<app key>.<point id>) and the io_points tag."""

from types import SimpleNamespace as NS

from conftest import APP_KEY, Harness

from pivot_control import model


def io_state(**data):
    return NS(channel=NS(name="io_state"), message=NS(data=data))


def nested(**data):
    """An io_state message carrying this install's points under its app key."""
    return io_state(**{APP_KEY: data})


BLANK = {"APP_KEY": APP_KEY}


# --------------------------------------------------------------------------- model


def test_resolve_blank_is_automatic():
    assert model.resolve_input_path("", "pivot_control_2", "forward") == (
        "$io_state.pivot_control_2.forward",
        True,
    )
    assert model.resolve_input_path(None, "p", "speed") == ("$io_state.p.speed", True)
    assert model.resolve_input_path("   ", "p", "safety") == (
        "$io_state.p.safety",
        True,
    )


def test_resolve_explicit_wins():
    assert model.resolve_input_path("$io_state.fwd", "p", "forward") == (
        "$io_state.fwd",
        False,
    )
    assert model.resolve_input_path(" $on_dm_event.x ", "p", "speed") == (
        "$on_dm_event.x",
        False,
    )


def test_nested_extraction_from_automatic_address():
    channel, parts = model.parse_message_path("$io_state.pivot_control_1.pressure")
    assert channel == "io_state" and parts == ["pivot_control_1", "pressure"]
    data = {"pivot_control_1": {"pressure": 12.5}, "other": 1}
    assert model.extract_path_value(data, parts) == 12.5
    assert model.extract_path_value({"other": 1}, parts) is None


def test_io_points_order_and_shape():
    tag = model.io_points(
        [{"id": "run", "label": "Run", "path": "$io_state.k.run", "auto": True}],
        [
            {"id": "speed", "label": "Speed", "path": "$io_state.s", "auto": False},
            {"id": "run", "label": "Dup", "path": "$io_state.x", "auto": True},
        ],
    )
    assert tag == {
        "version": 1,
        "points": [
            {
                "id": "run",
                "label": "Run",
                "kind": "output",
                "path": "$io_state.k.run",
                "auto": True,
            },
            {
                "id": "speed",
                "label": "Speed",
                "kind": "input",
                "path": "$io_state.s",
                "auto": False,
            },
        ],
    }


# --------------------------------------------------------------------------- app


async def test_io_points_published_with_all_blank_paths():
    h = Harness(config=dict(BLANK))
    app = await h.app()
    await app.on_deployment(None)
    tag = app.tags.io_points.value
    assert tag["version"] == 1
    assert [(p["id"], p["kind"], p["label"]) for p in tag["points"]] == [
        ("run", "output", "Run"),
        ("forward", "output", "Forward"),
        ("reverse", "output", "Reverse"),
        ("speed", "input", "Speed"),
        ("safety", "input", "Safety circuit"),
        ("pressure", "input", "Line pressure"),
        ("schedule_state", "input", "Schedule progress"),
    ]
    for point in tag["points"]:
        assert point["auto"] is True
        assert point["path"] == f"$io_state.{APP_KEY}.{point['id']}"
        assert "_" not in point["label"]


async def test_io_points_use_targets_and_explicit_paths():
    h = Harness(
        config=dict(
            BLANK,
            run_target="pivot_run",
            forward_target="pivot_fwd",
            reverse_target="pivot_rev",
            pressure_path="$io_state.water_pressure",
        )
    )
    app = await h.app()
    await app.on_schedule(None)
    points = {p["id"]: p for p in app.tags.io_points.value["points"]}
    assert list(points)[:3] == ["pivot_run", "pivot_fwd", "pivot_rev"]
    assert points["pivot_fwd"]["path"] == f"$io_state.{APP_KEY}.pivot_fwd"
    assert points["pressure"] == {
        "id": "pressure",
        "label": "Line pressure",
        "kind": "input",
        "path": "$io_state.water_pressure",
        "auto": False,
    }


async def test_io_points_written_only_when_changed():
    h = Harness(config=dict(BLANK))
    app = await h.app()
    await app.on_schedule(None)
    first = h.tag("io_points")
    app = await h.app()
    writes = []
    original = app.tags.io_points.set

    async def spy(value):
        writes.append(value)
        await original(value)

    app.tags.io_points.set = spy
    await app.on_schedule(None)
    assert writes == [] and h.tag("io_points") == first


async def test_state_read_from_automatic_address():
    h = Harness(config=dict(BLANK, forward_target="fwd"))
    app = await h.app()
    await app.on_message_create(nested(fwd=1, reverse=0, run=1))
    assert app.tags.status.value == "Running Forward"
    assert app.tags.run_output.value is True
    # A flat message is not this install's automatic address.
    app = await h.app()
    await app.on_message_create(io_state(fwd=0, forward=0))
    assert app.tags.status.value == "Running Forward"


async def test_optional_inputs_hidden_until_first_value():
    h = Harness(config=dict(BLANK, low_pressure_threshold=20.0))
    app = await h.app()
    await app.on_deployment(None)
    await app.on_message_create(nested(forward=1, reverse=0))
    # Nothing reported yet for the optional inputs: exactly as if they weren't configured.
    assert app.ui.safety.hidden is not False and app.ui.pressure.hidden is not False
    assert app.tags.safety_hidden.value is True
    assert app.tags.pressure_hidden.value is True
    assert app.tags.safety_ok.value is None and app.tags.safety_text.value is None
    assert app.tags.pressure.value is None
    assert h.notifications.sent == []

    app = await h.app()
    await app.on_message_create(nested(safety=1, pressure=12.0))
    assert app.tags.safety_hidden.value is False
    assert app.tags.pressure_hidden.value is False
    assert app.tags.safety_text.value == "OK"
    assert app.tags.pressure.value == 50.0
    assert app.tags.inputs_seen.value == {
        "forward": True,
        "reverse": True,
        "safety": True,
        "pressure": True,
    }

    # Once seen, shown from then on, even with no new value in later messages.
    app = await h.app()
    await app.on_message_create(nested(forward=0))
    assert app.tags.safety_hidden.value is False
    assert app.tags.pressure_hidden.value is False


async def test_automatic_speed_used_once_reported():
    h = Harness(config=dict(BLANK), ui_values={"start_speed": 40})
    app = await h.app()
    await app.on_message_create(nested(forward=0, reverse=0))
    await app.on_start(None, None)
    app = await h.app()
    await app.on_message_create(nested(forward=1))
    assert app.tags.speed_percent.value == 40.0  # nothing reported: the started speed
    app = await h.app()
    await app.on_message_create(nested(speed=65))
    assert app.tags.speed_percent.value == 65.0


async def test_explicit_paths_shown_without_values():
    h = Harness(config=dict(BLANK, safety_path="$io_state.safety"))
    app = await h.app()
    assert app.ui.safety.hidden is False
