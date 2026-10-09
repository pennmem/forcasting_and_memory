import argparse
import copy
import json
import math
import hashlib
import sys
from pathlib import Path


# -----------------------------
# Main design settings
# -----------------------------

NUM_PARTICIPANTS = 30

RHO_VALUES = [0.6]
START_TYPES = ["animacy", "size"]

N_AR_VALUES = 80
AR_MEAN = 500
AR_SD = 20
AR_MIN = 400
AR_MAX = 600

N_DISTRACTION_TASKS = 80
WORDS_PER_TASK = 20
TRAIN_LENGTHS = [3, 4, 5, 6]

# Bumped when the generation procedure changed. v3 conditioned on realized rho;
# this version matches rho, mean and SD exactly in each phase (see below).
SEED = "20261007-moment-matched-rho06"

# AR_SD is the SD of the series itself (its long-run stationary SD), so the
# white-noise innovations have SD AR_SD * sqrt(1 - rho^2).
# AR(1): x_t = mean + rho * (x_{t-1} - mean) + epsilon_t
#
# Set this to False to read AR_SD as the innovation SD instead.
INTERPRET_AR_SD_AS_STATIONARY_SD = True

# The first value is drawn from the process's stationary distribution but kept
# within START_WINDOW_SD_FRACTION * AR_SD of the mean (i.e. +/-10 for SD 20).
START_WINDOW_SD_FRACTION = 0.5


# -----------------------------
# Phase-wise moment matching
# -----------------------------
# The series has an observation phase (values 0 .. FORECAST_START_INDEX-1) and
# a forecasting phase (FORECAST_START_INDEX .. end). For the observation phase,
# the forecasting phase and the two combined, the realized mean, SD and AR(1)
# coefficient are made to equal the true values:
#
#   mean : exactly AR_MEAN (the integer sums are fixed)
#   SD   : exactly AR_SD, using the population SD (divide by n). That is the
#          only convention under which all three windows can match at once:
#          with equal means, the sums of squares of the two phases add up to
#          that of the whole series only if SS = n * SD^2 in each.
#   rho  : within RHO_MATCH_TOLERANCE of nominal. The values are integers (what
#          participants see), so exact rho is not generally attainable.
#
# Rho windows (OLS slope of x_t on x_{t-1}, with intercept):
#   observation : pairs inside the observation phase
#   forecast    : x[start-1 .. n-2] -> x[start .. n-1], the pairing the analysis
#                 regression uses (includes the boundary pair)
#   combined    : all consecutive pairs
#
# Method: draw an AR(1) series, rejection-sample it to a loose neighbourhood of
# the targets, then run a greedy integer search that moves mass between two
# values of the same phase (which preserves that phase's mean) until the SD and
# all three rhos hit their targets.
FORECAST_START_INDEX = 20

RHO_MATCH_TOLERANCE = 0.0005

# Loose rejection-sampling neighbourhood for the starting draw.
LOOSE_RHO_TOLERANCE = 0.08
LOOSE_SD_TOLERANCE = 3.0
LOOSE_MEAN_TOLERANCE = 6.0

MAX_AR_ATTEMPTS = 200000
POLISH_STEPS = 60000
MAX_POLISH_RESTARTS = 40


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
    matching below targets exactly the quantity that gets reported.
    """
    n = len(x_values)
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n

    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values))
    sxx = sum((x - x_mean) ** 2 for x in x_values)

    if sxx == 0:
        raise ValueError("Cannot estimate rho: x has no variance.")

    return sxy / sxx


def phase_bounds():
    return {
        "observation": (0, FORECAST_START_INDEX),
        "forecast": (FORECAST_START_INDEX, N_AR_VALUES),
        "combined": (0, N_AR_VALUES),
    }


def phase_rho(values, phase):
    start, end = phase_bounds()[phase]
    if phase == "forecast":
        # Forecasting round i: the participant has just seen values[i - 1].
        x_values = values[start - 1:end - 1]
        y_values = values[start:end]
    else:
        x_values = values[start:end - 1]
        y_values = values[start + 1:end]
    return ols_slope(y_values, x_values)


def phase_mean_sd(values, phase):
    start, end = phase_bounds()[phase]
    window = values[start:end]
    n = len(window)
    mean = sum(window) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in window) / n)  # population SD
    return mean, sd


def phase_stats(values):
    stats = {}
    for phase in phase_bounds():
        mean, sd = phase_mean_sd(values, phase)
        stats[phase] = {
            "mean": mean,
            "sd": sd,
            "rho": phase_rho(values, phase),
        }
    return stats


def innovation_sd_for_rho(rho):
    if INTERPRET_AR_SD_AS_STATIONARY_SD:
        return AR_SD * math.sqrt(1 - rho ** 2)
    else:
        return AR_SD


def draw_start_value():
    """A stationary draw, kept within START_WINDOW_SD_FRACTION * AR_SD of the mean."""
    limit = START_WINDOW_SD_FRACTION * AR_SD
    while True:
        value = round_positive_to_nearest_integer(rng.normal(AR_MEAN, AR_SD))
        if abs(value - AR_MEAN) <= limit:
            return value


def loose_draw(rho):
    """Rejection-sample an AR(1) series in a loose neighbourhood of the targets."""
    innovation_sd = innovation_sd_for_rho(rho)

    for attempt in range(1, MAX_AR_ATTEMPTS + 1):
        values = [draw_start_value()]
        for _ in range(1, N_AR_VALUES):
            epsilon = rng.normal(0, innovation_sd)
            values.append(AR_MEAN + rho * (values[-1] - AR_MEAN) + epsilon)
        rounded = [round_positive_to_nearest_integer(v) for v in values]
        rounded[0] = values[0]

        if not all(AR_MIN <= v <= AR_MAX for v in rounded):
            continue

        stats = phase_stats(rounded)
        if all(
            abs(st["rho"] - rho) <= LOOSE_RHO_TOLERANCE
            and abs(st["sd"] - AR_SD) <= LOOSE_SD_TOLERANCE
            and abs(st["mean"] - AR_MEAN) <= LOOSE_MEAN_TOLERANCE
            for st in stats.values()
        ):
            return rounded, attempt

    raise RuntimeError(
        f"No loose draw found for rho={rho} after {MAX_AR_ATTEMPTS} attempts."
    )


def rescale_phases(values):
    """Affinely rescale each phase to mean AR_MEAN and SD AR_SD (before rounding).

    Puts the integer search close to the targets, so it only has to repair
    rounding and rho rather than a large SD miss.
    """
    scaled = list(values)
    for phase in ("observation", "forecast"):
        start, end = phase_bounds()[phase]
        mean, sd = phase_mean_sd(values, phase)
        for i in range(start, end):
            scaled[i] = AR_MEAN + (values[i] - mean) * AR_SD / sd
    rounded = [round_positive_to_nearest_integer(v) for v in scaled]
    start_limit = START_WINDOW_SD_FRACTION * AR_SD
    rounded[0] = min(max(rounded[0], AR_MEAN - start_limit), AR_MEAN + start_limit)
    return rounded


def fix_phase_sums(values):
    """Nudge single values by +/-1 until each phase's mean is exactly AR_MEAN."""
    for phase in ("observation", "forecast"):
        start, end = phase_bounds()[phase]
        target = AR_MEAN * (end - start)
        while sum(values[start:end]) != target:
            i = start + rng.randbelow(end - start)
            if i == 0:
                continue  # the start value is pinned by the start window
            values[i] += 1 if sum(values[start:end]) < target else -1


def sum_squares(values, phase):
    start, end = phase_bounds()[phase]
    return sum((v - AR_MEAN) ** 2 for v in values[start:end])


def match_loss(values, rho):
    loss = 0.0
    for phase in ("observation", "forecast"):
        start, end = phase_bounds()[phase]
        target_ss = AR_SD ** 2 * (end - start)
        loss += ((sum_squares(values, phase) - target_ss) / 2) ** 2
    for phase in phase_bounds():
        loss += ((phase_rho(values, phase) - rho) / RHO_MATCH_TOLERANCE) ** 2
    return loss


def is_matched(values, rho):
    for phase in ("observation", "forecast"):
        start, end = phase_bounds()[phase]
        if sum(values[start:end]) != AR_MEAN * (end - start):
            return False
        if abs(sum_squares(values, phase) - AR_SD ** 2 * (end - start)) > 1e-6:
            return False
    return all(abs(phase_rho(values, p) - rho) <= RHO_MATCH_TOLERANCE for p in phase_bounds())


def polish(values, rho):
    """Greedy integer search; every move keeps each phase's sum (hence mean) fixed."""
    values = list(values)
    fix_phase_sums(values)
    loss = match_loss(values, rho)
    start_limit = START_WINDOW_SD_FRACTION * AR_SD

    for _ in range(POLISH_STEPS):
        if is_matched(values, rho):
            return values
        phase = "observation" if rng.random() < 0.25 else "forecast"
        lo, hi = phase_bounds()[phase]
        i = lo + rng.randbelow(hi - lo)
        j = lo + rng.randbelow(hi - lo)
        if i == j:
            continue
        d = 1 + rng.randbelow(3)
        vi, vj = values[i] + d, values[j] - d
        if not (AR_MIN <= vi <= AR_MAX and AR_MIN <= vj <= AR_MAX):
            continue
        if (i == 0 and abs(vi - AR_MEAN) > start_limit) or (
            j == 0 and abs(vj - AR_MEAN) > start_limit
        ):
            continue
        old_i, old_j = values[i], values[j]
        values[i], values[j] = vi, vj
        new_loss = match_loss(values, rho)
        if new_loss <= loss:
            loss = new_loss
        else:
            values[i], values[j] = old_i, old_j

    return values if is_matched(values, rho) else None


def generate_ar1_values(rho):
    """Draw an AR(1) series whose mean, SD and rho match the targets per phase.

    Returns (values, stats, attempts, restarts).
    """
    total_attempts = 0
    for restart in range(1, MAX_POLISH_RESTARTS + 1):
        draw, attempts = loose_draw(rho)
        total_attempts += attempts
        values = polish(rescale_phases(draw), rho)
        if values is not None:
            return values, phase_stats(values), total_attempts, restart

    raise RuntimeError(
        f"Could not match rho={rho} after {MAX_POLISH_RESTARTS} restarts. "
        f"Loosen RHO_MATCH_TOLERANCE or raise POLISH_STEPS."
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

        ar_values, stats, attempts, restarts = generate_ar1_values(rho)
        total_attempts += attempts

        distraction_tasks, train_lengths = generate_distraction_tasks(wordpool, start_type)

        if (slot + 1) % 25 == 0:
            print(f"  {slot + 1}/{len(design)} assignments generated")

        assignments.append({
            "slot": slot + 1,  # real slots are numbered 1..N; slot 0 is the debug slot
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
                "first_value": ar_values[0],

                # Realized mean / SD (population) / rho of this series in each
                # phase. These equal the true values (rho to within
                # RHO_MATCH_TOLERANCE); the analysis can benchmark against them.
                "realized": {
                    phase: {k: round(v, 6) for k, v in st.items()}
                    for phase, st in stats.items()
                },
                "generation_attempts": attempts,
                "polish_restarts": restarts,

                "values": ar_values
            },
            "distraction": {
                "train_lengths": train_lengths,
                "tasks": distraction_tasks
            }
        })

    # Slot 0 is the reserved debug slot (never counted by the server), so the
    # file is indexed by slot number: assignments[0] is debug and
    # assignments[1..N] are the real slots. The debug entry reuses slot 1's
    # stimuli.
    debug_entry = copy.deepcopy(assignments[0])
    debug_entry["slot"] = 0
    debug_entry["debug"] = True

    output = {
        "metadata": {
            "slot_numbering": (
                "assignments[0] is the debug slot (slot 0, reuses slot 1's stimuli); "
                "real slots are 1..num_participants"
            ),
            "num_participants": NUM_PARTICIPANTS,
            "rho_values": RHO_VALUES,
            "participants_per_rho": NUM_PARTICIPANTS // len(RHO_VALUES),
            "start_types": START_TYPES,
            "participants_per_rho_start_type_cell": NUM_PARTICIPANTS // (len(RHO_VALUES) * len(START_TYPES)),
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

            "moment_matching": {
                "phases": {
                    phase: {"start_index": lo, "end_index_exclusive": hi}
                    for phase, (lo, hi) in phase_bounds().items()
                },
                "mean": "exactly %s in the observation and forecasting phases (hence combined)" % AR_MEAN,
                "sd": "exactly %s (population SD, divide by n) in each phase" % AR_SD,
                "rho": "OLS slope of x_t on x_{t-1} with intercept, within %s of nominal in each phase" % RHO_MATCH_TOLERANCE,
                "rho_match_tolerance": RHO_MATCH_TOLERANCE,
                "start_value_window": [
                    AR_MEAN - START_WINDOW_SD_FRACTION * AR_SD,
                    AR_MEAN + START_WINDOW_SD_FRACTION * AR_SD,
                ],
                "mean_draws_per_assignment": round(total_attempts / len(assignments), 1),
            },

            "seed": SEED,
            "python_version_used_to_generate": sys.version,
            "do_not_regenerate_after_data_collection_begins": True
        },
        "assignments": [debug_entry] + assignments
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
    """Confirm the matching did what it was supposed to (read this on every regeneration)."""
    print("\nRealized statistics by phase (targets: mean %s, SD %s, rho nominal):" % (AR_MEAN, AR_SD))
    header = f"  {'rho':>5} {'phase':>12} {'stat':>5} {'min':>10} {'max':>10} {'max |err|':>10}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    by_rho = {}
    for a in assignments:
        by_rho.setdefault(a["rho"], []).append(a["ar1"])

    for rho in sorted(by_rho):
        targets = {"mean": AR_MEAN, "sd": AR_SD, "rho": rho}
        for phase in phase_bounds():
            for stat in ("mean", "sd", "rho"):
                vals = [ar["realized"][phase][stat] for ar in by_rho[rho]]
                err = max(abs(v - targets[stat]) for v in vals)
                print(f"  {rho:>5} {phase:>12} {stat:>5} {min(vals):>10.4f} {max(vals):>10.4f} {err:>10.6f}")

    firsts = [a["ar1"]["first_value"] for a in assignments]
    print(f"\n  Start values: min {min(firsts)}, max {max(firsts)} "
          f"(allowed {AR_MEAN - START_WINDOW_SD_FRACTION * AR_SD:g}..{AR_MEAN + START_WINDOW_SD_FRACTION * AR_SD:g})")


if __name__ == "__main__":
    main()