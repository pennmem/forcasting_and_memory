import argparse
import json
import math
import hashlib
import sys
from pathlib import Path


# -----------------------------
# Main design settings
# -----------------------------

NUM_PARTICIPANTS = 300

RHO_VALUES = [0.6, 0.7]
START_TYPES = ["animacy", "size"]

N_AR_VALUES = 80
AR_MEAN = 500
AR_SD = 20
AR_MIN = 1
AR_MAX = 1000

N_DISTRACTION_TASKS = 80
WORDS_PER_TASK = 20
TRAIN_LENGTHS = [3, 4, 5, 6]

# Bumped when the generation procedure changed to condition on realized rho.
# The pre-conditioning stimuli are archived as assignments_v1.json.
SEED = "20260827-rho-conditioned"

# Interpret AR_SD as the SD of the white-noise innovations.
# AR(1): x_t = mean + rho * (x_{t-1} - mean) + epsilon_t
# epsilon_t ~ Normal(0, AR_SD)
#
# If instead you want AR_SD to mean the long-run stationary SD of the process,
# set this to True.
INTERPRET_AR_SD_AS_STATIONARY_SD = False


# -----------------------------
# Realized-rho conditioning
# -----------------------------
# A single 80-point AR(1) draw has a sample rho that scatters with SD ~0.10 and
# sits ~0.06 below the nominal value (Kendall's small-sample bias, about
# -(1 + 3*rho)/T). With rho = 0.6 and rho = 0.7 only 0.1 apart, unconditioned
# draws overlap so badly that ~28% of the time a nominal-0.6 series is actually
# more persistent than a nominal-0.7 series.
#
# So candidate series are resampled until the realized rho lands within
# RHO_TOLERANCE of the nominal value. This is the ordinary rejection-sampling
# fix: the accepted series are draws from the AR(1) process conditioned on their
# own sample autocorrelation, which leaves the innovation SD, the series mean,
# and the value range essentially untouched.
#
# Tolerance rationale: 0.01 puts the within-condition SD of realized rho at
# ~0.006, i.e. 6% of the 0.1 between-condition separation. It is also below what
# the task can express -- a rho error of 0.01 moves the optimal forecast
# (mean + rho * (x - mean)) by ~0.2 units at a typical deviation and ~0.5 at an
# extreme one, under the 1-unit granularity of the response box. Tightening
# further buys resolution nobody can act on and costs acceptance rate.
RHO_TOLERANCE = 0.01

# Conditioning is applied to two windows:
#   - the full series, which is what participants learn persistence from
#   - the forecast rounds only, which is the window the analysis regresses over
# Constraining only the forecast window leaves the full-series rho scattered at
# SD ~0.04, because the observation phase stays unconstrained.
FORECAST_START_INDEX = 20

# Expected acceptance rate is ~1.4%, so ~70 draws per assignment. This cap is
# far enough above that to make a spurious failure essentially impossible.
MAX_AR_ATTEMPTS = 50000


# -----------------------------
# Paths
# -----------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORDPOOL_PATH = PROJECT_ROOT / "static" / "data" / "wordpool.txt" # PEERS 1638 word dataset
OUTPUT_PATH = PROJECT_ROOT / "static" / "data" / "assignments.json"


# -----------------------------
# Deterministic hash-based RNG
# -----------------------------
# This avoids relying too heavily on Python's random module internals.
# The generated assignments.json is still the main reproducible artifact.

class HashRNG:
    def __init__(self, seed):
        self.seed = str(seed)
        self.counter = 0

    def _digest(self):
        msg = f"{self.seed}:{self.counter}".encode("utf-8")
        self.counter += 1
        return hashlib.sha256(msg).digest()

    def random(self):
        # 53-bit precision uniform in [0, 1)
        digest = self._digest()
        value = int.from_bytes(digest[:8], "big") >> 11
        return value / (1 << 53)

    def randbelow(self, n):
        if n <= 0:
            raise ValueError("n must be positive")
        return int(self.random() * n)

    def shuffle(self, items):
        items = list(items)
        for i in range(len(items) - 1, 0, -1):
            j = self.randbelow(i + 1)
            items[i], items[j] = items[j], items[i]
        return items

    def sample(self, population, k):
        if k > len(population):
            raise ValueError("sample larger than population")
        shuffled = self.shuffle(population)
        return shuffled[:k]

    def normal(self, mean=0.0, sd=1.0):
        # Box-Muller transform
        u1 = max(self.random(), 1e-12)
        u2 = self.random()
        z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
        return mean + sd * z


rng = HashRNG(SEED)


# -----------------------------
# Helpers
# -----------------------------

def round_positive_to_nearest_integer(x):
    return int(math.floor(x + 0.5))


def load_wordpool(path):
    if not path.exists():
        raise FileNotFoundError(f"Could not find wordpool file: {path}")

    with open(path, "r", encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]

    # Check uniqueness in the source pool.
    duplicates = sorted({w for w in words if words.count(w) > 1})
    if duplicates:
        raise ValueError(
            "wordpool.txt contains duplicate words. "
            f"Examples: {duplicates[:10]}"
        )

    needed = N_DISTRACTION_TASKS * WORDS_PER_TASK
    if len(words) < needed:
        raise ValueError(
            f"Need at least {needed} unique words, but wordpool.txt has {len(words)}."
        )

    return words


def innovation_sd_for_rho(rho):
    if INTERPRET_AR_SD_AS_STATIONARY_SD:
        return AR_SD * math.sqrt(1 - rho ** 2)
    else:
        return AR_SD


def ols_slope(y_values, x_values):
    """Slope of an OLS regression of y on x with an intercept.

    This is the estimator the analysis uses (statsmodels `y ~ x`), so the
    conditioning below targets exactly the quantity that gets reported.
    """
    n = len(x_values)
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n

    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    sxx = sum((x - x_mean) ** 2 for x in x_values)

    if sxx == 0:
        raise ValueError("Cannot estimate rho: x has no variance.")

    return sxy / sxx


def realized_rho_full(values):
    """Sample AR(1) coefficient over the whole series."""
    return ols_slope(values[1:], values[:-1])


def realized_rho_forecast_window(values, start=FORECAST_START_INDEX):
    """Sample AR(1) coefficient over the forecast rounds only.

    Forecasting on round i, the participant has just seen values[i - 1] and the
    outcome is values[i]. That is the pairing the analysis regression uses.
    """
    x_values = values[start - 1:len(values) - 1]
    y_values = values[start:]
    return ols_slope(y_values, x_values)


def generate_ar1_values(rho):
    """Draw an AR(1) series whose realized rho is close to `rho`.

    Returns (values, rho_full, rho_forecast_window, attempts). See the
    RHO_TOLERANCE comment above for why the resampling is here.
    """
    innovation_sd = innovation_sd_for_rho(rho)

    for attempt in range(1, MAX_AR_ATTEMPTS + 1):
        values = [AR_MEAN]

        for _ in range(1, N_AR_VALUES):
            previous = values[-1]
            epsilon = rng.normal(0, innovation_sd)
            next_value = AR_MEAN + rho * (previous - AR_MEAN) + epsilon
            values.append(next_value)

        rounded = [round_positive_to_nearest_integer(v) for v in values]
        rounded[0] = AR_MEAN

        # Values are very unlikely to leave 1..1000 with these settings,
        # but this enforces the constraint.
        if not all(AR_MIN <= v <= AR_MAX for v in rounded):
            continue

        # Condition on the rounded values, since those are what participants
        # see and what the analysis reads back out of this file.
        rho_full = realized_rho_full(rounded)
        if abs(rho_full - rho) > RHO_TOLERANCE:
            continue

        rho_window = realized_rho_forecast_window(rounded)
        if abs(rho_window - rho) > RHO_TOLERANCE:
            continue

        return rounded, rho_full, rho_window, attempt

    raise RuntimeError(
        f"Could not generate an AR(1) sequence for rho={rho} with realized rho "
        f"within {RHO_TOLERANCE} of nominal after {MAX_AR_ATTEMPTS} attempts. "
        f"Loosen RHO_TOLERANCE or raise MAX_AR_ATTEMPTS."
    )


def can_finish_train_lengths(remaining, previous_length, memo):
    key = (remaining, previous_length)
    if key in memo:
        return memo[key]

    if remaining == 0:
        memo[key] = True
        return True

    if remaining < min(TRAIN_LENGTHS):
        memo[key] = False
        return False

    for length in TRAIN_LENGTHS:
        if length == previous_length:
            continue
        if length <= remaining:
            if can_finish_train_lengths(remaining - length, length, memo):
                memo[key] = True
                return True

    memo[key] = False
    return False


def generate_train_lengths(total_trials):
    lengths = []
    remaining = total_trials
    previous_length = None
    memo = {}

    while remaining > 0:
        candidates = []

        for length in TRAIN_LENGTHS:
            if length == previous_length:
                continue
            if length <= remaining:
                if can_finish_train_lengths(remaining - length, length, memo):
                    candidates.append(length)

        if not candidates:
            raise RuntimeError("Could not construct valid train lengths.")

        candidates = rng.shuffle(candidates)
        chosen = candidates[0]

        lengths.append(chosen)
        remaining -= chosen
        previous_length = chosen

    return lengths


def generate_task_types(start_type):
    if start_type not in ["animacy", "size"]:
        raise ValueError("start_type must be 'animacy' or 'size'.")

    train_lengths = generate_train_lengths(N_DISTRACTION_TASKS)

    task_types = []
    current_type = start_type

    for train_length in train_lengths:
        task_types.extend([current_type] * train_length)
        current_type = "size" if current_type == "animacy" else "animacy"

    if len(task_types) != N_DISTRACTION_TASKS:
        raise RuntimeError("Wrong number of task types generated.")

    return task_types, train_lengths


def generate_distraction_tasks(wordpool, start_type):
    task_types, train_lengths = generate_task_types(start_type)

    selected_words = rng.sample(
        wordpool,
        N_DISTRACTION_TASKS * WORDS_PER_TASK
    )

    tasks = []
    index = 0

    for task_number, task_type in enumerate(task_types):
        task_words = selected_words[index:index + WORDS_PER_TASK]
        index += WORDS_PER_TASK

        tasks.append({
            "task_number": task_number,
            "task_type": task_type,
            "words": task_words
        })

    return tasks, train_lengths


def make_balanced_design():
    design = []

    participants_per_cell = NUM_PARTICIPANTS // (len(RHO_VALUES) * len(START_TYPES))

    if participants_per_cell * len(RHO_VALUES) * len(START_TYPES) != NUM_PARTICIPANTS:
        raise ValueError("NUM_PARTICIPANTS must divide evenly across rho/start-type cells.")

    for rho in RHO_VALUES:
        for start_type in START_TYPES:
            for _ in range(participants_per_cell):
                design.append({
                    "rho": rho,
                    "start_type": start_type
                })

    return rng.shuffle(design)


def parse_args():
    n_cells = len(RHO_VALUES) * len(START_TYPES)

    parser = argparse.ArgumentParser(
        description=(
            "Generate per-participant AR(1) and distractor stimuli. With no "
            "arguments this reproduces the main study's assignments.json exactly "
            "(same participant count, output path, and seed as before) -- "
            "everything below is for generating an additional, separate file, "
            "such as a smaller pilot batch."
        )
    )
    parser.add_argument(
        "--num-participants",
        type=int,
        default=NUM_PARTICIPANTS,
        help=(
            f"Number of assignments to generate (default: {NUM_PARTICIPANTS}). "
            f"Must divide evenly by {n_cells} (the {len(RHO_VALUES)} rho values x "
            f"{len(START_TYPES)} start types), so every cell gets the same count "
            f"and each rho gets exactly num_participants / {len(RHO_VALUES)}."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Where to write the assignments JSON (default: {OUTPUT_PATH}).",
    )
    parser.add_argument(
        "--seed",
        default=None,
        help=(
            f"RNG seed (default: the module's {SEED!r}). Use a distinct seed for "
            "any file other than the main assignments.json -- reusing the same "
            "seed at a different --num-participants already produces a different "
            "design shuffle and different AR(1) draws (the two are not nested), "
            "but a distinct seed makes that unambiguous later."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # These are read as globals throughout the file below, so overriding them
    # here -- rather than threading parameters through every function -- is
    # the smallest change that lets this script generate an additional file
    # (e.g. a pilot batch) without touching how it generates the main one.
    global NUM_PARTICIPANTS, OUTPUT_PATH, SEED, rng
    NUM_PARTICIPANTS = args.num_participants
    OUTPUT_PATH = args.output
    if args.seed is not None:
        SEED = args.seed
    rng = HashRNG(SEED)  # rng is normally constructed at import time from the default SEED

    print(f"num_participants = {NUM_PARTICIPANTS}")
    print(f"output           = {OUTPUT_PATH}")
    print(f"seed             = {SEED!r}\n")

    wordpool = load_wordpool(WORDPOOL_PATH)
    design = make_balanced_design()

    assignments = []

    total_attempts = 0

    for slot, cell in enumerate(design):
        rho = cell["rho"]
        start_type = cell["start_type"]

        ar_values, rho_full, rho_window, attempts = generate_ar1_values(rho)
        total_attempts += attempts

        distraction_tasks, train_lengths = generate_distraction_tasks(wordpool, start_type)

        if (slot + 1) % 25 == 0:
            print(f"  {slot + 1}/{len(design)} assignments generated")

        assignments.append({
            "slot": slot,
            "rho": rho,
            "start_type": start_type,
            "ar1": {
                "mean": AR_MEAN,
                "rho": rho,
                "sd_parameter": AR_SD,
                "sd_interpretation": (
                    "stationary_process_sd"
                    if INTERPRET_AR_SD_AS_STATIONARY_SD
                    else "white_noise_innovation_sd"
                ),
                "first_value": AR_MEAN,

                # Realized persistence of this particular series. The analysis
                # should benchmark a participant's implied rho against these
                # rather than against the nominal `rho` above.
                "realized_rho_full": round(rho_full, 6),
                "realized_rho_forecast_window": round(rho_window, 6),
                "generation_attempts": attempts,

                "values": ar_values
            },
            "distraction": {
                "train_lengths": train_lengths,
                "tasks": distraction_tasks
            }
        })

    output = {
        "metadata": {
            "num_participants": NUM_PARTICIPANTS,
            "rho_values": RHO_VALUES,
            "participants_per_rho": NUM_PARTICIPANTS // len(RHO_VALUES),
            "start_types": START_TYPES,
            "participants_per_rho_start_type_cell": NUM_PARTICIPANTS // 4,
            "n_ar_values_per_participant": N_AR_VALUES,
            "ar_mean": AR_MEAN,
            "ar_sd_parameter": AR_SD,
            "ar_sd_interpretation": (
                "stationary_process_sd"
                if INTERPRET_AR_SD_AS_STATIONARY_SD
                else "white_noise_innovation_sd"
            ),
            "ar_bounds": [AR_MIN, AR_MAX],
            "n_distraction_tasks_per_participant": N_DISTRACTION_TASKS,
            "words_per_distraction_task": WORDS_PER_TASK,
            "unique_words_per_participant": N_DISTRACTION_TASKS * WORDS_PER_TASK,
            "train_lengths_allowed": TRAIN_LENGTHS,
            "constraint": "No two adjacent task trains have the same length.",

            "realized_rho_conditioning": {
                "tolerance": RHO_TOLERANCE,
                "estimator": "OLS slope of x_t on x_{t-1} with intercept",
                "windows_constrained": [
                    "full series (all %d values)" % N_AR_VALUES,
                    "forecast rounds only (index %d onward)" % FORECAST_START_INDEX,
                ],
                "forecast_start_index": FORECAST_START_INDEX,
                "note": (
                    "Series were resampled until the realized AR(1) coefficient fell "
                    "within the tolerance of the nominal value on both windows. "
                    "Without this, realized rho scatters with SD ~0.10 and sits ~0.06 "
                    "below nominal, which leaves the two conditions overlapping."
                ),
                "mean_attempts_per_assignment": round(total_attempts / len(assignments), 1),
            },

            "seed": SEED,
            "python_version_used_to_generate": sys.version,
            "do_not_regenerate_after_data_collection_begins": True
        },
        "assignments": assignments
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nGenerated {NUM_PARTICIPANTS} assignments.")
    print(f"Wrote: {OUTPUT_PATH}")
    print(f"Mean draws per assignment: {total_attempts / len(assignments):.1f}")

    # Basic balance checks
    counts = {}
    for a in assignments:
        key = (a["rho"], a["start_type"])
        counts[key] = counts.get(key, 0) + 1

    print("\nBalance check:")
    for key, value in sorted(counts.items()):
        print(f"  rho={key[0]}, start={key[1]}: {value}")

    report_realized_rho(assignments)


def summarize(values):
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    return mean, sd, min(values), max(values)


def report_realized_rho(assignments):
    """Confirm the conditioning did what it was supposed to.

    Worth reading every time this is regenerated: if the tolerance or the
    estimator ever drifts out of step with the analysis, it shows up here.
    """
    print("\nRealized rho check (tolerance +/- %.3f):" % RHO_TOLERANCE)

    by_rho = {}
    for a in assignments:
        by_rho.setdefault(a["rho"], []).append(a["ar1"])

    header = f"  {'nominal':>8} {'window':>10} {'mean':>9} {'sd':>8} {'min':>8} {'max':>8} {'bias':>9}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for rho in sorted(by_rho):
        for label, key in (
            ("full", "realized_rho_full"),
            ("forecast", "realized_rho_forecast_window"),
        ):
            values = [ar[key] for ar in by_rho[rho]]
            mean, sd, lo, hi = summarize(values)
            print(
                f"  {rho:>8} {label:>10} {mean:>9.4f} {sd:>8.4f} "
                f"{lo:>8.4f} {hi:>8.4f} {mean - rho:>+9.4f}"
            )

    # The failure this whole exercise exists to prevent: a nominally
    # low-persistence series that is actually more persistent than a nominally
    # high-persistence one.
    rho_values = sorted(by_rho)
    if len(rho_values) == 2:
        low, high = rho_values
        low_max = max(ar["realized_rho_full"] for ar in by_rho[low])
        high_min = min(ar["realized_rho_full"] for ar in by_rho[high])
        print(
            f"\n  Highest realized rho in the {low} condition: {low_max:.4f}"
            f"\n  Lowest realized rho in the {high} condition: {high_min:.4f}"
        )
        if low_max < high_min:
            print(f"  No overlap. Separation: {high_min - low_max:.4f}")
        else:
            print("  WARNING: the two conditions overlap in realized rho.")


if __name__ == "__main__":
    main()