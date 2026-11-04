"""Read a customer's own saved workflow for an AI AD Coin quote.

Uses the customer workspace's existing boundary: the same-origin customer
session cookie, workspace membership and the typed-flow detail read. Holding a
workspace or flow id is not enough. Only the catalog agents and their counts
leave this module; inputs, prompts and outputs of the private flow do not.
"""
import hashlib
import re

from .receipts import canonical

WS = re.compile(r'[A-Za-z0-9_-]{3,80}\Z')
FLOW = re.compile(r'[A-Za-z0-9_-]{3,80}\Z')


class PrivateWorkflowDenied(Exception):
    pass


def project(detail):
    """Keep only what pricing needs: agent nodes, their catalog ids and disabled flags."""
    definition = detail.get('definition') if isinstance(detail, dict) else None
    nodes = definition.get('nodes') if isinstance(definition, dict) else None
    if not isinstance(nodes, list):
        return None
    kept = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get('data') if isinstance(node.get('data'), dict) else {}
        item = {'id': str(node.get('id', ''))[:80], 'type': node.get('type', 'agent')}
        rid = node.get('resource_id') or data.get('resource_id')
        if type(rid) is int:
            item['resource_id'] = rid
        if node.get('disabled') or data.get('disabled'):
            item['disabled'] = True
        if item['type'] == 'agent' and 'resource_id' not in item:
            item['name'] = 'Private step'
        kept.append(item)
    if any(isinstance(n, dict) and n.get('when') for n in nodes):
        kept.append({'id': '_conditional', 'type': 'router'})  # conditional steps: the quote is an upper bound
    return {'id': detail.get('id'), 'name': 'Your saved workflow', 'active': bool(detail.get('active', True)),
            'definition_hash': hashlib.sha256(canonical(kept)).hexdigest(), 'nodes': kept}


def reader_for(front, enabled, core_factory=None):
    """Returns read(request, workspace_id, flow_id) or None when customer workspaces are closed.
    `core_factory` returns the customer authoring core (tests inject one)."""
    if not enabled:
        return None

    def core_of():
        if core_factory is not None:
            return core_factory()
        from ..customer_authoring import authoring_for
        from ..workspace_platform import platform_for
        return authoring_for(platform_for(front))

    def read(request, workspace_id, flow_id):
        if type(workspace_id) is not str or not WS.fullmatch(workspace_id) \
                or type(flow_id) is not str or not FLOW.fullmatch(flow_id):
            raise PrivateWorkflowDenied('invalid_ids')
        from fastapi import HTTPException
        from ..customer_identity_service import customer_actor
        from ..workspace_access import WorkspaceDenied, WorkspaceInvalid
        core = core_of()
        try:
            customer = customer_actor(request, core.identity)
            detail = core.typed.detail(workspace_id, flow_id, core.actor(workspace_id, customer))
        except HTTPException as exc:
            raise PrivateWorkflowDenied('sign_in_required' if exc.status_code == 401 else 'not_allowed') from None
        except (WorkspaceDenied, WorkspaceInvalid, KeyError, ValueError, TypeError):
            raise PrivateWorkflowDenied('not_allowed') from None
        projected = project(detail)
        if not projected or not projected['active']:
            raise PrivateWorkflowDenied('not_allowed')
        return projected
    return read
