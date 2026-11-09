"""ASGI entry point:  uvicorn app.main:app --host 127.0.0.1 --port 8000"""
from .api.main import create_app

app = create_app()
