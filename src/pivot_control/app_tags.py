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

    # Commands.
    pending_command = Tag("object", default=None)  # the command message, plus timed_out
    started_speed = Tag("number", default=None)  # speed of the last start sent
    last_command = Tag("string", default=None)
    command_message = Tag("string", default="")
    command_warning_hidden = Tag("boolean", default=True)

    # Schedules (the operator's edits; the edge runs them from the Settings Channel).
    schedules = Tag("array", default=None)
    sched_1_summary = Tag("string", default="Off")
    sched_2_summary = Tag("string", default="Off")
    sched_3_summary = Tag("string", default="Off")
    sched_4_summary = Tag("string", default="Off")

    # Notification latches, so each fires once per occurrence.
    safety_alert_active = Tag("boolean", default=False)
    low_pressure_active = Tag("boolean", default=False)
    safety_warning_hidden = Tag("boolean", default=True)
