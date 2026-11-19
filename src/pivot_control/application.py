"""Pivot Control: remote control and monitoring of a centre pivot through an edge controller.

The edge controller is the source of truth: it drives the outputs, runs the schedules and
reports the outputs' state. This app shows that reported state, sends Start / Stop commands
on the Command Channel and keeps the settings the edge enforces (defaults, limits and the
operator's schedules) in the Settings Channel aggregate under its app key.
"""

import logging
import re
from typing import Any

from pydoover import ui
from pydoover.models import (
    AggregateUpdateEvent,
    DeploymentEvent,
    MessageCreateEvent,
    ScheduleEvent,
)
from pydoover.processor import Application

from . import model
from .app_config import POSITION_FROM_LOCATION, PivotControlConfig
from .app_notifications import PivotControlNotifications
from .app_tags import PivotControlTags
from .app_ui import PivotControlUI

log = logging.getLogger(__name__)

# A safety trip within this long of the pivot stopping still counts as "while running": the
# controller may report the stop before (or with) the safety input that caused it.
SAFETY_STOP_GRACE_MS = 120_000

# Inputs read by message path: (config field, raw tag, kind).
INPUTS = (
    ("run_state_path", "run_output", "bool"),
    ("forward_state_path", "forward_output", "bool"),
    ("reverse_state_path", "reverse_output", "bool"),
    ("speed_state_path", "reported_speed", "number"),
    ("safety_path", "safety_input", "number"),
    ("pressure_path", "pressure_input", "number"),
)

SCHEDULE_RE = re.compile(
    r"^sched_(\d)_(enabled|start|direction|speed|end|stop_angle|hours)$"
)


class PivotControlApplication(Application):
    config: PivotControlConfig
    tags: PivotControlTags
    ui: PivotControlUI
    notifications: PivotControlNotifications

    config_cls = PivotControlConfig
    tags_cls = PivotControlTags
    ui_cls = PivotControlUI
    notifications_cls = PivotControlNotifications

    # ------------------------------------------------------------------ setup

    async def pre_hook_filter(self, event):
        # Aggregate updates matter only on tag_values (the angle source's tags); every other
        # channel is read from its messages.
        if isinstance(event, AggregateUpdateEvent):
            return event.channel.name == "tag_values"
        return True

    async def setup(self):
        self._paths: dict[str, tuple[str, list[str]] | None] = {}
        for field, _tag, _kind in INPUTS:
            raw = self._cfg(field, "")
            parsed = model.parse_message_path(raw)
            if raw and parsed is None:
                log.warning(
                    "%s %r is not a '$channel.path' message path: ignored", field, raw
                )
            self._paths[field] = parsed

    def _cfg(self, field: str, default: Any = None) -> Any:
        """A config value, or the default when it is missing or null (never raises)."""
        try:
            value = getattr(self.config, field).value
        except (AttributeError, ValueError):
            return default
        return default if value is None else value

    def _num(self, field: str, default: float) -> float:
        value = model.coerce_number(self._cfg(field, default))
        return default if value is None else value

    def _command_channel(self) -> str:
        return self._cfg("command_channel", "") or "io_commands"

    def _settings_channel(self) -> str:
        return self._cfg("settings_channel", "") or "control_settings"

    def _tz(self) -> str:
        return self._cfg("dv_proc_timezone", "") or "Australia/Brisbane"

    def _default_speed(self) -> float:
        return min(100.0, max(1.0, self._num("default_speed", 50.0)))

    def _max_hours(self) -> float:
        return max(0.0, self._num("max_run_hours", 0.0))

    def _angle_source(self) -> tuple[str | None, str | None]:
        try:
            source = self.config.angle_source
            return source.app_name.value or None, source.tag_name.value or None
        except (AttributeError, ValueError):
            return None, None

    async def _set(self, name: str, value):
        tag = getattr(self.tags, name)
        if tag.value != value:
            await tag.set(value)

    # ------------------------------------------------------------------ events

    async def on_deployment(self, event: DeploymentEvent):
        await self._publish_settings(self._schedules())
        await self._evaluate()

    async def on_schedule(self, event: ScheduleEvent):
        await self._evaluate()

    async def on_aggregate_update(self, event: AggregateUpdateEvent):
        # tag_values only (pre_hook_filter); the angle is re-read in _evaluate. Only the
        # angle source's and the GPS app's tags matter: skip everything else (including this
        # app's own tag writes).
        watched = self._gps_apps() | {self._angle_source()[0]}
        watched.discard(None)
        changed = getattr(getattr(event, "request_data", None), "data", None) or {}
        if not watched or not watched.intersection(changed):
            return
        await self._evaluate()

    async def on_message_create(self, event: MessageCreateEvent):
        channel = event.channel.name
        data = event.message.data or {}
        if channel == self._command_channel():
            await self._on_command_channel(data)
        elif channel != "ui_cmds":
            await self._read_inputs(channel, data)
        await self._evaluate()

    async def _read_inputs(self, channel: str, data: dict):
        for field, tag, kind in INPUTS:
            parsed = self._paths.get(field)
            if not parsed or parsed[0] != channel:
                continue
            raw = model.extract_path_value(data, parsed[1])
            if raw is None:
                continue  # this message doesn't carry it: keep the last value
            value = (
                model.coerce_bool(raw) if kind == "bool" else model.coerce_number(raw)
            )
            if value is None:
                log.warning("%s at %s is not usable: %r", tag, ".".join(parsed[1]), raw)
                continue
            await self._set(tag, value)

    async def _on_command_channel(self, data: dict):
        """A controller's reply to one of our commands: {"request_id", "ok", "error"}."""
        if "command" in data or "request_id" not in data or "ok" not in data:
            return  # a command (ours or another app's), not a reply
        pending = self.tags.pending_command.value
        if not pending or pending.get("request_id") != data.get("request_id"):
            return
        label = model.command_label(pending)
        await self._set("last_command", model.reply_text(data, label))
        if not data.get("ok"):
            await self._set("pending_command", None)
            await self._set("command_message", model.reply_text(data, label))
            await self._set("command_warning_hidden", False)

    # ------------------------------------------------------------------ state

    async def _evaluate(self):
        now = model.now_ms()
        await self._update_angle()

        prev_state = self.tags.state.value
        prev_safety = self.tags.safety_ok.value

        forward_on = (
            self.tags.forward_output.value
            if self._paths.get("forward_state_path")
            else None
        )
        reverse_on = (
            self.tags.reverse_output.value
            if self._paths.get("reverse_state_path")
            else None
        )
        has_reading = forward_on is not None or reverse_on is not None
        state, direction = model.derive_state(forward_on, reverse_on)
        if not has_reading:
            state = None  # nothing reported yet: no state, not "unknown"

        if state != prev_state:
            if state == model.RUNNING:
                await self._set("running_since", now)
            if state == model.RUNNING and prev_state is not None:
                await self._set("last_started", now)
            elif state == model.STOPPED and prev_state == model.RUNNING:
                await self._set("last_stopped", now)
        await self._set("state", state)
        await self._set("direction", direction)
        await self._set("status", model.status_text(state, direction, has_reading))

        # Speed: as reported, else the last confirmed start's while running.
        if self._paths.get("speed_state_path"):
            speed = self.tags.reported_speed.value
        else:
            speed = self.tags.started_speed.value if state == model.RUNNING else None
        await self._set("speed_percent", speed)

        running = state == model.RUNNING
        was_running = prev_state == model.RUNNING
        last_stopped = self.tags.last_stopped.value or 0
        await self._update_safety(
            prev_safety,
            running or was_running or now - last_stopped < SAFETY_STOP_GRACE_MS,
        )
        await self._update_pressure(running, now)
        await self._update_pending(state, direction, now)
        await self._update_schedule_summaries(now)

    def _tag_ref(self, field: str) -> tuple[str | None, str | None]:
        """An {app_name, tag_name} config object, each part falling back to its default."""
        source = getattr(self.config, field, None)
        parts = []
        for part in ("app_name", "tag_name"):
            element = getattr(source, part, None)
            try:
                value = element.value
            except ValueError:  # not in the deployment config
                value = getattr(element, "default", None)
            except AttributeError:
                value = None
            parts.append(value or None)
        return parts[0], parts[1]

    def _gps_apps(self) -> set[str]:
        """Apps whose tags carry the GPS position (only in the GPS tags position source)."""
        if self._cfg("position_source", "") == POSITION_FROM_LOCATION:
            return set()
        apps = {
            self._tag_ref("latitude_source")[0],
            self._tag_ref("longitude_source")[0],
        }
        return {a for a in apps if a}

    def _other_tag(self, ref: tuple[str | None, str | None]):
        app_name, tag_name = ref
        if not (app_name and tag_name):
            return None
        return self.tag_manager.get_tag(tag_name, app_key=app_name)

    def _gps_angle(self) -> float | None:
        """The angle from the pivot centre to the end tower's GPS position, when both are set."""
        if not self._gps_apps():
            return None
        centre = (self._cfg("pivot_centre_lat"), self._cfg("pivot_centre_lon"))
        tower = (
            self._other_tag(self._tag_ref("latitude_source")),
            self._other_tag(self._tag_ref("longitude_source")),
        )
        return model.arm_angle(centre, tower)

    async def _update_angle(self):
        app_name, tag_name = self._angle_source()
        angle = None
        if app_name and tag_name:
            angle = model.normalise_angle(
                self.tag_manager.get_tag(tag_name, app_key=app_name)
            )
        if angle is None:
            angle = self._gps_angle()
        if angle is not None:
            angle = round(angle, 1)
        await self._set("angle_deg", angle)
        await self._set("heading", model.heading_text(angle))

    async def _update_safety(self, prev_safety: bool | None, running: bool):
        if not self._paths.get("safety_path"):
            safety_ok = None
        else:
            raw = self.tags.safety_input.value
            ok_value = self._num("safety_ok_value", 1.0)
            safety_ok = None if raw is None else abs(raw - ok_value) < 1e-6
        await self._set("safety_ok", safety_ok)
        await self._set(
            "safety_text",
            None if safety_ok is None else ("OK" if safety_ok else "Tripped"),
        )
        await self._set("safety_warning_hidden", safety_ok is not False)

        if safety_ok is False:
            if (
                prev_safety is not False
                and running
                and not self.tags.safety_alert_active.value
            ):
                await self._set("safety_alert_active", True)
                await self.notifications.safety_tripped.send()
        elif safety_ok is True:
            await self._set("safety_alert_active", False)

    async def _update_pressure(self, running: bool, now: int):
        pressure = None
        if self._paths.get("pressure_path"):
            pressure = model.scale_pressure(
                self.tags.pressure_input.value,
                self._num("pressure_input_min", 4.0),
                self._num("pressure_input_max", 20.0),
                self._num("pressure_min", 0.0),
                self._num("pressure_max", 100.0),
            )
        if pressure is not None:
            pressure = round(pressure, 2)
        await self._set("pressure", pressure)

        threshold = model.coerce_number(self._cfg("low_pressure_threshold", None))
        started = self.tags.running_since.value
        delay_ms = self._num("low_pressure_delay_s", 300.0) * 1000
        low = (
            threshold is not None
            and pressure is not None
            and running
            and started is not None
            and now - started >= delay_ms
            and pressure < threshold
        )
        if low and not self.tags.low_pressure_active.value:
            await self._set("low_pressure_active", True)
            units = self._cfg("pressure_units", "") or ""
            await self.notifications.low_pressure.send(
                f"Line pressure is {pressure:g} {units} while the pivot is running "
                f"(threshold {threshold:g} {units})".replace("  ", " ")
            )
        elif not low and (
            pressure is None
            or not running
            or threshold is None
            or pressure >= threshold
        ):
            await self._set("low_pressure_active", False)

    async def _update_pending(self, state: str | None, direction: str | None, now: int):
        pending = self.tags.pending_command.value
        if not pending:
            return
        want_state, want_direction = model.expected_state(pending)
        label = model.command_label(pending)
        if state == want_state and (
            want_direction is None or direction == want_direction
        ):
            await self._set("pending_command", None)
            await self._set("command_warning_hidden", True)
            await self._set("command_message", "")
            await self._set("last_command", f"{label}: confirmed")
            return
        if pending.get("timed_out"):
            return
        timeout_ms = self._num("confirm_timeout_s", 120.0) * 1000
        if now - int(pending.get("ts") or now) >= timeout_ms:
            pending = dict(pending, timed_out=True)
            await self._set("pending_command", pending)
            text = f"{label} was not confirmed: the pivot still reports {self.tags.status.value}"
            await self._set("command_message", text)
            await self._set("command_warning_hidden", False)
            await self._set("last_command", f"{label}: not confirmed")
            await self.notifications.command_not_confirmed.send(text)

    # ------------------------------------------------------------------ commands

    def _ui_value(self, name: str, default=None):
        try:
            return self.ui_manager.get_value(name)
        except (KeyError, AttributeError):
            return default

    async def _send(self, command: dict):
        await self.api.create_message(self._command_channel(), command)
        await self._set("pending_command", command)
        label = model.command_label(command)
        await self._set("last_command", f"{label}: sent")
        await self._set(
            "command_message", f"{label}: sent, waiting for the pivot to confirm"
        )
        await self._set("command_warning_hidden", False)
        log.info("sent %s", command)

    @ui.handler("start", auto_update=False)
    async def on_start(self, ctx, _value):
        try:
            params, duration_s = model.start_request(
                self._ui_value("start_direction", model.FORWARD),
                self._ui_value("start_speed", self._default_speed()),
                self._ui_value("start_end", model.END_UNTIL_STOPPED),
                self._ui_value("start_stop_angle"),
                self._ui_value("start_hours"),
                default_speed=self._default_speed(),
                max_hours=self._max_hours(),
            )
        except ValueError as e:
            await self._set("last_command", f"Start not sent: {e}")
            await self._set("command_message", f"Start not sent: {e}")
            await self._set("command_warning_hidden", False)
            return {"sent": False, "error": str(e)}
        target = self._cfg("run_target", "") or "run"
        command = model.build_command(
            "start", target, self.app_key, params=params, duration_s=duration_s
        )
        await self._set("started_speed", params["speed_percent"])
        await self._send(command)
        return {"sent": True, "request_id": command["request_id"]}

    @ui.handler("stop", auto_update=False)
    async def on_stop(self, ctx, _value):
        target = self._cfg("run_target", "") or "run"
        command = model.build_command("stop", target, self.app_key)
        await self._send(command)
        return {"sent": True, "request_id": command["request_id"]}

    # ------------------------------------------------------------------ schedules

    def _schedules(self) -> list[dict]:
        return model.normalise_schedules(
            self.tags.schedules.value, self._default_speed()
        )

    @ui.handler(SCHEDULE_RE)
    async def on_schedule_edit(self, ctx, value):
        match = SCHEDULE_RE.match(ctx.method)
        slot, field = int(match.group(1)), match.group(2)
        schedules = self._schedules()
        if not 1 <= slot <= len(schedules):
            raise ValueError(f"no schedule slot {slot}")
        # Raises ValueError for a bad value: the site shows the command as failed and the
        # input keeps its previous value (auto_update only runs on success).
        schedules[slot - 1] = model.apply_schedule_edit(
            schedules[slot - 1], field, value
        )
        await self._set("schedules", schedules)
        await self._publish_settings(schedules)
        await self._update_schedule_summaries(model.now_ms())

    async def _update_schedule_summaries(self, now: int):
        tz = self._tz()
        for s in self._schedules():
            await self._set(
                f"sched_{s['slot']}_summary", model.schedule_summary(s, tz, now)
            )

    async def _publish_settings(self, schedules: list[dict]):
        if not self.app_key:
            return
        payload = model.settings_payload(
            targets={
                "run": self._cfg("run_target", "") or "run",
                "forward": self._cfg("forward_target", "") or "forward",
                "reverse": self._cfg("reverse_target", "") or "reverse",
            },
            cycle_s=self._num("cycle_s", 60.0),
            default_speed=self._default_speed(),
            max_run_hours=self._max_hours(),
            tz_name=self._tz(),
            schedules=schedules,
        )
        # Replace only this app's key: other apps' settings in the aggregate are kept.
        await self.api.update_channel_aggregate(
            self._settings_channel(),
            {self.app_key: payload},
            replace_keys=[self.app_key],
        )
