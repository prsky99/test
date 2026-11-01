"""Read-only registry census and safe runtime recipes; never invokes Providers."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import math
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

from agent_market.concierge.execution_policy import admit, resolve_a2a, tools_for, safe_registered_tool, ExecutionDenied
from agent_market.edge_gateway.catalog import payload_for
from agent_market.edge_gateway.config import Provider, EdgeError, https_url
from agent_market.collector import usage

PROMPT = 'Hello! In one or two sentences, what can you help with?'
SENSITIVE = re.compile(r'(key|token|secret|password|signature|credential|session|authorization)', re.I)


def safe_probe_input(arguments):
    """Do not forward sensitive defaults/examples supplied by a remote schema."""
    if not isinstance(arguments, dict): return False
    for key, value in arguments.items():
        if SENSITIVE.search(key): return False
        if isinstance(value, str):
            if len(value) > 120 or usage._PII_PARAM.search(key): return False
            if re.search(r'@|\b(?:Bearer|Basic)\s|\b(?:sk-|ghp_|AIza|vt_|eyJ)[A-Za-z0-9_-]{12,}', value): return False
            if re.search(r'\+?\d[\d\s().-]{8,}\d|0x[a-fA-F0-9]{40}', value) and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): return False
            if '://' in value and value not in ('https://example.com', 'https://example.com/'): return False
        elif type(value) in (int, float):
            if not math.isfinite(value) or abs(value) > 1000000: return False
        elif value is not None and type(value) is not bool: return False
    return True


def decoded(value):
    if not isinstance(value, str): return value or {}
    try: return json.loads(value)
    except (ValueError, TypeError): return {}


def classify(resource):
    """Static candidate only: DNS, current capability state and live output remain unchecked."""
    row = {'id': resource['id'], 'protocol': resource['kind']}
    try:
        u = urlsplit(resource.get('url') or '')
        row['host'] = u.hostname or ''
        row['connection_hash'] = hashlib.sha256((resource.get('url') or '').encode()).hexdigest()
        if not resource.get('active'): return {**row, 'status': 'excluded', 'reason': 'inactive'}, None
        # Match ManagedGateway.resource: x402 only probes an unpaid challenge.
        # No payment credentials or charge-authorizing action enter the recipe.
        admit(resource, resource['kind'], public=True, authorize_charge=resource['kind'] == 'x402')
        if any(resource.get(k, 0) > 60000 for k in ('details_bytes','guide_bytes','tools_bytes','full_bytes')):
            return {**row, 'status': 'needs_review', 'reason': 'metadata_exceeds_edge_profile'}, None
        if u.username or u.password or any(SENSITIVE.search(k) for k, _ in parse_qsl(u.query)):
            return {**row, 'status': 'excluded', 'reason': 'credential_in_connection'}, None
        https_url(u._replace(query='').geturl())
        spec, endpoint = '0.3', resource['url']
        if resource['kind'] == 'a2a':
            # No discovery here: the resolver below returns only cached registration data.
            resolver = SimpleNamespace(resolve=lambda _kind, url, **kw: {'url': url, 'v1': False})
            target = resolve_a2a(resource, resolver, public=True)
            endpoint = target['url']; https_url(endpoint)
            spec = '1.0' if target.get('v1') else '0.3'
            value = {'message': PROMPT}
        elif resource['kind'] == 'x402':
            value = {'action': 'probe'}
        elif resource['kind'] == 'mcp':
            if not resource.get('usage_tools_hash'):
                return {**row, 'status': 'needs_metadata', 'reason': 'no_registered_schema'}, None
            registered = tools_for(resource)
            candidates = [t for t in registered if safe_registered_tool(t)]
            trial = usage.pick_trial(candidates, resource.get('category'))
            if not trial:
                return {**row, 'status': 'needs_recipe', 'reason': 'no_safe_readonly_input'}, None
            tool, arguments = trial
            if not safe_probe_input(arguments):
                return {**row, 'status': 'needs_recipe', 'reason': 'unsafe_schema_example'}, None
            value = {'tool': tool['name'], 'arguments': arguments}
        else:
            return {**row, 'status': 'excluded', 'reason': 'unsupported_protocol'}, None
        provider = Provider(resource['id'], 'offline-unverified', endpoint, 'json', False, resource['kind'], spec, True)
        payload_for(provider, value, resource)
        row.update(status='static_candidate', reason='requires_live_dns_and_contract', spec_version=spec)
        recipe = {**row, 'input': value, 'schema_hash': resource.get('usage_full_hash') or resource.get('usage_tools_hash')}
        return row, recipe
    except ExecutionDenied as error:
        return {**row, 'status': 'excluded', 'reason': getattr(error, 'error_code', None) or 'execution_policy',
                'policy_detail': str(error)}, None
    except EdgeError as error:
        return {**row, 'status': 'excluded', 'reason': error.code}, None
    except (ValueError, TypeError, KeyError, StopIteration, RecursionError):
        return {**row, 'status': 'needs_review', 'reason': 'invalid_registered_metadata'}, None


def private_file(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    return os.fdopen(fd, 'w')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    # Reuse the existing native operator storage setup, without changing its policy.
    from scripts.agentcon_config import read_settings
    from agent_market.application_runtime import open_runtime_storage
    root = Path(__file__).resolve().parents[1]
    values = read_settings(root / 'gateway-data/agentcon.env')
    for key in ('APPLICATION_POSTGRES_DSN_FILE', 'APPLICATION_WORKFLOW_KEY_FILE'):
        if key in values: values[key] = str((root / values[key]).resolve())
    output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    counts, reasons, hosts, counts_protocol = Counter(), Counter(), set(), Counter()
    recipes, duplicates, fingerprints = 0, 0, set()
    import time
    started = time.time()
    storage = open_runtime_storage(str(root / 'gateway-data/gateway.db'), values=values)
    try:
        with private_file(output / 'census.jsonl') as census, private_file(output / 'recipes.jsonl') as queue, private_file(output / 'schema-corpus.jsonl') as corpus:
            with storage.store.tx(readonly=True):
                storage.store._execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                bounds = storage.store._execute('SELECT MAX(id) AS ceiling,COUNT(*) AS total FROM resources').fetchone()
                ceiling, expected = bounds['ceiling'] or 0, bounds['total']; cursor = 0
                while cursor < ceiling:
                    batch = storage.store._execute('''SELECT id,kind,url,category,active,health_status,price_usdc,auth_declared,auth_observed,eval_security,
                        CASE WHEN OCTET_LENGTH(details)<=60000 THEN details ELSE NULL END AS details,
                        CASE WHEN OCTET_LENGTH(usage_guide)<=60000 THEN usage_guide ELSE NULL END AS usage_guide,
                        CASE WHEN OCTET_LENGTH(usage_tools)<=60000 THEN usage_tools ELSE NULL END AS usage_tools,usage_tools_hash,
                        CASE WHEN OCTET_LENGTH(usage_full_tools)<=60000 THEN usage_full_tools ELSE NULL END AS usage_full_tools,usage_full_hash,
                        COALESCE(OCTET_LENGTH(details),0) AS details_bytes,COALESCE(OCTET_LENGTH(usage_guide),0) AS guide_bytes,
                        COALESCE(OCTET_LENGTH(usage_tools),0) AS tools_bytes,COALESCE(OCTET_LENGTH(usage_full_tools),0) AS full_bytes FROM resources
                        WHERE id>%s AND id<=%s ORDER BY id LIMIT 16''', (cursor, ceiling)).fetchall()
                    if not batch: break
                    for source in batch:
                        resource = dict(source); cursor = resource['id']
                        row, recipe = classify(resource)
                        census.write(json.dumps(row, separators=(',', ':')) + '\n')
                        counts[row['status']] += 1; reasons[row['reason']] += 1; counts_protocol[(row['protocol'], row['status'])] += 1
                        if row.get('host'): hosts.add(row['host'])
                        if recipe:
                            fingerprint = json.dumps([recipe['protocol'], recipe['connection_hash'], recipe['input'], recipe['schema_hash']], sort_keys=True)
                            if fingerprint in fingerprints:
                                duplicates += 1; continue
                            fingerprints.add(fingerprint)
                            queue.write(json.dumps(recipe, separators=(',', ':')) + '\n'); recipes += 1
                            if resource['kind'] == 'mcp':
                                full = decoded(resource.get('usage_full_tools'))
                                corpus.write(json.dumps({'id': resource['id'], 'protocol': 'mcp', 'input': recipe['input'],
                                    'full_tools': full if isinstance(full,list) else [], 'full_hash': resource.get('usage_full_hash'),
                                    'protocol_version': decoded(resource.get('usage_guide')).get('protocol_version')}, separators=(',', ':')) + '\n')
        total = sum(counts.values())
        if total != expected: raise RuntimeError('Snapshot row count mismatch')
        result = {'started_at': started, 'finished_at': time.time(), 'snapshot_max_id': ceiling, 'records': total,
                  'unique_hosts': len(hosts), 'status_counts': dict(counts), 'reason_counts': dict(reasons),
                  'protocol_status_counts': [{'protocol': k[0], 'status': k[1], 'count': v} for k,v in sorted(counts_protocol.items())],
                  'runtime_recipes': recipes, 'duplicate_recipes': duplicates, 'network_calls': 0,
                  'database_writes': 0, 'live_execution_verified': False}
        (output / 'census-summary.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
    finally: storage.close()


if __name__ == '__main__': main()
