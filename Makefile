PY = poetry run

.PHONY: help install fmt lint type test cov precommit run dashboard ui-dev ui-build

help:
	@echo "Targets: install fmt lint type test cov precommit run dashboard ui-dev ui-build"

install:
	poetry install

fmt:
	$(PY) ruff format
	$(PY) black mad tests || true

lint:
	$(PY) ruff check mad tests
	$(PY) bandit -q -r mad || true

type:
	$(PY) mypy .

test:
	$(PY) pytest -q

cov:
	$(PY) pytest -q --cov=mad --cov-report=term --cov-report=xml

precommit:
	$(PY) pre-commit run --all-files

run:
	$(PY) freemad "Write a function that returns Fibonacci(n)." --rounds 1 --save-transcript --format json --config examples/two_agents_direct.yaml

dashboard:
	$(PY) freemad-dashboard --dir transcripts

ui-dev:
	cd freemad_dashboard_ui && npm install && npm run dev

ui-build:
	cd freemad_dashboard_ui && npm install && npm run build
