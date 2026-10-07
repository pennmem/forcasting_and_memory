# Memory and Forecasting

An online experiment in which participants track an AR(1) process, forecast its
next value, and perform word-judgment distractor tasks in between. Run by the
Computational Memory Lab at the University of Pennsylvania.

The experiment was originally built on psiTurk and Mechanical Turk. It now runs
on **Prolific**, served by a small self-contained Flask app in `server/`.
psiTurk is no longer a dependency.

## Setup

```bash
./setup_env.sh
```

This creates a single `.venv` on Python 3.12 for both the server and the
analysis code. (psiTurk was what forced the old Python 3.9 / two-environment
split; pass `--split` if you still want a separate `.venv-analysis`.)

Then create a `.env` file in the project root for anything secret:

```bash
PROLIFIC_COMPLETION_CODE=your-completion-code
PROLIFIC_SCREENOUT_CODE=your-screenout-code
SECRET_KEY=generate-with-python-c-import-secrets-print-secrets-token_hex-32
# DATABASE_URL=postgresql+psycopg://user:pass@host/db   # optional
# PROLIFIC_API_TOKEN=...                                # only for --submit bonuses
# PROLIFIC_STUDY_ID=...
# ADMIN_TOKEN=...                                       # protects /admin/status
```

Everything else lives in `config.ini`, which replaces psiTurk's `config.txt`.
Environment variables always override it, so no secret needs to be committed.

## Running

```bash
source .venv/bin/activate
python run.py
```

Open <http://127.0.0.1:22362/exp> to run through the task yourself. With no
Prolific ID in the URL the server creates a throwaway debug session, which is
the equivalent of `psiturk debug`. Turn that off with `allow_debug_mode = false`
in `config.ini` before going live.

To see what a participant sees, start at the top of the funnel instead, with the
query parameters Prolific would supply:

```bash
open "http://127.0.0.1:22362/?PROLIFIC_PID=test01&STUDY_ID=dev&SESSION_ID=dev1"
```

Data goes to `prolific.db`. The psiTurk pilot database is a separate file
(`participants.db`) and is never written to.

Piloting the task end to end takes about 20 minutes at the real settings. To
click through it quickly, lower `forecast_start_index`, `max_trials` and
`distractor_length_ms` in `config.ini` — the server warns at startup whenever a
shortened timeline is in effect, so you cannot leave it that way by accident.

For real participants:

```bash
python run.py --production      # gunicorn
```

The server must be reachable over HTTPS. Put it behind a reverse proxy
(nginx, Caddy) or a host that terminates TLS for you.

## Setting up the Prolific study

1. Create a study in Prolific and choose **"I'll use my own study link"**.
2. Set the study URL to your server's root, with Prolific's URL parameters:

   ```
   https://your-server.example.edu/?PROLIFIC_PID={{%PROLIFIC_PID%}}&STUDY_ID={{%STUDY_ID%}}&SESSION_ID={{%SESSION_ID%}}
   ```

3. Choose **"I'll redirect them using a URL"** for completion, and create two
   completion codes:
   - one for normal completion, put it in `PROLIFIC_COMPLETION_CODE`
   - one for failing the attention check, put it in `PROLIFIC_SCREENOUT_CODE`
     (set its action to *approve* — screened-out participants are still paid for
     their time)
4. Set the base payment to match `flat_fee_dollars` in `config.ini`.
5. Set screening (age, native language, country) in Prolific's participant
   filters. These used to live in the MTurk HIT qualifications and in `ad.html`;
   Prolific handles them, so the task no longer asks.
6. Set the device filter to desktop only. The server also rejects phones and
   tablets, but filtering in Prolific avoids wasting participants' time.
7. Set "Number of participants" on the Prolific study itself to how many you
   actually want. `num_counters` in `config.ini` does **not** cap recruitment —
   it only sizes the pool of counterbalance conditions the server balances
   across. Once every slot has been used once, the server reuses the
   least-used one rather than turning people away, so it is Prolific's own
   participant cap that actually stops recruitment.

Set `num_counters` in `config.ini` to at least the number of participants you
plan to recruit, and make sure the file named by `assignments_filename` has
that many entries.

## Running a pilot

`config.pilot.ini` is a complete second configuration for a smaller run — 40
participants (20 at rho=0.6, 20 at rho=0.7) instead of the full 300 — with
everything else (80-round task, scoring rule, payment schedule) identical to
`config.ini`. It uses its own stimuli file, database, and log, so a pilot never
mixes with the full study's data:

| | full study | pilot |
| --- | --- | --- |
| config | `config.ini` | `config.pilot.ini` |
| stimuli | `static/data/assignments.json` (300) | `static/data/assignments_pilot.json` (40) |
| database | `prolific.db` | `prolific_pilot.db` |
| `experiment_code_version` | `3.0.0` | `3.0.0-pilot40` |

Point any command at it with the `CONFIG_PATH` environment variable, which
every entry point (`run.py`, `wsgi.py`, and the `scripts/`) reads:

```bash
CONFIG_PATH=config.pilot.ini python run.py
CONFIG_PATH=config.pilot.ini python scripts/export_data.py --out db_exports/pilot40.csv
CONFIG_PATH=config.pilot.ini python scripts/pay_bonuses.py
```

Set up a **separate Prolific study** for the pilot (its own listing, its own
completion/screenout codes in `config.pilot.ini`, "Number of participants" set
to 40) rather than reusing the full study's — the two need different links
regardless of which server config serves them.

`assignments_pilot.json` was generated with:

```bash
python scripts/generate_assignments.py \
    --num-participants 40 \
    --output static/data/assignments_pilot.json \
    --seed "20260904-pilot40-rho-conditioned"
```

`--num-participants` must divide evenly by 4 (2 rho values × 2 start types) for
the design to balance; 40 gives exactly 10 per cell, i.e. 20 per rho. Running
`generate_assignments.py` with no arguments is unchanged — it still (re)writes
the full 300-participant `assignments.json` with the original seed. Use a
distinct `--seed` for any other file so it's unambiguous later that the two
were generated independently.

To make a differently-sized pilot (or a second one later), repeat that command
with a different `--num-participants`/`--output`/`--seed` and copy
`config.pilot.ini` to a new file with matching `num_counters`,
`assignments_filename`, `database_url`, and `experiment_code_version`.

## Monitoring and payment

```bash
curl https://your-server/admin/status          # slots used, participants by status
python scripts/export_data.py                  # write db_exports/*.csv
python scripts/pay_bonuses.py                  # preview bonuses owed
python scripts/pay_bonuses.py --csv bonuses.csv    # for Prolific's bulk bonus box
python scripts/pay_bonuses.py --submit --mark-paid # via the Prolific API
```

Bonuses are recomputed on the server from the recorded forecast trials, not
taken from whatever score the browser reported, so a participant editing their
score in the console cannot change what they are paid.

## Migrating the psiTurk pilot data

```bash
python scripts/migrate_psiturk_db.py --source participants.db
```

This unpacks psiTurk's `datastring` blobs into the new tables so old and new
sessions export together. Imported participants get `prolific_pid` set to
`mturk:<worker id>` and are flagged as already paid, so they can never appear in
a Prolific bonus payment. Sessions where a participant reloaded mid-task are
split into separate attempts, which psiTurk's append-only format did not record.

The exported CSV keeps the psiTurk column names, so `notebooks/analysis.ipynb`
runs against it unchanged.

## Tests

```bash
pytest
```

Covers slot assignment and balance, repeat blocking, abandoned-slot reclaim,
server-side scoring, and the Prolific completion hand-off.

## Layout

| Path | What it is |
| --- | --- |
| `server/` | The Flask app: config, models, slot assignment, scoring, routes |
| `run.py`, `wsgi.py` | Entry points (dev server and gunicorn) |
| `config.ini` | All experiment, payment, and server settings |
| `config.pilot.ini` | Same, for the 40-participant pilot (see "Running a pilot") |
| `static/js/task.js` | The jsPsych timeline |
| `static/js/prolific.js` | Data recording client (replaces `psiturk.js`) |
| `static/js/utils.js` | Scoring and rendering helpers |
| `static/data/assignments.json` | Pre-generated per-participant stimuli (full study, N=300) |
| `static/data/assignments_pilot.json` | Same, for the 40-participant pilot |
| `static/data/assignments_v1.json` | Archived pre-conditioning stimuli (psiTurk pilot cohort) |
| `templates/` | Consent, experiment, completion, and error pages |
| `scripts/generate_assignments.py` | Builds `assignments.json` |
| `scripts/export_data.py` | Database to CSV |
| `scripts/pay_bonuses.py` | Bonus computation and Prolific payment |
| `scripts/migrate_psiturk_db.py` | Imports the old psiTurk database |
| `notebooks/analysis.ipynb` | Analysis |
| `tests/` | Server tests |

### Changing the task

Trial counts, timings, the scoring rule, and payment amounts all come from
`config.ini` and are injected into the page, so the server and the browser
cannot disagree about them. To pilot a short version, lower
`forecast_start_index` and `max_trials` there rather than editing `task.js`.

Do not regenerate `assignments.json` once data collection has started — slot
numbers in the database point into it by index.

## Stimulus generation and realized rho

A single 80-point AR(1) draw has a sample rho that scatters with SD ≈ 0.10 and
sits ≈ 0.06 *below* the nominal value (Kendall's small-sample bias, about
−(1+3ρ)/T). With the two conditions only 0.1 apart, unconditioned draws overlap
so badly that about 28% of the time a nominal-0.6 series is actually more
persistent than a nominal-0.7 series.

`scripts/generate_assignments.py` therefore resamples each series until its
realized rho lands within `RHO_TOLERANCE` (0.01) of the nominal value, measured
both over the full series and over the forecast rounds alone — the window the
analysis regresses on. Costs about 70 draws per assignment and a few seconds in
total. The result:

| | before | after |
| --- | --- | --- |
| bias in realized rho | −0.055 to −0.066 | ≈ 0.000 |
| within-condition SD | 0.10 – 0.12 | 0.006 |
| P(0.6 series more persistent than a 0.7 series) | 27.6% | 0% |

Each assignment records `ar1.realized_rho_full` and
`ar1.realized_rho_forecast_window`. **Analyses that ask whether participants
over- or under-react should benchmark a participant's implied rho against these,
not against the nominal `rho`.** With conditioning the two are within 0.01 of
each other so it rarely matters, but it mattered a great deal before.

`notebooks/analysis.ipynb` does this: Result 1 tests implied persistence against
each participant's realized rho, and reports the nominal-rho version underneath
as a robustness row. `get_realized_rho()` reads the stored field when present
and recomputes it from the series otherwise, so the same measurement applies to
the pilot cohort, whose stimulus file predates the field.

If you change `forecast_start_index` in `config.ini`, the conditioning window no
longer matches the analysis window; update `FORECAST_START_INDEX` in the
generator and regenerate.

### Stimulus versions

| File | Used by |
| --- | --- |
| `static/data/assignments.json` | `experiment_code_version` 3.0.0 (the full 300-participant study) |
| `static/data/assignments_pilot.json` | `experiment_code_version` 3.0.0-pilot40 (the 40-participant pilot) |
| `static/data/assignments_v1.json` | the psiTurk pilot and 2.x — unconditioned rho |

These files contain **different series at the same slot numbers**. A given
cohort's participants index into whichever file was configured when they ran
(`assignments_filename` in the matching `config*.ini`), not necessarily
`assignments.json`. Anything analyzing a cohort must load the file that
`experiment_code_version` says it used, or it will silently pair participants'
responses with stimuli they never saw. Split on `db_codeversion` in the export
and pick the matching file.

## psiTurk leftovers

The psiTurk config, custom routes, client library, and MTurk-only templates have
been deleted. Two things were deliberately kept:

- `participants.db` — the psiTurk pilot database. Keep it until you have run
  `scripts/migrate_psiturk_db.py` and checked the export.
