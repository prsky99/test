"""Byte-bounded resource reads with snapshot-verified contract hydration."""
from psycopg import sql
from .application_sql import placeholders, resource_predicate
from .concierge.retrieval_metrics import timed
MAX_RESOURCE_BYTES = 64 * 1024 * 1024


@timed('resource_read')
def resources(store, ids, where, parameters, *, allow_partial=False, source_only=False, hydrate_contracts=False,
              columns=None):
    """Keep full contracts intact without raising the per-query byte limit.

    WHERE is trusted repository code; IDs and every filter value remain bound.
    The caller holds a repeatable-read transaction, so size estimates and rows
    refer to the same versions. JSON wire length plus numeric allowance bounds
    decoded row bytes, including large provider schemas and descriptions.
    Narrow vector-source reads retain the same complete-row admission budget.
    Public contract reuse requires a read-only repeatable-read transaction and
    hashes of the current database text, independent of provider declarations.
    """
    from .application_store_postgres import ApplicationStoreError, MAX_BYTES, _CATALOG
    if (any(type(v) is not bool for v in (allow_partial, source_only, hydrate_contracts))
            or source_only and hydrate_contracts
            or not isinstance(ids, (list, tuple)) or len(ids) > 1000
            or any(type(value) is not int or not 0 < value < 2**63 for value in ids)):
        raise ApplicationStoreError('invalid_parameters')
    if type(parameters) not in (list, tuple):
        raise ApplicationStoreError('invalid_parameters')
    catalog = {column[1]: column[2] for column in _CATALOG['metadata']['resources']}
    if columns is not None:
        # A narrow ranking read: trusted catalog columns only, never contracts it does not name.
        if (source_only or hydrate_contracts or type(columns) is not tuple or not columns
                or any(type(name) is not str or name not in catalog for name in columns)):
            raise ApplicationStoreError('invalid_parameters')
        columns = tuple(dict.fromkeys(('id', *columns)))
    predicate = resource_predicate(where, len(parameters))
    if not ids:
        return []
    ids = list(dict.fromkeys(ids))
    result, decoded_bytes, reserved_bytes = [], 0, 0
    measured = columns or tuple(catalog)
    overhead = 8 * len(measured)
    text_bytes = sql.SQL('+').join([sql.SQL('coalesce(octet_length({}),0)').format(sql.Identifier(name))
                                    for name in measured if catalog[name] == 'TEXT'] or [sql.SQL('0')])
    from .concierge import discovery_contracts as cache
    hydrate_contracts = hydrate_contracts and cache.active()
    if hydrate_contracts:
        mode = store._execute("SELECT current_setting('transaction_isolation'),current_setting('transaction_read_only')").fetchone()
        hydrate_contracts = tuple(mode) == ('repeatable read', 'on')
    populate_contracts = hydrate_contracts
    probe_contracts = hydrate_contracts and cache.payloads_available()
    projection = sql.SQL('*')
    if columns is not None:
        projection = sql.SQL(',').join(sql.Identifier(name) for name in columns)
    elif source_only:
        from .legacy_vector_index import _RAW
        if len(_CATALOG['metadata']['resources']) > 128:
            return []
        projection = sql.SQL(',').join(sql.Identifier(name) for name in _RAW)
    elif hydrate_contracts:
        projection = sql.SQL(',').join(sql.Identifier(column[1]) for column in _CATALOG['metadata']['resources']
                              if column[1] not in ('usage_tools', 'usage_full_tools'))
    for start in range(0, len(ids), 100):
        hydrate_contracts = populate_contracts and probe_contracts
        selected = list(ids[start:start + 100])
        marks = placeholders(len(selected))
        extra = sql.SQL(",encode(sha256(convert_to(usage_tools,'UTF8')),'hex'),encode(sha256(convert_to(usage_full_tools,'UTF8')),'hex')"
                        if hydrate_contracts else '')
        # Exactly the decoded-byte measure below: UTF-8 text lengths plus 8 per
        # column. octet_length reads TOAST headers instead of serializing rows.
        size_query = sql.SQL("""SELECT id,{}+%s AS wire_bound{}
            FROM resources WHERE id IN ({}) AND {}""").format(text_bytes, extra, marks, predicate)
        sizes = store._execute(size_query.as_string(), [overhead, *selected, *parameters]).fetchall()
        batch, budget = [], 0

        def fetch(values):
            nonlocal decoded_bytes, probe_contracts
            cached = {rid: cache.payload(hashes_by_id[rid]) for rid in values} if hydrate_contracts else {}
            direct = hydrate_contracts and sum(value is None for value in cached.values()) > len(values) // 2
            selected_projection = sql.SQL('*') if direct or populate_contracts and not hydrate_contracts else projection
            query = sql.SQL('SELECT {} FROM resources WHERE id IN ({}) AND {}').format(
                selected_projection, placeholders(len(values)), predicate)
            rows = store._execute(query.as_string(), [*values, *parameters]).fetchall()
            if direct:
                # A cold batch uses one complete read; avoid transferring its
                # metadata and source separately just to populate the cache.
                for row in rows:
                    cache.remember_payload(hashes_by_id[row['id']], (row['usage_tools'], row['usage_full_tools']))
                probe_contracts = False
            elif populate_contracts and not hydrate_contracts:
                for row in rows:
                    cache.remember_observed_payload((row['usage_tools'], row['usage_full_tools']))
            elif hydrate_contracts:
                dictionaries = [dict(row) for row in rows]
                missing, payloads = [], {}
                for row in dictionaries:
                    found = cached[row['id']]
                    if found is None: missing.append(row['id'])
                    else: payloads[row['id']] = found
                if missing:
                    source_query = sql.SQL('SELECT id,usage_tools,usage_full_tools FROM resources WHERE id IN ({}) AND {}').format(
                        placeholders(len(missing)), predicate)
                    source_rows = store._execute(source_query.as_string(), [*missing, *parameters]).fetchall()
                    for row in source_rows:
                        pair = (row['usage_tools'], row['usage_full_tools'])
                        cache.remember_payload(hashes_by_id[row['id']], pair)
                        payloads[row['id']] = pair
                for row in dictionaries:
                    pair = payloads[row['id']]
                    row['usage_tools'], row['usage_full_tools'] = pair
                # Preserve the native Row iteration contract for byte accounting.
                rows = dictionaries
            for row in rows:
                decoded_bytes += sum(len(value.encode()) if type(value) is str else
                    len(value) if type(value) is bytes else 8 for value in (row.values() if isinstance(row, dict) else row))
            if decoded_bytes > MAX_RESOURCE_BYTES:
                raise ApplicationStoreError('result_limit')
            result.extend(rows)

        size_by_id = {row[0]: row[1] for row in sizes}
        hashes_by_id = {row[0]: (row[2], row[3]) for row in sizes} if hydrate_contracts else {}
        for rid in selected:
            if rid not in size_by_id: continue
            size = size_by_id[rid]
            if allow_partial:
                # Omit whole contracts only. A truncated schema could falsely
                # authorize a call or misrepresent an input requirement.
                if size > MAX_BYTES or reserved_bytes + size > MAX_RESOURCE_BYTES:
                    continue
                reserved_bytes += size
            if batch and budget + size > MAX_BYTES:
                fetch(batch)
                batch, budget = [], 0
            batch.append(rid)
            budget += size
        if batch:
            fetch(batch)
    by_id = {row['id']: row for row in result}
    return [by_id[rid] for rid in ids if rid in by_id]
