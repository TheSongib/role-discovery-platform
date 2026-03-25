#!/bin/bash
set -e

echo "Starting JobTracker..."
echo "  API  → http://localhost:8000"
echo "  App  → http://localhost:5173"
echo ""

# Kill both child processes on Ctrl+C
trap 'kill 0' EXIT

uvicorn api:app --reload &
cd frontend && npm run dev &

wait
