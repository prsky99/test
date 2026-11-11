"""Bounded native PostgreSQL scheduling for the current collector contract.

Only fixed predicates and source-owned identifiers form SQL. Values stay bound;
readiness queries do not reserve an external call. Observation tokens remain the
authority checked immediately before work and again when committing its bundle.
"""
import math
import threading
import time

from .observation_guards import GuardError

MAX_COLLECTOR_ROWS = 5000
MAX_COLLECTOR_BYTES = 32 * 1024 * 1024
CAP_BATCH = 1000            # ids ranked at once for the capability survey (11-11)
CAP_BATCH_SECONDS = 300     # a batch older than this is ranked again
_CAP_BATCH_LOCK = threading.Lock()


def _invalid():
    from .application_store_postgres import ApplicationStoreError
    raise ApplicationStoreError('invalid_parameters')


def _number(value):
    if type(value) not in (int, float) or not 0 <= value < 2**53 or not math.isfinite(value): _invalid()
    return value


def _limit(value):
    if type(value) is not int or not 1 <= value <= MAX_COLLECTOR_ROWS: _invalid()
    return value


def _kind(value):
    if type(value) is not str or not 1 <= len(value) <= 64 or '\0' in value: _invalid()
    return value


class PostgresCollectorMixin:
    def health_host_sizes(self):
        """A bounded two-column aggregate may span the full catalog's hosts."""
        with self.tx(readonly=True):
            return self._execute("""SELECT host,COUNT(*) AS n FROM resources
                WHERE active=1 AND health_status!='retired' GROUP BY host""",
                max_rows=200000, max_bytes=32 * 1024 * 1024).fetchall()

    def _collector_rows(self, sql, params=()):
        with self.tx(readonly=True):
            rows = self._execute(sql, params, max_rows=MAX_COLLECTOR_ROWS,
                max_bytes=MAX_COLLECTOR_BYTES).fetchall()
        return [{key: row[key] for key in row.keys() if key != 'rn'} for row in rows]

    def due_for_check(self, now, limit, per_host=None, kind=None):
        _number(now); _limit(limit)
        if per_host is not None: _limit(per_host)
        conditions = ["active=1", "health_status!='retired'"]
        params = []
        if isinstance(kind, (list, tuple)):
            if len(kind) > 16: _invalid()
            if kind:
                params.extend(_kind(value) for value in kind)
                conditions.append('kind IN (' + ','.join(['%s'] * len(kind)) + ')')
        elif kind is not None and kind != '':
            _kind(kind)
            if kind == 'x402': conditions.append("(kind='x402' OR kind NOT IN ('a2a','mcp') OR kind IS NULL)")
            else: conditions.append('kind=%s'); params.append(kind)
        conditions.append('(next_check_at IS NULL OR next_check_at<=%s)'); params.append(now)
        where = ' AND '.join(conditions)
        order = 'next_check_at IS NOT NULL,next_check_at'
        if per_host is None:
            sql = 'SELECT * FROM resources WHERE ' + where + ' ORDER BY ' + order + ',random() LIMIT %s'
        else:
            sql = 'SELECT * FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY host ORDER BY ' + order + \
                ') AS rn FROM resources WHERE ' + where + ') AS candidates WHERE rn<=%s ORDER BY ' + order + ',random() LIMIT %s'
            params.append(per_host)
        return self._collector_rows(sql, params + [limit])

    def due_for_scavenge(self, now, limit=50, per_host=1):
        _number(now); _limit(limit); _limit(per_host)
        return self._collector_rows('''SELECT * FROM (
            SELECT *,ROW_NUMBER() OVER(PARTITION BY host ORDER BY next_check_at IS NOT NULL,next_check_at) AS rn
            FROM resources WHERE (active=1 OR inactive_reason IN ('unhealthy:retired','unhealthy:down'))
            AND health_status='retired' AND next_check_at IS NOT NULL AND next_check_at<=%s
            ) AS candidates WHERE rn<=%s ORDER BY next_check_at IS NOT NULL,next_check_at LIMIT %s''', (now, per_host, limit))

    def activate_revived_resource(self, rid):
        _number(rid)
        with self.tx():
            return self._execute(
                'UPDATE resources SET active=1, inactive_reason=NULL WHERE id=%s',
                (rid,)).rowcount

    def scavenger_stats(self, *, read_db=None):
        now = time.time()
        with self.tx(readonly=True):
            p2 = self._execute("""SELECT COUNT(*) AS n FROM resources
                WHERE (active=1 OR inactive_reason IN ('unhealthy:retired','unhealthy:down'))
                AND health_status='retired' AND (%s - failing_since) < 30 * 86400""", (now,)).fetchone()['n']
            p3 = self._execute("""SELECT COUNT(*) AS n FROM resources
                WHERE (active=1 OR inactive_reason IN ('unhealthy:retired','unhealthy:down'))
                AND health_status='retired' AND (%s - failing_since) BETWEEN 30 * 86400 AND 90 * 86400""", (now,)).fetchone()['n']
            p4 = self._execute("""SELECT COUNT(*) AS n FROM resources
                WHERE (active=1 OR inactive_reason IN ('unhealthy:retired','unhealthy:down'))
                AND health_status='retired' AND (%s - failing_since) >= 90 * 86400""", (now,)).fetchone()['n']
            due = self._execute("""SELECT COUNT(*) AS n FROM resources
                WHERE (active=1 OR inactive_reason IN ('unhealthy:retired','unhealthy:down'))
                AND health_status='retired' AND next_check_at <= %s""", (now,)).fetchone()['n']
            total = self._execute("""SELECT COUNT(*) AS n FROM resources
                WHERE (active=1 OR inactive_reason IN ('unhealthy:retired','unhealthy:down'))
                AND health_status='retired'""").fetchone()['n']
        return {"total_retired": total, "phase2_weekly": p2, "phase3_monthly": p3, "phase4_tombstone": p4, "due_for_scavenge": due}

    def due_for_capability(self, now, max_age, limit, per_host=2, kind='mcp'):
        _number(now); _number(max_age); _limit(limit); _limit(per_host); _kind(kind)
        # Rank narrow columns only, then read the chosen rows. Sorting whole rows (106k A2A
        # listings, ~2.7 KB each) spilled ~180 MB to disk and passed the 5 s statement timeout
        # under load (11-10 13:28); the narrow ranking stays in memory (601 -> 310 ms).
        # 11-11: the ranking still read ~107k blocks per call, 18-26 calls a minute, for a few rows
        # each. One ranking now fills a batch of CAP_BATCH ids that later calls take from, until it is
        # empty or CAP_BATCH_SECONDS old. Ids are taken under a lock, so one process never hands the
        # same id out twice; only the jobs collector calls this. Taken rows are read again and kept
        # only while still due.
        cutoff = now - max_age
        key = (kind, per_host)
        batches = self.__dict__.setdefault('_cap_batches', {})
        served = []
        with _CAP_BATCH_LOCK:
            batch, fresh = batches.get(key), False
            while len(served) < limit:
                if batch is None or now - batch[0] > CAP_BATCH_SECONDS or not batch[1]:
                    if fresh or served:
                        break   # ranked during this call and nothing left, or a partial answer is enough
                    batch, fresh = (now, [row['id'] for row in self._collector_rows('''SELECT id FROM (
            SELECT id,cap_checked_at,ROW_NUMBER() OVER(PARTITION BY host ORDER BY cap_checked_at IS NOT NULL,cap_checked_at) AS rn
            FROM resources WHERE active=1 AND kind=%s AND health_status='healthy'
            AND (cap_checked_at IS NULL OR cap_checked_at<%s)) AS candidates
            WHERE rn<=%s ORDER BY cap_checked_at IS NOT NULL,cap_checked_at,random() LIMIT %s''',
                        (kind, cutoff, per_host, max(limit, CAP_BATCH)))]), True
                    batches[key] = batch
                    if not batch[1]:
                        break
                chunk = [batch[1].pop(0) for _ in range(min(limit - len(served), len(batch[1])))]
                rows = {row['id']: row for row in self._collector_rows(
                    'SELECT * FROM resources WHERE id IN (' + ','.join(['%s'] * len(chunk)) + ')', tuple(chunk))}
                for rid in chunk:
                    row = rows.get(rid)
                    checked = row.get('cap_checked_at') if row else None
                    if (row and row.get('active') == 1 and row.get('kind') == kind and row.get('health_status') == 'healthy'
                            and (checked is None or checked < cutoff)):
                        served.append(row)
        return served

    def due_for_auth(self, now, max_age, limit, per_host=1):
        _number(now); _number(max_age); _limit(limit); _limit(per_host)
        return self._collector_rows('''SELECT * FROM (
            SELECT *,ROW_NUMBER() OVER(PARTITION BY host ORDER BY auth_checked_at IS NOT NULL,auth_checked_at) AS rn
            FROM resources WHERE active=1 AND kind='mcp' AND health_status NOT IN ('down','retired')
            AND COALESCE(auth_observed,auth_declared)=1 AND (auth_checked_at IS NULL OR auth_checked_at<%s)
            ) AS candidates WHERE rn<=%s ORDER BY auth_checked_at IS NOT NULL,auth_checked_at,random() LIMIT %s''',
            (now - max_age, per_host, limit))

    def due_for_static_evaluation(self, now, max_age, limit):
        _number(now); _number(max_age); _limit(limit)
        return self._collector_rows('''SELECT * FROM resources WHERE active=1 AND kind='mcp'
            AND health_status NOT IN ('down','retired') AND COALESCE(auth_observed,auth_declared,0)=1
            AND COALESCE(auth_scope,'connection')!='tool' AND (eval_at IS NULL OR eval_at<%s)
            ORDER BY eval_at IS NOT NULL,eval_at LIMIT %s''', (now - max_age, limit))

    def evaluate_x402_batch(self, limit=5000):
        from .collector.evaluation import POLICY_WINDOW_DAYS, apply_quality_policy, evaluate_x402
        _limit(limit)
        rows = self._collector_rows('''SELECT * FROM resources WHERE active=1 AND kind='x402'
            AND health_status!='retired' AND (eval_at IS NULL OR eval_at<%s)
            ORDER BY eval_at IS NOT NULL,eval_at LIMIT %s''', (int(time.time()) - 86400, limit))
        accepted = 0
        counts = self.health_counts([row['id'] for row in rows], time.time() - POLICY_WINDOW_DAYS * 86400) if rows else {}
        for resource in rows:
            try:
                token = self.observation_guard(resource['id'], 'evaluation', expected_resource=resource)
                value = apply_quality_policy(resource, evaluate_x402(resource, now=time.time()), counts.get(resource['id']))
                with self.observation_transaction(token): self.record_evaluation(resource['id'], value)
                accepted += 1
            except GuardError: continue
        return accepted

    def health_counts(self, ids, since):
        _number(since)
        if type(ids) is not list or len(ids) > MAX_COLLECTOR_ROWS or any(type(value) is not int or not 0 < value < 2**63 for value in ids): _invalid()
        counts = {}
        for start in range(0, len(ids), 200):  # a statement binds at most 256 values
            chunk = ids[start:start + 200]
            rows = self._collector_rows('''SELECT resource_id,COUNT(*) AS n,
                SUM(CASE WHEN outcome IN ('healthy','reachable') THEN 1 ELSE 0 END) AS ok
                FROM health_checks WHERE at>%s AND resource_id IN (''' + ','.join(['%s'] * len(chunk)) + ''')
                GROUP BY resource_id''', (since, *chunk))
            counts.update({row['resource_id']: (row['n'], row['ok'] or 0) for row in rows})
        return counts

    def quality_policy_batch(self, limit=500):
        import json
        from .application_store_postgres import ApplicationStoreError
        from .collector.evaluation import POLICY_VERSION, POLICY_WINDOW_DAYS, apply_quality_policy
        _limit(limit)
        if self.get_meta('quality_policy_done') == POLICY_VERSION:
            return 0
        cursor = self.get_meta('quality_policy_cursor') or {}
        after = cursor.get('id', 0) if cursor.get('version') == POLICY_VERSION else 0
        sql = '''SELECT * FROM resources WHERE id>%s AND active=1
            AND kind IN ('mcp','a2a','x402') AND eval_score IS NOT NULL ORDER BY id LIMIT %s'''
        while True:
            # Large details can push 500 full rows past the 32 MB result cap; halve until it fits.
            try:
                rows = self._collector_rows(sql, (after, limit))
                break
            except ApplicationStoreError as error:
                if str(error) != 'result_limit': raise
                if limit > 1:
                    limit //= 2
                    continue
                skip = self._collector_rows('''SELECT id FROM resources WHERE id>%s AND active=1
                    AND kind IN ('mcp','a2a','x402') AND eval_score IS NOT NULL ORDER BY id LIMIT 1''', (after,))
                self.set_meta('quality_policy_cursor', {'version': POLICY_VERSION, 'id': skip[0]['id'], 'changed': 0})
                return 1
        if not rows:
            self.set_meta('quality_policy_done', POLICY_VERSION)
            return 0
        counts = self.health_counts([row['id'] for row in rows], time.time() - POLICY_WINDOW_DAYS * 86400)
        changed = 0
        for resource in rows:
            try: ev = json.loads(resource.get('eval_info') or 'null')
            except ValueError: continue
            new = apply_quality_policy(resource, ev, counts.get(resource['id']))
            if new is ev: continue
            try:
                token = self.observation_guard(resource['id'], 'evaluation', expected_resource=resource)
                with self.observation_transaction(token): self.record_evaluation(resource['id'], {**new, 'at': time.time()})
                changed += 1
            except GuardError: continue
        self.set_meta('quality_policy_cursor', {'version': POLICY_VERSION, 'id': rows[-1]['id'], 'changed': changed})
        return len(rows)

    def score_percentile(self, score, kind='mcp'):
        if type(score) not in (int, float) or not -2**63 <= score < 2**63 or not math.isfinite(score): _invalid()
        _kind(kind)
        with self.tx(readonly=True):
            row = self._execute('''SELECT COUNT(*) AS n,SUM(CASE WHEN eval_score<%s THEN 1 ELSE 0 END) AS lower
                FROM resources WHERE active=1 AND kind=%s AND eval_score IS NOT NULL''', (score, kind)).fetchone()
        return round((row['lower'] or 0) / row['n'], 3) if row['n'] >= 20 else None

    def postpone(self, ids, at):
        _number(at)
        if type(ids) is not list or len(ids) > MAX_COLLECTOR_ROWS or any(type(value) is not int or not 0 < value < 2**63 for value in ids): _invalid()
        with self.tx():
            for identity in ids:
                self._execute('UPDATE resources SET next_check_at=%s WHERE id=%s', (at, identity))

    def deactivate_unseen(self, source, before):
        self.mark_registry_unseen(source, before)
        return 0

    def mark_registry_unseen(self, source, before):
        if type(source) is not str or not source or len(source) > 256 or '\0' in source: _invalid()
        _number(before)
        now = time.time()
        total = 0
        while True:
            with self.tx():
                updated = self._execute('''UPDATE resources SET registry_missing_since=%s
                    WHERE id IN (
                        SELECT id FROM resources
                        WHERE source=%s AND last_seen<%s AND registry_missing_since IS NULL
                        LIMIT 1000
                        FOR UPDATE SKIP LOCKED
                    )''', (now, source, before)).rowcount
                total += updated
                if updated == 0:
                    break
        return total

    def evaluation_stats(self, kind=None):
        where = "FROM resources WHERE active=1 AND health_status!='retired' AND eval_at IS NOT NULL"
        params = []
        if kind in ('mcp', 'a2a', 'x402'): where += ' AND kind=%s'; params.append(kind)
        with self.tx(readonly=True):
            row = self._execute('SELECT COUNT(*) AS n,AVG(eval_score) AS avg,SUM((eval_at>%s)::integer) AS last_24h ' + where,
                [int(time.time()) - 86400] + params).fetchone()
            groups = {}
            for name, expression in (('by_grade', "COALESCE(eval_grade,'static')"), ('by_security', 'eval_security'), ('by_coverage', 'eval_coverage')):
                groups[name] = {r['value']: r['n'] for r in self._execute('SELECT ' + expression + ' AS value,COUNT(*) AS n ' + where +
                    ' GROUP BY ' + expression + ' ORDER BY ' + expression, params).fetchall()}
        return {'evaluated': row['n'], 'evaluated_24h': row['last_24h'] or 0,
            'average_score': round(row['avg'], 1) if row['avg'] is not None else None, **groups}

    def collector_stats(self):
        with self.tx(readonly=True):
            status = {r['health_status']: r['n'] for r in self._execute(
                'SELECT health_status,COUNT(*) AS n FROM resources WHERE active=1 GROUP BY health_status').fetchall()}
            checked = self._execute("SELECT COUNT(*) AS n,SUM((outcome IN ('healthy','reachable'))::integer) AS ok FROM health_checks WHERE at>%s",
                (time.time() - 3600,)).fetchone()
            overdue = self._execute("SELECT COUNT(*) FROM resources WHERE active=1 AND health_status!='retired' AND (next_check_at IS NULL OR next_check_at<%s)",
                (time.time() - 3600,)).fetchone()[0]
            runs = [dict(row) for row in self._execute('SELECT * FROM crawl_runs ORDER BY at DESC LIMIT 10').fetchall()]
            constraints = dict(self._execute('''SELECT
                SUM((COALESCE(auth_observed,auth_declared)=1)::integer) AS auth_required,
                SUM((COALESCE(auth_observed,auth_declared)=0)::integer) AS auth_free,
                SUM((COALESCE(auth_observed,auth_declared) IS NULL)::integer) AS auth_unknown,
                SUM((regions IS NOT NULL OR cap_regions IS NOT NULL)::integer) AS region_specific,
                SUM((cap_checked_at IS NOT NULL AND cap_error IS NULL)::integer) AS capabilities_checked,
                SUM((cap_languages IS NOT NULL)::integer) AS with_language_options,
                SUM((auth_method IS NOT NULL)::integer) AS auth_method_known,
                SUM((auth_autonomy='agent_autonomous')::integer) AS auth_agent_autonomous,
                SUM((usage_guide IS NOT NULL)::integer) AS usage_guides,
                SUM((trial_ok=1)::integer) AS verified_working,SUM((trial_ok=0)::integer) AS trial_failed,
                SUM((usage_changes IS NOT NULL AND usage_updated_at>%s)::integer) AS usage_changed_24h
                FROM resources WHERE active=1 AND health_status!='retired' ''', (int(time.time()) - 86400,)).fetchone())
            languages = {r['desc_lang']: r['n'] for r in self._execute('SELECT desc_lang,COUNT(*) AS n FROM resources WHERE active=1 AND desc_lang IS NOT NULL GROUP BY desc_lang ORDER BY n DESC LIMIT 10').fetchall()}
            methods = {r['auth_method']: r['n'] for r in self._execute('SELECT auth_method,COUNT(*) AS n FROM resources WHERE active=1 AND auth_method IS NOT NULL GROUP BY auth_method').fetchall()}
            return {'active_agents': sum(status.values()), 'by_health': status, 'by_kind_category': self.resource_counts(),
                'checks_last_hour': {'total': checked['n'], 'ok': checked['ok'] or 0}, 'overdue_over_1h': overdue,
                'recent_crawls': runs, 'constraints': {**{key: value or 0 for key, value in constraints.items()},
                    'description_languages': languages, 'auth_methods': methods}, 'evaluation': self.evaluation_stats(),
                'evaluation_by_kind': {kind: self.evaluation_stats(kind) for kind in ('mcp', 'a2a', 'x402')},
                'agent_sources': self.agent_source_stats()}

    def collector_agents(self, *, query=None, category=None, kind=None, status=None,
                         language=None, region=None, auth=None, verified=None,
                         min_grade=None, security=None, sort=None, limit=20):
        """Named collector listing; predicates are fixed, values remain bound."""
        import json
        from .gateway.classify import query_terms
        from .application_store_postgres import ApplicationStoreError, MAX_CORPUS_ROWS
        if type(limit) is not int or not 1 <= limit <= 100 or verified is not None and type(verified) is not bool:
            raise ApplicationStoreError('invalid_parameters')
        for value in (query, category, kind, status, language, region, auth, min_grade, security, sort):
            if value is not None and (type(value) is not str or '\0' in value or len(value.encode()) > 4096):
                raise ApplicationStoreError('invalid_parameters')
        conditions, params = ['r.active=1'], []
        if min_grade:
            if min_grade.upper() not in ('A','B','C','D','F'): raise ApplicationStoreError('invalid_parameters')
            grades='ABCDF'[:'ABCDF'.index(min_grade.upper())+1]
            conditions.append('r.eval_grade IN ('+','.join('%s' for _ in grades)+')');params.extend(grades)
        if security:
            if security not in ('ok','review','quarantine','unknown'): raise ApplicationStoreError('invalid_parameters')
            conditions.append('r.eval_security=%s');params.append(security)
        def like(field):
            return "translate("+field+",'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') LIKE translate(%s,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz') ESCAPE ''"
        if language:
            conditions.append('('+like('r.cap_languages')+' OR r.desc_lang=%s)');params.extend(['%,'+language+',%',language])
        if region:
            conditions.append('('+like('r.regions')+' OR '+like('r.cap_regions')+')');params.extend(['%,'+region+',%']*2)
        if verified is not None:conditions.append('r.trial_ok=%s');params.append(int(verified))
        if auth=='none':conditions.append('COALESCE(r.auth_observed,r.auth_declared,0)=0')
        elif auth=='agent':conditions.append("(COALESCE(r.auth_observed,r.auth_declared,0)=0 OR r.auth_autonomy='agent_autonomous')")
        elif auth in ('oauth2','api_key','bearer','basic'):conditions.append('r.auth_method=%s');params.append(auth)
        for field,value in (('category',category),('kind',kind),('health_status',status)):
            if value:conditions.append('r.'+field+'=%s');params.append(value)
        if not status:conditions.append("r.health_status!='retired'")
        terms=query_terms(query or '',limit=16)
        with self.tx(readonly=True):
            prefix='';tables='resources r'
            if terms:
                match=' OR '.join('"'+term.replace('"','')+'"' for term in terms)
                rows=self._fts().execute('SELECT rowid,bm25(documents) FROM documents WHERE documents MATCH ?',(match,)).fetchall()
                if len(rows)>MAX_CORPUS_ROWS:raise ApplicationStoreError('result_limit')
                prefix='WITH matches AS (SELECT (value->>0)::bigint AS id,(value->>1)::double precision AS rank FROM json_array_elements(%s::json)) '
                params.insert(0,json.dumps([list(row) for row in rows],separators=(',',':'),allow_nan=False))
                tables+=' JOIN matches m ON m.id=r.id'
            if sort=='quality':
                conditions.append('r.eval_score IS NOT NULL');order='r.eval_score DESC,COALESCE(r.payers_30d,0) DESC'
            else:order='m.rank,r.id' if terms else 'COALESCE(r.payers_30d,0) DESC'
            return [dict(row) for row in self._execute(prefix+'SELECT r.* FROM '+tables+' WHERE '+' AND '.join(conditions)
                +' ORDER BY '+order+' LIMIT %s',params+[limit]).fetchall()]
