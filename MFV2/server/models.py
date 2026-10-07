"""Database models and engine setup.

Replaces psiTurk's `Participant` model and its single `datastring` JSON blob.
Trials are stored as individual rows so a participant who drops out mid-task
still leaves usable data behind, which the psiTurk save-at-the-end design did
not guarantee.
"""

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Status:
    """Participant lifecycle states."""

    ALLOCATED = "allocated"  # slot reserved, experiment page served
    STARTED = "started"  # at least one trial recorded
    COMPLETED = "completed"  # finished and submitted
    SCREENED_OUT = "screened_out"  # failed the competency check
    ABANDONED = "abandoned"  # held a slot past the cutoff without finishing

    #: States that still count against a counterbalance slot.
    HOLDING_SLOT = (ALLOCATED, STARTED, COMPLETED, SCREENED_OUT)
    #: States a participant cannot return from.
    TERMINAL = (COMPLETED, SCREENED_OUT)


class Slot(Base):
    """One counterbalance slot, i.e. one entry in static/data/assignments.json.

    Kept as its own table so slot allocation is a single atomic UPDATE rather
    than a count over the participants table.
    """

    __tablename__ = "slots"

    slot: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    times_assigned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    times_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<Slot {self.slot} assigned={self.times_assigned} completed={self.times_completed}>"


class Participant(Base):
    __tablename__ = "participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: Server-generated session id. Analogous to psiTurk's `uniqueid`.
    uniqueid: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # Identifiers handed to us by Prolific in the study URL.
    prolific_pid: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    study_id: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[str | None] = mapped_column(String(64))

    slot: Mapped[int] = mapped_column(ForeignKey("slots.slot"), nullable=False, index=True)
    condition: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    codeversion: Mapped[str] = mapped_column(String(32), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default=Status.ALLOCATED, nullable=False)

    #: Incremented when a participant reloads the experiment page. Trials carry
    #: the attempt they belong to so restarts can be filtered out in analysis.
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)

    begin_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    end_time: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    failed_competency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fullscreen_exit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: Score the browser reported, kept only for cross-checking.
    client_score: Mapped[int | None] = mapped_column(Integer)
    #: Score recomputed on the server from the recorded forecast trials. This is
    #: the one bonuses are paid from.
    final_score: Mapped[int | None] = mapped_column(Integer)
    bonus_dollars: Mapped[float | None] = mapped_column(Float)
    bonus_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    feedback: Mapped[str | None] = mapped_column(Text)
    completion_code: Mapped[str | None] = mapped_column(String(64))

    trials: Mapped[list["TrialData"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan", lazy="selectin"
    )

    def is_terminal(self):
        return self.status in Status.TERMINAL

    def to_dict(self):
        return {
            "uniqueid": self.uniqueid,
            "prolific_pid": self.prolific_pid,
            "study_id": self.study_id,
            "session_id": self.session_id,
            "slot": self.slot,
            "condition": self.condition,
            "codeversion": self.codeversion,
            "status": self.status,
            "attempt": self.attempt,
            "begin_time": self.begin_time.isoformat() if self.begin_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "failed_competency": self.failed_competency,
            "fullscreen_exit_count": self.fullscreen_exit_count,
            "client_score": self.client_score,
            "final_score": self.final_score,
            "bonus_dollars": self.bonus_dollars,
            "bonus_paid": self.bonus_paid,
            "feedback": self.feedback,
        }

    def __repr__(self):
        return f"<Participant {self.prolific_pid} slot={self.slot} status={self.status}>"


class TrialData(Base):
    __tablename__ = "trialdata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    participant_id: Mapped[int] = mapped_column(
        ForeignKey("participants.id"), index=True, nullable=False
    )

    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    #: Position within this attempt, assigned by the browser.
    trial_index: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str | None] = mapped_column(String(64), index=True)

    #: The full jsPsych trial object, serialized as JSON.
    trialdata: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    participant: Mapped[Participant] = relationship(back_populates="trials")

    def __repr__(self):
        return f"<TrialData p={self.participant_id} i={self.trial_index} phase={self.phase}>"


def make_engine(database_url, echo=False):
    """Build an engine with the locking behaviour slot allocation depends on.

    SQLite's default deferred transactions would let two workers read the same
    "least used slot" before either writes. Promoting every transaction to
    BEGIN IMMEDIATE takes the write lock up front, which serializes allocation
    across processes. At this study's request rate the cost is irrelevant.
    """
    is_sqlite = database_url.startswith("sqlite")

    kwargs = {"echo": echo, "future": True}
    if is_sqlite:
        kwargs["connect_args"] = {"timeout": 30, "check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True

    engine = create_engine(database_url, **kwargs)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
            # Hand transaction control to SQLAlchemy so the listener below can
            # issue its own BEGIN.
            dbapi_connection.isolation_level = None

        @event.listens_for(engine, "begin")
        def _begin_immediate(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine, num_slots):
    """Create tables and make sure slots 0..num_slots-1 exist."""
    Base.metadata.create_all(engine)

    session_factory = make_session_factory(engine)
    with session_factory() as session:
        existing = {row[0] for row in session.query(Slot.slot).all()}
        missing = [s for s in range(num_slots) if s not in existing]

        if missing:
            session.add_all([Slot(slot=s, times_assigned=0, times_completed=0) for s in missing])
            session.commit()

        # Slots beyond the configured pool are deactivated rather than deleted
        # so participants already assigned to them keep a valid foreign key.
        stale = [s for s in existing if s >= num_slots]
        if stale:
            session.query(Slot).filter(Slot.slot.in_(stale)).update(
                {"active": False}, synchronize_session=False
            )
            session.commit()

    return len(missing)
