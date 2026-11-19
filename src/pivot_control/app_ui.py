from pathlib import Path

from pydoover import ui

from . import model
from .app_config import POSITION_FROM_LOCATION
from .app_tags import PivotControlTags as T

DIRECTION_OPTIONS = [ui.Option("Forward"), ui.Option("Reverse")]
END_OPTIONS = [
    ui.Option("Until stopped"),
    ui.Option("Stop at angle"),
    ui.Option("Run for hours"),
]

# Compass quadrants on the angle dial.
ANGLE_RANGES = [
    ui.Range("N-E", 0, 90, ui.Colour.blue),
    ui.Range("E-S", 90, 180, ui.Colour.green),
    ui.Range("S-W", 180, 270, ui.Colour.yellow),
    ui.Range("W-N", 270, 360, ui.Colour.purple),
]


class PivotControlUI(ui.UI):
    command_warning = ui.WarningIndicator(
        T.command_message,
        name="command_warning",
        hidden=T.command_warning_hidden,
        can_cancel=False,
        position=1,
    )
    safety_warning = ui.WarningIndicator(
        "Safety circuit tripped",
        name="safety_warning",
        hidden=T.safety_warning_hidden,
        can_cancel=False,
        position=2,
    )

    # The map: pivot centre, end tower, arm and recent track. Its config comes from this
    # app's deployment config (app_key); the widget reads tag_values / location itself.
    pivot_map = ui.RemoteComponent(
        name="pivot_map",
        display_name="Pivot Map",
        component_url="$config.app().dv_widget_url",
        scope="PivotControlWidget",
        module="./PivotControlWidget",
        app_key="$config.app().APP_KEY",
        position=3,
    )

    status = ui.TextVariable("Status", value=T.status, name="status", position=10)
    speed = ui.NumericVariable(
        "Speed",
        value=T.speed_percent,
        units="%",
        precision=0,
        name="speed",
        position=11,
    )
    angle = ui.NumericVariable(
        "Angle",
        value=T.angle_deg,
        units="°",
        precision=0,
        form=ui.Widget.radial,
        ranges=ANGLE_RANGES,
        name="angle",
        position=12,
    )
    heading = ui.TextVariable("Heading", value=T.heading, name="heading", position=13)
    safety = ui.TextVariable("Safety", value=T.safety_text, name="safety", position=14)
    pressure = ui.NumericVariable(
        "Line Pressure", value=T.pressure, precision=1, name="pressure", position=15
    )
    last_started = ui.Timestamp(
        "Last Started", value=T.last_started, name="last_started", position=16
    )
    last_stopped = ui.Timestamp(
        "Last Stopped", value=T.last_stopped, name="last_stopped", position=17
    )
    last_command = ui.TextVariable(
        "Last Command", value=T.last_command, name="last_command", position=18
    )

    # The pump on another device that supplies the water (only when one is linked). Nested
    # elements reference their tags by name.
    supply_pump_warning = ui.WarningIndicator(
        T.supply_pump_warning,
        name="supply_pump_warning",
        hidden=T.supply_pump_warning_hidden,
        can_cancel=False,
        position=4,
    )
    supply_pump = ui.Submodule(
        "Supply Pump",
        name="supply_pump",
        status=ui.tag_ref("supply_pump_state", "string", "Unknown"),
        position=19,
        children=[
            ui.TextVariable(
                "Pump",
                name="supply_pump_name",
                value=ui.tag_ref("supply_pump_name", "string", "Not read yet"),
            ),
            ui.TextVariable(
                "State",
                name="supply_pump_state",
                value=ui.tag_ref("supply_pump_state", "string", "Unknown"),
            ),
            ui.Timestamp(
                "Last Started",
                name="supply_pump_last_started",
                value=ui.tag_ref("supply_pump_last_started", "number"),
            ),
            ui.Timestamp(
                "Last Stopped",
                name="supply_pump_last_stopped",
                value=ui.tag_ref("supply_pump_last_stopped", "number"),
            ),
            ui.TextVariable(
                "With Pivot",
                name="supply_pump_mode",
                value=ui.tag_ref("supply_pump_mode", "string"),
            ),
            ui.Timestamp(
                "State Read",
                name="supply_pump_checked",
                value=ui.tag_ref("supply_pump_checked", "number"),
            ),
        ],
    )

    control = ui.Submodule(
        "Control",
        name="control",
        position=20,
        children=[
            ui.Select(
                "Direction",
                name="start_direction",
                options=DIRECTION_OPTIONS,
                default=model.FORWARD,
            ),
            ui.FloatInput(
                "Speed", name="start_speed", units="%", min_val=1, max_val=100
            ),
            ui.Select(
                "End",
                name="start_end",
                options=END_OPTIONS,
                default=model.END_UNTIL_STOPPED,
            ),
            ui.FloatInput(
                "Stop Angle", name="start_stop_angle", units="°", min_val=0, max_val=360
            ),
            ui.FloatInput("Run Time", name="start_hours", units="h", min_val=0),
            ui.Button(
                "Start",
                name="start",
                requires_confirm=True,
                command_timeout=60,
            ),
            ui.Button("Stop", name="stop", requires_confirm=True, command_timeout=60),
        ],
    )

    # The schedule: the running one with its steps and progress, Pause / Resume / End, or
    # Create Schedule (Simple, Detailed or from Past Schedules). It talks to this app through
    # the schedule_* RPCs on ui_cmds and reads the schedule_active / schedule_history tags.
    schedule = ui.RemoteComponent(
        name="schedule",
        display_name="Schedule",
        component_url="$config.app().dv_widget_url",
        scope="PivotControlWidget",
        module="./ScheduleWidget",
        app_key="$config.app().APP_KEY",
        position=30,
    )

    async def setup(self):
        cfg = self.config
        if cfg is None:
            return
        self.pressure.units = cfg.pressure_units.value or None
        self.pressure.hidden = not (cfg.pressure_path.value or "").strip()
        self.safety.hidden = not (cfg.safety_path.value or "").strip()
        try:
            source = cfg.angle_source
            has_angle = bool(source.app_name.value) and bool(source.tag_name.value)
        except ValueError:  # not configured
            has_angle = False
        if not has_angle:
            # The angle is also worked out from the GPS tags and a configured pivot centre.
            has_angle = (
                cfg.position_source.value != POSITION_FROM_LOCATION
                and cfg.pivot_centre_lat.value is not None
                and cfg.pivot_centre_lon.value is not None
            )
        self.angle.hidden = not has_angle
        has_pump = False
        for field in (
            "supply_pump_device",
            "supply_pump_app_key",
            "supply_pump_target",
        ):
            try:
                has_pump = has_pump or bool(
                    str(getattr(cfg, field).value or "").strip()
                )
            except ValueError:  # not configured
                pass
        self.supply_pump.hidden = not has_pump
        self.heading.hidden = not has_angle

        max_hours = float(cfg.max_run_hours.value or 0)
        default_speed = float(cfg.default_speed.value or 50)
        for name, element in self.get_interactions().items():
            if name == "start_speed":
                _set_default(element, default_speed)
            if max_hours and name == "start_hours":
                element.max = max_hours


def _set_default(element, default):
    """An input's default (shown until an operator sets it) from config."""
    element.default = default
    element._value_location = f"$cmds.app().{element.name}::{default:g}"


def export():
    PivotControlUI(None, None, None).export(
        Path(__file__).parents[2] / "doover_config.json", "pivot_control"
    )


if __name__ == "__main__":
    export()
