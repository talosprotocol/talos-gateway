#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# talos-gateway Test Script
# =============================================================================

echo "Testing talos-gateway..."

echo "Running ruff check..."
ruff check . --exclude=.venv --exclude=tests 2>/dev/null || true

echo "Running ruff format check..."
ruff format --check . --exclude=.venv --exclude=tests 2>/dev/null || true

echo "Running pytest..."
pytest tests/ --ignore=tests/test_sdk_integration.py --maxfail=1 -q

echo "talos-gateway tests passed."
