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
        "schedules",
    } <= names
