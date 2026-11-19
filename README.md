# Pivot Control

<img src="https://doover.com/wp-content/uploads/Doover-Logo-Landscape-Navy-padded-small.png" alt="App Icon" style="max-width: 300px;">

**Remote control and monitoring of a centre-pivot irrigator**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/getdoover/pivot-control/blob/main/LICENSE)

[Getting Started](#getting-started) • [Configuration](#configuration) • [Integrations](#integrations) • [Need Help?](#need-help)

<br/>

## Overview

Starts, stops, schedules and monitors a centre pivot whose panel takes run, forward, reverse
and speed (percentage timer) signals. An edge controller on site drives those signals and runs
everything locally, schedules included; this cloud app is its remote control. It always shows
the state the controller **reports**, never the state it asked for.

Key capabilities:

- **Status** -- Running Forward / Running Reverse / Stopped / Unknown, from the reported
  forward and reverse outputs, with the time it last started and stopped
- **Speed** -- the percentage timer setting, 1-100 %
- **Map** -- a small satellite map of the pivot: its centre, the end tower's current GPS
  position, the arm between them, the recent track and (optionally) the wetted circle
- **Angle** -- the pivot's position from another app's tag (e.g. a GPS tracker's
  `bearing_deg`), or worked out from the end tower's GPS position and the pivot centre, as a
  dial and a compass heading
- **Safety and line pressure** -- an optional safety circuit input and an optional 4-20 mA
  pressure transmitter, scaled to engineering units
- **Start / Stop** -- start forward or reverse at a speed, running until stopped, to a stop
  angle or for a number of hours, with a pending indicator until the pivot confirms
- **Schedule** -- plan a run as a Simple schedule (one direction, to a stop angle) or a
  Detailed one (an ordered list of steps, each with its own direction, wet or dry, speed,
  stop angle or run time and start delay), or start again from one of the last five. The
  running schedule shows each step and its progress, and can be paused, resumed or ended
- **Supply pump** -- link the pump on another device (a Pump Control install) that waters
  the pivot: its live state shows on the pivot's page, and the edge controller starts and
  stops it with the pivot's runs, with an optional lead time and run-on
- **Notifications** -- safety tripped while running, command not confirmed, and (opt-in)
  low line pressure while running

<br/>

## Getting Started

1. Install **Pivot Control** on the pivot's device.
2. Set the **output ids** the edge controller knows the run (percentage timer), forward and
   reverse outputs by, and the **message paths** it reports their state on.
3. Optionally point **Angle Source** at the app and tag that carry the pivot's angle, and set
   the safety and line pressure inputs.
4. Optionally link the **supply pump**: its device, the Pump Control install's app key and
   the pump's Target ID, and add that device under **Devices** so its state can be read.
5. Deploy. The page renders straight away and reads "No reading yet" until the controller
   reports.

<br/>

## Configuration

Message paths are `$channel.path.to.value`, read from messages on the subscribed channels
(for example `$io_state.forward`). Inputs are raw signals: 0/1 (or true/false, on/off) for
outputs and the safety circuit, the loop current for pressure.

| Setting | Key | Description | Default |
|---------|-----|-------------|---------|
| **Run Output** | `run_target` | Output id of the run / percentage timer; the `target` of start and stop commands | `run` |
| **Forward Output** | `forward_target` | Output id of the forward signal | `forward` |
| **Reverse Output** | `reverse_target` | Output id of the reverse signal | `reverse` |
| **Run State Path** | `run_state_path` | Reported run output (pulses with the percentage timer) | `$io_state.run` |
| **Forward State Path** | `forward_state_path` | Reported forward output | `$io_state.forward` |
| **Reverse State Path** | `reverse_state_path` | Reported reverse output | `$io_state.reverse` |
| **Speed State Path** | `speed_state_path` | Optional reported speed (%). Empty: the speed of the last confirmed start is shown while running | empty |
| **Safety Input Path** | `safety_path` | Optional safety circuit input | empty |
| **Safety OK Value** | `safety_ok_value` | The safety input's value when healthy | `1` |
| **Angle Source** | `angle_source` | `{app_name, tag_name}`: another app's tag carrying the angle, degrees, 0 = North, clockwise | tag `bearing_deg` |
| **Pivot Centre Latitude / Longitude** | `pivot_centre_lat` / `pivot_centre_lon` | The pivot point, decimal degrees. Empty: the map uses the device's fixed location | empty |
| **Wetted Radius (m)** | `wetted_radius_m` | Optional radius drawn as a circle on the map | empty |
| **Map Track (hours)** | `track_hours` | How much of the end tower's recent path the map draws | `24` |
| **Position Source** | `position_source` | Where the end tower's GPS position comes from: *GPS tags* (the two tags below) or *Location channel* (the device's `location` channel) | GPS tags |
| **Latitude Tag** / **Longitude Tag** | `latitude_source` / `longitude_source` | `{app_name, tag_name}`: another app's tags carrying the end tower's latitude and longitude | `gps_tracker_1` `latitude` / `longitude` |
| **Line Pressure Path** | `pressure_path` | Optional raw pressure input | empty |
| **Pressure Min / Max Input** | `pressure_input_min` / `pressure_input_max` | Raw input range | `4` / `20` |
| **Pressure at Min / Max Input** | `pressure_min` / `pressure_max` | Pressure at each end of the range | `0` / `100` |
| **Pressure Units** | `pressure_units` | Display units | `PSI` |
| **Low Pressure Threshold** | `low_pressure_threshold` | Pressure below which, while running, the low pressure notification is sent. Empty: never | empty |
| **Low Pressure Start Delay (s)** | `low_pressure_delay_s` | Grace after a start while the line fills | `300` |
| **Percent Timer Cycle (s)** | `cycle_s` | One percentage-timer cycle: at 50 % the run output is on for half of it | `60` |
| **Default Speed (%)** | `default_speed` | Speed offered for a new start or schedule step, and the speed of Simple schedules | `50` |
| **Simple Schedules Run Wet** | `simple_wet` | Whether a Simple schedule runs wet (supply pump on) or dry | `true` |
| **Schedule State Path** | `schedule_state_path` | Optional message path where the edge reports the running schedule's progress (see *Settings*). Empty: this app estimates it | empty |
| **Max Run Hours** | `max_run_hours` | Longest run (or schedule step run time) the edge allows; 0 = no limit | `0` |
| **Command Confirm Timeout (s)** | `confirm_timeout_s` | How long the reported state has to match a command | `120` |
| **Timezone** | `dv_proc_timezone` | Timezone sent to the edge with the settings | `Australia/Brisbane` |
| **Supply Pump Device** | `supply_pump_device` | Optional: the device with the pump that supplies the pivot. Add it under **Devices** too | empty |
| **Supply Pump App Key** | `supply_pump_app_key` | The Pump Control install's app key on that device, e.g. `pump_control_1` | empty |
| **Supply Pump Target ID** | `supply_pump_target` | The pump's Target ID in that install, e.g. `pump_1` | empty |
| **Start Pump with Pivot Runs** | `supply_pump_with_pivot` | The edge starts the pump with every run, manual or scheduled, and stops it when the run ends | `true` |
| **Pump Lead Time (s)** | `supply_pump_lead_s` | Seconds the pump runs before the pivot starts | `0` |
| **Pump Run-On (s)** | `supply_pump_run_on_s` | Seconds the pump keeps running after the pivot stops | `0` |
| **Devices** | `dv_proc_extended_permissions` | Devices this app may read: add the supply pump's device | none |
| **Command Channel** | `command_channel` | Where commands are published | `io_commands` |
| **Settings Channel** | `settings_channel` | Whose aggregate carries the settings and the schedule | `control_settings` |
| **Subscription** | `dv_proc_subscriptions` | Channels the app is invoked on | `io_state`, `ui_cmds`, `io_commands`, `tag_values` |
| **Schedule** | `dv_proc_schedules` | How often unconfirmed commands and the schedule's progress are re-checked | `rate(5 minutes)` |
| **Simulate Controller (demo)** | `demo_simulate_controller` | For demos only, with no edge controller connected: schedules count as accepted by the controller at once and their progress shows as reported, not estimated | `false` |

A pressure input well under the minimum (under 1 mA on 4-20 mA) is a dead loop and reads as
no pressure, not zero; just under the minimum reads as the minimum.

<br/>

## Using the Device Page

**Map.** At the top of the panel: satellite imagery centred on the pivot, with the centre
(white), the end tower's latest GPS position (orange), the arm between them (yellow) and the
end tower's track over the last *Map Track* hours (blue). A dashed circle shows the wetted
radius when one is set. The header repeats the status and the angle, and says how old the
last GPS fix is. The map needs no API key or setup beyond a pivot centre (or the device's
fixed location) and a GPS source; with neither it says so instead.

Doover's main map places a device at its fixed location when it has one, and otherwise at
its `location` channel, with that channel's history as the device's track. To follow the pivot
on the main map, leave the device's fixed location empty, set the pivot centre here, and have
the GPS source write the device's `location` channel (a GPS tracker app does).

**Status.** Status, speed, angle and heading, safety (OK / Tripped), line pressure, last
started, last stopped and the last command with its outcome. Safety, pressure and angle only
show when configured.

| Forward | Reverse | Status |
|---------|---------|--------|
| on | off | Running Forward |
| off | on | Running Reverse |
| off | off | Stopped |
| on | on | Unknown |
| not reported yet | | No reading yet |

**Supply Pump.** When a supply pump is linked, a *Supply Pump* section shows its device and
name (e.g. `Eastern Pump: Diesel Pump`), its state -- **Running**, **Stopped** or
**Unknown** -- as its Pump Control install reports it, when it last started and stopped, how
it follows the pivot (`Starts with the pivot, 30 s lead, 60 s run-on`) and when its state was
last read. It is read on deployment, every schedule tick and after each Start or Stop.
Unknown means the state could not be read or hasn't been reported, and a warning above says
why: the link is incomplete, the device isn't under **Devices**, or the pump app has reported
nothing yet.

**Control.** Choose a direction, a speed and how the run ends -- **Until stopped**, **Stop
at angle** (0-360°) or **Run for hours** -- then **Start**. **Stop** stops it. After either,
a banner shows the command as pending until the reported status matches it; if it doesn't
within the confirm timeout the banner turns into a warning and the *command not confirmed*
notification is sent. A controller that refuses a command and says so has its reason shown.

**Schedule.** A schedule is a plan for one run of the pivot, made fresh each time.

- *Nothing running:* **Create Schedule** offers **Simple**, **Detailed** and **Past
  Schedules**.
  - **Simple:** a direction and a stop angle, then **Go**. It runs at the Default Speed,
    wet or dry as *Simple Schedules Run Wet* says.
  - **Detailed:** the inputs for step 1 -- direction, wet or dry, speed, how it ends (at a
    stop angle or after a run time in hours) and an optional start delay in minutes.
    **Add Step** keeps that step and opens the next (with the same direction, water and
    speed); **Go** starts the schedule. The steps so far are listed in order above the
    inputs: click one to edit it, × to remove it, and drag its handle (mouse or touch) to
    reorder them, or focus the handle and use the arrow keys.
  - **Past Schedules:** the last five, newest first, with their steps and when they ran.
    Choosing one opens it in its editor, ready to adjust and **Go**.
- *Go* checks every step, and nothing is sent until they are all valid. Each problem is
  shown on its step, in red: `Step 2: choose a stop angle or a run time`, `Speed must be
  1–100 %`, `Stop angle must be 0–360°`, `Run time must be more than 0`, a run time over
  *Max Run Hours*, or a negative start delay. The app checks again and refuses a bad
  schedule with the same messages.
- *Running:* the schedule's type, when and by whom it was started, every step in order
  with the current one highlighted, a progress bar and what's left (degrees to the stop
  angle, time left, or the start delay counting down), and Running or Paused. **Pause**
  holds it until **Resume**; **End schedule** (confirmed in place) ends it early. When its
  last step is done it moves to Past Schedules.

Progress is what the edge reports at the *Schedule State Path* when one is set. Otherwise
it is this app's estimate, labelled *estimated*: a run-time step counts the time since it
began, less its start delay and time paused; an angle step counts the degrees the pivot has
turned in the step's direction since it began (forward = clockwise, so a reverse run counts
the angle going down, and either can run through North), until it is within 1° of the stop
angle.

<br/>

## Integrations

### Tags

| Tag | Type | Description |
|-----|------|-------------|
| **state** | string | `running`, `stopped` or `unknown`; `null` before any reading |
| **direction** | string | `forward` / `reverse` while running, otherwise `null` |
| **status** | string | Running Forward / Running Reverse / Stopped / Unknown / No reading yet |
| **speed_percent** | number | Reported speed, or the last confirmed start's while running |
| **angle_deg** | number | Pivot angle, 0-360°, 0 = North, clockwise |
| **heading** | string | Angle with its compass point, e.g. `93° E` |
| **safety_ok** | boolean | Safety circuit healthy; `null` when not configured or not reported |
| **pressure** | number | Line pressure in the configured units |
| **last_started** / **last_stopped** | number | When the reported state last changed to running / stopped (ms) |
| **pending_command** | object | The command awaiting confirmation (the message below, plus `timed_out`) |
| **last_command** | string | The last command and its outcome |
| **schedule_active** | object | The running schedule (as in *Settings* `schedule_state.active`) plus its `progress`; `null` when none |
| **schedule_history** | array | The last five schedules, newest first, each with `status` `completed` or `ended` and `ended_ts` |
| **edge_schedule_state** | object | The edge's last schedule report, when a Schedule State Path is set |
| **supply_pump_name** | string | The linked supply pump, `<device>: <pump name>` |
| **supply_pump_state** | string | Running / Stopped / Unknown, as its Pump Control install reports it |
| **supply_pump_running** | boolean | `true` / `false` as reported; `null` when unknown |
| **supply_pump_last_started** / **supply_pump_last_stopped** | number | As the pump's install reports them (ms) |
| **supply_pump_checked** | number | When the pump's state was last read (ms) |
| **run_output** / **forward_output** / **reverse_output** / **safety_input** / **pressure_input** | | Raw inputs as last reported |

### Inputs

Raw signals at the configured message paths, on any subscribed channel. A message carrying
only some of them updates those and keeps the rest. The angle is read from the Angle Source
app's tag in `tag_values`. Without one, when the Position Source is *GPS tags* and the pivot
centre is set, the angle is the bearing from the centre to the end tower's latitude /
longitude tags (positions within 10 m of the centre give no angle). The map reads the same
tags' history from `tag_values`, or in *Location channel* mode the `location` channel's
aggregate (`lat`, `long`) and messages.

The supply pump's state is read from the linked device's `tag_values` aggregate, under the
Pump Control install's app key: `p_<target>_running`, `p_<target>_name`,
`p_<target>_last_started` and `p_<target>_last_stopped` (the target with anything but
letters, digits and `_` replaced by `_`). Reading another device needs it under **Devices**.

### Commands

One message per command on the **Command Channel**:

```json
{"command": "start", "target": "run", "duration_s": 7200,
 "params": {"direction": "forward", "speed_percent": 50, "stop_angle_deg": null},
 "request_id": "<uuid4>", "app_key": "<app key>", "app": "pivot_control",
 "ts": 1795050000000}
```

```json
{"command": "stop", "target": "run", "duration_s": null, "params": {},
 "request_id": "<uuid4>", "app_key": "<app key>", "app": "pivot_control",
 "ts": 1795050000000}
```

`duration_s` is `null` unless the run is for a number of hours; `stop_angle_deg` is `null`
unless it stops at an angle.

When a supply pump is linked and **Start Pump with Pivot Runs** is on, Start and Stop carry it
in `params.supply_pump` (the same object as in the settings below), and the edge sequences the
pump with the pivot itself: on start, the pump first and the pivot `lead_s` later; on stop,
the pivot first and the pump `run_on_s` later. This app never commands the pump's device
directly.

```json
{"command": "start", "target": "run", "duration_s": null,
 "params": {"direction": "forward", "speed_percent": 50, "stop_angle_deg": null,
            "supply_pump": {"device_id": "123456789012345678", "app_key": "pump_control_1",
                            "target": "pump_1", "start_with_pivot": true,
                            "lead_s": 30, "run_on_s": 60}},
 "request_id": "<uuid4>", "app_key": "<app key>", "app": "pivot_control",
 "ts": 1795050000000}
```

The schedule's operator actions are commands too. `schedule_start` carries the whole
schedule as the edge runs it (the `schedule` object in the settings below) and the supply
pump link; `schedule_pause`, `schedule_resume` and `schedule_end` carry its id. The same
change is in the settings, so an edge that restarts still honours it.

```json
{"command": "schedule_pause", "target": "run", "duration_s": null,
 "params": {"schedule_id": "<uuid4>"},
 "request_id": "<uuid4>", "app_key": "<app key>", "app": "pivot_control",
 "ts": 1795050000000}
```

The controller may reply on the same channel with
`{"request_id": "...", "ok": true|false, "error": "..."}`; a reply is shown when present and
never required.

### Schedule RPCs

The Schedule widget calls these on `ui_cmds` (`{"type": "rpc", "app_key", "method",
"request"}`); each answers success or an error with its message.

| Method | Request | Does |
|--------|---------|------|
| `schedule_start` | `{"mode": "simple" \| "detailed", "steps": [step, ...]}` | Checks every step, stores the schedule and sends `schedule_start`. Refused while one is running |
| `schedule_pause` / `schedule_resume` / `schedule_end` | `{"schedule_id": "<id>"}` | Changes the running schedule and sends the command |

A step is `{"direction": "forward" | "reverse", "wet": true, "speed_percent": 50, "end":
"angle" | "time", "stop_angle_deg": 180, "run_hours": null, "delay_min": 0}`. A Simple
schedule needs only `direction` and `stop_angle_deg`.

### Settings

Written to the **Settings Channel** aggregate under the app's key on every deployment and
every schedule change, replacing only that key:

```json
{"<app key>": {
  "app": "pivot_control", "schema": 2,
  "targets": {"run": "run", "forward": "forward", "reverse": "reverse"},
  "percent_timer_cycle_s": 60, "default_speed_percent": 50,
  "max_run_s": null, "timezone": "Australia/Brisbane",
  "schedule": {
    "id": "<uuid4>", "mode": "detailed", "status": "running", "paused": false,
    "started_ts": 1795050000000, "paused_ts": null, "paused_ms": 0,
    "steps": [
      {"direction": "forward", "speed_percent": 50, "stop_angle_deg": 180,
       "duration_s": null, "delay_s": 0, "wet": true, "supply_pump_on": true},
      {"direction": "reverse", "speed_percent": 80, "stop_angle_deg": null,
       "duration_s": 7200, "delay_s": 900, "wet": false, "supply_pump_on": false}
    ]},
  "schedule_state": {"active": {...}, "history": [...]},
  "supply_pump": {"device_id": "123456789012345678", "app_key": "pump_control_1",
                  "target": "pump_1", "start_with_pivot": true,
                  "lead_s": 30, "run_on_s": 60},
  "updated_ts": 1795050000000}}
```

`schedule` is the running schedule, or `null`. The edge runs its steps in order, each with
the same fields as a start command, after waiting `delay_s`. A step ends at
`stop_angle_deg` or after `duration_s`; the schedule is done when the last step is.
`status` is `running` or `paused`: while paused the edge stops the pivot and holds the step,
and `paused_ms` is the time spent in finished pauses (a current one began at `paused_ts`).
The supply pump runs through steps with `supply_pump_on` and is stopped for the others and
at the end; it is only true for a wet step with a linked pump that starts with the pivot.

`schedule_state` is this app's own record of the running schedule and the last five, and is
what the page shows. The edge may report its progress at the *Schedule State Path* as
`{"schedule_id": "<id>", "step_index": 0, "step_progress": 0.4, "status": "running"}`
(`step_index` from 0, `step_progress` 0-1, `status` `running`, `paused`, `waiting`,
`completed` or `ended`); `completed` or `ended` moves the schedule to the past schedules.

`supply_pump` is `null` when no pump is linked. When `start_with_pivot` is true the edge
starts the pump (the Pump Control install `app_key` on `device_id`, pump `target`) with every
run, scheduled or manual, `lead_s` before the pivot, and stops it `run_on_s` after the pivot
stops. A half-set link is sent with its missing parts `null`; the edge ignores it.

### Notifications

| Notification | Severity | Policy | When |
|--------------|----------|--------|------|
| **Safety tripped** | Critical | default | The safety input leaves its OK value while running (or within 2 minutes of stopping) |
| **Command not confirmed** | Warning | default | The reported status doesn't match a Start or Stop within the confirm timeout |
| **Low pressure** | Warning | opt-in | Line pressure below the threshold while running, after the start delay |

Each fires once per occurrence. Nothing fires without data: an input that hasn't reported
never trips, alarms or times out.

<br/>

## Need Help?

- Email: support@doover.com
- [Doover Documentation](https://docs.doover.com)
- [Source](https://github.com/getdoover/pivot-control)

<br/>

## License

This app is licensed under the [Apache License 2.0](https://github.com/getdoover/pivot-control/blob/main/LICENSE).
