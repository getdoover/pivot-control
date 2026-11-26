from pydoover.tags import Tag, Tags


class PivotControlTags(Tags):
    # Reported state (derived from the reported forward / reverse outputs).
    state = Tag(
        "string", default=None
    )  # running, stopped, unknown; None before any reading
    direction = Tag("string", default=None)  # forward, reverse; None unless running
    status = Tag(
        "string", default="No reading yet"
    )  # Running Forward / Running Reverse / Stopped / Unknown
    speed_percent = Tag("number", default=None)
    angle_deg = Tag("number", default=None)
    heading = Tag("string", default=None)  # "123° ESE"
    safety_ok = Tag("boolean", default=None)
    safety_text = Tag("string", default=None)  # OK / Tripped
    pressure = Tag("number", default=None)
    last_started = Tag("number", default=None)  # unix ms
    last_stopped = Tag("number", default=None)  # unix ms
    running_since = Tag(
        "number", default=None
    )  # unix ms: start seen, or first seen running

    # Raw reported inputs, as last seen (an input message may carry only some of them).
    run_output = Tag("boolean", default=None)
    forward_output = Tag("boolean", default=None)
    reverse_output = Tag("boolean", default=None)
    reported_speed = Tag("number", default=None)
    safety_input = Tag("number", default=None)
    pressure_input = Tag("number", default=None)

    # Automatic input addresses: where each point is read from (for the edge bridge's map),
    # and which points have ever had a value. An optional input on its automatic address is
    # shown only once it has.
    io_points = Tag("object", default=None)  # {"version": 1, "points": [...]}
    inputs_seen = Tag("object", default=None)  # {point id: true}
    safety_hidden = Tag("boolean", default=True)
    pressure_hidden = Tag("boolean", default=True)

    # Commands.
    pending_command = Tag("object", default=None)  # the command message, plus timed_out
    started_speed = Tag("number", default=None)  # speed of the last start sent
    last_command = Tag("string", default=None)
    command_message = Tag("string", default="")
    command_warning_hidden = Tag("boolean", default=True)

    # Schedule (the edge runs it from the Settings Channel; these mirror what is stored there).
    schedule_active = Tag(
        "object", default=None
    )  # the running schedule, with its progress
    schedule_history = Tag("array", default=None)  # the last five, newest first
    edge_schedule_state = Tag("object", default=None)  # as the edge last reported it

    # Notification latches, so each fires once per occurrence.
    safety_alert_active = Tag("boolean", default=False)
    low_pressure_active = Tag("boolean", default=False)
    safety_warning_hidden = Tag("boolean", default=True)

    # Supply pump (another device's Pump Control install), as last read from its tags.
    supply_pump_name = Tag("string", default=None)  # "<device>: <pump name>"
    supply_pump_state = Tag("string", default="Unknown")  # Running / Stopped / Unknown
    supply_pump_running = Tag("boolean", default=None)
    supply_pump_last_started = Tag("number", default=None)  # unix ms
    supply_pump_last_stopped = Tag("number", default=None)  # unix ms
    supply_pump_mode = Tag("string", default=None)  # how it follows the pivot
    supply_pump_checked = Tag("number", default=None)  # unix ms of the last read
    supply_pump_warning = Tag("string", default="")
    supply_pump_warning_hidden = Tag("boolean", default=True)
