from pathlib import Path

from pydoover import config
from pydoover.processor import (
    ExtendedPermissionsConfig,
    ManySubscriptionConfig,
    ScheduleConfig,
    TimezoneConfig,
)


class AngleSource(config.Object):
    """A tag published by another app on this device carrying the pivot's angle."""

    app_name = config.ApplicationInstall(
        "Application",
        description="App on this device that publishes the angle tag (e.g. a GPS tracker).",
        name="app_name",
        default=None,
    )
    tag_name = config.String(
        "Tag Name",
        description="Name of the tag within that app: degrees, 0 = North, clockwise.",
        name="tag_name",
        default="bearing_deg",
    )


class LatitudeSource(config.Object):
    """The tag of another app on this device carrying the GPS latitude."""

    app_name = config.ApplicationInstall(
        "Application",
        description="App on this device that publishes the latitude (e.g. a GPS tracker).",
        name="app_name",
        default="gps_tracker_1",
    )
    tag_name = config.String(
        "Tag Name",
        description="Name of the latitude tag within that app, in decimal degrees.",
        name="tag_name",
        default="latitude",
    )


class LongitudeSource(config.Object):
    """The tag of another app on this device carrying the GPS longitude."""

    app_name = config.ApplicationInstall(
        "Application",
        description="App on this device that publishes the longitude (e.g. a GPS tracker).",
        name="app_name",
        default="gps_tracker_1",
    )
    tag_name = config.String(
        "Tag Name",
        description="Name of the longitude tag within that app, in decimal degrees.",
        name="tag_name",
        default="longitude",
    )


POSITION_FROM_TAGS = "GPS tags"
POSITION_FROM_LOCATION = "Location channel"


class PivotControlConfig(config.Schema):
    # --- Outputs (command targets) ---------------------------------------------
    run_target = config.String(
        "Run Output",
        name="run_target",
        description=(
            "Output id the edge controller drives as the run / percentage timer. Sent as the "
            "`target` of start and stop commands."
        ),
        default="run",
        position=1,
    )
    forward_target = config.String(
        "Forward Output",
        name="forward_target",
        description="Output id of the forward direction signal on the edge controller.",
        default="forward",
        position=2,
    )
    reverse_target = config.String(
        "Reverse Output",
        name="reverse_target",
        description="Output id of the reverse direction signal on the edge controller.",
        default="reverse",
        position=3,
    )

    # --- Reported state ----------------------------------------------------------
    run_state_path = config.String(
        "Run State Path",
        name="run_state_path",
        description=(
            "The run output's reported state (0/1). Shown for reference: it pulses with the "
            "percentage timer. Leave blank to use this input's automatic address, which the "
            "edge bridge fills in. Or give a message path, e.g. '$io_state.x'."
        ),
        default="",
        position=4,
    )
    forward_state_path = config.String(
        "Forward State Path",
        name="forward_state_path",
        description=(
            "The forward output's reported state (0/1). Leave blank to use this input's "
            "automatic address, which the edge bridge fills in. Or give a message path, "
            "e.g. '$io_state.x'."
        ),
        default="",
        position=5,
    )
    reverse_state_path = config.String(
        "Reverse State Path",
        name="reverse_state_path",
        description=(
            "The reverse output's reported state (0/1). Leave blank to use this input's "
            "automatic address, which the edge bridge fills in. Or give a message path, "
            "e.g. '$io_state.x'."
        ),
        default="",
        position=6,
    )
    speed_state_path = config.String(
        "Speed State Path",
        name="speed_state_path",
        description=(
            "Optional: the speed (%) the controller reports it is running at. Until it "
            "reports one, the speed of the last confirmed start is shown. Leave blank to "
            "use this input's automatic address, which the edge bridge fills in. Or give a "
            "message path, e.g. '$io_state.x'."
        ),
        default="",
        position=7,
    )
    safety_path = config.String(
        "Safety Input Path",
        name="safety_path",
        description=(
            "Optional: the pivot's safety circuit input. Not shown until it reports a "
            "value. Leave blank to use this input's automatic address, which the edge "
            "bridge fills in. Or give a message path, e.g. '$io_state.x'."
        ),
        default="",
        position=8,
    )
    safety_ok_value = config.Number(
        "Safety OK Value",
        name="safety_ok_value",
        description="The safety input's value when the circuit is healthy (1 = closed / on).",
        default=1.0,
        position=9,
    )

    # --- Angle -------------------------------------------------------------------
    angle_source = AngleSource(
        "Angle Source",
        description=(
            "Optional tag of another app on this device carrying the pivot's angle "
            "(0 = North, clockwise), e.g. a GPS tracker's bearing_deg. Without it the angle "
            "is worked out from the GPS tags and the pivot centre, when both are set."
        ),
        name="angle_source",
        default={},
        position=10,
    )

    # --- Map -------------------------------------------------------------------------
    pivot_centre_lat = config.Number(
        "Pivot Centre Latitude",
        name="pivot_centre_lat",
        description=(
            "Latitude of the pivot point, decimal degrees. Leave empty to use the device's "
            "fixed location."
        ),
        default=None,
        required=False,
        minimum=-90,
        maximum=90,
        position=11,
    )
    pivot_centre_lon = config.Number(
        "Pivot Centre Longitude",
        name="pivot_centre_lon",
        description=(
            "Longitude of the pivot point, decimal degrees. Leave empty to use the device's "
            "fixed location."
        ),
        default=None,
        required=False,
        minimum=-180,
        maximum=180,
        position=12,
    )
    wetted_radius_m = config.Number(
        "Wetted Radius (m)",
        name="wetted_radius_m",
        description="Optional radius the pivot waters, drawn as a circle on the map. Leave empty for none.",
        default=None,
        required=False,
        minimum=0,
        position=13,
    )
    track_hours = config.Number(
        "Map Track (hours)",
        name="track_hours",
        description="How many hours of the end tower's recent positions the map draws as its track.",
        default=24.0,
        minimum=1,
        maximum=720,
        position=14,
    )
    position_source = config.Enum(
        "Position Source",
        name="position_source",
        choices=[POSITION_FROM_TAGS, POSITION_FROM_LOCATION],
        default=POSITION_FROM_TAGS,
        description=(
            "Where the end tower's GPS position comes from: latitude / longitude tags of "
            "another app on this device (e.g. a GPS tracker), or the device's location channel."
        ),
        position=15,
    )
    latitude_source = LatitudeSource(
        "Latitude Tag",
        description="(GPS tags) tag of another app on this device carrying the end tower's latitude.",
        name="latitude_source",
        default={},
        position=16,
    )
    longitude_source = LongitudeSource(
        "Longitude Tag",
        description="(GPS tags) tag of another app on this device carrying the end tower's longitude.",
        name="longitude_source",
        default={},
        position=17,
    )

    # --- Line pressure -----------------------------------------------------------
    pressure_path = config.String(
        "Line Pressure Path",
        name="pressure_path",
        description=(
            "Optional: the raw line pressure input (e.g. mA). Not shown until it reports a "
            "value. Leave blank to use this input's automatic address, which the edge "
            "bridge fills in. Or give a message path, e.g. '$io_state.x'."
        ),
        default="",
        position=18,
    )
    pressure_input_min = config.Number(
        "Pressure Minimum Input",
        name="pressure_input_min",
        description="Raw input at the minimum pressure (e.g. 4 mA).",
        default=4.0,
        position=19,
    )
    pressure_input_max = config.Number(
        "Pressure Maximum Input",
        name="pressure_input_max",
        description="Raw input at the maximum pressure (e.g. 20 mA).",
        default=20.0,
        position=20,
    )
    pressure_min = config.Number(
        "Pressure at Minimum Input",
        name="pressure_min",
        description="Pressure at the minimum input.",
        default=0.0,
        position=21,
    )
    pressure_max = config.Number(
        "Pressure at Maximum Input",
        name="pressure_max",
        description="Pressure at the maximum input.",
        default=100.0,
        position=22,
    )
    pressure_units = config.String(
        "Pressure Units",
        name="pressure_units",
        default="PSI",
        description="Units of the pressure.",
        position=23,
    )
    low_pressure_threshold = config.Number(
        "Low Pressure Threshold",
        name="low_pressure_threshold",
        description=(
            "Line pressure below which, while running, the opt-in Low line pressure notification "
            "is sent. Leave empty to never send it."
        ),
        default=None,
        required=False,
        position=24,
    )
    low_pressure_delay_s = config.Number(
        "Low Pressure Start Delay (s)",
        name="low_pressure_delay_s",
        description="Seconds after a start before low pressure counts, while the line fills.",
        default=300.0,
        minimum=0,
        position=25,
    )

    # --- Running -----------------------------------------------------------------
    cycle_s = config.Number(
        "Percent Timer Cycle (s)",
        name="cycle_s",
        description="Length of one percentage-timer cycle: at 50 % the run output is on for half of it.",
        default=60.0,
        minimum=1,
        position=26,
    )
    default_speed = config.Number(
        "Default Speed (%)",
        name="default_speed",
        description="Speed offered for a new start or schedule step, and the speed of Simple schedules.",
        default=50.0,
        minimum=1,
        maximum=100,
        position=27,
    )
    simple_wet = config.Boolean(
        "Simple Schedules Run Wet",
        name="simple_wet",
        description=(
            "Whether a Simple schedule runs wet (the supply pump on) or dry. Detailed "
            "schedules choose for each step."
        ),
        default=True,
        position=28,
    )
    schedule_state_path = config.String(
        "Schedule State Path",
        name="schedule_state_path",
        description=(
            "Optional: where the edge reports the running schedule's progress "
            "({schedule_id, step_index, step_progress, status}). Until it reports, this "
            "app's estimate from the angle and elapsed time is shown. Leave blank to use "
            "this input's automatic address, which the edge bridge fills in. Or give a "
            "message path, e.g. '$io_state.x'."
        ),
        default="",
        position=29,
    )
    max_run_hours = config.Number(
        "Max Run Hours",
        name="max_run_hours",
        description=(
            "Longest a run (or a schedule step's run time) may last; the edge controller "
            "stops the pivot after it. 0 = no limit."
        ),
        default=0.0,
        minimum=0,
        position=30,
    )
    confirm_timeout_s = config.Number(
        "Command Confirm Timeout (s)",
        name="confirm_timeout_s",
        description=(
            "How long after a command the reported state must match it before the command "
            "counts as not confirmed."
        ),
        default=120.0,
        minimum=10,
        position=31,
    )
    dv_proc_timezone = TimezoneConfig(
        description="Timezone sent to the edge with the settings.",
        position=32,
    )

    # --- Supply pump (a pump on another device that waters the pivot) ------------
    supply_pump_device = config.Device(
        "Supply Pump Device",
        name="supply_pump_device",
        description=(
            "Optional: the device with the pump that supplies this pivot's water. "
            "Also add it under Devices below so its state can be read."
        ),
        default=None,
        required=False,
        position=33,
    )
    supply_pump_app_key = config.String(
        "Supply Pump App Key",
        name="supply_pump_app_key",
        description="The Pump Control install's app key on that device, e.g. 'pump_control_1'.",
        default=None,
        required=False,
        position=34,
    )
    supply_pump_target = config.String(
        "Supply Pump Target ID",
        name="supply_pump_target",
        description="The pump's Target ID in that install, e.g. 'pump_1'.",
        default=None,
        required=False,
        position=35,
    )
    supply_pump_with_pivot = config.Boolean(
        "Start Pump with Pivot Runs",
        name="supply_pump_with_pivot",
        description=(
            "The edge controller starts the supply pump with every pivot run (manual or "
            "scheduled) and stops it when the run ends."
        ),
        default=True,
        position=36,
    )
    supply_pump_lead_s = config.Number(
        "Pump Lead Time (s)",
        name="supply_pump_lead_s",
        description="Seconds the pump runs before the pivot starts, to fill the line.",
        default=0.0,
        minimum=0,
        position=37,
    )
    supply_pump_run_on_s = config.Number(
        "Pump Run-On (s)",
        name="supply_pump_run_on_s",
        description="Seconds the pump keeps running after the pivot stops.",
        default=0.0,
        minimum=0,
        position=38,
    )
    extended_permissions = ExtendedPermissionsConfig(
        extra_fields=["id", "name", "display_name"],
        default={
            "devices": [],
            "groups": [],
            "apps_installed": [],
            "all_devices": False,
        },
        required=False,
        position=39,
    )

    # --- Channels ----------------------------------------------------------------
    command_channel = config.String(
        "Command Channel",
        name="command_channel",
        description="Channel commands are published on, one message each. The edge may reply there.",
        default="io_commands",
        position=41,
        advanced=True,
    )
    settings_channel = config.String(
        "Settings Channel",
        name="settings_channel",
        description=(
            "Channel whose aggregate carries the settings and the schedule the edge runs, "
            "under this app's key."
        ),
        default="control_settings",
        position=42,
        advanced=True,
    )
    subscription = ManySubscriptionConfig(
        default=["io_state", "ui_cmds", "io_commands", "tag_values"],
        description=(
            "Channels this app is invoked on: the input paths' channel(s), ui_cmds for the "
            "controls, the Command Channel for replies and tag_values for the angle."
        ),
        advanced=True,
        position=43,
    )
    dv_proc_schedules = ScheduleConfig(
        default="rate(5 minutes)",
        description="How often unconfirmed commands and the schedule's progress are re-checked.",
        advanced=True,
        position=44,
    )

    demo_simulate_controller = config.Boolean(
        "Simulate Controller (demo)",
        name="demo_simulate_controller",
        description=(
            "For demos only, with no edge controller connected: schedules are treated as "
            "accepted by the controller at once and their progress is shown as reported, "
            "not estimated. Leave off on a real site."
        ),
        default=False,
        advanced=True,
        position=45,
    )

    position = config.ApplicationPosition(default=10, position=46)
    default_open = config.ApplicationDefaultOpen(default=True, position=47)


def export():
    PivotControlConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "pivot_control"
    )


if __name__ == "__main__":
    export()
