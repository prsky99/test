"""Negative failure-domain guards; different endpoints do not prove independence.

No network, discovery, approval or inference from untrusted annotations occurs.
"""
from urllib.parse import urlsplit
import ipaddress
import json

from .concierge.recommendation_security import usable_endpoint


class IndependenceDenied(ValueError):
    pass


def identity(resource):
    value = resource.get('url') if isinstance(resource, dict) else None
    if not usable_endpoint(value):
        raise IndependenceDenied('A public registered endpoint is required.')
    parsed = urlsplit(value)
    host = parsed.hostname.rstrip('.').encode('idna').decode('ascii').lower()
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        pass
    return (parsed.scheme.lower(), host,
            parsed.port or (443 if parsed.scheme.lower() == 'https' else 80),
            parsed.path.rstrip('/') or '/', parsed.query), host


def reviewed_dependencies(resource, tool):
    """Known and declared negative dependencies; never an independence grant."""
    _, host = identity(resource)
    domains = {'host:' + host}
    # Published Paper Finder support lists these sources. A candidate is not
    # independent of Crossref merely because the MCP server has another name.
    if host == 'papers.openkrill.app' and tool == 'search_papers':
        domains.add('upstream:api.crossref.org')
    if (host == 'agentconcierge.biz'
            and identity(resource)[0][3] == '/api/owned-data-agents/research-papers/mcp'
            and tool == 'search_research_papers'):
        domains.add('upstream:api.crossref.org')
    # Declared shared service/operator data can exclude a pair, never prove it
    # independent. Conservative first-pilot rejection is intentional.
    details = resource.get('details') or {}
    if isinstance(details, str):
        if len(details) > 262144:
            raise IndependenceDenied('Dependency metadata exceeds the review limit.')
        try:
            details = json.loads(details)
        except ValueError:
            raise IndependenceDenied('Review the registered dependency metadata.') from None
    if not isinstance(details, dict):
        raise IndependenceDenied('Review the registered dependency metadata.')
    registry = details.get('registry_name')
    if isinstance(registry, str) and '/' in registry:
        namespace = registry.split('/', 1)[0].lower()
        if '.' in namespace:
            domains.add('declared-registry-publisher:' + namespace)
    repo = details.get('repository') or {}
    repo = repo.get('url') if isinstance(repo, dict) else repo
    if isinstance(repo, str):
        parts = urlsplit(repo)
        owner = parts.path.strip('/').split('/')[0]
        if parts.hostname in ('github.com', 'gitlab.com') and owner:
            domains.add('declared-repository-publisher:' + parts.hostname + '/' + owner.lower())
    for remote in details.get('remotes') or []:
        if isinstance(remote, dict) and isinstance(remote.get('url'), str):
            try:
                domains.add('host:' + identity({'url': remote['url']})[1])
            except IndependenceDenied:
                raise IndependenceDenied('Review the declared remote endpoint.') from None
    site = details.get('website') or details.get('websiteUrl')
    if isinstance(site, str) and usable_endpoint(site):
        parts = urlsplit(site)
        domains.add('declared-site:' + parts.hostname.lower().removeprefix('www.')
                    + parts.path.rstrip('/'))
    return domains


def require_distinct(primary, alternate, primary_tool=None, alternate_tool=None):
    """Reject known aliases/dependencies; passing is not an admission grant."""
    a, ahost = identity(primary)
    b, bhost = identity(alternate)
    if primary.get('id') == alternate.get('id') or a == b:
        raise IndependenceDenied('The alternative uses the same registered endpoint.')
    if ahost == bhost:
        raise IndependenceDenied('The alternative shares the primary endpoint host.')
    if reviewed_dependencies(primary, primary_tool) & reviewed_dependencies(alternate, alternate_tool):
        raise IndependenceDenied('The alternative shares a known or declared failure dependency.')
    return True
