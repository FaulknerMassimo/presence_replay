# Presence Replay

A Home Assistant custom integration that records light brightness history and
replays it as a presence simulation — with real brightness levels, not just
on/off.

## Why

Home Assistant stopped recording light attributes in the recorder database in
[2024.8](https://github.com/home-assistant/core/pull/121776). Brightness and
colour temperature are no longer retained, because automations, light
effects, and adaptive-lighting integrations can generate enormous volumes of
`state_attributes` rows.

The consequence: existing presence simulators replay on/off correctly but
have no brightness data to work from, so every light comes back at whatever
default the integration picks. A house that runs at 40% in the evening lights
up at 100% for two weeks — a worse tell than leaving the lights off.

Presence Replay keeps its own compact event log, independent of the
recorder, and replays it with per-event brightness.

## Features

- Records level changes for a chosen set of lights, at negligible storage
  cost (own event log, not the recorder)
- Replays a chosen day-offset (default 7 days ago), looping daily
- Snapshots a reference period to disk so long trips don't feed the
  simulation its own output
- Fully configurable through the UI — config flow, options flow, a switch to
  arm/disarm, diagnostic sensors, no YAML
- Survives HA restarts, DST transitions, and unavailable lights

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories → add this repository as an
   "Integration"
2. Search for "Presence Replay" and install
3. Restart Home Assistant

### Manual

Copy `custom_components/presence_replay` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

Settings → Devices & Services → Add Integration → **Presence Replay**.

Give the entry a name and pick the lights you want recorded. You can add more
than one entry if you want separate schedules for different areas (e.g.
upstairs and downstairs).

Each entry creates one device with:

- A **switch** — turn it on to start the replay (freezing a snapshot of the
  last `delta_days` first), off to stop it
- Diagnostic **sensors** — events recorded, history span, next scheduled
  action, and which historical date is currently being replayed

## Options

Reconfigure via the entry's **Configure** button at any time.

| Option | Default | Description |
|---|---|---|
| `lights` | — | Which lights to record and replay |
| `delta_days` | 7 | How many days back to replay |
| `jitter_seconds` | 300 | ± randomisation applied to each replayed event; 0 disables it |
| `transition` | 2 | Fade duration (seconds) passed to `light.turn_on`/`light.turn_off`; 0 omits the parameter |
| `retention_days` | 21 | Events older than this are pruned from the log |
| `debounce_seconds` | 5 | Quiet period after a state change before it's recorded, to collapse fades into one event |
| `min_delta` | 3 | Ignore brightness changes smaller than this (0-255) |
| `use_snapshot` | true | Replay the frozen snapshot instead of the rolling log |
| `restore_on_stop` | true | Return lights to their pre-simulation state when the switch turns off |

## Snapshots and long trips

Turning the switch on freezes the last `delta_days` of recorded history into
a snapshot slot, and `use_snapshot` (on by default) replays that frozen
window instead of the live rolling log. Once real time runs past the days
the snapshot actually covers, it cycles back through the same `delta_days`
dates rather than sliding forward into dates the switch itself generated —
so a trip of any length loops one real reference period indefinitely instead
of replaying its own jittered output back into itself.

Turning `use_snapshot` off reverts to the old rolling-window behavior: each
night looks back `delta_days` from today, which drifts once a trip runs
longer than `delta_days` (a warning is logged once when this happens).

## Services

- `presence_replay.snapshot` — freeze the last `delta_days` of recorded
  events into the snapshot slot. The switch already does this automatically
  on every `turn_on`; this is for forcing a fresh snapshot without a restart
- `presence_replay.clear_log` — permanently delete all recorded events for an
  entry (requires typing `CLEAR` in the confirm field)
- `presence_replay.export_log` — returns the recorded event log as response
  data, for inspection from Developer Tools → Actions

All three take a `config_entry_id` selecting which Presence Replay entry to
act on.

## Design notes

- Events are stored via `homeassistant.helpers.storage.Store`, independent of
  the recorder, at roughly 40 bytes/event — a few hundred events a day keeps
  three weeks of history comfortably under a megabyte
- Capture is event-driven (`async_track_state_change_event`) with a
  per-entity debounce, not polling
- Replay schedules only the *next* event via `async_track_point_in_time`,
  not a sleeping task — this survives restarts and is cleanly cancellable
- Colour temperature/RGB replay and non-light domains are out of scope for
  v1; the data model allows adding them later without a migration

## Non-goals

- Colour temperature / RGB replay
- Replaying non-light domains (media players, covers, …)
- Any dependency on the recorder, `history`, or template helper entities

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install "pytest-homeassistant-custom-component>=0.13.348" ruff
ruff check custom_components tests
pytest tests
```
