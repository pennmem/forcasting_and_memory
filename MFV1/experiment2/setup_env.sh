#!/usr/bin/env bash
set -euo pipefail

# Creates the project's virtual environments.
#
# psiTurk pinned the experiment to Python 3.9, which is why this repository used
# to need two separate environments. It no longer does: the server and the
# analysis code both run on current Python. `.venv` is created by default and is
# enough for everything.
#
#   ./setup_env.sh              # .venv only (server + analysis)
#   ./setup_env.sh --split      # also create a separate .venv-analysis

PYTHON_VERSION="3.12"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

SPLIT_ENVS=false
for arg in "$@"; do
    case "$arg" in
        --split) SPLIT_ENVS=true ;;
        -h|--help) sed -n '3,12p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

echo "Project root: $PROJECT_ROOT"

find_python() {
    local expected_version="$1"

    if command -v pyenv >/dev/null 2>&1; then
        local pyenv_root
        pyenv_root="$(pyenv root)"

        for version in $(pyenv versions --bare); do
            if [[ "$version" == "$expected_version"* ]]; then
                local candidate="$pyenv_root/versions/$version/bin/python"
                if [[ -x "$candidate" ]]; then
                    echo "$candidate"
                    return 0
                fi
            fi
        done
    fi

    for candidate in "python$expected_version" python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            local actual_version
            actual_version="$("$candidate" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

            if [[ "$actual_version" == "$expected_version"* ]]; then
                command -v "$candidate"
                return 0
            fi
        fi
    done

    return 1
}

venv_python_version() {
    local venv_dir="$1"

    if [[ ! -x "$venv_dir/bin/python" ]]; then
        return 1
    fi

    "$venv_dir/bin/python" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null
}

create_or_refresh_venv() {
    local venv_dir="$1"
    local python_path="$2"
    shift 2

    # A project set up before the move off psiTurk has a Python 3.9 .venv here.
    # Reusing it would install the new requirements into an interpreter that
    # cannot parse the server code, so rebuild instead.
    if [[ -d "$venv_dir" ]]; then
        local existing
        existing="$(venv_python_version "$venv_dir" || true)"

        if [[ "$existing" != "$PYTHON_VERSION" ]]; then
            echo "$venv_dir has Python ${existing:-unknown}, but this project needs $PYTHON_VERSION."
            echo "  removing and rebuilding it"
            rm -rf "$venv_dir"
        fi
    fi

    if [[ ! -d "$venv_dir" ]]; then
        echo "Creating $venv_dir"
        "$python_path" -m venv "$venv_dir"
    else
        echo "$venv_dir already exists"
    fi

    "$venv_dir/bin/python" -m pip install --quiet --upgrade pip

    for requirements_file in "$@"; do
        if [[ -f "$requirements_file" ]]; then
            echo "  installing $requirements_file"
            "$venv_dir/bin/python" -m pip install --quiet -r "$requirements_file"
        else
            echo "  warning: $requirements_file not found, skipping"
        fi
    done
}

echo ""
echo "Finding Python $PYTHON_VERSION.x..."
PYTHON="$(find_python "$PYTHON_VERSION" || true)"

if [[ -z "${PYTHON:-}" ]]; then
    echo "Error: Python $PYTHON_VERSION.x not found."
    echo "Install it with:  pyenv install 3.12.7"
    exit 1
fi

echo "Using $PYTHON"

echo ""
if [[ "$SPLIT_ENVS" == true ]]; then
    echo "Creating server environment..."
    create_or_refresh_venv ".venv" "$PYTHON" "requirements.txt"

    echo ""
    echo "Creating analysis environment..."
    create_or_refresh_venv ".venv-analysis" "$PYTHON" "requirements-analysis.txt"
else
    echo "Creating combined environment..."
    create_or_refresh_venv ".venv" "$PYTHON" "requirements.txt" "requirements-analysis.txt" "requirements-dev.txt"
fi

echo ""
echo "Done."
echo ""
echo "  source .venv/bin/activate"
echo "  python run.py                 # start the experiment server"
echo "  open http://127.0.0.1:22362/exp"
echo ""
if [[ "$SPLIT_ENVS" == true ]]; then
    echo "For analysis:  source .venv-analysis/bin/activate"
    echo ""
fi
