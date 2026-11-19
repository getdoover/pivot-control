from pathlib import Path

from pydoover import notifications as n


class PivotControlNotifications(n.Notifications):
    safety_tripped = n.Notification(
        "The pivot's safety circuit tripped while it was running",
        description="The safety input left its OK value while the pivot was running (or had just stopped).",
        severity=n.NotificationSeverity.Critical,
    )
    command_not_confirmed = n.Notification(
        "A pivot command was not confirmed",
        description="The pivot's reported state didn't match a Start or Stop within the confirm timeout.",
        severity=n.NotificationSeverity.Warn,
    )
    low_pressure = n.Notification(
        "The pivot's line pressure is low while running",
        description="Line pressure fell below the configured threshold while running, after the start delay.",
        severity=n.NotificationSeverity.Warn,
        policy=n.NotificationPolicy.opt_in,
    )


def export():
    PivotControlNotifications.export(
        Path(__file__).parents[2] / "doover_config.json", "pivot_control"
    )


if __name__ == "__main__":
    export()
