#!/usr/bin/env python3
"""Compute Experiment 1 (Overreaction / forecasting) bonuses for Prolific.

Reads the JSON sessions written by fetch_forecasting.py (or the repo's data/
folder) and recomputes every bonus from the recorded forecasts rather than
trusting the browser's payment.bonus_usd field -- the task computes pay
client-side, so a participant who edits their score in the console changes
that field but cannot change this script's answer.

Scoring rule, copied from index.html and kept in step with it:
    score  = 100 * max(0, 1 - |forecast - actual| / SIGMA_E)   per forecast
    bonus  = sum(score) * BONUS_PER_SCORE

    python3 pay_bonuses.py forecasting_export/complete            # preview
    python3 pay_bonuses.py forecasting_export/complete --csv bonuses.csv
Paste the CSV into the bulk-bonus box on the Prolific study page.
"""
import argparse, csv, glob, json, os, sys

# --- must match index.html ---------------------------------------------------
SIGMA_E = 12
N_FORECAST = 40
EXPECTED_SCORE_PER_FORECAST = 29
TARGET_MEAN_BONUS_USD = 4.00
BONUS_PER_SCORE = TARGET_MEAN_BONUS_USD / (N_FORECAST * EXPECTED_SCORE_PER_FORECAST)
# -----------------------------------------------------------------------------


def score_one(forecast, actual):
    return 100 * max(0.0, 1 - abs(forecast - actual) / SIGMA_E)


def compute(session):
    fcs = session.get("forecasts", [])
    total = 0.0
    for f in fcs:
        if f.get("forecast") is None or f.get("actual") is None:
            continue
        total += score_one(float(f["forecast"]), float(f["actual"]))
    return total, len(fcs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="directory of completed-session JSON files")
    ap.add_argument("--csv", help="write Prolific bulk-bonus CSV here")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.folder, "*.json")))
    if not files:
        sys.exit(f"no .json files in {a.folder}")

    rows, flagged = [], []
    for path in files:
        s = json.load(open(path))
        pid = (s.get("participant") or {}).get("prolific_pid")
        stage = (s.get("completion") or {}).get("stage")
        if stage != "complete" or not pid:
            continue
        total, n = compute(s)
        bonus = round(total * BONUS_PER_SCORE, 2)
        claimed = (s.get("payment") or {}).get("bonus_usd")
        note = ""
        if n != N_FORECAST:
            note = f"only {n} forecasts"
        elif claimed is not None and abs(float(claimed) - bonus) > 0.01:
            note = f"browser claimed ${float(claimed):.2f}"
            flagged.append(pid)
        rows.append((pid, os.path.basename(path), total, n, bonus, note))

    print(f"{'Prolific ID':<26} {'file':<18} {'score':>7} {'n':>3} {'bonus':>7}  note")
    print("-" * 78)
    for pid, fn, total, n, bonus, note in rows:
        print(f"{pid:<26} {fn:<18} {total:7.1f} {n:>3} {bonus:7.2f}  {note}")
    print("-" * 78)
    print(f"{len(rows)} participants, ${sum(r[4] for r in rows):.2f} in bonuses"
          + (f"   ({len(flagged)} flagged: browser total disagrees with recomputation)" if flagged else ""))

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            for pid, _, _, _, bonus, _ in rows:
                w.writerow([pid, f"{bonus:.2f}"])
        print(f"\nwrote {a.csv} -- paste its contents into Prolific's bulk bonus box")


if __name__ == "__main__":
    main()
