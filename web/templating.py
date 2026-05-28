"""Shared Jinja2 templates instance.

Lives in its own module so route packages and ``web.app`` can both import it
without a circular dependency (``app`` includes the routers).
"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
