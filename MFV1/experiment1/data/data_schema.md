# Data JSON Structure

Each file itself is a different trial. To be able to download data, add `?debug=1` in the URL and use the Download data button after finishing the task.

One JSON file is one participant session. Session settings live under `design`. Round-level responses live under `observations` and `forecasts`. Word-judgment blocks between rounds live under `distractor_blocks`.

`series.values` is the full AR(1) path in time order (length = `n_observation` + `n_forecast`). Trial fields use a 1-based `series_index`: observation round `r` shows `series.values[r - 1]`, and forecast round `r` predicts `series.values[n_observation + r - 1]`.

Fields ending in `_ms` are `performance.now()` timestamps (ms since page load). `duration_ms`, `response_time_ms`, and `feedback_duration_ms` are elapsed times. `ended_iso` and `ended_wall_iso` are wall-clock ISO timestamps.

Score on each forecast is `100 * max(0, 1 - |forecast - actual| / sigma_e)`. Bonus pay is `total_score * bonus_per_score`.

Each `distractor_blocks` entry is one timed block after a round. Its `judgments` array lists the word responses in that block (`choice` `A` = left Shift, `B` = right Shift).

**Competency / attention check** (after consent, before instructions): three questions matching experiment 2. Participants are screened out only if they miss **both** Q1 (must click Blue) and Q3 (must click Never). Q2 is recorded but does not affect exclusion. Failures are saved with `completion.stage = "screened_out"` and a `competency` object.

## Schema

- **`completion`** — `code`, `ended_wall_iso` (time when they finished).
- **`participant`** — `participant_id`, and when present also `prolific_pid` / `mturk_worker_id` / `mturk_assignment_id` / `mturk_hit_id`.
- **`design`** — Parameters held fixed for the subject's session:
  - `rho`: the AR(1) persistence.
  - `typing_mode`: `forced` or `passive`, determining whether the subject undergoes active or passive recall. `forced`: after each observation value and after each revealed forecast outcome, they must type that number exactly. `passive`: those screens only need Enter (no typing the values).
  - `distractor_task` — randomly chosen between an `animacy` or `size` task.
  - `n_observation` / `n_forecast` — Number of observation rounds and forecast rounds (20 and 40).
  - `process` — Parameters for the underlying time series: `mu`, `sigma_e`, `min`, `max`, plus a short process note. Most cases we use 100, 12, 1, 200 respectively. Values that would exceed the bounds are reflected back into range (bounce at the boundary).
  - `distractor_duration_sec` — `min`, `max` in seconds between rounds.
- **`payment`** — `total_score`, `base_pay_usd`, `bonus_per_score`, `bonus_usd`, `total_pay_usd`. Score rule: `100 * max(0, 1 - |forecast - actual| / sigma_e)`. Bonus is `total_score * bonus_per_score` (scaled so typical accuracy yields about $4 bonus).
- **`series`** — `values` (full path for this run) and `n_values`. Observation round `r` shows `values[r - 1]`. Forecast round `r` predicts `values[n_observation + r - 1]`.
- **`observations`** — Array of observation rounds (see below).
- **`forecasts`** — Array of forecasting rounds (see below).
- **`distractor_blocks`** — Array of between-round word-judgment blocks (see below).
- **`diagnostics`** — `session_log`, `screen_timings`, `client` (`user_agent`, `viewport.width`, `viewport.height`).

### `observations`

Each item has a `round`, `value` (the number shown), `series_index` (1-based index into the process; same as `round` here), `typing_mode` (same as `design.typing_mode`), `duration_ms`, `started_ms`, `ended_ms`, `ended_iso`.

### `forecasts`

Each item has a `round`, `series_index` (1-based process index being predicted), `forecast`, `actual`, `error` (`forecast - actual`), `score`, `response_time_ms`, `feedback_duration_ms`, forecast/feedback timing fields (`forecast_started_ms`, `forecast_submitted_ms`, `feedback_started_ms`, `feedback_ended_ms`), `ended_iso`.

### `distractor_blocks`

Each item is one timed block after a round: `after_phase` (`observation` or `forecast`), `after_round`, `task`, `prompt`, `planned_duration_sec`, `actual_duration_ms`, `started_ms`, `ended_ms`, `ended_iso`, `n_judgments`, and `judgments`.

Each judgment has `word`, `choice` (`A` = left Shift, `B` = right Shift), `choice_label`, `rt_ms`, `shown_at_ms`, `responded_at_ms`.
