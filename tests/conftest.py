"""A processor invocation without the cloud: the real config, tags and UI, with the data API,
notifications and UI command values faked."""

import copy
from types import SimpleNamespace

import pytest
from pydoover.tags.manager import TagsManagerProcessor

from pivot_control.app_config import PivotControlConfig
from pivot_control.app_tags import PivotControlTags
from pivot_control.app_ui import PivotControlUI
from pivot_control.application import PivotControlApplication

APP_KEY = "pivot_control_1"

EXAMPLE_CONFIG = {
    "APP_KEY": APP_KEY,
    # Explicit paths (flat on io_state); blank ones use the automatic addresses.
    "run_state_path": "$io_state.run",
    "forward_state_path": "$io_state.forward",
    "reverse_state_path": "$io_state.reverse",
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
        # Other devices' channel aggregates: {(agent_id, channel): data}; a missing one raises
        # as a device without permission does.
        self.remote = {}
        self.fetched = []
        # This device's own channel aggregates, as this app's writes leave them.
        self.own = {}

    async def fetch_channel_aggregate(self, channel, agent_id=None, **kwargs):
        self.fetched.append((agent_id, channel))
        if agent_id is None:
            if channel not in self.own:
                raise LookupError(f"no {channel} aggregate yet")
            return SimpleNamespace(data=copy.deepcopy(self.own[channel]))
        if (agent_id, channel) not in self.remote:
            raise PermissionError(f"no access to {channel} on {agent_id}")
        return SimpleNamespace(data=self.remote[(agent_id, channel)])

    async def create_message(self, channel, data, **kwargs):
        self.messages.append((channel, data))

    async def update_channel_aggregate(self, channel, data, **kwargs):
        self.aggregates.append((channel, data, kwargs))
        current = self.own.setdefault(channel, {})
        for key, value in copy.deepcopy(data).items():
            if key in (kwargs.get("replace_keys") or []) or not isinstance(value, dict):
                current[key] = value
            else:
                current.setdefault(key, {}).update(value)

    def commands(self):
        return [d for c, d in self.messages if c == "io_commands"]

    def settings(self):
        return self.own.get("control_settings", {}).get(APP_KEY)


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
        self.config = dict(EXAMPLE_CONFIG if config is None else config)
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
