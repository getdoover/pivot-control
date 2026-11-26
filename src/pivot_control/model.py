"""The pivot as the app sees it: pure functions, no IO.

Inputs arrive as raw signals at configured message paths (``$channel.path``); commands go out
as messages on the Command Channel; the settings the edge enforces (defaults, limits and the
running schedule) go to the Settings Channel aggregate under the app's key. See README.md.
"""

from __future__ import annotations

import math
import re
import time
import uuid
from typing import Any

SETTINGS_SCHEMA = 2
APP_NAME = "pivot_control"

FORWARD = "forward"
REVERSE = "reverse"
DIRECTIONS = (FORWARD, REVERSE)

RUNNING = "running"
STOPPED = "stopped"
UNKNOWN = "unknown"

# How a run ends: latched until a Stop, at an angle, or after a time.
END_UNTIL_STOPPED = "until_stopped"
END_AT_ANGLE = "stop_at_angle"
END_AFTER_TIME = "run_for_hours"
END_MODES = (END_UNTIL_STOPPED, END_AT_ANGLE, END_AFTER_TIME)

# A loop current this fraction of the input span below the minimum input (under 1 mA on
# 4-20 mA) is a dead loop, not a low reading (same rule as Analog Level Sensor).
UNDER_RANGE_MARGIN = 3 / 16

COMPASS_POINTS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


# --------------------------------------------------------------------------- inputs


def parse_message_path(value: Any) -> tuple[str, list[str]] | None:
    """``$channel.path.to.value`` (or ``$channel:path``) as (channel, [path parts]).

    Empty means the input isn't configured: None. A malformed path is also None (and the
    caller logs it), so a bad path can never take the handler down."""
    if not value or not isinstance(value, str):
        return None
    path = value.strip()
    if not path.startswith("$"):
        return None
    body = path[1:]
    if ":" in body:
        channel, raw = body.split(":", 1)
    elif "." in body:
        channel, raw = body.split(".", 1)
    else:
        return None
    channel = channel.strip()
    parts = [p.strip() for p in raw.split(".") if p.strip()]
    if not channel or not parts:
        return None
    return channel, parts


AUTO_CHANNEL = "io_state"


def auto_path(app_key: str, point_id: str) -> str:
    """An input's automatic address: ``$io_state.<app key>.<point id>``."""
    return f"${AUTO_CHANNEL}.{app_key}.{point_id}"


def resolve_input_path(value: Any, app_key: str, point_id: str) -> tuple[str, bool]:
    """The path an input is read from, and whether it is automatic.

    Blank means the automatic address (which the edge bridge fills in); anything else is an
    explicit message path and wins, exactly as given."""
    explicit = value.strip() if isinstance(value, str) else ""
    if explicit:
        return explicit, False
    return auto_path(app_key, point_id), True


def io_points(outputs: list[dict], inputs: list[dict]) -> dict:
    """The ``io_points`` tag: outputs first, then inputs, each in config order.

    Each entry is ``{"id", "label", "path", "auto"}``; a point id seen twice keeps its
    first entry, so ids stay unique within the install."""
    points, seen = [], set()
    for kind, entries in (("output", outputs), ("input", inputs)):
        for entry in entries:
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            points.append(
                {
                    "id": entry["id"],
                    "label": entry["label"],
                    "kind": kind,
                    "path": entry["path"],
                    "auto": bool(entry["auto"]),
                }
            )
    return {"version": 1, "points": points}


def extract_path_value(data: Any, path: list[str]):
    value = data
    for part in path:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if value is None:
            return None
    return value


def coerce_number(value: Any) -> float | None:
    """A raw signal as a number: bools are 1/0, "on"/"off" strings too. None if it isn't one."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "on", "yes", "closed"):
            return 1.0
        if text in ("false", "off", "no", "open"):
            return 0.0
        try:
            return float(text)
        except ValueError:
            return None
    return None


def coerce_bool(value: Any) -> bool | None:
    number = coerce_number(value)
    if number is None:
        return None
    return number != 0


# --------------------------------------------------------------------------- state


def derive_state(
    forward_on: bool | None, reverse_on: bool | None
) -> tuple[str, str | None]:
    """(state, direction) from the reported forward / reverse outputs.

    Forward on and reverse off is running forward; the other way round, reverse. Both off is
    stopped. Both on, or either not reported yet, is unknown."""
    if forward_on is None or reverse_on is None:
        return UNKNOWN, None
    if forward_on and reverse_on:
        return UNKNOWN, None
    if forward_on:
        return RUNNING, FORWARD
    if reverse_on:
        return RUNNING, REVERSE
    return STOPPED, None


def status_text(state: str | None, direction: str | None, has_reading: bool) -> str:
    if state == RUNNING and direction == FORWARD:
        return "Running Forward"
    if state == RUNNING and direction == REVERSE:
        return "Running Reverse"
    if state == STOPPED:
        return "Stopped"
    if not has_reading:
        return "No reading yet"
    return "Unknown"


def expected_state(command: dict) -> tuple[str, str | None]:
    """The (state, direction) that confirms a command."""
    if command.get("command") == "start":
        return RUNNING, command.get("direction")
    return STOPPED, None


def scale_linear(
    value: float, in_min: float, in_max: float, out_min: float, out_max: float
) -> float | None:
    if in_max == in_min:
        return None
    return (value - in_min) / (in_max - in_min) * (out_max - out_min) + out_min


def scale_pressure(
    raw: float | None, in_min: float, in_max: float, out_min: float, out_max: float
) -> float | None:
    """A raw pressure input (e.g. mA) in engineering units. A dead loop (well under the minimum
    input) is None, not a zero pressure; just under the minimum reads as the minimum."""
    if raw is None:
        return None
    span = abs(in_max - in_min)
    low = min(in_min, in_max)
    if raw < low - span * UNDER_RANGE_MARGIN:
        return None
    reading = max(raw, low)
    return scale_linear(reading, in_min, in_max, out_min, out_max)


def normalise_angle(value: Any) -> float | None:
    number = coerce_number(value)
    if number is None or math.isnan(number):
        return None
    return number % 360.0


def heading_text(angle: float | None) -> str | None:
    if angle is None:
        return None
    point = COMPASS_POINTS[int((angle % 360) / 22.5 + 0.5) % 16]
    return f"{angle:.0f}° {point}"


# --------------------------------------------------------------------------- geometry

EARTH_RADIUS_M = 6_371_008.8

# Closer to the centre than this, a GPS fix can't give a meaningful bearing: a few metres
# of GPS error would swing it all the way round.
MIN_ARM_LENGTH_M = 10.0


def coerce_lat_lon(lat: Any, lon: Any) -> tuple[float, float] | None:
    """A usable (lat, lon) in decimal degrees, or None (missing, NaN, out of range or 0, 0)."""
    la, lo = coerce_number(lat), coerce_number(lon)
    if la is None or lo is None or math.isnan(la) or math.isnan(lo):
        return None
    if not (-90 <= la <= 90 and -180 <= lo <= 180):
        return None
    if la == 0 and lo == 0:  # no-fix placeholder, not a real position
        return None
    return la, lo


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2: degrees, 0 = North, clockwise, [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360.0


def arm_angle(centre: Any, tower: Any) -> float | None:
    """The pivot's angle from its centre to the end tower's GPS position, or None.

    ``centre`` and ``tower`` are (lat, lon) pairs (either may be None). None when either is
    missing or the tower is too close to the centre for the bearing to mean anything."""
    if not centre or not tower:
        return None
    c = coerce_lat_lon(*centre)
    t = coerce_lat_lon(*tower)
    if c is None or t is None:
        return None
    if distance_m(c[0], c[1], t[0], t[1]) < MIN_ARM_LENGTH_M:
        return None
    return bearing_deg(c[0], c[1], t[0], t[1])


# --------------------------------------------------------------------------- commands


def now_ms() -> int:
    return int(time.time() * 1000)


def build_command(
    command: str,
    target: str,
    app_key: str | None,
    *,
    params: dict | None = None,
    duration_s: int | None = None,
    ts: int | None = None,
) -> dict:
    """One command message for the Command Channel (contract section 3)."""
    return {
        "command": command,
        "target": target,
        "duration_s": duration_s,
        "params": params or {},
        "request_id": str(uuid.uuid4()),
        "app_key": app_key,
        "app": APP_NAME,
        "ts": ts if ts is not None else now_ms(),
    }


def validate_speed(value: Any, default: float) -> float:
    speed = coerce_number(value)
    if speed is None:
        speed = default
    if not 1.0 <= speed <= 100.0:
        raise ValueError("speed must be 1-100 %")
    return round(speed, 1)


def validate_angle(value: Any) -> float:
    angle = coerce_number(value)
    if angle is None or not 0.0 <= angle <= 360.0:
        raise ValueError("stop angle must be 0-360°")
    return round(angle % 360.0, 1)


def validate_hours(value: Any, max_hours: float) -> float:
    hours = coerce_number(value)
    if hours is None or hours <= 0:
        raise ValueError("run time must be more than 0 hours")
    if max_hours and hours > max_hours:
        raise ValueError(f"run time is over the {max_hours:g} h maximum")
    return hours


def start_request(
    direction: Any,
    speed: Any,
    end_mode: Any,
    stop_angle: Any,
    run_hours: Any,
    *,
    default_speed: float,
    max_hours: float,
) -> tuple[dict, int | None]:
    """(params, duration_s) for a start, from the operator's inputs. Raises ValueError."""
    direction = str(direction).lower() if direction else FORWARD
    if direction not in DIRECTIONS:
        raise ValueError("direction must be forward or reverse")
    speed_percent = validate_speed(speed, default_speed)
    end_mode = end_mode or END_UNTIL_STOPPED
    if end_mode not in END_MODES:
        raise ValueError(f"unknown end mode {end_mode!r}")
    stop_angle_deg = validate_angle(stop_angle) if end_mode == END_AT_ANGLE else None
    duration_s = (
        round(validate_hours(run_hours, max_hours) * 3600)
        if end_mode == END_AFTER_TIME
        else None
    )
    params = {
        "direction": direction,
        "speed_percent": speed_percent,
        "stop_angle_deg": stop_angle_deg,
    }
    return params, duration_s


def command_label(command: dict) -> str:
    if command.get("command") == "stop":
        return "Stop"
    params = command.get("params") or {}
    text = f"Start {str(params.get('direction') or '').capitalize()} at {params.get('speed_percent', 0):g} %"
    if params.get("stop_angle_deg") is not None:
        text += f", stop at {params['stop_angle_deg']:g}°"
    elif command.get("duration_s"):
        text += f", for {command['duration_s'] / 3600:g} h"
    return text


def reply_text(reply: dict, label: str) -> str:
    if reply.get("ok"):
        return f"{label}: accepted by the controller"
    return f"{label}: refused by the controller ({reply.get('error') or 'no reason given'})"


# --------------------------------------------------------------------------- schedules
#
# A schedule is a one-off plan for one run of the pivot: an ordered list of steps, each a
# direction, wet (supply pump on) or dry, a speed and an end (a stop angle or a run time),
# with an optional start delay. A Simple schedule is one step to an angle at the configured
# speed and wet setting. The edge runs it; this app keeps the operator's side of it (start,
# pause, resume, end) and, until the edge reports its own progress, estimates it.

SIMPLE = "simple"
DETAILED = "detailed"
SCHEDULE_MODES = (SIMPLE, DETAILED)

END_ANGLE = "angle"
END_TIME = "time"
STEP_ENDS = (END_ANGLE, END_TIME)

SCHEDULE_RUNNING = "running"
SCHEDULE_PAUSED = "paused"
SCHEDULE_COMPLETED = "completed"
SCHEDULE_ENDED = "ended"

HISTORY_LENGTH = 5
MAX_STEPS = 50

# An angle step counts as reached this close to its stop angle (GPS jitter).
ANGLE_TOLERANCE_DEG = 1.0


class ScheduleInvalid(ValueError):
    """A schedule that can't run. ``errors`` are the operator-facing messages, one per problem."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def normalise_step(raw: Any) -> dict:
    """A step as sent by the page, with every key present (values are not checked here)."""
    raw = raw if isinstance(raw, dict) else {}
    direction = str(raw.get("direction") or "").strip().lower() or None
    end = str(raw.get("end") or "").strip().lower() or None
    wet = raw.get("wet")
    return {
        "direction": direction,
        "wet": bool(coerce_bool(wet)) if wet is not None else True,
        "speed_percent": None
        if _blank(raw.get("speed_percent"))
        else coerce_number(raw.get("speed_percent")),
        "end": end,
        "stop_angle_deg": None
        if _blank(raw.get("stop_angle_deg"))
        else coerce_number(raw.get("stop_angle_deg")),
        "run_hours": None
        if _blank(raw.get("run_hours"))
        else coerce_number(raw.get("run_hours")),
        "delay_min": None
        if _blank(raw.get("delay_min"))
        else coerce_number(raw.get("delay_min")),
        # Kept so a value typed but not a number is reported, not silently dropped.
        "_bad": [
            k
            for k in ("speed_percent", "stop_angle_deg", "run_hours", "delay_min")
            if not _blank(raw.get(k)) and coerce_number(raw.get(k)) is None
        ],
    }


def step_errors(step: dict, max_hours: float = 0.0) -> list[str]:
    """What's wrong with one step, as messages the operator can act on (empty when valid)."""
    errors = []
    bad = step.get("_bad") or []
    if step.get("direction") not in DIRECTIONS:
        errors.append("Choose a direction (forward or reverse)")
    speed = step.get("speed_percent")
    if "speed_percent" in bad or speed is None or not 1.0 <= speed <= 100.0:
        errors.append("Speed must be 1–100 %")
    end = step.get("end")
    angle = step.get("stop_angle_deg")
    hours = step.get("run_hours")
    if end == END_ANGLE:
        if "stop_angle_deg" in bad or (angle is not None and not 0.0 <= angle <= 360.0):
            errors.append("Stop angle must be 0–360°")
        elif angle is None:
            errors.append("Choose a stop angle or a run time")
    elif end == END_TIME:
        if "run_hours" in bad:
            errors.append("Run time must be a number of hours")
        elif hours is None:
            errors.append("Choose a stop angle or a run time")
        elif hours <= 0:
            errors.append("Run time must be more than 0")
        elif max_hours and hours > max_hours:
            errors.append(f"Run time can't be over the {max_hours:g} h maximum")
    else:
        errors.append("Choose a stop angle or a run time")
    delay = step.get("delay_min")
    if "delay_min" in bad:
        errors.append("Start delay must be a number of minutes")
    elif delay is not None and delay < 0:
        errors.append("Start delay can't be negative")
    return errors


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def clean_step(step: dict) -> dict:
    """A valid step in its stored form: only the fields its end uses, numbers rounded."""
    end = step["end"]
    return {
        "direction": step["direction"],
        "wet": bool(step["wet"]),
        "speed_percent": round(float(step["speed_percent"]), 1),
        "end": end,
        "stop_angle_deg": round(float(step["stop_angle_deg"]) % 360.0, 1)
        if end == END_ANGLE
        else None,
        "run_hours": round(float(step["run_hours"]), 3) if end == END_TIME else None,
        "delay_min": round(float(step["delay_min"] or 0), 1),
    }


def validate_schedule(
    payload: Any,
    *,
    default_speed: float,
    simple_wet: bool,
    max_hours: float = 0.0,
) -> tuple[str, list[dict]]:
    """(mode, steps) from the page's request. Raises ScheduleInvalid with every problem.

    A Simple schedule is one step to an angle; its speed and wet setting always come from
    config, whatever the request says."""
    payload = payload if isinstance(payload, dict) else {}
    mode = str(payload.get("mode") or "").strip().lower()
    if mode not in SCHEDULE_MODES:
        raise ScheduleInvalid(["Unknown schedule type: choose Simple or Detailed"])
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ScheduleInvalid(["Add at least one step"])
    if mode == SIMPLE:
        raw_steps = [
            dict(
                raw_steps[0] if isinstance(raw_steps[0], dict) else {},
                speed_percent=default_speed,
                wet=simple_wet,
                end=END_ANGLE,
                run_hours=None,
                delay_min=None,
            )
        ]
    if len(raw_steps) > MAX_STEPS:
        raise ScheduleInvalid([f"A schedule can have at most {MAX_STEPS} steps"])
    steps = [normalise_step(s) for s in raw_steps]
    errors = []
    for n, step in enumerate(steps, start=1):
        for problem in step_errors(step, max_hours):
            errors.append(
                problem if mode == SIMPLE else f"Step {n}: {_lower_first(problem)}"
            )
    if errors:
        raise ScheduleInvalid(errors)
    return mode, [clean_step(s) for s in steps]


def new_schedule(
    mode: str,
    steps: list[dict],
    *,
    now: int,
    started_by: str | None = None,
    schedule_id: str | None = None,
) -> dict:
    """A schedule as stored, running from ``now``. Every key is always present."""
    return {
        "id": schedule_id or str(uuid.uuid4()),
        "mode": mode,
        "steps": steps,
        "status": SCHEDULE_RUNNING,
        "paused": False,
        "started_ts": now,
        "started_by": started_by,
        "paused_ts": None,  # when the current pause began
        "paused_ms": 0,  # total of finished pauses
        "ended_ts": None,
    }


def _clean_schedule(value: Any) -> dict | None:
    """A stored schedule, or None when it isn't one (keys outside the stored set dropped)."""
    if not isinstance(value, dict) or not value.get("id"):
        return None
    if not isinstance(value.get("steps"), list):
        return None
    base = new_schedule(
        value.get("mode") or DETAILED,
        value["steps"],
        now=int(value.get("started_ts") or 0),
        schedule_id=str(value["id"]),
    )
    base.update({k: value[k] for k in base if k in value})
    return base


def is_active(schedule: dict | None) -> bool:
    return bool(schedule) and schedule.get("status") in (
        SCHEDULE_RUNNING,
        SCHEDULE_PAUSED,
    )


def pause_schedule(schedule: dict, now: int) -> dict:
    if schedule.get("paused"):
        return schedule
    return dict(schedule, status=SCHEDULE_PAUSED, paused=True, paused_ts=now)


def resume_schedule(schedule: dict, now: int) -> dict:
    if not schedule.get("paused"):
        return schedule
    paused_for = max(0, now - int(schedule.get("paused_ts") or now))
    return dict(
        schedule,
        status=SCHEDULE_RUNNING,
        paused=False,
        paused_ts=None,
        paused_ms=int(schedule.get("paused_ms") or 0) + paused_for,
    )


def finish_schedule(schedule: dict, status: str, now: int) -> dict:
    """The schedule as history keeps it: completed (its last step done) or ended (by hand)."""
    finished = resume_schedule(schedule, now)
    return dict(finished, status=status, paused=False, ended_ts=now)


def push_history(history: Any, schedule: dict) -> list[dict]:
    """The newest HISTORY_LENGTH schedules, newest first, each once."""
    items = [
        s for s in (history if isinstance(history, list) else []) if isinstance(s, dict)
    ]
    items = [s for s in items if s.get("id") != schedule.get("id")]
    return [schedule, *items][:HISTORY_LENGTH]


def clean_history(history: Any) -> list[dict]:
    out = []
    for item in history if isinstance(history, list) else []:
        s = _clean_schedule(item)
        if s and all(o["id"] != s["id"] for o in out):
            out.append(s)
    return out[:HISTORY_LENGTH]


def paused_ms_at(schedule: dict, now: int) -> int:
    """Total time paused up to ``now``, including a pause still going."""
    total = int(schedule.get("paused_ms") or 0)
    if schedule.get("paused") and schedule.get("paused_ts"):
        total += max(0, now - int(schedule["paused_ts"]))
    return total


# --------------------------------------------------------------------------- progress
#
# The cloud's estimate of where a running schedule is, kept with the active schedule as
# ``progress``. The current step started at ``step_started_ts``; time spent paused since
# (``paused_ms_at(now) - paused_ms_at_step``) doesn't count. A step first waits out its start
# delay; then a time step runs its run time, and an angle step runs until the pivot has
# turned, in the step's direction, from where it was when the step began to the stop angle.
# The turn is accumulated from each reading's signed change, so GPS jitter cancels out and a
# run through North (359° -> 0°) counts as moving on.


def empty_progress(now: int, schedule: dict, angle: float | None) -> dict:
    return {
        "step_index": 0,
        "step_started_ts": now,
        "paused_ms_at_step": paused_ms_at(schedule, now),
        "start_angle_deg": angle,
        "last_angle_deg": angle,
        "turned_deg": 0.0,
        "waiting": False,
        "fraction": 0.0,
        "remaining_deg": None,
        "remaining_s": None,
        "estimated": True,
        "updated_ts": now,
    }


def angle_needed(start: float, stop: float, direction: str) -> float:
    """Degrees the pivot turns from ``start`` to ``stop`` in ``direction`` (forward = clockwise)."""
    if direction == REVERSE:
        return (start - stop) % 360.0
    return (stop - start) % 360.0


def signed_turn(previous: float, current: float, direction: str) -> float:
    """The change from one angle reading to the next, positive in the step's direction."""
    delta = (current - previous + 180.0) % 360.0 - 180.0
    return -delta if direction == REVERSE else delta


def estimate_progress(
    schedule: dict, progress: dict | None, angle: float | None, now: int
) -> tuple[dict, bool]:
    """(progress, done): the estimate brought up to ``now``. ``done`` once the last step is."""
    steps = schedule.get("steps") or []
    if not steps:
        return empty_progress(now, schedule, angle), True
    if not isinstance(progress, dict) or "step_index" not in progress:
        progress = empty_progress(
            int(schedule.get("started_ts") or now), schedule, angle
        )
    p = dict(progress)
    if schedule.get("paused"):
        return p, False
    paused_now = paused_ms_at(schedule, now)

    while True:
        index = int(p.get("step_index") or 0)
        if index >= len(steps):
            return p, True
        step = steps[index]
        active_ms = max(
            0,
            now
            - int(p.get("step_started_ts") or now)
            - (paused_now - int(p.get("paused_ms_at_step") or 0)),
        )
        delay_ms = float(step.get("delay_min") or 0) * 60_000
        if active_ms < delay_ms:
            p.update(
                waiting=True,
                fraction=0.0,
                remaining_s=round((delay_ms - active_ms) / 1000),
                remaining_deg=None,
                last_angle_deg=angle if angle is not None else p.get("last_angle_deg"),
                start_angle_deg=angle
                if angle is not None
                else p.get("start_angle_deg"),
                turned_deg=0.0,
                updated_ts=now,
            )
            return p, False

        finished_at = None
        if step.get("end") == END_TIME:
            run_ms = float(step.get("run_hours") or 0) * 3_600_000
            ran_ms = active_ms - delay_ms
            p.update(
                waiting=False,
                fraction=min(1.0, ran_ms / run_ms) if run_ms else 1.0,
                remaining_s=max(0, round((run_ms - ran_ms) / 1000)),
                remaining_deg=None,
            )
            if ran_ms >= run_ms:
                finished_at = int(now - (ran_ms - run_ms))
        else:
            start = p.get("start_angle_deg")
            last = p.get("last_angle_deg")
            turned = float(p.get("turned_deg") or 0.0)
            if start is None:
                start = last = angle  # first reading of this step
            elif angle is not None and last is not None:
                turned = max(0.0, turned + signed_turn(last, angle, step["direction"]))
            if angle is not None:
                last = angle
            p.update(
                start_angle_deg=start, last_angle_deg=last, turned_deg=round(turned, 2)
            )
            if start is None:
                p.update(
                    waiting=False, fraction=None, remaining_deg=None, remaining_s=None
                )
            else:
                need = angle_needed(
                    start, float(step["stop_angle_deg"]), step["direction"]
                )
                p.update(
                    waiting=False,
                    fraction=1.0
                    if need <= ANGLE_TOLERANCE_DEG
                    else min(1.0, turned / need),
                    remaining_deg=round(max(0.0, need - turned), 1),
                    remaining_s=None,
                )
                if need - turned <= ANGLE_TOLERANCE_DEG:
                    finished_at = now
        p["updated_ts"] = now
        if finished_at is None:
            return p, False
        # Next step, from where this one finished.
        p.update(
            step_index=index + 1,
            step_started_ts=finished_at,
            paused_ms_at_step=paused_now,
            start_angle_deg=angle,
            last_angle_deg=angle,
            turned_deg=0.0,
            fraction=0.0,
        )


def edge_progress(
    reported: Any, schedule: dict, now: int
) -> tuple[dict, str | None] | None:
    """Progress as the edge reports it, with its status, or None when it reports nothing
    usable for this schedule.

    The edge publishes ``{"schedule_id", "step_index", "step_progress", "status"}`` at the
    configured Schedule State Path; ``schedule_id`` and ``step_progress`` are optional."""
    if not isinstance(reported, dict):
        return None
    sid = reported.get("schedule_id")
    if sid and sid != schedule.get("id"):
        return None
    index = coerce_number(reported.get("step_index"))
    if index is None:
        return None
    fraction = coerce_number(reported.get("step_progress"))
    status = str(reported.get("status") or "").lower() or None
    progress = empty_progress(now, schedule, None)
    progress.update(
        step_index=int(index),
        fraction=None if fraction is None else max(0.0, min(1.0, fraction)),
        waiting=status == "waiting",
        estimated=False,
        step_started_ts=None,
        paused_ms_at_step=None,
    )
    return progress, status


# --------------------------------------------------------------------------- settings


def step_for_edge(step: dict, pump_linked: bool) -> dict:
    """One step as the edge runs it: the start command's fields, plus wet and delay."""
    return {
        "direction": step["direction"],
        "speed_percent": step["speed_percent"],
        "stop_angle_deg": step["stop_angle_deg"] if step["end"] == END_ANGLE else None,
        "duration_s": round(float(step["run_hours"]) * 3600)
        if step["end"] == END_TIME
        else None,
        "delay_s": round(float(step.get("delay_min") or 0) * 60),
        "wet": bool(step["wet"]),
        # The edge runs the supply pump through a wet step and stops it for a dry one.
        "supply_pump_on": bool(step["wet"]) and pump_linked,
    }


def schedule_for_edge(schedule: dict | None, pump_linked: bool) -> dict | None:
    if not schedule:
        return None
    return {
        "id": schedule["id"],
        "mode": schedule["mode"],
        "status": schedule["status"],
        "paused": bool(schedule.get("paused")),
        "started_ts": schedule.get("started_ts"),
        "paused_ts": schedule.get("paused_ts"),
        "paused_ms": schedule.get("paused_ms") or 0,
        "steps": [step_for_edge(s, pump_linked) for s in schedule.get("steps") or []],
    }


def settings_payload(
    *,
    targets: dict[str, str],
    cycle_s: float,
    default_speed: float,
    max_run_hours: float,
    tz_name: str,
    schedule: dict | None,
    history: list[dict],
    supply_pump: dict | None = None,
    ts: int | None = None,
) -> dict:
    """This app's entry in the Settings Channel aggregate (under its app key)."""
    pump_linked = bool(
        supply_pump
        and not supply_pump_problem(supply_pump)
        and supply_pump["start_with_pivot"]
    )
    return {
        "app": APP_NAME,
        "schema": SETTINGS_SCHEMA,
        "targets": targets,
        "percent_timer_cycle_s": cycle_s,
        "default_speed_percent": default_speed,
        "max_run_s": round(max_run_hours * 3600) if max_run_hours else None,
        "timezone": tz_name,
        "schedule": schedule_for_edge(schedule, pump_linked),
        # The operator's side of the schedules, as stored: the page's source of truth.
        "schedule_state": {"active": schedule, "history": history},
        "supply_pump": supply_pump,
        "updated_ts": ts if ts is not None else now_ms(),
    }


def schedule_from_settings(entry: Any) -> tuple[dict | None, list[dict]] | None:
    """(active, history) from this app's settings entry, or None when it has none stored."""
    if not isinstance(entry, dict) or not isinstance(entry.get("schedule_state"), dict):
        return None
    state = entry["schedule_state"]
    active = _clean_schedule(state.get("active"))
    return (active if is_active(active) else None), clean_history(state.get("history"))


def step_text(step: dict) -> str:
    """One step in words, e.g. 'Forward, wet, 50 %, to 180°, after 15 min'."""
    text = (
        f"{str(step.get('direction') or '').capitalize()}, "
        f"{'wet' if step.get('wet') else 'dry'}, {float(step.get('speed_percent') or 0):g} %"
    )
    if step.get("end") == END_TIME:
        text += f", for {float(step.get('run_hours') or 0):g} h"
    else:
        text += f", to {float(step.get('stop_angle_deg') or 0):g}°"
    if step.get("delay_min"):
        text += f", after {float(step['delay_min']):g} min"
    return text


# --------------------------------------------------------------------------- supply pump
#
# A pump on another device (a Pump Control install) that supplies the pivot's water. The
# edge controller starts and stops it with the pivot's runs; this app only tells the edge
# which pump that is (settings, and the start command's params) and shows the pump's state
# as its Pump Control install reports it in tags p_<target>_<field>.

PUMP_RUNNING = "Running"
PUMP_STOPPED = "Stopped"
PUMP_UNKNOWN = "Unknown"

_SLUG_RE = re.compile(r"[^A-Za-z0-9_]+")


def pump_tag_key(target: str, field: str) -> str:
    """The Pump Control tag of one pump's field: p_<target, made tag-safe>_<field>."""
    slug = _SLUG_RE.sub("_", str(target or "").strip()).strip("_") or "pump"
    return f"p_{slug}_{field}"


def supply_pump_link(
    device_id: Any,
    app_key: Any,
    target: Any,
    *,
    with_pivot: Any,
    lead_s: Any,
    run_on_s: Any,
) -> dict | None:
    """The supply pump as the edge needs it, or None when no pump is linked.

    A link missing its app key or target is still returned (the page says what is missing),
    so the edge can see a half-set link rather than none.
    """
    device = str(device_id).strip() if device_id not in (None, "") else ""
    app_key = str(app_key or "").strip()
    target = str(target or "").strip()
    if not (device or app_key or target):
        return None
    lead = coerce_number(lead_s)
    run_on = coerce_number(run_on_s)
    return {
        "device_id": device or None,
        "app_key": app_key or None,
        "target": target or None,
        "start_with_pivot": bool(with_pivot) if with_pivot is not None else True,
        "lead_s": max(0, round(lead)) if lead is not None else 0,
        "run_on_s": max(0, round(run_on)) if run_on is not None else 0,
    }


def supply_pump_problem(link: dict | None) -> str | None:
    """What a half-set link is missing, or None when it is complete (or absent)."""
    if not link:
        return None
    missing = [
        label
        for key, label in (
            ("device_id", "Supply Pump Device"),
            ("app_key", "Supply Pump App Key"),
            ("target", "Supply Pump Target ID"),
        )
        if not link.get(key)
    ]
    if missing:
        return "Supply pump link incomplete: set " + ", ".join(missing)
    return None


def supply_pump_state(tags: dict | None, target: str) -> dict:
    """The pump's reported state from its Pump Control install's tags.

    ``running`` is True / False only when the install reports a boolean; anything else
    (no tags, not reported yet, unreadable) is Unknown.
    """
    tags = tags or {}
    running = tags.get(pump_tag_key(target, "running"))
    running = running if isinstance(running, bool) else None
    state = (
        PUMP_RUNNING
        if running is True
        else PUMP_STOPPED
        if running is False
        else PUMP_UNKNOWN
    )
    name = tags.get(pump_tag_key(target, "name"))
    return {
        "running": running,
        "state": state,
        "name": str(name) if name else None,
        "last_started": coerce_number(tags.get(pump_tag_key(target, "last_started"))),
        "last_stopped": coerce_number(tags.get(pump_tag_key(target, "last_stopped"))),
    }


def supply_pump_mode_text(link: dict | None) -> str | None:
    """How the pump follows the pivot, e.g. 'Starts with the pivot, 30 s lead, 60 s run-on'."""
    if not link:
        return None
    if not link.get("start_with_pivot"):
        return "Not started with the pivot"
    text = "Starts with the pivot"
    if link.get("lead_s"):
        text += f", {link['lead_s']} s lead"
    if link.get("run_on_s"):
        text += f", {link['run_on_s']} s run-on"
    return text
