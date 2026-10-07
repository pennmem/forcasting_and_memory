# Memory and Forecasting — experiment server (MFV2)

A small Flask app that serves the AR(1) forecasting / word-judgment task to Prolific
participants and stores the data in SQLite. Requires Python 3.9 or newer (developed on 3.12).

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py                 # http://127.0.0.1:22362/exp  (debug session, no Prolific ID needed)
python run.py --production    # gunicorn, for real participants (serve over HTTPS)
```

Secrets go in a `.env` file or environment variables (they override `config.ini`):
`PROLIFIC_COMPLETION_CODE`, `PROLIFIC_SCREENOUT_CODE`, `SECRET_KEY`, optionally `DATABASE_URL`.
Set `allow_debug_mode = false` in `config.ini` before going live.

## Layout

- `config.ini` — task, timing, payment and server settings
- `server/` — routes, models, slot assignment, scoring
- `templates/` — consent, experiment shell, completion and error pages
- `static/js/` — task logic (`task.js`), Prolific glue (`prolific.js`), helpers
- `static/html/` — instruction and comprehension-check pages
- `static/data/assignments.json` — pre-generated stimuli, one entry per counterbalance slot
  (`num_counters` in `config.ini` must match its length)
- `static/data/wordpool.txt`, `wordpool_categories.csv` — PEERS word pool and word categories
- `scripts/` — `generate_assignments.py` (regenerate stimuli), `export_data.py` (dump the
  database to CSV), `pay_bonuses.py` (bonus payments)
- `static/lib/` — jQuery and the three jsPsych plugins the task uses
