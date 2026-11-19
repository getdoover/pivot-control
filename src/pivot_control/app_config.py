from pathlib import Path

from pydoover import config
from pydoover.processor import ManySubscriptionConfig, ScheduleConfig, TimezoneConfig


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
            "Message path of the run output's reported state (0/1), '$channel.path.to.value'. "
            "Shown for reference: it pulses with the percentage timer."
        ),
        default="$io_state.run",
        position=4,
    )
    forward_state_path = config.String(
        "Forward State Path",
        name="forward_state_path",
        description="Message path of the forward output's reported state (0/1).",
        default="$io_state.forward",
        position=5,
    )
    reverse_state_path = config.String(
        "Reverse State Path",
        name="reverse_state_path",
        description="Message path of the reverse output's reported state (0/1).",
        default="$io_state.reverse",
        position=6,
    )
    speed_state_path = config.String(
        "Speed State Path",
        name="speed_state_path",
        description=(
            "Optional message path of the speed (%) the controller reports it is running at. "
            "Leave empty to show the speed of the last confirmed start."
        ),
        default="",
        position=7,
    )
    safety_path = config.String(
        "Safety Input Path",
        name="safety_path",
        description="Optional message path of the pivot's safety circuit input. Leave empty if none.",
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
            "(0 = North, clockwise), e.g. a GPS tracker's bearing_deg."
        ),
        name="angle_source",
        default={},
        position=10,
    )

    # --- Line pressure -----------------------------------------------------------
    pressure_path = config.String(
        "Line Pressure Path",
        name="pressure_path",
        description="Optional message path of the raw line pressure input (e.g. mA). Leave empty if none.",
        default="",
        position=11,
    )
    pressure_input_min = config.Number(
        "Pressure Minimum Input",
        name="pressure_input_min",
        description="Raw input at the minimum pressure (e.g. 4 mA).",
        default=4.0,
        position=12,
    )
    pressure_input_max = config.Number(
        "Pressure Maximum Input",
        name="pressure_input_max",
        description="Raw input at the maximum pressure (e.g. 20 mA).",
        default=20.0,
        position=13,
    )
    pressure_min = config.Number(
        "Pressure at Minimum Input",
        name="pressure_min",
        description="Pressure at the minimum input.",
        default=0.0,
        position=14,
    )
    pressure_max = config.Number(
        "Pressure at Maximum Input",
        name="pressure_max",
        description="Pressure at the maximum input.",
        default=100.0,
        position=15,
    )
    pressure_units = config.String(
        "Pressure Units",
        name="pressure_units",
        default="PSI",
        description="Units of the pressure.",
        position=16,
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
        position=17,
    )
    low_pressure_delay_s = config.Number(
        "Low Pressure Start Delay (s)",
        name="low_pressure_delay_s",
        description="Seconds after a start before low pressure counts, while the line fills.",
        default=300.0,
        minimum=0,
        position=18,
    )

    # --- Running -----------------------------------------------------------------
    cycle_s = config.Number(
        "Percent Timer Cycle (s)",
        name="cycle_s",
        description="Length of one percentage-timer cycle: at 50 % the run output is on for half of it.",
        default=60.0,
        minimum=1,
        position=19,
    )
    default_speed = config.Number(
        "Default Speed (%)",
        name="default_speed",
        description="Speed offered for a new start or schedule.",
        default=50.0,
        minimum=1,
        maximum=100,
        position=20,
    )
    max_run_hours = config.Number(
        "Max Run Hours",
        name="max_run_hours",
        description=(
            "Longest a run may last; the edge controller stops the pivot after it. 0 = no limit."
        ),
        default=0.0,
        minimum=0,
        position=21,
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
        position=22,
    )
    dv_proc_timezone = TimezoneConfig(
        description="Timezone schedule start times are shown and sent to the edge in.",
        position=23,
    )

    # --- Channels ----------------------------------------------------------------
    command_channel = config.String(
        "Command Channel",
        name="command_channel",
        description="Channel commands are published on, one message each. The edge may reply there.",
        default="io_commands",
        position=24,
        advanced=True,
    )
    settings_channel = config.String(
        "Settings Channel",
        name="settings_channel",
        description=(
            "Channel whose aggregate carries the settings and schedules the edge runs, "
            "under this app's key."
        ),
        default="control_settings",
        position=25,
        advanced=True,
    )
    subscription = ManySubscriptionConfig(
        default=["io_state", "ui_cmds", "io_commands", "tag_values"],
        description=(
            "Channels this app is invoked on: the input paths' channel(s), ui_cmds for the "
            "controls, the Command Channel for replies and tag_values for the angle."
        ),
        advanced=True,
        position=26,
    )
    dv_proc_schedules = ScheduleConfig(
        default="rate(5 minutes)",
        description="How often unconfirmed commands and schedule summaries are re-checked.",
        advanced=True,
        position=27,
    )

    position = config.ApplicationPosition(position=28)


def export():
    PivotControlConfig.export(
        Path(__file__).parents[2] / "doover_config.json", "pivot_control"
    )


if __name__ == "__main__":
    export()
