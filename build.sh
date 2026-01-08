#!/usr/bin/env bash
set -o errexit

pip install --upgrade pip
pip install -r requirements_production.txt
python manage.py collectstatic --noinput