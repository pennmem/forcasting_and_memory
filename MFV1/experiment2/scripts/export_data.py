#!/usr/bin/env python
"""Export collected trial data to CSV.

Replaces scripts/export_psiturk_datastring.py, which had to unpack psiTurk's
single `datastring` JSON blob. Trials are now stored as rows, so this mostly
flattens them into the wide format notebooks/analysis.ipynb already reads.

The output keeps the psiTurk column names (`db_uniqueid`, `assignment_slot`,
...) so the existing notebook runs against it without edits.

    python scripts/export_data.py
    python scripts/export_data.py --status completed --latest-attempt-only
"""

import argparse
import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from server.config import get_config  # noqa: E402
from server.models import Participant, Status, TrialData, make_engine, make_session_factory  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "db_exports" / "trialdata_expanded.csv"

#: Column order at the front of the CSV. Anything else is appended alphabetically.
PREFERRED_FIRST = [
    "db_uniqueid",
    "db_prolific_pid",
    "db_study_id",
    "db_session_id",
    "db_status",
    "db_attempt",
    "db_slot",
    "db_condition",
    "db_codeversion",
    "db_final_score",
    "db_bonus_dollars",
    "db_failed_competency",
    "db_begin_time",
    "db_end_time",
    "uniqueId",
    "condition",
    "counterbalance",
    "assignment_slot",
    "rho",
    "start_type",
    "record_number",
    "phase",
    "round_index",
    "task_number",
    "task_type",
    "word",
    "word_index",
    "response",
    "rt",
    "distractor_response",
    "distractor_response_index",
    "distractor_answered",
    "previous_value",
    "forecast_typed_value",
    "forecast_value",
    "forecast_is_numeric",
    "true_value",
    "forecast_error",
    "points_earned",
    "cumulative_score",
    "typed_value",
    "typed_actual_value",
    "typed_actual_correct",
]


def clean_value(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, bool):
        return value
    return value


def participant_columns(participant):
    return {
        "db_uniqueid": participant.uniqueid,
        "db_prolific_pid": participant.prolific_pid,
        "db_study_id": participant.study_id,
        "db_session_id": participant.session_id,
        "db_status": participant.status,
        "db_attempt": participant.attempt,
        "db_slot": participant.slot,
        "db_condition": participant.condition,
        "db_codeversion": participant.codeversion,
        "db_final_score": participant.final_score,
        "db_client_score": participant.client_score,
        "db_bonus_dollars": participant.bonus_dollars,
        "db_failed_competency": participant.failed_competency,
        "db_fullscreen_exit_count": participant.fullscreen_exit_count,
        "db_feedback": participant.feedback,
        "db_begin_time": participant.begin_time.isoformat() if participant.begin_time else None,
        "db_end_time": participant.end_time.isoformat() if participant.end_time else None,
    }


def export_trials(session, statuses=None, latest_attempt_only=False):
    query = session.query(Participant).order_by(Participant.begin_time)
    if statuses:
        query = query.filter(Participant.status.in_(statuses))

    rows = []
    all_columns = set()

    for participant in query.all():
        meta = participant_columns(participant)

        trials = sorted(participant.trials, key=lambda t: (t.attempt, t.trial_index))
        if latest_attempt_only:
            trials = [t for t in trials if t.attempt == participant.attempt]

        for record_number, trial in enumerate(trials):
            try:
                data = json.loads(trial.trialdata)
            except (TypeError, ValueError):
                print(f"  Skipping unparseable trial {trial.id} for {participant.uniqueid}")
                continue

            row = dict(meta)
            row["record_number"] = record_number
            row["trial_attempt"] = trial.attempt
            row["trial_index"] = trial.trial_index

            for key, value in data.items():
                row[key] = clean_value(value)

            rows.append(row)
            all_columns.update(row.keys())

    return rows, all_columns


def export_participants(session, statuses=None):
    query = session.query(Participant).order_by(Participant.begin_time)
    if statuses:
        query = query.filter(Participant.status.in_(statuses))
    return [participant_columns(p) for p in query.all()]


def write_csv(path, rows, columns):
    ordered = [c for c in PREFERRED_FIRST if c in columns]
    ordered += [c for c in sorted(columns) if c not in ordered]

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Trial CSV path")
    parser.add_argument(
        "--status",
        action="append",
        choices=[Status.ALLOCATED, Status.STARTED, Status.COMPLETED, Status.SCREENED_OUT, Status.ABANDONED],
        help="Only export participants with this status (repeatable). Default: all.",
    )
    parser.add_argument(
        "--latest-attempt-only",
        action="store_true",
        help="Drop trials from earlier attempts by participants who reloaded the task",
    )
    args = parser.parse_args()

    config = get_config()
    engine = make_engine(config.database_url)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        rows, columns = export_trials(session, args.status, args.latest_attempt_only)
        participants = export_participants(session, args.status)

    write_csv(args.out, rows, columns)

    participant_path = args.out.parent / "participants.csv"
    if participants:
        write_csv(participant_path, participants, set(participants[0].keys()))

    print(f"Exported {len(rows)} trial rows from {len(participants)} participants")
    print(f"  trials:       {args.out}")
    print(f"  participants: {participant_path}")

    phases = sorted({str(row.get("phase", "")) for row in rows})
    print("\nPhases found:")
    for phase in phases:
        print(" ", phase)


if __name__ == "__main__":
    main()
