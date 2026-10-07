"""Memory & Forecasting experiment server.

A small Flask application that does the jobs psiTurk used to do -- serve the
task, hand out counterbalance conditions, and store trial data -- with
recruitment and payment handled by Prolific instead of Mechanical Turk.
"""

import logging
import sys
from pathlib import Path

from flask import Flask

from .config import PROJECT_ROOT, get_config
from .models import init_db, make_engine, make_session_factory

__all__ = ["create_app", "PROJECT_ROOT"]


def configure_logging(config):
    level = getattr(logging, config.get("Server Parameters", "loglevel", "info").upper(), logging.INFO)
    logfile = config.get("Server Parameters", "logfile", "-")

    handlers = []
    if logfile and logfile != "-":
        path = Path(logfile)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    else:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def create_app(config=None):
    config = config or get_config()
    configure_logging(config)

    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
        static_url_path="/static",
    )
    app.secret_key = config.secret_key

    engine = make_engine(config.database_url)
    created = init_db(engine, config.num_counters)

    app.config["EXPERIMENT_CONFIG"] = config
    app.config["ENGINE"] = engine
    app.config["SESSION_FACTORY"] = make_session_factory(engine)
    app.config["JSON_SORT_KEYS"] = False

    from .routes import bp

    app.register_blueprint(bp)

    logger = logging.getLogger(__name__)
    logger.info(
        "Experiment server ready: code version %s, %s counterbalance slots (%s new), database %s",
        config.code_version,
        config.num_counters,
        created,
        config.database_url,
    )

    # Settings that are useful while piloting and harmful once real
    # participants arrive. Warn loudly rather than discovering them in the data.
    if not config.completion_code:
        logger.warning(
            "No Prolific completion code configured. Set completion_code in config.ini "
            "or PROLIFIC_COMPLETION_CODE in the environment before running live."
        )

    if not config.screenout_code:
        logger.warning(
            "No Prolific screenout code configured. Participants who fail the competency "
            "check will be sent the normal completion code."
        )

    if config.allow_debug_mode:
        logger.warning(
            "allow_debug_mode is on: /exp can be opened without a Prolific ID. "
            "Set it to false in config.ini before collecting real data."
        )

    if config.task_settings.get("debug_slot") is not None:
        logger.warning(
            "debug_slot is set to %s: EVERY participant will receive that counterbalance "
            "condition. Clear it in config.ini before collecting real data.",
            config.task_settings["debug_slot"],
        )

    if config.task_settings["max_trials"] < 80 or config.task_settings["forecast_start_index"] < 20:
        logger.warning(
            "Running a shortened timeline (forecast_start_index=%s, max_trials=%s). "
            "The full study uses 20 and 80.",
            config.task_settings["forecast_start_index"],
            config.task_settings["max_trials"],
        )

    return app
