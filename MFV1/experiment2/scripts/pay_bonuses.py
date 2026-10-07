#!/usr/bin/env python
"""Compute and pay performance bonuses through Prolific.

Replaces the `compute_bonus` route in psiTurk's custom.py and the
`psiturk bonus` shell command.

Bonuses are recomputed here from the recorded forecast trials rather than
trusting whatever score the browser reported, so a participant who edited their
score in the console does not change what they are paid.

    # See what would be paid, without contacting Prolific
    python scripts/pay_bonuses.py

    # Write the CSV that Prolific's bulk bonus box accepts
    python scripts/pay_bonuses.py --csv db_exports/bonuses.csv

    # Submit the bonus payments through the Prolific API
    PROLIFIC_API_TOKEN=... python scripts/pay_bonuses.py --submit

The API route needs a token with the "Bonus payments" scope and a study id.
Prolific creates the payment as a draft that you must then confirm in the web
interface, so --submit does not move money on its own.
"""

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from server.config import get_config  # noqa: E402
from server.models import Participant, Status, make_engine, make_session_factory  # noqa: E402
from server.scoring import compute_bonus, score_from_trials  # noqa: E402

PROLIFIC_API = "https://api.prolific.com/api/v1"


def collect_bonuses(session, config, recompute=True):
    """Return one row per completed participant with the bonus they are owed."""
    payment = config.payment
    score_sd = config.task_settings["score_sd"]

    participants = (
        session.query(Participant)
        .filter(Participant.status == Status.COMPLETED)
        .order_by(Participant.end_time)
        .all()
    )

    rows = []
    for participant in participants:
        # Sessions imported from the psiTurk database carry an MTurk worker id,
        # not a Prolific one. They were paid through MTurk and must never be
        # included in a Prolific bonus payment.
        if participant.prolific_pid.startswith("mturk:"):
            continue

        if recompute:
            trials = [t for t in participant.trials if t.attempt == participant.attempt]
            score, n_rounds = score_from_trials(trials, score_sd)
        else:
            score, n_rounds = participant.final_score or 0, None

        bonus = compute_bonus(score, payment)

        rows.append(
            {
                "prolific_pid": participant.prolific_pid,
                "uniqueid": participant.uniqueid,
                "slot": participant.slot,
                "score": score,
                "rounds_scored": n_rounds,
                "stored_score": participant.final_score,
                "bonus": bonus,
                "stored_bonus": participant.bonus_dollars,
                "already_paid": participant.bonus_paid,
            }
        )

    return rows


def write_prolific_csv(path, rows):
    """Prolific's bulk bonus box takes `participant_id,amount` lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in rows:
            if row["bonus"] > 0:
                writer.writerow([row["prolific_pid"], f"{row['bonus']:.2f}"])


def submit_to_prolific(rows, api_token, study_id):
    """Create a bonus payment draft through the Prolific API."""
    import requests

    payable = [row for row in rows if row["bonus"] > 0 and not row["already_paid"]]
    if not payable:
        print("Nothing to submit: no unpaid bonuses.")
        return None

    csv_body = "\n".join(f"{row['prolific_pid']},{row['bonus']:.2f}" for row in payable)

    response = requests.post(
        f"{PROLIFIC_API}/submissions/bonus-payments/",
        headers={
            "Authorization": f"Token {api_token}",
            "Content-Type": "application/json",
        },
        json={"study_id": study_id, "csv_bonuses": csv_body},
        timeout=60,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"Prolific rejected the bonus payment: {response.status_code} {response.text}")

    payload = response.json()
    print(f"\nCreated bonus payment draft {payload.get('id')} for {len(payable)} participants.")
    print(f"Total: ${payload.get('total_amount', 0) / 100:.2f}" if payload.get("total_amount") else "")
    print("Confirm it in the Prolific web interface to actually pay it.")
    return payload


def mark_paid(session, rows):
    pids = {row["prolific_pid"] for row in rows if row["bonus"] > 0}
    updated = (
        session.query(Participant)
        .filter(Participant.prolific_pid.in_(pids), Participant.status == Status.COMPLETED)
        .update({"bonus_paid": True}, synchronize_session=False)
    )
    session.commit()
    return updated


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--csv", type=Path, help="Write a Prolific bulk-bonus CSV to this path")
    parser.add_argument("--submit", action="store_true", help="Create a bonus payment via the Prolific API")
    parser.add_argument(
        "--mark-paid",
        action="store_true",
        help="Flag these bonuses as paid in the local database (do this after confirming on Prolific)",
    )
    parser.add_argument(
        "--include-paid",
        action="store_true",
        help="Include participants already flagged as paid",
    )
    args = parser.parse_args()

    config = get_config()
    engine = make_engine(config.database_url)
    session_factory = make_session_factory(engine)

    with session_factory() as session:
        rows = collect_bonuses(session, config)

        if not args.include_paid:
            rows = [row for row in rows if not row["already_paid"]]

        if not rows:
            print("No completed participants awaiting a bonus.")
            return

        print(f"{'Prolific ID':<28} {'Slot':>5} {'Score':>7} {'Rounds':>7} {'Bonus':>8}  Note")
        print("-" * 78)

        total = 0.0
        for row in rows:
            note = ""
            if row["stored_score"] is not None and row["stored_score"] != row["score"]:
                note = f"stored score was {row['stored_score']}"
            print(
                f"{row['prolific_pid']:<28} {row['slot']:>5} {row['score']:>7} "
                f"{str(row['rounds_scored']):>7} {row['bonus']:>8.2f}  {note}"
            )
            total += row["bonus"]

        print("-" * 78)
        print(f"{len(rows)} participants, ${total:.2f} in bonuses")

        if args.csv:
            write_prolific_csv(args.csv, rows)
            print(f"\nWrote {args.csv}")
            print("Paste its contents into the bulk bonus box on your Prolific study page.")

        if args.submit:
            api_token = config.get("Prolific", "api_token")
            study_id = config.get("Prolific", "study_id")

            if not api_token:
                raise SystemExit("Set PROLIFIC_API_TOKEN (or Prolific.api_token in config.ini) to use --submit")
            if not study_id:
                raise SystemExit("Set PROLIFIC_STUDY_ID (or Prolific.study_id in config.ini) to use --submit")

            submit_to_prolific(rows, api_token, study_id)

        if args.mark_paid:
            updated = mark_paid(session, rows)
            print(f"\nFlagged {updated} participants as paid in the local database.")


if __name__ == "__main__":
    main()
