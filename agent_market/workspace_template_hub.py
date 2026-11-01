"""Customer-owned configurations of the shared public workflow catalog.

The reviewed product graph stays immutable. Parameter edits retain its routing
proof; arbitrary graphs use the separate typed editor and never inherit it.
"""
import copy
import re
import secrets
import time

from .shadow_ledger import SignedWorkspaceModule, exact
from .workspace_access import WorkspaceDenied, WorkspaceConflict, WorkspaceInvalid, _canonical, _rows, _safe_text, _hash
from .workflow_fallback import NOTICE as FALLBACK_NOTICE
from .workflows import public_template, public_outcome, WorkflowError

PROFILE = 'customer-template-hub-v1'
SAVE_NOTICE = 'save-reviewed-template-configuration-v1'
RUN_NOTICE = 'run-reviewed-template-with-alternative-v1'
FIXED_RUN_NOTICE = 'run-reviewed-template-defaults-v1'
SCHEMA = ('''CREATE TABLE IF NOT EXISTS workspace_template_records (
 id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,kind TEXT NOT NULL,
 parent TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,
 signature TEXT NOT NULL,created REAL NOT NULL)''',
 '''CREATE INDEX IF NOT EXISTS idx_workspace_template_records_scope ON workspace_template_records(workspace_id,kind,parent,created)''')


class TemplateHub(SignedWorkspaceModule):
    def __init__(self, core):
        self.core = core
        super().__init__(core.access, PROFILE, SCHEMA)

    @property
    def runtime(self):
        value = getattr(self.store, '_workflow_runtime', None)
        if value is None:
            raise WorkspaceDenied()
        return value

    def product(self, template, expected=None):
        if type(template) is not int or not 0 < template < 2**31:
            raise WorkspaceInvalid()
        workflow = self.store.get_workflow(template)
        value = public_template(workflow, self.runtime) if workflow else None
        if not value:
            raise WorkspaceDenied()
        if value.get('product'):
            if not value.get('fallback_available'):
                raise WorkspaceDenied()
        else:
            from .concierge.execution_availability import workflow_execution_availability
            if not workflow_execution_availability(self.store, workflow)['available']:
                raise WorkspaceDenied()
        if expected is not None and expected != value['definition_hash']:
            raise WorkspaceConflict()
        return workflow, value

    def catalog(self, ws, actor):
        with self.access._tx(actor):
            self.scope(ws, actor)
            products = []
            if getattr(self.store, '_workflow_runtime', None) is None:
                return {'templates': [], 'save_notice': SAVE_NOTICE, 'run_notice': RUN_NOTICE,
                        'automatic_execution': False, 'graph_editing_preserves_fallback': False}
            from .concierge.workflow_discovery import published_templates
            products = published_templates(self.store, runtime=self.runtime)
            return {'templates': products, 'save_notice': SAVE_NOTICE, 'run_notice': RUN_NOTICE,
                    'automatic_execution': False, 'graph_editing_preserves_fallback': False}

    def read(self, db, ws, identity, kind):
        rows = _rows(db, 'SELECT * FROM workspace_template_records WHERE id=? AND workspace_id=? AND kind=?', (identity, ws, kind))
        if len(rows) != 1:
            raise WorkspaceDenied()
        value = self.opened(rows[0])
        if any(value.get(k) != rows[0][k] for k in ('id', 'workspace_id', 'kind', 'parent', 'revision', 'created')):
            raise WorkspaceConflict()
        return value

    def insert(self, db, value):
        db.execute('INSERT INTO workspace_template_records VALUES(?,?,?,?,?,?,?,?)',
                   (value['id'], value['workspace_id'], value['kind'], value['parent'], value['revision'], _canonical(value), self.sign(value), value['created']))

    @staticmethod
    def dto(value):
        return {k: value[k] for k in ('id', 'name', 'revision', 'template_id', 'definition_hash', 'inputs', 'created')}

    def listing(self, ws, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            items = [self.read(db, ws, row['id'], 'draft') for row in _rows(db,
                'SELECT id FROM workspace_template_records WHERE workspace_id=? AND kind=? ORDER BY created DESC LIMIT 100', (ws, 'draft'))]
            return [self.dto(v) for v in items]

    def prepare(self, ws, body, actor):
        exact(body, ('template_id', 'definition_hash', 'name', 'inputs', 'draft_id', 'revision'))
        name = _safe_text(body['name'], 120)
        with self.access._tx(actor, write=True) as (db, _):
            self.core.access.require_editor(ws, actor)
            self.core.credits.require(db, actor)
            if type(body['revision']) is not int or body['revision'] < 0:
                raise WorkspaceInvalid()
            old = None
            if body['draft_id'] is not None:
                old = self.read(db, ws, body['draft_id'], 'draft')
                if type(body['revision']) is not int or old['revision'] != body['revision'] or old['template_id'] != body['template_id']:
                    raise WorkspaceConflict()
            elif body['revision'] != 0:
                raise WorkspaceInvalid()
            workflow, product = self.product(body['template_id'], body['definition_hash'])
            if type(body['inputs']) is not dict or set(body['inputs']) != {f['name'] for f in product.get('product', {}).get('inputs', [])}:
                raise WorkspaceInvalid()
            try:
                if product.get('product'):
                    self.runtime.products.prepare(workflow, {'kind': 'public', 'role': 'operator', 'subject': 'public'}, 'public', body['inputs'])
            except ValueError:
                raise WorkspaceInvalid() from None
            charge = self.core.credits.quote_in_transaction(db, ws, old['id'] if old else None, actor)
            value = {**body, 'name': name, 'workspace_id': ws, 'owner': actor.customer_id,
                     'session': actor.session_ref, 'expires': time.time()+300,
                     'review_id': 'tr_' + secrets.token_hex(16), 'credit_charge': charge}
            return {'proposal': value, 'signature': self.sign(value), 'credit_charge': charge, 'notice': SAVE_NOTICE}

    def save(self, ws, body, actor):
        exact(body, ('proposal', 'signature', 'authorized', 'notice'))
        p = body['proposal']
        if body['authorized'] is not True or body['notice'] != SAVE_NOTICE or type(p) is not dict or type(body['signature']) is not str or not self._artifact_signer.verify(p, body['signature']):
            raise WorkspaceDenied()
        with self.access._tx(actor, write=True) as (db, _):
            self.core.access.require_editor(ws, actor)
            if p['workspace_id'] != ws or p['owner'] != actor.customer_id or p['session'] != actor.session_ref:
                raise WorkspaceDenied()
            # A committed review remains idempotent, but never grants execution.
            rows = _rows(db, 'SELECT * FROM workspace_template_records WHERE id=? AND workspace_id=? AND kind=?', (p['review_id'], ws, 'version'))
            if rows:
                saved = self.read(db, ws, p['review_id'], 'version')
                if saved['review_hash'] != _hash(p):
                    raise WorkspaceConflict()
                return {**self.dto(saved), 'id': saved['parent'], 'replayed': True}
            if not time.time() < p['expires']:
                raise WorkspaceDenied()
            self.product(p['template_id'], p['definition_hash'])
            old = self.read(db, ws, p['draft_id'], 'draft') if p['draft_id'] is not None else None
            if old and old['revision'] != p['revision']:
                raise WorkspaceConflict()
            if p['credit_charge'] != self.core.credits.quote_in_transaction(db, ws, old['id'] if old else None, actor):
                raise WorkspaceConflict()
            if old is None and db.execute('SELECT COUNT(*) FROM workspace_template_records WHERE workspace_id=? AND kind=?', (ws, 'draft')).fetchone()[0] >= 100:
                raise WorkspaceConflict()
            identity = old['id'] if old else 'wpt_' + secrets.token_hex(16)
            revision = p['revision'] + 1
            value = {k: copy.deepcopy(p[k]) for k in ('name', 'inputs', 'template_id', 'definition_hash')}
            value.update(id=p['review_id'], workspace_id=ws, kind='version', parent=identity, revision=revision, created=time.time(), review_hash=_hash(p))
            self.insert(db, value)
            head = {**value, 'id': identity, 'kind': 'draft', 'created': old['created'] if old else value['created']}
            if old:
                if db.execute('UPDATE workspace_template_records SET revision=?,payload=?,signature=? WHERE id=? AND workspace_id=? AND revision=?',
                              (revision, _canonical(head), self.sign(head), identity, ws, old['revision'])).rowcount != 1:
                    raise WorkspaceConflict()
            else:
                self.insert(db, head)
            self.core.credits.saved(db, ws, identity, revision, actor, parent=identity if old else None)
            self.access._audit(db, actor, ws, 'template.save', identity, revision)
            return {**self.dto(head), 'replayed': False}

    def execute(self, ws, draft, body, actor):
        exact(body, ('revision', 'request_id', 'authorized', 'notice'))
        if body['authorized'] is not True or body['notice'] not in (RUN_NOTICE, FIXED_RUN_NOTICE) or type(body['request_id']) is not str or not re.fullmatch(r'[0-9a-f]{32}', body['request_id']):
            raise WorkspaceInvalid()
        identity = 'twr_' + _hash([ws, draft, body['request_id']])[:32]
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True)
            value = self.read(db, ws, draft, 'draft')
            if type(body['revision']) is not int or value['revision'] != body['revision']:
                raise WorkspaceConflict()
            workflow, product = self.product(value['template_id'], value['definition_hash'])
            if body['notice'] != (RUN_NOTICE if product.get('product') else FIXED_RUN_NOTICE):
                raise WorkspaceInvalid()
            existing = _rows(db, 'SELECT id FROM workspace_template_records WHERE id=? AND workspace_id=?', (identity, ws))
            if existing:
                raise WorkspaceConflict()  # Inspect retained history; never re-dispatch.
            count = db.execute('SELECT COUNT(*) FROM workspace_template_records WHERE workspace_id=? AND kind=? AND created>?', (ws, 'run', time.time()-60)).fetchone()[0]
            if count >= 20:
                raise WorkspaceConflict()
            record = dict(id=identity, workspace_id=ws, kind='run', parent=draft, revision=value['revision'], created=time.time(), state='dispatching', run_id=None, sealed=None)
            self.insert(db, record)
            self.access._audit(db, actor, ws, 'template.run', identity, value['revision'])
        # The committed dispatch boundary makes an interrupted admission uncertain,
        # rather than silently repeating an externally accepted operation.
        try:
            result = self.runtime.submit(workflow, source='public', public=True,
                allow_fallback=bool(product.get('product')),
                fallback_notice=FALLBACK_NOTICE if product.get('product') else None,
                product_input=value['inputs'] if product.get('product') else None)
        except (ValueError, WorkflowError):
            raise WorkspaceConflict() from None
        with self.access._tx(actor, write=True) as (db, _):
            self.scope(ws, actor, write=True)
            record.update(state='accepted', run_id=result['run_id'], sealed=self.runtime._seal(result['run_key'], identity))
            db.execute('UPDATE workspace_template_records SET payload=?,signature=? WHERE id=? AND workspace_id=?', (_canonical(record), self.sign(record), identity, ws))
        return {'id': identity, 'status': result['status']}

    def runs(self, ws, draft, actor):
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor)
            self.read(db, ws, draft, 'draft')
            records = [self.read(db, ws, r['id'], 'run') for r in _rows(db,
                'SELECT id FROM workspace_template_records WHERE workspace_id=? AND kind=? AND parent=? ORDER BY created DESC LIMIT 20', (ws, 'run', draft))]
        values = []
        for record in records:
            run = {'status': 'unknown'}
            if record['state'] == 'accepted' and self.runtime.authorized(record['run_id'], self.runtime._open(record['sealed'], record['id'])):
                run = public_outcome(self.runtime.get(record['run_id']))
                run.pop('run_id', None)
            values.append({'id': record['id'], 'revision': record['revision'], 'created': record['created'], **run})
        return values

    def package(self, ws, draft, revision, actor):
        from .workflow_product_package import build_product_package
        from io import BytesIO
        from zipfile import ZipFile, ZIP_DEFLATED
        from html import escape
        with self.access._tx(actor) as (db, _):
            self.scope(ws, actor, owner=True)
            value = self.read(db, ws, draft, 'draft')
            if str(value['revision']) != revision:
                raise WorkspaceConflict()
            workflow, product = self.product(value['template_id'], value['definition_hash'])
        runs = self.runs(ws, draft, actor)
        if not any(r['revision'] == value['revision'] and r['status'] == 'succeeded' for r in runs):
            raise WorkspaceDenied()
        if product.get('product'):
            product = copy.deepcopy(product)
            product['name'] = value['name']
            archive, filename = build_product_package(product)
        else:
            from .workflow_webapp import export_config, build_package
            config = export_config(workflow)
            config['title'] = value['name']
            archive, filename = build_package(config)
        output = BytesIO()
        with ZipFile(BytesIO(archive)) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == 'index.html':
                    text = data.decode()
                    for name, default in value['inputs'].items():
                        marker = 'name="' + escape(name, quote=True) + '" '
                        text = text.replace(marker, marker + 'value="' + escape(str(default), quote=True) + '" ')
                    data = text.encode()
                target.writestr(item.filename, data)
        self.core.credits.downloaded(ws, draft, value['revision'], actor)
        return output.getvalue(), filename
