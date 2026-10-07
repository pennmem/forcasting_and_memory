"""Configuration for the Prolific experiment server.

Reads `config.ini` and lets environment variables override anything secret.
This is the replacement for psiTurk's `PsiturkConfig` / `config.txt`.
"""

import configparser
import os
import secrets
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.ini"

# config.ini key -> environment variable that overrides it
ENV_OVERRIDES = {
    ("Server Parameters", "database_url"): "DATABASE_URL",
    ("Server Parameters", "secret_key"): "SECRET_KEY",
    ("Server Parameters", "host"): "HOST",
    ("Server Parameters", "port"): "PORT",
    ("Server Parameters", "server_url"): "SERVER_URL",
    ("Prolific", "completion_code"): "PROLIFIC_COMPLETION_CODE",
    ("Prolific", "screenout_code"): "PROLIFIC_SCREENOUT_CODE",
    ("Prolific", "api_token"): "PROLIFIC_API_TOKEN",
    ("Prolific", "study_id"): "PROLIFIC_STUDY_ID",
}

TRUTHY = {"true", "yes", "on", "1"}


def _load_dotenv():
    """Minimal .env loader so we do not need python-dotenv at runtime."""
    dotenv = PROJECT_ROOT / ".env"
    if not dotenv.exists():
        return

    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _resolve_config_path(explicit=None):
    """Which .ini file to load.

    An explicit `path=` argument always wins. Otherwise, CONFIG_PATH in the
    environment lets a whole separate run -- e.g. a smaller Prolific pilot --
    use its own settings (participant count, database, stimuli file) without
    touching config.ini:

        CONFIG_PATH=config.pilot.ini python run.py
    """
    if explicit is not None:
        return Path(explicit)

    override = os.environ.get("CONFIG_PATH")
    if override:
        override_path = Path(override)
        return override_path if override_path.is_absolute() else PROJECT_ROOT / override_path

    return CONFIG_PATH


class Config:
    def __init__(self, path=None):
        _load_dotenv()

        self.path = _resolve_config_path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"Could not find {self.path}. Copy config.ini from the repository root."
            )

        self._parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
        self._parser.read(self.path, encoding="utf-8")

        for (section, option), env_var in ENV_OVERRIDES.items():
            value = os.environ.get(env_var)
            if value:
                if not self._parser.has_section(section):
                    self._parser.add_section(section)
                self._parser.set(section, option, value)

    # -- typed getters ------------------------------------------------------

    def get(self, section, option, default=None):
        value = self._parser.get(section, option, fallback=None)
        if value is None or value.strip() == "":
            return default
        return value.strip()

    def get_int(self, section, option, default=None):
        value = self.get(section, option)
        return default if value is None else int(value)

    def get_float(self, section, option, default=None):
        value = self.get(section, option)
        return default if value is None else float(value)

    def get_bool(self, section, option, default=False):
        value = self.get(section, option)
        return default if value is None else value.lower() in TRUTHY

    def get_list(self, section, option, default=None):
        value = self.get(section, option)
        if value is None:
            return list(default or [])
        return [item.strip() for item in value.split(",") if item.strip()]

    # -- derived settings ---------------------------------------------------

    @property
    def database_url(self):
        url = self.get("Server Parameters", "database_url", "sqlite:///participants.db")
        # Heroku-style URLs still use the deprecated `postgres://` scheme.
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            relative = url[len("sqlite:///") :]
            url = f"sqlite:///{PROJECT_ROOT / relative}"
        return url

    @property
    def secret_key(self):
        key = self.get("Server Parameters", "secret_key")
        if key:
            return key
        # A generated key is fine for a single-process dev run; it would log
        # participants out across restarts, so live deploys must set SECRET_KEY.
        return secrets.token_hex(32)

    @property
    def payment(self):
        return {
            "flat_fee_dollars": self.get_float("Payment", "flat_fee_dollars", 3.00),
            "expected_bonus_dollars": self.get_float("Payment", "expected_bonus_dollars", 4.00),
            "expected_score_for_payment": self.get_float(
                "Payment", "expected_score_for_payment", 2000
            ),
            "max_bonus_dollars": self.get_float("Payment", "max_bonus_dollars", 8.00),
        }

    @property
    def task_settings(self):
        """Everything the browser needs, injected into the experiment page.

        Keeping these server-side means the payment shown to participants and
        the bonus actually paid are computed from the same numbers.
        """
        payment = self.payment
        return {
            "forecast_start_index": self.get_int("Experiment", "forecast_start_index", 20),
            "max_trials": self.get_int("Experiment", "max_trials", 80),
            "distractor_length_ms": self.get_int("Experiment", "distractor_length_ms", 4000),
            "score_sd": self.get_float("Experiment", "score_sd", 20),
            "min_ar_value": self.get_int("Experiment", "min_ar_value", 1),
            "max_ar_value": self.get_int("Experiment", "max_ar_value", 1000),
            "debug_slot": self.get_int("Experiment", "debug_slot", None),
            "flat_fee_dollars": payment["flat_fee_dollars"],
            "expected_bonus_dollars": payment["expected_bonus_dollars"],
            "expected_score_for_payment": payment["expected_score_for_payment"],
            "max_bonus_dollars": payment["max_bonus_dollars"],
        }

    @property
    def num_counters(self):
        return self.get_int("Task Parameters", "num_counters", 300)

    @property
    def assignments_filename(self):
        """Path (under static/) to the pre-generated per-participant stimuli.

        Defaults to the main study's file. A pilot config can point this at a
        smaller, separately-generated file (see scripts/generate_assignments.py
        --output) instead of overwriting or subsetting the main one.
        """
        return self.get("Task Parameters", "assignments_filename", "data/assignments.json")

    @property
    def num_conds(self):
        return self.get_int("Task Parameters", "num_conds", 1)

    @property
    def code_version(self):
        return self.get("Task Parameters", "experiment_code_version", "0.0.1")

    @property
    def contact_email(self):
        return self.get("Task Parameters", "contact_email_on_error", "")

    @property
    def allow_repeats(self):
        return self.get_bool("Task Parameters", "allow_repeats", False)

    @property
    def allow_debug_mode(self):
        return self.get_bool("Task Parameters", "allow_debug_mode", False)

    @property
    def cutoff_minutes(self):
        return self.get_int("Task Parameters", "cutoff_time", 90)

    @property
    def browser_exclude_rule(self):
        return self.get_list("Task Parameters", "browser_exclude_rule", [])

    @property
    def completion_code(self):
        return self.get("Prolific", "completion_code", "")

    @property
    def screenout_code(self):
        return self.get("Prolific", "screenout_code", "")

    @property
    def completion_url_base(self):
        return self.get(
            "Prolific", "completion_url_base", "https://app.prolific.com/submissions/complete"
        )

    def completion_url(self, code):
        if not code:
            return None
        return f"{self.completion_url_base}?cc={code}"


_config = None


def get_config():
    global _config
    if _config is None:
        _config = Config()
    return _config
