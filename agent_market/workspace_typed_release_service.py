"""Distinct typed SDK 2 routes; caller retains the closed public portal gate."""
from .workspace_release_service import router_for as _router_for


def router_for(releases, *, public=True, admin=True):
    return _router_for(releases, None, public=public, admin=admin, typed=True)
