"""Tests for the experiment server.

    pip install pytest
    pytest

These cover the parts of the psiTurk replacement that are easy to get wrong and
expensive to discover during data collection: balanced slot assignment, repeat
blocking, server-side scoring, and the Prolific completion hand-off.
"""

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)
HEADERS = {"User-Agent": DESKTOP_UA}


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("PROLIFIC_COMPLETION_CODE", "DONE123")
    monkeypatch.setenv("PROLIFIC_SCREENOUT_CODE", "SCREEN123")
    monkeypatch.setenv("SECRET_KEY", "test-key")

    # config is memoized, so clear it between tests
    import server.config

    server.config._config = None

    from server import create_app

    application = create_app()
    application.config["TESTING"] = True
    yield application

    server.config._config = None


@pytest.fixture()
def client(app):
    return app.test_client()


def task_config_from(response):
    """Pull window.TASK_CONFIG back out of a rendered /exp page."""
    body = response.get_data(as_text=True)
    start = body.index('id="task-config">') + len('id="task-config">')
    end = body.index("</script>", start)
    raw = body[start:end].replace("&#34;", '"').replace("&amp;", "&")
    return json.loads(raw)


def start_session(client, pid):
    response = client.get(f"/exp?PROLIFIC_PID={pid}&STUDY_ID=S&SESSION_ID=X", headers=HEADERS)
    assert response.status_code == 200
    return task_config_from(response)


def forecast_trials(rounds, forecast, actual):
    """A minimal set of trials the server can score."""
    trials = []
    for index in rounds:
        trials.append({"phase": "forecast", "round_index": index, "forecast_value": forecast})
        trials.append(
            {
                "phase": "forecast_feedback_recitation",
                "round_index": index,
                "forecast_value": forecast,
                "true_value": actual,
            }
        )
    return trials


# -- recruitment entry points ------------------------------------------------


def test_root_redirects_to_consent_keeping_prolific_params(client):
    response = client.get("/?PROLIFIC_PID=P1&STUDY_ID=S1&SESSION_ID=X1", headers=HEADERS)
    assert response.status_code == 302
    assert "P1" in response.headers["Location"]


def test_consent_page_has_no_mturk_language(client):
    body = client.get("/consent?PROLIFIC_PID=P1", headers=HEADERS).get_data(as_text=True)
    assert "Prolific" in body
    assert "Mechanical Turk" not in body
    assert "HIT" not in body


def test_mobile_devices_are_turned_away(client):
    response = client.get("/consent?PROLIFIC_PID=P1", headers={"User-Agent": MOBILE_UA})
    assert response.status_code == 403


def test_exp_page_injects_task_config(client):
    config = start_session(client, "P1")
    assert config["prolificPid"] == "P1"
    assert config["counterbalance"] == config["slot"]
    assert config["forecast_start_index"] == 20
    assert config["flat_fee_dollars"] == 3.00


# -- slot assignment ---------------------------------------------------------


def test_slots_are_handed_out_without_repeats(client):
    slots = [start_session(client, f"P{i}")["slot"] for i in range(10)]
    assert len(set(slots)) == 10
    assert sorted(slots) == list(range(10))


def test_reload_keeps_the_same_slot_and_counts_an_attempt(client):
    first = start_session(client, "P1")
    second = start_session(client, "P1")

    assert second["slot"] == first["slot"]
    assert second["uniqueId"] == first["uniqueId"]
    assert second["attempt"] == first["attempt"] + 1


def test_abandoned_sessions_release_their_slot(app):
    """A participant idle past the cutoff should not hold a condition forever."""
    import datetime as dt

    from server.assignment import assign_participant, release_abandoned_slots
    from server.models import Slot, Status

    with app.config["SESSION_FACTORY"]() as session:
        participant = assign_participant(
            session,
            prolific_pid="P_GONE",
            study_id="S",
            session_id="X",
            codeversion="test",
        )
        slot_number = participant.slot
        session.commit()

        assert session.get(Slot, slot_number).times_assigned == 1

        participant.last_seen = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)
        session.commit()

        released = release_abandoned_slots(session, cutoff_minutes=90)
        session.commit()

        assert released == 1
        assert participant.status == Status.ABANDONED
        assert session.get(Slot, slot_number).times_assigned == 0


# -- data collection ---------------------------------------------------------


def test_trials_are_stored_as_they_arrive(client, app):
    from server.models import Participant, Status, TrialData

    config = start_session(client, "P1")
    response = client.post(
        "/api/data",
        json={"uniqueId": config["uniqueId"], "trials": [{"phase": "a"}, {"phase": "b"}]},
        headers=HEADERS,
    )
    assert response.get_json()["stored"] == 2

    with app.config["SESSION_FACTORY"]() as session:
        participant = session.query(Participant).one()
        assert participant.status == Status.STARTED
        assert session.query(TrialData).count() == 2


def test_data_endpoint_rejects_bad_requests(client):
    assert client.post("/api/data", json={"trials": []}, headers=HEADERS).status_code == 400
    assert (
        client.post("/api/data", json={"uniqueId": "nope", "trials": []}, headers=HEADERS).status_code
        == 404
    )


# -- scoring and completion --------------------------------------------------


def test_score_is_recomputed_and_the_browser_is_not_trusted(client):
    config = start_session(client, "P1")
    # forecast 500 against an actual of 505: |error| 5, sd 20 -> 75 points
    trials = forecast_trials(range(20, 25), forecast=500, actual=505)
    client.post("/api/data", json={"uniqueId": config["uniqueId"], "trials": trials}, headers=HEADERS)

    result = client.post(
        "/api/complete",
        json={"uniqueId": config["uniqueId"], "score": 999999, "failedCompetency": False},
        headers=HEADERS,
    ).get_json()

    assert result["score"] == 5 * 75
    assert result["bonus"] == round(4.00 * 375 / 2000, 2)


def test_a_round_is_only_scored_once_even_if_the_feedback_screen_loops(client):
    config = start_session(client, "P1")
    trials = forecast_trials([20], forecast=500, actual=505)
    # The feedback trial repeats until the value is typed correctly.
    trials += forecast_trials([20], forecast=500, actual=505)
    client.post("/api/data", json={"uniqueId": config["uniqueId"], "trials": trials}, headers=HEADERS)

    result = client.post(
        "/api/complete", json={"uniqueId": config["uniqueId"], "score": 0}, headers=HEADERS
    ).get_json()

    assert result["score"] == 75


def test_bonus_is_capped(client, app):
    from server.scoring import compute_bonus

    payment = app.config["EXPERIMENT_CONFIG"].payment
    assert compute_bonus(10**9, payment) == payment["max_bonus_dollars"]
    assert compute_bonus(0, payment) == 0.0


def test_completion_returns_the_prolific_submission_url(client):
    config = start_session(client, "P1")
    result = client.post(
        "/api/complete", json={"uniqueId": config["uniqueId"], "score": 0}, headers=HEADERS
    ).get_json()

    assert result["participantStatus"] == "completed"
    assert result["completionUrl"] == "https://app.prolific.com/submissions/complete?cc=DONE123"


def test_screened_out_participants_get_the_screenout_code_and_no_bonus(client):
    config = start_session(client, "P_FAIL")
    result = client.post(
        "/api/complete",
        json={"uniqueId": config["uniqueId"], "failedCompetency": True, "score": 0},
        headers=HEADERS,
    ).get_json()

    assert result["participantStatus"] == "screened_out"
    assert "SCREEN123" in result["completionUrl"]
    assert result["bonus"] == 0.0


def test_trailing_trials_sent_with_completion_are_scored(client):
    """The last batch rides along with /api/complete, so it must land first."""
    config = start_session(client, "P1")
    result = client.post(
        "/api/complete",
        json={
            "uniqueId": config["uniqueId"],
            "trials": forecast_trials([20], forecast=500, actual=500),
            "score": 0,
        },
        headers=HEADERS,
    ).get_json()

    assert result["score"] == 100


def test_finished_participants_cannot_start_again(client):
    config = start_session(client, "P1")
    client.post("/api/complete", json={"uniqueId": config["uniqueId"], "score": 0}, headers=HEADERS)

    response = client.get("/exp?PROLIFIC_PID=P1&STUDY_ID=S&SESSION_ID=Y", headers=HEADERS)
    assert response.status_code == 403
    assert "DONE123" in response.get_data(as_text=True)


def test_feedback_and_scores_are_persisted(client, app):
    from server.models import Participant

    config = start_session(client, "P1")
    client.post(
        "/api/complete",
        json={
            "uniqueId": config["uniqueId"],
            "score": 123,
            "feedback": "all good",
            "fullscreenExitCount": 2,
        },
        headers=HEADERS,
    )

    with app.config["SESSION_FACTORY"]() as session:
        participant = session.query(Participant).one()
        assert participant.feedback == "all good"
        assert participant.client_score == 123
        assert participant.fullscreen_exit_count == 2
        assert participant.end_time is not None


# -- scoring rule parity with the browser ------------------------------------


@pytest.mark.parametrize(
    "forecast,actual,expected",
    [
        (500, 500, 100),  # exact
        (500, 505, 75),  # 5 off with sd 20
        (500, 510, 50),
        (500, 520, 0),  # exactly sd away
        (500, 600, 0),  # far off, never negative
    ],
)
def test_scoring_rule_matches_utils_js(forecast, actual, expected):
    from server.scoring import score_forecast

    assert score_forecast(forecast, actual, score_sd=20) == expected


# -- operations --------------------------------------------------------------


def test_health_and_status_endpoints(client):
    assert client.get("/health").get_json()["status"] == "ok"

    start_session(client, "P1")
    summary = client.get("/admin/status").get_json()
    assert summary["total_slots"] == 300
    assert summary["slots_in_use"] == 1
