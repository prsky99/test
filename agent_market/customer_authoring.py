"""Customer-owned task, typed-DAG and separate A2A session authoring.

This profile creates no staff membership and does not open the public frontend.
The common SDK gateway consumes the same signed releases and deployment rows.
"""
from .customer_organizations import CustomerOrganizations
from .customer_workspace_runtime import CustomerWorkspaceAccess
from .workspace_access import WorkspaceDenied
from .workspace_execution import WorkspaceExecution
from .workspace_release import WorkspaceReleases
from .workspace_metering import WorkspaceMetering
from .workspace_typed_flows import TypedFlows
from .workspace_typed_release import CustomerTypedFlows, WorkspaceTypedReleases
from .workspace_app_factory import AppFactory
from .workspace_support_outcomes import SupportOutcomes
from .customer_task_outcomes import CustomerTaskOutcomes
from .workflow_support import WorkflowSupport
from .workspace_remote_a2a import RemoteTasks


class CustomerAuthoringAccess(CustomerWorkspaceAccess):
    def _access(self, ws, actor, write=False, owner=False):
        value = super()._access(ws, actor, write=write, owner=owner)
        if not self.store._db.execute(
                'SELECT 1 FROM customer_organizations WHERE workspace_id=? AND active=1', (ws,)).fetchone():
            raise WorkspaceDenied()
        return value

    def require_editor(self, ws, actor):
        self._access(ws,actor,write=True)
        if self._authorize(actor,True)['role'] not in ('owner','editor') or actor.token_ref is not None:
            raise WorkspaceDenied()


class CustomerOwnedTypedFlows(CustomerTypedFlows):
    """Current customer editors author; runners execute a reviewed graph only."""
    EXECUTOR = 'customer'

    def options(self, ws, actor):
        from .workspace_provider_connections import profile
        from .workspace_access import WorkspaceConflict, WorkspaceInvalid
        from .workspace_app_factory import AppFactory
        value = super().options(ws, actor)
        # Labelling candidates only reads, so it skips the global writer lock (11-01: slowest opening read).
        with self.access._tx(actor, readonly=True) as (db, _):
            self._authority(ws, actor, write=False)
            for candidate in value['candidates']:
                resource = self.store.resource(candidate['resource_id'])
                if not resource:
                    candidate.update(name='Unavailable agent', executable=False,
                                     connection_label='Unavailable', connection_reason='This agent is no longer available.')
                    continue
                p = profile(resource)
                candidate['name'] = p['name']
                try:
                    node = AppFactory._node('candidate', candidate['resource_id'], candidate['contract_id'],
                                            'Reviewed application task', None, [])
                    self._pin(db, node, self._sample(node))
                    candidate.update(executable=True, connection_label='Ready for review', connection_reason='')
                except (WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid, ValueError, TypeError, KeyError):
                    candidate.update(executable=False, connection_label='Setup or verification required',
                                     connection_reason=('Provider authorization and execution support are required. Review Provider connection options.'
                                         if p['mode'] in ('api_key', 'oauth', 'payment') or resource.get('price_usdc')
                                         else 'This agent is not currently verified for this task. Choose another agent or review its connection options.'))
        return value

    def save(self, *args, **kwargs):
        return TypedFlows.save(self,*args,**kwargs)

    def _save_in_transaction(self, db, ws, body, actor, credit_parent=None):
        self.access.require_editor(ws,actor)
        result = super()._save_in_transaction(db,ws,body,actor)
        self.credits.saved(db,ws,result['id'],result['revision'],actor,
                           parent=credit_parent or body.get('flow_id'))
        return result

    def save_reviewed(self, db, ws, body, actor, parent):
        return self._save_in_transaction(db,ws,body,actor,credit_parent=parent)

    def _may_disable(self, ws, actor):
        # Role checks read the customer link inside the same transaction as the change.
        self.access.require_editor(ws,actor)

    def disable(self, ws, flow, body, actor):
        return TypedFlows.disable(self,ws,flow,body,actor)


class CustomerAppFactory(AppFactory):
    # 11-01: "Save changes" in the customer studio records the next revision of the same workflow.
    REVISE_BASE = True

    def __init__(self,*args,model_source=None,**kwargs):
        self.model_source,self._source_generation=model_source,None
        super().__init__(*args,**kwargs)

    @property
    def model_proposer(self):
        if self.model_source is not None and self._source_generation != self.model_source._model_generation:
            AppFactory.model_proposer.fset(self,self.model_source.model_proposer)
            self._source_generation=self.model_source._model_generation
        return AppFactory.model_proposer.fget(self)

    @model_proposer.setter
    def model_proposer(self,value):
        if self.model_source is not None:
            raise WorkspaceDenied()
        AppFactory.model_proposer.fset(self,value)

    def _authority(self, ws, actor, *, write=False, owner=False):
        if write:
            self.access.require_editor(ws,actor)
            self.typed.credits.require(self.access.store._db,actor)
        authority=super()._authority(ws,actor,write=write,owner=owner)
        authority['member_role']=self.access._authorize(actor,write)['role']
        return authority


class CustomerAuthoring:
    """Reviewed inputs and immutable releases under current customer authority."""
    def __init__(self, platform):
        self.identity = platform.identity
        from .customer_credits import CustomerCredits
        self.credits = CustomerCredits(self.identity)
        self.organizations = CustomerOrganizations(platform.identity, platform.access)
        self.access = CustomerAuthoringAccess(platform.access, platform.identity)
        self.execution = WorkspaceExecution(self.access, platform.execution.proxy)
        self.meter = WorkspaceMetering(self.access, self.execution)
        self.execution.meter = self.meter
        self.releases = WorkspaceReleases(self.execution, customer_identity=platform.identity,
                                         customer_executor=platform.app_execution)
        self.releases.compatibility_guard = platform.releases.compatibility_guard
        self.typed = CustomerOwnedTypedFlows(self.execution)
        self.typed.credits = self.credits
        self.organizations.drafts.credits = self.credits
        self.app_typed = CustomerTypedFlows(self.execution)
        self.typed_releases = WorkspaceTypedReleases(self.typed,customer_identity=platform.identity,
                                                   customer_flows=self.app_typed)
        self.typed_releases.compatibility_guard = getattr(getattr(platform,'typed_releases',None),'compatibility_guard',None)
        self.factory = CustomerAppFactory(self.typed,typed_releases=self.typed_releases,
            model_source=getattr(platform,'app_factory',None))
        from .workspace_template_hub import TemplateHub
        self.templates = TemplateHub(self)
        self.outcomes = CustomerTaskOutcomes(self.access,SupportOutcomes(self.access,self.execution,self.typed))
        self.support = WorkflowSupport(self.access)
        configured_remote = getattr(platform,'remote_tasks',None)
        self.remote_tasks = RemoteTasks(self.access,
            bindings=tuple(configured_remote.bindings.values()) if configured_remote is not None else (),
            cipher=configured_remote.cipher if configured_remote is not None else None)

    def actor(self, ws, customer):
        return self.organizations.runtime_actor(ws, customer)


def authoring_for(platform):
    # Construct under the Store lock before publishing the graph reference.
    with platform.access.store._lock:
        existing = getattr(platform, 'customer_authoring', None)
        if existing is None:
            existing = CustomerAuthoring(platform)
            platform.customer_authoring = existing
        return existing
