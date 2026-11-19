"""The pivot as the app sees it: pure functions, no IO.

Inputs arrive as raw signals at configured message paths (``$channel.path``); commands go out
as messages on the Command Channel; the settings the edge enforces (defaults, limits and the
schedules) go to the Settings Channel aggregate under the app's key. See README.md.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

SETTINGS_SCHEMA = 1
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

SCHEDULE_SLOTS = 4

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
    if number is None or number != number:  # NaN
        return None
    return number % 360.0


def heading_text(angle: float | None) -> str | None:
    if angle is None:
        return None
    point = COMPASS_POINTS[int((angle % 360) / 22.5 + 0.5) % 16]
    return f"{angle:.0f}° {point}"


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
        int(round(validate_hours(run_hours, max_hours) * 3600))
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

SCHEDULE_FIELDS = (
    "enabled",
    "start",
    "direction",
    "speed",
    "end",
    "stop_angle",
    "hours",
)


def empty_schedule(slot: int, default_speed: float) -> dict:
    return {
        "slot": slot,
        "enabled": False,
        "start_ts": None,
        "direction": FORWARD,
        "speed_percent": default_speed,
        "end_mode": END_UNTIL_STOPPED,
        "stop_angle_deg": None,
        "run_hours": None,
    }


def normalise_schedules(value: Any, default_speed: float) -> list[dict]:
    """Exactly SCHEDULE_SLOTS slots, whatever the tag held."""
    by_slot = {}
    for item in value if isinstance(value, list) else []:
        if isinstance(item, dict) and isinstance(item.get("slot"), int):
            by_slot[item["slot"]] = item
    out = []
    for slot in range(1, SCHEDULE_SLOTS + 1):
        base = empty_schedule(slot, default_speed)
        base.update({k: v for k, v in (by_slot.get(slot) or {}).items() if k in base})
        out.append(base)
    return out


def apply_schedule_edit(schedule: dict, field: str, value: Any) -> dict:
    """A schedule slot with one operator edit applied. Raises ValueError for a bad value."""
    s = dict(schedule)
    if field == "enabled":
        s["enabled"] = bool(coerce_bool(value))
    elif field == "start":
        number = coerce_number(value)
        s["start_ts"] = int(number) if number is not None else None
    elif field == "direction":
        direction = str(value or "").lower()
        if direction not in DIRECTIONS:
            raise ValueError("direction must be forward or reverse")
        s["direction"] = direction
    elif field == "speed":
        s["speed_percent"] = validate_speed(value, s.get("speed_percent") or 50.0)
    elif field == "end":
        if value not in END_MODES:
            raise ValueError(f"unknown end mode {value!r}")
        s["end_mode"] = value
    elif field == "stop_angle":
        s["stop_angle_deg"] = None if value in (None, "") else validate_angle(value)
    elif field == "hours":
        s["run_hours"] = None if value in (None, "") else validate_hours(value, 0)
    else:
        raise ValueError(f"unknown schedule field {field!r}")
    return s


def schedule_problem(s: dict) -> str | None:
    """Why an enabled schedule can't run, or None."""
    if s.get("start_ts") is None:
        return "no start time"
    if s.get("end_mode") == END_AT_ANGLE and s.get("stop_angle_deg") is None:
        return "no stop angle"
    if s.get("end_mode") == END_AFTER_TIME and not s.get("run_hours"):
        return "no run time"
    return None


def local_time(ts_ms: int | None, tz_name: str) -> datetime | None:
    if ts_ms is None:
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).astimezone(_zone(tz_name))


def _zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "Australia/Brisbane")
    except Exception:
        return ZoneInfo("Australia/Brisbane")


def schedule_for_edge(s: dict, tz_name: str, max_hours: float) -> dict:
    """One schedule as the edge runs it: the start command's fields, plus when."""
    start = local_time(s.get("start_ts"), tz_name)
    duration_s = None
    if s.get("end_mode") == END_AFTER_TIME and s.get("run_hours"):
        hours = float(s["run_hours"])
        if max_hours:
            hours = min(hours, max_hours)
        duration_s = int(round(hours * 3600))
    problem = schedule_problem(s)
    return {
        "slot": s["slot"],
        "enabled": bool(s.get("enabled")) and problem is None,
        "start_ts": s.get("start_ts"),
        "start_local": start.isoformat() if start else None,
        "direction": s.get("direction") or FORWARD,
        "speed_percent": s.get("speed_percent"),
        "stop_angle_deg": s.get("stop_angle_deg")
        if s.get("end_mode") == END_AT_ANGLE
        else None,
        "duration_s": duration_s,
    }


def schedule_summary(s: dict, tz_name: str, now: int | None = None) -> str:
    if not s.get("enabled"):
        return "Off"
    problem = schedule_problem(s)
    if problem:
        return f"Not set: {problem}"
    start = local_time(s["start_ts"], tz_name)
    text = f"{start:%a %d %b %H:%M}, {str(s.get('direction')).capitalize()} {s.get('speed_percent'):g} %"
    if s.get("end_mode") == END_AT_ANGLE:
        text += f", to {s['stop_angle_deg']:g}°"
    elif s.get("end_mode") == END_AFTER_TIME:
        text += f", {float(s['run_hours']):g} h"
    if s["start_ts"] < (now if now is not None else now_ms()):
        text += " (past)"
    return text


def settings_payload(
    *,
    targets: dict[str, str],
    cycle_s: float,
    default_speed: float,
    max_run_hours: float,
    tz_name: str,
    schedules: list[dict],
    ts: int | None = None,
) -> dict:
    """This app's entry in the Settings Channel aggregate (under its app key)."""
    return {
        "app": APP_NAME,
        "schema": SETTINGS_SCHEMA,
        "targets": targets,
        "percent_timer_cycle_s": cycle_s,
        "default_speed_percent": default_speed,
        "max_run_s": int(round(max_run_hours * 3600)) if max_run_hours else None,
        "timezone": tz_name,
        "schedules": [schedule_for_edge(s, tz_name, max_run_hours) for s in schedules],
        "updated_ts": ts if ts is not None else now_ms(),
    }
