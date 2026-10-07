#!/usr/bin/env python
"""Import an existing psiTurk database into the Prolific schema.

The psiTurk pilot data lives in `participants.db` as one `datastring` JSON blob
per row of the `assignments` table. This unpacks those blobs into the new
`participants` / `trialdata` tables so old and new sessions can be exported and
analyzed together.

    python scripts/migrate_psiturk_db.py --source participants.db --target prolific.db

Imported participants get `prolific_pid` set to their old MTurk worker id
prefixed with `mturk:`, and their psiTurk `counterbalance` becomes the
counterbalance slot. This is read-only with respect to the source database.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from server.config import get_config  # noqa: E402
from server.models import (  # noqa: E402
    Participant,
    Slot,
    Status,
    TrialData,
    init_db,
    make_engine,
    make_session_factory,
    utcnow,
)
from server.scoring import compute_bonus, score_from_trials  # noqa: E402

#: psiTurk status codes, from psiturk/models.py
PSITURK_STATUS = {
    1: Status.ALLOCATED,  # NOT_ACCEPTED
    2: Status.ALLOCATED,  # ALLOCATED
    3: Status.STARTED,  # STARTED
    4: Status.COMPLETED,  # COMPLETED (task finished; HIT not yet submitted)
    5: Status.COMPLETED,  # SUBMITTED
    6: Status.COMPLETED,  # CREDITED
    7: Status.ABANDONED,  # QUITEARLY
    8: Status.COMPLETED,  # BONUSED
}

#: Phases that show a participant reached the end of the timeline.
COMPLETION_PHASES = {"finished", "score_summary"}
SCREENOUT_PHASES = {"competency_failed"}

#: The task always opens with this trial, so a second one means a reload.
ATTEMPT_START_PHASE = "enter_fullscreen"


def split_into_attempts(trials):
    """Assign an attempt number to each trial.

    A psiTurk `datastring` is append-only: if a participant reloaded the task,
    their second run is concatenated onto the first with nothing marking the
    boundary. The new schema records attempts explicitly, so recover them here
    by splitting at each fresh `enter_fullscreen` trial.

    Returns a list of (attempt_number, trial) pairs.
    """
    attempts = []
    attempt = 1

    for index, trial in enumerate(trials):
        if index > 0 and isinstance(trial, dict) and trial.get("phase") == ATTEMPT_START_PHASE:
            attempt += 1
        attempts.append((attempt, trial))

    return attempts


def infer_status(trials, psiturk_status):
    """Work out how far a participant actually got.

    psiTurk leaves `status` at NOT_ACCEPTED for every session run through
    `psiturk debug`, so the whole pilot looks unstarted if we trust that column.
    The recorded phases say what really happened, so use those first and fall
    back to the status code only when the trials are inconclusive.

    Where a session contains several attempts, the last terminal phase wins: a
    participant who failed the competency check, reloaded, and then finished is
    completed, not screened out.
    """
    last_completion = -1
    last_screenout = -1

    for index, trial in enumerate(trials):
        if not isinstance(trial, dict):
            continue
        phase = trial.get("phase")
        if phase in COMPLETION_PHASES:
            last_completion = index
        elif phase in SCREENOUT_PHASES:
            last_screenout = index

    if last_completion >= 0 and last_completion > last_screenout:
        return Status.COMPLETED
    if last_screenout >= 0:
        return Status.SCREENED_OUT

    return PSITURK_STATUS.get(psiturk_status, Status.STARTED)


def find_source_table(conn):
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    for table in tables:
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "datastring" in columns:
            return table, columns
    raise RuntimeError(f"No table with a `datastring` column found. Tables: {tables}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT / "participants.db",
        help="psiTurk SQLite database to read",
    )
    parser.add_argument(
        "--target",
        type=Path,
        help="Destination SQLite file. Defaults to the database_url in config.ini.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what would be imported and stop")
    args = parser.parse_args()

    if not args.source.exists():
        raise SystemExit(f"Source database not found: {args.source}")

    config = get_config()
    target_url = f"sqlite:///{args.target.resolve()}" if args.target else config.database_url

    # The destination can collide with the source through config.ini as easily
    # as through --target, so compare the resolved files rather than the flags.
    target_file = None
    if target_url.startswith("sqlite:///"):
        target_file = Path(target_url[len("sqlite:///"):]).resolve()

    if target_file is not None and target_file == args.source.resolve():
        raise SystemExit(
            f"Refusing to migrate {args.source} into itself.\n"
            f"The destination resolves to the same file. Pass a different --target, "
            f"or change database_url in config.ini."
        )

    source = sqlite3.connect(f"file:{args.source}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row

    table, columns = find_source_table(source)
    rows = source.execute(f"SELECT * FROM {table}").fetchall()
    print(f"Reading {len(rows)} rows from {args.source} (table `{table}`)")

    engine = make_engine(target_url)
    init_db(engine, config.num_counters)
    session_factory = make_session_factory(engine)

    imported = 0
    skipped = 0
    trials_imported = 0

    with session_factory() as session:
        for row in rows:
            raw = row["datastring"]
            if not raw:
                skipped += 1
                continue

            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                print(f"  Could not parse datastring for uniqueid={row['uniqueid']}")
                skipped += 1
                continue

            records = parsed.get("data", []) if isinstance(parsed, dict) else []
            if not records:
                skipped += 1
                continue

            uniqueid = row["uniqueid"]
            if session.query(Participant).filter(Participant.uniqueid == uniqueid).first():
                print(f"  Already imported: {uniqueid}")
                skipped += 1
                continue

            worker_id = row["workerid"] if "workerid" in columns else uniqueid
            slot = int(row["counterbalance"] or 0) if "counterbalance" in columns else 0

            trial_dicts = [
                record.get("trialdata", record) if isinstance(record, dict) else {}
                for record in records
            ]
            status = infer_status(
                trial_dicts, row["status"] if "status" in columns else None
            )
            numbered_trials = split_into_attempts(trial_dicts)
            final_attempt = numbered_trials[-1][0] if numbered_trials else 1

            if session.get(Slot, slot) is None:
                session.add(Slot(slot=slot, times_assigned=0, times_completed=0, active=False))
                session.flush()

            participant = Participant(
                uniqueid=uniqueid,
                prolific_pid=f"mturk:{worker_id}",
                study_id=row["hitid"] if "hitid" in columns else None,
                session_id=row["assignmentid"] if "assignmentid" in columns else None,
                slot=slot,
                condition=int(row["cond"] or 0) if "cond" in columns else 0,
                codeversion=str(row["codeversion"]) if "codeversion" in columns else "psiturk",
                status=status,
                attempt=final_attempt,
                begin_time=utcnow(),
                failed_competency=status == Status.SCREENED_OUT,
            )
            session.add(participant)
            session.flush()

            slot_row = session.get(Slot, slot)
            if slot_row is not None:
                slot_row.times_assigned += 1

            for index, (attempt_number, trial) in enumerate(numbered_trials):
                if not isinstance(trial, dict):
                    continue
                session.add(
                    TrialData(
                        participant_id=participant.id,
                        attempt=attempt_number,
                        trial_index=index,
                        phase=str(trial.get("phase"))[:64] if trial.get("phase") else None,
                        trialdata=json.dumps(trial, default=str),
                    )
                )
                trials_imported += 1

            session.flush()

            # Score only the attempt that counted, matching how live sessions
            # are scored.
            final_trials = [t for t in participant.trials if t.attempt == final_attempt]
            score, _ = score_from_trials(final_trials, config.task_settings["score_sd"])
            participant.final_score = score
            participant.bonus_dollars = compute_bonus(score, config.payment)

            # These people were paid through MTurk. Flag the bonus as settled so
            # scripts/pay_bonuses.py never tries to pay them again on Prolific.
            participant.bonus_paid = True

            if status == Status.COMPLETED and slot_row is not None:
                slot_row.times_completed += 1

            imported += 1

        if args.dry_run:
            session.rollback()
            print("\nDry run: nothing was written.")
        else:
            session.commit()

    source.close()

    print(f"\nImported {imported} participants and {trials_imported} trials into {target_url}")
    print(f"Skipped {skipped} rows (empty, unparseable, or already imported)")


if __name__ == "__main__":
    main()
