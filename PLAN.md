# `presence_replay` — Home Assistant custom integration

Implementation brief. Build a HACS-installable custom integration that records
light brightness history and replays it as a presence simulation.

## Problem

Home Assistant stopped recording light attributes in the recorder database in
2024.8 ([core#121776](https://github.com/home-assistant/core/pull/121776)) —
brightness and colour temp are no longer retained, because automations, light
effects, and adaptive-lighting integrations can generate enormous volumes of
`state_attributes` rows.

Consequence: existing presence simulators (notably
[slashback100/presence_simulation](https://github.com/slashback100/presence_simulation))
replay on/off correctly but have no brightness data to work from, so every light
comes back at whatever default the integration picks. A house that runs at 40%
in the evening lights up at 100% for two weeks, which is a worse tell than
leaving the lights off.

This integration keeps its own compact event log, independent of the recorder,
and replays it with per-event brightness.

## Goals

- Record level changes for a user-selected set of lights, with negligible storage cost
- Replay a chosen day-offset (default 7 days ago) with realistic brightness, looping daily
- Snapshot a reference period to disk so long trips don't feed the simulation its own output
- Full UI configuration: config flow, options flow, switch entity, no YAML
- Survive HA restarts, DST transitions, and unavailable lights

## Non-goals

- Colour temperature / RGB replay (design the data model to allow it later, don't build it)
- Replaying non-light domains (media players, covers) — out of scope for v1
- Any dependency on the recorder, `history`, or template helper entities

---

## Architecture decisions

These are deliberate. Do not substitute alternatives without flagging it.

**Own event log, not the recorder.** The recorder is the source of the problem.
Store events via `homeassistant.helpers.storage.Store` under
`.storage/presence_replay.<entry_id>`. Use `Store.async_delay_save` with a
300-second delay so bursts of changes batch into one disk write. Keep the
working copy in memory.

**Event-driven capture with a debounce, not polling.**
`async_track_state_change_event` on the configured entities. Each state change
starts (or restarts) a per-entity `async_call_later` timer of
`debounce_seconds` (default 5). Record only when the timer fires, using the
*timestamp of the first change in the burst* and the *final settled level*. This
collapses a 2-second fade from ~40 intermediate events into one, which is the
whole reason polling was used in the prototype. Also drop changes smaller than
`min_delta` (default 3 of 255).

**Point-in-time scheduling, not a sleeping task.** The prototype ran an
`asyncio` loop with `sleep()` between events. Don't. Use
`homeassistant.helpers.event.async_track_point_in_time` to schedule *only the
next* event; its callback applies the action and schedules the following one.
This is DST-correct, cancellable, and doesn't hold a task across restarts. Add a
separate callback at local midnight to rebuild the day's plan.

**`runtime_data`, not `hass.data`.** Use the typed config entry pattern
(HA 2024.6+, and what core is actively migrating everything to):

```python
type PresenceReplayConfigEntry = ConfigEntry[PresenceReplayRuntime]
```

`PresenceReplayRuntime` is a dataclass holding the store, the event log, the
recorder-listener unsubscribe callables, and the scheduler object.

**Level encoding.** A single int per event, `0–255`, where `0` means off. A
non-dimmable light that is on records as `255`. This makes on/off and brightness
one series and makes replay a single `light.turn_on(brightness=...)` or
`light.turn_off()` decision.

---

## File tree

```
custom_components/presence_replay/
├── __init__.py           # setup/unload, runtime_data wiring, service registration
├── manifest.json
├── const.py              # DOMAIN, defaults, option keys
├── config_flow.py        # config flow + options flow
├── models.py             # PresenceReplayRuntime, LightEvent dataclasses
├── store.py              # Store wrapper: load, append, prune, snapshot, export
├── recorder.py           # state-change listeners + debounce (name it recorder.py, not logger.py)
├── scheduler.py          # plan building + point-in-time replay engine
├── switch.py             # the on/off control -- also snapshots on turn_on
├── sensor.py             # diagnostic sensors
├── websocket_api.py      # presence_replay/history command, feeds the card below
├── frontend.py           # serves www/ and auto-registers the card as a resource
├── www/
│   └── presence-replay-history-card.js  # bundled Lovelace card, no build step
├── services.yaml
├── strings.json
└── translations/en.json
hacs.json
README.md
```

## Bundled history card

A vanilla-JS Lovelace card (`www/presence-replay-history-card.js`, no
bundler/lit dependency) graphs the event log as a step chart per light.
`frontend.py` serves it via `hass.http.async_register_static_paths` and
calls `add_extra_js_url` so it's loaded for every dashboard without a
manual resource entry. `websocket_api.py` registers an admin-gated
`presence_replay/history` command that returns the same shape as
`export_log` plus the snapshot slot; the card calls it directly rather than
piggybacking on the export service.

This pulls in `http`, `frontend`, and `websocket_api` as manifest
dependencies -- a departure from "no requirements" above, but not from the
"independent of the recorder/`history`" non-goal: those three components
are the web UI itself and are already running on any real install. It does
mean tests need `home-assistant-frontend` installed (see CI/README dev
setup) since `frontend`'s `async_setup` imports the compiled `hass_frontend`
package.

## Data model

```python
@dataclass(slots=True, frozen=True)
class LightEvent:
    ts: float          # epoch seconds, UTC
    entity_id: str
    level: int         # 0-255, 0 = off
```

Persisted form is a list of 3-element lists — `[[1753400000.0, "light.kitchen", 180], ...]` —
not dicts. At ~40 bytes per event and a realistic few hundred events per day,
three weeks of history stays comfortably under a megabyte.

```json
{
  "version": 1,
  "minor_version": 1,
  "data": {
    "events": [[1753400000.0, "light.kitchen", 180]],
    "snapshot": {"created": 1753400000.0, "days": 7, "events": []}
  }
}
```

Implement `async_migrate_entry` from day one even though there's nothing to
migrate yet — it's much cheaper than retrofitting it after users have data.

---

## Config flow

**Step `user`:** name (`TextSelector`), lights
(`EntitySelector` with `domain="light"`, `multiple=True`). Validate at least one
entity is chosen. Title the entry from the name. Allow multiple entries — someone
may want separate schedules for upstairs and downstairs.

**Options flow:** all of the following, with the constants living in `const.py`.

| Option | Default | Notes |
|---|---|---|
| `lights` | — | Re-selectable after setup |
| `delta_days` | 7 | How far back to replay |
| `jitter_seconds` | 300 | ±N randomisation per event; 0 disables |
| `transition` | 2 | Fade seconds; 0 omits the parameter entirely |
| `retention_days` | 21 | Log pruning threshold |
| `debounce_seconds` | 5 | Burst collapse window |
| `min_delta` | 3 | Ignore level changes below this |
| `use_snapshot` | false | Replay the frozen snapshot rather than rolling history |
| `restore_on_stop` | true | Return lights to their pre-simulation state |

Do **not** assign `self.config_entry` in the options flow — it's set
automatically and explicit assignment has been deprecated since 2024.11. Reload
the entry on options update via `entry.async_on_unload(entry.add_update_listener(...))`.

## Entities

All entities share one `DeviceInfo` (identifiers `{(DOMAIN, entry.entry_id)}`)
so the integration presents as a single device.

**`switch`** — the control. `SwitchEntity` + `RestoreEntity`; on restart, if the
restored state was on, resume the simulation automatically. `turn_on` starts the
scheduler, `turn_off` stops it and restores prior light states when
`restore_on_stop` is set. This is the entity automations target.

**`sensor`** (all `EntityCategory.DIAGNOSTIC`):

- `events_recorded` — count in the log
- `history_span` — days between oldest and newest event, `device_class: duration`
- `next_action` — `device_class: timestamp`, the next scheduled point in time; `None` when idle
- `replaying_date` — which historical date is currently being played back

No separate snapshot control -- `switch.turn_on` calls the snapshot service
itself (with the configured `delta_days`) before starting the scheduler, so
arming the replay always freezes a fresh reference window.

## Services

Register with `async_register_admin_service`; define schemas in `services.yaml`
with matching `strings.json` entries.

- `presence_replay.snapshot` — freeze the last N days into the snapshot slot. Target: config entry.
- `presence_replay.clear_log` — wipe recorded events. Requires confirmation text in the UI schema.
- `presence_replay.export_log` — `SupportsResponse.ONLY`, returns the event list as response data for debugging from Developer Tools.

## Scheduler behaviour

`build_plan(target_date) -> tuple[dict[str, int], list[ScheduledEvent]]`

1. Take the local-midnight boundaries of `target_date`. Compute them with
   `homeassistant.util.dt.start_of_local_day`, never `timedelta(days=1)`
   arithmetic — that's an hour wrong twice a year.
2. Baseline = the last recorded level per entity at or before that midnight.
3. Events = everything strictly inside the day, converted to
   seconds-since-midnight, sorted.
4. Apply jitter to events only, never the baseline, so each simulated day starts
   from a deterministic state.

On start:

1. Apply the baseline immediately.
2. Collapse every already-past event into one apply per light using its most
   recent value. Starting the switch at 19:00 must not fast-forward the morning.
3. Schedule the next future event with `async_track_point_in_time`.
4. Schedule a rollover at the next local midnight that rebuilds the plan for
   `today - delta_days`.

On stop: cancel all scheduled callbacks, and if `restore_on_stop`, reapply the
light states captured at start.

---

## Edge cases

Handle each of these explicitly; several have bitten the existing integrations.

- **Feedback loop.** With `use_snapshot: false` and a trip longer than
  `delta_days`, the simulation begins replaying its own jittered output and drift
  compounds. Detect this: if any event being replayed was itself written while
  the switch was on, log a warning once per session pointing at the snapshot
  option. (Tag events written during replay with a fourth optional field, or
  track replay windows separately — implementer's choice, but the warning must fire.)
  `use_snapshot` defaults to `true` and is (re-)captured on every `turn_on`,
  so this is opt-out rather than something the user has to remember to arm.
- **Snapshot running dry.** A snapshot only contains `delta_days` calendar
  dates; once a trip runs longer than that, naively continuing to advance
  `target_date` walks past the dates the snapshot has events for and the
  house silently freezes (no drift, but no more variation either). The
  target-date calculation must instead cycle back through the snapshot's own
  date range, anchored to when it was taken, once real time runs past it.
- **Empty or too-short log.** If the target date has no events, log a clear
  warning naming the date, and leave lights untouched rather than turning
  everything off.
- **Unavailable light at replay time.** Skip and continue; don't abort the day.
- **Entity renamed or removed.** Log entries reference dead entity IDs. Skip
  silently during replay; surface the count in a diagnostic attribute.
- **HA restart mid-replay.** `RestoreEntity` resumes, and the catch-up logic in
  step 2 above puts lights in the right state for the current time of day.
- **DST.** Covered by `start_of_local_day`, but write an explicit test.
- **Simultaneous manual control.** If someone physically toggles a light during
  a replay, the change gets recorded into the log. That's acceptable — but do not
  let recording during replay corrupt the snapshot.

## Testing

`pytest-homeassistant-custom-component`, `MockConfigEntry`, and
`freezegun` + `async_fire_time_changed` for time travel. Required cases:

- Config flow: happy path, no-lights-selected validation, options update triggers reload
- Debounce: 40 rapid state changes within the window produce exactly one event, timestamped at the first change
- `min_delta`: a 2-step brightness change produces no event
- Plan building: baseline correctly picks up a light that was already on before midnight
- Catch-up: starting at 19:00 applies the 18:00 value once, not the 06:00 value
- DST: a plan built across the spring-forward boundary schedules at correct wall-clock times
- Pruning: events older than `retention_days` are dropped, snapshot events are not
- Restore-on-stop returns lights to pre-simulation state
- Unload removes all listeners and cancels all scheduled callbacks (assert no lingering timers)

## Build phases

1. **Skeleton** — manifest, const, config flow with entity selector, `async_setup_entry`/`async_unload_entry`, runtime_data dataclass. Integration loads and appears in Settings → Devices & Services.
2. **Capture** — store.py + recorder.py, listeners with debounce, delayed save, nightly prune. Verify events accumulate by watching the `.storage` file.
3. **Diagnostics** — sensor platform. Confirms capture is working before any replay code exists.
4. **Replay** — scheduler.py + switch platform. Test with a 1-day delta so you don't wait a week.
5. **Snapshot** — snapshot storage slot, auto-snapshot on switch `turn_on`, `use_snapshot` option (default on), cycling target-date so a frozen window loops indefinitely, feedback-loop warning for the opt-out rolling path.
6. **Options and polish** — full options flow, `restore_on_stop`, services.yaml, translations.
7. **Ship** — tests, hassfest + HACS validation GitHub Actions, ruff config matching core, README, HACS repo metadata.

Phases 1–4 are the working product. 5–7 are what make it worth publishing.

## manifest.json

```json
{
  "domain": "presence_replay",
  "name": "Presence Replay",
  "codeowners": ["@yourhandle"],
  "config_flow": true,
  "documentation": "https://github.com/yourhandle/ha-presence-replay",
  "integration_type": "helper",
  "iot_class": "calculated",
  "issue_tracker": "https://github.com/yourhandle/ha-presence-replay/issues",
  "requirements": [],
  "version": "0.1.0"
}
```

No `requirements` — everything needed is in core. Keep it that way.

## Acceptance criteria

- Installs via HACS, configures entirely through the UI, zero YAML
- After a week of recording, turning the switch on reproduces that week's
  lighting including brightness levels, with jitter applied
- Turning the switch off restores the previous state
- `hassfest` and `hacs/action` both pass
- Reloading or reconfiguring the entry leaves no orphaned listeners or timers