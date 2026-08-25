"""
Shared slowapi Limiter instance. Lives in its own module (not backend/main.py)
so backend/routes/admin.py can decorate its routes with the same limiter
without importing backend.main — main.py imports admin's router, so the
reverse import would be circular.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
