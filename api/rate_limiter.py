"""Shared rate-limiter instance.

Defining the limiter in a separate module guarantees that the FastAPI
app, the SlowAPIMiddleware, and the per-router @limiter.limit decorators
all reference the same Limiter object — without that, decorators on
auth.py have no effect (they were attached to a second, never-installed
limiter prior to 2026-05-02).
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
