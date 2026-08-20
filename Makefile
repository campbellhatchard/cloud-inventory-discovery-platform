.PHONY: install migrate seed run worker test lint typecheck compile js-check check clean-runtime openapi

install:
	python -m pip install -r requirements-dev.txt

migrate:
	alembic upgrade head

seed:
	python -m app.seed

run:
	uvicorn app.main:app --reload

worker:
	python -m app.worker

test:
	pytest -q

lint:
	ruff check .

typecheck:
	mypy app

compile:
	python -m compileall app alembic

js-check:
	node --check app/static/app.js
	node --check app/static/enhancements-v0.9.0.js

check: lint test compile js-check

openapi:
	python scripts/generate_openapi.py

clean-runtime:
	rm -rf .pytest_cache tests/.runtime discovery.db
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find local-storage -mindepth 1 ! -name .gitkeep -delete
