"""Build finite legacy social-feed dialect pairs, never runtime SQL rewriting."""
import re


def build_extra_families(root, statement, entries):
    from agent_market.gateway import sns

    class EmptyRows:
        def fetchall(self): return []
        def __iter__(self): return iter(())

    class Capture:
        def __init__(self): self.sql = []
        def execute(self, text, parameters=()):
            self.sql.append(text)
            return EmptyRows()

    db = Capture()
    for protocol in (None, 'mcp'):
        sns._discoveries(db, protocol, [], 3, 1)
        sns._feedback(db, protocol, [], 3)
        for count in range(9):
            terms = ['synthetic-term'] * count
            for rid in (None, 1):
                for read in (sns._evaluations, sns._trials, sns._usage_changes):
                    read(db, protocol, terms, 3, rid)
            for role in (None, 'agent'):
                sns._stored(db, protocol, role, terms, 3)
    for index, sql in enumerate(dict.fromkeys(db.sql)):
        statement('sns.family.' + str(index), sql)
    # The named IN/array methods keep this checked-in corpus bounded. All other
    # social SQL variants above have at most eight fixed query-term predicates.
    for item in entries:
        if not (item['name'].startswith('sns.family.') or item['name'].startswith('gateway/sns.')):
            continue
        sql = item['postgres']
        if re.match(r'\s*INSERT INTO sns_posts\b', item['sqlite']):
            sql += ' RETURNING id'
            item['generated_id'] = 'id'
        sql = re.sub(r'CAST\(first_seen / 3600 AS INT\)', 'TRUNC(first_seen / 3600)::bigint', sql)
        for prefix in ('r.', ''):
            column = prefix + 'trial_info'
            numeric = "jsonb_typeof((" + column + "::jsonb)->'at')='number'"
            sql = sql.replace("json_type(" + column + ", '$.at') IN ('integer','real')", numeric)
            # Guard the cast itself; WHERE predicate order is not a PG planner
            # guarantee and legacy JSON strings/booleans are never timestamps.
            sql = sql.replace("json_extract(" + column + ", '$.at')",
                "(CASE WHEN " + numeric + " THEN ((" + column + "::jsonb)->>'at')::double precision ELSE NULL END)")
        # SQLite LIKE folds ASCII only and treats backslash as an ordinary
        # character. Preserve those semantics for user-entered search terms.
        sql = re.sub(r'(r\.(?:name|description|url)|lower\((?:body|author|handle)\)|tags) LIKE %s',
            lambda m: "translate(" + (m[1][6:-1] if m[1].startswith('lower(') else m[1]) + ",'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') ESCAPE ''", sql)
        item['postgres'] = sql
