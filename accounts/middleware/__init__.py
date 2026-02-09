# accounts/middleware/__init__.py
from .middleware import UpdateLastActiveMiddleware, ProfileCompletionMiddleware

__all__ = ['UpdateLastActiveMiddleware', 'ProfileCompletionMiddleware']