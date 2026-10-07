"""Server-side scoring and bonus computation.

The browser scores forecasts as they happen so it can show feedback, but the
bonus that gets paid is recomputed here from the recorded trials. A participant
editing their score in the console should not be able to change what they earn.

Keep `score_forecast` in step with `scoreForecast` in static/js/utils.js.
"""

import json


def score_forecast(forecast, actual, score_sd):
    """Afrouzi scoring rule: full credit at zero error, zero at `score_sd` off."""
    if forecast is None or actual is None:
        return 0

    try:
        error = abs(float(forecast) - float(actual))
    except (TypeError, ValueError):
        return 0

    if score_sd <= 0:
        return 0

    return round(100 * max(0.0, 1.0 - (error / score_sd)))


def compute_bonus(score, payment):
    """Linear bonus schedule, capped at `max_bonus_dollars`."""
    expected_score = payment["expected_score_for_payment"]
    if not expected_score:
        return 0.0

    raw = payment["expected_bonus_dollars"] * (score or 0) / expected_score
    bonus = min(max(raw, 0.0), payment["max_bonus_dollars"])
    return round(bonus, 2)


def score_from_trials(trials, score_sd):
    """Total score across the forecast-feedback trials of a participant.

    `trials` is an iterable of `TrialData` rows. Only the first feedback trial
    per round counts, matching the browser's behaviour of scoring each round
    once even though the feedback screen loops until the value is typed
    correctly.
    """
    scored_rounds = {}

    for trial in trials:
        try:
            data = json.loads(trial.trialdata)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        if data.get("phase") != "forecast_feedback_recitation":
            continue

        round_index = data.get("round_index")
        if round_index is None or round_index in scored_rounds:
            continue

        scored_rounds[round_index] = score_forecast(
            data.get("forecast_value"), data.get("true_value"), score_sd
        )

    return sum(scored_rounds.values()), len(scored_rounds)
