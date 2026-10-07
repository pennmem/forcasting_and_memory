"""Slot allocation must be race-free.

The server runs under gunicorn with several threads (and possibly several
worker processes), so two participants can hit /exp at the same instant. If the
read of "least used slot" and the write that claims it are not atomic, both get
the same counterbalance condition and the design quietly goes out of balance.

The engine promotes every transaction to BEGIN IMMEDIATE for exactly this
reason; these tests are what keeps that from being removed by accident.
"""

import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'conc.db'}")

    import server.config

    server.config._config = None
    from server.config import get_config
    from server.models import init_db, make_engine, make_session_factory

    config = get_config()
    engine = make_engine(config.database_url)
    init_db(engine, config.num_counters)

    yield make_session_factory(engine)

    server.config._config = None


def test_threads_never_receive_the_same_slot(session_factory):
    from server.assignment import assign_participant

    n_threads = 8
    per_thread = 12
    results = []
    errors = []
    lock = threading.Lock()

    def allocate(thread_index):
        for i in range(per_thread):
            try:
                with session_factory() as session:
                    participant = assign_participant(
                        session,
                        prolific_pid=f"P_{thread_index}_{i}",
                        study_id="S",
                        session_id="X",
                        codeversion="test",
                    )
                    session.commit()
                    slot = participant.slot
                with lock:
                    results.append(slot)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=allocate, args=(t,)) for t in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors[:3]
    assert len(results) == n_threads * per_thread
    assert len(set(results)) == len(results), "two participants got the same slot"
    assert sorted(results) == list(range(len(results))), "slots did not fill contiguously"


CROSS_PROCESS_WORKER = """
import os, sys
os.environ["DATABASE_URL"] = "sqlite:///" + sys.argv[1]
sys.path.insert(0, sys.argv[2])
os.chdir(sys.argv[2])

from server.config import get_config
from server.assignment import assign_participant
from server.models import make_engine, make_session_factory

config = get_config()
Session = make_session_factory(make_engine(config.database_url))

slots = []
for i in range(15):
    with Session() as session:
        p = assign_participant(
            session,
            prolific_pid="P_%s_%s" % (sys.argv[3], i),
            study_id="S",
            session_id="X",
            codeversion="test",
        )
        session.commit()
        slots.append(p.slot)

print(",".join(str(s) for s in slots))
"""


def test_separate_processes_never_receive_the_same_slot(tmp_path, monkeypatch):
    """The threaded test shares one engine; gunicorn workers do not."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'conc.db'}")

    import server.config

    server.config._config = None
    from server.config import get_config
    from server.models import init_db, make_engine

    config = get_config()
    init_db(make_engine(config.database_url), config.num_counters)
    server.config._config = None

    worker = tmp_path / "worker.py"
    worker.write_text(CROSS_PROCESS_WORKER)

    n_procs = 4
    procs = [
        subprocess.Popen(
            [sys.executable, str(worker), str(tmp_path / "conc.db"), str(PROJECT_ROOT), str(i)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(n_procs)
    ]

    slots = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err[-2000:]
        slots.extend(int(s) for s in out.strip().split(","))

    assert len(set(slots)) == len(slots), "two processes claimed the same slot"
    assert sorted(slots) == list(range(len(slots)))
