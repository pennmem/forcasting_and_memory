"""Flask routes.

Map from the psiTurk routes this replaces:

    psiTurk                 here
    -------                 ----
    /ad                     (gone -- Prolific's study listing is the ad)
    /consent                /consent
    /exp                    /exp
    /sync (POST)            /api/data
    /complete, /worker_submitted
                            /api/complete  then  /complete
    /debrief, /quitter      (gone -- the debrief lives in the jsPsych timeline)
"""

import json
import logging
import os
import uuid

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from user_agents import parse as parse_user_agent

from .assignment import (
    AlreadyParticipated,
    NoSlotsAvailable,
    assign_participant,
    slot_summary,
)
from .models import Participant, Slot, Status, TrialData, utcnow
from .scoring import compute_bonus, score_from_trials

bp = Blueprint("experiment", __name__)
logger = logging.getLogger(__name__)

#: Query parameters Prolific appends to the study URL.
PID_PARAM = "PROLIFIC_PID"
STUDY_PARAM = "STUDY_ID"
SESSION_PARAM = "SESSION_ID"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _config():
    return current_app.config["EXPERIMENT_CONFIG"]


def _session():
    return current_app.config["SESSION_FACTORY"]()


def prolific_params():
    """Pull the Prolific identifiers out of the query string.

    Prolific's own docs show these upper-cased, but participants sometimes
    arrive through links that lower-case them, so accept either.
    """
    args = {key.upper(): value for key, value in request.args.items()}
    return (
        (args.get(PID_PARAM) or "").strip(),
        (args.get(STUDY_PARAM) or "").strip(),
        (args.get(SESSION_PARAM) or "").strip(),
    )


def is_excluded_browser(user_agent_string, rules):
    """Reimplements psiTurk's `browser_exclude_rule` check."""
    if not rules or not user_agent_string:
        return None

    agent = parse_user_agent(user_agent_string)

    for rule in rules:
        key = rule.strip().lower()

        if key == "mobile" and agent.is_mobile:
            return rule
        if key == "tablet" and agent.is_tablet:
            return rule
        if key == "touchcapable" and agent.is_touch_capable:
            return rule
        if key == "pc" and agent.is_pc:
            return rule
        if key == "bot" and agent.is_bot:
            return rule
        if key == "safari" and "safari" in agent.browser.family.lower():
            return rule
        if key and key in user_agent_string.lower():
            return rule

    return None


def client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def render_error(message, detail=None, status_code=400, show_return_link=False):
    config = _config()
    return (
        render_template(
            "error.html",
            message=message,
            detail=detail,
            contact_address=config.contact_email,
            show_return_link=show_return_link,
        ),
        status_code,
    )


# ---------------------------------------------------------------------------
# participant-facing pages
# ---------------------------------------------------------------------------


@bp.route("/")
def index():
    """Landing route -- this is the URL you paste into Prolific."""
    return redirect(url_for("experiment.consent", **request.args))


@bp.route("/consent")
def consent():
    config = _config()
    prolific_pid, study_id, session_id = prolific_params()

    excluded = is_excluded_browser(request.user_agent.string, config.browser_exclude_rule)
    if excluded:
        return render_template(
            "unsupported_browser.html",
            contact_address=config.contact_email,
            rule=excluded,
        ), 403

    if not prolific_pid and not config.allow_debug_mode:
        return render_error(
            "This study must be started from Prolific.",
            "We could not find your Prolific ID in the study link. Please return to "
            "Prolific and open the study from there.",
            status_code=400,
        )

    payment = config.payment
    return render_template(
        "consent.html",
        prolific_pid=prolific_pid,
        study_id=study_id,
        session_id=session_id,
        contact_address=config.contact_email,
        flat_fee=payment["flat_fee_dollars"],
        expected_bonus=payment["expected_bonus_dollars"],
        expected_total=payment["flat_fee_dollars"] + payment["expected_bonus_dollars"],
    )


@bp.route("/exp")
def experiment():
    """Allocate a counterbalance slot and serve the jsPsych task."""
    config = _config()
    prolific_pid, study_id, session_id = prolific_params()

    excluded = is_excluded_browser(request.user_agent.string, config.browser_exclude_rule)
    if excluded:
        return render_template(
            "unsupported_browser.html",
            contact_address=config.contact_email,
            rule=excluded,
        ), 403

    debug_mode = False
    if not prolific_pid:
        if not config.allow_debug_mode:
            return render_error(
                "This study must be started from Prolific.",
                "We could not find your Prolific ID in the study link.",
                status_code=400,
            )
        prolific_pid = f"debug-{uuid.uuid4().hex[:12]}"
        study_id = study_id or "debug-study"
        session_id = session_id or "debug-session"
        debug_mode = True

    with _session() as session:
        try:
            participant = assign_participant(
                session,
                prolific_pid=prolific_pid,
                study_id=study_id,
                session_id=session_id,
                codeversion=config.code_version,
                num_conds=config.num_conds,
                allow_repeats=config.allow_repeats or debug_mode,
                cutoff_minutes=config.cutoff_minutes,
                ip_address=client_ip(),
                user_agent=request.user_agent.string,
                forced_slot=config.task_settings.get("debug_slot"),
            )
        except AlreadyParticipated as exc:
            session.rollback()
            previous = exc.participant
            logger.info("Repeat visit from %s (status=%s)", prolific_pid, previous.status)
            return render_template(
                "already_participated.html",
                contact_address=config.contact_email,
                completion_url=config.completion_url(previous.completion_code)
                if previous.completion_code
                else None,
            ), 403
        except NoSlotsAvailable as exc:
            session.rollback()
            logger.error("Slot allocation failed for %s: %s", prolific_pid, exc)
            return render_error(
                "This study is full.",
                "All available sessions have been taken. Please return the study on "
                "Prolific so it can be offered to someone else.",
                status_code=503,
            )

        session.commit()

        logger.info(
            "Assigned %s to slot %s (uniqueid=%s, attempt=%s)",
            prolific_pid,
            participant.slot,
            participant.uniqueid,
            participant.attempt,
        )

        task_config = dict(config.task_settings)
        task_config.update(
            {
                "uniqueId": participant.uniqueid,
                "prolificPid": participant.prolific_pid,
                "studyId": participant.study_id,
                "sessionId": participant.session_id,
                "slot": participant.slot,
                "condition": participant.condition,
                "counterbalance": participant.slot,
                "attempt": participant.attempt,
                "codeversion": participant.codeversion,
                "contactAddress": config.contact_email,
                "debugMode": debug_mode,
                "dataUrl": url_for("experiment.api_data"),
                "completeUrl": url_for("experiment.api_complete"),
                "assignmentsUrl": url_for("static", filename=config.assignments_filename),
            }
        )

    return render_template("exp.html", task_config=task_config)


@bp.route("/complete")
def complete():
    """Final page. Shows the link back to Prolific if the browser lost it."""
    config = _config()
    uniqueid = request.args.get("uniqueId", "")

    completion_url = None
    with _session() as session:
        participant = (
            session.query(Participant).filter(Participant.uniqueid == uniqueid).one_or_none()
            if uniqueid
            else None
        )
        if participant and participant.completion_code:
            completion_url = config.completion_url(participant.completion_code)

    if completion_url is None:
        completion_url = config.completion_url(config.completion_code)

    return render_template(
        "complete.html",
        completion_url=completion_url,
        contact_address=config.contact_email,
    )


# ---------------------------------------------------------------------------
# JSON API used by static/js/prolific.js
# ---------------------------------------------------------------------------


@bp.post("/api/data")
def api_data():
    """Append a batch of jsPsych trials.

    Called repeatedly during the task rather than once at the end, so a
    participant who drops out still leaves the trials they completed.
    """
    payload = request.get_json(silent=True) or {}
    uniqueid = payload.get("uniqueId")
    trials = payload.get("trials") or []

    if not uniqueid:
        return jsonify({"status": "error", "message": "Missing uniqueId"}), 400

    with _session() as session:
        participant = (
            session.query(Participant).filter(Participant.uniqueid == uniqueid).one_or_none()
        )
        if participant is None:
            return jsonify({"status": "error", "message": "Unknown participant"}), 404

        existing = (
            session.query(TrialData)
            .filter(
                TrialData.participant_id == participant.id,
                TrialData.attempt == participant.attempt,
            )
            .count()
        )

        stored = 0
        for offset, trial in enumerate(trials):
            if not isinstance(trial, dict):
                continue
            session.add(
                TrialData(
                    participant_id=participant.id,
                    attempt=participant.attempt,
                    trial_index=existing + offset,
                    phase=str(trial.get("phase"))[:64] if trial.get("phase") else None,
                    trialdata=json.dumps(trial, default=str),
                )
            )
            stored += 1

        participant.last_seen = utcnow()
        if participant.status == Status.ALLOCATED and stored:
            participant.status = Status.STARTED

        session.commit()

    return jsonify({"status": "ok", "stored": stored})


@bp.post("/api/complete")
def api_complete():
    """Finish a session: recompute the score, record the bonus, hand back the
    Prolific submission URL the browser should redirect to."""
    config = _config()
    payload = request.get_json(silent=True) or {}
    uniqueid = payload.get("uniqueId")

    if not uniqueid:
        return jsonify({"status": "error", "message": "Missing uniqueId"}), 400

    with _session() as session:
        participant = (
            session.query(Participant).filter(Participant.uniqueid == uniqueid).one_or_none()
        )
        if participant is None:
            return jsonify({"status": "error", "message": "Unknown participant"}), 404

        # Store any trials the browser is still holding before scoring.
        trailing = payload.get("trials") or []
        if trailing:
            existing = (
                session.query(TrialData)
                .filter(
                    TrialData.participant_id == participant.id,
                    TrialData.attempt == participant.attempt,
                )
                .count()
            )
            for offset, trial in enumerate(trailing):
                if not isinstance(trial, dict):
                    continue
                session.add(
                    TrialData(
                        participant_id=participant.id,
                        attempt=participant.attempt,
                        trial_index=existing + offset,
                        phase=str(trial.get("phase"))[:64] if trial.get("phase") else None,
                        trialdata=json.dumps(trial, default=str),
                    )
                )
            session.flush()

        failed_competency = bool(payload.get("failedCompetency"))
        participant.failed_competency = failed_competency
        participant.client_score = payload.get("score")
        participant.feedback = payload.get("feedback")
        participant.fullscreen_exit_count = int(payload.get("fullscreenExitCount") or 0)

        # Query the trials rather than reading participant.trials: that
        # collection was loaded before the trailing batch above was inserted,
        # so it would miss the final rounds and under-score the participant.
        attempt_trials = (
            session.query(TrialData)
            .filter(
                TrialData.participant_id == participant.id,
                TrialData.attempt == participant.attempt,
            )
            .order_by(TrialData.trial_index)
            .all()
        )
        server_score, n_scored = score_from_trials(
            attempt_trials, config.task_settings["score_sd"]
        )

        participant.final_score = server_score
        participant.bonus_dollars = (
            0.0 if failed_competency else compute_bonus(server_score, config.payment)
        )

        if failed_competency:
            participant.status = Status.SCREENED_OUT
            code = config.screenout_code or config.completion_code
        else:
            participant.status = Status.COMPLETED
            code = config.completion_code

        participant.completion_code = code
        participant.end_time = utcnow()
        participant.last_seen = utcnow()

        if participant.status == Status.COMPLETED:
            slot = session.get(Slot, participant.slot)
            if slot is not None:
                slot.times_completed += 1

        session.commit()

        if participant.client_score is not None and participant.client_score != server_score:
            logger.warning(
                "Score mismatch for %s: browser reported %s, server computed %s over %s rounds",
                participant.prolific_pid,
                participant.client_score,
                server_score,
                n_scored,
            )

        logger.info(
            "Completed %s slot=%s status=%s score=%s bonus=%.2f",
            participant.prolific_pid,
            participant.slot,
            participant.status,
            server_score,
            participant.bonus_dollars or 0.0,
        )

        completion_url = config.completion_url(code)

        return jsonify(
            {
                "status": "ok",
                "participantStatus": participant.status,
                "score": server_score,
                "bonus": participant.bonus_dollars,
                "completionCode": code,
                "completionUrl": completion_url,
                "fallbackUrl": url_for("experiment.complete", uniqueId=participant.uniqueid),
            }
        )


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------


@bp.get("/health")
def health():
    with _session() as session:
        session.query(Participant).limit(1).all()
    return jsonify({"status": "ok"})


@bp.get("/admin/status")
def admin_status():
    """Recruitment progress. Protect this with HTTP auth at your proxy, or set
    ADMIN_TOKEN and pass ?token=..."""
    expected = os.environ.get("ADMIN_TOKEN")
    if expected and request.args.get("token") != expected:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    config = _config()
    with _session() as session:
        summary = slot_summary(session)
        summary["code_version"] = config.code_version
        summary["completion_code_set"] = bool(config.completion_code)
        summary["screenout_code_set"] = bool(config.screenout_code)

    return jsonify(summary)
