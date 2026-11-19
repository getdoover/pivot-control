from pydoover.processor import run_app

from .application import PivotControlApplication


def handler(event, context):
    """Lambda handler entry point."""
    return run_app(
        PivotControlApplication(),
        event,
        context,
    )
