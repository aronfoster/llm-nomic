# Makefile for LLM-Nomic project
# Provides convenient commands for development and CI

.PHONY: help install format fix lint typecheck test ci update-deps

# Default target - show help
help:
	@echo "Available targets:"
	@echo "  make install      - Install project dependencies"
	@echo "  make format       - Run auto-formatters (black, ruff --fix)"
	@echo "  make fix          - Alias for make format"
	@echo "  make lint         - Run linters (ruff, black --check)"
	@echo "  make typecheck    - Run type checker (mypy)"
	@echo "  make test         - Run tests (pytest)"
	@echo "  make ci           - Run full quality suite (lint + typecheck + test)"
	@echo "  make update-deps  - Upgrade all dependencies to latest versions and verify"

# Install dependencies
install:
	pip install --upgrade pip
	pip install -r requirements.txt
	pre-commit install

# Run auto-formatters
format:
	black --line-length=79 src tests
	ruff check --fix src tests

# Alias for format
fix: format

# Run linters (check mode only, no fixes)
lint:
	ruff check src tests
	black --check --line-length=79 src tests

# Run type checker
typecheck:
	PYTHONPATH=.:src python3 -m mypy src

# Run tests
test:
	PYTHONPATH=.:src python3 -m pytest tests

# Run full CI suite - this is what developers should run before pushing
ci: lint typecheck test
	@echo "✓ All quality checks passed!"

# Upgrade all dependencies to their latest available versions, update
# requirements.txt with the new exact pins, then verify with make ci.
# If make ci fails the new versions are left in requirements.txt so the
# failure is visible; fix the breakage manually, then re-run make ci.
update-deps:
	python3 scripts/update_deps.py
	pip install -r requirements.txt
	$(MAKE) ci
