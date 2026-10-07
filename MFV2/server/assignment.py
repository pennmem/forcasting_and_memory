"""Counterbalance slot allocation.

psiTurk handed out `counterbalance` values itself; task.js used that number to
index into static/data/assignments.json. This module reproduces that balanced
assignment without psiTurk, and adds the reclaiming of slots held by
participants who walked away.
"""

import datetime as dt
import uuid

from sqlalchemy import func, select

from .models import Participant, Slot, Status, utcnow


class NoSlotsAvailable(RuntimeError):
    """Every counterbalance slot has been used; the study is full."""


class AlreadyParticipated(RuntimeError):
    """This Prolific participant already finished (or was screened out)."""

    def __init__(self, participant):
        super().__init__(f"{participant.prolific_pid} already has status {participant.status}")
        self.participant = participant


def new_uniqueid():
    return uuid.uuid4().hex


def release_abandoned_slots(session, cutoff_minutes):
    """Mark participants who have been idle past the cutoff as abandoned.

    Their slot goes back into the pool by decrementing `times_assigned`, so a
    participant who accepts the study and closes the tab does not permanently
    consume one of the counterbalance conditions.
    """
    if cutoff_minutes is None or cutoff_minutes <= 0:
        return 0

    deadline = utcnow() - dt.timedelta(minutes=cutoff_minutes)

    stale = (
        session.execute(
            select(Participant).where(
                Participant.status.in_((Status.ALLOCATED, Status.STARTED)),
                Participant.last_seen < deadline,
            )
        )
        .scalars()
        .all()
    )

    for participant in stale:
        participant.status = Status.ABANDONED
        slot = session.get(Slot, participant.slot)
        if slot is not None and slot.times_assigned > 0:
            slot.times_assigned -= 1

    if stale:
        session.flush()

    return len(stale)


def _pick_least_used_slot(session):
    """Return the active slot with the fewest assignments.

    Ties are broken by slot number rather than randomly: with a fixed
    assignments.json this gives a deterministic, reproducible fill order and
    the balance is identical either way.
    """
    stmt = (
        select(Slot)
        .where(Slot.active.is_(True))
        .order_by(Slot.times_assigned.asc(), Slot.slot.asc())
        .limit(1)
    )

    if session.bind.dialect.name == "postgresql":
        # SQLite serializes writers already (BEGIN IMMEDIATE); Postgres needs
        # an explicit row lock.
        stmt = stmt.with_for_update()

    return session.execute(stmt).scalars().first()


def find_existing_participant(session, prolific_pid, codeversion=None):
    """Most recent record for this Prolific participant, if any."""
    stmt = select(Participant).where(Participant.prolific_pid == prolific_pid)
    if codeversion is not None:
        stmt = stmt.where(Participant.codeversion == codeversion)

    return (
        session.execute(stmt.order_by(Participant.begin_time.desc()).limit(1)).scalars().first()
    )


def assign_participant(
    session,
    prolific_pid,
    study_id,
    session_id,
    codeversion,
    num_conds=1,
    allow_repeats=False,
    cutoff_minutes=90,
    ip_address=None,
    user_agent=None,
    forced_slot=None,
):
    """Return the `Participant` row for this visit, creating one if needed.

    Everything here runs inside the caller's transaction, which the engine has
    already promoted to a write transaction, so the read-then-update of the
    slot counter is atomic with respect to other workers.

    Raises `AlreadyParticipated` if this person is done and repeats are off,
    and `NoSlotsAvailable` if the study is full.
    """
    existing = find_existing_participant(session, prolific_pid)

    if existing is not None:
        if existing.is_terminal() and not allow_repeats:
            raise AlreadyParticipated(existing)

        if existing.status in (Status.ALLOCATED, Status.STARTED):
            # A refresh or a return visit within the cutoff. Keep their slot
            # and count it as a new attempt.
            existing.attempt += 1
            existing.last_seen = utcnow()
            existing.session_id = session_id or existing.session_id
            existing.study_id = study_id or existing.study_id
            if ip_address:
                existing.ip_address = ip_address
            if user_agent:
                existing.user_agent = user_agent
            session.flush()
            return existing

    release_abandoned_slots(session, cutoff_minutes)

    if forced_slot is not None:
        slot = session.get(Slot, forced_slot)
        if slot is None:
            raise NoSlotsAvailable(f"Slot {forced_slot} does not exist")
    else:
        slot = _pick_least_used_slot(session)
        if slot is None:
            raise NoSlotsAvailable("No active counterbalance slots configured")

    slot.times_assigned += 1

    participant = Participant(
        uniqueid=new_uniqueid(),
        prolific_pid=prolific_pid,
        study_id=study_id,
        session_id=session_id,
        slot=slot.slot,
        condition=slot.slot % num_conds if num_conds else 0,
        codeversion=codeversion,
        status=Status.ALLOCATED,
        attempt=1,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    session.add(participant)
    session.flush()

    return participant


def slot_summary(session):
    """Counts used by the /admin/status page."""
    total_slots = session.scalar(select(func.count()).select_from(Slot).where(Slot.active.is_(True)))
    used_slots = session.scalar(
        select(func.count()).select_from(Slot).where(Slot.active.is_(True), Slot.times_assigned > 0)
    )

    by_status = dict(
        session.execute(
            select(Participant.status, func.count()).group_by(Participant.status)
        ).all()
    )

    return {
        "total_slots": total_slots or 0,
        "slots_in_use": used_slots or 0,
        "slots_free": (total_slots or 0) - (used_slots or 0),
        "participants_by_status": by_status,
    }
