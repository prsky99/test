"""Hidden test workflow products for the AI AD Coin closed test.

Published workflows are all free today, so nothing can be sponsored. These
products combine real catalog agents (paid x402 steps that can take coins and
free steps) into a priced task. They never enter the public workflow list,
are never executed against a provider here (runs are simulated) and reject any
step whose name or address looks like it moves money or writes state.
"""
import hashlib
import json
import re
import uuid

from .db import dumps, now
from .receipts import canonical
from .screening import ScreeningRejected, screen_text
from .upgrade import facts

ID = re.compile(r'tp_[0-9a-f]{16}\Z')
KINDS = frozenset(('x402', 'mcp', 'a2a'))
MAX_STEPS = 12
WRITES = re.compile(r'(?<![a-z])(send|transfer|withdraw|swap|bridge|mint|burn|payout|deposit|checkout|purchase|'
                    r'order|buy|sell|delete|remove|update|create|post|publish|sign|approve)', re.IGNORECASE)


class ProductError(ValueError):
    pass


class TestProducts:
    __test__ = False  # not a pytest class

    def __init__(self, database):
        self.db = database

    def create(self, *, name, description, steps, read_resource):
        try:
            name = screen_text(name, 80)
            description = screen_text(description or name, 300)
        except ScreeningRejected as exc:
            raise ProductError('Name or description rejected: ' + ', '.join(exc.reasons)) from None
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise ProductError('A test product needs 1 to 12 steps.')
        nodes, paid, seen = [{'id': 'start', 'type': 'trigger', 'name': 'Manual Trigger'}], 0, set()
        for position, step in enumerate(steps, 1):
            rid, calls = (step.get('resource_id'), step.get('calls_per_run', 1)) if isinstance(step, dict) else (None, None)
            if type(rid) is not int or rid <= 0 or type(calls) is not int or not 1 <= calls <= 100:
                raise ProductError('Each step needs a catalog resource_id and 1 to 100 calls per run.')
            if rid in seen:
                raise ProductError('List each catalog agent once and set its calls per run.')
            seen.add(rid)
            row = read_resource(rid)
            if not row or not row.get('active', 1):
                raise ProductError('Agent %d is not in the active catalog.' % rid)
            if row.get('kind') not in KINDS:
                raise ProductError('Agent %d has an unsupported kind.' % rid)
            if WRITES.search(str(row.get('name', '')) + ' ' + str(row.get('url', ''))):
                raise ProductError('Agent %d looks like it moves money or changes state; test products are read-only.' % rid)
            fact = facts(row)
            if fact['price_won'] and not fact['accepts_coins']:
                raise ProductError('Agent %d is paid but cannot take coins (%s).' % (rid, ', '.join(fact['reasons'])))
            paid += bool(fact['price_won'])
            nodes.append({'id': 's%d' % position, 'type': 'agent', 'kind': row.get('kind'),
                          'name': str(row.get('name') or 'Agent step')[:120], 'resource_id': rid,
                          'data': {'calls_per_run': calls}})
        if not paid:
            raise ProductError('Add at least one paid step; an all-free product needs no sponsor.')
        product_id = 'tp_' + uuid.uuid4().hex[:16]
        definition = {'id': product_id, 'name': name, 'description': description, 'test_product': True,
                      'nodes': nodes, 'edges': [{'source': nodes[i]['id'], 'target': nodes[i + 1]['id']}
                                                for i in range(len(nodes) - 1)]}
        definition['definition_hash'] = hashlib.sha256(canonical(nodes)).hexdigest()
        with self.db.transaction() as db:
            db.execute('INSERT INTO test_products VALUES (?,?,?,?,?,?)',
                       (product_id, name, description, dumps(definition), 'active', now()))
        return definition

    def get(self, product_id):
        if type(product_id) is not str or not ID.fullmatch(product_id):
            return None
        row = self.db.one("SELECT definition FROM test_products WHERE id=? AND status='active'", (product_id,))
        return json.loads(row['definition']) if row else None

    def list(self):
        rows = self.db.all('SELECT id, name, description, status, definition FROM test_products ORDER BY created_at')
        return [{'id': r['id'], 'name': r['name'], 'description': r['description'], 'status': r['status'],
                 'steps': [{'resource_id': n['resource_id'], 'name': n['name'],
                            'calls_per_run': n['data']['calls_per_run']}
                           for n in json.loads(r['definition'])['nodes'] if n['type'] == 'agent']} for r in rows]

    def archive(self, product_id):
        with self.db.transaction() as db:
            if not db.execute("UPDATE test_products SET status='archived' WHERE id=?", (product_id,)).rowcount:
                raise ProductError('Unknown test product.')
        return {'id': product_id, 'status': 'archived'}
