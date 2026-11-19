"""A processor invocation without the cloud: the real config, tags and UI, with the data API,
notifications and UI command values faked."""

import copy

import pytest
from pydoover.tags.manager import TagsManagerProcessor

from pivot_control.app_config import PivotControlConfig
from pivot_control.app_tags import PivotControlTags
from pivot_control.app_ui import PivotControlUI
from pivot_control.application import PivotControlApplication

APP_KEY = "pivot_control_1"

BARMOUNT_CONFIG = {
    "APP_KEY": APP_KEY,
    "safety_path": "$io_state.safety",
    "safety_ok_value": 1.0,
    "angle_source": {"app_name": "gps_tracker_1", "tag_name": "bearing_deg"},
    "pressure_path": "$io_state.water_pressure",
    "pressure_input_min": 4.0,
    "pressure_input_max": 20.0,
    "pressure_min": 0.0,
    "pressure_max": 87.0,
    "pressure_units": "PSI",
    "low_pressure_threshold": 20.0,
}


class FakeApi:
    def __init__(self):
        self.messages = []
        self.aggregates = []

    async def create_message(self, channel, data, **kwargs):
        self.messages.append((channel, data))

    async def update_channel_aggregate(self, channel, data, **kwargs):
        self.aggregates.append((channel, data, kwargs))


class FakeNotification:
    def __init__(self, sent, name):
        self._sent, self._name = sent, name

    async def send(self, message=None, **kwargs):
        self._sent.append((self._name, message))


class FakeNotifications:
    def __init__(self):
        self.sent = []

    def __getattr__(self, name):
        if name.startswith("_") or name == "sent":
            raise AttributeError(name)
        return FakeNotification(self.sent, name)


class FakeUIManager:
    def __init__(self, values):
        self.values = values

    def get_value(self, key):
        return self.values[key]


class Harness:
    def __init__(
        self,
        config: dict | None = None,
        tag_values: dict | None = None,
        ui_values: dict | None = None,
    ):
        self.config = dict(BARMOUNT_CONFIG if config is None else config)
        self._tag_values = tag_values if tag_values is not None else {}
        self._last = None
        self.ui_values = ui_values or {}
        self.api = FakeApi()
        self.notifications = FakeNotifications()

    @property
    def tag_values(self) -> dict:
        """tag_values as the last invocation left them (what the next one is handed)."""
        if self._last is not None:
            self._tag_values = self._last.tag_manager._tag_values
        return self._tag_values

    async def app(self) -> PivotControlApplication:
        """A fresh instance per invocation, as on Lambda, over the shared tag_values."""
        tag_values = copy.deepcopy(self.tag_values)
        app = object.__new__(PivotControlApplication)
        app.config = PivotControlConfig()
        app.config._inject_deployment_config(self.config)
        app.app_key = APP_KEY
        app.api = self.api
        app.tag_manager = TagsManagerProcessor(APP_KEY, self.api, 1, tag_values)
        app.tags = PivotControlTags(APP_KEY, app.tag_manager, app.config)
        await app.tags.setup()
        app.notifications = self.notifications
        app.ui_manager = FakeUIManager(self.ui_values)
        app.ui = PivotControlUI(app.config, app.tags, APP_KEY)
        await app.ui.setup()
        await app.setup()
        self._last = app
        return app

    def tag(self, name):
        return self.tag_values.get(APP_KEY, {}).get(name)


@pytest.fixture
def harness():
    return Harness()
