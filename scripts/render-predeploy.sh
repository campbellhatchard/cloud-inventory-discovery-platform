#!/bin/sh
set -eu

echo "Running database migrations..."
python -m alembic upgrade head

echo "Seeding application data..."
python -m app.seed

echo "Pre-deploy tasks completed."
