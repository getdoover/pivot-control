"""Pivot Control: remote control and monitoring of a centre pivot through an edge controller.

The edge controller is the source of truth: it drives the outputs, runs the schedule and
reports the outputs' state. This app shows that reported state, sends Start / Stop and the
schedule's start / pause / resume / end commands on the Command Channel and keeps the
settings the edge enforces (defaults, limits and the running schedule) in the Settings
Channel aggregate under its app key. The Schedule widget on the page talks to it through
RPCs on ui_cmds.
"""

import logging
from typing import Any

from pydoover import rpc, ui
from pydoover.models import (
    AggregateUpdateEvent,
    DeploymentEvent,
    MessageCreateEvent,
    ScheduleEvent,
)
from pydoover.processor import Application
from pydoover.rpc import RPCError

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
    ("schedule_state_path", "edge_schedule_state", "object"),
)

# Outputs whose reported state is read by message path, and whose point id is their Target
# ID: (state path field, target field, default target, label).
OUTPUT_POINTS = (
    ("run_state_path", "run_target", "run", "Run"),
    ("forward_state_path", "forward_target", "forward", "Forward"),
    ("reverse_state_path", "reverse_target", "reverse", "Reverse"),
)

# Optional read-only inputs: (path field, point id, label). With an automatic address they
# count as not configured until a value has ever arrived for them.
INPUT_POINTS = (
    ("speed_state_path", "speed", "Speed"),
    ("safety_path", "safety", "Safety circuit"),
    ("pressure_path", "pressure", "Line pressure"),
    ("schedule_state_path", "schedule_state", "Schedule progress"),
)
OPTIONAL_INPUTS = frozenset(field for field, _id, _label in INPUT_POINTS)

# Tags of the four fixed schedule slots this app used to have, cleared on deployment.
LEGACY_SCHEDULE_TAGS = (
    "schedules",
    "sched_1_summary",
    "sched_2_summary",
    "sched_3_summary",
    "sched_4_summary",
)

SCHEDULE_COMMANDS = {
    "schedule_pause": "Schedule paused",
    "schedule_resume": "Schedule resumed",
    "schedule_end": "Schedule ended",
}


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
        self._schedule_state: tuple[dict | None, list[dict]] | None = None
        self._paths: dict[str, tuple[str, list[str]] | None] = {}
        # Each input's point: (point id, label, path read, automatic).
        self._points: dict[str, tuple[str, str, str, bool]] = {}
        app_key = self.app_key or ""
        for field, target_field, default, label in OUTPUT_POINTS:
            point = str(self._cfg(target_field, "") or default).strip() or default
            path, auto = model.resolve_input_path(self._cfg(field, ""), app_key, point)
            self._points[field] = (point, label, path, auto)
        for field, point, label in INPUT_POINTS:
            path, auto = model.resolve_input_path(self._cfg(field, ""), app_key, point)
            self._points[field] = (point, label, path, auto)
        for field, _tag, _kind in INPUTS:
            path = self._points[field][2]
            parsed = model.parse_message_path(path)
            if parsed is None:
                log.warning(
                    "%s %r is not a '$channel.path' message path: ignored", field, path
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

    def _simple_wet(self) -> bool:
        return bool(self._cfg("simple_wet", True))

    def _max_hours(self) -> float:
        return max(0.0, self._num("max_run_hours", 0.0))

    def _angle_source(self) -> tuple[str | None, str | None]:
        try:
            source = self.config.angle_source
            return source.app_name.value or None, source.tag_name.value or None
        except (AttributeError, ValueError):
            return None, None

    def _has_input(self, field: str) -> bool:
        """Whether an input counts as configured: an explicit path, a main input's
        automatic address, or an optional input's automatic address that has ever had a
        value (until then it looks exactly like an input left out)."""
        if not self._paths.get(field):
            return False
        point, _label, _path, auto = self._points[field]
        if auto and field in OPTIONAL_INPUTS:
            return bool((self.tags.inputs_seen.value or {}).get(point))
        return True

    async def _publish_io_points(self):
        """The io_points tag: where each output's state and each input is read from."""
        entries = {
            field: {"id": p[0], "label": p[1], "path": p[2], "auto": p[3]}
            for field, p in self._points.items()
        }
        await self._set(
            "io_points",
            model.io_points(
                [entries[f] for f, *_ in OUTPUT_POINTS],
                [entries[f] for f, *_ in INPUT_POINTS],
            ),
        )

    async def _set(self, name: str, value):
        tag = getattr(self.tags, name)
        if tag.value != value:
            await tag.set(value)

    # ------------------------------------------------------------------ events

    async def on_deployment(self, event: DeploymentEvent):
        for name in LEGACY_SCHEDULE_TAGS:
            if self.tag_manager.get_tag(name) is not None:
                await self.tag_manager.set_tag(name, None)
        await self._publish_io_points()
        await self._publish_settings(*await self._load_schedules())
        await self._evaluate()
        await self._refresh_supply_pump()

    async def on_schedule(self, event: ScheduleEvent):
        await self._publish_io_points()
        await self._evaluate()
        await self._refresh_supply_pump()

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
            if kind == "object":
                value = raw if isinstance(raw, dict) else None
            elif kind == "bool":
                value = model.coerce_bool(raw)
            else:
                value = model.coerce_number(raw)
            if value is None:
                log.warning("%s at %s is not usable: %r", tag, ".".join(parsed[1]), raw)
                continue
            await self._set(tag, value)
            point = self._points[field][0]
            seen = self.tags.inputs_seen.value or {}
            if not seen.get(point):
                await self._set("inputs_seen", dict(seen, **{point: True}))

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
            if self._has_input("forward_state_path")
            else None
        )
        reverse_on = (
            self.tags.reverse_output.value
            if self._has_input("reverse_state_path")
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
        if self._has_input("speed_state_path"):
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
        await self._update_schedule(now)

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
        await self._set("safety_hidden", not self._has_input("safety_path"))
        if not self._has_input("safety_path"):
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
        await self._set("pressure_hidden", not self._has_input("pressure_path"))
        if self._has_input("pressure_path"):
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
        pump = self._pump_with_pivot()
        if pump:
            params["supply_pump"] = pump
        target = self._cfg("run_target", "") or "run"
        command = model.build_command(
            "start", target, self.app_key, params=params, duration_s=duration_s
        )
        await self._set("started_speed", params["speed_percent"])
        await self._send(command)
        await self._refresh_supply_pump()
        return {"sent": True, "request_id": command["request_id"]}

    @ui.handler("stop", auto_update=False)
    async def on_stop(self, ctx, _value):
        target = self._cfg("run_target", "") or "run"
        pump = self._pump_with_pivot()
        command = model.build_command(
            "stop", target, self.app_key, params={"supply_pump": pump} if pump else None
        )
        await self._send(command)
        await self._refresh_supply_pump()
        return {"sent": True, "request_id": command["request_id"]}

    # ------------------------------------------------------------------ supply pump

    def _supply_pump(self) -> dict | None:
        """The configured supply pump link, or None when none is set."""
        return model.supply_pump_link(
            self._cfg("supply_pump_device"),
            self._cfg("supply_pump_app_key"),
            self._cfg("supply_pump_target"),
            with_pivot=self._cfg("supply_pump_with_pivot", True),
            lead_s=self._cfg("supply_pump_lead_s", 0),
            run_on_s=self._cfg("supply_pump_run_on_s", 0),
        )

    def _pump_with_pivot(self) -> dict | None:
        """The link to put in a start / stop command: complete and following the pivot."""
        link = self._supply_pump()
        if not link or model.supply_pump_problem(link) or not link["start_with_pivot"]:
            return None
        return link

    def _device_name(self, device_id) -> str:
        config = getattr(self, "received_deployment_config", None) or {}
        entry = (config.get("DEVICE_MAP") or {}).get(str(device_id)) or {}
        return entry.get("display_name") or entry.get("name") or f"device {device_id}"

    async def _refresh_supply_pump(self):
        """Read the supply pump's state from its Pump Control install's tags on its device.

        Anything not read (no link, no permission, nothing reported) shows as Unknown with
        the reason, never as Stopped.
        """
        link = self._supply_pump()
        await self._set("supply_pump_mode", model.supply_pump_mode_text(link))
        if not link:
            for name, value in (
                ("supply_pump_name", None),
                ("supply_pump_state", model.PUMP_UNKNOWN),
                ("supply_pump_running", None),
                ("supply_pump_warning", ""),
                ("supply_pump_warning_hidden", True),
            ):
                await self._set(name, value)
            return

        warning = model.supply_pump_problem(link) or ""
        device_id, app_key, target = link["device_id"], link["app_key"], link["target"]
        device = self._device_name(device_id) if device_id else None
        state = model.supply_pump_state(None, target or "")
        if not warning:
            try:
                agg = await self.api.fetch_channel_aggregate(
                    "tag_values", agent_id=int(device_id)
                )
                tags = (getattr(agg, "data", None) or {}).get(app_key) or {}
            except Exception as e:
                log.warning("Can't read tag_values on %s: %s", device_id, e)
                warning = (
                    f"Can't read the supply pump on {device}: add it under Devices in "
                    "this app's config"
                )
            else:
                state = model.supply_pump_state(tags, target)
                await self._set("supply_pump_checked", model.now_ms())
                if not tags:
                    warning = (
                        f"The supply pump on {device} has reported nothing yet "
                        f"(app {app_key})"
                    )

        name = state["name"] or target or "pump"
        await self._set("supply_pump_name", f"{device}: {name}" if device else name)
        await self._set("supply_pump_running", state["running"])
        await self._set("supply_pump_state", state["state"])
        if state["last_started"] is not None:
            await self._set("supply_pump_last_started", state["last_started"])
        if state["last_stopped"] is not None:
            await self._set("supply_pump_last_stopped", state["last_stopped"])
        await self._set("supply_pump_warning", warning)
        await self._set("supply_pump_warning_hidden", not warning)

    # ------------------------------------------------------------------ schedule
    #
    # The active schedule and the last five are stored in this app's Settings Channel entry
    # (``schedule_state``), which only the schedule RPCs, completion and deployment write, and
    # mirrored to the schedule_active / schedule_history tags the page reads. Every invocation
    # reads the stored copy, so a concurrent invocation that wrote stale tags is put right by
    # the next one.

    async def _load_schedules(self) -> tuple[dict | None, list[dict]]:
        if self._schedule_state is not None:
            return self._schedule_state
        stored = None
        try:
            agg = await self.api.fetch_channel_aggregate(self._settings_channel())
            entry = (getattr(agg, "data", None) or {}).get(self.app_key)
            stored = model.schedule_from_settings(entry)
        except Exception as e:  # no aggregate yet, or unreadable: fall back to the tags
            log.info("Settings not readable (%s): using the schedule tags", e)
        if stored is None:
            active = model._clean_schedule(self.tags.schedule_active.value)
            stored = (
                active if model.is_active(active) else None,
                model.clean_history(self.tags.schedule_history.value),
            )
        self._schedule_state = stored
        return stored

    async def _save_schedules(self, active: dict | None, history: list[dict]):
        """Store the schedules (settings, for the edge and as the source of truth) and
        mirror them to the tags."""
        self._schedule_state = (active, history)
        await self._publish_settings(active, history)
        await self._set_schedule_tags(active, history)

    async def _set_schedule_tags(
        self, active: dict | None, history: list[dict], progress=None
    ):
        if active is not None:
            if progress is None:
                current = self.tags.schedule_active.value or {}
                if current.get("id") == active["id"]:
                    progress = current.get("progress")
            active = dict(active, progress=progress)
        await self._set("schedule_active", active)
        await self._set("schedule_history", history)

    async def _update_schedule(self, now: int):
        """Bring the running schedule's progress up to date, and retire it once done."""
        active, history = await self._load_schedules()
        if active is None:
            await self._set_schedule_tags(None, history)
            return
        current = self.tags.schedule_active.value or {}
        progress = (
            current.get("progress") if current.get("id") == active["id"] else None
        )

        status = None
        reported = None
        if self._has_input("schedule_state_path"):
            reported = model.edge_progress(
                self.tags.edge_schedule_state.value, active, now
            )
        if reported is not None:
            progress, status = reported
            done = status in (model.SCHEDULE_COMPLETED, model.SCHEDULE_ENDED)
        else:
            progress, done = model.estimate_progress(
                active, progress, self.tags.angle_deg.value, now
            )
            if self._cfg("demo_simulate_controller", False):
                # Demo: the estimate stands in for the controller's report.
                progress["estimated"] = False
        if done:
            await self._finish(
                active,
                history,
                model.SCHEDULE_ENDED
                if status == model.SCHEDULE_ENDED
                else model.SCHEDULE_COMPLETED,
                now,
            )
            return
        await self._set_schedule_tags(active, history, progress)

    async def _finish(self, active: dict, history: list[dict], status: str, now: int):
        finished = model.finish_schedule(active, status, now)
        await self._save_schedules(None, model.push_history(history, finished))
        await self._set(
            "last_command",
            "Schedule completed"
            if status == model.SCHEDULE_COMPLETED
            else "Schedule ended",
        )

    async def _send_schedule_command(self, verb: str, params: dict):
        """A schedule command on the Command Channel. Not tracked as pending: the reported
        outputs can't confirm a schedule change on their own."""
        command = model.build_command(
            verb, self._cfg("run_target", "") or "run", self.app_key, params=params
        )
        await self.api.create_message(self._command_channel(), command)
        log.info("sent %s", command)
        return command

    def _actor_name(self, ctx) -> str | None:
        actor = (getattr(getattr(ctx, "message", None), "data", None) or {}).get(
            "actor"
        )
        if isinstance(actor, dict):
            return actor.get("name") or actor.get("email") or None
        return None

    @rpc.handler("schedule_start", channel="ui_cmds")
    async def on_schedule_start(self, ctx, payload):
        """Start a schedule: ``{"mode": "simple" | "detailed", "steps": [...]}``."""
        now = model.now_ms()
        await self._update_angle()  # where the first step starts from
        active, history = await self._load_schedules()
        if active is not None:
            raise RPCError(
                "INVALID",
                "A schedule is already running: end it before starting another",
            )
        try:
            mode, steps = model.validate_schedule(
                payload,
                default_speed=self._default_speed(),
                simple_wet=self._simple_wet(),
                max_hours=self._max_hours(),
            )
        except model.ScheduleInvalid as e:
            raise RPCError("INVALID", "\n".join(e.errors)) from e
        schedule = model.new_schedule(
            mode, steps, now=now, started_by=self._actor_name(ctx)
        )
        await self._save_schedules(schedule, history)
        progress = model.empty_progress(now, schedule, self.tags.angle_deg.value)
        if self._cfg("demo_simulate_controller", False):
            progress["estimated"] = False
        await self._set_schedule_tags(schedule, history, progress)
        pump = self._pump_with_pivot()
        command = await self._send_schedule_command(
            "schedule_start",
            {
                "schedule_id": schedule["id"],
                "schedule": model.schedule_for_edge(schedule, pump is not None),
                "supply_pump": pump,
            },
        )
        await self._set(
            "last_command",
            f"Schedule started ({len(steps)} step{'s' if len(steps) != 1 else ''})",
        )
        return {"schedule_id": schedule["id"], "request_id": command["request_id"]}

    async def _schedule_action(self, ctx, payload, verb: str):
        now = model.now_ms()
        active, history = await self._load_schedules()
        wanted = (
            (payload or {}).get("schedule_id") if isinstance(payload, dict) else None
        )
        if active is None or (wanted and wanted != active["id"]):
            raise RPCError("NOT_RUNNING", "That schedule isn't running any more")
        if verb == "schedule_pause":
            await self._save_schedules(model.pause_schedule(active, now), history)
        elif verb == "schedule_resume":
            await self._save_schedules(model.resume_schedule(active, now), history)
        else:
            await self._finish(active, history, model.SCHEDULE_ENDED, now)
        command = await self._send_schedule_command(verb, {"schedule_id": active["id"]})
        await self._set("last_command", SCHEDULE_COMMANDS[verb])
        return {"schedule_id": active["id"], "request_id": command["request_id"]}

    @rpc.handler("schedule_pause", channel="ui_cmds")
    async def on_schedule_pause(self, ctx, payload):
        return await self._schedule_action(ctx, payload, "schedule_pause")

    @rpc.handler("schedule_resume", channel="ui_cmds")
    async def on_schedule_resume(self, ctx, payload):
        return await self._schedule_action(ctx, payload, "schedule_resume")

    @rpc.handler("schedule_end", channel="ui_cmds")
    async def on_schedule_end(self, ctx, payload):
        return await self._schedule_action(ctx, payload, "schedule_end")

    async def _publish_settings(self, schedule: dict | None, history: list[dict]):
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
            schedule=schedule,
            history=history,
            supply_pump=self._supply_pump(),
        )
        # Replace only this app's key: other apps' settings in the aggregate are kept.
        await self.api.update_channel_aggregate(
            self._settings_channel(),
            {self.app_key: payload},
            replace_keys=[self.app_key],
        )
