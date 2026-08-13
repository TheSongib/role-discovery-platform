#!/usr/bin/env bash
set -e

echo "Starting JobTracker..."
echo "  API  -> http://localhost:8000"
echo "  App  -> http://localhost:5173"
echo ""

# Prefer the project's Windows virtual environment when it exists. Otherwise,
# use the Python command available in the current Git Bash session.
if [[ -x ".venv/Scripts/python.exe" ]]; then
    PYTHON=".venv/Scripts/python.exe"
elif command -v python >/dev/null 2>&1; then
    PYTHON="python"
elif command -v py >/dev/null 2>&1; then
    PYTHON="py"
else
    echo "Python was not found. Install Python 3.11+ and try again."
    exit 1
fi

api_pid=""
frontend_pid=""

cleanup() {
    trap - EXIT INT TERM
    [[ -n "$api_pid" ]] && kill "$api_pid" 2>/dev/null || true
    [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
    wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

"$PYTHON" -m uvicorn api:app --reload &
api_pid=$!

(
    cd frontend
    npm run dev
) &
frontend_pid=$!

wait
