# Makefile for LLM-Nomic project
# Provides convenient commands for development and CI

.PHONY: help install format lint typecheck test ci

# Default target - show help
help:
	@echo "Available targets:"
	@echo "  make install    - Install project dependencies"
	@echo "  make format     - Run auto-formatters (black, ruff --fix)"
	@echo "  make lint       - Run linters (ruff, black --check)"
	@echo "  make typecheck  - Run type checker (mypy)"
	@echo "  make test       - Run tests (pytest)"
	@echo "  make ci         - Run full quality suite (lint + typecheck + test)"

# Install dependencies
install:
	pip install --upgrade pip
	pip install -r requirements.txt
	pre-commit install

# Run auto-formatters
format:
	black --line-length=79 src tests
	ruff check --fix src tests

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
