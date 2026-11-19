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
- **Angle** -- the pivot's position from another app's tag (e.g. a GPS tracker's
  `bearing_deg`), as a dial and a compass heading
- **Safety and line pressure** -- an optional safety circuit input and an optional 4-20 mA
  pressure transmitter, scaled to engineering units
- **Start / Stop** -- start forward or reverse at a speed, running until stopped, to a stop
  angle or for a number of hours, with a pending indicator until the pivot confirms
- **Schedules** -- four schedule slots the operator edits on the device page; the edge
  controller runs them
- **Notifications** -- safety tripped while running, command not confirmed, and (opt-in)
  low line pressure while running

<br/>

## Getting Started

1. Install **Pivot Control** on the pivot's device.
2. Set the **output ids** the edge controller knows the run (percentage timer), forward and
   reverse outputs by, and the **message paths** it reports their state on.
3. Optionally point **Angle Source** at the app and tag that carry the pivot's angle, and set
   the safety and line pressure inputs.
4. Deploy. The page renders straight away and reads "No reading yet" until the controller
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
| **Line Pressure Path** | `pressure_path` | Optional raw pressure input | empty |
| **Pressure Min / Max Input** | `pressure_input_min` / `pressure_input_max` | Raw input range | `4` / `20` |
| **Pressure at Min / Max Input** | `pressure_min` / `pressure_max` | Pressure at each end of the range | `0` / `100` |
| **Pressure Units** | `pressure_units` | Display units | `PSI` |
| **Low Pressure Threshold** | `low_pressure_threshold` | Pressure below which, while running, the low pressure notification is sent. Empty: never | empty |
| **Low Pressure Start Delay (s)** | `low_pressure_delay_s` | Grace after a start while the line fills | `300` |
| **Percent Timer Cycle (s)** | `cycle_s` | One percentage-timer cycle: at 50 % the run output is on for half of it | `60` |
| **Default Speed (%)** | `default_speed` | Speed offered for a new start or schedule | `50` |
| **Max Run Hours** | `max_run_hours` | Longest run the edge allows; 0 = no limit | `0` |
| **Command Confirm Timeout (s)** | `confirm_timeout_s` | How long the reported state has to match a command | `120` |
| **Timezone** | `dv_proc_timezone` | Timezone schedule times are shown and sent in | `Australia/Brisbane` |
| **Command Channel** | `command_channel` | Where commands are published | `io_commands` |
| **Settings Channel** | `settings_channel` | Whose aggregate carries the settings and schedules | `control_settings` |
| **Subscription** | `dv_proc_subscriptions` | Channels the app is invoked on | `io_state`, `ui_cmds`, `io_commands`, `tag_values` |
| **Schedule** | `dv_proc_schedules` | How often unconfirmed commands and schedule summaries are re-checked | `rate(5 minutes)` |

A pressure input well under the minimum (under 1 mA on 4-20 mA) is a dead loop and reads as
no pressure, not zero; just under the minimum reads as the minimum.

<br/>

## Using the Device Page

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

**Control.** Choose a direction, a speed and how the run ends -- **Until stopped**, **Stop
at angle** (0-360°) or **Run for hours** -- then **Start**. **Stop** stops it. After either,
a banner shows the command as pending until the reported status matches it; if it doesn't
within the confirm timeout the banner turns into a warning and the *command not confirmed*
notification is sent. A controller that refuses a command and says so has its reason shown.

**Schedules.** Four slots, each with Enabled, Start (date and time), Direction, Speed, End
(until stopped / stop at angle / run for hours), Stop Angle and Run Time. Each slot's header
summarises it, e.g. `Fri 20 Nov 06:00, Forward 50 %, to 180°`. Every edit is saved as the
`schedules` tag and sent to the edge straight away. A slot that is enabled but missing its
start time, stop angle or run time is sent disabled and its header says what is missing.

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
| **schedules** | array | The four schedule slots as edited |
| **run_output** / **forward_output** / **reverse_output** / **safety_input** / **pressure_input** | | Raw inputs as last reported |

### Inputs

Raw signals at the configured message paths, on any subscribed channel. A message carrying
only some of them updates those and keeps the rest. The angle is read from the Angle Source
app's tag in `tag_values`.

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
unless it stops at an angle. The controller may reply on the same channel with
`{"request_id": "...", "ok": true|false, "error": "..."}`; a reply is shown when present and
never required.

### Settings

Written to the **Settings Channel** aggregate under the app's key on every deployment and
every schedule edit, replacing only that key:

```json
{"<app key>": {
  "app": "pivot_control", "schema": 1,
  "targets": {"run": "run", "forward": "forward", "reverse": "reverse"},
  "percent_timer_cycle_s": 60, "default_speed_percent": 50,
  "max_run_s": null, "timezone": "Australia/Brisbane",
  "schedules": [
    {"slot": 1, "enabled": true, "start_ts": 1795118400000,
     "start_local": "2026-11-20T06:00:00+10:00", "direction": "forward",
     "speed_percent": 50, "stop_angle_deg": 180, "duration_s": null}
  ],
  "updated_ts": 1795050000000}}
```

All four slots are always present. A schedule starts its run at `start_ts` with the same
fields as a start command; `duration_s` is capped at `max_run_s`.

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
