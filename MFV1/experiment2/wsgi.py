"""WSGI entry point for gunicorn: `gunicorn wsgi:app`."""

from server import create_app

app = create_app()
