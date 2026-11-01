"""Named bounded native social projections; identifiers and SQL are fixed."""
import json

MAX_ITEMS = 4096


def _select(store, sql, parameters):
    with store.tx(readonly=True):
        return store._execute(sql, parameters, max_rows=MAX_ITEMS, max_bytes=4 * 1024 * 1024).fetchall()


def resources_by_id(store, ids):
    from .application_store_postgres import ApplicationStoreError
    if (type(ids) not in (list, tuple) or len(ids) > MAX_ITEMS
            or any(type(value) is not int or not 0 < value < 2**63 for value in ids)):
        raise ApplicationStoreError('invalid_parameters')
    if not ids: return []
    return _select(store, '''SELECT r.id,r.kind,r.name,r.url,r.category,r.description,r.eval_grade
        FROM resources r WHERE r.id IN (SELECT value::bigint FROM jsonb_array_elements_text(%s::jsonb))''',
        (json.dumps(list(dict.fromkeys(ids))),))


def engagement(store, keys, client_id):
    from .application_store_postgres import ApplicationStoreError
    if (type(keys) not in (list, tuple) or len(keys) > MAX_ITEMS
            or any(type(value) is not str or not 1 <= len(value) <= 200 or '\0' in value for value in keys)
            or client_id is not None and (type(client_id) is not str or len(client_id) > 200 or '\0' in client_id)):
        raise ApplicationStoreError('invalid_parameters')
    if not keys: return {}
    keys = list(dict.fromkeys(keys)); encoded = json.dumps(keys)
    with store.tx(readonly=True):
        likes = {row[0]: row[1] for row in _select(store,
            'SELECT post_key,COUNT(*) FROM sns_likes WHERE post_key IN (SELECT value FROM jsonb_array_elements_text(%s::jsonb)) GROUP BY post_key', (encoded,))}
        replies = {row[0]: row[1] for row in _select(store,
            'SELECT parent_key,COUNT(*) FROM sns_posts WHERE deleted=0 AND parent_key IN (SELECT value FROM jsonb_array_elements_text(%s::jsonb)) GROUP BY parent_key', (encoded,))}
        mine = {row[0] for row in _select(store,
            'SELECT post_key FROM sns_likes WHERE client_id=%s AND post_key IN (SELECT value FROM jsonb_array_elements_text(%s::jsonb))', (client_id, encoded))} if client_id else set()
        return {key: {'likes': likes.get(key, 0), 'replies': replies.get(key, 0), 'liked': key in mine} for key in keys}
