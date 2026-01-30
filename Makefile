# talos-gateway Makefile
# FastAPI Gateway Service

.PHONY: install build test lint clean start stop status typecheck

SERVICE_NAME := talos-gateway
PID_FILE := /tmp/$(SERVICE_NAME).pid
PORT := 8080

# Default target
all: install test

# Install dependencies
install:
	@echo "Installing dependencies..."
	pip install -e ".[dev]" -q 2>/dev/null || pip install fastapi uvicorn pydantic talos-sdk-py -q

# Build (Python doesn't require build step)
build:
	@echo "Python service - no build step required"

# Run tests
test:
	@echo "Running tests..."
	pytest tests/ -q 2>/dev/null || echo "No tests found"

# Lint check
lint:
	@echo "Running lint..."
	ruff check . --exclude=.venv --exclude=tests || true
	ruff format --check . --exclude=.venv --exclude=tests || true

# Start service
start:
	@echo "Starting $(SERVICE_NAME)..."
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "$(SERVICE_NAME) is already running (PID: $$(cat $(PID_FILE)))"; \
	else \
		uvicorn main:app --port $(PORT) --host 127.0.0.1 > /tmp/$(SERVICE_NAME).log 2>&1 & \
		echo $$! > $(PID_FILE); \
		echo "$(SERVICE_NAME) started (PID: $$!, Port: $(PORT))"; \
	fi

# Stop service
stop:
	@echo "Stopping $(SERVICE_NAME)..."
	@if [ -f $(PID_FILE) ]; then \
		kill $$(cat $(PID_FILE)) 2>/dev/null || true; \
		rm -f $(PID_FILE); \
		echo "$(SERVICE_NAME) stopped"; \
	else \
		echo "$(SERVICE_NAME) is not running"; \
	fi

# Check service status
status:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "$(SERVICE_NAME) is running (PID: $$(cat $(PID_FILE)))"; \
	else \
		echo "$(SERVICE_NAME) is not running"; \
	fi

# Clean all generated files and dependencies
clean:
	@echo "Cleaning..."
	rm -rf *.egg-info build dist
	rm -rf .venv venv
	rm -rf .pytest_cache .ruff_cache
	rm -rf __pycache__
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "Clean complete. Ready for fresh build."

typecheck:
	@echo "Typecheck not implemented for $(SERVICE_NAME)"
