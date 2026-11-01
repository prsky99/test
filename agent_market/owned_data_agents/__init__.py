"""Staged first-party data agents. Importing never mounts or registers them."""

from .engine import DataAgents, DataUnavailable
from .service import create_app, router_for

__all__ = ('DataAgents', 'DataUnavailable', 'create_app', 'router_for')
