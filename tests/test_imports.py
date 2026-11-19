def test_handler_imports():
    from pivot_control import handler

    assert callable(handler)


def test_ui_exports_cleanly():
    from pivot_control.app_ui import PivotControlUI

    schema = PivotControlUI(None, None, None).to_schema(resolve_config=False)
    names = set(schema["children"])
    assert {
        "status",
        "speed",
        "angle",
        "safety",
        "pressure",
        "control",
        "schedule",
    } <= names


def test_schedule_widget_wired():
    from pivot_control.app_ui import PivotControlUI

    schema = PivotControlUI(None, None, None).to_schema(resolve_config=False)
    widget = schema["children"]["schedule"]
    assert widget["type"] == "uiRemoteComponent"
    assert widget["module"] == "./ScheduleWidget"
    assert widget["scope"] == "PivotControlWidget"
    assert not any(name.startswith("sched_") for name in schema["children"])
