"""Trusted private composition without process, network or public activation.

The host provides validated objects before the cached platform graph exists.
This module reads no environment, discovers no address and starts no server.
"""
from contextlib import asynccontextmanager
from dataclasses import dataclass
import threading
import re
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .workspace_access import WorkspaceConflict, WorkspaceInvalid
from .workspace_integrations import PrivateIntegrations


@dataclass(frozen=True)
class PrivateDeployment:
    integrations: PrivateIntegrations
    customer_origin: str | None = None
    receiver_origin: str | None = None

    def __post_init__(self):
        if type(self.integrations) is not PrivateIntegrations:
            raise WorkspaceInvalid()
        for value in (self.customer_origin, self.receiver_origin):
            if value is None:
                continue
            try:
                part = urlsplit(value)
                if (part.scheme != 'https' or not part.hostname or not part.hostname.isascii()
                        or part.username or part.password or part.query or part.fragment or part.path
                        or value != 'https://' + part.netloc.lower() or part.port not in (None, 443)):
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise WorkspaceInvalid() from None
        if self.customer_origin and self.customer_origin == self.receiver_origin:
            raise WorkspaceInvalid()
        if self.receiver_origin and not self.integrations.receiver_enabled:
            raise WorkspaceInvalid()
        from .workspace_machine_adapters import _valid_binding
        from .workspace_machine_receiver import _binding
        for binding in self.integrations.destination_bindings:
            _valid_binding(binding)
        for binding in self.integrations.receiver_bindings:
            _binding(binding)


def configure_private(front, configuration):
    """Install once under the same construction lock as platform_for."""
    from .workspace_platform import _construction, platform_for
    if type(configuration) is not PrivateDeployment:
        raise WorkspaceInvalid()
    with _construction:
        if getattr(front, '_workspace_platform', None) is not None or hasattr(front, '_workspace_integrations'):
            raise WorkspaceConflict()
        front._workspace_integrations = configuration.integrations
        try:
            return platform_for(front)
        except BaseException:
            if getattr(front, '_workspace_platform', None) is None:
                del front._workspace_integrations
            raise


def _app(origin):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def protect(request: Request, next_handler):
        provider_callback = bool(re.fullmatch(r'/api/customer-provider-oauth/[0-9]+/callback', request.scope.get('path', '')))
        if provider_callback or request.scope.get('path') in ('/api/customer-auth/callback', '/api/customer-auth/github/callback'):
            request.scope['_customer_provider_callback_query' if provider_callback else '_customer_auth_callback_query'] = request.scope.get('query_string', b'')
            request.scope['query_string'] = b''
            for name in ('_url', '_query_params'):
                if hasattr(request, name):
                    delattr(request, name)
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                   'Referrer-Policy': 'no-referrer', 'X-Robots-Tag': 'noindex,noarchive'}
        if request.url.scheme != 'https' or str(request.base_url).rstrip('/') != origin:
            request.scope.pop('_customer_auth_callback_query', None)
            request.scope.pop('_customer_provider_callback_query', None)
            return JSONResponse({'detail': 'The private service is unavailable.'}, status_code=404, headers=headers)
        try:
            response = await next_handler(request)
        finally:
            request.scope.pop('_customer_auth_callback_query', None)
            request.scope.pop('_customer_provider_callback_query', None)
        response.headers.update(headers)
        return response
    return app


def receiver_app(graph, configuration):
    """Only the signed machine ingress, never staff or customer routes."""
    from .workspace_machine_receiver_service import router_for
    if type(configuration) is not PrivateDeployment or not configuration.receiver_origin:
        raise WorkspaceInvalid()
    app = _app(configuration.receiver_origin)
    app.include_router(router_for(graph.machine_receiver, enabled=True,
        allowed_hosts=(urlsplit(configuration.receiver_origin).hostname,)))
    return app


def customer_app(graph, configuration):
    """Private host composition; the global public Workspace remains closed."""
    from .customer_identity_service import router_for as identity
    from .customer_authoring_service import router_for as authoring
    from .workspace_release_service import router_for as releases
    from .workspace_typed_release_service import router_for as typed
    if type(configuration) is not PrivateDeployment or not configuration.customer_origin:
        raise WorkspaceInvalid()
    app = _app(configuration.customer_origin)
    app.include_router(identity(graph.access.store, graph.key, identity=graph.identity, admin=False))
    from .customer_recovery_service import router_for as recovery
    app.include_router(recovery(getattr(graph, 'customer_recovery', None)))
    from .first_party_corpus import router_for as owned_corpus
    app.include_router(owned_corpus(configuration.integrations.corpus_documents,
        enabled=configuration.integrations.first_party_corpus_enabled))
    app.include_router(authoring(graph))
    app.include_router(releases(graph.releases, graph.lifecycle, admin=False))
    app.include_router(typed(graph.typed_releases, admin=False))
    return app


class PrivateRuntime:
    """Two ASGI surfaces share one explicitly configured worker lifecycle."""
    def __init__(self, front, configuration):
        self.front = front
        self.graph = configure_private(front, configuration)
        self._lock, self._leases, self._closed = threading.RLock(), 0, False
        self.customer = customer_app(self.graph, configuration) if configuration.customer_origin else None
        self.receiver = receiver_app(self.graph, configuration) if configuration.receiver_origin else None
        for app in (self.customer, self.receiver):
            if app is not None:
                app.router.lifespan_context = self.lifespan

    @asynccontextmanager
    async def lifespan(self, app):
        from .workspace_platform import start_for, close_for
        with self._lock:
            if self._closed:
                raise WorkspaceConflict()
            if self._leases == 0:
                try:
                    started = start_for(self.front)
                except BaseException:
                    self._closed = True
                    raise
                if not started:
                    self._closed = True
                    raise WorkspaceConflict()
            self._leases += 1
        try:
            yield
        finally:
            with self._lock:
                self._leases -= 1
                if self._leases == 0:
                    self._closed = True
                    if not close_for(self.front):
                        raise WorkspaceConflict()


def compose_private(front, configuration):
    """Operator entrypoint: provide .customer/.receiver to the chosen ASGI host.

    This returns apps, never launches listeners, reads credentials or changes
    the existing public app. Hosts must use the exact configured TLS origins.
    """
    if type(configuration) is not PrivateDeployment or not configuration.customer_origin and not configuration.receiver_origin:
        raise WorkspaceInvalid()
    return PrivateRuntime(front, configuration)
