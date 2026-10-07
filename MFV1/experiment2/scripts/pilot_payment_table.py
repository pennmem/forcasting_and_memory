#!/usr/bin/env python
"""Build a per-participant payment table for the Prolific pilot from the
exported CSVs (Pilot_Data/participants.csv, Pilot_Data/pilot.csv).

Unlike scripts/pay_bonuses.py, this does not touch a live database -- the
pilot's prolific_pilot.db isn't part of this checkout, only its CSV exports
are. Scores are recomputed from the recorded forecast-feedback trials with
the same scoring rule and bonus schedule as server/scoring.py, rather than
trusting the stored final score.

Payment facts this script relies on (see server/routes.py's finish handler):
  - COMPLETED and SCREENED_OUT participants both reach the finish handler,
    both get `end_time` set, and both get a valid Prolific completion code
    (screenout_code falling back to completion_code for screen-outs). Both
    are therefore submissions Prolific will show and expect an approve/reject
    decision on. Screen-outs get bonus_dollars = 0.0 explicitly, but the flat
    fee is still owed for an approved submission.
  - STARTED / ALLOCATED participants never reach the finish handler: no
    end_time, no completion code was issued. Nothing was submitted back to
    Prolific from this app, so whatever Prolific shows for them (return,
    timeout, or nothing at all) is outside what this script can determine --
    check the Prolific submissions page directly.

Usage:
    python scripts/pilot_payment_table.py
    python scripts/pilot_payment_table.py --out analysis_outputs/pilot_payment_table.csv
"""

import argparse
import configparser
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from server.scoring import compute_bonus, score_forecast  # noqa: E402

PARTICIPANTS_CSV = PROJECT_ROOT / "Pilot_Data" / "participants.csv"
TRIALDATA_CSV = PROJECT_ROOT / "Pilot_Data" / "pilot.csv"
CONFIG_PATH = PROJECT_ROOT / "config.pilot.ini"

# Longest session in the pilot (76 min vs. a ~21 min mean), individually
# reviewed (60/60 forecast trials, 91% distractor accuracy, 10% modal
# forecast share, 19.5 mean abs error -- clears every quality threshold used
# elsewhere in this project). Confirmed good data; pay in full like any other
# completed participant.
VERIFIED_LONG_SESSION_NOTE = "Long session (76 min) but data individually verified as good -- pay in full"
VERIFIED_LONG_SESSION_UNIQUEIDS = {"<redacted>8e358084"}

# The competency check was implemented more strictly than intended (meant to
# be a single check), so these 6 screened-out participants failed through a
# study bug, not bad-faith responding. All 6 spent well under the full task's
# length in-app (8 sec - 2.2 min), so the flat fee alone -- not a completion
# bonus they never had the chance to earn -- is the fair, time-proportionate
# amount. The 2 who did not return still have an approvable submission; the 4
# who returned do not, so there is no payment mechanism to reach them.
SCREENOUT_BUG_UNIQUEIDS = {
    "<redacted>7852eeb3",  # <redacted> -- did not return
    "<redacted>b789c65c",  # <redacted> -- did not return
    "<redacted>d8a6d52f",  # <redacted> -- returned
    "<redacted>489b3c11",  # <redacted> -- returned
    "<redacted>d6ac6891",  # <redacted> -- returned
    "<redacted>c00bb791",  # <redacted> -- returned
}
SCREENOUT_DID_NOT_RETURN_UNIQUEIDS = {
    "<redacted>7852eeb3",
    "<redacted>b789c65c",
}


def load_payment_settings(config_path):
    parser = configparser.ConfigParser()
    parser.read(config_path)
    payment = parser["Payment"]
    return {
        "flat_fee_dollars": float(payment["flat_fee_dollars"]),
        "expected_bonus_dollars": float(payment["expected_bonus_dollars"]),
        "expected_score_for_payment": float(payment["expected_score_for_payment"]),
        "max_bonus_dollars": float(payment["max_bonus_dollars"]),
    }, float(parser["Experiment"]["score_sd"])


def recompute_score(trialdata, participant_col, score_sd):
    """Sum of score_forecast() over each participant's first-seen forecast
    round, mirroring server/scoring.py's score_from_trials -- a participant
    who loops back through a feedback screen (mistyped the recited value)
    logs the same round more than once, and only the first counts."""
    feedback_rows = trialdata[trialdata["phase"] == "forecast_feedback_recitation"].copy()
    feedback_rows["round_index"] = pd.to_numeric(feedback_rows["round_index"], errors="coerce")
    feedback_rows["forecast_value"] = pd.to_numeric(feedback_rows["forecast_value"], errors="coerce")
    feedback_rows["true_value"] = pd.to_numeric(feedback_rows["true_value"], errors="coerce")

    scores = {}
    for _, row in feedback_rows.iterrows():
        uid, round_index = row[participant_col], row["round_index"]
        if pd.isna(round_index):
            continue
        key = (uid, round_index)
        if key in scores:
            continue
        scores[key] = score_forecast(row["forecast_value"], row["true_value"], score_sd)

    per_participant = {}
    for (uid, _round_index), pts in scores.items():
        per_participant[uid] = per_participant.get(uid, 0) + pts

    return per_participant


def build_payment_table(participant_col="db_uniqueid"):
    participants = pd.read_csv(PARTICIPANTS_CSV)
    trialdata = pd.read_csv(TRIALDATA_CSV, low_memory=False)

    payment, score_sd = load_payment_settings(CONFIG_PATH)

    recomputed_scores = recompute_score(trialdata, participant_col, score_sd)

    rows = []
    for _, p in participants.iterrows():
        uid = p[participant_col]
        status = p["db_status"]
        failed_competency = bool(p["db_failed_competency"])
        completed_successfully = status == "completed"

        recomputed_score = recomputed_scores.get(uid)
        stored_score = p["db_final_score"] if pd.notna(p["db_final_score"]) else None

        if status in ("completed", "screened_out"):
            # Both statuses reach the finish handler and get a completion
            # code Prolific will show as a submission (see module docstring).
            score = 0 if failed_competency else (recomputed_score or 0)
            bonus = 0.0 if failed_competency else compute_bonus(score, payment)
            flat_fee = payment["flat_fee_dollars"]
            total_payment = flat_fee + bonus
            if uid in VERIFIED_LONG_SESSION_UNIQUEIDS:
                payment_note = VERIFIED_LONG_SESSION_NOTE
            elif uid in SCREENOUT_BUG_UNIQUEIDS:
                bonus = 0.0
                if uid in SCREENOUT_DID_NOT_RETURN_UNIQUEIDS:
                    total_payment = flat_fee
                    payment_note = (
                        "Screened out by a study bug (<=2 min in-app), not returned -- "
                        "approve on Prolific for the flat fee; no bonus, no task was completed"
                    )
                else:
                    total_payment = 0.0
                    payment_note = (
                        "Screened out by a study bug (<=2 min in-app), then returned -- "
                        "no submission left and no payment mechanism to reach them "
                        f"(would have been ${flat_fee:.2f} flat fee if reachable)"
                    )
            elif completed_successfully:
                payment_note = "Approve on Prolific: flat fee + bonus"
            else:
                payment_note = "Screened out (failed competency): approve for flat fee only, per app design"
        else:
            # started / allocated: no completion code was ever issued, so
            # nothing was submitted to Prolific from this app.
            score = None
            bonus = None
            flat_fee = None
            total_payment = None
            payment_note = "No submission sent to Prolific (session never finished) -- check Prolific dashboard directly"

        score_mismatch = (
            stored_score is not None
            and recomputed_score is not None
            and stored_score != recomputed_score
        )

        if uid in SCREENOUT_DID_NOT_RETURN_UNIQUEIDS:
            returned_submission = False
        elif uid in SCREENOUT_BUG_UNIQUEIDS:
            returned_submission = True
        else:
            returned_submission = None  # unknown -- not confirmed against the Prolific dashboard

        rows.append(
            {
                "prolific_pid": p["db_prolific_pid"],
                "uniqueid": uid,
                "slot": p["db_slot"],
                "started_at": p["db_begin_time"],
                "status": status,
                "completed_successfully": completed_successfully,
                "failed_competency": failed_competency,
                "returned_submission": returned_submission,
                "stored_final_score": stored_score,
                "recomputed_score": recomputed_score,
                "score_mismatch": score_mismatch,
                "flat_fee_dollars": flat_fee,
                "bonus_dollars": bonus,
                "total_payment_dollars": total_payment,
                "note": payment_note,
            }
        )

    table = pd.DataFrame(rows).sort_values("prolific_pid")
    return table


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT / "analysis_outputs" / "pilot_payment_table.csv",
        help="Where to write the CSV (default: analysis_outputs/pilot_payment_table.csv)",
    )
    args = parser.parse_args()

    table = build_payment_table()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)

    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", None)
    print(table.to_string(index=False))

    n_completed = (table["status"] == "completed").sum()
    n_screened_out = (table["status"] == "screened_out").sum()
    n_unfinished = table["status"].isin(["started", "allocated"]).sum()
    total_owed = table["total_payment_dollars"].dropna().sum()

    print()
    print(f"{n_completed} completed, {n_screened_out} screened out, {n_unfinished} never finished")
    print(f"Total payment owed (completed + screened-out): ${total_owed:.2f}")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
