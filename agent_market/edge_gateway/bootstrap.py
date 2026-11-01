"""Bind private delivery state independently in public and administrator roles."""
from .config import EdgeError, load
from .service import Service


def configure(front):
    if getattr(front,'managed_gateway',None) is None:
        from ..concierge.managed_gateway import ManagedGateway
        front.managed_gateway=ManagedGateway(front)
    try:
        config = load()
        service = Service(front, config) if config is not None else None
        front.store._edge_gateway_config_error = False
    except EdgeError:
        service = None
        front.store._edge_gateway_config_error = True
    front.edge_gateway = service
    front.store._edge_gateway_service = service
    return service
