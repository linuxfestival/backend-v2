#!/bin/sh

python manage.py makemigrations accounts
python manage.py makemigrations shop
python manage.py migrate

gunicorn --env DJANGO_SETTINGS_MODULE=backend.settings backend.wsgi:application --bind 0.0.0.0:8000